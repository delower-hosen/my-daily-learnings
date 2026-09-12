# Deep Dive 03 — Consistency Models, Formally

**Prerequisite:** [Chapter 05 — Distributed Systems](../05-distributed-systems.md) §5.5 · [Deep Dive 02](02-time-clocks-and-causality.md)

**What the map said:** *"Linearizable → Sequential → Causal → Read-your-writes → Eventual. Choose per operation."*

**What this deep dive does:** defines each model precisely enough to *prove* whether a given execution satisfies it, shows worked histories that separate the models, explains why linearizability composes and sequential consistency does not (and why that single fact shapes system architecture), maps the transaction isolation hierarchy onto the same framework, covers CRDTs and strong eventual consistency, surveys what real systems actually provide with their specific settings, and shows how Jepsen finds violations — including how to test your own system.

---

## Contents

```
1.  Three different things called "consistency"
2.  Notation: execution histories
3.  Linearizability — the definition
4.  Worked histories — linearizable or not?
5.  The composability property ⭐ and why it matters architecturally
6.  Sequential consistency, and why it does not compose
7.  The four-quadrant map: linearizable, serializable, and the two others
8.  Transaction isolation as a consistency hierarchy
9.  The anomaly catalogue, with cycles
10. Adya's formalism: cycles in the dependency graph
11. Snapshot isolation, precisely
12. Causal consistency — the strongest available model under partition
13. The session guarantees, formally
14. Eventual consistency: what it does and does not promise
15. Strong eventual consistency and CRDTs
16. The complete hierarchy
17. What real systems actually provide
18. Jepsen: how violations are found
19. Testing your own system
20. Choosing a model: the decision procedure
21. What an architect takes from this
```

---

## 1. Three different things called "consistency"

The word is overloaded across three fields, and conversations derail when two people mean different things by it.

| Field | "Consistency" means | Example |
|-------|--------------------|---------|
| **Databases (the C in ACID)** | The database enforces the constraints you declared | A `CHECK (balance >= 0)` is never violated |
| **Distributed systems (the C in CAP)** | **Linearizability** — the system behaves as if there is one copy | A read never returns a value older than a completed write |
| **Replication / caching** | How stale a copy may be | "Replicas converge within 2 seconds" |

**These are genuinely unrelated.** A database can be perfectly ACID-consistent and not remotely linearizable. A linearizable key-value store has no notion of ACID's C at all.

**Worse, ACID's "C" is the odd one out.** Atomicity, Isolation and Durability are properties the *system* provides. Consistency-in-ACID is a property *you* provide by declaring constraints; the database merely refuses transactions that violate them. Several authors have argued it is in the acronym mainly because ACID is pronounceable and AID is not.

**This deep dive is about the second and third senses.** When you see "consistency" below, it means "what guarantees does the system make about what a read can return".

> **Practical habit:** when anyone says "strongly consistent", ask *"linearizable, serializable, or strictly serializable?"* Those are three different products (§7). The answer, or the absence of one, tells you a great deal.

---

## 2. Notation: execution histories

To reason precisely, we need to write down what happened. A **history** records the invocation and response of every operation, with their real-time positions.

```
Each operation has TWO events:
    invocation:  the client issues it
    response:    the client receives the result

An operation TAKES TIME. It is an interval, not a point.
```

```
Notation used throughout:

  C1: |--- W(x,1) ---|                     client 1 writes x=1
  C2:        |--- R(x) → 1 ---|            client 2 reads x, gets 1
              ↑              ↑
          invocation      response

  Time flows left to right. Real time, as an omniscient observer would see it.
```

**Two operations are *concurrent* if their intervals overlap.** Two operations are *ordered in real time* if one's response precedes the other's invocation.

```
C1: |--- A ---|
C2:                 |--- B ---|        A precedes B in real time  (A <ʳᵗ B)

C1: |--- A ---------|
C2:        |--- B ---------|           A and B are CONCURRENT
```

**This distinction is the entire basis of what follows.** A consistency model is a rule about which *sequential* orderings of these intervals are permitted to explain the observed results.

---

## 3. Linearizability — the definition

Herlihy and Wing, 1990. The strongest single-object consistency model.

> **A history `H` is linearizable if there exists a sequential history `S` such that:**
>
> **(L1)** `S` contains the same operations as `H`, with the same arguments and the same return values, and
>
> **(L2)** if operation `a` completes before operation `b` begins in `H`, then `a` appears before `b` in `S`.

Informally, and more usefully:

> **Every operation appears to take effect atomically at some single instant between its invocation and its response, and that instant is consistent with a single global order that respects real time.**

### The two constraints, separated

```
(L1) — "there is SOME sequential order that explains the results"
       This is the easy half. It says the system behaved like a single machine.

(L2) — "that order respects REAL TIME"        ⭐ the hard half
       If I finished writing before you started reading, your read
       MUST see my write. No exceptions, no windows, no eventual.
```

**Constraint L2 is what makes linearizability expensive.** It is also what makes it intuitive: linearizable systems behave exactly as non-distributed programmers expect.

### What linearizability is NOT

- ❌ It is **not** about transactions. It is about **single objects** and **single operations**.
- ❌ It is **not** serializability (§7).
- ❌ It does **not** mean "fast" or "synchronous" — it is a correctness property, not a performance one.
- ❌ It does **not** require a single physical copy, only that the system be *indistinguishable* from one.

### The "linearization point" intuition

The most useful mental model: every operation has a moment — somewhere inside its interval — at which it "actually happened". If you can draw such a point for every operation, and the resulting sequence of points explains all the return values, the history is linearizable.

```
C1: |------W(x,1)------|
                 ↑ linearization point
C2:       |--------R(x)→1--------|
                          ↑ linearization point

Sequence: W(x,1) then R(x)→1.   ✓ Consistent with the returned value. Linearizable.
```

---

## 4. Worked histories — linearizable or not?

This is the section that makes the definition usable. Work through each before reading the verdict.

### History A

```
C1: |--W(x,1)--|
C2:                |--R(x)→1--|
C3:                              |--R(x)→1--|
```

**Verdict: linearizable.** ✓

The obvious sequential order `W(x,1), R(x)→1, R(x)→1` satisfies both constraints. Every operation is ordered in real time and the order explains every result.

---

### History B

```
C1: |--W(x,1)--|
C2:                |--R(x)→0--|
```

**Verdict: NOT linearizable.** ✗

`W(x,1)` completed before `R(x)` began, so L2 forces `W(x,1) <ₛ R(x)`. But then the read must return 1, not 0. No sequential order satisfies both constraints.

> **This is the single most important violation to recognise.** A read that returns a value older than a *completed* write is the canonical linearizability failure. It is what "read your own writes" (§13) prevents, and what a stale replica read produces (Chapter 09 §9.9).

---

### History C — concurrency creates freedom

```
C1: |------W(x,1)------|
C2:    |------W(x,2)------|
C3:                          |--R(x)→1--|
```

**Verdict: linearizable.** ✓

The two writes are concurrent, so L2 imposes **no** order between them. We may choose either. To explain the read returning 1, choose:

```
S = W(x,2), W(x,1), R(x)→1
```

Both writes complete before the read begins, so both must precede it — which they do. And because the writes overlapped, ordering `W(x,2)` first is permitted even though it *began* later.

> **The lesson: concurrency gives the system freedom.** Linearizability constrains only operations that are *ordered in real time*. This is why linearizable systems can still be fast under concurrent load — the constraint only bites across non-overlapping operations.

---

### History D — the one people get wrong

```
C1: |------W(x,1)------|
C2:    |------W(x,2)------|
C3:            |--R(x)→2--|
C4:                          |--R(x)→1--|
```

**Verdict: NOT linearizable.** ✗

Trace it carefully:

```
C3's read returns 2.  C3's read is concurrent with both writes, so we need
    W(x,2) <ₛ R₃(x)→2  and no later write before it. Fine so far.

C4's read returns 1.  C4's read begins AFTER C3's read completed.
    So L2 forces  R₃ <ₛ R₄.

Combined:  W(x,2) <ₛ R₃→2 <ₛ R₄→1

For R₄ to return 1, we need W(x,1) between R₃ and R₄.
But W(x,1) COMPLETED before R₃ began  →  L2 forces W(x,1) <ₛ R₃.

Contradiction. No valid S exists.
```

**The plain-English version:** once a value has been observed by *anyone*, the system cannot later reveal an older value to *anyone else*. Linearizability is a property of the whole system, not of each client's view.

> **This is exactly the monotonic-reads violation** from Chapter 05 §5.5 — a user sees "5 comments" then "3 comments". History D is what that looks like formally.

---

### History E — an uncertain operation

```
C1: |--W(x,1)--✗ (crashed, no response)
C2:                  |--R(x)→1--|
C3:                                 |--R(x)→1--|
```

**Verdict: linearizable.** ✓

The definition explicitly permits *extending* the history by supplying responses to pending invocations. An operation whose response was never delivered may be treated as either having taken effect or not — whichever makes the history linearizable.

Here we treat the crashed write as having taken effect, giving `S = W(x,1), R→1, R→1`. Valid.

> **This models reality precisely.** When a client's connection drops mid-write, the write may or may not have been applied, and the client cannot tell (Chapter 05 §5.1, the Two Generals problem). Linearizability accommodates this by allowing either interpretation — which is exactly why idempotency keys exist.

---

### History F — compare-and-swap

```
C1: |--CAS(x, 0→1) → true--|
C2:     |--CAS(x, 0→1) → true--|
```

**Verdict: NOT linearizable.** ✗

Any sequential order places one CAS first. That one succeeds, changing `x` from 0 to 1. The second then finds `x = 1`, so its expected value 0 does not match, and it **must** return `false`. Both returning `true` is unexplainable.

> **This is the history a correctness test for a distributed lock looks for.** Two clients both acquiring the same lock is precisely this violation, and it is what Jepsen's lock tests search for (§18).

---

## 5. The composability property ⭐

This is the deepest result about linearizability and it has direct architectural consequences.

> **Theorem (locality/composability):** A history over multiple objects is linearizable **if and only if** the history restricted to each individual object is linearizable.

**In plain terms: if every object in your system is individually linearizable, the whole system is linearizable — for free, with no coordination between objects.**

### Why this matters enormously

```
You have a linearizable key-value store.
You shard it across 100 nodes by key.
Each shard is independently linearizable (its own Raft group).

⭐ The COMBINED system is automatically linearizable.
   No cross-shard coordination. No global lock. No distributed transaction.
```

**This is the theoretical licence for range-sharded distributed databases.** CockroachDB, TiKV and Spanner run thousands of independent Raft groups (Deep Dive 01 §21). Each range is linearizable on its own; composability means single-key operations across the whole cluster are linearizable without any global mechanism.

It is also why you can build a linearizable system from linearizable parts without re-proving correctness each time — a property almost no other consistency model has.

### The proof sketch

```
(⟸ the interesting direction)

Given: each object's sub-history is linearizable.
Each object x has a valid sequential order Sₓ with linearization points inside
each operation's interval.

Construct S for the whole history by taking ALL those linearization points and
sorting them by time.

• L1 holds: within each object, the order is unchanged from Sₓ, so all
  return values are still explained.
• L2 holds: if op a completed before op b began, then a's linearization point
  (inside a's interval) precedes b's (inside b's interval).           ∎
```

The proof works because each linearization point is a **single instant in real time**, so points from different objects can simply be merged by time. This is exactly the property L2 provides — and it is precisely what sequential consistency lacks.

### The crucial limitation

Composability applies to **single-object operations**. It says nothing about *multi-object atomicity*.

```
Linearizable KV store, two keys on different shards:

    write(accounts:A, 900)     ← linearizable
    write(accounts:B, 1100)    ← linearizable

A reader can observe A=900 and B=1000 (the old value) between them.
The two writes are individually linearizable. Together they are NOT atomic.
```

**Atomicity across objects is a different property: it requires transactions.** That is what §7 and §8 are about, and it is why Spanner needs both TrueTime *and* two-phase commit — linearizability per range, plus transactions across ranges.

---

## 6. Sequential consistency, and why it does not compose

Lamport, 1979. Identical to linearizability **minus the real-time constraint**.

> **A history is sequentially consistent if there exists a sequential order `S` such that:**
>
> **(S1)** `S` contains the same operations with the same results, and
> **(S2)** `S` preserves the **program order of each individual process**.

The difference is exactly one clause:

```
Linearizable:  S respects REAL TIME order across ALL processes
Sequential:    S respects only each PROCESS's OWN order
```

### The history that separates them

```
C1: |--W(x,1)--|
C2:                 |--R(x)→0--|  |--R(x)→1--|
```

**Linearizable?** No. `W(x,1)` completed before the first read began, so that read must return 1.

**Sequentially consistent?** **Yes.** The only per-process constraint is that C2's two reads keep their order. This order works:

```
S = R(x)→0,  W(x,1),  R(x)→1
```

We simply "moved" the write later than its real-time position. Sequential consistency permits that; linearizability does not.

### Why sequential consistency does not compose ⭐

This is the result that explains why sequential consistency, despite being cheaper, is rarely what systems offer.

```
Two objects, x and y. Two processes.

C1: |--W(x,1)--|                 |--R(y)→0--|
C2:                |--W(y,1)--|                |--R(x)→0--|

Consider EACH OBJECT separately:

  Object x:   W(x,1) by C1,  R(x)→0 by C2
              Valid sequential order:  R(x)→0, W(x,1)   ✓ (per-process order kept)

  Object y:   W(y,1) by C2,  R(y)→0 by C1
              Valid sequential order:  R(y)→0, W(y,1)   ✓

  ⭐ Each object, in isolation, is sequentially consistent.

Now the COMBINED history. Per-process orders that must hold:
      C1:  W(x,1)  <ₛ  R(y)→0
      C2:  W(y,1)  <ₛ  R(x)→0

For R(y)→0 to return 0:  R(y) <ₛ W(y,1)
For R(x)→0 to return 0:  R(x) <ₛ W(x,1)

Chain them:
      W(x,1) <ₛ R(y) <ₛ W(y,1) <ₛ R(x) <ₛ W(x,1)

      ⭐ W(x,1) < ... < W(x,1).   A CYCLE. No total order exists.

The combined history is NOT sequentially consistent.
```

**Two sequentially-consistent objects compose into a non-sequentially-consistent system.**

> **The architectural consequence:** with linearizable components you can reason locally — prove each piece correct and the whole is correct. With sequentially-consistent components you must reason about the whole system at once, every time you add a component. That is why linearizability, despite costing more, is what distributed systems actually offer, and why this theorem is quoted more than any other in the field.

Sequential consistency survives mainly in **hardware memory models**, where a single machine's cache-coherence protocol provides it and composability across sockets is handled differently.

---

## 7. The four-quadrant map

Four models are constantly confused. They differ along exactly two axes.

```
                    │  SINGLE OBJECT,           │  MULTI-OBJECT
                    │  single operation         │  TRANSACTIONS
────────────────────┼───────────────────────────┼──────────────────────────
  RESPECTS          │                           │
  REAL TIME         │    LINEARIZABILITY        │  STRICT SERIALIZABILITY
                    │    (Herlihy & Wing 1990)  │  (the strongest model there is)
────────────────────┼───────────────────────────┼──────────────────────────
  IGNORES           │                           │
  REAL TIME         │    SEQUENTIAL             │  SERIALIZABILITY
                    │    CONSISTENCY            │  (the ANSI SQL "SERIALIZABLE")
                    │    (Lamport 1979)         │
```

### What each one actually allows

| Model | Guarantees | Notably allows |
|-------|-----------|----------------|
| **Linearizability** | Single ops appear instantaneous, in real-time order | Nothing about multi-object atomicity |
| **Serializability** | Transactions appear to run one at a time, in *some* order | That order need not match real time — **a transaction can appear to run in the past** |
| **Strict serializability** | Both | — |
| **Sequential** | Single ops in *some* order respecting each process's own order | Reads arbitrarily far in the past; does not compose |

### The serializability surprise

Plain serializability permits this:

```
T1: |--- write(x, 1); COMMIT ---|
T2:                                |--- read(x) → 0; COMMIT ---|
```

**This is serializable.** The valid serial order is `T2, T1` — T2 ran "first". Nothing in the definition of serializability requires the serial order to match real time.

Is it *useful*? Usually not. A user commits a change, immediately reloads, and sees the old value. The database is behaving correctly per the definition and the user files a bug.

**This is why strict serializability exists**, and why it is what you actually want from an OLTP database. PostgreSQL's `SERIALIZABLE` on a single node is effectively strict (a single node has a real-time order). Distributed systems must work for it: Spanner uses TrueTime commit-wait (Deep Dive 02 §17); CockroachDB uses HLC plus uncertainty restarts.

> **The precise questions to ask a distributed SQL vendor:**
> 1. *"Is it serializable or strictly serializable?"*
> 2. *"Does that hold for read-only transactions too?"*
>
> Several systems provide strict serializability for read-write transactions but only serializability (or snapshot reads) for read-only ones, because that is much cheaper. That is a legitimate design — but you should know.

---

## 8. Transaction isolation as a consistency hierarchy

The ANSI SQL isolation levels are the same kind of object as the models above, defined by which anomalies they forbid. The original standard defined them badly (by prohibiting three specific phenomena, in ambiguous prose); modern treatments define them by forbidding cycles in a dependency graph (§10).

### The practical hierarchy

```
                      SERIALIZABLE
                           │  forbids everything below
                           │
    ┌──────────────────────┴──────────────────────┐
    │                                              │
SNAPSHOT ISOLATION                         REPEATABLE READ
 (allows write skew)                       (ANSI: allows phantoms)
    │                                              │
    └──────────────────────┬──────────────────────┘
                           │
                    READ COMMITTED
                    (allows non-repeatable read, lost update)
                           │
                   READ UNCOMMITTED
                    (allows dirty read)
```

**Note that SNAPSHOT ISOLATION and REPEATABLE READ are siblings, not a chain.** They forbid different things:

| | Snapshot Isolation | ANSI Repeatable Read |
|---|---|---|
| Prevents phantoms? | **Yes** | No (by the letter of the standard) |
| Prevents write skew? | **No** | No |
| Prevents lost update? | Yes (first-committer-wins) | Implementation-dependent |

**And the naming is actively misleading in real products:**

| Product | Level named "REPEATABLE READ" is actually… |
|---------|---------------------------------------------|
| **PostgreSQL** | **Snapshot Isolation** (prevents phantoms; allows write skew) |
| **MySQL/InnoDB** | Snapshot-ish, with gap locks that prevent many phantoms |
| **Oracle** | Offers `SERIALIZABLE` which is actually Snapshot Isolation |
| **SQL Server** | `SNAPSHOT` is SI; `SERIALIZABLE` is genuine (via range locks) |

> **Never assume a level name means what the standard says.** Read the product's documentation for which *anomalies* are prevented. Oracle's `SERIALIZABLE` allowing write skew has surprised many people who read the name and stopped there.

---

## 9. The anomaly catalogue, with cycles

Each anomaly is a specific pattern. Recognising them by shape is more useful than memorising level tables.

### P0 — Dirty write

```
T1: write(x, 1) ................................ commit
T2:        write(x, 2) ... commit

T2 overwrote T1's uncommitted write. If T1 rolls back, what is x?
```
**Prevented by:** every level. All implementations take write locks.

### P1 — Dirty read

```
T1: write(x, 1) .................. ROLLBACK
T2:        read(x) → 1

T2 read a value that never existed.
```
**Prevented from:** Read Committed upward.

### P2 — Non-repeatable read (fuzzy read)

```
T1: read(x) → 100 ............. read(x) → 200
T2:           write(x, 200); commit

The same read, twice, in one transaction, gave different answers.
```
**Prevented from:** Repeatable Read / Snapshot Isolation upward.

### P3 — Phantom read

```
T1: SELECT count(*) WHERE total > 100 → 5 ........ same query → 6
T2:              INSERT (total = 200); commit

Not a changed row — a NEW row appeared that matches the predicate.
```
**Prevented by:** genuine Serializable; also by PostgreSQL's Repeatable Read (snapshot-based); also by MySQL's gap locks in many cases.

### P4 — Lost update

```
T1: read(x) → 10 ................ write(x, 11); commit
T2:      read(x) → 10 ... write(x, 11); commit

Two increments. Final value 11 instead of 12. One update vanished.
```
**Prevented by:** Snapshot Isolation (first-committer-wins), or `SELECT FOR UPDATE`, or an atomic `UPDATE x = x + 1`, or a version check.

**Crucially, Read Committed does NOT prevent it** — and Read Committed is the default in PostgreSQL, Oracle and SQL Server. This is one of the most common real bugs in production application code.

### A5B — Write skew ⭐

The anomaly that Snapshot Isolation permits, and the reason Serializable exists.

```
INVARIANT: at least one doctor must be on call.
Currently: Alice and Bob, both on call.

T1 (Alice):  SELECT count(*) WHERE on_call → 2.  OK, I can go off.
T2 (Bob):    SELECT count(*) WHERE on_call → 2.  OK, I can go off.
T1:          UPDATE doctors SET on_call = false WHERE name = 'Alice';  COMMIT
T2:          UPDATE doctors SET on_call = false WHERE name = 'Bob';    COMMIT

→ ZERO doctors on call. The invariant is violated.
```

**Why Snapshot Isolation does not catch it:** SI detects **write-write** conflicts — two transactions writing the **same row**. Here T1 writes Alice's row and T2 writes Bob's row. **Different rows. No write-write conflict. Both commit.**

The conflict is between T1's *read* of Bob's row and T2's *write* to it — a **read-write (anti-dependency)** conflict, which SI does not track.

**The general shape to recognise:**
```
1. Read a set of rows, checking some condition across them
2. Decide based on that condition
3. Write to a DIFFERENT row (or insert)
4. The write invalidates the condition another concurrent transaction read
```

**Real instances of this shape:**

| Domain | The write skew |
|--------|---------------|
| On-call rota | Both doctors go off call |
| Meeting room booking | Two bookings for the same slot (each inserts a different row) |
| Bank overdraft across two accounts | Both withdrawals pass a combined-balance check |
| Claiming a username | Two inserts, both checked "not taken" |
| Multiplayer game moves | Two players claim the same cell |
| **Inventory across warehouses** | Total stock check passes twice; both ship |

**Fixes, in order of preference:**
```
1. A DATABASE CONSTRAINT that makes the bad state unrepresentable
   → EXCLUDE USING GIST for booking overlap (Chapter 09 §9.6). Best: no race possible.
2. SERIALIZABLE isolation + retry on 40001
3. Materialise the conflict: SELECT ... FOR UPDATE on a row that represents
   the invariant (e.g. lock the rota row, not the doctor rows)
4. Application-level: a single aggregate owning the invariant (Chapter 03 §3.8)
```

Option 4 is the DDD answer and is often the cleanest: if a rule must hold across several rows, those rows probably belong to one aggregate, and the aggregate is the consistency boundary.

---

## 10. Adya's formalism: cycles in the dependency graph

The modern, implementation-independent way to define isolation levels. Worth knowing because it turns "which anomalies does this allow?" into a mechanical check — and it is how Jepsen's `elle` checker works (§18).

### Build a Direct Serialization Graph (DSG)

Nodes are committed transactions. Edges are dependencies:

```
ww  WRITE-WRITE      T1 → T2   if T2 overwrites a version T1 wrote
wr  WRITE-READ       T1 → T2   if T2 reads a version T1 wrote
rw  READ-WRITE       T1 → T2   if T2 overwrites a version T1 read
    (anti-dependency)          ⭐ the direction is counter-intuitive: the READER
                                  points to the WRITER
```

### The central theorem

> **A history is serializable if and only if its DSG is acyclic.**

A cycle means there is no way to order the transactions serially — each must come before the other.

### The levels, as forbidden cycles

| Level | Forbids |
|-------|---------|
| Read Uncommitted (PL-1) | `G0` — cycles of only `ww` edges (dirty write) |
| Read Committed (PL-2) | `G1` — reading aborted values (`G1a`), reading intermediate values (`G1b`), cycles with `ww`/`wr` (`G1c`) |
| Repeatable Read (PL-2.99) | G1 + cycles containing **at most one** `rw` edge |
| **Serializable (PL-3)** | **G2 — ALL cycles**, including any number of `rw` edges |

### Write skew as a cycle

```
T1 reads Bob's row (on_call = true), writes Alice's row
T2 reads Alice's row (on_call = true), writes Bob's row

Edges:
    T1 --rw--> T2     T1 read Bob's row; T2 overwrote it
    T2 --rw--> T1     T2 read Alice's row; T1 overwrote it

    ⭐ A 2-cycle consisting entirely of rw edges.
```

This cycle contains **two** `rw` edges. Snapshot Isolation forbids cycles with at most one; it permits this. Serializable forbids all cycles and therefore catches it.

**Now the whole hierarchy has a single explanation:** each level is defined by how many anti-dependency edges it tolerates in a cycle. That is far more precise than the ANSI prose, and it is why modern papers and checkers use it.

### Why anti-dependencies are the hard ones

`ww` and `wr` edges represent information that *flowed* — the system can see them by tracking versions. An `rw` edge represents information that **did not** flow: T1 read a value, and T2 later invalidated it, but nothing was communicated to T1.

Detecting that requires tracking **what each transaction read**, including predicates ("all rows where `on_call = true`", which includes rows that do not exist yet). That is expensive, and it is why serializable isolation costs more than snapshot isolation.

**PostgreSQL's SSI (Serializable Snapshot Isolation)** solves it elegantly: run snapshot isolation, additionally track read dependencies via SIREAD locks (which do not block anything), and abort a transaction when a **dangerous structure** appears — two consecutive `rw` edges, which is a necessary condition for a cycle. It is a conservative test: some aborted transactions would actually have been fine. That is the price of not blocking.

> **This is why PostgreSQL SERIALIZABLE gives you `40001` serialization failures rather than deadlocks or waits, and why retry logic is mandatory** (Chapter 09 §9.3). The transactions were never blocked; one was killed after the fact.

---

## 11. Snapshot isolation, precisely

Worth a section of its own because it is the most widely deployed isolation level and the most widely misunderstood.

### The rules

```
1. A transaction reads from a CONSISTENT SNAPSHOT taken at its start time.
   It sees all transactions that committed before it began, and NONE that
   commit afterwards — regardless of how long it runs.

2. FIRST-COMMITTER-WINS: if two concurrent transactions write the same row,
   only the first to commit succeeds. The other aborts.
```

### What it gives you

```
✅ No dirty reads          ✅ No non-repeatable reads
✅ No phantoms             ✅ No lost updates  (rule 2 catches them)
✅ Readers never block writers, writers never block readers (MVCC)
```

That last property is why it is so popular: analytical reads and OLTP writes coexist without lock contention.

### What it does not give you

```
❌ Write skew (§9)
❌ Read-only transaction anomalies  ⭐ (§ below — genuinely surprising)
```

### The read-only anomaly

Most people believe a read-only transaction cannot cause an anomaly. Under snapshot isolation, that is false.

```
Two accounts, X and Y, each with balance 50.
Rule: a withdrawal incurs a $1 fee if the COMBINED balance would go negative.

T1 (read-write): withdraw 40 from Y.
    reads X=50, Y=50 → total 100 ≥ 40 → no fee. writes Y=10.

T2 (read-write): withdraw 20 from X.
    reads X=50, Y=50 → total 100 ≥ 20 → no fee. writes X=30.

T3 (READ-ONLY): reads X and Y.

If T3's snapshot sees T1's commit but not T2's:
    T3 observes X=50, Y=10  → total 60

But there is NO serial order of T1 and T2 that produces that state as an
intermediate observable value while both fees were correctly waived.
T3 has observed a state that could not occur in any serial execution.
```

**The consequence:** under snapshot isolation, adding a read-only transaction can reveal an anomaly that the read-write transactions alone did not exhibit. You cannot reason about read-only transactions as "safe by construction".

PostgreSQL's SSI handles this — it can abort a **read-only** transaction with a serialization failure, which surprises people the first time they see it. It is correct behaviour.

### Where you meet snapshot isolation

| System | Where |
|--------|-------|
| PostgreSQL | `REPEATABLE READ` (named misleadingly) |
| Oracle | `SERIALIZABLE` (named very misleadingly) |
| SQL Server | `SNAPSHOT` (named correctly) |
| MySQL/InnoDB | `REPEATABLE READ`, plus gap locks |
| CockroachDB | Serializable only — SI is not offered, deliberately |
| MongoDB | Snapshot read concern in transactions |
| TiDB | SI by default; optimistic and pessimistic modes |

> **The architect's checklist item:** for every invariant that spans multiple rows, ask *"is this write skew?"* If yes, you need a constraint, serializable isolation with retries, or an aggregate boundary. Do not rely on the default isolation level to protect a multi-row invariant — in almost every major database, the default does not.

---

## 12. Causal consistency — the strongest available under partition

An important theoretical result, and the model that most user-facing systems should target.

> **Causal consistency guarantees that operations related by happens-before (Deep Dive 02 §8) are observed in that order by every process. Concurrent operations may be observed in different orders by different processes.**

### The definition

```
For every process P, there exists a sequential order S_P of all operations
such that:
    • S_P explains all of P's observed return values, and
    • if a → b (happens-before), then a appears before b in S_P

⭐ Note: each process may have a DIFFERENT S_P.
   That is the relaxation. Linearizability requires ONE shared order.
```

### The classic violation it prevents

```
Alice posts:    "I lost my keys"                (event A)
Alice posts:    "Found them!"                   (event B, A → B)
Bob reads B, replies: "Great news!"             (event C, B → C)

Carol's view under EVENTUAL consistency (no causal guarantee):
    "Great news!"          ← Bob's reply
    "I lost my keys"       ← Alice's first post
    (Alice's "Found them!" has not arrived yet)

Carol is confused. Bob appears to be celebrating lost keys.

Under CAUSAL consistency this is impossible: C cannot be delivered
to Carol before B, because B → C.
```

### The theoretical result that makes it important

> **Causal consistency is the strongest consistency model that can be provided by a system that remains available under network partition.** (Attiya, Ellen, Morrison 2015; building on Mahajan, Alvisi, Dahlin 2011.)

This sits exactly on the CAP boundary (Chapter 05 §5.4). Anything stronger than causal — sequential, linearizable — requires giving up availability during a partition. Causal does not.

**That makes causal consistency the natural target for AP systems**, and it is why it appears in the design of systems like COPS, Eiger, and (in a session-scoped form) MongoDB's causally consistent sessions and Azure Cosmos DB's "Consistent Prefix" and "Session" levels.

### How it is implemented

```
Track dependencies explicitly:
    • each write carries the version vector / dependency set of what the
      writer had observed
    • a replica DELAYS applying a write until all its dependencies are applied
```

```python
def receive_write(self, write):
    # Do not apply until everything this write causally depends on is applied
    if not self._dependencies_satisfied(write.deps):
        self.pending.append(write)          # buffer
        return
    self.apply(write)
    self._check_pending()                   # some buffered writes may now be ready

def _dependencies_satisfied(self, deps: VectorClock) -> bool:
    return all(self.applied_clock.get(node, 0) >= v for node, v in deps.items())
```

**The cost:** dependency metadata per write (the O(N) problem from Deep Dive 02 §11), and buffering — which means a missing dependency delays everything behind it.

**The pragmatic version most systems ship** is **causal consistency per session** rather than globally: track only what *this client* has seen. That is O(1) metadata and covers the cases users actually notice. It is what §13's session guarantees provide.

---

## 13. The session guarantees, formally

Four guarantees (Terry et al., Bayou, 1994) that make eventual consistency *usable by humans*. Each is cheap; together they cover almost all user-visible anomalies.

### RYW — Read Your Writes

> If process P writes a value, every subsequent read by P returns that value or a later one.

```
VIOLATION:
    P: write(profile.name, "Delower");  read(profile.name) → "Old Name"

The user saves, the page reloads, the old value appears. They save again.
```

**Implementations:** route a client's reads to the primary for N seconds after a write; sticky sessions to one replica; or return the new value in the write response and do not re-read (the cheapest and best option — Chapter 05 §5.5).

### MR — Monotonic Reads

> If process P reads a value, every subsequent read by P returns that value or a later one. **Time never goes backwards for a given reader.**

```
VIOLATION:
    P: read(comments) → 5 items
    P: read(comments) → 3 items      ← comments vanished

Cause: consecutive reads hit different replicas with different lag.
```

**Implementation:** pin a client to one replica (consistent hashing on session ID), or carry a minimum-version token in the session and have replicas wait or redirect.

**This is History D from §4** — the formal statement of that violation.

### MW — Monotonic Writes

> If process P writes A then writes B, every replica applies A before B.

```
VIOLATION:
    P: write(profile, v1);  write(profile, v2)
    Replica applies v2 then v1  →  the final state is v1. The newer write is lost.
```

Not automatic in a leaderless system where two writes may take different paths.

### WFR — Writes Follow Reads

> If P reads value V and then writes W, then W is ordered after the write that produced V on every replica.

```
VIOLATION:
    P reads Alice's post, replies to it.
    A replica shows P's reply BEFORE Alice's post.
```

This is the session-scoped version of the causal-consistency example in §12.

### The relationship to causal consistency

```
RYW + MR + MW + WFR  ≈  causal consistency, restricted to a single session
```

**The practical implication is important and under-appreciated:** you can get most of the *user-visible* benefit of causal consistency for O(1) metadata — a per-session token — instead of O(N) dependency vectors. This is precisely what MongoDB's causally consistent sessions and Cosmos DB's "Session" consistency level do, and it is why "Session" is Cosmos DB's default and most-used level.

```javascript
// MongoDB: session-scoped causal consistency, in practice
const session = client.startSession({ causalConsistency: true });
db.collection('x').insertOne({...}, { session });
db.collection('x').find({...}, { session });   // guaranteed to see the insert
// The driver carries an operationTime/clusterTime token on every request.
```

---

## 14. Eventual consistency: what it does and does not promise

> **Eventual consistency: if no new updates are made, all replicas eventually converge to the same value.**

### Read the definition adversarially

```
"If no new updates are made"  ← a busy system NEVER satisfies this precondition
"eventually"                  ← no bound. 10 ms or 10 hours both satisfy it.
"the same value"              ← says NOTHING about WHICH value
```

**Eventual consistency is, taken literally, an extremely weak promise.** A system that returns a random value for an hour and then converges satisfies it. A system that returns nothing at all and then converges satisfies it.

### What it is missing, concretely

```
❌ No bound on staleness
❌ No guarantee about WHICH value wins
❌ No session guarantees unless separately provided
❌ No causality — a reply can appear before the message it replies to
❌ No monotonicity — values can go backwards
```

**Which is why the four session guarantees (§13) are not optional extras.** "Eventually consistent" plus RYW plus MR is a system humans can use. "Eventually consistent" alone is a system that will generate support tickets describing impossible behaviour.

> **When evaluating an eventually-consistent system, the useful questions are:**
> 1. *What is the p99 convergence time, measured?* (not "usually fast")
> 2. *Which session guarantees are provided, and are they on by default?*
> 3. *What is the conflict resolution rule?* (LWW? siblings? CRDT merge?)
> 4. *What happens during a partition — and for how long can that last?*

---

## 15. Strong eventual consistency and CRDTs

A genuinely stronger property that removes the "which value wins?" problem entirely.

> **Strong Eventual Consistency (SEC): any two replicas that have received the same *set* of updates are in the same state — regardless of the order in which they received them, and without any coordination.**

The difference from plain eventual consistency: convergence is **immediate upon receiving the same updates**, not "eventually after some reconciliation process", and it requires **no conflict resolution** because there are no conflicts by construction.

### The mathematical requirement

The merge operation must form a **join-semilattice**:

```
COMMUTATIVE:   merge(a, b) = merge(b, a)              order does not matter
ASSOCIATIVE:   merge(merge(a,b), c) = merge(a, merge(b,c))   grouping does not matter
IDEMPOTENT:    merge(a, a) = a                        duplicates do not matter
```

**Those three properties correspond exactly to the three things an unreliable network does to your messages:** reorders them, regroups them, and duplicates them. A merge function immune to all three is immune to the network.

### The catalogue

| CRDT | Merge | Use |
|------|-------|-----|
| **G-Counter** | Per-node counts; merge = pointwise max; value = sum | Increment-only counters (page views) |
| **PN-Counter** | Two G-Counters (P and N); value = sum(P) − sum(N) | Counters that go both ways (likes) |
| **G-Set** | Union | Add-only sets |
| **2P-Set** | Two G-Sets (adds, removes); an element removed can never be re-added | Simple sets, with a real limitation |
| **LWW-Register** | Highest timestamp wins | A single value — **inherits every LWW problem** (Deep Dive 02 §18) |
| **MV-Register** | Keep all concurrent values as siblings | A single value, conflicts surfaced |
| **OR-Set** ⭐ | Each add gets a unique tag; remove removes observed tags only | **Sets with add and remove that both work** |
| **RGA / Logoot / YATA** | Position identifiers in a dense order | Collaborative text editing |

### The G-Counter, worked

```python
class GCounter:
    """Increment-only counter. Converges with no coordination whatsoever."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.counts: dict[str, int] = {}

    def increment(self, n: int = 1) -> None:
        self.counts[self.node_id] = self.counts.get(self.node_id, 0) + n

    def value(self) -> int:
        return sum(self.counts.values())

    def merge(self, other: "GCounter") -> "GCounter":
        merged = GCounter(self.node_id)
        for k in set(self.counts) | set(other.counts):
            # ⭐ POINTWISE MAX — this is the entire trick.
            # max is commutative, associative and idempotent.
            merged.counts[k] = max(self.counts.get(k, 0), other.counts.get(k, 0))
        return merged
```

```
Node A: {A: 5}          A increments 5 times
Node B: {B: 3}          B increments 3 times
Node C: {C: 2}          C increments 2 times

Any merge order:
    merge(merge(A,B), C) = {A:5, B:3, C:2}  → value 10
    merge(C, merge(B,A)) = {A:5, B:3, C:2}  → value 10
    merge(A, merge(A,B)) = {A:5, B:3}       → duplicate merge changed nothing ✓

⭐ No coordination. No conflict. No LWW. No lost increments.
```

**Why a naive shared integer fails here, and this does not:** a plain counter's merge would have to answer "is 5 or 3 correct?" — an unanswerable question. By splitting the counter into per-node slots, each slot has exactly one writer, so `max` is always correct. **This is the same insight as "partition so each key has one writer"** (Deep Dive 02 §18) applied at the data-structure level.

### The OR-Set — why 2P-Set is not enough

```
2P-Set problem:  add("x"), remove("x"), add("x")
                 → "x" is in the remove-set forever. The second add is ignored.

OR-Set (Observed-Remove):
    add("x")     → adds ("x", tag1)
    remove("x")  → removes only the tags currently OBSERVED: {tag1}
    add("x")     → adds ("x", tag2)   ← a NEW tag, not in the remove set
    → "x" is present ✓

And concurrent add/remove resolves toward ADD:
    Replica A: remove("x")  (observes tag1)
    Replica B: add("x")     (creates tag2, concurrently)
    Merge: tag1 removed, tag2 present → "x" IS in the set
```

**The add-wins bias is a deliberate design choice**, and it is the same commercial reasoning as Amazon's shopping cart (Deep Dive 02 §12): re-appearing data is an annoyance; disappearing data is a lost transaction.

### Where CRDTs are used in production

| System | Use |
|--------|-----|
| **Redis Enterprise (CRDB)** | Active-active geo-replication |
| **Riak** | Built-in CRDT data types |
| **Automerge / Yjs** | Collaborative editing (the Figma/Linear-style local-first model) |
| **Figma** | Multiplayer design (a custom CRDT-like approach) |
| **Soundcloud, Bet365** | Documented large-scale CRDT use |
| **Azure Cosmos DB** | Conflict resolution policies |

### The limits — be honest about these

```
❌ Not every data type has a sensible merge.
   "The account balance" cannot be a CRDT: a PN-Counter can go negative,
   because no replica can enforce a global "balance >= 0" invariant
   without coordination. That is not a CRDT limitation — it is CAP.

❌ Metadata overhead. OR-Sets accumulate tombstones; text CRDTs accumulate
   position identifiers. Garbage collection is a real, hard engineering problem.

❌ Merge semantics may be surprising to users.
   Concurrent edits to a text document merge deterministically — but not
   always in the way a human would have chosen.
```

> **The decision rule:** a CRDT is right when the merge semantics genuinely match the business meaning (sets of items, counters, collaborative text, presence). It is wrong when the correct answer requires a global invariant — and no amount of clever data-structure design escapes that, because it is the CAP theorem, not an implementation gap.

---

## 16. The complete hierarchy

```
                     STRICT SERIALIZABILITY
                     (transactions, real-time order)
                              │
                ┌─────────────┴─────────────┐
                │                            │
        LINEARIZABILITY                SERIALIZABILITY
        (single object,                (transactions, any order)
         real-time)                            │
                │                              │
        SEQUENTIAL CONSISTENCY         SNAPSHOT ISOLATION
        (single object, per-process           │
         order, DOES NOT COMPOSE)      REPEATABLE READ
                │                              │
                │                       READ COMMITTED
                │                              │
                │                      READ UNCOMMITTED
                │
        CAUSAL CONSISTENCY  ⭐ the strongest available under partition
                │
        ┌───────┴───────┬───────────┬──────────────┐
        │               │           │              │
   READ-YOUR-      MONOTONIC   MONOTONIC    WRITES-FOLLOW-
     WRITES          READS       WRITES         READS
        └───────┬───────┴───────────┴──────────────┘
                │
        EVENTUAL CONSISTENCY
                │
        (STRONG EVENTUAL CONSISTENCY sits beside it:
         same availability, but convergence is guaranteed
         by construction rather than by reconciliation)

  ── available under partition ──────────── NOT available under partition ──
                    ↑
            the CAP boundary sits here,
            between causal and sequential
```

**The two lines worth memorising:**

1. **The CAP boundary sits between causal and sequential consistency.** Everything at or below causal can remain available during a partition. Everything above cannot.
2. **Linearizability composes; sequential consistency does not.** That single fact is why real systems offer linearizability rather than the cheaper sequential consistency.

---

## 17. What real systems actually provide

Specific, with the settings that change the answer.

### Databases

| System | Default | Strongest available | Notes |
|--------|---------|--------------------|-------|
| **PostgreSQL (single node)** | Read Committed | Serializable (SSI) | `SERIALIZABLE` is genuine; requires retry on `40001` |
| **PostgreSQL + read replicas** | RC on primary; **stale on replicas** | — | Replica reads break linearizability entirely |
| **MySQL/InnoDB** | Repeatable Read | Serializable | RR is SI-ish with gap locks |
| **Oracle** | Read Committed | **"SERIALIZABLE" = Snapshot Isolation** | Genuinely serializable is not offered |
| **SQL Server** | Read Committed | Serializable (range locks) | `SNAPSHOT` is SI, correctly named |
| **CockroachDB** | Serializable | **Strict serializable** | Only offers serializable — a deliberate choice |
| **Spanner** | Strict serializable | — | TrueTime + commit wait (DD02 §17) |
| **YugabyteDB** | Snapshot | Serializable | |
| **TiDB** | Snapshot | — | Optimistic and pessimistic modes |

### Distributed stores

| System | Default | Configurable to | Notes |
|--------|---------|----------------|-------|
| **etcd / ZooKeeper / Consul** | **Linearizable** | Serializable (stale) reads | This is their job (DD01 §17) |
| **DynamoDB** | Eventually consistent | `ConsistentRead=true` → linearizable per item | 2× the read cost |
| **DynamoDB global tables** | **LWW across regions** | — | Cross-region conflicts use LWW |
| **Cassandra** | Tunable per query | `QUORUM`/`QUORUM` → strong-ish; `SERIAL` for LWT | Plain writes are always LWW (DD02 §18) |
| **MongoDB** | `w:1`, `readConcern:local` | `w:majority` + `readConcern:linearizable` | Causally consistent sessions available |
| **Redis (single)** | Linearizable-ish | — | Not durable by default; failover can lose writes |
| **Redis Cluster** | — | — | Async replication; **writes can be lost on failover** |
| **Cosmos DB** | Session | Strong / Bounded Staleness / Session / Consistent Prefix / Eventual | **Five explicit levels — the clearest model in the industry** |
| **Elasticsearch** | Near-real-time (~1 s refresh) | — | **Not a system of record** (Chapter 10 §10.8) |

### Cosmos DB's five levels are worth studying

Azure's model is the most explicit in the industry, and it maps cleanly onto this chapter:

```
STRONG              linearizable. Single region, or high latency across regions.
BOUNDED STALENESS   linearizable up to K versions or T seconds of lag. ⭐ A rare
                    and genuinely useful middle ground: a BOUNDED window.
SESSION             the four session guarantees (§13). The default. Most-used.
CONSISTENT PREFIX   reads never see out-of-order writes (no causality violations,
                    but no session guarantees either)
EVENTUAL            §14
```

**Bounded staleness is the model most systems should offer and few do.** "Eventually" with no bound is unusable for reasoning; "at most 5 seconds or 100 versions behind" is something you can design around, alert on, and explain to a product manager.

---

## 18. Jepsen: how violations are found

Kyle Kingsbury's Jepsen is the reason many of the claims in §17 are trustworthy — and the reason several vendors' earlier claims were not.

### The method

```
1. Set up a real cluster of the system under test
2. Run concurrent clients performing operations, recording a HISTORY
   (invocation and response with real timestamps — exactly §2's notation)
3. INJECT FAULTS: partitions, clock skew, process pauses (SIGSTOP),
   crashes, disk failures, membership changes
4. ⭐ CHECK the recorded history against the claimed consistency model
5. If no valid ordering exists → the claim is violated. Produce the
   minimal counterexample.
```

**Step 4 is the technically hard part.** Checking linearizability is NP-complete in general. Jepsen's checkers:

- **Knossos** — brute-force search with aggressive pruning; works for short histories
- **Elle** ⭐ — builds the dependency graph (§10) and searches for **cycles**. Far faster, and it explains *why* a history is invalid by exhibiting the cycle. Elle can also detect violations without observing every intermediate state, which makes it usable on real workloads.

### Representative findings

These are public reports. The point is not to criticise the products — most issues were fixed, and the vendors' willingness to be tested is a positive signal — but to show what the process catches.

| System | Finding | Root cause category |
|--------|---------|--------------------|
| **MongoDB (pre-3.x, several reports)** | Lost acknowledged writes under partition with `w:1` | Default write concern |
| **Elasticsearch (2014–2015)** | Lost documents during partitions | Not designed as a system of record |
| **Redis Sentinel** | Lost acknowledged writes on failover | Async replication + promotion |
| **Cassandra LWT** | Violations of the claimed linearizability in specific versions | Paxos implementation edge cases |
| **etcd / Consul (early versions)** | Stale reads from a partitioned leader | Missing CheckQuorum (DD01 §16) |
| **Kafka (2013)** | Data loss with unclean leader election enabled | A documented, deliberate trade — but the default surprised people |
| **PostgreSQL (12.3, 2020)** | A genuine serializability anomaly under specific concurrency | A real bug in SSI; fixed |
| **MariaDB Galera** | Documented as SI, not serializable | Marketing vs mechanism |

### What the pattern teaches

Nearly every finding falls into one of four buckets:

```
1. UNSAFE DEFAULTS      w:1, acks=1, unclean.leader.election=true.
                        Safe when configured; unsafe out of the box.

2. STALE LEADER READS   A partitioned leader serving reads (DD01 §16).

3. LWW SILENTLY LOSING  Conflicts resolved by clock (DD02 §18).

4. MARKETING VS MECHANISM  "Strongly consistent" meaning SI, or
                        serializable-but-not-strict.
```

> **All four are things you can check yourself before adopting a system**, without running Jepsen: read the default write/read concerns, ask about stale leader reads, find the conflict-resolution rule, and ask "linearizable, serializable, or strictly serializable?" That is the practical value of this whole deep dive.

---

## 19. Testing your own system

You can apply the method without the full Jepsen apparatus.

### Record a history

```python
@dataclass
class HistoryEntry:
    process: int
    op_type: str            # "invoke" | "ok" | "fail" | "info"
    function: str           # "read" | "write" | "cas"
    value: object
    time_ns: int            # ⭐ from a MONOTONIC clock, on ONE machine (DD02 §3)

# ⭐ "info" is critical and often omitted: it means the OUTCOME IS UNKNOWN
#    (timeout, connection reset). It is NOT a failure. A checker must treat
#    such an operation as possibly-applied (History E in §4).
#    Recording a timeout as "fail" will hide real violations.
```

### Check for the two easiest violations

Full linearizability checking is hard; these two catch most real problems and are trivial to implement.

```python
def check_read_your_writes(history) -> list[Violation]:
    """A process must never read a value older than one it wrote."""
    last_write: dict[int, tuple[object, int]] = {}   # process -> (value, time)
    violations = []
    for e in history:
        if e.op_type != "ok":
            continue
        if e.function == "write":
            last_write[e.process] = (e.value, e.time_ns)
        elif e.function == "read" and e.process in last_write:
            written, t = last_write[e.process]
            if e.time_ns > t and e.value != written and not _is_newer(e.value, written):
                violations.append(Violation("RYW", e, written))
    return violations


def check_monotonic_reads(history) -> list[Violation]:
    """A process must never see a version go backwards."""
    last_seen: dict[int, int] = {}      # process -> highest version observed
    violations = []
    for e in history:
        if e.op_type == "ok" and e.function == "read":
            v = e.value.version
            if e.process in last_seen and v < last_seen[e.process]:
                violations.append(Violation("MonotonicReads", e, last_seen[e.process]))
            last_seen[e.process] = max(last_seen.get(e.process, 0), v)
    return violations
```

### Inject the faults that actually find bugs

```bash
# Network partition (the fault that finds the most)
iptables -A INPUT  -s 10.0.1.2 -j DROP
iptables -A OUTPUT -d 10.0.1.2 -j DROP

# Asymmetric partition — often finds bugs a symmetric one does not,
# because it breaks failure-detection assumptions
iptables -A INPUT -s 10.0.1.2 -j DROP        # only one direction

# Latency and loss
tc qdisc add dev eth0 root netem delay 200ms 50ms loss 2%

# ⭐ Process pause — simulates a GC pause or CPU throttling (DD02 §2).
#    This finds lease and lock bugs that no network fault will.
kill -STOP $PID;  sleep 30;  kill -CONT $PID

# Clock skew
date -s "+5 seconds"

# Kill the leader repeatedly during writes
```

> **The two highest-yield faults are the asymmetric partition and the process pause.** Symmetric partitions are what everyone tests; asymmetric ones break failure detectors. And `SIGSTOP` reproduces the exact scenario that fencing tokens exist for (DD02 §19) — a process that believes it still holds a valid lease.

### Where to focus your own testing

```
1. Your idempotency keys       — are duplicate requests genuinely safe? (Ch. 05)
2. Your distributed locks      — can two holders exist under a pause?
3. Your outbox relay           — can an event be lost or duplicated? (Ch. 06)
4. Your cache invalidation     — can a stale value become permanent? (Ch. 11)
5. Your saga compensations     — do they run, and are they idempotent? (Ch. 05)
6. Your multi-row invariants   — is it write skew? (§9)
```

---

## 20. Choosing a model: the decision procedure

```
For each OPERATION (not each system):

1. If a stale or out-of-order read causes financial loss, legal exposure,
   or a safety issue:
       → LINEARIZABLE (or strict serializable if multi-object)
       → Accept the latency and the unavailability under partition

2. Else, if an invariant spans multiple rows/objects:
       → SERIALIZABLE with retry, or a DB constraint, or one aggregate
       → Check specifically for WRITE SKEW (§9)

3. Else, if the user must see their own changes:
       → READ-YOUR-WRITES + MONOTONIC READS at minimum
       → Best implementation: return the new value from the write; do not re-read

4. Else, if causal anomalies would confuse users (replies before posts,
   counts going backwards):
       → CAUSAL, or session-scoped causal (the four guarantees) — §13

5. Else:
       → EVENTUAL, with a MEASURED and MONITORED convergence bound
       → And a deliberately chosen conflict-resolution rule that is NOT
         "whatever the default is"
```

### Applied to one system

For the liveness verification SaaS (Chapter 25 §1):

| Operation | Model | Why |
|-----------|-------|-----|
| Record a verification decision | **Strict serializable** | Regulatory; must never be reordered or lost |
| Check and decrement tenant quota | **Serializable** (or atomic UPDATE + constraint) | Multi-row invariant; classic write skew shape |
| Read own session status | **Read-your-writes** | The user just submitted; must see it |
| Reviewer dashboard list | **Causal / session** | Must not show a decision before its session |
| Tenant analytics | **Eventual**, bounded to 5 min | Nobody acts on a 30-second-old number |
| Per-tenant verification counter | **Strong eventual (CRDT)** | Increments only; merges by construction |

> **Notice that one system uses five different models.** That is correct engineering, not inconsistency. Applying strict serializability to the analytics dashboard would cost latency for no benefit; applying eventual consistency to the decision record would be a regulatory finding.

---

## 21. What an architect takes from this

**1. "Strongly consistent" is not an answer.** Linearizable, serializable, and strictly serializable are three different products with three different costs. Ask which, every time, of every vendor.

**2. Linearizability composes; sequential consistency does not.** This single theorem is why range-sharded distributed databases work, and why you can reason about linearizable components locally instead of re-proving the whole system.

**3. Linearizability is about single objects. Atomicity across objects needs transactions.** Systems that provide the first and imply the second are a common source of surprise.

**4. Write skew is the anomaly your default isolation level allows.** For every invariant spanning multiple rows, ask explicitly whether it is write skew. The fix order is: constraint > serializable+retry > explicit lock > aggregate boundary.

**5. Level names lie.** Oracle's `SERIALIZABLE` is snapshot isolation. PostgreSQL's `REPEATABLE READ` is snapshot isolation. Read which anomalies are prevented, not what the level is called.

**6. Causal consistency is the CAP boundary.** It is the strongest model available to a system that stays up during a partition — which makes it the right target for AP systems, and the four session guarantees are the cheap, O(1) way to get its user-visible benefit.

**7. Eventual consistency alone is not a usable guarantee.** It needs the session guarantees and a bounded, monitored convergence time before humans can use it. "Bounded staleness" is the level more systems should offer.

**8. CRDTs remove conflicts by construction, where the merge matches the meaning.** They cannot enforce global invariants — and that is CAP, not a limitation of the technique.

**9. Jepsen's findings cluster into four buckets** — unsafe defaults, stale leader reads, silent LWW, and marketing-vs-mechanism — all four of which you can check yourself before adoption.

**10. Choose the model per operation, and write the choice down.** One system legitimately spans five models. The ADR that records which operation gets which guarantee, and why, is one of the most valuable documents you will write (Chapter 22).

---

## Exercises

1. Write the formal definition of linearizability from memory, then use it to decide these histories:
   ```
   (a) C1: |--W(x,1)--|         C2: |--R(x)→0--|         (overlapping)
   (b) C1: |--W(x,1)--|  C2: |--R(x)→1--|  C3: |--R(x)→0--|
   (c) C1: |--R(x)→1--|  C2: |--W(x,1)--|                (read before write!)
   ```
2. Prove that linearizability composes, then construct a two-object history that is sequentially consistent per object but not sequentially consistent overall (do not just copy §6 — build a new one).
3. Give a real business invariant from your own system and determine whether it is vulnerable to write skew. If it is, give all four fixes from §9 and choose one.
4. Draw the DSG for the on-call write-skew scenario. Mark each edge type. Explain why SI permits the cycle and SSI does not.
5. Construct a history that is serializable but not strictly serializable, and explain why a user would report it as a bug.
6. Why can a *read-only* transaction be aborted under PostgreSQL's SSI? Construct the anomaly it prevents.
7. Implement a PN-Counter and prove that its merge is commutative, associative and idempotent.
8. Explain why "the account balance" cannot be a CRDT. What would you have to give up to make it one?
9. Your system uses DynamoDB global tables. What is the conflict resolution rule, and what user-visible bug should you expect? Design a mitigation.
10. Record a history from your own application under a `SIGSTOP` fault injection and check it for read-your-writes and monotonic-reads violations.
11. For each operation in a system you work on, assign a consistency model using §20's procedure. Justify each one in a sentence.
12. A vendor says "we provide strong consistency with no latency penalty and no special hardware". List the three follow-up questions that would resolve what they actually mean.

---

**Next in this series:** Deep Dive 04 — Failure Detection and Membership

**Back to:** [Deep Dives](README.md) · [Chapter 05](../05-distributed-systems.md) · [The Map](../README.md)
