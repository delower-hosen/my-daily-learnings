# Chapter 18 — Observability 🟢

> **Monitoring** tells you *that* something is wrong.
> **Observability** lets you work out *why* — including for failures you never anticipated.
>
> In a distributed system, observability is not optional tooling. It is the only thing standing between you and guessing.

---

## 18.1 Monitoring vs Observability

| | **Monitoring** | **Observability** |
|---|---|---|
| Answers | Known questions | **Unknown** questions |
| Built from | Predefined dashboards and alerts | Rich, high-cardinality telemetry you can slice arbitrarily |
| "Is CPU high?" | ✅ | ✅ |
| "Why are checkout requests slow for enterprise tenants on Android in Singapore since 14:20?" | ❌ | ✅ |

**The formal definition:** a system is observable if you can determine its internal state from its external outputs, **without shipping new code**.

> **The practical test:** when a customer reports a problem, can you answer *"what happened to request `abc123`?"* in under five minutes without adding a log line and deploying? If not, you have monitoring, not observability.

### Why this matters more in distributed systems

In a monolith, one stack trace tells the whole story. With 8 services, one user action produces 8 separate log streams, 8 sets of metrics, and no single place that knows the full path. **The telemetry has to be designed** — it does not emerge.

---

## 18.2 The three pillars 🟢

```
┌─────────────────────────────────────────────────────────────┐
│  LOGS        discrete events        "what happened"          │
│  METRICS     numeric aggregates     "how much / how often"   │
│  TRACES      request journeys       "where did the time go"  │
└─────────────────────────────────────────────────────────────┘
```

They are complements, and each answers a different kind of question:

| Question | Pillar |
|----------|--------|
| "Are we healthy right now?" | **Metrics** (a dashboard) |
| "Which service is slow in this request?" | **Traces** |
| "What exactly went wrong in that one failure?" | **Logs** |
| "Has this got worse since the deploy?" | **Metrics** |
| "How many tenants are affected?" | **Metrics** (with tenant as a dimension) or traces |

**The workflow they support, in order:**
```
Metric alert fires  →  Dashboard narrows it to a service and a time window
                    →  Traces show which span is slow or failing
                    →  Logs for that trace ID give the exact error
```

If any pillar is missing, that chain breaks and you are back to guessing.

---

## 18.3 Logs 🟢

### Structured logging — non-negotiable

```python
# ❌ Unstructured: unsearchable, unparseable, unaggregatable
logger.info(f"User {user_id} verification failed with score {score} after {ms}ms")

# ✅ Structured: every field is queryable
logger.info(
    "verification_failed",
    user_id=user_id,
    tenant_id=tenant_id,
    session_id=session_id,
    score=score,
    duration_ms=ms,
    reason="below_threshold",
    threshold=0.85,
    attempt=2,
    trace_id=current_trace_id(),
)
```

```json
{"timestamp":"2026-09-12T10:14:22.481Z","level":"info","message":"verification_failed",
 "service":"verification-api","version":"1.8.2","env":"production",
 "trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7",
 "tenant_id":"t_42","session_id":"ses_881","score":0.61,"threshold":0.85,
 "duration_ms":3412,"reason":"below_threshold","attempt":2}
```

Now you can ask: *"show me the p95 duration of failed verifications for tenant t_42 in the last hour, grouped by reason."* With the unstructured version, that is a regex nightmare and it will still be wrong.

### Log levels — use them consistently

| Level | Meaning | Example | Action |
|-------|---------|---------|--------|
| **ERROR** | Something failed that needs attention | Payment gateway unreachable after retries | Investigate; often alert |
| **WARN** | Unexpected but handled | Fell back to the secondary vendor | Watch the rate |
| **INFO** | Significant business events | Session created, verification completed | Normal operation |
| **DEBUG** | Detailed diagnostic | Request/response payloads, decision branches | Off in production (or sampled) |

> **The most common mistake: logging handled conditions as ERROR.** A user typing a wrong password is not an error — it is expected behaviour. If your ERROR log has thousands of entries an hour, nobody reads it, and the one real error hides in the noise. **ERROR means "a human should probably look at this."**

### What to log — and what never to log

```
✅ LOG
   - Request start/end with method, path, status, duration, tenant
   - Business events (order placed, verification completed, refund issued)
   - All external calls: target, duration, outcome, retry count
   - State transitions
   - Authorization denials (Chapter 17)
   - Errors with full context and a stack trace
   - Configuration at startup (with secrets redacted)

❌ NEVER LOG
   - Passwords, tokens, API keys, session IDs, private keys
   - Full credit card numbers, CVVs
   - Full PII beyond what is necessary (log an ID, not an email or a name)
   - Biometric data or document images
   - Complete request bodies containing any of the above
   - Health-check requests (they will drown everything else)
```

> **Build redaction into the logger itself**, as a processor — do not rely on every developer remembering. A field named `password`, `token`, `secret`, `authorization` or `card_number` should be automatically replaced with `[REDACTED]` before it can reach a log sink.

### Correlation — the field that makes logs usable

Every log line must carry the **trace ID**. Without it, correlating 8 services' logs for one request is manual archaeology.

```python
# Middleware: extract or create a trace context and bind it for the whole request
@app.middleware("http")
async def correlation(request: Request, call_next):
    trace_id = request.headers.get("traceparent", "").split("-")[1:2] or [uuid4().hex]
    with structlog.contextvars.bound_contextvars(
        trace_id=trace_id[0],
        tenant_id=request.state.tenant_id,
        request_path=request.url.path,
    ):
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id[0]   # ⭐ give it to the CLIENT too
        return response
```

> **Return the trace ID to the client** in a response header and in error payloads (Chapter 08). A customer says "it failed, here's the ID" and you find the exact request in seconds. This single detail transforms support.

### Cost control

Logs are usually the most expensive part of an observability bill. At 5,000 RPS with 2 KB per log line, that is 10 MB/s — roughly 850 GB/day.

| Technique | Effect |
|-----------|--------|
| **Sample DEBUG/INFO** | Keep 1–10% of successful requests, 100% of errors |
| **Tiered retention** | 7 days hot (searchable), 90 days warm, 1 year cold in object storage |
| **Drop noise at the agent** | Health checks, static asset requests |
| **Move detail to traces and metrics** | A metric for "how many" is thousands of times cheaper than a log line each |
| **Cap per-service volume** | Prevents one chatty service from consuming the budget |

> **Tail-based sampling is the sophisticated version:** keep 100% of traces that contain an error or exceed a latency threshold, and 1% of the rest. You retain everything interesting and almost nothing boring.

---

## 18.4 Metrics 🟢

### The four types

| Type | Behaviour | Example |
|------|-----------|---------|
| **Counter** | Only increases | `http_requests_total`, `verifications_failed_total` |
| **Gauge** | Goes up and down | `queue_depth`, `active_connections`, `memory_bytes` |
| **Histogram** | Buckets of observations → percentiles | `request_duration_seconds` |
| **Summary** | Client-computed quantiles | Rarely preferred — cannot be aggregated across instances |

```python
from prometheus_client import Counter, Histogram, Gauge

verifications = Counter(
    "verifications_total", "Verifications processed",
    ["tenant_tier", "outcome", "method"],          # labels = dimensions you can slice by
)
duration = Histogram(
    "verification_duration_seconds", "End-to-end verification duration",
    ["method"],
    buckets=(0.5, 1, 2, 4, 8, 16, 30, 60),         # ⭐ chosen for YOUR SLO, not defaults
)
queue_depth = Gauge("verification_queue_depth", "Jobs waiting")

verifications.labels(tenant_tier="enterprise", outcome="passed", method="active").inc()
duration.labels(method="active").observe(3.412)
```

### Cardinality — the thing that will blow up your bill 🟢

**Cardinality** = the number of unique label-value combinations. Each one is a separate time series stored forever.

```
metric{tenant_tier="enterprise", outcome="passed", method="active"}
  3 tiers × 4 outcomes × 2 methods = 24 series          ✅ fine

metric{user_id="...", session_id="...", trace_id="..."}
  1M users × 10M sessions × ∞ traces = CARDINALITY EXPLOSION   ☠️
```

> **Rule: never put an unbounded value in a metric label.** No user IDs, session IDs, trace IDs, URLs with parameters, email addresses, or raw error messages.
>
> High-cardinality identifiers belong in **logs and traces**, which are indexed for exactly that. Metrics are for aggregates.

```python
# ❌ blows up: one series per URL
http_requests.labels(path=f"/sessions/{session_id}").inc()
# ✅ use the route TEMPLATE
http_requests.labels(route="/sessions/{id}").inc()
```

### The golden signals ⭐

Google's SRE book reduces service health to four:

| Signal | What it measures | Alert when |
|--------|-----------------|-----------|
| **Latency** | How long requests take — **separate successful from failed** | p95/p99 exceeds the SLO |
| **Traffic** | Demand: requests/sec, messages/sec | Anomalous spike or drop (a drop to zero is a serious signal) |
| **Errors** | Rate of failed requests | Error rate exceeds the budget |
| **Saturation** | How full the system is (CPU, memory, queue, connections, disk) | Approaching a limit |

**The critical detail on latency:** always split it by outcome. A failing request that returns instantly drags your p50 *down* and hides the fact that successful requests got slower. Measure the latency of success separately.

**RED** (Rate, Errors, Duration) for request-driven services and **USE** (Utilisation, Saturation, Errors) for resources are the same idea in different clothing. Use RED for your services and USE for your infrastructure.

### Percentiles, not averages 🟢

```
Requests: 100ms ×99, and 1 request at 10,000ms
  Average = 199 ms       "looks fine"
  p50     = 100 ms
  p99     = 10,000 ms    ← that is a real user having a terrible time
```

> **Averages lie.** Always look at p50, p95, p99 — and for anything user-facing, p99.9.

**The "one in a thousand" reality check:** if a page makes 100 backend calls, a p99 of 2 seconds means roughly **63% of page loads** contain at least one 2-second call. Tail latency dominates user experience far more than people expect.

**Never average percentiles across instances or time windows.** `avg(p99)` is mathematically meaningless. Use a histogram and compute the quantile over the aggregated buckets (`histogram_quantile` in Prometheus).

---

## 18.5 Distributed tracing ⭐ 🟢

**The one that makes distributed systems debuggable.**

```
Trace: 4bf92f3577b34da6a3ce929d0e0e4736     (one user request, end to end)

api-gateway            ├──────────────────────────────────────────┤  842ms
 └ verification-api    │ ├────────────────────────────────────┤     798ms
    ├ auth-check       │ │ ├──┤                                      18ms
    ├ db: get_session  │ │    ├──┤                                   12ms
    ├ s3: fetch_video  │ │       ├────────┤                         142ms
    ├ vendor: analyse  │ │                ├──────────────────┤      580ms ← THE PROBLEM
    │  └ (retry 1)     │ │                ├────────┤                240ms ← timed out
    │  └ (retry 2)     │ │                         ├─────────┤      338ms
    └ db: save_result  │ │                                   ├──┤    24ms
```

In one picture: the vendor call is 69% of the total, and it is being retried. No amount of log-grepping across four services gives you that in ten seconds.

### Concepts

| Term | Meaning |
|------|---------|
| **Trace** | The whole journey of one request |
| **Span** | One unit of work (an HTTP call, a query, a function) |
| **Parent span** | The span that caused this one |
| **Trace context** | The IDs propagated between services (W3C `traceparent`) |
| **Baggage** | Key-value data carried along the whole trace (tenant ID, feature flags) |
| **Attributes** | Key-values on a single span |

### W3C Trace Context — propagate it everywhere

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^  ^                                ^                ^
          version  trace-id (32 hex)         span-id (16 hex)   flags (01=sampled)
```

**This header must be propagated through every hop — including through message brokers** (Chapter 06). A trace that stops at the queue boundary hides exactly the part you most need to see: how long a message waited before being picked up.

### OpenTelemetry 🟢

**The vendor-neutral standard for all three pillars.** It matters architecturally because it decouples your instrumentation from your observability vendor — you instrument once, and change backends by changing configuration.

```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Auto-instrumentation gives you most of the value for almost no effort
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
HTTPXClientInstrumentor().instrument()

tracer = trace.get_tracer(__name__)

# Manual spans for business-meaningful operations
async def verify(session_id: str, video: bytes) -> Result:
    with tracer.start_as_current_span("liveness.verify") as span:
        span.set_attribute("session.id", session_id)
        span.set_attribute("video.size_bytes", len(video))
        span.set_attribute("tenant.id", current_tenant())
        try:
            result = await pipeline.run(video)
            span.set_attribute("liveness.score", result.score)
            span.set_attribute("liveness.outcome", result.outcome)
            return result
        except VendorUnavailable as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
```

> **Start with auto-instrumentation.** It gives you HTTP, database, cache and message-broker spans across the whole request path in an afternoon. Add manual spans only for business operations that the automatic ones cannot see.

**The OpenTelemetry Collector** sits between your services and your backends: it receives telemetry, processes it (sampling, redaction, enrichment, adding `k8s.*` metadata) and exports it anywhere. Running one means your applications are never coupled to a vendor's SDK, and you can change or dual-ship backends without redeploying anything.

### Sampling

100% tracing at high volume is expensive.

| Strategy | How | Trade-off |
|----------|-----|-----------|
| **Head-based** | Decide at the start, e.g. 1% | Simple, but you will miss most errors |
| **Tail-based** ⭐ | Buffer the whole trace, then decide | **Keeps 100% of errors and slow traces**, 1% of normal. Needs a collector with memory. |
| **Adaptive** | Rate varies by endpoint volume | Ensures low-traffic endpoints are still represented |

> **Tail-based sampling is what you want.** The whole point of a trace is to explain something unusual; head-based sampling throws away exactly those traces.

### Exemplars — linking metrics to traces

An exemplar attaches a trace ID to a metric data point. On a latency histogram, you click the slow bucket and jump straight into an actual slow trace. It is a small configuration step that dramatically shortens the metric → trace hop.

---

## 18.6 SLI, SLO, SLA and error budgets 🟢

### The definitions

```
SLI  Service Level Indicator  — a MEASUREMENT
     "Proportion of verification requests completed successfully in under 4 seconds"

SLO  Service Level Objective  — your INTERNAL TARGET
     "99.5% of verification requests succeed within 4 seconds, over a rolling 30 days"

SLA  Service Level Agreement  — an EXTERNAL CONTRACT with penalties
     "99.0% monthly uptime, or a 10% service credit"
```

> **Your SLO must be stricter than your SLA.** The gap is your safety margin. If they are equal, the first breach of your target is also a breach of contract.

### Writing a good SLI

**Bad:** "The service should be fast and reliable."

**Good:** a ratio of good events to valid events:

```
SLI = (verification requests returning 2xx within 4000ms)
    ─────────────────────────────────────────────────────
      (all verification requests, excluding 4xx client errors)
```

**Rules:**
- Measure **from the user's perspective** where possible (client-side or at the edge, not deep inside)
- **Exclude client errors** (4xx) — a user sending a malformed request is not your unavailability
- Pick 2–4 SLIs per user journey, not fifty
- **Availability and latency together** — a service that returns 200s in 30 seconds is not available in any meaningful sense

### Error budgets ⭐ — the most useful idea here

```
SLO = 99.5% over 30 days
Error budget = 0.5% = 3 hours 39 minutes of failure per month

Budget consumed:  ██████████░░░░░░░░░░  48%  (1h 45m used, 1h 54m remaining)
```

**What it enables — this is the point:**

| Budget state | What it means for the team |
|--------------|---------------------------|
| **Plenty remaining** | Ship faster. Take risks. Run chaos experiments. Deploy on Friday. |
| **Nearly exhausted** | Freeze risky changes. Prioritise reliability work. |
| **Exhausted** | **Feature work stops until the budget recovers.** |

> **The error budget converts an endless argument ("move fast!" vs "be careful!") into a number that both sides agreed to in advance.** That is its real value — it is an organisational tool disguised as a metric.

It also makes a crucial point explicit: **100% reliability is the wrong target.** It is impossible, and pursuing it means you ship nothing. The budget says, formally, that some failure is acceptable — and defines exactly how much.

### Burn-rate alerting ⭐ (alert on this, not on raw thresholds)

```
Burn rate = how fast you are consuming the error budget relative to the SLO period

Burn rate 1×  → you will exactly exhaust the budget at the end of the window
Burn rate 14× → you will exhaust a 30-day budget in ~2 days     ← page someone
Burn rate 6×  → exhausted in ~5 days                             ← page someone
Burn rate 1×  → slow burn                                        ← a ticket, not a page
```

```yaml
# Multi-window, multi-burn-rate: fast for severe, slow for creeping problems
- alert: ErrorBudgetBurnFast
  expr: |
    (slo:error_rate:5m  > 14 * 0.005) and
    (slo:error_rate:1h  > 14 * 0.005)
  for: 2m
  labels: { severity: page }
  annotations:
    summary: "Burning error budget 14× — full budget gone in ~2 days"
    runbook: "https://runbooks/verification-api/high-error-rate"

- alert: ErrorBudgetBurnSlow
  expr: |
    (slo:error_rate:6h  > 6 * 0.005) and
    (slo:error_rate:24h > 6 * 0.005)
  for: 15m
  labels: { severity: ticket }
```

**Why two windows?** The short window makes it react fast; the long window prevents a brief blip from paging anyone. Together they page for real problems and stay quiet for noise.

---

## 18.7 Alerting 🟢

### The rules of alerting

> **Every page must be urgent, important, actionable and real.**
> If any of those four is false, it should not be a page.

| Rule | Why |
|------|-----|
| **Alert on symptoms, not causes** | "Users cannot check out" not "CPU is 85%". High CPU with happy users is not an incident. |
| **Every alert needs a runbook** | A page at 3 AM with no instructions wastes the first 20 minutes |
| **Every alert needs a human action** | If the response is "nothing, it recovers" — delete it or automate it |
| **Page only for user-impacting problems** | Everything else is a ticket |
| **Make alerts hard to ignore** | If people routinely ignore an alert, it is broken. Fix or delete it. |

### Alert fatigue is the real danger

```
50 alerts/day → all ignored → the ONE real alert is missed → an outage nobody noticed
```

**This is not hypothetical.** Several well-documented major outages involved alerts that fired correctly and were ignored because that alert fired every day.

**The discipline:** review every page monthly. For each, ask: *was it real? was it actionable? did we do something?* If the answer is no three times, **delete the alert**. A smaller set of trustworthy alerts is vastly better than comprehensive noise.

### Severity levels

| Level | Criterion | Response |
|-------|-----------|----------|
| **P1 / Page** | Users are affected now; revenue or safety at risk | Wake someone, immediately |
| **P2 / Urgent ticket** | Degraded, or will become P1 soon | Business hours, same day |
| **P3 / Ticket** | Worth fixing; no user impact | Next sprint |
| **Info** | Just a signal | Dashboard only — **never a notification** |

---

## 18.8 Dashboards

**Three tiers, three audiences:**

```
1. SERVICE HEALTH (the on-call dashboard)
   The four golden signals for THIS service. Deploy markers. Dependencies' health.
   → Must answer "is this service OK?" in 10 seconds.

2. BUSINESS / SLO
   SLO attainment, error budget remaining and burn rate, verifications/hour,
   revenue-relevant funnels.
   → For everyone, including product and leadership.

3. DEEP DIVE (per subsystem)
   Database: connections, slow queries, replication lag, cache hit ratio.
   Queue: depth, age, consumer lag, DLQ depth.
   → For investigation, not for watching.
```

**Design rules:**
- **Most important metric top-left** (that is where eyes land)
- **Include the SLO threshold as a line** on every latency and error chart — context beats a number
- **Overlay deploy markers.** "It broke at 14:22" plus "we deployed at 14:20" is most of your root-cause analysis.
- **Time ranges that match the question** — 1 h for incidents, 30 d for trends
- **A dashboard nobody looks at should be deleted.** Dashboard sprawl is real.

---

## 18.9 Debugging an incident with observability

A realistic walkthrough — this is the skill all of the above exists to enable.

```
14:22  ALERT: ErrorBudgetBurnFast — verification-api error rate 14× budget

1. DASHBOARD (30 seconds)
   Error rate jumped from 0.2% → 8% at 14:20.
   Latency p99 rose 800ms → 12s. Traffic unchanged.
   Deploy marker at 14:19.   ← strong signal, but verify before assuming

2. NARROW IT (1 minute)
   Break errors down by dimension:
     by endpoint  → all on POST /verify
     by tenant    → all tenants, not one
     by status    → 504 Gateway Timeout
   → Not a tenant-specific or data-specific problem.

3. TRACES (1 minute)
   Filter: service=verification-api, status=error, last 15m.
   Every failing trace: the `vendor.analyse` span times out at 8s.
   Compare with 14:00 traces: that span was 600ms.
   → The vendor is the proximate cause, not our deploy.

4. LOGS (1 minute)
   Filter by one failing trace_id.
   "vendor_call_failed reason=connection_timeout host=api.vendor.com attempt=3"
   Vendor status page: degraded performance. Confirmed.

5. MITIGATE (immediately, before root-causing further)
   - Circuit breaker should have opened — check why it did not
     → threshold was 50% over 20 calls; this endpoint gets 3 calls/min. Too slow to trip.
   - Enable the fallback flag: route to manual review instead of failing
   - Error rate drops to 0.3%; verifications queue for review rather than failing

6. AFTERWARDS
   - Fix the circuit breaker configuration for low-traffic endpoints
   - Add an alert on vendor call latency specifically (a leading indicator)
   - Add a synthetic check against the vendor
   - Blameless postmortem: the detection was good (2 min), the mitigation was slow
     (18 min) because the fallback flag was undocumented
```

> **Notice what made this possible:** structured logs with trace IDs, metrics with useful dimensions, traces with named spans, deploy markers, and a feature flag to mitigate. Remove any one and this becomes an hour of guessing.

---

## 18.10 Common mistakes

1. **Unstructured logs** — unqueryable, so nobody uses them
2. **No trace ID in logs** — correlation across services becomes archaeology
3. **High-cardinality metric labels** — cardinality explosion, huge bill, slow queries
4. **Averages instead of percentiles** — the tail is invisible, and the tail is the user experience
5. **Latency not split by success/failure** — fast failures hide slow successes
6. **Alerting on causes, not symptoms** — pages for high CPU while users are fine
7. **Alert fatigue** — 50 alerts/day means the real one is missed
8. **Alerts with no runbook** — 20 minutes lost at 3 AM
9. **Logging secrets or PII** — a compliance incident created by your logging
10. **Head-based sampling** — you sample away exactly the traces you needed
11. **Trace context not propagated through queues** — the flow disappears at the broker
12. **No deploy markers on dashboards** — the most useful correlation in existence, missing
13. **Observability added after the incident** — instrument before you need it
14. **Vendor-specific instrumentation** — changing backends becomes a rewrite (use OpenTelemetry)
15. **Logging everything at DEBUG in production** — enormous cost, no extra insight

---

## 18.11 Architect's checklist

- [ ] Structured (JSON) logging with consistent field names across every service
- [ ] Trace ID on every log line; trace context propagated over HTTP **and** message brokers
- [ ] Trace ID returned to clients in a response header and in error bodies
- [ ] Automatic redaction of secrets and PII in the logging pipeline
- [ ] Log levels used correctly; ERROR means "a human should look"
- [ ] Four golden signals instrumented per service; latency split by outcome
- [ ] Metric labels bounded — no IDs, URLs or messages as label values
- [ ] Histograms with buckets chosen around the SLO threshold
- [ ] Distributed tracing via OpenTelemetry; auto-instrumentation plus business spans
- [ ] Tail-based sampling: 100% of errors and slow traces
- [ ] An OpenTelemetry Collector decouples applications from the observability vendor
- [ ] SLIs defined per user journey, from the user's perspective, excluding 4xx
- [ ] SLOs set, stricter than any SLA; error budget calculated and visible
- [ ] Multi-window burn-rate alerting instead of raw thresholds
- [ ] Every alert: symptom-based, actionable, with a runbook link
- [ ] Alerts reviewed monthly; noisy ones deleted
- [ ] Deploy markers overlaid on dashboards
- [ ] Three dashboard tiers: service health, business/SLO, deep dive
- [ ] Log retention tiered; costs monitored and capped per service
- [ ] Synthetic checks for critical user journeys from outside your infrastructure

---

## 18.12 Self-test

1. Monitoring vs observability — give the practical test that distinguishes them.
2. Which pillar answers each of: "are we healthy?", "where did the time go?", "what exactly failed?"
3. Why is unstructured logging a dead end? Rewrite a bad log line as a good one.
4. What must never appear in logs, and how do you enforce that reliably?
5. What is metric cardinality, and why is `user_id` as a label a disaster?
6. Name the four golden signals. Why must latency be split by outcome?
7. Why do averages lie? Explain the "100 backend calls with p99 = 2 s" maths.
8. Why is `avg(p99)` meaningless?
9. What is W3C trace context, and why must it cross message brokers?
10. Head-based vs tail-based sampling — why is tail-based usually correct?
11. Define SLI, SLO and SLA. Why must the SLO be stricter than the SLA?
12. What is an error budget, and what organisational argument does it settle?
13. Explain multi-window burn-rate alerting and why two windows are used.
14. Why is alert fatigue more dangerous than missing alerts?
15. Walk through debugging a latency spike using all three pillars in order.

---

## 18.13 Key takeaways

- **Monitoring answers known questions; observability answers unknown ones**
- **Three pillars, one workflow:** metrics alert → traces localise → logs explain
- **Structured logs with a trace ID** on every line — and return that ID to the client
- **Cardinality kills.** IDs belong in logs and traces, never in metric labels.
- **Percentiles, not averages.** The tail is the user experience.
- **Distributed tracing is what makes distributed systems debuggable** — propagate context everywhere, including through queues
- **OpenTelemetry** so instrumentation outlives your vendor choice
- **Tail-based sampling** keeps the traces that matter
- **SLOs and error budgets turn reliability into a shared, numeric decision** — and make explicit that 100% is the wrong target
- **Alert on symptoms with burn rates, always with a runbook, and delete noisy alerts**
- **Deploy markers on dashboards** are the cheapest root-cause tool you will ever add
- **Instrument before the incident.** Observability added afterwards is a postmortem action item, not a capability.

---

**Next:** [Chapter 19 — Reliability & Disaster Recovery](19-reliability-and-disaster-recovery.md)
