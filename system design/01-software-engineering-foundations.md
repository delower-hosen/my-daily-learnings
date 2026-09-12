# Chapter 01 — Software Engineering Foundations 🟢

> Architecture at the level of a single codebase.
> If the code inside a service is a swamp, no amount of clean boxes-and-arrows on a diagram will save you.

This chapter has three parts:

1. **Code-level architecture** — principles (SOLID, DRY, coupling, cohesion)
2. **Design patterns** — the classic Gang of Four catalogue
3. **Enterprise patterns** — Repository, Unit of Work, CQRS, Domain Events

---

# PART 1 — Code-level architecture 🟢

## 1.1 The two words that explain everything: Coupling and Cohesion

Before SOLID, before patterns, there are two words. Every other principle in this chapter exists to serve these two.

### Coupling — how much one thing depends on another

**Real life:** Think of Christmas lights, the old kind. One bulb burns out and the whole string goes dark. That is **tight coupling**. Modern LED strings where each bulb is independent — **loose coupling**.

**In code:**

```csharp
// TIGHT COUPLING — OrderService is welded to SQL Server and SMTP
public class OrderService
{
    public void PlaceOrder(Order order)
    {
        var conn = new SqlConnection("Server=prod-01;Database=Shop;...");
        conn.Open();
        // ... raw SQL here ...

        var smtp = new SmtpClient("smtp.gmail.com");
        smtp.Send(new MailMessage("shop@x.com", order.Email, "Thanks!", "..."));
    }
}
```

What is wrong?

- You cannot test it without a real database and a real mail server
- You cannot move to PostgreSQL without editing business logic
- You cannot switch to SendGrid without editing business logic
- The class knows about *connection strings*, which is not its job

```csharp
// LOOSE COUPLING — depends on ideas, not on products
public class OrderService
{
    private readonly IOrderRepository _orders;
    private readonly INotificationSender _notifier;

    public OrderService(IOrderRepository orders, INotificationSender notifier)
    {
        _orders = orders;
        _notifier = notifier;
    }

    public async Task PlaceOrderAsync(Order order)
    {
        await _orders.SaveAsync(order);
        await _notifier.SendAsync(order.Email, "Thanks!", $"Order {order.Id} received.");
    }
}
```

Now you can swap SQL Server for Postgres, SMTP for SendGrid, and test with fakes — **without touching the business rule**.

### The coupling scale (memorise the direction)

From worst to best:

| Level | Description | Example |
|-------|-------------|---------|
| **Content coupling** (worst) | One module reaches into another's internals | Reading another service's database table directly |
| **Common coupling** | Shared global state | Global mutable singleton, shared config object everyone mutates |
| **Control coupling** | Passing a flag that controls the other's logic | `Process(data, isRefund: true)` |
| **Stamp coupling** | Passing a whole object when only one field is needed | `SendEmail(customer)` when you only need `customer.Email` |
| **Data coupling** (good) | Passing only the data needed | `SendEmail(string emailAddress)` |
| **Message coupling** (best) | Communicating through events/messages, no direct knowledge | Publishing `OrderPlaced` and not knowing who listens |

> **Architect's translation:** the higher you are on this list, the more things break when you change something.

### Afferent and Efferent coupling (the words that show up in tools)

- **Afferent coupling (Ca)** = how many things depend on **me**. High Ca = I am important; changing me is dangerous.
- **Efferent coupling (Ce)** = how many things **I** depend on. High Ce = I am fragile; others break me.
- **Instability (I) = Ce / (Ca + Ce)** — between 0 (rock solid) and 1 (very unstable)

Rule of thumb: **stable things should not depend on unstable things.** Your domain model should be stable (high Ca, low Ce). Your controllers and adapters should be unstable (low Ca, high Ce). If your domain imports your web framework, you have it backwards.

### Cohesion — how much the things inside one module belong together

**Real life:** A kitchen drawer with knives, forks and spoons = **high cohesion** (all cutlery). A drawer with forks, batteries, tape, a passport and one sock = **low cohesion**. When you need something, you have no idea where to look.

```python
# LOW COHESION — this class does five unrelated things
class Utils:
    def calculate_tax(self, amount): ...
    def send_email(self, to, body): ...
    def resize_image(self, path): ...
    def parse_csv(self, file): ...
    def validate_passport(self, doc): ...
```

Anything named `Utils`, `Helper`, `Common`, `Manager`, or `Shared` is almost always a cohesion failure. It is a junk drawer.

```python
# HIGH COHESION — each class has one reason to exist
class TaxCalculator:
    def calculate(self, amount, region): ...
    def calculate_with_exemptions(self, amount, region, exemptions): ...

class ImageResizer:
    def resize(self, image, width, height): ...
    def thumbnail(self, image): ...
```

### The goal, in one line

> **Low coupling, high cohesion.**
> Things that change together should live together. Things that do not, should not know about each other.

Everything else in this chapter is a technique for achieving that sentence.

---

## 1.2 SOLID — five principles

SOLID is five rules that keep object-oriented code flexible. People over-quote them and under-understand them, so let us make each one concrete.

### S — Single Responsibility Principle (SRP)

**Common (wrong) statement:** "A class should do only one thing."
**Correct statement:** *"A class should have only one reason to change."* — or better, **"one actor it answers to."**

**Real life:** A restaurant. The chef cooks. The waiter serves. The cashier takes money. If one person did all three, then a change in the menu, the seating plan, *and* the tax law all disturb the same person.

```csharp
// VIOLATION — this class answers to three different departments
public class Employee
{
    public decimal CalculatePay()  { ... }   // changes when FINANCE changes rules
    public void SaveToDatabase()   { ... }   // changes when DBA/IT changes storage
    public string ReportHours()    { ... }   // changes when HR changes report format
}
```

Three actors (Finance, IT, HR) → three reasons to change → it will be edited constantly, by people who do not understand each other's parts, and they will break each other.

```csharp
// FIXED
public class Employee { /* data + domain rules only */ }
public class PayCalculator     { public decimal Calculate(Employee e) { ... } }
public class EmployeeRepository{ public void Save(Employee e)        { ... } }
public class HourReporter      { public string Report(Employee e)    { ... } }
```

**How to spot violations:**
- The class name has "And" in it, or could
- The word `Manager`/`Processor`/`Handler` with 900 lines
- Different teams keep touching the same file for unrelated reasons
- A test file that needs 12 different mocks

**Do not overdo it.** SRP taken to the extreme gives you 400 one-method classes and nobody can find anything. The unit of measurement is the **actor/reason to change**, not the number of methods.

### O — Open/Closed Principle (OCP)

*"Software entities should be open for extension, but closed for modification."*

Plain English: **you should be able to add new behaviour without editing existing, tested code.**

**Real life:** A power socket. To add a new device you do not rewire the house — you plug it in. The socket is *closed* (you do not modify it) and *open* (any device can extend it).

```python
# VIOLATION — every new payment method means editing this function
def process_payment(payment_type, amount):
    if payment_type == "card":
        # 30 lines
    elif payment_type == "bkash":
        # 30 lines
    elif payment_type == "paypal":
        # 30 lines
    # next month: elif "nagad" ... and you re-test everything
```

```python
# FIXED — Strategy pattern
from abc import ABC, abstractmethod

class PaymentMethod(ABC):
    @abstractmethod
    def pay(self, amount: Money) -> PaymentResult: ...

class CardPayment(PaymentMethod):
    def pay(self, amount): ...

class BkashPayment(PaymentMethod):
    def pay(self, amount): ...

class NagadPayment(PaymentMethod):   # NEW FILE. Nothing else changed.
    def pay(self, amount): ...

class PaymentProcessor:
    def __init__(self, methods: dict[str, PaymentMethod]):
        self._methods = methods

    def process(self, method_key: str, amount: Money) -> PaymentResult:
        return self._methods[method_key].pay(amount)
```

**The honest caveat:** you cannot make everything open for extension. You would drown in abstraction. Apply OCP where you have *evidence* that variation happens — payment methods, notification channels, tax rules, document types, file formats. If you have edited the same `if/elif` chain twice, that is your evidence.

### L — Liskov Substitution Principle (LSP)

*"If S is a subtype of T, objects of type T may be replaced with objects of type S without breaking the program."*

Plain English: **a child class must be usable anywhere the parent is expected, without surprises.**

**Real life:** A "coffee machine" that, when you press *brew*, sends an email instead. It technically implements the interface. It is not substitutable.

The classic example:

```csharp
public class Rectangle
{
    public virtual int Width  { get; set; }
    public virtual int Height { get; set; }
    public int Area => Width * Height;
}

public class Square : Rectangle   // "a square IS a rectangle" — mathematically true
{
    public override int Width  { set { base.Width = base.Height = value; } }
    public override int Height { set { base.Width = base.Height = value; } }
}

// Caller written against Rectangle:
void Test(Rectangle r)
{
    r.Width = 5;
    r.Height = 4;
    Assert.Equal(20, r.Area);   // PASSES for Rectangle, FAILS for Square (16)
}
```

The code compiles. The logic is silently wrong. **Inheritance modelled "is-a" in the real world, but broke behaviour in the program.**

**Common LSP violations in real systems:**

```python
class Bird:
    def fly(self): ...

class Penguin(Bird):
    def fly(self):
        raise NotImplementedError("Penguins can't fly")  # LSP violation
```

```csharp
// A read-only collection that throws on Add(), pretending to be IList<T>
public class ReadOnlyList<T> : IList<T>
{
    public void Add(T item) => throw new NotSupportedException(); // violation
}
```

**How to obey LSP:**
- A subclass must not **strengthen preconditions** (require more than the parent did)
- A subclass must not **weaken postconditions** (promise less than the parent did)
- A subclass must not **throw new exception types** the caller does not expect
- Invariants of the parent must still hold

**Practical rule:** if you need `if (x is SubType)` in the caller, LSP is already broken. And when in doubt, **prefer composition over inheritance** (see 1.6).

### I — Interface Segregation Principle (ISP)

*"No client should be forced to depend on methods it does not use."*

**Real life:** A TV remote with 60 buttons when you only ever use 4. Worse: every time the manufacturer adds a button, you have to buy a new remote.

```csharp
// VIOLATION — a fat interface
public interface IWorker
{
    void Work();
    void Eat();
    void Sleep();
    void AttendMeeting();
    void SubmitTimesheet();
}

public class RobotWorker : IWorker
{
    public void Work() { ... }
    public void Eat()   => throw new NotSupportedException();  // smell
    public void Sleep() => throw new NotSupportedException();  // smell
    // ...
}
```

```csharp
// FIXED — small, role-based interfaces
public interface IWorkable      { void Work(); }
public interface IFeedable      { void Eat(); }
public interface IReportable    { void SubmitTimesheet(); }

public class HumanWorker : IWorkable, IFeedable, IReportable { ... }
public class RobotWorker : IWorkable { ... }
```

**Real-world ISP win:** In a liveness/KYC system, do not create one `IVerificationVendor` with 15 methods (`DetectFace`, `MatchFace`, `ReadPassportMRZ`, `CheckSanctionsList`, `EstimateAge`, …). No vendor implements all 15. Create `IFaceDetector`, `IFaceMatcher`, `IDocumentReader`, `ISanctionsScreener` — then compose whichever vendors you use for each capability. When you switch document vendors, the face code does not move.

### D — Dependency Inversion Principle (DIP)

*"High-level modules should not depend on low-level modules. Both should depend on abstractions. Abstractions should not depend on details; details should depend on abstractions."*

This is the most architecturally important letter. It is the foundation of Hexagonal, Onion and Clean Architecture (Chapter 02).

**Real life:** A lamp does not have its wires soldered directly to the power station. Both the lamp and the power system agree on an **abstraction** — the plug and socket standard. Either side can change independently.

```
WITHOUT DIP (dependency follows control flow — bad)

   [ Business Logic ]
           │ depends on
           ▼
   [ SqlServerRepository ]          ← business logic knows about SQL Server


WITH DIP (dependency is inverted — good)

   [ Business Logic ]
           │ depends on
           ▼
   [ IOrderRepository ]  ◄────── implements ────── [ SqlServerRepository ]

   Note the arrow direction: the DETAIL points at the ABSTRACTION.
```

**Critical subtlety that most people get wrong:** the interface belongs to the **high-level module**, not to the low-level one. `IOrderRepository` lives in your *domain/application* project, not in your *infrastructure* project. That is what makes it an inversion. If you put the interface next to the SQL implementation, you have just added a useless layer of indirection and inverted nothing.

```
MyApp.Domain/
    Order.cs
    IOrderRepository.cs          ← interface lives HERE (with the business)
MyApp.Infrastructure/
    SqlOrderRepository.cs        ← implementation lives here, and references Domain
```

The dependency arrow at build time now points **inward**, toward the business. You can delete the entire Infrastructure project and the Domain still compiles. That is the test.

### SOLID summary card

| Letter | One line | Smell it fixes |
|--------|----------|----------------|
| **S** | One reason to change | God classes, `Utils` |
| **O** | Extend without editing | Growing `if/elif` chains |
| **L** | Subtypes must not surprise | `NotImplementedException`, `is SubType` checks |
| **I** | Small, role-based interfaces | Fat interfaces, unused methods |
| **D** | Depend on abstractions you own | Business logic importing SDKs and drivers |

---

## 1.3 DRY — Don't Repeat Yourself

*"Every piece of knowledge must have a single, unambiguous, authoritative representation within a system."*

Notice the word **knowledge**. DRY is **not** about identical-looking text.

```csharp
// These look identical. They are NOT duplication.
public bool IsEligibleForDiscount(Customer c) => c.Age > 60;
public bool CanAccessSeniorLounge(Customer c) => c.Age > 60;
```

Two different business rules that happen to have the same threshold today. If you "DRY" them into `IsOver60()`, then the day marketing changes the discount age to 55 but the lounge stays at 60, you get a bug and an awkward refactor.

### The danger: wrong abstraction is worse than duplication

> **"Duplication is far cheaper than the wrong abstraction."** — Sandi Metz

The failure sequence is so common it has a shape:

1. Two pieces of similar code appear
2. Someone extracts a shared function
3. A new requirement makes case A slightly different → add a boolean parameter
4. Another difference → another parameter
5. Six months later: `process(data, isRefund, skipTax, legacyMode, forCorporate, dryRun)`
6. Nobody can change it safely; everyone is afraid of it

**Practical rule (the Rule of Three):** Do not abstract on the second occurrence. Wait for the third. By then you can see the *shape* of the real abstraction.

### Where DRY matters most (real knowledge duplication)

- **Business rules** — VAT rate, retry limits, password policy, fraud thresholds
- **Validation rules** — duplicated on frontend and backend is *accepted duplication* (different reasons: UX vs security), but they must be derived from one source where possible (shared schema/contract)
- **Configuration** — a URL in 5 config files
- **Database schema knowledge** — table shape hard-coded in 10 places instead of one mapping/model
- **API contracts** — generate clients from OpenAPI/proto rather than hand-writing them

### WET, AHA and the modern view

- **WET** = "Write Everything Twice" (the joking counterpart to DRY)
- **AHA** = "Avoid Hasty Abstractions" — the best modern advice. *Prefer duplication over the wrong abstraction; optimise for change, not for fewer lines.*

---

## 1.4 KISS and YAGNI

### KISS — Keep It Simple, Stupid

The simplest solution that fully solves the problem is usually the right one.

**Real example.** A team needed to run a task once per day.

- **Their build:** Kafka topic + scheduler service + a state machine in Redis + a retry orchestrator + a Kubernetes CronJob controller they wrote themselves. Six weeks.
- **What was needed:** a cron entry calling a script, with a lock row in Postgres so two instances don't collide. One afternoon.

The first team had fun. The second team shipped the product.

**The simplicity test:** *Can a new developer understand this in 15 minutes?* If not, justify the complexity explicitly — or remove it.

Careful: *simple* ≠ *easy* and *simple* ≠ *few lines*. Rich Hickey's distinction is worth knowing: **simple = not intertwined** (few concepts, cleanly separated). **Easy = familiar/near at hand**. A clever one-liner is often easy to write and complex to understand. Aim for *simple*.

### YAGNI — You Aren't Gonna Need It

Do not build for a requirement that does not exist yet.

```csharp
// YAGNI violation — we support one currency; nobody asked for these
public interface ICurrencyConverter { ... }
public class MultiCurrencyPricingEngine { ... }
public class ExchangeRateProviderFactory { ... }
public class HistoricalRateCache { ... }
```

Two years later the company is still in one country, and every developer has to read those four classes to change a price.

**The cost of speculative generality:**
1. You build the wrong thing (you guessed the future, and you were wrong)
2. You pay maintenance on it forever
3. You slow down every reader of the code
4. The real requirement, when it finally arrives, does not fit your guess anyway

### But YAGNI has limits — where you MUST think ahead

YAGNI applies to **features**, not to **architecture that is expensive to change** (Chapter 00).

| Do apply YAGNI | Do NOT apply YAGNI |
|----------------|--------------------|
| Multi-currency, multi-tenant, plugin systems | Security — bolted on later, it is always broken |
| Configurable workflow engines | Primary key strategy |
| "We might support GraphQL later" | Data model & entity relationships |
| Extra microservices "for future scale" | Audit logging if you are regulated |
| A caching layer nobody measured a need for | Where PII is stored (it spreads, and you cannot un-spread it) |
| Abstracting over 2 databases you use 1 of | Basic observability (log/metric/trace hooks) |

> The dividing line is the Chapter 00 definition: **if it is cheap to add later, YAGNI it. If it is expensive to retrofit, do it now.**

---

## 1.5 Separation of Concerns

A **concern** is one area of interest: persistence, validation, business rules, presentation, logging, security.

**Real life:** a hospital. Reception, diagnosis, surgery, pharmacy, billing. Each is a concern with its own experts and its own room. You do not want the surgeon also handling insurance paperwork in the middle of an operation.

```python
# EVERYTHING MIXED — this is the most common real-world code shape
@app.post("/verify")
def verify(request):
    # presentation
    data = request.json
    # validation
    if not data.get("video"):
        return {"error": "video required"}, 400
    # business rule
    if len(data["video"]) > 5_000_000:
        return {"error": "too big"}, 400
    # persistence
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (...) VALUES (...)")
    # integration
    r = requests.post("https://vendor.ai/detect", files={"v": data["video"]})
    # business rule again
    score = r.json()["score"]
    passed = score > 0.85          # <-- the actual product, buried on line 16
    # persistence again
    cur.execute("UPDATE sessions SET score=%s, passed=%s", (score, passed))
    conn.commit()
    # presentation
    return {"passed": passed, "score": score}
```

That last function is untestable without a database, a vendor account and an HTTP server. And the one line that is actually your product (`score > 0.85`) is invisible.

```python
# SEPARATED
# --- presentation layer (thin!) ---
@app.post("/verify")
async def verify(req: VerifyRequest, svc: VerificationService = Depends()):
    result = await svc.verify(req.session_id, req.video)
    return VerifyResponse.from_domain(result)

# --- application layer: orchestration only ---
class VerificationService:
    def __init__(self, detector: FaceDetector, repo: SessionRepository):
        self._detector = detector
        self._repo = repo

    async def verify(self, session_id: SessionId, video: VideoData) -> Verification:
        session = await self._repo.get(session_id)
        signals = await self._detector.analyse(video)
        session.record_attempt(signals)      # <-- domain decides pass/fail
        await self._repo.save(session)
        return session.latest_result()

# --- domain layer: the actual product, no I/O, pure and testable ---
class LivenessSession:
    PASS_THRESHOLD = 0.85
    MAX_ATTEMPTS = 3

    def record_attempt(self, signals: Signals) -> None:
        if self._attempts >= self.MAX_ATTEMPTS:
            raise TooManyAttempts(self.id)
        passed = signals.liveness_score > self.PASS_THRESHOLD and not signals.spoof_detected
        self._results.append(Result(signals, passed))
        self._attempts += 1
```

Now the business rule is one small class you can unit-test in microseconds, with no infrastructure at all. **That is the payoff.**

### Cross-cutting concerns

Some concerns cut across *every* layer: logging, authentication, authorisation, caching, transactions, retries, metrics, validation.

If you paste them into every method, you get noise. Techniques to keep them out of business code:

- **Middleware / filters / pipeline behaviours** (ASP.NET middleware, FastAPI dependencies, MediatR behaviours)
- **Decorators** (wrap a service in a logging or caching decorator — see 1.8)
- **Aspect-Oriented Programming (AOP)** — interceptors, attributes (`[Authorize]`, `[Transactional]`)
- **Sidecars / service mesh** — do it *outside* the process entirely (Chapter 15)

```csharp
// MediatR pipeline behaviour — logging applied to EVERY command, written once
public class LoggingBehaviour<TReq, TRes> : IPipelineBehavior<TReq, TRes>
    where TReq : notnull
{
    private readonly ILogger<LoggingBehaviour<TReq, TRes>> _log;
    public LoggingBehaviour(ILogger<LoggingBehaviour<TReq, TRes>> log) => _log = log;

    public async Task<TRes> Handle(TReq request, RequestHandlerDelegate<TRes> next,
                                   CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        _log.LogInformation("Handling {Request}", typeof(TReq).Name);
        var response = await next();
        _log.LogInformation("Handled {Request} in {Ms}ms", typeof(TReq).Name, sw.ElapsedMilliseconds);
        return response;
    }
}
```

---

## 1.6 Composition over Inheritance

**Inheritance** = "is-a". **Composition** = "has-a".

### Why inheritance disappoints

1. **It is the tightest coupling available.** A subclass depends on the parent's *implementation*, not just its interface. Change the parent, break children you have never read. (This is the "fragile base class" problem.)
2. **It is single and permanent** in most languages. One parent, chosen at compile time, forever.
3. **Deep hierarchies are unreadable.** To understand `PremiumCorporateDiscountedOrder` you must read five files upward.
4. **Combinatorial explosion.** Add two independent variations and you need four classes; add a third and you need eight.

The classic disaster:

```
                Employee
               /        \
      FullTime            Contractor
       /     \             /      \
  Salaried  Hourly    Remote    OnSite
     /  \
Manager  IC
  ...now add "part-time remote hourly manager". You cannot.
```

```csharp
// COMPOSITION — each variation is an independent, swappable part
public class Employee
{
    private readonly IPaymentPolicy _payment;    // salaried / hourly / commission
    private readonly IWorkLocation  _location;   // remote / office / hybrid
    private readonly ILeavePolicy   _leave;      // full-time / part-time / contract

    public Employee(IPaymentPolicy payment, IWorkLocation location, ILeavePolicy leave)
        => (_payment, _location, _leave) = (payment, location, leave);

    public Money CalculatePay(Period p) => _payment.Calculate(this, p);
}

// Any combination is now possible, including ones you did not foresee:
var weirdButValid = new Employee(new HourlyPayment(), new Remote(), new ContractLeave());
```

### When inheritance IS right

Do not become a zealot. Inheritance is correct when:

- The relationship is genuinely **is-a** and permanent (`SqlException : Exception`)
- You are building a **framework extension point** (`class MyController : ControllerBase`)
- **Template Method** pattern — a fixed algorithm with pluggable steps (see 1.9)
- The hierarchy is **shallow** (1–2 levels) and **stable**

> **Rule:** Inherit for *identity and interface*. Compose for *behaviour and variation*.

---

## 1.7 Immutability

An **immutable** object cannot change after it is created. To "change" it, you create a new one.

**Real life:** A printed bank statement. You cannot edit last month's statement; you get a new one. That is why it can be trusted as evidence.

```csharp
// MUTABLE — dangerous
public class Money
{
    public decimal Amount { get; set; }
    public string Currency { get; set; }
}

var price = new Money { Amount = 100, Currency = "USD" };
ApplyDiscount(price);      // did this change my object? You must read the method to know.
Console.WriteLine(price.Amount);  // ...50? 100? Who knows.
```

```csharp
// IMMUTABLE — C# record, positional, with value equality built in
public record Money(decimal Amount, string Currency)
{
    public Money Add(Money other)
    {
        if (other.Currency != Currency)
            throw new InvalidOperationException("Currency mismatch");
        return new Money(Amount + other.Amount, Currency);
    }

    public Money ApplyDiscount(decimal percent) =>
        this with { Amount = Amount * (1 - percent / 100) };
}

var price = new Money(100, "USD");
var discounted = price.ApplyDiscount(20);   // price is still 100. Guaranteed.
```

```python
# Python equivalent
from dataclasses import dataclass, replace
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def apply_discount(self, percent: Decimal) -> "Money":
        return replace(self, amount=self.amount * (1 - percent / 100))
```

### Why architects care about immutability

| Benefit | Why it matters at scale |
|---------|------------------------|
| **Thread-safe for free** | No locks needed. This is enormous in concurrent servers. |
| **Safe to cache** | A cached immutable object cannot be corrupted by a caller |
| **Safe to share across boundaries** | Pass it anywhere; nobody can mutate your copy |
| **Easy to reason about** | The value you read is the value that was there. No "action at a distance" bugs. |
| **Natural fit for events** | An event is a fact about the past. Facts do not change. (Chapter 06) |
| **Enables time travel / audit** | Keep every version; you get history for free |

### The cost

- More object allocations (usually irrelevant; measure before caring)
- Awkward for genuinely large mutable structures (a 10 MB image buffer — do not copy it per pixel)
- Some ORMs and frameworks fight you

**Practical guidance:** make **Value Objects** (Money, Email, DateRange, Coordinates, Score) immutable *always*. Make **Entities** (Order, Customer) mutable but with **controlled** mutation — no public setters, only meaningful methods (`order.Cancel(reason)`, not `order.Status = "cancelled"`). Make **DTOs and events** immutable.

---

# PART 2 — Design Patterns 🟢

A design pattern is a **named, reusable solution to a recurring problem**. Their biggest value is not the code — it is the **shared vocabulary**. Saying "let us put an Adapter there" replaces ten minutes of explanation.

> **Warning:** Patterns are *discovered*, not *applied*. Do not start a project by choosing patterns. Write the simple thing; when the pain appears, you will recognise which pattern relieves it.

## 1.8 Creational patterns — *how objects get made*

### Factory Method

**Problem:** The calling code should not know which concrete class to instantiate.

```python
class DocumentReader(ABC):
    @abstractmethod
    def extract(self, image: bytes) -> IdentityData: ...

class PassportReader(DocumentReader): ...
class NationalIdReader(DocumentReader): ...
class DrivingLicenceReader(DocumentReader): ...

class DocumentReaderFactory:
    _readers = {
        DocType.PASSPORT: PassportReader,
        DocType.NID:      NationalIdReader,
        DocType.LICENCE:  DrivingLicenceReader,
    }

    @classmethod
    def create(cls, doc_type: DocType) -> DocumentReader:
        try:
            return cls._readers[doc_type]()
        except KeyError:
            raise UnsupportedDocumentType(doc_type)

# Caller knows nothing about concrete readers:
reader = DocumentReaderFactory.create(request.doc_type)
data = reader.extract(image)
```

**Use when:** the concrete type depends on runtime input (config, user choice, tenant, country).

### Abstract Factory

**Problem:** You need to create **families** of related objects that must match each other.

```csharp
// A whole vendor "family": if you use Vendor A's detector you must use A's matcher
public interface IBiometricVendorFactory
{
    IFaceDetector   CreateDetector();
    IFaceMatcher    CreateMatcher();
    ILivenessScorer CreateScorer();
}

public class AwsRekognitionFactory : IBiometricVendorFactory { ... }
public class AzureFaceFactory      : IBiometricVendorFactory { ... }
public class OnPremiseFactory      : IBiometricVendorFactory { ... }

// Swap the entire family with one line of configuration:
IBiometricVendorFactory factory = config.Vendor switch
{
    "aws"   => new AwsRekognitionFactory(),
    "azure" => new AzureFaceFactory(),
    _       => new OnPremiseFactory()
};
```

**Use when:** mixing components across families would be a bug. Rare, but valuable when it fits (cross-cloud, on-prem vs SaaS, multi-region compliance).

### Builder

**Problem:** An object with many optional parameters. Constructors explode.

```csharp
// The disease: telescoping constructors
new Report(data, true, false, null, 10, "USD", null, true, false);  // what?!
```

```csharp
// The cure
var report = new ReportBuilder()
    .ForPeriod(startDate, endDate)
    .InCurrency("USD")
    .GroupedBy(GroupBy.Month)
    .IncludingFailedVerifications()
    .WithPageSize(50)
    .Build();
```

Builders also let you **validate at `Build()`** ("you must set either a period or a customer") and return an immutable object.

**Use when:** 4+ constructor parameters, many optional; or you need step-by-step construction; or the built object should be immutable.

### Singleton

**Problem:** Exactly one instance must exist (a connection pool, a config registry, a metrics collector).

```csharp
public sealed class ConfigStore
{
    private static readonly Lazy<ConfigStore> _instance = new(() => new ConfigStore());
    public static ConfigStore Instance => _instance.Value;
    private ConfigStore() { }
}
```

**⚠️ Singleton is the most abused pattern in software.** Problems:

- It is **global mutable state** wearing a suit
- It makes testing hard (you cannot substitute it; tests leak state into each other)
- It hides dependencies — a class using `ConfigStore.Instance` does not declare that it needs config
- In a distributed system "only one instance" is a lie anyway — one per process, per pod, per region

> **Modern practice:** you almost never write the Singleton *pattern*. You register a class with **singleton lifetime** in your DI container:
> ```csharp
> services.AddSingleton<IConfigStore, ConfigStore>();
> ```
> Same single instance, but it is **injected**, so it is visible, substitutable and testable. Use this. Always.

### Prototype / Object Pool (awareness ⚪)

- **Prototype** — create a new object by cloning an existing one (useful when construction is expensive, e.g. a pre-configured ML pipeline object)
- **Object Pool** — reuse expensive objects instead of creating them (DB connection pools, HTTP client pools, thread pools). You rarely write one; you use one every day.

---

## 1.9 Structural patterns — *how objects are composed*

### Adapter (the architect's favourite)

**Problem:** You want to use an existing class but its interface does not match what you need.

**Real life:** A travel plug adapter. The wall does not change; your laptop does not change; the adapter sits between.

```python
# Your application's own interface — this is what YOUR code depends on
class FaceDetector(Protocol):
    def detect(self, image: bytes) -> list[Face]: ...

# The vendor's SDK, whose shape you do not control
class AcmeVisionSDK:
    def analyze_image_v2(self, b64_data: str, opts: dict) -> dict:
        ...

# The Adapter
class AcmeFaceDetectorAdapter:
    def __init__(self, sdk: AcmeVisionSDK):
        self._sdk = sdk

    def detect(self, image: bytes) -> list[Face]:
        raw = self._sdk.analyze_image_v2(
            base64.b64encode(image).decode(),
            {"mode": "fast", "return_landmarks": True},
        )
        return [
            Face(
                box=BoundingBox(f["x"], f["y"], f["w"], f["h"]),
                confidence=f["conf"] / 100.0,          # vendor uses 0-100, we use 0-1
            )
            for f in raw.get("detected_faces", [])
        ]
```

Now **one file** knows about Acme. Switching vendors is one new adapter. This tiny pattern is the single highest-leverage habit in integration work — it is the code-level version of the **Anti-Corruption Layer** (Chapter 03).

### Decorator

**Problem:** Add behaviour to an object without changing it and without subclass explosion.

**Real life:** Coffee. Espresso → +milk → +syrup → +whipped cream. Each wrapper adds something; the base drink never changes.

```csharp
public interface IFaceDetector { Task<IReadOnlyList<Face>> DetectAsync(byte[] image); }

// The real one
public class VendorFaceDetector : IFaceDetector { ... }

// Wrapper 1: caching
public class CachingFaceDetector : IFaceDetector
{
    private readonly IFaceDetector _inner;
    private readonly IDistributedCache _cache;

    public CachingFaceDetector(IFaceDetector inner, IDistributedCache cache)
        => (_inner, _cache) = (inner, cache);

    public async Task<IReadOnlyList<Face>> DetectAsync(byte[] image)
    {
        var key = $"faces:{Convert.ToHexString(SHA256.HashData(image))}";
        if (await _cache.GetAsync<List<Face>>(key) is { } hit) return hit;
        var result = await _inner.DetectAsync(image);
        await _cache.SetAsync(key, result, TimeSpan.FromMinutes(10));
        return result;
    }
}

// Wrapper 2: retry.  Wrapper 3: metrics.  Wrapper 4: circuit breaker.
// Composed at registration:
services.AddScoped<IFaceDetector>(sp =>
    new MetricsFaceDetector(
        new CircuitBreakerFaceDetector(
            new RetryFaceDetector(
                new CachingFaceDetector(
                    new VendorFaceDetector(sp.GetRequiredService<HttpClient>()),
                    sp.GetRequiredService<IDistributedCache>())))));
```

Each concern is one small, independently testable class. This is **Separation of Concerns achieved by composition**, and it is how resilience libraries (Polly, Resilience4j) work internally.

### Facade

**Problem:** A subsystem is complicated. Give clients one simple door.

```python
# Behind this one method: frame extraction, quality checks, face detection,
# head pose estimation, anti-spoofing, challenge validation, scoring, persistence.
class LivenessEngine:
    def verify(self, session_id: str, video: bytes) -> LivenessResult:
        frames  = self._extractor.extract(video)
        quality = self._quality.assess(frames)
        if not quality.acceptable:
            return LivenessResult.rejected(quality.reason)
        faces   = self._detector.detect_all(frames)
        pose    = self._pose.track(faces)
        spoof   = self._anti_spoof.score(frames, faces)
        outcome = self._challenge.validate(session_id, pose)
        return self._scorer.combine(spoof, outcome, quality)
```

The caller writes one line. Note: a Facade **simplifies**; it does not hide the subsystem from advanced users who need the parts.

### Proxy

**Problem:** Control access to an object — same interface, extra gate.

Flavours:
- **Virtual proxy** — delay expensive creation (lazy loading an ORM relation)
- **Protection proxy** — check permissions first
- **Remote proxy** — the object is on another machine (this is what a gRPC/HTTP client *is*)
- **Caching proxy** — serve from cache (overlaps with Decorator)

Proxy vs Decorator: nearly identical structure. **Intent** differs — a Decorator *adds* behaviour; a Proxy *controls access*.

### Composite

**Problem:** Treat individual objects and groups of objects uniformly (tree structures).

```csharp
public interface IValidationRule { ValidationResult Validate(Application app); }

public class MinimumAgeRule : IValidationRule { ... }       // leaf
public class DocumentExpiryRule : IValidationRule { ... }   // leaf

public class AllOfRule : IValidationRule                    // composite
{
    private readonly IReadOnlyList<IValidationRule> _rules;
    public AllOfRule(params IValidationRule[] rules) => _rules = rules;

    public ValidationResult Validate(Application app)
        => _rules.Select(r => r.Validate(app))
                 .Aggregate(ValidationResult.Success, ValidationResult.Combine);
}

// A rule tree — and the caller cannot tell a leaf from a branch:
IValidationRule policy = new AllOfRule(
    new MinimumAgeRule(18),
    new AnyOfRule(new PassportRule(), new NationalIdRule()),
    new DocumentExpiryRule());
```

**Use for:** file systems, org charts, UI trees, nested permissions, rule engines, bill-of-materials.

### Bridge & Flyweight (awareness ⚪)

- **Bridge** — separate an abstraction from its implementation so both can vary (`Shape` × `Renderer`: avoid `SvgCircle`, `CanvasCircle`, `SvgSquare`… explosion)
- **Flyweight** — share common state between many objects to save memory (character glyphs, map tiles, particle systems)

---

## 1.10 Behavioural patterns — *how objects interact*

### Strategy 🟢 (the one you will use most)

**Problem:** Multiple ways to do the same thing; choose at runtime.

```python
class PricingStrategy(Protocol):
    def price(self, usage: Usage) -> Money: ...

class PerVerificationPricing:
    def price(self, usage): return Money(usage.verifications * Decimal("0.15"), "USD")

class MonthlyFlatPricing:
    def price(self, usage): return Money(Decimal("499"), "USD")

class TieredPricing:
    TIERS = [(1_000, "0.20"), (10_000, "0.12"), (None, "0.08")]
    def price(self, usage): ...

class Subscription:
    def __init__(self, strategy: PricingStrategy):
        self._strategy = strategy
    def invoice(self, usage: Usage) -> Money:
        return self._strategy.price(usage)
```

Strategy is the concrete implementation of the **Open/Closed Principle**. Whenever you see a growing `if/elif` on a *type* or *mode*, reach for Strategy.

### Observer 🟢

**Problem:** When something happens, an unknown number of other parties need to know.

```csharp
public interface IDomainEventHandler<in TEvent> { Task HandleAsync(TEvent e, CancellationToken ct); }

public record VerificationCompleted(Guid SessionId, bool Passed, DateTime At);

// Three independent listeners, none knows about the others
public class SendWebhookHandler   : IDomainEventHandler<VerificationCompleted> { ... }
public class UpdateAnalyticsHandler: IDomainEventHandler<VerificationCompleted> { ... }
public class ReleaseQuotaHandler  : IDomainEventHandler<VerificationCompleted> { ... }
```

The publisher does not know or care who listens. **This is the in-process ancestor of event-driven architecture** (Chapter 06) — the same idea scaled up to a network gives you pub/sub.

### Command

**Problem:** Turn a request into an object, so you can queue it, log it, undo it, or retry it.

```csharp
public record ApproveVerification(Guid SessionId, string ApproverId, string? Note)
    : IRequest<Result>;

public class ApproveVerificationHandler : IRequestHandler<ApproveVerification, Result>
{
    public async Task<Result> Handle(ApproveVerification cmd, CancellationToken ct)
    {
        // ...
    }
}
```

Because the request is now **data**, you get for free: an audit log of commands, retry on failure, queueing for later execution, undo (with a matching compensating command), and a natural place to hang cross-cutting behaviour (validation, logging, transactions). This is the backbone of CQRS and MediatR-style codebases.

### State

**Problem:** An object behaves differently depending on its state, and you have `if (status == ...)` everywhere.

```python
class SessionState(ABC):
    @abstractmethod
    def submit_video(self, session, video): ...
    @abstractmethod
    def cancel(self, session): ...

class PendingState(SessionState):
    def submit_video(self, session, video):
        session.transition_to(ProcessingState())
        return session.enqueue(video)
    def cancel(self, session):
        session.transition_to(CancelledState())

class ProcessingState(SessionState):
    def submit_video(self, session, video):
        raise InvalidOperation("Already processing")
    def cancel(self, session):
        raise InvalidOperation("Cannot cancel while processing")

class CompletedState(SessionState):
    def submit_video(self, session, video):
        raise InvalidOperation("Session already completed")
    def cancel(self, session):
        raise InvalidOperation("Session already completed")
```

Now illegal transitions are impossible *by construction*, not by remembering to write an `if`. For anything with a lifecycle (order, payment, ticket, KYC session, subscription), **draw the state machine before you write the code.**

### Chain of Responsibility

**Problem:** A request should pass through several handlers, any of which may deal with it or pass it on.

**Real life:** Customer support tiers — L1 → L2 → engineering. Or airport security: ticket check → ID check → bag scan → body scan.

```csharp
public abstract class FraudCheck
{
    private FraudCheck? _next;
    public FraudCheck Then(FraudCheck next) { _next = next; return next; }

    public FraudVerdict Evaluate(Application app)
    {
        var verdict = Check(app);
        if (verdict.IsTerminal) return verdict;         // stop the chain
        return _next?.Evaluate(app) ?? FraudVerdict.Clean;
    }

    protected abstract FraudVerdict Check(Application app);
}

// Every HTTP middleware pipeline you have ever used is this pattern.
```

### Template Method

**Problem:** Several algorithms share the same skeleton but differ in a few steps.

```python
class VerificationPipeline(ABC):
    # The skeleton is FIXED and lives in one place
    def run(self, video: bytes) -> Result:
        frames = self.extract_frames(video)
        if not self.check_quality(frames):
            return Result.rejected("poor quality")
        signals = self.analyse(frames)          # subclasses differ HERE
        score   = self.score(signals)           # ...and HERE
        self.persist(score)
        return Result.from_score(score)

    def extract_frames(self, video): ...        # shared default
    def check_quality(self, frames): ...        # shared default
    @abstractmethod
    def analyse(self, frames): ...              # must implement
    @abstractmethod
    def score(self, signals): ...               # must implement

class PassiveLivenessPipeline(VerificationPipeline): ...
class ActiveChallengePipeline(VerificationPipeline): ...
```

This is the one place inheritance genuinely shines. (The composition alternative: pass in strategy objects for the varying steps.)

### Others worth recognising ⚪

| Pattern | One line |
|---------|----------|
| **Iterator** | Traverse a collection without exposing its internals (built into every modern language) |
| **Mediator** | Objects talk through a hub instead of to each other (MediatR; also a chat room) |
| **Memento** | Save and restore an object's state (undo) |
| **Visitor** | Add a new operation to a class hierarchy without editing those classes (compilers, AST walking) |
| **Interpreter** | Evaluate sentences in a small language (rule engines, query DSLs) |
| **Null Object** | A do-nothing implementation instead of `null` (`NullLogger`, `NoOpCache`) — kills a whole class of null checks |

---

# PART 3 — Enterprise patterns 🟢

These come from Martin Fowler's *Patterns of Enterprise Application Architecture* and from DDD. They shape whole applications rather than a few classes.

## 1.11 Repository

**Problem:** Business logic should not know about SQL, ORMs, or Mongo.

**The mental model:** a Repository pretends to be an **in-memory collection** of domain objects.

```csharp
// In the DOMAIN project — expressed in business language, no SQL anywhere
public interface IVerificationSessionRepository
{
    Task<VerificationSession?> GetAsync(SessionId id, CancellationToken ct);
    Task<IReadOnlyList<VerificationSession>> GetExpiredAsync(DateTime before, CancellationToken ct);
    Task AddAsync(VerificationSession session, CancellationToken ct);
    Task UpdateAsync(VerificationSession session, CancellationToken ct);
}

// In the INFRASTRUCTURE project
public class EfVerificationSessionRepository : IVerificationSessionRepository
{
    private readonly AppDbContext _db;
    public EfVerificationSessionRepository(AppDbContext db) => _db = db;

    public Task<VerificationSession?> GetAsync(SessionId id, CancellationToken ct) =>
        _db.Sessions.Include(s => s.Attempts)
                    .FirstOrDefaultAsync(s => s.Id == id, ct);
    // ...
}
```

### Rules for good repositories

1. **One repository per Aggregate Root**, not per table (Chapter 03). `IOrderRepository`, not `IOrderLineRepository`.
2. **Return domain objects**, never `DataTable`, `DbSet`, or vendor types.
3. **Do not leak `IQueryable`** out of the repository — if you do, callers can write any query, and you have gained nothing. The database concerns leak right back in.
4. **Name methods in business language** — `GetExpiredAsync`, `GetPendingReviewAsync`, not `FindByStatusAndDate`.
5. **Do not create a generic `IRepository<T>` with 20 methods** — that is an ISP violation and it forces every aggregate to support operations that make no sense for it.

### The honest counter-argument

Some argue a repository over an ORM like EF Core or SQLAlchemy is a pointless extra layer — the ORM's `DbSet`/`Session` *is already* a repository and a Unit of Work.

That is a fair point. Use a repository when:
- Your domain model must stay pure and testable without a DB (this is usually the deciding factor)
- You have complex queries you want named and reused
- There is a real chance of changing the data store, or you have two (SQL + a search index)

Skip it when: you have a small CRUD service and the ORM is already the abstraction. **Do not add layers by reflex.**

## 1.12 Unit of Work

**Problem:** One business operation touches several objects. Either all changes stick, or none do.

**Real life:** A bank transfer. Debit one account, credit another. Both, or neither. Never one.

```csharp
public interface IUnitOfWork
{
    Task<int> SaveChangesAsync(CancellationToken ct = default);
}

public class TransferMoneyHandler
{
    private readonly IAccountRepository _accounts;
    private readonly IUnitOfWork _uow;

    public async Task Handle(TransferMoney cmd, CancellationToken ct)
    {
        var from = await _accounts.GetAsync(cmd.From, ct) ?? throw new NotFound(cmd.From);
        var to   = await _accounts.GetAsync(cmd.To, ct)   ?? throw new NotFound(cmd.To);

        from.Withdraw(cmd.Amount);   // domain rules: sufficient funds? account frozen?
        to.Deposit(cmd.Amount);

        await _uow.SaveChangesAsync(ct);   // ONE transaction, both rows, or nothing
    }
}
```

`DbContext` in EF Core and `Session` in SQLAlchemy already **are** Units of Work — they track changes and flush them in one transaction. Wrapping them in an `IUnitOfWork` interface is mostly about keeping the application layer free of EF types.

**Architect's note:** Unit of Work works beautifully inside **one database**. Across services/databases it does not exist — that is where **Sagas** come in (Chapter 05). Knowing exactly where this boundary lies is a key architect skill.

## 1.13 Specification

**Problem:** Business rules for "which objects qualify?" get duplicated between validation code, query code and UI code.

```csharp
public abstract class Specification<T>
{
    public abstract Expression<Func<T, bool>> ToExpression();
    public bool IsSatisfiedBy(T candidate) => ToExpression().Compile()(candidate);

    public Specification<T> And(Specification<T> other) => new AndSpecification<T>(this, other);
    public Specification<T> Or(Specification<T> other)  => new OrSpecification<T>(this, other);
    public Specification<T> Not()                       => new NotSpecification<T>(this);
}

public class ExpiredSessionSpec : Specification<VerificationSession>
{
    private readonly DateTime _now;
    public ExpiredSessionSpec(DateTime now) => _now = now;
    public override Expression<Func<VerificationSession, bool>> ToExpression()
        => s => s.CreatedAt.AddMinutes(15) < _now && s.Status == SessionStatus.Pending;
}

public class HighRiskSpec : Specification<VerificationSession>
{
    public override Expression<Func<VerificationSession, bool>> ToExpression()
        => s => s.RiskScore > 0.7 || s.AttemptCount >= 3;
}

// The rule is defined ONCE and used in both places:
var spec = new ExpiredSessionSpec(DateTime.UtcNow).And(new HighRiskSpec());

bool needsReview = spec.IsSatisfiedBy(session);                 // in-memory check
var toReview     = await _db.Sessions.Where(spec.ToExpression()) // translated to SQL
                                     .ToListAsync(ct);
```

**Use when:** the same "which ones qualify" rule appears in more than one place, or when users can build filters by combining criteria. **Skip when:** you have three simple queries — a named repository method is simpler and clearer.

## 1.14 Service Layer

**Problem:** Where does orchestration live — code that is not a domain rule and not a controller?

The standard three-service confusion, resolved:

| Type | Lives in | Contains | Example |
|------|----------|----------|---------|
| **Application Service** | Application layer | Orchestration, transactions, authorisation checks, calls to repos and external services. **No business rules.** | `VerificationService.VerifyAsync()` |
| **Domain Service** | Domain layer | Business logic that does not belong to a single entity. **No I/O.** | `RiskScoringService.Score(session, history)` |
| **Infrastructure Service** | Infrastructure layer | Technical work | `S3VideoStorage`, `SendGridEmailSender` |

```python
# APPLICATION SERVICE — a thin conductor. Reads like a recipe.
class VerificationAppService:
    def __init__(self, sessions, detector, storage, events, uow):
        self._sessions, self._detector = sessions, detector
        self._storage, self._events, self._uow = storage, events, uow

    async def verify(self, cmd: VerifyCommand) -> VerificationDto:
        session = await self._sessions.get(cmd.session_id)
        if session is None:
            raise SessionNotFound(cmd.session_id)

        video_ref = await self._storage.save(cmd.video)          # infrastructure
        signals   = await self._detector.analyse(cmd.video)      # infrastructure
        session.record_attempt(signals, video_ref)               # DOMAIN decides

        await self._sessions.update(session)
        await self._uow.commit()
        await self._events.publish(session.pull_domain_events())
        return VerificationDto.from_domain(session)
```

> **Test for a healthy application service:** it should read like a list of steps, with **no `if` statements about business rules**. Every `if` about money, eligibility, limits or status belongs in the domain.

**The anti-pattern to avoid:** the *Anemic Domain Model* — entities that are just bags of properties with getters/setters, and all logic sitting in services. You then have procedural code wearing OOP clothes; rules get duplicated across services, and nobody can find them.

## 1.15 DTO — Data Transfer Object

**Problem:** Your internal model should not be your external contract.

```csharp
// DOMAIN — rich, protected, internal
public class VerificationSession
{
    public SessionId Id { get; private set; }
    public CustomerId CustomerId { get; private set; }
    internal string VendorApiKey { get; private set; }       // must NEVER go out
    public decimal InternalRiskScore { get; private set; }   // must NEVER go out
    private readonly List<Attempt> _attempts = new();
    public IReadOnlyList<Attempt> Attempts => _attempts;

    public void RecordAttempt(Signals s) { /* rules */ }
}

// API CONTRACT — flat, explicit, stable, safe
public record VerificationResponse(
    string SessionId,
    string Status,
    bool Passed,
    int AttemptsUsed,
    int AttemptsRemaining,
    DateTime CompletedAt);
```

### Why DTOs matter (four reasons)

1. **Security** — you cannot accidentally leak `VendorApiKey` or `InternalRiskScore`. Auto-serialising entities is a genuine, common breach vector.
2. **Stability** — rename a domain field, and the public API does not break (your mapper absorbs it)
3. **Shape** — the API can flatten, combine or compute (`AttemptsRemaining`) without polluting the domain
4. **Over-posting protection** — a request DTO with only the allowed fields prevents a client from setting `IsAdmin: true` in the JSON body

> **Hard rule: never expose domain entities directly over an API.** Also never accept them directly as input. Map at the boundary — by hand, or with Mapster/AutoMapper/Pydantic.

## 1.16 Dependency Injection

**DIP** is the principle (1.2). **DI** is the technique. **IoC container** is the tool.

### Three ways to inject

```csharp
// 1. CONSTRUCTOR INJECTION — use this ~95% of the time
public class OrderService
{
    private readonly IOrderRepository _repo;
    public OrderService(IOrderRepository repo) => _repo = repo;   // required, immutable
}

// 2. PROPERTY INJECTION — for genuinely optional dependencies
public class OrderService
{
    public ILogger Logger { get; set; } = NullLogger.Instance;    // has a safe default
}

// 3. METHOD INJECTION — the dependency varies per call
public decimal Calculate(Order o, ITaxPolicy policy) => policy.Apply(o);
```

### Lifetimes — get this wrong and you get 3 AM bugs

| Lifetime | One instance per | Use for | Classic bug |
|----------|-----------------|---------|-------------|
| **Transient** | Every request for it | Lightweight, stateless things | Creating expensive objects in a loop |
| **Scoped** | Per HTTP request / per unit of work | `DbContext`, per-request context | — |
| **Singleton** | Whole application | Config, caches, HTTP clients, pools | **Captive dependency**: a Singleton holding a Scoped `DbContext`. That DbContext now lives forever, is shared across requests, and is not thread-safe. Chaos. |

> Most DI containers can detect captive dependencies. **Turn that validation on** (`ValidateScopes = true`, `ValidateOnBuild = true` in .NET). It turns a mystery production bug into a startup error.

### Why DI is an architecture concern, not a coding trick

- It is how DIP is physically enforced at runtime
- It makes dependencies **visible** — read a constructor and you know exactly what a class needs. If it needs 9 things, SRP is broken, and now you can *see* it.
- It makes testing trivial (pass fakes)
- It enables the Decorator pattern at the composition root
- It gives you **one place** (the composition root) where all wiring is declared

## 1.17 CQRS — Command Query Responsibility Segregation

**Core idea:** the model you use to **change** data does not have to be the model you use to **read** data.

**Why:** Writes need validation, invariants, transactions, and a rich object graph. Reads need speed, flat shapes and joins. Serving both from one model means both are compromised.

### Level 1 — Just separate the code paths (start here)

```csharp
// WRITE side: rich domain, full aggregate, all rules enforced
public record ApproveVerification(Guid SessionId, string ApproverId) : IRequest;

public class ApproveVerificationHandler : IRequestHandler<ApproveVerification>
{
    public async Task Handle(ApproveVerification cmd, CancellationToken ct)
    {
        var session = await _repo.GetAsync(cmd.SessionId, ct);  // loads the aggregate
        session.Approve(cmd.ApproverId);                        // enforces invariants
        await _uow.SaveChangesAsync(ct);
    }
}

// READ side: no domain model at all — go straight to a fast projection
public class GetSessionListHandler : IRequestHandler<GetSessionList, IReadOnlyList<SessionRow>>
{
    private readonly IDbConnection _db;       // plain Dapper / raw SQL
    public async Task<IReadOnlyList<SessionRow>> Handle(GetSessionList q, CancellationToken ct)
        => (await _db.QueryAsync<SessionRow>(
                """
                SELECT s.id, s.status, c.name AS customer_name, s.created_at, s.score
                FROM   sessions s
                JOIN   customers c ON c.id = s.customer_id
                WHERE  s.tenant_id = @TenantId AND s.created_at >= @From
                ORDER  BY s.created_at DESC
                LIMIT  @Take OFFSET @Skip
                """, q)).ToList();
}
```

This alone removes a huge amount of pain: no more torturing an ORM into producing a grid view, and no more loading a 12-table aggregate to show 5 columns.

### Level 2 — Separate data stores (only when you need it)

```
                      ┌──────────────┐
  Commands ─────────► │ Write DB     │  (Postgres, normalised, transactional)
                      └──────┬───────┘
                             │ events / CDC
                             ▼
                      ┌──────────────┐
  Queries  ◄───────── │ Read store   │  (Elasticsearch / Mongo / materialised views)
                      └──────────────┘
```

**You gain:** reads and writes scale independently; each store is optimised for its job; complex search becomes easy.
**You pay:** eventual consistency (a user may not see their own write immediately), a synchronisation pipeline to build and operate, and double the storage.

> **When to use CQRS:** read and write loads are very different (e.g. 1000:1), or reporting queries are killing your OLTP database, or you have complex search needs.
> **When NOT to:** simple CRUD. CQRS on a basic admin screen is pure ceremony. Start at Level 1, and only go to Level 2 when you have measured a real problem.

### The "read your own writes" trap

With separate stores, a user clicks Save and then sees the old value. This is the number-one complaint about CQRS. Standard fixes:

- Return the new value directly from the command response (do not re-query)
- Update the UI optimistically on the client
- Route that user's reads to the write store for a few seconds ("sticky" reads)
- Show an explicit "processing…" state so the UI never lies

## 1.18 Domain Events

**Problem:** Something important happened in the domain, and several other parts of the system must react — but the domain should not know about them.

```csharp
public abstract record DomainEvent(DateTime OccurredAt);
public record VerificationPassed(SessionId SessionId, CustomerId CustomerId, decimal Score, DateTime OccurredAt)
    : DomainEvent(OccurredAt);

public class VerificationSession
{
    private readonly List<DomainEvent> _events = new();
    public IReadOnlyList<DomainEvent> DomainEvents => _events;
    public void ClearEvents() => _events.Clear();

    public void RecordAttempt(Signals signals)
    {
        if (_attempts.Count >= MaxAttempts) throw new TooManyAttemptsException(Id);

        var passed = signals.LivenessScore > PassThreshold && !signals.SpoofDetected;
        _attempts.Add(new Attempt(signals, passed));

        if (passed)
        {
            Status = SessionStatus.Passed;
            _events.Add(new VerificationPassed(Id, CustomerId, signals.LivenessScore, DateTime.UtcNow));
        }
        else if (_attempts.Count >= MaxAttempts)
        {
            Status = SessionStatus.Failed;
            _events.Add(new VerificationFailed(Id, CustomerId, "max attempts", DateTime.UtcNow));
        }
    }
}
```

The session raises a **fact**. It does not send an email, call a webhook, or update analytics. Those are handled by independent listeners:

```csharp
public class SendWebhookOnPass       : INotificationHandler<VerificationPassed> { ... }
public class ReleaseQuotaOnPass      : INotificationHandler<VerificationPassed> { ... }
public class UpdateDashboardOnPass   : INotificationHandler<VerificationPassed> { ... }
```

### When are events dispatched? (the important detail)

**Before** `SaveChanges` — handlers run inside the same transaction. Consistent, but a slow/failing handler rolls back the business operation. Fine for in-domain side effects.

**After** `SaveChanges` — the business change is safe; handlers run afterwards. But if the process crashes between commit and dispatch, **the event is lost**. This is the classic **dual-write problem**.

**The correct solution is the Outbox pattern:** write the event into an `outbox` table *in the same transaction* as the business data; a separate process reads the outbox and publishes. Atomic, and no lost events. Full treatment in Chapter 06 — it is one of the most valuable patterns in the whole book.

### Naming events

- **Past tense, always.** `OrderPlaced`, not `PlaceOrder` (that is a command).
- **Business language.** `CustomerVerified`, not `SessionRowUpdated`.
- **Immutable.** An event is a fact about the past; facts do not change.
- Include **what handlers need**, plus IDs, plus a timestamp — but be aware that fat events create coupling (Chapter 06 covers event-carried state transfer vs notification).

---

## 1.19 Common mistakes

1. **Pattern fever** — applying patterns because you learned them, not because you have the problem. A `FactoryProviderStrategyBuilder` for a config file.
2. **Anemic domain model** — entities with only getters/setters; all logic in services. Very common, and it quietly kills DDD.
3. **Generic `IRepository<T>` with 25 methods** — ISP violation; forces meaningless operations on every aggregate.
4. **Leaking `IQueryable`** out of repositories — all abstraction lost, and the DB shape is back in your business code.
5. **Singleton abuse** — global mutable state, untestable, hidden dependencies.
6. **DRY-ing coincidental similarity** — two rules that look alike today get welded together, and the wrong abstraction costs more than the duplication ever did.
7. **Exposing entities over the API** — the leading cause of accidental data exposure.
8. **Constructor with 12 dependencies** — DI did not cause this; it *revealed* an SRP violation. Fix the class, do not hide the constructor.
9. **Interfaces for everything** — one implementation, one interface, forever. If there will only ever be one implementation and you do not need the seam for testing, the interface is noise.
10. **Deep inheritance hierarchies** — 5 levels, and nobody can predict what `Save()` does.

---

## 1.20 Architect's checklist

- [ ] Can I unit-test the business rules with **no** database, network or file system?
- [ ] Does the domain layer import any framework, driver or SDK? (It must not.)
- [ ] Is there exactly **one** place where each business rule lives?
- [ ] Are external systems behind **my** interfaces (Adapter), not used directly?
- [ ] Are entities exposed over the API? (Must be no.)
- [ ] Can a new developer find where a given rule lives within 2 minutes?
- [ ] Are dependencies visible in constructors, rather than hidden in statics/singletons?
- [ ] Is there a class named `Utils`, `Helper`, `Manager` or `Common`? (Cohesion warning.)
- [ ] Are value objects immutable?
- [ ] Are there growing `if/switch` chains on type or mode? (Strategy candidate.)
- [ ] Does anything with a lifecycle have a drawn state machine?
- [ ] Are DI lifetimes validated at startup?

---

## 1.21 Self-test

1. Define coupling and cohesion. What is the goal for each?
2. Why is "one class, one thing" a *wrong* statement of SRP? State it correctly.
3. Show a Liskov violation in code, and explain why the compiler cannot catch it.
4. Where should the interface `IOrderRepository` physically live, and why does it matter?
5. When is duplication better than abstraction? Give a concrete example.
6. Where does YAGNI *not* apply? Name four things.
7. Adapter vs Decorator vs Proxy: same structure, different intent. State each intent.
8. Why is Singleton usually the wrong answer, and what is the right one?
9. What is the difference between an Application Service and a Domain Service?
10. What is an anemic domain model, and why is it a problem?
11. Explain CQRS Level 1 vs Level 2. When is Level 2 justified?
12. What is the dual-write problem with domain events, and what pattern fixes it?

---

## 1.22 Key takeaways

- Everything reduces to **low coupling, high cohesion**
- **SOLID** is five techniques for achieving that — DIP is the architecturally decisive one
- **DRY applies to knowledge, not to text.** The wrong abstraction costs more than duplication
- **YAGNI for features; think ahead for things that are expensive to retrofit**
- **Compose behaviour; inherit identity**
- **Immutability** buys thread safety, cacheability and sanity — use it for value objects, DTOs and events
- Patterns are a **vocabulary**, not a shopping list — discovered, not applied
- **Adapter** at every external boundary is the highest-leverage habit in integration work
- **Never expose domain entities over an API**
- Keep the domain **pure**: no I/O, no frameworks, fully unit-testable

---

**Next:** [Chapter 02 — Architecture Styles](02-architecture-styles.md)
