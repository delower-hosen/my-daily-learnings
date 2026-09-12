# অধ্যায় ১২ — Data Architecture (OLTP, OLAP, Pipeline, Lakehouse) 🟡

> প্রতিটা কোম্পানি শেষ পর্যন্ত আবিষ্কার করে যে product চালানো database-টা ব্যবসা নিয়ে প্রশ্নের উত্তর দেওয়ার জন্য একটা ভয়াবহ জায়গা।
> Data architecture হলো সেটা ঠিক করতে আপনি যা বানান — product না নামিয়েই।

---

## ১২.১ OLTP বনাম OLAP — মৌলিক বিভাজন

| | **OLTP** (Online Transaction Processing) | **OLAP** (Online Analytical Processing) |
|---|---|---|
| **উদ্দেশ্য** | ব্যবসা চালানো | ব্যবসা বোঝা |
| **সাধারণ query** | "order 8812 আনো" | "৩ বছরের অঞ্চল ও মাস অনুযায়ী আয়" |
| **যতগুলো row ছোঁয়** | ১ থেকে ১০০ | লাখ থেকে কোটি |
| **যতগুলো কলাম ছোঁয়** | সবগুলো | ২০০-র মধ্যে ৩ থেকে ৮টা |
| **Write** | অবিরাম, ছোট, concurrent | Bulk load, append-only |
| **Latency-র লক্ষ্য** | ১–৫০ ms | ১–৬০ সেকেন্ডই ঠিক আছে |
| **Concurrency** | হাজার হাজার ব্যবহারকারী | কয়েক ডজন বিশ্লেষক + dashboard |
| **Data model** | Normalised (3NF) | Denormalised (star schema) |
| **Storage-এর বিন্যাস** | **Row-ভিত্তিক** | **Column-ভিত্তিক** |
| **তাজা হওয়া** | এখন | মিনিট থেকে একদিন সাধারণত ঠিক আছে |
| **উদাহরণ** | PostgreSQL, MySQL, SQL Server | Snowflake, BigQuery, Redshift, ClickHouse, Databricks |

### Row বনাম column storage কেন সবকিছু বদলে দেয়

```
ROW STORE (OLTP) — একটা record-এর সবকিছু একসাথে জমা
  [id=1, name=Alice, city=Dhaka, amount=100][id=2, name=Bob, city=Delhi, amount=250]...

  "order 1 আনো"          → একটা সংলগ্ন block পড়ুন। নিখুঁত।
  "১০০ কোটির SUM(amount)" → একটা কলাম পেতে প্রতিটা row-র প্রতিটা byte পড়ুন। ভয়াবহ।

COLUMN STORE (OLAP) — একটা কলামের সবকিছু একসাথে জমা
  id:     [1, 2, 3, 4, ...]
  name:   [Alice, Bob, Carol, ...]
  city:   [Dhaka, Delhi, Dhaka, ...]
  amount: [100, 250, 80, ...]

  "১০০ কোটির SUM(amount)" → শুধু amount কলামটা পড়ুন। ৫০× কম I/O।
  "order 1 আনো"           → ২০০টা আলাদা জায়গা থেকে জোড়া লাগান। ধীর।
```

**Columnar storage অনেক ভালো compress-ও হয়**, কারণ একটা কলামে একই রকম মান থাকে: `city`-তে run-length encoding, `status`-এ dictionary encoding, timestamp-এ delta encoding। ১০–৩০× compression স্বাভাবিক — মানে কম কলাম পড়ার উপরে আরও ১০–৩০× কম I/O।

> **এই কারণেই আপনি শুধু "production database-এ report চালাতে" পারেন না।** এটা কোনো নীতির পছন্দ নয়; storage-এর বিন্যাসটাই কাজটার জন্য ভুল। আপনার OLTP database-এ একটা বিশ্লেষণধর্মী query সেই একই page scan করে যেগুলো আপনার customer-দের transaction-এর লাগে, আপনার buffer pool খালি করে দেয়, আর এমন snapshot ধরে রাখে যা vacuum আটকায় (অধ্যায় ০৯)।

### প্রতিটা কোম্পানি যে তিনটা ধাপ পার হয়

```
ধাপ ১  সরাসরি production DB-তে report
        → যতক্ষণ চলে চলে। একজন বিশ্লেষকের query checkout lock করে দেয়।

ধাপ ২  একটা read replica-তে report
        → ভালো, সস্তা, কয়েক বছর কিনে দেয়। কিন্তু: এখনো row-storage, এখনো একটা schema,
          এখনো কোনো ইতিহাস নেই, আর ভারী query replica-কে পিছিয়ে দিতে পারে।

ধাপ ৩  একটা pipeline-এ খাওয়ানো একটা আসল বিশ্লেষণধর্মী store (warehouse/lakehouse)
        → columnar, ঐতিহাসিক, বিশ্লেষণের জন্য model করা, production থেকে বিচ্ছিন্ন।
```

> **আর্কিটেক্টের নির্দেশনা: সাথে সাথে ধাপ ২-তে যান** (এতে প্রায় কিছুই খরচ হয় না)। **ধাপ ৩-এ যান যখন** বিশ্লেষকরা আটকে যান, যখন OLTP যে ইতিহাস মুছে ফেলে সেটা আপনার লাগে, অথবা যখন আপনাকে কয়েকটা সিস্টেমের data জোড়া লাগাতে হয়।

---

## ১২.২ Dimensional modelling — star schema 🟢

Kimball-এর star schema হলো বিশ্লেষণধর্মী data model করার প্রচলিত উপায়। এটা ইচ্ছাকৃতভাবে *denormalised*, আর তার একটা ভালো কারণ আছে।

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

### Fact আর dimension

| | **Fact table** | **Dimension table** |
|---|---|---|
| যা থাকে | পরিমাপ/ঘটনা — সংখ্যাগুলো | বর্ণনামূলক প্রেক্ষাপট — বিশেষণগুলো |
| আকার | বিশাল (কোটি কোটি row) | ছোট (হাজার থেকে লাখ) |
| Grain | প্রতি ঘটনা/দিন/transaction-এ একটা row | প্রতি entity-তে একটা row |
| কলাম | Foreign key + সংখ্যাসূচক measure | অনেক বর্ণনামূলক বৈশিষ্ট্য |
| পরিবর্তন | শুধু যোগ হয় | ধীরে বদলায় |

**Grain ঘোষণাই সবচেয়ে গুরুত্বপূর্ণ design সিদ্ধান্ত।** কোনো DDL লেখার আগে এটা এক বাক্যে বলুন:

> *"`fact_verification`-এর একটা row একটা সম্পন্ন verification প্রচেষ্টাকে বোঝায়।"*

বাকি সবকিছু এখান থেকেই আসে। একটা বিভ্রান্ত grain (কিছু row প্রচেষ্টা, কিছু দৈনিক সারসংক্ষেপ) স্থায়ীভাবে ভুল সংখ্যা তৈরি করে, যা কেউ debug করতে পারে না।

### Denormalise কেন? কারণ query গুলো বিশ্লেষকরা লেখেন

```sql
-- STAR SCHEMA: প্রতি dimension-এ একটা join, পড়া যায়, দ্রুত
SELECT t.region, d.month, count(*) AS verifications, avg(f.liveness_score) AS avg_score
FROM fact_verification f
JOIN dim_tenant t ON t.tenant_key = f.tenant_key
JOIN dim_date   d ON d.date_key   = f.date_key
WHERE d.year = 2026
GROUP BY 1, 2;

-- NORMALISED (3NF): একই প্রশ্নে ৮টা join লাগে, আর একজন বিশ্লেষক ভুল করেন।
```

Star schema **মানুষের বোঝা আর query engine-এর performance**-এর জন্য optimise করে, storage-এর দক্ষতার জন্য নয়। Storage সস্তা; বিশ্লেষকের সময় আর ভুল সংখ্যা নয়।

### Snowflake schema

এমন একটা star schema যেখানে dimension গুলো আরও sub-dimension-এ normalise করা (`dim_customer → dim_city → dim_country`)।

- ✅ কম পুনরাবৃত্তি, ভাগ করা শ্রেণিবিন্যাস রক্ষণাবেক্ষণ সহজ
- ❌ বেশি join, মানুষের জন্য কঠিন, সাধারণত ধীর

> **Default-এ star schema নিন।** Snowflake শুধু সেখানে যেখানে একটা শ্রেণিবিন্যাস সত্যিই অনেক dimension জুড়ে ভাগ করা আর ঘন ঘন বদলায়।

### Slowly Changing Dimension (SCD) ⭐

একজন customer ঢাকা থেকে দিল্লি চলে গেলেন। গত বছরের report-এর কী হবে?

| ধরন | আচরণ | কখন ব্যবহার করবেন |
|------|-----------|----------|
| **Type 0** | কখনো বদলায় না | অপরিবর্তনীয় বৈশিষ্ট্য (জন্মতারিখ) |
| **Type 1** | উপরে লিখে দেয় — ইতিহাস হারায় | সত্যিকারের ভুলের সংশোধন (নামের বানান ভুল) |
| **Type 2** ⭐ | **বৈধতার তারিখ সহ একটা নতুন row যোগ করে** | **বিশ্লেষণগতভাবে অর্থপূর্ণ যা কিছুর জন্য default** |
| **Type 3** | একটা "আগের মান" কলাম রাখে | আপনার শুধু এক ধাপ ইতিহাস লাগে |
| **Type 4/6** | Hybrid — একটা বর্তমান table আর একটা ইতিহাসের table | উন্নত ক্ষেত্র |

```sql
-- SCD Type 2: ইতিহাস সংরক্ষিত
customer_key | customer_id | name    | city   | valid_from | valid_to   | is_current
-------------|-------------|---------|--------|------------|------------|------------
        1001 | cus_42      | Delower | Dhaka  | 2024-01-01 | 2026-06-30 | false
        1002 | cus_42      | Delower | Delhi  | 2026-07-01 | 9999-12-31 | true
```

এখন ২০২৫-এর একটা report সঠিকভাবে ওই customer-কে ঢাকায় দেখায়, আর আজকের dashboard দেখায় দিল্লি। **এটাই একটা warehouse-এর পার্থক্য যেটা অতীত সম্পর্কে সত্য বলে আর একটার যেটা নীরবে ইতিহাস নতুন করে লেখে।**

Surrogate key-টা (`customer_key`) খেয়াল করুন — fact গুলো *সংস্করণের* দিকে তাকায়, business ID-র দিকে নয়। এই কারণেই warehouse natural key-র বদলে surrogate key ব্যবহার করে।

---

## ১২.৩ ETL বনাম ELT 🟢

### ETL — Extract, Transform, Load (ক্লাসিক)

```
Source DB ──extract──► [ রূপান্তরের engine ] ──load──► Warehouse
                        (Informatica, SSIS, Talend,
                         বা আপনার Python script)
```

Load করার *আগে* রূপান্তর করুন। শুধু পরিষ্কার, model করা data warehouse-এ নামে।

- ✅ Warehouse পরিষ্কার থাকে; কম storage; target ব্যয়বহুল বা অনমনীয় হলে ভালো
- ❌ রূপান্তরের logic warehouse-এর বাইরে থাকে (test আর version করা কঠিন); আবার process করা মানে উৎস থেকে আবার extract করা; রূপান্তরের engine একটা বাধা আর scale করার আলাদা একটা জিনিস

### ELT — Extract, Load, Transform ⭐ (আধুনিক default)

```
Source DB ──extract──► Warehouse (কাঁচা) ──warehouse-এর ভেতরেই transform──► model করা table
                                           (dbt, SQL, Spark)
```

আগে কাঁচা data load করুন; warehouse-এর নিজের compute ব্যবহার করে ভেতরেই রূপান্তর করুন।

- ✅ **কাঁচা data সংরক্ষিত থাকে** — production না ছুঁয়েই আপনি আবার process করতে পারেন
- ✅ রূপান্তর হলো **version control-এ থাকা SQL**, testable, review-যোগ্য (dbt এটাই জনপ্রিয় করেছে)
- ✅ Warehouse-এর বিশাল সমান্তরাল compute কাজটা করে
- ✅ আপনার আগেই নামানো ইতিহাস থেকে নতুন প্রশ্নের উত্তর দেওয়া যায়
- ❌ বেশি storage (সস্তা); warehouse-এ কাঁচা data-র governance আর access control লাগে

> **ELT কেন জিতল:** ক্লাউড storage প্রায় বিনামূল্যে হয়ে গেল আর warehouse-এর compute স্থিতিস্থাপক হলো। ETL-এর পুরনো কারণটা (ব্যয়বহুল warehouse-এর ক্ষমতা নষ্ট কোরো না) উবে গেল। আর **কাঁচা থেকে আবার process করার** ক্ষমতা বিশাল মূল্যবান, যেদিন তিন মাস পর একটা রূপান্তরের bug আবিষ্কার হয়।

### আধুনিক ELT stack

```
EXTRACT ও LOAD:   Fivetran / Airbyte / Debezium / custom
STORE:            Snowflake / BigQuery / Databricks / S3+Iceberg
TRANSFORM:        dbt (SQL + Jinja, test, docs, lineage)
ORCHESTRATE:      Airflow / Dagster / Prefect
SERVE:            Looker / Metabase / Power BI / Superset
```

```sql
-- একটা dbt model: শুধুই SQL, কিন্তু version-controlled, tested আর নির্ভরতা-সচেতন
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
  WHERE s.created_at > (SELECT max(created_at) FROM {{ this }})   -- শুধু নতুন row
{% endif %}
```

```yaml
# আর test গুলো এর পাশেই থাকে — data-র মান কোড হিসেবে
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

> **গত দশকে data engineering-এ এটাই একক সবচেয়ে বড় উন্নতি:** রূপান্তর হিসেবে review করা, test করা, version-controlled কোড, স্বয়ংক্রিয় lineage সহ — ২০১৯ সালে কেউ একজন বসানো একটা scheduler-এ অনথিভুক্ত SQL-এর বদলে।

---

## ১২.৪ Change Data Capture (CDC) 🟢

**Batch extraction-এর সমস্যা:**

```sql
-- সরল incremental extract
SELECT * FROM orders WHERE updated_at > :last_run;
```

এটা যা বাদ দেয়:
- **Delete** (row-টা নেই — আপনি কখনো দেখেনই না, তাই warehouse চিরকাল একটা ভূত ধরে রাখে)
- **মধ্যবর্তী state** (দুই run-এর মাঝে একটা row ৩ বার বদলেছে; আপনি শুধু শেষটা দেখেন)
- এমন row যেখানে application `updated_at` বসাতে ভুলে গেছে (এটা অনবরত হয়)
- এটা production database-এ load ফেলে
- সীমানায় clock/transaction-ক্রমের প্রান্তিক ক্ষেত্র

**CDC বরং database-এর transaction log পড়ে** — replication-এ ব্যবহৃত সেই একই WAL (অধ্যায় ০৯)।

```
PostgreSQL WAL ──► Debezium ──► Kafka ──► Warehouse / Lake / Search / Cache
                   (log-কে row-স্তরের পরিবর্তন-event-এ decode করে)
```

```json
{
  "op": "u",                       // c=create, u=update, d=delete, r=snapshot read
  "before": { "id": 42, "status": "pending",  "score": null },
  "after":  { "id": 42, "status": "passed",   "score": 0.94 },
  "source": { "ts_ms": 1757673600123, "lsn": 24857392, "table": "sessions" }
}
```

**CDC আপনাকে যা দেয়:**
- **প্রতিটা পরিবর্তন, delete আর মধ্যবর্তী state সহ**
- ঘণ্টায়-ঘণ্টায় batch-এর বদলে **প্রায়-real-time** (এক সেকেন্ডের কম)
- Production database-এ **প্রায় কোনো load নেই** (এটা log পড়ে, table নয়)
- **সঠিক ক্রম**, transaction log দিয়ে নিশ্চিত
- একটা pipeline অনেক consumer-কে খাওয়ায়: warehouse, search index, cache invalidation, event stream

**এর খরচ:** চালানো আর monitor করার জন্য Kafka + Connect + Debezium; replication slot ব্যবস্থাপনা (অধ্যায় ০৯ — একটা পরিত্যক্ত slot আপনার disk ভরে দেয়); উৎসে schema পরিবর্তন নিচের দিকে ছড়ায়; বড় table-এর প্রাথমিক snapshot-এ যত্ন লাগে।

> **CDC-ই scale-এ Outbox relay করারও উপায়** (অধ্যায় ০৬), আর পাঁচটা তাৎক্ষণিক pipeline-এর বদলে একটা প্রামাণিক pipeline থেকে derived store (Elasticsearch, Redis, warehouse) মিলিয়ে রাখারও। ওই একত্রীকরণটাই আসল architecture-এর জয়।

---

## ১২.৫ Batch বনাম Stream processing 🟢

| | **Batch** | **Stream** |
|---|---|---|
| যা process করে | একটা সীমাবদ্ধ data-সেট | একটা সীমাহীন, অবিরাম প্রবাহ |
| Trigger | সময়সূচি (ঘণ্টায়, রাতে) | প্রতিটা event, বা একটা ছোট window |
| Latency | মিনিট থেকে ঘণ্টা | মিলিসেকেন্ড থেকে সেকেন্ড |
| সঠিকতা | সহজ — আপনার কাছে সব data আছে | কঠিন — data দেরিতে আর ক্রমের বাইরে আসে |
| আবার process | শুধু আবার চালান | Replay লাগে (অধ্যায় ০৭) |
| খরচ | দক্ষ — বড় মেশিন, অল্প সময়ের জন্য | সবসময়-চালু infrastructure |
| জটিলতা | কম | বেশি |
| টুল | Spark, dbt, SQL, Airflow | Flink, Kafka Streams, Spark Structured Streaming |

### কখন আপনার সত্যিই streaming লাগে

সৎ থাকুন, কারণ streaming-এ মোটামুটি ৩× engineering-এর পরিশ্রম লাগে:

✅ **আসল streaming যুক্তিসঙ্গত:**
- Transaction চলাকালীনই fraud শনাক্তকরণ
- Real-time ব্যক্তিগতকরণ আর recommendation
- Operational monitoring আর alerting
- এমন live dashboard যেখানে সেকেন্ড বাণিজ্যিকভাবে গুরুত্বপূর্ণ
- গতিশীল দাম, channel জুড়ে inventory মিলানো

❌ **Batch-ই ঠিক আছে (আর বেশিরভাগ "real-time" চাহিদা আসলে এটাই):**
- দৈনিক/সাপ্তাহিক business report
- মাসিক billing
- Model training
- বেশিরভাগ executive dashboard ("real-time" সাধারণত মানে "৩ দিনের পুরনো নয়")

> **জিজ্ঞেস করুন: "এই data ৪ ঘণ্টার বদলে ৫ মিনিটের পুরনো হলে কোন সিদ্ধান্তটা আলাদা হবে?"** কেউ যদি একটা নির্দিষ্ট কাজ দিয়ে উত্তর দিতে না পারেন, তাহলে আপনার batch লাগবে। এই একটামাত্র প্রশ্ন বিপুল টাকা বাঁচায়।

### Streaming-এর কঠিন অংশ: সময়

```
EVENT TIME      যখন এটা আসলে device-এ ঘটেছে         ← এটাই আপনার দরকার
PROCESSING TIME যখন আপনার সিস্টেম এটা পেয়েছে         ← এটাই ব্যবহার করা সহজ
```

একটা mobile app লিফটে offline হয়ে গেল আর ১০ মিনিট পরে ২০টা event upload করল। এগুলো কোন window-তে পড়ে?

```
Window (সবগুলোই EVENT time-এ কাজ করে):
  TUMBLING   [০-৫মিনিট][৫-১০মিনিট][১০-১৫মিনিট]   নির্দিষ্ট, অ-উপরিপাতিত
  HOPPING    [০-৫][২-৭][৪-৯]                     নির্দিষ্ট আকার, উপরিপাতিত (sliding)
  SESSION    [কাজ]...ফাঁক...[কাজ]                 নিষ্ক্রিয়তার ফাঁক দিয়ে দলবদ্ধ
```

**Watermark** সিস্টেমকে বলে "আমি বিশ্বাস করি সময় T পর্যন্ত সব event দেখেছি; ওই window বন্ধ করা নিরাপদ।" Watermark-এর পরে আসা data হলো **দেরিতে আসা data**, আর আপনাকে ঠিক করতে হবে: ফেলে দেবেন, একটা side output-এ পাঠাবেন, নাকি একটা সংশোধিত ফলাফল আবার দেবেন। প্রতিটা গুরুতর streaming সিস্টেম আপনাকে এর উত্তর দিতে বাধ্য করে।

### Lambda বনাম Kappa architecture ⚪🟡

**Lambda** — একটা batch স্তর (নির্ভুল, ধীর) আর একটা speed স্তর (দ্রুত, আনুমানিক) দুটোই চালান, আর query-র সময় মিলিয়ে দিন।
- ✅ নির্ভুল *আর* দ্রুত
- ❌ **আপনি একই business logic দুইবার, দুটো ভাষায় রক্ষণাবেক্ষণ করেন।** সেগুলো ভেসে যায়। এই কারণেই Lambda অপ্রিয় হয়েছে।

**Kappa** — একটাই streaming pipeline। ইতিহাস আবার হিসাব করতে একই কোডের মধ্য দিয়ে log replay করুন।
- ✅ একটা codebase, একটা logic
- ❌ Log-এ লম্বা retention লাগে আর এমন একটা streaming engine লাগে যা গতিতে backfill সামলাতে পারে

> **আধুনিক চর্চা বেশিরভাগই "lakehouse সহ Kappa-ধাঁচে" মিলিত হয়**: একটা pipeline একটা open table format-এ (Iceberg/Delta) লেখে, যেটা streaming read আর batch query দুটোই সামলায়। একটা কপি, একটা logic-পথ।

---

## ১২.৬ Data Lake, Warehouse, Lakehouse 🟡

### Data Warehouse

কাঠামোবদ্ধ, model করা, schema-on-write। Load করার আগেই আপনি schema ঠিক করেন।

- ✅ দ্রুত query, governed, বিশ্বস্ত, দারুণ BI টুল
- ❌ অনমনীয়; কাঁচা/আধা-কাঠামোবদ্ধ data-র জন্য ব্যয়বহুল; প্রশ্নগুলো জানার আগেই model করতে হয়

উদাহরণ: Snowflake, BigQuery, Redshift, Synapse।

### Data Lake

সস্তা object storage-এ (S3/ADLS/MinIO) কাঁচা ফাইল। Schema-on-read।

- ✅ সস্তা, যা খুশি জমা রাখে (JSON, ছবি, ভিডিও, log, Parquet), পরের জন্য সব রাখে
- ❌ শৃঙ্খলা ছাড়া **এটা একটা data swamp হয়ে যায়**: কোনো schema বলবৎ নেই, কোনো ACID নেই, ভেতরে কী আছে কোনো ধারণা নেই, পুনরাবৃত্ত ফাইল, একটা row হালনাগাদ বা মুছে ফেলার কোনো উপায় নেই

> শিল্প এটা ২০১৫–২০১৯ নাগাদ কঠিনভাবে শিখেছে। "সব S3-তে ঢেলে দাও আর পরে দেখা যাবে" এমন petabyte তৈরি করেছিল যা কেউ ব্যবহার করতে পারেনি।

### Lakehouse ⭐ (বর্তমান ঐকমত্য)

সস্তা object storage + একটা **open table format** যা ফাইলের উপরে warehouse-এর feature যোগ করে।

```
        ┌──────────────────────────────────────────────┐
        │  QUERY ENGINE (যে কোনোটা, একই data)           │
        │  Spark · Trino · Snowflake · DuckDB · Flink  │
        └───────────────────┬──────────────────────────┘
                            │
        ┌───────────────────▼──────────────────────────┐
        │  TABLE FORMAT: Apache Iceberg / Delta / Hudi │
        │  • ACID transaction     • schema evolution   │
        │  • time travel          • partition evolution│
        │  • row-স্তরের UPDATE/DELETE (GDPR!)           │
        │  • snapshot isolation   • compaction         │
        └───────────────────┬──────────────────────────┘
                            │
        ┌───────────────────▼──────────────────────────┐
        │  FILE FORMAT: Parquet (columnar, compressed) │
        │  OBJECT STORAGE: S3 / ADLS / GCS / MinIO     │
        └──────────────────────────────────────────────┘
```

**Table format যা যোগ করে যা কাঁচা Parquet পারে না:**

| Feature | কেন গুরুত্বপূর্ণ |
|---------|---------------|
| **ACID commit** | একসাথে লেখা দুটো job table নষ্ট করে না; পাঠক কখনো অর্ধেক write দেখে না |
| **Row-স্তরের DELETE/UPDATE** | একটা data lake-এ **GDPR-এর "এই মানুষটাকে মুছে ফেলো"** — আগে প্রায় অসম্ভব ছিল |
| **Time travel** | `SELECT ... FOR VERSION AS OF 12` — গত মঙ্গলবারের report হুবহু আবার বানান |
| **Schema evolution** | Petabyte নতুন করে না লিখেই কলাম যোগ/নাম বদল/পুনর্বিন্যাস |
| **লুকানো partitioning** (Iceberg) | Pruning পেতে query লেখকদের partition-এর নকশা জানতে হয় না |
| **Compaction** | Lake-এর performance মেরে ফেলা ছোট-ফাইলের সমস্যা মিলিয়ে দেয় |

```sql
-- Iceberg সস্তা storage-এ warehouse-এর semantics দেয়
DELETE FROM verifications WHERE customer_id = 'cus_42';     -- GDPR-এর মুছে ফেলা
SELECT * FROM verifications FOR TIMESTAMP AS OF '2026-09-01';  -- time travel
ALTER TABLE verifications ADD COLUMN device_model STRING;   -- তাৎক্ষণিক, কোনো পুনর্লিখন নয়
```

> **Apache Iceberg মোটামুটি নিরপেক্ষ standard হয়ে গেছে** — Snowflake, BigQuery, Databricks, Trino, Spark আর Flink সবাই এটা পড়ে। বাস্তবে এর মানে **আপনার data আর একটা ভেন্ডরের warehouse-এর ভেতরে বন্দি নয়**, যেটা একটা সত্যিকারের architecture-এর সুবিধা আর যে কোনো ভেন্ডর আলোচনায় তোলার মতো।

### Medallion architecture 🟡

একটা lakehouse সাজানোর প্রচলিত উপায়, তিনটা স্তরে:

```
┌──────────────────────────────────────────────────────────────┐
│ BRONZE  — কাঁচা, যেমন এসেছে, immutable, শুধু যোগ হয়            │
│           • উৎসের হুবহু কপি, সাথে ingestion-এর metadata       │
│           • কখনো সম্পাদনা নয়। এটাই আপনার আবার process করার ক্ষমতা।│
├──────────────────────────────────────────────────────────────┤
│ SILVER  — পরিষ্কার, সঙ্গতিপূর্ণ, deduplicate করা, type করা      │
│           • যাচাই করা, জোড়া লাগানো, মানসম্মত, PII সামলানো      │
│           • প্রতি business entity/ঘটনায় একটা row, বিশ্বাসযোগ্য   │
├──────────────────────────────────────────────────────────────┤
│ GOLD    — business-স্তরের aggregate আর mart                  │
│           • star schema, KPI, ML-এর feature table            │
│           • dashboard আর বিশ্লেষকরা আসলে যা query করেন         │
└──────────────────────────────────────────────────────────────┘
```

**স্তরগুলো কেন গুরুত্বপূর্ণ:**
- **Bronze আপনার বিমা।** যে কোনো রূপান্তরের bug থেকে ফেরা যায়, কারণ কাঁচা সত্যটা এখনো আছে।
- **Silver আপনার contract।** নিচের টিমগুলো পরিষ্কার data-র উপর বানায়, উৎস-সিস্টেমের খামখেয়ালির উপর নয়।
- **Gold হলো product।** এটা প্রশ্নের জন্য গড়া, storage-এর জন্য নয়।

নিয়ম: bronze কখনো বদলানো হয় না; প্রতিটা স্তর শুধু উপরের স্তর থেকে derived; প্রতিটা সীমানায় মানের test চলে।

---

## ১২.৭ Data pipeline আর orchestration 🟡

### DAG মডেল

```python
# Airflow — সবচেয়ে প্রচলিত orchestrator
with DAG("daily_verification_marts", schedule="0 2 * * *",
         catchup=False, max_active_runs=1) as dag:

    extract = PostgresToS3Operator(task_id="extract_sessions", ...)
    load    = S3ToSnowflakeOperator(task_id="load_bronze", ...)
    dbt_run = BashOperator(task_id="dbt_transform", bash_command="dbt build --target prod")
    quality = GreatExpectationsOperator(task_id="validate_gold", ...)
    notify  = SlackOperator(task_id="notify", ...)

    extract >> load >> dbt_run >> quality >> notify
```

| টুল | চরিত্র |
|------|-----------|
| **Airflow** | প্রতিষ্ঠিতটা। বিশাল ecosystem। Task-কেন্দ্রিক; test করা অসুবিধাজনক। |
| **Dagster** | **Asset-কেন্দ্রিক** — আপনি data asset ঘোষণা করেন, এটা task বের করে নেয়। ভালো testing, ভালো lineage। নতুন কিছু বানানোর জন্য আধুনিক পছন্দ। |
| **Prefect** | Python-নেটিভ, গতিশীল workflow, হালকা অনুভূতি |
| **dbt** | Orchestrator নয় — এটা transform স্তরের ভেতরের DAG সামলায়। সাধারণত একটা orchestrator *দিয়ে* চালানো হয়। |
| **Temporal** | *Application* প্রক্রিয়ার (saga) জন্য টেকসই workflow, মূলত data pipeline নয় |

### Pipeline design-এর নিয়ম 🟢

**১. Idempotent** — একটা task আবার চালালে একই ফলাফল হতে হবে, duplicate নয়।

```sql
-- ❌ Idempotent নয়
INSERT INTO fact_verification SELECT * FROM staging WHERE date = '2026-09-12';

-- ✅ Idempotent: partition-টা মুছুন, তারপর insert করুন (বা MERGE)
DELETE FROM fact_verification WHERE created_date = '2026-09-12';
INSERT INTO fact_verification SELECT * FROM staging WHERE date = '2026-09-12';
```

**২. সময় দিয়ে partition করা** — একবারে একদিন/একঘণ্টা process করুন, যাতে বাকিটা না ছুঁয়েই একটা একক আবার process করতে পারেন।

**৩. Backfill করা যায় এমন** — প্রতিটা task একটা তারিখের parameter নেয়। গত মার্চ আবার চালানো একটা মাত্র command হতে হবে।

**৪. Observable** — প্রতিটা run-এর জন্য কত row ঢুকল, কত বেরোল, কতক্ষণ লাগল, আর ব্যর্থতা লিপিবদ্ধ করুন। শূন্য row তৈরি করে "সফল" হওয়া একটা pipeline একটা নীরব বিপর্যয়।

**৫. জোরে fail করুন, কখনো আংশিকভাবে নয়** — একটা staging জায়গায় লিখুন, যাচাই করুন, তারপর atomically বদলে দিন। কখনো একটা অর্ধেক-লেখা table রেখে যাবেন না যেটা dashboard খুশিমনে query করবে।

**৬. সীমাবদ্ধ** — প্রতি task-এ memory আর row সীমাবদ্ধ করুন; একটা ব্যস্ত দিনে রাত ৩টায় OOM হওয়া task একটা design-এর ত্রুটি, দুর্ভাগ্য নয়।

### Data-র মান — আপনার data-কে কোডের মতোই test করুন

```python
# Great Expectations / dbt test / Soda — যে চারটা শ্রেণি গুরুত্বপূর্ণ
expect_column_values_to_not_be_null("verification_id")
expect_column_values_to_be_unique("verification_id")
expect_column_values_to_be_between("liveness_score", 0, 1)
expect_table_row_count_to_be_between(min_value=1000, max_value=100000)   # volume-এর অস্বাভাবিকতা
expect_column_values_to_match_regex("tenant_id", r"^t_[a-z0-9]{8}$")
```

**প্রতিটা স্তরের সীমানায় যাচাই করার চারটা মাত্রা:**

| মাত্রা | প্রশ্ন | Test |
|-----------|----------|------|
| **সম্পূর্ণতা** | কিছু কি বাদ পড়েছে? | উৎসের সাথে row-সংখ্যা, null-এর হার |
| **নির্ভুলতা** | মানগুলো কি ঠিক? | পরিসর, referential integrity, উৎসের যোগফলের সাথে মিলানো |
| **সময়ানুবর্তিতা** | এটা কি সময়মতো এসেছে? | Freshness যাচাই: `max(updated_at) > now() - 2h` |
| **সামঞ্জস্য** | সিস্টেমগুলো কি একমত? | Warehouse-এর আয় বনাম billing সিস্টেমের আয় |

> **Reconciliation test-ই সেটা যা ক্যারিয়ার বাঁচায়:** প্রতিদিন warehouse-এর একটা প্রধান সংখ্যা operational সিস্টেমের সাথে তুলনা করুন। যখন সেগুলো আলাদা হয়, আপনি CFO-র আগেই জেনে যান।

### Data lineage 🟡

*"Executive dashboard-এর এই সংখ্যাটা — এটা কোথা থেকে আসে, আর আমি এই কলাম বদলালে কী ভাঙে?"*

Lineage দুটোরই উত্তর দেয়। আধুনিক টুল (dbt docs, Dagster, OpenLineage, DataHub, Atlan) SQL parse করে স্বয়ংক্রিয়ভাবে এটা বের করে।

**আর্কিটেক্টরা কেন এটা নিয়ে ভাবেন:**
- **প্রভাব বিশ্লেষণ** — "আমরা এই উৎস কলামের নাম বদলালে কী ভাঙে?" (নিচের ২৩টা model, ৪টা dashboard)
- **Debugging** — একটা ভুল সংখ্যা কয়েক দিনের বদলে কয়েক মিনিটে তার উৎস পর্যন্ত অনুসরণ করা
- **Compliance** — "প্রমাণ করুন এই PII field কোথায় কোথায় যায় আর সব জায়গায় কোথায় জমা থাকে"
- **Deprecation** — কিছুই পড়ে না প্রমাণ করতে পারলে আপনি নিরাপদে একটা table মুছতে পারেন

---

## ১২.৮ Data Mesh আর Data Fabric ⚪

দুটোই টেকনোলজির চেয়ে বেশি **সাংগঠনিক** ধারণা। পরিভাষাটা জানুন; প্রচার নিয়ে সন্দিহান থাকুন।

### Data Mesh

কেন্দ্রীয় data টিম একটা বাধা হয়ে ওঠার প্রতিক্রিয়া (প্রতিটা অনুরোধ একটা অতিরিক্ত চাপে থাকা টিমের পেছনে সারিতে)।

চারটা নীতি:
১. **Domain-এর মালিকানা** — যে টিম data তৈরি করে, তারাই তার বিশ্লেষণধর্মী data-রও মালিক
২. **Data একটা product হিসেবে** — একজন মালিক, SLA, documentation, মানের নিশ্চয়তা আর consumer সহ
৩. **Self-serve platform** — একটা কেন্দ্রীয় platform টিম টুল দেয়, pipeline নয়
৪. **Federated governance** — বৈশ্বিক standard (নামকরণ, PII সামলানো, আন্তঃক্রিয়াশীলতা), স্থানীয় স্বায়ত্তশাসন

> এটা **data-তে প্রয়োগ করা Conway's Law** (অধ্যায় ০০), আর **analytics-এ প্রয়োগ করা bounded context** (অধ্যায় ০৩)। ধারণাটা সঠিক। ব্যর্থতার রূপটা হলো ৩০ জনের সংগঠনে এটা করা, যেখানে সমন্বয়ের খরচ যুক্তিসঙ্গত করার মতো যথেষ্ট domain টিমই আপনার নেই — আর আপনি পাঁচটা অসঙ্গত মিনি-warehouse পান আর কোনো কেন্দ্রীয় সত্য থাকে না।

**আঙুলের নিয়ম:** data mesh তখনই অর্থবহ হতে শুরু করে যখন কেন্দ্রীয় data টিম একটা সত্যিকারের, মাপা বাধা হয়ে গেছে আর আপনার অনেকগুলো স্বায়ত্তশাসিত product টিম আছে। তার নিচে ভালো টুল সহ একটা কেন্দ্রীয় টিমই জেতে।

### Data Fabric

আরও ভেন্ডর-চালিত একটা ধারণা: বিতরণ করা data-র উপর একটা একীভূত metadata আর integration স্তর, ভারী automation আর সক্রিয় metadata সহ। বাস্তবে এর মানে সাধারণত "আমাদের platform কিনুন"। পরিচিতিই যথেষ্ট।

---

## ১২.৯ একটা reference data architecture

একটা মাঝারি আকারের SaaS-এর জন্য সব একসাথে:

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
│  │  কাঁচা  │  │ পরিষ্কার│  │ mart   │              │
│  └────────┘  └────────┘  └────────┘              │
│         dbt / Spark দিয়ে রূপান্তরিত                │
│         Dagster / Airflow দিয়ে orchestrate করা    │
│         Great Expectations / dbt test দিয়ে যাচাই   │
└────────────────────┬─────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────┐
│  SERVING                                         │
│  Trino / DuckDB (ad-hoc)  ·  Metabase (BI)       │
│  ClickHouse (দ্রুত dashboard)                     │
│  Feature store (ML)  ·  Reverse ETL (CRM-এ ফেরত) │
└──────────────────────────────────────────────────┘
```

### আর যে সংস্করণটা দিয়ে আপনার আসলে শুরু করা উচিত

```
PostgreSQL (production)
    │ রাতের logical replication বা একটা নির্ধারিত dump
    ▼
PostgreSQL read replica / আলাদা analytics database
    │ dbt model (version-controlled SQL)
    ▼
Metabase / Superset dashboard
```

> **ওই stack-এ প্রায় কিছুই খরচ হয় না, এক সপ্তাহ লাগে, আর মোটামুটি ২ কোটি ডলার আয় পর্যন্ত একটা কোম্পানিকে সেবা দেয়।** উপরের diagram-টা শুধু তখনই বানান যখন একটা নির্দিষ্ট সীমায় পৌঁছান — data-র পরিমাণ, উৎস-সিস্টেমের সংখ্যা, বা latency। Data architecture এমন একটা এলাকা যেখানে over-engineering সবচেয়ে ব্যয়বহুল আর সবচেয়ে সাধারণ, কারণ টুল গুলো উত্তেজনাপূর্ণ আর business-এর প্রভাব পরোক্ষ।

---

## ১২.১০ Governance, PII আর retention 🟢

বিশ্লেষণধর্মী সিস্টেমেই privacy লঙ্ঘন নীরবে জমতে থাকে, কারণ data কপি হয় আর কেউ track করে না।

**ন্যূনতম শৃঙ্খলা:**

১. **প্রতিটা কলাম শ্রেণিবদ্ধ করুন** — public / internal / confidential / PII / বিশেষ-শ্রেণি
২. **কাঁচা PII কখনো lake-এ নামাবেন না**, যদি না একদম বাধ্য হন। বরং:
   - **Tokenisation** — একটা ফেরানো-যায় token দিয়ে বদলান; mapping-টা একটা vault-এ থাকে
   - **Hashing** — যেসব join key কখনো ফেরাতে হবে না তার জন্য (salt দিন)
   - **Masking** — `d****r@example.com`
   - **Aggregation** — বিশ্লেষকদের কি ব্যক্তিটা লাগে, নাকি সংখ্যাটা?
৩. **কলাম-স্তরের access control** — বিশ্লেষকরা `country` দেখেন, `passport_number` নয়
৪. **প্রতি স্তরে retention policy** — bronze ৯০ দিন, silver ২ বছর, gold ৭ বছর। স্বয়ংক্রিয় মুছে ফেলা, ক্যালেন্ডারের স্মরণিকা নয়।
৫. **মুছে ফেলার অধিকার** — এই কারণেই Iceberg/Delta-র row-স্তরের delete গুরুত্বপূর্ণ। দরকার হওয়ার আগেই পরিকল্পনা করুন। Immutable log-এর জন্য **crypto-shredding** (অধ্যায় ০২): প্রতি ব্যক্তিতে encrypt করুন, key মুছে ফেলুন।
৬. **Access audit করুন** — কে কী query করেছে, বিশেষত PII কলাম
৭. **Data residency** — EU-র data যদি EU-তে থাকতে হয়, তাহলে আপনার pipeline আর warehouse-এর region একটা architecture-এর constraint, deployment-এর খুঁটিনাটি নয়

> **আর্কিটেক্টের আগেভাগে করা প্রশ্ন: "একজন customer কাল মুছে ফেলার দাবি করলে, তাঁর data যেখানে যেখানে আছে তার তালিকা দিন আর প্রতিটা থেকে কীভাবে সরাব বলুন।"** কেউ যদি ১০ মিনিটে উত্তর দিতে না পারেন, তাহলে সেটাই আপনার সর্বোচ্চ-অগ্রাধিকারের data-architecture আবিষ্কার।

---

## ১২.১১ সাধারণ ভুল

১. **Production OLTP database-এ analytics চালানো** — lock, buffer-pool খালি হওয়া, আটকে যাওয়া vacuum
২. একটা fact table-এ **কোনো grain ঘোষণা নেই** — স্থায়ীভাবে দ্ব্যর্থবোধক সংখ্যা
৩. **সব জায়গায় Type 1 dimension** — ইতিহাস নীরবে নতুন করে লেখা; গত বছরের report বদলে যায়
৪. **কোনো table format বা catalogue ছাড়া একটা data lake বানানো** — এক বছরের মধ্যে একটা data swamp
৫. **`updated_at`-এ batch extraction** — delete আর মধ্যবর্তী state চিরতরে হারায়
৬. **Batch-এ চলত সেখানে streaming** — যে data কেউ সোমবারের আগে পড়েই না তার জন্য ৩× খরচ আর জটিলতা
৭. **Non-idempotent pipeline** — একটা retry গতকালের আয় দ্বিগুণ করে দেয়
৮. **কোনো data quality test নেই** — একটা ভাঙা pipeline নীরবে শূন্য load করে আর dashboard একটা দারুণ কোয়ার্টার দেখায়
৯. **কোনো lineage নেই** — একটা ভুল সংখ্যা খুঁজতে তিন দিন লাগে
১০. **PII অযাচিতভাবে lake-এ কপি করা** — আবিষ্কারের অপেক্ষায় একটা compliance incident
১১. **উৎস-সিস্টেমের সাথে কোনো reconciliation নেই** — warehouse ভেসে যায় আর কেউ খেয়াল করে না
১২. **Scheduler-এর UI-তে অননুসৃত SQL হিসেবে রূপান্তর** — review-অযোগ্য, test-অযোগ্য, উদ্ধার-অযোগ্য
১৩. **প্রথম দিনেই over-engineering** — ৪ GB data-র জন্য Kafka + Spark + Iceberg + Airflow

---

## ১২.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] বিশ্লেষণধর্মী কাজ OLTP থেকে বিচ্ছিন্ন (অন্তত একটা read replica)
- [ ] কোনো DDL-এর আগেই fact table-এর grain এক বাক্যে ঘোষিত
- [ ] প্রতি dimension-এ SCD-র কৌশল বাছা; যেখানে ইতিহাস গুরুত্বপূর্ণ সেখানে Type 2
- [ ] কাঁচা data সংরক্ষিত রেখে ELT (bronze), যাতে আবার process করা কখনো production না ছোঁয়
- [ ] রূপান্তর হলো version-controlled, tested, review করা কোড (dbt বা সমতুল্য)
- [ ] প্রতিটা pipeline task idempotent, সময়-বিভাজিত আর backfill-যোগ্য
- [ ] প্রতিটা স্তরের সীমানায় data quality test: সম্পূর্ণতা, নির্ভুলতা, সময়ানুবর্তিতা, সামঞ্জস্য
- [ ] একটা operational সত্যের-উৎস সংখ্যার বিপরীতে দৈনিক reconciliation
- [ ] প্রতিটা gold table-এ freshness monitoring আর alerting
- [ ] Lineage উপলব্ধ আর স্বয়ংক্রিয়ভাবে তৈরি
- [ ] PII শ্রেণিবদ্ধ; নামানোর আগে ন্যূনতম, tokenise বা mask করা
- [ ] প্রতি স্তরে retention policy, স্বয়ংক্রিয়
- [ ] মুছে-ফেলার-অধিকারের প্রক্রিয়া লেখা আর পরীক্ষিত
- [ ] Data residency-র constraint region-এর পছন্দে প্রতিফলিত
- [ ] Streaming এমন একটা নির্দিষ্ট সিদ্ধান্ত দিয়ে যুক্তিসঙ্গত যেটা কম latency-তে বদলায় — নয়তো batch বাছা
- [ ] প্রয়োজন মেটানো সবচেয়ে সহজ stack, পরের ধাপের জন্য নাম করা trigger সহ

---

## ১২.১৩ নিজেকে যাচাই

১. আপনি কেন শুধু "production-এ report চালাতে" পারেন না? Storage-বিন্যাসের কারণটা দিন।
২. Columnar storage ব্যাখ্যা করুন আর কেন এটা ভালো compress হয়।
৩. একটা fact table-এর grain কী, আর এটা আগে ঘোষণা করা কেন এত গুরুত্বপূর্ণ?
৪. SCD Type 2 কী আর এটা ছাড়া কী ভাঙে? একটা বাস্তব report-এর উদাহরণ দিন।
৫. ETL বনাম ELT — ELT কেন জিতল? কাঁচা data সংরক্ষণ আপনাকে কী কিনে দেয়?
৬. Batch `updated_at` extraction যা বাদ দেয় আর CDC যা ধরে — এমন চারটা জিনিস দিন।
৭. আপনার streaming না batch লাগবে সেটা ঠিক করে দেয় এমন একটা প্রশ্ন বলুন।
৮. Event time বনাম processing time ব্যাখ্যা করুন, আর একটা watermark কীসের জন্য।
৯. S3-তে সাধারণ Parquet-এর উপর একটা open table format (Iceberg/Delta) কী যোগ করে? পাঁচটা জিনিসের নাম বলুন।
১০. Medallion architecture বর্ণনা করুন। Bronze কেন কখনো বদলানো যাবে না?
১১. একটা ভালোভাবে design করা pipeline task-এর ছয়টা নিয়ম তালিকাভুক্ত করুন।
১২. Data quality-র চারটা মাত্রা কী কী, আর reconciliation test কী?
১৩. Data mesh কী, আর এটা কখন উপযুক্ত হয়?
১৪. একজন customer মুছে ফেলার দাবি করলেন। একটা lakehouse-এ তাঁর data যেখানে যেখানে আছে সব ঘুরে দেখান, আর আপনি কীভাবে সেটা মুছবেন।

---

## ১২.১৪ মূল কথাগুলো

- **OLTP আর OLAP-এর storage-চাহিদা বিপরীত।** এগুলো আলাদা করুন — একটা read replica সস্তা প্রথম ধাপ।
- DDL লেখার আগে প্রতিটা fact table-এর **grain ঘোষণা করুন**
- বিশ্লেষণগতভাবে অর্থপূর্ণ যা কিছুর জন্য **SCD Type 2 হলো default** — নইলে আপনি ইতিহাস নতুন করে লেখেন
- **কাঁচা data সংরক্ষিত রেখে ELT** ETL-কে হারায়, কারণ আবার process করাই সেই feature যেটা আপনার সবচেয়ে বেশি লাগবে
- **রূপান্তর version control-এ থাকে, test সহ** — dbt-ধাঁচে। বেশিরভাগ টিমের করা সবচেয়ে বড় একক উন্নতি এটাই।
- **CDC batch extraction-কে হারায়**: এটা delete, মধ্যবর্তী state আর ক্রম ধরে, উৎসে প্রায় কোনো load ছাড়াই
- **Streaming-এ ~৩× পরিশ্রম লাগে।** এমন একটা সিদ্ধান্ত দিয়ে যুক্তি দিন যেটা বদলায়, নয়তো batch ব্যবহার করুন।
- **Lakehouse = সস্তা storage + একটা table format**, যা ACID, time travel আর row-স্তরের delete ফিরিয়ে আনে
- **Medallion: bronze বিমা, silver contract, gold product**
- **Idempotent, বিভাজিত, backfill-যোগ্য, observable** — প্রতিটা pipeline task-এর চারটা বৈশিষ্ট্য
- **আপনার data-কে কোডের মতো test করুন**, আর প্রতিদিন একটা operational সংখ্যার সাথে মিলিয়ে দেখুন
- **ছোট শুরু করুন।** একটা replica + dbt + Metabase বেশিরভাগ কোম্পানিকে তাদের প্রত্যাশার চেয়ে অনেক বেশিদিন সেবা দেয়।

---

**পরবর্তী:** [অধ্যায় ১৩ — Networking](13-networking.md)

**ইংরেজি সংস্করণ:** [Chapter 12](../12-data-architecture.md) · **[সূচিপত্র](README.md)**
