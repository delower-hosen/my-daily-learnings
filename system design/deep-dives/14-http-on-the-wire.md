# Deep Dive 14 — HTTP/1.1, /2 and /3 on the wire

**Prerequisite:** [Chapter 13 §13.6](../13-networking.md) · [Deep Dive 12](12-tcp-mechanics.md) · [Deep Dive 13](13-tls-and-applied-cryptography.md)

**What the map said:** *"HTTP/2 multiplexes streams over one connection and compresses headers. HTTP/3 runs over QUIC and solves TCP head-of-line blocking. Delete your HTTP/1.1 workarounds."*

**What this deep dive does:** shows each protocol's actual bytes, explains why HTTP/1.1 pipelining failed and what that teaches, takes apart HPACK's dynamic table and the head-of-line blocking it *creates*, explains the flow-control window that silently caps your throughput at 655 KB/s per stream, walks QUIC's packets/frames/streams separation and why per-stream reliability is the whole point, explains QPACK's solution to HPACK's problem, covers connection migration, and ends with the operational realities — load balancing UDP, debugging encrypted transport, and request smuggling at protocol boundaries.

---

## Contents

```
1.  HTTP/1.1 on the wire
2.  Persistent connections and the pipelining failure
3.  ⭐ The six-connection limit and the workarounds it spawned
4.  Chunked transfer encoding
5.  ⭐ Request smuggling: when two parsers disagree
6.  HTTP/2: the binary framing layer
7.  Frame types, and what each is for
8.  Streams and stream states
9.  ⭐ HPACK: static table, dynamic table, Huffman
10. ⭐ HPACK's own head-of-line blocking
11. ⭐ Flow control — the setting that caps you at 655 KB/s
12. Server push, and why it was removed
13. Priority, and its replacement
14. ⭐ HTTP/2's remaining problem: TCP
15. QUIC: why UDP
16. ⭐ Packets, frames and streams — three different things
17. The QUIC handshake
18. ⭐ Loss recovery: why QUIC's is strictly better than TCP's
19. ⭐ QPACK: solving HPACK's problem
20. ⭐ Connection migration
21. HTTP/3 semantics and discovery
22. ⭐ Head-of-line blocking: the complete picture
23. Performance: when each protocol wins
24. ⭐ Operations: load balancing, debugging, CPU
25. What an architect takes from this
```

---

## 1. HTTP/1.1 on the wire

Plain text, line-oriented, human-readable. That is both its great strength and the source of §5.

```http
GET /api/v1/orders?limit=20 HTTP/1.1\r\n
Host: api.example.com\r\n
User-Agent: curl/8.4.0\r\n
Accept: application/json\r\n
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...\r\n
\r\n
```

```http
HTTP/1.1 200 OK\r\n
Content-Type: application/json\r\n
Content-Length: 1847\r\n
Cache-Control: private, max-age=60\r\n
\r\n
{"orders":[...]}
```

```
⭐ THE STRUCTURE:
   request-line / status-line, then headers, then CRLF CRLF, then body.
   ⭐ The body's length is determined by EITHER Content-Length
      OR Transfer-Encoding: chunked (§4).

   ⭐ That "either/or" is the entire basis of request smuggling (§5).
```

### The overhead nobody measures

```
⭐ A typical browser request carries 700-900 BYTES OF HEADERS —
   cookies, user-agent, accept-*, sec-fetch-*, and so on.

  ⭐ On a page making 100 requests: 70-90 KB of headers,
     ⭐ SENT IN FULL, UNCOMPRESSED, ON EVERY SINGLE REQUEST,
     even though 95% of them are byte-identical.

⭐ THIS IS THE SINGLE LARGEST WASTE IN HTTP/1.1, and it is what
   HPACK (§9) was designed to eliminate.
```

---

## 2. Persistent connections and the pipelining failure

### Keep-alive

```
HTTP/1.0: one request, one connection, close.
          ⭐ A new TCP handshake + slow start (Deep Dive 12 §12)
             for EVERY resource.

HTTP/1.1: ⭐ persistent connections are the DEFAULT.
          Connection: close is needed to opt out.
```

```
Connection: keep-alive
Keep-Alive: timeout=5, max=1000
```

**This alone was HTTP/1.1's biggest performance win** — it removed a TCP handshake and a cold `cwnd` from every resource fetch.

### ⭐ Pipelining — the good idea that failed

```
⭐ PIPELINING: send request 2 before response 1 arrives.

  Client ──► GET /a  GET /b  GET /c ──►  Server
  Client ◄── 200 /a  200 /b  200 /c ◄──  Server
```

```
⭐ WHY IT FAILED — four independent reasons:

  1. ⭐ RESPONSES MUST RETURN IN REQUEST ORDER.
     There is no request ID in HTTP/1.1 — responses are matched to
     requests purely by ORDER. ⭐ So if /a takes 5 seconds and /b
     takes 5 ms, /b's response WAITS.
     ⭐ THIS IS APPLICATION-LEVEL HEAD-OF-LINE BLOCKING, and it made
        pipelining actively harmful for mixed workloads.

  2. ⭐ BROKEN INTERMEDIARIES. Many proxies and servers mishandled
     pipelined requests — dropping, reordering, or corrupting them.

  3. ⭐ RETRY SAFETY. If the connection drops mid-pipeline, which
     requests were processed? Only idempotent requests could be
     safely retried.

  4. Head-of-line blocking also existed at the TCP layer beneath it.

⭐ RESULT: every major browser DISABLED pipelining by default.
   It is effectively dead.
```

> **The lesson that HTTP/2 learned from this:** ordering is the problem. **HTTP/2's stream IDs exist precisely so responses can return out of order** — which is what made multiplexing work where pipelining did not.

---

## 3. ⭐ The six-connection limit and the workarounds it spawned

```
⭐ Browsers limit concurrent connections to ~6 PER ORIGIN
   (hostname + port + scheme).

  ⭐ WHY: RFC 2616 originally suggested 2. Browsers raised it to 6
     as a compromise between parallelism and being a good network
     citizen — more connections means more competing TCP flows,
     each with its own cold slow start (Deep Dive 12 §12).
```

### The workarounds — and why they are now harmful

```
⭐ 1. DOMAIN SHARDING
     Serve assets from img1.example.com, img2.example.com, img3...
     ⭐ 3 shards × 6 connections = 18 parallel downloads.

     ⭐ HARMFUL UNDER HTTP/2: each shard needs its OWN TCP connection,
        its OWN TLS handshake, and its OWN cold cwnd — while HTTP/2
        would have multiplexed everything over ONE warm connection.
        ⭐ DELETE YOUR DOMAIN SHARDING.

⭐ 2. CONCATENATION (bundling all JS into one file)
     Avoided per-file request overhead.
     ⭐ COSTLY UNDER HTTP/2: one changed line invalidates the whole
        bundle's cache entry. Smaller files cache better.
     ⭐ (Though note: compression works better on one large file,
        so this one is a genuine trade-off, not a pure win.)

⭐ 3. SPRITE SHEETS (combining images)
     Same reasoning. ⭐ Largely obsolete.

⭐ 4. INLINING (data: URIs in CSS/HTML)
     ⭐ Still harmful — inlined content cannot be cached separately
        and bloats the HTML on every load.
```

> **If your build pipeline still does domain sharding, aggressive concatenation or sprite generation, those are HTTP/1.1 artefacts that are now costing you.** Chapter 13 §13.6 said to delete them; this is why.

---

## 4. Chunked transfer encoding

```
⭐ THE PROBLEM: how do you send a response whose length you do not
   know in advance (a streamed database result, a generated report)?

⭐ Without Content-Length, HTTP/1.0 had to close the connection
   to signal the end — destroying keep-alive.
```

```http
HTTP/1.1 200 OK\r\n
Transfer-Encoding: chunked\r\n
\r\n
1a\r\n                          ⭐ chunk size in HEX (26 bytes)
{"orders":[{"id":1,"tot\r\n
15\r\n                          ⭐ 21 bytes
al":100}],"more":true}\r\n
0\r\n                           ⭐ zero-length chunk = END
\r\n                            ⭐ (optional trailers go here)
```

```
⭐ USES:
   • Streaming responses of unknown length
   • ⭐ Server-Sent Events (Chapter 08 §8.15)
   • Long-polling
   • ⭐ Trailers — headers sent AFTER the body (e.g. a checksum,
     or gRPC's trailing status)

⭐ AND: a request may also be chunked, which is where §5 begins.
```

---

## 5. ⭐ Request smuggling: when two parsers disagree

A vulnerability class that exists purely because HTTP/1.1 has **two** ways to express body length, and intermediaries may disagree about which wins.

```
⭐ THE SETUP: a front-end proxy and a back-end server, reusing a
   connection between them (which is normal and desirable).

⭐ THE ATTACK: craft a request that the FRONT-END parses as one
   request but the BACK-END parses as two.
   ⭐ The remainder is PREPENDED TO THE NEXT USER'S REQUEST.
```

### CL.TE — front-end uses Content-Length, back-end uses Transfer-Encoding

```http
POST /search HTTP/1.1
Host: example.com
Content-Length: 49
Transfer-Encoding: chunked

0

GET /admin HTTP/1.1
X-Ignore: x
```

```
⭐ FRONT-END (uses Content-Length: 49): forwards all 49 bytes as ONE request.

⭐ BACK-END (uses Transfer-Encoding): reads the "0\r\n\r\n" chunk
   terminator and considers the request FINISHED there.
   ⭐ The remaining bytes — "GET /admin HTTP/1.1..." — sit in the
      connection buffer.

⭐ THE NEXT USER'S REQUEST on that connection is APPENDED to the
   smuggled prefix:

     GET /admin HTTP/1.1
     X-Ignore: xGET /their-page HTTP/1.1
     Cookie: their-session=...

   ⭐ The attacker's /admin request now executes WITH THE VICTIM'S
      SESSION COOKIE.
```

### ⭐ The HTTP/2 downgrade variant

```
⭐ EVEN IF YOUR EDGE SPEAKS HTTP/2, if it DOWNGRADES to HTTP/1.1 for
   the back-end, the length must be RE-EXPRESSED as Content-Length
   or chunked.

  ⭐ In HTTP/2, length is IMPLICIT in the framing — there is no
     ambiguity. But a malicious HTTP/2 request can include an explicit
     content-length header that CONTRADICTS the actual frame length.

  ⭐ If the downgrading proxy trusts the header rather than the frames,
     it reintroduces smuggling on a connection that should have been
     immune — this is "H2.CL" / "H2.TE" smuggling, and it has been
     found in many major products.
```

### The defences

```
⭐ 1. REJECT AMBIGUOUS REQUESTS. If both Content-Length and
   Transfer-Encoding are present, ⭐ RETURN 400. Do not choose.
   (RFC 9112 says TE wins, but the correct behaviour for a
   security-conscious proxy is refusal.)

⭐ 2. USE HTTP/2 END-TO-END. No downgrade means no re-expression
   means no disagreement.

⭐ 3. VALIDATE ON DOWNGRADE. A proxy translating h2 → h1 must
   ⭐ IGNORE the client's content-length header and use the actual
   frame lengths.

⭐ 4. DO NOT REUSE BACK-END CONNECTIONS across different clients —
   expensive, but it makes the attack impossible.

⭐ 5. NORMALISE strictly: reject obfuscated headers
   ("Transfer-Encoding: chunked\r\n" with odd whitespace, duplicated
   headers, "chunked, identity").
```

> **This is an architectural concern, not just an application one.** It lives at the boundary between two components, which is exactly where Chapter 24 §24.8's "layers of translation" warning applies. Any time two parsers interpret the same bytes, ask whether they can disagree.

---

## 6. HTTP/2: the binary framing layer

```
⭐ HTTP/2 KEEPS HTTP'S SEMANTICS (methods, status codes, headers)
   AND REPLACES ITS SYNTAX ENTIRELY.

  ⭐ Everything is a binary FRAME. Frames belong to STREAMS.
     Streams are multiplexed over ONE TCP connection.
```

```
 ┌──────────────────────────────────────────────────────────────┐
 │ Length (24 bits)                                             │
 ├───────────────┬──────────────────────────────────────────────┤
 │ Type (8)      │ Flags (8)                                    │
 ├─┬─────────────┴──────────────────────────────────────────────┤
 │R│ ⭐ Stream Identifier (31 bits)                              │
 ├─┴────────────────────────────────────────────────────────────┤
 │ Frame Payload                                                 │
 └──────────────────────────────────────────────────────────────┘
   ⭐ 9-byte header. Default max payload 16,384 bytes
      (SETTINGS_MAX_FRAME_SIZE, up to 2²⁴−1).
```

```
⭐ THE KEY FIELD IS THE STREAM IDENTIFIER.

  It is what pipelining lacked (§2). Because every frame names its
  stream, ⭐ RESPONSES CAN RETURN IN ANY ORDER, and a slow response
  does not block a fast one.
```

```
⭐ STREAM ID RULES:
   • ⭐ Client-initiated streams are ODD (1, 3, 5, ...)
   • ⭐ Server-initiated (push) streams are EVEN (2, 4, ...)
   • ⭐ Stream 0 is the CONNECTION control stream (SETTINGS, PING,
     GOAWAY, connection-level WINDOW_UPDATE)
   • ⭐ IDs only ever INCREASE and are never reused — which bounds
     a connection's lifetime at 2³¹ streams.
```

### The connection preface

```
⭐ Every HTTP/2 connection begins with a fixed 24-byte magic string:

     PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n

  ⭐ It is deliberately chosen so an HTTP/1.1 server parsing it
     produces an error rather than doing something dangerous.
     ("PRI" and "SM" spell out a joke about the earlier SPDY name.)

  Followed by a SETTINGS frame from each side.
```

---

## 7. Frame types, and what each is for

| Type | Name | Purpose |
|------|------|---------|
| 0x0 | **DATA** | Request/response body |
| 0x1 | **HEADERS** | ⭐ HPACK-compressed header block; opens a stream |
| 0x2 | PRIORITY | ⭐ Deprecated (§13) |
| 0x3 | **RST_STREAM** | ⭐ Abort one stream without closing the connection |
| 0x4 | **SETTINGS** | Connection parameters (§11) |
| 0x5 | PUSH_PROMISE | ⭐ Server push — removed in practice (§12) |
| 0x6 | **PING** | ⭐ Liveness and RTT measurement |
| 0x7 | **GOAWAY** | ⭐ Graceful connection shutdown, naming the last stream processed |
| 0x8 | **WINDOW_UPDATE** | ⭐ Flow control credit (§11) |
| 0x9 | CONTINUATION | A header block too large for one frame |

### ⭐ GOAWAY — the one that matters for deploys

```
⭐ GOAWAY carries the LAST STREAM ID THE SENDER PROCESSED.

  ⭐ THEREFORE the client knows EXACTLY which requests were handled
     and which were not — and can safely retry the unprocessed ones
     on a new connection.

⭐ THIS IS WHAT MAKES GRACEFUL HTTP/2 SHUTDOWN POSSIBLE, and it is
   the mechanism behind zero-downtime deploys for gRPC and HTTP/2
   services (Chapter 15 §15.8).

⭐ THE TWO-GOAWAY PATTERN used by well-behaved servers:
   1. Send GOAWAY with last_stream_id = 2³¹−1 ("I am shutting down,
      stop opening new streams") but keep serving
   2. Wait a grace period for in-flight streams
   3. Send a second GOAWAY with the real last processed stream ID
   4. Close

   ⭐ Without this, a rolling deploy drops in-flight requests, and
      the client cannot tell which ones to retry.
```

### ⭐ RST_STREAM and the Rapid Reset attack

```
⭐ RST_STREAM cancels ONE stream cheaply. That is normally useful —
   a browser navigating away cancels in-flight requests.

⭐ CVE-2023-44487 "HTTP/2 RAPID RESET" (October 2023) weaponised it:

   The attacker opens a stream and IMMEDIATELY sends RST_STREAM,
   repeatedly, as fast as the connection allows.

   ⭐ The cancelled stream no longer counts against
      SETTINGS_MAX_CONCURRENT_STREAMS — but the SERVER HAS ALREADY
      STARTED PROCESSING IT.

   ⭐ RESULT: unbounded request rate from a single connection,
      bypassing the concurrency limit entirely. It produced the
      largest DDoS attacks recorded at the time (398 million rps).

⭐ THE FIX: track and rate-limit RST_STREAM frames per connection,
   and close connections that exceed a threshold. ⭐ Every major
   server and proxy shipped a patch. Verify yours is current.
```

---

## 8. Streams and stream states

```
                            ┌────────┐
                            │  idle  │
                            └───┬────┘
                   send/recv HEADERS
                            ┌───▼────┐
              ┌─────────────│  open  │─────────────┐
      send ES │             └────────┘             │ recv ES
              ▼                                     ▼
     ┌──────────────────┐              ┌──────────────────┐
     │ half-closed      │              │ half-closed      │
     │ (local)          │              │ (remote)         │
     │ ⭐ I finished     │              │ ⭐ they finished  │
     │ sending           │              │ sending          │
     └────────┬─────────┘              └────────┬─────────┘
              │ recv ES / RST_STREAM             │ send ES / RST_STREAM
              └──────────────┬───────────────────┘
                        ┌────▼────┐
                        │ closed  │
                        └─────────┘
    (ES = END_STREAM flag)
```

```
⭐ "HALF-CLOSED" IS THE STATE THAT MAKES STREAMING WORK:

  A client can finish sending its request (half-closed local) while
  the server continues sending a response for minutes.
  ⭐ This is how gRPC server-streaming and SSE-over-HTTP/2 work.

  ⭐ And both directions can stay open simultaneously — that is
     gRPC BIDIRECTIONAL streaming.
```

### `SETTINGS_MAX_CONCURRENT_STREAMS`

```
⭐ The limit on simultaneously-open streams per connection.

  ⭐ The RFC RECOMMENDS at least 100. Common values:
       nginx:  http2_max_concurrent_streams 128
       Go:     250
       ⭐ Some servers default to 100 — which for a gRPC client
          multiplexing heavily can become a bottleneck.

⭐ WHEN EXCEEDED: new streams are REFUSED with RST_STREAM
   (REFUSED_STREAM), and a well-behaved client queues them —
   ⭐ producing latency that looks like server slowness but is
      actually a concurrency cap.
```

---

## 9. ⭐ HPACK: static table, dynamic table, Huffman

The mechanism that eliminates §1's 70–90 KB of repeated headers.

### Three compression mechanisms, combined

```
⭐ 1. THE STATIC TABLE — 61 predefined, universally-known entries.

   Index  Name              Value
     2    :method           GET
     3    :method           POST
     4    :path             /
     8    :status           200
    16    accept-encoding   gzip, deflate
    ...

   ⭐ ":method GET" becomes ONE BYTE: 0x82 (indexed, index 2).

⭐ 2. THE DYNAMIC TABLE — per-connection, built as headers are sent.
   Both sides maintain an IDENTICAL copy.
   ⭐ FIFO eviction when it exceeds SETTINGS_HEADER_TABLE_SIZE
      (default 4096 bytes).

⭐ 3. HUFFMAN CODING for literal strings, using a static Huffman table
   optimised for HTTP header characters. ⭐ ~30% reduction on typical
   header values.
```

### The representations

```
⭐ 1. INDEXED HEADER FIELD              → 1 byte
      "the header at index N" — both name AND value from a table

⭐ 2. LITERAL WITH INCREMENTAL INDEXING → name (maybe indexed) + value
      ⭐ AND ADD IT TO THE DYNAMIC TABLE for next time

⭐ 3. LITERAL WITHOUT INDEXING          → sent, not stored
      ⭐ For values that change every request (a nonce, a timestamp)

⭐ 4. LITERAL NEVER INDEXED             → sent, not stored, and
      ⭐ intermediaries MUST NOT index it either
      ⭐ For SENSITIVE values — this is the CRIME/BREACH defence (below)
```

### Worked example

```
REQUEST 1 (a fresh connection):
  :method: GET              → static index 2        ⭐ 1 byte
  :scheme: https            → static index 7        ⭐ 1 byte
  :path: /api/v1/orders     → literal + index       ~18 bytes (Huffman)
  :authority: api.example.com → literal + index     ~14 bytes
  user-agent: Mozilla/5.0 (...)  → literal + index  ~60 bytes
  cookie: session=abc123...      → literal + index  ~40 bytes
                                                    ─────────
                                            ⭐ ~134 bytes
                                    (vs ~700 bytes uncompressed)

REQUEST 2 (same connection, different path):
  :method: GET              → static index 2        ⭐ 1 byte
  :scheme: https            → static index 7        ⭐ 1 byte
  :path: /api/v1/products   → literal                ~20 bytes
  :authority:               → ⭐ DYNAMIC index       ⭐ 1 byte
  user-agent:               → ⭐ DYNAMIC index       ⭐ 1 byte
  cookie:                   → ⭐ DYNAMIC index       ⭐ 1 byte
                                                    ─────────
                                            ⭐ ~25 bytes
                                    ⭐ vs ~700 uncompressed = 96% saved
```

```
⭐ MEASURED REAL-WORLD HPACK COMPRESSION: 80-90% on typical browser
   traffic. On a page with 100 requests, that is ⭐ ~70 KB saved —
   often more than one full TCP congestion window (Deep Dive 12 §12),
   so it directly reduces round trips.
```

### ⭐ The security requirement: `never indexed`

```
⭐ COMPRESSION + ATTACKER-CONTROLLED INPUT + A SECRET IN THE SAME
   CONTEXT = A COMPRESSION ORACLE.

  ⭐ This is CRIME (2012) and BREACH (2013). The attacker injects
     guesses and watches the compressed size: a correct guess
     compresses better, revealing the secret byte by byte.

⭐ HPACK's defence:
   • ⭐ Huffman coding is applied per-string, not across the whole
     header block, which limits the oracle
   • ⭐ "LITERAL NEVER INDEXED" tells every hop never to place the
     value in a dynamic table

⭐ USE IT FOR: session cookies, Authorization headers, CSRF tokens,
   API keys. Most HTTP/2 libraries expose a flag; ⭐ most applications
   never set it.
```

---

## 10. ⭐ HPACK's own head-of-line blocking

An under-appreciated subtlety, and the direct reason QPACK exists.

```
⭐ THE DYNAMIC TABLE IS SHARED ACROSS ALL STREAMS AND IS
   ORDER-DEPENDENT.

  Header block on stream 5 says "use dynamic entry 62".
  ⭐ Entry 62 was created by the header block on stream 3.

  ⭐ THEREFORE: header blocks MUST BE DECODED IN THE ORDER THEY
     WERE ENCODED. The decoder cannot skip ahead.
```

```
⭐ UNDER TCP THIS IS INVISIBLE, because TCP already delivers
   everything in order (Deep Dive 12 §18).

⭐ BUT IT MEANS: even if you fixed the transport to deliver streams
   independently, ⭐ HPACK WOULD STILL SERIALISE HEADER DECODING.

  ⭐ So simply putting HTTP/2 on top of QUIC would NOT have removed
     head-of-line blocking — the header compression would have
     reintroduced it.
```

> **This is why HTTP/3 needed a new header compression scheme (QPACK, §19), not just a new transport.** It is a good illustration of how a layering assumption baked into one component can defeat an improvement in another.

---

## 11. ⭐ Flow control — the setting that caps you at 655 KB/s

HTTP/2 has its own flow control, **separate from and in addition to TCP's**. It is one of the most commonly mis-tuned things in HTTP/2 deployments.

```
⭐ TWO LEVELS, and BOTH must have credit:

  1. ⭐ PER-STREAM window
  2. ⭐ PER-CONNECTION window (stream 0)

⭐ A sender may transmit DATA only if BOTH windows allow it.
   Only DATA frames are flow-controlled; HEADERS and control frames
   are not.
```

```
⭐ THE DEFAULT INITIAL WINDOW: 65,535 BYTES. For both levels.
```

### ⭐ The arithmetic — this is the important part

```
⭐ Just as with TCP (Deep Dive 12 §11):

     THROUGHPUT ≤ WINDOW / RTT

  ⭐ With the default 65,535-byte window:

     RTT   1 ms  →  65,535 / 0.001 = 65 MB/s     ✓ fine
     RTT  50 ms  →  65,535 / 0.05  = 1.3 MB/s    ⚠
     ⭐ RTT 100 ms → 65,535 / 0.1  = 655 KB/s    ❌ = 5.2 Mbps
     ⭐ RTT 250 ms → 65,535 / 0.25 = 262 KB/s    ❌ = 2 Mbps
```

```
⭐ AND THE CONNECTION-LEVEL WINDOW IS SHARED ACROSS ALL STREAMS.

   ⭐ 10 concurrent streams sharing a 65,535-byte connection window
      get 6.5 KB each. The multiplexing you enabled HTTP/2 for is
      throttled to nothing.
```

```
⭐ THE SYMPTOM: "HTTP/2 is SLOWER than HTTP/1.1 for large downloads
   over long distances."

  ⭐ It is real, it is common, and it is entirely this setting.
     HTTP/1.1's six connections each got a full TCP window;
     HTTP/2's single connection is capped by an application-layer
     window nobody raised.
```

### The fix

```nginx
# nginx
http2_body_preread_size 64k;
# ⭐ nginx sets the HTTP/2 window from these; modern versions
#   auto-tune, but verify on your version.
```

```go
// ⭐ Go's http2 server — raise BOTH
server := &http2.Server{
    MaxUploadBufferPerConnection: 1 << 20,  // ⭐ 1 MB connection window
    MaxUploadBufferPerStream:     1 << 20,  // ⭐ 1 MB stream window
}
```

```
⭐ SIZING: window ≥ bandwidth-delay product, exactly as for TCP.

   100 Mbps × 100 ms = 1.25 MB  → ⭐ set 2 MB or more
   ⭐ AND raise the CONNECTION window to N × the stream window,
      where N is your expected concurrent stream count.
```

```
⭐ gRPC USERS: this is THE most common cause of poor gRPC throughput
   over WAN links. gRPC-go exposes:
       grpc.InitialWindowSize(1 << 20)
       grpc.InitialConnWindowSize(1 << 24)
   ⭐ The defaults are the RFC's 65,535 and they are far too small
      for anything but a datacenter.
```

---

## 12. Server push, and why it was removed

```
⭐ THE IDEA: the server sends resources the client has not yet
   requested but will need — pushing style.css alongside index.html,
   saving a round trip.

  PUSH_PROMISE on stream 1 → "I am about to send you /style.css
                              on stream 2"
```

```
⭐ WHY IT FAILED, and this is instructive:

  1. ⭐ THE SERVER DOES NOT KNOW WHAT THE CLIENT HAS CACHED.
     Pushing a resource the browser already has is pure waste.
     ⭐ Cache digests were proposed to fix this and never shipped.

  2. ⭐ IT COMPETES WITH THE HTML ITSELF for the connection's
     bandwidth and flow-control window (§11) — sometimes making
     the page SLOWER.

  3. ⭐ Measured benefits were small and inconsistent; Chrome's
     telemetry found it was net-negative for most sites.

  4. Complex to implement correctly in servers, CDNs and frameworks.

⭐ CHROME REMOVED SERVER PUSH SUPPORT IN 2022. It is effectively dead.
```

### ⭐ What replaced it: 103 Early Hints

```http
HTTP/1.1 103 Early Hints
Link: </style.css>; rel=preload; as=style
Link: </app.js>; rel=preload; as=script

HTTP/1.1 200 OK                     ⭐ the real response, later
Content-Type: text/html
...
```

```
⭐ THE KEY DIFFERENCE: the server TELLS the client what it will need
   and lets the CLIENT decide whether to fetch it.

   ⭐ The client knows its own cache. It fetches only what it lacks.
   ⭐ The 103 can be sent IMMEDIATELY, while the server is still
      generating the real response — so the client starts fetching
      assets during the server's think time.

⭐ This is a better design for the same reason the Outbox pattern
   is better than a dual write: the party with the information makes
   the decision.
```

---

## 13. Priority, and its replacement

```
⭐ HTTP/2's ORIGINAL PRIORITY SCHEME: a dependency TREE with weights.
   Stream 5 depends on stream 3 with weight 128, exclusive flag, ...

⭐ IT WAS A FAILURE:
   • Extremely complex to implement correctly
   • ⭐ Servers implemented it inconsistently or ignored it
   • Browsers built different trees, so behaviour varied wildly
   • ⭐ It was formally DEPRECATED in RFC 9113
```

### ⭐ The replacement: RFC 9218

```http
Priority: u=1, i
          ^^^  ^
          │    └─ ⭐ incremental: render progressively as it arrives
          └────── ⭐ urgency 0-7 (0 = highest, 3 = default)
```

```
⭐ Sent either as an HTTP header, or as a PRIORITY_UPDATE frame
   to change priority mid-stream.

⭐ WHY IT IS BETTER: it is a simple scalar plus one flag. Both
   sides can implement it correctly, and the semantics are obvious.

⭐ TYPICAL BROWSER USAGE:
     u=0  blocking CSS, fonts
     u=1  scripts
     u=3  images (default)
     u=5  prefetch, analytics beacons
```

**The pattern is the same as TLS 1.3's (Deep Dive 13 §3): a complex, negotiable mechanism replaced by a simple one that implementations get right.**

---

## 14. ⭐ HTTP/2's remaining problem: TCP

```
⭐ HTTP/2 SOLVED APPLICATION-LEVEL HEAD-OF-LINE BLOCKING.
⭐ IT DID NOT — AND COULD NOT — SOLVE TCP-LEVEL HEAD-OF-LINE
   BLOCKING (Deep Dive 12 §18).
```

```
  TCP byte stream:  [stream 1][stream 3][⭐ LOST ][stream 5][stream 7]
                                            ▲
  ⭐ ONE lost TCP segment. TCP will not deliver ANY subsequent bytes
     to the application until it is retransmitted —
     ⭐ EVEN THOUGH streams 5 and 7 ARRIVED INTACT and belong to
        completely unrelated requests.

  ⭐ EVERY MULTIPLEXED STREAM STALLS.
```

### ⭐ The consequence people find surprising

```
⭐ ON A LOSSY LINK, HTTP/2 CAN BE SLOWER THAN HTTP/1.1.

  HTTP/1.1 with 6 connections: a loss on one connection blocks
  ⭐ ONE SIXTH of the traffic.

  HTTP/2 with 1 connection: a loss blocks ⭐ ALL of it.
```

```
⭐ MEASURED: at 2% packet loss, HTTP/2 page load times are frequently
   WORSE than HTTP/1.1. At 0% loss, HTTP/2 is clearly better.

⭐ Since mobile networks routinely see 1-3% loss, this was not a
   theoretical concern — it was a significant fraction of real users.
```

> **This single problem is why QUIC exists.** Everything in §15–20 follows from "we need multiplexing without a shared ordered byte stream underneath."

---

## 15. QUIC: why UDP

```
⭐ THE REQUIREMENT: independent, reliable, ordered streams — with
   loss in one not affecting the others.

⭐ TCP CANNOT PROVIDE THIS. Its contract is "one ordered byte stream",
   and that is precisely the problem.
```

### Why not a new transport protocol?

```
⭐ OSSIFICATION.

  Middleboxes — NATs, firewalls, load balancers, "optimisers" —
  inspect and modify TCP. ⭐ A NEW IP PROTOCOL NUMBER IS DROPPED BY
  A LARGE FRACTION OF THE INTERNET. SCTP and DCCP both died this way.

  ⭐ Even new TCP OPTIONS are frequently stripped (Deep Dive 12 §10's
     window scaling problem).
```

```
⭐ SO QUIC IS BUILT ON UDP — not because UDP is a good transport,
   but because ⭐ UDP IS A HOLE THROUGH THE MIDDLEBOXES.

⭐ AND EVERYTHING ABOVE THE UDP HEADER IS ENCRYPTED — including
   most of QUIC's own headers. ⭐ THIS IS DELIBERATE: it makes the
   protocol UNINSPECTABLE and therefore ⭐ UNOSSIFIABLE. Middleboxes
   cannot come to depend on internals they cannot see, so QUIC can
   keep evolving.

⭐ That is a genuinely novel design goal: encryption as a mechanism
   for protocol evolvability, not only for confidentiality.
```

```
⭐ AND QUIC LIVES IN USER SPACE, not the kernel. So a browser or
   server can ship a new congestion controller or loss-recovery
   algorithm with a software update, rather than waiting years for
   OS kernels to deploy it.
```

---

## 16. ⭐ Packets, frames and streams — three different things

The layering people most often confuse.

```
┌─ UDP DATAGRAM ─────────────────────────────────────────────┐
│ ┌─ ⭐ QUIC PACKET ───────────────────────────────────────┐ │
│ │ Header: ⭐ Connection ID, ⭐ Packet Number             │ │
│ │ ┌────────────────────────────────────────────────────┐ │ │
│ │ │ ⭐ ENCRYPTED PAYLOAD — a sequence of FRAMES:        │ │ │
│ │ │   STREAM frame (stream 0, offset 0, data)          │ │ │
│ │ │   STREAM frame (stream 4, offset 1200, data)       │ │ │
│ │ │   ACK frame                                         │ │ │
│ │ │   MAX_DATA frame                                    │ │ │
│ │ └────────────────────────────────────────────────────┘ │ │
│ └────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

```
⭐ PACKET  — the unit of TRANSMISSION and of LOSS DETECTION.
            Has a packet number. Is acknowledged. ⭐ Never retransmitted.

⭐ FRAME   — the unit of INFORMATION. Many frames per packet.
            ⭐ Frames from DIFFERENT streams can share one packet.

⭐ STREAM  — the unit of APPLICATION ORDERING. Identified by a stream ID.
            ⭐ Each stream is INDEPENDENTLY ordered and reliable.
```

### ⭐ The separation that makes everything work

```
⭐ "PACKETS ARE NEVER RETRANSMITTED."

  ⭐ In TCP, a lost segment is retransmitted WITH THE SAME SEQUENCE
     NUMBER. So when an ACK arrives, the sender ⭐ CANNOT TELL whether
     it acknowledges the original or the retransmission.
     ⭐ This is TCP's RETRANSMISSION AMBIGUITY, and it corrupts
        RTT measurement (Deep Dive 12 §17).

  ⭐ In QUIC, if packet 42 is lost, its FRAMES are re-sent in a NEW
     packet, number 57. ⭐ Packet numbers strictly increase and are
     never reused.

  ⭐ THEREFORE: every ACK unambiguously identifies exactly one
     transmission. ⭐ RTT measurement is exact. Loss detection is exact.
```

### Frame types worth knowing

```
STREAM            ⭐ application data, with a stream ID and a byte offset
ACK               ⭐ up to 256 ACK ranges (vs TCP SACK's 3-4)
CRYPTO            ⭐ TLS handshake data — carried in frames, not a stream
MAX_DATA          connection-level flow control credit
MAX_STREAM_DATA   stream-level flow control credit
RESET_STREAM      abort one stream
CONNECTION_CLOSE  terminate
PATH_CHALLENGE /  ⭐ path validation for connection migration (§20)
PATH_RESPONSE
NEW_CONNECTION_ID ⭐ supply alternative connection IDs (§20)
```

```
⭐ THE ACK RANGE COUNT IS A REAL ADVANTAGE. TCP SACK fits only
   3-4 blocks in the options field (40 bytes). ⭐ QUIC can report
   256 discontiguous ranges, so under heavy loss the sender learns
   far more precisely what arrived — dramatically improving recovery
   on bad links.
```

---

## 17. The QUIC handshake

```
⭐ QUIC INTEGRATES TLS 1.3 RATHER THAN LAYERING ON TOP OF IT.

  The TLS handshake messages travel in ⭐ CRYPTO frames inside QUIC
  packets. There is no separate "TLS record layer".
```

```
CLIENT                                              SERVER
  │──── Initial[CRYPTO: ClientHello] ────────────────►│
  │       ⭐ + QUIC transport parameters as a TLS extension
  │                                                    │
  │◄─── Initial[CRYPTO: ServerHello] ──────────────────│
  │◄─── Handshake[CRYPTO: EncryptedExtensions,
  │                       Certificate, CertVerify,
  │                       Finished] ───────────────────│
  │                                                    │
  │──── Handshake[CRYPTO: Finished] ──────────────────►│
  │◄══════ 1-RTT APPLICATION DATA ═══════════════════►│
```

```
⭐ THE COMPARISON THAT MATTERS:

   TCP + TLS 1.3:  ⭐ 1 RTT (TCP) + 1 RTT (TLS) = 2 RTT
   ⭐ QUIC:        ⭐ 1 RTT TOTAL

   ⭐ On a 100 ms path: 200 ms → 100 ms before the first byte of
      the HTTP request. A 50% reduction in connection setup.

   ⭐ And with 0-RTT resumption: 0 RTT — with all of Deep Dive 13 §14's
      replay caveats, which apply identically.
```

### ⭐ Packet number spaces

```
⭐ QUIC uses THREE SEPARATE packet number spaces:
     Initial, Handshake, Application

⭐ WHY: handshake packets are protected with different keys than
   application packets. Separate spaces mean ⭐ a loss in the handshake
   cannot be confused with a loss in application data, and each space
   has its own ACK state and its own loss recovery.

⭐ This is the same key-separation principle as TLS 1.3's key
   schedule (Deep Dive 13 §7), applied to the transport.
```

### The amplification defence

```
⭐ UDP IS SPOOFABLE. An attacker sends a small Initial packet with a
   forged source address; the server replies with a large certificate
   chain to the victim. ⭐ A reflection amplification attack.

⭐ QUIC'S RULE: a server MUST NOT send more than ⭐ 3× the bytes it
   has received from an unvalidated address.

⭐ CONSEQUENCE: a large certificate chain may not fit in the
   amplification budget, forcing the client to send padding or an
   extra round trip. ⭐ This is a real argument for SMALL CERTIFICATE
   CHAINS (ECDSA over RSA — Deep Dive 13 §21) in a QUIC deployment.
```

---

## 18. ⭐ Loss recovery: why QUIC's is strictly better

```
⭐ QUIC'S ADVANTAGES OVER TCP, each a direct consequence of §16:

  1. ⭐ NO RETRANSMISSION AMBIGUITY.
     Packet numbers never repeat → every RTT sample is exact.
     ⭐ TCP's Karn's algorithm has to DISCARD RTT samples from
        retransmitted segments; QUIC never needs to.

  2. ⭐ MONOTONIC PACKET NUMBERS make reordering trivially
     distinguishable from loss.

  3. ⭐ 256 ACK RANGES vs TCP SACK's 3-4.

  4. ⭐ EXPLICIT ACK DELAY: the receiver reports how long it delayed
     the ACK, so the sender subtracts it from the RTT sample.
     ⭐ TCP's delayed ACK (Deep Dive 12 §16) silently inflates RTT
        estimates; QUIC measures around it.

  5. ⭐ PER-STREAM DELIVERY. A lost STREAM frame for stream 3 blocks
     only stream 3. Streams 5 and 7 are delivered to the application
     immediately.
     ⭐ THIS IS THE ENTIRE POINT.

  6. ⭐ USER-SPACE IMPLEMENTATION: congestion control and loss
     recovery ship with the application, not the kernel.
```

```
⭐ THE TRACED DIFFERENCE:

  Packets carrying: [s1 data][s3 data][⭐LOST: s5 data][s7 data]

  ⭐ TCP:   streams 1, 3 delivered. ⭐ Stream 7 is HELD IN THE KERNEL
           until the lost segment is retransmitted (~1 RTT, or an RTO).
           ⭐ ALL streams stall.

  ⭐ QUIC:  streams 1, 3 delivered. ⭐ STREAM 7 DELIVERED IMMEDIATELY.
           ⭐ Only stream 5 waits for retransmission.
```

---

## 19. ⭐ QPACK: solving HPACK's problem

From §10: HPACK's dynamic table forces in-order header decoding, which would reintroduce head-of-line blocking even over QUIC.

```
⭐ QPACK'S SOLUTION: separate the TABLE UPDATES from the
   HEADER REFERENCES, onto dedicated unidirectional streams.

  ⭐ ENCODER STREAM  (unidirectional, encoder → decoder)
       carries INSTRUCTIONS that add entries to the dynamic table

  ⭐ DECODER STREAM  (unidirectional, decoder → encoder)
       ACKNOWLEDGES which entries have been received

  ⭐ REQUEST STREAMS carry header blocks that REFERENCE table entries
       by ABSOLUTE index, plus a ⭐ "Required Insert Count"
```

```
⭐ THE MECHANISM:

  A header block declares: "I need the dynamic table to contain at
  least N entries before you can decode me."

  ⭐ If the decoder has fewer than N, ⭐ THAT STREAM BLOCKS —
     and ONLY that stream. All other streams decode normally.
```

### ⭐ The tunable trade-off

```
⭐ AN ENCODER CAN CHOOSE ITS RISK:

  ⭐ AGGRESSIVE: reference entries that have been SENT but not yet
     ACKNOWLEDGED.
     ✅ Best compression
     ❌ ⭐ If the encoder-stream instruction is lost, the referencing
        stream blocks until it is retransmitted

  ⭐ CONSERVATIVE: reference ONLY entries the decoder has ACKNOWLEDGED.
     ✅ ⭐ ZERO head-of-line blocking, ever
     ❌ Slightly worse compression (some headers sent as literals)

⭐ SETTINGS_QPACK_BLOCKED_STREAMS lets the decoder cap how many
   streams may be blocked at once — 0 forces fully conservative
   encoding.
```

```
⭐ THE RESULT: QPACK achieves compression close to HPACK's while
   ⭐ MAKING HEAD-OF-LINE BLOCKING A TUNABLE CHOICE rather than a
      structural property.

⭐ THE DESIGN LESSON: when a shared, ordered data structure creates
   coupling, the fix is to separate the UPDATES from the USES and
   make the dependency EXPLICIT. The same pattern appears in
   event-sourced projections and in database catalog caching.
```

---

## 20. ⭐ Connection migration

The capability that genuinely cannot be retrofitted onto TCP.

```
⭐ A TCP CONNECTION IS IDENTIFIED BY THE 4-TUPLE
   (src_ip, src_port, dst_ip, dst_port).

  ⭐ CHANGE ANY OF THEM AND THE CONNECTION IS DEAD.

  ⭐ Walk out of a café: Wi-Fi → cellular → new source IP →
     ⭐ EVERY CONNECTION BREAKS. New TCP handshake, new TLS handshake,
        cold congestion window, and the application must retry.
```

```
⭐ A QUIC CONNECTION IS IDENTIFIED BY A CONNECTION ID,
   which is INDEPENDENT of the IP and port.

  ⭐ The client changes network → sends packets from a new address
     with THE SAME connection ID → ⭐ THE SERVER RECOGNISES IT AND
     CONTINUES THE CONNECTION.

  ⭐ No handshake. No TLS renegotiation. ⭐ The congestion window and
     all stream state survive (though the congestion controller
     re-probes the new path, since its characteristics may differ).
```

### Path validation

```
⭐ AN ATTACKER COULD SPOOF A MIGRATION to redirect a connection's
   traffic at a victim (an amplification attack).

⭐ SO MIGRATION REQUIRES PATH VALIDATION:

  Server → PATH_CHALLENGE (random 8 bytes) → new address
  Client → PATH_RESPONSE (the same bytes)  → server

  ⭐ Only an endpoint that actually receives traffic at the new
     address can answer. Until validation completes, the server
     limits sending on the new path (the 3× amplification rule, §17).
```

### ⭐ Connection ID privacy

```
⭐ A FIXED CONNECTION ID WOULD BE A TRACKING IDENTIFIER — an observer
   could follow a user across networks, which is worse for privacy
   than the 4-tuple it replaced.

⭐ THE FIX: NEW_CONNECTION_ID frames supply a POOL of alternative
   connection IDs. ⭐ On migration, the client switches to an unused
   one. An observer on the old path and one on the new path cannot
   link the two.
```

```
⭐ THE PRACTICAL IMPACT: for mobile users this is the single largest
   real-world benefit of HTTP/3 — larger than the loss-recovery
   improvements. A user moving between networks keeps their
   connection, their session, and their in-flight requests.
```

---

## 21. HTTP/3 semantics and discovery

```
⭐ HTTP/3 HAS THE SAME SEMANTICS AS HTTP/2. Methods, status codes,
   headers, and the request/response model are unchanged.

⭐ WHAT IT REMOVES, because QUIC already provides it:
   • ⭐ Stream multiplexing → QUIC streams
   • ⭐ Flow control frames → QUIC's MAX_DATA / MAX_STREAM_DATA
   • ⭐ RST_STREAM        → QUIC's RESET_STREAM
   • ⭐ The connection preface and most connection management

⭐ WHAT REMAINS: DATA, HEADERS, SETTINGS, GOAWAY, and the
   QPACK streams.
```

### ⭐ Discovery — how a client learns HTTP/3 is available

```
⭐ 1. Alt-Svc HEADER (over an existing HTTP/1.1 or /2 connection):

     Alt-Svc: h3=":443"; ma=86400

   ⭐ "I also speak HTTP/3 on port 443; remember this for 86,400 s."
   ⭐ THE COST: the FIRST connection must still be TCP. Only
      subsequent ones use HTTP/3.

⭐ 2. DNS HTTPS / SVCB RECORDS — the better mechanism:

     example.com.  3600  IN HTTPS 1 . alpn="h3,h2" port=443 ipv4hint=...

   ⭐ The client learns about HTTP/3 FROM DNS, BEFORE connecting.
      ⭐ No TCP connection is needed at all — genuinely 1-RTT from
         the very first request.
   ⭐ This is also the delivery mechanism for ECH (Deep Dive 13 §11).
```

```bash
# ⭐ Check whether a site advertises HTTP/3
dig +short HTTPS example.com
# 1 . alpn="h3,h2" ipv4hint=93.184.216.34

curl -sI https://example.com | grep -i alt-svc
# alt-svc: h3=":443"; ma=86400

# ⭐ Force HTTP/3
curl --http3 -sI https://example.com
```

---

## 22. ⭐ Head-of-line blocking: the complete picture

Pulling the whole series together, because this one concept explains the entire protocol evolution.

```
┌──────────────────────────────────────────────────────────────────┐
│ HTTP/1.1, NO PIPELINING                                          │
│   ⭐ One request at a time per connection.                        │
│   ⭐ HOL: total, by design. Mitigated by 6 parallel connections.  │
├──────────────────────────────────────────────────────────────────┤
│ HTTP/1.1 + PIPELINING                                            │
│   ⭐ Multiple requests, but responses MUST return in order.       │
│   ⭐ APPLICATION-LEVEL HOL. → abandoned (§2)                      │
├──────────────────────────────────────────────────────────────────┤
│ HTTP/2 over TCP                                                  │
│   ✅ ⭐ Application-level HOL SOLVED — streams return out of order │
│   ❌ ⭐ TCP-level HOL REMAINS — one lost segment stalls everything │
│   ❌ ⭐ HPACK-level HOL — header blocks must decode in order (§10) │
├──────────────────────────────────────────────────────────────────┤
│ HTTP/3 over QUIC                                                 │
│   ✅ ⭐ Application-level HOL solved (QUIC streams)                │
│   ✅ ⭐ TRANSPORT-level HOL SOLVED (per-stream reliability, §18)   │
│   ✅ ⭐ Header-compression HOL solved, and TUNABLE (QPACK, §19)    │
│   ⚠ ⭐ ONE REMAINS: if two streams' frames share ONE PACKET and   │
│      that packet is lost, both are affected. ⭐ Unavoidable —     │
│      packing frames from multiple streams into one packet is      │
│      what makes QUIC efficient in the first place.                │
└──────────────────────────────────────────────────────────────────┘
```

```
⭐ THE PATTERN ACROSS THREE PROTOCOL GENERATIONS:

  Each version identified a layer at which ordering created
  unnecessary coupling, and ⭐ REMOVED THE ORDERING REQUIREMENT
  AT THAT LAYER — while keeping it where the application
  genuinely needs it (within a single stream).

⭐ THAT IS A GENERAL ARCHITECTURAL PRINCIPLE, and it recurs
   everywhere in this book: per-key ordering instead of global
   ordering in Kafka (Chapter 06 §6.5), causal consistency instead
   of linearizability (Deep Dive 03 §12), per-aggregate transactions
   instead of global ones (Chapter 03 §3.8).
   ⭐ ORDER ONLY WHAT MUST BE ORDERED.
```

---

## 23. Performance: when each protocol wins

```
⭐ CONNECTION ESTABLISHMENT (100 ms RTT)

  HTTP/1.1 + TLS 1.2:  TCP 1 + TLS 2 = ⭐ 300 ms
  HTTP/2  + TLS 1.3:   TCP 1 + TLS 1 = ⭐ 200 ms
  ⭐ HTTP/3 (QUIC):                     ⭐ 100 ms
  ⭐ HTTP/3 0-RTT resumption:           ⭐ 0 ms  (with §14's caveats)
```

```
⭐ ON A CLEAN, FAST NETWORK (datacenter, 0% loss, 1 ms RTT):

  ⭐ HTTP/2 and HTTP/3 are ROUGHLY EQUAL.
  ⭐ HTTP/3 may be slightly SLOWER due to higher CPU cost (§24).
  ⭐ There is little reason to prefer HTTP/3 for internal
     service-to-service traffic.
```

```
⭐ ON A LOSSY OR HIGH-LATENCY NETWORK (mobile, 2% loss, 150 ms RTT):

  ⭐ HTTP/3 WINS DECISIVELY.
     • no transport HOL blocking (§18, §22)
     • better loss recovery (256 ACK ranges, exact RTT — §18)
     • ⭐ connection migration on network change (§20)

  ⭐ Measured by Google, Cloudflare and Fastly: 5-15% improvement in
     median page load, and ⭐ much larger improvements at the tail
     (p95, p99) — which is where users actually notice.
```

### The decision

```
⭐ USE HTTP/3 FOR:
   • ⭐ Public internet traffic, especially mobile
   • Anything where p99 latency matters more than CPU cost
   • ⭐ Long-lived connections on changing networks

⭐ HTTP/2 IS FINE (OR BETTER) FOR:
   • ⭐ Internal service-to-service inside a datacenter
   • ⭐ gRPC (which is HTTP/2-based; gRPC-over-HTTP/3 exists but
     is less mature)
   • CPU-constrained environments

⭐ AND IN PRACTICE: enable HTTP/3 at your CDN or edge, keep HTTP/2
   for the origin and for internal traffic. ⭐ This is what most
   large deployments do, and it captures nearly all the benefit.
```

---

## 24. ⭐ Operations: load balancing, debugging, CPU

### ⭐ UDP blocking and fallback

```
⭐ SOME NETWORKS BLOCK OR RATE-LIMIT UDP — corporate firewalls,
   some mobile carriers, some public Wi-Fi.

⭐ SO EVERY HTTP/3 DEPLOYMENT MUST FALL BACK TO TCP.

  ⭐ Clients race: attempt QUIC and TCP in parallel (or attempt
     QUIC with a short timeout, then fall back).
  ⭐ Measured: 3-5% of connections fall back to TCP.

⭐ THEREFORE: you can never turn TCP off. HTTP/3 is always an
   ADDITION to your stack, never a replacement — which means
   ⭐ MORE surface to configure, monitor and secure, not less.
```

### ⭐ Load balancing is fundamentally different

```
⭐ TCP LOAD BALANCING routes by the 4-TUPLE. Stable, and every
   L4 load balancer does it.

⭐ QUIC CANNOT WORK THAT WAY, because connection migration (§20)
   deliberately CHANGES the 4-tuple while the connection continues.

⭐ THE SOLUTION: route by CONNECTION ID.

  ⭐ The server encodes ROUTING INFORMATION INTO THE CONNECTION ID
     it issues (which server/shard should receive this connection).
     The load balancer reads that prefix and routes accordingly.

  ⭐ QUIC-LB is the (draft) standard for doing this in a way that
     does not leak server identity to observers.
```

```
⭐ THE PRACTICAL CONSEQUENCES:
   ❌ ⭐ A naive L4 UDP load balancer BREAKS connection migration —
      migrated packets land on the wrong backend.
   ❌ ⭐ ECMP hashing on the 4-tuple has the same problem.
   ✅ ⭐ You need a QUIC-aware load balancer, or you must terminate
      QUIC at the edge (which is what CDNs do, and why enabling
      HTTP/3 at a CDN is so much easier than doing it yourself).
```

### ⭐ Debugging encrypted transport

```
⭐ TCP: tcpdump shows you sequence numbers, flags, window sizes,
   retransmissions — everything (Deep Dive 12 §21-22).

⭐ QUIC: ⭐ ALMOST EVERYTHING IS ENCRYPTED, INCLUDING THE PACKET
   NUMBER AND MOST HEADER FIELDS. ⭐ tcpdump shows you UDP datagrams
   of opaque bytes.

⭐ THE ANSWER IS qlog — a standardised JSON logging format that
   endpoints emit, containing packet events, frames, congestion
   state and stream activity.
```

```bash
# ⭐ Capture qlog from Chrome
chrome --enable-quic --log-net-log=/tmp/netlog.json

# ⭐ From curl (with an HTTP/3-capable build)
QLOGDIR=/tmp/qlog curl --http3 https://example.com

# ⭐ Visualise with qvis (qvis.quictools.info) — timeline of packets,
#   congestion window, stream multiplexing, loss events
```

```
⭐ THIS IS A REAL OPERATIONAL COST. Your existing packet-capture
   expertise and tooling do not transfer. ⭐ Budget for it before
   deploying HTTP/3 on infrastructure you operate yourself.
```

### ⭐ CPU cost

```
⭐ QUIC USES MORE CPU THAN TCP+TLS. Historically 2-3×; now
   typically 1.2-2× after significant optimisation work.

⭐ WHY:
   1. ⭐ User-space implementation — no kernel TCP stack optimisations
   2. ⭐ Per-packet syscall overhead (one sendmsg per datagram,
      versus one write for a large TCP buffer)
   3. ⭐ No TSO/LRO hardware offload equivalent, initially
   4. Encryption of every packet header, not just the payload

⭐ THE MITIGATIONS THAT CLOSED MOST OF THE GAP:
   • ⭐ UDP GSO/GRO (Generic Segmentation/Receive Offload) —
     one syscall for many datagrams
   • ⭐ sendmmsg/recvmmsg — batched syscalls
   • ⭐ io_uring
   • Hardware offload is arriving in newer NICs
```

```
⭐ FOR A HIGH-THROUGHPUT ORIGIN SERVER, THIS MATTERS. It is another
   reason the common pattern is HTTP/3 at the CDN edge and HTTP/2
   to the origin.
```

---

## 25. What an architect takes from this

**1. HTTP/1.1 pipelining failed because responses had to return in order.** Every subsequent version is an attack on unnecessary ordering — stream IDs in HTTP/2, per-stream reliability in QUIC, tunable blocking in QPACK. **Order only what must be ordered** is the thread running through all of it.

**2. Delete your HTTP/1.1 workarounds.** Domain sharding actively harms HTTP/2 by forcing multiple cold connections. Sprite sheets and heavy inlining are obsolete.

**3. The HTTP/2 flow-control window defaults to 65,535 bytes and caps you at 655 KB/s per stream on a 100 ms path.** This is the most common cause of "HTTP/2 is slower than HTTP/1.1 over WAN" and of poor gRPC throughput. **Raise both the stream and connection windows to at least the bandwidth-delay product.**

**4. HPACK saves 80–90% of header bytes** — often more than a full congestion window on a request-heavy page. But mark session cookies and `Authorization` as **"never indexed"**, or you have built a compression oracle.

**5. `GOAWAY` carries the last processed stream ID**, which is what makes graceful HTTP/2 shutdown and safe retries possible. If your servers do not implement the two-GOAWAY pattern, your rolling deploys are dropping in-flight requests.

**6. HTTP/2 solved application-level head-of-line blocking and could not solve TCP's.** On a 2% loss link, HTTP/2 can be *slower* than HTTP/1.1 — which is exactly why QUIC exists.

**7. QUIC is on UDP because UDP is the only hole through the middleboxes**, and it encrypts its own headers specifically so it can keep evolving. Encryption as an anti-ossification mechanism is a genuinely new idea worth understanding.

**8. Packets, frames and streams are three different things**, and the separation is what gives QUIC exact RTT measurement, unambiguous loss detection, and per-stream delivery. "Packets are never retransmitted" is the sentence that unlocks it.

**9. Connection migration is the benefit that cannot be retrofitted onto TCP**, and for mobile users it is the largest real-world win — larger than the loss-recovery improvements.

**10. HTTP/3 is an addition, never a replacement.** 3–5% of connections fall back to TCP, so you operate both. And it needs connection-ID-aware load balancing, `qlog`-based debugging, and 1.2–2× the CPU.

**11. The pragmatic deployment is HTTP/3 at the edge, HTTP/2 to the origin and internally.** That captures nearly all the user-facing benefit without taking on the operational cost across your whole estate.

**12. Request smuggling exists because two parsers can disagree about one message.** Reject ambiguous requests, validate on protocol downgrade, and treat every parser boundary as a place to ask "can these two disagree?"

---

## Exercises

1. Capture an HTTP/1.1 request from a browser and measure the total header bytes. Multiply by the number of requests on a typical page.
2. Check whether your build pipeline still does domain sharding, concatenation or sprite generation. Which of these are now costing you?
3. Measure your HTTP/2 flow-control windows. Compute the per-stream throughput cap for your longest-RTT client path.
4. If you run gRPC over a WAN, check `InitialWindowSize` and `InitialConnWindowSize`. Are they still the 65,535 default?
5. Verify your servers send `Early-Data`-style `103 Early Hints` rather than relying on server push. If they use push, plan its removal.
6. Verify your HTTP/2 servers implement the two-GOAWAY graceful shutdown. Test by deploying under load and counting failed requests.
7. Confirm your HTTP/2 stack is patched for CVE-2023-44487 (Rapid Reset) and that RST_STREAM rate limiting is active.
8. Check whether your application marks sensitive headers as "never indexed" in HPACK. Most do not.
9. Explain, to a colleague, why HTTP/2 can be slower than HTTP/1.1 on a lossy mobile network.
10. Trace what happens to a TCP connection and a QUIC connection when a phone moves from Wi-Fi to cellular.
11. Test whether your site advertises HTTP/3 via both `Alt-Svc` and a DNS HTTPS record. Which gives a better first-connection experience, and why?
12. Capture a `qlog` from a QUIC connection and visualise it. Identify the congestion window growth and any loss events.
13. If you terminate QUIC yourself, verify your load balancer is connection-ID aware. Test connection migration by changing the client's source IP mid-transfer.
14. Construct a CL.TE request smuggling test against a staging proxy chain. Does your edge reject requests carrying both `Content-Length` and `Transfer-Encoding`?

---

**Next in this series:** Deep Dive 15 — Containers and the Kernel

**Back to:** [Deep Dives](README.md) · [Chapter 13](../13-networking.md) · [Chapter 08](../08-api-architecture.md) · [The Map](../README.md)
