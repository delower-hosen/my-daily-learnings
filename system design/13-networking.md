# Chapter 13 — Networking 🟢

> Application developers are often weakest here, and it costs them.
> Half of "the app is slow" and most of "it works on my machine" are networking problems.
>
> You do not need to be a network engineer. You need to know what happens between the browser and your code, and **what can fail at each step**.

---

## 13.1 The journey of one request

Memorise this chain. It is the single most useful diagram in the chapter, because every performance and availability problem lives somewhere on it.

```
  1. User types https://app.example.com
        │
  2. DNS RESOLUTION           browser cache → OS cache → resolver → root → TLD → authoritative
        │                     (0–100 ms; can be 0 if cached)
  3. TCP HANDSHAKE            SYN → SYN/ACK → ACK              (1 round trip)
        │
  4. TLS HANDSHAKE            ClientHello → ... → Finished     (1–2 round trips)
        │
  5. CDN EDGE                 cache hit? → return. miss → continue
        │
  6. LOAD BALANCER            pick a healthy backend
        │
  7. REVERSE PROXY / INGRESS  route by host/path, terminate TLS
        │
  8. API GATEWAY              auth, rate limit, route
        │
  9. SERVICE                  your code finally runs
        │
 10. DATABASE / CACHE         and its own connection, pool, query
        │
 11. RESPONSE                 back up the whole chain
```

**Every arrow is a place where things fail, add latency, or get misconfigured.** When someone says "the site is slow", your first question should be *"which of these eleven steps?"* — and the answer comes from tracing (Chapter 18), not from guessing.

---

## 13.2 IP, subnets and CIDR 🟢

### IPv4

32 bits, written as four octets: `192.168.1.100`. About 4.3 billion addresses — exhausted, which is why NAT and IPv6 exist.

### CIDR notation — read this fluently

`10.0.0.0/16` means: the first **16 bits** are the network, the remaining 16 identify hosts.

| CIDR | Subnet mask | Usable hosts | Typical use |
|------|-------------|--------------|-------------|
| `/8` | 255.0.0.0 | 16,777,214 | A whole private range |
| `/16` | 255.255.0.0 | 65,534 | **A VPC** |
| `/20` | 255.255.240.0 | 4,094 | A large subnet |
| `/24` | 255.255.255.0 | 254 | **A standard subnet** |
| `/28` | 255.255.255.240 | 14 | A small service subnet |
| `/32` | 255.255.255.255 | 1 | **A single host** (used constantly in firewall rules) |

**Quick mental maths:** usable hosts = 2^(32 − prefix) − 2. (Minus 2 for the network and broadcast addresses; cloud providers reserve a few more — AWS reserves 5 per subnet.)

### Private address ranges (RFC 1918) — memorise these

```
10.0.0.0/8         10.0.0.0    – 10.255.255.255     (16.7M addresses)
172.16.0.0/12      172.16.0.0  – 172.31.255.255     (1M addresses)
192.168.0.0/16     192.168.0.0 – 192.168.255.255    (65K addresses)
```

These are never routable on the public internet. Also worth knowing: `127.0.0.0/8` (loopback), `169.254.0.0/16` (link-local — including AWS's `169.254.169.254` metadata endpoint, which matters for SSRF attacks in Chapter 17).

### Designing a VPC — a practical layout

```
VPC: 10.0.0.0/16                                    (65,536 addresses)

  Availability Zone A            Availability Zone B
  ├── 10.0.1.0/24  public        ├── 10.0.2.0/24  public      ← ALB, NAT gateway
  ├── 10.0.11.0/24 private app   ├── 10.0.12.0/24 private app ← your services
  └── 10.0.21.0/24 private data  └── 10.0.22.0/24 private data← databases

  Public subnet  = has a route to an Internet Gateway
  Private subnet = no inbound from the internet; outbound via NAT
```

> **The core security principle: databases live in a private subnet with no route from the internet. Ever.** Application servers sit in a private subnet too; only the load balancer is public. If you can reach your database from your laptop without a VPN or bastion, that is a finding.

**Plan your CIDR ranges before you build.** Overlapping ranges between VPCs (or with an on-prem network) make VPC peering and VPN impossible later, and renumbering a live network is genuinely painful. Reserve generously — `/16` per VPC, `/24` per subnet.

### IPv6

128 bits: `2001:0db8:85a3::8a2e:0370:7334`. Enough addresses for every grain of sand. No NAT needed.

**Practical impact today:** mobile networks are increasingly IPv6-only, so public-facing services should support it (usually free via your load balancer or CDN). Internally, most clouds are still IPv4-centric. **Know that IPv6 addresses can appear in your logs and rate limiters** — a rate limiter keyed on a full IPv6 address is useless (a user has trillions); key on the `/64` prefix.

### NAT

Network Address Translation lets many private addresses share one public address.

```
10.0.11.5:51234 ──► NAT gateway ──► 54.23.11.9:51234 ──► internet
                    (rewrites source, remembers the mapping)
```

**What this means for you:**
- **Outbound works, inbound does not.** A private instance can call an API; the API cannot call it back.
- **Many users share one public IP.** A corporate office or mobile carrier can be thousands of users behind one address — so **IP-based rate limiting punishes them all**. Use user/tenant identity where you can.
- **NAT gateways cost money** in the cloud, charged per GB processed. A chatty service pulling from S3 through a NAT gateway generates a shocking bill. **Use VPC endpoints / Private Link** to keep that traffic off the NAT.

---

## 13.3 TCP and UDP 🟢

| | **TCP** | **UDP** |
|---|---|---|
| Connection | Yes — handshake first | No — just send |
| Reliability | Guaranteed delivery, retransmits | Best effort; packets may vanish |
| Ordering | Guaranteed | None |
| Congestion control | Yes | No (you build it) |
| Overhead | 20+ byte header, ACKs, state | 8 byte header, no state |
| Latency | Higher (handshake, retransmit waits) | Lower |
| Use for | HTTP, databases, email, file transfer | DNS, video/voice, gaming, metrics, QUIC |

### The TCP three-way handshake (why the first request is slow)

```
Client                          Server
  │──────── SYN ──────────────────►│
  │◄─────── SYN-ACK ───────────────│     1 full round trip before ANY data
  │──────── ACK + data ───────────►│
```

On a 50 ms link that is 50 ms before a single byte of your request is sent. **Add TLS (1–2 more round trips) and you have spent 100–150 ms before your server sees anything.**

> **This is why connection reuse matters so much.** HTTP keep-alive, connection pools and HTTP/2 multiplexing exist to avoid paying the handshake repeatedly. A client that opens a new connection per request on a cross-region link is an easy 100 ms per call slower than it needs to be.

### Concepts that show up in real incidents

| Concept | What it means | The symptom you will see |
|---------|---------------|--------------------------|
| **Slow start** | TCP begins cautiously and ramps up | The first ~14 KB is fast, then it accelerates — small responses never reach full speed |
| **Bandwidth-delay product** | Throughput ≈ window size ÷ RTT | High-latency links are slow even with huge bandwidth. Transferring a large file between continents needs window tuning or parallel streams. |
| **Nagle's algorithm** | Buffers small writes into one packet | Adds up to ~40 ms of latency for small chatty messages. Real-time protocols set `TCP_NODELAY`. |
| **TIME_WAIT** | Closed sockets linger ~60 s | A high-churn client exhausts local ports; symptom is "cannot assign requested address". Fix: connection pooling. |
| **Head-of-line blocking** | One lost packet stalls everything behind it on that connection | HTTP/2 solves it at the stream level but not at TCP level; **HTTP/3 over QUIC solves it properly** |

### Ports

```
0–1023      Well-known    (22 SSH, 53 DNS, 80 HTTP, 443 HTTPS, 5432 Postgres, 6379 Redis)
1024–49151  Registered    (8080, 3000, 9092 Kafka, 27017 Mongo)
49152–65535 Ephemeral     (the client side of each outbound connection)
```

**The ephemeral port limit is a real capacity ceiling:** ~28,000 usable ports per source IP per destination. A service making 30,000 concurrent outbound connections to one backend will run out. Connection pooling is the fix.

---

## 13.4 DNS 🟢

DNS turns names into addresses. It is also a load balancer, a failover mechanism, and — when misconfigured — the cause of a surprising number of outages.

### Resolution chain

```
app.example.com?
  1. Browser cache          (seconds–minutes)
  2. OS cache               (respects TTL, mostly)
  3. Recursive resolver     (ISP / 8.8.8.8 / 1.1.1.1) — caches per TTL
  4. Root servers           → "ask the .com servers"
  5. TLD servers (.com)     → "ask ns1.example.com"
  6. Authoritative server   → "93.184.216.34"
```

### Record types you must know

| Type | Purpose | Example |
|------|---------|---------|
| **A** | Name → IPv4 | `app.example.com → 93.184.216.34` |
| **AAAA** | Name → IPv6 | |
| **CNAME** | Alias to another name | `www → app.example.com` (cannot exist at the zone apex) |
| **ALIAS/ANAME** | CNAME-like, works at the apex | Provider-specific (Route 53 "Alias", Cloudflare "CNAME flattening") |
| **MX** | Mail servers | |
| **TXT** | Arbitrary text | SPF, DKIM, DMARC, domain verification |
| **NS** | Delegates a zone | |
| **SRV** | Service + port | Used by some service-discovery systems |
| **CAA** | Which CAs may issue certificates | A cheap, valuable security control |

### TTL — the setting that decides how fast you can fail over

```
TTL = 300      → changes propagate in ~5 minutes, more DNS queries
TTL = 86400    → changes take up to a DAY, fewer queries
```

> **The migration rule:** lower the TTL to 60 seconds **at least 24–48 hours before** a planned cutover (so the old long TTL has expired everywhere), do the migration, then raise it again. Teams that forget this discover that a "5 minute" DNS change takes a day for some users.

**Also know:** some clients (notably older JVMs) **cache DNS forever** regardless of TTL. Some resolvers ignore very low TTLs. **DNS is a hint, not a guarantee** — which is why DNS alone is a poor failover mechanism.

### DNS-based traffic management

| Policy | Behaviour | Use for |
|--------|-----------|---------|
| **Simple** | One record | Basics |
| **Weighted** | 90% → A, 10% → B | Canary releases, gradual migration |
| **Latency-based** | Nearest healthy region | Global performance |
| **Geolocation** | By user country | **Data residency and compliance** |
| **Failover** | Primary, with health checks | DR (Chapter 19) |
| **Multivalue** | Several healthy IPs | Poor-man's load balancing |

**Anycast** is the better global mechanism: one IP address announced from many locations, and BGP routes each user to the nearest one. This is how Cloudflare, Google DNS and modern CDNs work — failover is at the routing layer, in seconds, with no DNS caching problem.

### DNS failures you will meet

1. **Expired domain** — the most embarrassing outage class, and it still happens to large companies
2. **Missing CAA record** blocking certificate renewal
3. **CNAME at the apex** — invalid; use ALIAS/ANAME
4. **A negative cache (NXDOMAIN) stuck for the SOA minimum TTL** — you created the record, but resolvers still say it does not exist
5. **Split-horizon confusion** — internal and external DNS returning different answers, and only one of them is right for the caller
6. **DNS resolution inside containers** — a classic Kubernetes latency problem (`ndots:5` causing five failed lookups before the right one). Symptom: every outbound call has a mysterious extra 20–100 ms.

---

## 13.5 TLS/HTTPS 🟢

### What TLS provides

1. **Confidentiality** — encrypted in transit
2. **Integrity** — tampering is detected
3. **Authentication** — you are talking to the real server (via its certificate)

Note what it does **not** provide: it says nothing about whether the server is trustworthy, only that it is who its certificate claims.

### The handshake (TLS 1.3)

```
Client                                     Server
  │── ClientHello (+ key share) ─────────────►│
  │◄─ ServerHello, certificate, Finished ─────│     ONE round trip
  │── Finished, application data ────────────►│
```

TLS 1.2 needed two round trips; **TLS 1.3 needs one**, and supports 0-RTT resumption for repeat visitors. That is a real, measurable latency win — **use TLS 1.3, disable 1.0/1.1 entirely.**

### Certificates

```
Root CA (in the OS/browser trust store)
   └── Intermediate CA
          └── Your certificate (app.example.com)
```

**The #1 real-world mistake: not serving the intermediate certificate.** It works in your browser (which may have cached the intermediate) and fails in curl, on mobile, and in server-to-server calls. Always test with `openssl s_client -connect host:443 -showcerts` or SSL Labs, not just Chrome.

| Type | Covers | Notes |
|------|--------|-------|
| **DV** (Domain Validated) | Domain control | Free (Let's Encrypt), issued in seconds — **use this** |
| **OV / EV** | Organisation identity | Browsers no longer display them specially; mostly marketing |
| **Wildcard** | `*.example.com` | One cert, many subdomains; one key to lose |
| **SAN/multi-domain** | Several explicit names | Most flexible |

### Certificate expiry — the outage everyone has

**Expired certificates are one of the most common self-inflicted outages in the industry.**

- [ ] **Automate renewal** (cert-manager, ACME, or your cloud provider's managed certificates)
- [ ] **Alert at 30, 14 and 7 days** remaining — on *every* certificate, including internal ones
- [ ] **Inventory every certificate**, including ones on load balancers, internal services, client certs and third-party integrations
- [ ] Remember that **internal mTLS certs expire too**, and often have no monitoring at all

### Termination patterns

```
1. TERMINATE AT THE EDGE (most common)
   Client ──TLS──► LB ──plaintext──► Service
   ✅ Simple, LB can inspect and route     ❌ Internal traffic unencrypted

2. TERMINATE AND RE-ENCRYPT
   Client ──TLS──► LB ──TLS──► Service
   ✅ Encrypted everywhere, LB still routes  ❌ More CPU, more certs to manage

3. PASSTHROUGH
   Client ────────TLS────────► Service
   ✅ True end-to-end            ❌ LB is blind (L4 only); no path routing

4. mTLS (both sides present certificates)
   Client ◄──TLS + client cert──► Service
   ✅ Strong service identity     ❌ Certificate lifecycle at scale — use a service mesh
```

> For internal service-to-service traffic in a zero-trust model, **mTLS with short-lived certificates issued automatically by a service mesh** is the modern answer (Chapter 15/17). Do not hand-manage internal certificates.

**Security headers worth setting at the edge (Chapter 17 covers them fully):**

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; ...
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

---

## 13.6 HTTP versions 🟢

| | **HTTP/1.1** | **HTTP/2** | **HTTP/3** |
|---|---|---|---|
| Transport | TCP | TCP | **QUIC over UDP** |
| Concurrency | One request at a time per connection (browsers open 6) | **Multiplexed streams** on one connection | Multiplexed, independent streams |
| Head-of-line blocking | At the request level | Fixed at HTTP level, **remains at TCP level** | **Fully solved** |
| Headers | Plain text, repeated every request | **HPACK compression** | QPACK compression |
| Server push | No | Yes (deprecated in practice) | No |
| Connection setup | TCP + TLS (2–3 RTT) | TCP + TLS (2–3 RTT) | **1 RTT, or 0-RTT on resume** |
| Handles packet loss | Poorly | Poorly (TCP HOL) | **Well** |
| Connection migration | No | No | **Yes** — survives Wi-Fi → mobile switch |

### What this means practically

**HTTP/1.1 workarounds you should now delete:**
- Domain sharding (splitting assets across `cdn1`, `cdn2`) — actively *harmful* under HTTP/2
- Sprite sheets and file concatenation — mostly unnecessary
- Inlining assets to save requests — usually not worth it

**HTTP/2 gotchas:**
- One connection, many streams → a load balancer sees one connection and may send all of it to one backend. **gRPC/HTTP2 needs an L7-aware load balancer that balances per-request**, not per-connection. This is a classic "why is one pod at 100% CPU?" bug.
- TCP head-of-line blocking still bites on lossy networks (mobile)

**HTTP/3 is the real win on mobile:** connection migration means a user walking out of a café keeps their session instead of stalling. Enable it at your CDN — it is usually a toggle.

### Keep-alive and connection pooling

```python
# WRONG — a new TCP + TLS handshake for every call
for item in items:
    requests.get(f"https://api.example.com/items/{item}")   # ~100 ms wasted each

# RIGHT — reuse the connection
with httpx.Client(
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=2.0, read=10.0),
    http2=True,
) as client:
    for item in items:
        client.get(f"https://api.example.com/items/{item}")
```

> **In .NET: use `IHttpClientFactory`, never `new HttpClient()` in a loop** (socket exhaustion) and never a single static `HttpClient` forever (it caches DNS and misses failovers). The factory solves both.

---

## 13.7 Load balancers, proxies and gateways 🟢

Four words people use interchangeably and should not:

| Component | Sits in front of | Purpose |
|-----------|-----------------|---------|
| **Forward proxy** | The **client** | Client makes requests through it — corporate egress control, filtering, caching, anonymity |
| **Reverse proxy** | The **server** | Clients think it *is* the server — TLS, caching, compression, routing |
| **Load balancer** | The server | Distributes across backends (a specialised reverse proxy) |
| **API gateway** | The server | A reverse proxy plus API concerns: auth, rate limit, transform, metering |

```
FORWARD PROXY                          REVERSE PROXY
Client ──► Proxy ──► Internet          Internet ──► Proxy ──► Servers
(the proxy acts for the CLIENT)        (the proxy acts for the SERVER)
```

**Egress proxies matter architecturally:** in regulated environments all outbound traffic goes through a forward proxy for inspection and allowlisting. If your service calls a vendor API, it may need proxy configuration — and forgetting this is a classic "works in dev, fails in production" problem.

(L4 vs L7, algorithms and health checks are covered in Chapter 04 §4.6.)

### CDN — one more time, from the network angle

A CDN is a globally distributed reverse proxy. Beyond caching (Chapter 11), it gives you:

- **TLS termination at the edge** — the handshake happens 20 ms away instead of 200 ms away, which is a big latency win even for uncacheable content
- **Long-lived, optimised connections** back to your origin
- **DDoS absorption** — their capacity is measured in terabits
- **WAF** at the edge
- **Origin shielding** — one designated edge fetches from your origin, so a global cache miss does not become 200 simultaneous origin requests

> **Even for a fully dynamic, uncacheable API, putting a CDN in front is usually worth it** for TLS termination, connection reuse and DDoS protection alone. This surprises people.

---

## 13.8 Firewalls, security groups and network policy 🟢

### Layers of network control

```
1. NETWORK ACL / firewall     stateless, subnet level, allow AND deny rules
2. SECURITY GROUP             stateful, instance level, allow-only
3. HOST FIREWALL              iptables/nftables, on the machine
4. KUBERNETES NETWORK POLICY  pod-to-pod rules inside the cluster
5. SERVICE MESH POLICY        identity-based (mTLS), L7-aware
6. WAF                        application layer — SQLi, XSS, bot rules
```

**Stateful vs stateless matters:** a security group is stateful, so allowing inbound 443 automatically permits the response out. A network ACL is stateless — you must allow the return traffic on ephemeral ports explicitly. Forgetting this is a classic half-day debugging session.

### The rules that matter

```
✅ DEFAULT DENY. Allow only what is needed, explicitly.
✅ Reference security groups, not IP ranges, where the platform allows it
   (app-sg → db-sg on 5432, rather than 10.0.11.0/24 → 5432)
✅ Databases: inbound only from the app security group. Never 0.0.0.0/0. Never.
✅ Admin access (SSH/RDP): via a bastion, SSM Session Manager, or a VPN — never open to the internet
✅ Restrict EGRESS too — a compromised container should not be able to call anything
✅ Separate environments into separate VPCs/accounts, not just separate subnets
```

> **The single most common cloud breach:** a database or object store exposed to `0.0.0.0/0` "temporarily, for debugging". Audit for it automatically; make it a fitness function (Chapter 00).

### Kubernetes NetworkPolicy

By default in Kubernetes, **every pod can talk to every other pod, in every namespace.** That is almost never what you want.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-api-only
  namespace: production
spec:
  podSelector:
    matchLabels: { app: postgres }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels: { app: verification-api }
      ports:
        - protocol: TCP
          port: 5432
```

Start with a default-deny policy per namespace, then allow specific flows. Note: NetworkPolicy requires a CNI that supports it (Calico, Cilium) — with some CNIs the policy is silently ignored, which is worse than having none.

---

## 13.9 VPNs and private connectivity 🟡

| Option | What it is | Use for |
|--------|-----------|---------|
| **Site-to-site VPN** | Encrypted tunnel between two networks over the internet | Connecting on-prem to cloud; cheap, but internet-quality latency |
| **Client VPN** | Individual users dial in | Staff access to private resources |
| **Direct Connect / ExpressRoute** | A dedicated physical circuit | Consistent latency, high bandwidth, large data transfer; expensive, weeks to provision |
| **VPC Peering** | Direct private routing between two VPCs | Simple; **not transitive** (A–B and B–C does not give A–C); CIDRs must not overlap |
| **Transit Gateway** | A hub connecting many VPCs and VPNs | The scalable answer above ~5 VPCs |
| **PrivateLink / Private Endpoint** ⭐ | A service exposed *inside* your VPC as a private address | **Traffic to a vendor or a managed service never touches the internet** |

> **PrivateLink is the one to remember.** It lets you consume a SaaS/managed service (or expose your own to a customer) over private addressing only, with no internet route, no NAT charges, and a much simpler compliance story. For a B2B product handling sensitive data, offering PrivateLink is a genuine enterprise selling point.

---

## 13.10 Latency, bandwidth and the speed of light 🟢

**Latency is bounded by physics.** Light in fibre travels ~200,000 km/s, and real routes are not straight lines.

| Route | One-way (theoretical) | Realistic RTT |
|-------|----------------------|---------------|
| Same rack | — | 0.1 ms |
| Same datacenter | — | 0.5 ms |
| Same region (cross-AZ) | — | 1–2 ms |
| Dhaka ↔ Singapore | ~15 ms | 40–60 ms |
| London ↔ New York | ~28 ms | 70–90 ms |
| London ↔ Sydney | ~85 ms | 250–300 ms |

> **You cannot optimise your way past the speed of light.** If your users are in Sydney and your servers are in Frankfurt, every round trip costs ~280 ms. The only fixes are: fewer round trips, or servers closer to users.

### Reducing round trips is the highest-leverage optimisation

```
BAD: 8 sequential API calls to render a screen
     8 × 280 ms = 2.24 SECONDS of pure network

GOOD: 1 aggregated call (a BFF, Chapter 08)
     1 × 280 ms = 280 ms
```

| Technique | Effect |
|-----------|--------|
| **CDN / edge** | Move content nearer the user — the biggest single win |
| **Batch / aggregate endpoints** | Fewer round trips |
| **Connection reuse** | Skip the handshakes |
| **HTTP/2 or /3** | Parallel streams on one connection |
| **Compression (Brotli/gzip)** | Fewer bytes, fewer round trips on slow-start |
| **Prefetch / preconnect** | Warm the connection before it is needed |
| **Regional deployment** | Move the *compute* nearer, not just the content |

### Bandwidth vs latency — a distinction people confuse

**Bandwidth** is how wide the pipe is. **Latency** is how long the pipe is.

Adding bandwidth does **not** make a small request faster. A 1 KB API call takes the same time on a 10 Mbps connection as on a 1 Gbps one — it is latency-bound. Bandwidth matters for large transfers (video, file uploads, bulk data).

**Cloud egress costs are a real architectural constraint:** typically ~$0.05–0.09/GB leaving the cloud, and cross-region/cross-AZ traffic is charged too. A chatty cross-AZ service mesh can cost more than the compute. **Keep traffic within an AZ where you safely can**, use VPC endpoints instead of NAT, and put a CDN in front of anything high-volume.

---

## 13.11 Debugging network problems 🟢

The tools, in the order you should reach for them:

```bash
# 1. Does the name resolve, and to what?
dig app.example.com +short
dig app.example.com @1.1.1.1          # bypass the local resolver
dig -x 93.184.216.34                  # reverse lookup

# 2. Can I reach the host at all, and how far do packets get?
ping app.example.com
mtr app.example.com                   # traceroute + ping combined — the best tool here
traceroute app.example.com

# 3. Is the port open?
nc -zv app.example.com 443
telnet app.example.com 443

# 4. What is the TLS situation?
openssl s_client -connect app.example.com:443 -servername app.example.com -showcerts
echo | openssl s_client -connect app.example.com:443 2>/dev/null | openssl x509 -noout -dates

# 5. What is the full HTTP timing breakdown?  ← THE ONE TO MEMORISE
curl -w "@curl-format.txt" -o /dev/null -s https://app.example.com

# 6. What connections does this machine actually have?
ss -tanp | head -50
ss -s                                  # summary: how many in TIME_WAIT?

# 7. What is on the wire?
tcpdump -i any -n port 5432 -w capture.pcap
```

```
# curl-format.txt — put this in your dotfiles today
     time_namelookup:  %{time_namelookup}s\n
        time_connect:  %{time_connect}s\n
     time_appconnect:  %{time_appconnect}s\n      (TLS handshake complete)
    time_pretransfer:  %{time_pretransfer}s\n
       time_redirect:  %{time_redirect}s\n
  time_starttransfer:  %{time_starttransfer}s\n   (server thinking time)
                       ----------\n
          time_total:  %{time_total}s\n
```

**Reading it:**

| Large value | Means |
|-------------|-------|
| `time_namelookup` | DNS is slow — bad resolver, or container DNS config |
| `time_connect − time_namelookup` | Network RTT / TCP handshake — distance or packet loss |
| `time_appconnect − time_connect` | TLS handshake — old TLS version, big cert chain, or an OCSP stall |
| `time_starttransfer − time_pretransfer` | **Your server is slow.** This is the application's thinking time. |
| `time_total − time_starttransfer` | Response body transfer — payload too big, or bandwidth-limited |

> **This single command tells you which of the eleven steps in §13.1 is the problem.** It converts "the site is slow" into a specific, actionable finding in ten seconds.

---

## 13.12 Common mistakes

1. **No timeouts on network calls** — see Chapter 05; it is the most common cascading-failure cause
2. **Creating a new HTTP client/connection per request** — handshake cost and port exhaustion
3. **Databases reachable from the internet** — the classic breach
4. **Expired TLS certificates** — entirely preventable, still happens constantly
5. **Missing intermediate certificate** — works in your browser, fails everywhere else
6. **DNS TTL not lowered before a migration** — the "5 minute" change takes a day
7. **IP-based rate limiting** — punishes everyone behind one NAT or mobile carrier
8. **Chatty cross-region calls** — 8 sequential calls × 280 ms
9. **HTTP/2 with an L4 load balancer** — all streams pinned to one backend, one pod melts
10. **Overlapping CIDR ranges** — discovered on the day you try to peer or VPN
11. **Default-allow network policies in Kubernetes** — every pod can reach every pod and every database
12. **NAT gateway data charges** — a surprising line item; use VPC endpoints
13. **Assuming the internal network is secure** — fallacy #4 (Chapter 05); use mTLS
14. **`ndots:5` DNS latency in containers** — mysterious extra tens of milliseconds on every call

---

## 13.13 Architect's checklist

- [ ] VPC CIDR planned with room to grow; no overlaps with peers or on-prem
- [ ] Three tiers: public (LB only), private app, private data
- [ ] Databases and caches unreachable from the internet; admin access via bastion/SSM/VPN
- [ ] Default-deny security groups and network policies; egress restricted too
- [ ] TLS 1.3, HSTS, strong ciphers; 1.0/1.1 disabled
- [ ] **Every** certificate inventoried, auto-renewed, and alerted at 30/14/7 days
- [ ] Full chain (including intermediates) served and verified outside a browser
- [ ] HTTP/2 or /3 enabled at the edge; L7 load balancing for gRPC/HTTP2
- [ ] Connection pooling and keep-alive everywhere; no per-request clients
- [ ] DNS TTLs appropriate; lowered ahead of planned migrations
- [ ] CAA records set; domain auto-renewal enabled and owned by someone
- [ ] CDN in front of public traffic, even if mostly dynamic
- [ ] Round trips per user action counted and minimised; aggregation where needed
- [ ] Cross-AZ / cross-region / NAT data costs understood; VPC endpoints used
- [ ] PrivateLink considered for vendor and customer connectivity
- [ ] `curl -w` timing breakdown is a standard part of the on-call runbook

---

## 13.14 Self-test

1. Draw the eleven steps a request takes from browser to database. Where does each add latency?
2. `10.0.0.0/16` — how many addresses? What about `/24` and `/28`?
3. Why must databases be in a private subnet, and what does "private" actually mean?
4. Why is the first request to a server slower than the second? Quantify it.
5. Why does IP-based rate limiting hurt legitimate users? What is the fix?
6. Explain the DNS TTL rule before a migration, and why it is 24–48 hours.
7. Why does HTTP/2 misbehave behind an L4 load balancer?
8. What problem does HTTP/3 solve that HTTP/2 cannot?
9. Forward proxy vs reverse proxy vs load balancer vs API gateway — one line each.
10. Stateful vs stateless firewall rules — what bug does the difference cause?
11. What is PrivateLink and why does it matter for a B2B product?
12. Your API takes 2 seconds. `curl -w` shows `time_starttransfer` at 1.9 s. What have you learned, and what have you ruled out?
13. Why can you not "optimise" a 280 ms Sydney-to-Frankfurt round trip away? What are your only two options?
14. Name four things that make cloud network costs surprisingly high.

---

## 13.15 Key takeaways

- **Know the eleven steps** from browser to database; every latency problem lives on one of them
- **Private subnets for data, public only for load balancers.** Default deny, both directions.
- **Connection reuse is one of the biggest free wins** — handshakes cost 100+ ms across regions
- **Certificate expiry is a top self-inflicted outage.** Automate and alert on every certificate.
- **DNS is a hint, not a guarantee** — lower TTLs before migrations, and prefer Anycast for global failover
- **TLS 1.3 + HTTP/2 or /3 + a CDN** is the modern baseline, even for dynamic APIs
- **Latency is physics.** Reduce round trips or move the compute; there is no third option.
- **Bandwidth ≠ latency.** A bigger pipe does not make a small request faster.
- **`curl -w` with a timing format turns "it's slow" into a specific finding in ten seconds**
- **The internal network is not secure** — encrypt it, restrict it, and restrict egress too

---

**Next:** [Chapter 14 — Cloud Architecture](14-cloud-architecture.md)
