# Chapter 12 — Routing: Tables, Default Gateways, Longest-Prefix Match, and the Journey of a Packet

---

## 1. Why This Matters

Chapters 8–11 addressed *hosts on a segment*. Routing is how a packet gets from one segment to
another — across the office, across the data center, across the internet. For a cloud security
engineer, routing is not an abstract networking topic; it is a **primary security control** you
configure by hand:

- **A VPC route table (Chapter 75) is exactly the route table this chapter describes.** Whether a
  subnet is "public" or "private" is decided by one line in a route table: does it have a route to an
  internet gateway? Getting that wrong makes a private database internet-reachable, or breaks a
  service's egress.
- **Routing determines reachability, which is access.** "Can these two subnets talk?" is answered by
  routes before security groups are ever consulted. A missing route is an implicit deny; an
  unintended route is an implicit allow. You must be able to read a route table and know exactly what
  can reach what.
- **Routing attacks redirect traffic.** BGP hijacking has rerouted internet traffic (including
  cryptocurrency and cloud provider traffic) to attackers; ICMP redirects and route injection do it
  locally. Understanding routing is understanding a whole class of interception.
- **Incident response and debugging** constantly come down to "why can't this reach that?" or "why
  did traffic go there?" — routing questions answered by reading route tables and running
  `traceroute`.

The core idea: **a router forwards each packet toward its destination by consulting a route table
and picking the most specific matching route (longest-prefix match). The route table is a
security-relevant configuration: it defines the topology of reachability.** In the cloud you write
these tables directly, so routing is a control you own, and misconfiguring it is a common and serious
finding.

This chapter completes the "journey of a packet" begun in Chapter 8 §5: we now follow the packet
*across* networks, hop by hop, and see exactly how each router decides where to send it next.

---

## 2. Prerequisites

- Chapter 8 §5 (dst MAC = next hop, dst IP = final target; the local/remote decision) — routing is
  what happens after "remote."
- Chapter 10 (CIDR, prefixes — routes are CIDR-based) and Chapter 9 (ARP resolves each next hop).
- Chapter 4 (the map, Stop 2) and Chapter 6 (cloud) for the VPC context.

---

## 3. Mental Model

**Routing is repeated application of one decision: "given this destination IP, which is the most
specific route I have, and what is its next hop?" Every router (and every host) does this for every
packet, independently, hop by hop, until the packet arrives.**

```
   A packet from 10.0.1.5 to 93.184.216.34 (a web server):

   Host 10.0.1.5:  "93.184.216.34 is remote (Ch.8 §5). My route table says:
                     0.0.0.0/0 -> gateway 10.0.1.1. Send frame to the gateway's MAC."
        |
   Router 10.0.1.1: "dst 93.184.216.34. My most specific matching route -> next hop 203.0.113.1.
                     Rewrite L2 header (new src/dst MAC), decrement TTL, forward."
        |
   Router 203.0.113.1: same decision, next hop...
        |
   ... many hops, each an independent longest-prefix-match decision ...
        |
   Final router: "dst 93.184.216.34 is on a directly-connected network. ARP for it, deliver."
```

Four ideas do all the work:

1. **Hop-by-hop, independent.** No router knows the whole path; each just picks the next hop toward
   the destination. The path emerges from many local decisions. (This is why `traceroute` works —
   §6.)
2. **Longest-prefix match.** When multiple routes match a destination, the **most specific** (longest
   prefix) wins. `10.0.1.0/24` beats `10.0.0.0/16` beats `0.0.0.0/0` for a destination in
   `10.0.1.x`. This single rule governs all route selection.
3. **The default route (`0.0.0.0/0`) is the catch-all** — "if nothing more specific matches, send it
   here" (usually toward the internet). It is the least specific route, matched only when nothing
   else does.
4. **The L2 header is rewritten at every hop; the L3 destination IP never changes** (Chapter 8 §5);
   the **TTL decrements** each hop (§4.4). This is the mechanism that makes routing work and that
   `traceroute` exploits.

**The security framing:** the route table is the map of what can reach what. In the cloud, *you draw
that map*. "Is the database reachable from the internet?" is answered first by the route table (does
its subnet route to an internet gateway?), then by security groups. Routing is the coarsest, most
foundational reachability control — and a misdrawn route table is a foundational exposure.

---

## 4. Fundamentals

### 4.1 The route table

A route table is an ordered set of rules: `destination CIDR → next hop (or interface)`. On a host:

```bash
$ ip route
default via 10.0.1.1 dev eth0                        # 0.0.0.0/0 -> gateway (catch-all)
10.0.1.0/24 dev eth0 proto kernel scope link         # directly connected (no gateway; deliver on L2)
10.0.2.0/24 via 10.0.1.254 dev eth0                  # a specific route to another subnet
```

Read each entry:

- **`default via 10.0.1.1`** — the default route (`0.0.0.0/0`): anything not matched more specifically
  goes to the gateway `10.0.1.1`.
- **`10.0.1.0/24 dev eth0 scope link`** — the *directly connected* network: these destinations are on
  the local segment, delivered via ARP/L2 (Chapter 8–9), no gateway needed. This route is created
  automatically when you assign the interface an address.
- **`10.0.2.0/24 via 10.0.1.254`** — a specific route: to reach `10.0.2.x`, send to next hop
  `10.0.1.254` (some router on the local segment that knows how to reach `10.0.2.0/24`).

Each entry has a **destination prefix** and a **next hop** (a `via` gateway, or `dev` for
directly-connected). This is the same structure whether it is a Linux host, a physical router, or a
VPC route table.

### 4.2 Longest-prefix match (the one rule)

When a packet's destination matches multiple routes, the **most specific (longest prefix) wins**:

```
   Route table:
     0.0.0.0/0      -> internet gateway     (prefix length 0)
     10.0.0.0/16    -> VPC-local            (prefix length 16)
     10.0.5.0/24    -> a peering connection (prefix length 24)
     10.0.5.128/25  -> a specific appliance (prefix length 25)

   Destination 10.0.5.200:
     matches 0.0.0.0/0 (yes), 10.0.0.0/16 (yes), 10.0.5.0/24 (yes), 10.0.5.128/25 (yes: 200>=128)
     -> LONGEST prefix wins: /25 -> send to the appliance
   Destination 10.0.5.50:
     matches /0, /16, /24 (yes), /25 (no: 50<128)
     -> longest match is /24 -> send to the peering connection
   Destination 8.8.8.8:
     matches only 0.0.0.0/0 -> default route -> internet gateway
```

Longest-prefix match is *the* route-selection algorithm, and it has direct security consequences:

- **A more specific route overrides a general one.** This is how attacks work (inject a `/32` route to
  a target and you capture just that destination — §10) and how legitimate overrides work (route a
  specific destination through an inspection appliance while everything else goes direct).
- **Order does not matter; specificity does.** Unlike a firewall's first-match rules (Chapter 76),
  routing picks the most specific regardless of position. (Security groups and NACLs differ — SGs are
  "any allow matches," NACLs are ordered — Chapter 76; do not confuse route selection with rule
  evaluation.)
- **The default route is the last resort** — matched only when nothing specific does. A packet with
  no matching route at all (not even default) is dropped as unreachable.

### 4.3 Directly connected vs. routed, and the default gateway

Two categories of destination, from the host's view (Chapter 8 §5 restated as routing):

- **Directly connected** (a `scope link` route): the destination is on a network the host has an
  interface on; deliver directly via ARP/L2, no router involved.
- **Routed via a gateway** (a `via` route, including the default): the destination is elsewhere; send
  to the next-hop router, which continues the process.

The **default gateway** is the next hop for the default route — "everything I don't have a specific
route for." On a typical host it points at the local router/firewall. In a VPC, the "default gateway"
role is played by the VPC router (an implicit, highly-available router AWS provides), and the route
table entries you write tell it where to send each prefix.

### 4.4 TTL: the loop-prevention (and traceroute) mechanism

Every IP packet has a **TTL (Time To Live)** field (Chapter 7 §5 — you decoded it, value 64 in the
example). Each router **decrements the TTL by 1**; if it reaches 0, the router **drops the packet and
sends an ICMP "Time Exceeded" back to the source** (Chapter 23). Purposes:

- **Loop prevention:** if a routing misconfiguration creates a loop, packets do not circulate
  forever — TTL expiry kills them. Essential for internet stability.
- **`traceroute` (Chapter 23):** deliberately sends packets with TTL=1, 2, 3, … so each successive
  router along the path drops one and reveals itself via the ICMP Time Exceeded — which is how you
  *see* the hop-by-hop path (§6).
- **Security signal:** an unusually low TTL, or TTL-based OS fingerprinting (different OSes start at
  different TTLs — Linux 64, Windows 128, some network gear 255), is used in reconnaissance and in
  some firewall/IDS heuristics (Chapter 7 §5).

Common starting TTLs to recognize: **64 (Linux/macOS), 128 (Windows), 255 (many routers/BSD).** A
received TTL of 57 suggests a Linux host ~7 hops away (64 − 7).

### 4.5 Static vs. dynamic routing

- **Static routes** are configured by hand (or by IaC). **All VPC routing is static** — you write the
  route table entries; there is no dynamic routing protocol inside a basic VPC (though Transit
  Gateway and Direct Connect introduce BGP — Chapter 77). Static routing is simple, predictable, and
  auditable, which is why cloud uses it: the route table is a reviewable artifact.
- **Dynamic routing protocols** (OSPF, BGP, RIP, EIGRP) let routers exchange reachability information
  and adapt to changes automatically. They run the internet and large on-prem networks. The
  security-critical one is **BGP** (Border Gateway Protocol), the internet's inter-domain routing
  protocol — and, historically, trusting-by-default, leading to route hijacks (§4.6).

For a cloud security engineer, the essential knowledge is: **VPC routing is static and you own it**
(so audit it), and **the internet runs on BGP, which is a trust-based system vulnerable to hijacking**
(so understand the class, even though you rarely operate BGP directly).

### 4.6 BGP and the trust problem (internet-scale routing)

**BGP** connects the ~100,000 autonomous systems (ASes — networks under one administrative control,
each with an AS number) that make up the internet. Each AS *announces* which IP prefixes it can reach;
other ASes believe these announcements and route accordingly. The problem, familiar by now: **BGP
announcements are, by default, unauthenticated and trusted** — exactly the ARP/NDP/DNS pattern
(Chapters 9, 11, 17) at internet scale.

**BGP hijacking:** an AS announces a prefix it does not own (accidentally or maliciously); other ASes
believe it and route that prefix's traffic to the attacker. Because of longest-prefix match (§4.2),
announcing a *more specific* prefix than the legitimate owner captures the traffic. Real incidents:
traffic to cloud providers, DNS roots, and cryptocurrency services has been hijacked this way,
enabling interception and theft. Defenses (deployed by operators, not usually by you): **RPKI**
(Resource Public Key Infrastructure — cryptographically validates which AS may announce a prefix),
route filtering, and monitoring (BGP monitoring services alert on unexpected announcements of your
prefixes).

You will rarely configure BGP, but you must know: **the internet's routing is trust-based and
hijackable, so end-to-end encryption and authentication (TLS, DNSSEC) are essential precisely because
you cannot trust the path** — the same conclusion as Chapters 9 and 11, now at global scale.

---

## 5. Deep Technical Explanation: A Packet's Full Journey, with Routing

Combine Chapter 8 §5 (L2 delivery) with routing to trace a packet end to end, watching what changes
at each hop. Host A (`10.0.1.5`) sends to a web server (`93.184.216.34`):

```
 HOP 0 — Host A (10.0.1.5):
   Route lookup: 93.184.216.34 -> no specific route -> default 0.0.0.0/0 via 10.0.1.1
   Build frame: dst MAC = gateway 10.0.1.1's MAC (ARP), src MAC = A's, dst IP = 93.184.216.34, TTL=64
   Send.

 HOP 1 — Router 10.0.1.1 (the gateway):
   Receives frame (dst MAC = its own), strips L2, sees dst IP 93.184.216.34.
   Route lookup: longest-prefix match -> next hop 203.0.113.1 via its uplink interface.
   Decrement TTL 64 -> 63.
   Build NEW frame: dst MAC = 203.0.113.1's MAC, src MAC = router's uplink MAC. (L3 dst IP unchanged.)
   Forward.

 HOP 2..N — each router:
   Same: strip L2, route-lookup dst IP, decrement TTL, build new L2 frame for the next hop, forward.
   (This is where NAT may rewrite the source IP if crossing a NAT boundary — Chapter 14.)

 HOP N (final router, directly connected to 93.184.216.34's network):
   Route lookup: 93.184.216.34 is on a directly-connected network -> ARP for it, deliver.
   TTL now ~54 (started 64, ~10 hops).
```

Everything you learned converges here:

- **The dst IP (`93.184.216.34`) is constant end to end**; the dst MAC changes at every hop (Chapter
  8 §5). This is the single most important routing fact.
- **Each hop is an independent longest-prefix-match decision** (§4.2) — no router plans the whole
  path.
- **TTL decrements each hop** (§4.4), preventing loops and enabling `traceroute`.
- **ARP resolves each next hop** (Chapter 9) — which is why ARP spoofing at any hop is a MITM.
- **NAT may rewrite the source** at a boundary (Chapter 14) — the return path depends on the NAT
  table.

The security reading: **the path is a sequence of independent trust decisions, each hop trusting the
routing that got the packet to it, and each capable of reading/altering the packet if it is not
encrypted.** Any router on the path (a compromised one, a hijacked BGP route, an ARP-spoofing host at
a hop) is on-path. This is the mechanical foundation of "the network is untrusted" and thus of
end-to-end encryption (Chapters 9, 11, 28, 43): you cannot vet every hop, so you must make every hop
harmless with cryptography.

### 5.1 Route tables as a security control in the VPC

In a VPC, you write the route tables, and they *are* the reachability topology. The canonical
public/private distinction:

```
   PUBLIC subnet route table:
     10.20.0.0/16 -> local          (VPC-internal traffic stays in the VPC)
     0.0.0.0/0    -> igw-xxxx        (INTERNET GATEWAY -> this subnet is "public")

   PRIVATE app subnet route table:
     10.20.0.0/16 -> local
     0.0.0.0/0    -> nat-xxxx        (NAT gateway -> outbound-only internet; "private")

   PRIVATE data subnet route table:
     10.20.0.0/16 -> local
     (NO 0.0.0.0/0 route at all      -> NO internet path in OR out; fully isolated)
```

Read the security directly off the routes:

- **"Public" = has a route to an internet gateway.** One line. If a subnet meant to be private has a
  `0.0.0.0/0 -> igw` route, it is public — a critical finding, and a common one.
- **"Private with egress" = default route to a NAT gateway** (outbound + return only, no
  inbound-initiated — Chapter 14).
- **"Fully isolated" = no default route** — the data tier can only talk within the VPC (`local`),
  reaching the internet neither in nor out. This is the strongest routing-level isolation (Chapter 10
  §7, composing with SGs).
- **`local` is implicit and cannot be removed** — all subnets in a VPC can route to each other at the
  routing level by default (segmentation between them is done with SGs/NACLs, not routes, in a basic
  VPC — Chapters 75–76).

So **auditing route tables is a core cloud security review task**: for each subnet, what is its
default route (IGW = public, NAT = private-egress, none = isolated), and does that match its intended
role? A data subnet routing to an IGW, or an app subnet with no NAT (breaking egress), are the
findings. This is Chapter 75's material; the routing mechanics are here.

---

## 6. Internals: Observing Routing

### 6.1 Read the route table

```bash
$ ip route                          # IPv4 routes
$ ip -6 route                       # IPv6 routes (Chapter 11 — check these too!)
$ ip route get 93.184.216.34        # which route WOULD be used for this dst? (great for debugging)
93.184.216.34 via 10.0.1.1 dev eth0 src 10.0.1.5 ...
$ ip route get 10.0.2.50            # a local/other-subnet dst
```

`ip route get <dst>` is the single most useful routing-debug command: it tells you exactly which
route the kernel would select (longest-prefix match) and the next hop — answering "where would this
packet go?" without sending anything.

### 6.2 Trace the path (see hop-by-hop routing)

```bash
$ traceroute -n 93.184.216.34        # -n = numeric (Chapter 3: always numeric in security work)
 1  10.0.1.1      0.5 ms      # the gateway
 2  203.0.113.1   2.1 ms      # ISP edge
 3  198.51.100.9  8.4 ms
 ...
10  93.184.216.34 71.2 ms     # arrived
$ mtr -n 93.184.216.34               # continuous traceroute + loss stats (better for diagnosis)
```

`traceroute` reveals the actual path (§4.4 mechanism: increasing TTLs eliciting ICMP Time Exceeded).
In security work it shows *where* traffic goes (unexpected hops = possible redirection/hijack),
*where* it stops (a `* * *` at a firewall that drops the probes), and the path's geography (traffic
to a domestic service routing through an unexpected country is a hijack signal).

### 6.3 Enable/inspect forwarding (host-as-router)

```bash
$ cat /proc/sys/net/ipv4/ip_forward         # 0 = host does not forward; 1 = it routes
$ sudo sysctl -w net.ipv4.ip_forward=1       # make the host a router (also what an ARP-MITM needs)
```

`ip_forward=1` turns a host into a router — legitimate for NAT instances/routers, and exactly what an
ARP-spoofing MITM enables to relay traffic (Chapter 9 §4.4). Seeing forwarding enabled on a host that
should not route is a red flag.

### 6.4 The VPC route table (cloud)

```bash
$ aws ec2 describe-route-tables --query \
  'RouteTables[].{id:RouteTableId, routes:Routes[].{dst:DestinationCidrBlock, gw:GatewayId, nat:NatGatewayId}}'
# For each subnet's route table, check the 0.0.0.0/0 target:
#   igw-* -> PUBLIC subnet ;  nat-* -> private-egress ;  (none) -> isolated
```

This is the audit: enumerate route tables, find each subnet's default route, and confirm public/
private/isolated matches intent. A data subnet with `0.0.0.0/0 -> igw-*` is the critical finding.

---

## 7. Real-World Example: The Ledger VPC Routing

System B's routing, making the address plan from Chapter 10 §7 into actual reachability:

```
   VPC 10.20.0.0/16, three route tables:

   RT-public (attached to public subnets 10.20.0.0/24, 10.20.1.0/24):
     10.20.0.0/16 -> local
     0.0.0.0/0    -> igw-ledger        # ALB and NAT GW live here; internet-facing

   RT-app (attached to app subnets 10.20.10.0/24, 10.20.11.0/24):
     10.20.0.0/16 -> local
     0.0.0.0/0    -> nat-ledger        # ECS tasks: outbound updates/APIs, no inbound from internet

   RT-data (attached to data subnets 10.20.20.0/24, 10.20.21.0/24):
     10.20.0.0/16 -> local
     (no default route)                # RDS/ElastiCache: no internet path at all
```

The security properties, read off the routes:

- **RDS is not internet-reachable** because RT-data has *no route to the internet* — not in, not out.
  Combined with its private IP (Chapter 10) and its security group (Chapter 76), that is three
  independent layers providing "not internet-reachable" (Chapter 4 §7). Even if someone opened the
  SG, the route table still blocks internet reachability.
- **ECS tasks can reach the internet outbound** (for pulling images, calling external APIs) via the
  NAT gateway, but cannot be reached inbound from the internet — the NAT provides outbound-only
  (Chapter 14). This is the "private with egress" pattern.
- **The ALB is internet-facing** because it lives in a public subnet with an IGW route.
- **All tiers can route to each other** (`local`), so segmentation between app and data is enforced by
  **security groups**, not routes (in this basic design) — a key distinction: routes provide coarse
  internet-vs-not isolation, SGs provide fine tier-to-tier control (Chapters 75–76).

The findings a reviewer looks for, all routing-level:
- RT-data with a `0.0.0.0/0 -> igw` route (data tier made public — critical).
- RT-app with no NAT route (egress broken — a functionality bug that also breaks security updates).
- A route to a peering connection or Transit Gateway that unexpectedly widens reachability to another
  VPC (Chapter 77).

Routing is thus the *first* layer of the network security review (Chapter 4's Stop 2): before
checking security groups, check that the route tables put each subnet in its intended
internet/isolation posture. This is the same route-table construct as any router, now as a cloud
security control you own and audit.

---

## 8. Hands-On Demonstration

### LAB 12.1 — Routing, Longest-Prefix Match, and a Simulated Public/Private Topology

**Objective.** Read and reason about route tables, prove longest-prefix match, build a two-subnet
routed topology with a "router" container (public vs. private behavior), and observe the hop-by-hop
path and TTL mechanism.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 60–90 minutes.

**Steps.**

*Step 1 — Read your own routing and use `ip route get`.*

```bash
ip route
ip route get 8.8.8.8              # -> default route (internet)
ip route get 127.0.0.1           # -> loopback
# If on a multi-subnet host, try a same-subnet and other-subnet destination.
```

Predict each result (default vs. directly-connected) before running.

*Step 2 — Longest-prefix match (reason, then verify).*

```bash
# Add competing routes (in a throwaway namespace to avoid disrupting the host):
sudo ip netns add lpmtest
sudo ip netns exec lpmtest ip route add 10.0.0.0/16 dev lo 2>/dev/null || true
# (Simplest: reason on paper against a table, then verify with `ip route get` in a real setup.)
python3 - <<'PY'
import ipaddress
routes = {"0.0.0.0/0":"internet", "10.0.0.0/16":"vpc", "10.0.5.0/24":"peering", "10.0.5.128/25":"appliance"}
nets = sorted(((ipaddress.ip_network(c), n) for c,n in routes.items()), key=lambda x:-x[0].prefixlen)
for dst in ["10.0.5.200","10.0.5.50","10.0.9.9","8.8.8.8"]:
    a = ipaddress.ip_address(dst)
    chosen = next((n for net,n in nets if a in net), "DROP")
    print(f"{dst:12} -> {chosen}   (longest-prefix match)")
PY
sudo ip netns del lpmtest 2>/dev/null
```

**Expected:** `10.0.5.200`→appliance (/25), `10.0.5.50`→peering (/24), `10.0.9.9`→vpc (/16),
`8.8.8.8`→internet (/0). Confirm your paper reasoning matches — longest prefix always wins.

*Step 3 — Build a routed topology (public vs private via a router container).*

```bash
# Two isolated networks joined by a router container:
docker network create --internal privnet --subnet 10.50.2.0/24     # --internal = NO gateway to host/internet
docker network create pubnet --subnet 10.50.1.0/24
docker run -d --name router  --network pubnet --cap-add NET_ADMIN nicolaka/netshoot sleep 3600
docker network connect privnet router                              # router straddles both
docker run -d --name privhost --network privnet nicolaka/netshoot sleep 3600
docker run -d --name pubhost  --network pubnet  nicolaka/netshoot sleep 3600
# Enable forwarding on the router:
docker exec router sysctl -w net.ipv4.ip_forward=1
# privhost has no internet route (privnet is --internal) -> demonstrate:
docker exec privhost sh -c 'ip route; echo "---"; ping -c1 -W2 8.8.8.8 || echo "NO internet route (private): expected"'
```

**Expected:** `privhost` on the `--internal` network has no default route to the internet — it is
"private" purely by *routing* (no path out), mirroring a VPC data subnet with no IGW route. This
demonstrates that routing alone determines internet reachability.

*Step 4 — Add a route and observe reachability change.*

```bash
# Give privhost a route to reach pubnet via the router, and enable the return path:
ROUTER_PRIV=$(docker inspect -f '{{(index .NetworkSettings.Networks "privnet").IPAddress}}' router)
docker exec privhost ip route add 10.50.1.0/24 via ${ROUTER_PRIV}
docker exec privhost sh -c "ping -c2 $(docker inspect -f '{{(index .NetworkSettings.Networks \"pubnet\").IPAddress}}' pubhost) && echo 'cross-subnet routing works'"
```

**Security implication:** adding one route changed reachability. In a VPC, this is exactly how a
peering route or a mistaken `0.0.0.0/0 -> igw` widens access — a single route line is an access
decision.

*Step 5 — Observe TTL and path.*

```bash
docker exec pubhost sh -c 'traceroute -n -m 5 8.8.8.8 || true'   # see hops (limited in containers)
docker exec pubhost sh -c 'ping -c1 8.8.8.8 | grep ttl'          # observe received TTL
```

**Security implications.** Write down: (a) how the route table alone made `privhost` private (no
internet path); (b) how longest-prefix match selects routes; (c) how one added route changes
reachability (the VPC route-table finding); (d) that every hop can read unencrypted traffic (why
encryption is required).

**Cleanup.**
```bash
docker rm -f router privhost pubhost; docker network rm pubnet privnet
```

---

## 9. Security Implications

- **The route table defines reachability, which is access.** In the cloud you own it, so it is a
  control you configure and must audit. A missing route is implicit deny; an unintended route is
  implicit allow.
- **"Public vs private" is a routing decision:** a subnet is public iff it has a route to an internet
  gateway. This is often the first and most consequential network-security setting.
- **Longest-prefix match governs route selection** — a more specific route overrides a general one,
  which is how both legitimate overrides and routing attacks (specific-prefix injection/hijack) work.
- **Every hop is on-path** for unencrypted traffic — the path is a sequence of independent trust
  decisions you cannot vet, which is the mechanical basis for end-to-end encryption (Chapters 9, 28,
  43).
- **BGP (internet routing) is trust-based and hijackable** — reinforcing that you cannot trust the
  path, at global scale; defenses (RPKI) are operator-side, so end-to-end crypto is your control.
- **Route-table audit is a core review task**: verify each subnet's default route matches its intended
  internet/isolation posture; a data subnet routing to an IGW is a critical finding.

---

## 10. Attack Scenarios

1. **Misconfigured VPC route (data subnet → IGW):** a private/data subnet with a `0.0.0.0/0 -> igw`
   route becomes internet-reachable — a critical, common misconfiguration (§5.1, §7).
2. **BGP hijacking** (§4.6): an AS announces a prefix it does not own (a more-specific prefix wins via
   longest-prefix match), rerouting internet traffic to the attacker for interception/theft. Real
   incidents against cloud, DNS, and crypto services. Defense: RPKI, route monitoring; user defense:
   end-to-end TLS/DNSSEC.
3. **ICMP redirect abuse** (Chapter 23): an attacker sends ICMP Redirect messages to trick a host
   into using the attacker as a "better" router — a local routing-based MITM. Defense: ignore ICMP
   redirects (`accept_redirects=0`).
4. **Route injection / static route tampering:** an attacker with access to a host or router adds a
   specific route to capture traffic to a target (longest-prefix match ensures it wins). Defense:
   restrict who can modify routes; monitor route changes.
5. **Host-as-rogue-router:** an attacker enables `ip_forward` and combines with ARP/NDP spoofing to
   relay and inspect traffic (Chapter 9 §4.4). Defense: detection of unexpected forwarding + the ARP
   defenses.
6. **Overly broad peering/Transit Gateway routes** (Chapter 77): a route that connects a VPC to a
   less-trusted VPC/network wider than intended, exposing internal services across the peering.

---

## 11. Defensive Techniques

- **Audit route tables as a first-class review item.** For every subnet, confirm the default route
  matches intent: IGW = public (only where intended), NAT = private-egress, none = isolated. Flag any
  data/internal subnet with an internet-gateway route. Automate with Config rules / policy-as-code
  (Chapters 82, 91).
- **Use routing for coarse isolation, SGs/NACLs for fine control.** Give sensitive tiers *no internet
  route* (strongest isolation), and rely on security groups for tier-to-tier rules. Routing and SGs
  are complementary layers (defense in depth).
- **Least-route:** add only the routes needed. Broad peering/TGW routes widen reachability; scope
  them tightly and review them (Chapter 77).
- **Restrict and monitor route changes.** Who can modify VPC route tables (IAM), host route tables
  (root), and BGP announcements should be tightly controlled and logged (CloudTrail on route-table
  changes is a high-value signal).
- **Disable ICMP redirects** on hosts (`net.ipv4.conf.all.accept_redirects=0`,
  `secure_redirects=0`) and disable forwarding where not needed (`ip_forward=0`).
- **For internet routing, rely on end-to-end crypto.** You cannot control BGP, so TLS/mTLS + DNSSEC
  make path compromise (hijack, on-path routers) harmless — the load-bearing control (Chapters 9, 28,
  43). Consider BGP monitoring for your own prefixes if you announce them.

---

## 12. Production Architecture

Routing as a security layer, VPS vs cloud, and how it composes:

```
 CONCEPT                 SYSTEM A (VPS)                SYSTEM B (AWS VPC)
 ---------------------   ---------------------------   ---------------------------------------
 route table             host `ip route`               VPC route tables (you write them = IaC)
 "public"                has default gw to internet    subnet route 0.0.0.0/0 -> IGW
 "private + egress"      via NAT (if any)              subnet route 0.0.0.0/0 -> NAT gateway
 "fully isolated"        no default route              subnet route table with no 0.0.0.0/0
 inter-network           static routes / gateway       local route + peering/TGW routes (Ch.77)
 internet routing        BGP (ISP's problem)           BGP (AWS + Direct Connect/TGW)
 coarse isolation        routing                       routing (internet-vs-not)
 fine isolation          host firewall                 security groups / NACLs (Ch.76)
 load-bearing control    TLS/mTLS                       TLS/mTLS (path always untrusted)
```

The architectural principle: **routing provides the coarse reachability topology (can these networks
reach each other / the internet at all), and security groups/NACLs provide the fine-grained access
control on top.** Design the routing first — which subnets are public, private-egress, or isolated —
because it is the foundation the finer controls build on, and because a routing mistake (a data subnet
routed to an IGW) can expose a resource regardless of its security group. In the cloud, route tables
are IaC artifacts (Chapter 88), so they are reviewable and testable — treat them as security code.

---

## 13. Common Mistakes

1. **Data/internal subnet routed to an internet gateway** — makes it public; the classic critical
   routing finding.
2. **Confusing route selection with firewall evaluation** — routing is longest-prefix (specificity),
   SGs are any-allow, NACLs are ordered (Chapter 76). Different algorithms.
3. **Forgetting IPv6 routes** (Chapter 11) — a subnet private on IPv4 (NAT) but with an IPv6 IGW
   route is IPv6-public.
4. **Overly broad peering/TGW routes** widening reachability beyond intent (Chapter 77).
5. **Leaving `ip_forward` enabled** on hosts that should not route (an ARP-MITM enabler).
6. **Not disabling ICMP redirects** — a local routing-MITM vector.
7. **Relying on routing alone for tier isolation** within a VPC (all subnets can `local`-route to each
   other; use SGs for tier-to-tier).
8. **Not monitoring route-table changes** — an added route is an access change that should be logged
   and reviewed.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Host can't reach the internet | no/incorrect default route, or NAT/IGW issue | `ip route` (default present?); `ip route get 8.8.8.8`; VPC route table |
| Two subnets can't communicate | no route between them, or SG/NACL block | `ip route get <dst>`; check VPC routes + SGs (Chapter 76) |
| Traffic takes an unexpected path | route override (more specific), redirect, or hijack | `traceroute -n`; check for injected specific routes; `ip route get` |
| Private resource is internet-reachable | subnet routed to IGW (should be NAT/none) | inspect the subnet's route table default target |
| Egress broken from private subnet | no NAT route (or NAT GW down) | check `0.0.0.0/0 -> nat-*`; NAT GW health |
| Intermittent MITM / redirected traffic | ICMP redirects accepted, or ARP-MITM + forwarding | `sysctl net.ipv4.conf.all.accept_redirects`; check `ip_forward` on suspect hosts |
| `traceroute` shows `* * *` then stops | a firewall dropping probes (not necessarily a fault) | expected at filtering boundaries; try `-T`/`-I` variants (Chapter 23) |

---

## 15. Practical Lab

Lab 12.1 is in §8. Register it in the lab index. Extension (AWS): audit a real VPC's route tables —
for every subnet, identify the default-route target (IGW/NAT/none), classify it public/private-egress/
isolated, and verify it matches the subnet's intended role; produce a findings list of any mismatches
(data subnet → IGW being the headline). This is the routing half of a VPC security review (the SG half
is Chapter 76).

---

## 16. Exercises

### Concept questions

**12.1** Explain longest-prefix match and why route selection uses specificity rather than order.
Given routes `/0`, `/16`, `/24`, `/25`, which is chosen for a destination in the `/25` range, and why?

**12.2** How does a subnet become "public" vs "private" vs "fully isolated" purely in terms of routing?
Give the route-table entry for each.

**12.3** Explain what changes and what stays constant as a packet crosses each router hop (L2, L3,
TTL). Why does the dst IP never change but the dst MAC always does?

**12.4** What is TTL for, and how does `traceroute` exploit it? What does a received TTL tell you?

**12.5** Explain BGP hijacking and why longest-prefix match makes a more-specific announcement
effective. What defends it, and why must end users rely on end-to-end encryption regardless?

### Debugging problems

**12.6** A private subnet's instances suddenly have internet access they should not. Nothing in the
security groups changed. Where do you look, and what is the likely cause?

**12.7** An app in a private subnet cannot pull container images (egress fails), though it could
yesterday. SGs are unchanged. Diagnose using routing.

**12.8** Traffic to an internal service is being intercepted; `traceroute` shows an unexpected extra
hop. Give two routing-based causes and how to confirm each.

### Security scenarios

**12.9** You are auditing a VPC. Describe your route-table review methodology and the specific findings
you look for, ranked by severity.

**12.10** A team wants to peer their production VPC with a partner's VPC "to share a service." Explain
the routing-based risks and how you would scope the routes to minimize exposure.

### Architecture questions

**12.11** Design the route tables for a three-tier VPC (public/app/data) across two AZs, specifying
each subnet's default route and justifying the internet/isolation posture of each tier.

**12.12** Explain how routing and security groups are complementary layers, and give an example where
routing provides a security property that a security group cannot, and vice versa.

### Hands-on exercises

**12.13** Use `ip route get` to determine the next hop for five destinations on your host and explain
each selection in terms of the route table.

**12.14** Build the public/private container topology from Lab 12.1 and demonstrate that a
`--internal` network host has no internet path purely due to routing.

**12.15** Write a script that reads a VPC's route tables (or a mock JSON) and classifies each subnet as
public/private-egress/isolated based on its default-route target, flagging any data-tier subnet routed
to an IGW.

### Interview questions

**12.16** "Walk me through what happens at each router hop as a packet crosses the internet."

**12.17** "How is a subnet made public or private in a VPC? What's the actual mechanism?"

**12.18** "Explain longest-prefix match and how it relates to BGP hijacking."

**12.19** "How would you audit a VPC's routing for security issues?"

**12.20** "Why can't you trust the network path, and what do you do about it?"

---

## 17. Summary

- **Routing forwards each packet toward its destination by longest-prefix match on a route table,
  hop by hop, each hop an independent decision.** The path emerges from many local choices.
- A **route table** maps destination CIDRs to next hops; entries are directly-connected (`scope link`,
  deliver via ARP/L2) or routed (`via` a gateway), with the **default route `0.0.0.0/0`** as the
  catch-all.
- **Longest-prefix match** (most specific wins) is *the* route-selection rule — the basis of
  legitimate overrides and of specific-prefix routing attacks; it is distinct from firewall rule
  evaluation (Chapter 76).
- Across hops, the **dst IP is constant, the dst MAC is rewritten each hop, and the TTL decrements**
  (loop prevention + `traceroute`). ARP resolves each next hop; NAT may rewrite the source.
- **In the cloud, you write the route tables, so routing is a security control you own:** a subnet is
  **public (route to IGW), private-egress (route to NAT), or fully isolated (no default route)** —
  decided by one line. Route-table audit is a core review task; a data subnet routed to an IGW is a
  critical finding.
- **Routing provides coarse reachability; security groups/NACLs provide fine access control** — they
  are complementary layers (defense in depth).
- **The path is a sequence of untrusted, independent trust decisions** (compromised routers, ICMP
  redirects, and internet-scale **BGP hijacking**, which longest-prefix match makes effective), so
  **end-to-end encryption (TLS/mTLS) + DNSSEC is the load-bearing control** — you cannot vet every
  hop, so you make every hop harmless.

---

## 18. Knowledge Check

1. State the longest-prefix-match rule and pick the winner among /0,/16,/24,/25 for a /25-range dst. (§4.2)
2. What single route-table entry makes a subnet public? Private-egress? Isolated? (§5.1)
3. What changes and what stays constant at each hop? (§5)
4. What is TTL for, and how does traceroute use it? (§4.4)
5. What is BGP hijacking, and why does longest-prefix match matter to it? (§4.6)
6. Why is a data subnet routed to an IGW a critical finding? (§5.1, §7)
7. How do routing and security groups differ in what they control? (§5.1, §12)
8. What does `ip route get <dst>` tell you? (§6.1)
9. Why is `ip_forward=1` on an unexpected host a red flag? (§6.3)
10. Why must you rely on end-to-end encryption despite good routing? (§5, §4.6)

---

## 19. Further Exploration

- `man ip-route`; practice `ip route get <dst>` against many destinations until route selection is
  intuitive.
- Run `traceroute`/`mtr` to services in different regions and note the paths, hop counts, and where
  probes get filtered — build intuition for "normal."
- Read about a real BGP hijack incident (e.g. the 2018 Amazon Route 53 / MyEtherWallet hijack) and
  trace how longest-prefix match + trust enabled it and how end-to-end TLS would/would not have helped.
- AWS VPC route table documentation — then audit a real or Terraform-defined VPC's route tables per
  §15.
- RPKI overview (from an RIR like ARIN/RIPE) — understand the operator-side BGP defense you will
  reference but rarely operate.

---

## Solutions

### 12.1
Longest-prefix match selects, among all routes whose CIDR contains the destination, the one with the
**longest (most specific) prefix**. Route selection uses specificity rather than order because a more
specific route represents more precise knowledge of how to reach a destination — `10.0.5.128/25` is
"I know exactly this range's next hop," which should override the vaguer `0.0.0.0/0` catch-all
regardless of where each appears in the table. (Contrast firewall rules, which are order/first-match
or any-allow — Chapter 76.) For a destination in the `/25` range, all four routes (/0, /16, /24, /25)
match, and the **/25 wins** because it is the longest matching prefix — the router uses its most
specific knowledge. For a destination in the /24 but outside the /25, the /24 wins; outside the /24
but in the /16, the /16; otherwise the default /0.

### 12.2
Purely by the subnet's route table default entry: **Public** — has `0.0.0.0/0 -> internet gateway
(igw-*)`, so it can initiate and receive internet traffic (with a public IP). **Private with egress**
— has `0.0.0.0/0 -> NAT gateway (nat-*)`, so instances can initiate outbound internet connections and
receive the returns, but cannot be reached inbound-initiated from the internet. **Fully isolated** —
has **no `0.0.0.0/0` route at all**, only the implicit `local` route for the VPC CIDR, so it can
reach only within the VPC — no internet path in or out. The presence and target of the default route
is the entire mechanism; changing that one line changes the subnet's internet posture, which is why a
data subnet accidentally routed to an IGW is a critical finding.

### 12.3
Constant: the **destination IP address** (the final target) and normally the source IP (unless NAT
rewrites it at a boundary). Changes at every hop: the **entire Layer 2 (Ethernet) header** — each
router strips the incoming frame and builds a new one with source MAC = its outgoing interface and
destination MAC = the next hop's MAC (resolved via ARP/NDP); and the **TTL decrements by 1**. The dst
IP never changes because it names the ultimate endpoint, which routing is trying to reach — the whole
point is end-to-end delivery to that address. The dst MAC always changes because MAC addressing is
local-scope (Chapter 8): it only ever identifies the *next device on the current segment*, which is a
different device at each hop. So L3 addressing is end-to-end and stable; L2 addressing is per-hop and
rewritten — the unifying fact of Chapters 8, 10, and 12.

### 12.4
TTL (Time To Live) prevents packets from circulating forever in a routing loop: each router
decrements it, and a packet reaching TTL 0 is dropped, with an ICMP "Time Exceeded" sent back to the
source. Without it, a misconfigured loop would saturate links indefinitely. `traceroute` exploits
this by sending packets with deliberately small TTLs — TTL=1 elicits a Time Exceeded from the first
router (revealing hop 1), TTL=2 from the second, and so on — so the increasing TTLs map out the
hop-by-hop path via the ICMP responses. A received TTL tells you roughly how many hops away the sender
is and often hints at its OS: common starting values are 64 (Linux/macOS), 128 (Windows), 255 (many
routers/BSD), so a received TTL of 57 suggests a Linux host ~7 hops away (64−7). This is used in OS
fingerprinting and some IDS/firewall heuristics.

### 12.5
BGP hijacking is when an autonomous system announces (via BGP) that it can reach an IP prefix it does
not legitimately own; because BGP announcements are trusted by default, other ASes believe it and
route that prefix's traffic toward the hijacker, enabling interception, blackholing, or theft.
Longest-prefix match makes it especially effective: if the attacker announces a **more specific**
prefix (e.g. a /24 within the victim's /16), routers everywhere prefer the more-specific route over
the legitimate less-specific one, so the hijack captures the traffic even alongside the real
announcement. Defenses (operator-side): **RPKI** (cryptographically validates which AS may originate a
prefix, so invalid announcements are dropped), route filtering by transit providers, and BGP
monitoring that alerts owners to unexpected announcements of their prefixes. End users cannot control
internet routing, so they must rely on **end-to-end encryption and authentication** — TLS (server
cert validation defeats interception; a hijacker cannot present a valid cert) and DNSSEC — which make
a hijacked path harmless: the attacker sees ciphertext and cannot impersonate the destination. This
is the same "you can't trust the path, so authenticate the endpoints" conclusion as ARP/NDP, at
global scale.

### 12.6
Look at the **route table** of the private subnet(s), because internet access is a routing property
independent of security groups. The likely cause is that the subnet's route table was changed to add
(or was re-associated with a route table that has) a `0.0.0.0/0 -> internet gateway (igw-*)` route,
turning the "private" subnet public — perhaps someone attached the wrong route table, added an IGW
route "to fix egress" instead of using a NAT gateway, or a Terraform change altered the association.
Confirm via `describe-route-tables` for that subnet and check the default-route target (should be a
NAT gateway or absent, not an IGW), and check CloudTrail for recent `CreateRoute`/`ReplaceRoute`/
`AssociateRouteTable` events. Fix: remove the IGW route (use a NAT gateway if egress is needed), and
add a Config rule / policy-as-code check to prevent data/private subnets from having IGW routes. The
lesson: internet reachability is decided by routing first, so this class of "why is it exposed" is a
route-table question, not an SG question.

### 12.7
Egress from a private subnet depends on a `0.0.0.0/0 -> NAT gateway` route (and a healthy NAT). Since
SGs are unchanged and it worked yesterday, check routing/NAT: (1) the subnet's route table — is the
`0.0.0.0/0 -> nat-*` route still present and pointing at the correct, existing NAT gateway? A route
removed or the NAT gateway deleted/recreated (new ID) breaks egress. (2) NAT gateway health/state
(`describe-nat-gateways`) — is it available, in a public subnet with an IGW route, and not out of
Elastic IP / capacity? (3) The NAT's own subnet route table — the NAT must be in a public subnet with
a route to the IGW to function. (4) `ip route`/`ip route get` from an instance shows whether the
default route resolves. Most likely: the NAT gateway was replaced (IDs change) and the route table
still points at the old ID, or the NAT's public-subnet IGW route was disturbed. Fix the route to
point at the current NAT gateway and ensure the NAT's public path is intact. Confirm with CloudTrail
for recent NAT/route changes.

### 12.9
Methodology: enumerate all route tables and their subnet associations; for each subnet, identify the
**default-route target** and classify it — IGW = public, NAT = private-egress, none = isolated — then
verify the classification matches the subnet's intended role (from tags/naming/design). Also inspect
peering/Transit Gateway/VPN/Direct Connect routes for scope, IPv6 routes (Chapter 11), and any
suspiciously specific routes (possible redirection). Findings ranked by severity: (1) **Critical** — a
data/sensitive subnet with a `0.0.0.0/0 -> IGW` route (internet-exposed data tier), or an IPv6 IGW
route on a subnet meant to be private. (2) **High** — overly broad peering/TGW routes exposing
internal services to another VPC/network beyond intent; a public subnet where a private one was
intended. (3) **Medium** — private subnet missing its NAT route (broken egress, which also breaks
security updates — an availability-and-security issue), or routes to decommissioned/unknown targets.
(4) **Low/informational** — inconsistent route tables across AZs, missing IPv6 routes where IPv6 is
used. Cross-check with CloudTrail for recent route changes and pair the routing findings with the SG
review (Chapter 76) for the full picture. Automate the classification (Ex. 12.15) and enforce with
Config/policy-as-code.

### 12.11
Route tables (VPC 10.20.0.0/16, two AZs): **Public subnets** (10.20.0.0/24, 10.20.1.0/24) — route
table RT-public with `10.20.0.0/16 -> local` and `0.0.0.0/0 -> igw-*`; hosts the ALB and NAT
gateways, which must be internet-facing. **App subnets** (10.20.10.0/24, 10.20.11.0/24) — RT-app with
`10.20.0.0/16 -> local` and `0.0.0.0/0 -> nat-*` (NAT gateway in the public subnet of the same AZ for
resilience); ECS tasks can make outbound calls (image pulls, external APIs, security updates) but
cannot be reached inbound from the internet. **Data subnets** (10.20.20.0/24, 10.20.21.0/24) — RT-data
with only `10.20.0.0/16 -> local` and **no default route**; RDS/ElastiCache have no internet path in
or out, the strongest routing-level isolation. Justification: the data tier needs no internet, so
give it none (and combine with private IPs and SGs — three layers, Chapter 4 §7); the app tier needs
outbound-only, provided by NAT; the public tier hosts only the internet-facing edge. Use per-AZ NAT
gateways so an AZ failure does not break the other AZ's egress. Tier-to-tier access (app→data) is
enforced by security groups, not routes, since all subnets can `local`-route within the VPC.

### 12.16
At each hop a router: (1) receives the frame (its own MAC is the L2 destination) and strips the L2
header; (2) reads the packet's destination IP and performs a **longest-prefix-match** lookup in its
route table to find the next hop; (3) decrements the TTL by 1 (dropping the packet and returning ICMP
Time Exceeded if it hits 0 — loop prevention); (4) resolves the next hop's MAC (via ARP/NDP) and
builds a **new** L2 frame with its own outgoing interface MAC as source and the next hop's MAC as
destination — the **destination IP is unchanged**; (5) forwards it out the appropriate interface. At a
NAT boundary it also rewrites the source IP/port and records the mapping (Chapter 14). This repeats,
independently, at every router — no router knows the whole path — until a router finds the destination
on a directly-connected network and delivers it via ARP. The constants are the source/destination IPs
(barring NAT); the per-hop changes are the entire L2 header and the decrementing TTL. Bonus: mention
that any hop can read/alter unencrypted traffic, which is why TLS is needed, and that internet routing
between ASes is BGP.

### 12.17
Mechanism: a subnet's **route table** determines its internet posture. A subnet is **public** when its
route table contains `0.0.0.0/0 -> internet gateway (igw-*)` (and instances have public IPs), giving
inbound and outbound internet connectivity. It is **private (with egress)** when the default route
points to a **NAT gateway** (`0.0.0.0/0 -> nat-*`), allowing outbound-initiated connections and their
returns but no inbound-initiated internet traffic. It is **fully isolated** when there is **no default
route** — only the implicit `local` route — so it can reach nothing outside the VPC. There is no
"public/private" flag on a subnet per se; it is entirely a function of the associated route table's
default-route target (plus whether instances get public IPs and the security groups). That is why the
security review starts with route tables: one line decides internet reachability, and a data subnet
mistakenly routed to an IGW is publicly exposed regardless of its security groups.

### 12.18
Longest-prefix match: when multiple routes match a destination, the router selects the one with the
longest (most specific) prefix, because it represents the most precise reachability knowledge — a /24
route beats a /16 beats a /0 for an address they all contain. It relates to BGP hijacking because BGP
distributes reachability by prefix announcements, and routers apply longest-prefix match to choose
among them: if an attacker announces a **more specific** prefix (a /24 carved out of the victim's
legitimately announced /16), routers worldwide prefer the attacker's more-specific route over the
real one, capturing that traffic even though the legitimate announcement still exists. So the same
rule that makes routing efficient and precise also makes a more-specific hijack devastatingly
effective — the attacker does not need to suppress the real route, just to be more specific. Defenses
(RPKI, filtering) validate origin authorization; end users rely on end-to-end TLS/DNSSEC because they
cannot control which routes the internet believes.

### 12.19
Enumerate every route table and its subnet associations, and for each subnet determine its
default-route target to classify it public (IGW) / private-egress (NAT) / isolated (none), then
compare against intended role. Check: (1) any sensitive/data subnet with an IGW route (critical
exposure), including IPv6 IGW routes (Chapter 11); (2) peering/Transit Gateway/VPN/Direct Connect
routes and whether they widen reachability to less-trusted networks beyond intent; (3) private subnets
missing NAT routes (broken egress → failed security updates); (4) overly specific or unknown-target
routes (possible tampering/redirection); (5) consistency across AZs. Cross-reference CloudTrail for
recent route-table changes (`CreateRoute`, `ReplaceRoute`, `AssociateRouteTable`) to catch drift, and
pair with the security-group review (Chapter 76) since routing gives coarse reachability and SGs give
fine control. Automate the classification and enforce with Config rules / policy-as-code so
data-subnet-to-IGW routes cannot be introduced. Deliverable: a per-subnet posture table with findings
ranked by severity, IGW-on-data-tier being the headline.

### 12.20
Because a packet traverses many independent routers you neither own nor can vet, and internet routing
itself (BGP) is trust-based and hijackable — so any hop (a compromised router, a rogue on-path host
via ARP/NDP spoofing, an ICMP-redirect trick, or a hijacked BGP route) can read or alter unencrypted
traffic, and you cannot prevent this at the routing layer for traffic beyond your control. What you do
about it: **make the path irrelevant with end-to-end cryptography** — TLS/mTLS so any on-path party
sees only ciphertext and cannot impersonate the endpoint (certificate validation defeats
interception), plus DNSSEC/trusted resolvers so name resolution is not subverted (Chapter 17). Within
your own networks you additionally reduce the likelihood of on-path attackers (routing isolation, ARP/
NDP defenses, restricting who can change routes), but the load-bearing control is encryption, because
it holds even when the path is fully compromised. This is Zero Trust at the network layer: never trust
the path; authenticate and encrypt the endpoints — the same conclusion reached from ARP (Chapter 9),
IPv6 NDP (Chapter 11), and now internet routing.

---

*Next: Chapter 13 — Switching, VLANs, Trunks, and Layer 2 Segmentation. We return to Layer 2 to see
how VLANs carve one physical switch into isolated broadcast domains (the on-prem analogue of subnets),
how trunks carry multiple VLANs, and the VLAN-hopping attacks that defeat this segmentation — plus how
the cloud replaces all of it with subnets and security groups.*
