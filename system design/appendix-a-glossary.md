# Appendix A — Glossary

Every significant term in this book, in one line each, with the chapter that covers it.

---

## A

**ABAC** (Attribute-Based Access Control) — Permissions decided from attributes of subject, resource, action and environment. `[17]`

**ACID** — Atomicity, Consistency, Isolation, Durability: the guarantees a transactional database provides. `[09]`

**ACL** (Anti-Corruption Layer) — A translation layer that stops an external or legacy model from infecting your domain. **The highest-value integration pattern in this book.** `[03, 24]`

**Active-Active** — Two or more sites both serving live traffic. `[19]`

**Active-Passive** — One site serves; another stands by. `[19]`

**ADR** (Architecture Decision Record) — A short, immutable document recording one decision, its context, options, consequences and revisit trigger. `[22]`

**Adapter** — Pattern that makes an incompatible interface usable. The code-level ACL. `[01]`

**Afferent coupling (Ca)** — How many things depend on this module. `[01]`

**Aggregate** — A cluster of objects treated as one unit for data changes; the consistency and transaction boundary. `[03]`

**Aggregate Root** — The only member of an aggregate that outside code may reference. `[03]`

**Amdahl's Law** — Speedup is limited by the proportion of time spent in the part you optimise. `[20]`

**Anemic Domain Model** — Entities with only getters/setters and all logic in services; the most common DDD failure. `[01, 03]`

**Anycast** — One IP address announced from many locations; routing sends users to the nearest. `[13]`

**API Gateway** — Single entry point handling auth, rate limiting, routing and TLS for many services. `[08]`

**Arc42** — A 12-section template for comprehensive architecture documentation. `[22]`

**At-least-once** — Delivery guarantee: a message may arrive more than once, never zero times. `[06]`

**At-most-once** — Delivery guarantee: a message may be lost, never duplicated. `[06]`

**Autoscaling** — Automatically adding/removing capacity based on a metric. `[04, 15]`

**Availability** — The proportion of time a system successfully serves requests. `[04, 19]`

**Availability Zone (AZ)** — An isolated datacenter (or group) within a cloud region. `[14]`

---

## B

**Backpressure** — Signalling a fast producer to slow down rather than buffering without bound. `[05]`

**Backward compatibility** — New code can read old data/messages. `[06, 08]`

**BFF** (Backend for Frontend) — A backend tailored to one client type, owned by that client's team. `[08]`

**BIPA** — Illinois Biometric Information Privacy Act; statutory damages per violation. `[17]`

**Blast radius** — How much is affected when something fails. `[19]`

**Blue-Green deployment** — Two identical environments; traffic switches from one to the other. `[15]`

**Bloom filter** — Compact probabilistic structure answering "definitely not present" or "possibly present". `[11]`

**Bounded Context** — An explicit boundary within which one model and language apply consistently. **In practice, your service boundary.** `[03]`

**BRIN index** — Block-range index; tiny, excellent for naturally-ordered large tables. `[09]`

**Brownout** — A deliberate, announced temporary outage of a deprecated path, to find remaining users. `[23]`

**Bulkhead** — Isolating resources so one failing dependency cannot consume them all. `[05]`

**Burn rate** — How fast an error budget is being consumed relative to the SLO period. `[18]`

**Bus factor** — How many people must leave before a component becomes unmaintainable. `[23]`

---

## C

**C4 Model** — Four zoom levels for architecture diagrams: Context, Container, Component, Code. `[22]`

**Cache-aside** — Read from cache; on miss, read the source and populate. The default caching pattern. `[11]`

**Cache avalanche** — Many keys expiring at once, flooding the origin. `[11]`

**Cache penetration** — Requests for keys that do not exist, bypassing the cache entirely. `[11]`

**Cache stampede** — Many concurrent requests recomputing the same expired key. `[11]`

**Canary release** — Routing a small percentage of traffic to a new version. `[15]`

**Canonical data model** — One shared model all systems map to. Useful with industry standards; a trap when invented internally. `[24]`

**CAP theorem** — During a network partition, choose consistency or availability. `[05]`

**Cardinality** — Number of distinct values; in metrics, the number of label combinations. `[18]`

**Causal consistency** — Causally-related operations are seen in the same order by everyone. `[05]`

**CDC** (Change Data Capture) — Reading a database's transaction log to produce a stream of row changes. `[12, 24]`

**CDN** (Content Delivery Network) — Globally distributed caching reverse proxy. `[11, 13]`

**Cell-based architecture** — Independent full-stack cells each serving a subset of tenants, to bound blast radius. `[19]`

**CIDR** — Notation for IP ranges, e.g. `10.0.0.0/16`. `[13]`

**Circuit breaker** — Stops calling a failing dependency, fails fast, and probes for recovery. `[05]`

**Clean Architecture** — Layered design where all dependencies point inward, toward the domain. `[02]`

**Choreography** — Services react to each other's events with no central coordinator. `[02, 05]`

**Cohesion** — How strongly the things inside one module belong together. **High is good.** `[01]`

**Cold start** — Latency when a serverless function or container starts from nothing. `[02, 14]`

**Command** — A request for something to happen (imperative, one handler). `[01, 06]`

**Compensating transaction** — An action that semantically undoes a completed saga step. `[05]`

**Component test** — Tests one service in isolation with real infrastructure and stubbed externals. `[21]`

**Composite index** — An index over several columns; leftmost-prefix rules apply. `[09]`

**Conformist** — Accepting an upstream model as-is with no translation. `[03]`

**Consistent hashing** — Mapping keys and nodes onto a ring so adding a node moves only 1/N of keys. `[04]`

**Consensus** — Several nodes agreeing on one value despite failures. `[05]`

**Container (C4)** — A separately deployable/runnable thing: an app, a database, a queue. Broader than Docker. `[22]`

**Container (runtime)** — A process isolated with namespaces and cgroups, from a layered image. `[15]`

**Context Map** — Diagram of all bounded contexts and the relationship type between each pair. `[03]`

**Contract testing** — Verifying that a consumer's expectations of a provider still hold, in each side's own pipeline. `[21]`

**Conway's Law** — Systems mirror the communication structure of the organisation that builds them. `[00]`

**Coordinated omission** — A load-testing flaw that systematically understates tail latency. `[20]`

**Correlation ID** — An identifier tying all work for one original request together. `[06, 18]`

**Coupling** — How much one thing depends on another. **Low is good.** `[01]`

**CQRS** — Separating the model used to write data from the model used to read it. `[01]`

**CRDT** — A data type that merges concurrent updates without conflict. `[04]`

**Crypto-shredding** — Deleting an encryption key to render encrypted data unrecoverable; the GDPR answer for immutable stores. `[02, 12, 17]`

**CSRF** — Forcing a user's browser to make an authenticated request to your site. `[17]`

**CSP** (Content Security Policy) — Browser header that blocks unauthorised script execution; the best XSS defence. `[17]`

---

## D

**DAG** — Directed acyclic graph; the shape of a data pipeline. `[12]`

**DAST** — Dynamic application security testing: attacking the running application. `[21]`

**Data lake** — Raw files in cheap object storage, schema-on-read. `[12]`

**Data mesh** — Domain teams own their analytical data as a product. `[12]`

**Data warehouse** — Structured, modelled analytical store, schema-on-write. `[12]`

**DDD** (Domain-Driven Design) — Modelling software around the business domain and its language. `[03]`

**Deadlock** — Two transactions each waiting for a lock the other holds. `[09]`

**Defence in depth** — Multiple independent security layers, assuming each will fail. `[17]`

**Denormalisation** — Duplicating data to avoid joins. `[09, 12]`

**Dependency Inversion (DIP)** — Depend on abstractions you own, not on concrete implementations. `[01]`

**Deployment frequency** — A DORA metric: how often you ship. `[16]`

**Dimension table** — Descriptive context in a star schema. `[12]`

**Distributed monolith** — Services that must be deployed together; the worst of both worlds. `[02]`

**DLQ** (Dead Letter Queue) — Where messages go after repeated failure, for human inspection. `[06]`

**Domain event** — A past-tense fact the business cares about, raised by an aggregate. `[01, 03]`

**Domain service** — Business logic that belongs to no single entity; contains no I/O. `[03]`

**DORA metrics** — Deployment frequency, lead time, change failure rate, recovery time. `[16]`

**DTO** — Data Transfer Object; the external shape, never the domain entity. `[01]`

**Dual-write problem** — Writing to a database and a broker non-atomically; the reason the Outbox pattern exists. `[06]`

**Durability** — Committed data survives crashes. `[09, 19]`

---

## E

**Efferent coupling (Ce)** — How many things this module depends on. `[01]`

**Elasticity** — Scaling capacity automatically with demand. `[04, 14]`

**ELT** — Extract, Load, Transform: load raw, transform inside the warehouse. The modern default. `[12]`

**Envelope encryption** — Encrypt data with a data key; encrypt the data key with a master key in a KMS. `[17]`

**Error budget** — The allowed amount of failure implied by an SLO. `[18]`

**ESB** (Enterprise Service Bus) — Central integration middleware; the SOA ancestor of API gateways. `[02, 24]`

**ETag** — A response fingerprint enabling conditional requests and optimistic concurrency. `[08]`

**ETL** — Extract, Transform, Load: transform before loading. `[12]`

**Eventual consistency** — Replicas converge given time and no new writes. `[05]`

**Event-carried state transfer** — Fat events carrying the data consumers need, for autonomy. `[02, 06]`

**Event notification** — Thin events that tell consumers to go and look something up. `[02, 06]`

**Event sourcing** — Storing the sequence of events rather than current state. `[02]`

**Event storming** — A workshop technique for discovering bounded contexts using sticky notes. `[03]`

**Exactly-once processing** — At-least-once delivery + idempotent consumers. The only honest form. `[05, 06]`

**Expand/contract** — A four-release migration pattern enabling zero-downtime schema change. `[09, 16]`

---

## F

**Fact table** — The measurements/events in a star schema; huge and append-only. `[12]`

**Facade** — One simple interface in front of a complex subsystem. `[01]`

**Failover** — Promoting a standby to primary. `[19]`

**Fake** — A working simplified implementation used in tests. **Preferred over mocks.** `[21]`

**Fallacies of distributed computing** — Eight false assumptions about networks; all still violated daily. `[05]`

**Fan-out on read/write** — Computing a feed at read time vs pushing it at write time. `[25]`

**Feature flag** — Runtime toggle decoupling deployment from release. `[15, 16]`

**Fencing token** — A monotonically increasing number preventing a stale leader from acting. `[05]`

**FinOps** — Bringing engineering, finance and product into one conversation about cloud cost. `[14]`

**FIRST** — Fast, Isolated, Repeatable, Self-validating, Timely: properties of good unit tests. `[21]`

**Fitness function** — An automated test for an architectural property, run in CI. `[00, 23]`

**FLP impossibility** — No deterministic consensus in bounded time in an asynchronous network with one failure. `[05]`

**Forward compatibility** — Old code can read new data (by ignoring unknown fields). `[06, 08]`

**Forward proxy** — Sits in front of clients (egress control); contrast reverse proxy. `[13]`

---

## G

**GDPR** — EU data protection regulation; drives erasure, residency and minimisation requirements. `[17]`

**GIN index** — Generalised inverted index; for JSONB, arrays and full-text search. `[09]`

**GiST index** — For geometric data, ranges, nearest-neighbour and exclusion constraints. `[09]`

**GitOps** — Git as the source of truth; an in-cluster agent reconciles reality to match it. `[16]`

**Golden path** — A paved road where the easiest way to do something is also the correct way. `[16, 23]`

**Golden signals** — Latency, traffic, errors, saturation. `[18]`

**Graceful degradation** — Reducing functionality rather than failing entirely. `[05]`

**Graceful shutdown** — Draining in-flight work before terminating; requires preStop + SIGTERM handling. `[15]`

**GraphQL** — Query language letting clients request exactly the fields they need. `[08]`

**gRPC** — Binary RPC over HTTP/2 with Protobuf contracts. `[08]`

---

## H

**HATEOAS** — Responses include links to available next actions. `[08]`

**Head-of-line blocking** — One stalled item blocking everything behind it. `[13]`

**Health check** — Liveness (process alive) vs readiness (can serve traffic). `[04, 15]`

**Hexagonal architecture** — Ports and adapters; the application core depends on nothing external. `[02]`

**HLC** (Hybrid Logical Clock) — Combines physical time with a logical counter for causal ordering. `[05]`

**Horizontal scaling** — More machines. `[04]`

**HPA** — Kubernetes Horizontal Pod Autoscaler. `[15]`

**HSTS** — Header forcing browsers to use HTTPS. `[13, 17]`

---

## I

**IaC** (Infrastructure as Code) — Infrastructure defined declaratively, version-controlled and reviewed. `[16]`

**Idempotency** — Doing something N times has the same effect as doing it once. **The foundation of distributed reliability.** `[05]`

**Idempotency key** — A client-generated key making a POST safely retryable. `[05, 08]`

**IDOR** — Insecure Direct Object Reference; accessing another user's resource by ID. **The most common real vulnerability.** `[17]`

**Immutability** — Objects that cannot change after construction. `[01]`

**Inbox pattern** — Consumer-side deduplication in the same transaction as the work. `[06]`

**Index-only scan** — A query answered entirely from an index, never touching the table. `[09]`

**Ingress** — Kubernetes HTTP routing from outside the cluster. `[15]`

**Instability (I)** — Ce / (Ca + Ce); stable modules should not depend on unstable ones. `[01]`

**iPaaS** — Cloud integration platform with hosted connectors and low-code flows. `[24]`

**ISR** (In-Sync Replicas) — Kafka replicas caught up with the leader. `[07]`

**Isolation level** — How much concurrent transactions may interfere. `[09]`

---

## J–K

**JWT** — A signed token carrying claims; **base64, not encrypted**. `[17]`

**Kappa architecture** — One streaming pipeline; replay the log to recompute history. `[12]`

**KEDA** — Kubernetes event-driven autoscaling, e.g. on queue depth. `[15]`

**Keyset pagination** — Cursor pagination using the last row's sort values; constant time at any depth. `[08]`

**KMS** — Key Management Service. `[17]`

**KRaft** — Kafka's built-in Raft consensus, replacing ZooKeeper. `[07]`

---

## L

**Lakehouse** — Cheap object storage plus an open table format providing warehouse semantics. `[12]`

**Lambda architecture** — Parallel batch and speed layers merged at query time; largely superseded. `[12]`

**Lamport timestamp** — A logical counter establishing happened-before ordering. `[05]`

**Last responsible moment** — Defer a decision until not deciding costs more than deciding. `[00]`

**Latency** — Time for one operation. `[04, 20]`

**LCP** (Largest Contentful Paint) — Core Web Vital measuring when main content appears. `[20]`

**Leader-follower replication** — All writes to one node; followers replicate. `[04]`

**Least privilege** — Minimum permissions, for the minimum time. `[17]`

**Linearizability** — Operations appear to take effect instantaneously; the strongest consistency. `[05]`

**Liskov Substitution Principle** — Subtypes must be usable wherever the parent is expected, without surprises. `[01]`

**Little's Law** — L = λW: concurrency = arrival rate × time in system. `[04]`

**Liveness probe** — "Is the process healthy?" Failure restarts the container. **Must not check dependencies.** `[04, 15]`

**Load shedding** — Deliberately rejecting work when overloaded so the rest succeeds. `[05]`

**Log compaction** — Kafka retention keeping only the latest value per key. `[07]`

**LSM tree** — Write-optimised storage structure used by Cassandra, RocksDB and others. `[10]`

**LWW** (Last Write Wins) — Conflict resolution by timestamp; **silently loses data**. `[04, 05]`

---

## M

**Materialised view** — A precomputed, stored query result. `[09]`

**Medallion architecture** — Bronze (raw) → Silver (clean) → Gold (business) layers in a lakehouse. `[12]`

**Mediator** — Objects communicate through a hub rather than directly. `[01]`

**Metrics cardinality** — See Cardinality. Unbounded label values are the classic mistake. `[18]`

**Microkernel** — Minimal core plus plugins. `[02]`

**Microservice** — An independently deployable service owning its data, organised around a business capability. `[02]`

**Miniservice** — A pragmatically-sized service, larger than "micro". `[02]`

**Modular monolith** — One deployable unit with strictly-enforced internal module boundaries. **The recommended default.** `[02]`

**Monotonic clock** — A clock that never goes backwards; use it for durations. `[05]`

**Monotonic reads** — You never see a value older than one you have already seen. `[05]`

**mTLS** — Mutual TLS; both sides present certificates. `[13, 17]`

**MTTD / MTTR** — Mean time to detect / to recover. `[19]`

**Mutation testing** — Introducing bugs to check whether your tests catch them. `[21]`

**MVCC** — Multi-Version Concurrency Control; readers never block writers. `[09]`

---

## N

**N+1 query** — One query for a list plus one per row. **The most common performance bug in the industry.** `[09, 20]`

**NAT** — Network Address Translation; many private addresses sharing one public address. `[13]`

**NetworkPolicy** — Kubernetes pod-to-pod firewall rules. `[13, 15]`

**NFR** (Non-Functional Requirement) — How well the system must work. **NFRs drive architecture.** `[00]`

**Normalisation** — Structuring tables to eliminate redundancy; 3NF is the practical default. `[09]`

---

## O

**Object storage** — Flat key→blob storage over HTTP; the cheapest and most durable tier. `[14]`

**Observability** — The ability to determine internal state from external outputs, without new code. `[18]`

**OCP** (Open/Closed Principle) — Open for extension, closed for modification. `[01]`

**OIDC** — OpenID Connect; authentication layer on top of OAuth 2.0. `[17]`

**OLAP / OLTP** — Analytical vs transactional processing; opposite storage requirements. `[12]`

**Onion architecture** — Dependencies point inward toward the domain. `[02]`

**OpenAPI** — The standard machine-readable description of an HTTP API. `[08]`

**OpenTelemetry** — Vendor-neutral standard for logs, metrics and traces. `[18]`

**OPA / Gatekeeper** — Policy as code, enforced at admission. `[23]`

**Optimistic concurrency** — Detecting conflicts with a version check instead of holding locks. `[09]`

**Orchestration** — A central coordinator directing a multi-step process. `[02, 05]`

**Outbox pattern** — Writing events to a table in the same transaction as business data, then relaying them. **The answer to the dual-write problem.** `[06]`

---

## P

**PACELC** — If Partition: A or C; Else: Latency or Consistency. More useful than CAP. `[05]`

**Partition (Kafka)** — The unit of ordering and parallelism within a topic. `[07]`

**Partitioning (data)** — Splitting data across stores or tables. `[04, 09]`

**Passkey / WebAuthn** — Phishing-proof authentication bound to the origin. `[17]`

**PDB** (PodDisruptionBudget) — Minimum available pods during voluntary disruption. `[15]`

**PgBouncer** — PostgreSQL connection pooler. `[09]`

**Pilot light** — DR pattern: data replicated continuously, compute switched off until needed. `[19]`

**PITR** (Point-in-Time Recovery) — Restore to any moment using base backup plus transaction log. `[09, 19]`

**PKCE** — OAuth extension preventing authorisation-code interception. **Use it always.** `[17]`

**Poison message** — A message that fails repeatedly and blocks the queue. `[06]`

**Polyglot persistence** — Using several datastores, each for its best-fit access pattern. `[10]`

**Presigned URL** — A time-limited URL letting a client upload/download directly from object storage. `[14]`

**PrivateLink** — Consuming a service over private addressing with no internet route. `[13]`

**Property-based testing** — Stating an invariant and letting the framework generate inputs to break it. `[21]`

**Proxy** — Same interface, added access control. `[01]`

---

## Q–R

**QPS/RPS** — Queries/requests per second. `[04]`

**Quorum** — A majority: ⌊N/2⌋+1. Prevents split brain. `[05]`

**Raft** — A consensus algorithm designed to be understandable. `[05]`

**Rate limiting** — Capping request rate per client. `[05, 08]`

**RBAC** — Role-Based Access Control. `[17]`

**ReBAC** — Relationship-Based Access Control (the Zanzibar model). `[17]`

**Readiness probe** — "Can it serve traffic now?" Failure removes it from the load balancer. `[04, 15]`

**Read-your-writes** — A user always sees their own changes. **Non-negotiable in practice.** `[05]`

**Reconciliation** — Periodically verifying that two systems agree. **Every integration drifts.** `[24]`

**Repository** — An abstraction that makes persistence look like an in-memory collection. `[01, 03]`

**Reverse proxy** — Sits in front of servers; clients think it is the server. `[13]`

**RLS** (Row-Level Security) — Database-enforced row filtering; defence in depth for multi-tenancy. `[17]`

**RPO** (Recovery Point Objective) — How much data you can afford to lose. `[19]`

**RTO** (Recovery Time Objective) — How long you can afford to be down. `[19]`

---

## S

**Saga** — A sequence of local transactions with compensating actions; the alternative to 2PC. `[05]`

**SAST** — Static application security testing. `[21]`

**Saturation** — Work queued waiting for a resource. **A better signal than utilisation.** `[18, 20]`

**SBOM** — Software Bill of Materials; lets you answer "are we affected by CVE-X?" in minutes. `[15, 23]`

**SCD** (Slowly Changing Dimension) — How a warehouse handles changing attributes; Type 2 preserves history. `[12]`

**Schema registry** — Central schema store enforcing compatibility at publish time. `[06]`

**SemVer** — MAJOR.MINOR.PATCH: broke / added / fixed. `[23]`

**Separation of concerns** — Each part handles one area of interest. `[01]`

**Serializable** — The strongest isolation level; prevents write skew. Requires retry logic. `[09]`

**Serverless** — Platform-managed execution billed per use, scaling to zero. `[02, 14]`

**Service mesh** — Sidecar proxies providing mTLS, retries, tracing and L7 load balancing without code changes. `[15]`

**Sharding** — Horizontal partitioning across machines. **The last scaling resort.** `[04]`

**Shadow traffic** — Sending a copy of real requests to a new version and discarding the output. `[21]`

**Shared kernel** — A small shared model between two contexts; keep it tiny or avoid it. `[03]`

**Sidecar** — A helper container sharing a pod's network and storage. `[15]`

**Single-flight** — Only one request recomputes a value; others wait. `[11]`

**SLA / SLI / SLO** — External contract / measurement / internal target. **SLO must be stricter than SLA.** `[18]`

**SOLID** — Five object-oriented design principles. `[01]`

**Split brain** — Two nodes both believing they are the leader. `[05]`

**SRP** (Single Responsibility Principle) — One reason to change; one actor to answer to. `[01]`

**SSE** (Server-Sent Events) — One-way server→client streaming over plain HTTP, with built-in reconnect. **Under-used.** `[08]`

**SSRF** — Server-Side Request Forgery; the application fetches an attacker-supplied URL. `[17]`

**Star schema** — Denormalised fact table surrounded by dimension tables. `[12]`

**StatefulSet** — Kubernetes workload with stable identity and storage per pod. `[15]`

**Stateless** — The server holds no state between requests. **The key to horizontal scaling.** `[04]`

**STRIDE** — Spoofing, Tampering, Repudiation, Information disclosure, DoS, Elevation of privilege. `[17]`

**Strangler Fig** — Incrementally replacing a legacy system behind a facade. **Never big-bang.** `[00, 24]`

**Strategy pattern** — Interchangeable algorithms chosen at runtime; the OCP made concrete. `[01]`

---

## T

**Tail latency** — p99/p99.9; dominates user experience far more than the average. `[18, 20]`

**Tail-based sampling** — Keep 100% of error and slow traces, a small fraction of the rest. `[18]`

**TDE** — Transparent Data Encryption; protects stolen files, not a compromised application. `[17]`

**Technical debt** — The future cost of a shortcut; prudent+deliberate debt is good engineering. `[00]`

**Testcontainers** — Running real infrastructure in containers for integration tests. `[21]`

**Threat model** — Systematically identifying threats against a design. **The highest-return security activity.** `[17]`

**Throughput** — Operations completed per unit of time. `[20]`

**Time-series database** — Optimised for timestamped, append-heavy data with retention policies. `[10]`

**TLS** — Transport Layer Security; use 1.3. `[13]`

**Tolerant reader** — Ignore unknown fields; do not fail on extra data. `[08]`

**Tombstone** — A null-valued record marking a key for deletion during compaction. `[07, 10]`

**Trace / Span** — One request's journey / one unit of work within it. `[18]`

**Two-phase commit (2PC)** — Distributed atomic commit; blocking and usually the wrong choice. `[05]`

**Two Generals Problem** — Proof that guaranteed agreement over an unreliable channel is impossible. `[05]`

---

## U–Z

**Ubiquitous language** — One shared vocabulary used by business and code alike. `[03]`

**Unit economics** — Cost per transaction. **The architect's number.** `[14]`

**Unit of Work** — Tracking changes and committing them in one transaction. `[01]`

**USE method** — Utilisation, Saturation, Errors, per resource. `[20]`

**UUIDv7 / ULID** — Time-sortable unique identifiers; **better than UUIDv4 for primary keys**. `[04]`

**Value object** — Defined by its values, immutable, no identity. `[03]`

**VACUUM** — PostgreSQL reclaiming dead tuples; blocked by long transactions. `[09]`

**Vector clock** — Per-node counters enabling detection of concurrent updates. `[05]`

**Vertical scaling** — A bigger machine. **Do this before sharding.** `[04]`

**Vertical slice architecture** — Organising code by feature rather than by technical layer. `[02]`

**VPC** — A virtual private network in a cloud. `[13]`

**WAF** — Web Application Firewall. `[13, 17]`

**WAL** (Write-Ahead Log) — Changes logged before data pages; enables recovery, replication and CDC. `[09]`

**Watermark** — In stream processing, the point up to which events are assumed complete. `[12]`

**WebSocket** — Full-duplex persistent connection. `[08]`

**Well-Architected** — Six-pillar cloud review framework. `[14]`

**Write skew** — Two transactions each valid alone that together violate an invariant. `[09]`

**XSS** — Cross-Site Scripting; injected script executing in a user's browser. `[17]`

**YAGNI** — You Aren't Gonna Need It. Applies to features, not to expensive-to-retrofit architecture. `[00, 01]`

**Zero Trust** — Never trust, always verify; there is no trusted network. `[17]`

---

**Back to:** [Contents](README.md) · [Cheat Sheets](appendix-b-cheatsheets.md) · [Roadmap](appendix-c-roadmap.md)
