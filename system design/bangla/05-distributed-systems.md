# অধ্যায় ০৫ — Distributed Systems 🟢🟢

> **এটাই বইয়ের সবচেয়ে গুরুত্বপূর্ণ অধ্যায়।**
>
> আপনার সিস্টেমে যে মুহূর্তে একটার বেশি process একটা নেটওয়ার্কে কথা বলে, সেই মুহূর্তে programming সম্পর্কে আপনার জানা সবকিছু *সামান্য* মিথ্যা হয়ে যায়। Function call এখন মাঝপথে fail করতে পারে। সময় আর একটামাত্র জিনিস নয়। "এটা কি কাজ করেছে?" — এই প্রশ্নের উত্তর সত্যিই দেওয়া যায় না।
>
> আধুনিক সিস্টেমের বেশিরভাগ production incident আসলে ছদ্মবেশ পরা distributed systems-এর সমস্যা।

---

## ৫.১ Distributed system কেন কঠিন

একটা স্থানীয় function call:
- সবসময় ফেরত দেয় (বা throw করে), সবসময় দ্রুত, কখনো আংশিকভাবে চলে না, আর আপনি সবসময় ফলাফল জানেন।

একটা network call:
- সফল হতে পারে
- ব্যর্থ হতে পারে
- সফল হতে পারে কিন্তু **response** হারিয়ে যেতে পারে — **আপনি এটাকে ব্যর্থতা থেকে আলাদা করতে পারবেন না**
- ১০০ ms লাগতে পারে বা ১০০ সেকেন্ড
- **দুইবার** পৌঁছাতে পারে
- **ক্রমের বাইরে** পৌঁছাতে পারে
- **আপনি হাল ছেড়ে retry করার পরে** পৌঁছাতে পারে

> **মূল সমস্যা: আপনি "এটা fail করেছে" আর "এটা সফল হয়েছে কিন্তু আমি খবর পাইনি" — এই দুটোর পার্থক্য করতে পারবেন না।**
>
> এই অধ্যায়ের বাকি সবকিছুই ওই সত্যটা নিয়ে বাঁচার কৌশল।

### Distributed Computing-এর আটটা ভ্রান্তি

Peter Deutsch-এর ১৯৯৪ সালের তালিকা। প্রতিটাই এখনো প্রতিদিন লঙ্ঘিত হয়।

| # | ভ্রান্তি | বাস্তবতা | এটা আপনার কী খরচ করায় |
|---|---------|---------|-------------------|
| ১ | **নেটওয়ার্ক নির্ভরযোগ্য** | Packet পড়ে যায়, তার কাটা পড়ে, switch reboot হয়, ক্লাউড AZ partition হয় | প্রতিটা call-এ timeout + retry + fallback লাগে |
| ২ | **Latency শূন্য** | একই DC-তে ০.৫ ms, মহাদেশ পেরিয়ে ১৫০ ms | বাচাল design মরে যায়। Call গুলো batch করুন। |
| ৩ | **Bandwidth অসীম** | এটা মাপা হয় আর সীমিত | বড় payload-এ টাকা আর সময় দুটোই লাগে |
| ৪ | **নেটওয়ার্ক নিরাপদ** | নয় | সব জায়গায় TLS, service-এর মধ্যে mTLS, zero trust |
| ৫ | **Topology বদলায় না** | Pod সরে, IP বদলায়, instance প্রতি ঘণ্টায় বদলে যায় | Service discovery, কখনো IP hard-code নয় |
| ৬ | **একজনই প্রশাসক** | দশটা টিম, তিনটা ক্লাউড, পাঁচটা ভেন্ডর | সমন্বয়ের খরচ; কেউ পুরো সিস্টেম জানে না |
| ৭ | **পরিবহনের খরচ শূন্য** | Serialisation, TLS handshake, egress fee সব বাস্তব | JSON parsing প্রায়ই CPU-র hotspot |
| ৮ | **নেটওয়ার্ক একরকম** | আলাদা protocol, version, MTU, proxy | প্রান্তে compatibility-র bug |

**কঠিন পরিশ্রমে শেখা নিয়ম:** যখনই আপনি এমন একটা লাইন লেখেন যা একটা process-এর সীমানা পেরোয়, থামুন আর জিজ্ঞেস করুন — *এতে যদি ৩০ সেকেন্ড লাগে তাহলে কী? যদি কখনোই ফেরত না আসে? যদি দুইবার চলে?*

---

## ৫.২ Partial failure — সংজ্ঞায়ক সমস্যা

একটা monolith-এ হয় process চালু নয় বন্ধ। দুইয়ের একটা। সহজ।

একটা distributed system-এ **কিছু অংশ কাজ করে আর কিছু করে না**, আর কোনটা করে সেটা নিয়ে ভিন্ন ভিন্ন পর্যবেক্ষকের মধ্যে অমিল থাকে।

```
Service A ──► Service B    OK
Service A ──► Service C    TIMEOUT (কিন্তু C কি কাজটা করেছে?)
Service B ──► Service C    OK        ← B, C-তে পৌঁছায়, A পারে না। এবার কী?
```

### Two Generals সমস্যা

দুই পাহাড়ে দুটো সেনাবাহিনীকে একই সময়ে আক্রমণ করতে হবে। তারা বার্তাবাহক দিয়ে যোগাযোগ করে, আর বার্তাবাহক ধরা পড়তে পারে।

- General A পাঠান: "ভোরে আক্রমণ।" এটা কি পৌঁছাল?
- B একটা ack পাঠান। *সেটা* কি পৌঁছাল?
- A ack-এর একটা ack পাঠান…

> **এমন কোনো সসীম বার্তার ক্রম নেই যেটা দুই পক্ষকেই নিশ্চয়তা দেয়।** এটা প্রমাণিত, টেকনোলজির সীমাবদ্ধতা নয়।

**ব্যবহারিক ফলাফল:** **একটা নেটওয়ার্কে exactly-once delivery অসম্ভব।** আপনি *at-most-once* বা *at-least-once* পাবেন। "exactly once" বলে যা যা বিজ্ঞাপন করা হয়, সেগুলো আসলে **at-least-once delivery + idempotent processing**, যেটা একটা চমৎকার engineering উত্তর — শুধু জানুন এটা আসলে কী।

### Partial failure-এর জন্য design

প্রতিটা দূরবর্তী call-এর জন্য **আগেভাগেই** ঠিক করুন:

১. **Timeout** — কতক্ষণ পর হাল ছাড়ব? (সবসময় একটা বসান। Default সাধারণত অসীম বা অযৌক্তিক।)
২. **Retry** — করব কি? কতবার? কোন backoff সহ? Operation-টা কি আবার চালানো নিরাপদ?
৩. **Fallback** — cache করা মান? Default মান? সীমিত feature? Request fail করব?
৪. **Idempotency** — এটা দুইবার চললে business কি ভাঙে?

```python
# প্রতিটা বাইরের call, প্রতিবার। এটাকে আপনার codebase-এ একটা template বানান।
async def charge_customer(customer_id: str, amount: Money, idem_key: str) -> ChargeResult:
    return await self._client.post(
        "/charges",
        json={"customer": customer_id, "amount": str(amount.value),
              "currency": amount.currency},
        headers={"Idempotency-Key": idem_key},   # retry করা নিরাপদ
        timeout=Timeout(connect=2.0, read=10.0), # কখনো অসীম নয়
    )
```

---

## ৫.৩ সময় আর clock 🟢

**একটা distributed system-এ কোনো "এখন" নেই।**

### Wall clock কেন মিথ্যা বলে

- মেশিন drift করে (NTP ছাড়া সাধারণত ১০০–২০০ ms/দিন; VM-এ আরও খারাপ)
- NTP-র সংশোধন clock-কে **পেছনে** লাফ দেওয়ায় — `t2 - t1` ঋণাত্মক হতে পারে
- Leap second বাস্তব, বড় outage ঘটিয়েছে (Reddit, ২০১২)
- Virtual machine থামে আর আবার চলে, আর clock লাফ দেয়
- আলাদা মেশিন কখনোই ঠিক একই সময়ে থাকে না

```python
# BUG: এটা একটা ঋণাত্মক সময়কাল দিতে পারে, বা ভয়াবহ ভুল একটা
start = time.time()
do_work()
duration = time.time() - start     # কাজের মাঝপথে NTP সমন্বয় → আবর্জনা

# সঠিক: সময়কালের জন্য monotonic clock ব্যবহার করুন
start = time.monotonic()
do_work()
duration = time.monotonic() - start   # কখনো পেছনে যায় না
```

> **নিয়ম: "কটা বাজে?"-র জন্য wall clock (মানুষের জন্য timestamp)। "কতক্ষণ লাগল?"-র জন্য monotonic clock। কখনো মেশাবেন না।**

### বিপজ্জনক pattern: timestamp দিয়ে Last Write Wins

```
Node A (clock ৫০ ms দ্রুত): t=1000.050-এ {name: "Delower"} লেখে
Node B (clock সঠিক):       t=1000.000-এ {name: "Hosen"} লেখে  ← আসলে বাস্তব সময়ে পরে

LWW A-র মান রাখে। B-র write নীরবে হারিয়ে যায়। কোনো error নেই। কোনো log নেই। শুধু ভুল data।
```

Cassandra, DynamoDB আর Redis-ভিত্তিক lock — সবগুলোই মানুষকে এভাবে কামড়েছে। **সঠিকতা যদি ক্রমের উপর নির্ভর করে, তাহলে event সাজাতে wall-clock timestamp ব্যবহার করবেন না।**

### Logical clock — সময় ছাড়াই ক্রম

**Lamport timestamp**: প্রতি node-এ একটা সহজ counter।

```
নিয়ম:
  ১. যে কোনো স্থানীয় ঘটনার আগে:     counter += 1
  ২. message পাঠানোর সময়:          (message, counter) পাঠান
  ৩. message পাওয়ার সময়:           counter = max(local, received) + 1

দেয়: A যদি B-র আগে ঘটে, তাহলে LC(A) < LC(B)
দেয় না: LC(A) < LC(B) হলে A, B-র আগে ঘটেছে  ← concurrency শনাক্ত করতে পারে না
```

**Vector clock**: প্রতি node-এ একটা counter, একসাথে বহন করা।

```
Node A: [A:3, B:1, C:0]
Node B: [A:2, B:4, C:0]

উপাদান ধরে ধরে তুলনা:
  A[0]=3 > B[0]=2  কিন্তু  A[1]=1 < B[1]=4
  → কোনোটাই প্রাধান্য পায় না → এই ঘটনাগুলো CONCURRENT → একটা আসল সংঘর্ষ আছে
```

Dynamo-ধাঁচের database এভাবেই সংঘর্ষ **শনাক্ত** করে (নীরবে একটা write হারানোর বদলে)। তারপর তারা হয় application-কে দুটো সংস্করণই ফেরত দেয় ("sibling") নয় একটা merge নিয়ম প্রয়োগ করে।

**Hybrid Logical Clock (HLC)** একটা শারীরিক timestamp আর একটা logical counter মেশায় — আপনি মোটামুটি বাস্তব timestamp *আর* সঠিক causal ক্রম দুটোই পান। CockroachDB, MongoDB আর YugabyteDB ব্যবহার করে। নামটা জানা মূল্যবান।

### Google-এর TrueTime (ব্যয়বহুল উত্তর) ⚪

Spanner প্রতিটা datacenter-এ GPS receiver আর পারমাণবিক ঘড়ি বসায়, তাই এটা একটা সীমাবদ্ধ অনিশ্চয়তা ε (প্রায় ৭ ms)-এর মধ্যে সময় জানে। Commit করতে এটা কেবল ack করার আগে **অনিশ্চয়তাটুকু অপেক্ষা করে**।

ফলাফল: মহাদেশ জুড়ে বৈশ্বিকভাবে consistent, বাহ্যিকভাবে সাজানো transaction। খরচ: প্রতি commit-এ ~১৪ ms ইচ্ছাকৃত অপেক্ষা, সাথে পারমাণবিক ঘড়ি। জানুন যে এটা আছে; জানুন যে এটা সমাধান করতে *hardware* লেগেছিল, যা থেকেই বোঝা যায় সমস্যাটা কত কঠিন।

---

## ৫.৪ CAP Theorem 🟢

Eric Brewer-এর theorem, আর আমাদের ক্ষেত্রের সবচেয়ে ভুলভাবে উদ্ধৃত ধারণা।

**তিনটা বৈশিষ্ট্য:**

- **C — Consistency** (এখানে মানে *linearizability*): প্রতিটা read সর্বশেষ write দেখে। সব node একমত।
- **A — Availability**: একটা **অব্যর্থ** node-এ যাওয়া প্রতিটা request একটা non-error response পায়।
- **P — Partition tolerance**: node-দের মধ্যে নেটওয়ার্ক message পড়ে গেলেও সিস্টেম চলতে থাকে।

**Theorem:** একটা network partition-এর সময় আপনাকে C আর A-র মধ্যে বাছতে হবে।

### বলার সঠিক উপায়

> ❌ *"তিনটার মধ্যে দুটো বাছুন।"* — বিভ্রান্তিকর। নেটওয়ার্ক partition হয়ই; আপনি এটা থেকে অব্যাহতি পান না।
>
> ✅ **"একটা partition হলে আপনি কি একটা error ফেরত দেবেন (CP) নাকি সম্ভবত-পুরনো data ফেরত দেবেন (AP)?"**

```
            Network partition cluster ভাগ করে দেয়
     ┌──────────────┐   ╳╳╳╳   ┌──────────────┐
     │  Node A      │   ╳╳╳╳   │  Node B      │
     │  balance=100 │   ╳╳╳╳   │  balance=100 │
     └──────────────┘          └──────────────┘
            ▲                          ▲
     Client ৫০ লেখে              Client পড়ে
            │                          │
      ┌─────┴─────┐             ┌──────┴──────┐
      │  CP: write প্রত্যাখ্যান     │  CP: read প্রত্যাখ্যান (error)  │
      │  (error, সঠিক থাকুন)      │                               │
      │                          │                               │
      │  AP: write গ্রহণ           │  AP: ১০০ ফেরত দিন (পুরনো)     │
      │  (পরে মিলিয়ে নিন)         │                               │
      └──────────────────────────┴──────────────────────────────┘
```

### কোনটা বাছবেন — business-এর ফলাফল অনুযায়ী

| **CP** বাছুন যখন ভুল data কোনো data না থাকার চেয়ে খারাপ | **AP** বাছুন যখন কোনো data না থাকা পুরনো data-র চেয়ে খারাপ |
|---|---|
| ব্যাংক balance আর transfer | সামাজিক মাধ্যমের feed |
| সীমিত জিনিসের inventory | Product-এর view count |
| আসন/টিকিট বুকিং | Recommendation |
| Authentication আর permission | Analytics, logging |
| চিকিৎসার রেকর্ড | Shopping cart (পরে merge — Amazon বিখ্যাতভাবে এটা করে) |
| Payment processing | Presence/"ব্যবহারকারী online" নির্দেশক |

### বাস্তব সিস্টেম

| সিস্টেম | Default | নোট |
|--------|---------|-------|
| PostgreSQL / MySQL (single leader) | **CP** | Partition-এ সংখ্যালঘু দিক লিখতে পারে না |
| MongoDB | **CP** | Write/read concern দিয়ে সমন্বয়যোগ্য |
| Cassandra | **AP** (সমন্বয়যোগ্য) | প্রতি query-তে consistency level |
| DynamoDB | Default-এ **AP** | ২× খরচে strongly-consistent read পাওয়া যায় |
| Redis (একক) | মোটামুটি **CP** | Redis Cluster failover-এ write হারাতে পারে |
| ZooKeeper / etcd / Consul | **CP** | এরা সঠিক থাকার জন্যই আছে — এটাই তাদের কাজ |
| Spanner / CockroachDB | খুব উঁচু A সহ **CP** | কৌশল (TrueTime, Raft) partition-কে খুব কমই দৃশ্যমান করে |

### PACELC — আরও কাজের মডেল 🟢

CAP শুধু **partition-এর সময়কার** আচরণ বর্ণনা করে, যেটা বিরল। PACELC স্বাভাবিক অবস্থাও বর্ণনা করে।

> **যদি (P)artition হয়: (A)vailability নাকি (C)onsistency বাছুন
> (E)lse (নইলে): (L)atency নাকি (C)onsistency বাছুন**

**এটা আরও সৎ কাঠামো**, কারণ *দৈনন্দিন* trade-off হলো latency বনাম consistency। Strong consistency-তে সমন্বয় লাগে; সমন্বয়ে network round trip লাগে; round trip-এ মিলিসেকেন্ড খরচ হয়। প্রতিবারই।

| সিস্টেম | PACELC |
|--------|--------|
| DynamoDB | PA/EL — available আর দ্রুত, eventually consistent |
| Cassandra | PA/EL — একই |
| MongoDB | PA/EC — partition-এ available, নইলে consistent |
| PostgreSQL | PC/EC — সবসময় আগে সঠিকতা |
| Spanner | PC/EC — বৈশ্বিক consistency-র জন্য latency-র দাম দেয় |

> **আর্কিটেক্টের বাক্য:** *"আমরা feed-এর জন্য eventual consistency বেছেছি, কারণ ২০০ ms পুরনো হওয়া ব্যবহারকারীর চোখে পড়ে না, আর strong consistency প্রতিটা read-এ একটা ৪০ ms cross-region round trip যোগ করত।"*

---

## ৫.৫ Consistency model 🟢

কে বলছেন তার উপর ভিত্তি করে "consistency" অন্তত তিনটা আলাদা জিনিস বোঝায়। এগুলো আলাদা করুন:

- **ACID consistency** (database): database আপনার constraint বলবৎ করে
- **CAP consistency**: linearizability — সব node ঘটনার একটা ক্রম দেখে
- **Cache/replica consistency**: একটা কপি কতটা পুরনো হতে পারে?

এখানে আমরা দ্বিতীয় আর তৃতীয়টা বোঝাচ্ছি। সবচেয়ে শক্তিশালী (আর ধীর) থেকে সবচেয়ে দুর্বল (আর দ্রুত):

### ১. Linearizable (strong / atomic / external consistency)

প্রতিটা operation তার শুরু আর শেষের মাঝে কোনো এক বিন্দুতে **তাৎক্ষণিকভাবে** কার্যকর হয়েছে বলে মনে হয়। সিস্টেমটা এমন আচরণ করে যেন data-র ঠিক একটাই কপি আছে।

```
Client A: write(x=1) ────────█────────
Client B:              read(x) ──█──── → অবশ্যই ১ ফেরত দেবে
```

- ✅ ভাবতে সবচেয়ে সহজ। একটামাত্র মেশিনের মতো আচরণ করে।
- ❌ প্রতিটা operation-এ সমন্বয় লাগে → বেশি latency, কম availability
- কোথায়: etcd, ZooKeeper, Spanner, single-node database, DynamoDB-র strong read

### ২. Sequential consistency

সব node operation গুলো *একই ক্রমে* দেখে, কিন্তু ওই ক্রম বাস্তব সময়ের সাথে মিলতে হবে এমন নয়। Linearizable-এর চেয়ে দুর্বল, খুব কমই স্পষ্টভাবে দেওয়া হয়।

### ৩. Causal consistency ⭐

যেসব operation **কার্যকারণে সম্পর্কিত**, সেগুলো সবাই একই ক্রমে দেখে। Concurrent (অসম্পর্কিত) operation ভিন্ন ভিন্ন ক্রমে দেখা যেতে পারে।

```
Alice পোস্ট করেন: "আমার চাবি হারিয়ে গেছে"       (ঘটনা ১)
Alice পোস্ট করেন: "পেয়ে গেছি!"                  (ঘটনা ২, ১-এর কারণে)
Bob ২-তে মন্তব্য করেন: "দারুণ!"                 (ঘটনা ৩, ২-এর কারণে)

Causal consistency নিশ্চিত করে যে কেউই Bob-এর "দারুণ!" "পেয়ে গেছি!"-র আগে দেখবে না।
এটা Alice-এর পোস্টকে Carol-এর অসম্পর্কিত পোস্টের বিপরীতে সাজায় না।
```

> **বেশিরভাগ ব্যবহারকারী-মুখী সিস্টেমের জন্য এটাই সেরা জায়গা** — এতটা শক্তিশালী যে application কখনো মানুষের চোখে ভাঙা লাগে না, আবার এতটা দুর্বল যে দ্রুত আর available থাকে। Partition-এর সময় available থাকতে থাকতে অর্জনযোগ্য সবচেয়ে শক্তিশালী model এটাই।

### ৪. Read-your-writes (session consistency)

একজন ব্যবহারকারী সবসময় নিজের write দেখেন। অন্য ব্যবহারকারীরা পুরনো data দেখতে পারেন।

**বাস্তবে এটা আপসহীন।** একজন ব্যবহারকারী profile update করলেন আর পাতায় পুরনো নাম দেখা গেল — তিনি একটা bug report করবেনই, প্রতিবার। Leader read, sticky routing, বা সরাসরি নতুন মান ফেরত দিয়ে এটা implement করুন।

### ৫. Monotonic reads

আপনি কখনো সময়কে পেছনে যেতে দেখেন না। একটা মান একবার দেখলে আপনি আর কখনো তার চেয়ে পুরনো কিছু দেখেন না।

```
এটা ছাড়া:
  Read ১ (replica A, হালনাগাদ):   "৫টা মন্তব্য"
  Read ২ (replica B, পিছিয়ে):     "৩টা মন্তব্য"   ← মন্তব্য উধাও! ব্যবহারকারীরা আতঙ্কিত।
```

সমাধান: একজন ব্যবহারকারীকে একটা replica-তে আটকে দিন (user ID-তে consistent hashing)।

### ৬. Monotonic writes

আপনার নিজের write গুলো আপনি যে ক্রমে করেছেন সেই ক্রমেই প্রয়োগ হয়। স্পষ্ট, কিন্তু একটা leaderless সিস্টেমে বিনামূল্যে নয়।

### ৭. Eventual consistency

Write বন্ধ হলে সব replica শেষ পর্যন্ত মিলে যায়। প্রতিশ্রুতি এটুকুই — "শেষ পর্যন্ত"-এর কোনো সীমা নেই।

- ✅ সর্বোচ্চ availability আর সর্বনিম্ন latency
- ❌ "শেষ পর্যন্ত" ১০ ms হতে পারে বা (একটা incident-এর সময়) ১০ মিনিট। Application-কে এটা সহ্য করতে হবে।

> **চারটা session guarantee** — read-your-writes, monotonic reads, monotonic writes, writes-follow-reads — এগুলোই eventual consistency-কে বাস্তব মানুষের জন্য *ব্যবহারযোগ্য* করে। একটা eventually-consistent store-এও এগুলো implement করুন।

### বাস্তবে বেছে নেওয়া

```
ভুল data কি আর্থিক ক্ষতি, আইনি ঝুঁকি বা নিরাপত্তার ঝুঁকি ঘটায়?
├── হ্যাঁ → ওই operation-এর জন্য linearizable (আর শুধু সেটার — এটা ব্যয়বহুল)
└── না  → ব্যবহারকারীর কি নিজের পরিবর্তন সাথে সাথে দেখা দরকার?
          ├── হ্যাঁ → read-your-writes + causal (সাধারণ উত্তর)
          └── না  → eventual consistency (feed, counter, analytics)
```

**মূল অন্তর্দৃষ্টি:** consistency **প্রতি operation-এ** বাছা হয়, প্রতি সিস্টেমে নয়। একটা application-এ: "order দিন" আর "balance দেখুন"-এর জন্য strong consistency; "view count", "recommendation" আর "সম্প্রতি দেখা"-র জন্য eventual। মেশানোটা সঠিক engineering, অসঙ্গতি নয়।

---

## ৫.৬ Consensus 🟢

**সমস্যা:** ব্যর্থতা সত্ত্বেও কয়েকটা node-কে একটা মানে একমত হতে হবে (leader কে, পরের log entry কী, এই transaction কি commit হয়েছে)।

### এটা কেন কঠিন — FLP impossibility

> এমন একটা asynchronous নেটওয়ার্কে যেখানে এমনকি একটা node-ও fail করতে পারে, **কোনো deterministic algorithm সসীম সময়ে consensus নিশ্চিত করতে পারে না।**

সবাই যে কৌশলটা ব্যবহার করে: **এলোমেলো timeout**। Consensus সবসময় *নিরাপদ* থাকার নিশ্চয়তা দেয়, আর নেটওয়ার্ক ভালো আচরণ করলেই *সজীব* থাকে। এই কারণেই Raft-এর leader এলোমেলো election timeout ব্যবহার করে — সম্ভাব্যতার ভিত্তিতে প্রতিসাম্য ভাঙতে।

### Quorum — মৌলিক উপকরণ

একটা **quorum** হলো সংখ্যাগরিষ্ঠতা: `⌊N/2⌋ + 1`।

```
N = ৩  → quorum = ২  → ১টা ব্যর্থতা সহ্য করে
N = ৫  → quorum = ৩  → ২টা ব্যর্থতা সহ্য করে
N = ৭  → quorum = ৪  → ৩টা ব্যর্থতা সহ্য করে
```

**সংখ্যাগরিষ্ঠতা কেন?** কারণ একই সেটের দুটো ভিন্ন সংখ্যাগরিষ্ঠতা অন্তত একটা node-এ মিলবেই। ওই মিলটাই দুটো পরস্পরবিরোধী সিদ্ধান্ত অসম্ভব করে।

**বিজোড় সংখ্যা কেন?** N=৪-এরও quorum ৩, তাই এটা মাত্র ১টা ব্যর্থতা সহ্য করে — N=৩-এর সমান, বেশি খরচ আর বেশি latency-তে। **সবসময় বিজোড় আকারের cluster চালান: ৩, ৫, বা ৭।** এর বেশি খুব কমই — প্রতিটা বাড়তি node প্রতিটা সিদ্ধান্তে latency যোগ করে।

### Raft — বোধগম্য consensus 🟢

Raft স্পষ্টভাবেই শেখানোর জন্য design করা হয়েছিল (Paxos-এর বিপরীতে)। তিনটা উপ-সমস্যা:

**১. Leader election**

```
প্রতিটা node হয় FOLLOWER, CANDIDATE, নয় LEADER।

FOLLOWER:  leader-এর heartbeat-এর অপেক্ষা করে।
           একটা এলোমেলো timeout-এর (যেমন ১৫০–৩০০ ms) ভেতরে heartbeat না এলে → CANDIDATE হয়।

CANDIDATE: term বাড়ায়, নিজেকে ভোট দেয়, সবার কাছে ভোট চায়।
           সংখ্যাগরিষ্ঠতা পেল? → LEADER হয়।
           বেশি term দেখল? → FOLLOWER-এ নেমে যায়।
           কেউ না জিতে timeout হলো? → নতুন এলোমেলো timeout, আবার চেষ্টা।

LEADER:    প্রতি ~৫০ ms-এ heartbeat পাঠায়। সব client write সামলায়।
```

**এলোমেলো** timeout-টাই মূল কৌশল — এটা একসাথে প্রার্থী হওয়া বিরল করে, তাই election দ্রুত মীমাংসা হয়।

**২. Log replication**

```
Client → Leader: SET x = 5
  ১. Leader তার log-এ {term, index, "SET x=5"} যোগ করে  (uncommitted)
  ২. Leader সব follower-কে AppendEntries পাঠায়
  ৩. Follower গুলো যোগ করে আর ack করে
  ৪. একবার সংখ্যাগরিষ্ঠতা ack করলে → entry-টা COMMITTED
  ৫. Leader সেটা তার state machine-এ প্রয়োগ করে আর client-কে উত্তর দেয়
  ৬. Follower গুলো পরের heartbeat-এ commit-এর কথা জানে আর তারাও প্রয়োগ করে
```

**৩. Safety** — একজন candidate তখনই জিততে পারে যখন তার log ভোটদাতার log-এর অন্তত সমান হালনাগাদ। এটা নিশ্চিত করে যে একটা committed entry কখনো হারায় না।

### Split brain — যে ব্যর্থতাকে সবাই ভয় পায়

দুটো node-ই বিশ্বাস করে তারা leader। দুটোই write নেয়। Data দ্বিধাবিভক্ত হয়। কারও টাকা উধাও হয়।

```
        ╳╳ partition ╳╳
  ┌──────────────┐  ┌──────────────────────┐
  │   Node A     │  │  Node B    Node C    │
  │ (পুরনো leader)│  │        Node D  E     │
  │   ১টা node    │  │        ৪টা node       │
  └──────────────┘  └──────────────────────┘
   Quorum-এ পৌঁছাতে      Quorum আছে (৫-এর ৪)
   পারে না (৫-এর ১)      → নতুন leader নির্বাচন করে
   → নেমে যেতেই হবে        → নিরাপদে write নেয়
```

**Quorum split brain ঠেকায়** — সংখ্যালঘু দিক গাণিতিকভাবেই সংখ্যাগরিষ্ঠতা গড়তে পারে না, তাই তাকে write প্রত্যাখ্যান করতেই হয়। এই কারণেই quorum-ভিত্তিক সিস্টেম CP: সংখ্যালঘু ভুল হওয়ার বদলে unavailable হওয়া বেছে নেয়।

**অন্যান্য সুরক্ষা:**
- **Fencing token** — প্রতিটা leader একটা ক্রমবর্ধমান সংখ্যা পায়; নিচের সিস্টেমগুলো পুরনো token বহন করা যে কোনো request প্রত্যাখ্যান করে। এটা একটা *থেমে থাকা* পুরনো leader জেগে উঠে একটা পুরনো write পাঠানোর হাত থেকে রক্ষা করে।
- **STONITH** ("অন্য node-টার মাথায় গুলি করো") — সন্দেহভাজন node-এর বিদ্যুৎ জোর করে বন্ধ করে দিন। প্রচলিত HA cluster-এ সাধারণ।
- **Lease-ভিত্তিক leadership** — নবায়ন না করলে leadership-এর মেয়াদ শেষ হয়, তাই একটা বিচ্ছিন্ন leader নিজেই নেমে যায়।

### Paxos ⚪

মূল consensus algorithm (Leslie Lamport, ১৯৮৯)। প্রমাণিতভাবে সঠিক, বিখ্যাতভাবে বোঝা কঠিন আর সঠিকভাবে implement করা আরও কঠিন। Multi-Paxos Google Chubby আর Spanner-এ ব্যবহৃত। **পরিচিতিই যথেষ্ট** — জানুন যে Raft আছে কারণ Paxos খুব কঠিন ছিল।

### Byzantine Fault Tolerance ⚪

স্বাভাবিক consensus ধরে নেয় node *crash* করতে পারে কিন্তু কখনো *মিথ্যা বলে না*। BFT দুষ্ট node সামলায়, `f` জন বিশ্বাসঘাতক সহ্য করতে `3f + 1` node লাগে। Blockchain আর মহাকাশ প্রযুক্তিতে ব্যবহৃত। আপনার নিজের datacenter-এ এটা প্রায় নিশ্চিতভাবেই কখনো লাগবে না।

### আপনি আসলে কোথায় consensus-এর দেখা পান

আপনি খুব কমই এটা implement করেন। আপনি এটা **ব্যবহার** করেন:

| সিস্টেম | যে কাজে consensus ব্যবহার করে |
|--------|-------------------|
| etcd (Kubernetes-এর মস্তিষ্ক) | সব cluster state |
| ZooKeeper | Leader election, config, lock |
| Consul | Service registry, leader election |
| Kafka (KRaft) | Controller election, metadata |
| CockroachDB / TiDB / YugabyteDB | প্রতি range-এর replication |
| MongoDB | Replica-set-এর primary নির্বাচন |

> **আর্কিটেক্টের নির্দেশনা: কখনো নিজের consensus algorithm লিখবেন না।** etcd/ZooKeeper/Consul ব্যবহার করুন। একটা মাত্র Redis instance-এর উপর বানানো distributed lock নিরাপদ *নয়* (সুপরিচিত Redlock বিতর্ক দেখুন) — সঠিকতা যদি lock-এর উপর নির্ভর করে, তাহলে একটা আসল consensus সিস্টেম ব্যবহার করুন, অথবা এমনভাবে design করুন যাতে lock-ই না লাগে।

---

## ৫.৭ Distributed transaction 🟢

**সমস্যা:** একটা business operation-কে দুই বা ততোধিক service/database-এ atomically data বদলাতে হবে।

**উদাহরণ:** একটা order-কে (ক) inventory reserve করতে হবে, (খ) একটা card charge করতে হবে, (গ) একটা shipment বানাতে হবে। সব, নয়তো কিছুই না।

### Two-Phase Commit (2PC) — পাঠ্যবইয়ের উত্তর, যেটা আপনার সাধারণত এড়ানো উচিত

```
ধাপ ১: PREPARE
  Coordinator → সব অংশগ্রহণকারী: "আপনি কি commit করতে পারবেন? আপনার resource lock করুন।"
  অংশগ্রহণকারীরা: নিজের log-এ লেখে, row LOCK করে, YES বা NO উত্তর দেয়

ধাপ ২: COMMIT বা ABORT
  সবাই YES বললে → Coordinator → সবাই: "COMMIT"
  কেউ NO বললে   → Coordinator → সবাই: "ABORT"
```

**আধুনিক সিস্টেমে এটা কেন বেশিরভাগ সময় এড়ানো হয়:**

| সমস্যা | বিস্তারিত |
|---------|--------|
| **আটকে যাওয়া** | PREPARE-এর পর coordinator মরে গেলে অংশগ্রহণকারীরা **অনির্দিষ্টকাল** তাদের lock ধরে অপেক্ষা করে। আপনার database এখন জমে গেছে, এমন lock ধরে আছে যা কেউ ছাড়াতে পারে না। |
| **Coordinator একটা SPOF** | এর নিজের HA লাগে, যার জন্য consensus লাগে, যার জন্য... |
| **নেটওয়ার্ক জুড়ে lock ধরে রাখা** | Latency এখন *সবচেয়ে ধীর* অংশগ্রহণকারীর সময়। Throughput ভেঙে পড়ে। |
| **Available নয়** | যে কোনো অংশগ্রহণকারী বন্ধ = কোনো transaction-ই নয় (এটা দৃঢ়ভাবে CP) |
| **সীমিত সমর্থন** | বেশিরভাগ আধুনিক data store আর সব HTTP API এটা সাপোর্টই করে না |

**2PC কখন এখনো ঠিক আছে:** একটা প্রতিষ্ঠানের ভেতরে, একটা datacenter-এ, ছোট transaction, XA সাপোর্ট করা সিস্টেমে (ক্লাসিক: একটা enterprise Java stack-এ একটা database আর একটা message broker)। নইলে Saga ব্যবহার করুন।

### Saga pattern ⭐ 🟢 — ব্যবহারিক উত্তর

**ধারণা:** distributed transaction-টাকে **স্থানীয়** transaction-এর একটা ক্রমে ভাগ করুন। একটা ধাপ fail করলে আগেরগুলো বাতিল করতে **compensating** transaction চালান।

```
সুখী পথ
  T1: Inventory reserve   ✓
  T2: Payment charge      ✓
  T3: Shipment তৈরি       ✓
  → শেষ

T3-তে ব্যর্থতা
  T1: Inventory reserve   ✓
  T2: Payment charge      ✓
  T3: Shipment তৈরি       ✗ ব্যর্থ
  C2: Payment refund      ← compensation
  C1: Inventory ছেড়ে দিন   ← compensation
  → আবার consistent (শেষ পর্যন্ত)
```

**গুরুত্বপূর্ণ মানসিক পরিবর্তন:** একটা saga atomic **নয়**। এমন বাস্তব মুহূর্ত থাকে যখন customer-কে charge করা হয়েছে আর কোনো shipment নেই। Business-কে এটা মেনে নিতে হবে আর সিস্টেমকে নিশ্চিত করতে হবে যে এটা মিলে যায়। **Compensation মানে rollback নয়** — একটা refund একটা নতুন business সত্য, statement-এ দৃশ্যমান, কোনো মুছে ফেলা নয়।

### Choreography বনাম Orchestration (saga)

**Choreography** — service গুলো একে অপরের event-এ সাড়া দেয়:

```
Order Service ──[OrderCreated]──► Inventory Service
                                        │
                            [InventoryReserved]
                                        ▼
                                 Payment Service
                                        │
                              [PaymentCaptured]
                                        ▼
                                Shipping Service
```

✅ কোনো কেন্দ্রীয় component নেই; আলগা coupling
❌ **পুরো প্রক্রিয়াটা কেউ দেখতে পায় না।** Debug করা মানে ৬টা service পড়া। একটা ধাপ যোগ করা মানে বিদ্যমান সব subscription বোঝা। ভুল করে চক্রাকার নির্ভরতা তৈরি করা সহজ।

**Orchestration** — একজন coordinator ধাপগুলো চালায়:

```
                  ┌───────────────────────┐
                  │   Order Saga          │
                  │   Orchestrator        │
                  └───┬────┬────┬─────────┘
            reserve   │    │    │  ship
                 ┌────▼┐ ┌─▼───┐ ┌▼──────┐
                 │Inven│ │ Pay │ │Shippin│
                 └─────┘ └─────┘ └───────┘
```

✅ পুরো প্রক্রিয়াটা **একটা পড়ার মতো ফাইল**; কেন্দ্রীভূত error handling আর timeout; monitor করা আর ধাপ যোগ করা সহজ
❌ Orchestrator চালানোর জন্য আরেকটা service; এটা একটা god object হয়ে ওঠার ঝুঁকি, যাতে এমন business logic থাকে যেটা অন্য কোথাও থাকা উচিত

> **সুপারিশ: ৪+ ধাপ বা আসল টাকা জড়িত এমন যে কোনো কিছুর জন্য orchestration।** দৃশ্যমানতাটা এর দাম দেওয়ার মতো। সহজ fan-out notification-এর জন্য choreography ব্যবহার করুন।

```python
class OrderSagaOrchestrator:
    """পুরো business প্রক্রিয়া বর্ণনা করা একটা পড়ার মতো ফাইল।"""

    async def execute(self, order: Order) -> SagaResult:
        completed: list[CompensationStep] = []
        try:
            res = await self._inventory.reserve(order.items, order.id)
            completed.append(lambda: self._inventory.release(res.reservation_id))

            pay = await self._payments.charge(
                order.customer_id, order.total,
                idempotency_key=f"order-{order.id}",      # retry করা নিরাপদ
            )
            completed.append(lambda: self._payments.refund(pay.charge_id))

            ship = await self._shipping.create(order.id, order.address)
            completed.append(lambda: self._shipping.cancel(ship.shipment_id))

            await self._orders.mark_confirmed(order.id)
            return SagaResult.success(order.id)

        except Exception as e:
            logger.error("saga failed for order %s: %s", order.id, e)
            await self._compensate(reversed(completed))     # বাতিল করুন, উল্টো ক্রমে
            await self._orders.mark_failed(order.id, str(e))
            return SagaResult.failed(order.id, str(e))

    async def _compensate(self, steps) -> None:
        for step in steps:
            try:
                await step()                               # idempotent হতেই হবে
            except Exception as e:
                # Compensation fail করেছে। এখানে একজন মানুষ লাগবে। কখনো গিলে ফেলবেন না।
                logger.critical("COMPENSATION FAILED: %s", e)
                await self._alerts.page_oncall("saga_compensation_failed", error=str(e))
```

### Saga design-এর নিয়ম

১. **প্রতিটা ধাপ idempotent হতে হবে** — এটা retry হবেই
২. **প্রতিটা ধাপের একটা compensating action লাগবে** — সেটা ধাপের সাথেই design করুন, পরে নয়
৩. **Compensation-ও idempotent হতে হবে** আর কখনোই **নীরবে fail করা যাবে না**
৪. **কিছু ধাপ compensate করা যায় না** — আপনি একটা পাঠানো ইমেইল ফিরিয়ে আনতে পারবেন না। সেগুলো **সবার শেষে** রাখুন, অথবা business-এর ভাষায় ফেরানোর ব্যবস্থা করুন (একটা সংশোধনী ইমেইল পাঠান)।
৫. **Semantic lock / pending-state কৌশল ব্যবহার করুন** — record গুলো `PENDING` চিহ্নিত করুন, যাতে অন্য operation জানে এগুলো saga-র মাঝপথে
৬. **Saga-র state সংরক্ষণ করুন** — orchestrator saga-র মাঝপথে crash করলে তাকে আবার শুরু করতে হবে। একটা in-memory orchestrator মানে অপেক্ষমাণ একটা bug।
৭. **প্রতিটা ধাপে timeout বসান** — চিরকাল আটকে থাকা একটা saga একটা ব্যর্থ saga-র চেয়ে খারাপ
৮. **Saga-টা observable করুন** — চলমান saga, আটকে থাকা saga, আর compensation ব্যর্থতার একটা dashboard

### Operation-এর ক্রম কোথায় রাখবেন

ধাপগুলো এমনভাবে সাজান যাতে **সবচেয়ে বেশি fail করার সম্ভাবনা** আর **সবচেয়ে সহজে compensate করার মতো** গুলো আগে আসে।

```
খারাপ:  card charge → inventory reserve → (stock-এ নেই) → refund
        Customer একটা charge আর একটা refund দেখেন। Support ticket।

ভালো:  inventory reserve → card authorise → ship → payment CAPTURE
       Authorisation টাকা না নিয়েই আটকে রাখে; একটা auth ছেড়ে দেওয়া
       customer-এর চোখে পড়ে না। এই কারণেই আসল payment সিস্টেম
       authorise আর capture আলাদা করে।
```

ওই একটামাত্র ক্রম বদল আপনার বেশিরভাগ compensation-এর যন্ত্রণা সরিয়ে দেয়। **Business design কারিগরি চতুরতাকে হারায়।**

### টুল

এড়াতে পারলে নিজের হাতে একটা টেকসই orchestrator বানাবেন না: **Temporal**, **AWS Step Functions**, **Azure Durable Functions**, **Camunda/Zeebe**, **MassTransit Saga**, **NServiceBus Saga**। এরা আপনাকে persistence, retry, timeout, versioning আর একটা দৃশ্যমান ইতিহাস বিনামূল্যে দেয়।

---

## ৫.৮ Reliability pattern 🟢

এগুলো দৈনন্দিন টুল। সবগুলো ঝাড়া মুখস্থ জানুন।

### Timeout

**আপনার পুরো সিস্টেমের সবচেয়ে গুরুত্বপূর্ণ আর সবচেয়ে অবহেলিত setting।**

```python
# বিপজ্জনক — বেশিরভাগ HTTP client-এ default-এ কোনো timeout নেই বা খুব লম্বা
response = requests.get(url)          # চিরকাল ঝুলে থাকতে পারে

# সঠিক
response = requests.get(url, timeout=(3.0, 10.0))   # (connect, read)
```

**Timeout কীভাবে বাছবেন:** dependency-র p99 latency মাপুন, তারপর timeout তার একটু উপরে বসান (p99 × ১.৫ একটা যুক্তিসঙ্গত শুরু)। "৩০ সেকেন্ড কারণ সেটা নিরাপদ মনে হয়" নয় — একটা ৩০ সেকেন্ডের timeout মানে ৩০ সেকেন্ড ধরে একটা thread আটকে, একটা connection আটকে, আর একজন ব্যবহারকারী অপেক্ষমাণ।

**Cascading timeout-এর নিয়ম:** যত গভীরে যাবেন timeout তত **কমতে** হবে।

```
User          → ১০ সেকেন্ড বাজেট
  API Gateway → ৯ সেকেন্ড
    Service A → ৬ সেকেন্ড
      Service B → ৩ সেকেন্ড
        Database → ১ সেকেন্ড
```

ভেতরের একটা call-এর timeout বাইরেরটার চেয়ে লম্বা হলে বাইরেরটা আগে হাল ছেড়ে দেয় আর ভেতরের কাজটা নষ্ট হয় — অথচ সম্পদ ধরে রাখে। আরও ভালো, call-এর শৃঙ্খলে একটা **deadline** (এমন একটা পরম সময় যার পরে উত্তরটা অকেজো) পাঠান, যেমন gRPC করে।

### Retry

Retry ক্ষণস্থায়ী ব্যর্থতাকে সাফল্যে পরিণত করে। আবার অসাবধানে করলে এটা একটা ছোট সমস্যাকে একটা outage-এও পরিণত করে।

```python
# ভুল — এটা আপনার নিজের dependency-র উপর একটা DDoS
for attempt in range(5):
    try:
        return call_service()
    except Exception:
        continue            # কোনো দেরি নেই, jitter নেই, non-idempotent call retry করছে
```

```python
# সঠিক
async def call_with_retry(fn, *, max_attempts=3, base_delay=0.2, max_delay=5.0):
    for attempt in range(max_attempts):
        try:
            return await fn()
        except NonRetryableError:                 # 400, 401, 404, 422 — কখনো retry নয়
            raise
        except RetryableError as e:               # 429, 502, 503, 504, timeout
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = delay * (0.5 + random.random())          # FULL JITTER
            if (ra := getattr(e, "retry_after", None)):      # Retry-After মানুন
                delay = max(delay, ra)
            await asyncio.sleep(delay)
```

**Retry-র নিয়ম:**

১. **শুধু idempotent operation retry করুন।** একটা non-idempotent POST retry করলে দ্বিগুণ charge হয়।
২. **শুধু retryable error retry করুন।** 400/404/422 কখনোই সফল হবে না; সেগুলো retry করা সব নষ্ট করে।
৩. **Exponential backoff** — ২০০ ms, ৪০০ ms, ৮০০ ms, ১.৬ s…
৪. **Jitter যোগ করুন** — এটা ঐচ্ছিক নয়। নিচে দেখুন।
৫. **চেষ্টার সংখ্যা সীমিত করুন** (৩ সাধারণত ঠিক) আর মোট সময়ও সীমিত করুন
৬. **প্রতিটা স্তরে retry করবেন না।** ৩টা retry × ৪টা স্তর = নিচের service-এ ৮১টা call। **একটা** স্তরে retry করুন, সাধারণত সবচেয়ে বাইরেরটা যার যথেষ্ট প্রেক্ষাপট আছে।
৭. **`Retry-After` header মানুন**

**Jitter কেন গুরুত্বপূর্ণ — thundering herd:**

```
JITTER ছাড়া: একটা service ঝাঁকুনি খেল। ৫,০০০ client t=০-তে fail করল।
  সবাই t=১ সেকেন্ডে retry করল   → ৫,০০০ একসাথে request → service আবার মরল
  সবাই t=২ সেকেন্ডে retry করল   → ৫,০০০ একসাথে request → আবার মরল
  → সমলয়ে retry-ঝড়; service আর কখনোই ফেরে না

FULL JITTER সহ: retry গুলো [০, delay]-এর মধ্যে এলোমেলোভাবে ছড়ায়
  → মসৃণ load; service ফিরে আসে
```

AWS এটার চূড়ান্ত বিশ্লেষণ প্রকাশ করেছে; "full jitter" (`sleep = random(0, base * 2^attempt)`) প্রায় সব ক্ষেত্রেই সবচেয়ে ভালো কাজ করে।

### Circuit Breaker ⭐

**সমস্যা:** একটা dependency বন্ধ। প্রতিটা request একটা timeout-এর জন্য অপেক্ষা করে, একটা thread খরচ করে। আপনার thread শেষ। এখন *আপনি*ও বন্ধ। ব্যর্থতা ছড়িয়ে গেছে।

**সমাধান:** একটা ব্যর্থ dependency-কে call করা বন্ধ করুন, দ্রুত fail করুন, আর মাঝে মাঝে দেখুন এটা ফিরেছে কিনা।

```
        ┌─────────────────────────────────────────────┐
        │                                             │
        ▼                                             │
    ┌────────┐  ব্যর্থতা > সীমা         ┌────────┐     │
    │ CLOSED │ ──────────────────────► │  OPEN  │     │
    │(স্বাভাবিক)│                        │(দ্রুত   │     │
    └────────┘ ◄────────────────────── │ fail)  │     │
        ▲       probe সফল হলো           └───┬────┘     │
        │                                   │ cooldown │
        │       ┌───────────┐               │ এর পর    │
        └────── │ HALF-OPEN │ ◄─────────────┘          │
                │ (১–৫টা যেতে│                          │
                │  দিন)      │──── probe ব্যর্থ ─────────┘
                └───────────┘
```

```csharp
// Polly (.NET) — কয়েক লাইনে production-মানের
var pipeline = new ResiliencePipelineBuilder<HttpResponseMessage>()
    .AddRetry(new RetryStrategyOptions<HttpResponseMessage>
    {
        MaxRetryAttempts = 3,
        BackoffType = DelayBackoffType.Exponential,
        UseJitter = true,
        Delay = TimeSpan.FromMilliseconds(200),
    })
    .AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
    {
        FailureRatio = 0.5,                          // ৫০% call fail করছে
        MinimumThroughput = 20,                      // ...অন্তত ২০টা call-এর উপর
        SamplingDuration = TimeSpan.FromSeconds(30),
        BreakDuration = TimeSpan.FromSeconds(15),    // তারপর probe
    })
    .AddTimeout(TimeSpan.FromSeconds(5))
    .Build();
```

**Design-এর নোট:**
- **প্রতি dependency-তে একটা breaker**, একটা বৈশ্বিক breaker নয়
- Open থাকলে পারলে **একটা fallback ফেরত দিন** (cache করা মান, default, সীমিত feature) — নইলে একটা পরিষ্কার error সহ দ্রুত fail করুন
- একটা breaker খুললে **একটা metric আর একটা alert দিন**। একটা খোলা breaker একটা আসল incident-এর সংকেত।
- `MinimumThroughput` এমনভাবে সমন্বয় করুন যাতে কম-traffic-এর একটা endpoint ২টা ব্যর্থতায় না খোলে

### Bulkhead

জাহাজের কামরার নামে: একটা কামরায় ফুটো হলে পুরো জাহাজ ডোবে না।

**সমস্যা:** একটা ধীর dependency পুরো thread pool খেয়ে ফেলে, তাই *অসম্পর্কিত* endpoint গুলোও fail করে।

```
BULKHEAD ছাড়া                       BULKHEAD সহ
┌──────────────────────┐            ┌──────┬──────┬──────────┐
│  ২০০টা shared thread  │            │  ৫০  │  ৫০  │   ১০০    │
│                      │            │vendor│ mail │ স্বাভাবিক │
│ ধীর vendor সব ২০০টাই  │            │ pool │ pool │  traffic │
│ খায় → সব মরে         │            └──────┴──────┴──────────┘
└──────────────────────┘            ধীর vendor তার ৫০টা নেয় আর থামে।
                                    বাকি ১৫০টা কাজ করতে থাকে।
```

Implementation: আলাদা thread pool, আলাদা connection pool, প্রতি dependency-তে concurrency সীমিত করা semaphore, অথবা — infrastructure স্তরে — প্রতি workload-এ আলাদা pod/instance।

### Rate Limiting

অতিরিক্ত traffic (বা একটা কোলাহলপূর্ণ tenant) থেকে নিজেকে রক্ষা করুন।

| Algorithm | কীভাবে | Trade-off |
|-----------|-----|-----------|
| **Fixed window** | প্রতি মিনিট-বালতিতে ১০০ request | সহজ; কিন্তু সীমানায় ২× ঝাঁকুনি দেয় (১১:৫৯:৫৯-এ ১০০ + ১২:০০:০০-এ ১০০) |
| **Sliding window log** | প্রতিটা request-এর timestamp জমা রাখুন | নিখুঁত; memory-ক্ষুধার্ত |
| **Sliding window counter** | দুটো window-র ভারযুক্ত মিশ্রণ | ভালো ভারসাম্য — **সাধারণ default** |
| **Token bucket** ⭐ | Token একটা হারে ভরে; একটা request একটা নেয় | **নিয়ন্ত্রিত ঝাঁকুনির সুযোগ দেয়** — সাধারণত সেরা UX |
| **Leaky bucket** | Request একটা নির্দিষ্ট হারে বেরোয় | Output পুরোপুরি মসৃণ করে; কোনো ঝাঁকুনি নয় |

```python
# Redis-এ token bucket, Lua দিয়ে atomic (concurrency-তে সঠিক)
TOKEN_BUCKET = """
local key      = KEYS[1]
local rate     = tonumber(ARGV[1])   -- প্রতি সেকেন্ডে token
local capacity = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])

local b       = redis.call('HMGET', key, 'tokens', 'ts')
local tokens  = tonumber(b[1]) or capacity
local last    = tonumber(b[2]) or now

tokens = math.min(capacity, tokens + (now - last) * rate)
local allowed = tokens >= cost
if allowed then tokens = tokens - cost end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) * 2)
return { allowed and 1 or 0, tokens }
"""
```

**সবসময় প্রচলিত header গুলো ফেরত দিন**, যাতে client ভালো আচরণ করতে পারে:

```
HTTP/1.1 429 Too Many Requests
RateLimit-Limit: 1000
RateLimit-Remaining: 0
RateLimit-Reset: 42
Retry-After: 42
```

### Load Shedding

অতিরিক্ত চাপে **ইচ্ছাকৃতভাবে কিছু কাজ প্রত্যাখ্যান করুন**, যাতে বাকিটা সফল হয়।

Rate limiting প্রতি client-এ আর আগে থেকে সম্মত। Load shedding হলো বর্তমান স্বাস্থ্যের ভিত্তিতে **পুরো সিস্টেমের আত্মরক্ষা**।

```python
async def maybe_shed(request) -> bool:
    if queue_depth() > CRITICAL:
        return request.priority != Priority.CRITICAL   # শুধু payment/auth রাখুন
    if queue_depth() > HIGH:
        return request.priority == Priority.LOW        # analytics, prefetch ফেলে দিন
    return False
```

> **স্বজ্ঞাবিরোধী কিন্তু অত্যাবশ্যক:** ৭০% request ভালোভাবে পরিবেশন করা ১০০% request এত ধীরে পরিবেশন করার চেয়ে অনেক ভালো যে সবগুলোই timeout হয়ে যায়। যে সিস্টেম কখনো load shed করে না, সেটা ধাপে ধাপে দুর্বল হওয়ার বদলে পুরোপুরি ভেঙে পড়ে।

উন্নত: **adaptive concurrency limit** (Netflix-এর পদ্ধতি) — পর্যবেক্ষণ করা latency থেকে সুস্থ concurrency-র সীমা অনুমান করুন, আর তার উপরে shed করুন।

### Backpressure

একটা দ্রুত producer একটা ধীর consumer-কে ভাসিয়ে দিচ্ছে। Memory শেষ হওয়া পর্যন্ত buffer করার বদলে **পেছনে ঠেলুন**।

```
Producer ──► [ Queue ] ──► Consumer (ধীর)
                 │
    Queue বাড়ে → memory বাড়ে → OOM kill → সবকিছু হারায়
```

কৌশল:
- **সীমাবদ্ধ queue** — ভরে গেলে আটকান বা প্রত্যাখ্যান করুন (production-এ কখনো unbounded queue নয়)
- **TCP flow control** — বিনামূল্যে, অন্তর্নির্মিত, যদি আপনি stream ব্যবহার করেন
- **Reactive Streams / `request(n)`** — consumer বলে সে কতটা নিতে পারে
- **গ্রহণ থামান** — socket/broker থেকে পড়া বন্ধ করুন; broker data ধরে রাখে (এটা সেভাবেই বানানো)
- উপরে **503 / 429 ফেরত দিন**

> **নিয়ম: queue একটা ধীর consumer-এর সমাধান নয় — এটা একটা শক শোষক।** Queue যদি সীমাহীনভাবে বাড়ে, তাহলে আপনার ক্ষমতার সমস্যা, buffering-এর সমস্যা নয়। Queue-র গভীরতা আর *queue-র বয়স* (সবচেয়ে পুরনো message কত পুরনো) — দুটোতেই alert দিন; বয়সটাই ভালো সংকেত।

### Graceful Degradation

পুরোপুরি fail করার বদলে কার্যকারিতা কমান।

| পূর্ণ সেবা | সীমিত mode |
|--------------|---------------|
| ব্যক্তিগতকৃত recommendation | সাধারণ bestseller |
| সরাসরি inventory-র সংখ্যা | "Stock-এ আছে" / "Stock-এ নেই" |
| Real-time fraud score | নিয়ম-ভিত্তিক fallback + রিভিউয়ের জন্য চিহ্নিত |
| সমৃদ্ধ product পাতা | Cache করা static সংস্করণ |
| Filter আর facet সহ search | মৌলিক keyword search |

```python
async def get_recommendations(user_id: str) -> list[Product]:
    try:
        return await ml_service.recommend(user_id, timeout=0.3)
    except (TimeoutError, ServiceUnavailable):
        metrics.increment("recommendations.degraded")
        return await cache.get_or_compute("bestsellers", ttl=3600)
```

**Design-এর নিয়ম:** প্রতিটা feature-এর জন্য তার **সীমিত mode** আর তার **ন্যূনতম কার্যকর পথ** জানুন। একজন customer-এর মূল লেনদেন শেষ করতে সবচেয়ে ছোট কোন component-গুচ্ছ কাজ করতেই হবে? সবার আগে ওই পথটা রক্ষা করুন।

---

## ৫.৯ Idempotency 🟢 — সবচেয়ে গুরুত্বপূর্ণ ব্যবহারিক ধারণা

**সংজ্ঞা:** একটা operation N বার করলে যা হয়, একবার করলেও তাই হয়।

**কেন গুরুত্বপূর্ণ:** কারণ retry অনিবার্য, আর duplicate অনিবার্য, তাই **idempotency-ই একটা অনির্ভরযোগ্য নেটওয়ার্ককে নিরাপদ করে।** এটা ছাড়া at-least-once delivery মানে দ্বিগুণ charge।

### কোন HTTP method গুলো idempotent?

| Method | নিরাপদ (কিছু বদলায় না) | Idempotent | নোট |
|--------|-----------------|-----------|-------|
| GET | ✅ | ✅ | |
| HEAD | ✅ | ✅ | |
| PUT | ❌ | ✅ | "এই মানে সেট করো" — বারবার করলে ক্ষতি নেই |
| DELETE | ❌ | ✅ | দ্বিতীয় delete → ৪০৪ বা ২০৪; *state* একই |
| **POST** | ❌ | **❌** | "আরেকটা বানাও" — **এটাই বিপজ্জনকটা** |
| PATCH | ❌ | ❌* | `{"balance": 100}` idempotent; `{"increment": 10}` নয় |

### POST-কে idempotent করা — Idempotency Key pattern

Stripe, PayPal, Adyen আর প্রতিটা গুরুতর payments API এভাবেই কাজ করে। এটা শিখুন আর implement করুন।

```
Client প্রতিটা যৌক্তিক operation-এ একটা অনন্য key (UUID) বানায় আর পাঠায়:

POST /v1/charges
Idempotency-Key: 8f14e45f-ea2a-4f0e-b1d6-2c8e3f1a9b7d
{ "amount": 5000, "currency": "usd", "customer": "cus_123" }
```

```python
async def create_charge(request: ChargeRequest, idem_key: str) -> ChargeResponse:
    fingerprint = hashlib.sha256(request.canonical_json().encode()).hexdigest()

    async with db.transaction():
        existing = await db.fetch_one(
            "SELECT * FROM idempotency_keys WHERE key = $1 FOR UPDATE", idem_key)

        if existing:
            # একই key কিন্তু আলাদা body = একটা client-এর bug। কখনো নীরবে মানবেন না।
            if existing["fingerprint"] != fingerprint:
                raise IdempotencyKeyReuseError(idem_key)
            if existing["status"] == "completed":
                return ChargeResponse.parse_raw(existing["response"])   # replay
            if existing["status"] == "in_progress":
                raise ConcurrentRequestError(idem_key)                  # 409, পরে retry

        await db.execute(
            """INSERT INTO idempotency_keys (key, fingerprint, status, created_at)
               VALUES ($1, $2, 'in_progress', now())""", idem_key, fingerprint)

    try:
        result = await payment_gateway.charge(request)                  # আসল কাজ
        await db.execute(
            """UPDATE idempotency_keys
               SET status='completed', response=$2, completed_at=now()
               WHERE key=$1""", idem_key, result.json())
        return result
    except Exception:
        await db.execute("DELETE FROM idempotency_keys WHERE key=$1", idem_key)
        raise
```

```sql
CREATE TABLE idempotency_keys (
    key          TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,          -- request body-র hash
    status       TEXT NOT NULL,          -- in_progress | completed
    response     JSONB,
    created_at   TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX ON idempotency_keys (created_at);   -- পরিষ্কারের জন্য; key ~২৪-৭২ ঘণ্টা রাখুন
```

**মূল design পয়েন্ট:**
- **Client key বানায়** (এটাকে client-এর নিজের retry-তেও টিকতে হবে)
- **Response জমা রাখুন**, যাতে একটা retry হুবহু একই উত্তর পায়
- Request-এর একটা **fingerprint** জমা রাখুন — একই key + আলাদা body একটা bug, আর আপনাকে সেটা জোরালোভাবে প্রত্যাখ্যান করতে হবে
- ২৪–৭২ ঘণ্টা পর **key-র মেয়াদ শেষ করুন**
- পুরো জিনিসটা **transactional** হতে হবে, নইলে আপনি শুধু race condition-টা সরিয়ে দিলেন

### Idempotency অর্জনের অন্য উপায়

**১. স্বাভাবিক idempotency — operation-টাকেই নিরাপদভাবে design করুন**

```sql
-- Idempotent নয়
UPDATE accounts SET balance = balance + 100 WHERE id = 42;
-- Idempotent (পরম মান, আর একটা version দিয়ে রক্ষিত)
UPDATE accounts SET balance = 500, version = 8 WHERE id = 42 AND version = 7;
```

**২. Message consumer-এর জন্য deduplication table**

```python
async def handle_message(msg: Message) -> None:
    try:
        await db.execute(
            "INSERT INTO processed_messages (message_id, processed_at) VALUES ($1, now())",
            msg.id)
    except UniqueViolation:
        logger.info("duplicate message %s ignored", msg.id)
        return                                    # আগেই সামলানো হয়েছে
    await do_the_work(msg)
```

ক্রমের সূক্ষ্মতাটা খেয়াল করুন: আগে insert তারপর কাজ করলে মাঝখানে crash করলে কাজ হারানোর ঝুঁকি; আগে কাজ তারপর insert করলে দুইবার করার ঝুঁকি। কাজটা যখন একটা database পরিবর্তন, তখন **দুটোই একটা transaction-এর ভেতরে** করাই সঠিক উত্তর। কাজটা যখন একটা বাইরের call, তখন আপনার আবার নিচের দিকে idempotency লাগবে — আর ঠিক এই কারণেই প্রতিটা ভালো API একটা idempotency key দেয়।

**৩. Upsert / শর্তসাপেক্ষ write**

```sql
INSERT INTO verification_results (session_id, score, decided_at)
VALUES ($1, $2, now())
ON CONFLICT (session_id) DO NOTHING;     -- দ্বিতীয় চেষ্টায় কিছুই বদলায় না
```

**৪. State machine-এর প্রহরী**

```python
def mark_shipped(self) -> None:
    if self.status is OrderStatus.SHIPPED:
        return                      # আগেই আছে — গঠনগতভাবেই idempotent
    if self.status is not OrderStatus.PAID:
        raise InvalidTransition(self.status, OrderStatus.SHIPPED)
    self.status = OrderStatus.SHIPPED
```

### Exactly-once, সৎভাবে

> **"Exactly-once delivery"-র কোনো অস্তিত্ব নেই।**
> **"Exactly-once *processing*"-এর আছে** — আর এটা তৈরি হয় **at-least-once delivery + idempotent consumer** দিয়ে (সাথে, যেখানে পাওয়া যায়, এমন transactional write যা কাজ আর offset একসাথে atomically commit করে)।

একজন ভেন্ডর যখন exactly-once দাবি করেন, তিনি এটাই বোঝান। এখন আপনি জানেন তাঁকে কী জিজ্ঞেস করতে হবে।

---

## ৫.১০ Service discovery আর health 🟡

একটা গতিশীল পরিবেশে instance অনবরত আসে আর যায়। Hard-code করা IP হলো ৫ নম্বর ভ্রান্তি।

**Client-side discovery:** client একটা registry-কে জিজ্ঞেস করে, একটা instance বাছে, আর সরাসরি call করে। (Netflix Eureka + Ribbon।) বেশি নিয়ন্ত্রণ, বেশি client logic।

**Server-side discovery:** client একটা স্থিতিশীল ঠিকানায় call করে; একটা load balancer/proxy সেটা সমাধান করে। (Kubernetes Service, AWS ALB।) সহজ client — **এটাই আধুনিক default।**

**Kubernetes এটা DNS + endpoint দিয়ে করে:** আপনি `http://billing-service`-এ call করেন, kube-DNS সেটা সমাধান করে, kube-proxy একটা সুস্থ pod-এ load-balance করে। Registration আর deregistration স্বয়ংক্রিয়, readiness probe দ্বারা চালিত।

---

## ৫.১১ সব একসাথে: একটা সহনশীল call

```python
class ResilientVendorClient:
    """এই অধ্যায়ের প্রতিটা pattern, একটা বাস্তবসম্মত class-এ।"""

    def __init__(self, http, cache, breaker, limiter, metrics):
        self._http, self._cache = http, cache
        self._breaker, self._limiter, self._metrics = breaker, limiter, metrics
        self._semaphore = asyncio.Semaphore(50)          # BULKHEAD

    async def verify(self, doc: Document, request_id: str) -> VerificationResult:
        cache_key = f"verify:{doc.content_hash}"

        if (hit := await self._cache.get(cache_key)) is not None:   # CACHE
            self._metrics.increment("vendor.cache_hit")
            return VerificationResult.parse_raw(hit)

        if not await self._limiter.allow("vendor_api", cost=1):      # RATE LIMIT
            raise ThrottledError(retry_after=self._limiter.reset_in("vendor_api"))

        if self._breaker.is_open:                                    # CIRCUIT BREAKER
            self._metrics.increment("vendor.circuit_open")
            return self._degraded_result(doc)                        # GRACEFUL DEGRADATION

        async with self._semaphore:                                  # BULKHEAD
            for attempt in range(3):                                 # RETRY
                try:
                    resp = await self._http.post(
                        "/verify",
                        json=doc.to_vendor_payload(),
                        headers={
                            "Idempotency-Key": request_id,           # IDEMPOTENCY
                            "X-Correlation-Id": request_id,          # TRACEABILITY
                        },
                        timeout=Timeout(connect=2.0, read=8.0),      # TIMEOUT
                    )
                    resp.raise_for_status()
                    result = VerificationResult.from_vendor(resp.json())  # ACL

                    self._breaker.record_success()
                    await self._cache.set(cache_key, result.json(), ttl=3600)
                    return result

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    self._breaker.record_failure()
                    if attempt == 2:
                        self._metrics.increment("vendor.exhausted_retries")
                        return self._degraded_result(doc)
                    delay = 0.2 * (2 ** attempt) * (0.5 + random.random())  # JITTER
                    await asyncio.sleep(delay)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code < 500:                 # retry করার মতো নয়
                        self._breaker.record_success()               # তাদের দোষ, আমাদের নয়
                        raise VendorRejectedError(e.response.json())
                    self._breaker.record_failure()
                    if attempt == 2:
                        return self._degraded_result(doc)
                    await asyncio.sleep(0.2 * (2 ** attempt) * (0.5 + random.random()))

    def _degraded_result(self, doc: Document) -> VerificationResult:
        """ভেন্ডর নেই → ব্যবহারকারীকে fail করানোর বদলে manual review-এর queue-তে দিন।"""
        return VerificationResult.manual_review(
            reason="automated verification temporarily unavailable")
```

---

## ৫.১২ সাধারণ ভুল

১. **কোনো timeout নেই** — cascading ব্যর্থতার সবচেয়ে সাধারণ কারণ
২. **Non-idempotent operation retry করা** — দ্বিগুণ charge, duplicate order
৩. **Jitter ছাড়া retry** — সমলয়ে thundering herd; service আর কখনো ফেরে না
৪. **প্রতিটা স্তরে retry** — ৩টা retry × ৪টা স্তর = নিচে ৮১টা request
৫. **Event সাজাতে wall-clock timestamp ব্যবহার** — LWW-র মাধ্যমে নীরব data ক্ষতি
৬. **সময়কাল মাপতে `time.time()`** — NTP-র সমন্বয় ঋণাত্মক সময়কাল দেয়
৭. **বিশ্বাস করা যে "exactly once" বলে কিছু আছে** — বরং at-least-once + idempotency-র জন্য design করুন
৮. **একটা মাত্র Redis-এ distributed lock** — partition-এ নিরাপদ নয়; সঠিকতা নির্ভর করলে etcd/ZooKeeper ব্যবহার করুন
৯. **Service বা ইন্টারনেট জুড়ে 2PC** — আটকে যায়, ভঙ্গুর, আর সাধারণত unavailable
১০. **State সংরক্ষণ ছাড়া saga** — orchestrator restart করল আর saga চিরকালের জন্য হারিয়ে গেল
১১. **Compensation design ছাড়া saga** — "আমরা পরে rollback যোগ করব" কখনোই হয় না
১২. **Unbounded queue** — backpressure-কে একটা out-of-memory kill-এ পরিণত করে
১৩. **জোড় সংখ্যার consensus cluster** — N=৪ আপনাকে N=৩-এর চেয়ে কিছুই দেয় না
১৪. **কোনো circuit breaker নেই** — একটা ধীর dependency আপনার thread শেষ করে আপনাকে নামিয়ে দেয়
১৫. **নেটওয়ার্ক নিরাপদ ধরে নেওয়া** কারণ এটা "ভেতরের"

---

## ৫.১৩ আর্কিটেক্টের চেকলিস্ট

- [ ] প্রতিটা বাইরের call-এ একটা স্পষ্ট timeout আছে
- [ ] গভীরতার সাথে timeout কমে (বা deadline পাঠানো হয়)
- [ ] Retry policy নির্ধারিত: কোন error, কতবার, **jitter সহ** backoff
- [ ] Retry ঠিক **একটা** স্তরে হয়
- [ ] প্রতিটা retryable operation idempotent (key, dedup table, বা স্বাভাবিক)
- [ ] প্রতিটা বাইরের dependency-তে circuit breaker, একটা metric আর একটা alert সহ
- [ ] Bulkhead গুরুত্বপূর্ণ আর অগুরুত্বপূর্ণ dependency আলাদা করে
- [ ] প্রান্তে rate limiting, সঠিক ৪২৯ header সহ
- [ ] Load shedding নির্ধারিত, একটা অগ্রাধিকারের ক্রম সহ
- [ ] সব queue সীমাবদ্ধ; queue-র গভীরতা **আর queue-র বয়সে** alert
- [ ] প্রতিটা অ-গুরুত্বপূর্ণ dependency-র জন্য সীমিত mode নির্ধারিত
- [ ] ন্যূনতম কার্যকর পথ (মূল লেনদেন) চিহ্নিত আর সুরক্ষিত
- [ ] Consistency model **প্রতি operation-এ** বাছা, আর লেখা আছে
- [ ] Distributed transaction saga ব্যবহার করে, compensation আগেভাগে design করা
- [ ] Saga-র state সংরক্ষিত আর আবার শুরু করার যোগ্য; আটকে থাকা saga-তে alert আছে
- [ ] Consensus cluster বিজোড় আকারের (৩/৫/৭)
- [ ] Correlation ID প্রতিটা hop-এ যায়
- [ ] সময়কালের জন্য monotonic clock ব্যবহৃত

---

## ৫.১৪ নিজেকে যাচাই

১. "Fail করেছে" আর "সফল হয়েছে কিন্তু response হারিয়েছে" — এই দুটো আপনি কখনো আলাদা করতে পারবেন না কেন? এর থেকে কী আসে?
২. আটটা ভ্রান্তির তালিকা দিন। বাস্তবে কোনটা আপনাকে সবচেয়ে বেশি কামড়ায়?
৩. CAP সঠিকভাবে বলুন ("দুটো বাছুন" নয়)। তারপর PACELC বলুন আর ব্যাখ্যা করুন কেন সেটা বেশি কাজের।
৪. আপনার নিজের সিস্টেমে এমন একটা operation দিন যাতে linearizability লাগে আর একটা যাতে শুধু eventual consistency লাগে।
৫. চারটা session guarantee কী কী, আর এগুলো কেন eventual consistency-কে ব্যবহারযোগ্য করে?
৬. একটা consensus cluster-এ বিজোড় সংখ্যক node থাকতে হবে কেন?
৭. Split brain কী, আর কোন দুটো কৌশল এটা ঠেকায়?
৮. Service জুড়ে 2PC সাধারণত ভুল উত্তর কেন? তিনটা নির্দিষ্ট সমস্যার নাম বলুন।
৯. একটা হোটেল বুকিংয়ের (ঘর + payment + নিশ্চিতকরণ ইমেইল) জন্য একটা saga design করুন। ইমেইলটা কোথায় রাখবেন, আর কেন?
১০. Idempotency Key pattern শুরু থেকে শেষ পর্যন্ত ব্যাখ্যা করুন। Request body-র একটা fingerprint কেন জমা রাখবেন?
১১. Retry-তে jitter ছাড়া কী হয়? Timeline-টা আঁকুন।
১২. Circuit breaker-এর অবস্থা আর পরিবর্তন ব্যাখ্যা করুন। একটা breaker খুললে কী হওয়া উচিত?
১৩. Database যাচাই করা একটা liveness probe কেন বিপজ্জনক? (অধ্যায় ০৪, কিন্তু এটা এখানেও প্রাসঙ্গিক।)
১৪. কেউ বলছেন তাঁদের queue "exactly-once delivery" দেয়। আপনি তাঁদের কী জিজ্ঞেস করবেন?

---

## ৫.১৫ মূল কথাগুলো

- **আপনি ব্যর্থতা আর হারানো response-এর পার্থক্য করতে পারবেন না।** বাকি সবকিছু এখান থেকেই আসে।
- **Partial failure একটা distributed system-এর স্বাভাবিক অবস্থা**, ব্যতিক্রম নয়
- **কোনো "এখন" নেই।** সময়কালের জন্য monotonic clock ব্যবহার করুন; কখনো wall clock দিয়ে event সাজাবেন না।
- **CAP: partition-এর সময় error নাকি পুরনো data, বাছুন।** PACELC: বাকি সময়ে latency নাকি consistency, বাছুন।
- **Consistency প্রতি operation-এ বাছা হয়**, প্রতি সিস্টেমে নয়
- **Quorum = সংখ্যাগরিষ্ঠতা।** এটাই split brain ঠেকায়। শুধু বিজোড় আকারের cluster।
- **কখনো নিজের consensus লিখবেন না।** etcd/ZooKeeper/Consul ব্যবহার করুন।
- **Saga, 2PC নয়।** ধাপের সাথেই compensation design করুন। ধাপগুলো এমনভাবে সাজান যাতে সবচেয়ে কঠিন-বাতিলযোগ্যটা শেষে থাকে।
- **Idempotency নির্ভরযোগ্যতার ভিত্তি।** At-least-once delivery + idempotent processing = exactly-once processing।
- **Timeout, jitter সহ retry, circuit breaker, bulkhead, rate limit, load shed, graceful degradation।** এই সাতটাই আপনার দৈনন্দিন টুলকিট।
- **৭০% ভালোভাবে পরিবেশন করা ১০০% খারাপভাবে পরিবেশন করার চেয়ে ভালো।**

---

**পরবর্তী:** [অধ্যায় ০৬ — Messaging ও Event-Driven Architecture](06-messaging-and-event-driven-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 05](../05-distributed-systems.md) · **[সূচিপত্র](README.md)**
