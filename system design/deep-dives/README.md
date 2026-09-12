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
| **Traced executions** | Concrete scenarios with node-by-node, line-by-line state tables |
| **The counter-examples** | The cases that look correct and are not — and why the rule exists |
| **Worked numbers** | Real sizes, real latencies, real arithmetic |
| **Complete implementations** | Code you could run, not illustrative fragments |
| **What real systems do** | Named systems, named settings, named defaults |
| **Production debugging** | The commands, the metrics, the symptoms, the fixes |
| **The edge cases** | The things that bite after 18 months |

---

## The series

### Part I — Distributed systems internals

| # | Deep dive | Covers |
|---|-----------|--------|
| **01** | [Consensus, Replication and Raft](01-consensus-and-raft.md) | Quorums from first principles · Raft complete · the Figure-8 commit rule · split brain · membership changes · snapshots · linearizable reads · etcd internals |
| 02 | Time, Clocks and Causality | (planned) |
| 03 | Consistency Models, Formally | (planned) |
| 04 | Failure Detection and Membership | (planned) |

### Part II — Data storage internals

| # | Deep dive | Covers |
|---|-----------|--------|
| 05 | PostgreSQL MVCC and Storage | (planned) |
| 06 | B-trees, Indexes and the Access Methods | (planned) |
| 07 | The Query Planner and Executor | (planned) |
| 08 | Transactions, Isolation and SSI | (planned) |
| 09 | Write-Ahead Logging and Recovery | (planned) |
| 10 | LSM Trees and Write-Optimised Storage | (planned) |

### Part III — Network internals

| # | Deep dive | Covers |
|---|-----------|--------|
| 11 | TCP Mechanics | (planned) |
| 12 | TLS Handshakes and Cryptography | (planned) |
| 13 | HTTP/1.1, /2 and /3 on the wire | (planned) |

### Part IV — Platform internals

| # | Deep dive | Covers |
|---|-----------|--------|
| 14 | Kafka Internals | (planned) |
| 15 | Redis Internals | (planned) |
| 16 | Container and Kernel Internals | (planned) |
| 17 | Concurrency, Memory Models and GC | (planned) |

---

## How to read these

**Slowly, with a terminal open.** These are not chapters to skim. Each traced scenario is worth reproducing yourself — most of them can be run locally with three containers and a `tc netem` rule.

**The main book chapter is the prerequisite.** Each deep dive assumes you have read its map chapter and names which one at the top.

**You do not need all of them.** Read the deep dives for the areas where your work demands mechanism-level understanding. The map is sufficient for the rest — that was the original point and it is still true.

---

**Back to:** [The System Architect's Map](../README.md)
