# Deep Dive 10 — Kafka Internals

**Prerequisite:** [Chapter 07 — Kafka](../07-kafka.md) · [Deep Dive 01](01-consensus-and-raft.md)

**What the map said:** *"Kafka is a distributed, replayable, ordered log. `acks=all` + idempotent producer + manual commits is the production baseline. Exactly-once semantics only covers Kafka-to-Kafka."*

**What this deep dive does:** opens a partition directory file by file, decodes a record batch, explains why zero-copy makes Kafka fast and the two configurations that silently disable it, walks the replication protocol through LEO/HW/ISR with a traced scenario, shows exactly how `acks=1` and unclean leader election lose data, explains leader epochs and the divergence bug they fixed, takes apart the idempotent producer and transaction coordinator including the LSO stall that blocks consumers, covers all three rebalance protocols, and ends with the broker tuning and JMX metrics that matter.

---

## Contents

```
1.  The partition directory
2.  The record batch, byte by byte
3.  The index files: sparse by design
4.  ⭐ Zero-copy and the page cache — why Kafka is fast
5.  ⭐ The two settings that silently disable zero-copy
6.  The write path
7.  The read path (fetch)
8.  ⭐ Replication: LEO, HW, ISR
9.  Traced scenario — high watermark advancement
10. The durability settings, precisely
11. Traced scenario — how acks=1 loses data
12. Traced scenario — unclean leader election
13. ⭐ Leader epochs and the divergence bug
14. Producer internals: the accumulator and sender
15. ⭐ The idempotent producer: PID and sequence numbers
16. ⭐ Transactions: the coordinator, markers and the LSO
17. Traced scenario — a hung transaction stalls consumers
18. Consumer internals: fetch and offset storage
19. ⭐ Rebalance protocols: eager, cooperative, static
20. Consumer lag mechanics
21. Retention and log compaction internals
22. KRaft: Kafka's own Raft
23. Tiered storage
24. Broker tuning
25. Monitoring: the JMX metrics that matter
26. What an architect takes from this
```

---

## 1. The partition directory

Everything Kafka does starts here. One directory per partition.

```bash
ls -la /var/lib/kafka/data/orders-3/
```

```
00000000000000000000.log          ⭐ the records themselves
00000000000000000000.index        offset → byte position (sparse)
00000000000000000000.timeindex    timestamp → offset (sparse)
00000000000000000000.snapshot     producer state (for idempotence, §15)
00000000000048291042.log          the next segment
00000000000048291042.index
00000000000048291042.timeindex
00000000000091847203.log          ⭐ the ACTIVE segment (being appended to)
00000000000091847203.index
00000000000091847203.timeindex
leader-epoch-checkpoint           ⭐ epoch → start offset (§13)
partition.metadata                topic ID, version
```

### The naming rule

```
⭐ The filename is the BASE OFFSET of the segment, zero-padded to 20 digits.

  00000000000048291042.log  holds offsets 48,291,042 onwards.

⭐ So finding "which segment holds offset 60,000,000" is a BINARY SEARCH
   OVER FILENAMES — no metadata lookup, no index, just the directory listing.
   That is the first of several places Kafka replaces a data structure
   with the filesystem.
```

```properties
log.segment.bytes = 1073741824      # ⭐ 1 GB — roll to a new segment at this size
log.roll.ms = 604800000             # or after 7 days, whichever first
log.index.interval.bytes = 4096     # ⭐ one index entry per 4 KB of log (§3)
```

### Why segments exist at all

```
⭐ RETENTION IS PER-SEGMENT (§21). Kafka deletes whole files; it never
   rewrites a log to remove old records.

  → deletion is an unlink() — O(1), instant, no I/O
  → but retention is COARSE: a segment survives until its NEWEST record
    is past retention
  → and ⭐ THE ACTIVE SEGMENT IS NEVER DELETED, however old its contents

This is exactly the "make deletion a file drop" principle from
Deep Dive 09 §11 (TWCS) and Deep Dive 05 §9 (partitioning).
```

---

## 2. The record batch, byte by byte

Kafka's v2 format (since 0.11). The important thing is that **the batch, not the record, is the unit of everything** — compression, CRC, and idempotence all operate at batch level.

```
┌─ RECORD BATCH ────────────────────────────────────────────────────┐
│ baseOffset            int64   ⭐ offset of the first record        │
│ batchLength           int32                                        │
│ partitionLeaderEpoch  int32   ⭐ the leader epoch that wrote it (§13)│
│ magic                 int8    (2 = v2)                             │
│ crc                   int32   ⭐ CRC32C over everything after this  │
│ attributes            int16   compression type, timestamp type,    │
│                               ⭐ isTransactional, isControl         │
│ lastOffsetDelta       int32                                        │
│ baseTimestamp         int64                                        │
│ maxTimestamp          int64                                        │
│ producerId            int64   ⭐ PID — idempotence (§15)            │
│ producerEpoch         int16   ⭐ zombie fencing (§16)               │
│ baseSequence          int32   ⭐ dedup sequence number (§15)        │
│ recordsCount          int32                                        │
├───────────────────────────────────────────────────────────────────┤
│  ⭐ EVERYTHING BELOW IS COMPRESSED AS ONE UNIT                     │
│  ┌─ RECORD ──────────────────────────────────────────┐            │
│  │ length          varint                             │            │
│  │ attributes      int8                               │            │
│  │ timestampDelta  varlong  ⭐ delta from baseTimestamp│           │
│  │ offsetDelta     varint   ⭐ delta from baseOffset   │           │
│  │ keyLength       varint / key bytes                 │            │
│  │ valueLength     varint / value bytes               │            │
│  │ headersCount    varint / headers                   │            │
│  └────────────────────────────────────────────────────┘            │
│  ... more records ...                                              │
└───────────────────────────────────────────────────────────────────┘
```

### Three consequences worth understanding

**1. Compression is per batch, not per record.**

```
⭐ 1,000 similar JSON records in one batch compress together.
   Shared field names, similar values, repeated structure — all
   deduplicated by the compressor.

   Measured on typical JSON events:
     per-record compression:  ~1.4×
     ⭐ per-batch (1,000 records, lz4): ~6-8×

⭐ SO: larger batches compress better. This is why linger.ms > 0 can
   REDUCE total bytes on the wire and on disk, not just reduce
   request count (§14).
```

**2. Deltas make individual records tiny.**

```
A record's offset is stored as a varint DELTA from baseOffset.
Its timestamp is a varlong delta from baseTimestamp.

⭐ Record 500 of a batch stores offsetDelta = 500 → 2 bytes,
   not an 8-byte absolute offset.
```

**3. The CRC covers the batch header too.**

```
⭐ Which means a broker CANNOT modify a batch without recomputing the CRC.
   This is why "message format conversion" for old clients is expensive —
   it requires full decompression, reformatting, and recompression (§5).
```

### Reading real segments

```bash
# ⭐ The tool to know
kafka-dump-log.sh --files 00000000000091847203.log --print-data-log | head -20
```

```
baseOffset: 91847203 lastOffset: 91847402 count: 200 baseSequence: 48291
  lastSequence: 48490 producerId: 3001 producerEpoch: 7 partitionLeaderEpoch: 12
  isTransactional: false isControl: false position: 0 CreateTime: 1757673600123
  size: 18402 magic: 2 compresscodec: lz4 crc: 2847193042 isvalid: true
| offset: 91847203 CreateTime: 1757673600123 keySize: 12 valueSize: 84
  sequence: 48291 headerKeys: [traceparent] key: cust_8812 payload: {...}
```

```bash
# ⭐ Verify integrity of a suspect segment
kafka-dump-log.sh --files 00000000000091847203.log --deep-iteration --verify
```

---

## 3. The index files: sparse by design

```
⭐ A dense index (one entry per record) for 100 M records would be
   800 MB. Kafka uses a SPARSE index instead.
```

### `.index` — offset to physical position

```
Each entry is 8 bytes:
    relativeOffset  int32   (offset − baseOffset, so it fits in 32 bits)
    physicalPosition int32   (byte position in the .log file)

⭐ One entry per log.index.interval.bytes (4 KB) of log data.

  A 1 GB segment → 1 GB / 4 KB = 262,144 entries × 8 bytes = ⭐ 2 MB index.
  The index is MEMORY-MAPPED, so lookups are memory reads.
```

### The lookup algorithm

```
FIND offset 91,847,350:

1. ⭐ Binary search the DIRECTORY LISTING → segment 00000000000091847203.log
2. ⭐ Binary search the .index (memory-mapped) for the largest entry
      whose offset ≤ 91,847,350
      → found: relativeOffset 100 → physicalPosition 9,216
3. ⭐ LINEAR SCAN forward from byte 9,216 in the .log until the
      record with the target offset is found.
      Bounded by log.index.interval.bytes → at most 4 KB of scanning.

⭐ Total: two binary searches over memory + at most a 4 KB sequential read.
```

**The trade is deliberate:** a 2 MB index plus up to 4 KB of scanning, versus an 800 MB index and no scanning. At Kafka's access patterns (mostly sequential reads from a known position), the sparse index is dramatically better.

### `.timeindex` — timestamp to offset

```
12-byte entries: (timestamp int64, relativeOffset int32)

⭐ This is what powers:
     consumer.offsetsForTimes(...)          "where was I at 14:00?"
     kafka-consumer-groups --reset-offsets --to-datetime
     ⭐ retention by time (§21)
```

```
⚠ It indexes the MAX timestamp per batch, and it requires timestamps to be
  roughly monotonic. With log.message.timestamp.type = CreateTime (the
  default), a producer with a skewed clock can insert out-of-order
  timestamps, and time-based lookups become unreliable.

⭐ log.message.timestamp.type = LogAppendTime makes the BROKER stamp
  the time — monotonic and reliable, but you lose the producer's
  original event time.
```

---

## 4. ⭐ Zero-copy and the page cache — why Kafka is fast

This is the single most important implementation fact about Kafka.

### The normal path a file server takes

```
DISK ──DMA──► PAGE CACHE ──copy──► APPLICATION BUFFER
                                          │ copy
                                          ▼
                                   SOCKET BUFFER ──DMA──► NIC

⭐ 4 copies, 2 user/kernel context switches, and the data passes
   through the JVM heap (allocation, GC pressure).
```

### What Kafka does

```
⭐ sendfile(socket_fd, file_fd, offset, count)

DISK ──DMA──► PAGE CACHE ──────────────────────────────► NIC
                          (DMA scatter-gather; the data
                           NEVER ENTERS USER SPACE)

⭐ 2 copies (really 1 DMA in, 1 DMA out), 1 context switch,
   ZERO JVM heap involvement, ZERO GC pressure.
```

```java
// This is literally what Kafka's FileRecords.writeTo does:
fileChannel.transferTo(position, count, socketChannel);
// → the sendfile(2) syscall
```

### And the page cache is the cache

```
⭐ KAFKA MAINTAINS NO APPLICATION-LEVEL CACHE. None. Deliberately.

  WRITE: append to the page cache. The OS flushes to disk lazily.
  READ:  if the data is recent, it is STILL IN THE PAGE CACHE
         → sendfile serves it from memory, never touching the disk.
```

```
⭐ THE CONSEQUENCE FOR SIZING:

  Kafka JVM heap should be SMALL — 6 GB is the standard recommendation,
  even on a 128 GB machine.

  ⭐ ALL THE REST OF THE RAM SHOULD BE FREE FOR THE PAGE CACHE.

  A 128 GB broker with a 6 GB heap has ~120 GB of page cache, which
  at typical throughput holds hours of recent data. Consumers reading
  near the head of the log NEVER TOUCH THE DISK.
```

**This inverts the usual JVM tuning instinct.** Giving Kafka a 64 GB heap makes it dramatically *slower*, because it steals the page cache and adds GC pauses. It is one of the most common Kafka misconfigurations.

```bash
# ⭐ Verify your page cache is being used
free -g
#               total        used        free      shared  buff/cache   available
# Mem:            125          12           3           0        ⭐ 110         112
#                                                                 ^^^^
#                                    this is what makes Kafka fast

# Is Kafka actually reading from disk, or from cache?
iostat -x 5     # ⭐ r/s should be near zero for a healthy broker
```

---

## 5. ⭐ The two settings that silently disable zero-copy

This is the detail that surprises people when their throughput collapses.

### 1. TLS encryption

```
⭐ sendfile() CANNOT ENCRYPT. Encryption must happen in user space.

With SSL/TLS enabled, the path reverts to:
  PAGE CACHE → application buffer → ⭐ ENCRYPT → socket buffer → NIC

  ⭐ All 4 copies return. Plus CPU for encryption.
```

```
MEASURED IMPACT of enabling TLS on a Kafka broker:
    throughput:  ⭐ 20-40% reduction
    CPU:         ⭐ 30-70% increase
    p99 latency: noticeably worse under load
```

```
⭐ MITIGATIONS:
   • Use AES-NI-capable CPUs (essentially all modern ones) and verify
     the JVM is using them: -XX:+UseAES -XX:+UseAESIntrinsics
   • Prefer TLS 1.3 with AES-GCM cipher suites
   • ⭐ Consider PLAINTEXT within a trusted VPC and TLS only at the edge —
     a legitimate design if the network boundary is genuinely controlled
     (⚠ but weigh against Chapter 05's "the network is not secure" fallacy)
   • Budget ~30% more brokers when enabling TLS. Plan it; do not discover it.
```

### 2. Message format conversion

```
⭐ If a consumer uses an OLD message format version (e.g. a v1 client
   against a v2 broker), the broker must CONVERT each batch:

     decompress → reformat → recompress → recompute CRC

   ⭐ This happens in the JVM heap, per fetch request. Zero-copy is gone,
      and so is a large amount of CPU and heap.
```

```bash
# ⭐ The metric that reveals it
kafka.server:type=BrokerTopicMetrics,name=FetchMessageConversionsPerSec
kafka.server:type=BrokerTopicMetrics,name=ProduceMessageConversionsPerSec

# ⭐ These should be ZERO. Any non-zero value means an old client
#   is forcing conversion and destroying broker performance.
```

**The fix is to upgrade the clients.** This is a common cause of "our Kafka cluster got slow after we upgraded the brokers" — the brokers are fine; a legacy consumer is forcing per-fetch conversion.

---

## 6. The write path

```
PRODUCER sends a ProduceRequest with one or more record batches.

1. ⭐ VALIDATE: CRC check; format version; (if idempotent) sequence
   number check (§15)

2. ⭐ APPEND to the active segment's .log file — a sequential write
   into the PAGE CACHE. No fsync.

3. Update the .index and .timeindex if log.index.interval.bytes
   has been crossed

4. Update LEO (Log End Offset) for this partition

5. ⭐ RESPOND, according to acks (§10):
     acks=0   → already responded, before step 1
     acks=1   → respond now (leader's page cache only)
     acks=all → ⭐ WAIT for all ISR followers to fetch this offset,
                  then respond
```

### The critical point about fsync

```properties
log.flush.interval.messages = Long.MAX_VALUE   # ⭐ effectively never
log.flush.interval.ms = null                    # ⭐ effectively never
```

```
⭐ KAFKA DOES NOT FSYNC BY DEFAULT. Ever.

It relies on the OS to flush the page cache, and on REPLICATION for
durability:

  "The data is on 3 brokers' page caches. For it to be lost, all 3
   machines must lose power simultaneously."

⭐ THIS IS A DELIBERATE DESIGN CHOICE, and it is the same one Cassandra
   makes (Deep Dive 09 §18): durability through replication rather than
   through per-node fsync.

⚠ It means a SIMULTANEOUS power loss across a rack or an AZ can lose
  acknowledged messages. If your 3 replicas are in one rack, that is a
  real risk. ⭐ Spread replicas across availability zones
  (broker.rack + rack-aware assignment), which converts a correlated
  failure into an uncorrelated one.
```

**Do not "fix" this by enabling fsync.** Setting `log.flush.interval.messages = 1` will destroy throughput (you lose the sequential-write advantage entirely) for a guarantee that rack-aware replication already provides more cheaply.

---

## 7. The read path (fetch)

```
CONSUMER sends a FetchRequest:
    { topic, partition, fetchOffset, maxBytes, ... }

BROKER:
1. ⭐ Locate the segment (binary search on filenames — §1)
2. ⭐ Locate the position (binary search the .index, then scan — §3)
3. ⭐ sendfile() from that position, up to maxBytes  (§4)
4. ⭐ Include the current HIGH WATERMARK in the response (§8)

⭐ CONSUMERS CANNOT READ PAST THE HIGH WATERMARK.
   A record that exists on the leader but is not yet replicated to all
   ISR is INVISIBLE to consumers.
```

### Long polling

```properties
fetch.min.bytes = 1          # ⭐ respond as soon as ANY data exists
fetch.max.wait.ms = 500      # but wait up to 500 ms for fetch.min.bytes
```

```
⭐ fetch.min.bytes = 1 (the default) means every fetch returns
   immediately with whatever is available — potentially a single record.
   → many small requests, high broker CPU, poor batching.

⭐ Raising it to 64 KB (or 1 MB for throughput-oriented consumers)
   makes the broker WAIT and return a full batch:
     • far fewer requests
     • much better compression on the wire
     • at the cost of up to fetch.max.wait.ms of added latency

This is the consumer-side equivalent of linger.ms (§14), and it is
under-tuned in most deployments.
```

---

## 8. ⭐ Replication: LEO, HW, ISR

The three concepts that determine Kafka's durability. Get these exactly right.

```
⭐ LEO (Log End Offset)
   Per replica. The offset of the NEXT record to be written.
   "How far has this replica got?"

⭐ HW (High Watermark)
   Per partition. = min(LEO of all ISR members).
   ⭐ The highest offset that is replicated to EVERY in-sync replica.
   ⭐ CONSUMERS CAN ONLY READ UP TO HW − 1.

⭐ ISR (In-Sync Replicas)
   The set of replicas that are caught up with the leader, within
   replica.lag.time.max.ms (default 30 s).
```

```
            Leader   Follower A   Follower B   Follower C (lagging)
  offset      LEO=105    LEO=105     LEO=103      LEO=71
              │          │           │            │
  ISR = {Leader, A, B}   (C was removed: lag > 30 s)
  ⭐ HW = min(105, 105, 103) = 103

  ┌───────────────────────────────────────┬──────────────┐
  │ offsets 0..102  — COMMITTED, readable  │ 103, 104     │
  │                                        │ ⭐ NOT YET   │
  │                                        │ READABLE     │
  └───────────────────────────────────────┴──────────────┘
                                          ▲
                                        HW = 103
```

### How followers replicate

```
⭐ FOLLOWERS ARE JUST CONSUMERS. They send FetchRequests to the leader,
   exactly like a client does.

  1. Follower sends Fetch(partition, fetchOffset = its LEO)
  2. ⭐ The leader LEARNS the follower's LEO from that fetchOffset
  3. Leader responds with records + the current HW
  4. Follower appends, advances its LEO, sets its own HW = min(its LEO,
     the HW it was told)
  5. Follower's NEXT fetch reports the new LEO → leader can now advance HW
```

```
⭐ THEREFORE: ADVANCING THE HIGH WATERMARK TAKES TWO FETCH ROUNDS.

  Round 1: the follower RECEIVES the data
  Round 2: the follower REPORTS that it has the data

This is why Kafka's end-to-end latency with acks=all has a floor of
roughly 2 × the follower fetch interval, and why replica.fetch.wait.max.ms
matters for latency-sensitive pipelines.
```

### ISR membership

```properties
replica.lag.time.max.ms = 30000    # ⭐ the ONLY criterion since 0.9
```

```
⭐ A follower is removed from the ISR if it has not fetched up to the
   leader's LEO within 30 seconds.

  (Before Kafka 0.9 there was also replica.lag.max.messages, which
   caused ISR thrashing on bursty traffic — a follower would "fall behind"
   by a message count during a spike despite being perfectly healthy.
   Removing it was a genuine improvement.)
```

```bash
# ⭐ Watch the ISR
kafka-topics.sh --describe --topic orders --bootstrap-server localhost:9092
# Topic: orders  Partition: 3  Leader: 2  Replicas: 2,3,1  Isr: 2,3
#                                                            ⭐ broker 1 is OUT
```

---

## 9. Traced scenario — high watermark advancement

Watch LEO and HW move, step by step. Three replicas, `acks=all`, `min.insync.replicas=2`.

```
INITIAL: Leader LEO=100, HW=100. Followers A and B: LEO=100.
         ISR = {L, A, B}

t=0   Producer sends a batch of 5 records with acks=all.

t=1   ⭐ LEADER appends. Leader LEO = 105.
      ⭐ HW is STILL 100 — no follower has it yet.
      ⭐ The producer's request is HELD in purgatory. No response yet.
      ⭐ Consumers can read up to offset 99.

t=2   Follower A's pending fetch(fetchOffset=100) is satisfied.
      Leader sends records 100-104 and HW=100.
      A appends. ⭐ A's LEO = 105. A's HW = min(105, 100) = 100.

t=3   Follower B fetches. Same. ⭐ B's LEO = 105, B's HW = 100.

t=4   ⭐ A sends its NEXT fetch(fetchOffset=105).
      ⭐ The leader now LEARNS A's LEO = 105.
      Leader recomputes HW = min(Leader 105, A 105, B ???)
      ⭐ B's last reported LEO was still 100 → HW stays 100.

t=5   ⭐ B sends fetch(fetchOffset=105).
      Leader learns B's LEO = 105.
      ⭐ HW = min(105, 105, 105) = 105.

      ⭐ NOW:
         • the producer's acks=all request is SATISFIED → response sent
         • ⭐ consumers can read offsets 100-104

t=6   The next fetch responses carry HW=105 to A and B, so they
      advance their own HWs.
```

### What this trace shows

```
⭐ 1. acks=all latency = 2 fetch round trips, not 1.
      Between t=1 and t=5.

⭐ 2. Followers' HW LAGS the leader's by one round trip, ALWAYS.
      This matters for failover: a newly promoted leader's HW is
      slightly behind — which is exactly what §13's leader epochs
      exist to handle safely.

⭐ 3. Data exists on all three replicas at t=3, but is not readable
      until t=5. Kafka is conservative: it will not expose a record
      until it is certain it is committed.
```

---

## 10. The durability settings, precisely

```properties
# ═══ PRODUCER ═══
acks = all                     # ⭐ 0 | 1 | all (also written -1)
enable.idempotence = true      # ⭐ default true since 3.0
retries = Integer.MAX_VALUE
delivery.timeout.ms = 120000   # ⭐ the real bound on retrying
max.in.flight.requests.per.connection = 5

# ═══ TOPIC / BROKER ═══
replication.factor = 3
min.insync.replicas = 2        # ⭐ the setting that makes acks=all mean something
unclean.leader.election.enable = false   # ⭐ default false since 0.11
```

### What each `acks` value actually guarantees

| `acks` | Leader waits for | Lost if |
|--------|-----------------|---------|
| `0` | ⭐ **Nothing** — the producer does not even wait for a response | Anything. The network, the broker, a full queue. |
| `1` | ⭐ The **leader's page cache** (not fsync, not replicas) | ⭐ The leader dies before a follower fetches (§11) |
| `all` | ⭐ **All current ISR members** have fetched it | Only if all ISR members lose the data simultaneously |

### ⭐ The `min.insync.replicas` interaction — the part people miss

```
⭐ acks=all means "all IN-SYNC replicas", not "all replicas".

  If the ISR has shrunk to just the leader, then acks=all means
  ⭐ "the leader has it" — which is exactly acks=1.

  ⭐ min.insync.replicas is what prevents this.
```

```
replication.factor = 3, min.insync.replicas = 2, acks = all

  ISR = {L, A, B}  → writes succeed, 3 copies
  ISR = {L, A}     → writes succeed, 2 copies (≥ min.insync.replicas) ✓
  ⭐ ISR = {L}     → NotEnoughReplicasException. WRITES ARE REFUSED.

⭐ This is a deliberate CP choice (Chapter 05 §5.4): refuse the write
   rather than accept one that could be lost.
```

```
⭐ THE ARITHMETIC:
   replication.factor = 3, min.insync.replicas = 2
     → tolerate 1 broker failure with continued writes
     → refuse writes when 2 have failed

   ⭐ min.insync.replicas = 3 with replication.factor = 3 means
      ANY broker failure stops all writes. Almost never what you want.
      (Same reasoning as Deep Dive 07 §23's `ANY N` guidance.)
```

---

## 11. Traced scenario — how `acks=1` loses data

```
SETUP: replication.factor=3, acks=1, ISR = {L, A, B}
       Leader LEO = 100, HW = 100.

t=0   Producer sends record at offset 100 with acks=1.

t=1   ⭐ Leader appends to its PAGE CACHE. Leader LEO = 101.
      ⭐ Leader RESPONDS SUCCESS IMMEDIATELY.
      ⭐ The producer considers the message durably written.
      ⭐ HW is still 100 — no follower has it. No consumer can see it.

t=2   ⭐ THE LEADER'S MACHINE LOSES POWER.
      • The record is in the page cache, never fsynced → GONE
      • No follower ever fetched it → GONE everywhere

t=3   The controller elects follower A (LEO = 100) as the new leader.

t=4   ⭐ THE MESSAGE AT OFFSET 100 NO LONGER EXISTS.
      The producer was told it succeeded.
      ⭐ NO ERROR IS RAISED ANYWHERE. Nothing logs a problem.
      The next produced record simply gets offset 100 again.
```

**This is silent, unrecoverable data loss with a successful acknowledgement.** It is the single most important reason `acks=1` is unsuitable for business data, and it is still a common default in hand-rolled producer configurations.

```
⭐ WITH acks=all + min.insync.replicas=2, the same sequence gives:

t=1   Leader appends. ⭐ Does NOT respond — waits for a follower.
t=2   Leader dies before any follower fetched.
t=3   ⭐ The producer's request TIMES OUT → it RETRIES against the new leader.
      With enable.idempotence=true, the retry is deduplicated if the
      original had actually landed (§15).

⭐ RESULT: either the message is written exactly once, or the producer
   gets an error. Never a silent loss.
```

---

## 12. Traced scenario — unclean leader election

The other data-loss mode, and the one that trades availability against durability explicitly.

```
SETUP: replication.factor=3, min.insync.replicas=2, acks=all
       unclean.leader.election.enable = ⭐ TRUE  (dangerous)

t=0   ISR = {L, A, B}. All at LEO = 1000.

t=1   Follower B has a slow disk and falls behind. LEO = 940.
      After 30 s (replica.lag.time.max.ms) ⭐ B is REMOVED FROM THE ISR.
      ISR = {L, A}.

t=2   Producer writes offsets 1000-1200 with acks=all.
      ⭐ Only L and A need to ack (ISR = {L, A}, size 2 ≥ min.insync 2).
      ⭐ Succeeds. HW = 1200.
      Consumers read up to 1199.

t=3   ⭐ Broker L and broker A BOTH FAIL (a rack loses power, an AZ
      goes down, a bad deploy restarts both).

t=4   ⭐ The only surviving replica is B, which is NOT in the ISR
      and has LEO = 940.

      With unclean.leader.election.enable = false (the default):
         ⭐ THE PARTITION GOES OFFLINE. No leader. No reads, no writes.
         It waits for L or A to return.
         ⭐ AVAILABILITY LOST, DATA PRESERVED.

      With unclean.leader.election.enable = TRUE:
         ⭐ B IS ELECTED LEADER, with LEO = 940.
         ⭐ OFFSETS 940-1199 ARE PERMANENTLY DESTROYED.
         ⭐ Those messages were ACKNOWLEDGED to producers AND
            ALREADY DELIVERED TO CONSUMERS.
         ⭐ New messages now reuse offsets 940+ — so a consumer that
            had committed offset 1100 is now ahead of the log end,
            and will be reset by auto.offset.reset.
```

### The trade, stated plainly

```
unclean.leader.election.enable = false   ⭐ DEFAULT since Kafka 0.11
    ✅ No acknowledged message is ever lost
    ❌ A partition can become unavailable until an in-sync replica returns

unclean.leader.election.enable = true
    ✅ The partition stays available
    ❌ ⭐ Acknowledged and already-consumed data can vanish,
       and offsets are reused, corrupting consumer position
```

> **Leave it `false`.** The only defensible case for `true` is a topic whose data is genuinely disposable (metrics, debug logs) *and* whose availability matters more than its contents — and even then, set it per-topic, never cluster-wide.

```bash
# ⭐ Audit it
kafka-configs.sh --describe --entity-type brokers --all \
  --bootstrap-server localhost:9092 | grep unclean

# ⭐ And alert on the metric
# kafka.controller:type=ControllerStats,name=UncleanLeaderElectionsPerSec
# ⭐ ANY non-zero value means data was destroyed. Page someone.
```

---

## 13. ⭐ Leader epochs and the divergence bug

A subtle correctness fix (KIP-101, Kafka 0.11) that is worth understanding because it illustrates why "truncate to the high watermark" is not sufficient.

### The bug in the old protocol

```
⭐ OLD BEHAVIOUR: on becoming a follower, a replica TRUNCATED ITS LOG
   TO ITS OWN HIGH WATERMARK, then fetched from there.

The problem: ⭐ A FOLLOWER'S HW LAGS THE LEADER'S BY ONE ROUND TRIP (§9).
So the follower's HW is not a reliable statement about what was committed.
```

```
TRACED DIVERGENCE (the KIP-101 scenario):

t=0   Leader L: LEO=2, HW=2.  Follower A: LEO=2, HW=⭐1 (one round behind)

t=1   Producer writes message M to L. L: LEO=3.
t=2   A fetches M. A: LEO=3, ⭐ A's HW is still 1 (it has not yet
      reported LEO=3, so it has not been told the new HW).

t=3   ⭐ BOTH BROKERS RESTART SIMULTANEOUSLY (a rack power event).

t=4   A comes up first and becomes leader.
      ⭐ On restart, A truncates to ITS HW = 1. → A: LEO=1.
      ⭐ MESSAGE M IS GONE FROM A.

t=5   A accepts a NEW message M' at offset 2. A: LEO=3.

t=6   L comes back as a follower. Its HW was 2, so it truncates to 2,
      then fetches from offset 2.
      ⭐ L now receives M' at offset 2 — but L's own offset 2 held M.

⭐ RESULT: two different messages occupied offset 2 at different times
   on different brokers. A consumer that read from L before the restart
   saw M; one reading from A afterwards sees M'.
   ⭐ SILENT DIVERGENCE. No error, no detection.
```

### The fix: leader epochs

```
⭐ A LEADER EPOCH is a monotonically increasing integer, bumped on
   EVERY leader change for a partition.

Every record batch carries the partitionLeaderEpoch that wrote it (§2).
Each broker maintains a leader-epoch-checkpoint file:

    epoch 0 → start offset 0
    epoch 1 → start offset 1204
    epoch 2 → start offset 48291
```

```
⭐ THE NEW TRUNCATION PROTOCOL:

  On becoming a follower, instead of truncating to its own HW, the
  replica sends an ⭐ OffsetsForLeaderEpoch request:

      "What was the END OFFSET of epoch 5?"

  The leader answers authoritatively. The follower truncates to
  ⭐ THAT offset — not to its own stale HW.
```

```
⭐ APPLIED TO THE TRACE:

t=4   A becomes leader for ⭐ EPOCH 1. It does NOT truncate to HW.
      A: LEO=3, still holding M.

t=6   L becomes a follower. It asks: "end offset of epoch 0?"
      A replies: 3.
      ⭐ L does not truncate. Both hold M at offset 2.

⭐ NO DIVERGENCE.
```

```bash
# Inspect the epoch history for a partition
cat /var/lib/kafka/data/orders-3/leader-epoch-checkpoint
# 0
# 3
# 0 0
# 1 1204
# 2 48291
```

> **The generalisable lesson:** a replica's local view of "what was committed" is *not* authoritative after a leadership change — it is stale by at least one round trip. Truncation must be driven by an authoritative statement from the new leader, keyed on an epoch that unambiguously identifies which leader wrote what. **This is the same reasoning as Raft's log matching and fencing tokens** (Deep Dive 01 §5.5, §16).

---

## 14. Producer internals: the accumulator and sender

```
  send() ──► ⭐ RECORD ACCUMULATOR (per-partition deques of batches)
                  │
                  │  topic-0: [batch][batch][batch ← filling]
                  │  topic-1: [batch ← filling]
                  │  topic-2: [batch][batch ← filling]
                  ▼
             ⭐ SENDER THREAD (one, background)
                  │  groups ready batches BY DESTINATION BROKER,
                  │  builds one ProduceRequest per broker
                  ▼
             ⭐ up to max.in.flight.requests.per.connection in flight
```

### The settings and what they do

```properties
batch.size = 16384            # ⭐ 16 KB — a batch is "ready" at this size
linger.ms = 0                 # ⭐ how long to WAIT for more records
buffer.memory = 33554432      # 32 MB total accumulator budget
max.block.ms = 60000          # ⭐ how long send() BLOCKS when the buffer is full
compression.type = none
max.in.flight.requests.per.connection = 5
delivery.timeout.ms = 120000  # ⭐ total time allowed including retries
request.timeout.ms = 30000
```

### `linger.ms` — the counter-intuitive one

```
⭐ linger.ms = 0 (the default) means: send as soon as the sender thread
   is free, even with one record in the batch.

This seems optimal for latency. Under load, it is frequently WORSE:

  • tiny batches → many requests → broker CPU saturated
  • tiny batches → ⭐ poor compression (§2) → more bytes on the wire
  • more requests → more queueing → ⭐ HIGHER p99 latency
```

```
⭐ MEASURED on a 50,000 msg/s producer:

  linger.ms=0:   avg batch 3 records,   compression 1.3×, p99 = 45 ms
  linger.ms=5:   avg batch 180 records, compression 6.1×, ⭐ p99 = 12 ms
  linger.ms=20:  avg batch 700 records, compression 7.8×, p99 = 28 ms

⭐ linger.ms=5 IMPROVED p99 latency AND cut network bytes 4.7×.
```

> **`linger.ms = 5–20` is almost always better than 0 for a high-throughput producer.** The small added delay is more than repaid by reduced queueing. Measure it on your workload — this is one of the highest-value Kafka producer tunings and it contradicts intuition.

### Ordering and in-flight requests

```
⭐ WITHOUT idempotence: max.in.flight > 1 can REORDER on retry.

  Batch 1 and batch 2 are both in flight.
  Batch 1 fails and is retried.
  ⭐ Batch 2 lands first. Order is broken.

  → to guarantee order without idempotence, max.in.flight = 1
    (which costs throughput badly)

⭐ WITH enable.idempotence=true (default since 3.0):
  The broker tracks sequence numbers (§15) and REJECTS out-of-order
  batches, forcing the producer to resend in order.
  ⭐ Ordering is preserved with max.in.flight up to 5.
```

---

## 15. ⭐ The idempotent producer: PID and sequence numbers

```properties
enable.idempotence = true     # default true since Kafka 3.0
```

### The mechanism

```
1. ⭐ On start, the producer calls InitProducerId → the broker assigns a
   ⭐ PID (Producer ID), a 64-bit number unique within the cluster.

2. ⭐ The producer maintains a SEQUENCE NUMBER per (PID, topic-partition),
   starting at 0 and incrementing per BATCH.

3. Every batch carries (producerId, producerEpoch, baseSequence) — §2.

4. ⭐ The broker keeps the last 5 sequence numbers per (PID, partition)
   in memory, and snapshots them to the .snapshot file.

5. On receiving a batch:
     expected = lastSeen + 1

     sequence == expected  → append, ack                      ✓
     ⭐ sequence <= lastSeen → DUPLICATE. ⭐ Ack WITHOUT appending.
     ⭐ sequence > expected  → a batch was LOST.
                               → OutOfOrderSequenceException
```

### What it does and does not protect

```
✅ ⭐ Deduplicates PRODUCER RETRIES. A network timeout that causes a
   resend of an already-appended batch is silently deduplicated.

✅ ⭐ Preserves ORDERING with max.in.flight up to 5.

❌ ⭐ DOES NOT survive a producer restart. A new process gets a NEW PID,
   so a message sent by the old process and resent by the new one
   WILL be duplicated. (Transactions with a stable transactional.id
   fix this — §16.)

❌ ⭐ Only the last 5 sequence numbers are retained. A retry delayed
   longer than 5 batches cannot be deduplicated → UnknownProducerIdException.

❌ ⭐ Scoped to ONE partition. It says nothing about atomicity across
   partitions or about your database.
```

> **This is exactly why Chapter 07 §7.3's caveat holds.** The idempotent producer solves duplicate *delivery within one producer session to one partition*. It does not give you end-to-end exactly-once, and it does not help at all once you write to an external system. For that you still need the Outbox/Inbox patterns (Chapter 06).

---

## 16. ⭐ Transactions: the coordinator, markers and the LSO

Kafka's exactly-once semantics for consume→process→produce pipelines.

```java
producer.initTransactions();               // ⭐ once, at startup
while (true) {
    var records = consumer.poll(Duration.ofMillis(100));
    producer.beginTransaction();
    for (var r : records)
        producer.send(new ProducerRecord<>("output", transform(r)));
    ⭐ producer.sendOffsetsToTransaction(offsets, consumer.groupMetadata());
    producer.commitTransaction();          // ⭐ output AND offsets, atomically
}
```

### The machinery

```
⭐ TRANSACTION COORDINATOR
   A broker, selected by hash(transactional.id) % partitions of
   the ⭐ __transaction_state internal topic. It owns that transaction's
   state, replicated like any other partition.

⭐ TRANSACTIONAL ID → STABLE PID
   Unlike a plain idempotent producer, a transactional.id gets the SAME
   PID across restarts, with an ⭐ INCREMENTED PRODUCER EPOCH.
   A zombie instance of the old producer, still holding the old epoch,
   is ⭐ FENCED — the broker rejects it with ProducerFencedException.
   (This is a fencing token — Deep Dive 02 §19.)
```

### The commit protocol

```
1. beginTransaction()     — client-side only, no RPC
2. First send to a new partition → ⭐ AddPartitionsToTxn to the coordinator
3. Records are written to the partitions, marked ⭐ isTransactional
4. sendOffsetsToTransaction → ⭐ AddOffsetsToTxn; the offsets are written
   to __consumer_offsets as part of the transaction
5. commitTransaction():
     a) coordinator writes PREPARE_COMMIT to __transaction_state
     b) ⭐ coordinator writes a COMMIT MARKER (a control record) to
        EVERY partition involved
     c) coordinator writes COMPLETE_COMMIT
```

### ⭐ The LSO — the part with operational consequences

```
⭐ LSO (Last Stable Offset): the offset of the earliest record belonging
   to a STILL-OPEN transaction.

  isolation.level = read_uncommitted (default)
      → ⭐ consumers read up to the HIGH WATERMARK, including records
        from transactions that may still abort

  isolation.level = read_committed
      → ⭐ consumers read only up to the LSO, and the client filters out
        aborted records using the .txnindex file
```

```
  Partition log:
  ┌──────────────────────────────────────────────────────────────┐
  │ ...committed... │ TXN-A (open) │ TXN-B (committed) │ ...      │
  └─────────────────┴──────────────┴───────────────────┴──────────┘
                    ▲                                   ▲
                  ⭐ LSO                               HW

⭐ A read_committed consumer CANNOT read past the LSO — even though
   TXN-B has committed and sits after it. Transactions are exposed
   in offset order.
```

---

## 17. Traced scenario — a hung transaction stalls consumers

The operational failure that surprises people, and follows directly from §16.

```
SETUP: A stream-processing application uses transactions.
       isolation.level = read_committed on the downstream consumers.
       transaction.timeout.ms = 60000 (the default).

14:00:00  Instance 7 calls beginTransaction() and sends records to
          partitions orders-3 and orders-7.
          ⭐ LSO for orders-3 is pinned at offset 48,291,042.

14:00:03  ⭐ Instance 7's JVM enters a long GC pause / the pod is
          CPU-throttled / the process hangs.
          It never calls commitTransaction() or abortTransaction().

14:00:03+ ⭐ Downstream read_committed consumers of orders-3 CANNOT
          ADVANCE PAST offset 48,291,042.

          They are not lagging because they are slow.
          ⭐ They are BLOCKED — the data is there, committed by other
             producers, but it sits AFTER an open transaction.

14:00:30  Monitoring shows: consumer lag climbing steadily, consumers
          idle (0% CPU), broker healthy, no errors anywhere.
          ⭐ Every dashboard looks fine except lag.

14:01:03  ⭐ transaction.timeout.ms (60 s) expires.
          The coordinator ABORTS the transaction and writes ABORT markers.
          ⭐ The LSO advances. Consumers resume and catch up in a burst.
```

### Diagnosing it

```bash
# ⭐ The tell-tale sign: LSO far behind HW
kafka-get-offsets.sh --bootstrap-server localhost:9092 \
  --topic orders --partitions 3          # gives the HW

# Compare against what a read_committed consumer can actually reach.
# Or check the transaction state directly:
kafka-transactions.sh --bootstrap-server localhost:9092 list
kafka-transactions.sh --bootstrap-server localhost:9092 describe \
  --transactional-id my-app-7
# ⭐ State: Ongoing  StartTimeMs: 1757673600000  TransactionTimeoutMs: 60000

# ⭐ Force-abort a genuinely hung transaction (last resort)
kafka-transactions.sh --bootstrap-server localhost:9092 abort \
  --topic orders --partition 3 --start-offset 48291042
```

### The mitigations

```properties
# ⭐ 1. Shorten the timeout so a hang self-heals faster
transaction.timeout.ms = 15000
#    ⚠ must be ≤ transaction.max.timeout.ms on the broker (default 15 min)
#    ⚠ too short and legitimate slow transactions abort spuriously

# ⭐ 2. Keep transactions SHORT. Process fewer records per transaction.
max.poll.records = 100

# ⭐ 3. ALERT on LSO lag specifically, not just consumer lag.
#    They look identical on a lag dashboard and have completely
#    different causes and fixes.
```

> **This is the transactional equivalent of PostgreSQL's orphaned prepared transaction (Deep Dive 08 §25)** — an unresolved coordinator state that blocks unrelated work, is invisible in the obvious metrics, and requires a specific tool to diagnose. The pattern recurs across systems: **any two-phase protocol has a "stuck in phase one" failure mode that blocks readers.**

---

## 18. Consumer internals: fetch and offset storage

```properties
fetch.min.bytes = 1                  # ⭐ raise to 64KB-1MB for throughput
fetch.max.wait.ms = 500
max.partition.fetch.bytes = 1048576  # 1 MB per partition per fetch
fetch.max.bytes = 52428800           # 50 MB per fetch total
max.poll.records = 500               # ⭐ records returned per poll()
max.poll.interval.ms = 300000        # ⭐ 5 min — the rebalance killer (§19)
session.timeout.ms = 45000
heartbeat.interval.ms = 3000
```

### The two timeouts, and why both exist

```
⭐ SINCE KAFKA 0.10.1, HEARTBEATS ARE ON A SEPARATE BACKGROUND THREAD.

  session.timeout.ms (45 s)
      Governs the ⭐ HEARTBEAT THREAD. If heartbeats stop for this long,
      the consumer is considered dead.
      → detects a CRASHED or PARTITIONED consumer.

  ⭐ max.poll.interval.ms (5 min)
      Governs the ⭐ PROCESSING LOOP. If poll() is not called again
      within this window, the consumer is considered stuck.
      → detects a HUNG or SLOW consumer.
      ⭐ The heartbeat thread keeps sending heartbeats while processing,
         so session.timeout alone would NOT catch a slow consumer.
```

```
⭐ THE CLASSIC BUG (Chapter 07 §7.1's rebalance loop, explained):

  Each record takes 800 ms to process. max.poll.records = 500.
  → one poll() batch takes 500 × 0.8 = ⭐ 400 seconds.
  → max.poll.interval.ms = 300 s is exceeded.
  → ⭐ the consumer is EVICTED mid-batch. Rebalance.
  → the partition is reassigned; the new owner reprocesses from the
    last commit and hits the same limit.
  → ⭐ PERMANENT REBALANCE LOOP. No progress, ever.

⭐ THE FIX: reduce max.poll.records (to 50), not raise
   max.poll.interval.ms. Smaller batches mean faster feedback and a
   shorter redelivery window on failure.
```

### Offset storage

```
⭐ Offsets live in the internal topic __consumer_offsets:
     50 partitions (offsets.topic.num.partitions)
     ⭐ cleanup.policy = compact  (§21)
     replication.factor = 3 (offsets.topic.replication.factor)

  KEY:   (group.id, topic, partition)
  VALUE: (offset, leaderEpoch, metadata, commitTimestamp)

⭐ Partition = hash(group.id) % 50. So one group's offsets all live on
   one partition, whose leader is that group's ⭐ GROUP COORDINATOR.

⭐ Because the topic is COMPACTED, only the latest offset per key
   survives — so the topic stays small regardless of commit frequency.
```

```bash
# ⭐ Read the offsets topic directly (useful when consumer-groups tooling misleads)
kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic __consumer_offsets --from-beginning \
  --formatter "kafka.coordinator.group.GroupMetadataManager\$OffsetsMessageFormatter"
```

---

## 19. ⭐ Rebalance protocols: eager, cooperative, static

Rebalances are Kafka's most common operational pain, and the protocol you choose changes their impact completely.

### Protocol 1 — Eager (the old default)

```
⭐ STOP-THE-WORLD.

  1. A member joins or leaves → the coordinator triggers a rebalance
  2. ⭐ EVERY consumer REVOKES ALL of its partitions
  3. ⭐ ALL consumers rejoin the group
  4. The leader computes a new assignment
  5. Everyone receives their new partitions and resumes

⭐ DURING STEPS 2-5, NOBODY CONSUMES ANYTHING.

  With 50 consumers and a 30-second assignment computation,
  ⭐ the entire consumer group is stalled for 30+ seconds —
  including for the 48 consumers whose partitions did not change.
```

Assignors: `RangeAssignor` (default, and it distributes unevenly across topics), `RoundRobinAssignor`.

### Protocol 2 — Cooperative Sticky ⭐

```properties
partition.assignment.strategy = org.apache.kafka.clients.consumer.CooperativeStickyAssignor
```

```
⭐ INCREMENTAL. Two rebalance rounds, but no full stop.

  ROUND 1: everyone reports their current assignment. The leader computes
           the target assignment and revokes ⭐ ONLY the partitions that
           must move.
  ROUND 2: the revoked partitions are assigned to their new owners.

⭐ CONSUMERS KEEP PROCESSING PARTITIONS THAT ARE NOT MOVING.

  Adding one consumer to a 50-consumer group moves ~2% of partitions.
  ⭐ 98% of the group never stops.
```

```
⚠ MIGRATION REQUIRES TWO ROLLING RESTARTS (you cannot mix protocols):
  1. Deploy with both assignors listed:
       partition.assignment.strategy = CooperativeStickyAssignor, RangeAssignor
  2. Once every member is on that config, deploy with only
       partition.assignment.strategy = CooperativeStickyAssignor
```

### Protocol 3 — Static membership ⭐

```properties
group.instance.id = consumer-7        # ⭐ a STABLE, unique identity
session.timeout.ms = 300000           # ⭐ raise it — 5 minutes
```

```
⭐ A consumer with a group.instance.id keeps its identity and its
   PARTITION ASSIGNMENT across restarts.

  Consumer restarts (a deploy, a pod reschedule):
    ⭐ It rejoins with the same instance ID within session.timeout.ms
    ⭐ NO REBALANCE IS TRIGGERED AT ALL.
    ⭐ It resumes exactly the partitions it had.

⭐ THIS IS THE SINGLE BIGGEST WIN FOR ROLLING DEPLOYS.

  Without it: a 20-pod rolling restart triggers ⭐ 40 REBALANCES
              (one per pod leaving, one per pod rejoining).
  With it:    ⭐ ZERO rebalances, provided each pod restarts within
              session.timeout.ms.
```

```yaml
# ⭐ In Kubernetes, derive it from the StatefulSet pod ordinal
env:
  - name: POD_NAME
    valueFrom: { fieldRef: { fieldPath: metadata.name } }
# then: group.instance.id = ${POD_NAME}
```

### Protocol 4 — KIP-848, the new protocol

```
⭐ Kafka 3.7+ (preview), GA in 4.0: the next-generation consumer
   rebalance protocol.

  • ⭐ Assignment computed SERVER-SIDE by the group coordinator,
    not by an elected consumer leader
  • ⭐ Fully incremental — no stop-the-world round at all
  • No dependence on a client-side leader, so a slow consumer cannot
    stall the group
  • ⭐ Dramatically faster for large groups

⭐ This removes most of the reason the previous three protocols needed
   careful tuning. If you are on Kafka 4.x, use it.
```

> **The practical recommendation today: static membership + cooperative sticky.** Together they eliminate rebalances on deploys and make the unavoidable ones incremental. That combination solves the large majority of real-world consumer-group pain.

---

## 20. Consumer lag mechanics

```
⭐ LAG = (log end offset of the partition) − (consumer's committed offset)
```

```bash
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group billing
```
```
GROUP   TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG   CONSUMER-ID
billing orders  0          48291042        48291051        9     consumer-1-abc
billing orders  1          48287103        48291204        ⭐4101 consumer-2-def
billing orders  2          48290998        48291012        14    consumer-3-ghi
billing orders  3          0               48291204    ⭐48291204 ⭐ -
                                                                   ^^^^^^^^^^
                                                        ⭐ NO CONSUMER ASSIGNED
```

### Reading lag correctly

```
⭐ 1. LAG IN RECORDS IS MISLEADING ON ITS OWN.
      1 M records of a 200k msg/s topic = 5 seconds.
      1,000 records of a 2 msg/s topic  = 8 minutes.
      ⭐ ALWAYS compute lag in TIME, using the .timeindex:
         consumer.offsetsForTimes() to find the timestamp at the
         committed offset, then subtract from now().

⭐ 2. A MISSING CONSUMER-ID means no consumer is assigned. That is not
      lag — that is an outage on that partition.

⭐ 3. UNEVEN LAG ACROSS PARTITIONS usually means a HOT KEY —
      one partition is receiving disproportionate traffic
      (Chapter 07 §7.5's partition key problem).

⭐ 4. LAG THAT IS FLAT AND HIGH (not growing) with an idle consumer
      often means an LSO stall (§17), not slow processing.
```

```
⭐ THE FOUR LAG PATTERNS AND THEIR CAUSES:

  Growing steadily     → consumer cannot keep up. Add consumers
                         (up to partition count) or optimise processing.
  Sawtooth             → batch processing; normal if the peak is within SLA.
  Spike then recovery  → a restart or a rebalance. Check rebalance rate.
  ⭐ Flat, high, idle   → LSO stall (§17), or a poison message being
                         retried forever, or a paused consumer.
```

---

## 21. Retention and log compaction internals

### Time and size retention

```properties
log.retention.ms = 604800000       # 7 days
log.retention.bytes = -1           # unlimited (per partition!)
log.retention.check.interval.ms = 300000
```

```
⭐ RETENTION IS EVALUATED PER SEGMENT, NOT PER RECORD.

  A segment is eligible for deletion when its ⭐ LARGEST timestamp is
  older than retention.ms.

  ⭐ AND THE ACTIVE SEGMENT IS NEVER DELETED.

CONSEQUENCE: on a low-traffic topic with log.segment.bytes = 1 GB,
the active segment may take weeks to fill.
⭐ Data far older than retention.ms is retained, because it is in the
   active segment.

⭐ FIX: set log.roll.ms (e.g. 1 day) so segments roll on time as well
   as on size.
```

### Log compaction

```properties
cleanup.policy = compact              # or "compact,delete" for both
min.cleanable.dirty.ratio = 0.5       # ⭐ start cleaning at 50% dirty
min.compaction.lag.ms = 0             # ⭐ minimum age before compaction
delete.retention.ms = 86400000        # ⭐ how long tombstones survive
log.cleaner.threads = 1               # ⭐ often too few
```

### How the cleaner works

```
The log is conceptually split:

  ┌──────────── CLEANED (tail) ────────────┬──── DIRTY (head) ────┐
  │ one entry per key, latest value         │ arbitrary, uncompacted│
  └─────────────────────────────────────────┴───────────────────────┘
                                             ▲
                                          cleaner point

1. ⭐ Build an OFFSET MAP of the DIRTY section: key → highest offset.
   (An in-memory hash, bounded by log.cleaner.dedupe.buffer.size.)
2. ⭐ Recopy the segments, keeping a record ONLY IF its offset is the
   highest for its key.
3. Swap in the new segments, delete the old ones.
```

```
⭐ GUARANTEES COMPACTION PROVIDES:
   • ⭐ OFFSETS NEVER CHANGE. A record keeps its offset forever.
   • ⭐ ORDER IS PRESERVED.
   • Reading from the beginning yields at least the final value for
     every key.
   • ⭐ The head of the log is never compacted, so a consumer reading
     recent data sees every individual update.
```

### Tombstones

```
⭐ A record with a NULL VALUE is a TOMBSTONE: "this key is deleted."

  Compaction keeps the tombstone for ⭐ delete.retention.ms (24 h default)
  AFTER the segment containing it has been compacted, then removes it.

⭐ WHY THE DELAY: a consumer that is far behind must have a chance to
   SEE the tombstone. If it were removed immediately, a slow consumer
   reading from the beginning would never learn the key was deleted and
   would keep the old value in its local state forever.

   ⭐ THIS IS THE SAME REASONING AS CASSANDRA'S gc_grace_seconds
      (Deep Dive 09 §14) — tombstones must outlive the slowest reader.
```

```
⭐ THE OPERATIONAL TRAP: log.cleaner.threads = 1 by default.

  On a broker hosting many compacted partitions (especially
  __consumer_offsets with 50 partitions), one cleaner thread cannot
  keep up. Compacted topics grow without bound, and
  ⭐ __consumer_offsets growing unboundedly eventually breaks
     group coordination.

  → raise log.cleaner.threads to 2-4, and monitor
    kafka.log:type=LogCleanerManager,name=max-dirty-percent
```

---

## 22. KRaft: Kafka's own Raft

```
⭐ ZooKeeper is REMOVED in Kafka 4.0. KRaft is the only mode.
```

```
BEFORE (ZooKeeper):
   Brokers ──► ZooKeeper (cluster metadata, controller election)
   ⭐ One broker is elected CONTROLLER; it reads all metadata from ZK
      into memory at startup.
   ⭐ Controller failover = re-reading everything from ZK.
      With 100k partitions this took MINUTES.

AFTER (KRaft):
   ⭐ A quorum of CONTROLLER nodes runs Raft (Deep Dive 01) over an
      internal ⭐ __cluster_metadata topic.
   ⭐ Brokers are FOLLOWERS of that metadata log — they replicate it
      exactly like any other partition.
```

```
⭐ WHAT THIS BUYS:
   • ⭐ Controller failover in SECONDS, not minutes (the new controller
     already has the metadata log — it is a Raft leader election,
     Deep Dive 01 §6)
   • ⭐ Far more partitions supported (millions vs ~200k)
   • One system to operate instead of two
   • Metadata changes are ordered, versioned and replayable
```

```properties
# Controller quorum — ⭐ 3 or 5, odd, exactly as Deep Dive 01 §3
process.roles = broker,controller       # combined (dev / small clusters)
process.roles = controller              # ⭐ dedicated (production)
controller.quorum.voters = 1@c1:9093,2@c2:9093,3@c3:9093
```

```bash
# ⭐ Inspect the metadata quorum
kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status
# ClusterId:  4L6g3nShT-eMCtK--X86sw
# LeaderId:   2
# LeaderEpoch: 14
# HighWatermark: 482910
# ⭐ CurrentVoters: [1,2,3]
# ⭐ CurrentObservers: [101,102,103]     ← the brokers
```

> **Everything in Deep Dive 01 applies directly here.** The controller quorum is a Raft group: odd-sized, majority quorum, leader election with randomised timeouts, and the same fsync requirement on the metadata log. If you understood that deep dive, you already understand KRaft's failure modes.

---

## 23. Tiered storage

```properties
remote.storage.enable = true
local.retention.ms = 86400000        # ⭐ 1 day on local disk
retention.ms = 31536000000           # ⭐ 1 year total (rest in S3)
```

```
  ┌──────────────────── LOCAL DISK ────────────────────┐
  │  active segment  │  recent segments (24 h)          │
  └──────────────────┴──────────────────────────────────┘
                              │ ⭐ uploaded asynchronously
                              ▼
  ┌────────────────── REMOTE (S3 / GCS / HDFS) ────────┐
  │  older segments — up to retention.ms                │
  └─────────────────────────────────────────────────────┘
```

```
⭐ WHAT IT CHANGES ECONOMICALLY:

  Before: 1 year of retention × 3 replicas on local NVMe.
          100 TB of data → ⭐ 300 TB of provisioned SSD.

  After:  24 h locally × 3 replicas (~1 TB of SSD)
          + 100 TB in S3 (⭐ single copy — S3 handles its own durability)

  ⭐ Cost reduction is typically 5-10× for long-retention topics.
```

```
⭐ TRADE-OFFS:
   • ⭐ Reads of remote data are SLOW (S3 latency: tens to hundreds of ms)
     → fine for backfills and replays; unsuitable for a live consumer
       that has fallen behind past local.retention
   • ⭐ A consumer that falls behind past local retention suddenly gets
     10-100× worse fetch latency — a latency cliff, not a gradual decline
   • Compacted topics are not supported (as of 3.9)
   • Adds an operational dependency on object storage availability
```

**The architectural significance:** tiered storage makes Kafka viable as a **long-term event store** rather than only a transport buffer. Keeping a year of events for replay (Chapter 07 §7.8's killer feature) stops being prohibitively expensive — which strengthens the case for event sourcing and for rebuilding consumer state from the log.

---

## 24. Broker tuning

```properties
# ═══ THREADS ═══
num.network.threads = 8              # ⭐ ~ number of cores; handles socket I/O
num.io.threads = 16                  # ⭐ 2× cores; handles disk I/O + purgatory
num.replica.fetchers = 4             # ⭐ default 1 — FAR TOO LOW.
                                     #   This is the #1 cause of replica lag.
background.threads = 10

# ═══ LOG ═══
log.segment.bytes = 1073741824
log.roll.ms = 86400000               # ⭐ roll daily so retention works (§21)
log.retention.check.interval.ms = 300000
log.cleaner.threads = 4              # ⭐ default 1 — too few (§21)
log.cleaner.dedupe.buffer.size = 268435456

# ═══ REPLICATION ═══
replica.lag.time.max.ms = 30000
replica.fetch.max.bytes = 10485760   # ⭐ raise from 1 MB for high throughput
replica.socket.receive.buffer.bytes = 1048576
min.insync.replicas = 2              # ⭐ cluster default; override per topic
unclean.leader.election.enable = false  # ⭐ §12

# ═══ SOCKETS ═══
socket.send.buffer.bytes = 1048576
socket.receive.buffer.bytes = 1048576
socket.request.max.bytes = 104857600

# ═══ ⭐ DO NOT ENABLE FSYNC (§6) ═══
# log.flush.interval.messages    — leave unset
# log.flush.interval.ms          — leave unset

# ═══ RACK AWARENESS (§6) ═══
broker.rack = eu-west-1a             # ⭐ spreads replicas across AZs
```

### JVM

```bash
# ⭐ SMALL HEAP. This is the counter-intuitive one (§4).
export KAFKA_HEAP_OPTS="-Xms6g -Xmx6g"

export KAFKA_JVM_PERFORMANCE_OPTS="\
  -XX:+UseG1GC \
  -XX:MaxGCPauseMillis=20 \
  -XX:InitiatingHeapOccupancyPercent=35 \
  -XX:+ExplicitGCInvokesConcurrent \
  -XX:+UseAES -XX:+UseAESIntrinsics"       # ⭐ matters if TLS is on (§5)
```

### OS

```bash
# ⭐ File descriptors: one per segment file × 3 (log, index, timeindex),
#    plus one per connection. Thousands of partitions → 100k+ FDs.
ulimit -n 100000

# ⭐ Prefer page cache retention over swapping
sysctl vm.swappiness=1

# ⭐ Allow more dirty pages before forcing writeback (smooths flush spikes)
sysctl vm.dirty_background_ratio=5
sysctl vm.dirty_ratio=60

# Filesystem: XFS is recommended over ext4 for Kafka
mount -o noatime /dev/nvme0n1 /var/lib/kafka
```

---

## 25. Monitoring: the JMX metrics that matter

```
⭐ TIER 1 — ALERT IMMEDIATELY

kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions
    ⭐ MUST BE 0. Non-zero = a replica is not keeping up → durability at risk.

kafka.controller:type=KafkaController,name=OfflinePartitionsCount
    ⭐ MUST BE 0. Non-zero = a partition has NO LEADER → total outage
       for that partition.

kafka.controller:type=KafkaController,name=ActiveControllerCount
    ⭐ MUST SUM TO EXACTLY 1 across the cluster.
       0 = no controller. 2 = ⭐ SPLIT BRAIN.

kafka.controller:type=ControllerStats,name=UncleanLeaderElectionsPerSec
    ⭐ ANY non-zero value = DATA WAS DESTROYED (§12). Page someone.
```

```
⭐ TIER 2 — SATURATION

kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent
    ⭐ < 0.3 means the I/O threads are saturated → raise num.io.threads

kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent
    ⭐ < 0.3 → raise num.network.threads

kafka.server:type=ReplicaManager,name=IsrShrinksPerSec / IsrExpandsPerSec
    ⭐ Frequent shrink/expand = ISR THRASHING.
       Usually: slow disk, GC pauses, or num.replica.fetchers too low.

kafka.log:type=LogFlushStats,name=LogFlushRateAndTimeMs
    p99 flush time — the OS writeback behaviour
```

```
⭐ TIER 3 — CORRECTNESS AND EFFICIENCY

kafka.server:type=BrokerTopicMetrics,name=FetchMessageConversionsPerSec
kafka.server:type=BrokerTopicMetrics,name=ProduceMessageConversionsPerSec
    ⭐ MUST BE 0. Non-zero = zero-copy is disabled by format conversion (§5).

kafka.log:type=LogCleanerManager,name=max-dirty-percent
    ⭐ Compaction falling behind (§21)

kafka.network:type=RequestMetrics,name=TotalTimeMs,request=Produce|Fetch
    ⭐ Broken down into queue / local / remote / response time —
       tells you WHERE the latency is
```

```
⭐ CONSUMER-SIDE

records-lag-max            ⭐ per partition; also compute lag in TIME (§20)
fetch-latency-avg / -max
commit-latency-avg
⭐ rebalance-rate-per-hour  — should be near 0 with static membership (§19)
⭐ failed-rebalance-rate
last-rebalance-seconds-ago
```

---

## 26. What an architect takes from this

**1. Kafka is fast because of `sendfile` and the page cache, not because of clever data structures.** The corollary is the one people get wrong: **give Kafka a small JVM heap (6 GB) and leave the rest of RAM to the OS.**

**2. TLS disables zero-copy.** Budget ~30% more brokers when you enable it. This is a capacity decision, not a configuration toggle, and it should be made deliberately.

**3. `acks=1` loses acknowledged data silently.** The producer is told it succeeded; nothing anywhere logs a problem. `acks=all` + `min.insync.replicas=2` + `replication.factor=3` is the only defensible configuration for business data.

**4. `acks=all` means "all *in-sync* replicas".** Without `min.insync.replicas`, a shrunken ISR silently degrades it to `acks=1`. That single setting is what makes the guarantee real.

**5. Unclean leader election destroys acknowledged, already-consumed data and corrupts consumer offsets.** Leave it `false`. Alert on the metric — any non-zero value is an incident.

**6. Kafka does not fsync.** Durability comes from replication, which means **your replicas must be in different failure domains.** `broker.rack` turns a correlated power failure into an uncorrelated one, and without it the whole durability model is weaker than it looks.

**7. Static membership plus cooperative sticky assignment eliminates most rebalance pain.** A 20-pod rolling restart goes from 40 rebalances to zero. This is the highest-value consumer-side configuration change available.

**8. `max.poll.records` is the fix for rebalance loops, not `max.poll.interval.ms`.** Smaller batches give faster feedback and shorter redelivery windows.

**9. `linger.ms = 5–20` usually *improves* p99 latency** while cutting network bytes several-fold. It contradicts intuition and it is worth measuring on your workload.

**10. A hung transaction blocks `read_committed` consumers at the LSO** — lag climbs while consumers sit idle and every other dashboard looks healthy. It is the same failure shape as an orphaned prepared transaction in PostgreSQL, and it needs its own alert.

**11. Leader epochs exist because a replica's local view of "committed" is stale after a leadership change.** The same principle as fencing tokens and Raft's log matching: truncation must be driven by an authoritative epoch, never by local state.

**12. Tiered storage changes what Kafka is for.** Long retention stops being a cost problem, which makes replay and log-as-source-of-truth architectures genuinely practical — with a latency cliff for consumers that fall past local retention.

---

## Exercises

1. Dump a real segment with `kafka-dump-log.sh` and identify the batch boundaries, compression codec, producer ID and leader epoch.
2. Compute the index size for a 1 GB segment at the default `log.index.interval.bytes`. How many bytes are scanned in the worst case during a lookup?
3. Measure your brokers' `free -g` output. What fraction of RAM is page cache? Is the heap sized correctly?
4. Enable TLS on a test cluster and measure the throughput and CPU difference. Compute how many extra brokers production would need.
5. Check `FetchMessageConversionsPerSec` on your cluster. If non-zero, identify the client causing it.
6. Trace the high-watermark advancement for a batch with `acks=all` and explain why it takes two fetch rounds.
7. Reproduce the `acks=1` data loss on a test cluster: produce with `acks=1`, kill the leader immediately, and verify the message is gone.
8. Explain unclean leader election to a product owner in three sentences, including the offset-reuse consequence.
9. Explain why truncating to the local high watermark caused divergence, and how leader epochs fix it.
10. Measure batch size and compression ratio at `linger.ms` values of 0, 5 and 20 on your producer. Compare p99 latency.
11. Simulate a hung transaction and observe `read_committed` consumer lag. Write the alert that would catch it.
12. Perform a rolling restart of a consumer group with and without `group.instance.id`. Count the rebalances in each case.
13. Check `log.cleaner.threads` and `max-dirty-percent` on your cluster. Is `__consumer_offsets` being compacted fast enough?
14. Compute the cost of one year of retention for a 5 TB/month topic with and without tiered storage, using your cloud's actual prices.
15. Write the runbook entry for `UnderReplicatedPartitions > 0`. Include the three most likely causes and the diagnostic for each.

---

**Next in this series:** Deep Dive 11 — Redis Internals

**Back to:** [Deep Dives](README.md) · [Chapter 07](../07-kafka.md) · [The Map](../README.md)
