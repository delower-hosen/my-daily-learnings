# অধ্যায় ১৮ — Observability 🟢

> **Monitoring** আপনাকে বলে *যে* কিছু একটা ভুল।
> **Observability** আপনাকে বের করতে দেয় *কেন* — এমন ব্যর্থতার জন্যও যা আপনি কখনো ভাবেননি।
>
> একটা distributed system-এ observability ঐচ্ছিক টুল নয়। আপনার আর অনুমানের মাঝে দাঁড়ানো একমাত্র জিনিস এটাই।

---

## ১৮.১ Monitoring বনাম Observability

| | **Monitoring** | **Observability** |
|---|---|---|
| উত্তর দেয় | জানা প্রশ্নের | **অজানা** প্রশ্নের |
| যা দিয়ে তৈরি | আগে থেকে বানানো dashboard আর alert | সমৃদ্ধ, high-cardinality telemetry যা আপনি যথেচ্ছভাবে কাটতে পারেন |
| "CPU কি বেশি?" | ✅ | ✅ |
| "১৪:২০ থেকে সিঙ্গাপুরে Android-এ enterprise tenant-দের checkout request ধীর কেন?" | ❌ | ✅ |

**আনুষ্ঠানিক সংজ্ঞা:** একটা সিস্টেম observable যদি আপনি **নতুন কোড ship না করেই** এর বাইরের output থেকে ভেতরের অবস্থা নির্ধারণ করতে পারেন।

> **ব্যবহারিক পরীক্ষা:** একজন customer একটা সমস্যা জানালে আপনি কি একটা log লাইন যোগ করে deploy না করেই পাঁচ মিনিটের মধ্যে *"`abc123` request-টার কী হয়েছিল?"* — এর উত্তর দিতে পারেন? না পারলে আপনার monitoring আছে, observability নয়।

### Distributed system-এ এটা কেন বেশি গুরুত্বপূর্ণ

একটা monolith-এ একটা stack trace পুরো গল্প বলে। ৮টা service-এ একজন ব্যবহারকারীর একটা কাজ ৮টা আলাদা log stream, ৮ সেট metric তৈরি করে, আর পুরো পথটা জানে এমন কোনো একটা জায়গা নেই। **Telemetry-টা design করতে হয়** — এটা আপনাআপনি আসে না।

---

## ১৮.২ তিনটা স্তম্ভ 🟢

```
┌─────────────────────────────────────────────────────────────┐
│  LOG        বিচ্ছিন্ন ঘটনা          "কী ঘটেছিল"                │
│  METRIC     সংখ্যাসূচক সমষ্টি        "কত / কত ঘন ঘন"           │
│  TRACE      request-এর যাত্রা       "সময়টা কোথায় গেল"          │
└─────────────────────────────────────────────────────────────┘
```

এগুলো পরিপূরক, আর প্রতিটা আলাদা ধরনের প্রশ্নের উত্তর দেয়:

| প্রশ্ন | স্তম্ভ |
|----------|--------|
| "আমরা কি এখন সুস্থ?" | **Metric** (একটা dashboard) |
| "এই request-এ কোন service ধীর?" | **Trace** |
| "ওই একটা ব্যর্থতায় ঠিক কী ভুল হয়েছিল?" | **Log** |
| "Deploy-এর পর থেকে এটা কি খারাপ হয়েছে?" | **Metric** |
| "কতগুলো tenant প্রভাবিত?" | **Metric** (tenant একটা মাত্রা হিসেবে) বা trace |

**এগুলো যে কাজের ধারা সমর্থন করে, ক্রম অনুযায়ী:**
```
Metric-এর alert বাজল  →  Dashboard এটাকে একটা service আর সময়ের জানালায় সংকুচিত করে
                      →  Trace দেখায় কোন span ধীর বা ব্যর্থ
                      →  ওই trace ID-র log সঠিক error দেয়
```

কোনো একটা স্তম্ভ না থাকলে ওই শৃঙ্খল ভেঙে যায় আর আপনি আবার অনুমানে ফিরে আসেন।

---

## ১৮.৩ Log 🟢

### Structured logging — আপসহীন

```python
# ❌ অকাঠামোবদ্ধ: খোঁজা যায় না, parse করা যায় না, aggregate করা যায় না
logger.info(f"User {user_id} verification failed with score {score} after {ms}ms")

# ✅ কাঠামোবদ্ধ: প্রতিটা field query-যোগ্য
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

এখন আপনি জিজ্ঞেস করতে পারেন: *"গত এক ঘণ্টায় tenant t_42-র ব্যর্থ verification-এর p95 সময়কাল দেখাও, reason অনুযায়ী দলবদ্ধ করে।"* অকাঠামোবদ্ধ সংস্করণে এটা একটা regex-দুঃস্বপ্ন, আর তবু ভুল হবে।

### Log-এর level — ধারাবাহিকভাবে ব্যবহার করুন

| Level | মানে | উদাহরণ | কাজ |
|-------|---------|---------|--------|
| **ERROR** | কিছু একটা fail করেছে যাতে মনোযোগ দরকার | Retry-র পরও payment gateway-তে পৌঁছানো যাচ্ছে না | তদন্ত করুন; প্রায়ই alert |
| **WARN** | অপ্রত্যাশিত কিন্তু সামলানো হয়েছে | দ্বিতীয় ভেন্ডরে নেমে গেছে | হার লক্ষ্য করুন |
| **INFO** | উল্লেখযোগ্য business ঘটনা | Session তৈরি, verification সম্পন্ন | স্বাভাবিক কাজ |
| **DEBUG** | বিস্তারিত রোগনির্ণয় | Request/response-এর payload, সিদ্ধান্তের শাখা | Production-এ বন্ধ (বা sample করা) |

> **সবচেয়ে সাধারণ ভুল: সামলানো অবস্থাকে ERROR হিসেবে log করা।** একজন ব্যবহারকারীর ভুল password টাইপ করা কোনো error নয় — এটা প্রত্যাশিত আচরণ। আপনার ERROR log-এ যদি ঘণ্টায় হাজারটা এন্ট্রি থাকে, তাহলে কেউ সেটা পড়ে না, আর একমাত্র আসল error-টা গোলমালে লুকিয়ে থাকে। **ERROR মানে "একজন মানুষের সম্ভবত এটা দেখা উচিত।"**

### কী log করবেন — আর কী কখনো করবেন না

```
✅ LOG করুন
   - Method, path, status, সময়কাল, tenant সহ request-এর শুরু/শেষ
   - Business-এর ঘটনা (order দেওয়া, verification সম্পন্ন, refund দেওয়া)
   - সব বাইরের call: লক্ষ্য, সময়কাল, ফলাফল, retry-র সংখ্যা
   - State-এর পরিবর্তন
   - Authorization-এর প্রত্যাখ্যান (অধ্যায় ১৭)
   - পূর্ণ প্রেক্ষাপট আর একটা stack trace সহ error
   - Startup-এ configuration (secret মুছে দিয়ে)

❌ কখনো LOG করবেন না
   - Password, token, API key, session ID, private key
   - পূর্ণ credit card নম্বর, CVV
   - যতটুকু দরকার তার বেশি পূর্ণ PII (একটা ID log করুন, একটা ইমেইল বা নাম নয়)
   - Biometric data বা document-এর ছবি
   - উপরের কিছু আছে এমন সম্পূর্ণ request body
   - Health-check request (এগুলো বাকি সব ডুবিয়ে দেবে)
```

> **Redaction logger-এর ভেতরেই বানান**, একটা processor হিসেবে — প্রতিটা ডেভেলপারের মনে রাখার উপর নির্ভর করবেন না। `password`, `token`, `secret`, `authorization` বা `card_number` নামের একটা field কোনো log sink-এ পৌঁছানোর আগেই স্বয়ংক্রিয়ভাবে `[REDACTED]` দিয়ে বদলে যাওয়া উচিত।

### Correlation — যে field log-কে ব্যবহারযোগ্য করে

প্রতিটা log লাইনে **trace ID** থাকতেই হবে। এটা ছাড়া একটা request-এর জন্য ৮টা service-এর log মেলানো manual প্রত্নতত্ত্ব।

```python
# Middleware: একটা trace context বের করুন বা বানান আর পুরো request-এর জন্য bind করুন
@app.middleware("http")
async def correlation(request: Request, call_next):
    trace_id = request.headers.get("traceparent", "").split("-")[1:2] or [uuid4().hex]
    with structlog.contextvars.bound_contextvars(
        trace_id=trace_id[0],
        tenant_id=request.state.tenant_id,
        request_path=request.url.path,
    ):
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id[0]   # ⭐ CLIENT-কেও এটা দিন
        return response
```

> **Trace ID-টা client-কে ফেরত দিন** একটা response header-এ আর error payload-এ (অধ্যায় ০৮)। একজন customer বলেন "এটা fail করেছে, এই যে ID" আর আপনি সেকেন্ডে সঠিক request-টা খুঁজে পান। এই একটা খুঁটিনাটিই support-কে বদলে দেয়।

### খরচ নিয়ন্ত্রণ

Log সাধারণত একটা observability বিলের সবচেয়ে ব্যয়বহুল অংশ। ৫,০০০ RPS-এ প্রতি log লাইনে ২ KB হলে সেটা ১০ MB/s — মোটামুটি দিনে ৮৫০ GB।

| কৌশল | প্রভাব |
|-----------|--------|
| **DEBUG/INFO sample করুন** | সফল request-এর ১–১০% রাখুন, error-এর ১০০% |
| **স্তরভিত্তিক retention** | ৭ দিন গরম (খোঁজা যায়), ৯০ দিন উষ্ণ, ১ বছর ঠান্ডা object storage-এ |
| **Agent-এই গোলমাল ফেলে দিন** | Health check, static asset-এর request |
| **বিবরণ trace আর metric-এ সরান** | "কতগুলো"-র জন্য একটা metric প্রতিটায় একটা log লাইনের চেয়ে হাজার গুণ সস্তা |
| **প্রতি service-এ volume সীমিত করুন** | একটা বাচাল service-কে বাজেট খেয়ে ফেলা থেকে ঠেকায় |

> **Tail-based sampling হলো পরিশীলিত সংস্করণ:** যে trace-এ একটা error আছে বা একটা latency-সীমা ছাড়িয়েছে তার ১০০% রাখুন, আর বাকির ১%। আপনি আকর্ষণীয় সবকিছু রাখেন আর একঘেয়ে প্রায় কিছুই না।

---

## ১৮.৪ Metric 🟢

### চার ধরন

| ধরন | আচরণ | উদাহরণ |
|------|-----------|---------|
| **Counter** | শুধু বাড়ে | `http_requests_total`, `verifications_failed_total` |
| **Gauge** | ওঠে আর নামে | `queue_depth`, `active_connections`, `memory_bytes` |
| **Histogram** | পর্যবেক্ষণের bucket → percentile | `request_duration_seconds` |
| **Summary** | Client-এ হিসাব করা quantile | খুব কমই পছন্দনীয় — instance জুড়ে aggregate করা যায় না |

```python
from prometheus_client import Counter, Histogram, Gauge

verifications = Counter(
    "verifications_total", "Verifications processed",
    ["tenant_tier", "outcome", "method"],          # label = যে মাত্রা দিয়ে কাটতে পারবেন
)
duration = Histogram(
    "verification_duration_seconds", "End-to-end verification duration",
    ["method"],
    buckets=(0.5, 1, 2, 4, 8, 16, 30, 60),         # ⭐ আপনার SLO-র জন্য বাছা, default নয়
)
queue_depth = Gauge("verification_queue_depth", "Jobs waiting")

verifications.labels(tenant_tier="enterprise", outcome="passed", method="active").inc()
duration.labels(method="active").observe(3.412)
```

### Cardinality — যে জিনিসটা আপনার বিল উড়িয়ে দেবে 🟢

**Cardinality** = অনন্য label-মানের সমন্বয়ের সংখ্যা। প্রতিটাই একটা আলাদা time series, চিরকাল জমা থাকে।

```
metric{tenant_tier="enterprise", outcome="passed", method="active"}
  ৩টা tier × ৪টা outcome × ২টা method = ২৪টা series          ✅ ঠিক আছে

metric{user_id="...", session_id="...", trace_id="..."}
  ১০ লাখ user × ১ কোটি session × ∞ trace = CARDINALITY-বিস্ফোরণ   ☠️
```

> **নিয়ম: কখনো একটা metric-এর label-এ একটা সীমাহীন মান রাখবেন না।** কোনো user ID, session ID, trace ID, parameter সহ URL, ইমেইল ঠিকানা, বা কাঁচা error message নয়।
>
> High-cardinality শনাক্তকারী **log আর trace**-এর জিনিস, যেগুলো ঠিক ওই কাজের জন্যই index করা। Metric সমষ্টির জন্য।

```python
# ❌ উড়ে যায়: প্রতি URL-এ একটা series
http_requests.labels(path=f"/sessions/{session_id}").inc()
# ✅ route-এর TEMPLATE ব্যবহার করুন
http_requests.labels(route="/sessions/{id}").inc()
```

### Golden signal ⭐

Google-এর SRE বই service-এর স্বাস্থ্যকে চারটায় নামিয়ে আনে:

| Signal | কী মাপে | কখন alert |
|--------|-----------------|-----------|
| **Latency** | Request-এ কত সময় লাগে — **সফল আর ব্যর্থ আলাদা করুন** | p95/p99 SLO ছাড়ায় |
| **Traffic** | চাহিদা: request/সেকেন্ড, message/সেকেন্ড | অস্বাভাবিক লাফ বা পতন (শূন্যে পতন একটা গুরুতর সংকেত) |
| **Error** | ব্যর্থ request-এর হার | Error-হার বাজেট ছাড়ায় |
| **Saturation** | সিস্টেম কতটা ভরা (CPU, memory, queue, connection, disk) | একটা সীমার কাছে |

**Latency নিয়ে গুরুত্বপূর্ণ খুঁটিনাটি:** সবসময় ফলাফল অনুযায়ী ভাগ করুন। যে ব্যর্থ request তাৎক্ষণিকভাবে ফেরে সেটা আপনার p50-কে *নিচে* টেনে নামায় আর এই সত্যটা লুকায় যে সফল request গুলো ধীর হয়ে গেছে। সাফল্যের latency আলাদাভাবে মাপুন।

Request-চালিত service-এর জন্য **RED** (Rate, Errors, Duration) আর সম্পদের জন্য **USE** (Utilisation, Saturation, Errors) — একই ধারণার আলাদা পোশাক। আপনার service-এ RED আর আপনার infrastructure-এ USE ব্যবহার করুন।

### Percentile, গড় নয় 🟢

```
Request: ১০০ms ×৯৯টা, আর ১টা request ১০,০০০ms-এ
  গড়   = ১৯৯ ms       "দেখতে ঠিকই লাগে"
  p50   = ১০০ ms
  p99   = ১০,০০০ ms    ← ওটা একজন আসল ব্যবহারকারী ভয়াবহ সময় কাটাচ্ছেন
```

> **গড় মিথ্যা বলে।** সবসময় p50, p95, p99 দেখুন — আর ব্যবহারকারী-মুখী যা কিছুর জন্য p99.9-ও।

**"হাজারে এক"-এর বাস্তবতা যাচাই:** একটা পাতা যদি ১০০টা backend call করে, তাহলে p99 = ২ সেকেন্ড মানে মোটামুটি **৬৩% page load**-এ অন্তত একটা ২ সেকেন্ডের call আছে। লেজের latency ব্যবহারকারীর অভিজ্ঞতাকে মানুষের ধারণার চেয়ে অনেক বেশি প্রভাবিত করে।

**Instance বা সময়ের জানালা জুড়ে কখনো percentile গড় করবেন না।** `avg(p99)` গাণিতিকভাবে অর্থহীন। একটা histogram ব্যবহার করুন আর aggregate করা bucket-এর উপর quantile হিসাব করুন (Prometheus-এ `histogram_quantile`)।

---

## ১৮.৫ Distributed tracing ⭐ 🟢

**যেটা distributed system-কে debug-যোগ্য করে।**

```
Trace: 4bf92f3577b34da6a3ce929d0e0e4736     (একজন ব্যবহারকারীর একটা request, শুরু থেকে শেষ)

api-gateway            ├──────────────────────────────────────────┤  ৮৪২ms
 └ verification-api    │ ├────────────────────────────────────┤     ৭৯৮ms
    ├ auth-check       │ │ ├──┤                                      ১৮ms
    ├ db: get_session  │ │    ├──┤                                   ১২ms
    ├ s3: fetch_video  │ │       ├────────┤                         ১৪২ms
    ├ vendor: analyse  │ │                ├──────────────────┤      ৫৮০ms ← সমস্যাটা
    │  └ (retry 1)     │ │                ├────────┤                ২৪০ms ← timeout
    │  └ (retry 2)     │ │                         ├─────────┤      ৩৩৮ms
    └ db: save_result  │ │                                   ├──┤    ২৪ms
```

একটা ছবিতে: ভেন্ডরের call মোটের ৬৯%, আর এটা retry হচ্ছে। চারটা service জুড়ে যত log-ই grep করুন, দশ সেকেন্ডে এটা পাবেন না।

### ধারণা

| শব্দ | মানে |
|------|---------|
| **Trace** | একটা request-এর পুরো যাত্রা |
| **Span** | একটা কাজের একক (একটা HTTP call, একটা query, একটা function) |
| **Parent span** | যে span এটা ঘটিয়েছে |
| **Trace context** | Service-এর মধ্যে পাঠানো ID গুলো (W3C `traceparent`) |
| **Baggage** | পুরো trace জুড়ে বহন করা key-value data (tenant ID, feature flag) |
| **Attribute** | একটা span-এর উপর key-value |

### W3C Trace Context — সব জায়গায় পাঠান

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^  ^                                ^                ^
          version  trace-id (৩২ hex)        span-id (১৬ hex)   flag (01=sampled)
```

**এই header-টা প্রতিটা hop-এ পাঠাতে হবে — message broker-এর মধ্য দিয়েও** (অধ্যায় ০৬)। যে trace queue-র সীমানায় থেমে যায় সেটা ঠিক সেই অংশটাই লুকায় যেটা আপনার সবচেয়ে বেশি দেখা দরকার: একটা message তোলার আগে কতক্ষণ অপেক্ষা করেছিল।

### OpenTelemetry 🟢

**তিনটা স্তম্ভের জন্যই ভেন্ডর-নিরপেক্ষ standard।** এটা architecture-গতভাবে গুরুত্বপূর্ণ কারণ এটা আপনার instrumentation-কে আপনার observability ভেন্ডর থেকে আলাদা করে — আপনি একবার instrument করেন, আর configuration বদলে backend বদলান।

```python
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Auto-instrumentation প্রায় কোনো পরিশ্রম ছাড়াই বেশিরভাগ মূল্য দেয়
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
HTTPXClientInstrumentor().instrument()

tracer = trace.get_tracer(__name__)

# Business-অর্থবহ operation-এর জন্য manual span
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

> **Auto-instrumentation দিয়ে শুরু করুন।** এটা এক বিকেলে পুরো request-পথ জুড়ে HTTP, database, cache আর message-broker-এর span দেয়। শুধু সেইসব business operation-এর জন্য manual span যোগ করুন যেগুলো স্বয়ংক্রিয়গুলো দেখতে পায় না।

**OpenTelemetry Collector** আপনার service আর backend-এর মাঝে বসে: এটা telemetry নেয়, প্রক্রিয়া করে (sampling, redaction, সমৃদ্ধকরণ, `k8s.*` metadata যোগ করা) আর যে কোনো জায়গায় export করে। একটা চালানো মানে আপনার application কখনো একটা ভেন্ডরের SDK-র সাথে coupled নয়, আর আপনি কিছু redeploy না করেই backend বদলাতে বা দুটোতে পাঠাতে পারেন।

### Sampling

উচ্চ volume-এ ১০০% tracing ব্যয়বহুল।

| কৌশল | কীভাবে | Trade-off |
|----------|-----|-----------|
| **Head-based** | শুরুতেই ঠিক করুন, যেমন ১% | সহজ, তবে আপনি বেশিরভাগ error মিস করবেন |
| **Tail-based** ⭐ | পুরো trace buffer করুন, তারপর ঠিক করুন | **error আর ধীর trace-এর ১০০% রাখে**, স্বাভাবিকের ১%। Memory সহ একটা collector লাগে। |
| **Adaptive** | Endpoint-এর volume অনুযায়ী হার বদলায় | কম-traffic-এর endpoint-ও যেন প্রতিনিধিত্ব পায় তা নিশ্চিত করে |

> **Tail-based sampling-ই আপনার চাই।** একটা trace-এর পুরো উদ্দেশ্যই অস্বাভাবিক কিছু ব্যাখ্যা করা; head-based sampling ঠিক সেই trace গুলোই ফেলে দেয়।

### Exemplar — metric-কে trace-এর সাথে জোড়া

একটা exemplar একটা metric-এর data point-এ একটা trace ID যুক্ত করে। একটা latency histogram-এ আপনি ধীর bucket-টায় ক্লিক করে সোজা একটা আসল ধীর trace-এ চলে যান। এটা একটা ছোট configuration ধাপ যা metric → trace-এর লাফটা নাটকীয়ভাবে ছোট করে।

---

## ১৮.৬ SLI, SLO, SLA আর error budget 🟢

### সংজ্ঞা

```
SLI  Service Level Indicator  — একটা পরিমাপ
     "৪ সেকেন্ডের কম সময়ে সফলভাবে সম্পন্ন verification request-এর অনুপাত"

SLO  Service Level Objective  — আপনার ভেতরের লক্ষ্য
     "একটা চলমান ৩০ দিনে ৯৯.৫% verification request ৪ সেকেন্ডের মধ্যে সফল হয়"

SLA  Service Level Agreement  — জরিমানা সহ একটা বাইরের চুক্তি
     "মাসিক ৯৯.০% uptime, নয়তো ১০% service credit"
```

> **আপনার SLO আপনার SLA-র চেয়ে কড়া হতেই হবে।** ফাঁকটাই আপনার নিরাপত্তার ব্যবধান। এগুলো সমান হলে আপনার লক্ষ্যের প্রথম লঙ্ঘনই চুক্তির লঙ্ঘন।

### একটা ভালো SLI লেখা

**খারাপ:** "Service-টা দ্রুত আর নির্ভরযোগ্য হওয়া উচিত।"

**ভালো:** বৈধ ঘটনার মধ্যে ভালো ঘটনার একটা অনুপাত:

```
SLI = (৪০০০ms-এর মধ্যে ২xx ফেরত দেওয়া verification request)
    ─────────────────────────────────────────────────────
      (সব verification request, ৪xx client error বাদে)
```

**নিয়ম:**
- যেখানে সম্ভব **ব্যবহারকারীর দৃষ্টিকোণ থেকে** মাপুন (client-এ বা প্রান্তে, গভীর ভেতরে নয়)
- **Client-এর error (৪xx) বাদ দিন** — একজন ব্যবহারকারীর বিকৃত request পাঠানো আপনার অনুপলব্ধতা নয়
- প্রতি ব্যবহারকারী-যাত্রায় ২–৪টা SLI বাছুন, পঞ্চাশটা নয়
- **Availability আর latency একসাথে** — যে service ৩০ সেকেন্ডে ২০০ ফেরত দেয় সেটা কোনো অর্থপূর্ণ অর্থেই available নয়

### Error budget ⭐ — এখানকার সবচেয়ে কাজের ধারণা

```
SLO = ৩০ দিনে ৯৯.৫%
Error budget = ০.৫% = মাসে ৩ ঘণ্টা ৩৯ মিনিট ব্যর্থতা

বাজেট ব্যবহৃত:  ██████████░░░░░░░░░░  ৪৮%  (১ঘ ৪৫মি ব্যবহৃত, ১ঘ ৫৪মি বাকি)
```

**এটা যা সম্ভব করে — এটাই মূল কথা:**

| বাজেটের অবস্থা | টিমের জন্য এর মানে |
|--------------|---------------------------|
| **অনেক বাকি** | দ্রুত ship করুন। ঝুঁকি নিন। Chaos experiment চালান। শুক্রবারে deploy করুন। |
| **প্রায় শেষ** | ঝুঁকিপূর্ণ পরিবর্তন জমিয়ে রাখুন। নির্ভরযোগ্যতার কাজকে অগ্রাধিকার দিন। |
| **শেষ** | **বাজেট না ফেরা পর্যন্ত feature-এর কাজ বন্ধ।** |

> **Error budget একটা অন্তহীন তর্ককে ("দ্রুত এগোও!" বনাম "সাবধান হও!") এমন একটা সংখ্যায় পরিণত করে যাতে দুই পক্ষই আগেভাগে রাজি হয়েছিল।** এটাই এর আসল মূল্য — এটা একটা metric-এর ছদ্মবেশে একটা সাংগঠনিক টুল।

এটা একটা গুরুত্বপূর্ণ কথাও স্পষ্ট করে: **১০০% নির্ভরযোগ্যতা একটা ভুল লক্ষ্য।** এটা অসম্ভব, আর এর পেছনে ছুটলে আপনি কিছুই ship করতে পারবেন না। বাজেট আনুষ্ঠানিকভাবে বলে যে কিছু ব্যর্থতা গ্রহণযোগ্য — আর ঠিক কতটা তা সংজ্ঞায়িত করে।

### Burn-rate alerting ⭐ (কাঁচা সীমা নয়, এতে alert দিন)

```
Burn rate = SLO-র সময়কালের সাপেক্ষে আপনি কত দ্রুত error budget খাচ্ছেন

Burn rate ১×  → আপনি জানালার শেষে ঠিক বাজেটটা শেষ করবেন
Burn rate ১৪× → আপনি ৩০ দিনের বাজেট ~২ দিনে শেষ করবেন     ← কাউকে page করুন
Burn rate ৬×  → ~৫ দিনে শেষ                                 ← কাউকে page করুন
Burn rate ১×  → ধীর পোড়া                                    ← একটা ticket, একটা page নয়
```

```yaml
# Multi-window, multi-burn-rate: তীব্রর জন্য দ্রুত, ধীরে বাড়া সমস্যার জন্য ধীর
- alert: ErrorBudgetBurnFast
  expr: |
    (slo:error_rate:5m  > 14 * 0.005) and
    (slo:error_rate:1h  > 14 * 0.005)
  for: 2m
  labels: { severity: page }
  annotations:
    summary: "Error budget ১৪× হারে পুড়ছে — পুরো বাজেট ~২ দিনে শেষ"
    runbook: "https://runbooks/verification-api/high-error-rate"

- alert: ErrorBudgetBurnSlow
  expr: |
    (slo:error_rate:6h  > 6 * 0.005) and
    (slo:error_rate:24h > 6 * 0.005)
  for: 15m
  labels: { severity: ticket }
```

**দুটো জানালা কেন?** ছোট জানালা এটাকে দ্রুত সাড়া দেওয়ায়; লম্বা জানালা একটা ক্ষণস্থায়ী ঝাঁকুনিকে কাউকে page করা থেকে ঠেকায়। একসাথে এরা আসল সমস্যায় page করে আর গোলমালে চুপ থাকে।

---

## ১৮.৭ Alerting 🟢

### Alerting-এর নিয়ম

> **প্রতিটা page-কে জরুরি, গুরুত্বপূর্ণ, কার্যকর আর আসল হতে হবে।**
> এই চারটার একটাও মিথ্যা হলে সেটা একটা page হওয়া উচিত নয়।

| নিয়ম | কেন |
|------|-----|
| **কারণ নয়, উপসর্গে alert দিন** | "ব্যবহারকারীরা checkout করতে পারছেন না", "CPU ৮৫%" নয়। খুশি ব্যবহারকারী সহ উঁচু CPU কোনো incident নয়। |
| **প্রতিটা alert-এ একটা runbook লাগে** | কোনো নির্দেশনা ছাড়া রাত ৩টার একটা page প্রথম ২০ মিনিট নষ্ট করে |
| **প্রতিটা alert-এ একটা মানবিক কাজ লাগে** | সাড়া যদি হয় "কিছুই না, এটা ঠিক হয়ে যায়" — সেটা মুছে ফেলুন বা automate করুন |
| **শুধু ব্যবহারকারী-প্রভাবিত সমস্যায় page করুন** | বাকি সব একটা ticket |
| **Alert উপেক্ষা করা কঠিন করুন** | মানুষ যদি নিয়মিত একটা alert উপেক্ষা করে, সেটা ভাঙা। ঠিক করুন বা মুছুন। |

### Alert-ক্লান্তিই আসল বিপদ

```
দিনে ৫০টা alert → সব উপেক্ষিত → একমাত্র আসল alert মিস → এমন একটা outage যা কেউ খেয়াল করেনি
```

**এটা কাল্পনিক নয়।** কয়েকটা সুনথিভুক্ত বড় outage-এ alert সঠিকভাবেই বেজেছিল আর উপেক্ষিত হয়েছিল, কারণ ওই alert প্রতিদিন বাজত।

**শৃঙ্খলা:** প্রতি মাসে প্রতিটা page রিভিউ করুন। প্রতিটার জন্য জিজ্ঞেস করুন: *এটা কি আসল ছিল? কার্যকর ছিল? আমরা কি কিছু করেছিলাম?* তিনবার উত্তর না হলে **alert-টা মুছে ফেলুন।** কম সংখ্যক বিশ্বাসযোগ্য alert ব্যাপক গোলমালের চেয়ে বহুগুণ ভালো।

### Severity-র স্তর

| স্তর | মানদণ্ড | সাড়া |
|-------|-----------|----------|
| **P1 / Page** | এখন ব্যবহারকারীরা প্রভাবিত; আয় বা নিরাপত্তা ঝুঁকিতে | সাথে সাথে কাউকে জাগান |
| **P2 / জরুরি ticket** | দুর্বল, বা শীঘ্রই P1 হবে | অফিস-সময়ে, একই দিনে |
| **P3 / Ticket** | ঠিক করার মতো; ব্যবহারকারীর উপর প্রভাব নেই | পরের sprint |
| **Info** | শুধু একটা সংকেত | শুধু dashboard — **কখনো একটা notification নয়** |

---

## ১৮.৮ Dashboard

**তিন স্তর, তিন শ্রোতা:**

```
১. SERVICE HEALTH (on-call dashboard)
   এই service-এর চারটা golden signal। Deploy-এর চিহ্ন। Dependency-র স্বাস্থ্য।
   → ১০ সেকেন্ডে "এই service কি ঠিক আছে?" উত্তর দিতে হবে।

২. BUSINESS / SLO
   SLO অর্জন, বাকি error budget আর burn rate, ঘণ্টায় verification,
   আয়-সংশ্লিষ্ট funnel।
   → সবার জন্য, product আর নেতৃত্ব সহ।

৩. গভীর বিশ্লেষণ (প্রতি subsystem-এ)
   Database: connection, ধীর query, replication lag, cache hit ratio।
   Queue: গভীরতা, বয়স, consumer lag, DLQ-র গভীরতা।
   → তদন্তের জন্য, দেখার জন্য নয়।
```

**Design-এর নিয়ম:**
- **সবচেয়ে গুরুত্বপূর্ণ metric উপরে-বাঁয়ে** (চোখ ওখানেই পড়ে)
- প্রতিটা latency আর error চার্টে **SLO-র সীমা একটা রেখা হিসেবে রাখুন** — প্রেক্ষাপট একটা সংখ্যাকে হারায়
- **Deploy-এর চিহ্ন উপরে বসান।** "এটা ১৪:২২-এ ভাঙল" সাথে "আমরা ১৪:২০-এ deploy করেছি" — এটাই আপনার মূল-কারণ বিশ্লেষণের বেশিরভাগ।
- **প্রশ্নের সাথে মেলে এমন সময়ের পরিসর** — incident-এ ১ ঘণ্টা, প্রবণতায় ৩০ দিন
- **যে dashboard কেউ দেখে না সেটা মুছে ফেলা উচিত।** Dashboard-এর ছড়াছড়ি বাস্তব।

---

## ১৮.৯ Observability দিয়ে একটা incident debug করা

একটা বাস্তবসম্মত হাঁটা — উপরের সবকিছুর অস্তিত্ব এই দক্ষতাটা সম্ভব করার জন্যই।

```
১৪:২২  ALERT: ErrorBudgetBurnFast — verification-api-র error হার বাজেটের ১৪×

১. DASHBOARD (৩০ সেকেন্ড)
   Error-হার ১৪:২০-এ ০.২% → ৮%-এ লাফিয়েছে।
   Latency p99 ৮০০ms → ১২s। Traffic অপরিবর্তিত।
   ১৪:১৯-এ deploy-এর চিহ্ন।   ← শক্ত সংকেত, তবে ধরে নেওয়ার আগে যাচাই করুন

২. সংকুচিত করুন (১ মিনিট)
   Error গুলো মাত্রা অনুযায়ী ভাগ করুন:
     endpoint অনুযায়ী → সব POST /verify-তে
     tenant অনুযায়ী   → সব tenant, একটা নয়
     status অনুযায়ী   → 504 Gateway Timeout
   → এটা tenant-নির্দিষ্ট বা data-নির্দিষ্ট সমস্যা নয়।

৩. TRACE (১ মিনিট)
   Filter: service=verification-api, status=error, শেষ ১৫ মিনিট।
   প্রতিটা ব্যর্থ trace: `vendor.analyse` span ৮s-এ timeout করে।
   ১৪:০০-র trace-এর সাথে তুলনা: ওই span ছিল ৬০০ms।
   → ভেন্ডরই নিকট কারণ, আমাদের deploy নয়।

৪. LOG (১ মিনিট)
   একটা ব্যর্থ trace_id দিয়ে filter করুন।
   "vendor_call_failed reason=connection_timeout host=api.vendor.com attempt=3"
   ভেন্ডরের status পাতা: দুর্বল performance। নিশ্চিত।

৫. উপশম করুন (সাথে সাথে, আরও মূল-কারণ খোঁজার আগেই)
   - Circuit breaker-এর খোলার কথা ছিল — কেন খোলেনি দেখুন
     → সীমা ছিল ২০টা call-এ ৫০%; এই endpoint-এ মিনিটে ৩টা call। খুলতে খুব ধীর।
   - Fallback flag চালু করুন: fail করার বদলে manual review-তে পাঠান
   - Error-হার ০.৩%-এ নামে; verification fail না হয়ে review-র queue-তে যায়

৬. পরে
   - কম-traffic-এর endpoint-এর জন্য circuit breaker-এর configuration ঠিক করুন
   - বিশেষভাবে ভেন্ডর call-এর latency-তে একটা alert যোগ করুন (একটা আগাম নির্দেশক)
   - ভেন্ডরের বিপরীতে একটা synthetic check যোগ করুন
   - দোষারোপহীন postmortem: শনাক্তকরণ ভালো ছিল (২ মিনিট), উপশম ধীর ছিল
     (১৮ মিনিট) কারণ fallback flag-টা অনথিভুক্ত ছিল
```

> **খেয়াল করুন কী এটা সম্ভব করেছিল:** trace ID সহ structured log, কাজের মাত্রা সহ metric, নামযুক্ত span সহ trace, deploy-এর চিহ্ন, আর উপশমের জন্য একটা feature flag। যে কোনো একটা সরিয়ে দিন আর এটা এক ঘণ্টার অনুমান হয়ে যায়।

---

## ১৮.১০ সাধারণ ভুল

১. **অকাঠামোবদ্ধ log** — query করা যায় না, তাই কেউ ব্যবহার করে না
২. **Log-এ কোনো trace ID নেই** — service জুড়ে correlation প্রত্নতত্ত্ব হয়ে যায়
৩. **High-cardinality metric label** — cardinality-বিস্ফোরণ, বিশাল বিল, ধীর query
৪. **Percentile-এর বদলে গড়** — লেজ অদৃশ্য, আর লেজটাই ব্যবহারকারীর অভিজ্ঞতা
৫. **Latency সাফল্য/ব্যর্থতা অনুযায়ী ভাগ করা নেই** — দ্রুত ব্যর্থতা ধীর সাফল্য লুকায়
৬. **উপসর্গ নয়, কারণে alert** — ব্যবহারকারীরা ঠিক আছেন অথচ উঁচু CPU-তে page
৭. **Alert-ক্লান্তি** — দিনে ৫০টা alert মানে আসলটা মিস হয়
৮. **Runbook ছাড়া alert** — রাত ৩টায় ২০ মিনিট নষ্ট
৯. **Secret বা PII log করা** — আপনার logging-এর তৈরি একটা compliance incident
১০. **Head-based sampling** — আপনি ঠিক সেই trace গুলোই sample করে ফেলে দেন যেগুলো লাগত
১১. **Queue-র মধ্য দিয়ে trace context না পাঠানো** — broker-এ প্রবাহটা উধাও হয়ে যায়
১২. **Dashboard-এ কোনো deploy-চিহ্ন নেই** — অস্তিত্বশীল সবচেয়ে কাজের correlation-টা অনুপস্থিত
১৩. **Incident-এর পরে observability যোগ করা** — দরকার হওয়ার আগেই instrument করুন
১৪. **ভেন্ডর-নির্দিষ্ট instrumentation** — backend বদলানো একটা rewrite হয়ে যায় (OpenTelemetry ব্যবহার করুন)
১৫. **Production-এ সবকিছু DEBUG-এ log করা** — বিশাল খরচ, কোনো বাড়তি অন্তর্দৃষ্টি নেই

---

## ১৮.১১ আর্কিটেক্টের চেকলিস্ট

- [ ] প্রতিটা service জুড়ে সামঞ্জস্যপূর্ণ field-নাম সহ structured (JSON) logging
- [ ] প্রতিটা log লাইনে trace ID; HTTP **আর** message broker দুটোতেই trace context পাঠানো
- [ ] Trace ID client-কে একটা response header আর error body-তে ফেরত দেওয়া
- [ ] Logging pipeline-এ secret আর PII-র স্বয়ংক্রিয় redaction
- [ ] Log level সঠিকভাবে ব্যবহৃত; ERROR মানে "একজন মানুষের দেখা উচিত"
- [ ] প্রতি service-এ চারটা golden signal instrument করা; latency ফলাফল অনুযায়ী ভাগ করা
- [ ] Metric-এর label সীমাবদ্ধ — label-এর মান হিসেবে কোনো ID, URL বা message নয়
- [ ] SLO-র সীমার আশেপাশে bucket বাছা histogram
- [ ] OpenTelemetry দিয়ে distributed tracing; auto-instrumentation সাথে business span
- [ ] Tail-based sampling: error আর ধীর trace-এর ১০০%
- [ ] একটা OpenTelemetry Collector application-কে observability ভেন্ডর থেকে আলাদা করে
- [ ] প্রতি ব্যবহারকারী-যাত্রায় SLI সংজ্ঞায়িত, ব্যবহারকারীর দৃষ্টিকোণ থেকে, ৪xx বাদ দিয়ে
- [ ] SLO বসানো, যে কোনো SLA-র চেয়ে কড়া; error budget হিসাব করা আর দৃশ্যমান
- [ ] কাঁচা সীমার বদলে multi-window burn-rate alerting
- [ ] প্রতিটা alert: উপসর্গ-ভিত্তিক, কার্যকর, একটা runbook-এর লিংক সহ
- [ ] Alert মাসে একবার রিভিউ করা; গোলমেলেগুলো মুছে ফেলা
- [ ] Dashboard-এ deploy-এর চিহ্ন বসানো
- [ ] তিন স্তরের dashboard: service health, business/SLO, গভীর বিশ্লেষণ
- [ ] Log-এর retention স্তরায়িত; প্রতি service-এ খরচ monitor আর সীমিত
- [ ] আপনার infrastructure-এর বাইরে থেকে গুরুত্বপূর্ণ ব্যবহারকারী-যাত্রার synthetic check

---

## ১৮.১২ নিজেকে যাচাই

১. Monitoring বনাম observability — যে ব্যবহারিক পরীক্ষাটা এদের আলাদা করে সেটা দিন।
২. কোন স্তম্ভ উত্তর দেয়: "আমরা কি সুস্থ?", "সময়টা কোথায় গেল?", "ঠিক কী fail করেছিল?"
৩. অকাঠামোবদ্ধ logging কেন একটা অন্ধ গলি? একটা খারাপ log লাইনকে ভালো করে লিখুন।
৪. Log-এ কী কখনো থাকা উচিত নয়, আর আপনি কীভাবে সেটা নির্ভরযোগ্যভাবে বলবৎ করবেন?
৫. Metric-এর cardinality কী, আর `user_id` একটা label হিসেবে কেন একটা বিপর্যয়?
৬. চারটা golden signal-এর নাম বলুন। Latency কেন ফলাফল অনুযায়ী ভাগ করতে হবে?
৭. গড় কেন মিথ্যা বলে? "১০০টা backend call, p99 = ২ সেকেন্ড"-এর হিসাবটা ব্যাখ্যা করুন।
৮. `avg(p99)` কেন অর্থহীন?
৯. W3C trace context কী, আর এটা কেন message broker পেরোতে হবে?
১০. Head-based বনাম tail-based sampling — tail-based সাধারণত সঠিক কেন?
১১. SLI, SLO আর SLA-র সংজ্ঞা দিন। SLO কেন SLA-র চেয়ে কড়া হতে হবে?
১২. Error budget কী, আর এটা কোন সাংগঠনিক তর্ক মীমাংসা করে?
১৩. Multi-window burn-rate alerting ব্যাখ্যা করুন আর দুটো জানালা কেন ব্যবহার হয় বলুন।
১৪. Alert-ক্লান্তি অনুপস্থিত alert-এর চেয়ে বেশি বিপজ্জনক কেন?
১৫. তিনটা স্তম্ভ ক্রম অনুযায়ী ব্যবহার করে একটা latency-লাফ debug করে দেখান।

---

## ১৮.১৩ মূল কথাগুলো

- **Monitoring জানা প্রশ্নের উত্তর দেয়; observability অজানা প্রশ্নের**
- **তিন স্তম্ভ, এক ধারা:** metric alert দেয় → trace জায়গা বলে → log ব্যাখ্যা করে
- প্রতিটা লাইনে **trace ID সহ structured log** — আর ওই ID client-কে ফেরত দিন
- **Cardinality মেরে ফেলে।** ID log আর trace-এর জিনিস, কখনো metric-এর label-এ নয়।
- **Percentile, গড় নয়।** লেজটাই ব্যবহারকারীর অভিজ্ঞতা।
- **Distributed tracing-ই distributed system-কে debug-যোগ্য করে** — সব জায়গায় context পাঠান, queue-র মধ্য দিয়েও
- **OpenTelemetry**, যাতে instrumentation আপনার ভেন্ডর-পছন্দের চেয়ে বেশি দিন বাঁচে
- **Tail-based sampling** যে trace গুলো গুরুত্বপূর্ণ সেগুলো রাখে
- **SLO আর error budget নির্ভরযোগ্যতাকে একটা ভাগ করা, সাংখ্যিক সিদ্ধান্তে পরিণত করে** — আর স্পষ্ট করে যে ১০০% একটা ভুল লক্ষ্য
- **Burn rate সহ উপসর্গে alert দিন, সবসময় একটা runbook সহ, আর গোলমেলে alert মুছে ফেলুন**
- **Dashboard-এ deploy-চিহ্ন** আপনার যোগ করা সবচেয়ে সস্তা মূল-কারণ টুল
- **Incident-এর আগেই instrument করুন।** পরে যোগ করা observability একটা postmortem-এর কাজের তালিকা, কোনো ক্ষমতা নয়।

---

**পরবর্তী:** [অধ্যায় ১৯ — Reliability ও Disaster Recovery](19-reliability-and-disaster-recovery.md)

**ইংরেজি সংস্করণ:** [Chapter 18](../18-observability.md) · **[সূচিপত্র](README.md)**
