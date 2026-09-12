# অধ্যায় ১৩ — Networking 🟢

> Application ডেভেলপাররা প্রায়ই এখানেই সবচেয়ে দুর্বল, আর এর মূল্য তাঁদের দিতে হয়।
> "App ধীর"-এর অর্ধেক আর "আমার মেশিনে তো চলে"-র বেশিরভাগই networking-এর সমস্যা।
>
> আপনাকে network engineer হতে হবে না। আপনাকে জানতে হবে browser আর আপনার কোডের মাঝে কী ঘটে, আর **প্রতিটা ধাপে কী fail করতে পারে**।

---

## ১৩.১ একটা request-এর যাত্রা

এই শৃঙ্খলটা মুখস্থ করুন। এই অধ্যায়ের সবচেয়ে কাজের diagram এটাই, কারণ প্রতিটা performance আর availability সমস্যা এর কোথাও না কোথাও বাস করে।

```
  ১. ব্যবহারকারী লেখেন https://app.example.com
        │
  ২. DNS RESOLUTION           browser cache → OS cache → resolver → root → TLD → authoritative
        │                     (০–১০০ ms; cached হলে ০ হতে পারে)
  ৩. TCP HANDSHAKE            SYN → SYN/ACK → ACK              (১ round trip)
        │
  ৪. TLS HANDSHAKE            ClientHello → ... → Finished     (১–২ round trip)
        │
  ৫. CDN EDGE                 cache hit? → ফেরত। miss → এগিয়ে যান
        │
  ৬. LOAD BALANCER            একটা সুস্থ backend বাছুন
        │
  ৭. REVERSE PROXY / INGRESS  host/path দিয়ে route, TLS terminate
        │
  ৮. API GATEWAY              auth, rate limit, route
        │
  ৯. SERVICE                  অবশেষে আপনার কোড চলে
        │
 ১০. DATABASE / CACHE         আর তার নিজের connection, pool, query
        │
 ১১. RESPONSE                 পুরো শৃঙ্খল বেয়ে ফেরত
```

**প্রতিটা তীরই এমন একটা জায়গা যেখানে জিনিস fail করে, latency যোগ হয়, বা ভুল configure হয়।** কেউ যখন বলে "সাইট ধীর", আপনার প্রথম প্রশ্ন হওয়া উচিত *"এই এগারোটা ধাপের কোনটা?"* — আর উত্তরটা আসে tracing থেকে (অধ্যায় ১৮), অনুমান থেকে নয়।

---

## ১৩.২ IP, subnet আর CIDR 🟢

### IPv4

৩২ bit, চারটা octet-এ লেখা: `192.168.1.100`। প্রায় ৪৩০ কোটি ঠিকানা — শেষ হয়ে গেছে, আর এই কারণেই NAT আর IPv6 আছে।

### CIDR notation — এটা সাবলীলভাবে পড়ুন

`10.0.0.0/16` মানে: প্রথম **১৬ bit** হলো network, বাকি ১৬ bit host চিহ্নিত করে।

| CIDR | Subnet mask | ব্যবহারযোগ্য host | সাধারণ ব্যবহার |
|------|-------------|--------------|-------------|
| `/8` | 255.0.0.0 | ১,৬৭,৭৭,২১৪ | একটা পুরো private পরিসর |
| `/16` | 255.255.0.0 | ৬৫,৫৩৪ | **একটা VPC** |
| `/20` | 255.255.240.0 | ৪,০৯৪ | একটা বড় subnet |
| `/24` | 255.255.255.0 | ২৫৪ | **একটা প্রচলিত subnet** |
| `/28` | 255.255.255.240 | ১৪ | একটা ছোট service subnet |
| `/32` | 255.255.255.255 | ১ | **একটা একক host** (firewall-এর নিয়মে অনবরত ব্যবহৃত) |

**দ্রুত মাথার হিসাব:** ব্যবহারযোগ্য host = 2^(৩২ − prefix) − ২। (Network আর broadcast ঠিকানার জন্য মাইনাস ২; ক্লাউড প্রোভাইডাররা আরও কয়েকটা রাখে — AWS প্রতি subnet-এ ৫টা রাখে।)

### Private ঠিকানার পরিসর (RFC 1918) — এগুলো মুখস্থ করুন

```
10.0.0.0/8         10.0.0.0    – 10.255.255.255     (১.৬৭ কোটি ঠিকানা)
172.16.0.0/12      172.16.0.0  – 172.31.255.255     (১০ লাখ ঠিকানা)
192.168.0.0/16     192.168.0.0 – 192.168.255.255    (৬৫ হাজার ঠিকানা)
```

এগুলো কখনোই public ইন্টারনেটে route হয় না। এগুলোও জানার মতো: `127.0.0.0/8` (loopback), `169.254.0.0/16` (link-local — AWS-এর `169.254.169.254` metadata endpoint সহ, যেটা অধ্যায় ১৭-র SSRF আক্রমণে গুরুত্বপূর্ণ)।

### একটা VPC design করা — একটা ব্যবহারিক বিন্যাস

```
VPC: 10.0.0.0/16                                    (৬৫,৫৩৬টা ঠিকানা)

  Availability Zone A            Availability Zone B
  ├── 10.0.1.0/24  public        ├── 10.0.2.0/24  public      ← ALB, NAT gateway
  ├── 10.0.11.0/24 private app   ├── 10.0.12.0/24 private app ← আপনার service
  └── 10.0.21.0/24 private data  └── 10.0.22.0/24 private data← database

  Public subnet  = একটা Internet Gateway-তে route আছে
  Private subnet = ইন্টারনেট থেকে কোনো inbound নেই; outbound NAT দিয়ে
```

> **মূল নিরাপত্তা নীতি: database থাকে একটা private subnet-এ, ইন্টারনেট থেকে কোনো route ছাড়াই। কখনোই ব্যতিক্রম নয়।** Application server-ও একটা private subnet-এ বসে; শুধু load balancer public। VPN বা bastion ছাড়া আপনি যদি আপনার ল্যাপটপ থেকে আপনার database-এ পৌঁছাতে পারেন, তাহলে সেটা একটা আবিষ্কার।

**বানানোর আগে আপনার CIDR পরিসর পরিকল্পনা করুন।** VPC-র মধ্যে (বা একটা on-prem নেটওয়ার্কের সাথে) উপরিপাতিত পরিসর পরে VPC peering আর VPN অসম্ভব করে দেয়, আর একটা চলমান নেটওয়ার্ক নতুন করে নম্বর দেওয়া সত্যিই যন্ত্রণাদায়ক। উদারভাবে রাখুন — প্রতি VPC-তে `/16`, প্রতি subnet-এ `/24`।

### IPv6

১২৮ bit: `2001:0db8:85a3::8a2e:0370:7334`। বালির প্রতিটা কণার জন্য যথেষ্ট ঠিকানা। কোনো NAT লাগে না।

**আজকের ব্যবহারিক প্রভাব:** mobile নেটওয়ার্ক ক্রমশ IPv6-only হচ্ছে, তাই public-মুখী service-এর এটা সাপোর্ট করা উচিত (সাধারণত আপনার load balancer বা CDN দিয়ে বিনামূল্যে)। ভেতরে বেশিরভাগ ক্লাউড এখনো IPv4-কেন্দ্রিক। **জানুন যে IPv6 ঠিকানা আপনার log আর rate limiter-এ আসতে পারে** — একটা পূর্ণ IPv6 ঠিকানায় key করা rate limiter অকেজো (একজন ব্যবহারকারীর কোটি কোটি আছে); `/64` prefix-এ key করুন।

### NAT

Network Address Translation অনেক private ঠিকানাকে একটা public ঠিকানা ভাগ করতে দেয়।

```
10.0.11.5:51234 ──► NAT gateway ──► 54.23.11.9:51234 ──► ইন্টারনেট
                    (উৎস নতুন করে লেখে, mapping মনে রাখে)
```

**আপনার জন্য এর মানে:**
- **Outbound কাজ করে, inbound করে না।** একটা private instance একটা API call করতে পারে; API সেটাকে ফিরতি call করতে পারে না।
- **অনেক ব্যবহারকারী একটা public IP ভাগ করেন।** একটা কর্পোরেট অফিস বা mobile carrier একটা ঠিকানার পেছনে হাজার হাজার ব্যবহারকারী হতে পারে — তাই **IP-ভিত্তিক rate limiting সবাইকে শাস্তি দেয়**। যেখানে পারেন ব্যবহারকারী/tenant-এর পরিচয় ব্যবহার করুন।
- ক্লাউডে **NAT gateway-তে টাকা লাগে**, প্রতি GB প্রক্রিয়াকৃত হিসেবে। একটা বাচাল service যেটা NAT gateway দিয়ে S3 থেকে টানে, সেটা একটা চমকে দেওয়া বিল তৈরি করে। ওই traffic NAT থেকে দূরে রাখতে **VPC endpoint / Private Link ব্যবহার করুন**।

---

## ১৩.৩ TCP আর UDP 🟢

| | **TCP** | **UDP** |
|---|---|---|
| Connection | হ্যাঁ — আগে handshake | না — শুধু পাঠান |
| নির্ভরযোগ্যতা | নিশ্চিত delivery, আবার পাঠায় | যথাসাধ্য; packet উধাও হতে পারে |
| ক্রম | নিশ্চিত | নেই |
| Congestion control | হ্যাঁ | না (আপনি বানান) |
| Overhead | ২০+ byte header, ACK, state | ৮ byte header, কোনো state নেই |
| Latency | বেশি (handshake, retransmit-এর অপেক্ষা) | কম |
| কীসের জন্য | HTTP, database, email, file transfer | DNS, ভিডিও/ভয়েস, গেমিং, metric, QUIC |

### TCP-র তিন-ধাপের handshake (প্রথম request কেন ধীর)

```
Client                          Server
  │──────── SYN ──────────────────►│
  │◄─────── SYN-ACK ───────────────│     কোনো data-র আগেই ১ পূর্ণ round trip
  │──────── ACK + data ───────────►│
```

একটা ৫০ ms-এর লিংকে আপনার request-এর একটা byte পাঠানোর আগেই ৫০ ms। **TLS যোগ করুন (আরও ১–২ round trip) আর আপনার server কিছু দেখার আগেই ১০০–১৫০ ms খরচ হয়ে গেল।**

> **এই কারণেই connection পুনর্ব্যবহার এত গুরুত্বপূর্ণ।** HTTP keep-alive, connection pool আর HTTP/2-র multiplexing-এর অস্তিত্বই handshake বারবার না দেওয়ার জন্য। একটা cross-region লিংকে প্রতি request-এ নতুন connection খোলা client প্রতিটা call-এ সহজেই ১০০ ms বেশি ধীর, যা লাগত না।

### যেসব ধারণা সত্যিকারের incident-এ আসে

| ধারণা | মানে কী | যে উপসর্গ দেখবেন |
|---------|---------------|--------------------------|
| **Slow start** | TCP সতর্কভাবে শুরু করে আর বাড়তে থাকে | প্রথম ~১৪ KB দ্রুত, তারপর গতি বাড়ে — ছোট response কখনো পূর্ণ গতিতে পৌঁছায় না |
| **Bandwidth-delay product** | Throughput ≈ window-এর আকার ÷ RTT | বিশাল bandwidth থাকলেও উচ্চ-latency লিংক ধীর। মহাদেশের মধ্যে একটা বড় ফাইল পাঠাতে window tuning বা সমান্তরাল stream লাগে। |
| **Nagle's algorithm** | ছোট write গুলো একটা packet-এ buffer করে | ছোট বাচাল message-এ ~৪০ ms পর্যন্ত latency যোগ করে। Real-time protocol `TCP_NODELAY` বসায়। |
| **TIME_WAIT** | বন্ধ socket ~৬০ সেকেন্ড ঝুলে থাকে | দ্রুত-বদলানো client স্থানীয় port শেষ করে ফেলে; উপসর্গ হলো "cannot assign requested address"। সমাধান: connection pooling। |
| **Head-of-line blocking** | একটা হারানো packet ওই connection-এ তার পেছনের সবকিছু আটকে দেয় | HTTP/2 এটা stream স্তরে সমাধান করে কিন্তু TCP স্তরে নয়; **QUIC-এর উপর HTTP/3 এটা ঠিকভাবে সমাধান করে** |

### Port

```
০–১০২৩       সুপরিচিত     (২২ SSH, ৫৩ DNS, ৮০ HTTP, ৪৪৩ HTTPS, ৫৪৩২ Postgres, ৬৩৭৯ Redis)
১০২৪–৪৯১৫১   নিবন্ধিত     (৮০৮০, ৩০০০, ৯০৯২ Kafka, ২৭০১৭ Mongo)
৪৯১৫২–৬৫৫৩৫  Ephemeral   (প্রতিটা বাইরের connection-এর client দিক)
```

**Ephemeral port-এর সীমা একটা সত্যিকারের ক্ষমতার ছাদ:** প্রতি উৎস IP-তে, প্রতি গন্তব্যে ~২৮,০০০ ব্যবহারযোগ্য port। একটা backend-এ ৩০,০০০ concurrent বাইরের connection করা একটা service শেষ হয়ে যাবে। Connection pooling-ই সমাধান।

---

## ১৩.৪ DNS 🟢

DNS নামকে ঠিকানায় পরিণত করে। এটা আবার একটা load balancer, একটা failover কৌশল, আর — ভুল configure হলে — আশ্চর্যরকম অনেক outage-এর কারণ।

### Resolution-এর শৃঙ্খল

```
app.example.com?
  ১. Browser cache          (সেকেন্ড–মিনিট)
  ২. OS cache               (TTL মানে, বেশিরভাগ সময়)
  ৩. Recursive resolver     (ISP / 8.8.8.8 / 1.1.1.1) — TTL অনুযায়ী cache করে
  ৪. Root server            → ".com server-দের জিজ্ঞেস করো"
  ৫. TLD server (.com)      → "ns1.example.com-কে জিজ্ঞেস করো"
  ৬. Authoritative server   → "93.184.216.34"
```

### যে record-ধরনগুলো আপনাকে জানতেই হবে

| ধরন | উদ্দেশ্য | উদাহরণ |
|------|---------|---------|
| **A** | নাম → IPv4 | `app.example.com → 93.184.216.34` |
| **AAAA** | নাম → IPv6 | |
| **CNAME** | আরেকটা নামের alias | `www → app.example.com` (zone-এর শীর্ষে থাকতে পারে না) |
| **ALIAS/ANAME** | CNAME-এর মতো, শীর্ষেও কাজ করে | প্রোভাইডার-নির্দিষ্ট (Route 53-র "Alias", Cloudflare-এর "CNAME flattening") |
| **MX** | Mail server | |
| **TXT** | যথেচ্ছ টেক্সট | SPF, DKIM, DMARC, domain যাচাই |
| **NS** | একটা zone অর্পণ করে | |
| **SRV** | Service + port | কিছু service-discovery সিস্টেম ব্যবহার করে |
| **CAA** | কোন CA certificate দিতে পারে | একটা সস্তা, মূল্যবান নিরাপত্তা নিয়ন্ত্রণ |

### TTL — যে setting ঠিক করে আপনি কত দ্রুত failover করতে পারবেন

```
TTL = 300      → পরিবর্তন ~৫ মিনিটে ছড়ায়, বেশি DNS query
TTL = 86400    → পরিবর্তনে একদিন পর্যন্ত লাগে, কম query
```

> **Migration-এর নিয়ম:** একটা পরিকল্পিত cutover-এর **অন্তত ২৪–৪৮ ঘণ্টা আগে** TTL ৬০ সেকেন্ডে নামান (যাতে পুরনো লম্বা TTL সব জায়গায় শেষ হয়ে যায়), migration করুন, তারপর আবার বাড়ান। যে টিম এটা ভুলে যায় তারা আবিষ্কার করে যে একটা "৫ মিনিটের" DNS পরিবর্তনে কিছু ব্যবহারকারীর জন্য একদিন লাগে।

**এটাও জানুন:** কিছু client (বিশেষত পুরনো JVM) TTL যাই হোক **DNS চিরকাল cache করে**। কিছু resolver খুব ছোট TTL উপেক্ষা করে। **DNS একটা ইঙ্গিত, নিশ্চয়তা নয়** — আর এই কারণেই শুধু DNS একটা খারাপ failover কৌশল।

### DNS-ভিত্তিক traffic ব্যবস্থাপনা

| Policy | আচরণ | কীসের জন্য |
|--------|-----------|---------|
| **Simple** | একটা record | মৌলিক |
| **Weighted** | ৯০% → A, ১০% → B | Canary release, ধাপে ধাপে migration |
| **Latency-ভিত্তিক** | নিকটতম সুস্থ region | বৈশ্বিক performance |
| **Geolocation** | ব্যবহারকারীর দেশ অনুযায়ী | **Data residency আর compliance** |
| **Failover** | Primary, health check সহ | DR (অধ্যায় ১৯) |
| **Multivalue** | কয়েকটা সুস্থ IP | গরিবের load balancing |

**Anycast** ভালো বৈশ্বিক কৌশল: একটা IP ঠিকানা অনেক জায়গা থেকে ঘোষণা করা হয়, আর BGP প্রতিটা ব্যবহারকারীকে নিকটতমটায় পাঠায়। Cloudflare, Google DNS আর আধুনিক CDN এভাবেই কাজ করে — failover routing স্তরে, সেকেন্ডে, কোনো DNS caching-এর সমস্যা ছাড়াই।

### যে DNS ব্যর্থতাগুলোর দেখা পাবেন

১. **মেয়াদোত্তীর্ণ domain** — সবচেয়ে লজ্জাজনক outage-শ্রেণি, আর এটা এখনো বড় কোম্পানিগুলোর হয়
২. **অনুপস্থিত CAA record** certificate নবায়ন আটকে দেয়
৩. **শীর্ষে CNAME** — অবৈধ; ALIAS/ANAME ব্যবহার করুন
৪. **একটা negative cache (NXDOMAIN) SOA-র ন্যূনতম TTL ধরে আটকে আছে** — আপনি record বানিয়েছেন, কিন্তু resolver এখনো বলছে এটা নেই
৫. **Split-horizon-এর বিভ্রান্তি** — ভেতরের আর বাইরের DNS আলাদা উত্তর দিচ্ছে, আর caller-এর জন্য শুধু একটাই সঠিক
৬. **Container-এর ভেতরে DNS resolution** — একটা ক্লাসিক Kubernetes latency সমস্যা (`ndots:5`-এর কারণে সঠিকটার আগে পাঁচটা ব্যর্থ lookup)। উপসর্গ: প্রতিটা বাইরের call-এ রহস্যময় বাড়তি ২০–১০০ ms।

---

## ১৩.৫ TLS/HTTPS 🟢

### TLS যা দেয়

১. **গোপনীয়তা** — পথে encrypted
২. **অখণ্ডতা** — কারসাজি ধরা পড়ে
৩. **Authentication** — আপনি আসল server-এর সাথেই কথা বলছেন (তার certificate দিয়ে)

খেয়াল করুন এটা যা **দেয় না**: server বিশ্বাসযোগ্য কিনা সে বিষয়ে এটা কিছুই বলে না, শুধু বলে সে তার certificate যা দাবি করে সে তাই।

### Handshake (TLS 1.3)

```
Client                                     Server
  │── ClientHello (+ key share) ─────────────►│
  │◄─ ServerHello, certificate, Finished ─────│     একটা round trip
  │── Finished, application data ────────────►│
```

TLS 1.2-তে দুটো round trip লাগত; **TLS 1.3-তে একটা লাগে**, আর ফিরে আসা দর্শকদের জন্য 0-RTT resumption সাপোর্ট করে। এটা একটা সত্যিকারের, মাপা latency-জয় — **TLS 1.3 ব্যবহার করুন, 1.0/1.1 পুরোপুরি বন্ধ করুন।**

### Certificate

```
Root CA (OS/browser-এর trust store-এ)
   └── Intermediate CA
          └── আপনার certificate (app.example.com)
```

**১ নম্বর বাস্তব ভুল: intermediate certificate পরিবেশন না করা।** এটা আপনার browser-এ কাজ করে (যেটা হয়তো intermediate-টা cache করে রেখেছে) আর curl-এ, mobile-এ, আর server-থেকে-server call-এ fail করে। শুধু Chrome নয়, সবসময় `openssl s_client -connect host:443 -showcerts` বা SSL Labs দিয়ে test করুন।

| ধরন | যা ঢাকে | নোট |
|------|--------|-------|
| **DV** (Domain Validated) | Domain-এর নিয়ন্ত্রণ | বিনামূল্যে (Let's Encrypt), সেকেন্ডে ইস্যু — **এটাই ব্যবহার করুন** |
| **OV / EV** | সংগঠনের পরিচয় | Browser আর বিশেষভাবে দেখায় না; বেশিরভাগটাই বিপণন |
| **Wildcard** | `*.example.com` | একটা cert, অনেক subdomain; হারানোর জন্য একটা key |
| **SAN/multi-domain** | কয়েকটা স্পষ্ট নাম | সবচেয়ে নমনীয় |

### Certificate-এর মেয়াদ শেষ — যে outage সবারই হয়

**মেয়াদোত্তীর্ণ certificate শিল্পের সবচেয়ে সাধারণ স্ব-আরোপিত outage গুলোর একটা।**

- [ ] **নবায়ন automate করুন** (cert-manager, ACME, বা আপনার ক্লাউড প্রোভাইডারের managed certificate)
- [ ] **৩০, ১৪ আর ৭ দিন বাকি থাকতে alert দিন** — *প্রতিটা* certificate-এ, ভেতরেরগুলো সহ
- [ ] **প্রতিটা certificate-এর তালিকা রাখুন**, load balancer-এরগুলো, ভেতরের service-এরগুলো, client cert আর তৃতীয় পক্ষের integration সহ
- [ ] মনে রাখুন **ভেতরের mTLS cert-ও মেয়াদ শেষ করে**, আর প্রায়ই সেগুলোর কোনো monitoring-ই থাকে না

### Termination-এর pattern

```
১. প্রান্তে TERMINATE (সবচেয়ে প্রচলিত)
   Client ──TLS──► LB ──plaintext──► Service
   ✅ সহজ, LB পরিদর্শন আর route করতে পারে     ❌ ভেতরের traffic unencrypted

২. TERMINATE আর আবার ENCRYPT
   Client ──TLS──► LB ──TLS──► Service
   ✅ সব জায়গায় encrypted, LB তবু route করে  ❌ বেশি CPU, বেশি cert সামলাতে হয়

৩. PASSTHROUGH
   Client ────────TLS────────► Service
   ✅ সত্যিকারের শুরু-থেকে-শেষ      ❌ LB অন্ধ (শুধু L4); কোনো path routing নেই

৪. mTLS (দুই পক্ষই certificate দেখায়)
   Client ◄──TLS + client cert──► Service
   ✅ শক্তিশালী service পরিচয়      ❌ Scale-এ certificate-এর জীবনচক্র — একটা service mesh ব্যবহার করুন
```

> একটা zero-trust মডেলে ভেতরের service-থেকে-service traffic-এর জন্য **একটা service mesh-এর স্বয়ংক্রিয়ভাবে দেওয়া স্বল্পস্থায়ী certificate সহ mTLS**-ই আধুনিক উত্তর (অধ্যায় ১৫/১৭)। ভেতরের certificate হাতে সামলাবেন না।

**প্রান্তে বসানোর মতো security header (অধ্যায় ১৭ পুরোপুরি ঢাকে):**

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
Content-Security-Policy: default-src 'self'; ...
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

---

## ১৩.৬ HTTP-র সংস্করণ 🟢

| | **HTTP/1.1** | **HTTP/2** | **HTTP/3** |
|---|---|---|---|
| Transport | TCP | TCP | **UDP-র উপর QUIC** |
| Concurrency | প্রতি connection-এ একবারে একটা request (browser ৬টা খোলে) | এক connection-এ **multiplexed stream** | Multiplexed, স্বাধীন stream |
| Head-of-line blocking | Request স্তরে | HTTP স্তরে ঠিক, **TCP স্তরে থেকে যায়** | **পুরোপুরি সমাধান** |
| Header | সাধারণ টেক্সট, প্রতিটা request-এ পুনরাবৃত্ত | **HPACK compression** | QPACK compression |
| Server push | না | হ্যাঁ (বাস্তবে বাতিল) | না |
| Connection setup | TCP + TLS (২–৩ RTT) | TCP + TLS (২–৩ RTT) | **১ RTT, বা resume-এ 0-RTT** |
| Packet হারানো সামলায় | খারাপভাবে | খারাপভাবে (TCP HOL) | **ভালোভাবে** |
| Connection migration | না | না | **হ্যাঁ** — Wi-Fi → mobile বদলেও টেকে |

### বাস্তবে এর মানে

**HTTP/1.1-এর যে কৌশলগুলো এখন মুছে ফেলা উচিত:**
- Domain sharding (asset গুলো `cdn1`, `cdn2`-তে ভাগ করা) — HTTP/2-তে সক্রিয়ভাবে *ক্ষতিকর*
- Sprite sheet আর ফাইল জোড়া লাগানো — বেশিরভাগটাই অপ্রয়োজনীয়
- Request বাঁচাতে asset inline করা — সাধারণত এর দাম নেই

**HTTP/2-র ফাঁদ:**
- একটা connection, অনেক stream → একটা load balancer একটা connection দেখে আর সবটা একটা backend-এ পাঠাতে পারে। **gRPC/HTTP2-র এমন একটা L7-সচেতন load balancer লাগে যা প্রতি request-এ ভারসাম্য রাখে**, প্রতি connection-এ নয়। এটা একটা ক্লাসিক "একটা pod ১০০% CPU-তে কেন?" bug।
- Lossy নেটওয়ার্কে (mobile) TCP-র head-of-line blocking এখনো কামড়ায়

**Mobile-এ HTTP/3-ই আসল জয়:** connection migration মানে একজন ব্যবহারকারী ক্যাফে থেকে বেরিয়ে গেলে তাঁর session আটকে না গিয়ে টিকে থাকে। আপনার CDN-এ এটা চালু করুন — সাধারণত এটা একটা toggle।

### Keep-alive আর connection pooling

```python
# ভুল — প্রতিটা call-এ একটা নতুন TCP + TLS handshake
for item in items:
    requests.get(f"https://api.example.com/items/{item}")   # প্রতিবার ~১০০ ms নষ্ট

# সঠিক — connection পুনর্ব্যবহার করুন
with httpx.Client(
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=2.0, read=10.0),
    http2=True,
) as client:
    for item in items:
        client.get(f"https://api.example.com/items/{item}")
```

> **.NET-এ: `IHttpClientFactory` ব্যবহার করুন, কখনো একটা লুপে `new HttpClient()` নয়** (socket শেষ হয়ে যায়) আর কখনো চিরকালের জন্য একটা static `HttpClient`-ও নয় (এটা DNS cache করে আর failover মিস করে)। Factory দুটোই সমাধান করে।

---

## ১৩.৭ Load balancer, proxy আর gateway 🟢

চারটা শব্দ যেগুলো মানুষ একে অপরের বদলে ব্যবহার করে, আর করা উচিত নয়:

| Component | যার সামনে বসে | উদ্দেশ্য |
|-----------|-----------------|---------|
| **Forward proxy** | **Client** | Client এটার মাধ্যমে request করে — কর্পোরেট egress নিয়ন্ত্রণ, filtering, caching, অজ্ঞাতনামা থাকা |
| **Reverse proxy** | **Server** | Client ভাবে এটাই server — TLS, caching, compression, routing |
| **Load balancer** | Server | Backend জুড়ে বিলি করে (একটা বিশেষায়িত reverse proxy) |
| **API gateway** | Server | একটা reverse proxy সাথে API-র বিষয়: auth, rate limit, transform, metering |

```
FORWARD PROXY                          REVERSE PROXY
Client ──► Proxy ──► ইন্টারনেট          ইন্টারনেট ──► Proxy ──► Server
(proxy CLIENT-এর হয়ে কাজ করে)          (proxy SERVER-এর হয়ে কাজ করে)
```

**Egress proxy architecture-গতভাবে গুরুত্বপূর্ণ:** নিয়ন্ত্রিত পরিবেশে সব বাইরের traffic পরিদর্শন আর allowlisting-এর জন্য একটা forward proxy দিয়ে যায়। আপনার service যদি একটা ভেন্ডর API call করে, তাহলে তার proxy configuration লাগতে পারে — আর এটা ভুলে যাওয়া একটা ক্লাসিক "dev-এ চলে, production-এ fail করে" সমস্যা।

(L4 বনাম L7, algorithm আর health check অধ্যায় ০৪ §৪.৬-এ আছে।)

### CDN — আরেকবার, নেটওয়ার্কের দৃষ্টিকোণ থেকে

একটা CDN হলো একটা বিশ্বব্যাপী বিতরণ করা reverse proxy। Caching (অধ্যায় ১১)-এর বাইরেও এটা দেয়:

- **প্রান্তে TLS termination** — handshake ২০০ ms দূরে না হয়ে ২০ ms দূরে হয়, যেটা cache-অযোগ্য বিষয়বস্তুর জন্যও একটা বড় latency-জয়
- আপনার origin-এর দিকে **দীর্ঘস্থায়ী, optimised connection**
- **DDoS শোষণ** — তাঁদের ক্ষমতা terabit-এ মাপা হয়
- প্রান্তে **WAF**
- **Origin shielding** — একটা নির্দিষ্ট edge আপনার origin থেকে আনে, তাই একটা বৈশ্বিক cache miss ২০০টা একসাথে origin request হয়ে যায় না

> **একটা পুরোপুরি গতিশীল, cache-অযোগ্য API-র জন্যও সামনে একটা CDN বসানো সাধারণত সার্থক** — শুধু TLS termination, connection পুনর্ব্যবহার আর DDoS সুরক্ষার জন্যই। এটা মানুষকে অবাক করে।

---

## ১৩.৮ Firewall, security group আর network policy 🟢

### নেটওয়ার্ক নিয়ন্ত্রণের স্তর

```
১. NETWORK ACL / firewall     stateless, subnet স্তরে, allow আর deny দুই নিয়মই
২. SECURITY GROUP             stateful, instance স্তরে, শুধু allow
৩. HOST FIREWALL              iptables/nftables, মেশিনে
৪. KUBERNETES NETWORK POLICY  cluster-এর ভেতরে pod-থেকে-pod নিয়ম
৫. SERVICE MESH POLICY        পরিচয়-ভিত্তিক (mTLS), L7-সচেতন
৬. WAF                        application স্তর — SQLi, XSS, bot-এর নিয়ম
```

**Stateful বনাম stateless গুরুত্বপূর্ণ:** একটা security group stateful, তাই inbound ৪৪৩ অনুমতি দিলে response-এর বেরোনো স্বয়ংক্রিয়ভাবে অনুমোদিত। একটা network ACL stateless — আপনাকে ephemeral port-এ ফিরতি traffic স্পষ্টভাবে অনুমতি দিতে হবে। এটা ভুলে যাওয়া একটা ক্লাসিক আধা-দিনের debugging।

### যে নিয়মগুলো গুরুত্বপূর্ণ

```
✅ DEFAULT DENY। যা লাগে শুধু সেটাই স্পষ্টভাবে allow করুন।
✅ Platform অনুমতি দিলে IP পরিসর নয়, security group reference করুন
   (app-sg → db-sg ৫৪৩২-এ, 10.0.11.0/24 → ৫৪৩২ নয়)
✅ Database: শুধু app security group থেকে inbound। কখনো 0.0.0.0/0 নয়। কখনোই না।
✅ Admin access (SSH/RDP): একটা bastion, SSM Session Manager, বা একটা VPN দিয়ে — কখনো ইন্টারনেটে খোলা নয়
✅ EGRESS-ও সীমাবদ্ধ করুন — একটা আপসকৃত container-এর যে কোনো কিছু call করতে পারা উচিত নয়
✅ পরিবেশগুলো আলাদা VPC/account-এ ভাগ করুন, শুধু আলাদা subnet-এ নয়
```

> **সবচেয়ে সাধারণ ক্লাউড breach:** "সাময়িকভাবে, debug করার জন্য" `0.0.0.0/0`-তে উন্মুক্ত একটা database বা object store। এটার জন্য স্বয়ংক্রিয়ভাবে audit করুন; এটাকে একটা fitness function বানান (অধ্যায় ০০)।

### Kubernetes-এর NetworkPolicy

Kubernetes-এ default-এ **প্রতিটা pod প্রতিটা namespace-এর প্রতিটা pod-এর সাথে কথা বলতে পারে।** এটা প্রায় কখনোই আপনার কাম্য নয়।

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-api-only
  namespace: production
spec:
  podSelector:
    matchLabels: { app: postgres }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels: { app: verification-api }
      ports:
        - protocol: TCP
          port: 5432
```

প্রতি namespace-এ একটা default-deny policy দিয়ে শুরু করুন, তারপর নির্দিষ্ট প্রবাহ allow করুন। খেয়াল রাখুন: NetworkPolicy-র জন্য এমন একটা CNI লাগে যা এটা সাপোর্ট করে (Calico, Cilium) — কিছু CNI-তে policy নীরবে উপেক্ষিত হয়, যেটা কোনো policy না থাকার চেয়েও খারাপ।

---

## ১৩.৯ VPN আর private সংযোগ 🟡

| বিকল্প | এটা কী | কীসের জন্য |
|--------|-----------|---------|
| **Site-to-site VPN** | ইন্টারনেটের উপর দুটো নেটওয়ার্কের মাঝে encrypted tunnel | On-prem-কে ক্লাউডের সাথে যুক্ত করা; সস্তা, তবে ইন্টারনেট-মানের latency |
| **Client VPN** | আলাদা ব্যবহারকারীরা যুক্ত হন | কর্মীদের private সম্পদে প্রবেশ |
| **Direct Connect / ExpressRoute** | একটা নিবেদিত শারীরিক সার্কিট | সামঞ্জস্যপূর্ণ latency, উচ্চ bandwidth, বড় data স্থানান্তর; ব্যয়বহুল, বসাতে সপ্তাহ লাগে |
| **VPC Peering** | দুটো VPC-র মাঝে সরাসরি private routing | সহজ; **transitive নয়** (A–B আর B–C মানে A–C নয়); CIDR উপরিপাতিত হওয়া চলবে না |
| **Transit Gateway** | অনেক VPC আর VPN যোগ করা একটা hub | ~৫টা VPC-র উপরে scale-যোগ্য উত্তর |
| **PrivateLink / Private Endpoint** ⭐ | একটা service আপনার VPC-র *ভেতরে* একটা private ঠিকানা হিসেবে উন্মুক্ত | **একটা ভেন্ডর বা একটা managed service-এর traffic কখনো ইন্টারনেট ছোঁয় না** |

> **PrivateLink-ই মনে রাখার মতোটা।** এটা আপনাকে একটা SaaS/managed service ব্যবহার করতে (বা নিজেরটা একজন customer-কে দিতে) দেয় শুধু private ঠিকানায়, কোনো ইন্টারনেট route ছাড়া, কোনো NAT-এর খরচ ছাড়া, আর অনেক সহজ compliance-এর গল্প নিয়ে। সংবেদনশীল data সামলানো একটা B2B product-এর জন্য PrivateLink দেওয়া একটা সত্যিকারের enterprise বিক্রয়-সুবিধা।

---

## ১৩.১০ Latency, bandwidth আর আলোর গতি 🟢

**Latency পদার্থবিজ্ঞান দিয়ে সীমাবদ্ধ।** Fibre-এ আলো চলে ~২,০০,০০০ কিমি/সেকেন্ড, আর আসল পথগুলো সরলরেখা নয়।

| পথ | একমুখী (তাত্ত্বিক) | বাস্তব RTT |
|-------|----------------------|---------------|
| একই rack | — | ০.১ ms |
| একই datacenter | — | ০.৫ ms |
| একই region (cross-AZ) | — | ১–২ ms |
| ঢাকা ↔ সিঙ্গাপুর | ~১৫ ms | ৪০–৬০ ms |
| লন্ডন ↔ নিউ ইয়র্ক | ~২৮ ms | ৭০–৯০ ms |
| লন্ডন ↔ সিডনি | ~৮৫ ms | ২৫০–৩০০ ms |

> **আপনি optimise করে আলোর গতি পেরোতে পারবেন না।** আপনার ব্যবহারকারীরা সিডনিতে আর server ফ্রাঙ্কফুর্টে হলে প্রতিটা round trip-এ ~২৮০ ms লাগে। একমাত্র সমাধান: কম round trip, নয়তো ব্যবহারকারীদের কাছাকাছি server।

### Round trip কমানোই সবচেয়ে লাভজনক optimisation

```
খারাপ: একটা screen render করতে ৮টা ক্রমিক API call
       ৮ × ২৮০ ms = ২.২৪ সেকেন্ড নিখাদ নেটওয়ার্ক

ভালো: ১টা একত্রিত call (একটা BFF, অধ্যায় ০৮)
      ১ × ২৮০ ms = ২৮০ ms
```

| কৌশল | প্রভাব |
|-----------|--------|
| **CDN / edge** | বিষয়বস্তু ব্যবহারকারীর কাছে আনুন — সবচেয়ে বড় একক জয় |
| **Batch / একত্রিত endpoint** | কম round trip |
| **Connection পুনর্ব্যবহার** | Handshake এড়ান |
| **HTTP/2 বা /3** | এক connection-এ সমান্তরাল stream |
| **Compression (Brotli/gzip)** | কম byte, slow-start-এ কম round trip |
| **Prefetch / preconnect** | দরকারের আগেই connection গরম করুন |
| **Regional deployment** | শুধু বিষয়বস্তু নয়, *compute*-ও কাছে আনুন |

### Bandwidth বনাম latency — যে পার্থক্যটা মানুষ গুলিয়ে ফেলে

**Bandwidth** হলো পাইপ কত চওড়া। **Latency** হলো পাইপ কত লম্বা।

Bandwidth যোগ করলে একটা ছোট request দ্রুত **হয় না**। একটা ১ KB-র API call ১০ Mbps-এ যত সময় নেয়, ১ Gbps-এও তত — এটা latency-নির্ভর। Bandwidth গুরুত্বপূর্ণ বড় স্থানান্তরে (ভিডিও, file upload, bulk data)।

**ক্লাউডের egress খরচ একটা সত্যিকারের architecture-এর constraint:** সাধারণত ক্লাউড ছেড়ে বেরোতে ~$০.০৫–০.০৯/GB, আর cross-region/cross-AZ traffic-এও চার্জ হয়। একটা বাচাল cross-AZ service mesh compute-এর চেয়ে বেশি খরচ করাতে পারে। **যেখানে নিরাপদে পারেন সেখানে traffic একটা AZ-র ভেতরে রাখুন**, NAT-এর বদলে VPC endpoint ব্যবহার করুন, আর উচ্চ-volume যা কিছুর সামনে একটা CDN বসান।

---

## ১৩.১১ Network সমস্যা debug করা 🟢

যে ক্রমে টুল গুলোর দিকে হাত বাড়ানো উচিত:

```bash
# ১. নামটা কি resolve হয়, আর কীসে?
dig app.example.com +short
dig app.example.com @1.1.1.1          # স্থানীয় resolver এড়িয়ে যান
dig -x 93.184.216.34                  # উল্টো lookup

# ২. আমি কি host-এ আদৌ পৌঁছাতে পারি, আর packet কতদূর যায়?
ping app.example.com
mtr app.example.com                   # traceroute + ping একসাথে — এখানে সেরা টুল
traceroute app.example.com

# ৩. Port কি খোলা?
nc -zv app.example.com 443
telnet app.example.com 443

# ৪. TLS-এর অবস্থা কী?
openssl s_client -connect app.example.com:443 -servername app.example.com -showcerts
echo | openssl s_client -connect app.example.com:443 2>/dev/null | openssl x509 -noout -dates

# ৫. পুরো HTTP timing-এর বিশ্লেষণ কী?  ← এটাই মুখস্থ করার মতো
curl -w "@curl-format.txt" -o /dev/null -s https://app.example.com

# ৬. এই মেশিনের আসলে কী কী connection আছে?
ss -tanp | head -50
ss -s                                  # সারাংশ: কতগুলো TIME_WAIT-এ?

# ৭. তারে কী আছে?
tcpdump -i any -n port 5432 -w capture.pcap
```

```
# curl-format.txt — আজই এটা আপনার dotfiles-এ রাখুন
     time_namelookup:  %{time_namelookup}s\n
        time_connect:  %{time_connect}s\n
     time_appconnect:  %{time_appconnect}s\n      (TLS handshake সম্পন্ন)
    time_pretransfer:  %{time_pretransfer}s\n
       time_redirect:  %{time_redirect}s\n
  time_starttransfer:  %{time_starttransfer}s\n   (server-এর ভাবার সময়)
                       ----------\n
          time_total:  %{time_total}s\n
```

**এটা পড়া:**

| বড় মান | মানে |
|-------------|-------|
| `time_namelookup` | DNS ধীর — খারাপ resolver, বা container-এর DNS config |
| `time_connect − time_namelookup` | Network RTT / TCP handshake — দূরত্ব বা packet হারানো |
| `time_appconnect − time_connect` | TLS handshake — পুরনো TLS সংস্করণ, বড় cert-শৃঙ্খল, বা একটা OCSP আটকে যাওয়া |
| `time_starttransfer − time_pretransfer` | **আপনার server ধীর।** এটাই application-এর ভাবার সময়। |
| `time_total − time_starttransfer` | Response body স্থানান্তর — payload খুব বড়, বা bandwidth-সীমিত |

> **এই একটামাত্র command আপনাকে বলে দেয় §১৩.১-এর এগারোটা ধাপের কোনটা সমস্যা।** এটা দশ সেকেন্ডে "সাইট ধীর"-কে একটা নির্দিষ্ট, কার্যকর আবিষ্কারে পরিণত করে।

---

## ১৩.১২ সাধারণ ভুল

১. **Network call-এ কোনো timeout নেই** — অধ্যায় ০৫ দেখুন; এটাই cascading ব্যর্থতার সবচেয়ে সাধারণ কারণ
২. **প্রতি request-এ একটা নতুন HTTP client/connection বানানো** — handshake-এর খরচ আর port শেষ হওয়া
৩. **ইন্টারনেট থেকে পৌঁছানো যায় এমন database** — ক্লাসিক breach
৪. **মেয়াদোত্তীর্ণ TLS certificate** — পুরোপুরি ঠেকানো যায়, তবু অনবরত হয়
৫. **অনুপস্থিত intermediate certificate** — আপনার browser-এ চলে, বাকি সব জায়গায় fail করে
৬. **Migration-এর আগে DNS TTL না কমানো** — "৫ মিনিটের" পরিবর্তনে একদিন লাগে
৭. **IP-ভিত্তিক rate limiting** — একটা NAT বা mobile carrier-এর পেছনের সবাইকে শাস্তি দেয়
৮. **বাচাল cross-region call** — ৮টা ক্রমিক call × ২৮০ ms
৯. **একটা L4 load balancer সহ HTTP/2** — সব stream একটা backend-এ আটকে যায়, একটা pod গলে যায়
১০. **উপরিপাতিত CIDR পরিসর** — যেদিন peer বা VPN করতে যান সেদিন আবিষ্কৃত
১১. **Kubernetes-এ default-allow network policy** — প্রতিটা pod প্রতিটা pod আর প্রতিটা database-এ পৌঁছাতে পারে
১২. **NAT gateway-র data চার্জ** — একটা চমকে দেওয়া খরচের লাইন; VPC endpoint ব্যবহার করুন
১৩. **ভেতরের নেটওয়ার্ক নিরাপদ ধরে নেওয়া** — ৪ নম্বর ভ্রান্তি (অধ্যায় ০৫); mTLS ব্যবহার করুন
১৪. **Container-এ `ndots:5`-এর DNS latency** — প্রতিটা call-এ রহস্যময় বাড়তি কয়েক দশ মিলিসেকেন্ড

---

## ১৩.১৩ আর্কিটেক্টের চেকলিস্ট

- [ ] VPC-র CIDR বাড়ার জায়গা রেখে পরিকল্পনা করা; peer বা on-prem-এর সাথে কোনো উপরিপাতন নেই
- [ ] তিনটা স্তর: public (শুধু LB), private app, private data
- [ ] Database আর cache ইন্টারনেট থেকে অগম্য; admin access bastion/SSM/VPN দিয়ে
- [ ] Default-deny security group আর network policy; egress-ও সীমাবদ্ধ
- [ ] TLS 1.3, HSTS, শক্তিশালী cipher; 1.0/1.1 বন্ধ
- [ ] **প্রতিটা** certificate তালিকাভুক্ত, স্বয়ংক্রিয়ভাবে নবায়ন, আর ৩০/১৪/৭ দিনে alert
- [ ] পূর্ণ শৃঙ্খল (intermediate সহ) পরিবেশিত আর একটা browser-এর বাইরে যাচাই করা
- [ ] প্রান্তে HTTP/2 বা /3 চালু; gRPC/HTTP2-র জন্য L7 load balancing
- [ ] সব জায়গায় connection pooling আর keep-alive; কোনো per-request client নেই
- [ ] DNS-এর TTL উপযুক্ত; পরিকল্পিত migration-এর আগে কমানো
- [ ] CAA record বসানো; domain-এর স্বয়ংক্রিয় নবায়ন চালু আর কারও মালিকানায়
- [ ] Public traffic-এর সামনে CDN, বেশিরভাগ গতিশীল হলেও
- [ ] প্রতি ব্যবহারকারীর কাজে round trip গোনা আর কমানো; দরকারে একত্রীকরণ
- [ ] Cross-AZ / cross-region / NAT-এর data খরচ বোঝা; VPC endpoint ব্যবহৃত
- [ ] ভেন্ডর আর customer সংযোগের জন্য PrivateLink বিবেচিত
- [ ] `curl -w`-র timing বিশ্লেষণ on-call runbook-এর একটা প্রচলিত অংশ

---

## ১৩.১৪ নিজেকে যাচাই

১. Browser থেকে database পর্যন্ত একটা request-এর এগারোটা ধাপ আঁকুন। প্রতিটা কোথায় latency যোগ করে?
২. `10.0.0.0/16` — কতগুলো ঠিকানা? `/24` আর `/28`-এ কত?
৩. Database কেন একটা private subnet-এ থাকতে হবে, আর "private" আসলে কী মানে?
৪. একটা server-এ প্রথম request দ্বিতীয়টার চেয়ে কেন ধীর? পরিমাণ দিন।
৫. IP-ভিত্তিক rate limiting কেন বৈধ ব্যবহারকারীদের ক্ষতি করে? সমাধান কী?
৬. একটা migration-এর আগে DNS TTL-এর নিয়মটা ব্যাখ্যা করুন, আর এটা কেন ২৪–৪৮ ঘণ্টা।
৭. একটা L4 load balancer-এর পেছনে HTTP/2 কেন বেঠিক আচরণ করে?
৮. HTTP/3 এমন কোন সমস্যা সমাধান করে যা HTTP/2 পারে না?
৯. Forward proxy বনাম reverse proxy বনাম load balancer বনাম API gateway — প্রতিটার এক লাইন।
১০. Stateful বনাম stateless firewall নিয়ম — পার্থক্যটা কোন bug ঘটায়?
১১. PrivateLink কী আর একটা B2B product-এর জন্য এটা কেন গুরুত্বপূর্ণ?
১২. আপনার API-তে ২ সেকেন্ড লাগে। `curl -w` `time_starttransfer` ১.৯ সেকেন্ড দেখায়। আপনি কী জানলেন, আর কী বাদ দিলেন?
১৩. একটা ২৮০ ms-এর সিডনি-থেকে-ফ্রাঙ্কফুর্ট round trip আপনি কেন "optimise" করে সরাতে পারবেন না? আপনার একমাত্র দুটো বিকল্প কী?
১৪. ক্লাউডের নেটওয়ার্ক খরচ আশ্চর্যরকম বেশি করে এমন চারটা জিনিসের নাম বলুন।

---

## ১৩.১৫ মূল কথাগুলো

- Browser থেকে database পর্যন্ত **এগারোটা ধাপ জানুন**; প্রতিটা latency সমস্যা এর একটাতে বাস করে
- **Data-র জন্য private subnet, শুধু load balancer public।** Default deny, দুই দিকেই।
- **Connection পুনর্ব্যবহার সবচেয়ে বড় বিনামূল্যের জয়গুলোর একটা** — region জুড়ে handshake-এ ১০০+ ms লাগে
- **Certificate-এর মেয়াদ শেষ একটা শীর্ষ স্ব-আরোপিত outage।** প্রতিটা certificate automate করুন আর তাতে alert দিন।
- **DNS একটা ইঙ্গিত, নিশ্চয়তা নয়** — migration-এর আগে TTL কমান, আর বৈশ্বিক failover-এ Anycast-কে প্রাধান্য দিন
- **TLS 1.3 + HTTP/2 বা /3 + একটা CDN** হলো আধুনিক ভিত্তি, গতিশীল API-র জন্যও
- **Latency পদার্থবিজ্ঞান।** Round trip কমান বা compute সরান; তৃতীয় কোনো বিকল্প নেই।
- **Bandwidth ≠ latency।** একটা বড় পাইপ একটা ছোট request দ্রুত করে না।
- **একটা timing ফরম্যাট সহ `curl -w` দশ সেকেন্ডে "এটা ধীর"-কে একটা নির্দিষ্ট আবিষ্কারে পরিণত করে**
- **ভেতরের নেটওয়ার্ক নিরাপদ নয়** — এটা encrypt করুন, সীমাবদ্ধ করুন, আর egress-ও সীমাবদ্ধ করুন

---

**পরবর্তী:** [অধ্যায় ১৪ — Cloud Architecture](14-cloud-architecture.md)

**ইংরেজি সংস্করণ:** [Chapter 13](../13-networking.md) · **[সূচিপত্র](README.md)**
