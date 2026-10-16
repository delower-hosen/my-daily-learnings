# Chapter 18 — UDP: Connectionless Transport and the Protocols Built On It

---

## 1. Why This Matters

We now reach Layer 4 — the transport layer — where the two great protocols live: UDP (this chapter) and TCP
(Chapters 19–20). UDP is the simpler of the two, and understanding it first clarifies TCP by contrast. For
a cloud security engineer, UDP matters more than its simplicity suggests:

1. **UDP's spoofability underpins amplification DDoS** — the largest-volume attacks on the internet
   (memcached, DNS, NTP, SSDP amplification — Chapters 16, 85). We have referenced these repeatedly; here
   we explain the mechanism precisely.
2. **Critical services ride UDP** — DNS (Chapters 16–17), DHCP (Chapter 15), NTP, QUIC/HTTP3 (Chapter 29),
   VPNs (WireGuard, IPsec/IKE), VoIP, and many IoT/telemetry protocols. Securing these requires knowing
   UDP's properties (no handshake, no built-in reliability, spoofable source).
3. **UDP behaves differently in firewalls, NAT, and security groups** than TCP — it is connectionless, so
   "stateful" handling of UDP is an approximation (pseudo-connections via timeouts), which affects
   security-group behavior (Chapter 76), NAT tables (Chapter 14), and scanning (Chapter 123).
4. **QUIC (HTTP/3) runs over UDP**, moving the modern web's transport to UDP+TLS — with real implications
   for inspection, WAFs, and network visibility (Chapter 29).

The core idea: **UDP is a thin, connectionless, unreliable, minimal wrapper over IP — just ports plus a
length and checksum, no handshake, no state, no delivery guarantees. This makes it fast and simple, but
also spoofable (no handshake to verify the source) and stateless (harder to filter statefully), which is
exactly why it is the engine of amplification attacks and why its security properties differ sharply from
TCP's.** Understanding UDP's minimalism — what it deliberately omits — is understanding both why it is used
and how it is abused.

---

## 2. Prerequisites

- Chapter 3 (sockets, ports, the 4-tuple — UDP uses `SOCK_DGRAM`), Chapter 10 (IP addressing), Chapter 7
  (headers).
- Chapters 15–17 (DHCP and DNS ride UDP — the concrete examples), and the amplification references there.
- Chapter 4 (the map, Stops 2–3).

---

## 3. Mental Model

**UDP is "fire and forget": you hand the kernel a datagram with a destination IP and port, and it is sent
— no connection, no acknowledgment, no retransmission, no ordering. If it arrives, great; if not, UDP does
not care. Reliability, ordering, and congestion control (if wanted) are the application's job.**

```
   TCP (Chapter 19):  connection-oriented, reliable, ordered  -> handshake, state, ACKs, retransmits
   UDP:               connectionless, unreliable, unordered   -> just send the datagram, no state

   UDP datagram = [ src port | dst port | length | checksum ] + payload
                    (8-byte header — that's ALL the transport layer adds)
```

Three ideas do the work:

1. **UDP adds almost nothing to IP** — just source/destination ports (for multiplexing, Chapter 3), a
   length, and a checksum. No sequence numbers, no acknowledgments, no connection state. It is the minimal
   transport: "IP with ports."
2. **No handshake means the source is unverified.** TCP's three-way handshake (Chapter 19) proves the
   sender can receive at its claimed address (it must complete the handshake). UDP has no handshake, so an
   attacker can trivially **spoof the source address** — the datagram is accepted and any response goes to
   the *spoofed* address, not the attacker. This single property is the basis of amplification DDoS and of
   UDP's use in reflection attacks.
3. **Connectionless means stateless filtering is approximate.** There is no connection to track, so
   firewalls/NAT/security groups approximate UDP "state" with timeouts (a "pseudo-connection" — allow
   return traffic for a while after an outbound datagram). This differs from TCP's real connection state
   and affects how UDP is filtered, NAT'd, and scanned.

**The security framing:** UDP's deliberate omissions (no handshake, no state, no reliability) make it fast
and simple — ideal for DNS, DHCP, real-time media, and QUIC — but they also make it **spoofable** (no
source verification) and **stateless** (approximate filtering). Spoofability is the root of amplification
attacks; statelessness shapes how UDP is secured. And because UDP provides *no* security itself
(no encryption, no integrity beyond a weak checksum, no authentication), **any security for UDP-based
protocols must come from the application layer** — DNS via DNSSEC/DoT, QUIC via built-in TLS, VPNs via
their own crypto. UDP is a blank, fast transport; the protocol on top provides (or fails to provide)
security.

---

## 4. Fundamentals

### 4.1 The UDP header (8 bytes — that is all)

```
   0                   16                  32
   +--------+--------+--------+--------+
   |   Source Port   | Destination Port|
   +--------+--------+--------+--------+
   |     Length      |    Checksum     |
   +--------+--------+--------+--------+
   |            Payload ...            |
```

Four fields, 8 bytes total — contrast with TCP's 20+ byte header (Chapter 19):

- **Source/Destination Port** (16-bit each): multiplexing keys (Chapter 3). The destination port
  identifies the service (53 DNS, 67/68 DHCP, 123 NTP, 443 QUIC/HTTP3); the source port is usually
  ephemeral (for a client) so replies can return.
- **Length**: the datagram size (header + payload).
- **Checksum**: a weak error-detection checksum over the header, payload, and a pseudo-header (including
  the IP addresses). It detects accidental corruption (like Ethernet's FCS — Chapter 8) but is **not a
  security control** — it is not keyed, so an attacker recomputes it after tampering. Optional in IPv4
  (can be 0 = "not computed"), mandatory in IPv6.

That is the entire transport layer for UDP: ports plus length plus a weak checksum. No sequence numbers, no
acknowledgment field, no flags, no window — none of TCP's machinery. This minimalism is the point.

### 4.2 What UDP does NOT provide (and who must provide it)

UDP deliberately omits everything TCP provides. The security-relevant omissions:

| UDP does not provide | Consequence | Who provides it (if needed) |
|---|---|---|
| Connection / handshake | source is unverified → **spoofable** | application (or the protocol, e.g. QUIC's handshake) |
| Reliability (ACK/retransmit) | datagrams may be lost silently | application (DNS retries; QUIC has its own) |
| Ordering | datagrams may arrive out of order | application (or QUIC) |
| Flow/congestion control | can overwhelm receiver/network | application (QUIC has congestion control) |
| Confidentiality/integrity/auth | payload is plaintext, unauthenticated | **application-layer crypto** (DNSSEC/DoT, QUIC's TLS, VPN crypto) |

The last row is the crucial security point: **UDP provides no security whatsoever.** Any confidentiality,
integrity, or authentication for a UDP-based protocol must come from the application or an embedded crypto
layer. This is why DNS needed DNSSEC/DoT bolted on (Chapters 16–17), why QUIC builds TLS in from the start
(Chapter 29), and why UDP VPNs (WireGuard, IPsec) implement their own encryption. A raw UDP service is
plaintext and spoofable.

### 4.3 Why source spoofing is trivial (and consequential)

Because UDP has no handshake, sending a datagram with a **forged source IP** is trivial — the kernel puts
whatever source you specify (if you have raw-socket / `CAP_NET_RAW` capability — Chapter 2, or via a crafted
packet), and there is no round-trip to verify the sender can actually receive at that address. Contrast
TCP: to complete the three-way handshake (Chapter 19), the initiator must receive the SYN-ACK at its
claimed address and respond — so blind TCP spoofing is much harder (you would not see the SYN-ACK).

The consequences:

- **Reflection:** send a UDP query with the *victim's* IP as the source; the server's response goes to the
  victim, not the attacker. The attacker "reflects" traffic off the server onto the victim.
- **Amplification:** choose a protocol where the *response is much larger than the request* (DNS `ANY`,
  memcached `stats`, NTP `monlist`, SSDP), so a small spoofed request elicits a large response to the
  victim — amplifying the attacker's bandwidth by 10×–50,000× (§4.4).
- **No source accountability:** the source IP in a UDP packet cannot be trusted for attribution or
  authorization (like the MAC — Chapter 8, and reverse DNS — Chapter 16: attacker-controlled data is not a
  credential). Any UDP protocol that authorizes based on source IP alone is spoofable.

This is why **BCP 38 (source address validation)** — networks dropping outbound packets whose source
address is not theirs — is such an important internet-hygiene measure: it prevents spoofing at the source
and would neuter reflection/amplification if universally deployed (it is not).

### 4.4 UDP amplification DDoS (the mechanism, precisely)

The largest DDoS attacks are UDP amplification. The mechanism, combining §4.3's spoofing with a
high-amplification protocol:

```
   1. Attacker finds a UDP service with a large response-to-request ratio and open access:
        - DNS open resolver: small ANY query -> large response (~amplification 28-54x with DNSSEC)
        - NTP monlist:        small request  -> huge response      (~amplification 556x)
        - memcached stats:    tiny request   -> enormous response  (~amplification 10,000-51,000x!)
        - SSDP, CLDAP, etc.
   2. Attacker sends many small requests with the VICTIM's spoofed source IP to many such servers.
   3. Each server sends its LARGE response to the VICTIM.
   4. The victim is flooded with amplified traffic from many legitimate-looking servers.
        Attacker's small bandwidth -> massive traffic at the victim (e.g. memcached: Tbps-scale attacks).
```

The two ingredients are **spoofability** (UDP, §4.3) and **amplification** (a protocol whose response
dwarfs its request). memcached amplification (2018) produced the then-largest DDoS (1.35 Tbps against
GitHub, 1.7 Tbps elsewhere) because memcached on UDP had a ~10,000–51,000× ratio and was exposed on the
internet (the Chapter 5 insecure-default pattern: memcached bound to `0.0.0.0` on UDP with no auth).

Defenses (§11): **BCP 38 source validation** (stop spoofing at the source — the root fix), **do not expose
amplifiable UDP services** (memcached/NTP/DNS resolvers not on the public internet — the Chapter 5
bind-address lesson), **disable amplifiable features** (NTP monlist, DNS ANY, restrict recursion),
**response rate limiting**, and **anti-DDoS scrubbing at the edge** (Chapter 85, AWS Shield). Note that
amplification is an attack UDP services are *abused for* (harming a third party), which is why exposing an
amplifiable UDP service is a risk not just to you but to the internet.

### 4.5 UDP in firewalls, NAT, and security groups (stateless approximation)

Because UDP is connectionless, "stateful" handling is an approximation:

- **Firewalls/NAT/security groups track UDP "pseudo-connections" via timeouts:** when a host sends an
  outbound UDP datagram (e.g. a DNS query from ephemeral port 54321 to 53), the firewall/NAT creates a
  temporary state entry allowing return traffic to that port for a timeout period (tens of seconds). There
  is no connection to close, so the state simply expires. This is how a stateful security group (Chapter
  76) allows the DNS response back after an outbound query.
- **Consequences:** UDP state entries are short-lived and timeout-based, so long-gap UDP flows can break
  (the state expired); and the "stateful" allowance is looser than TCP's (any datagram to the expected
  port within the window is allowed, since there is no sequence/handshake to validate). NAT for UDP is
  correspondingly approximate and can break protocols that assume specific port behavior (§Chapter 14 ALGs).
- **UDP scanning is ambiguous** (Chapter 123): unlike TCP (where a closed port sends RST — Chapter 3), a
  closed UDP port sends an ICMP port-unreachable, while an open port often sends *nothing* (the application
  may not respond to a probe) — so `nmap -sU` distinguishes open/closed/filtered less cleanly and is slow.
  This ambiguity is why UDP services can hide.

### 4.6 QUIC: the modern UDP transport (preview of Chapter 29)

**QUIC** — the transport under **HTTP/3** — runs over UDP and rebuilds, in user space, everything UDP omits
(connection, reliability, ordering, congestion control) *plus* mandatory TLS 1.3 encryption, all in one
protocol. It uses UDP as a fast, unencumbered substrate and provides the guarantees and security itself.
Why it matters for security:

- **QUIC is encrypted by default** (TLS 1.3 built in), including much of the handshake — so far less is
  visible to the network than TCP+TLS (where the handshake and SNI were more exposed). This improves
  privacy but **reduces network visibility and inspection** (WAFs, IDS, and middleboxes see less —
  Chapter 29).
- **QUIC over UDP/443** means the modern web's transport is UDP, so "UDP is just for DNS/DHCP/VoIP" is
  outdated — a large fraction of web traffic is now UDP/QUIC, and firewalls/security tooling must handle
  it (some enterprises block UDP/443 to force TCP+TLS for inspectability — a real trade-off).
- **QUIC has its own connection handling** on top of UDP, so it is not subject to UDP's spoofability in the
  same way (its handshake verifies the peer) — it uses UDP as a substrate but adds a real connection.

Chapter 29 covers QUIC/HTTP3 in depth; the point here is that UDP is no longer a niche transport — it
carries the modern encrypted web via QUIC, with visibility implications.

---

## 5. Deep Technical Explanation: UDP's Minimalism as a Design and Security Choice

UDP's entire value is what it *omits*. TCP's reliability machinery (Chapters 19–20) adds latency (the
handshake round-trip, retransmission delays, head-of-line blocking) and state (per-connection memory). For
many use cases, that overhead is wrong:

- **DNS** (Chapters 16–17): a single query and response. A TCP handshake would triple the round-trips for
  a tiny exchange; UDP's one-shot model is far faster, and DNS handles loss with retries. (DNS falls back
  to TCP only for large responses or zone transfers.)
- **Real-time media (VoIP, video)**: late data is useless — a retransmitted audio packet arriving after its
  playback moment is worse than a dropped one. TCP's insistence on reliable, in-order delivery causes
  stalls; UDP lets the application drop late data and keep playing.
- **DHCP** (Chapter 15): broadcast-based bootstrapping where the client has no address — TCP's
  connection model does not even apply.
- **QUIC** (§4.6): wants control over reliability/congestion/multiplexing to avoid TCP's head-of-line
  blocking, so it builds its own on UDP.

The security lesson from this minimalism is precise and generalizable: **UDP provides a fast, unopinionated
transport and pushes all guarantees — reliability *and security* — to the application.** This means:

1. **Never assume a UDP service is secure by transport.** UDP gives no confidentiality, integrity, or
   authentication. If the application does not add crypto, the traffic is plaintext and spoofable. A raw
   UDP telemetry/IoT protocol, a UDP admin interface, an unauthenticated UDP service — all are exposed by
   default. This is the Chapter 5 insecure-default pattern applied at the transport layer.
2. **Source-based trust in UDP is broken.** Because the source is unverified (§4.3), any UDP protocol that
   authorizes or attributes by source IP is spoofable. Authentication must be cryptographic (a shared key,
   a signature), not "it came from a trusted IP."
3. **Exposing amplifiable UDP services harms others.** The spoofability + amplification combination
   (§4.4) makes an exposed UDP service a weapon against third parties, not just a risk to you — a
   distinctive UDP responsibility.

Contrast with TCP (Chapter 19), which provides a verified connection (the handshake proves the source can
receive) and thus resists blind spoofing — but at the cost of state (SYN-flood DoS targets that state,
Chapter 19) and latency. The transport choice is a trade-off: UDP's speed/simplicity vs TCP's
reliability/source-verification, each with its own security profile. A security engineer must know which
transport a protocol uses and therefore which properties (and vulnerabilities) it inherits.

---

## 6. Internals: Observing UDP

### 6.1 See UDP datagrams

```bash
# DNS is the canonical UDP example (Chapter 16):
$ sudo tcpdump -n -i any 'udp port 53' -c 4
10:22:41 IP 10.0.1.5.54321 > 10.0.0.2.53: 0x1a2b A? example.com. (28)   # query (small)
10:22:41 IP 10.0.0.2.53 > 10.0.1.5.54321: 0x1a2b 1/0/0 A 93.184.216.34 (44)  # response
# Note: no handshake -- just query then response. Source port 54321 is ephemeral (Chapter 3).

# DHCP (Chapter 15): UDP 67/68. NTP: UDP 123. QUIC/HTTP3: UDP 443.
$ sudo tcpdump -n 'udp port 443' -c 4     # QUIC traffic (encrypted; §4.6)
```

Contrast this with a TCP capture (Chapter 19): no SYN/SYN-ACK/ACK, no sequence numbers — just the datagram.
The minimalism is visible on the wire.

### 6.2 UDP sockets and listening services

```bash
$ ss -ulpn                     # UDP listening sockets (note: no LISTEN state — UDP is connectionless)
UNCONN 0 0 0.0.0.0:53   ...    users:(("systemd-resolve",...))   # UNCONN, not LISTEN (Chapter 3)
UNCONN 0 0 0.0.0.0:123  ...    users:(("ntpd",...))
# Audit: which UDP services are exposed (0.0.0.0)? Are any amplifiable (DNS resolver, NTP, memcached)?
```

`ss -ulpn` shows `UNCONN` (not `LISTEN`) for UDP because there are no connections — a visible sign of UDP's
connectionless nature. The audit question is the Chapter 5 one: which UDP services are exposed, and are any
amplifiable (an open DNS resolver, NTP with monlist, memcached) — those are both a risk to you and a weapon
against others.

### 6.3 Observe the amplification ratio (safely, locally)

```bash
# Measure a response/request size ratio for a UDP service (DNS example), WITHOUT spoofing:
$ dig ANY example.com @8.8.8.8 +ignore | wc -c        # response size
$ echo "request is ~28-40 bytes; ANY response can be much larger -> amplification ratio"
# NEVER send spoofed-source traffic; amplification is only demonstrated conceptually / by measuring ratios.
```

You can *measure* the amplification ratio (response size ÷ request size) to understand the risk, but you
must never actually perform reflection (sending spoofed-source packets), which is a DDoS on the victim and
illegal. Understanding the ratio is enough to reason about the threat and to identify which of your services
are dangerous to expose.

### 6.4 UDP scan behavior (Chapter 123 preview)

```bash
$ sudo nmap -sU -p 53,123,161 <target>      # UDP scan (slow; ambiguous — §4.5)
# open|filtered = no response (could be open-but-silent or filtered)
# closed = ICMP port unreachable received
```

The `open|filtered` ambiguity (no response could mean either) is UDP's connectionless nature showing up in
scanning — unlike TCP's clean SYN-ACK/RST distinction (Chapter 3, 123).

---

## 7. Real-World Example: UDP in the Ledger Environments

**Ledger's UDP surface:**

- **DNS (UDP 53):** the app resolves names via UDP DNS (Chapters 16–17). Security: DNSSEC/DoT for
  integrity, query logging for detection — as covered. The app is a DNS *client*, not a resolver, so it
  does not expose an amplifiable resolver.
- **NTP (UDP 123):** time synchronization (critical — wrong time breaks TLS cert validation, JWT expiry,
  log correlation — Chapter 15). Ledger uses a trusted NTP source; it does not expose an NTP server (and if
  it did, monlist must be disabled to prevent amplification).
- **QUIC/HTTP3 (UDP 443):** if Ledger's CloudFront/ALB serves HTTP/3, client↔edge traffic is QUIC over UDP
  (§4.6) — encrypted, with the visibility trade-off (the edge WAF still inspects after termination —
  Chapter 4 Stop 5, Chapter 29).
- **What Ledger must NOT do:** expose any amplifiable UDP service (memcached, an open DNS resolver, NTP with
  monlist) to the internet — the Chapter 5 insecure-default risk, made worse for UDP because it weaponizes
  the service against third parties. ElastiCache/memcached must be private (Chapter 5 §7), NTP restricted,
  and DNS resolution via the VPC resolver (not an exposed resolver).

**Security groups and UDP (Chapter 76 preview):** Ledger's security groups handle UDP statefully via
timeouts (§4.5) — an outbound DNS query from an instance is allowed a return response for the timeout
window. Ledger must ensure UDP services are not inadvertently exposed (a security group allowing UDP from
`0.0.0.0/0` to an amplifiable service is a critical finding — both a compromise risk and a DDoS-weapon
risk).

**AWS Shield and amplification:** AWS Shield (Standard, free) provides baseline protection against common
UDP amplification/reflection attacks at the edge (Chapter 85), and AWS's network drops spoofed traffic
(BCP 38-style source validation), so instances in a VPC cannot easily launch spoofed reflection attacks —
another cloud-fabric protection (like the L2 attacks removed in Chapters 8–9).

The Ledger takeaway: **UDP is the transport for DNS, NTP, and (increasingly) the web via QUIC — all of
which Ledger uses as a client and secures at the application layer (DNSSEC/DoT, trusted NTP, QUIC's built-in
TLS) — while the key risk to avoid is exposing an amplifiable UDP service, which endangers both Ledger and
the internet.** The cloud fabric adds baseline anti-spoofing and anti-DDoS, but not exposing amplifiable
services (the bind-address discipline of Chapter 5) remains Ledger's responsibility.

---

## 8. Hands-On Demonstration

### LAB 18.1 — UDP Behavior, Statelessness, and Amplification Understanding

**Objective.** Observe UDP's connectionless behavior and contrast it with TCP, see how firewalls/NAT
handle UDP statefully via timeouts, measure an amplification ratio (without performing an attack), and
audit for exposed amplifiable UDP services.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45 minutes.

**Steps.**

*Step 1 — UDP is connectionless (no handshake).*

```bash
# Capture a DNS (UDP) exchange and a TCP exchange side by side:
sudo tcpdump -n -i any 'udp port 53' -c 4 &
dig example.com @8.8.8.8 > /dev/null
sleep 1
# Compare: UDP = just query + response (no SYN/SYN-ACK/ACK). Now a TCP one:
sudo tcpdump -n -i any 'tcp port 443 and (tcp[tcpflags] & tcp-syn != 0)' -c 3 &
curl -s https://example.com > /dev/null
# TCP shows SYN/SYN-ACK/ACK (Chapter 19); UDP showed none. This is the core difference.
```

*Step 2 — UDP sockets show UNCONN, not LISTEN.*

```bash
ss -ulpn                          # note UNCONN state (connectionless) vs TCP's LISTEN
ss -tlpn                          # TCP for comparison: LISTEN state
```

*Step 3 — Statefulness via timeout (pseudo-connection).*

```bash
# On a Linux host with conntrack, an outbound UDP query creates a temporary state entry:
dig example.com @8.8.8.8 > /dev/null
sudo conntrack -L -p udp 2>/dev/null | grep :53 | head    # a UDP "connection" entry with a timeout
cat /proc/sys/net/netfilter/nf_conntrack_udp_timeout      # the short timeout (e.g. 30s)
# Unlike TCP, this state expires by timeout (no connection close) -- the §4.5 approximation.
```

*Step 4 — Measure an amplification ratio (NO spoofing).*

```bash
# Measure response vs request size for an amplifiable query (understanding only, no attack):
REQ=$(echo -n "dns ANY query ~ 40 bytes")
RESP=$(dig ANY google.com @8.8.8.8 +ignore 2>/dev/null | wc -c)
echo "Approx amplification: response ${RESP} bytes vs request ~40 bytes -> ratio ~$((RESP/40))x"
# This ratio, combined with source spoofing (which we do NOT perform), is the amplification mechanism.
```

*Step 5 — Audit for exposed amplifiable UDP services.*

```bash
ss -ulpn | awk '$5 ~ /0.0.0.0|\[::\]/ {print}'    # UDP services bound to all interfaces
# For each: is it amplifiable (DNS resolver, NTP, memcached, SSDP)? Is it meant to be exposed?
# An amplifiable UDP service on 0.0.0.0 reachable from the internet = critical finding.
```

**Security implications.** Write down: (a) UDP has no handshake → source is spoofable → reflection/
amplification; (b) firewalls/NAT/SGs handle UDP statefully via timeouts (approximate); (c) the
amplification mechanism = spoofability + a large response/request ratio; (d) exposing an amplifiable UDP
service endangers you *and* third parties; (e) UDP provides no security — the application must (DNSSEC/DoT,
QUIC TLS).

**Cleanup.** None.

---

## 9. Security Implications

- **UDP is a minimal, connectionless transport** — just ports + length + a weak (unkeyed, non-security)
  checksum. It provides **no confidentiality, integrity, authentication, reliability, or ordering**; all
  security must come from the application layer (DNSSEC/DoT, QUIC's TLS, VPN crypto).
- **No handshake = spoofable source.** UDP source addresses are trivially forged (no round-trip to verify),
  so source-based trust/attribution in UDP is broken (like MAC and reverse DNS — attacker-controlled).
- **Spoofability + amplification = the largest DDoS attacks** (memcached, NTP, DNS, SSDP reflection).
  Exposing an amplifiable UDP service is a risk to you *and* a weapon against third parties.
- **UDP is filtered statelessly (approximated by timeouts)** in firewalls/NAT/security groups — looser than
  TCP's real connection state, with short-lived entries that can break long-gap flows.
- **Critical services ride UDP** (DNS, DHCP, NTP, QUIC/HTTP3, VPNs) — securing them requires knowing UDP's
  properties; QUIC moves the encrypted web to UDP with reduced network visibility.
- **The cloud fabric adds baseline anti-spoofing (BCP 38-style) and anti-DDoS (Shield)** — but not exposing
  amplifiable services (the Chapter 5 bind-address discipline) remains your responsibility.

---

## 10. Attack Scenarios

1. **UDP amplification/reflection DDoS** (§4.4): small spoofed-source requests to amplifiable UDP services
   (memcached ~10,000–51,000×, NTP monlist ~556×, DNS ANY ~28–54×, SSDP) elicit large responses to the
   victim — the largest-volume internet attacks. Defense: don't expose amplifiable services, BCP 38,
   disable amplifiable features, RRL, edge scrubbing.
2. **Source-spoofed UDP abuse of source-trusting protocols:** any UDP protocol that authorizes/attributes
   by source IP is spoofable (§4.3). Defense: cryptographic authentication, not IP-based.
3. **Exposed unauthenticated UDP services** (memcached, some IoT/telemetry, UDP admin interfaces): plaintext
   and often unauthenticated (§4.2, Chapter 5). Defense: private binds, auth, encryption.
4. **DNS/DHCP attacks over UDP** (Chapters 15–17): poisoning/spoofing exploit UDP's spoofability + weak
   entropy. Defense: DNSSEC/DoT, DHCP snooping.
5. **QUIC visibility evasion** (§4.6): traffic over QUIC/UDP-443 is encrypted and less inspectable, which
   attackers (and privacy-seeking users) exploit to evade middlebox inspection. Defense: terminate/inspect
   at the edge (Chapter 29), or force TCP+TLS where inspection is required.
6. **UDP flood DoS:** raw UDP floods to a service (not amplification, just volume) exhausting bandwidth/
   resources. Defense: rate limiting, anti-DDoS.

---

## 11. Defensive Techniques

- **Do not expose amplifiable UDP services** to the internet — memcached, open DNS resolvers, NTP (with
  monlist), SSDP, CLDAP. Bind them privately (Chapter 5 §7), restrict access, and if a service must be
  public, disable amplifiable features (NTP monlist off, DNS ANY restricted, recursion limited to your
  clients). This protects you and prevents your service being weaponized against others.
- **Implement/rely on source address validation (BCP 38)** — networks dropping spoofed outbound packets;
  the root fix for reflection. The cloud fabric does this for you (instances cannot easily spoof); on-prem/
  hosting, ensure your provider does.
- **Never trust the UDP source address** for authorization or attribution — use cryptographic
  authentication (a shared key, a signature) instead of source-IP trust.
- **Add application-layer security to UDP protocols** — DNSSEC + DoT/DoH for DNS (Chapters 16–17), QUIC's
  built-in TLS, WireGuard/IPsec crypto for VPNs, application-layer auth/encryption for custom UDP services.
  Assume raw UDP is plaintext and spoofable.
- **Configure firewalls/security groups for UDP deliberately** — restrict UDP services to necessary sources
  (Chapter 76), and account for the timeout-based state (long-gap flows may break; the allowance is looser
  than TCP).
- **Use anti-DDoS at the edge** (AWS Shield, Chapter 85) for volumetric UDP attacks, and response rate
  limiting on any UDP service you do expose.
- **Handle QUIC/HTTP3 in your visibility/inspection strategy** — decide whether to terminate/inspect QUIC
  at the edge or restrict UDP/443 where inspection is mandatory (Chapter 29), balancing privacy/performance
  against inspectability.

---

## 12. Production Architecture

UDP's role and controls, VPS vs cloud:

```
 UDP SERVICE / USE       SECURITY NEED                    SYSTEM A         SYSTEM B (AWS)
 ---------------------   ------------------------------   --------------   ---------------------------
 DNS (client)            DNSSEC/DoT + query logging        resolver config  VPC resolver + Route53 (Ch16-17)
 NTP (client)            trusted source (time integrity)   ntp.conf         Amazon Time Sync / trusted NTP
 QUIC/HTTP3 (443)        edge TLS + inspection decision    (if used)        CloudFront/ALB HTTP3 + WAF (Ch29)
 amplifiable services    DO NOT EXPOSE                     private bind     private + SG; Shield at edge
 anti-spoofing (BCP 38)  provider/network                  provider-dep.    AWS fabric (built in)
 volumetric DDoS         edge scrubbing                    provider/Cloudflare AWS Shield (Ch85)
```

The architectural principle: **UDP is a fast, security-free transport that carries critical protocols (DNS,
NTP, QUIC) whose security lives at the application layer, and whose main systemic risk is exposing
amplifiable services.** Secure UDP-based protocols with their own crypto (DNSSEC/DoT, QUIC TLS, VPN
encryption), never trust UDP source addresses, do not expose amplifiable services (the bind-address
discipline), and rely on edge anti-DDoS and the cloud fabric's anti-spoofing for volumetric protection. As
QUIC moves the web to UDP, plan for its reduced inspectability. The key mindset: **know the transport a
protocol uses, and therefore which security properties it inherits (none, for raw UDP) and which you must
add.**

---

## 13. Common Mistakes

1. **Exposing amplifiable UDP services** (memcached, open resolvers, NTP monlist) — a DDoS weapon and a
   compromise risk (Chapter 5).
2. **Trusting the UDP source address** for authorization/attribution — trivially spoofable.
3. **Assuming a UDP service is secure by transport** — UDP provides no security; the application must add
   it.
4. **Not adding application-layer crypto to UDP protocols** — leaving DNS unsigned/unencrypted, custom UDP
   services plaintext.
5. **Ignoring UDP in firewall/SG rules** — leaving UDP services inadvertently exposed, or not accounting
   for timeout-based state breaking long-gap flows.
6. **Overlooking QUIC/HTTP3** in inspection/visibility strategy — a growing fraction of encrypted web
   traffic over UDP.
7. **Confusing UDP scan results** — `open|filtered` ambiguity misread (Chapter 123).
8. **Not synchronizing time (NTP) securely** — wrong time breaks TLS validation, token expiry, and log
   correlation (Chapter 15).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Intermittent UDP service failures | timeout-based state expired (long-gap flow) | check firewall/NAT UDP timeout; add keepalives/heartbeats |
| Your server used in a DDoS | exposed amplifiable UDP service being reflected | `ss -ulpn`; is DNS/NTP/memcached public? disable amplifiable features, restrict |
| DNS/DHCP resolution flaky | UDP loss (no retransmit by transport) | check for packet loss; DNS retries; consider TCP fallback |
| UDP scan gives ambiguous results | connectionless (open-but-silent vs filtered) | expected; `nmap -sUV` for service probes (Chapter 123) |
| HTTP/3 traffic not inspected by WAF | QUIC over UDP/443, encrypted | ensure edge terminates/inspects HTTP3, or restrict UDP/443 (Chapter 29) |
| TLS cert errors network-wide | wrong time (bad/absent NTP) | check NTP sync (Chapter 15); secure the time source |
| High UDP bandwidth to a service | UDP flood DoS | rate limiting; edge scrubbing (Shield/Chapter 85) |

---

## 15. Practical Lab

Lab 18.1 is in §8. Register it in the lab index. Extension: audit a host/VPC for all exposed UDP services
(`ss -ulpn` + security-group UDP rules), classify each as amplifiable or not, and for any amplifiable
service reachable beyond its intended scope, write the finding (risk to you + DDoS-weapon risk to others)
and the remediation (private bind/SG restriction, disable amplifiable features). This is a real, valuable
audit given how often amplifiable UDP services are accidentally exposed.

---

## 16. Exercises

### Concept questions

**18.1** Compare UDP and TCP across connection, reliability, ordering, and source verification. What does
UDP deliberately omit, and why is that useful?

**18.2** Explain why UDP source spoofing is trivial while blind TCP spoofing is hard, and the security
consequences of each.

**18.3** Explain the UDP amplification DDoS mechanism precisely, naming the two required ingredients and
example protocols/ratios.

**18.4** Why does UDP provide no security, and where must security for UDP-based protocols come from? Give
three examples.

**18.5** Explain how firewalls/NAT/security groups handle UDP statefully despite it being connectionless,
and the consequences.

### Debugging problems

**18.6** A UDP-based telemetry flow with long idle gaps intermittently fails to receive responses. Explain
using UDP state handling and give the fix.

**18.7** Your NTP server appears in a DDoS complaint. Diagnose and remediate.

**18.8** After a WAF deployment, some traffic bypasses inspection. It's HTTP/3. Explain and give options.

### Security scenarios

**18.9** You find memcached exposed on UDP to the internet with no auth. Explain both risks (to you and to
others) and the remediation, and why UDP makes the second risk worse.

**18.10** Design the security for a custom UDP-based service (e.g. a game server or IoT telemetry) that
needs performance but must not be spoofable or exposed as an amplifier.

### Architecture questions

**18.11** Explain the security profiles of UDP vs TCP as a transport choice, and how you would decide which
to use for a new protocol from a security standpoint.

**18.12** Explain how QUIC/HTTP3 changes network visibility and inspection, and how you would handle it in
a cloud edge architecture (bridge to Chapter 29).

### Hands-on exercises

**18.13** Capture and contrast a UDP (DNS) and a TCP (HTTPS) exchange, identifying the presence/absence of
a handshake and state.

**18.14** Measure the amplification ratio of a DNS ANY query (no spoofing) and explain the DDoS mechanism.

**18.15** Audit a host for exposed amplifiable UDP services and write the findings.

### Interview questions

**18.16** "What's the difference between UDP and TCP, and when would you use each?"

**18.17** "How does UDP amplification DDoS work, and how do you defend against it?"

**18.18** "Why can't you trust a UDP packet's source address?"

**18.19** "What security does UDP provide, and how are UDP-based protocols secured?"

**18.20** "How does QUIC/HTTP3 affect your network security visibility?"

---

## 17. Summary

- **UDP is a minimal, connectionless transport** — an 8-byte header (source/destination ports, length, a
  weak non-security checksum) over IP, with **no handshake, no reliability, no ordering, no flow/congestion
  control, and no security** (confidentiality/integrity/authentication). It is "IP with ports."
- UDP's omissions make it **fast and simple** (ideal for DNS, DHCP, NTP, real-time media, and QUIC) but
  **spoofable** (no handshake to verify the source) and **statelessly filtered** (firewalls/NAT/SGs
  approximate UDP state with timeouts — looser than TCP's real connection state).
- **Source spoofing is trivial** (unlike blind TCP spoofing, which the handshake resists), so **UDP source
  addresses cannot be trusted** for authorization/attribution, and spoofing enables **reflection**.
- **Spoofability + amplification (large response/request ratio) = the largest DDoS attacks** (memcached
  ~10,000–51,000×, NTP monlist ~556×, DNS ANY ~28–54×). **Exposing an amplifiable UDP service is a risk to
  you and a weapon against third parties** — the Chapter 5 bind-discipline lesson, amplified.
- **UDP provides no security; the application must** — DNS via DNSSEC/DoT (Chapters 16–17), QUIC via
  built-in TLS, VPNs via their own crypto. Assume raw UDP is plaintext and spoofable.
- **QUIC (HTTP/3) runs over UDP**, moving the encrypted web to UDP with **reduced network visibility** — a
  real inspection trade-off (Chapter 29).
- **Defenses:** don't expose amplifiable services, BCP 38 source validation, disable amplifiable features,
  response rate limiting, edge anti-DDoS (Shield), application-layer crypto, and never trust the UDP source.
  The cloud fabric adds baseline anti-spoofing and anti-DDoS; not exposing amplifiable services stays yours.

---

## 18. Knowledge Check

1. What are the four UDP header fields, and what does UDP omit vs TCP? (§4.1, §4.2)
2. Why is UDP source spoofing trivial and blind TCP spoofing hard? (§4.3)
3. Name the two ingredients of UDP amplification and two example protocols with ratios. (§4.4)
4. Where must security for UDP-based protocols come from? Give examples. (§4.2, §5)
5. How do firewalls/NAT/SGs handle UDP statefully, and what breaks? (§4.5)
6. Why is exposing an amplifiable UDP service a risk to third parties? (§4.4, §5)
7. What transport does QUIC/HTTP3 use, and what's the visibility implication? (§4.6)
8. Why can't you trust a UDP source address for authorization? (§4.3)
9. What does BCP 38 do, and who provides it in the cloud? (§4.3, §11)
10. Why does `ss -ulpn` show UNCONN instead of LISTEN? (§6.2)

---

## 19. Further Exploration

- RFC 768 (UDP) — one of the shortest, clearest RFCs; read it to appreciate UDP's minimalism.
- The **memcached amplification** and **NTP monlist** DDoS write-ups (2018/2014) — the definitive
  amplification case studies and the Chapter 5 exposed-default pattern at scale.
- BCP 38 / RFC 2827 (source address validation) — the internet-hygiene fix for spoofing.
- QUIC (RFC 9000) and HTTP/3 (RFC 9114) overviews — preview Chapter 29; note the built-in TLS and the
  visibility implications.
- Capture DNS, DHCP, NTP, and QUIC with tcpdump and contrast their UDP behavior with a TCP capture
  (Chapters 19, 24).
- Audit your environment for exposed amplifiable UDP services (§15) — a frequently-fruitful, high-value
  check.

---

## Solutions

### 18.1
UDP vs TCP: **Connection** — TCP is connection-oriented (three-way handshake establishes state); UDP is
connectionless (no handshake, no state). **Reliability** — TCP guarantees delivery via acknowledgments and
retransmission; UDP does not (datagrams may be lost silently). **Ordering** — TCP delivers bytes in order;
UDP may deliver datagrams out of order. **Source verification** — TCP's handshake proves the sender can
receive at its claimed address (resisting blind spoofing); UDP has no such proof (trivially spoofable).
UDP deliberately omits connection setup, reliability, ordering, flow/congestion control, and security. This
is useful because these features add latency (handshake round-trips, retransmission delays, head-of-line
blocking) and state (per-connection memory) that many use cases do not want: DNS wants a single fast
query/response (a handshake would triple round-trips); real-time media wants to drop late data rather than
wait for retransmission; DHCP bootstraps before the client even has an address; and QUIC wants to build its
own reliability/multiplexing to avoid TCP's head-of-line blocking. UDP provides a fast, unopinionated
substrate and pushes reliability *and security* to the application.

### 18.3
UDP amplification DDoS requires two ingredients: (1) **source spoofability** — UDP has no handshake, so an
attacker sends requests with the *victim's* IP as the forged source, and responses go to the victim; and
(2) an **amplifiable protocol** — one whose response is much larger than its request, so a small request
elicits a large response. Mechanism: the attacker sends many small spoofed-source requests to many exposed
UDP servers (reflectors); each server sends its large response to the victim; the victim is flooded with
amplified traffic from many legitimate-looking servers, turning the attacker's small bandwidth into a
massive attack. Example protocols and approximate ratios: **memcached** (~10,000–51,000×, produced the
1.35 Tbps GitHub attack in 2018), **NTP monlist** (~556×), **DNS ANY** (~28–54×, larger with DNSSEC),
**SSDP** and **CLDAP** (tens to hundreds ×). Defenses: don't expose amplifiable services (bind privately),
BCP 38 source validation (stop spoofing at the source — the root fix), disable amplifiable features (NTP
monlist off, DNS recursion restricted), response rate limiting, and edge scrubbing (AWS Shield). The dual
requirement means removing either ingredient (spoofing OR exposure/amplification) defeats the attack.

### 18.9
Two risks: (1) **To you** — memcached exposed with no authentication means anyone on the internet can read
and write your cache (session data, cached PII, application data), and potentially disrupt your service;
this is the Chapter 5 insecure-default exposure (memcached, like Redis, ships trusting the network). (2)
**To others** — memcached on UDP has an enormous amplification ratio (~10,000–51,000×), so attackers can
use *your* exposed memcached as a reflector: they send tiny spoofed-source requests and your server blasts
huge responses at a victim, making your infrastructure a weapon in a Tbps-scale DDoS against a third party
(this is exactly what caused the 2018 record DDoS). **UDP makes the second risk worse** because UDP's lack
of a handshake makes source spoofing trivial (§4.3) — TCP-based services cannot be reflected this way
because the handshake would not complete with a spoofed source. So memcached-on-UDP combines spoofability
and extreme amplification into the most dangerous reflector known. Remediation: bind memcached to a private
interface (loopback or the app subnet, Chapter 5 §7), restrict it with security groups to only the app
tier, disable UDP if only TCP is needed (memcached supports disabling UDP — a specific mitigation after the
2018 attacks), add authentication (SASL), and never expose it to the internet. Fix the exposure and the
UDP amplification vector both.

### 18.16
UDP is connectionless, unreliable, and unordered — a minimal transport (ports + length + weak checksum,
8-byte header) with no handshake, no delivery guarantees, and no built-in security. TCP is
connection-oriented, reliable, and ordered — it establishes a connection via a three-way handshake,
acknowledges and retransmits lost data, delivers bytes in order, and provides flow/congestion control (at
the cost of latency and per-connection state). Use **UDP** when you need low latency and can tolerate loss
or handle reliability yourself: DNS (single fast query/response), real-time media (late data is useless),
DHCP, NTP, and QUIC/HTTP3 (which builds its own reliability on UDP). Use **TCP** when you need reliable,
ordered delivery of a stream: HTTP/1.1–2, database connections, file transfer, SSH — anything where every
byte must arrive in order. Security angle to add: UDP's lack of a handshake makes its source spoofable
(enabling amplification DDoS) and it provides no security (the application must), while TCP's handshake
resists blind spoofing but its connection state is a SYN-flood DoS target (Chapter 19); and neither
provides confidentiality — that is TLS's job on top. The choice is a trade-off of speed/simplicity
(UDP) vs reliability/source-verification (TCP), each with a distinct security profile.

### 18.18
Because UDP has no handshake, there is no round-trip that proves the sender can actually receive traffic at
the source address it claims. An attacker simply puts any source IP in the datagram (with raw-socket
capability or a crafted packet), and the receiver has no way to verify it — the packet is accepted and any
response is sent to the *claimed* (possibly spoofed) source, not necessarily the real sender. Contrast TCP:
to do anything useful, the initiator must complete the three-way handshake, which requires receiving the
SYN-ACK at its claimed address and responding with the correct sequence number — a blind spoofer who cannot
see the SYN-ACK cannot complete it, so TCP source addresses are much harder to forge. The consequences of
UDP's unverified source: (1) reflection/amplification attacks (send with the victim's spoofed source so
responses hit the victim); (2) source-IP-based authorization or attribution in any UDP protocol is broken
(the source is attacker-controlled data, not a credential — like the MAC address in Chapter 8 or reverse
DNS in Chapter 16). So UDP-based protocols must authenticate cryptographically, never by trusting the
source IP, and the internet mitigates spoofing at the network level via BCP 38 source address validation
(which the cloud fabric enforces for you).

### 18.20
QUIC/HTTP3 runs over UDP (usually port 443) and encrypts almost everything — the payload and much of the
handshake — with TLS 1.3 built in, so far less is visible to the network than with TCP+TLS (where the
handshake and, historically, the SNI were more exposed). This affects visibility in several ways: (1)
**middleboxes, IDS, and WAFs see much less** — they cannot inspect QUIC's encrypted contents in transit,
so network-based inspection that worked for TCP+TLS (or at least saw the handshake/SNI) is reduced; (2) it
is **carried over UDP**, which some inspection tooling and firewalls handle less richly than TCP, and it can
be **harder to distinguish from other UDP traffic**; (3) it improves **user privacy** against network
observers but creates a **defender blind spot**, similar to DoH (Chapter 17). How to handle it in a cloud
edge architecture: **terminate QUIC/HTTP3 at the edge** (CloudFront/ALB/CDN) where you decrypt and can then
apply WAF inspection and logging on the plaintext (Chapter 4 Stop 5, Chapter 29) — inspection moves to the
termination point rather than the network path; ensure your edge and WAF support HTTP/3; and where
in-transit network inspection is mandatory and QUIC cannot be terminated/inspected, some organizations
**block UDP/443 to force clients to fall back to TCP+TLS** (a real trade-off of performance/privacy vs
inspectability). The key point: QUIC shifts inspection from the network to the termination endpoint, and
your architecture must account for that (Chapter 29 covers HTTP/3 in depth).

---

*Next: Chapter 19 — TCP Part 1: The State Machine, Handshake, Sequence Numbers, Teardown, RST, TIME_WAIT.
Having seen UDP's minimalism, we now build TCP's reliability machinery — the three-way handshake (and the
SYN flood that targets it), sequence numbers, connection teardown, and the state machine that "stateful"
firewalls and security groups track.*
