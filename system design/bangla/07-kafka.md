# অধ্যায় ০৭ — Kafka 🟡

> আপনি production-এ কখনো Kafka না চালালেও, আপনাকে whiteboard-এ এর মানসিক মডেলটা আঁকতে পারতে হবে আর ব্যাখ্যা করতে পারতে হবে এটা একটা queue থেকে কীভাবে আলাদা।
> "আপনি কি আসলেই distributed systems জানেন?" — এই আলোচনাগুলোর মধ্যে এটাই সবচেয়ে সাধারণ।

---

## ৭.০ একটাই ধারণা

**Kafka কোনো message queue নয়। Kafka একটা distributed, append-only, replay করা যায় এমন log।**

```
একটা QUEUE                       একটা LOG
┌───┬───┬───┬───┐               ┌───┬───┬───┬───┬───┬───┬───┐
│ 4 │ 3 │ 2 │ 1 │ → consumer    │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ ...
└───┴───┴───┴───┘               └───┴───┴───┴───┴───┴───┴───┘
message গ্রহণ = মুছে যাওয়া          ▲       ▲           ▲
                                  │       │           │
                              Consumer  Consumer   Consumer
                              group A   group B    group C
                              (offset 1)(offset 3) (offset 6)

                       পড়লে কিছুই মুছে যায় না।
                       প্রতিটা পাঠক নিজের অবস্থান নিজে রাখে।
```

Kafka-র বাকি সবকিছুই এখান থেকে আসে। "এটা একটা log, আর consumer-রা একটা বুকমার্ক ধরে রাখে" — এটা সত্যিই আত্মস্থ করলে API-র বাকি সব অর্থবহ হয়ে যায়।

---

## ৭.১ মূল ধারণা

### Topic

Record-এর একটা নামযুক্ত ধারা। একটা table-এর নাম বা একটা ফোল্ডারের মতো। `orders`, `verification-events`, `clickstream`।

### Partition ⭐

**একটা topic partition-এ ভাগ হয়। সব শক্তি আর সব সীমাবদ্ধতা এখান থেকেই আসে।**

```
Topic: "orders"  (৩টা partition)

Partition 0:  ┌───┬───┬───┬───┬───┐
              │ 0 │ 1 │ 2 │ 3 │ 4 │  ← offset, কঠোরভাবে সাজানো
              └───┴───┴───┴───┴───┘
Partition 1:  ┌───┬───┬───┐
              │ 0 │ 1 │ 2 │
              └───┴───┴───┘
Partition 2:  ┌───┬───┬───┬───┬───┬───┐
              │ 0 │ 1 │ 2 │ 3 │ 4 │ 5 │
              └───┴───┴───┴───┴───┴───┘
```

**তিনটা গুরুত্বপূর্ণ সত্য:**

১. **ক্রম একটা partition-এর ভেতরেই নিশ্চিত, আর শুধু একটা partition-এর ভেতরেই।** একটা topic জুড়ে কোনো বৈশ্বিক ক্রম নেই।
২. **Partition-ই সমান্তরালতার একক।** ৩টা partition = একটা group-এ সর্বোচ্চ ৩ জন consumer কাজের কাজ করবে। ৪র্থ consumer বসে থাকবে।
৩. **Partition বরাদ্দ হয় key দিয়ে:** `partition = hash(key) % num_partitions`। Key না থাকলে → round-robin (আর তাই ওই record-এর জন্য ক্রমের কোনো নিশ্চয়তাই নেই)।

```python
# একই key → একই partition → ওই entity-র জন্য কঠোর ক্রম
producer.send("orders", key=b"customer_42", value=order_created)
producer.send("orders", key=b"customer_42", value=order_paid)      # একই partition
producer.send("orders", key=b"customer_42", value=order_shipped)   # একই partition
# → customer_42-এর event সবসময়ই ক্রমে process হয়।
# customer_99-এর event মাঝে মিশে যেতে পারে। সেটা ঠিক আছে আর প্রত্যাশিত।
```

> **Kafka-র সাথে আপনার নেওয়া সবচেয়ে গুরুত্বপূর্ণ ব্যবহারিক সিদ্ধান্ত: key।** এমনভাবে বাছুন যাতে (ক) যেগুলো একসাথে সাজানো থাকতেই হবে সেগুলো একটা key ভাগ করে, আর (খ) key গুলো সমানভাবে ছড়ায়।

### Offset

একটা ক্রমবর্ধমান পূর্ণসংখ্যা, যা একটা partition-এ একটা record-এর অবস্থান চিহ্নিত করে। **Offset প্রতি partition-এ, বৈশ্বিক নয়।**

Consumer জমা রাখে "আমি partition 1-এ offset ৫,৮৩২ পর্যন্ত process করেছি"। ওই জমানো অবস্থানটাই **committed offset**, যেটা `__consumer_offsets` নামের একটা ভেতরের Kafka topic-এ থাকে।

Consumer যেহেতু নিজের অবস্থানের মালিক:
- এটা ০-তে reset করুন → **সবকিছু আবার process করুন**
- একটা timestamp-এ reset করুন → **গত ২ ঘণ্টা আবার process করুন**
- একটা নতুন application যোগ করুন → এটা শুরু থেকে পুরো ইতিহাস পড়ে

### Producer

Record লেখে। যে setting গুলো আপনাকে বুঝতেই হবে:

```python
producer = KafkaProducer(
    bootstrap_servers=["kafka-1:9092", "kafka-2:9092", "kafka-3:9092"],

    acks="all",                    # 0 = পাঠিয়ে ভুলে যাও (data হারায়)
                                   # 1 = শুধু leader (replication-এর আগে leader মরলে হারায়)
                                   # all = সব in-sync replica  ← গুরুত্বপূর্ণ যা কিছুর জন্য এটাই

    enable_idempotence=True,       # producer-এর retry dedupe করে → retry থেকে কোনো duplicate নয়
    retries=2147483647,            # চিরকাল retry (delivery.timeout.ms দিয়ে সীমাবদ্ধ)
    delivery_timeout_ms=120_000,
    max_in_flight_requests_per_connection=5,   # idempotence চালু থাকলে ≤৫ ক্রম রাখে

    compression_type="lz4",        # ৩-৫× ছোট; lz4/snappy দ্রুত, zstd ছোট, gzip ধীর
    linger_ms=10,                  # batch করতে ১০ ms পর্যন্ত অপেক্ষা → throughput-এ বিশাল লাভ
    batch_size=32_768,
)
```

> **Business data-র জন্য `acks=all` + `enable_idempotence=True`-ই সঠিক default।** `acks=1` একটা নীরব data-হারানোর setting, যেটা দেখতে ঠিকই লাগে — যতদিন না একদিন একটা leader fail করে।

### Consumer আর Consumer Group ⭐

```
৪টা partition সহ "orders" topic

CONSUMER GROUP "billing"          CONSUMER GROUP "analytics"
┌──────────┐                      ┌──────────┐
│Consumer A│ ← P0, P1             │Consumer X│ ← P0, P1, P2, P3
├──────────┤                      └──────────┘
│Consumer B│ ← P2, P3
└──────────┘

দুটো group-ই স্বাধীনভাবে প্রতিটা message পায়।
একটা group-এর ভেতরে প্রতিটা partition ঠিক একজন consumer পায়।
```

**নিয়মগুলো:**
- প্রতিটা partition **একটা group-এর ভেতরে** ঠিক একজন consumer-কে বরাদ্দ হয়
- আলাদা group সম্পূর্ণ স্বাধীন — প্রত্যেকের নিজের offset
- **Group-এ consumer > partition → বাড়তিগুলো বসে থাকে।** Partition-এর সংখ্যাই আপনার সমান্তরালতার ছাদ।
- একজন consumer যোগ/বাদ দিলে একটা **rebalance** হয়

### Rebalancing 🟡

Group-এর সদস্যপদ বদলালে partition গুলো আবার বরাদ্দ হয়।

**ক্লাসিক সমস্যা (eager/"stop-the-world" rebalancing):** প্রতিটা consumer থামে, সব বরাদ্দ প্রত্যাহার হয়, তারপর সবকিছু আবার বরাদ্দ হয়। এই সময়ে **কেউ consume করে না**। ধীর consumer বা ঘন ঘন restart থাকলে আপনি কাজের চেয়ে বেশি সময় rebalance-এ কাটাতে পারেন।

**যে সমাধানগুলো জানবেন:**

| Setting / feature | প্রভাব |
|---|---|
| `partition.assignment.strategy=CooperativeStickyAssignor` | **Incremental rebalancing** — শুধু যেগুলো সরছে সেই partition গুলো থামে। এটাই ব্যবহার করুন। |
| `group.instance.id` (static membership) | Restart হওয়া একজন consumer তার partition রাখে — একটা rolling deploy-এ কোনো rebalance নেই |
| `max.poll.interval.ms` | Process করতে এর চেয়ে বেশি সময় লাগলে consumer-কে মৃত ধরে বের করে দেওয়া হয়। **Rebalance লুপের ১ নম্বর কারণ।** |
| `session.timeout.ms` / `heartbeat.interval.ms` | ব্যর্থতা শনাক্তের জানালা |

> **ক্লাসিক production bug:** একজন consumer প্রতিটা message ৬ মিনিট ধরে process করে; `max.poll.interval.ms`-এর default ৫ মিনিট। Kafka ধরে নেয় consumer মরে গেছে, rebalance করে, message-টা আরেকজন consumer-কে দেয়, যারও ৬ মিনিট লাগে... Group কখনোই এগোয় না আর log rebalance-এ ভরে যায়। **সমাধান:** `max.poll.interval.ms` বাড়ান, `max.poll.records` কমান, অথবা ধীর কাজটা একটা thread pool-এ সরান আর poll করতে থাকুন।

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
        │  P0-র সব read আর write leader-এ যায়
   Producer/Consumer
```

- **Leader** একটা partition-এর সব read আর write সামলায়
- **Follower** গুলো replicate করে। Leader মরলে একটা follower পদোন্নতি পায়।
- **ISR (In-Sync Replicas)** — যে replica গুলো ধরে ফেলেছে। `acks=all` সহ একটা write সব ISR সদস্যের জন্য অপেক্ষা করে।
- `replication.factor=3` সহ **`min.insync.replicas=2`**: একটা broker বন্ধ থাকলেও write নিতে পারবে; দুটো বন্ধ থাকলে **data হারানোর ঝুঁকি নেওয়ার বদলে write প্রত্যাখ্যান করবে।** এই জোড়াটাই প্রচলিত production configuration।

আলাদা partition-এর আলাদা leader থাকে, broker-দের মধ্যে ছড়ানো — এভাবেই cluster load-এর ভারসাম্য রাখে।

---

## ৭.২ Retention আর Compaction 🟡

### সময়/আকার-ভিত্তিক retention (default)

```properties
retention.ms=604800000        # ৭ দিন রাখো
retention.bytes=10737418240   # অথবা প্রতি partition-এ ১০ GB, যেটা আগে আসে
```

পুরনো segment মুছে যায়। সহজ।

### Log compaction ⭐ (কম মূল্যায়িত feature)

প্রতিটা key-র জন্য **শুধু সর্বশেষ মানটা** রাখুন, চিরকাল।

```
compaction-এর আগে
  offset:  0        1        2        3        4        5
  key:     user_1   user_2   user_1   user_3   user_2   user_1
  value:   {A}      {B}      {A'}     {C}      {B'}     {A''}

compaction-এর পরে
  key:     user_3   user_2   user_1
  value:   {C}      {B'}     {A''}
```

**এটা কেন শক্তিশালী:** topic-টা একটা **টেকসই key-value snapshot** হয়ে যায়, যেটা শূন্য থেকে state আবার বানাতে পারে, সীমাহীন বৃদ্ধি ছাড়াই।

```properties
cleanup.policy=compact
# অথবা দুটোই: ৭ দিনের পূর্ণ ইতিহাস রাখো আর তার বাইরে একটা compacted snapshot
cleanup.policy=compact,delete
```

**ব্যবহার:**
- একটা service-এর পুরো বর্তমান state (startup-এ একটা cache বা materialised view আবার বানানো)
- Configuration topic
- CDC-র "বর্তমান row-র state" topic
- Kafka-র নিজের `__consumer_offsets` একটা compacted topic

**Tombstone:** `key=X, value=null` publish করলে compaction-এর সময় X মুছে ফেলার জন্য চিহ্নিত হয়। একটা compacted topic থেকে এভাবেই আপনি মুছে ফেলেন — আর একটা Kafka topic-এ GDPR-এর মুছে ফেলার দাবি এভাবেই মেটান।

---

## ৭.৩ Kafka-তে delivery-র নিশ্চয়তা

### At-most-once

```python
consumer = KafkaConsumer(enable_auto_commit=True, auto_commit_interval_ms=1000)
for msg in consumer:
    process(msg)      # এটা শেষ হওয়ার আগেই offset commit হয়ে যেতে পারে → crash-এ হারায়
```

### At-least-once ⭐ (এটাই ব্যবহার করুন)

```python
consumer = KafkaConsumer("orders", group_id="billing", enable_auto_commit=False)
for msg in consumer:
    process(msg)               # আগে কাজটা করুন
    consumer.commit()          # সফল হওয়ার পরেই commit করুন
    # দুটোর মাঝে crash → message আবার আসে → consumer-কে idempotent হতে হবে
```

Throughput-এর জন্য **batch-এ** commit করুন (প্রতি N message বা প্রতি M সেকেন্ডে), প্রতিটা message-এর পর নয় — offset commit একটা network call।

### Exactly-once semantics (EOS) — ঠিক কী জিনিস

Kafka-র EOS **consume → process → produce** লুপের জন্য কাজ করে, পুরোপুরি Kafka-র ভেতরে:

```java
producer.initTransactions();
while (true) {
    var records = consumer.poll(Duration.ofMillis(100));
    producer.beginTransaction();
    for (var record : records) {
        producer.send(new ProducerRecord<>("output-topic", transform(record)));
    }
    producer.sendOffsetsToTransaction(currentOffsets(), consumer.groupMetadata());
    producer.commitTransaction();      // output record আর offset atomically commit হয়
}
```

`output-topic`-এর consumer-দের `isolation.level=read_committed` সেট করতে হবে।

> **সীমাটা, সোজাসুজি:** যে মুহূর্তে আপনি ওই লুপের ভেতরে Postgres-এ লেখেন, একটা HTTP API call করেন, বা একটা ইমেইল পাঠান, EOS আর আপনাকে ঢাকে না। আপনি আবার at-least-once + idempotency-তে ফিরে এসেছেন (অধ্যায় ০৫/০৬)। কেউ যদি বলেন "Kafka আমাদের exactly-once দেয় তাই আমাদের idempotency লাগে না", তিনি ভুল, আর ভদ্রভাবে শুধরে দেওয়ার মতো।

---

## ৭.৪ Consumer lag — যে metric-টা গুরুত্বপূর্ণ

```
Lag = (partition-এর সর্বশেষ offset) − (consumer-এর committed offset)
```

| Lag-এর ধরন | মানে | কী করবেন |
|-------------|---------|--------|
| প্রায় শূন্য, স্থিতিশীল | সুস্থ | — |
| ছোট, traffic-এর সাথে ওঠানামা | স্বাভাবিক | — |
| **ধারাবাহিকভাবে বাড়ছে** | Consumer তাল রাখতে পারছে না | Consumer যোগ করুন (partition-এর সংখ্যা পর্যন্ত), processing optimise করুন, বা partition যোগ করুন |
| হঠাৎ লাফ তারপর সেরে ওঠা | একটা ঝাঁকুনি, বা একটা consumer restart | সাধারণত ঠিক আছে; সেরে ওঠার সময় SLA মানছে কিনা দেখুন |
| সমতল আর উঁচু | Consumer আটকে গেছে/crash করেছে | Log, rebalance, poison message দেখুন |

**একটা Kafka consumer-এর জন্য lag-ই সবচেয়ে ভালো স্বাস্থ্য-metric।** এতে alert দিন। **সময়ে lag**-ও track করুন (সবচেয়ে পুরনো process-না-হওয়া record কত পুরনো) — একটা দ্রুত topic-এর ১০ লাখ record হয়তো ১০ সেকেন্ড, আর একটা ধীর topic-এর ১,০০০ record হয়তো এক ঘণ্টা।

টুল: Burrow, Kafka Exporter + Prometheus, `kafka-consumer-groups.sh --describe`, Confluent Control Center।

---

## ৭.৫ Partition-এর সংখ্যা — যে সিদ্ধান্ত সহজে ফেরানো যায় না

```
বেশি partition:
  ✅ বেশি সমান্তরালতা (বেশি consumer কাজ করতে পারে)
  ✅ বেশি throughput
  ❌ broker-এ বেশি open file handle আর memory
  ❌ একটা broker fail করলে leader-election-এ বেশি সময়
  ❌ বেশি end-to-end latency (বেশি batch)
  ❌ পরে বাড়ালে ORDERING ভেঙে যায়
```

**Partition বাড়ানো কেন বিপজ্জনক:** N বদলালে `hash(key) % N` বদলায়। `customer_42` partition 1 থেকে partition 4-এ সরে যায়। তার পুরনো event গুলো partition 1-এ আর নতুনগুলো partition 4-এ বসে — **আর সেগুলো আর একে অপরের সাপেক্ষে সাজানো নেই।** Per-key ordering-এর উপর নির্ভরশীল যে কোনো consumer এখন সূক্ষ্মভাবে ভাঙা।

**আকার নির্ধারণের নির্দেশনা:**

```
partition = max(
    লক্ষ্য_throughput / প্রতি_partition-এ_throughput,   # প্রতি partition-এ ~১০ MB/s একটা নিরাপদ পরিকল্পনার সংখ্যা
    কাঙ্ক্ষিত_consumer_সমান্তরালতা
) × বৃদ্ধির_headroom (২-৩×)
```

ব্যবহারিক default: একটা স্বাভাবিক business topic-এর জন্য **৬–১২টা partition**; সত্যিকারের উচ্চ-volume stream-এর জন্য ৩০–১০০। "যদি লাগে" বলে ১,০০০টা partition বানাবেন না — broker প্রতিটার দাম দেয়।

**যদি আবার shard করতেই হয়:** নতুন partition-সংখ্যা সহ একটা নতুন topic বানান, তাতে dual-write বা replay করুন, consumer সরান, পুরনো topic বাতিল করুন। একে একটা config পরিবর্তন নয়, একটা migration প্রজেক্ট হিসেবে দেখুন।

---

## ৭.৬ Kafka Connect, Streams আর ksqlDB ⚪🟡

### Kafka Connect

Kafka-তে data ঢোকানো আর বের করার একটা framework, **কোনো কোড না লিখেই** — শুধু configuration।

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

- **Source connector** — database (Debezium/CDC), ফাইল, S3, MQTT, Salesforce...
- **Sink connector** — Elasticsearch, S3, Snowflake, BigQuery, JDBC...

**Debezium** হলো নাম ধরে জানার মতো গুরুত্বপূর্ণটা: এটা database-এর WAL অনুসরণ করে আর প্রতিটা row-র পরিবর্তনকে একটা Kafka event-এ পরিণত করে। CDC-র জন্য আর একটা কম-latency-র Outbox relay-র জন্য এটাই production-এর উত্তর (অধ্যায় ০৬)।

### Kafka Streams 🟡

Stream processing-এর জন্য একটা Java library (কোনো cluster নয়): filter, map, join, aggregate, window।

```java
StreamsBuilder builder = new StreamsBuilder();
builder.stream("verification-events")
       .filter((k, v) -> v.getOutcome().equals("FAILED"))
       .groupBy((k, v) -> v.getTenantId())
       .windowedBy(TimeWindows.ofSizeWithNoGrace(Duration.ofMinutes(5)))
       .count()
       .filter((tenant, count) -> count > 50)      // সম্ভাব্য আক্রমণ
       .toStream()
       .to("fraud-alerts");
```

চিনে রাখার মতো মূল ধারণা: **KStream** (event-এর একটা ধারা) বনাম **KTable** (একটা changelog যাকে বর্তমান state হিসেবে ব্যাখ্যা করা হয়), **stream-table join**, **windowing** (tumbling, hopping, session), আর **state store** (স্থানীয় RocksDB, যার পেছনে একটা compacted Kafka topic, আর এভাবেই এটা restart-এ টিকে যায়)।

### ksqlDB ⚪

Stream-এর উপর SQL।

```sql
CREATE STREAM failed_verifications AS
  SELECT tenant_id, session_id, score
  FROM verification_events
  WHERE outcome = 'FAILED'
  EMIT CHANGES;
```

Prototype বানাতে আর বিশ্লেষকদের জন্য চমৎকার। পরিচিতিই যথেষ্ট।

### নাম ধরে জানার মতো বিকল্প ⚪

**Apache Flink** — গুরুতর stream processing-এর জন্য বর্তমান ভারী ওজনের খেলোয়াড় (ভালো windowing, event-time সামলানো, exactly-once state, আর এটা Kafka-র বাইরেও কাজ করে)। কেউ যদি বলেন "আমাদের scale-এ আসল stream processing দরকার", আজকের দিনে Flink-ই সাধারণ উত্তর।

---

## ৭.৭ KRaft — ZooKeeper ছাড়া Kafka 🟡

ঐতিহাসিকভাবে metadata আর controller election-এর জন্য Kafka-র ZooKeeper লাগত। **KRaft** (Kafka Raft) সেটা প্রতিস্থাপন করে: Kafka ভেতরে নিজের Raft-ভিত্তিক consensus চালায়।

- সহজ operation (দুটোর বদলে একটা সিস্টেম)
- দ্রুত failover আর partition-সংখ্যার অনেক ভালো scaling
- Kafka 4.x-এ ZooKeeper mode সরিয়ে ফেলা হয়েছে

**ব্যবহারিক সারকথা:** যে কোনো নতুন cluster KRaft হওয়া উচিত। একটা ZooKeeper-ভিত্তিক cluster দেখলে বুঝবেন সেটা একটা পুরনো deployment।

---

## ৭.৮ কখন Kafka ব্যবহার করবেন — আর কখন নয়

### ✅ ভালো মানায়

| ব্যবহারের ক্ষেত্র | Kafka কেন |
|----------|-----------|
| অনেক service-এর জন্য **event-এর মেরুদণ্ড** | একবার publish, অনেক স্বাধীন consumer, প্রত্যেকে নিজের গতিতে |
| **খুব উচ্চ volume** (১ লাখ+ msg/s) | ধারাবাহিক disk write + zero-copy = অত্যন্ত দ্রুত |
| **Replay / পুনঃপ্রক্রিয়াকরণ** | একটা bug ঠিক করুন, offset reset করুন, তিন দিন আবার process করুন |
| **Stream processing** | Windowed aggregation, join, real-time analytics |
| **Log/metric aggregation** | হাজার হাজার উৎস থেকে ঝর্ণাধারা |
| **CDC pipeline** | Debezium + Kafka শিল্পমান |
| **নতুন service চালু করা** | একটা নতুন service ইতিহাস replay করে নিজের state বানায় |
| **Scale-এ event sourcing** | সাজানো, টেকসই, replay করা যায় এমন — স্বাভাবিকভাবেই মানায় |

### ❌ খারাপ মানায়

| পরিস্থিতি | কেন নয় | ভালো পছন্দ |
|-----------|---------|---------------|
| প্রতি-message retry সহ task queue | প্রতি-message ack/nack/reject নেই; retry মানে বাড়তি topic | **RabbitMQ**, SQS, Celery |
| Request/response RPC | একদমই ভুল আকৃতি | HTTP, gRPC |
| জটিল routing-এর নিয়ম | Kafka-র routing শুধু "topic + key" | RabbitMQ-র topic exchange |
| কম volume (< ১,০০০ msg/s) | একটা cluster চালানোর খরচ সমস্যার চেয়ে বেশি | RabbitMQ, SQS, বা একটা DB table |
| Priority queue | Kafka-তে message-এর priority নেই | RabbitMQ |
| বিলম্বিত / নির্ধারিত delivery | নিজস্বভাবে সাপোর্ট করে না | RabbitMQ-র TTL+DLX, SQS delay, একটা scheduler |
| ছোট টিম, কোনো platform engineer নেই | Kafka ভালোভাবে চালানো সত্যিই দাবিদার | **Managed Kafka** (Confluent Cloud, MSK, Event Hubs) বা একটা সহজ broker |

> **সৎ আর্কিটেক্টের মত:** Kafka যা করার জন্য, তাতে এটা অসাধারণ। আবার এটা গত দশকের সবচেয়ে বেশি-গৃহীত infrastructure-ও। **আপনি যদি replay, উচ্চ throughput, বা একই stream-এর অনেক স্বাধীন consumer-এর একটা বাস্তব প্রয়োজনের নাম বলতে না পারেন, তাহলে সম্ভবত আপনার RabbitMQ বা একটা managed queue দরকার** — আর আপনার জীবনটা অনেক শান্ত হবে। সত্যিই Kafka লাগলে, platform engineer না থাকলে একটা managed অফারকেই জোরালোভাবে প্রাধান্য দিন।

---

## ৭.৯ সাধারণ ভুল

১. **`acks=1`** — ভুল মুহূর্তে একটা leader fail করলে নীরবে data হারায়
২. **Idempotent producer চালু না করা** — retry থেকে duplicate তৈরি হয়
৩. আসল কাজের সাথে **`enable_auto_commit=True`** — processing শেষ হওয়ার আগেই offset commit করে
৪. **একটা keyed topic-এ partition বাড়ানো** — নীরবে per-key ordering ভাঙে
৫. **খুব বেশি partition** — ধীর failover, broker-এর memory-তে চাপ, বেশি latency
৬. ধীর processing-এর জন্য **`max.poll.interval.ms` খুব কম** — অন্তহীন rebalance লুপ
৭. **Kafka-কে task queue হিসেবে ব্যবহার** — টুলের সাথে লড়াই; প্রতি-message retry বা priority নেই
৮. **Consumer lag-এ কোনো alert নেই** — আপনি ব্যবহারকারীদের কাছ থেকে জানবেন
৯. **বিশ্বাস করা যে EOS বাইরের সিস্টেমও ঢাকে** — ঢাকে না
১০. **কোনো schema registry নেই** — একটা producer-এর পরিবর্তন মঙ্গলবার চারটা consumer ভেঙে দেয়
১১. ক্রম গুরুত্বপূর্ণ হলেও **key ছাড়া publish করা** — round-robin ক্রম ধ্বংস করে
১২. **Kafka-র দক্ষতা ছাড়া একটা self-managed cluster চালানো** — সব ঠিকই থাকবে, যতক্ষণ না একদমই থাকে না

---

## ৭.১০ আর্কিটেক্টের চেকলিস্ট

- [ ] Partition key এমনভাবে বাছা যে ক্রম-সংবেদনশীল record গুলো একটা key ভাগ করে আর key গুলো সমানভাবে ছড়ায়
- [ ] Partition-এর সংখ্যা ২–৩× headroom সহ ঠিক করা (পরে বাড়ালে ক্রম ভাঙে)
- [ ] Business data-র জন্য `replication.factor=3`, `min.insync.replicas=2`, `acks=all`
- [ ] Idempotent producer চালু
- [ ] Manual offset commit, processing-এর পরে, batch-এ
- [ ] Consumer গুলো idempotent (অধ্যায় ০৬-এর Inbox pattern)
- [ ] মসৃণ deploy-এর জন্য `CooperativeStickyAssignor` + static membership
- [ ] একটা poll batch-এর সবচেয়ে খারাপ processing সময়ের চেয়ে `max.poll.interval.ms` বেশি
- [ ] Retention policy ইচ্ছাকৃতভাবে সেট করা (সময়, আকার, বা compaction)
- [ ] Full compatibility বলবৎ করা schema registry
- [ ] Consumer lag monitor আর alert করা (record-এ **আর** সময়ে)
- [ ] Retry-topic আর DLQ-topic-এর কৌশল নির্ধারিত
- [ ] Self-hosting-এর আগে managed service বিবেচনা করা
- [ ] GDPR মুছে ফেলার কৌশল নির্ধারিত (compaction + tombstone, বা crypto-shredding)

---

## ৭.১১ নিজেকে যাচাই

১. এক বাক্যে ব্যাখ্যা করুন Kafka কেন একটা queue নয়।
২. Kafka-তে ক্রম সম্পর্কে ঠিক কী নিশ্চিত? কী নয়?
৩. Partition key কেন সবচেয়ে গুরুত্বপূর্ণ design সিদ্ধান্ত?
৪. Partition বাড়ালে ক্রম কেন ভাঙে? একটা key নিয়ে ধাপে ধাপে দেখান।
৫. আপনার ৪টা partition আর একটা group-এ ৬ জন consumer। কী হবে?
৬. Rebalance কী, এটা কেন বিঘ্নকর, আর ব্যথা কমানোর তিনটা উপায় বলুন।
৭. `acks=all` + `min.insync.replicas=2` + `replication.factor=3` ব্যাখ্যা করুন। দুটো broker মরলে কী হয়?
৮. Log compaction কী, আর এটা কোন সমস্যা সমাধান করে? Tombstone কী?
৯. Kafka-র exactly-once semantics ঠিক কী ঢাকে আর কী ঢাকে না, নিখুঁতভাবে বলুন।
১০. Consumer lag কীভাবে মাপবেন, আর record-এর পাশাপাশি সময়েও কেন মাপবেন?
১১. চারটা ব্যবহারের ক্ষেত্র দিন যেখানে Kafka সঠিক পছন্দ আর চারটা যেখানে ভুল।
১২. Debezium কী, আর Outbox pattern-এর সাথে এটা কোথায় বসে?

---

## ৭.১২ মূল কথাগুলো

- **Kafka একটা distributed, replay করা যায় এমন, সাজানো log।** Consumer-রা নিজের বুকমার্ক নিজে রাখে।
- **ক্রম শুধু প্রতি partition-এ।** সম্পর্কিত event একসাথে যাতে পড়ে সেভাবে message-এ key দিন।
- **Partition-ই সমান্তরালতার ছাদ** — আর সংখ্যাটা নিরাপদে বদলানো কঠিন
- **`acks=all` + idempotent producer + processing-এর পরে manual commit** — এটাই production-এর ভিত্তি
- **Replay-ই মোক্ষম feature** — এটা bug থেকে পুনরুদ্ধার, নতুন consumer আর backfill সম্ভব করে
- **Log compaction একটা topic-কে একটা টেকসই key-value snapshot-এ পরিণত করে**
- **Consumer lag-ই স্বাস্থ্য-metric।** এতে alert দিন।
- **EOS সত্যিকারের কিন্তু সংকীর্ণ।** Kafka-র বাইরে আপনার এখনো idempotency লাগবে।
- **Kafka অতিরিক্ত গৃহীত।** আপনার replay/throughput/fan-out-এর প্রয়োজনের নাম বলুন, নয়তো একটা সহজ broker ব্যবহার করুন — আর সত্যিই লাগলে managed Kafka-কে প্রাধান্য দিন।

---

**পরবর্তী:** [অধ্যায় ০৮ — API Architecture](08-api-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 07](../07-kafka.md) · **[সূচিপত্র](README.md)**
