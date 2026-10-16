# Chapter 10 — IPv4 Addressing, Subnet Masks, CIDR, and Subnetting Without a Calculator

---

## 1. Why This Matters

This chapter teaches the single most-used unit of measurement in cloud security: the **CIDR
block**. Every security group rule, every NACL entry, every firewall rule, every VPC and subnet
definition, every route, and every "allow from this range" decision you will ever make is written
in CIDR notation. If you cannot look at `10.0.0.0/8`, `172.16.0.0/12`, `192.168.1.0/24`, and
`0.0.0.0/0` and *instantly* know what each covers, you will make mistakes that expose systems — and
you will be slow in every review and every incident.

The stakes are concrete and recur constantly:

- `0.0.0.0/0` means **the entire internet**. A security group with `0.0.0.0/0` on port 22 is SSH
  open to the world — one of the most common serious findings in existence (Chapter 76). You must
  see that CIDR and feel alarm.
- `10.0.0.0/16` versus `10.0.0.0/24` differ by a factor of 256 in how many addresses they allow.
  Confusing them means allowing 65,536 hosts when you meant 256 — or blocking legitimate traffic.
- Designing a VPC (Chapter 75) *is* subnetting: carving a block into subnets for public, private,
  and data tiers. Get the arithmetic wrong and subnets overlap, routing breaks, or you run out of
  addresses mid-deployment.
- Reading logs and doing incident response means recognizing which addresses are private
  (RFC 1918), which are public, which are the metadata service (`169.254.169.254`), and which are
  loopback — instantly, without looking anything up.

The goal of this chapter is *fluency*, not just understanding. By the end you should subnet in your
head using the binary place-values from Chapter 7 (`128 64 32 16 8 4 2 1`), read any CIDR block on
sight, and never reach for a subnet calculator in a meeting again. This is a skill that pays off
every single day of a cloud security career, and it rests entirely on the binary fluency you built
in Chapter 7.

---

## 2. Prerequisites

- **Chapter 7 is essential** — binary/decimal conversion, the place values `128 64 32 16 8 4 2 1`,
  and the eight legal subnet-mask octets (128,192,224,240,248,252,254,255). We use them constantly.
- Chapter 8 §5 (the subnet mask decides "local or remote," triggering ARP) and Chapter 9 (ARP
  resolves the local addresses this chapter defines).
- Chapter 4 (the map — IP addressing is Layer 3, Stop 2).

---

## 3. Mental Model

**An IPv4 address is 32 bits, split by the subnet mask into a *network* part (which network you are
on) and a *host* part (which host on it). The mask says where the split falls. CIDR notation writes
the split as a number: `/24` means "the first 24 bits are network, the last 8 are host."**

```
   IP address:    10 . 0 . 1 . 11    = 00001010 00000000 00000001 00001011   (32 bits)
   Mask /24:      255.255.255. 0     = 11111111 11111111 11111111 00000000
                                        |___________ network ___|__ host __|
                                        network = 10.0.1  (first 24 bits)
                                        host    = .11      (last 8 bits)
```

Two ideas do all the work:

1. **The mask is a run of 1s (network) followed by 0s (host).** The number of 1s is the CIDR prefix
   length (`/n`). This is *why* only eight octet values are legal (Chapter 7 §4.1) — a mask octet is
   always some leading 1s. There are no gaps.
2. **All hosts with the same network bits are "on the same network"** and can reach each other
   directly at Layer 2 (Chapter 8 §5); anything with different network bits is "remote" and must go
   through a router. The mask is literally how a host decides local-vs-remote — the decision that
   triggered ARP in Chapter 8.

**The single most useful mental shortcut:** *the prefix length tells you the size.* More network
bits (bigger `/n`) = fewer host bits = smaller network. Each bit doubles or halves:

```
   host bits = 32 - prefix
   addresses = 2^(host bits)

   /24 -> 8 host bits -> 256 addresses    (a "class C"-sized subnet, the everyday default)
   /16 -> 16 host bits -> 65,536 addresses
   /8  -> 24 host bits -> 16,777,216 addresses
   /32 -> 0 host bits -> 1 address        (a single host — used in firewall rules a lot)
   /0  -> 32 host bits -> everything      (0.0.0.0/0 = the entire internet)
```

Memorize the anchors: **`/24` = 256, `/16` = 65,536, `/8` = 16.7M, `/32` = one host, `/0` =
everything.** From those, every other prefix is a doubling/halving away. This table is the core of
the chapter and the thing you will use daily.

---

## 4. Fundamentals

### 4.1 The IPv4 address

32 bits, written as four **octets** (bytes, Chapter 7 §4.3) in dotted decimal, each 0–255:

```
   10.0.1.11  =  00001010.00000000.00000001.00001011
   |  |  |  |
   each is one byte (0-255); the dots are just human formatting
```

The total space is 2^32 ≈ 4.3 billion addresses — famously exhausted, which drove NAT (Chapter 14),
CIDR itself, and IPv6 (Chapter 11).

### 4.2 The subnet mask and CIDR notation

The **subnet mask** marks which bits are network (1) and which are host (0). Two equivalent
notations:

```
   Dotted decimal mask:  255.255.255.0
   CIDR prefix:          /24
   (both mean "24 network bits, 8 host bits")
```

CIDR (**Classless Inter-Domain Routing**) replaced the old rigid "classes" (A/B/C) with an
arbitrary split point, so networks can be any power-of-two size. This is why you write `/24`, `/20`,
`/26` freely. The old classes are worth knowing only as historical vocabulary:

```
   Class A: /8   (e.g. 10.0.0.0/8)      Class B: /16    Class C: /24
   -- obsolete as an allocation scheme; CIDR lets you use any prefix.
```

Converting between mask and prefix uses Chapter 7's eight legal octets. A `/26` mask:

```
   /26 = 26 ones = 11111111.11111111.11111111.11000000 = 255.255.255.192
                                              |___|
                                              11000000 = 192 (Chapter 7: /2 within an octet)
```

The pattern: full octets of 255 for each group of 8 network bits, then one "partial" octet from the
legal-octet table for the remainder. `/26` = three 255s + `192` (2 bits) = `255.255.255.192`.

### 4.3 Network address, broadcast address, and usable hosts

Within any subnet, two addresses are reserved:

```
   Subnet: 10.0.1.0/24
     Network address:   10.0.1.0    (all host bits 0 — names the network itself; not assignable)
     Broadcast address: 10.0.1.255  (all host bits 1 — reaches all hosts; not assignable)
     Usable hosts:      10.0.1.1 - 10.0.1.254  (256 - 2 = 254 usable)
```

So **usable hosts = 2^(host bits) − 2** (subtract network and broadcast). For `/24`: 254. For `/30`:
2^2 − 2 = 2 usable (the classic point-to-point link size). For `/31`: a special case (RFC 3021)
using both addresses for point-to-point links. For `/32`: a single host, no network/broadcast
subtraction — used constantly in firewall rules to mean "exactly this one IP."

**Cloud caveat that catches everyone:** AWS reserves **five** addresses in every subnet (the
network address, the VPC router, DNS, a future-use address, and the broadcast address), so a `/24`
in AWS has 251 usable, not 254 (Chapter 75). Know this before you size subnets tightly.

### 4.4 Finding the network of any address (the core skill)

Given an address and a prefix, "what network is it on?" is the question you answer constantly (it is
how you tell whether two addresses can talk directly, and whether a firewall rule matches). The
method, done in your head with Chapter 7:

**For prefixes on octet boundaries (/8, /16, /24) it is trivial** — just keep that many octets:

```
   10.0.1.11 /24  -> network 10.0.1.0    (keep 3 octets, zero the last)
   10.0.1.11 /16  -> network 10.0.0.0    (keep 2 octets)
   172.16.34.9 /12 -> ... /12 is NOT on a boundary -> see below
```

**For prefixes inside an octet (/25–/31, /17–/23, etc.), work in the "interesting octet":** the one
where the mask is partial. The trick using the legal-octet table:

```
   Question: what network is 10.0.1.201 on, with a /26 ?
   /26 -> mask 255.255.255.192 -> interesting octet is the 4th, mask value 192.
   Block size in that octet = 256 - 192 = 64.
   The subnets step by 64:  .0, .64, .128, .192
   201 falls in the .192 block (192 <= 201 < 256).
   -> network = 10.0.1.192/26, broadcast = 10.0.1.255, usable .193-.254
```

The **block size = 256 − (mask value of the interesting octet)** is the single trick that makes
subnetting mental. `/26`→192→block 64; `/27`→224→block 32; `/28`→240→block 16; `/25`→128→block 128.
The subnets start at multiples of the block size, and any address falls into the block it rounds
down to. Practice this until it is automatic (Lab 10.1) — it is *the* subnetting skill.

### 4.5 Special and reserved address ranges (know these on sight)

These appear in every log, every rule, every incident. Memorize them:

| Range | CIDR | Meaning | Security relevance |
|---|---|---|---|
| Loopback | `127.0.0.0/8` | the host itself | `127.0.0.1` — loopback binds (Chapter 3 §7) |
| Private (A) | `10.0.0.0/8` | RFC 1918 private | not routable on the internet; VPCs use these |
| Private (B) | `172.16.0.0/12` | RFC 1918 private | 172.16–172.31; note the /12 range! |
| Private (C) | `192.168.0.0/16` | RFC 1918 private | home/office LANs |
| Link-local | `169.254.0.0/16` | auto-config, no DHCP | **`169.254.169.254` = cloud metadata service — SSRF target (Chapters 50, 78)** |
| Multicast | `224.0.0.0/4` | group addressing | routing protocols, discovery |
| "This host" | `0.0.0.0/8` | unspecified/this | `0.0.0.0` bind = all interfaces (Chapter 3); `0.0.0.0/0` = everything |
| Documentation | `192.0.2.0/24` etc. | examples only | used in docs (TEST-NET) |

Three you must never fumble:

- **`0.0.0.0/0`** — the entire internet. In a firewall/SG source, it means "from anywhere." Alarm.
- **`169.254.169.254`** — the instance metadata service in AWS/GCP/Azure. An SSRF that reaches it
  steals cloud credentials (Chapter 50, 78). Seeing your app connect to it (Chapter 2 §6.2's
  execsnoop example) is a red flag.
- **RFC 1918 ranges** — private, non-internet-routable. Recognizing them tells you "this is internal
  traffic," which matters for SSRF defense (block internal ranges — Chapter 50) and for reading
  logs.

### 4.6 Public vs private, and why it matters

**Private addresses (RFC 1918) are not routable on the internet** — routers drop them. So a host
with only a private IP cannot be reached from the internet directly and cannot reach the internet
without NAT (Chapter 14) translating its private source to a public one. This is foundational to
cloud network design:

- **Private subnets** (Chapter 75, 83) hold databases and app servers with only private IPs — they
  are unreachable from the internet *by addressing*, a strong control that composes with security
  groups (Chapter 4 §7's "property provided by multiple layers").
- **Public subnets** hold load balancers/NAT gateways with public IPs (or Elastic IPs) that *are*
  internet-routable.
- The "is it internet-reachable?" question (Chapter 3 §3) has an addressing component: a host with
  no public IP and no NAT path simply cannot be reached from or reach the internet, regardless of
  security groups. Addressing is thus a security boundary in its own right.

---

## 5. Deep Technical Explanation: How the Mask Decides "Local or Remote"

Recall Chapter 8 §5: a host decides whether a destination is local (deliver via ARP/L2) or remote
(send to the gateway) by comparing network bits. Here is exactly how, mechanically:

```
   Host: 10.0.1.11/24     Destination A: 10.0.1.50     Destination B: 10.0.2.50

   The host computes (my IP AND my mask) and (dest IP AND my mask), then compares:

   my network:   10.0.1.11 & 255.255.255.0 = 10.0.1.0
   A network:    10.0.1.50 & 255.255.255.0 = 10.0.1.0   -> SAME -> A is LOCAL -> ARP for A
   B network:    10.0.2.50 & 255.255.255.0 = 10.0.2.0   -> DIFFERENT -> B is REMOTE -> send to gateway
```

The AND operation (Chapter 7 §4.4) zeroes the host bits, leaving the network. If the destination's
network matches the host's, it is local. This is the mechanical link between Chapters 8, 9, and 10:
**the mask (Ch. 10) decides local/remote, which decides whether to ARP for the host or the gateway
(Ch. 8/9), which decides where the frame goes.** All three chapters are one story.

The security consequence: **a firewall rule that allows a source CIDR is doing exactly this AND
comparison.** "Allow from `10.0.1.0/24`" means "allow packets whose source IP, ANDed with
`255.255.255.0`, equals `10.0.1.0`." When you write a security-group rule, you are specifying a
network-bit prefix, and the fabric matches source IPs against it with this masking operation. Getting
the prefix wrong (writing `/16` when you meant `/24`) changes which 256× larger set of sources
matches — the arithmetic *is* the security.

### 5.1 Subnetting: carving a block into smaller ones (VPC design)

Designing a VPC is subnetting a block. Worked example — carve `10.0.0.0/16` (65,536 addresses) into
subnets for a three-tier design across two availability zones:

```
   VPC: 10.0.0.0/16

   Plan: /24 subnets (256 each) — plenty for most tiers, easy to read.
   Block size for /24 in the 3rd octet = 256 - 255 = ... no; /24 steps the 3rd octet by 1.

   AZ-a public:   10.0.0.0/24    (10.0.0.0 - 10.0.0.255)
   AZ-b public:   10.0.1.0/24
   AZ-a private:  10.0.10.0/24   (leave gaps for growth — good practice)
   AZ-b private:  10.0.11.0/24
   AZ-a data:     10.0.20.0/24
   AZ-b data:     10.0.21.0/24
```

Design principles that fall out of the arithmetic:

- **Leave gaps** (jumping from .1 to .10 to .20) so you can add subnets later without renumbering.
- **Do not overlap** — two subnets sharing any address range breaks routing; the arithmetic must be
  clean (each `/24` occupies exactly one value of the 3rd octet).
- **Right-size** — `/24` (251 usable in AWS) suits most tiers; use `/28` (11 usable) for tiny things
  like a NAT or endpoint subnet, `/20` (4091 usable) for large workloads. The prefix is your
  capacity knob.
- **Avoid overlap across VPCs you might peer** (Chapter 77) — if two VPCs use `10.0.0.0/16`, they
  cannot be peered because addresses collide. Plan address space org-wide.

This is Chapter 75's VPC design, and it is *pure subnetting arithmetic* plus the security intent of
which tier goes where. The math you are learning here is the math you will do to design real cloud
networks.

---

## 6. Internals: Tools and Verification

### 6.1 See your addressing

```bash
$ ip -br addr show
lo    UNKNOWN  127.0.0.1/8 ::1/128
eth0  UP       10.0.1.11/24 fe80::.../64

# The /24 tells you the mask; the network is 10.0.1.0/24.
$ ip route
default via 10.0.1.1 dev eth0            # the gateway for REMOTE traffic (Chapter 12)
10.0.1.0/24 dev eth0 proto kernel scope link src 10.0.1.11   # the LOCAL network (no gateway)
```

Read the route table with §5's logic: the `10.0.1.0/24` route (scope link) is "these are local,
deliver directly"; the `default` route (`0.0.0.0/0` via the gateway) is "everything else, send to
the gateway." That is local-vs-remote, encoded as routes (Chapter 12).

### 6.2 CIDR math on the command line (verify your head math)

```bash
# ipcalc is the standard tool:
$ ipcalc 10.0.1.201/26
Address:   10.0.1.201
Netmask:   255.255.255.192 = 26
Network:   10.0.1.192/26
Broadcast: 10.0.1.255
HostMin:   10.0.1.193
HostMax:   10.0.1.254
Hosts/Net: 62

# Python for scripting and checks:
$ python3 -c "import ipaddress; n=ipaddress.ip_network('10.0.1.201/26', strict=False); \
  print(n.network_address, n.broadcast_address, n.num_addresses, list(n.hosts())[0], list(n.hosts())[-1])"
10.0.1.192 10.0.1.255 64 10.0.1.193 10.0.1.254

# Is an IP in a CIDR? (the firewall-match question)
$ python3 -c "import ipaddress; print(ipaddress.ip_address('10.0.1.201') in ipaddress.ip_network('10.0.1.192/26'))"
True
```

Always verify your mental subnetting against `ipcalc` while learning; the goal is to reach the point
where you rarely need to.

### 6.3 Recognize the special ranges in practice

```bash
# Quick classification during log review / IR:
$ python3 - <<'PY'
import ipaddress
for ip in ["10.0.5.7","172.20.1.1","192.168.0.1","169.254.169.254","8.8.8.8","127.0.0.1"]:
    a = ipaddress.ip_address(ip)
    print(f"{ip:18} private={a.is_private} loopback={a.is_loopback} link_local={a.is_link_local} global={a.is_global}")
PY
```

The `169.254.169.254` line — `link_local=True` — is the one to burn in: a request to a link-local
address from your application is almost always either a bug or an SSRF attempt at the metadata
service (Chapters 50, 78).

---

## 7. Real-World Example: The Ledger VPC Address Plan

System B's VPC, designed with this chapter's arithmetic:

```
   VPC: 10.20.0.0/16   (65,536 addresses; chosen NOT to overlap other VPCs for future peering)

   Public subnets (ALB, NAT GW) — need internet routes:
     10.20.0.0/24   (AZ-a)     10.20.1.0/24   (AZ-b)
   Private app subnets (ECS tasks) — no public IP, NAT for egress:
     10.20.10.0/24  (AZ-a)     10.20.11.0/24  (AZ-b)
   Private data subnets (RDS, ElastiCache) — no internet route at all:
     10.20.20.0/24  (AZ-a)     10.20.21.0/24  (AZ-b)
```

Now read the security properties directly off the addressing:

- **Data subnets have no route to an internet gateway** (Chapter 12), so RDS in `10.20.20.0/24` is
  unreachable from and cannot reach the internet *by addressing* — the strongest form of "not
  internet-reachable," composing with the security group and the private IP (Chapter 4 §7, multiple
  layers providing one property).
- **Security group rules are written in CIDR:** "allow 5432 from `10.20.10.0/24` and
  `10.20.11.0/24`" (the app subnets) — or better, from the app *security group* (Chapter 76). You can
  now read exactly which sources those CIDRs permit.
- **A finding you can spot instantly:** an SG rule `allow 5432 from 0.0.0.0/0` on the data subnet
  means the database accepts connections from the entire internet — catastrophic, and obvious the
  moment you read the CIDR. Or `allow 22 from 0.0.0.0/0` (SSH from anywhere). The CIDR fluency is
  what makes these leap out.
- **Metadata SSRF context:** an app in `10.20.10.0/24` reaching `169.254.169.254` is the SSRF→
  credential-theft path; egress rules and IMDSv2 (Chapter 78) defend it, and recognizing the
  link-local address is step one of detection.

The addressing plan *is* the first layer of the network security design. Chapters 75–76 add the
route tables and security groups on top, but the CIDR arithmetic here is the foundation — and it is
the same arithmetic whether you are on AWS, Azure, GCP, or on-prem.

---

## 8. Hands-On Demonstration

### LAB 10.1 — Subnetting Fluency and a VPC Address Plan

**Objective.** Build automatic subnetting fluency (network/broadcast/usable, in-your-head), design a
non-overlapping multi-tier address plan, and verify firewall-style CIDR matching — the exact skills
used to design and audit cloud networks.

**Cost.** Free. **Environment.** ENV-1. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Prefix→size anchors (memorize, then drill).*

```bash
# Fill in from memory, then verify:
python3 - <<'PY'
for p in [8,16,24,25,26,27,28,30,32,0]:
    hosts = 2**(32-p)
    usable = max(hosts-2,0) if p<31 else (hosts if p==31 else 1)
    print(f"/{p:<2} -> {hosts:>10} addresses, ~{usable} usable (RFC1918/AWS caveats aside)")
PY
```

Confirm you can recite: /24→256, /16→65536, /8→16.7M, /26→64, /28→16, /30→4, /32→1, /0→everything.

*Step 2 — The block-size subnetting trick (do by hand first).*

For each, compute network, broadcast, and usable range **in your head** using block size =
256 − (interesting-octet mask), then verify:

```bash
for cidr in 10.0.1.201/26 172.16.34.9/20 192.168.5.130/25 10.0.0.77/28; do
  echo "== $cidr =="; ipcalc $cidr 2>/dev/null | grep -E 'Network|Broadcast|HostMin|HostMax|Hosts'
done
```

Work `10.0.1.201/26`: mask 192, block 64, blocks .0/.64/.128/.192, 201→.192 block → network
10.0.1.192, broadcast 10.0.1.255, usable .193–.254. Then check against `ipcalc`. Repeat until you do
not need `ipcalc`.

*Step 3 — Design a non-overlapping plan.*

Carve `10.30.0.0/16` into: 2 public /24, 2 private-app /24, 2 private-data /24, and one /28 for
endpoints — across two AZs, with growth gaps. Write it out, then validate no overlaps:

```bash
python3 - <<'PY'
import ipaddress
subnets = ["10.30.0.0/24","10.30.1.0/24","10.30.10.0/24","10.30.11.0/24",
           "10.30.20.0/24","10.30.21.0/24","10.30.30.0/28"]
nets = [ipaddress.ip_network(s) for s in subnets]
for i in range(len(nets)):
    for j in range(i+1,len(nets)):
        if nets[i].overlaps(nets[j]): print("OVERLAP!", nets[i], nets[j])
print("all within VPC:", all(n.subnet_of(ipaddress.ip_network("10.30.0.0/16")) for n in nets))
print("no overlaps found" )
PY
```

*Step 4 — Firewall-match reasoning (the SG rule question).*

```bash
python3 - <<'PY'
import ipaddress
rule = ipaddress.ip_network("10.30.10.0/24")   # "allow from the app subnet"
for src in ["10.30.10.55","10.30.11.55","10.30.10.255","10.0.0.1","0.0.0.0"]:
    print(f"{src:14} matches {rule}: {ipaddress.ip_address(src) in rule}")
PY
```

Predict each result before running (which sources does "allow from 10.30.10.0/24" permit?), then
verify. This is exactly the reasoning you apply when auditing a security group.

*Step 5 — Spot the findings.*

Given these SG source CIDRs on the data-tier port 5432, mark each safe/finding and why:
`10.30.10.0/24`, `10.30.0.0/16`, `0.0.0.0/0`, `10.30.10.55/32`, `172.16.0.0/12`.

**Expected reasoning:** `/24` app subnet = intended (safe); `/16` whole VPC = too broad (finding —
includes public subnets); `0.0.0.0/0` = entire internet to the database (critical finding);
`/32` single host = tightest (safe, but check it is the right host); `172.16.0.0/12` = a private
range not even in this VPC (finding — misconfiguration, matches nothing here or an unintended
network).

**Security implications.** Write down: (a) how prefix length maps to blast radius (more hosts
allowed = larger radius); (b) why `0.0.0.0/0` on a sensitive port is critical; (c) how addressing
(private subnet, no internet route) provides "not internet-reachable" independent of the SG.

**Cleanup.** None.

---

## 9. Security Implications

- **CIDR is the unit of network access control.** Every SG/NACL/firewall rule specifies a source or
  destination as a prefix; the prefix length is the blast radius of who is allowed.
- **`0.0.0.0/0` = the entire internet** — the highest-signal CIDR to recognize; on a sensitive
  source it is a critical finding.
- **Prefix length is a security knob:** `/32` = exactly one host (tightest); wider prefixes allow
  exponentially more. Writing `/16` for `/24` allows 256× more sources.
- **Private ranges (RFC 1918) and no-internet-route addressing are security boundaries** — a host
  with only a private IP and no NAT/IGW path is unreachable from the internet by addressing, a
  strong control that composes with SGs.
- **`169.254.169.254` (link-local) is the metadata service** — recognizing it is central to SSRF
  detection and defense (Chapters 50, 78).
- **Subnetting design is security design:** which tier lives in which subnet, and whether that
  subnet has an internet route, is a foundational access-control decision (Chapters 75, 83).

---

## 10. Attack Scenarios

1. **`0.0.0.0/0` on a sensitive port** (SSH 22, RDP 3389, database 5432/3306, Redis 6379): the
   database/host exposed to the entire internet — mass-scanned and exploited within minutes
   (Chapter 5 §10, Chapter 76). The single most common cloud misconfiguration.
2. **Overly broad source CIDR**: allowing `/8` or `/16` when a `/24` or `/32` was meant, permitting
   far more sources than intended — a subtler finding that CIDR fluency catches.
3. **Overlapping/misplanned address space**: subnets or VPCs overlapping, breaking routing or (worse)
   causing a firewall rule to match unintended networks.
4. **SSRF to `169.254.169.254`**: an app tricked into requesting the metadata service, stealing
   cloud credentials (Chapters 50, 78) — recognizing the link-local target is detection step one.
5. **Private-range confusion in SSRF defense**: a blocklist that forgets `172.16.0.0/12` (an easy
   range to mis-specify — it is /12, not /16) leaving internal targets reachable.
6. **Public IP on a resource that should be private**: an RDS/EC2 with a public IP and a permissive
   SG, bypassing the intended private-subnet isolation.

---

## 11. Defensive Techniques

- **Write the tightest prefix that works.** Prefer `/32` (single host) or a specific subnet CIDR
  over broad ranges; in AWS prefer **security-group references** over CIDRs entirely (Chapter 76) —
  "from the app SG" is tighter and self-updating than "from 10.x.x.x/24."
- **Never `0.0.0.0/0` on management/data ports.** SSH/RDP via a bastion or SSM (Chapter 78);
  databases only from the app tier. Enforce with policy-as-code (Chapter 91) and Config rules
  (Chapter 82).
- **Use private subnets with no internet route for data and internal app tiers** — addressing as a
  boundary (§4.6, §7), composing with SGs.
- **Plan address space org-wide** to avoid overlap (peering/Transit Gateway need non-overlapping
  CIDRs — Chapter 77); leave growth gaps; document the plan.
- **Block RFC 1918 + link-local in SSRF defenses**, getting every range right (especially
  `172.16.0.0/12` and `169.254.0.0/16`), and prefer allow-lists on the resolved IP (Chapter 50).
- **Audit CIDRs continuously** — a scanner/Config rule that flags `0.0.0.0/0` on sensitive ports and
  overly broad sources (Chapter 82). Your own fluency plus automation.

---

## 12. Production Architecture

Addressing decisions and where they enforce security, VPS vs cloud:

```
 CONCEPT                 SYSTEM A (VPS)              SYSTEM B (AWS VPC)
 ---------------------   -------------------------   ------------------------------------
 address space           provider-assigned          you choose (10.x/16 etc.), plan for peering
 private vs public       one public IP + loopback    public subnets (IGW) vs private (NAT/none)
 "not internet-reachable" loopback bind (Ch.3)        private subnet + no IGW route + SG
 access control unit     iptables CIDR rules          security group / NACL CIDRs (or SG refs)
 metadata risk           n/a (usually)               169.254.169.254 — IMDSv2 + egress control
 segmentation            subnets/VLANs (if any)       subnets per tier + route tables + SGs
```

The architectural principle carried forward: **addressing is the first layer of network security,
and it composes with the others.** "The database is not internet-reachable" is provided by *three*
things in System B — a private IP, a subnet with no internet route, and a security group — any of
which alone helps and all of which together are defense in depth (Chapter 4 §7). Design the address
plan first (this chapter), then routes (Chapter 12/75), then security groups (Chapter 76); each
layer references the CIDR arithmetic you learned here.

---

## 13. Common Mistakes

1. **`0.0.0.0/0` on sensitive ports** — the classic critical exposure.
2. **Confusing prefix lengths** — `/16` vs `/24` (256× difference); `/12` for the 172 range (not
   `/16`).
3. **Overlapping subnets/VPCs**, breaking routing or peering (Chapter 77).
4. **Sizing subnets too tightly** and forgetting AWS reserves 5 addresses per subnet (a `/28` has
   only 11 usable).
5. **Using broad CIDRs where a specific host or SG reference belongs** — larger blast radius than
   intended.
6. **Forgetting a private range in SSRF blocklists** (especially `172.16.0.0/12`, link-local).
7. **Giving resources public IPs** that should be private, bypassing subnet isolation.
8. **No org-wide address plan**, causing overlaps that block future peering.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Two hosts can't talk despite "same subnet" | mismatched masks (one thinks the other is remote) | compare `/prefix` on both (`ip addr`); apply §5 AND test |
| SG rule allows more/less than expected | wrong prefix length | check the CIDR; `ipcalc`/python `in` test |
| Ran out of IPs mid-deployment | subnet too small / AWS 5-reserved | recount usable (2^host−2, minus AWS reserves) |
| Peering fails | overlapping VPC CIDRs | compare VPC CIDRs; they must not overlap (Chapter 77) |
| App connecting to 169.254.169.254 | SSRF or SDK metadata call | distinguish legitimate SDK use from SSRF (Chapter 50, 78) |
| Traffic to internet fails from a subnet | no IGW/NAT route (private subnet) | check route table; is this subnet meant to be private? (Chapter 12) |
| Firewall rule "matches nothing" | CIDR not in the actual address space | verify the range is correct and present (§8 Step 5) |

---

## 15. Practical Lab

Lab 10.1 is in §8. Register it in the lab index. Extension: take a real (or realistic) VPC layout
and audit every security-group source CIDR, classifying each as tight/appropriate/too-broad/critical
using only your head (verify with python `in`). Produce a findings list — this is a genuine cloud
security review deliverable and the direct application of this chapter.

---

## 16. Exercises

### Concept questions

**10.1** Explain how a subnet mask splits an address into network and host parts, and how the CIDR
prefix expresses this. Why are only eight octet values legal in a mask?

**10.2** Give the number of addresses and usable hosts for /24, /26, /28, /30, /32, and /16 from
memory, and explain the −2 (and where it does not apply).

**10.3** Explain the "block size = 256 − mask value" trick and use it to find the network and
broadcast of `172.16.200.50/22` by hand.

**10.4** What does `0.0.0.0/0` mean as a firewall source, and why is it a critical finding on a
database port? What does `/32` mean?

**10.5** Explain how the subnet mask decides "local vs remote" (the AND comparison) and how that
connects to ARP (Chapter 8/9) and to a firewall CIDR match.

### Debugging problems

**10.6** Two servers, `10.0.1.10/24` and `10.0.2.20/24`, cannot reach each other, but both reach the
internet. Explain why (they are on different networks) and what is needed for them to communicate.

**10.7** A host `10.0.1.10/25` cannot reach `10.0.1.200` on the "same" subnet. Explain using the
mask why they are actually on different networks, and give the two network ranges.

**10.8** A `/28` subnet in AWS was sized for 14 hosts but a deployment of 12 instances fails with
"insufficient addresses." Explain.

### Security scenarios

**10.9** Audit these SG rules on a database tier and classify each (safe/finding/critical) with
justification: source `10.0.10.0/24` port 5432; source `0.0.0.0/0` port 5432; source `10.0.0.0/8`
port 5432; source `sg-app` (SG reference) port 5432; source `169.254.0.0/16` port 5432.

**10.10** You are writing SSRF protection. List every CIDR you must block to prevent reaching
internal and metadata targets, and explain the one range engineers most often get wrong.

### Architecture questions

**10.11** Design an address plan for a VPC that will host three environments (dev/staging/prod), each
three-tier, across two AZs, that will later peer with a shared-services VPC. State your CIDR choices
and justify the non-overlap and growth decisions.

**10.12** Explain how addressing (public vs private, internet route vs none) provides the "not
internet-reachable" property, and how it composes with security groups as defense in depth.

### Hands-on exercises

**10.13** By hand, for `192.168.10.100/26`: give network, broadcast, usable range, and how many
usable hosts. Verify with `ipcalc`.

**10.14** Write a script that takes a list of subnet CIDRs and reports any overlaps and whether all
fit within a given VPC CIDR (the validation from Lab 10.1 Step 3).

**10.15** Write a one-liner that, given an IP and a security-group source CIDR, answers whether the
rule allows that IP — the firewall-match question.

### Interview questions

**10.16** "What does `10.0.0.0/16` cover, and how many usable hosts? Do it in your head."

**10.17** "I see a security group allowing `0.0.0.0/0` on port 22. Walk me through why that's a
problem and what you'd do."

**10.18** "How do you subnet a `/16` into subnets for a three-tier, two-AZ VPC? Walk me through the
math and the design choices."

**10.19** "What is `169.254.169.254`, why does it matter for security, and how do you protect it?"

**10.20** "Explain how a host decides whether to send a packet to the gateway or directly to a
peer."

---

## 17. Summary

- An **IPv4 address is 32 bits**, split by the **subnet mask** into network and host parts; **CIDR
  notation** (`/n`) writes the number of network bits. The mask is always leading 1s then 0s — the
  reason only eight octet values are legal (Chapter 7).
- **Prefix length ↔ size**: host bits = 32 − prefix, addresses = 2^(host bits). Anchors to memorize:
  **/24 = 256, /16 = 65,536, /8 = 16.7M, /32 = one host, /0 = the entire internet.** Usable hosts =
  2^(host bits) − 2 (AWS reserves 5 per subnet).
- **Subnetting in your head:** block size = 256 − (interesting-octet mask value); subnets start at
  multiples of the block size; any address rounds down into its block.
- **The mask decides local vs remote** via the AND comparison — the mechanical trigger for ARP
  (Chapters 8–9) and the exact operation a firewall CIDR match performs.
- **CIDR is the unit of network access control.** The prefix length is the blast radius; `0.0.0.0/0`
  = the internet (critical on sensitive ports); `/32` = one host (tightest); prefer SG references
  over CIDRs in AWS.
- **Know the special ranges on sight:** RFC 1918 private (`10/8`, `172.16/12`, `192.168/16`),
  loopback (`127/8`), link-local (`169.254/16`, containing the **metadata service
  `169.254.169.254`**), and `0.0.0.0/0`.
- **Addressing is the first layer of network security**: private IPs + no internet route make a host
  unreachable from the internet by addressing, composing with security groups as defense in depth.
  **Subnetting design is security design** (Chapters 75, 83).

---

## 18. Knowledge Check

1. How many usable hosts in a /24? A /26? A /30? (§3, §4.3)
2. What does `0.0.0.0/0` mean, and `/32`? (§3, §4.5)
3. Find the network and broadcast of `10.0.1.201/26` in your head. (§4.4)
4. What are the three RFC 1918 ranges (with correct prefixes)? (§4.5)
5. What is `169.254.169.254` and why does it matter? (§4.5)
6. How does the mask decide local vs remote? (§5)
7. Why can't two VPCs with overlapping CIDRs be peered? (§5.1)
8. How many addresses does AWS reserve per subnet? (§4.3)
9. What is the block-size subnetting trick? (§4.4)
10. Which CIDR on a database port is a critical finding, and why? (§9)

---

## 19. Further Exploration

- Drill subnetting daily for a week with `ipcalc` as the checker until you no longer need it; use
  subnettingpractice.com or generate random CIDRs and compute by hand.
- Read RFC 1918 (private ranges) and RFC 4632 (CIDR) — short and foundational.
- `man ipcalc`; and `python3 -c "help('ipaddress')"` — the `ipaddress` module is invaluable for
  scripting CIDR audits.
- Audit a real cloud environment's security groups (or a Terraform plan) for `0.0.0.0/0` and overly
  broad sources — the direct professional application.
- Preview Chapter 75 (VPC) and Chapter 76 (security groups/NACLs): you will implement the address
  plan and rules you designed here.

---

## Solutions

### 10.1
A subnet mask is 32 bits: a contiguous run of 1s marking the network portion, followed by 0s marking
the host portion. A bitwise AND of an address with the mask yields the network address (host bits
zeroed). CIDR notation `/n` states the number of leading 1s (network bits); the host bits are
32 − n. Only eight octet values are legal in a mask because within any octet the mask is still a run
of 1s then 0s (no gaps allowed), giving exactly 10000000=128, 11000000=192, 11100000=224,
11110000=240, 11111000=248, 11111100=252, 11111110=254, 11111111=255 (plus 0 for an all-host octet).
A value like 255.255.255.**160** (10100000) is illegal because the 1s are not contiguous.

### 10.2
/24 → 2^8 = 256 addresses, 254 usable. /26 → 2^6 = 64, 62 usable. /28 → 2^4 = 16, 14 usable.
/30 → 2^2 = 4, 2 usable. /32 → 1 address, 1 usable (a single host — no network/broadcast
subtraction). /16 → 2^16 = 65,536, 65,534 usable. The −2 subtracts the network address (all host
bits 0, naming the network) and the broadcast address (all host bits 1, reaching all hosts), neither
of which is assignable to a host. It does not apply to /32 (a single host, used in firewall rules)
and is special for /31 (RFC 3021 uses both addresses for point-to-point links). AWS additionally
reserves 5 per subnet, so subtract 5, not 2, in a VPC.

### 10.3
The trick: in the "interesting octet" (where the mask is partial), block size = 256 − (mask value
of that octet); subnets start at multiples of the block size, and any address falls into the block
it rounds down to. For `172.16.200.50/22`: /22 = 255.255.252.0, so the interesting octet is the 3rd,
mask value 252, block size = 256 − 252 = 4. The 3rd octet steps by 4: …196, 200, 204… 200 falls in
the .200 block (200 ≤ 200 < 204). So network = 172.16.200.0/22, and the block spans 3rd octet
200–203, giving broadcast = 172.16.203.255, usable 172.16.200.1–172.16.203.254 (1022 usable). The
key was recognizing /22 is a 3rd-octet mask with block size 4.

### 10.4
`0.0.0.0/0` matches *every* IPv4 address — the entire internet — because it has zero network bits,
so the AND comparison always matches. As a firewall/SG source it means "allow from anywhere on the
internet." On a database port (5432/3306/etc.) it is critical because it exposes the database to the
entire internet: automated scanners find it within minutes and attempt exploitation (default creds,
known CVEs, brute force), and any authentication weakness becomes a full breach (Chapter 5 §10).
`/32` means exactly one host (32 network bits, 0 host bits), so it is the tightest possible source —
"allow only this single IP" — used for bastion hosts, specific peers, and precise rules.

### 10.5
A host decides local vs remote by comparing network bits: it computes (its own IP AND its mask) and
(destination IP AND its mask); if the two network addresses are equal, the destination is on the
same network (local) and the host delivers directly via L2, using ARP to get the destination's MAC
(Chapters 8–9); if they differ, the destination is remote and the host sends the frame to the
default gateway's MAC (ARPing for the gateway instead). Example: 10.0.1.11/24 to 10.0.1.50 → both
AND 255.255.255.0 = 10.0.1.0 → local → ARP for 10.0.1.50. To 10.0.2.50 → 10.0.2.0 ≠ 10.0.1.0 →
remote → send to gateway. A firewall CIDR match performs the identical operation: "allow from
10.0.1.0/24" means "allow packets whose source IP AND 255.255.255.0 equals 10.0.1.0." So the same
masking arithmetic underlies local/remote delivery, ARP triggering, and access-control matching —
Chapters 8, 9, and 10 are one mechanism.

### 10.6
They cannot reach each other directly because they are on **different networks**: 10.0.1.10/24 is on
network 10.0.1.0/24 and 10.0.2.20/24 is on network 10.0.2.0/24; the mask AND yields different
network addresses, so each considers the other *remote* (§5). Being remote, each sends traffic for
the other to its default gateway. They both reach the internet because the gateway routes their
traffic outward; but for them to reach *each other*, a **router** (or L3 device) must connect the two
networks and route between them — in a VPC, that is the VPC router with route table entries for both
subnets (Chapters 12, 75), and security groups/NACLs must permit the traffic. So the fix is a routing
path between the two networks plus permissive firewall rules; it is not an addressing bug — different
subnets *should* require routing.

### 10.7
With /25, the mask is 255.255.255.128, so the interesting (4th) octet has block size 256 − 128 =
128, giving two networks: 10.0.1.0/25 (hosts .1–.126, broadcast .127) and 10.0.1.128/25 (hosts
.129–.254, broadcast .255). The host 10.0.1.10 is in the **first** network (10.0.1.0/25), while
10.0.1.200 is in the **second** (10.0.1.128/25, since 200 ≥ 128). So although both share the first
three octets and "look" like the same /24, under a /25 mask they are on *different* networks —
10.0.1.10 considers 10.0.1.200 remote and sends it to the gateway; if there is no route between the
two /25s (or the SG blocks it), they cannot communicate. The lesson: the mask, not the visual
similarity of the address, determines the network — a /25 splits a /24 into two.

### 10.8
AWS reserves **5 addresses in every subnet** (the network address, the VPC router at .1, the DNS
address at .2, a reserved-for-future .3, and the broadcast address), not the usual 2. A /28 has 16
addresses; subtracting AWS's 5 leaves **11 usable**, not 14. A deployment of 12 instances therefore
cannot fit — it needs 12 addresses but only 11 are available (and ENIs/other resources may consume
more). Fix: size the subnet larger (a /27 = 32 addresses, 27 usable) or reduce the instance count.
The general lesson: in AWS, usable = 2^(host bits) − 5, so size subnets with that overhead in mind,
especially for small prefixes where the fixed 5-address reservation is a large fraction.

### 10.9
Source `10.0.10.0/24` on 5432: **safe/appropriate** if that is the app tier subnet — 256 specific
internal sources, matching the intended "app can reach DB." Source `0.0.0.0/0` on 5432:
**critical** — the database is open to the entire internet; remediate immediately. Source
`10.0.0.0/8` on 5432: **finding (too broad)** — allows all of the 10.x private space (16.7M
addresses), far more than the app tier; it likely includes other subnets/tiers and violates least
privilege; tighten to the app subnet or SG reference. Source `sg-app` (security-group reference) on
5432: **safest** — allows only instances in the app's security group, self-updating and independent
of IP ranges; this is the preferred form (Chapter 76). Source `169.254.0.0/16` on 5432:
**finding (nonsensical/misconfiguration)** — link-local addresses are not valid connection sources
for this; the rule matches nothing legitimate and indicates confusion (possibly an attempt to
reference the metadata range); remove it. Priority: fix `0.0.0.0/0` first, then narrow `10.0.0.0/8`,
prefer the SG reference, and remove the bogus link-local rule.

### 10.10
Block (deny egress to): all RFC 1918 private ranges — **`10.0.0.0/8`**, **`172.16.0.0/12`**,
**`192.168.0.0/16`**; **`169.254.0.0/16`** (link-local, containing the metadata service
`169.254.169.254` — the highest-value target); **`127.0.0.0/8`** (loopback, to prevent
`localhost`/`127.x` tricks); `0.0.0.0/8` ("this host"/unspecified); and IPv6 equivalents
(`::1/128`, `fc00::/7` unique-local, `fe80::/10` link-local, and `::ffff:0:0/96`
IPv4-mapped). The range engineers most often get wrong is **`172.16.0.0/12`**: it is a **/12**
(covering 172.16.0.0–172.31.255.255), not a /16, so a blocklist that writes `172.16.0.0/16` (or only
blocks `172.16.x`) leaves 172.17–172.31 reachable — a common gap. The stronger approach is not to
blocklist at all but to **allow-list the resolved destination IP** and re-resolve at connection time
to defeat DNS rebinding (Chapter 50), because blocklists inevitably miss an encoding or range.

### 10.11
Plan: use a distinct large block per environment from a well-separated space, each internally
three-tier × two-AZ, all non-overlapping with each other and with the shared-services VPC. Example:
prod `10.0.0.0/16`, staging `10.1.0.0/16`, dev `10.2.0.0/16`, shared-services `10.10.0.0/16` (gaps
left for more environments). Within each /16, carve /24 subnets with growth gaps: public
`.0.0/24`,`.1.0/24`; app `.10.0/24`,`.11.0/24`; data `.20.0/24`,`.21.0/24` (per AZ). Justification:
each environment in its own /16 gives clean isolation, easy route/SG rules per environment, and room
for ~250 /24 subnets each; the /16s do not overlap, so all can peer with the shared-services VPC (a
hub) without address collisions (Chapter 77 requires non-overlapping CIDRs for peering/TGW); growth
gaps (jumping .0→.10→.20) allow adding subnets without renumbering; and keeping environments in
separate /16s (rather than sharing one) supports separate accounts and blast-radius isolation
(Chapter 74). Document the allocation centrally so future VPCs do not collide.

### 10.12
Addressing provides "not internet-reachable" in two ways: (1) a resource with **only a private IP**
(RFC 1918) has no internet-routable address — internet routers drop RFC 1918, so nothing on the
internet can address it; and (2) placing it in a **subnet whose route table has no route to an
internet gateway** means even outbound-initiated paths (and thus return paths) to the internet do
not exist — the packets have nowhere to go (Chapter 12). Together, a private IP + a private subnet
(no IGW route) make the resource unreachable from and to the internet *by addressing and routing
alone*, before any firewall is consulted. This composes with **security groups** as defense in depth
(Chapter 4 §7): even if someone later adds a route or a public IP by mistake, the SG still restricts
sources; and even if the SG is misconfigured, the lack of a public IP/route still blocks internet
reachability. Three independent layers (private IP, no route, restrictive SG) each provide the
property, so no single mistake exposes the resource — which is exactly why data tiers live in private
subnets with tight SGs.

### 10.13
`192.168.10.100/26`: /26 mask = 255.255.255.192, interesting octet = 4th, block size = 256 − 192 =
64; blocks are .0/.64/.128/.192; 100 falls in the .64 block (64 ≤ 100 < 128). So **network =
192.168.10.64/26**, **broadcast = 192.168.10.127**, **usable range = 192.168.10.65 –
192.168.10.126**, **62 usable hosts** (2^6 − 2). Verify: `ipcalc 192.168.10.100/26` should report
Network 192.168.10.64/26, Broadcast 192.168.10.127, HostMin .65, HostMax .126, Hosts/Net 62.

### 10.14
Expected shape (Python `ipaddress`): take a VPC CIDR and a list of subnet CIDRs; check each subnet is
`subnet_of` the VPC, and check every pair for `.overlaps()`:
```python
import ipaddress, sys
vpc = ipaddress.ip_network(sys.argv[1])
subs = [ipaddress.ip_network(s) for s in sys.argv[2:]]
for s in subs:
    if not s.subnet_of(vpc): print(f"OUTSIDE VPC: {s}")
for i in range(len(subs)):
    for j in range(i+1, len(subs)):
        if subs[i].overlaps(subs[j]): print(f"OVERLAP: {subs[i]} <-> {subs[j]}")
```
Refinements: report usable-host counts (accounting for AWS's 5 reserved), flag subnets that are
suspiciously large/small for their role, and integrate into CI to validate Terraform-planned CIDRs
before apply (Chapter 91). The tool encodes the two rules of a valid plan: everything inside the VPC,
nothing overlapping.

### 10.15
`python3 -c "import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network(sys.argv[2]))" 10.0.10.55 10.0.10.0/24`
→ `True`. This answers the firewall-match question: does the rule with source CIDR (arg 2) allow the
IP (arg 1)? `in` performs the mask-AND comparison (§5) internally. Examples:
`... 10.0.11.55 10.0.10.0/24` → False (different /24); `... 8.8.8.8 0.0.0.0/0` → True (everything
matches the internet CIDR); `... 10.0.10.55 10.0.10.55/32` → True (exact host). This one-liner is
the essence of auditing whether a given source is permitted by a given rule.

### 10.16
`10.0.0.0/16` covers 10.0.0.0 through 10.0.255.255 — the entire 10.0.x.x range — which is 2^16 =
65,536 addresses, of which 65,534 are usable (subtract the network address 10.0.0.0 and the
broadcast 10.0.255.255; in AWS subtract 5, giving 65,531). In your head: /16 means 16 host bits,
2^16 = 65,536; the network is fixed at the first two octets (10.0), and the last two octets
(0.0–255.255) vary. It spans 256 /24 subnets (10.0.0.0/24 through 10.0.255.0/24). A common VPC size.

### 10.17
`0.0.0.0/0` on port 22 means SSH is open to the entire internet — anyone, anywhere, can attempt to
connect. Why it's a problem: SSH is a management port; exposing it globally invites continuous
automated brute-force and credential-stuffing attacks, and any weakness (weak/reused password,
an old CVE in the SSH daemon, a leaked key) becomes a full host compromise; it is one of the most
scanned ports on the internet and a top cause of breaches. What I'd do: remove `0.0.0.0/0`; access
hosts via **AWS SSM Session Manager** (no open port at all, IAM-authenticated, logged — Chapter 78)
or a **bastion host** with SSH restricted to a specific corporate IP (`/32`) or via a VPN; enforce
key-based auth and MFA; and add a Config rule / policy-as-code check that flags any SG allowing
0.0.0.0/0 on 22 (or 3389) so it cannot recur (Chapters 82, 91). The immediate action is to scope the
rule to a specific source or eliminate the open port; the systemic fix is automated detection.

### 10.18
Take the /16 (65,536 addresses) and carve /24 subnets (256 each, 251 usable in AWS) — enough for
most tiers and easy to read since each /24 is one value of the third octet. For three tiers × two
AZs = six subnets: public 10.0.0.0/24 (AZ-a) and 10.0.1.0/24 (AZ-b); app 10.0.10.0/24 and
10.0.11.0/24; data 10.0.20.0/24 and 10.0.21.0/24. Design choices: **leave gaps** (0/1 → 10/11 →
20/21) so more subnets can be added per tier without renumbering; **spread across two AZs** for
availability; **place each tier in its own subnets** so route tables and security groups can enforce
tier isolation (public has an IGW route; app has NAT for egress but no inbound from internet; data
has no internet route at all); **no overlaps**; and choose the /16 so it does not overlap other VPCs
you may peer (Chapter 77). If a tier needs more than 251 hosts, use a larger prefix (/23 or /22) for
that tier. The math is: /16 → 256 possible /24s; assign non-overlapping ones with gaps; the security
comes from which tier lands in which subnet and that subnet's routing.

### 10.19
`169.254.169.254` is the **instance metadata service (IMDS)** in AWS (and the same address in GCP/
Azure), a link-local endpoint (`169.254.0.0/16`) that returns information about the instance —
including, critically, **temporary IAM credentials** for the instance's role. It matters for
security because it is the pivot in **SSRF-to-cloud-compromise**: an application tricked into making
a request to `169.254.169.254` (via an SSRF bug, Chapter 50) can retrieve the instance's IAM
credentials and then act with that role's permissions over the cloud API — a very common and severe
attack path (the Capital One breach is the famous example). Protection: use **IMDSv2** (session-
token-based, which defeats simple SSRF because it requires a PUT to get a token and sets a hop
limit that stops proxied/containerized requests), set the **hop limit to 1** (or block containers'
access), apply **least-privilege instance roles** so a stolen credential is bounded, and **block
egress to 169.254.169.254** from application code paths / use SSRF allow-listing. Recognizing the
address in logs (an app connecting to it unexpectedly) is a key detection signal (Chapters 78, 82).

### 10.20
The host compares the destination IP's network to its own, using its subnet mask: it computes
(own IP AND mask) and (destination IP AND mask). If the results are equal, the destination is on the
same network (local), so the host resolves the *destination's* MAC via ARP (Chapter 9) and sends the
frame directly to the peer over Layer 2. If the results differ, the destination is on a different
network (remote), so the host cannot deliver directly; it sends the frame to its **default gateway**
— resolving the *gateway's* MAC via ARP and setting the frame's destination MAC to the gateway
(while the packet's destination IP remains the final target). The gateway/router then forwards the
packet onward (Chapter 12). So the decision is a masked comparison of network bits, and its outcome
determines whether the host ARPs for the peer or for the gateway — the unifying mechanism of
Chapters 8–10.

---

*Next: Chapter 11 — IPv6: Addressing, SLAAC, NDP, and the Security Surprises. IPv6 is enabled by
default on modern systems and often ignored — a gap attackers exploit. We cover its very different
addressing, its ARP-replacement NDP (whose spoofing you met in Chapter 9), and the dual-stack
oversights that leave "IPv4-hardened" networks wide open.*
