# Chapter 22 — Architecture Documentation 🟢🟢

> **Undocumented architecture does not exist.**
>
> It lives in three people's heads. Two of them will leave. The third will misremember it.
>
> This is the chapter that most separates "senior developer" from "architect", because producing clear, honest, useful documentation of a complex system is a genuine skill — and a rare one.

---

## 22.1 Why most architecture documentation fails

Everyone has seen it: a 90-page Word document, written once before the project started, describing a system that no longer exists, saved on a share drive nobody can find.

**Why it failed:**

| Failure | Cause |
|---------|-------|
| Nobody reads it | Too long, wrong audience, no clear purpose |
| It is wrong | It was never updated; the code moved on |
| Nobody can find it | Wrong place — not next to the code |
| It describes the *what*, not the *why* | The code already shows the what; only humans know the why |
| It was written once, at the worst moment | Before anything was learned |

**The four rules that fix all of it:**

1. **Documentation lives with the code** (in the repo, in version control, reviewed in PRs)
2. **Different documents for different audiences** — one document cannot serve everyone
3. **Record the *why*, not the *what*** — code shows what; only a human can record why
4. **Small, current documents beat large, stale ones** — if it cannot be kept current, do not write it

> **The test of documentation: can a competent new engineer become productive in a week using only the repository?** If they need three conversations to understand where things live and why, your documentation has failed regardless of its page count.

---

## 22.2 The C4 Model ⭐ 🟢

Simon Brown's C4 is the best general-purpose approach to architecture diagrams because it solves the single biggest problem: **mixing abstraction levels in one diagram**.

The classic bad diagram has a user, a load balancer, a Java class, an AWS region, a database table and an HTTP header all in the same picture. It is unreadable because it has no consistent zoom level.

**C4 gives you four zoom levels, like a map application.**

```
Level 1: CONTEXT      🌍  The system and the world around it
Level 2: CONTAINER    🏢  The deployable/runnable things inside it
Level 3: COMPONENT    🔧  The major parts inside one container
Level 4: CODE         📄  Classes — usually generated, rarely drawn by hand
```

### Level 1 — System Context

**Audience:** everyone, including non-technical stakeholders.
**Question it answers:** *What is this system, who uses it, and what does it talk to?*

```
   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
   │  End User    │         │   Reviewer   │         │ Tenant Admin │
   │  [Person]    │         │   [Person]   │         │  [Person]    │
   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘
          │ submits                │ adjudicates            │ configures
          │ verification           │ flagged sessions       │ policies
          ▼                        ▼                        ▼
   ┌────────────────────────────────────────────────────────────────┐
   │                  LIVENESS VERIFICATION PLATFORM                │
   │                      [Software System]                         │
   │   Proves a remote person is physically present and matches     │
   │   their identity document.                                     │
   └───┬────────────────┬──────────────────┬────────────────────┬───┘
       │                │                  │                    │
       ▼                ▼                  ▼                    ▼
 ┌───────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
 │ Face      │   │  Stripe     │   │ Customer's   │   │  Sanctions   │
 │ Vendor API│   │ [External]  │   │ Backend      │   │  List API    │
 │[External] │   │  billing    │   │ [External]   │   │ [External]   │
 └───────────┘   └─────────────┘   └──────────────┘   └──────────────┘
                                     receives webhooks
```

**Rules:** one box for your system. People and external systems around it. **No technology names.** If a CEO cannot understand it, it is wrong.

### Level 2 — Container ⭐ (the most valuable diagram you will ever draw)

**Audience:** developers, architects, operations.
**Question:** *What are the deployable units, what technology is each, and how do they communicate?*

> "Container" here means **a separately deployable/runnable thing** — an application, a service, a database, a queue, a file store. It predates Docker and is broader than it.

```
                              ┌──────────────┐
                              │   End User   │
                              └──────┬───────┘
                                     │ HTTPS
                                     ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  LIVENESS VERIFICATION PLATFORM                                      │
  │                                                                      │
  │  ┌────────────────┐        ┌─────────────────┐                       │
  │  │ Web App        │        │  Mobile SDK     │                       │
  │  │ [React]        │        │  [Kotlin/Swift] │                       │
  │  └───────┬────────┘        └────────┬────────┘                       │
  │          │  JSON/HTTPS               │  JSON/HTTPS                    │
  │          └───────────┬───────────────┘                               │
  │                      ▼                                               │
  │          ┌───────────────────────┐                                   │
  │          │   Verification API    │  Session lifecycle, policy,       │
  │          │   [Python/FastAPI]    │  quota enforcement                │
  │          └───┬───────┬────────┬──┘                                   │
  │     SQL      │       │ enqueue│  presigned PUT                       │
  │     ┌────────▼──┐ ┌──▼──────┐ │      ┌──────────────┐                │
  │     │ Postgres  │ │  Redis  │ │      │ Object Store │◄───────────────┼── user
  │     │[sessions, │ │[cache,  │ │      │ [S3] videos  │  uploads direct│
  │     │ results]  │ │ limits] │ │      └──────┬───────┘                │
  │     └───────────┘ └─────────┘ │             │ fetch                  │
  │                      ┌────────▼────┐        │                        │
  │                      │ Job Queue   │        │                        │
  │                      │ [SQS]       │        │                        │
  │                      └──────┬──────┘        │                        │
  │                             │ dequeue       │                        │
  │                      ┌──────▼──────────────▼┐                        │
  │                      │  Liveness Worker     │ GPU inference          │
  │                      │  [Python/ONNX, GPU]  │                        │
  │                      └──────┬───────────────┘                        │
  │                             │ publish results                        │
  │                      ┌──────▼──────────┐                             │
  │                      │ Webhook         │                             │
  │                      │ Dispatcher [Go] │─────────────────────────────┼──► customer
  │                      └─────────────────┘                             │    backend
  └──────────────────────────────────────────────────────────────────────┘
```

**Why this is the most valuable diagram:** it is the one people actually need. It tells a new engineer what exists, what technology each part uses, and how data flows — in one picture. **If you draw only one diagram for a system, draw this one.**

**Rules:** name the technology on every box. Label every arrow with *what* flows and *how* (protocol). Keep it to roughly 5–15 boxes.

### Level 3 — Component

**Audience:** developers working on that specific container.
**Question:** *What are the major building blocks inside this one container?*

Draw this only for containers that are genuinely complex. Most do not need it — and this is the level most likely to go stale, because internal structure changes fastest.

```
  VERIFICATION API [Python/FastAPI]
  ┌────────────────────────────────────────────────────────────┐
  │  ┌─────────────────┐   ┌──────────────────┐                │
  │  │ Session         │   │ Review           │  HTTP adapters │
  │  │ Controller      │   │ Controller       │                │
  │  └────────┬────────┘   └─────────┬────────┘                │
  │           ▼                      ▼                          │
  │  ┌──────────────────────────────────────────┐              │
  │  │      Verification Application Service     │ orchestration│
  │  └───┬──────────────┬──────────────┬────────┘              │
  │      ▼              ▼              ▼                        │
  │ ┌──────────┐ ┌─────────────┐ ┌──────────────┐              │
  │ │ Session  │ │  Policy     │ │  Quota       │  domain      │
  │ │ Aggregate│ │  Engine     │ │  Service     │              │
  │ └──────────┘ └─────────────┘ └──────────────┘              │
  │      │                              │                       │
  │      ▼                              ▼                       │
  │ ┌──────────────┐            ┌───────────────┐  adapters    │
  │ │ Session Repo │            │ Vendor ACL    │              │
  │ │ [SQLAlchemy] │            │ [httpx]       │              │
  │ └──────────────┘            └───────────────┘              │
  └────────────────────────────────────────────────────────────┘
```

### Level 4 — Code

Class diagrams. **Generate these from code when needed; do not maintain them by hand.** They go stale in days and the IDE already shows you this.

### Supplementary C4 diagrams

| Diagram | Shows |
|---------|-------|
| **Deployment** | How containers map onto infrastructure (regions, AZs, clusters, instances) |
| **Dynamic** | How containers/components collaborate for one specific scenario (like a sequence diagram, but at C4 levels) |
| **System Landscape** | All systems across the enterprise, and how they relate |

### Diagrams as code 🟢

```
graph TD
    User[End User] -->|HTTPS| API[Verification API<br/>Python/FastAPI]
    API -->|SQL| DB[(PostgreSQL<br/>sessions, results)]
    API -->|enqueue| Q[Job Queue<br/>SQS]
    Q -->|dequeue| W[Liveness Worker<br/>Python/ONNX GPU]
    W -->|fetch video| S3[(Object Store<br/>S3)]
    W -->|write result| DB
    W -->|publish| WH[Webhook Dispatcher<br/>Go]
    WH -->|HTTPS| Cust[Customer Backend]
```

> **Put diagrams in the repository as text** (Mermaid, PlantUML, Structurizr DSL, D2). Then they are version-controlled, diffable, reviewable in pull requests, and they cannot silently drift into a slide deck nobody can edit. A diagram trapped in a PNG someone drew in a tool you no longer have a licence for is a dead diagram.

---

## 22.3 Other diagram types 🟢

### Sequence diagrams — for interactions over time

**Best for:** explaining a flow, especially one involving several services, async steps, or error handling.

```
User        API        Queue      Worker      Vendor      DB
 │           │           │          │           │          │
 ├─POST /verify─────────►│          │           │          │
 │           ├─create session───────┼───────────┼─────────►│
 │           ├─enqueue──►│          │           │          │
 │◄─202 Accepted─────────┤          │           │          │
 │           │           ├─dequeue─►│           │          │
 │           │           │          ├─analyse──►│          │
 │           │           │          │◄─score────┤          │
 │           │           │          ├─save result─────────►│
 │           │           │          ├─publish event        │
 │◄──────────── webhook / SSE ──────┤           │          │
```

**Rules:** one scenario per diagram. Show the **error path** as a separate diagram — that is usually the one people need and the one nobody draws.

### State machine diagrams ⭐

**Best for:** anything with a lifecycle. Draw this **before** writing the code (Chapter 01, State pattern).

```
                    ┌─────────┐
        start ─────►│ PENDING │
                    └────┬────┘
              submit video│
                    ┌─────▼──────┐
                    │ PROCESSING │◄──────┐
                    └─┬───┬────┬─┘       │ retry
           pass        │   │    │ fail   │ (< max attempts)
              ┌────────┘   │    └────────┘
              ▼            ▼
        ┌─────────┐  ┌──────────────┐
        │ PASSED  │  │   REVIEW     │──approve──► PASSED
        └─────────┘  │  (borderline)│──reject───► FAILED
                     └──────────────┘
              ┌────────────────────────┐
              │  FAILED  (terminal)    │◄── max attempts / expired
              └────────────────────────┘
```

**Why it matters so much:** it makes the **illegal transitions visible**. Can a PASSED session go back to PROCESSING? Can an expired session be approved? These questions have business answers that must be decided — and a state diagram forces the conversation before the bugs.

### Entity Relationship Diagrams

For the data model. **Generate from the schema** where possible, and keep a hand-drawn conceptual version for the important entities only — a generated ERD of 80 tables is unreadable.

### Data flow diagrams ⭐

**Best for:** privacy, compliance and security reviews. Where does personal data enter, where is it stored, where does it leave, and where does it cross a trust boundary?

```
  ┌──────────────────────── TRUST BOUNDARY: internet ────────────────────┐
  │ User device                                                          │
  │  face video (BIOMETRIC) ──────────────┐                              │
  └───────────────────────────────────────┼──────────────────────────────┘
                                          ▼
  ┌──────────────────────── TRUST BOUNDARY: our VPC ─────────────────────┐
  │  Object Store  [encrypted, 90-day retention, per-tenant KMS key]     │
  │       │                                                              │
  │       ▼                                                              │
  │  Worker ──► face embedding (BIOMETRIC DERIVED) ──► Postgres          │
  │       │                                            [field-encrypted] │
  │       └──► score + decision (non-PII) ──► Postgres [7-year retention]│
  └───────┬──────────────────────────────────────────────────────────────┘
          │ pass/fail ONLY — no biometric data leaves
          ▼
      Customer backend (webhook)
```

This one diagram answers most of a GDPR/BIPA assessment (Chapter 17) and is far more useful for that purpose than any prose.

### Deployment diagram

Regions, availability zones, subnets, clusters, instance counts, and what runs where. Pairs with Chapter 19's DR planning.

### Choosing

| To show | Use |
|---------|-----|
| The system and its neighbours | C4 Context |
| What runs, and in what technology | **C4 Container** ⭐ |
| Inside one complex service | C4 Component |
| A flow over time | Sequence |
| A lifecycle | **State machine** ⭐ |
| Data shape and relationships | ERD |
| Where sensitive data goes | **Data flow + trust boundaries** ⭐ |
| Where it physically runs | Deployment |

---

## 22.4 Architecture Decision Records (ADRs) ⭐⭐ 🟢

**The single highest-value documentation practice there is.**

**The problem:** in 18 months someone asks *"why on earth did we use RabbitMQ instead of Kafka?"*. The people who decided have left. The code shows *what*, never *why*. So the team either lives with a decision they do not understand, or changes it — often back again after rediscovering the original reason the hard way.

**The solution:** a short markdown file, in the repository, per significant decision.

```markdown
# ADR-0014: Use RabbitMQ for verification job distribution

Date: 2026-09-12
Status: Accepted
Deciders: Delower Hosen (architect), Platform team
Supersedes: —
Superseded by: —

## Context

Verification jobs must be distributed from the API to GPU workers.

Constraints and forces:
- Peak volume ~120 jobs/minute (2/sec), average 0.6/sec. Low volume.
- Jobs take 3-6 seconds; failures must retry with backoff, then dead-letter
  for manual inspection.
- The team has 3 years of RabbitMQ operational experience; none with Kafka.
- We are 4 engineers with no platform specialist.
- No current or planned requirement to replay historical jobs.
- Per-message visibility (inspect, retry, drop one poison message) is
  operationally important — our support team uses it today in another product.

## Options considered

### 1. RabbitMQ (quorum queues)
+ Built-in per-message ack/nack, TTL-based retry queues and DLQ (Chapter 06)
+ Team already operates it; runbooks and monitoring exist
+ Managed option available (Amazon MQ / CloudAMQP)
− No replay of consumed messages
− Lower ceiling on throughput (irrelevant at 2/sec)

### 2. Apache Kafka
+ Replay, very high throughput, strong ordering guarantees
+ Would also serve a future analytics event stream
− No per-message retry/DLQ — requires building retry topics ourselves
− Significant operational learning curve for a team with no Kafka experience
− Overkill: we would use ~0.01% of its throughput capability

### 3. AWS SQS
+ Fully managed, near-zero operations, cheap at our volume
+ Native DLQ and visibility timeout
− Vendor lock-in to AWS
− Weaker routing than RabbitMQ topic exchanges (not needed today)

## Decision

We will use **RabbitMQ with quorum queues**, deployed as a managed service.

## Consequences

Positive:
- Retry-with-backoff and DLQ available immediately via TTL + dead-letter exchange
- Team can operate it on day one; no new on-call knowledge required
- Per-message operational visibility for support

Negative:
- No job replay. If we later need to reprocess historical jobs, we must
  reconstruct them from the `sessions` table rather than from the broker.
- A second broker would be needed if we later build an analytics event stream.
  (Mitigation: we would use Kafka for that, and keep RabbitMQ for task queues.
   Running both is acceptable — they serve different purposes.)

Neutral:
- Messages carry a `schema_version` header so we can evolve payloads (Chapter 06).

## Revisit if

- Sustained job volume exceeds 5,000/sec, OR
- A requirement appears to replay more than 24 hours of job history, OR
- We adopt Kafka for an event backbone and consolidation becomes worthwhile
```

### What makes an ADR good

| Element | Why |
|---------|-----|
| **Immutable** | Never edit a decided ADR. Supersede it with a new one. The history is the value. |
| **Numbered sequentially** | `0001`, `0002`… easy to reference in code comments and PRs |
| **In the repo** | `docs/adr/` — reviewed in pull requests, versioned with the code |
| **Short** | One page. If it needs five, the decision is really several decisions. |
| **Honest about the negatives** | An ADR with no downsides is marketing, not engineering |
| **Options genuinely considered** | Including the ones you rejected, with reasons |
| **A revisit trigger** | ⭐ The thing that makes it a *professional* decision rather than a permanent one |

### What deserves an ADR

```
✅ Anything expensive to reverse (the Chapter 00 definition of architecture)
   - Choice of database, broker, cloud, language, framework
   - Service boundaries and data ownership
   - Authentication and authorisation model
   - API style and versioning strategy
   - Consistency model for a critical flow
   - Multi-region / DR posture
   - A significant "we deliberately did NOT do X"  ← very valuable

❌ Not needed
   - Which logging library (unless it is contentious)
   - Code style
   - Anything trivially reversible
```

> **The "we decided not to" ADR is under-used and extremely valuable.** "ADR-0022: We will not adopt Kubernetes in 2026" with the reasoning stops the same debate recurring every quarter, and gives a clear trigger for when it *should* be revisited.

**Status lifecycle:** `Proposed` → `Accepted` → later possibly `Deprecated` or `Superseded by ADR-00NN`.

---

## 22.5 The documents every system needs 🟢

Not everything is a diagram. Here is the minimum viable documentation set.

### 1. README (the front door)

```markdown
# Verification API

One paragraph: what this service does and why it exists.

## Quick start
git clone ... && make dev          # running locally in under 5 minutes

## Architecture
- [Container diagram](docs/architecture/container.md)
- [ADRs](docs/adr/)

## Key concepts
Session, Attempt, Challenge, Signals, Outcome    ← the ubiquitous language (Chapter 03)

## Running tests
make test           # unit + integration (Testcontainers — Docker required)

## Deployment
Merging to main deploys to staging automatically.
Production requires approval in <pipeline link>.
Rollback: `./scripts/rollback.sh <version>`  (~3 minutes)

## Owner
Team: Verification · Slack: #team-verification · On-call: <rota link>
```

> **The "running in 5 minutes" test is the single best measure of a README.** If a new developer cannot get the service running locally in five minutes, fix that before writing anything else.

### 2. Runbooks (operational)

Covered in Chapter 19. One per alert, written for 3 AM.

### 3. API documentation

OpenAPI (Chapter 08), plus a getting-started guide with working curl examples.

### 4. Data dictionary

For each significant table/entity: what it means in business terms, who owns it, its PII classification, and its retention period. This is what makes compliance and data work tractable (Chapters 12, 17).

### 5. Threat model

Chapter 17. Reviewed when the architecture changes materially.

### 6. Onboarding guide

The path a new engineer follows in week one: read these five documents, run the system locally, make a trivial change, deploy it to staging. **Ask every new joiner to improve it on their way through** — they are the only people who can see what is missing.

---

## 22.6 The arc42 / structured template ⚪🟡

For systems that genuinely need a comprehensive document (regulated environments, handovers, enterprise standards), **arc42** provides a proven 12-section structure:

```
1.  Introduction and goals          7.  Deployment view
2.  Constraints                     8.  Cross-cutting concepts
3.  Context and scope               9.  Architecture decisions (ADRs)
4.  Solution strategy              10.  Quality requirements
5.  Building block view            11.  Risks and technical debt
6.  Runtime view                   12.  Glossary
```

> Use it as a **checklist of what to think about**, not as a mandate to write all twelve sections. Sections 1, 3, 4, 9, 10, 11 and 12 carry most of the value. Fill in the rest only if someone will actually read them.

---

## 22.7 Keeping documentation alive 🟢

**The hard part is not writing it. It is preventing it from becoming a lie.**

| Technique | Effect |
|-----------|--------|
| **Docs in the repo, reviewed in PRs** | Changing the code and the docs is one action |
| **Diagrams as code** | Diffable, reviewable, and impossible to lose the source |
| **Generated where possible** | OpenAPI from code, ERDs from schema, lineage from dbt (Chapter 12) |
| **A "docs impact" line in the PR template** | Prompts the author at exactly the right moment |
| **Date and owner on every document** | An undated document cannot be assessed for staleness |
| **Delete aggressively** | A wrong document is worse than a missing one — it actively misleads |
| **Architecture review as a trigger** | Chapter 23 — reviews naturally surface stale docs |
| **Fitness functions** | CI fails if a new service has no README or owner metadata (Chapter 00) |

> **The rule that decides everything: if a document is not worth keeping current, it is not worth writing.** Better five accurate pages than eighty that mislead. When in doubt, write less and keep it true.

### Documentation as onboarding-driven development

The most reliable feedback loop: **every new joiner must document the gap they hit.** They are the only people who can see what is missing, and only for their first three weeks. After that, the knowledge becomes invisible to them too. Make it an explicit expectation of the first month.

---

## 22.8 Presenting architecture to different audiences 🟢

The same system needs different framings. Getting this wrong is why architects lose rooms.

| Audience | They care about | Show them | Do not show them |
|----------|----------------|-----------|------------------|
| **Executives** | Cost, risk, timeline, business capability | C4 Context, a cost-per-transaction figure, the risk table | Container diagrams, technology names |
| **Product managers** | What is possible, what it costs, when | Context + a capability map, trade-offs in feature terms | Anything below the container level |
| **Developers** | Where things live, how to change them safely | **Container + Component diagrams, ADRs, the repo** | Executive framings |
| **Operations / SRE** | What fails, how to fix it, what to watch | Deployment diagram, runbooks, dependency map, SLOs | Domain model detail |
| **Security / compliance** | Where the data goes, who can see it | Data flow + trust boundaries, threat model, retention table | Implementation detail |
| **Auditors** | Evidence that controls exist and are followed | ADRs, access reviews, audit-log samples, retention policy | Speculative roadmap |

### The elevator pitch for your architecture

Practise this until it is 60 seconds and effortless:

> *"It is a Python API behind a queue, with GPU workers doing the actual liveness inference. Postgres is the system of record; videos go straight to object storage and are deleted after 90 days for compliance. It runs on Fargate across three availability zones. The main risk is our dependency on a single face-analysis vendor, which we mitigate with a circuit breaker and a manual-review fallback. It costs about 1.4 cents per verification against a 15-cent price."*

That paragraph contains: the topology, the data ownership, the compliance posture, the deployment model, the primary risk with its mitigation, and the unit economics. **That is what an architect sounds like.**

---

## 22.9 Common mistakes

1. **The 90-page document nobody reads** — written once, stale in a month
2. **Documentation separate from code** — it will drift, guaranteed
3. **Mixing abstraction levels in one diagram** — the classic unreadable architecture picture
4. **Documenting the *what* instead of the *why*** — the code already shows what
5. **No ADRs** — decisions get re-litigated forever, then reversed, then reversed back
6. **Editing an accepted ADR** — the history is the value; supersede instead
7. **Unlabelled arrows** — an arrow with no protocol or payload means nothing
8. **Diagrams as images with no source** — uneditable, undiffable, eventually unusable
9. **Hand-maintained class diagrams** — stale within days; generate them
10. **No owner or date on a document** — nobody can judge whether to trust it
11. **Never deleting stale documentation** — a wrong document is worse than none
12. **One document for all audiences** — it serves none of them
13. **No state diagram for something with a lifecycle** — illegal transitions become production bugs
14. **No data-flow diagram** in a system handling regulated data — the compliance review has no foundation

---

## 22.10 Architect's checklist

- [ ] README gets a new developer running locally in under 5 minutes
- [ ] C4 **Context** and **Container** diagrams exist and are current
- [ ] Component diagrams only for genuinely complex containers
- [ ] All diagrams are **as code**, in the repository, reviewed in PRs
- [ ] Every arrow labelled with what flows and over which protocol
- [ ] ADRs for every significant decision, numbered, immutable, with **revisit triggers**
- [ ] ADRs include the options rejected and the honest downsides
- [ ] At least one "we deliberately decided not to" ADR where relevant
- [ ] State machine diagram for every entity with a lifecycle
- [ ] Data flow diagram with trust boundaries for regulated data
- [ ] Deployment diagram showing regions, AZs and instance counts
- [ ] Sequence diagrams for the critical flows — including the **error paths**
- [ ] Runbook per alert (Chapter 19)
- [ ] OpenAPI spec generated and published (Chapter 08)
- [ ] Data dictionary with ownership, PII classification and retention
- [ ] Threat model current (Chapter 17)
- [ ] Every document has an owner and a last-reviewed date
- [ ] Stale documents deleted, not left to mislead
- [ ] New joiners are expected to improve the docs in their first month

---

## 22.11 Self-test

1. Why does most architecture documentation fail? Give the four rules that fix it.
2. Name the four C4 levels and the audience for each.
3. Which single C4 diagram would you draw if you could only draw one, and why?
4. What does "container" mean in C4, and why is it broader than Docker?
5. Why should diagrams be written as code and stored in the repository?
6. Why is a state machine diagram valuable *before* writing the code?
7. What question does a data-flow diagram with trust boundaries answer that no other diagram does?
8. What is an ADR, and what is the single most valuable field in it?
9. Why must an accepted ADR never be edited?
10. Give three things that deserve an ADR and three that do not.
11. Why is a "we decided not to do X" ADR valuable?
12. What is the best single test of a README?
13. How would you present the same system to a CEO, a developer, and an auditor? What changes?
14. Give the 60-second elevator description of a system you have worked on.

---

## 22.12 Key takeaways

- **Undocumented architecture does not exist** — it lives in heads that leave
- **Docs live with the code**, reviewed in PRs, written as code, and deleted when stale
- **C4 solves the abstraction-mixing problem.** The **Container diagram** is the single most valuable picture you will draw.
- **Label every arrow** with what flows and how
- **ADRs are the highest-value documentation practice** — they capture the *why*, which nothing else can
- **Immutable ADRs with revisit triggers** turn decisions into professional, reversible commitments
- **State machines before code**; **data flow diagrams** for anything regulated
- **Generate what you can**: OpenAPI, ERDs, lineage, class diagrams
- **If it is not worth keeping current, it is not worth writing** — five true pages beat eighty false ones
- **Different audiences need different documents** — and being able to switch registers fluently is a core architect skill

---

**Next:** [Chapter 23 — Architecture Governance](23-architecture-governance.md)
