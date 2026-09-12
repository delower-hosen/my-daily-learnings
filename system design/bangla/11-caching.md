# অধ্যায় ১১ — Caching 🟢

> Caching অস্তিত্বশীল সবচেয়ে লাভজনক performance কৌশল। একটা ২০ ms-এর database query হয়ে যায় একটা ০.৩ ms-এর memory read।
> আবার এখানেই আপনার সিস্টেমের সবচেয়ে সূক্ষ্ম bug গুলো বাস করবে।
>
> *"কম্পিউটার বিজ্ঞানে মাত্র দুটো কঠিন জিনিস আছে: cache invalidation আর নামকরণ।"* — Phil Karlton

---

## ১১.১ যে কোনো cache যোগ করার আগে তিনটা প্রশ্ন

প্রতিবারই এগুলো করুন। বেশিরভাগ খারাপ cache-এর অস্তিত্ব এই কারণেই যে কেউ এগুলো এড়িয়ে গেছে।

**১. এই data কি যত বদলায় তার চেয়ে অনেক বেশি পড়া হয়?**
Read:write অনুপাত ২:১ হলে একটা cache জটিলতা আর memory-র খরচ যোগ করে প্রায় কোনো লাভ ছাড়াই। ১০০০:১ হলে caching প্রায় বিনামূল্যের টাকা।

**২. এই data কতটা পুরনো হতে পারে?**
- কখনো পুরনো নয় → আপনার write-through বা স্পষ্ট invalidation লাগবে, আর জটিলতাটা মেনে নিতে হবে
- ৫ সেকেন্ড → একটা ছোট TTL সব সমাধান করে
- ১ ঘণ্টা → তুচ্ছভাবে cache করার যোগ্য
- উত্তরটাই আপনার পুরো কৌশল ঠিক করে। **Business থেকে একটা সংখ্যা নিন, কাঁধ ঝাঁকানো নয়।**

**৩. Cache খালি বা বন্ধ থাকলে কী হয়?**
উত্তর যদি হয় "database মরে যায়", তাহলে **আপনি একটা cache বানাননি — আপনি একটা ভার বহনকারী dependency বানিয়েছেন যেটা data হারানোর জন্য configure করা।** Live যাওয়ার আগেই ঠান্ডা-শুরুর ক্ষেত্রটার জন্য design করুন। (§১১.৭ দেখুন।)

---

## ১১.২ কোথায় cache করবেন — স্তরবিন্যাস

আপনি যত আগের স্তরে থামবেন, তার নিচের সবকিছু তত বাঁচবে।

| স্তর | Latency | পরিসর | কীসের জন্য সেরা |
|-------|---------|-------|----------|
| **১. Browser / client** | ০ ms | একজন ব্যবহারকারী | Static asset, ব্যবহারকারীর পছন্দ, `Cache-Control` সহ API response |
| **২. CDN / edge** | ১০–৫০ ms | বৈশ্বিক | ছবি, JS/CSS, ভিডিও, public API GET, পুরো পাতা |
| **৩. Reverse proxy / gateway** | ১–৫ ms | একটা region | পূর্ণ HTTP response, auth token যাচাই |
| **৪. Application-এর memory** | ~১০০ ns | একটা process | Config, feature flag, reference data, গরম ছোট object |
| **৫. Distributed cache (Redis)** | ০.৩–১ ms | সব process | Session, হিসাব করা ফলাফল, query-র ফলাফল, rate limit |
| **৬. Database-এর buffer pool** | ~১ ms | একটা DB | স্বয়ংক্রিয় — শুধু DB-কে যথেষ্ট RAM দিন |
| **৭. Materialised view** | ১–১০ ms | একটা DB | আগে থেকে aggregate করা report (অধ্যায় ০৯) |

### স্থানীয় (in-process) বনাম distributed cache

| | **স্থানীয় (in-memory)** | **Distributed (Redis)** |
|---|---|---|
| গতি | ~১০০ ns | ~৫০০ µs (তবু disk-এর চেয়ে ৪০× দ্রুত) |
| Instance জুড়ে consistency | ❌ প্রতিটা instance আলাদা | ✅ একটাই ভাগ করা সত্য |
| Restart-এ টেকে | ❌ | ✅ |
| Memory-র খরচ | × instance-এর সংখ্যা | একবার |
| Invalidation | কঠিন — সব instance-এ প্রচার করতে হবে | সহজ — একটা key মুছুন |
| কীসের জন্য সেরা | ছোট, কম-বদলানো, অনবরত-পড়া data | বাকি সবকিছু |

> **দুই-স্তরের pattern (near cache) হলো পেশাদার default:** Redis-এর সামনে একটা ছোট স্থানীয় cache। এটা সবচেয়ে গরম key গুলো ন্যানোসেকেন্ড গতিতে শুষে নেয় আর Redis-এর traffic নাটকীয়ভাবে কমায় — তবে আপনাকে instance জুড়ে invalidation সামলাতে হবে (সাধারণত Redis-এর pub/sub দিয়ে)।

```python
class TwoTierCache:
    """L1 = in-process (দ্রুত, ছোট, প্রতি instance-এ)। L2 = Redis (ভাগ করা)।"""

    def __init__(self, redis, local_ttl: int = 5, max_local: int = 10_000):
        self._redis = redis
        self._local = TTLCache(maxsize=max_local, ttl=local_ttl)   # ছোট TTL-ই সবচেয়ে
        self._local_ttl = local_ttl                                # সহজ invalidation

    async def get(self, key: str):
        if (v := self._local.get(key)) is not None:      # L1
            metrics.increment("cache.l1.hit")
            return v
        if (raw := await self._redis.get(key)) is not None:   # L2
            metrics.increment("cache.l2.hit")
            value = json.loads(raw)
            self._local[key] = value
            return value
        metrics.increment("cache.miss")
        return None

    async def invalidate(self, key: str) -> None:
        await self._redis.delete(key)
        self._local.pop(key, None)
        await self._redis.publish("cache:invalidate", key)   # অন্য instance গুলোকে জানান

    async def listen_for_invalidations(self) -> None:
        async for msg in self._redis.subscribe("cache:invalidate"):
            self._local.pop(msg["data"], None)
```

> **বাস্তববাদী নোট:** L1-এর TTL ছোট রাখুন (৫–৩০ সেকেন্ড)। ছোট TTL-এ প্রায়ই pub/sub প্রচারটা একদমই লাগে না — সীমাবদ্ধ পুরনো হওয়া নিখুঁত invalidation-এর চেয়ে সহজ আর বেশি মজবুত।

---

## ১১.৩ Caching pattern 🟢

### ১. Cache-Aside (Lazy Loading) ⭐ — ৯০% ক্ষেত্রে এটাই ব্যবহার করবেন

```
READ:
  ১. Cache-এ দেখুন
  ২. HIT  → ফেরত দিন
  ৩. MISS → database পড়ুন, cache-এ লিখুন, ফেরত দিন

WRITE:
  ১. Database-এ লিখুন
  ২. Cache-এর key INVALIDATE করুন (হালনাগাদ করবেন না — নিচে দেখুন)
```

```python
async def get_customer(customer_id: str) -> Customer:
    key = f"customer:{customer_id}"
    if (cached := await cache.get(key)) is not None:
        return Customer.parse_raw(cached)

    customer = await db.fetch_one("SELECT * FROM customers WHERE id = $1", customer_id)
    if customer is None:
        await cache.set(key, NULL_SENTINEL, ttl=60)      # negative cache (§১১.৮ দেখুন)
        raise NotFound(customer_id)

    await cache.set(key, customer.json(), ttl=300)
    return customer

async def update_customer(customer_id: str, changes: dict) -> None:
    await db.execute("UPDATE customers SET ... WHERE id = $1", customer_id)
    await cache.delete(f"customer:{customer_id}")        # INVALIDATE, হালনাগাদ নয়
```

**Write-এ হালনাগাদ না করে invalidate কেন?**

```
সময়  T1 (write A)                 T2 (write B)
 ১    UPDATE db SET x=1
 ২                                 UPDATE db SET x=2
 ৩                                 SET cache x=2
 ৪    SET cache x=1     ← পুরনো মান জিতল। Cache এখন স্থায়ীভাবে DB-র সাথে অমিল।
```

সাধারণ ক্ষেত্রে মুছে ফেলায় এমন কোনো race নেই: পরের read বর্তমান database-এর state থেকে আবার ভরে দেয়। (একটা সূক্ষ্মতর race এখনো আছে — §১১.৯ দেখুন — তবে write-এ delete করা write-এ update করার চেয়ে কঠোরভাবে নিরাপদ।)

| ✅ সুবিধা | ❌ অসুবিধা |
|---|---|
| যা আসলে চাওয়া হয় শুধু সেটাই cache করে | প্রথম request সবসময় ধীর (ঠান্ডা miss) |
| সহনশীল — cache বন্ধ ≠ সিস্টেম বন্ধ | একটা ছোট পুরনো-হওয়ার জানালা |
| সহজ, যে কোনো store-এ কাজ করে | Race-এ cache আর DB আলাদা হয়ে যেতে পারে |

### ২. Read-Through

Cache নিজেই miss-এ database থেকে load করে; application শুধু cache-এর সাথে কথা বলে।

```python
value = await cache.get_or_load(key, loader=lambda: db.fetch(...), ttl=300)
```

Cache-aside-এর মতোই আচরণ, তবে load-এর logic কেন্দ্রীভূত — মানে সামঞ্জস্যপূর্ণ TTL, সামঞ্জস্যপূর্ণ serialisation, আর stampede-সুরক্ষা যোগ করার একটাই জায়গা। **আপনার codebase জুড়ে ছড়ানো কাঁচা cache-aside-এর বদলে এটাকেই একটা abstraction হিসেবে প্রাধান্য দিন।**

### ৩. Write-Through

Cache **আর** database-এ synchronously লিখুন, এই ক্রমে, একটা যৌক্তিক operation হিসেবে।

```
Write → Cache → Database → ফেরত
```

| ✅ | ❌ |
|---|---|
| Cache কখনো পুরনো হয় না | প্রতিটা write ধীর (দুটো সিস্টেম) |
| Write-এর পরের read সবসময় hit করে | এমন data cache করে যা হয়তো কখনো পড়াই হবে না |

**কীসের জন্য:** এমন data যা একবার লেখা হয় আর সাথে সাথেই বহুবার পড়া হয় (signup-এর পর একটা user profile, একটা হিসাব করা দামের তালিকা)।

### ৪. Write-Behind (Write-Back)

Cache-এ লিখুন, সাথে সাথে স্বীকৃতি দিন, batch-এ asynchronously database-এ flush করুন।

```
Write → Cache → (সাথে সাথে ফেরত)
                     ↓ পরে, batch-এ
                 Database
```

| ✅ | ❌ |
|---|---|
| খুব দ্রুত write | **Flush-এর আগে cache মরলে data হারায়** |
| Batch database-এর load বিশালভাবে কমায় | জটিল; নিরাপদ হতে টেকসই queuing লাগে |

**কীসের জন্য:** উচ্চ-volume, হারানো-সহনীয় write — view count, like counter, analytics event, "শেষ দেখা" timestamp। **টাকার জন্য বা audit-যোগ্য কিছুর জন্য কখনোই নয়।**

```python
# মোটামুটি-নিরাপদ একটা write-behind: Redis-এ counter, পর্যায়ক্রমে flush
async def record_view(content_id: str) -> None:
    await redis.hincrby("pending_views", content_id, 1)   # তাৎক্ষণিক

async def flush_views_loop() -> None:                     # প্রতি ১০ সেকেন্ডে
    while True:
        counts = await redis.hgetall("pending_views")
        if counts:
            await redis.delete("pending_views")           # ছোট race-জানালা: গ্রহণযোগ্য
            await db.execute_many(
                "INSERT INTO view_counts (id, views) VALUES ($1,$2) "
                "ON CONFLICT (id) DO UPDATE SET views = view_counts.views + $2",
                [(k, int(v)) for k, v in counts.items()])
        await asyncio.sleep(10)
```

ওই pattern-টা সেকেন্ডে ৫০,০০০ database write-কে প্রতি ১০ সেকেন্ডে একটা batch write-এ পরিণত করে। Counter-এর জন্য এটাই সঠিক design — আর খেয়াল করুন ১০ সেকেন্ড পর্যন্ত গণনা হারানোর ইচ্ছাকৃত, নথিভুক্ত স্বীকৃতিটা।

### ৫. Refresh-Ahead

একটা key মেয়াদ শেষ হওয়ার আগেই সক্রিয়ভাবে refresh করুন, যদি সেটা ঘন ঘন ব্যবহৃত হয়।

```python
if remaining_ttl < 0.2 * original_ttl and is_hot(key):
    asyncio.create_task(refresh(key))    # পেছনে refresh করুন
return cached_value                       # বর্তমান মানটা সাথে সাথে দিন
```

গরম key-তে ব্যবহারকারীরা কখনো cache miss টের পান না। HTTP-র `stale-while-revalidate` মূলত এটাই করে, আর ব্যয়বহুল-হিসাবের, ঘন ঘন-পড়া data-র জন্য এটা চমৎকার।

---

## ১১.৪ TTL-এর কৌশল 🟢

**TTL (time to live) আপনার নিরাপত্তা-জাল।** Invalidation-এর logic-এ bug থাকলেও একটা TTL নিশ্চিত করে যে cache শেষ পর্যন্ত নিজেকে শুধরে নেয়। **সবসময় একটা বসান** — একটা অসীম TTL মানে একটা bug চিরকাল বাঁচে।

### একটা TTL বেছে নেওয়া

| Data | প্রস্তাবিত TTL | যুক্তি |
|------|--------------|-----------|
| Static reference data (দেশ, মুদ্রা) | ঘণ্টা–দিন | প্রায় কখনোই বদলায় না |
| Product ক্যাটালগ | ৫–৬০ মিনিট | মাঝে মাঝে বদলায়; পুরনো হওয়া সহনীয় |
| User profile | ৫–১৫ মিনিট | + হালনাগাদে স্পষ্ট invalidation |
| Permission / role | **সর্বোচ্চ ১–৫ মিনিট** | Security: একটা বাতিল করা permission দ্রুত কার্যকর হতে হবে |
| Search-এর ফলাফল | ১–৫ মিনিট | তাজা হওয়া গুরুত্বপূর্ণ; ফলাফল ব্যয়বহুল |
| Session data | Sliding, = session timeout | প্রতিবার ব্যবহারে বাড়ান |
| দাম / inventory | সেকেন্ড, বা কখনোই cache নয় | Business-critical সঠিকতা |
| হিসাব করা aggregate | Business-এর সহনশীলতার সাথে মেলান | জিজ্ঞেস করুন: "এই report কতটা তাজা লাগে?" |
| Negative ফলাফল (পাওয়া যায়নি) | ৩০–৬০ সেকেন্ড | ছোট, penetration ঠেকাতে (§১১.৮) |

> **Security-র নিয়ম: authorisation-এর সিদ্ধান্ত কখনো বেশিক্ষণ cache করবেন না।** একজন admin access বাতিল করলেন আর সেটা কার্যকর হতে ৩০ মিনিট লাগল — এটা একটা security incident, যেটা লেখা হওয়ার অপেক্ষায়। ৬০ সেকেন্ড, সাথে permission বদলালে স্পষ্ট invalidation।

### TTL-এ jitter যোগ করুন

```python
# ভুল — deploy-এর সময় বানানো ১০,০০০ key একই সেকেন্ডে মেয়াদ শেষ করে
await cache.set(key, value, ttl=300)

# সঠিক — মেয়াদ শেষ হওয়াটা একটা জানালা জুড়ে ছড়িয়ে দিন
await cache.set(key, value, ttl=300 + random.randint(-30, 30))
```

Jitter ছাড়া আপনি একটা সমলয় গণ-মেয়াদশেষ পান — একটা **cache avalanche** (§১১.৭)।

---

## ১১.৫ Cache key — ঠিকভাবে design করুন

```python
# খারাপ
key = f"user{user_id}"                       # কোনো namespace নেই, সংঘর্ষ করে, পড়া যায় না

# ভালো — কাঠামোবদ্ধ, namespace করা, version করা
key = f"app:v2:customer:{tenant_id}:{customer_id}"
key = f"app:v2:sessions:tenant={tenant_id}:status=pending:page={cursor}"
```

**নিয়ম:**

১. **সবকিছু namespace করুন** — `app:entity:id`। কোলন হলো Redis-এর প্রথা আর এটা `SCAN app:v2:customer:*` সম্ভব করে।
২. **একটা schema version রাখুন** (`v2`)। আপনার serialise করা আকৃতি বদলালে version বাড়ান — পুরো পুরনো cache সাথে সাথে অনাথ হয়ে নিজেই মেয়াদ শেষ করে। **এটাই সবচেয়ে পরিষ্কার cache-busting কৌশল, আর এটা একটা deploy-এর পর deserialisation crash এড়ায়।**
৩. **Tenant ID রাখুন।** একটা cache key-তে অনুপস্থিত tenant মানে একটা cross-tenant data ফাঁস — আপনার ship করা সবচেয়ে গুরুতর bug গুলোর একটা।
৪. **ফলাফল বদলায় এমন সবকিছু রাখুন** — ব্যবহারকারী, locale, permission, feature flag। একটা variable উপেক্ষা করা key একটা সঠিকতার bug।
৫. **Key deterministic রাখুন** — hash করার আগে query parameter গুলো sort করুন।

```python
def build_key(prefix: str, **params) -> str:
    """যথেচ্ছ parameter থেকে একটা deterministic key।"""
    canonical = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] is not None)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"app:v2:{prefix}:{digest}"
```

> **১ নম্বর caching security bug: একটা ব্যবহারকারী-নির্দিষ্ট response এমন একটা key-তে cache করা যেটা ব্যবহারকারী-নির্দিষ্ট নয়।** ব্যবহারকারী A-র dashboard ব্যবহারকারী B-কে দেওয়া হয়। Key-তে পরিচয় রাখুন, আর HTTP cache-এ `Vary: Authorization` রাখুন (অধ্যায় ০৮)।

---

## ১১.৬ Cache invalidation-এর কৌশল

| কৌশল | কীভাবে | কখন ব্যবহার করবেন |
|----------|-----|-------------|
| **শুধু TTL** | মেয়াদ শেষ হতে দিন | সবচেয়ে সহজ; সীমাবদ্ধ পুরনো হওয়া গ্রহণযোগ্য হলে — **default** |
| **Write-এ স্পষ্ট delete** | Entity বদলালে key invalidate করুন | তাজা হওয়া গুরুত্বপূর্ণ আর সব write আপনার নিয়ন্ত্রণে |
| **Key versioning** | Key-তে একটা version রাখুন; বাড়িয়ে সবকিছু অনাথ করুন | Schema পরিবর্তন, গণ invalidation |
| **Tag-ভিত্তিক** | Key-তে tag থাকে; tag X সহ সব key invalidate করুন | জটিল নির্ভরতার graph (CDN, Varnish, কিছু Redis pattern) |
| **Event-চালিত** | পরিবর্তনের event (CDC/outbox) নিন আর invalidate করুন | একাধিক লেখক, বা আপনার service-এর বাইরের লেখক — **scale-এ মজবুত উত্তর** |
| **Generation counter** | `cache:gen:customers = 7`; প্রতিটা key-তে রাখুন | একটা পুরো শ্রেণির key atomically invalidate করুন |

```python
# Generation-counter invalidation — একটা tenant-এর সবকিছু O(1)-এ invalidate করুন
async def get_key(tenant_id: str, suffix: str) -> str:
    gen = await redis.get(f"gen:tenant:{tenant_id}") or "0"
    return f"app:v2:t{tenant_id}:g{gen}:{suffix}"

async def invalidate_tenant(tenant_id: str) -> None:
    await redis.incr(f"gen:tenant:{tenant_id}")   # প্রতিটা পুরনো key এখন অগম্য
    # পুরনো key আর কখনো পড়া হয় না আর নিজেই মেয়াদ শেষ করে — কোনো scan নেই, কোনো delete নেই
```

> **Production Redis-এ কখনো `KEYS pattern*` ব্যবহার করবেন না** — এটা O(N), single-threaded server আটকে দেয়, আর সত্যিকারের outage ঘটিয়েছে। `SCAN` (cursor-ভিত্তিক) ব্যবহার করুন, অথবা এমনভাবে design করুন যাতে কখনো scan করতেই না হয়: generation counter আর version করা key scanning অপ্রয়োজনীয় করে দেয়।

---

## ১১.৭ তিনটা ক্লাসিক cache-বিপর্যয় 🟢

এগুলোর নাম আছে কারণ এগুলো সত্যিকারের সিস্টেম নামিয়ে দিয়েছে। তিনটাই জানুন।

### ১. Cache Stampede (Thundering Herd / Dog-piling)

```
একটা জনপ্রিয় key t=০-তে মেয়াদ শেষ করে।
t=০-তে ৫,০০০ concurrent request সবাই miss করে।
সব ৫,০০০টা একই মানের জন্য database query করে, একসাথে।
Database মরে যায়। কিছুই cache আবার ভরতে পারে না। সাইট বন্ধ।
```

**সমাধান ক — Lock (single-flight):** শুধু একটা request আবার হিসাব করে; বাকিরা অপেক্ষা করে বা পুরনোটা দেয়।

```python
async def get_with_lock(key: str, loader, ttl: int = 300):
    if (v := await cache.get(key)) is not None:
        return v

    lock_key = f"lock:{key}"
    got_lock = await redis.set(lock_key, "1", nx=True, ex=10)

    if got_lock:
        try:
            value = await loader()                          # শুধু একটা request এটা করে
            await cache.set(key, value, ttl=ttl + jitter())
            return value
        finally:
            await redis.delete(lock_key)
    else:
        # অন্য কেউ load করছে। একটু অপেক্ষা করুন, তারপর আবার দেখুন।
        for _ in range(20):
            await asyncio.sleep(0.05)
            if (v := await cache.get(key)) is not None:
                return v
        return await loader()      # শেষ আশ্রয় — চিরকাল অপেক্ষা করবেন না
```

**সমাধান খ — সম্ভাব্যতা-ভিত্তিক আগাম মেয়াদশেষ (XFetch):** প্রতিটা request-এর আগেভাগে refresh করার একটা ছোট, ক্রমবর্ধমান সম্ভাবনা থাকে, তাই refresh গুলো স্বাভাবিকভাবে ছড়িয়ে যায় আর load-এ কোনো key কখনো কঠোরভাবে মেয়াদ শেষ করে না।

```python
def should_refresh_early(ttl_remaining: float, compute_time: float, beta: float = 1.0) -> bool:
    # মেয়াদশেষের যত কাছে, আর হিসাব যত ব্যয়বহুল, সম্ভাবনা তত বেশি
    return ttl_remaining - compute_time * beta * math.log(random.random()) <= 0
```

**সমাধান গ — পুনর্যাচাই করতে করতে পুরনোটা দিন:** দুটো TTL রাখুন — একটা "নরম" যেটা পেছনে refresh শুরু করে, আর একটা "কঠিন" যেটা আসল মেয়াদশেষ। ব্যবহারকারীরা সবসময় তাৎক্ষণিক উত্তর পান।

**সমাধান ঘ — গরম key কখনো মেয়াদ শেষ হতে দেবেন না:** একটা background job থেকে সময়সূচি মেনে সেগুলো refresh করুন।

> **যে কোনো key যেটা একইসাথে হিসাব করতে ব্যয়বহুল আর ভারীভাবে পড়া হয়, তার জন্য stampede-সুরক্ষা ঐচ্ছিক নয়।**

### ২. Cache Penetration

```
একজন আক্রমণকারী (বা একটা buggy client) এমন key চায় যেগুলোর অস্তিত্ব নেই।
প্রতিটা request cache miss করে → database-এ যায় → কিছু পায় না → কিছু cache করে না।
Cache শূন্য সুরক্ষা দেয়। Database ১০০% traffic নেয়।
```

**সমাধান ক — Negative caching:** "পাওয়া যায়নি" ফলাফলটা cache করুন, একটা ছোট TTL সহ।

```python
NULL_SENTINEL = "\x00__NOT_FOUND__"

if cached == NULL_SENTINEL:
    raise NotFound(key)
...
if row is None:
    await cache.set(key, NULL_SENTINEL, ttl=60)     # ছোট! আইটেমটা শীঘ্রই তৈরি হতে পারে
    raise NotFound(key)
```

**সমাধান খ — Query করার আগে যাচাই করুন:** ID যদি UUID হয়, তাহলে প্রান্তেই এমন যা কিছু বৈধ UUID নয় তা প্রত্যাখ্যান করুন। বিনামূল্যে, আর এটা বেশিরভাগ scanning আক্রমণ থামায়।

**সমাধান গ — Bloom filter:** একটা কমপ্যাক্ট সম্ভাব্যতা-ভিত্তিক কাঠামো, যা "নিশ্চিতভাবে নেই" বা "সম্ভবত আছে" উত্তর দেয়। Filter যদি না বলে, database একদম এড়িয়ে যান।

```python
# ১ কোটি key, ১% false positive হার ≈ ১২ MB memory
if not bloom.might_contain(customer_id):
    raise NotFound(customer_id)        # নিশ্চিত যে এটা নেই — DB ছোঁয়াই হয়নি
```

**সমাধান ঘ — Miss-ভারী endpoint-এ client অনুযায়ী rate limit** করুন।

### ৩. Cache Avalanche

```
বিপুল সংখ্যক key একই মুহূর্তে মেয়াদ শেষ করে (বা পুরো cache restart হয়)।
সবকিছু একসাথে miss করে। Database তার পুরো uncached load পায়।
Database সেটা সামলাতে পারে না। সবকিছু timeout হয়।
```

**কারণ:** সব key একই সময়ে একই TTL দিয়ে ভরা (একটা deploy, একটা warmup script); একটা Redis restart বা failover; `maxmemory`-তে পৌঁছালে একটা cache eviction ঝড়।

**সমাধান:**
১. **TTL jitter** (§১১.৪) — মেয়াদশেষ ছড়িয়ে দেয়
২. **Cache warming** — traffic নেওয়ার আগে গরম key গুলো ভরে নিন
৩. **দুই-স্তরের caching** — L2 ঠান্ডা থাকাকালীন L1 স্থানীয় cache কিছু traffic শুষে নেয়
৪. **Database-এ circuit breaker** — ভেঙে পড়ার বদলে load shed করুন (অধ্যায় ০৫)
৫. **Redis HA** — replica + Sentinel/Cluster, যাতে একটা node হারানো মানে সব হারানো না হয়
৬. **Cache আবার ভরার rate-limit করুন** — কতগুলো concurrent miss database-এ পৌঁছাতে পারে তা সীমাবদ্ধ করুন

> **এটা ইচ্ছাকৃতভাবে test করুন:** production-এর মতো load-এর নিচে একটা staging environment-এ আপনার cache flush করুন আর দেখুন কী হয়। বেশিরভাগ টিম আবিষ্কার করে যে তাদের সিস্টেম একটা ঠান্ডা cache-এ টিকতে পারে না — আর তারা এটা production-এ আবিষ্কার করে।

---

## ১১.৮ Cache consistency — সৎ ছবিটা

### Cache-aside-এর মৌলিক race

```
সময়   Request A (read)           Request B (write)
 ১     cache miss
 ২     DB পড়ে → x = 1
 ৩                                UPDATE db SET x = 2
 ৪                                DELETE cache key
 ৫     SET cache x = 1   ← INVALIDATION-এর পরে পুরনো মান লেখা হলো
```

Cache এখন `1` ধরে রাখে যতক্ষণ না TTL শেষ হয়, আর database ধরে রাখে `2`।

**উপশম (পরিশ্রমের ক্রমবর্ধমান ক্রমে):**

১. **একটা ছোট TTL** — ক্ষতি সীমাবদ্ধ করে। সাধারণত যথেষ্ট, আর এই কারণেই আপনি সবসময় একটা TTL বসান।
২. **বিলম্বিত দ্বিগুণ delete** — delete করুন, লিখুন, ~৫০০ ms অপেক্ষা করুন, আবার delete করুন। অমার্জিত কিন্তু কার্যকর।
৩. **একটা version/timestamp যাচাই সহ set** — আপনার data নতুন হলেই cache-এ লিখুন।
৪. **CDC দিয়ে event-চালিত invalidation** — database-এর change log থেকে invalidate করুন, যেটা কঠোরভাবে সাজানো। **এটাই মজবুত উত্তর**, আর এটা অন্য service, batch job আর DBA-দের করা write-ও সামলায়।

```python
# CDC-চালিত invalidation — write-এর পথকে invalidate করার কথা মনে রাখতে হয় না
async def on_database_change(change: ChangeEvent) -> None:
    if change.table == "customers":
        await cache.delete(f"app:v2:customer:{change.row['tenant_id']}:{change.row['id']}")
        await redis.incr(f"gen:tenant:{change.row['tenant_id']}")   # view গণ-invalidate
```

> **এই বাস্তবতাটা মেনে নিন:** একটা cache *সংজ্ঞা অনুযায়ীই* একটা eventually-consistent কপি। কোনো data যদি **কোনোই** পুরনো হওয়া সইতে না পারে, তাহলে সেটা cache করবেন না — উৎস থেকে পড়ুন। একটা নিখুঁতভাবে consistent cache বানানোর চেষ্টাতেই মানুষ ছয় মাস খরচ করে আর তবু bug থেকে যায়।

### যা কখনো cache করবেন না

- Authentication-এর credential আর গোপন তথ্য
- এমন যা কিছু যেখানে একটা পুরনো read আর্থিক ক্ষতি ঘটায় (একটা transfer-এর মুহূর্তে account-এর balance)
- তাৎক্ষণিক আইনি মুছে ফেলার দাবির অধীন data, যদি না আপনি নির্ভরযোগ্যভাবে purge করতে পারেন
- একটা ভাগ করা key-র নিচে অত্যন্ত ব্যক্তিগতকৃত data (cross-tenant ফাঁস)

---

## ১১.৯ CDN caching 🟡

একটা CDN হলো স্তর ২-এ একটা cache — ভৌগোলিকভাবে বিতরণ করা, আর এটা আপনার infrastructure থেকে traffic পুরোপুরি সরিয়ে দেয়।

```
ব্যবহারকারী (ঢাকা) ──► CDN edge (সিঙ্গাপুর) ──► [miss] ──► Origin (ফ্রাঙ্কফুর্ট)
                          ↑                                     │
                          └───── ভবিষ্যতের ব্যবহারকারীদের জন্য cached ───┘
```

### CDN-এ কী রাখবেন

| বিষয়বস্তু | Cache করার যোগ্য? | কৌশল |
|---------|-----------|----------|
| ছবি, ভিডিও, font | ✅ নিখুঁতভাবে | লম্বা TTL + content-hash করা ফাইলনাম (`app.8f3a2b.js`) → `immutable` |
| CSS/JS bundle | ✅ | একই — version করা ফাইলনাম মানে আপনি কখনো invalidate করেন না, শুধু একটা নতুন নাম deploy করেন |
| Public API GET | ✅ | ছোট TTL + `stale-while-revalidate` |
| HTML পাতা (public) | ✅ | ছোট TTL, বা ESI/edge rendering |
| ব্যবহারকারী-নির্দিষ্ট পাতা | ⚠️ | শুধু `private` সহ — edge-এ কখনোই cache হওয়া চলবে না |
| POST/PUT/DELETE | ❌ | কখনোই না |
| Authenticated API response | ❌ সাধারণত | যদি না `private` + `Vary: Authorization` একদম ঠিক থাকে |

```http
# Version করা static asset — চিরকাল cache, কখনো পুনর্যাচাই নয়
Cache-Control: public, max-age=31536000, immutable

# Public API response — ৬০ সেকেন্ড তাজা, refresh করতে করতে ৫ মিনিট পুরনোটা দিন
Cache-Control: public, max-age=60, stale-while-revalidate=300, stale-if-error=86400

# ব্যবহারকারী-নির্দিষ্ট — শুধু browser, কখনো একটা shared cache নয়
Cache-Control: private, max-age=0, must-revalidate
Vary: Authorization
```

**`stale-if-error` কম মূল্যায়িত:** আপনার origin বন্ধ থাকলে CDN একদিন পর্যন্ত শেষ ভালো response দিতে থাকে। Origin-এর outage-এও আপনার সাইট চালু থাকে। এটা caching header-এর ছদ্মবেশে একটা resilience feature।

**CDN-এ cache invalidation:** purge ধীর (সেকেন্ড থেকে মিনিট) আর প্রায়ই rate-limited। **পেশাদার পদ্ধতি হলো কখনো purge না করা** — content-hash করা URL ব্যবহার করুন, যাতে একটা নতুন deploy নতুন URL তৈরি করে আর পুরনোগুলো নিজেই বুড়িয়ে যায়।

**CDN-এর অন্য জয়:** edge-এ TLS termination, DDoS শোষণ, WAF, compression (Brotli), HTTP/3, আর চলতি পথে image রূপান্তর।

---

## ১১.১০ আপনার cache monitor করা 🟢

**যে metric গুলো থাকতেই হবে:**

| Metric | কেন | কীসে alert |
|--------|-----|----------|
| **Hit ratio** | প্রধান কার্যকারিতার সংখ্যা | হঠাৎ পতন (একটা key-ফরম্যাট পরিবর্তন বা একটা deploy-এর bug নির্দেশ করে) |
| **Miss latency** | একটা miss আসলে কতটা খারাপ | p99-এর বৃদ্ধি |
| **Eviction-এর হার** | Memory-র চাপ — cache খুব ছোট | আপনি নির্ভর করেন এমন একটা cache-এ যে কোনো টেকসই eviction |
| **ব্যবহৃত memory / maxmemory** | ক্ষমতা | > ৮০% |
| **Key-র সংখ্যা / আকারের বণ্টন** | মোটা key খোঁজা | একটা key > কয়েক MB |
| **Connection-এর সংখ্যা / error** | Client-এর স্বাস্থ্য | Error > ০ |
| **Redis-এর latency (`--latency`, slowlog)** | আটকানো command | p99 > ১ ms |

```python
# প্রতিটা cache access instrument করুন — যা দেখতে পান না তা সমন্বয় করতে পারবেন না
async def get_instrumented(key: str, loader, ttl: int):
    start = time.monotonic()
    value = await cache.get(key)
    if value is not None:
        metrics.increment("cache.hit", tags={"prefix": key.split(":")[2]})
        metrics.timing("cache.get.duration", time.monotonic() - start)
        return value

    metrics.increment("cache.miss", tags={"prefix": key.split(":")[2]})
    load_start = time.monotonic()
    value = await loader()
    metrics.timing("cache.load.duration", time.monotonic() - load_start)
    await cache.set(key, value, ttl=ttl + jitter())
    return value
```

**Hit ratio ব্যাখ্যা করা:**

```
< ৫০%   → কিছু একটা ভুল। ভুল key? TTL খুব ছোট? খুব বেশি eviction?
৫০-৮০%  → মাঝারি। কী miss হচ্ছে আর কেন দেখুন।
৮০-৯৫%  → ভালো।
> ৯৫%   → চমৎকার। এবার দেখুন বাকি miss গুলো ব্যয়বহুল কিনা।
```

অধ্যায় ০৪-এর হিসাবটা মনে রাখুন: ৯৫% থেকে ৯৯%-এ গেলে **বাকি database load-এর ৮০%** সরে যায়। শেষ কয়েক শতাংশেই মূল্যটা।

---

## ১১.১১ সাধারণ ভুল

১. **কোনো TTL নেই** — invalidation-এর একটা bug স্থায়ী পুরনো data হয়ে যায়
২. **কোনো jitter নেই** — সমলয় গণ-মেয়াদশেষ → avalanche
৩. ব্যয়বহুল গরম key-তে **কোনো stampede-সুরক্ষা নেই** → মেয়াদশেষে database মরে
৪. **একটা ভাগ করা key-তে ব্যবহারকারী-নির্দিষ্ট data cache করা** — cross-user/cross-tenant data ফাঁস। **সবচেয়ে বিপজ্জনক caching bug।**
৫. **Production-এ `KEYS *`** — single-threaded Redis আটকায়, cache নামিয়ে দেয়
৬. **Write-এ invalidate-এর বদলে cache হালনাগাদ করা** — race condition স্থায়ীভাবে একটা পুরনো মান লেখে
৭. **কোনো negative caching নেই** — penetration আক্রমণ সোজা database-এ যায়
৮. **Authorisation খুব বেশিক্ষণ cache করা** — বাতিল করা access এখনো কাজ করে
৯. **Redis-কে একটা database ভাবা** — কোনো persistence configure করা নেই, তারপর একটা restart সবকিছু হারালে চমক
১০. **`maxmemory-policy noeviction`** (default) — ভরে গেলে Redis evict না করে **write প্রত্যাখ্যান** করতে শুরু করে
১১. **কখনো একটা ঠান্ডা cache test না করা** — production-এ আবিষ্কার করা যে সিস্টেম একটা গরম cache ছাড়া শুরুই হতে পারে না
১২. **মাপার আগেই caching** — যে query কখনো ধীর ছিলই না তাতে জটিলতা যোগ করা
১৩. **বিশাল object serialise করা** — একটা ৫ MB cache-মান আনা আর deserialise করা query-টার চেয়ে বেশি খরচ করায়
১৪. **Key-তে কোনো schema version নেই** — একটা deploy-এর পর পুরনো cache করা object deserialise হতে ব্যর্থ হয় আর app crash করে

---

## ১১.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] প্রতিটা cache-এর জন্য তিনটা প্রশ্নের উত্তর: read:write অনুপাত, পুরনো হওয়ার সহনশীলতা (একটা সংখ্যা), ঠান্ডা-cache-এর আচরণ
- [ ] **প্রতিটা** key-তে TTL বসানো, jitter সহ
- [ ] Key-র ফরম্যাট: namespace করা, schema-version করা, tenant-সীমিত, deterministic
- [ ] কোনো ভাগ করা key-তে ব্যবহারকারী-নির্দিষ্ট data cache করা নেই; HTTP cache-এ `Vary` ঠিকভাবে বসানো
- [ ] ব্যয়বহুল/গরম key-তে stampede-সুরক্ষা (lock, আগাম মেয়াদশেষ, বা পুরনোটা দেওয়া)
- [ ] পাওয়া-যায়নি ফলাফলের জন্য negative caching, একটা ছোট TTL সহ
- [ ] Invalidation-এর কৌশল বাছা আর নথিভুক্ত (TTL / delete / generation / CDC)
- [ ] `maxmemory` আর একটা eviction policy configure করা — `noeviction` নয়
- [ ] ভূমিকার সাথে মিলিয়ে Redis-এর persistence configure করা (ফেলে দেওয়া যায় বনাম derived বনাম সত্যের উৎস)
- [ ] সিস্টেম ঠান্ডা cache-এ টিকতে না পারলে Redis HA (replica + Sentinel বা Cluster)
- [ ] ঠান্ডা-cache load test করা হয়েছে; load-এর নিচে একটা পূর্ণ flush-এ সিস্টেম টেকে
- [ ] Hit ratio, eviction, memory, আর miss latency monitor আর alert করা
- [ ] Authorisation-এর data ≤ ৬০ সেকেন্ড cache করা, পরিবর্তনে স্পষ্ট invalidation সহ
- [ ] CDN: content-hash করা static asset, `immutable`, `stale-while-revalidate`, `stale-if-error`
- [ ] Cache-বন্ধের ক্ষেত্রের জন্য app আর database-এর মাঝে circuit breaker

---

## ১১.১৩ নিজেকে যাচাই

১. একটা cache যোগ করার আগে কোন তিনটা প্রশ্ন করবেন?
২. Write-এ cache হালনাগাদ না করে invalidate কেন? Race-টা আঁকুন।
৩. Cache-aside বনাম write-through বনাম write-behind — প্রতিটার একটা ব্যবহারের ক্ষেত্র দিন।
৪. প্রতিটা TTL-এ jitter কেন থাকতেই হবে?
৫. Cache stampede ব্যাখ্যা করুন আর তিনটা আলাদা সমাধান দিন।
৬. Cache penetration ব্যাখ্যা করুন। একটা Bloom filter-এর ভূমিকা কী?
৭. Cache avalanche ব্যাখ্যা করুন। চারটা প্রতিরক্ষার নাম বলুন।
৮. "একটা tenant-এর pending session, পাতা ৩, তারিখ অনুযায়ী সাজানো" — এর জন্য একটা cache key design করুন। এতে কী কী থাকতেই হবে আর কেন?
৯. সবচেয়ে বিপজ্জনক caching security bug কী, আর আপনি এটা কীভাবে ঠেকাবেন?
১০. Production-এ `KEYS *` কেন নিষিদ্ধ, আর আপনি এর বদলে কী ব্যবহার করবেন?
১১. একটা generation counter আপনাকে এমন কী দেয় যা key-ধরে-key delete করা দেয় না?
১২. `stale-while-revalidate` আর `stale-if-error` কী করে, আর দ্বিতীয়টা কেন একটা resilience feature?
১৩. আপনার hit ratio ৯৫%। ৯৯%-এ ঠেলা কেন পরিশ্রমের যোগ্য? হিসাব দেখান।
১৪. কোন data কখনো cache করা উচিত নয়?

---

## ১১.১৪ মূল কথাগুলো

- **আগে তিনটা প্রশ্ন করুন।** বেশিরভাগ খারাপ cache এগুলো এড়িয়ে যায়।
- **Cache-aside + TTL + write-এ invalidate** ৯০% ক্ষেত্র ঢাকে
- **সবসময় একটা TTL বসান, সবসময় jitter যোগ করুন।** TTL আপনার bug-বিমা।
- **Key-র design-এই সঠিকতা আর security বাস করে** — namespace, version, tenant, আর ফলাফল বদলায় এমন সবকিছু
- **Stampede, penetration আর avalanche** নামযুক্ত বিপর্যয়; তিনটার বিরুদ্ধেই স্পষ্টভাবে প্রতিরক্ষা নিন
- **একটা cache সংজ্ঞা অনুযায়ীই একটা eventually-consistent কপি।** যে data কোনো পুরনো হওয়া সইতে পারে না, তা cache করা চলবে না।
- **Authorisation কখনো বেশিক্ষণ cache করবেন না**
- **Load-এর নিচে ঠান্ডা cache test করুন** — সিস্টেম একটা flush-এ টিকতে না পারলে cache-টা cache নয়, একটা dependency
- **Hit ratio-ই প্রধান metric** — আর শেষ কয়েক শতাংশই মূল্যবান
- **একটা CDN-এ কখনো purge করবেন না — বরং URL version করুন**

---

**পরবর্তী:** [অধ্যায় ১২ — Data Architecture](12-data-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 11](../11-caching.md) · **[সূচিপত্র](README.md)**
