# Deep Dive 02 — Time, Clocks and Causality

**Prerequisite:** [Chapter 05 — Distributed Systems](../05-distributed-systems.md) §5.3

**What the map said:** *"There is no 'now'. Use monotonic clocks for durations. Don't order events by wall clock."*

**What this deep dive does:** explains exactly how much your clock lies and why, walks through NTP's arithmetic and the assumption that breaks it, derives happens-before formally, implements Lamport clocks, vector clocks, version vectors and Hybrid Logical Clocks with their full algorithms and failure modes, explains TrueTime and commit-wait, dissects three real outages caused by time, and gives you the techniques to build systems that do not depend on clocks being right.

---

## Contents

```
1.  How wrong is your clock, really?
2.  Where the error comes from
3.  The clock zoo: which one to call
4.  NTP: the arithmetic and the assumption that breaks
5.  Stepping vs slewing, and why it matters to you
6.  Leap seconds and three real outages
7.  The fundamental problem: no global now
8.  Happens-before, formally
9.  Lamport clocks — complete
10. Traced scenario — what Lamport clocks cannot see
11. Vector clocks — complete
12. Traced scenario — detecting a real conflict
13. Version vectors ≠ vector clocks
14. Dotted version vectors and sibling explosion
15. Hybrid Logical Clocks ⭐ — the production answer
16. Traced scenario — HLC under clock skew
17. TrueTime and commit wait
18. Last Write Wins: the anatomy of silent data loss
19. What to do instead: seven techniques
20. Clock skew in distributed tracing
21. Monitoring and debugging clocks
22. What an architect takes from this
```

---

## 1. How wrong is your clock, really?

Concrete numbers, because the abstraction "clocks drift" hides how large the errors actually are.

| Source | Typical error | Worst observed |
|--------|--------------|----------------|
| Uncorrected quartz crystal | **±10–100 ppm** → 1–10 s/day | 200 ppm in heat |
| NTP over the public internet | 1–50 ms | **seconds**, if the path is asymmetric |
| NTP on a LAN, good server | 0.1–1 ms | 10 ms under load |
| PTP (IEEE 1588) with hardware timestamping | **sub-microsecond** | tens of µs |
| GPS-disciplined clock | ~100 ns | — |
| AWS Time Sync Service | ~1 ms (µs with the newer clock sources) | — |
| **VM after live migration** | — | **seconds to minutes of stall** |
| **Container on an oversubscribed host** | — | scheduling delays of 100s of ms |

**The number that should worry you: 10–100 ppm.** A 50 ppm crystal drifts 4.3 seconds per day. Two machines drifting in opposite directions are 8.6 seconds apart after 24 hours without correction.

If your system orders events by `now()`, a write from a machine that is 200 ms fast will beat a genuinely-later write from a machine that is correct. Nothing will log an error. The data is simply wrong.

**Test your own fleet before assuming NTP has solved this:**

```bash
# Offset from your NTP sources, right now
chronyc tracking
# System time     : 0.000234567 seconds fast of NTP time     ← the number that matters
# RMS offset      : 0.000891234 seconds
# Frequency       : 12.456 ppm slow                          ← your crystal's drift
# Root dispersion : 0.001234567 seconds                      ← accumulated uncertainty

chronyc sources -v          # which servers, and how far away
ntpq -p                     # the older ntpd equivalent

# The real question: how far apart are two of YOUR machines?
# (Not "how far is each from NTP" — the errors can be in opposite directions.)
for h in node1 node2 node3; do
  echo -n "$h: "; ssh $h 'date +%s.%N'
done
```

> **The practical fleet rule:** on a well-run cluster with local NTP servers, assume **±10 ms** between any two machines. Across cloud regions with default configuration, assume **±100 ms**. If you have not measured, assume worse. And whatever the number is, it is a *statistical* bound, not a guarantee — there is no protocol that makes a machine's clock provably correct without specialised hardware (§17).

---

## 2. Where the error comes from

### Quartz crystals and temperature

A computer's clock is a quartz crystal oscillating at a nominal frequency. The actual frequency depends on:

- **Manufacturing tolerance** — ±20 ppm is typical for a cheap crystal
- **Temperature** — the dominant factor. An uncompensated crystal's frequency traces a parabola against temperature; a datacenter aisle temperature swing of 10 °C can shift drift by tens of ppm.
- **Ageing** — crystals drift a few ppm per year, permanently
- **Voltage**

**The observable consequence:** a rack under heavy load runs hot, its clocks drift differently from a lightly-loaded rack, and NTP is constantly correcting the difference. This is why clock offset often correlates with CPU load in monitoring graphs.

### Virtualisation

This is the big one in cloud environments, and it produces errors far larger than crystal drift.

```
A VM does not own the CPU. When the hypervisor deschedules it:

  guest's view:   ...running... [nothing] ...running...
  wall clock:     10:00:00.000              10:00:00.340

  The guest lost 340 ms with no notification. If it was mid-way through
  a function, it now measures durations that include the stall.
```

Specific hazards:

| Event | Effect |
|-------|--------|
| **Live migration** | The VM is paused, state is copied, resumed elsewhere. Multi-second stalls. Clock arrives wrong. |
| **Steal time** | Hypervisor gives CPU to another guest. Visible as `%st` in `top`. |
| **Snapshot restore** | The VM resumes with a clock from whenever the snapshot was taken — possibly *days* in the past |
| **Overcommitted host** | Scheduling latency of 100s of ms |
| **Container CPU throttling** | cgroup quota exhausted mid-period; the process is frozen until the next period (Chapter 15 §15.6) |

```bash
# Is the hypervisor stealing time from you?
vmstat 1
# procs ---memory--- ---swap-- -----io---- -system-- ------cpu-----
#  r  b   free  buff  si   so    bi    bo   in   cs  us sy id wa st
#  2  0  1.2G   340M   0    0     4    18  892 1204  34  8 56  0  2
#                                                              ↑↑
#                                            steal time — above ~5% is a problem
```

**A container CPU-throttled for 200 ms has, from its own perspective, experienced a 200 ms pause in the middle of whatever it was doing.** If that code held a lease, checked a timeout, or was mid-way through a two-step operation it believed was fast, it is now operating on stale assumptions. This is the mechanism behind many "impossible" distributed-systems bugs, and it is why §17's lease reasoning needs a safety margin.

### Garbage collection and the process's own pauses

```java
// The code you wrote
long start = System.currentTimeMillis();
if (lease.isValid()) {          // checked: valid, 3 seconds remaining
    // ← 8-second stop-the-world GC pause happens HERE
    writeToSharedResource();    // lease expired 5 seconds ago. Another node holds it.
}
```

**The process cannot observe its own pause.** From inside, no time passed. This is exactly the failure that fencing tokens (§19) exist to prevent, and it is why "check the lease, then act" is never sufficient on its own.

---

## 3. The clock zoo: which one to call

Different clocks answer different questions. Calling the wrong one is one of the most common bugs in this whole area.

| Clock (POSIX) | Measures | Jumps? | NTP-adjusted? | Counts suspend? | Use for |
|---------------|----------|--------|---------------|-----------------|---------|
| `CLOCK_REALTIME` | Wall-clock time since epoch | **Yes** | Yes (step + slew) | Yes | Timestamps for humans, logs, expiry dates |
| `CLOCK_MONOTONIC` | Time since an arbitrary point (boot) | **No** | **Rate-slewed, yes** | **No** (Linux) | **Measuring durations, timeouts** |
| `CLOCK_MONOTONIC_RAW` | Same, no NTP adjustment at all | No | No | No | Measuring the hardware's own rate |
| `CLOCK_BOOTTIME` | Like MONOTONIC but includes suspend | No | Slewed | **Yes** | Timeouts that must survive laptop sleep |
| `CLOCK_PROCESS_CPUTIME_ID` | CPU time used by this process | No | No | — | Profiling CPU, not wall time |

### The bug, in four languages

```python
# ❌ WRONG — an NTP step during the work gives a negative or wildly wrong duration
start = time.time()
do_work()
elapsed = time.time() - start

# ✅ RIGHT
start = time.monotonic()
do_work()
elapsed = time.monotonic() - start
```

```javascript
// ❌ WRONG
const start = Date.now();
// ✅ RIGHT
const start = performance.now();
```

```csharp
// ❌ WRONG
var start = DateTime.UtcNow;
// ✅ RIGHT
var sw = Stopwatch.StartNew();   // uses QueryPerformanceCounter — monotonic
```

```go
// Go got this right at the language level in 1.9:
start := time.Now()
elapsed := time.Since(start)
// time.Time carries BOTH a wall clock reading and a monotonic reading.
// Subtraction automatically uses the monotonic one.
//
// ⚠ But the monotonic reading is STRIPPED by:
//     t.Round(0)          t.Truncate(...)      t.UTC()
//     marshalling/unmarshalling (JSON, gob, protobuf)
//     any round trip through a database or the network
// After any of those, subtraction silently falls back to the wall clock.
```

> **The Go caveat is subtle and bites people.** A `time.Time` that has been serialised and deserialised has lost its monotonic component. Duration arithmetic on it is wall-clock arithmetic again. If you pass timestamps between services and subtract them, you are doing wall-clock maths whether you meant to or not — see §20.

### The subtlety with `CLOCK_MONOTONIC`

`CLOCK_MONOTONIC` never goes *backwards*, but NTP does adjust its **rate** (slewing, §5). If NTP decides your clock runs 50 ppm fast, `CLOCK_MONOTONIC` is slowed to compensate. So a "one second" measurement might actually be 1.00005 seconds of real time.

For almost everything this is irrelevant and in fact desirable. For measuring hardware performance precisely, use `CLOCK_MONOTONIC_RAW`.

And note: **on Linux, `CLOCK_MONOTONIC` stops during system suspend.** A laptop that sleeps for eight hours sees no elapsed monotonic time. If you are writing a timeout that must survive suspend, you want `CLOCK_BOOTTIME`.

---

## 4. NTP: the arithmetic and the assumption that breaks

NTP is how almost every machine gets its time. Understanding its one weak assumption tells you exactly when to distrust it.

### The four timestamps

```
Client                                          Server
  │                                               │
  │──── request, carrying T1 ────────────────────►│  T2 = server receives
  │                                               │
  │                                               │  (server processing)
  │                                               │
  │◄─── response, carrying T2 and T3 ─────────────│  T3 = server transmits
  │
  T4 = client receives
```

The client now has all four timestamps and computes two values:

```
Round-trip delay:   δ = (T4 − T1) − (T3 − T2)
                        └ total ─┘   └ server ┘
                          elapsed     time spent

Clock offset:       θ = ((T2 − T1) + (T3 − T4)) / 2
```

**Deriving the offset formula.** Let `θ` be the true offset (server ahead of client by `θ`) and let the one-way delay be `d` in each direction.

```
T2 = T1 + d + θ          →  T2 − T1 = d + θ
T4 = T3 + d − θ          →  T3 − T4 = −d + θ

Adding:  (T2 − T1) + (T3 − T4) = 2θ
         θ = ((T2 − T1) + (T3 − T4)) / 2     ∎
```

Notice that `d` cancels **exactly** — but only because we assumed the same `d` in both directions.

### The assumption that breaks

> **NTP's accuracy depends entirely on the network path being symmetric.**

If the outbound path takes `d_out` and the return path takes `d_in`, the error in the computed offset is:

```
error = (d_out − d_in) / 2
```

**Where asymmetry comes from in practice:**

| Cause | Typical asymmetry |
|-------|------------------|
| Different physical routes out and back (BGP) | 1–50 ms |
| One direction congested, the other not | 1–100 ms |
| Traffic shaping / QoS applied in one direction | variable |
| Satellite or cellular uplink vs downlink | 100s of ms |
| A busy NTP server delaying its own response | 1–10 ms |
| Virtualisation delaying the timestamping | 1–100 ms |

**The worked failure:** your outbound path to the NTP server is 5 ms, but the return path is routed the long way and takes 45 ms.

```
Actual offset θ = 0 (your clock is perfect)

NTP computes:  θ = ((d_out + θ) + (−d_in + θ)) / 2
                 = (5 − 45) / 2
                 = −20 ms

→ NTP "corrects" your perfect clock by 20 ms in the wrong direction.
```

NTP cannot detect this. There is no information in the four timestamps that distinguishes asymmetry from offset. This is why NTP accuracy over the internet is milliseconds rather than microseconds, and why it degrades exactly when the network is under stress — which is also when your distributed system is under stress.

### Defences NTP itself uses

- **Poll multiple servers** (`minsources`) and discard outliers using an intersection algorithm
- **Filter** — keep the sample with the *lowest* round-trip delay from the last 8, on the theory that the fastest observation had the least queueing
- **Stratum hierarchy** — stratum 0 is a reference clock (GPS, atomic), stratum 1 is directly attached, each hop adds error
- **Root dispersion** — an explicitly tracked upper bound on accumulated error. This is the honest number, and `chronyc tracking` prints it.

**PTP (Precision Time Protocol)** achieves sub-microsecond accuracy by having network switches timestamp packets *in hardware* as they pass through, which removes both queueing delay and OS scheduling from the measurement. It requires PTP-aware switches. Financial trading systems and 5G networks use it; most clouds now offer a PTP-backed time source.

---

## 5. Stepping vs slewing, and why it matters to you

When NTP finds an offset, it has two ways to correct it:

```
SLEWING — change the clock's RATE so it gradually converges
  Typical: adjust by up to 500 ppm → 0.5 ms per second of correction
  Correcting 1 second of error takes ~2,000 seconds (33 minutes)
  ✅ Time remains MONOTONIC. Never jumps. Never repeats.

STEPPING — set the clock directly
  ✅ Instant correction
  ❌ Time JUMPS. It can go BACKWARDS.
  ❌ Two events can receive the same timestamp, or out-of-order timestamps
```

**Default behaviour (chrony and ntpd):** slew small offsets; step if the offset exceeds a threshold (128 ms for ntpd; chrony's `makestep` directive, commonly configured to step only during the first few updates after boot).

### Why you should care

```
# A typical chrony configuration on a server
makestep 1.0 3      # step (rather than slew) if offset > 1 s, but only for
                    # the first 3 updates after startup. After that, slew only.
```

This is deliberate: **a running production system should never see its clock jump backwards.** A backwards step breaks:

- Duration measurements using the wall clock (§3)
- Log ordering — entries appear out of sequence, or timestamps repeat
- Any cache or lease expiry computed as `now + ttl`
- Certificate validity checks
- Database transaction timestamps in systems that use them
- Rate limiters keyed on time buckets

**The `-x` / "never step" option** exists for systems that cannot tolerate a jump at all. The trade-off is that a large offset then takes hours to correct.

> **Design rule that follows:** never write code whose correctness depends on the wall clock moving forward at a constant rate. Use monotonic clocks for durations (§3), and logical clocks for ordering (§9–15).

---

## 6. Leap seconds and three real outages

A leap second is an extra second inserted into UTC to keep it aligned with the Earth's rotation. UTC goes:

```
23:59:59  →  23:59:60  →  00:00:00
              ↑ this second does not exist in POSIX time
```

POSIX `time_t` is defined as seconds since the epoch **assuming exactly 86,400 seconds per day**. There is no representation for `23:59:60`. So implementations either repeat a second or freeze — and both break assumptions.

### Outage 1 — the 2012 Linux kernel livelock

On 30 June 2012, the leap second triggered a kernel bug in the hrtimer/futex code. Threads waiting on timers were woken in a tight loop, driving CPU to 100%.

**Affected, publicly:** Reddit (Cassandra), Mozilla, Qantas (check-in systems, causing real flight delays), LinkedIn, Yelp, StumbleUpon.

The fix was a reboot or `date -s "$(date)"` to reset the timer state — a fix nobody knew at 00:00 UTC on a Saturday.

### Outage 2 — Cloudflare, 1 January 2017

Cloudflare's RRDNS service, written in Go, computed a time delta for a peer-selection algorithm. At the leap second, `time.Now()` — which at that time returned **only** a wall-clock reading — produced a delta that went **negative**.

The code passed that negative duration into a function that assumed non-negative, causing a panic and taking DNS resolution down for a portion of their network for roughly 90 minutes.

**The engineering consequence:** this incident is part of why Go 1.9 (2017) added monotonic clock readings to `time.Time`. The language fixed it so that `time.Since()` could not go negative. That is also why the caveats in §3 about stripping the monotonic reading matter — they reintroduce the exact bug.

### Outage 3 — the AWS/Google divergence problem

Google introduced **leap smear**: instead of inserting a leap second, spread it over 24 hours by running clocks 0.0011% slow. No jump, no repeated second, no `23:59:60`.

AWS adopted smearing too. But:

```
Google smears over 24 hours centred on the leap second.
AWS smears over 24 hours starting at noon.
Other providers do not smear at all.

→ During the smear window, a Google VM and an AWS VM can be up to
  ~0.5 seconds apart, and BOTH believe they are perfectly synchronised.
```

**Consequence for you:** if your system spans providers, or uses a mix of smearing and non-smearing NTP sources, the smear window is a period of elevated, undetected clock skew. Never mix smearing and non-smearing NTP servers in one `chrony.conf` — the intersection algorithm will see them as conflicting and may pick badly.

> **The good news:** in 2022 the international bodies responsible agreed to stop inserting leap seconds by 2035. The bad news: that is a decade away, and the deeper lesson generalises well beyond leap seconds — **any code that assumes time moves forward smoothly is a latent bug.**

---

## 7. The fundamental problem: no global now

Everything above is about *accuracy*. There is a deeper problem that better clocks cannot solve.

```
Node A at 10:00:00.000 sends a message to Node B.
It arrives at Node B at "10:00:00.000" by B's clock.

Question: did the send happen before the receive?

Physically, obviously yes. But there is NO measurement either node can make
that PROVES it, because the only shared reference is a clock neither
of them can verify.
```

Worse, even with perfect clocks:

```
Node A writes x=1 at exactly 10:00:00.000000
Node B writes x=2 at exactly 10:00:00.000000
```

These are genuinely simultaneous. There is no "correct" order. Any system that pretends there is one is inventing an answer.

**The insight that resolves this** (Lamport, 1978): stop trying to order events by *time*. Order them by **causality** — by what could possibly have influenced what. Causality is something the system can actually observe, because it is carried by messages.

> **Two events are ordered if one could have caused the other. Otherwise they are concurrent, and any order you impose is arbitrary — so the system must either pick deliberately or surface the conflict.**

This reframing is the foundation of everything in the rest of this deep dive.

---

## 8. Happens-before, formally

Lamport's happens-before relation, written `→`, is defined by exactly three rules:

```
1. If a and b are events in the SAME process and a occurs before b,
   then  a → b

2. If a is the SENDING of a message and b is the RECEIPT of that message,
   then  a → b

3. Transitivity:  if a → b and b → c,  then  a → c
```

If neither `a → b` nor `b → a`, the events are **concurrent**, written `a ∥ b`.

### Reading a spacetime diagram

```
         e1      e2                e3            e4
P1  ─────●───────●─────────────────●─────────────●────────►
                  ╲                 ╲
                   ╲ m1              ╲ m3
                    ╲                 ╲
         f1          ▼f2      f3       ▼f4
P2  ─────●───────────●───────●─────────●──────────────────►
                             │
                             │ m2
                             ▼
         g1                  g2                  g3
P3  ─────●───────────────────●───────────────────●────────►
```

**What is ordered:**
```
e1 → e2           (rule 1, same process)
e2 → f2           (rule 2, message m1)
e1 → f2           (rule 3, transitivity)
e2 → f3 → g2      (rules 2 and 1 and 2)
e2 → g3           (transitivity through f3, m2, g2)
```

**What is concurrent:**
```
e1 ∥ f1           no message connects them; neither could have influenced the other
e2 ∥ g1           g1 happened before m2 was even sent
f3 ∥ e3           ⭐ look carefully: e3 is not connected to f3 by any chain
g2 ∥ e3           ditto
```

**The physical meaning of `a ∥ b`:** no information could have travelled from `a` to `b` or vice versa. Neither event could possibly know about the other. This is precisely analogous to spacelike separation in relativity, which is not a coincidence — Lamport's paper explicitly draws the parallel.

### Why this is the right abstraction

**Causality is exactly what a system can observe**, because information only travels via messages, and messages are things the system sends and receives.

Wall-clock time is an *external* reference that every node measures imperfectly. Causality is *internal* — it is built from the system's own events. That is why causal ordering can be made exact while wall-clock ordering cannot.

---

## 9. Lamport clocks — complete

The simplest mechanism that captures happens-before: a single integer per process.

### The algorithm

```
Each process P maintains a counter C, initialised to 0.

RULE 1 (local event):
    C = C + 1
    timestamp the event with C

RULE 2 (send a message m):
    C = C + 1
    attach C to m as m.ts
    send

RULE 3 (receive a message m):
    C = max(C, m.ts) + 1
    timestamp the receive event with C
```

### Implementation

```python
import threading

class LamportClock:
    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    def tick(self) -> int:
        """A local event occurred."""
        with self._lock:
            self._counter += 1
            return self._counter

    def send_event(self) -> int:
        """Returns the timestamp to attach to an outgoing message."""
        return self.tick()

    def receive_event(self, received_ts: int) -> int:
        """A message arrived carrying received_ts."""
        with self._lock:
            self._counter = max(self._counter, received_ts) + 1
            return self._counter
```

### The property it guarantees — and the one it does not

```
✅ GUARANTEED:      a → b  ⟹  C(a) < C(b)
❌ NOT GUARANTEED:  C(a) < C(b)  ⟹  a → b
```

**The implication is the whole point:** if you see `C(a) < C(b)`, you have learned *nothing definite*. Either `a` happened before `b`, **or** they are concurrent. Lamport clocks cannot tell you which.

They can, however, tell you something useful in the negative: **if `C(a) ≥ C(b)`, then `a` definitely did NOT happen before `b`.** A Lamport clock detects the *absence* of causality, not its presence.

### Total ordering with a tiebreaker

Lamport clocks can produce a **total order** that is *consistent with* causality:

```python
def lamport_key(event) -> tuple[int, str]:
    return (event.counter, event.process_id)   # process_id breaks ties deterministically
```

Every event gets a unique, globally comparable key. All processes will agree on the ordering. The order respects causality (`a → b` always sorts `a` first).

**What it is good for:** distributed mutual exclusion (Lamport's original application), any situation where you need a deterministic global order and do not care whether it matches real time.

**What it is not good for:** deciding which of two conflicting writes is "correct", because the order it imposes on concurrent writes is arbitrary — which brings us to the next section.

---

## 10. Traced scenario — what Lamport clocks cannot see

Three processes. Watch the counters, then look at what the numbers claim.

```
        P1                P2                P3
         C=0               C=0               C=0

t1    local event
      C = 1
      [e1: C=1]

t2                     local event
                       C = 1
                       [f1: C=1]

t3    send m1 to P2
      C = 2
      m1.ts = 2
         ────────────►
t4                     receive m1
                       C = max(1, 2)+1 = 3
                       [f2: C=3]

t5                                        local event
                                          C = 1
                                          [g1: C=1]

t6                     send m2 to P3
                       C = 4
                       m2.ts = 4
                          ────────────►
t7                                        receive m2
                                          C = max(1,4)+1 = 5
                                          [g2: C=5]

t8    local event
      C = 3
      [e3: C=3]
```

### The claims the numbers make

```
Event  Clock   True relationship to e3 (C=3)
─────  ─────   ────────────────────────────────
e1     1       e1 → e3   ✓ same process, correctly ordered
f1     1       f1 ∥ e3   ← CONCURRENT, but C(f1)=1 < C(e3)=3
g1     1       g1 ∥ e3   ← CONCURRENT, but C(g1)=1 < C(e3)=3
f2     3       f2 ∥ e3   ← CONCURRENT, and the clocks are EQUAL
g2     5       g2 ∥ e3   ← CONCURRENT, but C(g2)=5 > C(e3)=3
```

**Look at the last row carefully.** `C(g2) = 5 > C(e3) = 3`. If you interpret Lamport clocks as time, you conclude "g2 happened after e3". That conclusion is unjustified — the two events are concurrent, and neither could have known about the other.

### Why this matters concretely

Suppose `e3` and `g2` are both writes to the same key:

```
e3:  set  user_42.email = "old@example.com"    C=3
g2:  set  user_42.email = "new@example.com"    C=5

Last Write Wins by Lamport clock → "new@example.com" wins.
```

That answer might be right. It might be wrong. **The system has no basis for the decision**, because the writes were concurrent — and crucially, it does not *know* that they were concurrent. It silently picks one and discards the other, presenting the result as authoritative.

> **This is the precise limitation that vector clocks exist to remove.** Not to order concurrent events — that is impossible — but to **detect** that they are concurrent, so the application can decide what to do.

---

## 11. Vector clocks — complete

Instead of one counter, each process keeps a **counter per process**.

### The algorithm

```
Each process Pᵢ maintains a vector V of size N (one slot per process),
all slots initialised to 0.

RULE 1 (local event at Pᵢ):
    V[i] = V[i] + 1

RULE 2 (send from Pᵢ):
    V[i] = V[i] + 1
    attach a copy of V to the message

RULE 3 (receive at Pⱼ, message carrying Vm):
    for each k:  V[k] = max(V[k], Vm[k])      ← merge everything we learn
    V[j] = V[j] + 1                            ← then count our own receive event
```

**The intuition:** `V[k]` is "the number of events at process `k` that I know about". Merging on receive is how knowledge propagates.

### Comparison rules — this is where the power is

```
V1 ≤ V2     iff  V1[i] ≤ V2[i]  for ALL i
V1 <  V2    iff  V1 ≤ V2  AND  V1 ≠ V2

Then:
    a → b        iff  V(a) <  V(b)
    b → a        iff  V(b) <  V(a)
    a ∥ b        iff  NEITHER  ⭐ this is the new capability
```

Unlike Lamport clocks, this is an **if and only if**. Vector clocks capture causality exactly.

### Implementation

```python
from dataclasses import dataclass, field
from enum import Enum


class Ordering(Enum):
    BEFORE = "before"        # self happened-before other
    AFTER = "after"          # other happened-before self
    CONCURRENT = "concurrent"  # ⭐ a genuine conflict
    EQUAL = "equal"


@dataclass(frozen=True)
class VectorClock:
    clock: dict[str, int] = field(default_factory=dict)

    def tick(self, node_id: str) -> "VectorClock":
        """Local event at node_id."""
        new = dict(self.clock)
        new[node_id] = new.get(node_id, 0) + 1
        return VectorClock(new)

    def merge(self, other: "VectorClock") -> "VectorClock":
        """Take the pointwise maximum — 'everything either of us knows'."""
        keys = set(self.clock) | set(other.clock)
        return VectorClock({
            k: max(self.clock.get(k, 0), other.clock.get(k, 0)) for k in keys
        })

    def receive(self, other: "VectorClock", node_id: str) -> "VectorClock":
        """Rule 3: merge, then tick for our own receive event."""
        return self.merge(other).tick(node_id)

    def compare(self, other: "VectorClock") -> Ordering:
        keys = set(self.clock) | set(other.clock)
        self_le_other = all(self.clock.get(k, 0) <= other.clock.get(k, 0) for k in keys)
        other_le_self = all(other.clock.get(k, 0) <= self.clock.get(k, 0) for k in keys)

        if self_le_other and other_le_self:
            return Ordering.EQUAL
        if self_le_other:
            return Ordering.BEFORE
        if other_le_self:
            return Ordering.AFTER
        return Ordering.CONCURRENT       # ⭐ neither dominates — a real conflict
```

### The cost: O(N) space, forever

```
3 nodes:      {"A": 12, "B": 7, "C": 3}                     ~50 bytes
100 nodes:                                                   ~2 KB per value
10,000 clients each writing:                                 ~200 KB per value
```

**This is why vector clocks are not used naively at scale.** Attaching a 200 KB clock to a 100-byte value is absurd. Three mitigations exist:

1. **Only track servers, not clients** — a version vector (§13). The number of replicas is small and stable.
2. **Prune old entries** — remove entries not updated within a window. This can produce false "concurrent" verdicts, which is the safe direction to be wrong.
3. **Use Hybrid Logical Clocks** (§15) — O(1) size, at the cost of a bounded-clock-skew assumption.

Production systems overwhelmingly choose (1) or (3).

---

## 12. Traced scenario — detecting a real conflict

The scenario vector clocks were invented for: the Amazon shopping cart.

A user has a cart. They add items from a phone (which happens to reach replica A) and a laptop (which reaches replica B). A network partition means A and B cannot talk.

```
Replica A                            Replica B
V = {A:0, B:0}                       V = {A:0, B:0}
cart = []                            cart = []

─────────────── partition begins ───────────────

Phone → A: add "book"                Laptop → B: add "pen"
A.tick("A")                          B.tick("B")
V = {A:1, B:0}                       V = {A:0, B:1}
cart = ["book"]                      cart = ["pen"]

Phone → A: add "lamp"
A.tick("A")
V = {A:2, B:0}
cart = ["book", "lamp"]

─────────────── partition heals ────────────────

A sends its version to B.
B compares:  V_a = {A:2, B:0}   vs   V_b = {A:0, B:1}

    Is V_a ≤ V_b?   A: 2 ≤ 0?  NO
    Is V_b ≤ V_a?   B: 1 ≤ 0?  NO

    → Neither dominates → CONCURRENT ⭐
```

### What the system now knows, and what it does

The critical point is what the system has learned: **these are not "one is newer". They are two independent branches of history.** Any choice between them loses a genuine customer action.

Dynamo-style systems have three options:

**Option 1 — return both versions (siblings) to the client**

```json
{
  "key": "cart:user_42",
  "siblings": [
    { "value": ["book", "lamp"], "vclock": {"A": 2, "B": 0} },
    { "value": ["pen"],          "vclock": {"A": 0, "B": 1} }
  ]
}
```

The application resolves it. For a shopping cart the resolution is obvious and correct:

```python
def resolve_cart(siblings: list[Cart]) -> Cart:
    merged = set()
    for s in siblings:
        merged |= set(s.items)
    return Cart(items=sorted(merged))      # union — never lose an item

# → ["book", "lamp", "pen"]  ✓ nothing lost
```

**This is exactly what Amazon's Dynamo paper describes**, and the reasoning is commercial: adding an item the customer removed is a minor annoyance; losing an item they added loses a sale. The merge is deliberately biased.

**Option 2 — apply an automatic merge rule.** Only valid when the data type is genuinely mergeable: sets (union), counters (sum of per-node counts), max-value registers. This is the CRDT idea, and it works because the merge function is commutative, associative and idempotent — so every replica reaches the same answer regardless of the order in which it sees updates.

**Option 3 — Last Write Wins.** Pick one by timestamp and discard the other. Fast, simple, and it silently loses data. §18 covers exactly how badly.

### What Last Write Wins would have done here

```
Timestamp of "add lamp" on A:  10:00:00.150  (A's clock is 200 ms fast)
Timestamp of "add pen"  on B:  10:00:00.100  (B's clock is correct)

LWW keeps A's version.  The pen is GONE.
The customer's laptop showed it in the cart. It is not in the order.
No error. No log entry. No way to detect it after the fact.
```

> **The vector clock's contribution is not that it resolves the conflict. It is that it makes the conflict visible so that a human decided how to resolve it.** That distinction is the whole value.

---

## 13. Version vectors ≠ vector clocks

These are constantly conflated, including in otherwise-good documentation. They are different mechanisms for different problems.

| | **Vector clock** | **Version vector** |
|---|---|---|
| Tracks | **Events** in processes | **Versions** of a replicated object |
| One entry per | Process | **Replica** |
| Increments on | Every local event | Every **update to this object** |
| Question answered | "What is the causal order of these events?" | "Are these two replicas' versions of this object in conflict?" |
| Used by | Distributed debugging, causal message delivery | **Dynamo, Riak, Voldemort, CouchDB** |

**The practical difference that matters:** a version vector has one entry per **replica** (typically 3–5), not per **client** (potentially millions). That keeps it small and bounded.

```python
# Version vector for one key, on a 3-replica cluster
{
  "key": "user:42",
  "value": {"email": "d@example.com"},
  "version": {"replica-a": 7, "replica-b": 3, "replica-c": 7}
}
# Three entries. Always three. Regardless of how many clients write.
```

**When a client writes,** it sends back the version vector it read. The replica uses it to determine whether the write is a causal successor of what it already has, or a concurrent branch:

```python
def handle_write(self, key, value, client_context_vv):
    current = self.store.get(key)
    if current is None:
        vv = VersionVector().tick(self.replica_id)
        self.store[key] = Versioned(value, vv)
        return

    ordering = client_context_vv.compare(current.version)
    if ordering in (Ordering.AFTER, Ordering.EQUAL):
        # The client read the current version (or newer) → this is a clean overwrite
        self.store[key] = Versioned(value, current.version.tick(self.replica_id))
    else:
        # ⭐ The client based its write on a version we have since moved past,
        #    OR on a concurrent branch. Keep BOTH.
        self.store[key] = Siblings([
            current,
            Versioned(value, client_context_vv.tick(self.replica_id)),
        ])
```

> **This is why Riak and DynamoDB APIs make you pass a context/version token back on write.** It is not bookkeeping ceremony — it is the mechanism by which the server distinguishes "you are updating what you read" from "you are creating a concurrent branch". A client that discards the context and writes blindly converts every write into a potential conflict.

---

## 14. Dotted version vectors and sibling explosion

Standard version vectors have a real flaw that shows up in production Dynamo-style systems.

### The problem

```
Replica A, key "cart", current version {A: 5}

Client 1 reads {A:5}, writes "add book"
Client 2 reads {A:5}, writes "add pen"       (concurrent, hasn't seen client 1)
Client 3 reads {A:5}, writes "add lamp"      (concurrent)

All three arrive at replica A.

With plain version vectors, A cannot distinguish
  "three concurrent client writes"
from
  "three writes it should merge into one version",
because it has only ONE slot for itself ({A: n}) and cannot represent
three distinct concurrent events at the same replica.

Conservative behaviour: keep all three as siblings.
Then a fourth client reads all 3 siblings and writes → potentially more siblings.
```

**Sibling explosion.** Riak users hit this in production: a single key accumulating thousands of siblings, each read returning megabytes, until the key became unusable. It typically happened with a high-write-rate key and clients that did not correctly pass the context back.

### The fix — dotted version vectors (DVV)

Attach a **dot**: the specific `(replica, counter)` pair identifying *this individual write event*, separate from the causal context it summarises.

```
Version = (dot, context)
          └ this exact write    └ everything it causally follows

Client 1's write:  dot = (A, 6), context = {A: 5}
Client 2's write:  dot = (A, 7), context = {A: 5}
Client 3's write:  dot = (A, 8), context = {A: 5}
```

Now each write is individually identifiable. A later client that reads all three and writes back carries context `{A: 8}`, which **dominates all three dots** — so all three are correctly discarded and replaced with one version. Sibling count returns to one.

**Result:** the number of siblings is bounded by the number of genuinely concurrent clients, not by the write rate.

> **Riak 2.0 adopted DVVs specifically to fix this.** You are unlikely to implement one, but the concept is worth holding: *"a version identifier and the causal context it descends from are different things, and conflating them causes unbounded growth."* The same distinction appears in git (a commit hash vs its ancestor set) and in CRDT causal contexts.

---

## 15. Hybrid Logical Clocks ⭐ — the production answer

Vector clocks are exact but O(N). Physical clocks are O(1) but wrong. **HLC gives you O(1) size, captures happens-before, and stays close to physical time.**

This is what CockroachDB, YugabyteDB, MongoDB and several others actually use. It is the most practically important algorithm in this deep dive.

### The design goals

```
1. Size O(1)                            — one timestamp, not a vector
2. a → b  ⟹  HLC(a) < HLC(b)            — captures causality
3. HLC stays within ε of physical time  — timestamps are HUMAN-MEANINGFUL
4. Backwards compatible with 64-bit timestamps
```

Goal 3 is the one that makes HLC so useful in practice: the timestamps are actual, readable, roughly-correct times that you can put in a log, use for TTLs, and compare against wall clock — while *also* being causally correct.

### The algorithm

State per node: `(l, c)` where `l` is a physical-time-like value and `c` is a logical counter.

```
LOCAL EVENT or SEND:
    l_prev = l
    l = max(l_prev, pt)              # pt = current physical clock reading
    if l == l_prev:
        c = c + 1                    # physical time did not advance → use the counter
    else:
        c = 0                        # physical time advanced → reset the counter
    return (l, c)

RECEIVE a message with timestamp (m.l, m.c):
    l_prev = l
    l = max(l_prev, m.l, pt)         # take the maximum of all three

    if l == l_prev == m.l:
        c = max(c, m.c) + 1          # both were at this l → advance past both
    elif l == l_prev:
        c = c + 1                    # our l won → advance our counter
    elif l == m.l:
        c = m.c + 1                  # their l won → continue from their counter
    else:
        c = 0                        # pt won → fresh physical tick, reset

    return (l, c)

COMPARISON:  (l1, c1) < (l2, c2)  iff  l1 < l2  OR  (l1 == l2 AND c1 < c2)
```

### Implementation

```python
import time, threading
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class HLCTimestamp:
    l: int      # physical component, microseconds since epoch
    c: int      # logical counter

    def __str__(self) -> str:
        secs, usecs = divmod(self.l, 1_000_000)
        return f"{time.strftime('%H:%M:%S', time.gmtime(secs))}.{usecs:06d}+{self.c}"

    def encode(self) -> int:
        """Pack into a single 64-bit int: 48 bits physical, 16 bits counter."""
        return (self.l << 16) | (self.c & 0xFFFF)

    @classmethod
    def decode(cls, packed: int) -> "HLCTimestamp":
        return cls(l=packed >> 16, c=packed & 0xFFFF)


class HybridLogicalClock:
    # ⭐ If a received timestamp is further ahead than this, the sender's clock
    #    is broken. Accepting it would poison our clock permanently.
    MAX_DRIFT_US = 500_000          # 500 ms

    def __init__(self, physical_clock=lambda: int(time.time() * 1_000_000)):
        self._pt = physical_clock
        self._l = 0
        self._c = 0
        self._lock = threading.Lock()

    def now(self) -> HLCTimestamp:
        """Local event or send."""
        with self._lock:
            pt = self._pt()
            l_prev = self._l
            self._l = max(l_prev, pt)
            if self._l == l_prev:
                self._c += 1            # physical clock did not advance
            else:
                self._c = 0             # physical clock advanced
            return HLCTimestamp(self._l, self._c)

    def update(self, msg: HLCTimestamp) -> HLCTimestamp:
        """Receive. Merges the sender's knowledge into ours."""
        with self._lock:
            pt = self._pt()

            # ⭐ Reject an absurd timestamp rather than adopting it.
            if msg.l > pt + self.MAX_DRIFT_US:
                raise ClockDriftTooLarge(
                    f"received HLC {msg.l} is {(msg.l - pt)/1000:.1f} ms ahead of "
                    f"our physical clock; max allowed {self.MAX_DRIFT_US/1000} ms"
                )

            l_prev, c_prev = self._l, self._c
            self._l = max(l_prev, msg.l, pt)

            if self._l == l_prev == msg.l:
                self._c = max(c_prev, msg.c) + 1
            elif self._l == l_prev:
                self._c = c_prev + 1
            elif self._l == msg.l:
                self._c = msg.c + 1
            else:
                self._c = 0

            return HLCTimestamp(self._l, self._c)


class ClockDriftTooLarge(Exception):
    pass
```

### Why the drift check is essential

Without it, HLC has a serious vulnerability:

```
A node's clock is broken and reports the year 2085.
It sends a message with l = <2085 in microseconds>.

Every node that receives it does l = max(l, m.l, pt) → adopts 2085.
Those nodes propagate 2085 to everyone else.

⭐ The entire cluster is now permanently in 2085.
   Physical time will never catch up. The `c` counter becomes the only thing
   advancing, so HLC degenerates into a Lamport clock — losing goal 3 forever.
   Every TTL, expiry and time-based query is broken.
   There is no automatic recovery.
```

**This has happened in production systems.** CockroachDB handles it by **crashing the node** rather than accepting the timestamp:

```
F210415 12:00:00.123 clock synchronization error: this node is more than
500ms away from at least half of the known nodes
```

Crashing is the correct response: a node with a broken clock that stays up will corrupt the cluster's notion of time. A node that crashes is merely unavailable. This is the same reasoning as CP-over-AP in Chapter 05 — **prefer loud unavailability to silent corruption.**

---

## 16. Traced scenario — HLC under clock skew

Three nodes with realistically skewed clocks. Watch how HLC stays causally correct despite the skew, and stays close to physical time despite the logical counters.

```
Physical clocks (microseconds past 10:00:00):
  A: 1000    (200 µs BEHIND true time)
  B: 1200    (true)
  C: 1500    (300 µs AHEAD)

Initial HLC state:  all (0, 0)
```

```
STEP 1 — A: local event
  pt = 1000;  l_prev = 0
  l = max(0, 1000) = 1000;  l ≠ l_prev → c = 0
  A = (1000, 0)

STEP 2 — A: another local event immediately (physical clock has not ticked)
  pt = 1000;  l_prev = 1000
  l = max(1000, 1000) = 1000;  l == l_prev → c = 0 + 1 = 1
  A = (1000, 1)      ⭐ the counter handles sub-resolution events

STEP 3 — A sends m1 to C, carrying (1000, 1)
  Send is a local event: pt still 1000 → l stays 1000, c → 2
  m1.ts = (1000, 2)
  A = (1000, 2)

STEP 4 — C receives m1
  pt = 1500 (C's clock is ahead);  l_prev = 0, c_prev = 0
  drift check:  m1.l (1000) ≤ pt (1500) + 500000  ✓
  l = max(0, 1000, 1500) = 1500
  l ≠ l_prev, l ≠ m.l  → c = 0
  C = (1500, 0)

  ⭐ CAUSALITY HOLDS:  A's send (1000,2)  <  C's receive (1500,0)   ✓
  ⭐ And C's timestamp reflects its own physical clock — still meaningful.

STEP 5 — C sends m2 to B, carrying (1500, 1)
  pt = 1500; l_prev = 1500 → l == l_prev → c = 1
  C = (1500, 1)

STEP 6 — B receives m2
  pt = 1200 (B is BEHIND C);  l_prev = 0
  l = max(0, 1500, 1200) = 1500      ← C's timestamp wins over B's physical clock
  l ≠ l_prev, l == m.l → c = m.c + 1 = 2
  B = (1500, 2)

  ⭐ B's HLC (1500) is now 300 µs AHEAD of its own physical clock (1200).
     This is correct and intentional: B has causally observed an event
     that happened at logical time 1500, so it cannot claim to be earlier.

STEP 7 — B: local event, 100 µs later
  pt = 1300;  l_prev = 1500
  l = max(1500, 1300) = 1500;  l == l_prev → c = 3
  B = (1500, 3)
  ⭐ The counter carries B forward until its physical clock catches up.

STEP 8 — B: local event, 400 µs later
  pt = 1700;  l_prev = 1500
  l = max(1500, 1700) = 1700;  l ≠ l_prev → c = 0
  B = (1700, 0)
  ⭐ Physical time has overtaken. The counter resets. HLC re-converges
     on physical time. This is goal 3 working.
```

### The final ordering, and what it proves

```
(1000,0)  A local
(1000,1)  A local
(1000,2)  A send m1
(1500,0)  C receive m1     ← correctly AFTER the send
(1500,1)  C send m2
(1500,2)  B receive m2     ← correctly AFTER the send
(1500,3)  B local
(1700,0)  B local
```

**Every causally-related pair is correctly ordered.** And every timestamp is within ~300 µs of real physical time, so they remain useful as timestamps — you can log them, display them, use them in a range query, and compare them against a wall-clock value.

**What HLC gives up compared to vector clocks:** it cannot *distinguish* concurrent events from ordered ones. `(1000,0) < (1500,0)` whether those events were causally related or not. Like a Lamport clock, it provides a total order; unlike a vector clock, it cannot tell you when that order is arbitrary.

**Why that trade is usually right in practice:** most systems want a single, agreed, roughly-real timestamp for ordering, and handle conflict detection separately (via row versions, conditional writes, or transactions). Paying O(N) per value to detect concurrency is only worth it when the application genuinely merges concurrent versions — which is the Dynamo/Riak model, not the typical one.

---

## 17. TrueTime and commit wait

Google's answer to distributed time, and the only production approach that makes clock uncertainty **explicit and bounded** rather than hoping it is small.

### The API

```
TT.now() → interval [earliest, latest]

GUARANTEE: the true absolute time is somewhere inside this interval.

ε = (latest − earliest) / 2      the uncertainty
```

**The crucial difference from every other clock API:** `TT.now()` does not return a point. It returns an **interval**, and it guarantees containment. Every other clock returns a number and says nothing about how wrong it might be.

### How the bound is achieved

```
Every datacenter has "time masters": GPS receivers and atomic clocks
(Armageddon masters — deliberately using different failure modes, since
GPS and atomic clocks fail differently).

Every machine runs a daemon that:
  • polls multiple masters, from multiple datacenters
  • uses Marzullo's algorithm to reject liars
  • tracks its own crystal's drift rate conservatively (assumes 200 ppm)
  • ε grows linearly between synchronisations, then snaps back
```

```
   ε
   │        ╱│        ╱│        ╱│
 7ms│      ╱  │      ╱  │      ╱  │       sawtooth: ε grows at the assumed
   │    ╱    │    ╱    │    ╱    │        drift rate, resets on each sync
   │  ╱      │  ╱      │  ╱      │
 1ms│╱        │╱        │╱        │
   └──────────────────────────────► time
      ↑         ↑         ↑
     sync      sync      sync  (every ~30 s)

Reported: ε averages ~4 ms, with a maximum around 7 ms.
```

### Commit wait — the part that matters

TrueTime alone does not give you consistency. **The algorithm built on it does.**

```
To commit a transaction with timestamp s:

  1. Pick s = TT.now().latest        ← the latest time it could possibly be now
  2. Do the work; replicate via Paxos
  3. ⭐ WAIT until TT.now().earliest > s
  4. Only THEN release locks and acknowledge the client
```

**Step 3 is the trick, and it is worth understanding exactly why it works.**

By waiting until `TT.now().earliest > s`, the node has proven that absolute time has definitely passed `s` — because `earliest` is a guaranteed lower bound on the true time. So when the client learns the transaction committed, `s` is definitely in the past for **every** observer, everywhere.

**The consequence is external consistency (linearizability across the whole globe):**

```
Transaction T1 commits with timestamp s1 in London.
Client sees the acknowledgement.
Client then starts transaction T2 in Tokyo.

T2 must get a timestamp s2 > s1, because:
   T1 did not acknowledge until real time passed s1,
   T2 started after that acknowledgement,
   T2's timestamp is TT.now().latest ≥ true time > s1.

→ The timestamp order matches the real-world causal order,
  ACROSS CONTINENTS, with no message passing between them.
```

That last line is remarkable: Tokyo and London agree on ordering without communicating, because they both agree on *time* with a known bound.

### The cost

```
Average commit wait ≈ 2ε ≈ 8–10 ms, added to EVERY read-write transaction.
```

Google chose to pay it. The alternative — no global ordering — was worse for their use cases.

**The engineering lesson that generalises:** Google solved this problem with **hardware** (GPS receivers and atomic clocks in every datacenter). That is a meaningful signal about the difficulty of the problem. If it could have been solved in software, they would have done that.

### The open-source descendants

| System | Approach | Uncertainty handling |
|--------|----------|---------------------|
| **Spanner** | TrueTime + commit wait | Hardware-bounded ε ≈ 4 ms |
| **CockroachDB** | HLC + `--max-offset` | Assumes 500 ms; **crashes** nodes that exceed it |
| **YugabyteDB** | HLC, similar | Configurable max clock skew |
| **AWS (Aurora Limitless etc.)** | Time Sync with bounded error (ClockBound API) | Explicit interval, TrueTime-like |

**CockroachDB's approach is the pragmatic version:** rather than measuring uncertainty, it *assumes* a bound (`--max-offset=500ms`), detects violations, and crashes rather than corrupting. Reads within the uncertainty window either wait or restart the transaction ("uncertainty restarts"), which is why CockroachDB latency can be sensitive to clock quality — a badly-synced cluster produces visible transaction restarts.

> **The architect's takeaway:** any system offering globally-consistent transactions is either paying commit-wait latency, running on specialised time hardware, or making an assumption about clock skew that it enforces by crashing. Ask which. If a vendor claims global consistency with no latency cost and no clock requirements, something is being elided.

---

## 18. Last Write Wins: the anatomy of silent data loss

LWW is the default in more systems than people realise, and it is the single most common way clock error turns into lost data.

### The mechanism

```python
def merge(v1, v2):
    return v1 if v1.timestamp > v2.timestamp else v2
```

Simple, O(1), no siblings, no application involvement. Always converges. That is why it is popular.

### Failure mode 1 — the fast clock swallows later writes

```
Node A's clock is 200 ms fast.

10:00:00.000 (true)  User writes "Alice" via node A.
                     A stamps it 10:00:00.200

10:00:00.100 (true)  User writes "Bob" via node B  (100 ms LATER in reality)
                     B stamps it 10:00:00.100

Replication merges:  200 > 100  →  "Alice" wins.

☠ The LATER write is discarded. The user's most recent change is gone.
  They will see it revert, possibly minutes later when replication settles.
```

### Failure mode 2 — a persistently fast node becomes a black hole

Worse than a single lost write:

```
Node A's clock is 5 seconds fast, and nobody notices.

Every write through A gets a timestamp 5 seconds in the future.
Every write through B or C, for the next 5 seconds, is "older".

→ ALL writes through B and C are silently discarded until real time
  catches up to A's clock.
→ The window reopens every time A writes again.

Symptom the users report: "my changes don't save sometimes".
Symptom in the logs: nothing. Every write returned 200 OK.
```

**This has a name in the Cassandra community and a well-known remedy:** monitor clock skew as a first-class operational metric, and alert aggressively. It is one of the standard entries in a Cassandra runbook precisely because it is so hard to diagnose from the symptoms.

### Failure mode 3 — the poisoned cell

```
A misconfigured client writes with a timestamp of year 2100
(a bug: seconds vs milliseconds, or a broken test fixture reaching production).

That value is now permanent. Every subsequent legitimate write has a
smaller timestamp and is discarded.

The key is DEAD. It cannot be updated. It cannot be deleted
(a tombstone is also a timestamped write, and it loses too).

Recovery requires writing with an even LARGER timestamp,
or deleting at the storage layer.
```

**Cassandra's `USING TIMESTAMP` makes this trivially easy to do by accident:**

```sql
-- A bug in unit conversion produces a timestamp in the far future
INSERT INTO users (id, email) VALUES (42, 'x@y.com')
  USING TIMESTAMP 4102444800000000;   -- year 2100 in microseconds

-- Every later write is now invisible:
UPDATE users SET email = 'correct@y.com' WHERE id = 42;  -- silently lost
DELETE FROM users WHERE id = 42;                          -- silently lost
```

### Where LWW is hiding in systems you use

| System | LWW usage |
|--------|-----------|
| **Cassandra** | **The only conflict resolution.** Per-*cell*, using client-supplied or coordinator timestamps. |
| **DynamoDB** | Between regions in a global table |
| **Riak** | Optional (`last_write_wins=true`) — off by default for good reason |
| **CouchDB** | Deterministic winner chosen, but **all conflicting revisions are retained** |
| **Redis active-active (CRDB)** | LWW for simple types |
| **Many hand-rolled "sync" implementations** | Almost always, usually unknowingly |

**Cassandra's per-cell granularity is an interesting mitigation:** two concurrent writes to *different columns* of the same row both survive, because LWW is applied per cell rather than per row. This significantly reduces the blast radius — but writes to the *same* cell still lose.

### When LWW is genuinely acceptable

```
✅ The value is idempotent and self-correcting
   (a cached computed value, a "last seen" heartbeat, a sensor reading)
✅ Losing an update is genuinely harmless
   (a view counter that is approximate anyway)
✅ A single writer per key by design
   (partitioned so that only one node ever writes a given key —
    then there are no concurrent writes to resolve)
✅ Clock skew is measured, bounded and alerted on

❌ NEVER for: money, inventory, user-authored content, shopping carts,
   permissions, audit records, or anything a user would notice reverting
```

> **The single most useful mitigation, and it is architectural rather than technical: partition so that each key has one writer.** If only one node ever writes `user:42`, concurrent writes to it cannot occur, and LWW's weakness never manifests. This is why partitioning by entity (Chapter 04 §4.9) prevents whole categories of consistency problem, not just hotspots.

---

## 19. What to do instead: seven techniques

### 1. Sequence numbers from a single source

```sql
-- The database assigns the order. One writer, one sequence, no clocks.
INSERT INTO events (aggregate_id, seq, payload)
VALUES ($1, (SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE aggregate_id = $1), $2);
```

Or a dedicated sequence per aggregate. **Perfectly ordered, no clock dependency.** The cost is that all writes for an aggregate must go through one place — which is usually true anyway (Chapter 03: an aggregate is the consistency boundary).

### 2. Version numbers and conditional writes ⭐

```sql
UPDATE accounts
SET    balance = $2, version = version + 1
WHERE  id = $1 AND version = $3;
-- 0 rows affected → someone else changed it → re-read and retry
```

**This is optimistic concurrency (Chapter 09), and it requires no clock at all.** It does not order events; it *detects* that two writers raced and forces one to retry. For most application-level problems this is exactly what you want, and it is strictly better than any timestamp scheme.

The HTTP equivalent is ETags with `If-Match` (Chapter 08 §8.8) — the same mechanism, exposed over the wire.

### 3. Fencing tokens ⭐

The defence against the "process paused, lease expired, process resumes and writes anyway" problem from §2.

```
Lock service issues a monotonically increasing token with every lease.
The protected resource REJECTS any request with a token lower than
the highest it has already seen.
```

```
Client 1 acquires the lock, receives token 33.
Client 1 experiences a 10-second GC pause.
Lease expires. Client 2 acquires the lock, receives token 34.
Client 2 writes with token 34. Storage records highest_token = 34.

Client 1 wakes up, still believing it holds the lock,
and writes with token 33.

Storage: 33 < 34  →  REJECT.   ⭐ Safety preserved without any clock.
```

```python
class FencedStorage:
    def __init__(self):
        self._highest_token = 0

    def write(self, key, value, fencing_token: int):
        if fencing_token < self._highest_token:
            raise StaleFencingToken(
                f"token {fencing_token} < highest seen {self._highest_token}; "
                f"your lease has expired"
            )
        self._highest_token = fencing_token
        self._store[key] = value
```

**The critical property: the storage layer must enforce it.** A fencing token the client checks itself provides no protection — the paused client believes it still holds the lock. This is why ZooKeeper's `zxid` and etcd's `ModRevision` are useful: they are monotonic tokens the *server* can compare.

> Chapter 05 said "Redis locks are not safe for correctness". This is the precise reason: a plain Redis `SET NX PX` lock gives you no fencing token, so a paused client's late write cannot be rejected. etcd gives you the revision number, which can be.

### 4. Causal metadata on the wire

```python
@dataclass
class Event:
    event_id: str
    causation_id: str | None   # WHICH event caused this one
    correlation_id: str        # the originating request
    aggregate_version: int     # position in this aggregate's sequence
    occurred_at: datetime      # ⭐ for HUMANS ONLY. Never used for ordering.
```

The comment on the last field is the important part. Include a timestamp because humans reading logs need one — but make it explicit, in the code and in the documentation, that it is **not** the ordering mechanism. `aggregate_version` is.

### 5. Server-assigned timestamps at a single point

If you must use timestamps, assign them at **one** place:

```python
# ❌ Each client stamps its own write → N clocks, N errors
event.timestamp = datetime.now()          # in the client

# ✅ The server (or the database) stamps it → 1 clock
INSERT INTO events (..., created_at) VALUES (..., now());   -- database clock
```

This does not make the timestamp *correct*, but it makes all timestamps **mutually comparable**, which is usually what you actually needed. One consistently-wrong clock is far better than fifty independently-wrong ones.

### 6. Idempotency instead of ordering

Often the real requirement is not "apply these in order" but "apply each exactly once" (Chapter 05 §5.9). Idempotency keys and dedup tables need no clock and are immune to reordering. If you can restate an ordering requirement as an idempotency requirement, do — it is strictly simpler.

### 7. Make the consumer order-insensitive

Chapter 06 §6.5's version guard, restated as a clock-avoidance technique:

```sql
UPDATE customer_view
SET    name = $2, email = $3, version = $4
WHERE  id = $1 AND version < $4;     -- a late/out-of-order event does nothing
```

No clock, no ordering guarantee needed, and correct under arbitrary reordering and duplication.

---

## 20. Clock skew in distributed tracing

A place where clock error shows up daily, and where most people misread the symptom.

### The symptoms

```
Trace 4bf92f35...

api-gateway     ├────────────────────────────┤  842ms
 └ auth-service    ├──────┤                       18ms   ← starts BEFORE its parent?
 └ db-query           ├────────────────┤         -12ms   ← NEGATIVE duration?
 └ vendor-call            ├──────────────────┤   580ms
```

**A child span appearing to start before its parent, or a negative duration, is almost always clock skew** between the two machines — not a bug in your code and not a broken tracer.

### Why it happens

```
Machine A (gateway)  clock is 15 ms AHEAD
Machine B (auth)     clock is correct

A records span start:  10:00:00.100   (true time 10:00:00.085)
A calls B.
B records span start:  10:00:00.090   (true time 10:00:00.090)

→ The child's recorded start (…090) is BEFORE the parent's (…100).
  Physically impossible, and entirely explained by a 15 ms offset.
```

### What tracing backends do about it

| Approach | Behaviour |
|----------|-----------|
| **Clamp** | Force the child's start ≥ parent's start. Hides the problem, distorts durations. |
| **Skew adjustment** | Estimate the offset from the parent/child relationship and shift the whole span. Jaeger does this. |
| **Show it honestly** | Display the negative value and flag it. Most useful for diagnosis. |

**The important practical rules:**

1. **Durations within one process are reliable** — they come from one monotonic clock. Trust them.
2. **Durations spanning processes are approximate** — trust them to about ±(clock skew).
3. **Never alert on a cross-process duration finer than your clock skew.** If your fleet is ±10 ms, a 5 ms cross-service SLO cannot be measured this way.
4. **Sudden widespread skew artefacts in traces are a clock monitoring signal.** If traces across one host start showing negative child durations, check that host's NTP before investigating the application.

> This connects back to §3: if a language strips the monotonic reading when a timestamp crosses a process boundary (as Go does on serialisation), any duration you compute from those two timestamps is wall-clock arithmetic across two machines — and carries the full clock skew as error.

---

## 21. Monitoring and debugging clocks

### The metrics to collect

```promql
# node_exporter exposes these — collect them, they are nearly free

# Estimated offset from the NTP server
node_timex_offset_seconds
# ALERT if abs() > 0.1   (100 ms)

# Is the clock disciplined at all? 0 = synchronised, 16 = unsynchronised
node_timex_sync_status
# ALERT if 0 (means NOT synchronised — confusingly inverted in some exporters;
#             verify against your exporter version)

# Maximum error estimate — the honest upper bound
node_timex_maxerror_seconds
# ALERT if > 1

# Crystal drift correction being applied
node_timex_frequency_adjustment_ratio

# ⭐ The one that actually matters for correctness: skew BETWEEN your nodes
max(node_time_seconds) - min(node_time_seconds)
# ALERT if > 0.05 (50 ms) for a cluster that shares data
```

**The last one is the important one and it is frequently missing from dashboards.** Each node being within 20 ms of NTP is not the same as two nodes being within 20 ms of *each other* — if one is +20 ms and another is −20 ms, they are 40 ms apart.

### Application-level clock checks

```python
class ClockSkewDetector:
    """Piggyback skew detection on normal RPC traffic. Nearly free."""

    def __init__(self, alert_threshold_ms: int = 100):
        self._threshold = alert_threshold_ms / 1000.0
        self._observed: dict[str, float] = {}

    def on_response(self, peer: str, request_sent_at: float,
                    peer_timestamp: float, response_received_at: float) -> None:
        # NTP's own formula (§4), applied to ordinary application traffic
        rtt = response_received_at - request_sent_at
        estimated_peer_time_now = peer_timestamp + rtt / 2
        offset = estimated_peer_time_now - response_received_at

        self._observed[peer] = offset
        metrics.gauge("clock.peer_offset_seconds", offset, tags={"peer": peer})

        if abs(offset) > self._threshold:
            logger.warning(
                "clock_skew_detected",
                peer=peer, offset_ms=offset * 1000, rtt_ms=rtt * 1000,
            )
```

Every service already exchanges messages; adding a timestamp to the response header makes skew observable across your whole fleet without any new infrastructure. **The accuracy is limited by path asymmetry (§4), so treat it as an order-of-magnitude signal, not a measurement** — but an order of magnitude is exactly what you need to catch a node that is 5 seconds off.

### Diagnosing "my timestamps are wrong"

```bash
# 1. Is this node synchronised at all?
timedatectl status
#   System clock synchronized: yes
#   NTP service: active

chronyc tracking       # offset, drift, root dispersion
chronyc sources -v     # which servers, and are they reachable?

# 2. Was there a recent step?
journalctl -u chronyd --since "1 hour ago" | grep -i step
# "System clock wrong by 1.234567 seconds, adjustment started"

# 3. Is the hypervisor stealing time?
vmstat 1 5             # the 'st' column

# 4. Which clock source is the kernel using?
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
# 'tsc'  = good (fast, reliable on modern CPUs)
# 'kvm-clock' = good in a VM
# 'hpet' or 'acpi_pm' = SLOW (microseconds per call) — every timestamp costs you

# 5. How expensive is a timestamp call here?
# On a bad clocksource, clock_gettime() may not use the vDSO and costs a syscall.
python3 -c "
import time
n = 1_000_000
s = time.perf_counter()
for _ in range(n): time.time()
print(f'{(time.perf_counter()-s)/n*1e9:.0f} ns per time.time()')
"
# ~25 ns = vDSO fast path (good).  ~700 ns = syscall (a real cost in hot loops).
```

**Point 5 is an under-appreciated performance issue.** On a VM with a bad clocksource, `clock_gettime` falls back to a syscall. Logging libraries, metrics libraries and tracing call it several times per request. Switching a clocksource from `hpet` to `tsc` has produced double-digit percentage throughput improvements on affected hosts.

---

## 22. What an architect takes from this

**1. Never order events by wall-clock timestamp.**
Not across machines, not within a cluster, not "because our clocks are pretty good". Use sequence numbers, versions, or logical clocks. If you must use timestamps, assign them at one place and document that they are advisory.

**2. Monotonic for durations. Wall clock for display. Never mixed.**
And know that your language may silently strip the monotonic reading when a timestamp is serialised.

**3. Know which clock assumption every system you use is making.**
Cassandra: LWW on wall clock. CockroachDB: HLC with a 500 ms assumption enforced by crashing. Spanner: hardware-bounded uncertainty plus deliberate waiting. Redis leases: none, which is why they are not safe for correctness. This single question — *"what does this system assume about clocks?"* — is one of the most revealing you can ask a vendor.

**4. LWW is silent data loss with good marketing.**
It is acceptable only when losing an update is genuinely harmless, or when partitioning guarantees a single writer per key. Partitioning by entity is the architectural fix.

**5. Fencing tokens, not lease checks.**
A process cannot observe its own pause. Only the resource being protected can reject a stale writer, and only if it is given a monotonic token to compare.

**6. Vector clocks detect conflicts; they do not resolve them.**
Their value is making a conflict visible so a human designs the merge. If your data type has a natural merge (set union, counter sum, max), you have a CRDT and conflicts are free. If it does not, someone must decide — and the worst decision is to let a timestamp decide silently.

**7. HLC is the pragmatic production answer.**
O(1), causally correct, close to real time. Its one requirement — a bounded-drift check that crashes rather than accepting absurd timestamps — is non-negotiable, because a poisoned HLC is unrecoverable.

**8. Monitor inter-node skew, not just NTP offset.**
Each node being within 20 ms of NTP allows two nodes to be 40 ms apart. Dashboard `max(node_time) − min(node_time)`.

**9. Negative durations in traces are a clock signal, not a tracer bug.**
And they set a floor on the granularity of any cross-service latency measurement you can trust.

**10. Google solved this with GPS receivers and atomic clocks.**
That is the strongest available evidence for how hard the problem is. When someone proposes a design whose correctness depends on clocks agreeing, that fact is the argument.

---

## Exercises

1. Derive NTP's offset formula, then compute the error when the outbound path is 8 ms and the return path is 32 ms.
2. Your fleet's NTP offsets are: A `+18 ms`, B `−22 ms`, C `+4 ms`. What is the worst-case skew between any two nodes? What is the shortest event interval you can order by timestamp?
3. Draw a spacetime diagram with three processes and four messages. Mark every pair of events as ordered or concurrent, then compute both Lamport and vector clocks and verify which relationships each captures.
4. Construct an execution where two events have equal Lamport timestamps. What does a tiebreaker on process ID actually give you, and what does it not?
5. Implement `VectorClock.compare` and write a property test asserting that `a → b ⟺ V(a) < V(b)` over randomly generated executions.
6. Trace an HLC through four nodes where one node's clock is 400 ms ahead. Show the point at which the other nodes' HLCs exceed their own physical clocks, and when they re-converge.
7. Remove the drift check from the HLC implementation. Construct the execution that permanently poisons the cluster, and explain why there is no automatic recovery.
8. Explain commit wait to someone who knows what a transaction is but not what TrueTime is, in four sentences.
9. Design a lock service with fencing tokens. Show precisely where the token must be checked, and why checking it in the client is worthless.
10. A user reports "my profile changes revert after a few minutes, sometimes". The system uses Cassandra with LWW. Give your diagnosis and your first three diagnostic commands.
11. Your traces show child spans starting before their parents on exactly one host. What is your hypothesis and how do you confirm it?
12. Rewrite an event-ordering design that currently uses `created_at` timestamps so that it depends on no clock at all.

---

**Next in this series:** Deep Dive 03 — Consistency Models, Formally

**Back to:** [Deep Dives](README.md) · [Chapter 05](../05-distributed-systems.md) · [The Map](../README.md)
