# Chapter 21 — Testing Architecture 🟡

> Tests are not about finding bugs. Tests are about **being able to change the system without fear**.
>
> A codebase with no tests is not "untested" — it is **frozen**. Every change is a gamble, so changes get rarer, batches get bigger, and each release gets more dangerous. Testing is therefore a *deployability* concern, which makes it an architecture concern (Chapter 16).

---

## 21.1 Why testing is architecture

**Testability is a quality attribute** (Chapter 00), and it is determined by structure, not by effort:

| Architecture choice | Testing consequence |
|--------------------|--------------------|
| Business logic mixed with I/O | Cannot test rules without a database and a network |
| Dependencies constructed inside classes (`new SqlConnection()`) | No seam to substitute; must test against real infrastructure |
| Static/global state | Tests leak into each other; order-dependent failures |
| Domain layer free of frameworks (Chapter 02) | Rules test in **microseconds**, with no setup |
| Ports and adapters | In-memory adapters test the whole application logic |
| Services owning their data | Can be tested independently |
| Shared database between services | Every test needs the whole system running |

> **If your tests are slow, painful and flaky, that is a design finding, not a testing finding.** The usual root cause is that business logic cannot be reached without infrastructure. Fix the seams (Chapter 01 DIP, Chapter 02 hexagonal) and the tests become fast and pleasant almost automatically.

---

## 21.2 The test pyramid — and its honest critique

```
                    ╱╲
                   ╱E2E╲          few:  slow, brittle, expensive, high confidence
                  ╱──────╲
                 ╱ INTEG  ╲       some: medium speed, real infrastructure
                ╱──────────╲
               ╱    UNIT    ╲     many: milliseconds, no I/O, pinpoint failures
              ╱──────────────╲
```

**The reasoning behind the shape:**

| Level | Speed | Cost | Confidence | Failure diagnosis |
|-------|-------|------|-----------|-------------------|
| Unit | µs–ms | Very low | Narrow | **Points at the exact function** |
| Integration | 10 ms–1 s | Medium | Real | Points at a component |
| E2E | 10 s–minutes | High | Highest | *"Something broke somewhere"* |

The last column matters more than people realise: **a failing unit test tells you what to fix; a failing E2E test tells you to start investigating.**

### The honest critiques

**1. The "testing trophy" argument (Kent C. Dodds):** integration tests give the best confidence-per-effort in many modern codebases, because most real bugs live in the *wiring between* components, not inside a single function. With fast tooling (Testcontainers, in-memory databases), integration tests are no longer prohibitively slow.

**2. The "ice cream cone" anti-pattern** — lots of manual and E2E tests, few unit tests. This is what happens by default when nobody designs the strategy. It is slow, flaky, and expensive.

**3. Testing implementation details** — a unit test that mocks everything and asserts that `repository.save()` was called tests *your code's structure*, not its behaviour. It breaks on every refactor and catches no real bugs. This is the most common way test suites become a liability rather than an asset.

> **The pragmatic position:** shape matters less than these two rules —
> **(a) test *behaviour*, not implementation**, and
> **(b) push each test to the fastest level that can genuinely verify the behaviour.**

---

## 21.3 Unit tests 🟢

**Definition:** tests one unit of behaviour in isolation, with no I/O.

**What "unit" means is contested; the useful definition is "one behaviour", not "one class".** A test that exercises three collaborating classes with no I/O is still a fast, valuable unit test.

```python
# Pure domain logic — no database, no network, no mocks needed at all.
# This is what a clean domain layer buys you (Chapters 02, 03).
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

Those tests run in **microseconds**, need no setup, and describe the business rules so clearly that a compliance officer could read them.

### The characteristics of a good unit test (FIRST)

| Property | Meaning |
|----------|---------|
| **F**ast | Milliseconds. The whole suite in under a minute. |
| **I**solated | No shared state; any order; parallel-safe |
| **R**epeatable | Same result every run, on every machine, forever |
| **S**elf-validating | Passes or fails — no human reading output |
| **T**imely | Written with the code, not "later" |

### Test behaviour, not implementation

```python
# ❌ Tests implementation — breaks on any refactor, catches no real bug
def test_approve():
    repo = Mock()
    svc = Service(repo)
    svc.approve("s1")
    repo.get.assert_called_once_with("s1")          # who cares?
    repo.save.assert_called_once()                  # who cares?

# ✅ Tests behaviour — survives refactoring, catches real bugs
def test_approving_a_session_records_the_reviewer_and_marks_it_approved():
    repo = InMemorySessionRepository(seed=[pending_session("s1")])
    svc = Service(repo)

    svc.approve("s1", reviewer_id="r9")

    stored = repo.get("s1")
    assert stored.status is SessionStatus.APPROVED
    assert stored.reviewed_by == "r9"
```

The second version would survive replacing the repository, changing the ORM, or restructuring the service — and it would fail if the behaviour broke. That is the whole point.

### Test doubles — know the difference

| Double | Behaviour | Use |
|--------|-----------|-----|
| **Dummy** | Passed but never used | Filling a parameter |
| **Stub** | Returns canned answers | "The vendor returns score 0.9" |
| **Spy** | Records what happened | "Was the email sent?" |
| **Mock** | Pre-programmed with expectations; fails if not met | Verifying an interaction |
| **Fake** ⭐ | A working, simplified implementation | `InMemoryRepository`, in-memory queue |

> **Prefer fakes over mocks.** A `InMemorySessionRepository` is written once, used in a hundred tests, tests real behaviour, and does not break when you refactor. Mock-heavy tests are brittle by construction and are the main reason people come to hate their test suite.
>
> **Mock only at the boundaries you do not own** — and even there, a fake of the port (Chapter 02) is usually better than a mock of the HTTP client.

---

## 21.4 Integration tests 🟢

**Definition:** tests that components work together with real infrastructure — a real database, a real queue, a real cache.

### Testcontainers — the technique that changed this ⭐

```python
import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("postgres:16-alpine") as pg:   # REAL Postgres 16
        run_migrations(pg.get_connection_url())
        yield pg

async def test_expired_sessions_query_returns_only_expired(postgres, db):
    await db.execute(INSERT_SESSION, id="s1", created_at=hours_ago(2), status="pending")
    await db.execute(INSERT_SESSION, id="s2", created_at=minutes_ago(5), status="pending")
    await db.execute(INSERT_SESSION, id="s3", created_at=hours_ago(3), status="passed")

    repo = PostgresSessionRepository(db)
    expired = await repo.get_expired(before=minutes_ago(15))

    assert [s.id for s in expired] == ["s1"]     # not s2 (too recent), not s3 (concluded)
```

**Why this matters so much:** the in-memory-database shortcut (SQLite standing in for Postgres) is a trap. It has different SQL dialects, different type handling, different transaction semantics, different NULL ordering, and no JSONB, arrays, RLS or partial indexes. **Tests pass, production breaks.** Testcontainers gives you the real engine, the real dialect, and the real behaviour, in about two seconds of startup.

### What to integration-test

```
✅ Repository queries against a real database (especially complex SQL)
✅ Database migrations (run them forward on real data shapes)
✅ Transaction and concurrency behaviour (optimistic locking, deadlock handling)
✅ Message publishing and consumption, including retry and DLQ paths
✅ Cache interaction, including the cache-miss path
✅ HTTP layer: routing, serialisation, validation, auth middleware
✅ ⭐ Tenant isolation (Chapter 17) — tenant A must get 404 for tenant B's resources
```

That last one deserves a dedicated, automated test class. It catches the highest-impact bug category in multi-tenant SaaS.

```python
@pytest.mark.parametrize("path", ["/v1/sessions/{id}", "/v1/sessions/{id}/attempts",
                                  "/v1/customers/{id}"])
async def test_cross_tenant_access_returns_404(client, tenant_a_token, tenant_b_resource, path):
    res = await client.get(path.format(id=tenant_b_resource.id),
                           headers={"Authorization": f"Bearer {tenant_a_token}"})
    assert res.status_code == 404          # NOT 403 — do not leak existence
```

### Test data management

| Approach | Trade-off |
|----------|-----------|
| **Fresh database per test** | Perfect isolation; slow |
| **Transaction rollback per test** ⭐ | Fast and isolated — **usually the best choice** |
| **Truncate between tests** | Fast; must get the table order right |
| **Shared seed data** | Fastest; tests become coupled and order-dependent |

**Use builders, not fixtures full of magic values:**

```python
# ❌ What matters here? Everything looks equally important.
session = Session("s1", "t1", "c1", "pending", 0.0, 0, datetime(2026,1,1), None, "active")

# ✅ Only the relevant detail is visible; everything else is a sensible default
session = a_session().for_tenant("t1").with_score(0.82).pending().build()
```

The builder makes the *intent* of each test obvious, and adding a new required field does not break 200 tests.

---

## 21.5 Contract testing ⭐ 🟢

**The problem this solves is specific to distributed systems, and it is a real one.**

```
Service A calls Service B.

Unit tests on A:   mock B → pass
Unit tests on B:   pass
Both deploy.       💥 B changed a field name three weeks ago.
                      A's mock still returns the old shape.
                      Nobody found out until production.
```

The mock encodes A's *belief* about B. Nothing verifies that the belief is still true.

**E2E tests would catch it — but they are slow, flaky, and require every service running.** Contract testing catches it in each service's own fast pipeline.

### Consumer-driven contract testing (Pact)

```
1. CONSUMER (A) writes a test declaring what it needs from B.
   → this generates a CONTRACT file (a pact)

2. The contract is published to a broker.

3. PROVIDER (B) runs the contract against its real implementation in ITS pipeline.
   → if B breaks the contract, B's build fails — before deployment
```

```javascript
// CONSUMER side: "I need these fields, in this shape"
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
      // Note: consumer declares ONLY the fields it uses.
      // The provider may add more fields freely — that is the tolerant reader (Chapter 08).
    },
  },
});
```

```java
// PROVIDER side, in B's pipeline: verify the real service satisfies every contract
@Provider("verification-api")
@PactBroker(url = "https://pact-broker.internal")
class ContractVerificationTest {
    @State("a completed verification session ses_881 exists")
    void seedSession() { repository.save(passedSession("ses_881")); }
}
```

**Why "consumer-driven" is the right shape:** it documents what is *actually used*. If no consumer's contract mentions a field, you can delete it safely — a question that is otherwise impossible to answer in a microservices estate.

**Can-I-Deploy** is the practical payoff: before deploying, the broker answers *"is this version compatible with everything currently deployed?"* That turns coordinated release planning into an automated check.

### Schema-based contract testing (simpler, and often enough)

For APIs: **OpenAPI diffing in CI** (Chapter 08).

```bash
oasdiff breaking main-spec.yaml pr-spec.yaml --fail-on ERR
```

For events: **schema registry compatibility checks** (Chapter 06).

> **Start here.** Schema diffing is a one-line CI step and catches most breakages. Add Pact when you need the finer-grained "what is actually consumed" question — typically at 10+ services.

---

## 21.6 End-to-end tests 🟡

**Definition:** the whole system, through the real user interface, with real dependencies.

### Use them sparingly and deliberately

```
✅ Cover the 5-10 CRITICAL user journeys only
   - sign up and log in
   - complete a verification end to end
   - a reviewer approves a flagged session
   - billing generates a correct invoice

❌ Do NOT E2E-test every field validation, every error message, every edge case.
   Those belong in unit and integration tests.
```

**Why the restraint:** E2E tests are slow (minutes), brittle (a CSS change breaks them), expensive to maintain, and when they fail they rarely tell you *what* broke. A suite of 400 E2E tests becomes a suite everyone ignores because it is "probably just flaky" — and that is when it stops protecting you.

### Making E2E tests survivable

```javascript
// ❌ Brittle: breaks on styling changes
await page.click('.btn-primary.mt-4 > span:nth-child(2)');

// ✅ Robust: semantic and intentional
await page.getByRole('button', { name: 'Start verification' }).click();
await page.getByTestId('verification-result').waitFor();
```

```
1. Use semantic or explicit test-id selectors — never CSS structure
2. Auto-waiting, never fixed sleeps (Playwright/Cypress do this properly)
3. Each test creates its own data and cleans up — no shared fixtures
4. Run against a dedicated environment with known state
5. Quarantine flaky tests IMMEDIATELY — a flaky E2E suite is worse than none
6. Record video/traces on failure — debugging blind is unbearable
7. Run the full suite on a schedule and pre-release; a fast subset per PR
```

### Testing in production ⭐

Some things simply cannot be verified before release. The modern approach accepts this and makes production verification safe:

| Technique | What it gives |
|-----------|--------------|
| **Synthetic monitoring** | Critical journeys run every minute from outside (Chapter 19) |
| **Canary releases** | Real traffic, limited blast radius (Chapter 15) |
| **Feature flags** | Enable for internal users first, then 1% |
| **Shadow traffic** | Send a copy of real requests to the new version, compare results, discard the output |
| **Smoke tests after deploy** | A handful of assertions immediately post-release |

> **Shadow traffic is under-used and extremely powerful** when replacing a critical component — a new scoring model, a new query implementation, a rewritten service. You get production-scale validation with **zero** user risk, because the shadow output is never returned. For a liveness engine model upgrade, this is the correct way to gain confidence.

---

## 21.7 Other test types worth knowing 🟡

### Component testing

One service in isolation, with its real database but **all external services stubbed** (WireMock, MockServer, or a local fake).

```
[ Service under test ] ── real ──► [ Postgres, Redis in containers ]
                       ── stub ──► [ Vendor API, other services ]
```

This is often the **best value tier** in a microservices architecture: it exercises the whole service — HTTP layer, business logic, persistence, error handling — without needing the rest of the estate running. Faster and far more stable than E2E, with much of the confidence.

### Performance testing

Chapter 20. Load, stress, soak, spike. **Include a performance budget check in CI.**

### Security testing

| Type | What it does | When |
|------|-------------|------|
| **SAST** | Static analysis of source | Every PR |
| **SCA** | Dependency vulnerability scan | Every PR + daily |
| **Secret scanning** | Credentials in code | Every PR + pre-commit |
| **Container scanning** | Image CVEs | Every build |
| **DAST** | Attacks the running app | Nightly / pre-release |
| **IaC scanning** | Insecure infrastructure config | Every PR |
| **Penetration test** | Humans attacking it | Annually, and before major launches |

**Plus the architecture-specific ones you must write yourself:** cross-tenant isolation tests, authorisation matrix tests (every role × every endpoint), and IDOR tests. Automated tooling will not find these — they require knowledge of your domain.

### Mutation testing ⚪

Deliberately introduces bugs (mutations) into your code and checks whether your tests catch them.

```python
if score > 0.85:        # original
if score >= 0.85:       # mutant — do your tests fail?
if score < 0.85:        # mutant — do your tests fail?
```

**It tests your tests.** 90% line coverage with tests that assert nothing meaningful will score terribly on mutation testing — which is exactly the useful information coverage cannot give you. Slow to run, so use it periodically on your most critical modules (pricing, scoring, permissions), not on everything.

### Property-based testing ⚪🟡

Instead of specific examples, state a **property** that must always hold, and let the framework generate hundreds of inputs to try to break it.

```python
from hypothesis import given, strategies as st

@given(st.decimals(min_value=0, max_value=1, places=3))
def test_score_band_is_always_defined(score):
    assert LivenessScore(score).band in Confidence     # never crashes, never returns None

@given(st.lists(st.builds(Money, st.decimals(min_value=0, max_value=10000), st.just("USD"))))
def test_sum_is_order_independent(amounts):
    assert sum_money(amounts) == sum_money(list(reversed(amounts)))
```

**It finds the edge cases you did not think of** — empty lists, zero, boundary values, Unicode oddities, precision errors. Excellent for parsers, serialisers, calculations, and anything with invariants. When it finds a failure, it automatically shrinks the input to the minimal reproducing case, which is genuinely delightful.

---

## 21.8 Testing the hard things

### Time

```python
# ❌ Untestable and flaky
class Session:
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at

# ✅ Inject the clock
class Session:
    def is_expired(self, now: datetime) -> bool:
        return now > self.expires_at

# Now: session.is_expired(a_specific_moment) — deterministic, no sleeping, no freezing
```

> **Never call `datetime.now()` deep inside business logic.** Pass time in from the edge. This one habit removes an entire class of flaky tests and makes "what happens at the boundary?" trivially testable.

### Randomness

Inject the random source, or seed it. Same principle as time.

### Asynchrony and eventual consistency

```python
# ❌ Flaky: sometimes 100 ms is enough, sometimes it is not
await publish(event)
await asyncio.sleep(0.1)
assert await projection.get("s1") is not None

# ✅ Poll with a timeout — deterministic outcome, fast when it works
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

**`sleep()` in a test is almost always a bug.** It is either too short (flaky) or too long (slow) — usually both, on different machines.

### External vendors

```
1. FAKE for unit and component tests (a local implementation of your port)
2. RECORDED responses (VCR/cassettes) for integration tests
3. THEIR SANDBOX for a small number of contract tests, run on a schedule
4. ⭐ Test the FAILURE modes explicitly: timeout, 500, 429, malformed response,
   slow response, and connection reset. These are the paths that break in production
   and the ones that are almost never tested.
```

> Because you put an **Anti-Corruption Layer** in front of every vendor (Chapter 03), all of this is easy: swap the ACL implementation. Without an ACL, vendor testing is miserable — which is another argument for the pattern.

---

## 21.9 Coverage — use it correctly

**Coverage measures which lines ran, not whether behaviour is correct.**

```python
def calculate_discount(order, customer):
    if customer.tier == "gold":
        return order.total * Decimal("0.20")
    return Decimal("0")

def test_discount():
    calculate_discount(gold_order(), gold_customer())   # 100% line coverage
    # ...and no assertion. The test passes even if the function returns garbage.
```

**How to use coverage sensibly:**

```
✅ Use it to FIND untested code — "this whole error path has never run"
✅ Set a floor (70-80%) to prevent decay, and gate on it in CI
✅ Require higher coverage on critical modules (payments, auth, scoring)
✅ Look at BRANCH coverage, not just line coverage
❌ Do not chase 100% — the last 15% is usually defensive code and generated code
❌ Do not treat it as a quality measure — it measures execution, not verification
```

> **A more useful question than "what is our coverage?" is: "if I deliberately break this business rule, does a test fail?"** That is mutation testing's question, and it is the one that actually matters.

---

## 21.10 Test strategy for a distributed system

```
Per service (fast, in each service's own pipeline):
  ├── Unit tests          — domain logic, no I/O                  seconds
  ├── Integration tests   — real DB/queue via Testcontainers      1-2 minutes
  ├── Component tests     — whole service, externals stubbed      2-3 minutes
  └── Contract tests      — consumer + provider verification      seconds

Cross-service (slower, less frequent):
  ├── E2E tests           — 5-10 critical journeys only           10-20 minutes
  ├── Performance tests   — load, and soak before major releases  hours
  └── Security scans      — SAST/SCA/DAST                         minutes to hours

Production:
  ├── Synthetic monitoring — critical journeys, every minute
  ├── Canary + feature flags
  ├── Shadow traffic       — for risky component replacements
  └── Smoke tests          — immediately after every deploy
```

**The key structural insight: contract tests replace most cross-service E2E tests.** Each service verifies its contracts in its own fast pipeline, so you no longer need to stand up the whole estate to know that the integration still works. That is what makes independent deployment (Chapter 02) genuinely possible rather than nominally possible.

---

## 21.11 Common mistakes

1. **Testing implementation instead of behaviour** — brittle tests that break on every refactor
2. **Mock-heavy unit tests** — they test that your code calls your code
3. **SQLite standing in for Postgres** — different dialect, different semantics, false confidence
4. **The ice cream cone** — mostly E2E and manual testing; slow, flaky, expensive
5. **Tolerating flaky tests** — the team learns to ignore red, and CI stops protecting anything
6. **`sleep()` in tests** — flaky on slow machines, slow on fast ones
7. **`datetime.now()` inside business logic** — untestable, time-dependent failures
8. **Shared mutable test data** — order-dependent failures that appear only in CI
9. **Chasing 100% coverage** — effort spent on trivia while the error paths stay untested
10. **No contract tests between services** — integration breakage found in production
11. **Never testing failure paths** — timeouts, 500s, retries and fallbacks are untested in most codebases, and they are exactly what runs during an incident
12. **No cross-tenant isolation tests** — the highest-impact multi-tenant bug goes unguarded
13. **Slow test suites** — over ~10 minutes and developers stop running them locally
14. **Testing only the happy path** — the sad paths are where the money is lost

---

## 21.12 Architect's checklist

- [ ] Domain logic testable with **no** infrastructure (the structural test of a good design)
- [ ] Test strategy documented: what is tested at which level, and why
- [ ] Unit suite runs in under a minute
- [ ] Full PR pipeline under 10 minutes (Chapter 16)
- [ ] Integration tests use **real** infrastructure via Testcontainers
- [ ] Fakes preferred over mocks; builders preferred over fixture blobs
- [ ] Contract tests (or at minimum OpenAPI/schema diffing) between every service pair
- [ ] E2E limited to 5–10 critical journeys, with robust selectors
- [ ] Failure paths tested: timeout, 5xx, 429, malformed response, retry, DLQ
- [ ] Cross-tenant isolation tests for every resource type
- [ ] Authorisation matrix tested: every role × every endpoint
- [ ] Time, randomness and IDs injected, never called from within business logic
- [ ] Eventual consistency tested with polling, never `sleep`
- [ ] Coverage floor enforced in CI; higher on critical modules; branch coverage tracked
- [ ] Mutation testing run periodically on the most critical modules
- [ ] Flaky tests quarantined immediately and fixed or deleted
- [ ] Performance budgets and security scans in the pipeline
- [ ] Synthetic monitoring and post-deploy smoke tests in production

---

## 21.13 Self-test

1. Why is testability an architectural property? Give three design choices that determine it.
2. What is the real purpose of tests, and what does "untested" actually mean for a codebase?
3. Why does a failing unit test help more than a failing E2E test?
4. What is the "testing trophy" critique of the pyramid, and what is the pragmatic synthesis?
5. Why are mock-heavy tests brittle? Rewrite one to test behaviour instead.
6. Why prefer a fake over a mock? Give an example.
7. Why is SQLite-for-Postgres a trap? Name four specific differences.
8. Explain consumer-driven contract testing. What question can it answer that nothing else can?
9. How do contract tests replace most cross-service E2E tests, and why does that matter for deployability?
10. What is shadow traffic and when is it the right technique?
11. Why should `datetime.now()` never appear in business logic?
12. Why is `sleep()` in a test almost always a bug? What replaces it?
13. What does coverage measure, and what does it not? What is a better question?
14. What is mutation testing and what does it reveal that coverage cannot?
15. Name four failure paths that are almost never tested but always run during an incident.

---

## 21.14 Key takeaways

- **Tests exist so you can change the system without fear.** No tests = frozen system.
- **Painful tests are a design finding**, not a testing finding — fix the seams
- **Test behaviour, not implementation**, and at the fastest level that can verify it
- **Prefer fakes over mocks.** Mock-heavy tests break on refactor and catch little.
- **Use real infrastructure via Testcontainers** — SQLite-for-Postgres gives false confidence
- **Contract testing is the key distributed-systems technique** — it replaces most cross-service E2E tests and makes independent deployment real
- **E2E for 5–10 critical journeys only**, with semantic selectors and zero tolerance for flakiness
- **Test the failure paths** — timeouts, 5xx, retries, DLQ. They are what run during incidents.
- **Automate cross-tenant isolation tests** — the highest-impact multi-tenant bug class
- **Inject time, randomness and IDs.** Poll for eventual consistency; never sleep.
- **Coverage finds untested code; it does not measure quality.** Mutation testing tests your tests.
- **A flaky suite is worse than no suite** — it trains the team to ignore failure

---

**Next:** [Chapter 22 — Architecture Documentation](22-architecture-documentation.md)
