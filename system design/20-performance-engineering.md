# Chapter 20 — Performance Engineering 🟡

> The first rule of performance work: **measure**.
> The second rule: **measure**.
> Engineers are consistently, spectacularly wrong about where the time goes — including experienced ones, including you.

---

## 20.1 The vocabulary, precisely

| Term | Definition | Unit |
|------|-----------|------|
| **Latency** | Time for one operation | ms |
| **Throughput** | Operations completed per unit time | req/s |
| **Concurrency** | Operations in flight at one instant | count |
| **Response time** | What the *user* experiences (queueing + service time) | ms |
| **Service time** | Time actually working on the request | ms |
| **Queue time** | Time waiting before work starts | ms |
| **Utilisation** | Fraction of a resource in use | % |
| **Saturation** | Work waiting because a resource is full | queue length |

### The relationship that explains everything

```
Response time = Queue time + Service time
```

Most "slow application" incidents are **queue time**, not service time — the code is fine, it is waiting. Waiting for a thread, a database connection, a lock, a disk, or a downstream service.

> **This is why the fix is so often "add a connection to the pool" or "increase the worker count", not "optimise the algorithm".** Diagnose which of the two you have before you touch any code.

### Latency and throughput are not the same thing

```
A single-lane road:        low latency per car, low throughput
A ten-lane motorway:       same latency per car, 10× throughput
A ten-lane motorway at 99% capacity: terrible latency, high throughput
```

You can improve throughput (add servers) without improving latency at all. You can improve latency (a faster algorithm) and improve throughput as a side effect. **State which one you are optimising** — teams routinely argue because they are optimising different things.

---

## 20.2 Measure before you optimise 🟢

### Amdahl's Law — why optimising the wrong thing is futile

```
Speedup = 1 / ((1 - P) + P/S)
          P = proportion of time in the part you optimise
          S = how much faster you make that part
```

**A worked example:**

```
A request takes 1000 ms:
  200 ms application code
  750 ms database query
   50 ms serialisation

You make the application code 10× faster (200 ms → 20 ms).
  New total = 820 ms. An 18% improvement, for substantial effort.

You add one index and the query drops to 50 ms.
  New total = 300 ms. A 70% improvement, in ten minutes.
```

> **You cannot optimise your way past the bottleneck.** Even making the application code *infinitely* fast only gets you to 800 ms. Find the bottleneck first; everything else is wasted effort.

### The USE method — for any resource

For every resource (CPU, memory, disk, network, connection pool, thread pool):

```
UTILISATION  — what % of the time is it busy?
SATURATION   — how much work is queued waiting for it?
ERRORS       — is it failing?
```

**Saturation is the more important signal.** CPU at 100% with an empty run queue is fine — the machine is doing useful work. CPU at 60% with a run queue of 40 means something is badly wrong (probably lock contention or I/O waits).

### Profiling — find the truth

| Tool type | What it tells you | Examples |
|-----------|------------------|----------|
| **Sampling profiler** | Where CPU time goes | py-spy, async-profiler, dotnet-trace, perf |
| **Allocation profiler** | What is creating garbage | memory_profiler, dotMemory, pprof |
| **Flame graph** | Visual call-stack cost | speedscope, FlameGraph |
| **APM / distributed tracing** | Where time goes **across services** | OpenTelemetry (Chapter 18) |
| **Database EXPLAIN** | Query plans | Chapter 09 |
| **Continuous profiling** ⭐ | Production profiles, always on | Pyroscope, Parca, Datadog |

```bash
# py-spy: profile a RUNNING production process with negligible overhead — no code change
py-spy top --pid 12345
py-spy record --pid 12345 --duration 60 --output flame.svg
```

> **Profile production, not your laptop.** Production has real data volumes, real cache states, real concurrency and real network latency. A benchmark on a laptop with 100 rows tells you almost nothing about behaviour on 50 million.

**Reading a flame graph:** width = total time spent (including children), not call count. Look for the **widest plateaus** — those are where the time is. The shape of the stack above them tells you why.

---

## 20.3 Where the time actually goes

In a typical web request, ranked by how often each is the real culprit:

| Rank | Cause | Typical fix |
|------|-------|-------------|
| 1 | **N+1 queries** | Join, batch, or eager-load (Chapter 09) |
| 2 | **Missing index** | Add the index (Chapter 09) |
| 3 | **Serial network calls** | Parallelise or aggregate (Chapter 08) |
| 4 | **No caching on a hot read** | Cache it (Chapter 11) |
| 5 | **Connection pool exhaustion** | Size it via Little's Law (Chapter 04) |
| 6 | **Over-fetching** | `SELECT` the columns you need; paginate |
| 7 | **Serialisation overhead** | Smaller payloads, faster codec, compression |
| 8 | **Lock contention** | Shorter transactions, optimistic concurrency |
| 9 | **GC pauses** | Reduce allocation; tune the collector |
| 10 | **Actual algorithmic complexity** | Rare in business software, but real when it appears |

> **Notice that nine of the top ten are I/O, waiting, or data access — not CPU-bound code.** Business applications are almost never CPU-bound. Engineers optimise algorithms because that is what feels like "performance work", while the database round trips go unexamined.

### The three bound types

```
CPU-BOUND      the processor is the limit
               → profile, optimise hot paths, parallelise, scale out
               (image processing, ML inference, compression, crypto)

I/O-BOUND      waiting on disk or network
               → concurrency, batching, caching, connection reuse
               → MORE THREADS HELP (they are waiting, not computing)
               (most web applications)

MEMORY-BOUND   allocation, GC, or cache misses dominate
               → reduce allocation, use value types, improve data locality
               (high-throughput data processing)
```

**Identify which you have before choosing a technique.** Adding threads to a CPU-bound workload makes it slower (context-switching overhead). Optimising an algorithm in an I/O-bound service changes nothing.

---

## 20.4 Optimisation techniques 🟢

### 1. Do less work

The most effective optimisation is always **not doing the thing**.

```python
# Do we need all 200 columns?              → SELECT only what is used
# Do we need all 10,000 rows?              → paginate
# Do we need it on every request?          → cache
# Do we need it synchronously?             → queue it
# Do we need it at all?                    → delete the feature
```

### 2. Batch

```python
# ❌ 1,000 round trips × 0.5 ms = 500 ms of pure network
for record in records:
    await db.execute("INSERT INTO events (...) VALUES ($1, $2)", record.a, record.b)

# ✅ one round trip
await db.execute_many("INSERT INTO events (...) VALUES ($1, $2)",
                      [(r.a, r.b) for r in records])

# ✅ even better for bulk loads — COPY is 10-50× faster than INSERT
await db.copy_records_to_table("events", records=records, columns=["a", "b"])
```

Batching applies everywhere: database writes, API calls, message publishing, cache reads (`MGET`), log shipping.

**The trade-off: batching increases latency for the individual item** while increasing overall throughput. For async work that is free. For a user-facing request, cap the batch window (`linger_ms` style, Chapter 07).

### 3. Parallelise

```python
# ❌ sequential: 200 + 150 + 300 = 650 ms
session  = await get_session(id)
customer = await get_customer(cid)
quota    = await get_quota(tid)

# ✅ parallel: max(200, 150, 300) = 300 ms
session, customer, quota = await asyncio.gather(
    get_session(id), get_customer(cid), get_quota(tid)
)
```

Only when the calls are **independent**. And bound the parallelism — 10,000 concurrent calls will exhaust your pools and hurt the downstream service (Chapter 05 bulkheads).

### 4. Cache

The biggest single lever (Chapter 11). 20 ms → 0.3 ms.

### 5. Move work out of the request path

```python
# ❌ The user waits for all of this
async def complete_verification(session_id):
    result = await process(session_id)     # 3 s — necessary
    await send_email(result)               # 800 ms — not necessary NOW
    await update_analytics(result)         # 200 ms — not necessary NOW
    await call_webhook(result)             # 1.5 s — not necessary NOW, and it can fail
    return result                          # total: 5.5 s

# ✅ The user waits only for what they need
async def complete_verification(session_id):
    result = await process(session_id)     # 3 s
    await outbox.publish(VerificationCompleted(result))   # 5 ms (Chapter 06)
    return result                          # total: 3 s
```

> **Ask of every step in a request: does the user need this to have finished before they get their answer?** Usually the answer is no for at least half of it.

### 6. Reduce payload size

| Technique | Typical saving |
|-----------|---------------|
| Gzip / Brotli compression | 70–90% on JSON |
| Return only needed fields | 50–80% |
| Pagination | Unbounded → bounded |
| Binary format (Protobuf/MessagePack) | 30–60% vs JSON, plus faster parsing |
| Image formats (WebP/AVIF) | 30–50% vs JPEG |

**JSON serialisation is frequently a top-3 CPU cost** in API servers, and nobody profiles it. On a large response, a faster JSON library (orjson, System.Text.Json with source generators) can be a 2–5× improvement on that portion for a one-line change.

### 7. Connection pooling

Covered in Chapters 09 and 13. Sizing via Little's Law (Chapter 04):

```
Pool size ≈ throughput × average hold time × safety factor

500 req/s × 20 ms DB time = 10 concurrent → pool of ~20 is plenty
```

> **Bigger pools are not better.** An oversized pool moves the contention into the database (which has its own limits and context-switching costs) and hides the real problem. Measure `pool.wait_time`; if it is near zero, your pool is big enough.

### 8. Async I/O

For I/O-bound work, async lets one thread handle thousands of concurrent waits instead of blocking one thread each.

**But:** one blocking call in an async event loop stalls *everything*. A `time.sleep()`, a synchronous database driver, or a CPU-heavy loop in an async handler will destroy throughput in a way that is genuinely hard to diagnose. Use `run_in_executor` for blocking work, and audit your libraries.

### 9. Indexes and query optimisation

Chapter 09. Usually the single highest-value performance work available in a business application.

---

## 20.5 Load testing 🟢

### The four types — they answer different questions

| Type | Question | Method |
|------|----------|--------|
| **Load test** | Does it meet the SLO at expected load? | Ramp to target, hold for 10–30 min |
| **Stress test** | Where does it break, and how? | Ramp until failure |
| **Soak test** ⭐ | Does it survive sustained load for hours? | Target load for 4–24 hours |
| **Spike test** | Does it survive a sudden surge? | Jump instantly to 10× |

**The soak test is the one most teams skip, and it catches the problems that are hardest to find any other way:** memory leaks, connection leaks, file-handle exhaustion, disk filling with logs, cache growing unbounded, TIME_WAIT accumulation. These do not appear in a 5-minute test — they appear at 3 AM on day four in production.

**The stress test's real value is learning the failure mode.** Does it degrade gracefully, shed load, and recover? Or does it collapse and require a manual restart? You want to know that before a real traffic spike.

### Writing a useful load test

```javascript
// k6 — realistic, with thresholds that FAIL the test
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m',  target: 50 },   // warm up — never start at full load
    { duration: '5m',  target: 200 },  // ramp
    { duration: '20m', target: 200 },  // ⭐ sustained — this is where truth lives
    { duration: '2m',  target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<400', 'p(99)<1000'],   // matches the SLO
    http_req_failed:   ['rate<0.01'],
    checks:            ['rate>0.99'],
  },
};

export default function () {
  // Realistic mix: 90% reads, 10% writes — not 100% of one endpoint
  if (Math.random() < 0.9) {
    const res = http.get(`${__ENV.BASE}/v1/sessions?limit=20`,
                         { headers: { Authorization: `Bearer ${__ENV.TOKEN}` } });
    check(res, { 'list ok': (r) => r.status === 200 });
  } else {
    const res = http.post(`${__ENV.BASE}/v1/sessions`, JSON.stringify({ ... }),
                          { headers: { 'Content-Type': 'application/json',
                                       'Idempotency-Key': uuidv4() } });
    check(res, { 'create ok': (r) => r.status === 201 });
  }
  sleep(Math.random() * 3);            // think time — users are not bots
}
```

### The rules that make load tests meaningful

1. **Test in a production-like environment.** Half the instances and a tiny dataset produce numbers that mean nothing.
2. **Use realistic data volumes.** A query on 1,000 rows and the same query on 50 million are different queries.
3. **Realistic access patterns** — real systems have hot keys and a long tail. Uniform random access gives an unrealistically good cache hit ratio.
4. **Include think time.** Users pause; bots do not.
5. **Warm up first** — JIT compilation, connection pools and caches all need to reach steady state.
6. **Monitor the system under test, not just the client.** The client tells you it is slow; the server tells you why (CPU, connections, GC, queue depth).
7. **Test the failure modes too** — what happens at 150% of target?
8. **Watch the load generator itself.** A saturated client reports latency that is its own, not the server's. This fools people regularly.

### Coordinated omission — the bug in most load test results ⭐

```
Your tool sends a request every 100 ms. The server stalls for 10 seconds.
A naive tool WAITS for the response, then continues — so it never sends
the 100 requests that should have been issued during the stall.

Result: it records ONE slow request instead of 100 increasingly-delayed ones.
Your reported p99 looks fine. Real users experienced a 10-second outage.
```

**Use tools that correct for this** (k6, wrk2, Gatling, JMeter with throughput shaping) by measuring against the *intended* schedule rather than the actual one. Tools that simply loop "send, wait, send" systematically understate tail latency — often by an order of magnitude.

---

## 20.6 Frontend and perceived performance 🟡

Backend engineers under-invest here, but users experience the frontend.

### Core Web Vitals

| Metric | Measures | Good |
|--------|----------|------|
| **LCP** (Largest Contentful Paint) | When the main content appears | < 2.5 s |
| **INP** (Interaction to Next Paint) | Responsiveness to input | < 200 ms |
| **CLS** (Cumulative Layout Shift) | Visual stability | < 0.1 |

### Perceived performance often beats actual performance

| Technique | Effect |
|-----------|--------|
| **Skeleton screens** | Feels faster than a spinner — the eye sees structure appearing |
| **Optimistic UI** | Show the result immediately, reconcile with the server after |
| **Progressive rendering / streaming** | Something appears in 200 ms rather than everything in 2 s |
| **Prefetch on hover** | The page is loading before the click completes |
| **Immediate feedback** | Response within 100 ms feels instantaneous, even if it is just a spinner starting |

**The human thresholds worth knowing:**
```
< 100 ms   feels instantaneous
< 1 s      thought flow uninterrupted — no feedback strictly required
< 10 s     attention held, but feedback (progress) is essential
> 10 s     the user leaves or switches tasks
```

> **A 3-second operation with a progress bar is perceived far better than a 2-second operation with a frozen screen.** Perceived performance is a design decision, not only an engineering one.

---

## 20.7 Performance budgets and regression detection

**A performance budget is an SLO for speed, enforced in CI** — a fitness function (Chapter 00).

```yaml
budgets:
  api:
    - endpoint: POST /v1/verify
      p95_ms: 4000
      p99_ms: 8000
    - endpoint: GET /v1/sessions
      p95_ms: 300
  frontend:
    - metric: lcp_ms
      budget: 2500
    - metric: bundle_size_kb
      budget: 250
  database:
    - metric: queries_per_request
      budget: 10          # ⭐ catches N+1 regressions automatically
```

**The query-count budget is the highest-value one.** An N+1 introduced by an innocent-looking ORM change passes every functional test. Asserting "this endpoint must make ≤ 10 queries" catches it at the pull request.

```python
# A test that prevents the most common performance regression in existence
async def test_session_list_query_count(client, query_counter):
    await client.get("/v1/sessions?limit=50")
    assert query_counter.count <= 3, (
        f"N+1 detected: {query_counter.count} queries. "
        f"Queries: {query_counter.queries}"
    )
```

**Detect regressions in production too:** compare this week's p95 per endpoint against last week's, and alert on a significant increase. Performance decays gradually, one unnoticed change at a time, until someone complains — and by then the cause is buried under three months of commits.

---

## 20.8 When NOT to optimise 🟢

> *"Premature optimisation is the root of all evil."* — Knuth
>
> But the full quote matters: *"We should forget about small efficiencies, say about 97% of the time... **Yet we should not pass up our opportunities in that critical 3%.**"*

**Do not optimise when:**
- You have not measured — you will optimise the wrong thing
- It is not on the critical path
- It meets the requirement already (an 80 ms endpoint with a 200 ms SLO is *done*)
- The complexity cost exceeds the benefit
- The bottleneck is elsewhere (Amdahl)
- It makes the code substantially harder to understand for a gain nobody will notice

**Do optimise when:**
- You have measured and identified the bottleneck
- It is on the critical path, at p95/p99
- There is a real SLO being missed, or a real cost being incurred
- It is architectural and will be expensive to change later (data model, protocol, sharding key)

### The "critical 3%" that *is* worth designing for upfront

Some performance decisions are architectural and cannot be retrofitted cheaply (Chapter 00's rule about expensive-to-change decisions):

- **Data model and access patterns** — an unsuitable shape means a rewrite
- **Sharding/partition key** — nearly impossible to change later (Chapter 04)
- **Synchronous vs asynchronous** boundaries
- **Chatty vs coarse-grained API design** — hard to change once clients depend on it
- **Where state lives** — externalising it later is a large project

Everything else: build it simply, measure, then optimise what is actually slow.

---

## 20.9 A performance investigation, end to end

```
REPORT: "The sessions list page is slow."

1. QUANTIFY          "Slow" is not a measurement.
   Dashboard: GET /v1/sessions  p50 = 180 ms, p95 = 3.2 s, p99 = 8.1 s
   → the median is fine; the TAIL is terrible → something is conditional

2. SEGMENT           Break down by every dimension you have.
   by tenant   → tenants with > 10,000 sessions are slow. Small tenants are fine.
   → it is data-volume dependent, not a global problem

3. TRACE             Find a slow trace (tail-based sampling made sure you have one).
   Span breakdown:  auth 12 ms · db.query 2,980 ms · serialise 190 ms
   → it is the query

4. EXPLAIN           Run EXPLAIN (ANALYZE, BUFFERS) on the real query.
   Seq Scan on sessions  (rows=1,240,000)  Rows Removed by Filter: 1,238,000
   → no usable index for (tenant_id, status, created_at)

5. FIX               CREATE INDEX CONCURRENTLY idx_sessions_tenant_status_created
                       ON sessions (tenant_id, status, created_at DESC);
   → p95: 3.2 s → 95 ms

6. VERIFY            Confirm in production metrics, not just locally.
   Also check: did any other query plan regress? Did write latency increase?

7. PREVENT           Add a query-count and latency budget test for this endpoint.
                     Add an alert on p95 per endpoint.
                     Review other endpoints for the same missing-index pattern.
```

> **Step 2 is the one that separates a good engineer from a great one.** "It is slow" is unactionable. "It is slow only for tenants with more than 10,000 rows" points directly at a missing index, before you have opened a profiler.

---

## 20.10 Common mistakes

1. **Optimising without measuring** — you will be wrong about where the time goes
2. **Optimising the wrong 5%** — Amdahl's Law makes it futile
3. **Benchmarking on a laptop with tiny data** — proves nothing about production
4. **Averages instead of percentiles** — the tail is the user experience (Chapter 18)
5. **Coordinated omission in load tests** — reported p99 is an order of magnitude too good
6. **No soak test** — leaks and exhaustion appear on day four, in production
7. **Load testing without monitoring the system under test** — you learn it is slow, not why
8. **A saturated load generator** — you are measuring your client
9. **Unbounded parallelism** — you DDoS your own dependencies
10. **Oversized connection pools** — moves contention into the database and hides the problem
11. **A blocking call in an async event loop** — throughput collapses, cause is obscure
12. **Ignoring serialisation cost** — often a top-3 CPU consumer, rarely profiled
13. **No performance regression tests** — speed decays one commit at a time
14. **Ignoring perceived performance** — a fast backend behind a frozen UI still feels slow
15. **Optimising something that already meets its requirement**

---

## 20.11 Architect's checklist

- [ ] Performance requirements stated as percentiles with SLOs, per endpoint
- [ ] The critical path identified; optimisation effort concentrated there
- [ ] Profiling available in production (continuous profiling ideally)
- [ ] Distributed tracing shows where time goes across services (Chapter 18)
- [ ] Slow-query logging and `pg_stat_statements` enabled and reviewed
- [ ] N+1 detection: query-count budget tests on key endpoints
- [ ] Connection pools sized by Little's Law; pool wait time monitored
- [ ] Caching strategy in place for hot reads (Chapter 11)
- [ ] Non-essential work moved out of the request path (queue + outbox)
- [ ] Independent calls parallelised, with bounded concurrency
- [ ] Payloads compressed; responses return only needed fields; everything paginated
- [ ] Load test in a production-like environment with realistic data and access patterns
- [ ] Soak test run before any major launch
- [ ] Stress test run to learn the failure mode and confirm graceful degradation
- [ ] Load tool corrects for coordinated omission
- [ ] Performance budgets enforced in CI
- [ ] Week-over-week p95 regression alerting in production
- [ ] Frontend: Core Web Vitals measured; perceived-performance techniques used

---

## 20.12 Self-test

1. Response time = queue time + service time. Why does that distinction change the fix?
2. State Amdahl's Law and work through the 1000 ms example.
3. What is the USE method? Why is saturation a better signal than utilisation?
4. List the top five causes of slow web requests in order. What do they have in common?
5. CPU-bound, I/O-bound, memory-bound — how does the correct technique differ for each?
6. Why does adding threads help I/O-bound work but hurt CPU-bound work?
7. What is coordinated omission and why does it invalidate most load test results?
8. Which load test type catches memory leaks, and why do the others miss them?
9. Name six rules for a meaningful load test.
10. Why are bigger connection pools not better? What metric tells you the size is right?
11. Why is a query-count budget test the highest-value performance regression test?
12. When should you NOT optimise? Give five conditions.
13. Which performance decisions must be made upfront because they are expensive to change?
14. Why is a 3-second operation with a progress bar better than a 2-second frozen screen?
15. Walk through a full investigation of "the list page is slow", from report to prevention.

---

## 20.13 Key takeaways

- **Measure first. You will be wrong about the bottleneck** — everyone is.
- **Amdahl's Law:** optimising a non-bottleneck is arithmetic futility
- **Most slowness is queue time, not service time** — waiting, not computing
- **Nine of the top ten causes are I/O and data access**, not algorithms
- **The best optimisation is doing less work**: fewer queries, fewer round trips, smaller payloads, less in the request path
- **Batch, parallelise, cache, and move work out of the request path** — in that order of usual payoff
- **Profile production**, with real data volumes and real concurrency
- **Soak tests find what short tests cannot** — leaks, exhaustion, slow degradation
- **Coordinated omission makes most load test results wrong** by an order of magnitude
- **Query-count budgets in CI** prevent the most common regression in existence
- **Do not optimise what already meets its requirement** — but do design the expensive-to-change things correctly upfront
- **Perceived performance is real performance** to the person using it

---

**Next:** [Chapter 21 — Testing Architecture](21-testing-architecture.md)
