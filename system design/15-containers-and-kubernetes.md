# Chapter 15 — Containers & Kubernetes 🟡

> You do not need to become a Kubernetes administrator.
> You need to understand **why each object exists**, what problem it solves, and where the sharp edges are — so you can design systems that run well on it and know when *not* to use it.

---

# PART 1 — Containers

## 15.1 What a container actually is

A container is **not** a lightweight VM. That analogy causes real misunderstandings.

```
VIRTUAL MACHINES                    CONTAINERS
┌────────┬────────┬────────┐        ┌────────┬────────┬────────┐
│ App A  │ App B  │ App C  │        │ App A  │ App B  │ App C  │
├────────┼────────┼────────┤        ├────────┼────────┼────────┤
│Guest OS│Guest OS│Guest OS│        │  libs  │  libs  │  libs  │
│ (2 GB) │ (2 GB) │ (2 GB) │        └────────┴────────┴────────┘
├────────┴────────┴────────┤        ┌──────────────────────────┐
│       Hypervisor         │        │   Container runtime      │
├──────────────────────────┤        ├──────────────────────────┤
│        Host OS           │        │   Host OS (SHARED KERNEL)│
├──────────────────────────┤        ├──────────────────────────┤
│        Hardware          │        │        Hardware          │
└──────────────────────────┘        └──────────────────────────┘
  Boot: ~60 s, GB of RAM              Boot: ~50 ms, MB of RAM
  Strong isolation                    Weaker isolation (shared kernel)
```

**A container is just a Linux process** with three kernel features applied:

| Feature | What it does |
|---------|-------------|
| **Namespaces** | The process sees its own PIDs, network, mounts, hostname, users — it cannot see the host's |
| **cgroups** | Limits how much CPU, memory and I/O it may consume |
| **Union filesystem** | Layered, copy-on-write filesystem so images are small and shareable |

**The architectural consequences of "shared kernel":**
- A kernel vulnerability can potentially escape a container — this is why untrusted multi-tenant workloads use VMs, microVMs (Firecracker), or gVisor
- Containers cannot run a different OS kernel (no Linux containers on a Windows kernel without a Linux VM underneath)
- Startup is fast because there is no OS to boot

### What containers actually solve

1. **"Works on my machine"** — the image contains the dependencies, so dev/CI/prod are identical
2. **Density** — dozens of containers on one host rather than a handful of VMs
3. **Fast start** — milliseconds, which is what makes autoscaling responsive
4. **Immutable deployments** — you ship an artefact, not a series of commands run on a server
5. **Portability** — the same image runs on a laptop, a VM, Kubernetes, or a serverless container platform

> The biggest of these is **immutability**. A container image is built once and promoted unchanged through environments. That eliminates configuration drift — the source of an enormous share of "it worked in staging" incidents.

## 15.2 Images and layers

```dockerfile
FROM python:3.12-slim          # layer 1 — base OS + Python
WORKDIR /app
COPY requirements.txt .        # layer 2
RUN pip install -r requirements.txt   # layer 3 — the expensive one
COPY . .                       # layer 4 — changes on every commit
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

**Layers are cached and shared.** Ten containers from the same base image store that base **once**.

**Layer ordering is the single most impactful Dockerfile skill:** put things that change rarely first. In the example above, `requirements.txt` is copied before the source, so a code change does not invalidate the dependency-install layer. Getting this wrong turns a 10-second build into a 4-minute one, on every commit.

### Multi-stage builds — do this always

```dockerfile
# ---- Build stage: has compilers, dev dependencies, source ----
FROM python:3.12 AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- Runtime stage: ONLY what is needed to run ----
FROM python:3.12-slim
RUN groupadd -r app && useradd -r -g app app        # non-root user
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
    && rm -rf /wheels
COPY --chown=app:app ./app ./app
USER app                                             # never run as root
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Why it matters:** the runtime image has no compiler, no build tools, no source archives. That is smaller (faster pulls, faster scaling) **and** a much smaller attack surface. A typical multi-stage build takes an image from 1.2 GB to 180 MB.

### Image security rules 🟢

```
✅ Pin base images by digest, not by a floating tag
   FROM python:3.12-slim@sha256:abc123...
✅ Use minimal bases: slim, alpine, distroless, or scratch for static binaries
✅ Run as a non-root user (and set runAsNonRoot in Kubernetes)
✅ Scan images in CI (Trivy, Grype, Snyk) and FAIL the build on CRITICAL
✅ Never bake secrets into images — layers are permanent and extractable
✅ Rebuild regularly — a 6-month-old image has 6 months of unpatched CVEs
✅ Sign images (cosign) and verify signatures at admission
✅ Generate an SBOM so you can answer "are we affected by CVE-X?" in minutes
```

> **The `latest` tag is an anti-pattern.** It is not reproducible: the same manifest deploys different code on different days, and rollback becomes guesswork. Tag with the git SHA and deploy by digest.

---

# PART 2 — Kubernetes

## 15.3 What problem Kubernetes solves

You have 40 containers across 12 machines. Someone must:
- Decide which container runs on which machine (**scheduling**)
- Restart containers that crash (**self-healing**)
- Add or remove replicas as load changes (**autoscaling**)
- Give containers stable addresses as they move (**service discovery**)
- Roll out new versions without downtime (**deployments**)
- Distribute config and secrets
- Enforce resource limits so one container cannot starve others

Doing that by hand does not survive contact with reality. **Kubernetes is a control loop that continuously makes reality match your declared desired state.**

```
        ┌──────────────────────────────────────────┐
        │  You declare:  "I want 3 replicas"        │
        └───────────────────┬──────────────────────┘
                            ▼
        ┌──────────────────────────────────────────┐
        │  Controller: observe → compare → act      │
        │  "I see 2. I need 3. Create one."         │
        │  (forever, every few seconds)             │
        └──────────────────────────────────────────┘
```

**That reconciliation loop is the one idea that explains all of Kubernetes.** Everything else is an object that some controller reconciles.

## 15.4 The objects that matter 🟢

### Pod — the unit of deployment

One or more containers that **share a network namespace and storage**, always scheduled together.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: verification-api
spec:
  containers:
    - name: api
      image: registry/verification-api@sha256:abc123
      ports: [{ containerPort: 8000 }]
```

**You almost never create a Pod directly** — it has no self-healing. You create a Deployment, which manages ReplicaSets, which manage Pods.

**The sidecar pattern** uses the shared namespace: a second container in the same pod handling logging, a service-mesh proxy, or a credential refresher. Because they share `localhost`, the app talks to `127.0.0.1` and the sidecar handles the rest — this is how service meshes work transparently.

### Deployment — stateless workloads

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verification-api
spec:
  replicas: 3
  selector:
    matchLabels: { app: verification-api }
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }   # never lose capacity
  template:
    metadata:
      labels: { app: verification-api }
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: api
          image: registry/verification-api@sha256:abc123
          ports: [{ containerPort: 8000 }]

          resources:                                    # ⭐ see §15.6
            requests: { cpu: "200m", memory: "256Mi" }
            limits:   { memory: "512Mi" }               # note: no CPU limit

          livenessProbe:                                # process alive?
            httpGet: { path: /health/live, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 15
            failureThreshold: 3

          readinessProbe:                               # ready for traffic?
            httpGet: { path: /health/ready, port: 8000 }
            periodSeconds: 5
            failureThreshold: 2

          startupProbe:                                 # protects slow starters
            httpGet: { path: /health/live, port: 8000 }
            failureThreshold: 30
            periodSeconds: 2

          lifecycle:
            preStop:
              exec: { command: ["sleep", "10"] }        # ⭐ see §15.8

          envFrom:
            - configMapRef: { name: api-config }
            - secretRef:    { name: api-secrets }
```

**ReplicaSet** sits between Deployment and Pod; it exists so a Deployment can run two of them side by side during a rolling update, and so a rollback is just scaling the old one back up.

### Service — a stable address

Pods come and go with new IPs. A Service gives a stable name and IP.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: verification-api
spec:
  selector: { app: verification-api }     # matches pods by LABEL, not by name
  ports: [{ port: 80, targetPort: 8000 }]
  type: ClusterIP
```

Now any pod can call `http://verification-api` and reach a healthy pod.

| Type | Behaviour | Use |
|------|-----------|-----|
| **ClusterIP** | Internal only (default) | Service-to-service |
| **NodePort** | Opens a port on every node | Rarely — mostly for local dev |
| **LoadBalancer** | Provisions a cloud load balancer | One per service gets expensive |
| **ExternalName** | A DNS CNAME | Pointing at an external service |
| **Headless** (`clusterIP: None`) | DNS returns all pod IPs | StatefulSets, client-side load balancing |

> **Important:** a Service load-balances **connections**, not requests. For HTTP/2 and gRPC (one long-lived connection), all requests pin to one pod (Chapter 13 §13.6). You need an L7 proxy, a service mesh, or client-side load balancing over a headless service.

### Ingress / Gateway API — HTTP routing from outside

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts: [api.example.com]
      secretName: api-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /v1/verification
            pathType: Prefix
            backend: { service: { name: verification-api, port: { number: 80 } } }
          - path: /v1/billing
            pathType: Prefix
            backend: { service: { name: billing-api, port: { number: 80 } } }
```

One load balancer, many services, TLS terminated centrally. **Gateway API** is the newer, more expressive replacement (role-separated, supports header/weight routing natively) — it is where the ecosystem is heading.

### ConfigMap and Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: api-config }
data:
  LOG_LEVEL: "info"
  MAX_ATTEMPTS: "3"
  VENDOR_TIMEOUT_MS: "8000"
```

> **Kubernetes Secrets are base64-encoded, not encrypted, by default.** Anyone with read access to the namespace can decode them, and they sit in etcd. Enable **encryption at rest for etcd**, restrict RBAC, and for anything serious use an external secret store (External Secrets Operator + a cloud secrets manager, or Vault) so the real secret never lives in the cluster.

### StatefulSet — for stateful workloads

```
Deployment pods:   api-7d8f9-x4k2l, api-7d8f9-p9m3n   (random, interchangeable)
StatefulSet pods:  postgres-0, postgres-1, postgres-2  (stable, ordered, persistent)
```

Gives: stable network identity, stable persistent storage per pod, ordered startup and shutdown.

> **The honest advice: do not run production databases on Kubernetes unless you have a team that wants to own that.** Managed database services exist precisely because storage, failover, backup and upgrade are hard. Operators (CloudNativePG, Strimzi) have made it *possible* and genuinely good — but it is still a decision to make consciously, not by default.

### Job and CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: purge-expired-videos }
spec:
  schedule: "0 3 * * *"
  concurrencyPolicy: Forbid          # never overlap runs
  successfulJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 3
      activeDeadlineSeconds: 3600    # kill it if it runs over an hour
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: purge
              image: registry/maintenance@sha256:...
              args: ["purge-videos", "--older-than=90d"]
```

`concurrencyPolicy: Forbid` and `activeDeadlineSeconds` are the two settings people forget — without them, a slow job spawns overlapping copies until the cluster is full.

### DaemonSet

One pod on every node. For node-level agents: log collectors (Fluent Bit), metrics (node-exporter), security agents, CNI components.

### Namespace

Logical partitioning with its own RBAC, resource quotas and network policies. Use for environments (in small clusters), teams, or tenants.

> **Namespaces are not a security boundary strong enough for untrusted multi-tenancy.** They share a kernel, a control plane and often nodes. For hostile tenants, use separate clusters or sandboxed runtimes.

---

## 15.5 Networking in Kubernetes 🟡

**The model:** every pod gets its own IP, and every pod can reach every other pod **without NAT** — across nodes.

```
Pod A (10.244.1.5) on Node 1  ──────►  Pod B (10.244.2.8) on Node 2
                   (flat network, implemented by the CNI plugin)
```

**Consequence: by default, everything can talk to everything.** Locking it down requires NetworkPolicy (Chapter 13 §13.8) — start default-deny per namespace.

### Service mesh 🟡

A sidecar proxy next to every pod, intercepting all traffic.

```
┌──────────────────────┐        ┌──────────────────────┐
│  Pod A               │        │  Pod B               │
│  ┌──────┐ ┌────────┐ │        │ ┌────────┐ ┌──────┐  │
│  │ app  │►│ proxy  │─┼──mTLS──┼►│ proxy  │►│ app  │  │
│  └──────┘ └────────┘ │        │ └────────┘ └──────┘  │
└──────────────────────┘        └──────────────────────┘
```

**What it gives you without changing application code:**
- **mTLS everywhere** with automatic certificate rotation (zero trust, Chapter 17)
- Retries, timeouts, circuit breaking, outlier detection (Chapter 05) — configured, not coded
- **L7 load balancing** — which fixes the gRPC/HTTP2 pinning problem
- Traffic splitting for canary releases
- Automatic golden metrics and distributed tracing headers

**What it costs:** an extra proxy per pod (CPU, memory, a few ms of latency), a significant new system to understand and debug, and a control plane to run.

> **Rule of thumb: consider a mesh at ~20+ services, or when mTLS is a hard compliance requirement.** Below that, libraries (Polly, Resilience4j) and an ingress controller do the job with far less machinery. **Linkerd** is markedly simpler than Istio and is the right starting point for most teams. Newer "ambient"/sidecar-less modes reduce the overhead considerably.

---

## 15.6 Resources, limits and QoS — where most production pain lives 🟢

```yaml
resources:
  requests:              # GUARANTEED — used for scheduling
    cpu: "200m"          # 0.2 of a core
    memory: "256Mi"
  limits:                # CEILING — enforced at runtime
    memory: "512Mi"
```

### The two behave completely differently — this is the key insight

| | **CPU** | **Memory** |
|---|---|---|
| Over the limit | **Throttled** (slowed down) | **OOM-killed** (process terminated) |
| Compressible? | Yes | **No** |
| Effect of a too-low limit | Latency spikes, mysterious p99 | Crash loops |

> **Practical guidance that contradicts many defaults:**
> - **Always set memory requests AND limits, equal to each other** for predictable behaviour
> - **Set CPU requests, but consider omitting CPU limits.** CPU throttling via CFS quota causes severe, hard-to-diagnose latency spikes even when the node has idle CPU. Many experienced teams set CPU requests only, and rely on requests for fair sharing.
> - Right-size from real usage (Vertical Pod Autoscaler in recommendation mode, or Prometheus data). Guessed values are almost always 3× too high or dangerously too low.

### QoS classes — who gets evicted first

| Class | Condition | Eviction order |
|-------|-----------|---------------|
| **Guaranteed** | requests == limits for every container | Evicted **last** |
| **Burstable** | requests < limits | Evicted second |
| **BestEffort** | no requests or limits | **Evicted first** |

Production workloads should be Guaranteed or Burstable. **A BestEffort pod is the first thing killed when a node is under pressure** — never run anything important that way.

### Autoscaling — three kinds

```yaml
# HPA — horizontal: more pods
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: verification-api }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: verification-api }
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }
  behavior:
    scaleUp:   { stabilizationWindowSeconds: 0,   policies: [{ type: Percent, value: 100, periodSeconds: 30 }] }
    scaleDown: { stabilizationWindowSeconds: 300, policies: [{ type: Percent, value: 25,  periodSeconds: 60 }] }
```

| Type | Scales | Notes |
|------|--------|-------|
| **HPA** | Number of pods | The main one. **Scale up fast, down slowly.** |
| **VPA** | CPU/memory per pod | Use in recommendation mode; auto mode restarts pods |
| **Cluster Autoscaler / Karpenter** | Number of nodes | Needed, or HPA creates pods that cannot be scheduled |
| **KEDA** ⭐ | Pods, from **any** event source | **Queue depth is a far better scaling signal than CPU** for workers |

```yaml
# KEDA — scale GPU workers on queue depth, not CPU. This is the right signal.
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
spec:
  scaleTargetRef: { name: verification-worker }
  minReplicaCount: 1
  maxReplicaCount: 20
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: https://sqs.../verification-jobs
        queueLength: "5"          # one pod per 5 queued messages
```

> **Scaling a queue consumer on CPU is a classic mistake** — the worker is often I/O-bound, so CPU stays low while the backlog grows for an hour. Scale on the backlog.

---

## 15.7 Probes — get these right 🟢

(Introduced in Chapter 04; here are the Kubernetes specifics and the disasters.)

| Probe | Question | Failure action |
|-------|----------|---------------|
| **Startup** | Has it finished booting? | Keeps liveness/readiness from firing too early |
| **Liveness** | Is the process healthy? | **Restart the container** |
| **Readiness** | Can it serve traffic now? | **Remove from the Service endpoints** (no restart) |

```python
@app.get("/health/live")
async def live():
    # Process-level ONLY. No dependencies. No database. No external calls.
    return {"status": "ok"}

@app.get("/health/ready")
async def ready(db=Depends(get_db), cache=Depends(get_cache)):
    checks = {"database": await db.ping(), "cache": await cache.ping()}
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)
```

### The three classic probe disasters

1. **Liveness checks the database.** The DB blips for 30 seconds → every pod fails liveness → Kubernetes restarts **all of them at once** → the reconnection stampede keeps the DB down → the cluster never recovers. **Liveness must never check a dependency.**

2. **No startup probe on a slow-starting app.** A JVM app takes 45 s to warm up; liveness fires at 30 s and kills it; it restarts, gets killed again — a permanent crash loop that looks like a code bug.

3. **Readiness that always returns 200.** Traffic goes to a pod that is not ready, and users get 500s during every deploy. Readiness must genuinely reflect readiness.

---

## 15.8 Graceful shutdown — the most-missed detail 🟢

When Kubernetes terminates a pod, two things happen **in parallel**, and that is the problem:

```
t=0    Pod marked Terminating
       ├── Endpoint removal begins (propagates to kube-proxy/ingress) ── takes 1-5 SECONDS
       └── SIGTERM sent to the container                              ── IMMEDIATE

       → During that gap, traffic is STILL being routed to a pod that is shutting down.
       → Users get connection-refused errors during every single deploy.

t=30   SIGKILL (terminationGracePeriodSeconds)
```

**The fix — and it is a two-part fix:**

```yaml
lifecycle:
  preStop:
    exec: { command: ["sleep", "10"] }   # 1. absorb the endpoint-propagation delay
terminationGracePeriodSeconds: 60         # 2. allow long enough for in-flight work
```

```python
# 3. The application must handle SIGTERM properly
async def shutdown():
    app.state.ready = False          # readiness now fails
    await asyncio.sleep(5)           # let load balancers notice
    await server.shutdown()          # stop accepting new connections
    await drain_in_flight(timeout=30)  # finish current requests
    await close_db_pools()
    await close_broker_connections()  # for consumers: finish and ack the current message
```

> **If your deploys cause a spike of 502/503 errors, this is why, and this is the fix.** It is the single most common "our zero-downtime deploy isn't zero-downtime" cause.

**Also essential for availability during node maintenance:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: verification-api }
spec:
  minAvailable: 2                    # or maxUnavailable: 1
  selector:
    matchLabels: { app: verification-api }
```

Without a PDB, a node drain can evict all your replicas simultaneously.

---

## 15.9 Deployment strategies 🟢

### Rolling update (the Kubernetes default)

```
[v1][v1][v1] → [v1][v1][v2] → [v1][v2][v2] → [v2][v2][v2]
```
✅ No extra infrastructure, gradual
❌ Both versions run at once — **your API and database schema must be backward compatible** (expand/contract, Chapter 09)

### Blue-Green

```
Blue  (v1) ◄── 100% traffic          Blue  (v1) ◄── 0%
Green (v2) ◄── 0%          ──────►   Green (v2) ◄── 100%   (switch the Service selector)
```
✅ Instant rollback, one version live at a time, full test before the switch
❌ **2× resources** during the switch; database migrations still need care

### Canary ⭐

```
v1: 95% of traffic     →  v1: 75%  →  v1: 0%
v2:  5% of traffic        v2: 25%     v2: 100%
     ↑ watch error rate and latency at every step; roll back automatically on regression
```
✅ **Real production validation with limited blast radius** — the best risk/reward
❌ Needs traffic splitting (ingress, mesh, or Argo Rollouts/Flagger) and good metrics

```yaml
# Argo Rollouts: automated canary with analysis-based promotion
strategy:
  canary:
    steps:
      - setWeight: 5
      - pause: { duration: 5m }
      - analysis: { templates: [{ templateName: error-rate-check }] }
      - setWeight: 25
      - pause: { duration: 10m }
      - setWeight: 50
      - pause: { duration: 10m }
      - setWeight: 100
```

### Feature flags — decoupling deploy from release ⭐

```python
if await flags.is_enabled("new-liveness-model", tenant_id=tenant.id):
    result = await new_model.score(video)
else:
    result = await legacy_model.score(video)
```

**Deploy the code to everyone; enable the feature for 1%.** This is often *better* than a canary deploy because you can turn a feature off in one second without a rollback, and you can target specific tenants. The cost is flag debt — set an expiry date on every flag and remove it.

> **The mature combination: rolling deploys + feature flags + a small number of canaries for genuinely risky changes.**

---

## 15.10 When NOT to use Kubernetes 🟢

Be honest, because this is a decision that will shape your team's next three years.

❌ **Do not use it when:**
- You have fewer than ~5 services
- Nobody on the team can debug it under pressure
- You have no platform/infra engineer and no budget for one
- A PaaS or serverless containers would work (Chapter 14)
- Your workload is a monolith plus a database

✅ **Use it when:**
- 10+ services with real orchestration needs
- Multi-cloud or hybrid portability genuinely matters
- You need the ecosystem (operators, mesh, GPU scheduling, complex batch)
- You have or are hiring the expertise

### What managed Kubernetes does *not* remove

EKS/AKS/GKE manage the control plane. You still own:
- Cluster **version upgrades** (every 3–4 months, with deprecated-API breakage)
- Node pools, autoscaling, capacity planning
- Ingress controller, cert-manager, DNS
- RBAC, network policies, pod security standards
- Storage classes and CSI drivers
- Observability stack
- Cost management (Kubernetes makes waste invisible by default)
- **Debugging it at 3 AM**

> Budget one engineer's meaningful, ongoing attention. If you cannot, choose serverless containers instead — and there is no shame in that. Many successful companies run entirely on Cloud Run or Fargate.

---

## 15.11 Common mistakes

1. **No resource requests** — pods land anywhere, get evicted first, and node capacity is unknowable
2. **CPU limits causing throttling** — mysterious p99 latency while CPU sits idle
3. **Liveness probe checking the database** — one blip restarts the entire fleet
4. **No graceful shutdown / preStop** — 502s on every deploy
5. **No PodDisruptionBudget** — a node drain takes out all replicas
6. **Using `latest` tags** — unreproducible deploys, impossible rollback
7. **Running as root** — unnecessary privilege in a shared-kernel environment
8. **Secrets in ConfigMaps, or unencrypted etcd** — base64 is not encryption
9. **Default-allow networking** — every pod can reach every database
10. **Running stateful databases on Kubernetes without expertise** — managed services exist for a reason
11. **Scaling queue workers on CPU instead of queue depth**
12. **Adopting a service mesh at 5 services** — more complexity than it removes
13. **Adopting Kubernetes at all with 3 services and no platform engineer**
14. **Deploying with rolling updates while making a breaking schema change** — both versions run simultaneously

---

## 15.12 Architect's checklist

- [ ] Kubernetes decision justified against the "when not to" list, with team capability considered
- [ ] Images: multi-stage, minimal base, non-root, pinned by digest, scanned in CI
- [ ] No secrets in images; external secret store integrated
- [ ] Resource requests set on everything; memory limits == requests; CPU limits considered carefully
- [ ] Liveness, readiness and startup probes distinct and correct (liveness checks nothing external)
- [ ] preStop hook + SIGTERM handling + adequate grace period → verified zero-error deploys
- [ ] PodDisruptionBudgets on all production workloads
- [ ] HPA configured; workers scale on queue depth (KEDA), not CPU
- [ ] Cluster autoscaler/Karpenter in place with a maximum node cap
- [ ] Default-deny NetworkPolicies per namespace
- [ ] Pod Security Standards / admission policy enforced (no privileged, no root, read-only rootfs)
- [ ] RBAC least privilege; no cluster-admin for applications
- [ ] Anti-affinity / topology spread so replicas land in different AZs
- [ ] Deployment strategy chosen; schema changes use expand/contract
- [ ] Rollback tested and documented; someone has actually done it
- [ ] Cost visibility per namespace/team (Kubecost or equivalent)
- [ ] Cluster upgrade plan and cadence agreed

---

## 15.13 Self-test

1. A container is not a lightweight VM. What is it, and what are the three kernel features involved?
2. Why does Dockerfile layer ordering matter? Give the build-time impact.
3. What does a multi-stage build achieve, beyond a smaller image?
4. Explain the reconciliation loop in one sentence. Why does it explain all of Kubernetes?
5. Why do you almost never create a Pod directly?
6. Why do gRPC/HTTP2 calls through a ClusterIP Service pin to one pod, and what fixes it?
7. What happens when a container exceeds its CPU limit? Its memory limit? Why does the difference matter?
8. Explain the three QoS classes and eviction order.
9. Why should liveness never check the database? Describe the failure in full.
10. Why do deploys cause 502s without a preStop hook? Give the complete three-part fix.
11. What is a PodDisruptionBudget and what happens without one?
12. Why is queue depth a better autoscaling signal than CPU for a worker?
13. Compare rolling, blue-green and canary. When is each right?
14. What does managed Kubernetes *not* manage? List six things.

---

## 15.14 Key takeaways

- **A container is a process with namespaces, cgroups and a layered filesystem** — the shared kernel is a security consideration
- **Immutability is the real win** — build once, promote unchanged
- **Kubernetes is one idea: a reconciliation loop** making reality match declared state
- **Resource requests and correct probes are where most production pain originates**
- **CPU throttles, memory kills.** Treat the two limits completely differently.
- **Liveness checks the process; readiness checks dependencies.** Getting this backwards causes cluster-wide outages.
- **preStop + SIGTERM handling + grace period** is the fix for deploy-time 502s
- **Scale workers on queue depth, not CPU**
- **Canary + feature flags** give the best risk/reward for releases
- **Do not run Kubernetes without someone who can debug it at 3 AM** — serverless containers are a legitimate, professional alternative
- **Managed Kubernetes manages the control plane, not the operational burden**

---

**Next:** [Chapter 16 — DevOps & Platform Engineering](16-devops-and-platform-engineering.md)
