# Chapter 05 — Distributed Systems 🟢🟢

> **This is the most important chapter in the book.**
>
> The moment your system has more than one process talking over a network, everything you know about programming becomes *slightly* untrue. Function calls can now fail halfway. Time is no longer a single thing. "Did it work?" becomes genuinely unanswerable.
>
> Most production incidents in modern systems are distributed systems problems wearing a costume.

---

## 5.1 What makes distributed systems hard

A local function call:
- Always returns (or throws), always fast, never partially executes, and you always know the outcome.

A network call:
- May succeed
- May fail
- May succeed but the **response** is lost — **you cannot tell this apart from failure**
- May take 100 ms or 100 seconds
- May arrive **twice**
- May arrive **out of order**
- May arrive **after you gave up and retried**

> **The fundamental problem: you cannot distinguish "it failed" from "it succeeded but I didn't hear back".**
>
> Everything else in this chapter is a technique for living with that fact.

### The Eight Fallacies of Distributed Computing

Peter Deutsch's list from 1994. Every one is still violated daily.

| # | Fallacy | Reality | What it costs you |
|---|---------|---------|-------------------|
| 1 | **The network is reliable** | Packets drop, cables get cut, switches reboot, cloud AZs partition | Every call needs timeout + retry + fallback |
| 2 | **Latency is zero** | 0.5 ms same-DC, 150 ms cross-continent | Chatty designs die. Batch your calls. |
| 3 | **Bandwidth is infinite** | It is metered and finite | Big payloads cost money and time |
| 4 | **The network is secure** | It is not | TLS everywhere, mTLS between services, zero trust |
| 5 | **Topology doesn't change** | Pods move, IPs change, instances are replaced hourly | Service discovery, never hard-code IPs |
| 6 | **There is one administrator** | Ten teams, three clouds, five vendors | Coordination cost; nobody knows the whole system |
| 7 | **Transport cost is zero** | Serialisation, TLS handshakes, egress fees are real | JSON parsing is often the CPU hotspot |
| 8 | **The network is homogeneous** | Different protocols, versions, MTUs, proxies | Compatibility bugs at the edges |

**Hard-earned rule:** whenever you write a line of code that crosses a process boundary, pause and ask — *what happens if this takes 30 seconds? What if it never returns? What if it runs twice?*

---

## 5.2 Partial failure — the defining problem

In a monolith, either the process is up or it is down. Binary. Simple.

In a distributed system, **some parts work and some do not**, and different observers disagree about which.

```
Service A ──► Service B    OK
Service A ──► Service C    TIMEOUT (but did C do the work?)
Service B ──► Service C    OK        ← B can reach C, A cannot. Now what?
```

### The Two Generals Problem

Two armies on opposite hills must attack at the same time. They communicate by messenger, and messengers can be captured.

- General A sends: "Attack at dawn." Did it arrive?
- B sends an ack. Did *that* arrive?
- A sends an ack of the ack…

> **There is no finite sequence of messages that gives both sides certainty.** This is proven, not a limitation of technology.

**Practical consequence:** **exactly-once delivery over a network is impossible.** You get *at-most-once* or *at-least-once*. Everything advertised as "exactly once" is really **at-least-once delivery + idempotent processing**, which is a perfectly good engineering answer — just know what it actually is.

### Designing for partial failure

For every remote call, decide **in advance**:

1. **Timeout** — how long before I give up? (Always set one. Defaults are usually infinite or absurd.)
2. **Retry** — should I? How many times? With what backoff? Is the operation safe to repeat?
3. **Fallback** — cached value? Default value? Degraded feature? Fail the request?
4. **Idempotency** — if this runs twice, does the business break?

```python
# Every outbound call, every time. Make this a template in your codebase.
async def charge_customer(customer_id: str, amount: Money, idem_key: str) -> ChargeResult:
    return await self._client.post(
        "/charges",
        json={"customer": customer_id, "amount": str(amount.value),
              "currency": amount.currency},
        headers={"Idempotency-Key": idem_key},   # safe to retry
        timeout=Timeout(connect=2.0, read=10.0), # never infinite
    )
```

---

## 5.3 Time and clocks 🟢

**In a distributed system there is no "now".**

### Why wall clocks lie

- Machines drift (typically 100–200 ms/day without NTP; much worse on VMs)
- NTP corrections jump the clock **backwards** — `t2 - t1` can be negative
- Leap seconds have caused real, major outages (Reddit, 2012)
- Virtual machines pause and resume, and the clock jumps
- Different machines are simply never exactly in sync

```python
# BUG: this can produce a negative duration, or a wildly wrong one
start = time.time()
do_work()
duration = time.time() - start     # NTP adjusted mid-work → garbage

# CORRECT: use a monotonic clock for durations
start = time.monotonic()
do_work()
duration = time.monotonic() - start   # never goes backwards
```

> **Rule: wall clock for "what time is it?" (timestamps for humans). Monotonic clock for "how long did it take?" Never mix them.**

### The dangerous pattern: Last Write Wins by timestamp

```
Node A (clock +50 ms fast): writes {name: "Delower"} at t=1000.050
Node B (clock correct):     writes {name: "Hosen"}   at t=1000.000  ← actually LATER in real time

LWW keeps A's value. B's write is silently lost. No error. No log. Just wrong data.
```

Cassandra, DynamoDB and Redis-based locks have all bitten people this way. **If correctness depends on ordering, do not use wall-clock timestamps to order events.**

### Logical clocks — ordering without time

**Lamport timestamps**: a simple counter per node.

```
Rules:
  1. Before any local event:     counter += 1
  2. When sending a message:     send (message, counter)
  3. On receiving a message:     counter = max(local, received) + 1

Gives: if A happened-before B, then LC(A) < LC(B)
Does NOT give: if LC(A) < LC(B), then A happened-before B  ← cannot detect concurrency
```

**Vector clocks**: one counter per node, carried together.

```
Node A: [A:3, B:1, C:0]
Node B: [A:2, B:4, C:0]

Compare element-wise:
  A[0]=3 > B[0]=2  but  A[1]=1 < B[1]=4
  → NEITHER dominates → these events are CONCURRENT → a real conflict exists
```

This is how Dynamo-style databases **detect** conflicts (rather than silently losing a write). They then either return both versions to the application ("siblings") or apply a merge rule.

**Hybrid Logical Clocks (HLC)** combine a physical timestamp with a logical counter — you get roughly-real timestamps *and* correct causal ordering. Used by CockroachDB, MongoDB and YugabyteDB. Worth knowing the name.

### Google's TrueTime (the expensive answer) ⚪

Spanner puts GPS receivers and atomic clocks in every datacenter, so it knows time within a bounded uncertainty ε (about 7 ms). To commit, it simply **waits out the uncertainty** before acknowledging.

Result: globally consistent, externally-ordered transactions across continents. The cost: ~14 ms of deliberate waiting per commit, plus atomic clocks. Know it exists; know that it required *hardware* to solve, which tells you how hard the problem is.

---

## 5.4 CAP Theorem 🟢

Eric Brewer's theorem, and the most misquoted idea in our field.

**The three properties:**

- **C — Consistency** (here meaning *linearizability*): every read sees the most recent write. All nodes agree.
- **A — Availability**: every request to a **non-failing** node receives a non-error response.
- **P — Partition tolerance**: the system keeps operating despite network messages being dropped between nodes.

**The theorem:** during a network partition, you must choose between C and A.

### The correct way to state it

> ❌ *"Pick two of three."* — Misleading. Networks partition; you do not get to opt out.
>
> ✅ **"When a partition happens, do you return an error (CP) or return possibly-stale data (AP)?"**

```
            Network partition splits the cluster
     ┌──────────────┐   ╳╳╳╳   ┌──────────────┐
     │  Node A      │   ╳╳╳╳   │  Node B      │
     │  balance=100 │   ╳╳╳╳   │  balance=100 │
     └──────────────┘          └──────────────┘
            ▲                          ▲
     Client writes 50            Client reads
            │                          │
      ┌─────┴─────┐             ┌──────┴──────┐
      │  CP: refuse the write   │  CP: refuse the read (error)  │
      │  (error, stay correct)  │                               │
      │                          │                               │
      │  AP: accept the write    │  AP: return 100 (stale)       │
      │  (reconcile later)       │                               │
      └──────────────────────────┴──────────────────────────────┘
```

### Which to choose — by business consequence

| Choose **CP** when wrong data is worse than no data | Choose **AP** when no data is worse than stale data |
|---|---|
| Bank balances and transfers | Social media feeds |
| Inventory for a limited item | Product view counts |
| Seat/ticket booking | Recommendations |
| Authentication and permissions | Analytics, logging |
| Medical records | Shopping cart (merge later — Amazon famously does this) |
| Payment processing | Presence/"user is online" indicators |

### Real systems

| System | Default | Notes |
|--------|---------|-------|
| PostgreSQL / MySQL (single leader) | **CP** | On partition, the minority side cannot write |
| MongoDB | **CP** | Configurable with write/read concerns |
| Cassandra | **AP** (tunable) | Per-query consistency levels |
| DynamoDB | **AP** by default | Strongly-consistent reads available at 2× cost |
| Redis (single) | **CP**-ish | Redis Cluster can lose writes on failover |
| ZooKeeper / etcd / Consul | **CP** | They exist to be correct — that is their job |
| Spanner / CockroachDB | **CP** with very high A | Tricks (TrueTime, Raft) make partitions rarely visible |

### PACELC — the more useful model 🟢

CAP only describes behaviour **during a partition**, which is rare. PACELC also describes the normal case.

> **if (P)artition: choose (A)vailability or (C)onsistency
> (E)lse: choose (L)atency or (C)onsistency**

**This is the more honest framing**, because the *everyday* trade-off is latency vs consistency. Strong consistency requires coordination; coordination requires network round trips; round trips cost milliseconds. Every time.

| System | PACELC |
|--------|--------|
| DynamoDB | PA/EL — available and fast, eventually consistent |
| Cassandra | PA/EL — same |
| MongoDB | PA/EC — available on partition, consistent otherwise |
| PostgreSQL | PC/EC — correctness first, always |
| Spanner | PC/EC — pays latency for global consistency |

> **The architect's sentence:** *"We chose eventual consistency for the feed because 200 ms of staleness is invisible to users, and strong consistency would add a 40 ms cross-region round trip to every read."*

---

## 5.5 Consistency models 🟢

"Consistency" means at least three different things depending on who is speaking. Disentangle them:

- **ACID consistency** (databases): the database enforces your constraints
- **CAP consistency**: linearizability — all nodes see one order of events
- **Cache/replica consistency**: how stale can a copy be?

Here we mean the second and third. From strongest (and slowest) to weakest (and fastest):

### 1. Linearizable (strong / atomic / external consistency)

Every operation appears to take effect **instantaneously** at some point between its start and end. The system behaves as if there is exactly one copy of the data.

```
Client A: write(x=1) ────────█────────
Client B:              read(x) ──█──── → MUST return 1
```

- ✅ Simplest to reason about. Behaves like a single machine.
- ❌ Requires coordination on every operation → high latency, lower availability
- Where: etcd, ZooKeeper, Spanner, single-node databases, DynamoDB strong reads

### 2. Sequential consistency

All nodes see operations in the *same order*, but that order need not match real time. Weaker than linearizable, rarely offered explicitly.

### 3. Causal consistency ⭐

Operations that are **causally related** are seen in the same order by everyone. Concurrent (unrelated) operations may be seen in different orders.

```
Alice posts: "I lost my keys"          (event 1)
Alice posts: "Found them!"             (event 2, caused by 1)
Bob comments on 2: "Great!"            (event 3, caused by 2)

Causal consistency guarantees NOBODY sees Bob's "Great!" before "Found them!".
It does NOT order Alice's post against Carol's unrelated post.
```

> **This is the sweet spot for most user-facing systems** — strong enough that the application never looks broken to a human, weak enough to be fast and available. It is the strongest model achievable while remaining available during a partition.

### 4. Read-your-writes (session consistency)

A user always sees their own writes. Other users may see stale data.

**Non-negotiable in practice.** If a user updates their profile and the page shows the old name, they will report a bug — every time. Implement it with leader reads, sticky routing, or by returning the new value directly.

### 5. Monotonic reads

You never see time go backwards. Once you have seen a value, you never see an older one.

```
Without it:
  Read 1 (replica A, up to date):   "5 comments"
  Read 2 (replica B, behind):       "3 comments"   ← comments vanished! Users panic.
```

Fix: pin a user to one replica (consistent hashing on user ID).

### 6. Monotonic writes

Your own writes are applied in the order you made them. Obvious, but not free in a leaderless system.

### 7. Eventual consistency

If writes stop, all replicas eventually converge. That is the entire promise — no bound on "eventually".

- ✅ Highest availability and lowest latency
- ❌ "Eventually" can be 10 ms or (during an incident) 10 minutes. Applications must tolerate it.

> **The four session guarantees** — read-your-writes, monotonic reads, monotonic writes, writes-follow-reads — are what make eventual consistency *usable* by real people. Implement them even on an eventually-consistent store.

### Choosing, in practice

```
Does incorrect data cause financial loss, legal exposure, or safety risk?
├── YES → linearizable for THAT operation (and only that one — it is expensive)
└── NO  → Does the user need to see their own changes immediately?
          ├── YES → read-your-writes + causal (the common answer)
          └── NO  → eventual consistency (feeds, counters, analytics)
```

**Key insight:** consistency is chosen **per operation**, not per system. In one application: strong consistency for "place order" and "check balance"; eventual for "view count", "recommendations" and "recently viewed". Mixing is correct engineering, not inconsistency.

---

## 5.6 Consensus 🟢

**The problem:** several nodes must agree on one value (who is the leader, what is the next log entry, is this transaction committed), despite failures.

### Why it is hard — FLP impossibility

> In an asynchronous network where even one node may fail, **no deterministic algorithm can guarantee consensus in bounded time.**

The workaround everyone uses: **randomised timeouts**. Consensus is guaranteed *safe* always, and *live* whenever the network behaves. That is why Raft leaders use random election timeouts — to break symmetry probabilistically.

### Quorum — the basic building block

A **quorum** is a majority: `⌊N/2⌋ + 1`.

```
N = 3  → quorum = 2  → tolerates 1 failure
N = 5  → quorum = 3  → tolerates 2 failures
N = 7  → quorum = 4  → tolerates 3 failures
```

**Why a majority?** Because two different majorities of the same set must overlap in at least one node. That overlap is what makes two conflicting decisions impossible.

**Why an odd number?** N=4 also has quorum 3, so it tolerates only 1 failure — the same as N=3, at higher cost and higher latency. **Always run odd-sized clusters: 3, 5, or 7.** Rarely more — every extra node adds latency to every decision.

### Raft — understandable consensus 🟢

Raft was explicitly designed to be teachable (unlike Paxos). Three sub-problems:

**1. Leader election**

```
Every node is FOLLOWER, CANDIDATE, or LEADER.

FOLLOWER:  waits for heartbeats from the leader.
           If no heartbeat within a RANDOM timeout (e.g. 150–300 ms) → become CANDIDATE.

CANDIDATE: increment term, vote for self, request votes from all.
           Got a majority? → become LEADER.
           Saw a higher term? → step down to FOLLOWER.
           Timeout with no winner? → new random timeout, try again.

LEADER:    send heartbeats every ~50 ms. Handle all client writes.
```

The **random** timeout is the key trick — it makes simultaneous candidacies rare, so elections converge quickly.

**2. Log replication**

```
Client → Leader: SET x = 5
  1. Leader appends {term, index, "SET x=5"} to its log  (uncommitted)
  2. Leader sends AppendEntries to all followers
  3. Followers append and acknowledge
  4. Once a MAJORITY has acked → the entry is COMMITTED
  5. Leader applies it to its state machine and responds to the client
  6. Followers learn of the commit in the next heartbeat and apply it too
```

**3. Safety** — a candidate can only win if its log is at least as up to date as the voter's. This guarantees a committed entry is never lost.

### Split brain — the failure everyone fears

Two nodes both believe they are the leader. Both accept writes. Data diverges. Someone's money disappears.

```
        ╳╳ partition ╳╳
  ┌──────────────┐  ┌──────────────────────┐
  │   Node A     │  │  Node B    Node C    │
  │  (old leader)│  │        Node D  E     │
  │   1 node     │  │        4 nodes       │
  └──────────────┘  └──────────────────────┘
   Cannot reach a      HAS quorum (4 of 5)
   quorum (1 of 5)     → elects a new leader
   → MUST step down       → safely accepts writes
```

**Quorum prevents split brain** — the minority side mathematically cannot form a majority, so it must refuse writes. This is why quorum-based systems are CP: the minority chooses unavailability over incorrectness.

**Other protections:**
- **Fencing tokens** — every leader gets a monotonically increasing number; downstream systems reject any request carrying an older token. This protects against a *paused* old leader waking up and issuing a stale write.
- **STONITH** ("shoot the other node in the head") — forcibly power off the suspect node. Common in traditional HA clusters.
- **Lease-based leadership** — leadership expires unless renewed, so an isolated leader self-demotes.

### Paxos ⚪

The original consensus algorithm (Leslie Lamport, 1989). Provably correct, famously hard to understand and harder to implement correctly. Multi-Paxos is used in Google Chubby and Spanner. **Awareness is enough** — know that Raft exists because Paxos was too hard.

### Byzantine Fault Tolerance ⚪

Normal consensus assumes nodes may *crash* but never *lie*. BFT handles malicious nodes, requiring `3f + 1` nodes to tolerate `f` traitors. Used in blockchains and aerospace. You will almost certainly never need it inside your own datacenter.

### Where you actually meet consensus

You rarely implement it. You **use** it:

| System | Uses consensus for |
|--------|-------------------|
| etcd (Kubernetes' brain) | All cluster state |
| ZooKeeper | Leader election, config, locks |
| Consul | Service registry, leader election |
| Kafka (KRaft) | Controller election, metadata |
| CockroachDB / TiDB / YugabyteDB | Per-range replication |
| MongoDB | Replica-set primary election |

> **Architect's guidance: never write your own consensus algorithm.** Use etcd/ZooKeeper/Consul. Distributed locks built on a single Redis instance are *not* safe (see the well-known Redlock debate) — if correctness depends on the lock, use a real consensus system, or design so you do not need the lock at all.

---

## 5.7 Distributed transactions 🟢

**The problem:** one business operation must change data in two or more services/databases, atomically.

**Example:** an order must (a) reserve inventory, (b) charge a card, (c) create a shipment. All or nothing.

### Two-Phase Commit (2PC) — the textbook answer that you should usually avoid

```
PHASE 1: PREPARE
  Coordinator → all participants: "Can you commit? Lock your resources."
  Participants: write to their log, LOCK the rows, reply YES or NO

PHASE 2: COMMIT or ABORT
  If ALL said YES → Coordinator → all: "COMMIT"
  If ANY said NO  → Coordinator → all: "ABORT"
```

**Why it is mostly avoided in modern systems:**

| Problem | Detail |
|---------|--------|
| **Blocking** | If the coordinator dies after PREPARE, participants hold their locks **indefinitely**, waiting. Your database is now frozen, holding locks nobody can release. |
| **Coordinator is a SPOF** | Needs its own HA, which needs consensus, which... |
| **Locks held across the network** | Latency is now the duration of the *slowest* participant. Throughput collapses. |
| **Not available** | Any participant down = no transactions at all (it is strongly CP) |
| **Limited support** | Most modern data stores and all HTTP APIs simply do not support it |

**When 2PC is still fine:** inside one organisation, one datacenter, short transactions, on systems that support XA (classic: a database plus a message broker in an enterprise Java stack). Otherwise, use Sagas.

### Saga pattern ⭐ 🟢 — the practical answer

**The idea:** break the distributed transaction into a sequence of **local** transactions. If a step fails, run **compensating** transactions to undo the earlier ones.

```
HAPPY PATH
  T1: Reserve inventory   ✓
  T2: Charge payment      ✓
  T3: Create shipment     ✓
  → done

FAILURE AT T3
  T1: Reserve inventory   ✓
  T2: Charge payment      ✓
  T3: Create shipment     ✗ FAILED
  C2: Refund payment      ← compensation
  C1: Release inventory   ← compensation
  → consistent again (eventually)
```

**Crucial mental shift:** a saga is **not** atomic. There are real moments where the customer is charged and no shipment exists. The business must accept this and the system must guarantee it converges. **Compensation is not rollback** — a refund is a new business fact, visible in statements, not an erasure.

### Choreography vs Orchestration (sagas)

**Choreography** — services react to each other's events:

```
Order Service ──[OrderCreated]──► Inventory Service
                                        │
                            [InventoryReserved]
                                        ▼
                                 Payment Service
                                        │
                              [PaymentCaptured]
                                        ▼
                                Shipping Service
```

✅ No central component; loose coupling
❌ **Nobody can see the whole process.** Debugging means reading 6 services. Adding a step means understanding all existing subscriptions. Cyclic dependencies are easy to create by accident.

**Orchestration** — a coordinator drives the steps:

```
                  ┌───────────────────────┐
                  │   Order Saga          │
                  │   Orchestrator        │
                  └───┬────┬────┬─────────┘
            reserve   │    │    │  ship
                 ┌────▼┐ ┌─▼───┐ ┌▼──────┐
                 │Inven│ │ Pay │ │Shippin│
                 └─────┘ └─────┘ └───────┘
```

✅ The whole process is **one readable file**; centralised error handling and timeouts; easy to monitor and to add steps
❌ The orchestrator is another service to run; risk of it becoming a god object with business logic that belongs elsewhere

> **Recommendation: orchestration for anything with 4+ steps or real money involved.** The visibility is worth it. Use choreography for simple fan-out notifications.

```python
class OrderSagaOrchestrator:
    """One readable file describing the whole business process."""

    async def execute(self, order: Order) -> SagaResult:
        completed: list[CompensationStep] = []
        try:
            res = await self._inventory.reserve(order.items, order.id)
            completed.append(lambda: self._inventory.release(res.reservation_id))

            pay = await self._payments.charge(
                order.customer_id, order.total,
                idempotency_key=f"order-{order.id}",      # safe to retry
            )
            completed.append(lambda: self._payments.refund(pay.charge_id))

            ship = await self._shipping.create(order.id, order.address)
            completed.append(lambda: self._shipping.cancel(ship.shipment_id))

            await self._orders.mark_confirmed(order.id)
            return SagaResult.success(order.id)

        except Exception as e:
            logger.error("saga failed for order %s: %s", order.id, e)
            await self._compensate(reversed(completed))     # UNDO, in reverse order
            await self._orders.mark_failed(order.id, str(e))
            return SagaResult.failed(order.id, str(e))

    async def _compensate(self, steps) -> None:
        for step in steps:
            try:
                await step()                               # must be idempotent
            except Exception as e:
                # Compensation failed. This needs a HUMAN. Never swallow it.
                logger.critical("COMPENSATION FAILED: %s", e)
                await self._alerts.page_oncall("saga_compensation_failed", error=str(e))
```

### The rules of saga design

1. **Every step must be idempotent** — it will be retried
2. **Every step needs a compensating action** — design it at the same time as the step, not later
3. **Compensations must also be idempotent** and must **never fail silently**
4. **Some steps cannot be compensated** — you cannot un-send an email. Put those **last**, or make them reversible in business terms (send a correction email).
5. **Use the semantic lock / pending-state trick** — mark records as `PENDING` so other operations know they are mid-saga
6. **Persist saga state** — if the orchestrator crashes mid-saga, it must resume. An in-memory orchestrator is a bug waiting to happen.
7. **Set timeouts on every step** — a saga stuck forever is worse than a failed one
8. **Make the saga observable** — a dashboard of in-flight sagas, stuck sagas, and compensation failures

### Where to put the order of operations

Order the steps so the **most likely to fail** and the **easiest to compensate** come first.

```
BAD:  charge card → reserve inventory → (out of stock) → refund
      The customer sees a charge and a refund. Support tickets.

GOOD: reserve inventory → authorise card → ship → CAPTURE payment
      Authorisation holds funds without taking them; releasing an auth is
      invisible to the customer. This is why real payment systems separate
      authorise from capture.
```

That single reordering removes most of your compensation pain. **Business design beats technical cleverness.**

### Tools

Do not hand-roll a durable orchestrator if you can avoid it: **Temporal**, **AWS Step Functions**, **Azure Durable Functions**, **Camunda/Zeebe**, **MassTransit Sagas**, **NServiceBus Sagas**. They give you persistence, retries, timeouts, versioning and a visual history for free.

---

## 5.8 Reliability patterns 🟢

These are the everyday tools. Know all of them cold.

### Timeout

**The most important and most neglected setting in your entire system.**

```python
# DANGEROUS — most HTTP clients default to no timeout or a very long one
response = requests.get(url)          # can hang forever

# CORRECT
response = requests.get(url, timeout=(3.0, 10.0))   # (connect, read)
```

**How to choose a timeout:** measure p99 latency of the dependency, then set the timeout a bit above it (p99 × 1.5 is a reasonable start). Not "30 seconds because that seems safe" — a 30-second timeout means 30 seconds of a held thread, a held connection, and a waiting user.

**Cascading timeout rule:** timeouts must **decrease** as you go deeper.

```
User          → 10 s budget
  API Gateway → 9 s
    Service A → 6 s
      Service B → 3 s
        Database → 1 s
```

If an inner call has a longer timeout than the outer one, the outer gives up first and the inner work is wasted — while still holding resources. Better still, propagate a **deadline** (an absolute time by which the answer is useless) through the call chain, as gRPC does.

### Retry

Retries turn transient failures into successes. They also turn a small problem into an outage if done naively.

```python
# WRONG — this is a DDoS on your own dependency
for attempt in range(5):
    try:
        return call_service()
    except Exception:
        continue            # no delay, no jitter, retries non-idempotent calls
```

```python
# RIGHT
async def call_with_retry(fn, *, max_attempts=3, base_delay=0.2, max_delay=5.0):
    for attempt in range(max_attempts):
        try:
            return await fn()
        except NonRetryableError:                 # 400, 401, 404, 422 — NEVER retry
            raise
        except RetryableError as e:               # 429, 502, 503, 504, timeouts
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = delay * (0.5 + random.random())          # FULL JITTER
            if (ra := getattr(e, "retry_after", None)):      # honour Retry-After
                delay = max(delay, ra)
            await asyncio.sleep(delay)
```

**Rules for retries:**

1. **Only retry idempotent operations.** Retrying a non-idempotent POST creates duplicate charges.
2. **Only retry retryable errors.** 400/404/422 will never succeed; retrying them wastes everything.
3. **Exponential backoff** — 200 ms, 400 ms, 800 ms, 1.6 s…
4. **Add jitter** — this is not optional. See below.
5. **Cap the attempts** (3 is usually right) and cap the total time
6. **Do not retry at every layer.** 3 retries × 4 layers = 81 calls to the bottom service. Retry at **one** layer, usually the outermost that has enough context.
7. **Honour `Retry-After`** headers

**Why jitter matters — the thundering herd:**

```
WITHOUT JITTER: a service blips. 5,000 clients all fail at t=0.
  All retry at t=1 s      → 5,000 simultaneous requests → service dies again
  All retry at t=2 s      → 5,000 simultaneous requests → dies again
  → synchronised retry storm; the service never recovers

WITH FULL JITTER: retries spread randomly over [0, delay]
  → smooth load; the service recovers
```

AWS published the definitive analysis of this; "full jitter" (`sleep = random(0, base * 2^attempt)`) performs best in almost all cases.

### Circuit Breaker ⭐

**Problem:** a dependency is down. Every request waits for a timeout, consuming a thread. Your threads are exhausted. Now *you* are down too. The failure has cascaded.

**Solution:** stop calling a failing dependency, fail fast, and probe occasionally to see if it recovered.

```
        ┌─────────────────────────────────────────────┐
        │                                             │
        ▼                                             │
    ┌────────┐  failures > threshold   ┌────────┐     │
    │ CLOSED │ ──────────────────────► │  OPEN  │     │
    │ (normal)│                         │(fail   │     │
    └────────┘ ◄────────────────────── │ fast)  │     │
        ▲       probe succeeded         └───┬────┘     │
        │                                   │ after    │
        │       ┌───────────┐               │ cooldown │
        └────── │ HALF-OPEN │ ◄─────────────┘          │
                │ (let 1–5  │                          │
                │  through) │──── probe failed ────────┘
                └───────────┘
```

```csharp
// Polly (.NET) — production-grade in a few lines
var pipeline = new ResiliencePipelineBuilder<HttpResponseMessage>()
    .AddRetry(new RetryStrategyOptions<HttpResponseMessage>
    {
        MaxRetryAttempts = 3,
        BackoffType = DelayBackoffType.Exponential,
        UseJitter = true,
        Delay = TimeSpan.FromMilliseconds(200),
    })
    .AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
    {
        FailureRatio = 0.5,                          // 50% of calls failing
        MinimumThroughput = 20,                      // ...over at least 20 calls
        SamplingDuration = TimeSpan.FromSeconds(30),
        BreakDuration = TimeSpan.FromSeconds(15),    // then probe
    })
    .AddTimeout(TimeSpan.FromSeconds(5))
    .Build();
```

**Design notes:**
- **One breaker per dependency**, not one global breaker
- When open, **return a fallback** if you can (cached value, default, degraded feature) — otherwise fail fast with a clear error
- **Emit a metric and an alert** when a breaker opens. An open breaker is a real incident signal.
- Tune `MinimumThroughput` so a low-traffic endpoint does not trip on 2 failures

### Bulkhead

Named after ship compartments: a hole in one compartment does not sink the ship.

**Problem:** one slow dependency consumes the entire thread pool, so *unrelated* endpoints also fail.

```
WITHOUT BULKHEAD                    WITH BULKHEAD
┌──────────────────────┐            ┌──────┬──────┬──────────┐
│  200 shared threads  │            │  50  │  50  │   100    │
│                      │            │vendor│ mail │  normal  │
│ slow vendor eats ALL │            │ pool │ pool │  traffic │
│ 200 → everything dies│            └──────┴──────┴──────────┘
└──────────────────────┘            slow vendor uses its 50 and stops.
                                    The other 150 keep working.
```

Implementations: separate thread pools, separate connection pools, semaphores limiting concurrency per dependency, or — at the infrastructure level — separate pods/instances per workload.

### Rate Limiting

Protect yourself from too much traffic (or from one noisy tenant).

| Algorithm | How | Trade-off |
|-----------|-----|-----------|
| **Fixed window** | 100 req per minute-bucket | Simple; but allows a 2× burst at the boundary (100 at 11:59:59 + 100 at 12:00:00) |
| **Sliding window log** | Store every request timestamp | Exact; memory-hungry |
| **Sliding window counter** | Weighted blend of two windows | Good balance — **common default** |
| **Token bucket** ⭐ | Tokens refill at a rate; a request takes one | **Allows controlled bursts** — usually the best UX |
| **Leaky bucket** | Requests drain at a fixed rate | Smooths output completely; no bursts allowed |

```python
# Token bucket in Redis, atomic via Lua (correct under concurrency)
TOKEN_BUCKET = """
local key      = KEYS[1]
local rate     = tonumber(ARGV[1])   -- tokens per second
local capacity = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])

local b       = redis.call('HMGET', key, 'tokens', 'ts')
local tokens  = tonumber(b[1]) or capacity
local last    = tonumber(b[2]) or now

tokens = math.min(capacity, tokens + (now - last) * rate)
local allowed = tokens >= cost
if allowed then tokens = tokens - cost end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) * 2)
return { allowed and 1 or 0, tokens }
"""
```

**Always return the standard headers** so clients can behave well:

```
HTTP/1.1 429 Too Many Requests
RateLimit-Limit: 1000
RateLimit-Remaining: 0
RateLimit-Reset: 42
Retry-After: 42
```

### Load Shedding

When overloaded, **deliberately reject some work** so the rest succeeds.

Rate limiting is per-client and pre-agreed. Load shedding is **whole-system self-defence** based on current health.

```python
async def maybe_shed(request) -> bool:
    if queue_depth() > CRITICAL:
        return request.priority != Priority.CRITICAL   # keep only payments/auth
    if queue_depth() > HIGH:
        return request.priority == Priority.LOW        # drop analytics, prefetch
    return False
```

> **Counter-intuitive but vital:** serving 70% of requests well is far better than serving 100% of requests so slowly that they all time out anyway. A system that never sheds load will collapse completely instead of degrading.

Advanced: **adaptive concurrency limits** (Netflix's approach) — infer the healthy concurrency limit from observed latency, and shed above it.

### Backpressure

A fast producer overwhelming a slow consumer. Instead of buffering until you run out of memory, **push back**.

```
Producer ──► [ Queue ] ──► Consumer (slow)
                 │
    Queue grows → memory grows → OOM kill → EVERYTHING is lost
```

Techniques:
- **Bounded queues** — block or reject when full (never use an unbounded queue in production)
- **TCP flow control** — free, built in, if you are using streams
- **Reactive Streams / `request(n)`** — the consumer states how much it can take
- **Pause consumption** — stop reading from the socket/broker; the broker holds the data (it is designed to)
- **Return 503 / 429** upstream

> **Rule: the queue is not the solution to a slow consumer — it is a shock absorber.** If the queue grows without bound, you have a capacity problem, not a buffering problem. Alert on queue depth and on *queue age* (how old is the oldest message) — age is the better signal.

### Graceful Degradation

Reduce functionality rather than failing entirely.

| Full service | Degraded mode |
|--------------|---------------|
| Personalised recommendations | Generic bestsellers |
| Live inventory count | "In stock" / "Out of stock" |
| Real-time fraud score | Rule-based fallback + flag for review |
| Rich product page | Cached static version |
| Search with filters and facets | Basic keyword search |

```python
async def get_recommendations(user_id: str) -> list[Product]:
    try:
        return await ml_service.recommend(user_id, timeout=0.3)
    except (TimeoutError, ServiceUnavailable):
        metrics.increment("recommendations.degraded")
        return await cache.get_or_compute("bestsellers", ttl=3600)
```

**Design rule:** for every feature, know its **degraded mode** and its **minimum viable path**. What is the smallest set of components that must work for a customer to complete the core transaction? Protect that path above all else.

---

## 5.9 Idempotency 🟢 — the single most important practical concept

**Definition:** performing an operation N times has the same effect as performing it once.

**Why it matters:** because retries are unavoidable, and duplicates are unavoidable, **idempotency is what makes an unreliable network safe.** Without it, at-least-once delivery means double charges.

### Which HTTP methods are idempotent?

| Method | Safe (no change) | Idempotent | Notes |
|--------|-----------------|-----------|-------|
| GET | ✅ | ✅ | |
| HEAD | ✅ | ✅ | |
| PUT | ❌ | ✅ | "set to this value" — repeating is harmless |
| DELETE | ❌ | ✅ | Second delete → 404 or 204; the *state* is the same |
| **POST** | ❌ | **❌** | "create another one" — **this is the dangerous one** |
| PATCH | ❌ | ❌* | `{"balance": 100}` is idempotent; `{"increment": 10}` is not |

### Making POST idempotent — the Idempotency Key pattern

This is how Stripe, PayPal, Adyen and every serious payments API work. Learn it and implement it.

```
Client generates a unique key (UUID) per logical operation and sends it:

POST /v1/charges
Idempotency-Key: 8f14e45f-ea2a-4f0e-b1d6-2c8e3f1a9b7d
{ "amount": 5000, "currency": "usd", "customer": "cus_123" }
```

```python
async def create_charge(request: ChargeRequest, idem_key: str) -> ChargeResponse:
    fingerprint = hashlib.sha256(request.canonical_json().encode()).hexdigest()

    async with db.transaction():
        existing = await db.fetch_one(
            "SELECT * FROM idempotency_keys WHERE key = $1 FOR UPDATE", idem_key)

        if existing:
            # Same key but a DIFFERENT body = a client bug. Never silently accept.
            if existing["fingerprint"] != fingerprint:
                raise IdempotencyKeyReuseError(idem_key)
            if existing["status"] == "completed":
                return ChargeResponse.parse_raw(existing["response"])   # replay
            if existing["status"] == "in_progress":
                raise ConcurrentRequestError(idem_key)                  # 409, retry later

        await db.execute(
            """INSERT INTO idempotency_keys (key, fingerprint, status, created_at)
               VALUES ($1, $2, 'in_progress', now())""", idem_key, fingerprint)

    try:
        result = await payment_gateway.charge(request)                  # the real work
        await db.execute(
            """UPDATE idempotency_keys
               SET status='completed', response=$2, completed_at=now()
               WHERE key=$1""", idem_key, result.json())
        return result
    except Exception:
        await db.execute("DELETE FROM idempotency_keys WHERE key=$1", idem_key)
        raise
```

```sql
CREATE TABLE idempotency_keys (
    key          TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,          -- hash of the request body
    status       TEXT NOT NULL,          -- in_progress | completed
    response     JSONB,
    created_at   TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX ON idempotency_keys (created_at);   -- for cleanup; keep keys ~24-72h
```

**Key design points:**
- **The client generates the key** (it must survive the client's own retry)
- Store the **response**, so a retry gets the identical answer
- Store a **fingerprint** of the request — same key + different body is a bug, and you must reject it loudly
- **Expire keys** after 24–72 hours
- The whole thing must be **transactional** or you have just moved the race condition

### Other ways to achieve idempotency

**1. Natural idempotency — design the operation to be stateless-safe**

```sql
-- Not idempotent
UPDATE accounts SET balance = balance + 100 WHERE id = 42;
-- Idempotent (absolute value, and guarded by a version)
UPDATE accounts SET balance = 500, version = 8 WHERE id = 42 AND version = 7;
```

**2. Deduplication table for message consumers**

```python
async def handle_message(msg: Message) -> None:
    try:
        await db.execute(
            "INSERT INTO processed_messages (message_id, processed_at) VALUES ($1, now())",
            msg.id)
    except UniqueViolation:
        logger.info("duplicate message %s ignored", msg.id)
        return                                    # already handled
    await do_the_work(msg)
```

Note the ordering subtlety: insert-then-work risks losing work if you crash in between; work-then-insert risks doing it twice. Doing **both inside one transaction** is the correct answer when the work is a database change. When the work is an external call, you are back to needing idempotency downstream — which is exactly why every good API offers an idempotency key.

**3. Upsert / conditional write**

```sql
INSERT INTO verification_results (session_id, score, decided_at)
VALUES ($1, $2, now())
ON CONFLICT (session_id) DO NOTHING;     -- second attempt changes nothing
```

**4. State machine guards**

```python
def mark_shipped(self) -> None:
    if self.status is OrderStatus.SHIPPED:
        return                      # already there — idempotent by design
    if self.status is not OrderStatus.PAID:
        raise InvalidTransition(self.status, OrderStatus.SHIPPED)
    self.status = OrderStatus.SHIPPED
```

### Exactly-once, honestly

> **"Exactly-once delivery" does not exist.**
> **"Exactly-once *processing*" does** — and it is built from **at-least-once delivery + idempotent consumers** (plus, where available, transactional writes that atomically commit the work and the offset).

When a vendor claims exactly-once, this is what they mean. Now you know what to ask them.

---

## 5.10 Service discovery and health 🟡

In a dynamic environment, instances appear and disappear constantly. Hard-coded IPs are fallacy #5.

**Client-side discovery:** client asks a registry, picks an instance, calls it directly. (Netflix Eureka + Ribbon.) More control, more client logic.

**Server-side discovery:** client calls a stable address; a load balancer/proxy resolves it. (Kubernetes Services, AWS ALB.) Simpler clients — **this is the modern default.**

**Kubernetes does it with DNS + endpoints:** you call `http://billing-service`, kube-DNS resolves it, kube-proxy load-balances to a healthy pod. Registration and deregistration are automatic, driven by readiness probes.

---

## 5.11 Putting it together: a resilient call

```python
class ResilientVendorClient:
    """Every pattern from this chapter, in one realistic class."""

    def __init__(self, http, cache, breaker, limiter, metrics):
        self._http, self._cache = http, cache
        self._breaker, self._limiter, self._metrics = breaker, limiter, metrics
        self._semaphore = asyncio.Semaphore(50)          # BULKHEAD

    async def verify(self, doc: Document, request_id: str) -> VerificationResult:
        cache_key = f"verify:{doc.content_hash}"

        if (hit := await self._cache.get(cache_key)) is not None:   # CACHE
            self._metrics.increment("vendor.cache_hit")
            return VerificationResult.parse_raw(hit)

        if not await self._limiter.allow("vendor_api", cost=1):      # RATE LIMIT
            raise ThrottledError(retry_after=self._limiter.reset_in("vendor_api"))

        if self._breaker.is_open:                                    # CIRCUIT BREAKER
            self._metrics.increment("vendor.circuit_open")
            return self._degraded_result(doc)                        # GRACEFUL DEGRADATION

        async with self._semaphore:                                  # BULKHEAD
            for attempt in range(3):                                 # RETRY
                try:
                    resp = await self._http.post(
                        "/verify",
                        json=doc.to_vendor_payload(),
                        headers={
                            "Idempotency-Key": request_id,           # IDEMPOTENCY
                            "X-Correlation-Id": request_id,          # TRACEABILITY
                        },
                        timeout=Timeout(connect=2.0, read=8.0),      # TIMEOUT
                    )
                    resp.raise_for_status()
                    result = VerificationResult.from_vendor(resp.json())  # ACL

                    self._breaker.record_success()
                    await self._cache.set(cache_key, result.json(), ttl=3600)
                    return result

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    self._breaker.record_failure()
                    if attempt == 2:
                        self._metrics.increment("vendor.exhausted_retries")
                        return self._degraded_result(doc)
                    delay = 0.2 * (2 ** attempt) * (0.5 + random.random())  # JITTER
                    await asyncio.sleep(delay)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code < 500:                 # NOT retryable
                        self._breaker.record_success()               # their fault, not ours
                        raise VendorRejectedError(e.response.json())
                    self._breaker.record_failure()
                    if attempt == 2:
                        return self._degraded_result(doc)
                    await asyncio.sleep(0.2 * (2 ** attempt) * (0.5 + random.random()))

    def _degraded_result(self, doc: Document) -> VerificationResult:
        """Vendor unavailable → queue for manual review rather than failing the user."""
        return VerificationResult.manual_review(
            reason="automated verification temporarily unavailable")
```

---

## 5.12 Common mistakes

1. **No timeouts** — the single most common cause of cascading failure
2. **Retrying non-idempotent operations** — double charges, duplicate orders
3. **Retries without jitter** — synchronised thundering herd; the service never recovers
4. **Retries at every layer** — 3 retries × 4 layers = 81 requests hitting the bottom
5. **Using wall-clock timestamps to order events** — silent data loss via LWW
6. **`time.time()` for measuring durations** — NTP adjustments give negative durations
7. **Believing "exactly once" exists** — design for at-least-once + idempotency instead
8. **Distributed locks on a single Redis** — not safe under partition; use etcd/ZooKeeper if correctness depends on it
9. **2PC across services or the internet** — blocking, fragile, and usually unavailable
10. **Sagas without persisted state** — orchestrator restarts and the saga is lost forever
11. **Sagas without compensation design** — "we'll add rollback later" never happens
12. **Unbounded queues** — turns backpressure into an out-of-memory kill
13. **Even-numbered consensus clusters** — N=4 buys you nothing over N=3
14. **No circuit breakers** — one slow dependency exhausts your threads and takes you down
15. **Assuming the network is secure** because it is "internal"

---

## 5.13 Architect's checklist

- [ ] Every outbound call has an explicit timeout
- [ ] Timeouts decrease with depth (or deadlines are propagated)
- [ ] Retry policy defined: which errors, how many, backoff **with jitter**
- [ ] Retries happen at exactly **one** layer
- [ ] Every retryable operation is idempotent (key, dedup table, or natural)
- [ ] Circuit breaker on every external dependency, with a metric and an alert
- [ ] Bulkheads separate critical and non-critical dependencies
- [ ] Rate limiting at the edge, with correct 429 headers
- [ ] Load shedding defined, with a priority order
- [ ] All queues bounded; alerts on queue depth **and queue age**
- [ ] Degraded mode defined for every non-critical dependency
- [ ] The minimum viable path (core transaction) is identified and protected
- [ ] Consistency model chosen **per operation**, and written down
- [ ] Distributed transactions use sagas, with compensations designed upfront
- [ ] Saga state is persisted and resumable; stuck sagas are alerted on
- [ ] Consensus clusters are odd-sized (3/5/7)
- [ ] Correlation IDs propagate through every hop
- [ ] Monotonic clocks used for durations

---

## 5.14 Self-test

1. Why can you never distinguish "failed" from "succeeded but the response was lost"? What follows from that?
2. List the eight fallacies. Which one bites you most often in practice?
3. State CAP correctly (not "pick two"). Then state PACELC and explain why it is more useful.
4. Give an operation in your own system that needs linearizability and one that only needs eventual consistency.
5. What are the four session guarantees, and why do they make eventual consistency usable?
6. Why must a consensus cluster have an odd number of nodes?
7. What is split brain, and what two mechanisms prevent it?
8. Why is 2PC usually the wrong answer across services? Name three specific problems.
9. Design a saga for a hotel booking (room + payment + confirmation email). Where do you put the email, and why?
10. Explain the Idempotency Key pattern end-to-end. Why store a fingerprint of the request body?
11. What happens without jitter in retries? Draw the timeline.
12. Explain circuit breaker states and transitions. What should happen when a breaker opens?
13. Why is a liveness probe that checks the database dangerous? (Chapter 04, but it belongs here too.)
14. Someone says their queue gives "exactly-once delivery". What do you ask them?

---

## 5.15 Key takeaways

- **You cannot tell failure from a lost response.** Everything else follows from this.
- **Partial failure is the normal state** of a distributed system, not an exception
- **There is no "now".** Use monotonic clocks for durations; never order events by wall clock.
- **CAP: during a partition, choose error or stale.** PACELC: the rest of the time, choose latency or consistency.
- **Consistency is chosen per operation**, not per system
- **Quorum = majority.** It is what prevents split brain. Odd-sized clusters only.
- **Never write your own consensus.** Use etcd/ZooKeeper/Consul.
- **Sagas, not 2PC.** Design compensations at the same time as the steps. Order steps so the hardest-to-undo comes last.
- **Idempotency is the foundation of reliability.** At-least-once delivery + idempotent processing = exactly-once processing.
- **Timeout, retry with jitter, circuit breaker, bulkhead, rate limit, shed load, degrade gracefully.** These seven are your daily toolkit.
- **Serving 70% well beats serving 100% badly.**

---

**Next:** [Chapter 06 — Messaging & Event-Driven Architecture](06-messaging-and-event-driven-architecture.md)
