# অধ্যায় ১৫ — Container ও Kubernetes 🟡

> আপনাকে একজন Kubernetes প্রশাসক হতে হবে না।
> আপনাকে বুঝতে হবে **প্রতিটা object কেন আছে**, সেটা কোন সমস্যা সমাধান করে, আর ধারালো কিনারাগুলো কোথায় — যাতে আপনি এমন সিস্টেম design করতে পারেন যা এতে ভালো চলে, আর জানেন কখন এটা ব্যবহার **করবেন না**।

---

# পর্ব ১ — Container

## ১৫.১ একটা container আসলে কী

একটা container একটা হালকা VM **নয়**। ওই উপমাটা সত্যিকারের ভুল বোঝাবুঝি ঘটায়।

```
VIRTUAL MACHINE                     CONTAINER
┌────────┬────────┬────────┐        ┌────────┬────────┬────────┐
│ App A  │ App B  │ App C  │        │ App A  │ App B  │ App C  │
├────────┼────────┼────────┤        ├────────┼────────┼────────┤
│Guest OS│Guest OS│Guest OS│        │  lib   │  lib   │  lib   │
│ (২ GB) │ (২ GB) │ (২ GB) │        └────────┴────────┴────────┘
├────────┴────────┴────────┤        ┌──────────────────────────┐
│       Hypervisor         │        │   Container runtime      │
├──────────────────────────┤        ├──────────────────────────┤
│        Host OS           │        │ Host OS (ভাগ করা KERNEL)  │
├──────────────────────────┤        ├──────────────────────────┤
│        Hardware          │        │        Hardware          │
└──────────────────────────┘        └──────────────────────────┘
  Boot: ~৬০ সেকেন্ড, GB RAM           Boot: ~৫০ ms, MB RAM
  শক্তিশালী বিচ্ছিন্নতা                  দুর্বল বিচ্ছিন্নতা (ভাগ করা kernel)
```

**একটা container আসলে একটা Linux process**, যাতে তিনটা kernel feature প্রয়োগ করা:

| Feature | এটা যা করে |
|---------|-------------|
| **Namespace** | Process নিজের PID, network, mount, hostname, user দেখে — host-এরগুলো দেখতে পারে না |
| **cgroup** | এটা কত CPU, memory আর I/O ব্যবহার করতে পারবে তা সীমিত করে |
| **Union filesystem** | স্তরায়িত, copy-on-write filesystem, তাই image ছোট আর ভাগ করার যোগ্য |

**"ভাগ করা kernel"-এর architecture-গত ফলাফল:**
- একটা kernel-এর দুর্বলতা সম্ভাব্যভাবে একটা container থেকে পালাতে পারে — এই কারণেই অবিশ্বস্ত multi-tenant কাজ VM, microVM (Firecracker), বা gVisor ব্যবহার করে
- Container একটা আলাদা OS kernel চালাতে পারে না (নিচে একটা Linux VM ছাড়া Windows kernel-এ Linux container নয়)
- শুরু দ্রুত, কারণ boot করার মতো কোনো OS নেই

### Container আসলে যা সমাধান করে

১. **"আমার মেশিনে তো চলে"** — image-এ dependency থাকে, তাই dev/CI/prod একরকম
২. **ঘনত্ব** — মুষ্টিমেয় VM-এর বদলে একটা host-এ কয়েক ডজন container
৩. **দ্রুত শুরু** — মিলিসেকেন্ড, যেটাই autoscaling-কে সাড়াদায়ী করে
৪. **Immutable deployment** — আপনি একটা artefact পাঠান, একটা server-এ চালানো কতগুলো command নয়
৫. **বহনযোগ্যতা** — একই image একটা ল্যাপটপে, একটা VM-এ, Kubernetes-এ, বা একটা serverless container platform-এ চলে

> এগুলোর মধ্যে সবচেয়ে বড় হলো **immutability**। একটা container image একবার তৈরি হয় আর অপরিবর্তিত অবস্থায় পরিবেশগুলোর মধ্য দিয়ে যায়। এটা configuration-এর ভেসে যাওয়া দূর করে — যা "staging-এ তো চলছিল" incident-এর বিশাল একটা অংশের উৎস।

## ১৫.২ Image আর layer

```dockerfile
FROM python:3.12-slim          # স্তর ১ — base OS + Python
WORKDIR /app
COPY requirements.txt .        # স্তর ২
RUN pip install -r requirements.txt   # স্তর ৩ — ব্যয়বহুলটা
COPY . .                       # স্তর ৪ — প্রতিটা commit-এ বদলায়
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

**স্তর cache করা আর ভাগ করা হয়।** একই base image থেকে দশটা container ওই base **একবারই** রাখে।

**স্তরের ক্রমই সবচেয়ে প্রভাবশালী Dockerfile দক্ষতা:** যা কম বদলায় সেটা আগে রাখুন। উপরের উদাহরণে `requirements.txt` source-এর আগে কপি হয়, তাই একটা কোড পরিবর্তন dependency-install স্তরটা অকেজো করে না। এটা ভুল করলে প্রতিটা commit-এ একটা ১০ সেকেন্ডের build একটা ৪ মিনিটের build হয়ে যায়।

### Multi-stage build — এটা সবসময় করুন

```dockerfile
# ---- Build stage: compiler, dev dependency, source আছে ----
FROM python:3.12 AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- Runtime stage: চালাতে যা লাগে শুধু সেটুকু ----
FROM python:3.12-slim
RUN groupadd -r app && useradd -r -g app app        # non-root user
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
    && rm -rf /wheels
COPY --chown=app:app ./app ./app
USER app                                             # কখনো root হিসেবে চালাবেন না
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**কেন গুরুত্বপূর্ণ:** runtime image-এ কোনো compiler নেই, কোনো build টুল নেই, কোনো source archive নেই। এটা ছোট (দ্রুত pull, দ্রুত scaling) **আর** অনেক ছোট আক্রমণের পরিসর। একটা সাধারণ multi-stage build একটা image ১.২ GB থেকে ১৮০ MB-তে নামায়।

### Image-এর নিরাপত্তার নিয়ম 🟢

```
✅ Base image digest দিয়ে pin করুন, কোনো ভাসমান tag দিয়ে নয়
   FROM python:3.12-slim@sha256:abc123...
✅ ন্যূনতম base ব্যবহার করুন: slim, alpine, distroless, বা static binary-র জন্য scratch
✅ একটা non-root user হিসেবে চালান (আর Kubernetes-এ runAsNonRoot বসান)
✅ CI-তে image scan করুন (Trivy, Grype, Snyk) আর CRITICAL-এ build FAIL করান
✅ কখনো image-এ secret বেক করবেন না — স্তর স্থায়ী আর বের করা যায়
✅ নিয়মিত আবার build করুন — একটা ৬ মাসের পুরনো image-এ ৬ মাসের patch-না-করা CVE আছে
✅ Image sign করুন (cosign) আর admission-এ signature যাচাই করুন
✅ একটা SBOM তৈরি করুন, যাতে "আমরা কি CVE-X দ্বারা প্রভাবিত?" — এর উত্তর মিনিটে দিতে পারেন
```

> **`latest` tag একটা anti-pattern।** এটা পুনরুৎপাদনযোগ্য নয়: একই manifest আলাদা দিনে আলাদা কোড deploy করে, আর rollback অনুমানের ব্যাপার হয়ে যায়। git SHA দিয়ে tag দিন আর digest দিয়ে deploy করুন।

---

# পর্ব ২ — Kubernetes

## ১৫.৩ Kubernetes কোন সমস্যা সমাধান করে

আপনার ১২টা মেশিনে ৪০টা container আছে। কাউকে না কাউকে:
- ঠিক করতে হবে কোন container কোন মেশিনে চলবে (**scheduling**)
- Crash করা container আবার চালাতে হবে (**self-healing**)
- Load বদলালে replica যোগ বা বাদ দিতে হবে (**autoscaling**)
- Container সরলেও তাদের স্থিতিশীল ঠিকানা দিতে হবে (**service discovery**)
- Downtime ছাড়া নতুন সংস্করণ ছাড়তে হবে (**deployment**)
- Config আর secret বিলি করতে হবে
- Resource-এর সীমা বলবৎ করতে হবে যাতে একটা container অন্যদের অভুক্ত না রাখে

এটা হাতে করা বাস্তবতার সাথে টেকে না। **Kubernetes একটা control loop, যা অনবরত বাস্তবতাকে আপনার ঘোষিত কাঙ্ক্ষিত অবস্থার সাথে মেলায়।**

```
        ┌──────────────────────────────────────────┐
        │  আপনি ঘোষণা করেন:  "আমি ৩টা replica চাই"  │
        └───────────────────┬──────────────────────┘
                            ▼
        ┌──────────────────────────────────────────┐
        │  Controller: দেখুন → তুলনা করুন → কাজ করুন │
        │  "আমি ২টা দেখছি। আমার ৩টা লাগবে। একটা বানাও।"│
        │  (চিরকাল, প্রতি কয়েক সেকেন্ডে)             │
        └──────────────────────────────────────────┘
```

**ওই reconciliation লুপটাই সেই একটা ধারণা যা পুরো Kubernetes ব্যাখ্যা করে।** বাকি সবকিছুই এমন একটা object যা কোনো একটা controller reconcile করে।

## ১৫.৪ যে object গুলো গুরুত্বপূর্ণ 🟢

### Pod — deployment-এর একক

এক বা একাধিক container যারা **একটা network namespace আর storage ভাগ করে**, সবসময় একসাথে schedule হয়।

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

**আপনি প্রায় কখনোই সরাসরি একটা Pod বানান না** — এর কোনো self-healing নেই। আপনি একটা Deployment বানান, যেটা ReplicaSet সামলায়, যেগুলো Pod সামলায়।

**Sidecar pattern** ভাগ করা namespace ব্যবহার করে: একই pod-এ একটা দ্বিতীয় container যা logging, একটা service-mesh proxy, বা একটা credential refresher সামলায়। যেহেতু তারা `localhost` ভাগ করে, app `127.0.0.1`-এ কথা বলে আর sidecar বাকিটা সামলায় — service mesh এভাবেই স্বচ্ছভাবে কাজ করে।

### Deployment — stateless কাজ

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
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }   # কখনো ক্ষমতা হারাবেন না
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

          resources:                                    # ⭐ §১৫.৬ দেখুন
            requests: { cpu: "200m", memory: "256Mi" }
            limits:   { memory: "512Mi" }               # খেয়াল করুন: কোনো CPU limit নেই

          livenessProbe:                                # process জীবিত?
            httpGet: { path: /health/live, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 15
            failureThreshold: 3

          readinessProbe:                               # traffic নিতে প্রস্তুত?
            httpGet: { path: /health/ready, port: 8000 }
            periodSeconds: 5
            failureThreshold: 2

          startupProbe:                                 # ধীরে শুরু হওয়াদের রক্ষা করে
            httpGet: { path: /health/live, port: 8000 }
            failureThreshold: 30
            periodSeconds: 2

          lifecycle:
            preStop:
              exec: { command: ["sleep", "10"] }        # ⭐ §১৫.৮ দেখুন

          envFrom:
            - configMapRef: { name: api-config }
            - secretRef:    { name: api-secrets }
```

**ReplicaSet** Deployment আর Pod-এর মাঝে বসে; এর অস্তিত্ব এই কারণে যে একটা rolling update-এর সময় একটা Deployment দুটো ReplicaSet পাশাপাশি চালাতে পারে, আর একটা rollback মানে শুধু পুরনোটা আবার বাড়ানো।

### Service — একটা স্থিতিশীল ঠিকানা

Pod নতুন IP নিয়ে আসে আর যায়। একটা Service একটা স্থিতিশীল নাম আর IP দেয়।

```yaml
apiVersion: v1
kind: Service
metadata:
  name: verification-api
spec:
  selector: { app: verification-api }     # নাম নয়, LABEL দিয়ে pod মেলায়
  ports: [{ port: 80, targetPort: 8000 }]
  type: ClusterIP
```

এখন যে কোনো pod `http://verification-api` call করে একটা সুস্থ pod-এ পৌঁছাতে পারে।

| ধরন | আচরণ | ব্যবহার |
|------|-----------|-----|
| **ClusterIP** | শুধু ভেতরে (default) | Service-থেকে-service |
| **NodePort** | প্রতিটা node-এ একটা port খোলে | খুব কমই — বেশিরভাগ স্থানীয় dev-এ |
| **LoadBalancer** | একটা ক্লাউড load balancer বানায় | প্রতি service-এ একটা ব্যয়বহুল হয়ে যায় |
| **ExternalName** | একটা DNS CNAME | একটা বাইরের service-এর দিকে তাক করা |
| **Headless** (`clusterIP: None`) | DNS সব pod-এর IP ফেরত দেয় | StatefulSet, client-side load balancing |

> **গুরুত্বপূর্ণ:** একটা Service **connection** load-balance করে, request নয়। HTTP/2 আর gRPC-তে (একটা দীর্ঘস্থায়ী connection) সব request একটা pod-এ আটকে যায় (অধ্যায় ১৩ §১৩.৬)। আপনার একটা L7 proxy, একটা service mesh, বা একটা headless service-এর উপর client-side load balancing লাগবে।

### Ingress / Gateway API — বাইরে থেকে HTTP routing

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

একটা load balancer, অনেক service, TLS কেন্দ্রীয়ভাবে terminate করা। **Gateway API** হলো নতুন, আরও প্রকাশক্ষম প্রতিস্থাপন (ভূমিকা-বিভাজিত, নিজস্বভাবে header/weight routing সাপোর্ট করে) — ecosystem সেদিকেই যাচ্ছে।

### ConfigMap আর Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: api-config }
data:
  LOG_LEVEL: "info"
  MAX_ATTEMPTS: "3"
  VENDOR_TIMEOUT_MS: "8000"
```

> **Kubernetes Secret default-এ base64-encoded, encrypted নয়।** Namespace-এ read access আছে এমন যে কেউ decode করতে পারেন, আর এগুলো etcd-তে বসে থাকে। **etcd-তে বিশ্রামে encryption চালু করুন**, RBAC সীমিত করুন, আর গুরুতর যা কিছুর জন্য একটা বাইরের secret store ব্যবহার করুন (External Secrets Operator + একটা ক্লাউড secrets manager, বা Vault), যাতে আসল secret কখনো cluster-এ না থাকে।

### StatefulSet — stateful কাজের জন্য

```
Deployment-এর pod:   api-7d8f9-x4k2l, api-7d8f9-p9m3n   (এলোমেলো, বদলযোগ্য)
StatefulSet-এর pod:  postgres-0, postgres-1, postgres-2  (স্থিতিশীল, ক্রমিক, স্থায়ী)
```

যা দেয়: স্থিতিশীল network পরিচয়, প্রতি pod-এ স্থিতিশীল স্থায়ী storage, ক্রমিক শুরু আর বন্ধ।

> **সৎ পরামর্শ: Kubernetes-এ production database চালাবেন না, যদি না আপনার এমন একটা টিম থাকে যারা সেটার মালিকানা নিতে চায়।** Managed database service-এর অস্তিত্ব ঠিক এই কারণেই যে storage, failover, backup আর upgrade কঠিন। Operator (CloudNativePG, Strimzi) এটাকে *সম্ভব* আর সত্যিই ভালো করেছে — তবু এটা সচেতনভাবে নেওয়ার সিদ্ধান্ত, default-এ নয়।

### Job আর CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: purge-expired-videos }
spec:
  schedule: "0 3 * * *"
  concurrencyPolicy: Forbid          # কখনো run উপরিপাতিত হবে না
  successfulJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 3
      activeDeadlineSeconds: 3600    # এক ঘণ্টা ছাড়ালে মেরে ফেলুন
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: purge
              image: registry/maintenance@sha256:...
              args: ["purge-videos", "--older-than=90d"]
```

`concurrencyPolicy: Forbid` আর `activeDeadlineSeconds` — এই দুটো setting মানুষ ভুলে যায়। এগুলো ছাড়া একটা ধীর job উপরিপাতিত কপি তৈরি করতে থাকে যতক্ষণ না cluster ভরে যায়।

### DaemonSet

প্রতিটা node-এ একটা pod। Node-স্তরের agent-এর জন্য: log collector (Fluent Bit), metric (node-exporter), নিরাপত্তা agent, CNI-র component।

### Namespace

নিজস্ব RBAC, resource quota আর network policy সহ যৌক্তিক বিভাজন। পরিবেশ (ছোট cluster-এ), টিম, বা tenant-এর জন্য ব্যবহার করুন।

> **অবিশ্বস্ত multi-tenancy-র জন্য namespace যথেষ্ট শক্তিশালী নিরাপত্তা সীমানা নয়।** এরা একটা kernel, একটা control plane আর প্রায়ই node ভাগ করে। শত্রুভাবাপন্ন tenant-এর জন্য আলাদা cluster বা sandbox করা runtime ব্যবহার করুন।

---

## ১৫.৫ Kubernetes-এ networking 🟡

**মডেল:** প্রতিটা pod নিজের IP পায়, আর প্রতিটা pod **NAT ছাড়াই** অন্য প্রতিটা pod-এ পৌঁছাতে পারে — node জুড়ে।

```
Node 1-এ Pod A (10.244.1.5)  ──────►  Node 2-এ Pod B (10.244.2.8)
                   (সমতল নেটওয়ার্ক, CNI plugin দিয়ে বাস্তবায়িত)
```

**ফলাফল: default-এ সবকিছু সবকিছুর সাথে কথা বলতে পারে।** এটা আটকাতে NetworkPolicy লাগে (অধ্যায় ১৩ §১৩.৮) — প্রতি namespace-এ default-deny দিয়ে শুরু করুন।

### Service mesh 🟡

প্রতিটা pod-এর পাশে একটা sidecar proxy, যা সব traffic ধরে।

```
┌──────────────────────┐        ┌──────────────────────┐
│  Pod A               │        │  Pod B               │
│  ┌──────┐ ┌────────┐ │        │ ┌────────┐ ┌──────┐  │
│  │ app  │►│ proxy  │─┼──mTLS──┼►│ proxy  │►│ app  │  │
│  └──────┘ └────────┘ │        │ └────────┘ └──────┘  │
└──────────────────────┘        └──────────────────────┘
```

**Application-এর কোড না বদলে এটা যা দেয়:**
- স্বয়ংক্রিয় certificate ঘোরানো সহ **সব জায়গায় mTLS** (zero trust, অধ্যায় ১৭)
- Retry, timeout, circuit breaking, outlier detection (অধ্যায় ০৫) — configure করা, কোড করা নয়
- **L7 load balancing** — যেটা gRPC/HTTP2-র আটকে যাওয়ার সমস্যা ঠিক করে
- Canary release-এর জন্য traffic ভাগ করা
- স্বয়ংক্রিয় golden metric আর distributed tracing-এর header

**এর খরচ:** প্রতি pod-এ একটা বাড়তি proxy (CPU, memory, কয়েক ms latency), বোঝা আর debug করার মতো একটা উল্লেখযোগ্য নতুন সিস্টেম, আর চালানোর মতো একটা control plane।

> **আঙুলের নিয়ম: ~২০+ service-এ, বা mTLS যখন একটা কঠিন compliance-এর দাবি, তখন একটা mesh ভাবুন।** তার নিচে library (Polly, Resilience4j) আর একটা ingress controller অনেক কম যন্ত্রপাতিতে কাজটা করে। **Linkerd** Istio-র চেয়ে লক্ষণীয়ভাবে সহজ আর বেশিরভাগ টিমের জন্য সঠিক শুরুর বিন্দু। নতুন "ambient"/sidecar-বিহীন mode overhead অনেকটা কমায়।

---

## ১৫.৬ Resource, limit আর QoS — যেখানে বেশিরভাগ production-যন্ত্রণা বাস করে 🟢

```yaml
resources:
  requests:              # নিশ্চিত — scheduling-এ ব্যবহৃত
    cpu: "200m"          # একটা core-এর ০.২
    memory: "256Mi"
  limits:                # ছাদ — রানটাইমে বলবৎ
    memory: "512Mi"
```

### দুটোর আচরণ সম্পূর্ণ আলাদা — এটাই মূল অন্তর্দৃষ্টি

| | **CPU** | **Memory** |
|---|---|---|
| Limit ছাড়ালে | **Throttle** (ধীর করে দেওয়া) | **OOM-kill** (process বন্ধ) |
| সংকোচনযোগ্য? | হ্যাঁ | **না** |
| খুব কম limit-এর প্রভাব | Latency-র লাফ, রহস্যময় p99 | Crash লুপ |

> **যে ব্যবহারিক নির্দেশনা অনেক default-এর বিপরীতে যায়:**
> - **সবসময় memory-র request আর limit দুটোই বসান, একে অপরের সমান**, অনুমানযোগ্য আচরণের জন্য
> - **CPU-র request বসান, কিন্তু CPU-র limit বাদ দেওয়ার কথা ভাবুন।** CFS quota দিয়ে CPU throttling node-এ অলস CPU থাকা সত্ত্বেও তীব্র, কঠিন-নির্ণেয় latency-র লাফ ঘটায়। অনেক অভিজ্ঞ টিম শুধু CPU-র request বসান, আর ন্যায্য ভাগাভাগির জন্য request-এর উপর নির্ভর করেন।
> - আসল ব্যবহার থেকে সঠিক আকার দিন (Vertical Pod Autoscaler-এর recommendation mode, বা Prometheus-এর data)। অনুমান করা মান প্রায় সবসময়ই ৩ গুণ বেশি বা বিপজ্জনকভাবে কম।

### QoS শ্রেণি — কে আগে বের হয়ে যায়

| শ্রেণি | শর্ত | Eviction-এর ক্রম |
|-------|-----------|---------------|
| **Guaranteed** | প্রতিটা container-এ request == limit | **সবার শেষে** বের হয় |
| **Burstable** | request < limit | দ্বিতীয় |
| **BestEffort** | কোনো request বা limit নেই | **সবার আগে** বের হয় |

Production-এর কাজ Guaranteed বা Burstable হওয়া উচিত। **একটা node চাপে থাকলে একটা BestEffort pod-ই প্রথমে মারা পড়ে** — কখনো গুরুত্বপূর্ণ কিছু ওভাবে চালাবেন না।

### Autoscaling — তিন ধরন

```yaml
# HPA — horizontal: বেশি pod
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

| ধরন | যা scale করে | নোট |
|------|--------|-------|
| **HPA** | Pod-এর সংখ্যা | প্রধানটা। **দ্রুত উপরে, ধীরে নিচে।** |
| **VPA** | প্রতি pod-এ CPU/memory | Recommendation mode-এ ব্যবহার করুন; auto mode pod restart করে |
| **Cluster Autoscaler / Karpenter** | Node-এর সংখ্যা | লাগে, নইলে HPA এমন pod বানায় যেগুলো schedule হতে পারে না |
| **KEDA** ⭐ | **যে কোনো** event উৎস থেকে pod | Worker-এর জন্য **queue-র গভীরতা CPU-র চেয়ে অনেক ভালো scaling সংকেত** |

```yaml
# KEDA — CPU নয়, queue-র গভীরতায় GPU worker scale করুন। এটাই সঠিক সংকেত।
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
        queueLength: "5"          # প্রতি ৫টা queue করা message-এ একটা pod
```

> **একটা queue consumer-কে CPU-তে scale করা একটা ক্লাসিক ভুল** — worker প্রায়ই I/O-নির্ভর, তাই এক ঘণ্টা ধরে backlog বাড়লেও CPU কম থাকে। Backlog-এ scale করুন।

---

## ১৫.৭ Probe — এগুলো ঠিক করুন 🟢

(অধ্যায় ০৪-এ পরিচয় দেওয়া হয়েছে; এখানে Kubernetes-এর নির্দিষ্ট দিক আর বিপর্যয়গুলো।)

| Probe | প্রশ্ন | ব্যর্থতায় কী হয় |
|-------|----------|---------------|
| **Startup** | Boot শেষ হয়েছে? | liveness/readiness-কে খুব আগে চালু হতে দেয় না |
| **Liveness** | Process কি সুস্থ? | **Container restart করে** |
| **Readiness** | এটা কি এখন traffic নিতে পারে? | **Service-এর endpoint থেকে সরায়** (restart নয়) |

```python
@app.get("/health/live")
async def live():
    # শুধু process-স্তরে। কোনো dependency নয়। কোনো database নয়। কোনো বাইরের call নয়।
    return {"status": "ok"}

@app.get("/health/ready")
async def ready(db=Depends(get_db), cache=Depends(get_cache)):
    checks = {"database": await db.ping(), "cache": await cache.ping()}
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)
```

### তিনটা ক্লাসিক probe-বিপর্যয়

১. **Liveness database যাচাই করে।** DB ৩০ সেকেন্ড ঝাঁকুনি খেল → প্রতিটা pod liveness-এ fail করল → Kubernetes **সবগুলো একসাথে** restart করল → পুনঃসংযোগের হুড়োহুড়ি DB বন্ধ রাখল → cluster আর কখনো ফিরল না। **Liveness কখনো একটা dependency যাচাই করবে না।**

২. **ধীরে শুরু হওয়া একটা app-এ কোনো startup probe নেই।** একটা JVM app গরম হতে ৪৫ সেকেন্ড নেয়; liveness ৩০ সেকেন্ডে চালু হয়ে একে মেরে ফেলে; এটা restart হয়, আবার মারা পড়ে — একটা স্থায়ী crash লুপ, যেটা দেখতে একটা কোডের bug-এর মতো লাগে।

৩. **Readiness যা সবসময় ২০০ ফেরত দেয়।** Traffic এমন একটা pod-এ যায় যেটা প্রস্তুত নয়, আর প্রতিটা deploy-এ ব্যবহারকারীরা ৫০০ পান। Readiness-কে সত্যিই প্রস্তুতি প্রতিফলিত করতে হবে।

---

## ১৫.৮ Graceful shutdown — সবচেয়ে বেশি বাদ পড়া খুঁটিনাটি 🟢

Kubernetes যখন একটা pod বন্ধ করে, তখন দুটো জিনিস **সমান্তরালে** ঘটে, আর সেটাই সমস্যা:

```
t=০    Pod-কে Terminating চিহ্নিত করা হলো
       ├── Endpoint সরানো শুরু (kube-proxy/ingress-এ ছড়ায়) ── ১-৫ সেকেন্ড লাগে
       └── Container-এ SIGTERM পাঠানো হলো                   ── তাৎক্ষণিক

       → ওই ফাঁকটায় traffic এখনো একটা বন্ধ-হতে-থাকা pod-এ যাচ্ছে।
       → প্রতিটা deploy-এ ব্যবহারকারীরা connection-refused error পান।

t=৩০   SIGKILL (terminationGracePeriodSeconds)
```

**সমাধান — আর এটা দুই ভাগের একটা সমাধান:**

```yaml
lifecycle:
  preStop:
    exec: { command: ["sleep", "10"] }   # ১. endpoint ছড়ানোর দেরিটা শুষে নিন
terminationGracePeriodSeconds: 60         # ২. চলমান কাজের জন্য যথেষ্ট সময় দিন
```

```python
# ৩. Application-কে SIGTERM ঠিকভাবে সামলাতে হবে
async def shutdown():
    app.state.ready = False          # readiness এখন fail করে
    await asyncio.sleep(5)           # load balancer-দের খেয়াল করতে দিন
    await server.shutdown()          # নতুন connection নেওয়া বন্ধ করুন
    await drain_in_flight(timeout=30)  # চলমান request শেষ করুন
    await close_db_pools()
    await close_broker_connections()  # consumer-দের জন্য: বর্তমান message শেষ করে ack করুন
```

> **আপনার deploy যদি ৫০২/৫০৩ error-এর ঢেউ ঘটায়, তাহলে এটাই কারণ, আর এটাই সমাধান।** "আমাদের zero-downtime deploy আসলে zero-downtime নয়" — এর সবচেয়ে সাধারণ কারণ এটাই।

**Node রক্ষণাবেক্ষণের সময় availability-র জন্যও অপরিহার্য:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: verification-api }
spec:
  minAvailable: 2                    # বা maxUnavailable: 1
  selector:
    matchLabels: { app: verification-api }
```

একটা PDB ছাড়া একটা node drain আপনার সব replica একসাথে বের করে দিতে পারে।

---

## ১৫.৯ Deployment-এর কৌশল 🟢

### Rolling update (Kubernetes-এর default)

```
[v1][v1][v1] → [v1][v1][v2] → [v1][v2][v2] → [v2][v2][v2]
```
✅ কোনো বাড়তি infrastructure নেই, ধাপে ধাপে
❌ দুটো সংস্করণই একসাথে চলে — **আপনার API আর database-এর schema-কে backward compatible হতে হবে** (expand/contract, অধ্যায় ০৯)

### Blue-Green

```
Blue  (v1) ◄── ১০০% traffic          Blue  (v1) ◄── ০%
Green (v2) ◄── ০%          ──────►   Green (v2) ◄── ১০০%   (Service-এর selector বদলান)
```
✅ তাৎক্ষণিক rollback, একবারে একটা সংস্করণ live, বদলানোর আগে পূর্ণ test
❌ বদলানোর সময় **২× সম্পদ**; database-এর migration-এ এখনো যত্ন লাগে

### Canary ⭐

```
v1: ৯৫% traffic     →  v1: ৭৫%  →  v1: ০%
v2:  ৫% traffic        v2: ২৫%     v2: ১০০%
     ↑ প্রতিটা ধাপে error-হার আর latency দেখুন; পিছিয়ে গেলে স্বয়ংক্রিয়ভাবে rollback
```
✅ **সীমিত blast radius সহ আসল production যাচাই** — সেরা ঝুঁকি/পুরস্কার
❌ Traffic ভাগ করা (ingress, mesh, বা Argo Rollouts/Flagger) আর ভালো metric লাগে

```yaml
# Argo Rollouts: বিশ্লেষণ-ভিত্তিক promotion সহ স্বয়ংক্রিয় canary
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

### Feature flag — deploy আর release আলাদা করা ⭐

```python
if await flags.is_enabled("new-liveness-model", tenant_id=tenant.id):
    result = await new_model.score(video)
else:
    result = await legacy_model.score(video)
```

**সবার জন্য কোড deploy করুন; ১%-এর জন্য feature চালু করুন।** এটা প্রায়ই একটা canary deploy-এর *চেয়েও ভালো*, কারণ আপনি একটা rollback ছাড়াই এক সেকেন্ডে একটা feature বন্ধ করতে পারেন, আর নির্দিষ্ট tenant-কে লক্ষ্য করতে পারেন। খরচ হলো flag-এর ঋণ — প্রতিটা flag-এ একটা মেয়াদ বসান আর সেটা সরিয়ে ফেলুন।

> **পরিণত সমন্বয়: rolling deploy + feature flag + সত্যিই ঝুঁকিপূর্ণ পরিবর্তনের জন্য অল্প কয়েকটা canary।**

---

## ১৫.১০ কখন Kubernetes ব্যবহার করবেন না 🟢

সৎ থাকুন, কারণ এই সিদ্ধান্ত আপনার টিমের পরের তিন বছরের আকার দেবে।

❌ **ব্যবহার করবেন না যখন:**
- আপনার ~৫টার কম service আছে
- টিমের কেউ চাপে এটা debug করতে পারেন না
- আপনার কোনো platform/infra ইঞ্জিনিয়ার নেই আর একজনের বাজেটও নেই
- একটা PaaS বা serverless container কাজ করত (অধ্যায় ১৪)
- আপনার কাজ হলো একটা monolith আর একটা database

✅ **ব্যবহার করুন যখন:**
- সত্যিকারের orchestration-এর চাহিদা সহ ১০+ service
- Multi-cloud বা hybrid বহনযোগ্যতা সত্যিই গুরুত্বপূর্ণ
- আপনার ecosystem লাগে (operator, mesh, GPU scheduling, জটিল batch)
- আপনার দক্ষতা আছে বা নিয়োগ করছেন

### Managed Kubernetes যা *সরায় না*

EKS/AKS/GKE control plane সামলায়। এখনো আপনার:
- Cluster-এর **version upgrade** (প্রতি ৩–৪ মাসে, বাতিল-হওয়া API ভাঙা সহ)
- Node pool, autoscaling, ক্ষমতার পরিকল্পনা
- Ingress controller, cert-manager, DNS
- RBAC, network policy, pod security standard
- Storage class আর CSI driver
- Observability-র stack
- খরচ ব্যবস্থাপনা (Kubernetes default-এ অপচয় অদৃশ্য করে রাখে)
- **রাত ৩টায় এটা debug করা**

> একজন ইঞ্জিনিয়ারের অর্থপূর্ণ, চলমান মনোযোগ বরাদ্দ রাখুন। না পারলে বরং serverless container বাছুন — আর এতে কোনো লজ্জা নেই। অনেক সফল কোম্পানি পুরোপুরি Cloud Run বা Fargate-এ চলে।

---

## ১৫.১১ সাধারণ ভুল

১. **কোনো resource request নেই** — pod যেখানে সেখানে বসে, আগে বের হয়ে যায়, আর node-এর ক্ষমতা অজানা থাকে
২. **CPU limit-এর কারণে throttling** — CPU অলস বসে থাকে অথচ রহস্যময় p99 latency
৩. **Liveness probe database যাচাই করছে** — একটা ঝাঁকুনি পুরো fleet restart করায়
৪. **কোনো graceful shutdown / preStop নেই** — প্রতিটা deploy-এ ৫০২
৫. **কোনো PodDisruptionBudget নেই** — একটা node drain সব replica নিয়ে নেয়
৬. **`latest` tag ব্যবহার** — পুনরুৎপাদন-অযোগ্য deploy, অসম্ভব rollback
৭. **Root হিসেবে চালানো** — একটা ভাগ-করা-kernel পরিবেশে অপ্রয়োজনীয় বিশেষাধিকার
৮. **ConfigMap-এ secret, বা unencrypted etcd** — base64 encryption নয়
৯. **Default-allow networking** — প্রতিটা pod প্রতিটা database-এ পৌঁছাতে পারে
১০. **দক্ষতা ছাড়া Kubernetes-এ stateful database চালানো** — managed service একটা কারণেই আছে
১১. **Queue worker-কে queue-র গভীরতার বদলে CPU-তে scale করা**
১২. **৫টা service-এ একটা service mesh নেওয়া** — যত জটিলতা সরায় তার চেয়ে বেশি যোগ করে
১৩. **৩টা service আর কোনো platform engineer ছাড়াই Kubernetes নেওয়া**
১৪. **একটা breaking schema পরিবর্তন করতে করতে rolling update দিয়ে deploy করা** — দুটো সংস্করণই একসাথে চলে

---

## ১৫.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] "কখন নয়" তালিকার বিপরীতে Kubernetes-এর সিদ্ধান্ত যুক্তিযুক্ত, টিমের সক্ষমতা বিবেচনা করে
- [ ] Image: multi-stage, ন্যূনতম base, non-root, digest দিয়ে pin করা, CI-তে scan করা
- [ ] Image-এ কোনো secret নেই; বাইরের secret store যুক্ত
- [ ] সবকিছুতে resource request বসানো; memory-র limit == request; CPU-র limit সাবধানে বিবেচিত
- [ ] Liveness, readiness আর startup probe আলাদা আর সঠিক (liveness বাইরের কিছু যাচাই করে না)
- [ ] preStop hook + SIGTERM সামলানো + যথেষ্ট grace period → যাচাই করা শূন্য-error deploy
- [ ] সব production কাজে PodDisruptionBudget
- [ ] HPA configure করা; worker queue-র গভীরতায় (KEDA) scale করে, CPU-তে নয়
- [ ] একটা সর্বোচ্চ node-সীমা সহ cluster autoscaler/Karpenter বসানো
- [ ] প্রতি namespace-এ default-deny NetworkPolicy
- [ ] Pod Security Standard / admission policy বলবৎ (কোনো privileged নয়, কোনো root নয়, read-only rootfs)
- [ ] RBAC least privilege; application-এর জন্য কোনো cluster-admin নয়
- [ ] Anti-affinity / topology spread, যাতে replica আলাদা AZ-তে পড়ে
- [ ] Deployment-এর কৌশল বাছা; schema পরিবর্তনে expand/contract
- [ ] Rollback পরীক্ষিত আর নথিভুক্ত; কেউ সত্যিই এটা করেছেন
- [ ] প্রতি namespace/টিমে খরচের দৃশ্যমানতা (Kubecost বা সমতুল্য)
- [ ] Cluster upgrade-এর পরিকল্পনা আর ছন্দ সম্মত

---

## ১৫.১৩ নিজেকে যাচাই

১. একটা container একটা হালকা VM নয়। এটা কী, আর কোন তিনটা kernel feature জড়িত?
২. Dockerfile-এ স্তরের ক্রম কেন গুরুত্বপূর্ণ? Build-সময়ের প্রভাব দিন।
৩. একটা ছোট image-এর বাইরে একটা multi-stage build কী অর্জন করে?
৪. এক বাক্যে reconciliation লুপ ব্যাখ্যা করুন। এটা কেন পুরো Kubernetes ব্যাখ্যা করে?
৫. আপনি প্রায় কখনোই সরাসরি একটা Pod বানান না কেন?
৬. একটা ClusterIP Service দিয়ে gRPC/HTTP2 call কেন একটা pod-এ আটকে যায়, আর কী এটা ঠিক করে?
৭. একটা container তার CPU limit ছাড়ালে কী হয়? Memory limit ছাড়ালে? পার্থক্যটা কেন গুরুত্বপূর্ণ?
৮. তিনটা QoS শ্রেণি আর eviction-এর ক্রম ব্যাখ্যা করুন।
৯. Liveness কেন কখনো database যাচাই করবে না? ব্যর্থতাটা পুরোপুরি বর্ণনা করুন।
১০. একটা preStop hook ছাড়া deploy কেন ৫০২ ঘটায়? সম্পূর্ণ তিন-ভাগের সমাধান দিন।
১১. PodDisruptionBudget কী আর এটা ছাড়া কী হয়?
১২. একটা worker-এর জন্য queue-র গভীরতা কেন CPU-র চেয়ে ভালো autoscaling সংকেত?
১৩. Rolling, blue-green আর canary তুলনা করুন। প্রতিটা কখন সঠিক?
১৪. Managed Kubernetes কী কী *সামলায় না*? ছয়টা জিনিস তালিকাভুক্ত করুন।

---

## ১৫.১৪ মূল কথাগুলো

- **একটা container হলো namespace, cgroup আর একটা স্তরায়িত filesystem সহ একটা process** — ভাগ করা kernel একটা নিরাপত্তার বিবেচনা
- **Immutability-ই আসল জয়** — একবার build করুন, অপরিবর্তিত এগিয়ে নিন
- **Kubernetes একটাই ধারণা: একটা reconciliation লুপ**, যা বাস্তবতাকে ঘোষিত অবস্থার সাথে মেলায়
- **Resource request আর সঠিক probe-এই বেশিরভাগ production-যন্ত্রণার জন্ম**
- **CPU throttle করে, memory মেরে ফেলে।** দুটো limit-কে সম্পূর্ণ আলাদাভাবে দেখুন।
- **Liveness process যাচাই করে; readiness dependency যাচাই করে।** এটা উল্টো করলে cluster-জোড়া outage হয়।
- **preStop + SIGTERM সামলানো + grace period** হলো deploy-সময়ের ৫০২-এর সমাধান
- **Worker-কে queue-র গভীরতায় scale করুন, CPU-তে নয়**
- **Canary + feature flag** release-এর জন্য সেরা ঝুঁকি/পুরস্কার দেয়
- **রাত ৩টায় debug করতে পারেন এমন কেউ ছাড়া Kubernetes চালাবেন না** — serverless container একটা বৈধ, পেশাদার বিকল্প
- **Managed Kubernetes control plane সামলায়, operational ভার নয়**

---

**পরবর্তী:** [অধ্যায় ১৬ — DevOps ও Platform Engineering](16-devops-and-platform-engineering.md)

**ইংরেজি সংস্করণ:** [Chapter 15](../15-containers-and-kubernetes.md) · **[সূচিপত্র](README.md)**
