# Chapter 03 — Domain-Driven Design 🟢

> DDD is not a framework, a folder structure, or a set of base classes.
> It is a way of **finding the right boundaries** in a business, and keeping the code honest to that business.

For an architect, DDD's strategic half is more valuable than the tactical half. **Bounded Contexts are, in practice, your service boundaries.** Get those right and everything downstream gets easier. Get them wrong and no amount of Kubernetes will save you.

---

## 3.0 The problem DDD solves

Imagine an insurance company. Three departments say the word **"policy"** twenty times a day:

- **Sales** — a policy is a quote that was accepted. It has a price, a commission, a salesperson.
- **Claims** — a policy is a list of what is covered, with limits and exclusions.
- **Finance** — a policy is a stream of premium payments, with tax and accounting codes.

A junior engineer builds **one `Policy` class** to serve all three. It has 80 fields. Sales needs `commissionRate`; Claims does not. Claims needs `exclusions`; Finance does not. Every change breaks two departments. After two years, nobody dares touch it and everything is nullable.

**DDD's answer:** Stop. There are **three different concepts** that happen to share a word. Build three models, in three **Bounded Contexts**, and define how they translate between each other.

> That single insight — *the same word means different things in different parts of a business, and that is fine* — is worth more than all the tactical patterns combined.

---

# PART 1 — Strategic DDD 🟢

This is the architect's half.

## 3.1 Domain, Subdomain, and the three types

**Domain** = the entire business problem space your company operates in. For an identity-verification company, the domain is "proving that a person is who they claim to be, remotely".

**Subdomain** = a distinct area within that domain.

### The three kinds of subdomain — and why the classification drives real decisions

| Type | What it is | Investment strategy | Example (KYC/liveness company) |
|------|-----------|--------------------|-----------------------------|
| **Core** | What makes you money. Your competitive advantage. | **Your best engineers. Build it. Never outsource.** | The liveness/anti-spoofing engine, the risk-scoring model |
| **Supporting** | Necessary, specific to you, but not a differentiator | Build simply, or outsource-with-supervision | Verification workflow orchestration, tenant onboarding, the reviewer console |
| **Generic** | Every company needs it; solved problems | **Buy. Always.** | Authentication, billing, email, storage, logging, PDF generation |

**Why this matters so much in practice:**

A team spends 4 months building a beautiful custom authentication system with SSO, MFA and SCIM (generic subdomain — should have been Auth0 in 2 weeks), while the anti-spoofing model (core) is a threshold on a single vendor score that a competitor beats. They invested exactly backwards. This is astonishingly common.

> **Architect's first strategic act on any project:** list the subdomains and classify each one. Then check where the engineering hours are actually going. The mismatch is usually shocking, and fixing it is the highest-value thing you will do that quarter.

```
DOMAIN: Remote Identity Verification
│
├── CORE ────────────► Liveness Detection Engine      (build, best people)
├── CORE ────────────► Fraud & Risk Scoring           (build, best people)
│
├── SUPPORTING ─────► Verification Workflow          (build, keep simple)
├── SUPPORTING ─────► Reviewer Console               (build, keep simple)
├── SUPPORTING ─────► Tenant & Quota Management      (build, keep simple)
│
├── GENERIC ────────► Identity & Access (SSO/MFA)    (BUY — Keycloak/Auth0/Entra)
├── GENERIC ────────► Billing & Invoicing            (BUY — Stripe)
├── GENERIC ────────► Notifications                  (BUY — SendGrid/Twilio)
└── GENERIC ────────► Object Storage                 (BUY — S3/Blob)
```

## 3.2 Ubiquitous Language

**Definition:** One shared vocabulary, used by business people *and* in the code, with no translation layer.

**The test:** open your code. Can a domain expert read the method names and class names and recognise their business?

```python
# NOT ubiquitous language — technical noise, business meaning hidden
def update_record(self, rec_id: int, flag: int, val: float) -> None:
    row = self.db.get(rec_id)
    row.status_flag = flag
    row.score_val = val
    self.db.save(row)
```

```python
# Ubiquitous language — a compliance officer could read this
def record_verification_attempt(self, session_id: SessionId, signals: LivenessSignals) -> None:
    session = self._sessions.get(session_id)
    session.record_attempt(signals)
    if session.is_conclusively_spoofed():
        session.reject(reason=RejectionReason.PRESENTATION_ATTACK)
    self._sessions.save(session)
```

### How to actually build the language

1. **Listen to the experts and write down their nouns and verbs.** Do not "improve" their words. If they say *"we settle a claim"*, the method is `Settle()`, not `Finalize()` or `ProcessClosure()`.
2. **Challenge vague words.** When someone says "user", ask: "do you mean *applicant*, *reviewer*, *tenant admin*, or *end customer*?" Vague words hide missing concepts.
3. **Build a glossary** and keep it in the repo, next to the code.
4. **Rename ruthlessly** when the business corrects you. A rename is cheap; a permanent mistranslation is not.
5. **The language is per Bounded Context.** "Policy" means something different in Sales and Claims, and that is correct — do not force one definition across the company. That is the whole point.

**Real payoff:** in a meeting, a domain expert says *"a session can only be re-challenged twice"*. If your code has `session.re_challenge()` and `MAX_RE_CHALLENGES = 2`, that requirement takes 5 minutes. If your code has `updateFlow(type=3, retryCount)`, it takes two days and a misunderstanding.

## 3.3 Bounded Context ⭐ (the most important idea in this book's DDD chapter)

**Definition:** An explicit boundary within which a particular model and language apply consistently.

Inside a Bounded Context: one meaning per word, one model, one team's understanding.
Across contexts: different models, connected by explicit translation.

```
┌──────────────────────────┐        ┌──────────────────────────┐
│   SALES CONTEXT          │        │   CLAIMS CONTEXT         │
│                          │        │                          │
│  Policy                  │        │  Policy                  │
│   - quotedPremium        │        │   - coverageLimits       │
│   - commissionRate       │◄──────►│   - exclusions           │
│   - salesAgent           │  trans │   - deductible           │
│   - conversionDate       │  lation│   - claimHistory         │
│                          │        │                          │
│  Customer = a LEAD       │        │  Customer = a CLAIMANT   │
└──────────────────────────┘        └──────────────────────────┘

Same words. Different models. Both correct. Connected explicitly.
```

### How to find Bounded Context boundaries — five practical signals

1. **Language changes.** When the same word starts meaning something different, you have crossed a boundary. This is the strongest signal.
2. **Different people care.** Sales staff vs claims adjusters vs accountants. Different stakeholders → probably different contexts.
3. **Different rates of change.** The pricing rules change monthly; the document storage rules change yearly.
4. **Different consistency needs.** The ledger must be immediately consistent. The recommendation feed can be a minute stale.
5. **Data ownership.** If you cannot say "this context is the single source of truth for X", the boundary is wrong.

### Bounded Context vs Microservice

Not the same thing, and the distinction matters:

- A **Bounded Context** is a *conceptual/linguistic* boundary
- A **Microservice** is a *deployment* boundary

**Relationship:** one bounded context = **one or more** services. Never split one context across several services (you would split a model that must stay consistent — hello, distributed monolith). You *may* implement several small contexts in one service, especially early on.

> **Rule: a bounded context is the smallest sensible service.** A microservice smaller than a bounded context is almost always a mistake.

### Event Storming — how to find contexts in one workshop 🟡

The most effective practical technique in DDD. You need a wall, sticky notes, and the right people (domain experts + developers) for 2–4 hours.

```
1. ORANGE notes: everyone writes DOMAIN EVENTS (past tense) on the wall.
   "OrderPlaced"  "PaymentCaptured"  "VerificationFailed"  "DocumentExpired"

2. Put them in TIME ORDER, left to right. Arguments will start. Arguments are the point —
   they reveal hidden assumptions and missing knowledge.

3. BLUE notes: what COMMAND caused each event?    "PlaceOrder" → "OrderPlaced"
   YELLOW notes: who/what issued the command?      Actor / system / timer

4. PURPLE notes: business RULES/POLICIES.   "When VerificationFailed 3 times → BlockCustomer"

5. PINK notes: EXTERNAL SYSTEMS.   "Stripe"  "Vendor Face API"  "Sanctions List"

6. Look for CLUSTERS — groups of events that belong together and share language.
   Draw a line around each cluster. THOSE LINES ARE YOUR BOUNDED CONTEXTS.
```

The magic is step 2: putting events in time order in front of domain experts surfaces more requirements in three hours than three weeks of interviews.

## 3.4 Context Map

A Context Map shows **all** your bounded contexts and the **relationship type** between each pair. It is the most useful single diagram an architect can own — far more useful than a boxes-and-lines deployment diagram, because it shows *political and organisational* reality, not just technical wiring.

```
  ┌─────────────────┐       Customer/Supplier      ┌─────────────────┐
  │  Verification   │ ────────────────────────────►│    Billing      │
  │    Context      │      (we publish usage)      │    Context      │
  │   [CORE]        │                              │  [SUPPORTING]   │
  └────────┬────────┘                              └────────┬────────┘
           │                                                │
           │ ACL                                            │ Conformist
           ▼                                                ▼
  ┌─────────────────┐                              ┌─────────────────┐
  │ Vendor Face API │                              │     Stripe      │
  │   [EXTERNAL]    │                              │   [EXTERNAL]    │
  └─────────────────┘                              └─────────────────┘

  ┌─────────────────┐   Shared Kernel (ids, money) ┌─────────────────┐
  │   Identity      │◄────────────────────────────►│   Reviewer      │
  │   Context       │                              │   Console       │
  └─────────────────┘                              └─────────────────┘
```

## 3.5 The integration relationship patterns 🟢

These describe both the **technical** and the **political** relationship between two contexts. Knowing the names lets you have a much more precise conversation.

### 1. Shared Kernel

Two contexts share a small piece of model/code.

```
  Context A ──┐
              ├──► [ Shared Kernel: Money, CustomerId, DateRange ]
  Context B ──┘
```

- ✅ No duplication for genuinely universal concepts
- ❌ **Very tight coupling.** Any change needs agreement from both teams. It becomes a bottleneck.
- **Rule:** keep it tiny (IDs, Money, common value objects) and require both teams to approve changes. If your "shared kernel" contains business logic or entities, it is a liability and it will grow into a distributed monolith. Many experienced architects avoid it entirely.

### 2. Customer/Supplier

Downstream (customer) has real influence; upstream (supplier) agrees to meet their needs.

- Upstream team commits to a contract and a deprecation policy
- Downstream gets a seat in planning
- **Healthy and common** between internal teams. Requires actual organisational agreement, not just good intentions.

### 3. Conformist

Downstream simply accepts the upstream model as-is, with no translation.

- ✅ Zero translation cost, fast to build
- ❌ Their model is now your model; their changes are your emergencies; their bad naming infects your code
- **Use when:** the upstream is a well-designed, stable standard and the relationship is low-risk (e.g. conforming to an OAuth/OIDC token shape). **Avoid when:** the upstream is a messy legacy system.

### 4. Anti-Corruption Layer (ACL) ⭐ 🟢

**The most valuable pattern here.** A translation layer that protects your model from an external model.

```
  ┌──────────────────────┐   ┌─────────────┐   ┌────────────────────────┐
  │  YOUR CLEAN DOMAIN   │   │     ACL     │   │  UGLY EXTERNAL SYSTEM  │
  │                      │   │             │   │                        │
  │  Customer            │◄──┤ translate   ├──►│  CUST_MSTR_REC         │
  │   .Email             │   │             │   │   .EML_ADDR_TXT_1      │
  │   .VerifiedAt        │   │             │   │   .VRFY_DT_STR "20260912"│
  │   .Status: Verified  │   │             │   │   .STAT_CD: "V"         │
  └──────────────────────┘   └─────────────┘   └────────────────────────┘
```

```python
# ── Your domain: clean, meaningful ──
@dataclass(frozen=True)
class VerifiedIdentity:
    full_name: str
    date_of_birth: date
    document_number: str
    verified_at: datetime
    confidence: Confidence          # a value object with real rules

# ── The ACL: the ONLY place that knows the vendor exists ──
class AcmeVendorAntiCorruptionLayer:
    """Translates Acme's model into ours. Nothing else imports acme_sdk."""

    def __init__(self, client: AcmeClient):
        self._client = client

    async def verify(self, document: DocumentImage) -> VerifiedIdentity:
        try:
            raw = await self._client.doc_check_v3(
                img=base64.b64encode(document.bytes).decode(),
                opts={"lvl": 2, "rtn": "full"},
            )
        except AcmeTimeout as e:                       # vendor exceptions stop here
            raise VerificationUnavailable("vendor timeout") from e
        except AcmeRateLimit as e:
            raise VerificationThrottled(retry_after=e.retry_after) from e

        if raw.get("st") != "OK":                      # vendor's weird status codes stop here
            raise VerificationRejected(self._map_reason(raw.get("err_cd")))

        return VerifiedIdentity(                        # OUR model comes out
            full_name=f"{raw['fn']} {raw['ln']}".strip(),
            date_of_birth=datetime.strptime(raw["dob"], "%Y%m%d").date(),
            document_number=raw["doc_no"],
            verified_at=datetime.now(timezone.utc),
            confidence=Confidence.from_percent(raw["conf_pct"]),   # 0-100 → our 0-1
        )

    @staticmethod
    def _map_reason(vendor_code: str | None) -> RejectionReason:
        return {
            "E41": RejectionReason.DOCUMENT_EXPIRED,
            "E42": RejectionReason.DOCUMENT_TAMPERED,
            "E55": RejectionReason.FACE_MISMATCH,
        }.get(vendor_code or "", RejectionReason.UNKNOWN)
```

**What the ACL buys you:**
- Vendor changes touch **one file**
- Switching vendors is a new ACL, not a rewrite
- Vendor weirdness (status codes, date formats, 0–100 scales, odd exceptions) never reaches your business logic
- You can test your domain with a fake ACL

> **Rule: put an ACL in front of every external system and every legacy system. Every time. This is non-negotiable for a professional integration.**

### 5. Open Host Service (OHS)

You are upstream and many contexts consume you, so you publish a **well-designed, general-purpose public API** rather than bespoke integrations per consumer.

Sign you need it: you are writing your fourth "special endpoint for team X".

### 6. Published Language

A **shared, well-documented format** for exchanging information between contexts — JSON Schema, OpenAPI, Protobuf, Avro, or an industry standard (FHIR in healthcare, ISO 20022 in payments, FpML in finance).

OHS + Published Language together = "here is our public API and here is the documented, versioned schema of everything it speaks."

### 7. Separate Ways

The two contexts have **no** integration. Sometimes duplicating a small amount of functionality is cheaper than integrating.

Do not be embarrassed by this. If integrating costs 3 months and duplicating costs 3 days, duplicate. Integration is not free.

### 8. Partnership

Two teams succeed or fail together; they coordinate releases and plan jointly. Honest and workable for two teams; unmanageable for ten.

### 9. Big Ball of Mud

A named pattern for "this region has no discernible model". Marking it on the map is valuable: it tells everyone *"put an ACL here and do not try to understand it."*

---

# PART 2 — Tactical DDD 🟢

The building blocks inside one bounded context.

## 3.6 Entity

**Definition:** An object defined by its **identity**, not its attributes. It has a lifecycle, and it changes over time.

**Real life:** You. Your name, address, weight and hairstyle can all change — you are still the same person. Identified by a national ID, not by your attributes.

```csharp
public class VerificationSession                // ENTITY: identified by Id
{
    public SessionId Id { get; }                // identity — never changes
    public CustomerId CustomerId { get; }
    public SessionStatus Status { get; private set; }   // attributes change
    private readonly List<Attempt> _attempts = new();

    // Two sessions are equal if their IDs are equal — nothing else matters
    public override bool Equals(object? obj) => obj is VerificationSession s && s.Id == Id;
    public override int GetHashCode() => Id.GetHashCode();
}
```

**Key practices:**
- **No public setters.** Change happens through meaningful methods: `session.Approve(reviewerId)`, not `session.Status = "approved"`. Setters let callers put the object into an invalid state.
- Equality is by **ID only**
- The entity **protects its own invariants** — it should be impossible to construct or mutate an invalid one

## 3.7 Value Object

**Definition:** An object defined entirely by its **values**. No identity. Immutable. Interchangeable.

**Real life:** A ₹500 note. Any ₹500 note is as good as any other. You do not track *which* note.

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
            throw new InvalidEmailException(value);      // INVALID CANNOT EXIST
        Value = value.Trim().ToLowerInvariant();         // normalised on creation
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

### Why value objects are a huge quality win

**Before (primitive obsession):**

```csharp
public void Transfer(string from, string to, decimal amount, string currency) { }
Transfer(toAccount, fromAccount, 100, "USD");        // arguments swapped — COMPILES FINE
Transfer(from, to, -50, "US Dollars");               // negative, bad currency — COMPILES FINE
```

**After:**

```csharp
public void Transfer(AccountNumber from, AccountNumber to, Money amount) { }
Transfer(to, from, money);                           // COMPILE ERROR? no - but types match
// however: Money(-50, "US Dollars") throws at CONSTRUCTION. Invalid state cannot exist.
```

> **Rule of thumb:** if a concept has rules (an email has a format, a score has a range, money has a currency), it deserves a value object. Replacing `string`/`decimal` with value objects eliminates entire categories of bug, and it moves validation from "scattered `if`s in controllers" to "one place, enforced by the type system".

**Also:** value objects are immutable (Chapter 01), so they are thread-safe, cacheable and safe to share.

## 3.8 Aggregate and Aggregate Root ⭐

**The single hardest and most valuable tactical concept.**

**Definition:** An aggregate is a cluster of entities and value objects that is treated as **one unit for data changes**. One entity is the **Aggregate Root** — the only member that outside code may hold a reference to.

**Real life:** An order and its lines. You never edit an order line in isolation — "add this line" is an operation on the *order*, because the order's total, discount and minimum-value rules depend on the lines.

```
  ┌──────── AGGREGATE BOUNDARY ─────────────────────┐
  │                                                 │
  │   ┌──────────────────┐  ← AGGREGATE ROOT        │
  │   │      Order       │    (the only public door)│
  │   │  - Id            │                          │
  │   │  - Status        │                          │
  │   │  - Total         │                          │
  │   └────────┬─────────┘                          │
  │            │ owns                               │
  │   ┌────────▼─────────┐   ┌──────────────────┐   │
  │   │   OrderLine[]    │   │ ShippingAddress  │   │
  │   │   (entities)     │   │ (value object)   │   │
  │   └──────────────────┘   └──────────────────┘   │
  └─────────────────────────────────────────────────┘
              ▲
              │  outside code may ONLY touch Order,
              │  and may only reference OTHER aggregates BY ID
         CustomerId (just an ID, not a Customer object)
```

### The five rules of aggregates

**1. The root is the only entry point.** Outside code never holds a reference to an internal entity.

```csharp
// WRONG — the collection is exposed and mutable; invariants can be bypassed
public List<OrderLine> Lines { get; set; }
order.Lines.Add(new OrderLine(...));       // total not recalculated, rules not checked

// RIGHT
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

    RecalculateTotal();                              // invariant maintained, always
}
```

**2. The aggregate is the transaction and consistency boundary.** Everything inside is consistent immediately, after every operation. Nothing outside is.

**3. Reference other aggregates by ID only.**

```csharp
// WRONG — object reference across aggregates
public class Order { public Customer Customer { get; set; } }
// now loading an order loads a customer, which loads their orders, which... 

// RIGHT
public class Order { public CustomerId CustomerId { get; } }
```

This one rule prevents the "load one object, drag half the database into memory" disaster, and it keeps aggregate boundaries real rather than decorative.

**4. One transaction = one aggregate.** If a business operation must change two aggregates, use **eventual consistency** via a domain event, not a single big transaction.

```csharp
// WRONG — two aggregates in one transaction
order.Submit();
customer.IncrementOrderCount();      // different aggregate!
await _uow.SaveChangesAsync();

// RIGHT — order raises an event; a handler updates the customer separately
order.Submit();                      // raises OrderSubmitted
await _uow.SaveChangesAsync();
// → handler for OrderSubmitted updates Customer in its own transaction
```

**Why?** Because the multi-aggregate transaction is what stops you scaling, and it is what makes extracting a service impossible later. Obeying this rule inside a monolith is what makes a future split cheap.

**5. Keep aggregates small.** The classic failure is a `Customer` aggregate containing all their orders. A customer with 10,000 orders becomes unloadable, and every order change locks the whole customer.

### How to decide the boundary — the invariant test

> **Ask: "What rule must be true at every single instant, with no delay allowed?"**
> Everything that rule touches must be inside one aggregate. Everything else goes outside.

Examples:

| Invariant | Implication |
|-----------|-------------|
| "Order total must equal the sum of its lines" | Lines are **inside** the Order aggregate |
| "A customer cannot have more than 5 active orders" | Is a 1-second delay acceptable? Almost always **yes** → separate aggregates + eventual consistency. If genuinely not (regulatory), you need a different design (a reservation, or a single aggregate). |
| "A session may have at most 3 attempts" | Attempts are **inside** the Session aggregate |
| "Total company spend must not exceed the budget" | Under concurrency this needs care — consider a dedicated `Budget` aggregate with reservations, not a `SUM()` check |

**Challenge every invariant with: "what if this is true only after 2 seconds?"** Business people usually say "fine". When they say "fine", you get a smaller aggregate, better concurrency, and an easier future split.

### Concurrency and aggregates

Because the aggregate is the consistency boundary, it is also the **locking** boundary. Use **optimistic concurrency**: a version column on the root.

```csharp
// EF Core
public class Order
{
    [Timestamp] public byte[] RowVersion { get; private set; } = default!;
}
// Two users edit the same order → second SaveChanges throws DbUpdateConcurrencyException
```

Small aggregates → fewer conflicts. That is another reason rule 5 matters.

## 3.9 Repository (in DDD terms)

Covered mechanically in Chapter 01. The DDD rules:

- **One repository per aggregate root.** Never one per table, never one per internal entity.
- It returns **fully-formed aggregates** with their invariants intact
- It speaks the **ubiquitous language**: `GetActiveSessionsAwaitingReview()`, not `SelectWhereStatusIn(1,2)`

## 3.10 Domain Service

**Definition:** Business logic that does not naturally belong to any single entity or value object.

**Signal:** you have a rule involving two or more aggregates, or an operation that is a *process* rather than a *thing*.

```python
# Which entity should own "does this face match this document photo?"
# Neither Session nor Document alone. So: a domain service.
class FaceMatchingPolicy:                # DOMAIN service: pure rules, no I/O
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

**Critical distinction (people constantly confuse these):**

| | Domain Service | Application Service |
|---|---|---|
| **Contains** | Business rules | Orchestration |
| **Does I/O?** | **Never** | Yes — repos, HTTP, queues |
| **Transactions?** | No | Yes, it owns the transaction |
| **Testable without infra?** | Always | With fakes |
| **Example** | `FaceMatchingPolicy.decide()` | `VerificationService.verify()` |

> If your "domain service" has a repository injected, it is probably an application service wearing the wrong hat. That is fine — just name it correctly and put it in the right layer.

## 3.11 Factory

When creating an aggregate is complex (many invariants, or assembly from parts), put the logic in a factory — a static method on the aggregate, or a separate factory class.

```csharp
public class VerificationSession
{
    private VerificationSession() { }   // no public constructor — creation is controlled

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

Benefits: you cannot create an invalid session; the creation rules live in one place; the event is raised automatically.

## 3.12 Domain Event

Covered in Chapter 01 mechanically. In DDD terms:

- A domain event is a **fact that domain experts care about** — if the business would not say it out loud, it is probably not a domain event
- Named in **past tense**, in the **ubiquitous language**: `VerificationPassed`, `PolicyRenewed`, `ClaimSettled`
- Raised **by the aggregate**, dispatched by the infrastructure
- They are the mechanism for **eventual consistency between aggregates** (aggregate rule 4)
- They are often the natural **integration events** between bounded contexts — but be careful: an internal domain event and a published integration event should usually be **different types**, because publishing your internal model couples other contexts to it.

```csharp
// INTERNAL domain event — rich, tied to our model, may change freely
internal record VerificationPassed(SessionId Id, LivenessScore Score, VendorDetail Detail);

// PUBLISHED integration event — stable, versioned, deliberately minimal
public record CustomerVerifiedV1(string CustomerId, string SessionId, DateTime VerifiedAt);
```

---

## 3.13 Putting it together: a worked example

**Business:** A KYC platform. Let us model one bounded context properly.

```
BOUNDED CONTEXT: Verification

Ubiquitous language glossary:
  Session      — one customer's attempt to prove identity, time-limited
  Attempt      — one submission of video within a session
  Challenge    — an action we ask the user to perform (turn left, blink)
  Signals      — raw measurements from the engine (score, spoof flags, pose)
  Outcome      — the final Passed / Failed / ManualReview decision
  Reviewer     — a human who adjudicates a ManualReview outcome
```

```python
# ── VALUE OBJECTS ────────────────────────────────────────────────
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
class Attempt:                       # entity inside the aggregate (local identity)
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
        self.customer_id = customer_id          # OTHER aggregate, by ID only
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

    # ---- BEHAVIOUR (invariants enforced here, nowhere else) ----
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

Notice what this code has:

- **No database. No HTTP. No framework.** It runs in a unit test in microseconds.
- Every business rule is **visible in one file**, in business language
- Invalid states are **impossible** — you cannot record a 4th attempt, or conclude twice
- It produces **events** that other contexts can react to
- A compliance officer could read `record_attempt` and confirm the policy

That is the payoff of tactical DDD.

---

## 3.14 When NOT to use DDD

Be honest — DDD is expensive.

❌ **Do not use full DDD when:**
- The domain is simple CRUD (a contact list, a CMS). Rich aggregates for a form is pure ceremony.
- There is no access to domain experts (DDD *requires* the conversation; without it you invent a fake model)
- The team has no appetite to learn it — half-applied DDD is worse than none
- The system is short-lived (a 3-month campaign site)
- It is a technical utility, not a business domain (a logging library has no ubiquitous language)

✅ **Always use the strategic parts** (subdomain classification, bounded contexts, context map, ACL) — they are cheap and they pay off on **any** project of any size.

🟡 **Add tactical parts selectively** — use rich aggregates in your **core subdomain**, and simple CRUD in generic/supporting ones. Mixing styles within one system is not inconsistency; it is proportionate engineering.

---

## 3.15 Common mistakes

1. **"DDD = folder structure"** — creating `Domain/`, `Application/`, `Infrastructure/` folders and calling it DDD, while the code inside is anemic CRUD
2. **Anemic domain model** — entities with only getters and setters; all rules in services. The most common DDD failure by far.
3. **Huge aggregates** — `Customer` containing all orders, all addresses, all invoices. Unloadable, unlockable.
4. **Object references between aggregates** — leads to loading half the DB and to unclear boundaries
5. **Multi-aggregate transactions** — quietly destroys the ability to scale or split later
6. **One model for the whole company** — ignoring bounded contexts, building the 80-field `Policy`
7. **No ACL against a legacy/vendor system** — their model infects yours permanently
8. **Ignoring the domain experts** — inventing the language yourself; you will be subtly wrong everywhere
9. **Tactical DDD in generic subdomains** — a lovingly crafted aggregate for the email-preferences screen
10. **Shared kernel that grows** — starts as `Money`, ends as half the domain, and now two teams cannot move

---

## 3.16 Architect's checklist

- [ ] Are subdomains listed and classified as Core / Supporting / Generic?
- [ ] Does engineering effort actually match that classification?
- [ ] Are bounded contexts identified, with a written glossary per context?
- [ ] Is there a context map showing the relationship type between each pair?
- [ ] Does every external/legacy system have an ACL?
- [ ] Is each piece of data owned by exactly **one** context?
- [ ] For each aggregate: what invariant justifies its boundary?
- [ ] Does any transaction touch more than one aggregate?
- [ ] Do aggregates reference each other by ID only?
- [ ] Can the domain model be unit-tested with no infrastructure?
- [ ] Do class and method names match what domain experts say out loud?
- [ ] Are internal domain events separated from published integration events?

---

## 3.17 Self-test

1. Why do three departments needing "Policy" not mean you need one `Policy` class?
2. Classify these for a ride-hailing company: pricing/surge algorithm, driver payouts, email sending, matching riders to drivers, tax invoicing.
3. What is the relationship between a Bounded Context and a Microservice?
4. Give five practical signals that you have crossed a context boundary.
5. Explain Event Storming in six steps. What is the purpose of the arguments it causes?
6. Entity vs Value Object — give two examples of each from a domain you know.
7. State the five rules of aggregates.
8. What is "the invariant test" for finding an aggregate boundary?
9. Why must you reference other aggregates by ID rather than by object reference?
10. A business rule spans two aggregates. How do you implement it?
11. Domain Service vs Application Service — state the deciding difference.
12. When should you *not* use DDD?

---

## 3.18 Key takeaways

- **The same word means different things in different parts of a business** — this is the founding insight
- **Bounded Contexts are your service boundaries.** Get them right before anything else
- **Classify subdomains** — build Core, buy Generic. Check where your hours actually go
- **Ubiquitous Language** — your code should be readable by a domain expert
- **ACL in front of every external and legacy system.** Every time.
- **Aggregates = consistency + transaction + locking boundary.** Keep them small, reference by ID, one per transaction
- **Value objects kill primitive obsession** and make invalid states impossible
- **Strategic DDD is cheap and always worth it. Tactical DDD is expensive — spend it on your core domain.**
- **Anemic domain model** is the most common way DDD projects fail

---

**Next:** [Chapter 04 — System Design Fundamentals](04-system-design-fundamentals.md)
