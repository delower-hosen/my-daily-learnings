# অধ্যায় ০৬ — Messaging ও Event-Driven Architecture 🟢

> একটা message broker হলো distributed system-এর শক শোষক।
> এটা "এই service-কে call করো আর আশা করো সেটা চালু আছে"-কে "এই অভিপ্রায়টা লিখে রাখো আর নিশ্চিত করো যে কাজটা হবে"-তে পরিণত করে।

আপনার RabbitMQ-র অভিজ্ঞতা আছে, তাই এই অধ্যায় সেইসব pattern-এ গভীরে যায় যেগুলো একটা কাজ-করা prototype-কে একটা production সিস্টেম থেকে আলাদা করে: Outbox, Inbox, dead letter, poison message, ordering আর delivery semantics।

---

## ৬.১ Messaging কেন আদৌ?

### Synchronous call-এর সমস্যা

```
   Order Service ──HTTP──► Email Service
```

কী কী ভুল হতে পারে:

১. Email service **বন্ধ** → order fail করল। কিন্তু order তো বৈধ ছিল! একটা marketing ইমেইল কেন একটা বিক্রি আটকাবে?
২. Email service **ধীর** (৩ সেকেন্ড) → আপনার order API এখন একটা ৩ সেকেন্ডের API
৩. Email service **অতিরিক্ত চাপে** → আপনার retry সেটা আরও খারাপ করে
৪. আপনি SMS, push, analytics, একটা webhook যোগ করলেন → এখন order service ৫টা service call করে, সবগুলোর জন্য অপেক্ষা করে, আর সবগুলোর কথা জানে

### Messaging কী বদলে দেয়

```
   Order Service ──► [ Broker ] ──► Email Service
                          ├───────► SMS Service
                          ├───────► Analytics
                          └───────► Webhook Dispatcher
```

| সুবিধা | মানে কী |
|---------|---------------|
| **Temporal decoupling** | Producer publish করার সময় consumer-এর চালু থাকার দরকার নেই |
| **Load levelling** | ১০ গুণ traffic-এর ঢেউ একটা লম্বা queue হয়ে যায়, crash নয় |
| **Fan-out** | Producer-এ হাত না দিয়েই ষষ্ঠ একটা consumer যোগ করুন |
| **বিনামূল্যে retry** | ব্যর্থতা? Message queue-তেই থাকে। |
| **Back-pressure** | Queue-র গভীরতা সমস্যার একটা দৃশ্যমান, মাপা যায় এমন সংকেত |
| **স্বাধীন scaling** | ধীরটার জন্য ২০টা consumer, দ্রুতটার জন্য ২টা |

### এর খরচ

| খরচ | বাস্তবতা |
|------|---------|
| **Eventual consistency** | ইমেইল ২০০ ms (বা ২ মিনিট) পরে পৌঁছায় |
| **কোনো return value নেই** | আপনি "ফলাফলের জন্য await" করতে পারবেন না — design বদলাতে হবে |
| **Duplicate** | At-least-once মানে একই message দুইবার সামলানো |
| **Ordering** | Message ক্রমের বাইরে পৌঁছাতে পারে |
| **Operational পরিসর** | একটা broker একটা গুরুত্বপূর্ণ stateful সিস্টেম, যেটা চালাতে, patch করতে আর monitor করতে হয় |
| **Debugging** | প্রবাহটা আর একটা stack trace-এ নেই |
| **Dual-write সমস্যা** | §৬.৮ দেখুন — এটাই বড়টা |

> **আঙুলের নিয়ম: caller-এর যদি এগোনোর জন্য উত্তরটা লাগে, তাহলে request/response call ব্যবহার করুন। Caller-এর যদি শুধু কাজটা শেষ পর্যন্ত হওয়া দরকার হয়, তাহলে messaging ব্যবহার করুন।**

---

## ৬.২ Messaging-এর মডেল

### ১. Point-to-point (queue) — এক message, এক consumer

```
Producer ──► [ Queue ] ──► Consumer A
                      └──► Consumer B      প্রতিটা message শুধু একজনই পায়
```

**কাজ বিলি করার** জন্য ব্যবহার করুন: "এই ভিডিও process করো", "এই ইমেইল পাঠাও", "এই report বানাও"। এটা **Competing Consumers** pattern — দ্রুত করতে আরও consumer যোগ করুন।

### ২. Publish/Subscribe — এক message, প্রতিটা subscriber

```
                       ┌──► Subscriber A (একটা কপি পায়)
Publisher ──► [ Topic ]├──► Subscriber B (একটা কপি পায়)
                       └──► Subscriber C (একটা কপি পায়)
```

**সত্য প্রচার করার** জন্য ব্যবহার করুন: "একটা order দেওয়া হয়েছে", "একজন ব্যবহারকারী verify হয়েছেন"। প্রতিটা আগ্রহী পক্ষ স্বাধীনভাবে সাড়া দেয়।

### ৩. Messaging-এর উপর Request/Response

```
Client ──► [ request queue ] ──► Server
Client ◄── [ reply queue   ] ◄── Server     (correlation ID দিয়ে মেলানো হয়)
```

সম্ভব, কিন্তু নিজেকে জিজ্ঞেস করুন কেন। একটা synchronous উত্তর লাগলে HTTP/gRPC সাধারণত সহজ। একটা দীর্ঘ operation-এ queue-র buffering আর retry চাইলে এটা বৈধ।

### ৪. Competing Consumers

```
              ┌──► Worker 1  (msg 4 process করছে)
[ Queue ] ────┼──► Worker 2  (msg 5 process করছে)
              └──► Worker 3  (msg 6 process করছে)
```

Async কাজের মূল scaling pattern। মূল setting গুলো:

- **Prefetch / QoS** — একজন consumer কতগুলো unacked message ধরে রাখতে পারে। খুব বেশি: একজন consumer queue-টা দখল করে আর বাকিরা বসে থাকে। খুব কম: round-trip latency প্রাধান্য পায়। ধীর কাজে ১–১০ দিয়ে শুরু করুন, দ্রুত কাজে ১০০+।
- **কাজের পরে ack করুন, কখনো আগে নয়** — consumer crash করলে broker আবার পাঠায়
- Worker গুলোকে **idempotent** হতে হবে (অধ্যায় ০৫)

---

## ৬.৩ Event notification বনাম Event-carried state transfer বনাম Command

এই পার্থক্যটা আপনার পুরো architecture-এর আকার দেয়। এটা স্পষ্ট করুন।

| | **Command** | **Event Notification** | **Event-Carried State Transfer** |
|---|---|---|---|
| নাম | আদেশসূচক: `SendEmail` | অতীত কাল: `OrderPlaced` | অতীত কাল: `OrderPlaced` |
| অভিপ্রায় | "এটা করো" | "এটা ঘটেছে" | "এটা ঘটেছে, এই যে data" |
| Consumer | ঠিক একজন | অনেক, অজানা | অনেক, অজানা |
| প্রত্যাখ্যান করা যায়? | হ্যাঁ | না — এটা ইতিমধ্যে ঘটে গেছে | না |
| Payload | কাজ করার জন্য যা যা লাগে | শুধু ID | পুরো প্রাসঙ্গিক state |
| Coupling | Producer জানে consumer আছে | কম | রানটাইমে কম, schema-তে বেশি |

```json
// COMMAND — একটা নির্দিষ্ট handler-এর কাছে একটা অনুরোধ
{ "type": "SendVerificationEmail", "to": "a@b.com", "template": "kyc_passed",
  "vars": { "name": "Delower", "link": "https://..." } }

// EVENT NOTIFICATION — পাতলা
{ "type": "VerificationPassed", "sessionId": "ses_881", "occurredAt": "..." }
// consumer-কে এখন ফিরে call করতে হবে: GET /sessions/ses_881  ← বাড়তি load + coupling

// EVENT-CARRIED STATE TRANSFER — মোটা
{ "type": "VerificationPassed", "sessionId": "ses_881", "occurredAt": "...",
  "customer": { "id": "cus_42", "email": "a@b.com", "tier": "enterprise" },
  "result": { "score": 0.94, "method": "active_challenge", "attempts": 1 } }
// consumer সম্পূর্ণ স্বাধীন — producer বন্ধ থাকলেও কাজ করে
```

### কোনটা বাছবেন

- **Command** যখন ঠিক একজনই সঠিক handler আর আপনি কাজ পরিচালনা করছেন
- **Event notification** যখন payload বিশাল হতো, বা যখন consumer-দের এমনিতেও তাজা data লাগে, বা যখন data সংবেদনশীল আর সেটা প্রচার করা উচিত নয়
- **Event-carried state transfer** — service-এর মধ্যেকার event-এর জন্য **default হিসেবে** — স্বাধীনতাই তো EDA-র পুরো কথা

> **ফাঁদটা খেয়াল করুন:** মোটা event একটা *schema* contract তৈরি করে। আপনি যে প্রতিটা field publish করেন, সেটা এমন একটা field যার উপর কেউ নির্ভর করে। Consumer-দের যা লাগে, ইচ্ছাকৃতভাবে সেটাই publish করুন — আপনার ভেতরের entity-র একটা JSON dump নয়। (অধ্যায় ০৩: ভেতরের domain event ≠ প্রকাশিত integration event।)

---

## ৬.৪ Delivery semantics 🟢

### At-most-once

```
Broker: message পাঠায় → সাথে সাথে মুছে ফেলে
Consumer: process করার আগে crash করে → MESSAGE চিরতরে হারাল
```

কীসের জন্য: metric, sensor-এর পাঠ, log-এর লাইন — উচ্চ-volume-এর data যেখানে একটা হারানো অপ্রাসঙ্গিক।

### At-least-once ⭐ (যে default আপনি প্রায় সবসময় ব্যবহার করবেন)

```
Broker: পাঠায় → ack-এর অপেক্ষা করে → ack পেলে মোছে
Consumer: process করে → ack করে
Ack কখনো না এলে (crash, নেটওয়ার্ক) → broker আবার পাঠায়
→ message দুইবার process হতে পারে
```

কীসের জন্য: যা কিছু গুরুত্বপূর্ণ। **Idempotent consumer**-এর সাথে মেলান (অধ্যায় ০৫)।

### Exactly-once — সৎ সংস্করণ

```
একটা DELIVERY-র নিশ্চয়তা হিসেবে অসম্ভব (Two Generals, অধ্যায় ০৫)।
একটা PROCESSING-এর নিশ্চয়তা হিসেবে অর্জনযোগ্য:
    at-least-once delivery
  + idempotent consumer (dedup table / upsert / স্বাভাবিক idempotency)
  = exactly-once processing
```

Kafka-র "exactly-once semantics" সত্যিকারের কিন্তু সংকীর্ণ: এটা তখনই কাজ করে যখন আপনার consume→process→produce লুপ *Kafka-র ভেতরেই* থাকে (transactional producer + read-committed consumer + একই transaction-এ commit করা offset)। যে মুহূর্তে আপনি একটা বাইরের database-এ লেখেন বা একটা বাইরের API call করেন, **আপনার আবার idempotency লাগবে।** এটা নিখুঁতভাবে জানুন — ইন্টারভিউতে আর ভেন্ডরের সাথে আলোচনায় এটা আসে।

```python
# সর্বজনীন pattern: কাজের সাথে একই transaction-এ dedup
async def handle(msg: Message) -> None:
    async with db.transaction():
        inserted = await db.fetch_val(
            """INSERT INTO processed_messages (message_id, handler, processed_at)
               VALUES ($1, $2, now())
               ON CONFLICT (message_id, handler) DO NOTHING
               RETURNING 1""",
            msg.id, "verification_handler")
        if inserted is None:
            metrics.increment("messages.duplicate")
            return                                     # আগেই process হয়েছে

        await do_the_business_work(msg)                # একই transaction
    # commit → dedup record আর কাজ দুটোই atomically বসে
```

---

## ৬.৫ Ordering 🟢

Messaging-এ ordering সবচেয়ে ভুল বোঝা বিষয়গুলোর একটা।

### তিনটা স্তর

| স্তর | মানে | খরচ |
|-------|---------|------|
| **Global ordering** | সব জায়গার সব message একটা মোট ক্রমে | একটামাত্র writer লাগে। Throughput মেরে ফেলে। কার্যত কখনোই এর দাম দেওয়ার মতো নয়। |
| **Partition ordering** | একটা partition/queue-র ভেতরে ক্রম নিশ্চিত | সস্তা — Kafka আপনাকে এটাই দেয় |
| **Per-key ordering** ⭐ | একই key-র (customer, order, session) জন্য ক্রম নিশ্চিত | সস্তা আর প্রায় সবসময়ই যথেষ্ট |

> **Design-এর অন্তর্দৃষ্টি: আপনার প্রায় কখনোই global ordering লাগে না। আপনার per-entity ordering লাগে।**
> Order #১২৩-এর event গুলো একে অপরের সাপেক্ষে সাজানো থাকতে হবে। এগুলো order #৪৫৬-এর সাথে মিশে যাচ্ছে কিনা তাতে কিছু আসে যায় না।

### Per-key ordering কীভাবে কাজ করে

```
Kafka:     partition = hash(key) % num_partitions
           customer_42-এর সব event → একই partition → কঠোরভাবে সাজানো
           একটা partition একটা group-এর একজন consumer পড়ে → কোনো পুনর্বিন্যাস নেই

RabbitMQ:  একটা consistent-hash exchange ব্যবহার করুন, বা প্রতি key-পরিসরে একটা queue,
           প্রতি queue-তে একজন consumer সহ (কঠোরতার জন্য prefetch=1)
```

### কী ordering ভাঙে (ফাঁদগুলো)

১. **একটা queue-তে একাধিক consumer** — তিনজন worker msg ১, ২, ৩ নেয় আর যে কোনো ক্রমে শেষ করে
২. **Retry** — msg ১ fail করে একটা retry queue-তে যায়; msg ২ সাথে সাথে সফল হয়। এখন msg ২ msg ১-এর আগে প্রয়োগ হলো।
৩. **Consumer-এর ভেতরে concurrency** — আপনি ক্রমে পড়েন, তারপর প্রতিটায় `Task.Run` করেন
৪. **Kafka-তে partition বাড়ানো** — `hash(key) % N` বদলায়, তাই একটা key নতুন partition-এ যেতে পারে, আর তার পুরনো ও নতুন event আর একে অপরের সাপেক্ষে সাজানো থাকে না। **Partition-এর সংখ্যা আগেভাগে পরিকল্পনা করুন; বাড়ানো বিনামূল্যে নয়।**

### ভালো উত্তর: এমনভাবে design করুন যাতে ক্রমে কিছু আসে যায় না

Ordering-এর নিশ্চয়তা ব্যয়বহুল আর ভঙ্গুর। বরং consumer-কে **ক্রম-অসংবেদনশীল** করুন:

```python
# VERSION GUARD — আমাদের কাছে যা আছে তার চেয়ে পুরনো কিছু উপেক্ষা করুন
async def handle_customer_updated(event: CustomerUpdated) -> None:
    await db.execute(
        """UPDATE customer_view
           SET name = $2, email = $3, version = $4
           WHERE id = $1 AND version < $4""",     # ক্রমের বাইরের event কিছুই করে না
        event.customer_id, event.name, event.email, event.version)
```

```python
# COMMUTATIVE OPERATION — গঠনগতভাবেই ক্রম-নিরপেক্ষ
# "count = 5 সেট করো"-র বদলে একটা CRDT counter-এ "১ যোগ করো" ব্যবহার করুন
```

```python
# STATE MACHINE GUARD — অবৈধ transition কেবল উপেক্ষা করা হয়
if order.status is OrderStatus.SHIPPED and event.type == "PaymentCaptured":
    return          # দেরিতে আসা একটা payment event একটা shipped order ফেরাতে পারে না
```

> **নিয়ম: কঠোর ordering-এর নিশ্চয়তার চেয়ে idempotent, ক্রম-অসংবেদনশীল consumer-কে প্রাধান্য দিন।** এটা সস্তা, এটা scale করে, আর এটা retry-তে টেকে।

---

## ৬.৬ Dead Letter Queue আর poison message 🟢

### Poison message-এর সমস্যা

```
Message M fail করল → broker আবার পাঠাল → fail → আবার পাঠাল → fail → ...
→ অসীম লুপ
→ এই একটা message সবার জন্য queue আটকে দেয়
→ আপনার CPU ১০০% আর কিছুই হচ্ছে না
```

কারণ: বিকৃত payload, consumer-এ একটা bug, reference করা একটা record মুছে যাওয়া, একটা schema পরিবর্তন।

### Dead Letter Queue (DLQ)

N বার ব্যর্থতার পর message-টা মানুষের পরিদর্শনের জন্য একটা আলাদা queue-তে সরান।

```
                    ┌──────────────┐
Producer ──────────►│  main.queue  │──► Consumer
                    └──────┬───────┘       │ ৫ বার fail
                           │               │
                    ┌──────▼───────┐ ◄─────┘
                    │   dlq.queue  │  ← গভীরতা > ০ হলে alert
                    └──────────────┘
```

```python
# RabbitMQ-র setup
channel.exchange_declare("verification.dlx", exchange_type="direct", durable=True)
channel.queue_declare("verification.dlq", durable=True)
channel.queue_bind("verification.dlq", "verification.dlx", routing_key="failed")

channel.queue_declare(
    "verification.process",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "verification.dlx",
        "x-dead-letter-routing-key": "failed",
        "x-message-ttl": 3_600_000,        # মূল queue-তে সর্বোচ্চ ১ ঘণ্টা আয়ু
        "x-max-length": 100_000,           # সীমাবদ্ধ! (backpressure, অধ্যায় ০৫)
        "x-overflow": "reject-publish",    # পুরনো ফেলার বদলে নতুন message প্রত্যাখ্যান
    },
)
```

### Backoff সহ retry queue (delay-queue কৌশল)

শুধু একটা DLQ খুব ভোঁতা — একটা ক্ষণস্থায়ী ৩ সেকেন্ডের ভেন্ডর outage-এ message মানুষের কাছে পাঠানো উচিত নয়। আপনি চান **ক্রমবর্ধমান দেরি সহ retry**, তারপর একটা DLQ।

```
main.queue ──fail──► retry.5s   ──(TTL শেষ)──► আবার main.queue-তে
           ──fail──► retry.30s  ──(TTL শেষ)──► আবার main.queue-তে
           ──fail──► retry.5m   ──(TTL শেষ)──► আবার main.queue-তে
           ──fail──► DLQ (মানুষ)
```

RabbitMQ-তে নিজস্ব delayed delivery নেই, তাই আপনি **TTL + dead-lettering** ব্যবহার করেন: একটা message ৩০ সেকেন্ডের TTL আর কোনো consumer ছাড়া `retry.30s`-এ বসে থাকে; TTL শেষ হলে RabbitMQ সেটাকে dead-letter করে *আবার মূল exchange-এ* পাঠায়। মার্জিত আর ব্যাপকভাবে ব্যবহৃত। (বিকল্পে, `rabbitmq_delayed_message_exchange` plugin।)

```python
RETRY_DELAYS_MS = [5_000, 30_000, 300_000, 1_800_000]   # ৫s, ৩০s, ৫m, ৩০m

for delay in RETRY_DELAYS_MS:
    channel.queue_declare(
        f"verification.retry.{delay}",
        durable=True,
        arguments={
            "x-message-ttl": delay,
            "x-dead-letter-exchange": "verification.exchange",   # আবার main-এ
            "x-dead-letter-routing-key": "process",
        },
    )

def on_failure(ch, method, props, body, attempt: int) -> None:
    if attempt >= len(RETRY_DELAYS_MS):
        ch.basic_publish("verification.dlx", "failed", body, properties=props)
        metrics.increment("messages.dead_lettered")
        ch.basic_ack(method.delivery_tag)
        return
    headers = dict(props.headers or {}, x_attempt=attempt + 1,
                   x_last_error=str(current_error)[:500])
    ch.basic_publish(
        "", f"verification.retry.{RETRY_DELAYS_MS[attempt]}", body,
        properties=pika.BasicProperties(headers=headers, delivery_mode=2))
    ch.basic_ack(method.delivery_tag)
```

### DLQ-র operational শৃঙ্খলা

যে DLQ-র দিকে কেউ তাকায় না, সেটা বাড়তি কয়েক ধাপ সহ একটা data হারানোর কৌশল।

- [ ] **DLQ-র গভীরতা > ০ হলে alert দিন।** সবসময়। এর মানে কিছু একটার জন্য একজন মানুষ লাগবে।
- [ ] Message-এ **ব্যর্থতার কারণ**, **stack trace**, **চেষ্টার সংখ্যা** আর **মূল header** গুলো জমা রাখুন
- [ ] একটা **replay টুল** বানান — ঠিক করার পর DLQ থেকে message গুলো মূল queue-তে ফেরত পাঠানোর জন্য একটা কমান্ড
- [ ] একটা **runbook** রাখুন: পরিদর্শন → শ্রেণিবিভাগ → কোড বা data ঠিক করুন → replay → যাচাই
- [ ] DLQ-তেও একটা **retention/আকারের সীমা বসান**, আর সেটায় পৌঁছানোর আগেই alert দিন

### Retryable আর non-retryable আলাদা করুন — সাথে সাথেই

```python
try:
    await process(msg)
    ack()
except (ValidationError, SchemaError, UnknownMessageType) as e:
    # কখনোই সফল হবে না। ৪টা retry নষ্ট করবেন না। সোজা DLQ-তে।
    dead_letter(msg, reason=f"permanent: {e}")
    ack()
except (TimeoutError, ConnectionError, ServiceUnavailable) as e:
    # ক্ষণস্থায়ী। Backoff সহ retry করুন।
    schedule_retry(msg, attempt, reason=str(e))
    ack()
except Exception as e:
    # অজানা — দুয়েকবার retry, তারপর DLQ, আর alert। একটা শ্রেণিবদ্ধ-না-করা
    # error নিজেই একটা আবিষ্কার: পরের sprint-এ এটা শ্রেণিবদ্ধ করুন।
    logger.exception("unclassified consumer error")
    schedule_retry(msg, attempt, reason=str(e))
    ack()
```

---

## ৬.৭ Dual-write সমস্যা ⭐⭐

**এটাই event-driven architecture-এর সবচেয়ে গুরুত্বপূর্ণ সমস্যা, আর বেশিরভাগ টিম এটা ভুল করে।**

```python
# দেখতে ঠিক আছে। কিন্তু ভাঙা।
async def place_order(order: Order) -> None:
    await db.save(order)                      # write ১: database
    await broker.publish(OrderPlaced(order))  # write ২: broker
```

**দুই লাইনের মাঝে process crash করলে কী হয়?**

- Order database-এ আছে
- কোনো event publish হয়নি
- Inventory কখনো reserve হয় না, customer-কে কখনো ইমেইল যায় না
- **নীরব, স্থায়ী অসঙ্গতি।** কোথাও কোনো error নেই।

ক্রম উল্টে দিন:

```python
await broker.publish(OrderPlaced(order))   # publish হলো
await db.save(order)                       # ← এখানে crash
# এখন: inventory reserve হয়েছে, ইমেইল গেছে, এমন একটা order-এর জন্য যেটার অস্তিত্বই নেই।
```

একটা transaction-এ মুড়ে দিন?

```python
async with db.transaction():
    await db.save(order)
    await broker.publish(event)     # broker DB-র transaction-এ নেই
    # broker-এর publish সফল হয়ে DB commit fail করলে event তো ইতিমধ্যেই চলে গেছে
```

> **আপনি দুটো আলাদা সিস্টেমে atomically লিখতে পারবেন না।** (2PC/XA ব্যবহার না করলে, যেটা আপনার করা উচিত নয় — অধ্যায় ০৫।)

একে বলে **dual-write সমস্যা**, আর এই কারণেই পরের pattern-টার অস্তিত্ব।

---

## ৬.৮ Outbox Pattern ⭐⭐⭐ 🟢

**এই অধ্যায়ের সবচেয়ে মূল্যবান pattern।**

**ধারণা:** event-টা আপনার business data-র **একই database transaction-এ** একটা table-এ লিখুন। একটা আলাদা process ওই table পড়ে আর broker-এ publish করে।

```
┌───────────────────────────────────────┐
│          একটাই ACID TRANSACTION       │
│                                       │
│   INSERT INTO orders  (...)           │
│   INSERT INTO outbox  (...)           │
│                                       │
│   COMMIT  ← দুটোই, নয়তো কোনোটাই না     │
└───────────────┬───────────────────────┘
                │
                │  (আলাদা process, পরে)
                ▼
        ┌───────────────┐
        │ Outbox Relay  │ poll করে বা WAL অনুসরণ করে
        └───────┬───────┘
                │ publish
                ▼
        ┌───────────────┐
        │    Broker     │  at-least-once → consumer-দের idempotent হতে হবে
        └───────────────┘
```

### Schema

```sql
CREATE TABLE outbox (
    id             BIGSERIAL PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,     -- 'Order'
    aggregate_id   TEXT        NOT NULL,     -- 'ord_8812'  → partition key হিসেবে ব্যবহার করুন
    event_type     TEXT        NOT NULL,     -- 'OrderPlaced'
    payload        JSONB       NOT NULL,
    headers        JSONB       NOT NULL DEFAULT '{}',   -- correlation id, tenant, schema version
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at   TIMESTAMPTZ                          -- NULL = এখনো publish হয়নি
);

-- Partial index: শুধু unpublished row, যাতে polling query চিরকাল দ্রুত থাকে
CREATE INDEX idx_outbox_unpublished
    ON outbox (id) WHERE published_at IS NULL;
```

### লেখা (business transaction)

```python
async def place_order(cmd: PlaceOrder) -> OrderId:
    async with db.transaction():                       # একটাই transaction
        order = Order.create(cmd.customer_id, cmd.items)
        await db.execute(
            "INSERT INTO orders (id, customer_id, total, status) VALUES ($1,$2,$3,$4)",
            order.id, order.customer_id, order.total, order.status)

        for event in order.pull_domain_events():
            await db.execute(
                """INSERT INTO outbox
                     (aggregate_type, aggregate_id, event_type, payload, headers)
                   VALUES ($1, $2, $3, $4, $5)""",
                "Order", str(order.id), type(event).__name__,
                json.dumps(event.to_dict()),
                json.dumps({"correlation_id": current_correlation_id(),
                            "schema_version": 1}))
    # COMMIT — order আর event এখন atomically consistent
    return order.id
```

### Publish — বিকল্প ক: polling relay (সহজ, সব জায়গায় চলে)

```python
async def relay_loop() -> None:
    while True:
        rows = await db.fetch(
            """SELECT id, aggregate_id, event_type, payload, headers
               FROM outbox
               WHERE published_at IS NULL
               ORDER BY id                       -- ক্রম বজায় রাখে
               LIMIT 100
               FOR UPDATE SKIP LOCKED""")        # একাধিক relay instance-এ নিরাপদ

        if not rows:
            await asyncio.sleep(0.2)
            continue

        for row in rows:
            await broker.publish(
                topic=f"orders.{row['event_type']}",
                key=row["aggregate_id"],          # per-key ordering
                value=row["payload"],
                headers={**row["headers"], "message_id": str(row["id"])},
            )
            await db.execute(
                "UPDATE outbox SET published_at = now() WHERE id = $1", row["id"])
```

**`FOR UPDATE SKIP LOCKED`-ই মূল খুঁটিনাটি** — এটা আপনাকে কয়েকটা relay instance চালাতে দেয়, যারা একই row নিয়ে মারামারি করে না।

**খেয়াল রাখুন:** publish করার পর কিন্তু `UPDATE`-এর আগে crash করলে message দুইবার publish হয়। সেটা ঠিক আছে — **at-least-once, আর consumer গুলো idempotent।** কখনো relay-কে exactly-once বানানোর চেষ্টা করবেন না; বরং consumer গুলোকে idempotent করুন।

### Publish — বিকল্প খ: Change Data Capture (scale-এ ভালো)

Poll করার বদলে database-এর write-ahead log অনুসরণ করুন।

```
Postgres WAL ──► Debezium ──► Kafka
```

- ✅ Database-এ কোনো polling-এর load নেই, এক সেকেন্ডের কম latency, কোনো row বাদ পড়ে না
- ✅ Transaction-এর ক্রম হুবহু বজায় রাখে
- ❌ চালানো আর monitor করার জন্য আরও infrastructure (Kafka Connect / Debezium)

**আঙুলের নিয়ম:** polling দিয়ে শুরু করুন (এটা ৬০ লাইনের কোড); polling-এর latency বা load সমস্যা হলে, অথবা আপনি যদি এমনিতেই Kafka চালান, তখন CDC-তে যান।

### গৃহস্থালি

```sql
-- ৭ দিনের বেশি পুরনো publish হওয়া row মুছুন (debug/replay-র জন্য একটা জানালা রাখুন)
DELETE FROM outbox
WHERE published_at IS NOT NULL AND published_at < now() - INTERVAL '7 days';
```

Alert দিন: **সবচেয়ে পুরনো unpublished row-র বয়সে** (~৬০ সেকেন্ড ছাড়ালে relay আটকে গেছে) আর **outbox table-এর আকারে**।

---

## ৬.৯ Inbox Pattern

Consumer-এর দিকের আয়না-প্রতিবিম্ব: at-least-once delivery সত্ত্বেও নিশ্চিত করুন যে একটা message **ঠিক একবারই** process হয়।

```python
async def handle(msg: Message) -> None:
    async with db.transaction():
        try:
            await db.execute(
                """INSERT INTO inbox (message_id, consumer, received_at)
                   VALUES ($1, $2, now())""",
                msg.id, "inventory_service")
        except UniqueViolation:
            metrics.increment("inbox.duplicate")
            return                                   # আগেই process হয়েছে — ack করে এগিয়ে যান

        await reserve_inventory(msg.payload)         # একই transaction
    # commit → dedup record আর business পরিবর্তন একসাথে বসে
```

```sql
CREATE TABLE inbox (
    message_id  TEXT NOT NULL,
    consumer    TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (message_id, consumer)
);
CREATE INDEX ON inbox (received_at);   -- পরিষ্কারের জন্য
```

**Outbox + Inbox একসাথে আপনাকে service জুড়ে শুরু থেকে শেষ পর্যন্ত exactly-once *processing* দেয়, যেটা পুরোপুরি at-least-once delivery আর সাধারণ database transaction-এর উপর তৈরি।** এটাই production-মানের উত্তর, আর এতে কোনো অদ্ভুত টেকনোলজি লাগে না।

---

## ৬.১০ Kafka দিয়ে transactional messaging 🟡

Kafka একটা transactional producer দেয়, যেটা atomically একাধিক partition-এ message লেখে **আর** consumer-এর offset commit করে।

```java
producer.initTransactions();
producer.beginTransaction();
producer.send(new ProducerRecord<>("orders", key, orderEvent));
producer.send(new ProducerRecord<>("audit",  key, auditEvent));
producer.sendOffsetsToTransaction(offsets, consumerGroupMetadata);  // send-এর সাথে atomic
producer.commitTransaction();
```

Consumer গুলো `isolation.level=read_committed` সেট করে বাতিল হওয়া message এড়ায়।

**আবারও সেই গুরুত্বপূর্ণ সীমাবদ্ধতা:** এটা **শুধু Kafka-র ভেতরেই** atomic। ওই block-এর ভেতরে একটা database write এর আওতায় পড়ে না। Consume→transform→produce pipeline-এর জন্য এটা সত্যিই exactly-once; কোনো বাইরের সিস্টেম ছোঁয়া যে কোনো কিছুর জন্য Outbox/Inbox ব্যবহার করুন।

---

## ৬.১১ RabbitMQ গভীরে 🟢

### মডেল: exchange, binding, queue

```
                    ┌──────────────┐
Producer ──────────►│   EXCHANGE   │
                    └──────┬───────┘
                    binding অনুযায়ী routing
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         [ Queue A ]  [ Queue B ]  [ Queue C ]
              │            │            │
          Consumer     Consumer     Consumer
```

Producer **কখনোই** একটা queue-তে publish করে না — সবসময় একটা exchange-এ। Exchange-এর ধরন routing ঠিক করে।

| Exchange-এর ধরন | Routing-এর নিয়ম | কীসের জন্য |
|---------------|-------------|---------|
| **Direct** | routing key == binding key (হুবহু) | লক্ষ্যভিত্তিক work queue, severity routing |
| **Topic** ⭐ | `*` (এক শব্দ) আর `#` (শূন্য বা তার বেশি) সহ pattern | **Event publish করা — সবচেয়ে কাজের** |
| **Fanout** | Key উপেক্ষা করে, সব bound queue-তে পাঠায় | নিখাদ broadcast |
| **Headers** | Header-এর মানে মেলায় | বিরল; routing যখন কয়েকটা বৈশিষ্ট্যের উপর নির্ভর করে তখন |

```python
# Topic exchange — মূল কর্মী
channel.exchange_declare("events", exchange_type="topic", durable=True)

# Routing key: <context>.<aggregate>.<event>
#   verification.session.passed
#   verification.session.failed
#   billing.invoice.created

channel.queue_bind("email.queue",     "events", "verification.session.passed")
channel.queue_bind("analytics.queue", "events", "verification.#")     # সবকিছু
channel.queue_bind("audit.queue",     "events", "#")                  # আক্ষরিক অর্থে সব
channel.queue_bind("alerts.queue",    "events", "*.*.failed")         # যে কোনো ব্যর্থতা
```

### Durability — তিনটা আলাদা setting, তিনটাই লাগে

```python
# ১. Queue broker-এর restart-এ টিকে থাকে
channel.queue_declare("work", durable=True)

# ২. MESSAGE broker-এর restart-এ টিকে থাকে
channel.basic_publish(
    exchange="", routing_key="work", body=payload,
    properties=pika.BasicProperties(delivery_mode=2))   # ২ = persistent

# ৩. কাজ শেষ হওয়ার পরেই consumer ack করে
channel.basic_consume("work", on_message, auto_ack=False)   # কখনো auto_ack=True নয়
```

> তিনটার একটাও বাদ দিলে restart-এ message হারাবেন। `auto_ack=True` হলো সবচেয়ে সাধারণ RabbitMQ ভুল — এটা *delivery*-তে ack করে, তাই process-এর মাঝপথে crash করলে message নীরবে হারায়।

### Publisher confirm — এটা বাদ দেবেন না

Confirm ছাড়া `basic_publish` সাথে সাথে ফেরত আসে আর broker সেটা পেল কিনা আপনার **কোনো ধারণাই** থাকে না।

```python
channel.confirm_delivery()
try:
    channel.basic_publish(exchange="events", routing_key="verification.session.passed",
                          body=payload,
                          properties=pika.BasicProperties(delivery_mode=2))
    # broker নিশ্চিত করার পরেই ফেরত আসে
except pika.exceptions.UnroutableError:
    # এমন একটা exchange-এ publish হয়েছে যার কোনো মিলে যাওয়া binding নেই → কোথাও যায়নি
    logger.error("unroutable message — check bindings")
```

`mandatory=True`-ও সেট করুন, যাতে কোনো message কোনো queue-তে route করা না গেলে আপনাকে জানানো হয়। নীরব unroutable message একটা ক্লাসিক "কিছুই হচ্ছে না কেন?" bug।

### Prefetch (QoS) — performance-এর ডায়াল

```python
channel.basic_qos(prefetch_count=10)
```

- **prefetch=1** — পুরোপুরি ন্যায্য বণ্টন, প্রতি round trip-এ সর্বোচ্চ latency। ধীর কাজে ব্যবহার করুন (video processing, প্রতিটায় ৪ সেকেন্ড)।
- **prefetch=100+** — উচ্চ throughput, কিন্তু একজন consumer একটা বড় batch নিয়ে নিতে পারে আর বাকিরা বসে থাকে। দ্রুত কাজে ব্যবহার করুন (< ১০ ms প্রতিটায়)।
- **আঙুলের নিয়ম:** `prefetch ≈ ceil(processing_time / round_trip_time)`, memory দিয়ে সীমাবদ্ধ।

### Quorum queue (নির্ভরযোগ্যতার আধুনিক default)

```python
channel.queue_declare("payments", durable=True,
                      arguments={"x-queue-type": "quorum"})
```

Quorum queue node গুলোর মধ্যে replication-এর জন্য Raft ব্যবহার করে। এগুলো পুরনো "mirrored queue" (এখন বাতিল) প্রতিস্থাপন করে আর যা কিছু হারানো আপনি সইতে পারবেন না তার জন্য সঠিক পছন্দ। Trade-off: বেশি disk I/O আর memory; খুব উচ্চ-throughput-এর ক্ষণস্থায়ী কাজের জন্য উপযুক্ত নয়।

### RabbitMQ বনাম Kafka — যে প্রশ্নটা আপনাকে করা হবে

| | **RabbitMQ** | **Kafka** |
|---|---|---|
| **মডেল** | স্মার্ট broker, বোকা consumer | বোকা broker, স্মার্ট consumer |
| **গ্রহণের পর** | Message মুছে যায় | নির্ধারিত সময় পর্যন্ত থাকে |
| **Replay** | না (আবার publish না করলে) | **হ্যাঁ — সংজ্ঞায়ক feature** |
| **Routing** | সমৃদ্ধ (topic, direct, header, প্রতি message) | সহজ (topic + key দিয়ে partition) |
| **প্রতি-message operation** | হ্যাঁ — একটা message ack/nack/reject, priority, TTL | না — consumer একটা offset track করে |
| **Ordering** | প্রতি queue-তে, একাধিক consumer-এ দুর্বল | **প্রতি partition-এ কঠোর** |
| **Throughput** | প্রতি node-এ ~হাজারে msg/s | **লাখে msg/s** |
| **Retry/DLQ** | **অন্তর্নির্মিত আর চমৎকার** | Manual (retry topic, DLQ topic) |
| **Consumer** | একটা queue-তে competing consumer | Consumer group, partition-বরাদ্দ |
| **কীসের জন্য সেরা** | **Task queue, RPC, জটিল routing, প্রতি-message retry** | **Event stream, log aggregation, stream processing, replay, খুব উচ্চ volume** |

> **এক বাক্যের উত্তর:** *"RabbitMQ হলো কাজ বিলি করার জন্য প্রতি-message নিয়ন্ত্রণ সহ একটা স্মার্ট message router; Kafka হলো উচ্চ-volume event stream-এর জন্য একটা টেকসই, replay করা যায় এমন, সাজানো log। প্রতি-message retry আর জটিল routing লাগলে RabbitMQ। Replay, উচ্চ throughput, বা একই ইতিহাস পড়া অনেক স্বাধীন consumer লাগলে Kafka।"*

**আপনি অবশ্যই দুটোই ব্যবহার করতে পারেন।** খুবই সাধারণ একটা architecture: event-এর মেরুদণ্ড আর analytics-এর জন্য Kafka, task queue আর job-এর জন্য RabbitMQ।

---

## ৬.১২ Schema evolution 🟢

Event একটা **contract**। একবার publish হলে কেউ না কেউ তার উপর নির্ভর করে। আর একটা stream-এ ২০২৩-এর একটা event ২০৩০-এও পড়া হতে পারে।

### Compatibility-র ধরন

| ধরন | মানে | নিয়ম |
|------|---------|------|
| **Backward** | নতুন consumer পুরনো event পড়তে পারে | Optional field যোগ করুন; কখনো একটা required field সরাবেন বা নাম বদলাবেন না |
| **Forward** | পুরনো consumer নতুন event পড়তে পারে | Consumer-দের **অজানা field উপেক্ষা করতে হবে** |
| **Full** | দুটোই | শুধু default সহ optional field যোগ করুন |

> **FULL compatibility লক্ষ্য রাখুন।** Producer আর consumer স্বাধীনভাবে deploy করার এটাই একমাত্র উপায়, আর decoupling-এর পুরো কথাটাই তো এটা।

### নিরাপদ পরিবর্তনের নিয়ম

```
✅ নিরাপদ
   - default সহ একটা OPTIONAL field যোগ করা
   - একটা নতুন event type যোগ করা
   - একটা মানের সেট বাড়ানো (একটা নতুন enum মান যোগ করা) — যদি consumer অজানা মান সামলায়
   - একটা validation নিয়ম শিথিল করা

❌ ভাঙা — একটা নতুন version লাগবে
   - একটা field সরানো
   - একটা field-এর নাম বদলানো
   - একটা type বদলানো (string → int, int → string)
   - একটা optional field-কে required করা
   - একটা field-এর অর্থ বদলানো (নীরব ঘাতক — কোনো টুল এটা ধরে না)
   - একক বদলানো (সেকেন্ড → মিলিসেকেন্ড; ডলার → সেন্ট)
```

### Versioning-এর কৌশল

**১. Event type-এ version** (স্পষ্ট, সহজ, দীর্ঘ)

```json
{ "type": "OrderPlaced.v2", "orderId": "...", ... }
```

**২. একটা header/field-এ version, একটা upcaster সহ**

```python
UPCASTERS = {
    1: lambda d: {**d, "currency": "USD", "version": 2},        # v1-এ USD ধরা হয়েছিল
    2: lambda d: {**d, "totalCents": int(float(d.pop("total")) * 100), "version": 3},
}

def upcast(event: dict) -> dict:
    while (v := event.get("version", 1)) in UPCASTERS:
        event = UPCASTERS[v](event)
    return event                      # consumer সবসময় শুধু সর্বশেষ গঠনটাই দেখে
```

Event-sourced সিস্টেম এই pattern-টাই ব্যবহার করে, আর এটা চমৎকার: পুরনো event গুলো disk-এ অক্ষত থাকে, আর প্রতি version-এর migration-এ একটা ছোট function consumer-দের সহজ রাখে।

**৩. Migration-এর সময় সমান্তরাল topic**

```
orders.v1  ──► পুরনো consumer
orders.v2  ──► নতুন consumer
(producer একটা deprecation জানালার জন্য দুটোতেই লেখে, তারপর v1 বাতিল হয়)
```

### Schema Registry 🟡

একটা কেন্দ্রীয় service, যেটা schema (Avro / Protobuf / JSON Schema) জমা রাখে আর **publish-এর সময়ই compatibility বলবৎ করে**।

```
Producer ──► Schema Registry: "orders topic-এর জন্য schema v3 register করো"
             Registry: v3-কে v2-র বিপরীতে যাচাই করে → compatible? OK : REJECT
Producer ──► Kafka: message + schema ID (কয়েক byte, পুরো schema নয়)
Consumer ──► Registry: ID দিয়ে schema আনে → deserialise করে
```

**কেন গুরুত্বপূর্ণ:** এটা "গত মঙ্গলবার আমরা তিনটা নিচের টিম ভেঙে দিয়েছিলাম"-কে একটা CI ব্যর্থতায় পরিণত করে। আপনি যদি Kafka গুরুত্বের সাথে চালান, তাহলে একটা schema registry চালান।

**ফরম্যাটের পছন্দ:**

| ফরম্যাট | আকার | Schema | নোট |
|--------|------|--------|-------|
| **JSON** | বড় | ঐচ্ছিক (JSON Schema) | মানুষের পড়ার যোগ্য, debug করা সহজ, ধীর, default-এ কোনো বলবৎকরণ নেই |
| **Avro** | ছোট | আবশ্যক | Kafka-র নিজস্ব, চমৎকার evolution নিয়ম, একটা registry লাগে |
| **Protobuf** | সবচেয়ে ছোট | আবশ্যক | দারুণ টুল, cross-language, শক্তিশালী compatibility নিয়ম |

JSON + JSON Schema দিয়ে শুরু করুন। Volume বা contract-এর শৃঙ্খলা দাবি করলে Avro/Protobuf-এ যান।

---

## ৬.১৩ Messaging-এর observability 🟢

যা দেখতে পান না, তা debug করতে পারবেন না। ন্যূনতম কার্যকর instrumentation:

**Metric (এগুলোতে alert দিন):**

| Metric | কেন | Alert-এর সীমা |
|--------|-----|-----------------|
| **Queue-র গভীরতা** | Backlog জমছে | গভীরতা > স্বাভাবিকের ১০× |
| **Queue-র বয়স** (সবচেয়ে পুরনো message) ⭐ | **গভীরতার চেয়ে ভালো** — ১০,০০০ দ্রুত message ঠিক আছে; একটা ২০ মিনিট পুরনো message নয় | বয়স > SLA |
| **Consumer lag** (Kafka) | Consumer কতটা পিছিয়ে | Lag > N বা ধারাবাহিকভাবে বাড়ছে |
| **Processing time** p50/p95/p99 | Consumer-এর স্বাস্থ্য | p99 > বাজেট |
| **Error/retry-র হার** | কিছু ভুল হচ্ছে | যে কোনো টেকসই বৃদ্ধি |
| **DLQ-র গভীরতা** | মানুষ লাগবে এমন message | **> ০** |
| **Outbox-এর unpublished বয়স** | Relay আটকে গেছে | > ৬০ সেকেন্ড |
| **পুনঃপ্রেরণের হার** | Idempotency-র সমস্যা, বা ack ব্যর্থ হচ্ছে | হঠাৎ বৃদ্ধি |

**প্রতিটা message-এ থাকতেই হবে:**

```json
{
  "message_id":     "01J8X...",   // ULID — deduplication-এর জন্য
  "correlation_id": "req_9f2...", // মূল request — পুরো প্রবাহ বেঁধে দেয়
  "causation_id":   "msg_88a...", // কোন message এটা ঘটিয়েছে
  "occurred_at":    "2026-09-12T10:00:00.123Z",
  "schema_version": 2,
  "tenant_id":      "t_42",
  "trace_parent":   "00-4bf92f...-00f067aa0ba902b7-01"   // W3C trace context
}
```

**Correlation ID** উত্তর দেয় *"এই ব্যবহারকারীর request-এর জন্য যা যা ঘটেছে সব দেখাও"*।
**Causation ID** উত্তর দেয় *"এটা কী ঘটিয়েছে?"* — এগুলো শৃঙ্খলিত করলে আপনি পুরো কার্যকারণের গাছটা পুনর্গঠন করতে পারবেন, যেটাই একটা choreographed প্রবাহ debug করার একমাত্র উপায়।

**Broker জুড়ে distributed tracing:** publish করার সময় W3C `traceparent` header ঢোকান আর consume করার সময় বের করুন। তখন আপনার trace `HTTP POST → publish → queue-তে অপেক্ষা → consume → DB write`-কে একটা ছবি হিসেবে দেখাবে, queue-তে অপেক্ষার সময়সহ। EDA debug করার জন্য এটা রূপান্তরকারী। (অধ্যায় ১৮।)

---

## ৬.১৪ সাধারণ ভুল

১. **Dual write** — DB-তে save করা আর আলাদাভাবে publish করা। Outbox ব্যবহার করুন। **এটাই বড়টা।**
২. **`auto_ack=True`** — delivery-তে ack করে, crash-এ message হারায়
৩. **কোনো publisher confirm নেই** — publish fail করছে সেটা আপনি কখনো জানবেনই না
৪. **Non-durable queue বা non-persistent message** — broker restart-এ সব উধাও
৫. **কোনো DLQ নেই** — একটা poison message চিরকাল ঘুরতে থাকে আর queue আটকে দেয়
৬. **যে DLQ কেউ monitor করে না** — পেশাদার নামের একটা data হারানোর বালতি
৭. **Non-retryable error retry করা** — প্রতিবার একটা বিকৃত payload-এ ৫টা retry
৮. **Non-idempotent consumer** — duplicate থেকে দ্বিগুণ charge/ইমেইল/order
৯. **Unbounded queue** — backpressure-এর বদলে memory শেষ
১০. **Design না করেই ordering ধরে নেওয়া** (একাধিক consumer, retry)
১১. **ভেতরের entity-র প্রতিফলন করা মোটা event** — প্রতিটা consumer এখন আপনার schema-র সাথে coupled
১২. **Schema-র ভাঙা পরিবর্তন** — একটা field-এর নাম বদলালে চারটা টিম বন্ধ হয়ে যায়
১৩. **Command হিসেবে নাম দেওয়া event** (একটা topic-এ publish করা `SendEmail`) — অভিপ্রায় আর মালিকানা গুলিয়ে দেয়
১৪. **কোনো correlation ID নেই** — debugging প্রত্নতত্ত্বে পরিণত হয়
১৫. **যেখানে একটা synchronous call সঠিক ছিল সেখানে messaging ব্যবহার** — ব্যবহারকারী যে request-এর জন্য অপেক্ষা করছেন তাতে একটা queue যোগ করলে অকারণে latency আর জটিলতা বাড়ে

---

## ৬.১৫ আর্কিটেক্টের চেকলিস্ট

- [ ] যেখানেই একটা DB write থেকে একটা event তৈরি হতে হবে সেখানে Outbox pattern ব্যবহৃত
- [ ] সব consumer idempotent (inbox table, upsert, বা স্বাভাবিক)
- [ ] প্রতিটা প্রবাহে delivery semantics বাছা আর লেখা আছে
- [ ] Queue durable, message persistent, কাজের পরে manual ack
- [ ] Publisher confirm চালু; unroutable message শনাক্ত হয়
- [ ] Exponential backoff **আর jitter** সহ retry policy
- [ ] কোডে retryable আর non-retryable error শ্রেণিবদ্ধ
- [ ] DLQ configure করা, তাতে alert (> ০), নথিভুক্ত replay টুল আর runbook সহ
- [ ] সব queue সীমাবদ্ধ, একটা নির্ধারিত overflow আচরণ সহ
- [ ] Ordering-এর চাহিদা বলা আছে; per-key partitioning বা ক্রম-অসংবেদনশীল consumer
- [ ] Event schema version করা; full compatibility লক্ষ্য; Kafka ব্যবহার করলে registry
- [ ] প্রকাশিত event ইচ্ছাকৃতভাবে design করা, ভেতরের entity-র dump নয়
- [ ] প্রতিটা message-এ correlation ID, causation ID, message ID আর trace context
- [ ] Metric: গভীরতা, **বয়স**, lag, processing time, error-এর হার, DLQ-র গভীরতা, outbox-এর বয়স
- [ ] Business process কোথাও নথিভুক্ত, যেহেতু কোনো একটা ফাইল সেটা দেখায় না

---

## ৬.১৬ নিজেকে যাচাই

১. Synchronous call-এর তুলনায় messaging-এর চারটা সুবিধা আর চারটা খরচের নাম বলুন।
২. Command বনাম event notification বনাম event-carried state transfer — কখন কোনটা?
৩. Exactly-once delivery কেন অসম্ভব? বরং কী অর্জনযোগ্য, আর কীভাবে?
৪. Dual-write সমস্যাটা একটা বাস্তব ব্যর্থতার timeline দিয়ে ব্যাখ্যা করুন।
৫. Outbox pattern আঁকুন আর ব্যাখ্যা করুন। `FOR UPDATE SKIP LOCKED` কেন?
৬. Inbox pattern কী, আর Outbox + Inbox একসাথে আপনাকে কী দেয়?
৭. নীরবে message-এর ক্রম ভাঙে এমন তিনটা জিনিস বলুন।
৮. একটা consumer-কে কীভাবে ক্রম-অসংবেদনশীল করবেন? কোড সহ দুটো কৌশল দিন।
৯. শুধু TTL আর dead-lettering ব্যবহার করে RabbitMQ-তে একটা retry-with-backoff topology design করুন।
১০. RabbitMQ-র তিনটা durability setting কী কী, আর একটা বাদ দিলে কী হয়?
১১. দুই বাক্যে RabbitMQ বনাম Kafka।
১২. কোন schema পরিবর্তনগুলো নিরাপদ আর কোনগুলো ভাঙা? "একটা field-এর অর্থ বদলানো" কেন সবচেয়ে বিপজ্জনক?
১৩. Queue-র *গভীরতার* চেয়ে queue-র *বয়স* কেন ভালো alert?
১৪. Correlation ID আর causation ID-র পার্থক্য কী?

---

## ৬.১৭ মূল কথাগুলো

- Messaging **temporal decoupling, load levelling আর fan-out** কিনে দেয়; এর দাম **eventual consistency, duplicate আর debug করার কষ্ট**
- **Dual-write সমস্যা বাস্তব আর নীরব।** **Outbox pattern**-ই উত্তর। এটা শিখুন, সব জায়গায় ব্যবহার করুন।
- **At-least-once + idempotent consumer = exactly-once processing।** আর কিছুই সৎ নয়।
- আপনার **per-key ordering** লাগে, global ordering নয় — আর আরও ভালো, **ক্রম-অসংবেদনশীল consumer**
- **Backoff সহ DLQ + retry queue** বাধ্যতামূলক, আর একটা DLQ-তে alert থাকতে হবে আর সেটা replay করার যোগ্য হতে হবে
- **Event হলো contract।** এগুলো version করুন, full compatibility লক্ষ্য রাখুন, আর কখনো আপনার ভেতরের model কাঁচা publish করবেন না
- প্রতিটা message-এ **correlation + causation ID + trace context**, নইলে আপনি debug করতে পারবেন না
- শুধু গভীরতা নয়, **queue-র বয়সে** alert দিন
- **RabbitMQ = routing আর প্রতি-message নিয়ন্ত্রণ। Kafka = volume-এ replay করা যায় এমন সাজানো log।** মানালে দুটোই ব্যবহার করুন।

---

**পরবর্তী:** [অধ্যায় ০৭ — Kafka](07-kafka.md)

**ইংরেজি সংস্করণ:** [Chapter 06](../06-messaging-and-event-driven-architecture.md) · **[সূচিপত্র](README.md)**
