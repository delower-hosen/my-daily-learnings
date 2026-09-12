# Deep Dive 06 — The Query Planner and Executor

**Prerequisite:** [Chapter 09 §9.7](../09-database-architecture.md) · [Deep Dive 05](05-btrees-indexes-and-access-methods.md)

**What the map said:** *"PostgreSQL is cost-based. Compare `rows=` with `actual rows=`. A big gap means stale statistics."*

**What this deep dive does:** gives you the actual cost formulas with their default constants, shows how selectivity is computed from histograms and MCV lists by hand, explains the independence assumption and the exact shape of query that breaks it, walks all three join algorithms with their memory behaviour and spill mechanics, explains how `work_mem` is really consumed (and why the obvious setting is dangerous), covers parallel query, plan caching and the generic-plan trap, and ends with a systematic procedure for diagnosing any bad plan.

---

## Contents

```
1.  The pipeline: five stages
2.  What the planner is actually choosing between
3.  The cost model and its constants
4.  Sequential scan cost, computed by hand
5.  Index scan cost, and why correlation dominates
6.  Statistics: what ANALYZE stores
7.  Selectivity for equality, by hand
8.  Selectivity for ranges, by hand
9.  ⭐ The independence assumption, and the query shape that breaks it
10. Extended statistics: fixing correlation between columns
11. Join selectivity
12. Nested Loop — mechanics, cost, and Memoize
13. Hash Join — mechanics, batching, and spilling
14. Merge Join — mechanics and when it wins
15. Traced scenario — the same join, three ways
16. work_mem: how it is really consumed ⭐
17. Sorting: four algorithms
18. Aggregation: HashAgg vs GroupAgg, and the PG13 spill
19. Join order search: DP and GEQO
20. Parallel query: how workers are chosen
21. Subqueries, CTEs and the optimisation fence
22. Reading EXPLAIN properly — every field
23. Why estimates go wrong: eight causes
24. Plan caching and the generic plan trap ⭐
25. A systematic procedure for a bad plan
26. Tooling: auto_explain, pg_stat_statements, hypothetical indexes
27. What an architect takes from this
```

---

## 1. The pipeline: five stages

```
    SQL text
       │
       ▼
 ┌───────────────┐
 │ 1. PARSER     │  syntax → raw parse tree. Knows nothing about tables.
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ 2. ANALYZER   │  resolve names against the catalog → QUERY TREE
 │               │  "orders" → OID 16385, "total" → attnum 4, type numeric
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ 3. REWRITER   │  apply rules: expand VIEWS, apply RLS policies (Ch. 17),
 │               │  expand row-level security quals
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ 4. PLANNER    │  ⭐ the interesting stage. Enumerate PATHS, cost each,
 │  /OPTIMIZER   │     pick the cheapest, convert to a PLAN TREE.
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ 5. EXECUTOR   │  walk the plan tree, pulling tuples through it
 └───────────────┘
```

**Two things worth noting immediately.**

The rewriter is where **views disappear**. A query against a view is textually substituted before planning, which is why a view cannot hide a bad underlying query — and why `EXPLAIN` of a view shows the underlying tables. It is also where **row-level security predicates are injected** (Deep Dive 03's tenant isolation), which is why RLS is genuinely unbypassable: the predicate is added before the planner ever sees the query.

The executor uses a **pull model** (Volcano/iterator): the top node calls `ExecProcNode` on its child, which calls its child, and tuples flow up one at a time. This is why `LIMIT` can stop a whole plan early, and why `actual time` on an inner node is *per loop*, not total (§22).

---

## 2. What the planner is actually choosing between

For a single table, the planner builds **paths**:

```
For orders WHERE customer_id = 42 AND total > 100:

  Path 1: Seq Scan, filter both conditions
  Path 2: Index Scan on idx_customer, filter total
  Path 3: Bitmap Heap Scan via idx_customer
  Path 4: Bitmap Heap Scan via BitmapAnd(idx_customer, idx_total)
  Path 5: Index Only Scan on idx_customer_total (if it covers)
  ...each with a startup cost, a total cost, and a sort order
```

For joins, the space explodes:

```
Joining 4 tables:
  join orders: 4! = 24 orderings (and the planner also considers bushy trees)
  × 3 join algorithms per join
  × N scan paths per table
  = thousands of candidate plans
```

**The planner keeps, for each set of relations, only the cheapest path — plus the cheapest path for each useful *sort order*.** That second part matters: a slightly more expensive path that delivers rows already sorted may win overall, because it removes a `Sort` node higher up. This is why an index scan sometimes beats a cheaper bitmap scan when there is an `ORDER BY`.

---

## 3. The cost model and its constants

Costs are in **arbitrary units**, anchored to "one sequential page read = 1.0". They are not milliseconds. Only their *ratios* matter.

```sql
SELECT name, setting, unit FROM pg_settings WHERE name LIKE '%cost%' ORDER BY name;
```

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `seq_page_cost` | **1.0** | Read one page sequentially — the unit of measure |
| `random_page_cost` | **4.0** | ⭐ Read one page randomly |
| `cpu_tuple_cost` | 0.01 | Process one row |
| `cpu_index_tuple_cost` | 0.005 | Process one index entry |
| `cpu_operator_cost` | 0.0025 | Evaluate one operator or function |
| `parallel_tuple_cost` | 0.1 | Pass one row from a worker to the leader |
| `parallel_setup_cost` | 1000.0 | ⭐ Start parallel workers — large, deliberately |
| `effective_cache_size` | 4GB | ⭐ A **hint** about total OS + PG cache. Allocates nothing. |
| `jit_above_cost` | 100000 | Consider JIT compilation above this |

### The two settings almost everyone should change

```sql
-- ⭐ 1. random_page_cost = 4.0 assumes a spinning disk where a random read
--       costs 4× a sequential one. On NVMe the real ratio is ~1.1.
--       Leaving it at 4.0 systematically makes the planner avoid index
--       scans it should use.
ALTER SYSTEM SET random_page_cost = 1.1;

-- ⭐ 2. effective_cache_size should be ~75% of RAM. It tells the planner
--       how likely a repeated page read is to hit cache, which strongly
--       affects nested-loop and index-scan costing. It reserves NOTHING.
ALTER SYSTEM SET effective_cache_size = '24GB';

SELECT pg_reload_conf();
```

These two changes, together, are the most common "the planner suddenly makes good decisions" fix on cloud-hosted PostgreSQL, where the defaults are frequently left untouched.

### Startup cost vs total cost

```
cost=0.43..8.45
     ^^^^  ^^^^
     |     total cost: to return ALL rows
     startup cost: to return the FIRST row
```

**Why both exist:**

```
Seq Scan + Sort:        startup HIGH  (must read and sort everything first)
Index Scan:             startup LOW   (first row comes immediately)

⭐ With LIMIT 10, the planner compares STARTUP-dominated costs.
   Without LIMIT, it compares TOTAL costs.

This is why adding a LIMIT can completely change the plan — and why
a query that is fast with LIMIT 10 can be catastrophically slow with
LIMIT 10000 (§23, cause 7).
```

---

## 4. Sequential scan cost, computed by hand

```
cost = (seq_page_cost × relpages)
     + (cpu_tuple_cost × reltuples)
     + (cpu_operator_cost × reltuples × num_quals)
```

Work a real example:

```sql
SELECT relpages, reltuples FROM pg_class WHERE relname = 'orders';
--  relpages | reltuples
-- ----------+-----------
--     54321 |   4321000

EXPLAIN SELECT * FROM orders WHERE total > 100;
```

```
relpages   = 54,321
reltuples  = 4,321,000
num_quals  = 1  (total > 100)

I/O  : 1.0    × 54,321   = 54,321.00
CPU  : 0.01   × 4,321,000 = 43,210.00
Quals: 0.0025 × 4,321,000 × 1 = 10,802.50
                              ───────────
                     TOTAL  = 108,333.50
```

```
EXPLAIN output:
  Seq Scan on orders  (cost=0.00..108333.50 rows=1440333 width=64)
                             ^^^^  ^^^^^^^^^      ^^^^^^^
                        startup 0   matches       estimated rows (§8)
```

**Startup cost is 0** because a sequential scan can emit its first row after reading one page.

**Notice the CPU terms dominate here** (54k of I/O vs 54k of CPU). For a wide table with few pages per row this flips. This is why `cpu_tuple_cost` matters more than people expect on modern hardware, and why some practitioners lower `seq_page_cost` and `random_page_cost` *together* (e.g. to 0.5 and 0.6) rather than only lowering `random_page_cost` — it rebalances I/O against CPU for fast storage.

---

## 5. Index scan cost, and why correlation dominates

An index scan has two parts: descending the index, and fetching heap tuples.

```
cost = index_access_cost + heap_access_cost

index_access_cost ≈ (cpu_index_tuple_cost + cpu_operator_cost) × tuples_fetched
                  + random_page_cost × index_pages_read

heap_access_cost  ≈ ⭐ INTERPOLATED BETWEEN TWO EXTREMES based on correlation
```

### The interpolation

```
max_IO_cost (correlation = 0, fully random):
    = tuples_fetched × random_page_cost
      (assume every tuple is on a different page, read randomly)

min_IO_cost (correlation = 1, perfectly ordered):
    = pages_fetched × seq_page_cost
      (matching tuples are contiguous; read them sequentially)

⭐ actual = max_IO_cost + correlation² × (min_IO_cost − max_IO_cost)
```

The **squared** correlation term means the benefit is heavily concentrated at high correlation — a correlation of 0.7 gives you only 49% of the benefit of 1.0.

### Worked comparison

```
Fetching 50,000 rows from a 4.3 M row, 54,321-page table.

CORRELATION = 0.99 (e.g. a timestamp on an append-only table):
    pages_fetched ≈ 50,000 / 80 rows-per-page ≈ 625 contiguous pages
    heap cost ≈ 625 × 1.0 = 625
    ⭐ TOTAL ≈ 900     → the planner will happily use the index

CORRELATION = 0.01 (e.g. a UUIDv4 column, or any scattered value):
    pages_fetched ≈ 50,000 distinct random pages
    heap cost ≈ 50,000 × 4.0 = 200,000
    ⭐ TOTAL ≈ 200,300  → MORE EXPENSIVE than the 108,333 seq scan
                        → the planner correctly chooses Seq Scan
```

> **This is the cost-model explanation for Deep Dive 05 §11's "Cost 4".** A UUIDv4 primary key destroys correlation, which makes the planner abandon index scans much earlier than it would with a sequential key. You do not just get a bigger index — you get *fewer index scans*.

### Checking correlation

```sql
SELECT attname, correlation, n_distinct, null_frac, avg_width
FROM pg_stats WHERE tablename = 'orders'
ORDER BY abs(correlation) DESC;
```

---

## 6. Statistics: what ANALYZE stores

`ANALYZE` samples the table (`300 × default_statistics_target` rows — 30,000 by default) and stores five things per column.

```sql
SELECT attname, null_frac, avg_width, n_distinct,
       most_common_vals::text[], most_common_freqs,
       histogram_bounds::text[], correlation
FROM pg_stats WHERE tablename = 'orders' AND attname = 'status';
```

```
 attname           | status
 null_frac         | 0
 avg_width         | 9
 n_distinct        | 5                      ⭐ 5 distinct values
 most_common_vals  | {shipped,pending,cancelled,refunded,disputed}
 most_common_freqs | {0.71,0.19,0.07,0.02,0.01}    ⭐ frequencies
 histogram_bounds  | (null — all values are in the MCV list)
 correlation       | 0.31
```

### The five statistics

| Statistic | Meaning | Used for |
|-----------|---------|----------|
| **`null_frac`** | Fraction of NULLs | `IS NULL` selectivity; reduces other estimates |
| **`avg_width`** | Average bytes | `width=` in EXPLAIN; memory and sort sizing |
| **`n_distinct`** | ⭐ Distinct values. **Positive** = absolute count. **Negative** = a *fraction of rows* (−1 means unique) | Equality selectivity, grouping estimates |
| **`most_common_vals` / `_freqs`** | ⭐ The top N values and their exact frequencies | Skew handling — the most valuable statistic |
| **`histogram_bounds`** | Bucket boundaries for the *non-MCV* values, each bucket holding an equal number of rows | Range selectivity |

### `n_distinct` and why it is often wrong

```
n_distinct is estimated from a SAMPLE, and distinct-value estimation from
a sample is a genuinely hard statistical problem. PostgreSQL is frequently
wrong on high-cardinality columns in large tables.

⭐ You can override it when you know the truth:
```

```sql
-- We know this column is essentially unique
ALTER TABLE orders ALTER COLUMN order_ref SET (n_distinct = -1);
ANALYZE orders;

-- Or an absolute count we know from the domain
ALTER TABLE events ALTER COLUMN tenant_id SET (n_distinct = 850);
ANALYZE events;
```

### Raising the statistics target

```sql
-- Default 100 → 100 MCVs, 100 histogram buckets, 30,000 row sample
-- For a skewed or high-cardinality column, raise it:
ALTER TABLE orders ALTER COLUMN customer_id SET STATISTICS 1000;
ANALYZE orders;
-- → 1000 MCVs, 1000 buckets, 300,000 row sample
-- ⭐ Costs: slower ANALYZE, slightly slower planning. Usually worth it
--    on the 2-5 columns that drive your most important queries.
```

---

## 7. Selectivity for equality, by hand

This is the calculation that produces `rows=` in every `EXPLAIN`.

```
For  WHERE col = 'value':

  IF 'value' is in most_common_vals:
      ⭐ selectivity = the corresponding most_common_freqs entry (EXACT)

  ELSE:
      selectivity = (1 − sum(most_common_freqs) − null_frac)
                    ─────────────────────────────────────────
                        (n_distinct − number_of_MCVs)
```

### Worked example

```
Table: orders, 4,321,000 rows
Column: status
  n_distinct        = 5
  most_common_vals  = {shipped, pending, cancelled, refunded, disputed}
  most_common_freqs = {0.71, 0.19, 0.07, 0.02, 0.01}
  null_frac         = 0
```

```
WHERE status = 'pending'
    'pending' IS in the MCV list, at position 2.
    ⭐ selectivity = 0.19    (exact — no estimation involved)
    rows = 4,321,000 × 0.19 = 820,990

WHERE status = 'unknown_value'
    NOT in the MCV list.
    sum(mcf) = 0.71+0.19+0.07+0.02+0.01 = 1.00
    selectivity = (1 − 1.00 − 0) / (5 − 5) → division by zero
    ⭐ PostgreSQL clamps this: since all distinct values are covered by
       the MCV list, a non-MCV value is estimated as very rare.
    rows = 1
```

**This is the MCV list's real value: it handles skew exactly.** Without it, PostgreSQL would assume uniform distribution and estimate `4,321,000 / 5 = 864,200` for *every* status — wildly wrong for `disputed` (43,210 actual).

### A high-cardinality example

```
Column: customer_id
  n_distinct        = -0.02   ⭐ negative → 2% of rows are distinct
                              → 4,321,000 × 0.02 = 86,420 distinct customers
  most_common_vals  = {1001, 2044, 8891, ...}  (the 100 biggest customers)
  most_common_freqs = {0.008, 0.006, 0.005, ...}
  sum(mcf)          = 0.15    (the top 100 customers are 15% of all orders)
```

```
WHERE customer_id = 1001        (an MCV)
    ⭐ selectivity = 0.008
    rows = 34,568

WHERE customer_id = 55555       (not an MCV)
    selectivity = (1 − 0.15 − 0) / (86,420 − 100)
                = 0.85 / 86,320
                = 0.00000985
    rows = 4,321,000 × 0.00000985 ≈ 43
```

> **Notice how different those two estimates are — 34,568 vs 43 — for the same query shape with a different parameter.** This is exactly why prepared statements with a *generic* plan can be catastrophic (§24): one plan cannot be right for both.

---

## 8. Selectivity for ranges, by hand

Range conditions use the histogram.

```
histogram_bounds for orders.total (101 boundaries → 100 buckets,
each containing ~1% of the non-MCV rows):

  {0.00, 4.99, 9.99, 14.50, 19.99, ..., 98.00, 104.50, 112.00, ..., 9999.00}
```

```
WHERE total > 100

Find where 100 falls: between bucket boundary 98.00 (index 20) and
                      104.50 (index 21).

Fraction of THIS bucket above 100:
    (104.50 − 100) / (104.50 − 98.00) = 4.50 / 6.50 = 0.692

Buckets entirely above 100: buckets 21..99 = 79 full buckets

selectivity = (79 + 0.692) / 100 = 0.797

⭐ Plus MCV handling: add the frequencies of any MCVs that satisfy total > 100.
```

**The two assumptions baked in:**

1. **Values are uniformly distributed within each bucket.** With `default_statistics_target = 100`, each bucket covers 1% of rows — so within-bucket skew is usually tolerable. With heavily skewed data, raise the target.
2. **The histogram is current.** A histogram built before a bulk load knows nothing about the new range (§23, cause 2).

### The out-of-range problem ⭐

```
Table: events, histogram_bounds on created_at ends at 2026-09-10
       (that is when ANALYZE last ran)

Query: WHERE created_at > '2026-09-12'

⭐ The value is ABOVE the entire histogram.
   PostgreSQL estimates a very small number of rows — but there may be
   two days of data above that bound, which could be millions of rows.

This is the single most common estimate failure on time-series tables,
and it gets worse the longer since the last ANALYZE.
```

PostgreSQL partially mitigates this by extrapolating using `correlation` and the column's growth pattern for the *rightmost* bucket, but the estimate remains fragile. The fix is more frequent `ANALYZE` on high-insert tables:

```sql
ALTER TABLE events SET (autovacuum_analyze_scale_factor = 0.0,
                        autovacuum_analyze_threshold = 25000);
```

---

## 9. ⭐ The independence assumption, and the query shape that breaks it

**This is the single biggest source of bad plans in real systems.**

```
For  WHERE a = 1 AND b = 2:

    ⭐ PostgreSQL assumes a and b are INDEPENDENT:

       selectivity(a AND b) = selectivity(a) × selectivity(b)
```

That is correct when the columns are genuinely unrelated. It is catastrophically wrong when they are correlated — and in real schemas, **columns are correlated constantly**.

### The canonical failure

```sql
CREATE TABLE addresses (
    id      bigserial PRIMARY KEY,
    city    text,
    region  text,
    country text
);
-- 10,000,000 rows

SELECT * FROM addresses WHERE city = 'Dhaka' AND country = 'Bangladesh';
```

```
Statistics:
    city:    n_distinct = 40,000,  'Dhaka' frequency = 0.004
    country: n_distinct = 190,     'Bangladesh' frequency = 0.006

PLANNER:
    selectivity = 0.004 × 0.006 = 0.000024
    ⭐ estimated rows = 10,000,000 × 0.000024 = 240

REALITY:
    EVERY row with city='Dhaka' ALSO has country='Bangladesh'.
    The country predicate removes NOTHING.
    ⭐ actual rows = 40,000

    ESTIMATE IS 167× TOO LOW.
```

### Why a 167× underestimate is so damaging

It is not that the number is wrong — it is what the planner *does* with it.

```
Believing it will get 240 rows, the planner chooses:
    Nested Loop
      -> Index Scan on addresses (240 rows expected)
      -> Index Scan on orders    (executed once per row)

Reality: 40,000 rows → the inner index scan runs 40,000 times.

⭐ A plan that would have taken 200 ms as a Hash Join takes 4 minutes.
```

**Underestimates are far more dangerous than overestimates**, because they lead the planner to choose nested loops and to under-size hash tables. An overestimate merely causes a hash join where a nested loop would have been slightly faster.

### The shapes that produce correlation

Learn to recognise these in a schema:

```
1. ⭐ Hierarchies:        city → region → country
                          product → subcategory → category
                          building → floor → room
2. ⭐ Redundant flags:    status='shipped' AND shipped_at IS NOT NULL
3. ⭐ Denormalised copies: order.customer_country AND order.shipping_country
4. Derived columns:       created_at AND created_date
5. Encoded relationships: sku LIKE 'ELEC-%' AND category='electronics'
6. Multi-tenant scoping:  tenant_id AND any tenant-specific enum value
```

**Every one of those is common in real schemas.** If a query filters on two columns from the same group, its estimate is wrong by roughly the correlation factor.

---

## 10. Extended statistics: fixing correlation between columns

PostgreSQL 10+ lets you tell the planner that columns are related.

```sql
CREATE STATISTICS stat_addr (dependencies, ndistinct, mcv)
    ON city, region, country FROM addresses;

ANALYZE addresses;     -- ⭐ required — the statistic is empty until you do
```

### The three kinds

```
ndistinct     ⭐ The number of distinct COMBINATIONS.
                 Fixes GROUP BY and join estimates.
                 Without it: n_distinct(a) × n_distinct(b) — often absurd.

dependencies  ⭐ Functional dependency strength: "knowing city tells you
                 country with probability 1.0".
                 Fixes multi-column EQUALITY estimates.

mcv           ⭐ Most-common COMBINATIONS with their real frequencies.
                 The most powerful, and it also helps range and
                 inequality conditions. Larger to store.
```

### Verifying it worked

```sql
SELECT m.*
FROM pg_statistic_ext e
JOIN pg_statistic_ext_data d ON d.stxoid = e.oid,
     pg_mcv_list_items(d.stxdmcv) m
WHERE e.stxname = 'stat_addr' LIMIT 5;

--  index |      values          | frequency | base_frequency
-- -------+----------------------+-----------+----------------
--      0 | {Dhaka, Dhaka, Bangladesh} |   0.004 |       0.000024
--                                          ↑              ↑
--                              ⭐ the TRUTH    what independence predicted
--                                              (167× wrong)

-- Functional dependencies found:
SELECT stxname, stxddependencies FROM pg_statistic_ext e
JOIN pg_statistic_ext_data d ON d.stxoid = e.oid WHERE stxname='stat_addr';
-- {"1 => 3": 1.000000, "2 => 3": 1.000000, "1 => 2": 1.000000}
--   ⭐ city fully determines country (1.0). The planner now knows.
```

```
AFTER creating the statistic:
    Estimated rows: 240 → 39,812
    Actual rows:    40,000
    ⭐ Plan switches from Nested Loop to Hash Join. 4 minutes → 180 ms.
```

### Where to apply this

```sql
-- ⭐ The audit: find your worst estimates, then check whether the
--    predicates involve correlated columns.
-- (Requires auto_explain or manual EXPLAIN ANALYZE — see §26.)

-- Rules of thumb for where to create extended statistics:
--   1. Any hierarchy you filter on together
--   2. Any denormalised/derived column pair
--   3. Multi-tenant tables where tenant_id co-occurs with other filters
--   4. Anywhere EXPLAIN ANALYZE shows a >10× estimate error on an AND
```

> **Extended statistics are one of the highest-value, least-used PostgreSQL features.** Creating three or four of them on the right column groups routinely fixes plans that people have spent weeks trying to hint around.

---

## 11. Join selectivity

```
For  a JOIN b ON a.x = b.y :

    selectivity = 1 / max(n_distinct(a.x), n_distinct(b.y))

    estimated_rows = rows(a) × rows(b) × selectivity
```

**The intuition:** if `b.y` has 1,000 distinct values, each row of `a` matches roughly `rows(b)/1000` rows of `b`.

```
orders (4,321,000 rows) JOIN customers (86,420 rows) ON customer_id

  n_distinct(orders.customer_id)   = 86,420
  n_distinct(customers.id)          = 86,420 (unique)

  selectivity = 1 / 86,420 = 0.0000116
  rows = 4,321,000 × 86,420 × 0.0000116 = 4,321,000   ✓ correct —
         a foreign-key join returns one row per order
```

**When a foreign key exists, PostgreSQL uses it** — since PG9.6, the planner recognises foreign key constraints and estimates multi-column FK joins far more accurately. This is a concrete reason to declare foreign keys even in systems where the application "guarantees" referential integrity: **they improve query plans.**

### Where join estimates go wrong

```
1. ⭐ Estimate errors COMPOUND through a join tree.
      A 10× error on the first join becomes a 10× error in its output,
      which feeds the second join, and so on.
      A 4-table join with three 5× errors produces a 125× error at the top.

2. Joins on expressions or with functions — no statistics available.

3. Joins where a filter has already skewed the distribution:
      WHERE o.status = 'pending' AND o.customer_id = c.id
      ⭐ The n_distinct of customer_id AMONG PENDING ORDERS may be
         completely different from n_distinct over the whole table.
```

Cause 1 is why deep join trees are unstable: a small error at the leaves becomes a catastrophic one at the root.

---

## 12. Nested Loop — mechanics, cost, and Memoize

```
FOR each row in OUTER:
    FOR each matching row in INNER:
        emit the joined row
```

```
cost = outer_startup
     + outer_total
     + outer_rows × inner_cost_per_iteration
              ⭐ the term that dominates
```

**The critical property:** the inner side is re-executed **once per outer row**. If the inner has an index on the join key, each execution is cheap (a few page reads) and this is the best plan for small outer sets. If the outer set is large, or the inner has no index, it is a disaster.

```
Outer: 10 rows.    Inner: index scan, cost 8 each.
    cost = 10 × 8 = 80                              ⭐ excellent

Outer: 100,000 rows.    Inner: index scan, cost 8 each.
    cost = 100,000 × 8 = 800,000                    ⭐ terrible
    → a Hash Join would be ~50,000
```

> **This is why an underestimate is so dangerous (§9).** The planner believes the outer set is 240 rows and picks a nested loop; it is actually 40,000, and the plan is 167× more expensive than costed. **Nested loop + a large `actual rows` on the outer side is the signature of an estimate failure**, and it is the first thing to look for in a slow plan.

### Memoize (PG14+) ⭐

```
Nested Loop
  -> Seq Scan on orders           (100,000 rows)
  -> Memoize                       ⭐
       Cache Key: orders.customer_id
       Hits: 98,412  Misses: 1,588  Evictions: 0  Memory Usage: 421kB
       -> Index Scan on customers
```

Memoize caches inner-side results keyed by the join parameters. With 100,000 orders but only 1,588 distinct customers, the inner index scan runs **1,588 times instead of 100,000**.

```
⭐ This makes nested loops viable in cases where they previously were not:
   a large outer side with LOW CARDINALITY on the join key.

Read the Hits/Misses ratio in EXPLAIN. A high hit rate means Memoize is
doing real work. A low one means the cache is not helping and the
planner may have mis-costed it.
```

---

## 13. Hash Join — mechanics, batching, and spilling

```
BUILD PHASE:
    Scan the INNER relation (the planner picks the smaller side).
    Hash each row on the join key into an in-memory hash table.

PROBE PHASE:
    Scan the OUTER relation.
    Hash each row, look it up, emit matches.
```

```
cost = inner_total + outer_total
     + (hash build CPU) + (hash probe CPU)

⭐ Each side is scanned EXACTLY ONCE. This is why hash join wins for
   large joins — the cost is linear, not multiplicative.
```

**Restriction: equality joins only.** A hash table cannot answer `a.x < b.y`.

### What happens when it does not fit in work_mem

This is the part that determines real-world performance.

```
If the hash table exceeds work_mem, PostgreSQL switches to a BATCHED hash join:

  1. Partition BOTH sides by hash into N batches, written to temp files
  2. Process one batch at a time: load its inner partition into memory,
     stream its outer partition through

⭐ Cost: both relations are WRITTEN to disk and READ BACK.
   Roughly 2× the I/O of the unbatched case.
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id;

-- Hash Join  (actual time=891.2..14203.8 rows=4321000)
--   Hash Cond: (o.customer_id = c.id)
--   -> Seq Scan on orders
--   -> Hash  (actual rows=86420)
--        Buckets: 65536  Batches: 16  Memory Usage: 4097kB    ⭐⭐
--                                ^^^^^^^^^^
--        Batches > 1 means IT SPILLED TO DISK
--   Buffers: shared hit=..., temp read=48291 written=48291     ⭐ temp I/O
```

```sql
-- The fix
SET work_mem = '128MB';
-- Re-run:
--   Buckets: 131072  Batches: 1  Memory Usage: 9832kB
--   ⭐ Batches: 1 → fully in memory
--   actual time: 14203 ms → 2100 ms
```

> **`Batches: 1` is the target.** Any value above 1 means the join spilled. Combined with `temp read/written` in `BUFFERS`, this is one of the highest-signal diagnostics in `EXPLAIN`.

### Parallel Hash Join

```
Parallel Hash Join
  -> Parallel Seq Scan on orders
  -> Parallel Hash                    ⭐ workers build a SHARED hash table
       Buckets: 131072  Batches: 1  Memory Usage: 41216kB
```

Note that `Parallel Hash` builds **one shared** hash table across workers, and the memory limit is `work_mem × participating workers` — a detail that matters for §16's arithmetic.

---

## 14. Merge Join — mechanics and when it wins

```
Both inputs must be SORTED on the join key.
Walk both simultaneously, advancing whichever side is behind.
```

```
cost = sort_cost(outer) + sort_cost(inner) + merge_cost

⭐ If both inputs are ALREADY sorted (from index scans), the sort costs
   are ZERO and merge join is extremely cheap.
```

### When the planner chooses it

```
1. ⭐ Both sides have usable indexes on the join key → free ordering
2. The output needs to be sorted anyway (ORDER BY on the join key)
3. Both relations are large and a hash table would not fit
4. Range join conditions that hash cannot handle
```

```sql
EXPLAIN SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id
        ORDER BY o.customer_id;

-- Merge Join
--   Merge Cond: (o.customer_id = c.id)
--   -> Index Scan using idx_orders_customer on orders     ⭐ already sorted
--   -> Index Scan using customers_pkey on customers       ⭐ already sorted
--   (no Sort nodes, and no Sort needed for the ORDER BY either)
```

**The failure mode to watch for:**

```
Merge Join
  -> Sort  (actual rows=4321000)
       Sort Method: external merge  Disk: 284912kB      ⭐⭐ sorting 4.3 M rows
       -> Seq Scan on orders
  -> Sort
       Sort Method: quicksort  Memory: 8214kB
       -> Seq Scan on customers

⭐ Two explicit sorts means merge join was chosen despite having to sort.
   That is usually because a hash join was estimated to spill badly.
   Fix: raise work_mem, or add an index to provide the ordering for free.
```

---

## 15. Traced scenario — the same join, three ways

```sql
SELECT o.id, o.total, c.name
FROM orders o JOIN customers c ON c.id = o.customer_id
WHERE o.created_at > '2026-09-01';
```

```
orders:    4,321,000 rows, 54,321 pages
customers:    86,420 rows,  1,204 pages
Rows matching the date filter: varies by scenario
```

### Scenario A — the filter matches 50 rows

```
Nested Loop  (cost=0.86..421.30 rows=50)
  -> Index Scan using idx_orders_created on orders  (rows=50)
       Index Cond: (created_at > '2026-09-01')
  -> Index Scan using customers_pkey on customers   (loops=50)
       Index Cond: (id = o.customer_id)

⭐ 50 iterations × ~8 cost each = cheap. Nested loop is clearly right.
   Total: ~421 units, ~2 ms.
```

### Scenario B — the filter matches 800,000 rows

```
Hash Join  (cost=1584.45..142903.22 rows=800000)
  Hash Cond: (o.customer_id = c.id)
  -> Bitmap Heap Scan on orders  (rows=800000)
  -> Hash  (rows=86420)
       Buckets: 131072  Batches: 1  Memory Usage: 9832kB     ⭐ fits

⭐ Each side scanned once. Nested loop would be
   800,000 × 8 = 6,400,000 — 45× worse.
   Total: ~143,000 units, ~2.1 s.
```

### Scenario C — the filter matches 800,000 rows, but work_mem is 4 MB

```
Hash Join  (actual time=921..18402 rows=800000)
  -> Bitmap Heap Scan on orders
  -> Hash
       Buckets: 32768  Batches: 8  Memory Usage: 3905kB      ⭐⭐ SPILLED
  Buffers: temp read=12048 written=12048

⭐ Same plan shape, 9× slower, purely because of work_mem.
   The planner CHOSE correctly; the execution was starved of memory.
```

> **Scenario C is the important lesson: a correct plan can still be slow.** `EXPLAIN` without `ANALYZE` would show the same plan in B and C. Only `ANALYZE, BUFFERS` reveals the spill. **Always use both.**

---

## 16. work_mem: how it is really consumed ⭐

The most commonly misunderstood memory setting in PostgreSQL.

```
⭐ work_mem is NOT per connection.
⭐ work_mem is NOT per query.
⭐ work_mem is PER NODE that needs memory, PER PARALLEL WORKER.
```

### The arithmetic that bites

```sql
SELECT ... FROM a
JOIN b ON ...          -- Hash Join      → 1 × work_mem
JOIN c ON ...          -- Hash Join      → 1 × work_mem
WHERE ...
GROUP BY ...           -- HashAggregate  → 1 × work_mem
ORDER BY ...           -- Sort           → 1 × work_mem
```

```
That single query: 4 nodes × work_mem

With parallelism (2 workers + leader = 3 participants):
    ⭐ up to 4 × 3 = 12 × work_mem for ONE query

With work_mem = 256MB:  3 GB for one query.
With 100 such concurrent queries: 300 GB. ⭐ OOM.
```

### The sizing rule

```
Conservative upper bound:
    work_mem ≤ (RAM × 0.25) / (max_connections × expected_nodes_per_query)

For a 64 GB machine, max_connections = 200:
    16 GB / (200 × 3) ≈ 27 MB

⭐ But this is far too conservative for the queries that actually need memory.
```

### The practical approach

```sql
-- 1. A modest global default that is safe under full concurrency
ALTER SYSTEM SET work_mem = '32MB';

-- 2. ⭐ Raise it per-query for the queries that need it
BEGIN;
SET LOCAL work_mem = '512MB';       -- reverts at COMMIT/ROLLBACK
SELECT ... big analytical query ... ;
COMMIT;

-- 3. ⭐ Or per-role, so reporting users get more and the app gets less
ALTER ROLE analytics_user SET work_mem = '512MB';
ALTER ROLE app_user       SET work_mem = '16MB';

-- 4. PG13+: HashAggregate can use a different multiple
ALTER SYSTEM SET hash_mem_multiplier = 2.0;
--    → hash nodes get work_mem × 2.0, sorts still get work_mem.
--    ⭐ Useful because hash spilling is more expensive than sort spilling.
```

### Finding queries that spill

```sql
-- Global counter: are temp files being created at all?
SELECT datname, temp_files, pg_size_pretty(temp_bytes) AS temp_written
FROM pg_stat_database WHERE datname = current_database();

-- Log every temp file over a threshold, to find the culprits
ALTER SYSTEM SET log_temp_files = '10MB';
SELECT pg_reload_conf();
-- LOG: temporary file: path "base/pgsql_tmp/...", size 284912640
--      STATEMENT: SELECT ...
```

> **`log_temp_files` is one of the highest-value logging settings.** It directly identifies every query that is spilling, with the statement text, for effectively zero overhead.

---

## 17. Sorting: four algorithms

```sql
EXPLAIN (ANALYZE) SELECT * FROM orders ORDER BY total DESC LIMIT 10;
```

PostgreSQL picks one of four:

```
1. QUICKSORT                — fits in work_mem
   "Sort Method: quicksort  Memory: 8214kB"

2. TOP-N HEAPSORT          ⭐ ORDER BY ... LIMIT n
   "Sort Method: top-N heapsort  Memory: 27kB"
   ⭐ Keeps only n rows in memory, regardless of input size.
      Sorting 100 M rows for LIMIT 10 uses 27 kB, not gigabytes.

3. EXTERNAL MERGE          — does not fit; spills to disk
   "Sort Method: external merge  Disk: 284912kB"
   Writes sorted runs to temp files, then merges them.

4. EXTERNAL SORT           — an older variant, tape-based merge
   "Sort Method: external sort  Disk: 284912kB"
```

### Incremental Sort (PG13+) ⭐

```sql
-- Index provides (tenant_id), query needs (tenant_id, created_at)
EXPLAIN SELECT * FROM sessions ORDER BY tenant_id, created_at;

-- Incremental Sort
--   Sort Key: tenant_id, created_at
--   Presorted Key: tenant_id                    ⭐
--   Full-sort Groups: 847  Sort Method: quicksort  Average Memory: 28kB
--   -> Index Scan using idx_sessions_tenant on sessions
```

**The mechanism:** the input is already sorted by `tenant_id`. Rather than sorting everything, PostgreSQL sorts each `tenant_id` *group* independently.

```
⭐ Benefits:
   • Memory is bounded by the largest GROUP, not the whole result
   • It can emit rows EARLY → excellent startup cost → great with LIMIT
   • A partial index prefix becomes useful where it previously was not
```

**This means a multicolumn index does not need to match the `ORDER BY` exactly to be valuable** — a matching *prefix* is often enough. That is a meaningful relaxation of Deep Dive 05 §14's rules.

### Avoiding the sort entirely

```sql
-- Provide the exact ordering via an index, including direction
CREATE INDEX ON sessions (tenant_id, created_at DESC);

EXPLAIN SELECT * FROM sessions WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT 20;
-- Limit
--   -> Index Scan using idx_sessions_tenant_created on sessions
--   ⭐ NO Sort node at all. The index IS the sort order.
```

---

## 18. Aggregation: HashAgg vs GroupAgg, and the PG13 spill

```sql
SELECT tenant_id, count(*), avg(score) FROM sessions GROUP BY tenant_id;
```

### GroupAggregate

```
GroupAggregate
  Group Key: tenant_id
  -> Sort  (or an Index Scan providing the order)
       Sort Key: tenant_id

Requires SORTED input. Memory: O(1) — one group at a time.
⭐ Chosen when input is already sorted, or when the number of groups
   is so large that a hash table would not fit.
```

### HashAggregate

```
HashAggregate
  Group Key: tenant_id
  Batches: 1  Memory Usage: 2841kB       ⭐ PG13+ reports this

Builds a hash table of groups. No sorting needed.
Memory: O(number of groups).
⭐ Usually faster when the group count is modest.
```

### The PG13 change that matters

```
BEFORE PostgreSQL 13:
    ⭐ HashAggregate could NOT spill to disk.
    If the planner underestimated the group count, the hash table grew
    without bound and the backend was OOM-killed.
    The planner therefore refused HashAgg whenever it estimated the
    table would exceed work_mem — sometimes choosing a much slower
    GroupAggregate unnecessarily.

PostgreSQL 13+:
    ✅ HashAggregate SPILLS to disk, like a hash join.
    "Batches: 4  Memory Usage: 4097kB  Disk Usage: 187264kB"
    ⭐ No more OOM. But a spilling HashAgg is slow — treat Batches > 1
       as a signal to raise work_mem or hash_mem_multiplier.
```

```sql
-- ⭐ Estimating group counts badly is common. Check:
EXPLAIN (ANALYZE) SELECT tenant_id, count(*) FROM sessions GROUP BY tenant_id;
-- HashAggregate  (cost=... rows=200) (actual rows=8472)
--                            ^^^^^^^          ^^^^^^^^
--   ⭐ 200 is the DEFAULT estimate when n_distinct is unknown.
--      Fix with:  ALTER TABLE sessions ALTER COLUMN tenant_id SET (n_distinct = 8500);
```

**`rows=200` in a grouping node is a tell-tale sign** that PostgreSQL has no `n_distinct` estimate and fell back to a hard-coded default.

---

## 19. Join order search: DP and GEQO

```
Joining N tables: the number of possible orderings grows factorially.

   4 tables:      ~120 plans
   8 tables:    ~700,000 plans
  12 tables: ~28 billion plans        ⭐ exhaustive search is impossible
```

### Dynamic programming (the default, below the threshold)

```
PostgreSQL uses a bottom-up dynamic programming algorithm (System-R style):

  Level 1: best path for each single relation
  Level 2: best path for each PAIR (using level-1 results)
  Level 3: best path for each TRIPLE (using levels 1 and 2)
  ...

⭐ Key optimisation: for each SET of relations, keep only the cheapest path
   — plus the cheapest path for each useful SORT ORDER (an "interesting
   pathkey"). That second part is what lets merge joins and ORDER BY
   elimination win.
```

### GEQO — the genetic algorithm

```sql
SHOW geqo_threshold;   -- 12
```

```
Above 12 relations in one join, PostgreSQL switches to GEQO:
a genetic algorithm that samples the search space.

⭐ Consequences you will actually observe:
   • Planning time stays bounded (good)
   • The plan is NOT guaranteed optimal
   • ⭐ THE PLAN CAN DIFFER BETWEEN IDENTICAL RUNS — GEQO is randomised
     (seeded by geqo_seed, default 0.0, which does give reproducibility
      within a session, but the search is still heuristic)
```

```sql
-- For a critical 13-table report where you want deterministic, optimal plans:
SET geqo_threshold = 20;     -- force exhaustive DP
-- ⚠ Planning time may grow substantially. Measure it.

-- Or restructure: materialise part of the join into a temp table,
-- which is often better than fighting the planner.
```

> **Practical advice: if you have queries joining more than ~10 tables, the structural fix is usually to break them up** — a CTE materialised into a temp table, or a denormalised reporting table (Chapter 12). Fighting GEQO is rarely productive.

---

## 20. Parallel query: how workers are chosen

```sql
EXPLAIN (ANALYZE) SELECT count(*) FROM orders WHERE total > 100;

-- Finalize Aggregate
--   -> Gather                                     ⭐ collects from workers
--        Workers Planned: 2
--        Workers Launched: 2                      ⭐ check these MATCH
--        -> Partial Aggregate
--             -> Parallel Seq Scan on orders
```

### How many workers

```
The planner computes workers from TABLE SIZE:

  workers = ⌊ log₂( table_size / min_parallel_table_scan_size ) ⌋ ... roughly,
            capped by max_parallel_workers_per_gather

  min_parallel_table_scan_size = 8MB   (default)
  min_parallel_index_scan_size = 512kB

  8 MB   → 1 worker
  24 MB  → 2 workers
  72 MB  → 3 workers
  216 MB → 4 workers
  ...each ×3 in size adds one worker

⭐ Capped by max_parallel_workers_per_gather (default 2 — often too low)
```

### The settings

```sql
SHOW max_parallel_workers_per_gather;  -- 2   ⭐ per Gather node
SHOW max_parallel_workers;             -- 8   cluster-wide pool
SHOW max_worker_processes;             -- 8   total background workers

-- For an analytical workload on a many-core machine:
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;
ALTER SYSTEM SET max_parallel_workers = 16;
ALTER SYSTEM SET max_worker_processes = 20;
```

### `Workers Launched` < `Workers Planned` ⭐

```
Workers Planned: 4
Workers Launched: 1        ⭐ the pool was exhausted

The planner COSTED the query assuming 4 workers. It got 1.
→ The query takes ~4× longer than the plan predicted, and EXPLAIN's
  cost estimate is meaningless for this run.

Cause: max_parallel_workers is a CLUSTER-WIDE pool. Concurrent parallel
queries compete for it. Under load, workers are simply unavailable.
```

**This is a real source of erratic query latency on analytical workloads** — the same query is fast at 3 AM and slow at noon, with the same plan, because it got fewer workers.

### Gather vs Gather Merge

```
Gather:        collects rows from workers in ARBITRARY order. Cheaper.
Gather Merge:  ⭐ collects rows preserving each worker's SORT ORDER,
               merging them. Needed when the plan must stay sorted.
```

### What cannot be parallelised

```
❌ Queries writing data (INSERT/UPDATE/DELETE), except CREATE TABLE AS /
   CREATE INDEX in some cases
❌ Queries with FOR UPDATE / FOR SHARE
❌ Functions not marked PARALLEL SAFE           ⭐ the most common blocker
❌ Cursors (in most cases)
❌ Anything inside a function with a non-parallel-safe volatility
```

```sql
-- ⭐ A single unmarked user-defined function disables parallelism for the
--    ENTIRE query. This is a frequent and confusing cause of "why is my
--    query not parallel?"
SELECT proname, proparallel FROM pg_proc WHERE proname = 'my_function';
--  proparallel: 'u' = unsafe (default!), 'r' = restricted, 's' = safe

ALTER FUNCTION my_function(int) PARALLEL SAFE;
```

---

## 21. Subqueries, CTEs and the optimisation fence

### CTEs: the PG12 change that matters

```sql
WITH recent AS (
    SELECT * FROM orders WHERE created_at > '2026-09-01'
)
SELECT * FROM recent WHERE customer_id = 42;
```

```
BEFORE PostgreSQL 12:
    ⭐ CTEs were ALWAYS materialised — an "optimisation fence".
    The CTE ran in full (millions of rows), THEN the outer filter applied.
    People used this deliberately to control the planner.

PostgreSQL 12+:
    ⭐ A CTE is INLINED if it is:
       • referenced exactly ONCE
       • not RECURSIVE
       • has no side effects (no INSERT/UPDATE/DELETE, no volatile functions)

    Inlined → the outer predicate is PUSHED DOWN into the CTE.
    → the customer_id = 42 filter applies during the scan. Far faster.
```

```sql
-- ⭐ You can force either behaviour explicitly:
WITH recent AS MATERIALIZED     ( ... )     -- always materialise (a fence)
WITH recent AS NOT MATERIALIZED ( ... )     -- always inline
```

**When you genuinely want `MATERIALIZED`:**

```sql
-- The CTE is expensive and referenced multiple times — compute it once
WITH expensive AS MATERIALIZED (
    SELECT tenant_id, complex_aggregate(...) FROM huge_table GROUP BY 1
)
SELECT * FROM expensive a JOIN expensive b ON ...;

-- Or: you want to force a specific evaluation order because the planner
-- is making a bad choice. ⭐ This is a legitimate use, but treat it as
-- a hint of last resort and document WHY in a comment.
```

### Subquery pullup

```sql
SELECT * FROM (SELECT * FROM orders WHERE total > 100) x WHERE customer_id = 42;
```

The planner **flattens** this into a single scan with both predicates. Subqueries in `FROM` are generally free; they do not create a fence.

### EXISTS vs IN vs JOIN

```sql
-- These are usually planned IDENTICALLY (as a semi-join):
SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);
SELECT * FROM customers c WHERE c.id IN (SELECT customer_id FROM orders);

-- EXPLAIN shows:  Hash Semi Join     ⭐ a semi-join stops at the first match

-- ⚠ NOT IN is DIFFERENT and dangerous:
SELECT * FROM customers WHERE id NOT IN (SELECT customer_id FROM orders);
-- ⭐ If ANY customer_id is NULL, this returns ZERO ROWS (SQL's three-valued
--    logic). It also usually cannot be optimised into an anti-join.
-- ✅ Use NOT EXISTS instead — NULL-safe and plans as a Hash Anti Join.
```

**`NOT IN` with a nullable column is one of the most common SQL correctness bugs**, and it is also a performance problem. Prefer `NOT EXISTS` unconditionally.

---

## 22. Reading EXPLAIN properly — every field

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS, WAL, FORMAT TEXT) <query>;
```

| Option | Gives you |
|--------|-----------|
| `ANALYZE` | ⭐ **Actually runs it**; adds actual times and rows |
| `BUFFERS` | ⭐ Page hits/reads/dirtied/written, and temp I/O |
| `VERBOSE` | Output column lists, schema-qualified names |
| `SETTINGS` | ⭐ Non-default planner settings in effect |
| `WAL` | WAL records/bytes generated (for writes) |
| `GENERIC_PLAN` | (PG16+) plan a parameterised query without executing |

> ⚠ `ANALYZE` **executes the query**. For `INSERT`/`UPDATE`/`DELETE`, wrap it:
> ```sql
> BEGIN; EXPLAIN (ANALYZE) UPDATE ...; ROLLBACK;
> ```

### A fully annotated plan

```
Limit  (cost=1834.22..1834.25 rows=10 width=52) (actual time=2891.4..2891.5 rows=10 loops=1)
  Buffers: shared hit=48213 read=102847 dirtied=12
  I/O Timings: read=2104.881
  ->  Sort  (cost=1834.22..1902.11 rows=27156 width=52) (actual time=2891.4..2891.4 rows=10 loops=1)
        Sort Key: o.created_at DESC
        Sort Method: top-N heapsort  Memory: 28kB
        Buffers: shared hit=48213 read=102847
        ->  Hash Join  (cost=1204.30..1248.90 rows=27156 width=52) (actual time=412.1..2841.2 rows=891204 loops=1)
              Hash Cond: (o.customer_id = c.id)
              Buffers: shared hit=48213 read=102847
              ->  Seq Scan on orders o  (cost=0.00..108333.50 rows=1440333 width=40)
                                        (actual time=0.02..1904.8 rows=891204 loops=1)
                    Filter: (total > 100)
                    Rows Removed by Filter: 3429796
                    Buffers: shared hit=41002 read=98319
              ->  Hash  (cost=1204.30..1204.30 rows=86420 width=20) (actual time=411.8..411.8 rows=86420 loops=1)
                    Buckets: 131072  Batches: 1  Memory Usage: 5842kB
                    ->  Seq Scan on customers c  (actual time=0.01..184.2 rows=86420 loops=1)
Planning Time: 0.412 ms
Execution Time: 2891.8 ms
```

### Field by field

| Field | Meaning | What to look for |
|-------|---------|-----------------|
| `cost=X..Y` | Estimated startup..total | Only meaningful for comparison |
| `rows=N` | **Estimated** rows | ⭐ Compare against `actual rows` |
| `width=N` | Estimated bytes per row | Drives memory estimates |
| `actual time=X..Y` | ⭐ **Per loop**, in ms | Multiply by `loops` for the real total |
| `actual rows=N` | ⭐ **Per loop** | Multiply by `loops` |
| `loops=N` | Times this node executed | ⭐ High on an inner nested-loop side = trouble |
| `Buffers: shared hit` | Pages from cache | Good |
| `Buffers: shared read` | ⭐ Pages from disk | High = working set exceeds cache |
| `Buffers: shared dirtied` | Pages modified | ⭐ Non-zero on a SELECT = hint bits (DD04 §9) |
| `Buffers: temp read/written` | ⭐ Spill I/O | **Non-zero = raise `work_mem`** |
| `I/O Timings` | ⭐ Actual ms spent on I/O | Requires `track_io_timing = on` |
| `Rows Removed by Filter` | Rows read then discarded | ⭐ High = missing or unselective index |
| `Rows Removed by Index Recheck` | Lossy bitmap rechecks | ⭐ Raise `work_mem` (DD05 §19) |
| `Heap Fetches` | Index-only scan heap visits | ⭐ Non-zero = vacuum more (DD04 §23) |
| `Batches` | Hash spill count | ⭐ **> 1 = raise `work_mem`** |
| `Sort Method` | Which algorithm | ⭐ "external merge" = spilled |
| `Workers Launched` | Actual parallel workers | ⭐ < Planned = pool exhausted |
| `Planning Time` | ⭐ Time to plan | > execution time = too many indexes / too many joins |

### Reading it: the three-step method

```
1. FIND THE TIME.
   actual time is CUMULATIVE and PER LOOP.
   A node's own time = its actual_time × loops − (sum of children's totals).
   ⭐ In the example: Hash Join total = 2841 ms, of which Seq Scan is
      1904 ms and Hash is 411 ms → the join itself is ~525 ms.

2. FIND THE ESTIMATE ERROR.
   ⭐ Here: Hash Join estimated rows=27156, actual rows=891204.
      A 33× UNDERESTIMATE. That is the real problem — everything
      downstream was planned for 27k rows.

3. FIND THE I/O.
   read=102847 pages ≈ 800 MB read from disk, 2.1 s of I/O timing.
   ⭐ Two thirds of the total runtime is disk reads.
```

**In this plan the fix is not the join algorithm — it is the 33× estimate error, and the fact that `total > 100` removes only 20% of rows so no index helps.** The real answer is a covering index or a different query shape.

---

## 23. Why estimates go wrong: eight causes

Ranked by how often they are the culprit.

### 1. ⭐ Correlated columns (the independence assumption)

§9. **The most common cause by a wide margin.** Fix: extended statistics (§10).

### 2. ⭐ Stale statistics

```sql
SELECT relname, last_analyze, last_autoanalyze,
       n_mod_since_analyze, n_live_tup,
       round(100.0*n_mod_since_analyze/NULLIF(n_live_tup,0),1) AS pct_changed
FROM pg_stat_user_tables ORDER BY n_mod_since_analyze DESC LIMIT 10;
-- ⭐ pct_changed > 10 and last_analyze old → statistics are stale
```

Fix: lower `autovacuum_analyze_scale_factor`, or `ANALYZE` explicitly after bulk changes.

### 3. ⭐ Out-of-range values on a growing column

§8. The histogram ends before "now". Endemic on time-series tables. Fix: analyze more frequently.

### 4. Expression without statistics

```sql
WHERE lower(email) = '...'          -- ⭐ no stats for lower(email)
WHERE (metadata->>'channel') = 'x'  -- ⭐ no stats for the extraction
```

Fix: create an expression index (which creates statistics — Deep Dive 05 §17) or `CREATE STATISTICS ON (expression)`.

### 5. Compounding join errors

§11. A 5× error at the leaves becomes 125× at the root of a 4-way join.

### 6. Skewed data with an insufficient MCV list

A column with 5,000 distinct values where the top 500 hold 90% of rows. The default 100 MCVs miss most of the skew. Fix: `SET STATISTICS 1000`.

### 7. ⭐ Parameterised queries and the generic plan

§24. The plan is chosen without knowing the value.

### 8. Volatile or opaque functions

```sql
WHERE my_function(col) = 42      -- ⭐ no statistics; planner assumes 0.5% selectivity
```

Fix: mark the function `IMMUTABLE` if it is, and add an expression index.

---

## 24. Plan caching and the generic plan trap ⭐

A major source of "the query was fast yesterday" incidents.

### How PostgreSQL decides

```
For a PREPARED statement (which includes every parameterised query from
a driver using the extended protocol — ⭐ that is most ORMs):

  Executions 1-5:  build a CUSTOM plan each time, using the actual
                   parameter values. Record the cost.

  Execution 6+:    build a GENERIC plan (parameters treated as unknown).
                   ⭐ If generic_cost <= average(custom_costs),
                      USE THE GENERIC PLAN FROM NOW ON, PERMANENTLY.
```

### Why this goes wrong

```sql
PREPARE q(uuid) AS SELECT * FROM orders WHERE tenant_id = $1;
```

```
Tenant distribution:
    tenant A: 4,000,000 orders   (a huge customer)
    tenants B..Z: ~50 orders each (small customers)

Executions 1-5 use small tenants:
    custom plan: Index Scan. Cost ~8. Fast. ✓

Generic plan (no parameter known):
    The planner uses the AVERAGE selectivity: 4,050,000 / 850 tenants ≈ 4,765 rows
    ⭐ It picks a plan reasonable for 4,765 rows — perhaps a Bitmap Heap Scan.

Generic cost ≈ custom cost → PostgreSQL switches to generic.

Execution 6 with tenant B (50 rows):
    Bitmap Heap Scan instead of Index Scan. 10× slower. Survivable.

Execution 7 with tenant A (4 M rows):
    ⭐ The generic plan may nested-loop against another table
       expecting 4,765 rows and get 4,000,000.
       → 200 ms becomes 6 minutes.
```

**And it is sticky:** once the generic plan is chosen, it persists for the life of the prepared statement — which, with a connection pooler in `session` mode, can be hours.

### Diagnosing it

```sql
-- ⭐ PG16+: see the generic plan without executing
EXPLAIN (GENERIC_PLAN) SELECT * FROM orders WHERE tenant_id = $1;

-- Compare against a custom plan with a real value
EXPLAIN (ANALYZE) SELECT * FROM orders WHERE tenant_id = 'the-big-tenant';

-- ⭐ If the shapes differ significantly, you have this problem.
```

### Fixes

```sql
-- 1. ⭐ Force custom plans for this session/role — the usual fix
SET plan_cache_mode = force_custom_plan;
ALTER ROLE app_user SET plan_cache_mode = force_custom_plan;
--    Cost: replanning every execution (typically 0.1-1 ms). Almost
--    always worth it for skewed data.

-- 2. Force generic plans (rare — when planning cost dominates and data
--    is uniform)
SET plan_cache_mode = force_generic_plan;

-- 3. ⭐ Application-level: use a literal for the skewed parameter
--    Most ORMs allow this. It makes each distinct tenant a distinct
--    prepared statement, each with its own plan.

-- 4. Deallocate and re-prepare periodically
DEALLOCATE ALL;
```

> **If your data has heavy skew on a filtered column — which multi-tenant systems almost always do — `plan_cache_mode = force_custom_plan` should be your default.** The replanning cost is trivial compared to a single bad plan.

---

## 25. A systematic procedure for a bad plan

Follow this in order. Do not skip to step 5.

```
STEP 1 — REPRODUCE AND MEASURE
  EXPLAIN (ANALYZE, BUFFERS, SETTINGS) <query>;
  Note: total time, and where it is spent.

STEP 2 — FIND THE ESTIMATE ERROR
  Walk the plan bottom-up. At each node compare rows= vs actual rows.
  ⭐ Find the LOWEST node where the error first exceeds ~10×.
     That is the root cause. Everything above it is a consequence.

STEP 3 — CLASSIFY THE ERROR
  → Single-column estimate wrong?     → stale stats, or raise STATISTICS
  → Multi-column AND wrong?           → ⭐ correlated columns → CREATE STATISTICS
  → Value above the histogram?        → ANALYZE more often
  → Expression in the predicate?      → expression index or CREATE STATISTICS
  → rows=200 on a GROUP BY?           → n_distinct missing → set it
  → Only wrong for some parameters?   → ⭐ generic plan (§24)

STEP 4 — FIX THE ESTIMATE, THEN RE-CHECK
  ⭐ Do NOT skip to changing the plan. A correct estimate usually
     produces the correct plan automatically, and the fix is durable.

STEP 5 — IF THE ESTIMATE IS NOW CORRECT AND THE PLAN IS STILL BAD:
  a) Is a node spilling? (Batches > 1, external merge, temp read/written)
        → raise work_mem for this query (SET LOCAL)
  b) Are cost constants wrong for the hardware?
        → random_page_cost, effective_cache_size (§3)
  c) Is an index missing?
        → check Rows Removed by Filter; consider a covering index
  d) Is the query shape the problem?
        → rewrite: NOT IN → NOT EXISTS; correlated subquery → join;
          OR → UNION ALL; restructure a 12-way join

STEP 6 — LAST RESORT: STEER THE PLANNER
  ⭐ PostgreSQL has no query hints, deliberately. But you can:
     SET LOCAL enable_nestloop = off;      -- ⚠ session/transaction scoped
     WITH x AS MATERIALIZED (...)          -- an intentional fence
     OFFSET 0 in a subquery                -- an old-school fence

  ⭐ Treat all of these as temporary mitigations with a comment explaining
     why, plus a ticket to fix the underlying estimate. They are brittle
     and they hide the real problem.
```

> **Step 4 is the discipline that separates durable fixes from whack-a-mole.** Teams that jump to `enable_nestloop = off` accumulate a codebase full of planner hints that break on the next upgrade. Teams that fix estimates end up with a database that plans correctly on its own.

---

## 26. Tooling: auto_explain, pg_stat_statements, hypothetical indexes

### auto_explain — capture plans in production

```sql
-- postgresql.conf
shared_preload_libraries = 'auto_explain,pg_stat_statements'

auto_explain.log_min_duration = '1s'        -- ⭐ log plans for slow queries
auto_explain.log_analyze = on               -- ⚠ adds overhead; measure first
auto_explain.log_buffers = on
auto_explain.log_timing = off               -- ⭐ reduces overhead a lot
auto_explain.log_nested_statements = on     -- plans inside functions
auto_explain.log_format = 'json'
auto_explain.sample_rate = 0.05             -- ⭐ sample 5% to bound overhead
```

**`log_timing = off` with `log_analyze = on` is the useful combination**: you get actual row counts (which is what you need for §23) without per-node timing instrumentation, which is where most of the overhead lives.

### pg_stat_statements — find what to optimise

```sql
CREATE EXTENSION pg_stat_statements;

-- ⭐ Rank by TOTAL time, not mean. A 5 ms query called 2 M times costs
--    more than a 3 s report run twice a day.
SELECT substring(query,1,80) AS query,
       calls,
       round(total_exec_time::numeric,0)   AS total_ms,
       round(mean_exec_time::numeric,2)    AS mean_ms,
       round(stddev_exec_time::numeric,2)  AS stddev_ms,
       rows,
       round(100.0*shared_blks_hit/NULLIF(shared_blks_hit+shared_blks_read,0),1) AS hit_pct
FROM pg_stat_statements
ORDER BY total_exec_time DESC LIMIT 20;
```

**⭐ `stddev_exec_time` is the under-used column.** A query with a mean of 20 ms and a standard deviation of 800 ms has *unstable plans* — often the generic-plan problem (§24) or a parameter-dependent data skew. That is a different problem from "slow on average" and needs a different fix.

```sql
-- Queries that spill
SELECT substring(query,1,60), calls, temp_blks_written
FROM pg_stat_statements WHERE temp_blks_written > 0
ORDER BY temp_blks_written DESC LIMIT 10;

-- Queries with the worst cache hit ratios
SELECT substring(query,1,60), calls, shared_blks_read
FROM pg_stat_statements WHERE shared_blks_read > 100000
ORDER BY shared_blks_read DESC LIMIT 10;
```

### HypoPG — test an index without building it

```sql
CREATE EXTENSION hypopg;

SELECT * FROM hypopg_create_index(
    'CREATE INDEX ON orders (customer_id, created_at DESC)');

EXPLAIN SELECT * FROM orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 10;
-- ⭐ The planner considers the hypothetical index and shows whether it
--    would be used, with cost estimates — WITHOUT building a 20 GB index.

SELECT hypopg_reset();
```

**This is enormously useful on large tables**, where building a candidate index takes an hour and you want to know first whether the planner would even choose it.

---

## 27. What an architect takes from this

**1. `random_page_cost = 4.0` and a default `effective_cache_size` are wrong on modern hardware** and systematically distort every plan. Two settings, large effect.

**2. The independence assumption is the #1 cause of bad plans.** Any query filtering on correlated columns — hierarchies, denormalised copies, derived values, tenant-scoped enums — is mis-estimated by the correlation factor. **Extended statistics fix it and almost nobody uses them.**

**3. Underestimates are far more dangerous than overestimates**, because they lead to nested loops and under-sized hash tables. "Nested Loop with a large actual row count on the outer side" is the signature.

**4. Fix the estimate, not the plan.** A correct estimate usually produces a correct plan automatically and stays correct through upgrades. Planner hints are brittle mitigations that hide the real problem.

**5. `work_mem` is per node, per worker** — not per query or per connection. A modest global default plus `SET LOCAL` for the queries that need it is the right pattern. `log_temp_files` finds them for free.

**6. `Batches: 1` and `Sort Method: quicksort` are the targets.** Any spill visible in `EXPLAIN (ANALYZE, BUFFERS)` is a memory problem, not a plan problem.

**7. The generic plan trap is a real production incident class** for any multi-tenant system with skewed data. `plan_cache_mode = force_custom_plan` should be the default there.

**8. Declare your foreign keys.** Beyond integrity, the planner uses them to produce far better join estimates.

**9. Rank optimisation targets by total time, and look at `stddev_exec_time`.** High variance means unstable plans, which is a different problem from slow-on-average.

**10. `NOT IN` on a nullable column is both a correctness bug and a performance bug.** Use `NOT EXISTS`, always.

**11. Query planning is the layer where all the previous deep dives meet.** Correlation (DD05 §20) comes from key choice (DD05 §11); index-only scans depend on the visibility map (DD04 §23); statistics staleness depends on autovacuum (DD04 §18). A slow query is usually a symptom of a decision made three layers down.

---

## Exercises

1. Compute the sequential scan cost for a table in your system by hand from `pg_class`, then verify against `EXPLAIN`.
2. Take a column in your system and compute the equality selectivity for (a) an MCV value and (b) a non-MCV value, by hand from `pg_stats`. Verify against `EXPLAIN`.
3. Find two correlated columns in your schema. Measure the estimate error for a query filtering on both, then create extended statistics and measure again.
4. Construct a query where `LIMIT 10` and `LIMIT 10000` produce different plans. Explain using startup vs total cost.
5. Force a hash join to spill by lowering `work_mem`. Measure the difference and read the `Batches` and `temp` figures.
6. Find a query in your system that creates temp files (`log_temp_files`). Size `work_mem` correctly for it using `SET LOCAL`.
7. Compute the worst-case memory your system could allocate: `max_connections × typical nodes × work_mem`. Is it safe?
8. Write a query with `ORDER BY a, b` where an index exists on `(a)`. Confirm `Incremental Sort` is used and explain the memory benefit.
9. Find a `GROUP BY` in your system where the estimate is exactly `rows=200`. Fix it with `n_distinct`.
10. Create a prepared statement on a skewed column. Execute it six times with small values, then once with a large one. Demonstrate the generic plan problem.
11. Use `EXPLAIN (GENERIC_PLAN)` on your three most important parameterised queries. Do any differ materially from the custom plan?
12. Use HypoPG to evaluate three candidate indexes for a slow query without building any of them.
13. Take the slowest query in `pg_stat_statements` by total time and work through the full §25 procedure. Document each step.
14. Find a query with high `stddev_exec_time`. Determine whether it is the generic plan trap, data skew, or parallel worker availability.

---

**Next in this series:** Deep Dive 07 — Write-Ahead Logging, Checkpoints and Recovery

**Back to:** [Deep Dives](README.md) · [Chapter 09](../09-database-architecture.md) · [The Map](../README.md)
