# The Cloud Security Engineer's Deep Book

A from-first-principles engineering textbook that takes a senior software engineer to
genuine competence as a **Cloud Security Engineer**, and onward toward Security /
Cloud Security Architect work.

This is not a certification guide, not a glossary of terms, and not a survey course.
It is an internals book: it explains how things actually work, at the level of packets,
kernel structures, policy evaluation algorithms, and control-plane behavior — and then
explains how they break and how they are defended.

---

## Who this is written for

A backend/full-stack engineer with roughly seven years of experience in .NET, C#,
Angular, NestJS, Python, PostgreSQL, MongoDB, Redis, RabbitMQ, Docker and Linux
deployment, who wants to convert that engineering background into a security
specialization rather than starting over as a beginner.

If you already know what a class, an HTTP request, or a Docker image is, this book will
not waste your time re-teaching it. If you have never watched a TCP handshake in
Wireshark or read an IAM policy evaluation trace, it will slow down and go all the way
to the bottom.

---

## How the book is organized

| Part | Directory | Focus |
|---|---|---|
| 0 | `Part-00-Foundations/` | How modern systems actually work |
| 1 | `Part-01-Networking/` | Networking from first principles (24 chapters) |
| 2 | `Part-02-Linux/` | Linux internals for security engineers |
| 3 | `Part-03-Security-Fundamentals/` | The security mental model |
| 4 | `Part-04-Application-Security/` | AppSec in your own stack |
| 5 | `Part-05-API-Security/` | HTTP, JWT, OAuth2, OIDC, authorization |
| 6 | `Part-06-IAM/` | Identity as a specialization |
| 7 | `Part-07-AWS/` | AWS, the primary cloud platform |
| 8 | `Part-08-Cloud-Network-Security/` | Cloud network architecture |
| 9 | `Part-09-Terraform-IaC/` | Infrastructure as code and its security |
| 10 | `Part-10-Docker/` | Containers, deeply |
| 11 | `Part-11-Kubernetes/` | Kubernetes security |
| 12 | `Part-12-DevSecOps/` | Pipeline and supply-chain security |
| 13 | `Part-13-Detection-SIEM/` | Logging, detection engineering, IR |
| 14 | `Part-14-Offensive-Security/` | Attacker thinking, authorized labs |
| 15 | `Part-15-Security-Architecture/` | Judgment, trade-offs, architecture |
| 16 | `Part-16-AI-Security/` | AI/LLM security |

Supporting files:

| File | Purpose |
|---|---|
| `BOOK_PLAN.md` | The full 140-chapter curriculum and the reasoning behind it |
| `BOOK_PROGRESS.md` | Live state: what is written, what is next, decisions made |
| `GLOSSARY.md` | Every important term, with why it matters and where it appears |
| `LAB_INDEX.md` | Every hands-on lab, with its prerequisites and environment |
| `ARCHITECTURE_CASE_STUDIES.md` | The recurring reference systems, torn apart repeatedly |
| `capstones/` | Progressively harder end-to-end projects |
| `labs/` | Lab scaffolding: compose files, scripts, sample apps |

---

## How to read it

**Sequentially, for the first pass.** The book is built as a dependency graph, not a
reference manual. Chapter 76 (Security Groups vs NACLs) assumes Chapter 19 (TCP state
machine) because "stateful firewall" is meaningless without connection state. Chapter
104 (NetworkPolicy) assumes Chapter 37 (netfilter) because that is what implements it.

**With a terminal open.** Nearly every chapter has commands to run and packets to
capture. Reading about a TCP handshake and watching one are different experiences, and
only one of them produces an engineer.

**Slowly.** The book is deliberately large. A chapter is a study session, sometimes two.

---

## The lab environment

Most labs need only what you already have:

- A Linux VM or WSL2 (Ubuntu 22.04+ assumed)
- Docker and Docker Compose
- .NET SDK, Node.js, Python 3
- Wireshark and tcpdump
- Later parts: kind or minikube, Terraform, an AWS account (free tier where possible)

Every lab states its prerequisites, expected output, and cleanup steps. Anything that
costs money says so before you run it.

---

## Ground rules for the offensive material

Attack techniques in this book exist to make defenses comprehensible — you cannot design
a control against a mechanism you do not understand. All offensive work is scoped to:

- systems you own,
- deliberately vulnerable applications shipped for training,
- legal practice platforms (TryHackMe, Hack The Box, PortSwigger Web Security Academy),
- and authorized engagements.

Vulnerable code is always labeled `INTENTIONALLY VULNERABLE EXAMPLE` and is always
followed by a corrected version.

---

## The recurring question

Every technology in this book is interrogated the same way:

1. What can go wrong?
2. Why can it go wrong?
3. How would an attacker exploit it?
4. Which assumption is being violated?
5. How would I detect it?
6. How would I prevent it?
7. What happens when prevention fails?
8. How do I limit the blast radius?
9. How do I recover?

By the end, that sequence should run automatically in your head when you look at any
architecture diagram. That reflex — not a list of tools — is what the job actually is.
