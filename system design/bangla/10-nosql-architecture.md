# অধ্যায় ১০ — NoSQL Architecture 🟡

> "NoSQL" একটা বাজে নাম। এটা বর্ণনা করে এই database গুলো কী *নয়*।
> ভালো নাম হতো: **উদ্দেশ্য-ভিত্তিক database**। প্রতিটাই SQL যা দেয় তার কিছু ছেড়ে দেয়, বিনিময়ে নির্দিষ্ট কিছু পায়।
>
> আপনার কাজ হলো জানা **প্রতিটা কী ছেড়ে দেয়, আর কী কিনে নেয়।**

---

## ১০.১ পাঁচটা পরিবার

| পরিবার | Data-র আকৃতি | কীসের জন্য optimised | উদাহরণ |
|--------|-----------|---------------|----------|
| **Key-Value** | `key → blob` | Key দিয়ে সম্ভাব্য দ্রুততম lookup | Redis, Memcached, DynamoDB, etcd |
| **Document** | `key → JSON document` | নমনীয় schema, পুরো object পড়া | MongoDB, Couchbase, Firestore, DocumentDB |
| **Wide-Column** | `row key → column family` | বিশাল write throughput, বিশাল dataset | Cassandra, ScyllaDB, HBase, Bigtable |
| **Graph** | node + edge | সম্পর্কের মধ্য দিয়ে চলা | Neo4j, Neptune, ArangoDB, Memgraph |
| **Time-Series** | `(timestamp, tag) → মান` | Append-ভারী সময়-ক্রমিক data | InfluxDB, TimescaleDB, Prometheus, ClickHouse* |

\* ClickHouse আসলে একটা columnar OLAP database, তবে এটা খুব ঘন ঘন time-series-এর জন্য ব্যবহৃত হয়।

> **আপনার পাঁচটাতেই দক্ষ হওয়ার দরকার নেই।** আপনার চিনতে হবে একটা সমস্যা কোন পরিবারের, আর প্রতিটার একটা উদাহরণ যথেষ্ট ভালোভাবে জানতে হবে যাতে মূল্যায়ন করতে পারেন।

---

## ১০.২ NoSQL কেন আছে — SQL কী ছেড়ে দেয়

Relational database আপনাকে দেয়: join, ACID transaction, একটা নির্দিষ্ট schema, আর একটা শক্তিশালী declarative query ভাষা। এই feature গুলোর দাম আছে।

| SQL-এর শক্তি | এর দাম | NoSQL-এর বিনিময় |
|--------------|----------|-------------|
| Join | Distribute করা কঠিন — মেশিনের মধ্যে একটা join ব্যয়বহুল | **Denormalise করুন; কোনো join নয়।** যে আকৃতিতে পড়েন সেই আকৃতিতেই আগে থেকে জোড়া দিয়ে রাখুন। |
| Row জুড়ে ACID | সমন্বয় write throughput আর scale-out সীমিত করে | **শুধু প্রতি item-এ atomicity**, item-এর মধ্যে eventual consistency |
| নির্দিষ্ট schema | Migration ব্যয়বহুল আর ঝুঁকিপূর্ণ | **Schema-on-read** — যা খুশি জমা রাখুন, পরে ব্যাখ্যা করুন |
| নমনীয় ad-hoc query | প্রতিটা access path-এর জন্য planner-এর index লাগে | **Query-first design** — জানা query-র চারপাশে data model করুন |
| Strong consistency | Latency, partition-এ কম availability | **সমন্বয়যোগ্য / eventual consistency** |

> **এক লাইনের সারাংশ:** SQL আপনার *data* model করে। NoSQL আপনার *query* model করে।

### সৎ আধুনিক সতর্কবার্তা

মূল "scale-এর জন্য NoSQL লাগে" যুক্তিটার অনেকটাই দুর্বল হয়ে গেছে:

- PostgreSQL-এ আছে JSONB (document), full-text search, PostGIS (geo), pgvector (embedding), TimescaleDB (time-series), আর `SKIP LOCKED` (queue)
- Distributed SQL আছে (CockroachDB, Yugabyte, Spanner, Vitess) — SQL আর ACID **সহ** horizontal scale
- Hardware বিশাল হয়ে গেছে: ১২৮ core আর ২ TB RAM সহ একটা মেশিন ২০১২-তে যা একটা cluster লাগত তা সামলায়

> **তাই: PostgreSQL দিয়ে শুরু করুন। একটা নির্দিষ্ট, নাম করা access pattern যেটা একটা NoSQL store নাটকীয়ভাবে ভালোভাবে সামলায় — তখনই সেটা যোগ করুন।** "Polyglot persistence" একটা সত্যিকারের আর ভালো কৌশল — কিন্তু প্রতিটা বাড়তি database মানে আরেকটা জিনিস backup করা, monitor করা, patch করা, নিরাপদ রাখা আর রাত ৩টায় সেটার জন্য ডাক পাওয়া।

---

## ১০.৩ Key-Value store

সবচেয়ে সহজ মডেল: `GET key`, `PUT key value`, `DELETE key`। কোনো query নেই, কোনো join নেই, কোনো scan নেই।

### Redis 🟢 (এটা আপনি ব্যবহার করবেন)

Redis একটা key-value store, যেখানে *মান* গুলো সমৃদ্ধ data কাঠামো, memory-তে রাখা।

```redis
# String — caching, counter
SET session:ses_881 "{...json...}" EX 900
INCR ratelimit:tenant_42:2026091210

# Hash — object, field-স্তরের হালনাগাদ
HSET customer:42 name "Delower" tier "gold" verified_at "2026-09-12"
HINCRBY customer:42 login_count 1

# List — queue, সাম্প্রতিক আইটেম
LPUSH recent:user_42 "ses_881"
LTRIM recent:user_42 0 9              # শুধু শেষ ১০টা রাখুন

# Set — অনন্য সদস্যপদ, tag
SADD online_users 42 99 105
SISMEMBER online_users 42

# Sorted Set — leaderboard, priority queue, sliding-window rate limit
ZADD leaderboard 9500 "user_42"
ZREVRANGE leaderboard 0 9 WITHSCORES      # শীর্ষ ১০

# Stream — একটা append-only log (Kafka-lite)
XADD events * type verification.passed session ses_881

# HyperLogLog — volume যাই হোক, ১২ KB-তে আনুমানিক cardinality
PFADD daily_uniques user_42 user_99
PFCOUNT daily_uniques                      # ~০.৮১% ত্রুটি, ধ্রুব memory

# Geo — radius query
GEOADD stores 90.4125 23.8103 "dhaka_01"
GEOSEARCH stores FROMLONLAT 90.40 23.81 BYRADIUS 5 km ASC
```

**Redis সত্যিই যেসব কাজে দারুণ:**
- Caching (অধ্যায় ১১)
- Session জমা রাখা
- Rate limiting (atomic counter + Lua script)
- Leaderboard আর ক্রমযুক্ত data (sorted set-এর কোনো ভালো SQL সমতুল্য নেই)
- হালকা fan-out আর WebSocket backplane-এর জন্য pub/sub
- Distributed lock — **শর্তসাপেক্ষে** (নিচে দেখুন)
- Job queue (Stream দিয়ে, বা BullMQ/Celery/RQ-র মতো library দিয়ে)

**Persistence-এর বিকল্প (Redis-কে data দিয়ে বিশ্বাস করার আগে এগুলো বুঝুন):**

| Mode | আচরণ | Data হারানোর ঝুঁকি |
|------|-----------|---------------|
| **RDB** | পর্যায়ক্রমিক point-in-time snapshot | শেষ snapshot-এর পর সবকিছু হারায় (মিনিট) |
| **AOF** | প্রতিটা write command একটা log-এ যোগ করে | ছোট (`everysec` = ~১ সেকেন্ড; `always` = কিছুই না, কিন্তু ধীর) |
| **দুটোই** | দ্রুত restart-এর জন্য RDB, durability-র জন্য AOF | Data গুরুত্বপূর্ণ হলে সুপারিশকৃত |
| **কিছুই না** | নিখাদ in-memory | Restart-এ সবকিছু |

> **Default মানসিক মডেল: Redis-কে এমন একটা cache ভাবুন যেটা যে কোনো মুহূর্তে মুছে যেতে পারে।** এটাকে system of record হিসেবে ব্যবহার করলে AOF, replication আর backup ইচ্ছাকৃতভাবে configure করুন — আর জানুন যে তবু এটা key জুড়ে ACID নিশ্চয়তা সহ একটা database নয়।

**Redis-এর single-threaded execution** (command প্রক্রিয়াকরণে) একটা feature: প্রতিটা command atomic, তাই `INCR`, `SETNX` আর Lua script race-মুক্ত। এর মানে আবার **একটা ধীর command সবকিছু আটকে দেয়** — production-এ কখনো `KEYS *` চালাবেন না (`SCAN` ব্যবহার করুন), আর বড় কাঠামোতে বড় `ZRANGE`/`HGETALL` নিয়ে সাবধান থাকুন।

**Eviction policy — এটা configure করুন, default মেনে নেবেন না:**

```
maxmemory 4gb
maxmemory-policy allkeys-lru      # cache-এর ব্যবহার: সবচেয়ে কম-সম্প্রতি-ব্যবহৃতটা ফেলুন
# volatile-ttl    : শুধু TTL আছে এমন key ফেলুন, সবচেয়ে ছোট TTL আগে
# noeviction      : ভরে গেলে write প্রত্যাখ্যান করুন ← DEFAULT, আর এটা আপনাকে ডাক পাঠাবে
```

**Distributed lock — সৎ অবস্থান:** একটা মাত্র Redis-এ `SET key val NX PX 30000` lock "যথাসাধ্য" সমন্বয়ের জন্য ঠিক আছে (দ্বিগুণ কাজ এড়ানো)। Partition বা process থেমে যাওয়ার অবস্থায় সঠিকতার জন্য এটা **নিরাপদ নয়** — Redlock বিতর্ক এটা মীমাংসা করেছে। **সঠিকতা যদি lock-এর উপর নির্ভর করে, তাহলে etcd/ZooKeeper ব্যবহার করুন, অথবা এমনভাবে নতুন করে design করুন যাতে lock-ই না লাগে** (idempotency, optimistic concurrency, বা একটা database row lock)।

### DynamoDB 🟡

AWS-এর managed key-value/document store। এটা বোঝা মূল্যবান কারণ এর design-এর constraint গুলো NoSQL মানসিকতা অন্য যে কোনো কিছুর চেয়ে ভালো শেখায়।

```
Primary key = Partition Key (PK)  [+ Sort Key (SK)]

Partition key ঠিক করে item-টা কোন শারীরিক partition-এ থাকে।
Sort key একটা partition-এর ভেতরে item সাজায় আর range query সম্ভব করে।
```

**Single-table design** — যে pattern প্রথমে সবাইকে বিভ্রান্ত করে:

```
PK                  SK                        Attribute
──────────────────────────────────────────────────────────────────────
TENANT#42           METADATA                  {name: "Acme", plan: "pro"}
TENANT#42           SESSION#2026-09-12#ses_1  {status: "passed", score: 0.94}
TENANT#42           SESSION#2026-09-12#ses_2  {status: "failed", score: 0.31}
TENANT#42           USER#alice                {role: "admin"}
CUSTOMER#99         PROFILE                   {email: "a@b.com"}
CUSTOMER#99         SESSION#ses_1             {...}
```

একটা query — `PK = TENANT#42 AND begins_with(SK, "SESSION#2026-09-12")` — একটা tenant-এর একদিনের সব session ফেরত দেয়, একটা partition থেকে, এক round trip-এ, কোনো join ছাড়াই।

**DynamoDB-র যে নিয়মগুলো সব NoSQL-এই খাটে:**

১. **আপনার entity নয়, আপনার access pattern থেকে design করুন।** Application যে প্রতিটা query করবে *আগে* সেগুলোর তালিকা করুন। কোনো query ওই তালিকায় না থাকলে আপনি সেটা দক্ষভাবে সামলাতে পারবেন না।
২. **যা key নয় তা আপনি query করতে পারবেন না**, একটা scan (যেটা ধীর আর ব্যয়বহুল) বা একটা secondary index ছাড়া
৩. **গরম partition আপনাকে মেরে ফেলে** — এমন একটা partition key বাছুন যা সমানভাবে ছড়ায়
৪. **Item-এর আকারের সীমা** (DynamoDB-তে ৪০০ KB) — বড় blob object storage-এ যায়, item-এ একটা pointer থাকে
৫. **পরে একটা নতুন access pattern যোগ করতে একটা নতুন index বা একটা data migration লাগতে পারে** — এটাই query-first modelling-এর দাম

---

## ১০.৪ Document store — MongoDB 🟡

Document হলো JSON (BSON) object। Collection হলো document-এর দল। Default-এ কোনো schema বলবৎ হয় না।

```javascript
{
  _id: ObjectId("..."),
  tenantId: "t_42",
  customerId: "cus_99",
  status: "passed",
  score: 0.94,
  attempts: [                                // EMBEDDED array
    { number: 1, passed: false, score: 0.61, at: ISODate("...") },
    { number: 2, passed: true,  score: 0.94, at: ISODate("...") }
  ],
  device: { os: "iOS 18", model: "iPhone 15", appVersion: "3.2.1" },
  createdAt: ISODate("2026-09-12T10:00:00Z")
}
```

### Embed বনাম reference ⭐ — মূল modelling সিদ্ধান্ত

| | **Embed** | **Reference** |
|---|---|---|
| আকৃতি | Parent-এর ভেতরে nested | একটা ID জমা রাখুন, আলাদাভাবে আনুন |
| Read | একটা query, সবকিছু উপস্থিত | একাধিক query (বা `$lookup`) |
| Write | পুরো document হালনাগাদ | স্বাধীনভাবে হালনাগাদ |
| কখন সেরা | ১-থেকে-কয়েক, একসাথে পড়া হয়, সীমাবদ্ধ বৃদ্ধি | ১-থেকে-অনেক/অনেক-থেকে-অনেক, সীমাহীন, আলাদাভাবে ব্যবহৃত |

**সিদ্ধান্তের নিয়ম:**

```
EMBED করুন যখন:
  ✅ Child সবসময় parent-এর সাথে পড়া হয় (order line, ঠিকানা, attempt)
  ✅ Child-এর স্বাধীন কোনো অস্তিত্ব নেই
  ✅ Array সীমাবদ্ধ (ধরা যাক, < ১০০টা আইটেম)
  ✅ Child parent-এর চেয়ে অনেক বেশি বার হালনাগাদ হয় না

REFERENCE করুন যখন:
  ✅ Array সীমাহীনভাবে বাড়তে পারে (৫ বছরে একজন customer-এর session)
  ✅ Child নিজে থেকেই query হয়
  ✅ অনেক parent একই child ভাগ করে
  ✅ Child বড়
```

> **সীমাহীন-array anti-pattern:** একটা device document-এ "এই device-এর সব event" embed করা। এটা চিরকাল বাড়ে, ১৬ MB document-সীমায় পৌঁছায়, আর প্রতিটা ছোট হালনাগাদ একটা বিশাল document নতুন করে লেখে। **সময়ের সাথে বাড়ে এমন যে কোনো array-কে একটা আলাদা collection হতে হবে।**

### মানুষ MongoDB-তে কেন পুড়ে যায়

১. **"Schemaless" মানে "কোনো schema নেই" নয়** — মানে schema-টা আপনার application কোডে, পাঁচ জায়গায়, তিনটা সংস্করণে, অনথিভুক্ত। **Schema validation ব্যবহার করুন।**

```javascript
db.createCollection("sessions", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["tenantId", "status", "createdAt"],
    properties: {
      status: { enum: ["pending", "processing", "passed", "failed", "review"] },
      score:  { bsonType: "double", minimum: 0, maximum: 1 }
    }
  }},
  validationLevel: "strict"
});
```

২. **অনুপস্থিত index বিপর্যয়কর** — ৫ কোটি document-এ একটা collection scan। `.explain("executionStats")` দিয়ে দেখুন আর `COLLSCAN` খুঁজুন।
৩. **পুরনো default অনিরাপদ ছিল** (unacknowledged write)। আধুনিক সংস্করণে default `w: "majority"`, তবে **আপনার driver-এর write concern স্পষ্টভাবে যাচাই করুন।**
৪. **Document জুড়ে transaction আছে (৪.০+) কিন্তু SQL-এর চেয়ে ধীর আর সীমিত।** এগুলো যদি অনবরত লাগে, তাহলে আপনার document model ভুল — অথবা আপনার SQL লাগত।

### Replica set আর নির্বাচন

```
┌─────────┐      ┌───────────┐      ┌───────────┐
│ PRIMARY │─────►│ SECONDARY │      │ SECONDARY │
└─────────┘      └───────────┘      └───────────┘
  সব write          replication (oplog)

Primary fail করে → secondary গুলো একটা নির্বাচন করে (Raft-এর মতো) → একটা নতুন primary।
সংখ্যাগরিষ্ঠতা লাগে, তাই বিজোড় সংখ্যা চালান (৩ বা ৫)। ← অধ্যায় ০৫-এর একই নিয়ম
```

**Write concern আর read concern — এগুলো ইচ্ছাকৃতভাবে configure করুন:**

```javascript
// Write concern: কতগুলো node-কে স্বীকৃতি দিতে হবে?
{ w: 1 }           // শুধু primary — দ্রুত, failover-এ data হারাতে পারে
{ w: "majority" }  // ← গুরুত্বপূর্ণ যা কিছুর জন্য এটাই ব্যবহার করুন
{ w: "majority", j: true }  // + disk-এ journal করা

// Read concern: আপনি কোন consistency চান?
{ readConcern: { level: "local" } }        // এমন data পড়তে পারে যা rollback হতে পারে
{ readConcern: { level: "majority" } }     // শুধু majority-commit হওয়া data
{ readConcern: { level: "linearizable" } } // সবচেয়ে শক্তিশালী, সবচেয়ে ধীর

// Read preference: read কোথায় যায়?
{ readPreference: "primary" }              // default, consistent
{ readPreference: "secondaryPreferred" }   // read scale করুন, পুরনো হওয়া মেনে নিন
```

> `w: "majority"` + `readConcern: "majority"` হলো নিরাপদ production জোড়া। `w: 1` একটা নীরব data-হারানোর setting, ঠিক Kafka-র `acks=1`-এর মতো।

### Sharding

```
mongos (router) ──► Config server (cluster-এর metadata)
      │
      ├──► Shard 1 (replica set)
      ├──► Shard 2 (replica set)
      └──► Shard 3 (replica set)
```

অধ্যায় ০৪-এর একই shard-key নিয়ম: উচ্চ cardinality, সমান বণ্টন, আপনার query-র সাথে মেলে, আর বদলায় না। **একটা ক্রমবর্ধমান shard key (timestamp, ObjectId) একটা গরম shard তৈরি করে** — সব write শেষ chunk-এ যায়। Write-ভারী collection-এ hashed sharding বা একটা যৌগিক key ব্যবহার করুন।

---

## ১০.৫ Wide-column store — Cassandra 🟡

**বিশাল write throughput আর রৈখিক scalability**-র জন্য বানানো, কোনো single point of failure ছাড়াই।

```
প্রতিটা node সমান। কোনো leader নেই। Data একটা consistent-hashing ring-এ বসে।

              Node A
           ╱          ╲
      Node D          Node B      প্রতিটা key একটা অবস্থানে hash হয়;
           ╲          ╱           এটা ঘড়ির কাঁটার দিকে পরের N node-এ জমা হয়।
              Node C
```

### Data model query দিয়েই নির্ধারিত

```cql
-- আপনি প্রতি QUERY-তে একটা TABLE design করেন। পুনরাবৃত্তি স্বাভাবিক আর প্রত্যাশিত।

CREATE TABLE sessions_by_tenant (
    tenant_id   uuid,
    created_at  timestamp,
    session_id  uuid,
    status      text,
    score       decimal,
    PRIMARY KEY ((tenant_id), created_at, session_id)
    --           ^partition   ^clustering কলাম (partition-এর ভেতরে sort-এর ক্রম)
) WITH CLUSTERING ORDER BY (created_at DESC);

-- বরং customer দিয়ে query করা লাগবে? আপনি একটা দ্বিতীয় table লেখেন।
CREATE TABLE sessions_by_customer (
    customer_id uuid,
    created_at  timestamp,
    session_id  uuid,
    status      text,
    PRIMARY KEY ((customer_id), created_at, session_id)
) WITH CLUSTERING ORDER BY (created_at DESC);

-- Application প্রতিটা insert-এ দুটোতেই লেখে। এটাই design, কোনো কারসাজি নয়।
```

**Cassandra-র নিয়মগুলো:**
১. **আগে query, পরে table।** প্রতি access pattern-এ একটা table।
২. **জোরালোভাবে denormalise করুন।** অবাধে data-র পুনরাবৃত্তি করুন — disk সস্তা, join অসম্ভব।
৩. **Query করতে হলে partition key জানতেই হবে।** কোনো partition key নেই = একটা পূর্ণ cluster scan = করবেন না।
৪. **Partition সীমাবদ্ধ রাখুন** (লক্ষ্য < ১০০ MB, < ১ লাখ row)। সীমাহীন partition ১ নম্বর Cassandra ব্যর্থতা — দরকার হলে সময় দিয়ে bucket করুন: `PRIMARY KEY ((device_id, day), timestamp)`।
৫. **কোনো join নেই। Partition জুড়ে কোনো aggregate নেই। যথেচ্ছ কলামে কোনো `ORDER BY` নেই।**

**সমন্বয়যোগ্য consistency (সত্যিই কাজের feature):**

```cql
CONSISTENCY QUORUM;      -- R + W > RF → strong consistency (অধ্যায় ০৪ §৪.৮)
CONSISTENCY ONE;         -- দ্রুততম, eventually consistent
CONSISTENCY LOCAL_QUORUM;-- স্থানীয় datacenter-এর ভেতরে quorum — সাধারণ multi-DC পছন্দ
```

**Cassandra সত্যিই কোথায় জেতে:** বিশাল scale-এ time-series, IoT telemetry, message/event-এর ইতিহাস, activity feed, multi-datacenter active-active write, এমন write-হার যেখানে একটামাত্র leader তাল রাখতে পারে না। Discord, Netflix আর Apple-এর মতো কোম্পানি এটা petabyte scale-এ চালায়।

**কোথায় হারে:** ad-hoc query, join, transaction, বা শক্তিশালী একক-row read-modify-write দরকার এমন যে কোনো কিছু। আরও: **delete ব্যয়বহুল** — এগুলো "tombstone" লেখে, যা compaction সরানোর আগ পর্যন্ত পড়তে আর মেলাতে হয়; ভারী delete সহ একটা কাজ Cassandra-র একটা anti-pattern।

**ScyllaDB** হলো Cassandra-র একটা C++ পুনর্লিখন, একই API, প্রতি node-এ অনেক ভালো performance, আর কম latency-র লেজ। আজ কেউ Cassandra প্রস্তাব করলে জিজ্ঞেস করুন ScyllaDB মানায় কিনা।

---

## ১০.৬ Graph database 🟡

**যে সমস্যার সমাধান করে:** এমন সম্পর্ক যেগুলোর মধ্য দিয়ে অনেক ধাপ গভীরে যেতে হয়। SQL-এ "বন্ধুর বন্ধুর বন্ধু" তিনটা self-join; ছয় ধাপ চালানোই যায় না।

```cypher
// Neo4j / Cypher
MATCH (a:Customer {id: $id})-[:SHARES_DEVICE|SHARES_IP*1..4]-(b:Customer)
WHERE b.riskScore > 0.7
RETURN DISTINCT b.id, b.riskScore
```

এটা একটা fraud ring-এর মধ্য দিয়ে চার ধাপের চলাচল। SQL-এ এটা একটা recursive CTE যেটা শেষই হবে না।

**Graph কোথায় জেতে:**
- **Fraud ring** (ভাগ করা device, IP, ঠিকানা, ফোন নম্বর) — একটা KYC/identity ব্যবসার জন্য এটাই মোক্ষম ব্যবহার
- সামাজিক নেটওয়ার্ক আর recommendation ("যাঁরা X কিনেছেন তাঁরা…")
- Knowledge graph আর entity resolution
- Network/infrastructure-এর topology আর প্রভাব বিশ্লেষণ
- গভীর উত্তরাধিকার সহ access control
- Supply chain আর নির্ভরতা বিশ্লেষণ

**কোথায় হারে:** bulk aggregation, উচ্চ write throughput, সাধারণ lookup (একটা KV store দ্রুত), আর যা আসলে tabular তেমন যা কিছু।

> **ব্যবহারিক নোট:** আপনি খুব কমই একটা graph database-কে আপনার প্রধান store বানান। আপনি যে সম্পর্কগুলো নিয়ে ভাবেন সেগুলো একটা graph-এ **project** করেন, আপনার relational system of record-এর পাশাপাশি। PostgreSQL-এর recursive CTE আর Apache AGE extension অগভীর চলাচল ভালোভাবেই সামলায় — সত্যিই যখন গভীর, পরিবর্তনশীল-দৈর্ঘ্যের চলাচল দ্রুত লাগবে তখনই একটা নিবেদিত graph DB-র দিকে হাত বাড়ান।

---

## ১০.৭ Time-series database 🟡

**Data-র আকৃতি:** বিশাল append-only write, timestamp করা, খুব কমই হালনাগাদ হয়, সময়-পরিসর দিয়ে aggregation সহ query হয়, আর পুরনো data মূল্য হারায়।

```sql
-- TimescaleDB: PostgreSQL-এর extension — আপনি SQL রাখেন আর time-series performance পান
CREATE TABLE metrics (
    time        TIMESTAMPTZ NOT NULL,
    tenant_id   UUID NOT NULL,
    metric      TEXT NOT NULL,
    value       DOUBLE PRECISION
);
SELECT create_hypertable('metrics', 'time', chunk_time_interval => INTERVAL '1 day');

-- স্বয়ংক্রিয় আগাম-aggregation, ধাপে ধাপে হালনাগাদ রাখা
CREATE MATERIALIZED VIEW metrics_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket, tenant_id, metric,
       avg(value), max(value), count(*)
FROM metrics GROUP BY 1, 2, 3;

-- Compression আর retention policy হিসেবে
SELECT add_compression_policy('metrics', INTERVAL '7 days');   -- ১০-২০× ছোট
SELECT add_retention_policy('metrics', INTERVAL '1 year');     -- স্বয়ংক্রিয় মুছে ফেলা
```

**Time-series database যা করে যা অন্যরা করে না:** সময়-বিভাজিত storage, columnar compression (প্রায়ই ১০–২০×), downsampling/rollup, ফাঁক পূরণ আর interpolation, শেষ-বিন্দুর query, আর প্রথম-শ্রেণির feature হিসেবে retention policy।

| বিকল্প | নোট |
|--------|-------|
| **TimescaleDB** | PostgreSQL extension — **আপনি যদি এমনিতেই Postgres চালান তাহলে সবচেয়ে সহজ পছন্দ** |
| **InfluxDB** | উদ্দেশ্য-ভিত্তিক; নিজস্ব query ভাষা |
| **Prometheus** | Infrastructure-এর metric + alerting — pull-ভিত্তিক, সাধারণ store নয় |
| **ClickHouse** | Columnar OLAP; অবিশ্বাস্য দ্রুত বিশ্লেষণধর্মী aggregation। বড় scale-এ event analytics-এর জন্য ক্রমশ default। |

---

## ১০.৮ Search engine (ষষ্ঠ পরিবার, যেটা মানুষ ভুলে যায়) 🟡

**Elasticsearch / OpenSearch**-এর উল্লেখ প্রাপ্য, কারণ "search" একটা database সমস্যা যেটা SQL বা প্রচলিত NoSQL কোনোটাই ভালোভাবে সমাধান করে না।

এগুলো দেয়: inverted index, প্রাসঙ্গিকতার ক্রম (BM25), fuzzy মিলানো, faceted aggregation, autocomplete, বহুভাষিক বিশ্লেষণ, আর এখন vector/hybrid search।

**Architecture-এর নিয়ম:** Elasticsearch একটা **derived index, কখনোই system of record নয়।** আপনার টেকসই data থাকে Postgres-এ; আপনি CDC বা event দিয়ে সেটা Elasticsearch-এ project করেন। Index হারালে বা নষ্ট হলে আপনি উৎস থেকে আবার বানান। যেসব সিস্টেম Elasticsearch-কে সত্যের উৎস ভাবে, তারা শেষ পর্যন্ত data হারায় (এতে কোনো transaction নেই, আর reindexing একটা স্বাভাবিক operational ঘটনা)।

> **খুব তাড়াতাড়ি Elasticsearch-এর দিকে হাত বাড়াবেন না।** একটা GIN index সহ PostgreSQL-এর full-text search আশ্চর্যরকম অনেক কিছু সামলায় — শালীন প্রাসঙ্গিকতা সহ কয়েক লাখ document পর্যন্ত। সত্যিকারের relevance tuning, facet বা বহু-ভাষার বিশ্লেষণ লাগলে তখন সরুন।

---

## ১০.৯ Vector database ⚪🟡 (নতুন, ক্রমশ প্রাসঙ্গিক)

উচ্চ-মাত্রার embedding জমা রাখে আর নিকটতম প্রতিবেশী খুঁজে বের করে — semantic search আর RAG (retrieval-augmented generation) সিস্টেমের মেরুদণ্ড।

```sql
-- pgvector: আবারও, PostgreSQL প্রায়ই যথেষ্ট
CREATE EXTENSION vector;
ALTER TABLE documents ADD COLUMN embedding vector(1536);
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

SELECT id, content, embedding <=> $1 AS distance
FROM documents
ORDER BY embedding <=> $1
LIMIT 10;
```

নিবেদিত বিকল্প: Pinecone, Weaviate, Qdrant, Milvus। **একই পরামর্শ খাটে:** pgvector দিয়ে শুরু করুন; মোটামুটি কয়েক কোটি vector ছাড়ালে বা বিশেষায়িত filtering/sharding লাগলে একটা নিবেদিত store-এ যান।

Identity সিস্টেমের জন্যও প্রাসঙ্গিক: **মুখের embedding হলো vector।** একটা ১:N face search ("এই ব্যক্তি কি আগে অন্য নামে নথিভুক্ত হয়েছেন?") একটা নিকটতম-প্রতিবেশীর সমস্যা, আর pgvector বা একটা vector index-ই সঠিক টুল।

---

## ১০.১০ বেছে নেওয়া — সিদ্ধান্তের নির্দেশিকা

```
ACCESS PATTERN কী?

├── একটা key দিয়ে lookup, মিলিসেকেন্ডের নিচে হতে হবে, হারালে চলে
│   └──► REDIS
│
├── Key দিয়ে lookup, টেকসই, বিশাল scale, managed
│   └──► DYNAMODB / Cosmos DB
│
├── পুরো object পড়া, নমনীয়/বিকশিত আকৃতি, মাঝারি scale
│   └──► MONGODB  (তবে আগে: Postgres JSONB কি এটা পারে? সাধারণত হ্যাঁ।)
│
├── বিশাল write volume, সময়-ক্রমিক, multi-DC, কোনো একক leader নয়
│   └──► CASSANDRA / SCYLLADB
│
├── গভীর সম্পর্কের চলাচল (৩+ ধাপ), fraud ring, recommendation
│   └──► NEO4J  (বা অগভীর ক্ষেত্রে Postgres-এর recursive CTE / AGE)
│
├── Timestamp করা metric/event, সময়-পরিসরে aggregation, retention
│   └──► TIMESCALEDB (Postgres-এ থাকলে) / CLICKHOUSE / INFLUXDB
│
├── Full-text relevance, facet, fuzzy মিলানো, autocomplete
│   └──► ELASTICSEARCH  (একটা DERIVED index হিসেবে, কখনো সত্যের উৎস নয়)
│
├── Embedding-এর উপর semantic / সাদৃশ্য search
│   └──► আগে PGVECTOR; খুব বড় scale-এ একটা নিবেদিত vector DB
│
└── আর যা কিছু — transaction, সম্পর্ক, ad-hoc query, reporting
    └──► POSTGRESQL   ← সঠিক default
```

### যে কোনো datastore যোগ করার আগে যে প্রশ্নগুলো করবেন

১. **এটা এমন কোন access pattern সামলায় যা Postgres পারে না?** (নির্দিষ্ট হোন। "Scale" কোনো উত্তর নয়; "তিনটা datacenter জুড়ে সেকেন্ডে ৪০,০০০ write" একটা উত্তর।)
২. **রাত ৩টায় এটা কে চালাবে?** আমাদের কি সেই দক্ষতা আছে, নাকি আমরা managed কিনছি?
৩. **Consistency model কী, আর business কি সেটা মেনে নেয়?**
৪. **আমরা এটা কীভাবে backup করি, আর আমরা কি restore করেছি?**
৫. **Data এটার *ভেতরে* কীভাবে যায়, আর ওই pipeline ভাঙলে কী হয়?**
৬. **মোট খরচ কত — licence, infrastructure, আর মানুষের মনোযোগ?**

> **প্রতিটা বাড়তি datastore একটা স্থায়ী কর।** দুটো সাধারণত ঠিক আছে। ছয়টা মানে এমন একটা platform টিম যেটা আপনার নেই।

---

## ১০.১১ Polyglot persistence — ঠিকভাবে করা

একটা বাস্তবসম্মত পরিণত architecture:

```
┌──────────────────────────────────────────────────────────────┐
│                      Application                             │
└───┬─────────┬──────────┬──────────┬──────────┬───────────────┘
    │         │          │          │          │
┌───▼────┐┌───▼────┐┌────▼─────┐┌───▼─────┐┌───▼──────────┐
│Postgres││ Redis  ││Elastic-  ││ S3/Blob ││ ClickHouse   │
│        ││        ││search    ││         ││              │
│SYSTEM  ││ cache  ││ derived  ││ ভিডিও,   ││ analytics    │
│OF      ││session ││ search   ││ doc,    ││ (derived)    │
│RECORD  ││ rate   ││ index    ││ export  ││              │
│        ││ limit  ││(derived) ││         ││              │
└────────┘└────────┘└──────────┘└─────────┘└──────────────┘
     ▲         ▲          ▲                       ▲
     │         │          │                       │
  সত্যের     ফেলে দেওয়া   DERIVED               DERIVED
  উৎস       যায়         (আবার বানানো যায়)     (আবার বানানো যায়)
```

**গুরুত্বপূর্ণ শৃঙ্খলা: প্রতিটা store-এ একটা লেবেল দিন।**

| লেবেল | মানে | ফলাফল |
|-------|---------|-------------|
| **সত্যের উৎস** | প্রামাণিক কপি | Backup করা, PITR, সবচেয়ে শক্তিশালী consistency, সবচেয়ে বেশি যত্ন |
| **Derived** | উৎস থেকে বানানো | আবার বানানো যায়; backup লাগে না; পুরনো হতে পারে |
| **ফেলে দেওয়া যায়** | নিখাদ cache | এটা হারানো একটা performance-এর ঘটনা, data-র ঘটনা নয় |

> **যে ব্যর্থতার রূপটা এড়াতে হবে: একই সত্যের দুটো উৎস।** Postgres যখন বলে session pass করেছে আর MongoDB বলে fail করেছে, তখন কোনো সঠিক উত্তর নেই আর ফেরার কোনো উপায় নেই। ঠিক একটা store প্রতিটা সত্যের মালিক; বাকি সবকিছু তার থেকে derived, আদর্শভাবে একটা pipeline দিয়ে (CDC বা event — অধ্যায় ০৬)।

---

## ১০.১২ সাধারণ ভুল

১. **না মেপেই "scale"-এর জন্য NoSQL বাছা** — সেকেন্ডে ৫০০ write-এ Cassandra লাগে না
২. **MongoDB-কে একটা relational database হিসেবে ব্যবহার** — সব জায়গায় ID reference সহ document আর `$lookup` join। আপনি SQL চেয়েছিলেন।
৩. **সীমাহীন array / সীমাহীন partition** — document আকারের সীমায় পৌঁছায়; Cassandra-র partition query-অযোগ্য হয়ে যায়
৪. একটা "schemaless" store-এ **কোনো schema validation না থাকা** — production-এ একই entity-র তিনটা আকৃতি
৫. **অনুপস্থিত index** — ৫ কোটি document-এ একটা collection scan
৬. **Elasticsearch (বা Redis)-কে system of record ভাবা** — data হারানো শুধু সময়ের ব্যাপার
৭. **একই সত্যের দুটো উৎস** — অমীমাংসেয় সংঘর্ষ
৮. **একমুখী ক্রমবর্ধমান shard/partition key** — প্রতিটা write একটা গরম node-এ যায়
৯. গুরুত্বপূর্ণ data-তে **`w: 1` / `acks=1` ধাঁচের write concern**
১০. UI-তে **eventual-consistency-র contract উপেক্ষা করা** — ব্যবহারকারী save করে সাথে সাথেই পুরনো মান দেখেন
১১. **পাঁচজনের টিমে ছয়টা datastore** — কেউ কোনোটাই ভালোভাবে চালাতে পারে না
১২. একটা query-first database-এ **query-র বদলে entity model করা** — তারপর আবিষ্কার করা যে নতুন report-টা অসম্ভব

---

## ১০.১৩ আর্কিটেক্টের চেকলিস্ট

- [ ] একটা NoSQL data model বাছার **আগে** প্রতিটা access pattern তালিকাভুক্ত
- [ ] প্রতিটা store-এর জন্য: এটা কি সত্যের উৎস, derived, নাকি ফেলে দেওয়া যায়? লেখা আছে।
- [ ] প্রতিটা সত্যের ঠিক একজন মালিক; derived store-এর একটা নির্ধারিত পুনর্নির্মাণ প্রক্রিয়া আছে
- [ ] প্রতিটা store-এর consistency model বোঝা আর business মেনে নিয়েছে
- [ ] Write concern / consistency level স্পষ্টভাবে সেট করা, default-এ ছেড়ে দেওয়া নয়
- [ ] Partition/shard key সমানভাবে ছড়ায় আর query-র সাথে মেলে; কোনো একমুখী key নেই
- [ ] সব partition/document/array সীমাবদ্ধ, দরকার হলে একটা bucketing কৌশল সহ
- [ ] "Schemaless" store-এও schema validation চালু
- [ ] প্রতিটা query-পথের জন্য index আছে; explain-এর output দিয়ে যাচাই করা
- [ ] Redis: `maxmemory` আর eviction policy সেট করা; ব্যবহারের সাথে মিলিয়ে persistence configure করা
- [ ] প্রতিটা সত্যের-উৎস store-এর জন্য backup আর একটা **পরীক্ষিত** restore
- [ ] টিমের কেউ রাত ৩টায় প্রতিটা store চালাতে পারে — নয়তো এটা managed
- [ ] "PostgreSQL কি এটা পারত?" — প্রশ্নটা করা আর লিখিতভাবে উত্তর দেওয়া হয়েছে

---

## ১০.১৪ নিজেকে যাচাই

১. পাঁচটা NoSQL পরিবারের নাম, প্রতিটার একটা উদাহরণ, আর প্রতিটা যে access pattern সামলায় বলুন।
২. "SQL আপনার data model করে; NoSQL আপনার ___ model করে।" পূরণ করুন আর ব্যাখ্যা করুন।
৩. PostgreSQL এখন করে এমন চারটা জিনিস বলুন যেগুলোর জন্য আগে একটা আলাদা NoSQL store লাগত।
৪. MongoDB-তে কখন embed করবেন আর কখন reference করবেন? চারটা নিয়ম দিন।
৫. সীমাহীন-array anti-pattern কী আর আপনি এটা কীভাবে ঠিক করবেন?
৬. Cassandra-র "প্রতি query-তে একটা table" ব্যাখ্যা করুন। সেখানে পুনরাবৃত্তি কেন সঠিক?
৭. Cassandra-র tombstone কী, আর delete-ভারী কাজ কেন একটা anti-pattern?
৮. `w: "majority"` + `readConcern: "majority"` আপনাকে কী দেয়, আর `w: 1`-এ কী ঝুঁকি?
৯. যেখানে সঠিকতা গুরুত্বপূর্ণ সেখানে distributed lock-এর জন্য Redis কেন অনিরাপদ? আপনার কী ব্যবহার করা উচিত?
১০. সত্যের-উৎস, derived, আর ফেলে-দেওয়া-যায় store-এর পার্থক্য কী?
১১. Elasticsearch কেন কখনো system of record হওয়া উচিত নয়?
১২. একটা architecture-এ একটা নতুন datastore যোগ করার আগে ছয়টা প্রশ্ন দিন।

---

## ১০.১৫ মূল কথাগুলো

- **NoSQL = উদ্দেশ্য-ভিত্তিক।** প্রতিটা পরিবার SQL যা দেয় তার কিছু নির্দিষ্ট কিছুর বিনিময়ে ছেড়ে দেয়।
- **SQL data model করে; NoSQL query model করে।** Model করার *আগে* প্রতিটা access pattern তালিকাভুক্ত করুন।
- **PostgreSQL-ই সঠিক default** — আর এখন এটা document, search, geo, time-series, vector আর queue সবই ঢাকে
- **শুধু একটা নাম করা access pattern-এর জন্য একটা datastore যোগ করুন যেটা এটা নাটকীয়ভাবে ভালো সামলায়**, আর বলুন কে এটা চালাবে
- **প্রতিটা store-এ লেবেল দিন: সত্যের উৎস, derived, নাকি ফেলে দেওয়া যায়।** কখনো একটা সত্যের দুটো উৎস নয়।
- **সীমাবদ্ধ partition, সীমাবদ্ধ document, সীমাবদ্ধ array** — সীমাহীন বৃদ্ধিই সর্বজনীন NoSQL-ঘাতক
- **Write/read concern স্পষ্টভাবে সেট করুন।** Default benchmark-এর জন্য সমন্বয় করা, আপনার টাকার জন্য নয়।
- **Redis একটা মহাশক্তি সহ cache** — ইচ্ছাকৃতভাবে অন্যভাবে configure না করলে একে মুছে-যাওয়ার-যোগ্য ভাবুন
- **Elasticsearch আর analytics store হলো derived index**, সবসময় আবার বানানোর যোগ্য
- **প্রতিটা বাড়তি datastore একটা স্থায়ী operational কর।** সৎভাবে গুনুন।

---

**পরবর্তী:** [অধ্যায় ১১ — Caching](11-caching.md)

**ইংরেজি সংস্করণ:** [Chapter 10](../10-nosql-architecture.md) · **[সূচিপত্র](README.md)**
