# অধ্যায় ১৪ — Cloud Architecture 🟡

> ২০০টা service-এর নাম মুখস্থ করবেন না। **সাতটা শ্রেণি** শিখুন, প্রতি শ্রেণিতে এক-দুটো service জানুন, আর **খরচ ও ব্যর্থতার মডেল** বুঝুন।
> তাহলে যে কোনো ক্লাউডের service-তালিকা পড়া যায় হয়ে যাবে, কারণ সবাই একই সমস্যা আলাদা নামে সমাধান করে।

---

## ১৪.১ মানসিক মডেল: সাতটা শ্রেণি

প্রতিটা ক্লাউড একই সাতটা বাক্স।

| # | শ্রেণি | যে সমস্যার সমাধান করে | AWS | Azure | GCP |
|---|----------|----------------------|-----|-------|-----|
| ১ | **Compute** | কোড চালানো | EC2, ECS, Fargate, Lambda, EKS | VM, App Service, Container Apps, Functions, AKS | Compute Engine, Cloud Run, Functions, GKE |
| ২ | **Storage** | ফাইল আর block রাখা | S3, EBS, EFS | Blob, Managed Disks, Files | Cloud Storage, Persistent Disk, Filestore |
| ৩ | **Database** | কাঠামোবদ্ধ data রাখা | RDS, Aurora, DynamoDB, ElastiCache | Azure SQL, Cosmos DB, Cache for Redis | Cloud SQL, Spanner, Firestore, Memorystore |
| ৪ | **Networking** | জিনিস জোড়া লাগানো | VPC, ALB/NLB, Route 53, CloudFront | VNet, App Gateway, Front Door, CDN | VPC, Cloud LB, Cloud DNS, Cloud CDN |
| ৫ | **Messaging** | জিনিস decouple করা | SQS, SNS, EventBridge, MSK, Kinesis | Service Bus, Event Grid, Event Hubs | Pub/Sub, Cloud Tasks |
| ৬ | **Identity ও Security** | Access নিয়ন্ত্রণ, গোপন তথ্য রাখা | IAM, KMS, Secrets Manager, WAF | Entra ID, Key Vault, Defender | IAM, KMS, Secret Manager |
| ৭ | **Observability** | কী হচ্ছে দেখা | CloudWatch, X-Ray | Monitor, App Insights | Cloud Monitoring, Trace |

> **অচেনা কোনো service-এর দেখা পেলে জিজ্ঞেস করুন এটা সাতটা বাক্সের কোনটায়।** শুধু এটুকুই আপনাকে মূল্যায়নের জন্য যা লাগে তার বেশিরভাগ বলে দেয়।

---

## ১৪.২ যে মূল ধারণাগুলো প্রতিটা design-এর আকার দেয়

### Region আর Availability Zone ⭐

```
REGION (যেমন eu-west-1, আয়ারল্যান্ড)
│   একটা ভৌগোলিক এলাকা। Region গুলো ~স্বাধীন। আপনি না সরালে data
│   এদের মধ্যে যায় না। Region-এর মধ্যে latency: ১০–৩০০ ms।
│
├── AVAILABILITY ZONE A  ── এক বা একাধিক শারীরিকভাবে আলাদা datacenter
├── AVAILABILITY ZONE B  ── আলাদা বিদ্যুৎ, শীতাতপ, নেটওয়ার্ক
└── AVAILABILITY ZONE C  ── তবে এতটাই কাছে যে এদের মধ্যে ১–২ ms latency
```

**ক্লাউড design-এর একক সবচেয়ে গুরুত্বপূর্ণ নিয়ম:**

> **সবসময় একটা region-এর অন্তত ২টা (আদর্শভাবে ৩টা) Availability Zone জুড়ে deploy করুন। Multi-region-এ যান শুধু তখনই যখন আপনার একটা নির্দিষ্ট, খরচ-হিসাব করা কারণ আছে।**

| | Multi-AZ | Multi-Region |
|---|---|---|
| কী থেকে রক্ষা করে | একটা datacenter-এর ব্যর্থতা | একটা পুরো region-এর ব্যর্থতা, বা ভৌগোলিক নৈকট্য দেয় |
| এদের মধ্যে latency | ১–২ ms — synchronous replication ঠিক আছে | ১০–৩০০ ms — synchronous replication সাধারণত সম্ভব নয় |
| খরচ | মাঝারি (cross-AZ data-র চার্জ) | **সবকিছু ২×**, সাথে replication আর জটিলতা |
| জটিলতা | কম — বেশিরভাগ managed service আপনার হয়ে করে দেয় | **বেশি** — data consistency, failover, DNS, split brain |
| সাধারণত কার লাগে | **সবার** | Regulatory residency, বৈশ্বিক latency, বা একটা খুব উঁচু মূল্যের SLA |

**Multi-region হলো সবচেয়ে বেশি চাওয়া আর সবচেয়ে কম বিশ্লেষণ করা architecture সিদ্ধান্ত।** এটা আপনার খরচ দ্বিগুণ করে আর জটিলতা বহুগুণ করে। রাজি হওয়ার আগে জিজ্ঞেস করুন: *"একটা ৪ ঘণ্টার regional outage-এর business খরচ কত, আর region আসলে কত ঘন ঘন fail করে?"* সাধারণত সৎ উত্তরটা হলো "গ্রহণযোগ্য পরিমাণ, মোটামুটি কয়েক বছরে একবার" — আর একটা ভালোভাবে পরীক্ষিত multi-AZ সেটআপ আর একটা নথিভুক্ত regional DR পরিকল্পনাই (অধ্যায় ১৯) সঠিক সিদ্ধান্ত।

**Multi-region কখন যুক্তিসঙ্গত:**
- Data residency-র আইন (EU-র data EU-তে থাকতে হবে) — প্রযোজ্য হলে এটা আপসহীন
- কয়েকটা মহাদেশে ব্যবহারকারী আর latency বাণিজ্যিকভাবে গুরুত্বপূর্ণ
- একটা চুক্তিভিত্তিক SLA যা একটা region মেটাতে পারে না
- Regulatory DR-এর দাবি (finance-এ সাধারণ)

### Shared Responsibility Model 🟢

**এই ধারণাটাই ঠিক করে কার দোষ।**

```
                    ┌────────────────────────────────────┐
   আপনার কাজ         │  আপনার data, আপনার কোড             │
                    │  Identity ও access management      │
                    │  Network ও firewall-এর configuration│
                    │  Encryption-এর setting             │
                    │  OS patch করা (শুধু IaaS)           │
                    ├────────────────────────────────────┤
   ক্লাউডের কাজ       │  শারীরিক নিরাপত্তা                  │
                    │  Hardware, network infrastructure  │
                    │  Hypervisor                        │
                    │  Managed service-এর ভেতরের অংশ      │
                    └────────────────────────────────────┘
```

Service model অনুযায়ী রেখাটা সরে:

| মডেল | আপনি সামলান | তাঁরা সামলান |
|-------|-----------|-------------|
| **IaaS** (EC2, VM) | OS, patch, runtime, app, data, config | Hardware, network, hypervisor |
| **CaaS** (ECS/Fargate, Container Apps) | Container image, app, data, config | Host OS, orchestration, patch |
| **PaaS** (App Service, Cloud Run) | App-এর কোড, data, config | Runtime, OS, scaling, patch |
| **FaaS** (Lambda, Functions) | Function-এর কোড, config | বাকি সব |
| **SaaS** | আপনার data আর কে দেখতে পারে | বাকি সব |

> **প্রায় প্রতিটা ক্লাউড breach গ্রাহকের দিকের একটা ভুল configuration**, ক্লাউড প্রোভাইডারের ব্যর্থতা নয়: একটা public S3 bucket, একটা অতিরিক্ত অনুমতির IAM role, 0.0.0.0/0-তে খোলা একটা security group, একটা Git repository-তে ফাঁস হওয়া access key। **ক্লাউড নিরাপদ; ক্লাউডের *configuration* প্রায়ই নয়।**

---

## ১৪.৩ Compute — সঠিকটা বেছে নেওয়া 🟢

```
আপনার কি OS-স্তরের নিয়ন্ত্রণ, custom kernel, বা licensed সফটওয়্যার লাগে?
├── হ্যাঁ → VIRTUAL MACHINE (EC2 / Azure VM / Compute Engine)
└── না  → কাজটা কি event-চালিত, ঢেউ-খেলানো, বা খুব কম volume-এর?
          ├── হ্যাঁ → SERVERLESS FUNCTION (Lambda / Functions)
          └── না  → আপনার কি জটিল orchestration লাগে এমন অনেক service আছে?
                    ├── হ্যাঁ → KUBERNETES (EKS / AKS / GKE)
                    └── না  → SERVERLESS CONTAINER ⭐
                              (Fargate / Cloud Run / Container Apps)
```

### যে তুলনাটা গুরুত্বপূর্ণ

| | VM | Kubernetes | Serverless container | Function |
|---|---|---|---|---|
| Ops-এর ভার | **বেশি** | **সবচেয়ে বেশি** | **কম** | **সবচেয়ে কম** |
| স্থির load-এ খরচ | কম (reservation সহ) | কম (ভালো bin-packing) | মাঝারি | বেশি |
| অলস থাকলে খরচ | পুরো দাম | পুরো দাম | **প্রায় শূন্য** | **শূন্য** |
| Cold start | নেই | নেই | ১–১০ সেকেন্ড (বা min instance রাখুন) | ০.১–৫ সেকেন্ড |
| সর্বোচ্চ চলার সময় | সীমাহীন | সীমাহীন | সীমাহীন | ~১৫ মিনিট |
| বহনযোগ্যতা | মাঝারি | **সবচেয়ে বেশি** | বেশি (এটা একটা container) | **সবচেয়ে কম** |
| Scaling-এর গতি | মিনিট | সেকেন্ড | সেকেন্ড | মিলিসেকেন্ড |
| কীসের জন্য সেরা | Legacy, licensed সফটওয়্যার, GPU/বিশেষায়িত | অনেক service, একটা platform টিম | **বেশিরভাগ আধুনিক web service** | আঠা, cron, ঢেউ-খেলানো, কম volume |

> **কম মূল্যায়িত default: serverless container** (Cloud Run, Fargate, Container Apps)। আপনি একটা স্বাভাবিক Docker image-এ একটা স্বাভাবিক app লেখেন, আর আপনি পান autoscaling (শূন্য পর্যন্ত), managed patching, আর চালানোর মতো কোনো cluster নেই। Platform engineer ছাড়া একটা টিমের জন্য সাধারণত এটাই সঠিক উত্তর — আর FaaS-এর বিপরীতে আপনি বহনযোগ্যতা রাখেন, কারণ এটা শুধুই একটা container।

### Kubernetes-এর প্রশ্ন, সৎভাবে

**Kubernetes ব্যবহার করুন যখন:**
- আপনার সত্যিকারের orchestration-এর চাহিদা সহ ১০+ service আছে
- আপনার এমন কেউ আছেন (বা নিয়োগ করবেন) যিনি সত্যিই এটা জানেন
- আপনার multi-cloud বা hybrid বহনযোগ্যতা লাগে
- আপনার এর ecosystem লাগে (operator, service mesh, জটিল scheduling, GPU ভাগ করা)

**Kubernetes ব্যবহার করবেন না যখন:**
- আপনার ১–৫টা service আছে — আপনি product-এর চেয়ে cluster-এ বেশি সময় দেবেন
- টিমের কেউ রাত ৩টায় একটা CrashLoopBackOff debug করতে পারেন না
- একটা PaaS বা serverless container কাজটা করে দিত

> **Managed Kubernetes (EKS/AKS/GKE) control-plane ব্যবস্থাপনা সরায়, কিন্তু operational ভার নয়।** Upgrade, networking, ingress, autoscaling, RBAC, storage class, resource limit আর খরচ ব্যবস্থাপনা এখনো আপনারই। একজন ইঞ্জিনিয়ারের অর্থপূর্ণ মনোযোগ স্থায়ীভাবে বরাদ্দ রাখুন। (অধ্যায় ১৫।)

### কেনার মডেল — টাকা যেখানে

| মডেল | ছাড় | প্রতিশ্রুতি | কীসের জন্য |
|-------|----------|-----------|---------|
| **On-demand** | ০% | কিছু না | Development, অনিশ্চিত ঢেউ |
| **Reserved / Savings Plan** | ৩০–৭২% | ১–৩ বছর | **আপনার ভিত্তি ক্ষমতা** — এটাই সবচেয়ে বড় সহজ সাশ্রয় |
| **Spot / Preemptible** | **৭০–৯০%** | ~২ মিনিটে ফিরিয়ে নেওয়া হতে পারে | Batch job, CI, stateless worker, ML training |
| **Dedicated host** | — | বাড়তি দাম | Licensing বা compliance-এর বিচ্ছিন্নতা |

> **প্রচলিত খরচের কৌশল: আপনার ভিত্তি reserve করুন, peak-টা on-demand-এ autoscale করুন, সব batch আর CI Spot-এ চালান।** বেশিরভাগ কোম্পানি শুধু এই কারণেই বেশি দেয় যে কেউ এটা করেনি। এটা প্রায়ই এক সপ্তাহের কাজে ৪০%+ হ্রাস — একজন আর্কিটেক্ট business-এর জন্য যা করতে পারেন তার মধ্যে সবচেয়ে মূল্যবানগুলোর একটা।

---

## ১৪.৪ Storage 🟢

### তিন ধরন, আর এরা একে অপরের বদলি নয়

| | **Object** (S3/Blob) | **Block** (EBS/Disk) | **File** (EFS/Files) |
|---|---|---|---|
| Interface | HTTP API | একটা VM-এ যুক্ত একটা disk | NFS/SMB mount, অনেক VM |
| গঠন | সমতল key → blob | কাঁচা block | ডিরেক্টরির গাছ |
| হালনাগাদ | **পুরো object বদলান** | যে কোনো byte | যে কোনো byte |
| যার সাথে যুক্ত হয় | যা কিছু, HTTP-তে | সাধারণত একটা instance | অনেক instance |
| Scale | **কার্যত সীমাহীন** | প্রতি volume-এ সীমা | বড় |
| খরচ | **সবচেয়ে সস্তা** (~$০.০২৩/GB) | ~$০.০৮/GB | ~$০.৩০/GB |
| Durability | ১১টা নাইন | বেশি | বেশি |
| কীসের জন্য | ছবি, ভিডিও, backup, log, data lake | Database-এর volume, OS disk | Shared config, filesystem লাগে এমন legacy app |

> **Default-এ object storage নিন।** এটা সবচেয়ে সস্তা, সবচেয়ে টেকসই, সবচেয়ে scale-যোগ্য বিকল্প, আর যা কিছু একটা "ফাইল" তার সঠিক ঘর। Database-এর জন্য block storage ব্যবহার করুন। File storage শুধু তখনই যখন একটা application-এর সত্যিই মেশিন জুড়ে ভাগ করা একটা POSIX filesystem লাগে — এটা ব্যয়বহুল আর প্রায়ই এমন একটা design-এর চিহ্ন যা আধুনিক করা হয়নি।

### Storage class আর lifecycle — স্বয়ংক্রিয় টাকা সাশ্রয়

```
Hot / Standard     ~$০.০২৩/GB/মাস   তাৎক্ষণিক প্রবেশ        — সক্রিয় data
Infrequent Access  ~$০.০১২৫/GB/মাস  তাৎক্ষণিক, আনার ফি      — ৩০+ দিনের পুরনো
Archive / Glacier  ~$০.০০৪/GB/মাস   মিনিট থেকে ঘণ্টা         — ৯০+ দিনের পুরনো
Deep Archive       ~$০.০০০৯৯/GB/মাস ১২+ ঘণ্টা               — compliance-এর retention
```

```json
{
  "Rules": [{
    "Id": "verification-video-lifecycle",
    "Filter": { "Prefix": "videos/" },
    "Transitions": [
      { "Days": 7,  "StorageClass": "STANDARD_IA" },
      { "Days": 30, "StorageClass": "GLACIER_IR" }
    ],
    "Expiration": { "Days": 90 }
  }]
}
```

ওই একটা policy আপনার আইনি retention-এর দাবি **আর** storage-এর খরচ ~৮০% কমানো — দুটোই করে। অধ্যায় ০৪-এর liveness SaaS উদাহরণের জন্য (১৭.৮ TB ভিডিও) এটা ~$৪০০/মাস আর ~$৯০/মাসের পার্থক্য — আর মুছে ফেলাটা স্বয়ংক্রিয় আর audit-যোগ্য, যেটাই নিয়ন্ত্রক আসলে চান।

### যে pattern গুলো architecture-গতভাবে গুরুত্বপূর্ণ

**১. Presigned URL — কখনো আপনার API দিয়ে বড় ফাইল পাঠাবেন না**

```python
# Client সরাসরি storage-এ upload করে। আপনার API byte গুলো দেখেই না।
url = s3.generate_presigned_url(
    "put_object",
    Params={"Bucket": "uploads", "Key": f"videos/{session_id}.mp4",
            "ContentType": "video/mp4"},
    ExpiresIn=900,                       # ১৫ মিনিট
)
return {"upload_url": url, "session_id": session_id}
```

এটা আপনার application স্তর থেকে bandwidth, memory-র চাপ আর timeout-এর ঝুঁকি পুরোপুরি সরিয়ে দেয়। এটা সবচেয়ে মূল্যবান ক্লাউড pattern গুলোর একটা আর প্রায়ই বাদ পড়ে যায়।

**২. Event-চালিত প্রক্রিয়াকরণ** — একটা object upload একটা event ছাড়ে যেটা আপনার worker চালায়। কোনো polling নয়।

**৩. Versioning + object lock** — versioning দুর্ঘটনাজনিত মুছে ফেলা আর উপরে লেখা থেকে রক্ষা করে; object lock (WORM) immutable, ransomware-প্রতিরোধী backup দেয় আর প্রায়ই একটা compliance-এর দাবি।

**৪. Account স্তরে public access বন্ধ করুন** — আর যে কোনো ব্যতিক্রমকে একটা review করা নিরাপত্তা-সিদ্ধান্ত হিসেবে দেখুন, সুবিধা হিসেবে নয়।

---

## ১৪.৫ Managed database 🟡

| Service-এর ধরন | আপনি যা পান | আপনি যা হারান |
|--------------|--------------|---------------|
| **Managed relational** (RDS, Cloud SQL, Azure SQL) | Backup, patch, failover, replica, monitoring | Superuser access, কিছু extension, version-এর সময় |
| **Cloud-নেটিভ relational** (Aurora, AlloyDB) | দ্রুত, storage স্বয়ংক্রিয় বাড়ে, প্রায়-তাৎক্ষণিক replica | Lock-in, বেশি খরচ |
| **Distributed SQL** (Spanner, CockroachDB) | SQL আর ACID **সহ** horizontal scale | খরচ, latency-র মেঝে, কিছু SQL সীমাবদ্ধতা |
| **Managed NoSQL** (DynamoDB, Cosmos DB) | Serverless scale, কম ops | Query-first modelling, lock-in |
| **Managed cache** (ElastiCache, Memorystore) | না চালিয়েই HA Redis | খরচ, কম tuning-এর নিয়ন্ত্রণ |

> **Default পরামর্শ: managed service ব্যবহার করুন।** VM-এ নিজের database চালানো মানে backup, patch, failover testing, replication monitoring আর রাত ৩টার পুনরুদ্ধার সবই আপনার। একজন নিবেদিত DBA আর একটা শক্ত কারণ না থাকলে managed-এর বাড়তি দামটা চমৎকার মূল্যের।

### যে কোনো managed database-কে করার তিনটা প্রশ্ন

১. **একটা failover-এর সময় ঠিক কী হয়, আর কতক্ষণ লাগে?** (RDS Multi-AZ: সাধারণত ৬০–১২০ সেকেন্ড, আর connection ছিঁড়ে যায় — আপনার application-কে আবার যুক্ত হতে হবে।)
২. **Backup আর PITR-এর জানালা কত, আর আমরা কি একটা restore test করেছি?** (অধ্যায় ০৯ — অপরীক্ষিত backup হলো আশা।)
৩. **গ্রহণযোগ্য downtime-এ আমরা কীভাবে একটা major version upgrade করব?** (সাধারণত একটা নতুন instance-এ logical replication, তারপর একটা cutover।)

### Serverless database

Aurora Serverless v2, DynamoDB on-demand, Cosmos serverless, Neon — ক্ষমতা স্বয়ংক্রিয়ভাবে scale করে আর আপনি ব্যবহার অনুযায়ী দেন।

- ✅ অনিশ্চিত, ঢেউ-খেলানো বা development কাজের জন্য চমৎকার; অলস থাকলে সত্যিই প্রায়-শূন্য খরচে নামে
- ❌ স্থির উচ্চ load-এ বেশি ব্যয়বহুল; মাঝে মাঝে scaling-এর latency; **connection-এর সীমা তবু প্রযোজ্য** (একটা proxy/pooler ব্যবহার করুন, অধ্যায় ০৯)

---

## ১৪.৬ Identity আর access (IAM) 🟢

**IAM-এই ক্লাউডের নিরাপত্তা জেতা বা হারা হয়।** বেশিরভাগ ক্লাউড breach-এর সূত্র অতিরিক্ত অনুমতির পরিচয়ে, কোনো চতুর exploit-এ নয়।

### নিয়মগুলো

**১. কাজের জন্য কখনো দীর্ঘস্থায়ী access key ব্যবহার করবেন না।**

```
❌ একটা environment variable-এ, একটা config ফাইলে, বা (সবচেয়ে খারাপ)
   একটা Git repository-তে AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
✅ EC2/ECS/Lambda-র জন্য IAM role; Kubernetes-এর জন্য Workload Identity / IRSA;
   Azure-এ Managed Identity; CI/CD-র জন্য OIDC federation
```

তখন credential স্বল্পস্থায়ী, স্বয়ংক্রিয়ভাবে ঘোরানো, আর ফাঁস হওয়ার মতো কিছুই থাকে না। **GitHub Actions OIDC দিয়ে একটা ক্লাউড role ধারণ করতে পারে — CI-র secret-এ ক্লাউডের key রাখার আর কোনো কারণ নেই।**

**২. Least privilege, আর সেটা যাচাই করুন।**

```json
// ❌ সাধারণ, অলস, বিপজ্জনক
{ "Effect": "Allow", "Action": "s3:*", "Resource": "*" }

// ✅ নির্দিষ্ট action, নির্দিষ্ট resource, শর্ত সহ
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject"],
  "Resource": "arn:aws:s3:::verification-videos/tenants/${aws:PrincipalTag/tenant}/*",
  "Condition": {
    "Bool": { "aws:SecureTransport": "true" },
    "StringEquals": { "s3:x-amz-server-side-encryption": "aws:kms" }
  }
}
```

**৩. প্রতি পরিবেশে আলাদা account/subscription।** Production নিজের account-এ থাকাই উপলব্ধ সবচেয়ে শক্তিশালী blast-radius নিয়ন্ত্রণ — dev-এর একটা ভুল production ছুঁতে পারে না, আর বিনামূল্যে billing আলাদা হয়ে যায়।

**৪. মানুষ role পায়, user নয়।** আপনার identity provider (Entra ID, Okta, Google Workspace) থেকে SSO আর MFA সহ federate করুন। কেউ চলে গেলে একটা account বন্ধ করলেই সব ক্লাউড access চলে যায়।

**৫. প্রতিটা permission সাময়িক, যতক্ষণ না প্রমাণ হয় নয়।** Access analyser আর অব্যবহৃত-permission-এর report ব্যবহার করুন; ক্লাউড প্রোভাইডাররা এখন পর্যবেক্ষিত ব্যবহার থেকে least-privilege policy তৈরি করে দেয়।

### Secret ব্যবস্থাপনা

```
❌ একটা repo-তে commit করা environment variable-এ secret
❌ Container image-এ secret
❌ একটা shared drive-এর config ফাইলে secret
⚠️ রানটাইমে environment variable-এ secret (গ্রহণযোগ্য; process listing আর crash dump-এ দেখা যায়)
✅ স্বয়ংক্রিয় ঘোরানো আর audit logging সহ একটা secrets manager
✅ আরও ভালো: কোনো static secret-ই নয় — IAM-ভিত্তিক database auth, workload identity
```

> **যে শেষ অবস্থার দিকে লক্ষ্য রাখবেন: আপনার application-এ কোনো দীর্ঘস্থায়ী credential-ই নেই।** এটা platform-এর দেওয়া একটা পরিচয় দেখায় আর স্বল্পস্থায়ী token পায়। এটা "ফাঁস হওয়া credential"-এর পুরো শ্রেণিটাই দূর করে।

---

## ১৪.৭ খরচ ব্যবস্থাপনা 🟢

**ক্লাউডের খরচ একটা architecture-এর বিষয়, finance-এর সমস্যা নয়।** Architecture-এর সিদ্ধান্তই বিলের ৮০% ঠিক করে।

### টাকা আসলে কোথায় যায়

সাধারণ মাঝারি আকারের SaaS:

```
Compute            ৪০-৫৫%   ← reservation আর right-sizing এখানে থাকে
Data transfer      ১০-২৫%   ← চমকে দেওয়া খরচের লাইন
Storage            ১০-২০%   ← lifecycle policy এখানে থাকে
Managed database   ১০-২০%
বাকি সব             ৫-১০%
```

### সবচেয়ে বড় আর সবচেয়ে সাধারণ অপচয়

| অপচয় | সাধারণ আকার | সমাধান |
|-------|-------------|-----|
| **অতিরিক্ত বরাদ্দ করা instance** | compute-এর ৩০–৫০% | আসল metric থেকে সঠিক আকার দিন; বেশিরভাগ instance ১০% CPU-তে চলে |
| **ভিত্তি load-এ কোনো reservation নেই** | compute-এর ৩০–৫০% | Savings Plan / Reserved Instance |
| **অনাথ resource** | ৫–১৫% | যুক্ত না থাকা disk, অলস load balancer, পুরনো snapshot, অব্যবহৃত IP |
| **Non-production ২৪/৭ চলছে** | non-prod-এর ৬০% | অফিস-সময়ের বাইরে dev/test বন্ধ নির্ধারণ করুন |
| **Cross-AZ আর NAT gateway-র traffic** | compute ছাড়িয়ে যেতে পারে | Traffic AZ-র ভেতরে রাখুন; VPC endpoint ব্যবহার করুন; সামনে একটা CDN বসান |
| **Log আর metric-এর retention** | আশ্চর্যরকম বড় | স্তরভিত্তিক retention; উচ্চ-volume debug log sample করুন |
| **কোনো storage lifecycle policy নেই** | storage-এর ৫০–৮০% | স্বয়ংক্রিয় tiering আর মেয়াদশেষ |

### খরচ দৃশ্যমান করুন

```
১. সবকিছুতে TAG দিন          environment, team, service, cost-centre
                            → policy দিয়ে বলবৎ করুন; tag নেই = স্বয়ংক্রিয়ভাবে চিহ্নিত
২. BUDGET আর ALERT           মাসিক বাজেটের ৫০/৮০/১০০%-এ alert
৩. ANOMALY DETECTION        invoice-এ নয়, সেদিনই নিয়ন্ত্রণহীন job ধরুন
৪. UNIT ECONOMICS           ⭐ প্রতি verification / প্রতি tenant / প্রতি ১০০০ API call-এ খরচ
৫. টিমকে তাদের খরচ দেখান     প্রতি টিমে একটা dashboard যে কোনো policy-র চেয়ে বেশি আচরণ বদলায়
```

> **Unit economics-ই আর্কিটেক্টের সংখ্যা।** "আমরা মাসে $৪৭,০০০ খরচ করি" কারও কাছে কিছুই মানে না। **"প্রতি verification-এ আমাদের $০.০১৪ খরচ হয়, আর আমাদের দাম $০.১৫"** — এটা এমন একটা বাক্য যা সিদ্ধান্ত চালায়: এটা আপনার মুনাফা, আপনার scaling-এর জায়গা, আর ঠিক কোন component optimise করতে হবে সব বলে দেয়। এটা হিসাব করুন আর একটা dashboard-এ রাখুন।

### এক অনুচ্ছেদে FinOps

Engineering, finance আর product-কে একটা আলোচনায় আনুন: ইঞ্জিনিয়াররা তাঁদের পছন্দের খরচ দেখেন, finance পরিবর্তনশীল ক্লাউড খরচ বোঝে, আর product প্রতি feature-এর মুনাফা জানে। ব্যবহারিক শুরুর বিন্দু হলো tagging আর একটা প্রতি-টিম dashboard — সাধারণত শুধু এটাই এক কোয়ার্টারে ১৫–২৫% অপচয় সরিয়ে দেয়, কারণ যে ইঞ্জিনিয়াররা খরচ দেখতে পান তাঁরা না বললেও ব্যবস্থা নেন।

---

## ১৪.৮ Well-Architected — ছয়টা স্তম্ভ 🟡

প্রতিটা ক্লাউড এর একটা সংস্করণ প্রকাশ করে। এটা সত্যিই একটা কাজের রিভিউ চেকলিস্ট।

| স্তম্ভ | প্রশ্ন | মূল চর্চা |
|--------|-------------|---------------|
| **Operational excellence** | আমরা কি এটা চালাতে আর উন্নত করতে পারি? | IaC, CI/CD, runbook, observability, দোষারোপহীন postmortem |
| **Security** | আমরা কি সুরক্ষিত? | Least privilege, সব জায়গায় encryption, স্তরে স্তরে প্রতিরক্ষা, audit log |
| **Reliability** | এটা কি ফিরে আসে? | Multi-AZ, health check, retry, পরীক্ষিত backup, DR মহড়া |
| **Performance efficiency** | আমরা কি সঠিক সম্পদ ব্যবহার করছি? | সঠিক আকার, caching, কাজের জন্য সঠিক service, পরিমাপ |
| **Cost optimisation** | আমরা কি বেশি দিচ্ছি? | Reservation, lifecycle policy, সঠিক আকার, unit economics |
| **Sustainability** | এটা কি দক্ষ? | সঠিক আকার, আধুনিক instance type, region-এর কার্বন-ঘনত্ব |

> **প্রতি প্রধান সিস্টেমে বছরে একবার, আর যে কোনো বড় launch-এর আগে একবার একটা Well-Architected রিভিউ চালান।** এতে আধা দিন লাগে আর নির্ভরযোগ্যভাবে তিন-চারটা আসল সমস্যা খুঁজে পায়। একটা বিদ্যমান সিস্টেম নথিভুক্ত করারও এটা একটা চমৎকার উপায়, কারণ প্রশ্নগুলো আপনাকে জিনিস লিখে রাখতে বাধ্য করে।

---

## ১৪.৯ Multi-cloud আর lock-in 🟡

### Lock-in নিয়ে সৎ অবস্থান

Lock-in **দুইয়ের একটা নয়**, আর পুরোপুরি এড়ানোরও একটা দাম আছে।

```
কম LOCK-IN                                             বেশি LOCK-IN
│                                                                 │
VM, container ── managed Postgres ── managed queue ── DynamoDB ── Step Functions
  (বহনযোগ্য)       (বেশিরভাগ বহনযোগ্য)   (adapter দেওয়া যায়) (নতুন লিখতে হবে) (নতুন লিখতে হবে)
```

**যুক্তিসঙ্গত পদ্ধতি:**
- Managed service অবাধে ব্যবহার করুন — উৎপাদনশীলতার লাভটা বাস্তব আর বিশাল
- **প্রতিটাকে নিজের একটা interface-এর পেছনে লুকান** (Adapter/ACL, অধ্যায় ০১ আর ০৩), যাতে একটা পরিবর্তনের blast radius একটা ফাইল হয়
- আপনার **data** বহনযোগ্য রাখুন (প্রচলিত ফরম্যাট, Iceberg-এর মতো open table format — অধ্যায় ১২)
- গভীর lock-in শুধু সেখানেই মেনে নিন যেখানে service-টা সত্যিই ব্যতিক্রমী, আর লিখে রাখুন একটা migration-এ কত খরচ হবে

> **"সহনশীলতার জন্য" multi-cloud সাধারণত একটা ভুল।** আপনি দুই ক্লাউডের সর্বনিম্ন সাধারণ গুণ পান, দ্বিগুণ operational পরিসর, দ্বিগুণ দক্ষতার দাবি, আর আপনার টিম এখন একটায় ভালো হওয়ার বদলে দুটোয় মাঝারি। আপনি যে জটিলতা যোগ করবেন তার চেয়ে ক্লাউডের region অনেক কম fail করে।

**Multi-cloud যুক্তিসঙ্গত যখন:** একজন নিয়ন্ত্রক বা একজন বড় customer এটা দাবি করেন; আপনি বাণিজ্যিক কারণে একটা নির্দিষ্ট ভেন্ডর এড়াচ্ছেন; বা অধিগ্রহণের মাধ্যমে আপনি ইতিমধ্যেই সেখানে। বাস্তবে বেশিরভাগ "multi-cloud" কোম্পানি প্রতিটা workload একটা ক্লাউডে চালায় — যেটা ঠিক আছে, আর এটা একটা workload-কে দুটোতে চালানোর সমান নয়।

---

## ১৪.১০ একটা reference ক্লাউড architecture

Liveness verification SaaS-এর জন্য (সংখ্যা অধ্যায় ০৪ থেকে):

```
                            Route 53 / Front Door
                                     │
                          ┌──────────▼──────────┐
                          │   CloudFront / CDN  │  TLS, WAF, DDoS
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  ALB (public subnet)│  ৩টা AZ
                          └──────────┬──────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │ PRIVATE APP SUBNET (৩টা AZ)   │                               │
     │   ┌──────────────────┐        │      ┌──────────────────┐     │
     │   │ API (Fargate)    │◄───────┴─────►│ Worker (Fargate  │     │
     │   │ ২-১০টা task      │               │  + EC2-তে GPU)   │     │
     │   └────────┬─────────┘               │ ১-১০টা task, Spot│     │
     │            │                         └────────┬─────────┘     │
     │            │  enqueue                         │ dequeue       │
     │            └──────────► SQS / Service Bus ◄───┘               │
     └───────────────────────────────┬───────────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │ PRIVATE DATA SUBNET (৩টা AZ)  │                               │
     │  ┌─────────────┐  ┌───────────▼──┐  ┌──────────────────────┐  │
     │  │ RDS Postgres│  │ ElastiCache  │  │ S3 (ভিডিও)            │  │
     │  │ Multi-AZ    │  │ Redis, multi │  │ lifecycle: ৭দিন IA,   │  │
     │  │ + replica   │  │ -AZ          │  │ ৩০দিন Glacier, ৯০দিন │  │
     │  └─────────────┘  └──────────────┘  └──────────────────────┘  │
     └───────────────────────────────────────────────────────────────┘

     সবকিছু জুড়ে: Secrets Manager · KMS · CloudWatch/OTel · CloudTrail
     Client presigned URL দিয়ে সরাসরি S3-তে ভিডিও upload করে (কখনো API দিয়ে নয়)
```

**সিদ্ধান্ত আর তার কারণ — বাস্তবে একটা ADR দেখতে এমনই:**

| সিদ্ধান্ত | কেন |
|----------|-----|
| Fargate, Kubernetes নয় | ২টা service, ৪ জন ইঞ্জিনিয়ার। কোনো platform টিম নেই। বহনযোগ্য (container)। |
| API আর worker-এর মাঝে queue | Peak শুষে নেয়; GPU worker-কে স্বাধীনভাবে scale করতে দেয়; কোনো কাজ হারায় না |
| Spot-এ GPU worker | ৭০–৯০% সস্তা; কাজ retry-যোগ্য আর queue-তে, তাই বিঘ্ন ক্ষতিকর নয় |
| Presigned S3 upload | ৬ MB ভিডিও কখনো API স্তর ছোঁয় না — bandwidth, memory আর timeout-এর ঝুঁকি সরায় |
| RDS Multi-AZ | ~৯০ সেকেন্ড failover সহ একটা AZ-র ব্যর্থতা টেকে; multi-region-এর চেয়ে অনেক সস্তা |
| একটা region | এখনো কোনো residency-র দাবি নেই; একটা ৪ ঘণ্টার regional outage বাণিজ্যিকভাবে গ্রহণযোগ্য। **নথিভুক্ত, আবার ভাবার trigger সহ।** |
| S3 lifecycle | ৯০ দিনের আইনি retention স্বয়ংক্রিয়ভাবে বাস্তবায়ন করে আর খরচ ~৮০% কমায় |
| Redis Multi-AZ | Session আর rate-limit-এর state; সিস্টেমকে একটা node হারানো টিকতে হবে |

ওই টেবিলটাই deliverable। Diagram দেখায় *কী*; টেবিল দেখায় *কেন* — আর "কেন"-টাই ভবিষ্যতের আপনি আর আপনার উত্তরসূরির লাগবে।

---

## ১৪.১১ সাধারণ ভুল

১. **একটা AZ-তে deployment** — একটা datacenter-এর সমস্যা আপনাকে নামিয়ে দেয়; সমাধানটা প্রায় বিনামূল্যে
২. **বিশ্লেষণ ছাড়া "সহনশীলতার জন্য" multi-region** — ২× খরচ, ৫× জটিলতা, সাধারণত অযৌক্তিক
৩. কোডে, CI-তে বা environment variable-এ **দীর্ঘস্থায়ী access key**
৪. **`"Action": "*", "Resource": "*"`** IAM policy — বেশিরভাগ breach-এর মূল কারণ
৫. **Public bucket** — এখনো সবচেয়ে সাধারণ ক্লাউড data ফাঁস
৬. **কোনো tagging নেই** — আপনি খরচ বরাদ্দ বা optimise করতে পারবেন না, আর পরিষ্কার করা অসম্ভব হয়ে যায়
৭. **ভিত্তি load-এ কোনো reservation নেই** — compute খরচের ৩০–৫০% টেবিলে ফেলে রাখা
৮. **Data transfer-এর খরচ উপেক্ষা করা** — cross-AZ বকবক আর NAT gateway compute ছাড়িয়ে যেতে পারে
৯. **চালানোর কেউ নেই এমন Kubernetes** — cluster-টাই product হয়ে যায়
১০. **Application স্তর দিয়ে বড় ফাইলের upload পাঠানো** — memory, bandwidth আর timeout-এর সমস্যা, যেগুলো একটা presigned URL সরিয়ে দেয়
১১. **কোনো storage lifecycle policy নেই** — চার বছরের পুরনো log-এর জন্য গরম দাম দেওয়া
১২. **Dev আর test পরিবেশ ২৪/৭ চলছে**
১৩. **Managed মানেই backup আর পরীক্ষিত — এটা ধরে নেওয়া** — প্রোভাইডার snapshot নেয়; **আপনাকে** restore test করতে হবে
১৪. **খরচকে finance-এর সমস্যা ভাবা** — architecture-ই বিল ঠিক করে

---

## ১৪.১২ আর্কিটেক্টের চেকলিস্ট

- [ ] ≥ ২টা AZ জুড়ে deploy করা (৩টা ভালো); multi-region সিদ্ধান্ত স্পষ্টভাবে নেওয়া আর যুক্তিযুক্ত
- [ ] সিদ্ধান্ত-গাছের বিপরীতে compute মডেল ইচ্ছাকৃতভাবে বাছা, টিমের সক্ষমতা বিবেচনা করে
- [ ] ভিত্তি ক্ষমতা reserve করা; batch/CI Spot-এ; non-prod বন্ধ নির্ধারিত
- [ ] সব resource-এ tag (env, team, service, cost-centre); tag-বিহীন resource স্বয়ংক্রিয়ভাবে চিহ্নিত
- [ ] Budget alert আর cost anomaly detection configure করা
- [ ] **Unit economics** হিসাব করা আর একটা dashboard-এ
- [ ] কোথাও কোনো দীর্ঘস্থায়ী credential নেই; workload identity / OIDC federation ব্যবহৃত
- [ ] IAM policy নির্দিষ্ট action আর resource-এ সীমিত; least privilege একটা analyser দিয়ে যাচাই করা
- [ ] Production নিজের account/subscription-এ
- [ ] মানুষের access SSO + MFA দিয়ে, কোনো shared account নেই
- [ ] Secret একটা secrets manager-এ, ঘোরানো, access-audit করা
- [ ] সব জায়গায় বিশ্রাম আর পথে encryption চালু; দরকার হলে customer-managed key
- [ ] Object storage-এ account স্তরে public access বন্ধ
- [ ] Storage lifecycle policy retention-এর নিয়ম স্বয়ংক্রিয়ভাবে বাস্তবায়ন করছে
- [ ] Backup স্বয়ংক্রিয় **আর একটা restore পরীক্ষিত ও সময় মাপা**
- [ ] Audit logging (CloudTrail/Activity Log) চালু, কেন্দ্রীভূত, আর immutable
- [ ] Infrastructure কোড হিসেবে সংজ্ঞায়িত; production-এ কোনো manual console পরিবর্তন নয় (অধ্যায় ১৬)
- [ ] গত ১২ মাসে একটা Well-Architected রিভিউ সম্পন্ন

---

## ১৪.১৩ নিজেকে যাচাই

১. সাতটা ক্লাউড service-শ্রেণির নাম বলুন আর আপনার জানা একটা ক্লাউডে প্রতি শ্রেণিতে একটা service।
২. AZ বনাম region ব্যাখ্যা করুন। Default নিয়ম কী, আর multi-region আসলে কখন যুক্তিসঙ্গত?
৩. Shared responsibility model বলুন। একটা public S3 bucket-এর দায় কার?
৪. Compute-এর সিদ্ধান্ত-গাছটা হাঁটুন। Serverless container কোথায় বসে আর এগুলো কেন কম ব্যবহৃত?
৫. আপনার কখন Kubernetes ব্যবহার করা *উচিত নয়*?
৬. Object বনাম block বনাম file storage — প্রতিটার একটা সঠিক ব্যবহার দিন।
৭. Presigned URL আর এটা যে তিনটা সমস্যা সমাধান করে ব্যাখ্যা করুন।
৮. "৯০ দিন পর ভিডিও মুছে ফেলুন"-এর জন্য একটা storage lifecycle policy লিখুন আর সাশ্রয়ের হিসাব দিন।
৯. Workload-এর কখনো দীর্ঘস্থায়ী access key রাখা উচিত নয় কেন? এর বদলে কী?
১০. ক্লাউড অপচয়ের পাঁচটা উল্লেখযোগ্য উৎস আর প্রতিটার সমাধান বলুন।
১১. Unit economics কী, আর মোট খরচের বদলে এটা কেন আর্কিটেক্টের সংখ্যা?
১২. "সহনশীলতার জন্য" multi-cloud-এর বিরুদ্ধে সৎ যুক্তিটা দিন।
১৩. ছয়টা Well-Architected স্তম্ভের নাম আর প্রতিটা থেকে একটা চর্চা বলুন।
১৪. আপনার RDS instance failover করল। আপনার application কী অনুভব করে, আর তাকে কী সামলাতে হবে?

---

## ১৪.১৪ মূল কথাগুলো

- **সাতটা শ্রেণি, ২০০টা service নয়।** নতুন যা কিছু আসে তাকে একটাতে শ্রেণিবদ্ধ করুন।
- **সবসময় Multi-AZ; multi-region শুধু একটা খরচ-হিসাব করা, লিখিত কারণে**
- **Shared responsibility: ক্লাউড নিরাপদ, ক্লাউডের configuration প্রায়ই নয়।** প্রায় প্রতিটা breach গ্রাহকের দিকে।
- Platform engineer ছাড়া টিমের জন্য **serverless container-ই কম ব্যবহৃত সেরা জায়গা**
- **ভিত্তি reserve করুন, batch Spot-এ, non-prod বন্ধ নির্ধারণ করুন** — সাধারণত এক সপ্তাহের কাজে ৪০%+ সাশ্রয়
- **Presigned URL**: কখনো আপনার application স্তর দিয়ে বড় ফাইল পাঠাবেন না
- **Storage lifecycle policy** আইনি retention বাস্তবায়ন করে *আর* খরচ ৮০% কমায়
- **কোনো দীর্ঘস্থায়ী credential নয়।** সব জায়গায় workload identity আর OIDC federation।
- **Unit economics — প্রতি transaction-এ খরচ — আর্কিটেক্টের সংখ্যা**
- **Managed service নিজের interface-এর পেছনে লুকান**; lock-in ইচ্ছাকৃতভাবে মেনে নিন, আর জানুন বেরোতে কত খরচ হবে
- **Managed backup মানে পরীক্ষিত backup নয়।** Restore-এর মহড়া করুন।

---

**পরবর্তী:** [অধ্যায় ১৫ — Container ও Kubernetes](15-containers-and-kubernetes.md)

**ইংরেজি সংস্করণ:** [Chapter 14](../14-cloud-architecture.md) · **[সূচিপত্র](README.md)**
