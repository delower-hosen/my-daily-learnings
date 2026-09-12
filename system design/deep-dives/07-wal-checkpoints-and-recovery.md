# Deep Dive 07 — Write-Ahead Logging, Checkpoints and Recovery

**Prerequisite:** [Chapter 09 §9.8](../09-database-architecture.md) · [Deep Dive 04](04-postgresql-mvcc-and-storage.md)

**What the map said:** *"Write the change to a log before changing the data pages. Sequential WAL writes are fast; random data-page writes are slow. The WAL also enables replication, PITR and CDC."*

**What this deep dive does:** opens a WAL record, explains LSNs and how to read them, walks the exact write path from a dirty buffer to a durable commit, explains torn pages and why full-page writes cost you 40× WAL after a checkpoint, shows why the default `max_wal_size` is wrong and how to tune it from measurements, walks crash recovery step by step and explains why PostgreSQL needs no UNDO phase, traces a point-in-time recovery including the timeline problem that catches everyone, and takes apart streaming and logical replication including the replication slot that fills your disk.

---

## Contents

```
1.  The problem WAL solves
2.  The WAL record, byte by byte
3.  LSNs: reading positions in the log
4.  The write path, step by step
5.  The WAL-before-data rule, enforced
6.  Torn pages and full-page writes ⭐
7.  The full-page-write storm, quantified
8.  wal_compression
9.  WAL segments: files, naming, recycling
10. Checkpoints: the phases
11. ⭐ Checkpoint tuning: the default is wrong
12. Traced scenario — a checkpoint storm
13. synchronous_commit: all five levels ⭐
14. Group commit
15. Crash recovery, step by step
16. ⭐ Why PostgreSQL needs no UNDO phase
17. Base backups: what pg_basebackup actually does
18. Point-in-time recovery, traced
19. ⭐ Timelines — the concept that catches everyone
20. pg_rewind
21. Streaming replication: walsender and walreceiver
22. Replication slots and the disk-full incident
23. Synchronous replication topologies
24. Logical decoding: how CDC really works
25. REPLICA IDENTITY — the setting that breaks Debezium
26. Monitoring WAL
27. The tuning summary
28. What an architect takes from this
```

---

## 1. The problem WAL solves

```
A transaction modifies three rows on three different pages, then commits.

NAÏVE DURABILITY: write all three pages to disk before acknowledging.
    3 random 8 KB writes + fsync, scattered across a 500 GB file.
    ⭐ ~3 random writes per commit. At 1,000 commits/sec that is
       3,000 random IOPS just for durability.

AND IT IS NOT EVEN CORRECT: if the machine dies after writing page 1
    and page 2 but not page 3, the database is in a state that never
    existed. There is no record of what was supposed to happen.
```

**Write-Ahead Logging inverts this.**

```
1. Append a small record describing the change to a SEQUENTIAL log
2. fsync THAT
3. Acknowledge the commit                     ⭐ durability achieved HERE
4. Write the actual data pages LATER, lazily, in bulk
```

```
⭐ 1 sequential write per commit instead of N random ones.
   And the sequential writes from many concurrent commits COMBINE
   into a single fsync (§14).

On NVMe: ~1,000 random 8 KB writes/sec per commit → ~50,000 commits/sec
         with sequential WAL and group commit.
```

**The two properties that make it work:**

1. **Sequential writes are dramatically cheaper than random ones** — even on SSD, where the difference is 5–20× rather than 100×, and on the write path specifically because the drive can coalesce them.
2. **The log is the authoritative record of intent.** If we crash after step 2, recovery replays the log and the change happens. If we crash before step 2, the transaction never happened. There is no in-between.

> **This is the same "make the intermediate state correct but slower" principle** as the B-link split ordering (Deep Dive 05 §8) and the Outbox pattern (Chapter 06). Order your writes so every crash point leaves a recoverable state.

---

## 2. The WAL record, byte by byte

```c
typedef struct XLogRecord {
    uint32     xl_tot_len;    /* 4 B — total length of this record */
    TransactionId xl_xid;     /* 4 B — the transaction that made the change */
    XLogRecPtr xl_prev;       /* 8 B — ⭐ LSN of the PREVIOUS record.
                                      Makes the log a backwards-linked chain,
                                      so recovery can detect a partial write. */
    uint8      xl_info;       /* 1 B — record-type flags for the rmgr */
    RmgrId     xl_rmid;       /* 1 B — ⭐ which RESOURCE MANAGER owns this */
    /* 2 bytes padding */
    pg_crc32c  xl_crc;        /* 4 B — ⭐ CRC32C over the whole record */
} XLogRecord;                 /* 24 bytes header */

/* followed by: block references (which pages this touches), then the data */
```

### Resource managers

The `xl_rmid` field routes the record to the code that knows how to replay it. This is the extensibility mechanism that lets every access method log its own operations.

```
RM_XLOG_ID          checkpoints, parameter changes, switch-segment
RM_XACT_ID          COMMIT, ABORT, PREPARE
RM_HEAP_ID          INSERT, DELETE, UPDATE, LOCK
RM_HEAP2_ID         multi-insert, freeze, visibility-map updates, pruning
RM_BTREE_ID         B-tree insert, split, delete, page reuse
RM_GIN_ID  RM_GIST_ID  RM_SPGIST_ID  RM_BRIN_ID
RM_CLOG_ID          commit-log page extension
RM_MULTIXACT_ID
RM_STANDBY_ID       ⭐ standby-specific: AccessExclusiveLocks, running-xacts
RM_LOGICALMSG_ID    logical decoding messages
RM_GENERIC_ID       full-page images for extensions
```

### Inspecting real WAL

```bash
# pg_waldump decodes the WAL into human-readable records
pg_waldump -p /var/lib/postgresql/16/main/pg_wal 000000010000002A000000B3 | head -20
```

```
rmgr: Heap  len (rec/tot): 54/54,   tx: 847291, lsn: 2A/B3000028,
      prev 2A/B3000000, desc: INSERT off 12 flags 0x00, blkref #0: rel 1663/16385/16402 blk 4821

rmgr: Btree len (rec/tot): 64/64,   tx: 847291, lsn: 2A/B3000060,
      prev 2A/B3000028, desc: INSERT_LEAF off 87, blkref #0: rel 1663/16385/16419 blk 1204

rmgr: Heap  len (rec/tot): 80/8256, tx: 847292, lsn: 2A/B3000120,
      prev 2A/B3000060, desc: UPDATE off 4 xmax 847292 flags 0x10,
      blkref #0: rel 1663/16385/16402 blk 991 FPW        ⭐⭐ FPW = FULL PAGE WRITE
                          ^^^^^^^^^^                        80 bytes of record,
                          rec/tot shows 80 vs 8256          8,256 bytes on disk

rmgr: Transaction len (rec/tot): 34/34, tx: 847291, lsn: 2A/B3002140,
      prev 2A/B3000120, desc: COMMIT 2026-09-12 14:22:03.481 UTC
```

**Read the third record carefully.** An 80-byte logical change produced 8,256 bytes of WAL because it was the first modification of that page since the last checkpoint, so the entire 8 KB page was written. That is §6.

```bash
# ⭐ The single most useful pg_waldump invocation: where is my WAL going?
pg_waldump --stats=record -p pg_wal 000000010000002A000000B3 000000010000002A000000C0
```

```
Type                    N      (%)   Record size  (%)   FPI size  (%)  Combined (%)
----                    -      ---   -----------  ---   --------  ---  -------- ---
XLOG/FPI_FOR_HINT   12849  (18.2)        628,     0.9   105,246,72 (61.4)  ⭐ hint bits!
Heap/INSERT         28471  (40.3)     1,542,3    22.1        0     0.0
Heap/UPDATE          9214  (13.0)       912,8    13.1   18,420,48 (10.7)
Btree/INSERT_LEAF   19882  (28.1)     1,272,4    18.2   42,918,40 (25.0)
```

**That output tells you exactly where WAL volume comes from**, and it frequently contains a surprise — here, 61% of WAL bytes are full-page images caused by *hint bit* updates (Deep Dive 04 §9), which most people do not know generate WAL at all.

---

## 3. LSNs: reading positions in the log

```
LSN = Log Sequence Number = a 64-bit BYTE OFFSET into the infinite WAL stream.

Printed as two 32-bit halves in hex:    2A/B3000028
                                        ^^ ^^^^^^^^
                                        high   low
```

```sql
SELECT pg_current_wal_lsn()      AS current_write_position,
       pg_current_wal_insert_lsn() AS current_insert_position,
       pg_current_wal_flush_lsn()  AS flushed_to_disk;
--  current_write_position | current_insert_position | flushed_to_disk
-- ------------------------+-------------------------+-----------------
--  2A/B3000028            | 2A/B3000180             | 2A/B3000028
--                                     ↑ ahead: records inserted into the
--                                       WAL buffer but not yet written

-- ⭐ The arithmetic function you will use constantly
SELECT pg_size_pretty(pg_wal_lsn_diff('2A/B3000028', '2A/B0000000'));
--  48 MB          ← how much WAL between these two positions

-- Which file contains a given LSN?
SELECT pg_walfile_name('2A/B3000028');
--  000000010000002A000000B3
```

**LSNs are the universal currency of PostgreSQL replication and recovery.** Every one of these is an LSN comparison:

```
Replication lag        = sent_lsn − replay_lsn
Replication slot size  = current_lsn − restart_lsn
Recovery progress      = target_lsn − replayed_lsn
Page freshness         = page.pd_lsn vs flushed WAL LSN   (§5)
Backup consistency     = backup_end_lsn
```

---

## 4. The write path, step by step

```
Transaction: UPDATE accounts SET balance = 900 WHERE id = 1;

┌──────────────────────────────────────────────────────────────────────┐
│ STEP 1 — Read the page into shared_buffers (if not there)            │
│                                                                      │
│ STEP 2 — Pin and lock the buffer, modify the tuple in MEMORY         │
│          (Deep Dive 04 §11: new version inserted, old xmax set)      │
│          The buffer is now DIRTY.                                    │
│                                                                      │
│ STEP 3 — ⭐ Build the WAL record and copy it into the WAL BUFFERS    │
│          (a shared-memory ring, wal_buffers, default = 1/32 of        │
│           shared_buffers, capped at 16 MB)                            │
│          Set the page's pd_lsn = this record's end LSN.               │
│                                                                      │
│ STEP 4 — Release the buffer lock. Other backends can now read it.    │
│          ⭐ NOTHING has touched the disk yet.                         │
│                                                                      │
│ STEP 5 — COMMIT:                                                      │
│          a) write a COMMIT record into the WAL buffers                │
│          b) ⭐ XLogFlush(commit_lsn):                                 │
│                • write() WAL buffers up to commit_lsn to the file     │
│                • ⭐ fsync() the WAL file                              │
│          c) mark the transaction COMMITTED in pg_xact (clog)          │
│                                                                      │
│ STEP 6 — ⭐ RETURN SUCCESS TO THE CLIENT.                            │
│          Durability is achieved HERE — by the WAL fsync, not by       │
│          anything touching the data file.                             │
│                                                                      │
│ STEP 7 — LATER (seconds to minutes): the checkpointer or the          │
│          background writer writes the dirty data page to the heap     │
│          file. Possibly after hundreds of further modifications.      │
└──────────────────────────────────────────────────────────────────────┘
```

### The consequences worth internalising

```
⭐ The data file can be arbitrarily STALE. A page on disk may be minutes
   behind the committed state. That is normal and correct.

⭐ Commit latency = WAL fsync latency. Nothing else.
   This is why Deep Dive 01 §12's "wal_fsync_duration p99 < 10 ms" is
   the master metric — it IS your write latency.

⭐ A single dirty page modified 500 times between checkpoints is written
   to the data file ONCE. WAL absorbs the churn; the heap write is batched.
```

### Who writes the dirty pages

```
CHECKPOINTER      writes ALL dirty pages at checkpoint time (§10)
BACKGROUND WRITER writes SOME dirty pages continuously, so that backends
                  find clean buffers to evict
BACKEND           ⭐ if it needs a buffer and all are dirty, it writes one
                  ITSELF — a latency spike on a user query

-- ⭐ buffers_backend is the metric: backends doing the writer's job
SELECT buffers_checkpoint, buffers_clean, buffers_backend, buffers_backend_fsync
FROM pg_stat_bgwriter;
-- ⭐ buffers_backend_fsync > 0 is a RED FLAG: a backend had to fsync
--    a data file itself because the checkpointer's request queue was full.
```

---

## 5. The WAL-before-data rule, enforced

```
⭐ THE RULE: a dirty page may NEVER be written to the data file before
   the WAL record describing its change has been flushed to disk.
```

**Why it must hold:**

```
If the page were written first and the machine crashed before the WAL
flush, the data file would contain a change with NO LOG RECORD.

Recovery would not know the change exists. If the transaction had not
committed, there would be no way to know it should be invisible — and
no way to undo it (§16 explains why PostgreSQL cannot undo).
```

**How it is enforced:**

```c
/* Every buffer write does this check */
void FlushBuffer(BufferDesc *buf, ...)
{
    XLogRecPtr recptr = BufferGetLSN(buf);   /* the page's pd_lsn (DD04 §2) */

    /* ⭐ Force the WAL up to this page's LSN before writing the page */
    XLogFlush(recptr);

    smgrwrite(...);   /* only now write the page */
}
```

Each page carries `pd_lsn` — the LSN of the most recent WAL record affecting it. Writing the page requires flushing the WAL at least that far. **The rule is enforced page by page, mechanically, with no global coordination.**

---

## 6. Torn pages and full-page writes ⭐

The subtlety that makes WAL records insufficient on their own.

### The problem

```
PostgreSQL writes 8 KB pages.
Storage devices write in 512-byte or 4 KB sectors.
⭐ An 8 KB page write is therefore NOT ATOMIC.

Power fails mid-write:
    sectors 0-7   (4 KB): NEW data ✓
    sectors 8-15  (4 KB): OLD data ✗

    → a TORN PAGE: half old, half new. Internally inconsistent.
      Line pointers may point past pd_upper. The page is garbage.
```

### Why a normal WAL record cannot fix it

```
A WAL record says: "at offset 412 on page 991, change these 20 bytes."

To apply that, recovery must READ page 991 — but page 991 is TORN.
The delta is meaningless applied to corrupt data.

⭐ You cannot repair an unknown corruption with a delta.
```

### The solution: full-page writes

```
⭐ THE FIRST TIME a page is modified after each checkpoint, write the
   ENTIRE 8 KB page image into the WAL, instead of a delta.

During recovery:
    • encounter a full-page image → ⭐ restore the whole page wholesale.
      Whatever was on disk is irrelevant; it is overwritten.
    • subsequent delta records for that page apply on top, safely,
      because the page is now known-good.
```

```sql
SHOW full_page_writes;   -- on (the default)
```

### When you may turn it off

```
❌ Almost never. Only if your storage guarantees ATOMIC 8 KB writes:
   • ZFS with recordsize = 8 KB (copy-on-write — never overwrites in place)
   • Some enterprise arrays with battery-backed atomic write guarantees
   • NVMe with a validated atomic write unit ≥ 8 KB
   
⭐ Do NOT turn it off because "we have a UPS" or "our SSD has PLP".
   Power-loss protection on a drive protects the drive's cache; it does
   not make an 8 KB write atomic across sectors. Getting this wrong
   produces silent, unrecoverable corruption discovered months later.
```

**And note:** `wal_log_hints = on` (required for `pg_rewind`, §20) and data checksums *also* force full-page images for hint-bit changes, which is why the `pg_waldump --stats` output in §2 showed `FPI_FOR_HINT` as 61% of WAL volume.

---

## 7. The full-page-write storm, quantified

This is the mechanism behind the single most impactful WAL tuning decision.

```
IMMEDIATELY AFTER A CHECKPOINT:
    Every page touched is being touched "for the first time since the
    checkpoint" → ⭐ EVERY modification writes a FULL 8 KB PAGE.

LATER IN THE CHECKPOINT INTERVAL:
    Most hot pages have already been fully written once → subsequent
    modifications write small deltas (~100 bytes).
```

### The arithmetic

```
Workload: 2,000 UPDATEs/sec, each touching 1 heap page + 2 index pages.
checkpoint_timeout = 5 min (the DEFAULT).

First ~30 seconds after a checkpoint (the "storm"):
    2,000/sec × 3 pages × 8 KB = ⭐ 48 MB/sec of WAL

Steady state later in the interval:
    2,000/sec × 3 records × ~120 bytes = ⭐ 0.7 MB/sec of WAL

⭐ A 68× difference, and it repeats EVERY FIVE MINUTES.
```

### What you observe

```
• WAL volume spikes periodically, in a sawtooth
• Replication lag spikes at the same interval
• Commit latency (p99) spikes at the same interval  ⭐ because the WAL
  fsync queue is saturated
• Archive commands fall behind in bursts
• Network utilisation to replicas is spiky
```

**Teams frequently misdiagnose this as "the network is flaky" or "the replica is slow".** It is checkpoint-driven full-page writes.

### The fix: longer checkpoint intervals

```
⭐ A page written as a full image ONCE per checkpoint interval.
   Double the interval → half as many full-page writes for the same workload.
```

```sql
-- ⭐ The single highest-impact WAL change on most systems
ALTER SYSTEM SET checkpoint_timeout = '15min';   -- from the 5min default
ALTER SYSTEM SET max_wal_size = '16GB';          -- from the 1GB default
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
SELECT pg_reload_conf();
```

**The trade-off, stated honestly:**

```
LONGER checkpoint interval:
    ✅ Far less WAL (fewer full-page writes)
    ✅ Smoother I/O, less latency jitter
    ❌ LONGER CRASH RECOVERY — more WAL to replay
    ❌ More disk space for WAL
```

```
⭐ Recovery time estimate:
   worst case ≈ (WAL generated per checkpoint interval) / (replay rate)

   Replay is single-threaded and typically runs at 50-200 MB/s.
   16 GB of WAL / 100 MB/s ≈ 160 seconds of recovery.

   Decide this against your RTO (Chapter 19 §19.2). If your RTO is
   5 minutes, 16 GB is comfortable. If it is 30 seconds, it is not.
```

---

## 8. wal_compression

Because full-page images dominate WAL volume, compressing *them specifically* is unusually effective.

```sql
SHOW wal_compression;   -- off (default)  ⭐ usually should not be

-- PG15+ offers multiple algorithms
ALTER SYSTEM SET wal_compression = 'lz4';    -- ⭐ best default: fast, good ratio
-- options: off | pglz | lz4 | zstd
```

```
Measured on a typical OLTP workload:

  off:    WAL 480 GB/day
  pglz:   WAL 210 GB/day   (56% reduction, ~3% CPU)
  lz4:    WAL 195 GB/day   ⭐ (59% reduction, ~1% CPU — the best trade)
  zstd:   WAL 148 GB/day   (69% reduction, ~5% CPU)
```

**Why the ratio is so good:** an 8 KB heap page is mostly repetitive — tuple headers with similar xmin values, aligned padding, NULL bitmaps, and often free space. Pages compress far better than arbitrary data.

```
⭐ It compresses ONLY full-page images, not ordinary WAL records.
   So its benefit is largest exactly when the FPI storm is worst.

Knock-on benefits:
   • less replication bandwidth
   • smaller WAL archive (and lower archive storage cost)
   • ⭐ less WAL to fsync → LOWER COMMIT LATENCY
   • faster crash recovery (less to read)
```

> **`wal_compression = lz4` is close to a free win on any system with meaningful write volume**, and it is off by default for historical reasons. Enable it.

---

## 9. WAL segments: files, naming, recycling

```
$PGDATA/pg_wal/
  000000010000002A000000B3
  ^^^^^^^^^^^^^^^^^^^^^^^^
  │       │       └─ segment number within that log file (8 hex)
  │       └───────── log file number = high 32 bits of the LSN (8 hex)
  └───────────────── ⭐ TIMELINE ID (8 hex) — see §19

Default segment size: 16 MB (set at initdb with --wal-segsize; 64 MB is
                      a reasonable choice for very high-write systems,
                      reducing file-management overhead)
```

### Recycling, not deleting

```
⭐ When a WAL segment is no longer needed, PostgreSQL RENAMES it to a
   future segment name rather than deleting and recreating it.

   Why: the file is already allocated and (on most filesystems) already
   has its blocks. Reusing it avoids filesystem metadata work and
   avoids the "first write to a sparse file" penalty.

Controlled by min_wal_size (default 80 MB): keep at least this much
recycled and ready.
```

### What decides retention

A segment can be removed only when **all** of these are satisfied:

```
1. Its changes are covered by a completed CHECKPOINT (the REDO point
   has moved past it)
2. It has been ARCHIVED, if archive_mode = on
3. ⭐ Every REPLICATION SLOT's restart_lsn has moved past it   (§22)
4. It is beyond wal_keep_size, if that is set
```

**Condition 3 is the one that fills disks.** §22.

```sql
-- What is in pg_wal, and why?
SELECT count(*) AS segments,
       pg_size_pretty(count(*) * 16 * 1024 * 1024) AS total_size
FROM pg_ls_waldir();

SELECT name, pg_size_pretty(size) AS size, modification
FROM pg_ls_waldir() ORDER BY modification DESC LIMIT 5;
```

### wal_level

```sql
SHOW wal_level;
```

| Level | Logs enough for | Cost |
|-------|----------------|------|
| `minimal` | Crash recovery only. ⭐ Skips WAL entirely for some bulk operations (`COPY` into a table created in the same transaction). | No replication, **no PITR** |
| **`replica`** (default) | Crash recovery + physical replication + PITR | Baseline |
| `logical` | ⭐ All of the above + **logical decoding / CDC** (§24) | ~10–20% more WAL |

**`wal_level = minimal` is genuinely useful for ETL-only instances** where the data can be reloaded from source — bulk loads can be several times faster. Never on anything you need to replicate or recover to a point in time.

---

## 10. Checkpoints: the phases

A checkpoint establishes a point from which recovery can start, by guaranteeing that everything before it is safely in the data files.

```
PHASE 1 — Determine the REDO point
    ⭐ The REDO point is the LSN at the START of the checkpoint, NOT the
       end. Recovery must replay from here, because pages dirtied during
       the checkpoint might not be written.

PHASE 2 — Scan shared_buffers, write every dirty page
    ⭐ SPREAD OVER TIME (checkpoint_completion_target) to avoid an
       I/O spike. This is the part that takes minutes.

PHASE 3 — fsync every file that was written
    ⭐ Historically this was the killer: a single fsync on a large file
       with many dirty OS-cache pages could block for many seconds.
       PG9.6+ sorts writes and spreads fsyncs; PG12+ delegates fsync
       requests to the checkpointer more reliably.

PHASE 4 — Write the checkpoint record to WAL, and update pg_control
    pg_control now says "recovery starts at the REDO point"

PHASE 5 — Remove or recycle WAL segments older than the REDO point
    (subject to §9's four conditions)
```

### What triggers one

```
1. checkpoint_timeout elapsed             → a "timed" checkpoint  ✅ good
2. ⭐ max_wal_size exceeded               → a "requested" checkpoint ❌ bad
3. Manual CHECKPOINT command
4. Clean shutdown
5. pg_backup_start() / pg_basebackup
6. Certain DDL (CREATE DATABASE, DROP TABLESPACE)
```

```sql
-- ⭐ THE diagnostic. checkpoints_req should be near zero.
SELECT checkpoints_timed, checkpoints_req,
       round(100.0*checkpoints_req/NULLIF(checkpoints_timed+checkpoints_req,0),1)
         AS pct_requested,
       checkpoint_write_time, checkpoint_sync_time,
       buffers_checkpoint, buffers_clean, buffers_backend, buffers_backend_fsync
FROM pg_stat_bgwriter;
-- (PostgreSQL 17 moved checkpoint columns to pg_stat_checkpointer)
```

```
 checkpoints_timed | checkpoints_req | pct_requested
-------------------+-----------------+---------------
               288 |            4127 |          93.5   ⭐⭐ SEVERE PROBLEM
```

**93.5% requested means `max_wal_size` is far too small.** The system is checkpointing every few seconds because it keeps hitting the WAL size limit — which means a permanent full-page-write storm (§7).

---

## 11. ⭐ Checkpoint tuning: the default is wrong

```sql
-- The defaults
checkpoint_timeout = 5min
max_wal_size = 1GB                 ⭐ far too small for any busy system
min_wal_size = 80MB
checkpoint_completion_target = 0.9  (0.5 before PG14)
```

### Sizing `max_wal_size` from measurement

```sql
-- 1. Measure your actual WAL generation rate
SELECT pg_current_wal_lsn() AS lsn, now() AS t;
-- ... wait 60 seconds ...
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), 'PREVIOUS_LSN'))
       AS wal_per_minute;
--  412 MB

-- PG14+ makes this easier:
SELECT pg_size_pretty(wal_bytes) AS wal_total, wal_records, wal_fpi,
       stats_reset
FROM pg_stat_wal;
```

```
⭐ THE SIZING RULE:
   max_wal_size should hold AT LEAST the WAL generated in
   2-3 × checkpoint_timeout.

   412 MB/min × 15 min × 2.5 = ⭐ ~15 GB
```

```sql
-- The resulting configuration
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET max_wal_size = '16GB';
ALTER SYSTEM SET min_wal_size = '2GB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_compression = 'lz4';
ALTER SYSTEM SET wal_buffers = '64MB';           -- default caps at 16MB
SELECT pg_reload_conf();
```

### `checkpoint_completion_target`

```
0.9 means: spread the dirty-page writes over 90% of checkpoint_timeout.

  checkpoint_timeout = 15 min
  → write the dirty buffers over ~13.5 minutes
  → ⭐ a gentle, continuous trickle instead of a spike

With 0.0 (never do this), all writes happen as fast as possible,
producing a massive I/O spike that starves user queries.
```

### Verifying the fix

```sql
SELECT pg_stat_reset_shared('bgwriter');
-- ... wait a few hours ...
SELECT checkpoints_timed, checkpoints_req,
       round(checkpoint_write_time/1000.0/NULLIF(checkpoints_timed,0),1)
         AS avg_write_secs,
       round(checkpoint_sync_time/1000.0/NULLIF(checkpoints_timed,0),2)
         AS avg_sync_secs,
       buffers_backend_fsync
FROM pg_stat_bgwriter;
```

```
✅ HEALTHY:
   checkpoints_req ≈ 0
   avg_write_secs ≈ 0.9 × checkpoint_timeout  (spread properly)
   avg_sync_secs < 1
   buffers_backend_fsync = 0
```

---

## 12. Traced scenario — a checkpoint storm

A realistic incident showing all of §7 and §11 in motion.

```
SYSTEM: 3,000 writes/sec. Defaults never changed.
        checkpoint_timeout = 5min, max_wal_size = 1GB.

09:00:00  Checkpoint completes. REDO point set.

09:00:00-09:00:20  ⭐ FULL-PAGE-WRITE STORM
          Every page touched is "first touch since checkpoint".
          3,000/sec × 3 pages × 8 KB = 72 MB/sec of WAL.

09:00:14  ⭐ max_wal_size (1 GB) EXCEEDED after just 14 seconds.
          → A REQUESTED checkpoint fires immediately.

09:00:14  New checkpoint starts. REDO point moves.
          ⭐ ALL PAGES ARE NOW "FIRST TOUCH" AGAIN.
          The full-page-write storm RESTARTS.

09:00:28  max_wal_size exceeded again. Another checkpoint.

⭐ THE SYSTEM IS NOW IN A CHECKPOINT LOOP.
   It checkpoints every ~14 seconds instead of every 5 minutes.
   It NEVER reaches the efficient steady state.
   Essentially 100% of WAL is full-page images.
```

### What the team observed

```
• WAL generation: 72 MB/sec sustained (should be ~1 MB/sec)
• Replica lag: oscillating 0-45 seconds
• Commit p99: 180 ms (should be 3 ms)
• Disk write utilisation: 95%
• ⭐ The log, every 14 seconds:
    LOG: checkpoints are occurring too frequently (14 seconds apart)
    HINT: Consider increasing the configuration parameter "max_wal_size".
```

**PostgreSQL was printing the answer in the log the entire time.** This message is the single most actionable line in the PostgreSQL log and it is routinely ignored.

### The fix and the result

```sql
ALTER SYSTEM SET max_wal_size = '32GB';
ALTER SYSTEM SET checkpoint_timeout = '20min';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_compression = 'lz4';
SELECT pg_reload_conf();
```

```
AFTER:
  Checkpoints: every 20 minutes, all timed, zero requested
  WAL generation: 72 MB/sec → ⭐ 2.1 MB/sec  (34× reduction)
  Commit p99: 180 ms → ⭐ 2.8 ms
  Replica lag: steady < 100 ms
  Disk write utilisation: 95% → 12%

  Cost: crash recovery worst case grows from ~10 s to ~4 min.
        ⭐ Accepted explicitly against a 15-minute RTO.
```

> **34× less WAL and 64× better commit latency, from four configuration settings.** This is among the highest-value tuning changes available in PostgreSQL, and the defaults make it necessary on essentially every busy system.

---

## 13. synchronous_commit: all five levels ⭐

The durability dial, and it can be set **per transaction** — which makes it far more useful than most people realise.

```sql
SHOW synchronous_commit;   -- on
```

| Level | Waits for | Data loss window | Latency |
|-------|-----------|-----------------|---------|
| `off` | ⭐ **Nothing** — returns immediately | Up to 3 × `wal_writer_delay` (~600 ms) of **committed transactions** | **Lowest** |
| `local` | Local WAL fsync | None locally | 1 fsync |
| `remote_write` | Standby has `write()`n it (OS cache) | Lost if the standby's **OS** crashes | 1 fsync + network |
| **`on`** (default) | Local fsync + standby fsync | None | 1 fsync + network + remote fsync |
| `remote_apply` | ⭐ Standby has **applied** it (visible to queries there) | None | Highest |

### The crucial property of `off`

```
⭐ synchronous_commit = off does NOT risk corruption or inconsistency.

   It risks losing the LAST FEW HUNDRED MILLISECONDS of COMMITTED
   transactions on a crash.

   Atomicity holds: a transaction is either fully present or fully absent.
   Consistency holds: constraints are never violated.
   Isolation holds.
   ⭐ Only DURABILITY is relaxed, and only for a bounded window.
```

**This makes it a legitimate and valuable engineering lever** — unlike `fsync = off`, which genuinely risks corruption and must never be used on real data.

### Per-transaction use — the high-value pattern

```sql
-- ⭐ Payments: full durability, no compromise
BEGIN;
SET LOCAL synchronous_commit = on;
INSERT INTO payments (...) VALUES (...);
COMMIT;

-- ⭐ Analytics events: losing 600 ms on a crash is irrelevant,
--    and this can be 5-10× faster
BEGIN;
SET LOCAL synchronous_commit = off;
INSERT INTO page_views (...) SELECT ... ;
COMMIT;

-- Or per role
ALTER ROLE analytics_writer SET synchronous_commit = off;
ALTER ROLE payment_service  SET synchronous_commit = on;
```

```
MEASURED on a system with 1 ms fsync latency:
    synchronous_commit = on,  single-row inserts:  ~900 inserts/sec/connection
    synchronous_commit = off, single-row inserts:  ⭐ ~9,000 inserts/sec/connection
```

> **This is the correct answer to "our event ingestion is slow".** Before reaching for a queue, a different database, or batching complexity, ask whether losing 600 ms of analytics events on an unplanned crash is acceptable. It usually is, and one `SET LOCAL` gets you an order of magnitude.

### `remote_apply` and read-your-writes

```
⭐ remote_apply is the setting that makes READ-YOUR-WRITES work across
   a primary and a synchronous replica (Deep Dive 03 §13).

   With `on`, the standby has the data DURABLY but may not have APPLIED it —
   so a read routed there immediately after the commit can miss it.
   With `remote_apply`, the commit does not return until the standby can
   serve the new value.

Cost: commit latency now includes the standby's replay. On a busy standby
with replay lag, this can be substantial.
```

---

## 14. Group commit

```
⭐ When many backends commit concurrently, PostgreSQL batches their
   WAL flushes into a SINGLE fsync.

  Backend A: commit at LSN 1000 ─┐
  Backend B: commit at LSN 1080 ─┼─► ONE fsync to LSN 1240
  Backend C: commit at LSN 1160 ─┤    ⭐ all three are durable
  Backend D: commit at LSN 1240 ─┘
```

**This is why commit throughput scales far better than `1 / fsync_latency` would suggest.** With 100 concurrent committers and a 1 ms fsync, you do not get 1,000 commits/sec — you get closer to 50,000, because each fsync covers many commits.

```sql
-- Explicit tuning, rarely needed on modern versions
SHOW commit_delay;     -- 0 microseconds
SHOW commit_siblings;  -- 5

-- commit_delay: wait N microseconds before flushing, hoping more commits
--               arrive to join the batch. Only applies when at least
--               commit_siblings transactions are active.
-- ⭐ On slow storage (high fsync latency), a small commit_delay
--    (e.g. 100-1000 µs) can measurably increase throughput.
--    On NVMe it is usually counterproductive.
```

```sql
-- PG14+: observe the effect directly
SELECT wal_write, wal_sync,
       round(wal_write_time::numeric, 0) AS write_ms,
       round(wal_sync_time::numeric, 0)  AS sync_ms,
       wal_buffers_full                   -- ⭐ > 0 → raise wal_buffers
FROM pg_stat_wal;
```

---

## 15. Crash recovery, step by step

```
POSTGRES STARTS. pg_control says the last shutdown was NOT clean.

STEP 1 — Read pg_control
    • last checkpoint location
    • ⭐ the REDO point (where replay must START — §10 phase 1)
    • the timeline ID

STEP 2 — Open the WAL at the REDO point.

STEP 3 — REDO LOOP. For each record, in order:

    a) Verify the CRC. ⭐ A bad CRC means the record is torn — recovery
       STOPS here. This is the end of valid WAL.
    b) Verify xl_prev matches the previous record's LSN. Another
       torn-write detector.
    c) For each referenced page:
         • read the page into shared_buffers
         • ⭐ IF the record contains a FULL PAGE IMAGE:
                restore it wholesale, unconditionally  (§6)
         • ELSE IF page.pd_lsn >= record LSN:
                ⭐ SKIP — this change is already in the page
                   (the page was written to disk after this change)
         • ELSE:
                apply the delta, set page.pd_lsn = record LSN

STEP 4 — Recovery reaches the end of valid WAL.
    ⭐ NO UNDO PHASE. See §16.

STEP 5 — Write a checkpoint, update pg_control, open for connections.
```

### The idempotence property

```
⭐ Step 3c's LSN comparison makes replay IDEMPOTENT.

   Recovery can be interrupted and restarted from the same REDO point
   any number of times. Records whose effects are already on the page
   are skipped. There is no "partially recovered" state.

This is why a crash DURING recovery is harmless — you simply start again.
```

### Watching it

```
LOG:  database system was interrupted; last known up at 2026-09-12 14:18:02 UTC
LOG:  database system was not properly shut down; automatic recovery in progress
LOG:  redo starts at 2A/B3000028                        ⭐ the REDO point
LOG:  invalid record length at 2A/C1482190: wanted 24, got 0
                                            ⭐ NORMAL — the end of valid WAL
LOG:  redo done at 2A/C148215C system usage: CPU 2.41s/18.92u sec elapsed 41.02 s
LOG:  checkpoint starting: end-of-recovery immediate
LOG:  database system is ready to accept connections
```

```
⭐ "invalid record length ... wanted 24, got 0" during recovery is NOT
   an error. It is how recovery detects the end of the log. Seeing it
   in a recovery log is expected and correct.
```

### Estimating recovery time

```
Recovery time ≈ (WAL between REDO point and crash) / (replay rate)

Replay is SINGLE-THREADED and typically 50-200 MB/s, often bounded by
random reads of the pages being modified.

⭐ With max_wal_size = 16GB:  worst case ≈ 16 GB / 100 MB/s ≈ 160 seconds.
```

**This is the number to put in your RTO calculation** (Chapter 19 §19.2), and it is the direct cost of §11's checkpoint tuning.

---

## 16. ⭐ Why PostgreSQL needs no UNDO phase

A significant architectural simplification that follows from MVCC.

### What other databases do (ARIES)

```
Oracle, SQL Server, InnoDB, and the ARIES algorithm generally:

  PHASE 1 — ANALYSIS: scan WAL to find which transactions were in flight
  PHASE 2 — REDO:     replay everything, including uncommitted changes
  PHASE 3 — ⭐ UNDO:  roll back the uncommitted transactions using
                       the undo log

  Undo is REQUIRED because they UPDATE PAGES IN PLACE. An uncommitted
  change physically overwrote the old value, so recovery must restore it.
```

### What PostgreSQL does

```
  PHASE 1 — REDO: replay everything.
  ⭐ (there is no phase 2)
```

**Why it works:**

```
⭐ PostgreSQL never updates in place (Deep Dive 04 §11).

An uncommitted INSERT left a tuple with t_xmin = 847291.
An uncommitted DELETE left a tuple with t_xmax = 847291.

After recovery, pg_xact has NO COMMIT RECORD for 847291.
→ MVCC visibility (Deep Dive 04 §7) treats it as ABORTED.
→ ⭐ The inserted tuple is invisible. The deleted tuple is still visible.

The uncommitted work is physically present and logically absent.
Nothing needs to be undone. VACUUM cleans it up later, as ordinary
dead-tuple garbage.
```

### The consequences

| | PostgreSQL | ARIES (Oracle/InnoDB) |
|---|---|---|
| Recovery phases | **1 (REDO)** | 3 (analysis, redo, undo) |
| ROLLBACK cost | ⭐ **O(1)** — write an abort record | O(size of transaction) |
| Long transaction rollback | Instant | ⭐ Can take **longer than the transaction did** |
| Cost paid instead | Bloat + VACUUM (DD04) | Undo log management, "snapshot too old" |

```
⭐ A 6-hour bulk UPDATE that you cancel:
     PostgreSQL: ROLLBACK returns immediately.
     InnoDB:     the rollback can take hours, and it cannot be interrupted.
                 (This has caused real, extended outages.)
```

> This is the same trade as Deep Dive 04 §1 and §25, viewed from the recovery side. **PostgreSQL front-loads nothing and defers cleanup to VACUUM; ARIES databases keep the table compact and pay at rollback and at read time.** Neither is universally better — but knowing which you have tells you which failure mode to prepare for.

---

## 17. Base backups: what pg_basebackup actually does

```bash
pg_basebackup -h primary -D /backup/base -X stream -c fast -P -R \
              --compress=zstd:3
```

### The protocol

```
STEP 1 — pg_backup_start('label', fast := true)
    ⭐ Forces a CHECKPOINT (immediate with 'fast', or spread otherwise).
       Records the REDO point as the BACKUP START LSN.
       Sets a flag so full-page writes are guaranteed on (they must be).

STEP 2 — Copy the entire data directory.
    ⭐ Files are copied while the database is RUNNING and being modified.
       The copy is therefore INTERNALLY INCONSISTENT — a file copied at
       10:00 and another at 10:05 disagree.
       ⭐ THIS IS EXPECTED AND FINE. See step 4.

STEP 3 — pg_backup_stop()
    Returns the BACKUP END LSN and the contents of backup_label.

STEP 4 — ⭐ THE KEY INSIGHT:
    Replaying WAL from BACKUP START LSN to BACKUP END LSN makes the
    inconsistent file copy CONSISTENT.

    Because full-page writes are on, every page modified during the copy
    has a full image in that WAL range. Replay overwrites every
    possibly-torn or possibly-stale page with a known-good version.

⭐ THEREFORE: a base backup is useless without the WAL covering
   start→end. A backup without its WAL is not a backup.
```

### The options that matter

```bash
-X stream      # ⭐ stream WAL in a second connection DURING the backup.
               #    Guarantees the required WAL is captured even if the
               #    primary recycles segments. USE THIS.
-X fetch       #    collect WAL at the end — can FAIL if segments were
               #    already recycled. Avoid.

-c fast        # immediate checkpoint — starts the backup at once, at the
               # cost of an I/O spike. Without it, the backup waits for a
               # spread checkpoint (up to checkpoint_completion_target × timeout).

-R             # ⭐ write standby.signal + primary_conninfo → the copy is
               # immediately usable as a replica

--compress=zstd:3    # PG15+ server-side or client-side compression
-P                   # progress reporting
```

### The production tools

```
pg_basebackup   built in, full backups only, no incremental, no retention
pgBackRest      ⭐ incremental/differential, parallel, encryption, retention
                   policies, backup verification, delta restore
WAL-G           ⭐ cloud-native, delta backups, very fast, S3/GCS/Azure
Barman          mature, good for on-premise fleets
```

**For anything beyond a single small database, use pgBackRest or WAL-G.** `pg_basebackup` has no incremental support, so a 2 TB database means copying 2 TB every time.

---

## 18. Point-in-time recovery, traced

The scenario: at 14:32, someone ran `DELETE FROM orders` without a `WHERE` clause. It is now 14:47.

```bash
# ═══ STEP 0 — STOP. Do not let it get worse. ═══
# Take the application offline. Do NOT attempt to fix the data in place.
# ⭐ And do NOT restore over the existing data directory — you may need it.

# ═══ STEP 1 — Identify the recovery target ═══
# Option A: a timestamp
#   recovery_target_time = '2026-09-12 14:31:55 UTC'
#
# Option B: ⭐ more precise — find the exact transaction
pg_waldump -p /backup/wal 000000010000002A000000B3 \
  | grep -i "COMMIT" | grep "14:3[12]"
# Or search for the destructive statement's xid if you have logging

# ═══ STEP 2 — Restore the base backup to a NEW directory ═══
pgbackrest --stanza=main --type=time \
           --target="2026-09-12 14:31:55" \
           --target-action=pause \
           --pg1-path=/var/lib/postgresql/16/restored \
           restore

# Manually, the equivalent is:
#   tar -xf /backup/base.tar -C /var/lib/postgresql/16/restored
#   and then configure recovery:
```

```ini
# postgresql.conf in the restored directory (PG12+; these were in
# recovery.conf before PG12)

restore_command = 'cp /backup/wal/%f %p'
recovery_target_time = '2026-09-12 14:31:55 UTC'
recovery_target_inclusive = false        # ⭐ stop BEFORE this time
recovery_target_action = 'pause'         # ⭐ PAUSE, do not auto-promote
recovery_target_timeline = 'latest'
```

```bash
# ═══ STEP 3 — Signal recovery mode ═══
touch /var/lib/postgresql/16/restored/recovery.signal

# ═══ STEP 4 — Start it ═══
pg_ctl -D /var/lib/postgresql/16/restored start
```

```
LOG:  starting point-in-time recovery to 2026-09-12 14:31:55+00
LOG:  restored log file "000000010000002A000000B3" from archive
LOG:  redo starts at 2A/B3000028
LOG:  restored log file "000000010000002A000000B4" from archive
...
LOG:  recovery stopping before commit of transaction 847291, time 2026-09-12 14:31:57
LOG:  ⭐ recovery has paused
HINT: Execute pg_wal_replay_resume() to promote.
```

```sql
-- ═══ STEP 5 — ⭐ VERIFY BEFORE PROMOTING ═══
-- This is why recovery_target_action = 'pause' matters. The database is
-- open READ-ONLY at the target point. Check that you recovered to the
-- right moment.
SELECT count(*) FROM orders;                 -- 4,318,204 ✓ the data is back
SELECT max(created_at) FROM orders;          -- 14:31:52 ✓ just before the DELETE
SELECT pg_is_in_recovery();                  -- t

-- If the target was wrong, SHUT DOWN, adjust recovery_target_time,
-- and start again from the base backup. ⭐ You cannot rewind a promotion.
```

```sql
-- ═══ STEP 6 — Promote ═══
SELECT pg_wal_replay_resume();
-- or: pg_ctl promote -D /var/lib/postgresql/16/restored
```

```
LOG:  redo done at 2A/C1482190
LOG:  ⭐ selected new timeline ID: 2
LOG:  archive recovery complete
LOG:  database system is ready to accept connections
```

**Note that last line: a new timeline.** That is §19, and it is where PITR goes wrong for people.

### The recovery targets

```ini
recovery_target_time = '...'       # a timestamp
recovery_target_lsn  = '2A/B3000028'  # ⭐ the most precise
recovery_target_xid  = '847290'    # stop before/after this transaction
recovery_target_name = 'before_migration'   # ⭐ set earlier with
                                            #   pg_create_restore_point()
recovery_target = 'immediate'      # stop as soon as consistency is reached

recovery_target_inclusive = true|false      # include the target itself?
recovery_target_action = 'pause'|'promote'|'shutdown'
```

```sql
-- ⭐ Before any risky migration, create a named restore point.
--    It gives you an exact, unambiguous target instead of guessing a timestamp.
SELECT pg_create_restore_point('before_v2_migration');
```

---

## 19. ⭐ Timelines — the concept that catches everyone

```
⭐ A TIMELINE is a branch of WAL history.
   Every time recovery ends with a PROMOTION, the timeline ID increments.
```

### Why they exist

```
Timeline 1:  ... ──── 14:00 ──── 14:31 ──── 14:32 (the bad DELETE) ──── 14:47
                                    │
                                    │ PITR to 14:31:55, then promote
                                    ▼
Timeline 2:                         └──── 14:31:55 ──── new writes ────►

⭐ Without timelines, the new writes on timeline 2 would OVERWRITE the
   WAL segments of timeline 1 (same LSN range, same filenames) — and
   you could never recover to any other point in the original history.

WAL filenames embed the timeline (§9):
    0000000100000 02A000000B3    timeline 1
    0000000200000 02A000000B3    ⭐ timeline 2 — a DIFFERENT file,
                                    same LSN range
```

### The `.history` file

```bash
cat /backup/wal/00000002.history
```
```
1  2A/C1482190  before 2026-09-12 14:31:57.128411+00

# ⭐ "Timeline 2 branched from timeline 1 at LSN 2A/C1482190"
# Recovery uses this to follow the correct chain of timelines.
```

### The three mistakes people make

**Mistake 1 — the replicas are now on the wrong timeline**

```
You PITR the primary and promote. It is on timeline 2.
Your three replicas are still following timeline 1.

⭐ They cannot follow the new primary — their WAL histories diverged
   at 14:31:55, and they contain writes (14:32-14:47) that no longer exist.

Symptom:
    FATAL: requested timeline 2 is not a child of this server's history
    DETAIL: Latest checkpoint is at 2A/C9000028 on timeline 1, but in the
            history of the requested timeline, the server forked off from
            that timeline at 2A/C1482190.

FIX: rebuild each replica (pg_basebackup) or use pg_rewind (§20).
```

**Mistake 2 — recovering "to the latest" after a PITR**

```ini
recovery_target_timeline = 'latest'   # ⭐ the default in PG12+
```

```
"latest" means "follow timeline branches forward as far as they go".

⭐ If you are trying to recover to a point on timeline 1, but timeline 2
   exists in your archive, 'latest' will follow the branch into timeline 2
   and recover PAST the point you wanted.

To recover to a specific point on the ORIGINAL history:
    recovery_target_timeline = 1
```

**Mistake 3 — losing the `.history` files**

```
⭐ .history files are TINY (a few hundred bytes) and ABSOLUTELY ESSENTIAL.
   Without them, recovery cannot determine the timeline ancestry and
   will refuse to proceed or will follow the wrong branch.

Ensure your archive_command archives them (it does by default — they
pass through the same path as WAL segments), and ensure your retention
policy NEVER deletes them. They are the map of your recovery options.
```

> **Timelines are the single most common cause of a PITR that "worked" but left the fleet broken.** After any promotion, plan for the replicas: `pg_rewind` if possible, fresh base backups otherwise.

---

## 20. pg_rewind

The tool that saves you from rebuilding a large replica after a failover.

### The problem

```
Primary A fails. Replica B is promoted (now timeline 2).
A comes back up. It has WAL from timeline 1 that B never received —
⭐ A's history DIVERGED from B's.

A cannot simply follow B: it contains changes that do not exist on B.

Classic fix: pg_basebackup the entire 4 TB database. Hours of copying.
```

### What pg_rewind does

```
⭐ It rewinds A to the point of divergence by copying ONLY the blocks
   that changed, from B.

1. Find the divergence LSN from B's .history file
2. Scan A's WAL from that LSN forward, collecting every BLOCK it modified
3. Copy ONLY those blocks from B
4. Copy the control file and configuration
5. A can now start as a replica of B and replay forward

Copies gigabytes instead of terabytes. Minutes instead of hours.
```

```bash
# ⭐ A must be cleanly shut down first
pg_ctl -D /var/lib/postgresql/16/main stop -m fast

pg_rewind --target-pgdata=/var/lib/postgresql/16/main \
          --source-server="host=new-primary port=5432 user=postgres" \
          --progress

# Then configure it as a standby and start
```

### The prerequisite ⭐

```sql
-- pg_rewind REQUIRES one of these on the cluster:
SHOW wal_log_hints;   -- must be 'on'
SHOW data_checksums;  -- or this must be 'on'
```

```
⭐ WHY: pg_rewind needs every block modification to appear in the WAL,
   including HINT BIT changes (Deep Dive 04 §9) — which are normally
   NOT logged. Without one of these settings, pg_rewind cannot identify
   all changed blocks and would leave silent corruption.

⭐ BOTH require initdb-time or a restart to enable:
     data_checksums:  initdb --data-checksums, or pg_checksums --enable
                      (requires the cluster to be shut down)
     wal_log_hints:   a configuration change + restart

⭐ TURN ONE OF THESE ON NOW, before you need it. Discovering that
   pg_rewind is unavailable during an incident means a full rebuild.
```

**Patroni and most HA tooling use `pg_rewind` automatically during failback.** If it is not enabled, your automated failover degrades into a manual multi-hour rebuild at exactly the wrong moment.

---

## 21. Streaming replication: walsender and walreceiver

```
        PRIMARY                                    STANDBY
  ┌──────────────────┐                      ┌──────────────────┐
  │  backends        │                      │                  │
  │     │ write WAL  │                      │                  │
  │     ▼            │                      │                  │
  │  WAL buffers     │                      │                  │
  │     │            │                      │                  │
  │     ▼            │                      │                  │
  │  pg_wal/ ────────┼──► walsender ────────┼──► walreceiver   │
  │                  │    (one process      │        │         │
  │                  │     per standby)     │        ▼         │
  │                  │                      │     pg_wal/      │
  │                  │                      │        │         │
  │                  │                      │        ▼         │
  │                  │                      │   startup process│
  │                  │                      │   (replays WAL)  │
  └──────────────────┘                      └──────────────────┘
```

### The four LSNs of replication

```sql
-- ⭐ On the PRIMARY — the query to keep in your runbook
SELECT client_addr, application_name, state, sync_state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn))   AS pending_send,
       pg_size_pretty(pg_wal_lsn_diff(sent_lsn,  write_lsn))             AS send_lag,
       pg_size_pretty(pg_wal_lsn_diff(write_lsn, flush_lsn))             AS write_lag,
       pg_size_pretty(pg_wal_lsn_diff(flush_lsn, replay_lsn))            AS replay_lag,
       write_lag AS write_time, flush_lag AS flush_time, replay_lag AS replay_time
FROM pg_stat_replication;
```

| LSN | Meaning | A gap here means |
|-----|---------|-----------------|
| `sent_lsn` | Sent by the primary | Network or walsender is behind |
| `write_lsn` | Standby has `write()`n it | Standby OS/network buffer |
| `flush_lsn` | Standby has `fsync`d it | ⭐ **Standby disk is slow** |
| `replay_lsn` | Standby has **applied** it | ⭐ **Replay is behind** — usually a long query blocking it, or single-threaded replay saturated |

```sql
-- On the STANDBY
SELECT pg_is_in_recovery(),
       pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn(),
       ⭐ now() - pg_last_xact_replay_timestamp() AS replay_delay;
-- ⭐ replay_delay is the number to alert on — it is the actual staleness
--    a user reading from this replica would experience.
```

### Replay conflicts on a hot standby

```
The standby is replaying a VACUUM record that removes a tuple.
A query on the standby has a snapshot that still needs that tuple.

⭐ CONFLICT. One must lose.
```

```sql
-- Option A: cancel the standby query (the default)
SHOW max_standby_streaming_delay;   -- 30s
--   Replay waits up to 30 s, then CANCELS the conflicting query:
--     ERROR: canceling statement due to conflict with recovery
--     DETAIL: User query might have needed to see row versions that
--             must be removed.

-- Option B: ⭐ let the standby hold back the primary's xmin horizon
ALTER SYSTEM SET hot_standby_feedback = on;
--   The standby tells the primary "do not vacuum rows my queries need".
--   ✅ No more query cancellations.
--   ❌ ⭐ HOLDS THE PRIMARY'S XMIN HORIZON (Deep Dive 04 §16)
--      → bloat on the PRIMARY, caused by a long query on the STANDBY.
```

> **This is a genuine, unavoidable trade-off, and it must be a conscious decision.** Long analytical queries on a replica either get cancelled, or they cause bloat on the primary. The usual resolution: `hot_standby_feedback = on` **plus** a `statement_timeout` on the replica, bounding how long the horizon can be held.

```sql
-- The balanced configuration
-- On the standby:
ALTER SYSTEM SET hot_standby_feedback = on;
ALTER ROLE analytics SET statement_timeout = '5min';   -- ⭐ bounds the damage
```

---

## 22. Replication slots and the disk-full incident

```
A REPLICATION SLOT is the primary's promise: "I will retain WAL until
this consumer has confirmed it."
```

```sql
SELECT slot_name, slot_type, active, active_pid,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn))
         AS retained_wal,
       age(xmin) AS xmin_age,               -- ⭐ physical slot horizon hold
       age(catalog_xmin) AS catalog_xmin_age -- ⭐ logical slot horizon hold
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
```

```
  slot_name       | slot_type | active | retained_wal | xmin_age
------------------+-----------+--------+--------------+-----------
  old_replica_2   | physical  | ⭐ f   | ⭐ 847 GB    |  48291043
  debezium_cdc    | logical   | t      | 412 MB       |     18402
  replica_1       | physical  | t      | 84 MB        |      1204
```

### The incident this causes

```
09:00  Replica 2 is decommissioned. The VM is deleted.
       ⭐ Nobody drops its replication slot.

09:00+ The slot is INACTIVE, so restart_lsn never advances.
       PostgreSQL retains EVERY WAL segment from 09:00 onwards.

       At 3 GB/hour of WAL:
         Day 1:   72 GB in pg_wal
         Day 5:  360 GB
         Day 12: 864 GB

Day 12, 03:14  ⭐ THE DISK FILLS.

       PANIC: could not write to file "pg_wal/000000010000034A0000001C":
              No space left on device
       ⭐ POSTGRESQL SHUTS DOWN. The primary is DOWN.
```

**And recovery is awkward:** you cannot start PostgreSQL to drop the slot, because it has no disk space to start. You must free space at the filesystem level first — and **deleting WAL files by hand is extremely dangerous** (you can destroy the ability to recover).

```bash
# ⭐ The safe emergency procedure:
# 1. Free space from somewhere else — logs, a different partition,
#    temporarily extend the volume
# 2. Start PostgreSQL
# 3. Drop the offending slot IMMEDIATELY
psql -c "SELECT pg_drop_replication_slot('old_replica_2');"
# 4. CHECKPOINT to release the WAL
psql -c "CHECKPOINT;"
```

### The prevention

```sql
-- ⭐ 1. BOUND IT (PG13+). The single most important setting here.
ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';
--    Past this, the slot is INVALIDATED (marked 'lost'). The consumer
--    must be rebuilt — but ⭐ THE PRIMARY SURVIVES.
--    That is the correct trade: lose a replica, not the database.

-- 2. ⭐ ALERT on inactive slots
SELECT count(*) FROM pg_replication_slots WHERE NOT active;   -- alert if > 0

-- 3. ⭐ ALERT on retained WAL
SELECT slot_name,
       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS bytes
FROM pg_replication_slots
WHERE pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) > 10e9;  -- 10 GB

-- 4. Include "drop the replication slot" in your replica
--    decommissioning runbook. ⭐ This is a process fix, not a technical one.
```

### The logical slot's extra hazard

```
⭐ A LOGICAL slot also holds catalog_xmin — which pins the xmin horizon
   (Deep Dive 04 §16) for SYSTEM CATALOGS.

So an abandoned logical slot causes:
   • unbounded WAL retention (disk fill)
   • ⭐ AND catalog bloat
   • ⭐ AND blocks freezing → contributes to wraparound risk (DD04 §19)

A stalled Debezium connector is therefore a more serious incident than
it appears. Monitor logical slot lag as a first-class metric.
```

---

## 23. Synchronous replication topologies

```sql
-- Wait for ANY 1 of these three to confirm
ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (rep1, rep2, rep3)';

-- Wait for the FIRST available, in priority order
ALTER SYSTEM SET synchronous_standby_names = 'FIRST 2 (rep1, rep2, rep3)';

-- Wait for ALL (rarely correct)
ALTER SYSTEM SET synchronous_standby_names = '*';
```

### Choosing

| Config | Durability | Availability |
|--------|-----------|--------------|
| `ANY 1 (a, b, c)` | ⭐ At least one replica has it | ⭐ Survives 2 replica failures. **Usually right.** |
| `ANY 2 (a, b, c)` | Two replicas have it | Survives 1 replica failure |
| `FIRST 1 (a, b)` | `a` has it, or `b` if `a` is down | Priority order; predictable |
| `*` / `ALL` | Everyone has it | ⭐ **ANY replica failure blocks all writes.** Dangerous. |

### The failure mode to understand

```
⭐ If the required number of synchronous standbys is unavailable,
   COMMITS BLOCK. Indefinitely. The primary appears hung.

  synchronous_standby_names = 'ANY 1 (rep1)'
  rep1 dies.
  → every COMMIT hangs. The application times out. The system is DOWN,
    even though the primary is perfectly healthy.
```

**This is a deliberate CP choice** (Chapter 05 §5.4): the system refuses to accept a write it cannot guarantee, rather than accepting one it might lose.

```sql
-- ⭐ The escape hatch, to use during an incident:
ALTER SYSTEM SET synchronous_standby_names = '';
SELECT pg_reload_conf();
-- Commits resume immediately, now with local durability only.
-- ⭐ Put this in the runbook. Under pressure, nobody remembers that
--    it takes effect on reload and needs no restart.
```

> **Always configure `ANY N` with more standbys than N.** `ANY 1 (rep1, rep2)` survives one replica dying; `ANY 1 (rep1)` does not. That one extra name is the difference between a degraded system and an outage.

---

## 24. Logical decoding: how CDC really works

The mechanism behind Debezium, logical replication, and every CDC pipeline in Chapter 12.

```
                  ┌──────────────────────────────────────────┐
  WAL (physical)  │ Heap/INSERT blk 4821 off 12 ...           │
                  │ Btree/INSERT_LEAF ...                     │
                  │ Heap/UPDATE blk 991 ...                   │
                  │ Transaction/COMMIT                        │
                  └───────────────────┬──────────────────────┘
                                      │
                         ⭐ LOGICAL DECODING
                    (reassemble physical records into
                     logical row changes, per transaction,
                     ⭐ in COMMIT ORDER)
                                      │
                                      ▼
                  ┌──────────────────────────────────────────┐
                  │ OUTPUT PLUGIN                             │
                  │  pgoutput (built in) | wal2json |         │
                  │  decoderbufs | test_decoding              │
                  └───────────────────┬──────────────────────┘
                                      ▼
                  {"op":"u","table":"orders",
                   "before":{"status":"pending"},
                   "after": {"status":"paid"}}
```

### The requirements

```sql
-- 1. ⭐ wal_level must be 'logical' (a RESTART is required)
ALTER SYSTEM SET wal_level = 'logical';
-- 2. Slots available
ALTER SYSTEM SET max_replication_slots = 10;
ALTER SYSTEM SET max_wal_senders = 10;
```

### Three properties that shape any CDC design

```
1. ⭐ ONLY COMMITTED TRANSACTIONS ARE DECODED, IN COMMIT ORDER.
   Aborted transactions never appear. Changes appear in the order
   transactions COMMITTED, not the order they started.

2. ⭐ Before PG14, a transaction was fully BUFFERED before streaming.
   A single transaction updating 10 million rows buffered all of it
   (spilling to disk) before emitting anything.
   → an enormous latency spike, and a disk usage spike.
   PG14+ can stream in-progress transactions (streaming = on).

3. ⭐ DDL IS NOT DECODED.
   ALTER TABLE does not appear in the logical stream. A downstream
   consumer discovers schema changes only by the data suddenly having
   different columns. This is why Debezium pipelines break on migrations,
   and why an ACL downstream of CDC is mandatory (Chapter 24 §24.5).
```

### Creating and consuming a slot

```sql
-- Create
SELECT pg_create_logical_replication_slot('my_cdc', 'pgoutput');

-- Consume (test_decoding is useful for inspection)
SELECT pg_create_logical_replication_slot('inspect', 'test_decoding');
UPDATE orders SET status = 'paid' WHERE id = 1;

SELECT lsn, xid, data FROM pg_logical_slot_peek_changes('inspect', NULL, NULL);
--    lsn     |  xid   |                      data
-- -----------+--------+-------------------------------------------------
--  2A/C14821 | 847291 | BEGIN 847291
--  2A/C14850 | 847291 | table public.orders: UPDATE: id[bigint]:1
--            |        |   status[text]:'paid'
--  2A/C14890 | 847291 | COMMIT 847291

-- ⭐ peek does NOT advance the slot; get DOES.
--    Using get_changes in a monitoring query will silently break your
--    CDC pipeline by consuming its data.
```

---

## 25. REPLICA IDENTITY — the setting that breaks Debezium

```sql
SELECT relname, relreplident FROM pg_class WHERE relname = 'orders';
-- relreplident: 'd' = default (primary key)
--               'n' = nothing
--               'f' = ⭐ full (the entire old row)
--               'i' = a specific unique index
```

### What each gives you

| Setting | UPDATE emits | DELETE emits | Cost |
|---------|-------------|--------------|------|
| `DEFAULT` | New row + **PK only** as `before` | **PK only** | Low |
| `FULL` | New row + ⭐ **complete old row** | ⭐ **Complete old row** | ⭐ **High — the entire old row is written to WAL** |
| `NOTHING` | New row only | ⭐ **Nothing usable** | Lowest |
| `USING INDEX x` | New row + the index's columns | Index columns | Medium |

### The failure everyone hits

```
⭐ A table with NO PRIMARY KEY and REPLICA IDENTITY DEFAULT:

  UPDATE that_table SET x = 1 WHERE y = 2;

  ERROR: cannot update table "that_table" because it does not have a
         replica identity and publishes updates
  HINT:  To enable updating the table, set REPLICA IDENTITY using
         ALTER TABLE.
```

```sql
-- ⭐ The fix — choose deliberately:

-- Best: add a primary key (you should have one anyway)
ALTER TABLE that_table ADD PRIMARY KEY (id);

-- Or use an existing unique index
ALTER TABLE that_table REPLICA IDENTITY USING INDEX that_table_uniq_idx;

-- Or FULL — but understand the cost
ALTER TABLE that_table REPLICA IDENTITY FULL;
```

### The FULL trap ⭐

```
REPLICA IDENTITY FULL writes the ENTIRE OLD ROW to WAL on every
UPDATE and DELETE.

  A table with a 2 KB jsonb column:
    DEFAULT: ~150 bytes of WAL per UPDATE
    FULL:    ⭐ ~2,150 bytes of WAL per UPDATE  (14×)

At 1,000 updates/sec: 150 KB/s → ⭐ 2.1 MB/s, purely from the identity setting.

⭐ AND on the SUBSCRIBER side, matching rows without a unique index
   requires a SEQUENTIAL SCAN per change — logical replication apply
   becomes O(n²). (PG16 improved this by allowing non-unique indexes
   to be used, but a proper key is still far better.)
```

> **Teams enable `FULL` because Debezium wanted `before` images for change events, then discover their WAL volume tripled and their replica lag became unbounded.** If you genuinely need before-images, enable `FULL` on the *specific tables* that need them, never globally — and measure the WAL impact first.

---

## 26. Monitoring WAL

```sql
-- ═══ PG14+: the WAL statistics view ═══
SELECT wal_records, wal_fpi,
       pg_size_pretty(wal_bytes) AS wal_bytes,
       round(100.0 * wal_fpi / NULLIF(wal_records,0), 1) AS pct_full_page,  -- ⭐
       wal_buffers_full,                                                     -- ⭐
       wal_write, wal_sync,
       round(wal_write_time::numeric, 0) AS write_ms,
       round(wal_sync_time::numeric, 0)  AS sync_ms,
       stats_reset
FROM pg_stat_wal;
```

```
⭐ pct_full_page > 30%   → checkpoints too frequent (§11), or
                            wal_compression is off (§8)
⭐ wal_buffers_full > 0  → raise wal_buffers
⭐ sync_ms / wal_sync    → your average fsync latency. This IS your
                            commit latency floor.
```

### The alerts

```promql
# ⭐ 1. fsync latency — the master metric (Deep Dive 01 §12)
rate(pg_stat_wal_wal_sync_time[5m]) / rate(pg_stat_wal_wal_sync[5m]) > 10

# ⭐ 2. Requested checkpoints — max_wal_size too small
rate(pg_stat_bgwriter_checkpoints_req[1h]) > 0

# ⭐ 3. Backends doing their own fsyncs
pg_stat_bgwriter_buffers_backend_fsync > 0

# ⭐ 4. Replication slot retention
pg_replication_slot_retained_bytes > 10e9

# ⭐ 5. Inactive slots
pg_replication_slots_active == 0

# ⭐ 6. Replica replay lag (the user-visible number)
pg_replication_lag_seconds > 30

# 7. Archive failures
pg_stat_archiver_failed_count > 0

# 8. pg_wal directory size
pg_wal_size_bytes / node_filesystem_size_bytes > 0.7
```

### Archiving

```sql
SELECT archived_count, last_archived_wal, last_archived_time,
       failed_count, last_failed_wal, last_failed_time
FROM pg_stat_archiver;
```

```ini
archive_mode = on
archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'
#   ⭐ The `test ! -f` guard is essential: the command MUST NOT overwrite
#      an existing file, and MUST return non-zero on failure.
#      A command that returns 0 on failure silently destroys your ability
#      to recover.
archive_timeout = '300s'
#   ⭐ Force a segment switch every 5 minutes even if it is not full,
#      bounding RPO on a low-traffic system. Costs a partly-empty
#      16 MB segment each time.
```

> **Use a real tool (pgBackRest, WAL-G) rather than a hand-written `archive_command`.** They handle compression, encryption, retention, parallelism, and — critically — they *verify* that what was archived can be read back.

---

## 27. The tuning summary

```sql
-- ═══ 1. CHECKPOINTS — the highest-impact change (§11, §12) ═══
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET max_wal_size = '16GB';         -- size from measurement
ALTER SYSTEM SET min_wal_size = '2GB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;

-- ═══ 2. WAL EFFICIENCY (§8) ═══
ALTER SYSTEM SET wal_compression = 'lz4';       -- ⭐ near-free win
ALTER SYSTEM SET wal_buffers = '64MB';

-- ═══ 3. DURABILITY (§13) ═══
ALTER SYSTEM SET synchronous_commit = 'on';     -- global default
--   ⭐ then relax per-role/per-transaction where appropriate
ALTER ROLE analytics_writer SET synchronous_commit = 'off';

-- ═══ 4. REPLICATION SAFETY (§22) ═══
ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';   -- ⭐ bounds disk risk
ALTER SYSTEM SET wal_keep_size = '2GB';

-- ═══ 5. ENABLE RECOVERY TOOLING (§20) — do this BEFORE you need it ═══
ALTER SYSTEM SET wal_log_hints = on;            -- ⭐ requires restart
--   (or enable data checksums, which also satisfies pg_rewind)

-- ═══ 6. LOGICAL REPLICATION, if used (§24) ═══
ALTER SYSTEM SET wal_level = 'logical';         -- requires restart
ALTER SYSTEM SET max_replication_slots = 10;
ALTER SYSTEM SET max_wal_senders = 10;

-- ═══ 7. ARCHIVING (§26) ═══
ALTER SYSTEM SET archive_mode = on;             -- requires restart
ALTER SYSTEM SET archive_timeout = '300s';

-- ═══ 8. OBSERVABILITY ═══
ALTER SYSTEM SET track_io_timing = on;
ALTER SYSTEM SET track_wal_io_timing = on;      -- PG14+
ALTER SYSTEM SET log_checkpoints = on;          -- ⭐ on by default in PG15+

SELECT pg_reload_conf();
```

---

## 28. What an architect takes from this

**1. Commit latency *is* WAL fsync latency.** Nothing else is on the critical path. This is why disk quality dominates PostgreSQL write performance, and why Deep Dive 01's etcd fsync metric and this one are the same metric.

**2. The default `max_wal_size = 1GB` is wrong for any busy system**, and the resulting checkpoint loop can produce 30–70× more WAL than necessary. `"checkpoints are occurring too frequently"` in the log is the highest-value line PostgreSQL prints.

**3. Full-page writes explain the sawtooth** in WAL volume, replication lag and commit latency. Longer checkpoint intervals plus `wal_compression = lz4` is usually a 20–40× reduction.

**4. `synchronous_commit` is a per-transaction lever, not a global switch.** Relaxing it for loss-tolerant writes is a legitimate order-of-magnitude optimisation that does not risk corruption — only a bounded window of committed transactions.

**5. PostgreSQL has no UNDO phase**, which is why rollback is O(1) and recovery is one pass. The cost is paid as bloat and VACUUM instead. Knowing which side of that trade you are on tells you which incidents to prepare for.

**6. A base backup without its WAL is not a backup.** The file copy is inconsistent by design; only WAL replay makes it consistent.

**7. Timelines are where PITR goes wrong.** After any promotion, every replica is on the wrong branch. Plan `pg_rewind` or rebuilds *before* the incident — and enable `wal_log_hints` or checksums now, because you cannot enable them during one.

**8. An abandoned replication slot will fill your disk and shut down the primary.** `max_slot_wal_keep_size` bounds it; alerting on inactive slots prevents it; a decommissioning runbook fixes the root cause. A *logical* slot additionally pins the xmin horizon, so it causes bloat and wraparound risk too.

**9. `REPLICA IDENTITY FULL` can triple your WAL volume** and make subscriber apply O(n²). Enable it per table, never globally, and measure first.

**10. Logical decoding does not decode DDL.** Every CDC pipeline breaks on schema changes unless there is an ACL downstream translating the raw stream into a stable contract (Chapter 24 §24.5).

**11. `hot_standby_feedback` trades replica query cancellations for primary bloat.** There is no third option. Choose deliberately, and bound it with a `statement_timeout` on the replica.

---

## Exercises

1. Run `pg_waldump --stats=record` over an hour of your production WAL. What fraction is full-page images? What is the single largest record type?
2. Measure your WAL generation rate over 10 minutes. Size `max_wal_size` for a 15-minute checkpoint interval using §11's rule.
3. Check `checkpoints_req` vs `checkpoints_timed` on a production system. If the ratio is bad, compute how much WAL the storm is costing you.
4. Enable `wal_compression = lz4` on a test system and measure the WAL volume change for an identical workload.
5. Explain, to someone who knows what a transaction is, why a torn page cannot be repaired by a delta WAL record.
6. Benchmark single-row inserts with `synchronous_commit` set to `on` and `off`. Explain the difference in terms of §4's write path.
7. Perform a PITR on a test system to a named restore point. Verify before promoting. Then examine the `.history` file and explain what it records.
8. After that promotion, attempt to attach a replica that was following the original timeline. Reproduce the timeline error and fix it with `pg_rewind`.
9. Check whether `wal_log_hints` or `data_checksums` is enabled on your production cluster. If neither is, write the plan to enable one.
10. Create an inactive replication slot on a test system, generate WAL, and watch `pg_wal` grow. Then set `max_slot_wal_keep_size` and observe the slot being invalidated.
11. Set `REPLICA IDENTITY FULL` on a table with a large column and measure the WAL difference for 10,000 updates.
12. Estimate your crash recovery time from `max_wal_size` and a measured replay rate. Compare against your stated RTO.
13. Write the runbook entry for "commits are hanging and `pg_stat_replication` is empty". Include the exact commands.
14. Explain why an abandoned *logical* replication slot is a more serious incident than an abandoned *physical* one. Name all three consequences.

---

**Next in this series:** Deep Dive 08 — Transactions, Locking and SSI

**Back to:** [Deep Dives](README.md) · [Chapter 09](../09-database-architecture.md) · [The Map](../README.md)
