# Deep Dive 04 — PostgreSQL MVCC and Storage Internals

**Prerequisite:** [Chapter 09 — Database Architecture](../09-database-architecture.md) §9.4

**What the map said:** *"An UPDATE is really insert-a-new-version + mark-the-old-one-dead. Dead tuples stay on disk until vacuumed. Readers never block writers."*

**What this deep dive does:** opens an 8 KB page byte by byte, walks the tuple header field by field, implements the visibility algorithm exactly as PostgreSQL does, explains hint bits and why a `SELECT` can generate write I/O, traces a HOT update through a page, quantifies bloat with real arithmetic, explains precisely what blocks `VACUUM` and how to find it, walks transaction ID wraparound to the point where the database refuses to start, covers TOAST, and ends with the tuning that actually matters.

---

## Contents

```
1.  Why PostgreSQL chose this design
2.  The 8 KB page, byte by byte
3.  The tuple header, field by field
4.  What a row actually costs
5.  Transaction IDs and the 32-bit problem
6.  Snapshots: the exact data structure
7.  The visibility algorithm, implemented
8.  Traced scenario — four concurrent transactions
9.  Hint bits: why SELECT writes to disk
10. The commit log (pg_xact)
11. UPDATE = DELETE + INSERT, and the ctid chain
12. HOT updates ⭐ — the optimisation that changes everything
13. Traced scenario — a page through six updates
14. Bloat: the arithmetic
15. VACUUM: what it actually does, phase by phase
16. The xmin horizon — what stops VACUUM ⭐
17. Traced scenario — one idle transaction, 40 GB of bloat
18. Autovacuum tuning: the defaults are wrong for large tables
19. Freezing and transaction ID wraparound
20. The wraparound emergency, step by step
21. VACUUM FULL, pg_repack, and index bloat
22. TOAST — oversized attributes
23. The visibility map and index-only scans
24. Measuring bloat accurately
25. PostgreSQL MVCC vs Oracle, InnoDB and SQL Server
26. The tuning that actually matters
27. What an architect takes from this
```

---

## 1. Why PostgreSQL chose this design

Before the mechanics, the decision — because everything else follows from it.

**The problem:** readers and writers contend. A naive database takes a read lock for every read and a write lock for every write, and analytical queries block transactional writes.

**The MVCC insight:** keep multiple versions of each row. A reader takes a *snapshot* and sees the versions that were current at snapshot time. A writer creates a *new* version. Neither needs to wait for the other.

**The implementation choice, and this is where PostgreSQL differs from everyone else:**

```
WHERE DO OLD VERSIONS LIVE?

PostgreSQL:            In the table itself, beside the current version.
                       ✅ Reads are trivially fast — no reconstruction
                       ✅ Rollback is free (just mark the new version dead)
                       ❌ The table grows with every update
                       ❌ Needs VACUUM to reclaim space

Oracle / MySQL InnoDB: Current version in place; old versions in a separate
                       UNDO log, reconstructed on demand.
                       ✅ The table stays compact
                       ❌ Long-running readers must walk undo chains
                       ❌ "ORA-01555 snapshot too old" when undo is recycled
                       ❌ Rollback is expensive (must apply undo)

SQL Server (RCSI/SI):  Old versions in tempdb's version store.
                       Similar trade-offs to Oracle; tempdb becomes a bottleneck.
```

> **Everything difficult about PostgreSQL operations — bloat, VACUUM tuning, wraparound, table growth under update-heavy workloads — is a direct consequence of this one choice.** And everything pleasant about it — fast reads under concurrency, instant rollback, no "snapshot too old", simple recovery — is the same choice's other side.

Understanding this trade is the point of the whole deep dive. It tells you *which* workloads suit PostgreSQL and which need care.

---

## 2. The 8 KB page, byte by byte

Every table and index is an array of fixed-size **pages** (`BLCKSZ`, 8192 bytes by default, set at compile time).

```
 byte 0                                                          byte 8191
 ┌────────────────────────────────────────────────────────────────────────┐
 │ PageHeaderData  (24 bytes)                                             │
 ├────────────────────────────────────────────────────────────────────────┤
 │ ItemId[1] ItemId[2] ItemId[3] ...    (4 bytes each, grow RIGHTWARD →)  │
 ├────────────────────────────────────────────────────────────────────────┤
 │                                                                        │
 │                      FREE SPACE                                        │
 │              (pd_lower ──►      ◄── pd_upper)                          │
 │                                                                        │
 ├────────────────────────────────────────────────────────────────────────┤
 │  ... Tuple[3]   Tuple[2]   Tuple[1]   (grow LEFTWARD ←)                │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Special space (0 bytes for heap; 16 bytes for a B-tree page)           │
 └────────────────────────────────────────────────────────────────────────┘
```

**The two-ended layout is deliberate:** fixed-size line pointers grow forward from the header, variable-size tuples grow backward from the end, and free space is whatever is left in the middle. This lets a tuple be moved within the page (during pruning) without changing the index entries that point at it — because indexes point at the **line pointer**, not the tuple.

### PageHeaderData

```c
typedef struct PageHeaderData {
    PageXLogRecPtr pd_lsn;        /*  8 B — LSN of the last WAL record for this page.
                                          Used by the "WAL before data" rule (DD: WAL). */
    uint16   pd_checksum;         /*  2 B — page checksum if data checksums are enabled */
    uint16   pd_flags;            /*  2 B — PD_HAS_FREE_LINES, PD_PAGE_FULL,
                                          PD_ALL_VISIBLE  ⭐ (see §23) */
    LocationIndex pd_lower;       /*  2 B — offset to the end of the line pointer array */
    LocationIndex pd_upper;       /*  2 B — offset to the start of the tuple area */
    LocationIndex pd_special;     /*  2 B — offset to the special space */
    uint16   pd_pagesize_version; /*  2 B */
    TransactionId pd_prune_xid;   /*  4 B — ⭐ a hint: "a transaction older than this
                                          left prunable tuples here" (§12) */
    ItemIdData pd_linp[];         /*  the line pointer array starts here */
} PageHeaderData;                 /*  24 bytes total */
```

**Free space on the page is exactly `pd_upper − pd_lower`.** That single subtraction decides whether an update can be a HOT update (§12), which turns out to matter enormously.

### ItemIdData — the line pointer

```c
typedef struct ItemIdData {
    unsigned lp_off:15,    /* offset of the tuple within the page */
             lp_flags:2,   /* state */
             lp_len:15;    /* length of the tuple */
} ItemIdData;              /* exactly 4 bytes */
```

```
lp_flags:
  LP_UNUSED   (0)  free slot, reusable
  LP_NORMAL   (1)  points to a real tuple
  LP_REDIRECT (2)  ⭐ points to ANOTHER line pointer on this page (HOT chains, §12)
  LP_DEAD     (3)  the tuple is dead; the line pointer cannot be reused yet
                   because index entries may still point at it
```

**`LP_DEAD` is the state that makes VACUUM a two-pass operation** (§15). The heap tuple can be removed immediately, but the *line pointer* must survive until every index entry pointing to it has been removed — otherwise an index scan would follow a pointer to a slot that has been reused by a different row.

### Inspecting a real page

```sql
CREATE EXTENSION pageinspect;

SELECT lower, upper, special, pagesize, prune_xid
FROM page_header(get_raw_page('accounts', 0));
--  lower | upper | special | pagesize | prune_xid
-- -------+-------+---------+----------+-----------
--     92 |  7360 |    8192 |     8192 |         0
--
-- lower 92 = 24 (header) + 17 line pointers × 4 = 92  → 17 line pointers in use
-- free space = 7360 − 92 = 7268 bytes
```

---

## 3. The tuple header, field by field

Every row carries a 23-byte header (padded to 24) that holds the MVCC bookkeeping. This is where visibility lives.

```c
typedef struct HeapTupleHeaderData {
    union {
        HeapTupleFields t_heap;
        DatumTupleFields t_datum;
    } t_choice;                    /* 12 bytes: */
        /* TransactionId t_xmin;    4 B — the xid that INSERTED this version   */
        /* TransactionId t_xmax;    4 B — the xid that DELETED/UPDATED it, or 0 */
        /* union { CommandId t_cid; TransactionId t_xvac; }  4 B                */

    ItemPointerData t_ctid;        /*  6 B — ⭐ block(4) + offset(2).
                                          Points to ITSELF, or to the NEWER version. */
    uint16   t_infomask2;          /*  2 B — attribute count + HOT flags */
    uint16   t_infomask;           /*  2 B — ⭐ the hint bits (§9) */
    uint8    t_hoff;               /*  1 B — offset from header start to user data */
    /* then: optional null bitmap, then padding to MAXALIGN, then the data */
} HeapTupleHeaderData;             /* 23 bytes, padded to 24 */
```

### The fields that matter

| Field | Meaning |
|-------|---------|
| **`t_xmin`** | The transaction that created this version. A reader asks: *did this transaction commit, and was it visible to my snapshot?* |
| **`t_xmax`** | The transaction that deleted or updated it (0 = still live). A reader asks: *did this transaction commit and is it visible to me? If so, this version is gone for me.* |
| **`t_cid`** | Command ID within the transaction — so statement 3 of a transaction sees the effects of statements 1 and 2 but not of itself |
| **`t_ctid`** | Normally points to itself. After an UPDATE, points to the **newer** version — forming a version chain |
| **`t_infomask`** | Hint bits and flags (below) |
| **`t_infomask2`** | Number of attributes, plus `HEAP_HOT_UPDATED` and `HEAP_ONLY_TUPLE` |

### The infomask bits you will actually encounter

```c
#define HEAP_HASNULL            0x0001   /* a null bitmap follows the header */
#define HEAP_HASVARWIDTH        0x0002   /* has variable-length attributes    */
#define HEAP_HASEXTERNAL        0x0004   /* ⭐ has a TOAST pointer (§22)      */

#define HEAP_XMIN_COMMITTED     0x0100   /* ⭐ hint: xmin is known committed  */
#define HEAP_XMIN_INVALID       0x0200   /* ⭐ hint: xmin is known aborted    */
#define HEAP_XMIN_FROZEN        0x0300   /* ⭐ both bits: frozen (§19)        */
#define HEAP_XMAX_COMMITTED     0x0400   /* hint: xmax is known committed     */
#define HEAP_XMAX_INVALID       0x0800   /* hint: xmax is invalid/aborted     */

#define HEAP_UPDATED            0x2000   /* this version was produced by UPDATE */
```

```c
/* in t_infomask2 */
#define HEAP_HOT_UPDATED        0x4000   /* ⭐ this tuple was HOT-updated (§12) */
#define HEAP_ONLY_TUPLE         0x8000   /* ⭐ this tuple has NO index entries   */
```

### Reading real tuple headers

```sql
SELECT lp, lp_off, lp_flags, t_xmin, t_xmax, t_ctid,
       t_infomask::bit(16) AS infomask,
       t_infomask2::bit(16) AS infomask2
FROM heap_page_items(get_raw_page('accounts', 0))
WHERE lp_flags = 1;

--  lp | lp_off | lp_flags | t_xmin | t_xmax | t_ctid |     infomask     | infomask2
-- ----+--------+----------+--------+--------+--------+------------------+-----------
--   1 |   8144 |        1 |    847 |      0 | (0,1)  | 0000100100000010 | 0000000000000011
--                                    ↑        ↑          ↑↑
--                          not deleted   self  XMIN_COMMITTED + HASVARWIDTH
--
--   2 |   8096 |        1 |    851 |    853 | (0,3)  | 0000110100000010 | 0100000000000011
--                                    ↑        ↑                            ↑
--                       deleted by 853   points to (0,3)              HEAP_HOT_UPDATED
--                                        — the newer version!
```

That second row is a HOT-updated tuple. Its `t_ctid` points to line pointer 3 on the same page, and `HEAP_HOT_UPDATED` is set. §12 explains exactly what that means.

---

## 4. What a row actually costs

The overhead surprises people, and it drives real capacity decisions.

```
Per row:
    line pointer (ItemIdData)          4 bytes
    tuple header (HeapTupleHeaderData) 23 bytes → padded to 24
    null bitmap (if any column is NULL) ceil(ncols / 8) bytes, within the padding
    ───────────────────────────────────────────
    MINIMUM per row:                   28 bytes, before any data
```

### Worked example: a narrow table

```sql
CREATE TABLE events (
    id         bigint,       --  8 bytes
    tenant_id  uuid,         -- 16 bytes
    kind       smallint,     --  2 bytes
    created_at timestamptz   --  8 bytes
);
```

```
Data:      8 + 16 + 2 + 8 = 34 bytes
Alignment: timestamptz needs 8-byte alignment. With this column ORDER:
             id (8, aligned at 0)
             tenant_id (16, aligned at 8)
             kind (2, at 24)
             created_at (8, needs alignment 8 → 6 bytes PADDING at 26, starts at 32)
           → 40 bytes of data instead of 34

Header:    24 bytes
Pointer:    4 bytes
─────────────────────
Total:     68 bytes per row for 34 bytes of actual data.  50% overhead.
```

### ⭐ Column order matters, and it is free to fix

```sql
-- REORDER: widest-alignment columns first
CREATE TABLE events (
    id         bigint,       -- 8, at 0
    created_at timestamptz,  -- 8, at 8
    tenant_id  uuid,         -- 16, at 16
    kind       smallint      -- 2, at 32
);                            -- total 34, padded to 40 at the end anyway here,
                              -- but on wider tables this saves substantially
```

**The general rule: order columns from widest alignment requirement to narrowest** — `bigint`/`timestamptz`/`double` (8) → `int`/`float4` (4) → `smallint` (2) → `char`/`bool` (1) → variable-length (`text`, `numeric`, `jsonb`) last.

On a wide table with many small columns interleaved with large ones, this routinely saves 10–20% of table size. It costs nothing, it is invisible to queries, and almost nobody does it.

```sql
-- Find the padding waste in an existing table
SELECT a.attname, t.typname, t.typalign, t.typlen
FROM pg_attribute a
JOIN pg_type t ON t.oid = a.atttypid
WHERE a.attrelid = 'events'::regclass AND a.attnum > 0
ORDER BY a.attnum;
-- typalign: 'd'=8, 'i'=4, 's'=2, 'c'=1
```

### Rows per page

```
Usable space per page = 8192 − 24 (header) = 8168 bytes

68-byte row:   8168 / 68 ≈ 120 rows per page
200-byte row:  8168 / 200 ≈ 40 rows per page
```

**Which means: a table of 100 million 68-byte rows occupies roughly 833,000 pages = 6.8 GB** — before any bloat, before any indexes.

---

## 5. Transaction IDs and the 32-bit problem

```c
typedef uint32 TransactionId;   /* ⭐ 32 bits. This is the source of §19–20. */

#define InvalidTransactionId        ((TransactionId) 0)
#define BootstrapTransactionId      ((TransactionId) 1)
#define FrozenTransactionId         ((TransactionId) 2)   /* ⭐ "always visible" */
#define FirstNormalTransactionId    ((TransactionId) 3)
```

Only **4.29 billion** transaction IDs exist. A busy system generating 5,000 write transactions per second exhausts them in **ten days**.

### Comparison is circular

Because IDs wrap, PostgreSQL cannot simply compare them as integers. It compares them **modulo 2³¹**:

```c
bool TransactionIdPrecedes(TransactionId id1, TransactionId id2)
{
    int32 diff = (int32) (id1 - id2);   /* ⭐ signed subtraction of unsigned ints */
    return (diff < 0);
}
```

```
From any transaction's viewpoint:
    the 2 billion IDs "behind" it  → in the PAST    (visible)
    the 2 billion IDs "ahead" of it → in the FUTURE  (invisible)

    ┌──────────────── 4.29 billion IDs, arranged in a circle ──────────────┐
    │                                                                       │
    │      PAST (2^31 IDs)          [current xid]         FUTURE (2^31)     │
    │      ◄──────────────────────────────●──────────────────────────►      │
    │                                                                       │
    └───────────────────────────────────────────────────────────────────────┘
                         the two halves MEET on the far side
```

**The catastrophic failure this permits:** a tuple whose `xmin` is 2.1 billion transactions old appears to be in the **future**, and therefore **invisible**. The row still exists on disk and no query can see it.

§19 explains **freezing**, which is the mechanism that prevents this, and §20 walks through what happens when freezing falls behind.

> **Note:** PostgreSQL 17 introduced 64-bit transaction IDs internally in some paths, and there is long-running work toward eliminating this class of problem entirely. As of the versions in wide production use, the 32-bit limit is real and you must operate around it.

---

## 6. Snapshots: the exact data structure

A snapshot is what makes a transaction see a consistent point in time.

```c
typedef struct SnapshotData {
    TransactionId xmin;    /* ⭐ oldest xid still RUNNING when this snapshot was taken.
                                 Anything < xmin is definitely COMPLETE (committed or
                                 aborted) — its status is settled. */
    TransactionId xmax;    /* ⭐ first xid NOT YET ASSIGNED at snapshot time.
                                 Anything >= xmax started AFTER us → invisible. */
    TransactionId *xip;    /* ⭐ the array of xids that were IN PROGRESS at
                                 snapshot time (between xmin and xmax). */
    uint32 xcnt;           /* length of xip */
    CommandId curcid;      /* our own command counter — for statement-level visibility */
    /* ... subtransaction handling, and more ... */
} SnapshotData;
```

### The three regions

```
     xmin                                    xmax
      │                                       │
──────┼───────────────────────────────────────┼──────────►  transaction IDs
      │                                       │
  ALL COMPLETE          MIXED             ALL FUTURE
  (committed or    (check xip[]:         (started after
   aborted —        in the list = still    our snapshot →
   check clog)      running → invisible)   invisible)
```

**When is a snapshot taken?**

```
READ COMMITTED (the default):   a NEW snapshot at the start of EACH STATEMENT
REPEATABLE READ / SERIALIZABLE: ONE snapshot at the first statement,
                                held for the WHOLE transaction    ⭐
```

That difference is why Read Committed allows non-repeatable reads and why Repeatable Read does not (Deep Dive 03 §9) — and, critically for §16, why **a long-running `REPEATABLE READ` transaction pins the xmin horizon for its entire duration** while a Read Committed one only pins it per statement.

### Watching snapshots in action

```sql
-- In session 1:
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT 1;                              -- forces the snapshot to be taken
SELECT pg_current_snapshot();
--  pg_current_snapshot
-- ---------------------
--  847:851:847,849       ← xmin:xmax:xip[]
--
--  xmin = 847   anything below 847 is settled
--  xmax = 851   anything ≥ 851 is in our future
--  xip  = {847, 849}  these two were running → invisible to us
--         (848 and 850 were already complete → visible if committed)
```

---

## 7. The visibility algorithm, implemented

This is `HeapTupleSatisfiesMVCC`, the function every row read passes through. Here it is in Python, with the real logic.

```python
def is_visible(tuple_header, snapshot, my_xid, my_command_id) -> bool:
    """
    PostgreSQL's MVCC visibility check.
    Returns True if this tuple version is visible to this snapshot.
    """
    xmin = tuple_header.t_xmin
    xmax = tuple_header.t_xmax

    # ═══════════════ PART 1: is the INSERTING transaction visible to us? ════════
    if xmin == FROZEN_TRANSACTION_ID or tuple_header.infomask & HEAP_XMIN_FROZEN:
        pass                              # ⭐ frozen: visible to everyone forever (§19)

    elif xmin == my_xid:
        # We inserted it ourselves.
        if tuple_header.t_cid >= my_command_id:
            return False                  # ⭐ inserted by a LATER command in this
                                          #    same transaction — the Halloween
                                          #    Problem guard. An UPDATE must not
                                          #    see the rows it is itself producing.
        # else: visible to us (an earlier statement in our transaction inserted it)

    elif not transaction_committed(xmin, snapshot):
        return False                      # inserter aborted, or is still running,
                                          # or started after our snapshot → invisible

    # ═══════════════ PART 2: is the DELETING transaction visible to us? ═════════
    if xmax == INVALID_TRANSACTION_ID or (tuple_header.infomask & HEAP_XMAX_INVALID):
        return True                       # never deleted → visible

    if tuple_header.infomask & HEAP_XMAX_IS_MULTI:
        # Multiple transactions hold row locks (SELECT FOR SHARE etc.).
        # Resolve the MultiXact to find whether an actual DELETE is among them.
        return not multixact_has_visible_delete(xmax, snapshot)

    if xmax == my_xid:
        # We deleted it ourselves.
        if tuple_header.t_cid >= my_command_id:
            return True                   # deleted by a LATER command → still
                                          #  visible to THIS command
        return False                      # deleted by an earlier command in our txn

    if not transaction_committed(xmax, snapshot):
        return True                       # ⭐ the deleter aborted or is still
                                          #    running → the row is still live FOR US

    return False                          # deleted by a committed, visible transaction


def transaction_committed(xid, snapshot) -> bool:
    """Did this xid commit, AND is that commit visible to our snapshot?"""
    if xid >= snapshot.xmax:
        return False              # started after our snapshot → in our future
    if xid in snapshot.xip:
        return False              # was running when we took our snapshot
    if xid < snapshot.xmin:
        return clog_status(xid) == COMMITTED     # settled — consult the commit log
    return clog_status(xid) == COMMITTED         # between xmin and xmax, not in xip
                                                  # → it completed; check how
```

### The three things worth noticing

**1. Every row read potentially consults the commit log.** For each tuple, PostgreSQL may need to look up whether `xmin` (and `xmax`) committed. That would be a disaster for performance — which is why hint bits exist (§9).

**2. An aborted deleter leaves the row visible.** If transaction 900 ran `DELETE`, set `xmax = 900`, and then rolled back, the row is still live. **Nothing is undone** — the `xmax` simply never becomes visible. This is why rollback in PostgreSQL is essentially free, and why a rolled-back `DELETE` costs nothing to reverse.

**3. The command ID check prevents the Halloween Problem.** Without it, `UPDATE accounts SET balance = balance * 1.1` could see the rows it had already updated and update them again, looping. The `t_cid >= my_command_id` test makes a statement blind to its own output.

---

## 8. Traced scenario — four concurrent transactions

Watch the tuple headers change as four transactions interleave.

```
Initial state — one row, inserted by transaction 800 (long since committed):

  lp | t_xmin | t_xmax | t_ctid |  balance | infomask
  ---+--------+--------+--------+----------+------------------
   1 |    800 |      0 | (0,1)  |     1000 | XMIN_COMMITTED
```

```
t=0   TX 850 begins (READ COMMITTED). No snapshot yet.

t=1   TX 851 begins (REPEATABLE READ).
      SELECT → snapshot: xmin=850, xmax=852, xip={850}
      is_visible: xmin=800 < 850, clog says COMMITTED ✓
                  xmax=0 → visible ✓
      → sees balance = 1000

t=2   TX 850: UPDATE accounts SET balance = 900 WHERE id = 1;

      Physically, this does TWO things:
        (a) mark the old tuple deleted:   t_xmax = 850
        (b) INSERT a brand new tuple with t_xmin = 850

  lp | t_xmin | t_xmax | t_ctid |  balance | note
  ---+--------+--------+--------+----------+---------------------------
   1 |    800 |    850 | (0,2)  |     1000 | old version; ctid → (0,2)
   2 |    850 |      0 | (0,2)  |      900 | new version

      ⭐ Nothing was overwritten. Both versions exist on the page.

t=3   TX 851 (REPEATABLE READ, same snapshot from t=1): SELECT

      Tuple 1:  xmin=800 committed & visible ✓
                xmax=850 — is 850 visible to us?
                   850 is in our xip[] → still running at snapshot time
                   → transaction_committed() = False
                   → "the deleter is not visible to us" → TUPLE IS VISIBLE ✓
      Tuple 2:  xmin=850 — in our xip[] → NOT visible ✗

      → TX 851 still sees balance = 1000.  ⭐ Correct: its snapshot predates TX 850.

t=4   TX 852 begins (READ COMMITTED). SELECT.
      Snapshot: xmin=850, xmax=853, xip={850, 851}

      Tuple 1:  xmax=850, in xip → not visible → tuple visible
      Tuple 2:  xmin=850, in xip → not visible

      → TX 852 also sees 1000. TX 850 has not committed yet.

t=5   TX 850 COMMITS.

t=6   TX 852: SELECT again.
      ⭐ READ COMMITTED → a NEW SNAPSHOT for this statement:
         xmin=851, xmax=853, xip={851}

      Tuple 1:  xmax=850. 850 < xmin(851) → settled. clog: COMMITTED.
                → the deleter IS visible → TUPLE NOT VISIBLE ✗
      Tuple 2:  xmin=850 < 851 → settled, COMMITTED ✓; xmax=0 → VISIBLE ✓

      → TX 852 now sees 900.  ⭐ A non-repeatable read: it saw 1000, now 900.
                                 That is Read Committed working as designed.

t=7   TX 851: SELECT again (REPEATABLE READ — SAME snapshot as t=1)
      → still sees 1000.  ⭐ Repeatable Read working as designed.

t=8   TX 851 COMMITS.

      ⭐ ONLY NOW can tuple 1 be removed by VACUUM. Until TX 851 ended,
         tuple 1 was potentially needed. This is §16 in miniature.
```

**The last line is the whole operational story of PostgreSQL.** A dead tuple cannot be reclaimed while *any* transaction might still need to see it. One long transaction pins every dead tuple created after it began.

---

## 9. Hint bits: why SELECT writes to disk

The visibility algorithm consults the commit log for every tuple. That would be catastrophically slow. **Hint bits** are the cache.

```
First reader of a tuple whose xmin status is unknown:
    1. Look up xid 850 in pg_xact → COMMITTED
    2. ⭐ SET the HEAP_XMIN_COMMITTED bit in the tuple's infomask
    3. The page is now DIRTY

Every subsequent reader:
    1. See HEAP_XMIN_COMMITTED → skip the clog lookup entirely
```

### The surprising consequence

```sql
-- Load a lot of data
INSERT INTO big_table SELECT ... ;   -- 10 million rows
COMMIT;

-- Now the FIRST read:
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM big_table;
--   Buffers: shared hit=0 read=125000 DIRTIED=125000   ⭐⭐
--                                     ↑↑↑↑↑↑↑↑↑↑↑↑↑
--   A read-only query dirtied 125,000 pages (≈1 GB) and they must now be
--   written back to disk.

-- The SECOND identical read:
--   Buffers: shared hit=125000 dirtied=0
--   Fast, and no I/O.
```

**This is a real and frequently-reported phenomenon:**

- *"Why is my first `SELECT` after a bulk load so slow?"*
- *"Why does a read-only query cause a write I/O spike?"*
- *"Why did a checkpoint happen right after I ran a report?"*

All three are hint bits.

### The interaction with data checksums

```
data_checksums = off (default in a plain initdb):
    Hint bit changes are NOT WAL-logged. The page is dirtied, written once.

data_checksums = on  (or wal_log_hints = on — ⭐ REQUIRED for pg_rewind):
    A hint bit change alters the page → the checksum changes →
    the change MUST be WAL-logged (as a full-page image after a checkpoint).

    ⭐ So on a checksummed cluster, the first read after a bulk load
       generates WAL. This genuinely surprises people.
```

**This is a real trade-off worth making deliberately.** Data checksums catch silent disk corruption, which is valuable; they also mean read-heavy workloads on freshly-written data generate WAL. On modern hardware the checksum CPU cost is negligible (1–2%) and most people should enable them — but budget for the WAL.

### Mitigations

```sql
-- 1. VACUUM after a bulk load. It sets hint bits AND the visibility map (§23)
--    in one controlled pass, instead of letting the first user query pay for it.
VACUUM (ANALYZE) big_table;

-- 2. Or read it yourself, off the critical path, right after loading:
SELECT count(*) FROM big_table;

-- 3. For COPY specifically, pre-freezing skips the whole problem:
BEGIN;
TRUNCATE big_table;                  -- or CREATE TABLE, in the same transaction
COPY big_table FROM '...' WITH (FREEZE);   -- ⭐ tuples are written already frozen
COMMIT;
```

Option 3 is excellent for ETL: the tuples are written with `HEAP_XMIN_FROZEN` already set, so no hint bits are needed and **no future freeze scan is needed either** (§19). It requires that the table was created or truncated in the same transaction.

---

## 10. The commit log (pg_xact)

The authority on transaction status, consulted when hint bits are absent.

```
$PGDATA/pg_xact/     (called pg_clog before PostgreSQL 10)

Two bits per transaction:
    00  IN_PROGRESS
    01  COMMITTED
    10  ABORTED
    11  SUB_COMMITTED  (a subtransaction whose parent has not committed yet)

Density: 4 transactions per byte, 32,768 transactions per 8 KB page,
         256 KB per segment file = 1,048,576 transactions per file.

⭐ 4.29 billion transactions × 2 bits = ~1 GB maximum, ever.
   Old segments are deleted once all their transactions are frozen (§19).
```

Access goes through a small shared-memory SLRU cache. A lookup is normally a memory read; a miss is a page read from `pg_xact`.

**Why this matters operationally:** on a system with very high transaction rates and long-lived data, `pg_xact` lookups can become a measurable cost — visible as `SLRURead` wait events. The fix is the same as everything else here: keep hint bits set and keep tuples frozen.

---

## 11. UPDATE = DELETE + INSERT, and the ctid chain

There is no in-place update in PostgreSQL's heap. Ever.

```sql
UPDATE accounts SET balance = 900 WHERE id = 1;
```

```
1. Find the current version
2. Set its t_xmax = my_xid, and its t_ctid = <location of the new version>
3. Write a completely NEW tuple with t_xmin = my_xid
4. ⭐ Add an index entry to EVERY index on the table, pointing to the new tuple
   (unless this is a HOT update — §12)
```

### The version chain

```
Six updates to the same row produce a chain:

  lp 1: xmin=800  xmax=850  ctid=(0,2)  balance=1000  ─┐
  lp 2: xmin=850  xmax=851  ctid=(0,3)  balance=900   ─┤
  lp 3: xmin=851  xmax=852  ctid=(0,4)  balance=850   ─┤ chain
  lp 4: xmin=852  xmax=853  ctid=(0,5)  balance=800   ─┤
  lp 5: xmin=853  xmax=854  ctid=(0,6)  balance=750   ─┤
  lp 6: xmin=854  xmax=0    ctid=(0,6)  balance=700   ─┘  ← current

⭐ SIX physical rows for ONE logical row.
   Five of them are dead, and all five remain on disk until VACUUM runs
   AND no transaction still needs them (§16).
```

### The write amplification, quantified

```sql
-- A table with 5 indexes
UPDATE users SET last_seen_at = now() WHERE id = 42;
```

```
Without HOT, ONE update writes:
    1 new heap tuple                          ~200 bytes
    5 new index entries                       ~5 × 20 = 100 bytes
    WAL for all of the above                  ~400+ bytes
    (and full-page images if this is the first write to those pages
     after a checkpoint — potentially 8 KB PER PAGE TOUCHED)

Plus it CREATES:
    1 dead heap tuple
    5 dead index entries

⭐ A "last seen" heartbeat update at 1,000/sec on a 5-index table generates
   roughly 500,000 dead index entries per second.
```

**This is why `last_seen_at`-style columns are a classic PostgreSQL performance problem**, and why the fix is either a separate narrow table with no indexes, a HOT-friendly design (§12), or pushing the value into Redis.

### Using ctid for diagnosis

```sql
-- ctid is a system column: (page, line pointer)
SELECT ctid, id, balance FROM accounts WHERE id = 1;
--  ctid  | id | balance
-- -------+----+---------
--  (0,6) |  1 |     700

-- ⭐ ctid is NOT a stable row identifier. It changes on every UPDATE
--    and on VACUUM FULL. Never store it.

-- But it is excellent for seeing physical layout:
SELECT (ctid::text::point)[0]::int AS page, count(*)
FROM accounts GROUP BY 1 ORDER BY 1 LIMIT 10;
--  How many live rows per page? Low numbers on early pages = bloat.
```

---

## 12. HOT updates ⭐ — the optimisation that changes everything

**Heap-Only Tuple** updates avoid touching indexes entirely. This is the single most important PostgreSQL performance mechanism that developers can influence through schema design.

### The two conditions

```
A HOT update is possible if and only if:

  1. ⭐ The UPDATE does not modify ANY indexed column
  2. ⭐ The new tuple fits on the SAME page as the old one
```

Both must hold. Either alone is not enough.

### What happens

```
NORMAL UPDATE                          HOT UPDATE
                                       
index ──────► tuple v1 (dead)          index ──────► lp 1 (v1, dead)
index ──────► tuple v2 (live)                            │ t_ctid
                                                         ▼
5 indexes = 5 new entries                             lp 2 (v2, live)
                                                      HEAP_ONLY_TUPLE
                                       
                                       ⭐ ZERO index entries created.
                                          The index still points to lp 1;
                                          the scan follows the ctid chain.
```

The old tuple gets `HEAP_HOT_UPDATED`; the new tuple gets `HEAP_ONLY_TUPLE` (meaning "no index entry points directly at me").

### HOT pruning — cleanup without VACUUM

```
⭐ HOT chains can be cleaned up during ORDINARY page access — no VACUUM needed.

When a page is read and pd_prune_xid indicates prunable tuples:
    1. Dead tuples in the HOT chain are removed
    2. Their line pointers become LP_UNUSED (reusable immediately!)
    3. The root line pointer becomes LP_REDIRECT, pointing at the live tuple

  BEFORE:  lp1 (v1,dead) → lp2 (v2,dead) → lp3 (v3,live)
  AFTER:   lp1 = LP_REDIRECT → lp3
           lp2 = LP_UNUSED    ⭐ space reclaimed, no VACUUM involved
           lp3 (v3, live)
```

**This is why a well-designed update-heavy table can run almost indefinitely without bloating**: the updates are HOT, and pruning reclaims space during normal operation.

### Making HOT updates happen

**Condition 1 — do not index columns that change frequently.**

```sql
-- ❌ This index makes EVERY last_seen_at update non-HOT
CREATE INDEX idx_users_last_seen ON users (last_seen_at);

-- Ask: do you actually query by last_seen_at? Often it exists only because
-- someone added it "for reporting" years ago. Check:
SELECT idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'idx_users_last_seen';
```

**Condition 2 — leave free space on the page with `fillfactor`.**

```sql
-- Default fillfactor is 100: pages are packed full, so an update NEVER fits
-- on the same page, so it can NEVER be HOT.
ALTER TABLE users SET (fillfactor = 85);   -- leave 15% free for updates
VACUUM FULL users;                          -- or pg_repack, to apply it to existing pages
```

```
fillfactor guidance:
  100 (default)  append-only / insert-only tables. Correct there.
  90             lightly updated
  85             ⭐ a good default for an update-heavy table
  70             very update-heavy, wide rows
  
Trade-off: lower fillfactor = more pages = more I/O for sequential scans.
Do not lower it on a table you mostly scan.
```

### Measuring your HOT ratio

```sql
SELECT relname,
       n_tup_upd                       AS total_updates,
       n_tup_hot_upd                   AS hot_updates,
       round(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 1) AS hot_pct
FROM pg_stat_user_tables
WHERE n_tup_upd > 1000
ORDER BY n_tup_upd DESC;

--      relname      | total_updates | hot_updates | hot_pct
-- ------------------+---------------+-------------+---------
--  sessions         |      48291043 |    47102882 |    97.5   ✅ excellent
--  users            |       8210398 |      412094 |     5.0   ❌ investigate
--  audit_log        |            12 |           0 |     0.0   (fine — not updated)
```

> **A HOT ratio below ~60% on a frequently-updated table is one of the highest-value findings you can make in a PostgreSQL system.** The fix — drop an unused index on a hot column, or lower `fillfactor` — is usually one statement and can reduce write I/O and bloat by an order of magnitude.

---

## 13. Traced scenario — a page through six updates

Watch one page as the same row is updated six times, with and without HOT.

### Setup

```sql
CREATE TABLE sessions (
    id          uuid PRIMARY KEY,
    tenant_id   uuid NOT NULL,
    status      text NOT NULL,
    heartbeat_at timestamptz NOT NULL
) WITH (fillfactor = 85);

CREATE INDEX ON sessions (tenant_id, status);
-- ⭐ heartbeat_at is NOT indexed → updates to it can be HOT
```

### Without fillfactor (fillfactor = 100) — the bad case

```
Page 0, packed with 40 rows. No free space.

UPDATE sessions SET heartbeat_at = now() WHERE id = 'abc';

  Condition 1 (no indexed column changed):  ✓ satisfied
  Condition 2 (fits on the same page):      ✗ page is FULL

  → NOT a HOT update.
  → New tuple goes on page 1 (or a new page).
  → 2 index entries created (PK + the tenant/status index).
  → Old tuple on page 0 is dead and can only be reclaimed by VACUUM.

After 6 heartbeats for every row on the page:
  Page 0:   40 dead tuples, 0 live      ⭐ the entire page is garbage
  Pages 1-6: the live versions, scattered
  Indexes:  6 × 40 × 2 = 480 dead index entries
```

### With fillfactor = 85 — the good case

```
Page 0, 34 rows (85% full), ~1,200 bytes free.

UPDATE 1:  fits ✓, no indexed column changed ✓  → HOT
  lp 1 (v1, dead, HOT_UPDATED, ctid→lp 35)
  lp 35 (v2, live, HEAP_ONLY_TUPLE)
  ⭐ 0 index entries created

UPDATE 2:  → HOT
  lp 1 → lp 35 → lp 36

UPDATE 3:  page is now getting full. A read triggers HOT PRUNING:
  lp 1  = LP_REDIRECT → lp 37
  lp 35 = LP_UNUSED    ⭐ reclaimed
  lp 36 = LP_UNUSED    ⭐ reclaimed
  lp 37 (v4, live)
  ⭐ Space reclaimed WITHOUT VACUUM. The page can absorb more updates.

UPDATES 4, 5, 6:  continue the cycle — HOT, prune, HOT, prune.

⭐ After 6 heartbeats for every row:
     Page 0:   still ~34 live rows, still on one page
     Indexes:  ZERO new entries. Zero index bloat.
     VACUUM:   has almost nothing to do.
```

**The same workload. Two orders of magnitude difference in write amplification, and one is self-cleaning.** The only difference is one `fillfactor` setting and one absent index.

---

## 14. Bloat: the arithmetic

Bloat is dead tuples and free space that the table is holding but not using. It is not a bug — it is the cost of MVCC — but unbounded bloat is an operational failure.

### Where bloat comes from

```
1. UPDATEs and DELETEs create dead tuples (§11)
2. VACUUM marks the space reusable — it does NOT return it to the OS
3. If the dead-tuple creation rate exceeds the VACUUM rate, the table grows
4. A table NEVER shrinks except via VACUUM FULL, pg_repack, or truncating
   trailing empty pages
```

### The steady-state calculation

```
Table: 10 million rows × 200 bytes = 2 GB
Update rate: 1,000 updates/sec, NOT HOT
Autovacuum runs when dead tuples exceed 20% of the table (the default)

Dead tuples accumulate at 1,000/sec.
20% of 10M = 2,000,000 dead tuples → reached in 2,000 seconds (33 minutes).

Autovacuum starts. Suppose it processes the table in 10 minutes.
During those 10 minutes, another 600,000 dead tuples are created.

⭐ STEADY STATE: the table permanently carries ~2.6M dead tuples
   = 26% bloat = 2.5 GB on disk for 2 GB of data.

Now suppose one long transaction runs for 4 hours (§16):
   Dead tuples for 4 hours = 14,400,000
   ⭐ The table more than DOUBLES: 2 GB → 5 GB.
   And VACUUM, though it runs, can remove none of them.
```

### Why bloat hurts, beyond disk

```
1. Sequential scans read dead tuples and discard them — pure wasted I/O
2. The buffer cache holds dead tuples, evicting useful pages
3. Indexes bloat too, so index scans touch more pages
4. VACUUM itself takes longer, making the problem self-reinforcing
5. Backups are larger and slower
6. Replication ships more WAL
```

**The self-reinforcing property is the dangerous one.** A table that gets 2× bloated makes VACUUM take 2× longer, which allows more bloat to accumulate during the run. Systems can fall off a cliff.

---

## 15. VACUUM: what it actually does, phase by phase

```
PHASE 1 — SCAN THE HEAP
  Read pages (skipping all-visible ones via the visibility map, §23).
  Collect the TIDs of dead tuples into memory.
  ⭐ Limited by maintenance_work_mem. Pre-PG17 this was ~6 bytes per TID, so
     64 MB held ~11 million TIDs. Exceeding it forces MULTIPLE PASSES over
     all indexes — a massive cost. PG17's new TID store is far more compact
     and largely removes this cliff.
  Also: prune HOT chains, set hint bits, freeze eligible tuples (§19).

PHASE 2 — VACUUM THE INDEXES
  For EVERY index on the table, scan it and remove entries pointing at the
  dead TIDs collected in phase 1.
  ⭐ This is usually the most expensive phase, and it is why a table with
     10 indexes is 10× more expensive to vacuum than one with 1.

PHASE 3 — VACUUM THE HEAP
  Now that no index points at them, set the dead line pointers to LP_UNUSED.
  The space is now reusable by future inserts on that page.

PHASE 4 — UPDATE METADATA
  Free Space Map (which pages have room)
  Visibility Map (which pages are all-visible / all-frozen)
  pg_class.relpages, reltuples
  pg_database.datfrozenxid

PHASE 5 — TRUNCATE (optional)
  If pages at the END of the table are entirely empty, return them to the OS.
  ⭐ Requires a brief ACCESS EXCLUSIVE lock. PostgreSQL will give it up if
     anyone is waiting (it checks every 20 ms, and gives up after 5 seconds),
     so this rarely causes an outage — but it is the one moment VACUUM takes
     a strong lock.
```

### The crucial property

> **`VACUUM` returns space to PostgreSQL for reuse. It does NOT return space to the operating system** (except phase 5's trailing pages).

```
A 5 GB bloated table, after a successful VACUUM:
    still 5 GB on disk
    but with lots of internal free space that new rows will occupy

→ df shows no change. This confuses people constantly.
→ To actually shrink it, you need VACUUM FULL or pg_repack (§21).
```

**And that is usually the correct outcome.** A table in steady state will re-use that space. Shrinking it only to re-grow it is churn. Shrink only when the bloat is from a one-off event (a mass delete, a runaway transaction) that will not recur.

### Watching VACUUM run

```sql
SELECT pid, datname, relid::regclass AS table, phase,
       heap_blks_total, heap_blks_scanned, heap_blks_vacuumed,
       index_vacuum_count,
       round(100.0 * heap_blks_scanned / NULLIF(heap_blks_total,0), 1) AS pct
FROM pg_stat_progress_vacuum;

--  phase: 'scanning heap' | 'vacuuming indexes' | 'vacuuming heap' |
--         'cleaning up indexes' | 'truncating heap'
--
-- ⭐ index_vacuum_count > 1 means maintenance_work_mem was exceeded and
--    the indexes are being scanned MULTIPLE TIMES. Raise it.
```

---

## 16. The xmin horizon — what stops VACUUM ⭐

**This is the single most important operational concept in PostgreSQL.**

> **VACUUM can only remove a dead tuple if NO transaction anywhere could still need to see it.**
>
> The boundary is the **xmin horizon**: the oldest `xmin` of any snapshot that is still held anywhere in the system.

If the horizon does not advance, VACUUM runs, does work, consumes I/O — and **removes nothing**. The table grows without bound while your monitoring shows autovacuum running normally.

### The six things that hold the horizon back

```
1. ⭐ LONG-RUNNING TRANSACTIONS
     Any open transaction. In REPEATABLE READ or SERIALIZABLE, the snapshot
     is held for the WHOLE transaction. Even a read-only one. Even `BEGIN;`
     followed by nothing.

2. ⭐ IDLE IN TRANSACTION SESSIONS
     An application that opened a transaction and went to lunch.
     The most common cause in practice.

3. ⭐ REPLICATION SLOTS
     A slot holds catalog_xmin and restart_lsn. An INACTIVE slot (a replica
     that was decommissioned without dropping its slot) holds the horizon
     FOREVER and also accumulates WAL until the disk fills.

4. hot_standby_feedback = on + long queries on a standby
     The standby tells the primary "do not vacuum away rows my queries need".
     Prevents query cancellation on the replica; holds the horizon on the primary.

5. ⭐ PREPARED TRANSACTIONS (two-phase commit)
     A PREPARE TRANSACTION that was never committed or rolled back.
     Survives restarts. Holds the horizon indefinitely. Nearly invisible
     unless you look for it.

6. Long-running queries on the primary
     A single statement in READ COMMITTED still holds a snapshot for its duration.
```

### Finding the horizon — the diagnostic query

Keep this in your runbook.

```sql
-- What is holding the xmin horizon back, right now?
SELECT 'backend'          AS source,
       pid::text          AS id,
       state,
       age(backend_xmin)  AS xmin_age,
       now() - xact_start AS duration,
       left(query, 60)    AS query
FROM pg_stat_activity
WHERE backend_xmin IS NOT NULL

UNION ALL

SELECT 'replication_slot',
       slot_name,
       CASE WHEN active THEN 'active' ELSE '⚠ INACTIVE' END,
       age(xmin),
       NULL,
       'restart_lsn: ' || restart_lsn::text
FROM pg_replication_slots
WHERE xmin IS NOT NULL OR catalog_xmin IS NOT NULL

UNION ALL

SELECT 'prepared_xact',
       gid,
       'prepared',
       age(transaction),
       now() - prepared,
       'database: ' || database
FROM pg_prepared_xacts

ORDER BY xmin_age DESC NULLS LAST;
```

```
     source      |       id        |       state         | xmin_age |  duration
-----------------+-----------------+---------------------+----------+------------
 replication_slot| old_replica_2   | ⚠ INACTIVE          | 48291043 |
 backend         | 88214           | idle in transaction |  2104882 | 04:12:33
 prepared_xact   | trx_9f2a        | prepared            |   910233 | 01:48:02
 backend         | 88901           | active              |     1204 | 00:00:02
```

**Reading this:** the inactive replication slot is holding the horizon 48 million transactions back. Nothing created since then can be vacuumed anywhere in the database. The idle-in-transaction backend and the orphaned prepared transaction are also problems, but the slot is the worst.

### The fixes

```sql
-- 1. Kill a long idle-in-transaction session
SELECT pg_terminate_backend(88214);

-- 2. PREVENT it from happening again — ⭐ set this on every production database
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET statement_timeout = '60s';         -- per role/session as appropriate
SELECT pg_reload_conf();

-- 3. Drop an abandoned replication slot  ⭐ CHECK FIRST that it is truly unused
SELECT pg_drop_replication_slot('old_replica_2');

-- 4. Bound the damage a slot can do (PG13+)
ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';  -- slot is invalidated past this

-- 5. Resolve an orphaned prepared transaction
ROLLBACK PREPARED 'trx_9f2a';
-- And if you do not use 2PC at all:
ALTER SYSTEM SET max_prepared_transactions = 0;
```

> **`idle_in_transaction_session_timeout` is the single highest-value one-line configuration change for most PostgreSQL systems.** It converts an unbounded, invisible bloat problem into a visible application error that someone will fix.

---

## 17. Traced scenario — one idle transaction, 40 GB of bloat

A realistic incident, traced through.

```
09:00  Normal operation.
       orders table: 8 GB, 40 M rows. ~500 updates/sec.
       Autovacuum runs every ~40 minutes, keeps dead tuples around 3%.
       Disk: 200 GB, 90 GB used.

09:15  An analyst opens a BI tool. It issues:
           BEGIN;
           SELECT ... FROM orders WHERE ...;   -- 4 seconds
       ...and then does not COMMIT. The tool holds the connection open,
       idle in transaction. The analyst goes to a meeting.

       ⭐ The snapshot taken at 09:15 is now pinned.

09:15–13:00  Everything LOOKS normal:
       • Queries are fast
       • Autovacuum runs on schedule, logs "vacuuming orders"
       • No errors anywhere
       • ⭐ But every VACUUM removes ZERO tuples created after 09:15

       Dead tuples accumulate at 500/sec:
           1 hour  =  1.8 M dead tuples
           4 hours =  7.2 M dead tuples

13:00  Someone notices disk usage climbing.
       orders table: 8 GB → 19 GB
       n_dead_tup: 7,200,000

       SELECT * FROM pg_stat_user_tables WHERE relname='orders';
       -- last_autovacuum: 12:47   ← it IS running
       -- n_dead_tup: 7200000       ← and removing nothing

13:05  The diagnostic query from §16:

         source  |  id   |       state         | xmin_age | duration
        ---------+-------+---------------------+----------+----------
         backend | 91204 | idle in transaction |  6841022 | 03:50:14

13:06  SELECT pg_terminate_backend(91204);

13:07  Manual VACUUM:  VACUUM (VERBOSE) orders;
       "removed 7203881 row versions in 402219 pages"
       Table is still 19 GB on disk — but now with 11 GB of reusable free space.

13:30  Decision: is 11 GB of free space going to be reused?
       At the normal insert rate, yes, over weeks.
       But this was a one-off event, and the disk is tight.
       → Run pg_repack (online) to reclaim it (§21).

14:00  orders table back to 8.2 GB.

FOLLOW-UP ACTIONS
  ✅ ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
  ✅ Alert on: max(age(backend_xmin)) > 1,000,000
  ✅ Alert on: n_dead_tup / (n_live_tup + n_dead_tup) > 0.25
  ✅ Configure the BI tool to use autocommit for read-only queries
```

**The instructive part:** for nearly four hours, every dashboard was green. Autovacuum was running. Queries were fast. Nothing errored. The only visible symptom was disk growth — and only if someone was watching it.

> **This is why `age(backend_xmin)` belongs on your PostgreSQL dashboard.** It is the leading indicator; disk usage is the lagging one.

---

## 18. Autovacuum tuning: the defaults are wrong for large tables

The defaults were chosen when tables were much smaller. They scale badly.

### The trigger formula

```
VACUUM triggers when:
    n_dead_tup > autovacuum_vacuum_threshold
                 + autovacuum_vacuum_scale_factor × reltuples

Defaults:  threshold = 50,  scale_factor = 0.2  (20%)
```

```
  1,000 rows  →  vacuum at 250 dead tuples      (reasonable)
  1 M rows    →  vacuum at 200,050              (getting large)
  100 M rows  →  vacuum at 20,000,050  ⭐ TWENTY MILLION dead tuples
                                          before vacuum even STARTS
```

**Twenty million dead tuples on a 100M-row table is 20% bloat as a permanent floor**, plus whatever accumulates during the vacuum run itself.

### The throttle — the other half of the problem

Autovacuum deliberately throttles itself to avoid starving the workload:

```
vacuum_cost_page_hit   = 1     (page found in shared_buffers)
vacuum_cost_page_miss  = 2     (page read from disk; was 10 before PG14)
vacuum_cost_page_dirty = 20    (page modified)

autovacuum_vacuum_cost_limit = 200      ⭐ the throttle
autovacuum_vacuum_cost_delay = 2ms      (PG12+; was 20ms before)
```

**Compute the actual throughput:**

```
Worst case, every page dirtied:
    200 cost units / 20 per dirty page = 10 pages per cycle
    10 pages × 8 KB = 80 KB per cycle
    1 cycle per 2 ms → 500 cycles/sec
    ⭐ 40 MB/sec maximum vacuum throughput

A 100 GB table takes 100,000 MB / 40 MB/s = 2,500 seconds ≈ 42 minutes
— if it never sleeps for any other reason, and that is the optimistic case.
```

On modern NVMe capable of gigabytes per second, **40 MB/s is an artificial handbrake**. It made sense on spinning disks in 2005.

### The tuning

```sql
-- ═══ GLOBAL: raise the throttle substantially on modern hardware ═══
ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 2000;   -- 10× → ~400 MB/s
ALTER SYSTEM SET autovacuum_vacuum_cost_delay = '2ms';
ALTER SYSTEM SET autovacuum_max_workers = 6;            -- default 3
ALTER SYSTEM SET autovacuum_naptime = '15s';            -- default 60s
ALTER SYSTEM SET maintenance_work_mem = '1GB';          -- ⭐ avoids multi-pass index vacuum
ALTER SYSTEM SET vacuum_cost_page_miss = 2;             -- SSD-appropriate

-- ⭐ NOTE: autovacuum_max_workers share the cost limit between them.
--    6 workers with cost_limit 2000 each get ~333 effective — unless you set
--    autovacuum_vacuum_cost_limit per table. Budget accordingly.

-- ═══ PER LARGE TABLE: use an absolute threshold, not a percentage ═══
ALTER TABLE orders SET (
    autovacuum_vacuum_scale_factor  = 0.0,        -- ⭐ disable the percentage
    autovacuum_vacuum_threshold     = 50000,      -- ⭐ vacuum at 50k dead tuples
    autovacuum_analyze_scale_factor = 0.0,
    autovacuum_analyze_threshold    = 25000,
    autovacuum_vacuum_cost_limit    = 4000,       -- this table gets more budget
    fillfactor                      = 85          -- enable HOT (§12)
);

-- ═══ INSERT-ONLY tables (PG13+) ═══
-- These never trigger the dead-tuple threshold, so they were never vacuumed,
-- so they were never frozen, so they eventually hit wraparound (§19).
ALTER TABLE events SET (
    autovacuum_vacuum_insert_threshold    = 100000,
    autovacuum_vacuum_insert_scale_factor = 0.0
);
```

> **Setting `scale_factor = 0` and using an absolute threshold is the standard tuning for any table over ~10 million rows.** It converts "vacuum when 20% is garbage" into "vacuum every N modifications", which is what you actually want.

### Verifying it works

```sql
SELECT relname,
       n_live_tup, n_dead_tup,
       round(100.0*n_dead_tup/NULLIF(n_live_tup+n_dead_tup,0),1) AS dead_pct,
       last_autovacuum,
       autovacuum_count,
       now() - last_autovacuum AS since_last
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY n_dead_tup DESC
LIMIT 20;
```

Healthy: `dead_pct` under ~10%, `last_autovacuum` recent, `autovacuum_count` climbing steadily.

---

## 19. Freezing and transaction ID wraparound

The other job VACUUM does, and the one that can take your database offline.

### The problem restated

From §5: transaction IDs are 32 bits and comparison is circular. A tuple whose `xmin` is more than ~2 billion transactions in the past would appear to be in the **future**, and become invisible. The data would still be on disk and unreadable.

### The solution: freezing

```
FREEZING marks a tuple as "unconditionally visible, forever".

Modern PostgreSQL sets HEAP_XMIN_FROZEN (both XMIN_COMMITTED and XMIN_INVALID
bits) in the infomask rather than physically overwriting xmin with 2.
The visibility check short-circuits: frozen → visible. No comparison needed.
→ Immune to wraparound.
```

### The thresholds

```
vacuum_freeze_min_age        = 50,000,000    freeze tuples older than this
                                             during any vacuum of the page
vacuum_freeze_table_age      = 150,000,000   ⭐ escalate to an AGGRESSIVE vacuum
                                             (scan the WHOLE table, not just
                                             pages the visibility map says
                                             are unfrozen)
autovacuum_freeze_max_age    = 200,000,000   ⭐ force an anti-wraparound autovacuum
                                             EVEN IF autovacuum is disabled
```

### Monitoring — put this on your dashboard

```sql
SELECT datname,
       age(datfrozenxid) AS xid_age,
       round(100.0 * age(datfrozenxid) / 2000000000, 1) AS pct_to_wraparound
FROM pg_database
ORDER BY xid_age DESC;

--   datname  |  xid_age  | pct_to_wraparound
-- -----------+-----------+-------------------
--  production| 187420983 |               9.4     ✅ healthy

-- Per table — find the one that is falling behind
SELECT c.relname,
       age(c.relfrozenxid) AS xid_age,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
       s.last_autovacuum
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r','m','t') AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY age(c.relfrozenxid) DESC
LIMIT 20;
```

**Alert thresholds:**

```
age(datfrozenxid) > 500,000,000    → WARNING: investigate
age(datfrozenxid) > 1,000,000,000  → CRITICAL: act now
age(datfrozenxid) > 1,500,000,000  → EMERGENCY
```

### Why a table falls behind

```
1. An insert-only table that never triggers dead-tuple-based autovacuum
   (fixed by autovacuum_vacuum_insert_threshold, PG13+)
2. ⭐ A long-held xmin horizon (§16) — the SAME root cause as bloat.
   VACUUM cannot freeze tuples newer than the horizon.
3. Autovacuum throttled too aggressively to finish before the next threshold
4. Autovacuum disabled on a table ("it was causing load")
5. A very large table that simply takes longer than the freeze interval
6. Repeated cancellation of anti-wraparound vacuums by DDL taking conflicting locks
```

> **Point 2 deserves emphasis:** bloat and wraparound risk have the **same root cause**. An inactive replication slot or a forgotten idle transaction causes both simultaneously. Fixing the horizon fixes both.

---

## 20. The wraparound emergency, step by step

What actually happens as you approach the limit.

```
age(datfrozenxid) = 200,000,000
  → Anti-wraparound autovacuum launches automatically, even on tables where
    autovacuum is disabled. It is NOT cancelled by ordinary lock conflicts
    the way normal autovacuum is.

age = 2,000,000,000 − 40,000,000 = 1,960,000,000
  → WARNING in the log on every transaction:
    "database 'production' must be vacuumed within 40000000 transactions"
    "To avoid a database shutdown, execute a database-wide VACUUM in that database."

age = 2,000,000,000 − 3,000,000 = 1,997,000,000
  → ⭐ PostgreSQL REFUSES TO ASSIGN NEW TRANSACTION IDs:
    ERROR: database is not accepting commands to avoid wraparound data loss
           in database "production"
    HINT:  Stop the postmaster and vacuum that database in single-user mode.

  → NO WRITES ARE POSSIBLE. Reads still work. Your application is down.
```

### Recovery

```bash
# ═══ FIRST: find out WHY it fell behind. Fix the cause, or it recurs. ═══
psql -c "SELECT * FROM pg_replication_slots WHERE NOT active;"
psql -c "SELECT * FROM pg_prepared_xacts;"
psql -c "SELECT pid, state, age(backend_xmin), now()-xact_start
         FROM pg_stat_activity WHERE backend_xmin IS NOT NULL
         ORDER BY age(backend_xmin) DESC;"

# ═══ THEN vacuum. On modern PostgreSQL you can usually do this ONLINE ═══
# Read-only queries still work, so the database is not fully down.
psql -c "SET vacuum_cost_delay = 0;"     # remove the throttle entirely
psql -c "VACUUM (FREEZE, VERBOSE, PARALLEL 4) most_behind_table;"

# Work through tables in order of age(relfrozenxid), worst first.

# ═══ If the instance truly will not accept commands: single-user mode ═══
#   (Older versions, or if the above fails.)
pg_ctl stop -D $PGDATA
postgres --single -D $PGDATA production
# then at the backend> prompt:
backend> VACUUM FREEZE;
backend> <Ctrl-D>
pg_ctl start -D $PGDATA
```

### Prevention

```sql
-- 1. Monitor and alert (§19)
-- 2. Ensure insert-only tables are vacuumed (PG13+)
ALTER TABLE events SET (autovacuum_vacuum_insert_threshold = 100000);
-- 3. Never disable autovacuum on a table. If it causes load, TUNE it.
-- 4. Bound the xmin horizon:
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';
-- 5. Alert on inactive replication slots:
--    SELECT count(*) FROM pg_replication_slots WHERE NOT active;  → alert if > 0
-- 6. For bulk loads, freeze on the way in:
--    BEGIN; TRUNCATE t; COPY t FROM ... WITH (FREEZE); COMMIT;
```

> **Wraparound shutdown is entirely preventable and entirely catastrophic.** It has taken down well-known services. The monitoring query is four lines; the alert threshold is obvious; and almost nobody has it configured until after the first incident.

---

## 21. VACUUM FULL, pg_repack, and index bloat

### VACUUM FULL

```sql
VACUUM FULL orders;
```

```
What it does: rewrites the ENTIRE table into a new file, compacted, then
              swaps and drops the old one. Rebuilds all indexes.

⭐ Takes an ACCESS EXCLUSIVE lock for the whole duration.
   No reads. No writes. Nothing.
⭐ Needs up to 2× the table size in free disk space.
⭐ On a 100 GB table this is hours of complete unavailability.

→ Effectively NEVER acceptable on a production OLTP table.
```

### pg_repack — the online alternative

```bash
pg_repack -d production -t orders --jobs 4
```

```
How it works:
  1. Create a temporary copy of the table
  2. Install a trigger capturing all changes to the original
  3. Copy the data across
  4. Apply the captured changes
  5. ⭐ Brief ACCESS EXCLUSIVE lock (seconds) to swap the tables
  6. Drop the original

Requirements: a PRIMARY KEY or a unique NOT NULL index; ~2× disk space.
Caveat: the brief lock at the end can still queue behind a long query —
        run it when the system is quiet, with a lock_timeout.
```

### Index bloat and REINDEX CONCURRENTLY

Indexes bloat independently of tables and are frequently the larger problem.

```sql
-- PostgreSQL 12+ — rebuild an index without blocking writes
REINDEX INDEX CONCURRENTLY idx_orders_customer;
REINDEX TABLE CONCURRENTLY orders;         -- all indexes on the table

-- ⚠ If it fails partway, it leaves an invalid index named *_ccnew.
--   Find and drop them:
SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
```

**Why B-tree indexes bloat:** deleting a key leaves the slot empty. The space is reusable only by keys that belong in that same page range. On a monotonically increasing key (a timestamp, a serial ID) where old rows are deleted, the left-hand side of the index empties out and is **never reused**, because all new keys go to the right-hand side.

```
⭐ This is why "insert rows, delete old rows after 90 days" on a
   timestamp-indexed table produces an index that grows forever while the
   table stays constant. It is one of the most common index-bloat patterns.

The better fix is usually PARTITIONING (Chapter 09 §9.10): DROP the old
partition, and its index disappears with it. Instantly. No bloat, no REINDEX.
```

---

## 22. TOAST — oversized attributes

A tuple cannot span pages. So what happens to a 10 MB `jsonb` value?

**TOAST** (The Oversized-Attribute Storage Technique).

```
TOAST_TUPLE_THRESHOLD ≈ 2000 bytes (about ¼ of a page)

If a row exceeds it, PostgreSQL repeatedly takes the LARGEST toastable
attribute and compresses and/or moves it out of line, until the row fits.
```

### The four storage strategies

```sql
ALTER TABLE t ALTER COLUMN c SET STORAGE <strategy>;
```

| Strategy | Compress? | Out of line? | Use for |
|----------|-----------|--------------|---------|
| `PLAIN` | No | No | Fixed-size types; forbidden for large values |
| **`EXTENDED`** | **Yes** | **Yes** | **The default for text/jsonb/bytea** |
| `EXTERNAL` | No | Yes | ⭐ When you do `substring()` on large values — uncompressed values support partial fetch |
| `MAIN` | Yes | Only as a last resort | Keep it in the main table if at all possible |

### How it is stored

```
Main table row:           ... [TOAST pointer, 18 bytes] ...
                                    │
                                    ▼
pg_toast.pg_toast_16385:   chunk_id | chunk_seq | chunk_data
                           ---------+-----------+------------
                              9214  |         0 | <~2000 bytes>
                              9214  |         1 | <~2000 bytes>
                              9214  |         2 | <~2000 bytes>
                              ...

A 10 MB value = ~5,000 chunks, retrieved via the TOAST table's index.
Maximum field size: 1 GB.
```

### The performance facts worth knowing

**1. A TOASTed column is not read unless you select it.**

```sql
-- ✅ Does NOT touch the TOAST table at all
SELECT id, created_at FROM documents WHERE id = 42;

-- ❌ Fetches and decompresses 10 MB
SELECT * FROM documents WHERE id = 42;
```

**This is a concrete, large reason `SELECT *` is harmful** beyond the usual arguments. On a table with large TOASTed columns, `SELECT *` can be 100× slower than selecting the columns you need.

**2. Updating a row does not rewrite its TOAST** — if the toasted column itself is unchanged, the new tuple simply copies the 18-byte pointer. The TOAST chunks are shared.

**3. TOAST tables need vacuuming too**, and they are easy to overlook:

```sql
SELECT c.relname AS table_name,
       t.relname AS toast_name,
       pg_size_pretty(pg_relation_size(c.oid))  AS main_size,
       pg_size_pretty(pg_relation_size(t.oid))  AS toast_size,
       s.n_dead_tup AS toast_dead_tuples
FROM pg_class c
JOIN pg_class t ON t.oid = c.reltoastrelid
LEFT JOIN pg_stat_all_tables s ON s.relid = t.oid
WHERE c.relkind = 'r' AND c.reltoastrelid != 0
ORDER BY pg_relation_size(t.oid) DESC
LIMIT 10;
```

**4. Compression method matters (PG14+):**

```sql
-- lz4 is much faster to compress AND decompress than the default pglz,
-- at a slightly lower ratio. For most workloads it is a clear win.
ALTER SYSTEM SET default_toast_compression = 'lz4';
ALTER TABLE documents ALTER COLUMN body SET COMPRESSION lz4;
```

---

## 23. The visibility map and index-only scans

A tiny structure with a large performance impact.

```
For every heap page, the visibility map stores TWO BITS:

    ALL_VISIBLE   every tuple on this page is visible to ALL current
                  transactions (nothing dead, nothing in-flight)
    ALL_FROZEN    every tuple on this page is frozen

Size: 2 bits per 8 KB page → a 100 GB table has a ~3 MB visibility map.
      It stays in memory easily.
```

### Use 1 — index-only scans

An index entry does not carry visibility information (it has no `xmin`/`xmax`). So normally, after finding a matching index entry, PostgreSQL **must** fetch the heap tuple just to check whether it is visible.

```
⭐ UNLESS the visibility map says the heap page is ALL_VISIBLE.
   Then every tuple on it is visible by definition, and the heap fetch
   can be SKIPPED entirely.
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT tenant_id, created_at FROM sessions WHERE tenant_id = '...';

-- Index Only Scan using idx_sessions_tenant on sessions
--   Heap Fetches: 0            ⭐ PERFECT — the visibility map is current
--   Buffers: shared hit=12

-- versus, on a table that has not been vacuumed recently:
-- Index Only Scan using idx_sessions_tenant on sessions
--   Heap Fetches: 48213        ⭐ It is an "index only" scan doing 48,213
--   Buffers: shared hit=48891     heap fetches. Barely better than a normal
--                                 index scan.
```

> **`Heap Fetches: 0` is the target, and it is achieved by VACUUM.** If a query plan says "Index Only Scan" but reports large `Heap Fetches`, the answer is almost always "vacuum this table more often" — not "rewrite the query".

### Use 2 — skipping pages during VACUUM

```
VACUUM skips ALL_VISIBLE pages entirely (nothing to clean).
Anti-wraparound VACUUM skips ALL_FROZEN pages entirely (nothing to freeze).

⭐ This is what makes vacuuming a 2 TB mostly-static table feasible:
   it only reads the pages that have changed.
```

Without the all-frozen bit (added in 9.6), every anti-wraparound vacuum had to read the entire table every time. That single optimisation is why very large PostgreSQL tables became practical.

---

## 24. Measuring bloat accurately

### Fast estimate (safe on production)

```sql
-- pgstattuple's approximate variant — samples rather than scanning
CREATE EXTENSION IF NOT EXISTS pgstattuple;

SELECT * FROM pgstattuple_approx('orders');
--  table_len | scanned_percent | approx_free_percent | dead_tuple_percent
-- -----------+-----------------+---------------------+--------------------
--  20401094656|            2.31 |               54.12 |              11.30
--
-- ⭐ 54% free + 11% dead = this table is ~65% air.
```

### Exact measurement (scans the whole table — off-hours only)

```sql
SELECT * FROM pgstattuple('orders');
--  table_len | tuple_count | tuple_len | tuple_percent | dead_tuple_count |
--            |             |           |               | dead_tuple_len   | free_space
```

### Index bloat

```sql
CREATE EXTENSION IF NOT EXISTS pgstattuple;

SELECT indexrelname,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       (pgstatindex(indexrelid)).avg_leaf_density,
       (pgstatindex(indexrelid)).leaf_fragmentation
FROM pg_stat_user_indexes
WHERE pg_relation_size(indexrelid) > 100*1024*1024
ORDER BY pg_relation_size(indexrelid) DESC;

-- avg_leaf_density: ⭐ healthy is ~90% for a freshly built index.
--                      Below 60% → strong REINDEX candidate.
```

### The quick dashboard query

```sql
SELECT schemaname, relname,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       n_live_tup, n_dead_tup,
       round(100.0*n_dead_tup/NULLIF(n_live_tup+n_dead_tup,0),1) AS dead_pct,
       round(100.0*n_tup_hot_upd/NULLIF(n_tup_upd,0),1) AS hot_pct,
       last_autovacuum
FROM pg_stat_user_tables
WHERE n_live_tup > 10000
ORDER BY n_dead_tup DESC
LIMIT 20;
```

---

## 25. PostgreSQL MVCC vs Oracle, InnoDB and SQL Server

| | **PostgreSQL** | **Oracle / InnoDB** | **SQL Server (RCSI)** |
|---|---|---|---|
| Old versions live | **In the table** | In UNDO/rollback segments | In tempdb's version store |
| Reads need reconstruction | **No** — versions are right there | **Yes** — walk the undo chain | Yes — walk the version chain |
| Table grows on update | **Yes** | No (undo grows instead) | No (tempdb grows) |
| Rollback cost | **Free** (just mark dead) | **Expensive** (apply undo) | Moderate |
| "Snapshot too old" | **Impossible** | **ORA-01555 / MySQL undo too old** | tempdb full errors |
| Cleanup mechanism | **VACUUM** | Automatic undo retention | tempdb version store cleanup |
| Long readers cause | Bloat | Undo exhaustion → query errors | tempdb growth |
| UPDATE touches indexes | **Yes, unless HOT** | Only changed indexes | Only changed indexes |

### The honest assessment

**PostgreSQL's design is better for:**
- Read-heavy workloads with long analytical queries (no reconstruction cost, no "snapshot too old")
- Workloads with frequent rollbacks
- Predictable read latency

**Oracle/InnoDB's design is better for:**
- Update-heavy workloads on wide tables (the table stays compact)
- Systems where you cannot afford operational attention to VACUUM

**But note the symmetry:** a long-running query in Oracle does not cause bloat — it causes **ORA-01555 "snapshot too old"**, killing the query. PostgreSQL's equivalent is bloat. **Both designs punish long-running transactions; they just punish differently.** PostgreSQL's punishment is deferred and silent; Oracle's is immediate and loud.

> Which you prefer is a genuine architectural preference, not a matter of one being correct. What matters is knowing which one you have, and operating accordingly.

**Where the mechanism leaks into schema design:** in PostgreSQL, *a wide table with many indexes and a frequently-updated column is a specifically bad combination*, in a way it is not in InnoDB. That is an actionable design rule you would not derive without understanding MVCC.

---

## 26. The tuning that actually matters

Ranked by impact, for a typical OLTP system.

```sql
-- ═══ 1. BOUND THE XMIN HORIZON — the single highest-value change ═══
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET statement_timeout = '60s';         -- consider per-role
ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';
ALTER SYSTEM SET max_prepared_transactions = 0;     -- if you do not use 2PC

-- ═══ 2. MAKE AUTOVACUUM KEEP UP ═══
ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 2000;
ALTER SYSTEM SET autovacuum_max_workers = 6;
ALTER SYSTEM SET autovacuum_naptime = '15s';
ALTER SYSTEM SET maintenance_work_mem = '1GB';
ALTER SYSTEM SET vacuum_cost_page_miss = 2;

-- ═══ 3. PER-TABLE: absolute thresholds on large tables ═══
ALTER TABLE big_table SET (
    autovacuum_vacuum_scale_factor = 0.0,
    autovacuum_vacuum_threshold    = 50000,
    autovacuum_analyze_scale_factor = 0.0,
    autovacuum_analyze_threshold   = 25000
);

-- ═══ 4. ENABLE HOT UPDATES on update-heavy tables ═══
ALTER TABLE sessions SET (fillfactor = 85);
--   AND drop indexes on frequently-updated columns:
--   SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE idx_scan < 50;

-- ═══ 5. INSERT-ONLY TABLES still need vacuuming (PG13+) ═══
ALTER TABLE events SET (autovacuum_vacuum_insert_threshold = 100000);

-- ═══ 6. Better compression (PG14+) ═══
ALTER SYSTEM SET default_toast_compression = 'lz4';

-- ═══ 7. Observability ═══
ALTER SYSTEM SET log_autovacuum_min_duration = '1s';   -- log slow vacuums
ALTER SYSTEM SET track_io_timing = on;
SELECT pg_reload_conf();
```

### The four alerts

```promql
# 1. The xmin horizon is stuck  ⭐ the leading indicator for everything
max_over_time(pg_stat_activity_max_tx_duration[5m]) > 3600
# or, from a custom query: max(age(backend_xmin)) > 1000000

# 2. Bloat
pg_stat_user_tables_n_dead_tup / (pg_stat_user_tables_n_live_tup + 1) > 0.25

# 3. Wraparound risk
pg_database_frozen_xid_age > 1000000000

# 4. Inactive replication slots
pg_replication_slots_active == 0
```

---

## 27. What an architect takes from this

**1. Every PostgreSQL operational problem traces back to one design decision.** Old row versions live in the table. Bloat, VACUUM, wraparound and the update cost all follow from that. Knowing this lets you predict behaviour rather than memorise symptoms.

**2. The xmin horizon is the master variable.** A long transaction, an idle-in-transaction session, an inactive replication slot, or an orphaned prepared transaction simultaneously causes bloat *and* wraparound risk *and* poor index-only scan performance. One diagnostic query (§16) covers all three. Put it in your runbook.

**3. `idle_in_transaction_session_timeout` is the highest-value one-line change** you can make to a production PostgreSQL system. It converts an invisible, unbounded problem into a visible application error.

**4. HOT updates are a schema design decision, not a database setting.** `fillfactor` plus "do not index frequently-updated columns" can reduce write amplification by an order of magnitude. The HOT-ratio query (§12) is a five-minute audit with a large payoff.

**5. Autovacuum's defaults assume 2005 hardware and small tables.** `scale_factor = 0` with an absolute threshold on any table over ~10M rows, and a cost limit an order of magnitude higher on SSDs.

**6. `SELECT *` is expensive in a way most people do not know:** it forces TOAST fetches and decompression for large columns that the query did not need.

**7. Index bloat on a time-ordered key is unfixable by REINDEX alone** — it recurs. Partitioning and `DROP PARTITION` is the structural answer.

**8. Column order affects table size by 10–20%** through alignment padding, costs nothing, and is invisible to queries.

**9. Wraparound shutdown is preventable with four lines of monitoring** and has taken down well-known services that did not have them.

**10. This is the mechanism behind Chapter 09's rules.** "Keep transactions short", "no I/O inside a transaction", "beware long-running queries" are not style advice — they are direct consequences of the xmin horizon. Now you can explain *why* to a sceptical colleague, which is how those rules actually get followed.

---

## Exercises

1. Compute the total per-row overhead for a table with 12 columns, 3 of which are nullable. How many rows fit on a page if the data is 80 bytes?
2. Reorder the columns of a real table in your system to minimise alignment padding. Measure the size difference on a copy with 1M rows.
3. Given a tuple with `t_xmin=900, t_xmax=950` and a snapshot `xmin=920, xmax=960, xip={930, 950}`, is the tuple visible? Work through §7's algorithm line by line.
4. Explain why a rolled-back `DELETE` requires no cleanup in PostgreSQL but does in Oracle.
5. Run a bulk `INSERT`, then `EXPLAIN (ANALYZE, BUFFERS) SELECT count(*)` twice. Explain the `dirtied` count difference.
6. Take a table in your system with `n_tup_upd > 100000`. Compute its HOT ratio. If it is below 60%, find out why and fix it.
7. Set `fillfactor = 100` on a test table, run 10,000 updates to a non-indexed column, and measure table size. Repeat with `fillfactor = 85`. Explain the difference.
8. Open a `REPEATABLE READ` transaction and leave it idle. In another session, generate 100,000 dead tuples and run `VACUUM VERBOSE`. Explain the output.
9. Write the alert rule for the xmin horizon, and decide the threshold for your system. Justify the number.
10. Compute the maximum autovacuum throughput for your current settings. How long would it take to vacuum your largest table?
11. Find a table in your system where `Index Only Scan` reports non-zero `Heap Fetches`. Fix it and measure the improvement.
12. Your largest index is on `created_at`, and you delete rows older than 90 days. Explain why the index grows forever and design the fix.
13. A table has 65% bloat from a one-off incident. Argue for or against running `pg_repack`, given your disk headroom and traffic pattern.
14. Explain to a colleague, in four sentences, why "keep transactions short" is a correctness-adjacent rule in PostgreSQL and not merely a performance tip.

---

**Next in this series:** Deep Dive 05 — B-trees, Indexes and Access Methods

**Back to:** [Deep Dives](README.md) · [Chapter 09](../09-database-architecture.md) · [The Map](../README.md)
