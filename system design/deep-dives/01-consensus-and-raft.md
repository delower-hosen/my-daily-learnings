# Deep Dive 01 — Consensus, Replication and Raft

**Prerequisite:** [Chapter 05 — Distributed Systems](../05-distributed-systems.md) §5.6

**What the map said:** *"Raft has three sub-problems: leader election, log replication, and safety. Never write your own consensus algorithm."*

**What this deep dive does:** derives quorums from first principles, specifies Raft completely enough that you could implement it, traces six failure scenarios line by line including the one that breaks naive implementations, explains the commit rule that looks wrong and is not, covers the four extensions every production system adds, and shows how to debug a real etcd cluster.

---

## Contents

```
1.  The problem: replicated state machines
2.  Why you cannot just ask everyone
3.  Quorums from first principles
4.  What FLP actually says
5.  Raft: the complete specification
6.  Traced scenario 1 — a normal election
7.  Traced scenario 2 — a split vote
8.  Traced scenario 3 — log divergence and repair
9.  The election restriction, and why it is necessary
10. The commit rule that looks wrong  ⭐ (Figure 8)
11. Traced scenario 4 — the Figure 8 execution
12. Why persistence must be fsync'd
13. Traced scenario 5 — the lost vote
14. A working implementation
15. Extension 1 — PreVote
16. Extension 2 — CheckQuorum and leader leases
17. Extension 3 — linearizable reads without writing
18. Extension 4 — learners and non-voting members
19. Membership changes
20. Log compaction and snapshots
21. Performance: the actual arithmetic
22. What etcd really does
23. Debugging a real cluster
24. Raft vs Paxos vs ZAB vs Viewstamped Replication
25. What an architect takes from this
```

---

## 1. The problem: replicated state machines

Every consensus system exists to build one thing: a **replicated state machine**.

```
        client commands
              │
              ▼
    ┌─────────────────────┐
    │  CONSENSUS MODULE   │  ← decides the ORDER
    └──────────┬──────────┘
               │  an agreed, identical sequence of commands
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  ┌─────┐   ┌─────┐   ┌─────┐
  │ LOG │   │ LOG │   │ LOG │   identical on every node
  └──┬──┘   └──┬──┘   └──┬──┘
     ▼         ▼         ▼
  ┌─────┐   ┌─────┐   ┌─────┐
  │ SM  │   │ SM  │   │ SM  │   deterministic state machine
  └─────┘   └─────┘   └─────┘
   same      same      same     → identical state
```

**The insight that makes this work:** if the state machine is **deterministic**, and every replica applies **the same commands in the same order**, then every replica ends in the same state. You have turned "keep several machines in agreement about arbitrary state" into "keep several machines in agreement about the order of an append-only list".

That reduction is the whole game. Consensus is *only* ever about agreeing on the next entry in a log.

**What "the state machine" is in practice:**

| System | State machine |
|--------|--------------|
| etcd | A key-value map |
| ZooKeeper | A hierarchical znode tree |
| CockroachDB | One Raft group *per key range* (thousands of groups) |
| Kafka (KRaft) | Cluster metadata: topics, partitions, ISR membership |
| Consul | Service registry and KV |
| TiKV | One Raft group per region |

**Determinism is a hard requirement and it is easy to violate.** A state machine that does any of these is broken:

```python
# ❌ Every replica computes a DIFFERENT value → divergence
def apply(self, cmd):
    if cmd.type == "SET_EXPIRY":
        self.store[cmd.key] = time.time() + cmd.ttl      # different on each node!
    if cmd.type == "ASSIGN_ID":
        self.store[cmd.key] = uuid.uuid4()               # different on each node!
    if cmd.type == "PICK":
        self.store[cmd.key] = random.choice(cmd.options) # different on each node!
    if cmd.type == "MERGE":
        self.store[cmd.key] = {**a, **b}                 # dict order? (fine in modern
                                                         # Python, not in every language)
```

```python
# ✅ Non-determinism resolved BEFORE the command enters the log
#    The leader decides; the value is part of the command.
def propose_set_expiry(self, key, ttl):
    expiry = self.clock.now() + ttl        # leader computes ONCE
    return Command(type="SET_EXPIRY", key=key, expires_at=expiry)  # replicated as data
```

> **Rule: all non-determinism must be resolved by the proposer and carried in the command.** Clocks, random numbers, UUIDs, iteration order, floating-point in some languages, and anything reading external state. A replica must be able to reproduce the result from the command alone.

This rule is why etcd commands carry absolute expiry timestamps rather than TTLs, and why CockroachDB pushes timestamp assignment into the command.

---

## 2. Why you cannot just ask everyone

The naive replication protocol: write to all nodes, and only succeed if all acknowledge.

```
Client → [Node A, Node B, Node C]: "set x = 5"
Wait for all three.
```

**Consistency:** perfect. Every node has every write.

**Availability:** catastrophic. Compute it:

```
Each node is up 99% of the time.
Availability of "all three must respond" = 0.99³ = 97.03%

You added two nodes for reliability and made availability WORSE
than a single node (99%).
```

Every node you add *reduces* availability under unanimity. This is the exact opposite of what replication is for.

The other naive protocol: write to **any one** node.

```
Client → Node A: "set x = 5"     ✓ fast, available
Client → Node B: "read x"        → returns nothing. Which node is right?
```

Availability is excellent; consistency is gone; and there is no way to resolve a disagreement.

**Quorums are the resolution of this tension**, and the mechanism is not "majority rules" — it is set intersection.

---

## 3. Quorums from first principles

### The intersection property

Choose a read quorum size `R` and a write quorum size `W` over `N` nodes. The only property you actually need is:

> **Every write quorum must intersect every read quorum.**

If they always share at least one node, then any read is guaranteed to touch at least one node that saw the most recent write. If they can be disjoint, two clients can hold contradictory views with no way to detect it.

```
N = 5 nodes: {A, B, C, D, E}

W = 3: write goes to {A, B, C}
R = 3: read goes to  {C, D, E}
                      ↑ C is in both. The read cannot miss the write.

W = 2: write goes to {A, B}
R = 2: read goes to  {D, E}
                      ↑ DISJOINT. The read returns stale data and nobody knows.
```

**The condition, formally:** `W + R > N`

**Proof:** Suppose `W + R > N` but two quorums `Q_w` and `Q_r` are disjoint. Then `|Q_w| + |Q_r| ≤ N` (they fit in the node set without overlap). But `|Q_w| + |Q_r| = W + R > N`. Contradiction. Therefore they must intersect. ∎

### Why consensus uses majorities specifically

Consensus needs something stronger than read/write intersection: it needs **every quorum to intersect every other quorum**, because a quorum that elects a leader must intersect the quorum that accepted the previous leader's writes.

Set `W = R = ⌊N/2⌋ + 1` — a majority. Then:

```
W + R = 2(⌊N/2⌋ + 1) ≥ N + 1 > N   ✓ for all N
```

A majority is the **smallest** quorum size with the property that any two quorums intersect. That is the entire reason majorities are used — not tradition, not voting metaphors. It is the minimal self-intersecting quorum.

### The fault-tolerance table

```
f = maximum simultaneous failures tolerated
q = ⌊N/2⌋ + 1 = quorum size
f = N − q
```

| N | Quorum | Tolerates | Cost per decision | Notes |
|---|--------|-----------|-------------------|-------|
| 1 | 1 | **0** | 0 round trips | Not fault tolerant at all |
| 2 | 2 | **0** | 1 RTT to the other | **Worse than N=1** — needs both, so it is less available |
| **3** | **2** | **1** | 1 RTT to the fastest 1 of 2 | **The standard choice** |
| 4 | 3 | 1 | 1 RTT to the fastest 2 of 3 | Same tolerance as 3, higher cost |
| **5** | **3** | **2** | 1 RTT to the fastest 2 of 4 | Survives a failure **during maintenance** |
| 6 | 4 | 2 | — | Same tolerance as 5, higher cost |
| **7** | **4** | **3** | — | Rarely justified |

**Why odd numbers, stated precisely:** going from `N=3` to `N=4` does not increase `f`, but it does increase the quorum from 2 to 3 — so every decision now needs one more acknowledgement, and the *probability* that a quorum is available goes **down** if node failures are independent. You paid for a node and bought slower writes and worse availability.

**The N=2 trap is worth internalising.** Two nodes have quorum 2, so both must be alive. If either dies, the cluster is unavailable. A two-node "HA cluster" using consensus is strictly less available than one node. This is why every real deployment guide says three.

**Why not 9 or 11?** Every decision requires a round trip to a majority, so latency is governed by the **⌈N/2⌉-th fastest node**. As `N` grows, that node is further out in the latency distribution.

```
N=3:  wait for the 1st of 2 followers   → fast node wins
N=5:  wait for the 2nd of 4 followers   → median-ish
N=7:  wait for the 3rd of 6 followers   → you are now waiting on a slow node
```

Practical guidance: **3 for a single datacenter, 5 across three availability zones or when you need to survive a failure during a rolling upgrade.** Beyond 5, add **learners** (§18) rather than voters.

### The flexible-quorum refinement ⚪

A result from *Flexible Paxos* (2016) that most people do not know: you do not need every quorum to intersect every other quorum. You only need the **leader-election quorum** to intersect the **replication quorum**.

```
N = 5
Election quorum  Q1 = 4
Replication quorum Q2 = 2
Q1 + Q2 = 6 > 5  ✓  still safe

→ Writes commit after only 2 acknowledgements (faster steady state)
→ Elections are rarer and can afford to be slower
```

This is a real optimisation used in some systems for read-heavy or latency-sensitive deployments. Raft as specified uses majorities for both, which is simpler and is what etcd does.

---

## 4. What FLP actually says

The FLP result (Fischer, Lynch, Paterson, 1985) is quoted constantly and usually misquoted.

**The precise statement:**

> In an **asynchronous** message-passing system where **at most one process may crash**, there is **no deterministic** algorithm that solves consensus with **guaranteed termination**.

Each qualifier matters:

| Qualifier | Meaning | Why it matters |
|-----------|---------|----------------|
| **Asynchronous** | No bound on message delay or processing speed | You cannot distinguish "slow" from "dead" |
| **At most one crash** | Even *one* failure is enough to break it | It is not about many failures |
| **Deterministic** | No randomness | **This is the escape hatch** |
| **Guaranteed termination** | Must always finish | Safety is never violated — only liveness |

**What FLP does NOT say:**
- ❌ "Consensus is impossible" — it is achieved constantly
- ❌ "You cannot have both safety and liveness" — you can, almost always
- ❌ "Raft is broken" — Raft is always safe; it can theoretically fail to elect a leader

**The core of the proof, intuitively:** there always exists some *bivalent* configuration — a state where the outcome is still undecided — and an adversarial scheduler can always delay exactly the right message to keep the system in a bivalent state forever. The scheduler never has to actually crash anyone; it only has to be unlucky, forever.

### How every real system escapes FLP

**Randomised timeouts.** Raft's election timeout is random in `[T, 2T]`. The adversarial scheduler in the FLP proof needs to predict which node acts next; randomness makes the bad schedule have probability approaching zero over time.

```
Node A: timeout 187 ms
Node B: timeout 243 ms
Node C: timeout 298 ms
→ A almost certainly becomes candidate alone, and wins immediately.
→ If two collide, both re-randomise. The probability of k consecutive
   collisions falls off exponentially.
```

**Partial synchrony (the formal justification).** Dwork, Lynch and Stockmeyer's model: the system is asynchronous for an unbounded but finite period, after which it becomes synchronous. Consensus is solvable in this model. Real networks behave this way — they are occasionally terrible and eventually fine.

**The practical consequence for you as an architect:**

> **Raft guarantees safety unconditionally. It guarantees liveness only when the network behaves.**
>
> This means: your cluster will **never** produce two conflicting committed values, no matter what the network does. It **may** be unable to elect a leader — and therefore unable to accept writes — while the network is badly partitioned. That is a CP system (Chapter 05 §5.4) and it is a deliberate choice.

When etcd is unavailable, Kubernetes cannot schedule pods. That is the trade, and it is the correct one for a system whose job is to be the authoritative record.

---

## 5. Raft: the complete specification

Raft was designed by Diego Ongaro and John Ousterhout explicitly for **understandability**, after years of Paxos being correct and unimplementable. The design technique was decomposition: split consensus into independent sub-problems, and reduce the state space by adding constraints (for example: a leader never overwrites its own log).

### 5.1 Server state

Every server holds exactly this. Nothing else is needed.

```
PERSISTENT (must survive a crash — fsync before responding to any RPC)
┌──────────────┬──────────────────────────────────────────────────────┐
│ currentTerm  │ latest term seen, initialised to 0, increases only    │
│ votedFor     │ candidateId voted for in currentTerm, or null         │
│ log[]        │ entries: { term, index, command }; first index is 1   │
└──────────────┴──────────────────────────────────────────────────────┘

VOLATILE (all servers)
┌──────────────┬──────────────────────────────────────────────────────┐
│ commitIndex  │ highest index known to be committed (init 0)          │
│ lastApplied  │ highest index applied to the state machine (init 0)   │
└──────────────┴──────────────────────────────────────────────────────┘

VOLATILE (leaders only, reinitialised after every election)
┌──────────────┬──────────────────────────────────────────────────────┐
│ nextIndex[]  │ per follower: next index to send (init: lastLogIndex+1)│
│ matchIndex[] │ per follower: highest index known replicated (init 0) │
└──────────────┴──────────────────────────────────────────────────────┘
```

**`nextIndex` vs `matchIndex` is a distinction people get wrong.**
- `nextIndex` is **optimistic** — the leader's guess about where to start sending. It starts high and is decremented on rejection.
- `matchIndex` is **conservative and proven** — set only from a successful response. It is the only value safe to use for commit decisions.

Using `nextIndex` for the commit calculation is a real bug that produces data loss.

### 5.2 Terms — a logical clock

```
    term 1        term 2      term 3         term 4
 ┌───────────┬────────────┬──────────┬──────────────────┐
 │ election  │  election  │ election │    election      │
 │ + normal  │  + normal  │ FAILED   │    + normal      │
 │ operation │  operation │(no leader)│   operation     │
 └───────────┴────────────┴──────────┴──────────────────┘
```

Properties of terms:
- **Monotonically increasing** on every server
- **At most one leader per term** (enforced by "one vote per server per term")
- A term may have **zero** leaders (a failed election)
- Terms are carried in **every RPC**, in both directions

**The universal rule** — this single rule is responsible for most of Raft's robustness:

```
If any RPC request OR response contains term T > currentTerm:
    currentTerm = T
    votedFor = null
    convert to FOLLOWER
```

This means a stale leader **cannot persist**. The moment it exchanges any message with a server that has moved on, it learns it is obsolete and demotes itself. No separate detection mechanism is needed.

And the mirror rule:

```
If an RPC request contains term T < currentTerm:
    reply with currentTerm, and reject
```

The stale sender learns its term is old from the reply, and demotes.

### 5.3 RequestVote RPC

```
REQUEST                          RESPONSE
├── term          candidate's    ├── term         voter's currentTerm
├── candidateId                  └── voteGranted  true if vote given
├── lastLogIndex  candidate's last entry
└── lastLogTerm   term of that entry
```

**Receiver logic, in order:**

```python
def handle_request_vote(self, req):
    # Rule 1: stale term → reject, and tell them the real term
    if req.term < self.currentTerm:
        return VoteResponse(term=self.currentTerm, granted=False)

    # Universal rule: newer term → step down first
    if req.term > self.currentTerm:
        self.currentTerm = req.term
        self.votedFor = None
        self.become_follower()

    # Rule 2: one vote per term, and only for a sufficiently up-to-date log
    already_voted_for_someone_else = (
        self.votedFor is not None and self.votedFor != req.candidateId
    )
    if already_voted_for_someone_else:
        return VoteResponse(term=self.currentTerm, granted=False)

    if not self._candidate_log_is_up_to_date(req.lastLogTerm, req.lastLogIndex):
        return VoteResponse(term=self.currentTerm, granted=False)   # see §9

    self.votedFor = req.candidateId
    self.persist()                       # ⭐ fsync BEFORE replying — see §12
    self.reset_election_timer()
    return VoteResponse(term=self.currentTerm, granted=True)
```

### 5.4 AppendEntries RPC

Used for both log replication and heartbeats (a heartbeat is simply `entries=[]`).

```
REQUEST                             RESPONSE
├── term          leader's          ├── term      follower's currentTerm
├── leaderId                        └── success   true if the consistency
├── prevLogIndex  index BEFORE      │             check passed
│                 the new entries   │
├── prevLogTerm   term of that      │  (production systems add hints here,
│                 entry             │   see §8)
├── entries[]     may be empty
└── leaderCommit  leader's commitIndex
```

**Receiver logic, in order — every step matters:**

```python
def handle_append_entries(self, req):
    if req.term < self.currentTerm:                      # 1. stale leader
        return AppendResponse(term=self.currentTerm, success=False)

    if req.term > self.currentTerm:
        self.currentTerm = req.term
        self.votedFor = None
    self.become_follower()                               # a valid leader exists
    self.reset_election_timer()                          # ⭐ suppress our own election

    # 2. CONSISTENCY CHECK — the heart of the protocol
    if req.prevLogIndex > 0:
        if self.last_log_index() < req.prevLogIndex:
            return AppendResponse(term=self.currentTerm, success=False)  # gap
        if self.log[req.prevLogIndex].term != req.prevLogTerm:
            return AppendResponse(term=self.currentTerm, success=False)  # mismatch

    # 3 + 4. Append, truncating ONLY on a genuine conflict
    for i, entry in enumerate(req.entries):
        idx = req.prevLogIndex + 1 + i
        if idx <= self.last_log_index():
            if self.log[idx].term != entry.term:
                self.log = self.log[:idx]        # ⭐ delete conflict AND everything after
                self.log.append(entry)
            # else: identical entry already present — idempotent, skip
        else:
            self.log.append(entry)

    self.persist()                                       # ⭐ fsync before replying

    # 5. Advance commitIndex
    if req.leaderCommit > self.commitIndex:
        self.commitIndex = min(req.leaderCommit, self.last_log_index())
        self.apply_committed_entries()

    return AppendResponse(term=self.currentTerm, success=True)
```

**Step 3 contains a subtle trap.** The naive implementation is:

```python
# ❌ WRONG — truncates on every AppendEntries
self.log = self.log[:req.prevLogIndex + 1]
self.log.extend(req.entries)
```

This looks equivalent and is not. AppendEntries RPCs can be **delayed and reordered**. A stale RPC carrying older entries would truncate away newer entries that the follower legitimately received — and if those entries were already committed elsewhere, you have just violated safety. **Truncate only where the terms actually conflict.**

### 5.5 The Log Matching Property

This is the invariant the consistency check maintains, and it is what makes Raft simple.

> **If two logs contain an entry with the same index and the same term, then:**
> **(a) the entries store the same command, and**
> **(b) the logs are identical in all preceding entries.**

**Why (a) holds:** a leader creates at most one entry per index per term, and never changes it.

**Why (b) holds — by induction:** AppendEntries only succeeds if the follower already has a matching entry at `prevLogIndex`. So agreement at index `i` implies agreement at `i−1`, which implies agreement at `i−2`, all the way down.

**The consequence is powerful:** a single `(index, term)` pair acts as a checksum for the entire prefix. The leader does not need to compare logs entry by entry; it only needs to find one matching point.

### 5.6 The complete server rules

```
ALL SERVERS
  • if commitIndex > lastApplied:
        lastApplied++;  apply log[lastApplied] to the state machine
  • if any RPC request/response has term T > currentTerm:
        currentTerm = T; votedFor = null; become FOLLOWER

FOLLOWER
  • respond to RPCs from candidates and leaders
  • if election timeout elapses with no AppendEntries from the current leader
    and no vote granted to a candidate → become CANDIDATE

CANDIDATE
  • on becoming candidate: currentTerm++; vote for self; reset timer;
    send RequestVote to all others
  • majority of votes → become LEADER
  • AppendEntries received from a node with term ≥ currentTerm → become FOLLOWER
  • election timeout elapses → start a new election (new term, new random timeout)

LEADER
  • on election: send empty AppendEntries (heartbeat) to everyone immediately,
    and repeat during idle periods (typically every 50 ms)
  • client command → append to local log; respond once APPLIED
  • for each follower where lastLogIndex ≥ nextIndex[f]:
        send AppendEntries starting at nextIndex[f]
        success → nextIndex[f] = lastSent+1;  matchIndex[f] = lastSent
        failure → decrement nextIndex[f] (or use the hint) and retry
  • ⭐ if ∃ N such that
        N > commitIndex
        AND a majority of matchIndex[i] ≥ N
        AND log[N].term == currentTerm          ← THE CRITICAL CLAUSE (§10)
    then commitIndex = N
```

### 5.7 Timing requirements

Raft's liveness depends on one inequality:

```
broadcastTime  ≪  electionTimeout  ≪  MTBF

broadcastTime   = time for a round trip to a majority (0.5–20 ms typically)
electionTimeout = random in [T, 2T], typically T = 150–300 ms
MTBF            = mean time between failures of a single server (months)
```

**Why each `≪` matters:**

- `broadcastTime ≪ electionTimeout` — otherwise followers time out and start elections while the leader is perfectly healthy, and the cluster thrashes between elections instead of doing work.
- `electionTimeout ≪ MTBF` — otherwise the cluster spends a meaningful fraction of its life leaderless.

**Practical values:**

| Deployment | broadcastTime | electionTimeout | Heartbeat |
|-----------|---------------|-----------------|-----------|
| Same rack | 0.5–2 ms | 150–300 ms | 50 ms |
| Same region, 3 AZs | 1–5 ms | 500–1000 ms | 100 ms |
| Cross-region | 30–100 ms | **2500–5000 ms** | 500 ms |

**The common misconfiguration:** running the single-datacenter defaults across regions. `broadcastTime` becomes 80 ms, the 1000 ms election timeout is only 12× larger, and one GC pause or network hiccup triggers an election. The cluster spends its life re-electing. etcd's `--heartbeat-interval` and `--election-timeout` exist precisely for this, and the documented rule is `election-timeout ≥ 10 × heartbeat-interval`.

---

## 6. Traced scenario 1 — a normal election

Five servers, all starting fresh. Timeouts fire in the order S2, S5, S1, S3, S4.

```
t=0     ALL: FOLLOWER, currentTerm=0, votedFor=null, log=[]
        Random election timeouts:  S1:271  S2:163  S3:288  S4:299  S5:210 (ms)

t=163   S2 times out.
        S2: currentTerm 0→1, votedFor=S2, state=CANDIDATE, votes={S2}
        S2 → all: RequestVote{term=1, candidateId=S2, lastLogIndex=0, lastLogTerm=0}

t=165   S1 receives RequestVote.
          req.term(1) > currentTerm(0) → currentTerm=1, votedFor=null, FOLLOWER
          votedFor is null ✓
          candidate log (0,0) vs our log (0,0) → at least as up to date ✓
          → votedFor=S1's vote for S2. PERSIST. Reply granted=true.
          → S1 also RESETS its election timer (it granted a vote)

        S3, S4, S5 do the same.

t=167   S2 receives grants from S1 and S3.
        votes = {S2, S1, S3} = 3 ≥ quorum(3)
        → S2 becomes LEADER for term 1
        → nextIndex[] = {S1:1, S3:1, S4:1, S5:1}   (lastLogIndex 0 + 1)
        → matchIndex[] = {S1:0, S3:0, S4:0, S5:0}

t=167   S2 → all: AppendEntries{term=1, prevLogIndex=0, prevLogTerm=0,
                                entries=[], leaderCommit=0}     ← heartbeat

t=169   S4, S5 receive the heartbeat.
        Their election timers (299 ms, 210 ms) RESET. They never time out.

t=217   S5's original timeout would have fired — but it was reset at t=169.
        Nothing happens. The cluster is stable.
```

**The two mechanisms that made this converge in 4 ms:**
1. **Random timeouts** meant S2 was alone as a candidate. No contention.
2. **Granting a vote resets the timer.** S1 and S3 will not launch competing elections after helping S2. Without this rule, a voter could time out and become a candidate milliseconds after voting, creating unnecessary churn.

---

## 7. Traced scenario 2 — a split vote

The unlucky case: two candidates time out within the network round-trip time.

```
t=0      S1 timeout 200 ms; S2 timeout 203 ms.  Broadcast time ≈ 5 ms.

t=200    S1: term 0→1, votedFor=S1, CANDIDATE. Sends RequestVote(term=1).
t=203    S2: term 0→1, votedFor=S2, CANDIDATE. Sends RequestVote(term=1).
         ⚠ S2 had not yet received S1's request.

t=205    S3 receives S1's request first  → votes S1. votedFor=S1.
         S4 receives S2's request first  → votes S2. votedFor=S2.
         S5 receives S1's request first  → votes S1. votedFor=S1.

t=206    S3 receives S2's request. term==currentTerm(1), votedFor=S1 ≠ S2 → REJECT.
         S4 receives S1's request. term==currentTerm(1), votedFor=S2 ≠ S1 → REJECT.

t=208    S1 has votes {S1, S3, S5} = 3 ≥ 3 → S1 WINS.
```

In this run S1 won because S5 happened to hear from S1 first. Now consider the genuinely split case:

```
t=208    S1 has {S1, S3} = 2 < 3   ✗ no majority
         S2 has {S2, S4} = 2 < 3   ✗ no majority
         S5 is partitioned and voted for nobody.

         → NEITHER wins. Term 1 has NO leader. This is legal and expected.

t=208    Both candidates re-randomise their timeouts:
         S1: 176 ms   S2: 289 ms

t=384    S1 times out first.  term 1→2, votedFor=S1, CANDIDATE.
         Sends RequestVote(term=2).

t=386    S3: req.term(2) > currentTerm(1) → currentTerm=2, votedFor=NULL ⭐
         The term bump CLEARS the previous vote. S3 can vote again — in term 2.
         → grants.
         S4, S5 likewise.

t=389    S1 has {S1, S3, S4, S5} → LEADER for term 2.
```

**Two things to take from this:**

1. **A term with no leader is normal.** Terms are not "reigns"; they are attempts. Seeing gaps in term numbers in etcd logs is not a bug.

2. **The `votedFor = null` on term increment is what breaks the deadlock.** Votes are scoped to a term. Without that reset, a split vote would be permanent.

**The probability of repeated splits collapses fast.** With timeouts uniform in `[150, 300]` ms and a 5 ms broadcast time, the chance two specific nodes collide is roughly `5/150 ≈ 3%`. Two consecutive splits: ~0.1%. Three: ~0.003%. In practice elections converge in one or two rounds, which is why you should not "tune" this by narrowing the randomisation range — narrowing it makes splits *more* likely.

---

## 8. Traced scenario 3 — log divergence and repair

This is the scenario that shows why the consistency check is designed the way it is.

**Starting state.** S1 has just been elected leader for term 7. The followers' logs have diverged from earlier failed leaders.

```
index:      1    2    3    4    5    6    7    8    9   10   11   12
         ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
S1 (L):  │ 1  │ 1  │ 1  │ 4  │ 4  │ 5  │ 5  │ 6  │ 6  │ 6  │    │    │   term 7 leader
         └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
S2:      │ 1  │ 1  │ 1  │ 4  │ 4  │ 5  │ 5  │ 6  │ 6  │    │    │    │   missing 1 entry
S3:      │ 1  │ 1  │ 1  │ 4  │    │    │    │    │    │    │    │    │   far behind
S4:      │ 1  │ 1  │ 1  │ 4  │ 4  │ 5  │ 5  │ 6  │ 6  │ 6  │ 6  │    │   EXTRA entry
S5:      │ 1  │ 1  │ 1  │ 2  │ 2  │ 2  │ 3  │ 3  │ 3  │ 3  │ 3  │    │   DIVERGED at 4
                            ↑
                     divergence point

(numbers in cells are the TERM of the entry at that index)
```

S4 has an extra uncommitted entry from a previous leader. S5 diverged all the way back at index 4 — it followed a different leader in terms 2 and 3.

**S1 initialises on election:**
```
nextIndex[]  = {S2: 11, S3: 11, S4: 11, S5: 11}    (its own lastLogIndex 10, + 1)
matchIndex[] = {S2: 0,  S3: 0,  S4: 0,  S5: 0}
```

### Repairing S2 (one entry behind)

```
Attempt 1:  AppendEntries{prevLogIndex=10, prevLogTerm=6, entries=[]}
            S2: last_log_index() = 9 < 10  → GAP → success=false

S1: nextIndex[S2] = 10

Attempt 2:  AppendEntries{prevLogIndex=9, prevLogTerm=6, entries=[log[10]]}
            S2: log[9].term == 6 ✓ match
                append log[10]
            → success=true

S1: matchIndex[S2] = 10, nextIndex[S2] = 11.  S2 repaired in 2 round trips.
```

### Repairing S5 (diverged at index 4)

This is where naive decrement-by-one becomes painful.

```
Attempt 1:  prevLogIndex=10, prevLogTerm=6.  S5.log[10].term = 3 ≠ 6  → false
Attempt 2:  prevLogIndex=9,  prevLogTerm=6.  S5.log[9].term  = 3 ≠ 6  → false
Attempt 3:  prevLogIndex=8,  prevLogTerm=6.  S5.log[8].term  = 3 ≠ 6  → false
Attempt 4:  prevLogIndex=7,  prevLogTerm=5.  S5.log[7].term  = 3 ≠ 5  → false
Attempt 5:  prevLogIndex=6,  prevLogTerm=5.  S5.log[6].term  = 2 ≠ 5  → false
Attempt 6:  prevLogIndex=5,  prevLogTerm=4.  S5.log[5].term  = 2 ≠ 4  → false
Attempt 7:  prevLogIndex=4,  prevLogTerm=4.  S5.log[4].term  = 2 ≠ 4  → false
Attempt 8:  prevLogIndex=3,  prevLogTerm=1.  S5.log[3].term  = 1 ✓ MATCH

            entries = log[4..10] = terms [4,4,5,5,6,6,6]
            S5: idx 4 — existing term 2 ≠ new term 4 → TRUNCATE log[4:] and append
            → S5 log becomes identical to S1's.

8 round trips. At 50 ms cross-region RTT that is 400 ms just to repair one follower.
```

**The production optimisation.** The paper notes this can be batched; every real implementation returns a hint. etcd's `raft` library returns:

```
AppendResponse {
    success:       false,
    conflictIndex: <first index of the follower's term at prevLogIndex>,
    conflictTerm:  <the term the follower actually has at prevLogIndex>
}
```

The leader then does:

```python
def handle_append_rejection(self, follower, resp):
    if resp.conflictTerm is not None:
        # Does the leader have ANY entry with that term?
        last_index_of_term = self.last_index_with_term(resp.conflictTerm)
        if last_index_of_term is not None:
            # Skip straight past that whole term
            self.nextIndex[follower] = last_index_of_term + 1
        else:
            # Leader never had that term — skip the follower's entire run of it
            self.nextIndex[follower] = resp.conflictIndex
    else:
        self.nextIndex[follower] = resp.conflictIndex   # follower's log was short
```

Applied to S5: the first rejection reports `conflictTerm=3, conflictIndex=7`. S1 has no term-3 entries, so it jumps `nextIndex` to 7 immediately. The next rejection reports `conflictTerm=2, conflictIndex=4` → jump to 4. The third succeeds at `prevLogIndex=3`.

**8 round trips reduced to 3.** This matters enormously after a long partition heals, where a follower may be thousands of entries behind. Without the hint, repair is O(divergence); with it, it is O(number of distinct terms in the divergent region) — usually a handful.

### What happened to S4's extra entry

```
Attempt 1:  prevLogIndex=10, prevLogTerm=6.  S4.log[10].term = 6 ✓ MATCH
            entries = []   (leader has nothing past index 10)
            → success=true

S4 STILL HAS its entry at index 11.
```

The extra entry is not removed yet. It sits there, uncommitted and harmless, until the leader sends a real entry at index 11:

```
S1 appends a client command at index 11 (term 7).
AppendEntries{prevLogIndex=10, prevLogTerm=6, entries=[{index:11, term:7, ...}]}

S4: idx 11 exists with term 6 ≠ new term 7 → TRUNCATE log[11:], append.
→ the orphan entry is finally discarded.
```

> **This is why a leader must never count "entries that exist on a majority" as committed without checking the term.** S4's index-11 entry existed. It was never committed. It was destroyed. Section 10 is about exactly this.

---

## 9. The election restriction, and why it is necessary

Raft's simplicity relies on one strong rule:

> **A leader never overwrites or deletes entries in its own log. It only appends.**

Paxos-family protocols allow a new leader to *discover* and *adopt* entries from others, which is powerful and is a large part of why they are hard to implement. Raft forbids it — and therefore must guarantee that **a node with a missing committed entry can never become leader.**

That guarantee is enforced at vote time.

### The up-to-date comparison

```python
def _candidate_log_is_up_to_date(self, cand_last_term, cand_last_index):
    my_last_term  = self.log[-1].term  if self.log else 0
    my_last_index = len(self.log)

    if cand_last_term != my_last_term:
        return cand_last_term > my_last_term     # ⭐ TERM dominates
    return cand_last_index >= my_last_index      # same term → longer or equal wins
```

**Term is compared first, and this is not arbitrary.** A longer log is *not* necessarily more current:

```
S_a log:  [1, 1, 1, 2, 2, 2, 2, 2]          8 entries, last term 2
S_b log:  [1, 1, 1, 5]                      4 entries, last term 5

S_b is MORE up to date despite being half the length.

Why: S_b's entry from term 5 means a leader existed in term 5, which means a
majority had already moved past term 2. S_a's five extra term-2 entries are
uncommitted leftovers from a leader that was superseded. They will be truncated.
```

If length were compared first, S_a could win an election and would then — because leaders never delete their own entries — force those stale term-2 entries onto the cluster, overwriting committed term-5 entries. That is a direct safety violation.

### Why this guarantees the Leader Completeness Property

> **Leader Completeness:** if an entry is committed in term T, it is present in the log of every leader of every term > T.

**The argument:**

1. An entry committed in term T is, by definition, stored on a majority — call that set `M`.
2. Any future leader must win an election, which requires votes from a majority — call that set `V`.
3. `M` and `V` are both majorities, so **they intersect** (§3). Some server `s` is in both.
4. `s` has the committed entry (it is in `M`).
5. `s` granted a vote to the new leader (it is in `V`), which means the candidate's log was **at least as up to date as `s`'s**.
6. Since `s` has an entry from term T, the candidate must have either an entry with a term ≥ T at that position, or a longer log at term T.
7. By the Log Matching Property (§5.5), the candidate therefore also has the committed entry. ∎

**Notice where the work is done: step 3.** The entire safety argument rests on quorum intersection. Every other rule exists to make that intersection meaningful.

---

## 10. The commit rule that looks wrong ⭐

Here is the rule from §5.6 again, isolated:

```
if ∃ N such that
     N > commitIndex
     AND a majority of matchIndex[i] ≥ N
     AND log[N].term == currentTerm     ← this clause
then commitIndex = N
```

The third clause says: **a leader may not commit an entry from a previous term, even when that entry is replicated on a majority of servers.**

This looks unnecessary. The entry is durably stored on a majority. Surely it is safe?

**It is not.** This is Figure 8 of the Raft paper, and it is the single subtlety that most from-scratch implementations get wrong. The bug does not show up in testing — it requires a specific sequence of two crashes and two elections.

Section 11 traces the exact execution.

---

## 11. Traced scenario 4 — the Figure 8 execution

Five servers: S1…S5. Watch the entry at **index 2, term 2**. It will be replicated on a majority, and then destroyed.

### (a) — Term 2: S1 is leader and partially replicates

```
             idx:  1    2
         ┌─────────────────┐
S1 (L,t2)│  1  │  2  │      ← appends entry at index 2, term 2
S2       │  1  │  2  │      ← replicated here
S3       │  1  │     │
S4       │  1  │     │
S5       │  1  │     │
         └─────────────────┘

Entry (2, term 2) is on 2 of 5 servers. matchIndex majority not reached.
NOT committed. S1 has not responded to the client.
```

### (b) — S1 crashes; S5 wins term 3

```
S1 crashes.

S5 becomes candidate for term 3. Its log is [1] — last entry term 1, index 1.
Voters S3 and S4 have logs [1] — last entry term 1, index 1.
Up-to-date check: cand (1,1) vs voter (1,1) → equal → VOTE GRANTED. ✓ legal
S5 votes for itself.

S5 has {S5, S3, S4} = 3 ≥ quorum. S5 is LEADER for term 3.

S5 accepts a client command at index 2 — with term 3.

             idx:  1    2
S1 (down)│  1  │  2  │
S2       │  1  │  2  │
S3       │  1  │     │
S4       │  1  │     │
S5 (L,t3)│  1  │  3  │      ← DIFFERENT entry at the SAME index
```

**Two different entries now exist at index 2.** This is legal — neither is committed.

### (c) — S5 crashes; S1 returns and wins term 4

```
S5 crashes before replicating its term-3 entry anywhere.
S1 restarts (its persistent log survived: [1, 2]).

S1 becomes candidate for term 4. Its last entry is (index 2, term 2).
Voters S2 (last entry (2,2)), S3 ((1,1)), S4 ((1,1)):
   S2: cand (2,2) vs mine (2,2) → equal → grant ✓
   S3: cand term 2 > my term 1 → grant ✓
   S4: same → grant ✓

S1 is LEADER for term 4.

S1 now replicates its existing log. The term-2 entry at index 2 spreads:

             idx:  1    2
S1 (L,t4)│  1  │  2  │
S2       │  1  │  2  │
S3       │  1  │  2  │      ← replicated
S4       │  1  │  2  │      ← replicated
S5 (down)│  1  │  3  │

⭐ Entry (index 2, term 2) is now on FOUR of five servers.
   matchIndex = {S2:2, S3:2, S4:2} → a clear majority has it.

   A NAIVE implementation commits it here.  THIS IS THE BUG.
```

### (d) — the disaster, if it had been committed

```
S1 crashes again, before replicating anything from term 4.
S5 restarts.

S5 becomes candidate for term 5. Its last entry is (index 2, term 3).
Voters:
   S2: cand term 3 > my term 2 → GRANT ✓
   S3: cand term 3 > my term 2 → GRANT ✓
   S4: cand term 3 > my term 2 → GRANT ✓

S5 is LEADER for term 5 — entirely legally. Its log is more up to date by term.

S5 replicates its own log. Leaders never delete their own entries, so:

             idx:  1    2
S1 (down)│  1  │  2  │
S2       │  1  │  3  │      ← OVERWRITTEN
S3       │  1  │  3  │      ← OVERWRITTEN
S4       │  1  │  3  │      ← OVERWRITTEN
S5 (L,t5)│  1  │  3  │

☠️ The term-2 entry has been erased from the cluster.
   If it had been reported committed in step (c), a client was told
   "your write succeeded" and the write no longer exists.
   That is a violated durability guarantee — the worst class of bug.
```

### (e) — what the rule does instead

```
Back at step (c). S1 is leader for term 4 with the term-2 entry on a majority.

The commit rule REFUSES to commit it, because log[2].term (2) ≠ currentTerm (4).

Instead, S1 appends a new entry at index 3 with term 4 — in practice a no-op
entry that every Raft leader appends immediately on election, precisely for this.

             idx:  1    2    3
S1 (L,t4)│  1  │  2  │  4  │
S2       │  1  │  2  │  4  │
S3       │  1  │  2  │  4  │
S4       │  1  │     │     │
S5 (down)│  1  │  3  │     │

Now: log[3].term == currentTerm (4) ✓ AND majority has index 3 ✓
→ commitIndex = 3

⭐ Committing index 3 commits index 2 INDIRECTLY (the log is a prefix-consistent
   sequence — committing N commits everything ≤ N).

And now S5 can never win again:
   S5's last entry is (index 2, term 3).
   S2, S3 have last entry (index 3, term 4).
   Up-to-date check: cand term 3 < voter term 4 → REJECT.
   S5 can only get its own vote + S1's… and S1 has term 4 too. It cannot win.

The term-2 entry is now genuinely safe.
```

### Why the no-op entry matters operationally

Every Raft leader appends a no-op entry to its log immediately upon election. It is not ceremony:

1. It makes the commit rule fire, retroactively committing everything from previous terms.
2. Until it commits, the new leader **does not know its own commitIndex** — it cannot safely serve reads or tell clients that earlier writes succeeded.

**The observable consequence:** there is a brief window after every election where the cluster has a leader but cannot yet confirm the commit status of pre-election entries. etcd exposes this: a `Put` issued just before a leader change may return an error, and the client must retry idempotently. This is not a bug; it is Figure 8 made visible.

> **The general lesson for architects, beyond Raft:** *"it is stored on a majority"* is not the same as *"it is committed."* Commitment is a property of the protocol's decision, not of where bytes happen to be sitting. Any system claiming durability must define exactly which event constitutes commitment — and any system that conflates "replicated" with "committed" has this bug.

---

## 12. Why persistence must be fsync'd

The specification says `currentTerm`, `votedFor` and `log[]` are persistent and must be written to stable storage **before responding to any RPC**. Not "eventually". Not "buffered". **Before the reply leaves.**

This is expensive — an `fsync` is 0.1 ms on a good NVMe with a battery-backed cache, and 5–10 ms on a spinning disk or a network volume. It is on the critical path of every single write. Implementers are constantly tempted to relax it.

Here is what each relaxation costs.

### Losing `votedFor` → two leaders in one term

Traced in §13 below. This is the worst one.

### Losing `currentTerm` → accepting a stale leader

```
S3 is at currentTerm=9.  Crashes. On restart, currentTerm=0 (lost).
A zombie leader from term 5 sends AppendEntries{term=5}.
S3: req.term(5) > currentTerm(0) → accepts it as leader.
→ S3 now follows an obsolete leader and may truncate valid entries.
```

### Losing log entries → acknowledged writes vanish

```
S2 ACKs an entry (its fsync was buffered, not flushed).
The leader counts S2 towards the majority, commits, tells the client "OK".
S2 loses power. The entry is gone from S2's disk.
If the leader and the one other acknowledging node also fail,
the committed entry exists nowhere. The client was lied to.
```

### The cloud-storage trap

This is a live production concern, not a theoretical one:

| Storage | `fsync` guarantee |
|---------|------------------|
| Local NVMe with power-loss protection | Genuinely durable, ~0.05–0.2 ms |
| Local SSD without PLP | `fsync` may return before the drive's volatile cache is flushed |
| EBS gp3 / Premium SSD | Durable, but 0.5–2 ms and subject to IOPS limits |
| **Network filesystems (NFS/EFS)** | `fsync` semantics vary; **do not run etcd on these** |
| **Containers with a writable layer on overlayfs** | Extra latency; ensure a real volume |

etcd's documented requirement is a `wal_fsync_duration_seconds` p99 **under 10 ms**. When it exceeds that, heartbeats are delayed, elections trigger, and the cluster thrashes. **"Our Kubernetes cluster is randomly unstable" is very often "etcd is on slow disks."** It is one of the first things to check.

```promql
# The single most important etcd metric
histogram_quantile(0.99,
  rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])
) > 0.01
```

---

## 13. Traced scenario 5 — the lost vote

The precise failure caused by not persisting `votedFor`. This produces **two leaders in the same term**, which Raft's entire design is built to make impossible.

```
Five servers. Term 4 election in progress.
S1 and S2 are both candidates for term 4 (a split-vote situation).

t=0    S3 receives RequestVote from S1.
       votedFor=S1, currentTerm=4.
       ⚠ Implementation writes to a buffer; does NOT fsync.
       Replies granted=true.

t=1    S1 has {S1, S3} = 2.  Needs 3.  Waiting.

t=2    ☠ S3 CRASHES. The buffered votedFor is lost.

t=8    S3 restarts. Reads persistent state from disk:
       currentTerm=4 (this happened to be flushed earlier)
       votedFor=NULL   ← THE LOST WRITE

t=9    S3 receives RequestVote from S2 (also term 4).
       req.term(4) == currentTerm(4) → no step-down needed
       votedFor is NULL → "I have not voted in term 4"
       up-to-date check passes
       → GRANTS THE VOTE TO S2.

t=10   S2 has {S2, S4, S3} = 3 ≥ quorum → S2 becomes LEADER of term 4.
t=11   S1 receives a delayed grant from S5: {S1, S3, S5} = 3 → S1 becomes LEADER of term 4.

☠☠ TWO LEADERS IN TERM 4.
```

**What happens next is data corruption, not merely confusion:**

```
S1 (leader, t4) appends entry X at index 7, replicates to S3, S5 → majority → COMMITS X.
S2 (leader, t4) appends entry Y at index 7, replicates to S4, S3 → majority → COMMITS Y.

Two different entries, both "committed", at the same index, in the same term.
The Log Matching Property is violated at its root.
State machines diverge permanently. There is no recovery procedure —
the cluster has no way to determine which history is correct.
```

**Why the "one vote per term" rule is stated so absolutely.** The entire safety argument in §9 depends on quorum intersection identifying a server that *remembers* what it did. A server that forgets its vote breaks the intersection argument, because the intersecting node can testify to two contradictory things.

> **This is why `fsync` is non-negotiable and why you should not write your own consensus implementation.** The bug requires a crash in a specific 1 ms window during a split vote. You will not find it in testing. You will find it in production, once, and it will be unrecoverable.

---

## 14. A working implementation

A single-file Raft node with the complete core protocol. This is not production code (no snapshots, no membership changes, simplified transport), but every rule discussed above is present and correctly ordered.

```python
"""
Raft core. Implements: leader election, log replication, the consistency check,
the election restriction, and the Figure 8 commit rule.

Deliberately omitted (see §19, §20): snapshots, membership changes, PreVote,
leases, batching. Those are layered on top of this core.
"""
from __future__ import annotations
import random, time, threading
from dataclasses import dataclass, field
from enum import Enum


class Role(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


@dataclass(frozen=True)
class LogEntry:
    term: int
    index: int
    command: bytes | None      # None == the no-op entry appended on election


@dataclass
class AppendEntriesReq:
    term: int
    leader_id: str
    prev_log_index: int
    prev_log_term: int
    entries: list[LogEntry]
    leader_commit: int


@dataclass
class AppendEntriesResp:
    term: int
    success: bool
    conflict_index: int | None = None   # §8 fast-backtrack hint
    conflict_term: int | None = None


@dataclass
class RequestVoteReq:
    term: int
    candidate_id: str
    last_log_index: int
    last_log_term: int


@dataclass
class RequestVoteResp:
    term: int
    vote_granted: bool


class RaftNode:
    # §5.7 — tune these together; election >> broadcast
    HEARTBEAT_MS = 50
    ELECTION_MIN_MS = 150
    ELECTION_MAX_MS = 300

    def __init__(self, node_id: str, peers: list[str], storage, transport, state_machine):
        self.id = node_id
        self.peers = peers                       # does NOT include self
        self.storage = storage                   # must fsync (§12)
        self.transport = transport
        self.sm = state_machine

        # --- PERSISTENT (§5.1) ---
        persisted = storage.load()
        self.current_term: int = persisted.get("current_term", 0)
        self.voted_for: str | None = persisted.get("voted_for")
        self.log: list[LogEntry] = persisted.get("log", [])

        # --- VOLATILE, all servers ---
        self.commit_index: int = 0
        self.last_applied: int = 0

        # --- VOLATILE, leader only ---
        self.next_index: dict[str, int] = {}
        self.match_index: dict[str, int] = {}

        self.role = Role.FOLLOWER
        self.leader_id: str | None = None
        self.lock = threading.RLock()
        self._reset_election_timer()

    # ─────────────────────────── helpers ───────────────────────────

    @property
    def quorum(self) -> int:
        return (len(self.peers) + 1) // 2 + 1

    def last_log_index(self) -> int:
        return self.log[-1].index if self.log else 0

    def last_log_term(self) -> int:
        return self.log[-1].term if self.log else 0

    def entry_at(self, index: int) -> LogEntry | None:
        # log[0] is index 1 in this simplified model (no snapshot offset)
        if index <= 0 or index > len(self.log):
            return None
        return self.log[index - 1]

    def _persist(self) -> None:
        """§12 — MUST fsync before any RPC reply that depends on this state."""
        self.storage.save_and_fsync(
            current_term=self.current_term,
            voted_for=self.voted_for,
            log=self.log,
        )

    def _reset_election_timer(self) -> None:
        jitter = random.uniform(self.ELECTION_MIN_MS, self.ELECTION_MAX_MS)
        self.election_deadline = time.monotonic() + jitter / 1000.0

    def _step_down(self, term: int) -> None:
        """§5.2 universal rule: a higher term always demotes us."""
        self.current_term = term
        self.voted_for = None
        self.role = Role.FOLLOWER
        self.leader_id = None
        self._persist()

    # ─────────────────────── RPC: RequestVote ───────────────────────

    def handle_request_vote(self, req: RequestVoteReq) -> RequestVoteResp:
        with self.lock:
            if req.term < self.current_term:                       # rule 1
                return RequestVoteResp(self.current_term, False)

            if req.term > self.current_term:
                self._step_down(req.term)

            already_committed_vote = (
                self.voted_for is not None and self.voted_for != req.candidate_id
            )
            if already_committed_vote:
                return RequestVoteResp(self.current_term, False)

            if not self._log_is_up_to_date(req.last_log_term, req.last_log_index):
                return RequestVoteResp(self.current_term, False)   # §9

            self.voted_for = req.candidate_id
            self._persist()                       # ⭐ fsync BEFORE replying (§13)
            self._reset_election_timer()          # granting a vote suppresses our own
            return RequestVoteResp(self.current_term, True)

    def _log_is_up_to_date(self, cand_term: int, cand_index: int) -> bool:
        """§9 — TERM dominates; length only breaks ties within a term."""
        my_term, my_index = self.last_log_term(), self.last_log_index()
        if cand_term != my_term:
            return cand_term > my_term
        return cand_index >= my_index

    # ────────────────────── RPC: AppendEntries ──────────────────────

    def handle_append_entries(self, req: AppendEntriesReq) -> AppendEntriesResp:
        with self.lock:
            if req.term < self.current_term:                       # rule 1
                return AppendEntriesResp(self.current_term, False)

            if req.term > self.current_term:
                self._step_down(req.term)

            # A legitimate leader exists for this term.
            self.role = Role.FOLLOWER
            self.leader_id = req.leader_id
            self._reset_election_timer()

            # rule 2 — the consistency check (§5.4)
            if req.prev_log_index > 0:
                prev = self.entry_at(req.prev_log_index)
                if prev is None:
                    # Our log is too short. Tell the leader where it ends.
                    return AppendEntriesResp(
                        self.current_term, False,
                        conflict_index=self.last_log_index() + 1,
                        conflict_term=None,
                    )
                if prev.term != req.prev_log_term:
                    # Term mismatch. Report the first index of OUR conflicting term
                    # so the leader can skip the whole run in one step (§8).
                    bad_term = prev.term
                    first = req.prev_log_index
                    while first > 1 and self.entry_at(first - 1).term == bad_term:
                        first -= 1
                    return AppendEntriesResp(
                        self.current_term, False,
                        conflict_index=first, conflict_term=bad_term,
                    )

            # rules 3 + 4 — append, truncating ONLY on a real conflict (§5.4)
            for offset, entry in enumerate(req.entries):
                idx = req.prev_log_index + 1 + offset
                existing = self.entry_at(idx)
                if existing is None:
                    self.log.append(entry)
                elif existing.term != entry.term:
                    del self.log[idx - 1:]          # drop conflict and everything after
                    self.log.append(entry)
                # identical entry already present → skip (idempotent replay)

            if req.entries:
                self._persist()                     # ⭐ fsync before replying

            # rule 5 — advance commitIndex
            if req.leader_commit > self.commit_index:
                self.commit_index = min(req.leader_commit, self.last_log_index())
                self._apply_committed()

            return AppendEntriesResp(self.current_term, True)

    # ───────────────────────── elections ─────────────────────────

    def tick(self) -> None:
        """Called every few ms by the event loop."""
        with self.lock:
            if self.role == Role.LEADER:
                self._broadcast_append_entries()
                return
            if time.monotonic() >= self.election_deadline:
                self._start_election()

    def _start_election(self) -> None:
        self.role = Role.CANDIDATE
        self.current_term += 1
        self.voted_for = self.id
        self._persist()                             # ⭐ before soliciting votes
        self._reset_election_timer()

        term_of_this_election = self.current_term
        votes = {self.id}
        req = RequestVoteReq(
            term=term_of_this_election,
            candidate_id=self.id,
            last_log_index=self.last_log_index(),
            last_log_term=self.last_log_term(),
        )

        def on_response(peer: str, resp: RequestVoteResp) -> None:
            with self.lock:
                if resp.term > self.current_term:
                    self._step_down(resp.term)
                    return
                # ⭐ Ignore late responses from a previous election.
                if self.role != Role.CANDIDATE or self.current_term != term_of_this_election:
                    return
                if resp.vote_granted:
                    votes.add(peer)
                    if len(votes) >= self.quorum:
                        self._become_leader()

        for peer in self.peers:
            self.transport.send_request_vote(peer, req, on_response)

    def _become_leader(self) -> None:
        self.role = Role.LEADER
        self.leader_id = self.id
        nxt = self.last_log_index() + 1
        self.next_index = {p: nxt for p in self.peers}      # optimistic
        self.match_index = {p: 0 for p in self.peers}       # proven

        # ⭐ §11 — the no-op entry. Without it, entries from previous terms
        # can never be committed, and the new leader cannot learn its commitIndex.
        self.log.append(LogEntry(term=self.current_term, index=nxt, command=None))
        self._persist()
        self._broadcast_append_entries()

    # ────────────────────────── replication ──────────────────────────

    def propose(self, command: bytes) -> int | None:
        """Client entry point. Returns the log index, or None if not leader."""
        with self.lock:
            if self.role != Role.LEADER:
                return None
            entry = LogEntry(self.current_term, self.last_log_index() + 1, command)
            self.log.append(entry)
            self._persist()
            self._broadcast_append_entries()
            return entry.index

    def _broadcast_append_entries(self) -> None:
        for peer in self.peers:
            self._send_append_entries(peer)

    def _send_append_entries(self, peer: str) -> None:
        nxt = self.next_index[peer]
        prev_index = nxt - 1
        prev_entry = self.entry_at(prev_index)
        prev_term = prev_entry.term if prev_entry else 0

        entries = self.log[nxt - 1:]                 # may be empty → heartbeat
        req = AppendEntriesReq(
            term=self.current_term,
            leader_id=self.id,
            prev_log_index=prev_index,
            prev_log_term=prev_term,
            entries=entries,
            leader_commit=self.commit_index,
        )
        sent_through = prev_index + len(entries)
        term_when_sent = self.current_term

        def on_response(resp: AppendEntriesResp) -> None:
            with self.lock:
                if resp.term > self.current_term:
                    self._step_down(resp.term)
                    return
                # ⭐ Discard responses to requests from a previous term.
                if self.role != Role.LEADER or self.current_term != term_when_sent:
                    return

                if resp.success:
                    # ⭐ Never move matchIndex backwards — responses can reorder.
                    self.match_index[peer] = max(self.match_index[peer], sent_through)
                    self.next_index[peer] = self.match_index[peer] + 1
                    self._advance_commit_index()
                else:
                    self._backtrack(peer, resp)
                    self._send_append_entries(peer)    # retry immediately

        self.transport.send_append_entries(peer, req, on_response)

    def _backtrack(self, peer: str, resp: AppendEntriesResp) -> None:
        """§8 — jump over whole terms instead of decrementing by one."""
        if resp.conflict_term is not None:
            last_of_term = None
            for e in reversed(self.log):
                if e.term == resp.conflict_term:
                    last_of_term = e.index
                    break
            if last_of_term is not None:
                self.next_index[peer] = last_of_term + 1
            else:
                self.next_index[peer] = resp.conflict_index
        elif resp.conflict_index is not None:
            self.next_index[peer] = resp.conflict_index
        else:
            self.next_index[peer] = max(1, self.next_index[peer] - 1)

    def _advance_commit_index(self) -> None:
        """⭐ §10 — the Figure 8 rule lives here."""
        for n in range(self.last_log_index(), self.commit_index, -1):
            entry = self.entry_at(n)
            # THE CRITICAL CLAUSE: only entries from the CURRENT term may be
            # committed by counting replicas. Earlier terms commit indirectly.
            if entry.term != self.current_term:
                continue
            replicas = 1 + sum(1 for p in self.peers if self.match_index[p] >= n)
            if replicas >= self.quorum:
                self.commit_index = n
                self._apply_committed()
                return

    def _apply_committed(self) -> None:
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.entry_at(self.last_applied)
            if entry.command is not None:            # skip no-ops
                self.sm.apply(entry.command)
```

**The five lines most often written wrong**, all marked ⭐ above:

1. `_persist()` before **replying** to RequestVote, not after (§13)
2. `entry.term != self.current_term: continue` in the commit loop (§10)
3. Truncating only on a genuine term conflict, not unconditionally (§5.4)
4. Discarding RPC responses whose term no longer matches — stale responses from a previous election will otherwise corrupt `matchIndex`
5. `max(self.match_index[peer], sent_through)` — responses can arrive out of order, and `matchIndex` must never decrease

---

## 15. Extension 1 — PreVote

**The problem the base algorithm has.** A server that is partitioned away keeps timing out and incrementing its term. After five minutes of isolation it might be at term 400 while the healthy cluster is contentedly at term 12.

When the partition heals:

```
Isolated S5 (term 400) sends RequestVote{term=400}.

Healthy leader S1 (term 12) receives it:
   400 > 12 → STEP DOWN. currentTerm = 400. Become follower.

S2, S3, S4 also jump to term 400 and step down.

→ The cluster is now leaderless and must hold a fresh election.
→ S5 will LOSE it (its log is behind — §9 rejects it).
→ But it caused a completely unnecessary outage.
→ And the moment S5 is partitioned again, it repeats.
```

**The fix (Ongaro's thesis §9.6): ask before incrementing.**

```python
def _start_election(self):
    if self.PRE_VOTE_ENABLED:
        # Phase 1: a hypothetical election. Do NOT increment currentTerm.
        #          Do NOT change votedFor. Nothing is persisted.
        pre_votes = self._solicit(RequestVoteReq(
            term=self.current_term + 1,      # the term we WOULD use
            candidate_id=self.id,
            last_log_index=self.last_log_index(),
            last_log_term=self.last_log_term(),
        ), pre_vote=True)

        if len(pre_votes) < self.quorum:
            self._reset_election_timer()
            return                            # ⭐ nothing was disturbed

    # Phase 2: the real election, only if we could plausibly win
    self.current_term += 1
    ...
```

And on the receiving side:

```python
def handle_pre_vote(self, req):
    # Grant only if BOTH:
    #   (a) we have not heard from a live leader recently, AND
    #   (b) the candidate's log is sufficiently up to date
    if self._heard_from_leader_within_election_timeout():
        return RequestVoteResp(self.current_term, False)     # ⭐ leader is fine
    if not self._log_is_up_to_date(req.last_log_term, req.last_log_index):
        return RequestVoteResp(self.current_term, False)
    return RequestVoteResp(self.current_term, True)
    # NOTE: no state change, no persist, no term bump.
```

Condition (a) is the important half: a follower that is happily receiving heartbeats refuses to encourage a challenger. The isolated node gets zero pre-votes and never disturbs anyone.

**PreVote is enabled by default in etcd** (and in most mature implementations). If you are evaluating a Raft library, its absence is a meaningful gap.

---

## 16. Extension 2 — CheckQuorum and leader leases

### The stale-leader read problem

```
S1 is leader. A partition isolates it from S2..S5.

S2..S5 elect S4 as the new leader (term+1) and continue accepting writes.

S1 does not know. Nobody has sent it a higher term — it cannot receive anything.
If S1 serves reads from its local state machine, it returns data that is
arbitrarily stale, with no error.
```

The base algorithm never says S1 must stop. It will eventually learn when the partition heals, but until then it is a silent source of stale reads. For a system whose entire purpose is to be authoritative, that is unacceptable.

### CheckQuorum

```python
def tick(self):
    if self.role == Role.LEADER:
        self._broadcast_append_entries()

        # Every election timeout, verify we still command a majority.
        if time.monotonic() >= self.quorum_check_deadline:
            responsive = 1 + sum(
                1 for p in self.peers
                if self.last_response_time[p] > time.monotonic() - self.election_timeout
            )
            if responsive < self.quorum:
                # We are isolated. Demote ourselves proactively.
                self.role = Role.FOLLOWER
                self.leader_id = None
                metrics.increment("raft.leader.stepped_down_no_quorum")
            self.quorum_check_deadline = time.monotonic() + self.election_timeout
```

The isolated leader now steps down within one election timeout and starts returning "no leader" errors instead of stale data. **CheckQuorum converts a silent correctness failure into a loud availability failure**, which is the correct trade for a CP system.

CheckQuorum also pairs with PreVote: a leader that has CheckQuorum will step down on its own, so followers can safely refuse pre-votes while they still hear from it.

### Leader leases — and the assumption they require

CheckQuorum tells you when to stop. Leases let you serve reads fast while you are confident you are still leader.

```
Leader records: last_successful_heartbeat_round = T
Lease is valid until: T + election_timeout − clock_drift_bound

While the lease is valid, the leader may serve reads directly from its
local state machine, with NO round trip to the quorum.
```

**The safety argument:** a new leader cannot be elected until at least one election timeout has elapsed with followers hearing nothing. If our last successful heartbeat round was at `T`, no follower can have started an election before `T + election_timeout`. So until then, we are provably still the only leader.

**The assumption this smuggles in:** bounded clock drift between machines. Raft's core algorithm needs **no** clock assumptions — only timeouts, and being wrong about a timeout costs you an election, never correctness. Leases are different: if one machine's clock runs fast relative to another's by more than the safety margin, the lease can outlive the actual leadership, and you get a stale read that the protocol believed was linearizable.

| | Guarantee | Read cost | Clock assumption |
|---|-----------|-----------|------------------|
| **Log read** (append a read to the log) | Linearizable | 1 RTT + fsync | None |
| **ReadIndex** (§17) | Linearizable | 1 RTT, no disk | None |
| **Lease read** | Linearizable *if clocks behave* | **0 RTT** | **Bounded drift** |

> **Architect's judgement:** lease reads are a large performance win and a small, real correctness risk. etcd implements them and gates them behind `--experimental-enable-lease-checkpoint` style flags and careful defaults. Use them when read latency matters and your clocks are NTP-disciplined with monitoring on drift; use ReadIndex when you want no clock assumptions at all.

---

## 17. Extension 3 — linearizable reads without writing

A naive linearizable read appends a read command to the log, which costs a full round trip **and an fsync on every node**. For a read-heavy workload like a service registry, that is enormously wasteful — you are paying write costs for reads.

**ReadIndex** achieves linearizability with a round trip but no disk writes:

```
1. Leader records  readIndex = its current commitIndex

2. ⭐ Leader confirms it is STILL leader by exchanging one round of heartbeats
      and receiving responses from a majority.
      (If it has a valid lease, this step can be skipped — §16.)

3. Leader waits until its own state machine has applied at least readIndex
      (lastApplied >= readIndex)

4. Serve the read from the local state machine.
```

**Why each step is necessary:**

- **Step 1 before step 2** — reading `commitIndex` first, then confirming leadership, guarantees the value was committed *before* we proved we were leader. Reversing the order allows a stale read.
- **Step 2** — without it, an isolated leader serves stale data (§16). This is the linearizability guarantee.
- **Step 3** — `commitIndex` is the *decision*; `lastApplied` is the *visible state*. The state machine may lag behind by a few entries. Reading before applying returns a value from before the committed write.

```python
def linearizable_read(self, key):
    with self.lock:
        if self.role != Role.LEADER:
            raise NotLeader(self.leader_id)
        read_index = self.commit_index           # step 1

    self._confirm_leadership_via_heartbeat_round()   # step 2 — blocks until majority

    while self.last_applied < read_index:             # step 3
        self.applied_condition.wait()

    return self.sm.get(key)                           # step 4
```

**Follower reads.** A follower can serve linearizable reads too: it asks the leader for the current `readIndex` (one round trip to the leader, which still does step 2), waits for its own `lastApplied` to reach it, then reads locally. This spreads read load across the cluster while preserving linearizability, and is how CockroachDB and TiKV scale reads.

**Serializable (stale) reads** skip all of it and read the local state machine directly. Fast, no round trips, possibly stale. etcd exposes this explicitly:

```bash
etcdctl get /key                      # linearizable by default (ReadIndex)
etcdctl get /key --consistency=s      # serializable — local read, may be stale
```

> **This distinction appears in every quorum system.** When a vendor says "strongly consistent reads", ask which of these three they mean, and what it costs. The answer tells you their real latency profile.

---

## 18. Extension 4 — learners and non-voting members

**The problem with adding a node directly.** Suppose you have a healthy 3-node cluster and add a fourth. Quorum immediately becomes 3. But the new node has an empty log — it needs to catch up, possibly transferring gigabytes of snapshot. During that time:

- Quorum is 3 of 4
- The new node cannot meaningfully participate
- You have effectively made the cluster *less* fault tolerant while it catches up — you now need 3 of the 3 useful nodes

If a second node fails during catch-up, the cluster is unavailable.

**Learners solve this.** A learner receives the full replication stream but **does not vote and does not count towards quorum**.

```
Cluster: S1, S2, S3 (voters, quorum 2)
Add S4 as a LEARNER → still quorum 2, fault tolerance unchanged
S4 catches up over 20 minutes, no impact on the cluster
When S4's matchIndex is close to the leader's lastLogIndex:
    PROMOTE S4 to voter → quorum becomes 3
```

```bash
# etcd
etcdctl member add node4 --learner --peer-urls=https://10.0.1.4:2380
# ... wait for it to catch up ...
etcdctl member promote <member-id>
```

**Other uses for learners:**

| Use | Why a learner |
|-----|--------------|
| **Adding a node safely** | No quorum change during catch-up |
| **Geo-distributed read replica** | A distant node would slow every quorum decision as a voter |
| **Backup / analytics replica** | Full data, zero impact on write latency |
| **Cross-region standby for DR** | Ready to promote, but does not drag latency |

> **The geo-replication insight matters.** Adding a voter in another continent means every commit waits for a quorum that may include that node, adding 100+ ms to writes. As a learner, it receives everything and costs nothing on the critical path. This is how you get a remote copy without paying remote latency — and it is the right pattern for the DR standby discussed in Chapter 19.

---

## 19. Membership changes

Changing the set of voters is the most dangerous operation a consensus cluster performs, because **the definition of "majority" changes** — and if two different definitions are in effect simultaneously, two disjoint majorities can exist.

### Why the naive approach is unsafe

```
Changing directly from C_old = {S1,S2,S3} to C_new = {S1,S2,S3,S4,S5}
Servers switch at different times (there is no atomic global switch).

At one instant:
    S1, S2      still believe C_old  → their quorum is 2
    S3, S4, S5  already believe C_new → their quorum is 3

{S1, S2}       is a majority of C_old  → can elect a leader
{S3, S4, S5}   is a majority of C_new  → can elect a DIFFERENT leader

☠ TWO LEADERS IN THE SAME TERM, from two disjoint "majorities".
```

### Solution A — joint consensus (the original paper)

Pass through a transitional configuration `C_old,new` that requires **separate majorities of both** old and new configurations for every decision.

```
Phase 1: leader appends C_old,new to the log and replicates it.
         From the moment a server SEES this entry (not when it commits),
         it uses joint rules:
             • elections need a majority of C_old AND a majority of C_new
             • commits need a majority of C_old AND a majority of C_new
         → No decision can be made by a majority of only one config.
         → Two disjoint majorities become impossible.

Phase 2: once C_old,new is COMMITTED, the leader appends C_new.
         Once C_new is committed, servers not in C_new shut down.
```

**The critical implementation detail:** a server adopts a configuration entry **as soon as it appears in its log**, not when it is committed. Waiting for commitment would leave a window where servers disagree about the rules — exactly what joint consensus exists to prevent.

### Solution B — single-server changes (the thesis, and what most systems use)

Ongaro's dissertation showed a simpler approach: **add or remove exactly one server at a time.**

```
C_old = {S1, S2, S3}          quorum 2
C_new = {S1, S2, S3, S4}      quorum 3

Any majority of C_old (size 2) and any majority of C_new (size 3)
must INTERSECT, because C_new differs by only one member.
  |maj(C_old)| + |maj(C_new)| = 2 + 3 = 5 > 4 = |C_new|  ✓

→ No joint phase needed. One log entry does it.
```

**The subtlety that was found later** (and which caused real bugs in early implementations): a new leader must **commit an entry from its current term before making a membership change**. Without that, two overlapping single-server changes across a leader transition can still produce disjoint majorities. This is the same family of reasoning as Figure 8 — and it is another reason the no-op entry on election matters.

etcd, Consul and most production systems use single-server changes with that safeguard.

### Operational rules

```
✅ Change one member at a time; wait for the cluster to report healthy between changes
✅ Add as a LEARNER first, promote after catch-up (§18)
✅ REMOVE the old member before adding its replacement when doing a rolling replace,
   or you transiently have an even-sized cluster
✅ Never change membership while the cluster is already degraded
   (a 3-node cluster with one node down has zero margin)
❌ Never edit the member list by hand-editing data directories
❌ Never restore a snapshot onto a live cluster member
```

**The classic production incident:** replacing a failed member in a 3-node cluster by adding the new one first. You now have 4 members with quorum 3, one of which is dead and one of which is empty → only 2 useful nodes → **the cluster is already unavailable** and cannot even commit the membership change to fix itself. Recovery requires forcing a new cluster from a snapshot. **Remove the dead member first**, then add the replacement.

---

## 20. Log compaction and snapshots

The log grows forever. A busy etcd cluster generates millions of entries per day. Three problems follow: disk exhaustion, unbounded restart time (replaying the whole log), and impossibly slow catch-up for new members.

**Snapshots** solve all three. Each server independently writes the state machine's current state to disk and discards the log prefix it covers.

```
BEFORE
log: [1..1,000,000]                            state machine at index 1,000,000

SNAPSHOT
  lastIncludedIndex: 1,000,000
  lastIncludedTerm:  47
  configuration:     {S1,S2,S3}     ← ⭐ must be included
  state:             <serialized state machine>

AFTER
snapshot(1,000,000) + log: [1,000,001 ...]
```

**Why the configuration must be in the snapshot:** on restart, a server needs to know who its peers are *before* it can replay any log. If the membership entry was in the discarded prefix, it is lost. Every real implementation stores the latest configuration in the snapshot metadata.

**Why servers snapshot independently rather than via the leader:** snapshotting is a purely local operation on already-committed state. Coordinating it would add a distributed operation for no benefit.

### InstallSnapshot

When a follower is so far behind that the leader has already discarded the entries it needs:

```
Leader: nextIndex[S3] = 400  but  my log starts at 1,000,001
        → cannot send AppendEntries. Send the snapshot instead.

InstallSnapshot RPC (chunked, since snapshots can be gigabytes):
  term, leaderId, lastIncludedIndex, lastIncludedTerm, offset, data[], done
```

The follower discards its entire log if the snapshot is more recent, installs the state, and resumes normal replication from `lastIncludedIndex + 1`.

### The tuning trade-off

```
Snapshot too often  → constant CPU and I/O cost for serialisation
Snapshot too rarely → long restart times, frequent expensive InstallSnapshot transfers
```

etcd's knob:

```bash
--snapshot-count=10000        # entries between snapshots (default 100,000)
--max-snapshots=5             # snapshot files retained
--max-wals=5                  # WAL files retained
```

**A real operational hazard:** etcd's default `--quota-backend-bytes` is 2 GB (8 GB max recommended). When exceeded, etcd enters a **read-only alarm state** and refuses writes — which in Kubernetes means the entire control plane stops accepting changes. The cause is usually that old revisions were never compacted.

```bash
# Check
etcdctl endpoint status --write-out=table      # look at DB SIZE
etcdctl alarm list                             # NOSPACE?

# Fix: compact old revisions, then defragment, then clear the alarm
rev=$(etcdctl endpoint status --write-out=json | jq '.[0].Status.header.revision')
etcdctl compact $rev
etcdctl defrag --cluster                       # ⭐ do one member at a time
etcdctl alarm disarm
```

`defrag` blocks the member it runs on. **Running it cluster-wide simultaneously takes down your control plane.** One member at a time, waiting for health in between.

---

## 21. Performance: the actual arithmetic

### Write latency

```
Client → Leader                                       ½ RTT
Leader appends to its log + fsync                     D_leader
Leader → Followers (parallel)                         ½ RTT
Follower appends + fsync                              D_follower
Follower → Leader                                     ½ RTT
Leader applies + responds                             ½ RTT

Latency ≈ 2 × RTT + max(D_leader, D_follower_median)
```

Note that leader and follower fsyncs happen **in parallel**, so you pay for the slower of the two — and you only need the **median** follower (the ⌈N/2⌉-th fastest), not the slowest.

**Worked numbers:**

| Deployment | RTT | fsync | Expected write latency |
|-----------|-----|-------|------------------------|
| Same rack, NVMe | 0.2 ms | 0.1 ms | **~0.5 ms** |
| 3 AZs in one region, gp3 | 1 ms | 1.5 ms | **~3.5 ms** |
| 3 AZs, slow network volume | 1 ms | 12 ms | **~14 ms** ← disk-dominated |
| Cross-region (EU/US) | 80 ms | 1 ms | **~161 ms** |
| Three continents | 150 ms | 1 ms | **~301 ms** |

**Two conclusions an architect should draw:**

1. **Disk dominates in the common case.** At 1 ms RTT and 12 ms fsync, you are 85% disk-bound. Faster networking buys nothing; faster disks buy everything. This is why the etcd hardware recommendation is emphatic about SSDs.

2. **Cross-region consensus costs ~2 RTT per write, unavoidably.** A globally-distributed Raft group writing at 300 ms is not misconfigured — it is physics (Chapter 13 §13.10). Systems that need global writes either accept this (Spanner, and it waits *more*), partition by region so most writes are local (CockroachDB's locality-aware placement), or abandon strong consistency.

### Throughput

**Writes are bounded by the leader** — it must send every entry to every follower. That is `N−1` outbound streams from one machine.

Mitigations every implementation uses:

```
BATCHING     Accumulate entries for a few ms, send as one AppendEntries.
             Amortises the fsync — one fsync for 500 entries instead of 500.
             This is the single largest throughput lever.

PIPELINING   Do not wait for AppendEntries response N before sending N+1.
             Keeps the network busy; requires careful nextIndex bookkeeping.

PARALLEL     fsync the leader's log while simultaneously sending to followers,
FSYNC        rather than fsync-then-send. Saves one serial fsync from the path.
```

**Realistic numbers for etcd on decent hardware:** ~10,000 writes/sec, ~50,000 linearizable reads/sec with ReadIndex, much higher with serializable reads. If you need more write throughput than that, the answer is **multiple Raft groups** (sharding), which is exactly what CockroachDB, TiKV and YugabyteDB do — one Raft group per key range, thousands of groups per cluster, each with its own leader. That turns a single-leader bottleneck into a horizontally scalable system.

### The etcd sizing consequence for Kubernetes

```
Kubernetes stores EVERY object in etcd, and every watch is served from it.
A 5,000-node cluster with 100,000 pods generates substantial write load
from status updates alone.

This is why:
  • Large Kubernetes clusters use dedicated etcd nodes on fast local NVMe
  • events are often split to a SEPARATE etcd cluster (--etcd-servers-overrides)
  • aggressive compaction is configured (--etcd-compaction-interval)
  • the recommendation is 3 or 5 members and never more
```

---

## 22. What etcd really does

etcd is the Raft implementation you are most likely to operate, usually without choosing to (it is Kubernetes' entire state store).

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│  gRPC API  (KV, Watch, Lease, Lock, Election, Maintenance)│
├──────────────────────────────────────────────────────────┤
│  etcd server: MVCC layer                                  │
│    every key has a REVISION history, not just a value      │
│    → watches can replay from any revision                  │
├──────────────────────────────────────────────────────────┤
│  raft library (go.etcd.io/raft)                           │
│    ⭐ PURE state machine — no I/O, no network, no clock.   │
│       You feed it messages and ticks; it returns a `Ready`│
│       struct telling you what to persist and send.        │
├──────────────────────────────────────────────────────────┤
│  WAL (write-ahead log, fsync'd)  +  boltdb/bbolt (state)  │
└──────────────────────────────────────────────────────────┘
```

**The `raft` library's design is worth studying in its own right.** By making the consensus module a pure function of (current state, incoming messages, tick) → (new state, outputs), it becomes exhaustively testable — you can enumerate message orderings deterministically. Every I/O concern is pushed to the caller. This is hexagonal architecture (Chapter 02) applied to the hardest possible problem, and it is a large part of why etcd's Raft is trusted.

### Features on top of plain Raft

| Feature | What it adds |
|---------|-------------|
| **MVCC with revisions** | Every mutation gets a global revision; reads can target a historical revision |
| **Watch** | Stream changes from any revision — Kubernetes controllers depend entirely on this |
| **Leases** | Keys with TTLs, attached to a lease that clients keep alive (this is how Kubernetes does node heartbeats and leader election for controllers) |
| **Transactions** | `If(compare).Then(ops).Else(ops)` — compare-and-swap over multiple keys, atomically |
| **Auth + RBAC** | Per-key-prefix permissions |
| **Learner members** | §18 |
| **PreVote, CheckQuorum** | §15, §16 — enabled by default |

The `If/Then/Else` transaction is how distributed locks and leader election are built on etcd:

```go
// Acquire a lock: create the key only if it does not exist
txn := client.Txn(ctx).
    If(clientv3.Compare(clientv3.CreateRevision(lockKey), "=", 0)).
    Then(clientv3.OpPut(lockKey, myID, clientv3.WithLease(leaseID))).
    Else(clientv3.OpGet(lockKey))
```

**And note why this lock is actually safe, unlike a Redis lock** (Chapter 10): the compare-and-set is executed by a linearizable consensus system, and the lease ties the lock's lifetime to a heartbeat the holder must maintain. Combined with a fencing token (the key's `ModRevision`), it satisfies the requirements Chapter 05 §5.6 set out.

### Deployment rules that come directly from this chapter

```
✅ 3 or 5 members. Never 2. Never 4. Rarely 7.                      (§3)
✅ Dedicated fast local SSD/NVMe; wal_fsync p99 < 10 ms.            (§12, §21)
✅ Put the WAL on a SEPARATE disk from the data dir (--wal-dir).
✅ Members in different AZs, but within one region.                 (§21)
✅ Tune heartbeat/election for actual RTT; election ≥ 10× heartbeat. (§5.7)
✅ Monitor: fsync duration, leader changes, DB size, proposal failures.
✅ Snapshot + defrag regularly; defrag ONE MEMBER AT A TIME.        (§20)
✅ Regular snapshot backups, and PRACTISE the restore.              (Ch. 19)
❌ Do not run on network storage (NFS/EFS).                         (§12)
❌ Do not co-locate with noisy neighbours — etcd is latency-sensitive.
❌ Do not add a member to replace a dead one; REMOVE first.         (§19)
```

---

## 23. Debugging a real cluster

### The metrics that matter, in priority order

```promql
# 1. Disk — the #1 cause of instability (§12)
histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m]))
# ALERT above 0.010 (10 ms). Above 25 ms the cluster will be electing constantly.

histogram_quantile(0.99, rate(etcd_disk_backend_commit_duration_seconds_bucket[5m]))
# ALERT above 0.025

# 2. Leader stability
changes(etcd_server_leader_changes_seen_total[1h])
# ALERT above 3/hour. Frequent changes = slow disk, network loss, or bad timeouts.

etcd_server_has_leader
# ALERT on 0 — the cluster cannot accept writes AT ALL.

# 3. Proposals
rate(etcd_server_proposals_failed_total[5m])
# ALERT above 0 — writes are being rejected.

etcd_server_proposals_pending
# ALERT on sustained growth — the leader cannot keep up.

# 4. Network between peers
histogram_quantile(0.99, rate(etcd_network_peer_round_trip_time_seconds_bucket[5m]))
# Should be ~RTT. If it is 10× RTT, something is queueing.

# 5. Capacity
etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes
# ALERT above 0.8 — approaching the NOSPACE alarm (§20)
```

### Diagnostic commands

```bash
# Who is the leader? Are members healthy? How big is the DB?
etcdctl endpoint status --cluster --write-out=table

# +----------------+------------------+---------+---------+-----------+-----------+
# |    ENDPOINT    |        ID        | DB SIZE | IS LEADER | RAFT TERM | RAFT INDEX|
# +----------------+------------------+---------+---------+-----------+-----------+
# | 10.0.1.1:2379  | 8e9e05c52164694d | 2.1 GB  | true    |       847 |  40218935 |
# | 10.0.1.2:2379  | 91bc3c398fb3c146 | 2.1 GB  | false   |       847 |  40218935 |
# | 10.0.1.3:2379  | fd422379fda50e48 | 2.1 GB  | false   |       847 |  40218901 |
# +----------------+------------------+---------+---------+-----------+-----------+
#                                                            ↑ all same = healthy
#                                                              ↑ S3 lagging 34 entries

etcdctl endpoint health --cluster
etcdctl member list --write-out=table
etcdctl alarm list
```

### Symptom → cause table

| Symptom | Likely cause | Check | Fix |
|---------|-------------|-------|-----|
| Frequent leader changes | **Slow disk** (most common) | `wal_fsync_duration` p99 | Move to local NVMe; separate WAL disk |
| " | Election timeout too low for RTT | `peer_round_trip_time` vs timeout | Raise `--election-timeout` (§5.7) |
| " | CPU starvation / noisy neighbour | Node CPU, steal time | Dedicate the node |
| `has_leader = 0` | Lost quorum | `member list`, node health | Restore quorum; do **not** force a new cluster unless truly unrecoverable |
| Writes rejected, `NOSPACE` | DB exceeded quota | `alarm list`, DB size | Compact → defrag → disarm (§20) |
| One member always behind | Slow disk or network on that node | Per-member `raft index` | Investigate that node specifically |
| All writes slow, reads fine | fsync or leader overload | fsync duration, `proposals_pending` | Faster disk; reduce write volume; shard |
| Cluster fine, clients see errors | Client not retrying on leader change | Client logs | Retry with backoff — §11's post-election window |
| Rejoining node disrupts cluster | PreVote disabled | etcd version/flags | Upgrade; PreVote is default in modern etcd |

### Reading the logs

```
# NORMAL and expected during a rolling restart:
"raft.node: 8e9e05c52164694d elected leader 91bc3c398fb3c146 at term 848"

# WARNING — disk is too slow. This is the precursor to instability:
"failed to send out heartbeat on time (exceeded the 100ms timeout for 342.1ms)"
"server is likely overloaded"

# WARNING — apply loop falling behind:
"apply request took too long" took="1.243s" expected-duration="100ms"

# SERIOUS — the cluster cannot make progress:
"lost leader" / "no leader"

# THE DANGEROUS ONE — data mismatch between members.
# This should be impossible if the protocol is implemented correctly.
# It indicates disk corruption, a restore mistake, or split-brain from
# a forced new cluster. Stop and investigate before doing anything else:
"database space exceeded" / "mvcc: database space exceeded"
"member <id> has a different cluster ID"
```

---

## 24. Raft vs Paxos vs ZAB vs Viewstamped Replication

| | **Raft** | **Multi-Paxos** | **ZAB** | **Viewstamped Replication** |
|---|---|---|---|---|
| Year | 2014 | 1989/2001 | 2008 | 1988 |
| Leader | Strong — log flows **only** leader→follower | Optional; any node may propose | Strong | Strong ("primary") |
| Log holes | **Never** — strictly sequential | Allowed; filled later | Never | Never |
| Leader may overwrite own log | **No** | Yes (adopts others' values) | No | No |
| Election restriction | Log must be up to date | None — leader learns state | Highest zxid wins | Highest view |
| Membership change | Joint consensus / single-server | Reconfiguration is notoriously subtle | Dynamic reconfiguration | View change |
| Understandability | **Explicit design goal** | Famously difficult | Moderate | Moderate |
| Used by | etcd, Consul, CockroachDB, TiKV, Kafka KRaft, RabbitMQ quorum queues, Neo4j, MongoDB (variant) | Chubby, Spanner, Megastore | ZooKeeper | Original academic work |

**Why Raft won adoption.** The constraints it adds — no log holes, leaders never overwrite their own entries, logs must be up to date to win an election — are exactly what shrink the state space. Paxos is more general and that generality is precisely what makes it hard to implement correctly. Raft trades a little theoretical elegance for a protocol engineers can actually build and reason about, and a decade of production use has validated that trade.

**MongoDB's protocol** is worth noting as a variant: it is Raft-like (terms, elections, log up-to-date checks) but adapted to MongoDB's oplog and its `w`/`readConcern` settings (Chapter 10). If you understand Raft, MongoDB's replica-set behaviour becomes legible — including why `w: 1` can lose data on failover and `w: "majority"` cannot.

---

## 25. What an architect takes from this

You will almost certainly never implement Raft. Here is what this depth actually buys you.

**1. You can size and place a consensus cluster correctly.**
3 or 5, never 2 or 4, odd only. Spread across AZs, not regions. Fast local disks, because writes are usually fsync-bound, not network-bound. Learners for remote copies.

**2. You can diagnose "the cluster is unstable" in five minutes.**
It is almost always disk latency. `wal_fsync_duration` p99 over 10 ms explains frequent elections, slow writes, and the mysterious Kubernetes control-plane latency that nobody could attribute.

**3. You understand what "committed" means, and you will notice when a vendor is vague about it.**
"Replicated to a majority" ≠ "committed". Figure 8 is the proof. When evaluating any distributed database, ask: *what exactly is the event that makes a write durable, and what happens to writes acknowledged before a leader change?*

**4. You know which consistency you are paying for.**
Log read, ReadIndex read, lease read and stale read are four different products with four different costs. "Strongly consistent" is not an answer.

**5. You understand why CP systems become unavailable, and can defend it.**
When etcd loses quorum, Kubernetes stops scheduling. That is not a bug to be engineered around; it is the guarantee working. The alternative — an AP control plane — would mean two schedulers making conflicting decisions.

**6. You can evaluate a Raft library properly.**
Does it have PreVote? CheckQuorum? Learners? Does it fsync before replying? Does it implement the Figure 8 commit rule? Does it use conflict hints for backtracking? Absence of any of these is a specific, nameable gap rather than a vague feeling.

**7. You know where the leader bottleneck is and what to do about it.**
Single-group Raft tops out around 10k writes/sec. Beyond that, the answer is many Raft groups (range sharding), which is exactly how the distributed SQL databases scale — and knowing that tells you what their architecture must look like before you read their documentation.

**8. You will not write your own.**
Not because it is forbidden, but because you have now seen that the safety of the whole thing rests on a handful of rules whose violations produce unrecoverable, untestable, once-in-a-year corruption. §13 is the argument.

---

## Exercises

1. Draw the quorum-intersection argument for `N=4` and explain precisely why it buys nothing over `N=3`.
2. A five-node cluster has `matchIndex = {S2: 7, S3: 7, S4: 5, S5: 3}`, leader `lastLogIndex = 7`, `currentTerm = 9`, and `log[7].term = 8`. What is `commitIndex`? Why?
3. Modify scenario §11 so that S5 has **two** entries at indices 2 and 3 in term 3. Does anything change? Trace it.
4. Implement `_advance_commit_index` **without** the term check, then construct the test case from §11 that makes it lose a committed write.
5. Why must a server adopt a configuration entry when it *appears* in the log rather than when it *commits*? Construct the failure if it waited.
6. A leader has a valid lease and serves a read. Its clock is 400 ms fast relative to the followers. Construct an execution where the read is not linearizable.
7. Your etcd cluster shows `leader_changes_seen_total` increasing by 20/hour and `wal_fsync_duration` p99 of 45 ms. Give your diagnosis and your first three actions.
8. You must replace a failed member in a 3-node etcd cluster. Write the exact command sequence and explain what goes wrong if you reverse the order.
9. Explain to a product manager, in three sentences without jargon, why the Kubernetes control plane stops working when two of three etcd nodes are down.

---

**Next in this series:** Deep Dive 02 — Time, Clocks and Causality

**Back to:** [Deep Dives](README.md) · [Chapter 05](../05-distributed-systems.md) · [The Map](../README.md)
