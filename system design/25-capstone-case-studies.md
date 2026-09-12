# Chapter 25 — Capstone: Six Systems Designed End-to-End 🟢

> Everything in this book, applied.
>
> Each case study follows the same nine-step process from Chapter 00 §0.16. Read one, then cover the page and try the next one yourself before reading the answer. That is where the learning happens.

**The process, every time:**
```
1. UNDERSTAND → 2. CLARIFY → 3. CONSTRAIN → 4. ESTIMATE → 5. SKETCH
→ 6. STRESS-TEST → 7. ALTERNATIVES → 8. DECIDE → 9. VALIDATE
```

---

# Case Study 1 — The Liveness Verification SaaS

*Your own domain. Small scale, high compliance, GPU-bound.*

## 1. Understand

**Problem statement:** *"Today, businesses onboarding customers remotely cannot confirm that the person presenting an ID is physically present and is the document holder, because manual review takes 20 minutes per applicant and catches only obvious fraud — costing them ~15% applicant drop-off and an unquantified fraud loss."*

## 2. Clarify

**Functional:** start a session → upload video → detect liveness and anti-spoofing → match face to document → return a pass/fail/review decision → notify via webhook → reviewer console for borderline cases.

**Non-functional (the 14 questions, abbreviated):**

| NFR | Answer |
|-----|--------|
| Performance | Decision within 30 s p95 (async is acceptable — users expect a short wait) |
| Scale | 1M verifications/month, 2/sec peak |
| Availability | 99.5% — a failed verification can be retried by the user |
| Consistency | Strong for the decision; eventual for dashboards |
| Security | **Biometric data — restricted classification** |
| Compliance | GDPR Art. 9, BIPA. Video deleted at 90 days; decisions retained 7 years |
| Observability | Every decision must be explainable and auditable |
| Cost | Target < $0.03/verification against a $0.15 price |

## 3. Constrain

4 engineers, no platform specialist, 6-month deadline, must run in the EU for residency.

## 4. Estimate

(Full working in Chapter 04 §4.2.)

```
33,000/day · 2/sec peak · 6 MB video · 4 GPU-seconds each
→ ~8 concurrent GPU-seconds at peak → 8 GPU workers at peak, 1 at night
→ Video storage: 17.8 TB at 90-day retention
→ Ingress: 198 GB/day
→ THE CONSTRAINT IS GPU COST AND VIDEO STORAGE, NOT REQUEST RATE
```

## 5. Sketch

```
Mobile/Web
   │ 1. POST /sessions          → 201 + presigned upload URL
   ▼
┌────────┐  2. PUT video (direct)   ┌──────────────┐
│  API   │ ◄──────────────────────► │ Object Store │  (encrypted, 90d lifecycle)
│Fargate │  3. POST /sessions/{}/submit             │
│ 2-6    │                          └──────┬───────┘
└───┬────┘                                 │
    │ 4. enqueue                           │
    ▼                                      │
┌────────┐                                 │
│ Queue  │  (RabbitMQ quorum, DLQ + retry) │
└───┬────┘                                 │
    │ 5. dequeue (KEDA scales on depth)    │
    ▼                                      │
┌──────────────┐ 6. fetch ──────────────────┘
│ GPU Workers  │
│ 1-10, Spot   │ 7. write decision + outbox event
└──────┬───────┘
       ▼
┌──────────┐      ┌──────────────────┐
│ Postgres │─────►│ Webhook Dispatcher│──► customer backend
│ Multi-AZ │      └──────────────────┘
└──────────┘
```

## 6. Stress-test — what if each box dies?

| Failure | Consequence | Mitigation |
|---------|-------------|------------|
| API pod dies | None | 3 AZs, stateless, readiness probes |
| Queue down | No new work processed; API still accepts | Quorum queues; API returns 202 and retries publish via outbox |
| All GPU workers die | Backlog grows | Queue absorbs it; KEDA restarts; alert on queue **age** |
| Spot interruption | A job is interrupted mid-flight | Messages unacked → redelivered. Workers are idempotent. |
| Postgres failover | ~90 s write pause | Multi-AZ; app retries; queue holds work |
| Object storage down | No uploads, no processing | Regional outage → accept (documented in the DR ADR) |
| Vendor model fails | No automated decision | Fall back to manual review — **never auto-pass** |
| Traffic 10× | 20 GPU workers needed | KEDA max = 25; queue buffers; alert on age > 5 min |

## 7–8. Key decisions

| Decision | Why | Rejected alternative |
|----------|-----|---------------------|
| **Modular monolith API + separate GPU worker** | 2/sec does not need microservices. Only the GPU workload needs independent scaling. | Microservices: no force justifies it at 4 engineers |
| **Fargate, not Kubernetes** | No platform engineer. Containers keep portability. | K8s: cluster would become the product (Chapter 15) |
| **Presigned direct upload** | Removes 198 GB/day from the API tier | Upload through the API: memory and timeout risk |
| **Queue between API and worker** | Absorbs peaks, enables autoscaling, no dropped work | Synchronous inference: couples API availability to GPU capacity |
| **Spot GPU instances** | 70–90% cheaper; work is queued and retryable | On-demand: 3× the cost for no benefit |
| **Outbox pattern for webhooks** | Dual-write would silently lose notifications | Publish-after-commit: loses events on crash |
| **Field-encrypted biometrics, per-tenant keys** | Restricted classification; enables crypto-shredding | Disk encryption only: stops no realistic attack |
| **Single region (EU)** | Residency satisfied; a 4 h regional outage is commercially acceptable | Multi-region: 2× cost, unjustified |

**Unit economics:**
```
GPU (Spot, amortised)  $0.008   Storage (tiered, 90d) $0.004
API + queue + DB       $0.003   Egress + misc         $0.002
                                                      ───────
                                              TOTAL   $0.017 / verification
                                              Price   $0.150  → 89% gross margin
```

## 9. Validate

Spike the riskiest assumption first: **can one T4 GPU really do one inference per second on 6-second 720p video?** Three days of work. If it is 0.3/sec, the entire cost model changes and so does the architecture.

---

# Case Study 2 — A Twitter-like Social Feed

*Enormous read scale, eventual consistency, the fan-out problem.*

## 1–3. Understand, clarify, constrain

Post a message; see a timeline of people you follow. 150M DAU. Timeline must load in < 200 ms p95. Eventual consistency is acceptable — nobody notices a 2-second delay on a feed.

## 4. Estimate

(Full working in Chapter 04 §4.2.)
```
3,000 writes/sec · 150,000 reads/sec · READ:WRITE = 50:1
→ read-optimised design is mandatory
→ 450,000 reads/sec at peak CANNOT come from a database
```

## 5. Sketch — the central problem is fan-out

```
FAN-OUT ON READ (pull)          FAN-OUT ON WRITE (push)
On read: query posts from       On write: push the post into every
everyone you follow, merge,     follower's precomputed timeline.
sort.
                                Read  = O(1)  ← one lookup. FAST.
Read  = O(following)  SLOW      Write = O(followers) ← expensive
Write = O(1)          FAST

Good for: users following      Good for: the 99% of normal users
thousands; celebrity accounts   with < 1,000 followers
```

**The answer is hybrid** — and this is the key insight of the design:

```
┌─────────────────────────────────────────────────────────────┐
│  User posts                                                 │
│      │                                                      │
│      ▼                                                      │
│  Post Service ──► Postgres (source of truth, sharded by     │
│      │             user_id) + outbox                        │
│      ▼                                                      │
│  Kafka: "PostCreated"                                       │
│      │                                                      │
│      ▼                                                      │
│  Fanout Service                                             │
│      ├─ followers < 10,000?  → PUSH into each follower's    │
│      │                          Redis timeline (capped 800) │
│      └─ celebrity (> 10,000)? → DO NOT push. Mark the post. │
│                                                             │
│  On READ:                                                   │
│      precomputed timeline from Redis   (99% of the content) │
│    + MERGE recent posts from the handful of celebrities     │
│      this user follows (pulled live, cached 10 s)           │
└─────────────────────────────────────────────────────────────┘
```

**Why hybrid:** pure push means a celebrity with 50 million followers triggers 50 million writes per tweet — a write amplification that no system absorbs gracefully. Pure pull means every timeline read fans out to hundreds of queries. The hybrid pushes for the 99.9% of users where it is cheap, and pulls for the tiny number where it is not.

## 6. Stress-test

| Failure | Mitigation |
|---------|-----------|
| Redis cluster loses a node | Replicas; timeline rebuildable from Postgres (it is a **derived** store — Chapter 10) |
| Fanout service backlog | Kafka buffers; timelines lag by seconds; degrade to more pull |
| Celebrity posts | Excluded from fanout by design |
| Cold cache after a Redis restart | Rebuild the hottest N timelines proactively; fall back to pull |
| A user follows 50,000 accounts | Cap the merge; most are inactive anyway |

## 7–8. Key decisions

| Decision | Why |
|----------|-----|
| **Hybrid fan-out** | Handles both the common case and the celebrity case correctly |
| **Redis for timelines (capped lists)** | 450k reads/sec is only achievable from memory |
| **Kafka between post and fanout** | Decouples write latency from fan-out cost; replayable if fanout has a bug |
| **Postgres sharded by user_id** | Queries are user-scoped; even distribution (Chapter 04) |
| **Media to object storage + CDN** | Media is 100× the text storage; it must never touch app servers |
| **Eventual consistency, with read-your-writes** | A user must see their *own* post immediately — inject it client-side |

---

# Case Study 3 — A Ride-Hailing Matching System

*Geospatial, real-time, low-latency, stateful connections.*

## 1–3. Understand, clarify, constrain

Match a rider to a nearby driver in under 3 seconds. Track driver locations. Handle surge pricing. 100,000 active drivers; 500,000 rides/day.

## 4. Estimate

```
Driver location updates: 100,000 drivers × 1 update/4s = 25,000 writes/sec
  → this is the DOMINANT load, not the ride requests
Ride requests: 500,000/day ÷ 86,400 ≈ 6/sec average, ~25/sec peak
→ The design problem is the LOCATION FIREHOSE, not the matching
```

> **Notice how the estimate reframed the problem.** Everyone assumes "matching" is the hard part. The arithmetic says location ingestion is 1,000× the volume.

## 5. Sketch

```
Drivers ──WebSocket──► Location Gateway ──► Redis Geo (current position, TTL 30s)
  (25k/sec)                  │                     │
                             └──► Kafka ──► Trip History (analytics, cold path)
                                             Postgres/ClickHouse

Rider ──► Matching Service
             │ 1. GEOSEARCH Redis: drivers within 3 km
             │ 2. Filter: available, correct vehicle class, rating
             │ 3. Score: ETA (road distance, not straight line), rating, acceptance rate
             │ 4. Offer to the best driver via their WebSocket → 15 s to accept
             │ 5. Declined/timeout → offer to the next
             ▼
        Trip Service ──► Postgres (source of truth for trips, payments)
```

**The key insight: separate the hot path from the cold path.** Current location is ephemeral, needs sub-millisecond reads, and is worthless after 30 seconds → Redis with a TTL. Historical location is analytical, append-only, and valuable forever → Kafka to a columnar store. **Two different stores because they are two different problems** (Chapter 10).

## 6. Stress-test

| Failure | Mitigation |
|---------|-----------|
| Redis Geo down | **Matching stops.** Critical path. → Redis Cluster, multi-AZ; drivers re-register within 30 s of recovery |
| Location gateway restarts | 100,000 WebSockets reconnect at once → **stagger reconnection with jitter** (Chapter 05) |
| No drivers nearby | Widen the radius progressively; then surge pricing; then an honest "no drivers available" |
| Driver accepts, then cancels | State machine handles it; re-offer; track cancellation rate |
| Two riders matched to one driver | **Atomic claim in Redis** (`SET driver:x:claimed NX`) — the classic race condition |
| Surge calculation wrong | Cap the multiplier; audit every surge decision |

## 7–8. Key decisions

| Decision | Why |
|----------|-----|
| **Redis Geo for current position** | Sub-millisecond radius search; TTL gives automatic cleanup of stale drivers |
| **WebSocket for drivers, not polling** | 100,000 drivers polling every 4 s is the same load with worse latency and no push channel |
| **Kafka for the location firehose** | 25,000/sec, many consumers (analytics, ETA models, fraud), replayable |
| **Atomic claim before offering** | Prevents double-matching — a correctness requirement, not an optimisation |
| **Sharded geographically** | Cities are independent; a Dhaka incident must not affect Delhi (cell-based, Chapter 19) |
| **Trips in Postgres** | Money and legal records need ACID and audit, not eventual consistency |

---

# Case Study 4 — A Multi-Tenant B2B Analytics Platform

*Tenant isolation, noisy neighbours, wildly varying tenant sizes.*

## 1–3. Understand, clarify, constrain

Customers upload event data and query dashboards. 500 tenants ranging from 10,000 to 2 billion events. Enterprise customers demand data isolation guarantees and, in some cases, their own region.

## 4. Estimate

```
Ingestion: 50,000 events/sec aggregate
Query:     ~200 dashboard queries/sec, each scanning millions of rows
Storage:   ~40 TB/year compressed
Tenant skew: the largest tenant is 40% of all data   ← THE critical fact
```

## 5. Sketch — the tenancy model is the whole design

```
THREE MODELS (Chapter 04 sharding, applied to tenancy)

A. SHARED everything, tenant_id column
   ✅ cheapest, simplest ops       ❌ noisy neighbours, weakest isolation story

B. SHARED app, DATABASE PER TENANT
   ✅ strong isolation, easy per-tenant backup/restore/delete
   ❌ 500 databases to migrate and monitor

C. FULL STACK PER TENANT
   ✅ total isolation              ❌ unaffordable below enterprise pricing

→ TIERED, which is what mature SaaS actually does:
   Standard tier   → model A (shared, RLS-enforced)
   Business tier   → model B (dedicated schema/database)
   Enterprise tier → model C (dedicated deployment, own region)
```

```
Ingest API ──► Kafka (partitioned by tenant_id) ──► ClickHouse
                                                     (columnar, per-tenant
                                                      partitioning + quotas)
Query API  ──► Query router: resolves tenant → cluster/schema
                  │
                  ├─ per-tenant rate limit and query-cost budget
                  ├─ row-level security enforced at the database
                  └─ result cache keyed BY TENANT
```

## 6. Stress-test

| Failure | Mitigation |
|---------|-----------|
| **One tenant runs a query scanning 2 billion rows** | Per-tenant query cost limits and timeouts; separate query pool per tier (**bulkhead**) |
| One tenant's ingestion spikes 100× | Kafka partition per tenant; per-tenant ingest quotas |
| Cross-tenant data leak | Tenant in every cache key; RLS at the database; **automated cross-tenant tests** (Chapters 17, 21) |
| A tenant demands full deletion | Per-tenant encryption keys → crypto-shred; plus physical delete of partitions |
| The largest tenant outgrows its shard | Directory-based sharding lets you move one tenant to dedicated infrastructure |

## 7–8. Key decisions

| Decision | Why |
|----------|-----|
| **`tenant_id` in the schema and in every key from day one** | Retrofitting tenancy is a migration nightmare (Chapter 04) |
| **Directory-based sharding** | Lets you relocate a single large tenant without rehashing everything |
| **Postgres RLS + application checks** | Defence in depth on the highest-impact bug class (Chapter 17) |
| **ClickHouse for analytics** | Columnar; 10–30× compression; scans that Postgres cannot serve (Chapters 10, 12) |
| **Per-tenant quotas and bulkheads** | The noisy-neighbour problem is *the* multi-tenant failure mode |
| **Tiered isolation model** | Matches cost to price; enterprise isolation is a feature they pay for |

---

# Case Study 5 — An E-Commerce Checkout and Order Flow

*Distributed transactions, money, inventory, and the classic saga.*

## 1–3. Understand, clarify, constrain

Place an order: reserve inventory, take payment, create a shipment, send confirmation. Must never double-charge. Must never oversell. 50,000 orders/day, with 20× spikes during sales events.

## 4. Estimate

```
50,000/day ≈ 0.6/sec average · 12/sec during a sale · 100+/sec in the first minute
→ The SPIKE is the design driver, not the average
```

## 5. Sketch — an orchestrated saga

```
                    ┌─────────────────────────┐
   POST /orders ───►│   Order Orchestrator    │  (Temporal / Step Functions)
                    │   persists saga state   │
                    └──┬──────┬──────┬────────┘
                       │      │      │
   1. Reserve inventory│      │      │      compensate: release reservation
      ┌────────────────▼──┐   │      │
      │ Inventory Service │   │      │
      └───────────────────┘   │      │
   2. AUTHORISE payment ──────┘      │      compensate: void the authorisation
      ┌───────────────────┐          │        (invisible to the customer!)
      │ Payment Service   │          │
      └───────────────────┘          │
   3. Create shipment ───────────────┘      compensate: cancel shipment
      ┌───────────────────┐
      │ Shipping Service  │
      └───────────────────┘
   4. CAPTURE payment  ← only after everything else succeeded
   5. Publish OrderConfirmed → email, analytics, warehouse (all async)
```

**The single most important design decision here is the ordering** (Chapter 05 §5.7):

```
❌ BAD:  charge card → reserve inventory → (out of stock) → refund
         The customer sees a charge and a refund. Support tickets. Trust damage.

✅ GOOD: reserve inventory → AUTHORISE → ship → CAPTURE
         An authorisation hold can be released invisibly. The customer never
         sees a charge that gets reversed.
```

That is a **business** insight expressed in architecture, and it removes most of the compensation pain before any code is written.

## 6. Stress-test

| Failure | Mitigation |
|---------|-----------|
| Payment succeeds, response lost | **Idempotency key** → retry returns the original result (Chapter 05) |
| Orchestrator crashes mid-saga | Saga state persisted; Temporal resumes automatically |
| Inventory reserved but payment fails | Compensation releases it; reservations also have a TTL as a backstop |
| Compensation itself fails | **Alert a human.** Never swallow it. Manual reconciliation queue. |
| Sale spike: 100 orders/sec | Queue-based levelling; inventory reservation is the only synchronous hot path |
| Two customers, last item | Atomic `UPDATE stock = stock - 1 WHERE id = ? AND stock > 0` + a `CHECK (stock >= 0)` constraint (Chapter 09) |
| Shipping provider down | Order confirmed; shipment queued and retried; customer is informed honestly |

## 7–8. Key decisions

| Decision | Why |
|----------|-----|
| **Orchestrated saga, not choreographed** | 4 steps with money and compensation — the visibility is worth the coordinator (Chapter 05) |
| **Authorise then capture** | Makes the common failure invisible to the customer |
| **Idempotency keys on every step** | Retries are guaranteed; double charges are not acceptable |
| **Durable orchestrator (Temporal)** | Hand-rolled orchestrators lose sagas on restart |
| **Inventory constraint in the database** | Application bugs cannot oversell (Chapter 09) |
| **Everything post-confirmation is async** | Email, analytics and warehouse must never block or fail a sale |

---

# Case Study 6 — Legacy Modernisation at a Bank

*The most common real enterprise assignment. No greenfield anywhere.*

## 1–3. Understand, clarify, constrain

A 20-year-old monolithic core banking system (COBOL + Oracle). The bank wants a mobile app with real-time balances and instant transfers. **The core cannot be modified** — vendor contract, no source access, 6-month change queue. Nightly batch processing means balances are a day old. Strict regulation; every change requires an audit trail.

## 4. Estimate

```
2 million customers · 400,000 daily mobile sessions · 12/sec peak balance checks
→ The core mainframe cannot serve 12/sec of anything — its API is rated at 2/sec
→ Therefore: a READ MODEL outside the core is mandatory, not optional
```

## 5. Sketch — Strangler Fig with CDC

```
┌──────────────────────────────────────────────────────────────┐
│  PHASE 1: read-only, no risk                                 │
│                                                              │
│  Core (Oracle) ──CDC (Debezium)──► Kafka ──► ACL ──► Read    │
│   [UNTOUCHED]                                         Model  │
│                                                     (Postgres)│
│                                                         ▲     │
│  Mobile App ──► API Gateway ──► Account Service ────────┘     │
│                                 (balances, history: FAST)     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  PHASE 2: writes, still through the core                     │
│                                                              │
│  Mobile ──► Transfer Service ──► ACL ──► Core's SOAP API      │
│                    │                     (2/sec limit)        │
│                    └──► queue + rate limiter + circuit breaker│
│               (the queue absorbs the mismatch between         │
│                mobile demand and mainframe capacity)          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  PHASE 3+: strangle one capability at a time                 │
│                                                              │
│  Facade routes: /balances  → new service (owns the data now)  │
│                 /transfers → new service                      │
│                 /loans     → still the core                   │
│  Core shrinks. Each step is independently valuable.           │
└──────────────────────────────────────────────────────────────┘
```

## 6. Stress-test

| Failure | Mitigation |
|---------|-----------|
| CDC stream lags | Show the balance with an "as of" timestamp — **honesty beats a wrong number**; alert on lag > 60 s |
| Core's Sunday maintenance window | Queue transfers; tell the user "will complete by 07:00"; never lose the intent |
| Core schema changes without notice | ACL fails loudly on unknown shapes (Chapter 24); contract tests against a captured schema |
| Read model diverges from the core | **Daily reconciliation** — compare balances; alert on any mismatch (Chapter 24) |
| Transfer submitted twice | Idempotency key held in the new service; the core sees one request |
| Regulator asks "prove this transfer" | Every request/response retained 7 years; full audit trail from the outset |

## 7–8. Key decisions

| Decision | Why |
|----------|-----|
| **CDC from the core's database** | The only way to get near-real-time data from a system you may not modify (Chapter 24) |
| **ACL immediately after CDC** | Converts their table shapes into our events — the contract they never gave us |
| **Read model in Postgres** | 12/sec of reads that the mainframe could never serve |
| **Core remains the system of record** (Phase 1–2) | Non-negotiable during transition; the read model is explicitly **derived** |
| **Queue + rate limiter in front of the core API** | Protects a fragile 2/sec system from mobile-scale demand |
| **Strangler Fig, capability by capability** | A big-bang core replacement at a bank is a well-documented way to fail |
| **Balances shown with an explicit timestamp** | Regulatory honesty; and it makes eventual consistency a *feature* rather than a bug |
| **Daily reconciliation from day one** | Drift between a core and a read model is certain; find it in a day |

---

# 25.7 The patterns that recurred

Look back across all six. The same small set of ideas solved very different problems:

| Pattern | Appeared in | Chapter |
|---------|------------|---------|
| **Queue-based load levelling** | 1, 4, 5, 6 | 06 |
| **Anti-Corruption Layer** | 1, 6 | 03 |
| **Outbox pattern** | 1, 5 | 06 |
| **Idempotency keys** | 1, 5, 6 | 05 |
| **Circuit breaker + fallback** | 1, 6 | 05 |
| **Derived store, rebuildable** | 2, 4, 6 | 10 |
| **Separate hot path from cold path** | 3, 4 | 10, 12 |
| **Bulkhead / per-tenant quota** | 1, 4 | 05 |
| **Saga with compensation** | 5 | 05 |
| **Strangler Fig** | 6 | 00, 24 |
| **Reconciliation** | 4, 6 | 24 |
| **Estimate reframes the problem** | 1, 2, 3, 6 | 04 |

> **That last row is the most important.** In four of six cases, the back-of-envelope arithmetic changed what the problem *was*: the liveness system's constraint was GPU cost, not RPS; the social feed's was the 50:1 read ratio; ride-hailing's was location ingestion, not matching; the bank's was that the mainframe could not serve the read load at all.
>
> **Estimate before you design. It tells you what you are actually building.**

---

# 25.8 A design interview / review script

Whether you are in an interview or reviewing a colleague's design, this is the sequence.

```
MINUTE 0-5    REQUIREMENTS
  "Let me make sure I understand the problem…"
  Functional scope — and say explicitly what you are excluding.
  NFRs: scale, latency, availability, consistency, compliance, cost.

MINUTE 5-10   ESTIMATION
  DAU → RPS → peak → storage → bandwidth.
  Say out loud what the numbers imply:
  "50:1 read/write means this must be read-optimised."

MINUTE 10-15  API AND DATA MODEL
  The 3-5 core operations. The core entities. Where each fact lives and who owns it.

MINUTE 15-30  HIGH-LEVEL DESIGN
  Boxes and arrows. Happy path first. Label every arrow with protocol and payload.

MINUTE 30-40  DEEP DIVE
  Pick the 1-2 genuinely hard parts and go deep. (Interviewer will steer.)

MINUTE 40-50  SCALE AND FAILURE
  "What breaks at 10×?"  "What if this box dies?" for every box.
  Bottleneck → the fix → the new bottleneck.

MINUTE 50-60  TRADE-OFFS
  State what you gave up. Name the alternatives you rejected and why.
  Give the trigger that would make you revisit.
```

**What distinguishes a strong performance:**

| Weak | Strong |
|------|--------|
| Starts drawing immediately | Clarifies requirements first |
| Guesses at scale | Estimates out loud, and uses the result |
| One design, presented as correct | 2–3 options with honest trade-offs |
| Only the happy path | Walks every failure mode |
| Buzzwords | "We need Kafka **because** we need replay for the fraud backfill" |
| Over-engineers | Matches the design to the actual numbers and the actual team |
| Silent | Thinks out loud, so the reasoning is visible |
| Defensive about gaps | *"I don't know — here's how I'd find out"* |

> **The single strongest signal you can give: reduce scope deliberately and say so.** *"For this design I'll focus on the core verification flow and treat billing and the reviewer console as out of scope, though I'll note where they attach."* That sentence demonstrates judgement, which is the entire job.

---

# 25.9 Exercises — design these yourself

Use the nine-step process. Timebox each to 45 minutes. Write down your estimates, your failure modes and your trade-offs before you look anything up.

1. **A payment gateway** — idempotency, PCI scope reduction, reconciliation, multiple acquirers with failover
2. **A notification service** — email/SMS/push, per-user preferences, rate limiting, deduplication, provider failover, delivery tracking
3. **A video streaming platform** — transcoding pipeline, adaptive bitrate, CDN strategy, DRM, live vs on-demand
4. **A collaborative document editor** — real-time sync, conflict resolution (CRDT vs OT), presence, offline support
5. **An IoT telemetry platform** — 1M devices, intermittent connectivity, time-series storage, alerting rules, over-the-air updates
6. **A job scheduler** — cron at scale, exactly-once execution, distributed locking, backfills, dependency graphs
7. **A fraud detection system** — real-time scoring, feature store, model deployment and rollback, feedback loop, explainability
8. **A search platform** — indexing pipeline, relevance tuning, faceted search, autocomplete, index rebuild strategy

**For each, answer these before you start drawing:**
```
- What is the read:write ratio, and what does it imply?
- What is the ONE resource that constrains this system?
- Which operations need strong consistency, and which do not?
- What is the degraded mode?
- What does it cost per transaction?
- What would you build first, and what would you defer?
```

---

# 25.10 Key takeaways

- **Follow the same nine-step process every time.** Discipline beats inspiration.
- **Estimate early — it reframes the problem.** In most of these cases the arithmetic revealed that the obvious "hard part" was not the constraint.
- **Identify the one constraining resource**: GPU cost, read volume, location ingestion, tenant skew, mainframe throughput. The architecture follows from it.
- **Design the failure path as carefully as the happy path.** "What if this box dies?" for every box.
- **Separate hot paths from cold paths**, and **source-of-truth stores from derived stores**
- **Ordering of steps is a design decision** — authorise-then-capture removes most compensation pain
- **A small set of patterns solves most problems**: queue-based levelling, ACL, outbox, idempotency, circuit breaker + fallback, derived stores, bulkheads, sagas, strangler fig, reconciliation
- **Match the design to the team, the numbers, and the constraints** — not to what is fashionable
- **State your trade-offs out loud**, and give the trigger to revisit

---

**Appendices:** [A — Glossary](appendix-a-glossary.md) · [B — Cheat Sheets](appendix-b-cheatsheets.md) · [C — 12-Month Roadmap](appendix-c-roadmap.md)
