# অধ্যায় ০৩ — Domain-Driven Design 🟢

> DDD কোনো framework নয়, ফোল্ডারের গঠন নয়, বা base class-এর সেট নয়।
> এটা একটা বিজনেসে **সঠিক সীমানা খুঁজে বের করার** উপায়, আর কোডকে সেই বিজনেসের প্রতি সৎ রাখার উপায়।

একজন আর্কিটেক্টের জন্য DDD-র কৌশলগত (strategic) অর্ধেকটা রণকৌশলগত (tactical) অর্ধেকের চেয়ে বেশি মূল্যবান। **বাস্তবে Bounded Context-ই আপনার service boundary।** এগুলো ঠিক করুন, তারপরের সবকিছু সহজ হয়ে যাবে। ভুল করুন, আর কোনো পরিমাণ Kubernetes আপনাকে বাঁচাতে পারবে না।

---

## ৩.০ DDD যে সমস্যার সমাধান করে

একটা বীমা কোম্পানির কথা ভাবুন। তিনটা বিভাগ দিনে বিশবার **"policy"** শব্দটা বলে:

- **Sales** — policy মানে একটা গৃহীত quote। এর একটা দাম আছে, একটা commission, একজন salesperson।
- **Claims** — policy মানে কী কী covered তার একটা তালিকা, limit আর exclusion সহ।
- **Finance** — policy মানে premium payment-এর একটা ধারা, ট্যাক্স আর হিসাবের কোড সহ।

একজন জুনিয়র ইঞ্জিনিয়ার তিনটাকেই সেবা দিতে **একটা `Policy` class** বানায়। তাতে ৮০টা field। Sales-এর `commissionRate` লাগে; Claims-এর লাগে না। Claims-এর `exclusions` লাগে; Finance-এর লাগে না। প্রতিটা পরিবর্তন দুটো বিভাগ ভাঙে। দুই বছর পর কেউ এটা ছুঁতে সাহস পায় না আর সবকিছু nullable।

**DDD-র উত্তর:** থামুন। এখানে **তিনটা আলাদা ধারণা** আছে, যারা কাকতালীয়ভাবে একটা শব্দ ভাগ করে। তিনটা model বানান, তিনটা **Bounded Context**-এ, আর সংজ্ঞায়িত করুন এরা একে অপরের মধ্যে কীভাবে অনুবাদ হয়।

> ওই একটামাত্র অন্তর্দৃষ্টি — *একই শব্দ একটা বিজনেসের আলাদা আলাদা অংশে আলাদা মানে বোঝায়, আর এটা ঠিকই আছে* — সব tactical pattern একসাথে মিলিয়ে যা দেয় তার চেয়ে বেশি মূল্যবান।

---

# পর্ব ১ — Strategic DDD 🟢

এটাই আর্কিটেক্টের অর্ধেক।

## ৩.১ Domain, Subdomain আর তিন ধরন

**Domain** = আপনার কোম্পানি যে পুরো business সমস্যার পরিসরে কাজ করে। একটা identity-verification কোম্পানির জন্য domain হলো "দূর থেকে প্রমাণ করা যে একজন মানুষ যা দাবি করছে সে তা-ই"।

**Subdomain** = ওই domain-এর ভেতরের একটা আলাদা এলাকা।

### তিন ধরনের subdomain — আর এই শ্রেণিবিভাগ কেন বাস্তব সিদ্ধান্ত চালায়

| ধরন | এটা কী | বিনিয়োগের কৌশল | উদাহরণ (KYC/liveness কোম্পানি) |
|------|-----------|--------------------|-----------------------------|
| **Core** | যা আপনাকে টাকা দেয়। আপনার প্রতিযোগিতামূলক সুবিধা। | **আপনার সেরা ইঞ্জিনিয়াররা। নিজে বানান। কখনো বাইরে দেবেন না।** | Liveness/anti-spoofing engine, risk-scoring model |
| **Supporting** | দরকারি, আপনার নিজস্ব, কিন্তু আপনাকে আলাদা করে না | সহজভাবে বানান, বা তত্ত্বাবধানে বাইরে দিন | Verification workflow orchestration, tenant onboarding, reviewer console |
| **Generic** | প্রতিটা কোম্পানির লাগে; সমাধান হয়ে গেছে | **কিনুন। সবসময়।** | Authentication, billing, email, storage, logging, PDF তৈরি |

**বাস্তবে এটা কেন এত গুরুত্বপূর্ণ:**

একটা টিম ৪ মাস খরচ করে SSO, MFA আর SCIM সহ একটা সুন্দর custom authentication সিস্টেম বানায় (generic subdomain — ২ সপ্তাহে Auth0 হওয়ার কথা ছিল), আর এদিকে anti-spoofing model (core) হলো একটা ভেন্ডরের score-এর উপর একটা threshold, যেটা একজন প্রতিদ্বন্দ্বী হারিয়ে দেয়। তারা ঠিক উল্টো বিনিয়োগ করল। এটা আশ্চর্যরকম সাধারণ।

> **যে কোনো প্রজেক্টে আর্কিটেক্টের প্রথম কৌশলগত কাজ:** subdomain গুলোর তালিকা করুন আর প্রতিটাকে শ্রেণিবদ্ধ করুন। তারপর দেখুন engineering-এর ঘণ্টাগুলো আসলে কোথায় যাচ্ছে। অমিলটা সাধারণত চমকে দেওয়ার মতো, আর এটা ঠিক করাই ওই কোয়ার্টারে আপনার করা সবচেয়ে মূল্যবান কাজ হবে।

```
DOMAIN: Remote Identity Verification
│
├── CORE ────────────► Liveness Detection Engine      (বানান, সেরা লোকেরা)
├── CORE ────────────► Fraud ও Risk Scoring           (বানান, সেরা লোকেরা)
│
├── SUPPORTING ─────► Verification Workflow          (বানান, সহজ রাখুন)
├── SUPPORTING ─────► Reviewer Console               (বানান, সহজ রাখুন)
├── SUPPORTING ─────► Tenant ও Quota Management      (বানান, সহজ রাখুন)
│
├── GENERIC ────────► Identity ও Access (SSO/MFA)    (কিনুন — Keycloak/Auth0/Entra)
├── GENERIC ────────► Billing ও Invoicing            (কিনুন — Stripe)
├── GENERIC ────────► Notification                   (কিনুন — SendGrid/Twilio)
└── GENERIC ────────► Object Storage                 (কিনুন — S3/Blob)
```

## ৩.২ Ubiquitous Language (সর্বব্যাপী ভাষা)

**সংজ্ঞা:** একটাই ভাগ করা শব্দভাণ্ডার, যেটা বিজনেসের লোকেরা *এবং* কোড — দুই জায়গাতেই ব্যবহৃত হয়, কোনো অনুবাদের স্তর ছাড়াই।

**পরীক্ষা:** আপনার কোড খুলুন। একজন domain বিশেষজ্ঞ কি method আর class-এর নাম পড়ে তাঁর বিজনেস চিনতে পারবেন?

```python
# ubiquitous language নয় — কারিগরি গোলমাল, business-এর অর্থ লুকানো
def update_record(self, rec_id: int, flag: int, val: float) -> None:
    row = self.db.get(rec_id)
    row.status_flag = flag
    row.score_val = val
    self.db.save(row)
```

```python
# Ubiquitous language — একজন compliance officer এটা পড়তে পারবেন
def record_verification_attempt(self, session_id: SessionId, signals: LivenessSignals) -> None:
    session = self._sessions.get(session_id)
    session.record_attempt(signals)
    if session.is_conclusively_spoofed():
        session.reject(reason=RejectionReason.PRESENTATION_ATTACK)
    self._sessions.save(session)
```

### ভাষাটা আসলে কীভাবে বানাবেন

১. **বিশেষজ্ঞদের কথা শুনুন আর তাঁদের বিশেষ্য-ক্রিয়াপদ লিখে রাখুন।** তাঁদের শব্দ "উন্নত" করবেন না। তাঁরা যদি বলেন *"we settle a claim"*, তাহলে method হবে `Settle()`, `Finalize()` বা `ProcessClosure()` নয়।
২. **অস্পষ্ট শব্দকে চ্যালেঞ্জ করুন।** কেউ "user" বললে জিজ্ঞেস করুন: "আপনি কি *applicant*, *reviewer*, *tenant admin*, নাকি *end customer* বোঝাচ্ছেন?" অস্পষ্ট শব্দ অনুপস্থিত ধারণা লুকায়।
৩. **একটা glossary বানান** আর কোডের পাশেই repo-তে রাখুন।
৪. বিজনেস আপনাকে শুধরে দিলে **নির্মমভাবে rename করুন**। Rename করা সস্তা; স্থায়ী একটা ভুল অনুবাদ নয়।
৫. **ভাষা প্রতিটা Bounded Context-এর নিজস্ব।** "Policy" Sales আর Claims-এ আলাদা মানে বোঝায়, আর সেটাই সঠিক — পুরো কোম্পানিতে একটা সংজ্ঞা চাপাবেন না। পুরো কথাটাই তো এটা।

**বাস্তব লাভ:** একটা মিটিংয়ে একজন domain বিশেষজ্ঞ বললেন *"একটা session-কে সর্বোচ্চ দুইবার re-challenge করা যাবে"*। আপনার কোডে যদি `session.re_challenge()` আর `MAX_RE_CHALLENGES = 2` থাকে, তাহলে এই requirement-এ ৫ মিনিট লাগবে। আপনার কোডে যদি `updateFlow(type=3, retryCount)` থাকে, তাহলে দুই দিন আর একটা ভুল বোঝাবুঝি লাগবে।

## ৩.৩ Bounded Context ⭐ (এই বইয়ের DDD অধ্যায়ের সবচেয়ে গুরুত্বপূর্ণ ধারণা)

**সংজ্ঞা:** একটা স্পষ্ট সীমানা, যার ভেতরে একটা নির্দিষ্ট model আর ভাষা সামঞ্জস্যপূর্ণভাবে প্রযোজ্য।

একটা Bounded Context-এর ভেতরে: প্রতিটা শব্দের একটা মানে, একটা model, একটা টিমের বোঝাপড়া।
Context-এর মধ্যে: আলাদা model, স্পষ্ট অনুবাদ দিয়ে যুক্ত।

```
┌──────────────────────────┐        ┌──────────────────────────┐
│   SALES CONTEXT          │        │   CLAIMS CONTEXT         │
│                          │        │                          │
│  Policy                  │        │  Policy                  │
│   - quotedPremium        │        │   - coverageLimits       │
│   - commissionRate       │◄──────►│   - exclusions           │
│   - salesAgent           │  অনুবাদ │   - deductible           │
│   - conversionDate       │        │   - claimHistory         │
│                          │        │                          │
│  Customer = একজন LEAD     │        │  Customer = একজন CLAIMANT │
└──────────────────────────┘        └──────────────────────────┘

একই শব্দ। আলাদা model। দুটোই সঠিক। স্পষ্টভাবে যুক্ত।
```

### Bounded Context-এর সীমানা কীভাবে খুঁজবেন — পাঁচটা ব্যবহারিক সংকেত

১. **ভাষা বদলে যায়।** একই শব্দ যখন আলাদা মানে বোঝাতে শুরু করে, তখন আপনি একটা সীমানা পেরিয়েছেন। এটাই সবচেয়ে শক্তিশালী সংকেত।
২. **আলাদা মানুষ চিন্তা করে।** Sales-এর কর্মী বনাম claims adjuster বনাম হিসাবরক্ষক। আলাদা stakeholder → সম্ভবত আলাদা context।
৩. **পরিবর্তনের হার আলাদা।** Pricing-এর নিয়ম মাসে মাসে বদলায়; document storage-এর নিয়ম বছরে একবার।
৪. **Consistency-র চাহিদা আলাদা।** Ledger-কে সাথে সাথে consistent হতে হবে। Recommendation feed এক মিনিট পুরনো হতে পারে।
৫. **Data-র মালিকানা।** আপনি যদি বলতে না পারেন "X-এর একমাত্র সত্যের উৎস এই context", তাহলে সীমানাটা ভুল।

### Bounded Context বনাম Microservice

এক জিনিস নয়, আর পার্থক্যটা গুরুত্বপূর্ণ:

- একটা **Bounded Context** হলো একটা *ধারণাগত/ভাষাগত* সীমানা
- একটা **Microservice** হলো একটা *deployment* সীমানা

**সম্পর্ক:** একটা bounded context = **এক বা একাধিক** service। কখনোই একটা context কয়েকটা service-এ ভাগ করবেন না (আপনি এমন একটা model ভাগ করবেন যেটা consistent থাকতেই হবে — স্বাগতম, distributed monolith)। আপনি *পারেন* কয়েকটা ছোট context একটা service-এ রাখতে, বিশেষত শুরুর দিকে।

> **নিয়ম: একটা bounded context-ই সবচেয়ে ছোট যুক্তিসঙ্গত service।** একটা bounded context-এর চেয়ে ছোট microservice প্রায় সবসময়ই একটা ভুল।

### Event Storming — একটা workshop-এ context খুঁজে বের করার উপায় 🟡

DDD-র সবচেয়ে কার্যকর ব্যবহারিক কৌশল। আপনার লাগবে একটা দেয়াল, sticky note, আর সঠিক মানুষজন (domain বিশেষজ্ঞ + ডেভেলপার), ২–৪ ঘণ্টার জন্য।

```
১. কমলা নোট: সবাই দেয়ালে DOMAIN EVENT লেখেন (অতীত কাল)।
   "OrderPlaced"  "PaymentCaptured"  "VerificationFailed"  "DocumentExpired"

২. সেগুলো সময়ের ক্রমে সাজান, বাঁ থেকে ডানে। তর্ক শুরু হবে। তর্কটাই মূল কথা —
   এটা লুকানো assumption আর অনুপস্থিত জ্ঞান প্রকাশ করে দেয়।

৩. নীল নোট: প্রতিটা event-এর পেছনে কোন COMMAND ছিল?   "PlaceOrder" → "OrderPlaced"
   হলুদ নোট: কে/কী command দিল?                       Actor / সিস্টেম / timer

৪. বেগুনি নোট: business RULE/POLICY।   "VerificationFailed ৩ বার হলে → BlockCustomer"

৫. গোলাপি নোট: বাইরের সিস্টেম।   "Stripe"  "Vendor Face API"  "Sanctions List"

৬. CLUSTER খুঁজুন — এমন event-এর দল যারা একসাথে যায় আর ভাষা ভাগ করে।
   প্রতিটা cluster-এর চারপাশে একটা রেখা টানুন। ওই রেখাগুলোই আপনার BOUNDED CONTEXT।
```

জাদুটা ২ নম্বর ধাপে: domain বিশেষজ্ঞদের সামনে event গুলো সময়ের ক্রমে সাজালে তিন ঘণ্টায় যত requirement বেরিয়ে আসে, তিন সপ্তাহের সাক্ষাৎকারেও তত আসে না।

## ৩.৪ Context Map

একটা Context Map আপনার **সব** bounded context আর প্রতি জোড়ার মধ্যে **সম্পর্কের ধরন** দেখায়। একজন আর্কিটেক্ট একটাই diagram-এর মালিক হতে পারলে এটাই সবচেয়ে কাজের — একটা বাক্স-আর-রেখার deployment diagram-এর চেয়ে অনেক বেশি কাজের, কারণ এটা শুধু কারিগরি তার নয়, *রাজনৈতিক আর সাংগঠনিক* বাস্তবতা দেখায়।

```
  ┌─────────────────┐       Customer/Supplier      ┌─────────────────┐
  │  Verification   │ ────────────────────────────►│    Billing      │
  │    Context      │      (আমরা usage publish করি) │    Context      │
  │   [CORE]        │                              │  [SUPPORTING]   │
  └────────┬────────┘                              └────────┬────────┘
           │                                                │
           │ ACL                                            │ Conformist
           ▼                                                ▼
  ┌─────────────────┐                              ┌─────────────────┐
  │ Vendor Face API │                              │     Stripe      │
  │   [EXTERNAL]    │                              │   [EXTERNAL]    │
  └─────────────────┘                              └─────────────────┘

  ┌─────────────────┐  Shared Kernel (id, money)   ┌─────────────────┐
  │   Identity      │◄────────────────────────────►│   Reviewer      │
  │   Context       │                              │   Console       │
  └─────────────────┘                              └─────────────────┘
```

## ৩.৫ Integration সম্পর্কের pattern গুলো 🟢

এগুলো দুটো context-এর মধ্যে **কারিগরি** আর **রাজনৈতিক** — দুই ধরনের সম্পর্কই বর্ণনা করে। নামগুলো জানা থাকলে আপনি অনেক বেশি নিখুঁত আলোচনা করতে পারবেন।

### ১. Shared Kernel

দুটো context model/code-এর একটা ছোট অংশ ভাগ করে।

```
  Context A ──┐
              ├──► [ Shared Kernel: Money, CustomerId, DateRange ]
  Context B ──┘
```

- ✅ সত্যিকারের সর্বজনীন ধারণার জন্য কোনো পুনরাবৃত্তি নয়
- ❌ **খুবই শক্ত coupling।** যে কোনো পরিবর্তনে দুই টিমের সম্মতি লাগে। এটা একটা বাধা হয়ে দাঁড়ায়।
- **নিয়ম:** এটা ক্ষুদ্র রাখুন (ID, Money, সাধারণ value object) আর দুই টিমের অনুমোদন বাধ্যতামূলক করুন। আপনার "shared kernel"-এ যদি business logic বা entity থাকে, তাহলে সেটা একটা দায়, আর সেটা বেড়ে একটা distributed monolith হবে। অনেক অভিজ্ঞ আর্কিটেক্ট এটা পুরোপুরি এড়িয়ে চলেন।

### ২. Customer/Supplier

নিচের দিকের (customer) সত্যিকারের প্রভাব আছে; উপরের দিক (supplier) তাদের চাহিদা মেটাতে রাজি।

- উপরের টিম একটা contract আর একটা deprecation policy-তে প্রতিশ্রুতিবদ্ধ
- নিচের টিম planning-এ একটা আসন পায়
- ভেতরের টিমগুলোর মধ্যে **স্বাস্থ্যকর আর সাধারণ**। শুধু ভালো ইচ্ছা নয়, আসল সাংগঠনিক সম্মতি লাগে।

### ৩. Conformist

নিচের দিক উপরের model যেমন আছে তেমনই মেনে নেয়, কোনো অনুবাদ ছাড়াই।

- ✅ অনুবাদের খরচ শূন্য, দ্রুত বানানো যায়
- ❌ তাদের model এখন আপনার model; তাদের পরিবর্তন আপনার জরুরি অবস্থা; তাদের খারাপ নামকরণ আপনার কোডে সংক্রমিত হয়
- **ব্যবহার করুন যখন:** উপরের দিকটা একটা ভালোভাবে design করা, স্থিতিশীল standard আর সম্পর্কটা কম ঝুঁকির (যেমন একটা OAuth/OIDC token-এর গঠন মেনে চলা)। **এড়িয়ে চলুন যখন:** উপরের দিকটা একটা এলোমেলো legacy সিস্টেম।

### ৪. Anti-Corruption Layer (ACL) ⭐ 🟢

**এখানকার সবচেয়ে মূল্যবান pattern।** একটা অনুবাদের স্তর, যেটা আপনার model-কে একটা বাইরের model থেকে রক্ষা করে।

```
  ┌──────────────────────┐   ┌─────────────┐   ┌────────────────────────┐
  │  আপনার পরিষ্কার DOMAIN │   │     ACL     │   │  বিশ্রী বাইরের সিস্টেম    │
  │                      │   │             │   │                        │
  │  Customer            │◄──┤ অনুবাদ       ├──►│  CUST_MSTR_REC         │
  │   .Email             │   │             │   │   .EML_ADDR_TXT_1      │
  │   .VerifiedAt        │   │             │   │   .VRFY_DT_STR "20260912"│
  │   .Status: Verified  │   │             │   │   .STAT_CD: "V"         │
  └──────────────────────┘   └─────────────┘   └────────────────────────┘
```

```python
# ── আপনার domain: পরিষ্কার, অর্থপূর্ণ ──
@dataclass(frozen=True)
class VerifiedIdentity:
    full_name: str
    date_of_birth: date
    document_number: str
    verified_at: datetime
    confidence: Confidence          # আসল নিয়ম সহ একটা value object

# ── ACL: একমাত্র জায়গা যে জানে ভেন্ডরটার অস্তিত্ব আছে ──
class AcmeVendorAntiCorruptionLayer:
    """Acme-র model আমাদেরটায় অনুবাদ করে। আর কেউ acme_sdk import করে না।"""

    def __init__(self, client: AcmeClient):
        self._client = client

    async def verify(self, document: DocumentImage) -> VerifiedIdentity:
        try:
            raw = await self._client.doc_check_v3(
                img=base64.b64encode(document.bytes).decode(),
                opts={"lvl": 2, "rtn": "full"},
            )
        except AcmeTimeout as e:                       # ভেন্ডরের exception এখানেই থামে
            raise VerificationUnavailable("vendor timeout") from e
        except AcmeRateLimit as e:
            raise VerificationThrottled(retry_after=e.retry_after) from e

        if raw.get("st") != "OK":                      # ভেন্ডরের অদ্ভুত status code এখানেই থামে
            raise VerificationRejected(self._map_reason(raw.get("err_cd")))

        return VerifiedIdentity(                        # আমাদের model বেরিয়ে আসে
            full_name=f"{raw['fn']} {raw['ln']}".strip(),
            date_of_birth=datetime.strptime(raw["dob"], "%Y%m%d").date(),
            document_number=raw["doc_no"],
            verified_at=datetime.now(timezone.utc),
            confidence=Confidence.from_percent(raw["conf_pct"]),   # ০-১০০ → আমাদের ০-১
        )

    @staticmethod
    def _map_reason(vendor_code: str | None) -> RejectionReason:
        return {
            "E41": RejectionReason.DOCUMENT_EXPIRED,
            "E42": RejectionReason.DOCUMENT_TAMPERED,
            "E55": RejectionReason.FACE_MISMATCH,
        }.get(vendor_code or "", RejectionReason.UNKNOWN)
```

**ACL আপনাকে যা কিনে দেয়:**
- ভেন্ডরের পরিবর্তন **একটা ফাইলে** হাত দেয়
- ভেন্ডর বদলানো মানে একটা নতুন ACL, একটা rewrite নয়
- ভেন্ডরের অদ্ভুততা (status code, তারিখের ফরম্যাট, ০–১০০ স্কেল, উদ্ভট exception) কখনোই আপনার business logic-এ পৌঁছায় না
- আপনি একটা fake ACL দিয়ে আপনার domain test করতে পারেন

> **নিয়ম: প্রতিটা বাইরের সিস্টেম আর প্রতিটা legacy সিস্টেমের সামনে একটা ACL বসান। প্রতিবার। একটা পেশাদার integration-এ এটা আপসহীন।**

### ৫. Open Host Service (OHS)

আপনি উপরের দিকে আর অনেক context আপনাকে ব্যবহার করে, তাই আপনি প্রতি consumer-এর জন্য আলাদা integration না বানিয়ে একটা **ভালোভাবে design করা, সাধারণ উদ্দেশ্যের public API** প্রকাশ করেন।

এটা লাগবে এমন চিহ্ন: আপনি "team X-এর জন্য বিশেষ endpoint" চতুর্থবারের মতো লিখছেন।

### ৬. Published Language

Context-এর মধ্যে তথ্য বিনিময়ের জন্য একটা **ভাগ করা, ভালোভাবে নথিভুক্ত ফরম্যাট** — JSON Schema, OpenAPI, Protobuf, Avro, বা একটা শিল্পমান (স্বাস্থ্যে FHIR, payments-এ ISO 20022, finance-এ FpML)।

OHS + Published Language একসাথে = "এই আমাদের public API আর এই এটা যা যা বলে তার নথিভুক্ত, version করা schema।"

### ৭. Separate Ways

দুটো context-এর মধ্যে **কোনো** integration নেই। কখনো কখনো অল্প কিছু কাজের পুনরাবৃত্তি করা integration করার চেয়ে সস্তা।

এটা নিয়ে লজ্জা পাবেন না। Integration করতে যদি ৩ মাস লাগে আর পুনরাবৃত্তি করতে ৩ দিন, তাহলে পুনরাবৃত্তি করুন। Integration বিনামূল্যে নয়।

### ৮. Partnership

দুটো টিম একসাথে সফল হয় বা ব্যর্থ হয়; তারা release সমন্বয় করে আর একসাথে পরিকল্পনা করে। দুটো টিমের জন্য সৎ আর কার্যকর; দশটার জন্য অসামলানো।

### ৯. Big Ball of Mud

"এই এলাকায় কোনো বোধগম্য model নেই" — এর জন্য একটা নামযুক্ত pattern। মানচিত্রে এটা চিহ্নিত করা মূল্যবান: এটা সবাইকে বলে *"এখানে একটা ACL বসাও আর এটা বোঝার চেষ্টা কোরো না।"*

---

# পর্ব ২ — Tactical DDD 🟢

একটা bounded context-এর ভেতরের গাঁথুনির উপকরণ।

## ৩.৬ Entity

**সংজ্ঞা:** এমন একটা object যেটা তার **পরিচয়** দিয়ে সংজ্ঞায়িত, তার বৈশিষ্ট্য দিয়ে নয়। এর একটা জীবনচক্র আছে, আর এটা সময়ের সাথে বদলায়।

**বাস্তব জীবন:** আপনি। আপনার নাম, ঠিকানা, ওজন আর চুলের ছাঁট সবই বদলাতে পারে — আপনি তবু একই মানুষ। জাতীয় পরিচয়পত্র দিয়ে শনাক্ত, বৈশিষ্ট্য দিয়ে নয়।

```csharp
public class VerificationSession                // ENTITY: Id দিয়ে শনাক্ত
{
    public SessionId Id { get; }                // পরিচয় — কখনো বদলায় না
    public CustomerId CustomerId { get; }
    public SessionStatus Status { get; private set; }   // বৈশিষ্ট্য বদলায়
    private readonly List<Attempt> _attempts = new();

    // দুটো session সমান যদি তাদের ID সমান হয় — আর কিছুতেই কিছু আসে যায় না
    public override bool Equals(object? obj) => obj is VerificationSession s && s.Id == Id;
    public override int GetHashCode() => Id.GetHashCode();
}
```

**মূল চর্চা:**
- **কোনো public setter নয়।** পরিবর্তন হয় অর্থপূর্ণ method দিয়ে: `session.Approve(reviewerId)`, `session.Status = "approved"` নয়। Setter caller-দের object-টাকে অবৈধ অবস্থায় ফেলার সুযোগ দেয়।
- সমতা শুধু **ID দিয়ে**
- Entity **নিজের invariant নিজে রক্ষা করে** — একটা অবৈধ entity বানানো বা বদলানো অসম্ভব হওয়া উচিত

## ৩.৭ Value Object

**সংজ্ঞা:** এমন একটা object যেটা সম্পূর্ণভাবে তার **মান** দিয়ে সংজ্ঞায়িত। কোনো পরিচয় নেই। Immutable। পরস্পর বদলযোগ্য।

**বাস্তব জীবন:** একটা ৫০০ টাকার নোট। যে কোনো ৫০০ টাকার নোট অন্য যে কোনোটার সমান ভালো। আপনি *কোন* নোট সেটা track করেন না।

```csharp
public record Money(decimal Amount, string Currency)     // VALUE OBJECT
{
    public static Money Zero(string ccy) => new(0, ccy);

    public Money Add(Money other) => other.Currency == Currency
        ? new Money(Amount + other.Amount, Currency)
        : throw new CurrencyMismatchException(Currency, other.Currency);

    public Money Multiply(decimal factor) => this with { Amount = Amount * factor };
}

public record EmailAddress
{
    public string Value { get; }
    public EmailAddress(string value)
    {
        if (!MailAddress.TryCreate(value, out _))
            throw new InvalidEmailException(value);      // অবৈধ অস্তিত্ব পেতেই পারে না
        Value = value.Trim().ToLowerInvariant();         // তৈরির সময়ই normalise
    }
    public string Domain => Value.Split('@')[1];
}

public record LivenessScore
{
    public decimal Value { get; }
    public LivenessScore(decimal value)
    {
        if (value is < 0 or > 1) throw new ArgumentOutOfRangeException(nameof(value));
        Value = value;
    }
    public bool MeetsThreshold(LivenessScore threshold) => Value >= threshold.Value;
    public Confidence Band => Value switch
    {
        >= 0.95m => Confidence.VeryHigh,
        >= 0.85m => Confidence.High,
        >= 0.60m => Confidence.Medium,
        _        => Confidence.Low
    };
}
```

### Value object কেন মানের দিক থেকে বিশাল জয়

**আগে (primitive obsession):**

```csharp
public void Transfer(string from, string to, decimal amount, string currency) { }
Transfer(toAccount, fromAccount, 100, "USD");        // argument উল্টে গেছে — দিব্যি COMPILE হয়
Transfer(from, to, -50, "US Dollars");               // ঋণাত্মক, খারাপ currency — দিব্যি COMPILE হয়
```

**পরে:**

```csharp
public void Transfer(AccountNumber from, AccountNumber to, Money amount) { }
Transfer(to, from, money);                           // COMPILE ERROR? না - কিন্তু type মেলে
// তবে: Money(-50, "US Dollars") তৈরির সময়ই throw করে। অবৈধ অবস্থা অস্তিত্ব পেতে পারে না।
```

> **আঙুলের নিয়ম:** একটা ধারণার যদি নিয়ম থাকে (একটা email-এর একটা ফরম্যাট আছে, একটা score-এর একটা পরিসর আছে, টাকার একটা currency আছে), তাহলে সেটা একটা value object-এর যোগ্য। `string`/`decimal`-এর বদলে value object বসালে আস্ত কয়েক শ্রেণির bug দূর হয়, আর validation "controller-এ ছড়ানো `if`" থেকে "একটা জায়গা, type system দিয়ে বলবৎ"-এ চলে যায়।

**আরও:** value object immutable (অধ্যায় ০১), তাই এগুলো thread-safe, cache করা যায় আর ভাগ করা নিরাপদ।

## ৩.৮ Aggregate আর Aggregate Root ⭐

**সবচেয়ে কঠিন আর সবচেয়ে মূল্যবান tactical ধারণা।**

**সংজ্ঞা:** একটা aggregate হলো entity আর value object-এর একটা গুচ্ছ, যেটাকে **data পরিবর্তনের জন্য একটা একক** হিসেবে দেখা হয়। একটা entity হলো **Aggregate Root** — একমাত্র সদস্য, যার reference বাইরের কোড ধরে রাখতে পারে।

**বাস্তব জীবন:** একটা order আর তার line গুলো। আপনি কখনোই একটা order line আলাদাভাবে সম্পাদনা করেন না — "এই line যোগ করো" হলো *order*-এর উপর একটা operation, কারণ order-এর total, ছাড় আর ন্যূনতম মানের নিয়ম line গুলোর উপর নির্ভর করে।

```
  ┌──────── AGGREGATE-এর সীমানা ────────────────────┐
  │                                                 │
  │   ┌──────────────────┐  ← AGGREGATE ROOT        │
  │   │      Order       │    (একমাত্র public দরজা)  │
  │   │  - Id            │                          │
  │   │  - Status        │                          │
  │   │  - Total         │                          │
  │   └────────┬─────────┘                          │
  │            │ মালিক                              │
  │   ┌────────▼─────────┐   ┌──────────────────┐   │
  │   │   OrderLine[]    │   │ ShippingAddress  │   │
  │   │   (entity)       │   │ (value object)   │   │
  │   └──────────────────┘   └──────────────────┘   │
  └─────────────────────────────────────────────────┘
              ▲
              │  বাইরের কোড শুধু Order ছুঁতে পারে,
              │  আর অন্য aggregate-কে শুধু ID দিয়ে reference করতে পারে
         CustomerId (শুধু একটা ID, কোনো Customer object নয়)
```

### Aggregate-এর পাঁচটা নিয়ম

**১. Root-ই একমাত্র প্রবেশপথ।** বাইরের কোড কখনো ভেতরের কোনো entity-র reference ধরে রাখে না।

```csharp
// ভুল — collection উন্মুক্ত আর mutable; invariant এড়িয়ে যাওয়া যায়
public List<OrderLine> Lines { get; set; }
order.Lines.Add(new OrderLine(...));       // total আবার হিসাব হলো না, নিয়ম যাচাই হলো না

// সঠিক
private readonly List<OrderLine> _lines = new();
public IReadOnlyList<OrderLine> Lines => _lines.AsReadOnly();

public void AddLine(ProductId product, int quantity, Money unitPrice)
{
    if (Status != OrderStatus.Draft)
        throw new OrderAlreadySubmittedException(Id);
    if (_lines.Count >= MaxLines)
        throw new TooManyLinesException(Id, MaxLines);

    var existing = _lines.FirstOrDefault(l => l.ProductId == product);
    if (existing is not null) existing.IncreaseQuantity(quantity);
    else _lines.Add(new OrderLine(product, quantity, unitPrice));

    RecalculateTotal();                              // invariant সবসময় বজায়
}
```

**২. Aggregate হলো transaction আর consistency-র সীমানা।** ভেতরের সবকিছু প্রতিটা operation-এর পর সাথে সাথে consistent। বাইরের কিছুই নয়।

**৩. অন্য aggregate-কে শুধু ID দিয়ে reference করুন।**

```csharp
// ভুল — aggregate-এর মধ্যে object reference
public class Order { public Customer Customer { get; set; } }
// এখন একটা order load করলে একটা customer load হয়, যেটা তার order গুলো load করে, যেটা...

// সঠিক
public class Order { public CustomerId CustomerId { get; } }
```

এই একটা নিয়মই "একটা object load করো, অর্ধেক database memory-তে টেনে আনো" — এই বিপর্যয় ঠেকায়, আর aggregate-এর সীমানাকে সাজসজ্জা নয়, বাস্তব রাখে।

**৪. এক transaction = এক aggregate।** একটা business operation-কে যদি দুটো aggregate বদলাতে হয়, তাহলে একটা বড় transaction নয়, একটা domain event দিয়ে **eventual consistency** ব্যবহার করুন।

```csharp
// ভুল — এক transaction-এ দুটো aggregate
order.Submit();
customer.IncrementOrderCount();      // আলাদা aggregate!
await _uow.SaveChangesAsync();

// সঠিক — order একটা event raise করে; একটা handler customer আলাদাভাবে update করে
order.Submit();                      // OrderSubmitted raise করে
await _uow.SaveChangesAsync();
// → OrderSubmitted-এর handler নিজের transaction-এ Customer update করে
```

**কেন?** কারণ একাধিক aggregate-এর transaction-ই আপনাকে scale করতে বাধা দেয়, আর এটাই পরে একটা service বের করা অসম্ভব করে তোলে। একটা monolith-এর ভেতরে এই নিয়ম মানাই ভবিষ্যতের ভাগ করাকে সস্তা করে।

**৫. Aggregate ছোট রাখুন।** ক্লাসিক ব্যর্থতা হলো এমন একটা `Customer` aggregate যাতে তার সব order আছে। ১০,০০০ order সহ একজন customer load করাই যায় না, আর প্রতিটা order পরিবর্তন পুরো customer lock করে।

### সীমানা কীভাবে ঠিক করবেন — invariant পরীক্ষা

> **জিজ্ঞেস করুন: "কোন নিয়মটা প্রতিটা মুহূর্তে সত্য থাকতেই হবে, কোনো দেরি ছাড়াই?"**
> ওই নিয়ম যা যা ছোঁয়, সবকিছু একটা aggregate-এর ভেতরে থাকতে হবে। বাকি সব বাইরে।

উদাহরণ:

| Invariant | ফলাফল |
|-----------|-------------|
| "Order-এর total তার line গুলোর যোগফলের সমান হতেই হবে" | Line গুলো Order aggregate-এর **ভেতরে** |
| "একজন customer-এর ৫টার বেশি সক্রিয় order থাকতে পারবে না" | ১ সেকেন্ড দেরি কি গ্রহণযোগ্য? প্রায় সবসময়ই **হ্যাঁ** → আলাদা aggregate + eventual consistency। সত্যিই যদি না হয় (নিয়ন্ত্রক সংস্থার কারণে), তাহলে আপনার আলাদা design লাগবে (একটা reservation, বা একটা aggregate)। |
| "একটা session-এ সর্বোচ্চ ৩টা attempt থাকতে পারে" | Attempt গুলো Session aggregate-এর **ভেতরে** |
| "কোম্পানির মোট খরচ বাজেট ছাড়াতে পারবে না" | Concurrency-তে এতে সাবধানতা লাগে — একটা `SUM()` যাচাই নয়, reservation সহ একটা আলাদা `Budget` aggregate ভাবুন |

**প্রতিটা invariant-কে এই প্রশ্ন দিয়ে চ্যালেঞ্জ করুন: "এটা যদি ২ সেকেন্ড পরে সত্য হয় তাহলে কী?"** বিজনেসের লোকেরা সাধারণত বলেন "ঠিক আছে"। তাঁরা যখন "ঠিক আছে" বলেন, আপনি একটা ছোট aggregate, ভালো concurrency, আর ভবিষ্যতে সহজ ভাগ করা পান।

### Concurrency আর aggregate

Aggregate যেহেতু consistency-র সীমানা, তাই এটা **lock**-এরও সীমানা। **Optimistic concurrency** ব্যবহার করুন: root-এ একটা version কলাম।

```csharp
// EF Core
public class Order
{
    [Timestamp] public byte[] RowVersion { get; private set; } = default!;
}
// দুজন ব্যবহারকারী একই order সম্পাদনা করলে → দ্বিতীয় SaveChanges DbUpdateConcurrencyException ছুঁড়ে
```

ছোট aggregate → কম সংঘর্ষ। ৫ নম্বর নিয়ম গুরুত্বপূর্ণ হওয়ার এটাও একটা কারণ।

## ৩.৯ Repository (DDD-র ভাষায়)

যান্ত্রিক দিকটা অধ্যায় ০১-এ আছে। DDD-র নিয়মগুলো:

- **প্রতি aggregate root-এ একটা repository।** কখনো প্রতি table-এ নয়, কখনো প্রতি ভেতরের entity-তে নয়।
- এটা **সম্পূর্ণ গঠিত aggregate** ফেরত দেয়, যাদের invariant অক্ষত
- এটা **ubiquitous language**-এ কথা বলে: `GetActiveSessionsAwaitingReview()`, `SelectWhereStatusIn(1,2)` নয়

## ৩.১০ Domain Service

**সংজ্ঞা:** এমন business logic যা স্বাভাবিকভাবে কোনো একটা entity বা value object-এর নয়।

**সংকেত:** আপনার এমন একটা নিয়ম আছে যাতে দুই বা ততোধিক aggregate জড়িত, অথবা এমন একটা operation যা একটা *জিনিস* নয় বরং একটা *প্রক্রিয়া*।

```python
# "এই মুখটা কি এই document-এর ছবির সাথে মেলে?" — এটার মালিক কোন entity হওয়া উচিত?
# Session বা Document একা কোনোটাই নয়। তাই: একটা domain service।
class FaceMatchingPolicy:                # DOMAIN service: বিশুদ্ধ নিয়ম, কোনো I/O নয়
    STRICT_THRESHOLD = Similarity(0.92)
    STANDARD_THRESHOLD = Similarity(0.85)

    def decide(self, similarity: Similarity, risk: RiskLevel,
               document: DocumentQuality) -> MatchDecision:
        threshold = self.STRICT_THRESHOLD if risk is RiskLevel.HIGH else self.STANDARD_THRESHOLD
        if document.is_poor():
            threshold = threshold.relaxed_by(Decimal("0.03"))
        if similarity >= threshold:
            return MatchDecision.matched(similarity, threshold)
        if similarity >= threshold.relaxed_by(Decimal("0.05")):
            return MatchDecision.manual_review(similarity, threshold)
        return MatchDecision.rejected(similarity, threshold)
```

**গুরুত্বপূর্ণ পার্থক্য (মানুষ অনবরত এগুলো গুলিয়ে ফেলে):**

| | Domain Service | Application Service |
|---|---|---|
| **যা থাকে** | Business rule | Orchestration |
| **I/O করে?** | **কখনোই না** | হ্যাঁ — repo, HTTP, queue |
| **Transaction?** | না | হ্যাঁ, transaction-এর মালিক এটাই |
| **Infra ছাড়া testable?** | সবসময় | Fake দিয়ে |
| **উদাহরণ** | `FaceMatchingPolicy.decide()` | `VerificationService.verify()` |

> আপনার "domain service"-এ যদি একটা repository inject করা থাকে, তাহলে সেটা সম্ভবত ভুল টুপি পরা একটা application service। এতে সমস্যা নেই — শুধু ঠিক নাম দিন আর ঠিক layer-এ রাখুন।

## ৩.১১ Factory

একটা aggregate তৈরি করা যখন জটিল (অনেক invariant, বা টুকরো থেকে জোড়া লাগানো), তখন logic-টা একটা factory-তে রাখুন — aggregate-এর একটা static method, বা একটা আলাদা factory class।

```csharp
public class VerificationSession
{
    private VerificationSession() { }   // কোনো public constructor নেই — তৈরি নিয়ন্ত্রিত

    public static VerificationSession Start(
        CustomerId customer, TenantPolicy policy, IClock clock)
    {
        if (!policy.AllowsNewSessions)
            throw new TenantSuspendedException(policy.TenantId);

        var session = new VerificationSession
        {
            Id = SessionId.New(),
            CustomerId = customer,
            Status = SessionStatus.Pending,
            ExpiresAt = clock.UtcNow.Add(policy.SessionTimeout),
            MaxAttempts = policy.MaxAttempts,
            RequiredChallenges = ChallengeSet.ForRiskLevel(policy.RiskLevel),
        };
        session.Raise(new SessionStarted(session.Id, customer, clock.UtcNow));
        return session;
    }
}
```

সুবিধা: আপনি একটা অবৈধ session বানাতেই পারবেন না; তৈরির নিয়মগুলো একটা জায়গায় থাকে; event স্বয়ংক্রিয়ভাবে raise হয়।

## ৩.১২ Domain Event

যান্ত্রিক দিকটা অধ্যায় ০১-এ আছে। DDD-র ভাষায়:

- একটা domain event হলো **এমন একটা সত্য যা নিয়ে domain বিশেষজ্ঞরা ভাবেন** — বিজনেস যদি কথাটা মুখে না বলত, তাহলে সেটা সম্ভবত domain event নয়
- নাম **অতীত কালে**, **ubiquitous language**-এ: `VerificationPassed`, `PolicyRenewed`, `ClaimSettled`
- **Aggregate raise করে**, infrastructure dispatch করে
- এগুলোই **aggregate-এর মধ্যে eventual consistency**-র কৌশল (aggregate-এর নিয়ম ৪)
- এগুলো প্রায়ই bounded context-এর মধ্যেকার স্বাভাবিক **integration event** — তবে সাবধান: একটা ভেতরের domain event আর একটা প্রকাশিত integration event সাধারণত **আলাদা type** হওয়া উচিত, কারণ আপনার ভেতরের model প্রকাশ করলে অন্য context গুলো তার সাথে coupled হয়ে যায়।

```csharp
// ভেতরের domain event — সমৃদ্ধ, আমাদের model-এর সাথে জড়িত, অবাধে বদলাতে পারে
internal record VerificationPassed(SessionId Id, LivenessScore Score, VendorDetail Detail);

// প্রকাশিত integration event — স্থিতিশীল, version করা, ইচ্ছাকৃতভাবে ন্যূনতম
public record CustomerVerifiedV1(string CustomerId, string SessionId, DateTime VerifiedAt);
```

---

## ৩.১৩ সব একসাথে: একটা কাজ করা উদাহরণ

**বিজনেস:** একটা KYC প্ল্যাটফর্ম। একটা bounded context ঠিকভাবে model করা যাক।

```
BOUNDED CONTEXT: Verification

Ubiquitous language-এর glossary:
  Session      — একজন customer-এর পরিচয় প্রমাণের একটা প্রচেষ্টা, সময়-সীমিত
  Attempt      — একটা session-এর ভেতরে ভিডিও জমা দেওয়ার একটা ঘটনা
  Challenge    — আমরা ব্যবহারকারীকে যে কাজটা করতে বলি (বাঁয়ে ঘোরা, চোখ পিটপিট করা)
  Signals      — engine থেকে আসা কাঁচা পরিমাপ (score, spoof flag, pose)
  Outcome      — চূড়ান্ত Passed / Failed / ManualReview সিদ্ধান্ত
  Reviewer     — একজন মানুষ, যিনি ManualReview-এর নিষ্পত্তি করেন
```

```python
# ── VALUE OBJECT ─────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class LivenessScore:
    value: Decimal
    def __post_init__(self):
        if not (0 <= self.value <= 1):
            raise ValueError("liveness score must be between 0 and 1")

@dataclass(frozen=True, slots=True)
class Signals:
    liveness: LivenessScore
    spoof_detected: bool
    head_pose_valid: bool
    frame_quality: Decimal

@dataclass(frozen=True, slots=True)
class Attempt:                       # aggregate-এর ভেতরের entity (স্থানীয় পরিচয়)
    number: int
    signals: Signals
    passed: bool
    at: datetime

# ── AGGREGATE ROOT ───────────────────────────────────────────────
class VerificationSession:
    PASS_THRESHOLD = LivenessScore(Decimal("0.85"))
    REVIEW_BAND    = Decimal("0.05")

    def __init__(self, id_, customer_id, max_attempts, expires_at):
        self.id = id_
        self.customer_id = customer_id          # অন্য aggregate, শুধু ID দিয়ে
        self._max_attempts = max_attempts
        self._expires_at = expires_at
        self._attempts: list[Attempt] = []
        self.outcome: Outcome = Outcome.PENDING
        self._events: list[DomainEvent] = []

    # ---- FACTORY ----
    @classmethod
    def start(cls, customer_id: CustomerId, policy: TenantPolicy, now: datetime):
        if not policy.allows_new_sessions:
            raise TenantSuspended(policy.tenant_id)
        s = cls(SessionId.new(), customer_id, policy.max_attempts,
                now + policy.session_timeout)
        s._raise(SessionStarted(s.id, customer_id, now))
        return s

    # ---- আচরণ (invariant এখানেই বলবৎ, আর কোথাও নয়) ----
    def record_attempt(self, signals: Signals, now: datetime) -> None:
        if self.outcome is not Outcome.PENDING:
            raise SessionAlreadyConcluded(self.id, self.outcome)
        if now > self._expires_at:
            self._conclude(Outcome.FAILED, "expired", now); return
        if len(self._attempts) >= self._max_attempts:
            raise TooManyAttempts(self.id, self._max_attempts)

        passed = (not signals.spoof_detected
                  and signals.head_pose_valid
                  and signals.liveness.value >= self.PASS_THRESHOLD.value)

        self._attempts.append(Attempt(len(self._attempts) + 1, signals, passed, now))

        if passed:
            self._conclude(Outcome.PASSED, "threshold met", now)
        elif self._is_borderline(signals):
            self._conclude(Outcome.MANUAL_REVIEW, "borderline score", now)
        elif len(self._attempts) >= self._max_attempts:
            self._conclude(Outcome.FAILED, "max attempts exhausted", now)

    def _is_borderline(self, s: Signals) -> bool:
        return (not s.spoof_detected
                and self.PASS_THRESHOLD.value - self.REVIEW_BAND
                    <= s.liveness.value < self.PASS_THRESHOLD.value)

    def _conclude(self, outcome: Outcome, reason: str, now: datetime) -> None:
        self.outcome = outcome
        event = {
            Outcome.PASSED:        SessionPassed,
            Outcome.FAILED:        SessionFailed,
            Outcome.MANUAL_REVIEW: SessionFlaggedForReview,
        }[outcome]
        self._raise(event(self.id, self.customer_id, reason, now))

    def _raise(self, e: DomainEvent) -> None:
        self._events.append(e)

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
```

খেয়াল করুন এই কোডে কী কী আছে:

- **কোনো database নেই। কোনো HTTP নেই। কোনো framework নেই।** এটা একটা unit test-এ মাইক্রোসেকেন্ডে চলে।
- প্রতিটা business rule **একটা ফাইলে দৃশ্যমান**, business-এর ভাষায়
- অবৈধ অবস্থা **অসম্ভব** — আপনি ৪র্থ attempt রেকর্ড করতে পারবেন না, বা দুইবার সিদ্ধান্তে পৌঁছাতে পারবেন না
- এটা এমন **event** তৈরি করে যাতে অন্য context গুলো সাড়া দিতে পারে
- একজন compliance officer `record_attempt` পড়ে policy-টা নিশ্চিত করতে পারবেন

এটাই tactical DDD-র লাভ।

---

## ৩.১৪ কখন DDD ব্যবহার করবেন না

সৎ থাকুন — DDD ব্যয়বহুল।

❌ **পূর্ণ DDD ব্যবহার করবেন না যখন:**
- Domain সাধারণ CRUD (একটা contact list, একটা CMS)। একটা form-এর জন্য সমৃদ্ধ aggregate নিছক আনুষ্ঠানিকতা।
- Domain বিশেষজ্ঞদের কাছে যাওয়ার উপায় নেই (DDD-তে ওই কথোপকথন *লাগেই*; সেটা ছাড়া আপনি একটা নকল model বানাবেন)
- টিমের এটা শেখার আগ্রহ নেই — অর্ধেক প্রয়োগ করা DDD একেবারে না করার চেয়ে খারাপ
- সিস্টেমটা স্বল্পস্থায়ী (একটা ৩ মাসের campaign সাইট)
- এটা একটা কারিগরি utility, business domain নয় (একটা logging library-র কোনো ubiquitous language নেই)

✅ **কৌশলগত অংশগুলো সবসময় ব্যবহার করুন** (subdomain-এর শ্রেণিবিভাগ, bounded context, context map, ACL) — এগুলো সস্তা আর **যে কোনো** আকারের **যে কোনো** প্রজেক্টে লাভ দেয়।

🟡 **Tactical অংশগুলো বেছে বেছে যোগ করুন** — আপনার **core subdomain**-এ সমৃদ্ধ aggregate ব্যবহার করুন, আর generic/supporting-এ সাধারণ CRUD। একটা সিস্টেমের ভেতরে style মেশানো অসঙ্গতি নয়; এটা পরিমিত engineering।

---

## ৩.১৫ সাধারণ ভুল

১. **"DDD = ফোল্ডারের গঠন"** — `Domain/`, `Application/`, `Infrastructure/` ফোল্ডার বানিয়ে একে DDD বলা, অথচ ভেতরের কোড anemic CRUD
২. **Anemic domain model** — শুধু getter আর setter সহ entity; সব নিয়ম service-এ। এখন পর্যন্ত সবচেয়ে সাধারণ DDD-র ব্যর্থতা।
৩. **বিশাল aggregate** — `Customer`-এ তার সব order, সব ঠিকানা, সব invoice। Load করা যায় না, lock করা যায় না।
৪. **Aggregate-এর মধ্যে object reference** — অর্ধেক DB load করা আর অস্পষ্ট সীমানার দিকে নিয়ে যায়
৫. **একাধিক aggregate-এর transaction** — নীরবে পরে scale করা বা ভাগ করার ক্ষমতা ধ্বংস করে
৬. **পুরো কোম্পানির জন্য একটা model** — bounded context উপেক্ষা করে ৮০-field-এর `Policy` বানানো
৭. **Legacy/ভেন্ডর সিস্টেমের বিরুদ্ধে কোনো ACL নেই** — তাদের model স্থায়ীভাবে আপনারটায় সংক্রমিত হয়
৮. **Domain বিশেষজ্ঞদের উপেক্ষা করা** — নিজেই ভাষা বানানো; আপনি সব জায়গায় সূক্ষ্মভাবে ভুল হবেন
৯. **Generic subdomain-এ tactical DDD** — email-preference screen-এর জন্য যত্ন করে গড়া একটা aggregate
১০. **Shared kernel যেটা বাড়ে** — `Money` দিয়ে শুরু, শেষে অর্ধেক domain, আর এখন দুটো টিম নড়তে পারে না

---

## ৩.১৬ আর্কিটেক্টের চেকলিস্ট

- [ ] Subdomain গুলোর তালিকা আছে আর Core / Supporting / Generic হিসেবে শ্রেণিবদ্ধ?
- [ ] Engineering-এর পরিশ্রম কি আসলেই ওই শ্রেণিবিভাগের সাথে মেলে?
- [ ] Bounded context গুলো চিহ্নিত, প্রতিটা context-এর জন্য লিখিত glossary সহ?
- [ ] প্রতি জোড়ার মধ্যে সম্পর্কের ধরন দেখানো একটা context map আছে?
- [ ] প্রতিটা বাইরের/legacy সিস্টেমের কি একটা ACL আছে?
- [ ] প্রতিটা টুকরো data-র মালিক কি ঠিক **একটা** context?
- [ ] প্রতিটা aggregate-এর জন্য: কোন invariant তার সীমানার যুক্তি দেয়?
- [ ] কোনো transaction কি একটার বেশি aggregate ছোঁয়?
- [ ] Aggregate গুলো কি একে অপরকে শুধু ID দিয়ে reference করে?
- [ ] Domain model কি কোনো infrastructure ছাড়া unit-test করা যায়?
- [ ] Class আর method-এর নাম কি domain বিশেষজ্ঞরা মুখে যা বলেন তার সাথে মেলে?
- [ ] ভেতরের domain event কি প্রকাশিত integration event থেকে আলাদা?

---

## ৩.১৭ নিজেকে যাচাই

১. তিনটা বিভাগের "Policy" লাগে মানেই কেন আপনার একটা `Policy` class লাগে না?
২. একটা ride-hailing কোম্পানির জন্য এগুলো শ্রেণিবদ্ধ করুন: pricing/surge algorithm, driver payout, email পাঠানো, rider-এর সাথে driver মেলানো, ট্যাক্স invoicing।
৩. একটা Bounded Context আর একটা Microservice-এর সম্পর্ক কী?
৪. আপনি একটা context-এর সীমানা পেরিয়েছেন — এমন পাঁচটা ব্যবহারিক সংকেত দিন।
৫. ছয় ধাপে Event Storming ব্যাখ্যা করুন। এটা যে তর্ক ঘটায়, তার উদ্দেশ্য কী?
৬. Entity বনাম Value Object — আপনার জানা একটা domain থেকে প্রতিটার দুটো উদাহরণ দিন।
৭. Aggregate-এর পাঁচটা নিয়ম বলুন।
৮. একটা aggregate-এর সীমানা খুঁজে বের করার "invariant পরীক্ষা" কী?
৯. অন্য aggregate-কে object reference নয়, ID দিয়ে reference করতে হবে কেন?
১০. একটা business rule দুটো aggregate জুড়ে বিস্তৃত। আপনি এটা কীভাবে implement করবেন?
১১. Domain Service বনাম Application Service — নির্ণায়ক পার্থক্যটা বলুন।
১২. কখন আপনার DDD ব্যবহার করা *উচিত নয়*?

---

## ৩.১৮ মূল কথাগুলো

- **একই শব্দ একটা বিজনেসের আলাদা অংশে আলাদা মানে বোঝায়** — এটাই প্রতিষ্ঠাতা অন্তর্দৃষ্টি
- **Bounded Context-ই আপনার service boundary।** অন্য সবকিছুর আগে এগুলো ঠিক করুন
- **Subdomain শ্রেণিবদ্ধ করুন** — Core বানান, Generic কিনুন। দেখুন আপনার ঘণ্টাগুলো আসলে কোথায় যায়
- **Ubiquitous Language** — আপনার কোড একজন domain বিশেষজ্ঞের পড়ার যোগ্য হওয়া উচিত
- **প্রতিটা বাইরের আর legacy সিস্টেমের সামনে ACL। প্রতিবার।**
- **Aggregate = consistency + transaction + lock-এর সীমানা।** ছোট রাখুন, ID দিয়ে reference করুন, এক transaction-এ একটা
- **Value object primitive obsession মেরে ফেলে** আর অবৈধ অবস্থা অসম্ভব করে
- **Strategic DDD সস্তা আর সবসময়ই সার্থক। Tactical DDD ব্যয়বহুল — সেটা আপনার core domain-এ খরচ করুন।**
- **Anemic domain model**-ই DDD প্রজেক্ট ব্যর্থ হওয়ার সবচেয়ে সাধারণ উপায়

---

**পরবর্তী:** [অধ্যায় ০৪ — System Design-এর মূল বিষয়](04-system-design-fundamentals.md)

**ইংরেজি সংস্করণ:** [Chapter 03](../03-domain-driven-design.md) · **[সূচিপত্র](README.md)**
