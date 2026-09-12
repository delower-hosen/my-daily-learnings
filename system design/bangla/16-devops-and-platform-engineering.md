# অধ্যায় ১৬ — DevOps ও Platform Engineering 🟡

> DevOps কোনো পদবি বা টুলের সেট নয়। এটা "যাঁরা বানান" আর "যাঁরা চালান" — এদের মাঝের দেয়ালটা সরিয়ে ফেলা।
>
> একজন আর্কিটেক্টের জন্য গুরুত্বপূর্ণ অন্তর্দৃষ্টিটা হলো: **আপনার deployment pipeline আপনার architecture-এরই অংশ।** যে design নিরাপদে, ঘন ঘন আর ফেরানোর মতো করে deploy করা যায় না, সেটা একটা খারাপ design — diagram যতই মার্জিত হোক।

---

## ১৬.১ এটা কেন একটা architecture-এর অধ্যায়

যে architecture-এ প্রতি দ্বিতীয় বৃহস্পতিবার একটা চার ঘণ্টার সমন্বিত release লাগে, সেটা দিনে ৩০ বার ship করা architecture থেকে *কাঠামোগতভাবে* আলাদা — বাক্সগুলো দেখতে একরকম হলেও।

**Deployability একটা quality attribute** (অধ্যায় ০০), আর এটা architecture-এর পছন্দ দিয়েই নির্ধারিত হয়:

| Architecture-এর পছন্দ | Deployment-এর ফলাফল |
|--------------------|------------------------|
| Service গুলোর মধ্যে shared database | Service গুলোকে একসাথে deploy করতে হয় — distributed monolith |
| Breaking API পরিবর্তন | সমন্বিত client + server release |
| কোনো backward-compatible migration নেই | Downtime-এর জানালা, নয়তো কোনো rollback নেই |
| Stateful app server | Deploy ব্যবহারকারীর session ফেলে দেয় |
| কোনো feature flag নেই | প্রতিটা release সব-নয়তো-কিছুই-না |
| কোনো automated test নেই | Manual regression, তাই release বিরল আর ভীতিকর |

> **বিরল release-এর কারণ process নয়। কারণ ভয়। ভয়ের কারণ যাচাই করতে আর ফেরাতে না পারা।** ওই দুটো ঠিক করুন, ঘনত্ব আপনাআপনি আসবে।

### DORA metric 🟢

বছরের পর বছর গবেষণা (*Accelerate* / DORA গবেষণা) delivery-র performance-কে চারটা মাপা-যায় সংখ্যায় নামিয়ে এনেছে। এগুলো শিখুন — executive-রা ক্রমশ এই পরিভাষা ব্যবহার করছেন।

| Metric | Elite | Low | এটা আসলে কী মাপে |
|--------|-------|-----|------------------------|
| **Deployment frequency** | চাহিদামতো (দিনে একাধিক) | মাসে–৬ মাসে | Batch-এর আকার, আর আত্মবিশ্বাস |
| **Lead time for change** | < ১ ঘণ্টা | ১–৬ মাস | Pipeline-এর দক্ষতা |
| **Change failure rate** | ০–১৫% | ৪০–৬০% | Testing আর review-র মান |
| **Failed deployment recovery time** | < ১ ঘণ্টা | ১ সপ্তাহ–১ মাস | Rollback আর observability-র ক্ষমতা |

**বারবার নিশ্চিত হওয়া স্বজ্ঞাবিরোধী আবিষ্কারটা:** গতি আর স্থিতিশীলতা একটা trade-off **নয়**। যে টিম বেশি ঘন ঘন deploy করে তাদের ব্যর্থতার হার *কম* — কারণ ছোট পরিবর্তন review করা সহজ, নির্ণয় করা সহজ, আর ফেরানো সহজ।

> কেউ যদি প্রস্তাব করেন *"নিরাপদ থাকতে আমাদের কম ঘন ঘন deploy করা উচিত"*, তাহলে এখন আপনার কাছে ভদ্রভাবে দ্বিমত করার প্রমাণ আছে: উল্টোটাই সত্য। পরে একটা পঞ্চম metric, **reliability** (আপনি কতটা ভালোভাবে SLO মেটান), যোগ করা হয়েছে আর সেটা ছবিটা সম্পূর্ণ করে।

---

## ১৬.২ CI/CD 🟢

### Continuous Integration

**সংজ্ঞা:** প্রতিটা ডেভেলপার অন্তত দিনে একবার main branch-এ merge করেন, আর প্রতিটা merge স্বয়ংক্রিয়ভাবে build আর test হয়।

মূল কথাটা টুল নয় — **ছোট batch**। পরিবর্তনের আকারের সাথে integration-এর যন্ত্রণা অতি-রৈখিকভাবে বাড়ে।

```yaml
# একটা বাস্তবসম্মত CI pipeline — ক্রমটা খেয়াল করুন: আগে দ্রুত প্রতিক্রিয়া
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint + format + type check      # সেকেন্ড — দ্রুত fail করান
        run: |
          ruff check .
          ruff format --check .
          mypy app/
      - name: Unit test                       # < ২ মিনিট
        run: pytest tests/unit -x --cov=app --cov-fail-under=80
      - name: Architecture fitness function   # অধ্যায় ০০
        run: lint-imports                     # domain infrastructure import করতে পারবে না
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
      - name: API contract যাচাই              # অধ্যায় ০৮
        run: oasdiff breaking main-spec.yaml openapi.yaml --fail-on ERR

  build:
    needs: integration
    permissions: { id-token: write, contents: read }   # OIDC — কোনো জমানো ক্লাউড key নেই
    steps:
      - name: Image build
        run: docker build -t $IMAGE:${{ github.sha }} .
      - name: Image scan
        run: trivy image --exit-code 1 --severity CRITICAL $IMAGE:${{ github.sha }}
      - name: SBOM তৈরি
        run: syft $IMAGE:${{ github.sha }} -o spdx-json > sbom.json
      - name: Image sign
        run: cosign sign --yes $IMAGE:${{ github.sha }}
      - name: Push
        run: docker push $IMAGE:${{ github.sha }}
```

**CI pipeline design-এর নিয়ম:**

১. **আগে দ্রুত প্রতিক্রিয়া।** Lint (৫ সেকেন্ড) → unit (২ মিনিট) → integration (১০ মিনিট) → e2e (৩০ মিনিট)। ডেভেলপারদের একটা বানান-ভুলের কথা সেকেন্ডে জানতে হবে, ৪০ মিনিট পরে নয়।
২. একজন ডেভেলপার merge করতে পারেন — সেই বিন্দু পর্যন্ত **পুরো pipeline ~১০ মিনিটের নিচে রাখুন**। তার বেশি হলে মানুষ প্রসঙ্গ বদলায় আর প্রতিক্রিয়ার লুপ ভেঙে যায়।
৩. **Build পুনরুৎপাদনযোগ্য হতে হবে** — pin করা dependency, pin করা base image, কোনো `latest` নয়।
৪. **একটা লাল main branch একটা জরুরি অবস্থা।** থামুন আর ঠিক করুন; একটা ভাঙা ভিত্তির উপর বানাবেন না।
৫. **Flaky test সাথে সাথে আলাদা করুন।** যে test এলোমেলোভাবে fail করে, সেটা টিমকে ব্যর্থতা উপেক্ষা করতে শেখায়, যা CI-র পুরো মূল্যটাই ধ্বংস করে।

### Continuous Delivery বনাম Continuous Deployment

```
Continuous DELIVERY:   প্রতিটা পরিবর্তন স্বয়ংক্রিয়ভাবে release-যোগ্য প্রমাণিত হয়।
                       একজন মানুষ ঠিক করেন কখন বোতাম টিপবেন।

Continuous DEPLOYMENT: pipeline পার হওয়া প্রতিটা পরিবর্তন স্বয়ংক্রিয়ভাবে
                       production-এ যায়। কোনো মানবিক গেট নেই।
```

প্রায় সবার জন্য Continuous Delivery-ই সঠিক লক্ষ্য। Continuous Deployment-এ খুব শক্তিশালী automated testing, feature flag, progressive delivery আর দ্রুত rollback লাগে — আর সেখানে পৌঁছানো চমৎকার, তবে সেটা অর্জন করতে হয়।

### একবার build করুন, সব জায়গায় এগিয়ে নিন ⭐

```
        ┌──────────────┐
        │ একবার BUILD  │  → artefact: image@sha256:abc123
        └──────┬───────┘
               │  একই artefact, প্রতি পরিবেশে configuration ঢোকানো
     ┌─────────┼─────────┬──────────┐
     ▼         ▼         ▼          ▼
   [dev]    [staging]  [canary]  [production]
```

> **কখনো প্রতি পরিবেশে আবার build করবেন না।** Staging আর production-এ যদি আলাদা binary থাকে, তাহলে staging কিছুই প্রমাণ করে না। Configuration পরিবেশ অনুযায়ী বদলায়; artefact বদলানো চলবে না।

---

## ১৬.৩ Infrastructure as Code 🟢

**যে সমস্যার সমাধান করে:** একটা ক্লাউড console-এ ক্লিক করা পুনরাবৃত্তিযোগ্য নয়, review করা যায় না, নথিভুক্ত নয়, আর একটা বিপর্যয়ের পর আবার বানানো অসম্ভব।

```hcl
# Terraform — declarative কাঙ্ক্ষিত অবস্থা
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
  publicly_accessible    = false            # ← একটা pull request-এ review-যোগ্য

  performance_insights_enabled = true
  monitoring_interval          = 60

  tags = local.common_tags
}
```

**Automation-এর বাইরে IaC আপনাকে যা দেয়:**

| সুবিধা | কেন গুরুত্বপূর্ণ |
|---------|---------------|
| **Review-যোগ্য** | `publicly_accessible = true` একটা PR-এ ধরা পড়ে, একটা breach-এর report-এ নয় |
| **পুনরুৎপাদনযোগ্য** | পুরো পরিবেশ শূন্য থেকে আবার বানান — এটাই *আপনার* disaster recovery |
| **Audit-যোগ্য** | Git-এর ইতিহাস উত্তর দেয় "কে ওই port খুলেছিল, কখন, আর কেন" |
| **নথিভুক্ত** | কোডটাই documentation, আর এটা বাস্তবতা থেকে ভেসে যেতে পারে না |
| **Testable** | Policy-as-code (OPA, Checkov, tfsec) অনিরাপদ configuration-এ build fail করায় |
| **সামঞ্জস্যপূর্ণ** | Dev, staging আর production শুধু সেখানেই আলাদা যেখানে আপনি চেয়েছেন |

### Declarative বনাম imperative

| | Declarative (Terraform, CloudFormation, Kubernetes) | Imperative (script, CLI, Ansible playbook) |
|---|---|---|
| আপনি বর্ণনা করেন | কাঙ্ক্ষিত শেষ অবস্থা | সেখানে পৌঁছানোর ধাপ |
| আবার চালানো | নিরাপদ — একই অবস্থায় মিলিত হয় | প্রায়ই অনিরাপদ বা পুনরাবৃত্ত |
| Drift শনাক্তকরণ | অন্তর্নির্মিত (`plan` পার্থক্য দেখায়) | নেই |
| ক্রম | নির্ভরতা থেকে অনুমিত | আপনি সামলান |

> Declarative-কে প্রাধান্য দিন। Imperative টুল (Ansible, script) মেশিনের *ভেতরের* configuration-এ, বা এককালীন operational কাজে ব্যবহার করুন।

### IaC-র শৃঙ্খলা

১. **Lock সহ remote state** (S3 + DynamoDB, Terraform Cloud)। Local state ফাইল হলো সেই উপায় যেভাবে টিম একে অপরের infrastructure মুছে দেয়।
২. **প্রতি পরিবেশে আলাদা state।** Dev-এ একটা `terraform apply` production ছুঁতে পারাটাই অসম্ভব হতে হবে।
৩. **কখনো হাতে production বদলাবেন না।** Manual পরিবর্তন drift ঘটায়; পরের `apply` সেগুলো ফিরিয়ে দেয়, প্রায়ই সবচেয়ে খারাপ সময়ে। একটা incident-এ যদি জরুরি হস্তক্ষেপ করতেই হয়, **সেই সপ্তাহেই সেটা কোডে আনার একটা ticket বানান।**
৪. **PR-এ plan, merge-এ apply।** `plan`-এর output-ই review-র উপকরণ।
৫. পুনরাবৃত্ত pattern-এর জন্য **module**, version করা আর পরীক্ষিত।
৬. **Policy as code** — unencrypted storage, public database, অনুপস্থিত tag স্বয়ংক্রিয়ভাবে প্রত্যাখ্যান করুন।
৭. **State ফাইলে কখনো secret নয়** — Terraform-এর state-এ resource-এর বৈশিষ্ট্য plaintext-এ থাকে; state bucket-কে একটা secret store হিসেবে দেখুন আর encrypt করুন।

### GitOps 🟡

**কাঙ্ক্ষিত অবস্থার একমাত্র সত্যের উৎস Git; cluster-এর ভেতরের একটা agent অনবরত বাস্তবতাকে সেটার সাথে মেলায়।**

```
Developer ──PR──► Git repo (manifest) ──► ArgoCD / Flux (cluster-এ)
                                                  │
                                        অনবরত reconcile করে
                                                  ▼
                                            Kubernetes
```

| Push-ভিত্তিক CI/CD | GitOps (pull-ভিত্তিক) |
|---|---|
| CI-র কাছে production-এর credential আছে | **Cluster-এর credential কখনো cluster ছাড়ে না** |
| State-এর drift অদৃশ্য | Drift শনাক্ত হয় আর স্বয়ংক্রিয়ভাবে শুধরে যায় |
| Rollback = একটা pipeline আবার চালানো | **Rollback = `git revert`** |
| "কী deploy আছে?" = pipeline-এর log দেখুন | "কী deploy আছে?" = repo পড়ুন |

> নিরাপত্তার যুক্তিটাই সবচেয়ে শক্তিশালী: GitOps-এ আপনার CI সিস্টেমের cluster admin credential লাগে না, যেটা একটা খুবই আকর্ষণীয় আক্রমণের লক্ষ্য সরিয়ে দেয়। Kubernetes-এর reconciliation মডেলের (অধ্যায় ১৫) সাথে মিলিয়ে এটা স্বাভাবিকভাবেই মানায়।

---

## ১৬.৪ পরিবেশ, configuration আর secret 🟢

### পরিবেশের কৌশল

```
LOCAL       ডেভেলপারের মেশিন; dependency-র জন্য container বা mock
DEV         integration; merge-এ স্বয়ংক্রিয় deploy; ফেলে দেওয়ার যোগ্য
STAGING     production-এর মতো: একই topology, একই IaC, বাস্তবসম্মত (anonymised) data
PRODUCTION  আসলটা
```

**Staging শুধু তখনই কাজের যখন এটা সত্যিই production-এর মতো।** একটা instance, একটা আলাদা database সংস্করণ আর ২০০ row-র test data সহ একটা staging পরিবেশ কিছুই প্রমাণ করে না। একটা production-সদৃশ staging পরিবেশ যদি সামর্থ্যে না কুলায়, তাহলে সেটা নিয়ে সৎ থাকুন আর বরং **production-এ progressive delivery**-তে বিনিয়োগ করুন (canary, feature flag, ভালো observability) — যেটা প্রায়ই এমনিতেই ভালো বিনিয়োগ।

**ক্ষণস্থায়ী preview পরিবেশ** (প্রতি pull request-এ একটা, merge-এ ভেঙে ফেলা) একটা platform যা দিতে পারে তার মধ্যে সবচেয়ে মূল্যবান জিনিসগুলোর একটা: reviewer-রা একটা branch pull করার বদলে একটা লিংকে ক্লিক করেন।

### Twelve-Factor-এর যে নিয়মগুলো এখনো গুরুত্বপূর্ণ 🟢

মূল বারোটার মধ্যে এগুলোই সত্যিই architecture-এর আকার দেয়:

| Factor | নিয়ম | কেন |
|--------|------|-----|
| **III. Config** | **Config পরিবেশে, কখনো কোডে নয়** | একই artefact সব জায়গায় চলে |
| **IV. Backing service** | Database/queue-কে URL দিয়ে ঠিকানা দেওয়া সংযুক্ত সম্পদ ভাবুন | শুধু config বদলে একটা local Postgres-কে RDS দিয়ে বদলান |
| **VI. Process** | **Stateless আর কিছু ভাগ না করা** | Horizontal scaling-এর ভিত্তি (অধ্যায় ০৪) |
| **IX. Disposability** | দ্রুত শুরু, **graceful shutdown** | Autoscaling আর zero-downtime deploy সম্ভব করে (অধ্যায় ১৫) |
| **X. Dev/prod parity** | পরিবেশগুলো যতটা সম্ভব একরকম রাখুন | Bug staging-এ ধরা পড়ে, production-এ নয় |
| **XI. Log** | **stdout-এ একটা ধারা হিসেবে লিখুন** — log ফাইল সামলাবেন না | Platform সংগ্রহ আর routing সামলায় |

### Configuration

```python
# Type করা, যাচাই করা configuration যা startup-এ দ্রুত fail করে
class Settings(BaseSettings):
    database_url: PostgresDsn
    redis_url: RedisDsn
    vendor_api_timeout_ms: int = Field(default=8000, ge=100, le=30000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()      # config অবৈধ হলে STARTUP-এই raise করে
```

> **খারাপ configuration-এ দ্রুত fail করুন।** যে service একটা অনুপস্থিত setting নিয়ে খুশিমনে শুরু হয় আর তারপর রাত ২টায় প্রথম request-এ fail করে, সেটা deployment pipeline-এ শুরু হতে অস্বীকার করা একটার চেয়ে অনেক খারাপ। Boot-এই সবকিছু যাচাই করুন।

**Configuration-এর অগ্রাধিকার:** কোডে default → পরিবেশ-নির্দিষ্ট ফাইল → environment variable → রানটাইম override (feature flag)। অগ্রাধিকারটা স্পষ্ট আর নথিভুক্ত করুন।

### Secret — নিয়মগুলো 🟢

```
❌ Source control-এ (একটা private repo-তেও — এটা git-এর ইতিহাসে স্থায়ী)
❌ Container image-এ
❌ CI-র log-এ (mask করুন, আর masking কাজ করে কিনা যাচাই করুন)
⚠️ Environment variable-এ (চলে, তবে process listing আর crash dump-এ দেখা যায়)
✅ একটা secrets manager-এ, রানটাইমে ঢোকানো
✅ আরও ভালো: কোনো static secret-ই নয় — workload identity, স্বল্পস্থায়ী token
```

**ঘোরানো:** যে secret কখনো ঘোরানো হয়নি, সেটা এমন একটা secret যা আপনি ঘোরাতে পারবেন না। এটা অনুশীলন করুন। যেসব credential স্বয়ংক্রিয়ভাবে ঘোরে সেগুলোকে প্রাধান্য দিন (IAM database auth, ক্লাউড-managed ঘোরানো)।

**একটা secret ফাঁস হলে:** আগে ঘোরান, পরে তদন্ত করুন। git-এর ইতিহাস থেকে সরানো এটাকে নিরাপদ করে **না** — push হওয়ার মুহূর্ত থেকেই এটাকে আপসকৃত ধরে নিন।

---

## ১৬.৫ একটা pipeline-এ database migration 🟢

**এখানেই বেশিরভাগ "আমরা rollback করতে পারছি না" পরিস্থিতি তৈরি হয়।**

### নিয়মগুলো

১. **Migration application deploy থেকে আলাদাভাবে চলে**, নতুন কোডের আগে (যোগ করার পরিবর্তনে) বা পরে (সরানোর ক্ষেত্রে)
২. **প্রতিটা migration বর্তমানে চলা সংস্করণের সাথে backward compatible হতে হবে** — কারণ একটা rolling deploy-এর সময় দুটো সংস্করণই একসাথে চলে (অধ্যায় ১৫)
৩. **কোড পরিবর্তনের একই release-এ কখনো একটা ধ্বংসাত্মক migration লিখবেন না** — expand/contract ব্যবহার করুন (অধ্যায় ০৯)
৪. **Production-এ শুধু সামনের দিকে।** "Down" migration একটা সান্ত্বনাদায়ক কল্পকাহিনি: এগুলো সাধারণত ফেলে দেওয়া data ফেরাতে পারে না। **একটা fix দিয়ে সামনে এগিয়ে যান।**
৫. **Production-আকারের একটা কপির বিপরীতে migration test করুন** — ১,০০০ row-তে ৪ ms লাগা একটা migration ৫ কোটিতে ৪০ মিনিট নিতে আর একটা table lock করতে পারে
৬. **Retry সহ ছোট `lock_timeout`**, যাতে একটা migration application জমিয়ে না দিয়ে দ্রুত fail করে

```python
# চারটা release জুড়ে expand/contract (অধ্যায় ০৯), pipeline-এর ধাপ হিসেবে
# Release ১: নতুন কলাম যোগ করুন (nullable)। কোড দুটোতেই লেখে, পুরনোটা পড়ে।
# Release ২: batch-এ BACKFILL করুন (একটা job, একটা migration নয়)।
# Release ৩: কোড নতুনটা পড়ে, এখনো দুটোতেই লেখে।
# Release ৪: কোড শুধু নতুনটা ব্যবহার করে। তারপর পুরনো কলাম ফেলে দিন।
```

প্রতিটা release স্বাধীনভাবে deploy করা যায় আর স্বাধীনভাবে ফেরানো যায়। এটাই zero-downtime সম্ভব করে।

---

## ১৬.৬ Progressive delivery আর rollback 🟢

(কৌশলগুলো অধ্যায় ১৫ §১৫.৯-এ। এখানে pipeline আর operational দৃষ্টিভঙ্গি।)

### Rollback একঘেয়ে হতে হবে

> **আপনার ৫ মিনিটের কম সময়ে, রাত ৩টায়, এমন কারও দ্বারা rollback করতে পারা উচিত যিনি পরিবর্তনটা লেখেননি।**

মানে:
- [ ] একটা নথিভুক্ত, অনুশীলিত, এক-command-এর প্রক্রিয়া
- [ ] আগের artefact রাখা আর সাথে সাথে deploy করার যোগ্য
- [ ] Database-এর পরিবর্তন backward compatible, তাই কোড rollback করা নিরাপদ
- [ ] Feature flag একটা deploy **ছাড়াই** একটা feature বন্ধ করতে পারে — উপলব্ধ দ্রুততম "rollback"
- [ ] **আপনি সত্যিই এটা অনুশীলন করেছেন** — যে rollback প্রক্রিয়া কেউ চালায়নি সেটা একটা তত্ত্ব

**যেখানে পারেন সিদ্ধান্তটা automate করুন:**

```yaml
# একটা canary-র সময় error-হার সীমা ছাড়ালে স্বয়ংক্রিয়ভাবে rollback করুন
analysis:
  templates: [{ templateName: error-rate }]
  args: [{ name: service, value: verification-api }]
# error-rate template: ৫ মিনিটে rate(http_requests_total{code=~"5.."}) > 0.02 হলে fail
```

### যে কোনো উল্লেখযোগ্য কিছুর জন্য release-এর চেকলিস্ট

- [ ] Backward-compatible API আর schema পরিবর্তন
- [ ] Feature flag বসানো, default বন্ধ
- [ ] Deploy-এর **আগেই** dashboard আর alert প্রস্তুত
- [ ] Rollback-এর প্রক্রিয়া যাচাই করা আর artefact রাখা
- [ ] যেখানে সম্ভব অফিস-সময়ে deploy (যাঁরা ঠিক করতে পারেন তাঁরা জেগে আছেন)
- [ ] প্রথম ৩০ মিনিট একজন নামযুক্ত মালিক নজর রাখছেন
- [ ] Customer প্রভাবিত হলে যোগাযোগের পরিকল্পনা

> **"শুক্রবার বিকেলে deploy" কোনো কারিগরি প্রশ্ন নয়, এটা আপনি নিরাপদে ফেরাতে পারেন কিনা তার প্রশ্ন।** যাদের দ্রুত, একঘেয়ে rollback আছে তারা দুশ্চিন্তা ছাড়াই শুক্রবারে deploy করে। যাদের নেই তাদের মঙ্গলবারেও deploy করা উচিত নয়।

---

## ১৬.৭ Platform Engineering 🟡

### যে সমস্যার সমাধান করে

একটা product টিমকে infrastructure-এর পূর্ণ মালিকানা দিন, আর দুটোর একটা ঘটবে:

১. প্রতিটা টিম একই সমস্যা আলাদাভাবে সমাধান করে — ছয়টা CI pattern, চারটা logging ফরম্যাট, তিনভাবে deploy — আর কেউ টিম বদলাতে পারে না
২. অথবা তারা একদমই পেরে ওঠে না, আর মানসিক চাপ তাদের delivery ধ্বংস করে

**Platform engineering-ই উত্তর: এমন একটা ভেতরের product বানান যার গ্রাহক আপনার নিজের ডেভেলপাররা।**

```
                ┌──────────────────────────────────────┐
                │  INTERNAL DEVELOPER PLATFORM         │
                │                                      │
                │  • Golden-path template              │
                │  • Self-service পরিবেশ                │
                │  • প্রচলিত CI/CD pipeline              │
                │  • Default-এই যুক্ত observability      │
                │  • Secret, identity, networking      │
                │  • রক্ষাকবচ (policy as code)          │
                └──────────────────────────────────────┘
                 যারা ব্যবহার করে ↓  ↓  ↓  ↓
        Team A    Team B    Team C    Team D
```

### Golden path ⭐

**পাকা রাস্তা: কিছু করার সবচেয়ে সহজ উপায়টাই সঠিক উপায়।**

```bash
$ platform new service --name billing-api --template python-fastapi

তৈরি হলো:
  ✓ প্রচলিত প্রজেক্ট বিন্যাস সহ Repository
  ✓ CI pipeline (lint, test, scan, sign, build, deploy)
  ✓ Dockerfile (multi-stage, non-root, scan করা)
  ✓ Kubernetes manifest (probe, resource, PDB, HPA)
  ✓ Observability: structured logging, metric, tracing, dashboard
  ✓ Secret integration আর workload identity
  ✓ Staging পরিবেশ
  ✓ On-call runbook-এর খসড়া আর মালিকানার metadata
```

> **একজন আর্কিটেক্ট যা বানাতে পারেন তার মধ্যে এটাই একক সবচেয়ে লাভজনক।** একটা template-এ গেঁথে দেওয়া architecture-এর সিদ্ধান্ত আসলেই অনুসৃত হয়। একটা document-এ লেখা architecture-এর সিদ্ধান্ত একবার পড়া হয় আর ভুলে যাওয়া হয়।

**গুরুত্বপূর্ণ নীতি: golden path ঐচ্ছিক হতে হবে কিন্তু অপ্রতিরোধ্যভাবে আকর্ষণীয়।** এটা বাধ্যতামূলক করলে বিরক্তি আর ছায়া-infrastructure তৈরি হয়। এটাকে সত্যিই দ্রুততম পথ বানালে টিম নিজেরাই এটা বাছে — আর আপনি সম্মতির মাধ্যমে সামঞ্জস্য পান।

### Platform একটা product হিসেবে

| Product-এর শৃঙ্খলা | Platform-এ প্রয়োগ |
|-------------------|------------------------|
| আপনার ব্যবহারকারীদের জানুন | ডেভেলপারদের সাথে কথা বলুন; তাঁদের কাজ করতে দেখুন |
| গ্রহণযোগ্যতা মাপুন | কতগুলো টিম golden path ব্যবহার করে? |
| সন্তুষ্টি মাপুন | ডেভেলপার জরিপ; ঘর্ষণ কোথায় থেকে গেছে? |
| Roadmap আর versioning | Platform-এর পরিবর্তন হলো note সহ release |
| Support আর docs | একটা আসল support channel, "wiki পড়ুন" নয় |
| **গ্রহণ বাধ্যতামূলক করবেন না** | টিম যদি আপনাকে ঘুরিয়ে যায়, তাহলে আপনার product খারাপ |

**যে metric গুলো গুরুত্বপূর্ণ:** একটা নতুন service-এর `git init` থেকে production পর্যন্ত সময় (লক্ষ্য: ঘণ্টা, সপ্তাহ নয়); একজন নতুন ইঞ্জিনিয়ারের প্রথম production পরিবর্তনের সময় (লক্ষ্য: এক সপ্তাহের কম); golden path-এ থাকা service-এর শতাংশ।

### কখন আপনার একটা platform টিম লাগবে

| ইঞ্জিনিয়ার | পদ্ধতি |
|-----------|----------|
| < ২০ | কোনো platform টিম নয়। একটা shared template repo আর কয়েকটা প্রথা। |
| ২০–৬০ | এক-দুজন খণ্ডকালীন; CI/CD আর observability মানসম্মত করুন |
| ৬০+ | একটা নিবেদিত platform টিম, একটা product টিম হিসেবে দেখা |

> **ব্যথা অনুভব করার আগে একটা platform বানাবেন না।** ১৫ জন ইঞ্জিনিয়ারে একটা platform টিম মানে ২ জন মানুষ product না বানিয়ে এমন সমস্যা সমাধান করছেন যা এখনো আপনার নেই।

---

## ১৬.৮ Feature flag 🟡

```python
if await flags.enabled("new-scoring-model", context={"tenant": tid, "user": uid}):
    ...
```

**চারটা আলাদা ব্যবহার — এদের জীবনচক্র আলাদা আর নামও আলাদা হওয়া উচিত:**

| ধরন | উদ্দেশ্য | আয়ু |
|------|---------|----------|
| **Release toggle** | অন্ধকারে deploy, পরে চালু | দিন–সপ্তাহ। **Release-এর পর মুছে ফেলুন।** |
| **Experiment** | A/B test | পরীক্ষার সময়কাল |
| **Ops toggle** | Load-এ একটা ব্যয়বহুল feature-এর kill switch | দীর্ঘস্থায়ী, ইচ্ছাকৃতভাবে |
| **Permission toggle** | প্রতি plan/tenant-এ অধিকার | স্থায়ী (এটা আসলে configuration) |

### Flag-এর ঋণ বাস্তব

প্রতিটা flag তাত্ত্বিকভাবে কোডের পথের সংখ্যা দ্বিগুণ করে। দশটা flag = ১,০২৪টা সমন্বয় যা আপনি test করতে পারবেন না।

```
নিয়ম:
  ✅ প্রতিটা release toggle তৈরির সময়ই একটা মেয়াদ আর একজন মালিক পায়
  ✅ ৯০ দিনের বেশি পুরনো flag-এ CI সতর্ক করে
  ✅ একটা flag সরানো feature-এর "শেষ হয়েছে"-র সংজ্ঞার অংশ
  ✅ শুধু ops toggle আর অধিকার স্থায়ী হওয়ার অনুমতি পায়
  ✅ Default-কে নিরাপদ মান হতে হবে (সাধারণত বন্ধ)
```

> **প্রতিদানটা শৃঙ্খলার যৌক্তিকতা দেয়:** deploy-কে release থেকে আলাদা করা মানে আপনি অবিরাম ship করতে পারেন আর একটা tenant-এর জন্য feature চালু করতে পারেন, তারপর ৫%, তারপর সবার জন্য — আর একটা deploy ছাড়াই এক সেকেন্ডে বন্ধ করতে পারেন। উপলব্ধ দ্রুততম incident উপশম এটাই।

---

## ১৬.৯ সাধারণ ভুল

১. **Deploy pipeline-কে architecture-এর অংশ না ভাবা** — যে design নিরাপদে ship করতে পারে না সেটা শেষ হয়নি
২. **প্রতি পরিবেশে artefact আবার build করা** — তাহলে staging কিছুই প্রমাণ করে না
৩. **ধীর CI (> ২০ মিনিট)** — ডেভেলপাররা এটা চালানো বন্ধ করে আর পরিবর্তন জমিয়ে রাখে
৪. **Flaky test সহ্য করা** — টিম লাল build উপেক্ষা করতে শেখে, যা CI-র মূল্য ধ্বংস করে
৫. **Production infrastructure-এ manual পরিবর্তন** — drift, তারপর পরের apply-এ একটা চমকপ্রদ ফিরে যাওয়া
৬. **Lock ছাড়া Terraform state, বা পরিবেশ জুড়ে ভাগ করা**
৭. **git, image, বা CI-র log-এ secret**
৮. **কোড পরিবর্তনের সাথে ধ্বংসাত্মক migration ship করা** — rollback অসম্ভব হয়ে যায়
৯. **অপরীক্ষিত rollback প্রক্রিয়া** — একটা incident-এর সময় আবিষ্কার হয় যে এটা ভাঙা
১০. **Production-এর সাথে কোনো মিল নেই এমন staging** — মিথ্যা আত্মবিশ্বাস
১১. **মেয়াদ ছাড়া feature flag** — ২০০টা flag, সূচকীয় অপরীক্ষিত পথ
১২. **খুব আগেভাগে একটা platform টিম বানানো** — এমন সমস্যা সমাধান করা যা এখনো আপনার নেই
১৩. **Golden path বাধ্যতামূলক করা** — টিম এটা ঘুরিয়ে যায় আর আপনি ছায়া-infrastructure পান
১৪. **ব্যর্থতার হার না কমিয়ে deployment-এর ঘনত্ব optimise করা** — দ্রুত bug ship করা কোনো অগ্রগতি নয়

---

## ১৬.১০ আর্কিটেক্টের চেকলিস্ট

- [ ] DORA metric মাপা আর দৃশ্যমান; ত্রৈমাসিক প্রবণতা রিভিউ করা
- [ ] Merge-যোগ্য হতে CI ১০ মিনিটের নিচে; আগে দ্রুত যাচাই
- [ ] একবার build, প্রতিটা পরিবেশে একই artefact এগিয়ে নেওয়া
- [ ] CI-তে architecture fitness function চলে (অধ্যায় ০০)
- [ ] CI-তে API contract-এর breaking-change শনাক্তকরণ (অধ্যায় ০৮)
- [ ] Pipeline-এ image scan, SBOM, আর signing; CRITICAL-এ build fail
- [ ] CI-তে কোনো দীর্ঘস্থায়ী ক্লাউড credential নেই — OIDC federation
- [ ] সব infrastructure কোড হিসেবে সংজ্ঞায়িত; কোনো manual production পরিবর্তন নেই
- [ ] Remote, locked, encrypted state; প্রতি পরিবেশে আলাদা
- [ ] Policy-as-code স্বয়ংক্রিয়ভাবে অনিরাপদ configuration প্রত্যাখ্যান করছে
- [ ] Secret একটা manager-এ, রানটাইমে ঢোকানো, ঘোরানো, কখনো log নয়
- [ ] Configuration startup-এ যাচাই করা — দ্রুত fail
- [ ] Migration backward compatible, expand/contract, production-আকারে পরীক্ষিত
- [ ] Rollback নথিভুক্ত, ৫ মিনিটের নিচে, আর **অনুশীলিত**
- [ ] Feature flag-এ মালিক, মেয়াদ, আর নিরাপদ default
- [ ] প্রতি pull request-এ ক্ষণস্থায়ী preview পরিবেশ (সামর্থ্যে কুলালে)
- [ ] Golden-path template আছে আর সেটা architecture-এর সিদ্ধান্ত ধারণ করে
- [ ] প্রতিটা service-এর একজন নামযুক্ত মালিক আর একটা on-call runbook আছে

---

## ১৬.১১ নিজেকে যাচাই

১. Deployment pipeline কেন একটা architecture-এর বিষয়? এটাকে সীমাবদ্ধ করে এমন তিনটা architecture-পছন্দ দিন।
২. চারটা DORA metric-এর নাম বলুন। গতি আর স্থিতিশীলতা নিয়ে স্বজ্ঞাবিরোধী আবিষ্কারটা কী?
৩. প্রতি পরিবেশে আবার build না করে একবার build করে এগিয়ে নিতে হবে কেন?
৪. একটা CI pipeline-এ ধাপের সঠিক ক্রম কী, আর কেন?
৫. একটা flaky test একটা অনুপস্থিত test-এর চেয়ে খারাপ কেন?
৬. Continuous Delivery বনাম Continuous Deployment — পার্থক্য কী আর বেশিরভাগ টিমের কোনটা লক্ষ্য করা উচিত?
৭. Automation-এর বাইরে IaC আপনাকে কী দেয়? পাঁচটা জিনিস বলুন।
৮. GitOps কী, আর এর সবচেয়ে শক্তিশালী যুক্তি কী?
৯. "Down" migration বেশিরভাগটাই কেন একটা কল্পকাহিনি? এর বদলে আপনি কী করবেন?
১০. প্রতিটা migration-কে বর্তমানে চলা কোডের সাথে backward compatible হতে হবে কেন?
১১. একটা rollback-কে কী "একঘেয়ে" করে, আর সেটা deploy-এর প্রক্রিয়ার চেয়ে বেশি গুরুত্বপূর্ণ কেন?
১২. Golden path কী, আর এটা কেন ঐচ্ছিক হতে হবে?
১৩. চার ধরনের feature flag আর তাদের প্রত্যাশিত আয়ুর নাম বলুন।
১৪. একটা কোম্পানির কখন একটা platform টিম বানানো উচিত — আর কখন এটা খুব আগেভাগে?

---

## ১৬.১২ মূল কথাগুলো

- **আপনার pipeline আপনার architecture-এর অংশ।** যে design নিরাপদে আর ফেরানোর মতো করে deploy করা যায় না সেটা অসম্পূর্ণ।
- **গতি আর স্থিতিশীলতা একসাথে চলে** — ছোট batch নিরাপদ, আর DORA এটা প্রমাণ করেছে
- **একবার build করুন, সব জায়গায় এগিয়ে নিন।** প্রতি পরিবেশে আলাদা binary testing-কে অর্থহীন করে।
- **CI ১০ মিনিটের নিচে, আগে দ্রুত যাচাই, flaky test-এ শূন্য সহনশীলতা**
- **Infrastructure as Code নিরাপত্তাকে review-যোগ্য করে** — `publicly_accessible = true` একটা PR-এ ধরা পড়ে
- **কোনো manual production পরিবর্তন নয়।** কখনোই না। জরুরি fix সেই সপ্তাহেই কোডে আনুন।
- **Migration-এই rollback মরে** — expand/contract, backward compatible, শুধু সামনের দিকে
- **Rollback একঘেয়ে, দ্রুত আর অনুশীলিত হতে হবে।** Feature flag-ই সবচেয়ে দ্রুত rollback।
- **Golden path আপনার হাতের সবচেয়ে লাভজনক architecture টুল** — template-এর সিদ্ধান্ত অনুসৃত হয়; document-এর সিদ্ধান্ত হয় না
- **ব্যথা অনুভব করার আগে একটা platform টিম বানাবেন না**

---

**পরবর্তী:** [অধ্যায় ১৭ — Security Architecture](17-security-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 16](../16-devops-and-platform-engineering.md) · **[সূচিপত্র](README.md)**
