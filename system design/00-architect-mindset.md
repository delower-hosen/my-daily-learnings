# Chapter 00 — The Architect Mindset 🟢

> Before technology. Before diagrams. Before cloud.
> This chapter is the operating system that runs all the other chapters.

---

## 0.1 What an architect actually does

Let us kill the myth first.

**Myth:** An architect is a very senior developer who chooses the technology.

**Reality:** An architect is the person who **makes the expensive decisions early, with incomplete information, and writes down why.**

Think about building a house.

| House | Software |
|-------|----------|
| Where the load-bearing walls go | Service boundaries, data ownership |
| How many floors | Scaling model |
| Plumbing and wiring routes | Networking, messaging, integration |
| Foundation depth | Data model, consistency model |
| Paint colour in the bedroom | Which logging library |

You can repaint a bedroom on Saturday. You **cannot** move a load-bearing wall on Saturday.

> **Architecture = the decisions that are expensive to change later.**

That is the cleanest definition in this book. Memorise it.

If a decision is cheap to reverse, it is **not** architecture — let the team decide it. If a decision will cost six months and three arguments to reverse, it **is** architecture — and it is your job.

### The daily reality of the role

A week in the life looks roughly like this:

- 30% — asking questions (of business people, of developers, of vendors)
- 25% — drawing and writing (diagrams, ADRs, one-pagers)
- 20% — reviewing (designs, PRs at the boundary level, vendor proposals)
- 15% — prototyping / proving a risky assumption with real code
- 10% — saying "no", or better, "yes, and here is the cost"

Notice how little of it is typing production code. That surprises people. But also notice the 15% prototype time — **an architect who has stopped touching code becomes a PowerPoint architect within 18 months.** Keep your hands dirty.

---

## 0.2 Problem vs Solution — the first discipline

Beginners hear a request and immediately think of a solution.

> Business: *"We need a Kafka cluster."*
> Junior architect: *"OK, let me size the brokers."*
> Real architect: *"Interesting — what problem made you say Kafka?"*

Nine times out of ten the answer is something like *"our nightly report is slow"* or *"the sales team wants to see orders in real time."* Neither of those necessarily needs Kafka.

### The technique: Five Whys, but polite

Real conversation, from a loan company:

> **Them:** We want to move to microservices.
> **You:** What would get better for you if we did?
> **Them:** Releases would be faster.
> **You:** What makes releases slow today?
> **Them:** Every release needs 3 days of manual regression testing.
> **You:** Why manual?
> **Them:** We have no automated tests on the loan calculation module.
> **You:** So if we automated tests on that one module, releases would be fast again?
> **Them:** …yes, probably.

You just saved the company 18 months and $2M. **That is architecture.** The microservices migration was a *solution* pretending to be a *problem statement*.

### Problem statement template

Write it in one sentence, with a number in it:

> "Today, **[who]** cannot **[do what]** because **[constraint]**, which costs us **[measurable pain]**."

Examples:

- "Today, **operations staff** cannot **see a failed KYC check until the next morning**, because **results are written to a nightly batch file**, which costs us **~40 abandoned customer applications per week**."
- "Today, **the mobile app** cannot **show search results in under 3 seconds during evening peak**, because **every search hits the main Postgres**, which costs us **a 12% drop-off on the search page**."

If you cannot fill in this sentence, **you are not ready to design anything.**

---

## 0.3 Functional vs Non-Functional Requirements

### Functional requirements (FR) — *what the system does*

- A user can upload a selfie video
- The system detects whether the face is live
- An admin can see the verification history

They read like verbs. They come from the business. They go in your backlog.

### Non-functional requirements (NFR) — *how well the system does it*

- Verification must complete in under 4 seconds at the 95th percentile
- The system must handle 500 verifications per minute at peak
- 99.9% availability during business hours
- Face images must be deleted after 90 days (legal requirement)
- No personal data may leave the country

> **Architecture is driven far more by NFRs than by FRs.**

This is the single most important sentence in this chapter. Two systems with *identical* features can have *completely different* architectures because of NFRs.

**Same feature, "upload a photo":**

| NFR | Resulting architecture |
|-----|------------------------|
| 10 users, photos can take 10 seconds | Single app server, save to local disk. Done in an afternoon. |
| 10 million users, under 200 ms, 99.99% up, GDPR delete | CDN + presigned S3 upload + queue + worker fleet + multi-region replication + audit log + deletion pipeline |

Same sentence in the requirements document. Two *entirely* different systems and two entirely different budgets.

### The NFR checklist (ask all of these, every time)

Print this. Use it in every kickoff meeting.

| # | NFR | The question to ask |
|---|-----|---------------------|
| 1 | **Performance** | How fast, at which percentile? (p50/p95/p99) |
| 2 | **Scalability** | How many users/requests today? In 2 years? What is the peak vs average? |
| 3 | **Availability** | What happens to the business if it is down for 1 hour? For 1 day? |
| 4 | **Durability** | If we lose this data, can we recreate it? From where? |
| 5 | **Consistency** | Is it OK if two users briefly see different answers? |
| 6 | **Security** | Who must never see this data? What is the worst-case leak? |
| 7 | **Privacy / Compliance** | GDPR? PCI-DSS? HIPAA? Data residency? Retention period? |
| 8 | **Observability** | When it breaks at 3 AM, how do we find out why? |
| 9 | **Maintainability** | Who runs this in 3 years? How big is that team? |
| 10 | **Cost** | What is the monthly budget? Cost per transaction? |
| 11 | **Portability** | Must it run on-premise too? Multi-cloud? |
| 12 | **Interoperability** | What must it talk to? Which legacy systems? |
| 13 | **Auditability** | Must we prove who did what, and keep it how long? |
| 14 | **Localisation** | Languages, currencies, time zones, right-to-left text? |

**Real-life trick:** ask #3 as *"If this system is down for one full day, what happens?"* The answers are wonderfully clarifying:

- *"We lose maybe $200."* → one server is fine
- *"We lose $2M and get sued."* → now we talk about multi-region
- *"People could die."* → now we talk about formal verification, and you should be very awake

Business people can never answer *"do you need 99.9% or 99.99%?"* — but they can always answer *"what happens if it is down for a day?"* **Translate NFRs into business language, always.**

---

## 0.4 Constraints

A constraint is something you **cannot** change. It is a wall, not a preference.

Three kinds:

**1. Technical constraints**
- "We must use SQL Server, the company has a licence and a DBA team"
- "The legacy mainframe only accepts fixed-width files over SFTP"
- "Devices in the field are on 2G networks"

**2. Business constraints**
- "Must go live before the regulation deadline on March 31"
- "Budget is $50,000, total"
- "We have 4 developers, two of them junior"

**3. Organisational constraints**
- "The payments team will not give us database access"
- "Security team requires 6 weeks to approve any new vendor"
- "The company is being acquired; no long-term commitments"

### Conway's Law — the constraint people forget

> *"Organisations design systems which are copies of their communication structures."* — Melvin Conway, 1967

Plain English: **your architecture will end up looking like your org chart, whether you like it or not.**

If you have three teams — Frontend, Backend, Database — you will get a three-layer architecture, guaranteed. Not because it is right, but because that is who talks to whom.

If you want microservices owned end-to-end, you must first create **teams** that own a business capability end-to-end. This is called the **Inverse Conway Manoeuvre**: change the teams to get the architecture you want.

**Real example:** A bank wanted to split their monolith into 8 microservices. They kept one shared database team. Result after 2 years: 8 services, all writing to the same database, all deployed together every Thursday night. They built a **distributed monolith** — all the pain of distribution, none of the benefits. The org chart won, as it always does.

> Architect rule: **Before you draw the system, draw the teams.**

---

## 0.5 Assumptions

An assumption is something you believe but have not verified. They are not bad — you cannot verify everything. What is bad is **hidden** assumptions.

**Always write them down, visibly:**

> **Assumptions**
> A1. Peak traffic is 3× average traffic. *(Not measured — from the ops team's memory.)*
> A2. Each video is ≤ 5 MB. *(Mobile team says yes; not enforced in code today.)*
> A3. The vendor's face API responds within 800 ms. *(Their SLA page; we have not load-tested it.)*
> A4. Users will not verify more than twice a day. *(Product team's guess.)*

Now two magic things happen:

1. Anyone reading the design can say *"A3 is wrong, we measured 3 seconds last month"* — and you fix the design before you build it.
2. When the system fails in production, you can check the assumptions list first. Usually the failure is an assumption that was wrong.

**War story:** A team designed an image pipeline assuming average image size of 2 MB. They launched. Users uploaded 40 MB photos from new phones. Memory blew up, the service crashed hourly. The assumption was in someone's head, never written, never validated. Two lines in a document would have prevented a three-week firefight.

> **Rule: every assumption must have an owner and a plan to verify it.**

---

## 0.6 Risks

A risk is a bad thing that *might* happen. Architecture is largely **risk management**.

Use a simple table — do not over-engineer this:

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|------|-----------|--------|------------|-------|
| R1 | Vendor face API goes down | Medium | High — no verifications possible | Second vendor behind a common interface; circuit breaker; queue and retry | Delower |
| R2 | GPU costs exceed budget at scale | High | Medium | Cost alert at 70% of budget; batch small requests; benchmark CPU fallback | Finance + Arch |
| R3 | Team has no Kubernetes experience | High | High — outage with nobody to fix | Use managed PaaS for v1; train team in parallel | Eng Manager |
| R4 | New privacy law lands mid-build | Low | High | Keep PII in one service behind one interface | Legal + Arch |

### The three risk strategies

1. **Avoid** — change the design so the risk cannot happen ("do not store the card number at all")
2. **Mitigate** — reduce likelihood or impact (retry, fallback, circuit breaker, backup)
3. **Accept** — write it down and move on ("if AWS us-east-1 dies, we are down; the business accepts this")

**Accepting a risk consciously and in writing is a legitimate, professional decision.** What is *not* professional is not knowing the risk exists.

### Spike first, then design

For the biggest technical risk, do not argue in a meeting. **Build a spike**: 1–3 days of throwaway code that answers one question.

- "Can the vendor API actually handle 100 concurrent requests?" → write a load script, find out
- "Does this ORM support our partitioning scheme?" → try it

An architect who proves risky assumptions with a spike is worth ten who debate them in meetings.

---

## 0.7 Trade-offs — the heart of the job

> **There are no right answers in architecture. There are only trade-offs.**
> *(Neal Ford & Mark Richards — remember this quote, it is the most quoted line in the field.)*

Every single choice costs you something. The junior sees the benefit. The architect sees the price.

| You gain | You pay with |
|----------|--------------|
| Caching → speed | Staleness, cache invalidation bugs, more moving parts |
| Microservices → independent deploys | Network failures, distributed debugging, eventual consistency, ops load |
| Strong consistency → correctness | Latency, lower availability during partitions |
| Denormalisation → fast reads | Duplicate data, harder writes, update anomalies |
| Async messaging → resilience, decoupling | Eventual consistency, ordering problems, harder to trace |
| More abstraction → flexibility | Cognitive load, indirection, slower onboarding |
| Managed cloud service → less ops work | Vendor lock-in, higher unit cost, less control |
| Multi-region → survives a region outage | 2× cost, replication lag, data-residency headaches |
| Third-party library → speed to market | Supply-chain risk, licence risk, upgrade treadmill |

### How to present a trade-off (the professional format)

Never say *"Kafka is better."* Say this instead:

> **Decision:** Use RabbitMQ instead of Kafka for order events.
>
> **Because:** Our volume is 200 messages/second, we need per-message retry and dead-lettering, and the team has 3 years of RabbitMQ experience.
>
> **We give up:** Event replay from the beginning of time, and high-volume stream processing.
>
> **We accept this because:** No current or planned use case needs replay, and 200 msg/s is 1% of what a single RabbitMQ node handles.
>
> **We will revisit if:** Volume passes 20,000 msg/s, or analytics needs to replay history.

That last line — the **trigger to revisit** — is what separates a professional decision from a religious one.

---

## 0.8 Cost vs Complexity

Every architecture has two prices:

1. **The money price** — servers, licences, cloud bills
2. **The complexity price** — how many things must a human hold in their head to change this safely?

Junior engineers optimise money. Architects optimise complexity, because **complexity is paid every single day, by every single developer, forever.**

### The complexity budget

Imagine your team has a fixed budget of complexity — say 100 points. You spend it on:

- The business domain itself (unavoidable — this is **essential complexity**)
- The technology you chose (avoidable — this is **accidental complexity**)

If your domain is genuinely complex (insurance underwriting, tax calculation), you must spend **almost all** your budget there and keep the technology boring. If your domain is simple (a blog), you can afford fancier technology — but why would you?

> **Choose Boring Technology.** For each project you get roughly three "innovation tokens". Spend them on the thing that actually differentiates your product. Everything else should be the most boring, well-understood option available.

**Real example:** A 5-person startup building a KYC product chose Kubernetes + Istio + Kafka + Cassandra + gRPC + a custom CI platform. They spent 14 months on infrastructure and shipped no differentiating features. A competitor shipped on Postgres + a Django monolith + one managed queue, won the market, and *then* rebuilt the parts that hurt. The second team was not less skilled. They just knew where to spend the complexity.

### The cost conversation

Architects must speak money. Learn these:

- **CapEx vs OpEx** — buying servers (capital) vs renting cloud (operating expense). Finance departments care enormously about this difference.
- **TCO (Total Cost of Ownership)** — licence + hardware + people + training + migration + the cost of *not* doing something else
- **Unit economics** — "cost per verification", "cost per 1000 API calls". This is the number a CTO can act on.
- **Cost of delay** — if launching 3 months late costs $1M in lost revenue, then a $100K shortcut is cheap

> A good architect can say: *"Option A costs $4,000/month and takes 6 weeks. Option B costs $1,200/month and takes 14 weeks. At our current growth, B pays back the extra 8 weeks in 11 months."*
> That sentence gets you into the room where decisions are made.

---

## 0.9 Build vs Buy

The question: should we write this ourselves, or pay someone?

### Decision framework

Ask: **is this a core differentiator?**

```
Is this capability what customers pay us for?
├── YES → BUILD. Never outsource your competitive edge.
└── NO  → Is there a mature product that covers ≥ 80% of our need?
          ├── YES → BUY (and adapt our process to their 80%)
          └── NO  → Is the remaining 20% worth the build + maintain cost, forever?
                    ├── YES → BUILD (and be honest: it is a product now, it needs an owner)
                    └── NO  → BUY and live with the gap, or defer the capability
```

### Real examples

| Need | Decision | Why |
|------|----------|-----|
| Authentication for a fintech app | **Buy** (Auth0/Keycloak/Entra ID) | Not your differentiator; the security cost of getting it wrong is enormous |
| The liveness detection algorithm in a liveness product | **Build** | This *is* the product |
| Sending transactional email | **Buy** (SES/SendGrid) | Deliverability is a specialist dark art |
| Internal admin dashboard | **Build** (small) or buy low-code | Cheap either way; not customer-facing |
| Payment processing | **Buy** | PCI-DSS compliance alone will eat a year |
| Video transcoding for a video platform | **Build/tune** | Cost per minute is your margin |
| Logging & metrics | **Buy** until the bill hurts, then reconsider | Observability vendors get expensive at scale — a known crossover point |

### The hidden costs of "buy"

- Vendor lock-in and price increases at renewal (they *know* migrating is expensive)
- Their roadmap is not your roadmap
- Their outage is your outage, and you cannot fix it — you can only wait and update your status page
- Data leaving your boundary → compliance review
- Integration work is never zero; budget 20–40% of the "saved" effort

### The hidden costs of "build"

- The initial build is roughly **30%** of the lifetime cost. Maintenance, security patches, on-call, and documentation are the other 70%.
- The person who built it will leave
- You now own a product nobody wants to own

> **Rule of thumb:** Buy the boring, build the unique. And whichever you choose, **hide it behind your own interface** (see Anti-Corruption Layer in Chapter 03) so you can change your mind later at moderate cost.

---

## 0.10 Short-term vs Long-term

The classic fight:

> **Business:** "We need it in 6 weeks."
> **Engineer:** "Doing it properly takes 6 months."

Both are right. The architect's job is to find the path that ships in 6 weeks **without closing the door** on the 6-month version.

### The technique: keep options open at the boundaries

You can take shortcuts *inside* a component. You must be careful at the *boundaries* between components.

**Ship fast, safely:**
- One database, but **separate schemas per module** → you can split later
- One deployable, but **clean module boundaries in code** → you can extract a service later
- Synchronous call now, but **behind an interface** → you can make it async later
- Hard-coded rules now, but **in one class named `PricingPolicy`** → you can move it to a rules engine later

**Ship fast, dangerously:**
- Every module reads every other module's tables directly
- Business logic mixed into controllers and stored procedures
- The vendor SDK's types used as your domain model everywhere
- No tests on the money-calculating code

Both approaches ship in 6 weeks. One costs 3 weeks to evolve; the other costs 9 months.

> **The skill is not "do it perfectly". The skill is "take on debt in the places where it is cheap to repay."**

---

## 0.11 Technical Debt

The metaphor (from Ward Cunningham): shipping imperfect code is like taking a loan. You go faster now. You pay **interest** — every future change in that area costs more.

### Four kinds of debt (Martin Fowler's quadrant)

| | **Reckless** | **Prudent** |
|---|---|---|
| **Deliberate** | "We don't have time for design." | "We ship now and deal with the consequences — here is the ticket." |
| **Inadvertent** | "What's layering?" | "Now we know how we should have done it." |

- **Prudent + Deliberate** is *good engineering*. Do this often, with a written note.
- **Inadvertent + Prudent** is *learning*. Unavoidable and healthy.
- **Reckless** in either form is what kills companies.

### Managing debt like an adult

1. **Make it visible** — a debt register, or tickets tagged `tech-debt` with an estimate of the *interest* ("this costs us ~2 days per sprint")
2. **Price it in business terms** — "this debt makes each new payment method take 3 weeks instead of 3 days"
3. **Pay it with the boy-scout rule** — leave each file a little better than you found it
4. **Budget it** — 15–20% of every sprint, permanently. Not "we'll do a cleanup sprint later." That sprint never comes.
5. **Some debt should never be repaid** — code in a module that is being retired next year. Let it rot in peace. Repaying debt in dying code is pure waste.

> Architect's phrasing to management: *"We can keep the current speed, or we can keep the current quality, but the interest is now 20% of our capacity. Which would you like to pay down?"*

---

## 0.12 Evolutionary Architecture

Old belief: design everything upfront (**Big Design Up Front**), then build for 2 years.
Why it failed: the business changed, the tech changed, and the assumptions were wrong.

New belief: **design for change**. You will be wrong. Build so that being wrong is cheap.

### The three principles

**1. Last responsible moment**
Delay a decision until the moment when *not* deciding starts to cost more than deciding. Not "as late as possible" — "as late as *responsible*". You often learn crucial facts in the meantime.

Example: you do not need to choose between one database and sharding on day 1. You *do* need to choose your primary key strategy on day 1, because changing it later is brutal. So decide the key (UUID/ULID) and defer the sharding.

**2. Fitness functions**
An automated test for an **architectural** property, not a feature. It runs in CI and fails the build.

```csharp
// NetArchTest example — enforce layering automatically
[Fact]
public void Domain_Must_Not_Depend_On_Infrastructure()
{
    var result = Types.InAssembly(typeof(Order).Assembly)
        .That().ResideInNamespace("MyApp.Domain")
        .ShouldNot().HaveDependencyOn("MyApp.Infrastructure")
        .GetResult();

    Assert.True(result.IsSuccessful, string.Join(", ", result.FailingTypeNames ?? []));
}
```

```ini
# Python equivalent using import-linter (.importlinter file)
[importlinter:contract:1]
name = Domain must not import infrastructure
type = forbidden
source_modules = app.domain
forbidden_modules = app.infrastructure, sqlalchemy, fastapi
```

Other fitness functions worth having:
- p95 latency of the checkout endpoint must stay under 400 ms (run in a nightly load test)
- no service may have more than 5 inbound dependencies
- every public API endpoint must have an OpenAPI schema
- no `SELECT *` in production code paths
- container image must have zero CRITICAL CVEs

> A rule that is not automated is a rule that will be broken by Friday. **Fitness functions turn architecture principles into CI failures.**

**3. Incremental change**
Every part of the system must be independently deployable *enough* that you can change one thing without a 40-person coordinated release. This is why CI/CD and testing are architecture concerns, not "DevOps stuff".

### The Strangler Fig pattern (how to evolve safely)

Named after a tree that grows around a host tree until the host dies and the fig stands on its own.

```
Step 1:  Client ──────────────► Legacy Monolith

Step 2:  Client ──► Facade ──┬─► Legacy Monolith
                             └─► New Service (handles /payments only)

Step 3:  Client ──► Facade ──┬─► Legacy (shrinking)
                             ├─► Payments Service
                             └─► Orders Service

Step 4:  Client ──► Facade ──┬─► Payments Service
                             └─► Orders Service      (legacy deleted)
```

You never do a "big bang rewrite". You put a facade in front, move one capability at a time, and keep the system working every single day. Big-bang rewrites fail so reliably that they have their own famous case studies (Netscape 6 being the classic).

---

## 0.13 Architecture Principles

Principles are the **shared rules** your team uses to make consistent decisions when you are not in the room. Without them, every decision is re-argued from scratch.

A good principle has three parts: **the rule**, **the reason**, **the implication**.

### Example principle set (steal this, then adapt)

> **P1 — Buy before build for non-differentiating capabilities.**
> *Reason:* Our engineering capacity is our scarcest resource; it must go to what customers pay for.
> *Implication:* Any proposal to build auth, email, payments or logging needs explicit sign-off.

> **P2 — Every service owns its data. No shared databases.**
> *Reason:* Shared tables create invisible coupling; nobody can change a schema safely.
> *Implication:* Cross-service data access happens via API or events. Reporting gets a read replica or the warehouse, not the OLTP tables.

> **P3 — Prefer boring, widely-known technology.**
> *Reason:* We are a 12-person team. We cannot operate six exotic systems at 3 AM.
> *Implication:* New technology requires an ADR that names the operational owner.

> **P4 — Design for failure. Everything remote will fail.**
> *Reason:* Networks, vendors and disks fail; our SLA does not care whose fault it was.
> *Implication:* Every outbound call has a timeout, a retry policy and a defined fallback. No exceptions.

> **P5 — Secure by default; least privilege everywhere.**
> *Reason:* We handle identity documents. One breach ends the company.
> *Implication:* No shared admin accounts, no long-lived credentials, PII encrypted and access-logged.

> **P6 — Automate anything done more than twice.**
> *Reason:* Manual steps are where outages are born.
> *Implication:* Deploys, migrations, certificate renewal and environment creation are code.

**5–8 principles maximum.** Twenty principles = zero principles, because nobody remembers them.

---

## 0.14 Quality Attributes (the ISO 25010 map)

"Quality attribute" is the formal name for an NFR. Knowing the standard list helps you not forget a whole category.

| Attribute | Plain English | Typical tactic |
|-----------|---------------|----------------|
| **Performance efficiency** | Fast and not wasteful | Caching, async, indexing, batching |
| **Reliability** | Keeps working, recovers | Redundancy, retries, health checks, failover |
| **Availability** | Is it up right now? | Multi-AZ, load balancing, graceful degradation |
| **Security** | Only the right people, right actions | AuthN/AuthZ, encryption, least privilege |
| **Maintainability** | Easy to change safely | Modularity, tests, docs, low coupling |
| **Portability** | Runs elsewhere | Containers, standard APIs, config not code |
| **Usability** | Humans can use it | UX, error messages, docs |
| **Compatibility** | Plays well with others | Versioning, standard formats |
| **Functional suitability** | Does the right thing | The features themselves |
| **Scalability** | Grows with demand | Statelessness, partitioning, queues |
| **Observability** | You can see inside it | Logs, metrics, traces |
| **Testability** | You can verify it | DI, seams, contract tests |

### Quality attributes fight each other

This is the crucial insight. You cannot maximise all of them.

- **Security ↔ Usability** — 2FA on every action is very secure and very annoying
- **Performance ↔ Maintainability** — hand-tuned code is fast and horrible to change
- **Consistency ↔ Availability** — the CAP theorem, in one line (Chapter 05)
- **Flexibility ↔ Simplicity** — every plugin point is a new thing to understand
- **Cost ↔ Everything**

> The architect's real output is a **ranked list** of quality attributes for *this* system.
> "For our payment ledger: correctness > availability > latency > cost."
> "For our recommendation feed: latency > availability > cost > correctness."
>
> Those two sentences produce two completely different systems — and both are right.

### Writing a quality attribute *scenario* (make it testable)

Vague: *"The system should be fast."*

Testable scenario (6 parts):

| Part | Value |
|------|-------|
| **Source** | A mobile user |
| **Stimulus** | Submits a liveness video |
| **Environment** | During peak load (500 req/min) |
| **Artifact** | The verification API |
| **Response** | Returns a pass/fail decision |
| **Measure** | Within 4 seconds at p95, 8 seconds at p99 |

Now it is a thing you can *test*, *alert on*, and *argue about with evidence*.

---

## 0.15 The fundamental question

For every technology that crosses your desk:

> ## **What problem does this solve?**
> Not: *"How do I use this?"*

Practise it right now on five things:

| Technology | The problem it solves |
|------------|----------------------|
| **Redis** | Reading the same data from disk repeatedly is slow and hammers the database |
| **Kafka** | Many consumers need the same high-volume event stream, and want to re-read history |
| **Kubernetes** | Running many containers across many machines, with restarts, scaling and rollouts, done by hand, does not survive contact with reality |
| **GraphQL** | Mobile clients need different shapes of data and were making 8 round-trips per screen |
| **Service mesh** | Retries/mTLS/tracing were being re-implemented, differently and badly, in 30 services |
| **Terraform** | Clicking in a cloud console is unrepeatable, unreviewable, and undocumented |
| **Event sourcing** | The business needs to know *why* a balance is what it is, not just what it is |

Then ask the follow-up that separates the architect from the enthusiast:

> ## **Do I actually have that problem?**

Kubernetes solves a real and painful problem. If you have 3 containers and 2 developers, **you do not have that problem**, and Kubernetes will hand you a new set of problems for free.

### The "three questions" filter for any new tech

1. **What problem does it solve?** (If you cannot answer, stop.)
2. **Do we have that problem, today or within 12 months?** (If no, stop. Write it in a "maybe later" list.)
3. **What new problems does it bring, and can we operate them at 3 AM?** (If no, stop, or buy the managed version.)

---

## 0.16 How an architect *thinks* through a new system

A repeatable 9-step loop. Use it every time.

```
1. UNDERSTAND    → What is the business problem? Who feels the pain? How much is it worth?
2. CLARIFY       → Functional requirements. Then the NFR checklist (14 questions).
3. CONSTRAIN     → Budget, deadline, team skills, legacy systems, regulation, org chart.
4. ESTIMATE      → Users, RPS, data size, growth. Back-of-envelope only. (Chapter 04)
5. SKETCH        → Boxes and arrows. Data flow. Where the data lives. 15 minutes, on paper.
6. STRESS-TEST   → Where does it break? What if this component dies? What if traffic is 10×?
7. ALTERNATIVES  → Produce 2–3 real options. Write the trade-offs for each.
8. DECIDE        → Choose. Write an ADR: context, options, decision, consequences, revisit trigger.
9. VALIDATE      → Spike the risky part. Measure. Feed the result back into step 5.
```

**Step 7 is the one people skip.** If you present one option, you are a salesperson. If you present three with honest trade-offs, you are an architect — and the team owns the decision with you.

**Step 6 is the one that makes you look brilliant in reviews.** Just walk through the diagram and ask "what if this box dies?" for every box. It is almost mechanical, and it finds real holes every time.

---

## 0.17 Soft skills — the part nobody warns you about

Technical skill gets you to architect. These keep you there.

### Translate in both directions

| Engineer says | You tell the business |
|---------------|----------------------|
| "We need to refactor the persistence layer" | "Changes in this area take 3× longer than they should; 4 weeks of work makes the next 12 months faster" |
| "We should add a circuit breaker" | "When our document vendor is slow, our whole app currently freezes. This change keeps the rest working." |
| "The database is not sharded" | "We are fine to about 4× today's volume. Past that we need 2 months of work, so let us start when we hit 2×." |

### Influence without authority

Architects usually **cannot** order anyone to do anything. You get your way by:

- **Being right, repeatedly, in a way people can verify** — prototypes beat opinions
- **Making the right thing the easy thing** — a template repo, a shared library, a working example
- **Giving credit away** — if the team feels it was their idea, it will actually get built
- **Losing small arguments** — save your capital for the load-bearing walls; let the team pick the logging library

### Know when to say "it depends" — and never stop there

"It depends" is true and useless alone. The professional form is:

> *"It depends on whether we need to replay history. If we do, Kafka. If we do not, RabbitMQ is simpler and the team already knows it. Do we have a replay use case?"*

Name the *dependency*, then ask the question that resolves it.

---

## 0.18 Common mistakes (the ones you will actually make)

1. **Resume-driven development** — choosing tech because you want it on your CV. Everyone does it once. Notice it.
2. **Designing for a scale you will never reach** — building for 10M users while you have 200. You will spend your runway on infrastructure and die before the users arrive.
3. **Ignoring the team's skills** — the most beautiful architecture that your team cannot operate is a *bad* architecture. The team is part of the system.
4. **Not writing decisions down** — in 8 months nobody remembers why, so it gets changed, badly, and then changed back.
5. **Solving the stated solution instead of the real problem** — see 0.2.
6. **The ivory tower** — diagrams that no developer ever reads, disconnected from the code. If you have not looked at the repository this month, you are drifting.
7. **One option only** — presenting a single design is a decision disguised as a proposal.
8. **Forgetting operations** — who deploys it, who is on call, how do we roll back, what does it cost per month.
9. **Treating NFRs as "phase 2"** — security, observability and scalability are not features you sprinkle on later. They are structural.
10. **Being unable to say "I don't know"** — the fastest way to lose an engineering team's trust is to bluff. "I don't know, let me find out by Thursday" is a complete and respectable answer.

---

## 0.19 Architect's checklist

Before you call a design "done":

- [ ] The problem is written in one sentence, with a number in it
- [ ] Functional requirements listed
- [ ] All 14 NFR questions asked, answers written down
- [ ] Constraints listed (technical, business, organisational)
- [ ] Assumptions listed, each with an owner and a verification plan
- [ ] Risks listed with likelihood, impact, mitigation
- [ ] Quality attributes **ranked** for this specific system
- [ ] At least 2 alternatives considered and written down
- [ ] Trade-offs stated explicitly — what we give up, not just what we gain
- [ ] The "what if this box dies" walk-through done for every box
- [ ] Cost estimated (monthly, and per transaction)
- [ ] Team skills honestly assessed against the design
- [ ] ADR written, including the trigger to revisit
- [ ] A diagram exists that a new joiner can understand in 10 minutes
- [ ] The riskiest assumption has been spiked with real code

---

## 0.20 Self-test

Answer these out loud. If you stumble, re-read the section.

1. Define architecture in one sentence.
2. Give an example of two systems with the same features but different architectures. What caused the difference?
3. What is Conway's Law, and what is the Inverse Conway Manoeuvre?
4. A stakeholder says *"we need 99.99% availability"*. What do you ask next?
5. What are the four quadrants of technical debt? Which one is good engineering?
6. What is a fitness function? Write one for your current project.
7. Your CTO says *"let's move to microservices"*. Give your first three questions.
8. Name three things you give up by adding a cache.
9. When should you build instead of buy?
10. What does "last responsible moment" mean, and how is it different from procrastination?
11. Explain the Strangler Fig pattern to a project manager, in 30 seconds.
12. Rank the quality attributes for (a) a bank ledger, (b) a social media feed. Justify.

---

## 0.21 Key takeaways

- Architecture = **the decisions that are expensive to change later**
- **NFRs drive architecture** far more than features do
- Always ask **"what problem does this solve?"** then **"do I have that problem?"**
- There are **no right answers, only trade-offs** — and your job is to make them explicit
- **Write it down**: assumptions, risks, decisions, principles. Undocumented architecture does not exist.
- **Conway's Law is undefeated** — design the teams before the system
- Optimise for **complexity**, not just money; complexity is paid daily, forever
- Design for **change**, because you will be wrong
- The team's skills are **part of the architecture**

---

**Next:** [Chapter 01 — Software Engineering Foundations](01-software-engineering-foundations.md)
