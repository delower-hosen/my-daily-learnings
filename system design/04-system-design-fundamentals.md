# Chapter 04 — System Design Fundamentals 🟢

> This is the central chapter. Everything before it was preparation; everything after is depth in one direction.
> By the end you should be able to take *"design a system that does X for Y million users"* and produce a defensible design in 45 minutes.

---

## 4.0 The design process

```
1. REQUIREMENTS      → functional, then non-functional, then constraints
2. ESTIMATE          → users, RPS, storage, bandwidth  (back-of-envelope)
3. API DESIGN        → what are the operations? what goes in, what comes out?
4. DATA MODEL        → what do we store, where, in what shape?
5. HIGH-LEVEL DESIGN → boxes and arrows, the happy path
6. DEEP DIVE         → the 2–3 hard parts
7. SCALE IT          → where does it break at 10×? fix that.
8. FAILURE MODES     → what if each box dies?
9. TRADE-OFFS        → say out loud what you gave up
```

Follow it in order. The single most common failure is **jumping to step 5 without doing steps 1 and 2** — you end up designing for a scale you invented.

---

# PART 1 — Requirements and Estimation

## 4.1 Gathering requirements fast

You covered the theory in Chapter 00. Here is the *practical* version — the questions you actually ask in the first 10 minutes.

### The 10 opening questions

1. **Who uses it?** (consumers? internal staff? machines? how many?)
2. **What is the single most important operation?** (the one that must never be slow or wrong)
3. **Read-heavy or write-heavy?** And by what ratio?
4. **How much data, and how fast does it grow?**
5. **How fresh must data be?** (real-time? seconds? a nightly batch is fine?)
6. **What is the peak vs average traffic?** (and when is peak — daily? Friday evening? Black Friday?)
7. **What must never be lost?** (payments, audit records) vs **what is disposable?** (analytics clicks)
8. **What happens if it is down for an hour?**
9. **Any compliance rules?** (data residency, retention, PII)
10. **What is the budget and the deadline?**

### Scope control

In design discussions (and interviews), the scope is always too big. **Narrow it explicitly and say so:**

> "For this design I will focus on posting a message and reading a timeline. I will treat authentication, search and ads as out of scope, and I will note where they would plug in."

That sentence makes you look senior. Trying to design everything makes you look junior.

---

## 4.2 Back-of-envelope estimation 🟢

You must be able to do this quickly and out loud. It is not about being right — it is about being **within an order of magnitude**, so you know whether you need one server or three hundred.

### Numbers to memorise

**Latency (the famous "numbers every programmer should know", rounded for modern hardware):**

| Operation | Time | Intuition |
|-----------|------|-----------|
| L1 cache reference | 1 ns | — |
| Branch mispredict | 3 ns | — |
| L2 cache reference | 4 ns | — |
| Mutex lock/unlock | 17 ns | — |
| Main memory reference | 100 ns | **RAM is the baseline** |
| Compress 1 KB (Snappy) | 2 µs | |
| Send 1 KB over 1 Gbps network | 10 µs | |
| Read 4 KB randomly from SSD | 150 µs | **SSD ≈ 1,500× slower than RAM** |
| Read 1 MB sequentially from memory | 250 µs | |
| Round trip within same datacenter | 500 µs | **0.5 ms** |
| Read 1 MB sequentially from SSD | 1 ms | |
| Disk seek (spinning HDD) | 10 ms | **HDD ≈ 100,000× slower than RAM** |
| Read 1 MB sequentially from HDD | 20 ms | |
| Round trip CA → Netherlands → CA | 150 ms | **Speed of light is the limit** |

**Three rules of thumb that follow:**
1. Memory is fast, disk is slow, **network is slower**, cross-continent is slowest
2. **Sequential is 10–100× faster than random** — on any storage
3. **Avoid the round trip.** One call fetching 100 rows beats 100 calls fetching 1 row, every time. (This is the N+1 problem, and it is the #1 cause of slow apps.)

**Availability:**

| SLA | Downtime/year | Downtime/month | Downtime/week |
|-----|---------------|----------------|---------------|
| 90% ("one nine") | 36.5 days | 73 hours | 16.8 hours |
| 99% | 3.65 days | 7.3 hours | 1.68 hours |
| 99.9% ("three nines") | 8.77 hours | 43.8 min | 10.1 min |
| 99.95% | 4.38 hours | 21.9 min | 5 min |
| 99.99% ("four nines") | 52.6 min | 4.4 min | 1 min |
| 99.999% ("five nines") | 5.26 min | 26 sec | 6 sec |

> Note: 99.99% means you have **4 minutes a month**. That is less than one careless deploy. Four nines is not a configuration setting; it is an engineering programme.

**Data sizes:**

| Type | Size |
|------|------|
| char (ASCII) | 1 byte |
| int / float | 4 bytes |
| long / double / timestamp | 8 bytes |
| UUID | 16 bytes (36 as a string!) |
| A tweet (280 chars) | ~300 bytes + metadata ≈ 1 KB |
| A typical JSON API response | 1–10 KB |
| A web page (HTML only) | ~100 KB |
| A photo (phone, compressed) | 2–5 MB |
| A 10-second 720p video | ~5–10 MB |
| A minute of 1080p video | ~50–100 MB |

**Powers of two (for storage):**

| Power | Approx | Name |
|-------|--------|------|
| 2^10 | 1 thousand | 1 KB |
| 2^20 | 1 million | 1 MB |
| 2^30 | 1 billion | 1 GB |
| 2^40 | 1 trillion | 1 TB |
| 2^50 | 1 quadrillion | 1 PB |

**Time:**
- 1 day = 86,400 seconds ≈ **100,000** (use this — it makes mental maths trivial)
- 1 month ≈ 2.6 million seconds
- 1 year ≈ 31.5 million seconds ≈ **30 million**

### The estimation recipe

```
Step 1: DAU (daily active users)
Step 2: Actions per user per day
Step 3: Total actions/day = DAU × actions
Step 4: Average RPS = actions/day ÷ 86,400   (use ÷100,000 for speed)
Step 5: Peak RPS = average × peak factor (2× to 10×; use 3× if unknown)
Step 6: Storage/day = actions/day × bytes per action
Step 7: Storage over N years = storage/day × 365 × N × replication factor
Step 8: Bandwidth = RPS × payload size
```

### Worked example 1 — Twitter-like service

```
GIVEN
  300 million monthly active users
  50% are daily active            → DAU = 150 million
  Each user posts 2 tweets/day
  Each user reads 100 tweets/day
  Average tweet = 300 bytes text + metadata ≈ 1 KB
  10% of tweets have media, average 1 MB

WRITES
  150M × 2 = 300 million tweets/day
  Average write RPS = 300M ÷ 100,000 ≈ 3,000 writes/sec
  Peak (3×)         ≈ 9,000 writes/sec

READS
  150M × 100 = 15 billion reads/day
  Average read RPS = 15B ÷ 100,000 = 150,000 reads/sec
  Peak (3×)        ≈ 450,000 reads/sec

  READ:WRITE RATIO = 50:1   ← THE MOST IMPORTANT NUMBER IN THIS ANALYSIS

STORAGE
  Text:  300M × 1 KB       = 300 GB/day
  Media: 30M  × 1 MB       = 30 TB/day     ← media dominates by 100×
  Total ≈ 30.3 TB/day
  Per year ≈ 11 PB
  With 3× replication ≈ 33 PB/year

BANDWIDTH
  Ingress: 30.3 TB/day ÷ 86,400 ≈ 350 MB/s
  Egress:  150,000 reads/s × ~5 KB avg ≈ 750 MB/s  (plus media via CDN)
```

**What the numbers tell you — this is the point of the exercise:**

1. **50:1 read/write** → the design must be read-optimised. Heavy caching. Read replicas. Precomputed timelines (fan-out on write).
2. **Media is 100× the text storage** → media goes to blob storage + CDN, never through your app servers. Text goes to a database.
3. **9,000 writes/sec** → a single Postgres can *almost* do this, but not with headroom. You need partitioning or a write-optimised store.
4. **450,000 reads/sec** → impossible from a database. This *must* be served from cache. At ~100,000 ops/sec per Redis node, you need a cluster of ~10–20 nodes minimum.
5. **33 PB/year** → nobody buys this; object storage with lifecycle tiering (hot → cold → archive) is mandatory.

> Notice: five estimation lines produced five architectural decisions. **That is why you estimate.**

### Worked example 2 — the liveness verification SaaS (your domain)

```
GIVEN
  200 enterprise tenants
  Average 5,000 verifications/tenant/month  → 1 million verifications/month
  Each verification: a 6-second 720p video ≈ 6 MB
  Peak is concentrated: 60% of traffic in business hours (9 hours), weekdays
  Each verification uses ~4 seconds of GPU time
  Legal: raw video must be deleted after 90 days; results kept 7 years

THROUGHPUT
  1M/month ÷ 30 = 33,000/day
  Business-hours concentration: 33,000 × 0.6 = 20,000 in 9 hours
     = 20,000 ÷ 32,400s ≈ 0.6/sec average during business hours
  Peak-of-peak (3×) ≈ 2/sec = 120/minute

  → This is a SMALL system by request count. Do NOT over-engineer it.

COMPUTE  ← this is the real constraint, not RPS
  2/sec × 4 GPU-seconds = 8 concurrent GPU-seconds needed
  One T4 GPU handling ~1 inference/sec → need ~8 GPU workers at peak
  At $0.35/hr per T4 × 8 × 24 × 30 = $2,000/month if always on
  → AUTOSCALE. At night you need 1. This is a 5× cost difference.
  → Queue-based load levelling is essential: never drop work, just delay it.

STORAGE
  Video (90-day retention):
     33,000/day × 6 MB × 90 days = 17.8 TB hot-ish storage
     At ~$0.02/GB/month = ~$360/month  → use lifecycle rules to cool it fast
  Results (7-year retention):
     33,000/day × ~5 KB JSON × 365 × 7 = 420 GB  → trivial, keep in Postgres

BANDWIDTH
  Ingress: 33,000 × 6 MB = 198 GB/day ≈ 2.3 MB/s average, ~7 MB/s peak
  → Upload DIRECTLY to object storage with a presigned URL.
     Do NOT route 6 MB through your API servers. That single decision
     removes ~90% of your bandwidth and memory pressure.
```

**Architectural conclusions from the numbers:**

1. Low RPS → a **modular monolith** API is completely sufficient. No microservices needed.
2. GPU cost dominates → **separate the GPU worker** so it scales independently. This is the one real service boundary.
3. **Queue between API and worker** → absorbs peaks, enables autoscaling, prevents dropped work
4. **Presigned direct-to-storage upload** → API servers never touch video bytes
5. **Two retention policies** → video (90 days, lifecycle rules) and results (7 years, database). Two different stores.

```
   Mobile/Web
       │ 1. POST /sessions  →  returns presigned URL
       ▼
   ┌────────┐   2. PUT video directly     ┌──────────────┐
   │  API   │◄──────────────────────────► │Object Storage│
   │(2 pods)│   3. POST /sessions/{id}/submit           │
   └───┬────┘                              └──────┬──────┘
       │ 4. enqueue job                           │
       ▼                                          │
   ┌────────┐                                     │
   │ Queue  │                                     │
   └───┬────┘                                     │
       │ 5. dequeue                               │
       ▼                                          │
   ┌──────────────┐  6. fetch video ──────────────┘
   │ GPU Workers  │
   │ (1–10 pods,  │  7. write result
   │  autoscaled) │──────────────┐
   └──────────────┘              ▼
                            ┌──────────┐
                            │ Postgres │
                            └──────────┘
```

### Estimation shortcuts

| Want | Do this |
|------|---------|
| RPS from daily count | divide by 100,000 |
| Peak from average | ×3 (unknown), ×10 (consumer/viral), ×2 (B2B steady) |
| 1 million/month | ≈ 0.4/sec average |
| 1 billion/month | ≈ 400/sec average |
| GB/day from RPS × KB | RPS × KB × 86,400 ÷ 1,000,000 ≈ RPS × KB × 0.086 |
| Cost of 1 TB cloud storage/month | ~$20 (hot), ~$10 (cool), ~$1 (archive) |
| Cost of a small VM/month | ~$30–70 |

**Always round aggressively.** 86,400 → 100,000. 365 → 400. π → 3. You want speed, not precision.

---

## 4.3 Capacity planning 🟢

Estimation tells you the size. Capacity planning tells you **how many machines**, and **when to buy more**.

### Key terms

| Term | Meaning |
|------|---------|
| **QPS / RPS** | Queries/requests per second |
| **Concurrency** | Requests being handled *at the same instant* |
| **Throughput** | Completed work per unit of time |
| **Utilisation** | % of a resource in use |
| **Headroom** | Spare capacity for spikes and failures |

### Little's Law — the one formula you must know

> **L = λ × W**
> (Concurrency = Arrival rate × Average time in system)

```
If you receive 500 requests/second and each takes 200 ms:
  Concurrency = 500 × 0.2 = 100 requests in flight at any moment

→ You need at least 100 threads/connections/workers, plus headroom.
→ If each worker holds a DB connection, you need ~100 DB connections.
→ If your DB pool is 20, you have just found your bottleneck.
```

Run it backwards too:

```
Your server has 200 worker threads. Each request takes 400 ms.
  Max throughput = 200 ÷ 0.4 = 500 RPS per server.
  Need 2,000 RPS? → 4 servers minimum, 6 with headroom.
```

**Little's Law also explains queue explosions:** if arrival rate exceeds service rate even slightly, W grows without bound. This is why a system at 100% utilisation does not just "run a bit slow" — it collapses.

### The utilisation trap

```
  Latency
    │                                    ╱
    │                                  ╱
    │                              ╱╱
    │                        ╱╱╱╱
    │            ╱╱╱╱╱╱╱╱╱
    │──────────╱
    └──────────────────────────────────── Utilisation
     0%   40%   60%   70%   80%  90% 100%
                              ▲
                     the cliff starts here
```

Queueing theory: average wait time scales with **1/(1−utilisation)**.

| Utilisation | Relative queueing delay |
|-------------|------------------------|
| 50% | 2× |
| 70% | 3.3× |
| 80% | 5× |
| 90% | 10× |
| 95% | 20× |
| 99% | 100× |

> **Rule: target 50–70% utilisation for latency-sensitive services.** Running at 90% "to save money" is how you get an outage during a minor traffic bump. The extra servers are cheaper than the incident.

Batch/async workloads are different — there you *want* high utilisation, because latency does not matter and the queue is the buffer.

### Capacity plan worked example

```
REQUIREMENT: 2,000 RPS peak, p95 latency < 300 ms

MEASURED (from a load test on one instance, 4 vCPU / 8 GB):
  - one request uses ~25 ms CPU
  - one request holds a thread for 120 ms (mostly waiting on the DB)
  - one instance saturates CPU at ~140 RPS

CALCULATION
  Instances for throughput: 2,000 ÷ 140 = 14.3 → 15
  Target 60% utilisation:   15 ÷ 0.6 = 25 instances
  N+1 for AZ failure (3 AZs, survive losing one): 25 × 1.5 = 38
  → Run 38 instances across 3 AZs (≈13 per AZ)

  Little's Law check on connections:
  Concurrency = 2,000 × 0.12 = 240 in-flight requests
  → DB connection pool must support ~240 across the fleet
  → 38 instances × 10 connections = 380. Postgres max_connections default is 100.
  → YOU NEED A CONNECTION POOLER (PgBouncer). This is the real finding.
```

That last line is the kind of thing capacity planning exists to catch — **before** production.

### Growth planning

```
Today: 500 RPS. Growth: 8%/month.
  Months to double = 72 ÷ 8 = 9 months        (rule of 72)
  In 12 months: 500 × 1.08^12 ≈ 1,260 RPS
  In 24 months: 500 × 1.08^24 ≈ 3,170 RPS

→ Design headroom for 12 months. Know your plan for 24.
→ Set an alert at 60% of current capacity so you get 3 months of warning.
```

> **Architect's line:** *"We are good until about 1,200 RPS. We hit that in roughly 11 months. Sharding is a 6-week project, so we should start it in month 5."*

---

# PART 2 — Core design concepts

## 4.4 Stateless vs Stateful services 🟢

**The single most important scaling decision you make.**

### Stateful (bad for scaling)

```
User A ──► Server 1  [session: {cart: [...], user: A}]  ← state lives HERE
User B ──► Server 2  [session: {cart: [...], user: B}]

Server 1 dies → User A loses their cart
Add Server 3 → it has no sessions, and the load balancer must know that
Scale down  → you destroy live sessions
```

### Stateless (good)

```
User A ──► ANY server ──► reads state from Redis / DB / the token itself
User B ──► ANY server ──► same

Server dies      → users do not notice; requests go elsewhere
Add a server     → it works immediately
Deploy           → rolling restart, zero disruption
```

**Stateless does not mean "no state".** It means **the server holds no state between requests**. State moves to:

| Where | Good for | Watch out |
|-------|----------|-----------|
| **The client** (JWT, cookie) | User identity, small claims | Cannot be revoked easily; size limits; never put secrets in it |
| **A shared cache** (Redis) | Sessions, carts, rate-limit counters | Needs HA; it is now a dependency |
| **The database** | Anything durable | Slower |
| **Object storage** | Files, large blobs | Not for hot data |

### Sticky sessions — the tempting trap

Load balancers can pin a user to one server (by cookie or IP hash).

**Why it is tempting:** you keep in-memory sessions and everything "works".
**Why it hurts:**
- Uneven load — one server gets the heavy users
- Deploys kick everyone off
- Autoscaling does not rebalance existing users
- A dead server = lost sessions
- Your system is now fundamentally unable to scale elastically

> **Use sticky sessions only when you genuinely cannot avoid it** (long-lived WebSockets, some legacy apps). Otherwise, externalise state. Always.

### When state is unavoidable

Databases, caches, message brokers and stream processors are inherently stateful. Handle them with:
- **Replication** (multiple copies)
- **Consensus** (Raft — Chapter 05) for leader election
- **Persistent volumes** and **StatefulSets** in Kubernetes (Chapter 15)
- Or, best of all, **use a managed service** and let someone else run it

---

## 4.5 Vertical vs Horizontal scaling 🟢

### Vertical (scale up) — a bigger machine

```
  [2 vCPU, 4 GB]  →  [32 vCPU, 128 GB]  →  [128 vCPU, 2 TB]
```

| ✅ Pros | ❌ Cons |
|---------|---------|
| Zero code changes | A hard ceiling exists |
| No distributed complexity | Cost grows **super-linearly** (2× the machine ≈ 3× the price) |
| ACID transactions stay easy | **Single point of failure** |
| Often the fastest fix | Usually requires downtime to resize |

### Horizontal (scale out) — more machines

```
  [Server] → [Server][Server][Server][Server] behind a load balancer
```

| ✅ Pros | ❌ Cons |
|---------|---------|
| Effectively unlimited | Requires stateless design |
| Commodity hardware = cheaper per unit | Distributed systems problems (Chapter 05) |
| Fault tolerant by construction | Data consistency becomes hard |
| Scale up **and down** with demand | More operational complexity |

### The honest advice most people get wrong

> **Scale vertically first. Much further than you think.**

A modern single server can have 128 cores and 2 TB of RAM. That machine can serve tens of thousands of requests per second and hold a 500 GB database entirely in memory. StackOverflow famously served the world from 9 web servers and 2 SQL servers.

**The professional sequence:**

```
1. OPTIMISE      → fix the N+1 query, add the index, cache the hot read.
                   Usually gives 10–100×. Costs nothing. Do this FIRST.
2. SCALE UP      → bigger box. Simple, quick, buys you 12+ months.
3. SCALE OUT (stateless tier) → easy, do it early for availability anyway.
4. SCALE OUT (reads)  → read replicas, caching.
5. SCALE OUT (writes) → partitioning/sharding. LAST. It is the hard one.
```

**Real story:** a team spent 4 months building a sharded architecture for a database doing 400 writes/sec. A consultant added three indexes and moved it to a larger instance in one day. The system ran for three more years without sharding. Always check step 1 before step 5.

### Autoscaling

Scaling out automatically based on a metric.

| Trigger type | Example | Notes |
|--------------|---------|-------|
| **Reactive** | CPU > 70% for 3 min → add instance | Simple, but always lags. New instances take 1–5 min to be ready. |
| **Scheduled** | Scale to 20 at 08:00, down to 4 at 20:00 | Great for predictable business-hours load |
| **Predictive** | ML forecast of load | Cloud providers offer it; useful at large scale |
| **Queue-based** | queue depth > 1000 → add worker | **The best signal for async work** — it measures actual backlog |

**Autoscaling gotchas:**
- **Scale up fast, scale down slowly** (cooldowns) — flapping is worse than over-provisioning
- **Startup time matters** — if a pod takes 4 minutes to warm up, reactive scaling cannot help a 2-minute spike. Keep warm capacity.
- **Scaling the app but not the database** just moves the bottleneck and can *kill* the database with connections
- **Set a maximum.** A runaway autoscaler plus a retry storm is a genuine way to spend $50,000 in a night.

---

## 4.6 Load balancing 🟢

A load balancer distributes incoming requests across multiple servers.

```
                    ┌──────────────┐
   Clients ────────►│Load Balancer │
                    └───┬───┬───┬──┘
                   ┌────┘   │   └────┐
              ┌────▼──┐ ┌───▼───┐ ┌──▼────┐
              │Server1│ │Server2│ │Server3│
              └───────┘ └───────┘ └───────┘
```

### Layer 4 vs Layer 7

| | **L4 (transport)** | **L7 (application)** |
|---|---|---|
| Sees | IP + port | Full HTTP: URL, headers, cookies, body |
| Speed | Very fast, low CPU | Slower, more CPU |
| Can route by | Connection only | Path, host, header, cookie, method |
| TLS | Passes through (or TCP passthrough) | **Terminates TLS** |
| Examples | AWS NLB, HAProxy (TCP mode), IPVS | AWS ALB, Nginx, Envoy, Traefik, Azure App Gateway |
| Use for | Raw TCP, databases, gaming, extreme throughput | Web APIs, anything needing smart routing |

> Most web systems want **L7**. You get path-based routing (`/api/*` → API pods, `/static/*` → CDN origin), header-based canary routing, request retries, and TLS termination in one place.

### Algorithms

| Algorithm | How | Best for |
|-----------|-----|----------|
| **Round Robin** | Next server in turn | Uniform servers, uniform requests |
| **Weighted Round Robin** | Bigger servers get more | Mixed instance sizes |
| **Least Connections** | Fewest active connections | **Variable request durations — usually the best default** |
| **Least Response Time** | Fastest responder | Latency-sensitive |
| **IP Hash** | Hash client IP → server | Sticky-ish without cookies (breaks with NAT/mobile) |
| **Consistent Hashing** | Hash key → ring | **Caches and sharded state** — adding a node moves only 1/N of keys |
| **Random Two Choices** | Pick 2 at random, use the less loaded | Surprisingly excellent; used at scale (it avoids the "herd" problem of least-connections) |

### Health checks — the part people get wrong

```
LIVENESS   "Is the process alive?"       → if NO: restart it
READINESS  "Can it serve traffic NOW?"   → if NO: remove from the pool (but do not kill)
STARTUP    "Has it finished booting?"    → protects slow starters from being killed
```

```python
# Readiness must check DEPENDENCIES. Liveness must NOT.
@app.get("/health/live")
async def live():
    return {"status": "ok"}          # process is running. That is all.

@app.get("/health/ready")
async def ready(db=Depends(get_db), cache=Depends(get_cache)):
    checks = {
        "database": await db.ping(),
        "cache":    await cache.ping(),
    }
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks},
                        status_code=200 if ok else 503)
```

> **Classic production disaster:** making the *liveness* probe check the database. The database has a 30-second blip → every pod fails liveness → Kubernetes restarts **all of them simultaneously** → the stampede of reconnections keeps the database down → the cluster never recovers. **Liveness checks the process. Readiness checks dependencies.** Learn this before it bites you.

### Other load balancer responsibilities

- **TLS termination** (and re-encryption to the backend if required)
- **Connection draining / graceful shutdown** — stop sending new requests, let in-flight ones finish (typically 30 s)
- **Rate limiting** and **WAF** integration
- **Retries** on idempotent requests only (Chapter 05 — retrying a non-idempotent POST is how you get double charges)
- **Outlier detection** — automatically eject a backend that starts returning 5xx

### DNS load balancing and Global Server Load Balancing

- **DNS round-robin** — return multiple A records. Cheap, but DNS caching and TTLs make failover slow and unreliable. Not a real health-aware LB.
- **GSLB / Anycast** (Route 53, Azure Front Door, Cloudflare) — route users to the nearest *healthy* region. This is how multi-region failover actually works.

---

## 4.7 Caching (introduction — full chapter later) 🟢

**The idea:** keep a copy of expensive-to-produce data somewhere fast.

> **Caching is the single highest-leverage performance technique in existence.** It is also the source of the industry's most famous joke: *"There are only two hard things in computer science: cache invalidation and naming things."*

### The cache hierarchy — cache at every level

```
1. BROWSER CACHE        Cache-Control headers          0 ms, free
2. CDN                  static assets, some API GETs    ~20 ms, cheap
3. API GATEWAY CACHE    full responses                  ~5 ms
4. APPLICATION MEMORY   in-process dictionary/LRU        ~0.1 µs
5. DISTRIBUTED CACHE    Redis/Memcached                  ~0.5 ms
6. DATABASE CACHE       buffer pool, query cache         ~1 ms
7. DISK
```

Each layer you hit *earlier* saves everything below it.

### Cache hit ratio — the metric that matters

```
Hit ratio = hits ÷ (hits + misses)

At 1000 RPS with a 20 ms DB query:
  0%  hit ratio → 1000 DB queries/sec
  80% hit ratio → 200 DB queries/sec   (5× reduction)
  95% hit ratio → 50 DB queries/sec    (20× reduction)
  99% hit ratio → 10 DB queries/sec    (100× reduction)
```

Going from 95% to 99% removes **80% of the remaining load**. This is why hit ratio is a first-class metric and belongs on your dashboard.

### The three questions to ask before adding a cache

1. **Is this data read far more often than it changes?** (If it changes every read, caching adds cost and gains nothing.)
2. **How stale can it be?** (1 second? 1 hour? Never? The answer sets your TTL and strategy.)
3. **What happens when the cache is empty or down?** (If the answer is "the database dies", you have built a system that cannot restart. See *cache stampede*, Chapter 11.)

Full treatment — patterns, invalidation, stampede, penetration, avalanche — in **Chapter 11**.

---

## 4.8 Replication 🟢

**Definition:** keeping copies of the same data on multiple machines.

**Why:** availability (survive a node loss), read scalability (spread reads), and locality (serve users from a nearby region).

### Leader–Follower (primary–replica) — the most common model

```
          writes
             │
             ▼
        ┌─────────┐
        │ LEADER  │────replication log────┐
        └─────────┘                       │
             │                            │
     ┌───────┴────────┐           ┌───────▼────────┐
     ▼                ▼           ▼                ▼
┌─────────┐    ┌─────────┐  ┌─────────┐    ┌─────────┐
│FOLLOWER │    │FOLLOWER │  │FOLLOWER │    │FOLLOWER │
└─────────┘    └─────────┘  └─────────┘    └─────────┘
     ▲                ▲           ▲                ▲
     └────────── reads ───────────┴────────────────┘
```

- **All writes go to the leader.** Followers are read-only.
- The leader ships its change log; followers apply it.
- If the leader dies, a follower is **promoted** (automatically or manually).

### Synchronous vs asynchronous replication — the key trade-off

| | **Synchronous** | **Asynchronous** |
|---|---|---|
| Leader waits for follower? | Yes, before ack | No, acks immediately |
| Write latency | Higher (network round trip) | Low |
| Data loss on leader failure | **None** | **Possible** — unreplicated writes are lost |
| If a follower is slow/down | **Writes block** | No impact |

**The practical compromise: semi-synchronous.** One follower synchronous, the rest async. You get durability (at least one other copy has it) without being hostage to every replica.

```sql
-- PostgreSQL: wait for one named standby to confirm
synchronous_standby_names = 'ANY 1 (replica_a, replica_b)'
synchronous_commit = on
```

### Replication lag — and the bugs it causes

Asynchronous replicas are always *slightly* behind — microseconds normally, minutes under load or during a big write.

**The classic bug:**

```python
# User updates their profile
await db.write("UPDATE users SET name = 'Delower' WHERE id = 42")
# Redirect to profile page → read goes to a REPLICA
user = await db.read_replica("SELECT name FROM users WHERE id = 42")
# → returns the OLD name. User: "my change didn't save!" and clicks save again.
```

**Fixes (know all four):**

| Technique | How | Cost |
|-----------|-----|------|
| **Read-your-writes** | Route a user's reads to the leader for N seconds after they write | Extra leader load |
| **Monotonic reads** | Pin one user to one replica (consistent hashing) | Uneven load |
| **Token/LSN-based** | Client passes the write position; the replica waits until it has caught up | Complexity, added latency |
| **Just return the value** | The write response contains the new state; do not re-read | Free — **use this whenever possible** |

### Multi-leader replication

Two or more nodes accept writes. Used for multi-region write locality and offline-capable clients.

**The hard problem: write conflicts.** Two regions edit the same row simultaneously.

Resolution strategies:
- **Last Write Wins (LWW)** — simple, and **silently loses data**. Also relies on clocks, which lie (Chapter 05).
- **Application-level merge** — you write the conflict logic
- **CRDTs** — data types that merge mathematically without conflict (counters, sets, collaborative text). This is how Google Docs and Figma work.

### Leaderless replication (Dynamo style)

Any node accepts a write; the client writes to several and reads from several.

**Quorum:** with N replicas, W write acks, R read responses — if **W + R > N**, a read is guaranteed to see the latest write.

```
N = 3, W = 2, R = 2  →  2 + 2 > 3 ✓  strongly consistent, tolerates 1 node down
N = 3, W = 1, R = 1  →  1 + 1 < 3 ✗  fast, but may read stale data
N = 3, W = 3, R = 1  →  fast reads, but ANY node down blocks all writes
```

Used by Cassandra, DynamoDB, Riak. Tunable per query — which is genuinely useful: strong consistency for a balance check, eventual for a "like" count.

---

## 4.9 Partitioning and Sharding 🟢

**Replication** = the same data in many places (for availability and reads).
**Partitioning** = *different* data in different places (for size and writes).

They are almost always used **together**: each partition is replicated.

```
   PARTITIONING (sharding) — splitting the data
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │  Shard 1   │  │  Shard 2   │  │  Shard 3   │
   │ users A–H  │  │ users I–P  │  │ users Q–Z  │
   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
         │               │               │
   REPLICATION — each shard has copies
   ┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
   │  replica   │  │  replica   │  │  replica   │
   └────────────┘  └────────────┘  └────────────┘
```

### Why partition?

1. **Data does not fit** on one machine
2. **Write throughput** exceeds one machine (replication does not help writes — every replica still applies every write)
3. **Isolation** — per-tenant or per-region separation for compliance

### Vertical vs horizontal partitioning

**Vertical** — split by *column*. Move rarely-used or large columns to another table/store.

```
users                     user_profiles
├── id                    ├── user_id
├── email                 ├── bio (TEXT)
├── password_hash         ├── avatar_url
└── created_at            └── preferences (JSONB)
   (hot, small, cached)      (cold, large)
```

**Horizontal (sharding)** — split by *row*. This is what people mean by "sharding".

### Sharding strategies

**1. Range-based**

```
Shard 1: user_id 1–1,000,000
Shard 2: user_id 1,000,001–2,000,000
```
- ✅ Range queries are efficient; easy to reason about
- ❌ **Hotspots** — sequential IDs mean all new writes hit the last shard. Date-based ranges mean today's shard takes all the traffic.

**2. Hash-based**

```
shard = hash(user_id) % num_shards
```
- ✅ Even distribution
- ❌ Range queries must hit every shard
- ❌ **Resharding is agony** — changing `num_shards` remaps almost every key

**3. Consistent hashing** ⭐

Map both keys and nodes onto a ring; a key belongs to the next node clockwise.

```
          0/360°
            │
    node C ─┼─ node A
            │
    ────────┼────────
            │
        node B
```
- ✅ Adding/removing a node moves only **1/N** of keys, not all of them
- ✅ **Virtual nodes** (each physical node placed at many ring positions) fix uneven distribution
- Used by: Cassandra, DynamoDB, Riak, Memcached clients, most CDNs

**4. Directory-based (lookup table)**

```
lookup_table: { tenant_42 → shard_3, tenant_43 → shard_1, ... }
```
- ✅ Total flexibility; you can move one big tenant to its own shard
- ✅ Rebalancing is just a metadata update (plus a data move)
- ❌ The lookup service is a new dependency and a potential SPOF — cache it aggressively
- **This is the standard choice for multi-tenant SaaS**, and the right one for a per-tenant product

### Choosing a shard key — the decision you cannot easily undo

**A good shard key:**
1. **High cardinality** — many distinct values
2. **Even distribution** — no value dominates
3. **Matches your query pattern** — most queries should hit **one** shard
4. **Does not change** — changing a shard key means moving the row

**Examples:**

| System | Good key | Bad key | Why |
|--------|----------|---------|-----|
| Multi-tenant SaaS | `tenant_id` | `created_at` | Queries are nearly always scoped to one tenant |
| Social network | `user_id` | `post_id` | "Get my feed/posts" hits one shard |
| Chat | `conversation_id` | `message_id` | All messages in a chat live together |
| IoT | `device_id` | `timestamp` | Timestamp = all writes hit one shard |
| E-commerce orders | `customer_id` | `order_status` | Low cardinality; massive hotspot on 'completed' |

### The hard problems sharding creates (know these before you commit)

| Problem | Explanation | Mitigation |
|---------|-------------|------------|
| **Cross-shard joins** | SQL cannot join across machines | Denormalise; or query each shard and join in the app; or keep a separate analytics store |
| **Cross-shard transactions** | No ACID across shards | Sagas (Chapter 05); or design so transactions stay within one shard |
| **Global uniqueness** | `AUTO_INCREMENT` collides | UUID/ULID/Snowflake IDs (see below) |
| **Rebalancing** | Moving data while serving traffic | Consistent hashing + virtual nodes; or directory-based |
| **Hot shard** | One tenant is 40% of your traffic | Split them out; or sub-shard by a composite key |
| **Fan-out queries** | "Search all users" hits every shard; latency = the slowest shard | Keep a separate search index (Elasticsearch) |
| **Operational cost** | 20 shards × 3 replicas = 60 DBs to back up, patch and monitor | Automation, or a managed distributed DB |

### Distributed ID generation

| Method | Pros | Cons |
|--------|------|------|
| **UUIDv4** | Trivial, no coordination | Random → terrible B-tree index locality (page splits, bloat) |
| **UUIDv7 / ULID** | Time-sortable **and** unique — **best default today** | Slightly leaks creation time |
| **Snowflake** (timestamp + machine + sequence) | 64-bit, sortable, high throughput | Needs machine-ID coordination; clock-skew sensitive |
| **DB sequence blocks** | Small, sequential | Needs a central allocator |

> If you take one thing: **use UUIDv7/ULID instead of UUIDv4 for primary keys.** Same uniqueness, far better index behaviour.

### When to shard

> **As late as possible.** Sharding is the most expensive scaling step and the hardest to reverse.

Exhaust these first:
1. Indexes and query optimisation
2. Caching
3. Read replicas
4. Vertical scaling (a 128-core / 2 TB machine is a lot of database)
5. Vertical partitioning / archiving old data
6. Moving non-relational workloads out (search → Elasticsearch, time-series → Timescale/Influx)
7. **Then** shard

**Exception:** if you are building a multi-tenant SaaS, design the **shard key (`tenant_id`) into the schema from day one**, even if all tenants live on one database. Adding a tenant column to every table later is a migration nightmare. The *key* is a day-1 decision; the *splitting* is a later decision.

---

## 4.10 Putting it together: a design walkthrough

**Problem:** Design a URL shortener (the classic). 100 million new URLs/month, 10 billion redirects/month.

**1. Requirements**
- FR: shorten a URL, redirect a short code, basic analytics
- NFR: redirect p99 < 100 ms; 99.99% availability (a dead link is a broken promise); URLs never expire; codes must not be guessable-in-bulk

**2. Estimate**
```
Writes: 100M/month ÷ 2.6M sec ≈ 40/sec        (peak 120/sec)
Reads:  10B/month ÷ 2.6M sec  ≈ 4,000/sec     (peak 12,000/sec)
READ:WRITE = 100:1            ← read-optimised design

Storage: 100M/month × ~500 bytes = 50 GB/month = 600 GB/year
  → 5 years ≈ 3 TB. Fits comfortably on one machine. NO SHARDING NEEDED (yet).

Code length: 62 chars (a-zA-Z0-9)
  62^6 = 56 billion  → 6 characters is plenty for decades
```

**3. API**
```
POST /api/v1/urls          {"longUrl": "...", "customAlias": "..."}  → 201 {"shortUrl": "..."}
GET  /{code}                                                         → 301/302 redirect
GET  /api/v1/urls/{code}/stats                                       → 200 {clicks, ...}
```

**4. Data model**
```sql
CREATE TABLE urls (
    code        VARCHAR(10) PRIMARY KEY,     -- the short code
    long_url    TEXT NOT NULL,
    owner_id    UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);
CREATE INDEX idx_urls_owner ON urls (owner_id, created_at DESC);
```

**5. Code generation — three options, with trade-offs**

| Option | How | Trade-off |
|--------|-----|-----------|
| **Hash + truncate** | `base62(md5(url))[:7]` | Collisions must be detected and retried; same URL → same code (sometimes desirable, sometimes a privacy leak) |
| **Counter + base62** | Global counter, encode it | No collisions ever; but codes are **sequential and enumerable** — anyone can crawl all your links |
| **Pre-generated key pool** ⭐ | A service generates random unused codes into a table; app takes one | No collisions, not enumerable, O(1) — **best choice** |

**6. High-level design**
```
                    ┌─────┐
   Redirect ───────►│ CDN │ (cache 301s at the edge — huge win)
                    └──┬──┘
                       │ miss
                  ┌────▼─────┐
                  │    LB    │
                  └────┬─────┘
              ┌────────┴────────┐
         ┌────▼────┐       ┌────▼────┐
         │ App x N │  ...  │ App x N │  (stateless)
         └────┬────┘       └────┬────┘
              └────────┬────────┘
                  ┌────▼────┐   99% of reads stop here
                  │  Redis  │
                  └────┬────┘
                       │ miss
                  ┌────▼──────┐        ┌──────────────┐
                  │ Postgres  │───────►│ Read replicas│
                  │  (leader) │        └──────────────┘
                  └───────────┘
                       │ async
                  ┌────▼────┐      ┌──────────────┐
                  │  Queue  │─────►│  Analytics   │
                  └─────────┘      │  (ClickHouse)│
                                   └──────────────┘
```

**7. Key decisions and why**
- **Cache everything.** URLs are immutable once created → a perfect cache candidate with infinite TTL. Expect a 98%+ hit ratio.
- **301 vs 302:** 301 (permanent) lets browsers and CDNs cache it — great for load, but you then lose click analytics and can never change the target. **302 keeps control and analytics.** Choose based on whether analytics is the product. Most shorteners use 302.
- **Analytics goes through a queue** — never let click-counting slow down or break a redirect
- **No sharding needed** at this scale; note the trigger for when it would be (~10 TB or write RPS > 5,000)

**8. Failure modes**
- Redis down → fall through to Postgres. Add a small in-process LRU as a second line of defence so a cold Redis does not stampede the DB.
- Postgres leader down → promote a replica; writes pause ~30 s, **reads keep working** (because cache + replicas)
- Analytics queue backed up → clicks are delayed, redirects unaffected. Correct priority.

---

## 4.11 Common mistakes

1. **Designing before estimating** — you cannot know if you need a cache until you know the read:write ratio
2. **Over-engineering for imaginary scale** — sharding for 400 writes/sec
3. **Forgetting the peak factor** — designing for average traffic, dying on Friday night
4. **Stateful app servers** — the number-one blocker to horizontal scaling
5. **Liveness probes that check the database** — turns a blip into a cluster-wide restart loop
6. **Running at 90% utilisation** to "save money"
7. **Scaling the app tier but not the connection pool** — you just DDoS'd your own database
8. **Picking a shard key that matches the write pattern but not the read pattern** (or vice versa)
9. **Assuming replication means no data loss** — async replication loses the tail on failover; say so explicitly
10. **No plan for cache-cold start** — every deploy becomes an outage
11. **Ignoring the network** — 7 synchronous hops × 20 ms is a 140 ms floor before you do any work
12. **Not stating trade-offs** — a design without stated trade-offs is a wish list

---

## 4.12 Architect's checklist

- [ ] DAU, RPS (average **and** peak), storage and bandwidth estimated
- [ ] Read:write ratio calculated — does the design reflect it?
- [ ] Growth projected for 12 and 24 months; trigger points identified
- [ ] Every tier stateless, or state deliberately externalised
- [ ] Little's Law applied: threads, connections and pool sizes checked
- [ ] Target utilisation 50–70%, with N+1 redundancy per availability zone
- [ ] Load balancer: L4/L7 chosen, algorithm chosen, health checks correct
- [ ] Caching strategy defined, including behaviour when the cache is empty or down
- [ ] Replication: sync/async chosen; replication-lag bugs addressed
- [ ] Sharding: needed now? If not, what is the trigger? Is the key designed in anyway?
- [ ] Failure mode identified for every box in the diagram
- [ ] Cost per month and per transaction estimated
- [ ] Trade-offs written down explicitly

---

## 4.13 Self-test

1. 5 million DAU, 20 actions each per day. Average RPS? Peak?
2. 800 RPS, 250 ms per request. How many concurrent requests? How many DB connections?
3. Why does latency explode above ~80% utilisation? What is the rule of thumb target?
4. Give four places state can live if your servers are stateless, with a downside of each.
5. Why should you scale vertically before horizontally? Give the full recommended sequence.
6. What is the difference between liveness and readiness probes, and what is the classic disaster?
7. Explain W + R > N. Give a configuration for "strong consistency, tolerate one node failure" with N=3.
8. Your user saves a profile and immediately sees the old value. Diagnose it and give four fixes.
9. Name four sharding strategies and one situation where each wins.
10. What makes a good shard key? Give a good and a bad key for a multi-tenant SaaS.
11. Why is UUIDv7 better than UUIDv4 as a primary key?
12. When should you shard? List everything you should do first.

---

## 4.14 Key takeaways

- **Estimate before you design.** Five lines of arithmetic produce five architectural decisions.
- **Read:write ratio is the most informative single number** in most systems
- Memorise: **RAM 100 ns, SSD 150 µs, same-DC round trip 0.5 ms, cross-continent 150 ms**
- **Little's Law (L = λW)** turns latency into concurrency into pool sizes
- **Target 50–70% utilisation.** Above 80% latency explodes.
- **Stateless everything you can.** It is the key to horizontal scaling.
- **Optimise → scale up → scale out reads → shard.** In that order. Always.
- **Replication is for availability and reads. Partitioning is for size and writes.** You usually need both.
- **Sharding is the last resort** — but design the shard key early in multi-tenant systems
- Every design must answer: **what happens when each box dies?**

---

**Next:** [Chapter 05 — Distributed Systems](05-distributed-systems.md)
