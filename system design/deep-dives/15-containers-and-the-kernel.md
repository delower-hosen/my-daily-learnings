# Deep Dive 15 — Containers and the Kernel

**Prerequisite:** [Chapter 15 — Containers & Kubernetes](../15-containers-and-kubernetes.md)

**What the map said:** *"A container is a process with namespaces, cgroups and a layered filesystem. CPU throttles, memory kills. Always set requests; consider omitting CPU limits."*

**What this deep dive does:** takes apart all eight namespaces and shows what each actually isolates, explains cgroup v2's controllers with the exact files you read in production, traces the CFS quota throttling that produces 100 ms p99 spikes at 30% CPU utilisation, explains why page cache counts against your memory limit and why the JVM used to kill itself in containers, shows overlayfs copy-up and the write cliff it creates, enumerates the container escape surface with real CVEs, and ends with the commands you actually need at 3 AM.

---

## Contents

```
1.  A container is a process — the three mechanisms
2.  Namespaces: all eight
3.  ⭐ The PID namespace and the PID 1 problem
4.  The network namespace, from the inside
5.  cgroup v1 vs v2
6.  ⭐ cpu.max: the CFS quota and why it throttles you
7.  ⭐ Traced scenario — 100 ms p99 spikes at 30% CPU
8.  ⭐ cpu.weight vs cpu.max — requests vs limits
9.  Memory: max, high, low, min
10. ⭐ Page cache accounting — why memory.current lies
11. ⭐ The OOM kill, and exit code 137
12. ⭐ The JVM (and Go, and Node) in a container
13. overlayfs: lower, upper, work, merged
14. ⭐ Copy-up and the write performance cliff
15. Container networking: veth, bridge, CNI
16. ⭐ Capabilities: root, decomposed
17. seccomp
18. User namespaces and rootless containers
19. ⭐ The container escape surface
20. The runtime stack: CRI, containerd, shim, runc
21. Stronger isolation: gVisor, Kata, Firecracker
22. ⭐ Debugging: the commands
23. What an architect takes from this
```

---

## 1. A container is a process — the three mechanisms

There is no "container" object in the kernel. There is a process with three things applied to it.

```
⭐ NAMESPACES   → what the process can SEE
⭐ CGROUPS      → what the process can USE
⭐ UNION FS     → what the process's filesystem LOOKS LIKE
```

```bash
# ⭐ Prove it: a container process is an ordinary process on the host
docker run -d --name demo nginx
ps aux | grep nginx
# ⭐ root  8821  0.0  0.1  10628  6212 ?  Ss  14:22  0:00 nginx: master process

cat /proc/8821/cgroup
# ⭐ 0::/system.slice/docker-4f2a....scope

ls -l /proc/8821/ns/
# ⭐ cgroup -> 'cgroup:[4026532601]'
#    ipc    -> 'ipc:[4026532539]'
#    mnt    -> 'mnt:[4026532537]'
#    net    -> 'net:[4026532542]'
#    pid    -> 'pid:[4026532540]'
#    user   -> 'user:[4026531837]'     ⭐ same as the host — no user ns!
#    uts    -> 'uts:[4026532538]'
```

```
⭐ THE INODE NUMBERS ARE THE NAMESPACE IDENTITY. Two processes in the
   same namespace show the same inode. ⭐ Comparing them is how you
   determine whether two processes are "in the same container".

⭐ AND NOTE: `user` matches the host's. Without a user namespace,
   ⭐ root in the container IS root on the host, constrained only by
      capabilities (§16) and seccomp (§17). That is §19's starting point.
```

---

## 2. Namespaces: all eight

| Namespace | Flag | Isolates | Created by |
|-----------|------|----------|-----------|
| **mnt** | `CLONE_NEWNS` | ⭐ Mount points | Always |
| **pid** | `CLONE_NEWPID` | ⭐ Process IDs | Always (unless `hostPID`) |
| **net** | `CLONE_NEWNET` | ⭐ Interfaces, routes, iptables, ports, sockets | Always (unless `hostNetwork`) |
| **ipc** | `CLONE_NEWIPC` | System V IPC, POSIX message queues | Always (unless `hostIPC`) |
| **uts** | `CLONE_NEWUTS` | Hostname, domain name | Always |
| ⭐ **user** | `CLONE_NEWUSER` | ⭐ UID/GID mapping, **capabilities** | ⭐ Usually NOT (§18) |
| **cgroup** | `CLONE_NEWCGROUP` | The cgroup root the process sees | Usually |
| **time** | `CLONE_NEWTIME` | ⭐ `CLOCK_MONOTONIC`/`BOOTTIME` offsets | Rarely (Linux 5.6+) |

```
⭐ `CLONE_NEWNS` IS NAMED ODDLY because the mount namespace was the
   FIRST one (Linux 2.4.19, 2002) — before anyone imagined there
   would be others. The name stuck.
```

### The time namespace — a niche one worth knowing

```
⭐ Added in Linux 5.6. It offsets CLOCK_MONOTONIC and CLOCK_BOOTTIME
   (NOT CLOCK_REALTIME — Deep Dive 02 §3).

⭐ WHY IT EXISTS: CHECKPOINT/RESTORE (CRIU). If you snapshot a
   container and restore it on another machine hours later, its
   monotonic clock would JUMP FORWARD — breaking every timeout and
   duration measurement inside it.

  ⭐ The time namespace lets the restored container see a continuous
     monotonic clock.

⭐ IT DOES NOT let you fake the wall clock. That remains host-global,
   which is why a container cannot fix a skewed host clock
   (Deep Dive 02 §2).
```

---

## 3. ⭐ The PID namespace and the PID 1 problem

```
⭐ INSIDE the container:  PID 1, 2, 3...
⭐ ON THE HOST:           PID 8821, 8845, 8846...

  ⭐ The SAME PROCESS has two PIDs. The host can see and signal it;
     the container cannot see the host's processes at all.
```

```bash
# Inside
docker exec demo ps aux
# PID  COMMAND
#   1  nginx: master process      ⭐ PID 1 inside
#  29  nginx: worker process

# On the host
ps -ef | grep 'nginx: master'
# root  8821  8799  0 14:22 ?  00:00:00 nginx: master process   ⭐ PID 8821
```

### ⭐ PID 1 is special, and it breaks containers

```
⭐ THE KERNEL TREATS PID 1 DIFFERENTLY IN TWO WAYS:

  1. ⭐ NO DEFAULT SIGNAL HANDLERS.
     A normal process that ignores SIGTERM is still killed by the
     kernel's default action. ⭐ PID 1 IS NOT. If it has not
     installed a handler, ⭐ THE SIGNAL IS SIMPLY DISCARDED.

  2. ⭐ IT MUST REAP ORPHANED CHILDREN.
     When any process's parent dies, its children are reparented to
     PID 1, which must call wait() to reap them.
     ⭐ If PID 1 does not, they become ZOMBIES FOREVER.
```

### Failure 1 — SIGTERM ignored

```
docker stop / kubectl delete pod
  ⭐ 1. SIGTERM is sent to PID 1
  ⭐ 2. Your application has no SIGTERM handler
  ⭐ 3. THE SIGNAL IS DISCARDED. Nothing happens.
  ⭐ 4. After terminationGracePeriodSeconds (30 s default), SIGKILL.

⭐ RESULT: every pod termination takes the full grace period and
   kills the process abruptly. ⭐ In-flight requests are dropped.

⭐ THIS IS A LARGE PART OF WHY CHAPTER 15 §15.8'S GRACEFUL SHUTDOWN
   MATTERS — and why it does not work if your process is PID 1 and
   has no handler.
```

### Failure 2 — zombie accumulation

```
⭐ A shell script as PID 1 that spawns background processes, or an
   application that forks, will accumulate zombies:

     ps aux | grep defunct
     ⭐ [sh] <defunct>   × 40,000

⭐ Each zombie holds a PID slot. Eventually:
     fork(): Resource temporarily unavailable
   ⭐ The container cannot start any new process.
```

### The fixes

```bash
# ⭐ 1. An init process that forwards signals and reaps zombies
docker run --init nginx           # ⭐ injects tini as PID 1
```

```dockerfile
# ⭐ 2. Explicitly
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

```dockerfile
# ⭐ 3. Use exec form so your app IS PID 1, and handle signals in it
CMD ["node", "server.js"]           # ⭐ exec form — node is PID 1
# ❌ CMD node server.js              # ⭐ SHELL form — /bin/sh is PID 1,
#                                       and sh does NOT forward SIGTERM
```

```
⭐ THE SHELL-FORM TRAP IS EXTREMELY COMMON. `CMD npm start` makes
   /bin/sh PID 1; sh spawns node as a child and ⭐ DOES NOT FORWARD
   SIGTERM. Your graceful shutdown handler never runs.
```

---

## 4. The network namespace, from the inside

```
⭐ A network namespace has its OWN:
   • interfaces        • routing table       • iptables/nftables rules
   • port number space • ARP table           • socket table
   • conntrack table   • sysctls (net.*)
```

```bash
# ⭐ Enter a container's network namespace from the host
PID=$(docker inspect -f '{{.State.Pid}}' demo)
nsenter -t $PID -n ip addr
# 1: lo: <LOOPBACK,UP> ...
# ⭐ 2: eth0@if42: <BROADCAST,MULTICAST,UP> mtu 1450
#       inet 10.244.1.5/24
#       ⭐ mtu 1450 ← an overlay network (Deep Dive 12 §19)

nsenter -t $PID -n ss -tlnp      # ⭐ what is listening INSIDE
nsenter -t $PID -n iptables -L -n -v
```

```
⭐ nsenter IS THE MOST UNDER-USED CONTAINER DEBUGGING TOOL.
   It lets you run HOST tools (tcpdump, ss, iptables, dig) inside the
   container's namespaces — ⭐ WITHOUT installing anything in the
   container image.

   ⭐ This is how you debug a distroless or scratch container that has
      no shell and no utilities.
```

```bash
# ⭐ tcpdump inside a container that has no tcpdump
nsenter -t $PID -n tcpdump -i eth0 -nn port 5432
```

---

## 5. cgroup v1 vs v2

```
⭐ cgroup v1: a SEPARATE HIERARCHY PER CONTROLLER.
     /sys/fs/cgroup/cpu/...
     /sys/fs/cgroup/memory/...
     /sys/fs/cgroup/blkio/...
   ⭐ A process could be in DIFFERENT cgroups for different controllers,
      which made coordinated resource decisions (e.g. memory pressure
      affecting I/O) essentially impossible.

⭐ cgroup v2: ONE UNIFIED HIERARCHY.
     /sys/fs/cgroup/...
   ⭐ Every controller applies to the same tree, so the kernel can
      make decisions across resources (pressure stall information,
      memory-aware writeback throttling).
```

```bash
# ⭐ Which version are you on?
stat -fc %T /sys/fs/cgroup/
# ⭐ cgroup2fs   → v2
#    tmpfs       → v1
```

```
⭐ cgroup v2 IS NOW THE DEFAULT on all modern distributions and is
   required by newer Kubernetes features (memory QoS, PSI-based
   eviction). ⭐ If you are still on v1, that is technical debt.
```

### The v2 controllers

```
cpu       ⭐ cpu.max, cpu.weight, cpu.stat
memory    ⭐ memory.max, memory.high, memory.low, memory.min,
             memory.current, memory.stat, memory.events
io        io.max, io.weight, io.stat
pids      ⭐ pids.max  (fork-bomb protection)
cpuset    cpuset.cpus, cpuset.mems  (⭐ CPU pinning, NUMA)
hugetlb, rdma, misc
```

```bash
# ⭐ Find a container's cgroup path
cat /proc/$PID/cgroup
# 0::/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<uid>.slice/cri-containerd-<id>.scope

CG=/sys/fs/cgroup/kubepods.slice/.../cri-containerd-<id>.scope
ls $CG
```

---

## 6. ⭐ cpu.max: the CFS quota and why it throttles you

**The single most important thing in this deep dive.** It explains a class of latency problem that looks impossible.

```bash
cat $CG/cpu.max
# ⭐ 20000 100000
#   ^^^^^ ^^^^^^
#   quota period   (microseconds)

# ⭐ 20,000 µs of CPU time per 100,000 µs period = 0.2 CPU
```

```
⭐ THE MECHANISM:

  ⭐ Every 100 ms (the period), the cgroup's quota is REFILLED.
  ⭐ Threads consume it as they run.
  ⭐ WHEN IT IS EXHAUSTED, EVERY THREAD IN THE CGROUP IS
     ⭐ FROZEN UNTIL THE NEXT PERIOD BEGINS.

  ⭐ NOT SLOWED. FROZEN. Removed from the run queue entirely.
```

### ⭐ Why this is worse than it sounds

```
⭐ THE QUOTA IS CONSUMED BY ALL THREADS TOGETHER, IN PARALLEL.

  Container with limit = 1 CPU  (cpu.max = "100000 100000")
  Application has ⭐ 8 THREADS (a typical JVM or Go service on an
  8-core node).

  ⭐ All 8 threads run simultaneously for 12.5 ms
     → 8 × 12.5 ms = ⭐ 100 ms of CPU time consumed
     → ⭐ THE ENTIRE PERIOD'S QUOTA IS GONE IN 12.5 ms OF WALL TIME

  ⭐ THE CONTAINER IS THEN FROZEN FOR 87.5 ms.
```

```
⭐ THE OBSERVABLE SYMPTOM:

  • ⭐ CPU utilisation reported at 30-40% (you used 100 ms out of a
    possible 800 ms across 8 cores)
  • ⭐ p99 latency spikes of 50-100 ms, in multiples of the period
  • ⭐ No obvious cause — the service is not busy, the database is fine,
    the network is fine
  • ⭐ Adding more replicas does not help, because each one throttles
    identically
```

**This is the mechanism behind an enormous number of "mysterious p99 latency" investigations in Kubernetes.**

### Reading the throttling statistics

```bash
cat $CG/cpu.stat
# usage_usec 48291042
# user_usec 41028471
# system_usec 7262571
# ⭐ nr_periods 128471
# ⭐ nr_throttled 41029           ← throttled in 32% of periods!
# ⭐ throttled_usec 2847193042    ← 2,847 seconds spent frozen
```

```
⭐ THE TWO NUMBERS THAT MATTER:

  ⭐ THROTTLING RATE = nr_throttled / nr_periods
     41,029 / 128,471 = ⭐ 32%
     ⭐ Anything above ~1% is worth investigating.

  ⭐ AVERAGE FREEZE PER THROTTLED PERIOD
     = throttled_usec / nr_throttled
     = 2,847,193,042 / 41,029 = ⭐ 69,394 µs = 69 ms
     ⭐ THAT IS YOUR ADDED LATENCY, directly.
```

```promql
# ⭐ THE ALERT EVERY KUBERNETES CLUSTER SHOULD HAVE
rate(container_cpu_cfs_throttled_periods_total[5m])
  / rate(container_cpu_cfs_periods_total[5m]) > 0.05
```

### ⭐ The historical kernel bug

```
⭐ Before Linux 5.4, the CFS bandwidth controller LEAKED QUOTA to
   per-CPU run queues where it then EXPIRED unused.

  ⭐ RESULT: containers were throttled while using FAR LESS than
     their limit — sometimes 30% of it.

  ⭐ Fixed by Dave Chiluk's patch (merged 5.4, widely backported).
     ⭐ If you are on an older kernel and seeing inexplicable
        throttling, this is likely it.
```

---

## 7. ⭐ Traced scenario — 100 ms p99 spikes at 30% CPU

A realistic incident, traced through the mechanism.

```
SETUP: A Java service in Kubernetes.
       resources.limits.cpu: "1"      → cpu.max = "100000 100000"
       Node has 16 cores.
       ⭐ JVM sees 16 cores → creates 16 GC threads, 16 ForkJoinPool
          threads, and a 200-thread Tomcat pool.
       Traffic: 200 req/s, each request needs ~4 ms of CPU.
```

```
⭐ THE ARITHMETIC:
   200 req/s × 4 ms = 800 ms of CPU per second = ⭐ 0.8 CPU
   Limit is 1 CPU. ⭐ "We are at 80% of our limit. Fine."
```

```
⭐ WHAT ACTUALLY HAPPENS, PERIOD BY PERIOD:

t=0ms    ⭐ New 100 ms period. Quota refilled to 100,000 µs.
         20 requests arrive (200/s → ~20 per 100 ms period).
         ⭐ Tomcat dispatches them across 20 THREADS SIMULTANEOUSLY.

t=0-5ms  ⭐ 20 threads × 4 ms CPU each, running in PARALLEL on
         16 cores → ⭐ 80 ms of CPU consumed in ~5 ms of wall time.

t=5ms    ⭐ A minor GC triggers. 16 GC threads run.
         ⭐ 16 threads × ~1.5 ms = 24 ms of CPU consumed.
         ⭐ QUOTA: 80 + 24 = 104 ms > 100 ms.  ⭐ EXHAUSTED.

t=5ms    ⭐⭐ EVERY THREAD IN THE CONTAINER IS FROZEN.
         ⭐ Including the GC threads, mid-collection.
         ⭐ Including threads that had already finished their work
            and were about to write the response.

t=5-100ms ⭐ 95 MILLISECONDS OF COMPLETE FREEZE.

t=100ms  ⭐ New period. Threads resume.
         ⭐ Requests that arrived during the freeze are now queued.
         The 20 new requests PLUS the backlog now compete.

⭐ OBSERVED:
   • ⭐ CPU utilisation metric: ~0.8 cores → "80%, healthy"
   • ⭐ p50 latency: 6 ms
   • ⭐ p99 latency: ⭐ 104 ms
   • ⭐ nr_throttled / nr_periods: ⭐ 61%
```

### The fixes, in order of effectiveness

```
⭐ 1. REMOVE THE CPU LIMIT (keep the request).
     resources:
       requests: { cpu: "1" }
       ⭐ limits: { }          ← no cpu limit
   ⭐ cpu.weight still guarantees a fair share under contention (§8),
      but there is ⭐ NO HARD QUOTA AND THEREFORE NO FREEZE.
   ⭐ This is the most impactful change, and it is what many large
      Kubernetes operators do.

⭐ 2. TELL THE RUNTIME THE TRUE CPU BUDGET (§12).
     -XX:ActiveProcessorCount=2      (Java)
     GOMAXPROCS via automaxprocs      (Go)
   ⭐ Fewer threads → less parallel quota consumption.

⭐ 3. RAISE THE LIMIT substantially above the average.
   ⭐ A limit must accommodate BURSTS, not the average. A service
      averaging 0.8 CPU may legitimately need a 3-CPU limit.

⭐ 4. SHORTEN THE PERIOD (rarely used, and not exposed by Kubernetes)
     cpu.max = "100000 20000"   → a 20 ms period
   ⭐ Same average, but freezes are at most 20 ms instead of 100 ms.
```

> **The counter-intuitive conclusion: CPU limits can make a service slower and less reliable while making its metrics look healthier.** This is why Chapter 15 §15.6 said to consider omitting them — and this section is the mechanism behind that advice.

---

## 8. ⭐ cpu.weight vs cpu.max — requests vs limits

```
⭐ Kubernetes maps them differently, and the difference is fundamental:

  ⭐ resources.requests.cpu  →  cpu.weight   (PROPORTIONAL SHARE)
  ⭐ resources.limits.cpu    →  cpu.max      (HARD QUOTA)
```

### `cpu.weight` — proportional, and it never freezes

```bash
cat $CG/cpu.weight
# ⭐ 100      (range 1-10000, default 100)
# ⭐ Kubernetes: weight ≈ (millicores / 1000) × 100, roughly
```

```
⭐ HOW IT BEHAVES:

  ⭐ WHEN THE NODE IS NOT CONTENDED: a container may use
     ⭐ AS MUCH CPU AS IS AVAILABLE. Weight is irrelevant.

  ⭐ WHEN THE NODE IS CONTENDED: CPU is divided in PROPORTION
     to weights.

     Container A: weight 200   →  A gets ⭐ 2/3
     Container B: weight 100   →  B gets ⭐ 1/3

  ⭐ NO FREEZING. EVER. A container is simply scheduled less often.
```

```
⭐ THIS IS WHY "REQUESTS WITHOUT LIMITS" WORKS:

   ⭐ requests → scheduling decisions (where the pod fits) AND
                 a guaranteed proportional share under contention
   ⭐ limits   → a hard ceiling enforced by freezing

   ⭐ You get the guarantee WITHOUT the cliff.
```

### The honest counter-arguments

```
⚠ ⭐ ARGUMENTS FOR KEEPING CPU LIMITS:

  1. ⭐ PREDICTABILITY / "noisy neighbour" containment. Without limits,
     a runaway container can consume all spare capacity, making
     other containers' performance vary with unrelated workloads.

  2. ⭐ CAPACITY PLANNING. Limits make it clear what a service is
     allowed to use, which some organisations require.

  3. ⭐ QoS CLASS. A pod is only `Guaranteed` if requests == limits
     for CPU and memory (Chapter 15 §15.6). `Guaranteed` pods are
     evicted last, and get exclusive CPUs under the static CPU manager.

⭐ THE PRAGMATIC POSITION MOST LARGE OPERATORS REACH:
   ⭐ • ALWAYS set CPU requests (accurately)
   ⭐ • ALWAYS set memory requests AND limits, equal
   ⭐ • OMIT CPU limits for latency-sensitive services
   ⭐ • SET CPU limits for batch/background work, where freezing
       is harmless and containment matters
```

---

## 9. Memory: max, high, low, min

cgroup v2 gives four memory knobs, and the distinction between two of them is genuinely valuable.

```bash
cat $CG/memory.max     # ⭐ 536870912   — HARD limit → OOM kill
cat $CG/memory.high    # ⭐ max         — SOFT limit → throttle
cat $CG/memory.low     # 0             — reclaim protection (best effort)
cat $CG/memory.min     # 0             — reclaim protection (guaranteed)
cat $CG/memory.current # 412934144     — ⭐ current usage (see §10!)
```

| File | Behaviour when exceeded |
|------|------------------------|
| ⭐ `memory.max` | ⭐ **OOM kill** a process in the cgroup |
| ⭐ `memory.high` | ⭐ **Throttle** — the process is put under heavy reclaim pressure and slowed, **but not killed** |
| `memory.low` | Reclaim tries to avoid this cgroup below this amount (best effort) |
| `memory.min` | Reclaim will **never** take this cgroup below this amount |

### ⭐ `memory.high` is the under-used one

```
⭐ memory.max is a CLIFF: one byte over and a process dies.

⭐ memory.high is a RAMP: as usage approaches it, the kernel applies
   increasing reclaim pressure and ⭐ THROTTLES THE ALLOCATING PROCESS,
   slowing it down rather than killing it.

  ⭐ A container that briefly spikes above memory.high gets slower.
     A container that briefly spikes above memory.max DIES.
```

```
⭐ THE IDEAL CONFIGURATION:

     memory.high = 90% of the intended limit     ⭐ throttle first
     memory.max  = 100%                          ⭐ kill as a last resort

  ⭐ The process gets back-pressure and a chance to free memory
     or shed load before being killed.
```

```
⚠ ⭐ KUBERNETES DOES NOT EXPOSE memory.high DIRECTLY.
   ⭐ The `MemoryQoS` feature gate (alpha/beta, cgroup v2 only) sets
      memory.high from the memory REQUEST, giving exactly this
      behaviour. ⭐ It is worth knowing about and enabling when it
      reaches your cluster's version — it converts a class of
      OOMKill into a class of slowdown.
```

```bash
cat $CG/memory.events
# low 0
# high 0
# max 12              ⭐ hit the hard limit 12 times
# ⭐ oom 3
# ⭐ oom_kill 3       ← THREE PROCESSES KILLED
```

---

## 10. ⭐ Page cache accounting — why `memory.current` lies

A source of constant confusion in container memory monitoring.

```
⭐ THE PAGE CACHE IS CHARGED TO THE CGROUP THAT FAULTED THE PAGE IN.

  ⭐ So a container that reads a 2 GB file has 2 GB of page cache
     charged against its memory.max.
```

```bash
cat $CG/memory.stat
# ⭐ anon 184729600          ← application heap/stack — CANNOT be reclaimed
# ⭐ file 3891200000         ← PAGE CACHE — CAN be reclaimed
#   kernel_stack 2097152
#   slab 41943040
#   sock 8388608
#   file_mapped 104857600
#   ...
cat $CG/memory.current
# ⭐ 4118932480              ← anon + file + kernel ≈ 3.9 GB
```

```
⭐ SO: memory.current = 3.9 GB against a 4 GB limit LOOKS ALARMING.
   ⭐ But 3.7 GB of it is RECLAIMABLE PAGE CACHE.

  ⭐ When the container needs more anonymous memory, the kernel simply
     EVICTS PAGE CACHE. There is no OOM risk at all.
```

```
⭐ THE NUMBER THAT ACTUALLY PREDICTS AN OOM KILL:

     ⭐ anon + unreclaimable kernel memory
       (kernel_stack + a portion of slab + sock)

  ⭐ NOT memory.current.
```

```promql
# ⭐ THE CORRECT MEMORY ALERT — most dashboards get this wrong
container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
# ⭐ working_set = memory.current − inactive_file
#   i.e. it EXCLUDES easily-reclaimable page cache.
#   ⭐ This is also what Kubernetes uses for eviction decisions.

# ❌ NOT this — it counts reclaimable cache and fires constantly
# container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9
```

```
⭐ THE PRACTICAL CONSEQUENCE: teams see "memory at 95%" on a container
   that is perfectly healthy, raise the limit, and learn nothing.
   ⭐ Alert on WORKING SET, not usage.
```

### ⭐ Page cache is shared between containers with shared layers

```
⭐ Two containers from the same image share the SAME overlayfs lower
   layers, which means they share the SAME PAGE CACHE PAGES for those
   files.

  ⭐ 50 replicas of a 200 MB image do NOT use 10 GB of page cache
     for the image contents — they share it.

  ⭐ THIS IS A REAL AND UNDER-APPRECIATED BENEFIT OF LAYER REUSE,
     and an argument for a common base image across your services.
```

---

## 11. ⭐ The OOM kill, and exit code 137

```
⭐ WHEN memory.max IS REACHED AND RECLAIM CANNOT FREE ENOUGH:

  1. ⭐ The cgroup OOM killer runs — scoped to THIS cgroup only.
     ⭐ Other containers and the host are unaffected.
  2. It scores processes by memory usage (and oom_score_adj).
  3. ⭐ It sends SIGKILL. There is no SIGTERM, no cleanup, no
     graceful shutdown. The process is simply gone.
```

```bash
kubectl describe pod myapp
# Last State:  Terminated
#   ⭐ Reason: OOMKilled
#   ⭐ Exit Code: 137
```

```
⭐ 137 = 128 + 9 = SIGKILL.
   ⭐ (Similarly 143 = 128 + 15 = SIGTERM — a graceful stop.)
```

```bash
# ⭐ The kernel's record, on the node
dmesg -T | grep -i 'killed process\|oom'
# [Thu Sep 12 14:22:03] ⭐ Memory cgroup out of memory: Killed process 8821
#   (java) total-vm:4821904kB, anon-rss:3891200kB, file-rss:24576kB

journalctl -k | grep -i oom
```

### ⭐ The failure mode people miss

```
⭐ THE OOM KILLER PICKS THE LARGEST PROCESS IN THE CGROUP —
   ⭐ WHICH MAY NOT BE PID 1.

  ⭐ If a SIDE process is killed (a worker, a helper), the container
     KEEPS RUNNING in a degraded state.
     ⭐ Kubernetes does not restart it, because PID 1 is alive.
     ⭐ There is no OOMKilled event. The pod looks healthy.

  ⭐ You get a silently broken container.
```

```
⭐ THE DEFENCE: a readiness probe that actually checks the
   application's ability to work (Chapter 15 §15.7), not just that
   the process is alive. ⭐ This is one of the concrete reasons
   readiness must check real functionality.
```

---

## 12. ⭐ The JVM (and Go, and Node) in a container

A whole class of bug caused by runtimes reading host information instead of cgroup limits.

### The historical JVM disaster

```
⭐ BEFORE JDK 8u191 / JDK 10:

  The JVM read /proc/meminfo — ⭐ THE HOST'S TOTAL MEMORY —
  and defaulted the max heap to ~1/4 of it.

  ⭐ A 512 MB container on a 128 GB host:
     ⭐ JVM sizes the heap at 32 GB
     ⭐ Allocates freely
     ⭐ OOM-killed at 512 MB, immediately and repeatedly

  ⭐ And it read the HOST's CPU count for GC threads, ForkJoinPool
     parallelism, and more — creating 64 GC threads in a 1-CPU
     container (§7).
```

### The fix, and the remaining trap

```bash
# ⭐ UseContainerSupport is the DEFAULT since JDK 10 (backported to 8u191).
#   It reads the cgroup limits instead of the host's.
-XX:+UseContainerSupport               # ⭐ default on; verify it is not disabled

# ⭐ Size the heap as a PERCENTAGE of the container limit, not absolutely
-XX:MaxRAMPercentage=75.0
-XX:InitialRAMPercentage=50.0

# ⭐ Override the CPU count the JVM sees — CRITICAL with CPU limits (§7)
-XX:ActiveProcessorCount=2
```

```
⭐⭐ THE TRAP THAT REMAINS: -Xmx DOES NOT COVER ALL JVM MEMORY.

  ⭐ The JVM's total footprint is:
       heap (-Xmx)
     + ⭐ metaspace          (class metadata — unbounded by default!)
     + ⭐ thread stacks      (1 MB × thread count — 200 threads = 200 MB)
     + ⭐ code cache         (JIT-compiled code, up to 240 MB)
     + ⭐ direct byte buffers (NIO, Netty — OUTSIDE the heap)
     + ⭐ GC data structures  (card tables, remembered sets)
     + native libraries, JNI

  ⭐ SETTING -Xmx EQUAL TO THE CONTAINER LIMIT GUARANTEES AN OOM KILL.

⭐ MaxRAMPercentage=75 works because it leaves 25% for all of the above.
   ⭐ For a Netty/direct-buffer-heavy application, 50-60% may be needed.
```

```bash
# ⭐ Find out where the memory actually goes
java -XX:NativeMemoryTracking=summary -XX:+UnlockDiagnosticVMOptions ...
jcmd <pid> VM.native_memory summary
# ⭐ Total: reserved=2048MB, committed=1124MB
#   ⭐ Java Heap (reserved=1024MB, committed=768MB)
#   ⭐ Class (reserved=256MB, committed=132MB)
#   ⭐ Thread (reserved=204MB, committed=204MB)     ← 200 threads
#   ⭐ Code (reserved=248MB, committed=24MB)
```

### ⭐ Go

```
⭐ Go's runtime reads runtime.NumCPU() from the HOST, not the cgroup.

  ⭐ GOMAXPROCS = host core count = 64 on a large node,
     in a container limited to 1 CPU.

  ⭐ RESULT: 64 OS threads competing for a 1-CPU quota → severe
     throttling (§7) and heavy scheduler contention.
```

```go
// ⭐ THE FIX — one import, and it is worth adding to every Go service
import _ "go.uber.org/automaxprocs"
// ⭐ Reads cpu.max at startup and sets GOMAXPROCS accordingly.
```

```bash
# ⭐ And for memory (Go 1.19+): a soft memory limit that makes the GC
#   work harder as you approach it, INSTEAD of being OOM-killed.
GOMEMLIMIT=450MiB      # ⭐ set to ~90% of the container limit
# ⭐ This is Go's equivalent of memory.high (§9) and it is excellent.
```

### ⭐ Node.js

```bash
# ⭐ Node's default old-space heap is ~1.5-4 GB depending on version,
#   INDEPENDENT of the container limit.
NODE_OPTIONS="--max-old-space-size=384"   # ⭐ ~75% of a 512 MB limit

# ⭐ And libuv's thread pool defaults to 4 threads regardless of the
#   CPU limit; raise or lower deliberately:
UV_THREADPOOL_SIZE=4
```

> **Every managed runtime needs to be told the truth about its container.** This is one of the highest-hit-rate checks when a containerised service behaves oddly: does the runtime know its actual CPU and memory budget?

---

## 13. overlayfs: lower, upper, work, merged

```
┌─────────────────────────────────────────────────────────────┐
│ ⭐ merged/   — what the container SEES (the union)           │
├─────────────────────────────────────────────────────────────┤
│ ⭐ upper/    — the WRITABLE layer (all changes land here)     │
├─────────────────────────────────────────────────────────────┤
│ ⭐ lower/    — READ-ONLY image layers, stacked                │
│                layer 3: COPY . /app                          │
│                layer 2: RUN pip install ...                  │
│                layer 1: FROM python:3.12-slim                │
├─────────────────────────────────────────────────────────────┤
│   work/     — internal scratch space for atomic operations   │
└─────────────────────────────────────────────────────────────┘
```

```bash
mount | grep overlay
# overlay on /var/lib/docker/overlay2/<id>/merged type overlay
#   (rw,lowerdir=.../l/ABC:.../l/DEF:.../l/GHI,
#    upperdir=.../diff, workdir=.../work)
#    ⭐ lowerdir is a COLON-SEPARATED STACK, leftmost = topmost
```

### Lookup semantics

```
⭐ READ a file: search upper first, then each lower layer in order.
   The first match wins.

⭐ DELETE a file that exists in a lower layer: you cannot remove it
   from a read-only layer, so overlayfs creates a ⭐ WHITEOUT —
   a character device with major/minor 0/0 in the upper layer that
   masks the lower file.

  ⭐ CONSEQUENCE: `RUN rm -rf /large-thing` in a Dockerfile does NOT
     shrink the image. The files remain in the lower layer; you have
     only added whiteouts. ⭐ This is why multi-stage builds
     (Chapter 15 §15.2) matter — they are the only way to actually
     leave data behind.
```

---

## 14. ⭐ Copy-up and the write performance cliff

```
⭐ MODIFYING A FILE THAT LIVES IN A LOWER LAYER REQUIRES COPYING
   ⭐ THE ENTIRE FILE to the upper layer first. This is COPY-UP.

  ⭐ It happens on the first WRITE, and it copies the WHOLE FILE
     regardless of how many bytes you change.
```

```
⭐ THE ARITHMETIC:

  A 2 GB SQLite database file baked into the image.
  ⭐ The container writes ONE BYTE to it.
  ⭐ overlayfs copies ALL 2 GB to the upper layer before the write
     can proceed.

  ⭐ That single write takes SECONDS and consumes 2 GB of disk.
```

```
⭐ THE WORKLOADS THIS DESTROYS:

  ❌ ⭐ Databases with data files in the image or in the writable layer
  ❌ ⭐ Applications writing large log files to the container filesystem
  ❌ ⭐ Anything doing random writes to large files
  ❌ ⭐ Build caches inside the container
```

### The other overlayfs cost: many small files

```
⭐ EVERY FILE LOOKUP MUST SEARCH EACH LAYER IN TURN until it finds
   a match (or a whiteout).

  ⭐ With 15 image layers, a miss in the upper layer means 15 lookups.

  ⭐ THIS IS WHY node_modules IS PATHOLOGICALLY SLOW IN CONTAINERS:
     tens of thousands of small files, each requiring a multi-layer
     lookup on every access.
```

```
⭐ MITIGATIONS:
   ⭐ 1. USE VOLUMES for anything written heavily.
      A volume BYPASSES overlayfs entirely — it is a bind mount to
      the host filesystem. ⭐ No copy-up, no layer traversal.
      ⭐ THIS IS THE REAL REASON DATABASES NEED VOLUMES — not only
         persistence, but PERFORMANCE.

   ⭐ 2. FEWER LAYERS. Combine RUN commands; use multi-stage builds.

   ⭐ 3. tmpfs for scratch space:
         --tmpfs /tmp:rw,size=256m
      ⭐ Memory-backed, no overlayfs, no disk. (⭐ But it counts
         against the cgroup's memory limit — §10.)

   ⭐ 4. Consider a different storage driver for extreme cases
      (btrfs/zfs snapshots avoid whole-file copy-up), though
      overlay2 is the well-trodden default.
```

---

## 15. Container networking: veth, bridge, CNI

```
     HOST NETWORK NAMESPACE              CONTAINER NETWORK NAMESPACE
  ┌────────────────────────────┐       ┌──────────────────────────┐
  │  eth0 (10.0.1.5)           │       │  ⭐ eth0 (10.244.1.5)     │
  │     │                      │       │      │                   │
  │  ┌──▼──────────┐           │       │      │                   │
  │  │ cni0 bridge │           │       │      │                   │
  │  └──┬──────────┘           │       │      │                   │
  │     │                      │       │      │                   │
  │  ⭐ vethABC123 ◄═══════════╪═══════╪══════┘                   │
  │     (one end of a veth pair)       │  ⭐ the other end         │
  └────────────────────────────┘       └──────────────────────────┘
```

```
⭐ A veth PAIR IS A VIRTUAL CABLE: two interfaces where anything sent
   into one comes out of the other. One end is moved into the
   container's network namespace; the other stays on the host,
   attached to a bridge.
```

```bash
# ⭐ Find which host veth belongs to which container
PID=$(docker inspect -f '{{.State.Pid}}' demo)
nsenter -t $PID -n ip link show eth0
# ⭐ 2: eth0@if42: ...
#                ^^^^ ⭐ the host-side interface is ifindex 42
ip link | grep '^42:'
# ⭐ 42: vethABC123@if2: ... master cni0
```

### Outbound and inbound

```
⭐ OUTBOUND: the bridge routes to the host's eth0, and an
   ⭐ iptables MASQUERADE rule rewrites the source address
   (Deep Dive 12 / Chapter 13 §13.2's NAT).

⭐ INBOUND (published ports): a ⭐ DNAT rule rewrites the destination.

  iptables -t nat -L -n | grep 8080
  ⭐ DNAT tcp dpt:8080 to:10.244.1.5:80
```

### CNI plugins, and the MTU consequence

| Plugin | Mechanism | MTU impact |
|--------|-----------|-----------|
| **Flannel (VXLAN)** | UDP encapsulation | ⭐ −50 bytes → 1450 |
| **Calico (IPIP)** | IP-in-IP | ⭐ −20 bytes → 1480 |
| **Calico (BGP)** | ⭐ Native routing, no encapsulation | ⭐ None — full 1500 |
| **Cilium (eBPF)** | ⭐ eBPF, optional tunnelling | Depends on mode |

```
⭐ EVERY OVERLAY NETWORK REDUCES THE MTU, AND THAT IS THE SOURCE OF
   THE PMTU BLACK HOLE (Deep Dive 12 §19): small requests work,
   large responses hang.

  ⭐ CHECK IT:
     nsenter -t $PID -n ip link show eth0 | grep mtu
```

---

## 16. ⭐ Capabilities: root, decomposed

```
⭐ Linux splits root's powers into ~40 CAPABILITIES. A process can
   hold some and not others.
```

```bash
# ⭐ What does this container actually have?
docker run --rm alpine sh -c 'apk add -q libcap; capsh --print' | grep Current
# ⭐ Current: cap_chown,cap_dac_override,cap_fowner,cap_fsetid,cap_kill,
#   cap_setgid,cap_setuid,cap_setpcap,cap_net_bind_service,cap_net_raw,
#   cap_sys_chroot,cap_mknod,cap_audit_write,cap_setfcap=ep
```

### ⭐ The dangerous ones

| Capability | What it grants |
|-----------|---------------|
| ⭐ `CAP_SYS_ADMIN` | ⭐ **Effectively root.** Mount, pivot_root, many namespace operations. The "new root". |
| ⭐ `CAP_SYS_PTRACE` | ⭐ Attach to and read/write other processes' memory |
| ⭐ `CAP_SYS_MODULE` | ⭐ **Load kernel modules** — a complete host compromise |
| ⭐ `CAP_DAC_READ_SEARCH` | ⭐ Bypass file read permission checks; enables `open_by_handle_at` escapes |
| ⭐ `CAP_SYS_RAWIO` | ⭐ Direct I/O port and `/dev/mem` access |
| ⭐ `CAP_NET_RAW` | ⭐ Raw sockets → **ARP spoofing, packet crafting** on the pod network |
| ⭐ `CAP_NET_ADMIN` | Reconfigure networking, including iptables |
| ⭐ `CAP_SETUID`/`CAP_SETGID` | ⭐ Change UID — defeats "run as non-root" |

```
⭐ CAP_NET_RAW IS THE ONE PEOPLE MISS. It is in Docker's DEFAULT set
   and Kubernetes' default. ⭐ It allows a compromised pod to ARP-spoof
   other pods on the same node and intercept their traffic.
   ⭐ Most hardening baselines drop it.
```

### The correct configuration

```yaml
securityContext:
  ⭐ runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  ⭐ allowPrivilegeEscalation: false   # ⭐ blocks setuid binaries entirely
  ⭐ readOnlyRootFilesystem: true      # ⭐ forces volumes/tmpfs for writes
  capabilities:
    ⭐ drop: ["ALL"]                   # ⭐ START FROM ZERO
    add: ["NET_BIND_SERVICE"]         # ⭐ only if you must bind < 1024
  seccompProfile:
    ⭐ type: RuntimeDefault            # ⭐ NOT the default — you must set it (§17)
```

```
⭐ `allowPrivilegeEscalation: false` SETS THE no_new_privs BIT.
   ⭐ Once set, no descendant process can gain capabilities through
      a setuid binary — ever. ⭐ It is cheap, has almost no
      compatibility cost, and blocks a whole escalation path.

⭐ AND `NET_BIND_SERVICE` IS USUALLY UNNECESSARY: bind to port 8080
   inside the container and map it at the Service. ⭐ Then you need
   no capabilities at all.
```

---

## 17. seccomp

```
⭐ seccomp-bpf filters SYSTEM CALLS using a BPF program attached to
   the process. It is the second layer after capabilities.
```

```
⭐ Docker's DEFAULT PROFILE blocks ~44 of ~350 syscalls, including:
     keyctl            ⭐ (kernel keyring — used in real escapes)
     add_key, request_key
     mount, umount2    ⭐ (unless CAP_SYS_ADMIN)
     reboot, kexec_load
     ⭐ ptrace         (allowed again in newer versions)
     bpf, perf_event_open
     userfaultfd       ⭐ (used to win kernel race conditions)
     clone with CLONE_NEWUSER
```

```
⭐⭐ THE CRITICAL KUBERNETES FACT:

   ⭐ KUBERNETES DOES NOT APPLY A SECCOMP PROFILE BY DEFAULT
      (historically `Unconfined`).

   ⭐ You MUST set it explicitly:

        securityContext:
          seccompProfile:
            type: RuntimeDefault

   ⭐ Or cluster-wide via the SeccompDefault feature gate on the
      kubelet (GA since 1.27), which makes RuntimeDefault the default.
      ⭐ ENABLE IT. Most clusters have not.
```

```json
// ⭐ A custom profile, for a hardened workload
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    { "names": ["read","write","open","close","stat","mmap","fstat",
                "epoll_wait","accept4","futex","clock_gettime"],
      "action": "SCMP_ACT_ALLOW" }
  ]
}
```

```bash
# ⭐ Discover which syscalls your application actually uses
strace -f -c -o /tmp/syscalls.txt ./myapp
# ⭐ Or generate a profile automatically with the Security Profiles Operator
```

---

## 18. User namespaces and rootless containers

```
⭐ THE PROBLEM: without a user namespace, ⭐ UID 0 IN THE CONTAINER
   IS UID 0 ON THE HOST. Only capabilities and seccomp stand between
   a container escape and full host root.
```

```
⭐ USER NAMESPACES MAP IDs:

   container UID 0     →  ⭐ host UID 100000  (an unprivileged user)
   container UID 1     →  host UID 100001
   ...
   container UID 65535 →  host UID 165535

  ⭐ The process believes it is root. It has all capabilities
     ⭐ WITHIN ITS NAMESPACE. On the host it is an ordinary
     unprivileged user who owns nothing.
```

```bash
cat /proc/$PID/uid_map
# ⭐ 0  100000  65536
#   ^  ^^^^^^  ^^^^^
#   |  |       └─ range size
#   |  └───────── first host UID
#   └──────────── first container UID
```

```
⭐ THE SECURITY BENEFIT IS SUBSTANTIAL: a container escape lands you
   as an unprivileged host user, not as root. ⭐ Several historical
   container escape CVEs are neutralised entirely by user namespaces.
```

```
⭐ STATUS:
   • ⭐ Podman is rootless by default
   • ⭐ Docker supports rootless mode (dockerd-rootless)
   • ⭐ Kubernetes: the `UserNamespaces` feature gate (beta in 1.30+)
     via `hostUsers: false` in the pod spec

⚠ ⭐ THE COMPLICATIONS:
   • ⭐ Volume ownership — files written by container-UID 0 are owned
     by host UID 100000, which confuses shared volumes
   • Some workloads genuinely need real privileges
   • Performance overhead in some filesystem operations
```

> **User namespaces are the strongest single isolation improvement available**, and adoption is still low. If your platform supports `hostUsers: false`, it is worth the volume-permission work.

---

## 19. ⭐ The container escape surface

What actually lets an attacker get from inside a container to the host, ranked by how often it appears in real environments.

### ⭐ 1. `privileged: true` — no isolation at all

```yaml
securityContext:
  ⭐ privileged: true      # ⭐ ALL capabilities, all devices, no seccomp,
                          #    no AppArmor. Effectively root on the host.
```

```bash
# ⭐ A one-line escape from a privileged container:
mkdir /tmp/h && mount /dev/sda1 /tmp/h && chroot /tmp/h
# ⭐ You are now root on the host filesystem.
```

**There is essentially no legitimate reason for `privileged: true` in application workloads.** Some CNI/CSI/monitoring DaemonSets genuinely need it; nothing else should.

### ⭐ 2. Mounting the container runtime socket

```yaml
volumeMounts:
  - name: docker-sock
    ⭐ mountPath: /var/run/docker.sock
```

```bash
# ⭐ Trivial escape — ask the daemon to start a privileged container
curl -s --unix-socket /var/run/docker.sock -X POST \
  'http://localhost/containers/create' \
  -H 'Content-Type: application/json' \
  -d '{"Image":"alpine","Cmd":["sh"],"HostConfig":{"Privileged":true,
       "Binds":["/:/host"]}}'
# ⭐ You now have a privileged container with the host root mounted.
```

**Mounting the Docker/containerd socket is equivalent to granting root on the node.** CI runners and "build in cluster" setups do it constantly.

### ⭐ 3. `hostPID`, `hostNetwork`, `hostIPC`

```
⭐ hostPID: true     → see and ⭐ signal/ptrace ALL host processes
⭐ hostNetwork: true → the host's network stack; ⭐ can bind any port,
                       read all traffic, reach anything reachable from
                       the node (including cloud metadata — Chapter 17 §17.5)
⭐ hostIPC: true     → access host shared memory
```

### ⭐ 4. hostPath mounts

```yaml
volumes:
  - name: bad
    hostPath:
      ⭐ path: /                    # ⭐ the entire host filesystem
      # or /proc, /sys, /var/lib/kubelet, /etc/kubernetes
```

```
⭐ /var/lib/kubelet contains service account tokens for EVERY pod
   on the node. ⭐ Mounting it is a cluster-wide credential compromise.
```

### ⭐ 5. Kernel vulnerabilities

```
⭐ THE SHARED KERNEL IS THE FUNDAMENTAL LIMIT (Chapter 15 §15.1).

  ⭐ Dirty COW (CVE-2016-5195)        — write to read-only memory
  ⭐ Dirty Pipe (CVE-2022-0847)       — overwrite read-only files,
                                        including host binaries via
                                        overlayfs page cache
  ⭐ runc (CVE-2019-5736)             — overwrite the host's runc binary
                                        from inside a container
  ⭐ runc (CVE-2024-21626)            — leaked file descriptor allows
                                        access to the host filesystem
  ⭐ cgroups v1 release_agent escapes  — with CAP_SYS_ADMIN
```

```
⭐ THE DEFENCE IS NOT "DO NOT HAVE BUGS". It is:
   ⭐ • PATCH the kernel and the runtime promptly (runc CVEs in
       particular are exploited quickly)
   ⭐ • Reduce the syscall surface (seccomp, §17)
   ⭐ • Drop capabilities (§16)
   ⭐ • Use user namespaces (§18)
   ⭐ • For genuinely untrusted workloads, use stronger isolation (§21)
```

### The audit

```bash
# ⭐ Find the dangerous pods in your cluster
kubectl get pods -A -o json | jq -r '
  .items[] | select(
    .spec.hostNetwork == true or .spec.hostPID == true or
    .spec.hostIPC == true or
    (.spec.containers[]?.securityContext?.privileged == true) or
    (.spec.volumes[]? | select(.hostPath != null))
  ) | "\(.metadata.namespace)/\(.metadata.name)"'
```

```yaml
# ⭐ Enforce it — Pod Security Admission (built in since 1.25)
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    ⭐ pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
```

```
⭐ THE `restricted` PROFILE BLOCKS: privileged, hostPath, hostNetwork,
   hostPID, hostIPC, privilege escalation, running as root, and
   ⭐ REQUIRES seccomp RuntimeDefault and dropping ALL capabilities.

⭐ Turning it on for application namespaces is one of the highest-value
   security changes available in Kubernetes, and it is three labels.
```

---

## 20. The runtime stack: CRI, containerd, shim, runc

```
  ┌──────────────┐
  │   kubelet    │
  └──────┬───────┘
         │ ⭐ CRI (gRPC)
  ┌──────▼───────┐
  │  containerd  │   ⭐ image pull, snapshot management, CRI server
  └──────┬───────┘
         │
  ┌──────▼────────────┐
  │ containerd-shim   │  ⭐ ONE PER CONTAINER. Stays alive.
  │                   │  ⭐ Owns stdio, reports exit status, and lets
  └──────┬────────────┘     containerd RESTART WITHOUT KILLING CONTAINERS
         │
  ┌──────▼───────┐
  │     runc     │  ⭐ sets up namespaces + cgroups, execs the process,
  └──────┬───────┘     ⭐ THEN EXITS
         │
  ┌──────▼───────┐
  │ your process │  ⭐ reparented to the shim
  └──────────────┘
```

```
⭐ THE SHIM IS THE PIECE PEOPLE DO NOT KNOW ABOUT, and it explains
   a useful property: ⭐ you can restart or upgrade containerd
   WITHOUT killing running containers, because the shim — not
   containerd — is the container's parent.

⭐ AND runc EXITS IMMEDIATELY after setup. ⭐ So `ps` showing no runc
   process is normal, not a sign of a problem.
```

```
⭐ THE OCI SPECIFICATIONS make this pluggable:
   • ⭐ Image spec   — the layer/manifest format
   • ⭐ Runtime spec — config.json describing namespaces, cgroups,
                       mounts, capabilities, seccomp

   ⭐ Any OCI-compliant runtime can replace runc: crun (C, faster),
      gVisor's runsc, Kata's containerd-shim-kata-v2, youki (Rust).
      ⭐ This is what makes §21 a configuration change rather than
         a platform migration.
```

---

## 21. Stronger isolation: gVisor, Kata, Firecracker

For genuinely untrusted workloads, where a shared kernel is unacceptable.

### gVisor (runsc)

```
⭐ A USER-SPACE KERNEL. The "Sentry" intercepts the container's
   syscalls and implements most of Linux itself, in Go, in user space.

  ⭐ Only a small, restricted set of real host syscalls is ever made.

✅ ⭐ Dramatically reduced kernel attack surface
✅ Fast startup (it is still a process, not a VM)
❌ ⭐ ~2× syscall overhead — bad for syscall-heavy workloads (I/O)
❌ ⭐ Incomplete Linux compatibility — some applications simply fail
```

### Kata Containers

```
⭐ EACH POD RUNS IN ITS OWN LIGHTWEIGHT VM, with its own kernel.

✅ ⭐ TRUE hardware-enforced isolation — a kernel exploit stays in
   the guest
✅ ⭐ Full Linux compatibility (it IS Linux)
❌ Higher memory overhead (a kernel per pod)
❌ Slower startup (~100-500 ms)
❌ Requires nested virtualisation on cloud VMs, or bare metal
```

### Firecracker

```
⭐ A minimal VMM (virtual machine monitor) written in Rust,
   purpose-built for serverless.

  ⭐ ~125 ms boot time, ~5 MB memory overhead per microVM.
  ⭐ Deliberately minimal device model — no BIOS, no PCI, no USB —
     which is both why it is fast and why its attack surface is small.

⭐ THIS IS WHAT AWS LAMBDA AND FARGATE RUN ON. When Chapter 14 §14.3
   says serverless gives you isolation, ⭐ THIS IS THE MECHANISM.
```

```yaml
# ⭐ Selecting a runtime is a RuntimeClass — a per-pod choice
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
---
apiVersion: v1
kind: Pod
spec:
  ⭐ runtimeClassName: gvisor
```

```
⭐ THE ARCHITECTURAL POINT: isolation strength is a PER-WORKLOAD
   DECISION, not a cluster-wide one.

  ⭐ Run your own trusted services on runc (fast, full compatibility).
  ⭐ Run customer-supplied code, CI jobs, or untrusted plugins on
     gVisor or Kata.

  ⭐ If you are building a platform that executes user-provided code,
     ⭐ THIS IS NOT OPTIONAL — namespaces and cgroups were never
        designed as a security boundary against a determined attacker.
```

---

## 22. ⭐ Debugging: the commands

```bash
# ═══ ⭐ FIND THE CONTAINER'S PID AND CGROUP ═══
PID=$(docker inspect -f '{{.State.Pid}}' <name>)
# or, in Kubernetes:
crictl inspect --output go-template --template '{{.info.pid}}' <container-id>

cat /proc/$PID/cgroup
CG=/sys/fs/cgroup$(cat /proc/$PID/cgroup | cut -d: -f3)
```

```bash
# ═══ ⭐ CPU THROTTLING — check this FIRST for latency problems (§6) ═══
cat $CG/cpu.max            # ⭐ quota period
cat $CG/cpu.stat           # ⭐ nr_throttled / nr_periods
cat $CG/cpu.pressure       # ⭐ PSI: some avg10=12.34 → 12% of time stalled

# ⭐ PSI (Pressure Stall Information) is the best single signal:
cat $CG/cpu.pressure       # ⭐ CPU contention
cat $CG/memory.pressure    # ⭐ memory reclaim pressure
cat $CG/io.pressure        # ⭐ I/O stall
# ⭐ "some avg10=25.00" means 25% of the last 10 s had at least one
#   task stalled on that resource. ⭐ Far more actionable than
#   utilisation percentages.
```

```bash
# ═══ ⭐ MEMORY (§9-11) ═══
cat $CG/memory.max
cat $CG/memory.current
cat $CG/memory.stat | head -20     # ⭐ anon vs file — the key distinction
cat $CG/memory.events              # ⭐ oom_kill count
dmesg -T | grep -i 'killed process'
```

```bash
# ═══ ⭐ NETWORK — run HOST tools inside the container's namespace (§4) ═══
nsenter -t $PID -n ss -tanp
nsenter -t $PID -n ip addr
nsenter -t $PID -n ip route
nsenter -t $PID -n tcpdump -i eth0 -nn -c 100
nsenter -t $PID -n cat /etc/resolv.conf    # ⭐ (needs -m for the mount ns)

# ⭐ All namespaces at once, with a host shell:
nsenter -t $PID -a /bin/sh
```

```bash
# ═══ ⭐ SECURITY POSTURE ═══
grep -E 'CapPrm|CapEff|CapBnd|NoNewPrivs|Seccomp' /proc/$PID/status
# ⭐ CapEff: 00000000a80425fb     → decode with: capsh --decode=00000000a80425fb
# ⭐ NoNewPrivs: 1                 → allowPrivilegeEscalation: false ✓
# ⭐ Seccomp: 2                    → 0=disabled ❌, 2=filter mode ✓
```

```bash
# ═══ ⭐ FILESYSTEM (§13-14) ═══
mount | grep overlay | tr ',' '\n' | grep -E 'lowerdir|upperdir'
du -sh /var/lib/docker/overlay2/<id>/diff    # ⭐ how big is the writable layer?

# ═══ ⭐ DEBUGGING A DISTROLESS CONTAINER (no shell, no tools) ═══
kubectl debug -it <pod> --image=nicolaka/netshoot --target=<container>
# ⭐ Ephemeral container sharing the target's namespaces.
#   ⭐ This is the correct way to debug a minimal image.
```

```bash
# ═══ ⭐ NODE-LEVEL OVERVIEW ═══
systemd-cgtop          # ⭐ live cgroup resource usage, top-style
crictl ps -a
crictl stats
crictl logs --tail 100 <id>
```

---

## 23. What an architect takes from this

**1. A container is a process with namespaces, cgroups and a union filesystem.** There is no container object in the kernel — which is exactly why the isolation is weaker than a VM's, and why §19 exists.

**2. CFS quota throttling is the mechanism behind a large class of "mysterious p99 latency" in Kubernetes.** An 8-threaded service with a 1-CPU limit can exhaust its quota in 12 ms and freeze for 88 ms, while reporting 30% CPU utilisation. **`nr_throttled / nr_periods` should be on every dashboard.**

**3. CPU requests and limits do fundamentally different things.** Requests become `cpu.weight` — a proportional share with no cliff. Limits become `cpu.max` — a hard quota enforced by freezing every thread. **Set requests always; omit CPU limits for latency-sensitive services.**

**4. `memory.current` includes reclaimable page cache and will alarm you for no reason.** Alert on **working set**, not usage. And `memory.high` (throttle) is far better than `memory.max` (kill) where your platform exposes it.

**5. Every managed runtime must be told the truth about its container.** The JVM, Go and Node all historically read host CPU and memory. `MaxRAMPercentage`, `automaxprocs` and `GOMEMLIMIT` are not optimisations — they prevent OOM kills and throttling.

**6. `-Xmx` does not cover metaspace, thread stacks, code cache or direct buffers.** Setting it equal to the container limit guarantees an OOM kill.

**7. PID 1 does not get default signal handlers.** `CMD npm start` makes `/bin/sh` PID 1, which does not forward SIGTERM — so your graceful shutdown never runs and every deploy drops requests. Use exec form, or `--init`.

**8. overlayfs copy-up copies the entire file on first write.** A one-byte write to a 2 GB file copies 2 GB. **Volumes exist for performance as much as persistence.**

**9. Kubernetes does not apply a seccomp profile by default.** `seccompProfile: RuntimeDefault` and `capabilities: drop: [ALL]` are two lines that remove most of the syscall and privilege attack surface.

**10. Mounting the container runtime socket is equivalent to granting root on the node.** So is `privileged: true`, `hostPID`, and a `hostPath` of `/` or `/var/lib/kubelet`. **Enforce Pod Security Admission `restricted` on application namespaces — it is three labels.**

**11. Namespaces and cgroups were never designed as a security boundary against a determined attacker.** For untrusted code — customer plugins, CI jobs, multi-tenant execution — use gVisor, Kata or Firecracker. Isolation strength is a per-workload `RuntimeClass` decision.

**12. `nsenter` and ephemeral debug containers let you use host tooling inside a container with no shell.** This is the single most useful container debugging technique and it is not widely known.

---

## Exercises

1. Find a production container's cgroup path and read `cpu.stat`. Compute its throttling rate and average freeze duration.
2. Add the CFS throttling alert to your cluster. How many workloads exceed 5%?
3. Take a latency-sensitive service with a CPU limit. Remove the limit (keeping the request) and measure the p99 change.
4. For a Java service, run `jcmd VM.native_memory summary` and account for the gap between `-Xmx` and the container's memory limit.
5. Check whether your Go services use `automaxprocs` and set `GOMEMLIMIT`. What is `GOMAXPROCS` reporting inside a 1-CPU container?
6. Compare `container_memory_usage_bytes` and `container_memory_working_set_bytes` for a file-heavy container. Explain the difference.
7. Verify that your containers use exec-form `CMD` and that your application handles SIGTERM. Test by sending SIGTERM and watching for graceful shutdown.
8. Measure the cost of copy-up: write one byte to a 1 GB file in a container's writable layer, then repeat on a volume.
9. Audit your cluster for `privileged`, `hostPath`, `hostPID`, `hostNetwork` and runtime-socket mounts. Justify each one that remains.
10. Check whether `seccompProfile: RuntimeDefault` is applied to your workloads. If not, enable the `SeccompDefault` kubelet feature gate on a test node.
11. Decode a container's `CapEff` with `capsh --decode`. Which capabilities does it hold that it does not need?
12. Enable Pod Security Admission `restricted` on a non-production namespace. What breaks, and why?
13. Use `nsenter` to run `tcpdump` inside a distroless container that has no shell.
14. Read `cpu.pressure`, `memory.pressure` and `io.pressure` for a busy container. Which resource is it actually stalled on?

---

**Next in this series:** Deep Dive 16 — Concurrency, Memory Models and GC

**Back to:** [Deep Dives](README.md) · [Chapter 15](../15-containers-and-kubernetes.md) · [The Map](../README.md)
