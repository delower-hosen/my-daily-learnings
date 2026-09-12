# Chapter 06 — Messaging & Event-Driven Architecture 🟢

> A message broker is the shock absorber of a distributed system.
> It turns "call this service and hope it is up" into "record this intent and guarantee it gets done."

You already have RabbitMQ experience, so this chapter goes deep on the patterns that separate a working prototype from a production system: the Outbox, the Inbox, dead letters, poison messages, ordering and delivery semantics.

---

## 6.1 Why messaging at all?

### The problem with synchronous calls

```
   Order Service ──HTTP──► Email Service
```

What could go wrong:

1. Email service is **down** → the order fails. But the order was valid! Why should a marketing email block a sale?
2. Email service is **slow** (3 s) → your order API is now a 3-second API
3. Email service is **overloaded** → your retries make it worse
4. You add SMS, push, analytics, a webhook → now the order service calls 5 services, waits for all of them, and knows about all of them

### What messaging changes

```
   Order Service ──► [ Broker ] ──► Email Service
                          ├───────► SMS Service
                          ├───────► Analytics
                          └───────► Webhook Dispatcher
```

| Benefit | What it means |
|---------|---------------|
| **Temporal decoupling** | The consumer does not need to be up when the producer publishes |
| **Load levelling** | A 10× traffic spike becomes a longer queue, not a crash |
| **Fan-out** | Add a sixth consumer without touching the producer |
| **Retry for free** | Failure? The message stays in the queue. |
| **Back-pressure** | Queue depth is a visible, measurable signal of trouble |
| **Independent scaling** | 20 consumers for the slow one, 2 for the fast one |

### What it costs

| Cost | Reality |
|------|---------|
| **Eventual consistency** | The email arrives 200 ms (or 2 minutes) later |
| **No return value** | You cannot "await the result" — the design must change |
| **Duplicates** | At-least-once means handling the same message twice |
| **Ordering** | Messages may arrive out of order |
| **Operational surface** | A broker is a critical stateful system to run, patch and monitor |
| **Debugging** | The flow is no longer in one stack trace |
| **The dual-write problem** | See §6.8 — it is the big one |

> **Rule of thumb: use a request/response call when the caller needs the answer to continue. Use messaging when the caller only needs the work to eventually happen.**

---

## 6.2 Messaging models

### 1. Point-to-point (queue) — one message, one consumer

```
Producer ──► [ Queue ] ──► Consumer A
                      └──► Consumer B      only ONE of them gets each message
```

Use for **work distribution**: "process this video", "send this email", "generate this report". The **Competing Consumers** pattern — add more consumers to go faster.

### 2. Publish/Subscribe — one message, every subscriber

```
                       ┌──► Subscriber A (gets a copy)
Publisher ──► [ Topic ]├──► Subscriber B (gets a copy)
                       └──► Subscriber C (gets a copy)
```

Use for **broadcasting facts**: "an order was placed", "a user was verified". Each interested party reacts independently.

### 3. Request/Response over messaging

```
Client ──► [ request queue ] ──► Server
Client ◄── [ reply queue   ] ◄── Server     (correlation ID matches them up)
```

Possible, but ask yourself why. If you need a synchronous answer, HTTP/gRPC is usually simpler. Valid when you want the queue's buffering and retry on a long-running operation.

### 4. Competing Consumers

```
              ┌──► Worker 1  (processing msg 4)
[ Queue ] ────┼──► Worker 2  (processing msg 5)
              └──► Worker 3  (processing msg 6)
```

The core scaling pattern for async work. Key settings:

- **Prefetch / QoS** — how many unacked messages a consumer may hold. Too high: one consumer hogs the queue and others idle. Too low: round-trip latency dominates. Start at 1–10 for slow tasks, 100+ for fast ones.
- **Ack after work, never before** — if the consumer crashes, the broker redelivers
- Workers must be **idempotent** (Chapter 05)

---

## 6.3 Event notification vs Event-carried state transfer vs Commands

This distinction shapes your whole architecture. Get it explicit.

| | **Command** | **Event Notification** | **Event-Carried State Transfer** |
|---|---|---|---|
| Name | Imperative: `SendEmail` | Past tense: `OrderPlaced` | Past tense: `OrderPlaced` |
| Intent | "Do this" | "This happened" | "This happened, here is the data" |
| Consumers | Exactly one | Many, unknown | Many, unknown |
| Can be rejected? | Yes | No — it already happened | No |
| Payload | Everything needed to act | IDs only | The full relevant state |
| Coupling | Producer knows the consumer exists | Low | Low at runtime, higher on schema |

```json
// COMMAND — a request to a specific handler
{ "type": "SendVerificationEmail", "to": "a@b.com", "template": "kyc_passed",
  "vars": { "name": "Delower", "link": "https://..." } }

// EVENT NOTIFICATION — thin
{ "type": "VerificationPassed", "sessionId": "ses_881", "occurredAt": "..." }
// consumer must now call back: GET /sessions/ses_881  ← extra load + coupling

// EVENT-CARRIED STATE TRANSFER — fat
{ "type": "VerificationPassed", "sessionId": "ses_881", "occurredAt": "...",
  "customer": { "id": "cus_42", "email": "a@b.com", "tier": "enterprise" },
  "result": { "score": 0.94, "method": "active_challenge", "attempts": 1 } }
// consumer is fully autonomous — works even if the producer is down
```

### Which to choose

- **Commands** when there is exactly one correct handler and you are directing work
- **Event notification** when the payload would be huge, or when consumers need fresh data anyway, or when the data is sensitive and should not be broadcast
- **Event-carried state transfer** as the **default for cross-service events** — autonomy is the entire point of EDA

> **Watch the trap:** fat events create a *schema* contract. Every field you publish is a field someone depends on. Publish what consumers need, deliberately — not a JSON dump of your internal entity. (Chapter 03: internal domain events ≠ published integration events.)

---

## 6.4 Delivery semantics 🟢

### At-most-once

```
Broker: sends message → deletes immediately
Consumer: crashes before processing → MESSAGE LOST FOREVER
```

Use for: metrics, sensor readings, log lines — high-volume data where losing one is irrelevant.

### At-least-once ⭐ (the default you will almost always use)

```
Broker: sends → waits for ack → deletes on ack
Consumer: processes → acks
If the ack never arrives (crash, network) → broker REDELIVERS
→ the message may be processed TWICE
```

Use for: everything that matters. Combine with **idempotent consumers** (Chapter 05).

### Exactly-once — the honest version

```
Impossible as a DELIVERY guarantee (Two Generals, Chapter 05).
Achievable as a PROCESSING guarantee:
    at-least-once delivery
  + idempotent consumer (dedup table / upsert / natural idempotency)
  = exactly-once processing
```

Kafka's "exactly-once semantics" is real but narrow: it works when your consume→process→produce loop stays *within Kafka* (transactional producer + read-committed consumer + offsets committed in the same transaction). The moment you write to an external database or call an external API, **you are back to needing idempotency.** Know this precisely — it comes up in interviews and in vendor conversations.

```python
# The universal pattern: dedup in the same transaction as the work
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
            return                                     # already processed

        await do_the_business_work(msg)                # SAME transaction
    # commit → both the dedup record and the work land atomically
```

---

## 6.5 Ordering 🟢

Ordering is one of the most misunderstood topics in messaging.

### Three levels

| Level | Meaning | Cost |
|-------|---------|------|
| **Global ordering** | All messages everywhere in one total order | Requires a single writer. Kills throughput. Essentially never worth it. |
| **Partition ordering** | Order guaranteed within a partition/queue | Cheap — this is what Kafka gives you |
| **Per-key ordering** ⭐ | Order guaranteed for the same key (customer, order, session) | Cheap and almost always sufficient |

> **Design insight: you almost never need global ordering. You need per-entity ordering.**
> Events for order #123 must be ordered relative to each other. Whether they interleave with order #456 is irrelevant.

### How per-key ordering works

```
Kafka:     partition = hash(key) % num_partitions
           All events for customer_42 → the same partition → strictly ordered
           One partition is consumed by ONE consumer in a group → no reordering

RabbitMQ:  use a consistent-hash exchange, or one queue per key range,
           with a single consumer per queue (prefetch=1 for strictness)
```

### What breaks ordering (the gotchas)

1. **Multiple consumers on one queue** — three workers pull msg 1, 2, 3 and finish in any order
2. **Retries** — msg 1 fails and goes to a retry queue; msg 2 succeeds immediately. Now msg 2 is applied before msg 1.
3. **Concurrency inside the consumer** — you read in order, then `Task.Run` each one
4. **Increasing partitions in Kafka** — `hash(key) % N` changes, so a key can move to a new partition, and its old and new events are no longer ordered relative to each other. **Plan partition counts ahead; increasing them is not free.**

### The better answer: design so order does not matter

Ordering guarantees are expensive and fragile. Make the consumer **order-insensitive** instead:

```python
# VERSION GUARD — ignore anything older than what we have
async def handle_customer_updated(event: CustomerUpdated) -> None:
    await db.execute(
        """UPDATE customer_view
           SET name = $2, email = $3, version = $4
           WHERE id = $1 AND version < $4""",     # out-of-order events do nothing
        event.customer_id, event.name, event.email, event.version)
```

```python
# COMMUTATIVE OPERATIONS — order-independent by construction
# instead of "set count = 5", use "add 1" on a CRDT counter
```

```python
# STATE MACHINE GUARD — illegal transitions are simply ignored
if order.status is OrderStatus.SHIPPED and event.type == "PaymentCaptured":
    return          # a late payment event cannot un-ship an order
```

> **Rule: prefer idempotent, order-insensitive consumers over strict ordering guarantees.** It is cheaper, it scales, and it survives retries.

---

## 6.6 Dead Letter Queues and poison messages 🟢

### The poison message problem

```
Message M fails → broker redelivers → fails → redelivers → fails → ...
→ infinite loop
→ this one message blocks the queue for everyone
→ your CPU is 100% and nothing gets done
```

Causes: malformed payload, a bug in the consumer, a referenced record that was deleted, a schema change.

### Dead Letter Queue (DLQ)

After N failures, move the message to a separate queue for human inspection.

```
                    ┌──────────────┐
Producer ──────────►│  main.queue  │──► Consumer
                    └──────┬───────┘       │ fails 5×
                           │               │
                    ┌──────▼───────┐ ◄─────┘
                    │   dlq.queue  │  ← alert on depth > 0
                    └──────────────┘
```

```python
# RabbitMQ setup
channel.exchange_declare("verification.dlx", exchange_type="direct", durable=True)
channel.queue_declare("verification.dlq", durable=True)
channel.queue_bind("verification.dlq", "verification.dlx", routing_key="failed")

channel.queue_declare(
    "verification.process",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "verification.dlx",
        "x-dead-letter-routing-key": "failed",
        "x-message-ttl": 3_600_000,        # 1 hour max lifetime in the main queue
        "x-max-length": 100_000,           # bounded! (backpressure, Chapter 05)
        "x-overflow": "reject-publish",    # refuse new messages rather than drop old
    },
)
```

### Retry queues with backoff (the delay-queue trick)

A DLQ alone is too blunt — a transient 3-second vendor outage should not send messages to a human. You want **retries with increasing delay**, then a DLQ.

```
main.queue ──fail──► retry.5s   ──(TTL expires)──► back to main.queue
           ──fail──► retry.30s  ──(TTL expires)──► back to main.queue
           ──fail──► retry.5m   ──(TTL expires)──► back to main.queue
           ──fail──► DLQ (human)
```

RabbitMQ has no native delayed delivery, so you use **TTL + dead-lettering**: a message sits in `retry.30s` with a 30-second TTL and no consumer; when the TTL expires, RabbitMQ dead-letters it *back to the main exchange*. Elegant and widely used. (Alternatively, the `rabbitmq_delayed_message_exchange` plugin.)

```python
RETRY_DELAYS_MS = [5_000, 30_000, 300_000, 1_800_000]   # 5s, 30s, 5m, 30m

for delay in RETRY_DELAYS_MS:
    channel.queue_declare(
        f"verification.retry.{delay}",
        durable=True,
        arguments={
            "x-message-ttl": delay,
            "x-dead-letter-exchange": "verification.exchange",   # back to main
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

### DLQ operational discipline

A DLQ nobody looks at is a data-loss mechanism with extra steps.

- [ ] **Alert when DLQ depth > 0.** Always. It means something needs a human.
- [ ] Store the **failure reason**, the **stack trace**, the **attempt count** and the **original headers** on the message
- [ ] Build a **replay tool** — one command to push messages from the DLQ back to the main queue after a fix
- [ ] Have a **runbook**: inspect → categorise → fix code or data → replay → verify
- [ ] **Set a retention/size limit** on the DLQ too, and alert before it hits

### Distinguish retryable from non-retryable — immediately

```python
try:
    await process(msg)
    ack()
except (ValidationError, SchemaError, UnknownMessageType) as e:
    # Will NEVER succeed. Do not waste 4 retries. Straight to DLQ.
    dead_letter(msg, reason=f"permanent: {e}")
    ack()
except (TimeoutError, ConnectionError, ServiceUnavailable) as e:
    # Transient. Retry with backoff.
    schedule_retry(msg, attempt, reason=str(e))
    ack()
except Exception as e:
    # Unknown — retry a couple of times, then DLQ, and alert. An unclassified
    # error is itself a finding: classify it next sprint.
    logger.exception("unclassified consumer error")
    schedule_retry(msg, attempt, reason=str(e))
    ack()
```

---

## 6.7 The dual-write problem ⭐⭐

**This is the single most important problem in event-driven architecture, and most teams get it wrong.**

```python
# LOOKS FINE. IS BROKEN.
async def place_order(order: Order) -> None:
    await db.save(order)                      # write 1: database
    await broker.publish(OrderPlaced(order))  # write 2: broker
```

**What happens when the process crashes between the two lines?**

- Order is in the database
- No event was published
- Inventory is never reserved, the customer is never emailed
- **Silent, permanent inconsistency.** No error anywhere.

Swap the order:

```python
await broker.publish(OrderPlaced(order))   # published
await db.save(order)                       # ← crash here
# Now: inventory reserved, email sent, for an order that does not exist.
```

Wrap it in a transaction?

```python
async with db.transaction():
    await db.save(order)
    await broker.publish(event)     # broker is NOT in the DB transaction
    # if the broker publish succeeds and the DB commit fails, the event is already gone
```

> **You cannot atomically write to two different systems.** (Unless you use 2PC/XA, which you should not — Chapter 05.)

This is called the **dual-write problem**, and it is why the next pattern exists.

---

## 6.8 The Outbox Pattern ⭐⭐⭐ 🟢

**The single most valuable pattern in this chapter.**

**Idea:** write the event into a table in the **same database transaction** as your business data. A separate process reads that table and publishes to the broker.

```
┌───────────────────────────────────────┐
│          ONE ACID TRANSACTION         │
│                                       │
│   INSERT INTO orders  (...)           │
│   INSERT INTO outbox  (...)           │
│                                       │
│   COMMIT  ← both, or neither          │
└───────────────┬───────────────────────┘
                │
                │  (separate process, later)
                ▼
        ┌───────────────┐
        │ Outbox Relay  │ polls or tails the WAL
        └───────┬───────┘
                │ publish
                ▼
        ┌───────────────┐
        │    Broker     │  at-least-once → consumers must be idempotent
        └───────────────┘
```

### Schema

```sql
CREATE TABLE outbox (
    id             BIGSERIAL PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,     -- 'Order'
    aggregate_id   TEXT        NOT NULL,     -- 'ord_8812'  → use as the partition key
    event_type     TEXT        NOT NULL,     -- 'OrderPlaced'
    payload        JSONB       NOT NULL,
    headers        JSONB       NOT NULL DEFAULT '{}',   -- correlation id, tenant, schema version
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at   TIMESTAMPTZ                          -- NULL = not yet published
);

-- Partial index: only unpublished rows, so the polling query stays fast forever
CREATE INDEX idx_outbox_unpublished
    ON outbox (id) WHERE published_at IS NULL;
```

### Writing (the business transaction)

```python
async def place_order(cmd: PlaceOrder) -> OrderId:
    async with db.transaction():                       # ONE transaction
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
    # COMMIT — order and event are now atomically consistent
    return order.id
```

### Publishing — option A: polling relay (simple, works everywhere)

```python
async def relay_loop() -> None:
    while True:
        rows = await db.fetch(
            """SELECT id, aggregate_id, event_type, payload, headers
               FROM outbox
               WHERE published_at IS NULL
               ORDER BY id                       -- preserves order
               LIMIT 100
               FOR UPDATE SKIP LOCKED""")        # safe with multiple relay instances

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

**`FOR UPDATE SKIP LOCKED` is the key detail** — it lets you run several relay instances without them fighting over the same rows.

**Note:** if you crash after publishing but before the `UPDATE`, the message is published twice. That is fine — **at-least-once, and consumers are idempotent.** Never try to make the relay exactly-once; make the consumers idempotent instead.

### Publishing — option B: Change Data Capture (better at scale)

Instead of polling, tail the database's write-ahead log.

```
Postgres WAL ──► Debezium ──► Kafka
```

- ✅ No polling load on the database, sub-second latency, no missed rows
- ✅ Preserves transaction order exactly
- ❌ More infrastructure (Kafka Connect / Debezium) to run and monitor

**Rule of thumb:** start with polling (it is 60 lines of code); move to CDC when polling latency or load becomes a problem, or when you already run Kafka.

### Housekeeping

```sql
-- Delete published rows older than 7 days (keep a window for debugging/replay)
DELETE FROM outbox
WHERE published_at IS NOT NULL AND published_at < now() - INTERVAL '7 days';
```

Alert on: **oldest unpublished row age** (if it exceeds ~60 s, the relay is stuck) and **outbox table size**.

---

## 6.9 The Inbox Pattern

The mirror image, on the consumer side: guarantee a message is processed **exactly once** even with at-least-once delivery.

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
            return                                   # already processed — ack and move on

        await reserve_inventory(msg.payload)         # SAME transaction
    # commit → the dedup record and the business change land together
```

```sql
CREATE TABLE inbox (
    message_id  TEXT NOT NULL,
    consumer    TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (message_id, consumer)
);
CREATE INDEX ON inbox (received_at);   -- for cleanup
```

**Outbox + Inbox together give you end-to-end exactly-once *processing* across services, built entirely on at-least-once delivery and ordinary database transactions.** This is the production-grade answer, and it requires no exotic technology.

---

## 6.10 Transactional messaging with Kafka 🟡

Kafka offers a transactional producer that atomically writes messages to multiple partitions **and** commits consumer offsets.

```java
producer.initTransactions();
producer.beginTransaction();
producer.send(new ProducerRecord<>("orders", key, orderEvent));
producer.send(new ProducerRecord<>("audit",  key, auditEvent));
producer.sendOffsetsToTransaction(offsets, consumerGroupMetadata);  // atomic with the sends
producer.commitTransaction();
```

Consumers set `isolation.level=read_committed` to skip aborted messages.

**The crucial limitation, again:** this is atomic **within Kafka only**. A database write inside that block is not covered. For consume→transform→produce pipelines it is genuinely exactly-once; for anything touching an external system, use the Outbox/Inbox.

---

## 6.11 RabbitMQ deep dive 🟢

### The model: exchanges, bindings, queues

```
                    ┌──────────────┐
Producer ──────────►│   EXCHANGE   │
                    └──────┬───────┘
                    routing by binding
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         [ Queue A ]  [ Queue B ]  [ Queue C ]
              │            │            │
          Consumer     Consumer     Consumer
```

Producers **never** publish to a queue — always to an exchange. The exchange type decides the routing.

| Exchange type | Routing rule | Use for |
|---------------|-------------|---------|
| **Direct** | routing key == binding key (exact) | Targeted work queues, severity routing |
| **Topic** ⭐ | Pattern with `*` (one word) and `#` (zero or more) | **Event publishing — the most useful** |
| **Fanout** | Ignore the key, send to all bound queues | Pure broadcast |
| **Headers** | Match on header values | Rare; use when routing depends on several attributes |

```python
# Topic exchange — the workhorse
channel.exchange_declare("events", exchange_type="topic", durable=True)

# Routing keys: <context>.<aggregate>.<event>
#   verification.session.passed
#   verification.session.failed
#   billing.invoice.created

channel.queue_bind("email.queue",     "events", "verification.session.passed")
channel.queue_bind("analytics.queue", "events", "verification.#")     # everything
channel.queue_bind("audit.queue",     "events", "#")                  # literally all
channel.queue_bind("alerts.queue",    "events", "*.*.failed")         # any failure
```

### Durability — three separate settings, all required

```python
# 1. The queue survives a broker restart
channel.queue_declare("work", durable=True)

# 2. The MESSAGE survives a broker restart
channel.basic_publish(
    exchange="", routing_key="work", body=payload,
    properties=pika.BasicProperties(delivery_mode=2))   # 2 = persistent

# 3. The consumer acks only AFTER the work is done
channel.basic_consume("work", on_message, auto_ack=False)   # NEVER auto_ack=True
```

> Miss any one of the three and you will lose messages on restart. `auto_ack=True` is the single most common RabbitMQ mistake — it acks on *delivery*, so a crash mid-processing loses the message silently.

### Publisher confirms — do not skip this

Without confirms, `basic_publish` returns immediately and you have **no idea** whether the broker got it.

```python
channel.confirm_delivery()
try:
    channel.basic_publish(exchange="events", routing_key="verification.session.passed",
                          body=payload,
                          properties=pika.BasicProperties(delivery_mode=2))
    # returns only after the broker confirms
except pika.exceptions.UnroutableError:
    # published to an exchange with no matching binding → it went nowhere
    logger.error("unroutable message — check bindings")
```

Also set `mandatory=True` to be told when a message cannot be routed to any queue. Silent unroutable messages are a classic "why is nothing happening?" bug.

### Prefetch (QoS) — the performance dial

```python
channel.basic_qos(prefetch_count=10)
```

- **prefetch=1** — perfectly fair distribution, maximum latency per round trip. Use for slow tasks (video processing, 4 seconds each).
- **prefetch=100+** — high throughput, but one consumer may grab a big batch and others idle. Use for fast tasks (< 10 ms each).
- **Rule of thumb:** `prefetch ≈ ceil(processing_time / round_trip_time)`, capped by memory.

### Quorum queues (modern default for reliability)

```python
channel.queue_declare("payments", durable=True,
                      arguments={"x-queue-type": "quorum"})
```

Quorum queues use Raft for replication across nodes. They replace the old "mirrored queues" (now deprecated) and are the correct choice for anything you cannot afford to lose. Trade-off: more disk I/O and memory; not suitable for very high-throughput transient work.

### RabbitMQ vs Kafka — the question you will be asked

| | **RabbitMQ** | **Kafka** |
|---|---|---|
| **Model** | Smart broker, dumb consumer | Dumb broker, smart consumer |
| **After consumption** | Message is deleted | Retained for the configured period |
| **Replay** | No (unless you re-publish) | **Yes — the defining feature** |
| **Routing** | Rich (topic, direct, headers, per-message) | Simple (topic + partition by key) |
| **Per-message operations** | Yes — ack/nack/reject one message, priority, TTL | No — consumers track an offset |
| **Ordering** | Per queue, weakened by multiple consumers | **Strict per partition** |
| **Throughput** | ~tens of thousands msg/s per node | **Millions msg/s** |
| **Retry/DLQ** | **Built in and excellent** | Manual (retry topics, DLQ topics) |
| **Consumers** | Competing consumers on a queue | Consumer groups, partition-assigned |
| **Best for** | **Task queues, RPC, complex routing, per-message retry** | **Event streams, log aggregation, stream processing, replay, very high volume** |

> **The one-sentence answer:** *"RabbitMQ is a smart message router for work distribution with per-message control; Kafka is a durable, replayable, ordered log for high-volume event streams. If I need per-message retry and complex routing, RabbitMQ. If I need replay, high throughput, or many independent consumers reading the same history, Kafka."*

**You can absolutely use both.** A very common architecture: Kafka for the event backbone and analytics, RabbitMQ for task queues and jobs.

---

## 6.12 Schema evolution 🟢

Events are a **contract**. Once published, someone depends on them. And with a stream, an event from 2023 may still be read in 2030.

### Compatibility types

| Type | Meaning | Rule |
|------|---------|------|
| **Backward** | New consumer can read old events | Add optional fields; never remove or rename a required field |
| **Forward** | Old consumer can read new events | Consumers must **ignore unknown fields** |
| **Full** | Both | Only add optional fields with defaults |

> **Target FULL compatibility.** It is the only way to deploy producers and consumers independently, which is the whole point of decoupling.

### The safe-change rules

```
✅ SAFE
   - Add an OPTIONAL field with a default
   - Add a new event type
   - Widen a value set (add a new enum value) — IF consumers handle unknown values
   - Relax a validation rule

❌ BREAKING — needs a new version
   - Remove a field
   - Rename a field
   - Change a type (string → int, int → string)
   - Make an optional field required
   - Change the meaning of a field (the silent killer — no tool catches this)
   - Change units (seconds → milliseconds; dollars → cents)
```

### Versioning strategies

**1. Version in the event type** (explicit, simple, verbose)

```json
{ "type": "OrderPlaced.v2", "orderId": "...", ... }
```

**2. Version in a header/field, with an upcaster**

```python
UPCASTERS = {
    1: lambda d: {**d, "currency": "USD", "version": 2},        # v1 assumed USD
    2: lambda d: {**d, "totalCents": int(float(d.pop("total")) * 100), "version": 3},
}

def upcast(event: dict) -> dict:
    while (v := event.get("version", 1)) in UPCASTERS:
        event = UPCASTERS[v](event)
    return event                      # consumers only ever see the latest shape
```

This is the pattern event-sourced systems use, and it is excellent: old events stay untouched on disk, and one small function per version migration keeps consumers simple.

**3. Parallel topics during migration**

```
orders.v1  ──► old consumers
orders.v2  ──► new consumers
(producer writes both for a deprecation window, then v1 is retired)
```

### Schema Registry 🟡

A central service storing schemas (Avro / Protobuf / JSON Schema) and **enforcing compatibility at publish time**.

```
Producer ──► Schema Registry: "register schema v3 for topic orders"
             Registry: checks v3 against v2 → compatible? OK : REJECT
Producer ──► Kafka: message + schema ID (a few bytes, not the whole schema)
Consumer ──► Registry: fetch schema by ID → deserialise
```

**Why it matters:** it turns "we broke three downstream teams last Tuesday" into a CI failure. If you run Kafka seriously, run a schema registry.

**Format choice:**

| Format | Size | Schema | Notes |
|--------|------|--------|-------|
| **JSON** | Large | Optional (JSON Schema) | Human-readable, easy debugging, slow, no enforcement by default |
| **Avro** | Small | Required | Kafka-native, excellent evolution rules, needs a registry |
| **Protobuf** | Smallest | Required | Great tooling, cross-language, strong compatibility rules |

Start with JSON + JSON Schema. Move to Avro/Protobuf when volume or contract discipline demands it.

---

## 6.13 Observability for messaging 🟢

You cannot debug what you cannot see. Minimum viable instrumentation:

**Metrics (alert on these):**

| Metric | Why | Alert threshold |
|--------|-----|-----------------|
| **Queue depth** | Backlog building | Depth > 10× normal |
| **Queue age** (oldest message) ⭐ | **Better than depth** — 10,000 fast messages are fine; one 20-minute-old message is not | Age > SLA |
| **Consumer lag** (Kafka) | How far behind consumers are | Lag > N or growing steadily |
| **Processing time** p50/p95/p99 | Consumer health | p99 > budget |
| **Error/retry rate** | Things going wrong | Any sustained increase |
| **DLQ depth** | Messages needing a human | **> 0** |
| **Outbox unpublished age** | Relay stuck | > 60 s |
| **Redelivery rate** | Idempotency problems, or acks failing | Sudden spike |

**Every message must carry:**

```json
{
  "message_id":     "01J8X...",   // ULID — for deduplication
  "correlation_id": "req_9f2...", // the original request — ties the whole flow together
  "causation_id":   "msg_88a...", // WHICH message caused this one
  "occurred_at":    "2026-09-12T10:00:00.123Z",
  "schema_version": 2,
  "tenant_id":      "t_42",
  "trace_parent":   "00-4bf92f...-00f067aa0ba902b7-01"   // W3C trace context
}
```

**Correlation ID** answers *"show me everything that happened for this user request"*.
**Causation ID** answers *"what triggered this?"* — chain them and you can reconstruct the entire causal tree, which is the only way to debug a choreographed flow.

**Distributed tracing across the broker:** inject the W3C `traceparent` header when publishing and extract it when consuming. Then your trace shows `HTTP POST → publish → queue wait → consume → DB write` as one picture, including the time spent waiting in the queue. This is transformative for EDA debugging. (Chapter 18.)

---

## 6.14 Common mistakes

1. **Dual write** — saving to the DB and publishing separately. Use the Outbox. **This is the big one.**
2. **`auto_ack=True`** — acknowledges on delivery, loses messages on crash
3. **No publisher confirms** — you never learn that publishes are failing
4. **Non-durable queues or non-persistent messages** — everything vanishes on a broker restart
5. **No DLQ** — a poison message loops forever and blocks the queue
6. **A DLQ nobody monitors** — a data-loss bucket with a professional name
7. **Retrying non-retryable errors** — 5 retries on a malformed payload, every time
8. **Non-idempotent consumers** — duplicates create duplicate charges/emails/orders
9. **Unbounded queues** — memory exhaustion instead of backpressure
10. **Assuming ordering** without designing for it (multiple consumers, retries)
11. **Fat events that mirror internal entities** — every consumer is now coupled to your schema
12. **Breaking schema changes** — renaming a field takes down four teams
13. **Events named as commands** (`SendEmail` published to a topic) — confuses intent and ownership
14. **No correlation ID** — debugging becomes archaeology
15. **Using messaging where a synchronous call was correct** — adding a queue to a request the user is waiting for adds latency and complexity for nothing

---

## 6.15 Architect's checklist

- [ ] Outbox pattern used wherever a DB write must produce an event
- [ ] All consumers idempotent (inbox table, upsert, or natural)
- [ ] Delivery semantics chosen and written down per flow
- [ ] Queues durable, messages persistent, manual acks after work
- [ ] Publisher confirms enabled; unroutable messages detected
- [ ] Retry policy with exponential backoff **and jitter**
- [ ] Retryable vs non-retryable errors classified in code
- [ ] DLQ configured, alerted on (> 0), with a documented replay tool and runbook
- [ ] All queues bounded, with a defined overflow behaviour
- [ ] Ordering requirement stated; per-key partitioning or order-insensitive consumers
- [ ] Event schemas versioned; full compatibility targeted; registry if using Kafka
- [ ] Published events are deliberately designed, not internal entity dumps
- [ ] Correlation ID, causation ID, message ID and trace context on every message
- [ ] Metrics: depth, **age**, lag, processing time, error rate, DLQ depth, outbox age
- [ ] Business process documented somewhere, since no single file shows it

---

## 6.16 Self-test

1. Name four benefits and four costs of messaging vs synchronous calls.
2. Command vs event notification vs event-carried state transfer — when to use each?
3. Why is exactly-once delivery impossible? What is achievable instead, and how?
4. Explain the dual-write problem with a concrete failure timeline.
5. Draw and explain the Outbox pattern. Why `FOR UPDATE SKIP LOCKED`?
6. What is the Inbox pattern, and what do Outbox + Inbox give you together?
7. Give three things that silently break message ordering.
8. How do you make a consumer order-insensitive? Give two techniques with code.
9. Design a retry-with-backoff topology in RabbitMQ using only TTL and dead-lettering.
10. What are the three RabbitMQ durability settings, and what happens if you miss one?
11. RabbitMQ vs Kafka in two sentences.
12. Which schema changes are safe and which are breaking? Why is "changing the meaning of a field" the most dangerous?
13. Why is queue *age* a better alert than queue *depth*?
14. What is the difference between a correlation ID and a causation ID?

---

## 6.17 Key takeaways

- Messaging buys **temporal decoupling, load levelling and fan-out**; it costs **eventual consistency, duplicates and debugging difficulty**
- **The dual-write problem is real and silent.** The **Outbox pattern** is the answer. Learn it, use it everywhere.
- **At-least-once + idempotent consumers = exactly-once processing.** Nothing else is honest.
- You need **per-key ordering**, not global ordering — and better still, **order-insensitive consumers**
- **DLQ + retry queues with backoff** are mandatory, and a DLQ must be alerted on and replayable
- **Events are contracts.** Version them, target full compatibility, and never publish your internal model raw
- **Correlation + causation IDs + trace context** on every message, or you cannot debug
- Alert on **queue age**, not just depth
- **RabbitMQ = routing and per-message control. Kafka = replayable ordered log at volume.** Use both if it fits.

---

**Next:** [Chapter 07 — Kafka](07-kafka.md)
