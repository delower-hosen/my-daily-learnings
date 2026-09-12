# Deep Dives

The main book is a **map**: it names things, says what problem each solves, and gives you judgement about when to use them. That is what you asked for first, and it stays useful as an index.

This series is the **territory**. Each deep dive takes one topic and goes to mechanism level.

---

## What "deep dive" means here

The main book said:

> *"Raft has three sub-problems: leader election, log replication, and safety."*

A deep dive says: here is the complete state each node holds, here are the two RPCs field by field, here is an election traced through five nodes with a network partition in the middle, here is the exact log entry that Raft **refuses** to commit even though it is on a majority of nodes and why that rule exists, here is what happens when a node's disk write is lost, here is how etcd actually implements it, and here is how you debug it at 3 AM.

Concretely, every deep dive contains:

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

## Published

### Part I — Distributed systems internals

| # | Deep dive | Words | Covers |
|---|-----------|-------|--------|
| **01** | [Consensus, Replication and Raft](01-consensus-and-raft.md) | 14,000 | Quorums derived from set intersection · complete Raft spec · six traced failure scenarios · **the Figure-8 commit rule** · why `fsync` is non-negotiable · working implementation · PreVote, CheckQuorum, leases, ReadIndex, learners · membership changes · snapshots · etcd internals · production debugging |
| **02** | [Time, Clocks and Causality](02-time-clocks-and-causality.md) | 11,300 | How wrong clocks actually are · NTP's arithmetic and the symmetry assumption that breaks it · stepping vs slewing · three real leap-second outages · happens-before formally · Lamport and vector clocks complete · version vectors and DVVs · **Hybrid Logical Clocks** · TrueTime and commit wait · LWW as silent data loss · seven clock-free techniques · clock skew in tracing |
| **03** | [Consistency Models, Formally](03-consistency-models-formally.md) | 10,200 | Execution-history notation · linearizability defined and applied to six worked histories · **why linearizability composes and sequential consistency does not** · the four-quadrant map · isolation levels as cycle-forbidding · Adya's DSG · write skew · snapshot isolation's read-only anomaly · causal consistency at the CAP boundary · session guarantees · CRDTs and strong eventual consistency · what real systems provide · how Jepsen finds violations · testing your own system |

### Part II — Data storage internals

| # | Deep dive | Words | Covers |
|---|-----------|-------|--------|
| **04** | [PostgreSQL MVCC and Storage](04-postgresql-mvcc-and-storage.md) | 12,400 | The 8 KB page byte by byte · tuple header field by field · what a row really costs (and column-order padding) · snapshots and the **visibility algorithm implemented** · hint bits and why `SELECT` writes to disk · ctid chains · **HOT updates** · bloat arithmetic · VACUUM phase by phase · **the xmin horizon** and the six things that block it · a traced 40 GB bloat incident · autovacuum tuning · freezing and the **wraparound emergency** · TOAST · visibility map and index-only scans · vs Oracle/InnoDB/SQL Server |

---

## Planned

| # | Deep dive | Will cover |
|---|-----------|-----------|
| 05 | B-trees, Indexes and Access Methods | Page splits, fill factor, why UUIDv4 keys bloat, index-only scans, GIN/GiST/BRIN internals, bitmap scans, correlation and clustering |
| 06 | The Query Planner and Executor | Cost model arithmetic, selectivity estimation, statistics and histograms, join algorithms and memory, why estimates go wrong, plan stability |
| 07 | Write-Ahead Logging, Checkpoints and Recovery | Record format, LSNs, full-page writes, checkpoint tuning, crash recovery, PITR mechanics, logical decoding |
| 08 | Transactions, Locking and SSI | Lock modes and the lock manager, deadlock detection, SSI's dangerous structures, predicate locks, retry design |
| 09 | LSM Trees and Write-Optimised Storage | Memtables, SSTables, compaction strategies, read/write/space amplification, bloom filters, RocksDB tuning |
| 10 | Kafka Internals | Log segments, the page cache and zero-copy, ISR mechanics, the replication protocol, exactly-once internals, rebalance protocols |
| 11 | Redis Internals | Data structure encodings, the event loop, expiration and eviction algorithms, persistence internals, cluster resharding |
| 12 | TCP Mechanics | Congestion control algorithms, the bandwidth-delay product, buffer bloat, keepalives, TIME_WAIT, socket tuning |
| 13 | TLS and Applied Cryptography | Handshake message by message, cipher suite mechanics, certificate validation, session resumption, 0-RTT and replay |
| 14 | HTTP/1.1, /2 and /3 on the wire | Framing, HPACK/QPACK, flow control, QUIC streams and loss recovery, connection migration |
| 15 | Containers and the Kernel | Namespaces and cgroups v2 in detail, the CFS quota throttling mechanism, overlayfs, seccomp, container escape surface |
| 16 | Concurrency, Memory Models and GC | Memory ordering, false sharing, lock-free structures, GC algorithms and tuning, allocation profiling |

---

## How to read these

**Slowly, with a terminal open.** These are not chapters to skim. Each traced scenario is worth reproducing — most can be run locally with three containers and a `tc netem` rule, or a single `psql` session.

**The map chapter is the prerequisite.** Each deep dive names it at the top and assumes you have read it.

**You do not need all of them.** Read the deep dives for areas where your work demands mechanism-level understanding. The map is sufficient for the rest — that was the original point and it is still true.

---

**Back to:** [The System Architect's Map](../README.md)
