# Chapter 11 — IPv6: Addressing, SLAAC, NDP, and the Security Surprises

---

## 1. Why This Matters

IPv6 is the protocol most engineers ignore and most attackers do not. It is **enabled by default**
on every modern operating system — your Linux servers, your laptops, your phones, many cloud
resources — and it frequently runs *alongside* IPv4 (dual-stack) without anyone configuring or
monitoring it. That combination is a gift to attackers: a network meticulously hardened for IPv4
(firewall rules, DAI, monitoring) but blind to IPv6 has an entire unguarded parallel network.

The specific dangers a cloud security engineer must internalize:

- **Dual-stack bypass.** Your IPv4 firewall rules do not apply to IPv6. A host reachable only on a
  restricted IPv4 port may be wide open on IPv6 because nobody wrote the IPv6 rules. This is one of
  the most common real-world firewall gaps.
- **NDP attacks (Chapter 9 §5.1).** IPv6 replaces ARP with NDP, which has the same unauthenticated
  trust — and adds **rogue Router Advertisements**, which let an attacker become the default gateway
  *and* configure victims' addresses/DNS. This is often worse than ARP spoofing.
- **Auto-configuration surprises.** SLAAC means hosts configure their own IPv6 addresses without
  DHCP, so devices you did not provision get global addresses, and asset inventories built on IPv4/
  DHCP miss them.
- **Cloud IPv6.** AWS, GCP, and Azure all support IPv6, and its security model differs from IPv4 in
  important ways (no NAT by default, so IPv6 addresses are globally routable — a resource with an
  IPv6 address may be internet-reachable even if its IPv4 side is private). Getting this wrong
  exposes resources.

The lesson threading through this chapter, consistent with the book: **a control you did not write
is a control that does not exist.** IPv6 is the canonical example — the protocol is on, the attacks
work, and the defenses are absent by default. You do not need IPv6 *mastery* as a cloud security
engineer, but you need enough to (a) know it is there, (b) secure or disable it deliberately, and
(c) recognize its attacks. This chapter provides exactly that.

---

## 2. Prerequisites

- Chapter 10 (IPv4 addressing/CIDR — we contrast heavily) and Chapter 9 (ARP and NDP spoofing,
  §5.1).
- Chapter 8 (L2, broadcast/multicast) and Chapter 7 (hex — IPv6 is written in hex).
- Chapter 4 (the map) and Chapter 6 (cloud) for the dual-stack and cloud context.

---

## 3. Mental Model

**IPv6 solves IPv4's address exhaustion with a vastly larger space (128 bits), and in doing so
changes several security-relevant behaviors: no NAT by default, auto-configuration (SLAAC),
multicast instead of broadcast, and NDP instead of ARP. Each change is a security surprise if you
carry IPv4 assumptions.**

```
   IPv4:  32 bits  = 4.3 billion addresses     -> scarce -> NAT everywhere -> private is common
   IPv6:  128 bits = 340 undecillion addresses -> abundant -> NO NAT needed -> GLOBAL by default

   The security consequence in one line:
   In IPv4, a host is usually private and NAT'd (not directly reachable).
   In IPv6, a host often has a GLOBALLY ROUTABLE address by default.
   -> "It has an address" can mean "it is on the internet" in a way that was not true for IPv4.
```

The mental shift: with IPv4 you got some accidental protection from scarcity (NAT, private ranges).
IPv6 removes that accident — addresses are plentiful and global, so **reachability must be
controlled explicitly by firewalls/security groups, not by the accident of NAT.** If you assumed
"NAT protects it," IPv6 breaks that assumption silently.

Three things to hold:

1. **IPv6 is probably already on.** Assume dual-stack until proven otherwise.
2. **IPv6 needs its own firewall rules, monitoring, and NDP defenses** — IPv4 controls do not carry
   over.
3. **No NAT by default** means IPv6 addresses are globally routable; control reachability with
   firewalls, and understand that a "private" IPv4 host may be publicly reachable on IPv6.

---

## 4. Fundamentals

### 4.1 IPv6 address format

128 bits, written as eight groups of four hex digits (Chapter 7), separated by colons, with
compression rules:

```
   Full:        2001:0db8:0000:0000:0000:ff00:0042:8329
   Leading-zero drop:  2001:db8:0:0:0:ff00:42:8329
   Double-colon (one run of zero-groups):  2001:db8::ff00:42:8329
   Loopback:    ::1              (equivalent to IPv4 127.0.0.1)
   Unspecified: ::               (all zeros; like 0.0.0.0)
```

The `::` may appear **once** and represents one or more all-zero groups. `2001:db8::1` expands to
`2001:0db8:0000:0000:0000:0000:0000:0001`. Reading these fluently is just Chapter 7 hex applied to
groups.

Prefix notation is the same CIDR idea (Chapter 10): `2001:db8::/32` means the first 32 bits are the
prefix. Common prefixes:

```
   /48   typical site allocation
   /64   THE standard subnet size in IPv6 (64 network bits, 64 host/interface bits)
   /128  a single host
```

**The /64 subnet is a fixed convention** — SLAAC (§4.3) requires a /64 to work. So IPv6 subnetting
is much simpler than IPv4: subnets are /64s, and you have effectively unlimited of them. There is no
subnetting arithmetic to sweat; the interesting bits are the address *types*.

### 4.2 IPv6 address types (know these on sight)

| Type | Prefix | Meaning | IPv4 analogue |
|---|---|---|---|
| **Global unicast (GUA)** | `2000::/3` | globally routable — **internet-reachable** | public IP |
| **Unique local (ULA)** | `fc00::/7` (usually `fd00::/8`) | private, not internet-routed | RFC 1918 private |
| **Link-local (LLA)** | `fe80::/10` | auto-configured, one segment only | `169.254.0.0/16` |
| Loopback | `::1/128` | the host | `127.0.0.1` |
| Multicast | `ff00::/8` | group addressing (replaces broadcast) | `224.0.0.0/4` |
| Unspecified | `::/128` | no address | `0.0.0.0` |

Three security-critical points:

- **Global unicast (`2000::/3`) is internet-reachable.** Unlike an IPv4 private address behind NAT,
  a GUA on a host means that host can be reached from the internet if a route and firewall permit —
  and there is no NAT accidentally in the way. This is the single biggest IPv6 security surprise.
- **Link-local (`fe80::/10`) is always present.** Every IPv6 interface auto-configures a link-local
  address, used by NDP itself. It never leaves the segment (like ARP), so it is the medium of NDP
  attacks (§4.4). You will always see `fe80::...` on interfaces (`ip -6 addr`).
- **Unique local (`fd00::/8`) is the "private" choice** for internal networks that do not want
  global addressing — the closest IPv6 analogue to RFC 1918, though used less than you might expect
  because global addressing is abundant.

There is no metadata-service address quirk unique to IPv6 in the same way as `169.254.169.254`
(clouds still use the IPv4 link-local for IMDS, though IPv6 IMDS endpoints exist — `fd00:ec2::254`
in AWS); the link-local range remains the "auto-config, local only" one to recognize.

### 4.3 SLAAC: hosts configure themselves

**SLAAC (Stateless Address Autoconfiguration)** is IPv6's headline convenience and headline
surprise: a host can configure its own global IPv6 address *without a DHCP server*, using
information broadcast by the router.

```
   1. Host boots, auto-assigns a LINK-LOCAL address (fe80::...) from its interface identifier.
   2. Host sends a Router Solicitation (RS) multicast: "any routers here?"
   3. Router replies with a Router Advertisement (RA): "the prefix here is 2001:db8:1::/64,
        I am your default gateway, here is DNS (via RDNSS option)."
   4. Host forms its GLOBAL address: prefix (from RA) + interface identifier -> 2001:db8:1::<iid>
   5. Host is now globally addressed and has a default route -- with NO DHCP, NO admin action.
```

The security surprises:

- **Hosts self-assign global, internet-reachable addresses** based on whatever RA they hear. There
  is no central DHCP record, so **asset inventories and monitoring built on DHCP miss SLAAC hosts.**
- **The host trusts the RA.** Whoever sends the RA becomes the gateway and defines the prefix and
  DNS. This is the **rogue RA attack** (§4.4) — the most powerful IPv6 L2 attack.
- **Privacy addresses:** to avoid the interface identifier (originally derived from the MAC) leaking
  the device across networks, modern OSes use randomized/temporary addresses (RFC 4941/8981) that
  rotate. Good for privacy, but it means a host has *multiple* IPv6 addresses that change over time —
  complicating logging, allow-listing, and forensics.

DHCPv6 also exists (stateful, like IPv4 DHCP) and is used where central control is wanted, but SLAAC
is the default surprise.

### 4.4 NDP: IPv6's ARP replacement, with the same flaw plus more

**NDP (Neighbor Discovery Protocol)**, built on ICMPv6, replaces ARP and does more. Its messages:

| Message | ICMPv6 type | Purpose | IPv4 analogue |
|---|---|---|---|
| Router Solicitation (RS) | 133 | "any routers?" | — |
| Router Advertisement (RA) | 134 | "I'm a router, prefix is X, DNS is Y" | (DHCP-ish + gateway) |
| Neighbor Solicitation (NS) | 135 | "who has this IPv6?" | ARP request |
| Neighbor Advertisement (NA) | 136 | "I have it, at this MAC" | ARP reply |
| Redirect | 137 | "use this better router" | ICMP redirect |

Like ARP, **NDP is unauthenticated by default** (Chapter 9 §5.1). So:

- **NA spoofing** = ARP spoofing for IPv6: forge Neighbor Advertisements to redirect a victim's
  traffic to the attacker (MITM). Same mechanism, same defense (encryption + inspection).
- **Rogue RA** = a new, *more powerful* attack: send forged Router Advertisements to become the
  default gateway *and* dictate the prefix and DNS via SLAAC. One rogue RA can MITM an entire
  segment's IPv6 traffic and hand out attacker-controlled DNS — worse than ARP spoofing because it
  configures the victims, not just redirects. Tool: `flood_router6` / `fake_router6` (THC-IPv6).
- **ICMPv6 Redirect** abuse: trick a host into using the attacker as a "better" router.

The defenses (§11) mirror ARP's: **RA Guard** (switch drops RAs on non-router ports),
**ND Inspection / SAVI**, **SEND** (SEcure Neighbor Discovery, rarely deployed), and — the
load-bearing control everywhere — **encrypt traffic** so on-path position is useless (Chapter 9).

### 4.5 No NAT, and what that changes

IPv4's scarcity forced NAT (Chapter 14), which had an *accidental* security side effect: NAT'd hosts
are not directly reachable from the internet because they have no public address. Many organizations
came to rely on this accident.

IPv6 abundance removes the need for NAT — every host can have a global address. The consequences:

- **No accidental "NAT firewall."** In IPv6, reachability is controlled *only* by firewalls/security
  groups; there is no NAT hiding hosts. If you assumed NAT protected you, IPv6 exposes hosts you
  thought were private.
- **End-to-end addressing returns** (a design goal of IPv6), which is architecturally cleaner but
  means every host is potentially addressable and must be explicitly firewalled.
- **NPTv6 / IPv6 NAT exists** but is discouraged; the IPv6 philosophy is "global addresses + stateful
  firewall," not NAT.

The mental correction: **in IPv6, control reachability with firewalls explicitly; never rely on the
absence of a public address.** A host with a global unicast address and a permissive firewall is on
the internet, full stop.

---

## 5. Deep Technical Explanation: The Dual-Stack Bypass

The most common IPv6 security failure is not an exotic attack — it is the **dual-stack firewall
gap**. Walk it precisely, because it is the finding you will actually make:

```
   A server runs a service on port 8080, dual-stacked (listening on both 0.0.0.0:8080 and [::]:8080).
   The IPv4 firewall: "allow 8080 only from 10.0.0.0/8; deny the rest."   <- carefully written
   The IPv6 firewall: (empty / default-allow / never configured)          <- forgotten

   Result: the service is restricted on IPv4 but WIDE OPEN on IPv6.
   An attacker connects to [2001:db8::server]:8080 and bypasses the IPv4 rule entirely.
```

Why this happens constantly:

- **Services bind dual-stack by default.** A socket bound to `[::]` (IPv6 any) often *also* accepts
  IPv4 via IPv4-mapped addresses (Chapter 3 §4.4) — so "I only configured IPv4" does not mean "only
  IPv4 is listening." Check with `ss -tlpn` and look for `[::]` binds.
- **Firewall tools are separate for each family.** `iptables` (IPv4) and `ip6tables` (IPv6) are
  distinct; `nftables` can unify them but only if you write the rules. A rule in one does not apply
  to the other. Cloud security groups *do* cover both families in one rule set (an advantage), but
  you must add the IPv6 CIDRs explicitly.
- **Monitoring watches IPv4.** Flow logs, IDS, and dashboards often key on IPv4; IPv6 traffic slips
  by unwatched.

The defensive reflexes (§11): **for every IPv4 rule, write the IPv6 equivalent (or explicitly deny
IPv6); check `ss` for `[::]` binds; and either secure IPv6 to parity or disable it deliberately.**
The worst posture is "IPv6 is on and ignored" — which is the *default* posture, which is why this is
so common.

### 5.1 IPv6 in the cloud

In AWS (Chapter 75), IPv6 has specific behaviors that surprise IPv4-trained engineers:

- **IPv6 addresses in a VPC are global unicast** — there is no "private IPv6" equivalent to a private
  IPv4 subnet by default. A subnet's IPv6 range is globally routable *if* there is a route to an
  internet gateway.
- **The egress-only internet gateway (EIGW)** is IPv6's NAT-gateway analogue: it allows outbound IPv6
  and return traffic but blocks inbound-initiated — providing the "private" behavior explicitly,
  since there is no NAT. Using an EIGW (instead of a regular IGW) for a subnet that should be
  outbound-only is the IPv6 way to say "private."
- **Security groups and NACLs must include IPv6 rules explicitly.** An SG allowing `0.0.0.0/0`
  (IPv4) does *not* allow `::/0` (IPv6); conversely, adding `::/0` opens IPv6 to the world. The
  dual-stack gap applies in the cloud too — you must write both.
- **`::/0` is the IPv6 "entire internet"** — the direct analogue of `0.0.0.0/0` (Chapter 10), and an
  equally critical finding on a sensitive port.

The cloud lesson: **IPv6 is a parallel address family that needs parallel rules.** A security review
that checks IPv4 security groups and ignores IPv6 rules is half a review.

---

## 6. Internals: Observing IPv6

### 6.1 Your IPv6 configuration

```bash
$ ip -6 addr show
1: lo: ... inet6 ::1/128 scope host
2: eth0: ... inet6 2001:db8:1::42/64 scope global dynamic mngtmpaddr   # SLAAC global
          inet6 2001:db8:1::a1b2:c3d4:e5f6:7890/64 scope global temporary  # privacy address
          inet6 fe80::5054:ff:fe12:3456/64 scope link                  # link-local (always)

$ ip -6 route
2001:db8:1::/64 dev eth0 proto ra ...          # the RA-provided prefix (proto ra!)
default via fe80::gateway dev eth0 proto ra    # default gateway learned from RA
```

Read it: the `scope global` addresses are internet-routable (surprise if you thought this host was
"private"); `scope link` (`fe80::`) is always present; `proto ra` means these came from a Router
Advertisement (SLAAC) — trusting whoever sent it. Multiple global addresses (dynamic + temporary)
are the privacy-address behavior (§4.3).

### 6.2 The dual-stack bind check (the key audit)

```bash
$ ss -tlpn
tcp LISTEN 0 511 0.0.0.0:8080  0.0.0.0:*  users:(("app",...))
tcp LISTEN 0 511 [::]:8080     [::]:*     users:(("app",...))    # ALSO listening on IPv6!

# The [::] bind is the dual-stack surprise. Is it firewalled on IPv6?
$ sudo ip6tables -L -n | grep 8080 || echo "NO IPv6 rule for 8080 -> likely open!"
```

This two-command check — `ss` for `[::]` binds, then verify an IPv6 firewall rule exists — is the
core dual-stack audit and catches the §5 bypass.

### 6.3 NDP cache and messages

```bash
$ ip -6 neigh show                 # the NDP cache (like ARP's `ip neigh`)
2001:db8:1::1 dev eth0 lladdr 52:54:00:aa:bb:cc router REACHABLE   # the router (note 'router')
fe80::5054:ff:fe11:2233 dev eth0 lladdr 52:54:00:11:22:33 REACHABLE

$ sudo tcpdump -n -i eth0 icmp6 -c 10        # watch RS/RA/NS/NA (NDP)
# type 134 = RA (routers), 136 = NA (neighbor replies) -- the spoofable ones
```

Detection parallels ARP (Chapter 9 §6): watch for unexpected RAs (a rogue router), NDP cache
flapping, and one MAC claiming many IPv6 addresses.

### 6.4 Disable IPv6 deliberately (if you truly do not use it)

```bash
# Per-interface (runtime):
$ sudo sysctl -w net.ipv6.conf.eth0.disable_ipv6=1
# Refuse rogue RAs even if IPv6 is on:
$ sudo sysctl -w net.ipv6.conf.eth0.accept_ra=0
```

Disabling IPv6 is a legitimate choice *if* you genuinely do not use it and have verified nothing
depends on it — but the modern trend is to *use IPv6 securely* rather than disable it, since it is
increasingly required. The point is that the decision must be *deliberate*, not the default "on and
ignored."

---

## 7. Real-World Example: IPv6 in the Ledger Environments

**System A (VPS):** the VPS almost certainly has IPv6 enabled and a global IPv6 address, whether or
not anyone configured it. The risks:

- **Dual-stack bypass:** if the operator wrote `iptables` rules restricting SSH and the app to
  specific IPv4 sources but never wrote `ip6tables` rules, SSH and the app may be **open to the
  entire IPv6 internet** on the VPS's global IPv6 address. This is a real, common exposure. The fix
  is parity: mirror every IPv4 rule in `ip6tables` (or use `nftables` with both families), or disable
  IPv6 if unused.
- **The loopback binds (Chapter 3 §7)** still protect: PostgreSQL/Redis on `127.0.0.1`/`::1` are not
  exposed on either family. But Kestrel/Nginx bound to `[::]` are dual-stack and need IPv6 firewall
  parity.

**System B (AWS VPC):** if IPv6 is enabled on the VPC/subnets:

- **Security groups need IPv6 rules explicitly.** An SG allowing the ALB on `0.0.0.0/0:443` but not
  `::/0:443` means IPv6 clients cannot reach it (a functionality gap); conversely, adding `::/0` on a
  sensitive port is the IPv6 critical finding.
- **Data subnets must use an egress-only internet gateway or no IPv6 route** to keep IPv6 resources
  from being internet-reachable — the IPv6 way to provide the "private" property (§5.1), since there
  is no NAT.
- **The metadata service** is reached via IPv4 link-local (`169.254.169.254`) or the IPv6 endpoint
  (`fd00:ec2::254`) — SSRF defenses (Chapter 50) must consider both.

The recurring lesson, now for IPv6: **IPv6 is a parallel network that needs parallel controls;
"IPv4-secure" is not "secure" on a dual-stack host.** A cloud security review must check IPv6 rules,
IPv6 routes (EIGW vs IGW), and `[::]` binds — otherwise it certifies half the attack surface.

---

## 8. Hands-On Demonstration

### LAB 11.1 — Find and Close the Dual-Stack Gap

**Objective.** Discover IPv6 on your systems, demonstrate the dual-stack firewall bypass in an
isolated environment, close it with parity rules, and observe NDP.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Discover IPv6 on your host.*

```bash
ip -6 addr show                 # global (scope global) and link-local (fe80) addresses
ip -6 route                     # default route via RA?
sysctl net.ipv6.conf.all.disable_ipv6   # is it on? (0 = on)
ss -tlpn | grep '\[::\]'        # which services listen dual-stack?
```

Record: which services bind `[::]` (dual-stack), and whether you have a global IPv6 address.

*Step 2 — Demonstrate the bypass (isolated Docker network with IPv6).*

```bash
docker network create --ipv6 --subnet 2001:db8:cafe::/64 --subnet 172.28.0.0/24 v6lab 2>/dev/null || \
docker network create --ipv6 --subnet fd00:cafe::/64 v6lab
docker run -d --name v6svc --network v6lab nginx
# Restrict IPv4 with iptables INSIDE the container, but leave IPv6 open:
docker exec v6svc sh -c '
  apt-get update -qq && apt-get install -y -qq iptables >/dev/null 2>&1
  iptables -A INPUT -p tcp --dport 80 -s 172.28.0.5 -j ACCEPT
  iptables -A INPUT -p tcp --dport 80 -j DROP           # IPv4 restricted
  # NOTE: no ip6tables rules -> IPv6 port 80 wide open
'
docker exec v6svc sh -c 'ip -6 addr show eth0 | grep global'
# From another container, connect over IPv6 -> succeeds despite the IPv4 DROP:
docker run --rm --network v6lab nicolaka/netshoot sh -c '
  V6=$(getent hosts v6svc | awk "{print \$1}"); echo "target v6: $V6"
  curl -s -m3 "http://[$V6]:80" >/dev/null && echo "IPv6 BYPASS: reached the service" || echo "blocked"
'
```

**Expected:** the IPv6 connection succeeds even though IPv4 is restricted — the dual-stack bypass,
demonstrated. **Security implication:** the IPv4 firewall rule provided a false sense of protection.

*Step 3 — Close the gap with parity rules.*

```bash
docker exec v6svc sh -c '
  apt-get install -y -qq iptables >/dev/null 2>&1
  ip6tables -A INPUT -p tcp --dport 80 -j DROP    # mirror the IPv4 restriction on IPv6
'
docker run --rm --network v6lab nicolaka/netshoot sh -c '
  V6=$(getent hosts v6svc | awk "{print \$1}")
  curl -s -m3 "http://[$V6]:80" >/dev/null && echo "still reachable (check rules)" || echo "IPv6 now blocked: good"
'
```

*Step 4 — Observe NDP.*

```bash
docker exec v6svc sh -c 'ip -6 neigh show'                     # NDP cache
docker exec v6svc sh -c 'timeout 5 tcpdump -n -i eth0 icmp6 || true'   # RS/RA/NS/NA
```

**Security implications.** Write down: (a) how the IPv4 rule gave false assurance; (b) the two-command
audit (`ss` for `[::]`, then check `ip6tables`); (c) that NDP has ARP's trust problem plus rogue RAs;
(d) the choice between securing IPv6 to parity vs. disabling it deliberately.

**Cleanup.**
```bash
docker rm -f v6svc 2>/dev/null; docker network rm v6lab
```

---

## 9. Security Implications

- **IPv6 is on by default and usually ignored** — a parallel, unguarded network. "A control you did
  not write does not exist."
- **Dual-stack bypass is the top IPv6 finding:** IPv4 firewall rules do not apply to IPv6; a service
  restricted on IPv4 may be open on IPv6. Audit with `ss` (`[::]` binds) + IPv6 firewall check.
- **No NAT by default** means IPv6 addresses are globally routable; reachability must be controlled
  by firewalls explicitly — never rely on the absence of a public address.
- **NDP has ARP's unauthenticated trust plus rogue RAs**, which let an attacker become the gateway and
  set prefix/DNS — often worse than ARP spoofing. Defenses mirror ARP's (RA Guard, ND inspection),
  with encryption as the load-bearing control.
- **SLAAC self-configures global addresses without DHCP**, so DHCP-based asset inventories and
  monitoring miss IPv6 hosts; privacy addresses rotate, complicating logging and allow-lists.
- **Cloud IPv6 needs parallel rules**: security groups/NACLs must include IPv6 CIDRs (`::/0` = the
  internet), and "private" IPv6 requires an egress-only internet gateway or no IPv6 route.

---

## 10. Attack Scenarios

1. **Dual-stack firewall bypass** (§5): reach a service over IPv6 that is restricted on IPv4 —
   SSH, databases, admin panels. The most common IPv6 attack, requiring no exotic technique.
2. **Rogue Router Advertisement** (§4.4): forge RAs to become the default gateway and set DNS via
   SLAAC, MITM'ing the whole segment's IPv6 traffic and redirecting DNS — worse than ARP spoofing.
3. **Neighbor Advertisement spoofing** (§4.4): the IPv6 ARP-spoofing equivalent for targeted MITM.
4. **RA flooding DoS** (`flood_router6`): overwhelm hosts with bogus RAs, exhausting resources as
   they process addresses/routes.
5. **IPv6 as a covert/evasion channel:** exfiltrate or C2 over IPv6 where monitoring only watches
   IPv4 — a real IDS blind spot.
6. **SLAAC-based reconnaissance evasion:** attacker hosts self-assign addresses invisible to
   DHCP-based inventories, and privacy-address rotation frustrates IP-based blocking/tracking.
7. **Cloud IPv6 exposure:** an SG rule adding `::/0` on a sensitive port, or an IPv6 subnet with an
   IGW route where an egress-only gateway was intended, exposing a resource thought private.

---

## 11. Defensive Techniques

- **Achieve firewall parity.** For every IPv4 rule, write the IPv6 equivalent (or an explicit IPv6
  deny). Use `nftables` (unified families) or maintain `iptables` + `ip6tables` together; in the
  cloud, add IPv6 CIDRs to every relevant security group/NACL rule. Audit with `ss` for `[::]` binds.
- **Decide deliberately: secure IPv6 or disable it.** If you use it, secure it to parity; if you
  genuinely do not and have verified nothing depends on it, disable it
  (`net.ipv6.conf.*.disable_ipv6=1`) so it is not an unmonitored surface. The default "on and
  ignored" is the only wrong choice.
- **Defend NDP.** Enable **RA Guard** and **ND Inspection/SAVI** on switches to drop rogue RAs/NAs;
  set `accept_ra=0` on hosts that should not learn routes from RAs (e.g. servers with static
  config); consider SEND where supported. As with ARP, **encrypt traffic (TLS/mTLS)** so on-path
  position is useless — the load-bearing control (Chapter 9).
- **Control IPv6 reachability explicitly.** No NAT means firewalls are the only reachability control;
  for "private" IPv6 in AWS use an **egress-only internet gateway** (outbound + return only) or no
  IPv6 route; treat `::/0` on sensitive ports as critical, exactly like `0.0.0.0/0`.
- **Monitor IPv6.** Ensure flow logs, IDS, and dashboards cover IPv6, and include IPv6 addresses in
  inventories (do not rely on DHCP records — SLAAC hosts are missing). Account for privacy-address
  rotation in logging/allow-listing.
- **Include IPv6 in SSRF defenses** (block `fc00::/7`, `fe80::/10`, `::1`, IPv4-mapped `::ffff:0:0/96`,
  and the IPv6 metadata endpoint) — Chapter 50.

---

## 12. Production Architecture

IPv6 controls alongside IPv4, VPS vs cloud:

```
 CONCEPT              IPv4 (recap)              IPv6 (parallel — must be configured too)
 ------------------   -----------------------   ------------------------------------------
 firewall            iptables / SG (v4 CIDR)    ip6tables / SG (v6 CIDR) -- PARITY required
 "entire internet"   0.0.0.0/0                  ::/0
 private/reachability NAT + RFC1918 subnets     stateful firewall; EIGW for outbound-only
 L2/L3 neighbor      ARP (+ DAI)               NDP (+ RA Guard / ND Inspection)
 auto-config         DHCP (central record)      SLAAC (no record) + optional DHCPv6
 metadata SSRF       169.254.169.254            + fd00:ec2::254 (AWS)
 monitoring          flow logs / IDS (v4)       MUST also cover v6
 load-bearing control TLS/mTLS                  TLS/mTLS (same)
```

The architectural principle: **IPv6 is not "IPv4 with longer addresses"; it is a parallel address
family with its own reachability model (no NAT), its own neighbor protocol (NDP with rogue RAs), and
its own auto-config (SLAAC).** Every network control must be duplicated or explicitly extended to
IPv6, or the design has a hole exactly the size of the IPv6 attack surface. A mature design either
uses IPv6 with full-parity controls and monitoring, or disables it deliberately after verification —
never leaves it as the default unguarded parallel network.

---

## 13. Common Mistakes

1. **Ignoring IPv6 entirely** — it is on by default, so ignoring it means an unguarded parallel
   network (the dual-stack bypass).
2. **Writing IPv4 firewall rules only**, assuming they cover IPv6. They do not (`iptables` ≠
   `ip6tables`; `0.0.0.0/0` ≠ `::/0`).
3. **Relying on "no public IP / NAT" for IPv6 privacy** — there is no NAT by default; use an
   egress-only gateway or firewall explicitly.
4. **Forgetting NDP defenses** (RA Guard) — rogue RAs MITM the whole segment.
5. **Asset inventory/monitoring built on IPv4/DHCP** — SLAAC hosts and IPv6 traffic are missed.
6. **Not accounting for privacy-address rotation** — IP-based allow-lists and forensics break when a
   host has multiple, rotating IPv6 addresses.
7. **Adding `::/0` on sensitive ports** in cloud SGs — the IPv6 critical exposure.
8. **Excluding IPv6 from SSRF blocklists** (missing `fc00::/7`, link-local, IPv4-mapped, IPv6 IMDS).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Service reachable despite IPv4 firewall | dual-stack bypass (no IPv6 rule) | `ss -tlpn \| grep '::'`; `ip6tables -L -n`; add parity rules |
| Host got an unexpected global IPv6 address | SLAAC from an RA | `ip -6 addr`; `ip -6 route` (proto ra); check for rogue RAs |
| IPv6 default route changed / MITM suspected | rogue Router Advertisement | `ip -6 route`; `radvdump`/`tcpdump icmp6` for RAs; enable RA Guard |
| Cloud resource unexpectedly internet-reachable | IPv6 subnet has IGW route + `::/0` SG | check route table (IGW vs EIGW), SG IPv6 rules |
| Logs show unfamiliar IPv6 addresses for one host | privacy/temporary addresses rotating | `ip -6 addr` (temporary flag); correlate by MAC/interface id |
| IPv6 clients can't reach a service | SG allows `0.0.0.0/0` but not `::/0` | add the IPv6 CIDR to the SG rule |
| SSRF protection bypassed via IPv6 | blocklist omits IPv6 internal ranges | add fc00::/7, fe80::/10, ::1, ::ffff:0:0/96, IMDS v6 |

---

## 15. Practical Lab

Lab 11.1 is in §8. Register it in the lab index. Extension: audit a real host or cloud environment
for IPv6 parity — enumerate every `[::]` bind, every IPv4 firewall/SG rule, and confirm a
corresponding IPv6 rule (or explicit deny) exists; produce a findings list of any IPv4-only-protected
services. This is a genuine and frequently-fruitful review, because the dual-stack gap is so common.

---

## 16. Exercises

### Concept questions

**11.1** Explain why IPv6's lack of NAT is a security surprise for engineers trained on IPv4. What
must replace NAT as the reachability control?

**11.2** Compress `2001:0db8:0000:0000:0000:ff00:0042:8329` and expand `fd00::1`. What do the `::`
rules allow and forbid?

**11.3** Identify the type and internet-reachability of each: `2001:db8::5`, `fe80::1`, `fd12:3456::7`,
`::1`, `::/0`. Give the IPv4 analogue of each.

**11.4** Explain SLAAC step by step, and why it is both a convenience and a security surprise (asset
inventory, rogue RA).

**11.5** Compare NDP to ARP: what is the same (the flaw), and what does NDP add that is worse (rogue
RA)? What defends each?

### Debugging problems

**11.6** A service is restricted to internal sources on IPv4 but a pentest reaches it from the
internet. `ss -tlpn` shows it listening on `[::]:9000`. Explain and fix.

**11.7** After an IPv6 rollout, hosts intermittently route through an unexpected gateway and DNS
answers look tampered. What attack is this, and how do you confirm and defend?

**11.8** A cloud resource meant to be private is reachable from the internet over IPv6 though its
IPv4 side is in a private subnet. What was misconfigured?

### Security scenarios

**11.9** You are asked to secure a dual-stack fleet. Give your step-by-step approach to bring IPv6 to
security parity with IPv4, including audit, firewall, NDP, and monitoring.

**11.10** A team says "we don't use IPv6, so we ignore it." Evaluate this and give the two acceptable
postures and how to choose.

### Architecture questions

**11.11** Design IPv6 reachability for a three-tier VPC (public/app/data) without NAT: which gateway
each tier uses, and how you achieve "private" for the data tier.

**11.12** Explain how the "control you did not write does not exist" principle applies to IPv6, and
generalize it to two other areas of the book.

### Hands-on exercises

**11.13** Find every `[::]` bind on a host and, for each, verify whether an IPv6 firewall rule
restricts it; report any IPv4-only-protected services.

**11.14** In an isolated IPv6-enabled Docker network, demonstrate the dual-stack bypass and then
close it with `ip6tables` parity (Lab 11.1).

**11.15** Write an SSRF blocklist (or allow-list validator) that correctly handles IPv6 internal
ranges and IPv4-mapped addresses.

### Interview questions

**11.16** "Why is IPv6 a security concern even in shops that 'don't use it'?"

**11.17** "Walk me through the dual-stack firewall bypass and how you'd audit for it."

**11.18** "How does IPv6 change the reachability model compared to IPv4, and why does that matter?"

**11.19** "What is a rogue Router Advertisement, and how is it worse than ARP spoofing?"

**11.20** "How would you secure IPv6 in an AWS VPC to the same standard as IPv4?"

---

## 17. Summary

- **IPv6 (128-bit) is enabled by default and usually ignored**, creating an unguarded parallel
  network — the embodiment of "a control you did not write does not exist."
- Addresses are hex, eight groups, with `::` compression; the standard subnet is **/64**; key types:
  **global unicast `2000::/3` (internet-reachable), unique-local `fc00::/7` (private), link-local
  `fe80::/10` (segment-only, NDP's medium), `::1` loopback, `::/0` the entire internet.**
- **No NAT by default** — IPv6 addresses are globally routable, so reachability must be controlled by
  firewalls explicitly; never rely on the absence of a public address. In AWS, "private" IPv6 uses an
  **egress-only internet gateway**.
- **SLAAC** self-configures global addresses from Router Advertisements without DHCP — convenient but
  invisible to DHCP-based inventories, and trusting the RA.
- **NDP** replaces ARP with the **same unauthenticated trust (NA spoofing = ARP spoofing) plus rogue
  RAs**, which let an attacker become the gateway and set DNS — often worse than ARP spoofing.
  Defenses: RA Guard, ND Inspection, and — load-bearing — **encryption**.
- **The dual-stack bypass is the top IPv6 finding:** IPv4 firewall rules do not cover IPv6, so a
  service restricted on IPv4 may be open on IPv6. Audit with `ss` (`[::]` binds) + IPv6 firewall
  check; achieve **parity** or disable IPv6 deliberately.
- **Cloud IPv6 needs parallel rules** — security groups/NACLs must include IPv6 CIDRs (`::/0` = the
  internet, a critical finding on sensitive ports), monitoring must cover IPv6, and SSRF defenses must
  include IPv6 internal ranges.

---

## 18. Knowledge Check

1. Why is "no NAT by default" a security surprise, and what replaces NAT? (§3, §4.5)
2. What is the standard IPv6 subnet size, and why? (§4.1, §4.3)
3. Give the IPv4 analogue of `2000::/3`, `fe80::/10`, `fc00::/7`, `::1`, `::/0`. (§4.2)
4. What is SLAAC and why is it a security surprise? (§4.3)
5. What is a rogue RA and why is it worse than ARP spoofing? (§4.4)
6. What is the dual-stack bypass and how do you audit for it? (§5)
7. How do you provide "private" IPv6 in AWS without NAT? (§5.1)
8. Which two-command check reveals dual-stack exposure? (§6.2)
9. What is the IPv6 "entire internet" CIDR, and why does it matter? (§5.1)
10. What is the load-bearing defense against NDP MITM? (§4.4, §11)

---

## 19. Further Exploration

- RFC 4291 (IPv6 addressing) and RFC 4862 (SLAAC) — the primary sources; skim for the address types
  and the RA/SLAAC flow.
- Run `ip -6 addr`, `ip -6 route`, and `ss -tlpn | grep '::'` on every host you manage this week —
  discover your actual IPv6 footprint.
- THC-IPv6 toolkit docs (read-only) for the attack landscape (`fake_router6`, `flood_router6`,
  `parasite6`) — understand what RA Guard defends against.
- AWS VPC IPv6 documentation, especially the egress-only internet gateway — the concrete §5.1
  mechanism.
- Revisit Chapter 9 and note that ARP spoofing + NDP spoofing are the same lesson twice: unauthenticated
  neighbor protocols, defeated by encryption. Chapter 43 (Zero Trust) generalizes it.

---

## Solutions

### 11.1
IPv4's address scarcity forced NAT, which had an accidental security side effect: NAT'd hosts have no
public address, so they are not directly reachable from the internet, and many organizations came to
rely on this "NAT firewall." IPv6's abundance removes the need for NAT — every host can have a global,
internet-routable address — so that accidental protection disappears. Engineers who assumed "it has
no public IP, so it's safe" find IPv6 hosts globally reachable. What must replace NAT is an
**explicit stateful firewall** (host firewall, security group, or an egress-only gateway for
outbound-only): reachability in IPv6 is controlled only by firewall rules, never by the accident of
address scarcity. The mental correction is "control reachability explicitly; a global unicast address
+ a permissive firewall = on the internet."

### 11.2
Compressed: `2001:db8::ff00:42:8329` (drop leading zeros in each group, and replace the single run of
all-zero groups `0000:0000:0000` with `::`). Expanded `fd00::1` = `fd00:0000:0000:0000:0000:0000:0000:0001`.
The `::` rules: it may appear **at most once** in an address (because otherwise the number of zero
groups it represents would be ambiguous), and it stands for one or more consecutive all-zero 16-bit
groups. Within each group, leading zeros may be dropped (`00ff`→`ff`, `0000`→`0`), but a group of `0`
is only elided by `::`, and you cannot use `::` for a single already-short group if it creates
ambiguity. So `::` compresses the longest (or a chosen) run of zero groups, once.

### 11.3
`2001:db8::5` — global unicast (`2000::/3`), **internet-reachable**; analogue: public IPv4.
`fe80::1` — link-local (`fe80::/10`), **segment-only, not routed**; analogue: `169.254.0.0/16`.
`fd12:3456::7` — unique-local (`fc00::/7`, `fd00::/8`), **private, not internet-routed**; analogue:
RFC 1918 (10/8, 172.16/12, 192.168/16). `::1` — loopback, **the host itself**; analogue: `127.0.0.1`.
`::/0` — the **entire internet** (all addresses), used as "from/to anywhere" in firewall rules;
analogue: `0.0.0.0/0`. The two to flag in rules: a global unicast source/dest means real
internet reachability (no NAT hiding it), and `::/0` on a sensitive port is a critical exposure like
`0.0.0.0/0`.

### 11.4
SLAAC (Stateless Address Autoconfiguration): (1) the host auto-assigns a link-local address
(`fe80::` + interface identifier); (2) it multicasts a Router Solicitation ("any routers?"); (3) a
router replies with a Router Advertisement carrying the on-link prefix (a /64), itself as default
gateway, and often DNS (RDNSS); (4) the host forms its **global** address = prefix + interface
identifier; (5) it now has a globally routable address and default route — with no DHCP and no admin
action. It is a convenience because hosts self-configure with zero infrastructure. It is a security
surprise for two reasons: (a) there is **no central record** (unlike DHCP), so asset inventories and
monitoring built on DHCP miss SLAAC hosts, and hosts you did not provision can obtain global
addresses; and (b) the host **trusts the RA**, so whoever sends an RA controls the prefix, gateway,
and DNS — the basis of the **rogue RA** attack (§4.4). Privacy/temporary addresses (RFC 8981) add
further churn, giving a host multiple rotating global addresses.

### 11.5
Same: both ARP and NDP are **unauthenticated neighbor-resolution protocols** that believe whatever
they are told, so both are spoofable — **NA (Neighbor Advertisement) spoofing** is the exact IPv6
equivalent of ARP reply spoofing, redirecting a victim's traffic to the attacker for a targeted MITM.
Worse in NDP: the **rogue Router Advertisement**. Because IPv6 hosts configure themselves from RAs
(SLAAC), a forged RA lets the attacker become the **default gateway** for the whole segment *and*
dictate the prefix and **DNS** — configuring the victims, not merely redirecting one mapping. One
rogue RA can MITM an entire segment's IPv6 traffic and hijack DNS, which is broader and easier than
poisoning each victim's ARP. Defenses: for NA spoofing, ND Inspection/SAVI (like DAI); for rogue RAs,
**RA Guard** (switch drops RAs on non-router ports) and host `accept_ra=0`; SEND where supported; and
— the load-bearing control for both — **TLS/mTLS encryption** so on-path position yields only
ciphertext (Chapter 9). The lesson is ARP's, twice.

### 11.6
The service binds `[::]:9000` (dual-stack), so it listens on IPv6 as well as IPv4. The internal
restriction was written only in IPv4 (`iptables`/an IPv4 SG rule), and no equivalent IPv6 rule
exists, so the service is **open to the entire IPv6 internet** on the host's global IPv6 address —
the dual-stack bypass (§5). The pentest reached it via `[2001:db8::host]:9000`. Confirm: `ss -tlpn`
shows the `[::]` bind; `ip6tables -L -n` (or the cloud SG's IPv6 rules) shows no restriction on 9000.
Fix: add an IPv6 firewall rule mirroring the IPv4 one (restrict to internal IPv6 sources, or deny),
or, if IPv6 is not needed for this service, bind it to IPv4 only / disable IPv6. Systemic fix: audit
all `[::]` binds for IPv6-rule parity, and prefer `nftables`/cloud SGs that make writing both
families explicit.

### 11.7
This is a **rogue Router Advertisement** attack (§4.4): an attacker on the segment sends forged RAs,
becoming the default gateway (so hosts route through them) and advertising attacker-controlled DNS
(so DNS answers are tampered) — a full IPv6 MITM plus DNS hijack. Confirm: on affected hosts,
`ip -6 route` shows a default route (`proto ra`) via an unexpected gateway, and `ip -6 addr`/RDNSS
shows an unexpected prefix/DNS; capture RAs with `tcpdump -n icmp6` / `radvdump` and look for RAs
from a non-router MAC or conflicting RAs. Defend: enable **RA Guard** on the switch to drop RAs on
non-router ports; set `accept_ra=0` on hosts with static config; segment; and — decisively —
**encrypt traffic (TLS/mTLS)** and validate DNS (DNSSEC/DoH to a trusted resolver, Chapter 17) so the
MITM and DNS tampering are neutralized even if a rogue RA succeeds. This is Chapter 9's ARP lesson in
IPv6 form, with the added gateway/DNS control that makes it worse.

### 11.8
IPv6 was misconfigured to be internet-reachable while IPv4 was correctly private. Likely causes: the
IPv6 subnet's route table has a route to a regular **internet gateway** (`::/0` → IGW) instead of an
**egress-only internet gateway** (or no IPv6 route), so inbound IPv6 is possible; and/or the security
group/NACL allows `::/0` (or a broad IPv6 range) on the resource's port, whereas the IPv4 side had no
such allowance and sat in a private subnet with no IPv4 internet route. Because IPv6 has **no NAT**,
the "private" behavior IPv4 got from being in a private subnet with NAT-only egress must be
re-created explicitly with an egress-only gateway and restrictive IPv6 firewall rules — which was
missed. Fix: replace the IGW route for that subnet's IPv6 with an egress-only internet gateway (or
remove the IPv6 route), and remove the `::/0` allowance from the SG; verify with the route table and
IPv6 SG rules. The lesson: "private" must be configured for IPv6 separately and explicitly (§5.1).

### 11.9
Step-by-step parity approach: (1) **Discover** — inventory every host's IPv6 config (`ip -6 addr/
route`), every `[::]` bind (`ss -tlpn`), and whether IPv6 is on; build the true dual-stack footprint,
not the DHCP-based one (SLAAC hosts are missing). (2) **Firewall parity** — for every IPv4 rule
(host `iptables`, cloud SGs/NACLs), add the IPv6 equivalent, or an explicit IPv6 deny; migrate to
`nftables`/SGs that express both families; treat `::/0` on sensitive ports as critical. (3)
**Reachability** — ensure "private" tiers use egress-only gateways / no IPv6 internet route (no NAT
to hide them). (4) **NDP defenses** — enable RA Guard and ND Inspection on switches; `accept_ra=0` on
statically-configured servers. (5) **Monitoring** — extend flow logs, IDS, and dashboards to IPv6;
account for privacy-address rotation in logging/allow-lists; add IPv6 to inventory. (6) **SSRF/egress
controls** — include IPv6 internal ranges and the IPv6 IMDS endpoint. (7) **Encryption** — TLS/mTLS
everywhere as the load-bearing control regardless of family. (8) **Verify** — re-audit that no
service is IPv4-only-protected. The theme: bring IPv6 to full parity or disable it deliberately;
never leave it on-and-ignored.

### 11.10
"We don't use IPv6, so we ignore it" is **not acceptable**, because IPv6 is on by default on modern
systems whether or not you "use" it — services bind dual-stack (`[::]`), hosts obtain global
addresses via SLAAC, and NDP runs on the wire. Ignoring it means an unmonitored, unfirewalled
parallel network: the dual-stack bypass exposes services you thought were restricted, rogue RAs can
MITM the segment, and IPv6 traffic evades IPv4-only monitoring. The two acceptable postures: (1)
**Use IPv6 securely** — bring it to full parity with IPv4 (firewall rules, NDP defenses, monitoring,
encryption) as in Ex. 11.9; the modern default, since IPv6 is increasingly required. (2) **Disable it
deliberately** — after verifying nothing depends on it, turn IPv6 off (`disable_ipv6=1`, and
`accept_ra=0`) on hosts and remove IPv6 from cloud subnets, so there is no unguarded surface. Choose
(1) if you need IPv6 (public-facing services, modern clients, cloud IPv6 requirements) or foresee
needing it; choose (2) only for controlled environments where you can and do verify IPv6 is truly
absent. The unacceptable option is the default middle: on and ignored.

### 11.11
Design (no NAT in IPv6): **Public tier** — subnet with a route `::/0` → **internet gateway** (IGW) so
the ALB/edge is reachable inbound and outbound over IPv6; SG allows `::/0` only on 443. **App tier** —
subnet with a route `::/0` → **egress-only internet gateway (EIGW)** so instances can make outbound
IPv6 connections (updates, APIs) and receive return traffic, but **cannot** be reached
inbound-initiated from the internet; SG allows inbound only from the ALB's SG. **Data tier** — subnet
with **no IPv6 default route at all** (or EIGW only if outbound is genuinely needed), so RDS/cache is
unreachable from the internet by routing; SG allows inbound only from the app SG on the DB port.
Achieving "private" for the data tier: the combination of **no IGW route** (routing blocks inbound),
**no global reachability path**, and a **restrictive SG** — three layers, since IPv6 has no NAT to
provide accidental hiding. The EIGW is the key IPv6 construct: it gives outbound-only behavior that
IPv4 got from a NAT gateway. Verify each tier's route table (IGW vs EIGW vs none) and IPv6 SG rules.

### 11.12
"A control you did not write does not exist" applies to IPv6 directly: the protocol is *on* and its
attacks *work*, but the defenses (firewall rules, NDP guards, monitoring) are *absent by default*, so
the mere existence of IPv4 controls provides no IPv6 protection — you must explicitly write IPv6
controls or the surface is open (the dual-stack bypass). Generalizations: (1) **Kubernetes
NetworkPolicy** (Chapter 104) — a cluster with no NetworkPolicy is default-allow; the "control" of
network segmentation does not exist until you write policies, and assuming pods are isolated because
they are "internal" is the same error as assuming IPv4 rules cover IPv6. (2) **Cloud logging/
detection** (Chapter 82) — CloudTrail/GuardDuty/Config provide no protection until enabled and their
findings acted upon; an unmonitored account is unguarded exactly as an unmonitored IPv6 stack is. The
unifying principle: security properties come from *explicitly configured, active controls*, never from
defaults or from the existence of a related control on a different surface — so a review must
enumerate what is actually configured, family by family, surface by surface.

### 11.13
Expected: `ss -tlpn | grep '\[::\]'` to list every dual-stack (IPv6) listener with its process/port;
then for each, check `ip6tables -L -n` (host) or the cloud SG's IPv6 rules for a restriction on that
port. Script shape: parse the `[::]:PORT` binds, and for each grep the IPv6 firewall for a matching
rule; report any port that is listening on IPv6 but has no IPv6 restriction as "IPv4-only-protected —
FINDING." Refinements: cross-check that the IPv4 rule for the same port *is* restrictive (so the
finding is real), resolve the process/owner, and in the cloud query SG rules via the API and diff
IPv4 vs IPv6 CIDRs. The deliverable is a list of services protected on IPv4 but open (or unrestricted)
on IPv6 — precisely the dual-stack gap, and a common, high-value finding.

### 11.14
Expected: create an IPv6-enabled Docker network, run a service, restrict it on IPv4 with `iptables`
(accept from one source, drop the rest on the port) while leaving IPv6 unconfigured; from another
container, connect over the service's global IPv6 address and observe success despite the IPv4 DROP —
the dual-stack bypass. Then add the parity rule `ip6tables -A INPUT -p tcp --dport <port> -j DROP`
(mirroring the IPv4 restriction) and re-test to confirm the IPv6 path is now blocked. The deliverable
is the before/after demonstration: same service, IPv4-restricted but IPv6-open, then closed by writing
the IPv6 rule — proving that IPv4 rules do not cover IPv6 and that parity must be written explicitly
(§5, §11).

### 11.15
Expected: an SSRF validator that, after resolving the target, checks the IP against a comprehensive
internal set including **both** families: IPv4 `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
`127.0.0.0/8`, `169.254.0.0/16`, `0.0.0.0/8`; and IPv6 `::1/128` (loopback), `fc00::/7` (unique-local),
`fe80::/10` (link-local), `::ffff:0:0/96` (**IPv4-mapped** — critical: `::ffff:169.254.169.254`
reaches the metadata service and bypasses naive IPv4-only blocklists), `::/128`, and the IPv6 IMDS
endpoint (`fd00:ec2::254` in AWS). Implementation with Python `ipaddress`: resolve, then test
`addr in net` for each blocked network (and handle IPv4-mapped by extracting the embedded IPv4).
Best practice (Chapter 50): prefer an **allow-list of the resolved destination**, re-resolve at
connection time (defeat DNS rebinding), and reject the connection if the resolved IP is in any
internal range in either family. The key gotcha the exercise teaches: IPv4-mapped IPv6 addresses let
an attacker reach IPv4 internal targets through the IPv6 path, so an IPv4-only blocklist is bypassable.

### 11.16
Because IPv6 is enabled by default on modern operating systems and cloud resources, so "we don't use
it" is almost never literally true — services bind dual-stack (`[::]`), hosts self-configure global
addresses via SLAAC, and NDP runs on the segment, all without anyone acting. The result is an
**unguarded parallel network**: IPv4 firewall rules do not cover IPv6, so a service carefully
restricted on IPv4 may be wide open to the IPv6 internet (the dual-stack bypass); rogue Router
Advertisements can MITM the segment and hijack DNS; IPv6 traffic evades IPv4-only monitoring, making
it an exfiltration/C2 channel; and DHCP-based asset inventories miss SLAAC hosts. So even a shop that
believes it does not use IPv6 has the full IPv6 attack surface active and undefended. The correct
posture is to either secure IPv6 to parity or disable it deliberately after verification — never
leave it on and ignored, which is the default and the danger.

### 11.17
Dual-stack bypass: a host runs a service listening on both IPv4 and IPv6 (a `[::]` bind, which often
also accepts IPv4). The operator writes firewall rules restricting the service on IPv4 (e.g. allow
only internal sources) but never writes the IPv6 equivalent, because IPv4 and IPv6 firewalls are
separate (`iptables` vs `ip6tables`; `0.0.0.0/0` ≠ `::/0`; cloud SGs need IPv6 CIDRs added
explicitly). The service is therefore restricted on IPv4 but open on IPv6, and an attacker connects
to the host's global IPv6 address to bypass the IPv4 rule entirely. Audit: run `ss -tlpn` and look
for `[::]` (dual-stack) listeners; for each, verify an IPv6 firewall rule (`ip6tables -L`, or the
cloud SG's IPv6 rules) restricts it as the IPv4 rule does; any service listening on IPv6 without a
matching IPv6 restriction is a finding. Fix by writing parity rules (or disabling IPv6 for that
service). It is one of the most common real-world firewall gaps precisely because IPv6 is on by
default and its rules are an easy, silent omission.

### 11.18
IPv4 is scarce, so hosts are usually behind NAT with private (RFC 1918) addresses, which gives an
*accidental* protection: no public address means not directly internet-reachable. IPv6 is abundant,
so **no NAT is needed** and hosts commonly have **global, internet-routable addresses by default**.
The reachability model therefore changes from "protected by NAT/scarcity unless you expose it" to
"reachable by default unless you firewall it." This matters because engineers who relied on "no
public IP = safe" are wrong in IPv6: a host with a global unicast address and a permissive (or
absent) firewall is on the internet. Reachability must be controlled **explicitly** with stateful
firewalls, and "private" must be engineered (egress-only internet gateway, or no IPv6 route, plus
restrictive rules) rather than inherited from NAT. The upside is IPv6 restores end-to-end addressing
(cleaner architecture); the security cost is that every host is potentially addressable and must be
deliberately firewalled — no accidental hiding.

### 11.19
A rogue Router Advertisement is a forged NDP RA (ICMPv6 type 134) sent by an attacker on the segment.
Because IPv6 hosts auto-configure from RAs (SLAAC), a host that accepts the forged RA will take the
attacker as its **default gateway**, adopt an attacker-specified **prefix**, and use
attacker-specified **DNS** (RDNSS). It is worse than ARP spoofing for three reasons: (1) it
**configures** the victims (gateway + prefix + DNS) rather than merely poisoning one IP→MAC mapping,
so a single RA can MITM an entire segment's IPv6 traffic at once; (2) it hijacks **DNS**, enabling
redirection to attacker servers on top of interception; and (3) it exploits a default-on behavior
(hosts listen for RAs by default), so no per-victim targeting is needed. ARP spoofing must poison
each victim's cache for a specific IP; a rogue RA broadcasts a full network configuration the segment
accepts. Defenses: **RA Guard** on switches (drop RAs on non-router ports), host `accept_ra=0`, ND
Inspection/SAVI, SEND where supported, and encryption + DNSSEC/trusted resolvers to neutralize the
impact.

### 11.20
Bring IPv6 to full parity with IPv4 in the VPC: (1) **Security groups and NACLs** — for every IPv4
rule, add the IPv6 CIDR equivalent, and treat `::/0` on sensitive ports as a critical finding exactly
like `0.0.0.0/0`; ensure intended IPv6 access exists (an SG allowing `0.0.0.0/0:443` but not
`::/0:443` breaks IPv6 clients). (2) **Reachability/routing** — public subnets route `::/0` to the
IGW; app subnets use an **egress-only internet gateway** (outbound + return only); data subnets have
no IPv6 internet route — the no-NAT way to achieve "private." (3) **Metadata/SSRF** — account for the
IPv6 IMDS endpoint (`fd00:ec2::254`) and IPv4-mapped addresses in egress/SSRF controls. (4)
**Monitoring** — ensure VPC Flow Logs, GuardDuty, and any IDS cover IPv6 (they can, but verify), and
include IPv6 addresses in inventory (SLAAC/temporary addresses). (5) **Encryption** — TLS/mTLS
regardless of family. (6) **Policy-as-code** — add checks that flag `::/0` on sensitive ports and any
IPv4 rule lacking an IPv6 counterpart (Chapter 91). Verify by auditing that no resource is
IPv4-only-protected and that data-tier IPv6 has no inbound internet path. The principle: IPv6 is a
parallel family requiring parallel controls; parity or deliberate disablement, never on-and-ignored.

---

*Next: Chapter 12 — Routing: Tables, Default Gateways, Longest-Prefix Match, and the Journey of a
Packet. We follow a packet across networks — how routers decide the next hop, how route tables (the
same construct as a VPC route table) work, and how routing itself is attacked and secured. This is
the Layer 3 forwarding that the addressing of Chapters 10–11 feeds into.*
