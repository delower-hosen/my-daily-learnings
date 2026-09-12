# Deep Dives

The main book is a **map**: it names things, says what problem each solves, and gives you judgement about when to use them.

This series is the **territory**. Each deep dive takes one topic and goes to mechanism level.

---

## What "deep dive" means here

The main book said:

> *"Raft has three sub-problems: leader election, log replication, and safety."*

A deep dive says: here is the complete state each node holds, here are the two RPCs field by field, here is an election traced through five nodes with a network partition in the middle, here is the exact log entry that Raft **refuses** to commit even though it is on a majority of nodes and why that rule exists, here is what happens when a node's disk write is lost, here is how etcd actually implements it, and here is how you debug it at 3 AM.

Every deep dive contains:

| Element | Meaning |
|---------|---------|
| **First principles** | Why does this problem exist at all? What breaks without it? |
| **The mechanism, step by step** | The actual algorithm, with the real state, not a summary |
| **Traced executions** | Concrete scenarios with line-by-line state tables |
| **The counter-examples** | The cases that look correct and are not — and why the rule exists |
| **Worked numbers** | Real sizes, real latencies, real arithmetic |
| **Complete implementations** | Code you could run, not illustrative fragments |
| **What real systems do** | Named systems, named settings, named defaults |
| **Production debugging** | The commands, the metrics, the symptoms, the fixes |
| **The edge cases** | The things that bite after 18 months |

**Scale of the difference:** the whole distributed-systems chapter in the map is 7,400 words. Deep dives 01–03 cover the same territory in 35,500.

---

## Published — 11 deep dives, ~117,000 words

### Part I — Distributed systems internals

| # | Deep dive | Words | Highlights |
|---|-----------|-------|-----------|
| **01** | [Consensus, Replication and Raft](01-consensus-and-raft.md) | 14.0k | Quorums derived from set intersection · complete Raft spec · six traced failure scenarios · **the Figure-8 commit rule** · why `fsync` is non-negotiable · working implementation · PreVote, CheckQuorum, leases, ReadIndex, learners · etcd internals |
| **02** | [Time, Clocks and Causality](02-time-clocks-and-causality.md) | 11.3k | How wrong clocks really are · NTP's arithmetic and the symmetry assumption that breaks it · three real leap-second outages · Lamport and vector clocks complete · **Hybrid Logical Clocks** · TrueTime and commit wait · LWW as silent data loss · seven clock-free techniques |
| **03** | [Consistency Models, Formally](03-consistency-models-formally.md) | 10.2k | Execution-history notation · six worked histories · **why linearizability composes and sequential consistency does not** · Adya's dependency graphs · write skew · snapshot isolation's read-only anomaly · CRDTs · how Jepsen finds violations |

### Part II — Data storage internals

| # | Deep dive | Words | Highlights |
|---|-----------|-------|-----------|
| **04** | [PostgreSQL MVCC and Storage](04-postgresql-mvcc-and-storage.md) | 12.4k | The 8 KB page byte by byte · tuple header field by field · **the visibility algorithm implemented** · hint bits and why `SELECT` writes to disk · **HOT updates** · bloat arithmetic · **the xmin horizon** · a traced 40 GB bloat incident · the **wraparound emergency** · TOAST |
| **05** | [B-trees, Indexes and Access Methods](05-btrees-indexes-and-access-methods.md) | 12.3k | Fan-out and height arithmetic · a traced page split · **the right-link trick** · why B-trees never merge pages · **why UUIDv4 keys cost you four different ways** · deduplication and bottom-up deletion · GIN's pending list · GiST penalty/picksplit · BRIN's correlation requirement · the index audit |
| **06** | [The Query Planner and Executor](06-query-planner-and-executor.md) | 12.5k | Cost formulas with constants · selectivity computed by hand from histograms and MCVs · **the independence assumption and extended statistics** · all three join algorithms with spill mechanics · **how `work_mem` is really consumed** · parallel query · **the generic plan trap** · a systematic bad-plan procedure |
| **07** | [WAL, Checkpoints and Recovery](07-wal-checkpoints-and-recovery.md) | 12.0k | WAL records and LSNs · the write path · **torn pages and full-page writes** · a traced checkpoint storm (34× WAL reduction) · all five `synchronous_commit` levels · **why PostgreSQL needs no UNDO phase** · PITR traced · **timelines** · `pg_rewind` · logical decoding and `REPLICA IDENTITY` |
| **08** | [Transactions, Locking and SSI](08-transactions-locking-and-ssi.md) | 11.9k | The full lock conflict matrix · **why row locks are not in the lock manager** · MultiXacts and their **second wraparound** · four traced deadlocks including two that look impossible · **the DDL queue-blocking incident** · the safe-DDL catalogue · **SSI's dangerous-structure detection** traced |
| **09** | [LSM Trees and Write-Optimised Storage](09-lsm-trees-and-write-optimised-storage.md) | 9.5k | SSTables byte by byte · the read path through bloom filters · bloom filter maths · **the RUM conjecture** · four compaction strategies with amplification arithmetic · **tombstones** · traced Cassandra tombstone hell · **write stalls and compaction debt** · WiscKey · B-tree vs LSM decision |

### Part III — Platform internals

| # | Deep dive | Words | Highlights |
|---|-----------|-------|-----------|
| **10** | [Kafka Internals](10-kafka-internals.md) | 9.4k | The partition directory · record batches · **zero-copy and the two settings that disable it** · LEO/HW/ISR traced · **how `acks=1` loses data** · unclean leader election traced · **leader epochs and the divergence bug** · idempotent producer · **transactions and the LSO stall** · all four rebalance protocols · KRaft |
| **11** | [Redis Internals](11-redis-internals.md) | 9.4k | What "single-threaded" means in Redis 7 · **encodings and their one-way thresholds** · expiration sampling · approximated LRU and LFU · **the fork latency problem and THP** · COW amplification · **a traced cluster failover losing writes** · the blocking commands · latency diagnosis procedure |

---

## Planned

| # | Deep dive | Will cover |
|---|-----------|-----------|
| 12 | TCP Mechanics | Congestion control algorithms, bandwidth-delay product, buffer bloat, TIME_WAIT, socket tuning, what `ss` output means |
| 13 | TLS and Applied Cryptography | Handshake message by message, cipher suite mechanics, certificate validation, session resumption, 0-RTT replay |
| 14 | HTTP/1.1, /2 and /3 on the wire | Framing, HPACK/QPACK, flow control, QUIC streams and loss recovery, connection migration |
| 15 | Containers and the Kernel | Namespaces and cgroups v2 in detail, CFS quota throttling, overlayfs, seccomp, the container escape surface |
| 16 | Concurrency, Memory Models and GC | Memory ordering, false sharing, lock-free structures, GC algorithms and tuning, allocation profiling |

---

## Reading orders

**If you work on PostgreSQL daily:** 04 → 05 → 06 → 08 → 07. This is the highest-value block for most application engineers — it explains where nearly every production database incident comes from.

**If you are preparing for distributed systems work:** 01 → 02 → 03, in order. They build on each other.

**If you operate Kafka or Redis:** read 10 or 11 directly; each is self-contained given its map chapter.

**If you are choosing a storage engine:** 05 (B-trees) then 09 (LSM), then the decision section at the end of 09.

---

## How to read these

**Slowly, with a terminal open.** Each traced scenario is worth reproducing — most can be run locally with three containers, a `psql` session, or a `tc netem` rule.

**The map chapter is the prerequisite.** Each deep dive names it at the top.

**You do not need all of them.** Read the deep dives for areas where your work demands mechanism-level understanding. The map is sufficient for the rest.

---

**Back to:** [The System Architect's Map](../README.md)
