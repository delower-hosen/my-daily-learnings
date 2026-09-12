# Chapter 02 — Architecture Styles 🟢

> You should recognise every style in this chapter instantly — the way a doctor recognises a symptom.
> Not because you will use them all, but because when someone says *"it's a hexagonal event-driven modular monolith"*, you should picture it immediately and know what questions to ask next.

---

## 2.0 Two different kinds of "architecture"

People use the word for two different things, and the confusion causes endless arguing. Separate them:

| Kind | Question it answers | Examples |
|------|--------------------|---------| 
| **Deployment / topology style** | How many deployable units? How do they talk? | Monolith, microservices, serverless, SOA, event-driven |
| **Internal / code organisation style** | How is the code inside one unit arranged? | Layered, hexagonal, onion, clean, pipes-and-filters, plugin |

They are **independent axes**. You can have:

- A monolith organised with Clean Architecture ✅ (very common and very good)
- Microservices where each service is a mud ball ✅ (very common and very bad)
- A modular monolith with hexagonal modules ✅ (arguably the sweet spot for most teams)

> **The most common mistake in the industry:** thinking "microservices" fixes messy code. It does not. It takes your messy code and adds a network between the pieces. **Fix the modules first; the topology is a separate, later decision.**

---

# PART A — Deployment styles

## 2.1 The Traditional Monolith

**Definition:** One codebase, one build, one deployable unit, usually one database.

```
┌────────────────────────────────────────────┐
│              shop.exe / app.py             │
│                                            │
│  Users │ Products │ Orders │ Payments │ ...│
│  (all calling each other freely)           │
└──────────────────┬─────────────────────────┘
                   │
              ┌────▼────┐
              │   DB    │
              └─────────┘
```

### What it is genuinely good at

| Strength | Why |
|----------|-----|
| **Simplicity** | One repo, one build, one deploy, one log file, one debugger |
| **Performance** | A function call is ~1 nanosecond. A network call is ~1 millisecond. That is a **million times** difference. |
| **Transactions** | `BEGIN ... COMMIT` across the whole business operation. ACID for free. |
| **Refactoring** | "Rename Symbol" works across the entire system |
| **Debugging** | One stack trace tells the whole story |
| **Cost** | One server. No service mesh, no message broker, no distributed tracing bill. |

> **Monoliths are not obsolete. Shopify, GitHub, Stack Overflow and Basecamp run enormous, successful monoliths.** Stack Overflow served billions of page views from a handful of servers.

### Where it hurts

| Problem | Symptom |
|---------|---------|
| **Coupling entropy** | With no enforced boundaries, everything eventually calls everything |
| **Deploy coupling** | A one-line CSS fix requires deploying the payment engine |
| **Scale coupling** | Image processing needs 32 GB RAM, so *every* instance gets 32 GB |
| **Technology lock** | The whole thing is .NET 6; you cannot use a Python ML library in-process |
| **Team coupling** | 60 developers merging into one main branch; the CI queue is 4 hours |
| **Blast radius** | One memory leak in the report module takes down checkout |
| **Slow feedback** | The test suite takes 90 minutes |

**When does it actually break?** Usually not at a user count — at a **team count**. Roughly past 15–25 developers on one codebase, coordination cost starts to dominate. That number is the real trigger, not requests per second.

### Verdict

> **Default to a monolith.** Start here unless you have a specific, named reason not to. Martin Fowler's "MonolithFirst" advice has aged extremely well: you do not know your true service boundaries on day 1, and a bad boundary in a distributed system is *ten times* more expensive to fix than a bad boundary inside one process.

---

## 2.2 The Modular Monolith ⭐ (the most under-used style in the industry)

**Definition:** One deployable unit, but the code inside is split into strictly-enforced modules that communicate only through published interfaces.

```
┌──────────────────────────────────────────────────────────────┐
│                    ONE DEPLOYABLE UNIT                       │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│  │  Identity │  │  Billing  │  │Verification│ │ Reporting │  │
│  │           │  │           │  │           │  │           │  │
│  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │
│  │ │public │ │  │ │public │ │  │ │public │ │  │ │public │ │  │
│  │ │  API  │◄┼──┼─┤  API  │◄┼──┼─┤  API  │ │  │ │  API  │ │  │
│  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │
│  │  internal │  │  internal │  │  internal │  │  internal │  │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
└────────┼──────────────┼──────────────┼──────────────┼────────┘
         │              │              │              │
    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
    │ schema: │    │ schema: │    │ schema: │    │ schema: │
    │ identity│    │ billing │    │verificat│    │reporting│
    └─────────┘    └─────────┘    └─────────┘    └─────────┘
              ONE DATABASE, SEPARATE SCHEMAS
```

### The rules that make it work

1. **Each module has a public API** (a handful of interfaces/facades) and everything else is `internal`/private
2. **No module reaches into another module's tables.** Separate schemas, and the DB user for module A has no grant on module B's schema if you want it enforced hard
3. **Cross-module calls go through the public API** or through in-process events
4. **Enforce it with tooling, not discipline** — this is the whole trick

```csharp
// C#: physically enforce it by using separate assemblies + `internal`
// Billing.csproj exposes only:
namespace Billing.Contracts;
public interface IBillingApi
{
    Task<Quote> GetQuoteAsync(TenantId tenant, Usage usage, CancellationToken ct);
    Task ChargeAsync(TenantId tenant, Money amount, CancellationToken ct);
}
// Everything else in Billing.csproj is `internal` — other modules CANNOT see it.
```

```csharp
// And a fitness function so it can never regress:
[Fact]
public void Modules_Must_Only_Reference_Other_Modules_Contracts()
{
    var result = Types.InAssembly(typeof(VerificationModule).Assembly)
        .ShouldNot().HaveDependencyOnAny("Billing.Internal", "Identity.Internal")
        .GetResult();
    Assert.True(result.IsSuccessful);
}
```

```python
# Python: enforce with import-linter (.importlinter)
[importlinter]
root_package = app

[importlinter:contract:module-independence]
name = Modules communicate only via their public api module
type = forbidden
source_modules =
    app.modules.verification
forbidden_modules =
    app.modules.billing.internal
    app.modules.identity.internal
```

### Why this is the sweet spot for most teams

| You get (monolith) | You get (microservices-ish) |
|---------------------|------------------------------|
| ACID transactions | Clear boundaries |
| Simple deploy & debug | Independent teams can own modules |
| Fast in-process calls | Ready to extract to a service **when actually needed** |
| One repo, one CI | Forced to think about contracts |

And critically: **extraction later is cheap.** If `Verification` is already a module with a defined API and its own schema, turning it into a service is days of work — mostly changing an in-process call into an HTTP/queue call. If it is a spaghetti monolith, extraction is a year.

> **This is the single most valuable practical recommendation in this book:**
> **Start as a modular monolith. Extract a service only when a specific, measured force demands it** (independent scaling, independent deploy cadence, team autonomy, different technology, regulatory isolation).

### Real example

A payments company with 20 engineers built a modular monolith: 9 modules, 9 schemas, one deployable. Over 3 years they extracted exactly 2 services — the fraud-scoring engine (needed GPUs and Python) and the webhook dispatcher (needed to scale on I/O independently). The other 7 modules never needed to move. They avoided operating 9 services and shipped features the whole time.

---

## 2.3 The Distributed Monolith ☠️ (the anti-pattern)

**Definition:** Looks like microservices. Behaves like a monolith. Has the disadvantages of both and the benefits of neither.

### Diagnostic checklist — you have one if:

- [ ] Services must be deployed together, in a specific order
- [ ] Services share a database, or one service reads another's tables
- [ ] A single user action requires 6 synchronous service hops
- [ ] Changing a shared library forces every service to be rebuilt and redeployed
- [ ] One service being down makes the whole system unusable
- [ ] You have a "release train" where all services ship on Thursday night
- [ ] Services share DTOs from a common package that changes weekly

If you tick 3 or more, you have a distributed monolith.

```
   ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
   │ Svc A  │───►│ Svc B  │───►│ Svc C  │───►│ Svc D  │
   └───┬────┘    └───┬────┘    └───┬────┘    └───┬────┘
       └─────────────┴──────┬──────┴─────────────┘
                      ┌─────▼─────┐
                      │ SHARED DB │   ← the tell-tale sign
                      └───────────┘
   Synchronous chain: total latency = sum of all.
   Total availability = product of all (0.99^4 = 96%).
```

### How it happens (always the same story)

1. Management says "we need microservices"
2. The team splits by **technical layer** (`user-api`, `user-service`, `user-data`) instead of by **business capability**
3. Nobody wants to duplicate data, so the shared DB stays
4. Services need each other's data, so synchronous calls proliferate
5. Deploy order matters, so a coordinator appears
6. Now you need 6 terminals to debug a login

### How to escape

- Fix **data ownership** first — one owner per piece of data, no cross-reads. This is the root cause.
- Replace synchronous chains with **async events** where possible
- **Merge** services back together if they always change together. Merging is a legitimate, professional move — do not be too proud to do it.
- Stop sharing DTO packages; each service owns its contract and tolerates the others' (Chapter 08).

---

## 2.4 SOA — Service-Oriented Architecture ⚪🟡

The 2000s enterprise ancestor of microservices.

```
  App A ──┐                                    ┌── Legacy Mainframe
  App B ──┼──► ┌─────────────────────────┐ ────┼── SAP
  App C ──┘    │  ENTERPRISE SERVICE BUS │     └── Oracle DB
               │  routing, transformation,│
               │  orchestration, protocol │
               │  bridging, business rules│
               └─────────────────────────┘
```

**Key ideas:** reusable business services, a central **ESB** doing routing/transformation/orchestration, contracts in WSDL/SOAP, centralised governance.

**Why it fell out of favour:**
- The ESB became a **single point of failure** and a **single point of congestion**
- Business logic crept into the bus — "smart pipes, dumb endpoints" — so the bus became a monolith that everyone had to coordinate on
- Vendor licences were enormous
- Central governance meant every change needed the integration team, who had a 6-week queue

**Microservices are largely a reaction to this:** *"smart endpoints, dumb pipes."*

**Do you need to know it?** Awareness ⚪ — except that you will absolutely meet an ESB (MuleSoft, WSO2, BizTalk, TIBCO, IBM IIB) in an enterprise job, and you should not panic. Also worth knowing: the modern **API Gateway** and **service mesh** are the descendants that kept the useful parts (routing, security, observability) and dropped the business logic.

---

## 2.5 Microservices 🟢

**Definition:** A system built as a set of small, independently deployable services, each owning its data, organised around business capabilities.

### The defining characteristics (all of them must hold)

1. **Independently deployable** — this is the *point*. If you cannot deploy one without the others, you do not have microservices.
2. **Owns its data** — no shared database. Full stop.
3. **Organised around a business capability**, not a technical layer
4. **Smart endpoints, dumb pipes** — logic in the services, not in the bus
5. **Decentralised governance** — teams choose their own tools (within reason)
6. **Design for failure** — the network will fail; behave sensibly when it does
7. **Team-sized** — one team can own it fully ("two-pizza team")

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Identity   │  │  Billing    │  │Verification │  │ Notification│
│  Service    │  │  Service    │  │  Service    │  │  Service    │
│  (Team A)   │  │  (Team B)   │  │  (Team C)   │  │  (Team D)   │
│   .NET      │  │   .NET      │  │  Python/GPU │  │   Go        │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
  ┌────▼────┐      ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
  │Postgres │      │Postgres │      │ Mongo   │      │ Redis   │
  └─────────┘      └─────────┘      └─────────┘      └─────────┘
       └────────────────┴────────────────┴────────────────┘
                          Message broker (async events)
```

### The real benefits

| Benefit | Concrete example |
|---------|------------------|
| **Independent deployment** | Team C ships 8× a day without asking anyone |
| **Independent scaling** | The GPU verification service runs 30 pods; billing runs 2 |
| **Technology fit** | ML in Python, high-throughput I/O in Go, business logic in .NET |
| **Fault isolation** | Notification service dies → verifications still work, notifications queue up |
| **Team autonomy** | 8 teams, 8 backlogs, 8 release calendars, minimal coordination |
| **Targeted rewrite** | Rewriting one 5,000-line service is a quarter's work, not a 3-year programme |

### The real costs (be honest about these)

| Cost | Reality |
|------|---------|
| **Network is not reliable** | Every call can fail, time out, or arrive twice. All 8 fallacies of distributed computing now apply (Chapter 05) |
| **No distributed transactions** | You need Sagas and compensation. This is a large step up in design difficulty |
| **Eventual consistency** | The business must accept "the dashboard is 2 seconds behind" |
| **Debugging** | One user action, 7 services, 7 log streams. You *must* have distributed tracing (Chapter 18) before you need it |
| **Operational load** | 30 services = 30 pipelines, 30 dashboards, 30 on-call runbooks, 30 sets of secrets |
| **Testing** | Integration testing is genuinely hard. You need contract testing (Chapter 21) |
| **Data duplication** | Each service keeps a copy of what it needs; keeping copies correct is ongoing work |
| **Latency** | 7 hops × 20 ms = 140 ms floor, before any actual work |
| **Cost** | More instances, more idle capacity, a broker, a mesh, an observability bill |

### The availability maths that surprises people

If a request must synchronously touch 5 services, each 99.9% available:

```
0.999 ^ 5 = 0.995   →  99.5% availability  →  ~3.6 hours downtime/month
```

You made things **worse** than any single service. This is why async messaging, caching, graceful degradation and circuit breakers are not optional extras in microservices — they are load-bearing.

### The prerequisites (Martin Fowler's "microservices premium")

**Do not start microservices unless you already have:**

- [ ] Automated deployment (CI/CD) for every service
- [ ] Monitoring, centralised logging and distributed tracing
- [ ] The ability to provision infrastructure quickly (IaC)
- [ ] Teams that can own a service end-to-end, including on-call
- [ ] A good understanding of your domain boundaries (see DDD, Chapter 03)
- [ ] A real, named problem that microservices solve for you

Miss these, and microservices will cost you more than they give.

### How big is "micro"?

Wrong answers: "under 500 lines", "one per table", "one per developer".

**Right answers:**
- Small enough that **one team can own it** and understand it fully
- As big as **one bounded context** (Chapter 03) — usually the best rule
- Small enough to **rewrite in 2–4 weeks** if you had to

> **If two services always change together, they are one service.** That is the cleanest test in practice.

---

## 2.6 Miniservices / "Right-sized services" 🟡

The pragmatic middle. Also called *macroservices*, *modulith services*, or "services shaped by reality".

**The idea:** independently deployable services, but larger than "micro", and pragmatic about the strict rules — for example, two closely-related services might share a database schema if splitting it would create more problems than it solves.

```
┌────────────────────────┐  ┌────────────────────────┐
│  Customer Management   │  │   Verification Engine  │
│  (identity, profiles,  │  │  (sessions, liveness,  │
│   consent, KYC docs)   │  │   scoring, vendors)    │
│      ~4 modules        │  │      ~5 modules        │
└───────────┬────────────┘  └───────────┬────────────┘
            │                            │
      ┌─────▼─────┐                ┌─────▼─────┐
      │ Postgres  │                │ Postgres  │
      └───────────┘                └───────────┘
```

**When it is the right answer:** most of the time, for most companies. 4–8 well-chosen services usually deliver 90% of the microservices benefit at 30% of the operational cost.

**Architect's framing:** microservices is not a binary. It is a **dial**, from one deployable to hundreds. Your job is to pick the setting that matches your team size, your NFRs and your operational maturity — and to move the dial slowly, in one direction, with evidence.

---

## 2.7 Event-Driven Architecture (EDA) 🟢

**Definition:** Components communicate by producing and consuming **events** — facts about things that happened — rather than by calling each other directly.

```
ORCHESTRATION (command-driven, synchronous, coupled)

  Order Service ──calls──► Payment Service
                ──calls──► Inventory Service
                ──calls──► Shipping Service
                ──calls──► Email Service
  (Order Service must know all four, and wait for all four)


CHOREOGRAPHY (event-driven, async, decoupled)

  Order Service ──publishes──► [ OrderPlaced ]
                                    │
                ┌───────────────────┼───────────────────┬──────────────┐
                ▼                   ▼                   ▼              ▼
         Payment Service    Inventory Service    Shipping Service  Email Service
  (Order Service knows NOTHING about who listens)
```

### Two fundamentally different event styles (know the difference — it matters enormously)

**1. Event Notification** — thin event, "something happened, go look it up"

```json
{ "type": "OrderPlaced", "orderId": "ord_8812", "occurredAt": "2026-09-12T10:00:00Z" }
```

- ✅ Small, low coupling to the producer's data shape
- ❌ Every consumer must call back to the producer → a chatty, coupled runtime and a load spike on the producer

**2. Event-Carried State Transfer** — fat event, carries the data

```json
{
  "type": "OrderPlaced",
  "orderId": "ord_8812",
  "occurredAt": "2026-09-12T10:00:00Z",
  "customer": { "id": "cus_31", "email": "a@b.com", "tier": "gold" },
  "items": [{ "sku": "X1", "qty": 2, "unitPrice": "19.99" }],
  "total": { "amount": "39.98", "currency": "USD" }
}
```

- ✅ Consumers are fully autonomous — they can work even if the producer is down
- ❌ Bigger messages, data duplication, and a **schema contract** you must now version carefully

> **Practical guidance:** default to event-carried state transfer for cross-service events (autonomy is the whole point), but keep events focused — carry what consumers need, not the entire aggregate.

### Strengths of EDA

- **Extreme decoupling** — add a new consumer without touching the producer. This is the superpower.
- **Resilience** — a down consumer just means a growing queue, not a failed user request
- **Natural buffering** — handles traffic spikes; the queue absorbs them
- **Auditability** — the event log is a record of everything that happened
- **Scalability** — add consumers to parallelise

### Weaknesses of EDA (the honest list)

- **Eventual consistency** — the system is briefly in a contradictory state, always
- **No single place shows the whole flow** — the business process exists only as an emergent property of many handlers. This is the #1 real-world complaint.
- **Debugging** requires correlation IDs and tracing, always
- **Ordering** is hard (Chapter 06)
- **Duplicates happen** — every consumer must be idempotent
- **Cyclic event storms** — A triggers B triggers C triggers A. Infinite loop, in production, at 3 AM.

### Choreography vs Orchestration — when to use which

| | Choreography (events) | Orchestration (a coordinator) |
|---|---|---|
| **How** | Each service reacts to events | One service directs the steps |
| **Coupling** | Very loose | Coordinator knows all participants |
| **Visibility of the flow** | Poor — scattered | Excellent — it is one readable file |
| **Adding a step** | Add a consumer, touch nothing else | Edit the coordinator |
| **Error handling** | Hard, distributed | Centralised, easier |
| **Best for** | 2–4 steps, simple reactions, "notify everyone" | 5+ steps, complex compensation, business-critical flows |

> **Practical rule:** use **choreography for simple fan-out reactions**, use **orchestration for business processes that must be understood, monitored and compensated** (order fulfilment, loan approval, KYC onboarding). Do not be dogmatic; most real systems mix both.

---

## 2.8 Event Streaming 🟡

**Definition:** Events go to a durable, ordered, replayable **log** that consumers read at their own pace — rather than to a queue that deletes messages after delivery.

| | Message Queue (RabbitMQ) | Event Stream (Kafka) |
|---|---|---|
| After consumption | Message is deleted | Event stays for the retention period |
| Consumers | Compete for messages | Each group reads everything independently |
| Position | Broker tracks it | Consumer tracks its own **offset** |
| Replay | No | **Yes — the killer feature** |
| Ordering | Per queue, weak with multiple consumers | Strict **per partition** |
| Typical scale | Thousands/sec | Millions/sec |

### Why replay changes architecture

Because the log is the source of truth, you can:
- Add a brand-new service and let it **rebuild its entire state** from history
- Fix a bug in a consumer, reset the offset, and **reprocess** the last 3 days correctly
- Run a new ML model over **all historical events** to backfill features
- Give analytics its own read of the same stream without touching production DBs

That is a genuinely different capability, not just "a faster queue". Full detail in Chapter 07.

---

## 2.9 Event Sourcing 🟡 (powerful, and frequently misused)

**Definition:** Instead of storing current state, store the **sequence of events** that produced it. Current state is derived by replaying them.

```
TRADITIONAL (state-oriented) — you know WHAT, never WHY

  accounts
  ┌────┬─────────┐
  │ id │ balance │
  │ 42 │  1500   │    ← how did it get here? Nobody knows.
  └────┴─────────┘


EVENT SOURCED — the history IS the data

  events (append-only)
  ┌─────┬────────────┬───────────────────┬──────────────────────┐
  │ seq │ account_id │ type              │ data                 │
  │  1  │     42     │ AccountOpened     │ {initial: 0}         │
  │  2  │     42     │ MoneyDeposited    │ {amount: 2000}       │
  │  3  │     42     │ MoneyWithdrawn    │ {amount: 600}        │
  │  4  │     42     │ FeeCharged        │ {amount: 15, why:..} │
  │  5  │     42     │ InterestPaid      │ {amount: 115}        │
  └─────┴────────────┴───────────────────┴──────────────────────┘

  balance = 0 + 2000 - 600 - 15 + 115 = 1500  (and you can prove it)
```

### What you gain

- **Complete audit trail, for free** — mandatory in finance, healthcare, insurance
- **Time travel** — "what was this customer's state on 3 March at 14:00?" is a trivial query
- **Debugging superpower** — replay the exact event sequence that caused the bug
- **New projections from old data** — the business asks for a report that needs data you never stored... except you did, in the events
- **The events *are* your integration** — publish them and other systems just work

### What you pay

- **Everything is harder.** Queries need projections; you cannot just `SELECT * WHERE balance > 1000`
- **Schema evolution of events is a serious discipline** — events are immutable and live forever; a v1 event from 2021 must still be readable in 2031
- **Snapshots needed** — replaying 4 million events on every load is not viable, so you snapshot every N events
- **GDPR "right to be forgotten" vs an immutable log** — a genuine conflict. Standard answer: **crypto-shredding** (encrypt personal fields with a per-subject key; delete the key)
- **Team learning curve is steep** — and a half-understood event-sourced system is a nightmare

```csharp
public class BankAccount
{
    public Guid Id { get; private set; }
    public decimal Balance { get; private set; }
    public int Version { get; private set; }
    private readonly List<object> _uncommitted = new();

    // Rebuild from history
    public static BankAccount Rehydrate(IEnumerable<object> history)
    {
        var acc = new BankAccount();
        foreach (var e in history) acc.Apply(e);
        return acc;
    }

    // Behaviour: validate, then RAISE an event (never mutate directly)
    public void Withdraw(decimal amount)
    {
        if (amount <= 0)        throw new ArgumentException("Amount must be positive");
        if (amount > Balance)   throw new InsufficientFundsException(Id, Balance, amount);
        Raise(new MoneyWithdrawn(Id, amount, DateTime.UtcNow));
    }

    private void Raise(object e) { Apply(e); _uncommitted.Add(e); }

    // Apply: pure state mutation, NO validation (history already happened)
    private void Apply(object e)
    {
        switch (e)
        {
            case AccountOpened o:  Id = o.AccountId; Balance = o.Initial; break;
            case MoneyDeposited d: Balance += d.Amount; break;
            case MoneyWithdrawn w: Balance -= w.Amount; break;
            case FeeCharged f:     Balance -= f.Amount; break;
        }
        Version++;
    }
}
```

> **Critical rule:** `Apply` never validates. Validation happens in the command method, *before* the event is raised. Once an event exists, it is a fact — you cannot reject history.

### When to use it

✅ **Yes:** financial ledgers, audit-heavy regulated domains, systems where "why" matters as much as "what", collaborative editing, inventory/stock movements.

❌ **No:** CRUD apps, simple catalogues, when the team has never done it before and the domain does not demand it, when "current state" is genuinely all anyone cares about.

> **Best practice:** use event sourcing for **one or two aggregates that truly need it** (the ledger, the KYC decision trail), not for the whole system. It is a tool, not a religion. And note: **CQRS is almost always required alongside it**, because querying an event log directly is impractical.

---

## 2.10 Serverless / FaaS 🟡

**Definition:** You deploy functions. The platform runs them on demand, scales them from zero to thousands, and bills you per invocation and per GB-second.

```
  HTTP request ──► API Gateway ──► Lambda/Azure Function ──► DynamoDB
  S3 upload    ──────────────────► Lambda (thumbnail)
  Queue message ─────────────────► Lambda (process)
  Cron schedule ─────────────────► Lambda (nightly job)
```

### Genuine strengths

- **No servers to patch, scale or monitor**
- **Scale to zero** — pay literally nothing when idle. Unbeatable for spiky or low-volume workloads.
- **Automatic scaling** — 1 to 10,000 concurrent executions without a capacity plan
- **Event-native** — glue between cloud services with ~10 lines of code
- **Fast to start** — a working endpoint in an afternoon

### Genuine weaknesses

| Problem | Detail |
|---------|--------|
| **Cold starts** | First invocation after idle: 100 ms (Go/Node) to several seconds (JVM/.NET with big dependencies). Bad for latency-sensitive user paths. Mitigations: provisioned concurrency (costs money, defeats scale-to-zero), smaller packages, snapshot/AOT startup. |
| **Execution time limits** | Typically 15 minutes max. No long-running jobs. |
| **Vendor lock-in** | Deepest of any cloud choice — your event wiring *is* the vendor |
| **Local development & testing** | Better than it was, still worse than a container |
| **Database connections** | 5,000 concurrent lambdas × 1 connection each = a dead Postgres. You need a proxy/pooler (RDS Proxy, PgBouncer) — a classic, expensive surprise. |
| **Cost at steady high volume** | At constant load, a reserved VM is dramatically cheaper. There is a real crossover point — know where yours is. |
| **Distributed complexity** | 60 functions is 60 deployables. All of Chapter 05 applies. |

### When serverless is the right call

✅ Spiky, unpredictable, or low traffic
✅ Event-driven glue (file uploaded → resize; message arrived → process)
✅ Scheduled jobs and cron
✅ Rapid prototypes and internal tools
✅ Genuinely bursty batch work (fan out 1,000 parallel executions for 20 seconds)

❌ Steady high-throughput services
❌ Sub-50 ms latency requirements on a user-facing path
❌ Long-running computation (video transcoding, model training)
❌ WebSocket-heavy stateful workloads (possible, but awkward)
❌ When your team has no cloud-ops maturity — "serverless" does not mean "ops-free"

> **Note the broader meaning:** "serverless" now also includes managed databases (DynamoDB, Aurora Serverless, Cosmos DB), queues (SQS), and containers-that-scale-to-zero (Cloud Run, Container Apps, Fargate). **Serverless containers are often the sweet spot** — you keep a normal app and a normal Docker image, but pay per use and scale automatically.

---

# PART B — Internal code organisation styles

## 2.11 Layered (n-tier) architecture 🟢

The most common structure in the world.

```
┌─────────────────────────────────────┐
│   Presentation  (controllers, UI)   │
├─────────────────────────────────────┤
│   Business Logic (services)         │
├─────────────────────────────────────┤
│   Data Access   (repositories, ORM) │
├─────────────────────────────────────┤
│   Database                          │
└─────────────────────────────────────┘
        Dependencies point DOWN
```

**Rules:** each layer may only call the layer directly below (a *closed* layer). Sometimes a layer is *open* (may be skipped) — say so explicitly if you allow that, because "sometimes skip it" quietly becomes "always skip it".

**Pros:** everyone understands it instantly; easy to onboard; clear separation of technical concerns.

**Cons (important):**

1. **The database ends up at the centre.** Dependencies point down, toward the DB, so the data model drives the design and business rules get shaped by table structures.
2. **"Sinkhole" anti-pattern** — many requests just pass straight through every layer doing nothing (controller → service → repo → SELECT → back). If 80% of your calls are pass-through, the layers are costing you more than they give.
3. **Layers are technical, not business.** A single feature change touches all layers, in different folders, which is the opposite of high cohesion.
4. It says nothing about **modularity** — a layered monolith still becomes a mud ball.

**Verdict:** fine for small/simple apps and CRUD. For anything with real business complexity, prefer hexagonal/clean (below), which is layered but with the dependency arrow *inverted*.

---

## 2.12 Hexagonal Architecture (Ports & Adapters) 🟢

**Alistair Cockburn's idea:** the application sits in the middle. Everything external — UI, database, queue, vendor API — is *outside* and plugs in through **ports** (interfaces) via **adapters** (implementations).

```
                    ┌──── DRIVING (primary) side ────┐
                    │  things that USE the app       │
                    ▼                                ▼
        ┌────────────────┐              ┌────────────────┐
        │ REST Controller│              │  CLI / Worker  │
        │   (adapter)    │              │   (adapter)    │
        └───────┬────────┘              └───────┬────────┘
                │  implements/calls               │
        ┌───────▼─────────────────────────────────▼────────┐
        │            PORT (inbound interface)              │
        │  ┌────────────────────────────────────────────┐  │
        │  │                                            │  │
        │  │        APPLICATION + DOMAIN CORE           │  │
        │  │   (pure business logic, zero frameworks)   │  │
        │  │                                            │  │
        │  └────────────────────────────────────────────┘  │
        │           PORT (outbound interfaces)             │
        └───────┬─────────────────────────────────┬────────┘
                │                                 │
        ┌───────▼────────┐              ┌─────────▼──────┐
        │ PostgresRepo   │              │ VendorFaceApi  │
        │   (adapter)    │              │   (adapter)    │
        └────────────────┘              └────────────────┘
                    ▲                                ▲
                    └──── DRIVEN (secondary) side ───┘
                       things the app USES
```

**The one rule:** **all dependencies point inward.** The core knows nothing about HTTP, SQL, Kafka or any vendor.

```python
# ── CORE: ports (interfaces the core owns) ───────────────────────────
class SessionRepository(Protocol):                  # outbound port
    async def get(self, id: SessionId) -> Session | None: ...
    async def save(self, session: Session) -> None: ...

class FaceAnalyser(Protocol):                       # outbound port
    async def analyse(self, video: bytes) -> Signals: ...

class VerifyUseCase(Protocol):                      # inbound port
    async def execute(self, cmd: VerifyCommand) -> VerificationResult: ...

# ── CORE: the application, depends ONLY on ports ─────────────────────
class VerifyService(VerifyUseCase):
    def __init__(self, repo: SessionRepository, analyser: FaceAnalyser):
        self._repo, self._analyser = repo, analyser

    async def execute(self, cmd: VerifyCommand) -> VerificationResult:
        session = await self._repo.get(cmd.session_id) or Session.start(cmd.session_id)
        signals = await self._analyser.analyse(cmd.video)
        session.record_attempt(signals)
        await self._repo.save(session)
        return session.result()

# ── ADAPTERS: outside, and they depend on the core ───────────────────
class PostgresSessionRepository:      # implements SessionRepository
    ...
class OnnxFaceAnalyser:               # implements FaceAnalyser
    ...
class InMemorySessionRepository:      # a test adapter — this is the payoff
    ...
```

### The practical payoff

- **Test the entire application logic with in-memory adapters** — no DB, no network, milliseconds
- **Swap infrastructure** without touching business code
- The **same core** can be driven by HTTP, a CLI, a queue consumer, or a test
- Your business logic **outlives** your framework (frameworks have a ~5 year fashion cycle; your domain does not)

---

## 2.13 Onion Architecture & Clean Architecture 🟢

Both are refinements of the same idea as hexagonal. The differences are mostly vocabulary.

```
              ┌────────────────────────────────────────┐
              │   Frameworks & Drivers                 │   ← Web, DB, UI, devices
              │  ┌──────────────────────────────────┐  │
              │  │  Interface Adapters              │  │   ← Controllers, Presenters,
              │  │  ┌────────────────────────────┐  │  │     Gateways, Repositories(impl)
              │  │  │ Application Business Rules │  │  │   ← Use Cases
              │  │  │  ┌──────────────────────┐  │  │  │
              │  │  │  │ Enterprise Business  │  │  │  │   ← Entities
              │  │  │  │       Rules          │  │  │  │
              │  │  │  └──────────────────────┘  │  │  │
              │  │  └────────────────────────────┘  │  │
              │  └──────────────────────────────────┘  │
              └────────────────────────────────────────┘

                 THE DEPENDENCY RULE:
        source code dependencies point only INWARD.
        Nothing inner knows anything about anything outer.
```

### Typical .NET solution layout

```
src/
├── MyApp.Domain/              ← entities, value objects, domain events, domain services
│   └── (references: NOTHING. Not even EF Core. Not even ASP.NET.)
├── MyApp.Application/         ← use cases, DTOs, port interfaces (IOrderRepository)
│   └── (references: Domain)
├── MyApp.Infrastructure/      ← EF Core, HTTP clients, file storage, message bus
│   └── (references: Application, Domain)
├── MyApp.Api/                 ← controllers, middleware, DI composition root
│   └── (references: Application, Infrastructure)
└── tests/
    ├── MyApp.Domain.Tests/         ← pure, fast, no mocks needed
    └── MyApp.Application.Tests/    ← fake adapters
```

**The compile-time test:** delete `MyApp.Infrastructure` and `MyApp.Api`. Does `MyApp.Domain` still build? If yes, you have it right.

### Honest criticism

Clean Architecture on a small CRUD app produces 4 projects, 6 files and 3 mapping steps for one `GET /products` endpoint. That is **ceremony, not architecture**.

> **Use it when the business logic is genuinely complex or long-lived.** For a simple CRUD service, a well-organised layered app — or even "vertical slices" (below) — is the professional choice.

### Vertical Slice Architecture (the modern alternative worth knowing) 🟡

Instead of organising by *technical layer*, organise by *feature*:

```
Features/
├── Verification/
│   ├── StartSession/
│   │   ├── StartSessionCommand.cs
│   │   ├── StartSessionHandler.cs
│   │   ├── StartSessionValidator.cs
│   │   └── StartSessionEndpoint.cs
│   └── SubmitVideo/
│       ├── SubmitVideoCommand.cs
│       ├── SubmitVideoHandler.cs
│       └── SubmitVideoEndpoint.cs
└── Billing/
    └── GenerateInvoice/
        └── ...
```

Everything for one feature is in one folder. Changing a feature touches one folder. Each slice can be as simple or as layered as *it* needs. This maximises cohesion and is increasingly the preferred style for teams that found Clean Architecture too ceremonial. It pairs very naturally with CQRS.

---

## 2.14 Pipes and Filters 🟡

**Definition:** Data flows through a sequence of independent processing steps, each with one input and one output.

```
  Video ──► [Extract    ] ──► [Quality  ] ──► [Detect ] ──► [Score  ] ──► Result
            [ Frames    ]     [ Check   ]     [ Faces ]     [Liveness]
```

Each filter:
- Knows nothing about the others
- Can be tested alone
- Can be reordered, replaced, or run in parallel
- Can be independently scaled (if the pipes are queues)

```python
class Stage(Protocol):
    def process(self, ctx: PipelineContext) -> PipelineContext: ...

class Pipeline:
    def __init__(self, stages: list[Stage]):
        self._stages = stages

    def run(self, ctx: PipelineContext) -> PipelineContext:
        for stage in self._stages:
            ctx = stage.process(ctx)
            if ctx.should_stop:                 # early exit on rejection
                break
        return ctx

pipeline = Pipeline([
    FrameExtractionStage(),
    QualityCheckStage(min_brightness=40, min_sharpness=0.6),
    FaceDetectionStage(),
    HeadPoseStage(),
    AntiSpoofStage(),
    ChallengeValidationStage(),
    ScoringStage(),
])
```

**Where you see it:** ETL/data pipelines, image and video processing, compilers, HTTP middleware, Unix shell pipes (`cat x | grep y | sort | uniq -c`), CI/CD pipelines, ML inference pipelines.

**Trade-offs:** wonderfully modular and testable; but the shared context object can become a god object, and passing large payloads between stages can be expensive (pass references, not bytes).

---

## 2.15 Microkernel / Plugin Architecture 🟡

**Definition:** A minimal core system plus plug-in modules that add features.

```
        ┌─────────────────────────────────┐
        │         CORE SYSTEM             │
        │  (registry, lifecycle, routing) │
        └───┬─────────┬─────────┬─────────┘
            │         │         │
      ┌─────▼───┐┌────▼────┐┌───▼─────┐
      │ Plugin  ││ Plugin  ││ Plugin  │
      │ Passport││   NID   ││ Licence │
      │ Reader  ││ Reader  ││ Reader  │
      └─────────┘└─────────┘└─────────┘
```

**Real examples:** VS Code, Eclipse, WordPress, Jenkins, Chrome extensions, Kubernetes (CRDs + controllers), Terraform providers, browser rendering engines.

```csharp
public interface IDocumentPlugin
{
    string DocumentType { get; }
    string Version { get; }
    bool CanHandle(DocumentImage image);
    Task<ExtractedData> ExtractAsync(DocumentImage image, CancellationToken ct);
}

public class DocumentPluginRegistry
{
    private readonly IReadOnlyList<IDocumentPlugin> _plugins;
    public DocumentPluginRegistry(IEnumerable<IDocumentPlugin> plugins) => _plugins = plugins.ToList();

    public IDocumentPlugin Resolve(DocumentImage image)
        => _plugins.FirstOrDefault(p => p.CanHandle(image))
           ?? throw new UnsupportedDocumentException();
}
// Adding support for a new country's ID card = one new class. Core untouched.
```

**Use when:** you must support many variants of the same operation, especially variants added by others (customers, partners, a community) or per-tenant. **Do not use when** you control all the variants and there are three of them — a Strategy is enough.

**Key design questions for plugin systems:** versioning of the plugin contract, isolation (does a crashing plugin kill the host?), security (can a plugin read other tenants' data?), and discovery (config file, DI scan, dynamic assembly load).

---

## 2.16 Space-Based Architecture ⚪

**Problem it solves:** extreme, unpredictable concurrent load, where the *database* is the bottleneck.

**Idea:** remove the central database from the request path entirely. Keep data in a replicated in-memory data grid across processing units; persist asynchronously in the background.

Used in: high-frequency trading, ticketing systems for concert on-sales, betting platforms. Technologies: Hazelcast, Apache Ignite, GigaSpaces, Redis Enterprise.

**Awareness is enough** — but recognise the shape, because "our DB is the bottleneck and we cannot shard fast enough" is exactly the symptom it treats.

---

# PART C — Choosing

## 2.17 The decision table

| If your situation is… | Choose |
|----------------------|--------|
| Startup, < 10 devs, unclear domain | **Modular monolith** |
| Established product, 10–30 devs, some parts scale differently | **Modular monolith + 2–4 extracted services** |
| 50+ devs, clear bounded contexts, mature DevOps | **Microservices** |
| Enterprise, lots of legacy to bridge | **SOA / integration layer + new services** |
| Spiky/low traffic, event glue, cron jobs | **Serverless** |
| Many async reactions, high decoupling needs | **Event-driven** |
| Audit and "why" are legally required | **Event sourcing** (for those aggregates) |
| Multi-step data transformation | **Pipes and filters** |
| Many variants, third-party extensibility | **Plugin / microkernel** |
| Complex business rules, long-lived product | **Hexagonal / Clean** inside whatever topology |
| Simple CRUD | **Layered** or **vertical slices** |

## 2.18 The modular monolith vs microservices decision — properly

This is the decision you will be asked about most. Do not answer with fashion. Answer with **forces**.

### The forces that genuinely justify extracting a service

| Force | Example | Is it real for you? |
|-------|---------|--------------------|
| **Independent scaling** | Video processing needs GPUs and 30 pods; the rest needs 2 | Measure first. Vertical scaling is cheap and goes a long way. |
| **Independent deploy cadence** | One team ships hourly, another monthly (regulated) | Real and common |
| **Technology mismatch** | ML in Python, the rest in .NET | Very real |
| **Team autonomy at scale** | 8 teams blocked by one CI pipeline | Real past ~25 devs |
| **Fault isolation** | The report generator must never take down checkout | Real — but a bulkhead inside a monolith can also do this |
| **Regulatory isolation** | Card data must live in a PCI-scoped boundary | Real and non-negotiable |
| **Different availability needs** | Public API needs 99.99%; admin portal needs 99% | Real |

### Forces that are NOT good reasons

- ❌ "It is modern / everyone does it"
- ❌ "Our code is messy" (it will still be messy, just with network calls between the messes)
- ❌ "We might need to scale someday" (YAGNI — Chapter 01)
- ❌ "We want to use the new framework" (do it in one module)
- ❌ "The CTO read an article"

### The extraction recipe (when the force is real)

```
1. Make it a proper MODULE first (clean API, own schema, no cross-reads)
2. Let it stabilise — if the API churns weekly, the boundary is wrong
3. Move its tables to their own database (still in-process)
4. Replace in-process calls with network calls behind the SAME interface
5. Split the deployment
6. Give it its own pipeline, dashboards, alerts and on-call runbook
```

Steps 1–3 are the valuable ones, and they are reversible. If you cannot complete step 1, you are **not ready** for step 6 — and the failure to do step 1 is exactly how distributed monoliths are born.

---

## 2.19 Common mistakes

1. **Choosing microservices before you have the prerequisites** (CI/CD, tracing, ops maturity, domain clarity)
2. **Splitting by technical layer instead of business capability** — `user-api`, `user-service`, `user-db` is not three services, it is one service in three deployments
3. **Believing the topology fixes code quality** — it does not, ever
4. **Shared database between services** — the single most reliable way to build a distributed monolith
5. **Synchronous call chains 5 deep** — you multiplied failure probability and summed latency
6. **Applying Clean Architecture ceremony to trivial CRUD** — 6 files to return a list
7. **Event sourcing the whole system** because it was interesting
8. **No enforcement of module boundaries** — "we'll be disciplined" is never true after month three; use fitness functions
9. **Never merging services back** — if two always change together, merging is the right call
10. **Ignoring Conway's Law** — the org chart will beat your diagram every time

---

## 2.20 Architect's checklist

- [ ] Have I chosen a **deployment style** and an **internal style** separately and deliberately?
- [ ] Can I name the specific **force** that justifies each service boundary?
- [ ] Does every service own its own data, with no cross-service table reads?
- [ ] Is there any synchronous chain longer than 3 hops? What is its computed availability?
- [ ] Are module boundaries enforced by tooling, not by hope?
- [ ] If we chose microservices — do we have CI/CD, tracing, logging and on-call for **every** service?
- [ ] If we chose event-driven — where is the business process documented, given no single file shows it?
- [ ] Does the team's size and skill match this topology?
- [ ] Is the domain layer free of frameworks? (Can I delete Infrastructure and still compile?)
- [ ] What is our path back if this choice is wrong?

---

## 2.21 Self-test

1. What are the two independent axes of "architecture style"? Give an example combining them.
2. Why is a modular monolith usually better than microservices for a 12-person team?
3. Give five diagnostic signs of a distributed monolith.
4. Five services at 99.9% each, called synchronously in a chain — what is the availability? Show the maths.
5. Event notification vs event-carried state transfer: give the trade-off and a default recommendation.
6. When should you use choreography, and when orchestration?
7. What does event sourcing give you that a normal database plus an audit table does not?
8. Name four situations where serverless is the wrong choice.
9. What is "the dependency rule" in Clean Architecture, and what is the compile-time test for it?
10. What is the "sinkhole" anti-pattern in layered architecture?
11. List four forces that genuinely justify extracting a microservice, and three that do not.
12. Describe the six-step recipe for extracting a service from a modular monolith.

---

## 2.22 Key takeaways

- **Deployment style and code style are independent** — decide both, on purpose
- **Start with a modular monolith.** It is the highest-value default for most teams
- **Microservices are a solution to an organisational problem**, sold as a technical one — their real benefit is independent teams and deploys
- The **distributed monolith** is the most common failure mode; shared data is its root cause
- **EDA buys decoupling and pays with eventual consistency and lost visibility**
- **Event sourcing is powerful and expensive** — use it where "why" is legally or commercially required
- **Hexagonal/Clean inverts the dependency arrow** so business logic outlives frameworks
- **If two services always change together, they are one service**
- Every style is a **trade-off**; name yours out loud

---

**Next:** [Chapter 03 — Domain-Driven Design](03-domain-driven-design.md)
