# Chapter 4 — Anatomy of a Request: Browser to Database, Every Layer Explained

---

## 1. Why This Matters

This is the map chapter. Everything in Chapters 1–3 was a building block; here we assemble
them into the single most important object of study in web and cloud security: **one HTTPS
request, from a user typing a URL to a row coming back from PostgreSQL, with every layer and
every security control named.**

Why build the whole map now, before you know the details of any single layer? Because the
recurring failure of security learning is topic isolation. People learn "TLS" and "SQL
injection" and "IAM" as separate subjects and never see that they are *stops on one journey*.
When you understand the journey, every later chapter has a place to attach. When Chapter 28
teaches TLS in byte-level detail, you will already know exactly where TLS sits, what it
protects, and what it hands off to the next layer. When Chapter 46 teaches SQL injection, you
will already know that the query text is a string on a socket (you saw it in Chapter 2 §6.3)
and that the vulnerability is a confusion between two of the layers on this map.

The map also teaches the single most valuable analytical habit in this profession:
**for any security question, identify which layer it lives at, and therefore which controls
can possibly address it.** "Can a WAF stop this?" "Would a security group have helped?"
"Where should authentication happen?" — all of these are answerable in seconds once you can
place the threat on the map. A control at layer N cannot see what happens at layer N+2.

We will trace the request twice: once as System A (the VPS stack) and once as System B
(the AWS stack), because the *layers* stay constant while the *enforcing components* move —
the lesson established in Chapter 3 §7, now made concrete end to end.

---

## 2. Prerequisites

- Chapters 1–3 in full. This chapter is a synthesis; it assumes the address space, the
  syscall boundary, and the socket model.
- You have used browser devtools' Network tab and seen request/response headers.
- You do not yet need TCP, TLS, DNS, or HTTP internals — this chapter places them; Part 1
  fills them in. Where a detail is deferred, the forward reference is explicit.

---

## 3. Mental Model

**A request is a stack of envelopes, opened one at a time, and a stack of trust decisions,
made one at a time.**

Two complementary pictures. First, the *layering* — each layer wraps the one above and is
unwrapped in order:

```
   What the user thinks:  "show me my account balance"
        |
   HTTP layer:            GET /api/accounts/42  + headers + cookies/token
        |  wrapped in
   TLS layer:             encrypted, integrity-protected bytes
        |  wrapped in
   TCP layer:             ordered, reliable byte stream on a port (segments)
        |  wrapped in
   IP layer:              packets addressed host-to-host
        |  wrapped in
   Ethernet/link layer:   frames addressed hop-to-hop (MAC)
        |
   Physical:              bits on copper / fiber / radio
```

Second, the *trust boundaries* — each arrow crosses a boundary where identity and
authorization can (and often must) be checked:

```
  [user] --> [browser] --> [DNS] --> [network] --> [edge/proxy] --> [app] --> [data store]
     ^           ^            ^           ^              ^             ^            ^
   who?      same-origin   integrity   confidential   TLS term,    authN/authZ  least-priv
             policy        of name     & reachability WAF, rate     of the       DB creds,
                                                       limit        actual user  row-level
```

The two pictures are the same journey seen two ways: the first is what the *packet* looks
like, the second is where the *decisions* happen. A complete security engineer holds both
simultaneously — "where is this in the envelope stack?" and "which trust boundary is this
crossing?" — and this chapter's goal is to make that dual view automatic.

**The one rule that governs everything below:** *a layer can only enforce controls on what
it can see.* TLS sees encrypted bytes, so it cannot filter by URL. A security group sees IP
and port, so it cannot block a SQL injection payload. A WAF sees the HTTP text, so it can —
but only if TLS was terminated first so the WAF can read it. Every "can control X stop
threat Y?" question reduces to "does X's layer see Y?"

---

## 4. Fundamentals: The Journey, Stop by Stop

We will follow `https://app.ledger.example/api/accounts/42` requested by a logged-in user's
browser. Each stop gets: what happens, what the data looks like, and the security control
available *at that stop*.

### Stop 0 — The browser, before any network

Before a single packet leaves, the browser has already made security decisions:

- **The same-origin policy (SOP)** governs what script on the page may do. An origin is the
  triple `(scheme, host, port)` — `https://app.ledger.example:443`. Script from this origin
  may read responses from this origin; cross-origin reads are blocked unless CORS permits
  them (Chapter 59). This is the browser's foundational isolation model and the reason XSS
  (Chapter 48) is so damaging: XSS runs *inside* the origin, so SOP no longer protects you.
- **Cookie scoping**: the browser decides which cookies to attach based on domain, path,
  `Secure`, `SameSite`, and `HttpOnly` attributes (Chapter 49). The `SameSite` decision
  happens here, before the request is sent, and is the primary CSRF defense.
- **HSTS**: if the site previously sent `Strict-Transport-Security`, the browser upgrades
  `http://` to `https://` *before* connecting, refusing to speak plaintext at all (Chapter
  28). This closes the initial-plaintext-request window that SSL-stripping attacks exploit.
- **CSP**: a previously delivered Content-Security-Policy constrains which scripts may run,
  which is enforced as the page executes (Chapter 48).

**Security control at Stop 0:** the browser is a policy enforcement point you configure
*from the server* via headers. You do not control the user's browser, but you control the
headers that program its behavior. This is why "secure headers" (Chapter 59) are a real
control and not decoration — they reach across the network and configure the enforcement
point closest to the user.

### Stop 1 — DNS resolution: turning a name into an address

The browser needs the IP for `app.ledger.example`. It asks a resolver (Chapter 16 in depth):

```
browser -> OS stub resolver -> recursive resolver -> root -> .example -> ledger.example
        <- 203.0.113.10 (an A record), TTL 60
```

What the data looks like — a DNS query and answer (simplified):

```
Query:  app.ledger.example  IN  A
Answer: app.ledger.example  60  IN  A  203.0.113.10
```

Security realities at this stop, each a full chapter later:

- **DNS is trust-critical and historically unauthenticated.** If an attacker answers first
  (cache poisoning, Chapter 17) or controls the resolver, the browser connects to the
  attacker's IP. TLS then becomes the backstop — the attacker's server cannot present a valid
  certificate for `app.ledger.example` (Stop 4), so DNS spoofing alone does not defeat HTTPS.
  This handoff — "DNS integrity is weak, so TLS must catch the lie" — is a perfect example of
  layered defense across the map.
- **DNS is an exfiltration and C2 channel** (Chapter 17): queries leave most networks freely,
  so data encoded in subdomain labels tunnels out. This is why DNS query logging (Chapter 82)
  is a detection surface.
- **In the cloud, DNS resolves the metadata service and internal service names**, which is
  why DNS rebinding turns SSRF into internal access (Chapters 3 §Solutions 3.12, 50).

**Security control at Stop 1:** DNSSEC (integrity of the answer), DoH/DoT (confidentiality of
the query), resolver choice and egress restriction, and query logging. Note what DNS *cannot*
do: it does not authenticate the server — that is TLS's job. Keep the responsibilities
separate.

### Stop 2 — Routing and the network path: getting packets there

The browser now opens a TCP connection to `203.0.113.10:443` (Chapter 3 §4.5). The packets
traverse: the local network (ARP to find the gateway's MAC, Chapter 9), the default gateway,
the ISP, the internet backbone, and finally the destination network. At each router, the
IP destination is examined and the packet is forwarded toward it (Chapter 12).

What the data looks like at this layer — the IP + TCP headers wrapping the (still
unestablished) connection:

```
IP:   src=198.51.100.7  dst=203.0.113.10  proto=TCP  TTL=64
TCP:  src port=51844     dst port=443      flags=SYN   seq=...
```

Security realities:

- **The network path is untrusted.** Any router, ISP, or Wi-Fi access point on the path can
  observe and tamper with packets — the reason TLS exists (Stop 4). This is the "assume the
  network is hostile" premise of Zero Trust (Chapter 43).
- **Reachability is controlled here** by firewalls, security groups, and NACLs, all of which
  operate on the IP/TCP headers — source/destination IP, port, protocol (Chapters 3, 76).
  This layer can say "packets from this CIDR to port 443 are allowed" and nothing more
  granular, because IP and port are all it sees.
- **DDoS happens here and below** (volumetric floods, SYN floods — Chapter 19), which is why
  edge/CDN scrubbing (Chapter 85) sits in front.

**Security control at Stop 2:** firewalls / security groups / NACLs (packet-level
allow/deny), anti-DDoS at the edge, and network segmentation. What this layer *cannot* do:
see the URL, the user, the cookie, or the SQL. All of that is encrypted inside TLS or is at a
higher layer. A security group is a coarse but powerful control precisely because it is early
and simple.

### Stop 3 — TCP: establishing a reliable channel

Before any HTTP or TLS, TCP performs its three-way handshake (Chapter 19 in full):

```
browser -> SYN            -> server
browser <- SYN-ACK        <- server
browser -> ACK            -> server        now ESTABLISHED (a 4-tuple, Chapter 3)
```

Security realities:

- **The handshake is a resource commitment**, and the SYN backlog is finite — the SYN flood
  attack and SYN cookies live here (Chapter 19).
- **TCP itself provides no confidentiality or authenticity.** Sequence numbers provide *some*
  resistance to blind injection, but an on-path attacker can inject or reset connections
  (RST attacks). Everything meaningful is deferred to TLS.

**Security control at Stop 3:** SYN cookies, connection rate limiting, and timeouts (the
resource-exhaustion defenses from Chapter 3 §5). TCP is plumbing; it does not authenticate.

### Stop 4 — TLS: making the channel confidential and authenticated

Now the crucial handoff. Over the established TCP connection, the browser and server perform
the TLS handshake (Chapter 28, byte by byte). Three things are accomplished:

1. **Authentication of the server.** The server presents an X.509 certificate for
   `app.ledger.example`, signed by a CA the browser trusts (Chapter 27, PKI). The browser
   verifies the chain, the name match, the validity dates, and revocation. *This is where the
   DNS lie from Stop 1 gets caught*: an attacker who spoofed DNS cannot produce a valid
   certificate for the real name.
2. **Key agreement.** Browser and server derive a shared symmetric key via an ephemeral
   key exchange (ECDHE), giving **forward secrecy** — capturing the traffic and later
   stealing the server's key does not decrypt past sessions (Chapters 26, 28).
3. **A confidential, integrity-protected channel.** From here, everything is encrypted with
   authenticated encryption (AEAD). An on-path attacker sees only ciphertext and cannot
   modify it undetected.

What the data looks like — the one part still visible to the network in TLS 1.3 is the
**SNI** (the hostname, sent so the server knows which certificate to present) and the
handshake framing; the application data is opaque:

```
TLS record:  type=application_data  version=TLS1.3  length=517  [encrypted payload]
```

Security realities and the critical architectural point:

- **TLS protects data *in transit* between two endpoints. It says nothing about what happens
  at the endpoints.** Once TLS terminates, the data is plaintext again. *Where* TLS
  terminates is therefore an architectural security decision (Stop 5).
- **SNI leaks the hostname** (Encrypted Client Hello, Chapter 28, is the emerging fix), which
  is why "we use HTTPS" does not mean "the network cannot see which sites you visit."
- **mTLS** (mutual TLS) adds *client* authentication with a client certificate — the basis of
  service-to-service authentication (Chapter 64) and Zero Trust workload identity.

**Security control at Stop 4:** the entire confidentiality/authenticity guarantee of the
request. Also: certificate management, cipher suite policy, TLS version enforcement, and mTLS
for internal hops. This is the layer that makes the untrusted network (Stop 2) survivable.

### Stop 5 — The edge / reverse proxy: the first application-aware point

The TLS connection terminates at the edge — Nginx (System A) or CloudFront + ALB (System B).
**This is the first point on the journey that can see the actual HTTP request**, because it
is the first point after TLS decryption. That single fact makes the edge the natural home for
a cluster of controls:

```
Now visible for the first time (plaintext HTTP):
  GET /api/accounts/42 HTTP/2
  Host: app.ledger.example
  Authorization: Bearer eyJhbGci...        <-- the user's token
  Cookie: session=...
  User-Agent: Mozilla/5.0 ...
  X-Forwarded-For: 198.51.100.7
```

Controls that live here because the HTTP text is finally readable:

- **WAF** (Chapter 85): inspect the URL, headers, and body for injection/attack patterns.
  A WAF *must* sit after TLS termination — it cannot inspect ciphertext. This is why "WAF
  before TLS termination" is a category error.
- **Rate limiting and bot management**: keyed on IP, path, or token.
- **TLS re-origination**: the edge may open a *new* TLS connection to the backend (System B:
  CloudFront→ALB→ECS can be TLS at each hop) or speak plaintext on a trusted private network.
  This choice is the "east-west encryption" decision of Chapter 86.
- **Header sanitization**: stripping or setting `X-Forwarded-For`, removing hop-by-hop
  headers, adding security response headers. Getting `X-Forwarded-For` handling wrong is a
  common source of IP-spoofing and rate-limit-bypass bugs.
- **Request normalization**: and here lives a subtle, serious risk — if the edge and the
  backend *disagree* about how to parse the request (where the body ends, how headers are
  framed), you get **HTTP request smuggling** (Chapter 57). The map makes clear why: two
  layers parsing the same bytes differently is a confusion between layers, the same root
  cause as injection.

**Security control at Stop 5:** WAF, rate limiting, TLS termination policy, header hygiene,
and the request-parsing consistency that prevents smuggling. This is the "minimized,
hardened, internet-facing component" from Chapters 1 §12, 2 §7, and 3 §12 — the front door.

### Stop 6 — The application: authentication and authorization

The proxy forwards to the application — Kestrel/ASP.NET Core (Chapter 3 §7). The request now
enters the middleware pipeline, which is where the request finally meets *identity and
business logic*:

```
Kestrel receives -> ASP.NET Core middleware pipeline:
   1. Exception handling / logging
   2. HSTS / HTTPS redirection
   3. Routing:            which endpoint is GET /api/accounts/{id} ?
   4. AUTHENTICATION:     validate the Bearer token -> establish WHO this is
   5. AUTHORIZATION:      may THIS user access account 42 ?
   6. Model binding / validation
   7. The endpoint handler (business logic)
```

Two distinct decisions, constantly confused, that this map keeps separate:

- **Authentication (Stop 6, step 4): who are you?** The `Authorization: Bearer <JWT>` header
  is validated — signature checked against the issuer's key, expiry checked, audience checked
  (Chapters 60–61). This establishes the *identity* (a set of claims). It does *not* decide
  what they may do.
- **Authorization (Stop 6, step 5): may you do this?** Given the identity, may this user read
  account 42? This is where **broken access control** — IDOR/BOLA (Chapter 51) — lives, and
  it is the #1 web vulnerability class. The map shows why it is so common: authentication is
  centralized and easy to get right (validate the token), but authorization is *per-resource*
  and must be enforced at the business-logic layer with knowledge of ownership. The network,
  the edge, and the token validator cannot make this decision — only code that knows "account
  42 belongs to user X" can.

This is the single most important boundary on the entire map for an application security
engineer, so state it precisely: **authentication happens at a layer that sees the token;
authorization happens at the layer that knows the data model.** They are different layers,
and conflating them ("the token is valid, so let them in") is exactly the IDOR bug.

**Security control at Stop 6:** authentication (token/session validation), authorization
(per-resource access control), input validation, output encoding, and the secure-by-default
framework configuration of Chapter 58. Everything the WAF at Stop 5 might catch as a *pattern*
must be *actually prevented* here — the WAF is a filter on the request; the app is the
enforcement at the resource (Chapter 2 §5.4 principle, restated).

### Stop 7 — The data layer: the query and least privilege

The handler needs account 42. It builds a query and sends it to PostgreSQL over the socket
from Chapter 2 §6.3:

```
Q  SELECT id, balance, owner_id FROM accounts WHERE id = $1     [$1 = 42]
```

The single most important detail on the whole map, and the reason to have built it: **that
query travels to PostgreSQL as a string on a socket, and PostgreSQL executes whatever string
it receives.** PostgreSQL cannot know which bytes the developer intended as structure and
which came from the user. The security of this stop rests entirely on keeping user data *out*
of the query structure:

- **Parameterized queries** (the `$1` above) send the query text and the parameter values
  *separately*, so `42` can never become SQL syntax no matter what it contains. This is SQL
  injection prevention at its root (Chapter 46), and the map shows exactly why it works: it
  refuses to let data from Stop 6 become structure at Stop 7. Injection, universally, is
  *data from one layer being interpreted as instructions by the next* — you will see the
  identical shape in command injection (Chapter 53), XSS (Chapter 48, data becomes script),
  and prompt injection (Chapter 136, data becomes instruction).

Beyond injection, the data layer has its own controls:

- **Database credentials with least privilege** (Chapter 6, 68): the app's DB user should be
  able to touch only the tables it needs, with only the operations it needs — so that a SQL
  injection or logic bug has a bounded blast radius. If the app connects as a superuser, a
  single injection is total compromise; if it connects as a user restricted to five tables
  with no DDL, the same injection is far less catastrophic. This is the isolation ladder
  (Chapter 1 §5.4) applied to database privilege.
- **Encryption at rest** (Chapter 1 §4.6): protects the disk/snapshot, and nothing about
  this live query — say it precisely.
- **Row-level security and tenant isolation** (Chapter 51): enforced here as a backstop to
  the application's authorization check at Stop 6.

**Security control at Stop 7:** parameterized queries, least-privilege DB credentials,
network isolation of the database (Chapter 3 §7), encryption, auditing, and row-level
security. This is the last line; controls here bound the damage when the layers above fail.

### The response, and the journey back

The row returns, the handler serializes it to JSON, and the response travels back up the
stack: through the app (where output encoding and *not leaking too much data* matter — an
over-broad SELECT or a serializer that includes `owner_id` and internal fields is an
information-disclosure bug), through the edge (which adds security response headers), through
TLS (re-encrypted), across the network, and into the browser (where SOP, CSP, and cookie
handling govern what the page may do with it). The controls are symmetric: what you enforce
on the way in, you must also consider on the way out.

---

## 5. Deep Technical Explanation: The Complete Map

Here is the whole journey in one diagram, with the security control at each layer. Print this;
it is the table of contents for the rest of the book.

```
 LAYER / STOP            WHAT IT SEES               SECURITY CONTROL              CHAPTER
 ---------------------   -----------------------    ---------------------------   -------
 0  Browser              the DOM, origins           SOP, CSP, HSTS, cookie        48,49,59
                                                    attributes, SRI
 1  DNS                  hostnames                  DNSSEC, DoH/DoT, query log,   16,17
                                                    egress restriction
 2  IP / routing         src/dst IP, protocol       firewall, SG, NACL,           12,76,85
                                                    anti-DDoS, segmentation
 3  TCP                  ports, connection state    SYN cookies, rate limit,      19,21
                                                    conn/timeout limits
 4  TLS                  encrypted bytes + SNI      cert validation, cipher/      27,28
                                                    version policy, mTLS, FS
 5  Edge / proxy         full HTTP (post-decrypt)   WAF, rate limit, header       57,85
                                                    hygiene, smuggling defense
 6  Application          identity + business ctx    authN, authZ (IDOR!), input   51,58,60
                                                    validation, output encoding      61
 7  Data store           the query string + data    parameterized queries,        46,68
                                                    least-priv creds, RLS, encrypt
```

Read the "WHAT IT SEES" column top to bottom and the entire logic of layered security falls
out: **each layer sees more application meaning than the one below it, and less network detail
than the one above it.** A control can only act on what its layer sees. Therefore:

- You cannot fix authorization (needs Stop 6's business context) with a firewall (Stop 2).
- You cannot fix SQL injection (Stop 7's data/structure confusion) with a WAF (Stop 5) — a
  WAF *pattern-matches* and helps, but the WAF cannot know your schema, so it produces false
  positives and misses novel payloads. It is a filter, not the fix.
- You cannot inspect for attacks with a WAF (Stop 5) if TLS (Stop 4) has not been terminated
  first — you would be pattern-matching ciphertext.
- You cannot rely on the browser (Stop 0) for security decisions, because the attacker
  controls their own browser — browser controls protect the *user*, server controls protect
  the *system*.

This "which layer sees what" table is, genuinely, the mental model that separates engineers
who can reason about security architecture from those who apply controls by checklist.

### 5.1 Defense in depth, read off the map

Take one real attack and watch it meet every layer — this is defense in depth made concrete
rather than sloganized. An attacker tries to read another user's account via IDOR
(`GET /api/accounts/43` when they own 42):

| Layer | Does it stop the attack? | Why / why not |
|---|---|---|
| 0 Browser | No | The attacker uses their own tool; SOP is irrelevant to them |
| 1 DNS | No | Legitimate name resolution |
| 2 IP/SG | No | Legitimate source, legitimate port |
| 3 TCP | No | Normal connection |
| 4 TLS | No | Valid client, valid session (they are a real user!) |
| 5 WAF | Maybe | Only if a rule spots the pattern — unreliable; 43 looks like 42 |
| 6 App authZ | **YES** | The ownership check: "does user own account 43?" → no → 403 |
| 7 DB (RLS) | **YES (backstop)** | Row-level security scoped to the tenant returns nothing |

The attack is authorized-user abuse, so it sails through every network and transport control —
those layers cannot see the *authorization* question. It is stopped only where the business
context exists (Stop 6), with the data layer (Stop 7) as a backstop. This is why "we have a
firewall and HTTPS" is not application security, and why the map is worth internalizing:
**it tells you which threats your existing controls categorically cannot address.**

---

## 6. Internals: Watching a Real Request Cross the Layers

You can observe several of these stops directly. Do so — seeing the layers is different from
reading about them.

### 6.1 DNS (Stop 1)

```bash
$ dig +norecurse app.ledger.example        # what a resolver returns
$ dig +trace app.ledger.example            # watch delegation from root down
```

### 6.2 TCP + TLS (Stops 3–4)

```bash
$ curl -v --trace-time https://example.com/ 2>&1 | grep -E '^\* |^> |^< ' | head -40
```

You will see, in order: the TCP connect, the TLS handshake (`* SSL connection using
TLSv1.3`), the certificate details (`* subject:`, `* issuer:`, validity), then the HTTP
request (`>`) and response (`<`). That single command walks Stops 3 through 5 in front of
you. Add `openssl s_client -connect example.com:443 -servername example.com` to inspect the
certificate chain (Stop 4) in detail.

### 6.3 The layers on the wire (Stops 2–4)

```bash
$ sudo tcpdump -n -i any 'host example.com and tcp port 443' -c 20
```

You will see the SYN / SYN-ACK / ACK (Stop 3), then TLS handshake records, then encrypted
`application_data` — and you will *not* see the URL, because it is inside TLS. That absence
is the point: it demonstrates exactly what Stop 2's controls (and any network eavesdropper)
can and cannot see. Chapter 24 makes this a full workshop.

### 6.4 The application pipeline (Stop 6)

In ASP.NET Core, the middleware order *is* the security order. A minimal, correctly-ordered
pipeline:

```csharp
var app = builder.Build();
app.UseExceptionHandler("/error");   // catch-all first, so errors never leak stack traces
app.UseHsts();
app.UseHttpsRedirection();
app.UseRouting();                    // decide the endpoint
app.UseAuthentication();             // Stop 6.4: establish WHO (validate the token)
app.UseAuthorization();              // Stop 6.5: decide MAY THEY (per-endpoint/resource)
app.MapControllers();                // Stop 6.7: business logic
app.Run();
```

Order matters and is a real source of bugs: `UseAuthorization` before `UseAuthentication`
means authorization runs with no established identity; putting middleware after
`MapControllers` means it never runs for those endpoints. Chapter 58 dwells on this; here,
notice that the framework pipeline is literally the trust-boundary sequence from §3, made
executable.

### 6.5 The query (Stop 7)

```bash
# Turn on statement logging in PostgreSQL and watch what actually arrives:
$ psql -c "ALTER SYSTEM SET log_statement = 'all';" && sudo systemctl reload postgresql
$ sudo tail -f /var/log/postgresql/postgresql-*.log
# then issue a request through the app and watch the query appear
```

You will see either a parameterized statement (`SELECT ... WHERE id = $1` with parameters
logged separately — safe) or a fully-interpolated string (`SELECT ... WHERE id = 42` with the
value baked in — a warning sign that user input might be reaching the query as structure).
This log is where you *prove* whether your app parameterizes, and it is the first thing to
check when triaging a suspected injection.

---

## 7. Real-World Example: The Same Request, Two Architectures

The layers are invariant; the components change. Side by side:

```
 STOP   SYSTEM A (VPS)                    SYSTEM B (AWS)
 ----   ------------------------------    ------------------------------------------
 1 DNS  server's resolver / registrar     Route 53 (+ Resolver, query logging)
 2 IP   iptables/nftables on the VPS       Security Groups + NACLs + AWS Shield
 3 TCP  Linux TCP stack                    ALB / NLB TCP handling
 4 TLS  Nginx terminates TLS               CloudFront and/or ALB terminates TLS (ACM certs)
 5 Edge Nginx (WAF via modsecurity)        CloudFront + AWS WAF
 6 App  Kestrel/ASP.NET on the VPS         ECS Fargate task (ASP.NET), private subnet
 7 Data local PostgreSQL (loopback)        RDS PostgreSQL, private subnet, SG-restricted
```

The instructive part is *what provides each security property* in each:

- **"The database is not internet-reachable."** System A: PostgreSQL bound to loopback
  (Chapter 3 §7). System B: RDS in a private subnet with a security group allowing only the
  ECS tasks' SG. Same property, different mechanism — and in a review you must name which one
  applies.
- **"Attacks are filtered before the app."** System A: Nginx + ModSecurity. System B:
  CloudFront + AWS WAF. Same layer (Stop 5), different product.
- **"TLS terminates at a controlled point."** System A: one point, Nginx. System B: possibly
  two (CloudFront edge, then ALB), which means you must decide whether the CloudFront→ALB and
  ALB→ECS hops are also encrypted (Chapter 86) — a decision System A did not have to make
  because there was no network between Nginx and Kestrel (loopback).
- **"The app has an identity to reach the database."** System A: a DB password in config
  (Chapter 68's problem). System B: the same, *or* IAM database authentication where the task
  role gets a short-lived token (Chapter 81) — a strictly better answer that only the cloud
  architecture makes available.

This comparison is the entire justification for teaching AWS in depth (Part 7): the cloud
does not change *what* must be protected (the map is identical) — it changes *which component*
enforces each protection, and it offers stronger mechanisms (short-lived identities, managed
TLS, VPC endpoints) for the same properties. Learn the map first; then learn how each cloud
service plugs into it.

---

## 8. Hands-On Demonstration

### LAB 4.1 — Trace One Request Through Every Layer

**Objective.** Take a single HTTPS request through your own running stack and *observe* each
layer of the map with the appropriate tool, producing a per-layer note of what you saw and
what security control lives there.

**Cost.** Free. **Environment.** ENV-3 (dev stack) or ENV-2. **Time.** 60–90 minutes.

**Setup — a two-tier stack you can watch:**

```bash
mkdir -p ~/lab04 && cd ~/lab04
cat > docker-compose.yml <<'EOF'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: labpass
      POSTGRES_DB: ledger
    command: ["postgres", "-c", "log_statement=all", "-c", "log_connections=on"]
    networks: [appnet]
  api:
    image: mcr.microsoft.com/dotnet/sdk:8.0
    working_dir: /src
    volumes: [".:/src"]
    command: bash -c "cd LedgerApi && dotnet run --urls http://0.0.0.0:5000"
    depends_on: [db]
    networks: [appnet]
  proxy:
    image: nginx:1.27
    volumes: ["./nginx.conf:/etc/nginx/conf.d/default.conf:ro", "./certs:/certs:ro"]
    ports: ["8443:8443"]
    depends_on: [api]
    networks: [appnet]
networks: { appnet: {} }
EOF

# Self-signed cert for the lab (Stop 4):
mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -keyout certs/key.pem -out certs/cert.pem -subj "/CN=localhost" >/dev/null 2>&1

cat > nginx.conf <<'EOF'
server {
    listen 8443 ssl;
    ssl_certificate     /certs/cert.pem;
    ssl_certificate_key /certs/key.pem;
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options "nosniff" always;
    location / {
        proxy_pass http://api:5000;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF
```

Create the minimal API (Stops 6–7), deliberately showing both a safe and an unsafe query so
you can watch the difference at Stop 7:

```bash
dotnet new web -o LedgerApi
cat > LedgerApi/Program.cs <<'EOF'
using Npgsql;
var b = WebApplication.CreateBuilder(args);
var app = b.Build();
var cs = "Host=db;Username=postgres;Password=labpass;Database=ledger";

await using (var c = new NpgsqlConnection(cs)) {
    await c.OpenAsync();
    await using var cmd = new NpgsqlCommand(
      "CREATE TABLE IF NOT EXISTS accounts(id int primary key, owner text, balance numeric);" +
      "INSERT INTO accounts VALUES (42,'alice',100),(43,'bob',250) ON CONFLICT DO NOTHING;", c);
    await cmd.ExecuteNonQueryAsync();
}

// Stop 6: no auth here yet — deliberately, so the lab can discuss what's MISSING.
app.MapGet("/api/accounts/{id}", async (int id) => {
    await using var c = new NpgsqlConnection(cs); await c.OpenAsync();
    // SAFE: parameterized (Stop 7 done right)
    await using var cmd = new NpgsqlCommand("SELECT id,owner,balance FROM accounts WHERE id=$1", c);
    cmd.Parameters.AddWithValue(id);
    await using var r = await cmd.ExecuteReaderAsync();
    return await r.ReadAsync()
        ? Results.Ok(new { id = r.GetInt32(0), owner = r.GetString(1), balance = r.GetDecimal(2) })
        : Results.NotFound();
});
app.Run("http://0.0.0.0:5000");
EOF
(cd LedgerApi && dotnet add package Npgsql >/dev/null)
docker compose up -d
sleep 20
```

**Steps — observe each stop:**

*Stop 4–5 (TLS + edge):*
```bash
curl -vk https://localhost:8443/api/accounts/42 2>&1 | grep -E '^\*|^>|^<'
```
Note the `SSL connection using TLSv1.3`, the self-signed cert warning (why `-k` is needed),
and the response headers Nginx added (`Strict-Transport-Security`, `X-Content-Type-Options`).

*Stop 2–4 (packets):*
```bash
sudo tcpdump -n -i any 'tcp port 8443' -c 12
# in another terminal: curl -k https://localhost:8443/api/accounts/42
```
Confirm you see the handshake but not the URL — TLS hides Stop 6 from Stop 2.

*Stop 6 (pipeline / missing authz):*
```bash
curl -sk https://localhost:8443/api/accounts/42 ; echo    # alice's data
curl -sk https://localhost:8443/api/accounts/43 ; echo    # bob's data — ANYONE can read it
```
**This is the finding.** There is no authentication or authorization (Stop 6), so any caller
reads any account — a textbook IDOR/BOLA. Write down: which layer is responsible, and why no
lower layer could have prevented it.

*Stop 7 (the query):*
```bash
docker compose logs db | grep -E 'SELECT|statement:' | tail -5
```
Observe the parameterized statement with the parameter logged separately — Stop 7 done
correctly, so even without auth there is no SQL injection here. Contrast the two findings:
the app is safe against injection (Stop 7) but wide open to access-control abuse (Stop 6).
*Different layers, different bugs, and only the map keeps them straight.*

**Attack scenario.** With no authz, enumerate all accounts: `for i in $(seq 40 50); do curl
-sk https://localhost:8443/api/accounts/$i; echo; done`. This is exactly how BOLA is
exploited at scale (Chapter 51).

**Hardening (preview of Stop 6, built out in Part 5).** Add authentication (validate a Bearer
token) and an authorization check (`account.owner == currentUser`). Re-run the attack and
confirm 401/403.

**Verification.** After adding authz, `curl` without a token → 401; with alice's token to
`/43` → 403; with alice's token to `/42` → 200.

**Cleanup.**
```bash
cd ~/lab04 && docker compose down -v && cd ~ && rm -rf ~/lab04
```

---

## 9. Security Implications

The whole point of this chapter, stated as principles you will reuse in every later part:

1. **A control acts only on what its layer can see.** Place every threat on the map; the
   controls that can possibly address it are those at or above its layer that can observe it.
2. **Authentication and authorization are different layers.** AuthN sees the token; authZ
   knows the data. Conflating them is IDOR/BOLA, the most common serious web bug.
3. **Injection is cross-layer confusion**: data from one layer interpreted as structure by
   the next. Parameterization, output encoding, and safe APIs all work by refusing that
   promotion. This shape recurs in SQLi, command injection, XSS, and prompt injection.
4. **TLS protects transit, not endpoints.** Where it terminates is an architectural decision,
   and every hop after termination is plaintext unless re-encrypted.
5. **The network layers cannot see application meaning**, so "firewall + HTTPS" is
   necessary but nowhere near sufficient — it addresses Stops 2–4 and leaves Stops 5–7 open.
6. **Browser controls protect the user; server controls protect the system.** Never rely on
   the client for a decision the server must make.
7. **Defense in depth = controls at multiple layers so a failure at one is caught by
   another** — read directly off the §5.1 table.

---

## 10. Attack Scenarios (mapped)

Each major attack class in this book, placed on the map so you can see where it lives and
where it must be stopped:

| Attack | Lives at | Stopped at | Chapter |
|---|---|---|---|
| DNS spoofing | Stop 1 | caught at Stop 4 (cert) | 17 |
| Eavesdropping / MITM | Stop 2 | Stop 4 (TLS) | 28 |
| SYN flood / volumetric DDoS | Stops 2–3 | edge scrubbing, SYN cookies | 19, 85 |
| SSL stripping | Stop 1/2 | Stop 0 (HSTS) | 28 |
| SQL injection | Stop 6→7 (data→structure) | Stop 7 (parameterization) | 46 |
| XSS | Stop 0 (data→script) | Stop 6 (encoding) + Stop 0 (CSP) | 48 |
| CSRF | Stop 0 (ambient cookie) | Stop 0 (SameSite) + Stop 6 (token) | 49 |
| SSRF | Stop 6 (app makes a request) | Stop 6 (validate) + Stop 2 (egress/IMDS) | 50 |
| IDOR / BOLA | Stop 6 (authorization) | Stop 6 (authZ) + Stop 7 (RLS) | 51 |
| Request smuggling | Stop 5 (parser disagreement) | Stop 5 (consistent parsing) | 57 |
| Credential theft → data exfil | Stop 6/7 | Stop 7 (least priv) + Stop 2 (egress) | 68 |

Read this table as the syllabus it is: every one of these is a stop on the journey you now
understand, and each later chapter zooms into one row.

---

## 11. Defensive Techniques

The map's prescription is simply: **have a named, appropriate control at every stop, and
know what each one can and cannot do.**

- **Stop 0:** ship HSTS, CSP, `X-Content-Type-Options`, and correct cookie attributes.
- **Stop 1:** controlled resolvers, DNS query logging, DNSSEC where it applies.
- **Stop 2:** default-deny security groups/firewall, network segmentation, egress control,
  anti-DDoS at the edge.
- **Stop 3:** SYN cookies, connection/rate limits, timeouts.
- **Stop 4:** modern TLS only, valid managed certificates, mTLS for internal hops, forward
  secrecy.
- **Stop 5:** WAF (after TLS termination), rate limiting, header hygiene, smuggling-resistant
  proxy configuration.
- **Stop 6:** authentication *and* separate per-resource authorization, input validation,
  output encoding, secure framework defaults, no stack traces to clients.
- **Stop 7:** parameterized queries, least-privilege DB credentials, network isolation,
  encryption, row-level security, audit logging.

The failure mode this list guards against is the most common one in real systems: **a stack
that is strong at Stops 2–4 (because infrastructure teams own them) and weak at Stops 6–7
(because they require application-level work).** The map makes that imbalance visible, which
is the first step to fixing it.

---

## 12. Production Architecture

The complete System B request path, annotated with the control at each hop — the reference
you will return to throughout Parts 7–8:

```
   User's browser  [SOP, CSP, HSTS, cookies]
        |
        v  DNS
   Route 53  [DNSSEC, query logging]
        |
        v
   AWS Shield + CloudFront  [DDoS scrubbing, TLS termination #1, caching]
        |
        v
   AWS WAF  [inspect decrypted HTTP: injection/bot/rate rules]
        |
        v  (private, TLS re-originated)
   ALB  [TLS termination #2, target routing, health checks; SG: 443 from CloudFront prefix]
        |
        v  (private subnet; SG: app port from ALB SG only)
   ECS Fargate task — ASP.NET Core  [authN, authZ, validation; task IAM role; non-root; seccomp]
        |
        v  (private subnet; SG: 5432 from task SG only)
   RDS PostgreSQL  [least-priv DB user or IAM auth; encryption; no public access; RLS]
        |
        +--> Secrets Manager / KMS  [short-lived creds, envelope encryption]
        +--> CloudTrail / CloudWatch / VPC Flow Logs  [audit at every layer]
```

Every arrow is a trust boundary with a named control; every box is minimized to its job.
This diagram is not aspirational — it is the baseline a cloud security engineer is expected to
be able to draw, critique, and defend. By the end of Part 8 you will build it in Terraform
(capstones 5–6); for now, notice that it is *the map of this chapter*, instantiated in AWS.

---

## 13. Common Mistakes

1. **Treating "firewall + HTTPS" as security.** It covers Stops 2–4 and leaves the
   application (Stops 6–7) — where most breaches happen — untouched.
2. **Conflating authentication with authorization.** "The token is valid" is not "they may
   access this resource." → IDOR/BOLA.
3. **Putting a WAF where it cannot read the traffic** (before TLS termination), or trusting a
   WAF as the *fix* for injection rather than a filter.
4. **Terminating TLS and forgetting the hops after it are plaintext.** East-west traffic
   inside the VPC is not automatically encrypted.
5. **Relying on browser-side controls** (hidden fields, client validation, disabled buttons)
   for security decisions.
6. **Over-privileged database credentials**, turning a bounded bug into total compromise.
7. **Mishandling `X-Forwarded-For`** at the edge, enabling IP spoofing and rate-limit bypass.
8. **Leaking data on the way back** — verbose serializers, stack traces, internal fields — the
   response half of the journey, often forgotten.
9. **Not knowing which component enforces which property**, so a migration (VPS→cloud,
   monolith→microservices) silently drops a control that used to be provided by loopback or
   a shared process.

---

## 14. Troubleshooting

| Symptom | Likely layer | Diagnostic |
|---|---|---|
| Cert warning / handshake failure | Stop 4 | `openssl s_client -connect host:443 -servername host`; check chain, dates, name |
| Works over HTTP, fails over HTTPS | Stop 4/5 | proxy TLS config, `curl -v`; check SNI and cert |
| 401 for everyone | Stop 6.4 | token validation config (issuer, audience, signing key); middleware order |
| 403 for the wrong people, or no 403 when expected | Stop 6.5 | authorization logic; is ownership actually checked? |
| Requests reach app but wrong client IP in logs | Stop 5 | `X-Forwarded-For` handling; `ForwardedHeaders` middleware config |
| Random old/new responses after deploy | Stop 5/6 | `SO_REUSEPORT`, draining (Chapter 3 §Solutions 3.8) |
| SQL errors with odd input | Stop 7 | check for string interpolation; enable statement logging |
| Intermittent cross-user data | Stop 6 | shared/static per-request state (Chapter 1 §8, 1.8) |
| Reachable when it should not be | Stop 2 | `ss -tlpn` (bind) + SG/NACL + route (Chapter 3 §14) |

The meta-diagnostic: **place the symptom on the map, then reach for that layer's tool.** A
misplaced diagnosis (debugging the app for what is a TLS problem, or the network for what is
an authorization problem) wastes more time than any actual bug.

---

## 15. Practical Lab

Lab 4.1 is embedded in §8 (it is the natural place for a hands-on trace). Register it in the
lab index. As an extension exercise, repeat the trace against a real public site
(`curl -v https://example.com`) and against System B if you have an AWS account, and produce a
one-page per-layer control inventory for each — this "control inventory" is a deliverable you
will produce for real systems as a cloud security engineer.

---

## 16. Exercises

### Concept questions

**4.1** For each layer of the map, state one thing that layer *can* see and one thing it
*cannot*, and give one security control that consequently belongs there and one that does not.

**4.2** Explain, using the map, why a WAF must sit after TLS termination and why a WAF is a
filter rather than a fix for SQL injection.

**4.3** A colleague says "we don't need application authorization because our API is behind a
firewall and requires login." Refute this precisely using the §5.1 defense-in-depth table.

**4.4** Injection appears in this book as SQLi, command injection, XSS, and prompt injection.
State the single abstract shape common to all four, in terms of the map's layers, and explain
why parameterization/encoding is the general fix.

**4.5** Explain what "TLS protects transit, not endpoints" means for a System B architecture
with CloudFront → ALB → ECS, and what decision it forces on you.

### Debugging problems

**4.6** Users report that after logging in, they occasionally see another user's dashboard
for a split second. The database query logs show only correct, parameterized queries scoped
to the right user ID. Place this on the map and give the three most likely causes ranked.

**4.7** A request works with `curl` directly to the app (`:5000`) but returns 400 through the
proxy (`:8443`). Where on the map is the problem, and what are the two most likely causes?

**4.8** After migrating from the VPS (System A) to AWS (System B), the database — which was
never internet-reachable before — is now found to accept connections from the internet.
Nothing in the application changed. Using §7, explain how this happened and what control was
silently dropped in the migration.

### Security scenarios

**4.9** You are asked to add "a security layer" to an existing app that already has HTTPS and
a firewall. Using the map, identify which stops are likely under-protected and propose the
three highest-value additions, with justification.

**4.10** An incident report says "the attacker exfiltrated the customer table." Walk the map
backward from Stop 7 and enumerate, at each layer, what control *should* have made this harder
and what evidence you would look for that it failed.

### Architecture questions

**4.11** Draw the request map for a mobile app → API → microservices → database architecture.
Where does authentication happen, where does authorization happen, and how does identity
propagate from the edge to an internal service three hops deep? (Preview of Chapters 61, 64.)

**4.12** Design where TLS terminates and re-originates in a System C (Kubernetes + service
mesh) deployment, and justify each termination point against the "TLS protects transit not
endpoints" principle.

### Hands-on exercises

**4.13** Using `curl -v` and `tcpdump`, produce a labeled capture of a single HTTPS request
and annotate each visible element with its map stop. Confirm the URL is not visible on the
wire.

**4.14** Extend Lab 4.1 to add JWT authentication and per-resource authorization, then
re-run the enumeration attack and capture the 401/403 responses as proof.

**4.15** Enable PostgreSQL statement logging on a real app you have and classify every query
as parameterized or interpolated. Report any interpolated queries as findings.

### Interview questions

**4.16** "Walk me through everything that happens, and every security control involved, when a
user loads their account page over HTTPS."

**4.17** "Where does authentication happen versus authorization, and why does that distinction
cause the most common serious web vulnerability?"

**4.18** "A security group and a WAF are both 'firewalls.' Explain the difference in terms of
what each can see and therefore what each can stop."

**4.19** "TLS gives us end-to-end encryption, so we don't need to worry about internal
traffic. Respond."

**4.20** "Given a new architecture diagram, how do you systematically identify what's missing
from a security standpoint?"

---

## 17. Summary

- One HTTPS request is a stack of envelopes (HTTP inside TLS inside TCP inside IP inside
  Ethernet) and a sequence of trust boundaries (user → browser → DNS → network → edge → app →
  data), and mastering security means holding both views at once.
- **Each layer sees more application meaning than the one below and less network detail than
  the one above.** A control can act only on what its layer sees — the single rule from which
  all of layered security follows.
- The seven stops and their controls: **Browser** (SOP/CSP/HSTS/cookies), **DNS**
  (DNSSEC/logging), **IP** (firewall/SG/NACL/DDoS), **TCP** (SYN cookies/limits), **TLS**
  (cert validation/cipher policy/mTLS/forward secrecy), **Edge** (WAF/rate limit/header
  hygiene/smuggling defense), **App** (authN + authZ + validation + encoding), **Data**
  (parameterization + least privilege + RLS + encryption).
- **Authentication (sees the token) and authorization (knows the data) are different layers**;
  conflating them is IDOR/BOLA, the top web vulnerability class.
- **Injection is cross-layer confusion** — data promoted to structure/instructions — and the
  same shape underlies SQLi, command injection, XSS, and prompt injection.
- **TLS protects transit, not endpoints**; where it terminates is an architectural decision,
  and every post-termination hop is plaintext unless re-encrypted.
- **Defense in depth** is controls at multiple layers so a failure at one is caught by
  another; the IDOR walk-through shows exactly which layers can and cannot catch a given
  attack.
- The **layers are invariant across architectures; the enforcing components move** (VPS →
  AWS), and a security engineer must always be able to name *which component provides each
  property* — the skill that prevents controls from being silently dropped in migrations.

---

## 18. Knowledge Check

1. Name the seven stops of the request map and one control at each. (§5)
2. What is the one rule that determines whether a given control can stop a given threat? (§3, §5)
3. Why must a WAF sit after TLS termination? (§4 Stop 5, §5)
4. What is the difference between authentication and authorization, and which vulnerability
   comes from conflating them? (§4 Stop 6)
5. Why does a parameterized query prevent SQL injection, in map terms? (§4 Stop 7, §9)
6. What does "TLS protects transit, not endpoints" force you to decide in a multi-hop
   architecture? (§4 Stop 4, §7)
7. In the IDOR defense-in-depth table, which layers stop the attack and why can't the others? (§5.1)
8. What security property must be provided in *both* System A and System B for the database,
   and by what mechanism in each? (§7)
9. Why are browser-side controls insufficient for server security decisions? (§4 Stop 0, §9)
10. Where does each of SQLi, XSS, CSRF, SSRF, and IDOR live on the map? (§10)

---

## 19. Further Exploration

- Open your browser's devtools Network tab on any site, click a request, and map every field
  you see (headers, cookies, timing, security) to a stop on this chapter's map.
- `curl -v` against ten different sites; note which use HTTP/2 vs HTTP/3, TLS 1.2 vs 1.3, and
  what response headers they set. Build intuition for what "normal" looks like at Stops 4–5.
- Read the OWASP Top 10 once, now, and place each item on the map. You will find nearly all of
  them cluster at Stops 6–7 — which tells you where to spend your learning time.
- Mozilla Observatory (observatory.mozilla.org) grades a site's Stop 0 and Stop 5 headers;
  run it against a site you own and fix the findings.
- Keep the §5 table somewhere visible. For the rest of this book, when you learn a control,
  place it on the table. When you learn an attack, place it too. The map is the index.

---

## Solutions

### 4.1
Examples (one valid set): **Browser** sees the DOM and origins but not the network path;
belongs here: CSP; does not: database access control. **DNS** sees hostnames but not the
request content; belongs: DNSSEC; does not: SQL injection filtering. **IP** sees src/dst IP
and protocol but not the URL or user; belongs: security group; does not: per-user
authorization. **TCP** sees ports and connection state but not payload; belongs: SYN cookies;
does not: cert validation. **TLS** sees encrypted bytes and SNI but not (for an eavesdropper)
the plaintext; belongs: certificate validation; does not: business authorization. **Edge**
sees full HTTP after decryption but not the database schema; belongs: WAF; does not:
row-ownership decisions. **App** sees identity and business context but not lower-layer
network detail; belongs: authorization; does not: DDoS scrubbing. **Data** sees the query and
the data but not who the HTTP user was (only the DB credential); belongs: parameterization
and least privilege; does not: TLS cipher policy.

### 4.2
A WAF inspects the HTTP request text — the URL, headers, and body — to match attack patterns.
That text only exists in plaintext *after* TLS is decrypted, so a WAF placed before TLS
termination would be pattern-matching ciphertext, which is meaningless. Hence WAF must sit at
or after Stop 4's termination (typically Stop 5). It is a *filter*, not a *fix*, for SQL
injection because it lives at Stop 5 and does not know your database schema or which inputs
reach a query as structure; it guesses from patterns, producing false positives (blocking
legitimate input that looks like SQL) and false negatives (missing novel or obfuscated
payloads). The actual fix is at Stop 7 — parameterization — which structurally prevents data
from becoming SQL syntax regardless of content. WAF buys time and blocks commodity attacks;
parameterization eliminates the class.

### 4.3
The firewall operates at Stop 2 and sees only IP/port; "requires login" is authentication at
Stop 6.4. Neither addresses authorization at Stop 6.5. The IDOR/BOLA attack in §5.1 is
performed by a *legitimate, logged-in user* from a *legitimate source IP* over a *valid TLS
session* — so it passes the firewall (legitimate source), passes TLS (valid session), and
passes authentication (they really are logged in). Every layer the colleague cites is blind to
the question "may this authenticated user access *this specific resource*?" Only Stop 6.5
(authorization), with the data layer (RLS) as backstop, can answer it. Their controls address
Stops 2 and 6.4 and leave the single most-exploited web vulnerability class completely open.

### 4.4
The abstract shape: **untrusted data from one layer is passed to the next layer in a channel
that mixes data and instructions, and the receiving layer interprets the data as
instructions/structure.** SQLi: user data (Stop 6) becomes SQL syntax (Stop 7). Command
injection: user data becomes shell syntax (Stop 6→OS). XSS: user data becomes HTML/JS in the
page (Stop 6→Stop 0). Prompt injection: retrieved/user data becomes model instructions
(Chapter 136). The general fix is to keep data and instructions in *separate channels* so the
receiver never has to guess which is which: parameterized queries send SQL and values apart;
`execve` with an argument array (not a shell string) separates command and arguments;
context-aware output encoding marks data as data in HTML; and for LLMs, structural separation
and privilege limits (there is no perfect fix — Chapter 136). Parameterization/encoding works
because it removes the ambiguity the attack depends on.

### 4.5
It means the encryption guarantee ends at each termination point and the data is plaintext in
memory there and on the next hop unless re-encrypted. In CloudFront → ALB → ECS: TLS from the
user terminates at CloudFront (plaintext inside CloudFront), a *new* TLS connection runs
CloudFront → ALB (terminates at ALB, plaintext inside ALB), and you must *decide* whether
ALB → ECS is also TLS. The decision forced on you: are the CloudFront→ALB and ALB→ECS network
segments trusted enough to carry plaintext, or must they be encrypted (east-west encryption,
Chapter 86)? For a VPC you might accept plaintext ALB→ECS within a private subnet given
segmentation and the threat model, or require end-to-end TLS for regulated data. The point is
that "we use HTTPS" does not automatically mean "traffic is encrypted at every internal hop" —
you must name each hop and its encryption status.

### 4.6
This is a Stop 6 problem, not a Stop 7 problem — the queries are correct and scoped, so the
data layer is fine; the wrong data is being *associated with the wrong request/session*.
Ranked causes: (1) **Shared mutable per-request state in the application** — a static or
incorrectly-scoped singleton holding "current user" (e.g. a singleton service capturing
`HttpContext.User`, or a misused `AsyncLocal`), so a concurrent request briefly reads
another's context. Distinguishing evidence: correlates with concurrency; the "other user" was
active at the same instant. (2) **A caching layer keyed without the user/tenant** — a
dashboard cached in Redis under a key missing the user id, so user B gets user A's cached
render. Distinguishing evidence: repeatable per key, only on cacheable responses, cleared by
flushing the cache. (3) **Reverse-proxy/response buffer reuse or a connection-reuse bug** at
Stop 5 mixing responses between connections. Distinguishing evidence: correlates with the
proxy, seen as whole-response swaps. All three are the "threads/handlers share the process"
lesson (Chapter 1 §5.4); none are visible in the DB logs, which is the clue that it is above
Stop 7.

### 4.7
The problem is at Stop 5 (the edge/proxy) — the request succeeds directly to the app but
fails through the proxy, so the proxy is transforming the request into something the app
rejects (400 = bad request). Two most likely causes: (1) **Header handling** — the proxy is
adding/modifying headers (a malformed `X-Forwarded-For`, a duplicated `Host`, an oversized
header) or forwarding the request with framing the app rejects; or the app has strict host
filtering (`AllowedHosts`) that the proxied `Host` header does not satisfy. (2) **Protocol or
body handling** — the proxy is downgrading/upgrading the HTTP version, mishandling
`Content-Length`/`Transfer-Encoding` (a smuggling-adjacent framing mismatch, Chapter 57), or
buffering/altering the body. Diagnose by capturing what the proxy actually sends to the app
(`tcpdump` on the app port, or increase proxy access-log verbosity) and diffing it against the
working direct request.

### 4.8
In System A the "database not internet-reachable" property was provided by the *bind address*
— PostgreSQL bound to `127.0.0.1` on the VPS (Chapter 3 §7). In System B that mechanism no
longer exists: RDS is a managed service reachable over the network by design, so the property
must be re-provided by *different* controls — a private subnet with no route to an internet
gateway, `PubliclyAccessible=false`, and a security group allowing only the app tier. The
migration silently dropped the property because the team assumed "it was safe before" without
identifying *what made it safe* and re-implementing that in the new architecture. Concretely,
someone likely created the RDS instance with `PubliclyAccessible=true` (or in a public subnet)
and an over-broad security group. The fix: private subnet, `PubliclyAccessible=false`,
SG restricted to the task SG. The lesson (§7): always name the component providing each
property, so a migration re-provides it rather than losing it.

### 4.9
HTTPS + firewall cover Stops 2–4. The under-protected stops are almost certainly 5, 6, and 7.
Highest-value additions: (1) **Authorization at Stop 6** — verify per-resource access control
exists and is enforced on every endpoint (the IDOR/BOLA class is the most likely and most
damaging gap); this is application work but it addresses the top vulnerability class. (2)
**Least-privilege database credentials at Stop 7** — bound the blast radius of any Stop 6 bug;
cheap, high leverage. (3) **A WAF plus security response headers at Stops 5/0** — commodity
attack filtering and browser-side hardening (CSP, HSTS, cookie flags) that block whole classes
of client-side attack. Justification: this ordering targets where breaches actually happen
(application and data layers) before adding more perimeter, and each item addresses a distinct
layer so together they add genuine depth rather than reinforcing an already-strong perimeter.

### 4.10
Walking backward from Stop 7: **Stop 7 (data)** — the DB user should have least privilege
(could it even read the whole customer table?), row-level security should scope tenants,
encryption at rest for stolen snapshots, and audit logging of large reads; evidence: DB audit
logs showing a full-table scan by the app user, or direct DB access. **Stop 6 (app)** —
authorization should prevent bulk access, input validation should prevent injection, and rate
limiting should flag enumeration; evidence: an injection payload in app logs, or an authorized
endpoint returning far more rows than normal. **Stop 5 (edge)** — WAF should catch injection
patterns and rate limits should catch enumeration/bulk pulls; evidence: WAF logs, request-rate
anomalies. **Stop 2 (network)** — egress control should prevent the data leaving to an
unapproved destination, and Flow Logs should record the exfiltration; evidence: a large
outbound transfer to an unknown IP, or to the attacker's cloud bucket. **Stop 4/6 (identity)**
— if credentials were stolen, short-lived credentials would have limited the window; evidence:
CloudTrail showing use of a role/key from an unusual location. The report should end with
which control failed first (root cause) and which compensating controls also failed (why it
reached exfiltration).

### 4.11
Map: **Mobile app** authenticates the *user* to an identity provider (OIDC, Chapter 61),
receiving tokens; it sends an access token (JWT) on each API call. **Edge/API gateway (Stop
5)** validates the token (authentication) and may do coarse authorization and rate limiting.
**Front-end API service (Stop 6)** performs the primary authorization decision using the
user's identity and the resource. **Internal microservices (three hops deep)** need to know
*who the user is* to make their own authorization decisions — identity must propagate. Two
mechanisms: (a) **token passthrough** — forward the user's JWT (or a narrowed, re-issued
token) so each service validates it and authorizes independently; and (b)
**service-to-service authentication** (mTLS or a service token, Chapter 64) so a service also
knows *which service* is calling it, combined with a trusted "on-behalf-of" user claim. The
key design point: authentication of the user happens once at the edge, but authorization is
made independently at each service that owns a resource, using a propagated, verifiable
identity — never by trusting that "an upstream service already checked."

### 4.12
In System C with a service mesh: **User → Ingress**: TLS terminates at the ingress
gateway (managed cert), where the WAF/edge controls apply — the untrusted-internet hop must be
encrypted end-to-that-point. **Ingress → Pod and Pod → Pod (east-west)**: the mesh provides
**mTLS between sidecars** (Chapter 86), so each internal hop is encrypted *and mutually
authenticated* — this directly satisfies "TLS protects transit, not endpoints" for the
internal network, because each hop re-establishes an authenticated encrypted channel rather
than assuming the network is safe. **Sidecar → local app container**: typically plaintext over
loopback *within the pod's network namespace* — acceptable because it never leaves the pod
(same reasoning as System A's loopback bind, Chapter 3 §7). Justification: every hop that
crosses a network boundary (untrusted or internal) is encrypted and authenticated; the only
plaintext hop is intra-pod loopback with no network exposure. This gives end-to-end
confidentiality and, via mTLS, workload identity — the foundation of Zero Trust networking
(Chapter 87).

### 4.13
Expected deliverable: a `curl -v https://example.com/` transcript with each line labeled —
`* Trying 93.184.x.x:443` (Stop 2, IP/routing), `* Connected` (Stop 3, TCP established),
`* SSL connection using TLSv1.3 / ALPN h2` (Stop 4, TLS), `* subject:/issuer:/expire date`
(Stop 4, cert validation), `> GET / HTTP/2 / > Host:` (Stop 6 request, visible only locally),
`< HTTP/2 200 / < strict-transport-security:` (Stop 5/0 response controls) — alongside a
`tcpdump` capture of the same connection showing SYN/SYN-ACK/ACK and `application_data`
records but **no readable URL or headers**, proving that everything from Stop 5 up is inside
TLS and invisible to Stop 2. The write-up's key sentence: the URL that `curl -v` shows with
`>` does not appear anywhere in the packet capture, demonstrating what the network layer can
and cannot see.

### 4.14
Expected: add JWT bearer authentication (`AddAuthentication().AddJwtBearer(...)` with issuer/
audience/signing-key validation) and `app.UseAuthentication(); app.UseAuthorization();` in the
correct order; protect the endpoint with `.RequireAuthorization()` and add an ownership check
inside the handler (`if (account.Owner != User.Identity!.Name) return Results.Forbid();`).
Re-running the enumeration (`for i in 40..50`) should now yield 401 without a token, 403 for
accounts the caller does not own, and 200 only for owned accounts. The proof is the captured
401/403 responses replacing the earlier 200s — the same attack, now stopped at Stop 6,
demonstrating that the fix belongs at the application layer and nowhere below it.

### 4.15
Expected: enable `log_statement='all'` (or use `pg_stat_statements`), exercise the app, and
classify each logged statement. Parameterized statements appear with placeholders and
separately-logged parameters (`SELECT ... WHERE id = $1`, `parameters: $1 = '42'`);
interpolated statements appear with the value baked into the text (`SELECT ... WHERE id = 42`
or, damningly, `WHERE name = 'o''brien'` where a value was string-built). Any interpolated
statement carrying user-derived data is a finding: report the endpoint, the statement, and the
input path, and recommend converting to parameters. Note the nuance: a constant baked into SQL
(no user input) is not a vulnerability, so classification must trace whether the interpolated
value originates from user input — which is exactly the data-flow reasoning of Chapter 46 and
the SAST reachability analysis of Chapter 111.

### 4.16
Strong answer walks the map: browser applies SOP/HSTS and decides cookies/CSP; DNS resolves
the name (DNSSEC/logging, and the note that TLS will catch a spoof); TCP handshake (SYN
cookies, limits); TLS handshake authenticates the server via its certificate chain and
establishes a forward-secret encrypted channel (this is where a DNS lie is caught); the edge
terminates TLS and applies WAF/rate-limiting/header hygiene — the first point that sees the
HTTP; the application validates the token (authentication) then checks per-resource access
(authorization — call out IDOR here), validates input, and runs business logic; the data layer
receives a *parameterized* query over a socket, executed by a least-privileged DB user with
RLS and encryption; the response travels back, gaining security headers and re-encryption, and
the browser governs what the page may do with it. Bonus: name what each layer can and cannot
see, and mention audit logging (CloudTrail/Flow Logs/DB audit) spanning the whole path.

### 4.17
Authentication answers "who are you?" and happens at the layer that can see and validate the
credential — the token/session at the edge or in the app's authentication middleware (Stop
6.4). Authorization answers "may you do *this*, to *this resource*?" and must happen at the
layer that knows the data model and ownership — the application's authorization logic and,
as backstop, the database (Stops 6.5 and 7). The distinction causes the most common serious
web vulnerability (broken access control / IDOR / BOLA) because authentication is centralized
and easy to get right, so teams do it well and then implicitly assume "authenticated =
authorized." But authorization is per-resource and must be written for every object and every
action; a single missing ownership check lets an authenticated user access others' data. No
lower layer can catch it, because the attacker is a legitimate authenticated user — only code
that knows "this resource belongs to that user" can say no.

### 4.18
A security group operates at Stops 2–3: it sees source/destination IP, protocol, and port,
and nothing else. It can allow "TCP 443 from this CIDR/SG" and deny everything else — coarse
reachability control, applied early and cheaply, that stops an attacker from *reaching* a
service at all. A WAF operates at Stop 5: it sees the decrypted HTTP request — URL, headers,
body — and can match attack patterns (SQLi, XSS, path traversal), rate-limit by path, and
block bots. So the SG can stop "connections from unauthorized networks" but cannot see or
stop a malicious payload in an allowed request; the WAF can inspect the payload but only for
connections that were allowed to reach it, and only after TLS termination. They are
complementary controls at different layers: the SG controls *who can connect*, the WAF
controls *what an allowed request may contain*. Neither can do the other's job, and neither
replaces application-layer authorization.

### 4.19
TLS protects data *in transit between two endpoints*; it says nothing about the endpoints
themselves or about hops where it is terminated and re-originated. "End-to-end" is often
false in practice: TLS typically terminates at CloudFront, re-originates to the ALB,
terminates again, and may go plaintext to the backend — so "internal traffic" is frequently
*not* encrypted unless you explicitly configure east-west encryption (mesh mTLS, or TLS on
each hop). Moreover, encryption is not authorization or isolation: an encrypted channel from a
compromised or malicious internal service is still an attack. Zero Trust exists precisely
because "the internal network is safe" is the assumption that lets one foothold become total
compromise. So: verify where TLS actually terminates on each hop, encrypt internal hops that
cross a network boundary (mTLS), and never treat "it's internal" or "it's encrypted" as a
substitute for authentication, authorization, and segmentation.

### 4.20
Systematic method using the map: for each of the seven stops, ask "what control belongs here,
is it present, and what can it see?" — producing a control inventory. Then run the
defense-in-depth test: for each major attack class (§10), trace it across the layers and check
that at least one layer that can *see* it also *stops* it, with a backstop where feasible.
Specifically: Stop 0 (headers present? CSP/HSTS/cookies), Stop 1 (DNS controls, egress), Stop
2 (default-deny SG/NACL, segmentation, egress control), Stop 4 (TLS version/cert/mTLS
internal), Stop 5 (WAF after termination, rate limits, `X-Forwarded-For` hygiene), Stop 6
(authN present, authZ per-resource, validation, no data leakage on responses), Stop 7
(parameterization, least-priv creds, RLS, encryption, audit). Flag every stop with no named
control, every property whose enforcing component you cannot name, and every attack class that
no visible-to-it layer stops. The output is a prioritized gap list — which is exactly the
architecture-review deliverable of Chapter 133.

---

*This concludes the conceptual core of Part 0. Next: Chapter 5 — The Building Blocks of
Production: Servers, Services, Databases, Caches, Queues, and Proxies. We give each component
on the map its own security treatment — what Redis, RabbitMQ, PostgreSQL, and a reverse proxy
each get wrong by default — before Chapter 6 lifts everything into virtualization and the
cloud.*
