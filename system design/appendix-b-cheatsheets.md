# Appendix B — Cheat Sheets

Everything you should be able to recall or look up in ten seconds. Print the ones you use.

---

## B.1 Latency numbers

| Operation | Time | Relative |
|-----------|------|----------|
| L1 cache reference | 1 ns | 1× |
| Branch mispredict | 3 ns | 3× |
| L2 cache reference | 4 ns | 4× |
| Mutex lock/unlock | 17 ns | 17× |
| **Main memory reference** | **100 ns** | **100×** |
| Compress 1 KB (Snappy) | 2 µs | 2,000× |
| Send 1 KB over 1 Gbps | 10 µs | 10,000× |
| **Random 4 KB read from SSD** | **150 µs** | **150,000×** |
| Read 1 MB sequentially from memory | 250 µs | |
| **Round trip in same datacenter** | **500 µs** | **500,000×** |
| Read 1 MB sequentially from SSD | 1 ms | |
| **Disk seek (HDD)** | **10 ms** | **10,000,000×** |
| Read 1 MB sequentially from HDD | 20 ms | |
| **Cross-continent round trip** | **150 ms** | **150,000,000×** |

**Three rules:** memory fast, disk slow, network slower, cross-continent slowest · sequential beats random by 10–100× · **avoid the round trip**.

---

## B.2 Availability

| SLA | Per year | Per month | Per week |
|-----|----------|-----------|----------|
| 99% | 3.65 days | 7.3 h | 1.68 h |
| 99.5% | 1.83 days | 3.65 h | 50 min |
| **99.9%** | **8.77 h** | **43.8 min** | **10.1 min** |
| 99.95% | 4.38 h | 21.9 min | 5 min |
| **99.99%** | **52.6 min** | **4.4 min** | **1 min** |
| 99.999% | 5.26 min | 26 s | 6 s |

**Combined availability of a synchronous chain = the product.**
```
0.999^3 = 99.7%   |   0.999^5 = 99.5%   |   0.999^10 = 99.0%
```

---

## B.3 Estimation shortcuts

```
1 day             = 86,400 s        → use 100,000
1 month           = 2.6 million s
1 year            = 31.5 million s  → use 30 million

RPS from daily    = daily ÷ 100,000
Peak from average = ×3 (unknown) · ×10 (consumer/viral) · ×2 (B2B steady)
1 million/month   ≈ 0.4/sec
1 billion/month   ≈ 400/sec
GB/day            = RPS × KB × 0.086

Rule of 72: months to double = 72 ÷ monthly growth %
```

**Sizes:** UUID 16 B (36 as string) · timestamp 8 B · tweet ~1 KB · JSON response 1–10 KB · phone photo 2–5 MB · minute of 1080p video 50–100 MB

**Cloud costs (order of magnitude):** small VM $30–70/mo · 1 TB hot object storage ~$20/mo · archive ~$1/mo · egress ~$0.05–0.09/GB

---

## B.4 Little's Law and capacity

```
L = λ × W          concurrency = arrival rate × time in system

800 RPS × 250 ms = 200 concurrent → 200 threads/connections needed
200 threads ÷ 400 ms = 500 RPS max throughput per server
```

**Utilisation → queueing delay multiplier:**

| Utilisation | Delay | |
|---|---|---|
| 50% | 2× | ✅ |
| **70%** | **3.3×** | ✅ **target ceiling** |
| 80% | 5× | ⚠️ |
| 90% | 10× | ❌ |
| 95% | 20× | ❌ |

**Capacity formula:**
```
instances = (peak_RPS ÷ RPS_per_instance) ÷ target_utilisation × AZ_redundancy_factor
AZ factor with 3 AZs surviving one loss = 1.5
```

---

## B.5 CAP / PACELC decision

```
During a partition:  error (CP)  or  stale data (AP)?
Otherwise:           latency (L) or  consistency (C)?

CP → money, inventory, bookings, auth, medical
AP → feeds, counts, recommendations, carts, presence

Systems:  Postgres PC/EC · MongoDB PA/EC · Cassandra PA/EL
          DynamoDB PA/EL · Spanner PC/EC · etcd/ZooKeeper CP
```

**Consistency models, strongest → weakest:**
```
Linearizable → Sequential → Causal → Read-your-writes
→ Monotonic reads → Monotonic writes → Eventual
```

**Choose per operation, not per system.**

---

## B.6 Reliability patterns — the seven

| Pattern | Purpose | Key setting |
|---------|---------|-------------|
| **Timeout** | Never wait forever | p99 × 1.5; decrease with depth |
| **Retry** | Survive transient failure | 3 attempts, exponential, **full jitter**, idempotent only |
| **Circuit breaker** | Stop calling a dead dependency | 50% failures over 20 calls, 15 s break |
| **Bulkhead** | Contain resource exhaustion | Separate pool per dependency |
| **Rate limit** | Protect from overload | Token bucket; return `Retry-After` |
| **Load shedding** | Serve most, not none | Drop by priority above a threshold |
| **Graceful degradation** | Partial > nothing | Defined fallback per feature |

**Full jitter:** `sleep = random(0, base × 2^attempt)`

**Retry these:** 429, 502, 503, 504, timeouts, connection errors
**Never retry:** 400, 401, 403, 404, 422

---

## B.7 Idempotency quick reference

| Method | Safe | Idempotent |
|--------|------|-----------|
| GET / HEAD | ✅ | ✅ |
| PUT | ❌ | ✅ |
| DELETE | ❌ | ✅ |
| **POST** | ❌ | **❌** |
| PATCH | ❌ | depends |

**Making things idempotent:**
1. Idempotency key + stored response + request fingerprint
2. Dedup table, in the same transaction as the work
3. Absolute values, not increments (`SET x = 5`, not `x += 1`)
4. `INSERT ... ON CONFLICT DO NOTHING`
5. State-machine guard (already in the target state → return)

> **Exactly-once delivery does not exist.** At-least-once + idempotent processing = exactly-once processing.

---

## B.8 HTTP status codes

| Code | Meaning | Use |
|------|---------|-----|
| 200 / 201 / 202 / 204 | OK / Created (+`Location`) / Accepted / No Content | |
| 301 / 302 / 304 | Moved / Found / **Not Modified** | 304 saves bandwidth |
| **400** | Cannot parse | Malformed syntax |
| **401** | **Who are you?** | Not authenticated |
| **403** | **I know you, and no** | Not authorised |
| 404 | Not found | **Also use for cross-tenant denial** |
| 409 | Conflict | Duplicate, concurrent edit |
| 412 | Precondition failed | `If-Match` mismatch |
| **422** | Parsed, semantically invalid | Validation errors |
| **429** | Rate limited | **Must include `Retry-After`** |
| 500 / 502 / 503 / 504 | Server error / bad gateway / unavailable / gateway timeout | |

> **Never** `200 {"success": false}`.

**Rate limit headers:** `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `Retry-After`

---

## B.9 API design checklist

```
□ Nouns in URLs, verbs as methods, lowercase-hyphenated
□ Cursor pagination, capped limit
□ Filter/sort fields whitelisted AND indexed
□ Idempotency-Key on side-effecting POSTs
□ ETag + If-Match on updates
□ Problem Details (RFC 9457) errors with a trace ID
□ Cache-Control + Vary set deliberately
□ /v1/ path version; additive changes only; tolerant reader documented
□ Deprecation + Sunset headers; per-client usage measured
□ OpenAPI spec; breaking-change check in CI
□ Payload size limit and request timeout
```

---

## B.10 Database quick reference

**Isolation levels:**

| Level | Dirty read | Non-repeatable | Phantom | Lost update | Write skew |
|-------|-----------|----------------|---------|-------------|------------|
| Read Uncommitted | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Read Committed** (default) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Repeatable Read (PG) | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Serializable** | ❌ | ❌ | ❌ | ❌ | ❌ |

> SERIALIZABLE **requires retry logic** for SQLSTATE 40001.

**Preference order for protecting an invariant:**
```
CHECK constraint > atomic UPDATE > optimistic lock > pessimistic lock > SERIALIZABLE
```

**Index column order:** equality → range → sort

**Index types:** B-tree (default) · GIN (JSONB, arrays, FTS) · GiST (geo, ranges, exclusion) · BRIN (huge, ordered) · partial (`WHERE status='pending'`) · covering (`INCLUDE`)

**EXPLAIN red flags:**
```
Seq Scan on a big table with a selective filter → missing index
rows=1 but actual rows=450000                   → stale stats, run ANALYZE
Sort Method: external merge Disk: 84MB          → raise work_mem
Rows Removed by Filter: 2000000                 → index not selective
Buffers: shared read=50000                      → working set > RAM
```

**Safe migrations:** expand → backfill → migrate reads → contract. `CREATE INDEX CONCURRENTLY`. `ADD CONSTRAINT ... NOT VALID` then `VALIDATE`. Always set `lock_timeout`.

---

## B.11 Caching

**Patterns:** cache-aside (default) · read-through · write-through · write-behind (loss-tolerant only) · refresh-ahead

**On write: invalidate, do not update.**

**TTL guide:**
```
Reference data      hours-days      Search results    1-5 min
Product catalogue   5-60 min        Session           = timeout, sliding
User profile        5-15 min        Prices/inventory  seconds or never
Permissions         1-5 min MAX     Negative (404)    30-60 s
```

**Always add jitter:** `ttl ± 10%`

**Key format:** `app:v{schema}:{entity}:{tenant}:{id}` — namespace, version, **tenant**, everything that varies the result.

**The three disasters:**
```
STAMPEDE    → lock/single-flight · probabilistic early expiry · serve-stale
PENETRATION → negative caching · input validation · bloom filter
AVALANCHE   → TTL jitter · warming · two-tier · circuit breaker on the DB
```

**Hit ratio maths:** 95% → 99% removes **80% of remaining** database load.

---

## B.12 Sharding

**Strategies:** range (hotspots) · hash (no range queries, hard to reshard) · **consistent hashing** (moves 1/N) · **directory** (best for multi-tenant)

**Good shard key:** high cardinality · even distribution · matches query patterns · never changes

| System | Good | Bad |
|--------|------|-----|
| Multi-tenant SaaS | `tenant_id` | `created_at` |
| Social | `user_id` | `post_id` |
| Chat | `conversation_id` | `message_id` |
| IoT | `device_id` | `timestamp` |

**Order of scaling:**
```
1. Optimise (indexes, N+1, caching)   ← usually 10-100×, costs nothing
2. Scale up (bigger machine)
3. Scale out stateless tier
4. Read replicas
5. Vertical partitioning / archiving
6. Move workloads out (search, time-series)
7. Shard                               ← LAST
```

**IDs:** UUIDv7 / ULID (sortable, index-friendly) > Snowflake > UUIDv4 (poor locality)

---

## B.13 Messaging

**Delivery:** at-most-once (loss) · **at-least-once (default)** · exactly-once processing = at-least-once + idempotency

**Ordering:** global (never worth it) · partition · **per-key (what you actually need)** · or make consumers order-insensitive

**RabbitMQ vs Kafka:**

| | RabbitMQ | Kafka |
|---|---|---|
| Model | Smart broker | Replayable log |
| After consumption | Deleted | Retained |
| Replay | ❌ | ✅ |
| Per-message retry/DLQ | ✅ built in | Manual |
| Routing | Rich | Topic + key |
| Throughput | 10s of thousands/s | Millions/s |
| Use for | Task queues, RPC, routing | Event streams, replay, volume |

**RabbitMQ durability — all three required:** `queue durable=True` + `delivery_mode=2` + manual ack after work. Plus publisher confirms.

**Kafka production baseline:** `acks=all` · `enable.idempotence=true` · `replication.factor=3` · `min.insync.replicas=2` · manual commits after processing · `CooperativeStickyAssignor`

**Alert on queue AGE, not just depth.**

---

## B.14 Kubernetes essentials

```yaml
resources:
  requests: { cpu: 200m, memory: 256Mi }   # scheduling; ALWAYS set
  limits:   { memory: 256Mi }              # == request; CPU limits cause throttling

livenessProbe:  /health/live    # process only — NEVER a dependency
readinessProbe: /health/ready   # dependencies OK
startupProbe:                   # protects slow starters

lifecycle:
  preStop: { exec: { command: ["sleep", "10"] } }   # endpoint propagation
terminationGracePeriodSeconds: 60
```

**CPU throttles. Memory kills.**

**QoS eviction order:** BestEffort → Burstable → Guaranteed (last)

**Zero-downtime deploy requires all three:** preStop sleep + SIGTERM handling + PodDisruptionBudget.

**Autoscale workers on queue depth (KEDA), not CPU.**

---

## B.15 Security quick reference

**Password hashing:** Argon2id > scrypt > bcrypt > PBKDF2. Never SHA-*.

**OAuth flows:** ✅ Authorization Code + **PKCE** (everything user-facing) · ✅ Client Credentials (M2M) · ❌ Implicit · ❌ Password grant

**JWT validation must pin:** `alg`, `aud`, `iss`, `exp`. JWTs are **base64, not encrypted**.

**Token lifetimes:** access 5–15 min · refresh rotating with reuse detection.

**OWASP Top 10:** A01 broken access control (**#1**) · A02 crypto failures · A03 injection · A04 insecure design · A05 misconfiguration · A06 vulnerable components · A07 auth failures · A08 integrity failures · A09 logging failures · A10 SSRF

**Security headers:**
```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; object-src 'none'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

**Cookies:** `HttpOnly; Secure; SameSite=Lax`

**Multi-tenant isolation — three layers:**
1. Scope every query by the authenticated principal
2. Row-Level Security at the database
3. Automated cross-tenant tests asserting **404**, not 403

**STRIDE:** Spoofing · Tampering · Repudiation · Information disclosure · DoS · Elevation of privilege

---

## B.16 Observability

**Golden signals:** Latency (split by outcome!) · Traffic · Errors · Saturation

**Never put in a metric label:** user ID, session ID, trace ID, URL with parameters, error message. **Cardinality explosion.**

**Percentiles, not averages.** `avg(p99)` is meaningless.

**SLO maths:**
```
99.5% over 30 days = 3 h 39 min error budget
Burn rate 14× → budget gone in ~2 days → PAGE
Burn rate 6×  → gone in ~5 days        → PAGE
Burn rate 1×  → on track               → ticket
```

**Alert rules:** symptoms not causes · every alert has a runbook · every alert has a human action · delete noisy alerts.

**Every log line needs:** timestamp, level, service, version, **trace_id**, tenant_id, and structured fields. **Never** secrets or PII.

**Return the trace ID to the client.**

---

## B.17 DR patterns

| Pattern | RTO | RPO | Cost |
|---------|-----|-----|------|
| Backup & restore | hours–days | hours | $ |
| **Pilot light** | 10 min–2 h | seconds–min | $$ |
| Warm standby | 5–30 min | seconds | $$$ |
| Active-active | ~0 | ~0 | $$$$$$ |

**3-2-1-1-0:** 3 copies · 2 media · 1 off-site · **1 immutable** · **0 errors (verified by restore)**

> **HA ≠ DR.** Replication propagates `DELETE FROM orders` perfectly.

**AZ capacity:** with 3 AZs surviving one loss → run **1.5×** the minimum required capacity.

**Restore drill: quarterly, timed, performed by someone who did not write the runbook.**

---

## B.18 Performance

**Amdahl:** optimising a part that is 20% of the time gives at most a 20% improvement.

**USE per resource:** Utilisation · **Saturation** · Errors

**Top causes, in order:** N+1 · missing index · serial network calls · no caching · pool exhaustion · over-fetching · serialisation · lock contention · GC · algorithms

**Techniques, by usual payoff:** do less → batch → parallelise → cache → move out of the request path → smaller payloads → pool → async I/O → index

**Load test types:** load (meets SLO?) · stress (where does it break?) · **soak (leaks — the one people skip)** · spike

**Coordinated omission** makes naive load-test p99 an order of magnitude too optimistic.

**Query-count budget test** is the highest-value regression guard you can add.

---

## B.19 The decision tables

**Architecture style:**
```
< 10 devs, unclear domain          → modular monolith
10-30 devs, some parts differ      → modular monolith + 2-4 services
50+ devs, clear contexts, mature   → microservices
Spiky/low traffic, glue, cron      → serverless
Audit and "why" legally required   → event sourcing (those aggregates only)
Complex rules, long-lived          → hexagonal/clean inside any topology
Simple CRUD                        → layered or vertical slices
```

**Datastore:**
```
Sub-ms key lookup, loss OK         → Redis
Durable KV at scale, managed       → DynamoDB
Whole-object reads, flexible shape → MongoDB (but check Postgres JSONB first)
Huge writes, multi-DC, time-ordered→ Cassandra / ScyllaDB
Deep relationship traversal        → Neo4j
Metrics/events over time ranges    → TimescaleDB / ClickHouse
Relevance search, facets           → Elasticsearch (DERIVED, never source of truth)
Similarity/embeddings              → pgvector first
Everything else                    → PostgreSQL
```

**Compute:**
```
OS control / licensed software     → VMs
Event-driven, spiky, low volume    → Functions
10+ services, platform team exists → Kubernetes
Everything else                    → serverless containers ⭐
```

**API style:**
```
Public third-party API             → REST + OpenAPI
Internal, high volume              → gRPC
Many clients, varied screens       → GraphQL or a BFF
Server → browser push              → SSE ⭐ (not WebSocket)
Two-way real-time                  → WebSocket
Notify another company             → Webhooks (+ polling fallback)
Bulk data                          → file export + signed URL
```

---

## B.20 The architect's one-page checklist

```
PROBLEM
□ One sentence, with a number in it
□ Would doing nothing be acceptable?

REQUIREMENTS
□ Functional listed
□ All 14 NFRs asked
□ Quality attributes RANKED for this system
□ Constraints: technical, business, organisational
□ Assumptions listed, each with an owner
□ Risks listed with mitigation

ESTIMATE
□ DAU → RPS → peak → storage → bandwidth
□ Read:write ratio, and what it implies
□ Growth for 12 and 24 months
□ Cost per month AND per transaction

DESIGN
□ 2-3 alternatives considered in writing
□ Trade-offs stated — what we GIVE UP
□ Data ownership: one owner per fact
□ Consistency model per operation
□ Every box: what happens when it dies?
□ What breaks at 10×?
□ Degraded mode per non-critical dependency
□ Critical path identified and protected

OPERATIONS
□ Deploy and rollback procedure, practised
□ Observability: logs, metrics, traces, SLOs
□ Alerts with runbooks
□ On-call owner named
□ Backup + tested restore
□ RTO/RPO agreed with the business

SECURITY
□ Data classified
□ Threat model (STRIDE) done
□ Least privilege; no long-lived credentials
□ Tenant isolation at the data layer + automated tests

PEOPLE
□ Team has the skills to operate this
□ ADR written, with a REVISIT TRIGGER
□ A diagram a new joiner understands in 10 minutes
□ Riskiest assumption spiked with real code
```

---

**Back to:** [Contents](README.md) · [Glossary](appendix-a-glossary.md) · [Roadmap](appendix-c-roadmap.md)
