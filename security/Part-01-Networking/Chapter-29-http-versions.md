# Chapter 29 — HTTP/1.1, HTTP/2, HTTP/3: Semantics, Framing, Multiplexing, and Security Differences

---

## 1. Why This Matters

HTTP is the application protocol the web runs on — every API call, every web page, every REST/GraphQL request
you secure (Chapter 4, Part 5) rides on HTTP, carried by TLS (Chapter 28). You have used HTTP throughout the
book; this chapter examines its versions (1.1, 2, 3) and, critically, their *framing* differences — because
those differences are where a whole class of attacks (request smuggling) lives, and where the HTTP/3-over-QUIC
visibility shift (Chapter 18) matters.

For a cloud security engineer, HTTP versions matter because:

1. **Request smuggling** — the marquee HTTP framing attack — arises from *disagreement* about where one
   request ends and the next begins, between a front-end (proxy/CDN) and a back-end. Understanding HTTP
   framing across versions is understanding this attack class (Chapter 57 covers it in depth; this chapter
   establishes the framing).
2. **HTTP semantics are the security-relevant surface** — methods, headers, cookies, status codes — which are
   the substance of API security (Part 5), the request map (Chapter 4), and headers like HSTS/CSP (Chapter
   59).
3. **HTTP/2 and HTTP/3 change the framing and transport** — HTTP/2's multiplexing (binary framing) and
   HTTP/3's move to QUIC/UDP (Chapter 18) have security implications (new DoS vectors, downgrade
   inconsistencies, and the QUIC visibility shift).
4. **Version mismatches between intermediaries** (a CDN speaking HTTP/2, a backend speaking HTTP/1.1) create
   the parsing inconsistencies that request smuggling exploits.

The core idea: **HTTP is a request/response protocol whose *semantics* (methods, headers, status codes) are
stable across versions, but whose *framing* (how requests are delimited on the wire) differs: HTTP/1.1 uses
text with Content-Length/Transfer-Encoding to delimit (the source of request smuggling when intermediaries
disagree), HTTP/2 uses binary framing with multiplexing over one TCP connection (fixing head-of-line blocking
but adding new DoS vectors), and HTTP/3 moves to QUIC over UDP (Chapter 18 — fixing TCP head-of-line blocking
but shifting visibility). The framing differences and intermediary disagreements are where HTTP-layer attacks
(request smuggling) live.** This chapter completes the request map's application layer (Chapter 4) and sets up
request smuggling (Chapter 57) and API security (Part 5).

---

## 2. Prerequisites

- Chapter 4 (the request map — HTTP is Stops 5–6), Chapter 28 (TLS carries HTTP → HTTPS), Chapter 19 (TCP —
  HTTP/1.1 and 2 run on TCP), Chapter 18 §4.6 (QUIC — HTTP/3's transport).
- Chapter 7 (bytes/text — HTTP/1.1 is text, HTTP/2 is binary), Chapter 24 (packet analysis — reading HTTP).
- Forward: Chapter 57 (request smuggling — this chapter's framing is its foundation), Part 5 (API security),
  Chapter 59 (HTTP security headers).

---

## 3. Mental Model

**HTTP's semantics (methods, headers, status codes) are stable across versions; what changes is the framing —
how requests are delimited and multiplexed on the wire. HTTP/1.1 is text-delimited (Content-Length/
Transfer-Encoding), HTTP/2 is binary-multiplexed over one TCP connection, HTTP/3 is over QUIC/UDP. The framing
differences — especially disagreements between intermediaries about request boundaries — are where HTTP-layer
attacks (request smuggling) live.**

```
   HTTP SEMANTICS (stable across versions): request = method + path + headers + body; response = status + headers + body
     methods (GET/POST/PUT/DELETE...), headers (Host, Content-Type, Cookie, Authorization...), status codes
     (2xx ok, 3xx redirect, 4xx client error, 5xx server error). These are the security-relevant surface (Part 5).

   HTTP FRAMING (differs by version — the security-relevant difference):
     HTTP/1.1: TEXT, one request/response per connection (or keep-alive/pipelining); requests DELIMITED by
       Content-Length OR Transfer-Encoding: chunked. -> DISAGREEMENT about delimiting = REQUEST SMUGGLING (Ch57).
     HTTP/2: BINARY framing, MULTIPLEXING many streams over ONE TCP connection (fixes HTTP/1.1 head-of-line
       blocking at the app layer); headers compressed (HPACK). -> new DoS vectors (Rapid Reset, etc.).
     HTTP/3: over QUIC/UDP (Chapter 18) — fixes TCP head-of-line blocking; encrypted transport; reduced
       visibility (Chapter 24). -> QUIC visibility shift; framing over QUIC streams.
```

Three ideas:

1. **Semantics are stable; framing differs.** The *meaning* of an HTTP request (method, path, headers, body,
   status) is the same across versions and is the security-relevant surface (Part 5, Chapter 4). What differs
   is *framing* — how requests are delimited/multiplexed on the wire — and that is where the version-specific
   security differences (especially request smuggling) live.
2. **HTTP/1.1's text delimiting is the request-smuggling surface.** HTTP/1.1 delimits requests with
   Content-Length or Transfer-Encoding headers; if a front-end and back-end *disagree* about which to use or
   how to parse them, an attacker can "smuggle" a request past the front-end's controls — **request
   smuggling** (Chapter 57). This is the marquee HTTP framing attack, rooted in parsing inconsistency (the
   "two parties interpret the same bytes differently" root cause — Chapters 7, 22).
3. **HTTP/2 and HTTP/3 change framing and transport, with their own security implications.** HTTP/2's binary
   multiplexing fixes head-of-line blocking but adds DoS vectors (Rapid Reset — CVE-2023-44487); HTTP/3's move
   to QUIC/UDP (Chapter 18) fixes TCP head-of-line blocking but shifts visibility (encrypted transport,
   Chapter 24). Version *downgrades* and *mismatches* between intermediaries create inconsistencies.

**The security framing:** HTTP's semantics are the substance of application/API security (Part 5, Chapter 4 —
methods, headers, cookies, status codes, and security headers — Chapter 59), stable across versions. The
version differences are in *framing*, and the security-critical consequence is **request smuggling** —
arising from front-end/back-end disagreement about request boundaries (a parsing-inconsistency /
interpretation-ambiguity attack, the same root cause as encoding bypass and fragment evasion — Chapters 7,
22). HTTP/2 and HTTP/3 add framing-specific DoS vectors and, for HTTP/3, the QUIC visibility shift (Chapter
18). Understanding the framing per version is the foundation for request smuggling (Chapter 57) and for
reasoning about intermediary consistency.

---

## 4. Fundamentals

### 4.1 HTTP semantics (stable across versions — the security surface)

HTTP is a request/response protocol; its semantics are stable and are the security-relevant surface:

```
   REQUEST:  METHOD path HTTP/version    (e.g. GET /api/accounts/42 HTTP/1.1)
             Header: value               (Host, Content-Type, Cookie, Authorization, User-Agent...)
             <blank line>
             body (optional)
   RESPONSE: HTTP/version STATUS reason   (e.g. HTTP/1.1 200 OK)
             Header: value               (Content-Type, Set-Cookie, security headers — Chapter 59...)
             <blank line>
             body
```

The security-relevant semantic elements (detailed in Part 5, Chapter 59):

- **Methods:** GET (read, should be safe/idempotent), POST/PUT/PATCH (write), DELETE, etc. — method-based
  access control and CSRF considerations (Chapter 49) depend on methods being used correctly (GET should not
  change state).
- **Headers:** Host (routing/virtual hosting — and Host-header attacks), Cookie/Set-Cookie (sessions —
  Chapters 49, 60), Authorization (tokens — Chapter 60), Content-Type (parsing), and **security headers**
  (HSTS, CSP, X-Content-Type-Options, etc. — Chapter 59) that program browser behavior. `X-Forwarded-For`
  (client IP through proxies — Chapter 4 §Stop 5) is a header whose mishandling enables spoofing.
- **Status codes:** 2xx (success), 3xx (redirect — open-redirect risks), 4xx (client error — 401 auth, 403
  authz, 429 rate limit), 5xx (server error — don't leak stack traces, Chapter 58). Status codes are used in
  access control and error handling.

These semantics are the substance of API security (Part 5) and are consistent across HTTP versions — so
security *at the semantic layer* (authN/authZ, input validation, headers) is version-independent. The version
differences are in framing (§4.2–4.4).

### 4.2 HTTP/1.1 framing (text, and the request-smuggling surface)

HTTP/1.1 is a **text** protocol; requests are delimited by headers, and this delimiting is the
request-smuggling surface:

```
   HTTP/1.1 delimits the request body two ways:
     Content-Length: N          -> the body is exactly N bytes
     Transfer-Encoding: chunked -> the body is sent in chunks, terminated by a zero-length chunk
   Connection reuse: keep-alive (multiple requests per connection) and pipelining (send requests back-to-back).

   REQUEST SMUGGLING (Chapter 57) — the framing attack:
     If a request has BOTH Content-Length AND Transfer-Encoding (or ambiguous/malformed ones), and the
     FRONT-END (proxy/CDN) and BACK-END disagree about which to honor, they parse the request boundary
     DIFFERENTLY -> an attacker "smuggles" a second request that the front-end doesn't see but the back-end
     processes -> bypassing front-end controls (WAF, auth), poisoning other users' requests, etc.
```

The security consequence: **HTTP/1.1's text framing, with two delimiting mechanisms (Content-Length and
Transfer-Encoding), creates the possibility of front-end/back-end parsing disagreement — request smuggling**
(Chapter 57). This is a parsing-inconsistency attack — the same root cause as encoding bypass (Chapter 7),
fragment reassembly ambiguity (Chapter 22), and the general "two parties interpret the same bytes differently"
pattern. It is the marquee HTTP framing attack, and it is why HTTP/1.1 parsing consistency between
intermediaries matters (Chapter 4 §Stop 5, Chapter 57). Defenses: consistent parsing, rejecting ambiguous
requests (both CL and TE), and using HTTP/2 to the backend (which frames unambiguously — §4.3).

### 4.3 HTTP/2 framing (binary, multiplexing, and new DoS vectors)

HTTP/2 replaced text framing with **binary framing** and **multiplexing** to fix HTTP/1.1's performance
problems:

```
   HTTP/2: BINARY framing (not text). MULTIPLEXING: many concurrent "streams" over ONE TCP connection
     (fixes HTTP/1.1's app-layer head-of-line blocking — where one slow request blocks others on a connection).
   Header compression: HPACK (compresses repeated headers).
   Requests are framed unambiguously (length-prefixed binary frames) -> LESS request-smuggling surface at the
     HTTP/2 layer itself. BUT: HTTP/2-to-HTTP/1.1 DOWNGRADE at a proxy can re-introduce smuggling (the proxy
     translates HTTP/2 to HTTP/1.1 for the backend, and the translation can create CL/TE ambiguity — Ch57).
```

Security implications:

- **Unambiguous framing reduces smuggling at the HTTP/2 layer** (binary length-prefixed frames, not
  text-delimited) — but **HTTP/2→HTTP/1.1 downgrade** (a common pattern: CDN/proxy speaks HTTP/2 to clients,
  HTTP/1.1 to the backend) can re-introduce request smuggling in the translation (Chapter 57 — "H2.CL"/
  "H2.TE" smuggling). So HTTP/2 doesn't eliminate smuggling if there's a downgrade.
- **New DoS vectors from multiplexing:** the ability to open many streams cheaply on one connection created
  new attacks — notably **HTTP/2 Rapid Reset (CVE-2023-44487, 2023)**, where an attacker rapidly opens and
  cancels streams, causing the server to do work for each with minimal attacker cost — a record-breaking DDoS.
  Multiplexing's efficiency cuts both ways (like epoll — Chapter 3 §5.3). Defense: limit concurrent streams,
  rate-limit resets, patch.
- **HPACK header compression** had its own considerations (compression-based attacks, like CRIME/HPACK
  issues) — mitigated in the design, but a reminder that compression + secrets can leak (a general principle).

### 4.4 HTTP/3 framing (over QUIC/UDP — the visibility shift)

HTTP/3 moves HTTP to **QUIC over UDP** (Chapter 18 §4.6), fixing TCP's head-of-line blocking and shifting
visibility:

```
   HTTP/3 = HTTP over QUIC (Chapter 18) over UDP. QUIC provides: multiplexed streams (like HTTP/2) but WITHOUT
     TCP head-of-line blocking (a lost packet blocks only its stream, not all), built-in TLS 1.3 (Chapter 28),
     and faster connection setup (0-RTT).
   Framing: HTTP/3 frames over QUIC streams (unambiguous, like HTTP/2).
   Security implications:
     - ENCRYPTED TRANSPORT (TLS 1.3 built into QUIC) -> reduced network visibility (Chapter 24 §4.5, Ch18):
       middleboxes/WAFs/IDS see less; inspection must happen at termination.
     - UDP-based -> some firewalls/tooling handle it less richly; some enterprises block UDP/443 to force
       TCP+TLS for inspectability (Chapter 18 §4.6) — a privacy/performance vs inspection trade-off.
     - New protocol -> new implementation attack surface (as it matures).
```

Security implications:

- **The QUIC visibility shift** (Chapter 18 §4.6, Chapter 24 §4.5): HTTP/3's encrypted QUIC transport means
  network-based inspection (WAFs, IDS, middleboxes) sees less — inspection must happen at the termination
  point (the edge/CDN where HTTP/3 terminates — Chapter 4 §Stop 5), not on the network path. This is the same
  trade-off as QUIC (Chapter 18) and DoH (Chapter 17): better privacy/performance, reduced defender
  visibility. Some organizations block UDP/443 to force clients to TCP+TLS (HTTP/2) for inspectability.
- **HTTP/3 framing is unambiguous** (over QUIC streams, like HTTP/2), so less smuggling surface at the HTTP/3
  layer — but downgrades to HTTP/1.1 at a backend can still re-introduce it.
- **New protocol, new attack surface** — as HTTP/3/QUIC matures, implementation vulnerabilities emerge (as
  with any new protocol); keep implementations current.

The takeaway: HTTP/3 improves performance (no TCP head-of-line blocking, faster setup) and privacy (encrypted
transport) but shifts inspection to termination points (the QUIC visibility trade-off — Chapters 18, 24). For
a cloud security engineer: ensure the edge (CloudFront/ALB) that terminates HTTP/3 does the inspection (WAF),
and decide the UDP/443-blocking trade-off per your inspection needs.

### 4.5 Intermediary consistency (the request-smuggling root cause)

The unifying HTTP security concern across versions is **intermediary consistency** — front-ends (CDNs,
proxies, load balancers) and back-ends must agree on how to parse requests:

```
   A request passes through intermediaries: client -> CDN -> load balancer -> reverse proxy -> app server.
   Each parses the HTTP. If they DISAGREE about request boundaries (CL vs TE in HTTP/1.1, or in H2->H1
   downgrade translation), an attacker exploits the disagreement:
     REQUEST SMUGGLING (Chapter 57): smuggle a request the front-end doesn't see but the back-end processes
       -> bypass WAF/auth (front-end controls), poison other users' responses, hijack sessions.
   Root cause: "two parties interpret the same bytes differently" (Chapters 7, 22) — parsing inconsistency.
```

The security principle: **the more intermediaries parse a request, and the more they can disagree, the larger
the smuggling surface** — so consistency matters. Defenses (Chapter 57): use the same HTTP version end-to-end
where possible (avoid downgrades), configure intermediaries to reject ambiguous requests (both CL and TE, or
malformed), normalize requests at the edge, and prefer HTTP/2+ (unambiguous framing) end-to-end. This is why
the edge/proxy's parsing consistency is a security property (Chapter 4 §Stop 5) — request smuggling is the
concrete manifestation of intermediary parsing disagreement, and Chapter 57 covers it in depth.

### 4.6 HTTP security headers and semantics (preview of Chapter 59)

HTTP's semantics include the **security headers** that program browser behavior — a preview of Chapter 59
(the HTTP security model) and Chapter 4 §Stop 0:

```
   Security-relevant response headers (Chapter 59):
     Strict-Transport-Security (HSTS): force HTTPS (prevent SSL stripping — Chapters 9, 28)
     Content-Security-Policy (CSP): restrict scripts/resources (XSS mitigation — Chapter 48)
     X-Content-Type-Options: nosniff (prevent MIME sniffing)
     X-Frame-Options / frame-ancestors: prevent clickjacking
     Set-Cookie attributes: Secure, HttpOnly, SameSite (session security, CSRF — Chapters 49, 60)
   These are version-independent (semantics), applied at the response, programming the browser (Chapter 4 §Stop 0).
```

These security headers (Chapter 59) are part of HTTP's semantics (version-independent) and are a key part of
the request map's browser-side controls (Chapter 4 §Stop 0). They program the browser to enforce HTTPS
(HSTS), restrict scripts (CSP), and secure cookies (SameSite/HttpOnly/Secure) — the client-side security
layer. This chapter notes them as part of HTTP semantics; Chapter 59 covers the HTTP security model in depth.

---

## 5. Deep Technical Explanation: Framing Differences as the Security Surface

The security-defining insight about HTTP versions is that **the semantics are stable and version-independent
(so application/API security is the same across versions), while the framing differs — and the framing
differences, especially intermediary parsing disagreements, are where the version-specific attacks (request
smuggling, framing DoS) live.**

**Semantics vs framing — where security lives at each:**

- **Semantics (methods, headers, status codes, cookies) are the *application-layer* security surface** — this
  is where authN/authZ (Chapter 4 §Stop 6, Part 5), input validation, security headers (Chapter 59), and the
  bulk of web vulnerabilities (Part 4) live. It is **version-independent**: a SQL injection, an IDOR, an XSS,
  a CSRF is the same regardless of HTTP version, because they're about the request's *meaning*, not its
  *framing*. So most of application security (Part 4, Part 5) doesn't care about HTTP version.
- **Framing (delimiting, multiplexing, transport) is the *protocol-layer* security surface** — this is where
  the version-specific attacks live: **request smuggling** (framing/parsing disagreement — HTTP/1.1's CL/TE,
  or H2→H1 downgrade), **framing DoS** (HTTP/2 Rapid Reset — multiplexing abuse), and the **QUIC visibility
  shift** (HTTP/3's encrypted transport). These *are* version-dependent, because they're about how requests
  are structured on the wire.

**Request smuggling is the marquee framing attack, and it's a parsing-inconsistency attack:** request
smuggling (Chapter 57) arises when a front-end and back-end *disagree* about where one request ends and the
next begins — HTTP/1.1's two delimiting mechanisms (Content-Length and Transfer-Encoding) create ambiguity if
handled inconsistently, and HTTP/2→HTTP/1.1 downgrade translation can re-introduce it. This is the same root
cause as encoding bypass (Chapter 7 — the WAF and app decode differently), fragment reassembly ambiguity
(Chapter 22 — the IDS and target reassemble differently), and seccomp's pointer blindness (Chapter 2 — filter
vs enforce): **two parties interpreting the same bytes differently.** The defense is the same in spirit:
*consistency and normalization* — parse consistently, reject ambiguous input, normalize at a single point.
Request smuggling is the HTTP-layer instance of this recurring interpretation-ambiguity pattern, and it is why
intermediary consistency (§4.5) is a security property.

**The version evolution is a performance story with security side effects:** HTTP/1.1→2→3 is driven by
performance (fixing head-of-line blocking — first at the app layer with HTTP/2 multiplexing, then at the
transport layer with HTTP/3/QUIC), but each change has security side effects: HTTP/2's multiplexing enabled
new DoS (Rapid Reset — the efficiency-cuts-both-ways pattern, like epoll — Chapter 3); HTTP/3's QUIC shifted
visibility (encrypted transport — the privacy-vs-inspection trade-off, like DoH/QUIC — Chapters 17, 18);
downgrades between versions create parsing inconsistencies (smuggling). So the security engineer tracks the
version evolution not for the performance but for these side effects: new DoS vectors, visibility shifts, and
downgrade inconsistencies.

**The intermediary-consistency principle generalizes:** the deeper lesson is that **every point where a
request is parsed is a point where interpretations can diverge, and divergence is exploitable** — so minimize
the number of parsers, keep them consistent (same version end-to-end where possible), reject ambiguity, and
normalize at a single trusted point (the edge). This is why the edge/proxy's parsing behavior is a security
property (Chapter 4 §Stop 5), why request smuggling is a serious class (Chapter 57), and why the general
"normalize before you process/inspect" principle (Chapters 7, 22) applies to HTTP framing too.

The unifying insight: **HTTP's semantics are stable and version-independent (so application/API security is
the same across versions — Part 4, Part 5), while the framing differs by version — HTTP/1.1 text-delimited
(request-smuggling surface via CL/TE ambiguity), HTTP/2 binary-multiplexed (new DoS vectors like Rapid Reset,
downgrade smuggling), HTTP/3 over QUIC/UDP (visibility shift) — and the framing differences, especially
intermediary parsing disagreements (request smuggling — a parsing-inconsistency attack like encoding bypass
and fragment evasion), are where the version-specific security lives.** The defense is consistency and
normalization; the security engineer tracks version evolution for its side effects (DoS, visibility,
downgrade inconsistency), and Chapter 57 details request smuggling as the marquee framing attack.

---

## 6. Internals: Observing HTTP Versions

### 6.1 See which HTTP version is used

```bash
# curl shows the negotiated HTTP version:
$ curl -sI https://example.com | head -1              # HTTP/2 200 (or HTTP/1.1, or HTTP/3)
$ curl -sI --http2 https://example.com | head -1      # force HTTP/2
$ curl -sI --http3 https://example.com | head -1      # force HTTP/3 (if curl+server support it)
$ curl -sI --http1.1 https://example.com | head -1    # force HTTP/1.1
# ALPN (in the TLS handshake — Chapter 28) negotiates the version: "h2" (HTTP/2), "http/1.1", "h3" (HTTP/3).
$ openssl s_client -connect example.com:443 -alpn h2 </dev/null 2>/dev/null | grep ALPN
```

The negotiated HTTP version is shown by curl and negotiated via ALPN in the TLS handshake (Chapter 28 — `h2`,
`http/1.1`, `h3`). Knowing the version matters for reasoning about framing/smuggling and the QUIC visibility
shift.

### 6.2 Read HTTP semantics (the security surface)

```bash
# See the request/response headers (the semantic security surface — §4.1, §4.6):
$ curl -v https://example.com 2>&1 | grep -E '^> |^< '
#   > (request): method, path, Host, headers
#   < (response): status, security headers (HSTS, CSP, X-Content-Type-Options — Chapter 59), Set-Cookie
$ curl -sI https://example.com | grep -iE 'strict-transport|content-security|x-content-type|set-cookie'
# Check for security headers (Chapter 59) and cookie attributes (Secure/HttpOnly/SameSite — Chapters 49, 60).
```

Reading HTTP semantics — methods, headers, status, security headers, cookies — is the application-security
surface (Part 5, Chapter 59), version-independent. Checking for security headers (HSTS/CSP) and secure cookie
attributes is a common review item.

### 6.3 HTTP/1.1 framing and the smuggling surface (conceptual)

```bash
# HTTP/1.1 delimiting headers (the smuggling surface — §4.2, Chapter 57):
$ printf 'GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n' | \
    openssl s_client -connect example.com:443 -quiet 2>/dev/null | head
# A request with BOTH Content-Length and Transfer-Encoding is the smuggling primitive (Chapter 57) — testing
# it against systems you own reveals front-end/back-end parsing disagreement. (Chapter 57 covers safely.)
echo "HTTP/1.1: CL and TE delimit the body; disagreement between intermediaries = request smuggling (Ch57)."
```

HTTP/1.1's Content-Length/Transfer-Encoding delimiting is the request-smuggling surface (§4.2, Chapter 57);
ambiguous requests (both CL and TE) are the primitive. Chapter 57 covers testing/exploiting this safely; here
we note the framing basis.

### 6.4 HTTP/2 and HTTP/3 (binary framing, multiplexing, QUIC)

```bash
# HTTP/2 (binary, multiplexed):
$ curl -v --http2 https://example.com 2>&1 | grep -iE 'HTTP/2|multiplex|ALPN'
$ nghttp -v https://example.com 2>&1 | head    # nghttp shows HTTP/2 frames/streams (if installed)
# HTTP/3 (over QUIC/UDP — Chapter 18):
$ curl -v --http3 https://cloudflare.com 2>&1 | grep -iE 'HTTP/3|QUIC|h3'
# Note: HTTP/3 is over UDP/443 (Chapter 18) — reduced network visibility (Chapter 24); inspect at termination.
```

HTTP/2's binary multiplexing and HTTP/3's QUIC transport are observable via curl/nghttp. Note HTTP/3 is over
UDP/443 (Chapter 18) with the visibility shift (Chapter 24) — inspection must be at the termination point.

---

## 7. Real-World Example: HTTP Versions in the Ledger System

**Ledger's HTTP version usage and security:**

- **Client-facing (Chapters 4, 28):** CloudFront/ALB serve **HTTP/2** (and increasingly **HTTP/3** over QUIC)
  to clients over TLS — better performance (multiplexing, no head-of-line blocking). The **WAF inspects after
  TLS termination** (Chapters 4, 22, 85), and for HTTP/3 the inspection is at the edge (the QUIC visibility
  shift — §4.4, Chapter 24).
- **Request smuggling (Chapter 57):** Ledger's request path (CloudFront → ALB → ECS) has multiple
  intermediaries that parse HTTP. To prevent **request smuggling** (§4.2, §4.5), Ledger: uses consistent HTTP
  handling, avoids risky HTTP/2→HTTP/1.1 downgrades where possible (or ensures the translation is safe),
  configures intermediaries to reject ambiguous requests (both CL and TE), and relies on AWS's managed
  intermediaries (CloudFront/ALB) which handle framing consistently — with Chapter 57's defenses.
- **HTTP/2 DoS (Rapid Reset — §4.3):** Ledger's edge (CloudFront/ALB) and any HTTP/2 servers are patched
  against Rapid Reset (CVE-2023-44487) and limit concurrent streams / rate-limit resets — the multiplexing
  DoS vector.
- **HTTP/3 visibility (§4.4):** if Ledger serves HTTP/3, inspection happens at the CloudFront edge (where
  HTTP/3 terminates), since the QUIC transport is encrypted and reduces network visibility (Chapter 24).
  Ledger decides the UDP/443 trade-off (allow HTTP/3 for performance, inspect at the edge).
- **HTTP semantics/security headers (§4.6, Chapter 59):** Ledger sets security headers (HSTS, CSP,
  X-Content-Type-Options, secure cookie attributes — Chapters 49, 59, 60) at the response — version-independent
  application security (the request map's browser-side controls — Chapter 4 §Stop 0).
- **API security (Part 5):** Ledger's API security (authN/authZ, input validation, rate limiting) operates on
  HTTP *semantics* (methods, headers, tokens) — version-independent, the same across HTTP/1.1/2/3.

The HTTP-version decisions Ledger makes: use HTTP/2 (+HTTP/3) for performance; inspect after TLS termination
(WAF), at the edge for HTTP/3; prevent request smuggling (consistent parsing, reject ambiguity, safe
downgrades — Chapter 57); patch/limit against framing DoS (Rapid Reset); set security headers
(version-independent). The failures Ledger avoids: request smuggling (intermediary disagreement), framing DoS
(unpatched Rapid Reset), and lost HTTP/3 visibility (not inspecting at the edge).

The Ledger takeaway: **Ledger uses HTTP/2 (+HTTP/3) for performance, with application/API security operating
on version-independent HTTP semantics (authN/authZ/headers — Part 5, Chapter 59) and the version-specific
concerns being request smuggling (intermediary parsing consistency — Chapter 57), framing DoS (HTTP/2 Rapid
Reset), and the HTTP/3 QUIC visibility shift (inspect at the edge) — completing the request map's
application-and-transport layers (Chapter 4).** The framing differences are where the version-specific
security lives; the semantics are the stable application-security surface.

---

## 8. Hands-On Demonstration

### LAB 29.1 — HTTP Versions, Semantics, and the Framing Surface

**Objective.** Observe HTTP versions and their negotiation (ALPN), read HTTP semantics (the version-independent
security surface — methods/headers/status/security headers), and understand the framing differences (HTTP/1.1
CL/TE smuggling surface, HTTP/2 multiplexing, HTTP/3 QUIC visibility).

**Cost.** Free. **Environment.** ENV-1 (curl, openssl). **Time.** 45 minutes.

**Steps.**

*Step 1 — Observe HTTP versions and ALPN negotiation.*

```bash
curl -sI https://example.com | head -1                # the negotiated version (HTTP/2 or 1.1)
curl -sI --http1.1 https://example.com | head -1      # force HTTP/1.1
curl -sI --http2 https://cloudflare.com | head -1     # HTTP/2
curl -sI --http3 https://cloudflare.com | head -1 2>/dev/null || echo "HTTP/3 needs curl+server support"
openssl s_client -connect example.com:443 -alpn h2,http/1.1 </dev/null 2>/dev/null | grep -i ALPN
# ALPN (in the TLS handshake — Chapter 28) negotiates the version.
```

*Step 2 — Read HTTP semantics (the version-independent security surface).*

```bash
curl -v https://example.com 2>&1 | grep -E '^> |^< '   # request/response: methods, headers, status
# Security headers (Chapter 59) and cookie attributes (Chapters 49, 60):
curl -sI https://example.com | grep -iE 'strict-transport|content-security|x-content-type|x-frame|set-cookie'
```

Note the security headers present/absent (HSTS, CSP, etc. — Chapter 59) — a version-independent
application-security review item.

*Step 3 — HTTP/1.1 framing (the smuggling surface — conceptual).*

```bash
# HTTP/1.1 delimits with Content-Length / Transfer-Encoding (§4.2). A request with BOTH is the smuggling
# primitive (Chapter 57). Observe normal framing:
printf 'GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n' | \
  openssl s_client -connect example.com:443 -quiet 2>/dev/null | head -5
echo "Framing via CL/TE; front-end/back-end disagreement = request smuggling (Chapter 57)."
```

*Step 4 — HTTP/2 multiplexing and HTTP/3 QUIC (framing/transport differences).*

```bash
curl -v --http2 https://cloudflare.com 2>&1 | grep -iE 'HTTP/2|ALPN: h2'   # binary, multiplexed
curl -v --http3 https://cloudflare.com 2>&1 | grep -iE 'HTTP/3|h3|QUIC' 2>/dev/null || \
  echo "HTTP/3 over QUIC/UDP (Chapter 18) — reduced visibility (Chapter 24); inspect at termination."
```

**Security implications.** Write down: (a) HTTP semantics (methods/headers/status/security headers) are the
version-independent application-security surface (Part 5, Chapter 59); (b) framing differs by version and is
where version-specific security lives; (c) HTTP/1.1 CL/TE framing = request-smuggling surface (parsing
inconsistency — Chapter 57); (d) HTTP/2 multiplexing = new DoS (Rapid Reset); (e) HTTP/3 = QUIC/UDP =
visibility shift (inspect at edge — Chapters 18, 24); (f) intermediary consistency prevents smuggling.

**Cleanup.** None.

---

## 9. Security Implications

- **HTTP semantics (methods, headers, status codes, cookies, security headers) are stable across versions and
  are the version-independent application-security surface** — authN/authZ (Part 5), input validation,
  security headers (Chapter 59), and web vulnerabilities (Part 4) are the same regardless of HTTP version.
- **Framing differs by version and is where version-specific security lives:** HTTP/1.1 text-delimited
  (Content-Length/Transfer-Encoding — the **request-smuggling surface**), HTTP/2 binary-multiplexed (new DoS
  like **Rapid Reset**, and downgrade smuggling), HTTP/3 over QUIC/UDP (the **visibility shift**).
- **Request smuggling is the marquee HTTP framing attack** (Chapter 57) — front-end/back-end *disagreement*
  about request boundaries (CL/TE ambiguity, or H2→H1 downgrade) lets an attacker smuggle a request past
  front-end controls. It is a **parsing-inconsistency attack** — the same "two parties interpret the same
  bytes differently" root cause as encoding bypass (Chapter 7) and fragment evasion (Chapter 22).
- **Intermediary consistency is a security property** — every parser is a point of possible divergence; keep
  versions consistent end-to-end, reject ambiguous requests, normalize at the edge (Chapter 4 §Stop 5,
  Chapter 57).
- **HTTP/2 multiplexing added DoS vectors** (Rapid Reset — efficiency cuts both ways); **HTTP/3's QUIC
  transport reduces network visibility** (inspect at termination — Chapters 18, 24) — version evolution's
  security side effects.
- **The security engineer tracks version evolution for its side effects** (new DoS, visibility shifts,
  downgrade inconsistencies), not the performance — while application security operates on the stable
  semantics.

---

## 10. Attack Scenarios

1. **HTTP request smuggling** (§4.2, §4.5, Chapter 57): front-end/back-end parsing disagreement (CL/TE
   ambiguity, H2→H1 downgrade) → smuggle requests past front-end controls (WAF/auth bypass, response
   poisoning, session hijacking). The marquee framing attack. Defense: consistent parsing, reject ambiguity,
   safe downgrades (Chapter 57).
2. **HTTP/2 Rapid Reset (CVE-2023-44487)** (§4.3): rapidly open/cancel streams for a record DDoS. Defense:
   patch, limit concurrent streams, rate-limit resets.
3. **HTTP/3 visibility evasion** (§4.4, Chapter 18): encrypted QUIC transport evading network inspection.
   Defense: inspect at termination (edge WAF); consider blocking UDP/443 where inspection is mandatory.
4. **Host header attacks** (§4.1): manipulating the Host header for cache poisoning, password-reset poisoning,
   routing bypass. Defense: validate Host; strict virtual-host config (Part 5).
5. **Missing security headers** (§4.6, Chapter 59): no HSTS (SSL stripping — Chapter 9), no CSP (XSS —
   Chapter 48), insecure cookies (CSRF/theft — Chapters 49, 60). Defense: set security headers.
6. **X-Forwarded-For spoofing** (§4.1, Chapter 4 §Stop 5): trusting client-supplied XFF for IP-based
   controls. Defense: correct proxy XFF handling.
7. **Downgrade to weaker framing** — forcing HTTP/1.1 to re-introduce smuggling. Defense: consistent
   versions, safe handling.

---

## 11. Defensive Techniques

- **Prevent request smuggling** (Chapter 57) — the marquee framing attack: use consistent HTTP handling
  across intermediaries, reject ambiguous requests (both Content-Length and Transfer-Encoding, or malformed),
  avoid/secure HTTP/2→HTTP/1.1 downgrades, normalize at the edge, and prefer unambiguous framing (HTTP/2+)
  end-to-end. Intermediary consistency is a security property (§4.5).
- **Patch and limit against framing DoS** — patch HTTP/2 Rapid Reset (CVE-2023-44487); limit concurrent
  streams and rate-limit stream resets (§4.3).
- **Inspect at TLS/HTTP termination** — the WAF must sit after TLS termination (Chapters 4, 22, 85); for
  HTTP/3, inspection is at the edge where QUIC terminates (the visibility shift — §4.4, Chapters 18, 24).
- **Set HTTP security headers** (Chapter 59) — HSTS (prevent SSL stripping — Chapter 9), CSP (XSS — Chapter
  48), X-Content-Type-Options, X-Frame-Options, and secure cookie attributes (Secure/HttpOnly/SameSite —
  Chapters 49, 60) — version-independent application security.
- **Validate the Host header and handle X-Forwarded-For correctly** (§4.1, Chapter 4 §Stop 5) — prevent
  Host-header attacks and IP spoofing.
- **Decide the HTTP/3 / UDP-443 trade-off** — allow HTTP/3 for performance/privacy but ensure edge inspection;
  or block UDP/443 to force TCP+TLS where network inspection is mandatory (Chapter 18 §4.6).
- **Apply application/API security on the semantics** (Part 5) — authN/authZ, input validation, rate limiting
  — version-independent; the bulk of web security is here (Part 4).

---

## 12. Production Architecture

HTTP versions and their security handling, in the request path:

```
   Client --HTTP/2 or HTTP/3 (QUIC)--> CloudFront (edge) --HTTP/2--> ALB --HTTP/1.1 or 2--> ECS app
     |                                    |                             |                      |
   TLS (Ch28)                     WAF inspects HERE (after TLS      version handling      app security on
   + HTTP version                 termination — Ch4,22,85);         (avoid unsafe          SEMANTICS (Part 5):
   (ALPN negotiated)              HTTP/3 inspected at edge          H2->H1 downgrade =     authN/authZ, headers,
                                  (QUIC visibility — Ch18,24)       smuggling — Ch57)      input validation

   Version-specific concerns: request smuggling (intermediary consistency — Ch57), HTTP/2 Rapid Reset DoS,
     HTTP/3 QUIC visibility (inspect at edge). Version-INDEPENDENT: application/API security on semantics.
```

The architectural principle: **HTTP's semantics are the stable, version-independent application-security
surface (authN/authZ, input validation, security headers — Part 5, Chapter 59), while the framing differs by
version and is where the version-specific security lives — request smuggling (intermediary parsing
consistency — Chapter 57), framing DoS (HTTP/2 Rapid Reset), and the HTTP/3 QUIC visibility shift (inspect at
termination).** In the request path, the edge (CloudFront/ALB) terminates TLS and the HTTP version, inspects
with the WAF (after termination), and must handle framing consistently (avoiding unsafe downgrades that enable
smuggling — Chapter 57); the app enforces security on the semantics (Part 5). The cloud security engineer's
job: prevent smuggling (consistency), patch/limit framing DoS, inspect at the right point (edge, especially
for HTTP/3), set security headers, and apply application security on the version-independent semantics. This
completes the request map's application-and-transport layers (Chapter 4) and sets up request smuggling
(Chapter 57) and API security (Part 5).

---

## 13. Common Mistakes

1. **Request smuggling from intermediary disagreement** (§4.2, §4.5) — inconsistent parsing / unsafe H2→H1
   downgrade; the marquee framing attack (Chapter 57).
2. **Unpatched HTTP/2 Rapid Reset** — the multiplexing DoS (§4.3).
3. **Not inspecting HTTP/3 at the edge** — losing visibility (QUIC encrypted transport — §4.4).
4. **WAF before TLS/HTTP termination** — can't inspect (Chapters 4, 22).
5. **Missing security headers** (HSTS/CSP/etc.) — client-side vulnerabilities (Chapter 59).
6. **Host header / X-Forwarded-For mishandling** — Host attacks, IP spoofing (§4.1).
7. **Assuming HTTP/2/3 eliminate smuggling** — downgrades re-introduce it (§4.3).
8. **Treating HTTP version as a security control** — application security is on the semantics
   (version-independent); the version affects framing-specific concerns only.

---

## 14. Troubleshooting

| Symptom / concern | Issue | Approach |
|---|---|---|
| Request smuggling suspected | intermediary parsing disagreement (CL/TE, H2→H1) | Chapter 57 testing; consistent parsing; reject ambiguity |
| DDoS via HTTP/2 | Rapid Reset (CVE-2023-44487) | patch; limit streams; rate-limit resets (§4.3) |
| HTTP/3 traffic not inspected | QUIC encrypted transport | inspect at edge termination; or block UDP/443 (§4.4, Ch18) |
| WAF not seeing requests | before termination | place WAF after TLS/HTTP termination (Chapters 4, 22) |
| Missing HSTS/CSP → client attacks | no security headers | set security headers (Chapter 59) |
| Host-header cache/reset poisoning | Host not validated | validate Host; strict vhost config (§4.1) |
| Wrong client IP in logs | X-Forwarded-For mishandled | correct proxy XFF config (Chapter 4 §Stop 5) |
| Which HTTP version is used? | negotiation | `curl -sI`; ALPN in TLS handshake (§6.1) |

---

## 15. Practical Lab

Lab 29.1 is in §8. Register it in the lab index. Extension: capture HTTP/1.1, HTTP/2, and (if available)
HTTP/3 requests in Wireshark (Chapter 24) and compare the framing — HTTP/1.1 text with CL/TE, HTTP/2 binary
frames/streams, HTTP/3 over QUIC/UDP (encrypted) — seeing the framing differences that underlie the
version-specific security (request smuggling surface, multiplexing, QUIC visibility). Then audit a site's
security headers and HTTP version handling. This sets up Chapter 57 (request smuggling) and Part 5 (API
security).

---

## 16. Exercises

### Concept questions

**29.1** Explain the distinction between HTTP semantics (version-independent) and framing (version-specific),
and where security lives at each.

**29.2** Explain how HTTP/1.1's framing (Content-Length/Transfer-Encoding) creates the request-smuggling
surface, and why it's a parsing-inconsistency attack.

**29.3** Explain HTTP/2's improvements (multiplexing) and the new DoS vector (Rapid Reset) it introduced.

**29.4** Explain HTTP/3's move to QUIC/UDP and the visibility shift, and how it relates to QUIC (Chapter 18)
and DoH (Chapter 17).

**29.5** Explain why intermediary consistency is a security property and how it relates to request smuggling
and the general interpretation-ambiguity pattern (Chapters 7, 22).

### Debugging problems

**29.6** A WAF is bypassed by a crafted request. What framing attack do you suspect, and how do you
investigate?

**29.7** A DDoS overwhelms an HTTP/2 server with minimal attacker bandwidth. Diagnose and remediate.

**29.8** HTTP/3 traffic is not being inspected by the network IDS. Explain and give options.

### Security scenarios

**29.9** Design the HTTP handling for a multi-intermediary request path (CDN → LB → app) to prevent request
smuggling and framing DoS while enabling inspection.

**29.10** Explain how application/API security is version-independent (on semantics) while framing concerns
are version-specific, and what this means for a security review.

### Architecture questions

**29.11** Explain how request smuggling exemplifies the interpretation-ambiguity attack pattern (bridge to
Chapters 7, 22, 57) and the general defense (consistency/normalization).

**29.12** Design HTTP version strategy (1.1/2/3) for a cloud application balancing performance, security, and
inspectability.

### Hands-on exercises

**29.13** Observe HTTP version negotiation (ALPN) and force different versions with curl.

**29.14** Audit a site's HTTP security headers and cookie attributes.

**29.15** Compare HTTP/1.1, HTTP/2, and HTTP/3 framing in Wireshark.

### Interview questions

**29.16** "What's the difference between HTTP/1.1, HTTP/2, and HTTP/3 from a security standpoint?"

**29.17** "What is HTTP request smuggling, at a high level?"

**29.18** "Why does HTTP/3's use of QUIC affect security visibility?"

**29.19** "Is application security different across HTTP versions?"

**29.20** "What was HTTP/2 Rapid Reset?"

---

## 17. Summary

- **HTTP's semantics (methods, headers, status codes, cookies, security headers) are stable across versions
  and are the version-independent application-security surface** — authN/authZ (Part 5), input validation,
  security headers (Chapter 59), and web vulnerabilities (Part 4) are the same regardless of HTTP version.
- **Framing differs by version and is where version-specific security lives:** **HTTP/1.1** is text-delimited
  (Content-Length/Transfer-Encoding — the **request-smuggling surface**); **HTTP/2** is binary-multiplexed
  over one TCP connection (fixing head-of-line blocking, but adding DoS vectors like **Rapid Reset** and
  downgrade smuggling); **HTTP/3** runs over **QUIC/UDP** (Chapter 18 — fixing TCP head-of-line blocking,
  shifting visibility — Chapter 24).
- **Request smuggling is the marquee HTTP framing attack** (Chapter 57) — front-end/back-end *disagreement*
  about request boundaries (CL/TE ambiguity, or H2→H1 downgrade translation) lets an attacker smuggle a
  request past front-end controls (WAF/auth bypass, response poisoning). It is a **parsing-inconsistency
  attack** — the same "two parties interpret the same bytes differently" root cause as encoding bypass
  (Chapter 7) and fragment evasion (Chapter 22); the defense is **consistency and normalization**.
- **Intermediary consistency is a security property** — every parser is a point of possible divergence; keep
  versions consistent end-to-end, reject ambiguous requests, normalize at the edge (Chapter 4 §Stop 5).
- **Version evolution has security side effects the engineer tracks:** HTTP/2 multiplexing → new DoS (Rapid
  Reset, efficiency cuts both ways); HTTP/3 QUIC → reduced network visibility (inspect at termination —
  Chapters 18, 24); downgrades → parsing inconsistencies (smuggling).
- **Application/API security operates on the stable semantics (version-independent)**, while the
  version-specific concerns (smuggling, framing DoS, QUIC visibility) are about framing/transport — completing
  the request map's application-and-transport layers (Chapter 4) and setting up request smuggling (Chapter 57)
  and API security (Part 5).

---

## 18. Knowledge Check

1. What is the distinction between HTTP semantics and framing, and where does security live at each? (§3, §5)
2. How does HTTP/1.1 framing create the request-smuggling surface? (§4.2)
3. What did HTTP/2 improve, and what DoS vector did it introduce? (§4.3)
4. What is HTTP/3's transport, and its visibility implication? (§4.4)
5. Why is request smuggling a parsing-inconsistency attack? (§4.2, §5)
6. Why is intermediary consistency a security property? (§4.5)
7. Is application security version-dependent? (§4.1, §5)
8. What is HTTP/2 Rapid Reset? (§4.3)
9. How does HTTP/3 relate to QUIC (Chapter 18) and DoH (Chapter 17)? (§4.4)
10. What are the version-specific security concerns to track? (§5)

---

## 19. Further Exploration

- The HTTP RFCs: RFC 9110 (HTTP semantics), 9112 (HTTP/1.1), 9113 (HTTP/2), 9114 (HTTP/3) — semantics vs
  framing per version.
- PortSwigger's HTTP Request Smuggling material and labs — the definitive request-smuggling resource (Chapter
  57).
- The HTTP/2 Rapid Reset (CVE-2023-44487) advisory — the multiplexing DoS (§4.3).
- Chapter 18 (QUIC) and Chapter 24 (packet analysis) for the HTTP/3 transport and visibility shift.
- Chapter 57 (request smuggling) — the marquee framing attack in depth; Chapter 59 (HTTP security model/
  headers); Part 5 (API security on the semantics).
- Chapter 30 next (SSH) — completing Part 1 with the secure-shell protocol; then Part 2 (Linux internals).

---

## Solutions

### 29.1
HTTP **semantics** — the *meaning* of a request/response: methods (GET/POST/etc.), headers (Host, Cookie,
Authorization, Content-Type, security headers), status codes (2xx/3xx/4xx/5xx), and cookies — are **stable
across versions** (HTTP/1.1, 2, 3 all express the same semantics). HTTP **framing** — how requests are
*delimited and multiplexed on the wire*: HTTP/1.1 uses text with Content-Length/Transfer-Encoding, HTTP/2 uses
binary multiplexed frames over one TCP connection, HTTP/3 uses QUIC streams over UDP — **differs by version**.
Security lives at each differently: **at the semantic layer** is the *application-security* surface — authN/
authZ (Chapter 4 §Stop 6, Part 5), input validation, security headers (Chapter 59), and the bulk of web
vulnerabilities (Part 4, e.g. SQLi, IDOR, XSS, CSRF) — and this is **version-independent** (an IDOR is an IDOR
regardless of HTTP version, because it's about the request's meaning). **At the framing layer** is the
*protocol-security* surface — the version-specific attacks: **request smuggling** (HTTP/1.1 CL/TE parsing
disagreement, or H2→H1 downgrade), **framing DoS** (HTTP/2 Rapid Reset), and the **HTTP/3 QUIC visibility
shift** — and this **is version-dependent** (about how requests are structured on the wire). So application/
API security is the same across versions (operate on semantics), while the version differences introduce
framing-specific concerns (smuggling, DoS, visibility) that the security engineer tracks. This distinction
tells a reviewer: apply application-security checks version-independently, and separately assess the
framing-specific concerns (intermediary consistency for smuggling, framing DoS patching, HTTP/3 inspection
point) per the versions in use.

### 29.17
HTTP request smuggling is an attack where a front-end intermediary (a CDN, load balancer, or reverse proxy)
and a back-end server *disagree* about where one HTTP request ends and the next begins, letting an attacker
"smuggle" a request that the front-end doesn't see but the back-end processes (or vice versa). It arises from
HTTP/1.1's two body-delimiting mechanisms — **Content-Length** (the body is N bytes) and **Transfer-Encoding:
chunked** (the body is chunks ending in a zero chunk) — when a request contains both (or malformed versions)
and the front-end and back-end honor *different* ones or parse them *differently*. The attacker crafts a
request so the front-end considers it complete at one boundary while the back-end sees additional bytes as the
start of *another* request, "smuggling" that request into the back-end. It can also arise in HTTP/2→HTTP/1.1
downgrade translation at a proxy. The impact is serious: the smuggled request bypasses front-end controls
(WAF, authentication), can be prepended to *another user's* request (poisoning their response, hijacking their
session), and can poison caches. At its root it's a **parsing-inconsistency attack** — "two parties interpret
the same bytes differently" — the same root cause as encoding bypass (Chapter 7) and fragment reassembly
evasion (Chapter 22). Defenses (Chapter 57): consistent parsing across intermediaries, rejecting ambiguous
requests (both Content-Length and Transfer-Encoding, or malformed), avoiding/securing HTTP/2→HTTP/1.1
downgrades, and normalizing at a single point — the general "consistency and normalization" defense for
interpretation-ambiguity attacks. Chapter 57 covers the mechanics and exploitation in depth; the key idea is
front-end/back-end request-boundary disagreement.

### 29.20
HTTP/2 Rapid Reset (CVE-2023-44487, disclosed October 2023) was a denial-of-service vulnerability exploiting
HTTP/2's **multiplexing** — the ability to have many concurrent streams over a single TCP connection. The
attack: the client rapidly opens a new stream (sending a request) and immediately cancels it (sending a
RST_STREAM frame) — over and over, at high rate. Because canceling a stream is cheap for the client but the
server still does work to set up and tear down each stream (and process the request), the attacker forces the
server to do large amounts of work with minimal attacker cost and bandwidth, and the rapid resets evade the
usual concurrent-stream limits (a canceled stream frees the slot immediately, so the attacker never hits the
limit). This produced record-breaking DDoS attacks against major providers (Google, Cloudflare, AWS reported
attacks of hundreds of millions of requests per second). It's an example of **multiplexing's efficiency
cutting both ways** — the same feature that lets HTTP/2 handle many requests efficiently over one connection
(fixing head-of-line blocking) lets an attacker cheaply generate enormous server work (like epoll enabling
both scale and DoS — Chapter 3 §5.3). Defenses: patch HTTP/2 implementations (the fix limits/accounts for
rapid resets), limit the rate of stream creation and resets per connection, cap concurrent streams, and use
edge DDoS protection (Chapter 85). It's the marquee example of an HTTP/2-framing-specific DoS vector, and a
reminder that new framing/multiplexing features bring new attack surfaces the security engineer must track.

---

*Next: Chapter 30 — SSH Internals: Transport, Authentication, Channels, Tunnels, and Key Hygiene. The final
chapter of Part 1 covers the secure-shell protocol — how SSH establishes a secure channel (its own crypto,
building on Chapters 25–28), key-based authentication (Chapter 26 keys), tunnels/port-forwarding, and the key
hygiene that is a core operational-security practice — completing the networking foundation before Part 2's
Linux internals.*
