# Chapter 08 — API Architecture 🟢

> An API is a **promise you make to strangers**.
> Once published, you cannot take it back, you cannot see who depends on it, and every mistake in it is permanent.
>
> That is why API design is architecture, not implementation detail.

---

# PART 1 — REST

## 8.1 What REST actually is

REST (Representational State Transfer) is an architectural style from Roy Fielding's 2000 dissertation. Most "REST APIs" are really **HTTP JSON APIs**, which is fine — but know the difference, because the constraints are where the value is.

### The six constraints

| Constraint | Meaning | Why it matters architecturally |
|-----------|---------|-------------------------------|
| **Client–Server** | Separate concerns | Client and server evolve independently |
| **Stateless** | Each request contains everything needed | **This is what makes horizontal scaling possible** |
| **Cacheable** | Responses say whether they can be cached | Enormous performance lever (CDN, browser, proxy) |
| **Uniform interface** | Resources, standard methods, self-describing messages | Anyone can use it without a custom SDK |
| **Layered system** | Client cannot tell if it is talking to the origin | Lets you insert gateways, caches, load balancers freely |
| **Code on demand** (optional) | Server can send executable code | Rarely used |

> The two that actually pay rent: **stateless** (scaling) and **cacheable** (performance). If your "REST API" keeps server-side session state and sets `Cache-Control: no-store` on everything, you have thrown away the two benefits.

## 8.2 Resources and URLs

**Resources are nouns. Methods are verbs. The URL identifies *what*, the method says *what to do*.**

```
✅ GOOD                              ❌ BAD
GET    /verification-sessions        GET  /getAllSessions
POST   /verification-sessions        POST /createSession
GET    /verification-sessions/{id}   GET  /getSessionById?id=5
PATCH  /verification-sessions/{id}   POST /updateSession
DELETE /verification-sessions/{id}   POST /deleteSession
GET    /customers/{id}/sessions      GET  /getSessionsForCustomer?cid=5
```

### URL design rules

```
✅ Plural nouns for collections        /customers  not  /customer
✅ Lowercase, hyphen-separated         /verification-sessions  not  /VerificationSessions
✅ Nest to show ownership              /customers/{id}/sessions
✅ Stop nesting at 2 levels            /customers/{id}/sessions/{sid}/attempts  ← too deep
                                       → /sessions/{sid}/attempts instead
✅ Query params for filtering/sorting  /sessions?status=pending&sort=-created_at
✅ Version in the path or header       /v1/sessions
❌ No verbs in the path
❌ No file extensions                  /sessions.json  → use the Accept header
❌ No trailing slash inconsistency     pick one and redirect the other
```

### The actions that are not CRUD

Real systems have operations that are not "create/update/delete a thing": approve, cancel, retry, publish, send.

Three acceptable approaches:

```
1. SUB-RESOURCE AS A STATE CHANGE (most RESTful)
   PUT /sessions/{id}/status        { "status": "approved" }

2. ACTION SUB-RESOURCE (pragmatic, widely used — Stripe, GitHub do this)
   POST /sessions/{id}/approve      { "reviewer_id": "...", "note": "..." }
   POST /invoices/{id}/void
   POST /payments/{id}/refund

3. CREATE A RESOURCE THAT REPRESENTS THE ACTION (most powerful)
   POST /refunds                    { "payment_id": "...", "amount": 500 }
   → the refund is now a first-class thing with its own ID, status and history
```

> **Option 3 is often the best answer and people miss it.** If the action can fail, be retried, be audited, or take time, it *is* a resource. "A refund" is a thing, not a verb.

## 8.3 HTTP methods

| Method | Purpose | Safe | Idempotent | Request body | Response |
|--------|---------|------|-----------|--------------|----------|
| **GET** | Read | ✅ | ✅ | No | 200 + representation |
| **HEAD** | Read headers only | ✅ | ✅ | No | 200, no body |
| **POST** | Create / non-idempotent action | ❌ | ❌ | Yes | 201 + `Location`, or 200/202 |
| **PUT** | Replace entirely | ❌ | ✅ | Yes (full) | 200/204 |
| **PATCH** | Partial update | ❌ | ❌* | Yes (partial) | 200/204 |
| **DELETE** | Remove | ❌ | ✅ | No | 204, or 200 with body |
| **OPTIONS** | Discover capabilities | ✅ | ✅ | No | 200 + `Allow` |

**PUT vs PATCH — the practical difference:**

```http
PUT /customers/42
{ "name": "Delower", "email": "d@x.com", "tier": "gold" }
→ replaces the WHOLE resource. Omitted fields are REMOVED/nulled.

PATCH /customers/42
{ "tier": "platinum" }
→ changes only `tier`. Everything else untouched.
```

**The PUT trap:** clients that GET, modify one field, and PUT back will silently wipe any field added by a newer API version that their client does not know about. This is a real and common bug. **Prefer PATCH for updates.**

For PATCH, pick a format and document it: plain "merge" JSON (most common), or the standards — **JSON Merge Patch** (RFC 7386, `null` means delete) or **JSON Patch** (RFC 6902, an array of operations, supports array manipulation).

## 8.4 Status codes — use them properly

### 2xx — success

| Code | When |
|------|------|
| **200 OK** | Success with a body |
| **201 Created** | Resource created — **always include a `Location` header** |
| **202 Accepted** | Accepted for async processing — return a status URL |
| **204 No Content** | Success, nothing to return (DELETE, some PUTs) |
| **206 Partial Content** | Range requests (video, large files) |

### 3xx — redirection

| Code | When |
|------|------|
| **301 Moved Permanently** | Resource has a new permanent URL (cached aggressively by clients) |
| **302 Found** / **307** | Temporary redirect (307 preserves the method; 302 historically did not) |
| **304 Not Modified** | Conditional GET — **the client's cache is still valid. This saves enormous bandwidth.** |

### 4xx — client error

| Code | When | Common mistake |
|------|------|----------------|
| **400 Bad Request** | Malformed syntax / invalid request | Used as a catch-all for everything |
| **401 Unauthorized** | **Not authenticated** (misnamed in the spec) | Confused with 403 |
| **403 Forbidden** | Authenticated, but **not allowed** | Confused with 401 |
| **404 Not Found** | Does not exist — or you are hiding existence deliberately | |
| **405 Method Not Allowed** | Wrong verb on a valid URL | Must include an `Allow` header |
| **409 Conflict** | State conflict (duplicate, concurrent edit) | |
| **410 Gone** | Existed, permanently removed | Underused — nicer than 404 for deprecations |
| **412 Precondition Failed** | `If-Match` did not match — optimistic locking | |
| **415 Unsupported Media Type** | Wrong `Content-Type` | |
| **422 Unprocessable Entity** | Syntax fine, **semantics invalid** (validation errors) | |
| **429 Too Many Requests** | Rate limited — **must include `Retry-After`** | |

> **401 vs 403, memorised:** 401 = "**who are you?**" (no or bad credentials). 403 = "**I know who you are, and no.**"
>
> **400 vs 422:** 400 = I cannot parse this. 422 = I parsed it, and "age: -5" is not a valid age.

### 5xx — server error

| Code | When |
|------|------|
| **500 Internal Server Error** | Unhandled failure — **never leak a stack trace** |
| **502 Bad Gateway** | Upstream returned garbage |
| **503 Service Unavailable** | Overloaded/maintenance — **include `Retry-After`** |
| **504 Gateway Timeout** | Upstream did not answer in time |

> **The cardinal sin:** `HTTP 200 { "success": false, "error": "not found" }`. Now every cache, proxy, monitor and client library thinks everything is fine. Your error rate dashboard reads 0%. **Use the status code.**

## 8.5 Error responses — use RFC 9457 (Problem Details)

Stop inventing error formats. There is a standard.

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json

{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Your request parameters didn't validate.",
  "status": 422,
  "detail": "The 'video' field exceeds the maximum size of 10 MB.",
  "instance": "/v1/verification-sessions/ses_8812/attempts",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": [
    { "field": "video",       "code": "max_size_exceeded", "message": "Maximum 10 MB, received 14.2 MB" },
    { "field": "challenge_id","code": "required",          "message": "This field is required" }
  ]
}
```

**Rules for good errors:**
1. **Machine-readable code** (`max_size_exceeded`) — clients branch on this, never on the message text
2. **Human-readable message** — for the developer reading logs
3. **Field-level detail** for validation — return **all** errors, not the first one
4. **A trace ID** — so a customer can say "this failed, here is the ID" and you can find it instantly
5. **Never leak internals** — no stack traces, no SQL, no internal hostnames, no "user with that email already exists" on a signup form (that is account enumeration)

## 8.6 Pagination 🟢

Never return an unbounded list. Ever. The day a customer has 4 million records, your API will take down your database.

### Offset pagination (simple, and quietly broken at scale)

```http
GET /sessions?page=3&limit=50
```

```sql
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 50 OFFSET 100;
```

| ✅ | ❌ |
|---|---|
| Jump to any page | **Slow at depth** — `OFFSET 500000` makes the DB scan and discard 500,000 rows |
| Show total pages | **Items shift** — a new row appears while paging → you see an item twice or miss one |

### Cursor / keyset pagination ⭐ (what you should use)

```http
GET /sessions?limit=50
GET /sessions?limit=50&cursor=eyJpZCI6IjAxSjhYIiwidHMiOiIyMDI2LTA5LTEyIn0
```

```sql
-- The cursor encodes the last row's sort values
SELECT * FROM sessions
WHERE (created_at, id) < ($1, $2)     -- composite tiebreaker: stable & unique
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

| ✅ | ❌ |
|---|---|
| **Constant time at any depth** (it is an index seek) | Cannot jump to page 47 |
| **Stable** under concurrent inserts | Total count is expensive/omitted |
| Works for infinite scroll | Sort field must be fixed and indexed |

```json
{
  "data": [ ... ],
  "pagination": {
    "next_cursor": "eyJpZCI6...",
    "has_more": true,
    "limit": 50
  }
}
```

> **Rule:** offset pagination for small admin tables where users want page numbers; **cursor pagination for everything user-facing or large.** Always cap `limit` (e.g. max 100) — otherwise `?limit=1000000` is a free denial-of-service.

## 8.7 Filtering, sorting, field selection

```http
GET /sessions?status=pending&created_after=2026-09-01&sort=-created_at,id&fields=id,status,score
```

| Feature | Convention |
|---------|-----------|
| Filter | `?status=pending` (exact), `?score_gte=0.8` (comparison), `?status=a,b` (in) |
| Sort | `?sort=-created_at,name` (`-` = descending, comma = multiple) |
| Sparse fields | `?fields=id,status` — saves bandwidth for mobile |
| Expand | `?expand=customer` — embeds a related resource, saves a round trip |
| Search | `?q=delower` — full-text |

**Security warnings:**
- **Whitelist** filterable and sortable fields. Never pass user input into an `ORDER BY` or a query builder unchecked — that is SQL injection and a performance DoS in one.
- Every filterable field must have an **index**, or a filter becomes a table scan
- Cap `expand` depth — unbounded expansion is GraphQL's N+1 problem without GraphQL's tooling

## 8.8 Idempotency and concurrency in HTTP

### Idempotency keys (Chapter 05, applied)

```http
POST /v1/charges
Idempotency-Key: 8f14e45f-ea2a-4f0e-b1d6-2c8e3f1a9b7d
```

**Mandatory for any POST that moves money or creates something expensive.** Document it and enforce it.

### Optimistic concurrency with ETags ⭐

Stop lost updates without holding locks.

```http
GET /customers/42
→ 200 OK
  ETag: "a3f5c8e2"
  { "name": "Delower", "tier": "gold" }

PATCH /customers/42
If-Match: "a3f5c8e2"
{ "tier": "platinum" }

→ 200 OK        (nobody else changed it)
→ 412 Precondition Failed   (someone did — client must re-fetch and retry)
```

Without this, two admins editing the same record silently overwrite each other. **This is a two-line change that prevents a whole category of data-loss bug.**

### Conditional GET (free bandwidth savings)

```http
GET /sessions/ses_881
If-None-Match: "a3f5c8e2"

→ 304 Not Modified        (no body — bytes saved, DB query possibly skipped)
```

Also works with `Last-Modified` / `If-Modified-Since`.

## 8.9 Caching headers 🟢

```http
Cache-Control: public, max-age=3600, stale-while-revalidate=60
Cache-Control: private, max-age=0, must-revalidate
Cache-Control: no-store                      # never cache (PII, financial)
ETag: "a3f5c8e2"
Vary: Accept-Encoding, Authorization
```

| Directive | Meaning |
|-----------|---------|
| `public` | Any cache (CDN, proxy) may store it |
| `private` | Only the browser — **use for anything user-specific** |
| `no-store` | Never write it anywhere — for secrets and PII |
| `no-cache` | Store, but revalidate before every use (confusingly named) |
| `max-age=N` | Fresh for N seconds |
| `s-maxage=N` | Overrides `max-age` for shared caches (CDN) |
| `stale-while-revalidate=N` | Serve stale for N s while refreshing in the background — **excellent for perceived latency** |
| `immutable` | Never revalidate (versioned static assets) |

> **`Vary: Authorization` is a security-critical header.** Without it, a shared cache can serve user A's private response to user B. This has caused real breaches.

## 8.10 API versioning 🟢

You will need it. Decide before v1 ships.

| Strategy | Example | Pros | Cons |
|----------|---------|------|------|
| **URL path** ⭐ | `/v1/sessions` | Obvious, easy to route, easy to test in a browser | "Not RESTful" (the resource did not change); version sprawl |
| **Header** | `Accept: application/vnd.api.v2+json` | Clean URLs, content negotiation | Invisible, harder to test, caches must `Vary` |
| **Query param** | `/sessions?version=2` | Simple | Easy to forget; messy caching |
| **Date-based** | `Stripe-Version: 2026-09-12` | Very fine-grained, per-customer pinning | Complex to implement (Stripe maintains transformation layers) |

> **Recommendation: URL path versioning (`/v1/`) for major versions.** It is the most pragmatic. Combine with the rule below so that you almost never need v2.

### The far more important rule: version **additively**

```
✅ NON-BREAKING (no new version needed)
   - Add a new optional field to a response      (clients must ignore unknown fields)
   - Add a new optional request parameter
   - Add a new endpoint
   - Add a new enum value        ← ONLY if clients handle unknowns; document it
   - Relax a validation rule

❌ BREAKING (needs a new version)
   - Remove or rename a field
   - Change a field's type or format
   - Make an optional parameter required
   - Change default behaviour
   - Change the meaning of a field (the silent killer)
   - Remove an endpoint or an enum value
   - Add a new required error condition
```

**Tolerant Reader** is the contract you ask clients to honour: *ignore fields you do not recognise; do not fail on extra data.* Publish it. Then you can add fields forever without a v2.

### Deprecation, done professionally

```http
Deprecation: Sun, 01 Mar 2026 00:00:00 GMT
Sunset: Wed, 01 Sep 2026 00:00:00 GMT
Link: <https://api.example.com/docs/migrating-to-v2>; rel="deprecation"
Warning: 299 - "v1 will be removed on 2026-09-01. See the migration guide."
```

Plus: measure who still calls it (per-client metrics), email them, and **never remove a version without knowing exactly who breaks.**

## 8.11 HATEOAS ⚪

The "Level 3" of Richardson's maturity model: responses include links to what you can do next.

```json
{
  "id": "ses_881",
  "status": "pending_review",
  "_links": {
    "self":    { "href": "/v1/sessions/ses_881" },
    "approve": { "href": "/v1/sessions/ses_881/approve", "method": "POST" },
    "reject":  { "href": "/v1/sessions/ses_881/reject",  "method": "POST" }
  }
}
```

**The theory:** clients discover capabilities dynamically; the server can change URLs freely; the available actions reflect current state.

**The reality:** almost nobody implements real HATEOAS, and almost no client consumes it dynamically. **Awareness is enough.** The one genuinely useful piece is *state-dependent action links* — the client does not have to reimplement your state machine to know whether "approve" is currently allowed.

---

# PART 2 — Other API styles

## 8.12 gRPC 🟡

**What it is:** Google's RPC framework — Protobuf contracts over HTTP/2, with generated clients and servers.

```protobuf
syntax = "proto3";
package verification.v1;

service VerificationService {
  rpc StartSession   (StartSessionRequest)   returns (Session);
  rpc SubmitVideo    (stream VideoChunk)     returns (VerificationResult);  // client streaming
  rpc WatchSession   (WatchRequest)          returns (stream SessionEvent); // server streaming
}

message StartSessionRequest {
  string customer_id = 1;
  RiskLevel risk_level = 2;
}

message Session {
  string id = 1;
  SessionStatus status = 2;
  google.protobuf.Timestamp expires_at = 3;
}
```

| ✅ Strengths | ❌ Weaknesses |
|-------------|---------------|
| **Fast** — binary, compact, HTTP/2 multiplexing | **Not browser-native** (needs gRPC-Web + a proxy) |
| **Strongly typed contract**, generated code in 11+ languages | **Not human-readable** — you cannot curl it easily |
| **Streaming** in both directions, built in | Harder to debug and inspect on the wire |
| Built-in deadlines, cancellation, retries, load-balancing | Requires HTTP/2 end to end (some old proxies choke) |
| Excellent for high-volume internal traffic | More tooling and build-pipeline setup |

> **Use gRPC for internal service-to-service communication**, especially high-volume or streaming. **Use REST/JSON for public and browser-facing APIs.** Many companies do exactly this: gRPC inside, REST at the edge, with the gateway translating.

**Protobuf field numbers are the contract.** Never reuse a number, never change a field's number, and mark removed fields `reserved`. Getting this wrong corrupts data silently.

## 8.13 GraphQL 🟡

**The problem it solves:** REST endpoints return fixed shapes. A mobile screen needs data from 5 endpoints (**under-fetching** → 5 round trips), and each returns 40 fields when the screen needs 4 (**over-fetching** → wasted bandwidth).

```graphql
query SessionDashboard($id: ID!) {
  session(id: $id) {
    id
    status
    score
    customer {              # would have been a second REST call
      name
      tier
    }
    attempts(last: 3) {     # and a third
      number
      passed
      signals { livenessScore spoofDetected }
    }
  }
}
```

One request. Exactly the fields needed. The client controls the shape.

| ✅ Strengths | ❌ Weaknesses |
|-------------|---------------|
| Client gets exactly what it needs, in one round trip | **Caching is hard** — everything is `POST /graphql`, so HTTP caching does not apply |
| Strongly typed, self-documenting, great tooling | **N+1 queries** are the default failure mode (needs DataLoader batching) |
| One endpoint serves many client shapes | **Query complexity attacks** — a deeply nested query can melt your DB |
| Excellent for mobile with varied screens | Rate limiting by "requests" is meaningless; you need cost analysis |
| Schema evolution without versions (deprecate fields) | File uploads and errors need extra conventions |
| Federation composes many services into one graph | Real operational complexity; not a free lunch |

**Non-negotiable mitigations if you run GraphQL in production:**

```javascript
// 1. DataLoader — batch and dedupe, or you WILL have N+1
const customerLoader = new DataLoader(async (ids) =>
  db.customers.findMany({ where: { id: { in: ids } } })
);

// 2. Depth + complexity limits
validationRules: [depthLimit(7), costAnalysis({ maximumCost: 1000 })]

// 3. Persisted queries — only allow pre-registered queries in production
//    (kills arbitrary-query attacks AND enables GET + CDN caching)
```

> **When GraphQL wins:** many different clients with different data needs (web + iOS + Android + partners), a rich interconnected domain, and a team with the appetite to operate it.
> **When it loses:** a simple CRUD service, a single client, a small team, or when HTTP caching is your main performance strategy.

## 8.14 WebSockets 🟡

**Full-duplex, persistent, bidirectional connection.**

```
Client ──── HTTP Upgrade ────► Server
       ◄─── 101 Switching Protocols ───
       ◄══════ persistent, both directions ══════►
```

**Use for:** chat, collaborative editing, live dashboards, multiplayer, trading tickers, anything where the **client also sends frequently**.

**Architectural consequences you must plan for:**

1. **Connections are stateful** — this breaks the "stateless servers" rule. You need sticky routing or a shared backplane (Redis pub/sub) so any server can reach any connected client.
2. **Deploys drop connections** — clients need automatic reconnect with backoff **and** state resync (they missed messages while offline)
3. **Connection limits** — each connection holds memory and a file descriptor; ~10k–100k per node depending on the stack
4. **Load balancers need WebSocket support** and long idle timeouts
5. **No HTTP caching, no standard status codes** — you are designing your own protocol on top
6. **Auth** — the browser WebSocket API cannot set headers, so token-in-query-string (logged everywhere!) or a post-connect auth message. Design this deliberately.

## 8.15 Server-Sent Events (SSE) — the underrated option ⭐

**One-way, server → client, over plain HTTP.**

```http
GET /sessions/ses_881/events
Accept: text/event-stream

HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache

event: status
data: {"status":"processing","progress":30}

event: status
data: {"status":"processing","progress":75}

event: result
data: {"status":"passed","score":0.94}
```

```javascript
const es = new EventSource('/sessions/ses_881/events');
es.addEventListener('result', e => render(JSON.parse(e.data)));
// automatic reconnection with Last-Event-ID is BUILT IN
```

| SSE vs WebSockets | SSE | WebSocket |
|---|---|---|
| Direction | Server → client only | Both |
| Protocol | Plain HTTP | Upgrade to ws:// |
| Auto-reconnect | **Built in**, with `Last-Event-ID` replay | You write it |
| Proxies / firewalls | Just HTTP — works everywhere | Sometimes blocked |
| Compression, auth headers, HTTP/2 | All normal | Limited |
| Browser connection limit | 6 per domain on HTTP/1.1 (fine on HTTP/2) | Higher |

> **If you only need server→client push (progress updates, notifications, live status), use SSE.** It is dramatically simpler than WebSockets and most teams reach for WebSockets out of habit. For a verification progress feed, SSE is the right answer.

## 8.16 Webhooks 🟢

**Reverse API:** you call *their* endpoint when something happens.

```http
POST https://customer.example.com/webhooks/verification
Content-Type: application/json
Webhook-Id: msg_01J8X7...
Webhook-Timestamp: 1757673600
Webhook-Signature: v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=

{ "type": "verification.passed", "data": { "session_id": "ses_881", "score": 0.94 } }
```

### The webhook provider's checklist (get all of these right)

**1. Sign every payload — HMAC, with a timestamp**

```python
def sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    return base64.b64encode(hmac.new(secret.encode(), signed, hashlib.sha256).digest()).decode()
```

The timestamp inside the signed content prevents **replay attacks**. Receivers must reject anything older than ~5 minutes, and must use a **constant-time comparison**.

**2. Retry with exponential backoff** — and publish the schedule

```
Attempt 1: immediately
Attempt 2: +5 seconds        Attempt 5: +30 minutes
Attempt 3: +1 minute         Attempt 6: +2 hours
Attempt 4: +5 minutes        Attempt 7: +12 hours  → then disable and email them
```

**3. Give every event a stable ID** so receivers can deduplicate (delivery is at-least-once)

**4. Timeout fast (5–10 s)** and require the receiver to just acknowledge — they should queue and process asynchronously, not do work inside the request

**5. Provide a dashboard**: delivery history, payloads, response codes, and a **manual replay** button. This single feature removes most support tickets.

**6. Version the payloads** and let customers pin a version

**7. Publish your egress IP ranges** so customers can allowlist them

### The receiver's checklist

- Verify the signature **before** parsing the body, using the **raw bytes** (re-serialising changes the signature)
- Return **2xx immediately**, then process from a queue
- **Deduplicate** on the event ID
- Be prepared for **out-of-order** delivery (use the event timestamp/version, not arrival order)
- Never trust the payload contents for authorisation — re-fetch from the API if it matters

> **Webhooks vs polling:** webhooks are efficient and real-time but require the customer to run a public endpoint. **Offer both.** Many enterprise customers cannot accept inbound traffic, and a polling endpoint (`GET /events?after=cursor`) serves them — it is also your fallback when webhooks fail.

---

# PART 3 — API architecture patterns

## 8.17 API Gateway 🟢

A single entry point in front of your services.

```
                       ┌──────────────────────────────┐
                       │        API GATEWAY           │
   Clients ───────────►│  • TLS termination           │
                       │  • AuthN (validate JWT)      │
                       │  • Rate limiting / quotas    │
                       │  • Routing                   │
                       │  • Request/response transform│
                       │  • Caching                   │
                       │  • Logging, metrics, tracing │
                       │  • WAF, IP allowlist         │
                       └────┬─────────┬─────────┬─────┘
                            ▼         ▼         ▼
                        Service A  Service B  Service C
```

**Why it exists:** without it, every service re-implements auth, rate limiting, TLS, logging and CORS — differently, and some of them badly.

**What belongs in a gateway:**
✅ Authentication (validate the token, reject early)
✅ Rate limiting and quotas
✅ TLS termination
✅ Routing and path rewriting
✅ Request/response logging, metrics, trace initiation
✅ CORS, compression, WAF
✅ Response caching for public GETs

**What does NOT belong:**
❌ Business logic (this is how SOA's ESB became a monolith — Chapter 02)
❌ Data aggregation across many services (use a BFF instead)
❌ Anything that requires deploying the gateway whenever a service changes

**Risks:** it is a single point of failure (run it HA), it can become a bottleneck, and it can become a *team* bottleneck if one team must approve every route. Prefer declarative, self-service route config owned by each service team.

**Products:** Kong, AWS API Gateway, Azure API Management, Apigee, Tyk, Envoy, Traefik, NGINX, Spring Cloud Gateway, YARP.

## 8.18 Backend for Frontend (BFF) ⭐

**The problem:** one API tries to serve a web app, an iOS app, an Android app and partner integrations. Every client's needs conflict. Every change risks breaking three other clients. You end up with `?include=` flags everywhere.

**The solution:** one backend per client type, owned by that client's team.

```
   Web App ──────► Web BFF ────┐
   iOS App ──────► Mobile BFF ─┼──► Verification Service
   Partners ─────► Public API ─┤──► Customer Service
                               └──► Billing Service
```

Each BFF:
- Returns **exactly** the shape that client needs (mobile gets small payloads; web gets richer ones)
- Aggregates several service calls into one round trip (crucial on mobile networks)
- Handles client-specific auth (cookies for web, bearer tokens for mobile)
- Is **owned by the frontend team** — they can change it without a backend ticket

> **The organisational benefit is the real one:** the frontend team stops waiting on the backend team. That is worth more than the technical tidiness.

**Costs:** some duplicated logic across BFFs, more deployables. Keep BFFs **thin** — orchestration and shaping only, no business rules. A BFF with business logic is a new monolith in disguise.

## 8.19 API Composition / Aggregator

```python
# One client call → several backend calls, in PARALLEL
async def get_session_dashboard(session_id: str) -> Dashboard:
    session, customer, history, quota = await asyncio.gather(
        verification_svc.get_session(session_id),
        customer_svc.get(session.customer_id),
        verification_svc.get_history(session.customer_id, limit=5),
        billing_svc.get_quota(session.tenant_id),
        return_exceptions=True,            # partial failure tolerance
    )
    return Dashboard(
        session=session,
        customer=customer if not isinstance(customer, Exception) else None,
        history=history if not isinstance(history, Exception) else [],
        quota=quota if not isinstance(quota, Exception) else None,
        degraded=[n for n, v in zip(("customer","history","quota"),
                                    (customer, history, quota))
                  if isinstance(v, Exception)],
    )
```

**Design rules:**
- **Always call in parallel.** Sequential composition sums the latency of every dependency.
- **Handle partial failure.** Returning a dashboard without the quota widget beats returning a 500.
- **Set an overall deadline** and cancel stragglers
- Be honest with the client about what is missing (`degraded: [...]`)
- **This is also the read-side of CQRS** (Chapter 01). If composition gets slow or complex, build a **materialised read model** instead of composing on every request.

## 8.20 Rate limiting at the API layer

(Algorithms are in Chapter 05. Here is the API-facing design.)

**Limit by the right dimension:**

| Dimension | Use for |
|-----------|---------|
| **API key / tenant** | The primary control for B2B APIs |
| **User ID** | Per-user fairness within a tenant |
| **IP address** | Unauthenticated endpoints (login, signup) — careful with NAT and mobile carriers |
| **Endpoint** | Expensive operations get their own, tighter limit |
| **Cost/weight** | A search costs 10 units, a GET costs 1 — **the fairest model** |

**Tiered limits by plan:**

```yaml
free:       { requests_per_minute: 60,    burst: 100,   concurrent: 5 }
pro:        { requests_per_minute: 1000,  burst: 2000,  concurrent: 50 }
enterprise: { requests_per_minute: 10000, burst: 20000, concurrent: 500 }
```

**Always return the headers** (§5.8) and **document the limits publicly**. An undocumented rate limit is an outage from the customer's perspective.

## 8.21 Service discovery (API view) 🟡

Covered in Chapter 05. In API terms:

- **Internal:** services call each other by **logical name** (`http://billing-service`), resolved by Kubernetes DNS / Consul / Eureka. Never hard-code IPs or ports.
- **External:** DNS + a load balancer + a stable public hostname
- **Service mesh** (Istio, Linkerd) moves discovery, retries, timeouts, mTLS and tracing out of your code and into a sidecar — worth it at ~20+ services, overkill below that

---

## 8.22 API documentation and contracts 🟢

**An undocumented API does not exist.**

### OpenAPI (formerly Swagger) — the standard

```yaml
openapi: 3.1.0
info:
  title: Verification API
  version: 1.0.0
paths:
  /v1/verification-sessions:
    post:
      summary: Start a verification session
      operationId: startSession
      parameters:
        - name: Idempotency-Key
          in: header
          required: true
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/StartSessionRequest' }
      responses:
        '201':
          description: Session created
          headers:
            Location: { schema: { type: string } }
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Session' }
        '422':
          description: Validation failed
          content:
            application/problem+json:
              schema: { $ref: '#/components/schemas/Problem' }
```

**What OpenAPI gives you beyond docs:**
- Generated clients in every language (stop hand-writing HTTP calls)
- Generated server stubs and request validation
- Mock servers for frontend teams before the backend exists
- **Automated breaking-change detection in CI** (`oasdiff`) — this is a fitness function (Chapter 00)
- Contract tests (Chapter 21)

> **Design-first vs code-first:** generating OpenAPI from annotated code is convenient, but design-first (write the spec, review it, then implement) produces better APIs, because the contract gets reviewed *before* it is expensive to change. For public APIs, design-first is worth the discipline.

### A good API reference also needs

- Authentication guide with a working example
- **Copy-pasteable curl examples** for every endpoint
- Error code reference
- Rate limits, quotas and pagination explained
- Webhook event catalogue with sample payloads
- A changelog and a deprecation policy
- A sandbox environment with test credentials

---

## 8.23 Choosing an API style

| Situation | Choose |
|-----------|--------|
| Public API for third parties | **REST + OpenAPI** |
| Browser → your backend | REST, or GraphQL if many varied screens |
| Internal service → service, high volume | **gRPC** |
| Mobile app with many different screens | **GraphQL** or a **mobile BFF** |
| Server pushes updates to a browser | **SSE** |
| Two-way real-time (chat, collaboration) | **WebSocket** |
| Notify another company's system | **Webhooks** (plus a polling fallback) |
| Long-running operation | REST `202 Accepted` + a status endpoint, or SSE for progress |
| Bulk data transfer | File export to object storage + a signed URL — **not** a paginated API |

> **The mature answer is usually "several".** gRPC internally, REST at the public edge, SSE for progress, webhooks for notifications, and a file export for bulk. Each is chosen for a reason you can state.

---

## 8.24 Common mistakes

1. **Verbs in URLs** — `/getUser`, `/createOrder`
2. **HTTP 200 with `{"success": false}`** — breaks every cache, monitor and client
3. **Unbounded list endpoints** — the day a customer has 4M rows, you find out
4. **Offset pagination at depth** — `OFFSET 500000` scans half the table
5. **No idempotency keys on money endpoints** — double charges on a client retry
6. **Exposing domain entities directly** — accidental data leaks and a frozen internal model
7. **No `Vary: Authorization`** — a shared cache serves one user's data to another
8. **Breaking changes without a version** — clients break silently in production
9. **No rate limiting** — one buggy customer script takes down the API for everyone
10. **Leaking internals in errors** — stack traces, SQL, hostnames
11. **Inconsistent naming** — `created_at` here, `creationDate` there, `CreatedAt` over there
12. **Ignoring the 401/403 and 400/422 distinctions** — clients cannot handle errors correctly
13. **WebSockets where SSE would do** — ten times the complexity for one-way updates
14. **Unsigned webhooks** — anyone who learns the URL can forge events
15. **No `Retry-After` on 429/503** — clients hammer you while you are already struggling

---

## 8.25 Architect's checklist

- [ ] Resources are nouns; methods are verbs; URLs are consistent and lowercase
- [ ] Correct status codes, including 401 vs 403 and 400 vs 422
- [ ] Errors use Problem Details with a machine code, field errors and a trace ID
- [ ] Every collection endpoint is paginated (cursor-based where it matters) with a capped limit
- [ ] Filter/sort fields are whitelisted and indexed
- [ ] Idempotency keys required on all non-idempotent, side-effecting POSTs
- [ ] ETag / `If-Match` on updatable resources (optimistic concurrency)
- [ ] Cache headers set deliberately, with `Vary` where needed
- [ ] Versioning strategy chosen; additive-change policy documented; tolerant-reader contract published
- [ ] Deprecation policy with `Deprecation`/`Sunset` headers and per-client usage metrics
- [ ] Rate limits implemented, documented, and returned in headers
- [ ] OpenAPI spec exists, is reviewed, and breaking changes fail CI
- [ ] Webhooks are signed with a timestamp, retried with backoff, deduplicable and replayable
- [ ] Payload size limits and request timeouts enforced
- [ ] Auth (Chapter 17) and CORS configured explicitly, not permissively

---

## 8.26 Self-test

1. Which two REST constraints deliver most of the practical value, and why?
2. Model "refund a payment" three different RESTful ways. Which is best and why?
3. 401 vs 403. 400 vs 422. 302 vs 307. Explain each pair.
4. Why is returning HTTP 200 with an error body harmful? Name three systems it breaks.
5. Why is offset pagination slow at depth? Write the SQL for cursor pagination with a stable tiebreaker.
6. Explain the ETag / `If-Match` flow and the bug it prevents.
7. Why is `Vary: Authorization` security-critical?
8. Which API changes are non-breaking? What is the "tolerant reader" contract?
9. gRPC vs REST vs GraphQL — give the deciding factor for each.
10. When would you choose SSE over WebSockets? Give a concrete example.
11. List six things a professional webhook provider must do.
12. What belongs in an API Gateway, and what must never go in it?
13. What problem does a BFF solve that a gateway does not?
14. Design the rate-limiting scheme for a three-tier SaaS API, including headers.

---

## 8.27 Key takeaways

- **An API is a permanent public promise.** Design it before you build it.
- **Resources are nouns, methods are verbs, status codes carry meaning** — use them properly
- **Cursor pagination, capped limits, whitelisted filters** — or your API is a DoS vector
- **Idempotency keys on money.** **ETags on updates.** Both are small and prevent whole bug classes.
- **Version additively** and publish a tolerant-reader contract; then you rarely need v2
- **Problem Details (RFC 9457)** for errors, with a trace ID
- **gRPC inside, REST at the edge, SSE for push, webhooks for notification** — pick per purpose
- **SSE is under-used**; most one-way push does not need WebSockets
- **Sign, retry, dedupe and replay** your webhooks
- **Gateway for cross-cutting concerns, BFF for client-specific shaping.** Never business logic in either.
- **OpenAPI in CI** turns "we broke the contract" into a failed build

---

**Next:** [Chapter 09 — Database Architecture](09-database-architecture.md)
