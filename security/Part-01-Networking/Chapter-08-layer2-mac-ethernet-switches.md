# Chapter 8 — Layer 2: MAC Addresses, Ethernet Frames, NICs, Switches, and Broadcast Domains

---

## 1. Why This Matters

We start the networking stack at the bottom — the link layer, Layer 2 — because that is where
bytes physically become "network." Everything above (IP, TCP, TLS, HTTP) rides inside Layer 2
frames, and several attacks and controls you will meet later only make sense once you know what a
frame is, what a MAC address is, and what a switch does and does not isolate.

You might reasonably ask why a *cloud* security engineer needs Layer 2 at all — in AWS you never
touch a switch. The answer is threefold, and it matters:

1. **The cloud virtualizes Layer 2, and the abstractions carry L2 concepts.** A VPC subnet is a
   broadcast domain (mostly); an ENI has a MAC address; security groups make decisions that only
   make sense against the L2/L3 model. AWS's software-defined network *emulates* a switched
   Ethernet, and the vocabulary is identical (Chapter 75).
2. **L2 attacks explain why higher-layer controls exist.** ARP spoofing (Chapter 9), MAC
   flooding, and VLAN hopping are the reasons "the local network is trusted" is false, which is
   the reason Zero Trust (Chapter 43) exists. You cannot argue for encrypting internal traffic
   without understanding that the switch does not protect it.
3. **You will debug L2 in hybrid and on-prem environments**, in containers (which have virtual
   Ethernet interfaces and bridges — Chapter 93, 103), and whenever "the network is broken" turns
   out to be an ARP, MAC, or MTU issue.

The single most important idea this chapter installs: **Layer 2 provides delivery between devices
on the same local segment, with essentially no security.** A switch's job is efficiency, not
isolation. Any host on the same segment can, with the right techniques, see or redirect its
neighbors' traffic. Every "encrypt it anyway" and "don't trust the LAN" recommendation later
traces to this fact.

---

## 2. Prerequisites

- Chapter 7 (bits/hex, reading headers, bitmasks) — we decode Ethernet frames here.
- Chapter 3 (the NIC appeared as the bottom of the socket→wire path) and Chapter 4 (the layering
  model — L2 is the bottom envelope).
- The OSI/TCP-IP layering vocabulary at a basic level; we ground it concretely.

---

## 3. Mental Model

**Layer 2 delivers frames between devices that share a physical (or virtual) segment, addressing
them by hardware (MAC) address, with no authentication and no encryption.** It is the postal
service *within one building*: it knows how to get an envelope from room to room, it does not know
about street addresses (that is IP, Layer 3), and it does not check who you are.

```
   THE LAYERING (each layer wraps the one above — Chapter 4 restated bottom-up):

   +--------------------------------------------------+
   | Application data (HTTP...)                        |  Layer 7
   +--------------------------------------------------+
   | TCP segment (ports, seq)          <- Chapter 19  |  Layer 4
   +--------------------------------------------------+
   | IP packet (src/dst IP, TTL)       <- Chapter 10  |  Layer 3
   +--------------------------------------------------+
   | ETHERNET FRAME (src/dst MAC)      <- THIS CHAPTER|  Layer 2
   |    [ dst MAC | src MAC | type | ...payload... | FCS ]     |
   +--------------------------------------------------+
   | bits on the medium                               |  Layer 1
   +--------------------------------------------------+
```

Two scopes you must never confuse, because attacks and controls depend on the distinction:

- **MAC addresses are *local*.** They identify a NIC on the current segment and **do not travel
  beyond the first router.** Every hop rewrites the L2 header with new source/dest MACs. The IP
  addresses (Layer 3) stay the same end to end; the MACs change hop by hop (Chapter 12 makes this
  precise). So a MAC address is meaningful only within one broadcast domain.
- **A broadcast domain** is the set of devices that receive each other's broadcast frames — one
  "segment." A switch extends a broadcast domain; a *router* is the boundary between broadcast
  domains. VLANs subdivide broadcast domains logically (Chapter 13).

**The security kernel of the chapter:** within a broadcast domain, Layer 2 assumes cooperation.
Switches learn where MACs are by watching traffic and trust what they see; hosts trust ARP
replies (Chapter 9); there is no built-in identity. This is why L2 is a soft, trusting layer, and
why "same LAN" must never be equated with "trusted."

---

## 4. Fundamentals

### 4.1 The MAC address

A **MAC (Media Access Control) address** is a 48-bit (6-byte) identifier for a network interface,
written as six hex pairs: `00:1a:2b:3c:4d:5e` (Chapter 7 — each pair is one byte). Structure:

```
   00:1a:2b : 3c:4d:5e
   |________|  |________|
   OUI          NIC-specific
   (vendor)     (per-interface)

   Two special bits in the FIRST byte (0x00 = 0000 0000):
     bit 0 (I/G): 0 = unicast (one interface), 1 = multicast (a group)
     bit 1 (U/L): 0 = universally administered (vendor-assigned, globally unique)
                  1 = locally administered (set by software — e.g. a VM, or a spoofer)
```

Security-relevant facts:

- **The OUI (Organizationally Unique Identifier)**, the first 3 bytes, is assigned to a vendor.
  You can look it up (`00:50:56` = VMware, `02:...` often a locally-administered/virtual NIC).
  In forensics and asset discovery, the OUI tells you the device type/vendor.
- **MAC addresses are trivially spoofable.** The U/L bit and `ip link set dev eth0 address ...`
  let any host present any MAC. **Never use a MAC address as an authentication or authorization
  credential** — "MAC filtering" on Wi-Fi and NAC is a speed bump, not a control. This is a
  direct consequence of L2 having no authentication.
- **The broadcast MAC is `ff:ff:ff:ff:ff:ff`** — a frame sent here goes to every device in the
  broadcast domain. ARP (Chapter 9) uses it; so do several attacks and discovery techniques.
- **Locally-administered MACs (U/L bit set)** are normal for VMs, containers, and randomized Wi-Fi
  (phones randomize MACs for privacy). Seeing `02:`/`06:`/`0a:`/`0e:` as the first byte usually
  means a software-assigned MAC.

### 4.2 The Ethernet frame

The frame is the L2 envelope. Decoding one with Chapter 7's skills:

```
   [ Preamble ][ Dst MAC ][ Src MAC ][ EtherType ][   Payload   ][ FCS ]
     (7+1 B)     6 bytes    6 bytes     2 bytes      46-1500 B    4 bytes
     (hw sync)                                      (the IP packet) (CRC)

   Example header (12 bytes MAC + 2 bytes type):
   ff ff ff ff ff ff  0a 1b 2c 3d 4e 5f  08 06
   |______________|  |______________|  |___|
   dst = broadcast    src MAC           EtherType 0x0806 = ARP
```

Fields that matter:

- **Destination MAC** first (the switch reads this to decide where to forward — §4.4).
- **Source MAC** second.
- **EtherType** identifies the payload protocol: `0x0800` = IPv4, `0x86DD` = IPv6, `0x0806` = ARP,
  `0x8100` = 802.1Q VLAN tag (Chapter 13). This is how the NIC/kernel knows to hand the payload to
  the IP stack vs. the ARP handler.
- **Payload**: 46–1500 bytes normally. The **1500-byte maximum is the MTU** (Chapter 22) — the
  reason large data is split into many frames, and the source of fragmentation bugs.
- **FCS (Frame Check Sequence)**: a CRC-32 checksum. It detects *accidental* corruption (a flipped
  bit on the wire) and the NIC drops frames that fail it. Crucially, **the FCS is not a security
  control** — it detects noise, not tampering; an attacker who rewrites a frame simply recomputes
  the FCS. Integrity against an adversary is TLS's job (Chapter 28), not Ethernet's. This is a
  clean example of "error detection ≠ authentication."

### 4.3 The NIC (Network Interface Card)

The NIC is the hardware that puts frames on the medium and pulls them off (Chapter 3 §5.2, step
9). Security-relevant behaviors:

- **Normal mode:** the NIC accepts frames addressed to its own MAC, broadcast, and subscribed
  multicast; it drops the rest in hardware. So a host normally does *not* see traffic destined for
  other MACs — even on a shared medium.
- **Promiscuous mode:** the NIC accepts *all* frames it sees, regardless of destination MAC. This
  is what packet sniffers (Wireshark, tcpdump — Chapter 24) require to capture others' traffic.
  On a *switched* network, promiscuous mode alone shows you little (the switch only sends you your
  own traffic — §4.4), which is *why* attackers need ARP spoofing or MAC flooding to first
  redirect traffic to themselves (Chapter 9). Promiscuous mode is thus a prerequisite for
  sniffing but not sufficient on a switch.
- **Offloads:** modern NICs compute checksums, segment large sends (TSO/GSO), and (in clouds)
  handle VXLAN/overlay encapsulation. In AWS Nitro, a dedicated card handles VPC networking
  entirely (Chapter 1 §12, Chapter 75) — the "NIC" your instance sees is a virtualized interface.
- **MAC is configurable in software**, per §4.1 — the NIC's advertised MAC is not immutable.

### 4.4 The switch: learning, forwarding, and its (lack of) isolation

A **switch** connects devices in a broadcast domain and forwards frames intelligently. Its core
mechanism, the **MAC address table** (or CAM table), is worth understanding precisely because its
*failure modes are attacks*:

```
   A switch LEARNS by watching SOURCE MACs on each port:

   Frame arrives on port 3 with src MAC 0a:1b:2c:...  ->  "MAC 0a:1b:2c is on port 3"
   Switch records:  MAC-table[0a:1b:2c:3d:4e:5f] = port 3

   A switch FORWARDS by looking up the DEST MAC:
     - dest MAC in table  -> send ONLY out that port (unicast — this is the efficiency)
     - dest MAC unknown   -> FLOOD out all ports except the source (like a hub)
     - dest = broadcast   -> FLOOD out all ports except the source
```

Read the consequences carefully, because they are the whole security story of switching:

- **A switch is not a security device.** It forwards based on a learned table for efficiency, not
  policy. It does not authenticate MACs and does not, by default, prevent a host from claiming
  another's MAC or from seeing flooded traffic.
- **When the MAC table is full or an entry is unknown, the switch floods** — reverting to
  hub-like behavior where every port sees the frame. This is exactly the **MAC flooding attack**
  (§10): fill the CAM table with bogus MACs, and the switch floods all traffic, letting the
  attacker's promiscuous NIC capture everything on the segment.
- **The switch trusts source MACs**, so an attacker changing their MAC or sending frames with a
  victim's source MAC can poison the table (**MAC spoofing**), causing the switch to send the
  victim's traffic to the attacker's port.
- **A switch limits *collision* domains (one per port) but the whole switch is one *broadcast*
  domain** unless VLANs subdivide it (Chapter 13). Broadcasts (ARP, DHCP discovery) reach every
  port.

Compare to the ancestor **hub**, which simply repeats every frame to every port (one collision
domain, no learning) — a hub is a switch with an always-flooding table, which is why MAC flooding
"turns a switch into a hub" and is dangerous.

### 4.5 Broadcast domains, collision domains, and where routers fit

Three scoping concepts, cleanly separated:

```
   COLLISION DOMAIN: devices that can collide if they transmit simultaneously.
     - a hub = one collision domain (all ports share the medium)
     - a switch = one collision domain PER PORT (full-duplex, no collisions)
     - largely historical now, but explains why switches replaced hubs

   BROADCAST DOMAIN: devices that receive each other's broadcast frames.
     - a switch (or set of switches) = one broadcast domain
     - a VLAN = one broadcast domain (logically carved from a switch — Chapter 13)
     - a ROUTER is the boundary: broadcasts do NOT cross a router (Chapter 12)

   In AWS: a subnet behaves like a broadcast domain boundary for many purposes;
     routing between subnets goes through the VPC router (Chapter 75).
```

The security relevance: **the broadcast domain is the blast radius of L2 attacks.** ARP spoofing,
MAC flooding, and rogue DHCP (Chapter 15) affect everything in the same broadcast domain and stop
at the router. This is why network segmentation — putting sensitive systems in their own
VLAN/subnet — limits L2 attack reach (Chapter 13, 83), and it is a concrete instance of the
blast-radius reasoning from Chapter 1 §5.4 applied to the network.

---

## 5. Deep Technical Explanation: A Frame's Journey Across a Switched Segment

Trace a frame from host A (`10.0.1.5`, MAC `0a:...:05`) to host B (`10.0.1.9`, MAC `0a:...:09`)
on the same segment, then contrast with a frame destined off-segment. This ties L2 to L3 and
sets up ARP (Chapter 9) and routing (Chapter 12).

**Same segment (A → B, both on 10.0.1.0/24):**

```
1. A's IP stack: "10.0.1.9 is on my subnet (same L3 network) -> deliver directly on L2."
2. A needs B's MAC. It checks its ARP cache; if absent, it ARPs (Chapter 9):
      broadcast "who has 10.0.1.9?" -> B replies "10.0.1.9 is at 0a:...:09"
3. A builds a frame:  dst MAC = 0a:...:09,  src MAC = 0a:...:05,  EtherType 0x0800 (IPv4),
      payload = the IP packet (src 10.0.1.5, dst 10.0.1.9).
4. A sends it. The switch reads dst MAC 0a:...:09, looks it up -> port 7 -> forwards ONLY to B.
5. B's NIC accepts it (dst MAC matches), strips the frame, hands the IP packet up the stack.
```

Note step 1: **the source decides "local or remote" by comparing the destination IP to its own
subnet** (a Layer 3 decision using the subnet mask — Chapter 10), and only *then* uses L2 to
deliver. L2 and L3 cooperate: L3 decides *who*, L2 decides *how to hand it over the local wire*.

**Off segment (A → 8.8.8.8):**

```
1. A's IP stack: "8.8.8.8 is NOT on my subnet -> send to my DEFAULT GATEWAY."
2. A needs the GATEWAY's MAC (not 8.8.8.8's!). It ARPs for the gateway (10.0.1.1).
3. A builds a frame:  dst MAC = GATEWAY's MAC,  src MAC = A's MAC,  payload = IP packet
      (src 10.0.1.5, dst 8.8.8.8 — the IP destination is the FINAL target, unchanged).
4. The router receives the frame, strips it, sees dst IP 8.8.8.8 is remote, and forwards
      the IP packet on toward 8.8.8.8 — building a NEW L2 frame for the next hop.
```

This is the crucial insight that unifies L2 and L3: **the destination MAC is always the *next
hop* on the local segment; the destination IP is always the *final* target.** For local traffic
they point at the same device; for remote traffic the MAC points at the gateway while the IP
points across the internet. Every router rewrites the L2 header (new src/dst MAC) while leaving
the L3 header's IPs intact (except TTL decrement — Chapter 12). Hold this; it is the single most
common source of confusion in networking, and Chapter 9 (ARP) and Chapter 12 (routing) both build
directly on it.

The security payoff: an on-path attacker who controls L2 (via ARP spoofing) can make host A send
its off-segment traffic to the *attacker's* MAC instead of the gateway's — a man-in-the-middle,
achieved entirely at Layer 2 (Chapter 9). Understanding step 2 above (A ARPs for the gateway, and
trusts the reply) is understanding exactly how that MITM works.

---

## 6. Internals: Observing Layer 2

### 6.1 Your interfaces and their MACs

```bash
$ ip link show
1: lo: <LOOPBACK,UP,LOWER_UP> ...
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
    link/ether 0a:1b:2c:3d:4e:5f brd ff:ff:ff:ff:ff:ff

# Fields: link/ether = this NIC's MAC; brd ff:...:ff = the broadcast MAC; mtu 1500 (Chapter 22)
$ ip -br link                    # brief view
$ cat /sys/class/net/eth0/address    # the MAC, from sysfs (Chapter 32)
```

Note the `mtu 1500` (Chapter 22) and the broadcast address. On a container host you will also see
`veth...` pairs and a `docker0`/`cni0` bridge — the virtual Layer 2 of containers (Chapter 93).

### 6.2 Spoof your own MAC (prove it is trivial)

```bash
$ sudo ip link set dev eth0 down
$ sudo ip link set dev eth0 address 02:11:22:33:44:55   # 02 = locally-administered bit set
$ sudo ip link set dev eth0 up
$ ip link show eth0 | grep ether
    link/ether 02:11:22:33:44:55 ...
# Restore: reboot, or set it back to the original (from `ethtool -P eth0` permanent addr)
```

You just changed your hardware identity in three commands. This is why MAC-based access control is
not a security control — the "credential" is attacker-chosen.

### 6.3 The ARP cache and the MAC table (a preview of Chapter 9)

```bash
$ ip neigh show                  # this host's mapping of IPs -> MACs (the ARP cache)
10.0.1.1  dev eth0 lladdr 0a:00:00:00:00:01 REACHABLE   # the gateway
10.0.1.9  dev eth0 lladdr 0a:1b:2c:3d:4e:09 STALE
```

On a managed switch you would inspect the CAM table (`show mac address-table` on Cisco IOS); in
the cloud you do not have that access, but the concept — IP↔MAC↔port bindings — is what the
virtual network maintains for you.

### 6.4 Watch frames on the wire

```bash
# Layer 2 detail: -e shows Ethernet headers (src/dst MAC, EtherType)
$ sudo tcpdump -e -n -i eth0 -c 5
10:22:41 0a:1b:2c:3d:4e:05 > 0a:1b:2c:3d:4e:09, ethertype IPv4 (0x0800), length 74: 10.0.1.5.51844 > 10.0.1.9.443: Flags [S] ...
10:22:41 0a:1b:2c:3d:4e:05 > ff:ff:ff:ff:ff:ff, ethertype ARP (0x0806), length 42: Request who-has 10.0.1.9 tell 10.0.1.5
```

Read it with Chapters 7–8: the `-e` output shows `srcMAC > dstMAC, ethertype`. The first line is
an IPv4 frame (unicast, dst = B's MAC); the second is an ARP request (dst = broadcast). You can
now see the L2 layer that Chapter 4's `curl -v` hid. Chapter 24 turns this into a full workshop.

---

## 7. Real-World Example: Layer 2 in the Ledger Environments

**System A (VPS):** the VPS has one virtual NIC on the provider's network. The "segment" is the
provider's virtualized L2, shared (logically) with other tenants' VMs. The security implications:

- Your VPS's L2 neighbors may be *other customers*. On poorly-isolated providers, ARP spoofing and
  sniffing between tenants have historically been possible — a reason to treat even the "private"
  provider network as untrusted and to encrypt everything (Chapter 28). Reputable providers
  isolate tenants at L2, but you should not *assume* it.
- The loopback binds of Chapter 3 §7 protect against network exposure, but L2 attacks target
  traffic that *does* traverse the NIC (e.g. to the gateway) — another argument for TLS on every
  hop, even internal.

**System B (AWS VPC):** AWS does not run traditional Ethernet; it runs a **software-defined
network** on the Nitro cards (Chapter 1 §12, Chapter 75). Crucially, AWS *removes* most L2 attacks
by design:

- **The VPC does not deliver traffic to a MAC that is not the legitimate owner.** You cannot put a
  NIC in promiscuous mode and sniff a neighbor's traffic; the SDN simply will not send it to you.
  ARP spoofing does not work because AWS controls the ARP responses and the mapping.
- **Source/destination checking** on ENIs drops packets whose source IP/MAC does not match the
  ENI (unless you disable it deliberately, e.g. for a NAT instance) — killing spoofing.
- So the classic L2 attacks (ARP spoofing, MAC flooding, sniffing) are *not viable in a standard
  VPC*. This is a genuine, underappreciated security benefit of the cloud SDN, and a reason the
  cloud threat model shifts *up* to the control plane and IAM (Chapter 6 §4.4).

The lesson, consistent with Part 0: **the cloud does not remove the concepts (MACs, broadcast
domains, subnets); it removes some of the L2 *attacks* by controlling the virtualized L2, and
moves the risk elsewhere.** You still design with segmentation (subnets, security groups), but you
no longer defend against ARP spoofing inside a VPC — a different, and mostly better, set of
concerns. Knowing *why* (the SDN owns the L2 mappings) is what lets you answer "can a compromised
instance sniff its neighbors?" correctly: in a standard VPC, no.

---

## 8. Hands-On Demonstration

### LAB 8.1 — Decode Frames and Demonstrate L2's Lack of Isolation

**Objective.** Decode real Ethernet frames, prove MAC spoofing is trivial, and observe (in a
controlled container network) how a switch forwards vs floods and why that matters for sniffing.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Inspect your L2 identity and neighbors.*

```bash
ip -br link                       # interfaces and MACs
ip neigh show                     # IP -> MAC cache
sudo tcpdump -e -n -c 10 -i any   # watch frames; note src/dst MAC and ethertype
```

Identify: your MAC, the broadcast MAC, an ARP frame (ethertype 0x0806, dst broadcast), and an
IPv4 frame (0x0800, unicast dst). Decode the EtherType bytes by hand (Chapter 7).

*Step 2 — Prove MAC spoofing is trivial (on a disposable interface).*

```bash
# Use a container to avoid disrupting your host networking:
docker run -it --rm --cap-add NET_ADMIN alpine sh -c '
  ip link show eth0 | grep ether
  ip link set eth0 down
  ip link set eth0 address 02:de:ad:be:ef:01
  ip link set eth0 up
  ip link show eth0 | grep ether
'
```

**Expected:** the MAC changes to your chosen value. **Security implication:** the "hardware
identity" is software-defined; MAC filtering is not a control.

*Step 3 — Observe switch forwarding vs flooding (container bridge as a switch).*

```bash
# Docker's default bridge is a virtual switch. Create three containers on it:
docker network create --driver bridge labl2 2>/dev/null
for n in a b c; do docker run -d --name l2$n --network labl2 --cap-add NET_RAW nicolaka/netshoot sleep 3600; done
# Get IPs/MACs:
for n in a b c; do echo -n "l2$n: "; docker exec l2$n ip -br addr show eth0; done

# On container C, sniff. On A, ping B. Does C see A<->B unicast traffic?
docker exec -d l2c tcpdump -e -n -w /tmp/cap.pcap
docker exec l2a ping -c 3 $(docker exec l2b hostname -i)
sleep 1
docker exec l2c sh -c 'tcpdump -e -n -r /tmp/cap.pcap 2>/dev/null | grep -c ICMP || echo 0'
```

**Expected:** container C sees the ARP broadcasts (flooded) but generally *not* the A↔B ICMP
unicast (the bridge forwards unicast only to B's port once the MAC is learned). This demonstrates
that a switch/bridge isolates unicast by default — which is *why* an attacker needs ARP spoofing
(Chapter 9) or MAC flooding to sniff, not just promiscuous mode.

*Step 4 — Reason about the attack (do not perform it against systems you do not own).*

Given Step 3, describe how MAC flooding would defeat the isolation: overflow the bridge's MAC
table so it floods all frames, then C's promiscuous capture sees A↔B traffic. Note that Docker's
bridge and real switches with **port security** resist this differently (§11).

**Security implications.** Write down: (a) why promiscuous mode alone is insufficient on a switch;
(b) what an attacker must additionally do to sniff (spoof/flood); (c) why AWS VPC (§7) makes both
infeasible; (d) the general lesson that L2 provides delivery, not isolation or authentication.

**Cleanup.**
```bash
for n in a b c; do docker rm -f l2$n; done; docker network rm labl2
```

---

## 9. Security Implications

- **Layer 2 provides local delivery, not security.** No authentication, no encryption; the FCS
  detects noise, not tampering. Integrity/confidentiality against an adversary must come from
  higher layers (TLS, Chapter 28).
- **MAC addresses are spoofable identifiers, not credentials.** MAC filtering is a speed bump.
- **A switch is an efficiency device, not a security boundary.** It trusts source MACs and floods
  when the CAM table is full or the destination is unknown — both are attack conditions.
- **The broadcast domain is the blast radius of L2 attacks** (ARP spoofing, MAC flooding, rogue
  DHCP); routers/VLANs/subnets bound it — segmentation limits L2 reach.
- **"Same LAN" ≠ "trusted."** On-path attackers within a broadcast domain can redirect and read
  traffic; this is the empirical basis of Zero Trust and of encrypting internal traffic.
- **The cloud SDN removes most L2 attacks** by controlling the virtualized L2 (no promiscuous
  sniffing, no ARP spoofing, source/dest checks) — shifting risk to the control plane and IAM.

---

## 10. Attack Scenarios

1. **MAC flooding (CAM overflow):** flood the switch with frames bearing thousands of bogus source
   MACs, overflowing the finite CAM table; the switch fails open and floods all traffic, letting a
   promiscuous attacker sniff the whole segment. Tool: `macof`. Defense: switch **port security**
   (limit MACs per port), and — decisively — the cloud SDN, which has no such failure mode.
2. **MAC spoofing:** claim a victim's MAC to receive its traffic or bypass MAC-based filtering.
   Trivial (§6.2). Defense: 802.1X port authentication, DHCP snooping + dynamic ARP inspection,
   and not relying on MAC identity.
3. **ARP spoofing/poisoning (Chapter 9):** the dominant L2 MITM — forge ARP replies so the victim
   sends the gateway's traffic to the attacker. Enabled by the trust in step 2 of §5's off-segment
   flow.
4. **Rogue DHCP (Chapter 15):** answer DHCP faster than the real server, handing victims an
   attacker-controlled gateway/DNS — an L2-adjacent MITM. Defense: DHCP snooping.
5. **VLAN hopping (Chapter 13):** escape one VLAN into another via switch-spoofing or double
   tagging, defeating VLAN segmentation. Defense: disable auto-trunking, set a non-default native
   VLAN.
6. **Physical/rogue device:** plugging an unauthorized device into a switch port to join the
   broadcast domain. Defense: 802.1X, port security, physical security.

Note that 1–5 are largely **neutralized inside a standard AWS VPC** (§7), which is why Part 7–8's
cloud network security focuses on segmentation and IAM rather than on these L2 attacks. Know them
because you will meet them on-prem, in hybrid environments, and in the exam-room of "why do we
encrypt internal traffic?"

---

## 11. Defensive Techniques

**On-prem / traditional switched networks:**

- **Port security** — limit the number of MACs per switch port and pin expected MACs; shut down
  the port on violation. Defeats MAC flooding and limits spoofing.
- **DHCP snooping** — the switch tracks legitimate DHCP leases and drops rogue DHCP replies on
  untrusted ports (Chapter 15).
- **Dynamic ARP Inspection (DAI)** — validates ARP against the DHCP-snooping binding table,
  dropping forged ARP (Chapter 9's defense).
- **802.1X** — authenticate devices to the port before granting network access; the real answer to
  "MAC is not a credential" (Chapter 62, RADIUS).
- **VLAN segmentation** — separate broadcast domains for different trust levels; disable
  auto-trunking; use a non-default native VLAN (Chapter 13).
- **Disable unused ports; physical security** — an unplugged, disabled port cannot host a rogue.

**Cloud (AWS VPC):**

- The SDN provides most of this for free: no promiscuous sniffing, ARP handled by AWS, **source/
  destination check** on ENIs (leave it enabled except for NAT/routing appliances).
- Segmentation is done with **subnets and security groups** (Chapters 75–76), not VLANs and port
  security.
- **Encrypt internal traffic anyway** (TLS/mTLS, Chapter 86) — defense in depth, and required if
  your threat model includes a compromised instance on the same subnet.

**Everywhere:**

- **Do not trust the LAN.** Encrypt and authenticate every hop (Zero Trust, Chapter 43). This is
  the durable lesson that survives every platform.

---

## 12. Production Architecture

How L2 concepts appear in real designs, and where the enforcement lives:

```
 ON-PREM / DATA CENTER              AWS VPC
 --------------------------          ----------------------------------
 broadcast domain = VLAN             broadcast-domain-like = subnet
 boundary = router / L3 switch       boundary = VPC router + route tables
 isolation = VLANs + port security   isolation = subnets + security groups + SDN
 anti-spoof = DAI + DHCP snooping    anti-spoof = ENI source/dest check (built in)
 device auth = 802.1X                device auth = IAM (control plane, not L2)
 sniffing risk = real (mitigate)     sniffing risk = removed by SDN
```

The architectural principle carried from Part 0: **name what enforces each property.** "Hosts in
subnet X cannot sniff subnet Y" is enforced by VLAN separation + a router on-prem, and by the SDN
+ subnet boundary in AWS. "A rogue device cannot join" is 802.1X on-prem and IAM + no physical
access in the cloud. When you design a segmented network (Chapters 13, 83), you are choosing
broadcast-domain boundaries and the mechanism that enforces them — the same "property invariant,
mechanism moves" pattern (Chapter 4 §7) applied at Layer 2.

---

## 13. Common Mistakes

1. **Treating MAC addresses as credentials** (MAC filtering as "security"). Spoofable in one
   command.
2. **Assuming the switch isolates traffic** — it isolates unicast for efficiency, fails open to
   flooding, and never authenticates.
3. **Trusting the LAN** — "it's internal so it's safe," ignoring on-path L2 attackers.
4. **Believing the FCS provides integrity against attackers** — it detects noise, not tampering.
5. **Leaving ENI source/dest check disabled** unnecessarily in AWS, re-enabling spoofing.
6. **Assuming promiscuous mode = sniffing everything** on a switch (it does not without spoofing/
   flooding).
7. **Flat networks** — one giant broadcast domain, so any compromise sees/attacks everything;
   segment by trust level.
8. **Carrying on-prem L2 fears into AWS** (defending against ARP spoofing inside a VPC where it
   cannot happen) *and* the reverse — assuming the cloud removes the need to encrypt internal
   traffic.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Host unreachable on the same subnet | ARP not resolving; wrong/stale ARP entry | `ip neigh show`; `ping` then recheck; `arping` |
| Intermittent connectivity for two hosts | duplicate IP or duplicate/spoofed MAC | `arping <ip>` (multiple replies = duplicate); check `ip neigh` for MAC flaps |
| Can reach same-subnet hosts but not the internet | default gateway / gateway-MAC issue | `ip route`; ARP the gateway; check §5 off-segment flow |
| Sniffer sees only broadcasts, not unicast | on a switch without spoofing/flooding (expected) | this is normal switched behavior (§4.4, Lab 8.1) |
| AWS instance can't do NAT/routing | ENI source/dest check enabled | disable source/dest check on the appliance ENI |
| Unexpected traffic visible to a host | switch flooding (CAM overflow) or a hub, or ARP spoofing | check CAM table utilization; look for MAC flapping; DAI logs |
| MTU/large-packet issues | frame size vs MTU (Chapter 22) | `ip link` MTU; `ping -M do -s <size>` |

---

## 15. Practical Lab

Lab 8.1 is in §8. Register it in the lab index. Extension: on a machine with a real (non-cloud)
NIC, capture with `tcpdump -e` during normal use and catalogue every distinct EtherType you see
(IPv4, IPv6, ARP, possibly LLDP/STP), decoding each type field by hand. This builds the frame
literacy Chapter 24 assumes.

---

## 16. Exercises

### Concept questions

**8.1** Explain the difference between a MAC address and an IP address in terms of scope. Which
one changes at each router hop, and which stays the same end to end? Why?

**8.2** Why is a switch not a security device? Describe its learning and forwarding behavior and
the two conditions under which it floods.

**8.3** Explain the distinction between a collision domain and a broadcast domain, and where a
switch, a hub, and a router each fit.

**8.4** Why is the Frame Check Sequence not a security control? What layer provides integrity
against an adversary?

**8.5** In §5's off-segment flow, when host A sends to 8.8.8.8, what is the destination MAC and
what is the destination IP? Explain why they differ and what attack exploits this.

### Debugging problems

**8.6** Two servers on the same subnet intermittently lose connectivity to each other, and
`ip neigh` shows the MAC for one of them changing back and forth. Give the two most likely causes
and how you would distinguish them.

**8.7** An AWS NAT instance you built forwards no traffic despite correct routing and security
groups. What L2/L3 setting is the likely culprit, and why?

**8.8** A packet capture on a switched corporate network suddenly shows you traffic between two
*other* hosts. List the two most likely explanations and how you would confirm which.

### Security scenarios

**8.9** A colleague proposes MAC-address allow-listing to restrict which devices can use a
sensitive network segment. Evaluate this control and propose what you would actually do.

**8.10** You are asked "can a compromised EC2 instance sniff traffic of other instances in the
same subnet?" Answer precisely for a standard VPC, explain the mechanism, and state what would
change your answer.

### Architecture questions

**8.11** Design the segmentation for an on-prem network with three trust tiers (public-facing,
internal apps, sensitive data). Specify broadcast-domain boundaries, the L2 controls at each, and
how you would translate the same design to an AWS VPC.

**8.12** Explain, to a team migrating from on-prem to AWS, which of their existing L2 security
controls become unnecessary, which have cloud equivalents, and which concerns are entirely new.

### Hands-on exercises

**8.13** Capture and decode (by hand from `-X`/`-e` output) one ARP frame and one IPv4 frame,
identifying every field of the Ethernet header including the EtherType.

**8.14** Demonstrate on a container bridge that unicast is not visible to a third container by
default, and explain what an attacker would need to do to change that.

**8.15** Change a container's MAC and show that it still communicates, proving the MAC is not tied
to identity or authorization on that network.

### Interview questions

**8.16** "Walk me through what happens at Layer 2 when a host sends a packet to another host on
the same subnet, versus to a host on the internet."

**8.17** "Why isn't MAC filtering a real security control?"

**8.18** "Can one tenant sniff another's traffic in a public cloud VPC? Explain your answer at the
mechanism level."

**8.19** "What is a broadcast domain, and why does segmenting it matter for security?"

**8.20** "Which on-prem Layer 2 attacks stop being relevant in AWS, and why? What replaces the
defenses?"

---

## 17. Summary

- **Layer 2 delivers frames between devices on the same segment, addressed by MAC, with no
  authentication and no encryption.** It is delivery, not security.
- A **MAC address** is a 48-bit, local-scope, trivially spoofable identifier — never a credential.
  It changes at every router hop; the **IP address stays constant end to end** (Chapter 12).
- An **Ethernet frame** wraps the IP packet with dst/src MAC + EtherType (0x0800 IPv4, 0x0806 ARP,
  0x86DD IPv6, 0x8100 VLAN) + FCS; the **FCS detects noise, not tampering**.
- A **switch** learns MAC→port from source MACs and forwards unicast efficiently, but **floods
  when the CAM table overflows or the destination is unknown**, and trusts source MACs — both are
  attack conditions (MAC flooding, MAC spoofing). A switch is not a security device.
- The **broadcast domain is the blast radius of L2 attacks**; routers and VLANs/subnets bound it —
  segmentation limits L2 reach.
- The key L2/L3 rule: **destination MAC = next hop on the local segment; destination IP = final
  target.** For remote traffic the MAC points at the gateway, the IP at the destination — the
  basis of routing (Chapter 12) and of ARP-spoofing MITM (Chapter 9).
- **"Same LAN" ≠ "trusted"** — on-path L2 attackers can redirect and read traffic, the empirical
  root of Zero Trust and of encrypting internal traffic.
- **The cloud SDN removes most L2 attacks** (no promiscuous sniffing, ARP controlled, ENI
  source/dest checks), shifting the threat model up to the control plane and IAM — a genuine cloud
  security benefit, with the concepts (MAC, subnet, broadcast domain) retained.

---

## 18. Knowledge Check

1. What is the scope of a MAC address, and what changes it at each hop? (§3, §5)
2. Decode the EtherType `0x0806`. What protocol, and how is that frame addressed? (§4.2)
3. Under what two conditions does a switch flood? (§4.4)
4. Why is a switch not a security device? (§4.4, §9)
5. What is the destination MAC when sending to an off-subnet IP, and why? (§5)
6. Why is the FCS not a security control? (§4.2)
7. What bounds the blast radius of an L2 attack? (§4.5)
8. Why can't a standard EC2 instance sniff its neighbors? (§7)
9. Name three on-prem L2 defenses and their cloud equivalents. (§11, §12)
10. Why is "same LAN = trusted" false? (§9)

---

## 19. Further Exploration

- `man ip-link`, `man ip-neigh` — the modern Linux L2 tooling.
- Capture with `tcpdump -e` on a real LAN and catalogue EtherTypes; then read the same capture in
  Wireshark's Ethernet II dissector and match fields (bridge to Chapter 24).
- Read the AWS VPC networking docs section on ENIs and source/destination checks — the concrete
  mechanism behind §7.
- IEEE OUI lookup (e.g. Wireshark's built-in, or the IEEE registry): identify vendors from MACs in
  a capture — a real asset-discovery/forensics skill.
- For the attack mechanics (in a lab you own): read about `macof` (MAC flooding) and Cisco
  port-security, DHCP snooping, and Dynamic ARP Inspection — the on-prem defenses you will
  recommend in hybrid environments.

---

## Solutions

### 8.1
A MAC address is *local-scope*: it identifies a NIC on the current broadcast domain and is
meaningful only there. An IP address is *end-to-end scope*: it identifies the source and final
destination across the whole internetwork. At each router hop, the router strips the incoming
Ethernet frame and builds a new one with a new source MAC (its own outgoing interface) and a new
destination MAC (the next hop), so **the MAC addresses change at every hop**. The IP addresses in
the packet **stay the same end to end** (except the TTL decrements, Chapter 12), because they
name the ultimate endpoints, not the local delivery. Why: L2 solves "hand this frame to the next
device on this wire," which is a per-segment problem; L3 solves "get this packet to that host
somewhere in the world," which is an end-to-end problem. Different scopes, different addresses.

### 8.2
A switch's job is efficient delivery, not policy. It **learns** by recording the source MAC of
every frame against the port it arrived on (building the CAM table), and **forwards** by looking
up the destination MAC: if known, it sends only out that one port (unicast efficiency); if the
destination is a broadcast, or if the destination MAC is unknown or the CAM table is full, it
**floods** the frame out every port except the source. It authenticates nothing — it trusts the
source MAC it sees, so a host can spoof another's MAC or overflow the table. The two flooding
conditions (unknown/broadcast destination, and CAM overflow) are exactly the attack conditions:
MAC flooding forces overflow to make the switch flood everything (enabling sniffing), and MAC
spoofing poisons the table. So the switch provides no confidentiality, integrity, or
authentication guarantees; it is an efficiency device, and security must come from elsewhere
(port security, 802.1X, encryption, or the cloud SDN).

### 8.3
A **collision domain** is the set of devices that could collide if they transmitted at the same
time on a shared medium. A hub is a single collision domain (all ports share the medium,
half-duplex). A switch gives each port its own collision domain (full-duplex point-to-point), so
collisions are essentially eliminated — this is mostly historical now. A **broadcast domain** is
the set of devices that receive each other's broadcast frames. A switch (or a set of interconnected
switches) forms one broadcast domain; a VLAN carves a switch into multiple broadcast domains
(Chapter 13). A **router** is the boundary of a broadcast domain: broadcasts do not cross it.
So: a hub = one collision + one broadcast domain; a switch = many collision domains + one
broadcast domain (per VLAN); a router = separates broadcast domains. Security relevance: the
broadcast domain is the reach of L2 attacks, so routers/VLANs bound them.

### 8.4
The FCS is a CRC-32 designed to detect *accidental* corruption — bits flipped by electrical noise
or a faulty cable — and the NIC silently drops frames whose FCS does not match. It is not a
security control because it is not keyed: an attacker who modifies a frame simply recomputes the
correct CRC over the altered contents, and the receiver accepts it. CRC provides no evidence of
*who* produced the frame or whether it was *deliberately* altered. Integrity and authenticity
against an adversary require a keyed mechanism — a MAC (message authentication code) or a
signature — which at the transport layer is provided by TLS's authenticated encryption (Chapter
28), and at L2 optionally by MACsec (802.1AE). The general principle: error *detection* (CRC,
checksums) is not error *authentication*; only a secret-keyed construct resists a deliberate
attacker.

### 8.5
When A sends to 8.8.8.8 (off-subnet), the **destination MAC is the default gateway's MAC** (the
next hop on A's local segment), while the **destination IP is 8.8.8.8** (the final target,
unchanged). They differ because L2 addresses the next device on the wire and L3 addresses the
ultimate endpoint: A cannot put an L2 frame directly onto a segment 8.8.8.8 is not on, so it hands
the frame to the gateway, which will route the IP packet onward (building new L2 frames each hop).
The attack that exploits this is **ARP spoofing** (Chapter 9): A learns the gateway's MAC by ARP
and trusts the reply, so an attacker who forges an ARP reply ("the gateway is at *my* MAC") makes
A send all its off-subnet traffic to the attacker's MAC — an on-path man-in-the-middle at Layer 2.
The vulnerability is precisely that step 2 (A ARPs for the gateway and trusts the answer) is
unauthenticated.

### 8.6
Both symptoms — intermittent connectivity and a MAC that flaps between values in the ARP cache —
point to either (1) a **duplicate IP address**: two hosts configured with the same IP, so ARP
replies alternate and traffic goes to whichever answered last; or (2) **ARP spoofing / a spoofed
MAC**: an attacker sending forged ARP replies for the victim's IP, causing the mapping to flap
between the real and the attacker's MAC. Distinguish them: `arping <ip>` — a duplicate IP produces
replies from **two different MACs consistently**, and both are likely legitimate vendor OUIs and
present on the network with distinct hosts; ARP spoofing typically shows one MAC that is the
attacker's (possibly a locally-administered OUI), correlated with the attacker's presence, and DAI
(if enabled) logs violations. Check both hosts' configured IPs (`ip addr`), look at the OUIs of
the flapping MACs, and inspect switch/DAI logs. Duplicate IP is a misconfiguration; flapping to a
single suspicious MAC is an attack.

### 8.7
The likely culprit is the **ENI's source/destination check**, which AWS enables by default. This
check drops any packet whose source or destination IP does not match the ENI's own address — which
is exactly what a NAT/router instance must do: it *forwards* packets whose destination is some
other host. With source/dest check enabled, the NAT instance's forwarded packets are silently
dropped, so no traffic flows despite correct route tables and security groups. Fix: disable
source/destination checking on the NAT instance's ENI (`modify-instance-attribute
--no-source-dest-check`). This is the one place you deliberately turn off an anti-spoofing control
(§11), because the appliance's legitimate function *is* to handle traffic not addressed to itself
— and it is a reminder that the VPC's built-in anti-spoofing (which normally protects you) must be
relaxed for routing appliances.

### 8.8
On a *switched* network you should normally see only your own unicast traffic plus broadcasts, so
seeing two other hosts' unicast means the switch is flooding it to your port. Two most likely
explanations: (1) **CAM table overflow / MAC flooding attack** — the switch's MAC table is full
(possibly deliberately, via `macof`), so it fails open and floods all unicast like a hub; or (2)
**ARP spoofing** — an attacker has poisoned ARP so the traffic is being deliberately routed
through a man-in-the-middle (possibly you are receiving a copy), or you are the target of a
mirror/SPAN misconfiguration. Confirm: check switch CAM-table utilization and for MAC-table
overflow/flooding alarms (points to flooding); check `ip neigh`/ARP tables and DAI logs for
forged ARP and MAC flapping (points to ARP spoofing); check whether a SPAN/mirror port was
misconfigured to your port (benign but leaky). If neither and it persists, treat it as a potential
compromise and investigate the source of the excess MACs or forged ARP.

### 8.9
MAC allow-listing is weak because a MAC address is trivially spoofable (`ip link set address`,
one command — §6.2), so an attacker who observes a permitted MAC (easy on a shared segment, or via
the OUI on the device sticker) simply clones it and is allow-listed. It also breaks legitimately
(NIC replacement, VMs, randomized MACs) and creates operational burden for little gain. It raises
the bar only against the utterly unsophisticated. What I would actually do: **802.1X port-based
authentication** (Chapter 62) so devices authenticate with real credentials/certificates before
the port grants access; combine with **VLAN segmentation** to isolate the sensitive segment,
**DHCP snooping + Dynamic ARP Inspection** to prevent spoofing, and **encryption of the traffic**
(so even an on-path attacker gains nothing). In the cloud, the equivalent is subnet isolation +
security groups + IAM for device/workload identity, not MAC lists. MAC allow-listing can remain as
a minor inventory/defense-in-depth layer, never as the control.

### 8.10
For a **standard AWS VPC, the answer is no**: a compromised instance cannot sniff other instances'
traffic in the same subnet. Mechanism: AWS does not run a shared-medium Ethernet; the VPC is a
software-defined network implemented on the Nitro cards, and the SDN delivers a frame only to the
ENI that legitimately owns the destination address. Putting the NIC in promiscuous mode shows
nothing extra, because the SDN never sends a neighbor's unicast to your ENI; ARP is handled by AWS
(you cannot poison it); and ENI source/destination checks drop spoofed packets. So the classic L2
sniffing prerequisites (a shared medium or a floodable switch, plus ARP spoofing) do not exist.
What would change the answer: if you deliberately configure **traffic mirroring** (VPC Traffic
Mirroring) to your instance, or run an overlay/CNI inside the instances that re-creates a shared
L2 (e.g. certain container networks) where the tenant-visible traffic is not protected by the SDN,
or if the workloads send plaintext to a shared component the attacker controls. The precise
statement: at the *VPC* layer, no; encrypt internal traffic anyway (defense in depth) because the
guarantee is about the network fabric, not about a compromised shared service.

### 8.11
On-prem: three broadcast domains, one per tier, implemented as **three VLANs** (or separate
physical switches), with a **router/L3 firewall** between them enforcing which tiers may talk
(public→app allowed on specific ports, app→data allowed on the DB port, no direct public→data).
L2 controls in each VLAN: **port security** (limit/pin MACs) to stop flooding/spoofing, **DHCP
snooping + DAI** to stop rogue DHCP and ARP spoofing, **802.1X** to authenticate devices onto
ports, disabled unused ports, and a non-default native VLAN with auto-trunking off to prevent VLAN
hopping (Chapter 13). Encrypt inter-tier traffic. AWS translation: three **subnets** (or subnet
groups across AZs) — public, private-app, private-data; **route tables** control reachability
(only public has an IGW route; data has no internet route); **security groups** enforce
tier-to-tier rules by referencing each other's SG (app SG allowed to data SG on 5432 only); the
**SDN + ENI source/dest checks** provide the anti-spoofing that port security/DAI provided;
device/workload identity is **IAM**, not 802.1X. The design — broadcast-domain boundaries per
trust tier + a controlled path between them — is identical; only the enforcing mechanisms move
(Chapter 4 §7).

### 8.12
**Become unnecessary** (the VPC SDN handles them): defenses against ARP spoofing (Dynamic ARP
Inspection), MAC flooding (port security/CAM protection), promiscuous sniffing, and rogue DHCP —
because AWS controls the virtualized L2, delivers traffic only to the legitimate owner, handles
ARP/DHCP, and enforces ENI source/dest checks. **Have cloud equivalents**: VLAN segmentation →
subnets; router/L3 firewall between tiers → route tables + security groups + NACLs; 802.1X device
authentication → IAM (workload/instance identity via roles); network access control →
security-group references and IAM. **Entirely new concerns**: the **control plane and IAM become
the perimeter** (an over-permissioned role reads data over the API with no network access —
Chapter 6 §4.4); **misconfiguration** (public subnets, public IPs, open SGs, disabled source/dest
check) becomes the dominant risk; **VPC-level constructs** (endpoints, peering, Transit Gateway —
Chapter 77) and their routing/exposure; and the need to **encrypt internal traffic** as defense in
depth despite the SDN. Net: fewer L2 worries, but a large new surface in identity and cloud
configuration.

### 8.13
Expected: capture with `sudo tcpdump -e -X -c 2 -i any 'arp or ip'`. For the **ARP frame**, decode
the Ethernet header from the `-X` hex: first 6 bytes = destination MAC (for an ARP *request*,
`ff ff ff ff ff ff` = broadcast), next 6 = source MAC (the sender's NIC), next 2 = EtherType
`08 06` = ARP; then the ARP payload (Chapter 9) follows. For the **IPv4 frame**: first 6 bytes =
destination MAC (a specific unicast MAC, e.g. the gateway or peer), next 6 = source MAC, next 2 =
`08 00` = IPv4; then the IPv4 header (which you decode with Chapter 7 §5). The deliverable is
naming every Ethernet-header field (dst MAC, src MAC, EtherType) from the raw bytes and confirming
the EtherType against the `-e` textual decode. Bonus: note the ARP frame is broadcast while the
IPv4 unicast frame is addressed to a specific MAC.

### 8.14
Expected: create a bridge network with three containers (Lab 8.1 Step 3), start a capture on
container C, generate unicast traffic between A and B (ping), and show C's capture contains the
ARP broadcasts but not the A↔B ICMP unicast once the bridge has learned B's MAC. Explanation: the
Linux bridge (a virtual switch) learns MAC→port and forwards A→B unicast only to B's veth,
isolating it from C — so promiscuous capture on C sees broadcasts but not the unicast. To change
that, an attacker on C would need to (1) **ARP-spoof** A and/or B so their traffic is sent to C's
MAC (man-in-the-middle), or (2) **flood the bridge's MAC table** so it fails open and floods all
frames (if the bridge lacks protections). This proves switched isolation is real for honest
traffic but defeatable by active L2 attacks — hence the need for DAI/port-security on-prem, and
the relevance of the SDN removing these vectors in AWS.

### 8.15
Expected: in a container (or on a disposable NIC), record the original MAC, bring the interface
down, set a new MAC (`ip link set eth0 address 02:...`), bring it up, and show that the container
can still ping its gateway/peers and be reached — communication continues with the new MAC because
the switch/bridge simply relearns MAC→port and ARP relearns IP→MAC; nothing on the network tied
identity or authorization to the original MAC. This proves the MAC is a mutable, network-layer
delivery label, not a credential — so any control that trusts the MAC (MAC filtering) is bypassed
by exactly this operation. (Note: on AWS the ENI's MAC is managed and changing the guest's MAC
does not change what the SDN delivers — a nice contrast reinforcing §7.)

### 8.16
Same-subnet: the sending host's IP stack compares the destination IP to its own subnet (using the
mask, Chapter 10), concludes the target is local, resolves the target's MAC via the ARP cache or
an ARP request (Chapter 9), builds an Ethernet frame with dst = target's MAC, src = its own MAC,
EtherType 0x0800, carrying the IP packet, and sends it; the switch forwards the frame only to the
target's port; the target's NIC accepts it and hands the IP packet up. Off-subnet (internet): the
stack concludes the target is remote, so it resolves the **default gateway's** MAC (not the
target's), builds a frame with dst = gateway MAC, src = its own MAC, payload IP packet with dst IP
= the final remote target (unchanged); the gateway/router receives it, strips the frame, routes
the IP packet toward the destination, building new L2 frames at each hop. Key contrast: the **dst
MAC is the next hop (target or gateway); the dst IP is always the final target** — and the MAC
changes every hop while the IP stays constant. Bonus: mention this is why ARP spoofing the gateway
enables MITM of all off-subnet traffic.

### 8.17
Because a MAC address is not a secret and is trivially changed. Any host can set its NIC's MAC to
any value in one command (the address is software-configurable; the locally-administered bit
exists precisely for this), so an attacker who observes an allowed MAC — easy on a shared segment,
from the device label, or from prior traffic — clones it and is admitted. There is no
cryptographic proof of possession, no challenge, nothing an attacker cannot replay. MAC filtering
also breaks legitimately (NIC swaps, VMs, privacy MAC randomization) and adds management overhead.
It stops only the most casual unauthorized device. Real device/network authentication uses
credentials that cannot be trivially cloned — **802.1X** with certificates or credentials
(Chapter 62), and in the cloud, **IAM**-based workload identity. MAC filtering is at best a minor
inventory/defense-in-depth layer, never the control.

### 8.18
In a standard public-cloud VPC (e.g. AWS), **no**, at the fabric level. The mechanism: the VPC is
a software-defined network, not a shared Ethernet medium or a physical switch. Each instance's
ENI has addresses the SDN knows, and the fabric delivers a frame only to the ENI that legitimately
owns the destination address — it never places another tenant's (or even another same-subnet
instance's) unicast onto your ENI. Consequently promiscuous mode yields nothing extra, ARP is
mediated by AWS so it cannot be poisoned, and ENI source/destination checks drop spoofed packets,
so the L2 prerequisites for sniffing (shared medium or floodable switch + ARP spoofing) simply do
not exist. Caveats that would change it: if traffic mirroring is explicitly configured to the
attacker's instance, if an overlay network inside the instances re-creates an unprotected shared
L2, or if plaintext is sent to a shared service the attacker controls. Hence the guarantee is
about the *fabric*; you still encrypt internal traffic as defense in depth. Contrast with on-prem
switched networks, where sniffing via MAC flooding or ARP spoofing is real and must be defended.

### 8.19
A broadcast domain is the set of devices that receive one another's broadcast frames — one
logical segment, bounded by routers (and subdivided by VLANs). It matters for security because it
is the **blast radius of Layer 2 attacks**: ARP spoofing, MAC flooding, rogue DHCP, and broadcast/
multicast-based discovery all reach exactly the devices in the same broadcast domain and stop at
the router. A large, flat broadcast domain means any single compromised or malicious host can
attempt to intercept, redirect, or enumerate traffic for *every* other host in it. Segmenting the
network into smaller broadcast domains by trust level (VLANs on-prem, subnets in the cloud) bounds
that reach: a compromise in the public tier's domain cannot ARP-spoof the data tier if they are in
separate domains behind an L3 boundary. It is the network-layer instance of blast-radius
containment (Chapter 1 §5.4) and a foundation of defense in depth and Zero Trust.

### 8.20
Stops being relevant in AWS: **MAC flooding/CAM overflow** (no shared switch with a floodable
table), **ARP spoofing** (AWS mediates ARP; you cannot poison the mapping), **promiscuous
sniffing** of neighbors (the SDN never delivers others' unicast to your ENI), **rogue DHCP** (AWS
provides DHCP; you cannot answer for the subnet), and **VLAN hopping** (no 802.1Q trunks to
abuse). Why: AWS replaces physical switched Ethernet with a software-defined network on Nitro that
controls address→ENI delivery and enforces ENI source/destination checks, removing the shared
medium and the trust-the-source-MAC behaviors these attacks exploit. What replaces the defenses:
segmentation via **subnets + route tables**, filtering via **security groups + NACLs**,
anti-spoofing via **built-in ENI source/dest checks**, device/workload authentication via **IAM**
(instance/task roles) rather than 802.1X, and **encryption of internal traffic** as defense in
depth. Net: the L2 attack surface largely disappears, replaced by a focus on cloud configuration
and identity — the cloud's characteristic risk shift.

---

*Next: Chapter 9 — ARP: The Glue Between Layer 2 and Layer 3, and How It Is Poisoned. We take the
"A ARPs for the gateway and trusts the reply" step from §5 and turn it into both a complete
protocol walkthrough and the canonical local-network man-in-the-middle attack — and see exactly
why the cloud SDN neutralizes it.*
