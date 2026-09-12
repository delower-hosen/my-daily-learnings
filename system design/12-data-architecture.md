# Chapter 12 — Data Architecture (OLTP, OLAP, Pipelines, Lakehouse) 🟡

> Every company eventually discovers that the database running the product is a terrible place to answer questions about the business.
> Data architecture is what you build to fix that — without taking the product down.

---

## 12.1 OLTP vs OLAP — the fundamental split

| | **OLTP** (Online Transaction Processing) | **OLAP** (Online Analytical Processing) |
|---|---|---|
| **Purpose** | Run the business | Understand the business |
| **Typical query** | "Get order 8812" | "Revenue by region by month for 3 years" |
| **Rows touched** | 1 to 100 | Millions to billions |
| **Columns touched** | All of them | 3 to 8 out of 200 |
| **Writes** | Constant, small, concurrent | Bulk loads, append-only |
| **Latency target** | 1–50 ms | 1–60 seconds is fine |
| **Concurrency** | Thousands of users | Tens of analysts + dashboards |
| **Data model** | Normalised (3NF) | Denormalised (star schema) |
| **Storage layout** | **Row-oriented** | **Column-oriented** |
| **Freshness** | Now | Minutes to a day is usually fine |
| **Examples** | PostgreSQL, MySQL, SQL Server | Snowflake, BigQuery, Redshift, ClickHouse, Databricks |

### Why row vs column storage changes everything

```
ROW STORE (OLTP) — all of one record stored together
  [id=1, name=Alice, city=Dhaka, amount=100][id=2, name=Bob, city=Delhi, amount=250]...

  "Get order 1"          → read one contiguous block. PERFECT.
  "SUM(amount) of 1B"    → read EVERY byte of EVERY row to get one column. TERRIBLE.

COLUMN STORE (OLAP) — all of one column stored together
  id:     [1, 2, 3, 4, ...]
  name:   [Alice, Bob, Carol, ...]
  city:   [Dhaka, Delhi, Dhaka, ...]
  amount: [100, 250, 80, ...]

  "SUM(amount) of 1B"    → read ONLY the amount column. 50× less I/O.
  "Get order 1"          → reassemble from 200 separate locations. Slow.
```

**Columnar storage also compresses far better**, because a column contains similar values: run-length encoding on `city`, dictionary encoding on `status`, delta encoding on timestamps. 10–30× compression is routine — which means 10–30× less I/O on top of reading fewer columns.

> **This is why you cannot just "run reports on the production database".** It is not a policy choice; the storage layout is wrong for the job. An analytical query on your OLTP database scans the same pages your customers' transactions need, evicts your buffer pool, and holds snapshots that block vacuum (Chapter 09).

### The three stages every company goes through

```
STAGE 1  Report directly on the production DB
         → works until it doesn't. One analyst's query locks checkout.

STAGE 2  Report on a read replica
         → good, cheap, buys years. But: still row-storage, still one schema,
           still no history, and heavy queries can lag the replica.

STAGE 3  A real analytical store (warehouse/lakehouse) fed by a pipeline
         → columnar, historical, modelled for analysis, isolated from production.
```

> **Architect's guidance: go to Stage 2 immediately** (it costs almost nothing). **Go to Stage 3 when** analysts are blocked, when you need history that OLTP overwrites, or when you must join data from several systems.

---

## 12.2 Dimensional modelling — the star schema 🟢

Kimball's star schema is the standard way to model analytical data. It is deliberately *denormalised*, for a good reason.

```
                   ┌───────────────┐
                   │  dim_date     │
                   │ date_key (PK) │
                   │ date          │
                   │ day_of_week   │
                   │ month, quarter│
                   │ is_holiday    │
                   │ fiscal_period │
                   └───────┬───────┘
                           │
   ┌───────────────┐   ┌───▼──────────────────────────┐   ┌────────────────┐
   │ dim_customer  │   │      fact_verification       │   │  dim_tenant    │
   │ customer_key  │◄──┤ date_key        (FK)         ├──►│ tenant_key (PK)│
   │ customer_id   │   │ customer_key    (FK)         │   │ tenant_id      │
   │ name          │   │ tenant_key      (FK)         │   │ name           │
   │ country       │   │ device_key      (FK)         │   │ plan           │
   │ segment       │   │ ──────────────────────────── │   │ industry       │
   │ valid_from    │   │ session_count      (measure) │   │ region         │
   │ valid_to      │   │ passed_count       (measure) │   └────────────────┘
   │ is_current    │   │ duration_ms        (measure) │
   └───────────────┘   │ liveness_score     (measure) │   ┌────────────────┐
                       │ cost_usd           (measure) │──►│  dim_device    │
                       └──────────────────────────────┘   │ device_key (PK)│
                                                          │ os, model      │
                                                          └────────────────┘
```

### Facts and dimensions

| | **Fact table** | **Dimension table** |
|---|---|---|
| Contains | Measurements/events — the numbers | Descriptive context — the adjectives |
| Size | Huge (billions of rows) | Small (thousands to millions) |
| Grain | One row per event/day/transaction | One row per entity |
| Columns | Foreign keys + numeric measures | Many descriptive attributes |
| Changes | Append-only | Slowly changing |

**The grain declaration is the most important design decision.** State it in one sentence before writing any DDL:

> *"One row in `fact_verification` represents one completed verification attempt."*

Everything else follows from that. A confused grain (some rows are attempts, some are daily summaries) produces permanently wrong numbers that nobody can debug.

### Why denormalise? Because analysts write the queries

```sql
-- STAR SCHEMA: one join per dimension, readable, fast
SELECT t.region, d.month, count(*) AS verifications, avg(f.liveness_score) AS avg_score
FROM fact_verification f
JOIN dim_tenant t ON t.tenant_key = f.tenant_key
JOIN dim_date   d ON d.date_key   = f.date_key
WHERE d.year = 2026
GROUP BY 1, 2;

-- NORMALISED (3NF): the same question needs 8 joins, and an analyst gets it wrong.
```

The star schema optimises for **human comprehension and query-engine performance**, not for storage efficiency. Storage is cheap; analyst time and wrong numbers are not.

### Snowflake schema

A star schema where dimensions are further normalised into sub-dimensions (`dim_customer → dim_city → dim_country`).

- ✅ Less redundancy, easier to maintain shared hierarchies
- ❌ More joins, harder for humans, usually slower

> **Default to the star schema.** Snowflake only where a hierarchy is genuinely shared across many dimensions and changes often.

### Slowly Changing Dimensions (SCD) ⭐

A customer moves from Dhaka to Delhi. What happens to last year's reports?

| Type | Behaviour | Use when |
|------|-----------|----------|
| **Type 0** | Never changes | Immutable attributes (date of birth) |
| **Type 1** | Overwrite — history is lost | Corrections of genuine errors (typo in a name) |
| **Type 2** ⭐ | **Add a new row with validity dates** | **The default for anything analytically meaningful** |
| **Type 3** | Keep a "previous value" column | You only ever need one step of history |
| **Type 4/6** | Hybrid — a current table plus a history table | Advanced cases |

```sql
-- SCD Type 2: history preserved
customer_key | customer_id | name    | city   | valid_from | valid_to   | is_current
-------------|-------------|---------|--------|------------|------------|------------
        1001 | cus_42      | Delower | Dhaka  | 2024-01-01 | 2026-06-30 | false
        1002 | cus_42      | Delower | Delhi  | 2026-07-01 | 9999-12-31 | true
```

Now a 2025 report correctly shows that customer in Dhaka, while today's dashboard shows Delhi. **This is the difference between a warehouse that tells the truth about the past and one that quietly rewrites history.**

Note the surrogate key (`customer_key`) — facts point at the *version*, not at the business ID. This is why warehouses use surrogate keys rather than natural keys.

---

## 12.3 ETL vs ELT 🟢

### ETL — Extract, Transform, Load (the classic)

```
Source DB ──extract──► [ Transformation engine ] ──load──► Warehouse
                        (Informatica, SSIS, Talend,
                         or your Python script)
```

Transform *before* loading. Only clean, modelled data lands in the warehouse.

- ✅ The warehouse stays clean; less storage; good when the target is expensive or rigid
- ❌ Transformation logic lives outside the warehouse (harder to test and version); reprocessing means re-extracting from source; the transformation engine is a bottleneck and a separate thing to scale

### ELT — Extract, Load, Transform ⭐ (the modern default)

```
Source DB ──extract──► Warehouse (raw) ──transform IN the warehouse──► modelled tables
                                          (dbt, SQL, Spark)
```

Load raw data first; transform inside the warehouse using its own compute.

- ✅ **Raw data is preserved** — you can reprocess without touching production
- ✅ Transformations are **SQL in version control**, testable, reviewable (this is what dbt made popular)
- ✅ The warehouse's massive parallel compute does the work
- ✅ New questions can be answered from history you already landed
- ❌ More storage (cheap); raw data in the warehouse needs governance and access control

> **Why ELT won:** cloud storage became almost free and warehouse compute became elastic. The old reason for ETL (do not waste expensive warehouse capacity) evaporated. And the ability to **reprocess from raw** is worth an enormous amount the first time a transformation bug is discovered three months later.

### The modern ELT stack

```
EXTRACT & LOAD:   Fivetran / Airbyte / Debezium / custom
STORE:            Snowflake / BigQuery / Databricks / S3+Iceberg
TRANSFORM:        dbt (SQL + Jinja, tests, docs, lineage)
ORCHESTRATE:      Airflow / Dagster / Prefect
SERVE:            Looker / Metabase / Power BI / Superset
```

```sql
-- A dbt model: just SQL, but version-controlled, tested and dependency-aware
-- models/marts/fact_verification.sql
{{ config(materialized='incremental', unique_key='verification_id',
          partition_by={'field': 'created_date', 'data_type': 'date'}) }}

SELECT
    s.id                                        AS verification_id,
    {{ dbt_utils.generate_surrogate_key(['s.tenant_id']) }}   AS tenant_key,
    d.date_key,
    s.score                                     AS liveness_score,
    CASE WHEN s.status = 'passed' THEN 1 ELSE 0 END AS passed_flag,
    s.duration_ms,
    s.created_at::date                          AS created_date
FROM {{ ref('stg_sessions') }} s
JOIN {{ ref('dim_date') }} d ON d.date = s.created_at::date

{% if is_incremental() %}
  WHERE s.created_at > (SELECT max(created_at) FROM {{ this }})   -- only new rows
{% endif %}
```

```yaml
# And the tests live next to it — data quality as code
models:
  - name: fact_verification
    columns:
      - name: verification_id
        tests: [unique, not_null]
      - name: liveness_score
        tests:
          - dbt_utils.accepted_range: { min_value: 0, max_value: 1 }
      - name: tenant_key
        tests:
          - relationships: { to: ref('dim_tenant'), field: tenant_key }
```

> **This is the single biggest improvement in data engineering of the last decade:** transformations as reviewed, tested, version-controlled code with automatic lineage — instead of undocumented SQL in a scheduler someone set up in 2019.

---

## 12.4 Change Data Capture (CDC) 🟢

**The problem with batch extraction:**

```sql
-- The naive incremental extract
SELECT * FROM orders WHERE updated_at > :last_run;
```

What it misses:
- **Deletes** (the row is gone — you never see it, so the warehouse keeps a ghost forever)
- **Intermediate states** (a row changed 3 times between runs; you see only the last)
- Rows where the application forgot to set `updated_at` (it happens constantly)
- It puts load on the production database
- Clock/transaction ordering edge cases at the boundary

**CDC reads the database's transaction log instead** — the same WAL used for replication (Chapter 09).

```
PostgreSQL WAL ──► Debezium ──► Kafka ──► Warehouse / Lake / Search / Cache
                   (decodes the log into row-level change events)
```

```json
{
  "op": "u",                       // c=create, u=update, d=delete, r=snapshot read
  "before": { "id": 42, "status": "pending",  "score": null },
  "after":  { "id": 42, "status": "passed",   "score": 0.94 },
  "source": { "ts_ms": 1757673600123, "lsn": 24857392, "table": "sessions" }
}
```

**What CDC gives you:**
- **Every change, including deletes and intermediate states**
- **Near-real-time** (sub-second) instead of hourly batches
- **Almost no load** on the production database (it reads the log, not the tables)
- **Exact ordering**, guaranteed by the transaction log
- One pipeline feeding many consumers: warehouse, search index, cache invalidation, event stream

**What it costs:** Kafka + Connect + Debezium to run and monitor; replication slot management (Chapter 09 — an abandoned slot fills your disk); schema changes in the source ripple downstream; initial snapshots of large tables need care.

> **CDC is also how you do the Outbox relay at scale** (Chapter 06) and how you keep derived stores (Elasticsearch, Redis, the warehouse) in sync from one authoritative pipeline instead of five ad-hoc ones. That consolidation is the real architectural win.

---

## 12.5 Batch vs Stream processing 🟢

| | **Batch** | **Stream** |
|---|---|---|
| Processes | A bounded set of data | An unbounded, continuous flow |
| Trigger | Schedule (hourly, nightly) | Each event, or a small window |
| Latency | Minutes to hours | Milliseconds to seconds |
| Correctness | Easy — you have all the data | Hard — data arrives late and out of order |
| Reprocessing | Just re-run it | Requires replay (Chapter 07) |
| Cost | Efficient — big machines, briefly | Always-on infrastructure |
| Complexity | Low | High |
| Tools | Spark, dbt, SQL, Airflow | Flink, Kafka Streams, Spark Structured Streaming |

### When you genuinely need streaming

Be honest, because streaming costs roughly 3× the engineering effort:

✅ **Real streaming justified:**
- Fraud detection while the transaction is in flight
- Real-time personalisation and recommendations
- Operational monitoring and alerting
- Live dashboards where seconds matter commercially
- Dynamic pricing, inventory sync across channels

❌ **Batch is fine (and most "real-time" requests are this):**
- Daily/weekly business reports
- Monthly billing
- Model training
- Most executive dashboards ("real-time" usually means "not 3 days old")

> **Ask: "what decision will be made differently because this data is 5 minutes old instead of 4 hours old?"** If nobody can answer with a specific action, you need batch. This single question saves enormous amounts of money.

### The hard part of streaming: time

```
EVENT TIME      when it actually happened on the device       ← what you care about
PROCESSING TIME when your system received it                  ← what is easy to use
```

A mobile app goes offline in a lift and uploads 20 events 10 minutes later. Which window do they belong to?

```
Windows (all operate on EVENT time):
  TUMBLING   [0-5min][5-10min][10-15min]      fixed, non-overlapping
  HOPPING    [0-5][2-7][4-9]                  fixed size, overlapping (sliding)
  SESSION    [activity]...gap...[activity]    grouped by inactivity gaps
```

**Watermarks** tell the system "I believe I have seen all events up to time T; it is safe to close that window." Data arriving after the watermark is **late data**, and you must decide: drop it, send it to a side output, or re-emit a corrected result. Every serious streaming system makes you answer this.

### Lambda vs Kappa architecture ⚪🟡

**Lambda** — run both a batch layer (accurate, slow) and a speed layer (fast, approximate), and merge them at query time.
- ✅ Accurate *and* fast
- ❌ **You maintain the same business logic twice, in two languages.** They drift. This is why Lambda fell out of favour.

**Kappa** — one streaming pipeline. To recompute history, replay the log through the same code.
- ✅ One codebase, one set of logic
- ❌ Requires long retention in the log and a streaming engine that can handle backfill at speed

> **Modern practice mostly converges on "Kappa-ish with a lakehouse"**: one pipeline writes to an open table format (Iceberg/Delta) that serves both streaming reads and batch queries. One copy, one logic path.

---

## 12.6 Data Lake, Warehouse, Lakehouse 🟡

### Data Warehouse

Structured, modelled, schema-on-write. You decide the schema before loading.

- ✅ Fast queries, governed, trusted, great BI tooling
- ❌ Rigid; expensive for raw/semi-structured data; you must model before you know the questions

Examples: Snowflake, BigQuery, Redshift, Synapse.

### Data Lake

Raw files in cheap object storage (S3/ADLS/MinIO). Schema-on-read.

- ✅ Cheap, stores anything (JSON, images, video, logs, Parquet), keeps everything for later
- ❌ **Becomes a data swamp** without discipline: no schema enforcement, no ACID, no idea what is in there, duplicated files, no way to update or delete a row

> The industry learned this the hard way around 2015–2019. "Just dump everything in S3 and figure it out later" produced petabytes nobody could use.

### Lakehouse ⭐ (the current consensus)

Cheap object storage + an **open table format** that adds warehouse features on top of files.

```
        ┌──────────────────────────────────────────────┐
        │  QUERY ENGINES (any of them, same data)      │
        │  Spark · Trino · Snowflake · DuckDB · Flink  │
        └───────────────────┬──────────────────────────┘
                            │
        ┌───────────────────▼──────────────────────────┐
        │  TABLE FORMAT: Apache Iceberg / Delta / Hudi │
        │  • ACID transactions    • schema evolution   │
        │  • time travel          • partition evolution│
        │  • row-level UPDATE/DELETE (GDPR!)           │
        │  • snapshot isolation   • compaction         │
        └───────────────────┬──────────────────────────┘
                            │
        ┌───────────────────▼──────────────────────────┐
        │  FILE FORMAT: Parquet (columnar, compressed) │
        │  OBJECT STORAGE: S3 / ADLS / GCS / MinIO     │
        └──────────────────────────────────────────────┘
```

**What the table format adds that raw Parquet cannot do:**

| Feature | Why it matters |
|---------|---------------|
| **ACID commits** | Two jobs writing concurrently do not corrupt the table; readers never see half a write |
| **Row-level DELETE/UPDATE** | **GDPR "delete this person"** on a data lake — previously nearly impossible |
| **Time travel** | `SELECT ... FOR VERSION AS OF 12` — reproduce last Tuesday's report exactly |
| **Schema evolution** | Add/rename/reorder columns without rewriting petabytes |
| **Hidden partitioning** (Iceberg) | Query authors do not need to know the partition scheme to get pruning |
| **Compaction** | Merges the small-files problem that kills lake performance |

```sql
-- Iceberg gives you warehouse semantics on cheap storage
DELETE FROM verifications WHERE customer_id = 'cus_42';     -- GDPR erasure
SELECT * FROM verifications FOR TIMESTAMP AS OF '2026-09-01';  -- time travel
ALTER TABLE verifications ADD COLUMN device_model STRING;   -- instant, no rewrite
```

> **Apache Iceberg has largely become the neutral standard** — Snowflake, BigQuery, Databricks, Trino, Spark and Flink all read it. Practically, that means **your data is no longer locked inside one vendor's warehouse**, which is a genuine architectural advantage worth raising in any vendor discussion.

### Medallion architecture 🟡

The standard way to organise a lakehouse, in three layers:

```
┌──────────────────────────────────────────────────────────────┐
│ BRONZE  — raw, as ingested, immutable, append-only           │
│           • exact copy of source, plus ingestion metadata     │
│           • NEVER edited. This is your ability to reprocess.  │
├──────────────────────────────────────────────────────────────┤
│ SILVER  — cleaned, conformed, deduplicated, typed            │
│           • validated, joined, standardised, PII handled      │
│           • one row per business entity/event, trustworthy    │
├──────────────────────────────────────────────────────────────┤
│ GOLD    — business-level aggregates and marts                │
│           • star schemas, KPIs, feature tables for ML         │
│           • what dashboards and analysts actually query       │
└──────────────────────────────────────────────────────────────┘
```

**Why the layers matter:**
- **Bronze is your insurance.** Any transformation bug is recoverable because the raw truth is still there.
- **Silver is your contract.** Downstream teams build on clean data, not on source-system quirks.
- **Gold is the product.** It is shaped for questions, not for storage.

Rules: bronze is never modified; each layer is derived only from the layer above; quality tests run at each boundary.

---

## 12.7 Data pipelines and orchestration 🟡

### The DAG model

```python
# Airflow — the most common orchestrator
with DAG("daily_verification_marts", schedule="0 2 * * *",
         catchup=False, max_active_runs=1) as dag:

    extract = PostgresToS3Operator(task_id="extract_sessions", ...)
    load    = S3ToSnowflakeOperator(task_id="load_bronze", ...)
    dbt_run = BashOperator(task_id="dbt_transform", bash_command="dbt build --target prod")
    quality = GreatExpectationsOperator(task_id="validate_gold", ...)
    notify  = SlackOperator(task_id="notify", ...)

    extract >> load >> dbt_run >> quality >> notify
```

| Tool | Character |
|------|-----------|
| **Airflow** | The incumbent. Huge ecosystem. Task-centric; testing is awkward. |
| **Dagster** | **Asset-centric** — you declare the data assets, it works out the tasks. Better testing, better lineage. The modern choice for new builds. |
| **Prefect** | Python-native, dynamic workflows, lighter feel |
| **dbt** | Not an orchestrator — it handles the transform layer's internal DAG. Usually run *by* an orchestrator. |
| **Temporal** | Durable workflows for *application* processes (sagas), not primarily data pipelines |

### Pipeline design rules 🟢

**1. Idempotent** — re-running a task must produce the same result, not duplicates.

```sql
-- ❌ Not idempotent
INSERT INTO fact_verification SELECT * FROM staging WHERE date = '2026-09-12';

-- ✅ Idempotent: delete the partition, then insert (or MERGE)
DELETE FROM fact_verification WHERE created_date = '2026-09-12';
INSERT INTO fact_verification SELECT * FROM staging WHERE date = '2026-09-12';
```

**2. Partitioned by time** — process one day/hour at a time so you can reprocess one unit without touching the rest.

**3. Backfillable** — every task takes a date parameter. Re-running last March must be one command.

**4. Observable** — record rows in, rows out, duration, and failures for every run. A pipeline that "succeeded" while producing zero rows is a silent disaster.

**5. Fail loudly, never partially** — write to a staging location, validate, then atomically swap. Never leave a half-written table that dashboards will happily query.

**6. Bounded** — cap memory and rows per task; a task that OOMs at 3 AM on a busy day is a design flaw, not bad luck.

### Data quality — test your data like you test your code

```python
# Great Expectations / dbt tests / Soda — the four categories that matter
expect_column_values_to_not_be_null("verification_id")
expect_column_values_to_be_unique("verification_id")
expect_column_values_to_be_between("liveness_score", 0, 1)
expect_table_row_count_to_be_between(min_value=1000, max_value=100000)   # volume anomaly
expect_column_values_to_match_regex("tenant_id", r"^t_[a-z0-9]{8}$")
```

**The four dimensions to check at every layer boundary:**

| Dimension | Question | Test |
|-----------|----------|------|
| **Completeness** | Is anything missing? | Row counts vs source, null rates |
| **Accuracy** | Are the values right? | Ranges, referential integrity, reconciliation vs source totals |
| **Timeliness** | Did it arrive on time? | Freshness check: `max(updated_at) > now() - 2h` |
| **Consistency** | Do systems agree? | Warehouse revenue vs the billing system's revenue |

> **The reconciliation test is the one that saves careers:** compare a headline number in the warehouse against the operational system every day. When they diverge, you find out before the CFO does.

### Data lineage 🟡

*"This number on the executive dashboard — where does it come from, and what breaks if I change this column?"*

Lineage answers both. Modern tools (dbt docs, Dagster, OpenLineage, DataHub, Atlan) derive it automatically by parsing SQL.

**Why architects care:**
- **Impact analysis** — "if we rename this source column, what breaks?" (23 downstream models, 4 dashboards)
- **Debugging** — a wrong number traced back to its source in minutes rather than days
- **Compliance** — "prove where this PII field flows and everywhere it is stored"
- **Deprecation** — you can safely delete a table when you can prove nothing reads it

---

## 12.8 Data Mesh and Data Fabric ⚪

Both are **organisational** ideas more than technologies. Know the vocabulary; be sceptical of the hype.

### Data Mesh

A reaction to the central data team becoming a bottleneck (every request queued behind one overloaded team).

Four principles:
1. **Domain ownership** — the team that produces the data owns its analytical data too
2. **Data as a product** — with an owner, SLAs, documentation, quality guarantees and consumers
3. **Self-serve platform** — a central platform team provides the tooling, not the pipelines
4. **Federated governance** — global standards (naming, PII handling, interoperability), local autonomy

> This is **Conway's Law applied to data** (Chapter 00), and **bounded contexts applied to analytics** (Chapter 03). The idea is sound. The failure mode is doing it at 30 people, where you simply do not have enough domain teams to justify the coordination overhead — and you end up with five inconsistent mini-warehouses and no central truth.

**Rule of thumb:** data mesh starts to make sense when the central data team has become a genuine, measured bottleneck and you have many autonomous product teams. Below that, a central team with good tooling wins.

### Data Fabric

A more vendor-driven concept: a unified metadata and integration layer over distributed data, with heavy automation and active metadata. In practice it usually means "buy our platform". Awareness is enough.

---

## 12.9 A reference data architecture

Putting it together for a mid-sized SaaS:

```
┌─────────────── OPERATIONAL (OLTP) ───────────────┐
│  PostgreSQL (product)   MongoDB    Stripe   CRM  │
└────┬──────────────────────┬──────────┬───────┬───┘
     │ CDC (Debezium)       │ CDC      │ API   │ API
     ▼                      ▼          ▼       ▼
┌──────────────────────────────────────────────────┐
│  INGESTION:  Kafka  /  Fivetran / Airbyte        │
└────────────────────┬─────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────┐
│  LAKEHOUSE (S3/MinIO + Iceberg + Parquet)        │
│  ┌────────┐  ┌────────┐  ┌────────┐              │
│  │ BRONZE │─►│ SILVER │─►│  GOLD  │              │
│  │  raw   │  │ clean  │  │ marts  │              │
│  └────────┘  └────────┘  └────────┘              │
│         transformed by dbt / Spark               │
│         orchestrated by Dagster / Airflow        │
│         tested by Great Expectations / dbt tests │
└────────────────────┬─────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────┐
│  SERVING                                         │
│  Trino / DuckDB (ad-hoc)  ·  Metabase (BI)       │
│  ClickHouse (fast dashboards)                    │
│  Feature store (ML)  ·  Reverse ETL (back to CRM)│
└──────────────────────────────────────────────────┘
```

### And the version you should actually start with

```
PostgreSQL (production)
    │ nightly logical replication or a scheduled dump
    ▼
PostgreSQL read replica / separate analytics database
    │ dbt models (version-controlled SQL)
    ▼
Metabase / Superset dashboards
```

> **That stack costs almost nothing, takes a week, and serves a company to roughly $20M in revenue.** Build the diagram above it only when a specific limit is hit — data volume, source-system count, or latency. Data architecture is the area where over-engineering is most expensive and most common, because the tooling is exciting and the business impact is indirect.

---

## 12.10 Governance, PII and retention 🟢

Analytical systems are where privacy violations quietly accumulate, because data gets copied and nobody tracks it.

**Minimum discipline:**

1. **Classify every column** — public / internal / confidential / PII / special-category
2. **Never land raw PII in the lake** unless you must. Prefer:
   - **Tokenisation** — replace with a reversible token; the mapping lives in one vault
   - **Hashing** — for join keys you never need to reverse (salt it)
   - **Masking** — `d****r@example.com`
   - **Aggregation** — do analysts need the individual, or the count?
3. **Column-level access control** — analysts see `country`, not `passport_number`
4. **Retention policies per layer** — bronze 90 days, silver 2 years, gold 7 years. Automated deletion, not a calendar reminder.
5. **Right to erasure** — this is why Iceberg/Delta row-level deletes matter. Plan it before you need it. For immutable logs, **crypto-shredding** (Chapter 02): encrypt per-subject, delete the key.
6. **Audit access** — who queried what, especially PII columns
7. **Data residency** — if EU data must stay in the EU, your pipeline and warehouse region are architectural constraints, not deployment details

> **Architect's question to ask early: "If a customer demands deletion tomorrow, list every place their data lives and how we remove it from each."** If nobody can answer in 10 minutes, that is your highest-priority data-architecture finding.

---

## 12.11 Common mistakes

1. **Running analytics on the production OLTP database** — locks, buffer-pool eviction, blocked vacuum
2. **No grain declaration** on a fact table — permanently ambiguous numbers
3. **Type 1 dimensions everywhere** — history silently rewritten; last year's reports change
4. **Building a data lake with no table format or catalogue** — a data swamp within a year
5. **Batch extraction on `updated_at`** — deletes and intermediate states lost forever
6. **Streaming when batch would do** — 3× the cost and complexity for data nobody reads until Monday
7. **Non-idempotent pipelines** — a retry doubles yesterday's revenue
8. **No data quality tests** — a broken pipeline silently loads zeros and the dashboard shows a great quarter
9. **No lineage** — a wrong number takes three days to trace
10. **PII copied into the lake unchecked** — a compliance incident waiting to be discovered
11. **No reconciliation against source systems** — the warehouse drifts and nobody notices
12. **Transformations as untracked SQL in a scheduler UI** — unreviewable, untestable, unrecoverable
13. **Over-engineering on day one** — Kafka + Spark + Iceberg + Airflow for 4 GB of data

---

## 12.12 Architect's checklist

- [ ] Analytical workloads are isolated from OLTP (at minimum, a read replica)
- [ ] Fact table grain declared in one sentence before any DDL
- [ ] SCD strategy chosen per dimension; Type 2 where history matters
- [ ] ELT with raw data preserved (bronze), so reprocessing never touches production
- [ ] Transformations are version-controlled, tested, reviewed code (dbt or equivalent)
- [ ] Every pipeline task is idempotent, time-partitioned and backfillable
- [ ] Data quality tests at each layer boundary: completeness, accuracy, timeliness, consistency
- [ ] A daily reconciliation against an operational source-of-truth number
- [ ] Freshness monitoring and alerting on every gold table
- [ ] Lineage available and automatically derived
- [ ] PII classified; minimised, tokenised or masked before landing
- [ ] Retention policy per layer, automated
- [ ] Right-to-erasure procedure written and tested
- [ ] Data residency constraints reflected in region choices
- [ ] Streaming justified by a specific decision that changes with lower latency — or batch chosen
- [ ] The simplest stack that meets the need, with named triggers for the next step

---

## 12.13 Self-test

1. Why can you not simply "run reports on production"? Give the storage-layout reason.
2. Explain columnar storage and why it compresses better.
3. What is the grain of a fact table, and why is declaring it first so important?
4. What is SCD Type 2 and what breaks without it? Give a concrete report example.
5. ETL vs ELT — why did ELT win? What does preserving raw data buy you?
6. Give four things batch `updated_at` extraction misses that CDC catches.
7. Name a question that decides whether you need streaming or batch.
8. Explain event time vs processing time, and what a watermark is for.
9. What does an open table format (Iceberg/Delta) add over plain Parquet on S3? Name five things.
10. Describe the medallion architecture. Why must bronze never be modified?
11. List six rules for a well-designed pipeline task.
12. What are the four dimensions of data quality, and what is the reconciliation test?
13. What is a data mesh, and when does it become appropriate?
14. A customer demands erasure. Walk through everywhere their data lives in a lakehouse, and how you delete it.

---

## 12.14 Key takeaways

- **OLTP and OLAP have opposite storage requirements.** Separate them — a read replica is the cheap first step.
- **Declare the grain** of every fact table before writing DDL
- **SCD Type 2 is the default** for anything analytically meaningful — otherwise you rewrite history
- **ELT with preserved raw data** beats ETL, because reprocessing is the feature you will need most
- **Transformations belong in version control, with tests** — dbt-style. This is the biggest single upgrade most teams can make.
- **CDC beats batch extraction**: it catches deletes, intermediate states and ordering, with almost no source load
- **Streaming costs ~3× the effort.** Justify it with a decision that changes, or use batch.
- **Lakehouse = cheap storage + a table format** that restores ACID, time travel and row-level deletes
- **Medallion: bronze is insurance, silver is the contract, gold is the product**
- **Idempotent, partitioned, backfillable, observable** — the four properties of every pipeline task
- **Test your data like your code**, and reconcile against an operational number daily
- **Start tiny.** A replica + dbt + Metabase serves most companies far longer than they expect.

---

**Next:** [Chapter 13 — Networking](13-networking.md)
