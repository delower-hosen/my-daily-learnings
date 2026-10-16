# Chapter 19 — TCP Part 1: The State Machine, Handshake, Sequence Numbers, Teardown, RST, TIME_WAIT

---

## 1. Why This Matters

TCP is the transport under nearly everything you have secured so far — HTTP, TLS, SSH, database connections,
message brokers. This chapter and the next (Chapter 20) cover it in the depth the book demands, because
TCP's *connection state* is the thing that "stateful" firewalls and security groups track. When Chapter 76
says a security group is "stateful," it means it tracks the state machine you are about to learn. When
Chapter 37 covers conntrack, it is tracking TCP states. You cannot reason about stateful filtering without
knowing the states.

For a cloud security engineer, TCP Part 1 matters specifically because:

1. **The three-way handshake is the target of the SYN flood** — one of the classic DoS attacks — and its
   defense (SYN cookies) is a beautiful example of stateless defense against a state-exhaustion attack.
2. **Sequence numbers are TCP's weak "authentication"** — their predictability enabled connection
   hijacking and RST injection historically, and randomizing them (ISN randomization) is a real defense.
   This is the resistance to blind spoofing that UDP lacks (Chapter 18 §4.3).
3. **The state machine is what stateful firewalls/security groups track** (Chapters 37, 76). "Allow
   established/related" means "there is a state entry for this connection" — and the states, and their
   exhaustion (conntrack table), are security-relevant (Chapter 3 §5.4, Chapter 14 §4.2).
4. **RST and connection teardown** are used in censorship (RST injection), connection resets by
   middleboxes, and attacks — and `TIME_WAIT`/`CLOSE_WAIT` accumulation are operational-security issues
   you already met (Chapter 3 §Solutions 3.7, 3.8).
5. **Reading TCP flags and states in `ss`/tcpdump/Wireshark** (Chapters 3, 24) is a core incident and
   debugging skill — the flags byte you decoded in Chapter 7 §4.4 is here in full.

The core idea: **TCP provides a reliable, ordered, connection-oriented byte stream over unreliable IP by
establishing connection state (the three-way handshake), numbering every byte (sequence numbers) and
acknowledging receipt, and tearing the connection down cleanly — all governed by a state machine. That
connection state is TCP's strength (reliability, source verification) and its attack surface (state
exhaustion via SYN flood; hijacking via sequence prediction; RST injection).** Chapter 20 covers the
performance/reliability mechanics (retransmission, windows, congestion); Chapter 19 covers the connection
lifecycle and its security.

---

## 2. Prerequisites

- Chapter 18 (UDP — the contrast: TCP adds everything UDP omits), Chapter 3 (sockets, the 4-tuple,
  ephemeral ports, `TIME_WAIT`/`CLOSE_WAIT`), Chapter 7 §4.4 (the TCP flags byte).
- Chapter 10 (IP), Chapter 4 (the map, Stop 3).
- Forward: Chapters 37 (conntrack) and 76 (security groups) *depend on* this chapter's state machine —
  that dependency is recorded in BOOK_PROGRESS.

---

## 3. Mental Model

**TCP turns unreliable, unordered IP packets into a reliable, ordered byte stream between two endpoints by
maintaining connection state on both sides: it establishes a connection (handshake), numbers and
acknowledges every byte (sequence/ack numbers), retransmits what is lost (Chapter 20), and tears down
cleanly. A state machine governs the lifecycle, and that state is what stateful firewalls track.**

```
   The connection lifecycle (the state machine, simplified):

   CLOSED
     | (client) connect: send SYN
     v
   SYN_SENT  --receive SYN-ACK, send ACK-->  ESTABLISHED
                                                 |  (data flows both ways, reliably, in order)
                                                 |  either side closes: send FIN
                                                 v
                                            FIN_WAIT / CLOSE_WAIT ... -> TIME_WAIT -> CLOSED

   The THREE-WAY HANDSHAKE (establishment):
     Client --> SYN (seq=x)            "let's connect; my starting sequence is x"
     Server --> SYN-ACK (seq=y, ack=x+1) "ok; my starting sequence is y; I got your x"
     Client --> ACK (ack=y+1)           "got your y; we're connected"
     -> both sides now have connection state; ESTABLISHED.
```

Three ideas do the work:

1. **The handshake establishes shared state and verifies both endpoints.** After the three-way handshake,
   both sides agree on sequence numbers and know the other can send and receive at its address. This is why
   TCP resists blind spoofing (Chapter 18 §4.3): to complete the handshake, the initiator must receive the
   SYN-ACK and respond with the right ack number — a blind spoofer cannot. But establishing state also
   creates the **SYN flood** target (§4.2): half-open connections consume server state.
2. **Sequence numbers order and protect the stream.** Every byte has a sequence number; the receiver acks
   the next expected byte. This provides ordering and reliability (Chapter 20), and a weak form of
   protection: an off-path attacker who cannot see the sequence numbers cannot easily inject data or reset
   the connection — *if* the initial sequence numbers (ISNs) are unpredictable (§4.3). Predictable ISNs
   historically enabled hijacking.
3. **The state machine is what "stateful" means.** A stateful firewall/security group (Chapters 37, 76)
   tracks each connection's state; "allow established/related" permits packets belonging to a tracked
   connection. The states — SYN_SENT, ESTABLISHED, FIN_WAIT, TIME_WAIT, etc. — are the vocabulary of
   stateful filtering, and their exhaustion (the conntrack table) is a DoS surface.

**The security framing:** TCP's connection state gives it reliability and source verification (resisting
blind spoofing) — genuine security advantages over UDP. But that same state is an attack surface: SYN
floods exhaust the half-open-connection state; sequence prediction (if ISNs are weak) enables hijacking and
RST injection; and the connection-tracking state that firewalls maintain is itself exhaustible. Chapter 19
is the story of that state — how it is built (handshake), protected (sequence numbers, ISN randomization),
torn down (FIN/RST, TIME_WAIT), and attacked/defended.

---

## 4. Fundamentals

### 4.1 The TCP header and flags (Chapter 7 §4.4 in full)

The TCP header (20+ bytes, vs UDP's 8 — Chapter 18):

```
   Source Port (16) | Destination Port (16)
   Sequence Number (32)                          <- byte-number of the first byte in this segment
   Acknowledgment Number (32)                    <- next byte the sender EXPECTS to receive
   Data Offset (4) | Reserved | FLAGS (9 bits) | Window Size (16)   <- window: flow control (Ch.20)
   Checksum (16) | Urgent Pointer (16)
   Options (variable: MSS, window scale, SACK, timestamps -- Ch.20)
```

The **flags** (the byte you decoded in Chapter 7 §4.4), each governing the state machine:

| Flag | Meaning | Role |
|---|---|---|
| **SYN** | synchronize | opens a connection; carries the initial sequence number (ISN) |
| **ACK** | acknowledge | the ack number is valid; set on all packets after the initial SYN |
| **FIN** | finish | graceful close ("I have no more data to send") |
| **RST** | reset | abrupt termination ("this connection is invalid/refused/aborted") |
| **PSH** | push | deliver buffered data to the application now |
| **URG** | urgent | urgent data present (rarely used; a parsing-inconsistency source) |
| **ECE/CWR** | congestion signaling | ECN (Chapter 20) |

The handshake and teardown are choreographies of these flags:
- **SYN** → **SYN-ACK** (`0x02` → `0x12` in Chapter 7's decoding) → **ACK** (`0x10`): establishment.
- **FIN-ACK** (`0x11`) ↔ **ACK** (`0x10`): graceful teardown.
- **RST** (`0x04`): abrupt reset (a closed port replies with RST — Chapter 3; also RST-ACK `0x14`).

You can now read any TCP capture's flags (Chapter 24) and know the connection's state.

### 4.2 The three-way handshake and the SYN flood

Establishment (§3 restated with sequence detail):

```
   Client (CLOSED -> SYN_SENT):  SYN,  seq=x
   Server (LISTEN -> SYN_RCVD):  SYN-ACK, seq=y, ack=x+1     <- server allocates state for this half-open conn
   Client (SYN_SENT -> ESTABLISHED): ACK, ack=y+1
   Server (SYN_RCVD -> ESTABLISHED): (on receiving the ACK)
```

The security-critical detail: when the server receives the SYN and sends SYN-ACK, it **allocates state**
for the half-open connection (in the SYN backlog / SYN_RCVD state) while waiting for the final ACK. This is
the **SYN flood** target:

```
   SYN FLOOD:
   Attacker sends many SYNs (often with SPOOFED source IPs) but never sends the final ACK.
   The server allocates state for each half-open connection (SYN_RCVD), filling the SYN backlog.
   -> The backlog fills; the server cannot accept new legitimate connections -> DoS.
   (Spoofed sources also mean the SYN-ACKs go to victims, and no ACK ever returns.)
```

The SYN flood exhausts the server's half-open-connection state — an attack on TCP's *state establishment*.
The elegant defense is **SYN cookies** (§4.4): instead of allocating state on the SYN, the server encodes
the connection state into the ISN it sends in the SYN-ACK (a cryptographic function of the connection
tuple + a secret + time), allocating *no* state until the final ACK returns carrying that cookie back —
turning a stateful step into a stateless one, so there is no backlog to exhaust. This is a classic and
beautiful security pattern: **defend a state-exhaustion attack by making the step stateless.**

### 4.3 Sequence numbers, ISN randomization, and hijacking/RST injection

Every byte in a TCP stream has a **sequence number**; the **acknowledgment number** is the next byte the
receiver expects. This provides ordering and reliability (Chapter 20) and a weak security property:

- **To inject data or reset a connection, an attacker must supply a sequence number within the receiver's
  window** (Chapter 20). An *on-path* attacker sees the sequence numbers (so ARP spoofing → TCP hijacking
  is trivial — Chapter 9). An *off-path* attacker must *guess* the sequence numbers.
- **The Initial Sequence Number (ISN)** is chosen at connection setup. Historically, ISNs were predictable
  (incremented by a fixed amount, or time-based), which let off-path attackers **predict the ISN and hijack
  or spoof connections** (the classic Mitnick attack, 1994) or inject data. The defense is **ISN
  randomization** (RFC 6528): the ISN is a cryptographic function of the connection tuple + a secret, so it
  is unpredictable to an off-path attacker while still deterministic for the endpoints. Modern OSes do
  this; it is why blind TCP hijacking is hard today.
- **RST injection:** a forged RST with a valid sequence number tears down a connection. Off-path RST
  injection requires guessing the sequence number (within the window); it is used in **censorship** (e.g.
  the Great Firewall injects RSTs to kill connections to blocked content) and some attacks. On-path RST
  injection is trivial. Defenses: sequence-number validation (RFC 5961 tightened RST acceptance to reduce
  off-path injection), and — the backstop — **TLS**, which detects tampering (though a RST is a
  connection-level reset TLS cannot prevent, only detect the resulting failure).

The security synthesis: **sequence numbers give TCP resistance to *off-path* (blind) attacks that UDP
lacks — but only if ISNs are unpredictable, and only against off-path attackers.** An on-path attacker
(ARP/DHCP/routing MITM — Chapters 9, 12, 15) sees the sequence numbers and can hijack/reset at will, which
is why on-path position is so dangerous and why TLS (which authenticates the endpoints cryptographically,
not via sequence numbers) is the real defense.

### 4.4 SYN cookies (stateless defense against SYN flood)

The SYN cookie mechanism (§4.2 defense), in detail because it is a model security pattern:

```
   Normal handshake: server allocates state on SYN (vulnerable to flood).
   With SYN cookies (activated under SYN flood):
     1. Server receives SYN. Instead of allocating state, it computes a COOKIE:
          ISN = hash(client IP:port, server IP:port, secret, coarse timestamp) + encoded MSS
        and sends SYN-ACK with seq = cookie. NO STATE ALLOCATED.
     2. If the client is legitimate, it sends ACK with ack = cookie + 1.
     3. Server verifies the cookie (recompute the hash; check it matches ack-1). If valid, it
        RECONSTRUCTS the connection state from the cookie and moves to ESTABLISHED.
     -> A flood of SYNs allocates no state (no backlog to fill). A spoofed source never sends the
        valid ACK, so no state is ever created for it. The flood is defeated.
```

SYN cookies trade a small feature loss (some TCP options cannot be fully preserved) for immunity to SYN
floods, and modern kernels enable them automatically under backlog pressure
(`net.ipv4.tcp_syncookies=1`). The pattern — **encode the state into a value you hand the client and
require them to return it, so you hold no state until they prove liveness** — recurs in security
(stateless CSRF tokens, JWT sessions, capability tokens). It is worth internalizing as a general technique
for defending state-exhaustion attacks.

### 4.5 Connection teardown, RST, TIME_WAIT, and CLOSE_WAIT

Graceful teardown is a four-way exchange (each side closes independently — TCP is full-duplex):

```
   A --> FIN         (A: ESTABLISHED -> FIN_WAIT_1)   "I'm done sending"
   B --> ACK         (B: ESTABLISHED -> CLOSE_WAIT)    "ok, but I might still send"
   B --> FIN         (B: CLOSE_WAIT -> LAST_ACK)       "now I'm done too"
   A --> ACK         (A: FIN_WAIT_2 -> TIME_WAIT)      "ok"
   A waits 2*MSL in TIME_WAIT, then -> CLOSED.
```

The security/operational-relevant states (Chapter 3 §Solutions 3.7):

- **TIME_WAIT** (on the side that closed first — the *active closer*): the socket lingers for 2×MSL
  (maximum segment lifetime, ~60–120s) to (a) ensure the final ACK was received and (b) let any late/
  duplicate segments from the old connection die out before the tuple is reused. Accumulation of TIME_WAIT
  is normal for a busy active-closer (a load balancer, a client making many short connections); it is not
  a leak, but it consumes ephemeral ports/tuples and can cause port exhaustion under extreme rates.
  `SO_REUSEADDR` lets you rebind an address in TIME_WAIT (Chapter 3 §Solutions 3.15).
- **CLOSE_WAIT** (on the side that received the FIN but has not yet closed): means the *application has not
  called close()* after the peer closed. Accumulating CLOSE_WAIT is an **application bug** (a socket/fd
  leak — Chapter 3 §Solutions 3.7), leading to fd exhaustion. It is a real operational-security issue (a
  service that silently stops accepting connections).
- **RST** aborts a connection immediately (no graceful FIN exchange): a closed port replies RST (Chapter
  3), an application can force RST (`SO_LINGER` with timeout 0), and forged RSTs are used to kill
  connections (§4.3, censorship). RST is "this connection is invalid/gone," vs FIN's "I'm done sending."

Reading these states in `ss` (Chapter 3 §6.1) during an incident tells you the connection lifecycle:
many SYN_RCVD = possible SYN flood; many CLOSE_WAIT = an fd-leaking app; many TIME_WAIT = a busy active
closer (usually fine).

### 4.6 The state machine as the basis of stateful filtering

The whole point for a security engineer: **stateful firewalls, NAT, and security groups track this state
machine.** When Chapter 76 says a security group is stateful:

```
   Stateful firewall / security group behavior (Chapters 37, 76):
   - You write a rule for the INITIATING direction (e.g. "allow inbound TCP 443").
   - When a connection is established (the handshake completes), the firewall creates a STATE ENTRY
     tracking the connection's tuple and TCP state.
   - RETURN traffic (and related packets) is allowed automatically because it matches a state entry
     in ESTABLISHED state -- you do NOT need a separate rule for the replies.
   - The state entry is removed on teardown (FIN/RST) or timeout.
```

This is why a security group needs only an inbound rule and the outbound response is automatically allowed
(Chapter 76): the firewall tracks the TCP state machine and permits ESTABLISHED/RELATED traffic. It is the
same conntrack mechanism as NAT (Chapter 14 §Solutions 4.12) and Linux stateful iptables (Chapter 37). And
it inherits the same failure mode: **the state table is finite**, so many connections (legitimate or a
flood) can exhaust it (conntrack exhaustion — Chapter 3 §5.4, Chapter 14) — a DoS on the firewall's state.
Understanding TCP's state machine is thus directly understanding how stateful cloud/network filtering works
and fails.

---

## 5. Deep Technical Explanation: TCP State as Strength and Attack Surface

TCP's defining feature — connection *state* — is simultaneously its security strength and its attack
surface, and understanding both is the chapter's core lesson.

**State as strength (vs UDP):**

- **Source verification.** Completing the handshake requires receiving the SYN-ACK and returning the right
  ACK, so TCP resists *blind* (off-path) spoofing that UDP cannot (Chapter 18 §4.3). You cannot trivially
  forge a TCP connection's source the way you can a UDP datagram's — the handshake is a liveness/reachability
  proof. This is why TCP-based services are not reflection/amplification vectors the way UDP services are
  (Chapter 18 §4.4): an amplifier would need to complete the handshake, which a spoofed source cannot.
- **Ordering and reliability** (Chapter 20) prevent whole classes of data-corruption and reordering issues.
- **Sequence numbers** provide weak off-path-injection resistance (if ISNs are random — §4.3).

**State as attack surface:**

- **SYN flood** (§4.2): exhaust the half-open-connection state. Defended statelessly by SYN cookies (§4.4).
- **Sequence prediction / hijacking / RST injection** (§4.3): if ISNs are predictable, off-path attackers
  guess sequence numbers to inject/reset. Defended by ISN randomization + RFC 5961; on-path attackers
  bypass this (TLS is the real defense).
- **Connection-tracking state exhaustion** (§4.6): the stateful firewall's/NAT's/security group's state
  table is finite; floods (or leaks) exhaust it (conntrack exhaustion — Chapter 3, 14). Defended by sizing,
  timeouts, SYN cookies, and rate limiting.
- **CLOSE_WAIT/fd exhaustion** (§4.5): application bugs leaking sockets exhaust fds (Chapter 3). Defended
  by correct close() handling.
- **Slowloris and slow-read** (Chapter 3 §5): hold connections open with minimal data to exhaust
  per-connection resources (worker slots, buffers) — attacks on the *established* state's resources, not
  the handshake. Defended by timeouts, connection limits, and a reverse proxy absorbing slow clients
  (Chapter 3 §12).

The unifying insight: **every one of TCP's stateful attack surfaces is a form of resource exhaustion —
exhausting half-open state (SYN flood), connection-tracking state (conntrack), file descriptors
(CLOSE_WAIT, Slowloris), or worker slots (slow clients).** This is the "finite kernel resources are DoS
targets" theme from Chapter 3 §5.4, concentrated in TCP because TCP is where connection state lives. And
the defenses cluster around the same techniques: make the vulnerable step stateless (SYN cookies), bound
the resource (limits, timeouts), and absorb abuse before it reaches the fragile component (reverse proxy,
edge scrubbing). Meanwhile, the *confidentiality/integrity* of a TCP connection is not TCP's job at all —
TCP has no encryption or strong authentication; on-path attackers who see the sequence numbers can hijack
it, so **TLS on top is what actually secures the data** (Chapters 28, 9). TCP secures *delivery and, weakly,
against off-path injection*; TLS secures *the data against any on-path adversary*. Know which layer provides
which.

---

## 6. Internals: Observing TCP

### 6.1 Watch the handshake and teardown

```bash
$ sudo tcpdump -n -i any 'tcp port 443' -c 8
10:22:41 IP 10.0.1.5.51844 > 93.184.216.34.443: Flags [S], seq 1000000            # SYN
10:22:41 IP 93.184.216.34.443 > 10.0.1.5.51844: Flags [S.], seq 500, ack 1000001  # SYN-ACK
10:22:41 IP 10.0.1.5.51844 > 93.184.216.34.443: Flags [.], ack 501                 # ACK (established)
...  data flows ...
10:22:42 IP 10.0.1.5.51844 > 93.184.216.34.443: Flags [F.], ...                    # FIN (close)
10:22:42 IP 93.184.216.34.443 > 10.0.1.5.51844: Flags [F.], ...                    # FIN (peer close)
```

tcpdump flag notation: `[S]`=SYN, `[S.]`=SYN-ACK, `[.]`=ACK, `[F.]`=FIN-ACK, `[R]`=RST, `[P.]`=PSH-ACK.
This is Chapter 7 §4.4's flags byte and §3's state machine on the wire — the handshake, data, and teardown
visible in order.

### 6.2 See connection states

```bash
$ ss -tan                         # all TCP sockets and their states (Chapter 3 §6.1)
State       Recv-Q Send-Q  Local Address:Port  Peer Address:Port
LISTEN      0      511     0.0.0.0:443          0.0.0.0:*
ESTAB       0      0       10.0.1.5:443         10.0.1.9:52344
TIME-WAIT   0      0       10.0.1.5:51844       93.184.216.34:443
$ ss -tan state syn-recv | wc -l    # many SYN-RECV = possible SYN flood (§4.2)
$ ss -tan state close-wait | wc -l  # many CLOSE-WAIT = fd-leaking app (§4.5, Chapter 3 §Sol 3.7)
$ ss -tan state time-wait | wc -l   # many TIME-WAIT = busy active closer (usually fine, §4.5)
```

These state counts are core incident indicators: `syn-recv` spike (SYN flood), `close-wait` growth (app
bug), `time-wait` (busy closer).

### 6.3 SYN cookies and backlog

```bash
$ cat /proc/sys/net/ipv4/tcp_syncookies          # 1 = SYN cookies enabled (activate under flood) (§4.4)
$ cat /proc/sys/net/ipv4/tcp_max_syn_backlog      # the SYN backlog size (§4.2)
$ ss -tlpn | grep ':443'                          # Send-Q on LISTEN = the accept backlog
$ dmesg | grep -i 'syn flood'                     # kernel logs SYN flood detection / cookie activation
```

`tcp_syncookies=1` is the SYN-flood defense (§4.4); `dmesg` shows when the kernel detects a flood and
activates cookies. This is the stateless defense in action.

### 6.4 ISN randomization (verify)

```bash
# Modern kernels randomize ISNs (RFC 6528). Capture a few handshakes and confirm ISNs are unpredictable:
$ for i in 1 2 3; do sudo tcpdump -n -c1 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0' & \
    curl -s https://example.com >/dev/null; done
# The 'seq' values in the SYNs should be unrelated/unpredictable (not incrementing by a fixed amount).
```

Unpredictable ISNs are the defense against off-path sequence prediction/hijacking (§4.3); predictable ones
would be a finding (an ancient/misconfigured stack).

---

## 7. Real-World Example: TCP State in the Ledger Environments

**Ledger's TCP connections and their state-related security:**

- **The handshake and SYN floods:** Ledger's internet-facing endpoints (Nginx in System A, ALB/CloudFront
  in System B) are SYN-flood targets. Defenses: **SYN cookies** (`tcp_syncookies=1`) on the hosts; and in
  the cloud, **AWS Shield** (Chapter 85) and the ALB/CloudFront absorb SYN floods at the edge before they
  reach application instances — the edge as the SYN-flood shock absorber (the reverse-proxy pattern,
  Chapter 3 §12).
- **Stateful security groups (System B):** Ledger's security groups are stateful (Chapter 76) — they track
  the TCP state machine, so a rule allowing inbound 443 to the ALB automatically allows the return traffic,
  and app→RDS on 5432 (allowed outbound from the app SG) has its returns allowed by state. Ledger writes
  rules for the initiating direction; the state machine handles the rest.
- **Conntrack/state exhaustion:** under load or attack, the connection-tracking state (on hosts, NAT
  gateways, and firewalls) is finite (Chapter 3 §5.4, Chapter 14 §4.2); Ledger sizes limits, uses per-AZ
  NAT gateways, and relies on edge scrubbing to prevent state exhaustion from becoming a DoS.
- **CLOSE_WAIT / fd leaks:** if Ledger's app leaks sockets (unclosed `HttpClient`/DB connections — Chapter
  3 §Solutions 3.7), CLOSE_WAIT accumulates and the app silently stops accepting connections. Ledger
  monitors `ss` state counts and fd usage as leading indicators.
- **On-path hijacking and RST injection:** within the VPC, on-path TCP hijacking is not viable (the SDN
  prevents ARP spoofing — Chapters 8–9), but for traffic traversing untrusted networks (client→edge, or
  hybrid links), on-path attackers who see sequence numbers could hijack/reset — which is exactly why
  **TLS** protects all of it (the sequence numbers are irrelevant to an attacker who cannot decrypt or
  forge the TLS layer). ISN randomization defends off-path injection everywhere.

The Ledger takeaway: **TCP's connection state is both what makes Ledger's stateful security groups work
(Chapter 76) and what attackers target (SYN floods, state exhaustion, slow-client resource exhaustion) —
defended by SYN cookies, edge scrubbing, resource limits, and correct application close() handling — while
TLS secures the data against on-path attackers who could otherwise hijack the sequence-number-based
connection.** The state machine you learned here is the foundation for the stateful-firewall reasoning of
Chapters 37 and 76.

---

## 8. Hands-On Demonstration

### LAB 19.1 — TCP Handshake, States, and SYN-Flood Defense

**Objective.** Observe the three-way handshake and teardown on the wire, read connection states in `ss`,
verify SYN cookies, and demonstrate (in an isolated lab) the SYN-flood state-exhaustion mechanism and its
stateless defense.

**Cost.** Free. **Environment.** ENV-1 + ENV-2 (isolated). **Time.** 60 minutes.

**Ethics note.** SYN flooding is demonstrated only against your own isolated container. Never against
systems you do not own.

**Steps.**

*Step 1 — Watch a full connection lifecycle.*

```bash
sudo tcpdump -n -i any 'tcp port 443 and host example.com' -c 10 &
curl -s https://example.com > /dev/null
# Identify: [S] SYN, [S.] SYN-ACK, [.] ACK (established), [P.] data, [F.] FIN (teardown). (§6.1)
```

*Step 2 — Read connection states.*

```bash
ss -tan | head
ss -tan state established | wc -l    # active connections
ss -tan state time-wait | wc -l      # recently-closed (active closer)
# Note the states and map them to the state machine (§3, §4.5).
```

*Step 3 — Verify SYN cookies and backlog.*

```bash
cat /proc/sys/net/ipv4/tcp_syncookies         # should be 1 (§4.4)
cat /proc/sys/net/ipv4/tcp_max_syn_backlog     # the SYN backlog size (§4.2)
```

*Step 4 — Demonstrate SYN flood and defense (isolated).*

```bash
docker network create synlab 2>/dev/null || true
docker run -d --name target --network synlab nicolaka/netshoot sh -c 'python3 -m http.server 8080'
TARGET=$(docker inspect -f '{{(index .NetworkSettings.Networks "synlab").IPAddress}}' target)
docker run -d --name attacker --network synlab --cap-add NET_RAW nicolaka/netshoot sleep 3600

# With SYN cookies OFF (in the target's namespace), a SYN flood fills the backlog:
docker exec target sysctl -w net.ipv4.tcp_syncookies=0 2>/dev/null
docker exec target sysctl -w net.ipv4.tcp_max_syn_backlog=16 2>/dev/null   # small backlog to show the effect
# Flood SYNs from the attacker (hping3 if available, else a Python raw-socket flood):
docker exec -d attacker sh -c "hping3 -S -p 8080 --flood ${TARGET} 2>/dev/null || \
  python3 -c \"exec(open('/dev/stdin').read())\" <<'PY'
import socket,os
# crude SYN-ish flood via many connect attempts (illustrative in a lab)
for _ in range(2000):
    try:
        s=socket.socket(); s.setblocking(False); s.connect_ex(('${TARGET}',8080))
    except: pass
PY"
sleep 3
docker exec target ss -tan state syn-recv | wc -l    # backlog filling (SYN_RECV entries)
# Now enable SYN cookies -> no backlog exhaustion:
docker exec target sysctl -w net.ipv4.tcp_syncookies=1
docker exec target dmesg 2>/dev/null | grep -i 'syn flood' | tail -1   # kernel activates cookies
```

**Expected:** with cookies off and a small backlog, SYN_RECV entries accumulate (state exhaustion); with
cookies on, the kernel activates them under pressure and legitimate connections still succeed (no state
allocated on SYN). This demonstrates the state-exhaustion attack and the stateless defense.

*Step 5 — Observe a stateful-firewall analogy (conntrack).*

```bash
# Show that an established connection creates conntrack state (the basis of stateful SGs — §4.6):
docker exec target sh -c 'apk add --no-cache conntrack-tools 2>/dev/null; conntrack -L -p tcp 2>/dev/null | head'
# Each ESTABLISHED connection = one state entry; this is what a stateful SG tracks (Chapters 37, 76).
```

**Security implications.** Write down: (a) the handshake allocates state (SYN-flood target); (b) SYN
cookies defend by making the step stateless (encode state in the ISN, allocate none until the ACK returns);
(c) the state machine is what stateful firewalls/SGs track (established/related allowed automatically); (d)
state tables are finite (exhaustion DoS); (e) TLS, not sequence numbers, secures the data against on-path
attackers.

**Cleanup.**
```bash
docker rm -f target attacker 2>/dev/null; docker network rm synlab 2>/dev/null
```

---

## 9. Security Implications

- **TCP's connection state gives it source verification (resisting blind/off-path spoofing — unlike UDP)
  and reliability**, but that same state is the attack surface.
- **The three-way handshake allocates state, making it the SYN-flood target** — defended statelessly by
  **SYN cookies** (encode state in the ISN, allocate none until the ACK returns): a model
  "defend state-exhaustion by making the step stateless" pattern.
- **Sequence numbers provide weak off-path-injection resistance only if ISNs are unpredictable** (ISN
  randomization, RFC 6528/5961); on-path attackers see the sequence numbers and can hijack/RST-inject at
  will — so **TLS, not sequence numbers, is the real defense** for the data.
- **The state machine is what "stateful" firewalls/security groups track** (Chapters 37, 76) — "allow
  established/related" permits packets belonging to a tracked connection, so you write rules for the
  initiating direction and returns are automatic. The **state table is finite** (conntrack exhaustion DoS).
- **All of TCP's stateful attack surfaces are resource exhaustion** — half-open state (SYN flood),
  conntrack state, file descriptors (CLOSE_WAIT leaks, Slowloris), worker slots (slow clients) — the
  Chapter 3 §5.4 theme concentrated in TCP.
- **TCP secures delivery (and weakly, off-path injection); TLS secures the data** against any on-path
  adversary — know which layer provides which.

---

## 10. Attack Scenarios

1. **SYN flood** (§4.2): flood SYNs (often spoofed) to exhaust the half-open-connection backlog → DoS.
   Defense: SYN cookies, edge scrubbing (Shield), backlog sizing.
2. **TCP connection hijacking (sequence prediction)** (§4.3): off-path attacker predicts ISN/sequence to
   inject data or take over a connection (historically the Mitnick attack). Defense: ISN randomization; TLS.
3. **RST injection** (§4.3): forged RST with a valid sequence number tears down a connection — used in
   censorship (Great Firewall) and attacks. Defense: RFC 5961 sequence validation; TLS detects the
   resulting failure.
4. **On-path TCP hijacking/reset** (Chapter 9): an ARP/DHCP/routing MITM sees the sequence numbers and
   hijacks/resets trivially. Defense: TLS (the sequence numbers are useless to an attacker who cannot
   forge the TLS layer) + prevent on-path position.
5. **Conntrack/state-table exhaustion** (§4.6, Chapter 3 §5.4, Chapter 14): flood connections to exhaust
   the stateful firewall's/NAT's/SG's state table → DoS on the state. Defense: sizing, timeouts, SYN
   cookies, rate limiting.
6. **Slowloris / slow-read** (Chapter 3 §5): hold connections open with minimal data to exhaust worker
   slots/buffers/fds (attacks on established-state resources). Defense: timeouts, connection limits,
   reverse proxy absorbing slow clients.
7. **CLOSE_WAIT fd exhaustion** (§4.5, Chapter 3): an app bug leaking sockets exhausts fds → silent DoS.
   Defense: correct close() handling; monitor state counts.

---

## 11. Defensive Techniques

- **Enable SYN cookies** (`net.ipv4.tcp_syncookies=1`) — activate automatically under backlog pressure;
  the stateless defense against SYN floods (§4.4). Size `tcp_max_syn_backlog` appropriately.
- **Rely on edge scrubbing for volumetric SYN/TCP floods** — AWS Shield (Chapter 85), and let the
  ALB/CloudFront/reverse proxy absorb floods before application instances (Chapter 3 §12).
- **Ensure ISN randomization** (default on modern kernels — RFC 6528) and RFC 5961 sequence validation to
  resist off-path hijacking/RST injection; verify old/embedded stacks are not predictable.
- **Use TLS everywhere** — the real defense for the *data* against on-path attackers who could hijack/reset
  the sequence-number-based connection (TLS authenticates the endpoints cryptographically, not via sequence
  numbers) — Chapters 9, 28.
- **Bound connection-tracking state** — size conntrack tables (`nf_conntrack_max`), tune timeouts, use SYN
  cookies and rate limiting to prevent state-table exhaustion (Chapters 3, 14, 37); prefer stateful SGs
  with SG-references and monitor connection counts.
- **Set connection and timeout limits** — client/header/body timeouts, `limit_conn`/`limit_req` at the
  proxy (Chapter 3 §11) to defeat Slowloris/slow-read; a reverse proxy absorbs slow clients before workers.
- **Fix socket leaks** — correct `close()`/`Dispose()` on all paths to prevent CLOSE_WAIT/fd exhaustion
  (Chapter 3 §Solutions 3.7); monitor `ss` state counts and fd usage as leading indicators.
- **Monitor TCP state counts** — `ss` SYN_RECV spikes (SYN flood), CLOSE_WAIT growth (app leak), and
  conntrack utilization as early-warning signals.

---

## 12. Production Architecture

TCP state and its defenses, VPS vs cloud:

```
 TCP CONCERN              DEFENSE                          SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------   -------------------   -------------------------
 SYN flood               SYN cookies + edge scrubbing      tcp_syncookies=1      + AWS Shield + ALB/CloudFront
 off-path hijack/RST     ISN randomization + RFC5961        kernel default        kernel default (+ SDN)
 on-path hijack          TLS + prevent on-path             TLS + host security   TLS + VPC SDN (no ARP spoof)
 stateful filtering      state machine tracked              iptables/conntrack    stateful security groups (Ch76)
 state-table exhaustion  sizing/timeouts/rate limit         nf_conntrack tuning   NAT GW limits + SG + Shield
 Slowloris/slow-read     timeouts + reverse proxy           nginx limits          ALB/CloudFront + WAF
 CLOSE_WAIT/fd leak      correct close() + monitoring       app fix + ss monitor  app fix + CloudWatch
```

The architectural principle: **TCP's connection state is the foundation of stateful filtering (security
groups, NAT, conntrack) and the surface for a family of resource-exhaustion attacks — so defend the state
(SYN cookies make the vulnerable step stateless; sizing/timeouts/rate-limiting bound the resources; edge
scrubbing absorbs volume before the fragile components) and secure the data with TLS (since TCP's own
sequence-number protection fails against on-path attackers).** In the cloud, much of this is provided:
stateful security groups track the state machine for you, AWS Shield absorbs floods, and the SDN prevents
on-path hijacking within the VPC — but you still enable SYN cookies on hosts, set proxy/timeout limits, fix
socket leaks, and use TLS everywhere. The state machine learned here is the direct prerequisite for
Chapters 37 (conntrack) and 76 (security groups).

---

## 13. Common Mistakes

1. **Disabling SYN cookies** or leaving a tiny SYN backlog — enabling SYN-flood DoS.
2. **Assuming TCP secures the data** — TCP has no encryption; on-path attackers hijack/reset it; TLS is the
   data defense.
3. **Relying on sequence numbers for security** — only weak off-path resistance, and only with random ISNs;
   useless against on-path attackers.
4. **Ignoring conntrack/state-table limits** — state exhaustion is a real DoS (Chapters 3, 14).
5. **Leaking sockets (CLOSE_WAIT)** — fd exhaustion, silent DoS (Chapter 3 §Solutions 3.7).
6. **No timeouts/connection limits** — Slowloris/slow-read exhaustion (Chapter 3 §11).
7. **Misreading TIME_WAIT as a problem** — usually normal for a busy active closer (Chapter 3 §Solutions
   3.15).
8. **Not monitoring TCP state counts** — missing SYN-flood (SYN_RECV) and app-leak (CLOSE_WAIT) early
   signals.
9. **Confusing route selection with stateful filtering** — routing is longest-prefix (Chapter 12), stateful
   filtering tracks the TCP state machine (this chapter, Chapters 37, 76).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Service stops accepting new connections under load | SYN-flood backlog exhaustion | `ss state syn-recv \| wc -l`; `dmesg \| grep 'syn flood'`; enable SYN cookies |
| Service "up" but not accepting connections | CLOSE_WAIT fd leak or backlog full | `ss state close-wait \| wc -l`; fd count vs limit (Chapter 3) |
| Many TIME_WAIT sockets | busy active closer (usually fine) | `ss state time-wait \| wc -l`; SO_REUSEADDR; connection reuse (Chapter 3) |
| Connections reset unexpectedly | RST injection (censorship/attack) or app forcing RST | tcpdump for `[R]`; check SO_LINGER; TLS to detect tampering |
| Return traffic blocked despite outbound allowed | stateful tracking issue / asymmetric routing | check conntrack state; ensure symmetric path; SG statefulness (Chapter 76) |
| Firewall dropping new connections under load | conntrack/state-table exhaustion | `conntrack -C` vs `nf_conntrack_max`; NAT GW limits (Chapter 14) |
| Intermittent hangs on long connections | idle timeout evicting state (NAT/firewall) | keepalives; check timeouts (Chapter 14 §Sol 14.6) |

---

## 15. Practical Lab

Lab 19.1 is in §8. Register it in the lab index. Extension: instrument a small server and, in an isolated
lab, generate (a) a SYN flood, (b) a Slowloris slow-header attack, and (c) a CLOSE_WAIT leak (a client that
half-closes and a server that forgets to close), observing each via `ss` state counts and defending each
(SYN cookies; header timeouts + connection limits; correct close()). This exercises the full TCP-state
attack/defense family in one lab and directly prepares Chapters 37 and 76.

---

## 16. Exercises

### Concept questions

**19.1** Explain the three-way handshake step by step, what state each side allocates, and why this
resists blind spoofing (contrast UDP — Chapter 18).

**19.2** Explain the SYN flood and how SYN cookies defend it statelessly. Why is "make the vulnerable step
stateless" a general pattern?

**19.3** Explain the role of sequence numbers and ISN randomization. Against what attacker do they help,
and against what attacker are they useless (and what defends that case)?

**19.4** Explain how the TCP state machine is what stateful firewalls/security groups track, and why a
security group needs only an inbound rule.

**19.5** Distinguish TIME_WAIT, CLOSE_WAIT, and RST — what each means, which is normal, which is a bug, and
which is used in attacks.

### Debugging problems

**19.6** A service under load shows thousands of SYN_RECV connections and stops accepting new ones.
Diagnose and remediate.

**19.7** A service is "up" but silently stops accepting connections over time; `ss` shows growing
CLOSE_WAIT. Diagnose and fix (relate to Chapter 3).

**19.8** Return traffic for an allowed outbound connection is being dropped intermittently. Give two
state-related causes.

### Security scenarios

**19.9** Design the defense stack for an internet-facing service against the full family of TCP-state
attacks (SYN flood, Slowloris/slow-read, state exhaustion, hijacking), naming the control for each and the
load-bearing one for data confidentiality/integrity.

**19.10** Explain why, within a VPC, on-path TCP hijacking is not a concern but you still use TLS
everywhere, and what threat TLS addresses that the VPC does not.

### Architecture questions

**19.11** Explain how TCP's state machine underlies stateful security groups and conntrack, and what
happens (and how to defend) when the state table is exhausted (bridge to Chapters 37, 76, 14).

**19.12** Compare TCP's and UDP's security profiles as attack surfaces and defenses, and how the transport
choice affects a service's DoS and spoofing exposure.

### Hands-on exercises

**19.13** Capture and label a full TCP connection lifecycle (handshake, data, teardown) from tcpdump flags.

**19.14** Demonstrate a SYN flood and SYN-cookie defense in an isolated lab, observing SYN_RECV counts.

**19.15** Reproduce a CLOSE_WAIT leak and show the fd growth, then fix it.

### Interview questions

**19.16** "Walk me through the TCP three-way handshake and what a SYN flood does to it."

**19.17** "How do SYN cookies work, and why are they a clever defense?"

**19.18** "What is the security role of TCP sequence numbers, and what are their limits?"

**19.19** "How does a stateful firewall or security group work, in terms of TCP?"

**19.20** "Why does TCP not secure your data, and what does?"

---

## 17. Summary

- **TCP provides a reliable, ordered, connection-oriented byte stream over unreliable IP** by maintaining
  connection **state** on both sides, governed by a **state machine** (CLOSED → SYN_SENT/SYN_RCVD →
  ESTABLISHED → FIN_WAIT/CLOSE_WAIT → TIME_WAIT → CLOSED).
- **The three-way handshake (SYN → SYN-ACK → ACK)** establishes shared sequence numbers and **verifies both
  endpoints** (resisting blind/off-path spoofing that UDP cannot — Chapter 18) — but **allocates state,
  making it the SYN-flood target**. **SYN cookies** defend statelessly by encoding state in the ISN and
  allocating none until the ACK returns — a model "make the vulnerable step stateless" pattern.
- **Sequence numbers** order the stream and provide weak **off-path** injection/hijacking resistance **only
  if ISNs are unpredictable** (ISN randomization, RFC 6528/5961); **on-path attackers see the sequence
  numbers and hijack/RST at will**, so **TLS — not sequence numbers — secures the data**.
- **The state machine is what "stateful" firewalls/security groups track** (Chapters 37, 76): "allow
  established/related" permits packets of a tracked connection, so you write rules for the initiating
  direction and returns are automatic — and the **state table is finite** (conntrack exhaustion DoS).
- **All TCP stateful attack surfaces are resource exhaustion** — half-open state (SYN flood), conntrack
  state, file descriptors (CLOSE_WAIT leaks, Slowloris), worker slots (slow clients) — the Chapter 3 §5.4
  theme concentrated in TCP; defended by stateless steps (SYN cookies), bounded resources (limits,
  timeouts), and absorbing abuse at the edge (reverse proxy, Shield).
- **TCP secures delivery (and weakly, off-path injection); TLS secures the data** against any on-path
  adversary. Chapter 20 covers TCP's reliability/performance mechanics; this chapter's state machine is the
  prerequisite for Chapters 37 (conntrack) and 76 (security groups).

---

## 18. Knowledge Check

1. Narrate the three-way handshake and the state each side enters. (§3, §4.2)
2. What does a SYN flood exhaust, and how do SYN cookies defend it? (§4.2, §4.4)
3. What do sequence numbers protect against, and against whom are they useless? (§4.3)
4. What is ISN randomization and why does it matter? (§4.3)
5. How does the state machine relate to stateful security groups? (§4.6)
6. Distinguish TIME_WAIT, CLOSE_WAIT, and RST. (§4.5)
7. Why are all TCP stateful attacks a form of resource exhaustion? (§5)
8. Why does TLS, not sequence numbers, secure the data? (§4.3, §5)
9. What does `ss state syn-recv` (or close-wait) tell you in an incident? (§6.2)
10. Which later chapters depend on this state machine, and how? (§4.6, §12)

---

## 19. Further Exploration

- RFC 9293 (TCP, the consolidated spec) — read the state machine and handshake sections; and RFC 6528 (ISN
  randomization), RFC 5961 (blind attack mitigations).
- The **Mitnick attack (1994)** — the classic sequence-prediction hijacking story; understand why ISN
  randomization followed.
- Capture handshakes and teardowns in Wireshark (Chapter 24) and watch the state machine and sequence/ack
  numbers advance.
- `man 7 tcp` (again, after this chapter) and the SYN-cookie kernel docs (`net.ipv4.tcp_syncookies`).
- Preview Chapters 37 (conntrack) and 76 (security groups): both track this state machine — map "allow
  established/related" to the ESTABLISHED state you learned here.
- Chapter 20 next: TCP's reliability and performance (retransmission, windows, congestion) — the other half
  of TCP.

---

## Solutions

### 19.1
The three-way handshake: (1) the client sends **SYN** with its initial sequence number x, entering
SYN_SENT and allocating client-side state; (2) the server responds with **SYN-ACK** (its own ISN y, and
ack = x+1 acknowledging the client's SYN), entering SYN_RCVD and **allocating server-side state for the
half-open connection**; (3) the client sends **ACK** (ack = y+1), and both sides enter ESTABLISHED. After
this, both agree on sequence numbers and can reliably exchange data. It resists **blind spoofing** because
to complete the handshake the initiator must **receive the SYN-ACK** (which contains the server's ISN y) and
respond with ack = y+1 — an off-path attacker who spoofs the source and cannot see the SYN-ACK cannot
produce the correct ACK, so the connection never establishes. Contrast UDP (Chapter 18 §4.3): no handshake,
so a spoofed-source datagram is simply accepted and any response goes to the spoofed address — which is why
UDP is trivially spoofable and reflectable while TCP is not. The cost of this verification is the
server-side state allocated in step 2, which is exactly what the SYN flood attacks.

### 19.2
A **SYN flood** sends many SYNs (often with spoofed source IPs) but never completes the handshake with the
final ACK; the server allocates state for each half-open connection (SYN_RCVD) in its SYN backlog while
waiting, and the backlog fills, so the server cannot accept new legitimate connections — a DoS by
exhausting the half-open-connection state. **SYN cookies** defend statelessly: instead of allocating state
when it receives a SYN, the server computes the SYN-ACK's initial sequence number as a cryptographic
function (a "cookie") of the connection tuple + a secret + a coarse timestamp (encoding the essential
state, like the MSS), and allocates **no state**. A legitimate client returns an ACK carrying cookie+1; the
server recomputes/verifies the cookie and, if valid, **reconstructs** the connection state and proceeds to
ESTABLISHED. A flood of SYNs therefore allocates no state (no backlog to fill), and spoofed sources never
send the valid ACK, so the attack is defeated. "Make the vulnerable step stateless" is a general pattern
because state-exhaustion attacks target the state a server holds on behalf of unverified clients; by
encoding that state into a value handed to the client and requiring them to return it (proving liveness),
the server holds nothing until the client proves it is real — the same idea as stateless CSRF tokens,
JWT-based sessions, and capability tokens.

### 19.3
Sequence numbers number every byte in the stream (the ack number is the next expected byte), providing
ordering and reliability (Chapter 20) and a weak security property: to inject data into or reset a
connection, an attacker must supply a sequence number within the receiver's current window. **ISN
randomization** makes the initial sequence number a cryptographic function of the connection tuple + a
secret, so it is unpredictable to an **off-path** attacker (who cannot see the traffic and must guess).
Thus sequence numbers + random ISNs help against **off-path (blind) attackers** — they cannot easily guess
a valid sequence number to hijack the connection or inject a RST (this is what stopped sequence-prediction
attacks like Mitnick's, RFC 6528/5961). They are **useless against an on-path attacker** (an ARP/DHCP/
routing MITM — Chapters 9, 12, 15), who simply *sees* the sequence numbers and can inject data or reset the
connection at will. The defense against the on-path case is **TLS**, which authenticates the endpoints and
encrypts/authenticates the data cryptographically — so an on-path attacker who can read the sequence
numbers still cannot read the plaintext, tamper undetected, or impersonate the peer (though they can still
force a connection reset, which TLS detects as a failure). So: sequence numbers = weak off-path resistance
(with random ISNs); TLS = the real defense against on-path adversaries.

### 19.4
A stateful firewall or security group tracks each TCP connection's state (the state machine) in a
connection-tracking table. When you write a rule permitting a connection's **initiating** direction (e.g.
"allow inbound TCP 443"), the firewall permits the initial SYN; as the handshake completes, it creates a
**state entry** for that connection's 4-tuple in the ESTABLISHED state. Subsequent packets belonging to
that connection — including all the **return traffic** — are permitted automatically because they match the
existing state entry (they are "established/related"), without any separate rule. The entry is removed on
teardown (FIN/RST) or timeout. This is why a security group needs only an inbound rule: the returns are
allowed by state, not by an explicit outbound rule (Chapter 76). The same mechanism underlies Linux
conntrack (`ctstate ESTABLISHED,RELATED` — Chapter 37) and NAT (Chapter 14). The trade-off is that the
state table is finite, so a flood of connections can exhaust it (conntrack exhaustion — a DoS on the
firewall's state), which is why sizing, timeouts, SYN cookies, and rate limiting matter. Understanding the
TCP state machine is thus directly understanding how (and how fail) stateful cloud/network filtering works.

### 19.9
Defense stack for an internet-facing service against TCP-state attacks: (1) **SYN flood** → enable **SYN
cookies** (`tcp_syncookies=1`) on hosts and rely on **edge scrubbing** (AWS Shield) and the ALB/CloudFront/
reverse proxy to absorb floods before application instances (Chapter 3 §12). (2) **Slowloris/slow-read** →
**connection and timeout limits** at the reverse proxy/edge (client/header/body timeouts,
`limit_conn`/`limit_req`), and let the proxy absorb slow clients before precious worker threads (Chapter 3
§11). (3) **State-table/conntrack exhaustion** → size `nf_conntrack_max`/NAT-gateway limits, tune timeouts,
rate-limit, and use SYN cookies; distribute across per-AZ NAT gateways (Chapter 14). (4) **CLOSE_WAIT/fd
exhaustion** → correct `close()`/`Dispose()` handling and monitor `ss` state counts and fd usage (Chapter
3 §Solutions 3.7). (5) **Off-path hijacking/RST injection** → ISN randomization + RFC 5961 (kernel
defaults). (6) **On-path hijacking** → prevent on-path position (VPC SDN; ARP defenses on-prem) and — the
**load-bearing control for data confidentiality/integrity** — **TLS everywhere**, since it protects the
data against any on-path attacker who could otherwise read the sequence numbers and hijack the connection.
The pattern: make the vulnerable steps stateless (SYN cookies), bound the finite resources (limits,
timeouts, sizing), absorb volume at the edge (Shield/proxy), fix app leaks, and secure the data with TLS.
Monitoring TCP state counts (SYN_RECV, CLOSE_WAIT, conntrack utilization) provides early warning.

### 19.16
The three-way handshake: the client sends a **SYN** (with its initial sequence number) to open a
connection; the server responds with a **SYN-ACK** (its own initial sequence number plus an acknowledgment
of the client's), allocating state for the half-open connection while it waits; the client replies with an
**ACK**, and the connection is ESTABLISHED, with both sides agreeing on sequence numbers for reliable,
ordered data. A **SYN flood** abuses the state the server allocates in the second step: the attacker sends
many SYNs (typically with spoofed source addresses) but never sends the final ACK, so the server piles up
half-open connections in its SYN backlog (SYN_RCVD state), consuming memory/state until the backlog is full
and it can no longer accept new legitimate connections — a denial of service by exhausting the server's
half-open-connection state. It works because completing the handshake normally requires the server to hold
state before the client is verified. The defense is **SYN cookies**: the server encodes the connection
state into the initial sequence number it sends (a keyed hash of the tuple + secret + time) and allocates
no state until a valid ACK returns carrying that cookie — so a flood of SYNs (and spoofed sources that
never ACK) allocates nothing and cannot fill a backlog. Edge scrubbing (AWS Shield) and the reverse proxy
also absorb SYN floods before they reach application servers.

### 19.19
A stateful firewall or security group works by tracking the TCP connection state machine: for each
connection it maintains a state entry (keyed on the 4-tuple) recording the connection's state (SYN_SENT,
ESTABLISHED, etc.). You configure a rule for the connection's initiating direction; when a connection
matching an allow rule is established (the handshake completes), the firewall records it as ESTABLISHED,
and thereafter automatically permits packets that belong to that tracked connection — crucially, all the
**return traffic** — because they match the existing state entry ("established/related"), with no separate
rule needed. The entry is removed on teardown (FIN/RST) or on timeout. This is why an AWS security group is
"stateful": you allow inbound 443, and the responses go out automatically; you allow the app's outbound to
the database, and the returns come back automatically (Chapter 76). Under the hood it is connection
tracking (conntrack on Linux — Chapter 37; the same mechanism NAT uses — Chapter 14). The important
consequence is that the state table is finite, so a flood of connections can exhaust it — a DoS against the
firewall's state — which is why sizing, timeouts, SYN cookies, and rate limiting are part of operating
stateful filtering. Contrast with a stateless filter (NACLs — Chapter 76), which evaluates each packet
independently and therefore needs explicit rules for both directions.

### 19.20
TCP provides **reliable, ordered delivery and, weakly, resistance to off-path injection** — but it does
**not** provide confidentiality, integrity against a determined adversary, or strong authentication of the
data. TCP's header is not encrypted; its only "protection" of the stream is the sequence numbers, which
merely require an attacker to supply a value within the receiver's window. An **on-path** attacker (via ARP/
DHCP/routing MITM — Chapters 9, 12, 15) simply *sees* the sequence numbers and can read the plaintext,
inject data, or reset the connection at will; an off-path attacker with predictable ISNs (old stacks) could
guess them. So TCP secures *delivery*, not *data*. What secures the data is **TLS** (Chapters 4, 28): it
authenticates the server (and optionally the client) via certificates, encrypts the payload with
authenticated encryption (so tampering is detected), and provides forward secrecy — all cryptographically,
independent of the sequence numbers. An on-path attacker who can read every TCP sequence number still sees
only ciphertext and cannot impersonate the endpoint (they cannot present a valid certificate). Hence the
layering: TCP delivers the bytes reliably; TLS makes those bytes confidential, integrity-protected, and
authenticated. "We use TCP" says nothing about data security; "we use TLS over TCP" is what protects the
data — which is why the book insists on TLS everywhere, especially on any path an on-path attacker could
occupy.

---

*Next: Chapter 20 — TCP Part 2: Retransmission, Flow Control, Congestion Control, and Performance. Having
built TCP's connection lifecycle and its security, we cover how TCP achieves *reliability and performance*
— retransmission, sliding windows, congestion control — and the security-relevant behaviors (slow-read
attacks, window manipulation, and why performance tuning intersects with DoS resistance).*
