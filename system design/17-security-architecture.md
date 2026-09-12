# Chapter 17 — Security Architecture 🟢

> Security is not a feature you add in phase two. It is a **structural property**, like load-bearing walls.
> Bolted on afterwards, it is always partial, always expensive, and always leaks.
>
> For an architect there is one governing idea: **assume every layer will eventually fail, and make sure no single failure is catastrophic.**

---

## 17.1 The mental model

### Three questions, always in this order

1. **Authentication (AuthN)** — *Who are you?*
2. **Authorization (AuthZ)** — *What are you allowed to do?*
3. **Audit** — *What did you actually do?*

Confusing the first two causes a large share of real vulnerabilities. Skipping the third means you cannot answer the only question that matters after a breach: *what did they touch?*

### Defence in depth

```
                 Internet
                    │
    ┌───────────────▼───────────────┐
    │ 1. Edge:  DDoS, WAF, TLS      │
    ├───────────────────────────────┤
    │ 2. Network: firewall, private │
    │    subnets, segmentation      │
    ├───────────────────────────────┤
    │ 3. Identity: AuthN, MFA       │
    ├───────────────────────────────┤
    │ 4. Application: AuthZ,        │
    │    input validation, encoding │
    ├───────────────────────────────┤
    │ 5. Data: encryption, masking, │
    │    tokenisation               │
    ├───────────────────────────────┤
    │ 6. Monitoring: audit, alerting│
    └───────────────────────────────┘
```

> **Assume each layer will fail.** The WAF will be bypassed. A credential will leak. A developer will make a mistake. The question is not "how do we prevent everything?" but **"when layer N fails, what stops the attacker at layer N+1?"**

### The principles that actually drive design decisions

| Principle | What it means in practice |
|-----------|--------------------------|
| **Least privilege** | Every identity gets the minimum permissions, for the minimum time |
| **Fail secure** | On error, deny. An exception in your auth check must not mean "allowed". |
| **Complete mediation** | Check authorisation on **every** request. Never trust a prior check or a client-side one. |
| **Separation of duties** | The person who writes the payment code cannot approve their own production deploy |
| **Secure defaults** | New resources are private, new users have no permissions, encryption is on |
| **Minimise attack surface** | Every endpoint, port, dependency and permission you do not need is a liability |
| **Don't roll your own crypto** | Use vetted libraries. Always. Without exception. |
| **Assume breach** | Design so that a compromised component gains as little as possible |

---

# PART 1 — Identity and Access

## 17.2 Authentication 🟢

### Password handling — get this exactly right

```python
# ❌ NEVER: plaintext, MD5, SHA-1, SHA-256 (all far too fast to brute force)
# ✅ Use a memory-hard, purpose-built password hash
from argon2 import PasswordHasher

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)  # ~64 MB per hash

hashed = ph.hash(password)                    # salt is generated and embedded automatically

try:
    ph.verify(hashed, supplied_password)
    if ph.check_needs_rehash(hashed):          # parameters upgraded since? rehash silently
        store(ph.hash(supplied_password))
except VerifyMismatchError:
    raise InvalidCredentials()                 # same generic error for bad user AND bad password
```

**Preference order: Argon2id > scrypt > bcrypt > PBKDF2.** Never a bare hash function.

**Modern password policy (per NIST SP 800-63B — this overturns a lot of old advice):**

```
✅ Minimum 8 characters, allow up to 64+ ✅ Allow all characters including spaces and emoji
✅ Check against known-breached password lists (Have I Been Pwned's k-anonymity API)
✅ Encourage passphrases and password managers
❌ NO forced periodic rotation (it produces Password1! → Password2!)
❌ NO composition rules ("must contain a symbol") — they reduce entropy in practice
❌ NO password hints or knowledge-based security questions
❌ NO truncation, and no blocking of paste
```

**Other essentials:**
- **Generic error messages** — "invalid email or password", never "no such user" (that is account enumeration)
- **Constant-time comparison** for tokens and signatures (`hmac.compare_digest`)
- **Rate limit and lock out** progressively on failed attempts, per account **and** per IP
- **Timing:** perform a dummy hash when the user does not exist, so response time does not leak existence

### Multi-Factor Authentication

| Factor | Security | Notes |
|--------|----------|-------|
| **SMS OTP** | Weak | SIM swapping is a real, common attack. Better than nothing; do not use it for high-value accounts. |
| **TOTP** (authenticator app) | Good | Standard, offline, free. **The sensible default.** |
| **Push notification** | Good | Vulnerable to "MFA fatigue" — mitigate with number matching |
| **Passkeys / WebAuthn / FIDO2** ⭐ | **Strongest** | **Phishing-proof** — the credential is bound to the origin, so a fake site cannot use it |

> **Passkeys are the direction of travel.** They eliminate phishing and credential stuffing simultaneously, because there is no shared secret to steal or replay. Support them.

### Sessions vs tokens

| | **Server-side sessions** | **JWT (stateless)** |
|---|---|---|
| State | Stored server-side (Redis/DB) | Self-contained in the token |
| Revocation | **Instant** — delete the session | **Hard** — valid until expiry |
| Scale | Needs a shared session store | No lookup needed |
| Size | Small cookie | Larger; sent on every request |
| Best for | Web apps, anything needing instant revocation | Service-to-service, short-lived access tokens |

> **The most common JWT mistake is using them as long-lived sessions.** If a token is valid for 24 hours and you cannot revoke it, then firing an employee or detecting a compromise does not actually stop access for a day. **Access tokens should live 5–15 minutes**, with a revocable refresh token behind them.

---

## 17.3 OAuth 2.0 and OpenID Connect 🟢

**The crucial distinction people get wrong:**

```
OAuth 2.0  = AUTHORIZATION.  "This app may read my calendar."
OIDC       = AUTHENTICATION. "This is who I am."  (a thin layer ON TOP of OAuth 2.0)
```

Using raw OAuth 2.0 for login is a known anti-pattern — an access token proves *access*, not *identity*. **OIDC adds the `id_token`**, which is the identity assertion. If you are implementing "Sign in with X", you want OIDC.

### The four roles

```
RESOURCE OWNER      the user
CLIENT              your application
AUTHORIZATION SERVER  issues tokens (Auth0, Keycloak, Entra ID, Cognito)
RESOURCE SERVER     your API, which accepts tokens
```

### Authorization Code flow with PKCE ⭐ (the only flow you should use for user login)

```
1. App generates:  code_verifier = random(64 bytes)
                   code_challenge = BASE64URL(SHA256(code_verifier))

2. Browser → Auth Server:
   /authorize?response_type=code
             &client_id=...
             &redirect_uri=https://app.example.com/callback
             &scope=openid profile email
             &state=<random, anti-CSRF>
             &code_challenge=<challenge>&code_challenge_method=S256

3. User authenticates and consents

4. Auth Server → Browser → App:  /callback?code=<auth_code>&state=<same>
                                  ← app MUST verify `state` matches

5. App → Auth Server (back channel, server-to-server):
   POST /token  { code, code_verifier, client_id, redirect_uri }

6. Auth Server verifies SHA256(code_verifier) == stored code_challenge
   → returns { access_token, id_token, refresh_token }
```

**Why PKCE:** if an attacker intercepts the authorisation code (a malicious app registering the same URI scheme, a leaky redirect, browser history), they still cannot exchange it — they do not have the `code_verifier`. **PKCE is now recommended for all clients, including confidential server-side ones**, not just mobile.

### Flows: use and avoid

| Flow | Use? |
|------|------|
| **Authorization Code + PKCE** | ✅ **Everything user-facing** — web, SPA, mobile, desktop |
| **Client Credentials** | ✅ Machine-to-machine (no user involved) |
| **Device Code** | ✅ TVs, CLIs, input-constrained devices |
| **Refresh Token** | ✅ With rotation and reuse detection |
| **Implicit** | ❌ **Deprecated** — tokens in the URL fragment, leaks everywhere |
| **Resource Owner Password Credentials** | ❌ **Deprecated** — the app handles the password, defeating the purpose |

### JWT — validate properly

```python
claims = jwt.decode(
    token,
    key=public_key_from_jwks,              # fetched from the issuer's JWKS endpoint, cached
    algorithms=["RS256"],                  # ⭐ PIN THE ALGORITHM — never trust the header
    audience="https://api.example.com",    # ⭐ is this token FOR us?
    issuer="https://auth.example.com/",    # ⭐ did WE issue it (or our trusted IdP)?
    options={"require": ["exp", "iat", "sub", "aud", "iss"]},
)
```

**The JWT vulnerabilities you must know:**

1. **`alg: none`** — an unsigned token accepted as valid. **Always pin allowed algorithms explicitly.**
2. **Algorithm confusion (RS256 → HS256)** — the attacker signs with the *public* key as an HMAC secret. Pinning prevents it.
3. **Missing `aud` validation** — a token issued for a different service is accepted by yours
4. **Missing `exp` validation** — expired tokens still work
5. **Trusting claims without verifying the signature** — decoding is not validating
6. **Secrets in the payload** — a JWT is **base64, not encrypted.** Anyone can read it. Put nothing sensitive in it.
7. **Long expiry with no revocation** — see §17.2

### Refresh token rotation

```
Client uses refresh token RT1 → server issues new access token + RT2, INVALIDATES RT1
If RT1 is ever presented again → it was stolen → REVOKE THE ENTIRE TOKEN FAMILY
```

This detects theft rather than merely hoping it does not happen, and it is straightforward to implement. Store refresh tokens hashed, bind them to a client/device, and set an absolute maximum lifetime.

---

## 17.4 Authorization models 🟢

### RBAC — Role-Based Access Control

```
User → Role(s) → Permissions

alice → [reviewer]      → [session:read, session:approve, session:reject]
bob   → [tenant_admin]  → [session:*, user:*, billing:read]
```

✅ Simple, familiar, auditable, easy to explain to auditors
❌ **Role explosion** — `reviewer_eu_readonly_tier2` appears once you need context. RBAC alone cannot express "only their own tenant's data".

### ABAC — Attribute-Based Access Control

Decisions from attributes of the **subject**, **resource**, **action** and **environment**.

```python
def can_approve(user: User, session: Session, ctx: Context) -> bool:
    return (
        user.has_permission("session:approve")
        and session.tenant_id == user.tenant_id        # tenant isolation
        and session.status == SessionStatus.PENDING_REVIEW
        and session.created_by != user.id              # separation of duties
        and ctx.ip_in_allowed_range(user.tenant.ip_allowlist)
        and ctx.time_within_business_hours(user.tenant.timezone)
    )
```

✅ Expressive, fine-grained, no role explosion
❌ Harder to reason about and audit ("who can access X?" needs evaluation, not a lookup)

### ReBAC — Relationship-Based Access Control ⭐

Permissions derive from relationships in a graph (the Google Zanzibar model; OpenFGA, SpiceDB, Permify).

```
user:alice      is  owner        of  document:budget2026
group:finance   is  viewer       of  document:budget2026
user:bob        is  member       of  group:finance
                                     → bob can view budget2026 (derived)
```

This is how Google Docs, GitHub and Notion-style sharing work. When permissions are inherited through hierarchies (folder → document, org → team → repo), ReBAC is dramatically cleaner than either RBAC or ABAC.

### The practical recommendation

> **Most real systems use RBAC for coarse capabilities + ABAC for context.**
> "Does this user have the `session:approve` permission?" (RBAC) **and** "is this session in their tenant?" (ABAC).

### Authorization architecture 🟢

```
❌ Authorization logic scattered through controllers
   → inconsistent, untestable, and one forgotten check is a breach

✅ Centralised policy, enforced at a single point per request
```

```python
# A policy decision point — one place, testable, auditable
class AuthorizationService:
    async def authorize(self, principal: Principal, action: str,
                        resource: Resource) -> Decision:
        if not principal.has_permission(action):
            return Decision.deny("missing_permission", action)
        if resource.tenant_id != principal.tenant_id:
            # log as a potential attack, but return the SAME error as "not found"
            audit.log_suspicious("cross_tenant_attempt", principal, resource)
            return Decision.deny("not_found")
        for rule in self._rules_for(action):
            if not await rule.evaluate(principal, resource):
                return Decision.deny(rule.name)
        return Decision.allow()
```

**Two rules that prevent the most common breaches:**

**1. Tenant isolation must be enforced at the data layer, not just in application code.**

```sql
-- PostgreSQL Row-Level Security: even a forgotten WHERE clause cannot leak data
ALTER TABLE verification_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON verification_sessions
    USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

This is defence in depth in its purest form: a SQL injection or a missing filter still cannot cross tenants.

**2. Deny must look like "not found".** Returning 403 for a resource that exists and 404 for one that does not leaks the existence of other tenants' data. Return **404 for both**.

### IDOR — the most common web vulnerability

```python
# ❌ Insecure Direct Object Reference — the #1 finding in real pentests
@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    return await db.get_session(session_id)     # ANY id works. Any tenant. Any user.

# ✅ Always scope by the authenticated principal
@app.get("/sessions/{session_id}")
async def get_session(session_id: str, principal: Principal = Depends(current_principal)):
    session = await db.get_session(session_id, tenant_id=principal.tenant_id)
    if session is None:
        raise HTTPException(404)                # same response whether missing or forbidden
    return session
```

> **Test for this deliberately:** in your integration tests, have tenant A attempt to read every one of tenant B's resources by ID and assert 404. Automate it. This single test class catches the highest-impact bug category in multi-tenant SaaS.

---

# PART 2 — Application security

## 17.5 OWASP Top 10 🟢

The canonical list of what actually goes wrong. Know all ten; know the defence for each.

### A01 — Broken Access Control (the #1 category)

Covered in §17.4. IDOR, missing function-level checks, client-side-only enforcement, path traversal, CORS misconfiguration.

**Defences:** deny by default; centralised policy; scope every query by the principal; RLS at the database; automated cross-tenant tests.

### A02 — Cryptographic Failures

```
❌ Sensitive data over HTTP
❌ Weak or home-made crypto (ECB mode, static IVs, custom "encryption")
❌ Hard-coded keys
❌ Data at rest unencrypted
```

**Defences:** TLS 1.3 everywhere including internally; AES-256-GCM (authenticated encryption) or a high-level library (libsodium, `cryptography.fernet`); keys in a KMS/HSM, rotated; classify data and encrypt by classification.

### A03 — Injection

```python
# ❌ SQL injection
cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")
#   email = "' OR '1'='1' --"   → returns everyone

# ✅ Parameterised queries — the database never confuses data with code
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
```

```python
# ❌ Command injection
os.system(f"ffmpeg -i {filename} out.mp4")
#   filename = "x.mp4; rm -rf /"

# ✅ Argument list, never a shell
subprocess.run(["ffmpeg", "-i", filename, "out.mp4"], shell=False, check=True)
```

Also: NoSQL injection (`{"$ne": null}` as a password), LDAP injection, template injection (SSTI), and XXE in XML parsers (disable external entities).

> **The universal defence: never build a command, query or template by string concatenation with untrusted input.** Use the parameterised mechanism the library provides. Dynamic identifiers (table/column names) cannot be parameterised — **whitelist** them.

### A04 — Insecure Design

The category that is specifically an **architect's** responsibility: missing rate limits, no threat model, business-logic flaws (negative quantities, price manipulation, race conditions in redemption codes), unlimited resource consumption.

> No amount of secure coding fixes a design that allows a user to order −5 items and receive a refund.

### A05 — Security Misconfiguration

Default credentials, verbose errors in production, unnecessary features enabled, missing security headers, public cloud storage, directory listings.

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), camera=(), microphone=()
```

**CSP is the single most effective defence against XSS**, and `frame-ancestors 'none'` replaces the old `X-Frame-Options` for clickjacking.

### A06 — Vulnerable and Outdated Components

Your dependencies are your attack surface. Log4Shell, event-stream, and the xz backdoor were all supply-chain events.

**Defences:** SCA scanning in CI (Dependabot, Snyk, `pip-audit`); lockfiles; **SBOM** so you can answer "are we affected?" in minutes; pin versions; scan container base images; minimise dependencies (does this really need a library?); prefer packages with real maintenance.

### A07 — Identification and Authentication Failures

Credential stuffing, weak recovery flows, session fixation, missing MFA. Covered in §17.2–17.3.

**Also:** regenerate the session ID on privilege change (login, role change) — otherwise session fixation works.

### A08 — Software and Data Integrity Failures

Unsigned artefacts, insecure CI/CD, **insecure deserialisation**.

```python
# ❌ NEVER deserialise untrusted data with pickle/yaml.load/Java serialization
data = pickle.loads(user_supplied_bytes)     # arbitrary code execution
# ✅
data = json.loads(user_supplied_bytes)       # data only, no code
```

**Defences:** sign container images (cosign) and verify at admission; protect the build pipeline as a production system (it has production credentials); pin and verify dependencies.

### A09 — Security Logging and Monitoring Failures

The average breach goes undetected for months. If you cannot detect it, everything above is theatre.

**Log these events, always:** authentication success and failure, authorisation denials, privilege changes, access to sensitive data, configuration changes, admin actions, payment events.

```python
audit.log(
    event="verification.approved",
    actor=principal.id, actor_ip=request.client.host,
    resource_type="session", resource_id=session.id,
    tenant_id=principal.tenant_id,
    result="success", trace_id=current_trace_id(),
    timestamp=datetime.now(timezone.utc),
)
```

**Rules:** never log secrets, tokens, passwords or full PII; make audit logs **append-only and separately stored** (an attacker who gets in should not be able to erase the evidence); retain for your compliance period; **alert on patterns**, not just individual events.

### A10 — Server-Side Request Forgery (SSRF)

```python
# ❌ The application fetches a URL the user supplies
requests.get(user_supplied_url)
#   http://169.254.169.254/latest/meta-data/iam/security-credentials/
#   → cloud credentials stolen. This is how Capital One lost 100M records.
```

**Defences:** allowlist destination hosts; resolve the DNS and **validate the resolved IP** against private ranges (Chapter 13) — and re-validate after redirects to prevent DNS rebinding; disable redirects; require IMDSv2 (which requires a token and blocks naive SSRF); route outbound calls through an egress proxy that enforces the allowlist.

---

## 17.6 CSRF, XSS and browser security 🟢

### XSS — Cross-Site Scripting

```html
<!-- ❌ Reflected/stored XSS -->
<div>Welcome, {{ user_name|safe }}</div>       <!-- user_name = <script>steal()</script> -->

<!-- ✅ Escape by default (modern frameworks do this automatically) -->
<div>Welcome, {{ user_name }}</div>
```

**Defence stack, in order of effectiveness:**
1. **Context-aware output encoding** — HTML body, attribute, JavaScript and URL contexts each need different escaping. Let your framework do it; never disable it.
2. **CSP** — even if XSS exists, the browser refuses to execute injected script
3. **`HttpOnly` cookies** — JavaScript cannot read the session cookie, so XSS cannot steal it
4. **Sanitise rich HTML input** with a vetted library (DOMPurify), never with a regex

### CSRF — Cross-Site Request Forgery

An attacker's site causes the user's browser to make an authenticated request to yours.

**Defences:**
1. **`SameSite` cookies** — `Lax` is the browser default now and blocks most CSRF; use `Strict` for sensitive actions
2. **Anti-CSRF tokens** — synchroniser token or double-submit cookie
3. **Check `Origin`/`Referer`** on state-changing requests
4. **Never use GET for state changes** (a GET can be triggered by an `<img>` tag)

> **Token-based APIs (Authorization header) are largely immune to CSRF** because the browser does not attach the header automatically. Cookie-based sessions are the ones that need protection. Know which you are building.

### Cookie flags

```
Set-Cookie: session=...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=3600
            ^^^^^^^^^^^^^^^^^^^^^ all four matter
```

---

# PART 3 — Data and infrastructure security

## 17.7 Encryption 🟢

### In transit

TLS 1.3 everywhere, **including internal service-to-service traffic** (fallacy #4, Chapter 05). mTLS for service identity, ideally via a service mesh with automatic short-lived certificates (Chapter 15).

### At rest

| Layer | What it protects against | What it does NOT protect against |
|-------|-------------------------|----------------------------------|
| **Disk/volume encryption** | Stolen physical disks | Anything with database access |
| **Database TDE** | Stolen database files and backups | A compromised application |
| **Column/field encryption** | DBAs, backups, partial breaches | A compromised application with the key |
| **Application-level encryption** | Almost everything below the app | A compromised application |

> **Important honesty:** "we encrypt at rest" is frequently a compliance checkbox that stops almost no realistic attack — if the attacker has application or database credentials, transparent encryption is invisible to them. **Field-level encryption of genuinely sensitive data, with keys the database cannot access, is the control that actually helps.**

```python
# Envelope encryption — the standard pattern
# 1. Generate a random data key (DEK) per record or per tenant
# 2. Encrypt the data with the DEK
# 3. Encrypt the DEK with a master key in KMS (the KEK)
# 4. Store the ciphertext + the encrypted DEK together
#
# → Key rotation means re-encrypting DEKs, not terabytes of data
# → Per-subject DEKs enable CRYPTO-SHREDDING: delete the key = the data is gone
```

**Crypto-shredding** is the practical answer to GDPR erasure in immutable systems — event stores, append-only logs, backups (Chapters 02, 12).

### Key management

```
✅ Keys in a KMS/HSM, never in code, config, or the same database as the data
✅ Separate keys per environment, per tenant where the threat model justifies it
✅ Automatic rotation with a defined schedule
✅ Key access logged and alerted
✅ A documented, tested key-recovery procedure — losing a key means losing the data
❌ One key for everything, forever
```

### Data classification drives everything

| Class | Examples | Controls |
|-------|----------|----------|
| **Public** | Marketing content | None |
| **Internal** | Metrics, architecture docs | Access control |
| **Confidential** | Customer records, contracts | + encryption, audit logging |
| **Restricted** | Payment data, biometrics, health, government IDs | + field encryption, strict least privilege, retention limits, DLP, possible regulatory scope |

> **Classify first.** You cannot apply proportionate controls to data you have not categorised. For a KYC/liveness product, face images and document scans are **restricted biometric data** in most jurisdictions — with specific legal requirements (GDPR Article 9, Illinois BIPA, and similar). That classification is an architectural constraint, not a policy footnote: it determines where the data may be stored, who may see it, how long you may keep it, and what you must be able to prove.

---

## 17.8 Zero Trust 🟡

**Old model ("castle and moat"):** a hard perimeter; everything inside is trusted. It fails because the perimeter dissolved (cloud, remote work, SaaS, mobile) and because one compromised host gives an attacker the whole interior.

**Zero Trust:** *"Never trust, always verify."* There is no trusted network.

### The principles

1. **Verify explicitly** — authenticate and authorise every request, based on identity, device, location and behaviour
2. **Least privilege access** — just-in-time and just-enough, with time-bound elevation
3. **Assume breach** — segment, encrypt everywhere, monitor continuously, limit blast radius

### What it means concretely

| Old | Zero Trust |
|-----|-----------|
| VPN into the network, then everything is reachable | Per-application access, per-request authorisation |
| Services trust each other because they share a subnet | **mTLS with service identity; every call authorised** |
| Static admin accounts | Just-in-time elevation, time-limited, approved, recorded |
| One firewall at the edge | Micro-segmentation; default-deny between workloads |
| Trust the device because it is on the office network | Device posture is part of the access decision |

**For an architect, the practical checklist:**
- [ ] Every service-to-service call is authenticated (mTLS or signed tokens) — not just "it came from our VPC"
- [ ] Every service has its own identity with its own minimal permissions
- [ ] Network policies default-deny (Chapter 13/15)
- [ ] No shared service accounts; no long-lived credentials
- [ ] Human production access is time-bound, approved and recorded

---

## 17.9 Threat modelling 🟢

**The one security activity with the highest return on time for an architect.** Two hours, a whiteboard, and a design diagram.

### STRIDE

| Threat | Question | Mitigation |
|--------|----------|-----------|
| **S**poofing | Can someone pretend to be someone else? | Strong AuthN, MFA, mTLS |
| **T**ampering | Can data be modified in transit or at rest? | TLS, signatures, integrity checks, audit |
| **R**epudiation | Can someone deny doing something? | Append-only audit logs, signed actions |
| **I**nformation disclosure | Can data leak? | Encryption, access control, minimisation |
| **D**enial of service | Can it be made unavailable? | Rate limiting, quotas, autoscaling, load shedding |
| **E**levation of privilege | Can someone gain more rights? | Least privilege, input validation, segmentation |

### The process

```
1. DRAW the system: components, data stores, data flows, and TRUST BOUNDARIES
   (a trust boundary is anywhere data crosses between different levels of trust:
    internet → your edge, your app → a vendor, tenant A → tenant B)

2. For each ELEMENT and each FLOW, walk through STRIDE.
   "Can someone spoof this? Tamper with this? ..."

3. RATE each finding (likelihood × impact).

4. DECIDE per finding: mitigate / accept / transfer / eliminate.

5. WRITE IT DOWN and re-review when the architecture changes.
```

### Worked fragment — the liveness verification system

| Element | Threat | Risk | Mitigation |
|---------|--------|------|-----------|
| Video upload (presigned URL) | **T**ampering — user uploads a pre-recorded video | High | Server-issued challenge with a nonce; verify the challenge response matches; check capture metadata; anti-spoof model |
| Presigned URL | **I**nformation disclosure — URL shared or leaked | Medium | Short expiry (15 min), single-use where possible, scoped to one object key |
| Verification result | **T**ampering — client-side manipulation of the outcome | **Critical** | The decision is server-side only; the result is never trusted from the client; results are signed |
| Face images at rest | **I**nformation disclosure — breach exposes biometrics | **Critical** | Field-level encryption with per-tenant keys; 90-day retention; access logged and alerted; restricted classification |
| Vendor API call | **S**poofing — a compromised vendor returns false results | High | mTLS to the vendor; validate response shape and signature; second vendor for high-risk cases |
| Tenant data | **E**levation — tenant A reads tenant B's sessions | **Critical** | Policy at a single enforcement point + Postgres RLS + automated cross-tenant tests |
| Admin console | **E**levation — compromised admin account | High | MFA mandatory, IP allowlist, just-in-time elevation, all actions audited |
| API | **D**enial of service — one tenant exhausts GPU capacity | Medium | Per-tenant rate limits and quotas; queue-based load levelling; per-tenant concurrency caps |

> Notice how many mitigations are **architectural** — where the decision is made, where the data lives, which boundary enforces isolation. That is why threat modelling belongs to the architect and belongs at design time, not after.

---

## 17.10 Compliance as an architectural constraint 🟡

| Regime | Applies to | Architectural implications |
|--------|-----------|---------------------------|
| **GDPR** | EU residents' personal data | Lawful basis, data minimisation, **right to erasure**, portability, breach notice in 72 h, residency, DPIA for high-risk processing (biometrics qualify) |
| **PCI-DSS** | Card data | Network segmentation, no storage of CVV, key management, quarterly scans. **Scope reduction is the whole game** — use a payment provider and never touch card data. |
| **HIPAA** | US health data | Encryption, audit, BAAs with vendors, minimum necessary |
| **SOC 2** | B2B SaaS trust | Change management, access reviews, monitoring, vendor management — mostly *evidence of process* |
| **BIPA / biometric laws** | Biometric identifiers | **Explicit written consent, published retention schedule, deletion deadlines, no sale.** Statutory damages per violation — this is a genuine commercial risk for a liveness product. |

**The three architectural moves that make compliance tractable:**

1. **Reduce scope.** Card data never entering your systems removes most of PCI. Tokenising PII into one service removes it from the other forty.
2. **Isolate regulated data** into a small number of components with strong controls, rather than spreading it everywhere.
3. **Build the evidence in.** Audit logs, access reviews and retention automation should be *features*, not a scramble before an audit.

> **Ask early: "What is the smallest part of our system that must be in scope?"** That question saves more compliance money than any other.

---

## 17.11 Common mistakes

1. **Authorization checks scattered across controllers** — one missed check is a breach
2. **IDOR** — not scoping queries by the authenticated principal. The most common real vulnerability.
3. **403 vs 404 leaking existence** of other tenants' resources
4. **Long-lived JWTs with no revocation path**
5. **Not validating `aud`, `iss`, `exp`, or pinning `alg`**
6. **Secrets in git, images, or logs** — permanent once pushed
7. **String concatenation into SQL, shell commands, or templates**
8. **Trusting the internal network** — unencrypted service-to-service traffic
9. **Client-side-only validation or authorisation** — trivially bypassed
10. **User-supplied URLs fetched server-side** (SSRF) — the cloud metadata endpoint is right there
11. **No rate limiting on authentication endpoints** — credential stuffing at full speed
12. **"Encrypted at rest" as a checkbox** that stops no realistic attack
13. **No audit log, or a mutable one an attacker can erase**
14. **Security reviewed at the end** — when changes are most expensive
15. **No automated cross-tenant isolation tests**

---

## 17.12 Architect's checklist

**Identity**
- [ ] Argon2id (or bcrypt) password hashing; breached-password checking; no forced rotation
- [ ] MFA available and enforced for admin/privileged roles; passkeys supported
- [ ] Authorization Code + PKCE; implicit and password grants disabled
- [ ] Access tokens 5–15 minutes; refresh tokens rotated with reuse detection
- [ ] JWT validation pins `alg` and checks `aud`, `iss`, `exp`
- [ ] Session ID regenerated on privilege change

**Authorization**
- [ ] Single, centralised policy enforcement point — not scattered checks
- [ ] Every query scoped by the authenticated principal
- [ ] Tenant isolation enforced at the data layer (RLS) as well as the application
- [ ] Deny returns 404, not 403, for resources in other tenants
- [ ] Automated cross-tenant access tests in CI

**Application**
- [ ] Parameterised queries and argument-list subprocess calls everywhere
- [ ] Output encoding on by default; CSP configured and tested
- [ ] `HttpOnly`, `Secure`, `SameSite` on all cookies
- [ ] Rate limiting on auth, password reset, and expensive endpoints
- [ ] No untrusted deserialisation
- [ ] SSRF protection: allowlist, resolved-IP validation, IMDSv2, no redirects

**Data**
- [ ] Data classified; controls proportionate to classification
- [ ] TLS 1.3 everywhere including internal; mTLS between services
- [ ] Field-level encryption for restricted data; keys in KMS, rotated
- [ ] Crypto-shredding strategy for erasure in immutable stores
- [ ] Retention policies automated; deletion verifiable

**Operations**
- [ ] Threat model exists and is reviewed on significant architecture change
- [ ] Audit log: append-only, separately stored, retained, alerted on patterns
- [ ] Dependency and container scanning in CI; SBOM generated
- [ ] Artefacts signed and verified at deployment
- [ ] No long-lived credentials anywhere; workload identity used
- [ ] Incident response plan written, with a named owner and a practised drill
- [ ] Penetration test scheduled for anything handling regulated data

---

## 17.13 Self-test

1. AuthN, AuthZ, Audit — define each and give the consequence of skipping the third.
2. Why is SHA-256 wrong for passwords? What should you use and why?
3. Which modern password rules overturn traditional advice, and why?
4. OAuth 2.0 vs OIDC — what is the difference and which do you use for login?
5. Explain PKCE and the exact attack it prevents.
6. Name six ways JWT validation goes wrong.
7. Why are long-lived JWTs a problem, and what is the standard fix?
8. RBAC vs ABAC vs ReBAC — give a scenario where each is the right model.
9. What is IDOR? Write the vulnerable and the fixed code.
10. Why should a forbidden resource return 404 rather than 403?
11. How does Postgres RLS provide defence in depth for multi-tenancy?
12. Explain SSRF and how Capital One's breach worked. Give four defences.
13. What does "encrypted at rest" actually protect against, and what does it not?
14. What is crypto-shredding and which problem does it solve?
15. Walk STRIDE over an API endpoint that accepts a file upload.
16. Name the three architectural moves that make compliance tractable.

---

## 17.14 Key takeaways

- **Security is structural.** Bolted on later, it is always partial.
- **Defence in depth: assume every layer fails** and ask what stops the attacker at the next one
- **Broken access control is the #1 real vulnerability.** Centralise policy; scope every query by the principal; enforce tenant isolation at the database too.
- **Short-lived access tokens + rotating refresh tokens**, never long-lived unrevocable JWTs
- **Authorization Code + PKCE** for every user-facing flow; implicit and password grants are dead
- **Never concatenate untrusted input** into SQL, shell commands, or templates
- **Never trust the network**, internal or not — mTLS and per-request authorisation
- **Classify data first**, then apply proportionate controls. Biometrics are restricted data with legal consequences.
- **Threat modelling is the highest-return security activity an architect can do** — two hours with STRIDE and a diagram
- **Audit logs are append-only and separately stored**, or they are evidence an attacker can delete
- **Reduce compliance scope** — the smallest regulated footprint is the cheapest one

---

**Next:** [Chapter 18 — Observability](18-observability.md)
