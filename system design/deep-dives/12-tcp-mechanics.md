# Deep Dive 12 — TCP Mechanics

**Prerequisite:** [Chapter 13 — Networking](../13-networking.md) §13.3

**What the map said:** *"TCP gives you reliability and ordering. The three-way handshake costs a round trip. Slow start means the first 14 KB is slow. Connection reuse matters."*

**What this deep dive does:** walks the state machine including the two queues that silently drop your connections, explains TIME_WAIT precisely enough that you stop reaching for the dangerous sysctls, derives the bandwidth-delay product and shows why a 10 Gbps link can deliver 5 Mbps, compares CUBIC and BBR with the reason BBR exists, traces the 40 ms Nagle/delayed-ACK stall, explains the PMTU black hole that makes small requests work and large ones hang, and ends with a field-by-field reading of `ss -ti` and a diagnosis procedure.

---

## Contents

```
1.  The state machine
2.  The handshake, and the two queues ⭐
3.  Accept queue overflow — the silent drop
4.  SYN floods and SYN cookies
5.  The four-way close
6.  ⭐ TIME_WAIT: what it is actually for
7.  ⭐ Ephemeral port exhaustion, quantified
8.  CLOSE_WAIT accumulation — an application bug
9.  Sequence numbers, cumulative ACK and SACK
10. Flow control: the receive window and window scaling
11. ⭐ The bandwidth-delay product
12. Congestion control: slow start and congestion avoidance
13. Loss recovery: fast retransmit vs RTO
14. ⭐ CUBIC vs BBR
15. ⭐ Bufferbloat
16. ⭐ Traced scenario — the 40 ms Nagle stall
17. Retransmission timeouts and the cost of a lost SYN
18. Head-of-line blocking
19. ⭐ MSS, PMTUD and the black hole
20. Keepalives and TCP_USER_TIMEOUT
21. ⭐ Reading `ss -ti` field by field
22. Diagnosis: the procedure
23. Tuning
24. What an architect takes from this
```

---

## 1. The state machine

```
                          ┌────────┐
                          │ CLOSED │
                          └───┬────┘
              passive open ───┤─── active open (connect)
                     ┌────────▼────────┐        ┌──────────┐
                     │     LISTEN      │        │ SYN_SENT │
                     └────────┬────────┘        └────┬─────┘
                    rcv SYN   │                      │ rcv SYN-ACK
                    snd SYN-ACK                      │ snd ACK
                     ┌────────▼────────┐             │
                     │  SYN_RECEIVED   │             │
                     └────────┬────────┘             │
                       rcv ACK│                      │
                              └──────┬───────────────┘
                            ┌────────▼────────┐
                            │  ESTABLISHED    │
                            └───┬────────┬────┘
             close (active) ────┤        ├──── rcv FIN (passive)
                    snd FIN     │        │     snd ACK
              ┌─────────────────▼┐      ┌▼──────────────┐
              │   FIN_WAIT_1     │      │  CLOSE_WAIT   │ ⭐ §8
              └────┬────────┬────┘      └───────┬───────┘
         rcv ACK   │        │ rcv FIN           │ close
                   │        │ snd ACK           │ snd FIN
       ┌───────────▼┐    ┌──▼──────┐     ┌──────▼──────┐
       │ FIN_WAIT_2 │    │ CLOSING │     │  LAST_ACK   │
       └──────┬─────┘    └────┬────┘     └──────┬──────┘
   rcv FIN    │               │ rcv ACK         │ rcv ACK
   snd ACK    │               │                 │
        ┌─────▼───────────────▼─────┐     ┌─────▼──┐
        │   ⭐ TIME_WAIT (2×MSL)    │     │ CLOSED │
        └───────────┬───────────────┘     └────────┘
                    │ 2×MSL elapsed
              ┌─────▼──┐
              │ CLOSED │
              └────────┘
```

**Two states carry almost all the operational pain: `TIME_WAIT` (§6–7) and `CLOSE_WAIT` (§8).** They have completely different causes and completely different fixes, and they are routinely confused.

---

## 2. The handshake, and the two queues ⭐

```
CLIENT                                    SERVER (listening)
  │                                          │
  │──── SYN, seq=x ─────────────────────────►│  ⭐ enters the SYN QUEUE
  │                                          │
  │◄─── SYN-ACK, seq=y, ack=x+1 ─────────────│
  │                                          │
  │──── ACK, seq=x+1, ack=y+1 ──────────────►│  ⭐ moves to the ACCEPT QUEUE
  │                                          │
  │     ⭐ the client considers the           │  ⭐ the SERVER APPLICATION must
  │        connection ESTABLISHED here        │     call accept() to dequeue it
  │                                          │
  │──── data ───────────────────────────────►│
```

### ⭐ The two queues nobody knows about

This is the single most useful thing in this deep dive for debugging "connection refused / timeout under load".

```
┌──────────────────────────────────────────────────────────────┐
│ ⭐ SYN QUEUE (incomplete connections)                         │
│    Half-open: SYN received, SYN-ACK sent, waiting for the ACK │
│    Size: net.ipv4.tcp_max_syn_backlog  (default 128-1024)     │
│    ⭐ Overflow → SYN cookies (§4) or the SYN is DROPPED        │
├──────────────────────────────────────────────────────────────┤
│ ⭐ ACCEPT QUEUE (completed connections)                        │
│    Fully established, waiting for the application's accept()  │
│    Size: ⭐ min( backlog argument to listen(), net.core.somaxconn ) │
│    ⭐ Overflow → the final ACK is SILENTLY DROPPED (§3)        │
└──────────────────────────────────────────────────────────────┘
```

```c
listen(sockfd, 511);   /* ⭐ this 511 is CAPPED by net.core.somaxconn */
```

```bash
# ⭐ The kernel default is often 4096 on modern kernels, 128 on older ones.
sysctl net.core.somaxconn
# net.core.somaxconn = 4096

# ⭐ And the application's own backlog may be much smaller:
#   nginx:    listen ... backlog=511  (the default)
#   Node.js:  server.listen(port, host, backlog)  — ⭐ defaults to 511
#   Python:   sock.listen(5)          — ⭐ the textbook example is 5!
#   Go:       uses somaxconn directly
#   Java:     new ServerSocket(port, backlog) — ⭐ defaults to 50
```

```
⭐ THE EFFECTIVE QUEUE IS THE SMALLER OF THE TWO.
   Raising somaxconn does nothing if your application passes 50.
   Raising the application's backlog does nothing if somaxconn is 128.
   ⭐ YOU MUST RAISE BOTH.
```

### Inspecting the queues

```bash
# ⭐ For LISTEN sockets, ss shows the accept queue
ss -ltn
# State   Recv-Q  Send-Q  Local Address:Port
# LISTEN  ⭐ 0     ⭐ 511   0.0.0.0:8080
#            ▲        ▲
#            │        └── the queue's MAXIMUM size
#            └── ⭐ CURRENT number of completed connections WAITING for accept()

# ⭐ If Recv-Q is persistently near Send-Q, your application is not
#   calling accept() fast enough. That is an application problem, not
#   a kernel-tuning problem.
```

---

## 3. Accept queue overflow — the silent drop

```
⭐ WHEN THE ACCEPT QUEUE IS FULL AND THE FINAL ACK ARRIVES:

  net.ipv4.tcp_abort_on_overflow = 0  (⭐ THE DEFAULT)
      ⭐ The server SILENTLY DROPS the ACK.
      ⭐ The client is in ESTABLISHED and starts sending data.
      ⭐ The server is still in SYN_RECEIVED and retransmits the SYN-ACK.
      ⭐ The client sees no response to its data and retransmits.
      → the connection hangs for seconds, then may recover or time out.

  net.ipv4.tcp_abort_on_overflow = 1
      The server sends RST. ⭐ The client gets an immediate
      "connection reset by peer" — an honest, fast failure.
```

```
⭐ THE DEFAULT (0) IS CHOSEN DELIBERATELY: a brief burst may drain,
   and retransmission lets the connection survive. But under sustained
   overload it produces the WORST possible symptom — ⭐ multi-second
   hangs with no error anywhere, on a server that looks healthy.
```

### Detecting it

```bash
# ⭐ THE COUNTERS. These are the ones to check first for
#   "intermittent connection timeouts under load".
netstat -s | grep -iE 'listen|overflow'
#   ⭐ 2847 times the listen queue of a socket overflowed
#   ⭐ 2847 SYNs to LISTEN sockets dropped

nstat -az | grep -E 'ListenOverflows|ListenDrops'
# TcpExtListenOverflows   ⭐ 2847
# TcpExtListenDrops       ⭐ 2847
```

```
⭐ ANY NON-ZERO ListenOverflows MEANS CONNECTIONS ARE BEING DROPPED.
   It should be zero. If it is climbing, either:
     • the application is too slow to accept() → fix the application
       (a blocked accept loop, a thread pool exhausted, a slow TLS handshake)
     • or the backlog is too small → raise BOTH values (§2)
```

**This counter explains a large share of "random 500s under load" and "the load balancer says the backend is unhealthy but the backend looks fine".**

---

## 4. SYN floods and SYN cookies

```
⭐ A SYN FLOOD sends many SYNs and never completes the handshake.
   Each one occupies a SYN-queue slot for the SYN-ACK retransmission
   period (~63 s with default retries) — exhausting the queue so
   legitimate connections are dropped.
```

### SYN cookies — statelessness as a defence

```properties
net.ipv4.tcp_syncookies = 1     # ⭐ default on modern Linux: enabled
```

```
⭐ WHEN THE SYN QUEUE OVERFLOWS, instead of dropping the SYN, the server
   ENCODES THE CONNECTION STATE INTO THE INITIAL SEQUENCE NUMBER of the
   SYN-ACK, and ⭐ KEEPS NO STATE AT ALL.

   ISN = hash(src_ip, src_port, dst_ip, dst_port, secret, time_counter)
         || encoded MSS index || time counter

   ⭐ When the client's ACK arrives, the server RECOMPUTES the hash from
      the ACK's fields. If it matches ack−1, the handshake was genuine
      and the connection is reconstructed from nothing.

⭐ A forged SYN costs the attacker a packet and costs the server no memory.
```

```
⚠ THE COST: the cookie has limited bits, so some TCP options negotiated
  in the original SYN are lost or approximated — historically window
  scaling and SACK. ⭐ Modern Linux encodes these in the TCP timestamp
  option when timestamps are available, largely eliminating the penalty.

⭐ SYN cookies engage ONLY WHEN THE QUEUE OVERFLOWS. They are a
  fallback, not the normal path — so leaving them enabled costs nothing.
```

```bash
# Are cookies being used? (indicates the SYN queue is overflowing)
netstat -s | grep -i cookie
# ⭐ 1284 SYN cookies sent
# ⭐ 1281 SYN cookies received
```

---

## 5. The four-way close

```
A (active closer)                          B (passive closer)
  │                                          │
  │──── FIN, seq=m ─────────────────────────►│  ⭐ B → CLOSE_WAIT
  │  A → FIN_WAIT_1                          │
  │                                          │
  │◄─── ACK, ack=m+1 ────────────────────────│
  │  A → FIN_WAIT_2                          │
  │                                          │
  │      ⭐ B CAN STILL SEND DATA HERE —     │
  │         TCP connections are two           │
  │         independent half-duplex streams   │
  │                                          │
  │◄─── FIN, seq=n ──────────────────────────│  ⭐ B → LAST_ACK
  │                                          │     (only when the APPLICATION
  │                                          │      calls close())
  │──── ACK, ack=n+1 ───────────────────────►│  B → CLOSED
  │  ⭐ A → TIME_WAIT (2×MSL = 60 s)         │
  │                                          │
  │  ... 60 seconds ...                      │
  │  A → CLOSED                              │
```

```
⭐ THE CRITICAL ASYMMETRY:

  ⭐ TIME_WAIT is on the side that CLOSES FIRST (the ACTIVE closer).
  ⭐ CLOSE_WAIT is on the side that receives the FIRST FIN (the PASSIVE closer).

  This determines which machine accumulates which state, and therefore
  which problem you get.
```

---

## 6. ⭐ TIME_WAIT: what it is actually for

`TIME_WAIT` lasts `2 × MSL` (Maximum Segment Lifetime). **On Linux this is hardcoded at 60 seconds** (`TCP_TIMEWAIT_LEN`) and cannot be changed without recompiling the kernel.

### The two reasons it exists

```
⭐ REASON 1 — ENSURE THE FINAL ACK IS DELIVERED

  If A's final ACK is lost, B retransmits its FIN.
  ⭐ A must still exist to re-ACK it. If A had gone straight to CLOSED,
     it would reply with RST, and B would report an error on a
     connection that closed perfectly normally.

⭐ REASON 2 — PREVENT OLD SEGMENTS POLLUTING A NEW CONNECTION

  The 4-tuple (src_ip, src_port, dst_ip, dst_port) can be REUSED.
  ⭐ If a delayed segment from the old connection arrives after a new
     connection with the same 4-tuple is established, and its sequence
     number happens to fall inside the new connection's window,
     ⭐ IT WILL BE ACCEPTED AS VALID DATA.

  2×MSL guarantees every segment from the old connection has expired.
```

**Reason 2 is the serious one.** It is a data-corruption defence, not a tidiness measure — which is why the "fixes" that disable it are dangerous.

### The sysctls, and which are safe

```properties
# ⭐ SAFE and useful for OUTBOUND connections
net.ipv4.tcp_tw_reuse = 1
#   Allows a new OUTGOING connection to reuse a TIME_WAIT socket,
#   ⭐ but ONLY IF TCP TIMESTAMPS are enabled on both ends and the
#      new connection's timestamp is strictly newer.
#   ⭐ The timestamp check restores reason-2 safety.
#   ⚠ Affects OUTBOUND only. It does not help a server.

# ⭐⭐ REMOVED IN LINUX 4.12 — and it was DANGEROUS
# net.ipv4.tcp_tw_recycle = 1
#   ⭐ It tracked the most recent timestamp PER SOURCE IP. Behind NAT,
#     many clients share one IP with UNSYNCHRONISED clocks, so a client
#     with a slightly older timestamp was ⭐ SILENTLY REFUSED CONNECTION.
#   ⭐ Symptom: "some users can't connect, intermittently, and it
#     correlates with nothing." A notorious, hard-to-diagnose outage.
#   ⭐ IF YOU FIND THIS IN A CONFIG FILE OR A BLOG POST, REMOVE IT.

net.ipv4.tcp_timestamps = 1     # ⭐ required for tw_reuse; default on
```

```
⭐ AND NOTE: net.ipv4.tcp_max_tw_buckets caps the NUMBER of TIME_WAIT
   sockets. When exceeded, sockets are destroyed immediately with a
   log message:
       "TCP: time wait bucket table overflow"
   ⭐ That is reason-2 protection being abandoned under pressure.
      Raising the limit is usually better than letting it overflow —
      but the real fix is §7.
```

---

## 7. ⭐ Ephemeral port exhaustion, quantified

The practical consequence of TIME_WAIT, with the arithmetic.

```bash
sysctl net.ipv4.ip_local_port_range
# net.ipv4.ip_local_port_range = 32768	60999
# ⭐ = 28,232 usable ephemeral ports
```

### The limit

```
⭐ A connection is identified by the 4-TUPLE:
     (src_ip, src_port, dst_ip, dst_port)

⭐ So the port limit applies PER DESTINATION (ip, port) PAIR —
   not globally.

  28,232 ports ÷ 60 seconds of TIME_WAIT
  ⭐ = 470 new connections per second TO A SINGLE DESTINATION
```

```
⭐ EXCEED THAT AND YOU GET:
     connect(): Cannot assign requested address     (EADDRNOTAVAIL)

  ⭐ Often reported as "random connection failures under load" that
     correlate with request rate but not with the destination's health.
```

### The worked example

```
A service makes one outbound HTTP call per request to one upstream,
opening a new connection each time.

  At 300 req/s:  300 × 60 = 18,000 sockets in TIME_WAIT   ✓ survivable
  At 500 req/s:  500 × 60 = 30,000 > 28,232               ⭐ EXHAUSTED
  ⭐ Above ~470 req/s to one destination, this service CANNOT WORK.
```

```bash
# ⭐ Check it
ss -tan state time-wait | wc -l
# 28104          ⭐ essentially at the limit

ss -tan | awk '{print $NF}' | sort | uniq -c | sort -rn | head
#   ⭐ 28104 10.0.1.50:5432      ← all to one destination
```

### The fixes, in order of correctness

```
⭐ 1. CONNECTION POOLING / KEEP-ALIVE — THE REAL FIX.
   A pool of 50 persistent connections handles unlimited request
   volume with 50 sockets and ZERO TIME_WAIT churn.
   ⭐ This is Chapter 13 §13.6's advice, and this is why it matters.

   • HTTP: keep-alive + a client-side connection pool
   • PostgreSQL: PgBouncer (Deep Dive 04, Chapter 09 §9.9)
   • Redis: a client pool
   • gRPC: multiplexes over one HTTP/2 connection by design

2. ⭐ net.ipv4.tcp_tw_reuse = 1        (safe, outbound only)

3. Widen the range:
   net.ipv4.ip_local_port_range = 10240 65535    # ⭐ ~55,000 ports

4. ⭐ Multiple source IPs or multiple destination ports —
   the 4-tuple gives you a fresh port space per (dst_ip, dst_port).

5. ⭐ SO_REUSEPORT on the server side for accept scalability
   (a different problem, but often conflated)
```

> **If you find yourself tuning `ip_local_port_range` or reaching for `tcp_tw_recycle`, stop and add connection pooling instead.** Every other fix is a way of postponing the same problem.

---

## 8. CLOSE_WAIT accumulation — an application bug

```
⭐ CLOSE_WAIT means: the PEER sent FIN, the kernel ACKed it, and the
   kernel is now waiting for YOUR APPLICATION to call close().

⭐ IT WILL WAIT FOREVER. There is no timeout.
```

```bash
ss -tan state close-wait | wc -l
# ⭐ 8421           ← 8,421 file descriptors leaked
```

```
⭐ CLOSE_WAIT ACCUMULATION IS ALWAYS AN APPLICATION BUG.
   It is NEVER fixed by a sysctl.

⭐ THE CAUSES:
   • A connection object not closed on an error path
   • ⭐ An exception thrown before close(), with no try/finally
   • A connection pool that does not evict broken connections
   • Blocking forever on a read from a socket the peer has closed
   • A thread leak — the thread that would close it is stuck elsewhere
```

```bash
# ⭐ Find the offending process and the leaked FDs
ss -tanp state close-wait | head
# ESTAB ... users:(("myapp",pid=8821,fd=⭐1247))

ls -l /proc/8821/fd | wc -l          # ⭐ how many FDs does it hold?
cat /proc/8821/limits | grep files   # ⭐ how many is it allowed?
```

```
⭐ THE ENDGAME: file descriptor exhaustion.
     accept(): Too many open files    (EMFILE)
   ⭐ The service stops accepting ANY connection while appearing healthy
     on every other metric.
```

> **The diagnostic value of distinguishing these two states is high.** Many `TIME_WAIT` = you are opening too many connections (fix: pooling). Many `CLOSE_WAIT` = you are not closing them (fix: your code). They look similar in a socket count and have nothing in common.

---

## 9. Sequence numbers, cumulative ACK and SACK

```
⭐ Every byte has a 32-bit sequence number.
⭐ The Initial Sequence Number (ISN) is RANDOMISED — otherwise an
   attacker could predict it and inject data into a connection.
```

### Cumulative ACK — and its weakness

```
⭐ ACK n means "I have received EVERYTHING up to byte n−1".

  Sender transmits: [1000-1999] [2000-2999] [3000-3999] [4000-4999]
  ⭐ Segment 2000-2999 is LOST.
  Receiver ACKs:    ack=2000, ack=2000, ack=2000   (duplicate ACKs)

  ⭐ THE PROBLEM: the receiver cannot say "I got 3000-4999 too".
     Cumulative ACK can only express a single contiguous prefix.
     ⭐ Without more information, the sender may retransmit
        EVERYTHING from 2000 onwards.
```

### SACK — Selective Acknowledgement

```properties
net.ipv4.tcp_sack = 1          # ⭐ default on
net.ipv4.tcp_dsack = 1         # duplicate-SACK: report re-received data
net.ipv4.tcp_fack = 0          # obsolete, replaced by RACK
```

```
⭐ SACK lets the receiver say:
     "ack=2000, and additionally I have SACK blocks [3000-3999],[4000-4999]"

  ⭐ The sender retransmits ONLY 2000-2999.

⭐ Without SACK, a single loss on a high-BDP link can cost an enormous
   amount of redundant retransmission. It is one of the highest-value
   TCP options and it has been on by default for two decades.
```

```
⭐ RACK-TLP (Recent ACKnowledgement, Linux 4.18+) largely replaces the
   older duplicate-ACK heuristics: it uses TIME rather than packet
   counts to decide a segment is lost, which works far better with
   reordering and with small flows where 3 duplicate ACKs never arrive.
     net.ipv4.tcp_recovery = 1   (RACK enabled, the default)
```

---

## 10. Flow control: the receive window and window scaling

```
⭐ FLOW CONTROL protects the RECEIVER from being overwhelmed.
   (Congestion control, §12, protects the NETWORK. They are different
   mechanisms and are constantly confused.)

  Every ACK carries the receiver's ⭐ ADVERTISED WINDOW (rwnd):
      "I have this much free buffer space."

  ⭐ The sender may have at most rwnd bytes unacknowledged in flight.
```

### ⭐ The 16-bit problem and window scaling

```
⭐ The TCP header's window field is 16 BITS → maximum 65,535 bytes.

  ⭐ On a 100 ms RTT link, a 64 KB window caps throughput at:
       65,535 bytes / 0.1 s = 655 KB/s = ⭐ 5.2 Mbps
     ...regardless of whether the link is 10 Gbps.
```

```
⭐ WINDOW SCALING (RFC 7323) negotiates a SHIFT FACTOR in the SYN:
      actual window = advertised × 2^shift      (shift up to 14)
   ⭐ Maximum window becomes 65,535 × 2^14 = ~1 GB.
```

```properties
net.ipv4.tcp_window_scaling = 1     # ⭐ default on — verify it
```

```
⚠ ⭐ WINDOW SCALING IS NEGOTIATED IN THE SYN ONLY.
  If a middlebox (an old firewall, a broken load balancer) strips the
  option from the SYN, ⭐ the connection silently falls back to a
  64 KB window.

  ⭐ SYMPTOM: throughput capped at exactly ~5 Mbps on a fast
     long-distance link, with no errors and no loss.
     This is a real and frequently-misdiagnosed problem.

  ⭐ CHECK IT:  ss -ti | grep wscale
                #  wscale:7,7      ← ⭐ both directions negotiated
                #  (absent)        ← ⭐ scaling was stripped
```

---

## 11. ⭐ The bandwidth-delay product

The formula that explains most "the link is fast but the transfer is slow" cases.

```
⭐ BDP = BANDWIDTH × ROUND-TRIP TIME

   It is the amount of data "in flight" on the wire at full utilisation.

⭐ TO SATURATE A LINK, THE WINDOW MUST BE AT LEAST THE BDP.
⭐ THROUGHPUT ≤ WINDOW / RTT.
```

### Worked numbers

```
  1 Gbps, 1 ms RTT (same datacenter):
      BDP = 125 MB/s × 0.001 s = ⭐ 125 KB          — trivially satisfied

  1 Gbps, 100 ms RTT (transatlantic):
      BDP = 125 MB/s × 0.1 s   = ⭐ 12.5 MB         — needs a 12.5 MB window!

  10 Gbps, 100 ms RTT:
      BDP = 1.25 GB/s × 0.1 s  = ⭐ 125 MB

  10 Gbps, 250 ms RTT (satellite / Sydney–London):
      BDP = ⭐ 312 MB
```

```
⭐ NOW APPLY "throughput ≤ window / RTT":

  Default Linux max receive buffer: net.core.rmem_max = 212,992 bytes
  On a 100 ms RTT link:
      ⭐ 212,992 / 0.1 = 2.1 MB/s = 17 Mbps

  ⭐ ON A 10 Gbps TRANSATLANTIC LINK, DEFAULT BUFFERS GIVE YOU 17 Mbps.
     0.17% of the available bandwidth.
```

### The fix

```properties
# ⭐ Autotuning is on by default, but it is CAPPED by these maxima.
net.ipv4.tcp_moderate_rcvbuf = 1          # ⭐ autotuning enabled (default)

# min, default, max  — ⭐ the THIRD value is the autotuning ceiling
net.ipv4.tcp_rmem = 4096 131072 ⭐ 67108864     # 64 MB max receive
net.ipv4.tcp_wmem = 4096 16384  ⭐ 67108864     # 64 MB max send

# ⭐ And these must be raised too, or they cap the above
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
```

```
⭐ SIZE THE MAXIMUM FOR YOUR WORST-CASE BDP:
     max_buffer ≥ peak_bandwidth × max_RTT

   10 Gbps × 100 ms = 125 MB → set 128 MB if you genuinely need
   single-stream transatlantic line rate.

⚠ ⭐ THE TRADE: large buffers consume kernel memory per connection and
   contribute to bufferbloat (§15). Autotuning means most connections
   use far less than the maximum, so raising the ceiling is usually
   safe — but do not set an enormous default.
```

> **This single calculation explains a large fraction of "why is our cross-region replication slow?" investigations.** It is not the link; it is the window. And note the connection to Deep Dive 07: PostgreSQL streaming replication across regions is exactly this workload.

---

## 12. Congestion control: slow start and congestion avoidance

```
⭐ FLOW CONTROL (rwnd) protects the RECEIVER.
⭐ CONGESTION CONTROL (cwnd) protects the NETWORK.

⭐ Effective window = min(cwnd, rwnd)
```

### Slow start

```
⭐ cwnd starts at the INITIAL WINDOW (IW).
   RFC 6928 raised it to ⭐ 10 MSS ≈ 14.6 KB — this is why
   "the first 14 KB is special" (Chapter 13 §13.3).

⭐ EXPONENTIAL GROWTH: cwnd doubles every RTT.

  RTT 1: cwnd = 10 MSS  ≈ 14.6 KB
  RTT 2: cwnd = 20 MSS  ≈ 29 KB
  RTT 3: cwnd = 40 MSS  ≈ 58 KB
  RTT 4: cwnd = 80 MSS  ≈ 117 KB
  ...until cwnd ≥ ssthresh, or loss occurs
```

```
⭐ THE PRACTICAL CONSEQUENCE:

  Transferring 1 MB over a 100 ms RTT link, starting from cold:
     needs ~7 RTTs of slow start to reach a window large enough
     ⭐ ≈ 700 ms, dominated ENTIRELY by slow start, not by bandwidth.

  ⭐ The same transfer on an ALREADY-WARM connection: ~100 ms.

⭐ THIS IS WHY CONNECTION REUSE MATTERS SO MUCH — it is not just the
   handshake (§2) and TLS (Deep Dive 13); it is that a warm connection
   has a large cwnd and a cold one starts at 14.6 KB.
```

### Congestion avoidance

```
⭐ Once cwnd ≥ ssthresh, growth becomes LINEAR: +1 MSS per RTT.

     cwnd
       │        ╱╲        ╱╲         ╱
       │       ╱  ╲      ╱  ╲       ╱     ⭐ the classic
       │      ╱    ╲    ╱    ╲     ╱         "sawtooth"
       │     ╱      ╲  ╱      ╲   ╱
       │   ╱╱        ╲╱        ╲ ╱
       │ ╱╱ slow start  ▲       ▲
       └──────────────────────────────► time
                     loss    loss
```

---

## 13. Loss recovery: fast retransmit vs RTO

**The distinction that determines whether a loss costs you 20 ms or 1 second.**

### Fast retransmit / fast recovery — the good path

```
⭐ 3 DUPLICATE ACKs (or RACK's time-based detection) indicate a loss
   while data is still flowing.

  1. Retransmit the missing segment immediately — ⭐ do NOT wait for a timeout
  2. ssthresh = cwnd / 2
  3. ⭐ cwnd = ssthresh    (halve it; do NOT restart slow start)
  4. Continue in congestion avoidance

⭐ COST: ~1 RTT, and half the throughput. Recoverable in a few RTTs.
```

### RTO timeout — the bad path

```
⭐ NO ACKs ARRIVE AT ALL for the retransmission timeout period.

  1. Retransmit
  2. ssthresh = cwnd / 2
  3. ⭐ cwnd = 1 MSS        ← BACK TO THE BEGINNING
  4. ⭐ RESTART SLOW START
  5. ⭐ DOUBLE the RTO (exponential backoff)

⭐ COST: at least RTO (minimum 200 ms on Linux, 1 s initial), PLUS a
   full slow-start ramp. ⭐ Often 10-100× worse than fast retransmit.
```

```
⭐ WHY THE DIFFERENCE MATTERS ENORMOUSLY:

  Duplicate ACKs require data to still be flowing. So:
    • ⭐ A loss in the MIDDLE of a large transfer → fast retransmit → cheap
    • ⭐ A loss of the LAST segment of a response → no subsequent data,
         no duplicate ACKs → ⭐ RTO → hundreds of milliseconds

⭐ THIS IS WHY SMALL REQUEST/RESPONSE WORKLOADS ARE SO SENSITIVE TO
   PACKET LOSS. A 2 KB API response that loses its last packet stalls
   for a full RTO. The p99 latency of a request/response protocol on a
   lossy link is dominated by RTO events, not by bandwidth.
```

```
⭐ TAIL LOSS PROBE (TLP, part of RACK-TLP) exists exactly for this:
   before the RTO expires, send a probe to elicit a duplicate ACK and
   trigger fast recovery instead. It converts many RTOs into fast
   retransmits, and it is a significant p99 improvement.
     net.ipv4.tcp_early_retrans = 3   (default, includes TLP)
```

---

## 14. ⭐ CUBIC vs BBR

```bash
sysctl net.ipv4.tcp_congestion_control
# net.ipv4.tcp_congestion_control = cubic     ⭐ Linux default since 2.6.19

sysctl net.ipv4.tcp_available_congestion_control
# reno cubic bbr
```

### CUBIC — loss-based

```
⭐ CUBIC grows cwnd as a CUBIC FUNCTION of the time since the last
   congestion event:

     cwnd = C(t − K)³ + W_max

   • ⭐ Grows rapidly when far below the previous maximum
   • ⭐ Flattens near W_max (probing cautiously)
   • ⭐ Grows aggressively again if no loss occurs (searching for
     a new maximum)

⭐ IT IS INDEPENDENT OF RTT, which makes it fairer between flows with
   very different RTTs than the older Reno.
```

```
⭐ THE FUNDAMENTAL ASSUMPTION: PACKET LOSS MEANS CONGESTION.

  ⭐ THIS IS OFTEN FALSE:
     • Wireless links lose packets to interference, not congestion
     • Mobile networks lose packets during handover
     • ⭐ Long-haul links have small random loss rates that are not
       congestion at all

  ⭐ On a link with 0.1% random loss and 100 ms RTT, CUBIC's throughput
     is capped at roughly 30 Mbps no matter how fast the link is,
     because it keeps halving cwnd for non-congestion losses.
```

```
⭐ AND THE SECOND PROBLEM: CUBIC only backs off WHEN IT LOSES A PACKET.
   A packet is lost when a router buffer overflows.
   ⭐ SO CUBIC DELIBERATELY FILLS ROUTER BUFFERS. That is bufferbloat (§15).
```

### BBR — model-based

```
⭐ BBR (Bottleneck Bandwidth and Round-trip propagation time, Google 2016)
   does NOT use loss as a congestion signal at all.

  It continuously MEASURES two things:
    ⭐ BtlBw — the maximum delivery rate observed
    ⭐ RTprop — the minimum RTT observed (the propagation delay,
                with no queueing)

  ⭐ The optimal operating point is the BDP: BtlBw × RTprop.
     BBR PACES its sending to match BtlBw and keeps the in-flight
     data near the BDP — ⭐ so it fills the PIPE but NOT THE BUFFERS.
```

```
⭐ BBR'S ADVANTAGES:
   ✅ ⭐ Immune to random loss — 0.1% loss costs almost nothing
   ✅ ⭐ Does not cause bufferbloat; it keeps queues near empty
   ✅ ⭐ Dramatically better on long, lossy paths (mobile, satellite,
        cross-continent) — Google and others measured multi-× gains
   ✅ Much lower latency for competing traffic on the same link

⚠ ⭐ BBRv1 CAN BE UNFAIR TO CUBIC FLOWS sharing a bottleneck — it can
  take more than its share because it does not respond to the loss
  that CUBIC responds to. ⭐ BBRv2/v3 address this and add an ECN
  response.
```

```bash
# ⭐ Enable BBR (requires the fq or fq_codel qdisc for pacing)
sysctl -w net.core.default_qdisc=fq
sysctl -w net.ipv4.tcp_congestion_control=bbr

# Verify per connection
ss -ti | grep -o 'bbr\|cubic' | sort | uniq -c
```

```
⭐ WHEN TO SWITCH TO BBR:
   • ⭐ Serving clients over the public internet, especially mobile
   • ⭐ Cross-region replication or transfer on long paths
   • Any link with measurable random loss

⭐ WHEN CUBIC IS FINE:
   • Same-datacenter traffic (1 ms RTT, no loss) — the choice barely matters
   • ⭐ Where you share a bottleneck with CUBIC flows you do not want
     to disadvantage
```

---

## 15. ⭐ Bufferbloat

```
⭐ THE PROBLEM: network equipment has large buffers. Loss-based
   congestion control (CUBIC, Reno) only backs off when a buffer
   OVERFLOWS — ⭐ so it fills every buffer on the path first.

  A 1 Gbps link with a 128 MB router buffer:
      ⭐ Queueing delay when full = 128 MB / 125 MB/s = ⭐ 1 SECOND

  ⭐ A single large download can add A FULL SECOND of latency to every
     other flow sharing that link — including your interactive traffic.
```

```
⭐ THE SYMPTOM EVERYONE HAS EXPERIENCED: video calls degrade badly
   while someone in the house uploads a large file. The upload is not
   using all the bandwidth — it is filling a buffer, and every packet
   now waits behind it.
```

### The fixes

```bash
# ⭐ 1. ACTIVE QUEUE MANAGEMENT — drop/mark packets BEFORE the buffer fills
tc qdisc replace dev eth0 root fq_codel
# ⭐ CoDel ("Controlled Delay") tracks the MINIMUM queueing delay over
#   a window and drops packets when it exceeds 5 ms. It targets
#   LATENCY rather than queue length, which is the key insight.

# ⭐ 2. fq (Fair Queueing) — per-flow pacing, required for BBR
tc qdisc replace dev eth0 root fq

# ⭐ 3. Use BBR (§14) — it does not fill buffers in the first place

# ⭐ 4. Cap buffer sizes where you control the equipment
```

```properties
net.core.default_qdisc = fq_codel    # ⭐ a good default for most servers
                                     #   (use `fq` if you run BBR)
```

```
⭐ THE ARCHITECTURAL POINT: bufferbloat means that on a shared link,
   YOUR BULK TRANSFER DEGRADES SOMEONE ELSE'S INTERACTIVE LATENCY.
   If you run large replication or backup traffic over a link that also
   carries user requests, ⭐ traffic shaping is not optional —
   and this is the mechanism behind "our p99 spikes during the
   nightly backup window".
```

---

## 16. ⭐ Traced scenario — the 40 ms Nagle stall

A classic, precisely reproducible latency bug caused by two sensible algorithms interacting badly.

### The two algorithms

```
⭐ NAGLE'S ALGORITHM (RFC 896) — the SENDER
   "Do not send a small segment if there is unacknowledged data
    outstanding. Buffer it and coalesce."
   ⭐ PURPOSE: prevent a telnet session sending a 41-byte packet
      per keystroke.

⭐ DELAYED ACK (RFC 1122) — the RECEIVER
   "Do not ACK immediately. Wait up to 40-200 ms hoping to piggyback
    the ACK on outgoing data, or until a second segment arrives."
   ⭐ PURPOSE: avoid pure-ACK packets.
```

### The deadlock

```
APPLICATION writes a request in TWO write() calls:
    write(sock, header, 80);     /* 80-byte header */
    write(sock, body, 20);       /* 20-byte body   */

t=0     ⭐ Nagle: no unacked data outstanding → SEND the 80-byte header.

t=0+    ⭐ Nagle: the 20-byte body is SMALL and there IS unacked data
        (the header). ⭐ HOLD IT.

t=0.5ms Receiver gets the 80-byte header.
        ⭐ Delayed ACK: "I will wait — maybe more data is coming, or
           maybe my application will produce a response I can piggyback on."
        ⭐ The application is waiting for the FULL request (header+body),
           so it produces nothing.
        ⭐ DO NOT ACK YET.

t=0.5ms ── ⭐ DEADLOCK ──
        Sender waits for an ACK before sending the body.
        Receiver waits for more data before sending an ACK.
        ⭐ NEITHER CAN PROCEED.

t=40ms  ⭐ The receiver's delayed-ACK timer fires. ACK sent.
t=40ms  Sender receives the ACK, sends the 20-byte body.
t=41ms  Receiver has the full request. Processes it.

⭐ 40 MILLISECONDS OF PURE STALL, on a 0.5 ms network.
```

### How to recognise it

```
⭐ THE SIGNATURE:
   • Latency quantised around ⭐ 40 ms or 200 ms (multiples of the
     delayed-ACK timer)
   • ⭐ p50 is fine, p99 is exactly 40 ms
   • ⭐ Only affects small request/response workloads
   • Disappears entirely if the request is sent in one write()
   • Disappears under high throughput (more data → ACKs flow)
```

### The fixes

```c
/* ⭐ FIX 1 — disable Nagle. The standard fix for request/response. */
int flag = 1;
setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
```

```python
# ⭐ FIX 2 (BETTER) — write once. Do not split a logical message
#    across write() calls.
sock.sendall(header + body)          # ⭐ one syscall, one segment
# or
sock.sendmsg([header, body])         # vectored I/O — still one segment
```

```c
/* ⭐ FIX 3 — TCP_CORK: explicitly batch, then flush */
int cork = 1;  setsockopt(sock, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));
write(sock, header, 80);
write(sock, body, 20);
cork = 0;      setsockopt(sock, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));
```

```
⭐ MOST MODERN STACKS SET TCP_NODELAY BY DEFAULT:
   Go (net/http), Node.js, .NET, nginx, Redis, PostgreSQL, Kafka.

⭐ BUT: raw socket code, some RPC frameworks, and older libraries
   do NOT. If you see 40 ms quantisation in latency, check this first —
   it takes one line to test and it is a complete fix.
```

---

## 17. Retransmission timeouts and the cost of a lost SYN

### The RTO calculation (RFC 6298)

```
⭐ SRTT    = (1 − α)·SRTT + α·R              α = 1/8   (smoothed RTT)
⭐ RTTVAR  = (1 − β)·RTTVAR + β·|SRTT − R|   β = 1/4   (RTT variance)
⭐ RTO     = SRTT + max(G, 4 · RTTVAR)

  ⭐ The 4×RTTVAR term is what makes RTO robust: a jittery network gets
     a larger safety margin automatically.

⭐ Linux minimum RTO: 200 ms (TCP_RTO_MIN), not the RFC's 1 second.
⭐ Initial RTO (before any measurement): 1 second.
⭐ Exponential backoff: 1 s, 2 s, 4 s, 8 s, 16 s...
```

### ⭐ The lost SYN — the expensive case

```properties
net.ipv4.tcp_syn_retries = 6        # ⭐ for OUTGOING connections
net.ipv4.tcp_synack_retries = 5     # for the server's SYN-ACK
```

```
⭐ A LOST SYN COSTS AT LEAST 1 SECOND — there is no RTT measurement
   yet, so the initial RTO of 1 s applies.

⭐ AND WITH tcp_syn_retries = 6, A FAILING CONNECT TAKES:
     1 + 2 + 4 + 8 + 16 + 32 + 64 = ⭐ 127 SECONDS

   ⭐ Your application's connect() blocks for over two minutes before
      reporting failure — unless you set a shorter timeout yourself.
```

```
⭐ THIS IS WHY CHAPTER 05 §5.8'S "ALWAYS SET A TIMEOUT" IS NOT ADVICE —
   IT IS ESSENTIAL. The kernel default is 127 seconds, and a service
   waiting 127 seconds for a dead dependency has exhausted its thread
   pool long before that.
```

```properties
# ⭐ Reduce it for fast failure detection in a datacenter
net.ipv4.tcp_syn_retries = 3        # ⭐ 1+2+4 = 7 seconds
```

```c
/* ⭐ BETTER: bound it per socket, so one setting does not affect
   every connection on the host */
unsigned int timeout_ms = 5000;
setsockopt(sock, IPPROTO_TCP, TCP_USER_TIMEOUT, &timeout_ms, sizeof(timeout_ms));
```

---

## 18. Head-of-line blocking

```
⭐ TCP GUARANTEES IN-ORDER DELIVERY TO THE APPLICATION.

  Segments arrive: [1] [2] ✗LOST [4] [5] [6]

  ⭐ Segments 4, 5, 6 ARE IN THE RECEIVER'S KERNEL BUFFER.
  ⭐ But the application CANNOT READ THEM, because segment 3 is missing
     and TCP will not deliver out of order.

  ⭐ EVERYTHING BEHIND THE LOST SEGMENT IS BLOCKED until it is
     retransmitted and arrives — at least one RTT, or an RTO (§13).
```

### Why this matters for HTTP/2

```
⭐ HTTP/2 multiplexes many streams over ONE TCP connection (Chapter 13 §13.6).

  ⭐ It solved HTTP/1.1's APPLICATION-LEVEL head-of-line blocking
     (one request per connection at a time).

  ⭐ IT DID NOT SOLVE TCP-LEVEL HEAD-OF-LINE BLOCKING.

  One lost packet blocks ⭐ EVERY MULTIPLEXED STREAM on that connection,
  even streams whose data arrived perfectly.

⭐ ON A LOSSY LINK, HTTP/2 CAN BE WORSE THAN HTTP/1.1 — because
   HTTP/1.1's six parallel connections mean a loss on one blocks
   only one sixth of the traffic.
```

```
⭐ THIS IS PRECISELY WHY QUIC (AND THEREFORE HTTP/3) EXISTS.

  QUIC runs over UDP and implements its own per-stream reliability.
  ⭐ A loss in stream 3 blocks only stream 3. Streams 1, 2, 4 continue.

  (Deep Dive 14 covers QUIC's mechanics.)
```

---

## 19. ⭐ MSS, PMTUD and the black hole

The failure mode where small requests work perfectly and large ones hang forever.

```
⭐ MTU (Maximum Transmission Unit): the largest frame a link carries.
   Ethernet: 1500 bytes.

⭐ MSS (Maximum Segment Size): the largest TCP payload.
   MSS = MTU − 20 (IP header) − 20 (TCP header) = ⭐ 1460 bytes
```

### Path MTU Discovery

```
⭐ THE PATH's MTU is the MINIMUM MTU of every link along it.

  PMTUD:
    1. Send packets with the ⭐ DF (Don't Fragment) bit set
    2. A router whose next hop has a smaller MTU ⭐ CANNOT FRAGMENT,
       so it DROPS the packet and sends back
       ⭐ ICMP Type 3 Code 4 "Fragmentation Needed", including the MTU
    3. The sender lowers its MSS and retransmits
```

### ⭐ The black hole

```
⭐ MANY NETWORKS BLOCK ALL ICMP as a misguided security measure.

  ⭐ THEN:
    1. Sender sends a 1500-byte packet with DF set
    2. A router with a 1400-byte MTU drops it
    3. ⭐ It sends the ICMP message — WHICH IS BLOCKED
    4. ⭐ The sender NEVER LEARNS. It retransmits the same
       oversized packet. Forever.

⭐ THE SYMPTOM, and it is unmistakable once you know it:
    ✅ The TCP handshake works (SYN/ACK are small)
    ✅ Small requests and responses work perfectly
    ✅ `ping` works
    ⭐ ❌ ANY RESPONSE LARGER THAN ~1400 BYTES HANGS FOREVER

  ⭐ "The API works for small payloads but times out on large ones"
     is almost always this.
```

### Where reduced MTUs come from

```
⭐ Anything that ENCAPSULATES reduces the effective MTU:

  GRE tunnel:        −24 bytes   → 1476
  IPsec (varies):    −50 to −73  → ~1427-1450
  ⭐ VXLAN:          −50 bytes   → 1450
  PPPoE (DSL):       −8 bytes    → 1492
  ⭐ WireGuard:      −60 bytes   → 1420

⭐ KUBERNETES OVERLAY NETWORKS (Flannel VXLAN, Calico IPIP, Cilium
   with tunnelling) ALL REDUCE MTU. This is a very common source of
   the black hole inside clusters, especially for pod-to-pod traffic
   crossing nodes.
```

### Diagnosing and fixing

```bash
# ⭐ Find the actual path MTU: send progressively larger packets with DF set
ping -M do -s 1472 example.com     # 1472 + 28 = 1500 ⭐ total
# ping: local error: message too long, mtu=1450     ← ⭐ found it

# Binary search down until it succeeds:
ping -M do -s 1422 example.com     # 1422 + 28 = 1450 ✓

# ⭐ tracepath reports the PMTU along the route
tracepath example.com
#  1?: [LOCALHOST]      pmtu 1500
#  2:  10.0.0.1         0.412ms
#  3:  ⭐ pmtu 1450
```

```properties
# ⭐ THE FIX: MTU probing. When PMTUD fails, TCP detects the black hole
#   by noticing repeated retransmissions of large segments and
#   progressively lowers the MSS itself.
net.ipv4.tcp_mtu_probing = 1     # ⭐ enable on black-hole detection
net.ipv4.tcp_base_mss = 1024
```

```bash
# ⭐ Or set the interface MTU correctly (the proper fix inside a cluster)
ip link set dev eth0 mtu 1450

# ⭐ Or clamp MSS at a gateway (common on VPN/tunnel endpoints)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
         -j TCPMSS --clamp-mss-to-pmtu
```

---

## 20. Keepalives and TCP_USER_TIMEOUT

```properties
net.ipv4.tcp_keepalive_time   = 7200    # ⭐ 2 HOURS before the first probe
net.ipv4.tcp_keepalive_intvl  = 75      # then every 75 s
net.ipv4.tcp_keepalive_probes = 9       # 9 failed probes → dead
```

```
⭐ THE DEFAULT DETECTS A DEAD PEER AFTER:
     7200 + (9 × 75) = 7,875 seconds = ⭐ 2 HOURS 11 MINUTES

⭐ AND KEEPALIVE IS OFF BY DEFAULT — the application must enable it
   per socket with SO_KEEPALIVE.
```

```
⭐ WHY THIS MATTERS: a connection pool holding a connection to a
   machine that vanished (power loss, a NAT timeout, a firewall
   dropping state) will keep handing it out. Every request on it
   hangs until the ⭐ RTO backoff exhausts — potentially minutes —
   and the pool has no idea.
```

### ⭐ `TCP_USER_TIMEOUT` — usually the better tool

```c
/* ⭐ "If data remains unacknowledged for this long, kill the connection." */
unsigned int timeout_ms = 30000;
setsockopt(sock, IPPROTO_TCP, TCP_USER_TIMEOUT, &timeout_ms, sizeof(timeout_ms));
```

```
⭐ WHY IT IS BETTER THAN KEEPALIVE:
   • ⭐ It bounds the time for ACTUAL DATA, not just idle probes
   • It overrides the RTO backoff sequence, so a stalled connection
     fails at a predictable time rather than after 127 seconds (§17)
   • ⭐ It also caps how long keepalive probing continues

⭐ USE BOTH: keepalive to detect an IDLE dead peer, TCP_USER_TIMEOUT
   to bound an ACTIVE stalled connection.
```

```properties
# ⭐ Sensible datacenter settings
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6
# ⭐ → a dead idle peer is detected in 60 + 60 = 120 seconds
```

**PostgreSQL, Redis, Kafka and most connection pools expose keepalive settings.** Setting them is one of the cheapest ways to stop a pool from serving connections to a machine that no longer exists.

---

## 21. ⭐ Reading `ss -ti` field by field

The single most useful TCP diagnostic command, and almost nobody reads its output fully.

```bash
ss -tin dst 10.0.1.50
```

```
ESTAB 0  0  10.0.1.10:51234  10.0.1.50:5432
     cubic wscale:7,7 rto:204 rtt:3.421/1.887 ato:40 mss:1448 pmtu:1500
     rcvmss:1448 advmss:1448 cwnd:24 ssthresh:18 bytes_sent:184729
     bytes_retrans:2896 bytes_acked:181833 bytes_received:4829102
     segs_out:1284 segs_in:3910 data_segs_out:1201 data_segs_in:3402
     send 81.3Mbps lastsnd:12 lastrcv:8 lastack:8 pacing_rate 97.6Mbps
     delivery_rate 74.1Mbps delivered:1199 busy:4821ms
     retrans:0/2 ⭐ dsack_dups:1 rcv_rtt:4.1 rcv_space:65535
     minrtt:2.918
```

### Field by field

| Field | Meaning | What to look for |
|-------|---------|-----------------|
| `cubic` / `bbr` | Congestion control in use | §14 |
| ⭐ `wscale:7,7` | Window scale (send,recv) | ⭐ **Absent = scaling stripped (§10)** |
| `rto:204` | Current retransmission timeout (ms) | ⭐ Growing = repeated loss (§13) |
| ⭐ `rtt:3.421/1.887` | Smoothed RTT / RTT variance (ms) | ⭐ High variance = jitter or queueing |
| ⭐ `minrtt:2.918` | **Minimum RTT observed** | ⭐ Compare with `rtt` — a large gap means **queueing/bufferbloat (§15)** |
| `ato:40` | Delayed-ACK timeout (ms) | ⭐ 40 → the §16 stall is possible |
| `mss:1448` / `pmtu:1500` | Segment size / path MTU | ⭐ Low pmtu = tunnelling (§19) |
| ⭐ `cwnd:24` | Congestion window **in MSS units** | ⭐ 24 × 1448 = 34 KB in flight |
| `ssthresh:18` | Slow-start threshold | Present = a loss event occurred |
| ⭐ `bytes_retrans:2896` | Total bytes retransmitted | ⭐ vs `bytes_sent` = the **loss rate** |
| ⭐ `retrans:0/2` | Current/total retransmits | ⭐ Non-zero current = actively recovering |
| `dsack_dups` | Spurious retransmissions detected | ⭐ Indicates **reordering**, not loss |
| ⭐ `send 81.3Mbps` | cwnd / rtt — the theoretical rate | |
| ⭐ `delivery_rate` | **Actually measured** delivery rate | ⭐ Compare against `send` |
| `pacing_rate` | Rate limit applied (fq/BBR) | |
| `rcv_space` | Receive-window autotuning state | ⭐ Small = buffer cap reached (§11) |
| `busy:4821ms` | Time spent with data in flight | |

### ⭐ The three quick reads

```
⭐ 1. RETRANSMISSION RATE
     bytes_retrans / bytes_sent = 2896 / 184729 = ⭐ 1.6%
     ⭐ > 1% is significant. > 5% means the path is badly degraded.

⭐ 2. QUEUEING (BUFFERBLOAT)
     rtt (3.421) vs minrtt (2.918) → 0.5 ms of queueing. Fine.
     ⭐ If rtt were 45 ms and minrtt 3 ms, you have 42 ms of QUEUEING
        DELAY — bufferbloat (§15), not distance.

⭐ 3. THROUGHPUT CEILING
     cwnd × mss / rtt = 24 × 1448 / 0.003421 s = ⭐ ~10 MB/s
     ⭐ If that is far below the link speed, you are cwnd-limited
        (loss — §13) or rwnd-limited (buffers — §11).
```

```bash
# ⭐ System-wide summary
ss -s
# Total: 2847
# TCP:   2104 (estab 1847, closed 187, orphaned 2, ⭐ timewait 172)

# ⭐ The kernel's own counters — the highest-signal check
nstat -az | grep -E 'Retrans|ListenOverflows|ListenDrops|TCPTimeouts|TCPLostRetransmit|SyncookiesSent'
```

---

## 22. Diagnosis: the procedure

```
⭐ SYMPTOM: "connections fail / time out intermittently under load"

  1. nstat -az | grep -E 'ListenOverflows|ListenDrops'
     ⭐ Non-zero → §3. The accept queue is overflowing. Raise BOTH
       somaxconn and the application backlog, or fix the accept loop.

  2. ss -tan state time-wait | wc -l
     ⭐ Near ip_local_port_range size → §7. Port exhaustion.
       ⭐ Add connection pooling.

  3. dmesg | grep -i 'conntrack\|nf_conntrack'
     ⭐ "nf_conntrack: table full, dropping packet" — a completely
       separate limit, and a very common one behind firewalls/NAT.
       Raise net.netfilter.nf_conntrack_max.
```

```
⭐ SYMPTOM: "throughput is far below the link speed"

  1. ss -ti | grep wscale
     ⭐ Missing → §10. Window scaling stripped by a middlebox.

  2. Compute BDP = bandwidth × rtt (§11). Compare against
     net.core.rmem_max and net.ipv4.tcp_rmem[2].
     ⭐ If the buffer max < BDP, that is your ceiling.

  3. ss -ti → bytes_retrans / bytes_sent
     ⭐ > 1% → loss is limiting cwnd. ⭐ Consider BBR (§14).

  4. ss -ti → compare rtt with minrtt
     ⭐ Large gap → bufferbloat (§15). Deploy fq_codel or BBR.
```

```
⭐ SYMPTOM: "p99 latency is exactly 40 ms (or 200 ms)"

  ⭐ §16. Nagle + delayed ACK. Check TCP_NODELAY and whether the
    application splits a logical message across multiple write() calls.
```

```
⭐ SYMPTOM: "small requests work, large responses hang"

  ⭐ §19. PMTU black hole.
    ping -M do -s 1472 <host>   → find the real MTU
    ⭐ Check for tunnelling/overlay networks in the path.
```

```
⭐ SYMPTOM: "file descriptors climbing until the service dies"

  ss -tan state close-wait | wc -l
  ⭐ Non-trivial → §8. AN APPLICATION BUG. Find the unclosed
    connection path. No sysctl will fix it.
```

```bash
# ⭐ THE CAPTURE, when you genuinely need to see the packets
tcpdump -i any -nn -s 96 'host 10.0.1.50 and port 5432' -w /tmp/cap.pcap
# ⭐ -s 96 captures headers only — enough for TCP analysis, far less data

# Then, in Wireshark:
#   tcp.analysis.retransmission
#   tcp.analysis.zero_window            ⭐ receiver buffer full
#   tcp.analysis.window_full
#   tcp.flags.reset == 1                ⭐ who is sending RSTs, and when
```

---

## 23. Tuning

```properties
# ═══ CONNECTION QUEUES (§2-3) — ⭐ raise BOTH ═══
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_syncookies = 1                # ⭐ leave enabled
# ⭐ AND raise the application's listen() backlog to match

# ═══ PORT EXHAUSTION (§7) ═══
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_tw_reuse = 1                  # ⭐ safe; outbound only
net.ipv4.tcp_timestamps = 1                # required by tw_reuse
# ⭐ net.ipv4.tcp_tw_recycle — DOES NOT EXIST since 4.12. Never use it.
net.ipv4.tcp_max_tw_buckets = 2000000

# ═══ BUFFERS / BDP (§11) — size the MAXIMUM for your worst-case BDP ═══
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 131072 67108864
net.ipv4.tcp_wmem = 4096 16384 67108864
net.ipv4.tcp_moderate_rcvbuf = 1           # ⭐ autotuning, default on

# ═══ CONGESTION CONTROL (§14-15) ═══
net.core.default_qdisc = fq                # ⭐ fq for BBR, fq_codel otherwise
net.ipv4.tcp_congestion_control = bbr      # ⭐ for internet-facing / long paths
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_recovery = 1                  # ⭐ RACK-TLP

# ═══ FAILURE DETECTION (§17, §20) ═══
net.ipv4.tcp_syn_retries = 3               # ⭐ 7 s instead of 127 s
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# ═══ MTU (§19) ═══
net.ipv4.tcp_mtu_probing = 1               # ⭐ black-hole recovery

# ═══ CONNECTION TRACKING (if netfilter is in the path) ═══
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
```

```bash
# ⭐ Per-socket, in application code — better than global sysctls
setsockopt(fd, IPPROTO_TCP, TCP_NODELAY,      &one, sizeof(one));      # §16
setsockopt(fd, IPPROTO_TCP, TCP_USER_TIMEOUT, &ms,  sizeof(ms));       # §20
setsockopt(fd, SOL_SOCKET,  SO_KEEPALIVE,     &one, sizeof(one));      # §20
setsockopt(fd, SOL_SOCKET,  SO_REUSEPORT,     &one, sizeof(one));      # accept scaling
```

---

## 24. What an architect takes from this

**1. Two queues sit behind every `listen()`, and overflowing the accept queue silently drops connections.** `nstat | grep ListenOverflows` should be your first check for "intermittent timeouts under load" — and you must raise **both** `somaxconn` and the application's backlog.

**2. `TIME_WAIT` exists to prevent data corruption, not to be tidy.** The fix for port exhaustion is **connection pooling**, not disabling the protection. `tcp_tw_recycle` was removed from Linux for good reason; if you find it in a runbook, delete it.

**3. `TIME_WAIT` and `CLOSE_WAIT` are opposite problems.** Many `TIME_WAIT` means you open too many connections. Many `CLOSE_WAIT` means **your code does not close them** — no sysctl will help.

**4. 470 connections/second to one destination is the hard limit** without pooling. Do this arithmetic before designing anything that opens a connection per request.

**5. Throughput ≤ window / RTT.** Default buffers give you 17 Mbps on a 100 ms path regardless of a 10 Gbps link. Compute the BDP for your worst-case path and size `tcp_rmem`/`tcp_wmem` maxima accordingly.

**6. A loss of the *last* segment costs an RTO, not a fast retransmit.** This is why small request/response workloads are so sensitive to loss, and why p99 on a lossy path is dominated by RTO events.

**7. CUBIC treats loss as congestion, which is false on wireless and long-haul links, and it deliberately fills router buffers.** BBR fixes both. For internet-facing or cross-region traffic, it is usually a straightforward win.

**8. Bufferbloat means your bulk transfer degrades someone else's latency.** If replication or backup traffic shares a link with user requests, `fq_codel` or BBR is not optional.

**9. Latency quantised at exactly 40 ms is Nagle plus delayed ACK.** One socket option or one combined `write()` fixes it completely.

**10. "Small requests work, large ones hang" is a PMTU black hole**, and Kubernetes overlay networks cause it routinely. `ping -M do -s 1472` finds it in seconds.

**11. The kernel's default connect timeout is 127 seconds.** Chapter 05's "always set a timeout" is not a style preference — it is the difference between a 5-second failure and an exhausted thread pool.

**12. `ss -ti` tells you the retransmission rate, the queueing delay (`rtt` vs `minrtt`) and the throughput ceiling in one command.** Learn to read it; it replaces a great deal of guesswork.

---

## Exercises

1. Check `nstat -az | grep ListenOverflows` on every production host. Any non-zero value means dropped connections — find out why.
2. Find the effective accept queue size for your main service: the application's `listen()` backlog and `somaxconn`. Which one is binding?
3. Count `TIME_WAIT` sockets by destination on a busy client host. Compute how close you are to the 470/s limit.
4. Find a service in your system that opens a connection per request. Compute its theoretical ceiling and design the pooling fix.
5. Compute the BDP for your longest network path. Compare it against `net.ipv4.tcp_rmem`'s third value. Is it limiting you?
6. Run `ss -ti` against a cross-region connection. Compare `rtt` and `minrtt`. How much queueing delay is present?
7. Compute the retransmission rate from `bytes_retrans / bytes_sent` on a production connection. Is it above 1%?
8. Enable BBR on a test host and measure throughput on a long, slightly lossy path against CUBIC.
9. Reproduce the 40 ms Nagle stall: write a client that sends a request in two `write()` calls to a server that responds only on the full request. Then fix it three ways.
10. Find the path MTU to a service behind a VPN or an overlay network using `ping -M do`. Does it match the interface MTU?
11. Check `wscale` on a long-distance connection. Is window scaling negotiated in both directions?
12. Count `CLOSE_WAIT` sockets per process on your hosts. If any are accumulating, find the code path that fails to close.
13. Set `TCP_USER_TIMEOUT` on a database connection pool and verify that killing the database host fails connections in the expected time rather than after 127 seconds.
14. Capture a `tcpdump` of a slow request and identify, from the packet timings, whether the delay is handshake, slow start, a retransmission, or application think time.

---

**Next in this series:** Deep Dive 13 — TLS and Applied Cryptography

**Back to:** [Deep Dives](README.md) · [Chapter 13](../13-networking.md) · [The Map](../README.md)
