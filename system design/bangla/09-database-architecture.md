# অধ্যায় ০৯ — Database Architecture (Relational) 🟢

> আপনার সিস্টেমে database সাধারণত বদলানোর সবচেয়ে কঠিন জিনিস, সবচেয়ে আগে বাধা হয়ে দাঁড়ানো জিনিস, আর সবার শেষে যেটা কেউ ছুঁতে চায়।
> যে আর্কিটেক্ট database গভীরভাবে বোঝেন, তিনি না-বোঝা তিনজনের সমান।

উদাহরণগুলোতে PostgreSQL ব্যবহার করা হয়েছে কারণ ২০২৬ সালে বেশিরভাগ সিস্টেমের জন্য এটাই সেরা default পছন্দ, তবে ধারণাগুলো SQL Server, MySQL আর Oracle-এও খাটে।

---

## ৯.১ ACID — এটা আসলে কী নিশ্চিত করে

| অক্ষর | মানে | এটা ছাড়া কী ভাঙে |
|--------|---------|------------------------|
| **A — Atomicity** | একটা transaction-এর সব operation সফল হয়, নয়তো কোনোটাই না | একটা transfer এক account থেকে কাটে আর অন্যটায় কখনো জমা দেয় না |
| **C — Consistency** | Database একটা বৈধ state থেকে আরেকটায় যায় (constraint টেকে) | অনাথ row, ঋণাত্মক stock, অবৈধ foreign key |
| **I — Isolation** | একসাথে চলা transaction একে অপরকে নষ্ট করে না | দুজন ব্যবহারকারী শেষ জিনিসটা কেনেন; দুজনেই সফল হন |
| **D — Durability** | একবার commit হলে crash-এও টেকে | "Payment সফল" তারপর বিদ্যুৎ চলে গেল, আর payment উধাও |

**"C" নিয়ে একটা কথা:** ACID-এর C-কে প্রায়ই সবচেয়ে দুর্বল অক্ষর বলা হয় — এর আসল মানে "database *আপনার* ঘোষণা করা constraint গুলো বলবৎ করে"। আপনার business invariant আপনার দায়িত্ব। যা পারেন ঘোষণা করুন (`CHECK`, `FOREIGN KEY`, `UNIQUE`, `NOT NULL`) — **database হলো শেষ প্রতিরক্ষা রেখা, আর এটাই একমাত্র রেখা যেটা কখনো এড়ানো যায় না।**

```sql
-- Database যা পারে তা তাকেই বলবৎ করতে দিন। Application কোডে bug থাকে; constraint-এ নেই।
CREATE TABLE verification_sessions (
    id            UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    customer_id   UUID NOT NULL,
    status        TEXT NOT NULL
                  CHECK (status IN ('pending','processing','passed','failed','review')),
    score         NUMERIC(4,3) CHECK (score >= 0 AND score <= 1),
    attempt_count SMALLINT NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 3),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    concluded_at  TIMESTAMPTZ,
    CONSTRAINT concluded_requires_terminal_status
        CHECK ((concluded_at IS NULL) = (status IN ('pending','processing')))
);
```

শেষের ওই যৌগিক `CHECK`-টা schema-তে একটা সত্যিকারের business rule encode করে। কোনো কোডের পথ এটা লঙ্ঘন করতে পারবে না — কোনো script নয়, কোনো migration নয়, production-এ কোনো junior-এর `UPDATE`-ও নয়।

---

## ৯.২ Transaction

```sql
BEGIN;
  UPDATE accounts SET balance = balance - 100 WHERE id = 1;
  UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;   -- অথবা ROLLBACK
```

### Transaction-এর ব্যবহারিক নিয়ম

১. **ছোট রাখুন।** একটা transaction lock ধরে রাখে। লম্বা transaction অন্যদের আটকায় আর (Postgres-এ) `VACUUM`-কে পরিষ্কার করতে দেয় না — যেটা table bloat ঘটায়।
২. **Transaction-এর ভেতরে কখনো I/O করবেন না।** কোনো HTTP call নয়, কোনো file write নয়, কোনো `sleep` নয়। Transaction-এর ভেতরে একটা ৩ সেকেন্ডের ভেন্ডর call ৩ সেকেন্ড lock ধরে রাখে।
৩. Transaction-এর ভেতরে **কখনো একজন মানুষের জন্য অপেক্ষা করবেন না**।
৪. আপনার পুরো codebase জুড়ে **একটা সামঞ্জস্যপূর্ণ ক্রমে lock নিন** (এভাবেই আপনি deadlock ঠেকান)।
৫. একটা **`statement_timeout` বসান**, যাতে একটা নিয়ন্ত্রণহীন query চিরকাল lock ধরে রাখতে না পারে।

```python
# ভুল — transaction-এর ভেতরে একটা দূরবর্তী call
async with db.transaction():
    order = await db.save(order)
    await payment_gateway.charge(...)     # ২ সেকেন্ডের network call, lock ধরে আছে
    await db.update(order, status="paid")

# সঠিক — transaction, তারপর I/O, তারপর transaction (বা Outbox pattern ব্যবহার করুন)
async with db.transaction():
    order = await db.save(order)          # দ্রুত
result = await payment_gateway.charge(...)  # ধীর, কোনো lock ধরা নেই
async with db.transaction():
    await db.update(order, status="paid" if result.ok else "failed")
```

```sql
-- বৈশ্বিকভাবে বসানোর মতো নিরাপত্তা-জাল
SET statement_timeout = '30s';
SET idle_in_transaction_session_timeout = '60s';  -- ভুলে যাওয়া খোলা transaction মেরে ফেলে
SET lock_timeout = '5s';
```

---

## ৯.৩ Isolation level 🟢

**সমস্যা:** একসাথে চলা transaction একে অপরের অর্ধেক-শেষ কাজ দেখতে পারে। Isolation level ঠিক করে কতটা হস্তক্ষেপ অনুমোদিত।

### Anomaly গুলো

**১. Dirty read** — commit না হওয়া data পড়া

```
T1: UPDATE accounts SET balance = 0 WHERE id = 1;   (commit হয়নি)
T2: SELECT balance FROM accounts WHERE id = 1;      → ০ পড়ে
T1: ROLLBACK;                                        → ওই ০-র কোনো অস্তিত্বই ছিল না
```

**২. Non-repeatable read** — একটা transaction-এর ভেতরে একই row আলাদা মান দেয়

```
T1: SELECT balance FROM accounts WHERE id = 1;   → ৫০০
T2: UPDATE accounts SET balance = 300 WHERE id = 1; COMMIT;
T1: SELECT balance FROM accounts WHERE id = 1;   → ৩০০  (transaction-এর মাঝপথে বদলে গেল!)
```

**৩. Phantom read** — একই query আলাদা *row* ফেরত দেয়

```
T1: SELECT count(*) FROM orders WHERE total > 100;   → ৫
T2: INSERT INTO orders (total) VALUES (200); COMMIT;
T1: SELECT count(*) FROM orders WHERE total > 100;   → ৬  (একটা ভূত এলো)
```

**৪. Lost update** — দুটো transaction একই row পড়ে, বদলায় আর লেখে; একটা পরিবর্তন উধাও

```
T1: SELECT stock FROM items WHERE id=1;   → ১০
T2: SELECT stock FROM items WHERE id=1;   → ১০
T1: UPDATE items SET stock = 9 WHERE id=1; COMMIT;
T2: UPDATE items SET stock = 9 WHERE id=1; COMMIT;   ← ৮ হওয়ার কথা। একটা বিক্রি উধাও।
```

**৫. Write skew** — সূক্ষ্মটা, যেটা বিশেষজ্ঞদেরও ধরে ফেলে

```
নিয়ম: সবসময় অন্তত একজন ডাক্তার on call থাকতে হবে।
এখন: Alice আর Bob, দুজনেই on call.

T1 (Alice): SELECT count(*) FROM doctors WHERE on_call = true;  → ২, ঠিক আছে
T2 (Bob):   SELECT count(*) FROM doctors WHERE on_call = true;  → ২, ঠিক আছে
T1: UPDATE doctors SET on_call = false WHERE name='Alice'; COMMIT;
T2: UPDATE doctors SET on_call = false WHERE name='Bob';   COMMIT;

→ শূন্য ডাক্তার on call। প্রতিটা transaction আলাদাভাবে বৈধ ছিল।
  তারা আলাদা row ছুঁয়েছে, তাই কোনো সংঘর্ষ শনাক্ত হয়নি।
```

Write skew-এর কারণেই "শুধু transaction ব্যবহার করো" সবসময় যথেষ্ট নয়, আর এই কারণেই `SERIALIZABLE` আছে।

### Level গুলো

| Level | Dirty read | Non-repeatable | Phantom | Lost update | Write skew |
|-------|-----------|----------------|---------|-------------|------------|
| **Read Uncommitted** | ✅ সম্ভব | ✅ | ✅ | ✅ | ✅ |
| **Read Committed** (PG-র default) | ❌ ঠেকানো | ✅ সম্ভব | ✅ সম্ভব | ✅ সম্ভব | ✅ সম্ভব |
| **Repeatable Read** (PG = Snapshot) | ❌ | ❌ | ❌* | ❌ | ✅ সম্ভব |
| **Serializable** | ❌ | ❌ | ❌ | ❌ | ❌ |

\* PostgreSQL-এর Repeatable Read phantom-ও ঠেকায় (এটা snapshot isolation), SQL standard-এর ন্যূনতমের বিপরীতে।

### বাস্তবে কী ব্যবহার করবেন

```sql
-- READ COMMITTED (default) — আপনার ৯৫% কাজ
-- প্রতিটা STATEMENT একটা তাজা snapshot দেখে। ভালো throughput। CRUD-এর জন্য যথেষ্ট।

-- REPEATABLE READ — যখন একটা transaction-কে একটা সামঞ্জস্যপূর্ণ snapshot দেখতে হবে
BEGIN ISOLATION LEVEL REPEATABLE READ;
  -- ৮টা table পড়া একটা report সবগুলোকে একই মুহূর্তের অবস্থায় দেখে
COMMIT;

-- SERIALIZABLE — যখন concurrency-তে সঠিকতা আপসহীন
BEGIN ISOLATION LEVEL SERIALIZABLE;
  -- PostgreSQL SSI (Serializable Snapshot Isolation) ব্যবহার করে: এটা lock করে না,
  -- এটা সংঘর্ষ শনাক্ত করে আর একটা transaction serialization_failure দিয়ে বাতিল করে।
COMMIT;
```

> **গুরুত্বপূর্ণ operational পয়েন্ট:** `SERIALIZABLE`-এ PostgreSQL SQLSTATE `40001` দিয়ে transaction বাতিল করবে। **আপনার application-কে সেগুলো retry করতেই হবে।** Retry logic ছাড়া SERIALIZABLE চালু করলে আপনি শুধু এলোমেলো ব্যর্থতা যোগ করলেন।

```python
async def with_serializable_retry(fn, max_attempts: int = 5):
    for attempt in range(max_attempts):
        try:
            async with db.transaction(isolation="serializable"):
                return await fn()
        except SerializationFailure:            # SQLSTATE 40001
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(0.05 * (2 ** attempt) * (0.5 + random.random()))
```

### SERIALIZABLE-এর সস্তা বিকল্প

বেশিরভাগ সময় আপনার পূর্ণ serializability লাগে না — আপনার একটা invariant রক্ষা করা লাগে:

```sql
-- ১. Atomic read-modify-write (lost update ঠেকায়, বাড়তি isolation লাগে না)
UPDATE items SET stock = stock - 1 WHERE id = 1 AND stock > 0;
-- কতগুলো row প্রভাবিত হলো দেখুন: ০ মানে stock শেষ

-- ২. Pessimistic lock (SELECT ... FOR UPDATE)
BEGIN;
  SELECT stock FROM items WHERE id = 1 FOR UPDATE;   -- অন্য txn এখানে অপেক্ষা করে
  UPDATE items SET stock = stock - 1 WHERE id = 1;
COMMIT;

-- ৩. Optimistic lock (version কলাম) — web app-এর জন্য সেরা, কোনো lock ধরা থাকে না
UPDATE items SET stock = 9, version = 6 WHERE id = 1 AND version = 5;
-- ০ row প্রভাবিত → অন্য কেউ বদলেছে → আবার পড়ুন আর retry করুন

-- ৪. এমন একটা constraint যা খারাপ state-টাকেই অসম্ভব করে
ALTER TABLE items ADD CONSTRAINT stock_non_negative CHECK (stock >= 0);
-- এখন একটা bug-ও oversell করতে পারবে না; transaction কেবল fail করবে
```

> **Web application-এর জন্য পছন্দের ক্রম: constraint > atomic UPDATE > optimistic lock > pessimistic lock > SERIALIZABLE।** যতটুকু বাধ্য, ততটুকুই তালিকায় নিচে নামুন।

---

## ৯.৪ MVCC — PostgreSQL আসলে কীভাবে কাজ করে 🟢

**Multi-Version Concurrency Control:** read-এর জন্য row lock করার বদলে প্রতিটা row-র **একাধিক সংস্করণ** রাখুন।

```
Row id=1 সময়ের সাথে:

  সংস্করণ ১: (id=1, balance=500, xmin=100, xmax=105)   ← txn ১০০ বানিয়েছে, ১০৫ মুছেছে
  সংস্করণ ২: (id=1, balance=300, xmin=105, xmax=null)  ← txn ১০৫ বানিয়েছে, এখনো জীবিত

txn ১০৩-এ snapshot নেওয়া একটা transaction সংস্করণ ১ দেখে।
txn ১০৭-এ snapshot নেওয়া একটা transaction সংস্করণ ২ দেখে।
কেউ কাউকে আটকায় না।
```

> **যে সোনার নিয়মটা এখান থেকে আসে: পাঠক কখনো লেখককে আটকায় না, আর লেখক কখনো পাঠককে আটকায় না।** শুধু *একই row*-তে লেখক-বনাম-লেখক আটকায়।

PostgreSQL মিশ্র read/write কাজ এত ভালোভাবে সামলায় — এর সবচেয়ে বড় কারণ এটাই।

### খরচ: মৃত tuple আর VACUUM

PostgreSQL-এ একটা `UPDATE` আসলে "একটা নতুন সংস্করণ insert + পুরনোটা মৃত চিহ্নিত করা"। একটা `DELETE` শুধু মৃত চিহ্নিত করে। **মৃত row disk-এ থেকে যায়** যতক্ষণ না vacuum হয়।

```
একই row ১,০০০ বার UPDATE → ১,০০০টা মৃত tuple → table বাড়ে
→ sequential scan মৃত row পড়ে → সবকিছু ধীর হয় → "bloat"
```

**`VACUUM`** মৃত tuple পুনর্ব্যবহারের জন্য মুক্ত করে। **`autovacuum`** এটা স্বয়ংক্রিয়ভাবে করে — সাধারণত ভালোভাবে, কিন্তু write-ভারী table-এ এটা পিছিয়ে পড়তে পারে।

```sql
-- ক্ষতিটা দেখুন
SELECT relname,
       n_live_tup, n_dead_tup,
       round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 10;

-- একটা গরম table-এর জন্য autovacuum সমন্বয় করুন (উচ্চ-write table-এ default খুব অলস)
ALTER TABLE verification_sessions SET (
    autovacuum_vacuum_scale_factor  = 0.02,   -- ২% মৃত হলেই vacuum (default ২০%)
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_vacuum_cost_limit    = 2000    -- একে দ্রুত কাজ করতে দিন
);
```

### কী VACUUM আটকায় (আর তাই bloat ঘটায়)

১. **দীর্ঘ transaction** — কোনো খোলা transaction-এর যে সংস্করণ এখনো লাগতে পারে, VACUUM সেটা সরাতে পারে না। psql-এ একজন বিশ্লেষকের ভুলে যাওয়া `BEGIN;` আপনার পুরো database bloat করে দিতে পারে।
২. **Idle-in-transaction connection** — একই সমস্যা। `idle_in_transaction_session_timeout` বসান।
৩. **অব্যবহৃত replication slot** — একটা বিচ্ছিন্ন replica যার slot এখনো আছে, সেটা WAL **আর** vacuum দুটোই আটকায়, আর শেষ পর্যন্ত আপনার disk ভরে ফেলবে। এটা একটা ক্লাসিক production outage।
৪. `hot_standby_feedback=on` সহ **replica-তে দীর্ঘ query**

### Transaction ID wraparound ⚪ (জানুন যে এটা আছে)

PostgreSQL-এর transaction ID ৩২-bit আর এটা ঘুরে আসে। Autovacuum যদি সময়মতো পুরনো row freeze করতে না পারে, তাহলে database **আপনার data রক্ষা করতে বন্ধ হয়ে যাবে**। এটা বিরল, বিপর্যয়কর, আর পুরোপুরি ঠেকানো যায় — `age(datfrozenxid)` monitor করুন আর ১৫০ কোটির অনেক আগেই alert দিন।

---

## ৯.৫ Lock আর deadlock 🟢

### Lock-এর স্তর (সরলীকৃত)

| Lock | যে নেয় | যার সাথে সংঘর্ষ করে |
|------|------------|----------------|
| `ACCESS SHARE` | `SELECT` | শুধু `ACCESS EXCLUSIVE` |
| `ROW SHARE` | `SELECT ... FOR UPDATE` | `EXCLUSIVE`, `ACCESS EXCLUSIVE` |
| `ROW EXCLUSIVE` | `INSERT`, `UPDATE`, `DELETE` | `SHARE` আর তার উপরে |
| `SHARE` | `CREATE INDEX` (non-concurrent) | Write |
| `ACCESS EXCLUSIVE` | `ALTER TABLE`, `DROP`, `TRUNCATE`, `VACUUM FULL` | **সবকিছু** |

> **Migration-ঘাতক:** `ALTER TABLE` একটা `ACCESS EXCLUSIVE` lock নেয়। এটাকে যদি একটা লম্বা query-র পেছনে অপেক্ষা করতে হয়, তাহলে এটা **সারিতে দাঁড়ায়** — আর তার পরের প্রতিটা query *তার* পেছনে সারিতে দাঁড়ায়। একটা ব্যস্ত table-এ একটা schema পরিবর্তন কয়েক সেকেন্ডে আপনার পুরো application জমিয়ে দিতে পারে। সবসময় একটা ছোট `lock_timeout` সহ migration চালান আর retry করুন।

```sql
-- নিরাপদ migration pattern
SET lock_timeout = '3s';
ALTER TABLE orders ADD COLUMN discount_code TEXT;   -- app জমানোর বদলে দ্রুত fail করে
```

### নিরাপদ বনাম অনিরাপদ schema পরিবর্তন (PostgreSQL 12+)

| Operation | নিরাপদ? | নোট |
|-----------|-------|-------|
| `ADD COLUMN` (nullable, বা একটা ধ্রুব default সহ) | ✅ | PG 11 থেকে শুধু metadata, দ্রুত |
| একটা volatile default সহ `ADD COLUMN NOT NULL` | ❌ | পুরো table নতুন করে লেখে |
| `DROP COLUMN` | ✅ | শুধু metadata (জায়গা পরে মুক্ত হয়) |
| `ALTER COLUMN TYPE` | ❌ সাধারণত | পূর্ণ পুনর্লিখন + lock। একটা নতুন কলাম + backfill + swap ব্যবহার করুন। |
| `ADD INDEX` | ❌ | Write আটকায় — **`CREATE INDEX CONCURRENTLY` ব্যবহার করুন** |
| `ADD CHECK / FOREIGN KEY` | ⚠️ | `NOT VALID` তারপর আলাদাভাবে `VALIDATE CONSTRAINT` ব্যবহার করুন |
| `RENAME COLUMN` | ⚠️ | তাৎক্ষণিক, কিন্তু চলমান application কোড ভাঙে — expand/contract ব্যবহার করুন |

**Expand–contract (parallel change) migration pattern — এটা মুখস্থ করুন:**

```
১. EXPAND    নতুন কলাম/table যোগ করুন। এমন কোড deploy করুন যা দুটোতেই লেখে, পুরনোটা পড়ে।
২. BACKFILL  ছোট ছোট batch-এ data কপি করুন (একটা বিশাল UPDATE এড়ান)।
৩. MIGRATE   এমন কোড deploy করুন যা নতুনটা পড়ে (এখনো দুটোতেই লেখে)।
৪. CONTRACT  এমন কোড deploy করুন যা শুধু নতুনটা ব্যবহার করে। তারপর পুরনো কলাম ফেলে দিন।
```

চারটা deploy, শূন্য downtime, প্রতিটা ধাপে ফেরানো যায়। একটা চলমান সিস্টেমে schema এভাবেই বদলান।

### Deadlock

```
T1: UPDATE accounts SET ... WHERE id = 1;    -- row ১-এ lock ধরে আছে
T2: UPDATE accounts SET ... WHERE id = 2;    -- row ২-এ lock ধরে আছে
T1: UPDATE accounts SET ... WHERE id = 2;    -- T2-র অপেক্ষা করে
T2: UPDATE accounts SET ... WHERE id = 1;    -- T1-এর অপেক্ষা করে  → DEADLOCK
```

PostgreSQL `deadlock_timeout`-এর (default ১ সেকেন্ড) পরে এটা শনাক্ত করে আর SQLSTATE `40P01` দিয়ে একটা transaction মেরে ফেলে।

**প্রতিরোধ:**
১. **সবসময় একটা সামঞ্জস্যপূর্ণ ক্রমে lock নিন** (যেমন primary key-র আরোহী ক্রমে)। শুধু এটাই বেশিরভাগ deadlock দূর করে।
২. Transaction ছোট রাখুন
৩. যেখানে সম্ভব read-তারপর-write-এর বদলে একটা atomic statement ব্যবহার করুন
৪. **`40P01`-এ retry করুন** — একটা ব্যস্ত সিস্টেমে deadlock একটা স্বাভাবিক, প্রত্যাশিত অবস্থা, চমকে ওঠার মতো কোনো bug নয়

```python
# সামঞ্জস্যপূর্ণ lock-ক্রম ক্লাসিক transfer deadlock ঠেকায়
async def transfer(from_id: UUID, to_id: UUID, amount: Decimal) -> None:
    first, second = sorted([from_id, to_id])            # সবসময় একই ক্রম
    async with db.transaction():
        await db.execute("SELECT 1 FROM accounts WHERE id = $1 FOR UPDATE", first)
        await db.execute("SELECT 1 FROM accounts WHERE id = $1 FOR UPDATE", second)
        await db.execute("UPDATE accounts SET balance = balance - $2 WHERE id = $1",
                         from_id, amount)
        await db.execute("UPDATE accounts SET balance = balance + $2 WHERE id = $1",
                         to_id, amount)
```

### কী কাকে আটকাচ্ছে খুঁজে বের করা

```sql
SELECT blocked.pid        AS blocked_pid,
       blocked.query      AS blocked_query,
       blocking.pid       AS blocking_pid,
       blocking.query     AS blocking_query,
       now() - blocked.query_start AS blocked_for
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking
  ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE blocked.wait_event_type = 'Lock';
```

এই query-টা আপনার runbook-এ রাখুন। রাত ৩টায় এটা লাগবে।

---

## ৯.৬ Index 🟢

**একটা index হলো একটা আলাদা data কাঠামো, যেটা database-কে পুরো table scan না করেই row খুঁজে পেতে দেয়।**

বাস্তব জীবন: একটা বইয়ের শেষের নির্ঘণ্ট। এটা ছাড়া "MVCC" খুঁজতে ৪০০ পাতা পড়তে হয়। এটা দিয়ে আপনি সোজা সেখানে চলে যান।

### B-tree (default, আর যা লাগে তার ৯৫%)

```sql
CREATE INDEX idx_sessions_tenant_created
    ON verification_sessions (tenant_id, created_at DESC);
```

কীসের জন্য ভালো: `=`, `<`, `>`, `BETWEEN`, `IN`, `IS NULL`, `ORDER BY`, আর `LIKE 'prefix%'`।

### Composite index আর leftmost-prefix নিয়ম ⭐

```sql
CREATE INDEX idx_abc ON t (a, b, c);
```

| Query | Index ব্যবহার করে? |
|-------|-----------------|
| `WHERE a = 1` | ✅ |
| `WHERE a = 1 AND b = 2` | ✅ |
| `WHERE a = 1 AND b = 2 AND c = 3` | ✅ পুরোপুরি |
| `WHERE b = 2` | ❌ (`a` এড়ানো যায় না) |
| `WHERE a = 1 AND c = 3` | ⚠️ আংশিক — `a` ব্যবহার করে, `c` filter করে |

**কলামের ক্রমের নিয়ম:** আগে **সমতার** কলাম, তারপর **range**-এর কলাম, তারপর **sort**-এর কলাম।

```sql
-- Query: WHERE tenant_id = ? AND status = ? AND created_at > ? ORDER BY created_at DESC
CREATE INDEX ON sessions (tenant_id, status, created_at DESC);
--                         সমতা        সমতা      range + sort
```

### Covering index (index-only scan)

```sql
CREATE INDEX idx_sessions_lookup
    ON verification_sessions (tenant_id, status)
    INCLUDE (score, created_at);       -- বাড়তি কলাম leaf-এ থাকে, key-তে নয়
```

এখন `SELECT score, created_at FROM sessions WHERE tenant_id=? AND status=?` **পুরোপুরি index থেকেই** উত্তর পায় — এটা table-ই ছোঁয় না। গরম query-তে এটা ১০× উন্নতি হতে পারে।

### Partial index ⭐ (বিশালভাবে কম ব্যবহৃত)

```sql
-- মাত্র ০.৫% session pending, কিন্তু আপনি অনবরত সেটাই query করেন
CREATE INDEX idx_sessions_pending
    ON verification_sessions (created_at)
    WHERE status = 'pending';
```

একটা বিশালের বদলে একটা ক্ষুদ্র index: ছোট, দ্রুত, রক্ষণাবেক্ষণে সস্তা। Soft-delete কলাম (`WHERE deleted_at IS NULL`), status queue, আর যে কোনো অত্যন্ত নির্বাচনী flag-এর জন্য নিখুঁত।

### বাকি index-এর ধরন

| ধরন | কীসের জন্য | উদাহরণ |
|------|---------|---------|
| **B-tree** | Default — সমতা, range, sorting | `(tenant_id, created_at)` |
| **Hash** | শুধু সমতা | খুব কমই এর দাম আছে; B-tree প্রায় সমান ভালো আর বেশি নমনীয় |
| **GIN** | **বহু-মানের কলাম**: JSONB, array, full-text search | `USING GIN (tags)`, `USING GIN (doc jsonb_path_ops)`, `USING GIN (to_tsvector('english', body))` |
| **GiST** | জ্যামিতিক, range, নিকটতম-প্রতিবেশী, exclusion constraint | `USING GIST (location)`, booking-এর overlap ঠেকানো |
| **BRIN** | **স্বাভাবিকভাবে সাজানো data সহ বিশাল table** (time-series) | `USING BRIN (created_at)` — B-tree-র চেয়ে ১০০০× ছোট একটা index |
| **SP-GiST** | ভারসাম্যহীন কাঠামো (quadtree, IP prefix) | বিরল |

```sql
-- JSONB-র জন্য GIN
CREATE INDEX idx_meta ON sessions USING GIN (metadata jsonb_path_ops);
SELECT * FROM sessions WHERE metadata @> '{"channel": "mobile"}';

-- Full-text search-এর জন্য GIN
CREATE INDEX idx_fts ON documents USING GIN (to_tsvector('english', content));
SELECT * FROM documents WHERE to_tsvector('english', content) @@ plainto_tsquery('liveness');

-- একটা append-only ২ TB event table-এর জন্য BRIN
CREATE INDEX idx_events_time ON events USING BRIN (created_at) WITH (pages_per_range = 64);
-- এখানে B-tree হতো ~৬০ GB। BRIN ~৫০ MB। Range scan-এ এটা প্রায় সমান দ্রুত।

-- GiST exclusion constraint — DATABASE স্তরেই দ্বিগুণ booking ঠেকায়
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE room_bookings ADD CONSTRAINT no_double_booking
    EXCLUDE USING GIST (room_id WITH =, during WITH &&);
```

শেষেরটা জানার মতো: এটা overlapping booking **অসম্ভব** করে, কোনো application logic ছাড়াই আর কোনো race condition ছাড়াই।

### Index-এর খরচ

প্রতিটা index:
- **প্রতিটা INSERT/UPDATE/DELETE ধীর করে** (index রক্ষণাবেক্ষণ করতে হয়)
- Disk-এর জায়গা নেয় (প্রায়ই table-এর চেয়ে বেশি)
- দ্রুত হতে হলে memory-তে রাখতে হয়
- Planner-কে বিবেচনা করতে হয় (বেশি index = ধীর planning)

> **নিয়ম: আপনার আসল query-র জন্য index করুন, "যদি লাগে" বলে নয়।** ১৫টা index সহ একটা table-এর একটা write সমস্যা আছে।

### অব্যবহৃত আর অনুপস্থিত index খুঁজে বের করা

```sql
-- অব্যবহৃত index (মুছে ফেলার প্রার্থী) — একটা পূর্ণ business চক্রের পর production-এ চালান
SELECT schemaname, relname AS table, indexrelname AS index,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       idx_scan AS times_used
FROM pg_stat_user_indexes
WHERE idx_scan < 50
  AND indexrelid NOT IN (SELECT conindid FROM pg_constraint WHERE contype IN ('p','u'))
ORDER BY pg_relation_size(indexrelid) DESC;

-- যেসব table-এ অনেক sequential scan হচ্ছে (একটা নতুন index-এর প্রার্থী)
SELECT relname, seq_scan, seq_tup_read, idx_scan,
       seq_tup_read / NULLIF(seq_scan, 0) AS avg_rows_per_seq_scan
FROM pg_stat_user_tables
WHERE seq_scan > 1000
ORDER BY seq_tup_read DESC;
```

### যা নীরবে আপনার index অকেজো করে

```sql
-- ❌ কলামের উপর একটা function
WHERE LOWER(email) = 'a@b.com'
-- ✅ সমাধান: একটা expression index
CREATE INDEX ON users (LOWER(email));

-- ❌ Type-এর অমিল / অন্তর্নিহিত cast
WHERE user_id = '123'            -- user_id BIGINT, '123' text
-- ✅ Application থেকে সঠিক type পাঠান

-- ❌ শুরুতে wildcard
WHERE name LIKE '%delower'
-- ✅ একটা trigram index ব্যবহার করুন
CREATE EXTENSION pg_trgm;
CREATE INDEX ON users USING GIN (name gin_trgm_ops);

-- ❌ আলাদা কলাম জুড়ে OR প্রায়ই একটা index অকেজো করে
WHERE email = ? OR phone = ?
-- ✅ দুটো indexed query-র UNION, বা আলাদা index + bitmap OR
```

---

## ৯.৭ Query planner আর EXPLAIN ANALYZE 🟢

**PostgreSQL cost-ভিত্তিক:** এটা কয়েকটা plan-এর খরচ অনুমান করে আর সবচেয়ে সস্তাটা বাছে, `ANALYZE`-এর সংগ্রহ করা পরিসংখ্যান ব্যবহার করে।

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT s.id, s.score, c.name
FROM verification_sessions s
JOIN customers c ON c.id = s.customer_id
WHERE s.tenant_id = '...'
  AND s.status = 'pending'
  AND s.created_at > now() - INTERVAL '7 days'
ORDER BY s.created_at DESC
LIMIT 50;
```

```
Limit  (cost=0.85..412.33 rows=50 width=52) (actual time=0.043..2.118 rows=50 loops=1)
  Buffers: shared hit=214
  ->  Nested Loop  (cost=0.85..8104.21 rows=983 width=52) (actual time=0.041..2.098 rows=50 loops=1)
        Buffers: shared hit=214
        ->  Index Scan Backward using idx_sessions_pending on verification_sessions s
              (cost=0.43..2841.10 rows=983 width=36) (actual time=0.024..0.521 rows=50 loops=1)
              Index Cond: (tenant_id = '...' AND created_at > ...)
              Buffers: shared hit=54
        ->  Index Scan using customers_pkey on customers c
              (cost=0.42..5.35 rows=1 width=24) (actual time=0.024..0.025 rows=1 loops=50)
              Index Cond: (id = s.customer_id)
              Buffers: shared hit=160
Planning Time: 0.312 ms
Execution Time: 2.174 ms
```

### কীভাবে পড়বেন (যে চারটা জিনিস গুরুত্বপূর্ণ)

১. **সবচেয়ে ভেতরের/গভীরতম node থেকে বাইরের দিকে পড়ুন।** ওটাই চলার ক্রম।
২. **`rows=` (অনুমান) আর `actual rows=` তুলনা করুন।** বড় ফারাক মানে পরিসংখ্যান ভুল → `ANALYZE` চালান, বা ওই কলামে `default_statistics_target` বাড়ান। খারাপ অনুমানই খারাপ plan-এর ১ নম্বর কারণ।
৩. **`loops=N`** — ওই node-এর আসল মোট পেতে `actual time`-কে `loops` দিয়ে গুণ করুন।
৪. **`Buffers: shared hit` বনাম `read`** — `hit` cache থেকে (দ্রুত), `read` disk থেকে (ধীর)। বেশি `read` মানে আপনার working set `shared_buffers`-এ আঁটে না।

### Scan-এর ধরন, সেরা থেকে খারাপ (প্রেক্ষাপট অনুযায়ী)

| Node | মানে | কখন ঠিক আছে |
|------|---------|-----------------|
| **Index Only Scan** | পুরোপুরি index থেকেই উত্তর | সেরা অবস্থা |
| **Index Scan** | Index lookup, তারপর row আনা | নির্বাচনী query-র জন্য ভালো |
| **Bitmap Heap Scan** | মিলে যাওয়া row-র অবস্থান জড়ো করুন, তারপর disk-ক্রমে আনুন | মাঝারি নির্বাচনীতার জন্য ভালো |
| **Seq Scan** | পুরো table পড়া | ছোট table-এর জন্য বা >৫–১০% row ফেরত দিলে **সঠিক**। একটা নির্বাচনী filter সহ বড় table-এ একটা সমস্যা। |

### Join-এর ধরন

| Join | কীভাবে | কখন সেরা |
|------|-----|-----------|
| **Nested Loop** | প্রতিটা বাইরের row-র জন্য ভেতরেরটা খোঁজা | ছোট বাইরের সেট + indexed ভেতরের |
| **Hash Join** | এক দিকের একটা hash বানান, অন্যটা দিয়ে probe করুন | বড় অসাজানো সেট; memory লাগে (`work_mem`) |
| **Merge Join** | দুই দিকই সাজানো, একসাথে হাঁটুন | দুটোই আগে থেকেই সাজানো (যেমন index দিয়ে) |

### একটা plan-এর বিপদসংকেত

```
❌ একটা নির্বাচনী WHERE সহ বড় table-এ Seq Scan     → index অনুপস্থিত
❌ rows=1 কিন্তু actual rows=450000                → বাসি পরিসংখ্যান; ANALYZE চালান
❌ loops=100000 সহ Nested Loop                     → একটা Hash Join হওয়া উচিত; পরিসংখ্যান দেখুন
❌ Sort Method: external merge Disk: 84320kB       → work_mem বাড়ান, বা একটা সাজানো index যোগ করুন
❌ Rows Removed by Filter: 2000000                 → index যথেষ্ট নির্বাচনী নয়
❌ Buffers: shared read=50000                      → working set RAM ছাড়িয়ে গেছে
```

### পরিসংখ্যান আর গরম-পথের অভ্যাস

```sql
ANALYZE verification_sessions;                          -- পরিসংখ্যান তাজা করুন
ALTER TABLE sessions ALTER COLUMN status SET STATISTICS 1000;   -- একটা বাঁকা কলামে বেশি বিবরণ
CREATE STATISTICS sess_corr (dependencies) ON tenant_id, status FROM sessions;  -- সম্পর্কিত কলাম
```

```sql
-- Production-এ আপনার সবচেয়ে খারাপ query খুঁজুন (pg_stat_statements লাগে)
SELECT substring(query, 1, 80) AS query,
       calls,
       round(total_exec_time::numeric, 0) AS total_ms,
       round(mean_exec_time::numeric, 2)  AS mean_ms,
       rows
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

> **গড় সময় নয়, মোট সময় দিয়ে optimise করুন।** ২০ লাখ বার call হওয়া একটা ৫ ms-এর query দিনে দুইবার চলা একটা ৩ সেকেন্ডের report-এর চেয়ে বেশি খরচ করায়।

### N+1 query সমস্যা — শিল্পের সবচেয়ে সাধারণ performance bug

```python
# তালিকার জন্য ১টা query...
sessions = await db.fetch("SELECT * FROM sessions WHERE tenant_id = $1", tid)
for s in sessions:                       # ...+ প্রতি row-তে ১টা query = ১০১টা round trip
    customer = await db.fetch_one("SELECT * FROM customers WHERE id = $1", s.customer_id)
```

১০১টা round trip × ০.৫ ms = কোনো কাজের আগেই ৫০ ms নিখাদ নেটওয়ার্ক। ১,০০০ row হলে এটা একটা ৫০০ ms-এর পাতা।

```python
# সমাধান ১: একটা join
rows = await db.fetch("""
    SELECT s.*, c.name AS customer_name
    FROM sessions s JOIN customers c ON c.id = s.customer_id
    WHERE s.tenant_id = $1""", tid)

# সমাধান ২: দ্বিতীয় query batch করুন (যখন একটা join অসুবিধাজনক)
ids = {s.customer_id for s in sessions}
customers = {c.id: c for c in await db.fetch(
    "SELECT * FROM customers WHERE id = ANY($1)", list(ids))}

# সমাধান ৩ (ORM): eager loading
#   SQLAlchemy: .options(selectinload(Session.customer))
#   EF Core:    .Include(s => s.Customer)
```

> **ORM default-এ lazy loading দিয়ে N+1 ঘটায়।** Production কোডে lazy loading বন্ধ করুন, অথবা প্রতি request-এ query-র সংখ্যা log আর alert করুন। এই একটা অভ্যাসই আপনাকে একজন performance জাদুকরের মতো দেখাবে।

---

## ৯.৮ WAL — Write-Ahead Log 🟢

**নিয়ম: data page বদলানোর *আগে* পরিবর্তনটা একটা log-এ লিখুন।**

```
১. Transaction memory-তে (shared_buffers) একটা page বদলায়
২. পরিবর্তনটা WAL-এ লেখা হয় আর disk-এ fsync হয়
৩. COMMIT client-কে ফেরত আসে            ← durability এখানেই অর্জিত
৪. পরে একটা checkpoint নোংরা page গুলো data ফাইলে লেখে
```

**কেন:** ধারাবাহিক WAL write দ্রুত; এলোমেলো data-page write ধীর। Server crash করলে শেষ checkpoint থেকে WAL replay করুন, কিছুই হারাবেন না।

### WAL আরও যা সম্ভব করে

| Feature | এটা WAL কীভাবে ব্যবহার করে |
|---------|--------------------|
| **Crash recovery** | শেষ checkpoint থেকে replay |
| **Streaming replication** | Replica-তে WAL record পাঠানো |
| **Point-in-time recovery (PITR)** | Base backup + WAL archive → যে কোনো সেকেন্ডে ফেরানো |
| **Logical replication / CDC** | WAL-কে row-র পরিবর্তনে decode করা (Debezium) |

### মূল setting

```ini
wal_level = replica              # বা CDC/Debezium-এর জন্য 'logical'
synchronous_commit = on          # off = দ্রুত কিন্তু crash-এ শেষ ~২০০ ms হারাতে পারেন
max_wal_size = 4GB               # বড় = কম checkpoint = মসৃণ I/O
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9   # checkpoint-এর I/O ছড়িয়ে দিন
archive_mode = on
archive_command = 'wal-g wal-push %p'
```

> **অ-গুরুত্বপূর্ণ, উচ্চ-volume write-এর জন্য (analytics event, log) `synchronous_commit = off` একটা বৈধ performance লিভার।** এটা atomicity আর consistency রাখে কিন্তু crash-এ শেষ ভগ্নাংশ সেকেন্ডের commit হারানোর ঝুঁকি নেয়। আপনি এটা **প্রতি transaction-এও** সেট করতে পারেন — payment-এ কড়া, click tracking-এ শিথিল। এটা জানাটা সত্যিকারের database দক্ষতার চিহ্ন।

### Backup — যে অংশটা মানুষ ভুল করে

```
ধরন:
  Logical  (pg_dump)        — বহনযোগ্য, restore ধীর, কোনো PITR নেই। ~৫০ GB-র নিচে ঠিক আছে।
  Physical (pg_basebackup)  — দ্রুত restore, WAL archiving সহ PITR সম্ভব করে। আসল সিস্টেমে এটাই ব্যবহার করুন।
  টুল: pgBackRest, WAL-G, Barman
```

> **যে backup আপনি কখনো restore করেননি, সেটা backup নয় — সেটা একটা আশা।**
> একটা **ত্রৈমাসিক restore মহড়া** নির্ধারণ করুন, সময় মাপুন, আর মাপা RTO লিখে রাখুন। বেশিরভাগ টিম আবিষ্কার করে যে তাদের "১ ঘণ্টার" restore আসলে ৯ ঘণ্টার, আর তারা এটা আবিষ্কার করে একটা incident-এর সময়।

---

## ৯.৯ Replication আর read replica 🟢

(ধারণা অধ্যায় ০৪ §৪.৮-এ; এখানে PostgreSQL-এর বাস্তবতা।)

### Physical streaming replication (প্রচলিত)

```ini
# Primary
wal_level = replica
max_wal_senders = 10
# ঐচ্ছিক: একটা synchronous standby নিশ্চিত করুন
synchronous_standby_names = 'ANY 1 (replica1, replica2)'
```

```sql
-- Primary থেকে replication lag মাপুন
SELECT client_addr, state, sent_lsn, replay_lsn,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
       replay_lag
FROM pg_stat_replication;
```

### Read replica সঠিকভাবে ব্যবহার করা

```python
class Database:
    async def read(self, sql, *args, consistent: bool = False):
        pool = self._primary if consistent else self._replica    # স্পষ্ট পছন্দ
        return await pool.fetch(sql, *args)

    async def write(self, sql, *args):
        return await self._primary.execute(sql, *args)
```

**Primary-তে পাঠান যখন:**
- এমন একটা transaction-এর ভেতরে যেটা লেখেও
- ব্যবহারকারীর নিজের write-এর সাথে সাথেই (**read-your-writes**, অধ্যায় ০৫)
- যেখানে পুরনো হওয়াটা একটা সঠিকতার সমস্যা (balance, permission, quota যাচাই)

**Replica-তে পাঠান:** dashboard, report, search, list view, export, আর যে কোনো বিশ্লেষণধর্মী কিছু।

### Replication slot — দুই দিকে ধার আছে এমন তলোয়ার

একটা slot নিশ্চিত করে যে replica না খাওয়া পর্যন্ত primary WAL রাখবে। Replica মরে গেলে আর slot থেকে গেলে **WAL জমতে থাকে যতক্ষণ না primary-র disk ভরে যায় আর database থেমে যায়।** একটা Postgres cluster নামানোর সবচেয়ে সাধারণ উপায়গুলোর একটা এটা।

```sql
-- এটা monitor করুন। এতে alert দিন।
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

ক্ষতি সীমাবদ্ধ করতে `max_slot_wal_keep_size` বসান।

### Logical replication

Disk-এর block নয়, **row-র পরিবর্তন** replicate করে। যা সম্ভব করে: table-এর একটা উপসেট replicate করা, version-এর মধ্যে replication (প্রায়-শূন্য-downtime-এ major upgrade এভাবেই করেন), আর Kafka-তে CDC।

### Connection pooling — scale-এ বাধ্যতামূলক ⭐

প্রতিটা PostgreSQL connection একটা OS process, ~৫–১০ MB ব্যবহার করে। ৫০০ connection মানে একটা মৃত server।

```
App (৫০০ connection) ──► PgBouncer ──► PostgreSQL (২৫টা আসল connection)
```

| PgBouncer mode | আচরণ | নোট |
|---|---|---|
| `session` | Client-এর পুরো session জুড়ে connection ধরা থাকে | সবচেয়ে নিরাপদ, pooling-এর সুবিধা সবচেয়ে কম |
| **`transaction`** | প্রতিটা transaction-এর পর connection ফেরত | **কাজের mode।** Session-স্তরের feature ভাঙে: prepared statement (configure না করলে), `SET`, advisory lock, `LISTEN/NOTIFY`। |
| `statement` | প্রতিটা statement-এর পর ফেরত | খুবই সীমাবদ্ধ |

> আপনি যদি Postgres-এর বিপরীতে serverless function বা একটা autoscaled fleet চালান, **আপনার একটা pooler লাগবে**। এটাই ১ নম্বর "আমরা app scale করলাম আর database মেরে ফেললাম" চমক (অধ্যায় ০৪)।

---

## ৯.১০ Table partitioning 🟡

একটা বড় table-কে ছোট ছোট শারীরিক টুকরোয় ভাগ করা, স্বচ্ছভাবে।

```sql
CREATE TABLE verification_events (
    id          BIGSERIAL,
    tenant_id   UUID NOT NULL,
    event_type  TEXT NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (created_at);

CREATE TABLE verification_events_2026_09 PARTITION OF verification_events
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE verification_events_2026_10 PARTITION OF verification_events
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
```

**আপনি যা পান:**
- **Partition pruning** — `WHERE created_at > '2026-10-01'` পুরো table-এর বদলে একটা partition পড়ে
- **পুরনো data-র তাৎক্ষণিক মুছে ফেলা** — `DROP TABLE verification_events_2026_03` তাৎক্ষণিক; `DELETE FROM ... WHERE created_at < ...` ঘণ্টার পর ঘণ্টা নেয় আর বিশাল bloat বানায়
- প্রতি partition-এ ছোট index; `VACUUM` প্রতি partition-এ কাজ করে
- প্রতি partition-এ আলাদা storage স্তর (পুরনো মাসগুলো সস্তা disk-এ)

**আপনি যা দাম দেন:**
- **Partition key-টা primary key-তে আর বেশিরভাগ query-তে থাকতে হবে**, নইলে আপনি pruning হারাবেন আর প্রতিটা partition query করবেন
- ভবিষ্যতের partition বানাতে automation লাগবে (`pg_partman` ব্যবহার করুন)
- Partition-এর মধ্যে query আর partition জুড়ে unique constraint সীমিত

> **ক্লাসিক ব্যবহারের ক্ষেত্র হলো retention policy সহ time-series data।** আপনার যদি "N দিন পর মুছে ফেলো" নিয়ম সহ একটা বড় append-only table থাকে, তাহলে সময় দিয়ে partition করা প্রায় সবসময়ই সঠিক — শুধু `DROP TABLE`-ই এর যৌক্তিকতা দেয়।

---

## ৯.১১ Normalisation আর denormalisation 🟢

### Normal form গুলো, সহজ ভাষায়

| রূপ | নিয়ম | লঙ্ঘনের উদাহরণ |
|------|------|-------------------|
| **1NF** | পারমাণবিক মান, কোনো পুনরাবৃত্ত দল নয় | এক কলামে `phone_numbers: "123, 456, 789"` |
| **2NF** | 1NF + প্রতিটা non-key কলাম **পুরো** key-র উপর নির্ভর করে | `(order_id, product_id)`-তে `product_name` রাখা (শুধু product-এর উপর নির্ভর) |
| **3NF** | 2NF + কোনো কলাম আরেকটা non-key কলামের উপর নির্ভর করে না | `orders`-এ `customer_id` আর `customer_city` দুটোই রাখা |
| **BCNF** | কড়া 3NF | বিরল প্রান্তিক ক্ষেত্র |

> **ব্যবহারিক নিয়ম: default-এ 3NF পর্যন্ত normalise করুন।** এই আকৃতিই update anomaly ঠেকায়। তারপর *ইচ্ছাকৃতভাবে*, একটা লিখিত কারণ সহ denormalise করুন।

### কখন denormalise করবেন

```sql
-- ১. Read performance — একটা গরম পথে একটা ব্যয়বহুল join
ALTER TABLE orders ADD COLUMN customer_name TEXT;   -- customers-এর সাথে join এড়ান

-- ২. আগে থেকে হিসাব করা aggregate
ALTER TABLE customers ADD COLUMN total_orders INT NOT NULL DEFAULT 0,
                      ADD COLUMN lifetime_value NUMERIC(12,2) NOT NULL DEFAULT 0;

-- ৩. ঐতিহাসিক snapshot — এটা DENORMALISATION নয়, এটা সঠিকতা
ALTER TABLE order_lines ADD COLUMN unit_price_at_purchase NUMERIC(10,2) NOT NULL;
-- Product-এর দাম কাল বদলাবে। Invoice বদলাতে পারবে না। কখনোই না।
```

> **৩ নম্বর পয়েন্টটা গুরুত্বপূর্ণ আর প্রায়ই ভুল বোঝা হয়।** Order line-এ দামটা কপি করা duplication নয় — order line *একটা আলাদা সত্য* লিপিবদ্ধ করে (ওই মুহূর্তের দাম)। একটা আইনি নথির (invoice, চুক্তি, statement) যে কোনো সংখ্যা **snapshot** করতে হবে, join করা নয়।

**Denormalisation-এর খরচ:** প্রতিটা কপি মিলিয়ে রাখতে হবে। Trigger, application কোড, বা নির্ধারিত job ব্যবহার করুন — আর মেনে নিন যে এগুলো ভেসে যাবে। একটা reconciliation job যোগ করুন যেটা যাচাই করে আর ভেসে যাওয়ার খবর দেয়।

### Materialised view — কম যন্ত্রণায় denormalisation

```sql
CREATE MATERIALIZED VIEW tenant_daily_stats AS
SELECT tenant_id,
       date_trunc('day', created_at) AS day,
       count(*)                                      AS total,
       count(*) FILTER (WHERE status = 'passed')     AS passed,
       avg(score) FILTER (WHERE score IS NOT NULL)   AS avg_score
FROM verification_sessions
GROUP BY 1, 2;

CREATE UNIQUE INDEX ON tenant_daily_stats (tenant_id, day);   -- CONCURRENTLY-র জন্য আবশ্যক

REFRESH MATERIALIZED VIEW CONCURRENTLY tenant_daily_stats;    -- read আটকায় না
```

৮ সেকেন্ড লাগা একটা dashboard query এখন ৪ ms নেয়। Business আসলে যতটা তাজা চায় তার সাথে মিলিয়ে একটা সময়সূচিতে refresh করুন।

---

## ৯.১২ একটা relational database বেছে নেওয়া 🟡

| | **PostgreSQL** | **MySQL** | **SQL Server** |
|---|---|---|---|
| Licence | বিনামূল্যে, উদার | বিনামূল্যে (GPL) / Oracle | বাণিজ্যিক |
| শক্তি | Extension (PostGIS, pgvector, TimescaleDB), JSONB, full-text, সমৃদ্ধ index, কড়া সঠিকতা | খুব দ্রুত সাধারণ read, বিশাল install base, পরিণত replication | চমৎকার টুল, T-SQL, গভীর .NET integration |
| দুর্বলতা | প্রতি connection-এ process (একটা pooler লাগে), vacuum সমন্বয় | ঐতিহাসিকভাবে শিথিল default; দুর্বল SQL feature | খরচ; Windows-কেন্দ্রিক উত্তরাধিকার |
| কীসের জন্য সেরা | **বেশিরভাগ নতুন সিস্টেম** | Read-ভারী web, বিদ্যমান LAMP | .NET প্রতিষ্ঠান, বিদ্যমান Microsoft পরিবেশ |

> **একটা নতুন সিস্টেমের জন্য default সুপারিশ: PostgreSQL।** এটা বিনামূল্যে, অত্যন্ত সক্ষম, default-এ সঠিক, আর এর extension-ব্যবস্থার মানে হলো এটা আপনার search engine (full-text), time-series store (TimescaleDB), geospatial store (PostGIS), vector store (pgvector) আর queue (`SKIP LOCKED`) হিসেবে কাজ করতে পারে — এগুলোর কোনোটার জন্য আলাদা সিস্টেম লাগার আগেই। **কম সিস্টেম একটা সত্যিকারের architecture-এর জয়।**

---

## ৯.১৩ সাধারণ ভুল

১. **N+1 query** — সবচেয়ে সাধারণ performance bug, সাধারণত ORM-এর lazy loading-এর কারণে
২. **Foreign key-তে কোনো index নেই** — join আর cascading delete ধীর করে, আর lock-এর সংঘর্ষ ঘটায়
৩. **খুব বেশি index** — write হামাগুড়ি দেয়; খারাপ না হওয়া পর্যন্ত কেউ খেয়াল করে না
৪. **`SELECT *`** — অব্যবহৃত কলাম আনে, index-only scan ভাঙে, একটা কলাম যোগ হলে ভাঙে
৫. **দীর্ঘ transaction** — lock ধরে রাখে, vacuum আটকায়, bloat ঘটায়
৬. **Transaction-এর ভেতরে network call** — একটা HTTP timeout-এর পুরো সময় ধরে lock ধরা থাকে
৭. **`lock_timeout` ছাড়া `ALTER TABLE`** — একটা migration পুরো application জমিয়ে দেয়
৮. একটা চলমান table-এ **`CONCURRENTLY` ছাড়া index যোগ করা** — কয়েক মিনিট write আটকায়
৯. **Retry logic ছাড়া `SERIALIZABLE`** — এলোমেলো অব্যাখ্যাত ব্যর্থতা
১০. **টাকার জন্য `float` ব্যবহার** — `0.1 + 0.2 != 0.3`। `NUMERIC`/`DECIMAL`, বা পূর্ণসংখ্যা সেন্ট ব্যবহার করুন।
১১. **Time zone ছাড়া `TIMESTAMP`** — সবসময় `TIMESTAMPTZ` ব্যবহার করুন আর UTC জমা রাখুন
১২. **লেখার সাথে সাথেই একটা replica থেকে পড়া** — ব্যবহারকারী পুরনো data দেখেন
১৩. **পরিত্যক্ত replication slot** — primary-র disk ভরে যায় আর database থেমে যায়
১৪. **কখনো একটা restore test না করা** — একটা outage-এর সময় আবিষ্কার করা যে আপনার backup ভাঙা
১৫. একটা autoscaled app tier সহ **কোনো connection pooler না থাকা**

---

## ৯.১৪ আর্কিটেক্টের চেকলিস্ট

- [ ] Schema-তে constraint ঘোষণা করা (NOT NULL, CHECK, FK, UNIQUE) — শুধু কোডে নয়
- [ ] টাকা `NUMERIC`; timestamp UTC-তে `TIMESTAMPTZ`; ID UUIDv7/ULID বা bigint
- [ ] Index আসল query-র ধরনের সাথে মেলে; composite কলামের ক্রম সমতা → range → sort
- [ ] Foreign key indexed
- [ ] `pg_stat_statements` চালু; **মোট** সময় অনুযায়ী শীর্ষ query নিয়মিত রিভিউ করা
- [ ] কোনো N+1 নেই: lazy loading বন্ধ বা query-সংখ্যায় alert বসানো
- [ ] Isolation level ইচ্ছাকৃতভাবে বাছা; `40001` আর `40P01`-এর জন্য retry logic
- [ ] Lock সবসময় একটা সামঞ্জস্যপূর্ণ ক্রমে নেওয়া
- [ ] Transaction ছোট; ভেতরে কোনো I/O নেই; `statement_timeout` আর `idle_in_transaction_session_timeout` বসানো
- [ ] Migration-এ expand/contract, `CONCURRENTLY`, `NOT VALID` + `VALIDATE`, আর একটা ছোট `lock_timeout` ব্যবহার
- [ ] গরম table-এ autovacuum সমন্বয় করা; bloat আর দীর্ঘ transaction monitor করা
- [ ] WAL archiving + PITR configure করা; **restore মহড়া করা আর সময় মাপা**
- [ ] Replication lag আর replication slot-এর retention monitor আর alert করা
- [ ] Connection pooler বসানো, Little's Law দিয়ে আকার ঠিক করা
- [ ] কোডে read/write routing স্পষ্ট; read-your-writes সামলানো
- [ ] Retention-এর কৌশল: বড় time-series table-এর জন্য partitioning বা archiving
- [ ] PII কলাম চিহ্নিত; encryption আর access logging ঠিক করা (অধ্যায় ১৭)

---

## ৯.১৫ নিজেকে যাচাই

১. ACID-এর "C" আসলে কী নিশ্চিত করে, আর আপনার কাজ কী?
২. একটা উদাহরণ দিয়ে write skew ব্যাখ্যা করুন। কোন isolation level এটা ঠেকায়?
৩. SERIALIZABLE চালু করলে কেন retry logic যোগ করতেই হবে?
৪. তিন বাক্যে MVCC ব্যাখ্যা করুন। এটা আপনাকে যে সোনার নিয়মটা দেয় সেটা কী?
৫. Table bloat কী ঘটায়, আর VACUUM আটকায় এমন তিনটা জিনিসের নাম বলুন।
৬. একটা `ALTER TABLE` কীভাবে একটা পুরো application জমিয়ে দিতে পারে?
৭. চার ধাপে expand–contract migration pattern বর্ণনা করুন।
৮. `INDEX (a, b, c)` থাকলে এর কোনগুলো সেটা ব্যবহার করে: `WHERE b=1`; `WHERE a=1 AND c=1`; `WHERE a=1 AND b=1`?
৯. Partial index কী আর কখন এটা একটা বড় জয়? একটা উদাহরণ দিন।
১০. কখন একটা Seq Scan সঠিক plan?
১১. `EXPLAIN ANALYZE`-এ `rows=` আর `actual rows=`-এর মধ্যে বড় ফারাক আপনাকে কী বলে?
১২. N+1 কী, ORM কেন এটা ঘটায়, আর তিনটা সমাধান দিন।
১৩. Crash recovery ছাড়া WAL আর কী সম্ভব করে? চারটার নাম বলুন।
১৪. পরিত্যক্ত replication slot কেন বিপজ্জনক?
১৫. Denormalise করার তিনটা বৈধ কারণ দিন। কোনটা আসলে performance নয়, সঠিকতার ব্যাপার?

---

## ৯.১৬ মূল কথাগুলো

- **Database-এ constraint ঘোষণা করুন।** এটাই একমাত্র স্তর যেটা এড়ানো যায় না।
- **বেশিরভাগ কাজে Read Committed; ইচ্ছাকৃতভাবে উপরে উঠুন** — আর সবসময় serialization failure আর deadlock retry করুন
- **MVCC মানে পাঠক কখনো লেখককে আটকায় না** — আর এর মানে আপনাকে VACUUM-কে সম্মান করতে হবে
- **দীর্ঘ transaction বেশিরভাগ Postgres-যন্ত্রণার মূল**: lock, bloat, আটকে যাওয়া vacuum
- **আপনার আসল query-র জন্য index করুন।** Composite-এর ক্রম: সমতা → range → sort। Partial আর covering index কম ব্যবহৃত।
- **`EXPLAIN (ANALYZE, BUFFERS)`** — অনুমান করা আর আসল row তুলনা করুন; ওই ফারাকটাই বেশিরভাগ খারাপ plan ব্যাখ্যা করে
- **N+1 শিল্পের সবচেয়ে সাধারণ performance bug।** Lazy loading মেরে ফেলুন।
- **Migration সবচেয়ে বিপজ্জনক নিয়মিত operation** — expand/contract, `CONCURRENTLY`, ছোট `lock_timeout`
- **যে backup আপনি restore করেননি সেটা backup নয়।** ত্রৈমাসিক মহড়া করুন আর সময় মাপুন।
- **Replica eventually consistent** — read ইচ্ছাকৃতভাবে পাঠান
- আপনি যত আগে ভাবেন তারও অনেক আগে **আপনার একটা connection pooler লাগবে**
- **PostgreSQL আপনার search engine, time-series store, geo store আর queue হতে পারে** — কম সিস্টেম সত্যিকারের architecture

---

**পরবর্তী:** [অধ্যায় ১০ — NoSQL Architecture](10-nosql-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 09](../09-database-architecture.md) · **[সূচিপত্র](README.md)**
