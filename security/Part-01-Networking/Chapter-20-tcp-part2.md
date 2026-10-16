# Chapter 20 — TCP Part 2: Retransmission, Flow Control, Congestion Control, and Performance

---

## 1. Why This Matters

Chapter 19 covered TCP's connection lifecycle and its state-based security. This chapter covers how TCP
actually achieves *reliability and performance* — retransmission, sliding windows, flow control, and
congestion control — and why those mechanics matter to a security engineer. They are not just performance
trivia:

1. **Slow-read and window-manipulation attacks** exploit flow control directly. A malicious client that
   advertises a tiny receive window (or reads slowly) ties up server resources per connection — the
   "slow" DoS family (Slowloris' cousin), an attack *on TCP's flow-control mechanism* (Chapter 3 §5.1).
2. **Performance is availability, and availability is security.** Understanding buffers, windows, and
   retransmission is understanding where connections stall, where per-connection memory is consumed (a DoS
   surface), and why a reverse proxy that absorbs slow clients is a security control (Chapter 3 §12).
3. **TCP behavior reveals things in analysis** — retransmissions, resets, and window changes in a packet
   capture (Chapter 24) tell you about loss, attacks, and middlebox interference; RTT and congestion
   behavior distinguish normal from anomalous traffic.
4. **Buffer sizing and tuning intersect with DoS resistance** — send/receive buffers are per-connection
   kernel memory (Chapter 3 §5.1), so their sizing bounds how many connections a host can hold and how
   slow-client attacks scale.

The core idea: **TCP guarantees reliable, ordered delivery over lossy IP by numbering bytes, acknowledging
them, retransmitting what is lost, and pacing the sender via two windows — the receiver's advertised window
(flow control, "don't overwhelm the receiver") and the sender's congestion window (congestion control,
"don't overwhelm the network"). These windows and buffers are per-connection state and resources, which is
why they are both performance knobs and DoS surfaces.** Chapter 19 was TCP's connection state; Chapter 20
is TCP's data-transfer machinery, and its security relevance is that this machinery consumes per-connection
resources that attackers exhaust and that defenders bound.

---

## 2. Prerequisites

- Chapter 19 (TCP state machine, sequence/ack numbers, the header) — this chapter is the data-transfer
  half. Chapter 3 §5.1 (socket buffers, slow-read DoS) and §5.3 (C10k, connection resources).
- Chapter 18 (UDP contrast — UDP has none of this; the application must provide it if wanted).
- Chapter 24 preview (packet analysis — you will read retransmissions and windows there).

---

## 3. Mental Model

**TCP makes lossy IP reliable by acknowledging received bytes and retransmitting unacknowledged ones, and
it paces the sender with two windows: the receiver says "I can accept this much" (flow control) and the
sender infers "the network can carry this much" (congestion control). The smaller of the two governs how
much unacknowledged data is in flight.**

```
   Reliability:  every byte is numbered (Ch.19); receiver ACKs the next expected byte;
                 unacked data is RETRANSMITTED after a timeout (or fast-retransmit on duplicate ACKs).

   Two windows limit "bytes in flight" (sent but not yet ACKed):
     RECEIVE WINDOW (rwnd): advertised by the receiver -> "my buffer has this much space" (FLOW control)
     CONGESTION WINDOW (cwnd): computed by the sender  -> "the network seems to tolerate this much"
     Sender can have in flight: min(rwnd, cwnd) bytes.

   Flow control:      protect the RECEIVER from being overwhelmed (rwnd).
   Congestion control: protect the NETWORK from being overwhelmed (cwnd).
```

Three ideas:

1. **Reliability via ACK + retransmit.** The receiver acknowledges bytes; the sender retransmits anything
   not acknowledged within a timeout (RTO) or upon detecting loss (duplicate ACKs → fast retransmit). This
   is what makes TCP "reliable" — and the retransmission behavior is visible in captures (a diagnostic and
   attack signal).
2. **Two windows, two purposes.** The **receive window (rwnd)** is flow control — the receiver tells the
   sender how much buffer space it has, so a slow receiver is not overwhelmed. The **congestion window
   (cwnd)** is congestion control — the sender probes how much the *network* can carry (slow start,
   congestion avoidance) and backs off on loss. The sender is limited by the *minimum* of the two.
3. **Windows and buffers are per-connection resources — hence a DoS surface.** The receive window maps to a
   receive buffer; the send window to a send buffer (Chapter 3 §5.1). These are per-connection kernel
   memory, so many connections (or connections that deliberately keep buffers full) consume memory — the
   slow-read attack (a client advertising a tiny/zero window keeps the server's send buffer full, tying up
   memory per connection).

**The security framing:** TCP's reliability and pacing machinery is mostly about correctness and
performance, but its security relevance is concentrated in one place: **the windows and buffers are
per-connection state and resources that attackers exhaust (slow-read, window manipulation, connection
hoarding) and defenders bound (timeouts, connection limits, buffer sizing, reverse-proxy absorption).** And
because TCP provides reliability but *not security* (Chapter 19 §5), all of this operates below TLS —
performance and DoS-resistance concerns, not confidentiality/integrity, which remain TLS's job.

---

## 4. Fundamentals

### 4.1 Reliability: ACKs, retransmission timeout, and fast retransmit

TCP guarantees delivery by tracking what has been acknowledged and retransmitting what has not:

```
   Sender sends bytes 1-1000 (seq=1, 1000 bytes).
   Receiver ACKs: ack=1001 ("I have everything up to byte 1000; send me 1001 next").
   If the ACK does not arrive within the RETRANSMISSION TIMEOUT (RTO), the sender RETRANSMITS.
   RTO is derived from the measured Round-Trip Time (RTT) + variance (adaptive).

   FAST RETRANSMIT (don't wait for the full RTO):
     If a segment is lost, the receiver keeps ACKing the last in-order byte (DUPLICATE ACKs).
     3 duplicate ACKs -> the sender retransmits the missing segment immediately (before RTO).
```

Security/analysis relevance:

- **Retransmissions in a capture** (Chapter 24) indicate loss — from congestion, a lossy link, or an
  attack (e.g. an attacker dropping/injecting packets). A burst of retransmissions can signal network
  problems or interference.
- **RTO and RTT** are measured, so an attacker who can influence timing (adding latency) can affect TCP
  behavior; and RTT is used in some fingerprinting.
- **Selective Acknowledgment (SACK)** — a TCP option letting the receiver acknowledge non-contiguous
  blocks (so the sender retransmits only the truly missing segments) — improves efficiency but has had
  security bugs (the SACK Panic CVE-2019-11477, a remotely-triggerable kernel panic via crafted SACKs — a
  reminder that even TCP's optimization machinery is attack surface).

### 4.2 Flow control: the receive window (rwnd)

**Flow control** prevents a fast sender from overwhelming a slow receiver's buffer. The receiver advertises
its **receive window (rwnd)** — the amount of buffer space it currently has — in every ACK's window field
(Chapter 19 §4.1). The sender must not have more than `rwnd` bytes unacknowledged in flight.

```
   Receiver buffer has 64 KB free -> advertises rwnd=65535.
   Sender sends up to 64 KB unacked, then WAITS for ACKs (which free buffer space and re-advertise rwnd).
   If the receiver's application reads slowly, the buffer fills, rwnd shrinks toward 0.
   rwnd=0 (ZERO WINDOW) -> "stop sending; my buffer is full" -> sender pauses (sends window probes).
```

The security relevance is direct — this is the mechanism the **slow-read attack** exploits:

```
   SLOW-READ ATTACK (the flow-control DoS):
   A malicious client establishes a connection, requests a large response, then reads VERY SLOWLY
     (or advertises a tiny/zero receive window).
   The server's SEND buffer for that connection stays full (it cannot send more; rwnd is ~0), tying up
     per-connection memory and a worker/connection slot.
   Many such connections exhaust the server's memory/connection slots -> DoS.
```

The slow-read attack is the read-side twin of Slowloris (Chapter 3 §5, which withholds request data);
slow-read withholds *reading the response*, weaponizing flow control. **Window scaling** (an option
allowing windows larger than 64 KB, needed for high-bandwidth×delay paths) also interacts here — and
tiny-window advertisements are the attack. Defenses: **timeouts** (a connection that makes no progress is
dropped), **connection limits**, **minimum data-rate requirements** (drop connections that read/write
below a threshold), and a **reverse proxy** that absorbs slow clients before the application (Chapter 3
§12) — the same defenses as Slowloris, because both attack per-connection resources.

### 4.3 Congestion control: the congestion window (cwnd)

**Congestion control** prevents senders from overwhelming the *network* (routers, links). Unlike flow
control (which the receiver signals explicitly via rwnd), congestion is *inferred* by the sender from loss
and delay. The sender maintains a **congestion window (cwnd)** and adjusts it:

```
   SLOW START: cwnd starts small (a few segments), DOUBLES each RTT -> exponential ramp-up.
   CONGESTION AVOIDANCE: after a threshold (ssthresh), cwnd grows LINEARLY (careful probing).
   ON LOSS (the congestion signal): cwnd is CUT (halved for fast recovery, or reset for RTO) -> back off.
   -> The sender continuously probes for available bandwidth and backs off when the network signals stress.

   Algorithms: Reno/NewReno (loss-based), CUBIC (default on Linux; loss-based, optimized for high BDP),
     BBR (Google; model-based, uses bandwidth+RTT estimates rather than loss) — different tradeoffs.
```

Security relevance (subtler than flow control, but real):

- **Congestion control assumes cooperative senders.** A sender that ignores congestion signals (does not
  back off on loss) gets an unfair share and can contribute to congestion collapse — the basis of some
  "aggressive/unfair TCP" and DoS behaviors, and why the internet's stability depends on TCP stacks
  cooperating. Malicious or misconfigured stacks that do not back off are a network-abuse concern.
- **ECN (Explicit Congestion Notification)** lets routers signal congestion by marking packets (instead of
  dropping them), a performance improvement with its own edge cases (the CWR/ECE flags — Chapter 19 §4.1).
- **The bandwidth-delay product (BDP = bandwidth × RTT)** determines the optimal window; misconfigured
  windows (too small) throttle throughput, which is a performance/availability issue.
- **Congestion behavior is a fingerprinting/analysis signal** — different OSes/stacks use different
  algorithms (CUBIC vs BBR), observable in traffic patterns.

For a security engineer, the key congestion-control point is that it is a *cooperative* mechanism whose
abuse is mostly a fairness/stability concern, whereas flow control (§4.2) is the one directly weaponized as
a per-connection DoS (slow-read).

### 4.4 MSS, buffers, and per-connection resources

Two more mechanics that intersect with security:

- **MSS (Maximum Segment Size):** the largest payload a TCP segment carries, negotiated in the handshake
  (derived from the path MTU — Chapter 22). Mismatched MSS/MTU causes fragmentation or blackholing
  (Chapter 22's PMTU problems). MSS clamping is used at tunnels/VPNs to avoid these.
- **Send and receive buffers:** each connection has kernel send/receive buffers (Chapter 3 §5.1). Their
  sizes bound the window and consume per-connection memory. Sizing (`net.ipv4.tcp_rmem`/`tcp_wmem`, socket
  options) is a performance *and* DoS-resistance knob: larger buffers help throughput but let each
  connection consume more memory (fewer connections before exhaustion); smaller buffers limit per-
  connection memory (more connections, less throughput each). This is the direct link between TCP tuning
  and DoS resistance — buffer sizing determines how slow-client and connection-hoarding attacks scale.

### 4.5 Nagle, delayed ACK, and application-visible behavior

Two optimizations that occasionally surprise:

- **Nagle's algorithm:** batches small writes to avoid sending many tiny segments (coalesces until an ACK
  arrives or enough data accumulates). Good for bulk, bad for latency-sensitive small messages (adds
  delay). Disabled with `TCP_NODELAY` for interactive/low-latency protocols.
- **Delayed ACK:** the receiver waits briefly before ACKing, hoping to piggyback the ACK on outgoing data.
  Nagle + delayed ACK can interact badly (a stall). Mostly a performance concern, but relevant to
  understanding latency anomalies and some timing behaviors.

These are performance details, not security controls, but knowing them prevents misdiagnosing latency
issues as attacks and vice versa.

---

## 5. Deep Technical Explanation: TCP Performance Mechanics as a Security Surface

TCP's reliability/performance machinery is mostly about correctness and speed, but three security-relevant
themes emerge from it, each already foreshadowed:

**1. Flow control is directly weaponizable (per-connection resource exhaustion).** The receive window
(§4.2) exists to protect a slow receiver, but a *malicious* client uses it in reverse — advertising a
tiny/zero window or reading slowly to keep the *server's* send buffer full, consuming per-connection memory
and a connection slot indefinitely. This is the slow-read attack, the flow-control twin of Slowloris. It is
the clearest example of a performance mechanism becoming an attack: the feature (flow control, so slow
receivers work) is the vulnerability (slow receivers weaponized). The defense is the same as all
per-connection resource attacks (Chapter 3 §5, Chapter 19 §5): bound the resource (connection limits,
buffer sizing, timeouts, minimum data rates) and absorb abuse at a purpose-built front-end (reverse proxy)
before it reaches the application's precious workers.

**2. Buffers and windows are per-connection kernel memory — the DoS math.** Every connection consumes send
+ receive buffers (§4.4, Chapter 3 §5.1). The host's total memory bounds the number of concurrent
connections it can hold, so:

```
   max concurrent connections ≈ available memory / (per-connection buffer size + other per-conn state)
```

An attacker who opens many connections (or holds them via slow-read/Slowloris) consumes this memory. Buffer
sizing is thus a DoS-resistance decision: smaller buffers allow more concurrent connections (better against
connection-hoarding) but less throughput each; larger buffers give throughput but fewer connections before
exhaustion. This is the concrete link between "TCP tuning" and "DoS resistance," and it is why capacity
planning and security overlap. A reverse proxy (Chapter 3 §12) changes the math by absorbing many
(possibly malicious slow) client connections with efficient event-driven handling, protecting the
backend's per-connection-heavy workers.

**3. Congestion control is cooperative — and its abuse is a fairness/stability concern.** Unlike flow
control (weaponized per-connection), congestion control (§4.3) is a *network-wide cooperative* mechanism.
A well-behaved sender backs off on loss; a misbehaving one (ignoring congestion signals) grabs an unfair
share and can worsen congestion. This is mostly a stability/fairness issue rather than a targeted attack,
but it matters for: understanding "aggressive" traffic in analysis, recognizing that the internet's
stability depends on cooperative TCP stacks, and knowing that DDoS traffic often does *not* implement
congestion control (it does not care about fairness), which is a distinguishing characteristic.

The unifying insight, consistent with Chapters 3 and 19: **TCP's data-transfer machinery centers on
per-connection state and resources (buffers, windows), and the security relevance is that these are finite
and exhaustible.** Flow control is weaponized directly (slow-read); buffer sizing is the DoS-resistance
knob; congestion control's abuse is a fairness concern. And throughout, TCP provides *reliability and
performance, not security* — TLS on top provides confidentiality and integrity, and these performance
mechanics operate below it. The security engineer's takeaways: bound per-connection resources, absorb slow/
hoarding clients at the edge, size buffers with DoS-resistance in mind, and read TCP performance behavior
(retransmissions, zero windows, resets) as diagnostic and attack signals.

---

## 6. Internals: Observing TCP Performance

### 6.1 See windows, retransmissions, and RTT

```bash
$ ss -tin                          # -i shows internal TCP info: cwnd, rtt, retransmits, etc.
ESTAB ... cubic wscale:7,7 rto:204 rtt:3.5/1.7 mss:1448 cwnd:10 bytes_sent:... retrans:0/2 ...
# Read: congestion algo (cubic), window scale, RTO, RTT, MSS, cwnd (congestion window),
#       retrans (retransmissions) -- the performance state of the connection.

$ sudo tcpdump -n 'tcp port 443' -v | grep -iE 'win |retrans'   # window sizes and retransmissions
# In Wireshark (Chapter 24): "TCP Retransmission", "TCP ZeroWindow", "TCP Window Full" annotations.
```

`ss -tin` exposes the per-connection performance state (cwnd, rtt, retransmits, window scale). A connection
with a persistently near-zero window (`ss` shows a small window) and no progress is a slow-read signature
(§4.2); high retransmits indicate loss/interference (§4.1).

### 6.2 Buffer sizing (the DoS-resistance knob)

```bash
$ cat /proc/sys/net/ipv4/tcp_rmem        # receive buffer: min default max (auto-tuned within range)
4096   131072   6291456
$ cat /proc/sys/net/ipv4/tcp_wmem        # send buffer: min default max
4096   16384    4194304
$ cat /proc/sys/net/core/somaxconn        # max accept-backlog (Chapter 19)
# These bound per-connection memory (and thus max concurrent connections) -- the §5 DoS math.
```

These buffer settings are the per-connection memory knob (§4.4, §5): they bound throughput and, inversely,
how many connections the host can hold before memory exhaustion — a security-relevant tuning decision.

### 6.3 Congestion algorithm and behavior

```bash
$ sysctl net.ipv4.tcp_congestion_control      # e.g. cubic (default) or bbr
$ cat /proc/sys/net/ipv4/tcp_available_congestion_control
$ ss -tin | grep -o 'cubic\|bbr' | sort | uniq -c    # which algo connections are using
```

Knowing the congestion algorithm helps interpret traffic behavior (§4.3) and is occasionally a
fingerprinting signal.

### 6.4 Detect slow-read / window attacks

```bash
# Connections with a full/zero window and no progress over time = slow-read signature (§4.2):
$ ss -tin state established | grep -iE 'wnd:0|window' 
# Watch for many connections with Send-Q high and no advancement:
$ watch -n2 'ss -tn state established | awk "\$2 > 0" | wc -l'    # connections with unsent (stuck) data
# In production: alert on many long-lived connections with stalled send queues (proxy metrics).
```

Many established connections with a stuck send queue (data queued but not going out because rwnd is ~0) is
the slow-read attack signature — a per-connection-resource DoS in progress.

---

## 7. Real-World Example: TCP Performance and DoS in the Ledger Environments

**Ledger's TCP performance/DoS considerations:**

- **Slow-read and slow-write (Slowloris) attacks** target Ledger's connection resources. The defense is
  the reverse-proxy pattern (Chapter 3 §12): **Nginx (System A) / ALB + CloudFront (System B) absorb slow
  clients** with efficient event-driven handling, applying timeouts and connection limits *before* requests
  reach the application's per-connection-heavier workers (Kestrel threads, ECS tasks). This is why "front
  the app with a proxy" is a security control, not just performance — it protects the fragile backend from
  per-connection resource exhaustion (flow-control abuse).
- **Buffer sizing and connection capacity:** Ledger's hosts have finite memory, so per-connection buffers
  bound how many connections each can hold (§5). Under a connection-hoarding attack, the edge (proxy/ALB)
  holds the many client connections (efficiently), and the backend holds far fewer (to the proxy) — the
  proxy changes the DoS math in Ledger's favor. In the cloud, the ALB/CloudFront and AWS Shield (Chapter
  85) absorb volumetric and slow attacks at scale.
- **Timeouts and minimum data rates:** Ledger configures client/header/body/send timeouts at the edge
  (Chapter 3 §11) so connections that make no progress (slow-read/Slowloris) are dropped, freeing
  resources.
- **Retransmissions and analysis:** in incident/performance analysis, `ss -tin` and packet captures
  showing retransmissions, zero windows, or resets help distinguish network problems, middlebox
  interference, and attacks (e.g. a burst of zero-window connections = a slow-read attack in progress).
- **Congestion control cooperation:** Ledger's stacks use CUBIC/BBR (cooperative); DDoS traffic hitting
  Ledger typically does not implement congestion control (it does not care about fairness), a
  distinguishing signal that edge scrubbing (Shield) uses.

The Ledger takeaway: **TCP's flow-control and buffer mechanics are per-connection resources that slow-read/
Slowloris attacks exhaust, defended by the reverse-proxy pattern (absorb slow clients at the edge),
timeouts/connection limits, buffer sizing, and edge scrubbing — while TLS (above TCP) secures the data.**
The performance machinery of this chapter is, security-wise, about bounding and absorbing per-connection
resource consumption — the recurring "finite resources are DoS targets" theme (Chapters 3, 19) applied to
TCP's data-transfer layer.

---

## 8. Hands-On Demonstration

### LAB 20.1 — TCP Flow Control, the Slow-Read Attack, and Reverse-Proxy Defense

**Objective.** Observe TCP windows/retransmissions/RTT in `ss`, demonstrate (in an isolated lab) the
slow-read attack exhausting server connection resources via flow control, and show how a reverse proxy /
timeouts defend it.

**Cost.** Free. **Environment.** ENV-1 + ENV-2 (isolated). **Time.** 60 minutes.

**Ethics note.** Slow-read/DoS is demonstrated only against your own isolated container.

**Steps.**

*Step 1 — Observe TCP performance state.*

```bash
# Start a large download and watch its TCP internals:
curl -s -o /dev/null https://speed.hetzner.de/100MB.bin &
sleep 2
ss -tin | grep -A1 hetzner || ss -tin | head -5
# Identify: cwnd (congestion window), rtt, mss, wscale, retrans -- the §4 mechanics live.
kill %1 2>/dev/null
```

*Step 2 — See flow control (window) in a capture.*

```bash
sudo tcpdump -n 'tcp port 443' -c 20 -v 2>/dev/null | grep -oE 'win [0-9]+' | head
# The 'win' values are the advertised receive windows (rwnd, §4.2), changing as buffers fill/drain.
```

*Step 3 — Demonstrate the slow-read attack (isolated lab).*

```bash
docker network create slowlab 2>/dev/null || true
# A backend server WITHOUT a protective proxy, with a limited worker/connection count:
docker run -d --name backend --network slowlab nicolaka/netshoot sh -c '
  python3 -c "
import http.server, socketserver
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header(\"Content-Length\",\"10000000\"); self.end_headers()
        self.wfile.write(b\"x\"*10000000)   # large response the attacker reads slowly
socketserver.ThreadingTCPServer((\"0.0.0.0\",8080), H).serve_forever()
"'
BACKEND=$(docker inspect -f '{{(index .NetworkSettings.Networks "slowlab").IPAddress}}' backend)
# Attacker opens many connections and reads VERY slowly (advertising a tiny window):
docker run -d --name slowreader --network slowlab nicolaka/netshoot sh -c "
python3 - <<'PY'
import socket, time
conns=[]
for i in range(200):
    try:
        s=socket.socket(); s.connect(('${BACKEND}',8080))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512)   # tiny receive buffer -> small window
        s.send(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
        conns.append(s)                                           # hold open, read almost nothing
    except Exception as e: break
print('opened', len(conns), 'slow connections')
time.sleep(600)  # hold them, reading nothing -> server send buffers stay full
PY"
sleep 5
# Observe the server's stuck connections (send queue full, window ~0):
docker exec backend sh -c 'ss -tn state established | wc -l; echo "--- send-queues:"; ss -tn state established | awk "\$2>0" | head'
```

**Expected:** the server has many established connections with full send queues (data queued but not sent
because the slow reader's window is ~0), consuming per-connection memory/threads — the slow-read
flow-control DoS. New legitimate clients contend for the exhausted resources.

*Step 4 — Defend with a reverse proxy and timeouts.*

```bash
docker rm -f slowreader 2>/dev/null
# Front the backend with nginx applying timeouts + connection limits (absorbs slow clients):
docker run -d --name proxy --network slowlab -e BACKEND=$BACKEND nicolaka/netshoot sh -c '
  apk add --no-cache nginx 2>/dev/null
  cat > /etc/nginx/http.d/default.conf <<EOF
server {
  listen 80;
  client_body_timeout 5s; client_header_timeout 5s; send_timeout 5s;
  limit_conn_zone \$binary_remote_addr zone=perip:10m; limit_conn perip 10;
  location / { proxy_pass http://'$BACKEND':8080; proxy_read_timeout 5s; }
}
EOF
  nginx -g "daemon off;"'
# Now the proxy drops slow/idle connections via timeouts and caps per-IP connections, protecting the backend.
```

**Security implications.** Write down: (a) the slow-read attack weaponizes flow control (a tiny window
keeps the server's send buffer full, tying up per-connection resources); (b) it is the read-side twin of
Slowloris; (c) buffers/windows are per-connection memory, so the DoS math is memory ÷ per-connection buffer
(§5); (d) the defenses are timeouts, connection limits, buffer sizing, and a reverse proxy that absorbs
slow clients before the fragile backend; (e) TLS (above TCP) is unrelated to this — it is a resource/
availability attack, not a confidentiality one.

**Cleanup.**
```bash
docker rm -f backend slowreader proxy 2>/dev/null; docker network rm slowlab 2>/dev/null
```

---

## 9. Security Implications

- **TCP's reliability/performance machinery centers on per-connection state and resources (buffers,
  windows), which are finite and therefore a DoS surface** — the Chapter 3 §5 / Chapter 19 §5 theme applied
  to data transfer.
- **Flow control (the receive window) is directly weaponizable** — the **slow-read attack** advertises a
  tiny/zero window (or reads slowly) to keep the server's send buffer full, exhausting per-connection
  memory and connection slots (the read-side twin of Slowloris).
- **Buffer sizing is a DoS-resistance knob** — per-connection buffers bound throughput and, inversely, how
  many connections a host can hold before memory exhaustion (max connections ≈ memory ÷ per-connection
  buffer). TCP tuning and DoS resistance overlap.
- **Congestion control is cooperative** — its abuse (ignoring congestion signals) is mostly a fairness/
  stability concern, and DDoS traffic typically ignores it (a distinguishing signal).
- **The reverse-proxy pattern is a security control** — absorbing slow/hoarding clients at an efficient,
  purpose-built front-end protects the backend's per-connection-heavy workers (Chapter 3 §12).
- **Retransmissions, zero windows, and resets are diagnostic/attack signals** in captures and `ss` —
  distinguishing loss, interference, and slow-read attacks.
- **TCP provides reliability/performance, not security** — these mechanics operate below TLS, which
  provides confidentiality/integrity (Chapter 19 §5).

---

## 10. Attack Scenarios

1. **Slow-read attack** (§4.2, §5): advertise a tiny/zero receive window or read slowly to keep the
   server's send buffer full, exhausting per-connection resources → DoS. Defense: timeouts, connection
   limits, minimum data rates, reverse-proxy absorption.
2. **Slowloris (slow-write)** (Chapter 3 §5): withhold request data to hold connections open — the write-
   side twin; same defenses.
3. **Connection hoarding / exhaustion** (§5, Chapter 3): open many connections to exhaust per-connection
   memory/fds/worker slots. Defense: connection limits, buffer sizing, reverse proxy, edge scrubbing.
4. **SACK Panic (CVE-2019-11477)** (§4.1): crafted TCP SACK options triggering a kernel panic — even TCP's
   optimization machinery is attack surface. Defense: patch kernels; the class-elimination reminder
   (Chapter 1).
5. **Congestion-control abuse / unfair TCP** (§4.3): ignoring congestion signals for an unfair share /
   contributing to congestion — a fairness/stability concern; DDoS traffic ignoring congestion control.
6. **Window/RTT manipulation and timing attacks** (§4.1): influencing RTT/timing to affect TCP behavior or
   for fingerprinting — subtle, mostly analysis-relevant.
7. **MSS/MTU-based blackholing** (§4.4, Chapter 22): mismatched MSS/MTU causing connections to hang — a
   reliability failure that can be induced.

---

## 11. Defensive Techniques

- **Front applications with a reverse proxy / load balancer** (Nginx, ALB, CloudFront) that absorbs slow
  and hoarding clients with efficient event-driven handling, applying timeouts and connection limits before
  requests reach the per-connection-heavy backend (Chapter 3 §12) — the primary defense against
  flow-control/slow-client DoS.
- **Set aggressive timeouts and connection limits** — client/header/body/send/read timeouts,
  `limit_conn`/`limit_req`, and minimum-data-rate enforcement so connections that make no progress
  (slow-read/Slowloris) are dropped (Chapter 3 §11).
- **Size buffers with DoS resistance in mind** — smaller per-connection buffers allow more concurrent
  connections (better against hoarding); tune `tcp_rmem`/`tcp_wmem` and socket buffers to balance
  throughput and connection capacity (§4.4, §5).
- **Use edge scrubbing for volumetric and slow attacks** — AWS Shield (Chapter 85), which also distinguishes
  DDoS traffic (often no congestion control) from legitimate traffic.
- **Patch kernels** — TCP stack CVEs (SACK Panic, etc.) are remotely triggerable; keep stacks current
  (class-elimination, Chapter 1).
- **Monitor TCP performance state** — `ss -tin` for cwnd/rtt/retransmits, and alert on many connections
  with stalled send queues / zero windows (slow-read signature) and high retransmission rates
  (loss/interference/attack).
- **Ensure correct MSS/MTU handling** — MSS clamping at tunnels/VPNs to avoid PMTU blackholing (Chapter 22).
- **Remember TLS is separate** — these controls address availability/DoS; confidentiality/integrity remain
  TLS's job (Chapter 28).

---

## 12. Production Architecture

TCP performance/DoS controls, VPS vs cloud:

```
 CONCERN                  DEFENSE                          SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------   -------------------   -------------------------
 slow-read/Slowloris      reverse proxy + timeouts + limits nginx timeouts/limits ALB/CloudFront + WAF + Shield
 connection hoarding      limits + buffer sizing + edge     nginx limit_conn      ALB limits + Shield
 volumetric DoS           edge scrubbing                    provider/Cloudflare   AWS Shield (Ch85)
 buffer/capacity tuning   tcp_rmem/wmem, somaxconn           kernel tuning         instance sizing + ALB
 kernel TCP CVEs          patching                          patch cadence         managed nodes/Fargate patch
 analysis (retransmit/win) ss -tin + captures               same                  + VPC Flow Logs (Ch82)
 data confidentiality     TLS (separate concern)            TLS everywhere        TLS everywhere
```

The architectural principle: **TCP's data-transfer machinery is, security-wise, about per-connection
resources that attackers exhaust and defenders bound — so the architecture puts a resource-efficient,
purpose-built front-end (reverse proxy / load balancer / CDN) in front of the fragile, per-connection-heavy
application, applies timeouts and limits there, sizes buffers for connection capacity, and relies on edge
scrubbing for volume — while TLS (a separate layer) secures the data.** This is the reverse-proxy pattern
(Chapter 3 §12) justified from the TCP side: the proxy changes the DoS math by absorbing many (possibly
slow/malicious) client connections efficiently, protecting the backend. In the cloud, the ALB/CloudFront +
Shield provide this at scale. The recurring theme completes: TCP's reliability/performance mechanics matter
to security precisely because they define per-connection resource consumption, and defending availability
means bounding and absorbing that consumption.

---

## 13. Common Mistakes

1. **No timeouts/connection limits** — leaving slow-read/Slowloris and connection hoarding unmitigated.
2. **Exposing the application directly** without a reverse proxy to absorb slow/hoarding clients (Chapter 3
   §12).
3. **Oversized per-connection buffers** on a memory-constrained host — fewer connections before exhaustion
   (the §5 DoS math).
4. **Ignoring TCP-stack CVEs** (SACK Panic, etc.) — remotely triggerable kernel issues.
5. **Misreading retransmissions/zero-windows** as normal — missing loss/interference or a slow-read attack.
6. **Assuming performance and security are separate** — per-connection resource limits are both.
7. **MSS/MTU misconfiguration** at tunnels/VPNs — PMTU blackholing (Chapter 22).
8. **Confusing TCP-layer DoS with a confidentiality issue** — slow-read is availability; TLS is separate.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Server resources exhausted, many stuck connections | slow-read attack (flow-control DoS) | `ss -tn` full send queues / zero windows; add timeouts/proxy |
| High retransmission rate | packet loss (congestion, lossy link, interference) | `ss -tin` retrans; tcpdump for retransmissions (Chapter 24) |
| Poor throughput despite good bandwidth | small windows / BDP mismatch, or buffer limits | `ss -tin` cwnd/wscale; tune `tcp_rmem`/`tcp_wmem`; enable window scaling |
| Connections hang on certain paths | MSS/MTU mismatch (PMTU blackhole) | `ping -M do -s`; MSS clamping (Chapter 22) |
| Latency spikes on small interactive messages | Nagle + delayed ACK interaction | `TCP_NODELAY`; check application write pattern |
| Kernel panic / crash from crafted TCP | TCP stack CVE (e.g. SACK Panic) | patch kernel; check advisories |
| Server "up" but slow to accept | accept backlog full / worker exhaustion | `somaxconn`, `ss` LISTEN Send-Q; connection limits (Chapter 19) |

---

## 15. Practical Lab

Lab 20.1 is in §8. Register it in the lab index. Extension: benchmark the same backend with and without the
reverse proxy under a mixed load of fast and slow-read clients, measuring how many legitimate clients can be
served in each case — quantifying the reverse proxy's DoS-resistance benefit and the effect of buffer/
timeout tuning. This makes concrete that "front the app with a proxy" is a measurable availability/security
control, not just a performance one.

---

## 16. Exercises

### Concept questions

**20.1** Explain how TCP achieves reliability (ACKs, RTO, fast retransmit). What do retransmissions in a
capture indicate?

**20.2** Distinguish flow control (rwnd) from congestion control (cwnd) — what each protects, who signals
it, and what limits the sender.

**20.3** Explain the slow-read attack in terms of flow control, why it is the twin of Slowloris, and its
defenses.

**20.4** Explain why buffer sizing is a DoS-resistance knob, with the connection-capacity math.

**20.5** Why is congestion control's abuse a fairness/stability concern rather than a targeted attack, and
how does DDoS traffic relate to congestion control?

### Debugging problems

**20.6** A server is exhausting resources with many connections stuck with full send queues and near-zero
windows. Diagnose and remediate.

**20.7** A high-bandwidth transfer achieves poor throughput despite low loss. Diagnose using windows/BDP.

**20.8** Connections to one destination hang after the handshake. Diagnose (MSS/MTU) and fix.

### Security scenarios

**20.9** Design the defense against the full slow-client attack family (slow-read, Slowloris, connection
hoarding) for an internet-facing service, and explain how the reverse proxy changes the DoS math.

**20.10** Explain how TCP performance mechanics intersect with DoS resistance and why capacity planning and
security overlap.

### Architecture questions

**20.11** Explain the reverse-proxy pattern from the TCP-resource perspective: what per-connection resources
it protects and how (bridge to Chapter 3 §12 and Chapter 85).

**20.12** Explain the relationship between TCP (reliability/performance) and TLS (security), and which
layer addresses slow-read vs confidentiality.

### Hands-on exercises

**20.13** Observe cwnd, rtt, retransmits, and window scale for a real connection with `ss -tin` and explain
each.

**20.14** Demonstrate the slow-read attack and reverse-proxy/timeout defense in an isolated lab (Lab 20.1).

**20.15** Tune `tcp_rmem`/`tcp_wmem` and measure the effect on throughput and (conceptually) on connection
capacity.

### Interview questions

**20.16** "How does TCP achieve reliable delivery?"

**20.17** "What's the difference between flow control and congestion control?"

**20.18** "Explain the slow-read (or Slowloris) attack and how you'd defend against it."

**20.19** "How does buffer sizing relate to DoS resistance?"

**20.20** "Why is putting a reverse proxy in front of your app a security control, not just performance?"

---

## 17. Summary

- **TCP achieves reliability** by numbering bytes, acknowledging them, and **retransmitting** unacknowledged
  data (after the RTO, or via **fast retransmit** on duplicate ACKs); retransmissions in a capture signal
  loss/interference/attack.
- **TCP paces the sender with two windows**: the **receive window (rwnd)** — **flow control**, the receiver
  saying "my buffer has this much space" (protect the receiver) — and the **congestion window (cwnd)** —
  **congestion control**, the sender inferring "the network tolerates this much" from loss (protect the
  network, via slow start / congestion avoidance / backoff). The sender is limited by `min(rwnd, cwnd)`.
- **Flow control is directly weaponizable**: the **slow-read attack** advertises a tiny/zero window (or
  reads slowly) to keep the server's send buffer full, exhausting per-connection memory/slots — the
  read-side twin of Slowloris.
- **Windows/buffers are per-connection kernel memory**, so **buffer sizing is a DoS-resistance knob** (max
  connections ≈ memory ÷ per-connection buffer) — TCP tuning and DoS resistance overlap.
- **Congestion control is cooperative**; its abuse is a fairness/stability concern, and DDoS traffic
  typically ignores it (a distinguishing signal).
- **The reverse-proxy pattern is a security control** (Chapter 3 §12) — absorbing slow/hoarding clients at
  an efficient front-end protects the per-connection-heavy backend, changing the DoS math.
- **TCP provides reliability/performance, not security** — these mechanics operate below TLS, which
  provides confidentiality/integrity. Defenses: reverse proxy, timeouts, connection limits, buffer sizing,
  edge scrubbing, kernel patching; and read retransmissions/zero-windows/resets as diagnostic signals.

---

## 18. Knowledge Check

1. How does TCP retransmit lost data (RTO and fast retransmit)? (§4.1)
2. What is flow control vs congestion control, and what limits the sender? (§3, §4.2, §4.3)
3. Explain the slow-read attack and its defenses. (§4.2, §5)
4. Why is buffer sizing a DoS-resistance decision? (§4.4, §5)
5. Why is congestion control's abuse a fairness concern? (§4.3, §5)
6. How does the reverse-proxy pattern change the DoS math? (§5, §7)
7. What do retransmissions/zero-windows in a capture indicate? (§4.1, §6.4)
8. What was SACK Panic, and what does it illustrate? (§4.1)
9. Which layer addresses slow-read, and which addresses confidentiality? (§5)
10. What does `ss -tin` show about a connection's performance state? (§6.1)

---

## 19. Further Exploration

- RFC 5681 (TCP congestion control), RFC 6298 (RTO computation), RFC 2018 (SACK) — the reliability/
  performance mechanics.
- Read about CUBIC vs BBR congestion control — different philosophies (loss-based vs model-based) and their
  behaviors.
- The **SACK Panic (CVE-2019-11477)** advisory — TCP optimization machinery as attack surface.
- Capture a transfer in Wireshark (Chapter 24) and watch the window advertisements, retransmissions, and
  the congestion window's slow-start ramp.
- Run Lab 20.1 and quantify the reverse proxy's benefit (§15).
- Revisit Chapter 3 §5 and §12: this chapter is the TCP-mechanics justification for why per-connection
  resource limits and the reverse-proxy pattern are security controls.

---

## Solutions

### 20.2
**Flow control** protects the **receiver** from being overwhelmed: the receiver advertises its **receive
window (rwnd)** — the free space in its receive buffer — in every ACK, and the sender must not have more
than rwnd bytes unacknowledged in flight. It is *explicitly signaled* by the receiver, and a slow-reading
receiver shrinks rwnd toward zero, pausing the sender. **Congestion control** protects the **network**
(routers/links) from being overwhelmed: the sender maintains a **congestion window (cwnd)** that it grows
(slow start: doubling per RTT; then congestion avoidance: linear) and cuts on detecting loss (the
congestion signal), continuously probing available bandwidth and backing off under stress. It is *inferred*
by the sender (from loss/delay), not signaled by the receiver. The sender is limited by the **minimum of
rwnd and cwnd** — it cannot send more than the receiver can accept (flow) or than the network seems to
tolerate (congestion). Security-wise, flow control is directly weaponizable (slow-read: a tiny rwnd keeps
the server's send buffer full), while congestion control is a cooperative mechanism whose abuse is a
fairness/stability concern.

### 20.3
The slow-read attack weaponizes TCP flow control: an attacker establishes a connection, requests a large
response, and then reads the response **very slowly** (or advertises a tiny/zero receive window via a small
receive buffer). Because flow control forbids the server from sending more than the client's advertised
window, the server's **send buffer for that connection stays full** — it has data to send but cannot,
because rwnd is ~0 — tying up per-connection kernel memory and a connection/worker slot indefinitely. Many
such slow connections exhaust the server's memory and connection slots, denying service to legitimate
clients. It is the **read-side twin of Slowloris**: Slowloris withholds *sending* request data (keeping the
connection in a partial-request state), while slow-read withholds *reading* the response (keeping the send
buffer full) — both hold connections open with minimal traffic to exhaust per-connection resources, just at
opposite ends of the exchange. Defenses (the same for both, because both attack per-connection resources):
aggressive **timeouts** (drop connections that make no progress), **connection limits** (cap concurrent/
per-IP connections), **minimum data-rate enforcement** (drop connections reading/writing below a
threshold), and — the primary architectural defense — a **reverse proxy** that absorbs slow clients with
efficient event-driven handling before requests reach the per-connection-heavy application (Chapter 3 §12).

### 20.9
Defense against the slow-client family (slow-read, Slowloris, connection hoarding): (1) **Front the service
with a reverse proxy / load balancer / CDN** (Nginx, ALB, CloudFront) that handles connections with an
efficient event-driven model (epoll — Chapter 3 §5.3) and applies protections *before* the fragile backend.
(2) **Aggressive timeouts** — client/header/body/send/read timeouts so any connection making no progress is
dropped (defeats slow-read and Slowloris). (3) **Connection limits** — `limit_conn` per IP and overall, and
rate limits (`limit_req`), capping how many connections one source can hold. (4) **Minimum data-rate
enforcement** where available. (5) **Buffer sizing** tuned so per-connection memory allows many concurrent
connections (§5). (6) **Edge scrubbing** (AWS Shield) for volumetric attacks. How the reverse proxy changes
the DoS math: without it, each slow/hoarded connection consumes a *backend* worker/thread and its
per-connection buffers (expensive, and the backend has few workers), so relatively few malicious
connections exhaust the backend. With it, the many client connections (including slow/malicious ones) are
held by the *proxy*, which uses cheap event-driven handling and applies timeouts/limits, and the proxy
maintains only a small pool of connections to the backend — so the backend's precious per-connection-heavy
resources are protected, and the attacker must exhaust the far more resilient proxy instead. The proxy
converts "many expensive backend connections" into "many cheap proxy connections + few backend
connections," which is why fronting the app with a proxy is an availability/security control, not just
performance.

### 20.16
TCP achieves reliable delivery by numbering every byte with a sequence number and having the receiver
acknowledge the next byte it expects (the ack number). The sender tracks which bytes have been acknowledged
and retransmits any that are not: if an acknowledgment does not arrive within the **retransmission timeout
(RTO)** — an adaptive timer derived from the measured round-trip time and its variance — the sender resends
the unacknowledged data. To avoid waiting the full RTO, TCP also uses **fast retransmit**: when a segment is
lost, the receiver keeps acknowledging the last in-order byte (producing duplicate ACKs), and after three
duplicate ACKs the sender immediately retransmits the missing segment. **Selective Acknowledgment (SACK)**,
a TCP option, lets the receiver acknowledge non-contiguous received blocks so the sender retransmits only
the truly missing segments rather than everything after the loss. Together — sequence numbers, cumulative
ACKs, RTO-based and fast retransmission, and SACK — TCP turns lossy, unordered IP into a reliable, in-order
byte stream. Security/analysis notes: retransmissions in a capture indicate loss (congestion, a lossy link,
or interference/attack), and TCP's reliability machinery itself has been attack surface (SACK Panic
CVE-2019-11477), a reminder to patch kernels. Reliability is TCP's job; confidentiality/integrity is TLS's.

### 20.20
Because a reverse proxy protects the backend's finite per-connection resources by absorbing abusive
connection behavior at an efficient, purpose-built front-end. TCP connections consume per-connection kernel
memory (send/receive buffers) and, in a typical application server, a worker thread or slot each; the
backend has relatively few of these (Kestrel threads, ECS tasks), so slow-client attacks (slow-read,
Slowloris) and connection hoarding — which hold connections open with minimal traffic — can exhaust the
backend with a modest number of connections, denying service. A reverse proxy (Nginx, ALB, CloudFront) uses
an event-driven model (epoll — Chapter 3 §5.3) that holds tens of thousands of connections cheaply, applies
aggressive timeouts and connection/rate limits that drop non-progressing connections, and maintains only a
small pool of backend connections — so the many (possibly malicious/slow) client connections are absorbed
by the resilient proxy, and the backend's precious per-connection-heavy resources are shielded. It thereby
changes the DoS math from "few malicious connections exhaust the backend" to "the attacker must exhaust the
far more resilient proxy, while the backend stays healthy." This is a genuine availability/security control
(availability is a security property — CIA), not merely a performance optimization, and it is why "front
the app with a proxy/load balancer/CDN" appears as a security recommendation throughout the book (Chapter 3
§12, Chapter 85), justified here from TCP's per-connection-resource mechanics.

---

*This completes TCP (Chapters 19–20). Next: Chapter 21 — Sockets, Ports, Ephemeral Ranges, and the
Kernel's Connection Tables. We consolidate the transport layer by examining how the kernel manages sockets
and connection tables at scale — ephemeral port exhaustion, connection-table limits, and the resource
boundaries that TCP/UDP connections hit in high-scale and under-attack conditions.*
