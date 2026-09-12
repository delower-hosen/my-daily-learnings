# Chapter 11 — Caching 🟢

> Caching is the highest-leverage performance technique that exists. A 20 ms database query becomes a 0.3 ms memory read.
> It is also where the most subtle bugs in your system will live.
>
> *"There are only two hard things in computer science: cache invalidation and naming things."* — Phil Karlton

---

## 11.1 The three questions before you add any cache

Ask these every single time. Most bad caches exist because someone skipped them.

**1. Is this data read far more often than it changes?**
If the read:write ratio is 2:1, a cache adds complexity and memory cost for almost no benefit. If it is 1000:1, caching is close to free money.

**2. How stale can this data be?**
- Never stale → you need write-through or explicit invalidation, and you must accept the complexity
- 5 seconds → a short TTL solves everything
- 1 hour → trivially cacheable
- The answer sets your entire strategy. **Get a number from the business, not a shrug.**

**3. What happens when the cache is empty or down?**
If the answer is "the database dies", then **you have not built a cache — you have built a load-bearing dependency that is configured to lose data.** Design for the cold-start case before you go live. (See §11.7.)

---

## 11.2 Where to cache — the hierarchy

Every layer you hit earlier saves everything below it.

| Layer | Latency | Scope | Best for |
|-------|---------|-------|----------|
| **1. Browser / client** | 0 ms | One user | Static assets, user preferences, API responses with `Cache-Control` |
| **2. CDN / edge** | 10–50 ms | Global | Images, JS/CSS, video, public API GETs, whole pages |
| **3. Reverse proxy / gateway** | 1–5 ms | One region | Full HTTP responses, auth token validation |
| **4. Application memory** | ~100 ns | One process | Config, feature flags, reference data, hot small objects |
| **5. Distributed cache (Redis)** | 0.3–1 ms | All processes | Sessions, computed results, query results, rate limits |
| **6. Database buffer pool** | ~1 ms | One DB | Automatic — just give the DB enough RAM |
| **7. Materialised views** | 1–10 ms | One DB | Pre-aggregated reports (Chapter 09) |

### Local (in-process) vs distributed cache

| | **Local (in-memory)** | **Distributed (Redis)** |
|---|---|---|
| Speed | ~100 ns | ~500 µs (still 40× faster than disk) |
| Consistency across instances | ❌ each instance differs | ✅ one shared truth |
| Survives a restart | ❌ | ✅ |
| Memory cost | × number of instances | Once |
| Invalidation | Hard — must broadcast to all instances | Easy — delete one key |
| Best for | Small, rarely-changing, read-constantly data | Everything else |

> **The two-tier pattern (near cache) is the professional default:** a small local cache in front of Redis. It absorbs the hottest keys at nanosecond speed and dramatically reduces Redis traffic — but you must handle invalidation across instances (usually via Redis pub/sub).

```python
class TwoTierCache:
    """L1 = in-process (fast, small, per-instance). L2 = Redis (shared)."""

    def __init__(self, redis, local_ttl: int = 5, max_local: int = 10_000):
        self._redis = redis
        self._local = TTLCache(maxsize=max_local, ttl=local_ttl)   # short TTL is the
        self._local_ttl = local_ttl                                # simplest invalidation

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
        await self._redis.publish("cache:invalidate", key)   # tell the other instances

    async def listen_for_invalidations(self) -> None:
        async for msg in self._redis.subscribe("cache:invalidate"):
            self._local.pop(msg["data"], None)
```

> **Pragmatic note:** keep the L1 TTL short (5–30 s). With a short TTL you often do not need the pub/sub broadcast at all — bounded staleness is simpler and more robust than perfect invalidation.

---

## 11.3 Caching patterns 🟢

### 1. Cache-Aside (Lazy Loading) ⭐ — the one you will use 90% of the time

```
READ:
  1. Look in the cache
  2. HIT  → return it
  3. MISS → read the database, write to the cache, return it

WRITE:
  1. Write to the database
  2. INVALIDATE the cache key (do NOT update it — see below)
```

```python
async def get_customer(customer_id: str) -> Customer:
    key = f"customer:{customer_id}"
    if (cached := await cache.get(key)) is not None:
        return Customer.parse_raw(cached)

    customer = await db.fetch_one("SELECT * FROM customers WHERE id = $1", customer_id)
    if customer is None:
        await cache.set(key, NULL_SENTINEL, ttl=60)      # negative cache (see §11.8)
        raise NotFound(customer_id)

    await cache.set(key, customer.json(), ttl=300)
    return customer

async def update_customer(customer_id: str, changes: dict) -> None:
    await db.execute("UPDATE customers SET ... WHERE id = $1", customer_id)
    await cache.delete(f"customer:{customer_id}")        # INVALIDATE, don't update
```

**Why invalidate rather than update on write?**

```
Time  T1 (write A)                 T2 (write B)
 1    UPDATE db SET x=1
 2                                 UPDATE db SET x=2
 3                                 SET cache x=2
 4    SET cache x=1     ← STALE VALUE WINS. Cache now permanently disagrees with the DB.
```

Deleting has no such race in the common case: the next read repopulates from the current database state. (A subtler race still exists — see §11.9 — but delete-on-write is strictly safer than update-on-write.)

| ✅ Pros | ❌ Cons |
|---|---|
| Only caches what is actually requested | First request is always slow (cold miss) |
| Resilient — cache down ≠ system down | Brief staleness window |
| Simple, works with any store | Cache and DB can diverge under races |

### 2. Read-Through

The cache itself loads from the database on a miss; the application only talks to the cache.

```python
value = await cache.get_or_load(key, loader=lambda: db.fetch(...), ttl=300)
```

Same behaviour as cache-aside, but the loading logic is centralised — which means consistent TTLs, consistent serialisation, and one place to add stampede protection. **Prefer this as an abstraction over raw cache-aside scattered through your codebase.**

### 3. Write-Through

Write to the cache **and** the database synchronously, in that order, as one logical operation.

```
Write → Cache → Database → return
```

| ✅ | ❌ |
|---|---|
| Cache is never stale | Every write is slower (two systems) |
| Reads after a write always hit | Caches data that may never be read |

**Use for:** data that is written once and read many times immediately (a user profile after signup, a computed price list).

### 4. Write-Behind (Write-Back)

Write to the cache, acknowledge immediately, flush to the database asynchronously in batches.

```
Write → Cache → (return immediately)
                     ↓ later, batched
                 Database
```

| ✅ | ❌ |
|---|---|
| Very fast writes | **Data loss if the cache dies before flushing** |
| Batches reduce database load enormously | Complex; needs durable queuing to be safe |

**Use for:** high-volume, loss-tolerant writes — view counts, like counters, analytics events, "last seen" timestamps. **Never for money or anything auditable.**

```python
# A safe-ish write-behind: counters in Redis, flushed periodically
async def record_view(content_id: str) -> None:
    await redis.hincrby("pending_views", content_id, 1)   # instant

async def flush_views_loop() -> None:                     # every 10 seconds
    while True:
        counts = await redis.hgetall("pending_views")
        if counts:
            await redis.delete("pending_views")           # small race window: acceptable
            await db.execute_many(
                "INSERT INTO view_counts (id, views) VALUES ($1,$2) "
                "ON CONFLICT (id) DO UPDATE SET views = view_counts.views + $2",
                [(k, int(v)) for k, v in counts.items()])
        await asyncio.sleep(10)
```

That pattern turns 50,000 database writes per second into one batched write every 10 seconds. It is the correct design for counters — and note the deliberate, documented acceptance of losing up to 10 seconds of counts.

### 5. Refresh-Ahead

Proactively refresh a key before it expires, if it is being accessed frequently.

```python
if remaining_ttl < 0.2 * original_ttl and is_hot(key):
    asyncio.create_task(refresh(key))    # refresh in the background
return cached_value                       # serve the current value immediately
```

Users never experience a cache miss on hot keys. This is essentially what HTTP's `stale-while-revalidate` does, and it is excellent for expensive-to-compute, frequently-read data.

---

## 11.4 TTL strategy 🟢

**TTL (time to live) is your safety net.** Even if invalidation logic has a bug, a TTL guarantees the cache self-corrects eventually. **Always set one** — an infinite TTL means a bug lives forever.

### Choosing a TTL

| Data | Suggested TTL | Reasoning |
|------|--------------|-----------|
| Static reference data (countries, currencies) | Hours–days | Almost never changes |
| Product catalogue | 5–60 min | Changes occasionally; staleness is tolerable |
| User profile | 5–15 min | + explicit invalidation on update |
| Permissions / roles | **1–5 min max** | Security: a revoked permission must take effect quickly |
| Search results | 1–5 min | Freshness matters; results are expensive |
| Session data | Sliding, = session timeout | Extend on each access |
| Prices / inventory | Seconds, or never cache | Business-critical accuracy |
| Computed aggregates | Match the business's tolerance | Ask: "how fresh does this report need to be?" |
| Negative results (not found) | 30–60 s | Short, to prevent penetration (§11.8) |

> **Security rule: never cache authorisation decisions for long.** If an admin revokes access and it takes 30 minutes to apply, that is a security incident waiting to be written up. 60 seconds, plus explicit invalidation on permission change.

### Add jitter to TTLs

```python
# WRONG — 10,000 keys created at deploy time all expire at exactly the same second
await cache.set(key, value, ttl=300)

# RIGHT — spread expiry over a window
await cache.set(key, value, ttl=300 + random.randint(-30, 30))
```

Without jitter you get a synchronised mass expiry — a **cache avalanche** (§11.7).

---

## 11.5 Cache keys — design them properly

```python
# BAD
key = f"user{user_id}"                       # no namespace, collides, unreadable

# GOOD — structured, namespaced, versioned
key = f"app:v2:customer:{tenant_id}:{customer_id}"
key = f"app:v2:sessions:tenant={tenant_id}:status=pending:page={cursor}"
```

**Rules:**

1. **Namespace everything** — `app:entity:id`. Colons are the Redis convention and make `SCAN app:v2:customer:*` possible.
2. **Include a schema version** (`v2`). When your serialised shape changes, bump the version — the entire old cache is instantly orphaned and expires on its own. **This is the cleanest cache-busting technique there is, and it avoids deserialisation crashes after a deploy.**
3. **Include the tenant ID.** A missing tenant in a cache key is a cross-tenant data leak — one of the most serious bugs you can ship.
4. **Include everything that varies the result** — user, locale, permissions, feature flags. A key that ignores a variable is a correctness bug.
5. **Keep keys deterministic** — sort query parameters before hashing them.

```python
def build_key(prefix: str, **params) -> str:
    """Deterministic key from arbitrary parameters."""
    canonical = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] is not None)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"app:v2:{prefix}:{digest}"
```

> **The #1 caching security bug: caching a user-specific response under a key that is not user-specific.** User A's dashboard is served to User B. Include the identity in the key, and include `Vary: Authorization` on HTTP caches (Chapter 08).

---

## 11.6 Cache invalidation strategies

| Strategy | How | When to use |
|----------|-----|-------------|
| **TTL only** | Let it expire | Simplest; when bounded staleness is acceptable — **the default** |
| **Explicit delete on write** | Invalidate the key when the entity changes | When freshness matters and you control all writes |
| **Key versioning** | Include a version in the key; bump to orphan everything | Schema changes, bulk invalidation |
| **Tag-based** | Keys carry tags; invalidate all keys with tag X | Complex dependency graphs (CDNs, Varnish, some Redis patterns) |
| **Event-driven** | Consume change events (CDC/outbox) and invalidate | Multiple writers, or writers outside your service — **the robust answer at scale** |
| **Generation counter** | `cache:gen:customers = 7`; include it in every key | Invalidate a whole class of keys atomically |

```python
# Generation-counter invalidation — invalidate everything for a tenant in O(1)
async def get_key(tenant_id: str, suffix: str) -> str:
    gen = await redis.get(f"gen:tenant:{tenant_id}") or "0"
    return f"app:v2:t{tenant_id}:g{gen}:{suffix}"

async def invalidate_tenant(tenant_id: str) -> None:
    await redis.incr(f"gen:tenant:{tenant_id}")   # every old key is now unreachable
    # old keys are never read again and expire on their own — no scanning, no deletes
```

> **Never use `KEYS pattern*` in production Redis** — it is O(N), blocks the single-threaded server, and has caused real outages. Use `SCAN` (cursor-based), or design so you never need to scan: generation counters and versioned keys make scanning unnecessary.

---

## 11.7 The three classic cache disasters 🟢

These have names because they have taken down real systems. Know all three.

### 1. Cache Stampede (Thundering Herd / Dog-piling)

```
A popular key expires at t=0.
At t=0, 5,000 concurrent requests all miss.
All 5,000 query the database for the SAME value, simultaneously.
Database dies. Nothing can repopulate the cache. The site is down.
```

**Fix A — Locking (single-flight):** only one request recomputes; the others wait or serve stale.

```python
async def get_with_lock(key: str, loader, ttl: int = 300):
    if (v := await cache.get(key)) is not None:
        return v

    lock_key = f"lock:{key}"
    got_lock = await redis.set(lock_key, "1", nx=True, ex=10)

    if got_lock:
        try:
            value = await loader()                          # only ONE request does this
            await cache.set(key, value, ttl=ttl + jitter())
            return value
        finally:
            await redis.delete(lock_key)
    else:
        # Someone else is loading. Wait briefly, then re-check.
        for _ in range(20):
            await asyncio.sleep(0.05)
            if (v := await cache.get(key)) is not None:
                return v
        return await loader()      # last resort — do not wait forever
```

**Fix B — Probabilistic early expiry (XFetch):** each request has a small, increasing chance of refreshing early, so refreshes are naturally spread out and no key ever hard-expires under load.

```python
def should_refresh_early(ttl_remaining: float, compute_time: float, beta: float = 1.0) -> bool:
    # The closer to expiry, and the more expensive to compute, the higher the chance
    return ttl_remaining - compute_time * beta * math.log(random.random()) <= 0
```

**Fix C — Serve stale while revalidating:** keep two TTLs — a "soft" one that triggers a background refresh, and a "hard" one that is the real expiry. Users always get an instant answer.

**Fix D — Never let hot keys expire:** refresh them on a schedule from a background job.

> **For any key that is both expensive to compute and heavily read, stampede protection is not optional.**

### 2. Cache Penetration

```
An attacker (or a buggy client) requests keys that DO NOT EXIST.
Every request misses the cache → hits the database → finds nothing → caches nothing.
The cache provides zero protection. The database takes 100% of the traffic.
```

**Fix A — Negative caching:** cache the "not found" result, with a short TTL.

```python
NULL_SENTINEL = "\x00__NOT_FOUND__"

if cached == NULL_SENTINEL:
    raise NotFound(key)
...
if row is None:
    await cache.set(key, NULL_SENTINEL, ttl=60)     # short! the item may be created soon
    raise NotFound(key)
```

**Fix B — Validate before querying:** if IDs are UUIDs, reject anything that is not a valid UUID at the edge. Free, and it stops most scanning attacks.

**Fix C — Bloom filter:** a compact probabilistic structure that answers "definitely not present" or "possibly present". If the filter says no, skip the database entirely.

```python
# 10 million keys, 1% false positive rate ≈ 12 MB of memory
if not bloom.might_contain(customer_id):
    raise NotFound(customer_id)        # certain it does not exist — DB never touched
```

**Fix D — Rate limit** by client on miss-heavy endpoints.

### 3. Cache Avalanche

```
A large number of keys expire at the same moment (or the whole cache restarts).
Everything misses at once. The database receives its full uncached load.
The database cannot serve it. Everything times out.
```

**Causes:** all keys populated at the same time with the same TTL (a deploy, a warmup script); a Redis restart or failover; a cache eviction storm when `maxmemory` is reached.

**Fixes:**
1. **TTL jitter** (§11.4) — spreads expiry
2. **Cache warming** — prepopulate hot keys before taking traffic
3. **Two-tier caching** — L1 local cache absorbs some traffic while L2 is cold
4. **Circuit breaker on the database** — shed load rather than collapse (Chapter 05)
5. **Redis HA** — replicas + Sentinel/Cluster so a single node loss is not total loss
6. **Rate-limit cache repopulation** — cap how many concurrent misses may reach the database

> **Test this deliberately:** flush your cache in a staging environment under production-like load and see what happens. Most teams discover that their system cannot survive a cold cache — and they discover it in production.

---

## 11.8 Cache consistency — the honest picture

### The fundamental race in cache-aside

```
Time   Request A (read)           Request B (write)
 1     cache miss
 2     read DB → x = 1
 3                                UPDATE db SET x = 2
 4                                DELETE cache key
 5     SET cache x = 1   ← STALE VALUE WRITTEN AFTER THE INVALIDATION
```

The cache now holds `1` until the TTL expires, while the database holds `2`.

**Mitigations (in increasing order of effort):**

1. **A short TTL** — bounds the damage. Usually sufficient, and it is why you always set a TTL.
2. **Delayed double delete** — delete, write, wait ~500 ms, delete again. Crude but effective.
3. **Set with a version/timestamp check** — only write to the cache if your data is newer.
4. **Event-driven invalidation via CDC** — invalidate from the database's change log, which is strictly ordered. **This is the robust answer** and it also handles writes made by other services, batch jobs and DBAs.

```python
# CDC-driven invalidation — the write path doesn't have to remember to invalidate
async def on_database_change(change: ChangeEvent) -> None:
    if change.table == "customers":
        await cache.delete(f"app:v2:customer:{change.row['tenant_id']}:{change.row['id']}")
        await redis.incr(f"gen:tenant:{change.row['tenant_id']}")   # bulk invalidate views
```

> **Accept this reality:** a cache is *by definition* an eventually-consistent copy. If a piece of data cannot tolerate **any** staleness, do not cache it — read it from the source. Trying to build a perfectly consistent cache is how people spend six months and still have bugs.

### What to never cache

- Authentication credentials and secrets
- Anything where a stale read causes financial loss (account balance at the moment of a transfer)
- Data subject to immediate legal deletion requirements, unless you can purge it reliably
- Highly personalised data under a shared key (the cross-tenant leak)

---

## 11.9 CDN caching 🟡

A CDN is a cache at layer 2 — geographically distributed, and it removes traffic from your infrastructure entirely.

```
User (Dhaka) ──► CDN edge (Singapore) ──► [miss] ──► Origin (Frankfurt)
                    ↑                                     │
                    └───── cached for future users ───────┘
```

### What to put on a CDN

| Content | Cacheable? | Strategy |
|---------|-----------|----------|
| Images, video, fonts | ✅ Perfectly | Long TTL + content-hashed filenames (`app.8f3a2b.js`) → `immutable` |
| CSS/JS bundles | ✅ | Same — versioned filenames mean you never invalidate, you just deploy a new name |
| Public API GETs | ✅ | Short TTL + `stale-while-revalidate` |
| HTML pages (public) | ✅ | Short TTL, or ESI/edge rendering |
| User-specific pages | ⚠️ | Only with `private` — must never be cached at the edge |
| POST/PUT/DELETE | ❌ | Never |
| Authenticated API responses | ❌ usually | Unless `private` + `Vary: Authorization` is exactly right |

```http
# Versioned static asset — cache forever, never revalidate
Cache-Control: public, max-age=31536000, immutable

# Public API response — 60 s fresh, serve stale for 5 min while refreshing
Cache-Control: public, max-age=60, stale-while-revalidate=300, stale-if-error=86400

# User-specific — browser only, never a shared cache
Cache-Control: private, max-age=0, must-revalidate
Vary: Authorization
```

**`stale-if-error` is underrated:** if your origin is down, the CDN keeps serving the last good response for up to a day. Your site stays up during an origin outage. That is a resilience feature disguised as a caching header.

**Cache invalidation on a CDN:** purging is slow (seconds to minutes) and often rate-limited. **The professional approach is to never purge** — use content-hashed URLs so a new deploy produces new URLs, and the old ones simply age out.

**Other CDN wins:** TLS termination at the edge, DDoS absorption, WAF, compression (Brotli), HTTP/3, and image transformation on the fly.

---

## 11.10 Monitoring your cache 🟢

**Metrics you must have:**

| Metric | Why | Alert on |
|--------|-----|----------|
| **Hit ratio** | The headline effectiveness number | A sudden drop (indicates a key-format change or a deploy bug) |
| **Miss latency** | How bad a miss really is | p99 growth |
| **Eviction rate** | Memory pressure — the cache is too small | Any sustained evictions on a cache you rely on |
| **Memory used / maxmemory** | Capacity | > 80% |
| **Key count / size distribution** | Finding fat keys | Any single key > a few MB |
| **Connection count / errors** | Client-side health | Errors > 0 |
| **Redis latency (`--latency`, slowlog)** | Blocking commands | p99 > 1 ms |

```python
# Instrument every cache access — you cannot tune what you cannot see
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

**Interpreting hit ratio:**

```
< 50%   → Something is wrong. Wrong keys? TTL too short? Too much eviction?
50-80%  → Mediocre. Look at what is missing and why.
80-95%  → Good.
> 95%   → Excellent. Now look at whether the remaining misses are expensive.
```

Remember the maths from Chapter 04: going from 95% to 99% removes **80% of the remaining database load**. The last few percent are where the value is.

---

## 11.11 Common mistakes

1. **No TTL** — a bug in invalidation becomes permanent stale data
2. **No jitter** — synchronised mass expiry → avalanche
3. **No stampede protection** on expensive hot keys → the database dies at expiry
4. **Caching user-specific data under a shared key** — cross-user/cross-tenant data leak. **The most dangerous caching bug.**
5. **`KEYS *` in production** — blocks single-threaded Redis, takes down the cache
6. **Updating the cache on write instead of invalidating** — race condition writes a stale value permanently
7. **No negative caching** — penetration attacks go straight to the database
8. **Caching authorisation for too long** — revoked access still works
9. **Treating Redis as a database** — no persistence configured, then surprise when a restart loses everything
10. **`maxmemory-policy noeviction`** (the default) — Redis starts **rejecting writes** when full instead of evicting
11. **Never testing a cold cache** — discovering in production that the system cannot start without a warm cache
12. **Caching before measuring** — adding complexity to a query that was never slow
13. **Serialising huge objects** — a 5 MB cache value costs more to fetch and deserialise than the query did
14. **No schema version in the key** — after a deploy, old cached objects fail to deserialise and crash the app

---

## 11.12 Architect's checklist

- [ ] The three questions answered for each cache: read:write ratio, staleness tolerance (a number), cold-cache behaviour
- [ ] TTL set on **every** key, with jitter
- [ ] Key format: namespaced, schema-versioned, tenant-scoped, deterministic
- [ ] No user-specific data cached under a shared key; HTTP caches set `Vary` correctly
- [ ] Stampede protection on expensive/hot keys (lock, early expiry, or serve-stale)
- [ ] Negative caching for not-found results, with a short TTL
- [ ] Invalidation strategy chosen and documented (TTL / delete / generation / CDC)
- [ ] `maxmemory` and an eviction policy configured — not `noeviction`
- [ ] Redis persistence configured to match the role (disposable vs derived vs source of truth)
- [ ] Redis HA (replica + Sentinel or Cluster) if the system cannot survive a cold cache
- [ ] Cold-cache load test performed; the system survives a full flush under load
- [ ] Hit ratio, evictions, memory, and miss latency monitored and alerted
- [ ] Authorisation data cached for ≤ 60 s, with explicit invalidation on change
- [ ] CDN: content-hashed static assets, `immutable`, `stale-while-revalidate`, `stale-if-error`
- [ ] Circuit breaker between the app and the database for the cache-down case

---

## 11.13 Self-test

1. What are the three questions to ask before adding a cache?
2. Why invalidate rather than update the cache on write? Draw the race.
3. Cache-aside vs write-through vs write-behind — give a use case for each.
4. Why must every TTL have jitter?
5. Explain cache stampede and give three different fixes.
6. Explain cache penetration. What is a Bloom filter's role?
7. Explain cache avalanche. Name four defences.
8. Design a cache key for "a tenant's pending sessions, page 3, sorted by date". What must it include and why?
9. What is the most dangerous caching security bug, and how do you prevent it?
10. Why is `KEYS *` forbidden in production, and what do you use instead?
11. What does a generation counter give you that key-by-key deletion does not?
12. What do `stale-while-revalidate` and `stale-if-error` do, and why is the second a resilience feature?
13. Your hit ratio is 95%. Why is pushing to 99% worth the effort? Show the maths.
14. Which data should never be cached?

---

## 11.14 Key takeaways

- **Ask the three questions first.** Most bad caches skip them.
- **Cache-aside + TTL + invalidate-on-write** covers 90% of cases
- **Always set a TTL, always add jitter.** TTL is your bug insurance.
- **Key design is where correctness and security live** — namespace, version, tenant, and everything that varies the result
- **Stampede, penetration and avalanche** are named disasters; defend against all three explicitly
- **A cache is an eventually-consistent copy, by definition.** Data that tolerates no staleness must not be cached.
- **Never cache authorisation for long**
- **Test the cold cache under load** — if the system cannot survive a flush, the cache is not a cache, it is a dependency
- **Hit ratio is the headline metric** — and the last few percent are the valuable ones
- **On a CDN, never purge — version the URL instead**

---

**Next:** [Chapter 12 — Data Architecture](12-data-architecture.md)
