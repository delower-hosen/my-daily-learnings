# Deep Dive 08 — Transactions, Locking and SSI

**Prerequisite:** [Chapter 09 §9.3, §9.5](../09-database-architecture.md) · [Deep Dive 03](03-consistency-models-formally.md) · [Deep Dive 04](04-postgresql-mvcc-and-storage.md)

**What the map said:** *"Acquire locks in a consistent order. Keep transactions short. SERIALIZABLE requires retry logic. `ALTER TABLE` takes an ACCESS EXCLUSIVE lock."*

**What this deep dive does:** gives you the full table-lock conflict matrix and what each DDL statement actually takes, explains why row locks are *not* in the lock manager and what that implies, walks MultiXacts and their separate wraparound hazard, traces four deadlocks including two that look impossible, explains the DDL queue-blocking incident that takes down applications, gives the complete safe-migration catalogue, takes apart SSI's dangerous-structure detection with a traced example, and ends with the lock monitoring you need at 3 AM.

---

## Contents

```
1.  Two lock systems, not one
2.  Table-level locks: the eight modes
3.  The conflict matrix ⭐
4.  What each statement actually takes
5.  Row locks: four modes
6.  ⭐ Why row locks are not in the lock manager
7.  MultiXacts — when several transactions lock one row
8.  ⭐ MultiXact wraparound: the second wraparound nobody knows about
9.  The lock wait queue, and why it is FIFO
10. ⭐ The DDL queue-blocking incident
11. Deadlock detection: the wait-for graph
12. Traced deadlock 1 — the classic transfer
13. Traced deadlock 2 — foreign keys
14. Traced deadlock 3 — unique index insertion
15. Traced deadlock 4 — the unordered multi-row UPDATE
16. Why PostgreSQL has no lock escalation
17. Advisory locks
18. Safe DDL: the complete catalogue ⭐
19. CREATE INDEX CONCURRENTLY: how it really works
20. SSI: the mechanism ⭐
21. SIREAD locks and predicate granularity
22. Traced SSI scenario — the dangerous structure
23. SSI false positives, and DEFERRABLE
24. Retry patterns that work
25. Two-phase commit internals
26. Monitoring locks
27. The tuning summary
28. What an architect takes from this
```

---

## 1. Two lock systems, not one

PostgreSQL has two largely independent locking mechanisms, and confusing them is the source of most misunderstandings.

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. THE LOCK MANAGER (heavyweight locks)                          │
│    • Tracks: tables, indexes, relations, transactions, advisory  │
│    • Stored in SHARED MEMORY, a fixed-size hash table            │
│    • Has a wait queue and a deadlock detector                    │
│    • ⭐ Bounded size: max_locks_per_transaction × max_connections│
├──────────────────────────────────────────────────────────────────┤
│ 2. ROW LOCKS                                                     │
│    • ⭐ NOT in the lock manager. Stored IN THE TUPLE ITSELF.     │
│    • t_xmax + infomask bits (Deep Dive 04 §3)                    │
│    • ⭐ Effectively UNBOUNDED — lock 10 million rows if you like │
│    • Waiting is implemented by taking a lock-manager lock on the │
│      HOLDING TRANSACTION'S XID                                   │
└──────────────────────────────────────────────────────────────────┘
```

And, separately, a third mechanism that is not really locking at all:

```
┌──────────────────────────────────────────────────────────────────┐
│ 3. PREDICATE LOCKS (SIREAD) — only under SERIALIZABLE            │
│    • ⭐ Do NOT block anything, ever                              │
│    • They RECORD what a transaction read, so conflicts can be    │
│      DETECTED after the fact (§20)                               │
└──────────────────────────────────────────────────────────────────┘
```

> **The design insight in mechanism 2 is worth pausing on.** Storing row locks in the lock manager would require memory proportional to the number of locked rows — so `UPDATE` on 10 million rows would need 10 million lock entries. Instead, PostgreSQL writes the lock into the tuple (which it is already dirtying) and only creates *one* lock-manager entry per *waiting* transaction. Memory is bounded by concurrency, not by data volume.

---

## 2. Table-level locks: the eight modes

Ordered weakest to strongest.

| # | Mode | Acquired by |
|---|------|-------------|
| 1 | `ACCESS SHARE` | `SELECT` |
| 2 | `ROW SHARE` | `SELECT FOR UPDATE / FOR SHARE / FOR NO KEY UPDATE / FOR KEY SHARE` |
| 3 | `ROW EXCLUSIVE` | `INSERT`, `UPDATE`, `DELETE`, `MERGE` |
| 4 | `SHARE UPDATE EXCLUSIVE` | `VACUUM` (non-full), `ANALYZE`, `CREATE INDEX CONCURRENTLY`, `REINDEX CONCURRENTLY`, some `ALTER TABLE` variants |
| 5 | `SHARE` | `CREATE INDEX` (non-concurrent) |
| 6 | `SHARE ROW EXCLUSIVE` | `CREATE TRIGGER`, `ALTER TABLE ... ADD FOREIGN KEY`, some `ALTER TABLE` |
| 7 | `EXCLUSIVE` | `REFRESH MATERIALIZED VIEW CONCURRENTLY` |
| 8 | ⭐ `ACCESS EXCLUSIVE` | `ALTER TABLE` (most), `DROP TABLE`, `TRUNCATE`, `REINDEX`, `CLUSTER`, `VACUUM FULL`, `REFRESH MATERIALIZED VIEW` |

**The names describe what they permit, not what they block** — which is why they read backwards at first:

```
"ACCESS SHARE"    = "I am sharing access"        → the lightest
"ACCESS EXCLUSIVE"= "I need exclusive access"    → blocks EVERYTHING, including SELECT
"ROW EXCLUSIVE"   = "I exclusively modify rows"  → but several writers can hold it
```

```
⭐ ROW EXCLUSIVE does NOT conflict with itself. That is why many
   concurrent INSERT/UPDATE/DELETE statements run against one table
   without any table-level contention. All the contention is at the
   ROW level (§5).
```

---

## 3. The conflict matrix ⭐

Rows are the lock **requested**; columns are the lock **already held**. `X` means conflict (the requester waits).

```
                        │ AS │ RS │ RE │SUE │ SH │SRE │ EX │AE │
────────────────────────┼────┼────┼────┼────┼────┼────┼────┼───┤
ACCESS SHARE       (AS) │    │    │    │    │    │    │    │ X │
ROW SHARE          (RS) │    │    │    │    │    │    │ X  │ X │
ROW EXCLUSIVE      (RE) │    │    │    │    │ X  │ X  │ X  │ X │
SHARE UPDATE EXCL (SUE) │    │    │    │ X  │ X  │ X  │ X  │ X │
SHARE              (SH) │    │    │ X  │ X  │    │ X  │ X  │ X │
SHARE ROW EXCL    (SRE) │    │    │ X  │ X  │ X  │ X  │ X  │ X │
EXCLUSIVE          (EX) │    │ X  │ X  │ X  │ X  │ X  │ X  │ X │
ACCESS EXCLUSIVE   (AE) │ X  │ X  │ X  │ X  │ X  │ X  │ X  │ X │
```

### The five facts to extract from this table

```
1. ⭐ ACCESS EXCLUSIVE conflicts with EVERYTHING — including plain SELECT.
   This is why ALTER TABLE stops all reads (§10).

2. ⭐ ACCESS SHARE (SELECT) conflicts with ONLY ACCESS EXCLUSIVE.
   Readers are blocked by nothing except a table rewrite. This is MVCC
   working (Deep Dive 04 §4): readers never block writers and vice versa.

3. ⭐ ROW EXCLUSIVE does not self-conflict → concurrent DML is fine.

4. ⭐ SHARE UPDATE EXCLUSIVE self-conflicts → only ONE VACUUM, ANALYZE,
   or CREATE INDEX CONCURRENTLY per table at a time.

5. ⭐ SHARE conflicts with ROW EXCLUSIVE → a non-concurrent CREATE INDEX
   blocks all writes for its entire duration. Always use CONCURRENTLY.
```

---

## 4. What each statement actually takes

Keep this table. It answers "will this migration block my application?"

| Statement | Lock | Blocks |
|-----------|------|--------|
| `SELECT` | ACCESS SHARE | Nothing but DDL |
| `INSERT` / `UPDATE` / `DELETE` | ROW EXCLUSIVE | `CREATE INDEX`, DDL |
| `SELECT FOR UPDATE` | ROW SHARE + row locks | Other row lockers on the same rows |
| `CREATE INDEX` | ⭐ SHARE | **All writes** |
| `CREATE INDEX CONCURRENTLY` | ⭐ SHARE UPDATE EXCLUSIVE | Only VACUUM/ANALYZE/other CIC |
| `VACUUM` | SHARE UPDATE EXCLUSIVE | Other VACUUM, DDL |
| `VACUUM FULL` | ⭐ ACCESS EXCLUSIVE | **Everything** |
| `ANALYZE` | SHARE UPDATE EXCLUSIVE | Other VACUUM/ANALYZE |
| `ALTER TABLE ADD COLUMN` | ⭐ ACCESS EXCLUSIVE | **Everything** (but briefly — §18) |
| `ALTER TABLE ... TYPE` | ⭐ ACCESS EXCLUSIVE | **Everything, for the whole rewrite** |
| `ALTER TABLE ADD FOREIGN KEY` | SHARE ROW EXCLUSIVE (both tables) | Writes on both |
| `ALTER TABLE VALIDATE CONSTRAINT` | ⭐ SHARE UPDATE EXCLUSIVE | Only VACUUM — **this is why NOT VALID works** |
| `CREATE TRIGGER` | SHARE ROW EXCLUSIVE | Writes |
| `TRUNCATE` | ⭐ ACCESS EXCLUSIVE | **Everything** |
| `DROP TABLE` | ACCESS EXCLUSIVE | Everything |
| `REINDEX` | ACCESS EXCLUSIVE | Everything |
| `REINDEX CONCURRENTLY` | SHARE UPDATE EXCLUSIVE | VACUUM |
| `REFRESH MATERIALIZED VIEW` | ⭐ ACCESS EXCLUSIVE | **All reads of the view** |
| `REFRESH MAT VIEW CONCURRENTLY` | EXCLUSIVE | Writes (reads work) |

```sql
-- ⭐ Find out empirically what a statement takes, before running it in production
BEGIN;
ALTER TABLE orders ADD COLUMN discount_code text;
SELECT locktype, relation::regclass, mode, granted
FROM pg_locks WHERE pid = pg_backend_pid() AND relation IS NOT NULL;
ROLLBACK;
--  locktype | relation |        mode         | granted
-- ----------+----------+---------------------+---------
--  relation | orders   | AccessExclusiveLock | t
```

**This three-line recipe is the single most useful habit for migration safety.** Run it in a transaction, look at what it takes, roll back.

---

## 5. Row locks: four modes

```sql
SELECT * FROM accounts WHERE id = 1 FOR UPDATE;
SELECT * FROM accounts WHERE id = 1 FOR NO KEY UPDATE;
SELECT * FROM accounts WHERE id = 1 FOR SHARE;
SELECT * FROM accounts WHERE id = 1 FOR KEY SHARE;
```

### The conflict matrix

```
Requested ↓     Held →  │ KEY SHARE │ SHARE │ NO KEY UPDATE │ UPDATE │
────────────────────────┼───────────┼───────┼───────────────┼────────┤
FOR KEY SHARE           │           │       │               │   X    │
FOR SHARE               │           │       │      X        │   X    │
FOR NO KEY UPDATE       │           │   X   │      X        │   X    │
FOR UPDATE              │     X     │   X   │      X        │   X    │
```

### What each is for

| Mode | Acquired by | Purpose |
|------|-------------|---------|
| **`FOR KEY SHARE`** | ⭐ **Foreign key checks**, automatically | "Do not delete this row or change its key" — while permitting ordinary updates |
| `FOR SHARE` | Explicit | "Do not modify this row" |
| **`FOR NO KEY UPDATE`** | ⭐ **`UPDATE` that does not change a key column**, automatically | "I am modifying this, but its key is stable, so FK checks can proceed" |
| **`FOR UPDATE`** | Explicit, and `UPDATE` that changes a key, and `DELETE` | Full exclusive row lock |

### Why `FOR NO KEY UPDATE` exists — and why it matters

```
BEFORE PostgreSQL 9.3, there were only FOR SHARE and FOR UPDATE.

An UPDATE took FOR UPDATE.
A foreign key check took FOR SHARE.
⭐ They conflicted.

  T1: INSERT INTO orders (customer_id) VALUES (42);
      → FK check takes FOR SHARE on customers row 42

  T2: UPDATE customers SET last_login = now() WHERE id = 42;
      → takes FOR UPDATE on the same row
      → ⭐ BLOCKS, waiting for T1

⭐ Updating a customer's unrelated column blocked on inserting an order
   for that customer. This caused severe, widespread contention on
   "hot parent" rows — a single popular customer or tenant row could
   serialise the whole application.
```

```
PostgreSQL 9.3+ split the modes:
    FK check           → FOR KEY SHARE      (weakest)
    UPDATE, no key col → FOR NO KEY UPDATE
    ⭐ These do NOT conflict.

Now updating customer.last_login and inserting an order for that customer
proceed concurrently.
```

> **The practical consequence for schema design:** an `UPDATE` that touches a column referenced by a foreign key (usually the primary key) escalates to `FOR UPDATE` and reintroduces the contention. **Never update primary keys**, and be aware that `ON UPDATE CASCADE` foreign keys create exactly this pattern.

### `SKIP LOCKED` and `NOWAIT`

```sql
-- ⭐ The correct way to build a work queue in PostgreSQL
BEGIN;
SELECT * FROM jobs
WHERE state = 'queued'
ORDER BY priority DESC, created_at
LIMIT 10
FOR UPDATE SKIP LOCKED;          -- ⭐ skip rows another worker holds
-- ... process them ...
UPDATE jobs SET state = 'done' WHERE id = ANY($1);
COMMIT;
```

```
SKIP LOCKED: ignore locked rows entirely. ⭐ Perfect for work queues —
             N workers pull disjoint batches with zero contention.
NOWAIT:      raise an error immediately rather than waiting.
             ERROR: could not obtain lock on row in relation "jobs"
```

**`FOR UPDATE SKIP LOCKED` is why you often do not need a message broker.** For moderate volumes (Chapter 06 §6.1's decision), a `jobs` table with this pattern is simpler, transactional with your business data, and removes an entire system from your architecture.

---

## 6. ⭐ Why row locks are not in the lock manager

```
UPDATE orders SET status = 'archived' WHERE created_at < '2020-01-01';
-- affects 40,000,000 rows
```

```
If row locks lived in the shared-memory lock table:
    40,000,000 entries × ~150 bytes ≈ ⭐ 6 GB of shared memory
    for ONE statement.

    → impossible. The lock table is a fixed-size hash allocated at startup:
      max_locks_per_transaction (64) × (max_connections + max_prepared_transactions)
```

### How it actually works

```
The lock is written INTO THE TUPLE (Deep Dive 04 §3):

    t_xmax     = the locking transaction's xid
    t_infomask = HEAP_XMAX_LOCK_ONLY      (a lock, not a delete)
               | HEAP_XMAX_KEYSHR_LOCK    (which mode)
               | HEAP_XMAX_EXCL_LOCK
               | HEAP_XMAX_IS_MULTI       (several lockers — §7)

⭐ Cost: ZERO shared memory. The tuple was being written anyway.
```

### And waiting is the clever part

```
T2 wants to update a row whose t_xmax = 847291 (held by T1).

T2 does NOT create a "row lock wait" entry.
⭐ T2 takes a HEAVYWEIGHT lock on the TRANSACTION ID 847291.

When T1 commits or aborts, it releases its transaction-ID lock.
T2 wakes up, re-examines the tuple, and proceeds.

⭐ Lock-manager memory is O(waiting transactions), not O(locked rows).
```

```sql
-- ⭐ This is why you see `transactionid` locks in pg_locks:
SELECT locktype, transactionid, mode, granted FROM pg_locks
WHERE locktype = 'transactionid';
--  locktype      | transactionid |     mode      | granted
-- ---------------+---------------+---------------+---------
--  transactionid |        847291 | ExclusiveLock | t        ← T1 owns its own xid
--  transactionid |        847291 | ShareLock     | f        ← ⭐ T2 WAITING on T1
```

**Reading `pg_locks` correctly requires knowing this.** A row-lock wait appears as a `transactionid` lock with `granted = false`, not as a row lock — because there is no such thing as a row-lock entry.

### The costs of this design

```
✅ Unbounded row locking, zero memory
✅ No lock escalation needed (§16)
❌ ⭐ Taking a row lock DIRTIES THE PAGE → WAL is generated
   → SELECT ... FOR UPDATE on 1 million rows generates ~1 million
     WAL records and dirties thousands of pages. It is a WRITE operation
     in every respect except semantics.
❌ Lock information is lost on... no, actually it survives crashes,
   because it is in the tuple and WAL-logged. That is a benefit.
```

> **`SELECT ... FOR UPDATE` on a large set is a write-heavy operation.** People are surprised when a "read" query generates gigabytes of WAL. This is why.

---

## 7. MultiXacts — when several transactions lock one row

```
Two transactions both take FOR KEY SHARE on customer row 42
(both are inserting orders for that customer).

t_xmax can hold only ONE xid. How do you record two lockers?
```

```
⭐ ANSWER: t_xmax holds a MULTIXACT ID, and HEAP_XMAX_IS_MULTI is set.

The MultiXactId is an index into pg_multixact/, which stores the
actual member list:

  MultiXactId 4821 → [ (xid 847291, KeyShare),
                       (xid 847294, KeyShare) ]

Stored in two SLRU areas:
    pg_multixact/offsets   — where each MultiXact's members start
    pg_multixact/members   — ⭐ the member entries themselves
```

### When MultiXacts are created

```
1. ⭐ Multiple FK checks against the same parent row — by far the most common
2. Multiple explicit FOR SHARE / FOR KEY SHARE
3. A row locked by one transaction and then updated by a subtransaction
4. Combinations of lock modes on one row
```

### Why they cost you

```
❌ Reading a tuple with HEAP_XMAX_IS_MULTI requires an SLRU LOOKUP
   to resolve the member list — an extra memory (or disk) access
   per tuple visibility check.

❌ ⭐ MultiXact SLRU caches are SMALL and not sized by shared_buffers.
   Under heavy MultiXact churn, the caches thrash and you see
   MultiXactOffsetSLRU / MultiXactMemberSLRU wait events dominating.

❌ pg_multixact/members can grow to tens of GB.

❌ ⭐ And they have their own wraparound problem (§8).
```

```sql
-- ⭐ Diagnosing MultiXact contention
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity WHERE wait_event IS NOT NULL
GROUP BY 1,2 ORDER BY 3 DESC;
--  wait_event_type |      wait_event      | count
-- -----------------+----------------------+-------
--  LWLock          | MultiXactOffsetSLRU  |    47   ⭐ MultiXact thrashing
--  LWLock          | MultiXactMemberSLRU  |    31
```

**The usual root cause: a "hot parent" row.** Thousands of child rows referencing one tenant/customer/organisation row, each insert taking `FOR KEY SHARE` on it. PostgreSQL 17 made the SLRU caches configurable (`multixact_offsets_buffers`, `multixact_members_buffers`), which helps significantly.

---

## 8. ⭐ MultiXact wraparound: the second wraparound

Almost nobody knows this exists until it happens.

```
⭐ MultiXactIds are ALSO 32-bit, and they ALSO wrap around.
   This is a SEPARATE counter from transaction IDs (Deep Dive 04 §19)
   with its OWN thresholds and its OWN emergency.
```

```sql
-- ⭐ Monitor BOTH. Most dashboards have the first and not the second.
SELECT datname,
       age(datfrozenxid)      AS xid_age,          -- Deep Dive 04 §19
       mxid_age(datminmxid)   AS multixact_age     -- ⭐ this one
FROM pg_database ORDER BY 3 DESC;
--  datname    | xid_age   | multixact_age
-- ------------+-----------+---------------
--  production | 187420983 |     384029183   ⭐ approaching 400M!
```

```
autovacuum_multixact_freeze_max_age = 400,000,000  (default)
    → an anti-wraparound autovacuum is forced above this

At ~2 billion: ⭐ the same shutdown as xid wraparound:
    ERROR: database is not accepting commands to avoid wraparound data loss
```

### The other MultiXact limit — members exhaustion

```
⭐ SEPARATELY from the ID wraparound, pg_multixact/members has a
   HARD SIZE LIMIT (2^32 member entries).

    ERROR: multixact "members" limit exceeded
    DETAIL: This command would create a multixact with 2 members, but
            the remaining space is only enough for 0 members.
    HINT:   Execute a database-wide VACUUM in database with OID 16385
            with reduced vacuum_multixact_freeze_min_age and
            vacuum_multixact_freeze_table_age settings.

⭐ This can be hit LONG BEFORE the ID wraparound, on a workload with
   many multi-member MultiXacts — i.e. exactly the hot-parent-row
   pattern from §7.
```

### Prevention

```sql
-- 1. ⭐ Monitor it (most people monitor only xid age)
--    Alert: mxid_age(datminmxid) > 1,000,000,000

-- 2. Tune freezing for a MultiXact-heavy workload
ALTER SYSTEM SET vacuum_multixact_freeze_min_age = 5000000;    -- default 5M
ALTER SYSTEM SET vacuum_multixact_freeze_table_age = 150000000;
ALTER SYSTEM SET autovacuum_multixact_freeze_max_age = 200000000;  -- from 400M

-- 3. ⭐ FIX THE ROOT CAUSE: reduce FK checks against hot parent rows.
--    • Does that FK earn its cost? (it does buy planner benefits — DD06 §11)
--    • Can the parent be denormalised or the reference be logical?
--    • PG17: raise multixact_members_buffers / multixact_offsets_buffers
```

> **The design lesson:** a foreign key to a very hot parent row is not free. It takes a `FOR KEY SHARE` lock on every child insert, creates MultiXacts under concurrency, and consumes a 32-bit counter with its own wraparound. For a multi-tenant table where every row references one `tenants` row, this is a real consideration at scale.

---

## 9. The lock wait queue, and why it is FIFO

```
⭐ The lock queue is ORDERED. A waiter does not "retry until lucky" —
   it joins a queue, and requests behind it wait even if they would
   NOT conflict with the current holder.
```

```
Table `orders`:

  T1 (SELECT, long-running)  holds ACCESS SHARE           ← running
  T2 (ALTER TABLE)           wants ACCESS EXCLUSIVE       ← WAITING for T1
  T3 (SELECT)                wants ACCESS SHARE           ← ⭐ WAITING for T2

⭐ T3 does NOT conflict with T1. It could run right now.
   But it is BEHIND T2 in the queue, and the queue is FIFO.
   → T3 waits.
```

**Why FIFO:** without it, a stream of `ACCESS SHARE` requests would starve the `ACCESS EXCLUSIVE` waiter forever. FIFO guarantees fairness. The cost is §10.

```sql
SHOW deadlock_timeout;  -- 1s — also when the lock wait is first LOGGED
SHOW lock_timeout;      -- 0 = ⭐ WAIT FOREVER (the dangerous default)
SHOW statement_timeout; -- 0 = wait forever
```

---

## 10. ⭐ The DDL queue-blocking incident

The most common self-inflicted PostgreSQL outage. Every part of it follows from §3 and §9.

```
14:00:00  An analytics query starts:
              SELECT count(*) FROM orders WHERE ...;
          Takes ACCESS SHARE. Will run for 8 minutes.

14:00:30  A deploy runs a migration:
              ALTER TABLE orders ADD COLUMN discount_code text;
          ⭐ Wants ACCESS EXCLUSIVE. Conflicts with ACCESS SHARE.
          → JOINS THE QUEUE. Waits.

          ⭐ THE MIGRATION ITSELF IS INSTANT. ADD COLUMN with no default
             is metadata-only (§18). It would take 2 milliseconds.
             It is waiting purely because of the analytics query.

14:00:31  A normal application query arrives:
              SELECT * FROM orders WHERE id = 42;
          Wants ACCESS SHARE. Does NOT conflict with the running query.
          ⭐ BUT it is behind the ALTER in the FIFO queue.
          → WAITS.

14:00:31+ EVERY subsequent query on `orders` joins the queue behind the ALTER.

14:00:45  The connection pool is exhausted. Every connection is waiting.
14:00:50  ⭐ THE APPLICATION IS DOWN. Every request times out.

14:08:00  The analytics query finishes.
          ALTER runs in 2 ms.
          The queue drains. Service restored.

⭐ 8 MINUTES OF TOTAL OUTAGE caused by a 2-millisecond migration.
```

### The fix

```sql
-- ⭐ ALWAYS set lock_timeout before DDL. Always.
SET lock_timeout = '3s';
ALTER TABLE orders ADD COLUMN discount_code text;
-- If it cannot get the lock in 3 s:
--   ERROR: canceling statement due to lock timeout
-- ⭐ The queue NEVER FORMS. The application is never affected.
-- Then simply retry.
```

### The retry wrapper

```python
def run_ddl_safely(conn, statement, *, lock_timeout='3s',
                   max_attempts=20, base_delay=2.0):
    """⭐ Every migration tool should do this. Most do not."""
    for attempt in range(max_attempts):
        try:
            with conn.transaction():
                conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
                conn.execute(statement)
            return
        except LockNotAvailable:
            delay = min(base_delay * (2 ** attempt), 60) * (0.5 + random.random())
            log.info("lock not available, retry %d in %.1fs", attempt + 1, delay)
            time.sleep(delay)
    raise MigrationFailed(
        f"could not acquire lock after {max_attempts} attempts. "
        f"Check pg_stat_activity for long-running queries on the table."
    )
```

### The complementary defences

```sql
-- ⭐ Bound how long anything can hold a lock
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';  -- DD04 §16
ALTER ROLE analytics SET statement_timeout = '5min';

-- ⭐ Make lock waits VISIBLE in the log
ALTER SYSTEM SET log_lock_waits = on;
--   LOG: process 8821 still waiting for AccessExclusiveLock on relation
--        16402 of database 16385 after 1000.114 ms
--   DETAIL: Process holding the lock: 8402. Wait queue: 8821, 8830, 8841, ...
--                                                        ⭐ the queue, visible
```

> **`log_lock_waits = on` plus `lock_timeout` in your migration tool would prevent the majority of PostgreSQL-related deploy outages.** Both are one line.

---

## 11. Deadlock detection: the wait-for graph

```
⭐ PostgreSQL does not PREVENT deadlocks. It DETECTS them and kills a victim.
```

```
When a process has waited for deadlock_timeout (default 1s):

1. Build the WAIT-FOR GRAPH:
       node  = a transaction
       edge  = "A is waiting for a lock held by B"

2. Search for a CYCLE (depth-first).

3. If a cycle exists, choose a victim — normally the process that
   ran the detector — and abort it with:
       ERROR: deadlock detected
       SQLSTATE 40P01
```

```
     T1 ──waiting for──► T2
      ▲                   │
      │                   │ waiting for
      └───────────────────┘
              ⭐ CYCLE
```

### The cost

```
⭐ Deadlock detection ONLY runs after deadlock_timeout.
   So EVERY deadlock costs at least 1 second of wall time before
   anything is reported.

Lowering deadlock_timeout makes detection faster but runs the (expensive)
graph search more often on ordinary lock waits.

⭐ Do NOT lower it below ~200 ms. Instead, eliminate the deadlocks (§12-15).
```

```sql
ALTER SYSTEM SET log_lock_waits = on;
ALTER SYSTEM SET deadlock_timeout = '1s';   -- leave it
```

```
ERROR:  deadlock detected
DETAIL: Process 8821 waits for ShareLock on transaction 847291;
          blocked by process 8402.
        Process 8402 waits for ShareLock on transaction 847294;
          blocked by process 8821.
HINT:   See server log for query details.
CONTEXT: while updating tuple (4821,12) in relation "accounts"
         ⭐ the tuple, so you can identify the row
```

**The server log contains the actual statements from both processes.** That is what you need; the client error alone is not enough.

---

## 12. Traced deadlock 1 — the classic transfer

```
T1: transfer $100 from account 1 to account 2
T2: transfer $50  from account 2 to account 1

t=0   T1: UPDATE accounts SET balance = balance - 100 WHERE id = 1;
          → row 1: t_xmax = T1    ✓ acquired

t=1   T2: UPDATE accounts SET balance = balance - 50 WHERE id = 2;
          → row 2: t_xmax = T2    ✓ acquired

t=2   T1: UPDATE accounts SET balance = balance + 100 WHERE id = 2;
          → row 2 is locked by T2
          → ⭐ T1 takes ShareLock on transactionid T2 — WAITS

t=3   T2: UPDATE accounts SET balance = balance + 50 WHERE id = 1;
          → row 1 is locked by T1
          → ⭐ T2 takes ShareLock on transactionid T1 — WAITS

t=4   ⭐ CYCLE: T1 → T2 → T1

t=5   (after deadlock_timeout) the detector fires. T2 is aborted with 40P01.
```

### The fix: consistent lock ordering

```python
async def transfer(from_id, to_id, amount):
    # ⭐ ALWAYS lock in ascending ID order, regardless of direction
    first, second = sorted([from_id, to_id])

    async with db.transaction():
        await db.execute(
            "SELECT id FROM accounts WHERE id = ANY($1) ORDER BY id FOR UPDATE",
            [first, second])
        # ⭐ ORDER BY inside FOR UPDATE guarantees the acquisition order

        await db.execute("UPDATE accounts SET balance = balance - $2 WHERE id = $1",
                         from_id, amount)
        await db.execute("UPDATE accounts SET balance = balance + $2 WHERE id = $1",
                         to_id, amount)
```

```
⭐ WHY IT WORKS: both transactions now request row 1 before row 2.
   One of them gets row 1 and proceeds; the other waits for row 1
   and never holds row 2. No cycle is possible.
```

---

## 13. Traced deadlock 2 — foreign keys

The one that looks impossible, because neither transaction touches the same table row.

```sql
CREATE TABLE customers (id bigint PRIMARY KEY, name text);
CREATE TABLE orders (
    id bigint PRIMARY KEY,
    customer_id bigint REFERENCES customers(id)    -- ⭐ the FK
);
```

```
T1: INSERT INTO orders VALUES (1, 100);   -- child of customer 100
T2: INSERT INTO orders VALUES (2, 200);   -- child of customer 200
T1: INSERT INTO orders VALUES (3, 200);
T2: INSERT INTO orders VALUES (4, 100);
```

```
t=0   T1 inserts order 1 → ⭐ FK check takes FOR KEY SHARE on customers row 100
t=1   T2 inserts order 2 → ⭐ FK check takes FOR KEY SHARE on customers row 200
```

So far no conflict — `FOR KEY SHARE` does not conflict with itself (§5). Now add an update:

```
t=2   T3: UPDATE customers SET id = 101 WHERE id = 100;
          ⭐ Changes the KEY → takes FOR UPDATE
          → conflicts with T1's FOR KEY SHARE → WAITS for T1

t=3   T1: INSERT INTO orders VALUES (3, 200);
          → FK check wants FOR KEY SHARE on customers row 200
          → T2 holds FOR KEY SHARE there — no conflict... ✓ proceeds

t=4   T1: UPDATE customers SET name = 'x' WHERE id = 200;
          → FOR NO KEY UPDATE — conflicts with T2's FOR KEY SHARE? 
          → Check the matrix (§5): NO KEY UPDATE vs KEY SHARE → no conflict ✓

⭐ The realistic deadlock version:

t=2'  T1: UPDATE customers SET id = 201 WHERE id = 200;   -- key change → FOR UPDATE
          → conflicts with T2's FOR KEY SHARE on 200 → WAITS for T2
t=3'  T2: UPDATE customers SET id = 101 WHERE id = 100;   -- key change → FOR UPDATE
          → conflicts with T1's FOR KEY SHARE on 100 → WAITS for T1
⭐ CYCLE.
```

### Why this surprises people

```
⭐ Neither transaction ever explicitly referenced `customers`.
   The locks were taken INVISIBLY by foreign key validation.

   The developer sees "two INSERTs into orders deadlocked" and cannot
   explain it, because the deadlock is on a table they did not mention.
```

### The fixes

```sql
-- 1. ⭐ NEVER UPDATE PRIMARY KEYS. This removes the FOR UPDATE escalation
--    entirely. A surrogate key that never changes is a design rule,
--    not a preference.

-- 2. Insert child rows in a consistent parent-ID order within a transaction
INSERT INTO orders (id, customer_id) VALUES (...), (...)
-- ⭐ sorted by customer_id in the application before building the statement

-- 3. If the FK is not earning its keep on a hot parent, consider removing it
--    (⚠ but it DOES help the planner — DD06 §11. Measure both sides.)

-- 4. Avoid ON UPDATE CASCADE, which creates exactly this pattern by design
```

---

## 14. Traced deadlock 3 — unique index insertion

Another invisible one.

```sql
CREATE UNIQUE INDEX ON users (email);
```

```
T1: INSERT INTO users (email) VALUES ('a@x.com');   -- ✓
T2: INSERT INTO users (email) VALUES ('b@x.com');   -- ✓
T1: INSERT INTO users (email) VALUES ('b@x.com');
    ⭐ The unique index already has 'b@x.com' from T2 (uncommitted).
    ⭐ T1 CANNOT decide whether this is a violation until T2 resolves.
    → T1 takes ShareLock on transactionid T2. WAITS.

T2: INSERT INTO users (email) VALUES ('a@x.com');
    → same situation in reverse. WAITS on T1.

⭐ CYCLE. Deadlock.
```

```
⭐ THE KEY INSIGHT: a unique index makes an INSERT a LOCKING operation.
   Inserting a duplicate of an uncommitted row must wait, because the
   outcome depends on whether the other transaction commits.
```

### The fixes

```sql
-- 1. ⭐ ON CONFLICT — the insert no longer needs to wait for a decision
INSERT INTO users (email) VALUES ('b@x.com')
ON CONFLICT (email) DO NOTHING;
--   ⚠ Still takes a lock if the conflicting row is UNCOMMITTED,
--     but it removes the error path and most of the pathological cases.

-- 2. Insert in a deterministic order
--    Sort the batch by the unique key before inserting.

-- 3. ⭐ Batch into a single statement — one statement cannot deadlock
--    with itself, and PostgreSQL will order the insertions internally
INSERT INTO users (email) VALUES ('a@x.com'), ('b@x.com')
ON CONFLICT DO NOTHING;
```

---

## 15. Traced deadlock 4 — the unordered multi-row UPDATE

The subtlest one, and the reason "just sort your IDs" is insufficient.

```sql
-- T1
UPDATE accounts SET balance = balance + 10 WHERE id IN (1, 2, 3);
-- T2
UPDATE accounts SET balance = balance + 10 WHERE id IN (3, 2, 1);
```

```
⭐ You might assume PostgreSQL locks rows in the order written. IT DOES NOT.

The lock order is the order the EXECUTOR produces rows, which depends on
the PLAN:
   • Seq Scan      → physical page order
   • Index Scan    → index order
   • Bitmap Scan   → ⭐ physical page order (the bitmap is sorted by TID)

⭐ And the plan can CHANGE between the two executions — different
   parameters, different statistics, a different plan cache entry (DD06 §24).

So T1 might lock in order 1,2,3 and T2 in order 3,1,2. → Deadlock.
```

### The fix: force the order explicitly

```sql
-- ⭐ Lock the rows FIRST, in a guaranteed order, then update
BEGIN;
SELECT id FROM accounts WHERE id IN (1,2,3) ORDER BY id FOR UPDATE;
--                                            ^^^^^^^^^^^^^^^^^^^^
--   ⭐ ORDER BY is honoured for lock acquisition here
UPDATE accounts SET balance = balance + 10 WHERE id IN (1,2,3);
COMMIT;
```

```
⚠ NOTE: `UPDATE ... ORDER BY` is not valid SQL in PostgreSQL, and
  adding ORDER BY to a subquery inside UPDATE does NOT guarantee
  lock order either. The explicit SELECT ... ORDER BY ... FOR UPDATE
  is the reliable construction.
```

> **This class of deadlock is plan-dependent, which makes it intermittent and maddening.** It appears after a statistics change, a version upgrade, or a data-volume shift, with no code change. If you see deadlocks on multi-row updates that "used to be fine", this is it.

---

## 16. Why PostgreSQL has no lock escalation

```
SQL SERVER (and DB2): if a transaction acquires too many row locks,
the engine ESCALATES to a table lock to save memory.

  UPDATE 5,000 rows → ⭐ SQL Server may escalate to a TABLE lock
  → suddenly every other query on the table blocks
  → an intermittent, hard-to-reproduce outage under load
```

```
⭐ PostgreSQL NEVER escalates. It cannot, and does not need to, because
   row locks live in the tuples (§6) and cost no shared memory.

  UPDATE 40,000,000 rows → 40,000,000 row locks, ZERO table-level impact
  on readers.
```

### Why this matters architecturally

```
✅ No surprise blocking. A large batch UPDATE does not block SELECTs.
✅ Behaviour is predictable regardless of transaction size.
❌ ⭐ The cost moves elsewhere: 40 M row locks means 40 M dirtied
   tuples, a great deal of WAL, and 40 M dead tuples if it is an UPDATE.

⭐ So PostgreSQL replaces a LOCKING problem with an I/O and BLOAT problem.
   Which is, again, Deep Dive 04 §1's trade appearing in a new place.
```

**The practical guidance is different as a result:** in SQL Server you batch large updates to *avoid lock escalation*. In PostgreSQL you batch them to *avoid bloat, long transactions and WAL spikes* — same advice, completely different reason.

```sql
-- ⭐ Batched update, PostgreSQL style
DO $$
DECLARE rows_updated int;
BEGIN
  LOOP
    UPDATE orders SET status = 'archived'
    WHERE id IN (SELECT id FROM orders
                 WHERE created_at < '2020-01-01' AND status <> 'archived'
                 LIMIT 10000);
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    EXIT WHEN rows_updated = 0;
    COMMIT;                      -- ⭐ short transactions: xmin horizon advances
    PERFORM pg_sleep(0.1);       -- ⭐ let autovacuum keep up
  END LOOP;
END $$;
```

---

## 17. Advisory locks

Application-defined locks that PostgreSQL tracks but attaches no meaning to.

```sql
-- Session-level: held until explicitly released or the session ends
SELECT pg_advisory_lock(12345);
SELECT pg_advisory_unlock(12345);

-- ⭐ Transaction-level: released automatically at COMMIT/ROLLBACK.
--    Use this unless you have a specific reason not to.
SELECT pg_advisory_xact_lock(12345);

-- ⭐ Non-blocking variants — essential for leader election / singleton jobs
SELECT pg_try_advisory_lock(12345);       -- returns true/false immediately
SELECT pg_try_advisory_xact_lock(12345);

-- Two-integer form, useful for namespacing
SELECT pg_advisory_xact_lock(hashtext('daily_report'), tenant_id);
```

### The legitimate uses

```sql
-- ⭐ 1. Singleton job execution across N application instances
--    This is a genuinely good pattern and removes a whole coordination system.
SELECT pg_try_advisory_lock(hashtext('nightly-billing-run')) AS acquired;
-- If false, another instance is running it. Exit quietly.

-- 2. Serialising an operation on a logical entity that has no row to lock
SELECT pg_advisory_xact_lock(hashtext('tenant-provisioning'), tenant_id);

-- 3. Preventing concurrent runs of a migration or maintenance task
```

### The caveats

```
❌ ⭐ Advisory locks are PER-DATABASE-CLUSTER, not per-application.
   Two different applications using the same integer collide silently.
   → Namespace with hashtext('your-app:purpose').

❌ ⭐ A SESSION-level lock survives ROLLBACK. Leaking them is easy,
   especially with a connection pooler that reuses the session.
   → Prefer the _xact_ variants.

❌ ⭐ WITH A TRANSACTION-MODE POOLER (PgBouncer), session-level advisory
   locks are DANGEROUS: the session you lock on is not the session you
   later unlock on. Only the _xact_ variants are safe there.

❌ hashtext() collisions are possible (32-bit). Low risk, non-zero.
```

> **For "only one instance should run this job", an advisory lock is simpler, cheaper and more reliable than Redis, and — unlike a Redis lock (Chapter 05 §5.6) — it is released automatically when the holder's connection dies.** That automatic release is the property that makes it actually safe.

---

## 18. Safe DDL: the complete catalogue ⭐

The reference table. All of these assume you have set `lock_timeout` (§10).

### Safe — metadata only, instant

```sql
ADD COLUMN (nullable, no default)                   -- always instant
ADD COLUMN ... DEFAULT <constant>                   -- ⭐ instant since PG11
ADD COLUMN ... NOT NULL DEFAULT <constant>          -- ⭐ instant since PG11
DROP COLUMN                                          -- instant (space reclaimed later)
RENAME COLUMN / RENAME TABLE                        -- instant (⚠ breaks running code)
ALTER COLUMN SET/DROP DEFAULT                        -- instant
ALTER COLUMN DROP NOT NULL                           -- instant
ADD CONSTRAINT ... NOT VALID                         -- ⭐ instant, see below
ALTER TABLE SET (fillfactor = n)                     -- instant
CREATE INDEX CONCURRENTLY                            -- ⭐ no write blocking
DROP INDEX CONCURRENTLY
REINDEX INDEX/TABLE CONCURRENTLY                     -- PG12+
```

### Dangerous — full table rewrite, ACCESS EXCLUSIVE for the duration

```sql
ALTER COLUMN TYPE                  -- ⭐ except the safe cases below
ADD COLUMN ... DEFAULT <volatile>  -- e.g. DEFAULT gen_random_uuid()
ADD PRIMARY KEY (directly)
SET NOT NULL                       -- ⭐ full scan, see below
VACUUM FULL / CLUSTER
ALTER TABLE SET TABLESPACE
```

### The safe `ALTER COLUMN TYPE` exceptions

```sql
-- ⭐ These do NOT rewrite the table (the binary representation is unchanged):
varchar(n)  → varchar(m)  where m > n
varchar(n)  → text
text        → varchar(n)  ⚠ only if no value exceeds n (still scans to verify)
numeric(p,s)→ numeric(p2,s) where p2 > p
timestamp   → timestamptz ⚠ ONLY if TimeZone = 'UTC' (PG12+)
```

### The three patterns that make everything else safe

**Pattern 1 — `NOT VALID` then `VALIDATE`**

```sql
-- ❌ This takes SHARE ROW EXCLUSIVE and scans the whole table, blocking writes
ALTER TABLE orders ADD CONSTRAINT fk_customer
    FOREIGN KEY (customer_id) REFERENCES customers(id);

-- ✅ Two steps
ALTER TABLE orders ADD CONSTRAINT fk_customer
    FOREIGN KEY (customer_id) REFERENCES customers(id) NOT VALID;
--   ⭐ INSTANT. New rows are checked from now on; existing rows are not.

ALTER TABLE orders VALIDATE CONSTRAINT fk_customer;
--   ⭐ Takes only SHARE UPDATE EXCLUSIVE — does NOT block reads or writes.
--      Scans the table, but concurrently.
```

Same pattern for `CHECK` constraints.

**Pattern 2 — `SET NOT NULL` via a CHECK constraint**

```sql
-- ❌ Full table scan under ACCESS EXCLUSIVE
ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;

-- ✅ Three steps (PG12+ recognises the CHECK and skips the scan)
ALTER TABLE orders ADD CONSTRAINT orders_customer_id_not_null
    CHECK (customer_id IS NOT NULL) NOT VALID;          -- instant
ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_id_not_null;
                                                         -- concurrent scan
ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;
--   ⭐ PG12+ sees the valid CHECK and skips the scan → INSTANT
ALTER TABLE orders DROP CONSTRAINT orders_customer_id_not_null;  -- optional
```

**Pattern 3 — `ADD PRIMARY KEY` via a concurrent index**

```sql
-- ❌ Builds the index under ACCESS EXCLUSIVE
ALTER TABLE orders ADD PRIMARY KEY (id);

-- ✅
CREATE UNIQUE INDEX CONCURRENTLY orders_pkey_idx ON orders (id);
ALTER TABLE orders ALTER COLUMN id SET NOT NULL;         -- via pattern 2
ALTER TABLE orders ADD CONSTRAINT orders_pkey
    PRIMARY KEY USING INDEX orders_pkey_idx;
--   ⭐ Brief ACCESS EXCLUSIVE, but the index already exists → instant
```

### Column type change, the full safe procedure

This is expand/contract (Chapter 09 §9.5) applied to a type change.

```sql
-- Goal: orders.amount from integer to bigint, zero downtime

-- Release 1
ALTER TABLE orders ADD COLUMN amount_new bigint;          -- instant
CREATE FUNCTION sync_amount() RETURNS trigger AS $$
BEGIN NEW.amount_new := NEW.amount; RETURN NEW; END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sync_amount BEFORE INSERT OR UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION sync_amount();
-- Deploy code that writes `amount`, reads `amount`.

-- Release 2 — backfill in batches (§16's loop), off-peak

-- Release 3 — deploy code that reads amount_new

-- Release 4
ALTER TABLE orders DROP COLUMN amount;
ALTER TABLE orders RENAME COLUMN amount_new TO amount;
DROP TRIGGER trg_sync_amount ON orders;
```

**Four releases, each instant, each reversible.** That is what zero-downtime actually costs.

---

## 19. CREATE INDEX CONCURRENTLY: how it really works

```
PHASE 1 — take SHARE UPDATE EXCLUSIVE; add a catalog entry for the index,
          marked ⭐ indisready = false, indisvalid = false.
          Commit. ⭐ New writers now MAINTAIN the index even though it
          is not yet usable or complete.

PHASE 2 — ⭐ WAIT for all transactions that started before phase 1 to finish.
          They do not know about the index and would not maintain it.

PHASE 3 — FIRST TABLE SCAN: build the index from a snapshot.
          Set indisready = true. Commit.

PHASE 4 — ⭐ WAIT AGAIN for older transactions.

PHASE 5 — ⭐ SECOND TABLE SCAN: find rows inserted during phase 3 and
          add them. Set indisvalid = true. Commit. Done.
```

### The consequences

```
⭐ TWO full table scans → roughly 2-3× slower than a normal CREATE INDEX.

⭐ TWO waits for old transactions. A single long-running transaction
   ANYWHERE in the database blocks the build indefinitely.
   → CIC on a busy database with long analytics queries can hang for hours
     while appearing to do nothing.

⭐ IF IT FAILS, it leaves an INVALID index behind, which is:
     • NOT used by the planner
     • ⭐ STILL MAINTAINED on every write
   → pure cost, zero benefit, and easy to miss.
```

```sql
-- ⭐ ALWAYS check after a CIC, especially in automated migrations
SELECT indexrelid::regclass AS invalid_index, indrelid::regclass AS table
FROM pg_index WHERE NOT indisvalid;

-- Clean up and retry
DROP INDEX CONCURRENTLY IF EXISTS orders_customer_idx;

-- ⭐ And find what is blocking the build
SELECT pid, state, now() - xact_start AS duration, left(query, 60)
FROM pg_stat_activity
WHERE state <> 'idle' AND xact_start < now() - interval '5 min'
ORDER BY xact_start;
```

```sql
-- ⭐ CIC cannot run inside a transaction block.
--    Migration tools that wrap everything in BEGIN/COMMIT will fail:
--      ERROR: CREATE INDEX CONCURRENTLY cannot run inside a transaction block
--    → configure the tool to run this migration outside a transaction
--      (Alembic: with op.get_context().autocommit_block();
--       Rails: disable_ddl_transaction!)
```

---

## 20. SSI: the mechanism ⭐

PostgreSQL's `SERIALIZABLE` is **Serializable Snapshot Isolation** (Cahill et al., implemented in 9.1). It is genuinely serializable, and it achieves this **without blocking anything**.

### The idea

```
1. Run ordinary SNAPSHOT ISOLATION (Deep Dive 03 §11).
2. ⭐ Additionally TRACK what each transaction READ (SIREAD "locks").
3. Detect rw-ANTI-DEPENDENCIES: T1 read something that T2 then wrote.
4. ⭐ If a DANGEROUS STRUCTURE appears, abort one transaction.
```

### The dangerous structure

From Deep Dive 03 §10: a history is serializable iff its dependency graph is acyclic. Cahill's key theorem:

> **Every cycle in the dependency graph contains a transaction with BOTH an incoming and an outgoing rw-anti-dependency edge — consecutive rw edges.**

```
    T_in ──rw──► T_pivot ──rw──► T_out
                    ▲
              ⭐ THE PIVOT
              Has an incoming AND an outgoing rw edge.
```

```
⭐ So PostgreSQL does not need to search for cycles at all.
   It only needs to detect a PIVOT — a local, cheap condition.

If a pivot exists AND T_out commits first, a cycle is possible.
→ abort one of the three.
```

**This is why SSI is efficient:** cycle detection in a graph is expensive; detecting "this transaction has both edge types" is O(1) per edge added.

### Why it is conservative

```
⭐ The presence of a pivot is NECESSARY for a cycle but NOT SUFFICIENT.

So PostgreSQL sometimes aborts transactions that would actually have been
serializable. These are FALSE POSITIVES, and they are the price of
detecting conflicts cheaply and without blocking.
```

### The crucial operational property

```
⭐ SSI NEVER BLOCKS. There are no waits, no lock queues, no deadlocks
   from SIREAD locks.

Transactions run at full speed and are killed AFTER THE FACT with:

    ERROR:  could not serialize access due to read/write dependencies
            among transactions
    DETAIL: Reason code: Canceled on identification as a pivot, during write.
    HINT:   The transaction might succeed if retried.
    SQLSTATE: 40001
```

**Which means retry logic is not optional — it is the mechanism.** (§24.)

---

## 21. SIREAD locks and predicate granularity

```sql
-- Watch them being taken
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT * FROM doctors WHERE on_call = true;

SELECT locktype, relation::regclass, page, tuple, mode
FROM pg_locks WHERE mode = 'SIReadLock';
--  locktype |  relation  | page | tuple |    mode
-- ----------+------------+------+-------+------------
--  tuple    | doctors    |    0 |     1 | SIReadLock
--  tuple    | doctors    |    0 |     2 | SIReadLock
```

### Three granularities, with automatic promotion

```
TUPLE    one entry per row read — most precise, most memory
PAGE     one entry per page     — coarser
RELATION one entry for the whole table — ⭐ coarsest

⭐ PROMOTION happens automatically when limits are exceeded:

  max_pred_locks_per_page        (default 2)
      → more than 2 tuple locks on a page  → promote to a PAGE lock
  max_pred_locks_per_relation    (default -2, meaning
                                  max_pred_locks_per_transaction / -2)
      → too many page locks       → promote to a RELATION lock
  max_pred_locks_per_transaction (default 64)
      → the overall budget
```

### Why promotion causes false positives

```
⭐ A RELATION-level SIREAD lock means "this transaction read the whole table."

  Any write to ANY row of that table now creates an rw-dependency,
  even to a row the transaction never actually looked at.

  → many more detected conflicts
  → many more false-positive aborts
```

```sql
-- ⭐ If you see a high serialization failure rate under SERIALIZABLE,
--    this is the first thing to check and the first thing to tune.
ALTER SYSTEM SET max_pred_locks_per_transaction = 256;   -- from 64
ALTER SYSTEM SET max_pred_locks_per_page = 4;            -- from 2
-- Costs shared memory: roughly
--   max_pred_locks_per_transaction × (max_connections + max_prepared_transactions)
```

### The other source of false positives: sequential scans

```
⭐ A SEQUENTIAL SCAN under SERIALIZABLE takes a RELATION-level SIREAD lock
   immediately — because it genuinely did read every row.

  → ⭐ MISSING INDEXES CAUSE SERIALIZATION FAILURES.

  A query that uses an index takes a few tuple locks.
  The same query without an index takes a whole-table lock and
  conflicts with every concurrent writer.
```

> **This is a genuinely surprising and important connection: under `SERIALIZABLE`, adding the right index does not just make the query faster — it dramatically reduces serialization failures.** If you enable `SERIALIZABLE` and see a high abort rate, check for sequential scans before tuning anything else.

---

## 22. Traced SSI scenario — the dangerous structure

The on-call rota from Deep Dive 03 §9, now traced through SSI's machinery.

```sql
CREATE TABLE doctors (id int PRIMARY KEY, name text, on_call boolean);
INSERT INTO doctors VALUES (1,'Alice',true), (2,'Bob',true);
-- INVARIANT: at least one doctor must be on call.
```

```
t=0   T1: BEGIN ISOLATION LEVEL SERIALIZABLE;
      T2: BEGIN ISOLATION LEVEL SERIALIZABLE;

t=1   T1: SELECT count(*) FROM doctors WHERE on_call = true;   → 2
          ⭐ SIREAD locks taken on tuple (0,1) [Alice] and (0,2) [Bob]

t=2   T2: SELECT count(*) FROM doctors WHERE on_call = true;   → 2
          ⭐ SIREAD locks on the same two tuples.
          ⭐ SIREAD locks do NOT conflict with each other. Both proceed.

t=3   T1: UPDATE doctors SET on_call = false WHERE id = 1;     -- Alice
          ⭐ T1 writes tuple (0,1).
          ⭐ T2 holds a SIREAD lock on (0,1).
          → RECORD an anti-dependency:  T2 ──rw──► T1
             ("T2 read something T1 then wrote")

t=4   T2: UPDATE doctors SET on_call = false WHERE id = 2;     -- Bob
          ⭐ T2 writes tuple (0,2).
          ⭐ T1 holds a SIREAD lock on (0,2).
          → RECORD:  T1 ──rw──► T2

t=5   ⭐ THE GRAPH NOW CONTAINS:
             T2 ──rw──► T1 ──rw──► T2

          T1 has an INCOMING rw edge (from T2) and an OUTGOING rw edge (to T2).
          ⭐ T1 IS A PIVOT. DANGEROUS STRUCTURE DETECTED.

t=6   T1: COMMIT;   → ✓ succeeds (it commits first)

t=7   T2: COMMIT;
          ⭐ ERROR: could not serialize access due to read/write
                    dependencies among transactions
             DETAIL: Reason code: Canceled on identification as a pivot,
                     during commit attempt.
             HINT: The transaction might succeed if retried.

t=8   T2 RETRIES. Its new SELECT now sees Alice is off call → count = 1.
      The application logic correctly refuses to take Bob off call.
      ⭐ THE INVARIANT HOLDS.
```

**Compare to snapshot isolation**, where both commit and zero doctors are on call. SSI caught it — and note that it caught it **without ever blocking either transaction**. They both ran at full speed; one was told at commit time that its result was not serializable.

---

## 23. SSI false positives, and DEFERRABLE

### Measuring the abort rate

```sql
-- ⭐ Is SERIALIZABLE costing you?
SELECT datname, xact_commit, xact_rollback,
       round(100.0*xact_rollback/NULLIF(xact_commit+xact_rollback,0),2) AS rollback_pct
FROM pg_stat_database WHERE datname = current_database();

-- Better: count 40001 specifically, from application metrics or logs
ALTER SYSTEM SET log_min_error_statement = 'error';
-- then grep for 40001 / "could not serialize"
```

```
⭐ Rules of thumb:
   < 1%   fine — retries are cheap
   1-5%   tune (§21: pred lock limits, indexes)
   > 5%   ⭐ investigate seriously: missing indexes, over-long transactions,
          or a genuinely high-contention design that needs restructuring
```

### Reducing false positives

```
1. ⭐ ADD INDEXES. Sequential scans take relation-level SIREAD locks (§21).
2. ⭐ KEEP TRANSACTIONS SHORT. A longer transaction overlaps with more
   concurrent writers → more edges → more pivots.
3. Raise max_pred_locks_per_transaction and _per_page (§21).
4. ⭐ Do not read more than you need. `SELECT *` over a wide range
   takes SIREAD locks on everything it touched.
5. Use SERIALIZABLE only where the invariant requires it — it can be
   set per transaction (§24).
```

### `SERIALIZABLE READ ONLY DEFERRABLE` ⭐

A genuinely useful and little-known mode.

```sql
BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE;
SELECT ... ;   -- a long consistent report
COMMIT;
```

```
⭐ The transaction WAITS at the start until it can obtain a snapshot that
   is guaranteed safe — one where no serialization anomaly is possible.

Then:
   ✅ It can NEVER be aborted with 40001
   ✅ ⭐ It can never CAUSE another transaction to be aborted
   ✅ It takes NO SIREAD locks at all — zero overhead on the rest of the system
   ❌ It may wait (sometimes a long time) at the start
```

> **This is the correct mode for long analytical reports on a serializable system.** Without it, a 20-minute report accumulates SIREAD locks across the whole database, promotes them to relation level, and causes a storm of false-positive aborts in the OLTP workload. With `DEFERRABLE`, it is completely invisible to everyone else.

---

## 24. Retry patterns that work

Both `40001` (serialization failure) and `40P01` (deadlock) are **expected, normal conditions** under concurrency. Code must handle them.

```python
import random, time
from psycopg import errors

RETRYABLE = (errors.SerializationFailure,   # 40001
             errors.DeadlockDetected)        # 40P01

def with_retry(fn, *, max_attempts=5, base_delay=0.05, max_delay=2.0):
    """⭐ The pattern every serializable/high-concurrency codebase needs."""
    for attempt in range(max_attempts):
        try:
            with conn.transaction():
                return fn(conn)
        except RETRYABLE as e:
            if attempt == max_attempts - 1:
                metrics.increment("txn.retry_exhausted", tags={"code": e.sqlstate})
                raise
            metrics.increment("txn.retry", tags={"code": e.sqlstate})
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= (0.5 + random.random())     # ⭐ full jitter (Chapter 05 §5.8)
            time.sleep(delay)
```

### The rules

```
1. ⭐ RETRY THE WHOLE TRANSACTION, from the BEGIN.
   You cannot retry a single statement — the transaction's snapshot
   is invalid and it has been rolled back entirely.

2. ⭐ THE FUNCTION MUST BE IDEMPOTENT AT THE APPLICATION LEVEL.
   The database rolled back, but any side effects OUTSIDE the database
   (an email sent, an API call made) did NOT roll back.
   → Never do I/O inside a retryable transaction (Chapter 09 §9.2).

3. ⭐ USE JITTER. Without it, two conflicting transactions retry in
   lockstep and conflict again, indefinitely.

4. ⭐ CAP THE ATTEMPTS and emit a metric. A rising retry rate is a
   leading indicator of a contention problem.

5. Retry at ONE layer only (Chapter 05 §5.8).
```

### Per-transaction isolation

```sql
-- ⭐ SERIALIZABLE only where the invariant needs it
BEGIN;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- ... the on-call rota check ...
COMMIT;

-- Everything else stays at READ COMMITTED and pays nothing.
```

**This is the right default posture:** `READ COMMITTED` globally, `SERIALIZABLE` for the specific operations that guard a multi-row invariant (Deep Dive 03 §9), and a constraint where one is possible (which is better than both).

---

## 25. Two-phase commit internals

```sql
BEGIN;
INSERT INTO orders ...;
PREPARE TRANSACTION 'order-8812';   -- ⭐ phase 1
-- ... coordinate with other systems ...
COMMIT PREPARED 'order-8812';       -- phase 2
-- or ROLLBACK PREPARED 'order-8812';
```

### What `PREPARE TRANSACTION` actually does

```
1. Write the full transaction state to $PGDATA/pg_twophase/<xid>
   ⭐ and fsync it — it must survive a crash
2. ⭐ RELEASE the backend, but NOT the locks
3. The transaction is now "in doubt": neither committed nor aborted

⭐ THE PREPARED TRANSACTION CONTINUES TO HOLD:
     • every lock it acquired
     • ⭐ its xmin — pinning the horizon (Deep Dive 04 §16)
     • its entry in pg_xact as in-progress
   FOREVER, until explicitly resolved. It SURVIVES SERVER RESTARTS.
```

### Why this is dangerous

```
An orphaned prepared transaction — a coordinator crashed and never
resolved it — causes, simultaneously:

  ⭐ Locks held indefinitely → queries block forever
  ⭐ The xmin horizon pinned → unbounded bloat (Deep Dive 04 §17)
  ⭐ Freezing blocked → wraparound risk (Deep Dive 04 §19)
  ⭐ It is nearly invisible: it does not appear in pg_stat_activity
```

```sql
-- ⭐ CHECK FOR THESE. They are easy to miss because no session owns them.
SELECT gid, prepared, owner, database, age(transaction) AS xid_age
FROM pg_prepared_xacts ORDER BY prepared;
--     gid      |         prepared          | owner | xid_age
-- -------------+---------------------------+-------+----------
--  order-8812  | 2026-08-14 03:12:44+00    | app   |  9104882   ⭐ a MONTH old

ROLLBACK PREPARED 'order-8812';
```

```sql
-- ⭐ If you do not use two-phase commit, DISABLE IT.
--    This removes an entire class of silent, hard-to-diagnose incident.
ALTER SYSTEM SET max_prepared_transactions = 0;   -- requires restart
-- (This is the default. Verify nobody has changed it.)
```

> **Chapter 05 §5.7 argued against 2PC on design grounds. This is the operational argument:** a coordinator failure leaves a transaction that holds locks, blocks vacuum, and threatens wraparound, indefinitely, with no session to kill. Sagas have no equivalent failure mode.

---

## 26. Monitoring locks

### The blocking-chain query — keep this in your runbook

```sql
-- ⭐ THE query for "the application is hung"
WITH RECURSIVE blocking AS (
    SELECT pid, pg_blocking_pids(pid) AS blocked_by, 1 AS depth,
           pid::text AS chain
    FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0
    UNION ALL
    SELECT b.pid, pg_blocking_pids(b.pid), blocking.depth + 1,
           blocking.chain || ' <- ' || b.pid::text
    FROM pg_stat_activity b
    JOIN blocking ON b.pid = ANY(blocking.blocked_by)
    WHERE blocking.depth < 10
)
SELECT a.pid, a.state,
       now() - a.xact_start AS xact_age,
       now() - a.query_start AS query_age,
       a.wait_event_type, a.wait_event,
       cardinality(pg_blocking_pids(a.pid)) AS num_blockers,
       pg_blocking_pids(a.pid) AS blocked_by,
       left(a.query, 80) AS query
FROM pg_stat_activity a
WHERE a.state <> 'idle'
ORDER BY num_blockers DESC NULLS LAST, xact_age DESC NULLS LAST;
```

### Finding the root blocker

```sql
-- ⭐ The one transaction at the head of the chain
SELECT pid, usename, state, now() - xact_start AS duration,
       wait_event_type, wait_event, left(query, 100) AS query
FROM pg_stat_activity
WHERE pid IN (
    SELECT unnest(pg_blocking_pids(pid)) FROM pg_stat_activity
)
AND cardinality(pg_blocking_pids(pid)) = 0   -- ⭐ blocks others, blocked by none
ORDER BY xact_start;

-- Then:
SELECT pg_cancel_backend(<pid>);      -- ⭐ try this first — cancels the query
SELECT pg_terminate_backend(<pid>);   -- kills the connection
```

### Lock counts and exhaustion

```sql
-- Are you approaching the lock table limit?
SELECT count(*) AS total_locks,
       current_setting('max_locks_per_transaction')::int
         * (current_setting('max_connections')::int
            + current_setting('max_prepared_transactions')::int) AS capacity
FROM pg_locks;
-- ⭐ "ERROR: out of shared memory / HINT: You might need to increase
--     max_locks_per_transaction" happens when this fills.
--     Common cause: a transaction touching thousands of PARTITIONS,
--     each of which needs its own relation lock.

-- Lock waits by type
SELECT wait_event_type, wait_event, count(*)
FROM pg_stat_activity WHERE wait_event IS NOT NULL
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15;
```

### Deadlock and serialization metrics

```sql
SELECT datname, deadlocks, xact_commit, xact_rollback,
       round(100.0*xact_rollback/NULLIF(xact_commit+xact_rollback,0),2) AS rollback_pct
FROM pg_stat_database WHERE datname = current_database();
```

```promql
# ⭐ The alerts
rate(pg_stat_database_deadlocks[5m]) > 0.1          # deadlocks/sec
pg_locks_count / pg_locks_capacity > 0.7            # lock table filling
pg_prepared_xacts_count > 0                         # ⭐ orphaned 2PC
max(pg_stat_activity_max_tx_duration) > 300         # long transactions
```

---

## 27. The tuning summary

```sql
-- ═══ 1. BOUND LOCK HOLDING — the highest-value settings ═══
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';  -- ⭐ DD04 §16
ALTER SYSTEM SET statement_timeout = '60s';                      -- per role
ALTER SYSTEM SET lock_timeout = '0';                             -- ⭐ global 0,
--   but ALWAYS set it per-session before DDL (§10)

-- ═══ 2. VISIBILITY ═══
ALTER SYSTEM SET log_lock_waits = on;               -- ⭐ logs at deadlock_timeout
ALTER SYSTEM SET deadlock_timeout = '1s';           -- leave it
ALTER SYSTEM SET log_min_duration_statement = '1s';

-- ═══ 3. IF USING SERIALIZABLE (§21) ═══
ALTER SYSTEM SET max_pred_locks_per_transaction = 256;
ALTER SYSTEM SET max_pred_locks_per_page = 4;

-- ═══ 4. LOCK TABLE CAPACITY ═══
ALTER SYSTEM SET max_locks_per_transaction = 128;   -- ⭐ raise if you use
--   many partitions; requires restart

-- ═══ 5. ELIMINATE 2PC RISK IF UNUSED (§25) ═══
ALTER SYSTEM SET max_prepared_transactions = 0;     -- requires restart

-- ═══ 6. MULTIXACT (§8) — if you have hot parent rows ═══
ALTER SYSTEM SET autovacuum_multixact_freeze_max_age = 200000000;
ALTER SYSTEM SET vacuum_multixact_freeze_min_age = 5000000;

SELECT pg_reload_conf();
```

### Application-side rules

```
1. ⭐ Acquire locks in a consistent order (sorted key), ALWAYS (§12)
2. ⭐ Use explicit SELECT ... ORDER BY ... FOR UPDATE for multi-row locking (§15)
3. ⭐ Retry 40001 and 40P01 with jitter (§24)
4. ⭐ Never do I/O inside a transaction (§24 rule 2)
5. ⭐ Never update primary keys (§13)
6. ⭐ Set lock_timeout before every DDL statement (§10)
7. Batch large updates, committing between batches (§16)
8. Use SERIALIZABLE per-transaction, not globally (§24)
9. Use SERIALIZABLE READ ONLY DEFERRABLE for long reports (§23)
10. Use advisory _xact_ locks, never session-level, behind a pooler (§17)
```

---

## 28. What an architect takes from this

**1. There are two lock systems.** Table locks are in a bounded shared-memory manager; row locks are in the tuples themselves and are effectively unbounded. This is why PostgreSQL has no lock escalation, and why `SELECT ... FOR UPDATE` on a large set is a write-heavy operation.

**2. The DDL queue-blocking incident is the most common self-inflicted PostgreSQL outage**, and it is prevented entirely by `SET lock_timeout` plus a retry loop in your migration tool. Two lines.

**3. `NOT VALID` + `VALIDATE CONSTRAINT` is the pattern that makes almost every constraint addition safe.** `VALIDATE` takes only `SHARE UPDATE EXCLUSIVE` — it does not block reads or writes.

**4. Deadlocks are a design problem, not a database problem.** Consistent lock ordering eliminates the classic case. But the foreign-key, unique-index and unordered-multi-row cases are invisible in the application code, and you must recognise them by shape.

**5. Never update a primary key.** It escalates `FOR NO KEY UPDATE` to `FOR UPDATE`, reintroduces FK contention, and creates the §13 deadlock.

**6. MultiXact wraparound is a second, independent wraparound risk** that most monitoring misses entirely, and hot parent rows with foreign keys are what cause it.

**7. SSI never blocks — it kills after the fact.** Retry logic is therefore part of the mechanism, not an optional robustness measure. Budget for a 1–5% abort rate and treat anything higher as a tuning signal.

**8. Under `SERIALIZABLE`, missing indexes cause serialization failures**, because a sequential scan takes a relation-level predicate lock. Adding an index reduces aborts as well as latency — a connection almost nobody makes.

**9. `SERIALIZABLE READ ONLY DEFERRABLE` makes long reports invisible to the rest of the system.** It is the correct mode for analytics on a serializable database and it is almost unknown.

**10. An orphaned prepared transaction is a triple threat** — held locks, pinned xmin horizon, blocked freezing — and it is invisible in `pg_stat_activity`. If you do not use 2PC, set `max_prepared_transactions = 0`.

**11. Locking is where Chapter 09's rules come from.** "Keep transactions short", "no I/O in a transaction", "acquire locks in a consistent order", "always set `lock_timeout` for DDL" — every one is a direct consequence of a mechanism in this deep dive. You can now explain *why*, which is how those rules actually get adopted.

---

## Exercises

1. Reproduce the §10 queue-blocking incident on a test database: a long `SELECT`, then an `ALTER TABLE`, then a short `SELECT`. Observe the third one blocking. Then fix it with `lock_timeout`.
2. Use the `BEGIN; ... ; ROLLBACK;` recipe from §4 to determine the lock mode of five DDL statements you plan to run.
3. Construct and reproduce the classic transfer deadlock. Then fix it with consistent ordering and prove the fix.
4. Reproduce the foreign-key deadlock from §13. Explain to a colleague why two `INSERT`s into `orders` deadlocked on `customers`.
5. Reproduce the unique-index deadlock from §14 and fix it with a batched `INSERT ... ON CONFLICT`.
6. Query `pg_locks` during a `SELECT ... FOR UPDATE` and explain why you see a `transactionid` lock rather than a row lock.
7. Check `mxid_age(datminmxid)` on your production database. Is it monitored? Add the alert.
8. Measure the WAL generated by `SELECT ... FOR UPDATE` on 100,000 rows. Explain the result.
9. Write the complete safe migration to change a column from `integer` to `bigint` on a 500 M row table. List every release and its lock impact.
10. Run `CREATE INDEX CONCURRENTLY` while holding a long transaction open in another session. Observe it hanging, then explain which phase it is in.
11. Enable `SERIALIZABLE` on a test workload and measure the abort rate. Then remove an index and measure again. Explain the difference.
12. Reproduce the §22 dangerous structure and read the exact error message. Identify which transaction was the pivot.
13. Use `SERIALIZABLE READ ONLY DEFERRABLE` for a long report while OLTP traffic runs. Compare the abort rate against a plain `SERIALIZABLE` report.
14. Create a prepared transaction, leave it unresolved, and observe its effect on `pg_replication_slots`-style horizon queries, bloat, and `pg_locks`. Then clean it up.
15. Write the runbook entry for "the application is hung and all connections are waiting". Include the exact queries and the decision of cancel vs terminate.

---

**Next in this series:** Deep Dive 09 — LSM Trees and Write-Optimised Storage

**Back to:** [Deep Dives](README.md) · [Chapter 09](../09-database-architecture.md) · [The Map](../README.md)
