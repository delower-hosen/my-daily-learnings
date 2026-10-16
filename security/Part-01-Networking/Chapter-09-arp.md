# Chapter 9 — ARP: The Glue Between Layer 2 and Layer 3, and How It Is Poisoned

---

## 1. Why This Matters

Chapter 8 ended on a cliffhanger: to send a frame, a host needs the *MAC address* of the next
hop, but it starts only with an *IP address*. ARP — the **Address Resolution Protocol** — is the
mechanism that bridges that gap, and it is the single most important "small" protocol for a
security engineer to understand, for one reason: **ARP has no authentication, and its abuse is the
canonical local-network man-in-the-middle.**

Almost every "attacker on the same network reads/modifies your traffic" scenario — the coffee-shop
Wi-Fi attack, the malicious insider on a corporate LAN, the compromised host pivoting laterally —
runs through ARP spoofing. It is how attackers turn "I am on the segment" into "I see and can alter
everyone's traffic." Understanding it precisely does three things for you:

1. It makes the abstract warning "don't trust the LAN" (Chapter 8 §9) concrete and undeniable —
   you will *see* how one forged packet redirects a victim's entire traffic.
2. It grounds the whole case for **encrypting internal traffic** and **Zero Trust** (Chapter 43):
   if ARP MITM is this easy, then confidentiality and integrity cannot come from the network.
3. It explains, by contrast, exactly *what the cloud SDN does for you* (Chapter 8 §7): AWS
   controls ARP so this attack does not work inside a VPC — and knowing the mechanism is knowing
   why.

ARP is also a superb teaching example of a recurring security theme: **a protocol designed for a
trusted environment, deployed in a hostile one, with trust built into its core.** ARP believes
whatever it is told. That design choice, reasonable in 1982, is a vulnerability class today —
exactly the pattern you saw with insecure defaults in Chapter 5, now at the protocol level.

---

## 2. Prerequisites

- Chapter 8 in full, especially §5 (the L2/L3 delivery flow and "dst MAC = next hop") and §3
  (broadcast domain, broadcast MAC).
- Chapter 7 (reading headers/hex).
- Chapter 4 §Stop 1–2 (DNS/routing context) — ARP is the step *below* routing.

---

## 3. Mental Model

**ARP answers one question: "I know this IP is on my local segment; what MAC do I send the frame
to?" It asks the whole segment by broadcast, and it believes the first answer it gets.**

```
   Host A wants to send to 10.0.1.9 (which it has determined is local — Chapter 8 §5).
   A has the IP. A needs the MAC.

   1. A broadcasts:  "Who has 10.0.1.9? Tell 10.0.1.5"       (ARP Request, to ff:ff:ff:ff:ff:ff)
   2. Everyone on the segment hears it. Only B should answer.
   3. B replies (unicast): "10.0.1.9 is at 0a:...:09"        (ARP Reply)
   4. A caches: 10.0.1.9 -> 0a:...:09, and sends the frame.
```

Three properties, each a security consequence:

- **ARP is unauthenticated.** Step 3's reply carries no proof. *Anyone* can send it, and A will
  believe it. There is no signature, no challenge, nothing.
- **ARP is stateless and gullible.** A host will often accept an ARP *reply* even without having
  sent a request (a "gratuitous ARP"), overwriting its cache. This is by design (to speed up
  updates when an IP moves) and is exactly what an attacker exploits.
- **ARP is local-only.** It never crosses a router (broadcasts don't — Chapter 8 §4.5), so the
  attack is bounded to the broadcast domain — which is also its blast radius.

**The attack in one sentence:** if an attacker sends A a forged ARP reply claiming "the gateway's
IP is at *my* MAC," then A sends all its off-segment traffic to the attacker — a man-in-the-middle
achieved with a single unauthenticated packet. That is the whole of ARP spoofing, and everything
below is detail.

---

## 4. Fundamentals

### 4.1 The ARP packet

ARP rides directly in an Ethernet frame with EtherType `0x0806` (Chapter 8 §4.2 — you decoded this
byte). The packet:

```
   Hardware type   (2 bytes) = 0x0001 (Ethernet)
   Protocol type   (2 bytes) = 0x0800 (IPv4)
   HW addr length  (1 byte)  = 6  (MAC is 6 bytes)
   Proto addr len  (1 byte)  = 4  (IPv4 is 4 bytes)
   Operation       (2 bytes) = 1 (request) or 2 (reply)
   Sender MAC      (6 bytes)   <-- the claim: "this MAC..."
   Sender IP       (4 bytes)   <-- "...owns this IP"
   Target MAC      (6 bytes)
   Target IP       (4 bytes)
```

The two fields that matter for the attack are **Sender MAC** and **Sender IP** in a *reply*: they
are an unverified assertion "IP X is at MAC Y," and the receiver caches it. An attacker sends a
reply with Sender IP = the gateway and Sender MAC = the attacker's, and the victim believes it.

### 4.2 The ARP cache

Every host keeps a cache of IP→MAC mappings to avoid ARPing for every packet:

```bash
$ ip neigh show
10.0.1.1  dev eth0 lladdr 0a:00:00:00:00:01 REACHABLE   # the gateway
10.0.1.9  dev eth0 lladdr 0a:1b:2c:3d:4e:09 STALE
```

States you will see: `REACHABLE` (recently confirmed), `STALE` (needs re-checking), `DELAY`/
`PROBE` (revalidating), `FAILED`, `PERMANENT` (static, set manually). Entries expire after a short
time (tens of seconds to minutes), which is why an attacker must *continuously* re-send forged
replies to keep the poison fresh — a detectable behavior (§6, §11).

### 4.3 Request, reply, gratuitous, and announcements

- **ARP request:** broadcast "who has IP X?" — normal resolution.
- **ARP reply:** unicast "IP X is at MAC Y" — the answer.
- **Gratuitous ARP (GARP):** an unsolicited reply/announcement a host sends about *its own* IP,
  used legitimately to (a) announce a new IP or MAC after failover, (b) detect duplicate IPs, and
  (c) update everyone's caches quickly. Because hosts accept GARP to update caches, it is *the*
  vehicle for poisoning — the attacker sends GARP claiming the victim's or gateway's IP.
- **ARP probe/announcement (RFC 5227):** used during address configuration to check for conflicts.

The legitimate uses of gratuitous ARP are exactly why the protocol accepts unsolicited replies,
and thus why the attack is possible — a recurring theme: **the feature and the vulnerability are
the same mechanism.** (Compare Redis `CONFIG` in Chapter 5, and NX→ROP in Chapter 1.)

### 4.4 ARP spoofing / poisoning

The attack, step by step, for a full bidirectional MITM between victim A and gateway G, run by
attacker M on the same segment:

```
   Goal: A <-> G traffic flows A <-> M <-> G, with M reading/altering it.

   1. M tells A:  "G's IP (10.0.1.1) is at M's MAC"      (forged ARP reply to A)
   2. M tells G:  "A's IP (10.0.1.5) is at M's MAC"      (forged ARP reply to G)
   3. Now:
        A sends off-segment traffic -> frame to "gateway" = M's MAC -> arrives at M
        G sends A's return traffic  -> frame to "A" = M's MAC       -> arrives at M
   4. M enables IP forwarding and relays each frame to the real destination,
        so connectivity looks normal to A and G (this is what makes it stealthy).
   5. M now sees (and can modify) ALL traffic between A and the internet.
   6. M re-sends the forged replies every few seconds to keep the poisoned entries fresh.
```

What M can do once in the middle:

- **Read plaintext** — any unencrypted traffic (HTTP, DNS, plaintext DB connections — Chapter 5).
- **Downgrade/strip TLS** — SSL stripping (rewrite `https://` links to `http://` on the way to A),
  defeated by HSTS (Chapter 4 §Stop 0, Chapter 28).
- **Tamper** — inject content, alter responses (again, defeated by TLS integrity if present).
- **Spoof DNS** — answer A's DNS queries with attacker IPs (Chapter 17), since M sees them.

The critical insight for your job: **ARP spoofing gives an attacker on-path position; TLS is what
makes that position useless.** A properly TLS-protected connection through an ARP-MITM shows the
attacker only ciphertext and refuses to connect if they present a bad certificate. This is the
concrete, mechanical justification for "encrypt everything, even internal" — the attacker is
*already in the middle*, and only cryptography saves you. Chapter 4 §Stop 4's "TLS protects
transit" is exactly this scenario.

---

## 5. Deep Technical Explanation: Why ARP Trusts, and What That Implies

ARP was designed in 1982 (RFC 826) for a small, trusted, cooperative Ethernet. Authentication was
not a consideration — there were no adversaries on the wire, and adding cryptography to every
address resolution would have been absurd overhead for the era. So ARP has three trust
assumptions baked in, each now a liability:

1. **"Any reply is truthful."** No verification that the sender owns the claimed IP. → spoofing.
2. **"Unsolicited replies are helpful."** Hosts accept GARP to update caches. → poisoning without
   even needing to race a request.
3. **"The segment is cooperative."** Everyone on the broadcast domain is trusted. → any host can
   attack any other.

These are not bugs; they are the design, and they cannot be patched away without changing the
protocol (which is why the defenses in §11 are *external* — DAI, static ARP, encryption — rather
than "fix ARP"). This is the archetype of a security lesson you will apply repeatedly:
**when a protocol's trust model does not match the deployment's threat model, you cannot fix it
from inside; you wrap it (encryption, monitoring) or replace the environment (the SDN).**

There is a deeper structural point worth internalizing. ARP is the *foundation* of local delivery
— everything above it (IP, TCP, TLS, HTTP) assumes the frame reached the right next hop. If ARP is
poisoned, the higher layers are built on a lie. But notice the *containment*: TLS at Layer 4/5 does
not care that Layer 2 was lied to, because TLS authenticates the *endpoint* cryptographically, not
the *path*. This is defense in depth across layers (Chapter 4 §5.1) in its purest form: a total
compromise of one layer (L2) is survived by a control at a higher layer (TLS), because the higher
control does not depend on the lower one's integrity. Designing systems so that a lower layer's
compromise is caught above is the whole game.

### 5.1 IPv6 has the same problem under a different name

IPv6 replaces ARP with **NDP (Neighbor Discovery Protocol)** using ICMPv6 (Chapter 11). NDP has
the identical trust problem — **Neighbor Advertisement spoofing** is the IPv6 equivalent of ARP
spoofing, and **rogue Router Advertisements** let an attacker become the default gateway (worse
than ARP, since RAs configure addressing too). The defense (RA Guard, ND Inspection, SEND) mirrors
the ARP defenses. Mention this now because dual-stack networks (Chapter 11) are common, and an
environment hardened against ARP spoofing but ignoring IPv6 NDP is fully exposed via IPv6 — a real
and frequent oversight.

---

## 6. Internals: Observing ARP and Detecting Poisoning

### 6.1 Watch ARP resolution happen

```bash
$ ip neigh flush all                          # clear the cache
$ ping -c1 10.0.1.9                           # forces an ARP resolution
$ sudo tcpdump -e -n -i eth0 arp -c 4
10:22:41 0a:...:05 > ff:ff:ff:ff:ff:ff, ARP, Request who-has 10.0.1.9 tell 10.0.1.5, length 28
10:22:41 0a:...:09 > 0a:...:05, ARP, Reply 10.0.1.9 is-at 0a:...:09, length 28
$ ip neigh show 10.0.1.9
10.0.1.9 dev eth0 lladdr 0a:1b:2c:3d:4e:09 REACHABLE
```

You just watched the request/reply exchange from §3 in real bytes. Note the request is broadcast,
the reply is unicast, and the cache updates.

### 6.2 Detect poisoning: the telltale signs

Poisoning produces observable anomalies, which is the basis of detection (§11):

```bash
# 1. The same MAC claiming multiple IPs (attacker impersonating several hosts):
$ ip neigh show | awk '{print $5}' | sort | uniq -c | sort -rn | head
      3 0a:MA:LI:CI:OU:S1     # one MAC mapped to 3 IPs -> suspicious

# 2. MAC "flapping" for an IP (real MAC and attacker MAC alternating):
$ ip monitor neigh                            # live: watch entries change
# repeated changes of lladdr for the same IP = poisoning in progress

# 3. Gratuitous ARP storms:
$ sudo tcpdump -n -i eth0 'arp[6:2] = 2'      # ARP replies only
# a flood of unsolicited replies for the gateway IP = active poisoning
```

The signatures — one MAC for many IPs, a MAC flapping for the gateway's IP, and continuous
unsolicited replies — are exactly what IDS rules and tools like `arpwatch` alert on. An attacker
*must* re-send replies to keep the poison fresh (§4.2), so the attack is inherently noisy and
detectable if you are watching.

### 6.3 Pin critical entries statically

```bash
# The gateway's MAC should never change; pin it:
$ sudo ip neigh replace 10.0.1.1 lladdr 0a:00:00:00:00:01 dev eth0 nud permanent
$ ip neigh show 10.0.1.1
10.0.1.1 dev eth0 lladdr 0a:00:00:00:00:01 PERMANENT
```

A `PERMANENT` entry ignores ARP replies for that IP, defeating gateway poisoning for that host.
Impractical at scale (which is why switch-level DAI exists — §11), but a valid hardening for a
small number of critical mappings on a sensitive host.

---

## 7. Real-World Example: ARP MITM in the Ledger Environments

**System A (VPS / on-prem-like):** if the Ledger VPS shares a broadcast domain with other hosts
(other tenants on a poorly-isolated provider, or other servers in a colo), an attacker on that
segment could ARP-spoof the gateway and MITM the VPS's traffic. What saves Ledger:

- **TLS on the Nginx front (Chapter 4 §Stop 4)** — external traffic is encrypted; the MITM sees
  ciphertext.
- **BUT the app→DB, app→Redis traffic** — if those were on the network (not loopback) and
  *unencrypted* (Chapter 5's default), an ARP-MITM on that segment would read database queries and
  results in plaintext. This is precisely why Chapter 5 insisted on TLS for internal hops once they
  leave loopback, and why the loopback binds of Chapter 3 §7 are protective (loopback traffic never
  hits the wire, so it cannot be ARP-MITM'd).

The scenario crystallizes a Part 0 lesson: loopback isolation and internal TLS are not paranoia;
they are the direct answer to "an attacker is already in the middle of my network."

**System B (AWS VPC):** ARP spoofing **does not work** (Chapter 8 §7). The Nitro SDN answers ARP
authoritatively and does not deliver traffic to a MAC/IP that does not legitimately own it; a
compromised instance sending forged ARP achieves nothing — the fabric ignores it. This removes the
entire ARP-MITM class inside a VPC. The correct statement in a review: "inside the VPC, an attacker
cannot ARP-spoof to intercept traffic; the fabric prevents it." What remains: you still encrypt
internal traffic (defense in depth, and because your threat model may include the fabric being
misconfigured, traffic mirroring, or non-VPC segments), and the risk has moved to the control
plane and IAM (Chapter 6 §4.4).

The teaching contrast is the whole point of putting ARP in a cloud-security book: **the same
attack that is trivial and devastating on a traditional LAN is architecturally impossible inside a
VPC, because the cloud owns Layer 2.** Knowing the mechanism lets you answer the co-tenant sniffing
question with authority instead of hand-waving.

---

## 8. Hands-On Demonstration

### LAB 9.1 — Observe ARP and Demonstrate Poisoning (in an isolated lab)

**Objective.** Watch normal ARP resolution, then demonstrate ARP poisoning between two containers
on an isolated bridge (systems you own), observe the traffic redirection, prove that TLS defeats
the resulting MITM, and finally show the detection signatures and the static-entry defense.

**Cost.** Free. **Environment.** ENV-2 (isolated Docker network only — never on a network you do
not own). **Time.** 60–90 minutes.

**Ethics note.** ARP poisoning is only performed here between containers on a private bridge you
control. Doing this on any other network is illegal and out of scope (Chapter 14 ground rules).

**Steps.**

*Step 1 — Build an isolated three-host segment.*

```bash
docker network create --driver bridge --subnet 172.31.0.0/24 arplab
docker run -d --name victim   --network arplab --cap-add NET_RAW nicolaka/netshoot sleep 3600
docker run -d --name gateway  --network arplab --cap-add NET_RAW nicolaka/netshoot sleep 3600
docker run -d --name attacker --network arplab --cap-add NET_ADMIN --cap-add NET_RAW nicolaka/netshoot sleep 3600
for c in victim gateway attacker; do echo -n "$c: "; docker exec $c ip -br addr show eth0; done
```

*Step 2 — Observe normal ARP.*

```bash
docker exec victim ip neigh flush all
docker exec victim ping -c1 $(docker exec gateway hostname -i)
docker exec victim ip neigh show          # note gateway's real MAC
docker exec -d victim tcpdump -e -n -i eth0 arp -w /tmp/arp.pcap
```

*Step 3 — Poison (attacker tells victim it is the gateway).*

```bash
GW_IP=$(docker exec gateway hostname -i)
VIC_IP=$(docker exec victim hostname -i)
# arpspoof from dsniff, or use scapy for clarity:
docker exec -d attacker sh -c "
  python3 - <<'PY'
from scapy.all import ARP, send
import time
gw='${GW_IP}'; vic='${VIC_IP}'
while True:
    send(ARP(op=2, pdst=vic, psrc=gw), verbose=0)   # tell victim: gateway is at MY mac
    send(ARP(op=2, pdst=gw, psrc=vic), verbose=0)   # tell gateway: victim is at MY mac
    time.sleep(2)
PY
"
sleep 5
docker exec victim ip neigh show ${GW_IP}     # gateway IP now maps to ATTACKER's MAC!
```

**Expected:** the victim's ARP entry for the gateway IP now shows the *attacker's* MAC. The
redirection is in place.

*Step 4 — Prove the MITM sees plaintext, and TLS defeats it.*

```bash
# Attacker enables forwarding and sniffs:
docker exec attacker sysctl -w net.ipv4.ip_forward=1
docker exec -d attacker tcpdump -A -n -i eth0 -w /tmp/mitm.pcap
# Victim makes a PLAINTEXT request through the "gateway":
docker exec gateway sh -c 'nc -l -p 8080 -e /bin/echo "SECRET-DATA" &'   # toy service
docker exec victim sh -c "echo hello | nc ${GW_IP} 8080"
# Inspect what the attacker captured -> plaintext visible
docker exec attacker sh -c 'tcpdump -A -n -r /tmp/mitm.pcap 2>/dev/null | grep -i secret || echo "(inspect capture)"'
```

**Expected:** the attacker's capture contains the plaintext exchange. Now reason: had the service
used TLS, the attacker would see only ciphertext and could not have downgraded it if the client
enforced certificate validation. **This is the mechanical proof that TLS defeats an on-path
attacker.**

*Step 5 — Detection signatures.*

```bash
docker exec victim sh -c 'ip neigh show | awk "{print \$5}" | sort | uniq -c | sort -rn'
# the attacker's MAC appears for MULTIPLE IPs (gateway + others) -> detection signature
docker exec -d victim ip monitor neigh    # watch the lladdr flap live
```

*Step 6 — Defend with a static entry.*

```bash
GW_REAL_MAC=$(docker exec gateway cat /sys/class/net/eth0/address)
docker exec victim ip neigh replace ${GW_IP} lladdr ${GW_REAL_MAC} dev eth0 nud permanent
docker exec victim ip neigh show ${GW_IP}    # PERMANENT — now ignores forged replies
```

**Security implications.** Write down: (a) how one forged, unauthenticated packet redirected the
victim's traffic; (b) why the attacker must keep re-sending (cache expiry); (c) exactly what TLS
did and did not prevent; (d) the detection signatures; (e) why this attack is impossible inside an
AWS VPC (§7).

**Cleanup.**
```bash
for c in victim gateway attacker; do docker rm -f $c; done; docker network rm arplab
```

---

## 9. Security Implications

- **ARP is unauthenticated and gullible by design** — it believes any reply, including unsolicited
  ones (gratuitous ARP). This is the design, not a bug, and cannot be fixed from inside the
  protocol.
- **ARP spoofing is the canonical local-network MITM**: one forged packet redirects a victim's
  traffic to the attacker, who relays it transparently. It is bounded to the broadcast domain.
- **On-path position is only dangerous to unprotected traffic.** TLS with certificate validation
  makes the MITM see ciphertext and blocks tampering/downgrade (with HSTS) — the mechanical case
  for encrypting *everything*, including internal traffic.
- **The feature and the vulnerability are the same mechanism** (gratuitous ARP) — a recurring
  pattern; you wrap it (encryption, monitoring) rather than removing it.
- **Defense in depth across layers**: a total L2 compromise is survived by TLS at L4/5, because
  TLS authenticates the endpoint, not the path.
- **IPv6 NDP has the identical problem** — hardening ARP but ignoring NDP leaves a dual-stack
  network exposed.
- **The cloud SDN removes ARP spoofing inside a VPC** by owning Layer 2 — a genuine benefit, and
  the reason co-tenant sniffing is not viable there.

---

## 10. Attack Scenarios

1. **Gateway ARP-MITM** (§4.4): the classic — become the gateway for a victim, relay traffic, read
   plaintext, spoof DNS, attempt SSL stripping. The basis of most "attacker on the LAN" scenarios.
2. **Bidirectional MITM**: poison both the victim and the gateway for full duplex interception (Lab
   9.1).
3. **ARP-based DoS**: poison a victim with a non-existent MAC for the gateway, black-holing its
   traffic (denial rather than interception).
4. **ARP spoofing → DNS spoofing → phishing/credential theft**: MITM lets the attacker answer DNS,
   redirecting the victim to attacker-controlled servers (Chapter 17).
5. **ARP spoofing → SSL stripping**: downgrade HTTPS to HTTP for a victim who typed `http://` or
   followed an unprotected link; defeated by HSTS preload (Chapter 28).
6. **IPv6 rogue RA / NA spoofing** (§5.1): the IPv6 equivalents, often overlooked.
7. **Lateral movement after host compromise**: a compromised internal host ARP-spoofs to intercept
   credentials of neighboring systems — a common post-exploitation step on flat networks
   (Chapter 125).

All of these are **infeasible inside a standard AWS VPC** (§7) but very real on-prem, in hybrid,
and on shared/guest networks — know them for those environments and for the "why encrypt internal
traffic" argument.

---

## 11. Defensive Techniques

**Network-infrastructure controls (on-prem / traditional):**

- **Dynamic ARP Inspection (DAI)** — the primary defense. The switch validates every ARP packet
  against a trusted IP↔MAC binding table (built from DHCP snooping — Chapter 15) and drops forged
  ARP on untrusted ports. This kills ARP spoofing at the switch. (Chapter 8 §11.)
- **DHCP snooping** — provides the binding table DAI relies on, and stops rogue DHCP (Chapter 15).
- **Port security** — limits MACs per port, hindering the attacker's setup (Chapter 8 §11).
- **Segmentation (VLANs/subnets)** — smaller broadcast domains = smaller ARP blast radius; keep
  sensitive systems off shared segments (Chapters 13, 83).
- **Static ARP entries** for critical mappings (gateways, key servers) on sensitive hosts (§6.3) —
  effective but unscalable; use for the few mappings that matter most.

**Host / detection controls:**

- **arpwatch / IDS rules / `ip monitor neigh`** — alert on MAC flaps, one-MAC-many-IPs, and GARP
  storms (§6.2). Because the attack is noisy (continuous re-sending), detection is feasible.
- **802.1X** — authenticate devices before network access, reducing who can be on the segment
  (Chapter 62).

**The decisive control everywhere — encryption and endpoint authentication:**

- **TLS/mTLS on every connection, including internal** — makes on-path position useless: ciphertext
  only, tampering detected, downgrade blocked (with HSTS). This is the control that does not depend
  on trusting the network at all (Zero Trust, Chapter 43), and it is the one you can apply in any
  environment. Combined with **HSTS (preload)** to prevent SSL stripping (Chapter 28).

**Cloud:**

- **Nothing to do for ARP inside a VPC** — the SDN handles it (§7). Keep ENI source/dest check on
  (Chapter 8 §11). Still encrypt internal traffic as defense in depth and for non-VPC segments.

The prioritization to state in a review: DAI + DHCP snooping stop the attack at the network; but
**TLS/mTLS is the control that makes the attack irrelevant regardless of environment**, so it is
non-negotiable for anything sensitive. "We rely on the network being safe" is never acceptable;
"we encrypt so the network need not be trusted" is the posture.

---

## 12. Production Architecture

Where ARP defense sits in real designs, and the layered logic:

```
 ON-PREM                              AWS VPC
 ---------------------------------    -------------------------------------
 L2 anti-MITM: DHCP snooping + DAI    L2 anti-MITM: SDN (built in) + ENI src/dst check
 segmentation: VLANs                  segmentation: subnets + security groups
 detection:   arpwatch / IDS          detection: VPC Flow Logs / GuardDuty (different signals)
 DECISIVE:    TLS/mTLS everywhere <---SAME--->  TLS/mTLS everywhere
              HSTS preload                       HSTS preload
```

The architectural principle, consistent with the whole book: **do not build confidentiality or
integrity on network trust.** Network-layer ARP defenses (DAI, SDN) reduce the *likelihood* of an
on-path attacker; cryptographic controls (TLS/mTLS + HSTS) remove the *impact* of one. A mature
design has both, and treats the cryptographic layer as the load-bearing one because it holds
regardless of platform, network compromise, or misconfiguration. This is Zero Trust stated at Layer
2/3: authenticate and encrypt the endpoints, and the path can be hostile.

---

## 13. Common Mistakes

1. **Trusting internal/LAN traffic** ("it's behind the firewall") — ARP MITM makes any
   same-segment attacker on-path; encrypt regardless.
2. **Skipping TLS on internal hops** (app→DB, service→service) because "it's internal" — exactly
   what ARP-MITM reads (Chapter 5, §7).
3. **Hardening ARP but ignoring IPv6 NDP** — dual-stack networks are exposed via NDP (§5.1).
4. **Assuming ARP spoofing works in a VPC** (it does not) or, conversely, **assuming the VPC
   removes the need to encrypt internally** (it does not — defense in depth, non-VPC segments,
   fabric misconfig).
5. **Relying on static ARP at scale** — unmanageable; use DAI instead.
6. **No detection** — the attack is noisy and detectable (MAC flaps, GARP storms), but only if you
   watch (arpwatch/IDS).
7. **DAI without DHCP snooping** — DAI needs the binding table snooping provides.
8. **Believing HTTPS alone stops SSL stripping** without HSTS — a victim on `http://` can be
   downgraded before HTTPS engages.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Intermittent connectivity + MAC flapping for one IP | ARP spoofing or duplicate IP | `ip monitor neigh`; `arping <ip>` (multiple/attacker MAC); check DAI logs (Chapter 8 §Sol 8.6) |
| One MAC mapped to many IPs | ARP poisoning in progress | `ip neigh show \| awk '{print $5}' \| sort \| uniq -c` |
| Victim loses all off-segment connectivity | ARP DoS (poisoned with bad gateway MAC) | check gateway ARP entry vs real gateway MAC |
| Traffic works but is being intercepted (subtle) | stealthy MITM with forwarding enabled | look for GARP storms; check gateway MAC against known-good; TLS cert warnings |
| Certificate warnings appearing for internal sites | possible SSL-stripping/MITM, or cert issue | verify cert chain (`openssl s_client`); investigate ARP |
| IPv6 default route changed unexpectedly | rogue Router Advertisement | `ip -6 route`; check for unexpected RAs (`radvdump`); enable RA Guard |
| AWS: suspected instance sniffing neighbors | not possible via ARP in a VPC | confirm no traffic mirroring; the SDN prevents ARP MITM (§7) |

---

## 15. Practical Lab

Lab 9.1 is in §8. Register it in the lab index. Extension: repeat Step 4 with a TLS service
(`openssl s_server` on the gateway, `openssl s_client` on the victim through the MITM) and confirm
the attacker's capture shows only TLS records and that a bad/forged certificate causes the client
to refuse — the direct, hands-on proof of "TLS defeats the on-path attacker" that underpins
Chapters 28 and 43.

---

## 16. Exercises

### Concept questions

**9.1** Explain the exact problem ARP solves and why it must broadcast. What information does a
host have before ARP, and what does it need?

**9.2** Why is ARP spoofing possible? Identify the three trust assumptions in ARP's design and how
each contributes.

**9.3** What is gratuitous ARP, why does it exist legitimately, and why is it the vehicle for
poisoning? Relate this to the recurring "feature = vulnerability" pattern.

**9.4** Explain precisely what TLS does and does not prevent for a victim who is ARP-MITM'd. What
additional control is needed to stop SSL stripping, and why?

**9.5** Why does ARP spoofing not work inside an AWS VPC? Explain the mechanism, not just the
conclusion.

### Debugging problems

**9.6** A user reports certificate warnings on multiple internal sites, and connectivity is slightly
slow. `ip neigh` shows the gateway IP mapping to a MAC with a locally-administered OUI. Diagnose,
and give your first three actions.

**9.7** After enabling DAI on a switch, legitimate hosts lose connectivity intermittently. What is
the most likely cause, and how do you fix it without disabling DAI?

**9.8** An IPv4-hardened network (DAI, DHCP snooping) suffers a MITM anyway. What did the team
likely overlook, and how would you confirm it?

### Security scenarios

**9.9** You are doing an authorized internal assessment and find the network flat (one broadcast
domain) with no DAI and plaintext database connections. Rank the risks and the remediations, and
explain the single control that most reduces impact regardless of the others.

**9.10** A team argues that because they are moving to AWS, they no longer need to encrypt
service-to-service traffic "since the VPC prevents sniffing." Respond precisely: what is true, what
is incomplete, and what you would require.

### Architecture questions

**9.11** Design the defenses for a corporate LAN with untrusted user devices and sensitive servers,
layering network controls and cryptographic controls, and state which control is load-bearing and
why.

**9.12** Explain how the ARP-spoofing threat maps onto (a) Zero Trust principles and (b) the
defense-in-depth-across-layers idea from Chapter 4 §5.1. Use ARP as the concrete example.

### Hands-on exercises

**9.13** Capture and decode an ARP request and reply by hand from a `-X` dump, identifying the
operation field and the sender MAC/IP fields that an attacker would forge.

**9.14** In the Lab 9.1 environment, add a TLS service and demonstrate that the MITM captures only
ciphertext and that a forged certificate is rejected by the client.

**9.15** Write a detection script that watches `ip monitor neigh` (or parses `ip neigh` over time)
and alerts when any IP's MAC changes or when one MAC maps to more than N IPs.

### Interview questions

**9.16** "Walk me through an ARP spoofing man-in-the-middle attack, step by step, and tell me what
stops it at each layer."

**9.17** "If an attacker is already on-path via ARP spoofing, why do we still care about TLS?
What's left for TLS to protect?"

**9.18** "Can a compromised host sniff its neighbors' traffic in a VPC? On a corporate LAN? Explain
both."

**9.19** "How would you detect ARP poisoning, and why is the attack inherently detectable?"

**9.20** "Your CISO asks whether internal service-to-service encryption is worth the operational
cost. Make the argument using ARP as your example."

---

## 17. Summary

- **ARP resolves a known local IP to the MAC needed to build a frame** (Chapter 8's missing step):
  broadcast "who has IP X?", believe the reply, cache it.
- **ARP is unauthenticated, stateless, and accepts unsolicited (gratuitous) replies** — three trust
  assumptions from its 1982 design that make **ARP spoofing/poisoning** trivial: one forged reply
  redirects a victim's traffic to the attacker, who relays it transparently (MITM).
- The **feature and the vulnerability are the same mechanism** (gratuitous ARP), so ARP cannot be
  fixed from within; defenses are external.
- **On-path position is only dangerous to unprotected traffic.** TLS with certificate validation
  reduces the MITM to seeing ciphertext and blocks tampering; **HSTS** additionally blocks SSL
  stripping. This is the mechanical case for encrypting *all* traffic, internal included, and a
  pure example of **defense in depth across layers** (a total L2 compromise survived by L4/5
  crypto).
- **IPv6 NDP has the identical problem** (NA spoofing, rogue RAs) — do not harden ARP and forget
  NDP.
- Network defenses: **DHCP snooping + Dynamic ARP Inspection**, segmentation, static entries for
  critical mappings, and detection (arpwatch/IDS — the attack is noisy). The **load-bearing**
  control everywhere is **TLS/mTLS + HSTS**, because it does not depend on trusting the network.
- **The cloud SDN removes ARP spoofing inside a VPC** by owning Layer 2 — the reason co-tenant
  sniffing is not viable there — while the need to encrypt internally remains as defense in depth.

---

## 18. Knowledge Check

1. What does ARP resolve, and why does it broadcast the request? (§3)
2. Which two fields of an ARP reply does an attacker forge, and to what values for a gateway MITM? (§4.1, §4.4)
3. What is gratuitous ARP and why does it enable poisoning? (§4.3)
4. Why must an attacker continuously re-send forged replies? (§4.2)
5. What does TLS protect during an ARP MITM, and what does HSTS add? (§4.4, §5)
6. Why can't ARP be fixed from within the protocol? (§5)
7. What is the IPv6 equivalent of ARP spoofing? (§5.1)
8. Name the primary switch-level defense and what it depends on. (§11)
9. Why is ARP spoofing infeasible in a VPC? (§7)
10. What is the single load-bearing control against on-path attackers, and why? (§11)

---

## 19. Further Exploration

- RFC 826 (ARP) and RFC 5227 (IPv4 address conflict detection) — short, readable, and reveal the
  trust model directly.
- `man arpwatch`; set it up on a host and watch it report new/changed mappings.
- In Lab 9.1, add DNS spoofing on top of the ARP MITM (answer the victim's DNS with your IP) to see
  the ARP→DNS→phishing chain (bridge to Chapter 17).
- Read about Dynamic ARP Inspection and DHCP snooping in a switch vendor's docs — the concrete
  network defenses you will recommend in hybrid environments.
- For IPv6: read about RA Guard and SEND (SEcure Neighbor Discovery), and run `radvdump` on a
  dual-stack network to see Router Advertisements.
- Revisit Chapter 4 §5.1 and place ARP spoofing on the defense-in-depth table — which layers can
  and cannot stop it, and which catches it.

---

## Solutions

### 9.1
ARP solves the gap between Layer 3 and Layer 2: a host has determined (via the subnet mask,
Chapter 8 §5) that a destination IP is on its local segment and must now build an Ethernet frame,
which requires the destination's *MAC address* — but the host knows only the IP. ARP obtains the
MAC for a given local IP. It must broadcast the request because the host does not yet know which
device (which port/MAC) owns that IP; broadcasting to `ff:ff:ff:ff:ff:ff` reaches every device on
the segment, and only the owner of the queried IP is expected to reply. Before ARP the host has:
the destination IP, its own IP/MAC, and the knowledge that the destination is local. It needs: the
destination's MAC. After ARP it has that mapping cached and can send the frame.

### 9.2
ARP spoofing is possible because ARP was designed for a trusted, cooperative Ethernet and has
three trust assumptions: (1) **replies are truthful** — there is no authentication or proof that
the replier owns the claimed IP, so an attacker's forged reply is accepted; (2) **unsolicited
replies are helpful** — hosts accept gratuitous ARP to update caches, so an attacker need not even
race a legitimate request, just announce a false mapping; (3) **the segment is cooperative** —
every host on the broadcast domain is trusted, so any host can send ARP about any IP. Together
these mean any host can assert "IP X is at my MAC" and be believed, redirecting traffic. None is a
bug; they are the design, which is why defenses are external (DAI, encryption) rather than a
protocol patch.

### 9.3
Gratuitous ARP (GARP) is an *unsolicited* ARP reply/announcement a host sends about its own IP,
without anyone having asked. Legitimate uses: announcing a new IP or a new MAC after a failover (so
peers update their caches quickly and traffic follows the service), detecting duplicate IP
addresses, and generally keeping caches current when mappings change. It is the vehicle for
poisoning precisely because hosts *accept* GARP and overwrite their caches with it — so an attacker
sends GARP claiming the gateway's (or victim's) IP is at the attacker's MAC, and hosts update
without any request having been made. This is the recurring "feature = vulnerability" pattern
(Chapter 1 NX→ROP, Chapter 5 Redis CONFIG): the very mechanism that provides a useful capability
(fast cache updates on failover) is the mechanism the attacker abuses, so you cannot remove it
without breaking legitimate behavior — you must wrap it (encryption, DAI, monitoring).

### 9.4
During an ARP MITM, TLS **prevents** the attacker from reading the plaintext (they see only
ciphertext), from tampering with the data undetected (AEAD integrity), and from impersonating the
server (the attacker cannot present a valid certificate for the real hostname, so a validating
client refuses the connection). TLS does **not** prevent the attacker from being on-path, from
seeing metadata (the destination IP, the SNI hostname in TLS ≤1.2 and often 1.3, traffic timing
and volume), or from denying service (dropping traffic). The gap TLS alone leaves is **SSL
stripping**: if the victim first requests `http://` (typed a bare domain, or followed an
unprotected link), the MITM can serve plaintext and rewrite `https://` links, keeping the victim on
HTTP so TLS never engages. The additional control is **HSTS** (ideally preloaded): the browser,
having seen HSTS (or being on the preload list), refuses to speak HTTP to that domain at all and
upgrades to HTTPS before connecting, closing the initial-plaintext window. So TLS + HSTS together
neutralize the on-path attacker for web traffic.

### 9.5
ARP spoofing does not work in a VPC because AWS does not run a shared Ethernet where hosts resolve
and trust each other's ARP; the VPC is a software-defined network on the Nitro cards that owns
Layer 2. The SDN answers ARP authoritatively (it knows the true IP↔ENI↔MAC bindings) and, crucially,
delivers frames only to the ENI that legitimately owns the destination address — it will not
deliver a victim's traffic to an attacker's ENI just because the attacker sent a forged ARP.
Forged ARP from a compromised instance is simply ignored by the fabric; there is no cache to poison
on peer instances that the attacker can influence, and ENI source/destination checks drop spoofed
packets. So the prerequisites for ARP MITM (a shared medium and hosts that trust forged ARP) are
absent. The mechanism, not just the conclusion: **the cloud controls the ARP/address-resolution
function and the frame delivery, so the trust the attack depends on is held by AWS, not by
exploitable peer hosts.**

### 9.6
The locally-administered OUI on the gateway's MAC, plus certificate warnings on multiple sites and
slight slowness, strongly indicates an **ARP-spoofing MITM**: an attacker has poisoned the ARP
cache so the gateway IP points at their (software-set) MAC, is relaying traffic (the slowness), and
is attempting interception (the cert warnings arise from TLS interception attempts or SSL
stripping). Diagnose: compare the current gateway MAC (`ip neigh show <gw>`) against the known-good
gateway MAC; check for one MAC mapping to multiple IPs and for MAC flapping (`ip monitor neigh`);
capture ARP (`tcpdump arp`) to see GARP storms. First three actions: (1) **contain** — isolate the
affected segment or the suspected attacker port if identifiable (switch port from the MAC), and
alert the network team; (2) **verify and preserve evidence** — confirm the poisoning, capture the
forged ARP and the attacker MAC, correlate to a switch port/host; (3) **protect users** — instruct
affected users not to bypass certificate warnings (the warnings are TLS *working*), and remediate
via DAI/DHCP snooping if not already enabled, plus locate and remove the attacking host. Root-cause
follow-up: why was the segment un-inspected (no DAI) and can sensitive traffic be encrypted end to
end.

### 9.7
The most likely cause is that DAI is dropping legitimate ARP because the **DHCP-snooping binding
table is incomplete or DAI trust settings are wrong**: DAI validates ARP against bindings learned
from DHCP snooping, so hosts with **static IPs** (or hosts whose leases predate snooping being
enabled) have no binding and their ARP is dropped, and **trunk/uplink ports** or ports to other
switches/routers not marked as *trusted* have their legitimate ARP inspected and dropped. Fix
without disabling DAI: mark inter-switch links, the DHCP server port, and router/gateway ports as
**DAI-trusted**; add **static ARP-inspection ACLs (or static DHCP-snooping bindings)** for hosts
with static IPs so DAI recognizes them; and ensure DHCP snooping is fully deployed and the binding
table has repopulated (may require hosts to renew leases). Essentially, DAI needs a complete,
correct binding table and correct trusted-port configuration; the outage is a configuration gap,
not a reason to turn off the control.

### 9.8
The team likely overlooked **IPv6 / NDP**: they hardened IPv4 ARP with DAI and DHCP snooping, but
on a dual-stack (or IPv6-enabled) network the attacker used **Neighbor Advertisement spoofing** or,
more powerfully, a **rogue Router Advertisement** to become the default gateway over IPv6 —
achieving the same MITM through a protocol the IPv4 controls do not touch (§5.1). Modern OSes prefer
IPv6 when available, so even an "IPv4 network" often carries IPv6 traffic. Confirm: check for
unexpected IPv6 default routes (`ip -6 route`), capture Router Advertisements (`radvdump` / tcpdump
for ICMPv6 type 134) and Neighbor Advertisements (type 136) for spoofed entries, and see whether
hosts acquired IPv6 addresses/gateways from an unexpected source. Remediate with **RA Guard**, **ND
Inspection**, and disabling IPv6 where unused — mirroring the IPv4 defenses. The lesson: L2/L3
MITM defenses must cover *both* stacks.

### 9.9
Risks, ranked: (1) **Plaintext database connections on a flat network with no DAI** — the highest
impact: any compromised or malicious host on the single broadcast domain can ARP-spoof and read/
modify all DB traffic (credentials, PII), i.e. total data exposure with a trivial attack. (2)
**Flat network (one broadcast domain)** — the ARP blast radius is the entire estate; any compromise
becomes network-wide interception/lateral movement. (3) **No DAI/DHCP snooping** — nothing stops
the spoofing at the switch. Remediations, matched: enable **TLS/mTLS on all internal connections**
(especially DB), **segment** the network into per-trust broadcast domains, and deploy **DHCP
snooping + DAI**; add detection (arpwatch/IDS). The single control that most reduces impact
*regardless of the others* is **encrypting internal traffic (TLS/mTLS)**: even on a flat network
with no DAI and an attacker fully on-path, encrypted traffic yields only ciphertext and rejects
tampering/impersonation — the attack's *impact* drops to metadata and DoS. Segmentation and DAI
reduce *likelihood*; encryption removes *impact*, and impact-removal that holds under a successful
attack is the priority.

### 9.10
True: inside a standard VPC, ARP spoofing does not work and a compromised instance cannot sniff a
neighbor's traffic via L2 (§7), so the specific "sniffing on a shared medium" threat is indeed
handled by the SDN. Incomplete: (1) the guarantee is about the *VPC fabric* — it does not cover
traffic that leaves the VPC, hybrid/on-prem segments, VPC peering to less-trusted networks, or
overlay/CNI networks inside instances that re-create an unprotected L2; (2) it does not protect
against a *compromised endpoint or shared service* the traffic legitimately passes through, or
against **VPC Traffic Mirroring** being enabled; (3) the dominant cloud risk has moved to the
**control plane and IAM** (an over-permissioned role reads the data over the API with no sniffing
at all — Chapter 6 §4.4), which internal encryption is orthogonal to but which reinforces the
"don't rely on network position" mindset; (4) defense in depth and many compliance regimes require
encryption in transit regardless of network controls. What I would require: **TLS/mTLS on
service-to-service traffic** as the default, because it removes the *impact* of any on-path or
fabric-level failure and holds across VPC boundaries, hybrid links, and future architecture
changes — the operational cost is real but modern mesh/ALB tooling makes it routine, and the
posture must be "the network is not trusted" (Zero Trust), not "the VPC is safe."

### 9.11
Layered design. **Network controls (reduce likelihood):** put untrusted user devices and sensitive
servers in **separate VLANs/subnets** (separate broadcast domains, so users cannot ARP-spoof
servers directly); enforce **802.1X** so devices authenticate before joining; deploy **DHCP
snooping + Dynamic ARP Inspection** and **port security** on user segments to stop ARP spoofing and
MAC games; add **RA Guard/ND Inspection** for IPv6; and route inter-segment traffic through an L3
firewall enforcing least-privilege access. **Detection:** arpwatch/IDS for MAC flaps and GARP
storms. **Cryptographic controls (remove impact):** **TLS/mTLS on all server-to-server and
client-to-server connections**, **HSTS (preloaded)** for web services, and mutual authentication so
endpoints verify each other regardless of path. The **load-bearing control is TLS/mTLS**: the
network controls reduce the chance of an on-path attacker, but they can fail (misconfiguration, a
new VLAN, an insider, IPv6 oversight), whereas endpoint encryption makes an on-path attacker
harmless by design and does not depend on the network being trustworthy — it is the control that
still holds when everything else fails, which is the definition of the one to rely on.

### 9.12
(a) **Zero Trust**: ARP spoofing is the concrete proof of Zero Trust's founding premise — "the
network is not a trust boundary." A host being "on the internal LAN" confers no trustworthiness,
because any host on the segment can become on-path via ARP with one forged packet. Zero Trust
responds by never trusting the network and instead authenticating and encrypting at the endpoints
(mTLS, identity-based access), so location on the network grants nothing. ARP spoofing is the
worked example that makes "never trust the network" not a slogan but a mechanical necessity. (b)
**Defense in depth across layers** (Chapter 4 §5.1): ARP spoofing is a *total compromise of Layer
2* — the attacker fully controls local delivery. Yet the system survives because a control at a
*higher, independent* layer (TLS at L4/5) does not depend on L2's integrity: TLS authenticates the
*endpoint cryptographically*, not the *path*, so a lied-to Layer 2 cannot forge a valid
certificate or read the ciphertext. This is the essence of defense in depth: layers whose controls
do not depend on lower layers' integrity, so that a lower layer's complete failure is caught above.
ARP + TLS is the cleanest example in the book of a lower-layer compromise being rendered impotent
by an independent higher-layer control.

### 9.13
Expected: capture with `sudo tcpdump -e -X arp -c 2` and decode the ARP payload (after the 14-byte
Ethernet header) from the hex: bytes are HW type `00 01` (Ethernet), protocol type `08 00` (IPv4),
HW len `06`, proto len `04`, **operation** `00 01` (request) or `00 02` (reply), then **sender MAC**
(6 bytes), **sender IP** (4 bytes), target MAC (6 bytes), target IP (4 bytes). For a request, the
sender fields are the asker and the target MAC is zero; for a reply, the sender MAC/IP are the
*answer*. The fields an attacker forges in a malicious reply are the **operation = 2** with **sender
IP = the impersonated IP (e.g. the gateway)** and **sender MAC = the attacker's MAC** — the
unverified assertion that gets cached. Deliverable: point to those exact bytes in the dump and
explain that nothing in the packet proves the sender owns the sender IP.

### 9.14
Expected: on the gateway container run a TLS echo/HTTP server (`openssl s_server -accept 8443 -cert
c.pem -key k.pem` or a small HTTPS server); on the victim, connect through the established MITM
(`openssl s_client -connect <gw>:8443` or curl). With the attacker sniffing (Lab 9.1 Step 4), show
that `tcpdump -A -r` on the attacker's capture reveals only TLS handshake and `application_data`
records — no plaintext of the exchanged data. Then have the attacker attempt active interception by
presenting *their own* certificate (a TLS proxy); show that the victim's `openssl s_client` reports
certificate verification failure (unknown CA / name mismatch) and, with verification enforced,
refuses to proceed. Deliverable: two observations — (1) passive MITM yields only ciphertext, (2)
active MITM requires a certificate the attacker cannot forge, so a validating client rejects it —
proving TLS defeats both passive and active on-path attacks and grounding §9's claim mechanically.

### 9.15
Expected: a script that maintains a map of IP→MAC and watches for changes, e.g. parse
`ip -json neigh` (or `ip monitor neigh`) in a loop, and alert when (a) an IP's `lladdr` changes to
a different MAC (flap) or (b) any single MAC is associated with more than N distinct IPs. Skeleton:
```bash
declare -A seen
ip monitor neigh | while read -r line; do
  ip=$(awk '{print $1}' <<<"$line"); mac=$(grep -oE 'lladdr [0-9a-f:]+' <<<"$line" | awk '{print $2}')
  [ -z "$mac" ] && continue
  if [ -n "${seen[$ip]}" ] && [ "${seen[$ip]}" != "$mac" ]; then
     echo "ALERT: $ip changed MAC ${seen[$ip]} -> $mac (possible ARP spoofing)"
  fi
  seen[$ip]=$mac
  # also count MACs->IPs and alert if one MAC maps to > N IPs
done
```
Real-world refinements: whitelist legitimate failover events, alert on gratuitous-ARP storms
(reply rate), integrate with the SIEM (Chapter 118), and pin the gateway MAC. The detection works
because the attack is inherently noisy — continuous re-poisoning causes flaps and one-MAC-many-IPs,
exactly what the script keys on.

### 9.16
Steps: (1) The attacker M, on the same broadcast domain as victim A and gateway G, sends A a forged
ARP reply "G's IP is at M's MAC," and sends G "A's IP is at M's MAC" (gratuitous/unsolicited, so no
request needed). (2) A and G cache these, so A→internet frames go to M's MAC and G→A frames go to
M's MAC. (3) M enables IP forwarding and relays each frame to the real destination, so connectivity
looks normal (stealth), while M reads/modifies everything. (4) M re-sends the forged replies
periodically to keep the poison fresh. What stops it at each layer: **L2** — Dynamic ARP Inspection
+ DHCP snooping drop the forged ARP at the switch (and the cloud SDN prevents it entirely);
segmentation limits reach. **Detection** — arpwatch/IDS see the MAC flap and GARP storm. **L4/5** —
TLS makes the intercepted traffic ciphertext and blocks tampering/impersonation (M cannot present a
valid cert), and **HSTS** blocks SSL stripping. The decisive, environment-independent stopper is
**TLS/mTLS + HSTS**, because it removes the impact even when L2 is fully compromised — defense in
depth across layers.

### 9.17
Because ARP spoofing gives the attacker *position* (on-path), not *comprehension* or *control* of
the content — and TLS is exactly what denies them comprehension and control. On-path, without TLS,
the attacker reads all plaintext, modifies responses, injects content, and impersonates servers —
total compromise. With TLS (and certificate validation), the attacker on the same path sees only
ciphertext (confidentiality preserved), cannot alter data undetected (AEAD integrity), and cannot
impersonate the server because they cannot produce a valid certificate for the real name
(authentication) — a validating client refuses to connect to the attacker's substitute. So what is
"left for TLS to protect" is *everything that matters*: the actual data, its integrity, and the
identity of the peer. The attacker is reduced to seeing metadata (destination IP, SNI, timing/
volume) and to denial of service. Add HSTS to prevent the attacker from keeping the victim on
plaintext (SSL stripping). The point: position without cryptography is game over; position *with*
cryptography is nearly useless — which is why TLS is the load-bearing control against on-path
attackers.

### 9.18
**Corporate LAN:** yes, generally. A compromised host on the same broadcast domain can ARP-spoof
the gateway and its neighbors to become on-path and sniff/modify their traffic (the classic MITM),
bounded to that broadcast domain and defeated only by DAI/DHCP snooping at the switch, segmentation,
and — decisively — encryption of the traffic. So on a flat, un-inspected LAN, sniffing neighbors is
straightforward. **VPC:** no (at the fabric level). The SDN owns Layer 2, answers ARP
authoritatively, delivers frames only to the legitimate owner ENI, and enforces source/destination
checks, so a compromised instance cannot ARP-spoof or put its NIC in promiscuous mode to see
neighbors' unicast (§7). Caveats: VPC Traffic Mirroring configured to the attacker, overlay/CNI
networks inside instances that re-create an unprotected L2, or plaintext to a shared compromised
service. The precise contrast: the *same attack* that is trivial on a traditional LAN is
architecturally prevented inside a VPC because the cloud controls the L2 function — which is why
you defend the LAN with DAI+encryption and defend the VPC by focusing on IAM/config while still
encrypting internally as defense in depth.

### 9.19
Detect ARP poisoning by watching for its signatures: (1) an IP's MAC **changing/flapping** between
the legitimate and the attacker's MAC (`ip monitor neigh`, arpwatch); (2) **one MAC mapped to
multiple IPs** (the attacker impersonating several hosts/the gateway); (3) a **flood of unsolicited
(gratuitous) ARP replies**, especially for the gateway IP; (4) the gateway's MAC differing from a
known-good baseline, or having a locally-administered OUI unexpectedly. Tools: arpwatch, IDS
signatures (Snort/Suricata ARP rules), DAI logs on the switch, and `ip neigh`/`ip monitor` scripts
(Ex. 9.15). The attack is *inherently* detectable because ARP cache entries expire after tens of
seconds to minutes, so to maintain the MITM the attacker **must continuously re-send** the forged
replies — producing a steady stream of anomalous ARP that a passive monitor cannot miss. In other
words, the very persistence the attack requires is what betrays it; a one-shot poison would fade,
so a sustained MITM is always noisy.

### 9.20
Argument: internal service-to-service encryption is worth the cost because the alternative —
trusting the internal network — is unsafe, and ARP spoofing proves it concretely. On any shared
broadcast domain, an attacker (a compromised host, a malicious insider, a rogue device) can become
on-path with a single forged, unauthenticated ARP packet and then read and modify *all* unencrypted
internal traffic — including database credentials, tokens, and PII flowing between services. This
is not theoretical or difficult; it is a well-known, tooled attack, and it needs only presence on
the segment, which one compromised workload provides (lateral movement, Chapter 125). Network
controls (DAI, segmentation) reduce the likelihood but can fail — a new VLAN, a misconfiguration,
an IPv6 oversight, an insider — and they do not cover hybrid links or future architecture. mTLS
removes the *impact*: even a fully on-path attacker gets only ciphertext and cannot impersonate a
service, so a single host compromise no longer cascades into wholesale interception. The
operational cost is real but now routine with service meshes and managed certificate rotation, and
it directly enables Zero Trust and satisfies compliance requirements for encryption in transit. In
short: we already know attackers can get on-path internally (ARP proves it), so we must make that
position worthless — that is precisely what internal encryption does, and it is cheaper than the
breach it prevents.

---

*Next: Chapter 10 — IPv4 Addressing, Subnet Masks, CIDR, and Subnetting Without a Calculator. We
move up to Layer 3: how the addresses that ARP resolves are structured, how the subnet mask decides
"local or remote" (the decision that triggered ARP in Chapter 8 §5), and how CIDR blocks — the unit
of every security group, NACL, and firewall rule you will ever write — actually work.*
