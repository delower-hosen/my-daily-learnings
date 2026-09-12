# Deep Dive 16 — Concurrency, Memory Models and GC

**Prerequisite:** [Chapter 20 — Performance Engineering](../20-performance-engineering.md) · [Deep Dive 15](15-containers-and-the-kernel.md)

**What the map said:** *"CPU-bound, I/O-bound, memory-bound need different techniques. GC pauses are a cause of tail latency. Reduce allocation."*

**What this deep dive does:** explains why sharing a variable between cores costs 100× more than not sharing it, shows false sharing destroying throughput with a 64-byte alignment fix, explains memory reordering and why code that works on x86 breaks on ARM, walks the double-checked locking bug that was broken for a decade, derives why adding threads can make a system *slower*, explains tri-colour marking and the write barrier that makes concurrent GC possible, compares G1/ZGC/Go's collector on the properties that matter, and ends with the safepoint problem that makes your GC logs lie to you.

---

## Contents

```
1.  The hardware reality
2.  ⭐ Cache coherence: why sharing is expensive
3.  ⭐ False sharing, and the 64-byte fix
4.  Memory reordering: compiler and CPU
5.  ⭐ Memory models: x86-TSO vs ARM
6.  Memory barriers
7.  The Java Memory Model and C++ memory_order
8.  ⭐ The double-checked locking bug
9.  Locks: futex, adaptive spinning, and the 100× cliff
10. ⭐ Lock convoys and contention
11. Lock-free: CAS and the ABA problem
12. ⭐ The Universal Scalability Law — why more threads can be slower
13. Thread pool sizing
14. ⭐ Virtual threads, goroutines, and the pinning problem
15. Garbage collection: the fundamental algorithms
16. ⭐ Tri-colour marking and write barriers
17. The collectors: G1, ZGC, Shenandoah, Go
18. ⭐ GC tuning: what actually matters
19. Allocation profiling
20. ⭐ The safepoint problem — why your GC logs lie
21. Measuring concurrency and GC
22. What an architect takes from this
```

---

## 1. The hardware reality

Concurrency is hard because the machine you are programming is not the machine you think you are programming.

```
⭐ THE MENTAL MODEL MOST PEOPLE HAVE:

   Thread 1 ──┐
   Thread 2 ──┼──► ONE SHARED MEMORY
   Thread 3 ──┘

⭐ THE ACTUAL MACHINE:

   Core 1: [L1 32KB] ─┐
   Core 2: [L1 32KB] ─┼─ [L2 512KB each] ─ [⭐ L3 32MB SHARED] ─ [RAM]
   Core 3: [L1 32KB] ─┤
   Core 4: [L1 32KB] ─┘
              ▲
   ⭐ Each core has its OWN COPY of data it is using.
      A "shared variable" exists in several places at once.
```

```
⭐ THE LATENCY NUMBERS (Chapter 04 §4.2, at the CPU scale):

   L1 cache hit          ⭐ ~1 ns    (4 cycles)
   L2 cache hit          ~4 ns    (12 cycles)
   L3 cache hit          ~15 ns   (40 cycles)
   ⭐ RAM                 ~100 ns  (~300 cycles)
   ⭐ CACHE LINE TRANSFER
      BETWEEN CORES       ~40-100 ns   ← ⭐ the cost of SHARING
```

```
⭐ THE CENTRAL FACT:

   A variable only ONE core touches lives in that core's L1 and costs
   ⭐ ~1 ns to access.

   A variable SEVERAL cores write to must be transferred between
   caches on every write, costing ⭐ ~40-100 ns.

   ⭐ SHARING A MUTABLE VARIABLE IS ~100× MORE EXPENSIVE THAN NOT
      SHARING IT — before any lock is involved.
```

> **This is why "share nothing" architectures are fast, at every scale.** It is the same principle as Chapter 04's stateless services and Deep Dive 02's "partition so each key has one writer" — here it appears in silicon.

---

## 2. ⭐ Cache coherence: why sharing is expensive

```
⭐ MESI — each cache line, in each core's cache, is in one of four states:

   ⭐ M (Modified)  — this core has the ONLY copy, and it is DIRTY
   ⭐ E (Exclusive) — this core has the only copy, and it is CLEAN
   ⭐ S (Shared)    — SEVERAL cores have clean copies
   ⭐ I (Invalid)   — this copy is stale; must re-fetch
```

### What a write costs

```
⭐ Core 1 wants to WRITE to a cache line currently SHARED with cores 2, 3, 4:

  1. ⭐ Core 1 broadcasts "Request For Ownership" on the interconnect
  2. ⭐ Cores 2, 3, 4 mark their copies INVALID
  3. They acknowledge
  4. Core 1's line becomes MODIFIED; the write proceeds

  ⭐ ~40-100 ns, and it scales with core count.
```

```
⭐ AND THE NEXT READ BY CORE 2:

  1. Core 2's copy is INVALID → cache miss
  2. ⭐ The interconnect finds core 1 has it MODIFIED
  3. ⭐ Core 1 must WRITE BACK or FORWARD the line
  4. Both end up SHARED

  ⭐ Another ~40-100 ns.
```

```
⭐ SO A SHARED COUNTER INCREMENTED BY 8 CORES:

   ⭐ EVERY increment invalidates 7 other caches.
   ⭐ The cache line PING-PONGS between cores continuously.

   ⭐ MEASURED: a counter incremented by 1 thread: ~1 ns per increment.
               ⭐ The same counter incremented by 8 threads:
                  ⭐ ~100+ ns per increment — and TOTAL throughput
                     is LOWER than with one thread.
```

```
⭐ THE FIX IS ALWAYS THE SAME: DON'T SHARE.

   ⭐ Per-thread counters, summed on read. This is exactly what
      Java's LongAdder and Go's sharded counters do — and it is
      why they are dramatically faster than AtomicLong under
      contention.
```

```java
// ⭐ AtomicLong: one cache line, contended by every thread
AtomicLong counter = new AtomicLong();      // ⭐ ~100 ns/op at 8 threads

// ⭐ LongAdder: an array of per-thread cells, PADDED to avoid
//    false sharing (§3). sum() adds them up.
LongAdder counter = new LongAdder();        // ⭐ ~2 ns/op at 8 threads
```

---

## 3. ⭐ False sharing, and the 64-byte fix

The most common accidental performance disaster in multi-threaded code.

```
⭐ CACHE COHERENCE OPERATES ON CACHE LINES (64 bytes on x86 and ARM),
   ⭐ NOT ON INDIVIDUAL VARIABLES.

  ⭐ So two COMPLETELY INDEPENDENT variables that happen to sit in
     the same 64-byte line are, as far as the hardware is concerned,
     THE SAME THING.
```

```
   ┌──────────────── ONE 64-BYTE CACHE LINE ────────────────┐
   │ counterA (8B) │ counterB (8B) │ ... unrelated data ... │
   └────────────────────────────────────────────────────────┘
        ▲                  ▲
   ⭐ Thread 1        ⭐ Thread 2
      writes only        writes only
      counterA           counterB

   ⭐ THEY NEVER TOUCH THE SAME VARIABLE.
   ⭐ BUT EVERY WRITE BY THREAD 1 INVALIDATES THREAD 2'S CACHE LINE.
   ⭐ The line ping-pongs. Both threads run at a fraction of their
      potential speed.
```

### The measurement

```java
// ❌ FALSE SHARING — counters adjacent in memory
class Counters {
    volatile long a;    // ⭐ same cache line
    volatile long b;    // ⭐ same cache line
}
// ⭐ 2 threads, one incrementing each: ~85 million ops/sec total

// ✅ PADDED — each counter gets its own cache line
class PaddedCounters {
    volatile long a;
    long p1, p2, p3, p4, p5, p6, p7;   // ⭐ 56 bytes of padding
    volatile long b;
    long p8, p9, p10, p11, p12, p13, p14;
}
// ⭐ 2 threads: ~1,100 million ops/sec total
//    ⭐ A 13× IMPROVEMENT from adding unused fields.
```

### How to fix it properly

```java
// ⭐ Java 8+: @Contended (requires -XX:-RestrictContended)
@jdk.internal.vm.annotation.Contended
volatile long counter;
```

```c
// ⭐ C/C++
alignas(64) std::atomic<long> counter;

// C++17 gives you the portable constant:
alignas(std::hardware_destructive_interference_size) std::atomic<long> counter;
```

```go
// ⭐ Go: manual padding
type PaddedCounter struct {
    value uint64
    _     [56]byte   // ⭐ pad to 64 bytes
}
```

### Where false sharing hides in real systems

```
⭐ 1. ARRAYS INDEXED BY THREAD ID
     results[threadId]++    ⭐ 8 threads → all 8 counters in ONE line

⭐ 2. ADJACENT FIELDS IN A HOT OBJECT
     class Connection { volatile long bytesRead; volatile long bytesWritten; }
     ⭐ Read and write paths are often different threads.

⭐ 3. LOCK-FREE QUEUE HEAD AND TAIL
     ⭐ The producer writes tail; the consumer writes head.
        Adjacent → constant invalidation.
        ⭐ This is why every serious lock-free queue pads them —
           and why the Disruptor pattern exists.

⭐ 4. STRUCT-OF-ARRAYS vs ARRAY-OF-STRUCTS layout decisions
```

```bash
# ⭐ DETECTING IT
perf c2c record -a -- sleep 10
perf c2c report
# ⭐ Shows HITM (hit-modified) events — cache lines being contended,
#   and the exact source lines and offsets involved.

perf stat -e cache-misses,cache-references,LLC-load-misses ./myapp
```

---

## 4. Memory reordering: compiler and CPU

```
⭐ THE CODE YOU WROTE IS NOT THE CODE THAT EXECUTES.

  Two independent layers reorder your memory operations:

  ⭐ 1. THE COMPILER — register allocation, instruction scheduling,
     hoisting loads out of loops, dead store elimination

  ⭐ 2. THE CPU — out-of-order execution, store buffers,
     speculative execution, memory prefetch
```

### The store buffer — the main culprit

```
⭐ A store does not go straight to cache. It goes into a STORE BUFFER
   and is drained later.

  ⭐ WHY: a store that misses cache would otherwise stall the core for
     ~100 ns. Buffering lets execution continue.

  ⭐ THE CONSEQUENCE: a LATER LOAD can complete BEFORE an EARLIER
     STORE becomes visible to other cores.
     ⭐ This is StoreLoad reordering, and it is allowed even on x86.
```

### The canonical broken example

```c
// ⭐ Initially: x = 0, y = 0

// Thread 1            // Thread 2
x = 1;                 y = 1;
r1 = y;                r2 = x;

// ⭐ Intuitively, r1 == 0 && r2 == 0 should be IMPOSSIBLE —
//    at least one thread must have written before the other read.

// ⭐ BUT IT HAPPENS, ON EVERY REAL CPU INCLUDING x86.

// ⭐ WHY: both stores sit in their cores' store buffers. Both loads
//    read from cache, seeing the old values. Both stores drain afterwards.
```

```
⭐ THIS IS THE "STORE BUFFER" LITMUS TEST, and it is the reason
   sequential consistency is NOT what hardware provides — on any
   mainstream architecture.
```

---

## 5. ⭐ Memory models: x86-TSO vs ARM

Different CPU architectures allow different reorderings. **This is why code that works on your laptop can break in production.**

```
⭐ THE FOUR REORDERINGS:

     LoadLoad    — a later load moves before an earlier load
     LoadStore   — a later store moves before an earlier load
     StoreStore  — a later store moves before an earlier store
     StoreLoad   — a later load moves before an earlier store
```

| Architecture | LoadLoad | LoadStore | StoreStore | StoreLoad |
|-------------|----------|-----------|------------|-----------|
| **Sequential consistency** (a fiction) | ❌ | ❌ | ❌ | ❌ |
| ⭐ **x86 / x86-64 (TSO)** | ❌ | ❌ | ❌ | ⭐ **✅ allowed** |
| ⭐ **ARM / ARM64** | ⭐ ✅ | ⭐ ✅ | ⭐ ✅ | ⭐ ✅ |
| **POWER** | ✅ | ✅ | ✅ | ✅ |
| **RISC-V (RVWMO)** | ✅ | ✅ | ✅ | ✅ |

```
⭐⭐ THE PRACTICAL CONSEQUENCE, AND IT MATTERS MORE EVERY YEAR:

   ⭐ x86 IS ALMOST SEQUENTIALLY CONSISTENT. Only StoreLoad reordering
      is permitted. ⭐ So a great deal of INCORRECTLY SYNCHRONISED CODE
      HAPPENS TO WORK ON x86.

   ⭐ ARM IS WEAKLY ORDERED. Nearly everything can be reordered.
      ⭐ THE SAME CODE FAILS.

   ⭐ AND YOU ARE INCREASINGLY RUNNING ON ARM:
        • AWS Graviton (often the default choice now)
        • Apple Silicon (every developer's laptop)
        • Ampere, Azure Cobalt, Google Axion
```

```
⭐ SO: "we've run this code for five years without a problem" is
   ⭐ NOT EVIDENCE OF CORRECTNESS. It may be evidence that you have
      only ever run it on x86.

  ⭐ Data races that were latent for a decade surface on the first
     Graviton deployment — and they look like impossible bugs.
```

> **If you are migrating to ARM, latent data races are a real migration risk.** Run your test suite under ThreadSanitizer (`-fsanitize=thread`, Go's `-race`, Java's jcstress) *before* the migration, not after.

---

## 6. Memory barriers

```
⭐ A MEMORY BARRIER (fence) is an instruction that PREVENTS specific
   reorderings across it.
```

| Barrier | Prevents | x86 instruction | Cost |
|---------|----------|----------------|------|
| `LoadLoad` | Later loads moving before earlier loads | (free on x86) | ~0 |
| `LoadStore` | Later stores before earlier loads | (free on x86) | ~0 |
| `StoreStore` | Later stores before earlier stores | (free on x86) | ~0 |
| ⭐ `StoreLoad` | Later loads before earlier stores | ⭐ `mfence` / `lock`-prefixed op | ⭐ **~20-100 cycles** |

```
⭐ ON x86 ONLY THE StoreLoad BARRIER COSTS ANYTHING — because it is
   the only reordering the hardware actually performs.

  ⭐ It must DRAIN THE STORE BUFFER, which is why it is expensive.

⭐ ON ARM, EVERY barrier costs, because every reordering is possible.
   ⭐ ARM provides finer-grained barriers (dmb ishld, dmb ishst,
      dmb ish) so you pay only for what you need — and acquire/release
      semantics map to cheap instructions (ldar/stlr).
```

```
⭐ THE TAKEAWAY: a `volatile` write in Java, or a `seq_cst` store in
   C++, compiles to a full StoreLoad barrier. ⭐ It is not free.
   In a hot loop it can dominate.
```

---

## 7. The Java Memory Model and C++ memory_order

Rather than expose barriers directly, languages define a **memory model**: a contract about what a correctly-synchronised program is guaranteed to observe.

### Java: happens-before

```
⭐ THE JMM (JSR-133) DEFINES A HAPPENS-BEFORE RELATION.
   ⭐ (The same name as Lamport's from Deep Dive 02 §8 — and the same
      underlying idea: a partial order capturing "could have influenced".)

⭐ IF a happens-before b, THEN a's effects are VISIBLE to b.

  The edges:
   ⭐ 1. Program order within a single thread
   ⭐ 2. MONITOR: unlock of M happens-before every subsequent lock of M
   ⭐ 3. VOLATILE: a write to v happens-before every subsequent read of v
   ⭐ 4. Thread.start() happens-before everything in the started thread
   ⭐ 5. Everything in a thread happens-before another thread's join()
   ⭐ 6. FINAL FIELDS: correctly-constructed final fields are visible
        without synchronisation
   ⭐ 7. Transitivity
```

```
⭐ THE CRITICAL CONSEQUENCE OF RULE 3:

   `volatile` in Java gives you ⭐ VISIBILITY AND ORDERING —
   not just "don't cache in a register", which is what it means in C.

   ⭐ A volatile write ALSO publishes every write that preceded it.
```

```java
// ⭐ This is correct BECAUSE of happens-before rule 3:
class Publisher {
    private Config config;              // ⭐ NOT volatile
    private volatile boolean ready;     // ⭐ volatile

    void publish() {
        config = new Config(...);       // ⭐ 1. ordinary write
        ready = true;                   // ⭐ 2. volatile write — a RELEASE
    }
    Config get() {
        if (ready) {                    // ⭐ 3. volatile read — an ACQUIRE
            return config;              // ⭐ 4. GUARANTEED to see the new Config
        }
        return null;
    }
}
```

```
⭐ THE VOLATILE WRITE ACTS AS A RELEASE FENCE: everything written
   before it is visible to any thread that reads the volatile and
   sees the new value. ⭐ This is the "safe publication" idiom.
```

### ⭐ What `volatile` does NOT give you

```java
volatile int counter;
counter++;     // ⭐ STILL BROKEN. This is read-modify-write:
               //    1. read counter     (volatile read ✓)
               //    2. add 1
               //    3. write counter    (volatile write ✓)
               // ⭐ ANOTHER THREAD CAN INTERLEAVE BETWEEN 1 AND 3.

// ⭐ Use an atomic:
AtomicInteger counter;  counter.incrementAndGet();
// ⭐ or, under contention, LongAdder (§2)
```

### C++ memory_order

```cpp
std::atomic<int> x;

x.store(1, std::memory_order_relaxed);  // ⭐ atomicity only; no ordering
x.store(1, std::memory_order_release);  // ⭐ prior writes visible to an acquirer
x.load(std::memory_order_acquire);      // ⭐ subsequent reads see them
x.store(1, std::memory_order_seq_cst);  // ⭐ DEFAULT: a single total order
```

```
⭐ acquire/release IS THE WORKHORSE. It is exactly the Java volatile
   pairing, and on ARM it maps to cheap ldar/stlr instructions
   rather than full barriers.

⭐ seq_cst is the safe default but the most expensive —
   it requires a total order across ALL seq_cst operations.

⭐ relaxed is for counters and flags where you need atomicity but
   no ordering (e.g. a statistics counter). ⭐ Easy to misuse.
```

---

## 8. ⭐ The double-checked locking bug

The canonical example of why memory models matter — and it was broken in Java for nearly a decade before anyone understood why.

```java
// ❌ BROKEN (without volatile)
class Singleton {
    private static Singleton instance;      // ⭐ not volatile

    static Singleton getInstance() {
        if (instance == null) {                    // ⭐ 1. unsynchronised read
            synchronized (Singleton.class) {
                if (instance == null) {            // 2. double check
                    ⭐ instance = new Singleton();  // 3. THE BUG
                }
            }
        }
        return instance;
    }
}
```

### Why it is broken

```
⭐ `instance = new Singleton()` IS NOT ONE OPERATION. It is three:

   ⭐ a. ALLOCATE memory for the object
   ⭐ b. RUN THE CONSTRUCTOR (initialise the fields)
   ⭐ c. ASSIGN the reference to `instance`

⭐ THE COMPILER AND CPU MAY REORDER b AND c.

   ⭐ So the execution can be:  a, c, b
       — the reference is published BEFORE the object is constructed.
```

```
⭐ THE FAILURE:

   Thread 1: allocates, ⭐ ASSIGNS instance (step c), is preempted
             before running the constructor (step b).

   Thread 2: reads `instance` at line 1. ⭐ IT IS NOT NULL.
             ⭐ Returns a PARTIALLY CONSTRUCTED OBJECT.
             ⭐ Its fields are zeros/nulls.

   ⭐ NullPointerException, or silently wrong behaviour, in code that
      looks obviously correct.
```

### The fixes

```java
// ✅ FIX 1 — volatile (⭐ works correctly since Java 5 / JSR-133)
private static volatile Singleton instance;
// ⭐ The volatile write is a release fence: the constructor's writes
//    cannot be reordered after it.
```

```java
// ✅ ⭐ FIX 2 — the initialization-on-demand holder idiom. BEST.
class Singleton {
    private static class Holder {
        ⭐ static final Singleton INSTANCE = new Singleton();
    }
    static Singleton getInstance() { return Holder.INSTANCE; }
}
// ⭐ The JVM guarantees class initialisation is thread-safe and
//    happens exactly once, lazily, WITH NO SYNCHRONISATION COST
//    on subsequent reads. No volatile, no lock, no barrier.
```

```java
// ✅ FIX 3 — an enum
enum Singleton { INSTANCE; }
// ⭐ Thread-safe, serialization-safe, reflection-safe.
```

```
⭐ THE HISTORICAL NOTE THAT MAKES THE POINT:

   ⭐ Double-checked locking was published as a correct idiom, widely
      copied, and taught — and it was BROKEN under the original JMM
      even WITH volatile. ⭐ JSR-133 (Java 5, 2004) strengthened
      volatile specifically to make it work.

   ⭐ THE LESSON: "it looks correct" and "it works in testing" are
      worth nothing in concurrent code. ⭐ Only the memory model's
      guarantees count.
```

---

## 9. Locks: futex, adaptive spinning, and the 100× cliff

```
⭐ A MODERN MUTEX HAS TWO COMPLETELY DIFFERENT COST PROFILES.
```

### Uncontended — fast

```
⭐ The lock is free. Acquiring it is a single ATOMIC COMPARE-AND-SWAP
   in user space.

   ⭐ NO SYSTEM CALL. ~20 ns.
```

### Contended — expensive

```
⭐ The lock is held. The thread must WAIT.

   1. ⭐ ADAPTIVE SPINNING: spin briefly (tens to hundreds of
      iterations), because the holder may release almost immediately.
      ⭐ Spinning burns CPU but avoids a context switch.

   2. ⭐ If still held: futex_wait() — A SYSTEM CALL. The thread is
      DESCHEDULED.

   3. On release: futex_wake() — another syscall. The waiter is
      made runnable, then must be SCHEDULED, then must
      ⭐ REFILL ITS CACHES (its data was evicted while it slept).

   ⭐ TOTAL: 1-10 µs.
```

```
⭐⭐ THE CLIFF: ~20 ns UNCONTENDED vs ~1-10 µs CONTENDED.
    ⭐ A 50-500× DIFFERENCE.

⭐ THIS IS WHY LOCK CONTENTION IS SO DAMAGING, AND WHY IT IS
   NON-LINEAR: a lock that is fine at 4 threads can collapse
   completely at 16.
```

```
⭐ `futex` = "FAST USERSPACE MUTEX". The design insight is that the
   COMMON CASE (uncontended) needs no kernel involvement at all —
   the kernel is consulted only when a thread must actually block.
   ⭐ Before futexes, every lock operation was a syscall.
```

---

## 10. ⭐ Lock convoys and contention

```
⭐ A LOCK CONVOY: threads queue on a lock, and the queue never drains
   because each handoff costs a context switch.
```

```
⭐ THE MECHANISM:

   1. Thread A holds the lock and is PREEMPTED (its time slice ends).
   2. ⭐ Threads B, C, D, E all block on the lock.
   3. A is rescheduled, finishes, releases.
   4. ⭐ B is woken → context switch → B must refill its caches
      (the data is cold) → B does its short critical section →
      ⭐ B is preempted or blocks.
   5. ⭐ Repeat for C, D, E.

   ⭐ THE ACTUAL WORK takes 100 ns. ⭐ Each HANDOFF costs 1-10 µs.
   ⭐ THROUGHPUT IS DETERMINED BY CONTEXT SWITCHES, NOT BY WORK.
```

```
⭐ THE SYMPTOM: throughput COLLAPSES as concurrency rises, and CPU
   time is dominated by system time and context switching rather than
   user time.

   vmstat 1
   #  r  b   ...  ⭐ in     cs      us  sy  id
   #  24 0        48291  ⭐ 891042  22  ⭐ 61  17
   #                       ^^^^^^^^      ^^ ⭐ 61% SYSTEM TIME
   #                  ⭐ 891k context switches/sec = convoy
```

### The fixes, in order of effectiveness

```
⭐ 1. REDUCE THE CRITICAL SECTION. Do computation OUTSIDE the lock.
      ⭐ Lock only to mutate shared state, never to compute.

⭐ 2. REDUCE SHARING. Per-thread state, sharded structures, LongAdder.
      ⭐ The best lock is the one you do not take.

⭐ 3. SHARD THE LOCK. N locks over N buckets (ConcurrentHashMap's
      original design).

⭐ 4. READ-WRITE LOCKS — ⭐ but beware: a RW lock has HIGHER
      uncontended cost than a plain mutex, and writer starvation is
      real. ⭐ Only worth it when reads dominate heavily and the
      critical section is long.

⭐ 5. LOCK-FREE STRUCTURES (§11) — powerful and easy to get wrong.

⭐ 6. ⭐ IMMUTABILITY AND COPY-ON-WRITE. No lock needed at all.
      (Chapter 01 §1.7 — and this is the performance argument for it.)
```

---

## 11. Lock-free: CAS and the ABA problem

```
⭐ COMPARE-AND-SWAP: "if the value is still X, set it to Y, atomically."

   bool CAS(addr, expected, new):
       atomically:
           if *addr == expected:
               *addr = new;  return true
           else:
               return false
```

```java
// ⭐ The lock-free update loop — the fundamental pattern
long oldValue, newValue;
do {
    oldValue = counter.get();
    newValue = compute(oldValue);
} while (!counter.compareAndSet(oldValue, newValue));   // ⭐ retry on conflict
```

```
⭐ "LOCK-FREE" MEANS: at least one thread always makes progress.
   ⭐ It does NOT mean "fast" or "contention-free" — under heavy
      contention, CAS loops spin and waste CPU, and throughput can
      be WORSE than a mutex.
```

### ⭐ The ABA problem

```
⭐ CAS checks the VALUE, not the HISTORY.

   Thread 1: reads head = A. Is preempted.
   Thread 2: pops A, pops B, ⭐ pushes A back.
             ⭐ head is A again — but the LIST IS COMPLETELY DIFFERENT.
   Thread 1: resumes. ⭐ CAS(head, A, A.next) SUCCEEDS.
             ⭐ A.next points to B — which has been FREED.

   ⭐ THE LIST IS NOW CORRUPTED, and it points into freed memory.
```

### The solutions

```
⭐ 1. TAGGED / VERSIONED POINTERS
   Pack a counter alongside the pointer; CAS both together.
   ⭐ Java: AtomicStampedReference
   ⭐ C++: a 128-bit CAS (cmpxchg16b) with pointer + version

⭐ 2. HAZARD POINTERS
   Each thread publishes the pointers it is currently using.
   ⭐ Memory is only reclaimed when no hazard pointer references it.

⭐ 3. EPOCH-BASED RECLAMATION
   Threads enter/exit epochs; memory freed in epoch N is reclaimed
   only once all threads have advanced past N.
   ⭐ Used by crossbeam (Rust), and conceptually by RCU in the kernel.

⭐ 4. ⭐ GARBAGE COLLECTION
   ⭐ In Java, Go or C#, ABA via memory reuse largely DISAPPEARS —
      the GC will not free a node any thread can still reach.
   ⭐ THIS IS AN UNDER-APPRECIATED ADVANTAGE OF MANAGED RUNTIMES
      FOR LOCK-FREE PROGRAMMING.
```

> **Do not write lock-free data structures.** Use the ones in your standard library, which have been reviewed and model-checked. The failure modes are subtle, non-deterministic, and architecture-dependent (§5).

---

## 12. ⭐ The Universal Scalability Law — why more threads can be slower

Amdahl's Law (Chapter 20 §20.2) says speedup is bounded. **Gunther's Universal Scalability Law says throughput can actually *decrease*.**

```
⭐ C(N) = N / ( 1 + α(N − 1) + β·N·(N − 1) )

   N = concurrency
   ⭐ α = CONTENTION — the serial fraction (Amdahl's term)
   ⭐ β = COHERENCY — the cost of keeping N things consistent
        ⭐ This term is QUADRATIC in N.
```

```
⭐ THE THREE REGIMES:

   ⭐ α = 0, β = 0  → linear scaling (never happens)
   ⭐ α > 0, β = 0  → Amdahl: approaches a CEILING
   ⭐ β > 0         → ⭐ THROUGHPUT PEAKS AND THEN FALLS
```

```
   Throughput
       │           ⭐ peak
       │          ╱╲
       │        ╱    ╲___
       │      ╱           ╲______     ⭐ β > 0: RETROGRADE SCALING
       │    ╱                    ╲___
       │  ╱  ___________________      ⭐ β = 0: Amdahl ceiling
       │ ╱ ╱
       │╱╱
       └──────────────────────────────► concurrency (N)
              ⭐ adding threads past the peak makes it SLOWER
```

```
⭐ WHERE β COMES FROM — and it is everywhere in this deep dive:

   ⭐ • Cache coherence traffic (§2)
   ⭐ • False sharing (§3)
   ⭐ • Lock convoys (§10)
   ⭐ • CAS retry storms (§11)
   ⭐ • Distributed: cross-node coordination, consensus (Deep Dive 01)
```

```
⭐ THE PRACTICAL CONSEQUENCE:

   ⭐ THERE IS AN OPTIMAL CONCURRENCY, AND IT IS FINDABLE BY
      MEASUREMENT — usually far lower than the core count.

   ⭐ "Just add more threads" and "just add more connections" are
      not merely ineffective past a point; they are ACTIVELY HARMFUL.
```

```
⭐ THIS IS ALSO WHY:
   • ⭐ Database connection pools should be SMALL (Deep Dive 06 §16,
     Chapter 09 §9.9) — not "as large as possible"
   • ⭐ Chapter 04 §4.3's "target 50-70% utilisation" exists
   • ⭐ Raft clusters are 3 or 5, not 15 (Deep Dive 01 §3)
   • ⭐ Redis is single-threaded and fast (Deep Dive 11 §1)
```

**Fit the USL curve to a load test at 1, 2, 4, 8, 16, 32 threads.** You will usually find the peak is at a concurrency you would not have guessed, and it tells you exactly how to size pools.

---

## 13. Thread pool sizing

```
⭐ CPU-BOUND WORK:
     threads ≈ number of cores    (sometimes cores + 1)
   ⭐ More threads only add context switching and cache pollution.
   ⭐ AND IN A CONTAINER, "cores" MEANS THE CPU LIMIT,
      NOT THE HOST'S CORE COUNT (Deep Dive 15 §12).

⭐ I/O-BOUND WORK — Little's Law again (Chapter 04 §4.3):
     threads = cores × target_utilisation × (1 + wait_time/service_time)

   ⭐ Example: 8 cores, 90% target, 50 ms wait, 5 ms CPU per request
     threads = 8 × 0.9 × (1 + 50/5) = ⭐ 79 threads
```

```
⭐ THE REAL PROBLEM IS NOT SIZING — IT IS ⭐ BLOCKING IN A POOL
   SIZED FOR NON-BLOCKING WORK.

   ⭐ A ForkJoinPool sized to the core count, where tasks make
      blocking HTTP calls, will have ALL its threads blocked and
      ZERO throughput — while CPU sits at 0%.

   ⭐ THIS IS THE #1 THREAD POOL BUG. And it is exactly the same
      failure as "a blocking call in an async event loop"
      (Chapter 20 §20.4).
```

```
⭐ THE RULE: SEPARATE POOLS FOR SEPARATE WORKLOADS.
   This is the BULKHEAD pattern (Chapter 05 §5.8) applied inside
   a process:

     • a CPU pool sized to cores
     • an I/O pool sized by Little's Law
     • ⭐ a dedicated pool per external dependency, so a slow vendor
       cannot exhaust the threads serving everything else
```

---

## 14. ⭐ Virtual threads, goroutines, and the pinning problem

```
⭐ THE PROBLEM WITH OS THREADS:
   ⭐ ~1 MB of stack each (reserved), ~2-10 µs to context switch.
   ⭐ 10,000 concurrent connections = 10 GB of reserved stack and
      constant scheduler pressure.

⭐ THE ANSWER: M:N SCHEDULING. Many lightweight threads multiplexed
   onto few OS threads.
```

| | OS thread | ⭐ Goroutine | ⭐ Java virtual thread |
|---|---|---|---|
| Initial stack | ⭐ 1-8 MB reserved | ⭐ **2 KB, grows** | ⭐ **Heap-allocated, grows** |
| Context switch | 2-10 µs | ⭐ **~100 ns** | ⭐ **~100 ns** |
| Practical count | ~10,000 | ⭐ **millions** | ⭐ **millions** |
| Scheduler | Kernel | ⭐ Go runtime | ⭐ JVM (ForkJoinPool) |

```
⭐ THE KEY MECHANISM: when a lightweight thread performs a BLOCKING
   OPERATION, the runtime ⭐ UNMOUNTS it from its carrier OS thread
   and mounts another. ⭐ The OS thread is never blocked.

⭐ SO "BLOCKING" CODE BECOMES AS SCALABLE AS ASYNC CODE, WITHOUT
   THE "COLOURED FUNCTION" PROBLEM (async infecting every caller).
```

### ⭐ The pinning problem

```
⭐ UNMOUNTING IS NOT ALWAYS POSSIBLE. When it is not, the virtual
   thread is ⭐ PINNED to its carrier, and the carrier OS thread
   BLOCKS — defeating the entire mechanism.

⭐ JAVA (through JDK 21-23), pinning occurs inside:
   ⭐ • a `synchronized` block or method   ← ⭐ THE BIG ONE
   ⭐ • a native frame (JNI)

   ⭐ CONSEQUENCE: a library using `synchronized` internally —
      which includes many older JDBC drivers and connection pools —
      ⭐ PINS THE CARRIER. With a default carrier pool of
      `availableProcessors()`, a handful of pinned threads
      ⭐ DEADLOCKS YOUR ENTIRE APPLICATION.
```

```bash
# ⭐ DETECT PINNING — run this before adopting virtual threads
-Djdk.tracePinnedThreads=full
# ⭐ Prints a stack trace every time a virtual thread pins.
```

```java
// ⭐ THE FIX (pre-JDK 24): replace synchronized with ReentrantLock,
//    which IS virtual-thread-aware and unmounts correctly.
// ❌ synchronized void update() { ... }
// ✅
private final ReentrantLock lock = new ReentrantLock();
void update() { lock.lock(); try { ... } finally { lock.unlock(); } }
```

```
⭐ JEP 491 (JDK 24) LARGELY REMOVES synchronized PINNING — but you
   will be running on older JDKs for years, and third-party libraries
   are the risk. ⭐ Always run with tracePinnedThreads first.
```

### The other trap: ThreadLocal

```
⭐ ThreadLocal WITH MILLIONS OF VIRTUAL THREADS IS A MEMORY DISASTER.

   ⭐ A ThreadLocal holding a 1 MB buffer × 1,000,000 virtual threads
      = ⭐ 1 TB.

   ⭐ ThreadLocal was designed as an optimisation for a SMALL,
      REUSED pool of threads. That assumption is now false.

⭐ THE REPLACEMENT: ScopedValue (JEP 446+) — immutable, scoped,
   and shared rather than duplicated per thread.
```

```
⭐ GO'S EQUIVALENT ISSUES:
   ⭐ • cgo calls block the OS thread (like JNI)
   ⭐ • Goroutine leaks — a goroutine blocked on a channel nobody
        will ever write to lives forever. ⭐ Always have a
        cancellation path (context.Context).
   ⭐ • runtime.LockOSThread pins deliberately
```

---

## 15. Garbage collection: the fundamental algorithms

```
⭐ MARK-SWEEP
   Mark everything reachable from the roots; sweep the rest.
   ✅ Simple.  ❌ ⭐ FRAGMENTATION — free memory is scattered,
   so a large allocation can fail despite ample free space.

⭐ MARK-COMPACT
   Mark, then MOVE live objects together.
   ✅ ⭐ No fragmentation; allocation becomes a pointer bump.
   ❌ Expensive: must update every reference to every moved object.

⭐ COPYING (semispace)
   Two halves; copy live objects from one to the other.
   ✅ ⭐ Very fast — cost is proportional to LIVE data, not total.
   ✅ Allocation is a pointer bump.
   ❌ ⭐ Uses half the memory.

⭐ REFERENCE COUNTING
   Each object counts its references; free at zero.
   ✅ Immediate reclamation, predictable.
   ❌ ⭐ CANNOT COLLECT CYCLES. ❌ Counter updates are expensive
      and, in multi-threaded code, must be atomic (§2's problem).
   ⭐ (CPython uses this plus a cycle collector.)
```

### ⭐ The generational hypothesis

```
⭐ "MOST OBJECTS DIE YOUNG."

   ⭐ Empirically, 90-98% of objects become garbage almost immediately:
      loop temporaries, string builders, request-scoped objects,
      boxed primitives.
```

```
⭐ THE EXPLOITATION:

   ⭐ YOUNG GENERATION: small, collected FREQUENTLY with a COPYING
      collector. ⭐ Because almost everything is dead, the cost —
      proportional to the SURVIVORS — is tiny.

   ⭐ OLD GENERATION: large, collected RARELY with mark-compact.

   ⭐ RESULT: most collections are cheap and fast. The expensive
      full collection is rare.
```

```
⭐ THE COMPLICATION: an old object may reference a young one.
   ⭐ Scanning the entire old generation to find such references
      would defeat the purpose.

   ⭐ SOLUTION: a REMEMBERED SET / CARD TABLE, maintained by a
      ⭐ WRITE BARRIER (§16) on every reference store. Young
      collections then scan only the remembered set, not the whole
      old generation.
```

---

## 16. ⭐ Tri-colour marking and write barriers

The algorithm that makes **concurrent** garbage collection possible — collecting while the application keeps running.

```
⭐ THREE COLOURS:

   ⭐ WHITE — not yet visited. ⭐ At the end, white = garbage.
   ⭐ GREY  — visited, but its children have not been scanned yet.
   ⭐ BLACK — visited, and all its children have been scanned.
```

```
⭐ THE ALGORITHM:
   1. All objects start WHITE. Roots become GREY.
   2. While grey objects exist:
        take a grey object, ⭐ mark its children GREY,
        ⭐ then colour it BLACK.
   3. ⭐ When no grey objects remain, all WHITE objects are garbage.
```

### ⭐ The invariant, and how the application breaks it

```
⭐ THE TRI-COLOUR INVARIANT:
   ⭐ NO BLACK OBJECT MAY POINT TO A WHITE OBJECT.

   ⭐ (Because black means "fully scanned" — the collector will
      never look at it again.)
```

```
⭐ THE MUTATOR (your application) CAN BREAK IT:

   Collector: has marked A BLACK. B is still WHITE.
   ⭐ Application: A.field = B;        (a black object now points to white)
   ⭐ Application: removes the only other reference to B.

   ⭐ B IS REACHABLE (via A) BUT STILL WHITE.
   ⭐ THE COLLECTOR WILL FREE IT.
   ⭐ THE APPLICATION NOW HOLDS A DANGLING POINTER.
```

### ⭐ Write barriers — the fix, and their cost

```
⭐ A WRITE BARRIER IS CODE THE COMPILER INSERTS BEFORE OR AFTER
   ⭐ EVERY REFERENCE STORE, to preserve the invariant.

⭐ TWO FAMILIES:

  ⭐ SATB (Snapshot-At-The-Beginning) — G1, Shenandoah
     ⭐ Record the OLD value being overwritten, and mark it grey.
     ⭐ Collects a snapshot of the heap as it was when marking began.
     ⭐ Consequence: objects that die DURING marking are not
        collected this cycle ("floating garbage").

  ⭐ INCREMENTAL UPDATE — Go's collector (a hybrid), CMS historically
     ⭐ Record the NEW value being stored, and mark it grey.
     ⭐ Less floating garbage; requires re-scanning.
```

```
⭐⭐ THE COST NOBODY ACCOUNTS FOR:

   ⭐ A WRITE BARRIER RUNS ON EVERY SINGLE REFERENCE ASSIGNMENT
      IN YOUR PROGRAM.

   ⭐ Typically 5-15% throughput overhead — the price of
      concurrent collection.

   ⭐ THIS IS THE FUNDAMENTAL GC TRADE-OFF:
      ⭐ SHORTER PAUSES ARE PAID FOR WITH LOWER THROUGHPUT.
      ⭐ There is no collector that is best at both.
```

> **When someone says "ZGC has sub-millisecond pauses", the correct follow-up is "and what does it cost in throughput?"** The answer is usually 5–15%, and whether that is a good trade depends entirely on whether you are optimising p99 latency or total cost.

---

## 17. The collectors: G1, ZGC, Shenandoah, Go

### G1 (Java's default since 9)

```
⭐ REGION-BASED: the heap is divided into ~2,000 equal regions,
   each dynamically designated Eden, Survivor, Old or Humongous.

⭐ "GARBAGE FIRST": collect the regions with the most garbage first,
   to maximise memory recovered per unit of work.

⭐ PAUSE TARGET: -XX:MaxGCPauseMillis=200 (default).
   ⭐ G1 ADAPTS — it chooses HOW MANY REGIONS to collect in order
      to fit the target. ⭐ It is a goal, not a guarantee.
```

```
⭐ PAUSES: typically 10-200 ms, scaling with heap size.
⭐ GOOD FOR: general-purpose, heaps up to ~32 GB, where a
   100 ms pause is acceptable.
```

### ZGC

```
⭐ SUB-MILLISECOND PAUSES, INDEPENDENT OF HEAP SIZE.
   ⭐ Works from 8 MB to 16 TB heaps with the same pause profile.

⭐ THE MECHANISM: COLOURED POINTERS + LOAD BARRIERS.
   ⭐ Metadata (marked, remapped) is stored IN UNUSED BITS OF THE
      POINTER ITSELF.
   ⭐ A LOAD BARRIER on every reference READ checks those bits and
      fixes up the pointer if the object has moved.

   ⭐ SO: ALL marking and ALL relocation happen CONCURRENTLY.
      The only pauses are tiny root scans.
```

```
⭐ GENERATIONAL ZGC (JDK 21+) added a young generation, dramatically
   improving throughput over the original single-generation design.
   ⭐ Use -XX:+UseZGC -XX:+ZGenerational (default in JDK 23+).

⭐ COST: ⭐ load barriers on every reference read — a higher
   throughput overhead than G1's write barriers, and higher memory
   overhead.
```

### Shenandoah

```
⭐ CONCURRENT COMPACTION via BROOKS FORWARDING POINTERS —
   every object carries an extra word pointing to its current location.

⭐ Similar pause profile to ZGC. ⭐ Lower memory overhead than
   original ZGC, slightly higher per-object overhead.
```

### Go's collector

```
⭐ CONCURRENT MARK-SWEEP. ⭐ NON-GENERATIONAL. ⭐ NON-COMPACTING.

⭐ PAUSES: sub-millisecond, consistently. The design goal was
   explicitly LOW LATENCY over throughput.

⭐ THE TRADE-OFFS THAT FOLLOW FROM NON-COMPACTING:
   ❌ ⭐ Fragmentation — mitigated by size-class allocation (tcmalloc-style)
   ❌ ⭐ Allocation is slower than a bump pointer
   ❌ ⭐ NO GENERATIONAL OPTIMISATION — every cycle scans the whole
      live heap, so GC cost scales with LIVE HEAP SIZE, not with
      garbage produced

⭐ GOGC: the GC triggers when the heap grows GOGC% beyond the live
   size after the last collection. Default 100 = ⭐ collect when the
   heap doubles.
   ⭐ GOGC=400 → fewer collections, 4× more memory.
   ⭐ GOMEMLIMIT (1.19+) → a soft limit that forces collection —
      ⭐ essential in containers (Deep Dive 15 §12).
```

### Choosing

```
⭐ PAUSE REQUIREMENT      COLLECTOR
   ⭐ > 200 ms is fine     Parallel GC (⭐ best THROUGHPUT)
   ⭐ ~100 ms acceptable   G1 (the sensible default)
   ⭐ < 10 ms required     ZGC or Shenandoah
   ⭐ Huge heap (> 32 GB)  ⭐ ZGC (pauses do not grow with heap)
   ⭐ Batch / throughput   Parallel GC — ⭐ deliberately choosing
                           long pauses for maximum throughput
```

---

## 18. ⭐ GC tuning: what actually matters

```
⭐⭐ RULE 1: ALLOCATE LESS. THIS DOMINATES EVERYTHING ELSE.

   ⭐ No collector tuning will match the effect of not creating
      the garbage in the first place. A 50% reduction in allocation
      rate roughly halves GC frequency.
```

```java
// ⭐ Common, avoidable allocation sources — each is a real win:
// ❌ String concatenation in a loop         → StringBuilder
// ❌ Boxing in hot paths (Integer, Long)     → primitive collections
// ❌ Defensive copies of immutable data      → share the immutable object
// ❌ A new logger/formatter per call         → reuse
// ❌ Streams in the hottest inner loops      → a plain loop
// ❌ Large temporary buffers per request     → a pooled buffer
// ❌ ⭐ Log-message construction for a level that is disabled:
//       log.debug("x=" + expensive());       // ⭐ ALWAYS allocates
//       log.debug("x={}", expensive());      // ⭐ still evaluates!
//       if (log.isDebugEnabled()) log.debug("x=" + expensive());  // ✅
```

```
⭐ RULE 2: SIZE THE HEAP CORRECTLY.
   ⭐ Too small → constant collection, high CPU
   ⭐ Too large → longer pauses (for G1/Parallel), wasted memory,
      ⭐ and in a container, OOM kill (Deep Dive 15 §12)

   ⭐ A rough guide: the live set should be 30-50% of the heap.
      Measure the live set from a full GC log.

⭐ RULE 3: SET -Xms == -Xmx in a container.
   ⭐ Heap resizing is expensive, and the container's memory is
      fixed anyway. ⭐ Avoids gradual growth into an OOM kill.

⭐ RULE 4: CHOOSE THE COLLECTOR FOR YOUR PAUSE REQUIREMENT (§17).

⭐ RULE 5: STOP THERE.
   ⭐ Beyond these, most GC flags do more harm than good. G1 and ZGC
      are adaptive and tune themselves better than hand-set flags.
      ⭐ The vast majority of "GC tuning" blog posts are cargo cult.
```

```bash
# ⭐ THE LOGGING YOU ACTUALLY NEED (JDK 9+ unified logging)
-Xlog:gc*,safepoint:file=/var/log/gc.log:time,uptime,level,tags:filecount=5,filesize=20M

# ⭐ And the container-aware sizing (Deep Dive 15 §12)
-XX:MaxRAMPercentage=75 -XX:ActiveProcessorCount=<cpu limit>
```

---

## 19. Allocation profiling

```
⭐ YOU CANNOT REDUCE ALLOCATION YOU CANNOT SEE.
```

```bash
# ⭐ async-profiler — the best tool for this. Low overhead, works in prod.
./profiler.sh -e alloc -d 60 -f alloc.html <pid>
# ⭐ Produces a flame graph BY ALLOCATION VOLUME, not by CPU time.
#   ⭐ The widest frames are where your garbage comes from.

# ⭐ CPU profile for comparison
./profiler.sh -e cpu -d 60 -f cpu.html <pid>

# ⭐ Lock contention (§9-10)
./profiler.sh -e lock -d 60 -f lock.html <pid>
```

```bash
# ⭐ JFR — built in, always available, very low overhead
jcmd <pid> JFR.start duration=60s filename=/tmp/rec.jfr settings=profile
jfr summary /tmp/rec.jfr
jfr print --events ObjectAllocationSample /tmp/rec.jfr
```

```go
// ⭐ Go: pprof
import _ "net/http/pprof"
// go tool pprof -http=:8080 http://localhost:6060/debug/pprof/allocs
// ⭐ -alloc_space  = total allocated (⭐ what drives GC)
// ⭐ -inuse_space  = currently live (what drives heap size)
```

### ⭐ Escape analysis — the allocations that vanish

```
⭐ The JIT can prove an object NEVER ESCAPES its method, and then
   ⭐ ELIMINATE THE ALLOCATION ENTIRELY (scalar replacement) —
      the fields become registers.

  ⭐ THIS IS WHY MICROBENCHMARKS LIE: an allocation in a benchmark
     may be optimised away completely, while the same code in a
     real call graph (where the object escapes) allocates.
```

```bash
# ⭐ See what escape analysis did
-XX:+UnlockDiagnosticVMOptions -XX:+PrintEscapeAnalysis -XX:+PrintEliminateAllocations
```

```
⭐ THE PRACTICAL IMPLICATION: small, short-lived objects that do not
   escape are often FREE. ⭐ Do not contort your code to avoid them.
   ⭐ Profile first — optimise the allocations the profiler shows,
      not the ones you imagine.
```

---

## 20. ⭐ The safepoint problem — why your GC logs lie

```
⭐ THE JVM CAN ONLY STOP A THREAD AT A SAFEPOINT — a place where
   the thread's state is known and walkable (object references are
   in known locations).

⭐ SAFEPOINT POLLS ARE INSERTED AT:
   • method entry and return
   • ⭐ loop back-edges — ⭐ BUT NOT ALWAYS (see below)
```

```
⭐⭐ THE BUG: COUNTED LOOPS.

   ⭐ The JIT OMITS the safepoint poll from loops with an `int`
      counter and a known bound, as an optimisation — it "knows"
      the loop terminates.

   ⭐ SO A LONG-RUNNING COUNTED LOOP HAS NO SAFEPOINT POLL AT ALL.

   for (int i = 0; i < 2_000_000_000; i++) { ... }
   ⭐ NO SAFEPOINT until the loop ENDS.
```

```
⭐ THE CONSEQUENCE — AND THIS IS THE IMPORTANT PART:

   ⭐ WHEN GC NEEDS TO PAUSE, IT MUST WAIT FOR EVERY THREAD TO
      REACH A SAFEPOINT.

   ⭐ ONE THREAD IN A COUNTED LOOP BLOCKS THE ENTIRE PAUSE.
   ⭐ ALL OTHER THREADS ARE ALREADY STOPPED, WAITING.

   ⭐ THE GC LOG REPORTS: "Pause Young 3ms"
   ⭐ THE APPLICATION ACTUALLY STOPPED FOR: 800ms

   ⭐⭐ BECAUSE "TIME TO SAFEPOINT" (TTSP) IS NOT COUNTED IN THE
       REPORTED GC PAUSE.
```

```bash
# ⭐ MEASURE IT — this is the flag that reveals the lie
-Xlog:safepoint*:file=/var/log/safepoint.log:time,uptime

# ⭐ Look for:
# Safepoint "G1CollectForAllocation", ⭐ Time since last: 4821 ns,
#   ⭐ Reaching safepoint: 847291042 ns,   ← ⭐ 847 MILLISECONDS TTSP
#   At safepoint: 3102841 ns,               ← 3 ms of actual GC
#   Total: 850393883 ns

# ⭐ And make it fail loudly:
-XX:+SafepointTimeout -XX:SafepointTimeoutDelay=500
# ⭐ Logs which THREAD is failing to reach the safepoint.
```

### The causes and fixes

```
⭐ CAUSE 1: COUNTED LOOPS (int counter, long duration)
   ⭐ FIX: use a `long` counter — ⭐ loops with long counters DO get
      safepoint polls. A one-character change.
   ⭐ Or: -XX:+UseCountedLoopSafepoints (⭐ default since JDK 11 in
      some configurations; verify on yours)

⭐ CAUSE 2: LARGE ARRAY OPERATIONS
   ⭐ System.arraycopy or Arrays.fill on a huge array is a single
      intrinsic with no internal safepoint.
   ⭐ FIX: chunk the operation.

⭐ CAUSE 3: PAGE FAULTS / SWAPPING
   ⭐ A thread faulting on swapped-out memory cannot reach a
      safepoint quickly. ⭐ (Deep Dive 11 §21's lesson: never swap.)

⭐ CAUSE 4: ⭐ CPU THROTTLING (Deep Dive 15 §6)
   ⭐ A FROZEN thread cannot reach a safepoint. ⭐ CFS throttling and
      long TTSP compound each other viciously — and both are
      invisible in the obvious metrics.
```

> **If your p99 latency spikes do not match your GC pause log, measure TTSP.** This is one of the most under-diagnosed causes of JVM latency, and the safepoint log is the only place it appears.

---

## 21. Measuring concurrency and GC

```bash
# ═══ ⭐ CONTENTION AND CONTEXT SWITCHING (§9-10) ═══
vmstat 1
# ⭐ cs column: context switches/sec. ⭐ High + high system time = convoy.
# ⭐ r column: run queue length. > cores = CPU saturation.

pidstat -w -p <pid> 1
# ⭐ cswch/s   = voluntary (blocking on a lock or I/O)
# ⭐ nvcswch/s = involuntary (preempted — CPU contention or throttling)

perf stat -e context-switches,cpu-migrations,cache-misses ./app
```

```bash
# ═══ ⭐ FALSE SHARING (§3) ═══
perf c2c record -a -- sleep 10 && perf c2c report
# ⭐ HITM events = cache lines contended between cores

# ═══ ⭐ LOCK CONTENTION ═══
./profiler.sh -e lock -d 60 -f lock.html <pid>     # Java
go tool pprof http://localhost:6060/debug/pprof/mutex   # ⭐ Go (needs
                                                        #   SetMutexProfileFraction)
```

```bash
# ═══ ⭐ GC (§18, §20) ═══
jstat -gcutil <pid> 1000
# ⭐ S0 S1 E O M CCS  YGC YGCT FGC FGCT GCT
#                     ^^^  ^^^^ ^^^ ^^^^ ^^^
#   ⭐ YGC/YGCT: young collection count and total time
#   ⭐ FGC: ⭐ FULL GC count — should be near ZERO in steady state

# ⭐ The two ratios that matter:
#   ⭐ GC THROUGHPUT = 1 − (GCT / uptime).  ⭐ Target > 95%.
#   ⭐ ALLOCATION RATE = (eden size × YGC) / elapsed.

# ⭐ TIME TO SAFEPOINT (§20) — the one people miss
-Xlog:safepoint*:file=safepoint.log:time,uptime
```

```promql
# ⭐ The alerts
rate(jvm_gc_pause_seconds_sum[5m]) / rate(jvm_gc_pause_seconds_count[5m]) > 0.2
rate(jvm_gc_pause_seconds_count{action="end of major GC"}[10m]) > 0   # ⭐ full GCs
go_gc_duration_seconds{quantile="1"} > 0.01
process_context_switches_involuntary_total                            # ⭐ throttling
```

---

## 22. What an architect takes from this

**1. Sharing a mutable variable between cores costs ~100× more than not sharing it** — before any lock is involved. "Share nothing" is a hardware-level truth, not just an architectural preference, and it is the same principle as stateless services and single-writer partitioning.

**2. False sharing can cost 13× throughput and is invisible in code review.** Two independent variables in one 64-byte cache line behave as one. `perf c2c` finds it; padding fixes it.

**3. x86 is nearly sequentially consistent; ARM is not.** Code with latent data races has "worked" for years because it only ever ran on x86. **Migrating to Graviton or Apple Silicon surfaces them** — run a race detector before the migration, not after.

**4. `volatile` gives visibility and ordering, not atomicity.** `counter++` on a volatile is still broken. And double-checked locking was a published, widely-copied idiom that was simply wrong — **"it looks correct" is worth nothing in concurrent code.**

**5. An uncontended lock costs ~20 ns; a contended one costs 1–10 µs.** That 50–500× cliff is why contention is non-linear and why a lock that is fine at 4 threads collapses at 16.

**6. The Universal Scalability Law says throughput can *decrease* with concurrency.** There is an optimal thread count, connection pool size, and cluster size, and it is usually lower than you would guess. This single curve explains small connection pools, 50–70% utilisation targets, 3–5 node Raft clusters, and single-threaded Redis.

**7. The #1 thread pool bug is blocking work in a pool sized for CPU work.** Separate pools per workload — the bulkhead pattern applied inside a process.

**8. Virtual threads and goroutines make blocking code scalable — until something pins the carrier.** In Java, `synchronized` in a third-party library can deadlock your whole application. **Run with `-Djdk.tracePinnedThreads=full` before adopting them.**

**9. Concurrent GC is paid for with write barriers on every reference store** — typically 5–15% throughput. **Shorter pauses always cost throughput; there is no collector that is best at both.** "Sub-millisecond pauses" should always prompt "and what does it cost?"

**10. GC tuning is mostly allocating less.** After choosing a collector for your pause requirement and sizing the heap, additional flags usually make things worse. Profile allocation with a flame graph; do not guess.

**11. Time-to-safepoint is not counted in reported GC pauses.** A 3 ms pause can stop your application for 800 ms, and only the safepoint log shows it. If your latency spikes do not match your GC log, this is why.

**12. In a container, all of this interacts with cgroups.** CPU throttling freezes threads that then cannot reach safepoints; the runtime must be told its real CPU and memory limits (Deep Dive 15 §12). **The lowest layer and the highest layer are coupled, and debugging requires seeing both.**

---

## Exercises

1. Write a benchmark with two threads incrementing adjacent `long` fields, then add padding. Measure the difference.
2. Run `perf c2c` against a production service. Are there contended cache lines?
3. Explain to a colleague why `volatile int counter; counter++;` is broken.
4. Write out the three-step reordering that breaks double-checked locking, and explain why `volatile` fixes it.
5. Run your test suite under a race detector (`go test -race`, ThreadSanitizer, jcstress). How many races does it find?
6. If you plan an ARM migration, run the race detector first and record what it finds. Estimate the risk.
7. Load-test a service at 1, 2, 4, 8, 16, 32 threads and plot throughput. Where is the peak? Fit the USL and extract α and β.
8. Measure your database connection pool's wait time at different sizes. Find the size where throughput peaks.
9. Audit your thread pools: is any pool doing blocking I/O while sized to the core count?
10. If you use Java virtual threads, run with `-Djdk.tracePinnedThreads=full` under load. What pins?
11. Profile allocation with async-profiler or pprof. What are the top three allocation sites, and can any be eliminated?
12. Compute your GC throughput (`1 − GCT/uptime`). Is it above 95%? How many full GCs in the last day?
13. Enable safepoint logging and measure time-to-safepoint. Does it explain any of your latency outliers?
14. For a containerised JVM or Go service, verify the runtime knows its actual CPU and memory limits, then check whether CFS throttling (Deep Dive 15 §6) correlates with your latency spikes.

---

**This completes the deep dive series.**

**Back to:** [Deep Dives](README.md) · [Chapter 20](../20-performance-engineering.md) · [The Map](../README.md)
