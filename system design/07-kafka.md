# Chapter 07 — Kafka 🟡

> Even if you never run Kafka in production, you must be able to draw its mental model on a whiteboard and explain how it differs from a queue.
> This is one of the most common "do you actually know distributed systems?" conversations you will have.

---

## 7.0 The one idea

**Kafka is not a message queue. Kafka is a distributed, append-only, replayable log.**

```
A QUEUE                          A LOG
┌───┬───┬───┬───┐               ┌───┬───┬───┬───┬───┬───┬───┐
│ 4 │ 3 │ 2 │ 1 │ → consumer    │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ ...
└───┴───┴───┴───┘               └───┴───┴───┴───┴───┴───┴───┘
message consumed = deleted        ▲       ▲           ▲
                                  │       │           │
                              Consumer  Consumer   Consumer
                              group A   group B    group C
                              (offset 1)(offset 3) (offset 6)

                       Nothing is deleted on read.
                       Each reader keeps its own position.
```

Everything else about Kafka follows from this. Once you truly internalise "it is a log, and consumers hold a bookmark", the rest of the API makes sense.

---

## 7.1 Core concepts

### Topic

A named stream of records. Like a table name, or a folder. `orders`, `verification-events`, `clickstream`.

### Partition ⭐

**A topic is split into partitions. This is where all the power and all the constraints come from.**

```
Topic: "orders"  (3 partitions)

Partition 0:  ┌───┬───┬───┬───┬───┐
              │ 0 │ 1 │ 2 │ 3 │ 4 │  ← offsets, strictly ordered
              └───┴───┴───┴───┴───┘
Partition 1:  ┌───┬───┬───┐
              │ 0 │ 1 │ 2 │
              └───┴───┴───┘
Partition 2:  ┌───┬───┬───┬───┬───┬───┐
              │ 0 │ 1 │ 2 │ 3 │ 4 │ 5 │
              └───┴───┴───┴───┴───┴───┘
```

**Three critical facts:**

1. **Ordering is guaranteed within a partition, and only within a partition.** There is no global order across a topic.
2. **Partitions are the unit of parallelism.** 3 partitions = at most 3 consumers in a group doing useful work. A 4th consumer sits idle.
3. **Partition assignment is by key:** `partition = hash(key) % num_partitions`. No key → round-robin (and therefore no ordering guarantee at all for that record).

```python
# Same key → same partition → strict ordering for that entity
producer.send("orders", key=b"customer_42", value=order_created)
producer.send("orders", key=b"customer_42", value=order_paid)      # same partition
producer.send("orders", key=b"customer_42", value=order_shipped)   # same partition
# → customer_42's events are ALWAYS processed in order.
# customer_99's events may interleave. That is fine and expected.
```

> **This is the most important practical decision you make with Kafka: the key.** Choose it so that (a) things that must be ordered together share a key, and (b) the keys distribute evenly.

### Offset

A monotonically increasing integer identifying a record's position in a partition. **Offsets are per-partition, not global.**

The consumer stores "I have processed up to offset 5,832 in partition 1". That stored position is the **committed offset**, kept in an internal Kafka topic called `__consumer_offsets`.

Because the consumer owns its position:
- Reset it to 0 → **reprocess everything**
- Reset to a timestamp → **reprocess the last 2 hours**
- Add a new application → it reads the whole history from the beginning

### Producer

Writes records. Key settings you must understand:

```python
producer = KafkaProducer(
    bootstrap_servers=["kafka-1:9092", "kafka-2:9092", "kafka-3:9092"],

    acks="all",                    # 0 = fire and forget (data loss)
                                   # 1 = leader only  (loss if leader dies before replication)
                                   # all = all in-sync replicas  ← USE THIS for anything that matters

    enable_idempotence=True,       # dedupes producer retries → no duplicates from retries
    retries=2147483647,            # retry forever (bounded by delivery.timeout.ms)
    delivery_timeout_ms=120_000,
    max_in_flight_requests_per_connection=5,   # ≤5 keeps ordering WHEN idempotence is on

    compression_type="lz4",        # 3-5× smaller; lz4/snappy fast, zstd smaller, gzip slow
    linger_ms=10,                  # wait up to 10 ms to batch → huge throughput win
    batch_size=32_768,
)
```

> **`acks=all` + `enable_idempotence=True` is the correct default for business data.** `acks=1` is a silent data-loss setting that looks fine until the day a leader fails.

### Consumer and Consumer Group ⭐

```
Topic "orders" with 4 partitions

CONSUMER GROUP "billing"          CONSUMER GROUP "analytics"
┌──────────┐                      ┌──────────┐
│Consumer A│ ← P0, P1             │Consumer X│ ← P0, P1, P2, P3
├──────────┤                      └──────────┘
│Consumer B│ ← P2, P3
└──────────┘

Both groups receive EVERY message independently.
Within a group, each partition goes to exactly ONE consumer.
```

**The rules:**
- Each partition is assigned to exactly one consumer **within a group**
- Different groups are completely independent — each has its own offsets
- **Consumers in a group > partitions → the extras are idle.** Partition count is your parallelism ceiling.
- Adding/removing a consumer triggers a **rebalance**

### Rebalancing 🟡

When group membership changes, partitions are reassigned.

**The classic problem (eager/"stop-the-world" rebalancing):** every consumer stops, all assignments are revoked, then everything is reassigned. During this, **no one consumes**. With slow consumers or frequent restarts, you can spend more time rebalancing than working.

**Fixes to know:**

| Setting / feature | Effect |
|---|---|
| `partition.assignment.strategy=CooperativeStickyAssignor` | **Incremental rebalancing** — only the moving partitions pause. Use this. |
| `group.instance.id` (static membership) | A restarting consumer keeps its partitions — no rebalance for a rolling deploy |
| `max.poll.interval.ms` | If processing takes longer than this, the consumer is considered dead and kicked out. **The #1 cause of rebalance loops.** |
| `session.timeout.ms` / `heartbeat.interval.ms` | Failure detection window |

> **Classic production bug:** a consumer processes each message for 6 minutes; `max.poll.interval.ms` defaults to 5 minutes. Kafka assumes the consumer died, rebalances, redelivers the message to another consumer, which also takes 6 minutes... The group never makes progress and the logs are full of rebalances. **Fix:** raise `max.poll.interval.ms`, lower `max.poll.records`, or move the slow work to a thread pool and keep polling.

### Broker, Cluster, Replication

```
                    Topic "orders", partition 0, replication.factor=3

    Broker 1                Broker 2                Broker 3
   ┌─────────┐            ┌─────────┐            ┌─────────┐
   │ P0      │            │ P0      │            │ P0      │
   │ LEADER  │───────────►│FOLLOWER │            │FOLLOWER │
   │         │────────────────────────────────► │         │
   └─────────┘            └─────────┘            └─────────┘
        ▲                                              
        │  all reads AND writes for P0 go to the leader
   Producers/Consumers
```

- **Leader** handles all reads and writes for a partition
- **Followers** replicate. If a leader dies, a follower is promoted.
- **ISR (In-Sync Replicas)** — replicas that are caught up. A write with `acks=all` waits for all ISR members.
- **`min.insync.replicas=2`** with `replication.factor=3`: tolerate one broker down and still accept writes; if two are down, **refuse writes rather than risk data loss.** This pairing is the standard production configuration.

Different partitions have different leaders, spread across brokers — that is how the cluster balances load.

---

## 7.2 Retention and Compaction 🟡

### Time/size-based retention (the default)

```properties
retention.ms=604800000        # keep 7 days
retention.bytes=10737418240   # or 10 GB per partition, whichever hits first
```

Old segments are deleted. Simple.

### Log compaction ⭐ (the underrated feature)

Keep **only the latest value for each key**, forever.

```
BEFORE compaction
  offset:  0        1        2        3        4        5
  key:     user_1   user_2   user_1   user_3   user_2   user_1
  value:   {A}      {B}      {A'}     {C}      {B'}     {A''}

AFTER compaction
  key:     user_3   user_2   user_1
  value:   {C}      {B'}     {A''}
```

**Why this is powerful:** the topic becomes a **durable key-value snapshot** that can rebuild state from scratch, without unbounded growth.

```properties
cleanup.policy=compact
# or both: keep 7 days of full history AND a compacted snapshot beyond that
cleanup.policy=compact,delete
```

**Uses:**
- A service's full current state (rebuild a cache or a materialised view on startup)
- Configuration topics
- CDC "current row state" topics
- Kafka's own `__consumer_offsets` is a compacted topic

**Tombstones:** publishing `key=X, value=null` marks X for deletion during compaction. This is how you delete from a compacted topic — and it is also how you satisfy GDPR deletion on a Kafka topic.

---

## 7.3 Delivery guarantees in Kafka

### At-most-once

```python
consumer = KafkaConsumer(enable_auto_commit=True, auto_commit_interval_ms=1000)
for msg in consumer:
    process(msg)      # offset may be committed BEFORE this finishes → loss on crash
```

### At-least-once ⭐ (use this)

```python
consumer = KafkaConsumer("orders", group_id="billing", enable_auto_commit=False)
for msg in consumer:
    process(msg)               # do the work FIRST
    consumer.commit()          # commit only after success
    # crash between the two → the message is redelivered → consumer must be idempotent
```

Commit in **batches** for throughput (commit every N messages or every M seconds), not after every single message — offset commits are network calls.

### Exactly-once semantics (EOS) — precisely what it is

Kafka EOS works for the **consume → process → produce** loop, entirely inside Kafka:

```java
producer.initTransactions();
while (true) {
    var records = consumer.poll(Duration.ofMillis(100));
    producer.beginTransaction();
    for (var record : records) {
        producer.send(new ProducerRecord<>("output-topic", transform(record)));
    }
    producer.sendOffsetsToTransaction(currentOffsets(), consumer.groupMetadata());
    producer.commitTransaction();      // output records AND offsets commit atomically
}
```

Consumers of `output-topic` must set `isolation.level=read_committed`.

> **The limit, stated plainly:** the moment you write to Postgres, call an HTTP API, or send an email inside that loop, EOS no longer covers you. You are back to at-least-once plus idempotency (Chapter 05/06). Anyone who says "Kafka gives us exactly-once so we don't need idempotency" is mistaken, and it is worth correcting politely.

---

## 7.4 Consumer lag — the metric that matters

```
Lag = (latest offset in partition) − (consumer's committed offset)
```

| Lag pattern | Meaning | Action |
|-------------|---------|--------|
| Near zero, stable | Healthy | — |
| Small, oscillating with traffic | Normal | — |
| **Steadily increasing** | Consumers cannot keep up | Add consumers (up to partition count), optimise processing, or add partitions |
| Sudden spike then recovery | A burst, or a consumer restart | Usually fine; check if recovery time meets SLA |
| Flat and high | Consumer is stuck/crashed | Check logs, rebalances, poison message |

**Lag is the single best health metric for a Kafka consumer.** Alert on it. Also track **lag in time** (how old is the oldest unprocessed record) — 1 million records of a fast topic may be 10 seconds, while 1,000 records of a slow topic may be an hour.

Tools: Burrow, Kafka Exporter + Prometheus, `kafka-consumer-groups.sh --describe`, Confluent Control Center.

---

## 7.5 Partition count — the decision you cannot easily undo

```
More partitions:
  ✅ more parallelism (more consumers can work)
  ✅ higher throughput
  ❌ more open file handles and memory on brokers
  ❌ longer leader-election time if a broker fails
  ❌ more end-to-end latency (more batches)
  ❌ ORDERING BREAKS if you increase them later
```

**Why increasing partitions is dangerous:** `hash(key) % N` changes when N changes. `customer_42` moves from partition 1 to partition 4. Its old events sit in partition 1 and new ones in partition 4 — **and those are no longer ordered relative to each other.** Any consumer relying on per-key ordering is now subtly broken.

**Sizing guidance:**

```
partitions = max(
    target_throughput / throughput_per_partition,   # ~10 MB/s per partition is a safe planning figure
    desired_consumer_parallelism
) × growth_headroom (2-3×)
```

Practical defaults: **6–12 partitions** for a normal business topic; 30–100 for a genuinely high-volume stream. Do not create 1,000 partitions "just in case" — brokers pay for every one.

**If you must reshard:** create a new topic with the new partition count, dual-write or replay into it, migrate consumers, retire the old topic. Treat it as a migration project, not a config change.

---

## 7.6 Kafka Connect, Streams and ksqlDB ⚪🟡

### Kafka Connect

A framework for moving data in and out of Kafka **without writing code** — just configuration.

```json
{
  "name": "postgres-orders-source",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.dbname": "shop",
    "table.include.list": "public.orders,public.outbox",
    "plugin.name": "pgoutput",
    "topic.prefix": "shop"
  }
}
```

- **Source connectors** — database (Debezium/CDC), files, S3, MQTT, Salesforce...
- **Sink connectors** — Elasticsearch, S3, Snowflake, BigQuery, JDBC...

**Debezium** is the important one to know by name: it tails the database WAL and turns every row change into a Kafka event. It is the production answer for CDC and for a low-latency Outbox relay (Chapter 06).

### Kafka Streams 🟡

A Java library (not a cluster) for stream processing: filter, map, join, aggregate, window.

```java
StreamsBuilder builder = new StreamsBuilder();
builder.stream("verification-events")
       .filter((k, v) -> v.getOutcome().equals("FAILED"))
       .groupBy((k, v) -> v.getTenantId())
       .windowedBy(TimeWindows.ofSizeWithNoGrace(Duration.ofMinutes(5)))
       .count()
       .filter((tenant, count) -> count > 50)      // possible attack
       .toStream()
       .to("fraud-alerts");
```

Key concepts worth recognising: **KStream** (a stream of events) vs **KTable** (a changelog interpreted as current state), **stream-table joins**, **windowing** (tumbling, hopping, session), and **state stores** (local RocksDB backed by a compacted Kafka topic, which is how it survives restarts).

### ksqlDB ⚪

SQL over streams.

```sql
CREATE STREAM failed_verifications AS
  SELECT tenant_id, session_id, score
  FROM verification_events
  WHERE outcome = 'FAILED'
  EMIT CHANGES;
```

Lovely for prototyping and for analysts. Awareness is enough.

### Alternatives to know by name ⚪

**Apache Flink** — the current heavyweight for serious stream processing (better windowing, event-time handling, exactly-once state, and it works beyond Kafka). If someone says "we need real stream processing at scale", Flink is the usual answer today.

---

## 7.7 KRaft — Kafka without ZooKeeper 🟡

Historically Kafka needed ZooKeeper for metadata and controller election. **KRaft** (Kafka Raft) replaces it: Kafka runs its own Raft-based consensus internally.

- Simpler operations (one system instead of two)
- Faster failover and much better scaling of partition counts
- ZooKeeper mode is removed in Kafka 4.x

**Practical takeaway:** any new cluster should be KRaft. If you meet a ZooKeeper-based cluster, you are looking at an older deployment.

---

## 7.8 When to use Kafka — and when not to

### ✅ Good fits

| Use case | Why Kafka |
|----------|-----------|
| **Event backbone** for many services | One publish, many independent consumers, each at its own pace |
| **Very high volume** (100K+ msg/s) | Sequential disk writes + zero-copy = extremely fast |
| **Replay / reprocessing** | Fix a bug, reset the offset, reprocess three days |
| **Stream processing** | Windowed aggregation, joins, real-time analytics |
| **Log/metric aggregation** | Firehose from thousands of sources |
| **CDC pipelines** | Debezium + Kafka is the industry standard |
| **Bootstrapping new services** | A new service replays history to build its own state |
| **Event sourcing at scale** | Ordered, durable, replayable — a natural fit |

### ❌ Poor fits

| Situation | Why not | Better choice |
|-----------|---------|---------------|
| Task queue with per-message retry | No per-message ack/nack/reject; retries mean extra topics | **RabbitMQ**, SQS, Celery |
| Request/response RPC | Wrong shape entirely | HTTP, gRPC |
| Complex routing rules | Kafka routing is just "topic + key" | RabbitMQ topic exchanges |
| Low volume (< 1,000 msg/s) | Operating a cluster costs more than the problem | RabbitMQ, SQS, or a DB table |
| Priority queues | Kafka has no message priority | RabbitMQ |
| Delayed / scheduled delivery | Not supported natively | RabbitMQ TTL+DLX, SQS delay, a scheduler |
| Small team, no platform engineers | Kafka is genuinely demanding to operate well | **Managed Kafka** (Confluent Cloud, MSK, Event Hubs) or a simpler broker |

> **The honest architect's take:** Kafka is superb at what it is for. It is also the most over-adopted piece of infrastructure of the last decade. **If you cannot name a concrete need for replay, high throughput, or many independent consumers of the same stream, you probably want RabbitMQ or a managed queue** — and you will have a much quieter life. If you do need Kafka, strongly prefer a managed offering unless you have platform engineers.

---

## 7.9 Common mistakes

1. **`acks=1`** — silent data loss when a leader fails at the wrong moment
2. **Not enabling idempotent producers** — retries create duplicates
3. **`enable_auto_commit=True`** with real work — commits offsets before processing finishes
4. **Increasing partitions on a keyed topic** — silently breaks per-key ordering
5. **Too many partitions** — slow failover, broker memory pressure, higher latency
6. **`max.poll.interval.ms` too low for slow processing** — endless rebalance loop
7. **Using Kafka as a task queue** — fighting the tool; no per-message retry or priority
8. **No consumer lag alerting** — you find out from users
9. **Believing EOS covers external systems** — it does not
10. **No schema registry** — a producer change breaks four consumers on a Tuesday
11. **Publishing without a key** when ordering matters — round-robin destroys ordering
12. **Running a self-managed cluster with no Kafka expertise** — it will be fine until it very much is not

---

## 7.10 Architect's checklist

- [ ] Partition key chosen so ordering-sensitive records share a key and keys distribute evenly
- [ ] Partition count sized with 2–3× headroom (increasing it later breaks ordering)
- [ ] `replication.factor=3`, `min.insync.replicas=2`, `acks=all` for business data
- [ ] Idempotent producer enabled
- [ ] Manual offset commits, after processing, in batches
- [ ] Consumers idempotent (Chapter 06 Inbox pattern)
- [ ] `CooperativeStickyAssignor` + static membership for smooth deploys
- [ ] `max.poll.interval.ms` > worst-case processing time for a poll batch
- [ ] Retention policy set deliberately (time, size, or compaction)
- [ ] Schema registry with full compatibility enforcement
- [ ] Consumer lag monitored and alerted (in records **and** in time)
- [ ] Retry-topic and DLQ-topic strategy defined
- [ ] Managed service considered before self-hosting
- [ ] GDPR deletion strategy defined (compaction + tombstones, or crypto-shredding)

---

## 7.11 Self-test

1. Explain in one sentence why Kafka is not a queue.
2. What exactly is guaranteed about ordering in Kafka? What is not?
3. Why is the partition key the most important design decision?
4. Why does increasing partitions break ordering? Walk through it with a key.
5. You have 4 partitions and 6 consumers in a group. What happens?
6. What is a rebalance, why is it disruptive, and name three ways to reduce the pain.
7. Explain `acks=all` + `min.insync.replicas=2` + `replication.factor=3`. What happens when two brokers die?
8. What is log compaction, and what problem does it solve? What is a tombstone?
9. State precisely what Kafka's exactly-once semantics covers and what it does not.
10. How do you measure consumer lag, and why measure it in time as well as records?
11. Give four use cases where Kafka is the right choice and four where it is wrong.
12. What is Debezium, and where does it fit with the Outbox pattern?

---

## 7.12 Key takeaways

- **Kafka is a distributed, replayable, ordered log.** Consumers hold their own bookmark.
- **Ordering is per-partition only.** Key your messages so related events land together.
- **Partitions are the parallelism ceiling** — and the count is hard to change safely
- **`acks=all` + idempotent producer + manual commits after processing** is the production baseline
- **Replay is the killer feature** — it enables bug recovery, new consumers and backfills
- **Log compaction turns a topic into a durable key-value snapshot**
- **Consumer lag is the health metric.** Alert on it.
- **EOS is real but narrow.** Outside Kafka, you still need idempotency.
- **Kafka is over-adopted.** Name your replay/throughput/fan-out need, or use a simpler broker — and prefer managed Kafka if you do need it.

---

**Next:** [Chapter 08 — API Architecture](08-api-architecture.md)
