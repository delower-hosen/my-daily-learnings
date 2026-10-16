# Chapter 13 — Switching, VLANs, Trunks, and Layer 2 Segmentation

---

## 1. Why This Matters

Chapter 8 introduced the switch and the broadcast domain; Chapter 12 introduced routing between
networks. This chapter fills the gap between them: **how one physical switch is carved into many
isolated networks (VLANs), how those VLANs travel between switches (trunks), and how attackers escape
VLAN isolation (VLAN hopping).** For a cloud security engineer this matters for three reasons:

1. **VLANs are the on-prem ancestor of cloud subnets/security groups.** Understanding VLAN
   segmentation — its goals, its mechanisms, and its failure modes — is understanding what cloud
   segmentation replaced and *why the cloud does it differently (and often better)*. When you design
   VPC segmentation (Chapters 75–76, 83), you are solving the same problem VLANs solved, with a
   different, software-defined mechanism.
2. **You will work in hybrid and on-prem environments.** Data centers, corporate networks, and the
   on-prem side of hybrid cloud (Chapter 77) run on VLANs. Auditing segmentation, spotting VLAN
   hopping exposure, and reasoning about trust zones require this knowledge.
3. **The segmentation *principle* is platform-independent and central to security.** "Separate systems
   by trust level so a compromise in one zone cannot reach another" (Chapter 1 §5.4 blast radius) is
   implemented by VLANs on-prem, subnets/SGs in the cloud, and NetworkPolicy in Kubernetes (Chapter
   104). The mechanism changes; the principle — and the review question "is this properly segmented?"
   — does not.

The core idea: **a VLAN turns one physical switch into several logically separate switches, each its
own broadcast domain, so traffic in one VLAN cannot reach another without going through a router (and
its firewall). This is Layer 2 segmentation, and it is a foundational security control — undermined by
misconfiguration (VLAN hopping) exactly as cloud segmentation is undermined by over-broad security
groups.**

This chapter also closes a recurring thread: the cloud SDN (Chapters 8, 9) removes many L2 attacks,
and here we see specifically how it replaces VLANs with subnets — completing the "concepts stay,
mechanisms move" story for Layer 2.

---

## 2. Prerequisites

- Chapter 8 (switches, broadcast domains, the CAM table, MAC flooding) — VLANs subdivide the broadcast
  domain introduced there.
- Chapter 12 (routing — VLANs are joined by routers) and Chapter 10 (subnets — one VLAN usually maps
  to one IP subnet).
- Chapter 1 §5.4 (blast radius / isolation) — segmentation is blast-radius containment at Layer 2.

---

## 3. Mental Model

**A VLAN (Virtual LAN) is a broadcast domain defined in software on a switch rather than by physical
wiring. One switch can host many VLANs; ports assigned to VLAN 10 form one logical network, ports in
VLAN 20 another, and the two cannot communicate at Layer 2 — only through a router.**

```
   ONE physical switch, carved into three logical switches (VLANs):

   +------------------------------------------------------------------+
   |  Switch                                                           |
   |   VLAN 10 (finance):   ports 1,2,3   -> broadcast domain A        |
   |   VLAN 20 (dev):       ports 4,5,6   -> broadcast domain B        |
   |   VLAN 30 (guest):     ports 7,8     -> broadcast domain C        |
   |                                                                  |
   |   A host in VLAN 10 broadcasts -> only VLAN 10 ports hear it.      |
   |   VLAN 10 <-> VLAN 20 traffic MUST go through a router (L3),        |
   |     where a firewall/ACL can permit or deny it.                    |
   +------------------------------------------------------------------+
```

Three ideas do the work:

1. **A VLAN = a broadcast domain = (usually) one IP subnet.** VLAN 10 might be `10.0.10.0/24`, VLAN 20
   `10.0.20.0/24`. Same-VLAN hosts talk directly (L2, ARP); cross-VLAN requires routing (Chapter 12).
   This maps cleanly onto cloud: **a VLAN is the on-prem analogue of a subnet.**
2. **Inter-VLAN traffic is a choke point.** Because cross-VLAN traffic must traverse a router, that
   router (with its ACLs/firewall) is a natural place to enforce which zones may talk — the on-prem
   analogue of security groups controlling subnet-to-subnet traffic.
3. **VLAN membership is enforced by the switch.** A port is "in" a VLAN by configuration; frames are
   tagged (on trunks) with a VLAN ID so switches keep them separate. The isolation is only as good as
   the switch configuration — misconfiguration is the vulnerability (VLAN hopping, §4.4).

**The security framing:** VLANs implement segmentation — separating systems by trust level so a
breach in one zone (guest Wi-Fi, dev) cannot reach another (finance, production) at Layer 2. It is
blast-radius containment (Chapter 1 §5.4) at the network layer. The same review question applies as in
the cloud: *are systems of different trust levels actually isolated, and is the path between them
controlled and minimal?*

---

## 4. Fundamentals

### 4.1 VLANs and the 802.1Q tag

A VLAN is identified by a 12-bit **VLAN ID** (1–4094; 0 and 4095 reserved), giving up to 4094 VLANs. On
a single switch, VLAN membership is just port configuration. But when a frame must travel *between*
switches over one physical link carrying multiple VLANs, the switch adds an **802.1Q tag** to the
Ethernet frame identifying its VLAN:

```
   Untagged frame (access port): [ dst MAC | src MAC | EtherType | payload | FCS ]
   802.1Q-tagged frame (trunk):  [ dst MAC | src MAC | 0x8100 | TAG | EtherType | payload | FCS ]
                                                        |______|  |__|
                                                        TPID       12-bit VLAN ID (+ priority bits)
```

You met EtherType `0x8100` in Chapter 8 §4.2 — it signals "an 802.1Q VLAN tag follows." The tag lets a
single link carry many VLANs' traffic while keeping them separate: the receiving switch reads the tag
and delivers the frame only to ports in that VLAN.

### 4.2 Access ports vs trunk ports

Two port types, and confusing them is where attacks come from:

- **Access port:** belongs to exactly one VLAN, carries *untagged* frames, connects to an end device
  (a PC, server, printer). The device is unaware of VLANs; the switch adds/removes the VLAN association
  internally. Most ports are access ports.
- **Trunk port:** carries *tagged* frames for *multiple* VLANs, connecting switch-to-switch or
  switch-to-router (or to a hypervisor host running many VMs in different VLANs). The tag (§4.1) keeps
  the VLANs separated over the shared link.

The security-critical distinction: **an access port should never behave like a trunk.** If an attacker
on an access port can convince the switch to treat their port as a trunk (switch spoofing, §4.4), they
gain access to *all* VLANs — defeating segmentation entirely. This is why disabling dynamic trunking
(DTP) and explicitly configuring access ports is a core hardening step.

### 4.3 The native VLAN and inter-VLAN routing

- **Native VLAN:** on a trunk, one VLAN's frames are sent *untagged* (historically for compatibility) —
  the "native" VLAN. By default this is VLAN 1. The native VLAN is a security liability because
  untagged frames on a trunk are assumed to belong to it, which enables **double-tagging attacks**
  (§4.4). Best practice: change the native VLAN to an unused, dedicated VLAN and never use VLAN 1.
- **Inter-VLAN routing:** to let VLAN 10 talk to VLAN 20, traffic goes to a router (a dedicated router,
  a Layer 3 switch, or a "router-on-a-stick" — one trunk carrying all VLANs to a router). At that L3
  boundary, **ACLs/firewall rules enforce which VLANs may communicate** — the on-prem equivalent of
  security-group rules between subnets (Chapter 76). This is where segmentation policy is enforced;
  the VLANs provide isolation, the router provides controlled connectivity.

### 4.4 VLAN hopping: escaping the segmentation

Two classic attacks let an attacker on one VLAN reach another, defeating the isolation:

**1. Switch spoofing (DTP abuse):**

```
   Cisco's Dynamic Trunking Protocol (DTP) can auto-negotiate whether a port becomes a trunk.
   If an access port is left in "dynamic auto/desirable" mode:
     Attacker's device sends DTP frames pretending to be a switch wanting a trunk.
     The switch forms a trunk with the attacker's port.
     -> The attacker now receives tagged frames for ALL VLANs -> full segmentation bypass.
```

Defense: **disable DTP; explicitly configure access ports as access (`switchport mode access`,
`switchport nonegotiate`).** An access port that cannot become a trunk cannot be switch-spoofed.

**2. Double tagging:**

```
   Attacker (on the native VLAN, say VLAN 1) sends a frame with TWO 802.1Q tags:
     outer tag = native VLAN (1),  inner tag = target VLAN (20).
   First switch: strips the outer tag (it matches the native VLAN, sent untagged on the trunk),
     forwards the frame with the inner tag (20) still present.
   Second switch: reads the inner tag (20) and delivers the frame into VLAN 20.
   -> The attacker injected a frame into VLAN 20 (one-way; useful for some attacks).
```

Defense: **change the native VLAN to a dedicated unused VLAN, do not put hosts on the native VLAN, and
enable tagging of the native VLAN** so the outer-tag-stripping trick fails. Double tagging is one-way
(the attacker can send into the target VLAN but not easily receive), but it enables injection attacks.

Both attacks exploit *misconfiguration or insecure defaults* (auto-trunking on, VLAN 1 as native), not
a fundamental VLAN flaw — the recurring pattern (Chapters 5, 9): the mechanism is sound, the defaults
and the config are the risk.

### 4.5 Private VLANs and micro-segmentation

Standard VLANs isolate *between* VLANs but not *within* one — all hosts in a VLAN can talk to each
other. **Private VLANs (PVLANs)** add intra-VLAN isolation:

- **Isolated ports** can talk only to the router (promiscuous port), not to each other — used for, e.g.,
  hosting many customers who share a subnet but must not reach one another.
- **Community ports** can talk within their community and to the router, but not to other communities.

PVLANs are the on-prem move toward **micro-segmentation** — controlling east-west traffic even within a
segment, the same goal as Kubernetes NetworkPolicy (Chapter 104) and cloud security-group-to-SG rules.
The principle: default isolation, explicit connectivity, even inside a subnet — which the cloud
achieves natively with SGs (every instance's SG independently controls its traffic).

### 4.6 How the cloud replaces VLANs

In a VPC (Chapter 75), there are **no VLANs and no 802.1Q tags in the customer-visible model.** The SDN
provides segmentation differently:

```
   ON-PREM                          CLOUD (VPC)
   VLAN (broadcast domain)     ->   subnet (Chapter 10)
   inter-VLAN routing + ACLs   ->   route tables (Chapter 12) + security groups/NACLs (Chapter 76)
   access/trunk ports          ->   (none — the SDN handles delivery per-ENI)
   VLAN hopping                ->   (not applicable — no trunks to abuse)
   private VLAN / micro-seg    ->   security groups (per-instance, default micro-segmentation)
```

The consequences, completing the Chapter 8–9 story:

- **VLAN hopping does not exist in a VPC** — there are no trunks or DTP to abuse; the SDN delivers
  frames per-ENI based on the true topology. Another L2 attack removed by the cloud.
- **Security groups give per-instance micro-segmentation by default** — each instance's traffic is
  controlled by its own SG, which is *stronger* than standard VLANs (which isolate only between VLANs,
  not within) and closer to PVLANs, without extra configuration.
- **Segmentation is defined in software you audit** (subnets + SGs + routes as IaC — Chapters 75–76,
  88), rather than in switch port configs — more auditable and less prone to the config-drift that
  causes VLAN hopping.

The lesson, one more time: **the cloud keeps the segmentation *principle* and replaces the VLAN
*mechanism* with subnets and security groups — generally improving auditability and removing an attack
class.** Knowing VLANs lets you translate on-prem segmentation designs to the cloud and reason about
hybrid environments where both coexist.

---

## 5. Deep Technical Explanation: Segmentation as a Security Architecture

VLANs (and their cloud successors) exist to implement **network segmentation**, one of the most
important security architectures (Chapter 43). The reasoning, which is platform-independent:

**Without segmentation (a flat network):** every host shares one broadcast domain. A compromise
anywhere can reach everywhere at Layer 2 — ARP-spoof any host (Chapter 9), scan the whole network, move
laterally without crossing any control point (Chapter 125). The blast radius of one compromise is the
entire network. This is why flat networks are a serious finding (Chapter 9 §Solutions 9.9).

**With segmentation:** systems are grouped by trust level into separate broadcast domains (VLANs/
subnets). A compromise in one zone (guest Wi-Fi, a dev environment, a DMZ) is *contained* — to reach
another zone (production, finance, the data tier) the attacker must cross the L3 boundary, where a
firewall/ACL/security group inspects and can deny the traffic. Segmentation converts "one compromise =
total compromise" into "one compromise = one zone," and forces lateral movement through controllable,
monitorable choke points.

```
   Trust zones and the choke points between them:

   [ Internet ]---[ DMZ / public ]---[ app tier ]---[ data tier ]
                       |  firewall/ACL  |  firewall/ACL  |
                    (each -> boundary is a choke point where traffic is controlled and logged)

   [ Guest Wi-Fi ]--X (no path)--X-- [ corporate / production ]   (fully isolated zones)
```

Design principles (the same in VLANs, cloud, and Kubernetes):

- **Group by trust level**, not by convenience — public/DMZ, internal app, sensitive data, management,
  guest. Each is a zone.
- **Default-deny between zones**; permit only the specific flows needed (app→data on the DB port, not
  everything). This is least privilege applied to network zones.
- **The boundary between zones is a control point** — a firewall/ACL/SG that enforces and logs the
  permitted flows. Traffic that never crosses a boundary (intra-zone) is not controlled by it, which is
  why micro-segmentation (PVLANs, per-instance SGs, NetworkPolicy) matters for east-west traffic.
- **Minimize the number and breadth of allowed cross-zone flows** — each is an attack path and a
  blast-radius expansion.

This architecture is Chapter 83 (secure VPC design) and Chapter 87 (Zero Trust network architecture)
in miniature. The mechanism (VLAN vs subnet vs NetworkPolicy) is an implementation detail; the
architecture — trust zones separated by controlled, logged choke points, default-deny between them — is
the durable skill. When you audit *any* network (on-prem, cloud, Kubernetes), you ask: what are the
trust zones, are they actually isolated, what flows are permitted between them, and are those flows
minimal, controlled, and logged?

### 5.1 The management network: a segmentation must

One specific segmentation deserves emphasis because it is so commonly done wrong: **management
interfaces (SSH, RDP, switch/router admin, hypervisor management, IPMI/BMC) must be on a separate,
tightly-restricted network zone** — a dedicated management VLAN on-prem, or a bastion/SSM +
restrictive SGs in the cloud (Chapter 78). Management interfaces are the highest-value targets (they
control the infrastructure), and putting them on the general network means any lateral movement reaches
them. The management zone should be reachable only from specific admin sources (a jump host, a VPN, an
IAM-authenticated session), never from the general user or production network, and never from the
internet. This is a recurring finding and a recurring recommendation, and it is pure segmentation.

---

## 6. Internals: Observing and Configuring VLANs

### 6.1 VLANs on Linux (yes, Linux does 802.1Q)

Linux hosts can participate in VLANs directly — relevant for VMs, containers, and network appliances:

```bash
# Create a VLAN sub-interface (VLAN 20 on eth0):
$ sudo ip link add link eth0 name eth0.20 type vlan id 20
$ sudo ip addr add 10.0.20.5/24 dev eth0.20
$ sudo ip link set eth0.20 up
$ ip -d link show eth0.20
    ... vlan protocol 802.1Q id 20 ...       # confirms the 802.1Q tag and VLAN ID

# See VLAN-tagged frames on the wire:
$ sudo tcpdump -e -n -i eth0 vlan
10:22:41 ... 802.1Q, vlan 20, p 0, ethertype IPv4, 10.0.20.5 > 10.0.20.9: ...
```

The `tcpdump ... vlan` filter and the `802.1Q, vlan 20` in the output show the tag from §4.1 on the
wire. On a container host or hypervisor, VLAN sub-interfaces and bridges are how VMs/containers land in
different VLANs.

### 6.2 What VLAN configuration looks like (switch, conceptual)

On a managed switch (Cisco IOS shown conceptually — you audit these, rarely configure them as a cloud
engineer):

```
   ! An ACCESS port (end device) — hardened:
   interface Gi0/1
     switchport mode access               ! explicitly access, never a trunk
     switchport access vlan 20            ! member of VLAN 20
     switchport nonegotiate               ! disable DTP -> no switch spoofing (§4.4)

   ! A TRUNK port (to another switch) — hardened:
   interface Gi0/24
     switchport mode trunk
     switchport trunk native vlan 999     ! dedicated unused native VLAN (not 1) -> no double-tagging
     switchport trunk allowed vlan 10,20  ! only carry the VLANs that must traverse this link
```

Read the security in the config: `nonegotiate` (no DTP) defeats switch spoofing; a non-1 native VLAN
with no hosts defeats double tagging; `allowed vlan` restricts which VLANs cross the trunk (least
privilege for trunks). These three lines are the core VLAN-hopping defenses (§4.4), and auditing for
their presence is the on-prem review.

### 6.3 The cloud equivalent (what you actually configure)

```bash
# There are no VLANs to configure; you configure subnets, route tables, and security groups.
$ aws ec2 describe-subnets --query 'Subnets[].{id:SubnetId, cidr:CidrBlock, az:AvailabilityZone}'
$ aws ec2 describe-security-groups --query 'SecurityGroups[].{id:GroupId, name:GroupName}'
# Segmentation = which subnet + which SG rules; audit these (Chapters 75-76) instead of VLAN configs.
```

The audit shifts from "are trunks and native VLANs hardened?" to "are subnets and security groups
correctly segmenting trust zones?" — same question, different artifact.

---

## 7. Real-World Example: Ledger Segmentation, On-Prem vs Cloud

**On-prem / data center version of Ledger's environment:**

```
   VLAN 10 (10.0.10.0/24): DMZ — Nginx/load balancers (internet-facing)
   VLAN 20 (10.0.20.0/24): app tier — the ASP.NET Core services
   VLAN 30 (10.0.30.0/24): data tier — PostgreSQL, Redis, RabbitMQ
   VLAN 99 (10.0.99.0/24): management — SSH jump host, switch/hypervisor admin
   Router/firewall between VLANs enforces:
     DMZ  -> app:  allow 443/app-port ;  app -> data: allow 5432/6379/5672 ; deny the rest
     management -> all: allow admin protocols from the jump host only
     everything else between zones: DENY (default-deny)
```

The security properties: a compromise of a DMZ box (the most exposed) can reach the app tier only on
the permitted port, not the data tier directly; the data tier is reachable only from the app tier; and
management is isolated to the jump host. Blast radius is contained per zone (Chapter 1 §5.4). The VLAN-
hopping defenses (§4.4) must be in place, or an attacker on the DMZ VLAN could hop to the data VLAN,
defeating the whole design — which is exactly the finding to check.

**Cloud (System B) version — same architecture, different mechanism:**

```
   Public subnets      = DMZ VLAN       (ALB; SG allows 443 from internet)
   Private app subnets = app VLAN       (ECS; SG allows app-port from ALB SG only)
   Private data subnets= data VLAN      (RDS/cache; SG allows 5432 etc. from app SG only)
   No management VLAN needed as such    -> SSM Session Manager + IAM (no open SSH; Chapter 78)
   Route tables + security groups enforce the same default-deny-between-zones policy.
```

The mapping is one-to-one: subnets are the VLANs, security groups are the inter-VLAN ACLs, and the
management VLAN becomes IAM-authenticated SSM. The cloud version additionally gets **per-instance
micro-segmentation for free** (each instance's SG controls its own traffic, better than standard
VLANs), **no VLAN-hopping risk** (no trunks), and **auditable-as-code** segmentation (Chapter 88).

The takeaway for a cloud security engineer: **you design the same trust-zone segmentation as on-prem,
but you implement it with subnets, route tables, and security groups, and you audit those artifacts
instead of switch configs.** Knowing VLANs lets you translate legacy designs, reason about hybrid
connections (Chapter 77, where on-prem VLANs meet cloud subnets over VPN/Direct Connect), and explain
*why* the cloud mechanism is generally more robust.

---

## 8. Hands-On Demonstration

### LAB 13.1 — VLAN Segmentation and Its Cloud Equivalent

**Objective.** Create VLANs on Linux and observe 802.1Q tags, demonstrate that same-VLAN hosts
communicate while different-VLAN hosts do not (without routing), then map the design to cloud subnets/
security groups.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Create VLAN sub-interfaces and observe tags (network namespaces simulate hosts).*

```bash
# Simulate two hosts in VLAN 10 and one in VLAN 20 over a shared virtual link.
# Simplest observable demo: create VLAN interfaces on a host and capture tagged frames.
sudo ip link add link eth0 name eth0.10 type vlan id 10 2>/dev/null || echo "(needs a real eth0; use a veth)"
# Using veth + bridge for a self-contained demo:
sudo ip netns add h1; sudo ip netns add h2
sudo ip link add veth1 type veth peer name br-veth1
sudo ip link add veth2 type veth peer name br-veth2
sudo ip link add name vlanbr type bridge && sudo ip link set vlanbr up
sudo ip link set br-veth1 master vlanbr up
sudo ip link set br-veth2 master vlanbr up
sudo ip link set veth1 netns h1; sudo ip link set veth2 netns h2
# Put h1 in "VLAN 10" and h2 in "VLAN 20" via tagged sub-interfaces:
sudo ip netns exec h1 ip link add link veth1 name veth1.10 type vlan id 10
sudo ip netns exec h1 ip addr add 10.0.10.1/24 dev veth1.10
sudo ip netns exec h1 ip link set veth1 up && sudo ip netns exec h1 ip link set veth1.10 up
sudo ip netns exec h2 ip link add link veth2 name veth2.20 type vlan id 20
sudo ip netns exec h2 ip addr add 10.0.20.1/24 dev veth2.20
sudo ip netns exec h2 ip link set veth2 up && sudo ip netns exec h2 ip link set veth2.20 up
```

*Step 2 — Show that different VLANs cannot communicate (no routing).*

```bash
# h1 (VLAN10, 10.0.10.1) tries to reach h2 (VLAN20, 10.0.20.1) -> different VLAN AND different subnet:
sudo ip netns exec h1 ping -c1 -W2 10.0.20.1 || echo "unreachable across VLANs (expected): segmentation works"
# Add a same-VLAN peer to show intra-VLAN works (create h3 in VLAN 10)... (left as extension)
```

*Step 3 — Observe the 802.1Q tag on the wire.*

```bash
# Capture on the bridge and see the VLAN tags:
sudo timeout 5 tcpdump -e -n -i vlanbr vlan &
sudo ip netns exec h1 ping -c2 -W1 10.0.10.99 2>/dev/null   # generates VLAN-10-tagged ARP
# Expected in capture: "802.1Q, vlan 10, ethertype ARP ..."
```

*Step 4 — Map to the cloud.*

Write down the equivalent cloud design: VLAN 10 → a subnet + SG; VLAN 20 → another subnet + SG;
inter-VLAN ACL → SG rules; and note that in the cloud there are no trunks (no VLAN hopping) and each
instance gets per-instance micro-segmentation via its SG.

**Security implications.** Write down: (a) how VLANs contain blast radius (a compromise in VLAN 20
cannot reach VLAN 10 at L2); (b) the two VLAN-hopping attacks and their config defenses (§4.4); (c) how
the cloud replaces VLANs with subnets+SGs and removes VLAN hopping; (d) why management must be its own
zone (§5.1).

**Cleanup.**
```bash
sudo ip netns del h1; sudo ip netns del h2; sudo ip link del vlanbr 2>/dev/null
sudo ip link del eth0.10 2>/dev/null
```

---

## 9. Security Implications

- **VLANs implement Layer 2 segmentation** — carving one switch into isolated broadcast domains by
  trust level, containing blast radius (a compromise in one zone cannot reach another at L2).
- **Segmentation is a platform-independent security architecture:** trust zones separated by controlled,
  logged choke points, default-deny between them. VLANs, cloud subnets+SGs, and Kubernetes
  NetworkPolicy are three mechanisms for the same principle.
- **VLAN hopping (switch spoofing, double tagging) defeats segmentation** — but via misconfiguration/
  insecure defaults (DTP on, VLAN 1 native), not a VLAN flaw. Hardening: `nonegotiate`, explicit access
  ports, dedicated non-1 native VLAN, restricted trunk-allowed VLANs.
- **Standard VLANs isolate between VLANs, not within** — intra-VLAN east-west traffic is uncontrolled;
  PVLANs/micro-segmentation (and cloud per-instance SGs) address this.
- **The cloud replaces VLANs with subnets + security groups**, removing VLAN hopping, providing
  per-instance micro-segmentation by default, and making segmentation auditable as code.
- **Management interfaces must be a separate, tightly-restricted zone** — a recurring must and finding.

---

## 10. Attack Scenarios

1. **VLAN hopping via switch spoofing (DTP):** an attacker on an access port left in dynamic mode
   negotiates a trunk and gains access to all VLANs — full segmentation bypass (§4.4). Defense: disable
   DTP, explicit access ports.
2. **VLAN hopping via double tagging:** inject frames into a target VLAN from the native VLAN (§4.4).
   Defense: non-1, host-free native VLAN; tag the native VLAN.
3. **Flat network / no segmentation:** a compromise anywhere reaches everywhere at L2 — the worst case
   segmentation prevents (Chapter 9 §Sol 9.9). "Finding: no segmentation."
4. **Over-broad inter-VLAN ACLs (or SG rules):** permitting more cross-zone traffic than needed,
   widening lateral-movement paths — the cloud analogue is over-broad security groups (Chapter 76).
5. **Management interfaces on the general network:** high-value admin interfaces reachable from user/
   production zones, enabling privilege escalation after lateral movement (§5.1).
6. **Intra-VLAN lateral movement:** even with VLANs, hosts within one VLAN can attack each other (ARP
   spoofing, scanning) because standard VLANs do not isolate within — mitigated by PVLANs / per-instance
   SGs / NetworkPolicy.

---

## 11. Defensive Techniques

**On-prem VLAN hardening:**

- **Disable DTP; explicitly configure access ports** (`switchport mode access`, `switchport
  nonegotiate`) so they cannot be switch-spoofed into trunks (§4.4).
- **Use a dedicated, unused native VLAN (not VLAN 1); put no hosts on it; tag the native VLAN** to
  defeat double tagging. Avoid VLAN 1 for anything.
- **Restrict trunk-allowed VLANs** to only those that must traverse each trunk (least privilege for
  trunks).
- **Enforce default-deny between VLANs at the L3 boundary**, permitting only necessary flows, and log
  cross-zone traffic (Chapter 13's choke-point principle).
- **Segment management onto its own restricted VLAN** reachable only from admin sources (§5.1).
- **Use PVLANs / micro-segmentation** where intra-VLAN isolation is needed (shared-subnet tenants,
  sensitive hosts).
- Combine with the L2 defenses from Chapters 8–9 (port security, DHCP snooping, DAI) — VLANs alone do
  not stop ARP spoofing *within* a VLAN.

**Cloud (the VLAN successor):**

- **Design subnets by trust zone** (public/app/data/management) and **use security groups for
  default-deny, least-privilege, per-instance segmentation** (Chapters 75–76). Prefer SG-to-SG
  references over CIDRs.
- **No trunks means no VLAN hopping** — but audit that route tables and SGs actually implement the
  intended zone isolation (Chapters 12, 76).
- **Replace the management VLAN with IAM-authenticated access** (SSM Session Manager, no open SSH —
  Chapter 78).
- **Enforce segmentation as code** (Chapters 88, 91) so it is reviewable and drift is caught.

**Everywhere:**

- **Default-deny between zones; minimize and log cross-zone flows; separate management; and encrypt
  regardless** — because segmentation reduces the likelihood of lateral movement, but encryption (and
  the intra-zone controls) reduce its impact (Chapters 9, 43).

---

## 12. Production Architecture

Segmentation across platforms, the enforcing mechanism per layer:

```
 TRUST-ZONE SEGMENTATION      ON-PREM                 CLOUD (VPC)             KUBERNETES
 -------------------------    ---------------------   ---------------------   ---------------------
 the zone                     VLAN (broadcast domain) subnet                  namespace / labels
 between-zone control         router ACL / firewall   route table + SG/NACL   NetworkPolicy
 within-zone (east-west)      PVLAN (optional)         per-instance SG (free)  NetworkPolicy (free-ish)
 zone-hopping risk            VLAN hopping (config)    (none — no trunks)      policy gaps / default-allow
 management isolation         management VLAN          SSM + IAM + SG          RBAC + NetworkPolicy
 defined/audited as           switch configs           IaC (subnets/SGs)       manifests (IaC)
 load-bearing addition        encrypt + intra-zone     encrypt + SG-to-SG      mTLS (mesh) + NetPol
```

The architectural principle: **segmentation is one control (blast-radius containment via trust zones
and controlled choke points), implemented by whatever the platform provides.** The cloud's version is
generally superior — per-instance micro-segmentation by default, no zone-hopping attack class,
auditable as code — but the *design work* (identifying trust zones, defining minimal default-deny flows
between them, isolating management) is identical and is the durable skill. A mature multi-environment
platform applies the same segmentation architecture consistently across on-prem VLANs, cloud subnets/
SGs, and Kubernetes NetworkPolicy, unified by the same default-deny, least-privilege, separate-
management principles.

---

## 13. Common Mistakes

1. **Flat networks / no segmentation** — one compromise reaches everything (Chapter 9 §Sol 9.9).
2. **Leaving DTP/auto-trunking enabled** on access ports → switch-spoofing VLAN hopping.
3. **Using VLAN 1 as the native VLAN and putting hosts on it** → double-tagging exposure.
4. **Trunks allowing all VLANs** instead of only the necessary ones (no least privilege for trunks).
5. **Management interfaces on the general network** rather than an isolated zone (§5.1).
6. **Assuming VLANs isolate within a VLAN** — they do not; intra-VLAN attacks (ARP spoofing) still
   work; add PVLANs/SGs/NetworkPolicy.
7. **Over-broad inter-zone ACLs / security groups** — widening lateral-movement paths.
8. **Relying on segmentation alone** without encryption or intra-zone controls — segmentation reduces
   likelihood, not impact.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Hosts in the "same VLAN" can't talk | different VLAN IDs, or an access port in the wrong VLAN | check port VLAN assignments; `tcpdump vlan` for tags |
| Cross-VLAN traffic works when it shouldn't | possible VLAN hopping or a misconfigured trunk/ACL | check trunk allowed-VLANs, DTP status, native VLAN, L3 ACLs |
| An access port unexpectedly carries multiple VLANs | DTP negotiated a trunk (switch spoofing) | verify `switchport mode access` + `nonegotiate` |
| Frames appearing in the wrong VLAN | double-tagging or native-VLAN misconfig | check native VLAN (non-1, host-free, tagged) |
| Cloud: subnets can reach each other unexpectedly | SG too broad, or intended (routing allows local) | audit SG rules (Chapter 76); routing is local within VPC |
| Management interface reachable from user network | management not segmented | move to isolated VLAN / SSM+IAM; restrict sources (§5.1) |
| Linux VLAN interface no traffic | tag mismatch or upstream port not trunking that VLAN | `ip -d link show`; `tcpdump vlan`; check switch trunk config |

---

## 15. Practical Lab

Lab 13.1 is in §8. Register it in the lab index. Extension: take an on-prem VLAN segmentation design
(or invent one with 4 trust zones) and translate it fully to a cloud VPC design (subnets, route tables,
security-group rules with SG-to-SG references), then to a Kubernetes design (namespaces + NetworkPolicy)
— producing the same trust-zone architecture in three mechanisms. This "same architecture, three
mechanisms" exercise is exactly the translation skill a cloud security engineer needs in hybrid and
multi-platform environments (Chapters 75–76, 83, 104).

---

## 16. Exercises

### Concept questions

**13.1** Explain what a VLAN is and how it relates to a broadcast domain and an IP subnet. What is the
cloud equivalent?

**13.2** Distinguish access ports from trunk ports and explain why confusing them enables an attack.
What is the 802.1Q tag and when is it present?

**13.3** Describe both VLAN-hopping attacks (switch spoofing and double tagging) and the specific
configuration defense for each. Why are these misconfiguration issues rather than VLAN flaws?

**13.4** Explain network segmentation as a security architecture in terms of trust zones, choke points,
and blast radius. Why is a flat network a serious finding?

**13.5** Why do standard VLANs not protect against intra-VLAN attacks, and what mechanisms address
east-west traffic within a zone (on-prem and cloud)?

### Debugging problems

**13.6** During an assessment you find an access port that, when you connect a laptop, receives tagged
frames for several VLANs. Explain what is happening and the fix.

**13.7** A "segmented" network is found to allow a host in the DMZ VLAN to inject frames into the
database VLAN. What attack is likely, and what native-VLAN misconfiguration enabled it?

**13.8** In a VPC, two subnets that should be isolated can communicate. There are no VLANs. Where do
you look?

### Security scenarios

**13.9** You are asked to segment a flat corporate network. Describe your trust-zone design, the
choke-point controls, the VLAN-hopping hardening, and how you would handle management interfaces.

**13.10** Translate a four-zone on-prem VLAN segmentation (DMZ/app/data/management) into an equivalent
AWS VPC design, naming the mechanism for each element and the improvements the cloud provides.

### Architecture questions

**13.11** Design segmentation for a platform spanning on-prem (VLANs) and AWS (VPC) connected by
VPN/Direct Connect (Chapter 77). How do you keep trust zones consistent across the boundary?

**13.12** Explain how the segmentation principle recurs across VLANs, cloud security groups, and
Kubernetes NetworkPolicy, and what stays constant vs. what changes.

### Hands-on exercises

**13.13** Create VLAN sub-interfaces on Linux, assign addresses, and capture 802.1Q-tagged frames with
`tcpdump vlan`, identifying the VLAN ID in the output.

**13.14** Demonstrate that hosts in different VLANs (and subnets) cannot communicate without routing,
then (conceptually) describe the router ACL that would permit only the necessary flow.

**13.15** Write out (or script a check for) the three VLAN-hopping hardening settings on a switch
trunk/access config, and the cloud SG-audit equivalents.

### Interview questions

**13.16** "What is a VLAN, and how does it provide security?"

**13.17** "Explain VLAN hopping and how you'd prevent it."

**13.18** "How does cloud segmentation (subnets + security groups) compare to VLANs? What's better and
what's the same?"

**13.19** "Why must management interfaces be segmented, and how would you do it on-prem vs in the
cloud?"

**13.20** "Walk me through segmenting a flat network into trust zones."

---

## 17. Summary

- A **VLAN** is a broadcast domain defined in software on a switch — one physical switch becomes many
  logical, isolated networks, each usually one IP subnet. It is **Layer 2 segmentation**, the on-prem
  ancestor of the cloud subnet.
- **Access ports** carry one VLAN's untagged frames (end devices); **trunk ports** carry multiple VLANs'
  **802.1Q-tagged** frames (switch-to-switch/router). Cross-VLAN traffic must go through a router, where
  ACLs/firewalls enforce which zones may talk.
- **VLAN hopping** (switch spoofing via DTP; double tagging via the native VLAN) defeats segmentation,
  but through misconfiguration/insecure defaults — hardened by `nonegotiate`/explicit access ports, a
  dedicated non-1 native VLAN, and restricted trunk-allowed VLANs.
- **Segmentation is a platform-independent security architecture:** trust zones separated by controlled,
  logged choke points, **default-deny between them**, containing blast radius (a compromise in one zone
  cannot reach another). A flat network is a serious finding.
- **Standard VLANs isolate between but not within** — east-west/intra-zone traffic needs PVLANs
  (on-prem), per-instance security groups (cloud, free by default), or NetworkPolicy (Kubernetes).
- **Management interfaces must be their own restricted zone** — a recurring must and finding.
- **The cloud replaces VLANs with subnets + route tables + security groups**, removing the VLAN-hopping
  attack class, giving per-instance micro-segmentation by default, and making segmentation auditable as
  code — the same architecture, a generally better mechanism. Knowing VLANs lets you translate designs
  and reason about hybrid environments (Chapter 77).

---

## 18. Knowledge Check

1. What is a VLAN, and what is its cloud equivalent? (§3, §4.6)
2. Difference between access and trunk ports, and where the 802.1Q tag appears? (§4.2, §4.1)
3. Name the two VLAN-hopping attacks and one defense each. (§4.4)
4. Why is a flat network a serious security finding? (§5)
5. What is default-deny between zones, and why does cross-zone traffic being a choke point matter? (§5)
6. Do standard VLANs protect within a VLAN? What does? (§4.5)
7. How does the cloud remove VLAN hopping? (§4.6)
8. Why must management be segmented? (§5.1)
9. Map VLAN, inter-VLAN ACL, and PVLAN to their cloud equivalents. (§4.6, §12)
10. What stays constant across VLAN/SG/NetworkPolicy segmentation? (§12)

---

## 19. Further Exploration

- Cisco's VLAN security best-practices docs (DTP, native VLAN, VLAN 1) — the concrete on-prem hardening
  you will audit for in hybrid environments.
- Set up VLAN sub-interfaces on Linux (Lab 13.1) and inspect tags with Wireshark's 802.1Q dissector
  (bridge to Chapter 24).
- Read about the SANS/PCI-DSS guidance on network segmentation — segmentation is a compliance
  requirement, and understanding it in those terms helps in real reviews (Chapter 132).
- Preview Chapters 75–76 (VPC subnets and security groups) and Chapter 104 (NetworkPolicy) and map each
  back to the VLAN concepts here — the "same architecture, three mechanisms" exercise (§15).
- For micro-segmentation, read about zero-trust network segmentation and service mesh (Chapters 86–87),
  which push segmentation down to per-workload granularity.

---

## Solutions

### 13.1
A VLAN (Virtual LAN) is a broadcast domain defined logically on a switch rather than by physical
wiring, so one physical switch can host several independent VLANs, each behaving like a separate switch.
A VLAN *is* a broadcast domain (Chapter 8) — frames broadcast in VLAN 10 reach only VLAN 10 ports — and
it usually corresponds one-to-one with an IP subnet (VLAN 10 = 10.0.10.0/24, say). Hosts in the same
VLAN communicate directly at Layer 2 (ARP/switching); hosts in different VLANs must go through a router
(Layer 3), where ACLs/firewalls control the traffic. The cloud equivalent is the **subnet**: a VPC
subnet is the broadcast-domain-like unit, inter-subnet traffic is controlled by route tables and
security groups (the inter-VLAN ACL equivalent), and there are no VLAN tags in the customer model
because the SDN handles delivery. So "VLAN : on-prem :: subnet : cloud," with SGs playing the role of
inter-VLAN ACLs.

### 13.2
An access port belongs to exactly one VLAN and carries untagged frames to/from an end device (PC,
server) that is unaware of VLANs — the switch handles the VLAN association internally. A trunk port
carries multiple VLANs' frames, tagged with 802.1Q (EtherType 0x8100 + a 12-bit VLAN ID), connecting
switches to each other or to routers so many VLANs share one physical link while staying separated by
their tags. Confusing them enables **switch spoofing**: if an access port is left able to negotiate
trunking (DTP), an attacker can make it become a trunk and thereby receive tagged frames for *all*
VLANs, escaping the single-VLAN isolation the access port was supposed to provide — full segmentation
bypass. The 802.1Q tag is present on trunk links (to distinguish VLANs) and absent on access links
(the frame is untagged; the switch knows the VLAN from the port config). So the tag appears exactly
where multiple VLANs share a link.

### 13.3
**Switch spoofing:** an access port left in DTP dynamic mode can be tricked when the attacker's device
sends DTP frames pretending to be a switch that wants a trunk; the switch forms a trunk, and the
attacker receives all VLANs' tagged traffic. Defense: disable DTP and set ports explicitly to access
(`switchport mode access`, `switchport nonegotiate`), so the port cannot become a trunk. **Double
tagging:** the attacker (on the native VLAN) sends a frame with two 802.1Q tags — outer = native VLAN,
inner = target VLAN; the first switch strips the outer tag (native VLAN frames go untagged on the
trunk) and forwards the frame still bearing the inner tag, which the second switch delivers into the
target VLAN (one-way injection). Defense: use a dedicated, unused native VLAN (not VLAN 1), put no hosts
on it, and tag the native VLAN so the outer-tag-stripping trick fails. Both are misconfiguration/
insecure-default issues, not VLAN design flaws: DTP defaulting to auto and VLAN 1 defaulting as native
are the enablers, so correct configuration eliminates the attacks — the recurring "the mechanism is
sound; the defaults are the risk" pattern.

### 13.4
Segmentation groups systems into trust zones (public/DMZ, internal app, sensitive data, management,
guest), each its own network (VLAN/subnet), and permits traffic between zones only through controlled,
logged choke points (routers/firewalls/security groups) with **default-deny between zones**. Its
security value is blast-radius containment (Chapter 1 §5.4): a compromise in one zone is confined to
that zone, and reaching another requires crossing a choke point where the traffic is inspected and can
be denied and logged — converting "one compromise = total compromise" into "one compromise = one zone,"
and forcing lateral movement through monitorable control points. A flat network (one broadcast domain,
no zones) is a serious finding because it provides none of this: a compromise anywhere can reach and
attack everywhere at Layer 2 (ARP-spoof any host, scan the whole network, move laterally without
crossing any control), so the blast radius of a single foothold is the entire network — the worst-case
the whole architecture exists to prevent.

### 13.5
Standard VLANs isolate traffic *between* VLANs but not *within* one: all hosts in a VLAN share a
broadcast domain and can communicate directly at Layer 2, so a compromised host can still ARP-spoof,
scan, and attack its VLAN neighbors (Chapters 8–9) — the segmentation stops at the VLAN boundary, not
at each host. East-west (intra-zone) traffic is addressed by micro-segmentation: on-prem, **Private
VLANs (PVLANs)** with isolated/community ports restrict host-to-host communication within a VLAN; in
the cloud, **per-instance security groups** control each instance's traffic independently by default
(so intra-subnet traffic is already micro-segmented, better than standard VLANs); in Kubernetes,
**NetworkPolicy** controls pod-to-pod traffic within and across namespaces (Chapter 104). The principle
is default-isolation even within a zone, with explicit allow — the same least-privilege idea pushed to
finer granularity, which is where Zero Trust networking (Chapter 87) and service mesh (Chapter 86) take
it.

### 13.6
The access port is not truly locked to a single VLAN — it has negotiated (or been configured as) a
trunk, so it carries tagged frames for multiple VLANs. Most likely cause: DTP (Dynamic Trunking
Protocol) is enabled and the port is in dynamic auto/desirable mode, and something (the laptop's NIC/
tooling, or a prior device) triggered trunk negotiation — this is **switch spoofing / VLAN hopping**
(§4.4). It could also be a misconfiguration where the port was left as a trunk. The exposure is
severe: a device on this port can reach all VLANs the trunk carries, defeating segmentation. Fix:
configure the port explicitly as access (`switchport mode access`), assign it the correct single VLAN
(`switchport access vlan N`), and disable DTP (`switchport nonegotiate`); audit all access ports for
the same, and restrict trunk-allowed VLANs on real trunks. Verify by reconnecting and confirming only
untagged frames for the assigned VLAN are seen.

### 13.7
The likely attack is **double tagging** (§4.4): a host in the DMZ VLAN, if the DMZ VLAN is the trunk's
native VLAN (or the attacker can send on the native VLAN), sends a frame with an outer tag matching the
native VLAN and an inner tag for the database VLAN; the first switch strips the native (outer) tag and
forwards the frame still carrying the inner tag, which the next switch delivers into the database VLAN —
one-way frame injection into a supposedly isolated zone. The enabling misconfiguration is the **native
VLAN**: using VLAN 1 (or the DMZ VLAN) as the native VLAN on the trunk and allowing hosts on it, so
native-VLAN frames travel untagged and the outer-tag-stripping trick works. Fix: set the native VLAN
to a dedicated, unused VLAN with no hosts, enable tagging of the native VLAN so nothing is sent
untagged, and ensure the DMZ VLAN is never the native VLAN; also restrict which VLANs each trunk
carries. This closes the double-tagging path.

### 13.8
In a VPC there are no VLANs, so subnet-to-subnet reachability is governed by **route tables**
(Chapter 12) and **security groups/NACLs** (Chapter 76). Look there: (1) within a VPC, all subnets have
the implicit `local` route, so at the *routing* layer they can reach each other by default — isolation
between subnets is enforced by **security groups and NACLs**, not routing; so the likely cause is an
**over-broad security group** (e.g. allowing a wide CIDR like the whole VPC `10.0.0.0/16`, or
`0.0.0.0/0`, instead of a specific SG reference) or a permissive NACL. (2) Check the SG rules on the
resources in the two subnets for rules permitting the other subnet's CIDR/SG; (3) check NACLs (which
are subnet-level, stateless, ordered) for allow rules; (4) if peering/TGW is involved (Chapter 77),
check those routes too. Fix: tighten SGs to least privilege (prefer SG-to-SG references over CIDRs) so
only intended flows are allowed. The lesson: in the cloud, "why can these two subnets talk?" is a
security-group question first (since routing allows local), the inverse emphasis from on-prem where
VLANs block by default.

### 13.9
Trust-zone design: define zones by trust level — e.g. **guest** (untrusted, isolated), **user/
corporate** (workstations), **DMZ** (internet-facing services), **app/internal servers**, **data**
(databases/sensitive), and **management** (admin interfaces). Put each in its own VLAN/subnet.
Choke-point controls: route inter-zone traffic through a firewall/L3 device with **default-deny**,
permitting only necessary flows (users→app on app ports, app→data on DB ports, DMZ→app only, guest→
internet only with no path to internal), and **log** cross-zone traffic. VLAN-hopping hardening on the
switches: disable DTP and set explicit access ports (`nonegotiate`), use a dedicated non-1 native VLAN
with no hosts and tag it, restrict trunk-allowed VLANs, and don't use VLAN 1 for data. Management:
place all admin interfaces (SSH/RDP, switch/router/hypervisor admin, IPMI) on a dedicated **management
VLAN reachable only from a jump host / VPN**, never from user/production zones or the internet (§5.1).
Add intra-zone controls where needed (PVLANs for shared-subnet isolation) and combine with L2 defenses
(port security, DHCP snooping, DAI) and encryption. Phase the rollout to avoid outages, and document
the permitted-flows matrix as the reviewable artifact.

### 13.10
On-prem four zones → AWS: **DMZ VLAN → public subnets** (across two AZs) hosting the ALB, with an SG
allowing 443 from the internet; **app VLAN → private app subnets** (route to NAT for egress) hosting
ECS/EC2, with an SG allowing the app port only from the ALB's SG; **data VLAN → private data subnets**
(no internet route) hosting RDS/cache, with an SG allowing DB ports only from the app SG; **management
VLAN → replaced by IAM-authenticated SSM Session Manager** (no open SSH, no bastion needed) plus
restrictive SGs — management access is via IAM/CloudTrail, not a network zone. Inter-VLAN ACLs →
**security-group rules (SG-to-SG references)** and route tables; default-deny is the SG default (SGs
deny unless allowed). Improvements the cloud provides: **no VLAN-hopping attack class** (no trunks/
DTP/native VLAN to misconfigure); **per-instance micro-segmentation by default** (each instance's SG
controls its own traffic, better than standard VLANs); **segmentation auditable as code** (subnets/SGs/
routes in Terraform, Chapter 88); and management via IAM removes the open-admin-port risk. The design
work — zones, minimal default-deny flows, isolated management — is identical; the mechanism is subnets +
SGs + IAM.

### 13.16
A VLAN is a virtual LAN — a broadcast domain created logically on a switch, so one physical switch can
be divided into multiple isolated networks (each usually one IP subnet). It provides security through
**segmentation**: hosts in different VLANs cannot communicate at Layer 2 and must go through a router,
where ACLs/firewalls control (and log) which VLANs may talk. This contains blast radius — a compromise
in one VLAN (say guest Wi-Fi or a DMZ) cannot directly reach another (production, data) — and forces
lateral movement through controllable choke points, converting "one compromise = whole network" into
"one compromise = one zone." Caveats to mention: VLANs isolate *between* VLANs, not within one
(intra-VLAN attacks still work; use PVLANs/SGs), and misconfiguration (DTP, VLAN 1 native) enables VLAN
hopping that defeats the isolation — so VLANs must be hardened. The cloud achieves the same
segmentation with subnets + security groups.

### 13.17
VLAN hopping is escaping one VLAN's isolation to reach another, via two techniques. **Switch spoofing:**
an access port left able to negotiate trunking (DTP dynamic mode) is tricked into becoming a trunk by an
attacker's device sending DTP frames, giving the attacker tagged access to all VLANs. **Double
tagging:** an attacker on the native VLAN sends a doubly-802.1Q-tagged frame (outer = native, inner =
target); the first switch strips the outer tag and forwards the frame with the inner tag, which the next
switch delivers into the target VLAN (one-way injection). Prevention: disable DTP and set access ports
explicitly (`switchport mode access`, `switchport nonegotiate`) so they cannot become trunks; use a
dedicated, unused native VLAN (never VLAN 1), put no hosts on it, and tag the native VLAN so nothing is
sent untagged; and restrict each trunk's allowed VLANs to only those required. These are configuration
fixes because both attacks exploit insecure defaults, not a VLAN flaw. In the cloud, VLAN hopping does
not exist (no trunks), so the equivalent concern is over-broad security groups.

### 13.18
Cloud segmentation uses **subnets** as the zone unit and **security groups/NACLs** (plus route tables)
as the between-zone control, replacing VLANs and inter-VLAN ACLs. Same: the *architecture* — group by
trust zone, default-deny between zones, permit only minimal flows, isolate management, contain blast
radius; the design work is identical. Better in the cloud: (1) **no VLAN-hopping attack class** — there
are no trunks, DTP, or native VLANs to misconfigure, so an entire category of segmentation-bypass
disappears; (2) **per-instance micro-segmentation by default** — each instance's security group
controls its own traffic, so intra-subnet (east-west) traffic is controlled without extra work,
whereas standard VLANs isolate only between VLANs; (3) **auditable as code** — subnets/SGs/routes are
IaC artifacts, reviewable and drift-detectable, versus switch configs prone to drift; (4) **SG-to-SG
references** allow identity-based rules ("from the app tier") that auto-update, tighter than CIDRs.
What's the same: you still must design the zones and minimal flows correctly, and an over-broad SG is
the cloud analogue of a permissive inter-VLAN ACL. Net: the cloud keeps the principle and provides a
generally stronger, more auditable mechanism.

### 13.19
Management interfaces (SSH/RDP, switch/router/firewall admin, hypervisor management, IPMI/BMC) must be
segmented because they are the highest-value targets — controlling them means controlling the
infrastructure — so if they are reachable from the general user or production network, any lateral
movement (Chapter 125) reaches them and escalates to infrastructure compromise. On-prem: place all
management interfaces on a dedicated **management VLAN** reachable only from a hardened jump host or
VPN, never from user/production zones or the internet, with tight ACLs and logging, and protected by
strong (ideally MFA'd, RADIUS/TACACS+) admin authentication (Chapter 62). In the cloud: replace the
management VLAN with **IAM-authenticated access via SSM Session Manager** (no open SSH/RDP ports at all
— access is brokered through the AWS API, authenticated by IAM, logged in CloudTrail — Chapter 78),
plus restrictive security groups and, where SSH is unavoidable, a bastion restricted to specific source
IPs. Either way, the principle is: management is its own tightly-restricted zone, reachable only from
specific, authenticated admin sources, never broadly.

### 13.20
Walk: (1) **Inventory and classify** — enumerate systems and group them by trust level into zones
(e.g. guest, user, DMZ/public, app, data, management), based on exposure and sensitivity. (2) **Assign
zones to VLANs/subnets** — one broadcast domain (and IP subnet) per zone. (3) **Define the permitted
inter-zone flows** as a matrix, default-deny — only what's necessary (users→app on app ports, app→data
on DB ports, DMZ→app only, guest→internet only, management from jump host only), and route all
inter-zone traffic through a firewall/L3 device that enforces and **logs** it. (4) **Isolate management**
into its own restricted zone. (5) **Harden against VLAN hopping** — disable DTP, explicit access ports,
dedicated non-1 native VLAN, restricted trunk-allowed VLANs. (6) **Add intra-zone controls** where
needed (PVLANs / per-host controls) and combine with L2 defenses (port security, DHCP snooping, DAI)
and encryption. (7) **Phase the migration** to avoid outages (start by monitoring flows to build the
allow matrix, then enforce), and **document** the zones and flow matrix as the reviewable artifact.
The output is trust zones separated by controlled, logged, default-deny choke points — blast-radius
containment — and the same design translates directly to cloud subnets+SGs or Kubernetes NetworkPolicy.

---

*Next: Chapter 14 — NAT and PAT: Address Translation, Connection Tables, and Why NAT Is Not a
Firewall. We examine how private addresses (Chapter 10) reach the internet, how NAT's connection table
works (and how it accidentally provided the "NAT firewall" IPv6 removed — Chapter 11), and the precise,
often-misunderstood security properties of NAT.*
