# Chapter 10 — NoSQL Architecture 🟡

> "NoSQL" is a terrible name. It describes what these databases are *not*.
> A better name: **purpose-built databases**. Each one trades away something SQL gives you, in exchange for something specific.
>
> Your job is to know **what each one trades, and what it buys.**

---

## 10.1 The five families

| Family | Data shape | Optimised for | Examples |
|--------|-----------|---------------|----------|
| **Key-Value** | `key → blob` | The fastest possible lookup by key | Redis, Memcached, DynamoDB, etcd |
| **Document** | `key → JSON document` | Flexible schema, whole-object reads | MongoDB, Couchbase, Firestore, DocumentDB |
| **Wide-Column** | `row key → column families` | Massive write throughput, huge datasets | Cassandra, ScyllaDB, HBase, Bigtable |
| **Graph** | nodes + edges | Relationship traversal | Neo4j, Neptune, ArangoDB, Memgraph |
| **Time-Series** | `(timestamp, tags) → values` | Append-heavy time-ordered data | InfluxDB, TimescaleDB, Prometheus, ClickHouse* |

\* ClickHouse is really a columnar OLAP database, but it is very often used for time-series.

> **You do not need to master all five.** You need to recognise which family a problem belongs to, and know one example of each well enough to evaluate it.

---

## 10.2 Why NoSQL exists — what SQL gives up

Relational databases give you: joins, ACID transactions, a fixed schema, and a powerful declarative query language. Those features have costs.

| SQL strength | Its cost | NoSQL trade |
|--------------|----------|-------------|
| Joins | Hard to distribute — a join across machines is expensive | **Denormalise; no joins.** Store data pre-joined in the shape you read it. |
| ACID across rows | Coordination limits write throughput and scale-out | **Per-item atomicity only**, eventual consistency across items |
| Fixed schema | Migrations are expensive and risky | **Schema-on-read** — store whatever, interpret later |
| Flexible ad-hoc queries | The planner needs indexes for every access path | **Query-first design** — model the data around known queries |
| Strong consistency | Latency, lower availability under partition | **Tunable / eventual consistency** |

> **The one-line summary:** SQL models your *data*. NoSQL models your *queries*.

### The honest modern caveat

Much of the original "NoSQL is required for scale" argument has weakened:

- PostgreSQL has JSONB (documents), full-text search, PostGIS (geo), pgvector (embeddings), TimescaleDB (time-series), and `SKIP LOCKED` (queues)
- Distributed SQL exists (CockroachDB, Yugabyte, Spanner, Vitess) — horizontal scale *with* SQL and ACID
- Hardware got enormous: one machine with 128 cores and 2 TB of RAM handles what needed a cluster in 2012

> **So: start with PostgreSQL. Add a NoSQL store when you have a specific, named access pattern it serves dramatically better.** "Polyglot persistence" is a real and good strategy — but each extra database is an extra thing to back up, monitor, patch, secure and be paged about at 3 AM.

---

## 10.3 Key-Value stores

The simplest model: `GET key`, `PUT key value`, `DELETE key`. No queries, no joins, no scans.

### Redis 🟢 (you will use this)

Redis is a key-value store where the *values* are rich data structures, held in memory.

```redis
# Strings — caching, counters
SET session:ses_881 "{...json...}" EX 900
INCR ratelimit:tenant_42:2026091210

# Hashes — objects, field-level updates
HSET customer:42 name "Delower" tier "gold" verified_at "2026-09-12"
HINCRBY customer:42 login_count 1

# Lists — queues, recent items
LPUSH recent:user_42 "ses_881"
LTRIM recent:user_42 0 9              # keep only the last 10

# Sets — unique membership, tags
SADD online_users 42 99 105
SISMEMBER online_users 42

# Sorted Sets — leaderboards, priority queues, sliding-window rate limits
ZADD leaderboard 9500 "user_42"
ZREVRANGE leaderboard 0 9 WITHSCORES      # top 10

# Streams — an append-only log (Kafka-lite)
XADD events * type verification.passed session ses_881

# HyperLogLog — approximate cardinality in 12 KB, regardless of volume
PFADD daily_uniques user_42 user_99
PFCOUNT daily_uniques                      # ~0.81% error, constant memory

# Geo — radius queries
GEOADD stores 90.4125 23.8103 "dhaka_01"
GEOSEARCH stores FROMLONLAT 90.40 23.81 BYRADIUS 5 km ASC
```

**What Redis is genuinely great for:**
- Caching (Chapter 11)
- Session storage
- Rate limiting (atomic counters + Lua scripts)
- Leaderboards and ranked data (sorted sets have no good SQL equivalent)
- Pub/sub for lightweight fan-out and WebSocket backplanes
- Distributed locks — **with caveats** (see below)
- Job queues (via Streams, or libraries like BullMQ/Celery/RQ)

**Persistence options (understand these before trusting Redis with data):**

| Mode | Behaviour | Data loss risk |
|------|-----------|---------------|
| **RDB** | Periodic point-in-time snapshots | Lose everything since the last snapshot (minutes) |
| **AOF** | Append every write command to a log | Small (`everysec` = ~1 s; `always` = none, but slow) |
| **Both** | RDB for fast restart, AOF for durability | Recommended if the data matters |
| **None** | Pure in-memory | Everything on restart |

> **Default mental model: treat Redis as a cache that can be wiped at any moment.** If you use it as a system of record, configure AOF, replication and backups deliberately — and know that it is still not a database with ACID guarantees across keys.

**Redis single-threaded execution** (for command processing) is a feature: every command is atomic, so `INCR`, `SETNX` and Lua scripts are race-free. It also means **one slow command blocks everything** — never run `KEYS *` on production (use `SCAN`), and be careful with large `ZRANGE`/`HGETALL` on big structures.

**Eviction policy — configure it, do not accept the default:**

```
maxmemory 4gb
maxmemory-policy allkeys-lru      # cache use: evict least-recently-used
# volatile-ttl    : evict only keys with a TTL, shortest TTL first
# noeviction      : reject writes when full ← the DEFAULT, and it will page you
```

**Distributed locks — the honest position:** a `SET key val NX PX 30000` lock on a single Redis is fine for "best effort" coordination (avoiding duplicate work). It is **not safe** for correctness under partition or process pause — the Redlock debate settled this. **If correctness depends on the lock, use etcd/ZooKeeper, or redesign so you do not need a lock** (idempotency, optimistic concurrency, or a database row lock).

### DynamoDB 🟡

AWS's managed key-value/document store. Worth understanding because its design constraints teach the NoSQL mindset better than anything else.

```
Primary key = Partition Key (PK)  [+ Sort Key (SK)]

The partition key determines which physical partition the item lives on.
The sort key orders items within a partition and enables range queries.
```

**Single-table design** — the pattern that confuses everyone at first:

```
PK                  SK                        Attributes
──────────────────────────────────────────────────────────────────────
TENANT#42           METADATA                  {name: "Acme", plan: "pro"}
TENANT#42           SESSION#2026-09-12#ses_1  {status: "passed", score: 0.94}
TENANT#42           SESSION#2026-09-12#ses_2  {status: "failed", score: 0.31}
TENANT#42           USER#alice                {role: "admin"}
CUSTOMER#99         PROFILE                   {email: "a@b.com"}
CUSTOMER#99         SESSION#ses_1             {...}
```

One query — `PK = TENANT#42 AND begins_with(SK, "SESSION#2026-09-12")` — returns all of a tenant's sessions for a day, from one partition, in one round trip, with no joins.

**The DynamoDB rules that generalise to all NoSQL:**

1. **Design from your access patterns, not your entities.** List every query the application will make *first*. If a query is not in that list, you cannot serve it efficiently.
2. **You cannot query what is not a key** without a scan (which is slow and expensive) or a secondary index
3. **Hot partitions kill you** — choose a partition key that distributes evenly
4. **Item size limits** (400 KB in DynamoDB) — large blobs go to object storage with a pointer in the item
5. **Adding a new access pattern later may require a new index or a data migration** — this is the price of query-first modelling

---

## 10.4 Document stores — MongoDB 🟡

Documents are JSON (BSON) objects. Collections are groups of documents. No schema enforced by default.

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

### Embedding vs referencing ⭐ — the core modelling decision

| | **Embed** | **Reference** |
|---|---|---|
| Shape | Nested inside the parent | Store an ID, fetch separately |
| Read | One query, everything present | Multiple queries (or `$lookup`) |
| Write | Update the whole document | Update independently |
| Best when | 1-to-few, read together, bounded growth | 1-to-many/many-to-many, unbounded, accessed separately |

**Decision rules:**

```
EMBED when:
  ✅ The child is always read with the parent (order lines, address, attempts)
  ✅ The child does not exist independently
  ✅ The array is BOUNDED (say, < 100 items)
  ✅ The child is not updated far more often than the parent

REFERENCE when:
  ✅ The array could grow without bound (a customer's sessions over 5 years)
  ✅ The child is queried on its own
  ✅ Many parents share the child
  ✅ The child is large
```

> **The unbounded-array anti-pattern:** embedding "all events for this device" in a device document. It grows forever, hits the 16 MB document limit, and every small update rewrites a huge document. **Any array that grows with time must be a separate collection.**

### Why people get burned by MongoDB

1. **"Schemaless" does not mean "no schema"** — it means the schema is in your application code, in five places, in three versions, undocumented. **Use schema validation.**

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

2. **Missing indexes are catastrophic** — a collection scan on 50 million documents. Check with `.explain("executionStats")` and look for `COLLSCAN`.
3. **Old defaults were unsafe** (unacknowledged writes). Modern versions default to `w: "majority"`, but **verify your driver's write concern explicitly.**
4. **Cross-document transactions exist (4.0+) but are slower and more limited than SQL.** If you need them constantly, your document model is wrong — or you needed SQL.

### Replica sets and elections

```
┌─────────┐      ┌───────────┐      ┌───────────┐
│ PRIMARY │─────►│ SECONDARY │      │ SECONDARY │
└─────────┘      └───────────┘      └───────────┘
  all writes         replication (oplog)

Primary fails → the secondaries hold an election (Raft-like) → a new primary.
Requires a MAJORITY, so run an odd number (3 or 5). ← same rule as Chapter 05
```

**Write concern and read concern — configure these deliberately:**

```javascript
// Write concern: how many nodes must acknowledge?
{ w: 1 }           // primary only — fast, can lose data on failover
{ w: "majority" }  // ← USE THIS for anything that matters
{ w: "majority", j: true }  // + journalled to disk

// Read concern: what consistency do you want?
{ readConcern: { level: "local" } }        // may read data that could be rolled back
{ readConcern: { level: "majority" } }     // only majority-committed data
{ readConcern: { level: "linearizable" } } // strongest, slowest

// Read preference: where do reads go?
{ readPreference: "primary" }              // default, consistent
{ readPreference: "secondaryPreferred" }   // scale reads, accept staleness
```

> `w: "majority"` + `readConcern: "majority"` is the safe production pairing. `w: 1` is a silent data-loss setting, exactly like Kafka's `acks=1`.

### Sharding

```
mongos (router) ──► Config servers (cluster metadata)
      │
      ├──► Shard 1 (replica set)
      ├──► Shard 2 (replica set)
      └──► Shard 3 (replica set)
```

Same shard-key rules as Chapter 04: high cardinality, even distribution, matches your queries, and does not change. **A monotonically increasing shard key (timestamp, ObjectId) creates a hot shard** — all writes go to the last chunk. Use hashed sharding or a compound key for write-heavy collections.

---

## 10.5 Wide-column stores — Cassandra 🟡

Built for **enormous write throughput and linear scalability**, with no single point of failure.

```
Every node is equal. No leader. Data is placed on a consistent-hashing ring.

              Node A
           ╱          ╲
      Node D          Node B      Each key hashes to a position;
           ╲          ╱           it is stored on the next N nodes clockwise.
              Node C
```

### The data model is dictated by queries

```cql
-- You design ONE TABLE PER QUERY. Duplication is normal and expected.

CREATE TABLE sessions_by_tenant (
    tenant_id   uuid,
    created_at  timestamp,
    session_id  uuid,
    status      text,
    score       decimal,
    PRIMARY KEY ((tenant_id), created_at, session_id)
    --           ^partition   ^clustering columns (sort order within the partition)
) WITH CLUSTERING ORDER BY (created_at DESC);

-- Need to query by customer instead? You write a SECOND table.
CREATE TABLE sessions_by_customer (
    customer_id uuid,
    created_at  timestamp,
    session_id  uuid,
    status      text,
    PRIMARY KEY ((customer_id), created_at, session_id)
) WITH CLUSTERING ORDER BY (created_at DESC);

-- The application writes to BOTH on every insert. That is the design, not a hack.
```

**The Cassandra rules:**
1. **Query first, table second.** One table per access pattern.
2. **Denormalise aggressively.** Duplicate data freely — disk is cheap, joins are impossible.
3. **You must know the partition key to query.** No partition key = a full cluster scan = do not.
4. **Keep partitions bounded** (target < 100 MB, < 100k rows). Unbounded partitions are the #1 Cassandra failure — bucket by time if needed: `PRIMARY KEY ((device_id, day), timestamp)`.
5. **No joins. No aggregates across partitions. No `ORDER BY` on arbitrary columns.**

**Tunable consistency (the genuinely useful feature):**

```cql
CONSISTENCY QUORUM;      -- R + W > RF → strong consistency (Chapter 04 §4.8)
CONSISTENCY ONE;         -- fastest, eventually consistent
CONSISTENCY LOCAL_QUORUM;-- quorum within the local datacenter — the usual multi-DC choice
```

**Where Cassandra genuinely wins:** time-series at massive scale, IoT telemetry, message/event history, activity feeds, multi-datacenter active-active writes, write rates where a single leader cannot keep up. Companies like Discord, Netflix and Apple run it at petabyte scale.

**Where it loses:** anything needing ad-hoc queries, joins, transactions, or strong single-row read-modify-write semantics. Also: **deletes are expensive** — they write "tombstones" that must be read and merged until compaction removes them; a workload with heavy deletes is a Cassandra anti-pattern.

**ScyllaDB** is a C++ rewrite of Cassandra with the same API, much better performance per node, and lower latency tails. If someone proposes Cassandra today, ask whether ScyllaDB fits.

---

## 10.6 Graph databases 🟡

**The problem they solve:** relationships that need to be traversed many hops deep. In SQL, "friends of friends of friends" is three self-joins; six hops is unrunnable.

```cypher
// Neo4j / Cypher
MATCH (a:Customer {id: $id})-[:SHARES_DEVICE|SHARES_IP*1..4]-(b:Customer)
WHERE b.riskScore > 0.7
RETURN DISTINCT b.id, b.riskScore
```

That is a four-hop traversal across a fraud ring. In SQL it is a recursive CTE that will not finish.

**Where graphs win:**
- **Fraud rings** (shared devices, IPs, addresses, phone numbers) — this is the killer use case for a KYC/identity business
- Social networks and recommendations ("people who bought X also…")
- Knowledge graphs and entity resolution
- Network/infrastructure topology and impact analysis
- Access control with deep inheritance
- Supply chain and dependency analysis

**Where they lose:** bulk aggregation, high write throughput, simple lookups (a KV store is faster), anything that is really tabular.

> **Practical note:** you rarely make a graph database your primary store. You **project** the relationships you care about into a graph, alongside your relational system of record. PostgreSQL recursive CTEs and the Apache AGE extension handle shallow traversals fine — reach for a dedicated graph DB when you genuinely need deep, variable-length traversal at speed.

---

## 10.7 Time-series databases 🟡

**The shape of the data:** massive append-only writes, timestamped, rarely updated, queried by time range with aggregation, and old data loses value.

```sql
-- TimescaleDB: PostgreSQL extension — you keep SQL and get time-series performance
CREATE TABLE metrics (
    time        TIMESTAMPTZ NOT NULL,
    tenant_id   UUID NOT NULL,
    metric      TEXT NOT NULL,
    value       DOUBLE PRECISION
);
SELECT create_hypertable('metrics', 'time', chunk_time_interval => INTERVAL '1 day');

-- Automatic pre-aggregation, kept up to date incrementally
CREATE MATERIALIZED VIEW metrics_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket, tenant_id, metric,
       avg(value), max(value), count(*)
FROM metrics GROUP BY 1, 2, 3;

-- Compression and retention as policies
SELECT add_compression_policy('metrics', INTERVAL '7 days');   -- 10-20× smaller
SELECT add_retention_policy('metrics', INTERVAL '1 year');     -- automatic deletion
```

**What time-series databases do that others do not:** time-partitioned storage, columnar compression (often 10–20×), downsampling/rollups, gap-filling and interpolation, last-point queries, and retention policies as first-class features.

| Option | Notes |
|--------|-------|
| **TimescaleDB** | PostgreSQL extension — **easiest choice if you already run Postgres** |
| **InfluxDB** | Purpose-built; own query language |
| **Prometheus** | Metrics + alerting for infrastructure — pull-based, not a general store |
| **ClickHouse** | Columnar OLAP; blisteringly fast analytical aggregation. Increasingly the default for large-scale event analytics. |

---

## 10.8 Search engines (the sixth family people forget) 🟡

**Elasticsearch / OpenSearch** deserve a mention because "search" is a database problem that neither SQL nor typical NoSQL solves well.

They provide: inverted indexes, relevance ranking (BM25), fuzzy matching, faceted aggregation, autocomplete, multilingual analysis, and now vector/hybrid search.

**The architectural rule:** Elasticsearch is a **derived index, never a system of record.** Your durable data lives in Postgres; you project it into Elasticsearch via CDC or events. If the index is lost or corrupted, you rebuild it from the source. Systems that treat Elasticsearch as the source of truth eventually lose data (it has no transactions, and reindexing is a normal operational event).

> **Do not reach for Elasticsearch too early.** PostgreSQL full-text search with a GIN index handles a surprising amount — up to millions of documents with decent relevance. Move when you need real relevance tuning, facets, or multi-language analysis.

---

## 10.9 Vector databases ⚪🟡 (new, increasingly relevant)

Store high-dimensional embeddings and find nearest neighbours — the backbone of semantic search and RAG (retrieval-augmented generation) systems.

```sql
-- pgvector: again, PostgreSQL is often enough
CREATE EXTENSION vector;
ALTER TABLE documents ADD COLUMN embedding vector(1536);
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

SELECT id, content, embedding <=> $1 AS distance
FROM documents
ORDER BY embedding <=> $1
LIMIT 10;
```

Dedicated options: Pinecone, Weaviate, Qdrant, Milvus. **The same advice applies:** start with pgvector; move to a dedicated store when you exceed roughly tens of millions of vectors or need specialised filtering/sharding.

Also relevant for identity systems: **face embeddings are vectors.** A 1:N face search ("has this person enrolled before under another name?") is a nearest-neighbour problem, and pgvector or a vector index is the right tool.

---

## 10.10 Choosing — the decision guide

```
What is the ACCESS PATTERN?

├── Lookup by a single key, must be sub-millisecond, tolerable to lose
│   └──► REDIS
│
├── Lookup by key, durable, massive scale, managed
│   └──► DYNAMODB / Cosmos DB
│
├── Whole-object reads, flexible/evolving shape, moderate scale
│   └──► MONGODB  (but first: does Postgres JSONB do it? Usually yes.)
│
├── Enormous write volume, time-ordered, multi-DC, no single leader
│   └──► CASSANDRA / SCYLLADB
│
├── Deep relationship traversal (3+ hops), fraud rings, recommendations
│   └──► NEO4J  (or Postgres recursive CTE / AGE for shallow cases)
│
├── Timestamped metrics/events, aggregation over time ranges, retention
│   └──► TIMESCALEDB (if on Postgres) / CLICKHOUSE / INFLUXDB
│
├── Full-text relevance, facets, fuzzy matching, autocomplete
│   └──► ELASTICSEARCH  (as a DERIVED index, never the source of truth)
│
├── Semantic / similarity search over embeddings
│   └──► PGVECTOR first; a dedicated vector DB at very large scale
│
└── Anything else — transactions, relationships, ad-hoc queries, reporting
    └──► POSTGRESQL   ← the correct default
```

### The questions to ask before adding any datastore

1. **What access pattern does this serve that Postgres cannot?** (Be specific. "Scale" is not an answer; "40,000 writes/sec across three datacenters" is.)
2. **Who operates it at 3 AM?** Do we have that skill, or are we buying managed?
3. **What is the consistency model, and does the business accept it?**
4. **How do we back it up, and have we restored it?**
5. **How does data get *into* it, and what happens when that pipeline breaks?**
6. **What is the total cost — licence, infrastructure, and human attention?**

> **Every additional datastore is a permanent tax.** Two is usually fine. Six is a platform team you do not have.

---

## 10.11 Polyglot persistence — done properly

A realistic mature architecture:

```
┌──────────────────────────────────────────────────────────────┐
│                      Application                             │
└───┬─────────┬──────────┬──────────┬──────────┬───────────────┘
    │         │          │          │          │
┌───▼────┐┌───▼────┐┌────▼─────┐┌───▼─────┐┌───▼──────────┐
│Postgres││ Redis  ││Elastic-  ││ S3/Blob ││ ClickHouse   │
│        ││        ││search    ││         ││              │
│SYSTEM  ││ cache  ││ derived  ││ videos, ││ analytics    │
│OF      ││sessions││ search   ││ docs,   ││ (derived)    │
│RECORD  ││ rate   ││ index    ││ exports ││              │
│        ││ limits ││(derived) ││         ││              │
└────────┘└────────┘└──────────┘└─────────┘└──────────────┘
     ▲         ▲          ▲                       ▲
     │         │          │                       │
  SOURCE    DISPOSABLE  DERIVED               DERIVED
  OF TRUTH             (rebuildable)         (rebuildable)
```

**The critical discipline: label every store.**

| Label | Meaning | Implication |
|-------|---------|-------------|
| **Source of truth** | The authoritative copy | Backed up, PITR, strongest consistency, most care |
| **Derived** | Built from the source | Can be rebuilt; does not need backups; may be stale |
| **Disposable** | Pure cache | Losing it is a performance event, not a data event |

> **The failure mode to avoid: two sources of truth for the same fact.** When Postgres says the session passed and MongoDB says it failed, there is no correct answer and no way to recover. Exactly one store owns each fact; everything else is derived from it, ideally through one pipeline (CDC or events — Chapter 06).

---

## 10.12 Common mistakes

1. **Choosing NoSQL for "scale" without measuring** — 500 writes/sec does not need Cassandra
2. **Using MongoDB as a relational database** — documents with ID references everywhere and `$lookup` joins. You wanted SQL.
3. **Unbounded arrays / unbounded partitions** — documents hit size limits; Cassandra partitions become unqueryable
4. **No schema validation** in a "schemaless" store — three shapes of the same entity in production
5. **Missing indexes** — a collection scan on 50 million documents
6. **Treating Elasticsearch (or Redis) as a system of record** — data loss is a matter of time
7. **Two sources of truth for the same fact** — unresolvable conflicts
8. **Monotonic shard/partition keys** — every write hits one hot node
9. **`w: 1` / `acks=1` style write concerns** on important data
10. **Ignoring the eventual-consistency contract** in the UI — the user saves and immediately sees the old value
11. **Six datastores in a five-person team** — nobody can operate any of them well
12. **Modelling entities instead of queries** in a query-first database — then discovering the new report is impossible

---

## 10.13 Architect's checklist

- [ ] Every access pattern is listed **before** choosing a NoSQL data model
- [ ] For each store: is it source of truth, derived, or disposable? Written down.
- [ ] Exactly one owner for each fact; derived stores have a defined rebuild procedure
- [ ] Consistency model per store understood and accepted by the business
- [ ] Write concern / consistency level set explicitly, not left at default
- [ ] Partition/shard key distributes evenly and matches queries; no monotonic keys
- [ ] All partitions/documents/arrays bounded, with a bucketing strategy if needed
- [ ] Schema validation enabled even in "schemaless" stores
- [ ] Indexes exist for every query path; verified with explain output
- [ ] Redis: `maxmemory` and eviction policy set; persistence configured to match the use
- [ ] Backups and a **tested** restore for every source-of-truth store
- [ ] Someone on the team can operate each store at 3 AM — or it is managed
- [ ] "Could PostgreSQL do this?" was asked and answered in writing

---

## 10.14 Self-test

1. Name the five NoSQL families, one example of each, and the access pattern each serves.
2. "SQL models your data; NoSQL models your ___." Complete and explain.
3. Give four things PostgreSQL now does that used to require a separate NoSQL store.
4. When should you embed in MongoDB and when should you reference? Give the four rules.
5. What is the unbounded-array anti-pattern and how do you fix it?
6. Explain Cassandra's "one table per query". Why is duplication correct there?
7. What is a Cassandra tombstone, and why is a delete-heavy workload an anti-pattern?
8. What does `w: "majority"` + `readConcern: "majority"` give you, and what does `w: 1` risk?
9. Why is Redis unsafe for distributed locks where correctness matters? What should you use?
10. What is the difference between a source-of-truth, a derived, and a disposable store?
11. Why must Elasticsearch never be a system of record?
12. Give six questions to ask before adding a new datastore to an architecture.

---

## 10.15 Key takeaways

- **NoSQL = purpose-built.** Each family trades something SQL gives you for something specific.
- **SQL models data; NoSQL models queries.** List every access pattern *before* you model.
- **PostgreSQL is the correct default** — and now covers documents, search, geo, time-series, vectors and queues
- **Add a datastore only for a named access pattern it serves dramatically better**, and say who operates it
- **Label every store: source of truth, derived, or disposable.** Never two sources of truth for one fact.
- **Bounded partitions, bounded documents, bounded arrays** — unbounded growth is the universal NoSQL killer
- **Set write/read concerns explicitly.** Defaults are tuned for benchmarks, not for your money.
- **Redis is a cache with superpowers** — treat it as wipeable unless you deliberately configure otherwise
- **Elasticsearch and analytics stores are derived indexes**, always rebuildable
- **Every extra datastore is a permanent operational tax.** Count them honestly.

---

**Next:** [Chapter 11 — Caching](11-caching.md)
