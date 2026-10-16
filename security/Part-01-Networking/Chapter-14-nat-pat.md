# Chapter 14 — NAT and PAT: Address Translation, Connection Tables, and Why NAT Is Not a Firewall

---

## 1. Why This Matters

NAT (Network Address Translation) is the reason the IPv4 internet still functions despite address
exhaustion (Chapter 10), and it is the mechanism behind the AWS NAT gateway you already met in the
routing chapter (Chapter 12 §5.1). For a cloud security engineer, NAT matters because:

1. **The NAT gateway is a core VPC construct.** "Private subnet with egress" (Chapter 12) means "routes
   `0.0.0.0/0` to a NAT gateway." Understanding what NAT actually does — and what it does not — is
   understanding what that gateway provides your workloads and what it costs.
2. **NAT is chronically misunderstood as a security control.** "We're behind NAT, so we're safe" is a
   belief that has caused real breaches. NAT provides an *accidental* inbound-blocking side effect
   (Chapter 11 §4.5), but it is **not a firewall**, and conflating the two is a serious analytical
   error you must be able to correct precisely.
3. **NAT's connection table is a stateful table** — the same concept as connection tracking (Chapter
   37) and stateful firewalls / security groups (Chapter 76). Understanding NAT's table is understanding
   how "stateful" works, and it is a finite resource (a DoS target and a scaling limit — the NAT
   gateway's connection/bandwidth limits are real operational and security concerns).
4. **NAT complicates logging, attribution, and egress control.** Many hosts share one public IP behind
   NAT, so "which internal host made this connection?" requires the NAT table or logs — relevant to
   incident response and to the egress-exfiltration problem (Chapter 3 §10.2).

The core idea: **NAT rewrites the source (and/or destination) address and port of packets as they cross
a boundary, maintaining a table to reverse the translation for return traffic. Its primary purpose is
address conservation (many private hosts sharing few public IPs), and its inbound-blocking effect is a
side effect of needing an existing table entry — not a security policy.** Getting the "not a firewall"
distinction exactly right is one of the clarifying things a cloud security engineer does in reviews.

---

## 2. Prerequisites

- Chapter 10 (private vs public addresses, RFC 1918 — NAT translates between them) and Chapter 12 (NAT
  gateways in route tables; the packet's journey).
- Chapter 3 (the 4-tuple, ephemeral ports, connection state) — NAT keys on the tuple.
- Chapter 11 §4.5 (IPv6 has no NAT — the contrast that clarifies NAT's real role).

---

## 3. Mental Model

**NAT is a translator at a network boundary that rewrites addresses/ports and remembers each
translation in a table so it can rewrite the replies back. It lets many private hosts share few public
addresses. Its security-relevant behavior — blocking unsolicited inbound — is a consequence of the
table, not a firewall policy.**

```
   Many private hosts -> ONE public IP (PAT / "NAT overload"):

   Private host 10.0.1.5:41000 --> [ NAT ] --> 203.0.113.9:52000 --> Internet server 8.8.8.8:443
                                      |
                             NAT TABLE (the state):
                             10.0.1.5:41000 <-> 203.0.113.9:52000 -> 8.8.8.8:443

   Reply from 8.8.8.8:443 to 203.0.113.9:52000
        NAT looks up the table -> rewrites dst back to 10.0.1.5:41000 -> delivers.

   An UNSOLICITED inbound packet to 203.0.113.9:52000 with no table entry:
        NAT has no mapping -> nowhere to send it -> DROPPED.
        ^ This is the "accidental firewall" effect (Chapter 11 §4.5) — a side effect, not a policy.
```

Three ideas:

1. **NAT rewrites the tuple and remembers it.** The table (keyed on the 4-tuple, Chapter 3) maps
   internal ↔ external so replies find their way back. This is *stateful* — the same statefulness as a
   connection-tracking firewall (Chapters 37, 76).
2. **PAT (Port Address Translation), a.k.a. "NAT overload," is what "NAT" usually means today:** many
   internal hosts share one public IP, distinguished by *port*. This is your home router and the AWS
   NAT gateway.
3. **The inbound-blocking is a side effect, not security.** Unsolicited inbound packets are dropped
   because there is no table entry to translate them to — not because NAT decided to deny them. Change
   the scenario (add a port-forward, use a protocol NAT mishandles, or the mapping already exists) and
   the "protection" evaporates. **NAT is not a firewall.**

**The security framing:** NAT's real job is address conservation. Its inbound-blocking is a fragile,
incidental byproduct that (a) does not exist for IPv6 (Chapter 11), (b) is bypassed by port-forwarding,
NAT-traversal techniques (STUN/TURN/hole-punching), and outbound-initiated attacks, and (c) provides no
egress control, no inspection, and no policy. Relying on it as a security boundary is the error;
understanding it as a translator with a side effect is the correct model.

---

## 4. Fundamentals

### 4.1 Types of NAT

- **Static NAT (one-to-one):** one private IP ↔ one public IP, fixed. Used when a server must have a
  stable, dedicated public address (e.g. an on-prem mail server). AWS's **Elastic IP** attached to an
  instance is conceptually static NAT (the instance has a private IP; the EIP is its public one, and
  the fabric translates 1:1).
- **Dynamic NAT (pool):** a pool of public IPs shared among private hosts, assigned as needed. Less
  common now.
- **PAT / NAT overload / NAPT (many-to-one):** many private hosts share **one** public IP,
  distinguished by translated **source ports**. This is the dominant form: home routers, and the **AWS
  NAT gateway**. When people say "NAT," they almost always mean PAT.

The AWS mapping to know:

```
   AWS NAT gateway     = PAT (many private instances -> the NAT GW's public IP, outbound only)
   AWS Elastic IP      = static NAT (1:1, gives an instance a stable public IP, inbound possible)
   AWS internet gateway= NOT NAT (it routes public IPs; the "NAT-like" behavior for instances with
                          public IPs is 1:1 mapping done by the fabric)
```

### 4.2 PAT mechanics and the connection table

PAT works by rewriting the *source port* so that many internal connections sharing one public IP remain
distinguishable:

```
   Internal host A: 10.0.1.5:41000 -> 8.8.8.8:443
   Internal host B: 10.0.1.6:41000 -> 8.8.8.8:443   (same source port, different host!)

   NAT must keep these distinct on the shared public IP 203.0.113.9. It rewrites source ports:
     A -> 203.0.113.9:52000 -> 8.8.8.8:443   (table: 52000 <-> 10.0.1.5:41000)
     B -> 203.0.113.9:52001 -> 8.8.8.8:443   (table: 52001 <-> 10.0.1.6:41000)

   Replies come back to :52000 and :52001; NAT uses the table to route each to the right host.
```

The **NAT table** (translation table / connection table) holds these mappings, each an entry keyed by
the full tuple, with a timeout (idle connections are eventually evicted). Security-relevant properties:

- **It is finite.** The table has a maximum size; a flood of connections (legitimate or malicious) can
  exhaust it, causing new connections to fail — a DoS. The **AWS NAT gateway has documented limits**
  (~55,000 simultaneous connections *per destination IP:port*, and bandwidth/packet limits); exceeding
  them causes connection failures that look like intermittent outages. Knowing this limit is knowing a
  real availability boundary.
- **It is stateful** — the same concept as conntrack (Chapter 37) and stateful security groups
  (Chapter 76). Return traffic is allowed *because a table entry exists*, not because of an explicit
  rule. This is exactly how a stateful firewall's "allow established/related" works.
- **Timeouts matter.** Long-lived-but-idle connections may be dropped from the table, breaking them —
  a common cause of "my connection died after N minutes of inactivity" (databases, SSH, long polls).
  TCP keepalives address it.

### 4.3 SNAT vs DNAT

- **SNAT (Source NAT):** rewrite the *source* address/port. This is what PAT and outbound NAT do —
  making internal hosts appear to come from the public IP. The AWS NAT gateway does SNAT for outbound.
- **DNAT (Destination NAT):** rewrite the *destination* address/port. This is **port forwarding** —
  "inbound traffic to public IP:443 → forward to internal host 10.0.1.5:443." It is how you
  *deliberately* expose an internal service, and it is the mechanism a load balancer / reverse proxy
  effectively performs (Chapter 3 §12). DNAT is also how a NAT's inbound-blocking is *intentionally*
  bypassed — a port-forward is a hole you punch on purpose.

The security point: **SNAT (outbound) has the accidental inbound-blocking side effect; DNAT (port
forwarding) deliberately creates inbound reachability.** Every port-forward is an explicit exposure —
and a common source of accidental exposure when someone forwards a port "temporarily" and forgets.

### 4.4 Why NAT is not a firewall (the crucial distinction)

This is the most important section of the chapter. NAT's inbound-blocking *looks like* a firewall but
differs in every way that matters:

| Property | A firewall | NAT (PAT) |
|---|---|---|
| Purpose | enforce a security *policy* | conserve addresses; translation |
| Blocks inbound because | an explicit deny rule | no table entry exists to translate to |
| Egress control | yes (can deny outbound) | **no** — allows all outbound by design |
| Inspection / logging | yes (rules, logs, deep inspection) | minimal (translation table, not policy logs) |
| Policy granularity | per-rule, per-port, per-source | none — it is a translator |
| IPv6 | applies | **does not exist** (no NAT in IPv6 — Ch. 11) |
| Bypassed by | breaking a rule | port-forwarding, NAT traversal, outbound-initiated attacks, protocol quirks |

The concrete ways "NAT as security" fails:

- **No egress control.** NAT allows *all* outbound connections — it must, to do its job. So malware,
  exfiltration, and C2 flow out freely (Chapter 3 §10.2). A firewall can block egress; NAT cannot. This
  alone disqualifies NAT as a security boundary.
- **NAT traversal defeats inbound blocking.** STUN/TURN/ICE and UDP/TCP hole-punching (used by WebRTC,
  VoIP, gaming, and malware) establish inbound connectivity through NAT by having the internal host
  *initiate* outbound first, creating the table entry an external peer then uses. Two NAT'd hosts can
  connect to each other this way. So the inbound "protection" is routinely and legitimately bypassed.
- **Outbound-initiated attacks.** The dangerous traffic often *is* outbound — a user visits a malicious
  site, a compromised host beacons to C2, an SSRF reaches an internal service. NAT does nothing about
  any of these because they are outbound or internal.
- **IPv6 removes it entirely** (Chapter 11) — so any "security" you thought NAT provided is absent on
  the IPv6 side of a dual-stack host, which is exactly the dual-stack bypass (Chapter 11 §5).

**The correct statement:** NAT provides an *incidental* reduction in unsolicited *inbound* reachability
for IPv4 hosts without their own public IP — a minor defense-in-depth side effect — but it is not a
firewall, provides no egress control, no inspection, no policy, and no IPv6 protection. Reachability and
egress must be controlled by actual firewalls / security groups. Say this precisely; it is a common and
consequential misconception.

### 4.5 NAT and protocols it breaks

NAT rewrites addresses/ports in packet headers, but some protocols embed addresses in their *payload*
(above Layer 4), which NAT does not rewrite, breaking them:

- **FTP (active mode)** embeds the client IP/port in the payload; NAT must have an **ALG (Application
  Layer Gateway)** to fix it, or FTP breaks. (Passive FTP avoids this.)
- **SIP/VoIP, H.323** embed addresses; need ALGs or STUN.
- **IPsec (AH)** cannot traverse NAT because it authenticates the IP header NAT rewrites; **IPsec ESP
  needs NAT-Traversal (NAT-T, UDP encapsulation)** to work through NAT (Chapter 28-adjacent — VPNs).

The security relevance: **ALGs are themselves an attack surface** (SIP ALG vulnerabilities have enabled
firewall bypass), and NAT-T complicates VPN security analysis. For a cloud engineer, the takeaway is
mostly that NAT can break protocols in surprising ways (a debugging concern) and that ALGs, where used,
must be considered in the threat model.

---

## 5. Deep Technical Explanation: The AWS NAT Gateway in Depth

The AWS NAT gateway is PAT-as-a-service, and understanding it precisely resolves a lot of real VPC
design and incident questions. Its behavior:

```
   Private subnet instance (10.20.10.5, no public IP) makes an outbound connection:

   1. Route table (Chapter 12): 0.0.0.0/0 -> nat-gateway. Packet goes to the NAT GW.
   2. NAT GW (in a PUBLIC subnet, with an Elastic IP) does SNAT:
        rewrites source 10.20.10.5:port -> NAT-GW-EIP:translated-port, records the mapping.
   3. Packet goes out via the internet gateway (the NAT GW's public subnet routes 0.0.0.0/0 -> IGW).
   4. Reply returns to the EIP; NAT GW reverses the translation -> delivers to 10.20.10.5.
   5. Unsolicited inbound to the EIP with no mapping -> dropped (the side effect).
```

Key facts a cloud security engineer must hold:

- **The NAT gateway lives in a *public* subnet** (it needs an IGW route to reach the internet) and
  serves *private* subnets (whose default route points at the NAT GW). Getting this topology wrong (NAT
  GW in a private subnet, or private subnets routing to the IGW instead of the NAT GW) is a common
  misconfiguration.
- **It provides outbound-only internet access** to private instances — exactly the "private with egress"
  property (Chapter 12 §5.1). Instances can pull updates, call external APIs, and reach AWS service
  endpoints, but cannot be reached inbound from the internet.
- **It is NOT egress control.** The NAT gateway allows *all* outbound traffic to *any* destination — it
  is PAT, not a firewall. So "we use a NAT gateway" does not mean "egress is controlled." For egress
  control you need **security groups (per-instance), NACLs, VPC endpoints (to keep AWS traffic off the
  internet), an outbound proxy, or AWS Network Firewall** (Chapters 76, 77, 85). This is the single most
  important NAT-gateway misconception, and it directly connects to the exfiltration problem (Chapter 3
  §10.2): a compromised instance behind a NAT gateway can exfiltrate to any internet destination,
  because the NAT gateway allows all egress.
- **Connection limits are real.** ~55,000 simultaneous connections per unique destination, plus
  bandwidth/PPS limits; high-concurrency workloads (many connections to one destination, or a
  connection-leak bug — Chapter 3 §5.4) can exhaust this, causing intermittent failures. Per-AZ NAT
  gateways and, for AWS traffic, VPC endpoints (which bypass the NAT GW) mitigate this.
- **Cost and data processing:** NAT gateways charge per hour and per GB processed, which is why routing
  AWS-service traffic through **VPC endpoints** (Chapter 77) instead of the NAT gateway is both a cost
  and a security improvement (traffic stays on the AWS network, not the internet).

The design synthesis: **use a NAT gateway for private-subnet egress, but do not mistake it for egress
control; layer actual egress controls (VPC endpoints for AWS services, security groups, and a proxy/
Network Firewall for internet egress) on top.** The NAT gateway gives connectivity; the security comes
from the controls around it. This is the "name the enforcing mechanism" discipline (Chapter 4 §7)
applied to egress: "what controls what our instances can reach on the internet?" is answered by the
egress controls, never by "we have a NAT gateway."

---

## 6. Internals: Observing NAT

### 6.1 See NAT on a Linux router/host

Linux does NAT via netfilter (Chapter 37 covers this fully); here, just enough to observe it:

```bash
# The NAT rules (on a host acting as a router/gateway):
$ sudo iptables -t nat -L -n -v
Chain POSTROUTING (policy ACCEPT)
 pkts bytes target     prot opt in  out   source        destination
  ...  ... MASQUERADE  all  --  *   eth0  10.0.1.0/24   0.0.0.0/0     # SNAT/PAT for the subnet

# The connection tracking table shows the NAT mappings (the "NAT table"):
$ sudo conntrack -L 2>/dev/null | head
tcp 6 431999 ESTABLISHED src=10.0.1.5 dst=8.8.8.8 sport=41000 dport=443 \
    src=8.8.8.8 dst=203.0.113.9 sport=443 dport=52000 [ASSURED] ...
```

Read the conntrack entry: the *original* tuple (`src=10.0.1.5 ... sport=41000`) and the *reply* tuple
(`dst=203.0.113.9 ... dport=52000`) — the mapping. This is the NAT table (§4.2), and it is the same
conntrack table a stateful firewall uses (Chapters 37, 76). `MASQUERADE` is PAT (SNAT to the interface's
address).

### 6.2 See your public IP (the NAT's translation result)

```bash
$ curl -s https://api.ipify.org ; echo         # the public IP you appear to come from (the NAT's)
203.0.113.9
$ ip addr show                                  # your PRIVATE IP (behind the NAT) is different
    inet 10.0.1.5/24 ...
```

The difference between your private IP (`10.0.1.5`) and the public IP the internet sees (`203.0.113.9`)
*is* NAT (specifically SNAT/PAT). Every home network and every private-subnet instance shows this.

### 6.3 Observe the connection-table timeout

```bash
$ cat /proc/sys/net/netfilter/nf_conntrack_tcp_timeout_established   # e.g. 432000 (5 days) for TCP est.
$ cat /proc/sys/net/netfilter/nf_conntrack_max                       # table size limit
$ conntrack -C                                                        # current entry count
```

`nf_conntrack_max` is the table size — exhausting it drops new connections (a DoS/scaling concern). The
timeout is why idle long-lived connections die (§4.2). The AWS NAT gateway has analogous (higher,
managed) limits.

---

## 7. Real-World Example: NAT in the Ledger Environments

**System A (VPS):** the VPS typically has a public IP directly (static NAT / 1:1 at the provider, or a
directly-assigned public IP), so it is internet-reachable — the loopback binds and the host firewall
(Chapter 3 §7) provide the security, not NAT. If the VPS is behind a provider NAT, the "accidental
inbound blocking" applies, but it is not the security control — the firewall and binds are.

**System B (AWS) — the important case:**

```
   Public subnets:  ALB + NAT gateway (with EIPs) — internet-facing.
   Private app subnets: ECS tasks, no public IP, route 0.0.0.0/0 -> NAT gateway.
     -> Tasks can pull container images, call Stripe/external APIs, reach AWS endpoints (outbound).
     -> Tasks CANNOT be reached inbound from the internet (no public IP + NAT side effect + SGs).
   Private data subnets: RDS/cache, NO default route -> no internet at all (not even NAT).
```

The security analysis, applying §4.4 and §5:

- **The NAT gateway gives the app tier outbound internet without inbound reachability** — correct and
  intended for "private with egress." But:
- **The NAT gateway is not egress control.** A compromised ECS task can exfiltrate to *any* internet
  destination through the NAT gateway (Chapter 3 §10.2), because NAT allows all egress. To control this,
  Ledger should add: **VPC endpoints** so S3/DynamoDB/ECR/Secrets Manager traffic never touches the NAT
  gateway or the internet (Chapter 77 — both a cost and a security win), **security-group egress rules**
  restricting outbound where feasible, and for internet-bound traffic an **egress proxy or AWS Network
  Firewall** with a destination allow-list (Chapter 85). Without these, "private subnet + NAT gateway"
  is *inbound*-protected but *egress*-wide-open — a common gap.
- **The data tier has no NAT and no internet route at all** — the strongest posture, correct for a data
  store that needs no internet (it reaches AWS services via VPC endpoints if needed).
- **The `169.254.169.254` metadata risk (Chapters 10, 50, 78)** is unaffected by NAT — it is
  link-local, reached directly, not through the NAT gateway; so NAT provides no defense against
  SSRF-to-metadata.

The Ledger takeaway: **the NAT gateway is connectivity, not security. It provides inbound protection as
a side effect and zero egress control. The egress controls (VPC endpoints, SG egress rules, Network
Firewall/proxy) are what actually constrain what a compromised instance can reach — and they must be
added deliberately.** This is exactly the kind of precise correction ("we have a NAT gateway" ≠ "egress
is controlled") that a cloud security engineer contributes in a design review.

---

## 8. Hands-On Demonstration

### LAB 14.1 — NAT Mechanics and the "NAT Is Not a Firewall" Proof

**Objective.** Build a NAT boundary with Linux, observe the translation and connection table, prove that
NAT blocks unsolicited inbound (the side effect) but allows *all* outbound (no egress control), and
demonstrate that a port-forward (DNAT) trivially bypasses the inbound "protection."

**Cost.** Free. **Environment.** ENV-2 (Docker + Linux). **Time.** 60 minutes.

**Steps.**

*Step 1 — Build a NAT topology.*

```bash
docker network create --internal privnet --subnet 10.60.2.0/24    # no internet (private)
docker network create pubnet --subnet 10.60.1.0/24
docker run -d --name natgw --network pubnet --cap-add NET_ADMIN --sysctl net.ipv4.ip_forward=1 nicolaka/netshoot sleep 3600
docker network connect privnet natgw
docker run -d --name client --network privnet nicolaka/netshoot sleep 3600
# Point the client's default route at the NAT gateway:
NATGW_PRIV=$(docker inspect -f '{{(index .NetworkSettings.Networks "privnet").IPAddress}}' natgw)
docker exec client ip route replace default via ${NATGW_PRIV}
# Configure PAT on the gateway (masquerade privnet out to pubnet):
docker exec natgw iptables -t nat -A POSTROUTING -s 10.60.2.0/24 -o eth0 -j MASQUERADE
```

*Step 2 — Observe SNAT/PAT and the connection table.*

```bash
# From the client, make an outbound connection through the NAT gateway to something on pubnet:
docker run -d --name server --network pubnet nginx
SERVER_PUB=$(docker inspect -f '{{(index .NetworkSettings.Networks "pubnet").IPAddress}}' server)
docker exec client sh -c "curl -s -m3 http://${SERVER_PUB} >/dev/null && echo 'outbound works'"
# See the NAT mapping on the gateway:
docker exec natgw conntrack -L 2>/dev/null | grep 10.60.2 | head
# -> shows original (client private) and reply (natgw public) tuples: the translation
```

*Step 3 — Prove outbound is UNRESTRICTED (no egress control).*

```bash
# The client can reach ANY pubnet destination through NAT — NAT does not filter egress:
docker run -d --name evil --network pubnet nginx    # stands in for "any internet destination"
EVIL_PUB=$(docker inspect -f '{{(index .NetworkSettings.Networks "pubnet").IPAddress}}' evil)
docker exec client sh -c "curl -s -m3 http://${EVIL_PUB} >/dev/null && echo 'reached evil too: NAT allows ALL egress (no egress control)'"
```

**Security implication:** NAT let the client reach an arbitrary destination — exactly how a compromised
host exfiltrates. NAT provides *no* egress control.

*Step 4 — Prove inbound is blocked (the side effect)...*

```bash
# From the pubnet server, try to reach the client's private IP directly -> no route/no mapping:
CLIENT_PRIV=$(docker inspect -f '{{(index .NetworkSettings.Networks "privnet").IPAddress}}' client)
docker exec server sh -c "curl -s -m3 http://${CLIENT_PRIV} >/dev/null && echo reached || echo 'client unreachable inbound (NAT side effect)'"
```

*Step 5 — ...then bypass it with a port-forward (DNAT).*

```bash
# Run a service on the client, then port-forward the NAT gateway's public port to it (DNAT):
docker exec -d client sh -c 'python3 -m http.server 8080'
docker exec natgw iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination ${CLIENT_PRIV}:8080
docker exec natgw iptables -A FORWARD -p tcp -d ${CLIENT_PRIV} --dport 8080 -j ACCEPT
NATGW_PUB=$(docker inspect -f '{{(index .NetworkSettings.Networks "pubnet").IPAddress}}' natgw)
docker exec server sh -c "curl -s -m3 http://${NATGW_PUB}:8080 >/dev/null && echo 'inbound now works via port-forward: NAT inbound-blocking is not a policy'"
```

**Security implications.** Write down: (a) NAT allowed *all* outbound (no egress control) — the key
"not a firewall" point; (b) NAT blocked unsolicited inbound only because no mapping existed (a side
effect); (c) one DNAT rule (port-forward) trivially created inbound reachability — the "protection" is
not a policy; (d) therefore reachability and egress must be controlled by real firewalls/SGs, and in
AWS the NAT gateway is connectivity, not egress control.

**Cleanup.**
```bash
docker rm -f natgw client server evil; docker network rm pubnet privnet
```

---

## 9. Security Implications

- **NAT is a translator for address conservation, not a firewall.** Its inbound-blocking is a side
  effect of needing a table entry, not a security policy — say this precisely.
- **NAT provides no egress control** — it allows all outbound by design, so exfiltration, C2, and
  malware flow out freely. Egress control requires real firewalls/SGs/proxies/VPC endpoints.
- **The AWS NAT gateway = PAT-as-a-service**: outbound-only internet for private subnets, *not* egress
  control. "We have a NAT gateway" ≠ "egress is controlled." Layer VPC endpoints, SG egress rules, and
  Network Firewall/proxy on top.
- **The NAT/connection table is stateful and finite** — the same concept as conntrack/stateful
  firewalls (Chapters 37, 76), and a real DoS/scaling limit (NAT gateway connection limits; conntrack
  table exhaustion).
- **NAT does not apply to IPv6** (Chapter 11) — any "protection" you attributed to NAT is absent on the
  IPv6 side (the dual-stack bypass).
- **NAT complicates attribution** — many hosts share one public IP, so identifying the internal source
  of a connection requires the NAT table/logs (an IR consideration).

---

## 10. Attack Scenarios

1. **Egress exfiltration through NAT** (§4.4, §5, Chapter 3 §10.2): a compromised host behind NAT
   exfiltrates to any internet destination, because NAT allows all egress. Defense: real egress
   controls (VPC endpoints, SG egress, proxy/Network Firewall) — NAT does nothing here.
2. **"We're behind NAT so we're safe" false assurance:** relying on NAT as a security boundary, leaving
   no egress control and no IPv6 protection — a design-level failure.
3. **Port-forward exposure:** a DNAT rule (deliberate or forgotten) exposes an internal service; "temporary"
   port-forwards left in place are a common accidental exposure (§4.3, Lab 14.1).
4. **NAT traversal for inbound C2:** malware uses STUN/hole-punching to establish inbound connectivity
   through NAT via an outbound-initiated connection, defeating the inbound side effect (§4.4).
5. **NAT/conntrack table exhaustion DoS:** flooding connections to exhaust the NAT table (or the AWS NAT
   gateway's connection limit), causing new connections to fail — an availability attack (§4.2, §5).
6. **ALG vulnerabilities:** flaws in application-layer gateways (SIP ALG especially) enabling firewall
   bypass or spoofing (§4.5).
7. **IPv6 dual-stack bypass:** a host "protected" by IPv4 NAT is globally reachable on IPv6 (Chapter 11
   §5) — NAT's absence in IPv6 removes the assumed protection.

---

## 11. Defensive Techniques

- **Do not treat NAT as a firewall.** Provide reachability control (inbound) with real firewalls/
  security groups and NACLs, and **egress control** with SG egress rules, VPC endpoints (for AWS
  services), and an outbound proxy or AWS Network Firewall with a destination allow-list (Chapters 76,
  77, 85). NAT gives connectivity; these give security.
- **In AWS: use the NAT gateway for private-subnet egress, plus VPC endpoints for AWS-service traffic**
  (keeps it off the NAT GW and the internet — cheaper and more secure), and **restrict internet egress**
  with a proxy/Network Firewall where the threat model requires it. Give data tiers no internet route at
  all (not even NAT).
- **Audit port-forwards / DNAT rules and inbound SG rules** — every one is a deliberate exposure; ensure
  none are stale or accidental.
- **Size and monitor connection tables/limits** — watch NAT gateway connection/bandwidth metrics
  (CloudWatch) and conntrack table utilization on Linux; use per-AZ NAT gateways and VPC endpoints to
  distribute/reduce load; tune conntrack limits and timeouts.
- **Remember IPv6** — apply firewall/SG rules for IPv6 (no NAT there); use an egress-only internet
  gateway for outbound-only IPv6 (Chapter 11).
- **For attribution/IR, log NAT translations / flow logs** so a shared public IP can be traced to an
  internal source (VPC Flow Logs record the pre-NAT source in the VPC — Chapter 82).

---

## 12. Production Architecture

NAT's place in the network, and the controls that must accompany it:

```
   PRIVATE SUBNET (app tier)
        | 0.0.0.0/0 -> NAT gateway            <- CONNECTIVITY (outbound-only internet)
        |
   [ NAT gateway (PAT) ]  --- but ALSO layer on top: ---
        |                    - VPC endpoints (S3/DynamoDB/ECR/etc. bypass NAT + internet)  <- EGRESS + cost
        |                    - security-group egress rules                                  <- EGRESS
        |                    - egress proxy / AWS Network Firewall (destination allow-list) <- EGRESS + inspection
        v
   [ internet gateway ] -> Internet

   DATA SUBNET: NO default route -> no internet at all (strongest; use VPC endpoints for AWS svcs)
```

The architectural principle: **separate connectivity from control.** The NAT gateway (and the internet
gateway) provide *connectivity*; the security groups, NACLs, VPC endpoints, and egress
firewall/proxy provide *control*. A design that has a NAT gateway but no egress controls has inbound
protection (a side effect) and no egress protection — a half-secured egress path. A mature design
provides private-subnet egress via the NAT gateway *and* constrains it: AWS-service traffic through VPC
endpoints (off the internet entirely), internet traffic through an allow-listing proxy/firewall, and SG
egress rules per workload — so a compromised instance cannot freely exfiltrate. This is the concrete
answer to Chapter 3 §10.2's exfiltration question and a direct application of "name the enforcing
mechanism" (Chapter 4 §7): egress control is the proxy/endpoints/SGs, never the NAT gateway.

---

## 13. Common Mistakes

1. **Treating NAT as a firewall / security boundary** — the central error; NAT has no egress control, no
   policy, no IPv6.
2. **"We have a NAT gateway, so egress is controlled"** — it is not; the NAT gateway allows all
   outbound. Add VPC endpoints, SG egress, and a proxy/Network Firewall.
3. **Forgetting IPv6** — NAT does not apply, so IPv4-NAT "protection" is absent on IPv6 (Chapter 11).
4. **Stale/forgotten port-forwards (DNAT)** exposing internal services.
5. **NAT gateway in the wrong subnet** (private instead of public) or private subnets routing to the IGW
   instead of the NAT gateway — topology misconfigurations (Chapter 12).
6. **Not using VPC endpoints** — routing all AWS-service traffic through the NAT gateway (higher cost,
   traffic needlessly on the internet, and NAT-gateway load).
7. **Ignoring NAT/conntrack limits** — connection-table exhaustion causing intermittent failures
   (Chapter 3 §5.4).
8. **Assuming NAT provides attribution** — many hosts share one IP; you need flow logs / NAT logs to
   trace the source.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Outbound works, but exfiltration happened anyway | NAT allows all egress (no egress control) | expected — add egress controls; check flow logs for the destination |
| Long-lived connection drops after idle period | NAT/conntrack timeout evicted the entry | enable TCP keepalives; check `nf_conntrack_tcp_timeout_*` / NAT GW idle timeout |
| Intermittent connection failures under load | NAT table / NAT gateway connection limit exhausted | NAT GW CloudWatch (ErrorPortAllocation), `conntrack -C` vs `nf_conntrack_max`; add per-AZ NAT / VPC endpoints |
| Private instance can't reach the internet | wrong route (not to NAT GW), or NAT GW in wrong subnet | check route table (0.0.0.0/0 -> nat-*); NAT GW must be in a public subnet with IGW route |
| An internal service is unexpectedly reachable | a DNAT/port-forward or inbound SG rule | audit NAT PREROUTING/DNAT rules and inbound SG rules |
| IPv6 reachable though IPv4 "behind NAT" | no NAT for IPv6; missing IPv6 firewall | apply IPv6 SG/firewall; EIGW for outbound-only (Chapter 11) |
| FTP/SIP/VPN breaks through NAT | protocol embeds addresses; needs ALG/NAT-T | passive FTP; NAT-T for IPsec; check ALG config (§4.5) |

---

## 15. Practical Lab

Lab 14.1 is in §8. Register it in the lab index. Extension (AWS): in a real VPC, verify a private
subnet's egress path (route to NAT GW), then demonstrate the egress gap by connecting from a private
instance to an arbitrary internet destination (allowed), and close it by adding VPC endpoints for AWS
services + an SG egress restriction (or Network Firewall rule); confirm via VPC Flow Logs that AWS
traffic now uses the endpoint and internet egress is constrained. This makes the "NAT ≠ egress control"
lesson concrete in the platform you will actually secure.

---

## 16. Exercises

### Concept questions

**14.1** Explain what NAT does and its primary purpose. Distinguish static NAT, dynamic NAT, and PAT,
and give the AWS construct for each.

**14.2** Explain SNAT vs DNAT and which one produces the inbound-blocking side effect vs which one
deliberately creates inbound reachability.

**14.3** Explain precisely why NAT is not a firewall. Address egress control, inspection, IPv6, and how
the inbound "protection" is bypassed.

**14.4** Explain the NAT connection table: what it holds, why it is stateful, and how it relates to
conntrack and stateful security groups. What are its failure modes?

**14.5** Explain why "we have a NAT gateway, so our egress is controlled" is false, and what actually
controls egress in a VPC.

### Debugging problems

**14.6** A private-subnet instance's long-lived database connection drops after ~5 minutes of
inactivity. Explain the likely cause and the fix.

**14.7** Under peak load, a fleet behind a single NAT gateway experiences intermittent connection
failures to one external API. Diagnose and propose fixes.

**14.8** A "private" service is found reachable from the internet. There is a NAT gateway and no public
IP on the instance. What are the two most likely causes?

### Security scenarios

**14.9** During an incident, a compromised instance in a private subnet exfiltrated data to an external
server. The team is confused because "it was behind a NAT gateway." Explain what happened and what
should have been in place.

**14.10** You are reviewing a VPC. Describe how you assess the egress posture of private subnets, and
the specific gaps you look for beyond "there is a NAT gateway."

### Architecture questions

**14.11** Design the egress architecture for a three-tier VPC such that (a) app instances can reach only
approved external destinations, (b) AWS-service traffic never touches the internet, and (c) the data
tier has no internet access at all. Name every mechanism.

**14.12** Explain how NAT's statefulness relates to stateful firewalls and connection tracking, and why
understanding one helps you understand the others (Chapters 37, 76).

### Hands-on exercises

**14.13** Build the Lab 14.1 NAT topology and observe a translation in the conntrack table, identifying
the original and reply tuples.

**14.14** Demonstrate that NAT allows arbitrary outbound (no egress control) and that a DNAT port-forward
creates inbound reachability, then write the finding as you would in a review.

**14.15** On a Linux host, inspect `nf_conntrack_max`, current usage, and TCP timeouts, and explain how
each relates to a DoS or a dropped-connection symptom.

### Interview questions

**14.16** "Is NAT a security control? Explain precisely."

**14.17** "What does an AWS NAT gateway provide, and what does it not provide?"

**14.18** "A compromised instance in a private subnet exfiltrated data. It was behind a NAT gateway. How
did that happen, and how would you prevent it?"

**14.19** "How does NAT relate to a stateful firewall?"

**14.20** "Why does NAT not exist in IPv6, and what are the security implications?"

---

## 17. Summary

- **NAT translates addresses/ports at a boundary and maintains a table to reverse the translation for
  replies.** Its primary purpose is **address conservation** (many private hosts sharing few public
  IPs); its inbound-blocking is a **side effect** of needing a table entry, not a security policy.
- **PAT (NAT overload)** — many hosts share one public IP, distinguished by translated source ports — is
  the dominant form (home routers; the **AWS NAT gateway**). Static NAT (1:1) ≈ an **Elastic IP**.
- **SNAT** (source rewrite, outbound) produces the accidental inbound-blocking; **DNAT** (destination
  rewrite = **port forwarding**) deliberately creates inbound reachability — every port-forward is an
  explicit exposure.
- **NAT is not a firewall:** it has **no egress control** (allows all outbound — so exfiltration/C2 flow
  freely), no inspection, no policy, **does not exist in IPv6**, and its inbound "protection" is bypassed
  by port-forwards, NAT traversal (STUN/hole-punching), and outbound-initiated attacks.
- The **NAT/connection table is stateful and finite** — the same concept as conntrack and stateful
  security groups (Chapters 37, 76), and a real DoS/scaling limit (NAT gateway connection limits;
  conntrack exhaustion; idle timeouts dropping long-lived connections).
- **The AWS NAT gateway = PAT-as-a-service: outbound-only internet for private subnets, NOT egress
  control.** "We have a NAT gateway" ≠ "egress is controlled." Layer **VPC endpoints** (AWS traffic off
  the internet), **SG egress rules**, and an **egress proxy / Network Firewall** on top; give data tiers
  no internet route at all.
- **Separate connectivity from control:** the NAT/internet gateways provide connectivity; the SGs,
  NACLs, VPC endpoints, and egress firewall provide the security. Name the egress-control mechanism —
  it is never the NAT gateway.

---

## 18. Knowledge Check

1. What is NAT's primary purpose, and what is its inbound-blocking (policy or side effect)? (§3)
2. What is PAT, and which AWS construct is it? (§4.1)
3. SNAT vs DNAT — which blocks inbound as a side effect, which creates inbound reachability? (§4.3)
4. Give three reasons NAT is not a firewall. (§4.4)
5. Why does "we have a NAT gateway" not mean egress is controlled? (§5)
6. What does the NAT connection table hold, and how does it relate to conntrack/SGs? (§4.2, §6.1)
7. What controls egress in a VPC (name the mechanisms)? (§5, §11)
8. Why is NAT irrelevant to IPv6, and what's the implication? (§4.4, Chapter 11)
9. What are two failure modes of the NAT table? (§4.2)
10. What is a port-forward, and why is each one a deliberate exposure? (§4.3)

---

## 19. Further Exploration

- `man iptables` (nat table), `man conntrack` — see NAT and connection tracking on Linux (bridge to
  Chapter 37).
- AWS NAT gateway documentation, especially the connection/bandwidth limits and the comparison with VPC
  endpoints — the concrete §5 material; then read the VPC endpoints docs (Chapter 77).
- RFC 3022 (traditional NAT) and RFC 2663 (NAT terminology) for the precise definitions.
- Read about STUN/TURN/ICE (RFC 5389 etc.) to understand NAT traversal — why the inbound "protection" is
  routinely bypassed, relevant to WebRTC and to malware C2.
- Revisit Chapter 11 §4.5 (no NAT in IPv6) and Chapter 3 §10.2 (egress exfiltration) — NAT ties them
  together: it is the IPv4 mechanism whose inbound side effect IPv6 removes and whose lack of egress
  control enables exfiltration.

---

## Solutions

### 14.1
NAT (Network Address Translation) rewrites the source and/or destination IP address (and, for PAT, the
port) of packets as they cross a network boundary, maintaining a table so it can reverse the translation
for return traffic. Its primary purpose is **address conservation**: it lets many hosts with private
(RFC 1918) addresses share a small number of public IPv4 addresses, which is what kept IPv4 viable
despite exhaustion (Chapter 10). Types: **static NAT** — a fixed one-to-one private↔public mapping (AWS:
an **Elastic IP** attached to an instance); **dynamic NAT** — a pool of public IPs assigned to private
hosts as needed (less common now); **PAT / NAT overload** — many private hosts share **one** public IP,
distinguished by translated source ports (AWS: the **NAT gateway**, and every home router). "NAT" today
usually means PAT.

### 14.2
**SNAT (Source NAT)** rewrites the source address/port — used for outbound traffic so internal hosts
appear to come from the public IP (PAT is SNAT). **DNAT (Destination NAT)** rewrites the destination
address/port — used to forward inbound traffic to an internal host ("port forwarding"). SNAT produces
the **inbound-blocking side effect**: because outbound SNAT only creates table entries for
outbound-initiated connections, an unsolicited inbound packet has no matching entry to translate to and
is dropped. DNAT **deliberately creates inbound reachability**: a port-forward rule explicitly maps an
external IP:port to an internal host, punching a hole through the inbound-blocking. So SNAT's side effect
provides incidental inbound protection, while DNAT is the intentional mechanism to expose an internal
service — and every DNAT/port-forward is therefore a deliberate exposure to audit.

### 14.3
NAT is not a firewall because it is a *translator* with no security *policy*: (1) **No egress control** —
NAT allows all outbound connections by design (it must, to translate them), so malware, C2, and
exfiltration flow out freely; a firewall can deny egress, NAT cannot. (2) **No inspection or policy
granularity** — NAT has a translation table, not rules; it does not inspect content, cannot allow/deny
by policy, and produces no security logs. (3) **No IPv6** — NAT does not exist in IPv6 (addresses are
abundant), so any "protection" attributed to NAT is absent on the IPv6 side of a dual-stack host
(Chapter 11 §5). And its inbound-blocking is bypassed by: **port-forwarding (DNAT)** which deliberately
creates inbound reachability; **NAT traversal (STUN/TURN/hole-punching)** where an internal host
initiates outbound to create a mapping an external peer then uses (WebRTC, VoIP, malware C2); and
**outbound-initiated/internal attacks** (a user visiting a malicious site, an SSRF) which NAT is
irrelevant to. So NAT gives an incidental inbound-reachability reduction for IPv4 as a side effect, but
reachability and egress must be controlled by actual firewalls/security groups.

### 14.4
The NAT connection table holds, for each active connection, the mapping between the internal tuple
(private IP:port, destination) and the external tuple (public IP:translated-port, destination), so
return traffic can be translated back to the correct internal host (§4.2). It is **stateful** because it
records established connections and uses their presence to handle replies — return traffic is delivered
because a matching entry exists, not because of an explicit rule. This is exactly the mechanism of
**connection tracking (conntrack)** in Linux netfilter and of **stateful firewalls / security groups**
(Chapters 37, 76): "allow established/related" means "there is a state-table entry for this connection."
Failure modes: (1) **table exhaustion** — the table is finite (`nf_conntrack_max`; the AWS NAT gateway's
~55,000-connections-per-destination limit), so a flood of connections (malicious or a leak — Chapter 3
§5.4) fills it and new connections fail (a DoS/scaling issue); (2) **idle timeout eviction** — entries
for idle connections are evicted after a timeout, so long-lived-but-idle connections (databases, SSH,
long polls) break, fixed with TCP keepalives.

### 14.5
"We have a NAT gateway, so our egress is controlled" is false because the NAT gateway is PAT — it
translates and forwards **all** outbound connections to **any** destination; it applies no policy, no
allow-list, and no inspection. A compromised instance behind a NAT gateway can therefore connect to any
internet destination and exfiltrate data freely — the NAT gateway does nothing to stop it (Chapter 3
§10.2). What actually controls egress in a VPC: **security-group egress rules** (per-instance, restrict
outbound destinations/ports), **VPC endpoints** (route AWS-service traffic privately, off the internet
and off the NAT gateway entirely — both a security and cost win, Chapter 77), **NACLs** (subnet-level),
and an **egress proxy or AWS Network Firewall** with a destination allow-list and inspection (Chapter
85) for internet-bound traffic; plus giving tiers that need no internet **no default route at all**
(the data tier). The NAT gateway provides *connectivity* (outbound-only internet); these provide
*control*. The correct statement is "the NAT gateway is not egress control; egress is controlled by SG
egress rules, VPC endpoints, and a proxy/Network Firewall."

### 14.6
The likely cause is the NAT (connection-tracking) **idle timeout evicting the connection's table
entry**: after ~5 minutes of no traffic, the NAT gateway (or a Linux conntrack table) drops the mapping
for the idle connection, so subsequent packets have no translation entry and the connection breaks (the
app sees a reset or hang). Long-lived database connections that sit idle between queries are the classic
victim. Fix: enable **TCP keepalives** on the connection (OS-level `tcp_keepalive_time`/the driver's
keepalive setting) so periodic packets keep the NAT entry alive and refresh the timeout; set the
keepalive interval below the NAT idle timeout (the AWS NAT gateway idle timeout is ~350 seconds, so
keepalives well under that). Also consider connection pooling with validation/re-establishment. The root
lesson: NAT/conntrack tables have idle timeouts, and long-lived connections must generate traffic to
survive them.

### 14.7
The likely cause is exhaustion of the NAT gateway's **connection limit to a single destination**: the
AWS NAT gateway supports ~55,000 simultaneous connections *per unique destination IP:port*, so a fleet
making many concurrent connections to one external API (same destination IP:port) can hit that limit,
causing port-allocation errors and intermittent connection failures (visible as the
`ErrorPortAllocation` CloudWatch metric). Diagnose: check the NAT gateway CloudWatch metrics
(ActiveConnectionCount, ErrorPortAllocation, bandwidth/PPS), confirm the failures correlate with high
concurrency to that one destination, and check for a connection leak (Chapter 3 §5.4) inflating counts.
Fixes: distribute load across **multiple NAT gateways** (one per AZ, or several) since the limit is
per-NAT-gateway-per-destination; use **connection pooling / keep-alive reuse** to reduce simultaneous
connections; if the destination is an AWS service, use a **VPC endpoint** (bypasses the NAT gateway
entirely); and fix any connection leaks. The lesson: the NAT gateway is a finite, stateful resource with
per-destination limits that high-concurrency workloads can exhaust.

### 14.8
Two most likely causes: (1) a **DNAT / port-forward or an inbound rule deliberately (or accidentally)
exposing the service** — e.g. the service is behind a load balancer or a port-forward that maps a public
endpoint to the private instance, or someone added an inbound security-group rule plus a path (the NAT
gateway does not forward inbound, but an ALB/NLB, an Elastic IP, or a DNAT does). (2) **A separate public
path**: the instance has a route or an interface you missed — a second ENI with a public IP, an
Elastic IP, placement in a public subnet, or reachability via VPC peering/Transit Gateway from a
less-trusted network (Chapter 77) — so it is not as "private" as assumed. Investigate: check for
load balancers/target groups pointing at it, Elastic IPs and public IPs on its ENIs, its subnet's route
table (public vs private), inbound SG/NACL rules, and peering/TGW routes. The general point: NAT's
inbound side effect is not why it's private, and it does not prevent deliberate exposure paths — find
the actual inbound path (LB, EIP, DNAT, peering) rather than assuming NAT protects it.

### 14.9
What happened: the NAT gateway allows **all** outbound connections (it is PAT, not a firewall — §4.4,
§5), so the compromised instance simply opened an outbound connection to the attacker's external server
and exfiltrated the data through the NAT gateway, exactly as it would send any legitimate outbound
traffic. Being "behind a NAT gateway" prevented *unsolicited inbound* connections (a side effect) but
did nothing about *outbound* — and exfiltration is outbound. What should have been in place: **egress
controls** — VPC endpoints so AWS-service traffic never touches the internet, **security-group egress
rules** restricting outbound to approved destinations/ports, and an **egress proxy or AWS Network
Firewall** with a destination allow-list and logging so that connections to unapproved destinations are
blocked and alerted; plus **VPC Flow Logs / GuardDuty** to detect the anomalous egress. The team's
confusion is the exact "NAT is not a firewall" misconception; the correction is that the NAT gateway is
connectivity, not egress control, and egress must be explicitly controlled and monitored.

### 14.10
Assess egress by asking "what can each private subnet's instances actually reach on the internet, and
what controls that?" — never accepting "there is a NAT gateway" as the answer. Steps: (1) confirm the
route (private subnet 0.0.0.0/0 → NAT gateway) but recognize this is *connectivity*, not control. (2)
Check **security-group egress rules** — are they restricted, or the default allow-all outbound? (3)
Check for **VPC endpoints** for AWS services (S3, DynamoDB, ECR, Secrets Manager, etc.) — without them,
that traffic traverses the NAT gateway and the internet unnecessarily (cost + exposure). (4) Check for an
**egress proxy or AWS Network Firewall** with a destination allow-list and logging — without it,
instances can reach any internet destination (exfiltration path). (5) Check the **data tier** has *no*
internet route at all. (6) Confirm **VPC Flow Logs** are on for egress visibility/detection. Gaps to
flag: default allow-all SG egress, no VPC endpoints (all AWS traffic via NAT/internet), no egress
allow-listing/inspection, data tier with a NAT/internet route, and no flow logging. The headline finding
is "private subnets have a NAT gateway but no egress control — a compromised instance can exfiltrate to
any destination."

### 14.11
Design: (a) **App instances reach only approved external destinations** — route the app private subnet's
`0.0.0.0/0` to a NAT gateway for connectivity, but force internet-bound traffic through an **egress proxy
or AWS Network Firewall** with a **destination allow-list** (specific domains/IPs the app legitimately
needs — package registries, payment APIs) and logging; restrict **security-group egress** to the proxy/
firewall and required ports; deny all other egress. (b) **AWS-service traffic never touches the
internet** — create **VPC endpoints** (Gateway endpoints for S3/DynamoDB; Interface endpoints for ECR,
Secrets Manager, KMS, etc.) so that traffic to AWS services is routed privately over the AWS network,
bypassing both the NAT gateway and the internet; apply endpoint policies to restrict which resources.
(c) **Data tier has no internet access at all** — the data subnets have **no default route** (no NAT, no
IGW); if they need AWS services (e.g. KMS), reach them via VPC endpoints only. Mechanisms named: NAT
gateway (connectivity), Network Firewall/egress proxy + allow-list (internet egress control + inspection
+ logging), VPC endpoints + endpoint policies (private AWS-service access), security-group egress rules
(per-instance control), and route tables (no internet route for data). This separates connectivity from
control and constrains what a compromised instance can reach.

### 14.12
NAT is stateful in exactly the way a stateful firewall is: both maintain a **connection-state table**
keyed on the connection tuple, and both use the *presence of an entry* to handle return/related traffic.
In NAT, the table maps internal↔external tuples so replies are translated back; a reply is delivered
because its connection is in the table. In a stateful firewall (and a security group — Chapter 76),
"allow established/related" means the firewall permits return traffic because the outbound connection
created a state-table entry — you write a rule for the *initiating* direction, and the return is allowed
automatically by state. In Linux, both are implemented by the **same conntrack subsystem** (Chapter 37):
netfilter's connection tracking underlies both NAT (the `nat` table's translations are attached to
conntrack entries) and stateful filtering (`ctstate ESTABLISHED,RELATED`). So understanding NAT's
table — its keying on the tuple, its statefulness, its timeouts, and its finite size — directly teaches
you how stateful firewalls and security groups work and fail (e.g. why you only need an inbound rule for
a security group and the return is automatic, and why conntrack exhaustion is a DoS for both). One
mechanism, three manifestations.

### 14.16
NAT is **not** a security control in the firewall sense, though it has one incidental security-relevant
side effect. Its purpose is address translation/conservation, not policy enforcement. It provides no
egress control (it allows all outbound by design, so exfiltration and C2 flow freely), no traffic
inspection, no policy granularity, no security logging, and it does not exist in IPv6. Its only
security-relevant behavior is that **outbound SNAT/PAT incidentally drops unsolicited inbound packets**
because they have no translation-table entry — but this is a side effect of how translation works, not a
firewall policy, and it is routinely bypassed by port-forwarding (DNAT), NAT traversal (STUN/hole-
punching), and outbound-initiated/internal attacks. So the precise answer: NAT gives a minor,
incidental reduction in unsolicited inbound reachability for IPv4 hosts without a public IP — a
defense-in-depth footnote — but it is not a firewall, and reachability and egress must be controlled by
actual firewalls/security groups. Relying on NAT as a security boundary is a well-known and dangerous
mistake.

### 14.17
An AWS NAT gateway provides **outbound-only internet connectivity for instances in private subnets**: it
performs PAT (SNAT), translating many private instances' source addresses to its Elastic IP so they can
initiate outbound connections (pull images, call external APIs, reach AWS endpoints) and receive the
replies, while unsolicited inbound connections are dropped (no translation entry). What it does **not**
provide: **egress control** (it allows outbound to *any* destination — no allow-listing, no policy, so a
compromised instance can exfiltrate freely), traffic inspection, security logging (beyond CloudWatch
metrics), IPv6 (it is IPv4-only; use an egress-only internet gateway for IPv6), or attribution by itself.
It is also a finite, stateful resource with per-destination connection limits (~55,000) and bandwidth
limits that high-concurrency workloads can exhaust, and it incurs per-hour and per-GB cost. So: it is
*connectivity* (private-subnet egress), not *control*; egress control requires VPC endpoints, SG egress
rules, and a proxy/Network Firewall layered on top.

### 14.18
It happened because the NAT gateway is PAT, not a firewall (§4.4, §5): it allows all outbound
connections to any destination, so the compromised instance simply opened an outbound connection to the
attacker's server and exfiltrated through the NAT gateway like any normal outbound traffic. The NAT
gateway's inbound-blocking (a side effect) is irrelevant because exfiltration is outbound. Prevention:
add real **egress controls** — **VPC endpoints** so AWS-service traffic (and any exfiltration attempt to
AWS APIs) is scoped and off the internet; **security-group egress rules** restricting outbound to
approved destinations and ports; an **egress proxy or AWS Network Firewall** with a **destination
allow-list** and logging so connections to unapproved destinations are blocked and alerted; give tiers
that need no internet **no default route**; and enable **VPC Flow Logs + GuardDuty** to detect anomalous
egress (unusual destination, data volume). Also reduce the blast radius with least-privilege IAM and
short-lived credentials so even successful egress yields less. The correction to state clearly: "the NAT
gateway provided connectivity, not egress control; we needed explicit egress controls, which were
absent."

### 14.19
NAT and a stateful firewall share the same core mechanism: a **connection-state table keyed on the
connection tuple**, where the presence of an entry governs how return/related traffic is handled. A
stateful firewall lets you write a rule for the initiating direction and automatically allows the return
traffic because it tracks the connection's state ("established/related") — you don't need a separate rule
for replies. NAT does the same tracking to know how to translate replies back to the correct internal
host. In Linux, both are built on the same **conntrack** subsystem (Chapter 37): NAT translations are
attached to conntrack entries, and stateful filtering matches on conntrack states. So NAT is essentially
"a stateful function (translation) implemented on top of connection tracking," and a stateful firewall
is "a filtering function implemented on top of the same connection tracking." Understanding NAT's table
(keying, statefulness, timeouts, finite size, DoS via exhaustion) directly explains stateful firewall
and security-group behavior — for example, why a security group needs only an inbound rule and permits
the return automatically, and why conntrack-table exhaustion is a denial-of-service for both. The key
difference: a stateful firewall *enforces policy* (allow/deny), while NAT only *translates* — which is
precisely why NAT is not a firewall despite sharing the statefulness.

### 14.20
NAT does not exist in IPv6 because IPv6's enormous address space (128 bits, Chapter 11) removes the
scarcity that made NAT necessary — every host can have a globally routable address, so there is no need
to share public IPs among private hosts. (NPTv6/IPv6-NAT exists but is discouraged; the IPv6 model is
"global addresses + stateful firewall.") Security implications: (1) the **incidental inbound-blocking
side effect of IPv4 NAT is absent** — IPv6 hosts are globally reachable by default, so reachability must
be controlled *explicitly* by firewalls (never by the accident of NAT); (2) on a **dual-stack host, any
"protection" attributed to IPv4 NAT does not apply to IPv6**, so a host "behind NAT" on IPv4 may be
wide open on IPv6 — the dual-stack bypass (Chapter 11 §5); (3) "private" IPv6 (outbound-only) must be
engineered with an **egress-only internet gateway** or no route, since there is no NAT to provide it. The
overarching implication reinforces the chapter's thesis: NAT was never a security control, and IPv6
makes that explicit by removing it while requiring firewalls to do the actual reachability control — so
engineers who relied on "NAT protects us" find that assumption gone in IPv6 and must control reachability
and egress deliberately.

---

*Next: Chapter 15 — DHCP: Bootstrapping Identity on a Network, and DHCP Attacks. We cover how hosts get
their IP configuration (the addresses, gateway, and DNS that everything so far assumed), and the DHCP
attacks (rogue servers, starvation) that let an attacker control a victim's entire network configuration
— plus the DHCP snooping defense that underpins Dynamic ARP Inspection (Chapter 9).*
