# অধ্যায় ২১ — Testing Architecture 🟡

> Test bug খোঁজার জন্য নয়। Test হলো **ভয় ছাড়া সিস্টেম বদলাতে পারার** জন্য।
>
> Test-বিহীন একটা codebase "অপরীক্ষিত" নয় — এটা **জমে যাওয়া**। প্রতিটা পরিবর্তন একটা জুয়া, তাই পরিবর্তন বিরল হয়, batch বড় হয়, আর প্রতিটা release আরও বিপজ্জনক হয়। তাই testing একটা *deployability*-র বিষয়, যা এটাকে একটা architecture-এর বিষয় করে (অধ্যায় ১৬)।

---

## ২১.১ Testing কেন architecture

**Testability একটা quality attribute** (অধ্যায় ০০), আর এটা পরিশ্রম নয়, কাঠামো দিয়ে নির্ধারিত:

| Architecture-এর পছন্দ | Testing-এর ফলাফল |
|--------------------|--------------------|
| Business logic I/O-র সাথে মেশানো | Database আর network ছাড়া নিয়ম test করা যায় না |
| Class-এর ভেতরে dependency বানানো (`new SqlConnection()`) | বদলানোর কোনো seam নেই; আসল infrastructure-এর বিপরীতেই test করতে হয় |
| Static/global state | Test একে অপরের ভেতর ফাঁস করে; ক্রম-নির্ভর ব্যর্থতা |
| Framework-মুক্ত domain layer (অধ্যায় ০২) | নিয়ম **মাইক্রোসেকেন্ডে** test হয়, কোনো setup ছাড়াই |
| Port আর adapter | In-memory adapter পুরো application-এর logic test করে |
| Service নিজের data-র মালিক | স্বাধীনভাবে test করা যায় |
| Service-এর মধ্যে shared database | প্রতিটা test-এ পুরো সিস্টেম চালাতে হয় |

> **আপনার test যদি ধীর, যন্ত্রণাদায়ক আর flaky হয়, সেটা একটা design-এর আবিষ্কার, testing-এর নয়।** সাধারণ মূল কারণ হলো infrastructure ছাড়া business logic-এ পৌঁছানো যায় না। Seam গুলো ঠিক করুন (অধ্যায় ০১-এর DIP, অধ্যায় ০২-এর hexagonal) আর test প্রায় আপনাআপনিই দ্রুত আর আনন্দদায়ক হয়ে যায়।

---

## ২১.২ Test-পিরামিড — আর এর সৎ সমালোচনা

```
                    ╱╲
                   ╱E2E╲          কম:  ধীর, ভঙ্গুর, ব্যয়বহুল, উঁচু আত্মবিশ্বাস
                  ╱──────╲
                 ╱ INTEG  ╲       কিছু: মাঝারি গতি, আসল infrastructure
                ╱──────────╲
               ╱    UNIT    ╲     অনেক: মিলিসেকেন্ড, কোনো I/O নেই, নির্দিষ্ট ব্যর্থতা
              ╱──────────────╲
```

**আকৃতিটার পেছনের যুক্তি:**

| স্তর | গতি | খরচ | আত্মবিশ্বাস | ব্যর্থতার নির্ণয় |
|-------|-------|------|-----------|-------------------|
| Unit | µs–ms | খুব কম | সংকীর্ণ | **ঠিক function-টা দেখিয়ে দেয়** |
| Integration | ১০ ms–১ s | মাঝারি | আসল | একটা component দেখায় |
| E2E | ১০ s–মিনিট | বেশি | সর্বোচ্চ | *"কোথাও কিছু একটা ভাঙল"* |

শেষ কলামটা মানুষের ধারণার চেয়ে বেশি গুরুত্বপূর্ণ: **একটা ব্যর্থ unit test আপনাকে বলে কী ঠিক করতে হবে; একটা ব্যর্থ E2E test আপনাকে বলে তদন্ত শুরু করতে।**

### সৎ সমালোচনাগুলো

**১. "Testing trophy"-র যুক্তি (Kent C. Dodds):** অনেক আধুনিক codebase-এ integration test প্রতি-পরিশ্রমে সবচেয়ে বেশি আত্মবিশ্বাস দেয়, কারণ বেশিরভাগ আসল bug component-গুলোর *মাঝের সংযোগে* থাকে, একটা function-এর ভেতরে নয়। দ্রুত টুল (Testcontainers, in-memory database) থাকায় integration test আর নিষেধাত্মকভাবে ধীর নয়।

**২. "Ice cream cone" anti-pattern** — অনেক manual আর E2E test, কম unit test। কেউ কৌশলটা design না করলে default-এ এটাই হয়। এটা ধীর, flaky আর ব্যয়বহুল।

**৩. Implementation-এর খুঁটিনাটি test করা** — যে unit test সবকিছু mock করে আর দাবি করে `repository.save()` call হয়েছিল, সেটা *আপনার কোডের কাঠামো* test করে, আচরণ নয়। এটা প্রতিটা refactor-এ ভাঙে আর কোনো আসল bug ধরে না। Test-suite একটা সম্পদের বদলে একটা দায় হওয়ার এটাই সবচেয়ে সাধারণ উপায়।

> **বাস্তববাদী অবস্থান:** এই দুটো নিয়মের চেয়ে আকৃতি কম গুরুত্বপূর্ণ —
> **(ক) implementation নয়, *আচরণ* test করুন**, আর
> **(খ) প্রতিটা test-কে সবচেয়ে দ্রুত সেই স্তরে ঠেলে দিন যেখানে আচরণটা সত্যিই যাচাই করা যায়।**

---

## ২১.৩ Unit test 🟢

**সংজ্ঞা:** কোনো I/O ছাড়া, বিচ্ছিন্নভাবে একটা আচরণের একক test করে।

**"Unit" মানে কী তা নিয়ে বিতর্ক আছে; কাজের সংজ্ঞাটা হলো "একটা আচরণ", "একটা class" নয়।** যে test কোনো I/O ছাড়া তিনটা সহযোগী class চালায়, সেটাও একটা দ্রুত, মূল্যবান unit test।

```python
# বিশুদ্ধ domain logic — কোনো database নেই, কোনো network নেই, কোনো mock-ই লাগে না।
# একটা পরিষ্কার domain layer আপনাকে এটাই কিনে দেয় (অধ্যায় ০২, ০৩)।
def test_session_fails_after_max_attempts():
    session = VerificationSession.start(CustomerId("c1"), policy_with(max_attempts=3), NOW)

    for _ in range(3):
        session.record_attempt(failing_signals(), NOW)

    assert session.outcome is Outcome.FAILED
    assert "max attempts" in session.failure_reason


def test_borderline_score_goes_to_manual_review():
    session = VerificationSession.start(CustomerId("c1"), default_policy(), NOW)

    session.record_attempt(Signals(liveness=LivenessScore(Decimal("0.82")),
                                   spoof_detected=False, head_pose_valid=True), NOW)

    assert session.outcome is Outcome.MANUAL_REVIEW
```

ওই test গুলো **মাইক্রোসেকেন্ডে** চলে, কোনো setup লাগে না, আর business-এর নিয়মগুলো এত পরিষ্কারভাবে বর্ণনা করে যে একজন compliance officer পড়তে পারবেন।

### একটা ভালো unit test-এর বৈশিষ্ট্য (FIRST)

| বৈশিষ্ট্য | মানে |
|----------|---------|
| **F**ast | মিলিসেকেন্ড। পুরো suite এক মিনিটের নিচে। |
| **I**solated | কোনো ভাগ করা state নেই; যে কোনো ক্রমে; সমান্তরাল-নিরাপদ |
| **R**epeatable | প্রতিবার, প্রতিটা মেশিনে, চিরকাল একই ফলাফল |
| **S**elf-validating | Pass বা fail — কোনো মানুষের output পড়া লাগে না |
| **T**imely | কোডের সাথেই লেখা, "পরে" নয় |

### আচরণ test করুন, implementation নয়

```python
# ❌ Implementation test করে — যে কোনো refactor-এ ভাঙে, কোনো আসল bug ধরে না
def test_approve():
    repo = Mock()
    svc = Service(repo)
    svc.approve("s1")
    repo.get.assert_called_once_with("s1")          # কে পরোয়া করে?
    repo.save.assert_called_once()                  # কে পরোয়া করে?

# ✅ আচরণ test করে — refactoring-এ টেকে, আসল bug ধরে
def test_approving_a_session_records_the_reviewer_and_marks_it_approved():
    repo = InMemorySessionRepository(seed=[pending_session("s1")])
    svc = Service(repo)

    svc.approve("s1", reviewer_id="r9")

    stored = repo.get("s1")
    assert stored.status is SessionStatus.APPROVED
    assert stored.reviewed_by == "r9"
```

দ্বিতীয় সংস্করণটা repository বদলানো, ORM বদলানো, বা service নতুন করে সাজানো — সবই টিকে যেত, আর আচরণ ভাঙলে fail করত। পুরো কথাটাই এটা।

### Test double — পার্থক্যটা জানুন

| Double | আচরণ | ব্যবহার |
|--------|-----------|-----|
| **Dummy** | পাঠানো হয় কিন্তু কখনো ব্যবহার হয় না | একটা parameter পূরণ করা |
| **Stub** | বাঁধা উত্তর দেয় | "ভেন্ডর ০.৯ score দেয়" |
| **Spy** | কী হলো লিপিবদ্ধ করে | "ইমেইলটা কি পাঠানো হয়েছিল?" |
| **Mock** | প্রত্যাশা সহ আগে থেকে প্রোগ্রাম করা; না মিটলে fail করে | একটা মিথস্ক্রিয়া যাচাই করা |
| **Fake** ⭐ | একটা কাজ করা, সরলীকৃত implementation | `InMemoryRepository`, in-memory queue |

> **Mock-এর চেয়ে fake-কে প্রাধান্য দিন।** একটা `InMemorySessionRepository` একবার লেখা হয়, একশটা test-এ ব্যবহার হয়, আসল আচরণ test করে, আর আপনি refactor করলে ভাঙে না। Mock-ভারী test গঠনগতভাবেই ভঙ্গুর আর এগুলোই মানুষের নিজের test-suite-কে ঘৃণা করার প্রধান কারণ।
>
> **শুধু সেই সীমানায় mock করুন যেগুলোর মালিক আপনি নন** — আর সেখানেও HTTP client-এর একটা mock-এর চেয়ে port-এর একটা fake (অধ্যায় ০২) সাধারণত ভালো।

---

## ২১.৪ Integration test 🟢

**সংজ্ঞা:** যে test যাচাই করে component গুলো আসল infrastructure-এর সাথে একসাথে কাজ করে — একটা আসল database, একটা আসল queue, একটা আসল cache।

### Testcontainers — যে কৌশলটা এটা বদলে দিয়েছে ⭐

```python
import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("postgres:16-alpine") as pg:   # আসল Postgres 16
        run_migrations(pg.get_connection_url())
        yield pg

async def test_expired_sessions_query_returns_only_expired(postgres, db):
    await db.execute(INSERT_SESSION, id="s1", created_at=hours_ago(2), status="pending")
    await db.execute(INSERT_SESSION, id="s2", created_at=minutes_ago(5), status="pending")
    await db.execute(INSERT_SESSION, id="s3", created_at=hours_ago(3), status="passed")

    repo = PostgresSessionRepository(db)
    expired = await repo.get_expired(before=minutes_ago(15))

    assert [s.id for s in expired] == ["s1"]     # s2 নয় (খুব সাম্প্রতিক), s3 নয় (শেষ হয়ে গেছে)
```

**এটা কেন এত গুরুত্বপূর্ণ:** in-memory-database-এর শর্টকাট (Postgres-এর জায়গায় SQLite) একটা ফাঁদ। এর আলাদা SQL dialect, আলাদা type সামলানো, আলাদা transaction semantics, আলাদা NULL-ক্রম, আর কোনো JSONB, array, RLS বা partial index নেই। **Test পাস করে, production ভাঙে।** Testcontainers আপনাকে আসল engine, আসল dialect, আর আসল আচরণ দেয়, প্রায় দুই সেকেন্ডের startup-এ।

### কী integration-test করবেন

```
✅ একটা আসল database-এর বিপরীতে repository-র query (বিশেষত জটিল SQL)
✅ Database-এর migration (আসল data-র আকৃতিতে সামনের দিকে চালান)
✅ Transaction আর concurrency-র আচরণ (optimistic locking, deadlock সামলানো)
✅ Message publish আর গ্রহণ, retry আর DLQ-র পথ সহ
✅ Cache-এর মিথস্ক্রিয়া, cache-miss-এর পথ সহ
✅ HTTP স্তর: routing, serialisation, যাচাই, auth middleware
✅ ⭐ Tenant-এর বিচ্ছিন্নতা (অধ্যায় ১৭) — tenant A-কে tenant B-র resource-এ ৪০৪ পেতে হবে
```

শেষেরটা একটা নিবেদিত, স্বয়ংক্রিয় test-শ্রেণির যোগ্য। এটা multi-tenant SaaS-এর সবচেয়ে বেশি প্রভাবের bug-শ্রেণিটা ধরে।

```python
@pytest.mark.parametrize("path", ["/v1/sessions/{id}", "/v1/sessions/{id}/attempts",
                                  "/v1/customers/{id}"])
async def test_cross_tenant_access_returns_404(client, tenant_a_token, tenant_b_resource, path):
    res = await client.get(path.format(id=tenant_b_resource.id),
                           headers={"Authorization": f"Bearer {tenant_a_token}"})
    assert res.status_code == 404          # ৪০৩ নয় — অস্তিত্ব ফাঁস করবেন না
```

### Test-data ব্যবস্থাপনা

| পদ্ধতি | Trade-off |
|----------|-----------|
| **প্রতি test-এ নতুন database** | নিখুঁত বিচ্ছিন্নতা; ধীর |
| **প্রতি test-এ transaction rollback** ⭐ | দ্রুত আর বিচ্ছিন্ন — **সাধারণত সেরা পছন্দ** |
| **Test-এর মাঝে truncate** | দ্রুত; table-এর ক্রম ঠিক রাখতে হবে |
| **ভাগ করা seed data** | দ্রুততম; test coupled আর ক্রম-নির্ভর হয়ে যায় |

**Builder ব্যবহার করুন, জাদুকরী মান ভরা fixture নয়:**

```python
# ❌ এখানে কোনটা গুরুত্বপূর্ণ? সবকিছু সমান গুরুত্বপূর্ণ লাগে।
session = Session("s1", "t1", "c1", "pending", 0.0, 0, datetime(2026,1,1), None, "active")

# ✅ শুধু প্রাসঙ্গিক বিবরণ দৃশ্যমান; বাকি সব একটা যুক্তিসঙ্গত default
session = a_session().for_tenant("t1").with_score(0.82).pending().build()
```

Builder প্রতিটা test-এর *উদ্দেশ্য* স্পষ্ট করে, আর একটা নতুন required field যোগ করলে ২০০টা test ভাঙে না।

---

## ২১.৫ Contract testing ⭐ 🟢

**এটা যে সমস্যা সমাধান করে সেটা distributed system-এর নিজস্ব, আর এটা একটা আসল সমস্যা।**

```
Service A, Service B-কে call করে।

A-র unit test:   B mock করা → pass
B-র unit test:   pass
দুটোই deploy হলো।  💥 B তিন সপ্তাহ আগে একটা field-এর নাম বদলেছিল।
                     A-র mock এখনো পুরনো আকৃতি ফেরত দেয়।
                     Production-এর আগে কেউ জানল না।
```

Mock-টা B সম্পর্কে A-র *বিশ্বাস* ধারণ করে। বিশ্বাসটা এখনো সত্যি কিনা কিছুই যাচাই করে না।

**E2E test এটা ধরত — কিন্তু সেগুলো ধীর, flaky, আর প্রতিটা service চালানো লাগে।** Contract testing এটা প্রতিটা service-এর নিজের দ্রুত pipeline-এই ধরে।

### Consumer-driven contract testing (Pact)

```
১. CONSUMER (A) একটা test লেখে যেখানে ঘোষণা করে B-র কাছ থেকে তার কী লাগে।
   → এটা একটা CONTRACT ফাইল (একটা pact) তৈরি করে

২. Contract-টা একটা broker-এ প্রকাশিত হয়।

৩. PROVIDER (B) তার নিজের pipeline-এ তার আসল implementation-এর বিপরীতে contract চালায়।
   → B contract ভাঙলে B-র build fail করে — deployment-এর আগেই
```

```javascript
// CONSUMER-এর দিক: "আমার এই field গুলো, এই আকৃতিতে লাগে"
await provider.addInteraction({
  state: 'a completed verification session ses_881 exists',
  uponReceiving: 'a request for a session',
  withRequest:  { method: 'GET', path: '/v1/sessions/ses_881' },
  willRespondWith: {
    status: 200,
    body: {
      id:     Matchers.like('ses_881'),
      status: Matchers.term({ matcher: 'passed|failed|review', generate: 'passed' }),
      score:  Matchers.decimal(0.94),
      // খেয়াল করুন: consumer শুধু সেই field ঘোষণা করে যেগুলো সে ব্যবহার করে।
      // Provider অবাধে আরও field যোগ করতে পারে — এটাই tolerant reader (অধ্যায় ০৮)।
    },
  },
});
```

```java
// PROVIDER-এর দিক, B-র pipeline-এ: আসল service প্রতিটা contract মেটায় কিনা যাচাই করুন
@Provider("verification-api")
@PactBroker(url = "https://pact-broker.internal")
class ContractVerificationTest {
    @State("a completed verification session ses_881 exists")
    void seedSession() { repository.save(passedSession("ses_881")); }
}
```

**"Consumer-driven" কেন সঠিক আকৃতি:** এটা নথিভুক্ত করে *আসলে কী ব্যবহৃত হয়*। কোনো consumer-এর contract-এ যদি একটা field উল্লেখ না থাকে, তাহলে আপনি সেটা নিরাপদে মুছতে পারেন — একটা microservices পরিবেশে এই প্রশ্নের উত্তর দেওয়া অন্যথায় অসম্ভব।

**Can-I-Deploy** হলো ব্যবহারিক প্রতিদান: deploy করার আগে broker উত্তর দেয় *"এই সংস্করণ কি এখন deploy থাকা সবকিছুর সাথে compatible?"* এটা সমন্বিত release-পরিকল্পনাকে একটা স্বয়ংক্রিয় যাচাইয়ে পরিণত করে।

### Schema-ভিত্তিক contract testing (সহজ, আর প্রায়ই যথেষ্ট)

API-র জন্য: **CI-তে OpenAPI diffing** (অধ্যায় ০৮)।

```bash
oasdiff breaking main-spec.yaml pr-spec.yaml --fail-on ERR
```

Event-এর জন্য: **schema registry-র compatibility যাচাই** (অধ্যায় ০৬)।

> **এখান থেকে শুরু করুন।** Schema diffing এক লাইনের একটা CI ধাপ আর বেশিরভাগ ভাঙন ধরে। যখন "আসলে কী ব্যবহৃত হয়" — এই সূক্ষ্মতর প্রশ্নটা লাগবে তখন Pact যোগ করুন — সাধারণত ১০+ service-এ।

---

## ২১.৬ End-to-end test 🟡

**সংজ্ঞা:** পুরো সিস্টেম, আসল ব্যবহারকারী-interface দিয়ে, আসল dependency সহ।

### এগুলো কম আর ইচ্ছাকৃতভাবে ব্যবহার করুন

```
✅ শুধু ৫-১০টা গুরুত্বপূর্ণ ব্যবহারকারী-যাত্রা ঢাকুন
   - sign up আর log in
   - শুরু থেকে শেষ পর্যন্ত একটা verification সম্পন্ন
   - একজন reviewer একটা চিহ্নিত session অনুমোদন করেন
   - Billing একটা সঠিক invoice তৈরি করে

❌ প্রতিটা field-যাচাই, প্রতিটা error message, প্রতিটা প্রান্তিক ক্ষেত্র E2E-test করবেন না।
   ওগুলো unit আর integration test-এর জিনিস।
```

**সংযমটা কেন:** E2E test ধীর (মিনিট), ভঙ্গুর (একটা CSS পরিবর্তন এগুলো ভাঙে), রক্ষণাবেক্ষণে ব্যয়বহুল, আর fail করলে এগুলো খুব কমই বলে *কী* ভাঙল। ৪০০টা E2E test-এর একটা suite এমন একটা suite হয়ে যায় যা সবাই উপেক্ষা করে কারণ এটা "সম্ভবত শুধু flaky" — আর তখনই এটা আপনাকে রক্ষা করা বন্ধ করে।

### E2E test-কে টেকসই করা

```javascript
// ❌ ভঙ্গুর: styling পরিবর্তনে ভাঙে
await page.click('.btn-primary.mt-4 > span:nth-child(2)');

// ✅ মজবুত: অর্থবহ আর উদ্দেশ্যমূলক
await page.getByRole('button', { name: 'Start verification' }).click();
await page.getByTestId('verification-result').waitFor();
```

```
১. অর্থবহ বা স্পষ্ট test-id selector ব্যবহার করুন — কখনো CSS-এর কাঠামো নয়
২. স্বয়ংক্রিয় অপেক্ষা, কখনো নির্দিষ্ট sleep নয় (Playwright/Cypress এটা ঠিকভাবে করে)
৩. প্রতিটা test নিজের data বানায় আর পরিষ্কার করে — কোনো ভাগ করা fixture নয়
৪. জানা অবস্থা সহ একটা নিবেদিত পরিবেশের বিপরীতে চালান
৫. Flaky test সাথে সাথে আলাদা করুন — একটা flaky E2E suite না থাকার চেয়ে খারাপ
৬. ব্যর্থতায় video/trace রেকর্ড করুন — অন্ধভাবে debug করা অসহনীয়
৭. পূর্ণ suite একটা সময়সূচিতে আর release-এর আগে চালান; প্রতি PR-এ একটা দ্রুত উপসেট
```

### Production-এ testing ⭐

কিছু জিনিস release-এর আগে যাচাই করাই যায় না। আধুনিক পদ্ধতি এটা মেনে নেয় আর production-এর যাচাইকে নিরাপদ করে:

| কৌশল | কী দেয় |
|-----------|--------------|
| **Synthetic monitoring** | গুরুত্বপূর্ণ যাত্রা প্রতি মিনিটে বাইরে থেকে চলে (অধ্যায় ১৯) |
| **Canary release** | আসল traffic, সীমিত blast radius (অধ্যায় ১৫) |
| **Feature flag** | আগে ভেতরের ব্যবহারকারীদের জন্য চালু, তারপর ১% |
| **Shadow traffic** | আসল request-এর একটা কপি নতুন সংস্করণে পাঠান, ফলাফল তুলনা করুন, output ফেলে দিন |
| **Deploy-এর পরে smoke test** | Release-এর সাথে সাথেই মুষ্টিমেয় কয়েকটা দাবি |

> **Shadow traffic কম ব্যবহৃত আর অত্যন্ত শক্তিশালী**, যখন একটা গুরুত্বপূর্ণ component বদলাচ্ছেন — একটা নতুন scoring model, একটা নতুন query implementation, একটা নতুন করে লেখা service। আপনি **শূন্য** ব্যবহারকারী-ঝুঁকিতে production-মাপের যাচাই পান, কারণ shadow-এর output কখনো ফেরত দেওয়া হয় না। একটা liveness engine-এর model upgrade-এ আত্মবিশ্বাস পাওয়ার এটাই সঠিক উপায়।

---

## ২১.৭ জানার মতো অন্য test-ধরন 🟡

### Component testing

একটা service বিচ্ছিন্নভাবে, তার আসল database সহ কিন্তু **সব বাইরের service stub করা** (WireMock, MockServer, বা একটা স্থানীয় fake)।

```
[ পরীক্ষাধীন Service ] ── আসল ──► [ container-এ Postgres, Redis ]
                       ── stub ──► [ ভেন্ডরের API, অন্য service ]
```

একটা microservices architecture-এ এটা প্রায়ই **সেরা মূল্যের স্তর**: এটা পুরো service চালায় — HTTP স্তর, business logic, persistence, error handling — বাকি পরিবেশ চালানোর দরকার ছাড়াই। E2E-র চেয়ে দ্রুত আর অনেক বেশি স্থিতিশীল, প্রায় সমান আত্মবিশ্বাস সহ।

### Performance testing

অধ্যায় ২০। Load, stress, soak, spike। **CI-তে একটা performance বাজেট যাচাই রাখুন।**

### Security testing

| ধরন | কী করে | কখন |
|------|-------------|------|
| **SAST** | Source-এর static বিশ্লেষণ | প্রতিটা PR |
| **SCA** | Dependency-র দুর্বলতা scan | প্রতিটা PR + দৈনিক |
| **Secret scanning** | কোডে credential | প্রতিটা PR + pre-commit |
| **Container scanning** | Image-এর CVE | প্রতিটা build |
| **DAST** | চলমান app-এ আক্রমণ | রাতে / release-এর আগে |
| **IaC scanning** | অনিরাপদ infrastructure config | প্রতিটা PR |
| **Penetration test** | মানুষ আক্রমণ করে | বছরে একবার, আর বড় launch-এর আগে |

**সাথে যেগুলো আপনাকেই লিখতে হবে সেই architecture-নির্দিষ্ট test:** cross-tenant বিচ্ছিন্নতার test, authorisation-matrix test (প্রতিটা role × প্রতিটা endpoint), আর IDOR test। স্বয়ংক্রিয় টুল এগুলো খুঁজে পাবে না — এগুলোর জন্য আপনার domain-এর জ্ঞান লাগে।

### Mutation testing ⚪

আপনার কোডে ইচ্ছাকৃতভাবে bug (mutation) ঢোকায় আর দেখে আপনার test সেগুলো ধরে কিনা।

```python
if score > 0.85:        # মূল
if score >= 0.85:       # mutant — আপনার test কি fail করে?
if score < 0.85:        # mutant — আপনার test কি fail করে?
```

**এটা আপনার test-কে test করে।** অর্থহীন দাবি করা test সহ ৯০% line coverage mutation testing-এ ভয়ানক স্কোর করবে — আর ঠিক এই কাজের তথ্যটাই coverage দিতে পারে না। চালাতে ধীর, তাই আপনার সবচেয়ে গুরুত্বপূর্ণ module-এ (pricing, scoring, permission) পর্যায়ক্রমে ব্যবহার করুন, সবকিছুতে নয়।

### Property-based testing ⚪🟡

নির্দিষ্ট উদাহরণের বদলে এমন একটা **বৈশিষ্ট্য** বলুন যা সবসময় সত্য হতে হবে, আর framework-কে শত শত input তৈরি করে এটা ভাঙার চেষ্টা করতে দিন।

```python
from hypothesis import given, strategies as st

@given(st.decimals(min_value=0, max_value=1, places=3))
def test_score_band_is_always_defined(score):
    assert LivenessScore(score).band in Confidence     # কখনো crash নয়, কখনো None নয়

@given(st.lists(st.builds(Money, st.decimals(min_value=0, max_value=10000), st.just("USD"))))
def test_sum_is_order_independent(amounts):
    assert sum_money(amounts) == sum_money(list(reversed(amounts)))
```

**এটা সেই প্রান্তিক ক্ষেত্রগুলো খুঁজে পায় যেগুলোর কথা আপনি ভাবেননি** — খালি তালিকা, শূন্য, সীমার মান, Unicode-এর অদ্ভুততা, নির্ভুলতার ত্রুটি। Parser, serialiser, হিসাব, আর invariant আছে এমন যা কিছুর জন্য চমৎকার। একটা ব্যর্থতা পেলে এটা স্বয়ংক্রিয়ভাবে input-টা ন্যূনতম পুনরুৎপাদক ক্ষেত্রে সংকুচিত করে, যেটা সত্যিই আনন্দদায়ক।

---

## ২১.৮ কঠিন জিনিসগুলো test করা

### সময়

```python
# ❌ Test-অযোগ্য আর flaky
class Session:
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at

# ✅ Clock inject করুন
class Session:
    def is_expired(self, now: datetime) -> bool:
        return now > self.expires_at

# এখন: session.is_expired(একটা নির্দিষ্ট মুহূর্ত) — deterministic, কোনো ঘুম নেই, কোনো জমানো নেই
```

> **Business logic-এর গভীরে কখনো `datetime.now()` call করবেন না।** প্রান্ত থেকে সময় পাঠান। এই একটা অভ্যাস আস্ত একটা শ্রেণির flaky test দূর করে আর "সীমানায় কী হয়?" তুচ্ছভাবে test-যোগ্য করে।

### এলোমেলোতা

Random-এর উৎস inject করুন, বা seed দিন। সময়ের মতোই একই নীতি।

### Asynchrony আর eventual consistency

```python
# ❌ Flaky: কখনো ১০০ ms যথেষ্ট, কখনো নয়
await publish(event)
await asyncio.sleep(0.1)
assert await projection.get("s1") is not None

# ✅ একটা timeout সহ poll করুন — deterministic ফলাফল, কাজ করলে দ্রুত
async def eventually(check, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return await check()
        except AssertionError as e:
            last = e
            await asyncio.sleep(interval)
    raise last

await publish(event)
await eventually(lambda: assert_projection_updated("s1"))
```

**একটা test-এ `sleep()` প্রায় সবসময়ই একটা bug।** এটা হয় খুব ছোট (flaky) নয় খুব লম্বা (ধীর) — সাধারণত দুটোই, আলাদা মেশিনে।

### বাইরের ভেন্ডর

```
১. Unit আর component test-এ FAKE (আপনার port-এর একটা স্থানীয় implementation)
২. Integration test-এ রেকর্ড করা response (VCR/cassette)
৩. অল্প কয়েকটা contract test-এ তাদের SANDBOX, একটা সময়সূচিতে চালানো
৪. ⭐ ব্যর্থতার রূপগুলো স্পষ্টভাবে test করুন: timeout, ৫০০, ৪২৯, বিকৃত response,
   ধীর response, আর connection reset। এগুলোই সেই পথ যা production-এ ভাঙে
   আর এগুলোই প্রায় কখনো test করা হয় না।
```

> যেহেতু আপনি প্রতিটা ভেন্ডরের সামনে একটা **Anti-Corruption Layer** বসিয়েছেন (অধ্যায় ০৩), এই সবই সহজ: ACL-এর implementation বদলান। একটা ACL ছাড়া ভেন্ডর test করা দুর্বিষহ — pattern-টার পক্ষে এটা আরেকটা যুক্তি।

---

## ২১.৯ Coverage — ঠিকভাবে ব্যবহার করুন

**Coverage মাপে কোন লাইন চলেছে, আচরণ সঠিক কিনা নয়।**

```python
def calculate_discount(order, customer):
    if customer.tier == "gold":
        return order.total * Decimal("0.20")
    return Decimal("0")

def test_discount():
    calculate_discount(gold_order(), gold_customer())   # ১০০% line coverage
    # ...আর কোনো দাবি নেই। Function আবর্জনা ফেরত দিলেও test পাস করে।
```

**Coverage যুক্তিসঙ্গতভাবে কীভাবে ব্যবহার করবেন:**

```
✅ অপরীক্ষিত কোড খুঁজতে ব্যবহার করুন — "এই পুরো error-পথটা কখনো চলেইনি"
✅ ক্ষয় ঠেকাতে একটা মেঝে (৭০-৮০%) বসান, আর CI-তে এতে gate দিন
✅ গুরুত্বপূর্ণ module-এ (payment, auth, scoring) বেশি coverage দাবি করুন
✅ শুধু line নয়, BRANCH coverage দেখুন
❌ ১০০%-এর পেছনে ছুটবেন না — শেষ ১৫% সাধারণত রক্ষণাত্মক কোড আর generate করা কোড
❌ এটাকে মানের পরিমাপ ভাববেন না — এটা চলা মাপে, যাচাই নয়
```

> **"আমাদের coverage কত?"-এর চেয়ে বেশি কাজের প্রশ্ন: "আমি যদি ইচ্ছাকৃতভাবে এই business rule-টা ভাঙি, তাহলে কি একটা test fail করবে?"** এটাই mutation testing-এর প্রশ্ন, আর এটাই আসলে গুরুত্বপূর্ণ।

---

## ২১.১০ একটা distributed system-এর test-কৌশল

```
প্রতি service-এ (দ্রুত, প্রতিটা service-এর নিজের pipeline-এ):
  ├── Unit test          — domain logic, কোনো I/O নেই              সেকেন্ড
  ├── Integration test   — Testcontainers দিয়ে আসল DB/queue        ১-২ মিনিট
  ├── Component test     — পুরো service, বাইরেরগুলো stub করা         ২-৩ মিনিট
  └── Contract test      — consumer + provider যাচাই                সেকেন্ড

Service-জুড়ে (ধীর, কম ঘন ঘন):
  ├── E2E test           — শুধু ৫-১০টা গুরুত্বপূর্ণ যাত্রা             ১০-২০ মিনিট
  ├── Performance test   — load, আর বড় release-এর আগে soak        ঘণ্টা
  └── Security scan      — SAST/SCA/DAST                          মিনিট থেকে ঘণ্টা

Production-এ:
  ├── Synthetic monitoring — গুরুত্বপূর্ণ যাত্রা, প্রতি মিনিটে
  ├── Canary + feature flag
  ├── Shadow traffic       — ঝুঁকিপূর্ণ component প্রতিস্থাপনে
  └── Smoke test           — প্রতিটা deploy-এর সাথে সাথেই
```

**মূল কাঠামোগত অন্তর্দৃষ্টি: contract test বেশিরভাগ cross-service E2E test প্রতিস্থাপন করে।** প্রতিটা service তার নিজের দ্রুত pipeline-এ তার contract যাচাই করে, তাই integration এখনো কাজ করে জানতে আপনার আর পুরো পরিবেশ দাঁড় করাতে হয় না। এটাই স্বাধীন deployment-কে (অধ্যায় ০২) নামমাত্র নয়, সত্যিকারে সম্ভব করে।

---

## ২১.১১ সাধারণ ভুল

১. **আচরণের বদলে implementation test করা** — ভঙ্গুর test যা প্রতিটা refactor-এ ভাঙে
২. **Mock-ভারী unit test** — এগুলো test করে যে আপনার কোড আপনার কোড call করে
৩. **Postgres-এর জায়গায় SQLite** — আলাদা dialect, আলাদা semantics, মিথ্যা আত্মবিশ্বাস
৪. **Ice cream cone** — বেশিরভাগ E2E আর manual testing; ধীর, flaky, ব্যয়বহুল
৫. **Flaky test সহ্য করা** — টিম লাল উপেক্ষা করতে শেখে, আর CI কিছুই রক্ষা করা বন্ধ করে
৬. **Test-এ `sleep()`** — ধীর মেশিনে flaky, দ্রুত মেশিনে ধীর
৭. **Business logic-এ `datetime.now()`** — test-অযোগ্য, সময়-নির্ভর ব্যর্থতা
৮. **ভাগ করা mutable test-data** — ক্রম-নির্ভর ব্যর্থতা যা শুধু CI-তে আসে
৯. **১০০% coverage-এর পেছনে ছোটা** — তুচ্ছ জিনিসে পরিশ্রম, আর error-পথ অপরীক্ষিত
১০. **Service-এর মধ্যে কোনো contract test নেই** — integration-এর ভাঙন production-এ ধরা পড়ে
১১. **কখনো ব্যর্থতার পথ test না করা** — বেশিরভাগ codebase-এ timeout, ৫০০, retry আর fallback অপরীক্ষিত, আর ঠিক এগুলোই একটা incident-এ চলে
১২. **কোনো cross-tenant বিচ্ছিন্নতার test নেই** — সবচেয়ে বেশি প্রভাবের multi-tenant bug অরক্ষিত
১৩. **ধীর test-suite** — ~১০ মিনিটের বেশি হলে ডেভেলপাররা স্থানীয়ভাবে চালানো বন্ধ করেন
১৪. **শুধু সুখী পথ test করা** — দুঃখী পথগুলোতেই টাকা হারায়

---

## ২১.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] Domain logic **কোনো** infrastructure ছাড়াই test-যোগ্য (একটা ভালো design-এর কাঠামোগত পরীক্ষা)
- [ ] Test-কৌশল নথিভুক্ত: কোন স্তরে কী test হয়, আর কেন
- [ ] Unit suite এক মিনিটের নিচে চলে
- [ ] পূর্ণ PR pipeline ১০ মিনিটের নিচে (অধ্যায় ১৬)
- [ ] Integration test Testcontainers দিয়ে **আসল** infrastructure ব্যবহার করে
- [ ] Mock-এর চেয়ে fake-কে প্রাধান্য; fixture-গুচ্ছের চেয়ে builder-কে প্রাধান্য
- [ ] প্রতিটা service-জোড়ার মধ্যে contract test (বা অন্তত OpenAPI/schema diffing)
- [ ] E2E ৫–১০টা গুরুত্বপূর্ণ যাত্রায় সীমিত, মজবুত selector সহ
- [ ] ব্যর্থতার পথ test করা: timeout, ৫xx, ৪২৯, বিকৃত response, retry, DLQ
- [ ] প্রতিটা resource-ধরনের জন্য cross-tenant বিচ্ছিন্নতার test
- [ ] Authorisation-matrix test: প্রতিটা role × প্রতিটা endpoint
- [ ] সময়, এলোমেলোতা আর ID inject করা, কখনো business logic-এর ভেতর থেকে call নয়
- [ ] Eventual consistency polling দিয়ে test করা, কখনো `sleep` দিয়ে নয়
- [ ] CI-তে coverage-এর মেঝে বলবৎ; গুরুত্বপূর্ণ module-এ বেশি; branch coverage track করা
- [ ] সবচেয়ে গুরুত্বপূর্ণ module-এ পর্যায়ক্রমে mutation testing চালানো
- [ ] Flaky test সাথে সাথে আলাদা করা আর ঠিক বা মুছে ফেলা
- [ ] Pipeline-এ performance বাজেট আর security scan
- [ ] Production-এ synthetic monitoring আর deploy-পরবর্তী smoke test

---

## ২১.১৩ নিজেকে যাচাই

১. Testability কেন একটা architecture-গত বৈশিষ্ট্য? এটা নির্ধারণ করে এমন তিনটা design-পছন্দ দিন।
২. Test-এর আসল উদ্দেশ্য কী, আর একটা codebase-এর জন্য "অপরীক্ষিত" আসলে কী মানে?
৩. একটা ব্যর্থ E2E test-এর চেয়ে একটা ব্যর্থ unit test কেন বেশি সাহায্য করে?
৪. পিরামিডের "testing trophy" সমালোচনাটা কী, আর বাস্তববাদী সমন্বয়টা কী?
৫. Mock-ভারী test কেন ভঙ্গুর? একটাকে আচরণ test করার জন্য আবার লিখুন।
৬. Mock-এর চেয়ে fake কেন প্রাধান্য পাবে? একটা উদাহরণ দিন।
৭. Postgres-এর জায়গায় SQLite কেন একটা ফাঁদ? চারটা নির্দিষ্ট পার্থক্য বলুন।
৮. Consumer-driven contract testing ব্যাখ্যা করুন। এটা এমন কোন প্রশ্নের উত্তর দিতে পারে যা আর কিছু পারে না?
৯. Contract test কীভাবে বেশিরভাগ cross-service E2E test প্রতিস্থাপন করে, আর deployability-র জন্য সেটা কেন গুরুত্বপূর্ণ?
১০. Shadow traffic কী আর কখন এটা সঠিক কৌশল?
১১. Business logic-এ `datetime.now()` কেন কখনো থাকা উচিত নয়?
১২. একটা test-এ `sleep()` প্রায় সবসময় একটা bug কেন? এর বদলে কী?
১৩. Coverage কী মাপে, আর কী মাপে না? ভালো প্রশ্নটা কী?
১৪. Mutation testing কী আর এটা এমন কী প্রকাশ করে যা coverage পারে না?
১৫. প্রায় কখনো test হয় না কিন্তু একটা incident-এ সবসময় চলে — এমন চারটা ব্যর্থতার পথ বলুন।

---

## ২১.১৪ মূল কথাগুলো

- **Test-এর অস্তিত্ব যাতে আপনি ভয় ছাড়া সিস্টেম বদলাতে পারেন।** কোনো test নেই = জমে যাওয়া সিস্টেম।
- **যন্ত্রণাদায়ক test একটা design-এর আবিষ্কার**, testing-এর নয় — seam গুলো ঠিক করুন
- **আচরণ test করুন, implementation নয়**, আর সবচেয়ে দ্রুত যে স্তরে যাচাই করা যায় সেখানে
- **Mock-এর চেয়ে fake-কে প্রাধান্য দিন।** Mock-ভারী test refactor-এ ভাঙে আর কমই ধরে।
- **Testcontainers দিয়ে আসল infrastructure ব্যবহার করুন** — Postgres-এর জায়গায় SQLite মিথ্যা আত্মবিশ্বাস দেয়
- **Contract testing মূল distributed-systems কৌশল** — এটা বেশিরভাগ cross-service E2E test প্রতিস্থাপন করে আর স্বাধীন deployment-কে সত্যিকারের করে
- **শুধু ৫–১০টা গুরুত্বপূর্ণ যাত্রায় E2E**, অর্থবহ selector আর flakiness-এ শূন্য সহনশীলতা সহ
- **ব্যর্থতার পথ test করুন** — timeout, ৫xx, retry, DLQ। Incident-এ এগুলোই চলে।
- **Cross-tenant বিচ্ছিন্নতার test automate করুন** — সবচেয়ে বেশি প্রভাবের multi-tenant bug-শ্রেণি
- **সময়, এলোমেলোতা আর ID inject করুন।** Eventual consistency-তে poll করুন; কখনো sleep নয়।
- **Coverage অপরীক্ষিত কোড খুঁজে দেয়; এটা মান মাপে না।** Mutation testing আপনার test-কে test করে।
- **একটা flaky suite কোনো suite না থাকার চেয়ে খারাপ** — এটা টিমকে ব্যর্থতা উপেক্ষা করতে শেখায়

---

**পরবর্তী:** [অধ্যায় ২২ — Architecture Documentation](22-architecture-documentation.md)

**ইংরেজি সংস্করণ:** [Chapter 21](../21-testing-architecture.md) · **[সূচিপত্র](README.md)**
