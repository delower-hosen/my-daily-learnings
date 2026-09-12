# অধ্যায় ০৪ — System Design-এর মূল বিষয় 🟢

> এটাই কেন্দ্রীয় অধ্যায়। এর আগের সবকিছু ছিল প্রস্তুতি; এর পরের সবকিছু এক এক দিকে গভীরতা।
> শেষে আপনি *"এমন একটা সিস্টেম design করুন যেটা Y কোটি ব্যবহারকারীর জন্য X করে"* নিয়ে ৪৫ মিনিটে একটা যুক্তিযোগ্য design দাঁড় করাতে পারবেন।

---

## ৪.০ Design-এর প্রক্রিয়া

```
১. REQUIREMENTS      → functional, তারপর non-functional, তারপর constraint
২. ESTIMATE          → ব্যবহারকারী, RPS, storage, bandwidth  (খামের পেছনের হিসাব)
৩. API DESIGN        → operation গুলো কী? কী ঢোকে, কী বেরোয়?
৪. DATA MODEL        → আমরা কী জমা রাখি, কোথায়, কোন আকারে?
৫. HIGH-LEVEL DESIGN → বাক্স আর তীর, সুখী পথ
৬. DEEP DIVE         → ২–৩টা কঠিন অংশ
৭. SCALE IT          → ১০ গুণে কোথায় ভাঙে? সেটা ঠিক করুন।
৮. FAILURE MODE      → প্রতিটা বাক্স মরলে কী হয়?
৯. TRADE-OFF         → কী ছেড়ে দিলেন, জোরে বলুন
```

ক্রম অনুযায়ী চলুন। সবচেয়ে সাধারণ ব্যর্থতা হলো **১ আর ২ নম্বর ধাপ না করেই ৫ নম্বরে লাফ দেওয়া** — তখন আপনি নিজের বানানো একটা scale-এর জন্য design করে ফেলেন।

---

# পর্ব ১ — Requirement আর Estimation

## ৪.১ দ্রুত requirement সংগ্রহ

তত্ত্বটা অধ্যায় ০০-এ দেখেছেন। এই যে *ব্যবহারিক* সংস্করণ — প্রথম ১০ মিনিটে আপনি আসলে যে প্রশ্নগুলো করবেন।

### শুরুর ১০টা প্রশ্ন

১. **কে ব্যবহার করে?** (ভোক্তা? ভেতরের কর্মী? মেশিন? কতজন?)
২. **সবচেয়ে গুরুত্বপূর্ণ operation কোনটা?** (যেটা কখনোই ধীর বা ভুল হতে পারবে না)
৩. **Read-ভারী না write-ভারী?** আর অনুপাত কত?
৪. **কত data, আর কত দ্রুত বাড়ে?**
৫. **Data কতটা তাজা হতে হবে?** (real-time? সেকেন্ড? রাতের batch-ই চলবে?)
৬. **Peak বনাম average traffic কত?** (আর peak কখন — প্রতিদিন? শুক্রবার সন্ধ্যা? Black Friday?)
৭. **কী কখনো হারানো যাবে না?** (payment, audit record) বনাম **কী ফেলে দেওয়া যায়?** (analytics-এর click)
৮. **এক ঘণ্টা বন্ধ থাকলে কী হয়?**
৯. **কোনো compliance-এর নিয়ম?** (data কোন দেশে, কতদিন রাখা, PII)
১০. **বাজেট আর deadline কত?**

### Scope নিয়ন্ত্রণ

Design আলোচনায় (আর ইন্টারভিউতে) scope সবসময় বেশি বড় থাকে। **স্পষ্টভাবে সংকুচিত করুন আর সেটা বলুন:**

> "এই design-এ আমি একটা message পোস্ট করা আর একটা timeline পড়া নিয়ে কাজ করব। Authentication, search আর ads আমি scope-এর বাইরে রাখছি, আর কোথায় সেগুলো যুক্ত হতো সেটা উল্লেখ করব।"

এই বাক্যটা আপনাকে সিনিয়র দেখায়। সবকিছু design করার চেষ্টা আপনাকে জুনিয়র দেখায়।

---

## ৪.২ খামের পেছনের হিসাব (back-of-envelope estimation) 🟢

এটা আপনাকে দ্রুত আর মুখে মুখে করতে পারতে হবে। সঠিক হওয়াটা মূল কথা নয় — মূল কথা হলো **মাত্রার এক ধাপের মধ্যে** থাকা, যাতে আপনি জানেন আপনার একটা server লাগবে নাকি তিনশটা।

### যে সংখ্যাগুলো মুখস্থ করবেন

**Latency (বিখ্যাত "প্রতিটা প্রোগ্রামারের জানা উচিত এমন সংখ্যা", আধুনিক hardware-এর জন্য গোল করা):**

| Operation | সময় | স্বজ্ঞা |
|-----------|------|-----------|
| L1 cache reference | ১ ns | — |
| Branch mispredict | ৩ ns | — |
| L2 cache reference | ৪ ns | — |
| Mutex lock/unlock | ১৭ ns | — |
| Main memory reference | ১০০ ns | **RAM-ই ভিত্তি** |
| ১ KB compress (Snappy) | ২ µs | |
| ১ Gbps নেটওয়ার্কে ১ KB পাঠানো | ১০ µs | |
| SSD থেকে এলোমেলোভাবে ৪ KB পড়া | ১৫০ µs | **SSD ≈ RAM-এর চেয়ে ১,৫০০× ধীর** |
| Memory থেকে ধারাবাহিকভাবে ১ MB পড়া | ২৫০ µs | |
| একই datacenter-এ round trip | ৫০০ µs | **০.৫ ms** |
| SSD থেকে ধারাবাহিকভাবে ১ MB পড়া | ১ ms | |
| Disk seek (ঘূর্ণায়মান HDD) | ১০ ms | **HDD ≈ RAM-এর চেয়ে ১,০০,০০০× ধীর** |
| HDD থেকে ধারাবাহিকভাবে ১ MB পড়া | ২০ ms | |
| Round trip CA → নেদারল্যান্ডস → CA | ১৫০ ms | **আলোর গতিই সীমা** |

**এখান থেকে যে তিনটা আঙুলের নিয়ম আসে:**
১. Memory দ্রুত, disk ধীর, **network আরও ধীর**, মহাদেশ পেরোনো সবচেয়ে ধীর
২. **ধারাবাহিক এলোমেলোর চেয়ে ১০–১০০× দ্রুত** — যে কোনো storage-এ
৩. **Round trip এড়ান।** ১০০টা row আনা একটা call প্রতিবার ১টা row আনা ১০০টা call-কে হারায়। (এটাই N+1 সমস্যা, আর ধীর app-এর ১ নম্বর কারণ।)

**Availability:**

| SLA | বছরে downtime | মাসে downtime | সপ্তাহে downtime |
|-----|---------------|----------------|---------------|
| ৯০% ("এক নাইন") | ৩৬.৫ দিন | ৭৩ ঘণ্টা | ১৬.৮ ঘণ্টা |
| ৯৯% | ৩.৬৫ দিন | ৭.৩ ঘণ্টা | ১.৬৮ ঘণ্টা |
| ৯৯.৯% ("তিন নাইন") | ৮.৭৭ ঘণ্টা | ৪৩.৮ মিনিট | ১০.১ মিনিট |
| ৯৯.৯৫% | ৪.৩৮ ঘণ্টা | ২১.৯ মিনিট | ৫ মিনিট |
| ৯৯.৯৯% ("চার নাইন") | ৫২.৬ মিনিট | ৪.৪ মিনিট | ১ মিনিট |
| ৯৯.৯৯৯% ("পাঁচ নাইন") | ৫.২৬ মিনিট | ২৬ সেকেন্ড | ৬ সেকেন্ড |

> খেয়াল করুন: ৯৯.৯৯% মানে আপনার হাতে **মাসে ৪ মিনিট**। এটা একটা অসাবধান deploy-এর চেয়েও কম। চার নাইন কোনো configuration setting নয়; এটা একটা engineering কর্মসূচি।

**Data-র আকার:**

| ধরন | আকার |
|------|------|
| char (ASCII) | ১ byte |
| int / float | ৪ byte |
| long / double / timestamp | ৮ byte |
| UUID | ১৬ byte (string হিসেবে ৩৬!) |
| একটা tweet (২৮০ অক্ষর) | ~৩০০ byte + metadata ≈ ১ KB |
| একটা সাধারণ JSON API response | ১–১০ KB |
| একটা ওয়েব পাতা (শুধু HTML) | ~১০০ KB |
| একটা ছবি (ফোন, compressed) | ২–৫ MB |
| ১০ সেকেন্ডের 720p ভিডিও | ~৫–১০ MB |
| এক মিনিটের 1080p ভিডিও | ~৫০–১০০ MB |

**দুইয়ের ঘাত (storage-এর জন্য):**

| ঘাত | আনুমানিক | নাম |
|-------|--------|------|
| 2^10 | ১ হাজার | ১ KB |
| 2^20 | ১০ লাখ | ১ MB |
| 2^30 | ১০০ কোটি | ১ GB |
| 2^40 | ১ লাখ কোটি | ১ TB |
| 2^50 | ১০০ কোটি কোটি | ১ PB |

**সময়:**
- ১ দিন = ৮৬,৪০০ সেকেন্ড ≈ **১,০০,০০০** (এটাই ব্যবহার করুন — মাথার হিসাব তুচ্ছ হয়ে যায়)
- ১ মাস ≈ ২৬ লাখ সেকেন্ড
- ১ বছর ≈ ৩.১৫ কোটি সেকেন্ড ≈ **৩ কোটি**

### Estimation-এর রেসিপি

```
ধাপ ১: DAU (daily active user)
ধাপ ২: প্রতি ব্যবহারকারীর প্রতিদিনের কাজ
ধাপ ৩: মোট কাজ/দিন = DAU × কাজ
ধাপ ৪: গড় RPS = কাজ/দিন ÷ ৮৬,৪০০   (দ্রুততার জন্য ÷১,০০,০০০)
ধাপ ৫: Peak RPS = গড় × peak factor (২× থেকে ১০×; অজানা হলে ৩× ব্যবহার করুন)
ধাপ ৬: Storage/দিন = কাজ/দিন × প্রতি কাজে byte
ধাপ ৭: N বছরে storage = storage/দিন × ৩৬৫ × N × replication factor
ধাপ ৮: Bandwidth = RPS × payload-এর আকার
```

### কাজ করা উদাহরণ ১ — Twitter-এর মতো একটা service

```
দেওয়া আছে
  ৩০ কোটি মাসিক সক্রিয় ব্যবহারকারী
  ৫০% দৈনিক সক্রিয়            → DAU = ১৫ কোটি
  প্রতি ব্যবহারকারী দিনে ২টা tweet করেন
  প্রতি ব্যবহারকারী দিনে ১০০টা tweet পড়েন
  গড় tweet = ৩০০ byte টেক্সট + metadata ≈ ১ KB
  ১০% tweet-এ media আছে, গড়ে ১ MB

WRITE
  ১৫ কোটি × ২ = দিনে ৩০ কোটি tweet
  গড় write RPS = ৩০ কোটি ÷ ১,০০,০০০ ≈ ৩,০০০ write/সেকেন্ড
  Peak (৩×)                            ≈ ৯,০০০ write/সেকেন্ড

READ
  ১৫ কোটি × ১০০ = দিনে ১৫০০ কোটি read
  গড় read RPS = ১৫০০ কোটি ÷ ১,০০,০০০ = ১,৫০,০০০ read/সেকেন্ড
  Peak (৩×)                              ≈ ৪,৫০,০০০ read/সেকেন্ড

  READ:WRITE অনুপাত = ৫০:১   ← এই বিশ্লেষণের সবচেয়ে গুরুত্বপূর্ণ সংখ্যা

STORAGE
  টেক্সট:  ৩০ কোটি × ১ KB    = ৩০০ GB/দিন
  Media:  ৩ কোটি  × ১ MB    = ৩০ TB/দিন     ← media ১০০ গুণ বেশি জায়গা নেয়
  মোট ≈ ৩০.৩ TB/দিন
  বছরে ≈ ১১ PB
  ৩× replication সহ ≈ ৩৩ PB/বছর

BANDWIDTH
  Ingress: ৩০.৩ TB/দিন ÷ ৮৬,৪০০ ≈ ৩৫০ MB/s
  Egress:  ১,৫০,০০০ read/s × ~৫ KB গড় ≈ ৭৫০ MB/s  (media আলাদাভাবে CDN দিয়ে)
```

**সংখ্যাগুলো আপনাকে কী বলে — এই অনুশীলনের মূল কথা এটাই:**

১. **৫০:১ read/write** → design-কে read-optimised হতে হবে। ভারী caching। Read replica। আগে থেকে হিসাব করা timeline (fan-out on write)।
২. **Media টেক্সটের ১০০ গুণ storage** → media যাবে blob storage + CDN-এ, কখনোই আপনার app server দিয়ে নয়। টেক্সট যাবে database-এ।
৩. **৯,০০০ write/সেকেন্ড** → একটা Postgres *প্রায়* এটা পারে, কিন্তু জায়গা রেখে নয়। আপনার partitioning বা একটা write-optimised store লাগবে।
৪. **৪,৫০,০০০ read/সেকেন্ড** → একটা database থেকে অসম্ভব। এটা cache থেকেই পরিবেশন করতে *হবে*। প্রতি Redis node-এ ~১,০০,০০০ ops/সেকেন্ড ধরলে আপনার অন্তত ~১০–২০ node-এর একটা cluster লাগবে।
৫. **৩৩ PB/বছর** → এটা কেউ কেনে না; lifecycle tiering সহ object storage (hot → cold → archive) বাধ্যতামূলক।

> খেয়াল করুন: পাঁচ লাইনের হিসাব পাঁচটা architecture-এর সিদ্ধান্ত দিল। **এই কারণেই আপনি estimate করেন।**

### কাজ করা উদাহরণ ২ — liveness verification SaaS (আপনার domain)

```
দেওয়া আছে
  ২০০টা enterprise tenant
  প্রতি tenant-এ মাসে গড়ে ৫,০০০ verification  → মাসে ১০ লাখ verification
  প্রতিটা verification: একটা ৬ সেকেন্ডের 720p ভিডিও ≈ ৬ MB
  Peak কেন্দ্রীভূত: ৬০% traffic অফিস-সময়ে (৯ ঘণ্টা), কর্মদিবসে
  প্রতিটা verification-এ ~৪ সেকেন্ড GPU সময় লাগে
  আইন: কাঁচা ভিডিও ৯০ দিন পর মুছতে হবে; ফলাফল ৭ বছর রাখতে হবে

THROUGHPUT
  মাসে ১০ লাখ ÷ ৩০ = দিনে ৩৩,০০০
  অফিস-সময়ে কেন্দ্রীভূত: ৩৩,০০০ × ০.৬ = ৯ ঘণ্টায় ২০,০০০
     = ২০,০০০ ÷ ৩২,৪০০s ≈ অফিস-সময়ে গড়ে ০.৬/সেকেন্ড
  Peak-এর peak (৩×) ≈ ২/সেকেন্ড = মিনিটে ১২০

  → request-এর সংখ্যার হিসাবে এটা একটা ছোট সিস্টেম। একে over-engineer করবেন না।

COMPUTE  ← আসল বাধা এটাই, RPS নয়
  ২/সেকেন্ড × ৪ GPU-সেকেন্ড = ৮ concurrent GPU-সেকেন্ড দরকার
  একটা T4 GPU ~১ inference/সেকেন্ড সামলায় → peak-এ ~৮টা GPU worker লাগবে
  প্রতি T4-তে $০.৩৫/ঘণ্টা × ৮ × ২৪ × ৩০ = সবসময় চালু থাকলে মাসে $২,০০০
  → AUTOSCALE করুন। রাতে আপনার ১টা লাগে। এটা ৫ গুণ খরচের পার্থক্য।
  → Queue-ভিত্তিক load levelling অপরিহার্য: কাজ কখনো ফেলে দেবেন না, শুধু দেরি করান।

STORAGE
  ভিডিও (৯০ দিন রাখা):
     দিনে ৩৩,০০০ × ৬ MB × ৯০ দিন = ১৭.৮ TB মোটামুটি গরম storage
     ~$০.০২/GB/মাসে = ~$৩৬০/মাস  → lifecycle নিয়ম দিয়ে দ্রুত ঠান্ডা করুন
  ফলাফল (৭ বছর রাখা):
     দিনে ৩৩,০০০ × ~৫ KB JSON × ৩৬৫ × ৭ = ৪২০ GB  → তুচ্ছ, Postgres-এই রাখুন

BANDWIDTH
  Ingress: ৩৩,০০০ × ৬ MB = দিনে ১৯৮ GB ≈ গড়ে ২.৩ MB/s, peak-এ ~৭ MB/s
  → presigned URL দিয়ে সরাসরি object storage-এ upload করুন।
     ৬ MB আপনার API server দিয়ে পাঠাবেন না। ওই একটা সিদ্ধান্তই
     আপনার bandwidth আর memory-র চাপের ~৯০% সরিয়ে দেয়।
```

**সংখ্যা থেকে architecture-এর সিদ্ধান্ত:**

১. কম RPS → একটা **modular monolith** API পুরোপুরি যথেষ্ট। কোনো microservice লাগবে না।
২. GPU-র খরচ প্রাধান্য পায় → **GPU worker আলাদা করুন**, যাতে সেটা স্বাধীনভাবে scale করে। এটাই একমাত্র আসল service boundary।
৩. **API আর worker-এর মাঝে queue** → peak শুষে নেয়, autoscaling সম্ভব করে, কাজ হারানো ঠেকায়
৪. **Presigned সরাসরি-storage upload** → API server কখনো ভিডিওর byte ছোঁয় না
৫. **দুটো retention policy** → ভিডিও (৯০ দিন, lifecycle নিয়ম) আর ফলাফল (৭ বছর, database)। দুটো আলাদা store।

```
   Mobile/Web
       │ ১. POST /sessions  →  presigned URL ফেরত দেয়
       ▼
   ┌────────┐   ২. সরাসরি PUT video         ┌──────────────┐
   │  API   │◄──────────────────────────► │Object Storage│
   │(২ pod) │   ৩. POST /sessions/{id}/submit           │
   └───┬────┘                              └──────┬──────┘
       │ ৪. job enqueue করে                       │
       ▼                                          │
   ┌────────┐                                     │
   │ Queue  │                                     │
   └───┬────┘                                     │
       │ ৫. dequeue                               │
       ▼                                          │
   ┌──────────────┐  ৬. ভিডিও আনে ────────────────┘
   │ GPU Worker   │
   │ (১–১০ pod,   │  ৭. ফলাফল লেখে
   │  autoscaled) │──────────────┐
   └──────────────┘              ▼
                            ┌──────────┐
                            │ Postgres │
                            └──────────┘
```

### Estimation-এর শর্টকাট

| যা চান | এটা করুন |
|------|---------|
| দৈনিক সংখ্যা থেকে RPS | ১,০০,০০০ দিয়ে ভাগ করুন |
| গড় থেকে peak | ×৩ (অজানা), ×১০ (ভোক্তা/ভাইরাল), ×২ (B2B স্থির) |
| মাসে ১০ লাখ | ≈ গড়ে ০.৪/সেকেন্ড |
| মাসে ১০০ কোটি | ≈ গড়ে ৪০০/সেকেন্ড |
| RPS × KB থেকে GB/দিন | RPS × KB × ৮৬,৪০০ ÷ ১০,০০,০০০ ≈ RPS × KB × ০.০৮৬ |
| ক্লাউডে ১ TB storage-এর মাসিক খরচ | ~$২০ (hot), ~$১০ (cool), ~$১ (archive) |
| একটা ছোট VM-এর মাসিক খরচ | ~$৩০–৭০ |

**সবসময় সাহসের সাথে গোল করুন।** ৮৬,৪০০ → ১,০০,০০০। ৩৬৫ → ৪০০। π → ৩। আপনি গতি চান, নিখুঁততা নয়।

---

## ৪.৩ Capacity planning 🟢

Estimation আপনাকে আকার বলে। Capacity planning বলে **কয়টা মেশিন**, আর **কখন আরও কিনতে হবে**।

### মূল শব্দ

| শব্দ | মানে |
|------|---------|
| **QPS / RPS** | প্রতি সেকেন্ডে query/request |
| **Concurrency** | *একই মুহূর্তে* যত request সামলানো হচ্ছে |
| **Throughput** | একক সময়ে শেষ করা কাজ |
| **Utilisation** | একটা সম্পদের কত % ব্যবহৃত |
| **Headroom** | ঢেউ আর ব্যর্থতার জন্য বাড়তি ক্ষমতা |

### Little's Law — যে একটামাত্র সূত্র আপনাকে জানতেই হবে

> **L = λ × W**
> (Concurrency = আসার হার × সিস্টেমে গড় সময়)

```
আপনি যদি সেকেন্ডে ৫০০টা request পান আর প্রতিটায় ২০০ ms লাগে:
  Concurrency = ৫০০ × ০.২ = যে কোনো মুহূর্তে ১০০টা request চলমান

→ আপনার অন্তত ১০০টা thread/connection/worker লাগবে, সাথে headroom।
→ প্রতিটা worker যদি একটা DB connection ধরে রাখে, তাহলে ~১০০টা DB connection লাগবে।
→ আপনার DB pool যদি ২০ হয়, আপনি এইমাত্র আপনার বাধাটা খুঁজে পেলেন।
```

উল্টোভাবেও চালান:

```
আপনার server-এ ২০০টা worker thread। প্রতিটা request-এ ৪০০ ms লাগে।
  সর্বোচ্চ throughput = ২০০ ÷ ০.৪ = প্রতি server-এ ৫০০ RPS।
  ২,০০০ RPS লাগবে? → অন্তত ৪টা server, headroom সহ ৬টা।
```

**Little's Law queue-বিস্ফোরণও ব্যাখ্যা করে:** আসার হার সেবার হারকে সামান্যও ছাড়িয়ে গেলে W অসীমভাবে বাড়ে। এই কারণেই ১০০% utilisation-এ থাকা সিস্টেম শুধু "একটু ধীরে চলে" না — এটা ভেঙে পড়ে।

### Utilisation-এর ফাঁদ

```
  Latency
    │                                    ╱
    │                                  ╱
    │                              ╱╱
    │                        ╱╱╱╱
    │            ╱╱╱╱╱╱╱╱╱
    │──────────╱
    └──────────────────────────────────── Utilisation
     ০%   ৪০%   ৬০%   ৭০%   ৮০%  ৯০% ১০০%
                              ▲
                     খাদটা এখান থেকে শুরু
```

Queueing theory: গড় অপেক্ষার সময় **১/(১−utilisation)** অনুপাতে বাড়ে।

| Utilisation | আপেক্ষিক queue-এর দেরি |
|-------------|------------------------|
| ৫০% | ২× |
| ৭০% | ৩.৩× |
| ৮০% | ৫× |
| ৯০% | ১০× |
| ৯৫% | ২০× |
| ৯৯% | ১০০× |

> **নিয়ম: latency-সংবেদনশীল service-এ ৫০–৭০% utilisation লক্ষ্য রাখুন।** "টাকা বাঁচাতে" ৯০%-এ চালানোই হলো একটা সামান্য traffic বৃদ্ধিতে outage পাওয়ার উপায়। বাড়তি server গুলো incident-এর চেয়ে সস্তা।

Batch/async কাজ আলাদা — সেখানে আপনি উচ্চ utilisation *চানই*, কারণ latency-তে কিছু আসে যায় না আর queue-টাই buffer।

### Capacity plan-এর কাজ করা উদাহরণ

```
চাহিদা: peak-এ ২,০০০ RPS, p95 latency < ৩০০ ms

মাপা হয়েছে (একটা instance-এ load test থেকে, ৪ vCPU / ৮ GB):
  - একটা request ~২৫ ms CPU ব্যবহার করে
  - একটা request ১২০ ms একটা thread ধরে রাখে (বেশিরভাগটাই DB-র অপেক্ষায়)
  - একটা instance-এর CPU ~১৪০ RPS-এ পূর্ণ হয়

হিসাব
  Throughput-এর জন্য instance: ২,০০০ ÷ ১৪০ = ১৪.৩ → ১৫
  লক্ষ্য ৬০% utilisation:      ১৫ ÷ ০.৬ = ২৫টা instance
  AZ ব্যর্থতার জন্য N+১ (৩টা AZ, একটা হারানো সামলাতে): ২৫ × ১.৫ = ৩৮
  → ৩টা AZ জুড়ে ৩৮টা instance চালান (প্রতি AZ-তে ≈১৩)

  Connection-এ Little's Law যাচাই:
  Concurrency = ২,০০০ × ০.১২ = ২৪০টা চলমান request
  → পুরো fleet জুড়ে DB connection pool-কে ~২৪০ সাপোর্ট করতে হবে
  → ৩৮টা instance × ১০টা connection = ৩৮০। Postgres-এর default max_connections ১০০।
  → আপনার একটা CONNECTION POOLER (PgBouncer) লাগবে। এটাই আসল আবিষ্কার।
```

ওই শেষ লাইনটাই সেই জিনিস, যেটা ধরার জন্য capacity planning-এর অস্তিত্ব — **production-এর আগেই**।

### বৃদ্ধির পরিকল্পনা

```
আজ: ৫০০ RPS। বৃদ্ধি: ৮%/মাস।
  দ্বিগুণ হতে মাস = ৭২ ÷ ৮ = ৯ মাস        (৭২-এর নিয়ম)
  ১২ মাসে: ৫০০ × ১.০৮^১২ ≈ ১,২৬০ RPS
  ২৪ মাসে: ৫০০ × ১.০৮^২৪ ≈ ৩,১৭০ RPS

→ ১২ মাসের জন্য headroom design করুন। ২৪ মাসের পরিকল্পনা জেনে রাখুন।
→ বর্তমান ক্ষমতার ৬০%-এ একটা alert বসান, যাতে ৩ মাস আগে সতর্কতা পান।
```

> **আর্কিটেক্টের বাক্য:** *"আমরা প্রায় ১,২০০ RPS পর্যন্ত ঠিক আছি। মোটামুটি ১১ মাসে সেখানে পৌঁছাব। Sharding একটা ৬ সপ্তাহের প্রজেক্ট, তাই আমাদের ৫ নম্বর মাসে শুরু করা উচিত।"*

---

# পর্ব ২ — মূল design ধারণা

## ৪.৪ Stateless বনাম Stateful service 🟢

**আপনার নেওয়া সবচেয়ে গুরুত্বপূর্ণ scaling সিদ্ধান্ত।**

### Stateful (scaling-এর জন্য খারাপ)

```
User A ──► Server 1  [session: {cart: [...], user: A}]  ← state থাকে এখানে
User B ──► Server 2  [session: {cart: [...], user: B}]

Server 1 মরে গেল → User A-র cart হারাল
Server 3 যোগ করলেন → তার কোনো session নেই, আর load balancer-কে সেটা জানতে হবে
Scale down করলেন  → আপনি চলমান session ধ্বংস করলেন
```

### Stateless (ভালো)

```
User A ──► যে কোনো server ──► Redis / DB / token থেকে state পড়ে
User B ──► যে কোনো server ──► একই

Server মরে গেল    → ব্যবহারকারীরা টেরই পান না; request অন্যদিকে যায়
Server যোগ করলেন   → সাথে সাথে কাজ করে
Deploy করলেন       → rolling restart, কোনো বিঘ্ন নেই
```

**Stateless মানে "কোনো state নেই" নয়।** মানে **server দুটো request-এর মাঝে কোনো state ধরে রাখে না**। State চলে যায়:

| কোথায় | কীসের জন্য ভালো | সাবধানতা |
|-------|----------|-----------|
| **Client-এ** (JWT, cookie) | ব্যবহারকারীর পরিচয়, ছোট claim | সহজে বাতিল করা যায় না; আকারের সীমা; এতে কখনো গোপন তথ্য রাখবেন না |
| **একটা shared cache** (Redis) | Session, cart, rate-limit counter | HA লাগবে; এটা এখন একটা dependency |
| **Database** | টেকসই যা কিছু | ধীর |
| **Object storage** | ফাইল, বড় blob | গরম data-র জন্য নয় |

### Sticky session — লোভনীয় ফাঁদ

Load balancer একজন ব্যবহারকারীকে একটা server-এ আটকে রাখতে পারে (cookie বা IP hash দিয়ে)।

**কেন লোভনীয়:** আপনি in-memory session রাখেন আর সবকিছু "কাজ করে"।
**কেন ব্যথা দেয়:**
- অসম load — একটা server ভারী ব্যবহারকারীদের পায়
- Deploy সবাইকে বের করে দেয়
- Autoscaling বিদ্যমান ব্যবহারকারীদের পুনর্বণ্টন করে না
- একটা মৃত server = হারানো session
- আপনার সিস্টেম এখন মৌলিকভাবে স্থিতিস্থাপকভাবে scale করতে অক্ষম

> **Sticky session শুধু তখনই ব্যবহার করুন যখন সত্যিই এড়ানো যায় না** (দীর্ঘস্থায়ী WebSocket, কিছু legacy app)। নইলে state বাইরে সরান। সবসময়।

### যখন state এড়ানো যায় না

Database, cache, message broker আর stream processor স্বভাবতই stateful। এগুলো সামলান:
- **Replication** (একাধিক কপি) দিয়ে
- Leader election-এর জন্য **consensus** (Raft — অধ্যায় ০৫) দিয়ে
- Kubernetes-এ **persistent volume** আর **StatefulSet** (অধ্যায় ১৫) দিয়ে
- অথবা সবচেয়ে ভালো, **একটা managed service ব্যবহার করুন** আর অন্য কাউকে চালাতে দিন

---

## ৪.৫ Vertical বনাম Horizontal scaling 🟢

### Vertical (scale up) — একটা বড় মেশিন

```
  [২ vCPU, ৪ GB]  →  [৩২ vCPU, ১২৮ GB]  →  [১২৮ vCPU, ২ TB]
```

| ✅ সুবিধা | ❌ অসুবিধা |
|---------|---------|
| কোনো কোড পরিবর্তন নেই | একটা কঠিন সিলিং আছে |
| কোনো distributed জটিলতা নেই | খরচ **অতি-রৈখিকভাবে** বাড়ে (২× মেশিন ≈ ৩× দাম) |
| ACID transaction সহজ থাকে | **Single point of failure** |
| প্রায়ই দ্রুততম সমাধান | আকার বদলাতে সাধারণত downtime লাগে |

### Horizontal (scale out) — আরও মেশিন

```
  [Server] → [Server][Server][Server][Server] একটা load balancer-এর পেছনে
```

| ✅ সুবিধা | ❌ অসুবিধা |
|---------|---------|
| কার্যত সীমাহীন | Stateless design লাগে |
| সাধারণ hardware = প্রতি এককে সস্তা | Distributed system-এর সমস্যা (অধ্যায় ০৫) |
| গঠনগতভাবেই fault tolerant | Data consistency কঠিন হয়ে যায় |
| চাহিদা অনুযায়ী scale up **আর** down | বেশি operational জটিলতা |

### যে সৎ পরামর্শটা বেশিরভাগ মানুষ ভুল বোঝে

> **আগে vertically scale করুন। আপনি যতটা ভাবছেন তার চেয়ে অনেক বেশি দূর পর্যন্ত।**

একটা আধুনিক একক server-এ ১২৮টা core আর ২ TB RAM থাকতে পারে। ওই মেশিন সেকেন্ডে হাজার হাজার request পরিবেশন করতে পারে আর একটা ৫০০ GB database পুরোটাই memory-তে রাখতে পারে। StackOverflow বিখ্যাতভাবে ৯টা web server আর ২টা SQL server থেকে পুরো পৃথিবীকে সেবা দিয়েছে।

**পেশাদার ক্রম:**

```
১. OPTIMISE      → N+1 query ঠিক করুন, index যোগ করুন, গরম read cache করুন।
                   সাধারণত ১০–১০০× দেয়। কোনো খরচ নেই। এটা প্রথমে করুন।
২. SCALE UP      → বড় বাক্স। সহজ, দ্রুত, ১২+ মাস কিনে দেয়।
৩. SCALE OUT (stateless tier) → সহজ, availability-র জন্য এমনিতেই আগেভাগে করুন।
৪. SCALE OUT (read)  → read replica, caching।
৫. SCALE OUT (write) → partitioning/sharding। সবার শেষে। এটাই কঠিনটা।
```

**বাস্তব গল্প:** সেকেন্ডে ৪০০ write করা একটা database-এর জন্য একটা টিম ৪ মাস খরচ করে একটা sharded architecture বানিয়েছিল। একজন consultant একদিনে তিনটা index যোগ করে একে একটা বড় instance-এ সরিয়ে দিলেন। সিস্টেমটা আরও তিন বছর sharding ছাড়াই চলল। ৫ নম্বর ধাপের আগে সবসময় ১ নম্বর ধাপ দেখুন।

### Autoscaling

একটা metric-এর ভিত্তিতে স্বয়ংক্রিয়ভাবে scale out করা।

| Trigger-এর ধরন | উদাহরণ | নোট |
|--------------|---------|-------|
| **Reactive** | CPU > ৭০% ৩ মিনিট ধরে → instance যোগ | সহজ, কিন্তু সবসময় পিছিয়ে থাকে। নতুন instance প্রস্তুত হতে ১–৫ মিনিট লাগে। |
| **Scheduled** | ০৮:০০-তে ২০-এ, ২০:০০-তে ৪-এ | অনুমানযোগ্য অফিস-সময়ের load-এর জন্য চমৎকার |
| **Predictive** | load-এর ML পূর্বাভাস | ক্লাউড প্রোভাইডাররা দেয়; বড় scale-এ কাজের |
| **Queue-ভিত্তিক** | queue-র গভীরতা > ১০০০ → worker যোগ | **Async কাজের জন্য সেরা সংকেত** — এটা আসল backlog মাপে |

**Autoscaling-এর ফাঁদ:**
- **দ্রুত scale up করুন, ধীরে scale down** (cooldown) — ওঠানামা বেশি বরাদ্দের চেয়ে খারাপ
- **Startup-এর সময় গুরুত্বপূর্ণ** — একটা pod গরম হতে ৪ মিনিট নিলে reactive scaling একটা ২ মিনিটের ঢেউয়ে কোনো কাজেই আসে না। গরম ক্ষমতা রাখুন।
- **App scale করা কিন্তু database না করা** শুধু বাধাটা সরায়, আর connection দিয়ে database-কে *মেরে* ফেলতে পারে
- **একটা সর্বোচ্চ সীমা বসান।** একটা নিয়ন্ত্রণহীন autoscaler আর একটা retry-ঝড় মিলে এক রাতে $৫০,০০০ খরচ করার একটা সত্যিকারের উপায়।

---

## ৪.৬ Load balancing 🟢

একটা load balancer আসা request গুলো একাধিক server-এ বিলি করে।

```
                    ┌──────────────┐
   Client ─────────►│Load Balancer │
                    └───┬───┬───┬──┘
                   ┌────┘   │   └────┐
              ┌────▼──┐ ┌───▼───┐ ┌──▼────┐
              │Server1│ │Server2│ │Server3│
              └───────┘ └───────┘ └───────┘
```

### Layer 4 বনাম Layer 7

| | **L4 (transport)** | **L7 (application)** |
|---|---|---|
| দেখে | IP + port | পুরো HTTP: URL, header, cookie, body |
| গতি | খুব দ্রুত, কম CPU | ধীর, বেশি CPU |
| যা দিয়ে route করতে পারে | শুধু connection | Path, host, header, cookie, method |
| TLS | পার হয়ে যায় (বা TCP passthrough) | **TLS terminate করে** |
| উদাহরণ | AWS NLB, HAProxy (TCP mode), IPVS | AWS ALB, Nginx, Envoy, Traefik, Azure App Gateway |
| কীসের জন্য | কাঁচা TCP, database, গেমিং, চরম throughput | Web API, স্মার্ট routing লাগে এমন যা কিছু |

> বেশিরভাগ web সিস্টেমের **L7** চাই। আপনি একই জায়গায় path-ভিত্তিক routing (`/api/*` → API pod, `/static/*` → CDN origin), header-ভিত্তিক canary routing, request retry আর TLS termination পান।

### Algorithm

| Algorithm | কীভাবে | কীসের জন্য সেরা |
|-----------|-----|----------|
| **Round Robin** | পালা অনুযায়ী পরের server | একরকম server, একরকম request |
| **Weighted Round Robin** | বড় server বেশি পায় | মিশ্র আকারের instance |
| **Least Connections** | সবচেয়ে কম সক্রিয় connection | **পরিবর্তনশীল সময়ের request — সাধারণত সেরা default** |
| **Least Response Time** | দ্রুততম উত্তরদাতা | Latency-সংবেদনশীল |
| **IP Hash** | client IP hash → server | Cookie ছাড়া মোটামুটি sticky (NAT/mobile-এ ভাঙে) |
| **Consistent Hashing** | Key hash → ring | **Cache আর sharded state** — একটা node যোগ করলে শুধু ১/N key নড়ে |
| **Random Two Choices** | এলোমেলোভাবে ২টা বাছুন, কম load-এরটা নিন | আশ্চর্যরকম চমৎকার; বড় scale-এ ব্যবহৃত (least-connections-এর "পাল"-এর সমস্যা এড়ায়) |

### Health check — যে অংশটা মানুষ ভুল করে

```
LIVENESS   "Process কি জীবিত?"           → না হলে: restart করুন
READINESS  "এটা কি এখন traffic নিতে পারে?" → না হলে: pool থেকে সরান (কিন্তু মারবেন না)
STARTUP    "এটা কি boot শেষ করেছে?"        → ধীর শুরু হওয়াদের মরা থেকে রক্ষা করে
```

```python
# Readiness-কে DEPENDENCY যাচাই করতে হবে। Liveness-কে নয়।
@app.get("/health/live")
async def live():
    return {"status": "ok"}          # process চলছে। এটুকুই।

@app.get("/health/ready")
async def ready(db=Depends(get_db), cache=Depends(get_cache)):
    checks = {
        "database": await db.ping(),
        "cache":    await cache.ping(),
    }
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks},
                        status_code=200 if ok else 503)
```

> **ক্লাসিক production বিপর্যয়:** *liveness* probe-কে database যাচাই করানো। Database-এ ৩০ সেকেন্ডের একটা ঝাঁকুনি হলো → প্রতিটা pod liveness-এ fail করল → Kubernetes **সবগুলো একসাথে** restart করল → পুনঃসংযোগের হুড়োহুড়ি database-কে বন্ধ রাখল → cluster আর কখনোই ফিরল না। **Liveness process যাচাই করে। Readiness dependency যাচাই করে।** এটা কামড়ানোর আগেই শিখে নিন।

### Load balancer-এর অন্য দায়িত্ব

- **TLS termination** (আর দরকার হলে backend-এ পুনরায় encrypt)
- **Connection draining / graceful shutdown** — নতুন request পাঠানো বন্ধ করুন, চলমানগুলো শেষ হতে দিন (সাধারণত ৩০ সেকেন্ড)
- **Rate limiting** আর **WAF** integration
- শুধু idempotent request-এ **Retry** (অধ্যায় ০৫ — একটা non-idempotent POST retry করাই হলো দুইবার চার্জ করার উপায়)
- **Outlier detection** — যে backend ৫xx দিতে শুরু করে তাকে স্বয়ংক্রিয়ভাবে বের করে দেওয়া

### DNS load balancing আর Global Server Load Balancing

- **DNS round-robin** — একাধিক A record ফেরত দিন। সস্তা, কিন্তু DNS caching আর TTL-এর কারণে failover ধীর আর অনির্ভরযোগ্য। এটা আসল health-সচেতন LB নয়।
- **GSLB / Anycast** (Route 53, Azure Front Door, Cloudflare) — ব্যবহারকারীদের নিকটতম *সুস্থ* region-এ পাঠায়। Multi-region failover আসলে এভাবেই কাজ করে।

---

## ৪.৭ Caching (ভূমিকা — পূর্ণ অধ্যায় পরে) 🟢

**ধারণা:** ব্যয়বহুলভাবে তৈরি হওয়া data-র একটা কপি দ্রুত কোথাও রাখুন।

> **Caching হলো অস্তিত্বশীল সবচেয়ে লাভজনক performance কৌশল।** এটা আবার শিল্পের সবচেয়ে বিখ্যাত রসিকতারও উৎস: *"কম্পিউটার বিজ্ঞানে মাত্র দুটো কঠিন জিনিস আছে: cache invalidation আর নামকরণ।"*

### Cache-এর স্তরবিন্যাস — প্রতিটা স্তরে cache করুন

```
১. BROWSER CACHE        Cache-Control header           ০ ms, বিনামূল্যে
২. CDN                  static asset, কিছু API GET      ~২০ ms, সস্তা
৩. API GATEWAY CACHE    পুরো response                   ~৫ ms
৪. APPLICATION MEMORY   process-এর ভেতরের dictionary/LRU ~০.১ µs
৫. DISTRIBUTED CACHE    Redis/Memcached                  ~০.৫ ms
৬. DATABASE CACHE       buffer pool, query cache         ~১ ms
৭. DISK
```

আপনি যত *আগের* স্তরে থামবেন, তার নিচের সবকিছু তত বাঁচবে।

### Cache hit ratio — যে metric-টা গুরুত্বপূর্ণ

```
Hit ratio = hit ÷ (hit + miss)

২০ ms-এর DB query সহ ১০০০ RPS-এ:
  ০%  hit ratio → সেকেন্ডে ১০০০টা DB query
  ৮০% hit ratio → সেকেন্ডে ২০০টা DB query   (৫× কম)
  ৯৫% hit ratio → সেকেন্ডে ৫০টা DB query    (২০× কম)
  ৯৯% hit ratio → সেকেন্ডে ১০টা DB query    (১০০× কম)
```

৯৫% থেকে ৯৯%-এ গেলে **বাকি load-এর ৮০% সরে যায়**। এই কারণেই hit ratio একটা প্রথম শ্রেণির metric আর এটা আপনার dashboard-এ থাকা উচিত।

### Cache যোগ করার আগে তিনটা প্রশ্ন

১. **এই data কি যত বদলায় তার চেয়ে অনেক বেশি পড়া হয়?** (প্রতিবার পড়ার সময়ই বদলালে caching খরচ বাড়ায়, কিছু দেয় না।)
২. **এটা কতটা পুরনো হতে পারে?** (১ সেকেন্ড? ১ ঘণ্টা? কখনোই না? উত্তরটাই আপনার TTL আর কৌশল ঠিক করে।)
৩. **Cache খালি বা বন্ধ থাকলে কী হয়?** (উত্তর যদি হয় "database মরে যায়", তাহলে আপনি এমন একটা সিস্টেম বানিয়েছেন যেটা restart-ই করতে পারে না। দেখুন *cache stampede*, অধ্যায় ১১।)

পূর্ণ আলোচনা — pattern, invalidation, stampede, penetration, avalanche — **অধ্যায় ১১**-এ।

---

## ৪.৮ Replication 🟢

**সংজ্ঞা:** একই data-র কপি একাধিক মেশিনে রাখা।

**কেন:** availability (একটা node হারালেও টিকে থাকা), read scalability (read ছড়িয়ে দেওয়া), আর locality (কাছের region থেকে ব্যবহারকারীদের সেবা)।

### Leader–Follower (primary–replica) — সবচেয়ে সাধারণ মডেল

```
          write
             │
             ▼
        ┌─────────┐
        │ LEADER  │────replication log────┐
        └─────────┘                       │
             │                            │
     ┌───────┴────────┐           ┌───────▼────────┐
     ▼                ▼           ▼                ▼
┌─────────┐    ┌─────────┐  ┌─────────┐    ┌─────────┐
│FOLLOWER │    │FOLLOWER │  │FOLLOWER │    │FOLLOWER │
└─────────┘    └─────────┘  └─────────┘    └─────────┘
     ▲                ▲           ▲                ▲
     └────────── read ────────────┴────────────────┘
```

- **সব write যায় leader-এ।** Follower গুলো read-only।
- Leader তার পরিবর্তনের log পাঠায়; follower গুলো সেটা প্রয়োগ করে।
- Leader মরে গেলে একটা follower **পদোন্নতি** পায় (স্বয়ংক্রিয়ভাবে বা হাতে)।

### Synchronous বনাম asynchronous replication — মূল trade-off

| | **Synchronous** | **Asynchronous** |
|---|---|---|
| Leader কি follower-এর জন্য অপেক্ষা করে? | হ্যাঁ, ack-এর আগে | না, সাথে সাথে ack করে |
| Write latency | বেশি (network round trip) | কম |
| Leader ব্যর্থ হলে data হারানো | **কিছুই না** | **সম্ভব** — replicate না হওয়া write হারায় |
| একটা follower ধীর/বন্ধ হলে | **Write আটকে যায়** | কোনো প্রভাব নেই |

**ব্যবহারিক আপস: semi-synchronous।** একটা follower synchronous, বাকিগুলো async। আপনি প্রতিটা replica-র কাছে জিম্মি না হয়েও durability পান (অন্তত আরেকটা কপিতে জিনিসটা আছে)।

```sql
-- PostgreSQL: একটা নামযুক্ত standby-র নিশ্চিতকরণের জন্য অপেক্ষা
synchronous_standby_names = 'ANY 1 (replica_a, replica_b)'
synchronous_commit = on
```

### Replication lag — আর এটা যে bug ঘটায়

Asynchronous replica সবসময়ই *একটু* পেছনে — স্বাভাবিকভাবে মাইক্রোসেকেন্ড, কিন্তু load-এ বা একটা বড় write-এর সময় মিনিট।

**ক্লাসিক bug:**

```python
# ব্যবহারকারী তাঁর profile update করেন
await db.write("UPDATE users SET name = 'Delower' WHERE id = 42")
# Profile পাতায় redirect → read যায় একটা REPLICA-তে
user = await db.read_replica("SELECT name FROM users WHERE id = 42")
# → পুরনো নাম ফেরত দেয়। ব্যবহারকারী: "আমার পরিবর্তন save হয়নি!" আর আবার save চাপেন।
```

**সমাধান (চারটাই জানুন):**

| কৌশল | কীভাবে | খরচ |
|-----------|-----|------|
| **Read-your-writes** | লেখার পর N সেকেন্ডের জন্য ওই ব্যবহারকারীর read leader-এ পাঠান | Leader-এ বাড়তি load |
| **Monotonic reads** | একজন ব্যবহারকারীকে একটা replica-তে আটকে দিন (consistent hashing) | অসম load |
| **Token/LSN-ভিত্তিক** | Client write-এর অবস্থান পাঠায়; replica ধরে ফেলা পর্যন্ত অপেক্ষা করে | জটিলতা, বাড়তি latency |
| **শুধু মানটা ফেরত দিন** | Write-এর response-এ নতুন state থাকে; আবার পড়বেন না | বিনামূল্যে — **যখনই সম্ভব এটাই করুন** |

### Multi-leader replication

দুই বা ততোধিক node write নেয়। Multi-region write locality আর offline-সক্ষম client-এর জন্য ব্যবহৃত।

**কঠিন সমস্যা: write-এর সংঘর্ষ।** দুটো region একই সাথে একই row সম্পাদনা করে।

সমাধানের কৌশল:
- **Last Write Wins (LWW)** — সহজ, আর **নীরবে data হারায়**। এটা clock-এর উপরও নির্ভর করে, যারা মিথ্যা বলে (অধ্যায় ০৫)।
- **Application-স্তরের merge** — আপনি সংঘর্ষের logic লেখেন
- **CRDT** — এমন data type যেগুলো গাণিতিকভাবে সংঘর্ষ ছাড়াই মিশে যায় (counter, set, সহযোগিতামূলক টেক্সট)। Google Docs আর Figma এভাবেই কাজ করে।

### Leaderless replication (Dynamo ধাঁচের)

যে কোনো node write নেয়; client কয়েকটায় লেখে আর কয়েকটা থেকে পড়ে।

**Quorum:** N replica, W write ack, R read response — যদি **W + R > N** হয়, তাহলে একটা read সর্বশেষ write দেখবেই।

```
N = ৩, W = ২, R = ২  →  ২ + ২ > ৩ ✓  strongly consistent, ১টা node বন্ধ সহ্য করে
N = ৩, W = ১, R = ১  →  ১ + ১ < ৩ ✗  দ্রুত, কিন্তু পুরনো data পড়তে পারে
N = ৩, W = ৩, R = ১  →  দ্রুত read, কিন্তু যে কোনো node বন্ধ হলে সব write আটকে যায়
```

Cassandra, DynamoDB, Riak ব্যবহার করে। প্রতি query-তে সমন্বয়যোগ্য — যেটা সত্যিই কাজের: balance যাচাইয়ের জন্য strong consistency, "like"-এর সংখ্যার জন্য eventual।

---

## ৪.৯ Partitioning আর Sharding 🟢

**Replication** = একই data অনেক জায়গায় (availability আর read-এর জন্য)।
**Partitioning** = *আলাদা* data আলাদা জায়গায় (আকার আর write-এর জন্য)।

এগুলো প্রায় সবসময় **একসাথে** ব্যবহৃত হয়: প্রতিটা partition replicate করা থাকে।

```
   PARTITIONING (sharding) — data ভাগ করা
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │  Shard 1   │  │  Shard 2   │  │  Shard 3   │
   │ user A–H   │  │ user I–P   │  │ user Q–Z   │
   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
         │               │               │
   REPLICATION — প্রতিটা shard-এর কপি আছে
   ┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
   │  replica   │  │  replica   │  │  replica   │
   └────────────┘  └────────────┘  └────────────┘
```

### কেন partition করবেন?

১. **Data একটা মেশিনে আঁটে না**
২. **Write throughput** একটা মেশিনকে ছাড়িয়ে যায় (replication write-এ সাহায্য করে না — প্রতিটা replica তবু প্রতিটা write প্রয়োগ করে)
৩. **বিচ্ছিন্নতা** — compliance-এর জন্য প্রতি tenant বা প্রতি region আলাদা করা

### Vertical বনাম horizontal partitioning

**Vertical** — *কলাম* অনুযায়ী ভাগ। কম ব্যবহৃত বা বড় কলামগুলো অন্য table/store-এ সরান।

```
users                     user_profiles
├── id                    ├── user_id
├── email                 ├── bio (TEXT)
├── password_hash         ├── avatar_url
└── created_at            └── preferences (JSONB)
   (গরম, ছোট, cached)        (ঠান্ডা, বড়)
```

**Horizontal (sharding)** — *row* অনুযায়ী ভাগ। মানুষ "sharding" বলতে এটাই বোঝায়।

### Sharding-এর কৌশল

**১. Range-ভিত্তিক**

```
Shard 1: user_id ১–১০,০০,০০০
Shard 2: user_id ১০,০০,০০১–২০,০০,০০০
```
- ✅ Range query দক্ষ; ভাবতে সহজ
- ❌ **Hotspot** — ক্রমিক ID মানে সব নতুন write শেষ shard-এ যায়। তারিখ-ভিত্তিক range মানে আজকের shard সব traffic নেয়।

**২. Hash-ভিত্তিক**

```
shard = hash(user_id) % num_shards
```
- ✅ সমান বণ্টন
- ❌ Range query-কে প্রতিটা shard-এ যেতে হয়
- ❌ **আবার shard করা যন্ত্রণাদায়ক** — `num_shards` বদলালে প্রায় প্রতিটা key নতুন জায়গায় যায়

**৩. Consistent hashing** ⭐

Key আর node দুটোই একটা ring-এ বসান; একটা key ঘড়ির কাঁটার দিকে পরের node-এর।

```
          ০/৩৬০°
            │
    node C ─┼─ node A
            │
    ────────┼────────
            │
        node B
```
- ✅ একটা node যোগ/বাদ দিলে শুধু **১/N** key নড়ে, সব নয়
- ✅ **Virtual node** (প্রতিটা শারীরিক node ring-এর অনেক জায়গায় বসানো) অসম বণ্টন ঠিক করে
- যারা ব্যবহার করে: Cassandra, DynamoDB, Riak, Memcached client, বেশিরভাগ CDN

**৪. Directory-ভিত্তিক (lookup table)**

```
lookup_table: { tenant_42 → shard_3, tenant_43 → shard_1, ... }
```
- ✅ সম্পূর্ণ নমনীয়তা; আপনি একটা বড় tenant-কে তার নিজের shard-এ সরাতে পারেন
- ✅ পুনর্বণ্টন মানে শুধু একটা metadata update (আর একটা data সরানো)
- ❌ Lookup service একটা নতুন dependency আর সম্ভাব্য SPOF — একে জোরালোভাবে cache করুন
- **Multi-tenant SaaS-এর জন্য এটাই প্রচলিত পছন্দ**, আর প্রতি-tenant product-এর জন্য সঠিক

### Shard key বেছে নেওয়া — যে সিদ্ধান্ত সহজে ফেরানো যায় না

**একটা ভালো shard key:**
১. **উচ্চ cardinality** — অনেক আলাদা মান
২. **সমান বণ্টন** — কোনো মান প্রাধান্য পায় না
৩. **আপনার query-র ধরনের সাথে মেলে** — বেশিরভাগ query **একটা** shard-এ যাওয়া উচিত
৪. **বদলায় না** — shard key বদলানো মানে row সরানো

**উদাহরণ:**

| সিস্টেম | ভালো key | খারাপ key | কেন |
|--------|----------|---------|-----|
| Multi-tenant SaaS | `tenant_id` | `created_at` | Query প্রায় সবসময়ই একটা tenant-এ সীমাবদ্ধ |
| সামাজিক নেটওয়ার্ক | `user_id` | `post_id` | "আমার feed/post আনো" একটা shard-এ যায় |
| Chat | `conversation_id` | `message_id` | একটা chat-এর সব message একসাথে থাকে |
| IoT | `device_id` | `timestamp` | Timestamp = সব write একটা shard-এ যায় |
| E-commerce order | `customer_id` | `order_status` | কম cardinality; 'completed'-এ বিশাল hotspot |

### Sharding যে কঠিন সমস্যাগুলো তৈরি করে (প্রতিশ্রুতিবদ্ধ হওয়ার আগে জানুন)

| সমস্যা | ব্যাখ্যা | উপশম |
|---------|-------------|------------|
| **Cross-shard join** | SQL মেশিনের মধ্যে join করতে পারে না | Denormalise করুন; বা প্রতিটা shard-এ query করে app-এ join করুন; বা একটা আলাদা analytics store রাখুন |
| **Cross-shard transaction** | Shard-এর মধ্যে ACID নেই | Saga (অধ্যায় ০৫); বা এমনভাবে design করুন যাতে transaction একটা shard-এই থাকে |
| **বৈশ্বিক অনন্যতা** | `AUTO_INCREMENT` সংঘর্ষ করে | UUID/ULID/Snowflake ID (নিচে দেখুন) |
| **পুনর্বণ্টন** | Traffic পরিবেশন করতে করতে data সরানো | Consistent hashing + virtual node; বা directory-ভিত্তিক |
| **গরম shard** | একটা tenant আপনার ৪০% traffic | তাদের আলাদা করুন; বা একটা যৌগিক key দিয়ে sub-shard করুন |
| **Fan-out query** | "সব user খোঁজো" প্রতিটা shard-এ যায়; latency = সবচেয়ে ধীর shard | একটা আলাদা search index রাখুন (Elasticsearch) |
| **Operational খরচ** | ২০টা shard × ৩টা replica = ৬০টা DB backup, patch আর monitor করতে হবে | Automation, বা একটা managed distributed DB |

### Distributed ID তৈরি

| পদ্ধতি | সুবিধা | অসুবিধা |
|--------|------|------|
| **UUIDv4** | তুচ্ছ, কোনো সমন্বয় লাগে না | এলোমেলো → ভয়াবহ B-tree index locality (page split, bloat) |
| **UUIDv7 / ULID** | সময়-অনুযায়ী সাজানো যায় **আর** অনন্য — **আজকের সেরা default** | তৈরির সময় সামান্য ফাঁস হয় |
| **Snowflake** (timestamp + machine + sequence) | ৬৪-bit, সাজানো যায়, উচ্চ throughput | machine-ID সমন্বয় লাগে; clock-skew সংবেদনশীল |
| **DB sequence block** | ছোট, ক্রমিক | একটা কেন্দ্রীয় allocator লাগে |

> একটা জিনিস নিলে এটাই নিন: **primary key-র জন্য UUIDv4-এর বদলে UUIDv7/ULID ব্যবহার করুন।** একই অনন্যতা, অনেক ভালো index আচরণ।

### কখন shard করবেন

> **যত দেরিতে সম্ভব।** Sharding হলো সবচেয়ে ব্যয়বহুল scaling ধাপ আর ফেরানো সবচেয়ে কঠিন।

আগে এগুলো নিঃশেষ করুন:
১. Index আর query optimisation
২. Caching
৩. Read replica
৪. Vertical scaling (একটা ১২৮-core / ২ TB মেশিন অনেক বড় একটা database)
৫. Vertical partitioning / পুরনো data archive করা
৬. Non-relational কাজ বাইরে সরানো (search → Elasticsearch, time-series → Timescale/Influx)
৭. **তারপর** shard করুন

**ব্যতিক্রম:** আপনি যদি একটা multi-tenant SaaS বানান, তাহলে **প্রথম দিন থেকেই schema-তে shard key (`tenant_id`) রাখুন**, যদিও সব tenant একটা database-এ থাকে। পরে প্রতিটা table-এ একটা tenant কলাম যোগ করা একটা migration দুঃস্বপ্ন। *Key*-টা প্রথম দিনের সিদ্ধান্ত; *ভাগ করা*টা পরের সিদ্ধান্ত।

---

## ৪.১০ সব একসাথে: একটা design হেঁটে দেখা

**সমস্যা:** একটা URL shortener design করুন (ক্লাসিকটা)। মাসে ১০ কোটি নতুন URL, মাসে ১০০০ কোটি redirect।

**১. Requirement**
- FR: একটা URL ছোট করা, একটা short code redirect করা, মৌলিক analytics
- NFR: redirect p99 < ১০০ ms; ৯৯.৯৯% availability (একটা মৃত লিংক একটা ভাঙা প্রতিশ্রুতি); URL কখনো মেয়াদ শেষ হয় না; code গুচ্ছ আকারে অনুমানযোগ্য হওয়া যাবে না

**২. Estimate**
```
Write: মাসে ১০ কোটি ÷ ২৬ লাখ সেকেন্ড ≈ ৪০/সেকেন্ড        (peak ১২০/সেকেন্ড)
Read:  মাসে ১০০০ কোটি ÷ ২৬ লাখ সেকেন্ড ≈ ৪,০০০/সেকেন্ড     (peak ১২,০০০/সেকেন্ড)
READ:WRITE = ১০০:১            ← read-optimised design

Storage: মাসে ১০ কোটি × ~৫০০ byte = ৫০ GB/মাস = ৬০০ GB/বছর
  → ৫ বছরে ≈ ৩ TB। একটা মেশিনে স্বচ্ছন্দে আঁটে। কোনো SHARDING লাগবে না (এখনো)।

Code-এর দৈর্ঘ্য: ৬২টা অক্ষর (a-zA-Z0-9)
  62^6 = ৫৬০০ কোটি  → ৬ অক্ষর কয়েক দশকের জন্য যথেষ্ট
```

**৩. API**
```
POST /api/v1/urls          {"longUrl": "...", "customAlias": "..."}  → 201 {"shortUrl": "..."}
GET  /{code}                                                         → 301/302 redirect
GET  /api/v1/urls/{code}/stats                                       → 200 {clicks, ...}
```

**৪. Data model**
```sql
CREATE TABLE urls (
    code        VARCHAR(10) PRIMARY KEY,     -- short code
    long_url    TEXT NOT NULL,
    owner_id    UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);
CREATE INDEX idx_urls_owner ON urls (owner_id, created_at DESC);
```

**৫. Code তৈরি — তিনটা বিকল্প, trade-off সহ**

| বিকল্প | কীভাবে | Trade-off |
|--------|-----|-----------|
| **Hash + ছাঁটাই** | `base62(md5(url))[:7]` | সংঘর্ষ শনাক্ত আর retry করতে হবে; একই URL → একই code (কখনো কাম্য, কখনো একটা privacy ফাঁস) |
| **Counter + base62** | একটা বৈশ্বিক counter, সেটা encode করুন | কখনো সংঘর্ষ নেই; কিন্তু code গুলো **ক্রমিক আর গোনা যায়** — যে কেউ আপনার সব লিংক crawl করতে পারে |
| **আগে থেকে তৈরি key pool** ⭐ | একটা service এলোমেলো অব্যবহৃত code একটা table-এ বানায়; app একটা নেয় | কোনো সংঘর্ষ নেই, গোনা যায় না, O(1) — **সেরা পছন্দ** |

**৬. High-level design**
```
                    ┌─────┐
   Redirect ───────►│ CDN │ (edge-এ ৩০১ cache করুন — বিশাল লাভ)
                    └──┬──┘
                       │ miss
                  ┌────▼─────┐
                  │    LB    │
                  └────┬─────┘
              ┌────────┴────────┐
         ┌────▼────┐       ┌────▼────┐
         │ App × N │  ...  │ App × N │  (stateless)
         └────┬────┘       └────┬────┘
              └────────┬────────┘
                  ┌────▼────┐   ৯৯% read এখানেই থামে
                  │  Redis  │
                  └────┬────┘
                       │ miss
                  ┌────▼──────┐        ┌──────────────┐
                  │ Postgres  │───────►│ Read replica │
                  │  (leader) │        └──────────────┘
                  └───────────┘
                       │ async
                  ┌────▼────┐      ┌──────────────┐
                  │  Queue  │─────►│  Analytics   │
                  └─────────┘      │  (ClickHouse)│
                                   └──────────────┘
```

**৭. মূল সিদ্ধান্ত আর কারণ**
- **সবকিছু cache করুন।** URL একবার তৈরি হলে immutable → অসীম TTL সহ একটা নিখুঁত cache প্রার্থী। ৯৮%+ hit ratio আশা করুন।
- **301 বনাম 302:** ৩০১ (স্থায়ী) browser আর CDN-কে cache করতে দেয় — load-এর জন্য দারুণ, কিন্তু তখন আপনি click analytics হারান আর target কখনো বদলাতে পারেন না। **৩০২ নিয়ন্ত্রণ আর analytics রাখে।** Analytics-ই product কিনা তার উপর ভিত্তি করে বাছুন। বেশিরভাগ shortener ৩০২ ব্যবহার করে।
- **Analytics একটা queue দিয়ে যায়** — click গোনা যেন কখনোই একটা redirect ধীর বা ভাঙা না করে
- এই scale-এ **কোনো sharding লাগবে না**; কখন লাগবে তার trigger উল্লেখ করুন (~১০ TB বা write RPS > ৫,০০০)

**৮. Failure mode**
- Redis বন্ধ → Postgres-এ নেমে যায়। দ্বিতীয় প্রতিরক্ষা হিসেবে একটা ছোট in-process LRU রাখুন, যাতে একটা ঠান্ডা Redis DB-তে হুড়োহুড়ি না বাধায়।
- Postgres leader বন্ধ → একটা replica-কে পদোন্নতি দিন; write ~৩০ সেকেন্ড থামে, **read চলতে থাকে** (কারণ cache + replica)
- Analytics queue জমে গেল → click দেরিতে আসে, redirect অক্ষত। সঠিক অগ্রাধিকার।

---

## ৪.১১ সাধারণ ভুল

১. **Estimate-এর আগে design** — read:write অনুপাত না জেনে আপনি জানতেই পারবেন না আপনার cache লাগবে কিনা
২. **কল্পিত scale-এর জন্য over-engineer** — সেকেন্ডে ৪০০ write-এর জন্য sharding
৩. **Peak factor ভুলে যাওয়া** — গড় traffic-এর জন্য design করা, শুক্রবার রাতে মরা
৪. **Stateful app server** — horizontal scaling-এর ১ নম্বর বাধা
৫. **Liveness probe যেটা database যাচাই করে** — একটা ঝাঁকুনিকে cluster-জোড়া restart লুপে পরিণত করে
৬. **"টাকা বাঁচাতে" ৯০% utilisation-এ চালানো**
৭. **App tier scale করা কিন্তু connection pool নয়** — আপনি এইমাত্র নিজের database-কে DDoS করলেন
৮. **এমন shard key বাছা যা write-এর ধরনের সাথে মেলে কিন্তু read-এর সাথে নয়** (বা উল্টোটা)
৯. **ধরে নেওয়া যে replication মানে কোনো data হারাবে না** — async replication failover-এ লেজটুকু হারায়; এটা স্পষ্ট করে বলুন
১০. **Cache-cold start-এর কোনো পরিকল্পনা নেই** — প্রতিটা deploy একটা outage হয়ে যায়
১১. **নেটওয়ার্ক উপেক্ষা করা** — ৭টা synchronous hop × ২০ ms মানে কোনো কাজ শুরুর আগেই ১৪০ ms-এর মেঝে
১২. **Trade-off না বলা** — trade-off ছাড়া একটা design একটা ইচ্ছার তালিকা

---

## ৪.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] DAU, RPS (গড় **আর** peak), storage আর bandwidth estimate করা
- [ ] Read:write অনুপাত হিসাব করা — design কি সেটা প্রতিফলিত করে?
- [ ] ১২ আর ২৪ মাসের বৃদ্ধির পূর্বাভাস; trigger পয়েন্ট চিহ্নিত
- [ ] প্রতিটা tier stateless, নাকি state ইচ্ছাকৃতভাবে বাইরে সরানো
- [ ] Little's Law প্রয়োগ করা: thread, connection আর pool-এর আকার যাচাই করা
- [ ] লক্ষ্য utilisation ৫০–৭০%, প্রতি availability zone-এ N+১ redundancy সহ
- [ ] Load balancer: L4/L7 বাছা, algorithm বাছা, health check সঠিক
- [ ] Caching-এর কৌশল নির্ধারিত, cache খালি বা বন্ধ থাকলে আচরণ সহ
- [ ] Replication: sync/async বাছা; replication-lag-এর bug-এর সমাধান করা
- [ ] Sharding: এখন লাগবে? না লাগলে trigger কী? Key কি তবু design করা আছে?
- [ ] Diagram-এর প্রতিটা বাক্সের জন্য failure mode চিহ্নিত
- [ ] মাসিক আর প্রতি transaction-এ খরচ estimate করা
- [ ] Trade-off স্পষ্টভাবে লেখা

---

## ৪.১৩ নিজেকে যাচাই

১. ৫০ লাখ DAU, প্রত্যেকে দিনে ২০টা কাজ। গড় RPS? Peak?
২. ৮০০ RPS, প্রতি request-এ ২৫০ ms। কতগুলো concurrent request? কতগুলো DB connection?
৩. ~৮০% utilisation-এর উপরে latency কেন বিস্ফোরিত হয়? আঙুলের নিয়মের লক্ষ্য কত?
৪. আপনার server stateless হলে state কোন চারটা জায়গায় থাকতে পারে, প্রতিটার একটা অসুবিধা সহ বলুন।
৫. Horizontally-র আগে vertically scale করা উচিত কেন? পুরো সুপারিশকৃত ক্রম দিন।
৬. Liveness আর readiness probe-এর পার্থক্য কী, আর ক্লাসিক বিপর্যয়টা কী?
৭. W + R > N ব্যাখ্যা করুন। N=৩ সহ "strong consistency, একটা node ব্যর্থতা সহ্য করবে" — এর জন্য একটা configuration দিন।
৮. আপনার ব্যবহারকারী একটা profile save করে সাথে সাথে পুরনো মান দেখছেন। রোগনির্ণয় করুন আর চারটা সমাধান দিন।
৯. চারটা sharding কৌশলের নাম বলুন আর প্রতিটা যেখানে জেতে এমন একটা করে পরিস্থিতি দিন।
১০. একটা ভালো shard key কী দিয়ে তৈরি? একটা multi-tenant SaaS-এর জন্য একটা ভালো আর একটা খারাপ key দিন।
১১. Primary key হিসেবে UUIDv7 কেন UUIDv4-এর চেয়ে ভালো?
১২. কখন shard করবেন? আগে যা যা করা উচিত সব তালিকাভুক্ত করুন।

---

## ৪.১৪ মূল কথাগুলো

- **Design-এর আগে estimate করুন।** পাঁচ লাইনের পাটিগণিত পাঁচটা architecture-এর সিদ্ধান্ত দেয়।
- বেশিরভাগ সিস্টেমে **read:write অনুপাতই সবচেয়ে তথ্যপূর্ণ একটামাত্র সংখ্যা**
- মুখস্থ করুন: **RAM ১০০ ns, SSD ১৫০ µs, একই DC-তে round trip ০.৫ ms, মহাদেশ পেরিয়ে ১৫০ ms**
- **Little's Law (L = λW)** latency-কে concurrency-তে, concurrency-কে pool-এর আকারে পরিণত করে
- **৫০–৭০% utilisation লক্ষ্য রাখুন।** ৮০%-এর উপরে latency বিস্ফোরিত হয়।
- **যা কিছু পারেন stateless করুন।** Horizontal scaling-এর চাবি এটাই।
- **Optimise → scale up → read scale out → shard।** এই ক্রমেই। সবসময়।
- **Replication availability আর read-এর জন্য। Partitioning আকার আর write-এর জন্য।** সাধারণত আপনার দুটোই লাগে।
- **Sharding শেষ আশ্রয়** — তবে multi-tenant সিস্টেমে shard key আগেভাগে design করুন
- প্রতিটা design-কে উত্তর দিতে হবে: **প্রতিটা বাক্স মরলে কী হয়?**

---

**পরবর্তী:** [অধ্যায় ০৫ — Distributed Systems](05-distributed-systems.md)

**ইংরেজি সংস্করণ:** [Chapter 04](../04-system-design-fundamentals.md) · **[সূচিপত্র](README.md)**
