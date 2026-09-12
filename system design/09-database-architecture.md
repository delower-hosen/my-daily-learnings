# Chapter 09 — Database Architecture (Relational) 🟢

> The database is usually the hardest thing in your system to change, the first thing to become a bottleneck, and the last thing anyone wants to touch.
> An architect who understands databases deeply is worth three who do not.

Examples use PostgreSQL because it is the best default choice for most systems in 2026, but the concepts transfer to SQL Server, MySQL and Oracle.

---

## 9.1 ACID — what it actually guarantees

| Letter | Meaning | What breaks without it |
|--------|---------|------------------------|
| **A — Atomicity** | All operations in a transaction succeed, or none do | A transfer debits one account and never credits the other |
| **C — Consistency** | The database moves from one valid state to another (constraints hold) | Orphaned rows, negative stock, invalid foreign keys |
| **I — Isolation** | Concurrent transactions do not corrupt each other | Two users buy the last item; both succeed |
| **D — Durability** | Once committed, it survives a crash | "Payment successful" then a power cut, and the payment is gone |

**A note on "C":** ACID's C is often called the weakest letter — it really means "the database enforces the constraints *you* declared". Your business invariants are your job. Declare what you can (`CHECK`, `FOREIGN KEY`, `UNIQUE`, `NOT NULL`) — **the database is the last line of defence, and it is the only one that is never bypassed.**

```sql
-- Let the database enforce what it can. Application code has bugs; constraints do not.
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

That last composite `CHECK` encodes a real business rule in the schema. No code path can violate it — not a script, not a migration, not a junior's `UPDATE` in production.

---

## 9.2 Transactions

```sql
BEGIN;
  UPDATE accounts SET balance = balance - 100 WHERE id = 1;
  UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;   -- or ROLLBACK
```

### Practical rules for transactions

1. **Keep them short.** A transaction holds locks. Long transactions block others and (in Postgres) prevent `VACUUM` from cleaning up — which causes table bloat.
2. **Never do I/O inside a transaction.** No HTTP calls, no file writes, no `sleep`. A 3-second vendor call inside a transaction holds locks for 3 seconds.
3. **Never wait for a human** inside a transaction.
4. **Acquire locks in a consistent order** across your codebase (this is how you prevent deadlocks).
5. **Set a `statement_timeout`** so a runaway query cannot hold locks forever.

```python
# WRONG — a remote call inside a transaction
async with db.transaction():
    order = await db.save(order)
    await payment_gateway.charge(...)     # 2 s network call, holding locks
    await db.update(order, status="paid")

# RIGHT — transaction, then I/O, then transaction (or use the Outbox pattern)
async with db.transaction():
    order = await db.save(order)          # fast
result = await payment_gateway.charge(...)  # slow, no locks held
async with db.transaction():
    await db.update(order, status="paid" if result.ok else "failed")
```

```sql
-- Safety nets worth setting globally
SET statement_timeout = '30s';
SET idle_in_transaction_session_timeout = '60s';  -- kills forgotten open transactions
SET lock_timeout = '5s';
```

---

## 9.3 Isolation levels 🟢

**The problem:** transactions running at the same time can see each other's half-finished work. Isolation levels define how much interference is allowed.

### The anomalies

**1. Dirty read** — reading uncommitted data

```
T1: UPDATE accounts SET balance = 0 WHERE id = 1;   (not committed)
T2: SELECT balance FROM accounts WHERE id = 1;      → reads 0
T1: ROLLBACK;                                        → that 0 never existed
```

**2. Non-repeatable read** — the same row gives different values within one transaction

```
T1: SELECT balance FROM accounts WHERE id = 1;   → 500
T2: UPDATE accounts SET balance = 300 WHERE id = 1; COMMIT;
T1: SELECT balance FROM accounts WHERE id = 1;   → 300  (changed mid-transaction!)
```

**3. Phantom read** — the same query returns different *rows*

```
T1: SELECT count(*) FROM orders WHERE total > 100;   → 5
T2: INSERT INTO orders (total) VALUES (200); COMMIT;
T1: SELECT count(*) FROM orders WHERE total > 100;   → 6  (a phantom appeared)
```

**4. Lost update** — two transactions read, modify and write the same row; one change vanishes

```
T1: SELECT stock FROM items WHERE id=1;   → 10
T2: SELECT stock FROM items WHERE id=1;   → 10
T1: UPDATE items SET stock = 9 WHERE id=1; COMMIT;
T2: UPDATE items SET stock = 9 WHERE id=1; COMMIT;   ← should be 8. One sale vanished.
```

**5. Write skew** — the subtle one that catches experts

```
Rule: at least one doctor must always be on call.
Currently: Alice and Bob, both on call.

T1 (Alice): SELECT count(*) FROM doctors WHERE on_call = true;  → 2, fine
T2 (Bob):   SELECT count(*) FROM doctors WHERE on_call = true;  → 2, fine
T1: UPDATE doctors SET on_call = false WHERE name='Alice'; COMMIT;
T2: UPDATE doctors SET on_call = false WHERE name='Bob';   COMMIT;

→ ZERO doctors on call. Each transaction was individually valid.
  They touched DIFFERENT rows, so no conflict was detected.
```

Write skew is why "just use transactions" is not always enough, and why `SERIALIZABLE` exists.

### The levels

| Level | Dirty read | Non-repeatable | Phantom | Lost update | Write skew |
|-------|-----------|----------------|---------|-------------|------------|
| **Read Uncommitted** | ✅ possible | ✅ | ✅ | ✅ | ✅ |
| **Read Committed** (PG default) | ❌ prevented | ✅ possible | ✅ possible | ✅ possible | ✅ possible |
| **Repeatable Read** (PG = Snapshot) | ❌ | ❌ | ❌* | ❌ | ✅ possible |
| **Serializable** | ❌ | ❌ | ❌ | ❌ | ❌ |

\* PostgreSQL's Repeatable Read prevents phantoms too (it is snapshot isolation), unlike the SQL standard's minimum.

### What to use in practice

```sql
-- READ COMMITTED (default) — 95% of your work
-- Each STATEMENT sees a fresh snapshot. Good throughput. Good enough for CRUD.

-- REPEATABLE READ — when a transaction must see one consistent snapshot
BEGIN ISOLATION LEVEL REPEATABLE READ;
  -- a report reading 8 tables sees them all as of the same instant
COMMIT;

-- SERIALIZABLE — when correctness under concurrency is non-negotiable
BEGIN ISOLATION LEVEL SERIALIZABLE;
  -- PostgreSQL uses SSI (Serializable Snapshot Isolation): it does not lock,
  -- it DETECTS conflicts and aborts one transaction with a serialization_failure.
COMMIT;
```

> **Critical operational point:** under `SERIALIZABLE`, PostgreSQL will abort transactions with SQLSTATE `40001`. **Your application MUST retry them.** If you enable SERIALIZABLE without retry logic, you have simply added random failures.

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

### The cheaper alternatives to SERIALIZABLE

Most of the time you do not need full serializability — you need to protect one invariant:

```sql
-- 1. Atomic read-modify-write (prevents lost update, no extra isolation needed)
UPDATE items SET stock = stock - 1 WHERE id = 1 AND stock > 0;
-- check rows affected: 0 means it was out of stock

-- 2. Pessimistic lock (SELECT ... FOR UPDATE)
BEGIN;
  SELECT stock FROM items WHERE id = 1 FOR UPDATE;   -- other txns wait here
  UPDATE items SET stock = stock - 1 WHERE id = 1;
COMMIT;

-- 3. Optimistic lock (version column) — best for web apps, no held locks
UPDATE items SET stock = 9, version = 6 WHERE id = 1 AND version = 5;
-- 0 rows affected → someone else changed it → re-read and retry

-- 4. A constraint that makes the bad state impossible
ALTER TABLE items ADD CONSTRAINT stock_non_negative CHECK (stock >= 0);
-- now even a bug cannot oversell; the transaction simply fails
```

> **Preference order for web applications: constraint > atomic UPDATE > optimistic lock > pessimistic lock > SERIALIZABLE.** Go down the list only as far as you must.

---

## 9.4 MVCC — how PostgreSQL really works 🟢

**Multi-Version Concurrency Control:** instead of locking rows for reads, keep **multiple versions** of each row.

```
Row id=1 over time:

  version 1: (id=1, balance=500, xmin=100, xmax=105)   ← created by txn 100, deleted by 105
  version 2: (id=1, balance=300, xmin=105, xmax=null)  ← created by txn 105, still live

A transaction with snapshot at txn 103 sees version 1.
A transaction with snapshot at txn 107 sees version 2.
Neither blocks the other.
```

> **The golden rule that follows: readers never block writers, and writers never block readers.** Only writer-vs-writer on the *same row* blocks.

This is the single biggest reason PostgreSQL handles mixed read/write workloads so well.

### The cost: dead tuples and VACUUM

An `UPDATE` in PostgreSQL is really "insert a new version + mark the old one dead". A `DELETE` just marks dead. **Dead rows stay on disk** until vacuumed.

```
UPDATE the same row 1,000 times → 1,000 dead tuples → the table grows
→ sequential scans read dead rows → everything slows down → "bloat"
```

**`VACUUM`** reclaims dead tuples for reuse. **`autovacuum`** does it automatically — usually well, but it can fall behind on write-heavy tables.

```sql
-- See the damage
SELECT relname,
       n_live_tup, n_dead_tup,
       round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 10;

-- Tune autovacuum for a hot table (defaults are too lazy for high-write tables)
ALTER TABLE verification_sessions SET (
    autovacuum_vacuum_scale_factor  = 0.02,   -- vacuum at 2% dead (default 20%)
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_vacuum_cost_limit    = 2000    -- let it work faster
);
```

### What blocks VACUUM (and therefore causes bloat)

1. **Long-running transactions** — VACUUM cannot remove a version any open transaction might still need. An analyst's forgotten `BEGIN;` in psql can bloat your whole database.
2. **Idle-in-transaction connections** — same problem. Set `idle_in_transaction_session_timeout`.
3. **Unused replication slots** — a disconnected replica whose slot still exists holds back WAL **and** vacuum, and will eventually fill your disk. This is a classic production outage.
4. **Long-running queries on replicas** with `hot_standby_feedback=on`

### Transaction ID wraparound ⚪ (know it exists)

PostgreSQL transaction IDs are 32-bit and wrap around. If autovacuum cannot freeze old rows in time, the database will **shut down to protect your data**. It is rare, catastrophic, and entirely preventable — monitor `age(datfrozenxid)` and alert well before 1.5 billion.

---

## 9.5 Locks and deadlocks 🟢

### Lock levels (simplified)

| Lock | Acquired by | Conflicts with |
|------|------------|----------------|
| `ACCESS SHARE` | `SELECT` | Only `ACCESS EXCLUSIVE` |
| `ROW SHARE` | `SELECT ... FOR UPDATE` | `EXCLUSIVE`, `ACCESS EXCLUSIVE` |
| `ROW EXCLUSIVE` | `INSERT`, `UPDATE`, `DELETE` | `SHARE` and above |
| `SHARE` | `CREATE INDEX` (non-concurrent) | Writes |
| `ACCESS EXCLUSIVE` | `ALTER TABLE`, `DROP`, `TRUNCATE`, `VACUUM FULL` | **Everything** |

> **The migration killer:** `ALTER TABLE` takes an `ACCESS EXCLUSIVE` lock. If it has to wait behind a long query, it **queues** — and every subsequent query queues behind *it*. One schema change on a busy table can freeze your entire application in seconds. Always run migrations with a short `lock_timeout` and retry.

```sql
-- Safe migration pattern
SET lock_timeout = '3s';
ALTER TABLE orders ADD COLUMN discount_code TEXT;   -- fails fast instead of freezing the app
```

### Safe vs unsafe schema changes (PostgreSQL 12+)

| Operation | Safe? | Notes |
|-----------|-------|-------|
| `ADD COLUMN` (nullable, or with a constant default) | ✅ | Fast metadata-only since PG 11 |
| `ADD COLUMN NOT NULL` with a volatile default | ❌ | Rewrites the whole table |
| `DROP COLUMN` | ✅ | Metadata only (space reclaimed later) |
| `ALTER COLUMN TYPE` | ❌ usually | Full rewrite + lock. Use a new column + backfill + swap. |
| `ADD INDEX` | ❌ | Blocks writes — **use `CREATE INDEX CONCURRENTLY`** |
| `ADD CHECK / FOREIGN KEY` | ⚠️ | Use `NOT VALID` then `VALIDATE CONSTRAINT` separately |
| `RENAME COLUMN` | ⚠️ | Instant, but breaks running application code — use expand/contract |

**The expand–contract (parallel change) migration pattern — memorise this:**

```
1. EXPAND    Add the new column/table. Deploy code that writes BOTH, reads OLD.
2. BACKFILL  Copy data in small batches (avoid one giant UPDATE).
3. MIGRATE   Deploy code that reads NEW (still writes both).
4. CONTRACT  Deploy code that only uses NEW. Then drop the OLD column.
```

Four deploys, zero downtime, reversible at every step. This is how you change a schema on a live system.

### Deadlocks

```
T1: UPDATE accounts SET ... WHERE id = 1;    -- holds lock on row 1
T2: UPDATE accounts SET ... WHERE id = 2;    -- holds lock on row 2
T1: UPDATE accounts SET ... WHERE id = 2;    -- waits for T2
T2: UPDATE accounts SET ... WHERE id = 1;    -- waits for T1  → DEADLOCK
```

PostgreSQL detects it after `deadlock_timeout` (default 1 s) and kills one transaction with SQLSTATE `40P01`.

**Prevention:**
1. **Always acquire locks in a consistent order** (e.g. ascending primary key). This alone eliminates most deadlocks.
2. Keep transactions short
3. Use a single atomic statement instead of read-then-write where possible
4. **Retry on `40P01`** — deadlocks are a normal, expected condition in a busy system, not a bug to be shocked by

```python
# Consistent lock ordering prevents the classic transfer deadlock
async def transfer(from_id: UUID, to_id: UUID, amount: Decimal) -> None:
    first, second = sorted([from_id, to_id])            # ALWAYS the same order
    async with db.transaction():
        await db.execute("SELECT 1 FROM accounts WHERE id = $1 FOR UPDATE", first)
        await db.execute("SELECT 1 FROM accounts WHERE id = $1 FOR UPDATE", second)
        await db.execute("UPDATE accounts SET balance = balance - $2 WHERE id = $1",
                         from_id, amount)
        await db.execute("UPDATE accounts SET balance = balance + $2 WHERE id = $1",
                         to_id, amount)
```

### Finding what is blocking what

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

Keep this query in your runbook. You will need it at 3 AM.

---

## 9.6 Indexes 🟢

**An index is a separate data structure that lets the database find rows without scanning the whole table.**

Real-life: the index at the back of a book. Without it, finding "MVCC" means reading 400 pages. With it, you jump straight there.

### B-tree (the default, and 95% of what you need)

```sql
CREATE INDEX idx_sessions_tenant_created
    ON verification_sessions (tenant_id, created_at DESC);
```

Good for: `=`, `<`, `>`, `BETWEEN`, `IN`, `IS NULL`, `ORDER BY`, and `LIKE 'prefix%'`.

### Composite indexes and the leftmost-prefix rule ⭐

```sql
CREATE INDEX idx_abc ON t (a, b, c);
```

| Query | Uses the index? |
|-------|-----------------|
| `WHERE a = 1` | ✅ |
| `WHERE a = 1 AND b = 2` | ✅ |
| `WHERE a = 1 AND b = 2 AND c = 3` | ✅ fully |
| `WHERE b = 2` | ❌ (can't skip `a`) |
| `WHERE a = 1 AND c = 3` | ⚠️ partially — uses `a`, filters `c` |

**Column order rule:** put **equality** columns first, then **range** columns, then **sort** columns.

```sql
-- Query: WHERE tenant_id = ? AND status = ? AND created_at > ? ORDER BY created_at DESC
CREATE INDEX ON sessions (tenant_id, status, created_at DESC);
--                         equality    equality  range + sort
```

### Covering indexes (index-only scans)

```sql
CREATE INDEX idx_sessions_lookup
    ON verification_sessions (tenant_id, status)
    INCLUDE (score, created_at);       -- extra columns stored in the leaf, not the key
```

Now `SELECT score, created_at FROM sessions WHERE tenant_id=? AND status=?` is answered **entirely from the index** — it never touches the table. This can be a 10× improvement on hot queries.

### Partial indexes ⭐ (hugely underused)

```sql
-- Only 0.5% of sessions are pending, but that's what you query constantly
CREATE INDEX idx_sessions_pending
    ON verification_sessions (created_at)
    WHERE status = 'pending';
```

A tiny index instead of a huge one: smaller, faster, cheaper to maintain. Perfect for soft-delete columns (`WHERE deleted_at IS NULL`), status queues, and any highly selective flag.

### The other index types

| Type | Use for | Example |
|------|---------|---------|
| **B-tree** | Default — equality, ranges, sorting | `(tenant_id, created_at)` |
| **Hash** | Equality only | Rarely worth it; B-tree is nearly as good and more flexible |
| **GIN** | **Multi-value columns**: JSONB, arrays, full-text search | `USING GIN (tags)`, `USING GIN (doc jsonb_path_ops)`, `USING GIN (to_tsvector('english', body))` |
| **GiST** | Geometric, ranges, nearest-neighbour, exclusion constraints | `USING GIST (location)`, booking-overlap prevention |
| **BRIN** | **Huge tables with naturally ordered data** (time-series) | `USING BRIN (created_at)` — an index 1000× smaller than B-tree |
| **SP-GiST** | Non-balanced structures (quadtrees, IP prefixes) | Rare |

```sql
-- GIN for JSONB
CREATE INDEX idx_meta ON sessions USING GIN (metadata jsonb_path_ops);
SELECT * FROM sessions WHERE metadata @> '{"channel": "mobile"}';

-- GIN for full-text search
CREATE INDEX idx_fts ON documents USING GIN (to_tsvector('english', content));
SELECT * FROM documents WHERE to_tsvector('english', content) @@ plainto_tsquery('liveness');

-- BRIN for an append-only 2 TB event table
CREATE INDEX idx_events_time ON events USING BRIN (created_at) WITH (pages_per_range = 64);
-- B-tree here would be ~60 GB. BRIN is ~50 MB. For range scans it is nearly as fast.

-- GiST exclusion constraint — prevents double-booking AT THE DATABASE LEVEL
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE room_bookings ADD CONSTRAINT no_double_booking
    EXCLUDE USING GIST (room_id WITH =, during WITH &&);
```

That last one is worth knowing: it makes overlapping bookings **impossible**, with no application logic and no race conditions.

### The cost of indexes

Every index:
- Makes **every INSERT/UPDATE/DELETE slower** (the index must be maintained)
- Takes disk space (often more than the table)
- Must be kept in memory to be fast
- Must be considered by the planner (more indexes = slower planning)

> **Rule: index for your actual queries, not "just in case".** A table with 15 indexes has a write problem.

### Finding unused and missing indexes

```sql
-- UNUSED indexes (candidates for deletion) — run on production after a full business cycle
SELECT schemaname, relname AS table, indexrelname AS index,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       idx_scan AS times_used
FROM pg_stat_user_indexes
WHERE idx_scan < 50
  AND indexrelid NOT IN (SELECT conindid FROM pg_constraint WHERE contype IN ('p','u'))
ORDER BY pg_relation_size(indexrelid) DESC;

-- Tables doing lots of sequential scans (candidates for a new index)
SELECT relname, seq_scan, seq_tup_read, idx_scan,
       seq_tup_read / NULLIF(seq_scan, 0) AS avg_rows_per_seq_scan
FROM pg_stat_user_tables
WHERE seq_scan > 1000
ORDER BY seq_tup_read DESC;
```

### Things that silently disable your index

```sql
-- ❌ Function on the column
WHERE LOWER(email) = 'a@b.com'
-- ✅ Fix: an expression index
CREATE INDEX ON users (LOWER(email));

-- ❌ Type mismatch / implicit cast
WHERE user_id = '123'            -- user_id is BIGINT, '123' is text
-- ✅ Pass the right type from the application

-- ❌ Leading wildcard
WHERE name LIKE '%delower'
-- ✅ Use a trigram index
CREATE EXTENSION pg_trgm;
CREATE INDEX ON users USING GIN (name gin_trgm_ops);

-- ❌ OR across different columns often defeats a single index
WHERE email = ? OR phone = ?
-- ✅ UNION of two indexed queries, or separate indexes + bitmap OR
```

---

## 9.7 The query planner and EXPLAIN ANALYZE 🟢

**PostgreSQL is cost-based:** it estimates the cost of several plans and picks the cheapest, using statistics collected by `ANALYZE`.

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

### How to read it (the four things that matter)

1. **Read from the innermost/deepest node outward.** That is the execution order.
2. **Compare `rows=` (estimate) with `actual rows=`.** A big gap means the statistics are wrong → run `ANALYZE`, or increase `default_statistics_target` on that column. Bad estimates are the #1 cause of bad plans.
3. **`loops=N`** — multiply `actual time` by `loops` to get the real total for that node.
4. **`Buffers: shared hit` vs `read`** — `hit` is from cache (fast), `read` is from disk (slow). High `read` means your working set does not fit in `shared_buffers`.

### Scan types, from best to worst (in context)

| Node | Meaning | When it is fine |
|------|---------|-----------------|
| **Index Only Scan** | Answered entirely from the index | Best case |
| **Index Scan** | Index lookup, then fetch the row | Good for selective queries |
| **Bitmap Heap Scan** | Collect matching row locations, then fetch in disk order | Good for medium selectivity |
| **Seq Scan** | Read the whole table | **Correct** for small tables or when returning >5–10% of rows. A problem on a large table with a selective filter. |

### Join types

| Join | How | Best when |
|------|-----|-----------|
| **Nested Loop** | For each outer row, look up inner | Small outer set + indexed inner |
| **Hash Join** | Build a hash of one side, probe with the other | Large unsorted sets; needs memory (`work_mem`) |
| **Merge Join** | Both sides sorted, walk together | Both already sorted (e.g. by index) |

### Red flags in a plan

```
❌ Seq Scan on a large table with a selective WHERE     → missing index
❌ rows=1 but actual rows=450000                        → stale stats; run ANALYZE
❌ Nested Loop with loops=100000                        → should be a Hash Join; check stats
❌ Sort Method: external merge Disk: 84320kB            → raise work_mem, or add a sorted index
❌ Rows Removed by Filter: 2000000                      → the index isn't selective enough
❌ Buffers: shared read=50000                           → working set exceeds RAM
```

### Statistics and hot-path habits

```sql
ANALYZE verification_sessions;                          -- refresh stats
ALTER TABLE sessions ALTER COLUMN status SET STATISTICS 1000;   -- more detail on a skewed column
CREATE STATISTICS sess_corr (dependencies) ON tenant_id, status FROM sessions;  -- correlated columns
```

```sql
-- Find your worst queries in production (requires pg_stat_statements)
SELECT substring(query, 1, 80) AS query,
       calls,
       round(total_exec_time::numeric, 0) AS total_ms,
       round(mean_exec_time::numeric, 2)  AS mean_ms,
       rows
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

> **Optimise by total time, not by mean time.** A 5 ms query called 2 million times costs more than a 3-second report run twice a day.

### The N+1 query problem — the most common performance bug in the industry

```python
# 1 query for the list...
sessions = await db.fetch("SELECT * FROM sessions WHERE tenant_id = $1", tid)
for s in sessions:                       # ...+ 1 query per row = 101 round trips
    customer = await db.fetch_one("SELECT * FROM customers WHERE id = $1", s.customer_id)
```

101 round trips × 0.5 ms = 50 ms of pure network, before any work. With 1,000 rows it is a 500 ms page.

```python
# FIX 1: one join
rows = await db.fetch("""
    SELECT s.*, c.name AS customer_name
    FROM sessions s JOIN customers c ON c.id = s.customer_id
    WHERE s.tenant_id = $1""", tid)

# FIX 2: batch the second query (when a join is awkward)
ids = {s.customer_id for s in sessions}
customers = {c.id: c for c in await db.fetch(
    "SELECT * FROM customers WHERE id = ANY($1)", list(ids))}

# FIX 3 (ORM): eager loading
#   SQLAlchemy: .options(selectinload(Session.customer))
#   EF Core:    .Include(s => s.Customer)
```

> **ORMs cause N+1 by default through lazy loading.** Turn lazy loading off in production code, or log and alert on query counts per request. This one habit will make you look like a performance wizard.

---

## 9.8 WAL — Write-Ahead Log 🟢

**The rule: write the change to a log *before* changing the data pages.**

```
1. Transaction modifies a page in memory (shared_buffers)
2. The change is written to the WAL and fsync'd to disk
3. COMMIT returns to the client            ← durability achieved HERE
4. Later, a checkpoint writes the dirty pages to the data files
```

**Why:** sequential WAL writes are fast; random data-page writes are slow. If the server crashes, replay the WAL from the last checkpoint and you lose nothing.

### What the WAL also enables

| Feature | How it uses the WAL |
|---------|--------------------|
| **Crash recovery** | Replay from the last checkpoint |
| **Streaming replication** | Ship WAL records to replicas |
| **Point-in-time recovery (PITR)** | Base backup + WAL archive → restore to any second |
| **Logical replication / CDC** | Decode the WAL into row changes (Debezium) |

### Key settings

```ini
wal_level = replica              # or 'logical' for CDC/Debezium
synchronous_commit = on          # off = faster but you can lose the last ~200 ms on a crash
max_wal_size = 4GB               # larger = fewer checkpoints = smoother I/O
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9   # spread checkpoint I/O out
archive_mode = on
archive_command = 'wal-g wal-push %p'
```

> **`synchronous_commit = off` is a legitimate performance lever** for non-critical, high-volume writes (analytics events, logs). It keeps atomicity and consistency but risks losing the last fraction of a second of commits on a crash. You can even set it **per transaction** — strict for payments, relaxed for click tracking. Knowing this is a mark of real database fluency.

### Backups — the part people get wrong

```
Types:
  Logical  (pg_dump)        — portable, slow to restore, no PITR. Fine under ~50 GB.
  Physical (pg_basebackup)  — fast restore, enables PITR with WAL archiving. Use for real systems.
  Tools: pgBackRest, WAL-G, Barman
```

> **A backup you have never restored is not a backup — it is a hope.**
> Schedule a **quarterly restore drill**, time it, and write down the measured RTO. Most teams discover their "1 hour" restore is actually 9 hours, and they discover it during an incident.

---

## 9.9 Replication and read replicas 🟢

(Concepts in Chapter 04 §4.8; here is the PostgreSQL reality.)

### Physical streaming replication (the standard)

```ini
# Primary
wal_level = replica
max_wal_senders = 10
# Optional: guarantee one synchronous standby
synchronous_standby_names = 'ANY 1 (replica1, replica2)'
```

```sql
-- Measure replication lag from the primary
SELECT client_addr, state, sent_lsn, replay_lsn,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
       replay_lag
FROM pg_stat_replication;
```

### Using read replicas correctly

```python
class Database:
    async def read(self, sql, *args, consistent: bool = False):
        pool = self._primary if consistent else self._replica    # explicit choice
        return await pool.fetch(sql, *args)

    async def write(self, sql, *args):
        return await self._primary.execute(sql, *args)
```

**Route to the primary when:**
- Inside a transaction that also writes
- Immediately after the user's own write (**read-your-writes**, Chapter 05)
- Anything where staleness is a correctness problem (balances, permissions, quota checks)

**Route to replicas for:** dashboards, reports, search, list views, exports, and anything analytical.

### Replication slots — the double-edged sword

A slot guarantees the primary keeps WAL until the replica has consumed it. If the replica dies and the slot remains, **WAL accumulates until the primary's disk fills and the database stops**. This is one of the most common ways to take down a Postgres cluster.

```sql
-- Monitor this. Alert on it.
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

Set `max_slot_wal_keep_size` to bound the damage.

### Logical replication

Replicates **row changes**, not disk blocks. Enables: replicating a subset of tables, cross-version replication (this is how you do near-zero-downtime major upgrades), and CDC to Kafka.

### Connection pooling — mandatory at scale ⭐

Each PostgreSQL connection is an OS process using ~5–10 MB. 500 connections is a dead server.

```
App (500 connections) ──► PgBouncer ──► PostgreSQL (25 real connections)
```

| PgBouncer mode | Behaviour | Notes |
|---|---|---|
| `session` | Connection held for the client's whole session | Safest, least pooling benefit |
| **`transaction`** | Connection returned after each transaction | **The useful mode.** Breaks session-level features: prepared statements (unless configured), `SET`, advisory locks, `LISTEN/NOTIFY`. |
| `statement` | Returned after each statement | Very restrictive |

> If you run serverless functions or an autoscaled fleet against Postgres, **you need a pooler**. This is the #1 "we scaled the app and killed the database" surprise (Chapter 04).

---

## 9.10 Table partitioning 🟡

Splitting one large table into smaller physical pieces, transparently.

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

**What you gain:**
- **Partition pruning** — `WHERE created_at > '2026-10-01'` reads one partition instead of the whole table
- **Instant deletion of old data** — `DROP TABLE verification_events_2026_03` is instant; `DELETE FROM ... WHERE created_at < ...` takes hours and creates enormous bloat
- Smaller indexes per partition; `VACUUM` works per partition
- Different storage tiers per partition (old months on cheaper disks)

**What you pay:**
- **The partition key must be in the primary key and in most queries**, or you lose pruning and query every partition
- Automation needed to create future partitions (use `pg_partman`)
- Cross-partition queries and unique constraints across partitions are limited

> **The classic use case is time-series data with a retention policy.** If you have a big append-only table with a "delete after N days" rule, partitioning by time is almost always right — the `DROP TABLE` alone justifies it.

---

## 9.11 Normalisation and denormalisation 🟢

### The normal forms, in plain English

| Form | Rule | Example violation |
|------|------|-------------------|
| **1NF** | Atomic values, no repeating groups | `phone_numbers: "123, 456, 789"` in one column |
| **2NF** | 1NF + every non-key column depends on the **whole** key | In `(order_id, product_id)`, storing `product_name` (depends only on product) |
| **3NF** | 2NF + no column depends on another non-key column | Storing both `customer_id` and `customer_city` in `orders` |
| **BCNF** | Stricter 3NF | Rare edge cases |

> **Practical rule: normalise to 3NF by default.** It is the shape that prevents update anomalies. Then denormalise *deliberately*, with a written reason.

### When to denormalise

```sql
-- 1. Read performance — an expensive join on a hot path
ALTER TABLE orders ADD COLUMN customer_name TEXT;   -- avoid joining customers

-- 2. Precomputed aggregates
ALTER TABLE customers ADD COLUMN total_orders INT NOT NULL DEFAULT 0,
                      ADD COLUMN lifetime_value NUMERIC(12,2) NOT NULL DEFAULT 0;

-- 3. Historical snapshots — THIS ONE IS NOT DENORMALISATION, IT IS CORRECTNESS
ALTER TABLE order_lines ADD COLUMN unit_price_at_purchase NUMERIC(10,2) NOT NULL;
-- The product price changes tomorrow. The invoice must NOT change. Ever.
```

> **Point 3 is important and frequently misunderstood.** Copying the price into the order line is not duplication — the order line records *a different fact* (the price at that moment). Any figure on a legal document (invoice, contract, statement) must be **snapshotted**, not joined.

**The cost of denormalisation:** every copy must be kept in sync. Use triggers, application code, or scheduled jobs — and accept that they will drift. Add a reconciliation job that checks and reports drift.

### Materialised views — denormalisation with less pain

```sql
CREATE MATERIALIZED VIEW tenant_daily_stats AS
SELECT tenant_id,
       date_trunc('day', created_at) AS day,
       count(*)                                      AS total,
       count(*) FILTER (WHERE status = 'passed')     AS passed,
       avg(score) FILTER (WHERE score IS NOT NULL)   AS avg_score
FROM verification_sessions
GROUP BY 1, 2;

CREATE UNIQUE INDEX ON tenant_daily_stats (tenant_id, day);   -- required for CONCURRENTLY

REFRESH MATERIALIZED VIEW CONCURRENTLY tenant_daily_stats;    -- no read blocking
```

A dashboard query that took 8 seconds now takes 4 ms. Refresh on a schedule that matches how fresh the business actually needs it.

---

## 9.12 Choosing a relational database 🟡

| | **PostgreSQL** | **MySQL** | **SQL Server** |
|---|---|---|---|
| Licence | Free, permissive | Free (GPL) / Oracle | Commercial |
| Strengths | Extensions (PostGIS, pgvector, TimescaleDB), JSONB, full-text, rich indexes, strict correctness | Very fast simple reads, huge install base, mature replication | Superb tooling, T-SQL, deep .NET integration |
| Weaknesses | Connection-per-process (needs a pooler), vacuum tuning | Historically lax defaults; weaker SQL features | Cost; Windows-centric heritage |
| Best for | **Most new systems** | Read-heavy web, existing LAMP estates | .NET shops, existing Microsoft estates |

> **Default recommendation for a new system: PostgreSQL.** It is free, extremely capable, correct by default, and its extension ecosystem means it can serve as your search engine (full-text), time-series store (TimescaleDB), geospatial store (PostGIS), vector store (pgvector) and queue (`SKIP LOCKED`) before you need a separate system for any of them. **Fewer systems is a real architectural win.**

---

## 9.13 Common mistakes

1. **N+1 queries** — the single most common performance bug, usually caused by ORM lazy loading
2. **No index on foreign keys** — makes joins and cascading deletes slow, and causes lock contention
3. **Too many indexes** — writes crawl; nobody notices until it is bad
4. **`SELECT *`** — fetches unused columns, breaks index-only scans, breaks when a column is added
5. **Long transactions** — hold locks, block vacuum, cause bloat
6. **Network calls inside transactions** — locks held for the duration of an HTTP timeout
7. **`ALTER TABLE` without `lock_timeout`** — one migration freezes the whole application
8. **Adding an index without `CONCURRENTLY`** on a live table — blocks writes for minutes
9. **`SERIALIZABLE` without retry logic** — random unexplained failures
10. **Using `float` for money** — `0.1 + 0.2 != 0.3`. Use `NUMERIC`/`DECIMAL`, or integer cents.
11. **`TIMESTAMP` without time zone** — always use `TIMESTAMPTZ` and store UTC
12. **Reading from a replica right after writing** — the user sees stale data
13. **Abandoned replication slots** — the primary's disk fills and the database stops
14. **Never testing a restore** — discovering your backup is broken during an outage
15. **No connection pooler** with an autoscaled app tier

---

## 9.14 Architect's checklist

- [ ] Constraints declared in the schema (NOT NULL, CHECK, FK, UNIQUE) — not only in code
- [ ] Money is `NUMERIC`; timestamps are `TIMESTAMPTZ` in UTC; IDs are UUIDv7/ULID or bigint
- [ ] Indexes match actual query patterns; composite column order is equality → range → sort
- [ ] Foreign keys are indexed
- [ ] `pg_stat_statements` enabled; top queries by **total** time reviewed regularly
- [ ] No N+1: lazy loading disabled or query-count alerting in place
- [ ] Isolation level chosen deliberately; retry logic for `40001` and `40P01`
- [ ] Locks always acquired in a consistent order
- [ ] Transactions short; no I/O inside; `statement_timeout` and `idle_in_transaction_session_timeout` set
- [ ] Migrations use expand/contract, `CONCURRENTLY`, `NOT VALID` + `VALIDATE`, and a short `lock_timeout`
- [ ] Autovacuum tuned for hot tables; bloat and long transactions monitored
- [ ] WAL archiving + PITR configured; **restore drill performed and timed**
- [ ] Replication lag and replication slot retention monitored and alerted
- [ ] Connection pooler in place, sized with Little's Law
- [ ] Read/write routing explicit in code; read-your-writes handled
- [ ] Retention strategy: partitioning or archiving for large time-series tables
- [ ] PII columns identified; encryption and access logging decided (Chapter 17)

---

## 9.15 Self-test

1. What does the "C" in ACID actually guarantee, and what is your job?
2. Explain write skew with an example. Which isolation level prevents it?
3. Why must you add retry logic when you enable SERIALIZABLE?
4. Explain MVCC in three sentences. What is the golden rule it gives you?
5. What causes table bloat, and name three things that block VACUUM.
6. Why can one `ALTER TABLE` freeze an entire application?
7. Describe the expand–contract migration pattern in four steps.
8. Given `INDEX (a, b, c)`, which of these use it: `WHERE b=1`; `WHERE a=1 AND c=1`; `WHERE a=1 AND b=1`?
9. What is a partial index and when is it a big win? Give an example.
10. When is a Seq Scan the correct plan?
11. In `EXPLAIN ANALYZE`, what does a large gap between `rows=` and `actual rows=` tell you?
12. What is N+1, why do ORMs cause it, and give three fixes.
13. What does the WAL enable besides crash recovery? Name four things.
14. Why are abandoned replication slots dangerous?
15. Give three legitimate reasons to denormalise. Which one is actually about correctness, not performance?

---

## 9.16 Key takeaways

- **Declare constraints in the database.** It is the only layer that cannot be bypassed.
- **Read Committed for most work; escalate deliberately** — and always retry serialization failures and deadlocks
- **MVCC means readers never block writers** — and it means you must respect VACUUM
- **Long transactions are the root of most Postgres pain**: locks, bloat, blocked vacuum
- **Index for your real queries.** Composite order: equality → range → sort. Partial and covering indexes are underused.
- **`EXPLAIN (ANALYZE, BUFFERS)`** — compare estimated vs actual rows; that gap explains most bad plans
- **N+1 is the most common performance bug in the industry.** Kill lazy loading.
- **Migrations are the most dangerous routine operation** — expand/contract, `CONCURRENTLY`, short `lock_timeout`
- **A backup you have not restored is not a backup.** Drill it quarterly and time it.
- **Replicas are eventually consistent** — route reads deliberately
- **You need a connection pooler** long before you think you do
- **PostgreSQL can be your search engine, time-series store, geo store and queue** — fewer systems is real architecture

---

**Next:** [Chapter 10 — NoSQL Architecture](10-nosql-architecture.md)
