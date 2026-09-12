# Chapter 14 — Cloud Architecture 🟡

> Do not memorise 200 service names. Learn the **seven categories**, know one or two services per category, and understand the **cost and failure models**.
> Then any cloud's service catalogue becomes readable, because they all solve the same problems with different names.

---

## 14.1 The mental model: seven categories

Every cloud is the same seven boxes.

| # | Category | The problem it solves | AWS | Azure | GCP |
|---|----------|----------------------|-----|-------|-----|
| 1 | **Compute** | Run code | EC2, ECS, Fargate, Lambda, EKS | VM, App Service, Container Apps, Functions, AKS | Compute Engine, Cloud Run, Functions, GKE |
| 2 | **Storage** | Keep files and blocks | S3, EBS, EFS | Blob, Managed Disks, Files | Cloud Storage, Persistent Disk, Filestore |
| 3 | **Database** | Keep structured data | RDS, Aurora, DynamoDB, ElastiCache | Azure SQL, Cosmos DB, Cache for Redis | Cloud SQL, Spanner, Firestore, Memorystore |
| 4 | **Networking** | Connect things | VPC, ALB/NLB, Route 53, CloudFront | VNet, App Gateway, Front Door, CDN | VPC, Cloud LB, Cloud DNS, Cloud CDN |
| 5 | **Messaging** | Decouple things | SQS, SNS, EventBridge, MSK, Kinesis | Service Bus, Event Grid, Event Hubs | Pub/Sub, Cloud Tasks |
| 6 | **Identity & Security** | Control access, keep secrets | IAM, KMS, Secrets Manager, WAF | Entra ID, Key Vault, Defender | IAM, KMS, Secret Manager |
| 7 | **Observability** | See what is happening | CloudWatch, X-Ray | Monitor, App Insights | Cloud Monitoring, Trace |

> **When you meet an unfamiliar service, ask which of the seven boxes it is in.** That alone tells you most of what you need to evaluate it.

---

## 14.2 The core concepts that shape every design

### Regions and Availability Zones ⭐

```
REGION (e.g. eu-west-1, Ireland)
│   A geographic area. Regions are ~independent. Data does not
│   move between them unless you move it. Latency between regions: 10–300 ms.
│
├── AVAILABILITY ZONE A  ── one or more physically separate datacenters
├── AVAILABILITY ZONE B  ── separate power, cooling, network
└── AVAILABILITY ZONE C  ── but close enough for 1–2 ms latency between them
```

**The single most important cloud design rule:**

> **Always deploy across at least 2 (preferably 3) Availability Zones within a region. Go multi-region only when you have a specific, costed reason.**

| | Multi-AZ | Multi-Region |
|---|---|---|
| Protects against | A datacenter failure | A whole-region failure, or gives geographic locality |
| Latency between | 1–2 ms — synchronous replication is fine | 10–300 ms — synchronous replication is usually not viable |
| Cost | Modest (cross-AZ data charges) | **2× everything**, plus replication and complexity |
| Complexity | Low — most managed services do it for you | **High** — data consistency, failover, DNS, split brain |
| Typical need | **Everyone** | Regulatory residency, global latency, or a very high-value SLA |

**Multi-region is the most over-requested and under-analysed architecture decision.** It doubles your cost and multiplies your complexity. Before agreeing, ask: *"What is the business cost of a 4-hour regional outage, and how often do regions actually fail?"* Usually the honest answer is "an acceptable amount, roughly once every few years" — and a well-tested multi-AZ setup plus a documented regional DR plan (Chapter 19) is the right call.

**When multi-region IS justified:**
- Data residency law (EU data must stay in the EU) — this is non-negotiable when it applies
- Users on several continents and latency is commercially material
- A contractual SLA that a single region cannot meet
- Regulatory DR requirements (common in finance)

### The Shared Responsibility Model 🟢

**This is the concept that decides who is to blame.**

```
                    ┌────────────────────────────────────┐
   YOUR JOB         │  Your data, your code              │
                    │  Identity & access management      │
                    │  Network & firewall configuration  │
                    │  Encryption settings               │
                    │  OS patching (IaaS only)           │
                    ├────────────────────────────────────┤
   CLOUD'S JOB      │  Physical security                 │
                    │  Hardware, network infrastructure  │
                    │  Hypervisor                        │
                    │  Managed service internals         │
                    └────────────────────────────────────┘
```

The line moves depending on the service model:

| Model | You manage | They manage |
|-------|-----------|-------------|
| **IaaS** (EC2, VM) | OS, patching, runtime, app, data, config | Hardware, network, hypervisor |
| **CaaS** (ECS/Fargate, Container Apps) | Container image, app, data, config | Host OS, orchestration, patching |
| **PaaS** (App Service, Cloud Run) | App code, data, config | Runtime, OS, scaling, patching |
| **FaaS** (Lambda, Functions) | Function code, config | Everything else |
| **SaaS** | Your data and who can see it | Everything else |

> **Almost every cloud breach is a customer-side misconfiguration**, not a cloud provider failure: a public S3 bucket, an over-permissive IAM role, a security group open to 0.0.0.0/0, a leaked access key in a Git repository. **The cloud is secure; cloud *configurations* frequently are not.**

---

## 14.3 Compute — choosing the right one 🟢

```
Do you need OS-level control, custom kernels, or licensed software?
├── YES → VIRTUAL MACHINES (EC2 / Azure VM / Compute Engine)
└── NO  → Is the workload event-driven, spiky, or very low volume?
          ├── YES → SERVERLESS FUNCTIONS (Lambda / Functions)
          └── NO  → Do you have many services needing complex orchestration?
                    ├── YES → KUBERNETES (EKS / AKS / GKE)
                    └── NO  → SERVERLESS CONTAINERS ⭐
                              (Fargate / Cloud Run / Container Apps)
```

### The comparison that matters

| | VMs | Kubernetes | Serverless containers | Functions |
|---|---|---|---|---|
| Ops burden | **High** | **Highest** | **Low** | **Lowest** |
| Cost at steady load | Low (with reservations) | Low (good bin-packing) | Medium | High |
| Cost when idle | Full price | Full price | **Near zero** | **Zero** |
| Cold start | None | None | 1–10 s (or keep min instances) | 0.1–5 s |
| Max runtime | Unlimited | Unlimited | Unlimited | ~15 min |
| Portability | Medium | **Highest** | High (a container) | **Lowest** |
| Scaling speed | Minutes | Seconds | Seconds | Milliseconds |
| Best for | Legacy, licensed software, GPU/specialised | Many services, a platform team | **Most modern web services** | Glue, cron, spiky, low volume |

> **The under-appreciated default: serverless containers** (Cloud Run, Fargate, Container Apps). You write a normal app in a normal Docker image, and you get autoscaling (including to zero), managed patching, and no cluster to run. For a team without platform engineers, this is usually the right answer — and unlike FaaS, you keep portability because it is just a container.

### The Kubernetes question, answered honestly

**Use Kubernetes when:**
- You have 10+ services with real orchestration needs
- You have (or will hire) someone who genuinely knows it
- You need multi-cloud or hybrid portability
- You need its ecosystem (operators, service mesh, complex scheduling, GPU sharing)

**Do not use Kubernetes when:**
- You have 1–5 services — you will spend more time on the cluster than on the product
- Nobody on the team can debug a CrashLoopBackOff at 3 AM
- A PaaS or serverless containers would do the job

> **Managed Kubernetes (EKS/AKS/GKE) removes control-plane management but not the operational burden.** You still own upgrades, networking, ingress, autoscaling, RBAC, storage classes, resource limits and cost management. Budget one engineer's meaningful attention, permanently. (Chapter 15.)

### Purchasing models — where the money is

| Model | Discount | Commitment | Use for |
|-------|----------|-----------|---------|
| **On-demand** | 0% | None | Development, unpredictable spikes |
| **Reserved / Savings Plans** | 30–72% | 1–3 years | **Your baseline capacity** — this is the biggest easy saving |
| **Spot / Preemptible** | **70–90%** | Can be reclaimed in ~2 minutes | Batch jobs, CI, stateless workers, ML training |
| **Dedicated hosts** | — | Premium | Licensing or compliance isolation |

> **The standard cost strategy: reserve your baseline, autoscale the peak on-demand, run all batch and CI on Spot.** Most companies over-pay simply because nobody has done this. It is often a 40%+ reduction for a week of work — one of the highest-value things an architect can do for the business.

---

## 14.4 Storage 🟢

### Three kinds, and they are not interchangeable

| | **Object** (S3/Blob) | **Block** (EBS/Disks) | **File** (EFS/Files) |
|---|---|---|---|
| Interface | HTTP API | A disk attached to one VM | NFS/SMB mount, many VMs |
| Structure | Flat key → blob | Raw blocks | Directory tree |
| Update | **Replace the whole object** | Any byte | Any byte |
| Attach to | Anything, over HTTP | Usually one instance | Many instances |
| Scale | **Effectively unlimited** | Per-volume limits | Large |
| Cost | **Cheapest** (~$0.023/GB) | ~$0.08/GB | ~$0.30/GB |
| Durability | 11 nines | High | High |
| Use for | Images, video, backups, logs, data lake | Database volumes, OS disks | Shared config, legacy apps needing a filesystem |

> **Default to object storage.** It is the cheapest, most durable, most scalable option, and it is the right home for anything that is a "file". Use block storage for databases. Use file storage only when an application genuinely requires a POSIX filesystem shared across machines — it is expensive and often a sign of a design that has not been modernised.

### Storage classes and lifecycle — automatic money saving

```
Hot / Standard     ~$0.023/GB/mo   instant access          — active data
Infrequent Access  ~$0.0125/GB/mo  instant, retrieval fee  — 30+ days old
Archive / Glacier  ~$0.004/GB/mo   minutes to hours        — 90+ days old
Deep Archive       ~$0.00099/GB/mo 12+ hours               — compliance retention
```

```json
{
  "Rules": [{
    "Id": "verification-video-lifecycle",
    "Filter": { "Prefix": "videos/" },
    "Transitions": [
      { "Days": 7,  "StorageClass": "STANDARD_IA" },
      { "Days": 30, "StorageClass": "GLACIER_IR" }
    ],
    "Expiration": { "Days": 90 }
  }]
}
```

That one policy implements your legal retention requirement **and** cuts storage cost by ~80%. For the liveness SaaS example in Chapter 04 (17.8 TB of video), this is the difference between ~$400/month and ~$90/month — and the deletion is automatic and auditable, which is what the regulator actually wants.

### The patterns that matter architecturally

**1. Presigned URLs — never route large files through your API**

```python
# The client uploads DIRECTLY to storage. Your API never sees the bytes.
url = s3.generate_presigned_url(
    "put_object",
    Params={"Bucket": "uploads", "Key": f"videos/{session_id}.mp4",
            "ContentType": "video/mp4"},
    ExpiresIn=900,                       # 15 minutes
)
return {"upload_url": url, "session_id": session_id}
```

This removes bandwidth, memory pressure and timeout risk from your application tier entirely. It is one of the highest-value cloud patterns and it is frequently missed.

**2. Event-driven processing** — an object upload emits an event that triggers your worker. No polling.

**3. Versioning + object lock** — versioning protects against accidental deletion and overwrite; object lock (WORM) provides immutable, ransomware-resistant backups and is often a compliance requirement.

**4. Block public access, at the account level** — and treat any exception as a reviewed security decision, not a convenience.

---

## 14.5 Managed databases 🟡

| Service type | What you gain | What you lose |
|--------------|--------------|---------------|
| **Managed relational** (RDS, Cloud SQL, Azure SQL) | Backups, patching, failover, replicas, monitoring | Superuser access, some extensions, version timing |
| **Cloud-native relational** (Aurora, AlloyDB) | Faster, storage auto-scaling, near-instant replicas | Lock-in, higher cost |
| **Distributed SQL** (Spanner, CockroachDB) | Horizontal scale **with** SQL and ACID | Cost, latency floor, some SQL limitations |
| **Managed NoSQL** (DynamoDB, Cosmos DB) | Serverless scale, low ops | Query-first modelling, lock-in |
| **Managed cache** (ElastiCache, Memorystore) | HA Redis without running it | Cost, less tuning control |

> **Default advice: use the managed service.** Running your own database on VMs means you own backups, patching, failover testing, replication monitoring and 3 AM recovery. Unless you have a dedicated DBA and a strong reason, the managed premium is excellent value.

### The three questions to ask of any managed database

1. **What exactly happens during a failover, and how long does it take?** (RDS Multi-AZ: typically 60–120 s, and connections are dropped — your application must reconnect.)
2. **What is the backup and PITR window, and have we tested a restore?** (Chapter 09 — untested backups are hopes.)
3. **How do we do a major version upgrade with acceptable downtime?** (Usually logical replication to a new instance, then a cutover.)

### Serverless databases

Aurora Serverless v2, DynamoDB on-demand, Cosmos serverless, Neon — capacity scales automatically and you pay per use.

- ✅ Excellent for unpredictable, spiky or development workloads; genuinely scales to near-zero cost when idle
- ❌ More expensive at steady high load; occasional scaling latency; **connection limits still apply** (use a proxy/pooler, Chapter 09)

---

## 14.6 Identity and access (IAM) 🟢

**IAM is where cloud security is won or lost.** Most cloud breaches trace back to over-permissive identity, not a clever exploit.

### The rules

**1. Never use long-lived access keys for workloads.**

```
❌ AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in an environment variable,
   a config file, or (worst) a Git repository
✅ IAM roles for EC2/ECS/Lambda; Workload Identity / IRSA for Kubernetes;
   Managed Identity in Azure; OIDC federation for CI/CD
```

The credential is then short-lived, rotated automatically, and there is nothing to leak. **GitHub Actions can assume a cloud role via OIDC — there is no longer any reason to store cloud keys in CI secrets.**

**2. Least privilege, and verify it.**

```json
// ❌ Common, lazy, dangerous
{ "Effect": "Allow", "Action": "s3:*", "Resource": "*" }

// ✅ Specific action, specific resource, with conditions
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject"],
  "Resource": "arn:aws:s3:::verification-videos/tenants/${aws:PrincipalTag/tenant}/*",
  "Condition": {
    "Bool": { "aws:SecureTransport": "true" },
    "StringEquals": { "s3:x-amz-server-side-encryption": "aws:kms" }
  }
}
```

**3. Separate accounts/subscriptions per environment.** Production in its own account is the strongest blast-radius control available — a mistake in dev cannot touch production, and billing is separated for free.

**4. Humans get roles, not users.** Federate from your identity provider (Entra ID, Okta, Google Workspace) with SSO and MFA. When someone leaves, disabling one account removes all cloud access.

**5. Every permission grant is temporary until proven otherwise.** Use access analysers and unused-permission reports; cloud providers now generate least-privilege policies from observed usage.

### Secrets management

```
❌ Secrets in environment variables committed to a repo
❌ Secrets in container images
❌ Secrets in a config file on a shared drive
⚠️ Secrets in environment variables at runtime (acceptable; visible in process listings and crash dumps)
✅ A secrets manager with automatic rotation and audit logging
✅ Better: no static secret at all — IAM-based database auth, workload identity
```

> **The end state to aim for: your application holds no long-lived credentials at all.** It presents a platform-issued identity and receives short-lived tokens. This eliminates the entire class of "leaked credential" incidents.

---

## 14.7 Cost management 🟢

**Cloud cost is an architectural concern, not a finance problem.** Architecture decisions determine 80% of the bill.

### Where the money actually goes

Typical mid-sized SaaS:

```
Compute            40-55%   ← reservations and right-sizing live here
Data transfer      10-25%   ← the surprise line item
Storage            10-20%   ← lifecycle policies live here
Managed databases  10-20%
Everything else     5-10%
```

### The biggest and most common wastes

| Waste | Typical size | Fix |
|-------|-------------|-----|
| **Over-provisioned instances** | 30–50% of compute | Right-size from actual metrics; most instances run at 10% CPU |
| **No reservations on baseline load** | 30–50% of compute | Savings Plans / Reserved Instances |
| **Orphaned resources** | 5–15% | Unattached disks, idle load balancers, old snapshots, unused IPs |
| **Non-production running 24/7** | 60% of non-prod | Schedule dev/test off outside business hours |
| **Cross-AZ and NAT gateway traffic** | Can exceed compute | Keep traffic in-AZ; use VPC endpoints; put a CDN in front |
| **Logs and metrics retention** | Surprisingly large | Tiered retention; sample high-volume debug logs |
| **No storage lifecycle policies** | 50–80% of storage | Automatic tiering and expiry |

### Make cost visible

```
1. TAG EVERYTHING           environment, team, service, cost-centre
                            → enforce with policy; untagged = auto-flagged
2. BUDGETS AND ALERTS       alert at 50/80/100% of the monthly budget
3. ANOMALY DETECTION        catch the runaway job the same day, not on the invoice
4. UNIT ECONOMICS           ⭐ cost per verification / per tenant / per 1000 API calls
5. SHOW TEAMS THEIR SPEND   a dashboard per team changes behaviour more than any policy
```

> **Unit economics is the architect's number.** "We spend $47,000/month" means nothing to anyone. **"It costs us $0.014 per verification, and our price is $0.15"** is a sentence that drives decisions — it tells you your margin, your scaling headroom, and exactly which component to optimise. Compute it and put it on a dashboard.

### FinOps in one paragraph

Bring engineering, finance and product into one conversation: engineers see the cost of their choices, finance understands variable cloud spend, and product knows the margin per feature. The practical starting point is tagging plus a per-team dashboard — that alone typically removes 15–25% of waste within a quarter, because engineers who can see cost act on it without being told.

---

## 14.8 Well-Architected — the six pillars 🟡

Every cloud publishes a version of this. It is a genuinely useful review checklist.

| Pillar | The question | Key practices |
|--------|-------------|---------------|
| **Operational excellence** | Can we run and improve it? | IaC, CI/CD, runbooks, observability, blameless postmortems |
| **Security** | Are we protected? | Least privilege, encryption everywhere, defence in depth, audit logs |
| **Reliability** | Does it recover? | Multi-AZ, health checks, retries, tested backups, DR drills |
| **Performance efficiency** | Are we using the right resources? | Right-sizing, caching, the right service for the job, measurement |
| **Cost optimisation** | Are we paying too much? | Reservations, lifecycle policies, right-sizing, unit economics |
| **Sustainability** | Is it efficient? | Right-sizing, modern instance types, region carbon intensity |

> **Run a Well-Architected review annually per major system, and once before any major launch.** It takes half a day and reliably finds three or four real issues. It is also an excellent way to get an existing system documented, because the questions force you to write things down.

---

## 14.9 Multi-cloud and lock-in 🟡

### The honest position on lock-in

Lock-in is **not** binary, and avoiding it entirely has a cost.

```
LOW LOCK-IN                                            HIGH LOCK-IN
│                                                                 │
VMs, containers ── managed Postgres ── managed queue ── DynamoDB ── Step Functions
   (portable)         (mostly portable)    (adapter-able)  (rewrite)   (rewrite)
```

**The rational approach:**
- Use managed services freely — the productivity gain is real and large
- **Hide each one behind your own interface** (Adapter/ACL, Chapters 01 and 03) so the blast radius of a change is one file
- Keep your **data** portable (standard formats, open table formats like Iceberg — Chapter 12)
- Accept deep lock-in only where the service is genuinely exceptional, and write down what a migration would cost

> **Multi-cloud "for resilience" is usually a mistake.** You get the lowest common denominator of both clouds, double the operational surface, double the expertise required, and your team is now mediocre at two platforms instead of good at one. Cloud regions fail far less often than the complexity you would add.

**Multi-cloud is justified when:** a regulator or a major customer requires it; you are avoiding a specific vendor for commercial reasons; or you are already there through acquisition. In practice, most "multi-cloud" companies run each workload in one cloud — which is fine, and is not the same as making one workload run in two.

---

## 14.10 A reference cloud architecture

For the liveness verification SaaS (numbers from Chapter 04):

```
                            Route 53 / Front Door
                                     │
                          ┌──────────▼──────────┐
                          │   CloudFront / CDN  │  TLS, WAF, DDoS
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  ALB (public subnet)│  3 AZs
                          └──────────┬──────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │ PRIVATE APP SUBNETS (3 AZs)   │                               │
     │   ┌──────────────────┐        │      ┌──────────────────┐     │
     │   │ API (Fargate)    │◄───────┴─────►│ Worker (Fargate  │     │
     │   │ 2-10 tasks       │               │  + GPU on EC2)   │     │
     │   └────────┬─────────┘               │ 1-10 tasks, Spot │     │
     │            │                         └────────┬─────────┘     │
     │            │  enqueue                         │ dequeue       │
     │            └──────────► SQS / Service Bus ◄───┘               │
     └───────────────────────────────┬───────────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │ PRIVATE DATA SUBNETS (3 AZs)  │                               │
     │  ┌─────────────┐  ┌───────────▼──┐  ┌──────────────────────┐  │
     │  │ RDS Postgres│  │ ElastiCache  │  │ S3 (videos)          │  │
     │  │ Multi-AZ    │  │ Redis, multi │  │ lifecycle: 7d IA,    │  │
     │  │ + replica   │  │ -AZ          │  │ 30d Glacier, 90d del │  │
     │  └─────────────┘  └──────────────┘  └──────────────────────┘  │
     └───────────────────────────────────────────────────────────────┘

     Cross-cutting: Secrets Manager · KMS · CloudWatch/OTel · CloudTrail
     Client uploads video DIRECTLY to S3 via presigned URL (never through the API)
```

**The decisions and their reasons — this is what an ADR looks like in practice:**

| Decision | Why |
|----------|-----|
| Fargate, not Kubernetes | 2 services, 4 engineers. No platform team. Portable (containers). |
| Queue between API and worker | Absorbs peaks; lets GPU workers scale independently; no dropped work |
| GPU workers on Spot | 70–90% cheaper; work is retryable and queued, so interruption is harmless |
| Presigned S3 upload | 6 MB videos never touch the API tier — removes bandwidth, memory and timeout risk |
| RDS Multi-AZ | Survives an AZ failure with ~90 s failover; far cheaper than multi-region |
| Single region | No residency requirement yet; a 4-hour regional outage is commercially acceptable. **Documented, with the trigger to revisit.** |
| S3 lifecycle | Implements the 90-day legal retention automatically and cuts cost ~80% |
| Redis Multi-AZ | Session and rate-limit state; system must survive one node loss |

That table is the deliverable. The diagram shows *what*; the table shows *why* — and the "why" is what future-you and your successor will need.

---

## 14.11 Common mistakes

1. **Single AZ deployment** — one datacenter issue takes you down; the fix is nearly free
2. **Multi-region "for resilience" without analysis** — 2× cost, 5× complexity, usually unjustified
3. **Long-lived access keys** in code, CI or environment variables
4. **`"Action": "*", "Resource": "*"`** IAM policies — the root cause of most breaches
5. **Public buckets** — still the most common cloud data leak
6. **No tagging** — you cannot attribute or optimise cost, and cleanup becomes impossible
7. **No reservations on baseline load** — leaving 30–50% of compute spend on the table
8. **Ignoring data transfer costs** — cross-AZ chatter and NAT gateways can exceed compute
9. **Kubernetes with no one to run it** — the cluster becomes the product
10. **Routing large file uploads through the application tier** — memory, bandwidth and timeout problems that a presigned URL removes
11. **No storage lifecycle policies** — paying hot prices for four-year-old logs
12. **Dev and test environments running 24/7**
13. **Assuming managed = backed up and tested** — the provider takes snapshots; **you** must test the restore
14. **Treating cost as finance's problem** — architecture decides the bill

---

## 14.12 Architect's checklist

- [ ] Deployed across ≥ 2 AZs (3 preferred); multi-region decision explicitly made and justified
- [ ] Compute model chosen deliberately against the decision tree, with team capability considered
- [ ] Baseline capacity reserved; batch/CI on Spot; non-prod scheduled off
- [ ] All resources tagged (env, team, service, cost-centre); untagged resources flagged automatically
- [ ] Budget alerts and cost anomaly detection configured
- [ ] **Unit economics** computed and on a dashboard
- [ ] No long-lived credentials anywhere; workload identity / OIDC federation used
- [ ] IAM policies scoped to specific actions and resources; least privilege verified with an analyser
- [ ] Production in its own account/subscription
- [ ] Human access via SSO + MFA, no shared accounts
- [ ] Secrets in a secrets manager, rotated, access-audited
- [ ] Encryption at rest and in transit enabled everywhere; customer-managed keys where required
- [ ] Public access blocked at the account level for object storage
- [ ] Storage lifecycle policies implementing retention rules automatically
- [ ] Backups automated **and a restore tested and timed**
- [ ] Audit logging (CloudTrail/Activity Log) enabled, centralised, and immutable
- [ ] Infrastructure defined as code; no manual console changes in production (Chapter 16)
- [ ] Well-Architected review completed within the last 12 months

---

## 14.13 Self-test

1. Name the seven cloud service categories and one service per category in a cloud you know.
2. Explain AZs vs regions. What is the default rule, and when is multi-region actually justified?
3. State the shared responsibility model. Who is responsible for a public S3 bucket?
4. Walk the compute decision tree. Where do serverless containers fit and why are they under-used?
5. When should you *not* use Kubernetes?
6. Object vs block vs file storage — give one correct use for each.
7. Explain presigned URLs and the three problems they solve.
8. Write a storage lifecycle policy for "delete video after 90 days" and estimate the saving.
9. Why should workloads never hold long-lived access keys? What replaces them?
10. Name five significant sources of cloud waste and the fix for each.
11. What are unit economics, and why is it the architect's number rather than total spend?
12. Give the honest argument against multi-cloud "for resilience".
13. Name the six Well-Architected pillars and one practice from each.
14. Your RDS instance fails over. What does your application experience, and what must it handle?

---

## 14.14 Key takeaways

- **Seven categories, not 200 services.** Classify anything new into one of them.
- **Multi-AZ always; multi-region only with a costed, written reason**
- **Shared responsibility: the cloud is secure, cloud configurations often are not.** Almost every breach is customer-side.
- **Serverless containers are the under-used sweet spot** for teams without platform engineers
- **Reserve the baseline, Spot the batch, schedule non-prod off** — usually a 40%+ saving for a week of work
- **Presigned URLs**: never route large files through your application tier
- **Storage lifecycle policies** implement legal retention *and* cut cost by 80%
- **No long-lived credentials.** Workload identity and OIDC federation everywhere.
- **Unit economics — cost per transaction — is the architect's number**
- **Hide managed services behind your own interfaces**; accept lock-in deliberately, and know what leaving would cost
- **Managed backups are not tested backups.** Drill the restore.

---

**Next:** [Chapter 15 — Containers & Kubernetes](15-containers-and-kubernetes.md)
