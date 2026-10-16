# Chapter 16 — DNS Part 1: Resolution, Records, Delegation, Caching, and the Root

---

## 1. Why This Matters

DNS is the phone book of the internet, and it is load-bearing for essentially everything. Every
connection your systems make starts with a DNS lookup: your browser to the app, the app to the database,
a Lambda to an external API, a container pulling an image, a workload reaching the metadata service.
DNS is also the connective tissue of cloud: service discovery, private DNS, internal service names,
health-check failover, and CDN steering all run on DNS.

For a cloud security engineer, understanding DNS mechanics (this chapter) before DNS attacks (Chapter 17)
matters because:

1. **DNS is trust-critical and, in its classic form, unauthenticated** — so its integrity failures
   (poisoning, spoofing, hijacking — Chapter 17) are among the most impactful attacks in security. You
   cannot reason about those without knowing how resolution, caching, and delegation actually work.
2. **DNS is a control point you configure.** Route 53, private hosted zones, resolver rules, and query
   logging are cloud DNS security features. Split-horizon DNS, internal service names, and DNS-based
   egress control are architectural decisions you make.
3. **DNS is a detection and exfiltration surface.** DNS queries leave almost every network freely, so
   DNS is both a prime exfiltration/C2 channel (Chapter 17) and, correspondingly, a rich detection
   source (query logging — Chapter 82). Understanding what a normal resolution looks like is prerequisite
   to spotting an abnormal one.
4. **DNS caching and TTLs shape behavior and attacks** — cache poisoning, DNS rebinding (Chapter 17,
   which enables SSRF — Chapter 50), and failover all hinge on caching and TTL, which this chapter
   establishes.

The core idea: **DNS resolves a human-readable name to an address (and other records) through a
hierarchical, delegated, heavily-cached, globally-distributed system, using mostly UDP and mostly
without authentication.** Each of those properties — hierarchy, delegation, caching, UDP,
unauthenticated — has security consequences that Chapter 17 exploits and defends. This chapter builds the
accurate mental model; Chapter 17 breaks and secures it.

---

## 2. Prerequisites

- Chapters 8–15: DNS runs over UDP/TCP (Chapters 18–19), the resolver is handed to the client by DHCP
  (Chapter 15) or the DHCP option set (cloud), and resolution returns the addresses that routing
  (Chapter 12) and ARP (Chapter 9) then use.
- Chapter 4 §Stop 1 (DNS on the request map) — this chapter is that stop in depth.
- Chapter 7 (reading records/packets).

---

## 3. Mental Model

**DNS is a distributed, hierarchical database that maps names to records, resolved by walking down a tree
of delegated authorities and aggressively caching the answers. No single server knows everything; each
level of the hierarchy points you to the next.**

```
   Resolving www.ledger.example  (a RECURSIVE resolver does the walking for the client):

   Client --> recursive resolver: "what is www.ledger.example?"
   Resolver, if not cached, walks the hierarchy:
     1. Ask a ROOT server: "who handles .example?"  -> "ask the .example TLD servers" (a referral)
     2. Ask the .example TLD server: "who handles ledger.example?" -> "ask ns1.ledger.example" (referral)
     3. Ask ledger.example's AUTHORITATIVE server: "what is www.ledger.example?"
          -> "A record: 203.0.113.10, TTL 300"  (the actual ANSWER)
   Resolver caches each result (per its TTL) and returns 203.0.113.10 to the client.
```

Four ideas do the work:

1. **Hierarchy and delegation.** The namespace is a tree: root (`.`) → TLD (`.example`, `.com`) →
   domain (`ledger.example`) → subdomains. Each level *delegates* authority for the level below to
   specific name servers (via NS records). No server is authoritative for everything; authority is
   distributed. This delegation is where control (and hijacking — Chapter 17) lives.
2. **Recursive vs authoritative.** A **recursive resolver** does the walking on the client's behalf and
   caches results (your ISP's resolver, `8.8.8.8`, the cloud's resolver). **Authoritative servers** hold
   the real records for a zone and answer only for it. The client asks the recursive resolver; the
   resolver asks the authoritative chain.
3. **Caching and TTL.** Every answer carries a **TTL** (time to live); resolvers cache it for that
   duration to avoid re-walking the tree. Caching makes DNS fast and scalable — and is the substrate of
   cache poisoning (Chapter 17) and the reason TTL controls failover speed and rebinding windows.
4. **Records, not just addresses.** DNS stores many **record types** — A (IPv4), AAAA (IPv6), CNAME
   (alias), MX (mail), TXT (arbitrary text, incl. SPF/DKIM/verification), NS (delegation), SOA (zone
   info), PTR (reverse), CAA (which CAs may issue certs), SRV (service location). Each has security
   relevance.

**The security framing:** DNS is trust-critical (everything depends on getting the right address) but
classically unauthenticated (a resolver believes the answer it receives, and traditional DNS has no
signature — DNSSEC, Chapter 17, adds one). It is heavily cached (so a poisoned answer persists) and
delegated (so control of any level in the chain — registrar, TLD, name server — is control of the name).
These properties are the attack surface Chapter 17 exploits; this chapter makes them precise.

---

## 4. Fundamentals

### 4.1 The namespace hierarchy and FQDNs

DNS names are read right-to-left, from the most general to the most specific:

```
   www . ledger . example .
   |     |        |       |
   |     |        |       +-- root (the implicit trailing dot; usually omitted)
   |     |        +---------- TLD (top-level domain): .example, .com, .org, .io
   |     +------------------- second-level domain (the registered domain): ledger.example
   +------------------------- subdomain/host: www
```

A **FQDN (Fully Qualified Domain Name)** is the complete name with the (usually implicit) trailing dot.
The hierarchy is the delegation structure: the root delegates TLDs to registries, registries delegate
domains to registrants (you, via a registrar), and you delegate subdomains as you wish. **Control of a
domain is control of everything under it** — a critical security fact (Chapter 17: subdomain takeover,
registrar/registry compromise).

### 4.2 The resolution process in detail

Two modes of query:

- **Recursive query:** "give me the final answer" — the client asks the recursive resolver, which does
  all the work and returns the answer. Clients send recursive queries.
- **Iterative query:** "give me the answer or a referral to who might know" — the recursive resolver
  sends iterative queries down the hierarchy, following referrals (NS records) until it reaches an
  authoritative answer.

The full walk (cold cache), which you should be able to narrate:

```
   1. Client (stub resolver) -> recursive resolver: "www.ledger.example A?" (recursive)
   2. Resolver checks its cache. Miss. It starts iterating:
   3. Resolver -> a ROOT server: "www.ledger.example A?"
        Root: "I don't know, but .example is handled by these TLD servers" (NS referral + glue)
   4. Resolver -> .example TLD server: "www.ledger.example A?"
        TLD: "ledger.example is handled by ns1.ledger.example (203.0.113.53)" (NS referral + glue A)
   5. Resolver -> ns1.ledger.example (authoritative): "www.ledger.example A?"
        Authoritative: "A 203.0.113.10, TTL 300" (the AUTHORITATIVE answer — the AA bit is set)
   6. Resolver caches root/TLD/authoritative NS records and the A record (each per its TTL),
        returns 203.0.113.10 to the client.
```

Key terms: a **referral** points to the next level's name servers (NS records); **glue records** are A/
AAAA records for name servers included in a referral so the resolver can actually reach them (avoiding a
chicken-and-egg lookup); the **AA (Authoritative Answer) bit** in the response indicates the answer came
from a server authoritative for the zone (vs a cached/non-authoritative answer). Subsequent lookups hit
the cache and skip most of this walk — which is why DNS is fast, and why a poisoned cache entry is
durable (Chapter 17).

### 4.3 Record types (the security-relevant ones)

| Type | Purpose | Security relevance |
|---|---|---|
| **A** | name → IPv4 | the basic mapping; poisoning target |
| **AAAA** | name → IPv6 | often overlooked (dual-stack — Chapter 11) |
| **CNAME** | alias (name → another name) | **subdomain takeover** if it points to a decommissioned resource (Chapter 17) |
| **NS** | delegation (who is authoritative) | **control of delegation = control of the domain**; hijack target |
| **SOA** | zone metadata (serial, refresh, TTLs) | zone transfer/consistency |
| **MX** | mail servers | email security; spoofing if misconfigured |
| **TXT** | arbitrary text | **SPF, DKIM, DMARC (email anti-spoofing), domain-verification tokens** |
| **PTR** | reverse (IP → name) | logging/attribution; not a security control (spoofable by the IP owner) |
| **CAA** | which CAs may issue certs for the domain | **limits cert mis-issuance** (Chapter 27) |
| **SRV** | service location (host+port) | service discovery (Kerberos, SIP, etc.) |
| **DS/DNSKEY/RRSIG** | DNSSEC (signatures) | **authenticates DNS answers** (Chapter 17) |

Several of these are direct security controls you configure: **CAA** restricts which certificate
authorities may issue certificates for your domain (mitigating mis-issuance — Chapter 27); **TXT records
for SPF/DKIM/DMARC** are the email anti-spoofing framework (a domain without them is trivially spoofable
for phishing); and **NS records** define delegation, so their integrity is the integrity of your entire
domain.

### 4.4 Caching, TTL, and negative caching

- **Positive caching:** resolvers cache successful answers for the record's **TTL** (seconds). A low TTL
  (e.g. 60) means fast propagation of changes but more queries; a high TTL (e.g. 86400) means fewer
  queries but slow changes. TTL choice affects **failover speed** (Route 53 health-check failover is
  bounded by TTL), **change propagation**, and the **DNS rebinding window** (Chapter 17).
- **Negative caching:** resolvers also cache *failures* (NXDOMAIN — "no such name") for a period
  controlled by the SOA record's minimum, to avoid hammering authoritative servers for nonexistent names.
- **The cache is the performance win and the attack surface.** Cache poisoning (Chapter 17) works by
  inserting a forged answer that the resolver caches and serves to all its clients for the TTL — so the
  impact is amplified (many clients) and durable (the TTL). Understanding caching is understanding why
  poisoning is high-impact.

### 4.5 Zones, delegation, and authoritative servers

A **zone** is a portion of the namespace under one administrative authority (e.g. `ledger.example` and
its subdomains, unless a subdomain is further delegated). The **authoritative name servers** for a zone
hold its records. **Delegation** happens via NS records: the parent zone (`.example`) has NS records
pointing to the child zone's (`ledger.example`) authoritative servers, and the child's servers answer
authoritatively for it.

Security implications of delegation:

- **The delegation chain is a trust chain.** To trust `www.ledger.example`, you trust the root → TLD →
  `ledger.example` delegation. Compromise or misconfiguration at *any* level (a hijacked registrar
  account, a compromised TLD, a stale delegation) hijacks the name (Chapter 17). This is why registrar
  account security (MFA, registry lock) is a critical, often-overlooked control.
- **Stale delegations / dangling records** (an NS or CNAME pointing to a resource you no longer control)
  enable **subdomain takeover** (Chapter 17) — an attacker claims the pointed-to resource and controls
  your subdomain.
- **Zone transfers (AXFR)** replicate a zone between authoritative servers; if left open to anyone, they
  leak the entire zone's records (reconnaissance — Chapter 17, Chapter 123). Restrict AXFR to secondary
  servers only.

### 4.6 Reverse DNS (PTR) and why it is not a security control

**Reverse DNS** maps an IP back to a name via PTR records in the `in-addr.arpa` (IPv4) /`ip6.arpa`
(IPv6) hierarchy. It is used in logging (showing a name instead of an IP), some anti-spam checks, and
diagnostics. But it is **not a security control**: the PTR record is controlled by whoever owns the IP's
reverse zone (the IP block owner), so an attacker who controls their IP's reverse DNS can make it say
anything. Never trust reverse DNS for authorization or identity — the same lesson as "don't trust the
MAC" (Chapter 8): attacker-controlled data is not a credential. (Forward-confirmed reverse DNS — where
the PTR's name also forward-resolves back to the IP — is a slightly stronger check used in anti-spam, but
still not an authorization mechanism.)

---

## 5. Deep Technical Explanation: The DNS Query on the Wire, and Why UDP Matters

A DNS query is a small UDP packet (Chapter 18) to port 53, and the transport choice has deep security
consequences worth understanding now (Chapter 17 exploits them):

```
   DNS query (UDP/53), simplified:
     Header: [ ID (16-bit) | flags (QR, opcode, AA, TC, RD, RA, RCODE) | counts ]
     Question: www.ledger.example  IN  A
   DNS response (UDP/53):
     Header: same ID, QR=1 (response), RCODE=0 (no error)
     Answer: www.ledger.example  300  IN  A  203.0.113.10
```

Why UDP, and why it matters for security:

- **DNS uses UDP for speed** (no handshake — one query, one response, Chapter 18). This is essential for
  performance (billions of lookups) but has consequences:
  - **UDP is spoofable** — the source address is not verified by a handshake, so an attacker can forge a
    response appearing to come from the resolver's expected server. Combined with the **16-bit query ID**
    and source port, this is the basis of **cache poisoning** (Chapter 17): guess/forge the ID+port and
    inject a fake answer before the real one arrives. Source-port randomization and the 16-bit ID make it
    harder but not impossible (the Kaminsky attack, Chapter 17).
  - **UDP DNS enables amplification DDoS** (Chapter 18, Chapter 85): a small spoofed query elicits a
    large response sent to the victim (spoofed source), amplifying the attacker's bandwidth.
- **DNS falls back to TCP/53** for large responses (over 512 bytes traditionally, or when the **TC
  (truncated) bit** is set) and for zone transfers (AXFR). EDNS0 allows larger UDP responses (up to
  ~4096 bytes), which also enables larger amplification.
- **The 16-bit transaction ID + source port are the only "authentication"** in classic DNS — an attacker
  who guesses both can spoof a response. This weak entropy is why cache poisoning was practical (Chapter
  17) and why DNSSEC (cryptographic signatures) and DoH/DoT (encrypted transport) exist.

The security synthesis: **classic DNS trusts the transport (unauthenticated UDP, weak transaction
entropy) and the answer (no signature).** This is the same unauthenticated-trust pattern as ARP/DHCP
(Chapters 9, 15), and it makes DNS spoofing/poisoning possible (Chapter 17). The defenses — DNSSEC
(authenticate the *answer*), DoH/DoT (encrypt/authenticate the *transport*) — address the two halves, and
Chapter 17 covers them. For now, hold that DNS's speed-driven design (cached, UDP, weakly-authenticated)
is exactly what makes its integrity attacks possible.

### 5.1 DNS in the cloud: the resolver and private zones

Cloud DNS adds constructs you configure and secure:

- **The VPC resolver (Route 53 Resolver)** at the "VPC+2" address (e.g. `10.0.0.2`) — the resolver
  instances get from the DHCP option set (Chapter 15). It resolves public names and **private hosted
  zones**.
- **Private hosted zones** — DNS zones resolvable only within your VPC(s), for internal service names
  (e.g. `db.internal.ledger`). This is **split-horizon DNS**: the same name can resolve differently
  inside vs outside the VPC — a useful pattern (internal name resolves to a private IP) with security
  implications (do not leak internal names publicly).
- **Resolver rules and outbound endpoints** — forward specific domains to on-prem resolvers (hybrid) or
  to specific resolvers; a control point for DNS egress and hybrid resolution.
- **Route 53 Resolver query logging** — logs every DNS query from the VPC (Chapter 82) — a primary
  detection surface for DNS exfiltration/C2 (Chapter 17) and for anomalous resolution.
- **Route 53 (public)** — authoritative hosting for your public domains, with health-check-based failover,
  latency/geo routing, and DNSSEC signing.

The security relevance: **the cloud makes DNS a configurable, loggable control point.** You decide the
resolvers (DHCP option set — Chapter 15), you host internal names privately (split-horizon), you can log
every query (detection), and you can sign your zones (DNSSEC). Misconfiguring these — pointing at an
untrusted resolver, leaking internal zones, not logging queries — is the cloud DNS security failure mode.
Chapter 17 details the attacks; the point here is that cloud DNS is something you own and secure, not just
infrastructure that happens.

---

## 6. Internals: Observing DNS

### 6.1 `dig` — the DNS microscope

```bash
$ dig www.example.com                     # a normal query via your resolver
;; ANSWER SECTION:
www.example.com.  300  IN  A  93.184.216.34
;; Query time: 12 msec  ;; SERVER: 10.0.0.2#53   ;; flags: qr rd ra;

$ dig +trace www.example.com              # WATCH the delegation walk from root down (§4.2)
.                     NS  a.root-servers.net.   ...      # root
com.                  NS  a.gtld-servers.net.   ...      # TLD referral
example.com.          NS  a.iana-servers.net.   ...      # domain referral
www.example.com.      A   93.184.216.34                  # authoritative answer

$ dig www.example.com +norecurse          # ask WITHOUT recursion (see if it's cached / referral)
$ dig example.com NS                       # the delegation (authoritative name servers)
$ dig example.com TXT                       # SPF/DKIM/verification records
$ dig example.com CAA                       # which CAs may issue certs (Chapter 27)
$ dig -x 93.184.216.34                      # reverse (PTR) — NOT a security control (§4.6)
```

`dig +trace` is the single best way to *see* the hierarchy and delegation from §4.2 — run it and watch
root → TLD → authoritative. The `flags` (`qr rd ra`, and `aa` on authoritative answers) and `SERVER`
line tell you how the answer was obtained.

### 6.2 See the record types and TTLs

```bash
$ dig example.com ANY 2>/dev/null           # (often restricted now, but shows the idea)
$ dig www.example.com +noall +answer         # just the answer with its TTL
www.example.com. 300 IN A 93.184.216.34      # TTL 300 -> cached for 5 minutes (§4.4)
# Re-run immediately: query time drops (cache hit) and TTL counts down.
```

Watching the TTL count down on repeated queries shows caching in action (§4.4) — and the TTL is the
window of a poisoned entry (Chapter 17) and the bound on failover.

### 6.3 What resolver am I using? (the DHCP/option-set result)

```bash
$ cat /etc/resolv.conf                        # the DNS server(s) — from DHCP (Chapter 15) or option set
nameserver 10.0.0.2                           # e.g. the VPC resolver
$ resolvectl status 2>/dev/null               # systemd-resolved view (per-interface resolvers, DoT)
```

This is the DNS server DHCP handed the client (Chapter 15) — pointing it at an untrusted resolver is a
MITM (Chapters 15, 17), so knowing and controlling it matters.

### 6.4 Cloud DNS query logging (detection)

```bash
# Route 53 Resolver query logs (once configured) record every VPC DNS query:
$ aws logs filter-log-events --log-group-name /aws/route53/vpc-queries --max-items 5
# Look for: high-entropy subdomains (exfiltration), unexpected external domains (C2), etc. (Chapter 17)
```

This is the primary DNS detection surface (Chapter 82) — knowing what normal resolution looks like (this
chapter) is what lets you spot abnormal (Chapter 17).

---

## 7. Real-World Example: DNS in the Ledger Environments

**System A (VPS):** Ledger's `ledger.example` domain is registered at a registrar and hosted on
authoritative name servers (the registrar's or a DNS provider's). The app makes DNS lookups to reach
PostgreSQL (or uses `127.0.0.1`), external APIs (Stripe), and package registries. Security-relevant
points:

- **The registrar account is a critical asset** — control of it means control of the domain's delegation
  (NS records), hence the whole domain. It needs strong MFA and, ideally, registry lock. Registrar
  compromise is a devastating, underappreciated attack (Chapter 17).
- **DNS records to secure:** SPF/DKIM/DMARC (TXT) to prevent email spoofing of `ledger.example`; CAA to
  restrict which CAs can issue certs; correct NS delegation.
- **The resolver** the app uses (from the VPS's `/etc/resolv.conf`) should be a trusted one; a
  compromised resolver MITMs all name resolution.

**System B (AWS):** Ledger uses Route 53 and the VPC resolver:

- **Public zone in Route 53** (authoritative for `ledger.example`) with health-check failover, DNSSEC
  signing (Chapter 17), and correct SPF/DKIM/DMARC/CAA records.
- **Private hosted zone** for internal names (`db.internal.ledger` → RDS's private IP) — split-horizon
  DNS so internal names resolve to private IPs inside the VPC and are not exposed publicly.
- **The DHCP option set** points instances at AmazonProvidedDNS (the VPC resolver), with **Route 53
  Resolver query logging** enabled — every DNS query from the VPC is logged, the primary detection
  surface for DNS exfiltration/C2 (Chapter 17) and for the SSRF-to-metadata pattern (an app resolving
  unexpected names).
- **DNS as an egress consideration:** because DNS queries leave the VPC (to resolve public names), DNS is
  a potential exfiltration channel (Chapter 17); resolver query logging + anomaly detection is the
  control, and restricting outbound DNS to the VPC resolver (not arbitrary external resolvers) tightens
  it.

The Ledger takeaway: **DNS is trust-critical infrastructure that you own and secure at multiple points —
the registrar account (delegation), the zone records (SPF/DKIM/DMARC/CAA/NS), the resolver configuration
(trusted resolvers, split-horizon private zones), and query logging (detection).** Chapter 17 shows how
each is attacked; this chapter establishes what "correctly configured" looks like. The recurring theme:
DNS is not just plumbing — it is a control surface, and in the cloud a loggable, configurable one.

---

## 8. Hands-On Demonstration

### LAB 16.1 — DNS Resolution, Delegation, and Record Inspection

**Objective.** See the resolution walk and delegation hierarchy, inspect security-relevant record types,
observe caching/TTL, and identify the resolver in use — building the accurate DNS model that Chapter 17's
attacks and defenses require.

**Cost.** Free. **Environment.** ENV-1. **Time.** 45 minutes.

**Steps.**

*Step 1 — Watch the delegation walk.*

```bash
dig +trace www.example.com
# Identify: the root servers, the TLD (.com) referral, the domain (example.com) referral,
# and the final authoritative A answer. Narrate each step per §4.2.
```

*Step 2 — Recursive vs authoritative, and the AA bit.*

```bash
dig www.example.com                 # via your recursive resolver (flags: ra = recursion available)
dig @a.iana-servers.net www.example.com   # ask an AUTHORITATIVE server directly (flags: aa)
# Compare the 'flags' line: 'aa' present = authoritative answer (§4.2).
```

*Step 3 — Inspect security-relevant records.*

```bash
dig example.com NS +short           # delegation (authoritative name servers)
dig example.com SOA +short          # zone metadata (serial, TTLs)
dig google.com TXT +short           # SPF and verification records
dig google.com CAA +short           # which CAs may issue certs (Chapter 27)
dig -x 8.8.8.8 +short               # reverse (PTR) — note it's controlled by the IP owner (§4.6)
```

For a domain you control, check whether SPF/DKIM/DMARC and CAA exist — their absence is a real finding
(email spoofing / cert mis-issuance exposure).

*Step 4 — Observe caching and TTL.*

```bash
dig www.example.com +noall +answer       # note the TTL
sleep 2
dig www.example.com +noall +answer       # TTL has counted down (cached); query time lower
# The TTL is the window a poisoned entry would persist (Chapter 17) and the failover bound.
```

*Step 5 — Identify your resolver.*

```bash
cat /etc/resolv.conf                     # which DNS server (from DHCP/option set — Chapter 15)
dig www.example.com | grep SERVER        # confirms the resolver that answered
```

**Security implications.** Write down: (a) the delegation chain is a trust chain (compromise at any level
hijacks the name); (b) caching amplifies and prolongs a poisoned answer (TTL window); (c) DNS is
unauthenticated over UDP (spoofable — Chapter 17); (d) which security records (SPF/DKIM/DMARC/CAA) a
domain should have; (e) the resolver is attacker-relevant (a compromised/rogue resolver MITMs
resolution).

**Cleanup.** None.

---

## 9. Security Implications

- **DNS is trust-critical and classically unauthenticated** — everything depends on getting the right
  address, yet classic DNS has no signature and rides spoofable UDP with weak (16-bit ID + port) entropy.
  This is the substrate of poisoning/spoofing (Chapter 17).
- **The delegation chain is a trust chain** — control of any level (registrar, TLD, name server, NS
  records) is control of the name; registrar account security (MFA, registry lock) is a critical,
  under-appreciated control.
- **Caching amplifies and prolongs attacks** — a poisoned answer is served to all a resolver's clients
  for the TTL; TTL also bounds failover and the DNS-rebinding window (Chapter 17).
- **DNS records are direct security controls you configure** — SPF/DKIM/DMARC (email anti-spoofing), CAA
  (cert mis-issuance limits), correct NS delegation; their absence is a finding.
- **Reverse DNS (PTR) is not a security control** — attacker-controlled, not a credential.
- **DNS queries leave the network freely** — a prime exfiltration/C2 channel and, correspondingly, a rich
  detection surface (query logging — Chapters 17, 82).
- **In the cloud, DNS is a configurable, loggable control point** — resolvers (DHCP option set), private
  hosted zones (split-horizon), resolver rules, query logging, and DNSSEC signing are yours to secure.

---

## 10. Attack Scenarios (previewing Chapter 17)

This chapter is mechanics; Chapter 17 is attacks/defenses. But the mechanics already reveal the surface:

1. **Cache poisoning / spoofing** — forge a response (spoofable UDP + guessed 16-bit ID/port) that the
   resolver caches and serves to all clients for the TTL (Chapter 17; the Kaminsky attack).
2. **Registrar / delegation hijack** — compromise the registrar account or alter NS records to redirect
   the entire domain (Chapter 17).
3. **Subdomain takeover** — a dangling CNAME/NS pointing to a decommissioned resource an attacker can
   claim (Chapter 17).
4. **DNS rebinding** — exploit caching/TTL so a name resolves to an external IP then an internal one,
   enabling SSRF-like access (Chapters 17, 50).
5. **DNS exfiltration / tunneling** — encode data in subdomain queries to an attacker's authoritative
   server, since DNS egress is usually unrestricted (Chapter 17).
6. **Amplification DDoS** — small spoofed UDP queries eliciting large responses to a victim (Chapters 18,
   85).
7. **Email spoofing** — a domain without SPF/DKIM/DMARC is trivially spoofable for phishing.

Each maps to a mechanic in this chapter (caching, delegation, UDP, records); Chapter 17 exploits and
defends them.

---

## 11. Defensive Techniques (foundational; deepened in Chapter 17)

- **Secure the registrar and delegation** — MFA on the registrar account, **registry lock** to prevent
  unauthorized NS/transfer changes, monitor NS records for changes. This protects the top of the trust
  chain.
- **Configure the security records** — **SPF, DKIM, DMARC** (email anti-spoofing; a domain without them
  is spoofable for phishing), **CAA** (restrict which CAs may issue certificates — Chapter 27), and
  correct **NS** delegation. Audit their presence.
- **Restrict zone transfers (AXFR)** to authorized secondary servers only — open AXFR leaks the whole
  zone (reconnaissance — Chapter 17, 123).
- **Avoid dangling records** — remove CNAME/NS pointing to decommissioned resources to prevent subdomain
  takeover (Chapter 17); audit for them.
- **Use trusted, controlled resolvers** — the DHCP option set / `/etc/resolv.conf` should point at
  trusted resolvers (AmazonProvidedDNS or your controlled ones), not attacker-influenced ones (Chapter
  15).
- **Enable DNS query logging** (Route 53 Resolver query logging) — the primary detection surface for
  exfiltration/C2 and anomalous resolution (Chapters 17, 82).
- **Use split-horizon private hosted zones** for internal names, and do not leak internal zone data
  publicly.
- **Deploy DNSSEC and DoH/DoT** (Chapter 17) — authenticate answers and encrypt transport, closing the
  unauthenticated-UDP gap. And rely on **TLS** end-to-end so a DNS lie is caught by certificate
  validation (Chapters 4, 9, 17).

---

## 12. Production Architecture

DNS as infrastructure and control point, VPS vs cloud:

```
 CONCEPT                  SYSTEM A (VPS)                 SYSTEM B (AWS)
 ----------------------   ---------------------------    ---------------------------------------
 authoritative hosting    registrar/DNS provider         Route 53 public hosted zone (+DNSSEC)
 delegation security      registrar MFA + registry lock  registrar MFA + registry lock (same)
 internal names           /etc/hosts or a resolver       Route 53 private hosted zone (split-horizon)
 resolver                 /etc/resolv.conf (from DHCP)    VPC resolver (DHCP option set — Ch.15)
 email anti-spoof         SPF/DKIM/DMARC TXT records      SPF/DKIM/DMARC (same, via Route 53)
 cert mis-issuance limit  CAA records                     CAA records (same)
 detection                resolver/query logs (if any)    Route 53 Resolver query logging (Ch.82)
 integrity/confidentiality DNSSEC + DoH/DoT + TLS          DNSSEC + DoH/DoT + TLS (Chapter 17)
```

The architectural principle: **DNS is trust-critical infrastructure and a configurable control point, not
just plumbing.** Secure it at every level of the trust chain (registrar → delegation → zone records →
resolver → transport), configure the record-based controls (SPF/DKIM/DMARC/CAA), log queries for
detection, and rely on end-to-end TLS so that even a DNS integrity failure is caught by certificate
validation. In the cloud, DNS becomes especially controllable and observable (private zones, resolver
rules, query logging, DNSSEC signing) — treat it as a first-class part of the security architecture.
Chapter 17 turns each of these mechanics into specific attacks and hardening; this chapter's job was to
make the machine legible so those attacks are comprehensible.

---

## 13. Common Mistakes

1. **Weak registrar account security** — no MFA, no registry lock; a compromised registrar account
   hijacks the entire domain (the top of the trust chain).
2. **Missing SPF/DKIM/DMARC** — the domain is trivially spoofable for phishing.
3. **No CAA records** — any CA can issue certs for the domain (cert mis-issuance risk — Chapter 27).
4. **Open zone transfers (AXFR)** — leaking the entire zone to anyone (reconnaissance).
5. **Dangling CNAME/NS records** — enabling subdomain takeover (Chapter 17).
6. **Trusting reverse DNS (PTR)** for identity/authorization — attacker-controlled.
7. **Pointing at untrusted resolvers** (DHCP option set / resolv.conf) — a DNS MITM (Chapters 15, 17).
8. **No DNS query logging** — losing a primary detection surface for exfiltration/C2.
9. **Leaking internal zone data publicly** — exposing internal names/IPs (recon aid).
10. **Assuming DNS is authenticated** — classic DNS is not; rely on DNSSEC + TLS (Chapter 17).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Name doesn't resolve | delegation broken, record missing, or resolver issue | `dig +trace`; `dig @authoritative name`; check NS records |
| Old IP still used after a DNS change | TTL caching (change not yet propagated) | check the record's TTL; wait/flush; lower TTL before planned changes |
| Different answers from different resolvers | split-horizon, caching, or poisoning | compare `dig @resolver1` vs `@resolver2` and vs authoritative |
| Email spoofed as your domain | missing/incorrect SPF/DKIM/DMARC | `dig TXT` for SPF/DMARC; check DKIM selector records |
| Cert issued by an unexpected CA | no CAA restriction | `dig CAA`; add CAA (Chapter 27) |
| Whole zone appears leaked | open AXFR | `dig AXFR @ns example.com` (should be refused); restrict transfers |
| Subdomain serving attacker content | subdomain takeover (dangling record) | check CNAME/NS targets are still controlled (Chapter 17) |
| Suspicious high-entropy DNS queries | DNS exfiltration/tunneling | Route 53 Resolver query logs; look for long/random subdomains (Chapter 17) |

---

## 15. Practical Lab

Lab 16.1 is in §8. Register it in the lab index. Extension: for a domain you control (or a test domain),
audit its DNS security posture — verify SPF/DKIM/DMARC, CAA, correct NS delegation, no open AXFR, and no
dangling records — producing a findings list. This "DNS security posture audit" is a real, recurring
deliverable and directly sets up Chapter 17's attacks (each finding corresponds to an attack it enables).

---

## 16. Exercises

### Concept questions

**16.1** Explain the DNS resolution process end to end, distinguishing recursive from iterative queries
and recursive resolvers from authoritative servers. What is a referral and a glue record?

**16.2** Explain the delegation hierarchy and why "the delegation chain is a trust chain." Which levels'
compromise would hijack a name?

**16.3** Explain caching and TTL, and why caching makes DNS both scalable and a high-impact attack
surface. How does TTL relate to failover and the rebinding window?

**16.4** For each of A, CNAME, NS, TXT, CAA, PTR, describe its purpose and one security relevance.

**16.5** Why does DNS use UDP, and what are the security consequences (spoofability, amplification, weak
transaction entropy)?

### Debugging problems

**16.6** After changing a record, some users still get the old IP hours later. Explain and give the
correct procedure for planned DNS changes.

**16.7** A name resolves differently inside your VPC than outside. Is this a problem? Explain
split-horizon DNS and when the difference is intended vs a poisoning symptom.

**16.8** Email from your domain is being spoofed for phishing. Which DNS records do you check and
configure, and how do they prevent spoofing?

### Security scenarios

**16.9** You are auditing a domain's DNS security posture. List every check you perform and the attack
each finding would enable (bridge to Chapter 17).

**16.10** Explain why the registrar account is one of the most critical assets to protect, and how you
would secure the DNS trust chain end to end.

### Architecture questions

**16.11** Design DNS for a cloud application needing public names, internal service discovery, email, and
detection. Name the mechanism for each and its security configuration.

**16.12** Explain how DNS is a control point (not just plumbing) in a cloud environment, listing the
security features you configure and what each protects against.

### Hands-on exercises

**16.13** Use `dig +trace` to document the full delegation walk for a domain, labeling root/TLD/
authoritative steps and the AA bit.

**16.14** Audit a domain for SPF/DKIM/DMARC, CAA, NS, and open AXFR, and report findings.

**16.15** Observe caching/TTL by repeated `dig` and explain how the TTL bounds a poisoned entry's
lifetime and failover speed.

### Interview questions

**16.16** "Walk me through what happens when you type a URL, from the DNS perspective."

**16.17** "Why is DNS a security-critical system, and what makes classic DNS attackable?"

**16.18** "What DNS records are actually security controls, and what does each protect?"

**16.19** "How is DNS a control point and detection surface in the cloud?"

**16.20** "Why is the domain registrar account such a critical asset?"

---

## 17. Summary

- **DNS resolves names to records through a hierarchical, delegated, heavily-cached, globally-distributed
  system, mostly over UDP and classically unauthenticated.** A **recursive resolver** walks the tree
  (root → TLD → authoritative), following **referrals** (NS records, with **glue**) and caching each
  answer per its **TTL**.
- **The namespace is a delegation hierarchy**, and **the delegation chain is a trust chain** — control of
  any level (registrar, TLD, name server, NS records) controls the name, so registrar security (MFA,
  registry lock) is critical.
- **Records are more than addresses**: A/AAAA (mappings), **CNAME** (aliases — subdomain-takeover risk),
  **NS** (delegation), **TXT** (**SPF/DKIM/DMARC** email anti-spoofing, verification), **CAA** (limit
  cert issuers — Chapter 27), **PTR** (reverse — **not** a security control), SRV, MX. Several are direct
  security controls you must configure.
- **Caching + TTL** make DNS fast and scalable and make attacks **high-impact and durable** (a poisoned
  answer is served to all clients for the TTL); TTL bounds failover and the rebinding window (Chapter 17).
- **UDP transport + 16-bit transaction ID + source port are the only classic "authentication"** — weak
  and spoofable, enabling **cache poisoning** and **amplification DDoS**; DNSSEC (sign answers) and
  DoH/DoT (encrypt transport) address this (Chapter 17).
- **In the cloud, DNS is a configurable, loggable control point**: resolvers (DHCP option set), **private
  hosted zones** (split-horizon), resolver rules, **query logging** (detection), and DNSSEC signing —
  yours to secure.
- **DNS queries leave the network freely** — a prime exfiltration/C2 channel and, symmetrically, a rich
  detection surface (Chapters 17, 82). Chapter 17 turns these mechanics into attacks and defenses.

---

## 18. Knowledge Check

1. What is the difference between a recursive resolver and an authoritative server? (§3, §4.2)
2. Narrate the cold-cache resolution walk for a name. (§4.2)
3. What is a referral and a glue record? (§4.2)
4. Which record types are direct security controls, and what does each protect? (§4.3)
5. Why does caching make DNS attacks high-impact and durable? (§4.4)
6. Why is "the delegation chain is a trust chain," and what secures the top of it? (§4.5, §11)
7. Why is reverse DNS not a security control? (§4.6)
8. Why does DNS use UDP, and what are the security consequences? (§5)
9. What cloud DNS features are security control points? (§5.1)
10. What are the two halves of DNS security that DNSSEC and DoH/DoT address? (§5, preview §17)

---

## 19. Further Exploration

- `dig +trace` several domains and narrate the delegation each time until the hierarchy is intuitive.
- RFC 1034/1035 (DNS concepts and implementation) — foundational; skim the resolution and record
  sections.
- Run a DNS security posture audit (Lab 16.1 extension / §15) on a domain you control; fix the findings.
- Read the SPF/DKIM/DMARC overview (dmarc.org) — the email anti-spoofing framework you configure in DNS.
- AWS Route 53 documentation: public vs private hosted zones, Resolver rules/endpoints, query logging,
  and DNSSEC — the cloud DNS control points (§5.1).
- Preview Chapter 17: each mechanic here (caching, delegation, UDP, records) becomes an attack (poisoning,
  hijack, rebinding, exfiltration) and a defense (DNSSEC, DoH/DoT, registry lock, query-log detection).

---

## Solutions

### 16.1
Resolution: the client's stub resolver sends a **recursive** query ("give me the final answer") to a
**recursive resolver**. If the resolver has the answer cached, it returns it; otherwise it performs
**iterative** queries ("give me the answer or a referral") down the hierarchy — asking a root server
(which refers it to the TLD servers), then the TLD server (which refers it to the domain's authoritative
servers), then the **authoritative server** for the zone (which returns the actual record with the AA
bit set). The resolver caches each result per its TTL and returns the answer to the client. A **recursive
resolver** does the walking and caches (e.g. 8.8.8.8, the VPC resolver); an **authoritative server**
holds a zone's real records and answers only for that zone. A **referral** is a response that, instead of
the answer, points to the name servers (NS records) for the next level down. A **glue record** is an
A/AAAA record for a name server included *within* a referral, so the resolver can reach that name server
without a separate lookup (avoiding the chicken-and-egg where resolving the NS's name would itself require
DNS). So clients send recursive queries; resolvers send iterative queries following referrals with glue.

### 16.9
DNS security posture audit checks and the attack each finding enables: (1) **Registrar account security**
(MFA, registry lock) — if weak → **domain/delegation hijack** (Chapter 17). (2) **NS delegation
correctness and monitoring** — stale/incorrect NS → hijack or resolution failure; unmonitored NS changes
→ undetected hijack. (3) **SPF, DKIM, DMARC (TXT)** — missing/misconfigured → **email spoofing/phishing**
of the domain. (4) **CAA records** — absent → any CA can issue certs → **certificate mis-issuance**
(Chapter 27). (5) **Open zone transfer (AXFR)** — if permitted to anyone → **full zone disclosure /
reconnaissance** (Chapter 17, 123). (6) **Dangling CNAME/NS records** (pointing to decommissioned cloud
resources) → **subdomain takeover** (Chapter 17). (7) **DNSSEC** — unsigned zone → susceptible to
**cache poisoning/spoofing** without cryptographic validation (Chapter 17). (8) **Resolver configuration**
(what resolvers clients/instances use) — untrusted resolver → **DNS MITM** (Chapters 15, 17). (9) **Query
logging enabled?** — absent → no detection of **DNS exfiltration/C2** (Chapter 17). (10) **Internal zone
exposure** — internal names/IPs resolvable publicly → **reconnaissance aid**. Deliverable: a findings
list, each tied to the attack it enables, prioritized by impact (registrar/delegation and email spoofing
typically highest). This audit directly maps to Chapter 17's attack catalogue.

### 16.16
From the DNS perspective: the browser first checks its own cache and the OS stub resolver's cache for the
name; on a miss, the stub resolver sends a recursive query to the configured recursive resolver (from
DHCP / the DHCP option set — Chapter 15, e.g. the VPC resolver or 8.8.8.8). The recursive resolver, if
not cached, iterates the hierarchy: it asks a root server (referral to the TLD servers), then the TLD
server (referral to the domain's authoritative name servers, with glue), then the authoritative server,
which returns the A/AAAA record (authoritative answer, AA bit set) with a TTL. The resolver caches each
result per its TTL and returns the address to the client. The browser now has the IP and proceeds to
connect (TCP handshake, TLS, HTTP — Chapter 4). Security notes to add: classic DNS is unauthenticated
over UDP (spoofable — the resolver believes the answer), so a poisoned/spoofed answer would send the
browser to the attacker's IP, caught only by TLS certificate validation (the attacker cannot present a
valid cert for the real name) — which is why DNS integrity (DNSSEC) and TLS together matter; and the
whole thing is cached, so a poisoned entry persists for the TTL and affects all the resolver's clients.

### 16.20
The registrar account is critical because it controls the **delegation** of your domain — specifically
the NS records that determine which name servers are authoritative for your zone, and the ability to
transfer the domain to another registrar. Control of the registrar account is therefore control of the
entire domain: an attacker who compromises it can repoint the NS records to name servers they control,
making themselves authoritative for every name under the domain — redirecting web traffic, email (MX),
and any service, and obtaining TLS certificates for the domain (via DNS or HTTP validation) since they
now control DNS responses. This is a total, top-of-the-trust-chain compromise that bypasses all your
server-side controls, because it happens above your infrastructure at the delegation layer. It is also
frequently under-protected (treated as a mundane billing account). Securing it: enable **MFA** on the
registrar account, use **registry lock** (a registry-level lock requiring out-of-band verification to
change NS/transfer/contact records, preventing even a compromised registrar account from making changes),
restrict and monitor who has access, **monitor NS records** for unexpected changes, and keep registration
contact details current. Because it is the root of the DNS trust chain, its compromise is one of the most
devastating and hardest-to-detect attacks, which is exactly why it warrants the strongest protection.

---

*Next: Chapter 17 — DNS Part 2: DoH/DoT, DNSSEC, Poisoning, Rebinding, Exfiltration, and Cloud DNS. We
take every mechanic from this chapter and turn it into the attacks (cache poisoning, hijacking, subdomain
takeover, rebinding→SSRF, tunneling/exfiltration) and the defenses (DNSSEC to authenticate answers,
DoH/DoT to encrypt transport, registry lock, query-log detection) — completing DNS as both the most
depended-upon and most attacked system in the stack.*
