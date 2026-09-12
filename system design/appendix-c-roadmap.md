# Appendix C — A 12-Month Learning Roadmap

> The book is the map. This is the route.
>
> The rule that makes it work: **every month has one reading goal and one *building* goal.** Reading alone produces someone who can talk about architecture. Building produces an architect.

---

## How to use this

**Time budget:** ~5 hours per week. 2 hours reading, 3 hours building. That is realistic alongside a full-time job, and it is enough.

**The depth rule** (from the README): do not try to turn every ⚪ into a 🟢. Breadth first, depth where your work demands it. You are building a **map of the territory**, not mastering every province.

**The most important habit:** after every chapter, find where that topic exists in **a system you actually work on**. Abstract knowledge evaporates; knowledge attached to a real system stays.

---

## Quarter 1 — Foundations and thinking (months 1–3)

*Goal: stop thinking like a developer who writes features, start thinking like someone who makes decisions.*

### Month 1 — Mindset and code-level architecture

**Read:** Chapters [00](00-architect-mindset.md), [01](01-software-engineering-foundations.md)

**Build:**
- Write an **ADR for a decision already made** in your current system. Reconstruct the context, the options, the consequences. You will discover how much was never written down.
- Pick the worst-coupled area of your codebase. Draw its dependencies. Write down what would break if you changed it.
- Add **one fitness function** to CI (a layering rule, or a "no secrets in source" check).

**Reflect:** For your current project, write the problem statement in one sentence with a number in it. Then ask three colleagues to do the same. Compare.

---

### Month 2 — Architecture styles and DDD

**Read:** Chapters [02](02-architecture-styles.md), [03](03-domain-driven-design.md)

**Build:**
- Classify your company's subdomains as **Core / Supporting / Generic**. Then check where the engineering hours actually go. Write up the mismatch.
- Draw a **Context Map** of your systems, labelling each relationship (conformist, ACL, customer/supplier…).
- Find one external dependency with no ACL. **Write the ACL.** This is the single highest-value refactor in this roadmap.

**Reflect:** Is your system a monolith, a modular monolith, a distributed monolith, or microservices? Be honest. Use the diagnostic checklist in §2.3.

---

### Month 3 — System design fundamentals

**Read:** Chapter [04](04-system-design-fundamentals.md) · Appendix B sections 1–4

**Build:**
- **Estimate your own system.** DAU, RPS, peak, storage, bandwidth, read:write ratio. Compare against actual production metrics. Note where you were wrong and why.
- Apply **Little's Law** to your service. Compare the result against your actual connection pool and thread pool sizes. Most people find a surprise here.
- Memorise the latency table and the availability table. Genuinely memorise them.

**Reflect:** What is the one resource that constrains your system? Is your architecture shaped around it?

---

## Quarter 2 — Distributed systems and data (months 4–6)

*Goal: understand what actually breaks in production, and why.*

### Month 4 — Distributed systems ⭐

**Read:** Chapter [05](05-distributed-systems.md) — **read it twice.** This is the highest-value chapter in the book.

**Build:**
- Audit every outbound call in your system. **How many have an explicit timeout?** Fix the ones that do not.
- Add a **circuit breaker** to your most fragile dependency. Watch it trip in staging.
- Implement the **idempotency key** pattern on one side-effecting endpoint.
- Run a small experiment: kill a dependency in staging and observe what your system does.

**Reflect:** Draw your system and mark every synchronous dependency. Calculate the combined availability. Is it what you promised?

---

### Month 5 — Messaging and events

**Read:** Chapters [06](06-messaging-and-event-driven-architecture.md), [07](07-kafka.md)

**Build:**
- Find a **dual write** in your codebase (a database write followed by a publish). **Implement the Outbox pattern** for it. This is a career-defining pattern to have used in anger.
- Set up a **retry-with-backoff + DLQ topology** in RabbitMQ using TTL and dead-lettering.
- Add correlation and causation IDs to every message; propagate trace context through the broker.

**Reflect:** For every consumer you own, ask: what happens if this message arrives twice? If you cannot answer confidently, it is not idempotent.

---

### Month 6 — Databases and caching

**Read:** Chapters [09](09-database-architecture.md), [11](11-caching.md)

**Build:**
- Enable `pg_stat_statements`. Find your **top 10 queries by total time**. `EXPLAIN (ANALYZE, BUFFERS)` each one.
- Find and fix an **N+1 query**. Add a **query-count budget test** so it cannot come back.
- Audit your cache keys. Do they include the **tenant** and a **schema version**? Do they all have a TTL with jitter?
- **Flush your cache in staging under load.** Observe whether the system survives. Most do not.

**Reflect:** Perform a **restore drill**. Restore a real backup to an isolated environment. Time it. Compare against your claimed RTO.

---

## Quarter 3 — The ground it runs on (months 7–9)

*Goal: understand everything between the user and your code.*

### Month 7 — Networking and APIs

**Read:** Chapters [13](13-networking.md), [08](08-api-architecture.md)

**Build:**
- Put `curl -w` with the timing format in your dotfiles. **Use it on your own API.** Learn where the time goes.
- Trace one request through all eleven steps of §13.1 in your own infrastructure.
- Audit your API against the §8.25 checklist. Fix the top three gaps (usually: pagination, idempotency keys, error format).
- Add **OpenAPI breaking-change detection** to CI.

**Reflect:** Inventory every TLS certificate your systems depend on, including internal ones. Is each one auto-renewed and alerted on?

---

### Month 8 — Cloud and containers

**Read:** Chapters [14](14-cloud-architecture.md), [15](15-containers-and-kubernetes.md)

**Build:**
- Calculate your **unit economics**: cost per transaction. Put it on a dashboard.
- Find the three biggest sources of cloud waste in your account (over-provisioning, no reservations, non-prod running 24/7, orphaned resources).
- Improve one Dockerfile: multi-stage, minimal base, non-root, pinned by digest, scanned in CI.
- Verify your **graceful shutdown**: deploy under load and check for 502s. Add preStop + SIGTERM handling if there are any.

**Reflect:** Run a Well-Architected review on one system. Half a day. Write down the findings.

---

### Month 9 — DevOps and observability

**Read:** Chapters [16](16-devops-and-platform-engineering.md), [18](18-observability.md)

**Build:**
- Measure your **DORA metrics**. Even roughly. Establish the baseline.
- Add **OpenTelemetry auto-instrumentation** to one service. Look at a real trace. This is usually a revelation.
- Convert your logs to **structured JSON with a trace ID** on every line. Return the trace ID to clients.
- Define **one SLO with an error budget** for your most important user journey. Set up burn-rate alerting.

**Reflect:** Review every alert that fired in the last month. For each: was it real? actionable? did you do something? **Delete the ones that fail.**

---

## Quarter 4 — The job itself (months 10–12)

*Goal: operate as an architect, not just think like one.*

### Month 10 — Security and reliability

**Read:** Chapters [17](17-security-architecture.md), [19](19-reliability-and-disaster-recovery.md)

**Build:**
- Run a **threat model workshop** (STRIDE) on one system. Two hours, a whiteboard, the right people. Write up the findings.
- Write **automated cross-tenant isolation tests** for every resource type. Assert 404.
- Agree **RTO and RPO with the business** for each system. Write them down. Note where the current architecture does not meet them.
- Run a **chaos game day**: two hours, staging, kill something, watch what happens.

**Reflect:** If a customer demanded complete erasure tomorrow, could you list every place their data lives and how you remove it from each?

---

### Month 11 — Documentation and governance

**Read:** Chapters [22](22-architecture-documentation.md), [23](23-architecture-governance.md), [12](12-data-architecture.md)

**Build:**
- Draw a **C4 Container diagram** for your main system, **as code** (Mermaid/Structurizr), in the repository.
- Draw a **state machine** for your most important entity. Find at least one illegal transition that is currently possible.
- Draw a **data flow diagram with trust boundaries** for anything handling personal data.
- Write **three ADRs** for decisions being made right now, each with a revisit trigger.
- Draft a **technology radar** for your team. Bring it to a discussion.

**Reflect:** Give a new joiner your repository and nothing else. Can they get it running in 5 minutes and understand the architecture in a day?

---

### Month 12 — Integration, testing, and putting it together

**Read:** Chapters [24](24-integration-architecture.md), [21](21-testing-architecture.md), [20](20-performance-engineering.md), [25](25-capstone-case-studies.md)

**Build:**
- Add a **reconciliation job** for your most important integration.
- Add **contract testing** (or at minimum schema diffing) between two services.
- Run a **soak test** — 4+ hours at target load. Watch memory, connections and file handles.
- **Design two of the Chapter 25 exercises from scratch**, timeboxed to 45 minutes each. Write down estimates, failure modes and trade-offs. Then have someone review them using the §23.3 questions.

**Reflect:** Give the 60-second elevator description of your system (§22.8). Include topology, data ownership, compliance posture, the main risk with its mitigation, and unit economics.

---

## The habits that matter more than the schedule

These compound. The reading does not, on its own.

| Habit | Frequency | Why |
|-------|-----------|-----|
| **Write an ADR** for every significant decision | Ongoing | The single highest-value practice in the book |
| **Ask "what problem does this solve?"** then "do we have it?" | Every new technology | Prevents 80% of bad technology decisions |
| **Estimate before designing** | Every design | It reframes the problem, reliably |
| **"What if this box dies?"** for every box | Every design review | Finds more real issues than everything else combined |
| **State the trade-off out loud** | Every recommendation | What separates an architect from an enthusiast |
| **Spike the riskiest assumption** | Every project | Prototypes beat opinions |
| **Keep writing code** | Weekly | An architect who stops coding becomes theoretical in 18 months |
| **Restore drill** | Quarterly | A backup you have not restored is a hope |
| **Review your alerts** | Monthly | Alert fatigue is how outages go unnoticed |
| **Improve one document** | Weekly | Documentation decays continuously |

---

## Reading beyond this book

**If you read only three:**

1. **Designing Data-Intensive Applications** — Martin Kleppmann. The best technical book in this field, by a distance. Deepens Chapters 04, 05, 09, 10, 12.
2. **Fundamentals of Software Architecture** — Mark Richards & Neal Ford. The best book on the *role*. Deepens Chapters 00, 02, 23.
3. **Domain-Driven Design Distilled** — Vaughn Vernon. DDD without the 560 pages. Deepens Chapter 03.

**Then, by area:**

| Area | Book |
|------|------|
| Distributed systems | *Understanding Distributed Systems* — Roberto Vitillo |
| Microservices | *Building Microservices* (2nd ed.) — Sam Newman |
| Monolith→services | *Monolith to Microservices* — Sam Newman |
| Messaging | *Enterprise Integration Patterns* — Hohpe & Woolf (the canonical reference) |
| Reliability | *Site Reliability Engineering* — Google (free online) |
| Databases | *PostgreSQL 14 Internals* — Egor Rogov (free) · *Database Internals* — Alex Petrov |
| Security | *Alice and Bob Learn Application Security* — Tanya Janca · OWASP ASVS |
| Delivery | *Accelerate* — Forsgren, Humble, Kim (the DORA research) |
| Evolution | *Building Evolutionary Architectures* — Ford, Parsons, Kua |
| Legacy | *Working Effectively with Legacy Code* — Michael Feathers |
| Code | *A Philosophy of Software Design* — John Ousterhout (short, excellent) |

**Ongoing:** the AWS Architecture Blog · Martin Fowler's site · the Netflix, Uber, Discord, Stripe and Cloudflare engineering blogs · InfoQ architecture track · the papers-we-love repository.

**Practise:** design one system per week from the Chapter 25 exercise list. Timebox to 45 minutes. Write it up. Do this for ten weeks and you will be genuinely fluent.

---

## Signals you are becoming an architect

Not certifications. These:

- [ ] You ask **"what problem does this solve?"** before "how do I use it?"
- [ ] You estimate before designing, and the estimate changes your design
- [ ] You present **options with trade-offs**, not a single recommendation
- [ ] You can say **"I don't know, I'll find out by Thursday"** comfortably
- [ ] You write things down, and people actually read what you write
- [ ] You can explain the same system to a CEO and to a junior developer, differently
- [ ] You think about **operations and cost** during design, not after
- [ ] You know what your system does when each dependency fails — because you tested it
- [ ] You have changed your mind publicly when evidence contradicted you
- [ ] You are comfortable choosing the **boring** technology
- [ ] Teams invite you to reviews rather than being required to
- [ ] You still write code

> The last one is not sentimental. It is the mechanism by which all the others stay true.

---

## A closing note

You do not need to master every topic in this book. You need to **recognise the vocabulary, understand what problem each thing solves, know where it fits, and know where to look when the situation demands depth.**

When someone puts a new system in front of you and mentions event sourcing, or a saga, or PACELC, or an anti-corruption layer, or coordinated omission — you should now think *"I know what that is, I know what problem it solves, and I know the questions to ask."*

That is the whole goal. Everything else is depth you acquire when a real project requires it.

Now go and design something.

---

**Back to:** [Contents](README.md) · [Glossary](appendix-a-glossary.md) · [Cheat Sheets](appendix-b-cheatsheets.md)
