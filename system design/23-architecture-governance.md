# Chapter 23 — Architecture Governance 🟢

> This is what separates a very good senior developer from an architect.
>
> A senior developer makes good decisions. An architect makes good decisions **possible across an organisation** — consistently, repeatedly, and without being in every room.

---

## 23.1 What governance is (and what it must not become)

**Governance = how architectural decisions get made, communicated, enforced and revisited.**

There are two failure modes, and both are common.

| **Ivory tower** (too much) | **Anarchy** (too little) |
|---------------------------|--------------------------|
| A central board approves every decision | Every team chooses everything |
| 6-week approval queues | 7 languages, 4 databases, 9 CI patterns |
| Architects who have not written code in years | Nobody can move between teams |
| Teams route around the process | The same problem solved badly, 12 times |
| Decisions made by people without context | No shared security or observability baseline |
| **Result: resentment, shadow IT, slow delivery** | **Result: unmaintainable sprawl, huge cognitive load** |

> **The goal is neither control nor freedom. It is *alignment*:** teams move fast and independently, and the results still fit together.

### The modern model: guardrails, not gates

```
OLD (gates):   Team proposes → Architecture Board reviews → approves/rejects → team builds
               Slow. Adversarial. Decisions made without context. Bypassed.

NEW (guardrails):
               Golden paths make the right thing easiest       (Chapter 16)
               Automated policy blocks the dangerous thing     (fitness functions)
               ADRs record decisions where teams make them     (Chapter 22)
               Lightweight review only for high-impact choices
               Architects embed with teams rather than sitting above them
```

**The principle: make the right thing the easy thing.** A policy that must be enforced by a human in a meeting will be bypassed. A policy enforced by a failing CI build will be followed.

---

## 23.2 Architecture principles as the foundation

Principles (Chapter 00 §0.13) are the mechanism by which teams make consistent decisions **without you in the room**. That is their entire purpose.

Good governance starts by publishing 5–8 principles, each with a rule, a reason and an implication — and then **testing every decision against them**.

```
Proposal: "We want to use MongoDB for the new reporting service."

Check against P3 (prefer boring, widely-known technology):
  → Do we already run MongoDB? No. Postgres, yes.
  → Does the reporting use case require a document model? Let us examine that.
  → If not: P3 says use Postgres. If yes: an ADR must name the operational owner.
```

That conversation takes three minutes and produces a decision the team owns. Without principles, it takes an hour and produces a preference.

---

## 23.3 Architecture review 🟢

### What to review — and what to leave alone

You cannot review everything, and you should not try.

```
REVIEW (high impact, expensive to reverse — the Chapter 00 definition)
  ✅ New services or new bounded contexts
  ✅ New datastores, brokers, or major frameworks
  ✅ Changes to service boundaries or data ownership
  ✅ Public API contracts
  ✅ Authentication / authorisation model changes
  ✅ Anything handling regulated data
  ✅ Multi-region / DR posture
  ✅ Cross-team integration points

DO NOT REVIEW (cheap to reverse — trust the team)
  ❌ Internal class structure
  ❌ Which testing or logging library
  ❌ Code style
  ❌ Refactoring within a service
```

> **Reviewing cheap decisions destroys the credibility you need for the expensive ones.** Spend your attention where reversal is costly.

### How to run a review that people want to attend

**The format that works:**

```
1. WRITTEN FIRST         A one-page design doc or draft ADR, circulated 48h ahead.
                         No slides. No live presentation of new information.

2. SILENT READING        First 10 minutes of the meeting, everyone reads and comments.
                         (This is the single biggest improvement you can make —
                          it guarantees everyone has actually read it.)

3. QUESTIONS, NOT VERDICTS
                         "What happens when the vendor is down?"
                         NOT "you should use Kafka"

4. DECISION AND OWNER    Approved / approved with conditions / needs rework.
                         The TEAM remains the owner either way.

5. ADR UPDATED           Within 48 hours, including what the review changed.
```

### The review questions — a reusable script

Work through these in order. They are almost mechanical, and they find real problems every time.

```
PROBLEM
  1. What problem does this solve? Who has it? How much does it cost them?
  2. What happens if we do nothing?

REQUIREMENTS
  3. What are the NFRs? (The 14-question checklist, Chapter 00)
  4. What is the expected load, and the load in 2 years?

DESIGN
  5. What alternatives were considered, and why were they rejected?
  6. What are we giving up with this choice?
  7. Where does the data live, and who owns it?
  8. What is the consistency model, and does the business accept it?

FAILURE   ⭐ the questions that find the most issues
  9. What happens when each dependency is slow? Down? Returns garbage?
 10. What is the blast radius of a failure here?
 11. How do we roll this back?
 12. What is the degraded mode?

OPERATIONS
 13. How do we know it is working? What are the SLIs and alerts?
 14. Who is on call for this?
 15. What does it cost per month, and per transaction?

SECURITY
 16. What data classification is involved? Who can access it?
 17. Where are the trust boundaries?

PEOPLE
 18. Does the team have the skills to operate this?
 19. Who maintains it in three years?
```

> **Questions 9–12 find more genuine problems than all the others combined.** Most designs describe the happy path beautifully and have never considered the failure path. Simply walking the diagram and asking "what if this box dies?" for each box is a mechanical process that reliably surfaces real gaps.

### The tone that makes reviews work

- **Review the design, never the person.** "This design has a single point of failure here" — not "you forgot redundancy."
- **Ask, do not instruct.** A question invites thinking; an instruction invites compliance or resistance.
- **Say what is good.** A review that is only criticism trains people to avoid reviews.
- **Let the team decide.** You advise; they own it. If you overrule, you now own the outcome — and you should be willing to say so explicitly.
- **Timebox it.** 45 minutes. If it needs longer, the proposal was not ready.

---

## 23.4 Technology selection 🟢

### The framework

```
1. WHAT PROBLEM does this solve?           (Chapter 00 — if you cannot answer, stop)
2. DO WE HAVE that problem, today or in 12 months?
3. CAN WE SOLVE IT with something we already run?      ⭐ the most-skipped question
4. What are the alternatives, including "do nothing"?
5. What does it cost — licence, infrastructure, AND human attention?
6. Who operates it at 3 AM?
7. What is the exit cost if it turns out to be wrong?
8. Is it mature? Maintained? Is there a community? Will it exist in 5 years?
```

**Question 3 is the one that saves the most money.** Before adding Elasticsearch, ask whether Postgres full-text search suffices. Before adding Kafka, ask whether the existing queue suffices. Before adding a graph database, ask whether a recursive CTE suffices. (Chapters 09–12 make this case repeatedly, because it keeps being true.)

### Evaluating a technology properly

| Dimension | Questions |
|-----------|-----------|
| **Fit** | Does it actually solve our problem, or a neighbouring one? |
| **Maturity** | Version 1.0? Production users at our scale? Age? |
| **Community** | Commit frequency, issue response time, number of maintainers |
| **Bus factor** | Is it one person's side project? |
| **Licence** | Permissive? Has it changed recently? (SSPL/BSL changes have burned many companies) |
| **Operability** | Can *our* team run it? Is there a managed option? |
| **Exit** | How hard to migrate away? Is the data in an open format? |
| **Skills market** | Can we hire people who know it? |
| **Total cost** | Licence + infra + training + operations + opportunity cost |

> **Bus factor and licence changes are the two risks people systematically under-weight.** A critical dependency maintained by one unpaid person, or a database that relicenses to a restrictive licence in version 6, are both scenarios that have caused real, expensive migrations recently.

### The technology radar ⭐

A living, published inventory of what is endorsed, tolerated, and forbidden.

```
ADOPT       Proven here. Use it by default.
            → PostgreSQL, Python/FastAPI, Terraform, OpenTelemetry, RabbitMQ

TRIAL       Promising. Approved for one non-critical use, with a named owner.
            → Temporal (for the onboarding saga), Dagster (data pipelines)

ASSESS      Worth understanding. Not for production yet.
            → Iceberg, eBPF observability, service mesh ambient mode

HOLD        Do not start new work with this. Existing use is being retired.
            → MongoDB (migrating to Postgres), self-managed Kafka (moving to MSK),
              jQuery, our in-house auth service
```

**Why it works better than a policy document:**
- It is **positive** — it tells people what *to* use, not just what not to
- **TRIAL creates a safe, bounded path to innovation** rather than forcing people to sneak things in
- **HOLD communicates direction** without banning overnight
- It is a **conversation**, reviewed quarterly with the teams — not a decree

> **Keep the ADOPT list short.** Its value is in what it *excludes*. An ADOPT list with four databases on it is not governance, it is a catalogue.

---

## 23.5 Reference architectures and golden paths

**Reference architecture:** the recommended shape for a common problem in your organisation.

```
REFERENCE: "Standard internal API service"

  Client → API Gateway (auth, rate limit) → Service (containers, 3 AZs)
                                              ├→ PostgreSQL (managed, Multi-AZ)
                                              ├→ Redis (cache, sessions)
                                              └→ Queue (async work, DLQ)

  Cross-cutting (provided, not rebuilt):
    OpenTelemetry (logs/metrics/traces) · Secrets manager · CI/CD pipeline
    Standard health endpoints · Standard error format (RFC 9457)

  Use this unless you have a documented reason not to (record it in an ADR).
```

**The golden path (Chapter 16) is the reference architecture made executable.** A template repository that generates all of it in one command is worth more than any number of documents, because architecture decisions embedded in a template are actually followed.

> **This is the highest-leverage governance mechanism there is.** Twenty teams reading a standards document produce twenty interpretations. Twenty teams using one template produce one architecture.

---

## 23.6 Automated governance — fitness functions ⭐ 🟢

**The core principle: a rule that is not automated is a rule that will be broken by Friday.**

Fitness functions (Chapter 00 §0.12) turn architectural principles into CI failures.

### The governance layers, from softest to hardest

```
1. GUIDANCE     Documentation, reference architectures, ADRs
                → Followed by the willing

2. TEMPLATES    Golden-path scaffolding
                → Followed by default, because it is easiest

3. LINTING      Warnings in CI
                → Noticed

4. CI GATES     Build fails
                → Enforced at development time

5. ADMISSION    Deployment rejected (OPA/Gatekeeper, policy as code)
                → Enforced at runtime; cannot be bypassed

6. RUNTIME      Continuous compliance scanning, auto-remediation
                → Catches drift and manual changes
```

**Use the softest layer that works, and escalate only where the risk justifies it.** Hard gates on everything is the ivory tower with better tooling.

### Fitness functions worth having

```python
# ── Structural (Chapter 01/02) ────────────────────────────────
"Domain layer must not import infrastructure"          import-linter / NetArchTest
"No service may have more than 5 inbound dependencies"  dependency graph check
"No cross-service database access"                      connection-string scan

# ── API (Chapter 08) ──────────────────────────────────────────
"No breaking API changes without a version bump"        oasdiff in CI
"Every endpoint documented in OpenAPI"                  spec coverage check
"Every list endpoint is paginated"                      spec lint rule

# ── Security (Chapter 17) ─────────────────────────────────────
"No CRITICAL CVEs in container images"                  Trivy, fails the build
"No secrets in source"                                  gitleaks, pre-commit + CI
"No storage bucket is public"                           Checkov / cloud config rule
"No database is internet-reachable"                     IaC policy
"All containers run as non-root"                        OPA Gatekeeper admission

# ── Operations (Chapters 15/18/19) ────────────────────────────
"Every pod has resource requests and probes"            admission policy
"Every service has an owner, a runbook and an SLO"      service-catalogue check
"Every resource is tagged with team and cost-centre"    cloud policy

# ── Performance (Chapter 20) ──────────────────────────────────
"Checkout p95 stays under 400 ms"                       nightly load test
"No endpoint makes more than 10 queries"                query-count test
```

```rego
# OPA/Gatekeeper — enforced at deployment, cannot be argued with
package kubernetes.admission

deny[msg] {
  input.request.kind.kind == "Deployment"
  c := input.request.object.spec.template.spec.containers[_]
  not c.resources.requests.memory
  msg := sprintf("Container %v must declare a memory request", [c.name])
}

deny[msg] {
  input.request.kind.kind == "Deployment"
  c := input.request.object.spec.template.spec.containers[_]
  endswith(c.image, ":latest")
  msg := sprintf("Container %v must not use the :latest tag", [c.name])
}
```

> **Every fitness function you add is a conversation you never have to have again.** That is how one architect scales across twenty teams.

**Two cautions:** introduce new rules as **warnings first**, then escalate to failure after teams have had time to comply — a rule that breaks everyone's build on day one destroys goodwill. And **every rule must have an escape hatch with an audit trail** (an annotated exemption that expires), because there will be legitimate exceptions and a rule with no exception path gets disabled entirely.

---

## 23.7 Dependency governance 🟡

### Internal dependencies

**The rules:**
```
1. No circular dependencies between services. Ever.
   (A→B→C→A means none can be deployed or understood independently.)
2. Dependencies flow toward stability (Chapter 01: stable things must not depend
   on unstable things)
3. No shared database access across service boundaries (Chapter 02)
4. Shared libraries are versioned and backward compatible — never a "common" library
   that every service must upgrade in lockstep (that is a distributed monolith)
5. The dependency graph is visible and reviewed
```

> **A shared "common" library that all services must upgrade together is one of the most common ways teams accidentally rebuild a monolith.** If changing a shared package forces a coordinated release of 12 services, you have deployment coupling regardless of what your diagram says.

### External dependencies

```
✅ Lockfiles committed; builds reproducible
✅ Automated vulnerability scanning (SCA) on every PR and daily
✅ SBOM generated per build — so "are we affected by CVE-X?" takes minutes
✅ Licence scanning — GPL in a proprietary product is a legal problem
✅ An approval step for new dependencies in critical services
✅ Regular update cadence — staying current is cheaper than a big-bang upgrade
✅ Bus-factor check on anything critical
```

**The transitive dependency problem:** you directly depend on 40 packages, which pull in 900. **You are responsible for all 900.** This is why SBOMs and automated scanning matter more than manual review — no human reads 900 packages.

---

## 23.8 Versioning and deprecation 🟢

### Versioning strategy

Publish one and apply it consistently.

| Artefact | Scheme |
|----------|--------|
| Public APIs | Path version for major (`/v1/`), additive for minor (Chapter 08) |
| Internal libraries | SemVer: `MAJOR.MINOR.PATCH` |
| Events / messages | Schema version in the envelope; full compatibility (Chapter 06) |
| Container images | Git SHA; deploy by digest. **Never `latest`.** |
| Databases | Sequential, forward-only migrations (Chapter 09) |

**SemVer in one line:** MAJOR = you broke something, MINOR = you added something, PATCH = you fixed something. **If you break a contract, the major version must change.** Failing to bump major on a breaking change is how you destroy trust in your own versioning.

### Deprecation — the process that keeps you credible

The hardest governance problem is not adding things. It is **removing** them.

```
1. ANNOUNCE      Communicate the removal date. Minimum notice:
                 internal APIs 3 months · public APIs 6-12 months · data formats 12 months

2. MARK          Deprecation headers (Chapter 08), compiler warnings, docs banners

3. MEASURE   ⭐  Who is still using it? Per-client usage metrics.
                 You cannot deprecate what you cannot measure.

4. ASSIST        Migration guide, automated codemod where possible, direct help
                 for the biggest consumers

5. ESCALATE      As the date nears: emails, then brownouts
                 (deliberately return errors for 1 hour, then 4 hours, then a day —
                  this finds the users who ignored every email)

6. REMOVE        On the announced date. Removing on time is what makes the
                 NEXT deprecation credible.

7. RECORD        An ADR noting what was removed and why
```

> **Step 3 is non-negotiable and step 6 is where organisations lose their nerve.** Deprecations that slip repeatedly train everyone to ignore deprecation notices — and then you can never remove anything. The **brownout** in step 5 is the technique that works: a scheduled, announced, temporary outage of the deprecated path surfaces every remaining consumer in an afternoon.

### Managing technical debt as governance

(Chapter 00 §0.11 covers the concept; this is the organisational mechanism.)

```
1. A visible register — tickets tagged, with an estimate of the INTEREST
   ("this costs ~2 days per sprint")
2. Priced in business terms — "each new payment method takes 3 weeks instead of 3 days"
3. A permanent budget — 15-20% of every sprint, not a mythical "cleanup sprint"
4. Reviewed quarterly alongside the architecture
5. Some debt is deliberately never repaid — code in a module being retired.
   Say so explicitly so nobody wastes effort on it.
```

---

## 23.9 Architecture at different organisation sizes 🟡

Governance must match the organisation. The same model applied at the wrong size fails badly.

| Size | Model | What governance looks like |
|------|-------|---------------------------|
| **< 15 engineers** | The senior engineers *are* the architects | ADRs in the repo. A shared template. Conversations. **No board, no process.** |
| **15–50** | One or two architects, embedded | Principles published. Golden path. Lightweight review for big decisions. A radar. |
| **50–200** | An architecture guild + embedded architects | Guild meets fortnightly; architects sit in teams. Fitness functions. Reference architectures. |
| **200+** | A formal function with domain architects | Enterprise standards, formal review for cross-cutting decisions, a platform team, a service catalogue |

### The architecture guild / chapter model ⭐

The pattern that works best in the 50–200 range:

```
- Architects are EMBEDDED in teams (they write code, they feel the consequences)
- They meet as a GUILD fortnightly to align on cross-cutting decisions
- The guild owns: principles, the radar, reference architectures, fitness functions
- Teams own: their own designs, within those guardrails
- Senior/principal architects facilitate rather than decide
```

**Why it beats a central board:** decisions are made by people with context, the architects stay technically credible, and alignment emerges from shared understanding rather than from approval queues.

> **The failure mode to watch for: architects who stop writing code.** Within 18 months their advice becomes theoretical, teams stop respecting it, and governance collapses into either bureaucracy or irrelevance. Chapter 00 said keep your hands dirty; this is the organisational reason why.

---

## 23.10 Measuring whether governance is working

Governance that cannot be measured becomes ritual. Track a small number of outcomes:

| Metric | Healthy signal |
|--------|---------------|
| **Lead time for a new service** | Hours to days, not weeks (the golden path works) |
| **% of services on the golden path** | High and rising (it is genuinely the easiest route) |
| **DORA metrics** (Chapter 16) | Improving — governance should not slow delivery |
| **Number of distinct technologies in production** | Stable or falling |
| **Fitness function violations** | Falling; and violations are caught in CI, not in production |
| **ADRs written per quarter** | Steady — decisions are being recorded |
| **Time in architecture review** | Short; and teams voluntarily bring things |
| **Incidents with an architectural root cause** | Falling |
| **Developer survey: "is the architecture process helpful?"** | ⭐ The honest one |

> **The last one is the real test.** If developers experience governance as an obstacle, it will be routed around — and then you have all the cost and none of the alignment. Ask them, act on the answer, and be willing to remove process that is not earning its keep.

---

## 23.11 Common mistakes

1. **Ivory tower** — architects who do not write code making decisions for people who do
2. **Reviewing everything** — credibility spent on decisions that are cheap to reverse
3. **Gates instead of guardrails** — slow, adversarial, and bypassed
4. **Rules that are not automated** — followed for two weeks, then forgotten
5. **New fitness functions that fail everyone's build on day one** — goodwill destroyed
6. **No escape hatch on policies** — so the policy gets disabled entirely
7. **No technology radar** — the same "can we use X?" debate every quarter
8. **An ADOPT list with everything on it** — a catalogue, not governance
9. **Deprecations that never complete** — nobody believes any deprecation notice again
10. **Deprecating without measuring usage** — you cannot remove what you cannot see
11. **A shared "common" library everyone must upgrade together** — accidental distributed monolith
12. **Governance that slows delivery** — DORA metrics will tell you; act on them
13. **Architecture decisions with no written record** — re-litigated forever
14. **Wrong governance model for the organisation's size** — a formal board at 12 engineers, or anarchy at 200

---

## 23.12 Architect's checklist

- [ ] 5–8 architecture principles published, each with rule, reason and implication
- [ ] Clear criteria for what requires review and what explicitly does not
- [ ] Review format: written first, silent reading, questions not verdicts, team retains ownership
- [ ] The 19 review questions used consistently — especially the failure questions
- [ ] ADRs for every significant decision, with revisit triggers (Chapter 22)
- [ ] A technology radar, reviewed quarterly with the teams
- [ ] Reference architectures documented **and** implemented as a golden-path template
- [ ] Fitness functions in CI for structure, API compatibility, security and operations
- [ ] Policy-as-code at admission for the non-negotiables
- [ ] New rules introduced as warnings before becoming failures
- [ ] Every policy has a documented, expiring exemption path
- [ ] Dependency rules: no cycles, no shared databases, no lockstep shared libraries
- [ ] SBOM, SCA and licence scanning automated
- [ ] Versioning scheme published per artefact type; SemVer honoured
- [ ] Deprecation process with notice periods, usage measurement, brownouts, and on-time removal
- [ ] Technical debt register with business-language interest and a permanent sprint budget
- [ ] Governance model matched to organisation size
- [ ] Architects still write code
- [ ] Governance effectiveness measured — including asking developers

---

## 23.13 Self-test

1. Define governance. Name the two failure modes and what each produces.
2. What is the difference between gates and guardrails? Why do guardrails win?
3. Give five things that deserve architecture review and four that do not. What is the deciding criterion?
4. Why is silent reading at the start of a review the single biggest format improvement?
5. Which review questions find the most real problems, and why?
6. What is the most-skipped question in technology selection?
7. What are the four states on a technology radar, and why is TRIAL important?
8. Why must the ADOPT list be short?
9. Name six governance layers from softest to hardest. Which should you prefer?
10. Why must new fitness functions start as warnings, and why must every policy have an escape hatch?
11. Why is a shared "common" library that everyone upgrades together dangerous?
12. Walk through the seven steps of a professional deprecation. Which two do organisations get wrong?
13. What is a brownout and what problem does it solve?
14. Describe the right governance model at 12, 40, 120 and 500 engineers.
15. What is the single most honest measure of whether governance is working?

---

## 23.14 Key takeaways

- **Governance is alignment, not control.** Neither ivory tower nor anarchy.
- **Guardrails, not gates.** Make the right thing the easy thing.
- **Review only what is expensive to reverse** — everything else is the team's decision
- **The failure questions ("what if this box dies?") find more problems than everything else combined**
- **A rule that is not automated will be broken by Friday** — fitness functions turn principles into CI failures
- **The golden path is the highest-leverage mechanism** — decisions in a template get followed; decisions in a document do not
- **A technology radar makes direction visible** and gives innovation a safe, bounded path
- **Ask "can we solve this with something we already run?"** before every new technology
- **Deprecation is harder than adoption** — measure usage, use brownouts, and remove on time
- **Match the governance model to the organisation's size**
- **Architects must keep writing code**, or governance becomes theatre
- **Measure governance itself** — including asking developers whether it helps

---

**Next:** [Chapter 24 — Integration Architecture](24-integration-architecture.md)
