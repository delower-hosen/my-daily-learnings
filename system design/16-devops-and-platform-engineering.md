# Chapter 16 — DevOps & Platform Engineering 🟡

> DevOps is not a job title or a set of tools. It is the removal of the wall between "people who build" and "people who run".
>
> For an architect, the important insight is this: **your deployment pipeline is part of your architecture.** A design that cannot be deployed safely, frequently and reversibly is a bad design, however elegant the diagram.

---

## 16.1 Why this is an architecture chapter

An architecture that requires a four-hour coordinated release every second Thursday is *structurally* different from one that ships 30 times a day — even if the boxes look identical.

**Deployability is a quality attribute** (Chapter 00), and it is determined by architectural choices:

| Architecture choice | Deployment consequence |
|--------------------|------------------------|
| Shared database between services | Services must deploy together — the distributed monolith |
| Breaking API changes | Coordinated client + server releases |
| No backward-compatible migrations | Downtime windows, or no rollback |
| Stateful app servers | Deploys drop user sessions |
| No feature flags | Every release is all-or-nothing |
| No automated tests | Manual regression, so releases are rare and scary |

> **Rare releases are not caused by process. They are caused by fear. Fear is caused by an inability to verify and to reverse.** Fix those two and frequency follows.

### The DORA metrics 🟢

Years of research (the *Accelerate* / DORA studies) reduced delivery performance to four measurable numbers. Learn them — they are the vocabulary executives increasingly use.

| Metric | Elite | Low | What it really measures |
|--------|-------|-----|------------------------|
| **Deployment frequency** | On demand (multiple/day) | Monthly–6-monthly | Batch size, and confidence |
| **Lead time for change** | < 1 hour | 1–6 months | Pipeline efficiency |
| **Change failure rate** | 0–15% | 40–60% | Quality of testing and review |
| **Failed deployment recovery time** | < 1 hour | 1 week–1 month | Rollback and observability capability |

**The counter-intuitive finding, repeatedly confirmed:** speed and stability are **not** a trade-off. Teams that deploy more often have *lower* failure rates — because small changes are easier to review, easier to diagnose, and easier to reverse.

> If someone proposes *"we should deploy less often to be safer"*, you now have the evidence to disagree politely: the opposite is true. A fifth metric, **reliability** (how well you meet your SLOs), was added later and completes the picture.

---

## 16.2 CI/CD 🟢

### Continuous Integration

**Definition:** every developer merges to the main branch at least daily, and every merge is automatically built and tested.

The point is not the tooling — it is **small batches**. Integration pain grows super-linearly with the size of the change.

```yaml
# A realistic CI pipeline — note the ordering: fast feedback first
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint + format + type check      # seconds — fail fast
        run: |
          ruff check .
          ruff format --check .
          mypy app/
      - name: Unit tests                      # < 2 minutes
        run: pytest tests/unit -x --cov=app --cov-fail-under=80
      - name: Architecture fitness functions  # Chapter 00
        run: lint-imports                     # domain must not import infrastructure
      - name: Secret scan
        run: gitleaks detect --no-git -v

  integration:
    needs: quality
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_PASSWORD: test } }
      redis:    { image: redis:7 }
    steps:
      - uses: actions/checkout@v4
      - run: alembic upgrade head
      - run: pytest tests/integration
      - name: API contract check              # Chapter 08
        run: oasdiff breaking main-spec.yaml openapi.yaml --fail-on ERR

  build:
    needs: integration
    permissions: { id-token: write, contents: read }   # OIDC — no stored cloud keys
    steps:
      - name: Build image
        run: docker build -t $IMAGE:${{ github.sha }} .
      - name: Scan image
        run: trivy image --exit-code 1 --severity CRITICAL $IMAGE:${{ github.sha }}
      - name: Generate SBOM
        run: syft $IMAGE:${{ github.sha }} -o spdx-json > sbom.json
      - name: Sign image
        run: cosign sign --yes $IMAGE:${{ github.sha }}
      - name: Push
        run: docker push $IMAGE:${{ github.sha }}
```

**CI pipeline design rules:**

1. **Fast feedback first.** Lint (5 s) → unit (2 min) → integration (10 min) → e2e (30 min). Developers must learn about a typo in seconds, not after 40 minutes.
2. **Keep the whole pipeline under ~10 minutes** to the point where a developer can merge. Past that, people context-switch and the feedback loop breaks.
3. **The build must be reproducible** — pinned dependencies, pinned base images, no `latest`.
4. **A red main branch is an emergency.** Stop and fix; do not build on a broken base.
5. **Flaky tests must be quarantined immediately.** A test that fails randomly trains the team to ignore failures, which destroys the entire value of CI.

### Continuous Delivery vs Continuous Deployment

```
Continuous DELIVERY:   every change is automatically proven releasable.
                       A human decides WHEN to press the button.

Continuous DEPLOYMENT: every change that passes the pipeline goes to production
                       automatically. No human gate.
```

Continuous Delivery is the right goal for nearly everyone. Continuous Deployment requires very strong automated testing, feature flags, progressive delivery and fast rollback — and it is a wonderful place to end up, but you earn it.

### Build once, promote everywhere ⭐

```
        ┌──────────────┐
        │  BUILD ONCE  │  → artefact: image@sha256:abc123
        └──────┬───────┘
               │  the SAME artefact, configuration injected per environment
     ┌─────────┼─────────┬──────────┐
     ▼         ▼         ▼          ▼
   [dev]    [staging]  [canary]  [production]
```

> **Never rebuild per environment.** If staging and production contain different binaries, staging proves nothing. Configuration varies by environment; the artefact must not.

---

## 16.3 Infrastructure as Code 🟢

**The problem it solves:** clicking in a cloud console is unrepeatable, unreviewable, undocumented, and impossible to recreate after a disaster.

```hcl
# Terraform — declarative desired state
resource "aws_db_instance" "primary" {
  identifier     = "verification-${var.environment}"
  engine         = "postgres"
  engine_version = "16.3"
  instance_class = var.environment == "production" ? "db.r6g.xlarge" : "db.t4g.medium"

  allocated_storage     = 100
  max_allocated_storage = 1000              # storage autoscaling
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.db.arn

  multi_az                = var.environment == "production"
  backup_retention_period = var.environment == "production" ? 30 : 7
  deletion_protection     = var.environment == "production"

  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false            # ← reviewable in a pull request

  performance_insights_enabled = true
  monitoring_interval          = 60

  tags = local.common_tags
}
```

**What IaC gives you beyond automation:**

| Benefit | Why it matters |
|---------|---------------|
| **Reviewable** | `publicly_accessible = true` gets caught in a PR, not in a breach report |
| **Reproducible** | Rebuild the whole environment from scratch — this *is* your disaster recovery |
| **Auditable** | Git history answers "who opened that port, when, and why" |
| **Documented** | The code is the documentation, and it cannot drift from reality |
| **Testable** | Policy-as-code (OPA, Checkov, tfsec) fails the build on insecure configuration |
| **Consistent** | Dev, staging and production differ only where you intended |

### Declarative vs imperative

| | Declarative (Terraform, CloudFormation, Kubernetes) | Imperative (scripts, CLI, Ansible playbooks) |
|---|---|---|
| You describe | The desired end state | The steps to get there |
| Re-running | Safe — converges to the same state | Often unsafe or duplicative |
| Drift detection | Built in (`plan` shows differences) | None |
| Ordering | Inferred from dependencies | You manage it |

> Prefer declarative. Use imperative tooling (Ansible, scripts) for configuration *inside* machines, or for one-off operational tasks.

### IaC discipline

1. **Remote state with locking** (S3 + DynamoDB, Terraform Cloud). Local state files are how teams overwrite each other's infrastructure.
2. **Separate state per environment.** A `terraform apply` in dev must be incapable of touching production.
3. **Never modify production by hand.** Manual changes cause drift; the next `apply` reverts them, often at the worst time. If you must break glass in an incident, **create a ticket to codify it the same week.**
4. **Plan in the PR, apply on merge.** The `plan` output is the review artefact.
5. **Modules for repeated patterns**, versioned and tested.
6. **Policy as code** — automatically reject unencrypted storage, public databases, missing tags.
7. **Secrets never in state files** — Terraform state contains resource attributes in plaintext; treat the state bucket as a secret store and encrypt it.

### GitOps 🟡

**Git is the single source of truth for desired state; an in-cluster agent continuously reconciles reality to match it.**

```
Developer ──PR──► Git repo (manifests) ──► ArgoCD / Flux (in the cluster)
                                                  │
                                       continuously reconciles
                                                  ▼
                                            Kubernetes
```

| Push-based CI/CD | GitOps (pull-based) |
|---|---|
| CI has production credentials | **Cluster credentials never leave the cluster** |
| State drift is invisible | Drift is detected and auto-corrected |
| Rollback = re-run a pipeline | **Rollback = `git revert`** |
| "What is deployed?" = check the pipeline logs | "What is deployed?" = read the repo |

> The security argument is the strongest one: with GitOps your CI system does not need cluster admin credentials, which removes a very attractive attack target. Combined with Kubernetes' reconciliation model (Chapter 15), it is a natural fit.

---

## 16.4 Environments, configuration and secrets 🟢

### Environment strategy

```
LOCAL       developer machine; containers or mocks for dependencies
DEV         integration; auto-deploy on merge; disposable
STAGING     production-like: same topology, same IaC, realistic (anonymised) data
PRODUCTION  the real thing
```

**Staging is only useful if it is genuinely production-like.** A staging environment with one instance, a different database version and 200 rows of test data proves nothing. If you cannot afford a production-like staging environment, be honest about it and invest instead in **progressive delivery in production** (canary, feature flags, good observability) — which is often the better investment anyway.

**Ephemeral preview environments** (one per pull request, torn down on merge) are one of the highest-value things a platform can offer: reviewers click a link instead of pulling a branch.

### The Twelve-Factor rules that still matter 🟢

Of the original twelve, these are the ones that genuinely shape architecture:

| Factor | Rule | Why |
|--------|------|-----|
| **III. Config** | **Config in the environment, never in code** | The same artefact runs everywhere |
| **IV. Backing services** | Treat databases/queues as attached resources, addressed by URL | Swap a local Postgres for RDS by changing config only |
| **VI. Processes** | **Stateless and share-nothing** | The foundation of horizontal scaling (Chapter 04) |
| **IX. Disposability** | Fast startup, **graceful shutdown** | Enables autoscaling and zero-downtime deploys (Chapter 15) |
| **X. Dev/prod parity** | Keep environments as similar as possible | Bugs found in staging, not production |
| **XI. Logs** | **Write to stdout as a stream** — do not manage log files | The platform handles collection and routing |

### Configuration

```python
# Typed, validated configuration that fails fast at startup
class Settings(BaseSettings):
    database_url: PostgresDsn
    redis_url: RedisDsn
    vendor_api_timeout_ms: int = Field(default=8000, ge=100, le=30000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()      # raises at STARTUP if config is invalid
```

> **Fail fast on bad configuration.** A service that starts happily with a missing setting and then fails on the first request at 2 AM is far worse than one that refuses to start in the deployment pipeline. Validate everything at boot.

**Configuration precedence:** defaults in code → environment-specific file → environment variables → runtime overrides (feature flags). Make the precedence explicit and documented.

### Secrets — the rules 🟢

```
❌ In source control (even in a private repo — it is permanent in git history)
❌ In container images
❌ In CI logs (mask them, and verify the masking works)
⚠️ In environment variables (workable, but visible in process listings and crash dumps)
✅ In a secrets manager, injected at runtime
✅ Better: no static secret at all — workload identity, short-lived tokens
```

**Rotation:** a secret that has never been rotated is a secret you cannot rotate. Practise it. Prefer credentials that rotate automatically (IAM database auth, cloud-managed rotation).

**If a secret leaks:** rotate first, investigate second. Removing it from git history does **not** make it safe — assume it is compromised the moment it is pushed.

---

## 16.5 Database migrations in a pipeline 🟢

**This is where most "we can't roll back" situations are created.**

### The rules

1. **Migrations run separately from application deploys**, before the new code (for additive changes) or after (for removals)
2. **Every migration must be backward compatible** with the currently-running version — because during a rolling deploy, both versions run simultaneously (Chapter 15)
3. **Never write a destructive migration in the same release as the code change** — use expand/contract (Chapter 09)
4. **Forward-only in production.** "Down" migrations are a comforting fiction: they usually cannot restore dropped data. **Roll forward with a fix.**
5. **Test migrations against a production-sized copy** — a migration that takes 4 ms on 1,000 rows can take 40 minutes and lock a table on 50 million
6. **Short `lock_timeout` with retries** so a migration fails fast rather than freezing the application

```python
# Expand/contract across four releases (Chapter 09), as pipeline steps
# Release 1: ADD the new column (nullable). Code writes BOTH, reads OLD.
# Release 2: BACKFILL in batches (a job, not a migration).
# Release 3: Code reads NEW, still writes both.
# Release 4: Code uses NEW only. THEN drop the old column.
```

Each release is independently deployable and independently reversible. This is what makes zero-downtime possible.

---

## 16.6 Progressive delivery and rollback 🟢

(Strategies are in Chapter 15 §15.9. Here is the pipeline and operational view.)

### Rollback must be boring

> **You should be able to roll back in under 5 minutes, at 3 AM, by someone who did not write the change.**

Which means:
- [ ] A documented, practised, one-command procedure
- [ ] Previous artefacts retained and immediately deployable
- [ ] Database changes are backward compatible, so rolling back the code is safe
- [ ] Feature flags can disable a feature **without** a deploy — the fastest "rollback" available
- [ ] **You have actually practised it** — a rollback procedure nobody has run is a theory

**Automate the decision where you can:**

```yaml
# Roll back automatically if error rate exceeds the threshold during a canary
analysis:
  templates: [{ templateName: error-rate }]
  args: [{ name: service, value: verification-api }]
# error-rate template: fail if rate(http_requests_total{code=~"5.."}) > 0.02 over 5m
```

### Release checklist for anything significant

- [ ] Backward-compatible API and schema changes
- [ ] Feature flag in place, default off
- [ ] Dashboards and alerts ready **before** the deploy
- [ ] Rollback procedure verified and the artefact retained
- [ ] Deploy during business hours where possible (the people who can fix it are awake)
- [ ] A named owner watching for the first 30 minutes
- [ ] Communication plan if customers are affected

> **"Deploy on Friday afternoon" is not a technical question, it is a question about whether you can safely reverse.** Teams with fast, boring rollback deploy on Fridays without anxiety. Teams without it should not deploy on Tuesdays either.

---

## 16.7 Platform Engineering 🟡

### The problem it solves

Give a product team full ownership of infrastructure and one of two things happens:

1. Every team solves the same problems differently — six CI patterns, four logging formats, three ways to deploy — and nobody can move between teams
2. Or they cannot cope at all, and cognitive load destroys their delivery

**Platform engineering is the answer: build an internal product whose customers are your own developers.**

```
                ┌──────────────────────────────────────┐
                │  INTERNAL DEVELOPER PLATFORM         │
                │                                      │
                │  • Golden-path templates             │
                │  • Self-service environments         │
                │  • Standard CI/CD pipelines          │
                │  • Observability wired in by default │
                │  • Secrets, identity, networking     │
                │  • Guardrails (policy as code)       │
                └──────────────────────────────────────┘
                 used by ↓  ↓  ↓  ↓
        Team A    Team B    Team C    Team D
```

### The golden path ⭐

**The paved road: the easiest way to do something is also the correct way.**

```bash
$ platform new service --name billing-api --template python-fastapi

Created:
  ✓ Repository with the standard project layout
  ✓ CI pipeline (lint, test, scan, sign, build, deploy)
  ✓ Dockerfile (multi-stage, non-root, scanned)
  ✓ Kubernetes manifests (probes, resources, PDB, HPA)
  ✓ Observability: structured logging, metrics, tracing, dashboard
  ✓ Secrets integration and workload identity
  ✓ Staging environment
  ✓ On-call runbook stub and ownership metadata
```

> **This is the single highest-leverage thing an architect can build.** Architecture decisions embedded in a template are actually followed. Architecture decisions written in a document are read once and forgotten.

**The crucial principle: the golden path must be optional but overwhelmingly attractive.** Mandating it creates resentment and shadow infrastructure. Making it genuinely the fastest route means teams choose it — and you get consistency by consent.

### Platform as a product

| Product discipline | Applied to the platform |
|-------------------|------------------------|
| Know your users | Talk to developers; watch them work |
| Measure adoption | How many teams use the golden path? |
| Measure satisfaction | Developer surveys; where does friction remain? |
| Roadmap and versioning | Platform changes are releases with notes |
| Support and docs | A real support channel, not "read the wiki" |
| **Do not force adoption** | If teams route around you, your product is bad |

**The metrics that matter:** time from `git init` to production for a new service (target: hours, not weeks); time for a new engineer's first production change (target: under a week); percentage of services on the golden path.

### When you need a platform team

| Engineers | Approach |
|-----------|----------|
| < 20 | No platform team. A shared template repo and a few conventions. |
| 20–60 | One or two people part-time; standardise CI/CD and observability |
| 60+ | A dedicated platform team, treated as a product team |

> **Do not build a platform before you have the pain.** A platform team at 15 engineers is 2 people not building the product, solving problems you do not have yet.

---

## 16.8 Feature flags 🟡

```python
if await flags.enabled("new-scoring-model", context={"tenant": tid, "user": uid}):
    ...
```

**Four distinct uses — they have different lifecycles and should be named differently:**

| Type | Purpose | Lifetime |
|------|---------|----------|
| **Release toggle** | Deploy dark, enable later | Days–weeks. **Delete after release.** |
| **Experiment** | A/B test | The experiment's duration |
| **Ops toggle** | Kill switch for an expensive feature under load | Long-lived, deliberately |
| **Permission toggle** | Entitlement per plan/tenant | Permanent (this is really configuration) |

### Flag debt is real

Every flag doubles the theoretical number of code paths. Ten flags = 1,024 combinations you cannot test.

```
Rules:
  ✅ Every release toggle gets an expiry date and an owner at creation
  ✅ CI warns on flags older than 90 days
  ✅ Removing a flag is part of the feature's definition of done
  ✅ Only ops toggles and entitlements are allowed to be permanent
  ✅ Default must be the SAFE value (usually off)
```

> **The payoff justifies the discipline:** decoupling deploy from release means you can ship continuously and turn features on for one tenant, then 5%, then everyone — and turn them off in one second without a deploy. That is the fastest incident mitigation available.

---

## 16.9 Common mistakes

1. **Deploy pipeline not treated as part of the architecture** — a design that cannot ship safely is not done
2. **Rebuilding artefacts per environment** — staging then proves nothing
3. **Slow CI (> 20 minutes)** — developers stop running it and batch their changes
4. **Tolerating flaky tests** — the team learns to ignore red builds, destroying CI's value
5. **Manual changes to production infrastructure** — drift, then a surprise revert on the next apply
6. **Terraform state without locking, or shared across environments**
7. **Secrets in git, images, or CI logs**
8. **Destructive migrations shipped with code changes** — rollback becomes impossible
9. **Untested rollback procedure** — discovered to be broken during an incident
10. **Staging that is nothing like production** — false confidence
11. **Feature flags with no expiry** — 200 flags, exponential untested paths
12. **Building a platform team too early** — solving problems you do not yet have
13. **Mandating the golden path** — teams route around it and you get shadow infrastructure
14. **Optimising deployment frequency without reducing failure rate** — shipping bugs faster is not progress

---

## 16.10 Architect's checklist

- [ ] DORA metrics measured and visible; trend reviewed quarterly
- [ ] CI under 10 minutes to merge-ready; fast checks first
- [ ] Build once, promote the same artefact through every environment
- [ ] Architecture fitness functions run in CI (Chapter 00)
- [ ] API contract breaking-change detection in CI (Chapter 08)
- [ ] Image scanning, SBOM, and signing in the pipeline; CRITICAL fails the build
- [ ] No long-lived cloud credentials in CI — OIDC federation
- [ ] All infrastructure defined as code; no manual production changes
- [ ] Remote, locked, encrypted state; separate per environment
- [ ] Policy-as-code rejecting insecure configurations automatically
- [ ] Secrets in a manager, injected at runtime, rotated, never logged
- [ ] Configuration validated at startup — fail fast
- [ ] Migrations backward compatible, expand/contract, tested at production scale
- [ ] Rollback documented, under 5 minutes, and **practised**
- [ ] Feature flags with owners, expiry dates, and safe defaults
- [ ] Ephemeral preview environments per pull request (if affordable)
- [ ] Golden-path template exists and encodes the architecture decisions
- [ ] Every service has a named owner and an on-call runbook

---

## 16.11 Self-test

1. Why is the deployment pipeline an architectural concern? Give three architecture choices that constrain it.
2. Name the four DORA metrics. What is the counter-intuitive finding about speed and stability?
3. Why must you build an artefact once and promote it, rather than rebuilding per environment?
4. What is the correct ordering of stages in a CI pipeline, and why?
5. Why is a flaky test worse than a missing test?
6. Continuous Delivery vs Continuous Deployment — what is the difference and which should most teams target?
7. What does IaC give you beyond automation? Name five things.
8. What is GitOps, and what is its strongest argument?
9. Why are "down" migrations mostly a fiction? What do you do instead?
10. Why must every migration be backward compatible with the currently-running code?
11. What makes a rollback "boring", and why does that matter more than the deploy process?
12. What is a golden path, and why must it be optional?
13. Name the four kinds of feature flag and their expected lifetimes.
14. When should a company create a platform team — and when is it too early?

---

## 16.12 Key takeaways

- **Your pipeline is part of your architecture.** A design that cannot be deployed safely and reversibly is incomplete.
- **Speed and stability go together** — small batches are safer, and DORA proved it
- **Build once, promote everywhere.** Different binaries per environment make testing meaningless.
- **CI under 10 minutes, fast checks first, zero tolerance for flaky tests**
- **Infrastructure as Code makes security reviewable** — `publicly_accessible = true` caught in a PR
- **No manual production changes.** Ever. Codify emergency fixes the same week.
- **Migrations are where rollback dies** — expand/contract, backward compatible, forward-only
- **Rollback must be boring, fast, and practised.** Feature flags are the fastest rollback of all.
- **The golden path is the highest-leverage architecture tool you have** — decisions in a template get followed; decisions in a document do not
- **Do not build a platform team before you feel the pain**

---

**Next:** [Chapter 17 — Security Architecture](17-security-architecture.md)
