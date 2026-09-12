# The System Architect's Map

**A practical book for developers who want to become System / Solution Architects.**

Written in easy English. Every topic explains *what problem it solves* before *how it works*.

---

## Why this book exists

Most learning material has one of two problems:

1. **Too shallow** — you learn buzzwords, but when a real system is put in front of you, you freeze.
2. **Too deep, too early** — you spend three months on Kafka internals and still cannot draw a system diagram.

This book takes the middle path, which is the **architect's path**:

> "When someone puts a new system in front of me, I should never think *'I have never even heard of this.'*
> I should recognise the vocabulary, understand what problem it solves, know where it fits —
> and then learn the production details when the situation requires it."

So this book gives you the **map of the territory**, with enough depth in each area that you can:

- Speak the language confidently in a meeting
- Ask the right questions in a design review
- Know which trade-off you are making, and why
- Know exactly *where to dig deeper* when a project demands it

---

## How to read this book

Each topic is marked with a depth badge:

| Badge | Meaning | What you should be able to do |
|-------|---------|-------------------------------|
| 🟢 | **Know deeply** | Use it, debug it, teach it, defend the choice |
| 🟡 | **Understand concept + when/why** | Explain it on a whiteboard, know the trade-offs, pick it correctly |
| ⚪ | **Awareness is enough** | Recognise the word, know which family it belongs to, know where to look it up |

**Do not** try to turn every ⚪ into a 🟢. That is how people burn out and never become architects.

### Reading orders

**If you are a working developer (recommended):**
`00 → 01 → 02 → 04 → 05 → 08 → 09 → 11 → 22` then the rest in any order.

**If you have a system design interview soon:**
`04 → 05 → 09 → 10 → 11 → 06 → 08 → 13 → 19 → 25`

**If you just got promoted to architect:**
`00 → 22 → 23 → 03 → 24 → 02`

**If you build data platforms:**
`09 → 10 → 12 → 06 → 07 → 24`

---

## Table of contents

### Part I — The Mind of an Architect
| # | Chapter | Depth |
|---|---------|-------|
| 00 | [The Architect Mindset](00-architect-mindset.md) | 🟢 |
| 01 | [Software Engineering Foundations](01-software-engineering-foundations.md) | 🟢 |

### Part II — Shapes of Systems
| # | Chapter | Depth |
|---|---------|-------|
| 02 | [Architecture Styles](02-architecture-styles.md) | 🟢 |
| 03 | [Domain-Driven Design](03-domain-driven-design.md) | 🟢 |

### Part III — Designing at Scale
| # | Chapter | Depth |
|---|---------|-------|
| 04 | [System Design Fundamentals](04-system-design-fundamentals.md) | 🟢 |
| 05 | [Distributed Systems](05-distributed-systems.md) | 🟢 |
| 06 | [Messaging & Event-Driven Architecture](06-messaging-and-event-driven-architecture.md) | 🟢 |
| 07 | [Kafka](07-kafka.md) | 🟡 |
| 08 | [API Architecture](08-api-architecture.md) | 🟢 |

### Part IV — Data
| # | Chapter | Depth |
|---|---------|-------|
| 09 | [Database Architecture (Relational)](09-database-architecture.md) | 🟢 |
| 10 | [NoSQL Architecture](10-nosql-architecture.md) | 🟡 |
| 11 | [Caching](11-caching.md) | 🟢 |
| 12 | [Data Architecture (OLTP, OLAP, Lakehouse)](12-data-architecture.md) | 🟡 |

### Part V — The Ground It Runs On
| # | Chapter | Depth |
|---|---------|-------|
| 13 | [Networking](13-networking.md) | 🟢 |
| 14 | [Cloud Architecture](14-cloud-architecture.md) | 🟡 |
| 15 | [Containers & Kubernetes](15-containers-and-kubernetes.md) | 🟡 |
| 16 | [DevOps & Platform Engineering](16-devops-and-platform-engineering.md) | 🟡 |

### Part VI — Keeping It Alive and Safe
| # | Chapter | Depth |
|---|---------|-------|
| 17 | [Security Architecture](17-security-architecture.md) | 🟢 |
| 18 | [Observability](18-observability.md) | 🟢 |
| 19 | [Reliability & Disaster Recovery](19-reliability-and-disaster-recovery.md) | 🟡 |
| 20 | [Performance Engineering](20-performance-engineering.md) | 🟡 |
| 21 | [Testing Architecture](21-testing-architecture.md) | 🟡 |

### Part VII — The Job Itself
| # | Chapter | Depth |
|---|---------|-------|
| 22 | [Architecture Documentation](22-architecture-documentation.md) | 🟢 |
| 23 | [Architecture Governance](23-architecture-governance.md) | 🟢 |
| 24 | [Integration Architecture](24-integration-architecture.md) | 🟢 |

### Part VIII — Putting It All Together
| # | Chapter | Depth |
|---|---------|-------|
| 25 | [Capstone: Six Systems Designed End-to-End](25-capstone-case-studies.md) | 🟢 |

### Appendices
- [A. Glossary — every term in this book, one line each](appendix-a-glossary.md)
- [B. Cheat Sheets — numbers, formulas, decision tables](appendix-b-cheatsheets.md)
- [C. 12-Month Learning Roadmap](appendix-c-roadmap.md)

---

## The one question

You will see this question repeated in every chapter, because it is the whole job:

> ### **What problem does this solve?**
>
> Not *"how do I use this?"*

A developer collects tools.
An architect collects **problems** — and knows which tool answers each one.

---

*Written for Delower Hosen. Start with [Chapter 00](00-architect-mindset.md).*
