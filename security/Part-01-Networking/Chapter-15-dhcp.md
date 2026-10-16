# Chapter 15 — DHCP: Bootstrapping Identity on a Network, and DHCP Attacks

---

## 1. Why This Matters

Every chapter so far assumed a host already had an IP address, a subnet mask, a default gateway, and a
DNS server (Chapters 8–14). **DHCP is how a host gets all of that automatically** — and because it
hands a client its gateway and DNS, **whoever controls DHCP controls where the victim's traffic goes and
how names resolve.** That makes DHCP a high-leverage attack surface and a fundamental trust-bootstrapping
problem.

For a cloud security engineer, DHCP matters in specific ways:

1. **DHCP is a trust-on-first-use bootstrapping problem** — a host with no configuration must trust
   whatever DHCP server answers first. This is the same unauthenticated-trust pattern as ARP (Chapter 9)
   and NDP (Chapter 11), and it enables **rogue DHCP** attacks that MITM an entire segment by handing out
   a malicious gateway and DNS.
2. **DHCP snooping is the foundation of Dynamic ARP Inspection** (Chapter 9 §11). DAI validates ARP
   against the DHCP-snooping binding table, so understanding DHCP is a prerequisite for understanding the
   primary ARP defense.
3. **The cloud provides DHCP as a managed, trusted service** (AWS "DHCP option sets"), removing the
   rogue-DHCP attack inside a VPC — another instance of "the cloud SDN removes an L2/bootstrapping attack"
   (Chapters 8–9). But you configure DHCP option sets (especially the DNS servers), and misconfiguring
   them has security consequences.
4. **DHCP logs are an asset-inventory and IR source** — leases record which MAC got which IP when, useful
   for attribution (and, as Chapter 11 noted, incomplete for SLAAC/IPv6 hosts).

The core idea: **DHCP automates network configuration by having a client broadcast a request and accept
a server's offer of an IP, mask, gateway, and DNS — an unauthenticated, first-answer-wins exchange that
bootstraps the client's entire network trust. Controlling DHCP means controlling the victim's gateway and
DNS, i.e. a full MITM.** The defenses (DHCP snooping, port security) and the cloud's managed DHCP address
this, and DHCP snooping in turn enables the ARP defense you already learned.

---

## 2. Prerequisites

- Chapter 10 (addresses, masks, gateway), Chapter 12 (default gateway/routing), Chapter 16-preview (DNS —
  DHCP hands out the DNS server).
- Chapter 9 (ARP, and DAI which depends on DHCP snooping) and Chapter 8 (broadcast, L2 — DHCP starts with
  a broadcast).
- The unauthenticated-trust pattern from Chapters 9 and 11 — DHCP is the same shape.

---

## 3. Mental Model

**DHCP is how a host with no network identity gets one: it shouts "I need configuration" to the whole
segment, and trusts the first server that answers with an IP, mask, gateway, and DNS. That trust is
unauthenticated — whoever answers first (or fastest) configures the client.**

```
   A host boots with NO IP, NO gateway, NO DNS. It must bootstrap. The DORA exchange:

   Client --> DISCOVER (broadcast: "any DHCP server? I need config")     [dst ff:ff:ff:ff:ff:ff]
   Server --> OFFER    (here's an IP, mask, gateway, DNS, lease time)
   Client --> REQUEST  (broadcast: "I accept THIS offer" — names the chosen server)
   Server --> ACK      (confirmed; the lease is yours)

   Now the client has: IP, subnet mask, DEFAULT GATEWAY, DNS SERVER(S), lease duration.
                                            ^^^^^^^^^^^^^^^^  ^^^^^^^^^^^
                                            whoever set these controls the victim's traffic & names.
```

Three ideas:

1. **DHCP bootstraps the client's entire network trust.** The gateway (where all off-subnet traffic
   goes — Chapter 12) and the DNS server (how all names resolve — Chapter 16) come from DHCP. Control
   them and you control the victim.
2. **It is unauthenticated and first-answer-wins.** The client cannot verify the server; a rogue server
   that answers first (or that the client accepts) supplies the config. This is trust-on-first-use with no
   verification — the ARP/NDP pattern (Chapters 9, 11).
3. **It is broadcast-based and L2-local.** DISCOVER is a broadcast (Chapter 8), so DHCP operates within a
   broadcast domain (a router relays it to a central server via a DHCP relay/helper if the server is
   elsewhere). The attack is thus bounded to the broadcast domain — its blast radius, like ARP.

**The security framing:** DHCP is the *bootstrapping* trust problem — before a host has any identity or
config, it must trust something to give it one, unauthenticated. Rogue DHCP exploits this to become the
victim's gateway and DNS (a MITM broader than ARP spoofing, since it also controls DNS from the start).
The defense is to make the network only trust *legitimate* DHCP servers (DHCP snooping), and the cloud
solves it by providing DHCP as a trusted managed service.

---

## 4. Fundamentals

### 4.1 The DORA exchange in detail

DHCP's four-message exchange (**D**iscover, **O**ffer, **R**equest, **A**ck):

```
   1. DISCOVER  (client -> broadcast 255.255.255.255, from 0.0.0.0)
        "I have no address. Any DHCP servers out there? Here's my MAC."
   2. OFFER     (server -> the client)
        "I offer you 10.0.1.50, mask /24, gateway 10.0.1.1, DNS 10.0.1.2, lease 24h."
   3. REQUEST   (client -> broadcast, naming the chosen server)
        "I accept the offer from server X for 10.0.1.50." (broadcast so other servers know it's taken)
   4. ACK       (server -> client)
        "Confirmed. 10.0.1.50 is yours for 24 hours."
```

Why broadcast for DISCOVER and REQUEST: the client has no IP yet (so it uses source `0.0.0.0` and
destination broadcast), and it does not know where the server is. The REQUEST is broadcast so that *other*
DHCP servers that made offers know the client chose someone else and can reclaim their offered addresses.

The client also renews the lease before it expires (unicast REQUEST to the server at ~50% of lease time),
and can RELEASE an address it no longer needs. A NAK tells a client its requested address is invalid
(e.g. it moved networks).

### 4.2 What DHCP hands out (the "options")

Beyond the IP and mask, DHCP delivers **options** — configuration parameters, each security-relevant:

| Option | What it sets | Security relevance |
|---|---|---|
| IP address + mask | the client's address (Chapter 10) | basic |
| **Router (gateway)** | the default gateway (Chapter 12) | **controls where off-subnet traffic goes — MITM target** |
| **DNS servers** | name resolution (Chapter 16) | **controls how names resolve — DNS-spoofing/MITM target** |
| Domain name / search | DNS suffix | can influence name resolution |
| Lease time | how long the address is valid | affects logging/attribution windows |
| NTP servers | time source | wrong time breaks TLS cert validation, logs, tokens |
| **Option 121 (classless static routes)** | additional routes | **can inject routes to redirect specific traffic — a subtle MITM (see the "TunnelVision" class of attack)** |
| WPAD / proxy auto-config | HTTP proxy | **can route all web traffic through an attacker's proxy** |
| TFTP/boot server | network boot source | can serve malicious boot images (PXE attacks) |

The two most dangerous to control are the **gateway** and **DNS servers** — set these to attacker-owned
values and you MITM the victim entirely. But note the subtler ones: **Option 121 static routes** can
inject routes that override the client's routing (including, in some 2024-era attacks, routing VPN
traffic outside the tunnel), and **WPAD/proxy** options can silently route all web traffic through an
attacker proxy. A rogue DHCP server's power is exactly the sum of the options it can set.

### 4.3 DHCP relay (for centralized servers)

Since DISCOVER is a broadcast and broadcasts do not cross routers (Chapter 8 §4.5, Chapter 12), a DHCP
server in a different subnet cannot hear it directly. A **DHCP relay agent** (IP helper) on the router
forwards DHCP messages between the client's subnet and a central DHCP server, converting the broadcast to
a unicast to the server. This is how one central DHCP server serves many subnets. Security relevance: the
relay is a trusted intermediary, and DHCP snooping (§4.5) must be configured with awareness of relay
topology (the relay/server ports are "trusted," client ports are "untrusted").

### 4.4 DHCP attacks

**1. Rogue DHCP server (the MITM):**

```
   Attacker runs a DHCP server on the segment. When a client broadcasts DISCOVER, the rogue server
   answers (fastest, or the client accepts it) with:
     gateway = attacker's IP,  DNS = attacker's IP  (and/or malicious Option 121 routes / WPAD).
   -> The victim now sends all off-subnet traffic to the attacker (gateway) and resolves all names
      via the attacker (DNS). Full MITM, from the moment the client gets on the network — broader than
      ARP spoofing because it controls DNS and routing from the start.
```

Rogue DHCP is often *easier and stealthier* than ARP spoofing: it does not require continuous packet
injection (the lease persists), it controls DNS and routing natively, and a client that just joined the
network accepts it as normal configuration. It can be a malicious device, a compromised host, or even an
*accidental* rogue (a misconfigured home router plugged into a corporate network — a classic accidental
outage/exposure).

**2. DHCP starvation (DoS + setup for rogue):**

```
   Attacker floods DISCOVER messages with many spoofed MAC addresses, requesting addresses until the
   DHCP server's pool is EXHAUSTED. Legitimate clients then cannot get addresses (DoS).
   Often combined with a rogue server: starve the real server, then the attacker's rogue server is the
   only one answering.  Tool: dhcpstarv, Yersinia.
```

**3. Option-based attacks:** even a "legitimate-looking" rogue can push malicious **Option 121 routes**
(redirect specific traffic, including bypassing VPNs — the "TunnelVision" attack class) or **WPAD/proxy**
settings (route web traffic through an attacker proxy) or bad **NTP** (break TLS validation by skewing
time). These are subtler than gateway/DNS hijack but equally effective for specific goals.

All of these exploit the same root: **DHCP is unauthenticated bootstrapping, and the client trusts the
configuration it receives.** The mechanism is sound for a cooperative network; the trust is the
vulnerability in a hostile one — the recurring pattern (Chapters 5, 9, 11).

### 4.5 DHCP snooping (the primary defense)

**DHCP snooping** is a switch feature that makes the network trust only legitimate DHCP servers:

```
   The switch classifies ports as TRUSTED or UNTRUSTED:
     - TRUSTED ports (toward the real DHCP server / relay / uplink): DHCP server messages (OFFER/ACK) allowed.
     - UNTRUSTED ports (toward clients): DHCP server messages (OFFER/ACK) DROPPED.
   -> A rogue DHCP server on a client (untrusted) port cannot send OFFERs; its offers are dropped.

   As a bonus, snooping builds a BINDING TABLE: {MAC, IP, port, VLAN, lease} for each legitimate lease.
   This table is what DYNAMIC ARP INSPECTION (Chapter 9 §11) and IP Source Guard validate against.
```

So DHCP snooping does two jobs: (1) blocks rogue DHCP servers by dropping server messages on client
ports, and (2) builds the IP↔MAC↔port binding table that **DAI** (ARP defense, Chapter 9) and **IP Source
Guard** (anti-IP-spoofing) rely on. This is why Chapter 9 said DAI "depends on DHCP snooping" — the
binding table comes from here. DHCP snooping is thus a keystone L2 defense: it stops rogue DHCP *and*
enables the anti-spoofing controls.

Complementary: **port security** (Chapter 8) limits MACs per port, hindering DHCP starvation (which uses
many spoofed MACs).

### 4.6 DHCP in the cloud

In a VPC, AWS provides DHCP as a **managed, trusted service** — instances get their IP, gateway, and DNS
automatically, and you configure the DNS (and optionally domain name, NTP) via a **DHCP option set**:

```
   AWS DHCP option set controls:
     - domain-name-servers   (default: AmazonProvidedDNS at the VPC+2 address; or your own resolvers)
     - domain-name, ntp-servers, netbios settings

   You do NOT run a DHCP server; the SDN answers. There is NO rogue-DHCP attack in a VPC:
     a compromised instance cannot answer DHCP for others -- the fabric owns DHCP, like it owns ARP.
```

Consequences:

- **Rogue DHCP does not work in a VPC** — the SDN provides DHCP authoritatively; a compromised instance
  cannot become a DHCP server for its neighbors. Another L2/bootstrapping attack removed by the cloud
  (joining ARP spoofing, MAC flooding — Chapters 8, 9).
- **But you configure the DNS servers** in the option set. Setting them to a compromised or
  attacker-controlled resolver would MITM name resolution VPC-wide — so the DHCP option set (specifically
  its DNS servers) is a security-relevant configuration you own. Best practice: use AmazonProvidedDNS or
  your own controlled, logged resolvers (Chapter 17).
- **Attribution** in the cloud uses VPC Flow Logs and the known ENI/IP assignments rather than DHCP
  leases, but the concept — mapping addresses to instances over time — is the same.

The recurring lesson, now for DHCP: **the cloud removes the rogue-DHCP attack by owning DHCP, but you own
the configuration (DNS servers) it hands out, which is itself security-relevant.** Concepts persist,
attacks move, configuration responsibility remains yours (Chapter 6 §5.2).

---

## 5. Deep Technical Explanation: DHCP as the Bootstrapping Trust Problem

DHCP is the clearest example in networking of the **bootstrapping trust problem**: a system with *no*
prior configuration or credentials must obtain them from *somewhere*, and it has no way to verify that
somewhere. This problem recurs throughout security, and DHCP is a good place to name it:

- **The host has no identity, no config, no trust anchor.** It cannot validate a DHCP server's identity
  because it has nothing to validate against — no keys, no known-good address (it does not even have an
  address yet).
- **So it must trust the first plausible answer.** This is trust-on-first-use (TOFU) with no
  verification, the weakest form.

The same bootstrapping problem appears elsewhere, and DHCP teaches the general shape:

- **ARP/NDP** (Chapters 9, 11): trust the first neighbor answer — same TOFU, at Layer 2/3.
- **SSH first-connect** (Chapter 30): you trust the host key on first connection (TOFU), then pin it —
  a *managed* TOFU that at least detects later changes.
- **TLS/PKI** (Chapters 27–28): solves bootstrapping with a *pre-installed trust anchor* (the CA
  certificates shipped with the OS/browser), so the client *can* verify — the mature solution.
- **Cloud instance identity** (Chapters 67, 78): an instance bootstraps its identity from the metadata
  service / instance identity document, anchored in the hypervisor — a trusted local anchor.

The lesson: **bootstrapping trust requires either a pre-installed trust anchor (the strong solution, as
in PKI) or trust-on-first-use (the weak solution, as in DHCP/ARP), and TOFU is exploitable by whoever
answers first.** DHCP uses TOFU with no anchor, so it is exploitable (rogue DHCP); the defenses (DHCP
snooping, cloud managed DHCP) work by making the *network* only relay trusted answers, effectively
providing the anchor at the infrastructure level rather than the client. When you evaluate any
bootstrapping mechanism, ask: *is there a trust anchor, or is it TOFU, and if TOFU, what stops a rogue
from answering first?* This framing generalizes far beyond DHCP.

DHCP also authenticates the *result*, not the *server*, in secured deployments: **DHCP snooping's binding
table becomes a trust anchor for later decisions** (DAI validates ARP against it, IP Source Guard
validates source IPs against it). So the network bootstraps a trusted mapping from DHCP and then enforces
it — turning an unauthenticated exchange into a source of ground truth for other controls. That pattern —
*bootstrap a binding, then enforce everything against it* — is worth recognizing; it is how the network
turns weak TOFU into a usable trust foundation.

---

## 6. Internals: Observing DHCP

### 6.1 Watch the DORA exchange

```bash
# Trigger a DHCP renewal and capture it:
$ sudo dhclient -r eth0 && sudo dhclient -v eth0        # release then request (verbose)
$ sudo tcpdump -n -i eth0 'port 67 or port 68' -v      # DHCP: server=67, client=68
# You'll see: DISCOVER (0.0.0.0 -> 255.255.255.255), OFFER, REQUEST, ACK
```

Ports to know: **UDP 67 (server), UDP 68 (client)**. The DISCOVER shows source `0.0.0.0` (no address
yet) to destination `255.255.255.255` (broadcast). Reading the OFFER/ACK reveals the options handed out —
gateway, DNS, lease — the exact values an attacker would forge.

### 6.2 Inspect your lease

```bash
$ cat /var/lib/dhcp/dhclient.leases 2>/dev/null || cat /var/lib/NetworkManager/*.lease* 2>/dev/null
lease {
  interface "eth0";
  fixed-address 10.0.1.50;
  option routers 10.0.1.1;                 # the gateway DHCP gave you
  option domain-name-servers 10.0.1.2;     # the DNS server DHCP gave you
  option dhcp-server-identifier 10.0.1.2;  # WHICH server gave you this (check it's legit!)
  ...
}
```

The `dhcp-server-identifier` tells you *which* server configured you — a rogue-DHCP detection point (is
it the expected server?). The `routers` and `domain-name-servers` are the MITM-relevant values.

### 6.3 Detect a rogue DHCP server

```bash
# Actively probe for DHCP servers on the segment (are there more than expected?):
$ sudo nmap --script broadcast-dhcp-discover
# Look for MULTIPLE servers responding, or a server that is not the sanctioned one.

# Passive: watch for OFFERs from unexpected sources:
$ sudo tcpdump -n -i eth0 'udp port 67' | grep -i offer
```

Multiple DHCP servers answering, or a `dhcp-server-identifier` that is not the sanctioned server, is the
rogue-DHCP signature. On managed switches, DHCP snooping logs violations directly.

### 6.4 The cloud DHCP option set

```bash
$ aws ec2 describe-dhcp-options --query \
  'DhcpOptions[].DhcpConfigurations[?Key==`domain-name-servers`]'
# Verify the DNS servers are AmazonProvidedDNS or your controlled resolvers -- not something unexpected.
```

In the cloud you audit the option set (especially DNS servers) rather than hunting rogue servers, since
the SDN prevents rogues.

---

## 7. Real-World Example: DHCP in the Ledger Environments

**On-prem / corporate context (where DHCP attacks are real):** the corporate network Ledger's developers
use runs DHCP for user devices. The risks and defenses:

- **Rogue DHCP** — a malicious or compromised device (or an accidentally-plugged-in home router) could
  answer DHCP, handing users a malicious gateway/DNS and MITM'ing them (§4.4). Defense: **DHCP snooping**
  on the switches (trusted ports only toward the real DHCP server), which also builds the binding table
  for **DAI** (the ARP defense, Chapter 9) and IP Source Guard — one feature, three protections.
- **The user devices' DNS comes from DHCP**, so controlling DHCP means controlling DNS, which means
  phishing/credential theft via redirected name resolution (Chapter 17). This is why DHCP + DNS integrity
  is a combined concern.
- **Management/server networks** should use **static addressing or reservations** and be segmented
  (Chapter 13), reducing DHCP exposure for critical systems.

**System B (AWS):** Ledger's instances get DHCP from the VPC's managed service via a DHCP option set:

- **No rogue DHCP is possible** inside the VPC — the SDN owns DHCP. A compromised ECS task cannot become
  a DHCP server for other instances. This removes the on-prem rogue-DHCP concern entirely.
- **The DHCP option set's DNS servers** are Ledger's responsibility. Using AmazonProvidedDNS (with Route
  53 Resolver query logging — Chapter 17) or Ledger's own controlled, logged resolvers is the secure
  choice; pointing them at an untrusted resolver would MITM all VPC name resolution. So the option set
  (DNS specifically) is the security-relevant configuration to audit.
- **Attribution** uses VPC Flow Logs and ENI/IP records rather than DHCP leases.

The Ledger takeaway: **DHCP is a real MITM surface on-prem (defended by DHCP snooping, which also
underpins DAI), and in the cloud it becomes a managed service where the attack is gone but the DNS
configuration remains yours to get right.** This is the third L2/bootstrapping attack (after ARP and MAC
flooding) that the cloud removes — with the consistent caveat that the configuration responsibility
persists.

---

## 8. Hands-On Demonstration

### LAB 15.1 — DHCP, Rogue Servers, and Snooping-Style Defense

**Objective.** Observe the DORA exchange, run a rogue DHCP server in an isolated network to demonstrate
gateway/DNS hijacking, and reason about the DHCP-snooping defense and the cloud's managed DHCP.

**Cost.** Free. **Environment.** ENV-2 (isolated Docker network only — never on a network you do not
own). **Time.** 45–60 minutes.

**Ethics note.** Rogue DHCP is demonstrated only on an isolated bridge you control. Running a DHCP server
on a network you do not own is disruptive and illegal.

**Steps.**

*Step 1 — Build an isolated segment with a legitimate DHCP server.*

```bash
docker network create --internal dhcplab --subnet 10.70.0.0/24
# Legitimate DHCP server:
docker run -d --name dhcpd --network dhcplab --cap-add NET_ADMIN nicolaka/netshoot sh -c '
  apk add --no-cache dnsmasq 2>/dev/null || true
  dnsmasq -d --interface=eth0 --dhcp-range=10.70.0.100,10.70.0.150,1h \
    --dhcp-option=3,10.70.0.1 --dhcp-option=6,10.70.0.53 --no-daemon'
```

*Step 2 — Observe a client getting a lease (DORA).*

```bash
docker run -d --name victim --network dhcplab --cap-add NET_ADMIN nicolaka/netshoot sleep 3600
docker exec -d victim tcpdump -n -i eth0 'port 67 or port 68' -w /tmp/dora.pcap
docker exec victim sh -c 'udhcpc -i eth0 -q 2>&1 | tail; ip route; cat /etc/resolv.conf'
docker exec victim tcpdump -n -r /tmp/dora.pcap 2>/dev/null | grep -iE 'discover|offer|request|ack'
```

**Expected:** the victim receives an IP in 10.70.0.100–150, a gateway of 10.70.0.1, and DNS 10.70.0.53 —
the legitimate config. The capture shows DISCOVER/OFFER/REQUEST/ACK.

*Step 3 — Introduce a rogue DHCP server (faster / malicious options).*

```bash
docker run -d --name rogue --network dhcplab --cap-add NET_ADMIN nicolaka/netshoot sh -c '
  apk add --no-cache dnsmasq 2>/dev/null || true
  # Rogue: hand out the ATTACKER as gateway AND DNS:
  dnsmasq -d --interface=eth0 --dhcp-range=10.70.0.200,10.70.0.250,1h \
    --dhcp-option=3,10.70.0.66 --dhcp-option=6,10.70.0.66 --dhcp-authoritative --no-daemon'
# Force the victim to re-request; it may accept the rogue's offer:
docker exec victim sh -c 'udhcpc -i eth0 -q 2>&1 | tail; echo "---"; ip route; cat /etc/resolv.conf'
```

**Expected (may require a few attempts, as it is a race):** the victim may receive a gateway/DNS of
10.70.0.66 — the attacker. If so, all its off-subnet traffic and DNS now go through the attacker. **This
is the rogue-DHCP MITM.**

*Step 4 — Reason about the defense.*

DHCP snooping would designate the `dhcpd` port trusted and the `rogue`/`victim` ports untrusted, dropping
the rogue's OFFER/ACK on the untrusted port — the rogue could never hand out config. Write out how
snooping classifies ports and how its binding table also feeds DAI (Chapter 9). Then note that in an AWS
VPC, the rogue server could not answer at all (the SDN owns DHCP).

**Security implications.** Write down: (a) how one rogue server hijacked gateway *and* DNS (broader than
ARP spoofing); (b) why DHCP snooping (trusted vs untrusted ports) stops it; (c) that snooping's binding
table underpins DAI/IP Source Guard; (d) that the cloud removes rogue DHCP but leaves the DNS-servers
option as your responsibility.

**Cleanup.**
```bash
docker rm -f dhcpd rogue victim; docker network rm dhcplab
```

---

## 9. Security Implications

- **DHCP bootstraps a host's entire network trust** (IP, gateway, DNS) via an **unauthenticated,
  first-answer-wins** exchange — the bootstrapping trust problem in its purest form.
- **Controlling DHCP = controlling the victim's gateway and DNS = a full MITM**, often stealthier and
  broader than ARP spoofing (persists via the lease, controls DNS/routing from the start). Subtler
  option-based variants (Option 121 static routes — including VPN bypass; WPAD/proxy; bad NTP) extend the
  attacker's reach.
- **DHCP starvation** exhausts the address pool (DoS) and sets up rogue servers as the only responders.
- **DHCP snooping is the primary defense** (trusted vs untrusted ports drop rogue server messages) **and
  the foundation of Dynamic ARP Inspection and IP Source Guard** (its binding table is their trust
  anchor) — one keystone L2 feature protecting against rogue DHCP, ARP spoofing, and IP spoofing.
- **The bootstrapping pattern generalizes**: trust anchors (PKI) are strong; trust-on-first-use (DHCP,
  ARP) is weak and exploitable by whoever answers first.
- **The cloud removes rogue DHCP** (managed, SDN-owned) but leaves the **DHCP option set's DNS servers**
  as your security-relevant configuration.

---

## 10. Attack Scenarios

1. **Rogue DHCP MITM** (§4.4): an attacker's DHCP server hands victims a malicious gateway and DNS,
   MITM'ing all their traffic and name resolution from the moment they join — a full, stealthy MITM.
2. **Accidental rogue DHCP:** a misconfigured home router/AP plugged into a corporate network answers
   DHCP, causing outages and unintended routing — a common real incident. Defense: DHCP snooping.
3. **DHCP starvation DoS** (§4.4): flooding spoofed-MAC DISCOVERs to exhaust the pool, denying legitimate
   clients addresses; often paired with a rogue server.
4. **Option 121 route injection ("TunnelVision"-class):** a rogue/compromised DHCP pushes classless
   static routes that override the client's routing — notably routing VPN-destined traffic *outside* the
   tunnel, defeating a VPN's confidentiality without breaking the tunnel visibly.
5. **WPAD/proxy hijack:** DHCP (or DNS) supplies a malicious proxy-autoconfig, routing all the victim's
   web traffic through an attacker proxy.
6. **NTP manipulation:** a bad NTP server skews the client's clock, breaking TLS certificate validation
   (expired/not-yet-valid errors) or token/log integrity.
7. **PXE/boot attacks:** a rogue DHCP + TFTP serves a malicious boot image to network-booting hosts.

All are largely **infeasible inside a VPC** (managed DHCP), but very real on-prem/hybrid and on
guest/shared networks.

---

## 11. Defensive Techniques

**On-prem / traditional networks:**

- **DHCP snooping** — the primary control: classify ports trusted (toward the real DHCP server/relay/
  uplink) vs untrusted (clients), dropping DHCP server messages (OFFER/ACK) on untrusted ports so rogue
  servers cannot configure clients. Also builds the binding table for DAI and IP Source Guard.
- **Dynamic ARP Inspection + IP Source Guard** (Chapter 9) — layered on the snooping binding table to
  stop ARP spoofing and IP spoofing; deploy them together as a set.
- **Port security** (Chapter 8) — limits MACs per port, hindering DHCP starvation.
- **Static addressing / DHCP reservations for critical systems** (servers, management) — reduce DHCP
  exposure for high-value hosts; segment them (Chapter 13).
- **Segment and separate management** — smaller broadcast domains bound the rogue-DHCP blast radius; keep
  DHCP off untrusted/guest segments or run isolated DHCP per segment.
- **Monitor for rogue DHCP** — snooping violation logs, periodic `broadcast-dhcp-discover` scans, and
  alerting on multiple/unexpected DHCP servers.
- **Rate-limit DHCP** on untrusted ports to blunt starvation.

**Cloud:**

- **Rely on managed DHCP** — no rogue-DHCP risk in a VPC. **Audit the DHCP option set**, especially the
  **DNS servers** (AmazonProvidedDNS or your controlled, logged resolvers — Chapter 17); do not point
  them at untrusted resolvers.
- **Use Route 53 Resolver query logging** for DNS visibility (the cloud analogue of watching what DHCP's
  DNS server does).

**Everywhere:**

- **Encrypt and authenticate endpoints (TLS/mTLS)** — as with ARP/routing, a DHCP-based MITM is
  neutralized for confidentiality/integrity by end-to-end crypto, and **HSTS + validated DNS (DNSSEC/DoH)**
  reduce the DNS-hijack impact. The bootstrapping MITM cannot read ciphertext or forge a valid cert
  (Chapters 9, 12, 28) — the load-bearing control regardless of environment.

---

## 12. Production Architecture

DHCP's place and defenses, on-prem vs cloud:

```
 CONCEPT                  ON-PREM                          CLOUD (VPC)
 ----------------------   ------------------------------   -----------------------------------
 DHCP service             your DHCP server(s) + relay      AWS managed (SDN) via DHCP option set
 rogue-DHCP defense       DHCP snooping (trusted ports)    (not applicable — SDN owns DHCP)
 binding table feeds      DAI + IP Source Guard (Ch.9)     (SDN handles ARP/IP anti-spoof natively)
 DNS handed to clients    from your DHCP server            from the DHCP option set (YOU configure)
 critical systems         static/reservations + segment    fixed ENIs; option set for DNS
 attribution              DHCP leases                      VPC Flow Logs + ENI/IP records
 load-bearing control     TLS/mTLS + validated DNS         TLS/mTLS + validated DNS (same)
```

The architectural principle, consistent with Chapters 8–14: **the cloud removes another L2/bootstrapping
attack (rogue DHCP) by owning the mechanism, but the configuration it hands out (DNS servers) remains
your responsibility, and the load-bearing control against any bootstrapping MITM is end-to-end
encryption plus validated DNS.** On-prem, DHCP snooping is the keystone that stops rogue DHCP and enables
the ARP/IP anti-spoofing controls — deploy snooping + DAI + IP Source Guard as a coordinated set. In the
cloud, the equivalent protections are built into the fabric, and your job shifts to auditing the DHCP
option set (DNS) and enabling DNS query logging. Everywhere, do not trust the bootstrapped network config
to be honest — encrypt and validate.

---

## 13. Common Mistakes

1. **No DHCP snooping** on switched networks — leaving rogue DHCP (and, transitively, DAI/IP Source Guard)
   unavailable.
2. **DAI/IP Source Guard without DHCP snooping** — they depend on the snooping binding table; snooping
   must come first.
3. **Trusting DHCP-provided config as honest** — a rogue DHCP controls gateway *and* DNS; do not build
   security on the assumption that the network config is legitimate. Encrypt and validate DNS.
4. **Ignoring option-based attacks** (Option 121 routes, WPAD, NTP) — gateway/DNS are not the only
   dangerous options.
5. **Running critical systems on DHCP without reservations/segmentation** — increasing their MITM/DoS
   exposure.
6. **Not monitoring for rogue/accidental DHCP servers** — accidental rogues (home routers) cause outages;
   malicious ones cause MITM.
7. **Cloud: pointing the DHCP option set's DNS at an untrusted resolver** — MITM'ing all VPC name
   resolution; use AmazonProvidedDNS/controlled resolvers with logging.
8. **Assuming SLAAC/IPv6 hosts appear in DHCP leases** for attribution — they do not (Chapter 11).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Client gets an unexpected gateway/DNS | rogue (or accidental) DHCP server answered | check `dhcp-server-identifier` in the lease; `nmap --script broadcast-dhcp-discover`; snooping logs |
| Clients can't get addresses | DHCP starvation, pool exhaustion, or server down | check pool utilization; look for DISCOVER floods; `tcpdump port 67` |
| Intermittent wrong config on new joins | race between legitimate and rogue DHCP | multiple OFFERs in capture; deploy DHCP snooping |
| VPN traffic leaking outside the tunnel | Option 121 static-route injection (TunnelVision-class) | inspect client routes after DHCP (`ip route`); untrusted network |
| All web traffic through an unknown proxy | malicious WPAD/proxy DHCP/DNS option | check proxy autoconfig settings; DHCP options |
| TLS cert "not yet valid/expired" errors network-wide | bad NTP from DHCP skewing clocks | check time sync source; DHCP NTP option |
| Cloud: unexpected DNS resolution VPC-wide | DHCP option set DNS misconfigured | `describe-dhcp-options`; verify DNS servers |

---

## 15. Practical Lab

Lab 15.1 is in §8. Register it in the lab index. Extension: in the lab, have the rogue DHCP additionally
push a malicious DNS server, then run a DNS-spoofing responder on the attacker (bridge to Chapter 17) to
complete the DHCP→DNS→phishing chain — demonstrating that controlling DHCP's DNS option yields full name-
resolution control, and that only validated DNS + TLS defeats it. (Isolated network only.)

---

## 16. Exercises

### Concept questions

**15.1** Explain the DORA exchange and why DISCOVER and REQUEST are broadcasts. What configuration does a
client receive, and which items are the most security-critical?

**15.2** Explain why DHCP is the "bootstrapping trust problem" and how it relates to ARP, SSH first-
connect, and TLS/PKI. Which use a trust anchor and which use TOFU?

**15.3** Describe the rogue DHCP attack and why it is often stealthier and broader than ARP spoofing.

**15.4** Explain DHCP snooping: how it stops rogue servers and how its binding table enables DAI and IP
Source Guard.

**15.5** What are Option 121 and WPAD attacks, and why are gateway/DNS not the only dangerous DHCP
options?

### Debugging problems

**15.6** New devices on a segment intermittently get a gateway/DNS pointing at an unexpected IP. Diagnose
and give the fix.

**15.7** After enabling DAI, some hosts lose connectivity, and you recall DAI depends on DHCP snooping.
What is likely wrong and how do you fix it (relate to Chapter 9)?

**15.8** VPN users report that some traffic bypasses the VPN on one particular untrusted network.
Diagnose using DHCP options.

### Security scenarios

**15.9** You are securing a corporate LAN against MITM at Layer 2/3. Describe the coordinated set of DHCP/
ARP/IP defenses and why they must be deployed together, plus the load-bearing control that works
regardless.

**15.10** A team migrating to AWS asks whether they still need to worry about rogue DHCP. Answer
precisely, and identify what DHCP-related configuration remains their responsibility.

### Architecture questions

**15.11** Design the network-bootstrapping security for a mixed environment (corporate LAN + AWS VPC +
guest Wi-Fi), specifying DHCP handling and defenses in each zone.

**15.12** Explain the general "bootstrap a binding, then enforce against it" pattern using DHCP snooping →
DAI/IP Source Guard, and give one analogous pattern elsewhere in the book.

### Hands-on exercises

**15.13** Capture and identify each DORA message and the options (gateway, DNS, lease) in an OFFER/ACK.

**15.14** In an isolated lab, demonstrate a rogue DHCP server hijacking gateway/DNS, then explain the
snooping configuration that would prevent it.

**15.15** Audit an AWS DHCP option set and verify the DNS servers are trusted/controlled; describe what a
malicious change would do.

### Interview questions

**15.16** "Walk me through how a host gets its network configuration and what an attacker can do with
that process."

**15.17** "What is rogue DHCP, and how do you defend against it?"

**15.18** "How does DHCP snooping relate to Dynamic ARP Inspection?"

**15.19** "Does rogue DHCP work in a cloud VPC? What DHCP-related risk remains?"

**15.20** "Explain the bootstrapping trust problem using DHCP, and how PKI solves the general version."

---

## 17. Summary

- **DHCP bootstraps a host's network identity and trust** — IP, mask, **gateway**, and **DNS** — via the
  unauthenticated, first-answer-wins **DORA** exchange (Discover/Offer/Request/Ack) on UDP 67/68,
  broadcast within a broadcast domain (relayed to central servers by a DHCP relay).
- **Controlling DHCP = controlling the victim's gateway and DNS = a full MITM.** **Rogue DHCP** is often
  stealthier and broader than ARP spoofing; subtler option attacks (**Option 121** static routes incl.
  VPN bypass, **WPAD/proxy**, bad **NTP**) extend the attacker's reach. **DHCP starvation** exhausts the
  pool (DoS) and sets up rogues.
- **DHCP is the bootstrapping trust problem**: a host with no config must trust an unauthenticated answer
  (TOFU, no anchor) — the same shape as ARP/NDP, contrasted with PKI's pre-installed **trust anchor**
  (the strong solution) and SSH's managed TOFU.
- **DHCP snooping is the keystone defense**: trusted vs untrusted ports drop rogue server messages, *and*
  its binding table is the trust anchor for **Dynamic ARP Inspection** and **IP Source Guard** — deploy
  the three as a coordinated set. "Bootstrap a binding, then enforce against it."
- **The cloud removes rogue DHCP** (managed, SDN-owned — the third L2/bootstrapping attack the cloud
  eliminates, after MAC flooding and ARP spoofing), but the **DHCP option set's DNS servers** remain your
  security-relevant configuration to audit.
- **The load-bearing control against any bootstrapping MITM is end-to-end encryption (TLS/mTLS) plus
  validated DNS (DNSSEC/DoH) and HSTS** — do not trust the bootstrapped network config to be honest.

---

## 18. Knowledge Check

1. What are the four DORA messages, and which are broadcast and why? (§4.1)
2. Which two DHCP options are the primary MITM targets, and which two are subtler ones? (§4.2)
3. Why is DHCP the "bootstrapping trust problem," and how does PKI solve the general version? (§5)
4. How does DHCP snooping stop rogue DHCP, and what does its binding table also enable? (§4.5)
5. Why is rogue DHCP often stealthier/broader than ARP spoofing? (§4.4)
6. What is DHCP starvation and how does it combine with a rogue server? (§4.4)
7. What is the Option 121 / TunnelVision-class attack? (§4.4, §10)
8. Does rogue DHCP work in a VPC, and what DHCP config remains yours? (§4.6)
9. What ports does DHCP use, and what source/dest does DISCOVER have? (§6.1)
10. What is the load-bearing control against a DHCP MITM? (§11)

---

## 19. Further Exploration

- RFC 2131 (DHCP) — read the DORA state machine; short and clarifying.
- Capture a real DHCP exchange (Lab 15.1) and dissect the options in Wireshark's DHCP dissector (bridge
  to Chapter 24).
- Read about the **TunnelVision (CVE-2024-3661)** DHCP Option 121 VPN-bypass attack — a current, vivid
  example that gateway/DNS are not the only dangerous options.
- Cisco DHCP snooping + DAI + IP Source Guard configuration guides — the coordinated on-prem defense set
  you will recommend in hybrid environments.
- AWS DHCP option sets documentation — audit the DNS-servers configuration (§6.4) and pair with Route 53
  Resolver query logging (Chapter 17).
- Revisit Chapters 9 and 11: DHCP, ARP, and NDP are three faces of the same unauthenticated-bootstrapping
  problem, and DHCP snooping is what ties the L2 defenses together.

---

## Solutions

### 15.1
DORA is Discover → Offer → Request → Ack. **DISCOVER** is broadcast because the client has no IP (source
0.0.0.0) and does not know where any DHCP server is, so it must reach the whole segment
(255.255.255.255). A server replies with an **OFFER** (an IP, mask, gateway, DNS, lease). **REQUEST** is
broadcast because the client formally accepts one offer and broadcasts it so that *other* DHCP servers
that also offered know their offered addresses are declined and can reclaim them (and because the client
still may not have a usable unicast path). The server confirms with **ACK**. The client receives: IP
address and subnet mask, **default gateway (router)**, **DNS server(s)**, lease time, and optional
parameters (domain name, NTP, static routes, proxy). The most security-critical items are the **gateway**
(controls where off-subnet traffic goes) and the **DNS servers** (control how names resolve) — controlling
either MITMs the victim; subtler dangerous options include Option 121 static routes, WPAD/proxy, and NTP.

### 15.2
DHCP is the bootstrapping trust problem because a host booting with **no address, no configuration, and
no credentials** must obtain its network config from somewhere, yet it has nothing to verify that
somewhere against — no keys, no known-good server address, not even its own address — so it must trust the
first plausible answer (trust-on-first-use, TOFU, with no anchor). Relation to others: **ARP/NDP**
(Chapters 9, 11) are the same TOFU at Layer 2/3 (trust the first neighbor/router answer); **SSH
first-connect** (Chapter 30) is a *managed* TOFU — you trust the host key on first use but pin it and
detect later changes; **TLS/PKI** (Chapters 27–28) is the mature solution: it ships a **pre-installed
trust anchor** (the CA certificates in the OS/browser) so the client *can* cryptographically verify the
server and does not rely on TOFU. So DHCP, ARP, and NDP use weak TOFU with no anchor (exploitable by
whoever answers first); PKI uses a trust anchor (strong); SSH is TOFU-with-pinning (intermediate). The
general lesson: bootstrapping trust needs either a pre-installed anchor or TOFU, and TOFU without an
anchor is exploitable.

### 15.3
A rogue DHCP server answers clients' DISCOVER messages with configuration pointing the gateway and DNS
(and possibly Option 121 routes / WPAD) at the attacker, so the victim sends all off-subnet traffic to
the attacker and resolves all names via the attacker — a full MITM from the moment the client joins. It
is often stealthier and broader than ARP spoofing because: (1) it does **not require continuous packet
injection** — the lease persists, so there is no ongoing storm of forged packets to detect (ARP spoofing
must re-send constantly, which is noisy — Chapter 9); (2) it controls **DNS and routing natively** from
the start, not just one IP↔MAC mapping, so it captures name resolution too (enabling phishing) and can
inject arbitrary routes; (3) it looks like **normal configuration** to a client that just joined the
network, raising no suspicion; and (4) it can be an *accidental* rogue (a home router) that blends in.
So rogue DHCP is a more complete and quieter MITM primitive than ARP spoofing, defended by DHCP snooping
and neutralized (for confidentiality) by end-to-end encryption + validated DNS.

### 15.4
DHCP snooping is a switch feature that classifies ports as **trusted** (toward the legitimate DHCP
server, relay, or uplink) or **untrusted** (toward clients). It drops DHCP **server** messages (OFFER,
ACK) arriving on **untrusted** ports, so a rogue DHCP server plugged into a client port cannot hand out
configuration — its offers are discarded before reaching victims. That stops rogue DHCP. As a byproduct,
snooping records every legitimate lease it observes into a **binding table**: {MAC, IP, port, VLAN,
lease}. This binding table is the trust anchor that **Dynamic ARP Inspection (DAI)** uses to validate
ARP packets (dropping ARP whose IP↔MAC does not match a binding — Chapter 9) and that **IP Source Guard**
uses to validate source IP addresses on frames (dropping spoofed source IPs). So one feature — DHCP
snooping — both blocks rogue DHCP and provides the ground-truth bindings that make the ARP-spoofing and
IP-spoofing defenses possible, which is why DAI "depends on DHCP snooping" and why the three are deployed
as a coordinated set.

### 15.9
Deploy the L2/L3 anti-MITM controls as a coordinated set on the switches: (1) **DHCP snooping** —
trusted ports toward the real DHCP server/relay, untrusted toward clients, dropping rogue server
messages; this also builds the binding table. (2) **Dynamic ARP Inspection (DAI)** — validates ARP
against the snooping binding table, stopping ARP spoofing (Chapter 9). (3) **IP Source Guard** — validates
source IPs against the binding table, stopping IP spoofing. (4) **Port security** — limits MACs per port,
hindering DHCP starvation and MAC flooding (Chapter 8). They must be deployed together because DAI and IP
Source Guard **depend on the DHCP-snooping binding table** for their ground truth — without snooping they
have nothing to validate against — and because each closes a different MITM vector (rogue DHCP, ARP
spoofing, IP spoofing) that an attacker would otherwise pivot to. Add segmentation (Chapter 13) to bound
blast radius and separate management. The **load-bearing control that works regardless** of all the
above is **end-to-end encryption + authentication (TLS/mTLS) plus validated DNS (DNSSEC/DoH) and HSTS**:
even if an attacker achieves an on-path MITM despite the network controls, encrypted traffic is
unreadable and untamperable and the attacker cannot impersonate endpoints — so the network controls
reduce likelihood while encryption removes impact (the recurring Chapter 9/12 conclusion).

### 15.10
No, rogue DHCP does not work inside a VPC: AWS provides DHCP as a managed service via the SDN, so a
compromised instance cannot answer DHCP for other instances — the fabric owns DHCP the same way it owns
ARP (Chapters 8–9), and there is no shared medium on which a rogue server could race legitimate offers.
So the on-prem rogue-DHCP MITM concern is eliminated in a standard VPC. What remains their
responsibility: the **DHCP option set**, specifically the **domain-name-servers (DNS)** it hands to
instances. If they point the option set's DNS at an untrusted or compromised resolver, they would MITM
all VPC name resolution (a self-inflicted equivalent of the rogue-DHCP DNS hijack). Best practice: use
**AmazonProvidedDNS** (or their own controlled, logged resolvers) and enable **Route 53 Resolver query
logging** for visibility. Also note attribution shifts from DHCP leases to **VPC Flow Logs + ENI/IP
records**. And as always, encrypt internal traffic and validate DNS as defense in depth. Summary: the
attack is gone, but the DNS configuration of the option set is theirs to get right and audit.

### 15.16
A host with no configuration broadcasts a DHCP **DISCOVER** on the segment; a DHCP server responds with
an **OFFER** containing an IP address, subnet mask, default gateway, DNS servers, and a lease time; the
client **REQUEST**s the offered configuration (broadcast, naming the chosen server); the server **ACK**s,
and the client is now configured with its address, gateway, and DNS. The exchange is unauthenticated and
first-answer-wins. What an attacker can do: run a **rogue DHCP server** that answers with a
**malicious gateway and DNS** (and/or Option 121 static routes or a WPAD proxy), so from the moment the
victim joins the network, all its off-subnet traffic goes to the attacker (gateway) and all name
resolution goes through the attacker (DNS) — a complete, stealthy MITM that persists via the lease
(unlike noisy ARP spoofing). Variants include DHCP starvation (exhaust the pool, forcing clients onto the
rogue) and option abuse (route injection to bypass VPNs, proxy hijack, NTP skew to break TLS). Defenses:
DHCP snooping (trusted vs untrusted ports) to block rogue servers, DAI/IP Source Guard built on its
binding table, and — regardless of the network — end-to-end TLS + validated DNS so a MITM sees only
ciphertext and cannot forge certificates. In the cloud, managed DHCP removes the rogue-server attack, but
the option set's DNS remains a security-relevant setting.

### 15.20
The bootstrapping trust problem: a host booting with no address, no configuration, and no credentials
must obtain its network configuration from some source, but it has no way to verify that source's
identity — it has no keys, no trusted reference, not even its own address. DHCP illustrates this exactly:
the client broadcasts for configuration and must accept whatever a server offers, unauthenticated and
first-answer-wins (trust-on-first-use with no anchor). This is why rogue DHCP works — the client cannot
tell a legitimate server from an attacker's. PKI solves the *general* version by providing a
**pre-installed trust anchor**: the operating system and browsers ship with a set of trusted Certificate
Authority certificates, so when a client later connects to a server over TLS, it can cryptographically
verify the server's certificate chains up to one of those pre-trusted CAs (Chapters 27–28). The client no
longer has to trust the first answer — it can *verify* the answer against an anchor it already possessed
before the exchange, so an impostor without a validly-signed certificate is rejected. The general lesson:
secure bootstrapping requires a trust anchor established out-of-band (like CA certs baked into the OS);
DHCP lacks one and so relies on weak TOFU, which is why its defenses (DHCP snooping, cloud managed DHCP)
work by moving the trust decision into the *infrastructure* (only relay trusted servers' answers) rather
than the client, and why end-to-end TLS — which *does* have an anchor — is what ultimately protects the
traffic regardless of a DHCP MITM.

---

*Next: Chapter 16 — DNS Part 1: Resolution, Records, Delegation, Caching, and the Root. DHCP just handed
the client a DNS server; now we follow how a name becomes an address — the hierarchical, cached,
globally-distributed system that every connection depends on, and whose integrity failures (covered in
Chapter 17) are among the most impactful attacks in security.*
