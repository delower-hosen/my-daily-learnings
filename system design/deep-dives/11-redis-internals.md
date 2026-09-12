# Deep Dive 11 — Redis Internals

**Prerequisite:** [Chapter 10 §10.3](../10-nosql-architecture.md) · [Chapter 11 — Caching](../11-caching.md)

**What the map said:** *"Redis is single-threaded, so every command is atomic. Never run `KEYS *`. Treat it as a cache that can be wiped at any moment unless you configure otherwise."*

**What this deep dive does:** explains what "single-threaded" actually means in Redis 7 (it is no longer simply true), takes apart every data-structure encoding and the thresholds that switch between them, walks the expiration and eviction algorithms including the sampling that makes them approximate, explains why `fork()` for a snapshot can block a 64 GB Redis for a full second and how Transparent Huge Pages make it ten times worse, traces a Redis Cluster failover to the exact window where acknowledged writes are lost, and ends with the latency diagnosis procedure.

---

## Contents

```
1.  "Single-threaded" — what that actually means in Redis 7
2.  The event loop
3.  Object representation: robj and SDS
4.  ⭐ Encodings: the thresholds that silently change your memory profile
5.  Traced scenario — a hash crossing the encoding threshold
6.  ⭐ Expiration: lazy plus active sampling
7.  ⭐ Eviction: approximated LRU and LFU
8.  Persistence 1 — RDB and the fork
9.  ⭐ The fork latency problem, and Transparent Huge Pages
10. ⭐ Copy-on-write memory amplification
11. Persistence 2 — AOF and the rewrite
12. Replication: full sync, partial sync, the backlog
13. ⭐ Why Redis replication can lose acknowledged writes
14. Sentinel
15. Cluster: hash slots, MOVED and ASK
16. ⭐ Traced scenario — a cluster failover losing writes
17. Hash tags and multi-key operations
18. Pipelining vs transactions vs Lua vs Functions
19. ⭐ The commands that block the world
20. Streams internals
21. Memory fragmentation and active defrag
22. ⭐ Latency diagnosis: the procedure
23. Monitoring
24. Tuning
25. What an architect takes from this
```

---

## 1. "Single-threaded" — what that actually means in Redis 7

The claim is repeated everywhere and it is now only partly true. The distinction matters for capacity planning.

```
⭐ COMMAND EXECUTION IS STILL SINGLE-THREADED.
   One command runs at a time, to completion, on the main thread.
   ⭐ This is what makes every command atomic, and it is unchanged.

⭐ BUT REDIS 6.0+ IS A MULTI-THREADED PROCESS:

  io-threads N          ⭐ parallel socket READ + protocol PARSE,
                           and parallel response WRITE
  lazyfree threads      ⭐ background freeing of large objects (§19)
  bio threads           background fsync, file close, AOF fsync
```

```
        ┌──────────────────────────────────────────────────────┐
        │  io-thread 1 ─┐                                       │
        │  io-thread 2 ─┼─► read + parse ─┐                     │
        │  io-thread 3 ─┘                  ▼                    │
        │                      ⭐ MAIN THREAD: EXECUTE          │
        │                         (strictly serial)             │
        │                                  │                    │
        │  io-thread 1 ─┐                  ▼                    │
        │  io-thread 2 ─┼─◄ format + write ┘                    │
        │  io-thread 3 ─┘                                       │
        ├──────────────────────────────────────────────────────┤
        │  lazyfree threads: free large objects asynchronously   │
        │  bio threads: fsync, close, AOF                        │
        └──────────────────────────────────────────────────────┘
```

```properties
io-threads 4              # ⭐ typically cores/2 to cores-1; 1 = disabled
io-threads-do-reads yes   # ⭐ also parallelise reads (was off by default in 6.0)
```

```
⭐ WHEN io-threads HELPS:
   • Large values (the protocol write is the bottleneck, not the lookup)
   • Many concurrent connections
   • ⭐ TLS enabled — encryption is a per-connection CPU cost that
     parallelises well
   Measured: 1.5-3× throughput on large-value workloads.

⭐ WHEN IT DOES NOT HELP:
   • Small values and simple commands — the bottleneck is the single
     execution thread, and io-threads adds coordination overhead
   • ⭐ It does NOT make slow commands faster. A KEYS * still blocks
     everything (§19).
```

> **The practical consequence: Redis scales vertically with cores only up to a point, because execution is still serial.** Beyond that you shard (Redis Cluster, §15) — which is why Redis Cluster exists and why "just get a bigger machine" stops working sooner than for PostgreSQL.

---

## 2. The event loop

```c
/* ae.c — the entire architecture, simplified */
while (!server.shutdown_asap) {
    /* 1. ⭐ TIMER EVENTS — serverCron, ~hz times per second (default 10) */
    processTimeEvents();       /* expiration cycle (§6), stats, replication
                                  cron, rehashing, defrag... */

    /* 2. ⭐ BLOCK in epoll_wait / kqueue until a socket is readable */
    numevents = aeApiPoll(eventLoop, tvp);

    /* 3. For each ready socket: read, parse, ⭐ EXECUTE, queue the reply */
    for (j = 0; j < numevents; j++)
        fe->rfileProc(eventLoop, fd, fe->clientData, mask);

    /* 4. Write queued replies */
    handleClientsWithPendingWrites();
}
```

### The consequences

```
⭐ 1. EVERY COMMAND IS ATOMIC, for free. No locks, no CAS, no races.
      INCR, SETNX, LPUSH, and Lua scripts are all race-free by construction.
      ⭐ This is why Redis is such a good primitive for rate limiters,
         counters and coordination (Chapter 05 §5.8).

⭐ 2. ONE SLOW COMMAND BLOCKS EVERYTHING.
      There is no preemption. A 3-second KEYS * means every other client
      waits 3 seconds. ⭐ This is Redis's single biggest operational hazard (§19).

⭐ 3. hz CONTROLS BACKGROUND WORK GRANULARITY.
      hz 10 (default) = serverCron runs every 100 ms.
      ⭐ Raising it to 100 makes expiration and other background work
         more responsive, at the cost of more CPU when idle.
```

```properties
hz 10                    # background task frequency
dynamic-hz yes           # ⭐ scale hz with the number of clients
```

---

## 3. Object representation: robj and SDS

Every value in Redis is wrapped in a `redisObject`.

```c
typedef struct redisObject {
    unsigned type:4;        /* STRING, LIST, SET, ZSET, HASH, STREAM... */
    unsigned encoding:4;    /* ⭐ the physical representation (§4)        */
    unsigned lru:24;        /* ⭐ LRU clock, or LFU counter+decay (§7)    */
    int refcount;           /* shared objects (small integers 0-9999)    */
    void *ptr;              /* the actual data                           */
} robj;                     /* ⭐ 16 bytes of overhead per object         */
```

### SDS — Simple Dynamic String

Redis does not use C strings.

```c
struct sdshdr8 {
    uint8_t len;        /* ⭐ O(1) STRLEN                       */
    uint8_t alloc;      /* ⭐ capacity, for amortised APPEND     */
    unsigned char flags;/* which header variant (5/8/16/32/64)  */
    char buf[];         /* ⭐ binary-safe — may contain \0       */
};
```

```
⭐ WHY IT MATTERS:
   • STRLEN is O(1), not O(n)
   • ⭐ BINARY SAFE — you can store protobuf, images, anything
   • APPEND pre-allocates (doubling up to 1 MB, then +1 MB), so
     repeated APPEND is amortised O(1) rather than O(n²)
   • ⭐ Five header sizes (sdshdr5..64) so a short string carries
     only 3 bytes of header, not 16
```

### The memory overhead nobody accounts for

```
⭐ SET user:1000 "x"     — a ONE-BYTE value

  dictEntry (key, value, next pointer)     ~32 bytes (jemalloc bin: 32)
  key SDS ("user:1000", 9 bytes + hdr)     ~16 bytes
  robj                                      16 bytes
  value SDS ("x")                          ~16 bytes
  hash table slot amortised                 ~8 bytes
  ────────────────────────────────────────────────
  ⭐ ~88 BYTES for a 1-byte value.
```

```
⭐ THE PRACTICAL RULE: 10 million small keys ≈ 900 MB, almost all
   overhead. If you are storing millions of tiny values, ⭐ USE A HASH
   instead — a small hash is a listpack (§4) with ~5 bytes per field
   instead of ~88.

  ❌ SET user:1000:name "D"  SET user:1000:age "34"  ...  (88 B each)
  ✅ HSET user:1000 name "D" age "34" ...               (⭐ ~5 B per field)
```

This is one of the highest-value Redis memory optimisations and it is frequently missed.

---

## 4. ⭐ Encodings: the thresholds that silently change your memory profile

Every Redis type has **two or more physical representations**. Redis switches automatically, and the switch is **one-way** — it never converts back.

```bash
redis-cli OBJECT ENCODING mykey
```

| Type | Small encoding | Large encoding | Threshold |
|------|---------------|----------------|-----------|
| **String** | `int` (a `long`) / `embstr` (single allocation) | `raw` (separate SDS) | ⭐ `embstr` up to **44 bytes** |
| **List** | `listpack` | `quicklist` (linked list of listpacks) | `list-max-listpack-size 128` |
| **Hash** | `listpack` | `hashtable` | `hash-max-listpack-entries 128`, `hash-max-listpack-value 64` |
| **Set** | `intset` (all integers) / `listpack` | `hashtable` | `set-max-intset-entries 512`, `set-max-listpack-entries 128` |
| **ZSet** | `listpack` | ⭐ `skiplist` + `hashtable` | `zset-max-listpack-entries 128`, `zset-max-listpack-value 64` |

### listpack — the compact representation

```
⭐ A listpack is a single contiguous byte array of length-prefixed entries.

  [total-bytes][num-elements][entry][entry][entry]...[end-byte]

  Each entry: [encoding+length][data][backlen]

⭐ PROPERTIES:
   ✅ Extremely compact — no pointers, no per-element allocation
   ✅ ⭐ Cache-friendly: the whole structure is one contiguous block
   ❌ ⭐ O(n) lookup — every operation scans linearly
   ❌ O(n) insert in the middle (memmove)
```

```
⭐ WHY THE THRESHOLDS EXIST: for small collections, an O(n) scan of a
   contiguous 200-byte block is FASTER than an O(1) hash lookup that
   chases pointers across cache lines. Memory locality beats
   algorithmic complexity at small n.

⭐ listpack REPLACED ziplist in Redis 7.0. ziplist stored a
   "previous entry length" field that could cascade: growing one entry
   past 254 bytes forced every subsequent entry to grow its prev-length
   field from 1 byte to 5, ⭐ potentially rewriting the whole structure
   in a chain reaction. listpack's backlen removes that failure mode.
```

### The zset double structure

```
⭐ A large ZSET maintains TWO structures simultaneously:

  1. HASH TABLE:  member → score        ⭐ O(1) ZSCORE
  2. SKIP LIST:   ordered by score      ⭐ O(log n) ZRANGEBYSCORE,
                                           O(log n) ZRANK

  Both hold a pointer to the same member SDS (refcounted), so the
  member string is not duplicated — but the ⭐ structural overhead is
  roughly 2× that of a plain hash.
```

---

## 5. Traced scenario — a hash crossing the encoding threshold

The conversion is silent, one-way, and can multiply memory by 5×.

```bash
redis-cli
> CONFIG GET hash-max-listpack-entries
1) "hash-max-listpack-entries"
2) "128"

# ── 128 fields: still a listpack ──
> HSET session:abc f1 v1 f2 v2 ... f128 v128
> OBJECT ENCODING session:abc
"listpack"
> MEMORY USAGE session:abc
(integer) ⭐ 1848        # ~14 bytes per field

# ── one more field ──
> HSET session:abc f129 v129
> OBJECT ENCODING session:abc
⭐ "hashtable"
> MEMORY USAGE session:abc
(integer) ⭐ 9456        # ⭐ 5× MORE, for 1 more field (~73 bytes per field)

# ── remove it again ──
> HDEL session:abc f129
> OBJECT ENCODING session:abc
⭐ "hashtable"           # ⭐ IT NEVER CONVERTS BACK
> MEMORY USAGE session:abc
(integer) 9312           # ⭐ still 5× the listpack size
```

### What this means operationally

```
⭐ 1. THE CONVERSION IS ONE-WAY. Once a collection exceeds the threshold
      even momentarily, it stays in the expensive encoding for its
      entire lifetime. Only DEL + recreate reverts it.

⭐ 2. A SINGLE OVERSIZED VALUE CONVERTS THE WHOLE COLLECTION.
      hash-max-listpack-value is 64 BYTES. One field with a 65-byte
      value converts a 10-field hash to a hashtable.

⭐ 3. MEMORY CAN JUMP DISCONTINUOUSLY. A gradual workload change that
      pushes many hashes past 128 fields produces a sudden step in
      used_memory, not a gradual rise.
```

### Tuning the thresholds

```properties
# ⭐ Raising them trades CPU (O(n) scans) for memory
hash-max-listpack-entries 512     # from 128
hash-max-listpack-value 128       # from 64
zset-max-listpack-entries 256
set-max-listpack-entries 256
list-max-listpack-size 256
```

```
⭐ WHEN TO RAISE: many small collections, memory-constrained, and
   collections are read whole (HGETALL) rather than field by field.
   A linear scan of 512 entries is ~2 µs — negligible.

⭐ WHEN NOT TO: you do single-field lookups (HGET) on large hashes.
   O(n) at n=512 on every lookup, on the single execution thread,
   is a real cost at high QPS.
```

```bash
# ⭐ Audit your actual encodings — this frequently finds easy wins
redis-cli --scan --pattern 'session:*' | head -1000 | while read k; do
  echo "$(redis-cli OBJECT ENCODING "$k") $(redis-cli MEMORY USAGE "$k") $k"
done | sort | uniq -c -w 12
```

---

## 6. ⭐ Expiration: lazy plus active sampling

Redis does **not** delete a key at the moment it expires. Understanding what it actually does explains several confusing behaviours.

### Strategy 1 — lazy expiration

```c
/* Every key access goes through this */
robj *lookupKeyRead(redisDb *db, robj *key) {
    if (expireIfNeeded(db, key) == KEY_EXPIRED)
        return NULL;      /* ⭐ deleted on access, and reported as missing */
    return dictFetchValue(db->dict, key->ptr);
}
```

```
⭐ THE PROBLEM WITH LAZY ALONE: a key that expires and is never
   accessed again occupies memory FOREVER.
```

### Strategy 2 — active expiration cycle

```
Runs ~hz times per second (10/s by default), inside serverCron:

  REPEAT:
    1. ⭐ Sample 20 RANDOM keys from the `expires` dictionary
       (ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP)
    2. Delete those that have expired
    3. ⭐ IF MORE THAN 25% WERE EXPIRED → repeat immediately
    4. Stop if 25% of the CPU time slice is consumed
       (ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC)
```

```
⭐ THE 25% RULE IS THE KEY DESIGN CHOICE:

  It is a statistical bound. If fewer than 25% of a random sample are
  expired, then ⭐ probabilistically fewer than ~25% of all keys with
  TTLs are expired — which is deemed acceptable, and the cycle stops.

⭐ SO: up to ~25% of your TTL'd keys may be expired-but-still-in-memory
   at any moment. `used_memory` counts them. `DBSIZE` counts them.
```

### The three consequences that confuse people

```
⭐ 1. `used_memory` IS HIGHER THAN THE LIVE DATA SIZE.
      Expired keys linger. This is normal, not a leak.

⭐ 2. `DBSIZE` COUNTS EXPIRED KEYS.
      But `SCAN` filters them (it calls expireIfNeeded), so SCAN and
      DBSIZE disagree. Both are "correct".

⭐ 3. KEYSPACE NOTIFICATIONS FIRE LATE.
      The `expired` event is emitted when the key is ACTUALLY DELETED —
      lazily on access, or by the active cycle — ⭐ NOT at the TTL moment.
      A key with a 10-second TTL that nobody touches may fire its
      expired event seconds or minutes later.

      ⭐ NEVER build a scheduler or a timeout mechanism on Redis expired
      events. The delay is unbounded in the worst case.
```

### Replicas and expiration ⭐

```
⭐ REPLICAS DO NOT EXPIRE KEYS THEMSELVES.

  The master expires a key, then propagates an explicit DEL (or UNLINK)
  to the replicas.

⭐ WHY: to guarantee that master and replica agree. If replicas expired
   independently, clock skew (Deep Dive 02) would cause divergence.

⭐ THE OBSERVABLE CONSEQUENCE: a logically-expired key can still be
   present on a replica until the master's DEL arrives. Redis handles
   this by having replicas return nil for logically-expired keys on
   read — but ⭐ `DBSIZE` and `RANDOMKEY` on a replica can still count them.
```

---

## 7. ⭐ Eviction: approximated LRU and LFU

```properties
maxmemory 8gb
maxmemory-policy noeviction     # ⭐ THE DEFAULT, and it is dangerous
maxmemory-samples 5
```

### The policies

| Policy | Behaviour |
|--------|-----------|
| ⭐ `noeviction` | **Return an error on writes when full.** The default. |
| `allkeys-lru` | Evict least-recently-used from all keys |
| `volatile-lru` | LRU, but ⭐ **only keys with a TTL** |
| `allkeys-lfu` | ⭐ Least-**frequently**-used (Redis 4.0+) |
| `volatile-lfu` | LFU among TTL'd keys |
| `allkeys-random` | Random |
| `volatile-random` | Random among TTL'd keys |
| `volatile-ttl` | Shortest remaining TTL first |

```
⭐ THE noeviction TRAP:

  Redis's DEFAULT is noeviction. A cache configured with maxmemory but
  the default policy does not evict — it starts returning:

      (error) OOM command not allowed when used memory > 'maxmemory'

  ⭐ Your cache stops accepting writes instead of making room.
     Chapter 11 §11.11 listed this; here is why it happens.

⭐ AND THE volatile-* TRAP: if you use volatile-lru but some keys have
   no TTL, Redis cannot evict those. If ALL keys lack a TTL, volatile-lru
   behaves exactly like noeviction.
```

### ⭐ Approximated LRU — why it is approximate

```
A true LRU requires a doubly-linked list of every key, reordered on
every access:
    ⭐ 16 extra bytes per key (two pointers) — enormous at 100 M keys
    ⭐ pointer churn on every single read

⭐ REDIS INSTEAD: each robj carries a 24-bit LRU CLOCK (§3).
   On eviction, sample `maxmemory-samples` random keys and evict the
   one with the oldest clock.
```

```
⭐ ACCURACY vs maxmemory-samples:

   samples=5  (default): good, with visible errors on the tail
   samples=10:           ⭐ nearly indistinguishable from true LRU
   samples=3:            noticeably worse

⭐ Redis 3.0+ also maintains a POOL of good eviction candidates across
   invocations, which improves quality substantially at the same
   sample count.
```

```properties
maxmemory-samples 10     # ⭐ a cheap, worthwhile improvement
```

### LFU — and why it is often better for a cache

```
⭐ THE LRU PROBLEM: one large scan (a batch job, an analytics sweep)
   touches every key once and evicts your entire hot set.
   ⭐ LRU is not scan-resistant.

⭐ LFU tracks FREQUENCY instead, with an 8-bit counter per key:

   • ⭐ LOGARITHMIC increment — the higher the counter, the less
     likely an access increments it. This lets 8 bits represent
     frequencies up to millions without saturating.
   • ⭐ DECAY over time, so a formerly-hot key that went cold loses
     its counter and becomes evictable.
```

```properties
maxmemory-policy allkeys-lfu
lfu-log-factor 10        # ⭐ higher = slower counter growth = wider range
lfu-decay-time 1         # ⭐ minutes of idleness per counter decrement
```

```
⭐ CHOOSE LFU WHEN:
   • There is a stable hot set and periodic full scans
   • Access frequencies vary by orders of magnitude
   • ⭐ You have been bitten by a batch job flushing the cache

⭐ CHOOSE LRU WHEN:
   • Recency genuinely predicts future access (session data, feeds)
   • The working set shifts over time
```

```bash
# ⭐ Inspect a key's LFU counter or idle time
redis-cli OBJECT FREQ user:1000      # LFU counter (requires an lfu policy)
redis-cli OBJECT IDLETIME user:1000  # seconds idle (requires an lru policy)
```

---

## 8. Persistence 1 — RDB and the fork

```properties
save 900 1        # snapshot if ≥1 key changed in 900 s
save 300 10
save 60 10000
dbfilename dump.rdb
rdbcompression yes
rdbchecksum yes
```

### How `BGSAVE` works

```
1. ⭐ fork() — create a child process
2. ⭐ The CHILD sees a FROZEN, consistent view of memory at the moment
   of the fork, thanks to copy-on-write.
3. The child serialises everything to a temp file, then renames it.
4. The parent ⭐ CONTINUES SERVING CLIENTS THROUGHOUT.
```

```
⭐ THE ELEGANCE: a point-in-time consistent snapshot with no locking,
   no pausing, and no application-visible effect — implemented entirely
   by the kernel's COW machinery.

⭐ THE COST: §9 and §10.
```

### RDB characteristics

```
✅ ⭐ COMPACT — a binary format, typically much smaller than AOF
✅ ⭐ FAST TO LOAD — a 10 GB RDB loads far faster than replaying an AOF
✅ Good for backups and for seeding replicas
❌ ⭐ DATA LOSS WINDOW = the time since the last snapshot.
   With `save 60 10000`, you can lose up to 60 seconds.
❌ ⭐ The fork is a latency spike (§9)
```

---

## 9. ⭐ The fork latency problem, and Transparent Huge Pages

The most important Redis operational fact, and the cause of most mysterious latency spikes.

### Why fork is not free

```
⭐ fork() does NOT copy memory. But it MUST COPY THE PAGE TABLES.

  Page table size ≈ (memory / 4 KB) × 8 bytes

    1 GB Redis  →   262,144 pages → ~2 MB of page tables  → fork ~10 ms
   16 GB Redis  → 4,194,304 pages → ~32 MB                → fork ~200 ms
   ⭐ 64 GB Redis → 16,777,216 pages → ~128 MB            → ⭐ fork ~1 SECOND
```

```
⭐ DURING fork(), THE REDIS PROCESS IS COMPLETELY BLOCKED.
   Not slowed — blocked. Every client waits.

⭐ A 64 GB Redis doing a BGSAVE every 60 seconds has a ONE-SECOND
   STALL every minute. That is a p99.9 catastrophe, and the cause is
   invisible in Redis's own command latency metrics.
```

```bash
# ⭐ Measure it directly
redis-cli INFO stats | grep latest_fork_usec
# latest_fork_usec:⭐847213        ← 847 ms. Every BGSAVE. Every replica sync.
```

### ⭐ Transparent Huge Pages — the multiplier

```
⭐ THP makes the kernel use 2 MB pages instead of 4 KB pages.

  ✅ Fewer page-table entries → FASTER fork
  ❌ ⭐ BUT COW now copies 2 MB AT A TIME instead of 4 KB.

  ⭐ Writing ONE BYTE to a page during a background save copies
     2 MB instead of 4 KB — a 512× amplification.

RESULT:
  • ⭐ Massive memory spikes during BGSAVE (§10)
  • ⭐ Severe, erratic latency as the parent blocks on 2 MB copies
  • Redis logs a warning about it at startup, which people ignore
```

```bash
# ⭐ DISABLE THP. This is not optional for a production Redis.
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Make it persistent
cat >> /etc/rc.local <<'EOF'
echo never > /sys/kernel/mm/transparent_hugepage/enabled
EOF

# Verify
cat /sys/kernel/mm/transparent_hugepage/enabled
# always [never] madvise      ⭐ "never" must be bracketed
```

**Redis prints a startup warning when THP is enabled.** It is one of the few log lines that genuinely means "fix this before going to production".

### Mitigations for fork latency

```
1. ⭐ KEEP INSTANCES SMALL. 8-16 GB per instance, sharded, rather than
   one 128 GB instance. This is the primary reason to shard Redis
   even when one machine could hold the data.

2. ⭐ DISABLE AUTOMATIC SNAPSHOTS on a pure cache:
       save ""
   and take backups from a replica instead.

3. ⭐ Run BGSAVE ONLY ON A REPLICA. The master never forks;
   the replica's latency spike affects nobody.

4. Disable THP (above).

5. On EC2, prefer instance types with fast memory; fork time is
   dominated by page-table copying, which is memory-bandwidth bound.
```

---

## 10. ⭐ Copy-on-write memory amplification

The second half of the fork problem, and the cause of surprise OOM kills.

```
At fork(), parent and child SHARE all memory pages.
⭐ When the PARENT writes to a page, the kernel COPIES it so the child
   keeps seeing the old version.

⭐ SO: memory usage during a BGSAVE grows in proportion to the
   WRITE RATE × SNAPSHOT DURATION.
```

```
⭐ WORKED EXAMPLE:

  Redis: 20 GB of data
  Write rate: touching 200 MB/s worth of distinct pages
  BGSAVE duration: 40 seconds

  ⭐ COW copies: 200 MB/s × 40 s = 8 GB of duplicated pages

  ⭐ PEAK RSS = 20 GB + 8 GB = 28 GB

  If maxmemory is 24 GB and the machine has 32 GB,
  ⭐ THE OOM KILLER TERMINATES REDIS MID-SNAPSHOT.
```

### The rules that follow

```
⭐ 1. NEVER SET maxmemory ABOVE ~50-60% OF SYSTEM RAM if you use
   RDB or AOF rewrite. The remainder is COW headroom.

   ⭐ This is the single most common Redis capacity mistake:
      maxmemory 60gb on a 64 GB machine → OOM on the first BGSAVE.

⭐ 2. WITH THP ENABLED (§9), amplification is up to 512× worse.
   Disable it.

⭐ 3. On a write-heavy instance, the amplification can EXCEED the
   dataset size. Measure it:
```

```bash
# ⭐ Watch RSS during a BGSAVE
redis-cli INFO memory | grep -E 'used_memory_human|used_memory_rss_human'
redis-cli BGSAVE
watch -n1 "redis-cli INFO memory | grep used_memory_rss_human"
```

```properties
# ⭐ This helps a great deal on Linux
vm.overcommit_memory = 1
```

```
⭐ WHY overcommit_memory=1 MATTERS: without it, fork() can FAIL outright
   with "Cannot allocate memory" when the kernel's heuristic decides the
   worst case (a full copy) will not fit — even though COW means it
   almost certainly will. Redis logs this and the background save simply
   never happens, silently leaving you with no persistence.
   ⭐ Redis warns about this at startup too.
```

---

## 11. Persistence 2 — AOF and the rewrite

```properties
appendonly yes
appendfsync everysec       # ⭐ always | everysec | no
appenddirname "appendonlydir"        # Redis 7.0+ multi-part AOF
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
aof-use-rdb-preamble yes   # ⭐ base is an RDB, increments are commands
```

### The durability dial

| `appendfsync` | Behaviour | Loss window |
|---------------|-----------|-------------|
| `always` | fsync on every write | ⭐ None — but throughput collapses to disk IOPS |
| **`everysec`** | fsync once per second, on a background thread | ⭐ **Up to 1 second** |
| `no` | Let the OS decide | ⭐ Up to 30 s (kernel writeback interval) |

```
⭐ everysec IS THE DEFAULT AND ALMOST ALWAYS THE RIGHT CHOICE.
   The fsync happens on a bio thread, so it does not block command
   execution — ⭐ UNLESS the previous fsync has not finished, in which
   case the main thread blocks waiting for it.

   ⭐ THIS IS WHY SLOW DISKS CAUSE REDIS LATENCY SPIKES even with
      everysec. Check:
```

```bash
redis-cli INFO stats | grep aof_delayed_fsync
# ⭐ aof_delayed_fsync:2841     ← the main thread blocked this many times
```

### AOF rewrite

```
The AOF grows forever (every write is appended). ⭐ REWRITE compacts it.

  1. ⭐ fork() — the same cost as BGSAVE (§9, §10)
  2. The child writes a COMPACT representation of the current dataset
     (with aof-use-rdb-preamble, ⭐ that base is an RDB)
  3. Meanwhile the parent buffers new writes
  4. The buffer is appended to the new AOF, and the files are swapped
```

```properties
auto-aof-rewrite-percentage 100     # ⭐ rewrite when the AOF has doubled
auto-aof-rewrite-min-size 64mb      # ...but not below this size
```

```
⭐ Redis 7.0 MULTI-PART AOF: instead of one file, a manifest plus a
   base file (RDB) plus incremental files. The rewrite no longer needs
   to hold the entire new AOF in a temp file, which removes a large
   disk-space spike.
```

### Choosing

```
⭐ PURE CACHE (data is rebuildable):
     save ""
     appendonly no
   ⭐ No persistence at all. No forks, no COW, no latency spikes.
      This is the correct configuration for most cache use, and
      people rarely set it explicitly.

⭐ SESSION STORE / SEMI-DURABLE:
     appendonly yes, appendfsync everysec
     save ""                    # ⭐ AOF only — avoid two fork sources
   Up to 1 second of loss, acceptable for sessions.

⭐ SYSTEM OF RECORD (think hard before doing this at all):
     appendonly yes, appendfsync always
     + replication + backups
   ⚠ And note you still do not get PostgreSQL's guarantees
     (Chapter 10 §10.3).
```

---

## 12. Replication: full sync, partial sync, the backlog

```
REPLICA                                      MASTER
  │ ⭐ PSYNC <replid> <offset> ──────────────►│
  │                                            │
  │  ┌─ if the offset is still in the backlog:│
  │  │  ⭐ +CONTINUE — send only the delta     │
  │  │                                         │
  │  └─ otherwise:                             │
  │     ⭐ +FULLRESYNC <replid> <offset>       │
  │     1. BGSAVE (⭐ a fork — §9)             │
  │     2. send the RDB                        │
  │     3. stream the buffered writes          │
```

### ⭐ The replication backlog — the setting that is too small

```properties
repl-backlog-size 1mb        # ⭐ THE DEFAULT. Far too small.
repl-backlog-ttl 3600
```

```
⭐ The backlog is a CIRCULAR BUFFER of recent writes on the master.
   If a replica reconnects and its offset is still inside the buffer,
   it gets a cheap PARTIAL resync.
   ⭐ If not, it gets a FULL resync — which forks the master, transfers
      the whole dataset, and hammers the network.

⭐ SIZE IT: repl-backlog-size ≥ write_rate × expected_disconnection_time

  Write rate 10 MB/s, network blips up to 60 s:
      ⭐ 10 MB/s × 60 s = 600 MB

  With the 1 MB default, a 0.1-second blip forces a FULL RESYNC.
```

```bash
# ⭐ Are you getting full resyncs you should not be?
redis-cli INFO stats | grep sync
# sync_full:⭐47                 ← full resyncs. Should be near zero.
# sync_partial_ok:3
# ⭐ sync_partial_err:47         ← partial attempts that FAILED → backlog too small
```

**`sync_full` climbing is one of the clearest signals in Redis** — it means every network hiccup is triggering a fork and a full dataset transfer on your master.

### PSYNC2 and replication IDs

```
⭐ Redis 4.0+ gives each dataset a REPLICATION ID, plus a SECONDARY ID
   retained after a failover.

  ⭐ CONSEQUENCE: when a replica is promoted to master, the other
     replicas can PARTIALLY resync to it — they recognise the
     secondary replication ID as their shared history.

  Before PSYNC2, every failover triggered a full resync of every
  remaining replica. On a large dataset that was a cascading outage.
```

---

## 13. ⭐ Why Redis replication can lose acknowledged writes

```
⭐ REDIS REPLICATION IS ASYNCHRONOUS. ALWAYS. There is no synchronous mode.

  1. Client sends SET k v
  2. ⭐ Master applies it and REPLIES +OK IMMEDIATELY
  3. ⭐ Only afterwards does it propagate to replicas

⭐ If the master dies between 2 and 3, the write is acknowledged and gone.
```

### `WAIT` — and what it does not give you

```bash
SET key value
WAIT 2 1000     # ⭐ block until 2 replicas ack, or 1000 ms elapse
# (integer) 2   ← the number that actually acked
```

```
⭐ WAIT IS NOT SYNCHRONOUS REPLICATION:
   • The write was ALREADY ACKNOWLEDGED before WAIT ran
   • ⭐ WAIT does not roll anything back if the count is insufficient —
     it just returns a smaller number
   • ⭐ It provides no guarantee about a failover that happens
     concurrently

⭐ WAIT is a SYNCHRONISATION POINT, not a durability primitive.
   It lets the APPLICATION decide what to do — but the window has
   already passed.
```

### `min-replicas-to-write` — the real protection

```properties
min-replicas-to-write 2      # ⭐ refuse writes below this replica count
min-replicas-max-lag 10      # ⭐ a replica counts only if its lag < 10 s
```

```
⭐ This is Redis's equivalent of Kafka's min.insync.replicas
   (Deep Dive 10 §10) and PostgreSQL's synchronous_standby_names
   (Deep Dive 07 §23):

   ⭐ REFUSE THE WRITE rather than accept one that is likely to be lost.

  It narrows the loss window substantially — but ⭐ it does not close it,
  because replication remains asynchronous. There is still a window
  between "master applied and acked" and "replica received".
```

> **Be clear-eyed about this when choosing Redis for anything durable.** It is an AP system with a genuine, unavoidable acknowledged-write loss window. Chapter 10 §10.3's advice — treat Redis as wipeable unless you have deliberately configured otherwise — comes directly from this section, and even "deliberately configured" does not get you PostgreSQL-grade durability.

---

## 14. Sentinel

```
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │Sentinel 1│   │Sentinel 2│   │Sentinel 3│   ⭐ 3+, odd
   └────┬─────┘   └────┬─────┘   └────┬─────┘
        └──── monitor ─┴──── monitor ─┘
                       │
              ┌────────▼────────┐
              │     MASTER      │──► replica ──► replica
              └─────────────────┘
```

```
1. ⭐ SDOWN (subjectively down): one Sentinel stops getting PINGs
   for down-after-milliseconds.
2. ⭐ ODOWN (objectively down): `quorum` Sentinels agree it is down.
3. ⭐ The Sentinels elect a LEADER (a Raft-like majority vote among
   themselves) to perform the failover.
4. The leader picks the best replica (by replica-priority, then
   replication offset, then run ID) and issues REPLICAOF NO ONE.
5. Other replicas are reconfigured to follow the new master.
6. Clients discover the new master by asking any Sentinel.
```

```properties
sentinel monitor mymaster 10.0.1.5 6379 2     # ⭐ quorum = 2
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
sentinel parallel-syncs mymaster 1            # ⭐ replicas resynced at once
```

```
⭐ THE TWO NUMBERS PEOPLE CONFUSE:
   • `quorum` — how many Sentinels must agree the master is DOWN
   • ⭐ A MAJORITY of Sentinels is required to ELECT A FAILOVER LEADER

   ⭐ With 3 Sentinels and quorum=2: 2 agree it is down, and 2 (a
      majority of 3) elect the leader. Consistent.
   ⭐ With 2 Sentinels: a majority is 2, so ANY Sentinel failure makes
      failover impossible. ⭐ Always run 3 or 5 — the same reasoning
      as Deep Dive 01 §3.
```

```
⭐ SENTINEL DOES NOT PREVENT DATA LOSS. The promoted replica is
   asynchronously replicated (§13), so it may be behind. Sentinel
   restores AVAILABILITY; it cannot restore lost writes.
```

---

## 15. Cluster: hash slots, MOVED and ASK

```
⭐ 16,384 HASH SLOTS, distributed across master nodes.

    slot = CRC16(key) mod 16384

  Node A: slots 0     - 5460
  Node B: slots 5461  - 10922
  Node C: slots 10923 - 16383
```

```
⭐ WHY 16384 AND NOT 65536: each node gossips a bitmap of the slots it
   owns in every heartbeat. 16384 bits = 2 KB; 65536 bits = 8 KB.
   With frequent gossip among many nodes, that difference is
   significant bandwidth. It also caps practical cluster size at
   ~1000 nodes, which was deemed sufficient.
```

### MOVED vs ASK ⭐

```
⭐ MOVED — a PERMANENT redirect. "Slot 8912 now lives on node B."
   GET foo
   (error) MOVED 8912 10.0.1.6:6379
   ⭐ The client should UPDATE ITS SLOT MAP and retry there.

⭐ ASK — a TEMPORARY redirect, used ONLY during slot migration.
   GET foo
   (error) ASK 8912 10.0.1.6:6379
   ⭐ The client retries on B, prefixing the command with ASKING —
      but does NOT update its slot map, because the slot has not
      finished moving.
```

```
⭐ THE DISTINCTION MATTERS during resharding:
   • Keys already migrated → ASK to the target
   • Keys not yet migrated → served by the source
   • ⭐ The client must handle both, or it will thrash its slot map
     and issue enormous numbers of redirects.

⭐ This is why you must use a CLUSTER-AWARE CLIENT. A plain client
   pointed at a cluster node "works" for some keys and fails for others.
```

### Gossip and failure detection

```
⭐ Nodes gossip over the CLUSTER BUS (the client port + 10000).

  PFAIL (possible failure): a node has not responded for
                            cluster-node-timeout
  ⭐ FAIL: a MAJORITY OF MASTERS agree it is PFAIL

  Then a replica of the failed master requests votes from the other
  masters; ⭐ a majority elects it, and it takes over the slots.
```

```properties
cluster-enabled yes
cluster-node-timeout 15000          # ⭐ the failure detection window
cluster-require-full-coverage yes   # ⭐ see below
cluster-replica-validity-factor 10
```

```
⭐ cluster-require-full-coverage = yes (the DEFAULT):
   If ANY slot has no owner, ⭐ THE ENTIRE CLUSTER REFUSES ALL QUERIES,
   including for slots that are perfectly healthy.

   ⭐ Losing one master WITHOUT A REPLICA takes down the whole cluster.

   Setting it to `no` lets the healthy slots continue serving —
   ⭐ a deliberate AP-over-CP choice. Decide it consciously; do not
      leave it at the default without knowing what it does.
```

---

## 16. ⭐ Traced scenario — a cluster failover losing writes

The window is real, bounded, and specified. Here it is precisely.

```
SETUP: Redis Cluster. Master M owns slots 0-5460, with replica R.
       cluster-node-timeout = 15000 ms.

t=0      Client writes SET user:42 "alice" to M.
         ⭐ M applies it and replies +OK. (§13 — async replication)

t=0.001  ⭐ THE NETWORK PARTITIONS M from the rest of the cluster.
         The write has NOT reached R.

t=0.001  ⭐ M IS STILL RUNNING and still reachable by some clients
         (those on M's side of the partition).
         ⭐ M CONTINUES ACCEPTING WRITES. It does not know it is isolated.

t=0-15   ⭐ Clients on M's side write hundreds of keys. All acknowledged.
         None reach R.

t=15     ⭐ cluster-node-timeout expires.
         • The majority side marks M as FAIL.
         • R requests votes, wins, and is promoted.
         • R now owns slots 0-5460.

         ⭐ SIMULTANEOUSLY, M detects it cannot reach a majority and
            ⭐ STOPS ACCEPTING WRITES (it enters an error state).
            This is the mechanism that bounds the damage.

t=16     The partition heals. M rejoins and ⭐ becomes a replica of R.
         ⭐ M DISCARDS ITS OWN DATASET and full-resyncs from R.

⭐ RESULT: every write accepted by M between t=0 and t=15 is
   PERMANENTLY LOST. All of them were acknowledged to clients.
```

### The bound, and how to narrow it

```
⭐ THE LOSS WINDOW ≈ cluster-node-timeout.

  Lowering it narrows the window:
      cluster-node-timeout 5000    → ~5 seconds of exposure
  ⭐ But too low causes SPURIOUS FAILOVERS on transient network
     hiccups or GC pauses, which cause their own loss events.

⭐ THE REAL MITIGATIONS:
   min-replicas-to-write 1      ⭐ M refuses writes once its replica
   min-replicas-max-lag 10         is unreachable — closing most of
                                   the window
```

```
⭐ THE HONEST SUMMARY:
   Redis Cluster is an AP system (Chapter 05 §5.4) with a
   ⭐ BOUNDED, SPECIFIED, UNAVOIDABLE acknowledged-write loss window.

   ⭐ Compare with Kafka (Deep Dive 10 §12), where unclean leader
      election is OFF by default and the equivalent loss requires you
      to opt in; and with Raft systems (Deep Dive 01), where the
      minority side cannot commit at all.

   ⭐ This is a legitimate design for a cache. It is not a design for
      a ledger. Choose accordingly, and say so in the ADR.
```

---

## 17. Hash tags and multi-key operations

```
⭐ In a cluster, a multi-key command only works if ALL keys map to
   the SAME SLOT.

  MGET user:1 user:2
  ⭐ (error) CROSSSLOT Keys in request don't hash to the same slot
```

### Hash tags

```
⭐ If a key contains {...}, ONLY the content between the first { and
   the first following } is hashed.

    {user:1000}.profile   ┐
    {user:1000}.settings  ├─ ⭐ ALL hash to the same slot
    {user:1000}.sessions  ┘

  → MGET across them works
  → a Lua script over them works
  → a MULTI/EXEC over them works
```

```
⭐ THE DANGER: hash tags CONCENTRATE keys onto one node.

  Tagging by tenant: {tenant:acme}...
  ⭐ If one tenant is 40% of your data, one node holds 40% of the
     cluster's data and traffic. The cluster cannot rebalance it,
     because every one of those keys must stay in the same slot.

⭐ THE RULE: use hash tags for a BOUNDED group of related keys that
   genuinely must be operated on atomically. Never for an unbounded
   grouping like a tenant or a customer.
```

---

## 18. Pipelining vs transactions vs Lua vs Functions

Four different mechanisms that people conflate.

### Pipelining — a network optimisation only

```
⭐ Send N commands without waiting for each reply.

  Without: 1000 commands × 0.5 ms RTT = ⭐ 500 ms
  With:    1 round trip                = ⭐ ~1 ms

  ⭐ NOT ATOMIC. Other clients' commands CAN interleave.
  ⭐ It is purely about round trips.
```

### MULTI/EXEC — atomic, but not a transaction as you know it

```
MULTI
SET a 1
INCR b
EXEC

⭐ Commands are QUEUED, then executed ATOMICALLY (nothing interleaves).

⭐ BUT:
   ❌ NO ROLLBACK. If INCR b fails because b is a string, ⭐ SET a 1
      STILL HAPPENED. EXEC returns the errors and moves on.
   ❌ You cannot read a value mid-transaction and branch on it —
      all commands are fixed before EXEC.
```

```
⭐ WATCH gives optimistic concurrency:

  WATCH balance
  val = GET balance
  MULTI
  SET balance <computed>
  EXEC          ⭐ returns nil if `balance` changed since WATCH → retry

  ⭐ This is compare-and-swap, the same pattern as PostgreSQL's
     version column (Deep Dive 08 §24).
```

### Lua — atomic and expressive, and it blocks

```lua
-- Atomic read-modify-write, impossible with MULTI/EXEC
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current + tonumber(ARGV[1]) > tonumber(ARGV[2]) then
    return 0                          -- would exceed the limit
end
redis.call('INCRBY', KEYS[1], ARGV[1])
return 1
```

```
✅ ⭐ ATOMIC — the whole script runs with nothing interleaved
✅ Can branch on values it reads
✅ One round trip

❌ ⭐ IT BLOCKS THE ENTIRE SERVER FOR ITS ENTIRE DURATION.
   A script with a loop over a million keys is a cluster-wide outage.

❌ ⭐ In a cluster, ALL KEYS must be in the same slot, and must be
   passed as KEYS[] (not constructed inside the script), or the
   client cannot route it.
```

```properties
busy-reply-threshold 5000    # ⭐ after 5 s, other clients get BUSY
                             #   and SCRIPT KILL becomes possible —
                             #   ⭐ but ONLY if the script has not
                             #      yet written anything.
                             #   If it has, only SHUTDOWN NOSAVE works.
```

**That last point is severe: a long-running Lua script that has already written cannot be killed without losing the instance.** Keep scripts short and bounded, always.

### Functions (Redis 7.0+)

```lua
#!lua name=ratelimit
redis.register_function('check_limit', function(keys, args)
    -- same logic, but REGISTERED and PERSISTED
end)
```

```
⭐ Functions are the successor to EVAL/EVALSHA:
   • Persisted in the RDB/AOF and replicated
   • ⭐ No SCRIPT LOAD / NOSCRIPT dance on reconnect or failover
   • Proper libraries and namespacing
   ⭐ Same blocking semantics — they are not safer, only better managed.
```

---

## 19. ⭐ The commands that block the world

Because execution is single-threaded (§1–2), **any O(n) command is an outage in proportion to n**.

| Command | Complexity | Safe alternative |
|---------|-----------|------------------|
| ⭐ `KEYS pattern` | O(N) over the **whole keyspace** | ⭐ `SCAN` (cursor-based) |
| ⭐ `SMEMBERS bigset` | O(N) | `SSCAN` |
| ⭐ `HGETALL bighash` | O(N) | `HSCAN` |
| ⭐ `LRANGE list 0 -1` | O(N) | `LRANGE` with a bounded range |
| ⭐ `ZRANGE zset 0 -1` | O(N) | Bounded ranges |
| ⭐ `DEL bigkey` | ⭐ O(N) — freeing N elements | ⭐ **`UNLINK`** (frees on a background thread) |
| ⭐ `FLUSHALL` / `FLUSHDB` | O(N) | ⭐ `FLUSHALL ASYNC` |
| ⭐ `SORT` on a large collection | O(N log N) | Precompute |
| ⭐ A Lua script with a loop | Unbounded | Bound it, or move the logic to the app |

### `SCAN` — and its guarantees

```bash
# ⭐ Cursor-based, O(1) per call
redis-cli --scan --pattern 'session:*'

# Manually:
SCAN 0 MATCH session:* COUNT 100
# 1) "17"          ← the next cursor
# 2) 1) "session:abc" ...
```

```
⭐ SCAN'S GUARANTEES (and its non-guarantees):
   ✅ Every element present from start to finish IS returned
   ⭐ ❌ Elements may be returned MORE THAN ONCE
   ⭐ ❌ Elements added or removed during the scan may or may not appear
   ⭐ ❌ COUNT is a HINT, not a limit — a single SCAN call can return
         far more than COUNT (e.g. when scanning a large listpack-encoded
         collection with HSCAN)
```

### Lazy freeing

```properties
lazyfree-lazy-eviction yes      # ⭐ free evicted keys in the background
lazyfree-lazy-expire yes        # ⭐ free expired keys in the background
lazyfree-lazy-server-del yes    # ⭐ implicit deletes (e.g. overwriting a big key)
lazyfree-lazy-user-del yes      # ⭐ makes DEL behave like UNLINK
replica-lazy-flush yes          # ⭐ background flush before a full resync
```

```
⭐ TURN ALL OF THESE ON. They move the O(N) free of large objects off
   the main thread. Without them, evicting a 1-million-element set
   blocks every client for the duration of the free.
```

### Finding the offenders

```bash
# ⭐ The slowlog — commands exceeding slowlog-log-slower-than (10000 µs)
redis-cli SLOWLOG GET 10
# 1) 1) (integer) 14
#    2) (integer) 1757673600
#    3) (integer) ⭐ 2847193        ← 2.8 SECONDS
#    4) 1) "KEYS"
#       2) "session:*"
#    5) "10.0.1.42:51234"

# ⭐ Find the biggest keys (samples; safe to run)
redis-cli --bigkeys
redis-cli --memkeys          # by memory rather than element count

# ⭐ Live command sampling — what is actually being run?
redis-cli --hotkeys          # requires an LFU policy
```

```properties
# ⭐ DISABLE THE DANGEROUS COMMANDS ENTIRELY IN PRODUCTION
rename-command KEYS ""
rename-command FLUSHALL ""
rename-command FLUSHDB ""
rename-command CONFIG "CONFIG_a8f3c2"
```

**Renaming `KEYS` to nothing is a legitimate and common production hardening step.** It converts "someone ran `KEYS *` and took down the site" from an incident into an error message.

---

## 20. Streams internals

```
⭐ A Redis Stream is a RADIX TREE of entry IDs, whose leaves are
   listpack-encoded "macro nodes" holding many entries.

  Entry ID: <milliseconds>-<sequence>       e.g. 1757673600123-0

  ⭐ The radix tree gives O(log n) lookup by ID and efficient
     range scans; the listpack macro nodes give compact storage
     and field-name deduplication across entries in the same node.
```

```bash
XADD events '*' type verification.passed session ses_881
XLEN events
XRANGE events - + COUNT 10
```

### Consumer groups and the PEL

```
⭐ PEL (Pending Entries List): per consumer group, the set of entries
   DELIVERED but NOT YET ACKNOWLEDGED.

  XREADGROUP GROUP billing worker-1 COUNT 10 STREAMS events '>'
      ⭐ delivers new entries AND adds them to the PEL

  XACK events billing 1757673600123-0
      ⭐ removes the entry from the PEL

  ⭐ XAUTOCLAIM events billing worker-2 60000 0
      claims entries idle for >60 s from a dead consumer
```

```
⭐ THE PEL IS THE AT-LEAST-ONCE MECHANISM. An entry stays pending
   until acknowledged, so a crashed consumer's work is reclaimable.

⭐ THE HAZARD: an unbounded PEL. A consumer that reads but never
   acknowledges (a bug, or a crash loop) grows the PEL forever,
   consuming memory that MAXLEN trimming CANNOT reclaim.
   ⭐ Monitor XPENDING.
```

### Trimming

```bash
XADD events MAXLEN 1000000 '*' ...      # exact — O(N) when trimming
⭐ XADD events MAXLEN '~' 1000000 '*' ... # ⭐ approximate — O(1)
XTRIM events MINID '~' 1757673600000     # trim by ID/time
```

```
⭐ ALWAYS USE `~`. Exact trimming must remove entries one at a time
   from a macro node; approximate trimming drops whole nodes, which is
   O(1) and removes slightly more than requested. The difference at
   high throughput is enormous.
```

---

## 21. Memory fragmentation and active defrag

```bash
redis-cli INFO memory
# used_memory:8589934592               ⭐ what Redis THINKS it uses
# used_memory_rss:12884901888          ⭐ what the OS has allocated
# ⭐ mem_fragmentation_ratio:1.50
# allocator_frag_ratio:1.42
# mem_allocator:jemalloc-5.3.0
```

### Reading the ratio

```
⭐ ratio ≈ 1.0-1.1   healthy
⭐ ratio > 1.5       significant fragmentation — 50% of RAM wasted
⭐ ratio < 1.0       ⭐⭐ THE PROCESS IS SWAPPING. This is a
                     catastrophic latency event for Redis. Fix it
                     immediately (more RAM, or lower maxmemory).
```

### Why fragmentation happens

```
⭐ jemalloc allocates from SIZE-CLASS BINS (8, 16, 32, 48, 64, 80, 96...).

  A 33-byte value occupies a 48-byte slot → ⭐ 15 bytes wasted.

  And when a key is deleted, its slot is freed but the PAGE is not
  returned to the OS unless the whole page is empty.

⭐ WORKLOADS THAT FRAGMENT BADLY:
   • Highly variable value sizes
   • ⭐ Heavy churn — many writes and deletes of differently-sized values
   • Long-running instances with shifting access patterns
```

### Active defragmentation

```properties
activedefrag yes                      # ⭐ requires jemalloc (the default build)
active-defrag-ignore-bytes 100mb      # do not bother below this
active-defrag-threshold-lower 10      # start at 10% fragmentation
active-defrag-threshold-upper 100     # maximum effort at 100%
active-defrag-cycle-min 1             # ⭐ % of CPU at minimum effort
active-defrag-cycle-max 25            # ⭐ % of CPU at maximum effort
```

```
⭐ HOW IT WORKS: Redis walks the keyspace, and for allocations that
   jemalloc reports as sitting in poorly-utilised runs, it REALLOCATES
   and COPIES them into better-packed regions.

⭐ It is incremental and CPU-bounded, but it IS main-thread work.
   Watch latency after enabling it.
```

```bash
# ⭐ The nuclear option: a restart with an RDB reload rebuilds memory
#   perfectly compactly. On a replica, this is a zero-downtime defrag:
#   failover to the replica, restart the old master, fail back.
```

---

## 22. ⭐ Latency diagnosis: the procedure

Redis latency problems have a small number of causes. This procedure identifies which.

```bash
# ═══ STEP 1 — Is it Redis, or the network/client? ═══
redis-cli --latency
# min: 0, max: 1, avg: 0.19 (1427 samples)      ✅ healthy
# min: 0, max: ⭐ 847, avg: 12.31                ❌ something blocks

redis-cli --latency-history -i 5      # over time, 5-second buckets

# ⭐ STEP 1b — Is it the MACHINE rather than Redis?
redis-cli --intrinsic-latency 100
# ⭐ Measures the kernel/hypervisor's scheduling latency with NO Redis
#   work at all. If this is already high (>10 ms), the problem is the
#   host — a noisy neighbour, CPU steal, or THP — not Redis.
```

```bash
# ═══ STEP 2 — The slowlog: are individual commands slow? ═══
redis-cli CONFIG SET slowlog-log-slower-than 1000   # ⭐ 1 ms, temporarily
redis-cli SLOWLOG RESET
# ... wait ...
redis-cli SLOWLOG GET 25
# ⭐ Identifies O(N) commands (§19)
```

```bash
# ═══ STEP 3 — The latency monitor: what EVENT is slow? ═══
redis-cli CONFIG SET latency-monitor-threshold 100   # ⭐ ms
redis-cli LATENCY RESET
# ... wait ...
redis-cli LATENCY LATEST
# 1) 1) "⭐ fork"
#    2) (integer) 1757673600
#    3) (integer) ⭐ 847              ← 847 ms fork (§9)
#    4) (integer) 921
# 2) 1) "⭐ expire-cycle"
#    ...
redis-cli LATENCY DOCTOR       # ⭐ a human-readable diagnosis
```

```
⭐ THE EVENTS AND WHAT THEY MEAN:

  ⭐ fork                  → §9. Too much memory, or THP enabled.
  ⭐ expire-cycle          → §6. Too many keys expiring at once.
  ⭐ eviction-cycle        → §7. maxmemory reached; heavy eviction.
  ⭐ eviction-del          → freeing evicted keys → enable lazyfree (§19)
  ⭐ aof-fsync-always      → appendfsync always on slow disk
  ⭐ aof-write             → §11. Check aof_delayed_fsync.
  ⭐ command               → an individual slow command → see the slowlog
  ⭐ active-defrag-cycle   → §21. Defrag is consuming CPU.
```

```bash
# ═══ STEP 4 — The usual suspects, checked directly ═══
redis-cli INFO stats | grep latest_fork_usec        # ⭐ §9
redis-cli INFO memory | grep -E 'fragmentation|rss' # ⭐ §21 (ratio < 1 = swap!)
redis-cli INFO stats | grep -E 'sync_full|expired_keys|evicted_keys'
redis-cli INFO clients | grep blocked
cat /sys/kernel/mm/transparent_hugepage/enabled     # ⭐ must be [never]
vmstat 1 5                                           # ⭐ 'st' column = CPU steal
```

### The decision table

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| ⭐ Periodic spikes matching `save` intervals | Fork (§9) | `save ""`, snapshot on a replica, disable THP, smaller instances |
| ⭐ `intrinsic-latency` already high | Host problem | Check CPU steal, THP, noisy neighbours |
| ⭐ `mem_fragmentation_ratio < 1` | **Swapping** | More RAM, lower `maxmemory`, `vm.swappiness=1` |
| Spikes correlated with traffic peaks | Eviction or O(N) commands | Check slowlog; enable lazyfree |
| ⭐ `sync_full` climbing | Backlog too small (§12) | Raise `repl-backlog-size` |
| ⭐ `aof_delayed_fsync` climbing | Slow disk (§11) | Faster disk, or `appendfsync no` |
| Sudden step in `used_memory` | Encoding conversion (§5) | Check `OBJECT ENCODING` on hot key patterns |
| ⭐ One command at 100% CPU | Lua script (§18) | `SCRIPT KILL` if it has not written; bound your scripts |

---

## 23. Monitoring

```bash
redis-cli INFO all
```

```
⭐ TIER 1 — ALERT IMMEDIATELY

  ⭐ mem_fragmentation_ratio < 1        → SWAPPING. Catastrophic.
  ⭐ used_memory / maxmemory > 0.9      → approaching eviction/OOM
  ⭐ rejected_connections > 0           → maxclients reached
  ⭐ master_link_status:down            → replication broken
  ⭐ latest_fork_usec > 500000          → 500 ms+ fork stalls (§9)
  ⭐ blocked_clients climbing           → blocking commands piling up

⭐ TIER 2 — TRENDS THAT MATTER

  ⭐ evicted_keys/sec                   → cache too small, or a scan flush
  ⭐ expired_keys/sec                   → TTL churn
  ⭐ keyspace_hits / (hits + misses)    → THE hit ratio (Chapter 11 §11.10)
  ⭐ sync_full                          → §12, backlog too small
  ⭐ aof_delayed_fsync                  → §11, disk too slow
  ⭐ instantaneous_ops_per_sec
  ⭐ connected_clients vs maxclients
  ⭐ total_net_input_bytes / _output_   → bandwidth; often the real limit

⭐ TIER 3 — CLUSTER

  ⭐ cluster_state:ok                   → anything else = degraded/down
  ⭐ cluster_slots_assigned = 16384     → less means uncovered slots (§15)
  ⭐ cluster_known_nodes                → unexpected changes
```

```promql
# ⭐ The alerts
redis_memory_fragmentation_ratio < 1                          # swapping
redis_memory_used_bytes / redis_memory_max_bytes > 0.9
rate(redis_evicted_keys_total[5m]) > 100
redis_latest_fork_usec > 500000
redis_connected_slaves < 1
rate(redis_keyspace_hits_total[5m]) /
  (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m])) < 0.8
```

---

## 24. Tuning

```properties
# ═══ MEMORY — the most important section ═══
maxmemory 8gb                  # ⭐ ≤ 50-60% of RAM if persistence is on (§10)
maxmemory-policy allkeys-lru   # ⭐ NOT the noeviction default (§7)
maxmemory-samples 10           # ⭐ better LRU approximation

# ═══ ENCODINGS (§4) ═══
hash-max-listpack-entries 512
hash-max-listpack-value 128
zset-max-listpack-entries 256
set-max-listpack-entries 256
list-max-listpack-size 256

# ═══ LAZY FREEING (§19) — turn all of these ON ═══
lazyfree-lazy-eviction yes
lazyfree-lazy-expire yes
lazyfree-lazy-server-del yes
lazyfree-lazy-user-del yes
replica-lazy-flush yes

# ═══ PERSISTENCE (§8-11) ═══
# Pure cache:
save ""
appendonly no
# Semi-durable:
# appendonly yes
# appendfsync everysec
# save ""                      # ⭐ AOF only — one fork source, not two

# ═══ REPLICATION (§12-13) ═══
repl-backlog-size 256mb        # ⭐ NOT the 1 MB default
repl-backlog-ttl 3600
min-replicas-to-write 1        # ⭐ narrows the loss window
min-replicas-max-lag 10
repl-diskless-sync yes         # ⭐ stream the RDB without writing it to disk
repl-diskless-sync-delay 5

# ═══ THREADS (§1) ═══
io-threads 4
io-threads-do-reads yes

# ═══ SAFETY (§19) ═══
rename-command KEYS ""
rename-command FLUSHALL ""
rename-command FLUSHDB ""

# ═══ DEFRAG (§21) ═══
activedefrag yes

# ═══ OBSERVABILITY (§22) ═══
slowlog-log-slower-than 10000
slowlog-max-len 256
latency-monitor-threshold 100

# ═══ LIMITS ═══
maxclients 20000
timeout 300
tcp-keepalive 300
```

```bash
# ═══ OS-LEVEL — ⭐ all three matter ═══
echo never > /sys/kernel/mm/transparent_hugepage/enabled   # ⭐ §9
sysctl vm.overcommit_memory=1                              # ⭐ §10
sysctl vm.swappiness=1                                     # ⭐ §21
sysctl net.core.somaxconn=65535
ulimit -n 65535
```

---

## 25. What an architect takes from this

**1. "Single-threaded" means *execution* is serial.** Redis 6+ parallelises I/O, which helps large values and TLS — but it never makes a slow command faster. **One O(N) command still blocks every client.**

**2. `fork()` for a snapshot blocks a 64 GB Redis for about a second.** This is the leading cause of unexplained Redis latency spikes, and it is invisible in command-level metrics. `latest_fork_usec` is the number to watch.

**3. Disable Transparent Huge Pages.** It multiplies copy-on-write amplification by up to 512× and turns a manageable fork into an erratic, memory-spiking one. Redis warns about it at startup.

**4. Never set `maxmemory` above ~50–60% of RAM if you use any persistence.** COW amplification during a background save needs the rest. This is the single most common Redis capacity mistake.

**5. Keep instances small — 8–16 GB — and shard.** Fork time, COW amplification, full-resync duration and failover time all scale with instance size. This is why Redis Cluster exists even when one machine could hold the data.

**6. The default `maxmemory-policy` is `noeviction`.** A cache with `maxmemory` set and the default policy returns errors instead of evicting. Set it explicitly.

**7. Encoding thresholds cause discontinuous memory jumps, and conversions are one-way.** One oversized field converts a whole collection permanently. Audit `OBJECT ENCODING` on your hot key patterns.

**8. Millions of small keys is the wrong shape.** ~88 bytes of overhead per key versus ~5 bytes per field in a listpack-encoded hash. Restructuring into hashes routinely saves 80% of memory.

**9. Expiration is sampled, not scheduled.** Up to ~25% of TTL'd keys can be expired-but-resident, `used_memory` counts them, and `expired` keyspace events fire late by an unbounded amount. **Never build a scheduler on Redis expiry.**

**10. Redis replication is asynchronous with no synchronous option.** Acknowledged writes can be lost on failover, and Redis Cluster's loss window is approximately `cluster-node-timeout`. `min-replicas-to-write` narrows it but does not close it. This is a legitimate cache design and an unacceptable ledger design.

**11. `cluster-require-full-coverage yes` means one master without a replica takes down the entire cluster.** Know that this is the default and decide it deliberately.

**12. A Lua script that has written cannot be killed.** Bound every script; prefer moving complex logic to the application.

**13. Rename `KEYS` and `FLUSHALL` out of existence in production.** It converts a class of incident into an error message.

---

## Exercises

1. Run `OBJECT ENCODING` and `MEMORY USAGE` across a sample of your production keys. How many collections are in the expensive encoding, and what would raising the thresholds save?
2. Create a hash with 128 fields, measure its memory, add one field, and measure again. Then delete the field and measure a third time. Explain all three numbers.
3. Check `latest_fork_usec` on a production instance. How long does it block, and how often?
4. Verify whether THP is enabled on every Redis host you run. If it is, explain the two distinct problems it causes.
5. Compute the COW headroom needed for a 32 GB instance with a 150 MB/s page-touch rate and a 60-second BGSAVE. What should `maxmemory` be on a 64 GB machine?
6. Compare `allkeys-lru` and `allkeys-lfu` on a workload with a periodic full scan. Measure the hit ratio for each.
7. Store 1 million small values as individual keys, then as fields in 10,000 hashes. Compare total memory.
8. Set `repl-backlog-size` to the default, disconnect a replica for 2 seconds under load, and observe `sync_full`. Then size it correctly and repeat.
9. Reproduce the §16 cluster failover write loss on a test cluster using `iptables` to partition a master. Count the lost writes.
10. Write a Lua script that takes 10 seconds. Observe what happens to other clients, then try `SCRIPT KILL` before and after it performs a write.
11. Run `redis-cli --intrinsic-latency 100` on your Redis hosts. Is the baseline acceptable?
12. Use `LATENCY DOCTOR` on a production instance and interpret the output.
13. Design the key schema for a multi-tenant session store in Redis Cluster. Explain your hash-tag decision and its rebalancing consequences.
14. Write the ADR for using Redis as a session store, stating the durability guarantee precisely, including the failover loss window.

---

**Next in this series:** Deep Dive 12 — TCP Mechanics

**Back to:** [Deep Dives](README.md) · [Chapter 11](../11-caching.md) · [The Map](../README.md)
