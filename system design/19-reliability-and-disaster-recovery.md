# Chapter 19 — Reliability & Disaster Recovery 🟡

> Reliability is not achieved by preventing failure. Failure is guaranteed.
> Reliability is achieved by **making failure survivable, contained, and boring**.
>
> Two numbers govern this entire chapter: **RTO** (how fast can we recover?) and **RPO** (how much data can we lose?). Know both, for every system, cold.

---

## 19.1 The vocabulary, precisely

People use these words loosely and then build the wrong thing. Be exact.

| Term | Meaning | Example |
|------|---------|---------|
| **Availability** | Is it up *right now*? | 99.9% of the time, requests succeed |
| **Reliability** | Does it work *correctly, over time*? | It has not corrupted data in 3 years |
| **Durability** | Will the data still exist? | S3's 11 nines — one object lost per 10,000 objects per 10 million years |
| **Fault tolerance** | Keeps working *despite* a failure | A node dies; no user notices |
| **High availability (HA)** | Automatic recovery, minimal downtime | Failover in 60 seconds |
| **Disaster recovery (DR)** | Recovery from a *large-scale* event | A whole region is gone; restore elsewhere |
| **Resilience** | Absorbs disturbance and adapts | Degrades gracefully under load |

**HA vs DR is the distinction people most often blur:**

```
HIGH AVAILABILITY            DISASTER RECOVERY
scope:     one component      scope:     the whole system/site
trigger:   node/AZ failure    trigger:   region loss, ransomware, data corruption
response:  automatic          response:  usually a human decision
time:      seconds–minutes    time:      minutes–days
cost:      moderate           cost:      significant
```

> **HA does not give you DR.** Multi-AZ database replication protects you from a datacenter failure. It does **not** protect you from someone running `DELETE FROM orders` — that statement replicates perfectly to every replica in milliseconds. **Only backups protect you from logical corruption.** This confusion has ended companies.

---

## 19.2 RTO and RPO ⭐ 🟢

```
        ◄────── RPO ──────►│◄────── RTO ──────►
   ─────┬──────────────────┬───────────────────┬──────►  time
        │                  │                   │
   last good            DISASTER           service
   backup/replica                          restored

   RPO = how much DATA you can afford to lose  (measured backwards from the failure)
   RTO = how long you can afford to be DOWN    (measured forwards)
```

### How to get real numbers from the business

Do not ask *"what RPO do you need?"* — everyone says zero. Ask about consequences:

| Question | What it reveals |
|----------|-----------------|
| "If we lost the last hour of data, what would you have to do?" | RPO tolerance, and whether the data is reconstructible |
| "If we were down for 4 hours on a Tuesday morning, what happens?" | RTO tolerance |
| "Could you rebuild the last hour from emails, paper, or the partner's system?" | Whether a large RPO is genuinely survivable |
| "What would you tell customers?" | The reputational cost |
| "Which is worse: down for 8 hours, or losing 15 minutes of transactions?" | **The RTO/RPO priority** — and they are often in tension |

**Different systems in one company deserve different numbers:**

| System | RPO | RTO | Reasoning |
|--------|-----|-----|-----------|
| Payment ledger | **0** | 15 min | Financial and legal; nothing may be lost |
| Verification sessions | 5 min | 1 hour | Sessions can be redone by the user |
| Audit log | 0 | 24 h | Must not be lost; can be read later |
| Analytics warehouse | 24 h | 48 h | Rebuildable from source systems |
| Marketing site | 24 h | 4 h | Low impact |

> **Uniform RTO/RPO across all systems is a design smell.** It means nobody asked, and you are either over-paying for the unimportant parts or under-protecting the critical ones.

**The cost curve is steep and non-linear:**

```
RPO = 24h    nightly backup                              $
RPO = 1h     hourly snapshots + WAL archiving            $$
RPO = 5min   continuous WAL shipping, async replica      $$$
RPO = 0      synchronous replication (+ latency cost)    $$$$$

RTO = 24h    restore from backup, rebuild infrastructure  $
RTO = 4h     IaC + automated restore, tested             $$
RTO = 1h     warm standby                                $$$
RTO = 5min   hot standby with automated failover         $$$$
RTO = 0      active-active multi-region                  $$$$$$
```

Show the business this table. **"RPO zero" costs ten times "RPO five minutes", and the conversation changes immediately** when they see the price of the last few minutes.

---

## 19.3 Redundancy and the levels of failure 🟢

```
LEVEL              FAILURE                     PROTECTION
────────────────────────────────────────────────────────────────────
Component          Disk dies                   RAID, replicas
Process            App crashes                 Restart, multiple instances
Host               Server fails                Multiple hosts, orchestration
Rack               Rack power fails            Spread across racks
Availability Zone  Datacenter fails            MULTI-AZ  ← the essential one
Region             Region fails                Multi-region DR
Cloud provider     Provider outage             Multi-cloud (rarely justified)
Logical            Bad deploy / bad DELETE     BACKUPS + rollback  ← replication cannot help
```

> **The most important line in that table is the last one.** Redundancy protects against *infrastructure* failure. It offers zero protection against *logical* failure — a bug, a bad migration, a malicious insider, or ransomware. Those need backups, point-in-time recovery, and immutability.

### N+1, N+2, 2N

| Model | Meaning | Example |
|-------|---------|---------|
| **N** | Exactly enough capacity | 4 servers handle the load — any loss degrades service |
| **N+1** | One spare | 5 servers; survive losing one |
| **N+2** | Two spares | Survive one failure *during* maintenance |
| **2N** | Full duplication | 8 servers; survive losing half |

**The AZ calculation people get wrong:**

```
You need 6 servers of capacity, deployed across 3 AZs.
Naive:  2 per AZ = 6 total.
        Lose one AZ → 4 servers → only 67% of required capacity → degraded.

Correct: enough that losing one AZ still leaves full capacity.
        3 per AZ = 9 total. Lose one AZ → 6 remaining → full capacity. ✅
```

**Rule: with N availability zones, each AZ must carry no more than 1/(N−1) of total required capacity.** With 3 AZs, you run 1.5× the minimum. That 50% overhead is the price of surviving an AZ loss without degradation — and it is far cheaper than the incident.

### Active-active vs active-passive

| | **Active-Passive** | **Active-Active** |
|---|---|---|
| Standby | Idle (or serving nothing) | Serving traffic |
| Failover | Promote the standby | Traffic simply shifts |
| RTO | Minutes | Seconds |
| Cost efficiency | Half the capacity is idle | All capacity is used |
| Complexity | Lower | **Much higher** — conflict resolution, data consistency |
| Confidence | **The standby is untested** until you need it | Continuously proven |

> **The hidden argument for active-active: an untested standby usually does not work.** Configuration drifts, certificates expire, capacity was never validated. Active-active is continuously exercised. If you are going to build a second site, seriously consider making it carry real traffic — even 10% — so you know it works.

---

## 19.4 Disaster recovery patterns 🟢

Four standard patterns, in increasing cost and decreasing RTO.

### 1. Backup and Restore

```
Primary region: everything running
DR region:      nothing — just backups in object storage

Disaster → provision infrastructure (IaC) → restore data → repoint DNS
```

| RTO | RPO | Cost | Use for |
|-----|-----|------|---------|
| Hours to days | Hours | **$** (storage only) | Internal tools, dev, low-criticality systems |

**This is only viable if your infrastructure is fully coded** (Chapter 16). Without IaC, "provision infrastructure" means weeks, not hours.

### 2. Pilot Light

```
Primary region: everything running
DR region:      database replica running + AMIs/images ready; compute switched OFF

Disaster → start the compute (already-built images) → promote the DB → repoint DNS
```

| RTO | RPO | Cost | Use for |
|-----|-----|------|---------|
| 10 min – 2 h | Seconds to minutes | **$$** | Most business systems — **usually the best value** |

The "pilot light" is the always-on data replication. Compute is cheap to start; data is slow to move. That asymmetry is why this pattern works so well.

### 3. Warm Standby

```
Primary region: full capacity
DR region:      a scaled-down but RUNNING copy (say 10-25% capacity)

Disaster → scale up → shift traffic
```

| RTO | RPO | Cost | Use for |
|-----|-----|------|---------|
| 5 – 30 min | Seconds | **$$$** | Revenue-critical systems |

**Advantage over pilot light: it is continuously running, so you know it works.** You can even route a small percentage of real traffic to it as a live test.

### 4. Multi-site Active-Active

```
Both regions serving traffic, data replicated bidirectionally or partitioned by region
```

| RTO | RPO | Cost | Use for |
|-----|-----|------|---------|
| Near zero | Near zero | **$$$$$$** | Global scale, or a regulatory requirement |

**The hard part is never the compute — it is the data.** Bidirectional replication means write conflicts (Chapter 04 §4.8). Common resolutions: partition by region (EU users write to EU only), use a globally consistent database (Spanner/CockroachDB, paying the latency), or design data types that merge (CRDTs).

### Choosing

```
What is the business cost of N hours of downtime?
├── Trivial          → Backup & Restore
├── Meaningful       → Pilot Light          ← most systems land here
├── Severe           → Warm Standby
└── Catastrophic, or regulator-mandated → Active-Active
```

> **Be sceptical of jumping to active-active.** It multiplies your cost and complexity permanently. Most businesses survive a rare 2-hour regional outage far more comfortably than they survive the ongoing engineering drag of a globally consistent architecture.

---

## 19.5 Backups 🟢

### The 3-2-1 rule (and its modern extension)

```
3 copies of the data
2 different media/storage types
1 copy off-site (different region or provider)
──────────────────────────────────────────────
+1 copy IMMUTABLE / air-gapped     ← the ransomware answer
+0 errors verified by testing      ← the part everyone skips
```

**Why immutability matters now:** modern ransomware specifically hunts and encrypts backups first. Object Lock / WORM storage means even an attacker with full admin credentials **cannot** delete or modify the backup within the retention period. This is one of the highest-value, lowest-effort controls available today.

### Backup types

| Type | What it stores | Restore | Trade-off |
|------|---------------|---------|-----------|
| **Full** | Everything | Fast, one step | Large, slow to take |
| **Incremental** | Changes since the last backup of any type | Slow — needs the full + **every** increment | Small; one missing increment breaks the chain |
| **Differential** | Changes since the last **full** | Full + one differential | Middle ground |
| **Continuous / PITR** ⭐ | Base + transaction log | **Any point in time** | Best RPO; more complex |

**Point-in-time recovery is the one that matters** for databases (Chapter 09). "Restore to 14:19, just before the bad migration at 14:20" is exactly the capability you want during a real incident.

### The rules that actually matter

```
1. AUTOMATE      A manual backup is a backup that stops happening in month three
2. VERIFY        Check the backup completed AND is readable — a 0-byte file "succeeds"
3. TEST RESTORE  ⭐ Quarterly, timed, documented. This is the only real proof.
4. OFF-SITE      Different region minimum; different provider or account for critical data
5. IMMUTABLE     Object Lock so ransomware cannot destroy it
6. ENCRYPT       At rest and in transit; keys stored SEPARATELY from the backup
7. RETAIN        By policy: daily 30d, weekly 12w, monthly 12m, yearly 7y
8. DOCUMENT      A restore runbook someone who did not build it can follow
9. MONITOR       Alert on backup failure AND on backup age
10. SEPARATE ACCESS  Backup deletion should require different credentials from production
```

> **The line to remember: "A backup you have never restored is not a backup — it is a hope."**
>
> The typical discovery during a first restore drill: the documented 1-hour restore actually takes 9 hours, the runbook references a person who left, and nobody has the decryption key. **Far better to learn that on a Tuesday afternoon than during a real outage.**

### The restore drill

```
1. Schedule it. Quarterly. Put it in the calendar as a real commitment.
2. Pick a random recent backup — not a specially prepared one.
3. Restore to an ISOLATED environment.
4. TIME IT. Record the actual RTO, not the theoretical one.
5. VERIFY the data: row counts, checksums, a business-level sanity check.
6. Have someone who did NOT write the runbook perform it.
7. Write down everything that went wrong. Fix the runbook. Fix the automation.
```

Step 6 is the one that finds the real gaps.

---

## 19.6 Failure detection and failover 🟢

### Health checks

```
Shallow:  "Is the process responding?"    → fast, cheap, few false negatives
Deep:     "Can it reach the DB, cache, and vendor?" → catches real problems,
                                                      but risks cascading failure
```

(Chapter 15 §15.7 covers the probe disasters. The same lesson applies here: a health check that depends on a shared dependency will mark the entire fleet unhealthy simultaneously.)

**Synthetic monitoring** is the outside-in complement: a scripted user journey run every minute from outside your infrastructure. It catches what internal health checks cannot — a DNS failure, an expired certificate, a broken CDN configuration, or a whole-region problem. Every critical journey should have one.

### Failover mechanics

```
1. DETECT     health checks fail for N consecutive intervals
2. DECIDE     is this real, or a network blip? (quorum, Chapter 05)
3. PROMOTE    a standby becomes primary (fence the old one first!)
4. REDIRECT   DNS / load balancer / connection string
5. VERIFY     is the new primary actually serving correctly?
```

**Failover dangers — each has bitten real systems:**

| Danger | Consequence | Mitigation |
|--------|-------------|-----------|
| **Split brain** | Two primaries accept writes; data diverges irreparably | Quorum, fencing tokens, STONITH (Chapter 05) |
| **Flapping** | Repeated failover/failback under an intermittent fault | Hysteresis; require N consecutive failures; cooldowns |
| **Cold standby** | The standby cannot handle the load or has drifted | Keep it warm; test it; verify capacity |
| **DNS caching** | Clients keep using the dead primary | Low TTLs prepared in advance; prefer Anycast/load-balancer failover |
| **Failback surprise** | Automatic failback while the primary is still unstable | **Make failback manual and deliberate** |
| **Data loss on promotion** | Async replica was behind; unreplicated writes are gone | Know your replication lag; decide the policy *before* the incident |

> **A decision you must make in advance, not at 3 AM:** if your async replica is 40 seconds behind, do you promote it (losing 40 seconds of data) or wait for the primary to recover (extending downtime)? **This is an RPO/RTO trade-off and it is a business decision.** Write it down in the runbook.

---

## 19.7 Chaos engineering 🟡

**The idea:** deliberately inject failure in a controlled way, to find weaknesses before they find you.

**The premise:** your system already has these weaknesses. The only question is whether you discover them on a Tuesday afternoon with everyone available, or at 3 AM on a holiday.

### The method

```
1. DEFINE STEADY STATE     a measurable normal (e.g. verifications/min, p99 latency)
2. HYPOTHESISE             "If one AZ fails, throughput stays within 5%"
3. LIMIT BLAST RADIUS      start in staging; then 1% of production traffic
4. INJECT THE FAILURE      kill instances, add latency, drop packets, fill a disk
5. OBSERVE                 did steady state hold? Did alerts fire? Did anyone notice?
6. FIX WHAT BROKE          then repeat
```

**Experiments worth running, roughly in order:**

| Experiment | What it reveals |
|------------|----------------|
| Kill a random pod | Do retries and load balancing work? |
| Kill an entire AZ | Is capacity really N+1? Do the health checks behave? |
| Add 500 ms latency to a dependency | Do timeouts and circuit breakers trigger correctly? |
| Make a dependency return errors | Does the fallback path work? Has anyone ever run it? |
| **Flush the cache** | Can the system survive a cold start? (Chapter 11 — most cannot) |
| Fill a disk | Do you alert before it is fatal? |
| Expire a certificate in staging | Does anything actually detect it? |
| Fail over the database | Does the application reconnect? What is the real RTO? |
| Saturate the CPU on one node | Does load shedding work? |

> **Start with a "game day", not automated chaos.** Gather the team for two hours, announce the experiment, run it in staging, and watch what happens. The value is as much in *what the team learns about the system* as in the finding itself. Automated continuous chaos (Chaos Monkey style) is the mature end state, not the starting point.

**The prerequisites:** good observability (Chapter 18), a tested rollback (Chapter 16), and management buy-in. Running chaos experiments without observability just creates outages you cannot explain.

---

## 19.8 Incident management 🟢

### Roles during an incident

| Role | Responsibility |
|------|---------------|
| **Incident Commander** | Coordinates. **Does not debug.** Makes decisions, tracks actions. |
| **Operations lead** | Actually investigates and changes things |
| **Communications lead** | Updates the status page, customers, internal stakeholders |
| **Scribe** | Timestamps every observation, action and decision |

> **The single most valuable practice: the Incident Commander must not be the person typing.** When the best engineer is head-down in a terminal, nobody is thinking about the customer communication, the escalation, or whether a completely different hypothesis is worth testing. Separating coordination from investigation reliably shortens incidents.

### The flow

```
1. DETECT       alert, or a customer report
2. TRIAGE       severity? user impact? who is needed?
3. COMMUNICATE  status page + internal channel, within minutes. Even "we are investigating."
4. MITIGATE     ⭐ STOP THE BLEEDING FIRST. Root cause comes later.
5. RESOLVE      confirm recovery, monitor for recurrence
6. POSTMORTEM   blameless, within 5 working days
```

**Step 4 is where teams lose the most time.** The instinct is to understand the problem before acting. The correct order is: **mitigate, then understand.** Roll back. Flip the feature flag. Fail over. Shed load. You can investigate a healthy system at leisure; you cannot investigate calmly while customers are down.

### Runbooks

Every alert links to one. A good runbook contains:

```
# Runbook: verification-api high error rate

## Impact
Users cannot complete verification. Revenue-affecting. Customer-visible.

## Quick checks (in order)
1. Dashboard: <link> — which endpoint, which tenant, which status code?
2. Recent deploys: <link> — anything in the last hour?
3. Vendor status: <link>
4. Traces filtered to errors: <link>

## Common causes and mitigations
| Symptom | Likely cause | Mitigation |
|---------|-------------|------------|
| 504s on /verify, vendor span slow | Vendor degraded | Enable flag `vendor_fallback_manual_review` |
| 500s right after a deploy | Bad release | `./deploy rollback verification-api` (~3 min) |
| 429s | Quota exhausted | Raise the tenant limit: <link> |

## Escalation
Primary: #team-verification · Secondary: <name> · Vendor support: <contact, account #>

## Verification that it is fixed
Error rate < 0.5% for 10 minutes on <dashboard link>
```

> **Write runbooks for the tired, frightened version of yourself at 3 AM.** Short, specific, with links and exact commands. Prose explaining the architecture belongs elsewhere.

### Blameless postmortems 🟢

**The principle:** people do not cause incidents. **Systems that allow a single human action to cause an incident cause incidents.**

If someone ran a bad migration in production, the finding is not "Sarah was careless." It is: *why was it possible to run an unreviewed destructive migration directly against production?* That question produces a fix. Blame produces silence — and the next incident is hidden rather than reported.

**Postmortem structure:**

```
1. SUMMARY          What happened, impact, duration, in three sentences
2. TIMELINE         Timestamped: detection, actions, decisions, resolution
3. IMPACT           Users affected, requests failed, revenue, SLO budget consumed
4. ROOT CAUSE       Usually several contributing factors, not one
5. WHAT WENT WELL   ⭐ Not optional — reinforce what worked
6. WHAT WENT BADLY  Honestly
7. ACTION ITEMS     Each with an OWNER and a DUE DATE, tracked like any other work
8. LESSONS          What we now understand differently
```

**The metrics to track over time:**
- **MTTD** (mean time to detect) — improved by better alerting
- **MTTA** (mean time to acknowledge) — improved by on-call process
- **MTTR** (mean time to recover) — improved by rollback capability and runbooks
- **Change failure rate** — improved by testing and review (Chapter 16)

> **Action items without owners and due dates do not happen.** The most common postmortem failure is a beautiful document with twelve improvements, none of which are ever done. Cap it at three real actions and actually finish them.

---

## 19.9 Designing for reliability — the architect's decisions

Everything in Chapter 05's reliability patterns applies. At the architecture level, these are the choices that matter most:

| Decision | Reliability impact |
|----------|-------------------|
| **Stateless services** | Any instance can die with no user impact (Chapter 04) |
| **Async where possible** | A down consumer means a queue, not a failed request (Chapter 06) |
| **Bounded blast radius** | Cell-based or per-tenant isolation: one tenant's problem affects one cell |
| **Graceful degradation defined per feature** | Partial service beats no service (Chapter 05) |
| **The critical path identified and protected** | Know the minimum set of components needed to complete the core transaction |
| **No shared single points of failure** | One shared cache/queue/database that everything needs is a system-wide risk |
| **Idempotency everywhere** | Makes retry and replay safe (Chapter 05) |
| **Everything reproducible from code** | Your DR plan is `terraform apply` (Chapter 16) |

### Identify the critical path explicitly

```
For the liveness SaaS, the minimum viable transaction is:
  API receives request → job queued → worker processes → result stored → response

Components on the critical path:  API, queue, workers, database, object storage
NOT on the critical path:         analytics, webhooks, email, the admin console,
                                  the reporting warehouse

→ The critical path gets multi-AZ, tighter SLOs, more capacity headroom,
  and the most attention.
→ Everything else may degrade or queue without blocking a verification.
```

> **Writing this down is one of the most valuable half-hours an architect can spend.** It tells you where to spend your reliability budget, and it tells the on-call engineer what may safely be sacrificed during an incident.

### Cell-based architecture ⚪🟡

Instead of one large system serving all tenants, run several complete, independent "cells", each serving a subset.

```
Cell 1 → tenants A–F     (full stack: API, DB, cache, workers)
Cell 2 → tenants G–M     (full stack)
Cell 3 → tenants N–Z     (full stack)
```

**The benefit: the blast radius of almost any failure is one cell.** A bad deploy, a poison message, a runaway query or a hot tenant affects a third of customers, not all of them. It also gives you a natural canary: deploy to one cell first.

The cost is operational multiplicity and routing complexity. It is how AWS and other large providers limit blast radius, and it becomes worth considering when a single-cell failure would be commercially unacceptable.

---

## 19.10 Common mistakes

1. **Confusing HA with DR** — replication does not protect against `DELETE FROM orders`
2. **Never testing a restore** — discovering the backup is broken during the disaster
3. **No RTO/RPO numbers** — so every reliability investment is a guess
4. **The same RTO/RPO for everything** — over-paying and under-protecting simultaneously
5. **Untested standby** — it has drifted, its certificates expired, and it cannot take the load
6. **Capacity that cannot survive one AZ loss** — 2 servers per AZ across 3 AZs when you need 6
7. **Backups in the same account or region as production** — ransomware and account compromise take both
8. **No immutable backup copy** — modern ransomware targets backups first
9. **Automatic failback** — flapping between an unstable primary and a standby
10. **Deep health checks causing cascading failure** — one dependency blip restarts everything
11. **No runbooks** — every incident starts from scratch
12. **The Incident Commander also debugging** — nobody is coordinating or communicating
13. **Blameful postmortems** — people stop reporting problems, and you lose your early warning system
14. **Action items with no owner** — the same incident happens again in six months
15. **Investigating before mitigating** — customers stay down while you build understanding

---

## 19.11 Architect's checklist

**Requirements**
- [ ] RTO and RPO defined **per system**, agreed with the business, written down
- [ ] The critical path identified; non-critical components listed as degradable
- [ ] Availability target set as an SLO with an error budget (Chapter 18)

**Redundancy**
- [ ] Multi-AZ for everything on the critical path
- [ ] Capacity sized so one AZ can be lost with no degradation
- [ ] No single points of failure on the critical path
- [ ] DR pattern chosen and justified against the cost of downtime

**Backups**
- [ ] Automated, monitored, and alerted on failure **and** on age
- [ ] 3-2-1 plus an immutable copy (Object Lock)
- [ ] Stored in a separate account/region; deletion requires separate credentials
- [ ] Encrypted, with keys stored separately
- [ ] Point-in-time recovery available for databases
- [ ] **Restore drill performed quarterly, timed, by someone who did not write the runbook**
- [ ] Measured RTO compared against the target, and the gap addressed

**Failure handling**
- [ ] Health checks shallow for liveness, dependency-aware for readiness
- [ ] Synthetic monitoring of critical journeys from outside the infrastructure
- [ ] Failover tested; split-brain prevention verified; failback is manual
- [ ] The "promote a lagging replica or wait?" decision made and documented in advance
- [ ] Graceful degradation defined per non-critical dependency

**Operations**
- [ ] Runbooks for every alert, written for 3 AM
- [ ] Incident roles defined; Incident Commander separate from the investigator
- [ ] Status page and communication templates ready before they are needed
- [ ] Blameless postmortems within 5 days, with owned and dated actions
- [ ] MTTD / MTTR tracked and trending
- [ ] At least one chaos game day run in the last 6 months

---

## 19.12 Self-test

1. HA vs DR — give the distinction and the classic failure that proves replication is not a backup.
2. Draw RTO and RPO on a timeline. Which measures backwards?
3. How do you get honest RTO/RPO numbers out of a business stakeholder?
4. Why should different systems in one company have different RTO/RPO?
5. You need 6 servers of capacity across 3 AZs and must survive losing one AZ with no degradation. How many do you run, and why?
6. Name the four DR patterns with their approximate RTO, RPO and relative cost.
7. Why is Pilot Light usually the best value? What is the asymmetry it exploits?
8. State 3-2-1 and its two modern additions. Why does immutability matter now?
9. Why is "a backup you have never restored" not a backup? What does a drill typically reveal?
10. Name six dangers during failover and a mitigation for each.
11. Your async replica is 40 seconds behind and the primary is down. What do you do, and when should that decision be made?
12. What is chaos engineering's premise? List five experiments worth running.
13. Why must the Incident Commander not be the person debugging?
14. Why must postmortems be blameless? Rewrite "Sarah ran a bad migration" as a systemic finding.
15. What is cell-based architecture and what does it buy you?

---

## 19.13 Key takeaways

- **Failure is guaranteed. Design for survivability, not prevention.**
- **RTO and RPO are the two numbers** — define them per system, with the business, in writing
- **HA ≠ DR.** Replication propagates your mistakes perfectly. Only backups protect against logical failure.
- **Capacity must survive an AZ loss without degradation** — with 3 AZs that means 1.5× the minimum
- **Pilot Light is usually the best value**: data replicates continuously, compute starts on demand
- **3-2-1 plus immutable plus verified.** Ransomware hunts backups first.
- **A backup you have never restored is a hope.** Drill quarterly, time it, use someone unfamiliar.
- **An untested standby usually does not work** — this is the strongest argument for active-active
- **Make failback manual.** Automatic failback causes flapping.
- **Mitigate first, understand later.** Rollback, flag, fail over, shed load.
- **Separate the Incident Commander from the investigator**
- **Blameless postmortems with owned, dated actions** — blame destroys your early warning system
- **Identify and protect the critical path**; let everything else degrade

---

**Next:** [Chapter 20 — Performance Engineering](20-performance-engineering.md)
