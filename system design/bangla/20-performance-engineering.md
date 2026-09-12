# অধ্যায় ২০ — Performance Engineering 🟡

> Performance-এর কাজের প্রথম নিয়ম: **মাপুন**।
> দ্বিতীয় নিয়ম: **মাপুন**।
> সময়টা কোথায় যায় সে বিষয়ে ইঞ্জিনিয়াররা ধারাবাহিকভাবে, চমকপ্রদভাবে ভুল করেন — অভিজ্ঞরাও, আপনিও।

---

## ২০.১ পরিভাষা, নিখুঁতভাবে

| শব্দ | সংজ্ঞা | একক |
|------|-----------|------|
| **Latency** | একটা operation-এর সময় | ms |
| **Throughput** | একক সময়ে সম্পন্ন operation | req/s |
| **Concurrency** | এক মুহূর্তে চলমান operation | সংখ্যা |
| **Response time** | *ব্যবহারকারী* যা অনুভব করেন (queue + service-এর সময়) | ms |
| **Service time** | Request-এ আসলে কাজ করার সময় | ms |
| **Queue time** | কাজ শুরুর আগে অপেক্ষার সময় | ms |
| **Utilisation** | একটা সম্পদের ব্যবহৃত ভগ্নাংশ | % |
| **Saturation** | একটা সম্পদ ভরা বলে অপেক্ষমাণ কাজ | queue-র দৈর্ঘ্য |

### যে সম্পর্কটা সবকিছু ব্যাখ্যা করে

```
Response time = Queue time + Service time
```

বেশিরভাগ "app ধীর" incident আসলে **queue time**, service time নয় — কোড ঠিকই আছে, এটা অপেক্ষা করছে। একটা thread, একটা database connection, একটা lock, একটা disk, বা একটা নিচের service-এর অপেক্ষায়।

> **এই কারণেই সমাধানটা এত ঘন ঘন "pool-এ একটা connection যোগ করুন" বা "worker-এর সংখ্যা বাড়ান" হয়, "algorithm optimise করুন" নয়।** কোনো কোড ছোঁয়ার আগে আপনার দুটোর কোনটা আছে নির্ণয় করুন।

### Latency আর throughput এক জিনিস নয়

```
একটা এক-লেনের রাস্তা:        প্রতি গাড়িতে কম latency, কম throughput
একটা দশ-লেনের মহাসড়ক:      প্রতি গাড়িতে একই latency, ১০× throughput
৯৯% ক্ষমতায় একটা দশ-লেনের মহাসড়ক: ভয়াবহ latency, উঁচু throughput
```

আপনি latency-র কোনো উন্নতি ছাড়াই throughput বাড়াতে পারেন (server যোগ করে)। আপনি latency উন্নত করতে (একটা দ্রুত algorithm) আর পার্শ্বপ্রতিক্রিয়ায় throughput-ও উন্নত করতে পারেন। **আপনি কোনটা optimise করছেন বলুন** — টিম নিয়মিত তর্ক করে কারণ তারা আলাদা জিনিস optimise করছে।

---

## ২০.২ Optimise করার আগে মাপুন 🟢

### Amdahl's Law — ভুল জিনিস optimise করা কেন বৃথা

```
Speedup = 1 / ((1 - P) + P/S)
          P = আপনি যে অংশটা optimise করছেন তাতে সময়ের অনুপাত
          S = ওই অংশটা আপনি কত গুণ দ্রুত করলেন
```

**একটা কাজ করা উদাহরণ:**

```
একটা request-এ ১০০০ ms লাগে:
  ২০০ ms application-এর কোড
  ৭৫০ ms database-এর query
   ৫০ ms serialisation

আপনি application-এর কোড ১০× দ্রুত করলেন (২০০ ms → ২০ ms)।
  নতুন মোট = ৮২০ ms। উল্লেখযোগ্য পরিশ্রমে ১৮% উন্নতি।

আপনি একটা index যোগ করলেন আর query ৫০ ms-এ নামল।
  নতুন মোট = ৩০০ ms। দশ মিনিটে ৭০% উন্নতি।
```

> **আপনি optimise করে বাধাটা পেরোতে পারবেন না।** Application-এর কোড *অসীম* দ্রুত করলেও আপনি শুধু ৮০০ ms-এ পৌঁছাবেন। আগে বাধাটা খুঁজুন; বাকি সব নষ্ট পরিশ্রম।

### USE পদ্ধতি — যে কোনো সম্পদের জন্য

প্রতিটা সম্পদের জন্য (CPU, memory, disk, network, connection pool, thread pool):

```
UTILISATION  — এটা কত % সময় ব্যস্ত?
SATURATION   — এর জন্য কতটা কাজ queue-তে অপেক্ষা করছে?
ERROR        — এটা কি fail করছে?
```

**Saturation বেশি গুরুত্বপূর্ণ সংকেত।** খালি run queue সহ ১০০% CPU ঠিক আছে — মেশিন কাজের কাজ করছে। ৪০-এর run queue সহ ৬০% CPU মানে কিছু একটা খুব ভুল (সম্ভবত lock-এর সংঘর্ষ বা I/O-র অপেক্ষা)।

### Profiling — সত্যটা খুঁজুন

| টুলের ধরন | কী বলে | উদাহরণ |
|-----------|------------------|----------|
| **Sampling profiler** | CPU-র সময় কোথায় যায় | py-spy, async-profiler, dotnet-trace, perf |
| **Allocation profiler** | কী আবর্জনা তৈরি করছে | memory_profiler, dotMemory, pprof |
| **Flame graph** | Call-stack-এর খরচের চিত্র | speedscope, FlameGraph |
| **APM / distributed tracing** | **Service জুড়ে** সময় কোথায় যায় | OpenTelemetry (অধ্যায় ১৮) |
| **Database-এর EXPLAIN** | Query-র plan | অধ্যায় ০৯ |
| **Continuous profiling** ⭐ | Production-এর profile, সবসময় চালু | Pyroscope, Parca, Datadog |

```bash
# py-spy: নগণ্য overhead-এ একটা চলমান production process profile করুন — কোনো কোড পরিবর্তন নয়
py-spy top --pid 12345
py-spy record --pid 12345 --duration 60 --output flame.svg
```

> **আপনার ল্যাপটপ নয়, production profile করুন।** Production-এ আসল data-র পরিমাণ, আসল cache-এর অবস্থা, আসল concurrency আর আসল network latency আছে। ১০০ row সহ একটা ল্যাপটপের benchmark ৫ কোটিতে আচরণ সম্পর্কে প্রায় কিছুই বলে না।

**একটা flame graph পড়া:** প্রস্থ = মোট ব্যয়িত সময় (child সহ), call-এর সংখ্যা নয়। **সবচেয়ে চওড়া মালভূমি** খুঁজুন — সেখানেই সময়টা। তার উপরের stack-এর আকৃতি বলে কেন।

---

## ২০.৩ সময়টা আসলে কোথায় যায়

একটা সাধারণ web request-এ, কোনটা কত ঘন ঘন আসল অপরাধী সেই অনুযায়ী:

| স্থান | কারণ | সাধারণ সমাধান |
|------|-------|-------------|
| ১ | **N+1 query** | Join, batch, বা eager-load (অধ্যায় ০৯) |
| ২ | **অনুপস্থিত index** | Index যোগ করুন (অধ্যায় ০৯) |
| ৩ | **ক্রমিক network call** | সমান্তরাল করুন বা একত্র করুন (অধ্যায় ০৮) |
| ৪ | **একটা গরম read-এ কোনো caching নেই** | Cache করুন (অধ্যায় ১১) |
| ৫ | **Connection pool শেষ** | Little's Law দিয়ে আকার দিন (অধ্যায় ০৪) |
| ৬ | **অতিরিক্ত আনা** | যে কলাম লাগে সেগুলোই `SELECT` করুন; paginate করুন |
| ৭ | **Serialisation-এর overhead** | ছোট payload, দ্রুত codec, compression |
| ৮ | **Lock-এর সংঘর্ষ** | ছোট transaction, optimistic concurrency |
| ৯ | **GC-র বিরতি** | Allocation কমান; collector সমন্বয় করুন |
| ১০ | **আসল algorithm-এর জটিলতা** | Business সফটওয়্যারে বিরল, তবে এলে বাস্তব |

> **খেয়াল করুন শীর্ষ দশের নয়টাই I/O, অপেক্ষা, বা data-তে প্রবেশ — CPU-নির্ভর কোড নয়।** Business application প্রায় কখনোই CPU-নির্ভর নয়। ইঞ্জিনিয়াররা algorithm optimise করেন কারণ সেটাই "performance-এর কাজ" মনে হয়, আর database-এর round trip গুলো অপরীক্ষিত থেকে যায়।

### তিন ধরনের সীমাবদ্ধতা

```
CPU-নির্ভর      processor-ই সীমা
                → profile করুন, গরম পথ optimise করুন, সমান্তরাল করুন, scale out
                (image processing, ML inference, compression, crypto)

I/O-নির্ভর      disk বা network-এর অপেক্ষায়
                → concurrency, batching, caching, connection পুনর্ব্যবহার
                → বেশি THREAD সাহায্য করে (তারা অপেক্ষা করছে, হিসাব করছে না)
                (বেশিরভাগ web application)

MEMORY-নির্ভর   allocation, GC, বা cache miss প্রাধান্য পায়
                → allocation কমান, value type ব্যবহার করুন, data-র locality উন্নত করুন
                (উচ্চ-throughput data প্রক্রিয়াকরণ)
```

**একটা কৌশল বাছার আগে আপনার কোনটা আছে চিহ্নিত করুন।** একটা CPU-নির্ভর কাজে thread যোগ করলে সেটা ধীর হয় (context-switch-এর overhead)। একটা I/O-নির্ভর service-এ algorithm optimise করলে কিছুই বদলায় না।

---

## ২০.৪ Optimisation-এর কৌশল 🟢

### ১. কম কাজ করুন

সবচেয়ে কার্যকর optimisation সবসময়ই **কাজটা না করা**।

```python
# আমাদের কি ২০০টা কলামই লাগে?          → শুধু যেটা ব্যবহার হয় সেটা SELECT করুন
# আমাদের কি ১০,০০০ row-ই লাগে?         → paginate করুন
# আমাদের কি প্রতিটা request-এ লাগে?      → cache করুন
# আমাদের কি synchronously লাগে?        → queue-তে দিন
# আমাদের কি আদৌ লাগে?                  → feature-টা মুছে ফেলুন
```

### ২. Batch করুন

```python
# ❌ ১,০০০টা round trip × ০.৫ ms = ৫০০ ms নিখাদ নেটওয়ার্ক
for record in records:
    await db.execute("INSERT INTO events (...) VALUES ($1, $2)", record.a, record.b)

# ✅ একটা round trip
await db.execute_many("INSERT INTO events (...) VALUES ($1, $2)",
                      [(r.a, r.b) for r in records])

# ✅ bulk load-এ আরও ভালো — COPY, INSERT-এর চেয়ে ১০-৫০× দ্রুত
await db.copy_records_to_table("events", records=records, columns=["a", "b"])
```

Batching সব জায়গায় খাটে: database-এর write, API call, message publish, cache read (`MGET`), log পাঠানো।

**Trade-off: batching একক আইটেমের latency বাড়ায়** আর সামগ্রিক throughput বাড়ায়। Async কাজে সেটা বিনামূল্যে। একটা ব্যবহারকারী-মুখী request-এ batch-এর জানালা সীমিত করুন (`linger_ms` ধাঁচে, অধ্যায় ০৭)।

### ৩. সমান্তরাল করুন

```python
# ❌ ক্রমিক: ২০০ + ১৫০ + ৩০০ = ৬৫০ ms
session  = await get_session(id)
customer = await get_customer(cid)
quota    = await get_quota(tid)

# ✅ সমান্তরাল: max(২০০, ১৫০, ৩০০) = ৩০০ ms
session, customer, quota = await asyncio.gather(
    get_session(id), get_customer(cid), get_quota(tid)
)
```

শুধু তখনই যখন call গুলো **স্বাধীন**। আর সমান্তরালতা সীমাবদ্ধ করুন — ১০,০০০ concurrent call আপনার pool শেষ করবে আর নিচের service-এর ক্ষতি করবে (অধ্যায় ০৫-এর bulkhead)।

### ৪. Cache করুন

সবচেয়ে বড় একক লিভার (অধ্যায় ১১)। ২০ ms → ০.৩ ms।

### ৫. Request-এর পথ থেকে কাজ সরান

```python
# ❌ ব্যবহারকারী এই সবের জন্য অপেক্ষা করেন
async def complete_verification(session_id):
    result = await process(session_id)     # ৩ সেকেন্ড — দরকারি
    await send_email(result)               # ৮০০ ms — এখন দরকারি নয়
    await update_analytics(result)         # ২০০ ms — এখন দরকারি নয়
    await call_webhook(result)             # ১.৫ সেকেন্ড — এখন দরকারি নয়, আর fail করতে পারে
    return result                          # মোট: ৫.৫ সেকেন্ড

# ✅ ব্যবহারকারী শুধু যা লাগে তার জন্য অপেক্ষা করেন
async def complete_verification(session_id):
    result = await process(session_id)     # ৩ সেকেন্ড
    await outbox.publish(VerificationCompleted(result))   # ৫ ms (অধ্যায় ০৬)
    return result                          # মোট: ৩ সেকেন্ড
```

> **একটা request-এর প্রতিটা ধাপ সম্পর্কে জিজ্ঞেস করুন: ব্যবহারকারীর উত্তর পাওয়ার আগে কি এটা শেষ হওয়া দরকার?** সাধারণত অন্তত অর্ধেকের ক্ষেত্রে উত্তর না।

### ৬. Payload-এর আকার কমান

| কৌশল | সাধারণ সাশ্রয় |
|-----------|---------------|
| Gzip / Brotli compression | JSON-এ ৭০–৯০% |
| শুধু দরকারি field ফেরত দিন | ৫০–৮০% |
| Pagination | সীমাহীন → সীমাবদ্ধ |
| Binary ফরম্যাট (Protobuf/MessagePack) | JSON-এর চেয়ে ৩০–৬০%, সাথে দ্রুত parsing |
| Image ফরম্যাট (WebP/AVIF) | JPEG-এর চেয়ে ৩০–৫০% |

**API server-এ JSON serialisation প্রায়ই শীর্ষ-৩ CPU খরচ**, আর কেউ এটা profile করে না। একটা বড় response-এ একটা দ্রুত JSON library (orjson, source generator সহ System.Text.Json) এক লাইনের পরিবর্তনে ওই অংশটায় ২–৫× উন্নতি হতে পারে।

### ৭. Connection pooling

অধ্যায় ০৯ আর ১৩-তে আলোচিত। Little's Law দিয়ে আকার (অধ্যায় ০৪):

```
Pool-এর আকার ≈ throughput × গড় ধরে রাখার সময় × নিরাপত্তার গুণক

৫০০ req/s × ২০ ms DB-র সময় = ১০ concurrent → ~২০-র pool যথেষ্টের বেশি
```

> **বড় pool ভালো নয়।** একটা অতিরিক্ত বড় pool সংঘর্ষটা database-এ সরিয়ে দেয় (যার নিজের সীমা আর context-switch-এর খরচ আছে) আর আসল সমস্যা লুকায়। `pool.wait_time` মাপুন; এটা প্রায় শূন্য হলে আপনার pool যথেষ্ট বড়।

### ৮. Async I/O

I/O-নির্ভর কাজে async একটা thread-কে প্রতিটায় একটা thread আটকানোর বদলে হাজার হাজার concurrent অপেক্ষা সামলাতে দেয়।

**তবে:** একটা async event loop-এ একটা blocking call *সবকিছু* থামিয়ে দেয়। একটা `time.sleep()`, একটা synchronous database driver, বা একটা async handler-এ একটা CPU-ভারী লুপ throughput এমনভাবে ধ্বংস করবে যা সত্যিই নির্ণয় করা কঠিন। Blocking কাজের জন্য `run_in_executor` ব্যবহার করুন, আর আপনার library গুলো যাচাই করুন।

### ৯. Index আর query optimisation

অধ্যায় ০৯। সাধারণত একটা business application-এ উপলব্ধ সবচেয়ে বেশি-মূল্যের performance-কাজ।

---

## ২০.৫ Load testing 🟢

### চার ধরন — এগুলো আলাদা প্রশ্নের উত্তর দেয়

| ধরন | প্রশ্ন | পদ্ধতি |
|------|----------|--------|
| **Load test** | প্রত্যাশিত load-এ কি এটা SLO মেটায়? | লক্ষ্যে ওঠান, ১০–৩০ মিনিট ধরে রাখুন |
| **Stress test** | এটা কোথায় ভাঙে, আর কীভাবে? | ব্যর্থতা পর্যন্ত ওঠান |
| **Soak test** ⭐ | এটা কি ঘণ্টার পর ঘণ্টা টেকসই load টেকে? | ৪–২৪ ঘণ্টা লক্ষ্য load |
| **Spike test** | এটা কি একটা আচমকা ঢেউ টেকে? | সাথে সাথে ১০×-এ লাফ দিন |

**Soak test-ই সেটা যা বেশিরভাগ টিম এড়িয়ে যায়, আর এটা এমন সমস্যা ধরে যা অন্য কোনোভাবে খুঁজে পাওয়া সবচেয়ে কঠিন:** memory leak, connection leak, file-handle শেষ হওয়া, log দিয়ে disk ভরা, cache সীমাহীনভাবে বাড়া, TIME_WAIT জমা। এগুলো একটা ৫ মিনিটের test-এ আসে না — এগুলো production-এ চতুর্থ দিনে রাত ৩টায় আসে।

**Stress test-এর আসল মূল্য হলো ব্যর্থতার রূপটা জানা।** এটা কি ধাপে ধাপে দুর্বল হয়, load shed করে, আর ফিরে আসে? নাকি ভেঙে পড়ে আর একটা manual restart লাগে? একটা আসল traffic-ঢেউয়ের আগে আপনি সেটা জানতে চান।

### একটা কাজের load test লেখা

```javascript
// k6 — বাস্তবসম্মত, এমন threshold সহ যা test FAIL করায়
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m',  target: 50 },   // গরম করুন — কখনো পূর্ণ load-এ শুরু করবেন না
    { duration: '5m',  target: 200 },  // ওঠান
    { duration: '20m', target: 200 },  // ⭐ টেকসই — সত্যটা এখানেই থাকে
    { duration: '2m',  target: 0 },    // নামান
  ],
  thresholds: {
    http_req_duration: ['p(95)<400', 'p(99)<1000'],   // SLO-র সাথে মেলে
    http_req_failed:   ['rate<0.01'],
    checks:            ['rate>0.99'],
  },
};

export default function () {
  // বাস্তবসম্মত মিশ্রণ: ৯০% read, ১০% write — একটা endpoint-এর ১০০% নয়
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
  sleep(Math.random() * 3);            // ভাবার সময় — ব্যবহারকারীরা bot নন
}
```

### যে নিয়মগুলো load test-কে অর্থবহ করে

১. **Production-সদৃশ পরিবেশে test করুন।** অর্ধেক instance আর একটা ক্ষুদ্র dataset এমন সংখ্যা দেয় যার কোনো মানে নেই।
২. **বাস্তবসম্মত data-র পরিমাণ ব্যবহার করুন।** ১,০০০ row-তে একটা query আর ৫ কোটিতে সেই একই query আলাদা query।
৩. **বাস্তবসম্মত access-এর ধরন** — আসল সিস্টেমে গরম key আর একটা লম্বা লেজ থাকে। সমান এলোমেলো access অবাস্তবভাবে ভালো cache hit ratio দেয়।
৪. **ভাবার সময় রাখুন।** ব্যবহারকারীরা থামেন; bot থামে না।
৫. **আগে গরম করুন** — JIT compilation, connection pool আর cache সবগুলোরই স্থির অবস্থায় পৌঁছাতে হয়।
৬. **শুধু client নয়, পরীক্ষাধীন সিস্টেমও monitor করুন।** Client বলে এটা ধীর; server বলে কেন (CPU, connection, GC, queue-র গভীরতা)।
৭. **ব্যর্থতার রূপগুলোও test করুন** — লক্ষ্যের ১৫০%-এ কী হয়?
৮. **Load generator নিজেই দেখুন।** একটা পূর্ণ client যে latency জানায় সেটা তার নিজের, server-এর নয়। এটা নিয়মিত মানুষকে বোকা বানায়।

### Coordinated omission — বেশিরভাগ load test ফলাফলের bug ⭐

```
আপনার টুল প্রতি ১০০ ms-এ একটা request পাঠায়। Server ১০ সেকেন্ড থেমে যায়।
একটা সরল টুল response-এর জন্য অপেক্ষা করে, তারপর এগোয় — তাই ওই থেমে থাকার
সময়ে যে ১০০টা request পাঠানোর কথা ছিল সেগুলো এটা কখনো পাঠায় না।

ফলাফল: এটা ক্রমশ-বিলম্বিত ১০০টার বদলে একটা ধীর request লিপিবদ্ধ করে।
আপনার জানানো p99 ঠিকই লাগে। আসল ব্যবহারকারীরা একটা ১০ সেকেন্ডের outage পেয়েছিলেন।
```

**এমন টুল ব্যবহার করুন যা এটা সংশোধন করে** (k6, wrk2, Gatling, throughput shaping সহ JMeter) — আসল নয়, *উদ্দিষ্ট* সময়সূচির বিপরীতে মেপে। যেসব টুল কেবল "পাঠাও, অপেক্ষা করো, পাঠাও" লুপ করে, সেগুলো লেজের latency ব্যবস্থিতভাবে কম দেখায় — প্রায়ই মাত্রার একটা ধাপ কম।

---

## ২০.৬ Frontend আর অনুভূত performance 🟡

Backend ইঞ্জিনিয়াররা এখানে কম বিনিয়োগ করেন, কিন্তু ব্যবহারকারীরা frontend-ই অনুভব করেন।

### Core Web Vitals

| Metric | কী মাপে | ভালো |
|--------|----------|------|
| **LCP** (Largest Contentful Paint) | মূল বিষয়বস্তু কখন আসে | < ২.৫ সেকেন্ড |
| **INP** (Interaction to Next Paint) | Input-এ সাড়া | < ২০০ ms |
| **CLS** (Cumulative Layout Shift) | দৃশ্যগত স্থিতিশীলতা | < ০.১ |

### অনুভূত performance প্রায়ই আসল performance-কে হারায়

| কৌশল | প্রভাব |
|-----------|--------|
| **Skeleton screen** | একটা spinner-এর চেয়ে দ্রুত লাগে — চোখ কাঠামো আসতে দেখে |
| **Optimistic UI** | ফলাফল সাথে সাথে দেখান, পরে server-এর সাথে মিলিয়ে নিন |
| **Progressive rendering / streaming** | ২ সেকেন্ডে সবকিছুর বদলে ২০০ ms-এ কিছু একটা আসে |
| **Hover-এ prefetch** | ক্লিক শেষ হওয়ার আগেই পাতা load হচ্ছে |
| **তাৎক্ষণিক প্রতিক্রিয়া** | ১০০ ms-এর মধ্যে সাড়া তাৎক্ষণিক লাগে, সেটা শুধু একটা spinner শুরু হলেও |

**মানুষের যে সীমাগুলো জানার মতো:**
```
< ১০০ ms   তাৎক্ষণিক লাগে
< ১ সেকেন্ড  চিন্তার প্রবাহ অবিচ্ছিন্ন — কঠোরভাবে কোনো প্রতিক্রিয়া লাগে না
< ১০ সেকেন্ড মনোযোগ ধরে রাখে, তবে প্রতিক্রিয়া (progress) অপরিহার্য
> ১০ সেকেন্ড ব্যবহারকারী চলে যান বা কাজ বদলান
```

> **একটা progress bar সহ ৩ সেকেন্ডের operation একটা জমে যাওয়া পর্দা সহ ২ সেকেন্ডের operation-এর চেয়ে অনেক ভালো লাগে।** অনুভূত performance একটা design-সিদ্ধান্ত, শুধু engineering-এর নয়।

---

## ২০.৭ Performance-এর বাজেট আর regression শনাক্তকরণ

**একটা performance budget হলো গতির জন্য একটা SLO, CI-তে বলবৎ করা** — একটা fitness function (অধ্যায় ০০)।

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
      budget: 10          # ⭐ N+1 regression স্বয়ংক্রিয়ভাবে ধরে
```

**Query-সংখ্যার বাজেটটাই সবচেয়ে বেশি মূল্যের।** একটা নিরীহ-দেখতে ORM পরিবর্তনে ঢোকা একটা N+1 প্রতিটা functional test পাস করে। "এই endpoint-এ ≤ ১০টা query হতে হবে" — এটা দাবি করলে সেটা pull request-এই ধরা পড়ে।

```python
# একটা test যা অস্তিত্বশীল সবচেয়ে সাধারণ performance regression ঠেকায়
async def test_session_list_query_count(client, query_counter):
    await client.get("/v1/sessions?limit=50")
    assert query_counter.count <= 3, (
        f"N+1 detected: {query_counter.count} queries. "
        f"Queries: {query_counter.queries}"
    )
```

**Production-এও regression শনাক্ত করুন:** প্রতি endpoint-এ এই সপ্তাহের p95 গত সপ্তাহের সাথে তুলনা করুন, আর উল্লেখযোগ্য বৃদ্ধিতে alert দিন। Performance ধীরে ধীরে ক্ষয় হয়, একবারে একটা অলক্ষিত পরিবর্তনে, যতক্ষণ না কেউ অভিযোগ করে — আর ততক্ষণে কারণটা তিন মাসের commit-এর নিচে চাপা পড়ে গেছে।

---

## ২০.৮ কখন optimise করবেন না 🟢

> *"অকাল optimisation সব অনিষ্টের মূল।"* — Knuth
>
> তবে পুরো উক্তিটা গুরুত্বপূর্ণ: *"আমাদের ছোট দক্ষতার কথা ভুলে যাওয়া উচিত, ধরা যাক ৯৭% সময়... **তবু ওই গুরুত্বপূর্ণ ৩%-এ আমাদের সুযোগ হাতছাড়া করা উচিত নয়।**"*

**Optimise করবেন না যখন:**
- আপনি মাপেননি — আপনি ভুল জিনিস optimise করবেন
- এটা গুরুত্বপূর্ণ পথে নেই
- এটা ইতিমধ্যেই চাহিদা মেটায় (২০০ ms SLO সহ একটা ৮০ ms-এর endpoint *শেষ*)
- জটিলতার খরচ লাভকে ছাড়িয়ে যায়
- বাধাটা অন্য কোথাও (Amdahl)
- এটা কোডকে এমন কঠিন করে যার লাভ কেউ খেয়ালই করবে না

**Optimise করুন যখন:**
- আপনি মেপেছেন আর বাধাটা চিহ্নিত করেছেন
- এটা গুরুত্বপূর্ণ পথে, p95/p99-এ
- একটা আসল SLO মিস হচ্ছে, বা একটা আসল খরচ হচ্ছে
- এটা architecture-গত আর পরে বদলানো ব্যয়বহুল হবে (data model, protocol, sharding key)

### যে "গুরুত্বপূর্ণ ৩%" আগেভাগে design করার মতোই

কিছু performance সিদ্ধান্ত architecture-গত আর সস্তায় পরে বসানো যায় না (অধ্যায় ০০-এর ব্যয়বহুল-পরিবর্তনের নিয়ম):

- **Data model আর access-এর ধরন** — অনুপযুক্ত আকৃতি মানে একটা rewrite
- **Sharding/partition key** — পরে বদলানো প্রায় অসম্ভব (অধ্যায় ০৪)
- **Synchronous বনাম asynchronous** সীমানা
- **বাচাল বনাম মোটা দাগের API design** — client নির্ভর করা শুরু করলে বদলানো কঠিন
- **State কোথায় থাকে** — পরে বাইরে সরানো একটা বড় প্রজেক্ট

বাকি সব: সহজভাবে বানান, মাপুন, তারপর যা আসলে ধীর সেটা optimise করুন।

---

## ২০.৯ একটা performance তদন্ত, শুরু থেকে শেষ

```
অভিযোগ: "Session-এর তালিকার পাতা ধীর।"

১. পরিমাণ দিন      "ধীর" কোনো পরিমাপ নয়।
   Dashboard: GET /v1/sessions  p50 = ১৮০ ms, p95 = ৩.২ s, p99 = ৮.১ s
   → মধ্যমা ঠিকই আছে; লেজটা ভয়াবহ → কিছু একটা শর্তসাপেক্ষ

২. ভাগ করুন        আপনার কাছে থাকা প্রতিটা মাত্রা দিয়ে ভাগ করুন।
   tenant অনুযায়ী   → > ১০,০০০ session আছে এমন tenant ধীর। ছোট tenant ঠিক আছে।
   → এটা data-পরিমাণ নির্ভর, একটা বৈশ্বিক সমস্যা নয়

৩. TRACE           একটা ধীর trace খুঁজুন (tail-based sampling নিশ্চিত করেছে যে আপনার আছে)।
   Span-এর ভাগ:  auth ১২ ms · db.query ২,৯৮০ ms · serialise ১৯০ ms
   → এটা query-টা

৪. EXPLAIN         আসল query-তে EXPLAIN (ANALYZE, BUFFERS) চালান।
   Seq Scan on sessions  (rows=1,240,000)  Rows Removed by Filter: 1,238,000
   → (tenant_id, status, created_at)-এর জন্য কোনো ব্যবহারযোগ্য index নেই

৫. সমাধান          CREATE INDEX CONCURRENTLY idx_sessions_tenant_status_created
                     ON sessions (tenant_id, status, created_at DESC);
   → p95: ৩.২ s → ৯৫ ms

৬. যাচাই           শুধু স্থানীয়ভাবে নয়, production-এর metric-এ নিশ্চিত করুন।
   এটাও দেখুন: অন্য কোনো query-plan কি পিছিয়ে গেল? Write-এর latency কি বাড়ল?

৭. প্রতিরোধ         এই endpoint-এর জন্য একটা query-সংখ্যা আর latency বাজেট test যোগ করুন।
                   প্রতি endpoint-এ p95-এ একটা alert যোগ করুন।
                   একই অনুপস্থিত-index ধরনের জন্য অন্য endpoint রিভিউ করুন।
```

> **২ নম্বর ধাপটাই একজন ভালো ইঞ্জিনিয়ারকে একজন অসাধারণ ইঞ্জিনিয়ার থেকে আলাদা করে।** "এটা ধীর" কার্যকর নয়। "এটা শুধু ১০,০০০-এর বেশি row আছে এমন tenant-দের জন্য ধীর" — এটা একটা profiler খোলার আগেই সরাসরি একটা অনুপস্থিত index-এর দিকে ইশারা করে।

---

## ২০.১০ সাধারণ ভুল

১. **না মেপে optimise করা** — সময় কোথায় যায় সে বিষয়ে আপনি ভুল হবেন
২. **ভুল ৫% optimise করা** — Amdahl's Law এটাকে বৃথা করে
৩. **ক্ষুদ্র data সহ একটা ল্যাপটপে benchmark** — production সম্পর্কে কিছুই প্রমাণ করে না
৪. **Percentile-এর বদলে গড়** — লেজটাই ব্যবহারকারীর অভিজ্ঞতা (অধ্যায় ১৮)
৫. **Load test-এ coordinated omission** — জানানো p99 মাত্রার একটা ধাপ বেশি ভালো
৬. **কোনো soak test নেই** — leak আর শেষ হয়ে যাওয়া চতুর্থ দিনে, production-এ আসে
৭. **পরীক্ষাধীন সিস্টেম monitor না করে load test** — আপনি জানেন এটা ধীর, কেন নয়
৮. **একটা পূর্ণ load generator** — আপনি আপনার client মাপছেন
৯. **সীমাহীন সমান্তরালতা** — আপনি নিজের dependency-কে DDoS করছেন
১০. **অতিরিক্ত বড় connection pool** — সংঘর্ষ database-এ সরায় আর সমস্যা লুকায়
১১. **একটা async event loop-এ একটা blocking call** — throughput ভেঙে পড়ে, কারণ অস্পষ্ট
১২. **Serialisation-এর খরচ উপেক্ষা করা** — প্রায়ই শীর্ষ-৩ CPU খরচ, খুব কমই profile করা
১৩. **কোনো performance regression test নেই** — গতি একবারে একটা commit করে ক্ষয় হয়
১৪. **অনুভূত performance উপেক্ষা করা** — একটা জমে যাওয়া UI-র পেছনে দ্রুত backend-ও ধীর লাগে
১৫. **যা ইতিমধ্যেই চাহিদা মেটায় সেটা optimise করা**

---

## ২০.১১ আর্কিটেক্টের চেকলিস্ট

- [ ] Performance-এর চাহিদা প্রতি endpoint-এ SLO সহ percentile হিসেবে বলা
- [ ] গুরুত্বপূর্ণ পথ চিহ্নিত; optimisation-এর পরিশ্রম সেখানেই কেন্দ্রীভূত
- [ ] Production-এ profiling উপলব্ধ (আদর্শভাবে continuous profiling)
- [ ] Distributed tracing service জুড়ে সময় কোথায় যায় দেখায় (অধ্যায় ১৮)
- [ ] Slow-query logging আর `pg_stat_statements` চালু আর রিভিউ করা
- [ ] N+1 শনাক্তকরণ: মূল endpoint-এ query-সংখ্যার বাজেট test
- [ ] Connection pool Little's Law দিয়ে আকার দেওয়া; pool-এর অপেক্ষার সময় monitor করা
- [ ] গরম read-এর জন্য caching-এর কৌশল বসানো (অধ্যায় ১১)
- [ ] অপ্রয়োজনীয় কাজ request-এর পথ থেকে সরানো (queue + outbox)
- [ ] স্বাধীন call সমান্তরাল করা, সীমাবদ্ধ concurrency সহ
- [ ] Payload compress করা; response শুধু দরকারি field দেয়; সবকিছু paginate করা
- [ ] বাস্তবসম্মত data আর access-ধরন সহ production-সদৃশ পরিবেশে load test
- [ ] যে কোনো বড় launch-এর আগে soak test চালানো
- [ ] ব্যর্থতার রূপ জানতে আর graceful degradation নিশ্চিত করতে stress test চালানো
- [ ] Load টুল coordinated omission সংশোধন করে
- [ ] CI-তে performance budget বলবৎ
- [ ] Production-এ সপ্তাহে-সপ্তাহে p95 regression-এ alert
- [ ] Frontend: Core Web Vitals মাপা; অনুভূত-performance-এর কৌশল ব্যবহৃত

---

## ২০.১২ নিজেকে যাচাই

১. Response time = queue time + service time। এই পার্থক্যটা সমাধান কেন বদলে দেয়?
২. Amdahl's Law বলুন আর ১০০০ ms-এর উদাহরণটা কষে দেখান।
৩. USE পদ্ধতি কী? Saturation কেন utilisation-এর চেয়ে ভালো সংকেত?
৪. ধীর web request-এর শীর্ষ পাঁচটা কারণ ক্রমে বলুন। এদের মধ্যে মিল কী?
৫. CPU-নির্ভর, I/O-নির্ভর, memory-নির্ভর — প্রতিটার জন্য সঠিক কৌশল কীভাবে আলাদা?
৬. I/O-নির্ভর কাজে thread যোগ করা সাহায্য করে কিন্তু CPU-নির্ভরে ক্ষতি করে কেন?
৭. Coordinated omission কী আর এটা কেন বেশিরভাগ load test ফলাফল অকেজো করে?
৮. কোন load test-এর ধরন memory leak ধরে, আর অন্যরা কেন মিস করে?
৯. একটা অর্থবহ load test-এর ছয়টা নিয়ম বলুন।
১০. বড় connection pool ভালো নয় কেন? কোন metric বলে আকারটা ঠিক আছে?
১১. একটা query-সংখ্যার বাজেট test কেন সবচেয়ে বেশি মূল্যের performance regression test?
১২. কখন আপনার optimise করা উচিত নয়? পাঁচটা শর্ত দিন।
১৩. কোন performance সিদ্ধান্তগুলো আগেভাগে নিতে হবে কারণ পরে বদলানো ব্যয়বহুল?
১৪. একটা progress bar সহ ৩ সেকেন্ডের operation একটা জমে যাওয়া ২ সেকেন্ডের চেয়ে ভালো কেন?
১৫. "তালিকার পাতা ধীর" — অভিযোগ থেকে প্রতিরোধ পর্যন্ত একটা পূর্ণ তদন্ত হেঁটে দেখান।

---

## ২০.১৩ মূল কথাগুলো

- **আগে মাপুন। বাধা নিয়ে আপনি ভুল হবেন** — সবাই হয়।
- **Amdahl's Law:** একটা অ-বাধা optimise করা পাটিগণিতের দিক থেকেই বৃথা
- **বেশিরভাগ ধীরগতি queue time, service time নয়** — অপেক্ষা, হিসাব নয়
- **শীর্ষ দশের নয়টাই I/O আর data-তে প্রবেশ**, algorithm নয়
- **সেরা optimisation হলো কম কাজ করা**: কম query, কম round trip, ছোট payload, request-এর পথে কম কিছু
- **Batch, সমান্তরাল, cache, আর request-এর পথ থেকে কাজ সরান** — সাধারণ প্রতিদানের এই ক্রমে
- আসল data-পরিমাণ আর আসল concurrency সহ **production profile করুন**
- **Soak test যা ছোট test পারে না তা খুঁজে পায়** — leak, শেষ হয়ে যাওয়া, ধীর ক্ষয়
- **Coordinated omission বেশিরভাগ load test ফলাফলকে** মাত্রার এক ধাপ ভুল করে
- **CI-তে query-সংখ্যার বাজেট** অস্তিত্বশীল সবচেয়ে সাধারণ regression ঠেকায়
- **যা ইতিমধ্যেই চাহিদা মেটায় তা optimise করবেন না** — তবে ব্যয়বহুল-পরিবর্তনের জিনিসগুলো আগেভাগেই ঠিকভাবে design করুন
- যিনি ব্যবহার করছেন তাঁর কাছে **অনুভূত performance-ই আসল performance**

---

**পরবর্তী:** [অধ্যায় ২১ — Testing Architecture](21-testing-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 20](../20-performance-engineering.md) · **[সূচিপত্র](README.md)**
