# Chapter 21 — Sockets, Ports, Ephemeral Ranges, and the Kernel's Connection Tables

---

## 1. Why This Matters

Chapters 18–20 covered the transport protocols; this chapter consolidates the transport layer by examining
how the kernel *manages sockets and connections at scale* — and, crucially, the **finite resources** that
bound how many connections a system can hold. This is where the recurring theme of the book — "finite kernel
resources are DoS targets" (Chapters 1 §5.4, 3 §5, 14 §4.2, 19–20) — becomes fully concrete and
quantifiable.

For a cloud security engineer, this matters because:

1. **Ephemeral port exhaustion** is a real, subtle failure that looks like an outage or an attack. A host
   making many outbound connections (a busy proxy, a service calling an API heavily, a load test) runs out
   of source ports, and new connections fail — a self-inflicted DoS you must recognize and prevent.
2. **Connection-table (conntrack) limits** bound how many connections a stateful firewall/NAT/security
   group can track (Chapters 14, 19, 37, 76); exhausting them drops connections. NAT gateway connection
   limits (Chapter 14) are the cloud manifestation.
3. **File-descriptor limits** (Chapter 3 §5.4) bound how many sockets a process can hold; exhaustion is a
   silent DoS. These three limits — ephemeral ports, conntrack entries, and fds — are the connection-scaling
   ceilings that attacks and load both hit.
4. **Understanding the 4-tuple's role in connection uniqueness** (Chapter 3 §3) explains why connection
   capacity is what it is, and why certain scaling patterns (many connections to one destination) hit
   limits sooner.

The core idea: **a connection is uniquely identified by its 4-tuple (source IP:port, dest IP:port), and the
kernel tracks each active connection in tables that consume finite resources — ephemeral source ports (for
outbound connections), connection-tracking entries (for stateful filtering/NAT), and file descriptors (per
socket). Each is a finite ceiling that high scale and attacks both hit, causing connection failures that
look like outages or DoS.** This chapter quantifies those ceilings and their defenses, completing the
transport-layer picture as a set of exhaustible resources.

---

## 2. Prerequisites

- Chapter 3 (sockets, the 4-tuple, ephemeral ports, fd limits, `ss`/`lsof`), Chapters 19–20 (TCP state,
  conntrack, buffers).
- Chapter 14 (NAT tables), forward Chapters 37 (conntrack) and 76 (security groups) — the connection-table
  concept recurs there.
- Chapter 1 §5.4 (finite resources as DoS targets — the theme this chapter concentrates).

---

## 3. Mental Model

**Every connection is a 4-tuple the kernel must track, and tracking consumes three finite resources: an
ephemeral source port (for outbound connections), a connection-tracking table entry (for stateful
filtering/NAT), and a file descriptor (per socket). The 4-tuple's uniqueness rules determine capacity, and
exhausting any of the three resources causes connection failures.**

```
   A connection is unique by its 4-TUPLE:  (src IP, src port, dst IP, dst port)   (Chapter 3 §3)

   Three finite resources per connection:
     1. EPHEMERAL SOURCE PORT  -- for OUTBOUND connections (the kernel picks a source port ~32768-60999)
     2. CONNTRACK TABLE ENTRY  -- for STATEFUL filtering/NAT (Chapters 14, 19, 37, 76)
     3. FILE DESCRIPTOR        -- one per socket (Chapter 3 §5.4)

   Exhaust any one -> new connections FAIL:
     - ephemeral ports exhausted -> "cannot assign requested address" (EADDRNOTAVAIL)
     - conntrack table full       -> packets dropped (nf_conntrack: table full)
     - file descriptors exhausted -> "too many open files" (EMFILE) (Chapter 3 §8.3)
```

Three ideas:

1. **The 4-tuple defines connection uniqueness and thus capacity.** Two connections can share three of the
   four tuple elements but must differ in at least one. For *outbound* connections from one host to one
   destination (same dst IP:port, same src IP), the only varying element is the **source port** — so the
   ~28,000 ephemeral ports cap the number of simultaneous connections to a *single* destination. This is
   the ephemeral-port-exhaustion ceiling.
2. **The kernel tracks connections in finite tables.** Conntrack (for stateful filtering/NAT) has a maximum
   entry count; the fd table has a per-process limit; the ephemeral port range is finite. Each is a
   distinct ceiling.
3. **High scale and attacks hit the same ceilings.** A legitimate high-connection workload and a
   connection-flood attack both consume these resources — so the defenses (raising limits appropriately,
   connection reuse, port range tuning, conntrack sizing) serve both scaling and DoS resistance. This is
   the "finite resources are DoS targets" theme made quantitative.

**The security framing:** connection capacity is bounded by three finite resources, and exhaustion — whether
from load, a bug (connection leak — Chapter 3 §Solutions 3.7), or an attack (connection flood, slow-client
hoarding — Chapters 19–20) — causes connection failures indistinguishable from an outage. A security
engineer must know these ceilings, recognize their exhaustion signatures, size them appropriately, and
defend them (connection reuse, limits, edge absorption). The cloud adds managed ceilings (NAT gateway
connection limits — Chapter 14) with the same failure modes.

---

## 4. Fundamentals

### 4.1 The 4-tuple and connection uniqueness (capacity math)

A connection is identified by `(src IP, src port, dst IP, dst port)` (Chapter 3 §3). The uniqueness
requirement — no two active connections share all four — drives capacity:

```
   INBOUND to a server (dst = server IP:443, fixed): the src IP and src port vary across many clients.
     -> a server can hold MANY connections on ONE listening port (Chapter 3 §4.4) -- capacity is high,
        bounded by fds/memory/conntrack, NOT by the tuple (each client contributes a unique src IP:port).

   OUTBOUND from a host to ONE destination (src IP fixed, dst IP:port fixed):
     -> only the SOURCE PORT can vary -> at most ~28,000 simultaneous connections (the ephemeral range)
        to that single destination. THIS is the ephemeral-port-exhaustion ceiling.

   OUTBOUND to MANY destinations: each distinct dst IP:port gives a fresh ~28,000-port space
     -> capacity is much higher (the constraint is per-destination).
```

The key insight: **ephemeral port exhaustion is a *per-destination* limit for outbound connections.** A
host making 30,000 simultaneous connections to *one* API endpoint exhausts its source ports to that
destination; the same host making connections spread across many destinations does not. This is why a busy
reverse proxy or a service hammering a single downstream API hits this limit, and why connection reuse
(keep-alive, pooling) is the primary defense.

### 4.2 Ephemeral ports and their exhaustion

When a host makes an outbound connection, the kernel assigns a **source port** from the ephemeral range
(Chapter 3 §4.5). On Linux the default is `32768–60999` (≈28,000 ports), configurable via
`net.ipv4.ip_local_port_range`. Exhaustion:

```
   A host opens many simultaneous outbound connections to ONE destination:
     each needs a unique source port -> the ~28,000-port range fills ->
     new connections fail with EADDRNOTAVAIL ("cannot assign requested address").

   Aggravating factors:
     - TIME_WAIT (Chapter 19 §4.5): closed connections hold their tuple for 2*MSL (~60-120s), so ports
       are not immediately reusable -> effective capacity is lower under high connection churn.
     - short-lived connections (no keep-alive): each request opens+closes a connection, cycling ports
       rapidly and piling up TIME_WAIT.
```

This is a common, confusing failure: a service that worked fine at moderate load suddenly fails to make new
outbound connections under higher load or churn, with `EADDRNOTAVAIL` — not an attack, but a resource
ceiling. Defenses (§11): **connection reuse (HTTP keep-alive, connection pooling)** — the primary fix, since
reusing connections avoids consuming a new port per request; **widen the ephemeral range**
(`ip_local_port_range`); **tune TIME_WAIT reuse** (`tcp_tw_reuse` for outbound — carefully); and **spread
across destinations** (multiple downstream IPs). In the cloud, this manifests at NAT gateways (which do PAT,
so the NAT gateway's ports to a destination are the shared limit — Chapter 14 §5's ~55,000-per-destination
limit).

### 4.3 The connection-tracking table (conntrack)

Stateful filtering and NAT (Chapters 14, 19, 37, 76) require tracking each connection in the **conntrack
table**, which is finite:

```
   Each tracked connection = one conntrack entry (the tuple + state + timeout).
   The table has a maximum: net.netfilter.nf_conntrack_max (e.g. 262144, sized from RAM).
   Table full -> "nf_conntrack: table full, dropping packet" -> new connections DROPPED.

   Attacks/load that exhaust it: connection floods, SYN floods (before SYN cookies), slow-client hoarding,
     or simply high legitimate connection volume.
```

Conntrack exhaustion is a DoS on the *stateful filter itself* — when the table is full, the firewall drops
new connections, denying service (Chapters 14 §4.2, 19 §4.6). The cloud equivalent is the **NAT gateway's
and stateful security group's connection limits** — AWS security groups track connections (Chapter 76), and
the NAT gateway has a ~55,000-per-destination limit (Chapter 14). Defenses: **size the table**
(`nf_conntrack_max`), **tune timeouts** (shorter timeouts free entries faster), **SYN cookies** (avoid
tracking half-open floods — Chapter 19), and in the cloud, **distribute load** (per-AZ NAT gateways, VPC
endpoints to bypass NAT for AWS services) and **connection reuse**.

### 4.4 File descriptors (the per-socket limit)

Each socket consumes a **file descriptor** (Chapter 3 §4.5, §5.4), and processes have fd limits:

```
   Per-process soft/hard limits: ulimit -n / LimitNOFILE (systemd) / process rlimits.
   System-wide: /proc/sys/fs/file-max.
   Exhaustion: new accept()/open()/socket() -> EMFILE ("too many open files") (Chapter 3 §8.3).
```

fd exhaustion is a silent DoS: a service that has hit its fd limit appears "up" but cannot accept new
connections (Chapter 3 §5.4). Causes: high connection volume (legitimate), connection leaks (CLOSE_WAIT
accumulation — Chapters 3 §Solutions 3.7, 19 §4.5), or connection-hoarding attacks (Slowloris, slow-read —
Chapters 19–20). Defenses: **raise `LimitNOFILE`** appropriately, **fix leaks**, **connection limits**, and
**monitor fd usage** as a leading indicator (Chapter 3 §11).

### 4.5 The three ceilings together (the connection-capacity picture)

These three limits interact to bound total connection capacity:

```
   For a SERVER (inbound connections):
     - fds: one per connection (the usual first ceiling for many connections)
     - conntrack: one entry per connection (if stateful filtering is on)
     - memory: per-connection buffers (Chapter 20 §4.4)
     - listening port: NOT a limit (many connections share one listening port -- §4.1)
     -> capacity ≈ min(fd limit, conntrack limit, memory/buffer capacity)

   For a CLIENT/PROXY (outbound connections to one destination):
     - ephemeral ports: ~28,000 per destination (the usual ceiling to a single destination)
     - fds, conntrack, memory: as above
     -> capacity to one destination ≈ min(ephemeral ports, fds, conntrack, memory)
```

The practical upshot: **know which ceiling you will hit for your workload.** A server holding many client
connections hits fds/conntrack/memory (not ports); a client/proxy connecting heavily to one destination
hits ephemeral ports first. Sizing means raising the relevant limit and reducing consumption (connection
reuse). Under attack, the same ceilings are the targets, so the defenses double as DoS resistance. This is
the quantitative form of "finite resources are DoS targets."

### 4.6 SO_REUSEADDR, SO_REUSEPORT, and connection management

Two socket options relevant to connection management and occasionally to security (Chapter 3 §Solutions
3.8, 3.15):

- **SO_REUSEADDR:** allows binding an address that has a socket in TIME_WAIT (Chapter 19 §4.5) — needed for
  quick service restarts (avoiding "address already in use").
- **SO_REUSEPORT:** allows *multiple* sockets to bind the *same* address:port, with the kernel
  load-balancing incoming connections across them — used for multi-process/multi-worker servers and
  zero-downtime restarts. Security-relevant edge case: during a botched rolling restart, both old and new
  processes can be live on the same port, serving inconsistent versions (Chapter 3 §Solutions 3.8).

These are connection-management tools, not primarily security features, but understanding them prevents
misdiagnosing restart/binding issues and the SO_REUSEPORT version-mixing surprise.

---

## 5. Deep Technical Explanation: Connection Capacity as a Security Boundary

The three ceilings (§4.5) make connection capacity a *quantifiable security boundary* — and understanding
this quantitatively is what distinguishes an engineer who can reason about DoS resistance from one who
guesses.

**The core equations:**

```
   Server connection capacity  ≈ min( fd_limit, conntrack_max, memory / per_conn_buffer )
   Client/proxy capacity/dest  ≈ min( ephemeral_ports (~28k), fd_limit, conntrack_max, memory/buffer )
```

The security reasoning that flows from these:

1. **Every DoS/scaling limit is one of these ceilings.** Slowloris/slow-read (Chapters 19–20) exhaust fds
   and memory (holding connections open); SYN floods exhaust half-open state (Chapter 19); connection floods
   exhaust conntrack and fds; a proxy hammering one backend exhausts ephemeral ports. When you analyze "how
   many connections before this fails?", you compute the min of these ceilings. When you analyze an attack,
   you identify which ceiling it targets.

2. **Raising a limit and reducing consumption are the two levers.** You either raise the ceiling (more fds,
   larger conntrack table, wider port range, more memory) or reduce per-connection consumption (connection
   reuse to avoid new ports/entries, smaller buffers to fit more connections, timeouts to free resources
   faster). Both are DoS-resistance measures. Connection reuse (keep-alive, pooling) is especially powerful
   because it reduces consumption of *all three* ceilings simultaneously — one reused connection instead of
   many short-lived ones consumes one port, one conntrack entry, one fd, across many requests.

3. **The reverse proxy changes the capacity math (again).** As in Chapter 20 §5, a reverse proxy absorbs
   many client connections efficiently (its event-driven model raises the effective fd ceiling it can
   handle) and maintains a small, reused pool to the backend (avoiding backend port/fd/conntrack
   exhaustion) — so the proxy shifts the capacity ceiling from the fragile backend to the resilient
   front-end. This is the third time the reverse proxy appears as a capacity/DoS control (Chapters 3 §12,
   20 §5, here), because it addresses per-connection resource consumption at the architecture level.

4. **The cloud provides and bounds these ceilings.** NAT gateway connection limits (~55,000 per
   destination — Chapter 14), stateful security group connection tracking (Chapter 76), and instance
   networking limits are the managed ceilings; VPC endpoints (bypassing NAT for AWS services), per-AZ NAT
   gateways, and connection reuse are how you stay under them. ELB/ALB absorb the client-side connection
   volume (like a reverse proxy). Knowing the cloud ceilings (they are documented limits) is part of
   capacity and DoS planning.

The unifying insight, completing the transport layer: **a connection is a 4-tuple the kernel tracks using
finite resources (ephemeral ports, conntrack entries, fds, buffers), and connection capacity — the boundary
between "handling load" and "failing" — is the minimum of those ceilings. Every connection-based DoS
targets one of them, and every defense either raises a ceiling or reduces consumption, with connection
reuse and reverse-proxy absorption being the highest-leverage because they reduce consumption across
multiple ceilings at once.** This is the quantitative culmination of the "finite resources are DoS targets"
theme (Chapters 1, 3, 14, 19, 20). Note again that all of this is *availability* (a CIA property) —
confidentiality/integrity remain TLS's job (Chapters 19–20); connection-table security is about keeping the
service reachable under load and attack.

---

## 6. Internals: Observing Connection Resources

### 6.1 The three ceilings and current usage

```bash
# 1. Ephemeral port range and usage:
$ cat /proc/sys/net/ipv4/ip_local_port_range          # e.g. 32768 60999 (~28k ports)
$ ss -tan state established | awk '{print $4}' | grep -oE ':[0-9]+$' | sort -u | wc -l   # ports in use
$ ss -s                                                # socket summary (TCP/UDP counts, TIME_WAIT, etc.)

# 2. Conntrack table:
$ cat /proc/sys/net/netfilter/nf_conntrack_max        # the table limit (e.g. 262144)
$ conntrack -C 2>/dev/null                             # current entry count
$ dmesg | grep -i 'nf_conntrack: table full'          # exhaustion events (dropped packets!)

# 3. File descriptors:
$ ulimit -n                                            # per-process soft limit
$ cat /proc/sys/fs/file-max                            # system-wide
$ ls /proc/<PID>/fd | wc -l                            # a process's current fd count (Chapter 3)
```

These three commands per resource give you the full connection-capacity picture: how close each ceiling is
to exhaustion. Monitoring these (§11) is how you catch exhaustion — from load, a leak, or an attack — before
it causes an outage.

### 6.2 Reproduce ephemeral port exhaustion (safely)

```bash
# Open many simultaneous connections to ONE destination and watch ports fill (§4.2):
$ python3 - <<'PY'
import socket
socks=[]
try:
    while True:
        s=socket.socket(); s.connect(('127.0.0.1', 8080)); socks.append(s)  # a local listener on 8080
except OSError as e:
    print(f"failed after {len(socks)} connections: {e}")   # EADDRNOTAVAIL or EMFILE (which ceiling first?)
PY
# The error tells you which ceiling you hit: EADDRNOTAVAIL (ports) or EMFILE (fds) -- often fds first
# unless ulimit is high, then ports to a single destination.
```

This shows *which ceiling you hit first* for your configuration — a key diagnostic (raise the binding one).

### 6.3 Connection reuse (the primary defense) observed

```bash
# WITHOUT keep-alive: each request opens+closes a connection (piles up TIME_WAIT, consumes ports):
$ for i in $(seq 1 100); do curl -s -o /dev/null http://localhost:8080/; done
$ ss -tan state time-wait | wc -l          # many TIME_WAIT (ports held ~60-120s)

# WITH keep-alive/reuse: one connection serves many requests (one port, one fd, one conntrack entry):
$ curl -s -o /dev/null http://localhost:8080/ --keepalive-time 60 [multiple requests on one connection]
# Connection pooling in your HttpClient / DB driver / SDK is the production form of this.
```

Connection reuse (keep-alive, pooling) is the highest-leverage defense (§5): it reduces consumption of
ports, conntrack entries, and fds simultaneously. Your HttpClient, database driver, and cloud SDK should
pool connections — verifying they do is a real check.

### 6.4 Cloud connection ceilings

```bash
# NAT gateway connection metrics (the cloud ephemeral-port/conntrack ceiling — Chapter 14):
$ aws cloudwatch get-metric-statistics --namespace AWS/NATGateway \
    --metric-name ActiveConnectionCount ...    # approaching the ~55k-per-destination limit?
$ aws cloudwatch get-metric-statistics --namespace AWS/NATGateway \
    --metric-name ErrorPortAllocation ...      # port allocation failures = exhaustion (Chapter 14)
```

The NAT gateway's `ErrorPortAllocation` metric is the cloud ephemeral-port-exhaustion signal (Chapter 14
§Solutions 14.7) — the same ceiling, managed and monitored via CloudWatch.

---

## 7. Real-World Example: Connection Ceilings in the Ledger Environments

**Ledger's connection-capacity considerations:**

- **The app hammering one downstream (ephemeral port exhaustion):** if Ledger's app makes many simultaneous
  connections to one external API (Stripe) or one internal service without connection pooling, it can
  exhaust ephemeral ports to that destination (§4.2). The fix is **connection pooling** in the HttpClient/
  SDK (reuse connections across requests) — the primary defense, which Ledger must verify is enabled (a
  common oversight: creating a new HttpClient per request defeats pooling and exhausts ports/sockets — a
  well-known .NET foot-gun).
- **NAT gateway limits (System B):** Ledger's private-subnet instances share the NAT gateway's
  per-destination connection limit (~55,000 — Chapter 14). Heavy connections to one external destination
  can hit it (`ErrorPortAllocation`). Fixes: **connection reuse**, **VPC endpoints** for AWS services
  (bypass the NAT gateway entirely — Chapter 14, 77), and **per-AZ NAT gateways** to distribute load.
- **Server-side fds/conntrack (inbound):** Ledger's app instances hold client connections (via the ALB), so
  fd and conntrack limits bound how many they handle; the ALB/CloudFront absorb the bulk of client
  connections (the reverse-proxy capacity shift — §5), and Ledger sizes `LimitNOFILE`, conntrack, and
  buffers appropriately.
- **Attack ceilings:** connection-flood and slow-client attacks (Chapters 19–20) target these same ceilings;
  the edge (ALB/CloudFront + Shield) absorbs the volume, and Ledger's timeouts/limits/monitoring defend the
  backend.
- **Monitoring:** Ledger monitors fd usage, conntrack utilization, TIME_WAIT counts, and NAT gateway
  connection metrics as leading indicators — exhaustion of any looks like an outage, and early detection
  prevents it.

The Ledger takeaway: **connection capacity is bounded by three finite ceilings (ephemeral ports, conntrack
entries, fds), which both high load and connection-based attacks hit — defended by connection reuse (the
highest-leverage, reducing all three), reverse-proxy/ALB absorption of client connections, VPC endpoints
and per-AZ NAT gateways to distribute the cloud ceilings, appropriate limit sizing, and monitoring.** The
most common self-inflicted version is a service that fails to pool connections and exhausts ephemeral ports/
sockets to a downstream — a bug that masquerades as an attack or outage, which knowing these ceilings lets
you diagnose instantly.

---

## 8. Hands-On Demonstration

### LAB 21.1 — Connection Ceilings: Exhaustion and Defense

**Objective.** Observe the three connection-capacity ceilings (ephemeral ports, conntrack, fds), reproduce
ephemeral-port/fd exhaustion, identify which ceiling binds first, and demonstrate connection reuse as the
primary defense.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Inventory the three ceilings.*

```bash
cat /proc/sys/net/ipv4/ip_local_port_range          # ephemeral port range (~28k)
cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo "conntrack not loaded"
ulimit -n                                            # fd soft limit
ss -s                                                # current socket summary
```

Record each ceiling and current usage — the connection-capacity picture (§4.5).

*Step 2 — Reproduce exhaustion and identify the binding ceiling.*

```bash
# Start a local listener:
docker run -d --name target --network host nicolaka/netshoot sh -c 'python3 -m http.server 8080' 2>/dev/null || \
  (python3 -m http.server 8080 &)
sleep 2
# With a LOW fd limit, fds bind first (EMFILE):
( ulimit -n 64; python3 - <<'PY'
import socket
s=[]
try:
    while True:
        c=socket.socket(); c.connect(('127.0.0.1',8080)); s.append(c)
except OSError as e: print(f"LOW ulimit: failed after {len(s)}: {e}")   # EMFILE (fds)
PY
)
# With a HIGH fd limit, ephemeral ports to ONE destination bind first (EADDRNOTAVAIL):
( ulimit -n 200000 2>/dev/null; python3 - <<'PY'
import socket
s=[]
try:
    while True:
        c=socket.socket(); c.connect(('127.0.0.1',8080)); s.append(c)
except OSError as e: print(f"HIGH ulimit: failed after {len(s)}: {e}")  # EADDRNOTAVAIL (ports) ~28k
PY
)
```

**Expected:** with a low `ulimit`, you hit `EMFILE` (fds) first at ~60; with a high `ulimit`, you hit
`EADDRNOTAVAIL` (ephemeral ports) around ~28,000 connections to the single destination. **This shows which
ceiling binds first depends on configuration** (§4.5) — the key diagnostic.

*Step 3 — Observe conntrack (if loaded).*

```bash
sudo modprobe nf_conntrack 2>/dev/null
conntrack -C 2>/dev/null                              # current entries
cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null   # the limit
# Under the connection load above, watch entries climb toward the limit (table-full = dropped packets).
```

*Step 4 — Connection reuse (the primary defense).*

```bash
# WITHOUT reuse: 100 separate connections (100 ports, 100 fds, 100 conntrack entries, 100 TIME_WAITs):
for i in $(seq 1 100); do curl -s -o /dev/null http://localhost:8080/; done
ss -tan state time-wait | wc -l                      # ~100 TIME_WAIT (ports held)
# WITH reuse: one connection, many requests (1 port, 1 fd, 1 entry):
curl -s -o /dev/null http://localhost:8080/ http://localhost:8080/ http://localhost:8080/  # reuses the connection
ss -tan state time-wait | wc -l                      # far fewer new TIME_WAITs
```

**Expected:** connection reuse dramatically reduces consumption of all three ceilings — one reused
connection vs many short-lived ones. This is why HttpClient/SDK/DB connection pooling is the primary defense
(§5).

**Security implications.** Write down: (a) the three ceilings (ephemeral ports, conntrack, fds) and that
capacity ≈ their minimum; (b) which binds first depends on configuration (raise the binding one); (c)
connection reuse reduces all three simultaneously — the highest-leverage defense; (d) exhaustion looks like
an outage/attack, so monitoring these is essential; (e) the cloud manifests these as NAT gateway limits
(`ErrorPortAllocation`) and SG connection tracking.

**Cleanup.**
```bash
docker rm -f target 2>/dev/null; pkill -f 'http.server 8080' 2>/dev/null
```

---

## 9. Security Implications

- **Connection capacity is bounded by three finite ceilings** — **ephemeral source ports** (~28k
  per-destination, for outbound), **conntrack table entries** (for stateful filtering/NAT), and **file
  descriptors** (per socket) — plus per-connection memory (Chapter 20). Capacity ≈ the minimum of these.
- **The 4-tuple's uniqueness makes ephemeral-port exhaustion a per-destination limit** for outbound
  connections — a host hammering one destination without connection reuse exhausts its source ports there.
- **High load and connection-based attacks hit the same ceilings** — Slowloris/slow-read (fds, memory), SYN
  floods (half-open state), connection floods (conntrack, fds), single-destination hammering (ports) — so
  defenses double as DoS resistance ("finite resources are DoS targets," quantified).
- **Connection reuse (keep-alive, pooling) is the highest-leverage defense** — it reduces consumption of
  ports, conntrack entries, and fds simultaneously; failing to pool (e.g. new HttpClient per request) is a
  common self-inflicted exhaustion.
- **The reverse proxy/ALB shifts the capacity ceiling** from the fragile backend to the resilient front-end
  (the third appearance of this control — Chapters 3, 20).
- **The cloud provides and bounds these ceilings** — NAT gateway connection limits (~55k/destination,
  `ErrorPortAllocation`), stateful SG connection tracking — with the same exhaustion failure modes; VPC
  endpoints and per-AZ NAT gateways distribute them.
- **Exhaustion looks like an outage/attack** — monitoring the three ceilings is essential for both scaling
  and security.

---

## 10. Attack Scenarios

1. **Connection-flood DoS** (§4.3, §4.4): open many connections to exhaust conntrack entries and/or fds →
   new connections dropped. Defense: limits, conntrack sizing, SYN cookies, edge absorption.
2. **Slow-client hoarding (Slowloris/slow-read)** (Chapters 19–20): hold connections open to exhaust fds/
   memory. Defense: timeouts, connection limits, reverse-proxy absorption.
3. **Ephemeral-port exhaustion (self-inflicted or induced)** (§4.2): a service (or an attacker forcing it)
   making many connections to one destination without reuse exhausts source ports → `EADDRNOTAVAIL`.
   Defense: connection pooling, wider port range, spread destinations.
4. **NAT gateway connection exhaustion** (§4.3, Chapter 14): exhaust the NAT gateway's per-destination
   connection limit → `ErrorPortAllocation`, dropped connections. Defense: connection reuse, VPC endpoints,
   per-AZ NAT gateways.
5. **fd-leak-induced exhaustion (CLOSE_WAIT)** (Chapter 3 §Solutions 3.7, Chapter 19): an app bug leaking
   sockets exhausts fds → silent DoS. Defense: fix leaks, monitor fd usage.
6. **SYN flood** (Chapter 19): exhaust half-open state / conntrack. Defense: SYN cookies, edge scrubbing.

All target one of the finite ceilings; identifying which is the diagnostic, and the defense either raises
the ceiling or reduces consumption (§5).

---

## 11. Defensive Techniques

- **Use connection reuse everywhere** — HTTP keep-alive, connection pooling in HttpClient/DB drivers/cloud
  SDKs — the highest-leverage defense, reducing consumption of ports, conntrack entries, and fds
  simultaneously. Verify your clients pool (a new HttpClient/connection per request is a classic bug).
- **Size the three ceilings appropriately** — `LimitNOFILE`/`ulimit -n` (fds), `nf_conntrack_max` and
  timeouts (conntrack), `ip_local_port_range` (ephemeral ports) — raised for the workload but bounded to
  prevent unbounded resource use.
- **Front with a reverse proxy / ALB** that absorbs client connections efficiently and maintains a small,
  reused backend pool — shifting the capacity ceiling to the resilient front-end (Chapters 3 §12, 20 §5).
- **In the cloud: use VPC endpoints** (bypass the NAT gateway for AWS services), **per-AZ NAT gateways**
  (distribute the per-destination limit), and **connection reuse** — to stay under NAT gateway/SG connection
  limits (Chapter 14).
- **Fix connection/socket leaks** (CLOSE_WAIT — Chapter 3 §Solutions 3.7) and enforce **connection limits
  and timeouts** (Chapters 19–20) to defend against hoarding attacks.
- **Monitor all three ceilings** — fd usage (`/proc/PID/fd`), conntrack utilization (`conntrack -C` vs
  `nf_conntrack_max`), ephemeral port usage / TIME_WAIT counts (`ss -s`), and NAT gateway metrics
  (`ActiveConnectionCount`, `ErrorPortAllocation`) — as leading indicators, since exhaustion looks like an
  outage.
- **Use SYN cookies and edge scrubbing** (Chapters 19, 85) for flood attacks that target half-open state
  and volume.

---

## 12. Production Architecture

Connection ceilings and their management, VPS vs cloud:

```
 CEILING                  DEFENSE                          SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------   -------------------   -------------------------
 ephemeral ports          connection reuse + wider range    pooling + tuning      pooling + VPC endpoints + per-AZ NAT
 conntrack table          sizing + timeouts + SYN cookies   nf_conntrack tuning   SG limits + NAT GW limits + Shield
 file descriptors         LimitNOFILE + fix leaks + limits  systemd LimitNOFILE   instance sizing + ALB absorption
 per-conn memory (Ch20)   buffer sizing + reverse proxy     kernel tuning + nginx ALB/CloudFront + instance sizing
 client connection volume reverse proxy / LB absorption     nginx                 ALB/CloudFront + Shield
 monitoring               ss/conntrack/fd metrics           node metrics          CloudWatch NAT/SG/instance metrics
```

The architectural principle, completing the transport layer: **connection capacity is the minimum of finite
resource ceilings (ephemeral ports, conntrack entries, fds, memory), and the architecture manages them by
reducing consumption (connection reuse — the highest leverage), raising ceilings appropriately, absorbing
client connections at a resilient reverse-proxy/ALB front-end, distributing cloud ceilings (VPC endpoints,
per-AZ NAT gateways), and monitoring each ceiling as a leading indicator.** This is the quantitative
foundation of DoS resistance and capacity planning combined — the two overlap precisely because both are
bounded by the same finite connection resources. In the cloud, these become documented, monitored managed
limits (NAT gateway, SG, instance networking) that you stay under via reuse, endpoints, and distribution.
The recurring theme reaches its quantitative conclusion: know your ceilings, reduce consumption, absorb at
the edge, and monitor — for both load and attack.

---

## 13. Common Mistakes

1. **Not pooling connections** (new HttpClient/connection per request) — exhausting ephemeral ports/sockets
   to a downstream; the classic self-inflicted DoS.
2. **Not knowing which ceiling binds first** — raising the wrong limit (e.g. raising fds when ports are the
   constraint, or vice versa).
3. **Ignoring conntrack limits** — table-full drops new connections silently (Chapter 14).
4. **fd/socket leaks (CLOSE_WAIT)** — silent DoS (Chapter 3 §Solutions 3.7).
5. **Exposing the backend directly** without a reverse proxy/ALB to absorb client connection volume
   (Chapters 3, 20).
6. **Not using VPC endpoints** — routing all AWS-service traffic through the NAT gateway, hitting its
   connection limit (Chapter 14).
7. **Not monitoring the ceilings** — missing the leading indicators; exhaustion presents as an outage.
8. **Confusing capacity (availability) with confidentiality** — these ceilings are availability/DoS; TLS is
   separate (Chapters 19–20).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Outbound connections fail with EADDRNOTAVAIL | ephemeral port exhaustion (to one destination) | `ss -s`; TIME_WAIT count; `ip_local_port_range`; enable connection pooling |
| New connections fail with EMFILE | fd exhaustion (leak or high volume) | `ls /proc/PID/fd \| wc -l` vs `ulimit -n`; check CLOSE_WAIT (Chapter 3) |
| Firewall dropping new connections under load | conntrack table full | `conntrack -C` vs `nf_conntrack_max`; `dmesg \| grep 'table full'` |
| Cloud: intermittent outbound failures under load | NAT gateway connection limit / port allocation | CloudWatch `ErrorPortAllocation`, `ActiveConnectionCount`; VPC endpoints, per-AZ NAT (Chapter 14) |
| Service "up" but not accepting connections | fd exhaustion or backlog full | fd count; `ss` LISTEN Send-Q; connection limits |
| Many TIME_WAIT, ports scarce | short-lived connections without reuse | enable keep-alive/pooling; `tcp_tw_reuse` (carefully); widen range |
| "Address already in use" on restart | previous socket in TIME_WAIT | SO_REUSEADDR (Chapter 3 §Solutions 3.15) |

---

## 15. Practical Lab

Lab 21.1 is in §8. Register it in the lab index. Extension: instrument a service that makes outbound calls
without connection pooling, reproduce ephemeral-port exhaustion under load, then add connection pooling and
measure the dramatic reduction in port/fd/conntrack consumption and the elimination of the exhaustion — a
direct demonstration that connection reuse is the highest-leverage connection-resource defense, and the fix
for the most common self-inflicted connection DoS.

---

## 16. Exercises

### Concept questions

**21.1** Explain how the 4-tuple determines connection uniqueness and why ephemeral-port exhaustion is a
per-destination limit for outbound connections but not a limit for a server's inbound connections.

**21.2** Name the three finite connection-capacity ceilings, what each bounds, and the error each produces
on exhaustion.

**21.3** Why is connection reuse the highest-leverage defense, and which ceilings does it reduce?

**21.4** Explain how high load and connection-based attacks hit the same ceilings, and how this makes
capacity planning and DoS resistance overlap.

**21.5** Explain the connection-capacity equations (server and client/proxy) and how to determine which
ceiling binds first for a given workload.

### Debugging problems

**21.6** A service that worked fine suddenly fails to make outbound connections under higher load, with
`EADDRNOTAVAIL`. Diagnose and fix.

**21.7** A service is "up" but stops accepting new connections; `EMFILE` in logs. Diagnose (two causes) and
fix.

**21.8** A cloud fleet behind a NAT gateway has intermittent outbound failures to one external API under
load. Diagnose and give three fixes (relate to Chapter 14).

### Security scenarios

**21.9** Design connection-resource management and DoS resistance for a high-throughput service, addressing
all three ceilings and the reverse-proxy/edge role.

**21.10** Explain how an attacker could exhaust each of the three ceilings and the defense for each,
distinguishing self-inflicted from attacker-induced exhaustion.

### Architecture questions

**21.11** Explain how the reverse proxy/ALB shifts the connection-capacity ceiling and why this is a
recurring capacity/DoS control (bridge to Chapters 3 §12, 20 §5).

**21.12** Explain the cloud connection ceilings (NAT gateway, SG connection tracking) and how VPC endpoints
and per-AZ NAT gateways manage them (bridge to Chapters 14, 77).

### Hands-on exercises

**21.13** Inventory the three ceilings on a host and determine which binds first for a single-destination
outbound workload.

**21.14** Reproduce ephemeral-port and fd exhaustion, observing which error appears under different
`ulimit` settings.

**21.15** Demonstrate connection reuse reducing port/fd/conntrack consumption vs short-lived connections.

### Interview questions

**21.16** "What limits how many connections a server (or a client to one destination) can have?"

**21.17** "A service fails with 'cannot assign requested address' under load. What's happening and how do
you fix it?"

**21.18** "Why is connection pooling a security/availability control?"

**21.19** "What is conntrack exhaustion, and how does it manifest in the cloud?"

**21.20** "How do capacity planning and DoS resistance relate for connection-based services?"

---

## 17. Summary

- **A connection is a 4-tuple** `(src IP, src port, dst IP, dst port)`, and the kernel tracks each active
  connection using **three finite resources**: **ephemeral source ports** (~28k per-destination, for
  outbound), **conntrack table entries** (for stateful filtering/NAT), and **file descriptors** (per
  socket) — plus per-connection memory (Chapter 20).
- **Connection capacity ≈ the minimum of these ceilings.** For a *server* (inbound), the binding ceiling is
  usually fds/conntrack/memory (many connections share one listening port); for a *client/proxy* (outbound
  to one destination), it is usually **ephemeral ports (~28k), a per-destination limit** driven by the
  4-tuple's uniqueness.
- **High load and connection-based attacks hit the same ceilings** — Slowloris/slow-read (fds, memory), SYN
  floods (half-open state), connection floods (conntrack, fds), single-destination hammering (ports) — so
  **capacity planning and DoS resistance overlap**, and defenses serve both. This is the quantitative form
  of "finite resources are DoS targets" (Chapters 1, 3, 14, 19, 20).
- **Connection reuse (keep-alive, pooling) is the highest-leverage defense** — it reduces consumption of
  ports, conntrack entries, and fds *simultaneously*; failing to pool (new HttpClient/connection per
  request) is the classic self-inflicted exhaustion.
- **The reverse proxy/ALB shifts the capacity ceiling** from the fragile backend to the resilient
  front-end (third appearance — Chapters 3, 20).
- **The cloud provides and bounds these ceilings** — NAT gateway per-destination connection limits (~55k,
  `ErrorPortAllocation`), stateful SG connection tracking — managed via connection reuse, VPC endpoints, and
  per-AZ NAT gateways.
- **Exhaustion looks like an outage/attack** — monitor all three ceilings as leading indicators. All of
  this is *availability* (CIA); confidentiality/integrity remain TLS's job.

---

## 18. Knowledge Check

1. What are the three connection-capacity ceilings and the error each produces? (§4, §5)
2. Why is ephemeral-port exhaustion a per-destination limit for outbound but not for a server's inbound? (§4.1)
3. Why is connection reuse the highest-leverage defense? (§5)
4. What is connection capacity approximately equal to? (§4.5, §5)
5. How do high load and attacks hit the same ceilings? (§5)
6. How does the reverse proxy shift the capacity ceiling? (§5)
7. What are the cloud manifestations of these ceilings? (§4.3, §6.4, Chapter 14)
8. What error indicates ephemeral-port exhaustion, and conntrack exhaustion? (§3, §4.2, §4.3)
9. Why do capacity planning and DoS resistance overlap? (§5)
10. What is the classic self-inflicted connection DoS? (§5, §7)

---

## 19. Further Exploration

- `man ss`, `man conntrack`; and the kernel networking sysctls (`ip_local_port_range`, `nf_conntrack_max`,
  `tcp_tw_reuse`) — the tunable ceilings.
- Read about the .NET `HttpClient` connection-pooling foot-gun (creating a new HttpClient per request
  exhausting sockets) — the canonical self-inflicted ephemeral-port exhaustion.
- AWS NAT gateway limits and CloudWatch metrics (`ErrorPortAllocation`, `ActiveConnectionCount`) — the cloud
  ceilings (Chapter 14); and VPC endpoints (Chapter 77) as the bypass.
- Reproduce ephemeral-port and fd exhaustion (Lab 21.1) and observe which binds first under different
  configurations.
- Revisit Chapters 3 (§5, §8.3), 14 (§4.2), 19 (§4.6), 20 (§4.4) — this chapter is the quantitative
  consolidation of the connection-resource-exhaustion theme.

---

## Solutions

### 21.1
A connection is uniquely identified by its 4-tuple `(src IP, src port, dst IP, dst port)` — no two active
connections may share all four. For a **server's inbound** connections, the destination is fixed (the
server's IP and listening port), but each client contributes a distinct source IP and/or source port, so
the tuples are unique across many clients — the server can hold a very large number of connections on one
listening port, bounded by fds/conntrack/memory rather than by the tuple. For **outbound** connections from
one host to **one** destination, the source IP is fixed and the destination IP:port is fixed, so the only
element that can vary to keep tuples unique is the **source port** — and there are only ~28,000 ephemeral
ports, capping simultaneous connections to that single destination. This is why ephemeral-port exhaustion is
a **per-destination** limit for outbound connections (spreading across many destinations gives each a fresh
port space, raising capacity) but not a limit for a server's inbound connections (where the varying client
addresses provide uniqueness). The 4-tuple's uniqueness requirement is thus the direct cause of the
per-destination outbound ceiling.

### 21.2
The three finite connection-capacity ceilings: (1) **Ephemeral source ports** — bound the number of
simultaneous *outbound* connections to a single destination (~28,000, `ip_local_port_range`); exhaustion
produces **EADDRNOTAVAIL** ("cannot assign requested address"). (2) **Conntrack table entries** — bound the
number of connections a stateful firewall/NAT/security group can track (`nf_conntrack_max`); exhaustion
produces dropped packets and the kernel log "nf_conntrack: table full, dropping packet" (and, in the cloud,
NAT gateway `ErrorPortAllocation`). (3) **File descriptors** — bound the number of open sockets per process
(`ulimit -n`/`LimitNOFILE`); exhaustion produces **EMFILE** ("too many open files"). Plus per-connection
**memory** (send/receive buffers — Chapter 20) as a fourth practical ceiling. Connection capacity is
approximately the minimum of these, and which binds first depends on configuration and workload (a server
usually hits fds/conntrack/memory; a client to one destination usually hits ephemeral ports).

### 21.6
The service is hitting **ephemeral-port exhaustion** to a single destination (§4.2): under higher load it is
opening many simultaneous (or rapidly-churning short-lived) outbound connections to one destination, and the
~28,000 ephemeral source ports for that destination fill up, so new connections fail with EADDRNOTAVAIL.
TIME_WAIT (Chapter 19) aggravates it — closed connections hold their tuple for ~60–120s, so ports are not
immediately reusable, and short-lived connections without keep-alive pile up TIME_WAIT. Diagnose: `ss -s`
and `ss -tan state time-wait | wc -l` (many TIME_WAIT), check `ip_local_port_range`, and confirm the
connections are to one destination without reuse. Fix, in order of leverage: (1) **enable connection reuse
/ pooling** (HTTP keep-alive, HttpClient/SDK/DB connection pooling) so many requests share few connections —
the primary fix, reducing port consumption dramatically; (2) if reuse is insufficient, widen
`ip_local_port_range` and consider `tcp_tw_reuse` (carefully, for outbound); (3) spread load across multiple
destination IPs if possible. The most common root cause is failing to pool (e.g. a new HttpClient per
request), so verify pooling first — it is a self-inflicted DoS, not an attack.

### 21.18
Connection pooling (reuse) is a security/availability control because it is the highest-leverage defense
against connection-resource exhaustion — which is a denial-of-service condition (availability is a CIA
property). Every new connection consumes an ephemeral source port (to that destination), a
connection-tracking entry (in stateful firewalls/NAT/SGs), a file descriptor, and per-connection memory —
all finite. Without pooling, a high-throughput service opens (and rapidly churns) many short-lived
connections, exhausting ephemeral ports to a downstream (EADDRNOTAVAIL), piling up TIME_WAIT, consuming fds
and conntrack entries — a self-inflicted DoS that presents as an outage. Pooling reuses a small set of
connections across many requests, so it reduces consumption of **all** these ceilings simultaneously (one
port/fd/conntrack entry serves many requests), dramatically raising the effective capacity and eliminating
the exhaustion. It also reduces the attack surface for connection-based DoS (fewer resources consumed per
unit of work). And it aligns with the cloud ceilings — pooling keeps you under the NAT gateway's
per-destination connection limit (Chapter 14). So while pooling is often thought of as a performance
optimization, it is fundamentally an availability/DoS-resistance control, and its absence (e.g. a new
HttpClient per request) is a classic self-inflicted availability failure — which is why it belongs in the
security engineer's toolkit alongside timeouts, connection limits, and reverse-proxy absorption.

### 21.20
Capacity planning and DoS resistance overlap because both are bounded by the *same finite connection
resources* — ephemeral ports, conntrack entries, file descriptors, and per-connection memory. Capacity
planning asks "how many connections can this system handle?" and the answer is the minimum of those ceilings
(§4.5, §5). DoS resistance asks "how many connections can an attacker force before the system fails?" — and
the answer is the *same* ceilings, because a connection flood, slow-client hoarding, or single-destination
hammering all consume the identical resources that legitimate load does. So raising a ceiling (more fds,
larger conntrack table, wider port range, more memory) or reducing per-connection consumption (connection
reuse, smaller buffers, shorter timeouts) improves *both* capacity and DoS resistance at once, and the
reverse-proxy/ALB pattern (absorbing client connections efficiently, maintaining a small reused backend
pool) shifts the ceiling for both. The practical consequence: you cannot separate "how much load can we
handle" from "how much DoS can we absorb" — they are the same question about the same finite resources, and
the same measures (reuse, sizing, edge absorption, monitoring) address both. This is why the "finite
resources are DoS targets" theme (Chapters 1, 3, 14, 19, 20) culminates here in the recognition that
availability engineering (capacity) and security engineering (DoS resistance) are, at the connection layer,
one discipline.

---

*This completes the transport-layer consolidation. Next: Chapter 22 — MTU, Fragmentation, Path MTU
Discovery, and the Bugs They Cause. We examine packet sizing across the network — why MTU mismatches cause
hangs and blackholes, how fragmentation works and is abused, and the security-relevant behaviors (fragment
attacks, PMTU blackholing) that intersect with everything from VPNs to firewalls.*
