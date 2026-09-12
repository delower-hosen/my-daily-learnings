# Deep Dive 05 — B-trees, Indexes and Access Methods

**Prerequisite:** [Chapter 09 §9.6](../09-database-architecture.md) · [Deep Dive 04](04-postgresql-mvcc-and-storage.md)

**What the map said:** *"An index is a data structure that lets the database find rows without scanning the table. Column order: equality → range → sort. Use UUIDv7 instead of UUIDv4."*

**What this deep dive does:** builds a B-tree page byte by byte, computes real fan-out and height for real tables, traces a page split, explains the right-link trick that lets readers descend without locks, shows exactly why random keys produce indexes 2× larger than sequential ones and quantifies it, explains why B-trees never merge pages (and what PostgreSQL 14 did about it), takes apart GIN's pending list, GiST's penalty/picksplit framework and BRIN's correlation dependency, and ends with the index audit you should run on every production database.

---

## Contents

```
1.  Why B-trees and not binary trees
2.  The B+ tree, and PostgreSQL's B-link variant
3.  A B-tree page, byte by byte
4.  Fan-out and height: the real arithmetic
5.  The search algorithm
6.  Insertion and the page split
7.  Traced scenario — a page split, step by step
8.  The right-link trick ⭐ — concurrency without locking the tree
9.  Deletion: why B-trees bloat
10. Traced scenario — sequential vs random insertion
11. Why UUIDv4 primary keys cost you ⭐
12. Deduplication (PG13) and posting lists
13. Bottom-up index deletion (PG14) ⭐
14. Multicolumn indexes: why leftmost-prefix
15. Covering indexes and INCLUDE
16. Partial indexes
17. Expression indexes and the planner's blind spot
18. Index scan, index-only scan, bitmap scan
19. Bitmap scans, work_mem and lossy bitmaps
20. Correlation: the statistic that decides everything
21. GIN internals — the pending list trap
22. GiST internals — penalty and picksplit
23. SP-GiST, and what it is for
24. BRIN internals — tiny indexes, one hard requirement
25. Hash indexes — finally usable
26. The cost of an index, quantified
27. The index audit
28. Choosing an index type
29. What an architect takes from this
```

---

## 1. Why B-trees and not binary trees

Start from the constraint, because it explains the whole design.

```
A binary search tree over 100 million rows:
    height = log₂(100,000,000) ≈ 27 levels

Each level is a pointer to somewhere else in memory or on disk.
On disk, each level is a separate 8 KB page read.

    27 page reads × 150 µs (random SSD read) = 4 ms per lookup
    On a spinning disk at 10 ms per seek: 270 ms.  Unusable.
```

**The problem is that a binary node holds one key.** You pay a full page read to learn one comparison's worth of information. A 8 KB page can hold hundreds of keys — and reading 8 KB costs essentially the same as reading 16 bytes, because the cost is dominated by the seek, not the transfer.

```
A B-tree node fills an entire page:

    height = log₄₀₀(100,000,000) ≈ 3.1 → 4 levels

    4 page reads, and the top 2-3 levels are almost always cached.
    → typically 1-2 actual disk reads per lookup.
```

> **The B-tree is not a clever algorithm. It is a data structure shaped around the fact that storage is addressed in blocks.** Every design decision — high fan-out, all data in leaves, splitting rather than rebalancing — follows from "a page read costs the same whether you use 16 bytes of it or 8192".

This also explains why B-trees remain correct for SSDs and even for memory: the same argument now applies to cache lines and NVMe page sizes, just at different magnitudes.

---

## 2. The B+ tree, and PostgreSQL's B-link variant

PostgreSQL's `nbtree` is a **B+ tree** with the **Lehman & Yao** high-concurrency modifications (a *B-link tree*).

```
                    ┌──────────── ROOT (internal) ───────────┐
                    │  [ ·  | 500 |  ·  | 1200 |  ·  ]       │
                    └───┬──────────┬───────────┬─────────────┘
                        │          │           │
            ┌───────────┘          │           └───────────┐
            ▼                      ▼                       ▼
   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
   │ INTERNAL        │   │ INTERNAL        │   │ INTERNAL        │
   │ [·|120|·|340|·] │   │ [·|700|·|950|·] │   │ [·|1500|·|...]  │
   └──┬────┬─────┬───┘   └──┬────┬─────┬───┘   └─────────────────┘
      │    │     │          │    │     │
      ▼    ▼     ▼          ▼    ▼     ▼
   ┌────┐┌────┐┌────┐    ┌────┐┌────┐┌────┐
   │LEAF││LEAF││LEAF│◄──►│LEAF││LEAF││LEAF│   ⭐ leaves are DOUBLY LINKED
   └────┘└────┘└────┘    └────┘└────┘└────┘
     ▲                                  ▲
     └──── every leaf is at the SAME depth ────┘
```

### The three properties that matter

**1. All data lives in leaf pages.** Internal pages hold only *separator keys* and downlinks. They are pure navigation.

```
Consequence: internal pages are small and dense, so they stay in the buffer
cache. A 100 M row index's internal levels are a few MB — permanently cached.
Only the leaf access touches disk.
```

**2. Leaves are linked in both directions.** An ordered scan (`ORDER BY id`, or a range query) descends once to the first matching leaf, then walks sideways. It never has to return to the root.

```
Consequence: ORDER BY on an indexed column is free — the index already
delivers rows in order. This is why "equality → range → sort" (Chapter 09)
works: the index's physical order IS the sort order.
```

**3. Every leaf is at the same depth.** The tree grows by splitting, and it grows **upward from the leaves** — the root splits last, which is the only operation that increases height.

### The B-link addition

Lehman & Yao added two things to the classic B+ tree:

```
• A HIGH KEY on every page: an upper bound on the keys this page may contain
• A RIGHT LINK (btpo_next) to the next sibling at the same level
```

Together these let a reader that arrives at a page **which has split since it read the parent** recover without any locking, by simply moving right. §8 traces exactly how, and it is the reason PostgreSQL index reads never block index writes.

---

## 3. A B-tree page, byte by byte

Same 8 KB page as the heap (Deep Dive 04 §2), with a different special area.

```
 byte 0                                                          byte 8191
 ┌────────────────────────────────────────────────────────────────────────┐
 │ PageHeaderData                                    24 bytes             │
 ├────────────────────────────────────────────────────────────────────────┤
 │ ItemId[1]  ItemId[2]  ItemId[3] ...               4 bytes each  →      │
 ├────────────────────────────────────────────────────────────────────────┤
 │                         FREE SPACE                                     │
 ├────────────────────────────────────────────────────────────────────────┤
 │  ← IndexTuple[3]   IndexTuple[2]   IndexTuple[1]                       │
 │                                     ↑                                   │
 │                        ⭐ ItemId[1] is the HIGH KEY on a non-rightmost  │
 │                           page — the upper bound for this page          │
 ├────────────────────────────────────────────────────────────────────────┤
 │ BTPageOpaqueData (special space)                  16 bytes             │
 └────────────────────────────────────────────────────────────────────────┘
```

### BTPageOpaqueData

```c
typedef struct BTPageOpaqueData {
    BlockNumber btpo_prev;      /* 4 B — left sibling at this level */
    BlockNumber btpo_next;      /* 4 B — ⭐ RIGHT LINK (the B-link trick, §8) */
    union {
        uint32 level;           /*      level of this page: 0 = leaf */
        TransactionId xact;     /*      when deleted: the xid that deleted it */
    } btpo;                     /* 4 B */
    uint16 btpo_flags;          /* 2 B */
    BTCycleId btpo_cycleid;     /* 2 B — vacuum cycle, prevents concurrency hazards */
} BTPageOpaqueData;             /* 16 bytes */
```

```c
/* btpo_flags */
#define BTP_LEAF        (1 << 0)   /* leaf page (level 0) */
#define BTP_ROOT        (1 << 1)   /* root page */
#define BTP_DELETED     (1 << 2)   /* ⭐ page is dead, awaiting recycling (§9) */
#define BTP_META        (1 << 3)   /* the metapage (block 0) */
#define BTP_HALF_DEAD   (1 << 4)   /* ⭐ mid-deletion (§9) */
#define BTP_SPLIT_END   (1 << 5)
#define BTP_HAS_GARBAGE (1 << 6)   /* has LP_DEAD entries to clean up */
```

### IndexTupleData

```c
typedef struct IndexTupleData {
    ItemPointerData t_tid;      /* 6 B — ⭐ the HEAP TID this entry points to
                                        (block number + line pointer offset).
                                        On an internal page, the downlink block. */
    unsigned short t_info;      /* 2 B — 13 bits size, plus NULL and VARLENA flags */
    /* then: optional null bitmap, then the key data, MAXALIGNed */
} IndexTupleData;               /* 8-byte header */
```

**Note that the index entry points at the heap's *line pointer*, not at the tuple.** That is what allows HOT pruning to move tuples within a page without invalidating index entries (Deep Dive 04 §12).

### Inspecting a real index

```sql
CREATE EXTENSION IF NOT EXISTS pageinspect;

-- Metapage (block 0) — where the root lives and how tall the tree is
SELECT * FROM bt_metap('accounts_pkey');
--  magic   | version | root | level | fastroot | fastlevel | allequalimage
-- ---------+---------+------+-------+----------+-----------+---------------
--  340322  |       4 |  412 |     2 |      412 |         2 | t
--                             ↑
--          ⭐ level 2 → the tree is 3 levels deep (leaves are level 0)

-- Statistics for one page
SELECT * FROM bt_page_stats('accounts_pkey', 412);
--  blkno | type | live_items | dead_items | avg_item_size | page_size | free_size
-- -------+------+------------+------------+---------------+-----------+-----------
--    412 | r    |        287 |          0 |            16 |      8192 |      3452

-- The actual entries on a leaf page
SELECT itemoffset, ctid, itemlen, left(data, 24) AS data
FROM bt_page_items('accounts_pkey', 3) LIMIT 5;
--  itemoffset |   ctid   | itemlen |          data
-- ------------+----------+---------+--------------------------
--           1 | (16,1)   |      16 | 2a 00 00 00 00 00 00 00    ⭐ offset 1 on a
--           2 | (0,1)    |      16 | 01 00 00 00 00 00 00 00       non-rightmost
--           3 | (0,2)    |      16 | 02 00 00 00 00 00 00 00       page is the HIGH KEY
```

---

## 4. Fan-out and height: the real arithmetic

This is where abstract "O(log n)" becomes numbers you can act on.

### Usable space per page

```
8192  total
 −24  PageHeaderData
 −16  BTPageOpaqueData
 −── 
8152  usable for line pointers + index tuples
```

### Entry size by key type

```
Entry cost = 4 (line pointer) + 8 (IndexTuple header) + MAXALIGN(key size)

  int4      →  4 + 8 + 8  = 20 bytes     (4-byte key padded to 8)
  int8      →  4 + 8 + 8  = 20 bytes
  uuid      →  4 + 8 + 16 = 28 bytes
  text (20) →  4 + 8 + 24 = 36 bytes     (1-4 byte varlena header + data)
  (int8,int8) → 4 + 8 + 16 = 28 bytes    (composite)
```

### Fan-out

```
Fan-out = 8152 / entry_size, then × fillfactor

  int8, fillfactor 90:   8152 / 20 = 407 → ~366 entries per page
  uuid, fillfactor 90:   8152 / 28 = 291 → ~262 entries per page
  text(20):              8152 / 36 = 226 → ~203 entries per page
```

### Height and the lookup cost

```
Rows a tree of height h can index ≈ fanout^h

BIGINT key (fan-out 366):
    height 1 (root is a leaf) :            366 rows
    height 2 :                         133,000 rows
    height 3 :                      48,600,000 rows
    height 4 :                  17,800,000,000 rows

UUID key (fan-out 262):
    height 3 :                      18,000,000 rows
    height 4 :                   4,700,000,000 rows
```

**Read this table carefully, because it contains a fact people find surprising:**

```
⭐ A 100-million-row table has a B-tree index 4 levels deep.
   A 10-billion-row table has a B-tree index 4 levels deep.

   Growing 100× adds ZERO levels.
```

That is why B-trees scale so well, and why "the index will get slow as the table grows" is usually wrong. What *does* get slow is the leaf access, because the leaves stop fitting in the buffer cache.

### The cost model that actually applies

```
Lookup cost = (height − cached_levels) page reads + 1 heap fetch

Typical 100 M row table, bigint PK, 4-level index:
    root (level 3)      → always cached
    level 2             → always cached (a few hundred pages, ~3 MB)
    level 1             → usually cached (~100k pages? no: ~133k entries / 366
                           = 365 pages, ~3 MB — cached)
    leaf (level 0)      → ~273,000 pages (2.2 GB) — MAYBE cached
    heap tuple          → 1 random read

⭐ So a primary key lookup on a 100 M row table is typically
   1-2 physical reads, not 4.
```

**The practical implication:** index size matters not because of tree height, but because of **whether the leaf level fits in RAM**. A 2.2 GB index on a machine with 8 GB of `shared_buffers` will be mostly cached; the same index at 6 GB will not, and lookups become disk-bound. This is the real reason to keep indexes small — and the real cost of a UUIDv4 key (§11).

```sql
-- How big are your indexes relative to shared_buffers?
SELECT sum(pg_relation_size(indexrelid)) AS total_index_bytes,
       pg_size_pretty(sum(pg_relation_size(indexrelid))) AS total_index_size,
       current_setting('shared_buffers') AS shared_buffers
FROM pg_stat_user_indexes;
```

---

## 5. The search algorithm

```python
def btree_search(index, key):
    """PostgreSQL's _bt_search, simplified but structurally accurate."""
    page = read_page(index.metapage.root)

    # ── Descend through internal pages ──
    while not page.is_leaf:
        # ⭐ Binary search WITHIN the page. This is the second level of
        #    the search: log2(366) ≈ 9 comparisons, all in CPU cache.
        offset = binary_search_page(page, key)
        child_block = page.items[offset].downlink
        page = read_page(child_block)          # ← the only I/O in the loop

    # ── At the leaf: check whether we need to move right (§8) ──
    while True:
        if page.high_key is not None and key > page.high_key:
            # ⭐ This page split after we read its parent.
            #    The key we want moved to a sibling. Follow the right link.
            page = read_page(page.opaque.btpo_next)
            continue
        break

    offset = binary_search_page(page, key)
    return scan_forward_from(page, offset)     # matches may span pages
```

**Two searches, not one.** The tree descent picks the page (I/O-bound, ~4 steps). The binary search *within* the page picks the entry (CPU-bound, ~9 comparisons on cached data).

**Why this matters for key type choice:** the in-page binary search calls the type's comparison function ~9 times per level, ~36 times per lookup. For `bigint` that is a single machine instruction. For `text` with a non-C collation it is a call into ICU or glibc's `strcoll`, which is *hundreds* of times more expensive.

```sql
-- ⭐ A real, measurable optimisation for text keys you only ever compare for equality
CREATE INDEX idx_users_email ON users (email COLLATE "C");
-- "C" collation = byte comparison. Often 3-10× faster than a locale-aware
-- collation for index operations. The trade-off: ORDER BY gives byte order,
-- not linguistic order, and LIKE 'prefix%' still works (it works with any
-- collation only if you use text_pattern_ops or C collation).
```

---

## 6. Insertion and the page split

```python
def btree_insert(index, key, heap_tid):
    leaf = descend_to_leaf(index, key)

    if leaf.has_room(entry_size):
        leaf.insert_sorted(key, heap_tid)          # the common case — done
        return

    # ── The page is full. Before splitting, try to avoid it: ──

    # 1. Remove entries already marked LP_DEAD by earlier scans (§9)
    if leaf.has_lp_dead_items():
        leaf.remove_dead_items()
        if leaf.has_room(entry_size):
            leaf.insert_sorted(key, heap_tid)
            return

    # 2. ⭐ PG14+: bottom-up deletion. Check whether many entries point at
    #    dead heap tuples from version churn, and delete them. (§13)
    if bottom_up_deletion(leaf, index):
        if leaf.has_room(entry_size):
            leaf.insert_sorted(key, heap_tid)
            return

    # 3. Split.
    split_point = find_split_location(leaf, key)   # ⭐ see below
    right_page = allocate_page()

    right_page.items = leaf.items[split_point:]
    leaf.items        = leaf.items[:split_point]

    # ⭐ Establish the links BEFORE touching the parent (this is what makes
    #    the B-link trick work — §8)
    right_page.opaque.btpo_next = leaf.opaque.btpo_next
    right_page.opaque.btpo_prev = leaf.block
    leaf.opaque.btpo_next       = right_page.block
    right_page.high_key         = leaf.high_key
    leaf.high_key               = right_page.items[0].key

    insert_into(leaf if key < leaf.high_key else right_page, key, heap_tid)

    # Now propagate a new separator key up. May cascade.
    insert_into_parent(leaf.parent, leaf.high_key, right_page.block)
```

### `find_split_location` — the decision that shapes your index

This is the function that determines whether your index ends up 90% packed or 50% packed.

```
IF the page being split is the RIGHTMOST page at its level:
    ⭐ Split at the fillfactor point (default 90 for B-tree leaves).
       The left page keeps 90%; the right page starts nearly empty.
       Rationale: monotonically increasing keys will keep arriving at the
       right edge, so the new right page will fill up naturally.

ELSE (an interior split, caused by a random insert):
    Split ~50/50, balancing the two pages.
    Rationale: we have no idea where the next key will land, so hedge.

PG12+ also has "split after new tuple": when many duplicate or
near-duplicate keys are being appended, it recognises the pattern and
packs more aggressively.
```

> **This single branch is the entire explanation for §10 and §11.** Sequential keys always split the rightmost page and get 90% packing. Random keys split interior pages and get 50% packing — permanently, at steady state.

---

## 7. Traced scenario — a page split, step by step

A tiny tree (fan-out 4, for legibility) taking one insert too many.

```
BEFORE — leaf page 5 is full

  Parent (page 2, internal):
    [ →p4 | 10 | →p5 | 30 | →p6 ]
                    ↑ separator: keys ≥ 10 and < 30 live in p5

  Page 4:  high_key=10   items=[1,4,7,9]        next→5
  Page 5:  high_key=30   items=[10,15,20,25]    next→6    ← FULL
  Page 6:  high_key=∞    items=[30,34,38]       next→NULL

INSERT key 18 into page 5.
```

```
STEP 1 — page 5 is full; no LP_DEAD items; bottom-up deletion finds nothing.
         → must split.

STEP 2 — find_split_location:
         Page 5 is NOT the rightmost leaf (page 6 is).
         → split 50/50. Split point = 2.

STEP 3 — allocate page 7. Move the upper half.

         Page 5:  items=[10,15]
         Page 7:  items=[20,25]

STEP 4 — ⭐ Fix the sibling links FIRST, before the parent:

         Page 7.btpo_next = 6          (inherits page 5's old right link)
         Page 7.btpo_prev = 5
         Page 5.btpo_next = 7          (was 6)
         Page 6.btpo_prev = 7          (was 5)

         Page 7.high_key  = 30         (inherits page 5's old high key)
         Page 5.high_key  = 20         ⭐ NEW: the first key of page 7

         At this instant the leaf level is correct and traversable:
             p4 → p5 → p7 → p6
         ...but the PARENT still says "keys 10..30 are in p5".
         ⭐ A reader looking for 25 will descend to p5 and not find it.
            §8 explains how it recovers.

STEP 5 — Insert 18. It belongs in page 5 (18 < high_key 20).

         Page 5:  items=[10,15,18]
         Page 7:  items=[20,25]

STEP 6 — Insert the separator into the parent:

  Parent (page 2):
    [ →p4 | 10 | →p5 | 20 | →p7 | 30 | →p6 ]
                          ↑ NEW

         If the parent were also full, it would split too, and so on up.
         If the ROOT splits, a new root is created and the tree grows
         one level taller. ⭐ This is the ONLY way a B-tree gets taller.
```

```
AFTER

  Parent (page 2):
    [ →p4 | 10 | →p5 | 20 | →p7 | 30 | →p6 ]

  Page 4: high=10  [1,4,7,9]     next→5
  Page 5: high=20  [10,15,18]    next→7     ⭐ 3/4 full
  Page 7: high=30  [20,25]       next→6     ⭐ 2/4 full
  Page 6: high=∞   [30,34,38]    next→NULL
```

**Note the outcome: two pages that were one full page are now 75% and 50% full.** That space is reclaimable only by future inserts landing in those exact key ranges. With random keys, that happens; with sequential keys, it never does — which is why §9's "B-trees do not merge" matters.

---

## 8. The right-link trick ⭐ — concurrency without locking the tree

The Lehman & Yao contribution, and the reason PostgreSQL index reads never block.

### The problem it solves

```
Reader:  descends to internal page 2, reads "keys 10..30 are in page 5",
         releases the lock on page 2 (⭐ it must, or the tree would be a
         serial bottleneck), and starts reading page 5.

Writer:  concurrently splits page 5, moving keys 20-25 to page 7.

Reader:  arrives at page 5 looking for key 25. It is not there.

         A naive B-tree would return "not found" — a WRONG ANSWER.
```

The obvious fix — hold locks all the way down the tree — makes the root a global bottleneck. Every index operation would serialise on it.

### The Lehman-Yao solution

```
Every page carries a HIGH KEY: the exclusive upper bound of keys it may hold.
Every page carries a RIGHT LINK to its sibling.

A reader that lands on a page and finds  search_key >= page.high_key
knows the page has split since it read the parent, and simply FOLLOWS
THE RIGHT LINK.
```

```
Reader looking for 25:

  arrives at page 5.  high_key = 20.  25 >= 20  →  MOVE RIGHT
  arrives at page 7.  high_key = 30.  25 < 30   →  search this page. FOUND ✓

⭐ No locks held during the descent. No wrong answer. No retry from the root.
```

### Why the ordering in step 4 of §7 is critical

```
The split MUST establish the sibling links and high keys BEFORE updating
the parent. Between those two moments the tree is in a state where:

   • the parent is STALE (points only to page 5)
   • but the leaf level is COMPLETE and traversable (5 → 7 → 6)

⭐ A reader can always reach the correct page by moving right.
   The stale parent costs it one extra page read, not correctness.

If the parent were updated first, there would be a window where the parent
points to page 7 but page 7 does not yet exist or is not yet linked —
and a reader would follow a dangling pointer.
```

**This is also why a crash mid-split is safe.** An "incomplete split" leaves the leaf level correct and the parent stale. PostgreSQL detects the incomplete split flag on the next traversal and finishes the parent insertion then. No recovery-time tree repair is needed.

> **The general lesson, which recurs throughout systems design:** make the intermediate state *correct but slower* rather than *fast but briefly wrong*. The right-link trick, the Outbox pattern (Chapter 06), and expand/contract migrations (Chapter 09) are all the same idea — order your writes so that every intermediate state is safe.

---

## 9. Deletion: why B-trees bloat

This is the mechanism behind index bloat, and it is quite different from heap bloat.

### What a DELETE does to an index

**Nothing, immediately.**

```
DELETE FROM accounts WHERE id = 42;

  Heap:   the tuple gets t_xmax = <my xid>  (Deep Dive 04 §11)
  Index:  ⭐ NOTHING HAPPENS. The index entry still points to the heap TID.
```

The index entry cannot be removed at delete time, because the deleting transaction might roll back, and because other snapshots may still need to see the row.

### The three-stage cleanup

**Stage 1 — `kill_prior_tuple` (the cheap opportunistic one)**

```
An index scan follows an entry to the heap, and discovers the heap tuple is
dead to ALL transactions.

⭐ It sets LP_DEAD on the INDEX line pointer as a hint.

This costs nothing extra (the heap page was already read) and it means
future scans skip the entry without a heap fetch.
```

**Stage 2 — deletion during an insert that would otherwise split**

```
Before splitting a page, PostgreSQL removes LP_DEAD entries (§6 step 1).
This frequently avoids the split entirely.
```

**Stage 3 — VACUUM**

```
VACUUM's index pass (Deep Dive 04 §15 phase 2) scans the whole index and
removes every entry pointing at a dead heap TID.
```

### ⭐ The core problem: pages are not merged

```
A leaf page holds 366 entries. 360 of them are deleted and vacuumed away.

The page now holds 6 entries and 8,000 bytes of free space.

⭐ PostgreSQL does NOT merge it with its siblings.
   The page stays in the tree, nearly empty, forever —
   unless future inserts land in exactly that key range.
```

**Page deletion only happens when a page becomes completely empty**, and even then it is careful:

```
1. The page becomes entirely empty
2. VACUUM marks it BTP_HALF_DEAD and unlinks it from the parent
3. It becomes BTP_DELETED, stamped with the deleting xid
4. ⭐ It can only be RECYCLED (reused for a new split) once no concurrent
   scan could still hold a reference to it — determined by comparing against
   the current xmin horizon (Deep Dive 04 §16).

So: even fully empty pages sit unusable until the horizon advances.
```

### The pattern that bloats indexes forever

```
Table: events, indexed on created_at.
Workload: INSERT constantly; DELETE rows older than 90 days.

  Inserts:  always at the RIGHT edge (created_at is increasing)
  Deletes:  always at the LEFT edge (oldest rows)

  ⭐ The left side of the index empties out.
     Those pages are never reused, because no new key ever belongs there.
     The index grows monotonically while the table size stays flat.
```

```sql
-- The symptom
SELECT pg_size_pretty(pg_relation_size('events'))               AS table_size,
       pg_size_pretty(pg_relation_size('idx_events_created_at')) AS index_size;
--  table_size | index_size
-- ------------+------------
--  42 GB      | 38 GB        ⭐ an index nearly the size of the table,
--                               on a single timestamp column
```

**The fixes, in order of quality:**

```
1. ⭐ PARTITION by time (Chapter 09 §9.10).
   DROP PARTITION removes the data AND its index portion instantly.
   No bloat. No REINDEX. This is the structural answer.

2. REINDEX INDEX CONCURRENTLY idx_events_created_at;
   Works, but it recurs. You are on a treadmill.

3. Consider BRIN instead (§24) — for an append-only, time-correlated
   column, BRIN is ~1000× smaller and has no bloat problem at all.
```

---

## 10. Traced scenario — sequential vs random insertion

The same 1,000 inserts, two key types. This is the experiment that makes §11 concrete.

### Sequential keys (bigserial / UUIDv7)

```
Keys arrive: 1, 2, 3, 4, ... 1000

Insert 1-366:    all land on the root-as-leaf page. It fills.
Insert 367:      page is full → SPLIT.
                 ⭐ It is the RIGHTMOST page → split at fillfactor 90.
                 Left page keeps 329 entries (90%), right page gets 37.
                 A new root is created. Tree height = 2.

Insert 368-696:  all go to the RIGHT page (keys are increasing).
                 It fills to 366 → split → left keeps 90%, new right page.

Pattern repeats:
    ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌──────┐
    │ 90%   │ │ 90%   │ │ 90%   │ │ 90%   │ │ 12%  │ ← only the rightmost
    │ full  │ │ full  │ │ full  │ │ full  │ │ full │   page is partly empty
    └───────┘ └───────┘ └───────┘ └───────┘ └──────┘

⭐ RESULT: ~90% average page density.
   Every insert touches ONE page — always the same rightmost page,
   which is permanently in the buffer cache.
   Splits are rare and always at the right edge.
```

### Random keys (UUIDv4)

```
Keys arrive in random order across the whole 128-bit space.

Insert 1-366:   fill the root-as-leaf. Split.
Insert 367+:    each key lands on a RANDOM page.

When a page fills and splits:
    ⭐ It is NOT the rightmost page → split 50/50.
    Two pages at 50% each.

Those two pages then receive random inserts, fill to 100%, split 50/50 again.

Steady state: pages oscillate between 50% and 100% full.
              ⭐ AVERAGE DENSITY ≈ 68-70%.

    ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐
    │ 52%   │ │ 88%   │ │ 61%   │ │ 95%   │ │ 55%   │  ← all partially full
    └───────┘ └───────┘ └───────┘ └───────┘ └───────┘
```

### The measured difference

```sql
CREATE TABLE t_seq  (id bigserial PRIMARY KEY, payload text);
CREATE TABLE t_uuid (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), payload text);

INSERT INTO t_seq  (payload) SELECT repeat('x',100) FROM generate_series(1,5000000);
INSERT INTO t_uuid (payload) SELECT repeat('x',100) FROM generate_series(1,5000000);

SELECT 'sequential' AS kind,
       pg_size_pretty(pg_relation_size('t_seq_pkey'))  AS index_size,
       (pgstatindex('t_seq_pkey')).avg_leaf_density
UNION ALL
SELECT 'random uuid',
       pg_size_pretty(pg_relation_size('t_uuid_pkey')),
       (pgstatindex('t_uuid_pkey')).avg_leaf_density;

--     kind     | index_size | avg_leaf_density
-- -------------+------------+------------------
--  sequential  | 107 MB     |            90.12     ⭐
--  random uuid | 211 MB     |            67.84     ⭐  ~2× the size
```

**And the index size difference is only half the story.** §11 covers the rest.

---

## 11. Why UUIDv4 primary keys cost you ⭐

The map said "use UUIDv7 instead of UUIDv4". Here is the full accounting.

### Cost 1 — the index is ~2× larger

From §10: 90% vs 68% leaf density, plus UUID's 16-byte key vs bigint's 8.

```
5 M rows, bigint PK:   107 MB
5 M rows, uuid v4 PK:  211 MB

At 500 M rows:  ~10 GB  vs  ~21 GB

⭐ The consequence that actually hurts: whether the leaf level fits in
   shared_buffers (§4). A 10 GB index on a 32 GB machine is cached.
   A 21 GB one is not, and every lookup becomes a disk read.
```

### Cost 2 — every insert dirties a random page

```
SEQUENTIAL:  every insert touches the SAME rightmost leaf page.
             That page is in the buffer cache, already dirty.
             One page dirtied per checkpoint cycle for the whole insert stream.

RANDOM:      every insert touches a DIFFERENT random leaf page.
             ⭐ Each one must be READ from disk (cache miss) and then DIRTIED.

At 1,000 inserts/sec into a 21 GB index that does not fit in cache:
    ~1,000 random page reads/sec + ~1,000 pages dirtied/sec
    = ~8 MB/s of random read + ~8 MB/s of eventual write,
      PURELY for index maintenance.
```

### Cost 3 — WAL amplification from full-page writes

This is the largest and least-known cost.

```
⭐ PostgreSQL writes a FULL PAGE IMAGE to the WAL the first time a page is
   modified after each checkpoint (full_page_writes = on, the default,
   required for torn-page protection).

SEQUENTIAL: the same rightmost page is dirtied repeatedly within a
            checkpoint cycle → ONE 8 KB full-page image, then small
            incremental records.

RANDOM:     ⭐ every insert hits a DIFFERENT page → a different
            "first touch after checkpoint" → an 8 KB FULL PAGE IMAGE
            for nearly EVERY INSERT.

    1,000 inserts/sec × 8 KB = 8 MB/s of WAL from index pages alone
    versus roughly 0.2 MB/s for sequential keys.

    ⭐ That is a 40× difference in WAL volume — which means 40× the
       replication bandwidth, 40× the archive storage, and 40× the
       WAL fsync load (Deep Dive 01 §12 — the same fsync that gates
       your consensus latency, if you run Patroni/etcd on the same disks).
```

### Cost 4 — heap access loses correlation

```
With a sequential PK, rows inserted together are physically adjacent
(correlation ≈ 1.0, §20). A range scan reads sequential heap pages.

With a random PK, rows inserted together are scattered across the heap.
⭐ Any index scan returning many rows does random heap I/O instead of
   sequential — often 10-100× slower, and it makes the planner
   correctly prefer a sequential scan much earlier.
```

### The fix: UUIDv7 or ULID

```
UUIDv4:  ffffffff-ffff-4fff-bfff-ffffffffffff
         ↑ 122 random bits. No ordering.

UUIDv7:  018f1a2b-3c4d-7xxx-yxxx-xxxxxxxxxxxx
         └──────┬──────┘
         48-bit Unix ms timestamp, then randomness.
         ⭐ Sortable by creation time. Sequential-ish insert pattern.
```

```sql
-- PostgreSQL 18 has uuidv7() built in. Before that:
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid AS $$
  SELECT encode(
    set_bit(
      set_bit(
        overlay(uuid_send(gen_random_uuid())
                PLACING substring(int8send((extract(epoch FROM clock_timestamp())
                                            * 1000)::bigint) FROM 3)
                FROM 1 FOR 6),
        52, 1),                      -- version 7
      53, 1),
    'hex')::uuid;
$$ LANGUAGE sql VOLATILE;
```

```
MEASURED IMPACT of switching UUIDv4 → UUIDv7 on a 500 M row table:
    index size:       21 GB → 11 GB
    WAL volume:       ~40× reduction on index writes
    insert throughput: 2-5× improvement on a cache-constrained system
    heap correlation:  ~0.02 → ~0.98
```

> **When UUIDv4 is still correct:** when the ID must not leak creation time (a security requirement), or must be unguessable as a capability. In those cases, use a sequential internal PK *and* a separate random external ID — index both, but let the sequential one be the clustering key. That is the standard pattern and it gets you both properties.

---

## 12. Deduplication (PG13) and posting lists

A significant space optimisation for low-cardinality indexes.

### The problem

```sql
CREATE INDEX idx_orders_status ON orders (status);
-- 50 million rows, 5 distinct status values
```

```
Before PG13, the index stored 50 million separate entries:
    ('pending', (0,1))   20 bytes
    ('pending', (0,2))   20 bytes
    ('pending', (0,3))   20 bytes
    ... 10 million times for 'pending' alone
    → ~1 GB index for 5 distinct values
```

### The fix: posting lists

```
PG13+ stores duplicates as ONE key with a POSTING LIST of TIDs:

    ('pending', [(0,1), (0,2), (0,3), (1,7), (1,9), ...])
      ↑ key stored ONCE       ↑ 6 bytes per TID
```

```
Space: ~20 bytes per unique key + 6 bytes per row
       instead of 20 bytes per row

⭐ For a 5-value index on 50 M rows: ~1 GB → ~300 MB
```

Deduplication is applied lazily — when a page is about to split, PostgreSQL first tries to deduplicate it, often avoiding the split entirely.

```sql
-- Check whether it is enabled (it requires the "allequalimage" property:
-- the opclass must guarantee that equal keys are interchangeable —
-- true for most types, false for e.g. numeric where 1.0 and 1.00 are
-- equal but not identical)
SELECT allequalimage FROM bt_metap('idx_orders_status');

-- It can be disabled per index
ALTER INDEX idx_orders_status SET (deduplicate_items = off);
```

> **Practical consequence:** low-cardinality indexes became much more viable in PG13. An index on a boolean or a small enum is no longer automatically wasteful — though a **partial index** (§16) is usually still better if you only query one of the values.

---

## 13. Bottom-up index deletion (PG14) ⭐

One of the most impactful PostgreSQL changes of recent years, and it directly addresses the non-HOT update problem from Deep Dive 04 §11.

### The problem

```
UPDATE users SET status = 'active' WHERE id = 42;      -- status IS indexed
```

Every such update creates a **new index entry** and leaves the old one dead. On a frequently-updated indexed column, the index fills with **version churn** — many entries for the same logical row, all but one dead.

```
Index leaf page for status='active':
    ('active', (5,1))  ← dead (old version of row A)
    ('active', (5,2))  ← dead (old version of row A)
    ('active', (5,3))  ← dead (old version of row A)
    ('active', (5,4))  ← LIVE  (current version of row A)
    ('active', (9,1))  ← dead (old version of row B)
    ...

Pre-PG14: the page fills with these, then SPLITS.
          → the index grows, permanently, from pure version churn.
          → and VACUUM is the only thing that ever cleans it.
```

### The fix

```
⭐ When a leaf page is about to split, PostgreSQL first checks whether the
   page contains many entries that look like VERSION DUPLICATES (several
   entries with the same key pointing at nearby heap TIDs).

   If so, it visits those heap pages and checks which versions are dead,
   then deletes those index entries — WITHOUT waiting for VACUUM.

   The split is avoided entirely.
```

```
RESULT for an update-heavy indexed column:
    Pre-PG14:  index grows without bound between vacuums
    PG14+:     ⭐ index size stays essentially CONSTANT — the page
               self-cleans at exactly the moment it matters
```

**This is targeted precisely at the case where HOT updates are impossible** (because an indexed column changed). It does not remove the reason to prefer HOT, but it turns "unbounded index bloat" into "bounded index size" for workloads that cannot avoid non-HOT updates.

```sql
-- Verify you benefit: an update-heavy table with an indexed hot column
SELECT relname, n_tup_upd, n_tup_hot_upd,
       round(100.0*n_tup_hot_upd/NULLIF(n_tup_upd,0),1) AS hot_pct
FROM pg_stat_user_tables WHERE n_tup_upd > 100000 ORDER BY n_tup_upd DESC;
-- Low hot_pct + PG14+ → bottom-up deletion is doing real work for you.
-- Low hot_pct + PG13 or earlier → ⭐ upgrading is worth real money here.
```

---

## 14. Multicolumn indexes: why leftmost-prefix

The map stated the rule. Here is the mechanism.

```sql
CREATE INDEX idx ON t (a, b, c);
```

**The index is sorted by `(a, b, c)` lexicographically** — like a phone book sorted by (surname, first name, middle name).

```
Leaf entries, in order:

  (1, 'alpha',  10)
  (1, 'alpha',  20)
  (1, 'beta',    5)
  (1, 'beta',   99)
  (2, 'alpha',   1)
  (2, 'gamma',  50)
  (3, 'alpha',   7)
```

### Why each query shape works or does not

```
WHERE a = 2
    ⭐ All a=2 entries are CONTIGUOUS. Descend once, scan forward. ✓

WHERE a = 2 AND b = 'alpha'
    ⭐ Within a=2, b is sorted. Contiguous. ✓

WHERE a = 2 AND b = 'alpha' AND c = 1
    ⭐ Fully specified. A single entry. ✓

WHERE b = 'alpha'
    ❌ 'alpha' entries are at offsets 1, 2, 5, 7 — SCATTERED throughout.
       There is no contiguous range. The index gives no help in locating
       them, so a full index scan would be needed — usually worse than
       a sequential scan.

WHERE a = 2 AND c = 1
    ⚠ PARTIAL. Descend to a=2 (contiguous), then scan ALL a=2 entries
      and filter on c. Useful if a=2 is selective; useless if not.
      EXPLAIN shows this as:
          Index Cond: (a = 2)
          Filter: (c = 1)              ← ⭐ the tell-tale sign

WHERE a > 5 AND b = 'alpha'
    ⚠ Once you use a RANGE on a, b is no longer contiguous within it.
      Index Cond: (a > 5), then b is a filter.
      ⭐ This is why the rule is "equality columns FIRST, range LAST".
```

### The skip-scan caveat

PostgreSQL historically had no "index skip scan" (unlike Oracle and MySQL 8), so `WHERE b = 'alpha'` genuinely could not use `idx(a,b,c)`. PostgreSQL 18 added skip scan support, which can use a leading column with low cardinality by probing each distinct value.

**Do not rely on it for design.** The rule stands: put the columns you filter on by equality first, in descending order of selectivity, and range/sort columns last. Skip scan is a recovery mechanism for indexes you already have, not a licence to ignore column order.

### Choosing column order — the decision procedure

```
1. Equality predicates first
2. Among equality columns: MOST SELECTIVE first
   (exception: if one column is in EVERY query and another only sometimes,
    put the always-present one first even if less selective)
3. Range predicates next
4. ORDER BY columns last, in ORDER BY order, with matching ASC/DESC
5. Columns only SELECTed (never filtered) → INCLUDE, not a key column (§15)
```

```sql
-- Query: WHERE tenant_id = ? AND status = ? AND created_at > ? ORDER BY created_at DESC
CREATE INDEX ON sessions (tenant_id, status, created_at DESC);
--                        └ equality ┘ └equality┘ └ range + sort ┘
```

---

## 15. Covering indexes and INCLUDE

```sql
CREATE INDEX idx_sessions_lookup
    ON sessions (tenant_id, status)          -- KEY columns: searchable, sorted
    INCLUDE (score, created_at);             -- ⭐ PAYLOAD: stored in leaves only
```

### The mechanism

```
KEY columns:
  • stored in BOTH internal and leaf pages
  • participate in the sort order
  • usable in WHERE and ORDER BY
  • ⭐ count against the index tuple size limit and reduce fan-out

INCLUDE columns:
  • stored ONLY in leaf pages
  • NOT part of the sort order
  • NOT usable for searching
  • ⭐ do NOT reduce internal-page fan-out → the tree stays shallow
  • can be types with no B-tree opclass at all (e.g. point, json)
```

### Why this matters

```sql
SELECT score, created_at FROM sessions WHERE tenant_id = $1 AND status = 'pending';
```

```
WITHOUT INCLUDE:
    Index Scan → find matching TIDs → FETCH EACH HEAP TUPLE for score/created_at
    → 1 index read + N random heap reads

WITH INCLUDE:
    Index Only Scan → everything needed is in the leaf
    → 1 index read, ZERO heap reads   ⭐ (subject to the visibility map, §18)
```

### INCLUDE vs adding key columns

```sql
-- Option A
CREATE INDEX ON sessions (tenant_id, status, score, created_at);
-- Option B
CREATE INDEX ON sessions (tenant_id, status) INCLUDE (score, created_at);
```

| | Option A (all key) | Option B (INCLUDE) |
|---|---|---|
| Internal page fan-out | Lower (bigger keys) → possibly taller tree | **Unchanged** |
| Can search on `score` | Yes | No |
| Can `ORDER BY score` | Yes | No |
| Unique constraint on the key | Would include score | ⭐ **Can be UNIQUE on (tenant_id, status) alone** |
| Deduplication | Less effective | More effective |

> **Use INCLUDE when the extra columns are only ever *returned*, never *searched*.** The unique-constraint case is the strongest argument: `CREATE UNIQUE INDEX ON t (email) INCLUDE (name, created_at)` gives you a uniqueness guarantee *and* index-only scans for a common query, which adding the columns to the key would destroy.

---

## 16. Partial indexes

The most under-used PostgreSQL feature, and often a 100× space saving.

```sql
CREATE INDEX idx_sessions_pending
    ON sessions (created_at)
    WHERE status = 'pending';
```

### The mechanism

**Only rows satisfying the predicate get an index entry.** The predicate is stored in `pg_index.indpred`.

```
Table: 50,000,000 sessions.  0.2% are 'pending' → 100,000 rows.

Full index on (status, created_at):  50 M entries  ≈ 1.5 GB
Partial index:                      100 K entries  ≈ 3 MB

⭐ 500× smaller. Permanently in cache. And crucially:
   ⭐ INSERTs and UPDATEs of non-pending rows do not touch it AT ALL —
      so it costs almost nothing to maintain.
```

### When the planner will use it

The planner must *prove* that the query's predicate implies the index's predicate.

```sql
-- ✓ USES the index — exact match
SELECT * FROM sessions WHERE status = 'pending' ORDER BY created_at;

-- ✓ USES it — 'pending' AND something is implied by 'pending'
SELECT * FROM sessions WHERE status = 'pending' AND tenant_id = $1;

-- ❌ Does NOT use it — cannot prove status = 'pending'
SELECT * FROM sessions WHERE created_at > now() - interval '1 hour';

-- ❌ Does NOT use it — the planner cannot reason through a parameter
SELECT * FROM sessions WHERE status = $1;      -- ⭐ even if $1 IS 'pending'
```

**That last case catches people out.** A parameterised query cannot use a partial index whose predicate depends on the parameter's value, because the plan is chosen before the value is known (unless a custom plan is generated — which PostgreSQL may do for the first five executions; see `plan_cache_mode`).

### The highest-value uses

```sql
-- 1. ⭐ Soft deletes — the single most common win
CREATE INDEX ON orders (customer_id) WHERE deleted_at IS NULL;
--   Typically 95%+ of queries filter on this. The index excludes all
--   the dead rows, and deleting a row does not touch the index.

-- 2. Work queues — the "pending" set is tiny, the table is huge
CREATE INDEX ON jobs (priority, created_at) WHERE state = 'queued';

-- 3. ⭐ Conditional uniqueness — cannot be expressed any other way
CREATE UNIQUE INDEX ON users (email) WHERE deleted_at IS NULL;
--   Allows the same email to be reused after a soft delete.

-- 4. Excluding a dominant value that is never queried
CREATE INDEX ON events (user_id) WHERE event_type != 'heartbeat';

-- 5. Recent data only
CREATE INDEX ON logs (user_id, ts) WHERE ts > '2026-01-01';
--   ⚠ Requires periodic recreation as the window moves. Partitioning
--     is usually better for this one.
```

> **The soft-delete partial index is the highest-value single index change in most applications**, and almost nobody has it. Check: `SELECT count(*) FROM your_table WHERE deleted_at IS NOT NULL;` — if that is a meaningful fraction, every index on that table should have `WHERE deleted_at IS NULL`.

---

## 17. Expression indexes and the planner's blind spot

```sql
-- ❌ The index on (email) is USELESS here — the function changes the value
SELECT * FROM users WHERE lower(email) = 'a@b.com';

-- ✅ Index the EXPRESSION
CREATE INDEX idx_users_email_lower ON users (lower(email));
```

**The requirement: the expression must be `IMMUTABLE`.** The same input must always give the same output, forever, on any machine.

```sql
-- ❌ Rejected — now() is not immutable
CREATE INDEX ON orders ((created_at > now()));

-- ⚠ DANGEROUS — this is marked immutable but is NOT, because the output
--   depends on the session TimeZone setting:
CREATE INDEX ON orders ((created_at::date));       -- timestamptz → date
--   → the index can silently return WRONG results for sessions with a
--     different TimeZone. Use an explicit zone:
CREATE INDEX ON orders (((created_at AT TIME ZONE 'UTC')::date));
```

### The statistics blind spot ⭐

This is the subtle part that costs people real query performance.

```sql
CREATE INDEX idx_meta_channel ON sessions ((metadata->>'channel'));

SELECT * FROM sessions WHERE metadata->>'channel' = 'mobile';
```

```
⭐ PostgreSQL has NO STATISTICS for the expression metadata->>'channel'
   until ANALYZE runs after the index is created.

   Without them, the planner uses a default selectivity estimate of 0.5%
   for an equality on an unknown expression — which may be wildly wrong
   (if 80% of rows are 'mobile', the planner will pick an index scan
   that reads 80% of the table via random I/O).
```

```sql
-- ⭐ ALWAYS run this after creating an expression index
ANALYZE sessions;

-- Creating the index causes PostgreSQL to collect stats on the expression:
SELECT attname, n_distinct, most_common_vals
FROM pg_stats WHERE tablename = 'idx_meta_channel';
--     attname     | n_distinct |    most_common_vals
-- ----------------+------------+-------------------------
--  expr           |          4 | {mobile,web,api,sdk}   ⭐ now the planner knows
```

**PostgreSQL 14+ offers an alternative without the index**, useful when you want statistics but not the maintenance cost:

```sql
CREATE STATISTICS stat_channel ON (metadata->>'channel') FROM sessions;
ANALYZE sessions;
```

---

## 18. Index scan, index-only scan, bitmap scan

Three different plan nodes, three different access patterns.

### Index Scan

```
For each matching index entry, in index order:
    1. read the index leaf page
    2. ⭐ fetch the heap tuple (random I/O)
    3. check visibility (Deep Dive 04 §7)
    4. return the row

Good for: few rows (high selectivity), or when index order matches ORDER BY
Bad for:  many rows → many random heap reads
```

### Index Only Scan

```
Same, but step 2 is SKIPPED when the visibility map says the heap page is
ALL_VISIBLE (Deep Dive 04 §23).

Requirements:
  • every column the query needs is in the index (key or INCLUDE)
  • ⭐ the heap pages are marked all-visible → REQUIRES RECENT VACUUM
```

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT tenant_id, status FROM sessions WHERE tenant_id = $1;

-- Index Only Scan using idx_sessions_tenant_status on sessions
--   Heap Fetches: 0            ⭐ perfect
--   Buffers: shared hit=8

-- versus a table that has not been vacuumed:
--   Heap Fetches: 48213        ⭐ it is "index only" in name only
```

> **`Heap Fetches` is the metric.** A non-zero value on an Index Only Scan means "vacuum this table more often" (Deep Dive 04 §18) — not "rewrite this query".

### Bitmap Heap Scan

```
PHASE 1 — Bitmap Index Scan
    Scan the index, collecting matching TIDs into an in-memory BITMAP.
    ⭐ No heap access at all yet.

PHASE 2 — Bitmap Heap Scan
    ⭐ Sort/traverse the bitmap in PHYSICAL page order, then read each
       heap page ONCE, extracting all matching tuples from it.
```

**Why this wins for medium selectivity:**

```
An index scan returning 50,000 rows scattered across 30,000 heap pages:
    Index Scan:  50,000 random page reads (some pages read repeatedly)
    Bitmap Scan: 30,000 reads, in ascending page order → the OS and the
                 storage layer can READ AHEAD. Often 5-10× faster.
```

**And it can combine indexes:**

```sql
EXPLAIN SELECT * FROM sessions WHERE tenant_id = $1 AND status = 'failed';

-- Bitmap Heap Scan on sessions
--   Recheck Cond: ((tenant_id = $1) AND (status = 'failed'))
--   -> BitmapAnd                          ⭐ intersect two bitmaps
--        -> Bitmap Index Scan on idx_sessions_tenant
--        -> Bitmap Index Scan on idx_sessions_status
```

**This is why "one index per column" is not always wrong** — the planner can `BitmapAnd` them. But a single composite index is still far better when the combination is common, because it avoids building and intersecting two bitmaps.

---

## 19. Bitmap scans, work_mem and lossy bitmaps

The detail that explains a specific class of slow query.

### The bitmap has two representations

```
EXACT (per-tuple):  one bit per heap TUPLE
                    → the heap scan returns exactly the matching tuples

LOSSY (per-page):   one bit per heap PAGE
                    → ⭐ the heap scan must RE-CHECK every tuple on that page
```

### The transition

```
The bitmap is built in work_mem. When it does not fit, PostgreSQL
DEGRADES portions of it to page-level granularity to save space.

⭐ Once a page is lossy, every tuple on it must be re-examined against
   the original condition — which means reading and evaluating ~200 tuples
   to find the 3 that match.
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM events WHERE tenant_id = $1 AND created_at > now() - interval '7 days';

-- Bitmap Heap Scan on events  (actual time=245.1..8934.2 rows=482911)
--   Recheck Cond: (...)
--   Rows Removed by Index Recheck: 12849201        ⭐⭐ THE SMOKING GUN
--   Heap Blocks: exact=8214 lossy=412903           ⭐⭐ mostly lossy
--   Buffers: shared hit=12 read=421117
```

**Reading this:** 12.8 million tuples were read from the heap and thrown away, because 412,903 pages were lossy and every tuple on each had to be rechecked. The query returned 482,911 rows and examined 13.3 million.

```sql
-- The fix
SET work_mem = '256MB';       -- ⭐ per-operation, per-connection — be careful
-- Re-run:
--   Heap Blocks: exact=421117 lossy=0
--   Rows Removed by Index Recheck: 0
--   actual time=245.1..1102.4        ⭐ 8× faster
```

### Sizing work_mem for bitmaps

```
Exact bitmap: ~1 bit per tuple in the TABLE (not per matching tuple),
              plus per-page overhead.

A 100 M row table needs roughly 100,000,000 / 8 = 12.5 MB for a fully
exact bitmap. The default work_mem of 4 MB is not enough.

⭐ Setting work_mem = 64MB is a reasonable baseline for OLTP systems that
   run bitmap scans, BUT note: work_mem is per SORT/HASH/BITMAP NODE,
   per connection. 200 connections × 3 nodes × 64 MB = 38 GB of potential
   allocation. Size it against max_connections, or set it per-query:

     SET LOCAL work_mem = '256MB';   -- inside a transaction, for one query
```

---

## 20. Correlation: the statistic that decides everything

```sql
SELECT attname, correlation, n_distinct
FROM pg_stats WHERE tablename = 'events';
--   attname    | correlation | n_distinct
-- -------------+-------------+------------
--  created_at  |    0.999812 |         -1    ⭐ physical order ≈ logical order
--  tenant_id   |    0.023411 |        847    ⭐ scattered
--  id_uuid     |   -0.001204 |         -1    ⭐ random
```

**Correlation ranges from −1 to 1** and measures how well the physical row order on disk matches the sorted order of that column.

### Why the planner cares enormously

```
An index scan returning 10,000 rows:

correlation ≈ 1.0:
    ⭐ The matching heap tuples are in ~50 CONSECUTIVE pages.
       Sequential read. Fast. The planner costs this cheaply and will
       happily choose an index scan even for a large fraction of the table.

correlation ≈ 0.0:
    ⭐ The 10,000 tuples are spread over ~9,500 DIFFERENT pages.
       Random read. The planner costs this at random_page_cost (default 4.0,
       ⭐ which should be 1.1 on SSDs) and will often switch to a
       sequential scan instead.
```

```sql
-- ⭐ One of the highest-value single settings on modern hardware.
-- The default of 4.0 assumes a spinning disk where a random read costs
-- 4× a sequential one. On NVMe it is closer to 1.1.
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_cache_size = '24GB';   -- ~75% of RAM; a HINT, not an allocation
SELECT pg_reload_conf();
```

Leaving `random_page_cost` at 4.0 on SSD storage causes the planner to systematically avoid index scans it should use — one of the most common misconfigurations in the field.

### Improving correlation

```sql
-- CLUSTER physically reorders the table to match an index.
-- ⚠ Takes ACCESS EXCLUSIVE. Not maintained — new rows go wherever they fit.
CLUSTER events USING idx_events_created_at;

-- Online alternative:
-- pg_repack -t events -o created_at

-- ⭐ Better structural answer: PARTITION by the correlated column.
--    Each partition is naturally clustered, correlation stays high
--    forever, and old partitions can be dropped (§9).
```

**And note the connection back to §11:** a sequential primary key gives you correlation ≈ 1.0 for free, forever, with no maintenance. A random UUID gives you correlation ≈ 0.0 and no way to fix it short of `CLUSTER`. That is Cost 4 from §11, now quantified through the planner's cost model.

---

## 21. GIN internals — the pending list trap

**GIN** = Generalized Inverted iNdex. For values containing *multiple* searchable items: arrays, `jsonb`, full-text vectors, trigrams.

### The structure

```
                 ENTRY TREE (a B-tree over the individual ITEMS)
                 ┌──────────────────────────────┐
                 │ 'liveness' │ 'session' │ ...  │
                 └─────┬───────────┬────────────┘
                       │           │
          ┌────────────┘           └──────────┐
          ▼                                    ▼
   POSTING LIST                         POSTING TREE
   (few TIDs — stored inline)           (many TIDs — a B-tree of TIDs)
   [(0,1),(0,4),(3,2)]                  ┌────────────────┐
                                        │  B-tree of TIDs │
                                        └────────────────┘
```

**The key idea:** one document containing 100 words produces 100 entries in the entry tree, each pointing at this document's TID. A search for one word finds its posting list directly.

### The pending list ⭐ — where the operational surprises live

```
GIN inserts are EXPENSIVE: one row with 100 array elements = 100 entry-tree
insertions, each potentially splitting pages.

⭐ To make inserts fast, GIN has FASTUPDATE (default ON):
   New entries go into an unsorted PENDING LIST — a simple appended page
   chain — instead of being merged into the tree.
```

**This creates three problems:**

```
1. ⭐ SEARCHES MUST SCAN THE ENTIRE PENDING LIST, linearly, in addition to
      the tree. A large pending list makes every query slower.

2. ⭐ THE FLUSH IS A LATENCY CLIFF. When the pending list exceeds
      gin_pending_list_limit (default 4 MB), the NEXT UNLUCKY INSERT
      performs the entire merge, synchronously.
      → one INSERT out of thousands takes 2 seconds.
      → This shows up as inexplicable p99 latency spikes.

3. VACUUM also flushes it, so vacuum timing affects query latency.
```

```sql
-- Diagnose
SELECT * FROM pgstatginindex('idx_documents_fts');
--  version | pending_pages | pending_tuples
-- ---------+---------------+----------------
--        2 |           491 |         214882    ⭐ 491 pages scanned per query

-- Option A: disable fastupdate — slower, PREDICTABLE inserts
ALTER INDEX idx_documents_fts SET (fastupdate = off);
REINDEX INDEX CONCURRENTLY idx_documents_fts;

-- Option B: keep it, but bound the list so flushes are small and frequent
ALTER INDEX idx_documents_fts SET (gin_pending_list_limit = '512kB');
```

> **Rule of thumb:** for a **latency-sensitive OLTP** workload, set `fastupdate = off` — predictable is better than fast-on-average. For a **bulk-load-then-query** workload, leave it on and flush explicitly with `VACUUM` after loading.

### GIN operator classes worth knowing

```sql
-- jsonb: two choices, and the difference is significant
CREATE INDEX ON docs USING GIN (data);                  -- jsonb_ops (default)
--   indexes every key AND every value → larger, supports ?, ?|, ?&, @>

CREATE INDEX ON docs USING GIN (data jsonb_path_ops);   -- ⭐ smaller, faster
--   indexes only the hashed key-value PATHS → ~3× smaller
--   supports ONLY @> (containment) — which is usually all you need

-- Trigram search — makes LIKE '%substring%' indexable
CREATE EXTENSION pg_trgm;
CREATE INDEX ON users USING GIN (name gin_trgm_ops);
SELECT * FROM users WHERE name ILIKE '%delow%';         -- ⭐ now uses the index

-- Full-text
CREATE INDEX ON docs USING GIN (to_tsvector('english', body));
-- ⭐ Better: store the tsvector as a generated column so it is computed once
ALTER TABLE docs ADD COLUMN body_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', body)) STORED;
CREATE INDEX ON docs USING GIN (body_tsv);
```

---

## 22. GiST internals — penalty and picksplit

**GiST** = Generalized Search Tree. Not one index type — a **framework** for building balanced trees over arbitrary data, where internal nodes store a *predicate* that covers everything beneath them.

### The structure

```
Internal node entries are PREDICATES, not keys:

    for geometry:   a bounding box covering all children
    for ranges:     a range covering all child ranges
    for tsvector:   a signature (bloom-filter-like) of all child terms

              ┌──────────────────────────────────┐
              │ BOX(0,0,100,100) │ BOX(50,50,200,200) │   ⭐ these may OVERLAP
              └────────┬─────────┴─────────┬──────────┘
                       ▼                    ▼
                 children                children

⭐ Because predicates can overlap, a search may need to descend MULTIPLE
   branches. This is fundamentally different from a B-tree, where the
   key ranges are disjoint and exactly one child matches.
```

### The seven functions you would implement

```c
consistent()   /* Could this subtree contain a match? (may say yes wrongly — LOSSY) */
union()        /* Compute a predicate covering a set of entries */
compress()     /* Convert a value into its indexable form */
decompress()   /* The inverse */
penalty()      /* ⭐ Cost of adding an entry to this subtree — drives INSERT */
picksplit()    /* ⭐ How to divide a full page into two — drives QUALITY */
same()         /* Predicate equality */
```

**`penalty` and `picksplit` determine the entire quality of the index.**

```
penalty:    for bounding boxes, typically "how much would this box GROW?"
            → inserts go where they cause the least expansion
            → keeps boxes tight → fewer branches to search

picksplit:  a bad split creates two heavily OVERLAPPING boxes,
            so every search descends both, and performance collapses.
            ⭐ Good picksplit implementations (e.g. the Guttman quadratic
               split) are what separate a usable spatial index from a
               useless one.
```

### GiST's `consistent` is lossy — and that is the point

```
consistent() may return TRUE for a subtree that contains no actual match
(a bounding box overlaps your query box, but no actual geometry inside does).

⭐ So GiST results MUST be rechecked against the real values.
   EXPLAIN shows this as "Rows Removed by Index Recheck".
   That is normal for GiST, unlike for B-tree.
```

### What GiST is actually for

```sql
-- 1. ⭐ EXCLUSION CONSTRAINTS — makes overlapping bookings IMPOSSIBLE
CREATE EXTENSION btree_gist;
ALTER TABLE bookings ADD CONSTRAINT no_overlap
    EXCLUDE USING GIST (room_id WITH =, during WITH &&);
--   ⭐ This is a write-skew fix at the database level (Deep Dive 03 §9).
--      No application logic. No race condition. No serializable isolation needed.

-- 2. Range queries
CREATE INDEX ON reservations USING GIST (during);
SELECT * FROM reservations WHERE during && '[2026-09-01,2026-09-08)'::tstzrange;

-- 3. Geospatial (PostGIS)
CREATE INDEX ON places USING GIST (location);
SELECT * FROM places WHERE ST_DWithin(location, ST_MakePoint(90.4,23.8)::geography, 5000);

-- 4. ⭐ K-nearest-neighbour — GiST supports ORDER BY distance natively
SELECT *, location <-> ST_MakePoint(90.4,23.8) AS dist
FROM places ORDER BY location <-> ST_MakePoint(90.4,23.8) LIMIT 10;
--   The index returns rows in distance order — no sort node needed.
```

> **The exclusion constraint is the one to remember.** It solves a correctness problem (double-booking) that would otherwise require serializable isolation and retry logic, and it solves it at the storage layer where nothing can bypass it.

---

## 23. SP-GiST, and what it is for

**SP-GiST** = Space-Partitioned GiST. For **non-balanced**, **disjoint** partitioning structures — quadtrees, k-d trees, radix tries.

```
The key difference from GiST:
    GiST:     partitions may OVERLAP → a search may descend several branches
    SP-GiST:  partitions are DISJOINT → exactly one branch matches
              ⭐ but the tree may be UNBALANCED
```

**Where it wins:**

```sql
-- 1. ⭐ Text prefix search via a radix trie — much smaller than a B-tree
CREATE INDEX ON domains USING SPGIST (name text_ops);
SELECT * FROM domains WHERE name LIKE 'example%';

-- 2. IP address containment (the inet type's natural structure is a trie)
CREATE INDEX ON firewall_rules USING SPGIST (cidr_range inet_ops);
SELECT * FROM firewall_rules WHERE cidr_range >>= '10.0.4.7'::inet;

-- 3. Point data with a quadtree — often faster than GiST for pure points
CREATE INDEX ON locations USING SPGIST (coords);
```

**Awareness is enough** for most people. Reach for it when you have prefix/containment queries on text or `inet`, where a radix structure matches the data far better than a balanced tree does.

---

## 24. BRIN internals — tiny indexes, one hard requirement

**BRIN** = Block Range INdex. The smallest index type by orders of magnitude, with one absolute prerequisite.

### The structure

```
Instead of one entry per ROW, BRIN stores a SUMMARY per RANGE OF PAGES.

pages_per_range = 128 (default) → one summary per 128 pages = 1 MB of table

  range 0   (pages   0-127): min=2026-01-01 09:00, max=2026-01-01 09:14
  range 1   (pages 128-255): min=2026-01-01 09:14, max=2026-01-01 09:29
  range 2   (pages 256-383): min=2026-01-01 09:29, max=2026-01-01 09:41
  ...

Query: WHERE created_at BETWEEN '09:25' AND '09:35'
  ⭐ range 0: max 09:14 < 09:25  → SKIP entirely
  ⭐ range 1: overlaps           → scan its 128 pages
  ⭐ range 2: overlaps           → scan its 128 pages
  ⭐ ranges 3+: min > 09:35      → SKIP
```

### The size

```
A 1 TB table, pages_per_range = 128:
    1 TB / 8 KB = 134,217,728 pages
    134,217,728 / 128 = 1,048,576 ranges
    × ~32 bytes per summary
    = ⭐ 33 MB

    A B-tree on the same column: ~30 GB.
    ⭐ BRIN is ~1000× smaller and fits entirely in cache.
```

### The hard requirement: correlation

```
⭐ BRIN ONLY WORKS IF THE PHYSICAL ORDER CORRELATES WITH THE VALUE.

correlation ≈ 1.0  → each range has a tight min/max → excellent pruning
correlation ≈ 0.0  → ⭐ EVERY range has min≈global_min, max≈global_max
                      → NOTHING can be pruned
                      → the index is worse than useless: it costs space
                        and the planner may still choose it and then
                        scan the entire table
```

```sql
-- ⭐ CHECK THIS BEFORE CREATING A BRIN INDEX. Always.
SELECT attname, correlation FROM pg_stats
WHERE tablename = 'events' AND attname = 'created_at';
--  attname    | correlation
-- ------------+-------------
--  created_at |    0.999812    ✅ BRIN is an excellent choice

-- correlation < 0.9 → BRIN will not help. Use B-tree, or CLUSTER first.
```

### Tuning and maintenance

```sql
CREATE INDEX idx_events_brin ON events USING BRIN (created_at)
    WITH (pages_per_range = 32,     -- ⭐ smaller = more precise, larger index
          autosummarize = on);      -- ⭐ summarise new ranges automatically

-- ⚠ WITHOUT autosummarize, ranges created since the last VACUUM are
--   UNSUMMARIZED and are always scanned. On an append-heavy table this
--   silently degrades the index until VACUUM runs.
SELECT brin_summarize_new_values('idx_events_brin');   -- manual catch-up

-- Inspect what the index actually contains
SELECT * FROM brin_page_items(get_raw_page('idx_events_brin', 2), 'idx_events_brin');
```

**`pages_per_range` trade-off:**

```
128 (default):  smallest index, coarsest pruning — scan ≥1 MB per hit
 32:            4× larger index, 4× finer pruning — scan ≥256 KB per hit
  8:            16× larger, finest — approaching B-tree size with B-tree-like precision

⭐ 32 is a good starting point for a time-series table where queries
   target windows of minutes rather than days.
```

### The bloom operator class (PG14+)

```sql
-- ⭐ For EQUALITY on a column that is NOT correlated but IS low-cardinality
CREATE INDEX ON events USING BRIN (tenant_id uuid_bloom_ops);
--   Each range stores a BLOOM FILTER of the values it contains.
--   "Does range 42 contain tenant X?" → probabilistic, but no false negatives.
--   ⭐ Works without correlation — a genuinely different tool.
```

> **BRIN's ideal case is the append-only time-series table** (Chapter 12) — and it is also the case where a B-tree bloats forever (§9). For an events table partitioned by month with a BRIN on the timestamp, you get a tiny index, no bloat, and instant partition drops. That combination is the correct design for high-volume log/event data, and it is worth recognising.

---

## 25. Hash indexes — finally usable

```sql
CREATE INDEX ON sessions USING HASH (session_token);
```

### The history matters

```
Before PostgreSQL 10:
    ❌ NOT WAL-logged → not crash safe, not replicated
    → the documentation actively recommended against them
    → an entire generation of engineers learned "never use hash indexes"

PostgreSQL 10+:
    ✅ WAL-logged, crash safe, replicated
    ✅ Genuinely useful for one specific case
```

### When a hash index is actually better

```
⭐ Equality lookups on LARGE values.

A B-tree on a 200-byte token stores the full 200 bytes in every index entry.
A hash index stores a 4-byte hash.

    B-tree index on a 200-byte column, 50 M rows:  ~11 GB
    Hash index on the same column:                  ~2 GB
```

### The limitations

```
❌ Equality only. No <, >, BETWEEN, ORDER BY, LIKE 'prefix%'
❌ No multicolumn hash indexes
❌ Cannot back a UNIQUE constraint      ⭐ the most common blocker
❌ No index-only scans (the original value is not stored)
❌ Splitting a bucket is more disruptive than a B-tree page split
```

> **Practical verdict:** a real but narrow win. Use it for large-token equality lookups where you do not need uniqueness enforcement. For everything else, B-tree — and note that an **expression index on a hash** (`CREATE INDEX ON t (md5(token))`) gives you similar size benefits *plus* B-tree's other capabilities, and is often the better choice.

---

## 26. The cost of an index, quantified

Every index is a permanent tax. Here is the bill.

### Write amplification

```
INSERT into a table with N indexes:
    1 heap tuple write
  + N index entries
  + N potential page splits
  + WAL for all of it (⭐ including full-page images on first touch
    after a checkpoint — §11)

A 6-index table, measured:
    INSERT throughput vs the same table with only a PK: ~40% slower
    WAL generated per insert: ~4× more
```

### Update amplification

```
UPDATE that changes ONE indexed column, on a 6-index table:
    ⭐ Non-HOT (Deep Dive 04 §12) → 6 new index entries + 6 dead ones
    Even though only ONE index's column changed.

    Because the tuple MOVED, every index must point at the new location.
```

**That is the single strongest argument for keeping index count low on update-heavy tables** — and for `fillfactor` + HOT, which avoids the whole cost.

### Space

```
Rule of thumb: indexes total 0.5× to 3× the table size.

SELECT pg_size_pretty(pg_table_size(c.oid))    AS heap,
       pg_size_pretty(pg_indexes_size(c.oid))  AS indexes,
       round(pg_indexes_size(c.oid)::numeric
             / NULLIF(pg_table_size(c.oid),0), 2) AS ratio
FROM pg_class c WHERE c.relname = 'orders';
--   heap   | indexes | ratio
-- ---------+---------+-------
--  8192 MB | 21 GB   |  2.63    ⭐ indexes are 2.6× the table — audit them
```

### Planning time

```
More indexes = more paths for the planner to consider.
With 15 indexes on a table, planning time for a multi-table join can
exceed execution time for a simple query.

EXPLAIN (ANALYZE) shows:
    Planning Time: 8.412 ms
    Execution Time: 0.891 ms     ⭐ planning dominates
```

---

## 27. The index audit

Run these on every production database. They reliably find real waste.

### 1. Unused indexes

```sql
SELECT s.schemaname, s.relname AS table, s.indexrelname AS index,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       s.idx_scan AS scans
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan < 50
  AND NOT i.indisunique                        -- ⭐ never drop unique indexes
  AND NOT i.indisprimary
  AND pg_relation_size(s.indexrelid) > 10*1024*1024
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

**Caveats before you drop:**
- `pg_stat_user_indexes` counters reset on `pg_stat_reset()` and on crash. Check `pg_postmaster_start_time()` and `stats_reset`.
- An index used only by a quarterly report will show zero scans for months.
- ⭐ **Check replicas separately** — an index unused on the primary may be critical on a read replica.
- Safer than dropping: `UPDATE pg_index SET indisvalid = false WHERE indexrelid = '...'::regclass;` — the planner ignores it but it is still maintained, so you can re-enable it instantly if something breaks. Drop it a week later.

### 2. Duplicate and redundant indexes

```sql
-- Exact duplicates
SELECT pg_size_pretty(sum(pg_relation_size(idx))::bigint) AS wasted,
       array_agg(idx::regclass) AS duplicates
FROM (
  SELECT indexrelid AS idx,
         indrelid::text||'|'||indclass::text||'|'||indkey::text||'|'||
         coalesce(indexprs::text,'')||'|'||coalesce(indpred::text,'') AS sig
  FROM pg_index
) s GROUP BY sig HAVING count(*) > 1;

-- ⭐ REDUNDANT: idx(a) is entirely covered by idx(a,b) — drop idx(a)
SELECT a.indexrelid::regclass AS redundant,
       b.indexrelid::regclass AS covered_by,
       pg_size_pretty(pg_relation_size(a.indexrelid)) AS reclaimable
FROM pg_index a
JOIN pg_index b ON a.indrelid = b.indrelid
                AND a.indexrelid <> b.indexrelid
                AND array_to_string(b.indkey,' ') LIKE array_to_string(a.indkey,' ')||'%'
WHERE NOT a.indisunique AND NOT a.indisprimary;
```

The redundancy check is the one that finds the most waste in practice — teams add `(tenant_id)` and later `(tenant_id, created_at)` without removing the first.

### 3. Bloated indexes

```sql
CREATE EXTENSION IF NOT EXISTS pgstattuple;

SELECT indexrelname,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       round((pgstatindex(indexrelid)).avg_leaf_density::numeric, 1) AS leaf_density,
       round((pgstatindex(indexrelid)).leaf_fragmentation::numeric, 1) AS fragmentation
FROM pg_stat_user_indexes
WHERE pg_relation_size(indexrelid) > 100*1024*1024
ORDER BY pg_relation_size(indexrelid) DESC;

-- ⭐ avg_leaf_density below 60 → REINDEX INDEX CONCURRENTLY
--    But first ask WHY (§9). If it is the delete-old-rows pattern,
--    REINDEX is a treadmill and partitioning is the real fix.
```

### 4. Missing indexes

```sql
-- Tables doing heavy sequential scanning
SELECT relname,
       seq_scan, seq_tup_read,
       idx_scan,
       seq_tup_read / NULLIF(seq_scan,0) AS avg_rows_per_seq_scan,
       pg_size_pretty(pg_relation_size(relid)) AS size
FROM pg_stat_user_tables
WHERE seq_scan > 1000 AND pg_relation_size(relid) > 50*1024*1024
ORDER BY seq_tup_read DESC LIMIT 20;

-- ⚠ A high seq_scan count is NOT automatically bad. Small tables SHOULD
--   be sequentially scanned. Look for LARGE tables with high
--   avg_rows_per_seq_scan relative to what the queries actually return.

-- Then find the actual queries:
SELECT substring(query,1,100), calls,
       round(total_exec_time::numeric,0) AS total_ms,
       round(mean_exec_time::numeric,2)  AS mean_ms, rows
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
```

### 5. Invalid indexes (failed CONCURRENTLY builds)

```sql
SELECT indexrelid::regclass AS invalid_index, indrelid::regclass AS table
FROM pg_index WHERE NOT indisvalid;
-- ⭐ These are NOT used by the planner but ARE maintained on every write.
--    Pure cost, zero benefit. Drop and rebuild them.
```

---

## 28. Choosing an index type

```
What is the query shape?

├── Equality / range / sort on a scalar
│   ├── Need uniqueness, ordering, or index-only scans?  → B-TREE
│   ├── Equality only, on a LARGE value, no uniqueness?  → HASH
│   └── Column correlates with physical order, huge table, range queries?
│                                                        → ⭐ BRIN
│
├── Only a subset of rows is ever queried                → ⭐ PARTIAL B-TREE
│   (soft deletes, work queues, status='pending')
│
├── The query filters on an EXPRESSION                   → EXPRESSION INDEX
│   (lower(email), (data->>'key'), (ts AT TIME ZONE 'UTC')::date)
│
├── The value CONTAINS many searchable items
│   ├── jsonb containment (@>)                → GIN with jsonb_path_ops
│   ├── jsonb key existence (?, ?|, ?&)       → GIN with jsonb_ops
│   ├── arrays (@>, &&)                       → GIN
│   ├── full-text search                      → GIN on a stored tsvector
│   └── LIKE '%substring%' / fuzzy            → ⭐ GIN with gin_trgm_ops
│
├── Ranges, geometry, or OVERLAP semantics
│   ├── Overlap queries (&&)                  → GiST
│   ├── ⭐ Must PREVENT overlap               → GiST EXCLUSION CONSTRAINT
│   ├── Nearest-neighbour (ORDER BY dist)     → GiST (KNN)
│   └── Geospatial                            → GiST (PostGIS)
│
├── Prefix / containment on text or inet      → SP-GiST
│
└── Vector similarity (embeddings)            → pgvector HNSW or IVFFlat
```

---

## 29. What an architect takes from this

**1. B-tree height barely grows.** 100 M rows and 10 B rows are both 4 levels. What matters is whether the **leaf level fits in cache** — which is why index *size* matters, not tree depth.

**2. The split rule explains everything about key choice.** Rightmost splits pack to 90%; interior splits pack to 50%. Sequential keys always split rightmost. That one branch in `_bt_findsplitloc` is why UUIDv7 beats UUIDv4.

**3. UUIDv4 primary keys cost four separate things**: ~2× index size, random page dirtying, up to 40× WAL amplification from full-page writes, and destroyed heap correlation. The WAL cost is the one nobody measures and the one that hurts most at scale.

**4. B-trees never merge partially-empty pages.** The insert-then-delete-old-rows pattern grows an index forever. REINDEX is a treadmill; **partitioning is the structural fix.**

**5. Partial indexes on soft-delete columns are the highest-value single index change** in most applications, and almost nobody has them.

**6. `random_page_cost = 4.0` is wrong on SSDs** and systematically causes the planner to avoid index scans it should use. Set it to 1.1.

**7. `Heap Fetches` on an Index Only Scan means "vacuum more", not "rewrite the query"** — the visibility map is the mechanism (Deep Dive 04 §23).

**8. `Rows Removed by Index Recheck` with lossy heap blocks means `work_mem` is too small** for the bitmap. It is a one-setting fix with large payoff.

**9. GIN's `fastupdate` trades predictable latency for average throughput.** For OLTP, turn it off. The mysterious p99 spike on an insert into a full-text-indexed table is the pending-list flush.

**10. Check correlation before creating a BRIN index.** Without correlation ≈ 1, BRIN is worse than no index — it costs space and can still be chosen.

**11. GiST exclusion constraints solve write skew at the storage layer** (Deep Dive 03 §9), with no application logic and no isolation-level cost. For bookings, schedules and resource allocation, this is the right answer and it is frequently missed.

**12. Run the index audit.** Unused, duplicate, redundant, invalid and bloated indexes are present in essentially every production database, and each one is paid for on every write, forever.

---

## Exercises

1. Compute the fan-out and height for a B-tree on `(uuid, timestamptz)` over 800 million rows. How many levels, and how large is the leaf level?
2. Trace a page split for a rightmost page with `fillfactor = 90`, then the same split for an interior page. Show the resulting densities.
3. Explain why the sibling links must be updated before the parent during a split. Construct the failure if the order were reversed.
4. Build the §10 experiment on your own machine with 5 M rows. Measure index size, `avg_leaf_density`, and WAL generated (`pg_stat_wal`) for sequential vs UUIDv4 keys.
5. A table receives 2,000 inserts/sec with a UUIDv4 primary key, and the index does not fit in cache. Estimate the WAL volume per hour from full-page writes alone.
6. Given `INDEX (a, b, c)`, decide for each: `WHERE b=1 AND c=2`; `WHERE a=1 AND c=3`; `WHERE a>5 AND b=2`; `WHERE a=1 ORDER BY b`. Explain each using the leaf ordering.
7. Rewrite an index in your system as `(key columns) INCLUDE (payload)`. Measure the change in index size and in `Heap Fetches`.
8. Find a table in your system with soft deletes. Compute how much index space a partial `WHERE deleted_at IS NULL` index would save.
9. Create an expression index without running `ANALYZE`, then `EXPLAIN` a query using it. Run `ANALYZE` and compare the estimated row counts.
10. Find a query in your system with `lossy` heap blocks. Tune `work_mem` for it and measure.
11. Check `correlation` for every column in your largest table. Which are BRIN candidates?
12. Design the indexing for a bookings table that must prevent double-booking. Use an exclusion constraint and explain why it is better than `SERIALIZABLE`.
13. Run all five audit queries from §27 against a production database. Report total reclaimable space and justify each proposed drop.
14. Your `events` table is 42 GB and its `created_at` B-tree is 38 GB, growing while the table stays flat. Diagnose it and give the structural fix.

---

**Next in this series:** Deep Dive 06 — The Query Planner and Executor

**Back to:** [Deep Dives](README.md) · [Chapter 09](../09-database-architecture.md) · [The Map](../README.md)
