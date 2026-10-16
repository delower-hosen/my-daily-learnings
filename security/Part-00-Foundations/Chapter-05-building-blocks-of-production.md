# Chapter 5 — The Building Blocks of Production: Servers, Services, Databases, Caches, Queues, and Proxies

---

## 1. Why This Matters

Chapter 4 gave you the map of a request. This chapter walks into each box on that map and
asks the recurring question of the book — *what does this component get wrong by default, and
why?* — for the specific pieces you already use: PostgreSQL, MongoDB, Redis, RabbitMQ, Nginx,
and the application server itself.

You know these components as an application engineer: you know Redis is fast, RabbitMQ moves
messages, Nginx proxies requests. What you may not have examined is their **default security
posture**, and this is where an enormous fraction of real-world breaches actually originate.
The uncomfortable pattern, which you should carry as a working assumption for the rest of your
career:

> Most infrastructure software ships configured for *developer convenience on a trusted
> network in 1998*, not for *safety on a hostile network in production*. The defaults assume
> the network is friendly. The network is not friendly.

Concrete, historically devastating examples, all of which are *default behavior*, not bugs:

- **Redis** historically had no authentication and, until recently, bound to all interfaces
  in some packages. Combined with `CONFIG SET dir`, an exposed Redis is remote code execution
  (Chapter 3 §10.1). Hundreds of thousands of instances have been compromised this way.
- **MongoDB** shipped for years binding to `0.0.0.0` with no authentication. The result was
  the "Mongo apocalypse" of 2017: tens of thousands of databases wiped and ransomed by
  automated scanners in days.
- **Elasticsearch, Memcached, Docker API, Kubernetes dashboards, Jenkins** — the same story
  repeated, each one a mass-compromise event driven by an insecure default meeting the public
  internet.
- **Memcached** on UDP became the largest DDoS *amplification* vector ever recorded (a 50,000×
  amplification factor), because its default UDP listener would reflect and amplify spoofed
  requests.

None of these required a clever exploit. They required a default left unchanged and a network
path left open. As a cloud security engineer, a large part of your value is knowing these
defaults cold and building systems where they cannot hurt you — which means understanding
*why* each default is what it is, so you can reason about the next component you have never
seen.

This chapter also introduces the **data-classification and blast-radius** thinking that Part
15 formalizes: these components hold data of very different sensitivity (a cache of rendered
HTML vs. the customer table vs. a queue of payment events), and the right controls follow from
what a component holds and what happens if it is breached.

---

## 2. Prerequisites

- Chapters 1–4. Especially Chapter 3 (bind addresses, sockets, the docker.sock lesson) and
  Chapter 4 (the map, and where each of these components sits on it).
- You have deployed at least a few of these components yourself. This chapter reframes what
  you know operationally in security terms.

---

## 3. Mental Model

**Every production component is three things at once, and each has its own security surface:**

```
   A COMPONENT (e.g. PostgreSQL)
   +----------------------------------------------------------+
   | 1. A PROCESS         -> runs as a user, has memory,      |
   |                         syscalls, capabilities (Ch.1-2)  |
   | 2. A NETWORK SERVICE -> binds an address:port, speaks a  |
   |                         protocol, authenticates (Ch.3)   |
   | 3. A DATA CUSTODIAN  -> holds data of some sensitivity,  |
   |                         with its own access model        |
   +----------------------------------------------------------+
```

For any component — including ones you have never met — walk these three:

1. **As a process:** which user does it run as? Root? Does it need to? What is its blast
   radius if the process is compromised (Chapter 1 §7)?
2. **As a network service:** what does it bind to (Chapter 3 §4.4)? Does it authenticate
   connections? Is the protocol encrypted? Is it reachable from where it should not be?
3. **As a data custodian:** what data does it hold, how sensitive is it, what is its own
   authorization model (users/roles/ACLs), and is the data encrypted at rest and in transit?

This three-lens model is a checklist you can apply in a design review to *any* piece of
infrastructure, and it maps directly onto the layers of Chapter 4: the process lives at the
host layer, the network service at Stops 2–4, and the data custodian at Stop 7.

**Second model — the "middlebox trust" problem.** Proxies, load balancers, caches, and
message brokers are *intermediaries*: they sit between other components and see (or store)
data in transit. That makes them uniquely dangerous, because a compromise of an intermediary
is a compromise of *everything that flows through it*. A reverse proxy that terminates TLS
sees every request in plaintext. A cache holds copies of responses. A message broker holds
the payloads of events. Intermediaries concentrate data, and concentrated data concentrates
risk — the blast-radius reasoning of Chapter 1 §5.4, applied to the data plane.

---

## 4. Fundamentals: The Components, One by One

### 4.1 The application server (Kestrel / Node / Gunicorn)

This is your own code, so you have the most control — and the most responsibility (Chapter 4
Stops 6–7 live here). The security essentials as a *component*:

- **Process identity:** run as a dedicated non-root user (Chapter 2 §7, §11). A web
  application that parses untrusted input should never be root, so that a deserialization or
  memory-safety bug in a dependency is contained.
- **Bind address:** loopback, fronted by a proxy (Chapter 3 §7). Never expose Kestrel/Gunicorn
  directly to the internet — they are application servers, not hardened edges.
- **Resource limits:** the thread pool, connection limits, and request size limits are
  security controls (Chapter 3 §5.3) — they bound denial-of-service.
- **Secrets in memory and config:** connection strings and keys live in this process's memory
  (Chapter 1 §7) and often in its config files. This is the single richest target after a
  compromise, and the reason for short-lived credentials (Chapter 68).
- **Error handling:** an unhandled exception that returns a stack trace leaks dependency
  versions and can de-randomize ASLR (Chapter 1 §11.2); it is a Stop 6 information-disclosure
  bug (Chapter 58).

### 4.2 PostgreSQL — the relational store

**As a process:** runs as the `postgres` user (good — not root). It uses shared memory
extensively (the shared buffer pool), which is why its RSS accounting is subtle (Chapter 1
§6.2). A compromise of the `postgres` OS user can read all data files directly, bypassing
the SQL permission model entirely — so OS-level and DB-level access are two separate concerns.

**As a network service:**

- **Bind:** Debian/Ubuntu default `listen_addresses = 'localhost'` (safe); some other
  packages and container images default wider. Always verify (`ss -tlpn | grep 5432`).
- **Authentication is governed by `pg_hba.conf`** — the host-based access file, which is a
  small firewall of its own, matched top to bottom:

```
# TYPE  DATABASE  USER      ADDRESS         METHOD
local   all       all                       peer          # OS-user maps to DB-user (local)
host    all       all       127.0.0.1/32    scram-sha-256  # password, strong hashing
host    ledger    ledger    10.0.1.0/24     scram-sha-256  # app subnet only
# DANGER if present:
# host  all       all       0.0.0.0/0       trust          # NO password from ANYWHERE
```

The `trust` method means *no authentication at all* — a catastrophic misconfiguration that
has appeared in real breaches. `scram-sha-256` is the modern password method; `md5` is legacy
and weaker; `cert` enables client-certificate auth; `peer` maps the OS user for local
connections. Reading and auditing `pg_hba.conf` is a core skill, because it is where "who can
connect" is actually decided (Chapter 4 Stop 7).

- **TLS:** off by default in many builds. `ssl = on` plus `sslmode=verify-full` on the client
  is required to protect the query and results in transit and to authenticate the server
  (otherwise a MITM on the DB connection reads everything — the same threat as Chapter 4
  Stop 4, applied to the app→DB hop, which System A hides behind loopback but System B exposes
  on the network).

**As a data custodian:**

- **The role/privilege model:** PostgreSQL has roles, `GRANT`/`REVOKE`, schema and
  table-level privileges, and **row-level security (RLS)**. The application should connect as
  a role with only the privileges it needs (Chapter 4 §Stop 7, least privilege) — not as a
  superuser, and ideally not even as the table *owner* (owners can `DROP`). A read-heavy
  service might use a read-only role for most operations.
- **Encryption at rest:** via the filesystem/volume (Chapter 1 §4.6) or transparent options;
  protects snapshots and stolen disks, not a live SQL-injection.
- **Audit:** `log_statement`, `log_connections`, and the `pgaudit` extension produce the
  record you will need for detection and incident response (Chapter 4 §6.5, Chapter 13).

### 4.3 MongoDB — the document store

**The cautionary tale of insecure defaults.** For years MongoDB bound to `0.0.0.0` with
**no authentication enabled by default**. Modern versions bind to localhost and require
`--auth`, but the lesson stands and older deployments persist.

Security essentials:

- **Enable authentication (`security.authorization: enabled`)** — without it, anyone who can
  connect is an admin. This is not optional; it is the difference between "a database" and "a
  public data dump waiting to be scraped."
- **Bind to a private interface / loopback**, and use MongoDB's role-based access control
  (built-in roles like `read`, `readWrite`, `dbAdmin`, plus custom roles) so the app has a
  scoped user, not `root`.
- **TLS:** off by default; enable `net.tls.mode: requireTLS`.
- **Injection is different but real:** MongoDB does not have SQL, but **NoSQL injection**
  exists — passing attacker-controlled objects (e.g. `{"$ne": null}`) into a query where a
  scalar was expected bypasses authentication checks and filters (Chapter 47). This is the
  same cross-layer confusion (Chapter 4 §9) in a document idiom: a JSON body that becomes
  query *operators* instead of query *values*. The fix is the same in spirit — validate and
  coerce types so user input can never become a query operator.

### 4.4 Redis — the in-memory store

Redis is the sharpest example of the "convenience defaults" problem, and the most
security-relevant to understand deeply because it is so widely deployed as a cache, session
store, and queue.

**As a process:** single-threaded for command execution (which has security relevance — one
slow command like `KEYS *` blocks *all* clients, an availability foot-gun), runs as the
`redis` user. It holds everything in memory, so a memory read (Chapter 1 §8.5) or a `DEBUG`/
`DUMP` command exposes all cached data — including session tokens if you store sessions there.

**As a network service — the danger zone:**

- **Authentication:** historically none. Modern Redis has `requirepass` and, in Redis 6+,
  **ACLs** (per-user command and key-pattern permissions). Use them even behind a private
  bind — defense in depth (Chapter 3 §7, point 3).
- **`protected-mode`** (default on since 3.2) refuses external connections when no password
  is set — a guardrail added *because* of the mass compromises, but one that is easily
  disabled and absent in old configs.
- **The RCE primitive:** `CONFIG SET dir` + `CONFIG SET dbfilename` + `SAVE` writes a
  Redis-controlled file to an attacker-chosen path — a cron job, an SSH `authorized_keys`, a
  web shell. Also `SLAVEOF`/`REPLICAOF` and the `MODULE LOAD` command (loads native code) are
  RCE vectors. This is why an exposed, unauthenticated Redis is not "someone can read my
  cache" but "someone owns the host" (Chapter 3 §10.1). Disable dangerous commands via ACL
  or `rename-command` in hardened deployments.
- **TLS:** supported (`tls-port`), off by default.

**As a data custodian:** consider carefully *what you put in Redis*. Session tokens, cached
PII, and rate-limit counters have very different sensitivities. A cache breach that exposes
rendered public pages is minor; one that exposes session tokens is account takeover for every
active user. Classify before you cache (Chapter 15, data architecture, and Chapter 51,
sessions).

### 4.5 RabbitMQ — the message broker

**As an intermediary, it concentrates data:** every message that flows through a queue is, at
least transiently, stored in the broker. A compromise of RabbitMQ is a compromise of the
*content* of your events — which for the Ledger system might include transaction details,
user actions, or PII in event payloads.

Security essentials:

- **Default credentials:** the infamous `guest`/`guest`. It is restricted to localhost by
  default in modern versions, but the account exists and is the first thing any scanner
  tries. Delete it or change it; create per-application users with scoped permissions.
- **The permission model** is per-vhost, with `configure`/`write`/`read` permissions matched
  by regex against resource names. A publisher should have `write` only to its exchanges; a
  consumer `read` only from its queues. This is least privilege for the messaging layer, and
  it limits what a compromised producer or consumer can do (it cannot, for example, read
  every other service's queue).
- **The management UI** (port 15672) is a web app with its own auth — another network service
  to bind privately and protect; exposed management UIs are a common finding.
- **TLS** between clients and the broker, and for inter-node clustering (the Erlang
  distribution protocol between nodes is a powerful, sensitive channel — its cookie is
  effectively a cluster root credential).
- **Message-level concerns:** messages may carry sensitive payloads; consider whether they
  should be encrypted at the application level, and remember that messages persisted to disk
  (durable queues) are subject to the same at-rest reasoning as any store.

### 4.6 Nginx — the reverse proxy (an intermediary that sees everything)

Nginx sits at Chapter 4 Stop 5, and if it terminates TLS it sees **every request and response
in plaintext**. That makes it both a powerful security control point and a high-value target.

**As a process:** the master runs as root (to bind 80/443 and read certs/logs), workers drop
to `www-data` (Chapter 2 §7). The private TLS keys are readable by the master — protect them
(mode 0600, owner root) because they are the crown jewels of your TLS (Chapter 27).

**As an intermediary, its configuration *is* security policy:**

- **TLS configuration:** protocol versions, cipher suites, OCSP stapling, HSTS — Nginx is
  where you enforce modern TLS (Chapter 28).
- **Request filtering and limits:** `client_max_body_size`, header and body timeouts,
  `limit_req`/`limit_conn` — the resource-exhaustion defenses from Chapter 3 §5, applied at
  the edge before requests reach the fragile application.
- **Header handling:** setting security response headers, and — critically — handling
  `X-Forwarded-For`/`X-Forwarded-Proto` correctly (Chapter 4 §Stop 5). A misconfigured proxy
  that trusts a client-supplied `X-Forwarded-For` enables IP spoofing and rate-limit bypass.
- **Request smuggling exposure:** if Nginx and the backend disagree on request framing, an
  attacker can smuggle a second request past the proxy's controls (Chapter 57). The proxy's
  parsing consistency is a security property.
- **Path handling and misrouting:** `alias`/`location` misconfigurations have leaked source
  code and allowed path traversal; a trailing-slash or normalization bug can expose internal
  endpoints. The proxy's routing rules are an authorization surface.

### 4.7 The pattern across all of them

Step back and notice that the same five issues recur in every component:

| Issue | Insecure default seen in |
|---|---|
| No / weak authentication | Redis, MongoDB, Memcached, RabbitMQ (guest), Elasticsearch |
| Binds to all interfaces | Redis (old), MongoDB (old), many container images |
| No transport encryption | PostgreSQL, MongoDB, Redis, RabbitMQ — all off by default |
| Overpowered default account | RabbitMQ guest, DB superuser used by apps, Redis no-ACL |
| Dangerous features enabled | Redis CONFIG/MODULE, PostgreSQL untrusted extensions, Mongo server-side JS |

Once you see the pattern, you stop needing to memorize each product. You apply the three-lens
model (§3) and the five-issue checklist (above) to *any* component, including ones released
next year. That transferable habit is the actual deliverable of this chapter.

---

## 5. Deep Technical Explanation: Why the Defaults Are Bad

It is worth understanding *why* infrastructure software ships insecure, because the reasons
tell you where to look and predict the next component's failings.

1. **The software predates a hostile internet, or assumes a trusted network.** Redis,
   Memcached, and early MongoDB were designed for a single-tenant, trusted LAN or a single
   developer's laptop. "The network is trusted" was a reasonable 2009 assumption for a cache.
   It is a catastrophic 2026 assumption. This is precisely the assumption Zero Trust
   (Chapter 43) exists to kill.

2. **Convenience wins adoption.** A database that requires auth configuration before it starts
   is harder to try than one that just works. Vendors optimize the first five minutes
   (developer experience) over the production posture, because adoption drives the business.
   The insecure default is a *growth* decision, not an oversight — which is why it persists
   even after the vendor knows better (they add guardrails like `protected-mode` rather than
   changing the default outright, for years).

3. **The trust boundary is invisible in development.** On a laptop, everything is loopback and
   the insecure default never bites. The gap between dev and prod (Chapter 98) is exactly
   where these defaults become vulnerabilities: the developer's `docker-compose.yml` with no
   Redis password gets copied toward production, and the loopback assumption silently breaks
   when the network changes.

4. **Backward compatibility freezes bad defaults.** Changing a default breaks existing
   deployments, so vendors are reluctant. `md5` auth lingers in PostgreSQL; `guest` lingers in
   RabbitMQ. The install base holds the default hostage.

The predictive value: when you adopt *any* new data or infrastructure component, assume it
ships trusting the network, with a powerful default account, and without transport encryption,
until you have verified otherwise. Read the "security" section of its docs *first*, not after
the incident. This is a professional reflex, and it is faster than it sounds — the five-issue
checklist takes ten minutes per component and prevents the incidents that take weeks.

### 5.1 The intermediary amplification problem

Intermediaries deserve extra scrutiny because their compromise is *transitive*. Trace the
blast radius:

```
   Compromise a leaf (one app instance)  -> that instance's data and permissions
   Compromise an intermediary (Nginx)    -> EVERY request/response through it (plaintext)
   Compromise the cache (Redis)          -> EVERY session/cached secret it holds
   Compromise the broker (RabbitMQ)      -> EVERY message that transits it
   Compromise the DB (PostgreSQL)        -> ALL persisted data
```

The blast radius grows as you move toward shared, central components. This is why the most
central components get the most controls (network isolation, auth, encryption, monitoring),
and why "defense in depth around the data" is the right investment priority — a lesson Part 15
formalizes as designing around blast radius. It also argues *against* unnecessary
centralization: a single shared Redis across all tenants concentrates risk that per-tenant
isolation would bound (Chapter 51).

---

## 6. Internals: Inspecting a Component's Posture

A repeatable procedure for assessing any component, using PostgreSQL and Redis as worked
examples. This is a mini-audit you can run in minutes.

### 6.1 The three-lens audit, as commands

**Lens 1 — as a process:**

```bash
$ ps -o pid,user,comm -C postgres -C redis-server
   PID USER      COMMAND
  1990 postgres  postgres        # good: not root
  2101 redis     redis-server    # good: not root
$ grep -E 'Cap(Eff|Bnd)' /proc/1990/status   # what can it do? (Chapter 2)
```

**Lens 2 — as a network service:**

```bash
$ ss -tlpn | grep -E '5432|6379|5672|27017'
tcp LISTEN 0 244 127.0.0.1:5432 ...   # good: loopback
tcp LISTEN 0 511 0.0.0.0:6379  ...   # FINDING: Redis on all interfaces

# Is auth required? Test it (from an allowed host):
$ redis-cli -h 127.0.0.1 ping
PONG                                  # FINDING if this works with no password

$ psql "host=127.0.0.1 dbname=postgres user=postgres" -c 'select 1' 2>&1 | head -1
# prompts for password (good) or connects (FINDING: trust auth)
```

**Lens 3 — as a data custodian:**

```bash
# PostgreSQL: what can the app's role do? (least privilege check)
$ psql -c "\du"                        # list roles and their attributes
$ psql -c "SELECT grantee, table_name, privilege_type
           FROM information_schema.role_table_grants
           WHERE grantee='ledger';"    # exactly what 'ledger' may touch

# Redis: is dangerous functionality reachable?
$ redis-cli acl list                   # ACL rules (Redis 6+)
$ redis-cli config get dir             # can CONFIG be called? (RCE primitive)
```

### 6.2 Reading pg_hba.conf like a firewall

```bash
$ sudo grep -vE '^\s*#|^\s*$' $(psql -tAc 'SHOW hba_file')
```

Read every line as an allow rule, top to bottom, first match wins. Flag: any `trust` method,
any `0.0.0.0/0` address, any `md5` (prefer `scram-sha-256`), any rule broader than it needs to
be. This file is the answer to "who can connect to the database," and auditing it is a
concrete, billable review deliverable.

### 6.3 What a cache actually holds

```bash
$ redis-cli --scan --count 100 | head       # sample the keyspace (NOT `KEYS *` in prod!)
session:a1b2c3...
ratelimit:198.51.100.7
cache:accounts:42
$ redis-cli get "session:a1b2c3..." | head -c 200
```

If session tokens or PII are in there in plaintext, you have just found the blast radius of a
Redis compromise. This is the "classify before you cache" check made concrete.

---

## 7. Real-World Example: The Ledger Stack's Component Posture

Applying the three-lens model to System A produces a component security inventory — exactly
the deliverable a cloud security engineer produces in an architecture review:

| Component | Process | Network | Data custodian | Top risk |
|---|---|---|---|---|
| Nginx | master root → worker www-data | 0.0.0.0:443 (intended) | TLS keys; sees all plaintext | key theft; smuggling; header mishandling |
| Kestrel/API | user `ledger`, non-root | 127.0.0.1:5000 | secrets in memory; sees all app data | RCE → secrets → DB creds |
| PostgreSQL | user `postgres` | 127.0.0.1:5432 | ALL persisted data | over-priv app role; `trust` in pg_hba |
| Redis | user `redis` | 127.0.0.1:6379 | sessions + cached PII | no auth + CONFIG = RCE if exposed |
| RabbitMQ | user `rabbitmq` | 127.0.0.1:5672 | event payloads | guest account; scoped perms |

The security story of System A rests almost entirely on the **loopback binds** (Chapter 3 §7):
they are the single control that makes the weak defaults (no Redis auth, no DB TLS) survivable.
That is a fragile foundation — one `bind 0.0.0.0` change, or one migration to a network where
loopback no longer means "same trusted host," and every weak default is suddenly exposed.

This is exactly why the migration to System B (AWS) must *re-provide each property
deliberately* (Chapter 4 §7):

- Redis → ElastiCache: now on the network, so it **must** have AUTH and TLS enabled and a
  security group restricting it to the app tier — the loopback crutch is gone.
- PostgreSQL → RDS: TLS becomes mandatory (network hop), `pg_hba` is managed but the role
  privileges are still yours to scope, and IAM database auth becomes an option (short-lived
  credentials — Chapter 81).
- RabbitMQ → Amazon MQ or self-managed: guest gone, TLS on, per-service users.

The recurring lesson, one more time because it is the whole point of Part 0: **the layers and
components are constant; what changes is which mechanism provides each security property, and
you must be able to name it for every component in the inventory.**

---

## 8. Hands-On Demonstration

### LAB 5.1 — Component Security Audit and Hardening

**Objective.** Stand up the Ledger backing services with realistic defaults, run the
three-lens audit to find the findings, then harden each and verify.

**Cost.** Free. **Environment.** ENV-2/ENV-3. **Time.** 60–90 minutes.

**Setup — services with mixed posture:**

```bash
mkdir -p ~/lab05 && cd ~/lab05
cat > docker-compose.yml <<'EOF'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: postgres
    # note: default trusts local; we will inspect pg_hba
    ports: ["5432:5432"]          # deliberately published to the host
  redis:
    image: redis:7
    command: ["redis-server", "--protected-mode", "no"]   # DELIBERATELY INSECURE
    ports: ["6379:6379"]                                   # exposed, no auth
  rabbitmq:
    image: rabbitmq:3-management
    ports: ["5672:5672", "15672:15672"]                    # guest/guest, mgmt exposed
EOF
docker compose up -d
sleep 20
```

**Steps.**

*Step 1 — Lens 2 audit (network + auth) on each.*

```bash
# Redis: connect with NO password from the host
redis-cli -h 127.0.0.1 ping                      # PONG  -> FINDING: no auth
redis-cli -h 127.0.0.1 config get dir            # works -> FINDING: RCE primitive reachable

# RabbitMQ: default guest account, management UI
curl -su guest:guest http://localhost:15672/api/whoami ; echo   # -> FINDING: guest works

# PostgreSQL: inspect pg_hba
docker compose exec postgres bash -c 'grep -vE "^\s*#|^\s*$" "$PGDATA/pg_hba.conf"'
```

**Expected findings:** Redis answers with no auth and exposes `CONFIG`; RabbitMQ accepts
guest; PostgreSQL's default `pg_hba` may include a broad `trust`/`scram` line for the
container network. Write each up as a finding with its blast radius.

*Step 2 — Demonstrate the Redis RCE primitive (contained in the lab).*

```bash
# We won't write outside the container, but we prove the mechanism:
redis-cli -h 127.0.0.1 config set dir /tmp
redis-cli -h 127.0.0.1 config set dbfilename pwned.txt
redis-cli -h 127.0.0.1 set payload "arbitrary content an attacker controls"
redis-cli -h 127.0.0.1 save
docker compose exec redis cat /tmp/pwned.txt      # attacker-controlled file written
```

**Security implication:** if `dir` were `/var/spool/cron/crontabs` and the redis user could
write there, this is remote code execution. Note the three preconditions (reachable + no auth
+ CONFIG enabled) and that removing any one breaks the chain.

*Step 3 — Harden.*

```bash
cat > docker-compose.yml <<'EOF'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/pg
    secrets: [pg]
    # no ports: not published to the host at all
    networks: [backend]
  redis:
    image: redis:7
    command: ["redis-server", "--requirepass", "S3cure-redis-pass",
              "--protected-mode", "yes",
              "--rename-command", "CONFIG", "",
              "--rename-command", "MODULE", "",
              "--rename-command", "SLAVEOF", ""]
    networks: [backend]
  rabbitmq:
    image: rabbitmq:3-management
    environment:
      RABBITMQ_DEFAULT_USER: ledger
      RABBITMQ_DEFAULT_PASS: S3cure-mq-pass
    networks: [backend]   # mgmt UI not published
secrets:
  pg: { environment: PG_SECRET }
networks: { backend: {} }
EOF
PG_SECRET="S3cure-pg-pass" docker compose up -d
sleep 20
```

*Step 4 — Verify the findings are closed.*

```bash
# From the host, the services are no longer published:
redis-cli -h 127.0.0.1 -p 6379 ping 2>&1 || echo "unreachable from host: good"

# From inside the network, auth is now required and CONFIG is gone:
docker compose exec redis redis-cli -a S3cure-redis-pass ping        # PONG
docker compose exec redis redis-cli -a S3cure-redis-pass config get dir 2>&1 \
   | grep -qi "unknown command" && echo "CONFIG disabled: good"
docker compose exec rabbitmq rabbitmqctl authenticate_user guest guest 2>&1 \
   | grep -qi "refused\|error" && echo "guest disabled: good"
```

**Attack scenario extension.** Suppose Redis *must* be reachable from a separate app host.
Enumerate the layered controls (bind private interface, `requirepass`/ACL, TLS, SG allowing
only the app SG) and note this is the "control moves to the network layer" case from §7.

**Hardening summary applied:** removed host port publishing (network isolation), required
auth on every service, disabled dangerous Redis commands, replaced default accounts. Note that
you fixed each finding at *multiple* layers where possible (Redis: not exposed AND auth AND
CONFIG disabled) — defense in depth.

**Verification checklist:**
```bash
docker compose ps --format '{{.Service}} {{.Ports}}'   # expect no host-published ports
```

**Cleanup.**
```bash
cd ~/lab05 && docker compose down -v && cd ~ && rm -rf ~/lab05
```

---

## 9. Security Implications

- **Insecure defaults are the norm, not the exception.** Assume every new component trusts the
  network, has a powerful default account, and lacks transport encryption until you verify
  otherwise.
- **The three-lens model (process / network service / data custodian)** applies to any
  component and maps onto the Chapter 4 layers; use it as a review checklist.
- **Intermediaries concentrate risk.** Proxies, caches, and brokers see or store data in
  transit; their compromise is transitive. Give central components the most controls.
- **Loopback binds are a real control but a fragile foundation** — they make weak defaults
  survivable, and they silently disappear when the network changes. Do not let them be the
  *only* control (Chapter 3 §7).
- **Classify data before you store it.** A cache of public pages and a cache of session tokens
  demand different protection; the blast radius follows the data's sensitivity.
- **Least privilege applies to every component's own access model** — DB roles, Redis ACLs,
  RabbitMQ per-vhost permissions — not just to cloud IAM.

---

## 10. Attack Scenarios

1. **Exposed unauthenticated data store → RCE** (Redis/Mongo). Covered in Chapter 3 §10.1 and
   Lab 5.1. Root cause: convenience default + network reachability + dangerous feature.
2. **Default credentials** (RabbitMQ guest, `admin/admin` management UIs, DB default
   passwords). Scanners try these first; they require no exploit.
3. **NoSQL injection via type confusion** (`{"$ne": null}` as a password). A JSON body whose
   values become query *operators* — Chapter 4's cross-layer confusion in a document store
   (Chapter 47).
4. **Intermediary compromise → mass data exposure.** Compromise of a TLS-terminating proxy or
   a shared cache exposes everything flowing through it.
5. **Message broker payload exposure.** Sensitive data in event payloads sitting in queues,
   readable by anyone with broker access or a leaked cluster cookie.
6. **DB connection MITM.** App→DB traffic in plaintext on the network (System B without TLS)
   read by an on-path attacker — the loopback crutch removed by cloud migration.
7. **Amplification DDoS** (Memcached UDP, misconfigured DNS): a service that reflects and
   amplifies spoofed requests weaponized against third parties (Chapter 85).

---

## 11. Defensive Techniques

The universal checklist, derived from the five recurring issues (§4.7):

1. **Authenticate every connection**, even behind a private network. Strong, unique
   credentials or, better, short-lived/managed identities (Chapter 68, 81). Delete default
   accounts.
2. **Bind privately and isolate at the network layer** (loopback/private interface + security
   group/NetworkPolicy). Never expose a data store to the internet.
3. **Encrypt in transit** — enable TLS on every component; do not rely on "it's internal."
4. **Least privilege for each component's access model** — scoped DB roles, Redis ACLs,
   RabbitMQ per-vhost permissions; the app is never a superuser.
5. **Disable dangerous features** — Redis `CONFIG`/`MODULE`/`SLAVEOF`, PostgreSQL untrusted
   extensions and superuser-only functions, MongoDB server-side JS, unused broker plugins.
6. **Classify and minimize stored data** — do not cache secrets in plaintext; set TTLs;
   encrypt sensitive payloads at the application layer where the store cannot be trusted.
7. **Audit and monitor** — enable connection/statement/command logging; alert on anomalous
   access (a new client IP to the DB, `CONFIG` calls to Redis, guest login attempts).
8. **Manage the intermediaries' secrets** — TLS private keys (mode 0600, root), cluster
   cookies, and broker credentials are high-value; treat them as crown jewels.

---

## 12. Production Architecture

The hardened backing-services tier, and how it changes from System A to System B:

```
 SYSTEM A (VPS)                          SYSTEM B (AWS)
 --------------------------------        ------------------------------------------
 App (loopback binds provide             App (ECS task) in a private subnet
   the primary isolation)                  |
   |  loopback                             | SG: only from task SG, TLS required
   v                                       v
 PostgreSQL 127.0.0.1  scram, RLS        RDS PostgreSQL  private subnet, TLS,
 Redis      127.0.0.1  requirepass         IAM auth option, SG-restricted
 RabbitMQ   127.0.0.1  scoped users      ElastiCache Redis  AUTH + TLS + SG
                                         Amazon MQ / SQS  IAM-controlled, encrypted
 secrets in config files                 Secrets Manager / KMS, short-lived creds
 logs on local disk                      CloudWatch / CloudTrail centralized
```

The architectural upgrades the cloud enables are worth naming, because they address the exact
weaknesses of System A:

- **Managed identity replaces stored passwords** (IAM DB auth, IRSA) — the biggest single
  improvement, shrinking the "secret in memory forever" window (Chapter 1 §7) to minutes.
- **Network isolation is explicit and auditable** (security groups, private subnets) rather
  than implicit in a bind address that anyone can change.
- **Encryption in transit and at rest are one checkbox each** and centrally enforceable via
  policy (Chapter 82, 91).
- **Centralized logging** replaces logs-on-the-box that an attacker with host access can
  delete (Chapter 36, 116).

But the cloud does not *automatically* do any of this — every item is a decision you must make
and verify. A default RDS instance can still be public; a default ElastiCache can still lack
AUTH. The three-lens audit (§6) applies to managed services too, just with the console/API as
the inspection tool instead of `ss` and config files.

---

## 13. Common Mistakes

1. **Relying on loopback/private networks as the *only* control**, so weak defaults are one
   config change from exposure.
2. **Apps connecting as database superusers** (or the table owner), turning any bug into total
   compromise.
3. **Leaving default accounts** (RabbitMQ guest, admin/admin UIs) enabled.
4. **No transport encryption on internal hops**, assuming "internal = safe."
5. **Caching secrets in plaintext** (session tokens, PII in Redis) without considering the
   cache's blast radius.
6. **Exposing management/admin UIs** (RabbitMQ 15672, DB admin tools) to broad networks.
7. **Leaving Redis `CONFIG`/`MODULE` enabled** on any instance an attacker might reach.
8. **Copying dev `docker-compose.yml` toward production**, carrying no-auth, exposed defaults
   with it (Chapter 98).
9. **Not auditing `pg_hba.conf`** (or the managed equivalent) — the actual "who can connect"
   decision.
10. **Treating managed services as automatically secure** — they inherit the same three-lens
    questions.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| App can't reach DB after enabling TLS | client `sslmode` too strict, or cert not trusted | `psql "sslmode=verify-full ..."`; check CA bundle |
| Redis works locally, "NOAUTH" from app | `requirepass` set but app not sending it | check the client connection string/ACL |
| RabbitMQ "access refused" | per-vhost permissions not granted to the app user | `rabbitmqctl list_permissions -p <vhost>` |
| DB rejects app connection | `pg_hba.conf` no matching allow line for the app's IP/method | inspect hba; check order (first match wins) |
| Redis latency spikes / freezes | a blocking command (`KEYS`, big `SMEMBERS`) — single-threaded | `redis-cli --latency`; `SLOWLOG GET`; use `SCAN` |
| Unexpected data-store client IP | possible compromise or exposed service | connection logs; `ss -tnp`; check bind + SG |
| Management UI reachable externally | bound/published too widely | check ports/bind; restrict to private + auth |

---

## 15. Practical Lab

Lab 5.1 is in §8. Register it in the lab index. Extension: repeat the three-lens audit against
a managed service if you have an AWS account — create an RDS instance and an ElastiCache
cluster with defaults, then audit them via the console/CLI and remediate (private subnet,
`PubliclyAccessible=false`, encryption, AUTH/TLS, SG restriction). Produce the same
component-inventory table as §7 for the cloud version.

---

## 16. Exercises

### Concept questions

**5.1** State the three-lens model and apply it, from memory, to a component not covered in
this chapter (e.g. Elasticsearch, Kafka, or Memcached). What would you check for each lens?

**5.2** Explain *why* infrastructure software tends to ship with insecure defaults, and use
that reasoning to predict the likely default posture of a data store you have never used.

**5.3** Why is a compromise of Nginx (or any TLS-terminating proxy) more damaging than a
compromise of one application instance? Frame it in blast-radius terms.

**5.4** Redis bound to loopback with no password: is this secure? Argue both sides and give the
defense-in-depth answer.

**5.5** Explain how the Redis `CONFIG SET dir` RCE works, list its three preconditions, and
show that removing any one breaks it.

### Debugging problems

**5.6** After migrating PostgreSQL from a VPS (loopback) to a networked host, the app works but
a security scan flags "database traffic in plaintext." Nothing in the app changed. Explain what
protected the traffic before, what does not now, and the fix.

**5.7** A shared Redis cache is returning one tenant's data to another intermittently. The app
code is correct per-request. Place this on the component model and give the most likely cause.

**5.8** RabbitMQ consumers for service B can read service A's queues. Explain which control is
missing and how you would scope it correctly.

### Security scenarios

**5.9** You inherit a system with PostgreSQL, Redis, and RabbitMQ, all reachable from a broad
internal network, all with default or weak auth. You have one day. Prioritize your hardening
actions and justify the order by blast radius and exploitability.

**5.10** A developer wants to cache decrypted PII in Redis "for performance." Walk through the
data-classification and blast-radius reasoning, and propose what you would actually allow.

### Architecture questions

**5.11** Design the backing-services tier for System B such that a compromise of the
application tier does not immediately expose all data. Name the control at each hop and what
has to fail for the DB to be reached directly.

**5.12** You must run a multi-tenant SaaS. Argue for and against a single shared Redis/DB vs.
per-tenant instances, in terms of blast radius, cost, and operational complexity, and state
what you would choose and why.

### Hands-on exercises

**5.13** Write a script that runs the three-lens audit against all data-store containers on a
host and outputs a findings table (process user, bind address, auth required?, dangerous
features reachable?).

**5.14** Configure PostgreSQL with an app role restricted to `SELECT/INSERT/UPDATE` on three
tables (no `DELETE`, no DDL), connect as it, and demonstrate that a `DROP TABLE` and a
cross-table read both fail.

**5.15** Enable TLS on a local PostgreSQL and connect with `sslmode=verify-full`. Then connect
with `sslmode=disable` and observe (via tcpdump) the query visible in plaintext in the second
case and not the first.

### Interview questions

**5.16** "Why has Redis been involved in so many breaches? Walk me from the default to the RCE."

**5.17** "How would you assess the security posture of a database you've just been handed?"

**5.18** "What's special about securing a reverse proxy or a message broker compared to
securing an application server?"

**5.19** "An app connects to its database as a superuser. Why is that a problem, and what would
you change?"

**5.20** "Everything's on a private network, so we don't need auth or TLS between services.
Respond."

---

## 17. Summary

- Every production component is simultaneously a **process** (runs as a user, has a blast
  radius), a **network service** (binds, authenticates, may encrypt), and a **data custodian**
  (holds classified data with its own access model). This three-lens model applies to any
  component and maps onto the Chapter 4 layers.
- **Insecure defaults are the norm**: no/weak auth, binding all interfaces, no transport
  encryption, overpowered default accounts, and dangerous features enabled — seen across
  Redis, MongoDB, RabbitMQ, PostgreSQL, Memcached, and others. Assume it, verify it, fix it.
- The defaults are bad for structural reasons (pre-hostile-internet design, convenience-driven
  adoption, invisible dev trust boundary, backward compatibility) — which makes the next
  component's failings predictable.
- **Intermediaries (proxies, caches, brokers) concentrate risk**; their compromise is
  transitive, so central components deserve the most controls and unnecessary centralization
  is itself a risk.
- **Loopback binds are a genuine but fragile control** — they make System A's weak defaults
  survivable and vanish on migration, which is why System B must re-provide each property
  deliberately (auth, TLS, SG isolation, managed identity).
- **Classify data before storing it**; the blast radius follows sensitivity (public cache vs.
  session tokens vs. the customer table).
- The universal defensive checklist: authenticate every connection, isolate at the network,
  encrypt in transit, least-privilege each component's own model, disable dangerous features,
  minimize/classify stored data, audit and monitor, and guard intermediaries' secrets.

---

## 18. Knowledge Check

1. Name the three lenses and one question each asks. (§3)
2. Give four insecure defaults common across infrastructure software. (§4.7)
3. Why is `trust` in `pg_hba.conf` dangerous, and what should replace it? (§4.2)
4. What are the three preconditions for the Redis `CONFIG` RCE? (§4.4, §8)
5. Why is a TLS-terminating proxy compromise worse than an app-instance compromise? (§5.1)
6. What single control makes System A's weak data-store defaults survivable, and why is it
   fragile? (§7)
7. What is NoSQL injection via type confusion, and how does it relate to Chapter 4's injection
   model? (§4.3)
8. Why is "it's on a private network" insufficient justification for skipping auth/TLS? (§5, §9)
9. What changes and what stays the same when moving a data store from VPS to a managed cloud
   service? (§7, §12)
10. What does "classify before you cache" mean, and give an example of the difference it makes.
    (§4.4, §5.1)

---

## 19. Further Exploration

- Read the "Security" chapter of the official docs for PostgreSQL, Redis, MongoDB, and
  RabbitMQ. Notice how much of each is "turn on the things that are off by default."
- The Redis security page and the history of `protected-mode` — a case study in a vendor
  retrofitting safety onto a convenience default.
- Shodan (shodan.io): search for exposed Redis/Mongo/Elasticsearch (read-only; do not
  connect). Seeing the sheer count of exposed instances makes the point permanently.
- Run the three-lens audit (§6) on every data store you are responsible for this week.
- PortSwigger's NoSQL injection labs (free) for hands-on §4.3.
- For the intermediary problem, read a real post-mortem of a reverse-proxy or cache breach and
  trace the blast radius through the components.

---

## Solutions

### 5.1
The three lenses: **process** (which user, root or not, blast radius on compromise, syscalls/
capabilities), **network service** (bind address, authentication required, transport
encryption, reachability), **data custodian** (what data and its sensitivity, the component's
own auth/role model, encryption at rest). Applied to **Kafka**: process — runs as a service
user, JVM, holds messages on disk; check it is non-root. Network — brokers listen on 9092;
check SASL/mTLS authentication is enabled (Kafka defaults to no auth), and TLS (`ssl`
listeners) is configured; ZooKeeper/KRaft controllers are a sensitive control channel to
isolate. Data custodian — topics hold event payloads (classify them), ACLs control per-topic
produce/consume (enable authorization, which is off by default), and disk data is at-rest
material. The findings you would expect on defaults: no authentication, PLAINTEXT listeners,
no ACLs — the same five issues as every other component.

### 5.2
Reasons: the software often predates or assumes a trusted network; vendors optimize the
first-five-minutes developer experience to drive adoption; the trust boundary is invisible in
loopback-only development; and backward compatibility freezes bad defaults because changing
them breaks the install base. Predicting a new store's posture from this: assume it binds
broadly or at least does not authenticate by default, ships with a powerful default/admin
account or no access control, and does not encrypt in transit — because those are the choices
that maximize the easy first experience. Verify by reading the security docs first; you will
usually find the hardening steps are "enable auth, restrict the bind, turn on TLS, scope the
default account, disable dangerous features" — the universal checklist.

### 5.3
An application instance holds its own data and permissions; compromising it yields the blast
radius of that one process (its memory, its DB credentials, its scope). A TLS-terminating
proxy sits at Chapter 4 Stop 5 and sees *every* request and response in plaintext for *every*
user and *every* backend behind it, plus it holds the TLS private keys. So its compromise is
transitive: the attacker can read all traffic (credentials, tokens, PII in transit), tamper
with responses, and impersonate the site with the stolen keys. In blast-radius terms, the
proxy is a shared, central node through which all data flows, so its blast radius is the union
of everything it fronts — orders of magnitude larger than one leaf. This is why central
intermediaries get the most controls and why key protection on the proxy is critical.

### 5.4
It is *more* secure than an exposed Redis, but not *secure*. For: the loopback bind means no
network attacker can reach it; the kernel enforces this regardless of any firewall (Chapter 3
§4.4). Against: "no password" means *any local process, as any user that can reach loopback*
can fully control Redis — read all sessions/cache, and (if CONFIG is enabled) achieve RCE. A
compromise of *any other service on the host* (the app, a sidecar, a cron job) pivots
instantly into Redis. The defense-in-depth answer: bind to loopback/private *and* set
`requirepass`/ACLs *and* disable `CONFIG`/`MODULE` *and* classify what you store — so that no
single failure (a bind change, a local compromise) is catastrophic. The bind reduces the
attack surface; auth and feature-disabling bound the damage if the surface is reached.

### 5.5
Mechanism: `CONFIG SET dir /path` changes Redis's working directory; `CONFIG SET dbfilename
name` sets the RDB dump filename; setting a key to attacker-controlled content and calling
`SAVE` writes an RDB file to `/path/name` whose contents include the attacker's value. If the
path/filename target an executable location — `~/.ssh/authorized_keys`, a cron directory, a
web root — the written file becomes code execution. Three preconditions: (1) **reachable** —
the attacker can connect to Redis; (2) **unauthenticated (or auth bypassed)** — commands are
accepted; (3) **`CONFIG` (and `SAVE`) enabled** — the primitive is available, and the redis
user can write to the target path. Remove any one: restrict the bind/network → not reachable;
set `requirepass`/ACL → not authenticated; `rename-command CONFIG ""` or run read-only → no
primitive; run redis as a user with no write access to sensitive paths → the write fails.
Defense in depth means removing several.

### 5.6
On the VPS, PostgreSQL was bound to loopback, so the app→DB traffic never traversed a network
at all — it stayed within the host over loopback, unreachable by any network attacker, so its
being plaintext did not matter (there was no wire to sniff). After migrating to a networked
host, the query and results now cross an actual network between the app and the DB, and
without TLS they are readable by any on-path attacker (Chapter 4 Stop 4 applied to the app→DB
hop). Nothing in the app changed because the *code* did not change — the *topology* did, moving
a hop from loopback to the network and thereby exposing a property (confidentiality of DB
traffic) that loopback had implicitly provided. Fix: enable `ssl = on` on PostgreSQL and
connect with `sslmode=verify-full` (also authenticating the server against a known CA), plus
restrict the network path with a security group. This is the canonical "property provided by
loopback silently lost on migration" case (Chapter 4 §7).

### 5.7
On the component model, Redis is a *data custodian* shared across tenants, and the symptom —
one tenant seeing another's data, with correct per-request app code — points to the cache
*keying*, not the app logic. Most likely cause: cache keys that omit the tenant/user
discriminator, so tenant B's request computes the same key as tenant A's earlier request and
gets A's cached value (a key collision across tenants). Distinguishing evidence: it is
repeatable for the same key, occurs only on cacheable endpoints, and disappears when the cache
is flushed. Fix: include the tenant id (and user id where appropriate) in every cache key, and
consider per-tenant key namespaces or separate logical databases/instances for
high-sensitivity tenants to bound the blast radius. This is the same "shared state across
requests" lesson as Chapter 1 §8/1.8 and Chapter 4 §Solutions 4.6, at the cache layer.

### 5.8
The missing control is RabbitMQ's per-vhost/per-resource permission model — service B's user
has been granted read on resources it should not, or all services share one over-permissioned
user. Correct scoping: give each service its own broker user; grant `configure`/`write`/`read`
permissions matched by regex to only that service's own exchanges and queues (e.g. service B's
user has `read` only on `^svcB\.` queues and `write` only on `^svcB\.` exchanges), and place
services in separate vhosts if stronger isolation is needed. Verify with
`rabbitmqctl list_permissions -p <vhost>`. This is least privilege applied to the messaging
layer — the same principle as scoped DB roles and IAM policies — and it bounds a compromised
consumer to its own queues.

### 5.9
Priority by exploitability × blast radius: (1) **Change/disable all default and weak
credentials immediately** (RabbitMQ guest, DB passwords, any admin UI) — these are trivially
exploitable by automated scanners and require no skill; highest exploitability. (2) **Restrict
network reachability** — move the stores off the broad internal network to a segment reachable
only by the app tier (security groups/firewall), so even un-hardened services are not exposed
while you work; this bounds blast radius fast. (3) **Scope the application's data-store
privileges** (DB role least privilege, Redis ACLs, RabbitMQ per-vhost perms) so an app-tier
compromise cannot touch everything. (4) **Enable transport encryption** on each hop. (5)
**Disable dangerous features** (Redis CONFIG/MODULE). (6) **Turn on logging/monitoring** to
detect exploitation of anything not yet fixed. The order front-loads the changes that stop the
most likely attack (default creds + reachability) with the least effort, then works down to
harder, deeper controls.

### 5.10
Data classification: decrypted PII is high-sensitivity; Redis is an in-memory, often
plaintext, sometimes shared, highly-targeted store whose compromise exposes everything it
holds (§5.1). Blast-radius reasoning: caching decrypted PII means a Redis compromise (or a
memory read, or a `DUMP`/`DEBUG`, or a leaked backup) exposes PII for every cached user at
once — converting a performance optimization into a mass-disclosure liability. What I would
allow instead: cache a *non-sensitive projection* (e.g. a display name and an opaque id, not
the SSN/DOB); or cache the PII *encrypted at the application layer* with a key held only by the
app (so Redis holds ciphertext and its compromise leaks nothing usable); or cache only for the
shortest viable TTL and never persist; and require that Redis itself is authenticated, TLS-
protected, network-isolated, and not shared across trust boundaries. The default answer to
"cache decrypted PII" is no — cache a reference or ciphertext, not the plaintext.

### 5.11
Hop by hop: **Internet → ALB** (only public component, SG allows 443 from anywhere). **ALB →
ECS app** (app in private subnet, SG allows the app port only from the ALB's SG; no public
IP). **App → RDS** (RDS in an isolated/private subnet, SG allows 5432 only from the app task
SG, TLS required, app connects as a least-privileged role or via IAM auth). **App →
ElastiCache** (private subnet, SG from app SG only, AUTH + TLS). **App → SQS/secrets** (via
IAM, no network path to the internet needed if using VPC endpoints). For the DB to be reached
directly, multiple independent controls must fail together: RDS would need a public subnet
*and* a public IP *and* an SG opened beyond the app SG *and* a route to an internet gateway —
plus the app's least-privileged role limits what a compromised app can do even *with* access.
The design ensures no single misconfiguration exposes the data, and that an app-tier
compromise is bounded by the app's DB privileges rather than being total.

### 5.12
Shared single Redis/DB — for: lower cost, simpler operations, easier cross-tenant analytics,
efficient resource use. Against: the blast radius is *all tenants* — one compromise, one
noisy-neighbor DoS, one key-collision bug (§Solutions 5.7), or one over-broad query exposes
everyone; isolation is purely logical and depends on application correctness (Chapter 1 §5.4).
Per-tenant instances — for: hard blast-radius boundaries (a compromise is one tenant), simpler
compliance/data-residency, independent scaling and noisy-neighbor isolation. Against: much
higher cost and operational complexity (thousands of instances), harder cross-tenant
operations, resource waste for small tenants. What I would choose: a *tiered* approach — shared
infrastructure with strong logical isolation (tenant-scoped keys, row-level security, scoped
credentials) for the majority of small tenants, and dedicated instances for large or
high-sensitivity/regulated tenants who justify the cost. Change my mind toward more isolation
if the data is highly regulated, if tenants are mutual competitors/adversaries, or after any
cross-tenant incident; toward more sharing if cost pressure is severe and the data
sensitivity is low. State the isolation rung explicitly and match it to the data.

### 5.13
Expected shape: iterate over data-store containers, and for each output process user
(`docker exec <c> ps -o user= -p 1` or inspect), published/bind ports
(`docker inspect --format '{{.NetworkSettings.Ports}}'` and `ss` inside), auth test (attempt
an unauthenticated command: `redis-cli ping`, `psql` without password, RabbitMQ guest curl),
and dangerous-feature reachability (`redis-cli config get dir`, Mongo `db.runCommand` js).
Produce a table: `component | user | bind/published | auth_required | dangerous_reachable |
findings`. Real-world refinement: run non-destructive checks only, flag any `0.0.0.0`/
published port, any successful unauthenticated command, and any reachable RCE primitive; emit
exit code non-zero if any finding so it can gate CI (Chapter 91's policy-as-code idea applied
to runtime posture).

### 5.14
Expected: create the role and grants —
```sql
CREATE ROLE app LOGIN PASSWORD '...';
GRANT SELECT, INSERT, UPDATE ON accounts, transactions, users TO app;
-- deliberately NO DELETE, NO DDL, NO grant on other tables
```
Connect as `app` and demonstrate: `DROP TABLE accounts;` fails with "must be owner" /
permission denied; `DELETE FROM accounts;` fails (no DELETE privilege); `SELECT * FROM
some_other_table;` fails (no privilege on that table); while `SELECT/INSERT/UPDATE` on the
three granted tables succeed. The lesson: a SQL injection or logic bug in an app connected as
`app` cannot drop tables, cannot delete rows, and cannot read tables outside its grant —
least privilege bounding the blast radius (Chapter 4 Stop 7). Note that the role should also
not be the table *owner* (owners can DROP regardless of grants).

### 5.15
Expected: enable TLS (`ssl=on`, provide `server.crt`/`server.key`), then
`psql "host=... sslmode=verify-full sslrootcert=ca.crt dbname=... user=..."` connects and, via
`\conninfo` or `SELECT ssl_is_used()`, confirms SSL is in use; a `tcpdump -A -n port 5432` on
that connection shows only TLS records, no readable SQL. Then connect with `sslmode=disable`
and run a query; the same `tcpdump` now shows the query text (`SELECT ... WHERE ...`) and
results in plaintext on the wire. The contrast demonstrates that (a) without TLS, DB traffic
is fully readable by an on-path attacker, and (b) `verify-full` additionally authenticates the
server (rejecting a MITM presenting a different cert), which `sslmode=require` alone does not.
This is Chapter 4 Stop 4 proven on the app→DB hop.

### 5.16
Redis defaulted to no authentication and (in older packages) a broad bind, on the 2009
assumption of a trusted network. So an exposed instance accepts commands from anyone. From
there: Redis commands include `CONFIG SET dir`/`dbfilename` and `SAVE`, which let a client
make Redis write an arbitrary file to an arbitrary path (RDB persistence, repurposed); pointing
that at `~/.ssh/authorized_keys`, a cron directory, or a web root turns "I can talk to your
cache" into "I run code as the redis user on your host." `MODULE LOAD` and `REPLICAOF` are
further RCE vectors. The result was mass, automated compromise of internet-exposed instances.
The fixes trace the chain: `protected-mode` and `requirepass`/ACLs (block unauthenticated
access), private binds and firewalls (block reachability), and `rename-command`/read-only
(remove the primitive) — and the deeper lesson is that convenience defaults meeting a hostile
network is a recurring, predictable failure, not a Redis-specific bug.

### 5.17
Use the three-lens model as a method. **Process:** which OS user runs it (root?), its blast
radius, whether OS-level access bypasses the DB permission model. **Network service:** bind
address (`ss -tlpn`), whether authentication is required (attempt a no-credential connect),
whether TLS is enabled, and reachability (who on the network can connect — SG/firewall/
`pg_hba`). **Data custodian:** what data it holds and its sensitivity; the role/privilege model
(does the app connect as a superuser or a scoped role? `\du`, table grants); encryption at
rest; audit logging. Concretely for PostgreSQL: read `pg_hba.conf` for `trust`/`0.0.0.0`/`md5`
findings, list roles and grants, check `ssl`, check `log_statement`/`pgaudit`, verify the app
role is least-privileged and not the owner. Deliverable: a findings table with each issue's
blast radius and a prioritized remediation list — the §7 inventory format.

### 5.18
An application server mostly protects *its own* data and logic. A reverse proxy and a message
broker are *intermediaries*: they sit between components and see or store data belonging to
*everything that flows through them*, so their compromise is transitive and their blast radius
is the union of all they front (§5.1). Specifics: a TLS-terminating proxy holds the private
keys and sees all plaintext, so key protection, TLS policy, header hygiene, and request-parsing
consistency (smuggling) are its security surface, and its config *is* the security policy. A
broker holds message payloads (often sensitive), has a per-vhost/per-resource permission model
that must be scoped so a compromised producer/consumer cannot touch others' queues, and has a
sensitive inter-node channel (the Erlang cookie) that is effectively a cluster root credential.
Both also expose management UIs that are separate network services to protect. In short:
intermediaries concentrate data and trust, so they need the most controls and the tightest
key/credential management.

### 5.19
Connecting as a superuser means any bug — a SQL injection, a logic flaw, a compromised app
process — inherits total control of the database: read/modify/delete *all* data across all
tables, alter schema (`DROP`), create/alter roles, install extensions, read files via
superuser functions, and often reach the OS. The blast radius of any single application
vulnerability becomes "the entire database," removing the last line of defense (Chapter 4 Stop
7). What I would change: create a dedicated application role with only the privileges it needs
— `SELECT/INSERT/UPDATE/DELETE` on precisely the tables it uses, no DDL, not the table owner,
no superuser — and separate roles for read-heavy paths (read-only) and for migrations (a
distinct, tightly-controlled role used only by the deploy pipeline, not the running app). Add
row-level security for tenant isolation. Then a SQL injection is bounded to what that role can
do, turning a total compromise into a contained one.

### 5.20
"Private network" is a weak and often false premise, and even when true it is insufficient.
False: cloud "private" networks still have other tenants' workloads, misconfigurations that
add routes, and lateral movement paths; "internal" traffic frequently traverses shared
infrastructure. Insufficient even if true: the whole point of Zero Trust (Chapter 43) is that
one compromised host inside the network should not yield everything — if services trust each
other with no auth and speak plaintext, a single foothold reads all inter-service traffic and
impersonates any service, turning one bug into total compromise. Concretely: without auth, any
process that reaches the DB/cache/broker controls it; without TLS, any on-path position
(a compromised host, a misrouted packet, a sniffing sidecar) reads credentials and data
(§Solutions 5.6). The correct posture is authenticate and encrypt *every* hop regardless of
network location, treat the network as hostile, and use least privilege — so that network
segmentation is *one* layer of defense in depth, not the only one.

---

*Next: Chapter 6 — Virtualization, Containers, and Cloud: What "a Server" Means Now. We lift
the process/host model of Chapters 1–5 into VMs, containers, and cloud abstractions, closing
Part 0 and setting up the isolation-boundary reasoning that Parts 7–11 depend on.*
