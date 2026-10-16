# Chapter 24 — Packet Analysis Workshop: tcpdump, Wireshark, and BPF Filters

---

## 1. Why This Matters

Chapters 7–23 built the network stack layer by layer, and throughout, you captured and read packets with
tcpdump. This chapter consolidates that into a genuine packet-analysis capability — the single most valuable
hands-on skill in network security. Packet analysis is how you:

1. **Prove what is actually happening on the wire** — not what the config says, not what the application
   logs claim, but the ground truth. In an incident, "show me the packets" ends most arguments.
2. **Investigate incidents** — identify C2 traffic, exfiltration (DNS/ICMP tunneling — Chapters 17, 23),
   lateral movement, and the exact bytes of an attack.
3. **Debug the confusing failures** — TLS handshake failures (Chapter 28), MTU blackholes (Chapter 22),
   connection resets (Chapter 19), and the "works sometimes" bugs that only the wire reveals.
4. **Validate security controls** — confirm TLS is actually used (and its version/cipher), that traffic is
   encrypted, that a firewall is actually blocking, that data is not leaking in plaintext.

The core idea: **packet analysis captures the actual bytes on the wire and lets you read them across every
layer (Ethernet, IP, TCP/UDP, TLS, HTTP — Chapters 7–23) using tcpdump (capture/CLI), Wireshark (deep
analysis/GUI), and BPF filters (precise capture). It is the ground-truth observation skill that underpins
network security, incident response, and debugging — the ability to see exactly what happened rather than
what was configured or logged.** This chapter is a workshop: it assembles the layer-by-layer reading skills
of Part 1 into a fluent capability, and adds the filtering, capture-management, and analysis techniques that
make it practical at scale and under the constraints (encryption, cloud) of real environments.

---

## 2. Prerequisites

- **All of Part 1 so far (Chapters 7–23)** — this chapter reads packets across every layer built there:
  Ethernet (8), ARP (9), IP (10–11), routing (12), TCP/UDP (18–20), DNS (16–17), ICMP (23), and previews
  TLS (28) and HTTP (29). Chapter 7 (hex/headers) is essential.
- Familiarity with tcpdump from prior chapters' captures.

---

## 3. Mental Model

**Packet analysis is reading the actual bytes on the wire across every layer. You capture with tcpdump (or
Wireshark), filter precisely with BPF to get only the packets you need, and read each layer (Ethernet → IP →
TCP/UDP → application) using the header knowledge from Part 1. It is ground truth — what actually happened,
not what was configured or logged.**

```
   The workflow:
     1. CAPTURE   -- get the packets (tcpdump on the host/mirror; Wireshark on the desktop)
     2. FILTER    -- BPF (capture filter) to reduce volume; display filters (Wireshark) to focus analysis
     3. READ      -- decode each layer using Part 1's header knowledge (Chapters 7-23)
     4. FOLLOW    -- reconstruct streams/conversations to see the full exchange
     5. CONCLUDE  -- what actually happened (the ground truth for the incident/debug/validation)

   Two tools, two roles:
     tcpdump   -- lightweight, CLI, on the host/server; capture and quick reading; scriptable
     Wireshark -- rich GUI, deep dissection, stream reassembly, statistics; on the desktop (read the pcap)
```

Three ideas:

1. **Packets are ground truth.** Configuration says what *should* happen; logs say what the application
   *thinks* happened; packets say what *actually* happened on the wire. In security, the wire settles
   disputes — it shows the real bytes of an attack, the actual TLS version, the true source of traffic.
2. **Two tools for two roles.** **tcpdump** is the lightweight CLI capturer you run on servers/hosts
   (capture to a pcap, quick reads, scriptable, always available). **Wireshark** is the rich desktop
   analyzer you use to deeply dissect a pcap (protocol decoders, stream reassembly, statistics, filters). A
   common workflow: capture with tcpdump on the server, analyze the pcap in Wireshark on your desktop.
3. **Filtering is essential.** Networks carry enormous traffic; you must filter to the packets you care
   about. **BPF (Berkeley Packet Filter) capture filters** (in tcpdump and Wireshark) reduce what is
   captured (efficient, kernel-level); **Wireshark display filters** focus analysis after capture. Precise
   filtering is what makes packet analysis practical.

**The security framing:** packet analysis is the observation foundation of network security. It is how you
*verify* (is TLS really used? is the firewall really blocking? is data leaking?), *investigate* (what is
this C2/exfiltration traffic? what were the attack's exact bytes?), and *debug* (why does this connection
fail?). But it has a critical limitation in the modern encrypted world: **you can see that traffic exists
and its metadata (endpoints, timing, volume, TLS version/SNI) but not the encrypted payload** — so analysis
increasingly relies on metadata and on capturing at decryption points (the edge, after TLS termination —
Chapter 4 Stop 5). This chapter builds the capability and its limits.

---

## 4. Fundamentals

### 4.1 tcpdump — capture and read on the host

tcpdump is the CLI packet capturer, available everywhere. Core usage (assembled from Part 1):

```bash
# Basic capture with the essential flags:
$ sudo tcpdump -n -i any -c 100 'tcp port 443'
#   -n : numeric (no DNS/port-name resolution — ALWAYS in security work, Chapter 3; avoids slow/poisoned DNS)
#   -i any : all interfaces (or -i eth0 for one)
#   -c 100 : stop after 100 packets
#   'tcp port 443' : the BPF capture filter (§4.3)

# Verbosity and content:
$ sudo tcpdump -nn -v -i eth0 'host 10.0.1.5'      # -v verbose (more header detail); -nn also numeric ports
$ sudo tcpdump -n -X 'tcp port 80' -c 5             # -X : hex + ASCII dump (read payloads — Chapter 7)
$ sudo tcpdump -n -A 'tcp port 80' -c 5             # -A : ASCII only (read HTTP text)
$ sudo tcpdump -n -e 'arp' -c 5                      # -e : Ethernet headers (MAC/EtherType — Chapter 8)

# Capture to a file for later analysis (the tcpdump -> Wireshark workflow):
$ sudo tcpdump -n -i any -w capture.pcap 'tcp port 443'    # write pcap
$ tcpdump -n -r capture.pcap 'tcp port 443 and host 10.0.1.5'   # read pcap (apply a filter on read)
```

The flags to internalize: **`-n`** (numeric — always, for speed and to avoid attacker-controlled DNS/reverse
lookups — Chapters 3, 16), **`-i`** (interface), **`-c`** (count), **`-w`/`-r`** (write/read pcap),
**`-X`/`-A`** (payload hex/ASCII), **`-e`** (Ethernet), **`-v/-vv`** (verbosity). tcpdump's output notation
(flags `[S]`/`[S.]`/`[.]`/`[F.]`/`[R]` — Chapter 19; `802.1Q vlan` — Chapter 13; ICMP types — Chapter 23) you
already know from Part 1.

### 4.2 Wireshark — deep analysis on the desktop

Wireshark provides rich dissection of a pcap (captured by tcpdump on a server, or captured directly):

- **Protocol dissectors:** Wireshark decodes every layer automatically (Ethernet → IP → TCP → TLS → HTTP),
  showing each field labeled — the tool that does what you learned to do by hand in Part 1 (Chapter 7 §5).
- **Display filters:** a rich filter language (different from BPF — §4.3) applied *after* capture to focus
  analysis, e.g. `tls.handshake.type == 1` (TLS ClientHello), `http.request.method == "POST"`,
  `tcp.flags.reset == 1` (RSTs), `dns.qry.name contains "evil"`.
- **Follow Stream:** reassemble a TCP/UDP/TLS/HTTP conversation into a readable stream — see the full HTTP
  request/response, or the TLS handshake, as one exchange (§4.4).
- **Statistics:** conversation lists, protocol hierarchy, I/O graphs, expert info (retransmissions, resets,
  errors flagged) — for spotting anomalies (a burst of retransmissions, a flood of SYNs, unusual protocols).
- **Coloring rules and expert info:** Wireshark highlights retransmissions, resets, zero windows (Chapter
  20), malformed packets, and other anomalies — surfacing the security/performance signals.

The tcpdump→Wireshark workflow is standard: **capture headlessly on the server with tcpdump (`-w`), transfer
the pcap, analyze richly in Wireshark on the desktop.** This works because tcpdump runs anywhere (including
minimal servers/containers) while Wireshark's GUI is on your workstation.

### 4.3 BPF — the filter language

**BPF (Berkeley Packet Filter)** is the kernel-level capture-filter language used by tcpdump and Wireshark's
capture filters — efficient because it filters in the kernel before copying packets to userspace. The syntax
(assembled from Part 1's examples):

```bash
# Host, network, port:
'host 10.0.1.5'                      'net 10.0.0.0/16'         'port 443'      'portrange 8000-8100'
'src host 10.0.1.5'                  'dst port 5432'           'src net 10.0.1.0/24'

# Protocols:
'tcp'   'udp'   'icmp'   'arp'   'ip6'   'tcp port 443'   'udp port 53'

# Logical operators:
'tcp and port 443 and host 10.0.1.5'        'udp port 53 or tcp port 53'       'not arp'
'host 10.0.1.5 and not port 22'             '(port 80 or port 443) and host 10.0.1.5'

# Byte-level (advanced — matching header fields, Chapter 7):
'tcp[tcpflags] & tcp-syn != 0'              # SYN set (any SYN or SYN-ACK)
'tcp[tcpflags] & (tcp-syn|tcp-ack) = tcp-syn'   # SYN set, ACK clear (new inbound connections — Chapter 19)
'icmp[icmptype] = icmp-echo'                # ICMP echo (ping — Chapter 23)
'ip[6:2] & 0x3fff != 0'                     # fragmented packets (Chapter 22)
```

BPF is worth real fluency: it is the filter you use to capture *only* what matters (essential on busy links
where capturing everything is infeasible and where you must not capture sensitive unrelated traffic). The
byte-level filters (matching header fields directly) leverage exactly the header knowledge from Chapter 7
and throughout Part 1 — e.g. `tcp[tcpflags] & (tcp-syn|tcp-ack) = tcp-syn` captures new inbound connections
(SYN without ACK), useful for spotting a SYN flood (Chapter 19) or scanning (Chapter 123).

**Note the two filter types in Wireshark:** *capture filters* use BPF syntax (applied at capture, like
tcpdump); *display filters* use Wireshark's own richer syntax (applied after capture, e.g. `tcp.port ==
443`). Do not confuse them (`tcp port 443` is BPF/capture; `tcp.port == 443` is Wireshark display).

### 4.4 Following streams and reconstructing conversations

Individual packets are hard to read; **reconstructing the conversation** is where analysis happens:

- **Wireshark "Follow TCP/UDP/TLS/HTTP Stream":** reassembles all packets of a conversation into the readable
  byte stream — see the full HTTP request and response, the plaintext of an unencrypted protocol, or the TLS
  handshake sequence. This is how you read what actually transpired.
- **tcpdump equivalent:** less rich, but `-A`/`-X` shows payloads, and tools like `tcpflow` reconstruct
  streams from a pcap on the CLI.
- **Security use:** following a stream reveals the exact bytes of an attack (the injection payload, the
  exfiltrated data if unencrypted, the HTTP request that triggered an exploit), the credentials sent in
  plaintext (a finding — Chapter 5), or the full C2 exchange.

Stream reconstruction is where Part 1's per-layer reading becomes an investigation: you go from "these are
TCP segments" to "this is the HTTP POST with the SQL injection payload" or "this is data being exfiltrated in
DNS queries" (Chapter 17).

### 4.5 The encryption limitation and metadata analysis

The critical modern constraint: **most traffic is encrypted (TLS — Chapter 28, QUIC — Chapter 18), so you
cannot read the payload from a capture.** What you *can* see:

- **Metadata:** the endpoints (IPs, ports — Chapter 3), timing, volume, direction, and connection patterns —
  which is often enough (a connection to a known-bad IP, an unusual data volume, beaconing periodicity for
  C2, connections to the metadata service — Chapter 10).
- **TLS handshake details (partially):** the TLS version, cipher suites offered, and — in TLS ≤1.2 and often
  1.3 — the **SNI (server name)**, which reveals *which* site is being contacted even though the content is
  encrypted (Chapter 28). TLS fingerprinting (JA3/JA4 — the hash of ClientHello parameters) identifies the
  *client software* even without decryption — useful for spotting malware/C2 clients.
- **What you cannot see:** the encrypted application payload (the HTTP request/response, the actual data).

So modern packet analysis relies heavily on **metadata and TLS-handshake analysis**, and on capturing at
**decryption points** — the edge/reverse proxy where TLS terminates (Chapter 4 Stop 5), where the plaintext
HTTP is available for inspection (this is why WAFs sit after TLS termination — Chapter 22, 85). Or, for
debugging, capturing the pre-encryption traffic (e.g. `SSLKEYLOGFILE` to let Wireshark decrypt your own TLS
with the session keys — a legitimate debugging technique for traffic you control). The lesson: **encryption
(which you want, for confidentiality) reduces packet-analysis visibility, so analysis shifts to metadata and
to decryption points** — the same visibility trade-off as QUIC (Chapter 18) and DoH (Chapter 17).

### 4.6 Capturing in the cloud and at scale

Packet analysis in cloud/production has specific mechanisms and constraints:

- **VPC Traffic Mirroring / Flow Logs (AWS):** you cannot tcpdump the physical network in the cloud, but
  **VPC Traffic Mirroring** copies packets from an ENI to a monitoring appliance (full packet capture in the
  cloud), and **VPC Flow Logs** (Chapter 82) provide connection *metadata* (the 4-tuple, bytes, action) —
  the cloud's primary network-visibility tools. Flow Logs are metadata (like §4.5's metadata analysis at
  scale); Traffic Mirroring is full capture (for deep analysis).
- **Capturing on the host/container:** tcpdump on an instance/container captures that host's traffic (the
  practical approach for a specific host's traffic).
- **Scale and privacy:** capturing everything is infeasible and a privacy/compliance risk (packets contain
  sensitive data). Capture is targeted (specific hosts/filters/time windows), and captures are handled as
  sensitive data (they may contain PII, credentials, tokens — Chapter 5's classify-before-you-store applies
  to pcaps).
- **The pcap as sensitive data:** a full packet capture can contain plaintext credentials, tokens, PII, and
  session data — so pcaps must be handled, stored, and disposed of as sensitive data (a common oversight —
  a captured pcap left on a share is a data exposure).

The cloud packet-analysis reality: **use VPC Flow Logs for metadata at scale (Chapter 82), VPC Traffic
Mirroring for targeted full capture, and host/container tcpdump for specific hosts — and treat all captures
as sensitive data.** The encryption limitation (§4.5) means metadata (Flow Logs) is often the practical
primary tool, with full capture reserved for deep investigation.

---

## 5. Deep Technical Explanation: Packet Analysis as the Ground-Truth Discipline

Packet analysis is the *ground-truth discipline* of network security, and understanding its role, power, and
limits is what makes it useful rather than just a tool you know how to run.

**Why ground truth matters:** every other source of information about network behavior is an abstraction or a
claim. The configuration says what *should* happen (but may be wrong, or overridden, or not what you think).
Application logs say what the application *believes* happened (but may be incomplete, wrong, or manipulated by
an attacker). Metrics aggregate (losing detail). Packets are the actual bytes that traversed the wire — they
cannot lie about what was sent (though they can be crafted). So in security:

- **Verification:** "Is TLS actually used?" — the config says yes, but a capture *proves* it (or reveals a
  plaintext fallback, a wrong version, a downgrade). "Is the firewall blocking?" — the capture shows whether
  the packets actually arrive or are dropped. "Is data leaking in plaintext?" — only a capture reveals the
  credentials-in-the-clear (Chapter 5). Packet analysis is how you *validate* security controls against
  reality, not against configuration.

- **Investigation:** in an incident, packets reveal the attack's exact bytes (the injection payload, the C2
  exchange, the exfiltrated data), the true source (not the claimed one), and the timeline. "Show me the
  packets" is how disputes about what happened are settled, and how the precise indicators (IPs, payloads,
  patterns) for detection are extracted.

- **Debugging:** the confusing failures — TLS handshake failures (which cipher/version mismatch? — Chapter
  28), MTU blackholes (are large packets dropped? — Chapter 22), connection resets (who sent the RST? —
  Chapter 19), asymmetric routing, intermittent drops — are often *only* visible on the wire, because the
  application sees only "connection failed" while the packets show *why*.

**The power comes from Part 1's layered knowledge.** Packet analysis is only as good as your ability to read
the layers — and Chapters 7–23 built exactly that: hex/headers (7), Ethernet/MAC (8), ARP (9), IP/CIDR
(10–11), routing/TTL (12), TCP state/flags (19–20), UDP (18), DNS (16–17), ICMP (23). A capture is a stack of
these layers, and reading it fluently *is* the accumulated Part 1 knowledge applied. This is why the workshop
comes at the end of Part 1: it consolidates every layer's reading skill into one capability.

**The limits are as important as the power:**

1. **Encryption limits payload visibility** (§4.5) — the modern reality. You see metadata (endpoints,
   timing, volume, TLS handshake/SNI, JA3 fingerprint) but not the encrypted content. This is *good*
   (confidentiality — you *want* traffic encrypted) but shifts analysis to metadata and decryption points.
   The security engineer accepts this trade-off: encryption reduces your visibility *and* the attacker's, and
   you compensate with metadata analysis, capturing at TLS-termination points (the edge/WAF — Chapter 4), and
   endpoint/log telemetry (Chapters 13, 120).

2. **Scale limits full capture** (§4.6) — you cannot capture everything on a busy network; you filter (BPF)
   and target. Metadata at scale (Flow Logs) complements targeted full capture.

3. **Packets are sensitive data** (§4.6) — a pcap can contain plaintext credentials, tokens, and PII, so
   captures are handled as sensitive (classify-before-you-store — Chapter 5). A carelessly stored pcap is a
   data exposure.

The unifying insight: **packet analysis is the ground-truth observation discipline that validates,
investigates, and debugs network behavior by reading the actual bytes across every layer (the consolidated
Part 1 knowledge), using tcpdump, Wireshark, and BPF — powerful because it is reality rather than
configuration or claims, but limited by encryption (shifting analysis to metadata and decryption points),
scale (requiring targeted filtering), and the sensitivity of the captured data itself.** It is the skill that
turns Part 1's theory into operational capability, and it underpins incident response (Chapter 121),
detection (Chapter 118), and every network-debugging task. Mastering it — capturing precisely, reading every
layer, following streams, and knowing what encryption hides — is a defining competence of a network-literate
security engineer.

---

## 6. Internals: The Packet-Analysis Toolkit in Practice

### 6.1 Capture recipes (assembled from Part 1)

```bash
# General-purpose capture to a file, numeric, targeted:
$ sudo tcpdump -n -i any -w /tmp/inv.pcap 'host 10.0.1.5 and not port 22'   # exclude your own SSH

# Specific investigations:
$ sudo tcpdump -n 'tcp port 443' -c 20               # TLS traffic (Chapter 28)
$ sudo tcpdump -n 'udp port 53' -A                    # DNS (read query names — Chapter 16)
$ sudo tcpdump -n 'tcp[tcpflags] & (tcp-syn|tcp-ack) = tcp-syn'   # new inbound connections / SYN flood (Ch19)
$ sudo tcpdump -n 'icmp' -v                            # ICMP (types/codes — Chapter 23)
$ sudo tcpdump -n -e 'arp'                             # ARP (MITM detection — Chapter 9)
$ sudo tcpdump -n 'host 169.254.169.254'              # metadata service access (SSRF signal — Chapter 10, 50)
$ sudo tcpdump -n 'dst port 443 and not dst net 10.0.0.0/8'   # outbound HTTPS to the internet (egress/exfil — Ch3)
```

These recipes are Part 1's chapters as capture filters — each targets a specific security question (TLS
usage, DNS exfiltration, SYN floods, ARP MITM, metadata SSRF, egress). Building this recipe repertoire is the
practical output of the workshop.

### 6.2 Reading a capture across layers (the consolidated skill)

```bash
$ sudo tcpdump -nn -v -X 'tcp port 443 and host example.com' -c 3
# Read it top to bottom:
#   Ethernet (Chapter 8): src/dst MAC, EtherType (with -e)
#   IP (Chapter 7 §5, 10): version, TTL, protocol, src/dst IP
#   TCP (Chapter 19): ports, seq/ack, flags [S]/[S.]/[.], window
#   Payload (Chapter 7): the -X hex — for TLS, you see the handshake framing but encrypted app data (§4.5)
```

This is the consolidation: one capture, read across every layer using the header knowledge from all of Part
1. Practicing this until it is fluent is the workshop's core exercise.

### 6.3 Wireshark display filters for security analysis

```
# In Wireshark (display filters — different syntax from BPF, §4.3):
tls.handshake.type == 1                    # TLS ClientHello (see version, ciphers, SNI — Chapter 28)
tls.handshake.extensions_server_name       # the SNI (which site — even when content is encrypted, §4.5)
http.request.method == "POST"               # HTTP POSTs (data submission — if unencrypted)
tcp.flags.reset == 1                        # RSTs (resets — Chapter 19; censorship/attacks)
tcp.analysis.retransmission                 # retransmissions (loss/interference — Chapter 20)
dns.qry.name contains "suspicious"          # DNS queries (exfiltration/C2 — Chapter 17)
ip.addr == 169.254.169.254                  # metadata service (SSRF — Chapter 10, 50)
frame contains "password"                    # plaintext credentials (a finding — Chapter 5)
```

Wireshark's display filters (and Follow Stream) turn a pcap into an investigation — spotting the ClientHello
details, the SNI (which site despite encryption), RSTs, retransmissions, DNS exfiltration, metadata access,
and plaintext credentials.

### 6.4 Handle captures as sensitive data

```bash
# A pcap can contain credentials, tokens, PII (§4.6) — treat it as sensitive:
$ ls -l /tmp/inv.pcap                       # restrict permissions
$ chmod 600 /tmp/inv.pcap                    # owner-only
# Extract only what you need, then dispose:
$ tcpdump -n -r /tmp/inv.pcap 'host <target>' -w /tmp/scoped.pcap   # scope down
$ shred -u /tmp/inv.pcap                      # secure delete when done (note SSD caveat — Chapter 1)
# NEVER leave full captures on shares; NEVER capture more than the investigation needs.
```

Treating pcaps as sensitive data (classify-before-you-store — Chapter 5) is a discipline often forgotten — a
full capture is a data exposure if mishandled.

---

## 7. Real-World Example: Packet Analysis in a Ledger Incident

**Scenario: Ledger suspects an ECS task is compromised and exfiltrating data.** The packet-analysis
investigation, applying the whole toolkit:

1. **Metadata first (VPC Flow Logs — §4.6, Chapter 82):** the fastest, always-available source. Flow Logs
   show the task's connections — and reveal an unexpected outbound connection to an unknown external IP, and
   DNS queries to a suspicious domain. Metadata (endpoints, volume) is enough to confirm suspicion and scope.

2. **Targeted full capture (VPC Traffic Mirroring or host tcpdump — §4.6):** to see more, mirror the task's
   traffic or tcpdump on the host: `tcpdump -n 'host <task-ip> and not port 443'` scoped to the investigation.

3. **DNS exfiltration check (§4.4, Chapter 17):** `tcpdump -n 'udp port 53' -A` reveals DNS queries with
   long, high-entropy subdomains to the attacker's domain — DNS tunneling exfiltration (Chapter 17 §4.5). The
   query names (metadata, visible even without payload decryption) are the evidence.

4. **Metadata service access (§6.1, Chapter 10, 50):** `tcpdump -n 'host 169.254.169.254'` confirms whether
   the task accessed the metadata service (SSRF → credential theft — Chapter 78) — a key indicator.

5. **The encryption limit (§4.5):** the exfiltration over HTTPS (443) is encrypted, so the payload is not
   readable — but the metadata (destination, volume, timing) confirms exfiltration, and the SNI (if TLS ≤1.2/
   visible) reveals the destination host. To see content, Ledger would need to capture at a TLS-termination
   point (the edge/proxy — §4.5, Chapter 4) or use endpoint telemetry (Chapter 120).

6. **Handling the capture (§6.4):** the pcap contains sensitive data (possibly the exfiltrated content if any
   was plaintext, plus other traffic), so it is handled as sensitive — scoped, permissioned, and disposed of
   properly.

The investigation combines metadata (Flow Logs — fast, at scale), targeted full capture (Traffic Mirroring/
tcpdump — deep), per-layer reading (DNS query names, metadata-service access, TLS metadata), and the
recognition of the encryption limit (payload not readable; rely on metadata and decryption points). This is
packet analysis as the ground-truth discipline for an incident.

The Ledger takeaway: **packet analysis (metadata via Flow Logs, targeted full capture via Traffic Mirroring/
tcpdump, per-layer reading, and stream reconstruction) is how Ledger establishes ground truth in an incident
— confirming exfiltration, identifying the channel (DNS tunneling, HTTPS to an unknown IP), checking for
metadata-service access, and extracting indicators — within the modern constraints (encryption limits payload
visibility → rely on metadata and decryption points; captures are sensitive data).** The whole of Part 1's
layer-reading knowledge is applied here as one investigative capability.

---

## 8. Hands-On Demonstration

### LAB 24.1 — Packet Analysis Across Every Layer

**Objective.** Consolidate Part 1's layer-reading into a fluent packet-analysis capability: capture with
tcpdump, filter with BPF, read every layer, follow a stream, observe the encryption limit, and handle the
capture as sensitive data.

**Cost.** Free. **Environment.** ENV-1 (+ Wireshark on the desktop if available). **Time.** 60–90 minutes.

**Steps.**

*Step 1 — Capture and read across layers.*

```bash
# Capture a mix of traffic to a file:
sudo tcpdump -n -i any -w /tmp/lab24.pcap -c 200 &
# Generate varied traffic:
curl -s https://example.com > /dev/null          # TLS/HTTP (Chapters 28, 29)
dig example.com @8.8.8.8 > /dev/null             # DNS (Chapter 16)
ping -c2 8.8.8.8 > /dev/null                      # ICMP (Chapter 23)
sleep 2; sudo pkill tcpdump
# Read it, layer by layer:
tcpdump -nn -v -r /tmp/lab24.pcap 'tcp port 443' -c 3    # IP/TCP layers (Chapters 10, 19)
tcpdump -n -A -r /tmp/lab24.pcap 'udp port 53' -c 2      # DNS query names (Chapter 16)
tcpdump -n -e -r /tmp/lab24.pcap 'arp' -c 2 2>/dev/null  # Ethernet/ARP (Chapters 8, 9)
tcpdump -n -v -r /tmp/lab24.pcap 'icmp' -c 2             # ICMP types (Chapter 23)
```

For each, read the layers using Part 1: Ethernet (MAC/EtherType), IP (TTL/protocol/addresses), TCP (flags/
seq/ports), and identify the protocol.

*Step 2 — BPF filtering practice.*

```bash
# Practice targeted BPF filters (§4.3):
tcpdump -n -r /tmp/lab24.pcap 'tcp[tcpflags] & tcp-syn != 0'      # SYNs (connection starts — Chapter 19)
tcpdump -n -r /tmp/lab24.pcap 'dst port 443 and not dst net 10.0.0.0/8'   # outbound HTTPS to internet
tcpdump -n -r /tmp/lab24.pcap 'icmp[icmptype] = icmp-echo'        # pings (Chapter 23)
```

*Step 3 — Follow a stream and observe the encryption limit.*

```bash
# For the TLS connection, observe you can see the handshake but NOT the encrypted payload (§4.5):
tcpdump -n -X -r /tmp/lab24.pcap 'tcp port 443' -c 5
# You see the TLS record framing and handshake, but the application_data is encrypted (unreadable).
# In Wireshark: open lab24.pcap, filter "tls.handshake.type == 1", see the ClientHello's version/ciphers/SNI;
#   then "Follow TLS Stream" -> encrypted (unless you have the keys). Contrast an HTTP (plaintext) stream.
```

**Expected:** the TLS handshake metadata (version, ciphers, SNI) is visible, but the application payload is
encrypted — the modern encryption limit (§4.5). If you capture a plaintext protocol (HTTP), "Follow Stream"
shows the full readable exchange — the contrast that motivates encryption.

*Step 4 — A security-question capture.*

```bash
# Metadata-service access (SSRF signal — §6.1):
sudo tcpdump -n 'host 169.254.169.254' -c 5 &     # (would show any metadata access)
# DNS exfiltration signature (§4.4, Chapter 17): long high-entropy subdomains to one domain.
# ARP MITM signature (Chapter 9): one MAC for many IPs, gratuitous ARP.
```

*Step 5 — Handle the capture as sensitive data.*

```bash
chmod 600 /tmp/lab24.pcap                          # restrict (§6.4)
strings /tmp/lab24.pcap | grep -iE 'password|token|authorization' | head   # check for plaintext secrets
# If any plaintext credentials appear -> a finding (Chapter 5); the pcap is sensitive.
shred -u /tmp/lab24.pcap 2>/dev/null || rm -f /tmp/lab24.pcap   # dispose properly
```

**Security implications.** Write down: (a) packets are ground truth (verify/investigate/debug); (b) reading a
capture is the consolidated Part 1 layer knowledge; (c) BPF filtering targets what matters; (d) the
encryption limit (metadata visible, payload not) → rely on metadata and decryption points; (e) pcaps are
sensitive data (handle/dispose carefully); (f) security-question capture recipes (TLS usage, DNS exfil,
metadata access, ARP MITM, egress).

**Cleanup.**
```bash
rm -f /tmp/lab24.pcap /tmp/scoped.pcap 2>/dev/null
```

---

## 9. Security Implications

- **Packet analysis is ground truth** — the actual bytes on the wire, not configuration or claims. It is how
  you **verify** controls (is TLS really used? is the firewall blocking? is data leaking?), **investigate**
  incidents (attack bytes, C2, exfiltration, true source), and **debug** the confusing failures (TLS/MTU/RST
  issues only the wire reveals).
- **Reading a capture is the consolidated Part 1 knowledge** — Ethernet (8), ARP (9), IP (10–11), routing
  (12), TCP/UDP (18–20), DNS (16–17), ICMP (23) — applied as one capability. tcpdump (capture/CLI),
  Wireshark (deep analysis), and BPF (precise filtering) are the tools.
- **The encryption limit is the modern reality** — most traffic is encrypted, so you see **metadata**
  (endpoints, timing, volume, TLS version/SNI, JA3 fingerprint) but not the payload. Analysis shifts to
  metadata and to **decryption points** (the edge/WAF after TLS termination — Chapter 4). Encryption is good
  (confidentiality) and reduces both your and the attacker's visibility.
- **Filtering (BPF) is essential** — capture only what matters (efficiency, and avoiding capturing sensitive
  unrelated traffic); the byte-level filters leverage Part 1's header knowledge.
- **Captures are sensitive data** — pcaps can contain plaintext credentials, tokens, and PII, so handle,
  store, and dispose of them as sensitive (classify-before-you-store — Chapter 5); a mishandled pcap is a
  data exposure.
- **Cloud packet analysis:** VPC Flow Logs (metadata at scale — Chapter 82), VPC Traffic Mirroring (targeted
  full capture), host/container tcpdump (specific hosts) — with the encryption limit and sensitivity
  handling.

---

## 10. Attack Scenarios (what packet analysis reveals)

Packet analysis is primarily defensive/investigative; it *reveals* attacks:

1. **C2 / exfiltration** — connections to known-bad IPs, DNS/ICMP tunneling (Chapters 17, 23), beaconing
   periodicity, unusual data volumes/destinations — visible in metadata even when encrypted.
2. **Metadata-service SSRF** — traffic to `169.254.169.254` from an application (Chapters 10, 50, 78).
3. **ARP/DNS MITM** — one MAC for many IPs, gratuitous ARP (Chapter 9); DNS answers changing (Chapter 17).
4. **Scanning / SYN floods** — SYN patterns (`tcp[tcpflags] & (tcp-syn|tcp-ack) = tcp-syn`), port sweeps
   (Chapters 19, 123).
5. **Plaintext credential exposure** — credentials/tokens visible in a capture (Chapter 5) — a finding.
6. **Downgrade / plaintext fallback** — TLS not actually used, wrong version, or a plaintext fallback
   (Chapter 28) — visible in the handshake metadata.
7. **The attacker's use of packet analysis** — attackers also sniff (given on-path position — Chapters 8–9),
   which is why encryption (making sniffed traffic ciphertext) is the defense (the packet-analysis limit
   §4.5 protects you against *their* analysis too).

---

## 11. Defensive Techniques

- **Build a packet-analysis capability** — fluency with tcpdump, Wireshark, and BPF, and the recipe
  repertoire (§6.1) for security questions (TLS usage, DNS exfil, metadata access, ARP MITM, egress). It is
  the ground-truth skill for verification, investigation, and debugging.
- **Use cloud-native network visibility** — **VPC Flow Logs** (metadata at scale, always on — Chapter 82),
  **VPC Traffic Mirroring** (targeted full capture), host/container tcpdump — as the cloud packet-analysis
  toolkit.
- **Capture at decryption points** for content analysis — the edge/reverse proxy where TLS terminates
  (Chapter 4 Stop 5), where the WAF inspects plaintext (Chapter 85); or `SSLKEYLOGFILE` for debugging your
  own TLS. Accept that encrypted traffic requires metadata analysis or decryption-point capture.
- **Rely on metadata analysis** — endpoints, timing, volume, TLS handshake/SNI, JA3 fingerprints — since most
  traffic is encrypted; combine with endpoint/log telemetry (Chapters 13, 120).
- **Filter precisely (BPF)** — capture only what the investigation needs (efficiency, and minimizing
  sensitive-data capture); scope captures to specific hosts/time windows.
- **Handle captures as sensitive data** — restrict permissions, scope, and securely dispose of pcaps
  (classify-before-you-store — Chapter 5); never leave full captures on shares.
- **Encrypt your own traffic** — so that an attacker's packet analysis (given on-path position — Chapters
  8–9) yields only ciphertext; the encryption limit (§4.5) protects you against their sniffing too.

---

## 12. Production Architecture

Packet analysis / network visibility, VPS vs cloud:

```
 NEED                     TOOL                             SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------   -------------------   -------------------------
 metadata at scale        connection metadata               (limited/host logs)  VPC Flow Logs (Ch82)
 targeted full capture    packet capture                    tcpdump on the host   VPC Traffic Mirroring / host tcpdump
 deep analysis            protocol dissection               Wireshark (desktop)   Wireshark on the pcap
 precise capture          BPF capture filters               tcpdump BPF           tcpdump/Mirroring BPF
 content (encrypted)      capture at TLS-termination         nginx edge capture    ALB/CloudFront edge + WAF (Ch85)
 detection integration    IDS/telemetry                     Suricata/Zeek         GuardDuty + Flow Logs (Ch82)
 capture sensitivity      handle as sensitive data          restrict/dispose      restrict/dispose (S3 encryption)
```

The architectural principle: **packet analysis is the ground-truth network-visibility discipline —
metadata at scale (Flow Logs), targeted full capture (Traffic Mirroring/tcpdump), deep analysis (Wireshark),
and precise filtering (BPF) — applied for verification, investigation, and debugging, within the modern
constraints (encryption limits payload visibility → metadata + decryption-point capture; captures are
sensitive data).** It consolidates all of Part 1's layer-reading into one operational capability, and it
underpins detection (Chapter 118), incident response (Chapter 121), and every network-debugging task. In the
cloud, it becomes managed (Flow Logs for metadata, Traffic Mirroring for capture, GuardDuty for detection),
with the same encryption limits and sensitivity handling. The defining competence: capture precisely, read
every layer fluently, follow streams, know what encryption hides, and treat the capture as sensitive.

---

## 13. Common Mistakes

1. **Not using `-n`** — reverse DNS/port-name resolution is slow and can be attacker-influenced (Chapters 3,
   16); always numeric in security work.
2. **Capturing everything** — infeasible at scale, and a privacy/sensitivity risk; filter precisely (BPF).
3. **Confusing BPF and Wireshark display-filter syntax** (`tcp port 443` vs `tcp.port == 443`).
4. **Expecting to read encrypted payloads** — the encryption limit (§4.5); rely on metadata and decryption
   points.
5. **Mishandling captures** — leaving pcaps (with credentials/PII) on shares; treat as sensitive data (§6.4).
6. **Relying on config/logs over the wire** — packets are ground truth; verify against reality.
7. **Not using cloud-native visibility** — ignoring VPC Flow Logs (metadata) and Traffic Mirroring (capture)
   in favor of trying to tcpdump the physical network (impossible in the cloud).
8. **Not building the recipe repertoire** — knowing tcpdump exists is not the same as fluently answering
   security questions with it (§6.1).

---

## 14. Troubleshooting

| Need | Approach | Command/tool |
|---|---|---|
| Verify TLS is actually used and its version | capture the handshake | `tcpdump -n 'tcp port 443'`; Wireshark `tls.handshake` (Chapter 28) |
| Confirm a firewall is blocking | capture at both sides | `tcpdump` — do packets arrive/leave? (Chapters 12, 76) |
| Find data leaking in plaintext | capture + search payloads | `tcpdump -A`; `strings pcap | grep -i password` (Chapter 5) |
| Investigate C2/exfiltration | metadata + targeted capture | Flow Logs (metadata); tcpdump/Traffic Mirroring; DNS/ICMP tunneling signatures (Chapters 17, 23) |
| Debug a TLS handshake failure | capture the handshake | Wireshark `tls.handshake`; version/cipher mismatch (Chapter 28) |
| Debug an MTU blackhole | capture large packets | tcpdump; DF ping (Chapter 22) |
| Detect ARP/DNS MITM | capture ARP/DNS | `tcpdump -e arp` (one MAC many IPs); DNS answer changes (Chapters 9, 17) |
| Check metadata-service access | filter the metadata IP | `tcpdump -n 'host 169.254.169.254'` (Chapters 10, 50) |

---

## 15. Practical Lab

Lab 24.1 is in §8. Register it in the lab index. Extension: capture a realistic multi-protocol session (web
browsing generating DNS, TLS, HTTP/2, maybe QUIC), open it in Wireshark, and produce a written analysis
identifying every protocol/layer, the TLS handshake details (version, ciphers, SNI), any plaintext, and any
security-relevant observations (metadata visible despite encryption, etc.) — the capstone packet-analysis
exercise that proves fluency across all of Part 1.

---

## 16. Exercises

### Concept questions

**24.1** Explain why packet analysis is "ground truth" and give three security uses (verify, investigate,
debug) with an example of each.

**24.2** Explain the roles of tcpdump, Wireshark, and BPF, and the tcpdump→Wireshark workflow.

**24.3** Explain the encryption limitation of packet analysis and what you can still see (metadata, TLS
handshake, SNI, JA3). How does analysis adapt?

**24.4** Explain why captures are sensitive data and how to handle them.

**24.5** Explain the difference between BPF capture filters and Wireshark display filters, with an example of
each.

### Debugging problems

**24.6** An application logs "connection failed" intermittently. How do you use packet analysis to find the
real cause, and what would you look for?

**24.7** A config says TLS 1.3 is enforced, but a security scan flags TLS 1.0. How do you settle this with
packet analysis?

**24.8** You suspect data exfiltration but all traffic is encrypted. What can packet analysis still tell you?

### Security scenarios

**24.9** Design the network-visibility architecture for a cloud environment, naming the tools for metadata,
full capture, and detection, and addressing the encryption limit and capture sensitivity.

**24.10** You are handed a pcap from an incident. Walk through your analysis methodology, layer by layer, to
extract indicators.

### Architecture questions

**24.11** Explain how packet analysis consolidates all of Part 1's layer knowledge, and how it underpins
detection (Chapter 118) and incident response (Chapter 121).

**24.12** Explain how the encryption limit shifts network visibility to metadata and decryption points, and
how you architect for content inspection despite encryption (bridge to Chapters 4, 85).

### Hands-on exercises

**24.13** Capture a multi-protocol session and read every layer (Ethernet→IP→TCP→app) for one connection.

**24.14** Write BPF filters for five security questions (TLS usage, DNS exfil, SYN flood, metadata access,
egress) and test them.

**24.15** Demonstrate the encryption limit: capture a TLS session, show the handshake metadata is visible but
the payload is not; contrast with a plaintext protocol.

### Interview questions

**24.16** "How do you use packet analysis in an incident?"

**24.17** "What can and can't you see in a packet capture of encrypted traffic?"

**24.18** "Walk me through capturing and analyzing traffic to verify a security control."

**24.19** "How do you do packet analysis in the cloud?"

**24.20** "Why is a packet capture ground truth, and what are its limits?"

---

## 17. Summary

- **Packet analysis is the ground-truth discipline of network security** — reading the actual bytes on the
  wire across every layer, which is what actually happened (not configuration or claims). It is how you
  **verify** controls, **investigate** incidents, and **debug** the confusing failures.
- **Reading a capture is the consolidated Part 1 knowledge** (Ethernet 8, ARP 9, IP 10–11, routing 12,
  TCP/UDP 18–20, DNS 16–17, ICMP 23) applied as one capability, using **tcpdump** (capture/CLI, on
  servers), **Wireshark** (deep dissection/streams/statistics, on the desktop), and **BPF** (precise
  kernel-level capture filtering).
- **Filter precisely (BPF)** — capture only what matters (efficiency, minimizing sensitive-data capture);
  byte-level filters leverage Part 1's header knowledge (e.g. SYN-without-ACK for new connections).
- **The encryption limit is the modern reality** — most traffic is encrypted, so you see **metadata**
  (endpoints, timing, volume, TLS version/SNI, JA3 fingerprint) but not the payload; analysis shifts to
  **metadata and decryption points** (the edge/WAF after TLS termination — Chapter 4). Encryption reduces
  both your and the attacker's visibility (a good trade-off).
- **Captures are sensitive data** — pcaps can contain plaintext credentials/tokens/PII, so handle, store, and
  dispose of them as sensitive (classify-before-you-store — Chapter 5).
- **Cloud packet analysis:** **VPC Flow Logs** (metadata at scale — Chapter 82), **VPC Traffic Mirroring**
  (targeted full capture), host/container tcpdump — with the encryption limit and sensitivity handling. It
  underpins detection (Chapter 118) and incident response (Chapter 121), consolidating all of Part 1 into one
  operational capability.

---

## 18. Knowledge Check

1. Why is packet analysis "ground truth," and what are three security uses? (§3, §5)
2. What are the roles of tcpdump, Wireshark, and BPF? (§4.1–4.3)
3. What can you still see in encrypted traffic, and what can't you? (§4.5)
4. Why are captures sensitive data, and how are they handled? (§4.6, §6.4)
5. What is the difference between BPF and Wireshark display filters? (§4.3)
6. What are the cloud packet-analysis tools and their roles? (§4.6)
7. Why always use `-n`? (§4.1, Chapters 3, 16)
8. How does the encryption limit shift analysis? (§4.5, §5)
9. Write a BPF filter for new inbound connections (SYN without ACK). (§4.3)
10. How does packet analysis consolidate Part 1? (§5)

---

## 19. Further Exploration

- The tcpdump and Wireshark documentation and BPF filter reference; and the pcap-filter man page
  (`man 7 pcap-filter`) — the filter syntax.
- Wireshark's sample captures (wiki.wireshark.org/SampleCaptures) — practice reading real captures of every
  protocol.
- Zeek (formerly Bro) and Suricata — network security monitoring tools that do packet/metadata analysis at
  scale (bridge to Chapters 13, 120).
- AWS VPC Flow Logs and Traffic Mirroring documentation — the cloud packet-analysis tools (Chapter 82).
- The `SSLKEYLOGFILE` technique for decrypting your own TLS in Wireshark (debugging traffic you control).
- Capstone: capture and fully analyze a real browsing session (Lab 24.1 extension) — the proof of Part 1
  fluency. Next, Chapter 25 begins cryptography, the foundation of TLS (Chapter 28) whose handshake you just
  saw in captures.

---

## Solutions

### 24.3
The encryption limitation is that most traffic is encrypted (TLS — Chapter 28, QUIC — Chapter 18), so a
packet capture cannot read the **application payload** — the actual HTTP request/response, the data. What you
*can* still see: (1) **Metadata** — the endpoints (source/destination IPs and ports), timing, direction,
volume, and connection patterns; this is often enough (a connection to a known-bad IP, an unusual data
volume, beaconing periodicity for C2, access to the metadata service). (2) **TLS handshake details
(partially)** — the negotiated TLS version and cipher suites, and (in TLS ≤1.2 and often 1.3) the **SNI**
(the server name), which reveals *which* site is being contacted even though the content is encrypted. (3)
**TLS/client fingerprints (JA3/JA4)** — a hash of the ClientHello parameters that identifies the *client
software*, useful for spotting known malware/C2 clients without decryption. What you cannot see: the
encrypted application data. Analysis adapts by: relying on **metadata analysis** (endpoints/timing/volume/
patterns), using **TLS-handshake/SNI/JA3** to identify sites and clients, capturing at **decryption points**
(the edge/reverse proxy where TLS terminates — Chapter 4 Stop 5, where a WAF inspects plaintext — Chapter 85)
for content, using `SSLKEYLOGFILE` to decrypt your own traffic for debugging, and combining with **endpoint
and log telemetry** (Chapters 13, 120). The trade-off is deliberate: encryption reduces *your* payload
visibility but also the *attacker's* (they see ciphertext when sniffing — Chapters 8–9), which is why you
want traffic encrypted; you compensate with metadata analysis and decryption-point capture.

### 24.8
Even with all traffic encrypted, packet analysis (and metadata sources like VPC Flow Logs) can still reveal a
great deal about suspected exfiltration: (1) **Destinations** — connections to unknown, known-bad, or
unexpected external IPs/domains (an application talking to an IP it never normally contacts is a strong
signal); the SNI (if visible) reveals the destination host even over TLS. (2) **Volume and direction** — an
unusual amount of *outbound* data (exfiltration is outbound), especially from a host that normally sends
little, and the timing/volume pattern. (3) **DNS and ICMP** — DNS-tunneling exfiltration (Chapter 17) shows
long, high-entropy subdomain queries to one domain (the query *names* are metadata, visible without
decrypting anything); ICMP tunneling (Chapter 23) shows unusual ICMP volume/payloads. (4) **Beaconing** —
regular, periodic connections (C2 check-ins) are visible in the timing pattern even when encrypted. (5)
**Metadata-service access** — traffic to `169.254.169.254` (SSRF/credential theft — Chapters 10, 50, 78). (6)
**JA3/client fingerprints** — identifying known malware/C2 client software from the TLS ClientHello. What you
*cannot* see is the encrypted payload content (the actual exfiltrated data over HTTPS) — for that you would
capture at a TLS-termination point (the edge) or use endpoint telemetry (Chapter 120). So the methodology is:
use metadata (destinations, volume, timing, DNS query names, ICMP) to confirm and scope the exfiltration and
extract indicators, recognize the channel (HTTPS to an unknown IP, DNS/ICMP tunneling), check for
metadata-service access, and go to decryption points or endpoint telemetry for content. Encryption limits
payload visibility but leaves ample metadata to detect and investigate exfiltration.

### 24.16
In an incident, packet analysis establishes ground truth — what actually traversed the wire — to confirm the
compromise, identify the attack, extract indicators, and scope the impact. Methodology: (1) **Start with
metadata at scale** — VPC Flow Logs (Chapter 82) or connection logs to quickly see the suspect host's
connections, spotting unexpected destinations (known-bad IPs, the metadata service `169.254.169.254`),
unusual outbound volume, and DNS queries — fast and always available. (2) **Targeted full capture** — VPC
Traffic Mirroring or tcpdump on the host, scoped with BPF filters to the investigation (`tcpdump -n 'host
<suspect> and not port 22' -w incident.pcap`), to see more detail. (3) **Read across layers** using Part 1's
knowledge — identify the protocols, connection states (SYN floods/scanning — Chapter 19), ARP anomalies
(MITM — Chapter 9), DNS/ICMP tunneling signatures (long high-entropy subdomains — Chapters 17, 23), and
metadata-service access. (4) **Follow streams** to reconstruct conversations and read plaintext exchanges
(the attack's exact bytes — injection payloads, C2 commands, exfiltrated data *if unencrypted*). (5)
**Account for encryption** — encrypted payloads are not readable, so rely on metadata (destinations, volume,
timing, SNI, JA3) and, for content, capture at TLS-termination points or use endpoint telemetry (Chapter
120). (6) **Extract indicators** — IPs, domains, payloads, patterns — for detection (Chapter 118) and to
scope the incident. (7) **Handle the pcap as sensitive data** (§6.4) — it may contain credentials/PII. The
result is ground truth: what happened, how, the indicators, and the scope — settling disputes that
configuration and logs alone cannot.

### 24.20
A packet capture is ground truth because it records the *actual bytes that traversed the wire* — the real
events, not an abstraction or a claim. Every other information source about network behavior is derived or
fallible: configuration says what *should* happen (but may be wrong, overridden, or misunderstood);
application logs say what the application *believes* happened (but may be incomplete, wrong, or manipulated by
an attacker); metrics aggregate and lose detail. The wire cannot misrepresent what was actually sent (though
packets can be crafted). So packets settle disputes — they *prove* whether TLS is really used and its
version, whether a firewall really blocks, whether data leaks in plaintext, what the exact bytes of an attack
were, and the true source of traffic. Its limits: (1) **Encryption** — most traffic is encrypted, so you see
metadata (endpoints, timing, volume, TLS version/SNI, JA3) but not the payload; analysis shifts to metadata
and decryption points (the edge/WAF), and content requires capturing at TLS-termination or endpoint
telemetry. (2) **Scale** — you cannot capture everything on a busy network, so you filter (BPF) and target;
metadata at scale (Flow Logs) complements targeted capture. (3) **Sensitivity** — a capture can contain
plaintext credentials, tokens, and PII, so it is itself sensitive data to be handled and disposed of
carefully. (4) **On-path requirement** — you can only capture traffic you can see (your host, a mirror/SPAN,
or a decryption point), and in the cloud you use Flow Logs/Traffic Mirroring rather than tapping the physical
network. Within these limits, packet analysis is the definitive ground-truth discipline for verifying,
investigating, and debugging — the operational culmination of Part 1's layer-by-layer knowledge.

---

*This completes the observation skills of Part 1. Next: Chapter 25 — Cryptography Part 1: Symmetric
Encryption, Modes, Hashes, MACs, and Randomness. Having captured TLS handshakes and seen encryption's role as
both a control and a visibility limit, we now build cryptography from the ground up — the foundation of TLS
(Chapter 28), PKI (Chapter 27), JWTs (Chapter 60), and every confidentiality/integrity control in the book.*
