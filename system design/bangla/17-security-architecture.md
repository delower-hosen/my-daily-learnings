# অধ্যায় ১৭ — Security Architecture 🟢

> Security এমন কোনো feature নয় যা আপনি দ্বিতীয় ধাপে যোগ করেন। এটা একটা **কাঠামোগত বৈশিষ্ট্য**, load-bearing দেয়ালের মতো।
> পরে জুড়ে দিলে এটা সবসময় আংশিক, সবসময় ব্যয়বহুল, আর সবসময় ফাঁস করে।
>
> একজন আর্কিটেক্টের জন্য একটাই পরিচালক ধারণা: **ধরে নিন প্রতিটা স্তর শেষ পর্যন্ত fail করবে, আর নিশ্চিত করুন যে কোনো একটা ব্যর্থতাই বিপর্যয়কর নয়।**

---

## ১৭.১ মানসিক মডেল

### তিনটা প্রশ্ন, সবসময় এই ক্রমে

১. **Authentication (AuthN)** — *আপনি কে?*
২. **Authorization (AuthZ)** — *আপনার কী করার অনুমতি আছে?*
৩. **Audit** — *আপনি আসলে কী করলেন?*

প্রথম দুটো গুলিয়ে ফেলা সত্যিকারের দুর্বলতার একটা বড় অংশের কারণ। তৃতীয়টা বাদ দেওয়া মানে একটা breach-এর পর একমাত্র গুরুত্বপূর্ণ প্রশ্নটার উত্তর আপনি দিতে পারবেন না: *তারা কী ছুঁয়েছিল?*

### স্তরে স্তরে প্রতিরক্ষা

```
                 ইন্টারনেট
                    │
    ┌───────────────▼───────────────┐
    │ ১. Edge:  DDoS, WAF, TLS      │
    ├───────────────────────────────┤
    │ ২. Network: firewall, private │
    │    subnet, segmentation       │
    ├───────────────────────────────┤
    │ ৩. Identity: AuthN, MFA       │
    ├───────────────────────────────┤
    │ ৪. Application: AuthZ,        │
    │    input যাচাই, encoding       │
    ├───────────────────────────────┤
    │ ৫. Data: encryption, masking, │
    │    tokenisation               │
    ├───────────────────────────────┤
    │ ৬. Monitoring: audit, alert   │
    └───────────────────────────────┘
```

> **ধরে নিন প্রতিটা স্তর fail করবে।** WAF এড়ানো হবে। একটা credential ফাঁস হবে। একজন ডেভেলপার ভুল করবেন। প্রশ্নটা "আমরা কীভাবে সব ঠেকাব?" নয়, বরং **"N স্তর fail করলে আক্রমণকারীকে N+1 স্তরে কী থামায়?"**

### যে নীতিগুলো আসলে design-এর সিদ্ধান্ত চালায়

| নীতি | বাস্তবে এর মানে |
|-----------|--------------------------|
| **Least privilege** | প্রতিটা পরিচয় ন্যূনতম permission পায়, ন্যূনতম সময়ের জন্য |
| **Fail secure** | Error হলে deny করুন। আপনার auth যাচাইয়ে একটা exception মানে "অনুমোদিত" হতে পারে না। |
| **Complete mediation** | **প্রতিটা** request-এ authorisation যাচাই করুন। আগের কোনো যাচাই বা client-side যাচাই বিশ্বাস করবেন না। |
| **দায়িত্বের বিভাজন** | যিনি payment-এর কোড লেখেন তিনি নিজের production deploy অনুমোদন করতে পারবেন না |
| **নিরাপদ default** | নতুন resource private, নতুন ব্যবহারকারীর কোনো permission নেই, encryption চালু |
| **আক্রমণের পরিসর কমান** | যে প্রতিটা endpoint, port, dependency আর permission আপনার লাগে না সেটা একটা দায় |
| **নিজের crypto বানাবেন না** | যাচাই করা library ব্যবহার করুন। সবসময়। কোনো ব্যতিক্রম ছাড়া। |
| **Breach ধরে নিন** | এমনভাবে design করুন যাতে একটা আপসকৃত component যতটা সম্ভব কম পায় |

---

# পর্ব ১ — Identity আর Access

## ১৭.২ Authentication 🟢

### Password সামলানো — এটা একদম ঠিকভাবে করুন

```python
# ❌ কখনোই না: plaintext, MD5, SHA-1, SHA-256 (সবগুলোই brute force-এর জন্য অনেক দ্রুত)
# ✅ একটা memory-hard, উদ্দেশ্য-ভিত্তিক password hash ব্যবহার করুন
from argon2 import PasswordHasher

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)  # প্রতি hash-এ ~৬৪ MB

hashed = ph.hash(password)                    # salt স্বয়ংক্রিয়ভাবে তৈরি আর ভেতরে রাখা হয়

try:
    ph.verify(hashed, supplied_password)
    if ph.check_needs_rehash(hashed):          # parameter উন্নত হয়েছে? নীরবে rehash করুন
        store(ph.hash(supplied_password))
except VerifyMismatchError:
    raise InvalidCredentials()                 # খারাপ user আর খারাপ password — দুটোতেই একই সাধারণ error
```

**পছন্দের ক্রম: Argon2id > scrypt > bcrypt > PBKDF2।** কখনো একটা খালি hash function নয়।

**আধুনিক password policy (NIST SP 800-63B অনুযায়ী — এটা অনেক পুরনো পরামর্শ উল্টে দেয়):**

```
✅ ন্যূনতম ৮ অক্ষর, ৬৪+ পর্যন্ত অনুমতি দিন   ✅ স্পেস আর ইমোজি সহ সব অক্ষর অনুমতি দিন
✅ জানা ফাঁস-হওয়া password-এর তালিকার সাথে মিলিয়ে দেখুন (Have I Been Pwned-এর k-anonymity API)
✅ Passphrase আর password manager উৎসাহিত করুন
❌ জোর করে পর্যায়ক্রমে বদলানো নয় (এটা Password1! → Password2! তৈরি করে)
❌ গঠনের নিয়ম নয় ("একটা symbol থাকতে হবে") — বাস্তবে এগুলো entropy কমায়
❌ কোনো password hint বা জ্ঞান-ভিত্তিক নিরাপত্তা প্রশ্ন নয়
❌ কোনো ছাঁটাই নয়, আর paste আটকানো নয়
```

**অন্য অপরিহার্য বিষয়:**
- **সাধারণ error message** — "invalid email or password", কখনো "এমন কোনো user নেই" নয় (সেটা account enumeration)
- Token আর signature-এ **constant-time তুলনা** (`hmac.compare_digest`)
- ব্যর্থ চেষ্টায় ধাপে ধাপে **rate limit আর lock out**, প্রতি account-এ **আর** প্রতি IP-তে
- **সময়:** ব্যবহারকারী না থাকলেও একটা নকল hash করুন, যাতে response-এর সময় অস্তিত্ব ফাঁস না করে

### Multi-Factor Authentication

| Factor | নিরাপত্তা | নোট |
|--------|----------|-------|
| **SMS OTP** | দুর্বল | SIM swap একটা বাস্তব, সাধারণ আক্রমণ। কিছু না থাকার চেয়ে ভালো; উচ্চ-মূল্যের account-এ ব্যবহার করবেন না। |
| **TOTP** (authenticator app) | ভালো | প্রচলিত, offline, বিনামূল্যে। **যুক্তিসঙ্গত default।** |
| **Push notification** | ভালো | "MFA ক্লান্তি"-তে দুর্বল — number matching দিয়ে উপশম করুন |
| **Passkey / WebAuthn / FIDO2** ⭐ | **সবচেয়ে শক্তিশালী** | **Phishing-প্রতিরোধী** — credential origin-এর সাথে বাঁধা, তাই একটা নকল সাইট সেটা ব্যবহার করতে পারে না |

> **Passkey-ই যাত্রার দিক।** এগুলো একইসাথে phishing আর credential stuffing দূর করে, কারণ চুরি বা replay করার মতো কোনো ভাগ করা secret নেই। এগুলো সাপোর্ট করুন।

### Session বনাম token

| | **Server-side session** | **JWT (stateless)** |
|---|---|---|
| State | Server-এ জমা (Redis/DB) | Token-এর ভেতরেই স্বয়ংসম্পূর্ণ |
| বাতিল করা | **তাৎক্ষণিক** — session মুছুন | **কঠিন** — মেয়াদ শেষ না হওয়া পর্যন্ত বৈধ |
| Scale | একটা shared session store লাগে | কোনো lookup লাগে না |
| আকার | ছোট cookie | বড়; প্রতিটা request-এ পাঠানো হয় |
| কীসের জন্য সেরা | Web app, তাৎক্ষণিক বাতিল লাগে এমন যা কিছু | Service-থেকে-service, স্বল্পস্থায়ী access token |

> **সবচেয়ে সাধারণ JWT ভুল হলো এগুলোকে দীর্ঘস্থায়ী session হিসেবে ব্যবহার করা।** একটা token যদি ২৪ ঘণ্টা বৈধ থাকে আর আপনি সেটা বাতিল করতে না পারেন, তাহলে একজন কর্মীকে বরখাস্ত করা বা একটা আপস শনাক্ত করা একদিনের জন্য access আটকায় না। **Access token ৫–১৫ মিনিট বাঁচা উচিত**, পেছনে একটা বাতিলযোগ্য refresh token সহ।

---

## ১৭.৩ OAuth 2.0 আর OpenID Connect 🟢

**যে গুরুত্বপূর্ণ পার্থক্যটা মানুষ ভুল করে:**

```
OAuth 2.0  = AUTHORIZATION।  "এই app আমার ক্যালেন্ডার পড়তে পারবে।"
OIDC       = AUTHENTICATION। "আমি এই।"  (OAuth 2.0-র উপরে একটা পাতলা স্তর)
```

Login-এর জন্য কাঁচা OAuth 2.0 ব্যবহার করা একটা পরিচিত anti-pattern — একটা access token *access* প্রমাণ করে, *পরিচয়* নয়। **OIDC `id_token` যোগ করে**, যেটাই পরিচয়ের দাবি। আপনি যদি "Sign in with X" বানান, আপনার OIDC লাগবে।

### চারটা ভূমিকা

```
RESOURCE OWNER        ব্যবহারকারী
CLIENT                আপনার application
AUTHORIZATION SERVER  token দেয় (Auth0, Keycloak, Entra ID, Cognito)
RESOURCE SERVER       আপনার API, যা token গ্রহণ করে
```

### PKCE সহ Authorization Code flow ⭐ (ব্যবহারকারীর login-এ এটাই একমাত্র ব্যবহার্য flow)

```
১. App তৈরি করে:  code_verifier = random(৬৪ byte)
                   code_challenge = BASE64URL(SHA256(code_verifier))

২. Browser → Auth Server:
   /authorize?response_type=code
             &client_id=...
             &redirect_uri=https://app.example.com/callback
             &scope=openid profile email
             &state=<এলোমেলো, anti-CSRF>
             &code_challenge=<challenge>&code_challenge_method=S256

৩. ব্যবহারকারী authenticate করেন আর সম্মতি দেন

৪. Auth Server → Browser → App:  /callback?code=<auth_code>&state=<একই>
                                  ← app-কে অবশ্যই `state` মেলে কিনা যাচাই করতে হবে

৫. App → Auth Server (পেছনের channel, server-থেকে-server):
   POST /token  { code, code_verifier, client_id, redirect_uri }

৬. Auth Server যাচাই করে SHA256(code_verifier) == জমানো code_challenge
   → ফেরত দেয় { access_token, id_token, refresh_token }
```

**PKCE কেন:** একজন আক্রমণকারী যদি authorisation code ধরেও ফেলে (একই URI scheme নিবন্ধন করা একটা দূষিত app, একটা ফাঁস হওয়া redirect, browser-এর ইতিহাস), তবু তারা সেটা বিনিময় করতে পারবে না — তাদের কাছে `code_verifier` নেই। **PKCE এখন সব client-এর জন্য সুপারিশকৃত, server-side confidential client সহ**, শুধু mobile নয়।

### Flow: কোনটা ব্যবহার করবেন আর কোনটা এড়াবেন

| Flow | ব্যবহার? |
|------|------|
| **Authorization Code + PKCE** | ✅ **ব্যবহারকারী-মুখী সবকিছু** — web, SPA, mobile, desktop |
| **Client Credentials** | ✅ Machine-থেকে-machine (কোনো ব্যবহারকারী জড়িত নয়) |
| **Device Code** | ✅ TV, CLI, input-সীমিত device |
| **Refresh Token** | ✅ ঘোরানো আর পুনর্ব্যবহার শনাক্তকরণ সহ |
| **Implicit** | ❌ **বাতিল** — URL-এর fragment-এ token, সব জায়গায় ফাঁস |
| **Resource Owner Password Credentials** | ❌ **বাতিল** — app password সামলায়, যা পুরো উদ্দেশ্যটাই নষ্ট করে |

### JWT — ঠিকভাবে যাচাই করুন

```python
claims = jwt.decode(
    token,
    key=public_key_from_jwks,              # issuer-এর JWKS endpoint থেকে আনা, cache করা
    algorithms=["RS256"],                  # ⭐ ALGORITHM PIN করুন — কখনো header বিশ্বাস করবেন না
    audience="https://api.example.com",    # ⭐ এই token কি আমাদের জন্য?
    issuer="https://auth.example.com/",    # ⭐ আমরা কি এটা দিয়েছি (বা আমাদের বিশ্বস্ত IdP)?
    options={"require": ["exp", "iat", "sub", "aud", "iss"]},
)
```

**যে JWT দুর্বলতাগুলো আপনাকে জানতেই হবে:**

১. **`alg: none`** — একটা unsigned token বৈধ হিসেবে গৃহীত। **সবসময় অনুমোদিত algorithm স্পষ্টভাবে pin করুন।**
২. **Algorithm-এর বিভ্রান্তি (RS256 → HS256)** — আক্রমণকারী *public* key-টাকে একটা HMAC secret হিসেবে ব্যবহার করে sign করে। Pin করা এটা ঠেকায়।
৩. **`aud` যাচাই অনুপস্থিত** — অন্য একটা service-এর জন্য দেওয়া একটা token আপনারটা গ্রহণ করে
৪. **`exp` যাচাই অনুপস্থিত** — মেয়াদোত্তীর্ণ token এখনো কাজ করে
৫. **Signature যাচাই না করে claim বিশ্বাস করা** — decode করা যাচাই করা নয়
৬. **Payload-এ secret** — একটা JWT **base64, encrypted নয়।** যে কেউ এটা পড়তে পারে। এতে সংবেদনশীল কিছু রাখবেন না।
৭. **বাতিল করার উপায় ছাড়া লম্বা মেয়াদ** — §১৭.২ দেখুন

### Refresh token ঘোরানো

```
Client refresh token RT1 ব্যবহার করে → server নতুন access token + RT2 দেয়, RT1 বাতিল করে
RT1 যদি কখনো আবার দেখানো হয় → এটা চুরি হয়েছিল → পুরো TOKEN-পরিবারটা বাতিল করুন
```

এটা চুরি না-হওয়ার আশা করার বদলে চুরি শনাক্ত করে, আর implement করা সোজা। Refresh token hash করে রাখুন, একটা client/device-এর সাথে বাঁধুন, আর একটা পরম সর্বোচ্চ আয়ু বসান।

---

## ১৭.৪ Authorization-এর মডেল 🟢

### RBAC — Role-Based Access Control

```
User → Role → Permission

alice → [reviewer]      → [session:read, session:approve, session:reject]
bob   → [tenant_admin]  → [session:*, user:*, billing:read]
```

✅ সহজ, পরিচিত, audit-যোগ্য, auditor-দের ব্যাখ্যা করা সহজ
❌ **Role-এর বিস্ফোরণ** — প্রেক্ষাপট লাগলেই `reviewer_eu_readonly_tier2` আসে। শুধু RBAC "শুধু নিজের tenant-এর data" প্রকাশ করতে পারে না।

### ABAC — Attribute-Based Access Control

**Subject**, **resource**, **action** আর **environment**-এর বৈশিষ্ট্য থেকে সিদ্ধান্ত।

```python
def can_approve(user: User, session: Session, ctx: Context) -> bool:
    return (
        user.has_permission("session:approve")
        and session.tenant_id == user.tenant_id        # tenant-এর বিচ্ছিন্নতা
        and session.status == SessionStatus.PENDING_REVIEW
        and session.created_by != user.id              # দায়িত্বের বিভাজন
        and ctx.ip_in_allowed_range(user.tenant.ip_allowlist)
        and ctx.time_within_business_hours(user.tenant.timezone)
    )
```

✅ প্রকাশক্ষম, সূক্ষ্ম, কোনো role-বিস্ফোরণ নেই
❌ ভাবা আর audit করা কঠিন ("X-এ কে ঢুকতে পারে?" — এতে একটা lookup নয়, মূল্যায়ন লাগে)

### ReBAC — Relationship-Based Access Control ⭐

Permission একটা graph-এর সম্পর্ক থেকে আসে (Google Zanzibar-এর মডেল; OpenFGA, SpiceDB, Permify)।

```
user:alice      হলো  owner        of  document:budget2026
group:finance   হলো  viewer       of  document:budget2026
user:bob        হলো  member       of  group:finance
                                     → bob budget2026 দেখতে পারে (উদ্ভূত)
```

Google Docs, GitHub আর Notion-ধাঁচের ভাগাভাগি এভাবেই কাজ করে। Permission যখন শ্রেণিবিন্যাসের মধ্য দিয়ে উত্তরাধিকারসূত্রে আসে (folder → document, org → team → repo), তখন ReBAC RBAC বা ABAC — দুটোর চেয়েই নাটকীয়ভাবে পরিচ্ছন্ন।

### ব্যবহারিক সুপারিশ

> **বেশিরভাগ বাস্তব সিস্টেম মোটা দাগের ক্ষমতার জন্য RBAC + প্রেক্ষাপটের জন্য ABAC ব্যবহার করে।**
> "এই ব্যবহারকারীর কি `session:approve` permission আছে?" (RBAC) **আর** "এই session কি তাঁর tenant-এ?" (ABAC)।

### Authorization-এর architecture 🟢

```
❌ Controller জুড়ে ছড়ানো authorization-এর logic
   → অসঙ্গত, test-অযোগ্য, আর একটা ভুলে যাওয়া যাচাই একটা breach

✅ কেন্দ্রীভূত policy, প্রতি request-এ একটামাত্র বিন্দুতে বলবৎ
```

```python
# একটা policy decision point — একটা জায়গা, testable, audit-যোগ্য
class AuthorizationService:
    async def authorize(self, principal: Principal, action: str,
                        resource: Resource) -> Decision:
        if not principal.has_permission(action):
            return Decision.deny("missing_permission", action)
        if resource.tenant_id != principal.tenant_id:
            # সম্ভাব্য আক্রমণ হিসেবে log করুন, কিন্তু "not found"-এর মতোই error ফেরত দিন
            audit.log_suspicious("cross_tenant_attempt", principal, resource)
            return Decision.deny("not_found")
        for rule in self._rules_for(action):
            if not await rule.evaluate(principal, resource):
                return Decision.deny(rule.name)
        return Decision.allow()
```

**যে দুটো নিয়ম সবচেয়ে সাধারণ breach ঠেকায়:**

**১. Tenant-এর বিচ্ছিন্নতা data স্তরে বলবৎ করতে হবে, শুধু application কোডে নয়।**

```sql
-- PostgreSQL-এর Row-Level Security: একটা ভুলে যাওয়া WHERE clause-ও data ফাঁস করতে পারে না
ALTER TABLE verification_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON verification_sessions
    USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

এটা বিশুদ্ধতম রূপে স্তরে স্তরে প্রতিরক্ষা: একটা SQL injection বা একটা অনুপস্থিত filter তবু tenant পেরোতে পারে না।

**২. Deny দেখতে "not found"-এর মতো হতে হবে।** যে resource আছে তার জন্য ৪০৩ আর যেটা নেই তার জন্য ৪০৪ ফেরত দিলে অন্য tenant-এর data-র অস্তিত্ব ফাঁস হয়। **দুটোতেই ৪০৪ ফেরত দিন।**

### IDOR — সবচেয়ে সাধারণ web দুর্বলতা

```python
# ❌ Insecure Direct Object Reference — আসল pentest-এ ১ নম্বর আবিষ্কার
@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    return await db.get_session(session_id)     # যে কোনো id চলে। যে কোনো tenant। যে কোনো user।

# ✅ সবসময় authenticated principal দিয়ে সীমিত করুন
@app.get("/sessions/{session_id}")
async def get_session(session_id: str, principal: Principal = Depends(current_principal)):
    session = await db.get_session(session_id, tenant_id=principal.tenant_id)
    if session is None:
        raise HTTPException(404)                # নেই না নিষিদ্ধ — দুটোতেই একই response
    return session
```

> **এটার জন্য ইচ্ছাকৃতভাবে test করুন:** আপনার integration test-এ tenant A-কে দিয়ে tenant B-র প্রতিটা resource ID দিয়ে পড়ার চেষ্টা করান আর ৪০৪ assert করুন। এটা automate করুন। এই একটা test-শ্রেণিই multi-tenant SaaS-এর সবচেয়ে বেশি প্রভাবের bug-শ্রেণিটা ধরে।

---

# পর্ব ২ — Application security

## ১৭.৫ OWASP Top 10 🟢

আসলে কী ভুল হয় তার প্রামাণিক তালিকা। দশটাই জানুন; প্রতিটার প্রতিরক্ষা জানুন।

### A01 — Broken Access Control (১ নম্বর শ্রেণি)

§১৭.৪-এ আলোচিত। IDOR, অনুপস্থিত function-স্তরের যাচাই, শুধু client-side বলবৎকরণ, path traversal, CORS-এর ভুল configuration।

**প্রতিরক্ষা:** default-এ deny; কেন্দ্রীভূত policy; প্রতিটা query principal দিয়ে সীমিত; database-এ RLS; স্বয়ংক্রিয় cross-tenant test।

### A02 — Cryptographic Failure

```
❌ HTTP-তে সংবেদনশীল data
❌ দুর্বল বা ঘরে-বানানো crypto (ECB mode, static IV, নিজের "encryption")
❌ Hard-code করা key
❌ বিশ্রামে unencrypted data
```

**প্রতিরক্ষা:** ভেতরে সহ সব জায়গায় TLS 1.3; AES-256-GCM (authenticated encryption) বা একটা উঁচু-স্তরের library (libsodium, `cryptography.fernet`); key একটা KMS/HSM-এ, ঘোরানো; data শ্রেণিবদ্ধ করুন আর শ্রেণি অনুযায়ী encrypt করুন।

### A03 — Injection

```python
# ❌ SQL injection
cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")
#   email = "' OR '1'='1' --"   → সবাইকে ফেরত দেয়

# ✅ Parameterised query — database কখনো data আর code গুলিয়ে ফেলে না
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
```

```python
# ❌ Command injection
os.system(f"ffmpeg -i {filename} out.mp4")
#   filename = "x.mp4; rm -rf /"

# ✅ Argument-এর তালিকা, কখনো একটা shell নয়
subprocess.run(["ffmpeg", "-i", filename, "out.mp4"], shell=False, check=True)
```

আরও: NoSQL injection (password হিসেবে `{"$ne": null}`), LDAP injection, template injection (SSTI), আর XML parser-এ XXE (বাইরের entity বন্ধ করুন)।

> **সর্বজনীন প্রতিরক্ষা: অবিশ্বস্ত input দিয়ে string জুড়ে কখনো একটা command, query বা template বানাবেন না।** Library যে parameterised কৌশল দেয় সেটা ব্যবহার করুন। গতিশীল identifier (table/কলামের নাম) parameterise করা যায় না — সেগুলো **whitelist** করুন।

### A04 — Insecure Design

যে শ্রেণিটা বিশেষভাবে একজন **আর্কিটেক্টের** দায়িত্ব: অনুপস্থিত rate limit, কোনো threat model নেই, business-logic-এর ত্রুটি (ঋণাত্মক পরিমাণ, দামের কারসাজি, redemption code-এ race condition), সীমাহীন সম্পদ ব্যবহার।

> কোনো পরিমাণ secure coding এমন একটা design ঠিক করে না যেটা একজন ব্যবহারকারীকে −৫টা জিনিস order করে refund পেতে দেয়।

### A05 — Security Misconfiguration

Default credential, production-এ বিস্তারিত error, অপ্রয়োজনীয় feature চালু, অনুপস্থিত security header, public ক্লাউড storage, directory listing।

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), camera=(), microphone=()
```

**CSP-ই XSS-এর বিরুদ্ধে একক সবচেয়ে কার্যকর প্রতিরক্ষা**, আর clickjacking-এর জন্য `frame-ancestors 'none'` পুরনো `X-Frame-Options` প্রতিস্থাপন করে।

### A06 — দুর্বল আর পুরনো Component

আপনার dependency-ই আপনার আক্রমণের পরিসর। Log4Shell, event-stream, আর xz-এর backdoor — সবই supply-chain-এর ঘটনা।

**প্রতিরক্ষা:** CI-তে SCA scan (Dependabot, Snyk, `pip-audit`); lockfile; **SBOM**, যাতে "আমরা কি প্রভাবিত?" — এর উত্তর মিনিটে দিতে পারেন; version pin করুন; container-এর base image scan করুন; dependency কমান (এটার জন্য কি সত্যিই একটা library লাগে?); সত্যিকারের রক্ষণাবেক্ষণ আছে এমন package-কে প্রাধান্য দিন।

### A07 — Identification ও Authentication-এর ব্যর্থতা

Credential stuffing, দুর্বল পুনরুদ্ধারের প্রবাহ, session fixation, অনুপস্থিত MFA। §১৭.২–১৭.৩-এ আলোচিত।

**আরও:** বিশেষাধিকার বদলালে (login, role পরিবর্তন) session ID আবার তৈরি করুন — নইলে session fixation কাজ করে।

### A08 — Software ও Data-র অখণ্ডতার ব্যর্থতা

Sign না করা artefact, অনিরাপদ CI/CD, **অনিরাপদ deserialisation**।

```python
# ❌ কখনো pickle/yaml.load/Java serialization দিয়ে অবিশ্বস্ত data deserialise করবেন না
data = pickle.loads(user_supplied_bytes)     # যথেচ্ছ কোড চালানো
# ✅
data = json.loads(user_supplied_bytes)       # শুধু data, কোনো কোড নয়
```

**প্রতিরক্ষা:** container image sign করুন (cosign) আর admission-এ যাচাই করুন; build pipeline-কে একটা production সিস্টেম হিসেবে রক্ষা করুন (এর কাছে production-এর credential আছে); dependency pin আর যাচাই করুন।

### A09 — Security Logging ও Monitoring-এর ব্যর্থতা

গড়ে একটা breach মাসের পর মাস অশনাক্ত থাকে। আপনি যদি শনাক্ত করতে না পারেন, তাহলে উপরের সবকিছুই নাটক।

**এই ঘটনাগুলো সবসময় log করুন:** authentication-এর সাফল্য আর ব্যর্থতা, authorisation-এর প্রত্যাখ্যান, বিশেষাধিকারের পরিবর্তন, সংবেদনশীল data-তে প্রবেশ, configuration-এর পরিবর্তন, admin-এর কাজ, payment-এর ঘটনা।

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

**নিয়ম:** কখনো secret, token, password বা পূর্ণ PII log করবেন না; audit log **append-only আর আলাদাভাবে জমা** রাখুন (যে আক্রমণকারী ঢুকেছে সে যেন প্রমাণ মুছতে না পারে); আপনার compliance-এর সময়কাল পর্যন্ত রাখুন; শুধু একক ঘটনা নয়, **pattern-এ alert দিন**।

### A10 — Server-Side Request Forgery (SSRF)

```python
# ❌ Application ব্যবহারকারীর দেওয়া একটা URL আনে
requests.get(user_supplied_url)
#   http://169.254.169.254/latest/meta-data/iam/security-credentials/
#   → ক্লাউডের credential চুরি। Capital One এভাবেই ১০ কোটি record হারিয়েছিল।
```

**প্রতিরক্ষা:** গন্তব্য host allowlist করুন; DNS resolve করে **resolve হওয়া IP যাচাই করুন** private পরিসরের বিপরীতে (অধ্যায় ১৩) — আর DNS rebinding ঠেকাতে redirect-এর পরে আবার যাচাই করুন; redirect বন্ধ করুন; IMDSv2 বাধ্যতামূলক করুন (এতে একটা token লাগে আর সরল SSRF আটকায়); বাইরের call একটা egress proxy দিয়ে পাঠান যেটা allowlist বলবৎ করে।

---

## ১৭.৬ CSRF, XSS আর browser-এর নিরাপত্তা 🟢

### XSS — Cross-Site Scripting

```html
<!-- ❌ Reflected/stored XSS -->
<div>Welcome, {{ user_name|safe }}</div>       <!-- user_name = <script>steal()</script> -->

<!-- ✅ Default-এ escape করুন (আধুনিক framework স্বয়ংক্রিয়ভাবে করে) -->
<div>Welcome, {{ user_name }}</div>
```

**প্রতিরক্ষার স্তর, কার্যকারিতার ক্রমে:**
১. **প্রেক্ষাপট-সচেতন output encoding** — HTML body, attribute, JavaScript আর URL — প্রতিটা প্রেক্ষাপটে আলাদা escaping লাগে। আপনার framework-কে করতে দিন; কখনো বন্ধ করবেন না।
২. **CSP** — XSS থাকলেও browser ঢোকানো script চালাতে অস্বীকার করে
৩. **`HttpOnly` cookie** — JavaScript session cookie পড়তে পারে না, তাই XSS সেটা চুরি করতে পারে না
৪. একটা যাচাই করা library (DOMPurify) দিয়ে **সমৃদ্ধ HTML input sanitise করুন**, কখনো একটা regex দিয়ে নয়

### CSRF — Cross-Site Request Forgery

একজন আক্রমণকারীর সাইট ব্যবহারকারীর browser-কে দিয়ে আপনার সাইটে একটা authenticated request করায়।

**প্রতিরক্ষা:**
১. **`SameSite` cookie** — `Lax` এখন browser-এর default আর বেশিরভাগ CSRF আটকায়; সংবেদনশীল কাজে `Strict` ব্যবহার করুন
২. **Anti-CSRF token** — synchroniser token বা double-submit cookie
৩. State বদলানো request-এ **`Origin`/`Referer` যাচাই করুন**
৪. **State পরিবর্তনে কখনো GET ব্যবহার করবেন না** (একটা `<img>` tag একটা GET ঘটাতে পারে)

> **Token-ভিত্তিক API (Authorization header) মূলত CSRF-প্রতিরোধী**, কারণ browser স্বয়ংক্রিয়ভাবে header যোগ করে না। Cookie-ভিত্তিক session-এরই সুরক্ষা লাগে। আপনি কোনটা বানাচ্ছেন জানুন।

### Cookie-র flag

```
Set-Cookie: session=...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=3600
            ^^^^^^^^^^^^^^^^^^^^^ চারটাই গুরুত্বপূর্ণ
```

---

# পর্ব ৩ — Data আর infrastructure-এর নিরাপত্তা

## ১৭.৭ Encryption 🟢

### পথে

সব জায়গায় TLS 1.3, **ভেতরের service-থেকে-service traffic সহ** (৪ নম্বর ভ্রান্তি, অধ্যায় ০৫)। Service-এর পরিচয়ের জন্য mTLS, আদর্শভাবে স্বয়ংক্রিয় স্বল্পস্থায়ী certificate সহ একটা service mesh দিয়ে (অধ্যায় ১৫)।

### বিশ্রামে

| স্তর | কী থেকে রক্ষা করে | কী থেকে রক্ষা করে **না** |
|-------|-------------------------|----------------------------------|
| **Disk/volume encryption** | চুরি হওয়া শারীরিক disk | Database-এ প্রবেশ আছে এমন যা কিছু |
| **Database TDE** | চুরি হওয়া database ফাইল আর backup | একটা আপসকৃত application |
| **কলাম/field encryption** | DBA, backup, আংশিক breach | Key সহ একটা আপসকৃত application |
| **Application-স্তরের encryption** | App-এর নিচের প্রায় সবকিছু | একটা আপসকৃত application |

> **গুরুত্বপূর্ণ সততা:** "আমরা বিশ্রামে encrypt করি" প্রায়ই একটা compliance-এর টিক, যা প্রায় কোনো বাস্তব আক্রমণই থামায় না — আক্রমণকারীর কাছে যদি application বা database-এর credential থাকে, তাহলে transparent encryption তাদের কাছে অদৃশ্য। **সত্যিকারের সংবেদনশীল data-র field-স্তরের encryption, এমন key দিয়ে যা database-এর নাগালে নেই — এটাই সেই নিয়ন্ত্রণ যা আসলে কাজে লাগে।**

```python
# Envelope encryption — প্রচলিত pattern
# ১. প্রতি record বা প্রতি tenant-এ একটা এলোমেলো data key (DEK) তৈরি করুন
# ২. DEK দিয়ে data encrypt করুন
# ৩. KMS-এর একটা master key (KEK) দিয়ে DEK encrypt করুন
# ৪. Ciphertext + encrypted DEK একসাথে জমা রাখুন
#
# → Key ঘোরানো মানে DEK আবার encrypt করা, terabyte data নয়
# → প্রতি-ব্যক্তিতে DEK CRYPTO-SHREDDING সম্ভব করে: key মুছুন = data শেষ
```

Immutable সিস্টেমে GDPR-এর মুছে ফেলার ব্যবহারিক উত্তর **crypto-shredding** — event store, append-only log, backup (অধ্যায় ০২, ১২)।

### Key ব্যবস্থাপনা

```
✅ Key একটা KMS/HSM-এ, কখনো কোডে, config-এ, বা data-র একই database-এ নয়
✅ প্রতি পরিবেশে আলাদা key, threat model যুক্তি দিলে প্রতি tenant-এও
✅ একটা নির্ধারিত সময়সূচি সহ স্বয়ংক্রিয় ঘোরানো
✅ Key-তে প্রবেশ log আর alert করা
✅ একটা নথিভুক্ত, পরীক্ষিত key-পুনরুদ্ধার প্রক্রিয়া — একটা key হারানো মানে data হারানো
❌ সবকিছুর জন্য একটা key, চিরকাল
```

### Data-র শ্রেণিবিভাগই সবকিছু চালায়

| শ্রেণি | উদাহরণ | নিয়ন্ত্রণ |
|-------|----------|----------|
| **Public** | Marketing-এর বিষয়বস্তু | কিছুই না |
| **Internal** | Metric, architecture-এর নথি | Access control |
| **Confidential** | Customer-এর record, চুক্তি | + encryption, audit logging |
| **Restricted** | Payment-এর data, biometrics, স্বাস্থ্য, সরকারি ID | + field encryption, কড়া least privilege, retention-এর সীমা, DLP, সম্ভাব্য নিয়ন্ত্রক পরিসর |

> **আগে শ্রেণিবদ্ধ করুন।** যে data আপনি শ্রেণিবদ্ধ করেননি তাতে আপনি আনুপাতিক নিয়ন্ত্রণ প্রয়োগ করতে পারবেন না। একটা KYC/liveness product-এর জন্য মুখের ছবি আর document স্ক্যান বেশিরভাগ এখতিয়ারে **restricted biometric data** — নির্দিষ্ট আইনি দাবি সহ (GDPR-এর ধারা ৯, Illinois BIPA, ইত্যাদি)। ওই শ্রেণিবিভাগ একটা architecture-এর constraint, কোনো নীতির পাদটীকা নয়: এটা ঠিক করে data কোথায় রাখা যাবে, কে দেখতে পারবে, কতদিন রাখতে পারবেন, আর আপনাকে কী প্রমাণ করতে পারতে হবে।

---

## ১৭.৮ Zero Trust 🟡

**পুরনো মডেল ("দুর্গ আর পরিখা"):** একটা শক্ত পরিধি; ভেতরের সবকিছু বিশ্বস্ত। এটা fail করে কারণ পরিধিটাই গলে গেছে (ক্লাউড, দূর থেকে কাজ, SaaS, mobile) আর কারণ একটা আপসকৃত host আক্রমণকারীকে পুরো ভেতরটা দেয়।

**Zero Trust:** *"কখনো বিশ্বাস নয়, সবসময় যাচাই।"* কোনো বিশ্বস্ত নেটওয়ার্ক নেই।

### নীতিগুলো

১. **স্পষ্টভাবে যাচাই করুন** — পরিচয়, device, অবস্থান আর আচরণের ভিত্তিতে প্রতিটা request authenticate আর authorise করুন
২. **Least privilege access** — just-in-time আর just-enough, সময়-সীমিত উন্নয়ন সহ
৩. **Breach ধরে নিন** — ভাগ করুন, সব জায়গায় encrypt করুন, অনবরত নজর রাখুন, blast radius সীমিত করুন

### বাস্তবে এর মানে

| পুরনো | Zero Trust |
|-----|-----------|
| নেটওয়ার্কে VPN, তারপর সবকিছুতে পৌঁছানো যায় | প্রতি application-এ access, প্রতি request-এ authorisation |
| Service একে অপরকে বিশ্বাস করে কারণ তারা একটা subnet ভাগ করে | **Service পরিচয় সহ mTLS; প্রতিটা call authorised** |
| Static admin account | Just-in-time উন্নয়ন, সময়-সীমিত, অনুমোদিত, লিপিবদ্ধ |
| প্রান্তে একটা firewall | Micro-segmentation; workload-এর মধ্যে default-deny |
| Device বিশ্বস্ত কারণ এটা অফিসের নেটওয়ার্কে | Device-এর অবস্থা access-সিদ্ধান্তের অংশ |

**একজন আর্কিটেক্টের জন্য ব্যবহারিক চেকলিস্ট:**
- [ ] প্রতিটা service-থেকে-service call authenticated (mTLS বা signed token) — শুধু "এটা আমাদের VPC থেকে এসেছে" নয়
- [ ] প্রতিটা service-এর নিজের পরিচয় আর নিজের ন্যূনতম permission আছে
- [ ] Network policy default-deny (অধ্যায় ১৩/১৫)
- [ ] কোনো shared service account নেই; কোনো দীর্ঘস্থায়ী credential নেই
- [ ] মানুষের production access সময়-সীমিত, অনুমোদিত আর লিপিবদ্ধ

---

## ১৭.৯ Threat modelling 🟢

**একজন আর্কিটেক্টের সময়ের বিনিময়ে সর্বোচ্চ প্রতিদান দেওয়া একমাত্র নিরাপত্তা-কাজ।** দুই ঘণ্টা, একটা whiteboard, আর একটা design diagram।

### STRIDE

| হুমকি | প্রশ্ন | উপশম |
|--------|----------|-----------|
| **S**poofing | কেউ কি অন্য কারও ভান করতে পারে? | শক্তিশালী AuthN, MFA, mTLS |
| **T**ampering | Data কি পথে বা বিশ্রামে বদলানো যায়? | TLS, signature, অখণ্ডতা যাচাই, audit |
| **R**epudiation | কেউ কি কিছু করার কথা অস্বীকার করতে পারে? | Append-only audit log, signed কাজ |
| **I**nformation disclosure | Data কি ফাঁস হতে পারে? | Encryption, access control, ন্যূনতমীকরণ |
| **D**enial of service | এটাকে কি অনুপলব্ধ করা যায়? | Rate limiting, quota, autoscaling, load shedding |
| **E**levation of privilege | কেউ কি বেশি অধিকার পেতে পারে? | Least privilege, input যাচাই, segmentation |

### প্রক্রিয়া

```
১. সিস্টেমটা আঁকুন: component, data store, data-র প্রবাহ, আর TRUST BOUNDARY
   (একটা trust boundary হলো যেখানেই data আলাদা বিশ্বাসের স্তরের মধ্যে পেরোয়:
    ইন্টারনেট → আপনার প্রান্ত, আপনার app → একটা ভেন্ডর, tenant A → tenant B)

২. প্রতিটা ELEMENT আর প্রতিটা FLOW-র জন্য STRIDE ধরে হাঁটুন।
   "কেউ কি এটার ভান করতে পারে? এটা বদলাতে পারে? ..."

৩. প্রতিটা আবিষ্কারকে রেট দিন (সম্ভাবনা × প্রভাব)।

৪. প্রতিটার জন্য সিদ্ধান্ত নিন: উপশম / মেনে নেওয়া / স্থানান্তর / দূর করা।

৫. এটা লিখে রাখুন আর architecture বদলালে আবার রিভিউ করুন।
```

### কাজ করা অংশ — liveness verification সিস্টেম

| Element | হুমকি | ঝুঁকি | উপশম |
|---------|--------|------|-----------|
| ভিডিও upload (presigned URL) | **T**ampering — ব্যবহারকারী আগে রেকর্ড করা ভিডিও upload করেন | বেশি | Server-এর দেওয়া nonce সহ challenge; challenge-এর উত্তর মেলে কিনা যাচাই; capture-এর metadata যাচাই; anti-spoof model |
| Presigned URL | **I**nformation disclosure — URL ভাগ বা ফাঁস | মাঝারি | ছোট মেয়াদ (১৫ মিনিট), যেখানে সম্ভব একবার-ব্যবহার্য, একটা object key-তে সীমিত |
| Verification-এর ফলাফল | **T**ampering — client-side-এ ফলাফলের কারসাজি | **সংকটপূর্ণ** | সিদ্ধান্ত শুধু server-এ; ফলাফল কখনো client থেকে বিশ্বাস করা হয় না; ফলাফল signed |
| বিশ্রামে মুখের ছবি | **I**nformation disclosure — breach-এ biometrics প্রকাশ | **সংকটপূর্ণ** | প্রতি-tenant key সহ field-স্তরের encryption; ৯০ দিন retention; access log আর alert করা; restricted শ্রেণিবিভাগ |
| ভেন্ডরের API call | **S**poofing — একটা আপসকৃত ভেন্ডর মিথ্যা ফলাফল দেয় | বেশি | ভেন্ডরের সাথে mTLS; response-এর গঠন আর signature যাচাই; উচ্চ-ঝুঁকির ক্ষেত্রে দ্বিতীয় ভেন্ডর |
| Tenant-এর data | **E**levation — tenant A tenant B-র session পড়ে | **সংকটপূর্ণ** | একটামাত্র বলবৎকরণ বিন্দুতে policy + Postgres RLS + স্বয়ংক্রিয় cross-tenant test |
| Admin console | **E**levation — আপসকৃত admin account | বেশি | MFA বাধ্যতামূলক, IP allowlist, just-in-time উন্নয়ন, সব কাজ audit করা |
| API | **D**enial of service — একটা tenant GPU-র ক্ষমতা শেষ করে দেয় | মাঝারি | প্রতি-tenant rate limit আর quota; queue-ভিত্তিক load levelling; প্রতি-tenant concurrency-র সীমা |

> খেয়াল করুন কতগুলো উপশম **architecture-গত** — সিদ্ধান্তটা কোথায় নেওয়া হয়, data কোথায় থাকে, কোন সীমানা বিচ্ছিন্নতা বলবৎ করে। এই কারণেই threat modelling আর্কিটেক্টের কাজ আর design-এর সময়ের কাজ, পরের নয়।

---

## ১৭.১০ Compliance একটা architecture-এর constraint হিসেবে 🟡

| ব্যবস্থা | কার জন্য প্রযোজ্য | Architecture-গত ফলাফল |
|--------|-----------|---------------------------|
| **GDPR** | EU-র বাসিন্দাদের ব্যক্তিগত data | আইনি ভিত্তি, data ন্যূনতমীকরণ, **মুছে ফেলার অধিকার**, বহনযোগ্যতা, ৭২ ঘণ্টায় breach-এর নোটিশ, residency, উচ্চ-ঝুঁকির প্রক্রিয়ায় DPIA (biometrics এতে পড়ে) |
| **PCI-DSS** | Card-এর data | Network segmentation, CVV জমা রাখা নিষেধ, key ব্যবস্থাপনা, ত্রৈমাসিক scan। **পরিসর কমানোই পুরো খেলা** — একটা payment প্রোভাইডার ব্যবহার করুন আর card-এর data কখনো ছোঁবেন না। |
| **HIPAA** | মার্কিন স্বাস্থ্য-data | Encryption, audit, ভেন্ডরদের সাথে BAA, ন্যূনতম প্রয়োজনীয় |
| **SOC 2** | B2B SaaS-এর আস্থা | পরিবর্তন ব্যবস্থাপনা, access রিভিউ, monitoring, ভেন্ডর ব্যবস্থাপনা — বেশিরভাগটাই *প্রক্রিয়ার প্রমাণ* |
| **BIPA / biometric আইন** | Biometric শনাক্তকারী | **স্পষ্ট লিখিত সম্মতি, প্রকাশিত retention সময়সূচি, মুছে ফেলার সময়সীমা, বিক্রি নিষেধ।** প্রতি লঙ্ঘনে আইনি ক্ষতিপূরণ — একটা liveness product-এর জন্য এটা একটা সত্যিকারের বাণিজ্যিক ঝুঁকি। |

**যে তিনটা architecture-গত পদক্ষেপ compliance-কে সামলানোর যোগ্য করে:**

১. **পরিসর কমান।** Card-এর data আপনার সিস্টেমে না ঢোকা PCI-র বেশিরভাগটাই সরিয়ে দেয়। PII একটা service-এ tokenise করা বাকি চল্লিশটা থেকে সেটা সরিয়ে দেয়।
২. **নিয়ন্ত্রিত data বিচ্ছিন্ন করুন** শক্ত নিয়ন্ত্রণ সহ অল্প কয়েকটা component-এ, সব জায়গায় ছড়ানোর বদলে।
৩. **প্রমাণটা ভেতরেই বানান।** Audit log, access রিভিউ আর retention automation *feature* হওয়া উচিত, একটা audit-এর আগে হুড়োহুড়ি নয়।

> **আগেভাগে জিজ্ঞেস করুন: "আমাদের সিস্টেমের সবচেয়ে ছোট কোন অংশটা পরিসরে থাকতেই হবে?"** এই প্রশ্নটা অন্য যে কোনো প্রশ্নের চেয়ে বেশি compliance-এর টাকা বাঁচায়।

---

## ১৭.১১ সাধারণ ভুল

১. **Controller জুড়ে ছড়ানো authorization যাচাই** — একটা বাদ পড়া যাচাই একটা breach
২. **IDOR** — authenticated principal দিয়ে query সীমিত না করা। সবচেয়ে সাধারণ বাস্তব দুর্বলতা।
৩. অন্য tenant-এর resource-এর **অস্তিত্ব ফাঁস করা ৪০৩ বনাম ৪০৪**
৪. **বাতিল করার পথ ছাড়া দীর্ঘস্থায়ী JWT**
৫. **`aud`, `iss`, `exp` যাচাই না করা, বা `alg` pin না করা**
৬. **git, image, বা log-এ secret** — একবার push হলে স্থায়ী
৭. **SQL, shell command, বা template-এ string জোড়া লাগানো**
৮. **ভেতরের নেটওয়ার্ক বিশ্বাস করা** — unencrypted service-থেকে-service traffic
৯. **শুধু client-side যাচাই বা authorisation** — তুচ্ছভাবে এড়ানো যায়
১০. **ব্যবহারকারীর দেওয়া URL server-এ আনা** (SSRF) — ক্লাউডের metadata endpoint ঠিক ওখানেই আছে
১১. **Authentication endpoint-এ কোনো rate limiting নেই** — পুরো গতিতে credential stuffing
১২. **একটা টিক হিসেবে "বিশ্রামে encrypted"**, যা কোনো বাস্তব আক্রমণ থামায় না
১৩. **কোনো audit log নেই, বা এমন একটা যা আক্রমণকারী মুছে দিতে পারে**
১৪. **শেষে নিরাপত্তা রিভিউ করা** — যখন পরিবর্তন সবচেয়ে ব্যয়বহুল
১৫. **কোনো স্বয়ংক্রিয় cross-tenant বিচ্ছিন্নতার test নেই**

---

## ১৭.১২ আর্কিটেক্টের চেকলিস্ট

**Identity**
- [ ] Argon2id (বা bcrypt) password hashing; ফাঁস-হওয়া-password যাচাই; জোর করে বদলানো নয়
- [ ] MFA উপলব্ধ আর admin/বিশেষাধিকারপ্রাপ্ত role-এ বাধ্যতামূলক; passkey সাপোর্ট করা
- [ ] Authorization Code + PKCE; implicit আর password grant বন্ধ
- [ ] Access token ৫–১৫ মিনিট; refresh token পুনর্ব্যবহার শনাক্তকরণ সহ ঘোরানো
- [ ] JWT যাচাইয়ে `alg` pin করা আর `aud`, `iss`, `exp` যাচাই করা
- [ ] বিশেষাধিকার বদলালে session ID আবার তৈরি

**Authorization**
- [ ] একটামাত্র, কেন্দ্রীভূত policy বলবৎকরণ বিন্দু — ছড়ানো যাচাই নয়
- [ ] প্রতিটা query authenticated principal দিয়ে সীমিত
- [ ] Tenant-এর বিচ্ছিন্নতা application-এর পাশাপাশি data স্তরেও (RLS) বলবৎ
- [ ] অন্য tenant-এর resource-এ deny ৪০৪ ফেরত দেয়, ৪০৩ নয়
- [ ] CI-তে স্বয়ংক্রিয় cross-tenant access test

**Application**
- [ ] সব জায়গায় parameterised query আর argument-তালিকা সহ subprocess call
- [ ] Default-এ output encoding চালু; CSP configure আর পরীক্ষিত
- [ ] সব cookie-তে `HttpOnly`, `Secure`, `SameSite`
- [ ] Auth, password reset, আর ব্যয়বহুল endpoint-এ rate limiting
- [ ] কোনো অবিশ্বস্ত deserialisation নেই
- [ ] SSRF সুরক্ষা: allowlist, resolve-হওয়া-IP যাচাই, IMDSv2, কোনো redirect নয়

**Data**
- [ ] Data শ্রেণিবদ্ধ; নিয়ন্ত্রণ শ্রেণিবিভাগের সাথে আনুপাতিক
- [ ] ভেতরে সহ সব জায়গায় TLS 1.3; service-এর মধ্যে mTLS
- [ ] Restricted data-র জন্য field-স্তরের encryption; key KMS-এ, ঘোরানো
- [ ] Immutable store-এ মুছে ফেলার জন্য crypto-shredding-এর কৌশল
- [ ] Retention policy স্বয়ংক্রিয়; মুছে ফেলা যাচাইযোগ্য

**Operations**
- [ ] Threat model আছে আর উল্লেখযোগ্য architecture পরিবর্তনে রিভিউ হয়
- [ ] Audit log: append-only, আলাদাভাবে জমা, সংরক্ষিত, pattern-এ alert
- [ ] CI-তে dependency আর container scan; SBOM তৈরি
- [ ] Artefact sign করা আর deployment-এ যাচাই করা
- [ ] কোথাও কোনো দীর্ঘস্থায়ী credential নেই; workload identity ব্যবহৃত
- [ ] Incident response-এর পরিকল্পনা লেখা, একজন নামযুক্ত মালিক আর একটা অনুশীলিত মহড়া সহ
- [ ] নিয়ন্ত্রিত data সামলায় এমন যা কিছুর জন্য penetration test নির্ধারিত

---

## ১৭.১৩ নিজেকে যাচাই

১. AuthN, AuthZ, Audit — প্রতিটার সংজ্ঞা দিন আর তৃতীয়টা বাদ দিলে কী হয় বলুন।
২. Password-এর জন্য SHA-256 ভুল কেন? আপনার কী ব্যবহার করা উচিত আর কেন?
৩. কোন আধুনিক password নিয়মগুলো প্রচলিত পরামর্শ উল্টে দেয়, আর কেন?
৪. OAuth 2.0 বনাম OIDC — পার্থক্য কী আর login-এ আপনি কোনটা ব্যবহার করবেন?
৫. PKCE আর এটা ঠিক যে আক্রমণটা ঠেকায় সেটা ব্যাখ্যা করুন।
৬. JWT যাচাই ভুল হওয়ার ছয়টা উপায় বলুন।
৭. দীর্ঘস্থায়ী JWT কেন একটা সমস্যা, আর প্রচলিত সমাধান কী?
৮. RBAC বনাম ABAC বনাম ReBAC — প্রতিটা যেখানে সঠিক মডেল এমন একটা করে পরিস্থিতি দিন।
৯. IDOR কী? দুর্বল আর ঠিক করা কোড লিখুন।
১০. একটা নিষিদ্ধ resource-এ ৪০৩-এর বদলে ৪০৪ ফেরত দেওয়া উচিত কেন?
১১. Multi-tenancy-তে Postgres-এর RLS কীভাবে স্তরে স্তরে প্রতিরক্ষা দেয়?
১২. SSRF ব্যাখ্যা করুন আর Capital One-এর breach কীভাবে কাজ করেছিল বলুন। চারটা প্রতিরক্ষা দিন।
১৩. "বিশ্রামে encrypted" আসলে কী থেকে রক্ষা করে, আর কী থেকে করে না?
১৪. Crypto-shredding কী আর এটা কোন সমস্যা সমাধান করে?
১৫. একটা file upload নেওয়া API endpoint-এর উপর STRIDE হাঁটুন।
১৬. Compliance-কে সামলানোর যোগ্য করে এমন তিনটা architecture-গত পদক্ষেপের নাম বলুন।

---

## ১৭.১৪ মূল কথাগুলো

- **Security কাঠামোগত।** পরে জুড়ে দিলে এটা সবসময় আংশিক।
- **স্তরে স্তরে প্রতিরক্ষা: ধরে নিন প্রতিটা স্তর fail করে** আর জিজ্ঞেস করুন পরেরটায় আক্রমণকারীকে কী থামায়
- **Broken access control ১ নম্বর বাস্তব দুর্বলতা।** Policy কেন্দ্রীভূত করুন; প্রতিটা query principal দিয়ে সীমিত করুন; database-এও tenant-এর বিচ্ছিন্নতা বলবৎ করুন।
- **স্বল্পস্থায়ী access token + ঘোরানো refresh token**, কখনো দীর্ঘস্থায়ী অবাতিলযোগ্য JWT নয়
- প্রতিটা ব্যবহারকারী-মুখী প্রবাহে **Authorization Code + PKCE**; implicit আর password grant মৃত
- **SQL, shell command, বা template-এ কখনো অবিশ্বস্ত input জোড়া লাগাবেন না**
- **কখনো নেটওয়ার্ক বিশ্বাস করবেন না**, ভেতরের হোক বা না হোক — mTLS আর প্রতি-request authorisation
- **আগে data শ্রেণিবদ্ধ করুন**, তারপর আনুপাতিক নিয়ন্ত্রণ প্রয়োগ করুন। Biometrics আইনি ফলাফল সহ restricted data।
- **একজন আর্কিটেক্টের করা সর্বোচ্চ-প্রতিদানের নিরাপত্তা-কাজ threat modelling** — STRIDE আর একটা diagram নিয়ে দুই ঘণ্টা
- **Audit log append-only আর আলাদাভাবে জমা**, নইলে সেগুলো এমন প্রমাণ যা একজন আক্রমণকারী মুছতে পারে
- **Compliance-এর পরিসর কমান** — সবচেয়ে ছোট নিয়ন্ত্রিত পদচিহ্নই সবচেয়ে সস্তা

---

**পরবর্তী:** [অধ্যায় ১৮ — Observability](18-observability.md)

**ইংরেজি সংস্করণ:** [Chapter 17](../17-security-architecture.md) · **[সূচিপত্র](README.md)**
