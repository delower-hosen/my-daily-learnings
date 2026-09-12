# অধ্যায় ০৮ — API Architecture 🟢

> একটা API হলো **অচেনা মানুষদের কাছে করা একটা প্রতিশ্রুতি**।
> একবার প্রকাশ করলে আপনি সেটা ফিরিয়ে নিতে পারবেন না, কে এর উপর নির্ভর করছে দেখতে পারবেন না, আর এর প্রতিটা ভুল স্থায়ী।
>
> এই কারণেই API design একটা architecture, implementation-এর খুঁটিনাটি নয়।

---

# পর্ব ১ — REST

## ৮.১ REST আসলে কী

REST (Representational State Transfer) হলো Roy Fielding-এর ২০০০ সালের গবেষণাপত্র থেকে আসা একটা architectural style। বেশিরভাগ "REST API" আসলে **HTTP JSON API**, যেটা ঠিক আছে — তবে পার্থক্যটা জানুন, কারণ মূল্যটা constraint গুলোর মধ্যেই।

### ছয়টা constraint

| Constraint | মানে | Architecture-এর দিক থেকে কেন গুরুত্বপূর্ণ |
|-----------|---------|-------------------------------|
| **Client–Server** | আলাদা দায়িত্ব | Client আর server স্বাধীনভাবে বিকশিত হয় |
| **Stateless** | প্রতিটা request-এ যা যা লাগে সব থাকে | **এটাই horizontal scaling সম্ভব করে** |
| **Cacheable** | Response বলে দেয় সেটা cache করা যাবে কিনা | বিশাল performance-এর লিভার (CDN, browser, proxy) |
| **Uniform interface** | Resource, প্রচলিত method, স্ব-বর্ণনামূলক message | কোনো custom SDK ছাড়াই যে কেউ ব্যবহার করতে পারে |
| **Layered system** | Client বুঝতে পারে না সে origin-এর সাথে কথা বলছে কিনা | আপনাকে অবাধে gateway, cache, load balancer বসাতে দেয় |
| **Code on demand** (ঐচ্ছিক) | Server চালানোর যোগ্য কোড পাঠাতে পারে | খুব কমই ব্যবহৃত |

> যে দুটো আসলে ভাড়া দেয়: **stateless** (scaling) আর **cacheable** (performance)। আপনার "REST API" যদি server-এ session state রাখে আর সবকিছুতে `Cache-Control: no-store` বসায়, তাহলে আপনি দুটো সুবিধাই ফেলে দিয়েছেন।

## ৮.২ Resource আর URL

**Resource হলো বিশেষ্য। Method হলো ক্রিয়া। URL বলে *কী*, method বলে *কী করতে হবে*।**

```
✅ ভালো                              ❌ খারাপ
GET    /verification-sessions        GET  /getAllSessions
POST   /verification-sessions        POST /createSession
GET    /verification-sessions/{id}   GET  /getSessionById?id=5
PATCH  /verification-sessions/{id}   POST /updateSession
DELETE /verification-sessions/{id}   POST /deleteSession
GET    /customers/{id}/sessions      GET  /getSessionsForCustomer?cid=5
```

### URL design-এর নিয়ম

```
✅ Collection-এর জন্য বহুবচন বিশেষ্য     /customers  , /customer নয়
✅ ছোট হাতের অক্ষর, হাইফেন দিয়ে আলাদা     /verification-sessions  , /VerificationSessions নয়
✅ মালিকানা দেখাতে nest করুন              /customers/{id}/sessions
✅ ২ স্তরে nesting থামান                  /customers/{id}/sessions/{sid}/attempts  ← খুব গভীর
                                        → বরং /sessions/{sid}/attempts
✅ Filter/sort-এর জন্য query param       /sessions?status=pending&sort=-created_at
✅ Path বা header-এ version              /v1/sessions
❌ Path-এ কোনো ক্রিয়া নয়
❌ কোনো file extension নয়                /sessions.json  → Accept header ব্যবহার করুন
❌ Trailing slash-এ অসঙ্গতি নয়            একটা বাছুন আর অন্যটা redirect করুন
```

### যে কাজগুলো CRUD নয়

বাস্তব সিস্টেমে এমন operation থাকে যেগুলো "একটা জিনিস তৈরি/হালনাগাদ/মুছে ফেলা" নয়: approve, cancel, retry, publish, send।

তিনটা গ্রহণযোগ্য পদ্ধতি:

```
১. STATE পরিবর্তন হিসেবে SUB-RESOURCE (সবচেয়ে RESTful)
   PUT /sessions/{id}/status        { "status": "approved" }

২. ACTION SUB-RESOURCE (বাস্তববাদী, ব্যাপকভাবে ব্যবহৃত — Stripe, GitHub এটা করে)
   POST /sessions/{id}/approve      { "reviewer_id": "...", "note": "..." }
   POST /invoices/{id}/void
   POST /payments/{id}/refund

৩. কাজটাকেই প্রতিনিধিত্ব করে এমন একটা RESOURCE তৈরি করুন (সবচেয়ে শক্তিশালী)
   POST /refunds                    { "payment_id": "...", "amount": 500 }
   → refund-টা এখন নিজের ID, status আর ইতিহাস সহ একটা প্রথম-শ্রেণির জিনিস
```

> **বিকল্প ৩ প্রায়ই সেরা উত্তর আর মানুষ এটা বাদ দিয়ে যায়।** কাজটা যদি fail করতে পারে, retry হতে পারে, audit হতে পারে, বা সময় নিতে পারে, তাহলে সেটা একটা resource-ই। "একটা refund" একটা জিনিস, ক্রিয়া নয়।

## ৮.৩ HTTP method

| Method | উদ্দেশ্য | নিরাপদ | Idempotent | Request body | Response |
|--------|---------|------|-----------|--------------|----------|
| **GET** | পড়া | ✅ | ✅ | না | ২০০ + representation |
| **HEAD** | শুধু header পড়া | ✅ | ✅ | না | ২০০, কোনো body নেই |
| **POST** | তৈরি / non-idempotent কাজ | ❌ | ❌ | হ্যাঁ | ২০১ + `Location`, বা ২০০/২০২ |
| **PUT** | পুরোপুরি প্রতিস্থাপন | ❌ | ✅ | হ্যাঁ (পূর্ণ) | ২০০/২০৪ |
| **PATCH** | আংশিক হালনাগাদ | ❌ | ❌* | হ্যাঁ (আংশিক) | ২০০/২০৪ |
| **DELETE** | সরানো | ❌ | ✅ | না | ২০৪, বা body সহ ২০০ |
| **OPTIONS** | ক্ষমতা জানা | ✅ | ✅ | না | ২০০ + `Allow` |

**PUT বনাম PATCH — ব্যবহারিক পার্থক্য:**

```http
PUT /customers/42
{ "name": "Delower", "email": "d@x.com", "tier": "gold" }
→ পুরো resource প্রতিস্থাপন করে। বাদ দেওয়া field গুলো সরে যায়/null হয়।

PATCH /customers/42
{ "tier": "platinum" }
→ শুধু `tier` বদলায়। বাকি সব অক্ষত।
```

**PUT-এর ফাঁদ:** যে client GET করে, একটা field বদলায়, আর PUT করে ফেরত পাঠায় — সেটা নীরবে এমন যে কোনো field মুছে দেবে যা একটা নতুন API সংস্করণ যোগ করেছে কিন্তু ওই client জানে না। এটা একটা বাস্তব আর সাধারণ bug। **হালনাগাদের জন্য PATCH-কে প্রাধান্য দিন।**

PATCH-এর জন্য একটা ফরম্যাট বাছুন আর নথিভুক্ত করুন: সাধারণ "merge" JSON (সবচেয়ে প্রচলিত), অথবা standard গুলো — **JSON Merge Patch** (RFC 7386, `null` মানে মুছে ফেলা) বা **JSON Patch** (RFC 6902, operation-এর একটা array, array পরিবর্তন সাপোর্ট করে)।

## ৮.৪ Status code — ঠিকভাবে ব্যবহার করুন

### 2xx — সাফল্য

| Code | কখন |
|------|------|
| **200 OK** | একটা body সহ সাফল্য |
| **201 Created** | Resource তৈরি হয়েছে — **সবসময় একটা `Location` header দিন** |
| **202 Accepted** | Async প্রক্রিয়াকরণের জন্য গৃহীত — একটা status URL ফেরত দিন |
| **204 No Content** | সাফল্য, ফেরত দেওয়ার কিছু নেই (DELETE, কিছু PUT) |
| **206 Partial Content** | Range request (ভিডিও, বড় ফাইল) |

### 3xx — redirection

| Code | কখন |
|------|------|
| **301 Moved Permanently** | Resource-এর একটা নতুন স্থায়ী URL আছে (client জোরালোভাবে cache করে) |
| **302 Found** / **307** | অস্থায়ী redirect (৩০৭ method অক্ষত রাখে; ৩০২ ঐতিহাসিকভাবে রাখত না) |
| **304 Not Modified** | Conditional GET — **client-এর cache এখনো বৈধ। এটা বিশাল bandwidth বাঁচায়।** |

### 4xx — client-এর ভুল

| Code | কখন | সাধারণ ভুল |
|------|------|----------------|
| **400 Bad Request** | বিকৃত syntax / অবৈধ request | সবকিছুর জন্য ঢালাওভাবে ব্যবহার করা |
| **401 Unauthorized** | **Authenticate হয়নি** (spec-এ নামটা ভুল) | ৪০৩-এর সাথে গুলিয়ে ফেলা |
| **403 Forbidden** | Authenticate হয়েছে, কিন্তু **অনুমতি নেই** | ৪০১-এর সাথে গুলিয়ে ফেলা |
| **404 Not Found** | অস্তিত্ব নেই — বা আপনি ইচ্ছাকৃতভাবে অস্তিত্ব লুকাচ্ছেন | |
| **405 Method Not Allowed** | একটা বৈধ URL-এ ভুল ক্রিয়া | একটা `Allow` header দিতেই হবে |
| **409 Conflict** | State-এর সংঘর্ষ (duplicate, একসাথে সম্পাদনা) | |
| **410 Gone** | ছিল, স্থায়ীভাবে সরানো হয়েছে | কম ব্যবহৃত — deprecation-এর জন্য ৪০৪-এর চেয়ে ভালো |
| **412 Precondition Failed** | `If-Match` মেলেনি — optimistic locking | |
| **415 Unsupported Media Type** | ভুল `Content-Type` | |
| **422 Unprocessable Entity** | Syntax ঠিক, **অর্থ অবৈধ** (validation-এর ভুল) | |
| **429 Too Many Requests** | Rate limit — **`Retry-After` দিতেই হবে** | |

> **৪০১ বনাম ৪০৩, মুখস্থ করুন:** ৪০১ = "**আপনি কে?**" (credential নেই বা খারাপ)। ৪০৩ = "**আমি জানি আপনি কে, আর না।**"
>
> **৪০০ বনাম ৪২২:** ৪০০ = আমি এটা parse করতে পারছি না। ৪২২ = আমি parse করেছি, আর "age: -5" একটা বৈধ বয়স নয়।

### 5xx — server-এর ভুল

| Code | কখন |
|------|------|
| **500 Internal Server Error** | সামলানো হয়নি এমন ব্যর্থতা — **কখনো একটা stack trace ফাঁস করবেন না** |
| **502 Bad Gateway** | উপরের দিক আবর্জনা ফেরত দিয়েছে |
| **503 Service Unavailable** | অতিরিক্ত চাপ/রক্ষণাবেক্ষণ — **`Retry-After` দিন** |
| **504 Gateway Timeout** | উপরের দিক সময়মতো উত্তর দেয়নি |

> **মহাপাপ:** `HTTP 200 { "success": false, "error": "not found" }`। এখন প্রতিটা cache, proxy, monitor আর client library ভাবছে সবকিছু ঠিক আছে। আপনার error-rate dashboard ০% দেখাচ্ছে। **Status code ব্যবহার করুন।**

## ৮.৫ Error response — RFC 9457 (Problem Details) ব্যবহার করুন

নিজের error ফরম্যাট বানানো বন্ধ করুন। একটা standard আছে।

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json

{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Your request parameters didn't validate.",
  "status": 422,
  "detail": "The 'video' field exceeds the maximum size of 10 MB.",
  "instance": "/v1/verification-sessions/ses_8812/attempts",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": [
    { "field": "video",       "code": "max_size_exceeded", "message": "Maximum 10 MB, received 14.2 MB" },
    { "field": "challenge_id","code": "required",          "message": "This field is required" }
  ]
}
```

**ভালো error-এর নিয়ম:**
১. **মেশিনের পড়ার যোগ্য code** (`max_size_exceeded`) — client এটার উপর শাখা করে, কখনো message-এর লেখার উপর নয়
২. **মানুষের পড়ার যোগ্য message** — যে ডেভেলপার log পড়ছেন তাঁর জন্য
৩. Validation-এর জন্য **field-স্তরের বিবরণ** — প্রথমটা নয়, **সব** error ফেরত দিন
৪. **একটা trace ID** — যাতে একজন customer বলতে পারেন "এটা fail করেছে, এই যে ID" আর আপনি সাথে সাথে খুঁজে পান
৫. **কখনো ভেতরের জিনিস ফাঁস করবেন না** — কোনো stack trace নয়, SQL নয়, ভেতরের hostname নয়, একটা signup ফর্মে "এই ইমেইলে একজন ব্যবহারকারী আছেন" নয় (সেটা account enumeration)

## ৮.৬ Pagination 🟢

কখনো একটা সীমাহীন তালিকা ফেরত দেবেন না। কখনোই না। যেদিন একজন customer-এর ৪০ লাখ record থাকবে, সেদিন আপনার API আপনার database নামিয়ে দেবে।

### Offset pagination (সহজ, আর scale-এ নীরবে ভাঙা)

```http
GET /sessions?page=3&limit=50
```

```sql
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 50 OFFSET 100;
```

| ✅ | ❌ |
|---|---|
| যে কোনো পাতায় লাফ দেওয়া | **গভীরে ধীর** — `OFFSET 500000` DB-কে ৫,০০,০০০ row scan করে ফেলে দিতে বাধ্য করে |
| মোট পাতার সংখ্যা দেখানো | **আইটেম সরে যায়** — paging-এর মাঝে একটা নতুন row এলে → আপনি একটা আইটেম দুইবার দেখেন বা একটা বাদ পড়ে |

### Cursor / keyset pagination ⭐ (যেটা আপনার ব্যবহার করা উচিত)

```http
GET /sessions?limit=50
GET /sessions?limit=50&cursor=eyJpZCI6IjAxSjhYIiwidHMiOiIyMDI2LTA5LTEyIn0
```

```sql
-- Cursor শেষ row-র sort-এর মানগুলো encode করে
SELECT * FROM sessions
WHERE (created_at, id) < ($1, $2)     -- যৌগিক tiebreaker: স্থিতিশীল ও অনন্য
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

| ✅ | ❌ |
|---|---|
| **যে কোনো গভীরতায় ধ্রুব সময়** (এটা একটা index seek) | ৪৭ নম্বর পাতায় লাফ দেওয়া যায় না |
| একসাথে insert হলেও **স্থিতিশীল** | মোট সংখ্যা ব্যয়বহুল/বাদ দেওয়া হয় |
| Infinite scroll-এ কাজ করে | Sort-এর field নির্দিষ্ট আর indexed হতে হবে |

```json
{
  "data": [ ... ],
  "pagination": {
    "next_cursor": "eyJpZCI6...",
    "has_more": true,
    "limit": 50
  }
}
```

> **নিয়ম:** ছোট admin table-এর জন্য offset pagination, যেখানে ব্যবহারকারীরা পাতার নম্বর চান; **ব্যবহারকারী-মুখী বা বড় সবকিছুর জন্য cursor pagination।** সবসময় `limit` সীমাবদ্ধ করুন (যেমন সর্বোচ্চ ১০০) — নইলে `?limit=1000000` একটা বিনামূল্যের denial-of-service।

## ৮.৭ Filter, sort, field নির্বাচন

```http
GET /sessions?status=pending&created_after=2026-09-01&sort=-created_at,id&fields=id,status,score
```

| Feature | প্রথা |
|---------|-----------|
| Filter | `?status=pending` (হুবহু), `?score_gte=0.8` (তুলনা), `?status=a,b` (এর মধ্যে) |
| Sort | `?sort=-created_at,name` (`-` = অবরোহী, কমা = একাধিক) |
| Sparse field | `?fields=id,status` — mobile-এ bandwidth বাঁচায় |
| Expand | `?expand=customer` — একটা সম্পর্কিত resource ঢোকায়, একটা round trip বাঁচায় |
| Search | `?q=delower` — full-text |

**নিরাপত্তার সতর্কবার্তা:**
- Filter আর sort করা যায় এমন field গুলো **whitelist** করুন। কখনো একটা `ORDER BY`-তে বা একটা query builder-এ যাচাই ছাড়া ব্যবহারকারীর input পাঠাবেন না — এটা একসাথে SQL injection আর একটা performance DoS।
- Filter করা যায় এমন প্রতিটা field-এর একটা **index** থাকতে হবে, নইলে একটা filter একটা table scan হয়ে যায়
- `expand`-এর গভীরতা সীমাবদ্ধ করুন — সীমাহীন expansion হলো GraphQL-এর টুল ছাড়া GraphQL-এর N+1 সমস্যা

## ৮.৮ HTTP-তে idempotency আর concurrency

### Idempotency key (অধ্যায় ০৫, প্রয়োগ করা)

```http
POST /v1/charges
Idempotency-Key: 8f14e45f-ea2a-4f0e-b1d6-2c8e3f1a9b7d
```

**যে কোনো POST যেটা টাকা নাড়ায় বা ব্যয়বহুল কিছু তৈরি করে, তার জন্য বাধ্যতামূলক।** এটা নথিভুক্ত করুন আর বলবৎ করুন।

### ETag দিয়ে optimistic concurrency ⭐

Lock ধরে না রেখেই হারিয়ে যাওয়া update ঠেকান।

```http
GET /customers/42
→ 200 OK
  ETag: "a3f5c8e2"
  { "name": "Delower", "tier": "gold" }

PATCH /customers/42
If-Match: "a3f5c8e2"
{ "tier": "platinum" }

→ 200 OK        (আর কেউ এটা বদলায়নি)
→ 412 Precondition Failed   (কেউ বদলেছে — client-কে আবার আনতে আর retry করতে হবে)
```

এটা ছাড়া দুজন admin একই record সম্পাদনা করে নীরবে একে অপরের কাজ মুছে দেন। **এটা দুই লাইনের একটা পরিবর্তন যা আস্ত একটা শ্রেণির data-হারানোর bug ঠেকায়।**

### Conditional GET (বিনামূল্যে bandwidth সাশ্রয়)

```http
GET /sessions/ses_881
If-None-Match: "a3f5c8e2"

→ 304 Not Modified        (কোনো body নেই — byte বাঁচল, DB query হয়তো এড়ানো গেল)
```

`Last-Modified` / `If-Modified-Since` দিয়েও কাজ করে।

## ৮.৯ Caching header 🟢

```http
Cache-Control: public, max-age=3600, stale-while-revalidate=60
Cache-Control: private, max-age=0, must-revalidate
Cache-Control: no-store                      # কখনো cache নয় (PII, আর্থিক)
ETag: "a3f5c8e2"
Vary: Accept-Encoding, Authorization
```

| Directive | মানে |
|-----------|---------|
| `public` | যে কোনো cache (CDN, proxy) এটা রাখতে পারে |
| `private` | শুধু browser — **ব্যবহারকারী-নির্দিষ্ট যে কোনো কিছুর জন্য ব্যবহার করুন** |
| `no-store` | কখনো কোথাও লিখবেন না — গোপন তথ্য আর PII-র জন্য |
| `no-cache` | রাখুন, কিন্তু প্রতিবার ব্যবহারের আগে যাচাই করুন (নামটা বিভ্রান্তিকর) |
| `max-age=N` | N সেকেন্ডের জন্য তাজা |
| `s-maxage=N` | Shared cache-এর (CDN) জন্য `max-age` ছাপিয়ে যায় |
| `stale-while-revalidate=N` | পেছনে refresh করতে করতে N সেকেন্ড পুরনোটা পরিবেশন করুন — **অনুভূত latency-র জন্য চমৎকার** |
| `immutable` | কখনো যাচাই করবেন না (version করা static asset) |

> **`Vary: Authorization` একটা নিরাপত্তা-গুরুত্বপূর্ণ header।** এটা ছাড়া একটা shared cache ব্যবহারকারী A-র ব্যক্তিগত response ব্যবহারকারী B-কে দিতে পারে। এতে সত্যিকারের breach ঘটেছে।

## ৮.১০ API versioning 🟢

আপনার এটা লাগবেই। v1 ship করার আগেই ঠিক করুন।

| কৌশল | উদাহরণ | সুবিধা | অসুবিধা |
|----------|---------|------|------|
| **URL path** ⭐ | `/v1/sessions` | স্পষ্ট, route করা সহজ, browser-এ test করা সহজ | "RESTful নয়" (resource তো বদলায়নি); version ছড়িয়ে পড়ে |
| **Header** | `Accept: application/vnd.api.v2+json` | পরিষ্কার URL, content negotiation | অদৃশ্য, test করা কঠিন, cache-কে `Vary` করতে হয় |
| **Query param** | `/sessions?version=2` | সহজ | ভুলে যাওয়া সহজ; caching এলোমেলো |
| **তারিখ-ভিত্তিক** | `Stripe-Version: 2026-09-12` | খুবই সূক্ষ্ম, প্রতি-customer pinning | Implement করা জটিল (Stripe রূপান্তরের স্তর রক্ষণাবেক্ষণ করে) |

> **সুপারিশ: major version-এর জন্য URL path versioning (`/v1/`)।** এটাই সবচেয়ে বাস্তববাদী। নিচের নিয়মটার সাথে মেলান, যাতে আপনার প্রায় কখনোই v2 লাগে না।

### অনেক বেশি গুরুত্বপূর্ণ নিয়ম: **যোগ করে** version করুন

```
✅ ভাঙে না (নতুন version লাগে না)
   - response-এ একটা নতুন optional field যোগ করা      (client-কে অজানা field উপেক্ষা করতে হবে)
   - একটা নতুন optional request parameter যোগ করা
   - একটা নতুন endpoint যোগ করা
   - একটা নতুন enum মান যোগ করা        ← শুধু যদি client অজানা মান সামলায়; নথিভুক্ত করুন
   - একটা validation নিয়ম শিথিল করা

❌ ভাঙে (একটা নতুন version লাগবে)
   - একটা field সরানো বা নাম বদলানো
   - একটা field-এর type বা ফরম্যাট বদলানো
   - একটা optional parameter-কে required করা
   - default আচরণ বদলানো
   - একটা field-এর অর্থ বদলানো (নীরব ঘাতক)
   - একটা endpoint বা একটা enum মান সরানো
   - একটা নতুন required error শর্ত যোগ করা
```

**Tolerant Reader** হলো সেই contract যা আপনি client-দের মানতে বলেন: *যে field চেনেন না সেগুলো উপেক্ষা করুন; বাড়তি data-তে fail করবেন না।* এটা প্রকাশ করুন। তারপর আপনি v2 ছাড়াই চিরকাল field যোগ করতে পারবেন।

### Deprecation, পেশাদারভাবে

```http
Deprecation: Sun, 01 Mar 2026 00:00:00 GMT
Sunset: Wed, 01 Sep 2026 00:00:00 GMT
Link: <https://api.example.com/docs/migrating-to-v2>; rel="deprecation"
Warning: 299 - "v1 will be removed on 2026-09-01. See the migration guide."
```

সাথে: কে এখনো এটা call করে মাপুন (প্রতি-client metric), তাঁদের ইমেইল করুন, আর **কে ভাঙবে ঠিক করে না জেনে কখনো একটা version সরাবেন না।**

## ৮.১১ HATEOAS ⚪

Richardson-এর maturity model-এর "Level 3": response-এ পরবর্তীতে কী করতে পারেন তার লিংক থাকে।

```json
{
  "id": "ses_881",
  "status": "pending_review",
  "_links": {
    "self":    { "href": "/v1/sessions/ses_881" },
    "approve": { "href": "/v1/sessions/ses_881/approve", "method": "POST" },
    "reject":  { "href": "/v1/sessions/ses_881/reject",  "method": "POST" }
  }
}
```

**তত্ত্ব:** client গতিশীলভাবে ক্ষমতা আবিষ্কার করে; server অবাধে URL বদলাতে পারে; উপলব্ধ কাজগুলো বর্তমান state প্রতিফলিত করে।

**বাস্তবতা:** প্রায় কেউই আসল HATEOAS implement করে না, আর প্রায় কোনো client গতিশীলভাবে এটা ব্যবহার করে না। **পরিচিতিই যথেষ্ট।** সত্যিকারের কাজের একটা অংশ হলো *state-নির্ভর action link* — client-কে আপনার state machine আবার লিখতে হয় না জানার জন্য যে "approve" এখন অনুমোদিত কিনা।

---

# পর্ব ২ — অন্যান্য API style

## ৮.১২ gRPC 🟡

**এটা কী:** Google-এর RPC framework — HTTP/2-র উপর Protobuf contract, generate করা client আর server সহ।

```protobuf
syntax = "proto3";
package verification.v1;

service VerificationService {
  rpc StartSession   (StartSessionRequest)   returns (Session);
  rpc SubmitVideo    (stream VideoChunk)     returns (VerificationResult);  // client streaming
  rpc WatchSession   (WatchRequest)          returns (stream SessionEvent); // server streaming
}

message StartSessionRequest {
  string customer_id = 1;
  RiskLevel risk_level = 2;
}

message Session {
  string id = 1;
  SessionStatus status = 2;
  google.protobuf.Timestamp expires_at = 3;
}
```

| ✅ শক্তি | ❌ দুর্বলতা |
|-------------|---------------|
| **দ্রুত** — binary, ছোট, HTTP/2-র multiplexing | **Browser-এর নিজস্ব নয়** (gRPC-Web + একটা proxy লাগে) |
| **দৃঢ়ভাবে type করা contract**, ১১+ ভাষায় generate করা কোড | **মানুষের পড়ার যোগ্য নয়** — সহজে curl করা যায় না |
| দুই দিকেই **streaming**, অন্তর্নির্মিত | তারে debug আর পরিদর্শন করা কঠিন |
| অন্তর্নির্মিত deadline, cancellation, retry, load-balancing | পুরো পথে HTTP/2 লাগে (কিছু পুরনো proxy আটকে যায়) |
| উচ্চ-volume-এর ভেতরের traffic-এর জন্য চমৎকার | আরও টুল আর build-pipeline-এর সেটআপ |

> **ভেতরের service-থেকে-service যোগাযোগের জন্য gRPC ব্যবহার করুন**, বিশেষত উচ্চ-volume বা streaming-এ। **Public আর browser-মুখী API-র জন্য REST/JSON ব্যবহার করুন।** অনেক কোম্পানি ঠিক এটাই করে: ভেতরে gRPC, প্রান্তে REST, আর gateway অনুবাদ করে।

**Protobuf-এর field নম্বরই contract।** কখনো একটা নম্বর পুনর্ব্যবহার করবেন না, কখনো একটা field-এর নম্বর বদলাবেন না, আর সরানো field গুলো `reserved` চিহ্নিত করুন। এটা ভুল করলে নীরবে data নষ্ট হয়।

## ৮.১৩ GraphQL 🟡

**যে সমস্যার সমাধান করে:** REST endpoint নির্দিষ্ট আকৃতি ফেরত দেয়। একটা mobile screen-এ ৫টা endpoint থেকে data লাগে (**under-fetching** → ৫টা round trip), আর প্রতিটা ৪০টা field ফেরত দেয় যখন screen-এ ৪টা লাগে (**over-fetching** → নষ্ট bandwidth)।

```graphql
query SessionDashboard($id: ID!) {
  session(id: $id) {
    id
    status
    score
    customer {              # এটা একটা দ্বিতীয় REST call হতো
      name
      tier
    }
    attempts(last: 3) {     # আর একটা তৃতীয়
      number
      passed
      signals { livenessScore spoofDetected }
    }
  }
}
```

একটা request। ঠিক যতগুলো field দরকার। Client আকৃতি নিয়ন্ত্রণ করে।

| ✅ শক্তি | ❌ দুর্বলতা |
|-------------|---------------|
| Client ঠিক যা লাগে তাই পায়, এক round trip-এ | **Caching কঠিন** — সবকিছু `POST /graphql`, তাই HTTP caching খাটে না |
| দৃঢ়ভাবে type করা, স্ব-নথিভুক্ত, দারুণ টুল | **N+1 query** default ব্যর্থতার রূপ (DataLoader batching লাগে) |
| একটা endpoint অনেক client-আকৃতিকে সেবা দেয় | **Query-জটিলতার আক্রমণ** — একটা গভীরভাবে nested query আপনার DB গলিয়ে দিতে পারে |
| বিভিন্ন screen সহ mobile-এর জন্য চমৎকার | "request" দিয়ে rate limiting অর্থহীন; আপনার cost বিশ্লেষণ লাগবে |
| Version ছাড়াই schema evolution (field deprecate করুন) | File upload আর error-এর জন্য বাড়তি প্রথা লাগে |
| Federation অনেক service-কে একটা graph-এ জোড়ে | সত্যিকারের operational জটিলতা; বিনামূল্যের খাবার নয় |

**আপনি production-এ GraphQL চালালে যে উপশমগুলো আপসহীন:**

```javascript
// ১. DataLoader — batch আর dedupe করুন, নইলে আপনার N+1 হবেই
const customerLoader = new DataLoader(async (ids) =>
  db.customers.findMany({ where: { id: { in: ids } } })
);

// ২. গভীরতা + জটিলতার সীমা
validationRules: [depthLimit(7), costAnalysis({ maximumCost: 1000 })]

// ৩. Persisted query — production-এ শুধু আগে থেকে register করা query চলতে দিন
//    (যথেচ্ছ-query আক্রমণ মারে, আর GET + CDN caching সম্ভব করে)
```

> **GraphQL কখন জেতে:** আলাদা আলাদা data-চাহিদা সহ অনেক ভিন্ন client (web + iOS + Android + partner), একটা সমৃদ্ধ পরস্পর-সংযুক্ত domain, আর এটা চালানোর আগ্রহ আছে এমন একটা টিম।
> **কখন হারে:** একটা সাধারণ CRUD service, একটামাত্র client, একটা ছোট টিম, বা যখন HTTP caching-ই আপনার প্রধান performance কৌশল।

## ৮.১৪ WebSocket 🟡

**Full-duplex, স্থায়ী, দ্বিমুখী connection।**

```
Client ──── HTTP Upgrade ────► Server
       ◄─── 101 Switching Protocols ───
       ◄══════ স্থায়ী, দুই দিকেই ══════►
```

**কীসের জন্য:** chat, সহযোগিতামূলক সম্পাদনা, live dashboard, multiplayer, trading ticker — যেখানে **client-ও ঘন ঘন পাঠায়** এমন যে কোনো কিছু।

**Architecture-এর যে ফলাফলগুলোর জন্য আপনাকে পরিকল্পনা করতেই হবে:**

১. **Connection stateful** — এটা "stateless server"-এর নিয়ম ভাঙে। আপনার sticky routing বা একটা shared backplane (Redis pub/sub) লাগবে, যাতে যে কোনো server যে কোনো যুক্ত client-এর কাছে পৌঁছাতে পারে।
২. **Deploy connection ফেলে দেয়** — client-দের backoff সহ স্বয়ংক্রিয় পুনঃসংযোগ **আর** state পুনঃসমন্বয় লাগবে (offline থাকাকালীন তারা message মিস করেছে)
৩. **Connection-এর সীমা** — প্রতিটা connection memory আর একটা file descriptor ধরে রাখে; stack অনুযায়ী প্রতি node-এ ~১০ হাজার–১ লাখ
৪. **Load balancer-এ WebSocket সাপোর্ট** আর লম্বা idle timeout লাগবে
৫. **কোনো HTTP caching নেই, কোনো প্রচলিত status code নেই** — আপনি উপরে নিজের protocol design করছেন
৬. **Auth** — browser-এর WebSocket API header বসাতে পারে না, তাই query string-এ token (সব জায়গায় log হয়!) বা connect-পরবর্তী একটা auth message। এটা ইচ্ছাকৃতভাবে design করুন।

## ৮.১৫ Server-Sent Events (SSE) — কম মূল্যায়িত বিকল্প ⭐

**একমুখী, server → client, সাধারণ HTTP-র উপর।**

```http
GET /sessions/ses_881/events
Accept: text/event-stream

HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache

event: status
data: {"status":"processing","progress":30}

event: status
data: {"status":"processing","progress":75}

event: result
data: {"status":"passed","score":0.94}
```

```javascript
const es = new EventSource('/sessions/ses_881/events');
es.addEventListener('result', e => render(JSON.parse(e.data)));
// Last-Event-ID সহ স্বয়ংক্রিয় পুনঃসংযোগ অন্তর্নির্মিত
```

| SSE বনাম WebSocket | SSE | WebSocket |
|---|---|---|
| দিক | শুধু server → client | দুই দিকেই |
| Protocol | সাধারণ HTTP | ws://-এ upgrade |
| স্বয়ংক্রিয় পুনঃসংযোগ | **অন্তর্নির্মিত**, `Last-Event-ID` replay সহ | আপনি লেখেন |
| Proxy / firewall | শুধুই HTTP — সব জায়গায় চলে | কখনো কখনো আটকে যায় |
| Compression, auth header, HTTP/2 | সব স্বাভাবিক | সীমিত |
| Browser-এর connection সীমা | HTTP/1.1-এ প্রতি domain-এ ৬ (HTTP/2-তে সমস্যা নেই) | বেশি |

> **আপনার যদি শুধু server→client push লাগে (progress আপডেট, notification, live status), তাহলে SSE ব্যবহার করুন।** এটা WebSocket-এর চেয়ে নাটকীয়ভাবে সহজ আর বেশিরভাগ টিম অভ্যাসবশত WebSocket-এর দিকে হাত বাড়ায়। একটা verification progress feed-এর জন্য SSE-ই সঠিক উত্তর।

## ৮.১৬ Webhook 🟢

**উল্টো API:** কিছু ঘটলে আপনি *তাদের* endpoint call করেন।

```http
POST https://customer.example.com/webhooks/verification
Content-Type: application/json
Webhook-Id: msg_01J8X7...
Webhook-Timestamp: 1757673600
Webhook-Signature: v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=

{ "type": "verification.passed", "data": { "session_id": "ses_881", "score": 0.94 } }
```

### Webhook প্রদানকারীর চেকলিস্ট (সবগুলোই ঠিক করুন)

**১. প্রতিটা payload sign করুন — HMAC, একটা timestamp সহ**

```python
def sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    return base64.b64encode(hmac.new(secret.encode(), signed, hashlib.sha256).digest()).decode()
```

Sign করা বিষয়বস্তুর ভেতরের timestamp-টা **replay আক্রমণ** ঠেকায়। গ্রহীতাদের ~৫ মিনিটের বেশি পুরনো যে কোনো কিছু প্রত্যাখ্যান করতে হবে, আর একটা **constant-time তুলনা** ব্যবহার করতে হবে।

**২. Exponential backoff সহ retry করুন** — আর সময়সূচিটা প্রকাশ করুন

```
চেষ্টা ১: সাথে সাথে
চেষ্টা ২: +৫ সেকেন্ড        চেষ্টা ৫: +৩০ মিনিট
চেষ্টা ৩: +১ মিনিট           চেষ্টা ৬: +২ ঘণ্টা
চেষ্টা ৪: +৫ মিনিট           চেষ্টা ৭: +১২ ঘণ্টা  → তারপর বন্ধ করে তাঁদের ইমেইল করুন
```

**৩. প্রতিটা event-কে একটা স্থিতিশীল ID দিন**, যাতে গ্রহীতারা deduplicate করতে পারেন (delivery at-least-once)

**৪. দ্রুত timeout করুন (৫–১০ সেকেন্ড)** আর গ্রহীতাকে শুধু স্বীকৃতি দিতে বলুন — তাঁদের queue-তে রেখে asynchronously process করা উচিত, request-এর ভেতরে কাজ করা নয়

**৫. একটা dashboard দিন**: delivery-র ইতিহাস, payload, response code, আর একটা **manual replay** বোতাম। শুধু এই একটা feature বেশিরভাগ support ticket সরিয়ে দেয়।

**৬. Payload version করুন** আর customer-দের একটা version-এ আটকে থাকতে দিন

**৭. আপনার egress IP পরিসর প্রকাশ করুন**, যাতে customer-রা allowlist করতে পারেন

### গ্রহীতার চেকলিস্ট

- Body parse করার **আগে** signature যাচাই করুন, **কাঁচা byte** ব্যবহার করে (আবার serialise করলে signature বদলায়)
- **সাথে সাথে ২xx ফেরত দিন**, তারপর একটা queue থেকে process করুন
- Event ID-তে **deduplicate করুন**
- **ক্রমের বাইরে** delivery-র জন্য প্রস্তুত থাকুন (আসার ক্রম নয়, event-এর timestamp/version ব্যবহার করুন)
- Authorisation-এর জন্য payload-এর বিষয়বস্তু কখনো বিশ্বাস করবেন না — গুরুত্বপূর্ণ হলে API থেকে আবার আনুন

> **Webhook বনাম polling:** webhook দক্ষ আর real-time, কিন্তু customer-কে একটা public endpoint চালাতে হয়। **দুটোই দিন।** অনেক enterprise customer ভেতরে আসা traffic নিতে পারেন না, আর একটা polling endpoint (`GET /events?after=cursor`) তাঁদের সেবা দেয় — webhook fail করলে এটাই আপনার fallback।

---

# পর্ব ৩ — API architecture-এর pattern

## ৮.১৭ API Gateway 🟢

আপনার service গুলোর সামনে একটামাত্র প্রবেশপথ।

```
                       ┌──────────────────────────────┐
                       │        API GATEWAY           │
   Client ────────────►│  • TLS termination           │
                       │  • AuthN (JWT যাচাই)          │
                       │  • Rate limiting / quota     │
                       │  • Routing                   │
                       │  • Request/response transform│
                       │  • Caching                   │
                       │  • Logging, metric, tracing  │
                       │  • WAF, IP allowlist         │
                       └────┬─────────┬─────────┬─────┘
                            ▼         ▼         ▼
                        Service A  Service B  Service C
```

**এটা কেন আছে:** এটা ছাড়া প্রতিটা service auth, rate limiting, TLS, logging আর CORS আবার লেখে — আলাদাভাবে, আর কিছু কিছু খারাপভাবে।

**একটা gateway-তে যা থাকা উচিত:**
✅ Authentication (token যাচাই করুন, আগেভাগে প্রত্যাখ্যান করুন)
✅ Rate limiting আর quota
✅ TLS termination
✅ Routing আর path পুনর্লিখন
✅ Request/response logging, metric, trace শুরু করা
✅ CORS, compression, WAF
✅ Public GET-এর জন্য response caching

**যা থাকা উচিত নয়:**
❌ Business logic (এভাবেই SOA-র ESB একটা monolith হয়ে গিয়েছিল — অধ্যায় ০২)
❌ অনেক service জুড়ে data একত্রীকরণ (বরং একটা BFF ব্যবহার করুন)
❌ এমন কিছু যাতে একটা service বদলালেই gateway deploy করতে হয়

**ঝুঁকি:** এটা একটা single point of failure (HA-তে চালান), এটা একটা বাধা হয়ে উঠতে পারে, আর একটা টিমকে প্রতিটা route অনুমোদন করতে হলে এটা একটা *টিম*-এর বাধাও হয়ে উঠতে পারে। প্রতিটা service টিমের মালিকানাধীন declarative, self-service route config-কে প্রাধান্য দিন।

**পণ্য:** Kong, AWS API Gateway, Azure API Management, Apigee, Tyk, Envoy, Traefik, NGINX, Spring Cloud Gateway, YARP।

## ৮.১৮ Backend for Frontend (BFF) ⭐

**সমস্যা:** একটা API একটা web app, একটা iOS app, একটা Android app আর partner integration — সবাইকে সেবা দেওয়ার চেষ্টা করে। প্রতিটা client-এর চাহিদা সংঘর্ষ করে। প্রতিটা পরিবর্তন আরও তিনটা client ভাঙার ঝুঁকি নেয়। শেষে সব জায়গায় `?include=` flag।

**সমাধান:** প্রতি client-ধরনে একটা backend, ওই client-এর টিমের মালিকানায়।

```
   Web App ──────► Web BFF ────┐
   iOS App ──────► Mobile BFF ─┼──► Verification Service
   Partner ──────► Public API ─┤──► Customer Service
                               └──► Billing Service
```

প্রতিটা BFF:
- ওই client-এর **ঠিক যে আকৃতি লাগে** সেটাই ফেরত দেয় (mobile ছোট payload পায়; web আরও সমৃদ্ধ)
- কয়েকটা service call এক round trip-এ একত্র করে (mobile নেটওয়ার্কে গুরুত্বপূর্ণ)
- Client-নির্দিষ্ট auth সামলায় (web-এ cookie, mobile-এ bearer token)
- **Frontend টিমের মালিকানাধীন** — তাঁরা একটা backend ticket ছাড়াই এটা বদলাতে পারেন

> **সাংগঠনিক সুবিধাটাই আসলটা:** frontend টিম backend টিমের জন্য অপেক্ষা করা বন্ধ করে। কারিগরি পরিচ্ছন্নতার চেয়ে এটা বেশি মূল্যবান।

**খরচ:** BFF গুলোর মধ্যে কিছু logic-এর পুনরাবৃত্তি, আরও deployable। BFF গুলো **পাতলা** রাখুন — শুধু orchestration আর আকৃতি দেওয়া, কোনো business rule নয়। Business logic সহ একটা BFF ছদ্মবেশে একটা নতুন monolith।

## ৮.১৯ API Composition / Aggregator

```python
# একটা client call → কয়েকটা backend call, সমান্তরালে
async def get_session_dashboard(session_id: str) -> Dashboard:
    session, customer, history, quota = await asyncio.gather(
        verification_svc.get_session(session_id),
        customer_svc.get(session.customer_id),
        verification_svc.get_history(session.customer_id, limit=5),
        billing_svc.get_quota(session.tenant_id),
        return_exceptions=True,            # আংশিক ব্যর্থতা সহ্য করা
    )
    return Dashboard(
        session=session,
        customer=customer if not isinstance(customer, Exception) else None,
        history=history if not isinstance(history, Exception) else [],
        quota=quota if not isinstance(quota, Exception) else None,
        degraded=[n for n, v in zip(("customer","history","quota"),
                                    (customer, history, quota))
                  if isinstance(v, Exception)],
    )
```

**Design-এর নিয়ম:**
- **সবসময় সমান্তরালে call করুন।** ক্রমিক composition প্রতিটা dependency-র latency যোগ করে।
- **আংশিক ব্যর্থতা সামলান।** Quota widget ছাড়া একটা dashboard ফেরত দেওয়া একটা ৫০০ ফেরত দেওয়ার চেয়ে ভালো।
- **একটা সামগ্রিক deadline বসান** আর পিছিয়ে পড়াগুলো বাতিল করুন
- Client-এর কাছে সৎ থাকুন কী কী নেই সে বিষয়ে (`degraded: [...]`)
- **এটা CQRS-এরও read-দিক** (অধ্যায় ০১)। Composition ধীর বা জটিল হয়ে গেলে প্রতিটা request-এ compose না করে বরং একটা **materialised read model** বানান।

## ৮.২০ API স্তরে rate limiting

(Algorithm গুলো অধ্যায় ০৫-এ। এখানে API-মুখী design।)

**সঠিক মাত্রা দিয়ে সীমিত করুন:**

| মাত্রা | কীসের জন্য |
|-----------|----------|
| **API key / tenant** | B2B API-র প্রাথমিক নিয়ন্ত্রণ |
| **User ID** | একটা tenant-এর ভেতরে প্রতি-ব্যবহারকারী ন্যায্যতা |
| **IP ঠিকানা** | Unauthenticated endpoint (login, signup) — NAT আর mobile carrier নিয়ে সাবধান |
| **Endpoint** | ব্যয়বহুল operation নিজের, কড়া সীমা পায় |
| **খরচ/ওজন** | একটা search-এ ১০ একক, একটা GET-এ ১ — **সবচেয়ে ন্যায্য মডেল** |

**Plan অনুযায়ী স্তরভিত্তিক সীমা:**

```yaml
free:       { requests_per_minute: 60,    burst: 100,   concurrent: 5 }
pro:        { requests_per_minute: 1000,  burst: 2000,  concurrent: 50 }
enterprise: { requests_per_minute: 10000, burst: 20000, concurrent: 500 }
```

**সবসময় header গুলো ফেরত দিন** (§৫.৮) আর **সীমাগুলো প্রকাশ্যে নথিভুক্ত করুন**। Customer-এর দৃষ্টিতে একটা অনথিভুক্ত rate limit একটা outage।

## ৮.২১ Service discovery (API-র দৃষ্টিতে) 🟡

অধ্যায় ০৫-এ আলোচিত। API-র ভাষায়:

- **ভেতরে:** service গুলো একে অপরকে **যৌক্তিক নাম** দিয়ে call করে (`http://billing-service`), যেটা Kubernetes DNS / Consul / Eureka সমাধান করে। কখনো IP বা port hard-code করবেন না।
- **বাইরে:** DNS + একটা load balancer + একটা স্থিতিশীল public hostname
- **Service mesh** (Istio, Linkerd) discovery, retry, timeout, mTLS আর tracing আপনার কোড থেকে সরিয়ে একটা sidecar-এ নেয় — ~২০+ service-এ এর দাম আছে, তার নিচে অতিরিক্ত

---

## ৮.২২ API documentation আর contract 🟢

**একটা অনথিভুক্ত API-র কোনো অস্তিত্ব নেই।**

### OpenAPI (আগে Swagger) — standard

```yaml
openapi: 3.1.0
info:
  title: Verification API
  version: 1.0.0
paths:
  /v1/verification-sessions:
    post:
      summary: Start a verification session
      operationId: startSession
      parameters:
        - name: Idempotency-Key
          in: header
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/StartSessionRequest' }
      responses:
        '201':
          description: Session created
          headers:
            Location: { schema: { type: string } }
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Session' }
        '422':
          description: Validation failed
          content:
            application/problem+json:
              schema: { $ref: '#/components/schemas/Problem' }
```

**Documentation-এর বাইরে OpenAPI আপনাকে যা দেয়:**
- প্রতিটা ভাষায় generate করা client (হাতে HTTP call লেখা বন্ধ করুন)
- Generate করা server stub আর request validation
- Backend তৈরির আগেই frontend টিমের জন্য mock server
- **CI-তে স্বয়ংক্রিয় breaking-change শনাক্তকরণ** (`oasdiff`) — এটা একটা fitness function (অধ্যায় ০০)
- Contract test (অধ্যায় ২১)

> **Design-first বনাম code-first:** annotate করা কোড থেকে OpenAPI generate করা সুবিধাজনক, কিন্তু design-first (spec লিখুন, রিভিউ করুন, তারপর implement করুন) ভালো API তৈরি করে, কারণ contract-টা ব্যয়বহুল হওয়ার *আগেই* রিভিউ হয়। Public API-র জন্য design-first-এর শৃঙ্খলা রাখার মতো।

### একটা ভালো API reference-এ আরও যা লাগে

- একটা কাজ করা উদাহরণ সহ authentication-এর গাইড
- প্রতিটা endpoint-এর জন্য **কপি-পেস্ট করার যোগ্য curl উদাহরণ**
- Error code-এর reference
- Rate limit, quota আর pagination ব্যাখ্যা করা
- নমুনা payload সহ webhook event-এর ক্যাটালগ
- একটা changelog আর একটা deprecation policy
- Test credential সহ একটা sandbox environment

---

## ৮.২৩ একটা API style বেছে নেওয়া

| পরিস্থিতি | বাছুন |
|-----------|--------|
| তৃতীয় পক্ষের জন্য public API | **REST + OpenAPI** |
| Browser → আপনার backend | REST, বা অনেক বিভিন্ন screen থাকলে GraphQL |
| ভেতরের service → service, উচ্চ volume | **gRPC** |
| অনেক আলাদা screen সহ mobile app | **GraphQL** বা একটা **mobile BFF** |
| Server একটা browser-এ আপডেট পাঠায় | **SSE** |
| দ্বিমুখী real-time (chat, সহযোগিতা) | **WebSocket** |
| অন্য কোম্পানির সিস্টেমকে জানানো | **Webhook** (সাথে একটা polling fallback) |
| দীর্ঘ operation | REST `202 Accepted` + একটা status endpoint, বা progress-এর জন্য SSE |
| Bulk data স্থানান্তর | Object storage-এ file export + একটা signed URL — একটা paginated API **নয়** |

> **পরিণত উত্তর সাধারণত "কয়েকটা"।** ভেতরে gRPC, public প্রান্তে REST, progress-এর জন্য SSE, notification-এর জন্য webhook, আর bulk-এর জন্য একটা file export। প্রতিটাই এমন একটা কারণে বাছা, যেটা আপনি বলতে পারেন।

---

## ৮.২৪ সাধারণ ভুল

১. **URL-এ ক্রিয়া** — `/getUser`, `/createOrder`
২. **`{"success": false}` সহ HTTP 200** — প্রতিটা cache, monitor আর client ভাঙে
৩. **সীমাহীন list endpoint** — যেদিন একজন customer-এর ৪০ লাখ row হবে, সেদিন জানবেন
৪. **গভীরে offset pagination** — `OFFSET 500000` অর্ধেক table scan করে
৫. **টাকার endpoint-এ কোনো idempotency key নেই** — client retry করলে দ্বিগুণ charge
৬. **Domain entity সরাসরি প্রকাশ করা** — দুর্ঘটনাজনিত data ফাঁস আর একটা জমে যাওয়া ভেতরের model
৭. **কোনো `Vary: Authorization` নেই** — একটা shared cache একজনের data আরেকজনকে দেয়
৮. **Version ছাড়া breaking পরিবর্তন** — production-এ client নীরবে ভাঙে
৯. **কোনো rate limiting নেই** — একটা buggy customer script সবার জন্য API নামিয়ে দেয়
১০. **Error-এ ভেতরের জিনিস ফাঁস** — stack trace, SQL, hostname
১১. **অসঙ্গত নামকরণ** — এখানে `created_at`, ওখানে `creationDate`, আরেক জায়গায় `CreatedAt`
১২. **৪০১/৪০৩ আর ৪০০/৪২২-র পার্থক্য উপেক্ষা করা** — client সঠিকভাবে error সামলাতে পারে না
১৩. **যেখানে SSE চলত সেখানে WebSocket** — একমুখী আপডেটের জন্য দশ গুণ জটিলতা
১৪. **Sign না করা webhook** — যে কেউ URL জানলে event জাল করতে পারে
১৫. **৪২৯/৫০৩-এ কোনো `Retry-After` নেই** — আপনি ইতিমধ্যেই কষ্টে আছেন, আর client আপনাকে পেটাচ্ছে

---

## ৮.২৫ আর্কিটেক্টের চেকলিস্ট

- [ ] Resource বিশেষ্য; method ক্রিয়া; URL সামঞ্জস্যপূর্ণ আর ছোট হাতের
- [ ] সঠিক status code, ৪০১ বনাম ৪০৩ আর ৪০০ বনাম ৪২২ সহ
- [ ] Error-এ Problem Details ব্যবহৃত, একটা মেশিন-code, field-error আর একটা trace ID সহ
- [ ] প্রতিটা collection endpoint paginated (যেখানে গুরুত্বপূর্ণ সেখানে cursor-ভিত্তিক), একটা সীমাবদ্ধ limit সহ
- [ ] Filter/sort-এর field গুলো whitelist করা আর indexed
- [ ] পার্শ্বপ্রতিক্রিয়া আছে এমন সব non-idempotent POST-এ idempotency key আবশ্যক
- [ ] হালনাগাদযোগ্য resource-এ ETag / `If-Match` (optimistic concurrency)
- [ ] Cache header ইচ্ছাকৃতভাবে সেট করা, যেখানে দরকার সেখানে `Vary` সহ
- [ ] Versioning-এর কৌশল বাছা; যোগ-করে-পরিবর্তনের নীতি নথিভুক্ত; tolerant-reader contract প্রকাশিত
- [ ] `Deprecation`/`Sunset` header আর প্রতি-client ব্যবহারের metric সহ deprecation policy
- [ ] Rate limit implement করা, নথিভুক্ত, আর header-এ ফেরত দেওয়া
- [ ] OpenAPI spec আছে, রিভিউ হয়, আর breaking change CI fail করায়
- [ ] Webhook timestamp সহ sign করা, backoff সহ retry করা, deduplicate করা যায় আর replay করা যায়
- [ ] Payload-এর আকারের সীমা আর request timeout বলবৎ
- [ ] Auth (অধ্যায় ১৭) আর CORS স্পষ্টভাবে configure করা, ঢালাওভাবে নয়

---

## ৮.২৬ নিজেকে যাচাই

১. কোন দুটো REST constraint বেশিরভাগ ব্যবহারিক মূল্য দেয়, আর কেন?
২. "একটা payment refund করুন" — তিনভাবে RESTful-ভাবে model করুন। কোনটা সেরা আর কেন?
৩. ৪০১ বনাম ৪০৩। ৪০০ বনাম ৪২২। ৩০২ বনাম ৩০৭। প্রতিটা জোড়া ব্যাখ্যা করুন।
৪. একটা error body সহ HTTP 200 ফেরত দেওয়া কেন ক্ষতিকর? এটা ভাঙে এমন তিনটা সিস্টেমের নাম বলুন।
৫. Offset pagination গভীরে কেন ধীর? একটা স্থিতিশীল tiebreaker সহ cursor pagination-এর SQL লিখুন।
৬. ETag / `If-Match`-এর প্রবাহ আর এটা যে bug ঠেকায় সেটা ব্যাখ্যা করুন।
৭. `Vary: Authorization` কেন নিরাপত্তা-গুরুত্বপূর্ণ?
৮. কোন API পরিবর্তনগুলো ভাঙে না? "Tolerant reader" contract কী?
৯. gRPC বনাম REST বনাম GraphQL — প্রতিটার নির্ণায়ক বিষয়টা বলুন।
১০. WebSocket-এর বদলে কখন SSE বাছবেন? একটা বাস্তব উদাহরণ দিন।
১১. একজন পেশাদার webhook প্রদানকারীকে যে ছয়টা কাজ করতেই হবে, তালিকা দিন।
১২. একটা API Gateway-তে কী থাকা উচিত, আর কী কখনোই যাওয়া উচিত নয়?
১৩. একটা BFF এমন কোন সমস্যা সমাধান করে যা একটা gateway করে না?
১৪. একটা তিন-স্তরের SaaS API-র জন্য rate-limiting-এর পরিকল্পনা design করুন, header সহ।

---

## ৮.২৭ মূল কথাগুলো

- **একটা API একটা স্থায়ী প্রকাশ্য প্রতিশ্রুতি।** বানানোর আগেই design করুন।
- **Resource বিশেষ্য, method ক্রিয়া, status code অর্থ বহন করে** — ঠিকভাবে ব্যবহার করুন
- **Cursor pagination, সীমাবদ্ধ limit, whitelist করা filter** — নইলে আপনার API একটা DoS-এর পথ
- **টাকায় idempotency key।** **হালনাগাদে ETag।** দুটোই ছোট আর আস্ত শ্রেণির bug ঠেকায়।
- **যোগ করে version করুন** আর একটা tolerant-reader contract প্রকাশ করুন; তাহলে আপনার খুব কমই v2 লাগবে
- Error-এ **Problem Details (RFC 9457)**, একটা trace ID সহ
- **ভেতরে gRPC, প্রান্তে REST, push-এ SSE, notification-এ webhook** — উদ্দেশ্য অনুযায়ী বাছুন
- **SSE কম ব্যবহৃত**; বেশিরভাগ একমুখী push-এ WebSocket লাগে না
- আপনার webhook **sign, retry, dedupe আর replay** করুন
- **Cross-cutting concern-এর জন্য gateway, client-নির্দিষ্ট আকৃতির জন্য BFF।** কোনোটাতেই কখনো business logic নয়।
- **CI-তে OpenAPI** "আমরা contract ভেঙেছি"-কে একটা ব্যর্থ build-এ পরিণত করে

---

**পরবর্তী:** [অধ্যায় ০৯ — Database Architecture](09-database-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 08](../08-api-architecture.md) · **[সূচিপত্র](README.md)**
