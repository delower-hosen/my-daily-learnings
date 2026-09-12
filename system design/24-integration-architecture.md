# Chapter 24 — Integration Architecture 🟢

> In most enterprises, **more effort goes into connecting systems than into building them**.
>
> Integration is where architectures actually fail — not in the clean new service you designed, but at the seam between it and the 1998 mainframe that nobody understands and nobody may change.

---

## 24.1 The integration styles

Gregor Hohpe's four fundamental styles. Every integration is one of these, or a combination.

```
1. FILE TRANSFER        System A writes a file; System B reads it
2. SHARED DATABASE      Both systems read/write the same tables
3. REMOTE PROCEDURE     System A calls System B and waits
4. MESSAGING            System A sends a message; System B processes it later
```

| Style | Coupling | Timeliness | Reliability | Complexity | Verdict |
|-------|----------|-----------|-------------|------------|---------|
| **File transfer** | Very low | Poor (batch) | Good (files persist) | Low | Still correct for bulk and legacy |
| **Shared database** | **Extreme** | Immediate | Good | Low to build | ☠️ **Almost always wrong** |
| **RPC / API** | Medium | Immediate | Poor (both must be up) | Medium | Right when you need the answer now |
| **Messaging** | Low | Near real-time | **Excellent** | Higher | The default for system-to-system |

### Why shared database integration is the one to fight

It is the easiest to build and by far the most expensive to live with.

```
System A ──┐
           ├──► [ SHARED DATABASE ]
System B ──┘
```

- Neither system can change its schema without breaking the other
- No system truly *owns* the data, so business rules are enforced in two places — differently
- One system's bad query locks the other's transactions
- You cannot deploy, scale, or replace either independently
- Data integrity depends on every application getting it right, forever

> **It is the root cause of the distributed monolith** (Chapter 02), and it is usually introduced by someone who thought they were saving time. If you find yourself proposing it, propose an API or an event stream instead — and if the argument is "we need the data now", the answer is a read replica or a projection, not shared write access.

---

## 24.2 Synchronous integration (API-based) 🟢

Covered in depth in Chapter 08. The integration-specific concerns:

### When synchronous is correct

```
✅ The caller genuinely cannot continue without the answer
   - "Is this card valid?" before completing checkout
   - "What is this customer's current balance?"
   - "Is this user authorised?"

❌ The caller does not need the answer now
   - "Send a welcome email"
   - "Update the analytics warehouse"
   - "Notify the partner system"
   → These should be asynchronous. Making them synchronous couples your
     availability to theirs for no benefit.
```

### The availability arithmetic you must do

```
Your service (99.9%) synchronously calls three partners (99.5%, 99.9%, 99.0%):

  Combined = 0.999 × 0.995 × 0.999 × 0.990 = 0.983 = 98.3%
  → 12 hours of downtime per month, most of it not your fault

Make two of those async, and you depend on one partner:
  Combined = 0.999 × 0.995 = 99.4%
  → 4 hours per month
```

> **Every synchronous dependency you add lowers your ceiling.** This calculation belongs in every integration design review.

### Non-negotiables for any synchronous integration

Every one from Chapter 05, applied at the boundary:

```python
class PartnerClient:
    """Everything a production integration needs. No exceptions."""
    # 1. TIMEOUT          — never infinite
    # 2. RETRY + JITTER   — idempotent operations only
    # 3. CIRCUIT BREAKER  — stop calling a dead partner
    # 4. BULKHEAD         — a slow partner must not exhaust your threads
    # 5. FALLBACK         — cached value, default, or degraded mode
    # 6. IDEMPOTENCY KEY  — safe retries
    # 7. ACL              — their model never reaches your domain (Chapter 03)
    # 8. OBSERVABILITY    — latency, error rate, and circuit state per partner
```

---

## 24.3 Asynchronous integration 🟢

Chapter 06 covers messaging. The integration-specific patterns:

### Event-driven integration between organisations

```
   Your system ──publish──► [ Event stream / queue ]
                                      │
                            ┌─────────┼─────────┐
                            ▼         ▼         ▼
                      Partner A   Partner B   Internal
                                              consumers
```

**Advantages across an organisational boundary:**
- Their downtime does not become your failure
- You can add a consumer without renegotiating anything
- Natural buffering for traffic spikes
- The event log gives you a reconciliation record

**The critical discipline:** the events you publish externally are a **public contract** (Chapter 06 §6.12). They must be versioned, documented, backward compatible, and deliberately designed — **never a raw dump of your internal model**.

### Webhooks (Chapter 08 §8.16)

The standard way to push events to another company. The provider checklist there is the complete one: sign with a timestamp, retry with backoff, stable event IDs, fast timeout, replay UI, versioned payloads, published egress IPs — **and always offer a polling endpoint as well**, because many enterprise customers cannot accept inbound traffic.

---

## 24.4 File-based and batch integration 🟡

**Do not dismiss it.** It is still the correct answer for bulk data, for many legacy systems, and for most B2B and government interfaces. A nightly SFTP drop is not a design failure if the business genuinely operates on a daily cycle.

```
  Partner ──SFTP──► /incoming/ ──► Validate ──► Process ──► /archive/
                                       │
                                       └── invalid ──► /error/ + alert
```

### The rules that make file integration reliable

```
1. ATOMIC ARRIVAL      Write to `file.tmp`, then rename to `file.csv`.
                       Otherwise you will process half a file. This is the
                       single most common file-integration bug.
   Or: a `.done` marker file written after the data file completes.

2. IDEMPOTENT          Track processed filenames/hashes. Re-delivery happens
                       constantly and must be harmless.

3. VALIDATE FIRST      Schema, row count, checksum, and a business sanity check
                       (a payroll file with 3 rows instead of 3,000 is an ALERT,
                        not an input)

4. ALL OR NOTHING      Stage into a temporary table, validate, then swap.
                       Never leave a half-loaded dataset visible.

5. ARCHIVE EVERYTHING  Keep the original file. You will need it for a dispute
                       or a reprocess.

6. ALERT ON ABSENCE ⭐ The file that does NOT arrive is the failure nobody
                       notices for three days. Alert on "expected by 06:00,
                       not received."

7. AGREE THE CONTRACT  Encoding, delimiter, quoting, date format, decimal
                       separator, line endings, timezone, null representation,
                       and what happens on error. In writing. Every field.

8. NAME DETERMINISTICALLY   `partner_transactions_20260912_001.csv`
```

> **Rules 1 and 6 cause more incidents than all the others combined.** Partial file reads corrupt data silently; missing files are discovered days later when someone asks why the numbers are wrong.

**Formats:** CSV (universal, ambiguous — agree the dialect precisely), fixed-width (legacy, brutal, still common in banking), XML (verbose, schema-validated), JSON Lines (streamable, good for modern pipelines), **Parquet** (columnar, compressed — the right choice for analytical bulk transfer, Chapter 12).

---

## 24.5 Change Data Capture as integration 🟢

Chapter 12 covers CDC mechanically. As an **integration pattern** it is powerful and under-used:

```
Legacy system's database ──WAL/log──► Debezium ──► Kafka ──► Your new services
```

**Why this matters enormously for legacy integration:** you get near-real-time data from a system you are **not allowed to modify**. No code changes to the legacy application, no polling load, no missed deletes, exact transaction ordering.

This is often the only viable path when:
- The legacy system has no API and cannot get one
- The vendor will not (or contractually may not) change it
- The team that owns it has a 9-month backlog
- You need events but the system was never designed to emit them

**The caveats:** you are coupling to their *schema*, not to a contract — so a schema change breaks you silently. Mitigate with an **Anti-Corruption Layer immediately downstream of the CDC stream** (Chapter 03), which translates their table shapes into your events. That ACL is the contract you wish they had given you.

---

## 24.6 Legacy integration 🟢

This is the work that defines enterprise architecture. It is rarely glamorous and it is where the real skill shows.

### The realities

- You **cannot** change it (no source, no team, no budget, or a vendor contract forbids it)
- It has no API, or a SOAP API from 2006
- It is a single machine with no redundancy
- Its data model reflects 1990s business processes
- It goes down for a four-hour maintenance window every Sunday
- Nobody alive fully understands it

### The integration options, in order of preference

```
1. API (if one exists)          Cleanest. Wrap it in an ACL immediately.
2. CDC from its database        Read-only, no changes to it, near real-time.
3. File exchange                Universal, reliable, batch latency.
4. Screen scraping / RPA        Last resort. Brittle. Breaks on any UI change.
5. Direct database writes       ☠️ Bypasses ALL its business logic. Almost never
                                acceptable — and if forced, isolate it ruthlessly.
```

### The Anti-Corruption Layer is mandatory here ⭐

```
┌──────────────────┐   ┌──────────────┐   ┌─────────────────────┐
│  YOUR CLEAN      │   │     ACL      │   │  LEGACY SYSTEM      │
│  DOMAIN          │◄──┤              ├──►│                     │
│                  │   │  translate   │   │  CUST_MSTR_REC      │
│  Customer        │   │  retry       │   │  STAT_CD: "A"/"I"   │
│   .Email         │   │  cache       │   │  DT_CRT: "19980304" │
│   .Status        │   │  fallback    │   │  SOAP 1.1, EBCDIC   │
└──────────────────┘   └──────────────┘   └─────────────────────┘

  ONE component knows the legacy system exists. Nothing else does.
```

Everything covered in Chapter 03 §3.5 applies. In legacy work it is not a nice-to-have — **without it, the legacy model infects your entire new system and you have built a second legacy system.**

### The Strangler Fig migration ⭐

The only safe way to replace a legacy system (Chapter 00 §0.12).

```
Step 1:  Client ─────────────────────► Legacy

Step 2:  Client ──► Facade ──┬───────► Legacy
                             └───────► New Service (one capability)
         Facade routes by feature. Both systems live. Nothing breaks.

Step 3:  Client ──► Facade ──┬───────► Legacy (shrinking)
                             ├───────► New Service A
                             └───────► New Service B

Step 4:  Client ──► Facade ──┬───────► New Service A
                             └───────► New Service B    (legacy decommissioned)
```

**Making it work in practice:**

1. **Start with a read-only capability.** Lowest risk, builds confidence, proves the facade.
2. **Run both in parallel and compare** — send traffic to both, serve the legacy answer, log the differences. This is **shadow traffic** (Chapter 21), and it is how you gain real confidence before switching.
3. **Migrate data ownership last.** Two systems writing to the same data is the dangerous phase; keep it short and keep one side authoritative throughout.
4. **Make each step independently valuable and reversible.** If the programme is cancelled after step 2 — which happens — the work done so far must still have delivered something.
5. **Plan for the long tail.** The last 10% of a legacy system takes 40% of the effort, because it is the weird parts nobody documented.

> **Never attempt a big-bang rewrite.** The failure rate is famously high, and the reason is structural: you must reimplement years of undocumented edge cases while the original keeps changing, with no value delivered until the very end.

---

## 24.7 ESB, iPaaS and the middleware question 🟡

### The Enterprise Service Bus

Chapter 02 §2.4 covers why it fell out of favour: business logic migrated into the bus, the bus became a bottleneck and a monolith, and the integration team became a queue everyone waited in.

**But you will meet one** (MuleSoft, WSO2, BizTalk, TIBCO, IBM IIB) in any established enterprise. **Do not simply declare it obsolete.** It genuinely does provide protocol bridging, transformation, and a governed catalogue of integrations — and replacing it is a multi-year programme.

**The pragmatic architect's position:** keep the bus for what it is good at (legacy protocol bridging, mainframe adapters, established B2B flows), and build new integrations with modern patterns (APIs, events) alongside it. Use the Strangler Fig on the bus itself if it must go.

> **The rule that matters, whatever the technology: keep business logic out of the pipes.** "Smart endpoints, dumb pipes." When routing logic starts making business decisions, you have recreated the problem regardless of whether the tool is called an ESB, an API gateway, or a service mesh.

### iPaaS

Cloud integration platforms (Workato, Boomi, MuleSoft Anypoint, Azure Logic Apps, Zapier at the small end) — hosted connectors and low-code flows.

- ✅ Hundreds of pre-built SaaS connectors; fast for business-process integration; often usable by non-engineers
- ❌ Per-operation pricing that scales badly; limited version control and testing; logic that lives outside your codebase; real lock-in

**A sensible dividing line:** iPaaS for **business-process integration** (Salesforce → NetSuite → HubSpot), custom code for **product integration** (anything in your critical path or your differentiating logic).

---

## 24.8 Data transformation and mapping 🟢

Every integration involves translating between models. This is where the subtle, expensive bugs live.

### The layers of translation

```
1. PROTOCOL   SOAP ↔ REST ↔ gRPC ↔ file
2. FORMAT     XML ↔ JSON ↔ CSV ↔ Avro ↔ fixed-width
3. STRUCTURE  nested ↔ flat, one row ↔ many rows
4. SEMANTIC   ⭐ their "customer" ↔ your "customer"   ← the hard one
5. VALUE      "A" ↔ Active, 20260912 ↔ 2026-09-12, USD cents ↔ decimal
```

**Layers 1–3 are mechanical. Layer 4 is where projects fail** — and it is not a technical problem, it is a domain problem (Chapter 03). Their "order" includes cancelled orders; yours does not. Their "active customer" means "logged in within 90 days"; yours means "has a paid subscription". These mismatches are invisible in a field-mapping spreadsheet and catastrophic in production.

> **Always ask: "what does this field mean to *you*?" — not "what is this field called?"** The answer is frequently different from what the name implies, and you will only discover it by asking a human.

### Mapping discipline

```
✅ Explicit mapping in code or a versioned mapping file — never implicit
✅ Handle missing/null/empty distinctly — they are three different things
✅ Validate AFTER mapping, not only before
✅ Fail loudly on an unknown enum value — never silently default it
✅ Preserve the original payload for debugging and reprocessing
✅ Log the transformation for a sampled subset
✅ Unit-test the mapper with real payloads, including malformed ones
✅ Agree units and precision explicitly (cents vs dollars; metres vs feet)
```

```python
def map_partner_status(code: str) -> CustomerStatus:
    mapping = {"A": CustomerStatus.ACTIVE,
               "I": CustomerStatus.INACTIVE,
               "S": CustomerStatus.SUSPENDED}
    try:
        return mapping[code]
    except KeyError:
        # ❌ NEVER: return CustomerStatus.INACTIVE  (silently wrong forever)
        # ✅ Fail loudly. An unknown value means their model changed and we must know.
        raise UnknownPartnerStatusError(
            f"Unknown partner status code {code!r}. "
            f"Known: {sorted(mapping)}. The partner's model may have changed."
        )
```

> **Silently defaulting an unknown enum is one of the most damaging habits in integration work.** The partner adds status "P" for "pending"; you map every one of them to INACTIVE; six months later someone notices that thousands of customers were treated incorrectly, and there is no record of which ones.

### Canonical data model — use with care ⚪🟡

The idea: instead of N² point-to-point mappings, map everything to and from one shared canonical model (N×2 mappings).

```
POINT-TO-POINT              CANONICAL
A ↔ B, A ↔ C, A ↔ D          A ↔ [CANONICAL] ↔ B
B ↔ C, B ↔ D, C ↔ D          C ↔     ↕      ↔ D
6 mappings for 4 systems     4 mappings for 4 systems
```

**The appeal is real, and so is the trap.** The canonical model becomes a committee-owned artefact that must satisfy every system, so it accumulates every field anyone needs, pleases nobody, and becomes the bottleneck every change must pass through — a shared kernel at organisational scale (Chapter 03).

**When it works:** a genuine industry standard exists (FHIR in healthcare, ISO 20022 in payments, ACORD in insurance). Then you are conforming to an external standard, not inventing one, and the governance problem is somebody else's.

**When it does not:** an internally-invented canonical model across a handful of systems. Point-to-point with good ACLs is usually simpler and more honest at that scale.

---

## 24.9 Reliability across organisational boundaries 🟢

Everything in Chapter 05 applies, plus these integration-specific realities:

### Reconciliation ⭐ — the pattern people forget

For any integration that matters financially or legally, **verify periodically that both sides agree.**

```python
async def daily_reconciliation(date: date) -> ReconciliationReport:
    ours   = await our_db.summarise(date)        # count, sum, hash of IDs
    theirs = await partner.fetch_summary(date)

    report = ReconciliationReport(date=date)
    if ours.count != theirs.count:
        report.add_discrepancy("count", ours.count, theirs.count)
        missing_here  = set(theirs.ids) - set(ours.ids)
        missing_there = set(ours.ids)   - set(theirs.ids)
        report.add_detail(missing_here=missing_here, missing_there=missing_there)
    if ours.total != theirs.total:
        report.add_discrepancy("total", ours.total, theirs.total)

    if report.has_discrepancies:
        await alerts.raise_(severity="high", report=report)
    return report
```

> **Every integration drifts.** Messages are lost, retries create duplicates, a deploy drops a batch, a partner has an incident and silently reprocesses. **Reconciliation is how you find out in a day instead of in a quarterly audit.** For anything involving money, it is not optional — and having it is the difference between a two-hour investigation and a two-week forensic exercise.

### The dead letter process

A DLQ nobody monitors is a data-loss mechanism (Chapter 06). For partner integrations specifically:

```
1. Alert on DLQ depth > 0, always
2. Categorise: their bad data / our bug / transient
3. Their bad data  → notify the partner with the specific record and reason
4. Our bug         → fix, then replay
5. Transient       → replay
6. Keep an audit trail of everything replayed
```

### Partner SLAs and expectation management

```
Document for every partner:
  - Their committed availability and latency
  - Their maintenance windows (and whether they honour them)
  - Their rate limits and quotas
  - Their support contact, escalation path, and response times
  - What happens when they are down: do we queue, degrade, or fail?
  - Contractual obligations in both directions
```

> **Then design assuming they will breach it**, because they will. Their 99.9% SLA does not help your customers at 3 AM — only your fallback does.

---

## 24.10 Designing an integration — a worked example

**Requirement:** integrate with a bank's KYC system to check sanctions lists during verification.

```
1. UNDERSTAND
   - What: check a name/DOB against sanctions lists
   - When: during verification, before we return a decision
   - Volume: 33,000/day, peak 2/sec
   - Criticality: a false negative is a regulatory breach. This is high stakes.

2. THEIR INTERFACE
   - SOAP over mTLS (their choice; not negotiable)
   - p95 latency 1.2 s, p99 4 s
   - SLA 99.5% (≈3.6 hours downtime/month)
   - Rate limit 10/sec
   - Maintenance: Sundays 02:00-06:00 UTC

3. SYNC OR ASYNC?
   - We need the answer before concluding the verification → SYNCHRONOUS
   - BUT their 99.5% × our 99.9% = 99.4% → too low for our SLO
   → DESIGN: synchronous with a queue-and-review fallback

4. THE DESIGN
   Verification Worker
        │
        ▼
   ┌──────────────────────────────────────────────┐
   │  SanctionsScreeningAdapter  (the ACL)         │
   │   • SOAP client, mTLS, their WSDL             │
   │   • translate their model → our SanctionsHit  │
   │   • timeout 5s · retry 2× with jitter         │
   │   • circuit breaker (30% over 20 calls)       │
   │   • bulkhead: max 8 concurrent (their limit/2)│
   │   • cache: identical name+DOB for 24h         │
   │   • rate limiter: 8/sec (below their 10)      │
   └───────────────┬──────────────────────────────┘
                   │ unavailable / breaker open
                   ▼
   ┌──────────────────────────────────────────────┐
   │  FALLBACK: mark the session MANUAL_REVIEW     │
   │  and queue for screening when they return.    │
   │  We NEVER auto-pass without a screen —        │
   │  that would be the regulatory breach.         │
   └──────────────────────────────────────────────┘

5. FAILURE MODES
   Their system slow      → timeout at 5s → retry → fallback to review
   Their system down      → breaker opens → all sessions go to review
                            → alert operations: review queue will grow
   Their maintenance      → scheduled: pre-emptively route to review, notify ops
   They return malformed  → ACL raises a typed error → review, and alert us
   Rate limited (429)     → honour Retry-After; our own limiter should prevent it

6. OBSERVABILITY
   - Latency and error rate per outcome; circuit-breaker state
   - Count of sessions sent to manual review because of unavailability
   - Cache hit ratio
   - Daily reconciliation: our screen count vs their reported count

7. COMPLIANCE
   - Every screening request and response retained 7 years (audit requirement)
   - PII sent is minimised: name, DOB, nationality only
   - mTLS certificates inventoried with expiry alerting (Chapter 13)

8. ADR
   Records: why synchronous, why the review fallback rather than auto-pass,
   the accepted availability impact, and the trigger to revisit
   (if their SLA or our volume changes materially).
```

**Note the shape of the thinking:** the technical integration is straightforward. The architecture is in the **fallback decision** — and that decision was driven by a regulatory constraint, not a technical one. That is what integration architecture actually is.

---

## 24.11 Common mistakes

1. **Shared database integration** — extreme coupling, no ownership, and a distributed monolith
2. **Synchronous when async would do** — your availability is now the product of everyone's
3. **No Anti-Corruption Layer** — their model spreads through your entire codebase
4. **No timeout / retry / circuit breaker** on a partner call — one slow partner takes you down
5. **Retrying non-idempotent operations** — duplicate payments to a partner
6. **Silently defaulting unknown enum values** — quietly wrong data, for months
7. **Non-atomic file arrival** — processing half a file
8. **No alert on a file that fails to arrive** — discovered three days later
9. **No reconciliation** — drift found in a quarterly audit rather than tomorrow morning
10. **A DLQ nobody monitors** — a data-loss mechanism with a professional name
11. **Business logic in the integration layer** — the ESB monolith, reborn
12. **An internally-invented canonical model** — a committee-owned bottleneck
13. **Publishing internal models as external events** — you can never change them again
14. **Big-bang legacy rewrite** — famously and structurally likely to fail
15. **Mapping field names without asking what they mean** — the semantic mismatch that surfaces in production

---

## 24.12 Architect's checklist

- [ ] Integration style chosen deliberately; shared-database integration rejected
- [ ] Synchronous used only where the caller genuinely needs the answer now
- [ ] Combined availability calculated for every synchronous chain
- [ ] Every external call: timeout, retry with jitter, circuit breaker, bulkhead, fallback
- [ ] Every external system behind an **Anti-Corruption Layer**
- [ ] Idempotency keys on every non-idempotent outbound operation
- [ ] Published events designed as a public contract, versioned, backward compatible
- [ ] Webhook provider checklist met (signed, retried, deduplicable, replayable) + polling alternative
- [ ] File integration: atomic arrival, idempotent, validated, staged, archived
- [ ] **Alert on expected files that do not arrive**
- [ ] Field mapping explicit, tested with real payloads, fails loudly on unknown values
- [ ] Semantic meaning of each field confirmed with a human, not inferred from the name
- [ ] **Reconciliation job** for every financially or legally significant integration
- [ ] DLQ monitored, categorised, and replayable with an audit trail
- [ ] Partner SLA, rate limits, maintenance windows and escalation path documented
- [ ] Behaviour during partner downtime explicitly designed and agreed with the business
- [ ] Legacy replacement uses Strangler Fig with parallel-run comparison
- [ ] Certificates for mTLS integrations inventoried with expiry alerting
- [ ] Compliance: data minimised, retention defined, audit trail retained

---

## 24.13 Self-test

1. Name the four integration styles and the trade-off of each.
2. Why is shared-database integration almost always wrong? Give four specific consequences.
3. Your service is 99.9% and calls three partners at 99.5%, 99.9% and 99.0% synchronously. What is your availability? How do you improve it?
4. Give three things that should be synchronous and three that should not.
5. Why is an ACL mandatory for legacy integration rather than merely advisable?
6. What is CDC's specific advantage for integrating with a system you may not modify? What is the risk, and how do you mitigate it?
7. State the eight rules of reliable file integration. Which two cause the most incidents?
8. Why is alerting on a *missing* file more important than alerting on a malformed one?
9. Why is silently defaulting an unknown enum value so damaging? What should you do instead?
10. What is the semantic layer of transformation, and why do projects fail there?
11. When is a canonical data model appropriate, and when is it a trap?
12. What is reconciliation, why does every integration need it, and what does its absence cost?
13. Describe the Strangler Fig pattern and the five things that make it work in practice.
14. Why is a big-bang legacy rewrite structurally likely to fail?
15. Walk through designing an integration with a partner whose SLA is lower than yours.

---

## 24.14 Key takeaways

- **Integration is where architectures actually fail** — design it with the same rigour as the system itself
- **Never integrate via a shared database.** It is the root of the distributed monolith.
- **Every synchronous dependency lowers your availability ceiling** — do the multiplication, out loud, in the review
- **An Anti-Corruption Layer at every external boundary.** One file knows the vendor exists.
- **Async by default** for system-to-system; synchronous only when the answer is needed now
- **Published events are a public contract** — versioned, compatible, deliberately designed
- **File integration is still valid** — atomic arrival, idempotency, validation, and an alert on absence
- **CDC gives you events from systems you may not modify** — with an ACL to make it a contract
- **Never silently default an unknown value.** Fail loudly; their model changed and you need to know.
- **Reconcile.** Every integration drifts; find out tomorrow, not in the audit.
- **Strangler Fig, never big bang.** Parallel-run and compare before switching.
- **The architecture is usually in the fallback decision**, not in the protocol

---

**Next:** [Chapter 25 — Capstone: Six Systems Designed End-to-End](25-capstone-case-studies.md)
