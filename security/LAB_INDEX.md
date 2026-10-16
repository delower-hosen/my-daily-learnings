# LAB INDEX

Every hands-on lab in the book, in order, with what it needs and what it costs.

| # | Lab | Chapter | Environment | Cost | Status |
|---|---|---|---|---|---|
| 1.1 | Anatomy of a Running Process | 1 | ENV-1 | free | written |
| 2.1 | Build a Minimal Seccomp Profile From Measured Behavior | 2 | ENV-1 + ENV-2 | free | written |
| 3.1 | Map and Harden a Host's Network Attack Surface | 3 | ENV-2 | free | written |
| 4.1 | Trace One Request Through Every Layer | 4 | ENV-3 / ENV-2 | free | written |
| 5.1 | Component Security Audit and Hardening | 5 | ENV-2 / ENV-3 | free | written |
| 6.1 | Prove the Container/VM Boundary Difference | 6 | ENV-2 | free | written |
| 7.1 | Byte-Level Fluency Drills and a Real Decode | 7 | ENV-1 | free | written |
| 8.1 | Decode Frames and Demonstrate L2's Lack of Isolation | 8 | ENV-1 + ENV-2 | free | written |
| 9.1 | Observe ARP and Demonstrate Poisoning (isolated lab) | 9 | ENV-2 | free | written |
| 10.1 | Subnetting Fluency and a VPC Address Plan | 10 | ENV-1 | free | written |
| 11.1 | Find and Close the Dual-Stack Gap | 11 | ENV-1 + ENV-2 | free | written |
| 12.1 | Routing, Longest-Prefix Match, and a Public/Private Topology | 12 | ENV-1 + ENV-2 | free | written |
| 13.1 | VLAN Segmentation and Its Cloud Equivalent | 13 | ENV-1 + ENV-2 | free | written |
| 14.1 | NAT Mechanics and the "NAT Is Not a Firewall" Proof | 14 | ENV-2 | free | written |
| 15.1 | DHCP, Rogue Servers, and Snooping-Style Defense | 15 | ENV-2 | free | written |
| 16.1 | DNS Resolution, Delegation, and Record Inspection | 16 | ENV-1 | free | written |
| 17.1 | DNSSEC Validation, DNS Exfiltration Detection, Rebinding-Robust Validation | 17 | ENV-1 + ENV-2 | free | written |
| 18.1 | UDP Behavior, Statelessness, and Amplification Understanding | 18 | ENV-1 + ENV-2 | free | written |
| 19.1 | TCP Handshake, States, and SYN-Flood Defense | 19 | ENV-1 + ENV-2 | free | written |
| 20.1 | TCP Flow Control, Slow-Read Attack, and Reverse-Proxy Defense | 20 | ENV-1 + ENV-2 | free | written |
| 21.1 | Connection Ceilings: Exhaustion and Defense | 21 | ENV-1 + ENV-2 | free | written |
| 22.1 | MTU, PMTUD, and Diagnosing a Blackhole | 22 | ENV-1 + ENV-2 | free | written |
| 23.1 | ICMP Diagnostics, Abuse, and Precise Filtering | 23 | ENV-1 + ENV-2 | free | written |
| 24.1 | Packet Analysis Across Every Layer | 24 | ENV-1 (+Wireshark) | free | written |
| 25.1 | Using Cryptographic Primitives Correctly | 25 | ENV-1 | free | written |
| 26.1 | Asymmetric Keys, Signatures, and Key Exchange | 26 | ENV-1 | free | written |
| 27.1 | Certificates, Chains, Validation, and the Trust Model | 27 | ENV-1 | free | written |
| 28.1 | TLS: The Synthesis, Configuration, and mTLS | 28 | ENV-1 | free | written |
| 29.1 | HTTP Versions, Semantics, and the Framing Surface | 29 | ENV-1 | free | written |
| 30.1 | SSH: Keys, Hardening, Tunnels, and Key Hygiene | 30 | ENV-1 + ENV-2 | free | written |

---

## Standard lab environments

**ENV-1 — Local Linux**
Ubuntu 22.04+ VM or WSL2. Needs: `procps`, `iproute2`, `net-tools`, `strace`, `ltrace`,
`tcpdump`, `curl`, `dnsutils`, `openssl`. Most of Parts 0–3 run here.

**ENV-2 — Local Docker**
Docker Engine + Compose v2. Used for multi-host network simulations, vulnerable app
targets, and all of Part 10.

**ENV-3 — Dev stack**
.NET 8 SDK, Node.js 20+, Python 3.11+, PostgreSQL, MongoDB, Redis, RabbitMQ (the last
four via Compose). Used across Parts 4, 5, and 12.

**ENV-4 — Packet analysis**
Wireshark on the desktop, `tcpdump` on the VM. Capture files are read on the desktop;
capture happens on the VM. Used across Part 1.

**ENV-5 — Kubernetes**
kind (preferred, for speed and multi-node) or minikube. Used across Part 11.

**ENV-6 — AWS**
A dedicated AWS account, ideally inside an Organization created for this book, with a
budget alarm at a low threshold. Free tier covers most labs; labs that cost money say so
in their header and include teardown steps. Used across Parts 7, 8, 9, 13.

**ENV-7 — Practice platforms**
PortSwigger Web Security Academy (free), TryHackMe, Hack The Box. Used in Parts 4 and 14
for legally sanctioned exploitation practice.

---

## Rules for every lab

1. Labs state their objective, prerequisites, architecture, and cleanup.
2. Labs never target systems you do not own or have not been authorized to test.
3. Labs that can cost money declare it in the first line of the lab header.
4. Labs that create credentials tell you how to revoke them.
5. Every lab ends with verification — how to prove the thing you did actually happened.
