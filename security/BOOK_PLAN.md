# BOOK PLAN — The Cloud Security Engineer's Deep Book

> A ground-up, internals-first engineering textbook for a senior software engineer
> becoming a Cloud Security Engineer.

---

## 0. How this plan was derived

The source roadmap (a general cybersecurity roadmap covering networking, OSI, TCP/IP,
IP/CIDR/subnetting, DNS, DHCP, NAT, VLAN, VPN, routing, switching, HTTP/HTTPS, TLS, SSH,
Linux, Windows, authentication, LDAP, Kerberos, RADIUS, SSO, PKI, cryptography, firewalls,
IDS/IPS, logs, Wireshark, tcpdump, nmap, threat hunting, incident response, vulnerability
management, OWASP, web attacks, malware, Zero Trust, defense in depth, SIEM/SOAR, cloud,
AWS/Azure/GCP, virtualization, frameworks, CTFs, pentesting) was mapped against the
**Cloud Security Engineer** target role. Four decisions were made:

**KEPT AND DEEPENED** — everything a cloud security engineer uses daily:
networking internals, TCP/IP, DNS, TLS/PKI, Linux internals, authentication protocols,
cryptography, logging, OWASP, threat modeling, Zero Trust, firewalls, packet analysis.
These are not summarized; they are taught down to wire format and kernel behavior.

**REORGANIZED** — the roadmap's topic-by-topic ordering is replaced by a
capability-building progression. Networking is not "one chapter"; it is a 24-chapter
part, because the roadmap assumes networking knowledge that a backend engineer does not
have, and because every cloud security control (security groups, NACLs, NetworkPolicy,
service mesh, WAF, VPC endpoints) is a networking control wearing a cloud costume.

**DEMOTED** — subjects belonging to adjacent roles are taught only to the depth a cloud
security engineer needs in order to work *with* those roles:

- SOC analyst workflows → "enough to build detections and respond", not a SOC textbook.
- Malware reverse engineering → concepts and detection implications only.
- Offensive security → attacker modelling and authorized lab work, not a pentest career track.
- Windows/Active Directory → only where it intersects identity and hybrid cloud.
- Azure/GCP → taught as deltas from AWS, since AWS is the primary platform.

**ADDED** (absent from the source roadmap, required by the target role):
application security at code level in the reader's own stack, API/OAuth/OIDC/JWT depth,
IAM as a specialization, Terraform/IaC security, Docker and Kubernetes security,
DevSecOps and software supply chain, cloud network architecture, security architecture
judgment, and AI/LLM security.

---

## 1. The reader

Senior software engineer, ~7 years. Strong in: .NET/ASP.NET Core, C#, Angular, NestJS,
Python, REST, microservices, distributed systems, RabbitMQ, Redis, MongoDB, PostgreSQL,
CQRS, Clean Architecture, DDD, Docker, Linux deployment, Nginx, CI/CD, VPS, some
Kubernetes. Developing: networking fundamentals, operating-system internals below the
process level, cryptography, cloud security controls, offensive reasoning.

Consequences for the book:

- Zero time is spent on programming basics. Code is a teaching instrument, not a tutorial.
- Networking, OS internals, and cryptography get genuine first-principles treatment.
- Every abstraction is grounded in the reader's own stack: an ASP.NET Core API behind
  Nginx talking to PostgreSQL, Redis and RabbitMQ, with an Angular frontend.
- Staff-level reasoning (trade-offs, blast radius, organizational boundaries) appears
  throughout, not saved for a final chapter.

---

## 2. The ten-level teaching contract

Every significant concept is taught through these levels. A chapter that stops at
level 3 is an incomplete chapter and must be rewritten before moving on.

| Level | Question | Typical content |
|---|---|---|
| 1 | What is it? | Plain-language definition with a concrete anchor |
| 2 | Why does it exist? | The problem it solved; what came before it |
| 3 | How does it work? | The mechanism, the algorithm, the state machine |
| 4 | What happens internally? | Kernel, NIC, memory, protocol stack, cloud control plane |
| 5 | What does the data look like? | Hex dumps, packet headers, JWT payloads, JSON policies |
| 6 | Demonstrate it | Runnable commands, code, configuration |
| 7 | Observe it | tcpdump/Wireshark, strace, /proc, logs, devtools, CloudTrail |
| 8 | Break it | The attack, why it works, what assumption it violates |
| 9 | Secure it | The control, why it works, and its residual risk |
| 10 | Production architecture | How it is actually deployed at scale, with trade-offs |

---

## 3. Chapter structure

Chapters generally follow this skeleton, deviating when the material demands it:

1. Why This Matters · 2. Prerequisites · 3. Mental Model · 4. Fundamentals ·
5. Deep Technical Explanation · 6. Internals · 7. Real-World Example ·
8. Hands-On Demonstration · 9. Security Implications · 10. Attack Scenarios ·
11. Defensive Techniques · 12. Production Architecture · 13. Common Mistakes ·
14. Troubleshooting · 15. Practical Lab · 16. Exercises · 17. Interview Questions ·
18. Summary · 19. Knowledge Check · 20. Further Exploration

Exercise **answers are never inline** — they live in a `## Solutions` section at the end
of the chapter, after the exercises and interview questions.

---

## 4. The full curriculum — 140 chapters in 17 parts

### PART 0 — How Modern Systems Actually Work (6 chapters)

Establishes the mental model everything else hangs on. Almost no security yet, by design.

| # | Chapter |
|---|---|
| 01 | The Machine Underneath: CPU, Memory, Storage, and the Illusions They Maintain |
| 02 | The Kernel Boundary: Processes, Threads, System Calls, and Privilege Rings |
| 03 | Files, Descriptors, Sockets, and Ports: How a Program Reaches the World |
| 04 | Anatomy of a Request: Browser to Database, Every Layer Explained |
| 05 | The Building Blocks of Production: Servers, Services, Databases, Caches, Queues, Proxies |
| 06 | Virtualization, Containers, and Cloud: What "a Server" Means Now |

### PART 1 — Networking From First Principles (24 chapters)

The largest foundational part. Assumes nothing.

| # | Chapter |
|---|---|
| 07 | Bits, Bytes, Binary and Hex: Reading Data the Way the Wire Sees It |
| 08 | Layer 2: MAC Addresses, Ethernet Frames, NICs, Switches, Broadcast Domains |
| 09 | ARP: The Glue Between Layer 2 and Layer 3, and How It Is Poisoned |
| 10 | IPv4 Addressing, Subnet Masks, CIDR, and Subnetting Without a Calculator |
| 11 | IPv6: Addressing, SLAAC, NDP, and the Security Surprises |
| 12 | Routing: Tables, Default Gateways, Longest-Prefix Match, and the Journey of a Packet |
| 13 | Switching, VLANs, Trunks, and Layer 2 Segmentation |
| 14 | NAT and PAT: Translation, Connection Tables, and Why NAT Is Not a Firewall |
| 15 | DHCP: Bootstrapping Identity on a Network, and DHCP Attacks |
| 16 | DNS Part 1: Resolution, Records, Delegation, Caching, and the Root |
| 17 | DNS Part 2: DoH/DoT, DNSSEC, Poisoning, Rebinding, Exfiltration, and Cloud DNS |
| 18 | UDP: Connectionless Transport and the Protocols Built On It |
| 19 | TCP Part 1: State Machine, Handshake, Sequence Numbers, Teardown, RST, TIME_WAIT |
| 20 | TCP Part 2: Retransmission, Flow Control, Congestion Control, and Performance |
| 21 | Sockets, Ports, Ephemeral Ranges, and the Kernel's Connection Tables |
| 22 | MTU, Fragmentation, Path MTU Discovery, and the Bugs They Cause |
| 23 | ICMP, Ping, and Traceroute: Diagnostics and Their Abuse |
| 24 | Packet Analysis Workshop: tcpdump, Wireshark, and BPF Filters |
| 25 | Cryptography Part 1: Symmetric Encryption, Modes, Hashes, MACs, and Randomness |
| 26 | Cryptography Part 2: Asymmetric Keys, Signatures, Key Exchange, Forward Secrecy |
| 27 | PKI and X.509: Certificates, CAs, Chains, Revocation, Certificate Transparency |
| 28 | TLS Byte by Byte: 1.2 vs 1.3 Handshakes, Key Schedule, Cipher Suites, mTLS, SNI |
| 29 | HTTP/1.1, HTTP/2, HTTP/3: Semantics, Framing, Multiplexing, Security Differences |
| 30 | SSH Internals: Transport, Authentication, Channels, Tunnels, and Key Hygiene |

### PART 2 — Linux Deep Dive for Security Engineers (8 chapters)

| # | Chapter |
|---|---|
| 31 | Boot to Login: Firmware, Bootloader, Kernel, init, systemd, and the Process Tree |
| 32 | The Filesystem as an Interface: Mounts, Devices, /proc, /sys, and Kernel State |
| 33 | Users, Groups, Permissions, setuid, ACLs, and Linux Capabilities |
| 34 | Shell, Environment, PATH, and the Attack Surface of Convenience |
| 35 | systemd, Services, Timers, and Cron: Running Code, and Persisting as an Attacker |
| 36 | Logs, journald, auditd, and Building a Trustworthy Record |
| 37 | Linux Networking Internals: netfilter, iptables/nftables, conntrack, ss |
| 38 | Isolation Primitives: Namespaces, cgroups, seccomp, AppArmor, SELinux |

### PART 3 — Security Fundamentals (6 chapters)

| # | Chapter |
|---|---|
| 39 | The Vocabulary That Constrains Design: CIA, Authenticity, Accountability, Non-repudiation |
| 40 | Assets, Threats, Actors, Vulnerabilities, Exploits, Risk, and Controls |
| 41 | Trust Boundaries, Attack Surface, Attack Paths, and Blast Radius |
| 42 | Threat Modeling in Practice: Data Flow Diagrams, STRIDE, and Abuse Cases |
| 43 | Defense in Depth, Least Privilege, Segmentation, and Zero Trust |
| 44 | Vulnerability Management, Hardening, Patching, Backups, and Resilience |

### PART 4 — Application Security (14 chapters)

The largest applied part. Taught in ASP.NET Core, NestJS, Angular, PostgreSQL, MongoDB, Redis.

| # | Chapter |
|---|---|
| 45 | How Applications Break: The Five Universal Root Causes |
| 46 | SQL Injection: From String Concatenation to EF Core and Dapper |
| 47 | NoSQL, ORM, and Query-Object Injection: MongoDB, Redis, and LINQ |
| 48 | Cross-Site Scripting: Contexts, Sinks, Angular's Sanitizer, and CSP |
| 49 | CSRF, SameSite, and the Browser's Origin Model |
| 50 | SSRF: The Vulnerability That Owns Cloud Accounts |
| 51 | Broken Access Control: IDOR, BOLA, BFLA, and Multi-Tenancy Failures |
| 52 | Authentication Failures: Password Storage, MFA, Sessions, Enumeration, Reset Flows |
| 53 | Command Injection, Path Traversal, and Unsafe Process Execution |
| 54 | File Upload, Deserialization, XXE, and Dangerous Parsers |
| 55 | Race Conditions, TOCTOU, Idempotency, and Business Logic Flaws |
| 56 | JavaScript-Specific Risks: Prototype Pollution, Supply Chain, and the Browser Bundle |
| 57 | HTTP Request Smuggling, Cache Poisoning, and Intermediary Disagreement |
| 58 | Secure-by-Default Application Architecture in ASP.NET Core and NestJS |

### PART 5 — API Security (6 chapters)

| # | Chapter |
|---|---|
| 59 | The HTTP Security Model: Headers, Cookies, CORS, and Origins |
| 60 | Sessions, Tokens, and JWT Internals: Signing, Validation, and the Classic Bugs |
| 61 | OAuth 2.0 and OpenID Connect: Every Flow, PKCE, and What Each Token Is For |
| 62 | Enterprise Identity Protocols: SAML, LDAP, Kerberos, RADIUS |
| 63 | Authorization at API Scale: RBAC, ABAC, ReBAC, and Policy Engines |
| 64 | Gateways, Rate Limiting, WAF, mTLS, and Service-to-Service Authentication |

### PART 6 — Identity and Access Management (6 chapters)

| # | Chapter |
|---|---|
| 65 | Identity as the Perimeter: Principals, Credentials, Assertions, and Trust |
| 66 | Human Identity: Directories, SSO, MFA, Federation, and Lifecycle |
| 67 | Machine Identity: Service Accounts, Workload Identity, SPIFFE, Instance Metadata |
| 68 | Secrets Management: Storage, Distribution, Rotation, and Leak Response |
| 69 | Privileged Access: PAM, JIT, JEA, Break-Glass, and Separation of Duties |
| 70 | IAM Attack Paths: Escalation, Token Theft, Confused Deputy, and Graph Analysis |

### PART 7 — AWS (12 chapters)

| # | Chapter |
|---|---|
| 71 | AWS Architecture: Accounts, Regions, AZs, the Control Plane, and SigV4 |
| 72 | AWS IAM Part 1: Principals, Policy Documents, and the Evaluation Algorithm |
| 73 | AWS IAM Part 2: Roles, STS, AssumeRole, Trust Policies, Boundaries, SCPs |
| 74 | Organizations, Multi-Account Strategy, and Landing Zones |
| 75 | VPC Fundamentals: Subnets, Route Tables, IGW, NAT, ENIs, and the SDN Underneath |
| 76 | Security Groups and NACLs: Stateful vs Stateless, and How Evaluation Really Works |
| 77 | VPC Endpoints, PrivateLink, Peering, Transit Gateway, and Hybrid Connectivity |
| 78 | EC2 Security: AMIs, IMDSv2, EBS, SSM, User Data, and Host Hardening |
| 79 | S3 Deep Dive: The Permission Model, Encryption, and the Anatomy of a Public Bucket |
| 80 | KMS and Encryption: Envelope Encryption, Key Policies, Grants, Cross-Account Keys |
| 81 | Compute Services: Lambda, ECS, and EKS Security Models |
| 82 | Detection and Governance: CloudTrail, Config, GuardDuty, Security Hub, Inspector, Macie |

### PART 8 — Cloud Network Security (5 chapters)

| # | Chapter |
|---|---|
| 83 | Designing a Secure VPC: Tiering, Multi-AZ, and Controlled Egress |
| 84 | The Packet's Journey: Route53 → CloudFront → WAF → ALB → ECS → RDS |
| 85 | Edge Security: CDN, WAF Rules, DDoS, TLS Termination, and Origin Protection |
| 86 | East-West Security: Microsegmentation, Service Mesh, and Private DNS |
| 87 | Zero Trust Network Architecture in the Cloud |

### PART 9 — Terraform and IaC Security (5 chapters)

| # | Chapter |
|---|---|
| 88 | Terraform Mechanics: Providers, Resources, the Graph, Plan/Apply, and State |
| 89 | Modules, Environments, and Secure Project Structure |
| 90 | State Security, Secrets, and Credentials in IaC Pipelines |
| 91 | Policy as Code: Checkov, tfsec, OPA/Conftest, and Guardrail Design |
| 92 | Building a Secure-by-Default Platform: Paved-Road Modules |

### PART 10 — Docker and Container Security (6 chapters)

| # | Chapter |
|---|---|
| 93 | What a Container Actually Is: Namespaces, cgroups, and the OCI Image Format |
| 94 | Dockerfiles, Layers, Registries, and Build-Time Security |
| 95 | Runtime Security: Non-Root, Capabilities, Read-Only Filesystems, seccomp |
| 96 | Container Escape: Privileged Mode, the Docker Socket, and Kernel Boundaries |
| 97 | Image Supply Chain: Scanning, SBOM, Signing, and Provenance |
| 98 | Compose, Local Development, and the Gap Between Dev and Production |

### PART 11 — Kubernetes Security (10 chapters)

| # | Chapter |
|---|---|
| 99 | Kubernetes Architecture: Control Plane, etcd, kubelet, and Reconciliation |
| 100 | The API Server Request Lifecycle: Authentication, Authorization, Admission |
| 101 | Kubernetes RBAC in Depth |
| 102 | Pods, Workloads, and ServiceAccounts: Identity Inside the Cluster |
| 103 | Kubernetes Networking: CNI, Services, kube-proxy, Ingress, and CoreDNS |
| 104 | NetworkPolicy and Cluster Segmentation |
| 105 | Pod Security Standards, Admission Policy, Kyverno, and Gatekeeper |
| 106 | Secrets in Kubernetes and External Secret Systems |
| 107 | Runtime Security and Detection: Audit Logs, Falco, and eBPF Tooling |
| 108 | Multi-Tenancy, Cluster Hardening, and EKS Specifics (IRSA, Pod Identity) |

### PART 12 — DevSecOps (7 chapters)

| # | Chapter |
|---|---|
| 109 | The Secure SDLC and the Shape of a Modern Pipeline |
| 110 | Source Control Security: Branch Protection, Signed Commits, Secret Scanning |
| 111 | SAST, DAST, and IAST: Mechanics, Limits, and Not Drowning in Findings |
| 112 | SCA and the Dependency Graph: CVEs, VEX, Reachability, and Patch Strategy |
| 113 | Artifact Signing, SBOM, SLSA, and Provenance |
| 114 | CI/CD Pipeline Security: Runners, OIDC Federation, Isolation, and PPE Attacks |
| 115 | The Complete Pipeline: A Working Reference Implementation |

### PART 13 — Logging, Detection, and SIEM (6 chapters)

| # | Chapter |
|---|---|
| 116 | Logging Architecture: What to Log, Where It Goes, and How Not to Lose It |
| 117 | Cloud Audit Logs: CloudTrail Events Field by Field |
| 118 | Detection Engineering: From Hypothesis to Rule to Tuned Alert |
| 119 | SIEM and SOAR Mechanics: Sentinel, Splunk, and OpenSearch Concepts |
| 120 | Endpoint, Network, and Container Telemetry |
| 121 | Incident Response for Cloud Engineers |

### PART 14 — Offensive Security (6 chapters)

| # | Chapter |
|---|---|
| 122 | The Attacker's Workflow: Kill Chain and MITRE ATT&CK |
| 123 | Reconnaissance and Scanning: Nmap From Packets Up |
| 124 | Web Exploitation with Burp Suite |
| 125 | Credential Attacks, Cracking, and Lateral Movement |
| 126 | Cloud Penetration Testing: AWS Attack Paths |
| 127 | Building a Legal Home Lab and Practicing Deliberately |

### PART 15 — Security Architecture (6 chapters)

| # | Chapter |
|---|---|
| 128 | The Architect's Toolkit: Requirements, Constraints, and Trade-offs |
| 129 | Reference Architectures: Secure Web Platform and Secure Data Platform |
| 130 | Encryption and Key Management Architecture |
| 131 | Resilience, Disaster Recovery, and Security During Failure |
| 132 | Governance, Compliance, and Security at Organizational Scale |
| 133 | Architecture Review Workshop: Three Systems Torn Apart |

### PART 16 — AI and LLM Security (7 chapters)

| # | Chapter |
|---|---|
| 134 | How LLMs Actually Work: Tokens, Inference, Context, and Embeddings |
| 135 | LLM Application Architecture: RAG, Agents, Tool Calling, and MCP |
| 136 | Prompt Injection: Direct, Indirect, and Why There Is No Complete Fix |
| 137 | RAG and Vector Database Security |
| 138 | Agent Security: Excessive Agency, Tool Poisoning, and Sandboxing |
| 139 | AI Supply Chain, Model Security, and Data Governance |
| 140 | AI Red Teaming, Guardrails, and Production Monitoring |

---

## 5. Capstone projects

Placed at part boundaries, each building on the last. All live in `capstones/`.

| Project | After Part | Title |
|---|---|---|
| 1 | 2 | Harden a Linux server and prove it |
| 2 | 4 | Build and attack a deliberately vulnerable ASP.NET Core API |
| 3 | 5 | Implement OAuth2/OIDC end to end with Angular + ASP.NET Core |
| 4 | 7 | Build a least-privilege multi-account AWS foundation |
| 5 | 8 | Design and deploy a secure three-tier VPC architecture |
| 6 | 9 | Codify the whole platform in Terraform with policy gates |
| 7 | 10 | Containerize and harden the application with a signed supply chain |
| 8 | 11 | Deploy to Kubernetes with RBAC, NetworkPolicy, and workload identity |
| 9 | 12 | Build a complete DevSecOps pipeline |
| 10 | 13 | Centralized detection and an incident response runbook |
| 11 | 15 | Threat-model the entire platform |
| Final | 16 | Design and secure a production-grade fintech cloud platform, AI features included |

---

## 6. Recurring reference systems

Three systems recur across the entire book so examples compound instead of resetting.

**System A — "Ledger" (the reader's stack, on a VPS)**

```
Angular SPA --> Nginx --> ASP.NET Core API --> PostgreSQL
                             |--> Redis (cache + sessions)
                             |--> RabbitMQ --> .NET Worker
```

**System B — "Ledger on AWS" (the same system, cloud-native)**

```
Route53 --> CloudFront --> WAF --> ALB --> ECS Fargate --> RDS PostgreSQL
                                              |--> ElastiCache
                                              |--> SQS/EventBridge --> Lambda
```

**System C — "Ledger at scale" (Kubernetes, multi-account, AI-enabled)**

```
Route53 --> CloudFront --> WAF --> ALB --> EKS (microservices, service mesh)
                                              |--> Kafka / RabbitMQ
                                              |--> Aurora / DynamoDB
                                              |--> Vector DB + LLM gateway
```

Each part asks of these systems: *what can go wrong, why, how would I detect it,
how do I prevent it, and what is the blast radius when prevention fails?*

---

## 7. Conventions

- Insecure code always carries the banner
  `// ===== INTENTIONALLY VULNERABLE EXAMPLE =====`
  and is always followed by the secure version plus an explanation of the fix.
- Commands are shown with expected output wherever the output carries meaning.
- Diagrams are ASCII and are explained step-by-step underneath.
- Cross-references use the form `(see Chapter 19, TCP Part 1)`.
- Terms bolded on first use are destined for `GLOSSARY.md`.
- Every lab is registered in `LAB_INDEX.md`.
- Exercise solutions live at the end of the chapter, never inline.
- Chapter files are named `Chapter-NN-slug.md` inside their part directory.
