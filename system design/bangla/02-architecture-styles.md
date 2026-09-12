# অধ্যায় ০২ — Architecture Style 🟢

> এই অধ্যায়ের প্রতিটা style আপনার সাথে সাথে চেনা উচিত — যেভাবে একজন ডাক্তার একটা উপসর্গ চেনেন।
> সবগুলো আপনি ব্যবহার করবেন বলে নয়, বরং কেউ যখন বলবে *"এটা একটা hexagonal event-driven modular monolith"*, তখন আপনার সাথে সাথে ছবিটা মাথায় আসা উচিত আর জানা উচিত এরপর কী প্রশ্ন করতে হবে।

---

## ২.০ "Architecture" শব্দের দুই রকম অর্থ

মানুষ শব্দটা দুই আলাদা জিনিসের জন্য ব্যবহার করে, আর এই বিভ্রান্তি থেকে অন্তহীন তর্ক হয়। এদের আলাদা করুন:

| ধরন | যে প্রশ্নের উত্তর দেয় | উদাহরণ |
|------|--------------------|---------|
| **Deployment / topology style** | কয়টা deployable unit? তারা কীভাবে কথা বলে? | Monolith, microservices, serverless, SOA, event-driven |
| **ভেতরের / code organisation style** | একটা unit-এর ভেতরের কোড কীভাবে সাজানো? | Layered, hexagonal, onion, clean, pipes-and-filters, plugin |

এগুলো **স্বাধীন অক্ষ**। আপনার থাকতে পারে:

- Clean Architecture দিয়ে সাজানো একটা monolith ✅ (খুবই সাধারণ আর খুবই ভালো)
- এমন microservices যেখানে প্রতিটা service কাদার তাল ✅ (খুবই সাধারণ আর খুবই খারাপ)
- Hexagonal module সহ একটা modular monolith ✅ (যুক্তিসঙ্গতভাবে বেশিরভাগ টিমের জন্য সেরা জায়গা)

> **শিল্পের সবচেয়ে সাধারণ ভুল:** ভাবা যে "microservices" এলোমেলো কোড ঠিক করে দেবে। করে না। এটা আপনার এলোমেলো কোড নেয় আর টুকরোগুলোর মাঝে একটা নেটওয়ার্ক যোগ করে। **আগে module ঠিক করুন; topology একটা আলাদা, পরের সিদ্ধান্ত।**

---

# পর্ব ক — Deployment style

## ২.১ প্রচলিত Monolith

**সংজ্ঞা:** এক codebase, এক build, এক deployable unit, সাধারণত এক database।

```
┌────────────────────────────────────────────┐
│              shop.exe / app.py             │
│                                            │
│  Users │ Products │ Orders │ Payments │ ...│
│  (সবাই অবাধে একে অপরকে call করছে)          │
└──────────────────┬─────────────────────────┘
                   │
              ┌────▼────┐
              │   DB    │
              └─────────┘
```

### এটা আসলে কোন জায়গায় ভালো

| শক্তি | কেন |
|----------|-----|
| **সরলতা** | এক repo, এক build, এক deploy, এক log ফাইল, এক debugger |
| **Performance** | একটা function call ~১ ন্যানোসেকেন্ড। একটা network call ~১ মিলিসেকেন্ড। এটা **দশ লাখ গুণ** পার্থক্য। |
| **Transaction** | পুরো business operation জুড়ে `BEGIN ... COMMIT`। ACID বিনামূল্যে। |
| **Refactoring** | "Rename Symbol" পুরো সিস্টেম জুড়ে কাজ করে |
| **Debugging** | একটা stack trace পুরো গল্প বলে |
| **খরচ** | একটা server। কোনো service mesh নেই, কোনো message broker নেই, distributed tracing-এর বিল নেই। |

> **Monolith অচল হয়ে যায়নি। Shopify, GitHub, Stack Overflow আর Basecamp বিশাল, সফল monolith চালায়।** Stack Overflow মুষ্টিমেয় কয়েকটা server থেকে কোটি কোটি page view পরিবেশন করেছে।

### কোথায় ব্যথা দেয়

| সমস্যা | উপসর্গ |
|---------|---------|
| **Coupling-এর বিশৃঙ্খলা** | বলবৎ করা সীমানা না থাকলে শেষ পর্যন্ত সবকিছু সবকিছুকে call করে |
| **Deploy coupling** | এক লাইনের CSS ঠিক করতে payment engine deploy করতে হয় |
| **Scale coupling** | Image processing-এ ৩২ GB RAM লাগে, তাই *প্রতিটা* instance ৩২ GB পায় |
| **Technology-র শৃঙ্খল** | পুরোটা .NET 6; আপনি process-এর ভেতরে একটা Python ML library ব্যবহার করতে পারবেন না |
| **Team coupling** | ৬০ জন ডেভেলপার একটা main branch-এ merge করছেন; CI-র সারি ৪ ঘণ্টা |
| **Blast radius** | Report module-এ একটা memory leak checkout বন্ধ করে দেয় |
| **ধীর প্রতিক্রিয়া** | Test suite-এ ৯০ মিনিট লাগে |

**এটা আসলে কখন ভাঙে?** সাধারণত ব্যবহারকারীর সংখ্যায় নয় — **টিমের সংখ্যায়**। মোটামুটি একটা codebase-এ ১৫–২৫ জন ডেভেলপার পার হলে সমন্বয়ের খরচ প্রাধান্য পেতে শুরু করে। ওই সংখ্যাটাই আসল trigger, সেকেন্ডে কত request সেটা নয়।

### রায়

> **Default হিসেবে monolith নিন।** নির্দিষ্ট, নাম করা কারণ না থাকলে এখান থেকেই শুরু করুন। Martin Fowler-এর "MonolithFirst" পরামর্শটা চমৎকারভাবে টিকে গেছে: প্রথম দিনে আপনি আপনার আসল service boundary জানেন না, আর distributed system-এ একটা ভুল boundary ঠিক করা একটা process-এর ভেতরের ভুল boundary-র চেয়ে *দশ গুণ* বেশি ব্যয়বহুল।

---

## ২.২ Modular Monolith ⭐ (শিল্পের সবচেয়ে কম ব্যবহৃত style)

**সংজ্ঞা:** একটা deployable unit, কিন্তু ভেতরের কোড কঠোরভাবে বলবৎ করা module-এ ভাগ করা, যারা শুধু প্রকাশিত interface দিয়ে যোগাযোগ করে।

```
┌──────────────────────────────────────────────────────────────┐
│                    একটাই DEPLOYABLE UNIT                     │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│  │  Identity │  │  Billing  │  │Verification│ │ Reporting │  │
│  │           │  │           │  │           │  │           │  │
│  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │
│  │ │public │ │  │ │public │ │  │ │public │ │  │ │public │ │  │
│  │ │  API  │◄┼──┼─┤  API  │◄┼──┼─┤  API  │ │  │ │  API  │ │  │
│  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │
│  │  internal │  │  internal │  │  internal │  │  internal │  │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
└────────┼──────────────┼──────────────┼──────────────┼────────┘
         │              │              │              │
    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
    │ schema: │    │ schema: │    │ schema: │    │ schema: │
    │ identity│    │ billing │    │verificat│    │reporting│
    └─────────┘    └─────────┘    └─────────┘    └─────────┘
              একটাই DATABASE, আলাদা SCHEMA
```

### যে নিয়মগুলো একে কাজ করায়

১. **প্রতিটা module-এর একটা public API আছে** (মুষ্টিমেয় কয়েকটা interface/facade) আর বাকি সবকিছু `internal`/private
২. **কোনো module আরেক module-এর table-এ হাত ঢোকায় না।** আলাদা schema, আর শক্তভাবে বলবৎ করতে চাইলে module A-র DB user-এর module B-র schema-তে কোনো grant থাকবে না
৩. **Module-এর মধ্যে call যাবে public API দিয়ে** অথবা process-এর ভেতরের event দিয়ে
৪. **এটা শৃঙ্খলা দিয়ে নয়, টুল দিয়ে বলবৎ করুন** — পুরো কৌশলটাই এখানে

```csharp
// C#: আলাদা assembly + `internal` দিয়ে শারীরিকভাবে বলবৎ করুন
// Billing.csproj শুধু এটুকু প্রকাশ করে:
namespace Billing.Contracts;
public interface IBillingApi
{
    Task<Quote> GetQuoteAsync(TenantId tenant, Usage usage, CancellationToken ct);
    Task ChargeAsync(TenantId tenant, Money amount, CancellationToken ct);
}
// Billing.csproj-এর বাকি সবকিছু `internal` — অন্য module গুলো দেখতেই পারে না।
```

```csharp
// আর একটা fitness function, যাতে এটা কখনো পিছিয়ে না যায়:
[Fact]
public void Modules_Must_Only_Reference_Other_Modules_Contracts()
{
    var result = Types.InAssembly(typeof(VerificationModule).Assembly)
        .ShouldNot().HaveDependencyOnAny("Billing.Internal", "Identity.Internal")
        .GetResult();
    Assert.True(result.IsSuccessful);
}
```

```python
# Python: import-linter দিয়ে বলবৎ করুন (.importlinter)
[importlinter]
root_package = app

[importlinter:contract:module-independence]
name = Modules communicate only via their public api module
type = forbidden
source_modules =
    app.modules.verification
forbidden_modules =
    app.modules.billing.internal
    app.modules.identity.internal
```

### বেশিরভাগ টিমের জন্য এটাই কেন সেরা জায়গা

| আপনি পান (monolith) | আপনি পান (microservices-এর মতো) |
|---------------------|------------------------------|
| ACID transaction | পরিষ্কার সীমানা |
| সহজ deploy আর debug | স্বাধীন টিম module-এর মালিক হতে পারে |
| দ্রুত process-এর ভেতরের call | **যখন সত্যিই দরকার** তখন service হিসেবে বের করতে প্রস্তুত |
| এক repo, এক CI | Contract নিয়ে ভাবতে বাধ্য |

আর সবচেয়ে গুরুত্বপূর্ণ: **পরে বের করা সস্তা।** `Verification` যদি ইতিমধ্যেই একটা module হয় নির্দিষ্ট API আর নিজের schema সহ, তাহলে সেটাকে service বানানো কয়েক দিনের কাজ — বেশিরভাগটাই একটা process-এর ভেতরের call-কে HTTP/queue call-এ বদলানো। এটা যদি একটা জট পাকানো monolith হয়, তাহলে বের করতে এক বছর।

> **এই বইয়ের সবচেয়ে মূল্যবান ব্যবহারিক সুপারিশ এটাই:**
> **Modular monolith দিয়ে শুরু করুন। একটা নির্দিষ্ট, মাপা শক্তি দাবি করলে তবেই একটা service বের করুন** (স্বাধীন scaling, স্বাধীন deploy-এর গতি, টিমের স্বায়ত্তশাসন, ভিন্ন টেকনোলজি, নিয়ন্ত্রক সংস্থার কারণে বিচ্ছিন্নতা)।

### বাস্তব উদাহরণ

২০ জন ইঞ্জিনিয়ারের একটা payments কোম্পানি একটা modular monolith বানিয়েছিল: ৯টা module, ৯টা schema, একটা deployable। ৩ বছরে তারা ঠিক ২টা service বের করেছিল — fraud-scoring engine (GPU আর Python লাগত) আর webhook dispatcher (I/O-তে স্বাধীনভাবে scale করা লাগত)। বাকি ৭টা module কখনোই নড়ার দরকার হয়নি। তারা ৯টা service চালানো এড়িয়েছিল আর পুরো সময়টা feature ship করেছিল।

---

## ২.৩ Distributed Monolith ☠️ (anti-pattern)

**সংজ্ঞা:** দেখতে microservices-এর মতো। আচরণ monolith-এর মতো। দুটোরই অসুবিধা আছে আর কোনোটারই সুবিধা নেই।

### রোগনির্ণয়ের চেকলিস্ট — আপনার একটা আছে যদি:

- [ ] Service গুলো একসাথে, নির্দিষ্ট ক্রমে deploy করতে হয়
- [ ] Service গুলো database ভাগ করে, অথবা একটা service আরেকটার table পড়ে
- [ ] একজন ব্যবহারকারীর একটা কাজে ৬টা synchronous service hop লাগে
- [ ] একটা shared library বদলালে প্রতিটা service আবার build আর redeploy করতে হয়
- [ ] একটা service বন্ধ থাকলে পুরো সিস্টেম অকেজো হয়ে যায়
- [ ] আপনার একটা "release train" আছে যেখানে সব service বৃহস্পতিবার রাতে ship হয়
- [ ] Service গুলো একটা common package থেকে DTO ভাগ করে, যেটা প্রতি সপ্তাহে বদলায়

৩টা বা তার বেশি টিক পড়লে আপনার একটা distributed monolith আছে।

```
   ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
   │ Svc A  │───►│ Svc B  │───►│ Svc C  │───►│ Svc D  │
   └───┬────┘    └───┬────┘    └───┬────┘    └───┬────┘
       └─────────────┴──────┬──────┴─────────────┘
                      ┌─────▼─────┐
                      │ SHARED DB │   ← স্পষ্ট চিহ্ন
                      └───────────┘
   Synchronous চেইন: মোট latency = সবগুলোর যোগফল।
   মোট availability = সবগুলোর গুণফল (0.99^4 = ৯৬%)।
```

### এটা কীভাবে ঘটে (গল্পটা সবসময় একই)

১. ম্যানেজমেন্ট বলে "আমাদের microservices দরকার"
২. টিম **business capability** অনুযায়ী নয়, **technical layer** অনুযায়ী ভাগ করে (`user-api`, `user-service`, `user-data`)
৩. কেউ data-র পুনরাবৃত্তি চায় না, তাই shared DB থেকে যায়
৪. Service গুলোর একে অপরের data লাগে, তাই synchronous call বাড়তে থাকে
৫. Deploy-এর ক্রম গুরুত্বপূর্ণ হয়ে ওঠে, তাই একটা coordinator আসে
৬. এখন একটা login debug করতে আপনার ৬টা terminal লাগে

### কীভাবে বের হবেন

- আগে **data ownership** ঠিক করুন — প্রতি টুকরো data-র একজন মালিক, কোনো cross-read নয়। এটাই মূল কারণ।
- যেখানে সম্ভব synchronous চেইনগুলো **async event** দিয়ে বদলান
- Service গুলো সবসময় একসাথে বদলালে সেগুলো আবার **merge** করে দিন। Merge করা একটা বৈধ, পেশাদার পদক্ষেপ — এটা করতে অহংকার করবেন না।
- DTO package ভাগ করা বন্ধ করুন; প্রতিটা service নিজের contract-এর মালিক আর অন্যদেরটা সহ্য করে (অধ্যায় ০৮)।

---

## ২.৪ SOA — Service-Oriented Architecture ⚪🟡

Microservices-এর ২০০০ দশকের enterprise পূর্বপুরুষ।

```
  App A ──┐                                    ┌── পুরনো Mainframe
  App B ──┼──► ┌─────────────────────────┐ ────┼── SAP
  App C ──┘    │  ENTERPRISE SERVICE BUS │     └── Oracle DB
               │  routing, transformation,│
               │  orchestration, protocol │
               │  bridging, business rule │
               └─────────────────────────┘
```

**মূল ধারণা:** পুনর্ব্যবহারযোগ্য business service, routing/transformation/orchestration করা একটা কেন্দ্রীয় **ESB**, WSDL/SOAP-এ contract, কেন্দ্রীভূত governance।

**এটা কেন অপ্রিয় হলো:**
- ESB হয়ে দাঁড়াল **একটা single point of failure** আর **একটা single point of congestion**
- Business logic bus-এ ঢুকে পড়ল — "smart pipes, dumb endpoints" — তাই bus-টাই একটা monolith হয়ে গেল যেটার উপর সবাইকে সমন্বয় করতে হতো
- ভেন্ডরের licence ছিল বিশাল
- কেন্দ্রীয় governance মানে প্রতিটা পরিবর্তনে integration টিম লাগত, যাদের ৬ সপ্তাহের সারি ছিল

**Microservices মূলত এরই প্রতিক্রিয়া:** *"smart endpoints, dumb pipes."*

**এটা কি জানা দরকার?** পরিচিতি ⚪ — শুধু এটুকু যে enterprise-এর চাকরিতে আপনি অবশ্যই একটা ESB-র (MuleSoft, WSO2, BizTalk, TIBCO, IBM IIB) দেখা পাবেন, আর তখন আতঙ্কিত হওয়ার কিছু নেই। আরও জানার মতো: আধুনিক **API Gateway** আর **service mesh** হলো সেই বংশধর, যারা দরকারি অংশগুলো (routing, security, observability) রেখেছে আর business logic বাদ দিয়েছে।

---

## ২.৫ Microservices 🟢

**সংজ্ঞা:** একটা সিস্টেম যেটা ছোট, স্বাধীনভাবে deploy করা যায় এমন service-এর সমষ্টি, যার প্রতিটা নিজের data-র মালিক, আর business capability অনুযায়ী সাজানো।

### সংজ্ঞায়ক বৈশিষ্ট্য (সবগুলোই থাকতে হবে)

১. **স্বাধীনভাবে deploy করা যায়** — এটাই *মূল কথা*। অন্যগুলো ছাড়া একটা deploy করতে না পারলে আপনার microservices নেই।
২. **নিজের data-র মালিক** — কোনো shared database নয়। ব্যস।
৩. **একটা business capability অনুযায়ী সাজানো**, technical layer অনুযায়ী নয়
৪. **Smart endpoints, dumb pipes** — logic service-এ, bus-এ নয়
৫. **বিকেন্দ্রীভূত governance** — টিম নিজের টুল বাছে (যুক্তির মধ্যে থেকে)
৬. **ব্যর্থতার জন্য design** — নেটওয়ার্ক fail করবে; তখন বুদ্ধিমানের মতো আচরণ করুন
৭. **টিমের আকারের** — একটা টিম পুরোপুরি এটার মালিক হতে পারে ("two-pizza team")

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Identity   │  │  Billing    │  │Verification │  │ Notification│
│  Service    │  │  Service    │  │  Service    │  │  Service    │
│  (Team A)   │  │  (Team B)   │  │  (Team C)   │  │  (Team D)   │
│   .NET      │  │   .NET      │  │  Python/GPU │  │   Go        │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
  ┌────▼────┐      ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
  │Postgres │      │Postgres │      │ Mongo   │      │ Redis   │
  └─────────┘      └─────────┘      └─────────┘      └─────────┘
       └────────────────┴────────────────┴────────────────┘
                          Message broker (async event)
```

### আসল সুবিধা

| সুবিধা | বাস্তব উদাহরণ |
|---------|------------------|
| **স্বাধীন deployment** | Team C কাউকে না জিজ্ঞেস করে দিনে ৮ বার ship করে |
| **স্বাধীন scaling** | GPU verification service ৩০টা pod-এ চলে; billing চলে ২টায় |
| **টেকনোলজির মানানসই ব্যবহার** | Python-এ ML, Go-তে high-throughput I/O, .NET-এ business logic |
| **ত্রুটি বিচ্ছিন্নকরণ** | Notification service মরে গেল → verification তবু চলে, notification জমতে থাকে |
| **টিমের স্বায়ত্তশাসন** | ৮টা টিম, ৮টা backlog, ৮টা release ক্যালেন্ডার, ন্যূনতম সমন্বয় |
| **লক্ষ্যভিত্তিক rewrite** | ৫,০০০ লাইনের একটা service নতুন করে লেখা এক কোয়ার্টারের কাজ, ৩ বছরের কর্মসূচি নয় |

### আসল খরচ (এগুলো নিয়ে সৎ থাকুন)

| খরচ | বাস্তবতা |
|------|---------|
| **নেটওয়ার্ক নির্ভরযোগ্য নয়** | প্রতিটা call fail করতে, timeout করতে বা দুইবার পৌঁছাতে পারে। Distributed computing-এর ৮টা ভ্রান্তিই এখন প্রযোজ্য (অধ্যায় ০৫) |
| **কোনো distributed transaction নেই** | আপনার Saga আর compensation লাগবে। Design-এর কঠিনতায় এটা বিশাল এক ধাপ উপরে |
| **Eventual consistency** | বিজনেসকে মেনে নিতে হবে যে "dashboard ২ সেকেন্ড পেছনে" |
| **Debugging** | ব্যবহারকারীর একটা কাজ, ৭টা service, ৭টা log stream। যখন দরকার পড়বে তার *আগেই* আপনার distributed tracing থাকতেই হবে (অধ্যায় ১৮) |
| **Operational চাপ** | ৩০টা service = ৩০টা pipeline, ৩০টা dashboard, ৩০টা on-call runbook, ৩০ সেট secret |
| **Testing** | Integration testing সত্যিই কঠিন। আপনার contract testing লাগবে (অধ্যায় ২১) |
| **Data-র পুনরাবৃত্তি** | প্রতিটা service তার যা লাগে তার একটা কপি রাখে; কপিগুলো ঠিক রাখা একটা চলমান কাজ |
| **Latency** | ৭টা hop × ২০ ms = ১৪০ ms-এর মেঝে, কোনো আসল কাজ শুরুর আগেই |
| **খরচ** | বেশি instance, বেশি অলস ক্ষমতা, একটা broker, একটা mesh, একটা observability-র বিল |

### যে availability-র হিসাব মানুষকে অবাক করে

একটা request-কে যদি synchronously ৫টা service ছুঁতে হয়, প্রতিটা ৯৯.৯% available:

```
0.999 ^ 5 = 0.995   →  ৯৯.৫% availability  →  মাসে ~৩.৬ ঘণ্টা downtime
```

আপনি একটামাত্র service-এর চেয়েও অবস্থা **খারাপ** করে ফেললেন। এই কারণেই microservices-এ async messaging, caching, graceful degradation আর circuit breaker বাড়তি জিনিস নয় — এগুলো ভার বহনকারী।

### পূর্বশর্ত (Martin Fowler-এর "microservices premium")

**Microservices শুরু করবেন না যদি আপনার ইতিমধ্যেই না থাকে:**

- [ ] প্রতিটা service-এর জন্য automated deployment (CI/CD)
- [ ] Monitoring, কেন্দ্রীভূত logging আর distributed tracing
- [ ] দ্রুত infrastructure বানানোর ক্ষমতা (IaC)
- [ ] এমন টিম যারা on-call সহ একটা service শুরু থেকে শেষ পর্যন্ত মালিকানা নিতে পারে
- [ ] আপনার domain-এর সীমানা সম্পর্কে ভালো বোঝাপড়া (DDD দেখুন, অধ্যায় ০৩)
- [ ] একটা আসল, নাম করা সমস্যা যেটা microservices আপনার জন্য সমাধান করে

এগুলো না থাকলে microservices আপনাকে যা দেবে তার চেয়ে বেশি নেবে।

### "Micro" কত বড়?

ভুল উত্তর: "৫০০ লাইনের নিচে", "প্রতি table-এ একটা", "প্রতি ডেভেলপারে একটা"।

**সঠিক উত্তর:**
- এত ছোট যে **একটা টিম এর মালিক হতে** আর পুরোপুরি বুঝতে পারে
- **একটা bounded context**-এর সমান বড় (অধ্যায় ০৩) — সাধারণত এটাই সেরা নিয়ম
- এত ছোট যে দরকার পড়লে **২–৪ সপ্তাহে নতুন করে লেখা** যায়

> **দুটো service যদি সবসময় একসাথে বদলায়, তাহলে সেগুলো একটাই service।** বাস্তবে এটাই সবচেয়ে পরিষ্কার পরীক্ষা।

---

## ২.৬ Miniservice / "Right-sized service" 🟡

বাস্তববাদী মাঝামাঝি। একে *macroservice*, *modulith service*, বা "বাস্তবতা দিয়ে গড়া service"-ও বলা হয়।

**ধারণা:** স্বাধীনভাবে deploy করা যায় এমন service, কিন্তু "micro"-র চেয়ে বড়, আর কঠোর নিয়ম নিয়ে বাস্তববাদী — যেমন, ঘনিষ্ঠভাবে সম্পর্কিত দুটো service একটা database schema ভাগ করতে পারে, যদি সেটা ভাগ করলে সমাধানের চেয়ে বেশি সমস্যা তৈরি হতো।

```
┌────────────────────────┐  ┌────────────────────────┐
│  Customer Management   │  │   Verification Engine  │
│  (identity, profile,   │  │  (session, liveness,   │
│   consent, KYC doc)    │  │   scoring, vendor)     │
│      ~৪টা module        │  │      ~৫টা module        │
└───────────┬────────────┘  └───────────┬────────────┘
            │                            │
      ┌─────▼─────┐                ┌─────▼─────┐
      │ Postgres  │                │ Postgres  │
      └───────────┘                └───────────┘
```

**কখন এটাই সঠিক উত্তর:** বেশিরভাগ সময়, বেশিরভাগ কোম্পানির জন্য। ৪–৮টা ভালোভাবে বাছা service সাধারণত microservices-এর ৯০% সুবিধা দেয় operational খরচের ৩০%-এ।

**আর্কিটেক্টের দৃষ্টিভঙ্গি:** microservices দুইয়ের একটা পছন্দ নয়। এটা একটা **ডায়াল**, একটা deployable থেকে শত শত পর্যন্ত। আপনার কাজ হলো এমন একটা সেটিং বাছা যেটা আপনার টিমের আকার, আপনার NFR আর আপনার operational পরিপক্বতার সাথে মেলে — আর ডায়ালটা ধীরে, এক দিকে, প্রমাণসহ ঘোরানো।

---

## ২.৭ Event-Driven Architecture (EDA) 🟢

**সংজ্ঞা:** Component গুলো একে অপরকে সরাসরি call করার বদলে **event** — যা ঘটেছে তার সত্য — তৈরি আর গ্রহণ করে যোগাযোগ করে।

```
ORCHESTRATION (command-চালিত, synchronous, coupled)

  Order Service ──call──► Payment Service
                ──call──► Inventory Service
                ──call──► Shipping Service
                ──call──► Email Service
  (Order Service-কে চারটাই জানতে হবে, আর চারটার জন্যই অপেক্ষা করতে হবে)


CHOREOGRAPHY (event-চালিত, async, decoupled)

  Order Service ──publish──► [ OrderPlaced ]
                                    │
                ┌───────────────────┼───────────────────┬──────────────┐
                ▼                   ▼                   ▼              ▼
         Payment Service    Inventory Service    Shipping Service  Email Service
  (Order Service কে শুনছে সে সম্পর্কে কিছুই জানে না)
```

### দুই রকম মৌলিকভাবে আলাদা event-এর ধরন (পার্থক্যটা জানুন — এটা বিশাল গুরুত্বপূর্ণ)

**১. Event Notification** — পাতলা event, "কিছু ঘটেছে, গিয়ে দেখে নাও"

```json
{ "type": "OrderPlaced", "orderId": "ord_8812", "occurredAt": "2026-09-12T10:00:00Z" }
```

- ✅ ছোট, producer-এর data-র গঠনের সাথে কম coupling
- ❌ প্রতিটা consumer-কে producer-এর কাছে ফিরে call করতে হয় → একটা বাচাল, coupled রানটাইম আর producer-এর উপর load-এর ঢেউ

**২. Event-Carried State Transfer** — মোটা event, data বহন করে

```json
{
  "type": "OrderPlaced",
  "orderId": "ord_8812",
  "occurredAt": "2026-09-12T10:00:00Z",
  "customer": { "id": "cus_31", "email": "a@b.com", "tier": "gold" },
  "items": [{ "sku": "X1", "qty": 2, "unitPrice": "19.99" }],
  "total": { "amount": "39.98", "currency": "USD" }
}
```

- ✅ Consumer গুলো সম্পূর্ণ স্বাধীন — producer বন্ধ থাকলেও তারা কাজ করতে পারে
- ❌ বড় message, data-র পুনরাবৃত্তি, আর একটা **schema contract** যেটা এখন আপনাকে সাবধানে version করতে হবে

> **ব্যবহারিক নির্দেশনা:** service-এর মধ্যেকার event-এর জন্য default-এ event-carried state transfer নিন (স্বাধীনতাই তো পুরো কথা), তবে event গুলো কেন্দ্রীভূত রাখুন — consumer-দের যা লাগে তা বহন করুন, পুরো aggregate নয়।

### EDA-র শক্তি

- **চরম decoupling** — producer-এ হাত না দিয়েই একটা নতুন consumer যোগ করুন। এটাই মহাশক্তি।
- **সহনশীলতা** — একটা consumer বন্ধ থাকা মানে শুধু একটা বাড়তে থাকা queue, ব্যবহারকারীর ব্যর্থ request নয়
- **স্বাভাবিক বাফারিং** — traffic-এর ঢেউ সামলায়; queue সেগুলো শুষে নেয়
- **Auditability** — event log হলো যা যা ঘটেছে তার রেকর্ড
- **Scalability** — সমান্তরাল করতে consumer যোগ করুন

### EDA-র দুর্বলতা (সৎ তালিকা)

- **Eventual consistency** — সিস্টেম সবসময়ই কিছুক্ষণের জন্য পরস্পরবিরোধী অবস্থায় থাকে
- **পুরো প্রবাহটা কোনো এক জায়গায় দেখা যায় না** — business process-টা শুধু অনেকগুলো handler-এর একটা উদ্ভূত বৈশিষ্ট্য হিসেবে টিকে থাকে। বাস্তবে এটাই ১ নম্বর অভিযোগ।
- **Debugging**-এ সবসময় correlation ID আর tracing লাগে
- **Ordering** কঠিন (অধ্যায় ০৬)
- **Duplicate ঘটে** — প্রতিটা consumer-কে idempotent হতে হবে
- **চক্রাকার event-ঝড়** — A থেকে B, B থেকে C, C থেকে আবার A। অসীম লুপ, production-এ, রাত ৩টায়।

### Choreography বনাম Orchestration — কখন কোনটা

| | Choreography (event) | Orchestration (একজন coordinator) |
|---|---|---|
| **কীভাবে** | প্রতিটা service event-এ সাড়া দেয় | একটা service ধাপগুলো পরিচালনা করে |
| **Coupling** | খুবই আলগা | Coordinator সব অংশগ্রহণকারীকে জানে |
| **প্রবাহের দৃশ্যমানতা** | খারাপ — ছড়ানো | চমৎকার — এটা একটা পড়ার মতো ফাইল |
| **একটা ধাপ যোগ করা** | একটা consumer যোগ করুন, আর কিছুতে হাত দেবেন না | Coordinator সম্পাদনা করুন |
| **Error handling** | কঠিন, বিতরণ করা | কেন্দ্রীভূত, সহজ |
| **কীসের জন্য সেরা** | ২–৪টা ধাপ, সহজ প্রতিক্রিয়া, "সবাইকে জানাও" | ৫+ ধাপ, জটিল compensation, business-critical প্রবাহ |

> **ব্যবহারিক নিয়ম:** **সহজ fan-out প্রতিক্রিয়ার জন্য choreography** ব্যবহার করুন, আর **যেসব business process বুঝতে, নজরে রাখতে আর compensate করতে হবে তার জন্য orchestration** (order fulfilment, loan approval, KYC onboarding)। গোঁড়া হবেন না; বেশিরভাগ বাস্তব সিস্টেমে দুটোই মেশানো থাকে।

---

## ২.৮ Event Streaming 🟡

**সংজ্ঞা:** Event গুলো এমন একটা টেকসই, ক্রমিক, replay করা যায় এমন **log**-এ যায়, যেটা consumer-রা নিজের গতিতে পড়ে — এমন queue-তে নয় যেটা delivery-র পর message মুছে ফেলে।

| | Message Queue (RabbitMQ) | Event Stream (Kafka) |
|---|---|---|
| গ্রহণের পর | Message মুছে যায় | Event retention period পর্যন্ত থাকে |
| Consumer | Message-এর জন্য প্রতিযোগিতা করে | প্রতিটা group স্বাধীনভাবে সবকিছু পড়ে |
| অবস্থান | Broker track করে | Consumer নিজের **offset** track করে |
| Replay | না | **হ্যাঁ — এটাই মোক্ষম feature** |
| Ordering | প্রতি queue-তে, একাধিক consumer-এ দুর্বল | প্রতি **partition**-এ কঠোর |
| সাধারণ scale | হাজারে/সেকেন্ড | লাখে/সেকেন্ড |

### Replay কেন architecture বদলে দেয়

Log-টাই সত্যের উৎস হওয়ায় আপনি পারেন:
- একদম নতুন একটা service যোগ করে তাকে ইতিহাস থেকে **পুরো state নতুন করে বানাতে** দিতে
- একটা consumer-এর bug ঠিক করে, offset reset করে, গত ৩ দিন ঠিকভাবে **আবার প্রক্রিয়া করতে**
- **সব ঐতিহাসিক event**-এর উপর একটা নতুন ML model চালিয়ে feature backfill করতে
- Analytics-কে production DB না ছুঁয়ে একই stream-এর নিজস্ব পাঠ দিতে

এটা সত্যিই একটা আলাদা ক্ষমতা, শুধু "একটা দ্রুত queue" নয়। পূর্ণ বিবরণ অধ্যায় ০৭-এ।

---

## ২.৯ Event Sourcing 🟡 (শক্তিশালী, আর প্রায়ই অপব্যবহৃত)

**সংজ্ঞা:** বর্তমান state জমা রাখার বদলে, যে **event-এর ক্রম** সেটা তৈরি করেছে সেটা জমা রাখুন। বর্তমান state সেগুলো replay করে বের করা হয়।

```
প্রচলিত (state-ভিত্তিক) — আপনি জানেন কী, কখনো জানেন না কেন

  accounts
  ┌────┬─────────┐
  │ id │ balance │
  │ 42 │  1500   │    ← এখানে কীভাবে এলো? কেউ জানে না।
  └────┴─────────┘


EVENT SOURCED — ইতিহাসই data

  events (শুধু যোগ হয়)
  ┌─────┬────────────┬───────────────────┬──────────────────────┐
  │ seq │ account_id │ type              │ data                 │
  │  1  │     42     │ AccountOpened     │ {initial: 0}         │
  │  2  │     42     │ MoneyDeposited    │ {amount: 2000}       │
  │  3  │     42     │ MoneyWithdrawn    │ {amount: 600}        │
  │  4  │     42     │ FeeCharged        │ {amount: 15, why:..} │
  │  5  │     42     │ InterestPaid      │ {amount: 115}        │
  └─────┴────────────┴───────────────────┴──────────────────────┘

  balance = 0 + 2000 - 600 - 15 + 115 = 1500  (আর আপনি এটা প্রমাণ করতে পারেন)
```

### আপনি যা পান

- **সম্পূর্ণ audit trail, বিনামূল্যে** — finance, healthcare, insurance-এ বাধ্যতামূলক
- **সময়ভ্রমণ** — "৩ মার্চ দুপুর ২টায় এই customer-এর state কী ছিল?" — এটা একটা তুচ্ছ query
- **Debugging-এর মহাশক্তি** — ঠিক যে event-ক্রম bug-টা ঘটিয়েছিল সেটা replay করুন
- **পুরনো data থেকে নতুন projection** — বিজনেস এমন একটা report চাইল যার জন্য এমন data লাগে যা আপনি কখনো জমাননি… কেবল আপনি জমিয়েছিলেন, event-এ
- **Event গুলোই আপনার integration** — publish করুন আর অন্য সিস্টেমগুলো এমনিতেই কাজ করবে

### আপনি যা দাম দেন

- **সবকিছু কঠিন হয়ে যায়।** Query-র জন্য projection লাগে; আপনি শুধু `SELECT * WHERE balance > 1000` লিখতে পারবেন না
- **Event-এর schema evolution একটা গুরুতর শৃঙ্খলা** — event immutable আর চিরকাল বাঁচে; ২০২১-এর একটা v1 event ২০৩১-এও পড়া যেতে হবে
- **Snapshot লাগবে** — প্রতিবার load-এ ৪০ লাখ event replay করা সম্ভব নয়, তাই প্রতি N event-এ snapshot নিন
- **GDPR-এর "ভুলে যাওয়ার অধিকার" বনাম একটা immutable log** — একটা সত্যিকারের সংঘাত। প্রচলিত উত্তর: **crypto-shredding** (ব্যক্তিগত field গুলো প্রতি ব্যক্তির একটা key দিয়ে encrypt করুন; key মুছে ফেলুন)
- **টিমের শেখার বক্ররেখা খাড়া** — আর অর্ধেক বোঝা একটা event-sourced সিস্টেম একটা দুঃস্বপ্ন

```csharp
public class BankAccount
{
    public Guid Id { get; private set; }
    public decimal Balance { get; private set; }
    public int Version { get; private set; }
    private readonly List<object> _uncommitted = new();

    // ইতিহাস থেকে আবার তৈরি
    public static BankAccount Rehydrate(IEnumerable<object> history)
    {
        var acc = new BankAccount();
        foreach (var e in history) acc.Apply(e);
        return acc;
    }

    // আচরণ: validate করুন, তারপর একটা event RAISE করুন (কখনো সরাসরি mutate নয়)
    public void Withdraw(decimal amount)
    {
        if (amount <= 0)        throw new ArgumentException("Amount must be positive");
        if (amount > Balance)   throw new InsufficientFundsException(Id, Balance, amount);
        Raise(new MoneyWithdrawn(Id, amount, DateTime.UtcNow));
    }

    private void Raise(object e) { Apply(e); _uncommitted.Add(e); }

    // Apply: বিশুদ্ধ state পরিবর্তন, কোনো validation নয় (ইতিহাস তো ঘটেই গেছে)
    private void Apply(object e)
    {
        switch (e)
        {
            case AccountOpened o:  Id = o.AccountId; Balance = o.Initial; break;
            case MoneyDeposited d: Balance += d.Amount; break;
            case MoneyWithdrawn w: Balance -= w.Amount; break;
            case FeeCharged f:     Balance -= f.Amount; break;
        }
        Version++;
    }
}
```

> **গুরুত্বপূর্ণ নিয়ম:** `Apply` কখনো validate করে না। Validation হয় command method-এ, event raise করার *আগে*। একটা event একবার অস্তিত্ব পেলে সেটা একটা সত্য — আপনি ইতিহাস প্রত্যাখ্যান করতে পারবেন না।

### কখন ব্যবহার করবেন

✅ **হ্যাঁ:** আর্থিক ledger, audit-ভারী নিয়ন্ত্রিত domain, যেসব সিস্টেমে "কেন" "কী"-র মতোই গুরুত্বপূর্ণ, সহযোগিতামূলক সম্পাদনা, inventory/মজুদের চলাচল।

❌ **না:** CRUD app, সাধারণ ক্যাটালগ, টিম যখন এটা কখনো করেনি আর domain এটা দাবি করে না, যখন "বর্তমান state"-ই সত্যিই সবার একমাত্র চিন্তা।

> **সেরা চর্চা:** event sourcing ব্যবহার করুন **এক-দুটো aggregate-এর জন্য যাদের সত্যিই লাগে** (ledger, KYC সিদ্ধান্তের trail), পুরো সিস্টেমের জন্য নয়। এটা একটা টুল, ধর্ম নয়। আর খেয়াল রাখুন: **এর পাশাপাশি প্রায় সবসময়ই CQRS লাগে**, কারণ একটা event log-এ সরাসরি query করা অবাস্তব।

---

## ২.১০ Serverless / FaaS 🟡

**সংজ্ঞা:** আপনি function deploy করেন। Platform চাহিদামতো সেগুলো চালায়, শূন্য থেকে হাজারে scale করে, আর প্রতি invocation আর প্রতি GB-সেকেন্ডে বিল করে।

```
  HTTP request ──► API Gateway ──► Lambda/Azure Function ──► DynamoDB
  S3 upload    ──────────────────► Lambda (thumbnail)
  Queue message ─────────────────► Lambda (process)
  Cron schedule ─────────────────► Lambda (রাতের কাজ)
```

### আসল শক্তি

- **কোনো server patch, scale বা monitor করতে হয় না**
- **শূন্যে scale** — অলস থাকলে আক্ষরিক অর্থে কিছুই দিতে হয় না। ঢেউ-খেলানো বা কম-volume-এর কাজের জন্য অপ্রতিদ্বন্দ্বী।
- **স্বয়ংক্রিয় scaling** — কোনো capacity plan ছাড়াই ১ থেকে ১০,০০০ concurrent execution
- **Event-native** — ~১০ লাইন কোড দিয়ে ক্লাউড service-এর মধ্যে আঠা
- **দ্রুত শুরু** — এক বিকেলে একটা কাজ করা endpoint

### আসল দুর্বলতা

| সমস্যা | বিস্তারিত |
|---------|--------|
| **Cold start** | অলস থাকার পর প্রথম invocation: ১০০ ms (Go/Node) থেকে কয়েক সেকেন্ড (বড় dependency সহ JVM/.NET)। Latency-সংবেদনশীল ব্যবহারকারীর পথের জন্য খারাপ। উপশম: provisioned concurrency (টাকা লাগে, scale-to-zero-র উদ্দেশ্য নষ্ট করে), ছোট package, snapshot/AOT startup। |
| **চলার সময়ের সীমা** | সাধারণত সর্বোচ্চ ১৫ মিনিট। কোনো দীর্ঘ কাজ নয়। |
| **Vendor lock-in** | যে কোনো ক্লাউড পছন্দের মধ্যে সবচেয়ে গভীর — আপনার event wiring-টাই *হলো* ভেন্ডর |
| **Local development আর testing** | আগের চেয়ে ভালো, তবু একটা container-এর চেয়ে খারাপ |
| **Database connection** | ৫,০০০ concurrent lambda × প্রতিটায় ১টা connection = একটা মৃত Postgres। আপনার একটা proxy/pooler লাগবে (RDS Proxy, PgBouncer) — একটা ক্লাসিক, ব্যয়বহুল চমক। |
| **স্থির উচ্চ volume-এ খরচ** | স্থির load-এ একটা reserved VM নাটকীয়ভাবে সস্তা। একটা আসল crossover পয়েন্ট আছে — জেনে নিন আপনারটা কোথায়। |
| **Distributed জটিলতা** | ৬০টা function মানে ৬০টা deployable। পুরো অধ্যায় ০৫ প্রযোজ্য। |

### Serverless কখন সঠিক সিদ্ধান্ত

✅ ঢেউ-খেলানো, অনিশ্চিত বা কম traffic
✅ Event-driven আঠা (ফাইল upload হলো → resize; message এলো → process)
✅ নির্ধারিত কাজ আর cron
✅ দ্রুত prototype আর ভেতরের টুল
✅ সত্যিকারের ঝাঁকুনিমূলক batch কাজ (২০ সেকেন্ডের জন্য ১,০০০টা সমান্তরাল execution ছড়িয়ে দিন)

❌ স্থির high-throughput service
❌ ব্যবহারকারীর মুখোমুখি পথে ৫০ ms-এর নিচে latency-র দাবি
❌ দীর্ঘ হিসাব (video transcoding, model training)
❌ WebSocket-ভারী stateful কাজ (সম্ভব, তবে অসুবিধাজনক)
❌ আপনার টিমের যখন cloud-ops-এর পরিপক্বতা নেই — "serverless" মানে "ops-মুক্ত" নয়

> **বৃহত্তর অর্থটা খেয়াল করুন:** "serverless" এখন managed database (DynamoDB, Aurora Serverless, Cosmos DB), queue (SQS), আর শূন্যে scale হওয়া container (Cloud Run, Container Apps, Fargate)-ও বোঝায়। **Serverless container প্রায়ই সেরা জায়গা** — আপনি একটা স্বাভাবিক app আর স্বাভাবিক Docker image রাখেন, কিন্তু ব্যবহার অনুযায়ী দাম দেন আর স্বয়ংক্রিয়ভাবে scale করেন।

---

# পর্ব খ — ভেতরের কোড সাজানোর style

## ২.১১ Layered (n-tier) architecture 🟢

পৃথিবীর সবচেয়ে সাধারণ কাঠামো।

```
┌─────────────────────────────────────┐
│   Presentation  (controller, UI)    │
├─────────────────────────────────────┤
│   Business Logic (service)          │
├─────────────────────────────────────┤
│   Data Access   (repository, ORM)   │
├─────────────────────────────────────┤
│   Database                          │
└─────────────────────────────────────┘
        Dependency নিচের দিকে যায়
```

**নিয়ম:** প্রতিটা layer শুধু ঠিক নিচের layer-কে call করতে পারে (একটা *closed* layer)। কখনো একটা layer *open* হয় (এড়িয়ে যাওয়া যায়) — আপনি সেটা অনুমতি দিলে স্পষ্ট করে বলুন, কারণ "কখনো কখনো এড়িয়ে যান" নীরবে "সবসময় এড়িয়ে যান" হয়ে ওঠে।

**সুবিধা:** সবাই সাথে সাথে বোঝে; নতুনদের শেখানো সহজ; technical concern-এর পরিষ্কার বিভাজন।

**অসুবিধা (গুরুত্বপূর্ণ):**

১. **Database কেন্দ্রে চলে আসে।** Dependency নিচের দিকে, DB-র দিকে যায়, তাই data model design চালায় আর business rule গুলো table-এর গঠন অনুযায়ী আকার নেয়।
২. **"Sinkhole" anti-pattern** — অনেক request কিছু না করেই প্রতিটা layer সোজা পার হয়ে যায় (controller → service → repo → SELECT → ফেরত)। আপনার ৮০% call যদি pass-through হয়, তাহলে layer গুলো যা দিচ্ছে তার চেয়ে বেশি নিচ্ছে।
৩. **Layer গুলো technical, business নয়।** একটা feature-এর পরিবর্তন সব layer-এ, আলাদা আলাদা ফোল্ডারে হাত দেয়, যেটা high cohesion-এর উল্টো।
৪. এটা **modularity** নিয়ে কিছুই বলে না — একটা layered monolith-ও কাদার তাল হয়ে যায়।

**রায়:** ছোট/সহজ app আর CRUD-এর জন্য ঠিক আছে। সত্যিকারের business জটিলতা আছে এমন কিছুর জন্য hexagonal/clean (নিচে) নিন, যেটা layered-ই কিন্তু dependency-র তীরটা *উল্টে* দেওয়া।

---

## ২.১২ Hexagonal Architecture (Ports & Adapters) 🟢

**Alistair Cockburn-এর ধারণা:** application বসে মাঝখানে। বাইরের সবকিছু — UI, database, queue, ভেন্ডরের API — *বাইরে* থাকে আর **port** (interface) দিয়ে **adapter** (implementation)-এর মাধ্যমে প্লাগ হয়।

```
                    ┌──── DRIVING (প্রাথমিক) দিক ────┐
                    │  যারা app ব্যবহার করে           │
                    ▼                                ▼
        ┌────────────────┐              ┌────────────────┐
        │ REST Controller│              │  CLI / Worker  │
        │   (adapter)    │              │   (adapter)    │
        └───────┬────────┘              └───────┬────────┘
                │  implement/call করে             │
        ┌───────▼─────────────────────────────────▼────────┐
        │            PORT (inbound interface)              │
        │  ┌────────────────────────────────────────────┐  │
        │  │                                            │  │
        │  │        APPLICATION + DOMAIN CORE           │  │
        │  │   (বিশুদ্ধ business logic, কোনো framework নয়) │  │
        │  │                                            │  │
        │  └────────────────────────────────────────────┘  │
        │           PORT (outbound interface)              │
        └───────┬─────────────────────────────────┬────────┘
                │                                 │
        ┌───────▼────────┐              ┌─────────▼──────┐
        │ PostgresRepo   │              │ VendorFaceApi  │
        │   (adapter)    │              │   (adapter)    │
        └────────────────┘              └────────────────┘
                    ▲                                ▲
                    └──── DRIVEN (গৌণ) দিক ──────────┘
                       app যাদের ব্যবহার করে
```

**একটাই নিয়ম:** **সব dependency ভেতরের দিকে তাকায়।** Core HTTP, SQL, Kafka বা কোনো ভেন্ডর সম্পর্কে কিছুই জানে না।

```python
# ── CORE: port (core-এর নিজের interface) ─────────────────────────────
class SessionRepository(Protocol):                  # outbound port
    async def get(self, id: SessionId) -> Session | None: ...
    async def save(self, session: Session) -> None: ...

class FaceAnalyser(Protocol):                       # outbound port
    async def analyse(self, video: bytes) -> Signals: ...

class VerifyUseCase(Protocol):                      # inbound port
    async def execute(self, cmd: VerifyCommand) -> VerificationResult: ...

# ── CORE: application, শুধু port-এর উপর নির্ভরশীল ─────────────────────
class VerifyService(VerifyUseCase):
    def __init__(self, repo: SessionRepository, analyser: FaceAnalyser):
        self._repo, self._analyser = repo, analyser

    async def execute(self, cmd: VerifyCommand) -> VerificationResult:
        session = await self._repo.get(cmd.session_id) or Session.start(cmd.session_id)
        signals = await self._analyser.analyse(cmd.video)
        session.record_attempt(signals)
        await self._repo.save(session)
        return session.result()

# ── ADAPTER: বাইরে, আর এরা core-এর উপর নির্ভর করে ─────────────────────
class PostgresSessionRepository:      # SessionRepository implement করে
    ...
class OnnxFaceAnalyser:               # FaceAnalyser implement করে
    ...
class InMemorySessionRepository:      # একটা test adapter — এটাই লাভ
    ...
```

### ব্যবহারিক লাভ

- **in-memory adapter দিয়ে পুরো application logic test করুন** — কোনো DB নেই, কোনো নেটওয়ার্ক নেই, মিলিসেকেন্ডে
- Business কোডে হাত না দিয়েই **infrastructure বদলান**
- **একই core** চালানো যায় HTTP, একটা CLI, একটা queue consumer, বা একটা test দিয়ে
- আপনার business logic আপনার framework-এর চেয়ে **বেশি দিন বাঁচে** (framework-এর ফ্যাশনচক্র ~৫ বছরের; আপনার domain-এর নয়)

---

## ২.১৩ Onion Architecture ও Clean Architecture 🟢

দুটোই hexagonal-এর মতো একই ধারণার পরিমার্জন। পার্থক্য বেশিরভাগটাই শব্দভাণ্ডারের।

```
              ┌────────────────────────────────────────┐
              │   Framework ও Driver                   │   ← Web, DB, UI, device
              │  ┌──────────────────────────────────┐  │
              │  │  Interface Adapter               │  │   ← Controller, Presenter,
              │  │  ┌────────────────────────────┐  │  │     Gateway, Repository(impl)
              │  │  │ Application Business Rule  │  │  │   ← Use Case
              │  │  │  ┌──────────────────────┐  │  │  │
              │  │  │  │ Enterprise Business  │  │  │  │   ← Entity
              │  │  │  │       Rule           │  │  │  │
              │  │  │  └──────────────────────┘  │  │  │
              │  │  └────────────────────────────┘  │  │
              │  └──────────────────────────────────┘  │
              └────────────────────────────────────────┘

                 THE DEPENDENCY RULE:
        source code-এর dependency শুধু ভেতরের দিকে তাকায়।
        ভেতরের কিছু বাইরের কিছু সম্পর্কে কিছুই জানে না।
```

### সাধারণ .NET solution-এর বিন্যাস

```
src/
├── MyApp.Domain/              ← entity, value object, domain event, domain service
│   └── (reference: কিছুই না। EF Core-ও না। ASP.NET-ও না।)
├── MyApp.Application/         ← use case, DTO, port interface (IOrderRepository)
│   └── (reference: Domain)
├── MyApp.Infrastructure/      ← EF Core, HTTP client, file storage, message bus
│   └── (reference: Application, Domain)
├── MyApp.Api/                 ← controller, middleware, DI composition root
│   └── (reference: Application, Infrastructure)
└── tests/
    ├── MyApp.Domain.Tests/         ← বিশুদ্ধ, দ্রুত, কোনো mock লাগে না
    └── MyApp.Application.Tests/    ← fake adapter
```

**Compile-time পরীক্ষা:** `MyApp.Infrastructure` আর `MyApp.Api` মুছে ফেলুন। `MyApp.Domain` কি তবু build হয়? হলে আপনি ঠিক করেছেন।

### সৎ সমালোচনা

একটা ছোট CRUD app-এ Clean Architecture একটা `GET /products` endpoint-এর জন্য ৪টা project, ৬টা ফাইল আর ৩টা mapping ধাপ তৈরি করে। এটা **আনুষ্ঠানিকতা, architecture নয়**।

> **Business logic যখন সত্যিই জটিল বা দীর্ঘজীবী, তখন ব্যবহার করুন।** একটা সাধারণ CRUD service-এর জন্য একটা ভালোভাবে সাজানো layered app — বা এমনকি "vertical slice" (নিচে) — পেশাদার পছন্দ।

### Vertical Slice Architecture (জানার মতো আধুনিক বিকল্প) 🟡

*Technical layer* অনুযায়ী সাজানোর বদলে *feature* অনুযায়ী সাজান:

```
Features/
├── Verification/
│   ├── StartSession/
│   │   ├── StartSessionCommand.cs
│   │   ├── StartSessionHandler.cs
│   │   ├── StartSessionValidator.cs
│   │   └── StartSessionEndpoint.cs
│   └── SubmitVideo/
│       ├── SubmitVideoCommand.cs
│       ├── SubmitVideoHandler.cs
│       └── SubmitVideoEndpoint.cs
└── Billing/
    └── GenerateInvoice/
        └── ...
```

একটা feature-এর সবকিছু একটা ফোল্ডারে। একটা feature বদলালে একটা ফোল্ডারে হাত পড়ে। প্রতিটা slice ঠিক ততটাই সহজ বা স্তরায়িত হতে পারে যতটা *তার* দরকার। এটা cohesion সর্বোচ্চ করে, আর যেসব টিম Clean Architecture-কে অতিরিক্ত আনুষ্ঠানিক মনে করেছে তাদের কাছে এটা ক্রমশ পছন্দের style। CQRS-এর সাথে এটা খুব স্বাভাবিকভাবে জোড়া লাগে।

---

## ২.১৪ Pipes and Filters 🟡

**সংজ্ঞা:** Data একের পর এক স্বাধীন প্রক্রিয়াকরণ ধাপের মধ্য দিয়ে যায়, প্রতিটার একটা input আর একটা output।

```
  ভিডিও ──► [Frame    ] ──► [Quality  ] ──► [Face   ] ──► [Liveness] ──► ফলাফল
            [ বের করা  ]     [ যাচাই    ]     [ শনাক্ত ]     [ Score  ]
```

প্রতিটা filter:
- অন্যদের সম্পর্কে কিছুই জানে না
- একা test করা যায়
- ক্রম বদলানো, বদলে ফেলা, বা সমান্তরালে চালানো যায়
- স্বাধীনভাবে scale করা যায় (pipe গুলো যদি queue হয়)

```python
class Stage(Protocol):
    def process(self, ctx: PipelineContext) -> PipelineContext: ...

class Pipeline:
    def __init__(self, stages: list[Stage]):
        self._stages = stages

    def run(self, ctx: PipelineContext) -> PipelineContext:
        for stage in self._stages:
            ctx = stage.process(ctx)
            if ctx.should_stop:                 # প্রত্যাখ্যানে আগেভাগে বেরিয়ে যান
                break
        return ctx

pipeline = Pipeline([
    FrameExtractionStage(),
    QualityCheckStage(min_brightness=40, min_sharpness=0.6),
    FaceDetectionStage(),
    HeadPoseStage(),
    AntiSpoofStage(),
    ChallengeValidationStage(),
    ScoringStage(),
])
```

**কোথায় দেখবেন:** ETL/data pipeline, image আর video processing, compiler, HTTP middleware, Unix shell pipe (`cat x | grep y | sort | uniq -c`), CI/CD pipeline, ML inference pipeline।

**Trade-off:** চমৎকারভাবে modular আর testable; কিন্তু shared context object একটা god object হয়ে যেতে পারে, আর ধাপগুলোর মধ্যে বড় payload পাঠানো ব্যয়বহুল হতে পারে (byte নয়, reference পাঠান)।

---

## ২.১৫ Microkernel / Plugin Architecture 🟡

**সংজ্ঞা:** একটা ন্যূনতম core সিস্টেম, সাথে feature যোগ করা plug-in module।

```
        ┌─────────────────────────────────┐
        │         CORE SYSTEM             │
        │  (registry, lifecycle, routing) │
        └───┬─────────┬─────────┬─────────┘
            │         │         │
      ┌─────▼───┐┌────▼────┐┌───▼─────┐
      │ Plugin  ││ Plugin  ││ Plugin  │
      │ Passport││   NID   ││ Licence │
      │ Reader  ││ Reader  ││ Reader  │
      └─────────┘└─────────┘└─────────┘
```

**বাস্তব উদাহরণ:** VS Code, Eclipse, WordPress, Jenkins, Chrome extension, Kubernetes (CRD + controller), Terraform provider, browser rendering engine।

```csharp
public interface IDocumentPlugin
{
    string DocumentType { get; }
    string Version { get; }
    bool CanHandle(DocumentImage image);
    Task<ExtractedData> ExtractAsync(DocumentImage image, CancellationToken ct);
}

public class DocumentPluginRegistry
{
    private readonly IReadOnlyList<IDocumentPlugin> _plugins;
    public DocumentPluginRegistry(IEnumerable<IDocumentPlugin> plugins) => _plugins = plugins.ToList();

    public IDocumentPlugin Resolve(DocumentImage image)
        => _plugins.FirstOrDefault(p => p.CanHandle(image))
           ?? throw new UnsupportedDocumentException();
}
// একটা নতুন দেশের ID card সাপোর্ট করা = একটা নতুন class। Core-এ হাত পড়ে না।
```

**ব্যবহার করুন যখন:** একই operation-এর অনেক রকম রূপ সাপোর্ট করতে হবে, বিশেষত যেসব রূপ অন্যরা যোগ করে (customer, partner, একটা community) বা প্রতি tenant-এ। **ব্যবহার করবেন না যখন** সব রূপ আপনার নিয়ন্ত্রণে আর সেগুলো তিনটা — একটা Strategy-ই যথেষ্ট।

**Plugin সিস্টেমের মূল design প্রশ্ন:** plugin contract-এর versioning, বিচ্ছিন্নতা (একটা crash করা plugin কি host মেরে ফেলে?), security (একটা plugin কি অন্য tenant-এর data পড়তে পারে?), আর আবিষ্কার (config ফাইল, DI scan, dynamic assembly load)।

---

## ২.১৬ Space-Based Architecture ⚪

**যে সমস্যার সমাধান করে:** চরম, অনিশ্চিত concurrent load, যেখানে *database*-ই বাধা।

**ধারণা:** কেন্দ্রীয় database-কে request-এর পথ থেকে পুরোপুরি সরিয়ে দিন। Data রাখুন প্রক্রিয়াকরণ ইউনিটগুলোর মধ্যে একটা replicated in-memory data grid-এ; পেছনে asynchronously persist করুন।

যেখানে ব্যবহৃত হয়: high-frequency trading, কনসার্টের টিকিট বিক্রির সিস্টেম, বাজির প্ল্যাটফর্ম। টেকনোলজি: Hazelcast, Apache Ignite, GigaSpaces, Redis Enterprise।

**পরিচিতিই যথেষ্ট** — তবে আকৃতিটা চিনে রাখুন, কারণ "আমাদের DB-ই বাধা আর আমরা যথেষ্ট দ্রুত shard করতে পারছি না" — ঠিক এই উপসর্গটারই এটা চিকিৎসা।

---

# পর্ব গ — বেছে নেওয়া

## ২.১৭ সিদ্ধান্তের টেবিল

| আপনার অবস্থা যদি হয়… | বেছে নিন |
|----------------------|--------|
| Startup, < ১০ ডেভেলপার, domain অস্পষ্ট | **Modular monolith** |
| প্রতিষ্ঠিত product, ১০–৩০ ডেভেলপার, কিছু অংশ আলাদাভাবে scale করে | **Modular monolith + ২–৪টা বের করা service** |
| ৫০+ ডেভেলপার, পরিষ্কার bounded context, পরিণত DevOps | **Microservices** |
| Enterprise, সেতু বাঁধার মতো অনেক legacy | **SOA / integration layer + নতুন service** |
| ঢেউ-খেলানো/কম traffic, event-এর আঠা, cron job | **Serverless** |
| অনেক async প্রতিক্রিয়া, বেশি decoupling দরকার | **Event-driven** |
| Audit আর "কেন" আইনত আবশ্যক | **Event sourcing** (ওই aggregate গুলোর জন্য) |
| বহু-ধাপের data রূপান্তর | **Pipes and filters** |
| অনেক রূপ, তৃতীয় পক্ষের সম্প্রসারণযোগ্যতা | **Plugin / microkernel** |
| জটিল business rule, দীর্ঘজীবী product | যে topology-ই হোক তার ভেতরে **Hexagonal / Clean** |
| সাধারণ CRUD | **Layered** বা **vertical slice** |

## ২.১৮ Modular monolith বনাম microservices-এর সিদ্ধান্ত — ঠিকভাবে

এই সিদ্ধান্তটা নিয়েই আপনাকে সবচেয়ে বেশি জিজ্ঞেস করা হবে। ফ্যাশন দিয়ে উত্তর দেবেন না। **শক্তি** দিয়ে উত্তর দিন।

### যে শক্তিগুলো সত্যিই একটা service বের করার যুক্তি দেয়

| শক্তি | উদাহরণ | এটা কি আপনার জন্য সত্যি? |
|-------|---------|--------------------|
| **স্বাধীন scaling** | Video processing-এ GPU আর ৩০টা pod লাগে; বাকিতে ২টা | আগে মাপুন। Vertical scaling সস্তা আর অনেক দূর নিয়ে যায়। |
| **স্বাধীন deploy-এর গতি** | একটা টিম প্রতি ঘণ্টায় ship করে, আরেকটা মাসে (নিয়ন্ত্রিত) | সত্যি আর সাধারণ |
| **টেকনোলজির অমিল** | Python-এ ML, বাকিটা .NET-এ | খুবই সত্যি |
| **Scale-এ টিমের স্বায়ত্তশাসন** | ৮টা টিম একটা CI pipeline-এ আটকে আছে | ~২৫ ডেভেলপারের পর সত্যি |
| **ত্রুটি বিচ্ছিন্নকরণ** | Report generator কখনোই checkout বন্ধ করতে পারবে না | সত্যি — তবে একটা monolith-এর ভেতরে bulkhead-ও এটা করতে পারে |
| **নিয়ন্ত্রক সংস্থার কারণে বিচ্ছিন্নতা** | Card-এর data একটা PCI-scoped সীমানায় থাকতে হবে | সত্যি আর আপসহীন |
| **আলাদা availability-র চাহিদা** | Public API-তে ৯৯.৯৯% লাগে; admin portal-এ ৯৯% | সত্যি |

### যেগুলো ভালো কারণ নয়

- ❌ "এটা আধুনিক / সবাই করে"
- ❌ "আমাদের কোড এলোমেলো" (এলোমেলোই থাকবে, শুধু এলোমেলোগুলোর মাঝে network call যোগ হবে)
- ❌ "আমাদের হয়তো কোনোদিন scale করা লাগবে" (YAGNI — অধ্যায় ০১)
- ❌ "আমরা নতুন framework ব্যবহার করতে চাই" (একটা module-এ করুন)
- ❌ "CTO একটা আর্টিকেল পড়েছেন"

### বের করার রেসিপি (যখন শক্তিটা সত্যি)

```
১. আগে একে একটা ঠিকঠাক MODULE বানান (পরিষ্কার API, নিজের schema, কোনো cross-read নয়)
২. একে স্থিতিশীল হতে দিন — API যদি সাপ্তাহিক বদলায়, তাহলে সীমানাটা ভুল
৩. এর table গুলো নিজের database-এ সরান (এখনো process-এর ভেতরেই)
৪. Process-এর ভেতরের call গুলো একই interface-এর পেছনে network call দিয়ে বদলান
৫. Deployment আলাদা করুন
৬. একে নিজের pipeline, dashboard, alert আর on-call runbook দিন
```

১–৩ ধাপগুলোই মূল্যবান, আর সেগুলো ফেরানো যায়। আপনি যদি ১ নম্বর ধাপ শেষ করতে না পারেন, তাহলে আপনি ৬ নম্বর ধাপের জন্য **প্রস্তুত নন** — আর ১ নম্বর ধাপ না করাই ঠিক সেই উপায় যেভাবে distributed monolith-এর জন্ম হয়।

---

## ২.১৯ সাধারণ ভুল

১. **পূর্বশর্ত না থাকতেই microservices বেছে নেওয়া** (CI/CD, tracing, ops-এর পরিপক্বতা, domain-এর স্পষ্টতা)
২. **Business capability-র বদলে technical layer অনুযায়ী ভাগ করা** — `user-api`, `user-service`, `user-db` তিনটা service নয়, এটা তিনটা deployment-এ একটা service
৩. **বিশ্বাস করা যে topology কোডের মান ঠিক করে** — করে না, কখনোই না
৪. **Service গুলোর মধ্যে shared database** — distributed monolith বানানোর সবচেয়ে নির্ভরযোগ্য উপায়
৫. **৫ স্তর গভীর synchronous call চেইন** — আপনি ব্যর্থতার সম্ভাবনা গুণ করলেন আর latency যোগ করলেন
৬. **তুচ্ছ CRUD-এ Clean Architecture-এর আনুষ্ঠানিকতা প্রয়োগ** — একটা তালিকা ফেরত দিতে ৬টা ফাইল
৭. **পুরো সিস্টেম event sourcing করা** কারণ এটা আকর্ষণীয় ছিল
৮. **Module-এর সীমানা বলবৎ না করা** — "আমরা শৃঙ্খলাবদ্ধ থাকব" তৃতীয় মাসের পর কখনোই সত্যি নয়; fitness function ব্যবহার করুন
৯. **কখনো service আবার merge না করা** — দুটো যদি সবসময় একসাথে বদলায়, merge করাই সঠিক সিদ্ধান্ত
১০. **Conway's Law উপেক্ষা করা** — org chart প্রতিবারই আপনার diagram-কে হারাবে

---

## ২.২০ আর্কিটেক্টের চেকলিস্ট

- [ ] আমি কি একটা **deployment style** আর একটা **ভেতরের style** আলাদাভাবে আর ইচ্ছাকৃতভাবে বেছেছি?
- [ ] প্রতিটা service boundary-র পক্ষে যে নির্দিষ্ট **শক্তি** আছে, আমি কি তার নাম বলতে পারি?
- [ ] প্রতিটা service কি নিজের data-র মালিক, কোনো cross-service table read ছাড়া?
- [ ] ৩ hop-এর বেশি লম্বা কোনো synchronous চেইন আছে? তার হিসাব করা availability কত?
- [ ] Module-এর সীমানা কি টুল দিয়ে বলবৎ, আশার উপর নয়?
- [ ] Microservices বেছে থাকলে — **প্রতিটা** service-এর জন্য কি আমাদের CI/CD, tracing, logging আর on-call আছে?
- [ ] Event-driven বেছে থাকলে — কোনো একটা ফাইল যেহেতু পুরো ছবিটা দেখায় না, business process কোথায় নথিভুক্ত?
- [ ] টিমের আকার আর দক্ষতা কি এই topology-র সাথে মেলে?
- [ ] Domain layer কি framework-মুক্ত? (আমি কি Infrastructure মুছে দিয়েও compile করতে পারি?)
- [ ] এই পছন্দ ভুল হলে ফেরার পথ কী?

---

## ২.২১ নিজেকে যাচাই

১. "Architecture style"-এর দুটো স্বাধীন অক্ষ কী কী? দুটো মিলিয়ে একটা উদাহরণ দিন।
২. ১২ জনের একটা টিমের জন্য modular monolith সাধারণত microservices-এর চেয়ে ভালো কেন?
৩. Distributed monolith-এর পাঁচটা রোগনির্ণয়ের চিহ্ন বলুন।
৪. প্রতিটা ৯৯.৯%-এর পাঁচটা service, একটা চেইনে synchronously call করা — availability কত? হিসাব দেখান।
৫. Event notification বনাম event-carried state transfer: trade-off আর একটা default সুপারিশ দিন।
৬. কখন choreography ব্যবহার করবেন, আর কখন orchestration?
৭. একটা স্বাভাবিক database আর একটা audit table যা দেয় না, event sourcing তার বাইরে কী দেয়?
৮. Serverless ভুল পছন্দ — এমন চারটা পরিস্থিতির নাম বলুন।
৯. Clean Architecture-এ "the dependency rule" কী, আর এর compile-time পরীক্ষা কী?
১০. Layered architecture-এ "sinkhole" anti-pattern কী?
১১. একটা microservice বের করার পক্ষে সত্যিকারের চারটা শক্তি আর তিনটা যেগুলো নয় — তালিকা দিন।
১২. একটা modular monolith থেকে service বের করার ছয় ধাপের রেসিপি বর্ণনা করুন।

---

## ২.২২ মূল কথাগুলো

- **Deployment style আর code style স্বাধীন** — দুটোই ইচ্ছাকৃতভাবে ঠিক করুন
- **Modular monolith দিয়ে শুরু করুন।** বেশিরভাগ টিমের জন্য এটাই সর্বোচ্চ মূল্যের default
- **Microservices একটা সাংগঠনিক সমস্যার সমাধান**, যেটা কারিগরি সমাধান হিসেবে বিক্রি হয় — এর আসল সুবিধা স্বাধীন টিম আর স্বাধীন deploy
- **Distributed monolith** সবচেয়ে সাধারণ ব্যর্থতার রূপ; shared data এর মূল কারণ
- **EDA decoupling কিনে দেয় আর eventual consistency আর হারানো দৃশ্যমানতা দিয়ে দাম নেয়**
- **Event sourcing শক্তিশালী আর ব্যয়বহুল** — যেখানে "কেন" আইনত বা বাণিজ্যিকভাবে আবশ্যক সেখানে ব্যবহার করুন
- **Hexagonal/Clean dependency-র তীর উল্টে দেয়**, যাতে business logic framework-এর চেয়ে বেশি দিন বাঁচে
- **দুটো service যদি সবসময় একসাথে বদলায়, সেগুলো একটাই service**
- প্রতিটা style একটা **trade-off**; আপনারটা জোরে বলুন

---

**পরবর্তী:** [অধ্যায় ০৩ — Domain-Driven Design](03-domain-driven-design.md)

**ইংরেজি সংস্করণ:** [Chapter 02](../02-architecture-styles.md) · **[সূচিপত্র](README.md)**
