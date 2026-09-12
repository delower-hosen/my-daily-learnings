# Deep Dive 09 — LSM Trees and Write-Optimised Storage

**Prerequisite:** [Chapter 10](../10-nosql-architecture.md) · [Deep Dive 05](05-btrees-indexes-and-access-methods.md)

**What the map said:** *"Cassandra is built for enormous write throughput. Deletes write tombstones, and a delete-heavy workload is an anti-pattern."*

**What this deep dive does:** derives the LSM design from the write-amplification problem B-trees have, builds an SSTable byte by byte, walks the read path through bloom filters and level files, gives the amplification arithmetic for each compaction strategy, explains tombstones and traces the Cassandra "queue anti-pattern" to the exact point where queries start timing out, covers write stalls and compaction debt, and ends with a decision procedure for B-tree versus LSM.

---

## Contents

```
1.  The problem: B-tree write amplification
2.  The LSM idea: never update in place
3.  The memtable
4.  The SSTable, byte by byte
5.  The write path
6.  The read path ⭐ — and why it is the hard part
7.  Bloom filters: the maths
8.  The three amplifications and the RUM conjecture ⭐
9.  Compaction strategy 1 — size-tiered
10. Compaction strategy 2 — leveled ⭐
11. Compaction strategy 3 — time-window
12. Compaction strategy 4 — FIFO and universal
13. Amplification arithmetic, compared
14. Tombstones ⭐ — the delete problem
15. Traced scenario — Cassandra tombstone hell
16. Write stalls and compaction debt ⭐
17. Caches: block, row and page
18. The commit log
19. Key-value separation (WiscKey)
20. RocksDB: the tuning that matters
21. Where LSM engines are actually used
22. B-tree vs LSM: the decision
23. Monitoring an LSM system
24. What an architect takes from this
```

---

## 1. The problem: B-tree write amplification

Start from what Deep Dive 05 established, and count the bytes.

```
UPDATE one 100-byte row in a B-tree-backed database:

  1. Read the 8 KB leaf page              (random read)
  2. Modify 100 bytes in memory
  3. ⭐ WAL: full-page image if first touch since checkpoint → 8 KB
            (Deep Dive 07 §6)
  4. ⭐ Eventually write the whole 8 KB page back    (random write)
  5. Plus the same for every secondary index touched

  ⭐ WRITE AMPLIFICATION for a 100-byte logical change:
     8 KB (WAL FPI) + 8 KB (page) = 16 KB minimum
     = 160× amplification, before indexes.
```

**And the writes are random.** Page 4,821 then page 991,203 then page 12. On a spinning disk that is catastrophic; on SSD it is merely expensive — and it causes write amplification *inside the drive too*, because the SSD's flash translation layer must garbage-collect erase blocks.

### The insight

```
⭐ Random writes are expensive. Sequential writes are cheap.
   On NVMe: ~50k random 8 KB writes/sec vs ~3 GB/s sequential.
   That is roughly a 7× throughput difference — and a much larger
   difference in device wear.

⭐ So: what if we NEVER wrote randomly?
   What if every write were an APPEND?
```

That question is the LSM tree. **It trades read performance and background I/O for write performance**, and the entire design follows from making that trade well.

---

## 2. The LSM idea: never update in place

**Log-Structured Merge tree** (O'Neil et al., 1996).

```
┌─────────────────────────────────────────────────────────────────┐
│ MEMORY                                                          │
│   ┌──────────────┐   ┌───────────────────┐                      │
│   │  MEMTABLE    │   │ IMMUTABLE MEMTABLE│  (being flushed)     │
│   │  (mutable,   │   │                   │                      │
│   │   sorted)    │   │                   │                      │
│   └──────────────┘   └─────────┬─────────┘                      │
└──────────────────────────────────┼──────────────────────────────┘
                                   │ flush (sequential write)
┌──────────────────────────────────▼──────────────────────────────┐
│ DISK                                                            │
│  L0  ┌────┐ ┌────┐ ┌────┐ ┌────┐   ⭐ files here OVERLAP        │
│      └────┘ └────┘ └────┘ └────┘                                │
│              │ compaction (merge + rewrite)                     │
│  L1  ┌──────────┐┌──────────┐┌──────────┐  non-overlapping     │
│      └──────────┘└──────────┘└──────────┘                       │
│              │                                                   │
│  L2  ┌──────────────────────────────────────┐  10× larger       │
│      └──────────────────────────────────────┘                    │
│  ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

### The three rules

```
1. ⭐ ALL WRITES GO TO MEMORY (the memtable) and to an append-only log.
   No random disk writes on the write path. Ever.

2. ⭐ WHEN THE MEMTABLE IS FULL, it is written to disk as ONE
   IMMUTABLE, SORTED FILE (an SSTable), in one sequential write.

3. ⭐ BACKGROUND COMPACTION merges SSTables, discarding superseded
   versions and deleted keys.
```

**The consequence that defines everything else:** a key can exist in *many* SSTables with *different* values. The newest wins. So a read may have to check many files — which is why §6 and §7 exist.

---

## 3. The memtable

```
Typically a SKIP LIST — a probabilistic sorted structure with
O(log n) search and, crucially, ⭐ lock-free concurrent insertion.

   level 3  HEAD ─────────────────────────────► 34 ──────► NIL
   level 2  HEAD ──────────► 12 ──────────────► 34 ──────► NIL
   level 1  HEAD ───► 7 ───► 12 ───► 21 ──────► 34 ─► 51 ─► NIL
   level 0  HEAD ─► 3─► 7 ─► 12 ─► 19─► 21 ─► 28─► 34 ─► 51 ─► NIL

Each node is promoted to the next level with probability 1/2.
Expected height: log₂(n). Search: start at the top, drop down.
```

### Why a skip list rather than a B-tree or a hash map

```
✅ SORTED — required, because the flush must produce a sorted SSTable
✅ ⭐ Concurrent inserts need no global lock (CAS on individual pointers)
✅ Simple to implement correctly, unlike a concurrent B-tree
❌ Worse cache locality than a B-tree — acceptable, because it is in RAM
```

**Alternatives in real systems:** RocksDB offers a skip list (default), a hash-skip-list, and a vector memtable. Cassandra uses a concurrent skip-list map. ScyllaDB uses a B-tree-ish structure tuned for its shard-per-core model.

### The lifecycle

```
1. Writes go to the ACTIVE memtable (and the commit log, §18)
2. It reaches write_buffer_size (RocksDB default 64 MB)
3. ⭐ It becomes IMMUTABLE. A new active memtable is created instantly.
4. A background thread flushes the immutable memtable to an L0 SSTable
5. Once flushed and fsynced, the corresponding commit log can be recycled

⭐ max_write_buffer_number (default 2) bounds how many immutable
   memtables may exist. If flushing cannot keep up and the limit is
   reached, WRITES STALL (§16).
```

---

## 4. The SSTable, byte by byte

**Sorted String Table** — an immutable, sorted key-value file. The format below is LevelDB/RocksDB's; Cassandra's differs in detail but not in structure.

```
┌───────────────────────────────────────────────────────────────┐
│ DATA BLOCK 0      (~4 KB)  keys a..f, sorted                  │
│ DATA BLOCK 1      (~4 KB)  keys g..m                          │
│ DATA BLOCK 2      (~4 KB)  keys n..s                          │
│ ...                                                            │
├───────────────────────────────────────────────────────────────┤
│ FILTER BLOCK      ⭐ the bloom filter (§7)                     │
├───────────────────────────────────────────────────────────────┤
│ INDEX BLOCK       ⭐ last key of each data block → block offset│
│                      "f" → offset 0,  "m" → 4096, "s" → 8192  │
├───────────────────────────────────────────────────────────────┤
│ METAINDEX BLOCK   pointers to the filter and other meta blocks │
├───────────────────────────────────────────────────────────────┤
│ FOOTER (fixed 48 B) → offsets of the index and metaindex       │
└───────────────────────────────────────────────────────────────┘
```

### Inside a data block: prefix compression and restart points

```
Keys in a block share prefixes (they are sorted), so each entry stores
only the DIFFERENCE from the previous key:

  entry:  [shared_len][unshared_len][value_len][unshared_key][value]

  "user:1000:name"   → shared=0,  unshared=14, "user:1000:name"
  "user:1000:email"  → ⭐ shared=10, unshared=5,  "email"
  "user:1000:phone"  → ⭐ shared=10, unshared=5,  "phone"
  "user:1001:name"   → shared=8,  unshared=6,  "1:name"

⭐ RESTART POINTS every 16 entries (block_restart_interval) store a
   FULL key, so binary search within the block is possible. Without
   them you would have to scan from the start of the block.
```

**This is why key design matters enormously in LSM systems.** Keys with a long common prefix (`tenant:123:user:456:...`) compress extremely well. Random UUIDs as keys compress not at all — the same lesson as Deep Dive 05 §11, appearing in a completely different mechanism.

### Reading it

```
⭐ THE FILE IS IMMUTABLE. It is written once, sequentially, and never
   modified. It is either read or deleted.

Consequences:
   ✅ No locking needed for reads — ever
   ✅ Trivially cacheable, checksummable, and safe to replicate by copying
   ✅ Compression works well (whole blocks compress, no in-place updates)
   ❌ ⭐ An update cannot modify it — the new value goes in a NEWER file,
      and the old one lingers until compaction
```

---

## 5. The write path

```
PUT("user:1000:name", "Delower")

1. ⭐ Append to the COMMIT LOG (WAL), fsync if configured   (§18)
2. Insert into the active MEMTABLE (in memory, sorted)
3. ⭐ RETURN SUCCESS TO THE CLIENT

   Total durable I/O: ONE sequential append.
```

```
DELETE("user:1000:name")

1. ⭐ Append a TOMBSTONE to the commit log and memtable.
   NOT a removal — a MARKER saying "this key is deleted as of now".  (§14)

UPDATE("user:1000:name", "D. Hosen")

1. ⭐ Append a NEW VERSION. The old one is untouched, in an older file.
```

**Every operation is an append.** There is no read-modify-write anywhere on the write path, which is why LSM write throughput is so high — and why the read path has to do so much work.

```
⭐ WRITE AMPLIFICATION ON THE WRITE PATH: ~1×
   (the commit log entry, plus eventually one sequential memtable flush)

⭐ TOTAL WRITE AMPLIFICATION INCLUDING COMPACTION: 10-30×  (§13)
   The cost is DEFERRED to the background, not eliminated.
```

That deferral is the whole design. It converts foreground random I/O into background sequential I/O, which is a far better use of the device — and it is also why compaction becomes the operational problem (§16).

---

## 6. The read path ⭐ — and why it is the hard part

```
GET("user:1000:name")

1. ⭐ ACTIVE MEMTABLE          → found? return (newest wins)
2. ⭐ IMMUTABLE MEMTABLES      → found? return
3. ⭐ L0 SSTables — files OVERLAP, so check EVERY ONE,
                    newest first
4. ⭐ L1..Ln — files within a level are NON-OVERLAPPING, so
              binary-search the level's file list to find the ONE
              candidate file, then check it

   For each SSTable checked:
     a) ⭐ BLOOM FILTER — "definitely not here" → skip the file entirely
     b) INDEX BLOCK    → which data block might contain the key
     c) DATA BLOCK     → read (from block cache, or from disk), binary search
```

### Why L0 is special and problematic

```
⭐ L0 files come straight from memtable flushes, so they can contain
   OVERLAPPING key ranges. There is no way to know which one has the key.

   → every L0 file must be checked.

   level0_file_num_compaction_trigger (default 4) keeps this small.
   If compaction falls behind and L0 grows to 30 files, ⭐ read latency
   degrades sharply — and this is the first symptom of compaction debt (§16).
```

### The read amplification arithmetic

```
Leveled compaction, 7 levels, bloom filters at 1% false positive:

  memtable + immutable:        0 disk reads
  L0 (4 files):                4 bloom checks, ~0.04 expected disk reads
  L1..L6 (1 candidate each):   6 bloom checks, ~0.06 expected disk reads
  ⭐ plus 1 read for the level that actually has the key
                               ─────────────────────────────
  ⭐ ~1.1 disk reads for a point lookup that HITS.

⭐ BUT for a key that does NOT exist:
  every level must be checked, and only bloom filters save you.
  ~10 bloom checks × 1% = 0.1 expected disk reads. Still good.

⭐ AND FOR A RANGE SCAN — bloom filters DO NOT HELP AT ALL (§7).
  Every level must be opened and merged.
  ⭐ Range scans are LSM's weakness. 10+ file reads, merged with a heap.
```

> **This is the fundamental asymmetry: LSM point lookups are nearly as good as B-tree point lookups (thanks to bloom filters), but LSM range scans are substantially worse.** If your workload is dominated by range scans, that is a strong argument for a B-tree.

---

## 7. Bloom filters: the maths

The structure that makes LSM reads viable.

```
A bloom filter answers ONE question:
    "Is this key DEFINITELY NOT in this SSTable?"

    ⭐ NO FALSE NEGATIVES. If it says "not present", it is not present.
    ⭐ FALSE POSITIVES possible. If it says "maybe", you must check.
```

### How it works

```
A bit array of m bits, k hash functions.

INSERT key:  set bits h₁(key), h₂(key), ..., h_k(key)
QUERY key:   if ANY of those bits is 0 → ⭐ DEFINITELY NOT PRESENT
             if ALL are 1              → maybe present (check the file)

    bits:  0 1 0 0 1 1 0 1 0 0 1 0 0 1 0 0
                ▲     ▲         ▲
           h₁("abc") h₂("abc") h₃("abc")   all 1 → "maybe"
```

### The formulas

```
Given n keys and m bits:

  ⭐ optimal k = (m/n) × ln 2 ≈ 0.693 × (m/n)

  ⭐ false positive rate  p ≈ (1 − e^(−kn/m))^k

  ⭐ bits per key needed for rate p:   m/n = −ln(p) / (ln 2)²
```

```
  p = 10%    → 4.8 bits/key
  p = 1%     → ⭐ 9.6 bits/key   (RocksDB default: 10 bits/key)
  p = 0.1%   → 14.4 bits/key
  p = 0.01%  → 19.2 bits/key
```

### Sizing in practice

```
1 billion keys at 10 bits/key = 10 Gbit = ⭐ 1.25 GB of bloom filters.

⭐ THEY MUST BE IN MEMORY. A bloom filter read from disk defeats its
   entire purpose — you have done a disk read to avoid a disk read.

So bloom filter memory is a HARD capacity requirement that scales with
KEY COUNT, not data size. A billion tiny keys costs the same bloom
memory as a billion large ones.
```

```
⭐ THE CRITICAL LIMITATION:
   Bloom filters answer "does key K exist?" — a POINT query.
   They CANNOT answer "are there any keys between A and B?"

   → Range scans get no benefit whatsoever.
   → Every level must be opened and merged. (§6)
```

### Ribbon filters (the modern improvement)

```
RocksDB 6.15+ offers RIBBON FILTERS as an alternative:
   ⭐ ~30% less memory for the same false-positive rate
   ❌ ~3× more CPU to construct (during compaction)
   ✅ Same or slightly better query CPU

⭐ A good trade when bloom memory is your constraint, which it often is
   on key-heavy workloads. Configurable per level — many deployments use
   ribbon filters for the large lower levels and bloom for the hot upper ones.
```

---

## 8. The three amplifications and the RUM conjecture ⭐

Every storage engine is characterised by three numbers.

```
⭐ WRITE AMPLIFICATION = bytes written to disk / bytes written by the user
⭐ READ  AMPLIFICATION = disk reads per logical read
⭐ SPACE AMPLIFICATION = bytes on disk / bytes of live data
```

### The RUM conjecture

> **RUM conjecture** (Athanassoulis et al., 2016): for any data structure, you can optimise for at most **two** of **R**ead overhead, **U**pdate overhead, and **M**emory (space) overhead. Improving one of the three necessarily worsens at least one other.

```
                        READ
                         ▲
                        ╱ ╲
                   B-tree   ╲
                      ╱      ╲
                     ╱  ⭐ you  ╲
                    ╱   pick a   ╲
                   ╱   point in   ╲
                  ╱   this space   ╲
                 ╱                  ╲
         LSM ───────────────────── hash index
       UPDATE                        MEMORY/SPACE
```

**This is not a limitation of current engineering — it is a proven trade-off**, and it explains why there is no universally best storage engine and never will be. Every choice in §9–12 is a different point in this space.

### Where the engines sit

| Engine | Write amp | Read amp | Space amp |
|--------|-----------|----------|-----------|
| **B-tree** | ⭐ High (10–100×, page + WAL FPI) | ⭐ **Low (~1–4)** | Medium (~1.3, fragmentation) |
| **LSM, leveled** | ⭐ High (10–30×) | Medium (~1–10) | ⭐ **Low (~1.1)** |
| **LSM, size-tiered** | ⭐ **Low (~4–10×)** | High (~10–50) | ⭐ High (~2×+) |
| **Hash index** | Low | ⭐ **Lowest (1)** | High, and ⭐ no range scans |

> **Read the table as a menu, not a ranking.** Size-tiered compaction is chosen precisely when you want minimum write amplification and can afford the space. Leveled is chosen when space matters more. Neither is "better".

---

## 9. Compaction strategy 1 — size-tiered

**Cassandra's default (`STCS`). RocksDB calls a variant of it "universal".**

```
RULE: when N SSTables of SIMILAR SIZE exist, merge them into one
      larger SSTable.  (Cassandra: min_threshold = 4)

  4 × 64 MB files    →  merge  →  1 × ~256 MB file
  4 × 256 MB files   →  merge  →  1 × ~1 GB file
  4 × 1 GB files     →  merge  →  1 × ~4 GB file
```

```
                    ┌────────────────────────────────┐  4 GB
                    └────────────────────────────────┘
              ┌───────────┐ ┌───────────┐               1 GB each
              └───────────┘ └───────────┘
        ┌───┐ ┌───┐ ┌───┐                                256 MB each
        └───┘ └───┘ └───┘
  ┌─┐ ┌─┐ ┌─┐                                            64 MB each
  └─┘ └─┘ └─┘
```

### The trade-offs

```
✅ ⭐ LOW WRITE AMPLIFICATION. Each byte is rewritten roughly
   log_N(total/memtable) times ≈ 4-10× total.

❌ ⭐ HIGH READ AMPLIFICATION. A key may exist in a file at EVERY size
   tier — so a read may check 10-20 files.

❌ ⭐ HIGH SPACE AMPLIFICATION, and it is worse than it looks:
   • superseded versions live in older tiers until a big merge happens
   • ⭐ MERGING 4 × 1 GB FILES NEEDS 4 GB OF FREE SPACE for the output,
     while the inputs still exist.
   → ⭐ YOU NEED ~50% FREE DISK, and a large compaction can briefly
     need much more.
```

> **The "Cassandra needs 50% free disk" rule comes from here.** It is not conservatism — a size-tiered compaction of your largest tier genuinely requires space for a full copy. Running a Cassandra node above ~70% disk is how you get a node that cannot compact, which makes reads slower, which makes everything worse.

---

## 10. Compaction strategy 2 — leveled ⭐

**RocksDB's default (`LCS` in Cassandra, "level" style in RocksDB).**

```
L0: files from memtable flushes. ⭐ OVERLAPPING key ranges.
L1: ⭐ NON-OVERLAPPING files, total size ~256 MB
L2: non-overlapping, total ~2.5 GB      (10× L1)
L3: non-overlapping, total ~25 GB       (10× L2)
...each level is 10× the previous (max_bytes_for_level_multiplier)
```

```
L0  ┌──┐┌──┐┌──┐┌──┐          overlapping
    └──┘└──┘└──┘└──┘
L1  ┌────┐┌────┐┌────┐        a..f | g..m | n..z   ⭐ DISJOINT
    └────┘└────┘└────┘
L2  ┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐  a..c|d..f|g..i|...   ⭐ DISJOINT
    └──┘└──┘└──┘└──┘└──┘└──┘
```

### How compaction works here

```
When L_n exceeds its target size:
  1. Pick ONE file from L_n
  2. ⭐ Find all files in L_(n+1) whose key ranges OVERLAP it
     (typically ~10 files, since L_(n+1) is 10× denser)
  3. Merge them all, write the result into L_(n+1)
  4. Delete the inputs

⭐ WRITE AMPLIFICATION PER LEVEL: ~10 (you rewrote 1 file plus 10 files
   to produce 10 files, for 1 file's worth of new data).

⭐ TOTAL: ~10 per level × 6-7 levels = 60-70× in the worst case,
   commonly measured at 10-30× in practice.
```

### The trade-offs

```
✅ ⭐ LOW SPACE AMPLIFICATION (~1.1×). Because levels are non-overlapping,
   a key exists at most once per level, and the lower levels hold
   ~90% of the data with almost no duplication.

✅ ⭐ LOW READ AMPLIFICATION. At most one file per level needs checking
   (plus all of L0).

❌ ⭐ HIGH WRITE AMPLIFICATION. Every byte is rewritten many times as
   it migrates down the levels.

❌ ⭐ MORE CONSTANT BACKGROUND I/O. Compaction runs continuously
   rather than in large bursts.
```

### Choosing between them

```
⭐ SIZE-TIERED when:
   • write-heavy, and disk is cheap
   • you can afford 50%+ free space
   • reads are mostly recent data (which lives in small, recent files)

⭐ LEVELED when:
   • read-heavy, or mixed
   • disk space matters (cloud storage cost, or dense nodes)
   • you need predictable read latency
   • ⭐ you have enough write bandwidth to absorb 10-30× amplification
```

---

## 11. Compaction strategy 3 — time-window

**`TWCS` in Cassandra. The correct choice for time-series with TTL — and one of the highest-value configuration decisions in that domain.**

```
RULE: group SSTables by the TIME WINDOW of the data they contain.
      Compact ONLY within a window. ⭐ NEVER merge across windows.

  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐
  │  2026-09-09  │ │  2026-09-10  │ │  2026-09-11  │ │ today  │
  │  (sealed)    │ │  (sealed)    │ │  (sealed)    │ │ active │
  └──────────────┘ └──────────────┘ └──────────────┘ └────────┘
```

### Why it is so much better for TTL data

```
With SIZE-TIERED or LEVELED, data from different days gets MERGED into
the same file. So when the oldest data expires:

  ⭐ You cannot just delete a file — it also contains newer data.
  ⭐ The expired rows become TOMBSTONES (§14) that must be compacted away.
  ⭐ You pay full compaction I/O to delete data you no longer want.

With TWCS:
  ⭐ An entire window expires at once → THE WHOLE FILE IS DROPPED.
     Zero compaction I/O. Zero tombstones. Instant space reclamation.
```

```sql
-- Cassandra
ALTER TABLE metrics WITH
  compaction = {'class': 'TimeWindowCompactionStrategy',
                'compaction_window_unit': 'DAYS',
                'compaction_window_size': 1}
  AND default_time_to_live = 2592000;   -- 30 days
```

```
⭐ REQUIREMENTS for TWCS to work:
   1. Data must be written roughly in time order (no large backfills)
   2. ⭐ TTL should be uniform — mixed TTLs within a window defeat it
   3. No updates to old data
   4. Aim for 20-30 windows total — too many windows means too many
      files to check on read
```

> **This is exactly the same insight as PostgreSQL partitioning by time (Deep Dive 05 §9):** if your deletion pattern is "drop everything older than N", organise the physical storage so that deletion becomes *dropping a file*, not *rewriting data*. The mechanism differs; the principle is identical.

---

## 12. Compaction strategy 4 — FIFO and universal

### FIFO

```
⭐ No merging at all. When total size exceeds a limit, DELETE the
   oldest SSTable.

Use: pure caches, or data where losing the oldest entries is acceptable
     by design. Zero write amplification beyond the flush.
     ❌ No deduplication — an updated key keeps all its old versions
        until its file ages out.
```

### Universal (RocksDB)

```
RocksDB's size-tiered variant, with finer control:
   • bounded space amplification (max_size_amplification_percent)
   • bounded number of sorted runs
   • can merge non-adjacent tiers

⭐ Use when you want size-tiered's low write amplification but need
   a hard ceiling on space.
```

---

## 13. Amplification arithmetic, compared

A concrete workload, so the numbers are real.

```
WORKLOAD
  100 GB of live data
  10,000 writes/sec × 1 KB = 10 MB/s of logical writes
  Memtable: 64 MB
```

### Leveled compaction

```
Levels: L0 (256 MB), L1 (256 MB), L2 (2.5 GB), L3 (25 GB), L4 (250 GB)
        → 100 GB of data fits within L4 → ⭐ 5 levels

WRITE AMPLIFICATION:
  memtable → L0:              1×
  L0 → L1:                   ~2×  (L0 files overlap L1 heavily)
  L1 → L2, L2 → L3, L3 → L4: ~10× each
  ⭐ TOTAL ≈ 1 + 2 + 10 + 10 + 10 = 33×

  ⭐ ACTUAL DISK WRITE RATE: 10 MB/s × 33 = 330 MB/s
     — sustained, in the background, forever.

SPACE AMPLIFICATION: ~1.1× → 110 GB on disk
READ AMPLIFICATION: ~1-2 disk reads per point lookup
```

```
⭐ NOTE THE 330 MB/s. That is a real, sustained requirement on the device.
   A drive rated at 500 MB/s sequential write is at 66% utilisation from
   compaction alone, before serving any reads. THIS is why LSM systems
   are provisioned on NVMe and why compaction throttling exists.
```

### Size-tiered compaction

```
WRITE AMPLIFICATION:
  Tiers: 64 MB → 256 MB → 1 GB → 4 GB → 16 GB → 64 GB → 256 GB
  ⭐ ~7 tiers, each byte rewritten once per tier ≈ 7×

  ⭐ ACTUAL DISK WRITE RATE: 10 MB/s × 7 = 70 MB/s   (5× less than leveled)

SPACE AMPLIFICATION: ~2× → ⭐ 200 GB on disk
  ⭐ plus transient space for a large merge: up to +64 GB
  ⭐ → provision ~300 GB for 100 GB of data

READ AMPLIFICATION: up to 7 files checked per lookup (bloom filters help)
```

### The summary table

| | Leveled | Size-tiered | Difference |
|---|---|---|---|
| Disk write rate | **330 MB/s** | 70 MB/s | ⭐ 4.7× |
| Disk space | **110 GB** | 200–300 GB | ⭐ 2–3× |
| Read amplification | ~1–2 | ~7 | ⭐ 4× |
| Device wear | High | Lower | |

> **You are trading device write bandwidth and endurance against disk capacity and read latency.** On cloud storage where you pay per GB *and* per provisioned IOPS, that calculation is genuinely non-obvious and worth doing with your actual prices.

---

## 14. Tombstones ⭐ — the delete problem

The hardest part of LSM, and the source of most operational pain in Cassandra.

### Why a delete cannot just delete

```
DELETE key "user:1000"

The key may exist in SSTables at 5 different levels. To actually remove
it you would have to find and rewrite all of them — ⭐ a random-write
operation, which is exactly what LSM exists to avoid.

⭐ SO: write a TOMBSTONE — a marker meaning "this key is deleted as of
   timestamp T" — into the memtable, like any other write.
```

```
On READ:
  L0 file:  "user:1000" → ⭐ TOMBSTONE (t=1000)      ← newest, wins
  L2 file:  "user:1000" → {"name": "Delower"} (t=500)
  L4 file:  "user:1000" → {"name": "D."} (t=100)

  ⭐ The read must still FIND AND READ all three, then discard them.
     A deleted key costs MORE to read than a live one.
```

### When can a tombstone be removed?

```
⭐ ONLY when compaction merges the tombstone together with EVERY
   SSTable that could contain an older version of that key.

   In leveled compaction, that means the tombstone must reach the
   BOTTOM level. That can take days.
```

### And in a distributed system, it is worse ⭐

```
⭐ THE ZOMBIE RESURRECTION PROBLEM:

  Node A, B, C hold replicas of key K.
  Node C is DOWN.
  DELETE K → tombstones written to A and B. C knows nothing.

  If A and B removed their tombstones immediately:
     C comes back up.
     Repair/read-repair compares: A has nothing, C has a value.
     ⭐ "Nothing" loses to "a value" — C's data is REPLICATED BACK.
     ⭐ THE DELETED ROW RETURNS FROM THE DEAD.
```

```
⭐ THE FIX: gc_grace_seconds (Cassandra default: 10 DAYS)

  Tombstones are retained for at least this long, guaranteeing they
  survive long enough to be replicated to any node that was down.

  ⭐ AND THE CONTRACT: you MUST run repair on every node more often
     than gc_grace_seconds, or a node down longer than that can
     resurrect data.
```

**This is the operational contract that people miss:** `gc_grace_seconds = 10 days` is not just "tombstones stick around" — it is a *requirement* that you complete a full repair cycle within 10 days. Lowering it without shortening your repair cycle is how you get resurrected data.

---

## 15. Traced scenario — Cassandra tombstone hell

The canonical LSM anti-pattern, traced to the exact failure.

```sql
-- ❌ The queue anti-pattern
CREATE TABLE job_queue (
    shard    int,
    job_id   timeuuid,
    payload  text,
    PRIMARY KEY (shard, job_id)    -- ⭐ all jobs for a shard in ONE partition
);
```

```
THE WORKLOAD:
  INSERT a job
  SELECT the oldest N jobs in the shard
  DELETE them after processing

  Rate: 1,000 jobs/sec, processed and deleted within seconds.
```

```
HOUR 1
  Partition "shard=0" contains:
    ~3.6 M rows inserted
    ~3.6 M tombstones (all processed and deleted)
    ⭐ ~0 live rows at any moment

  Query: SELECT * FROM job_queue WHERE shard = 0 LIMIT 10;

  ⭐ To find 10 live rows, Cassandra must SCAN FORWARD past every
     tombstone in the partition, in order, discarding each.

HOUR 1:   ~10,000 tombstones scanned per query.  Latency ~15 ms.
HOUR 4:   ~100,000 tombstones scanned.           Latency ~200 ms.
          ⭐ WARN: Read 10 live rows and 100000 tombstone cells
                   (see tombstone_warn_threshold)

HOUR 8:   ~500,000 tombstones.                   Latency ~2 s.

HOUR 12:  ⭐ 1,000,000 tombstones.
          ⭐ ERROR: Scanned over 100000 tombstones during query ...
                    (see tombstone_failure_threshold); query aborted

          ⭐ THE QUERY NOW FAILS. NOT SLOWLY — IT FAILS.
          And it will keep failing for gc_grace_seconds (10 days)
          unless you intervene.
```

### Why the obvious fixes do not work

```
❌ "Lower gc_grace_seconds to 1 hour"
   → risks zombie resurrection (§14). And tombstones still accumulate
     within that hour at 3.6 M/hour.

❌ "Run compaction more often"
   → compaction cannot remove a tombstone until it reaches the bottom
     level AND gc_grace has passed.

❌ "Add LIMIT" — already there. The problem is what is scanned before
   the limit is reached.
```

### The actual fixes

```
✅ 1. ⭐ DO NOT USE CASSANDRA AS A QUEUE.
      This is the documented answer. Use Kafka, SQS, RabbitMQ, or
      PostgreSQL's SELECT ... FOR UPDATE SKIP LOCKED (Deep Dive 08 §5).

✅ 2. ⭐ IF YOU MUST: use TTL instead of DELETE, plus TWCS (§11).
      Rows expire; whole SSTables are dropped; no tombstone scanning.
      CREATE TABLE ... WITH default_time_to_live = 3600
                        AND compaction = {'class': 'TimeWindowCompactionStrategy', ...}

✅ 3. ⭐ BUCKET THE PARTITION BY TIME so it never accumulates.
      PRIMARY KEY ((shard, hour_bucket), job_id)
      → old buckets are never queried, so their tombstones are never scanned.
```

> **The general LSM design rule this teaches: never build a data model where you repeatedly write and delete within the same partition.** The partition becomes a graveyard you must walk through on every read. This applies to Cassandra, HBase, and any LSM engine — the mechanism is universal.

---

## 16. Write stalls and compaction debt ⭐

The failure mode that takes LSM systems down.

```
⭐ COMPACTION DEBT: writes arrive faster than compaction can merge them.

  L0 accumulates files.
  Read amplification rises (every L0 file must be checked — §6).
  Reads get slower. Which uses I/O. Which slows compaction further.
  ⭐ A self-reinforcing spiral.
```

### RocksDB's throttle

```
level0_slowdown_writes_trigger = 20     ⭐ writes are DELAYED
level0_stop_writes_trigger     = 36     ⭐ writes are BLOCKED ENTIRELY

soft_pending_compaction_bytes_limit = 64 GB   → slow down
hard_pending_compaction_bytes_limit = 256 GB  → ⭐ stop
```

```
⭐ WHAT THE APPLICATION SEES:

  Normal:      write latency p99 = 2 ms
  Slowdown:    write latency p99 = 500 ms     ⭐ deliberate throttling
  Stop:        ⭐ WRITES BLOCK. Seconds. Then minutes.
               The application appears completely hung.
```

**This is deliberate back-pressure** (Chapter 05 §5.8) — the engine refusing work it cannot sustain, rather than accumulating unbounded debt. But from the application's perspective it is indistinguishable from an outage, and it arrives suddenly after a long period of apparent health.

### Diagnosing it

```sql
-- Cassandra
nodetool compactionstats
-- pending tasks: 1847              ⭐ COMPACTION DEBT
-- id  compaction type  keyspace  table   completed  total   unit  progress
-- ... Compaction       prod      events  4.21 GB    18.9 GB bytes 22.28%

nodetool tablestats prod.events
--   SSTable count: 284             ⭐ should be ~10-20 with LCS
--   SSTables in each level: [242/4, 31, 11, 0, 0, 0, 0]
--                            ^^^^^^  ⭐ 242 files in L0 (target: 4)
```

```
# RocksDB
rocksdb.num-files-at-level0        → ⭐ > 20 means trouble
rocksdb.estimate-pending-compaction-bytes
rocksdb.actual-delayed-write-rate  → ⭐ non-zero means throttling now
rocksdb.stall-micros               → ⭐ cumulative stall time
```

### The causes and the fixes

| Cause | Fix |
|-------|-----|
| ⭐ Compaction threads starved | Raise `concurrent_compactors` / `max_background_compactions` |
| ⭐ Compaction throughput throttled | Cassandra: `compaction_throughput_mb_per_sec` — **the default 16 MB/s is far too low for NVMe**; set 64–256 or 0 (unlimited) |
| Disk cannot sustain write amp (§13) | Faster disk, or switch to size-tiered to cut write amplification |
| Write rate genuinely exceeds capacity | Add nodes — this is a capacity problem, not a tuning one |
| Too-small memtable → too many L0 files | Raise `write_buffer_size` / `memtable_heap_space` |
| A huge single compaction blocking | Reduce `target_file_size_base` so compactions are smaller and more frequent |

```
⭐ THE MOST COMMON REAL CAUSE: compaction_throughput_mb_per_sec = 16
   (Cassandra's historical default, sized for spinning disks) on a node
   with NVMe capable of 2 GB/s. Compaction is throttled to 0.8% of the
   device's capability, falls behind permanently, and the cluster
   slowly degrades over weeks.
```

---

## 17. Caches: block, row and page

```
┌───────────────────────────────────────────────────────────────┐
│ ROW CACHE (Cassandra; off by default)                         │
│   ⭐ Caches ENTIRE PARTITIONS, fully merged.                   │
│   ❌ Any write to the partition INVALIDATES THE WHOLE ENTRY.   │
│   ❌ A large partition consumes enormous memory.               │
│   ⭐ Useful ONLY for small, hot, read-mostly partitions.       │
├───────────────────────────────────────────────────────────────┤
│ BLOCK CACHE (RocksDB) / KEY CACHE (Cassandra)                 │
│   ⭐ Caches uncompressed SSTable data blocks (RocksDB) or      │
│      key→offset mappings (Cassandra).                          │
│   ⭐ THE IMPORTANT ONE. Sized at 1/3 of RAM typically.         │
├───────────────────────────────────────────────────────────────┤
│ OS PAGE CACHE                                                  │
│   ⭐ Caches the COMPRESSED SSTable files.                      │
│   Free, automatic, and it survives a process restart.          │
└───────────────────────────────────────────────────────────────┘
```

### The compressed/uncompressed distinction ⭐

```
BLOCK CACHE holds UNCOMPRESSED blocks  → fewer entries, no CPU on hit
PAGE CACHE  holds COMPRESSED files     → ⭐ 3-5× more data cached,
                                            but decompression CPU per read

⭐ THE TUNING DECISION:
   • CPU-constrained, data compresses poorly → larger block cache
   • Memory-constrained, data compresses well (3-5×) → ⭐ rely on the
     page cache and keep the block cache modest

   Cassandra historically relies heavily on the page cache, which is
   why "leave half the RAM for the OS" is standard Cassandra advice.
```

---

## 18. The commit log

Every LSM engine has a WAL, for exactly the reason PostgreSQL does (Deep Dive 07 §1): the memtable is in memory and would be lost on a crash.

```
WRITE → append to commit log → insert into memtable → ack

⭐ When a memtable is FLUSHED and fsynced to an SSTable, the commit log
   segments covering it can be recycled.
```

### The durability dial

```
Cassandra:
  commitlog_sync: periodic
  commitlog_sync_period_in_ms: 10000    ⭐ fsync every 10 SECONDS by default
     → ⭐ up to 10 seconds of acknowledged writes can be lost on a crash

  commitlog_sync: batch
  commitlog_sync_batch_window_in_ms: 2
     → fsync within 2 ms, group-committed. Much safer, slower.

RocksDB:
  WriteOptions.sync = false   ⭐ default: OS buffer only
  WriteOptions.sync = true    fsync every write
  WriteOptions.disableWAL = true   ⭐ no WAL at all — for rebuildable data
```

```
⭐ CASSANDRA'S DEFAULT IS `periodic` WITH A 10-SECOND WINDOW.

   This surprises people who assume a successful write is durable.
   It is durable in the sense of "replicated to N nodes' memtables and
   commit log buffers" — but a simultaneous power loss across those
   nodes loses up to 10 seconds.

   ⭐ This is a deliberate AP-system trade (Chapter 05 §5.4): durability
      is provided by REPLICATION, not by per-node fsync. It is defensible.
      But you should know it, and `batch` mode exists if you need more.
```

**Compare with PostgreSQL's `synchronous_commit` (Deep Dive 07 §13):** the same dial, different defaults, reflecting different philosophies. PostgreSQL defaults to full local durability; Cassandra defaults to replication-based durability with a loss window.

---

## 19. Key-value separation (WiscKey)

An optimisation worth knowing about, because it dramatically changes the arithmetic for large values.

```
⭐ THE OBSERVATION: compaction rewrites KEYS AND VALUES together.
   But only the KEYS need to be sorted. The values are just payload.

   For a 10 KB value with a 20-byte key, ⭐ 99.8% of compaction I/O
   is moving payload that never needed to be re-sorted.
```

```
⭐ WiscKey (2016): store VALUES in a separate append-only VALUE LOG.
   The LSM tree stores only  key → (log offset, length).

   LSM tree:    "user:1000" → (vlog_file_12, offset 48291, len 10240)
   Value log:   [ ...appended values... ]
```

```
✅ ⭐ WRITE AMPLIFICATION COLLAPSES for large values.
   The LSM holds only small pointers, so compaction moves almost nothing.
   Measured: 10-30× → ⭐ 2-3× for multi-KB values.

❌ An extra random read per lookup (the vlog seek).
   ⭐ Acceptable on SSD; catastrophic on spinning disks — which is why
      this design only became practical with flash.
❌ ⭐ The value log needs its own garbage collection, which is a real
   engineering problem (it must find live pointers to know what to keep).
❌ Range scans lose locality — values are scattered in the vlog.
```

**Implementations:** BadgerDB (Go, WiscKey by design), RocksDB's **BlobDB** (`enable_blob_files = true`), TerarkDB. RocksDB's BlobDB is production-grade and worth considering for any workload with values above ~1 KB.

```
⭐ THE RULE OF THUMB: key-value separation pays off when values exceed
   roughly 1 KB. Below that, the pointer overhead and the extra read
   outweigh the compaction saving.
```

---

## 20. RocksDB: the tuning that matters

RocksDB is the LSM engine you are most likely to encounter, often without choosing it — it is embedded in TiKV, MyRocks, Kafka Streams, Flink's state backend, and Ceph's BlueStore.

```cpp
Options options;

// ═══ MEMTABLE (§3) ═══
options.write_buffer_size = 256 * 1024 * 1024;   // ⭐ 64 MB default is small
options.max_write_buffer_number = 4;              // ⭐ more headroom before stalls
options.min_write_buffer_number_to_merge = 2;     // merge before flushing

// ═══ COMPACTION (§10) ═══
options.compaction_style = kCompactionStyleLevel;
options.level0_file_num_compaction_trigger = 4;
options.level0_slowdown_writes_trigger = 20;      // ⭐ §16
options.level0_stop_writes_trigger = 36;          // ⭐ §16
options.max_bytes_for_level_base = 512 * 1024 * 1024;
options.max_bytes_for_level_multiplier = 10;
options.target_file_size_base = 64 * 1024 * 1024;

// ═══ BACKGROUND WORK — ⭐ the most common under-configuration ═══
options.max_background_jobs = 8;                  // default 2
options.max_subcompactions = 4;                   // parallelise one compaction

// ═══ BLOOM FILTERS (§7) ═══
BlockBasedTableOptions table_options;
table_options.filter_policy.reset(NewBloomFilterPolicy(10, false));  // 10 bits/key
table_options.whole_key_filtering = true;
table_options.cache_index_and_filter_blocks = true;          // ⭐ important
table_options.pin_l0_filter_and_index_blocks_in_cache = true;// ⭐ keep L0 hot

// ═══ BLOCK CACHE (§17) ═══
table_options.block_cache = NewLRUCache(8ULL * 1024 * 1024 * 1024);  // 8 GB
table_options.block_size = 16 * 1024;             // ⭐ 4 KB default is small
                                                   //   for scan-heavy workloads

// ═══ COMPRESSION ═══
options.compression = kLZ4Compression;             // ⭐ upper levels: fast
options.bottommost_compression = kZSTD;            // ⭐ bottom level: dense
                                                   //   (written once, read rarely)
```

### The five settings that matter most

```
1. ⭐ max_background_jobs — the default of 2 starves compaction on any
   modern multi-core machine. This is the #1 cause of compaction debt.

2. ⭐ write_buffer_size — a larger memtable means fewer, larger L0 files
   and less L0→L1 amplification.

3. ⭐ cache_index_and_filter_blocks + pin_l0_... — without these, index
   and filter blocks can be evicted, and then every read pays extra I/O
   to re-read the thing that was supposed to save I/O.

4. ⭐ Tiered compression (lz4 upper, zstd bottommost) — the bottom level
   holds ~90% of the data and is read rarely, so pay CPU there for density
   and keep the hot upper levels fast.

5. ⭐ bloom bits per key — 10 is the default; raise it if you have
   memory and do many negative lookups.
```

---

## 21. Where LSM engines are actually used

| System | Engine | Notes |
|--------|--------|-------|
| **Cassandra** | Own LSM | STCS default; LCS and TWCS available |
| **ScyllaDB** | Own C++ LSM | ⭐ Shard-per-core, no page cache reliance, much better tail latency |
| **HBase** | Own LSM (HFiles) | On HDFS |
| **RocksDB** | — | ⭐ The embedded LSM library everyone uses |
| **LevelDB** | — | Google's original; RocksDB is its descendant |
| **TiKV** | RocksDB | With Raft on top (Deep Dive 01) |
| **CockroachDB** | ⭐ **Pebble** | A Go rewrite of RocksDB, for control and CGo avoidance |
| **MyRocks** | RocksDB | MySQL storage engine — Facebook's replacement for InnoDB |
| **Kafka Streams / Flink** | RocksDB | ⭐ Local state stores |
| **InfluxDB** | TSM (LSM-like) | Time-series optimised |
| **ClickHouse** | MergeTree | ⭐ LSM-*like*: sorted immutable parts, background merges, columnar |
| **Ceph BlueStore** | RocksDB | For metadata |
| **Badger** | Own (WiscKey) | ⭐ Key-value separation by design |

> **Note how many of these are *embedded*.** RocksDB is a library, not a server. When Kafka Streams keeps local state, or Flink checkpoints, or CockroachDB stores a range, there is an LSM tree in the process. Understanding compaction behaviour explains a surprising number of "why does this service periodically have a latency spike" investigations.

---

## 22. B-tree vs LSM: the decision

```
┌────────────────────────────────────────────────────────────────┐
│ CHOOSE LSM WHEN:                                                │
│  ✅ ⭐ Write-heavy (writes ≥ reads, or very high write rate)     │
│  ✅ Writes are inserts/appends more than in-place updates        │
│  ✅ Reads are mostly POINT LOOKUPS (bloom filters work)          │
│  ✅ ⭐ Space efficiency matters (leveled compaction ~1.1×)       │
│  ✅ Data compresses well (whole immutable blocks compress)       │
│  ✅ You can tolerate ⭐ TAIL LATENCY VARIANCE from compaction    │
│  ✅ SSD/NVMe storage                                             │
├────────────────────────────────────────────────────────────────┤
│ CHOOSE B-TREE WHEN:                                             │
│  ✅ Read-heavy                                                   │
│  ✅ ⭐ RANGE SCANS are common (bloom filters do not help LSM)    │
│  ✅ ⭐ PREDICTABLE LATENCY matters more than peak throughput      │
│  ✅ You need ACID transactions and rich secondary indexes        │
│  ✅ Small updates to existing rows dominate                      │
│  ✅ The working set fits in memory                               │
└────────────────────────────────────────────────────────────────┘
```

### The tail-latency point, specifically

```
⭐ THE MOST PRACTICALLY IMPORTANT DIFFERENCE.

B-tree:  p50 = 0.5 ms,  p99 = 3 ms,   p99.9 = 15 ms
LSM:     p50 = 0.3 ms,  p99 = 8 ms,   ⭐ p99.9 = 200 ms+

The LSM tail comes from:
  • compaction competing for I/O
  • write stalls (§16)
  • L0 file count spikes
  • memtable flush pauses
  • (in JVM systems: GC of large memtables)

⭐ ScyllaDB's entire value proposition is fixing this — shard-per-core,
   its own scheduler, no JVM, and I/O prioritisation between compaction
   and user requests.
```

> **If your SLO is on p99.9 latency rather than throughput, that single line should weigh heavily.** A B-tree system is easier to make *predictable*; an LSM system is easier to make *fast on average*.

### The honest modern caveat

```
⭐ The B-tree/LSM distinction is less decisive than it was in 2015.

  • PostgreSQL with a well-tuned checkpoint interval and lz4 WAL
    compression (Deep Dive 07) has far lower write amplification
    than the naive analysis suggests.
  • Modern NVMe makes random writes much less costly than they were.
  • LSM systems have added B-tree-like features (secondary indexes,
    transactions) and B-tree systems have added LSM-like ones
    (ClickHouse's MergeTree, PostgreSQL's ZHeap experiments).

⭐ Choose on the workload's SHAPE (point vs range, read vs write ratio,
   latency vs throughput priority) rather than on the storage-engine
   family name.
```

---

## 23. Monitoring an LSM system

### The metrics that matter

```
⭐ 1. COMPACTION DEBT — the master metric
     Cassandra: nodetool compactionstats → pending tasks
     RocksDB:   rocksdb.estimate-pending-compaction-bytes
     ALERT: pending tasks > 100, or pending bytes > 25% of data size

⭐ 2. L0 FILE COUNT — the leading indicator of read degradation
     Cassandra: nodetool tablestats → SSTables in each level
     RocksDB:   rocksdb.num-files-at-level0
     ALERT: > 20

⭐ 3. WRITE STALLS — the failure itself
     RocksDB:   rocksdb.stall-micros, rocksdb.actual-delayed-write-rate
     Cassandra: dropped mutations, write timeouts
     ALERT: any non-zero stall time

⭐ 4. TOMBSTONE RATIO — the silent killer (§15)
     Cassandra: tombstone_warn_threshold log warnings
                nodetool tablestats → "Average tombstones per slice"
     ALERT: average tombstones per read > 100

⭐ 5. SPACE AMPLIFICATION
     on-disk size / estimated live data
     ALERT: > 2× for leveled, > 3× for size-tiered

6. Bloom filter false positive rate
     Cassandra: nodetool tablestats → "Bloom filter false ratio"
     RocksDB:   rocksdb.bloom.filter.useful vs .full.positive
     ALERT: > 5% → raise bits per key

7. Read/write latency percentiles, especially ⭐ p99.9
```

### The diagnostic commands

```bash
# ═══ Cassandra ═══
nodetool compactionstats          # ⭐ debt
nodetool tablestats keyspace.table # ⭐ SSTable count, levels, tombstones, bloom
nodetool tablehistograms ks.tbl   # ⭐ latency + SSTables-per-read distribution
nodetool cfstats                  # overall
nodetool tpstats                  # thread pools — dropped messages

# ⭐ The single most useful one: how many SSTables does a read touch?
nodetool tablehistograms prod.events
#  Percentile  SSTables  Write Latency  Read Latency  Partition Size
#  50%         3.00      35.43 us       120.12 us     1109
#  99%         ⭐ 24.00  186.56 us      ⭐ 8409.01 us  17084
#              ^^^^^^^ 24 SSTables for a p99 read → compaction is behind
```

```bash
# ═══ RocksDB (via the embedding application's stats endpoint) ═══
rocksdb.num-files-at-level0 .. level6
rocksdb.estimate-pending-compaction-bytes
rocksdb.stall-micros
rocksdb.compaction-pending
rocksdb.estimate-live-data-size
rocksdb.total-sst-files-size        # ⭐ vs live-data-size = space amp
rocksdb.block-cache-hit / .-miss
rocksdb.bloom.filter.useful
```

---

## 24. What an architect takes from this

**1. LSM converts foreground random writes into background sequential writes.** The cost is not eliminated — it is *deferred* into compaction, where it shows up as 10–30× write amplification and a sustained background I/O load you must provision for.

**2. Do the write-amplification arithmetic before choosing.** 10 MB/s of logical writes becomes 330 MB/s of device writes under leveled compaction. That is a provisioning fact, not a detail.

**3. The RUM conjecture means there is no best engine.** Read, update and space overhead trade against each other, provably. Every compaction strategy is a different point on that surface.

**4. Bloom filters make LSM point lookups competitive and do nothing for range scans.** If your access pattern is range-dominated, that is a strong argument against LSM.

**5. Tombstones are the hardest part.** Never build a write-then-delete-within-a-partition pattern. Use TTL plus time-window compaction so deletion becomes *dropping a file* — the same principle as PostgreSQL partitioning.

**6. `gc_grace_seconds` is a contract, not a setting.** It obliges you to complete a full repair within that window, or risk resurrected data.

**7. Write stalls are back-pressure working as designed**, and they are indistinguishable from an outage to the application. Monitor compaction debt and L0 file count as leading indicators, not write latency as a lagging one.

**8. Cassandra's default `compaction_throughput_mb_per_sec = 16` is sized for spinning disks** and silently causes slow cluster degradation on NVMe. This is one of the most common real-world LSM misconfigurations.

**9. Tail latency is LSM's weak point.** p99.9 can be 10× worse than a B-tree's. If your SLO is on the tail, weigh that heavily — or look at ScyllaDB, whose entire design targets it.

**10. RocksDB is embedded in more systems than you realise.** Kafka Streams state stores, Flink checkpoints, TiKV, CockroachDB (Pebble), MyRocks. Periodic latency spikes in any of them are frequently compaction, and now you know how to confirm it.

**11. Key design matters as much here as in a B-tree, for different reasons.** Prefix-compressible keys make SSTable blocks dramatically smaller; random keys defeat both prefix compression and any locality in compaction. It is Deep Dive 05 §11's lesson in a different mechanism.

---

## Exercises

1. Compute write amplification for a leveled LSM with 6 levels and a 10× multiplier. Then compute the sustained device write rate for 20 MB/s of logical writes.
2. Size the bloom filters for 500 million keys at a 0.1% false-positive rate. Does it fit in your node's RAM budget?
3. Explain why bloom filters cannot help a range scan, and what that implies for a time-series query workload.
4. A Cassandra table uses STCS and holds 400 GB. How much free disk must the node have, and why?
5. Trace a `GET` for a key that does not exist, through a 6-level LSM with bloom filters. How many disk reads, in expectation?
6. Reproduce the tombstone problem: insert and delete 100,000 rows in one Cassandra partition, then query it. Observe the warning threshold.
7. Redesign the §15 job queue three different ways. Rank them and justify.
8. Explain `gc_grace_seconds` to an operations team, including the repair obligation it creates.
9. Check `compaction_throughput_mb_per_sec` on a Cassandra cluster. Is it appropriate for the storage? Compute the correct value.
10. Find the L0 file count and pending compaction bytes for a RocksDB-backed system you run (Kafka Streams, Flink, TiKV). Is it healthy?
11. Compare leveled and size-tiered for a workload with 50 GB of data, 5,000 writes/sec, and cloud storage priced per GB and per provisioned IOPS. Show the cost calculation.
12. Explain when key-value separation (WiscKey/BlobDB) pays off, with the size threshold and the reason.
13. Your service has p50 = 0.4 ms and p99.9 = 240 ms, backed by RocksDB. Give three hypotheses and the metric that distinguishes them.
14. Write the decision memo for a new system: 40,000 writes/sec, 4,000 reads/sec, all point lookups by key, 2 TB of data, p99 SLO of 20 ms. B-tree or LSM? Justify with numbers.

---

**Next in this series:** Deep Dive 10 — Kafka Internals

**Back to:** [Deep Dives](README.md) · [Chapter 10](../10-nosql-architecture.md) · [The Map](../README.md)
