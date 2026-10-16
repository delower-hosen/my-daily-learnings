# BOOK PROGRESS

Live state file. Updated after every chapter. If work resumes in a new session, read this
file first, then continue from **Next Action** without restarting anything.

---

## Status

- **Total chapters planned:** 140 (17 parts)
- **Chapters written:** 30
- **Current part:** Part 2 — Linux Deep Dive (Parts 0 & 1 COMPLETE)
- **Next Action:** Write `Part-02-Linux/Chapter-31-boot-to-login.md`

---

## Completion by part

| Part | Chapters | Written | Status |
|---|---|---|---|
| 0 — Foundations | 01–06 | 6/6 | **COMPLETE** |
| 1 — Networking | 07–30 | 24/24 | **COMPLETE** |
| 2 — Linux | 31–38 | 0/8 | starting |
| 3 — Security Fundamentals | 39–44 | 0/6 | not started |
| 4 — Application Security | 45–58 | 0/14 | not started |
| 5 — API Security | 59–64 | 0/6 | not started |
| 6 — IAM | 65–70 | 0/6 | not started |
| 7 — AWS | 71–82 | 0/12 | not started |
| 8 — Cloud Network Security | 83–87 | 0/5 | not started |
| 9 — Terraform / IaC | 88–92 | 0/5 | not started |
| 10 — Docker | 93–98 | 0/6 | not started |
| 11 — Kubernetes | 99–108 | 0/10 | not started |
| 12 — DevSecOps | 109–115 | 0/7 | not started |
| 13 — Detection / SIEM | 116–121 | 0/6 | not started |
| 14 — Offensive Security | 122–127 | 0/6 | not started |
| 15 — Security Architecture | 128–133 | 0/6 | not started |
| 16 — AI Security | 134–140 | 0/7 | not started |

---

## Chapter log

Format: `NN | title | file | labs | key concepts introduced`

`01 | The Machine Underneath | Part-00-Foundations/Chapter-01-the-machine-underneath.md | Lab 1.1 | rings, MMU/page tables, PTE permission bits, W^X/NX, ASLR, stack layout & overflow geometry, page faults/COW, isolation ladder, cache side channels, page cache & crypto-shredding, Nitro/shared responsibility`

`02 | The Kernel Boundary | Part-00-Foundations/Chapter-02-the-kernel-boundary.md | Lab 2.1 | syscall ABI & dispatch, task_struct, clone flags (= containers), process credentials as OS-level IAM, execve credential transition, no_new_privs, fds as capabilities, seccomp-bpf, capabilities, ptrace, vDSO, eBPF observation, io_uring evasion`

`03 | Files, Descriptors, Sockets, Ports | Part-00-Foundations/Chapter-03-files-descriptors-sockets-ports.md | Lab 3.1 | everything-is-a-file/VFS/f_op, inode vs name (symlink/hardlink), socket families, bind/listen/accept vs connect, bind address as exposure decision, the 4-tuple, ports as convention, socket buffers & slow attacks, epoll/C10k, fd limits as DoS, ss/lsof, Unix sockets & docker.sock=root, egress exfiltration, reverse-proxy tier isolation`

`04 | Anatomy of a Request | Part-00-Foundations/Chapter-04-anatomy-of-a-request.md | Lab 4.1 | THE MAP: 7 stops (browser/DNS/IP/TCP/TLS/edge/app/data) + control at each + "what each layer sees", authN vs authZ as different layers (IDOR), injection = cross-layer confusion, TLS protects transit not endpoints, defense-in-depth table, System A vs B (property invariant, mechanism moves), full System B reference diagram`

`05 | Building Blocks of Production | Part-00-Foundations/Chapter-05-building-blocks-of-production.md | Lab 5.1 | three-lens model (process/network service/data custodian), insecure-defaults pattern (5 recurring issues), why defaults are bad (structural reasons), intermediary risk amplification, PostgreSQL/pg_hba/Redis-CONFIG-RCE/Mongo/RabbitMQ/Nginx posture, classify-before-you-cache, loopback as fragile foundation`

`06 | Virtualization, Containers, Cloud | Part-00-Foundations/Chapter-06-virtualization-containers-cloud.md | Lab 6.1 | THE ISOLATION LADDER as decision tool (hardware/VM/microVM/container/process + cost axis), hypervisor & EPT/NPT/IOMMU, container = clone+ns (shared kernel), microVMs (Firecracker/Kata/gVisor), Lambda/Fargate use microVMs, control plane & IAM = the perimeter, shared-responsibility gradient table, non-root buys/doesn't-buy, §5 rung-selection decision procedure, Fargate > EKS-on-EC2 on isolation axis`

--- PART 1 — NETWORKING ---
`07 | Bits, Bytes, Binary, Hex | Part-01-Networking/Chapter-07-bits-bytes-binary-hex.md | Lab 7.1 | nibble=hex digit, place values & the 8 legal subnet-mask octets, bitmask testing (x&mask) for TCP/PTE/cap flags, TCP flags byte preview, endianness/network byte order/htons, encodings (hex/Base64/URL) recognition & reversibility, Base64≠encryption, decode-count mismatch = WAF bypass, hand-decoding an IPv4 header, canonicalize-then-allowlist`

`08 | Layer 2 (MAC/Ethernet/switches) | Part-01-Networking/Chapter-08-layer2-mac-ethernet-switches.md | Lab 8.1 | L2 = local delivery, no auth/no crypto; MAC scope (local, spoofable, not a credential); Ethernet frame & EtherTypes; FCS detects noise not tampering; switch learns/floods (CAM overflow=MAC flooding); broadcast domain = L2 blast radius; dst MAC=next hop, dst IP=final target (unifies L2/L3); "same LAN ≠ trusted"; cloud SDN removes ARP-spoof/sniffing/MAC-flood (ENI src/dst check)`

`09 | ARP | Part-01-Networking/Chapter-09-arp.md | Lab 9.1 | ARP resolves local IP→MAC (broadcast ask, believe reply); unauthenticated+gratuitous=poisoning; ARP spoofing = canonical LAN MITM; feature=vulnerability (GARP); TLS/mTLS+HSTS defeats on-path attacker = defense-in-depth ACROSS layers (L2 compromise survived by L4/5 crypto); IPv6 NDP has same flaw; DAI+DHCP-snooping; detection (MAC flap, one-MAC-many-IPs, GARP storm); cloud SDN prevents ARP-spoof in VPC`

`10 | IPv4/CIDR/Subnetting | Part-01-Networking/Chapter-10-ipv4-cidr-subnetting.md | Lab 10.1 | 32-bit addr, mask=network/host split, CIDR prefix↔size anchors (/24=256,/16=65536,/8=16.7M,/32=host,/0=internet), block-size subnetting trick (256-maskval), mask AND decides local/remote (=ARP trigger = firewall match), special ranges (RFC1918 10/8·172.16/12·192.168/16, 127/8, 169.254/16 metadata, 0.0.0.0/0), addressing as security boundary (private subnet+no route), CIDR = unit of every SG/NACL rule, AWS reserves 5/subnet`

`11 | IPv6 | Part-01-Networking/Chapter-11-ipv6.md | Lab 11.1 | IPv6 on-by-default = unguarded parallel net ("control you didn't write doesn't exist"); addr types (GUA 2000::/3 internet-reachable, ULA fc00::/7, LLA fe80::/10, ::1, ::/0); NO NAT = global by default (reachability via firewall only, EIGW for private); SLAAC self-config (no DHCP record); NDP = ARP flaw + rogue RA (worse); DUAL-STACK BYPASS (IPv4 rules ≠ IPv6, audit ss[::]+ip6tables); cloud needs parallel SG rules; IPv4-mapped ::ffff bypass in SSRF`

`12 | Routing | Part-01-Networking/Chapter-12-routing.md | Lab 12.1 | hop-by-hop independent forwarding; LONGEST-PREFIX MATCH (specificity, not order — vs firewall eval); route table = reachability topology YOU own in cloud; default route target decides public(IGW)/private-egress(NAT)/isolated(no route); dst IP constant + dst MAC rewritten + TTL-- each hop (traceroute); routing=coarse isolation, SG=fine (complementary); BGP hijack (trust + longest-prefix); path untrusted → end-to-end crypto; route-table audit as core review task (data-subnet→IGW = critical)`

`13 | Switching/VLANs/Trunks | Part-01-Networking/Chapter-13-switching-vlans-trunks.md | Lab 13.1 | VLAN = software broadcast domain = on-prem subnet; 802.1Q tag, access vs trunk ports; VLAN hopping (switch-spoof/DTP + double-tagging/native-VLAN) = misconfig not flaw; SEGMENTATION as platform-independent architecture (trust zones + default-deny choke points = blast-radius containment); VLANs isolate between not within (PVLAN/SG/NetworkPolicy for east-west); MANAGEMENT must be own zone; cloud replaces VLANs w/ subnets+SG (removes VLAN hopping, per-instance micro-seg free, auditable-as-code); "same architecture, 3 mechanisms" (VLAN/SG/NetPol)`

`14 | NAT/PAT | Part-01-Networking/Chapter-14-nat-pat.md | Lab 14.1 | NAT=translator for address conservation, inbound-blocking is SIDE EFFECT not policy; PAT/overload (AWS NAT GW) vs static NAT (EIP); SNAT(outbound side effect) vs DNAT(port-forward=deliberate exposure); NAT IS NOT A FIREWALL (no egress control, no inspection, no IPv6, bypassed by port-forward/NAT-traversal/outbound attacks); NAT table = stateful+finite = conntrack/SG statefulness (Ch37/76); AWS NAT GW = connectivity NOT egress control (add VPC endpoints+SG egress+Network Firewall/proxy); connection limits real DoS`

`15 | DHCP | Part-01-Networking/Chapter-15-dhcp.md | Lab 15.1 | DORA exchange (UDP 67/68); DHCP hands gateway+DNS = controls victim's traffic+names; THE BOOTSTRAPPING TRUST PROBLEM (TOFU no anchor; vs PKI anchor, vs SSH pinning); rogue DHCP = MITM stealthier/broader than ARP (persists, controls DNS+routing); option attacks (Opt121 static routes/TunnelVision VPN-bypass, WPAD, NTP); starvation DoS; DHCP snooping (trusted ports) = keystone + binding table feeds DAI+IP Source Guard ("bootstrap a binding, enforce against it"); cloud managed DHCP removes rogue but option-set DNS is yours`

`16 | DNS Part 1 | Part-01-Networking/Chapter-16-dns-part1.md | Lab 16.1 | hierarchical/delegated/cached/UDP/unauthenticated resolution; recursive resolver vs authoritative, referral+glue, AA bit; delegation chain = trust chain (registrar=critical asset, MFA+registry lock); record types as security controls (SPF/DKIM/DMARC email anti-spoof, CAA cert-issuer limit, NS delegation, PTR NOT a control); caching+TTL amplify/prolong attacks + bound failover/rebinding; UDP+16-bit ID = weak auth (poisoning/amplification); cloud DNS = control point (Route53, private zones/split-horizon, resolver rules, query logging, DNSSEC)`

`17 | DNS Part 2 (attacks/defenses) | Part-01-Networking/Chapter-17-dns-part2.md | Lab 17.1 | 2 attack layers: resolution (poisoning/Kaminsky/on-path spoof) + delegation (registrar hijack, subdomain takeover/dangling records) + covert channel (tunneling/exfil) + amplification DDoS; TWO-HALF DEFENSE: DNSSEC=authenticate answer (not confidentiality, not registrar), DoH/DoT=encrypt transport (DoH=defender blind spot); DNS REBINDING → SSRF → metadata (validate CONNECTED IP at connect-time + block internal ranges + pin + IMDSv2 — links Ch50/78); exfil bypasses egress but query logging=detection surface (DNS Firewall/RPZ); registry lock; TLS end-to-end = backstop`

`18 | UDP | Part-01-Networking/Chapter-18-udp.md | Lab 18.1 | UDP = minimal connectionless (8-byte hdr: ports/length/weak-checksum), NO handshake/reliability/ordering/SECURITY; no handshake = source SPOOFABLE (vs blind TCP spoof hard); spoofability + amplification (memcached 10k-51kx, NTP monlist 556x, DNS ANY) = largest DDoS + weaponizes YOUR service vs 3rd parties; UDP filtered statelessly via timeouts (approximate, looser than TCP); UDP security must come from app layer (DNSSEC/DoT, QUIC TLS, VPN crypto); QUIC/HTTP3 over UDP = encrypted web = reduced inspection; BCP38 + don't-expose-amplifiers + Shield`

`19 | TCP Part 1 (state machine) | Part-01-Networking/Chapter-19-tcp-part1.md | Lab 19.1 | 3-way handshake (SYN/SYN-ACK/ACK) establishes state + verifies endpoints (resists blind spoof, unlike UDP); flags byte (Ch7); SYN FLOOD exhausts half-open state → SYN COOKIES (stateless defense = "encode state in ISN, allocate none until ACK" — general pattern); sequence numbers + ISN randomization = weak OFF-path resistance only (on-path sees them → TLS is real defense); state machine = what STATEFUL firewalls/SGs track ("allow established/related" — deps: Ch37 conntrack, Ch76 SGs); TIME_WAIT(normal)/CLOSE_WAIT(app bug)/RST; ALL TCP attacks = resource exhaustion`

`20 | TCP Part 2 (reliability/perf) | Part-01-Networking/Chapter-20-tcp-part2.md | Lab 20.1 | reliability = ACK+RTO+fast-retransmit(+SACK); 2 windows: rwnd=flow control(protect receiver, receiver-signaled) + cwnd=congestion control(protect network, sender-inferred, slow-start/backoff), sender limited by min; SLOW-READ attack weaponizes flow control (tiny window keeps server send buffer full = read-side twin of Slowloris); buffers/windows=per-conn memory → buffer sizing = DoS-resistance knob (max conns≈mem/buffer); congestion control cooperative (abuse=fairness; DDoS ignores it); REVERSE PROXY changes DoS math (absorb slow clients at efficient front-end); SACK Panic; retransmit/zero-window = diagnostic signals; TLS separate (data security)`

`21 | Sockets/Ports/Connection Tables | Part-01-Networking/Chapter-21-sockets-ports-connection-tables.md | Lab 21.1 | connection = 4-tuple tracked via 3 FINITE CEILINGS: ephemeral ports (~28k PER-DESTINATION outbound), conntrack entries (stateful filter/NAT), fds (per socket) + per-conn memory; capacity ≈ min(ceilings); server hits fds/conntrack/mem (many conns share 1 listen port), client-to-1-dest hits ports; high load & attacks hit SAME ceilings → capacity planning = DoS resistance (quantitative "finite resources = DoS targets"); CONNECTION REUSE (pooling/keepalive) = highest-leverage (reduces all 3); reverse proxy shifts ceiling; cloud = NAT GW limits (ErrorPortAllocation) + SG tracking → VPC endpoints + per-AZ NAT; new-HttpClient-per-request = classic self-inflicted DoS`

`22 | MTU/Fragmentation | Part-01-Networking/Chapter-22-mtu-fragmentation.md | Lab 22.1 | MTU per link (1500/jumbo9000/reduced-by-encapsulation VPN/overlay - endemic in cloud); DF+PMTUD finds path MTU via ICMP; PMTU BLACKHOLE = blocking all ICMP breaks PMTUD → "small works large hangs" (SECURITY CONTROL causing OUTAGE); LESSON 1: precise-not-blanket filtering (allow ICMP type3code4/PacketTooBig, IPv6 essential); fragmentation = attack surface (PingOfDeath/teardrop reassembly bugs, overlapping/tiny-fragment IDS EVASION = "2 parties interpret differently" root cause, fragment-flood DoS); LESSON 2: reassembly ambiguity = evasion surface (reassemble/normalize before inspect); MSS clamping = tunnel/VPN fix; DF ping test diagnosis`

`23 | ICMP/Ping/Traceroute | Part-01-Networking/Chapter-23-icmp-ping-traceroute.md | Lab 23.1 | ICMP = essential(PMTUD type3code4/PacketTooBig, error signaling, IPv6 NDP) YET abused(recon ping/traceroute, tunneling in echo payloads, redirect type5 MITM, smurf/PoD/flood DoS); THE PRECISE-vs-BLANKET FILTERING CASE STUDY (per-type per-source: allow essential, restrict/rate-limit recon ping, ignore redirects, monitor tunneling — NEVER blanket-block, esp ICMPv6=breaks IPv6); generalizes to firewalls/WAF/IAM (blanket=false economy); ignore redirects (accept_redirects=0), disable directed broadcasts; traceroute=TTL/TimeExceeded topology map`

`24 | Packet Analysis Workshop | Part-01-Networking/Chapter-24-packet-analysis-workshop.md | Lab 24.1 | CONSOLIDATES Part 1 layer-reading into one capability; packets = GROUND TRUTH (verify/investigate/debug — beats config/logs/claims); tcpdump(capture/CLI) + Wireshark(deep/streams/stats) + BPF(precise kernel filter; -n always); ENCRYPTION LIMIT = see metadata(endpoints/timing/volume/TLS-version/SNI/JA3) not payload → analysis shifts to metadata + decryption points (edge/WAF after TLS term); follow streams; captures = SENSITIVE DATA (classify-before-store); cloud = VPC Flow Logs(metadata) + Traffic Mirroring(capture) + host tcpdump; recipe repertoire per security question`

`25 | Cryptography Part 1 (symmetric) | Part-01-Networking/Chapter-25-cryptography-part1.md | Lab 25.1 | MATCH PRIMITIVE TO GOAL: symmetric enc(AES=confidentiality,shared key)/hash(SHA256=one-way fingerprint,no key)/MAC(HMAC=integrity+authenticity,shared key)/AEAD(AES-GCM=conf+integ together=USE THIS); CORRECT USAGE > algorithm choice (failures=misuse: ECB penguin, nonce reuse, encryption≠integrity, weak RNG, timing); NEVER roll your own (algos OR usage); PASSWORD STORAGE special case = slow salted memory-hard (Argon2id NOT fast hash); CSPRNG for all randomness; CONSTANT-TIME comparison (Ch1 timing); symmetric needs shared key → key distribution problem → Ch26 asymmetric; KMS(Ch80) manages`

`26 | Cryptography Part 2 (asymmetric) | Part-01-Networking/Chapter-26-cryptography-part2.md | Lab 26.1 | key pair (public shared/private secret=crown jewel); solves 2 problems symmetric can't: KEY EXCHANGE (DH/ECDHE = shared symmetric key over insecure channel between strangers → enables TLS; ephemeral=FORWARD SECRECY defeats harvest-now-decrypt-later) + SIGNATURES (sign private/verify public = authenticity+NON-REPUDIATION, scales to strangers unlike MAC → basis of certs/JWT/artifact signing); asymmetric SLOW → partner w/ symmetric (asymmetric establishes+authenticates, symmetric transfers) = TLS/hybrid/envelope-encryption(KMS); RSA vs ECC(smaller/faster,preferred); key exchange must be AUTHENTICATED (→PKI Ch27); PQC horizon (RSA/ECC quantum-vulnerable)`

`27 | PKI & X.509 | Part-01-Networking/Chapter-27-pki-x509.md | Lab 27.1 | PKI binds pubkey→identity via CA signatures (Ch26) anchored in pre-installed root trust store = solves bootstrapping trust (Ch15 §5, strong solution=anchor); cert=signed identity-key binding (SANs,validity,issuer); CHAIN of trust (leaf←intermediate←root); VALIDATION = chain+trusted-root+IDENTITY-MATCH(prevents MITM)+validity+revocation; DISABLING VALIDATION (verify=False/-k/InsecureSkipVerify) = encryption w/o auth = MITM (#1 serious TLS bug); trust model weakness = CA compromise/mis-issuance (DigiNotar) → CAA(limit issuers)+Cert Transparency(detect,auditable logs)+pinning; revocation WEAK (soft-fail) → SHORT LIFETIMES+automation; EXPIRY=#1 outage → AUTOMATE (ACM/ACME/cert-manager); authenticates key exchange (Ch26) making TLS secure`

`28 | TLS byte by byte | Part-01-Networking/Chapter-28-tls-byte-by-byte.md | Lab 28.1 | TLS = SYNTHESIS of Ch25-27: PKI(authenticate,Ch27)+ECDHE key exchange(establish key+forward secrecy,Ch26)+symmetric AEAD(transfer data,Ch25); handshake authenticates+establishes then AEAD transfers; TLS 1.3=1-RTT/forward-secrecy-REQUIRED/AEAD-only/hardened (correct-usage-by-default) → prefer 1.3, DISABLE 1.0/1.1/SSL+weak ciphers; cipher suite decomposes (ECDHE+sig+AEAD+hash); validation IS TLS auth (Ch27); SNI leaks which-site (ECH closes); mTLS=mutual auth (→service-to-service Ch64, workload identity Ch67, Zero Trust mesh Ch86-87); TLS=LOAD-BEARING control vs on-path attackers (Part 1 culmination, Zero Trust Ch43); protects TRANSIT not endpoints (termination architectural, WAF after, re-encrypt internal); grade w/ SSL Labs`

`29 | HTTP/1.1/2/3 | Part-01-Networking/Chapter-29-http-versions.md | Lab 29.1 | HTTP SEMANTICS(methods/headers/status/cookies/security-headers) = STABLE across versions = version-INDEPENDENT app-security surface (Part 5, Ch59); FRAMING differs = where version-specific security lives; HTTP/1.1 text CL/TE delimiting = REQUEST-SMUGGLING surface (Ch57, parsing-inconsistency = "2 parties interpret differently" root cause Ch7/22); HTTP/2 binary multiplex = new DoS (Rapid Reset CVE-2023-44487) + downgrade smuggling; HTTP/3 = QUIC/UDP (Ch18) = visibility shift (inspect at termination Ch24); INTERMEDIARY CONSISTENCY = security property (reject ambiguity, normalize at edge); WAF after termination; security headers = Ch59`

`30 | SSH internals | Part-01-Networking/Chapter-30-ssh-internals.md | Lab 30.1 | SSH = applied crypto for remote access (3 layers mirror TLS: transport=key exchange+AEAD, auth=public-key, connection=channels); crypto SOUND, security OPERATIONAL; top attack target (exposed port 22 brute-forced Ch10) → public-key-ONLY (disable passwords) defeats brute-force = #1 hardening; host-key verify = TOFU+pinning (Ch15); KEY HYGIENE core (long-lived keys accumulate/sprawl → one-per-person/rotate/audit; short-lived certs better); tunnels DOUBLE-EDGED (access + pivot/exfil Ch13/17/23); MODERN DIRECTION = SSM Session Manager (no port/no keys/IAM-auth/logged Ch78) or short-lived SSH certs — eliminates structural weaknesses`

--- PART 1 COMPLETE (Chapters 7-30). Parts 0 & 1 = foundational half done. ---
--- Recurring cross-Part-1 themes: "network is untrusted" (ARP/DNS/routing/DHCP all attackable) → TLS is the
    load-bearing control (Ch28, Zero Trust Ch43); "finite resources = DoS targets" (Ch3/19/20/21); "2 parties
    interpret bytes differently" = injection/smuggling/evasion (Ch7/22/29/57); precise-not-blanket filtering
    (Ch22/23); bootstrapping trust TOFU vs anchor (Ch15/27/30); short-lived > long-lived credentials (Ch1/26/
    27/30/68); cloud SDN removes L2/bootstrapping attacks but moves risk to IAM/config. ---

---

## Concepts introduced so far

**Ch. 1:** privilege rings (0/3 + hypervisor) · virtual vs physical addresses · MMU, page
tables, PTE flags (R/W, U/S, NX) · process address-space layout · W^X · ASLR · stack
canaries · CFI · page faults (minor/major/invalid) · lazy allocation · copy-on-write ·
guard pages · TLB & KPTI · context switches · threads share everything · **the isolation
ladder** (threads→processes→containers→VMs→hosts→accounts) · memory hierarchy & cache
timing as a side channel · ROP · memory safety as class-elimination · page cache ·
crypto-shredding · the precise limits of "encryption at rest" · Nitro / shrinking the TCB.

**Recurring reasoning patterns established in Ch. 1** (reuse these, do not re-derive):
1. *"What hardware or cryptographic mechanism enforces this boundary, and who can
   reconfigure it?"*
2. *"Every control has a specific threat it addresses and specific threats it does not."*
3. *"Attackers do not break your control; they make it irrelevant."* (NX → ROP)
4. *"Prefer eliminating a vulnerability class over detecting its instances."*
5. *"Isolation boundaries are only as strong as the credentials that cross them."*

**Ch. 2:** system calls as the complete process↔world vocabulary · x86-64 syscall ABI ·
`task_struct`, and threads/processes/containers as the same object with different shared
pointers · process credentials (real/effective/saved UID, capability sets) as the OS's IAM ·
`execve` as the only privilege-gain point, and `no_new_privs` · file descriptors as
capabilities granted at `open()` · seccomp-bpf and its pointer blindness · the nginx
privilege-drop pattern · ptrace as same-UID isolation bypass · vDSO · eBPF syscall
observation · io_uring as a detection blind spot · the five containment dimensions
(UID, capabilities, seccomp, namespaces, cgroups).

**Recurring reasoning patterns added in Ch. 2:**
6. *"Filter on the request, or enforce at the resource — only the latter is race-free."*
   (seccomp vs LSM; SG vs bucket policy; WAF vs app authz; admission vs RBAC)
7. *"Do privileged work first, keep the descriptors, then drop privilege irreversibly."*
8. *"Containment is not remediation — the bug is identical, only the consequence changed."*

**Ch. 3:** everything-is-a-file / VFS / f_op dispatch · inode vs filename (symlinks,
hardlinks, TOCTOU) · sockets as fds, the 4-tuple as the atomic unit of network controls ·
bind address as the exposure decision (below any firewall) · "is the port open?" = bind +
reachability · ports as conventions not contracts · socket buffers and slow-client attacks ·
epoll/C10k and its security downsides · fds/buffers/ports/conntrack as finite DoS targets ·
ss/lsof · Unix sockets & docker.sock = root · egress exfil through allowed destinations ·
reverse-proxy tier isolation.

**Recurring reasoning patterns added in Ch. 3:**
9. *"Name the layer and name the enforcing mechanism"* — "it's safe" is never an answer.
10. *"The control providing a property can move between layers (bind→SG→NetworkPolicy) as
    architecture changes, but the property must always be provided by something nameable."*

**Ch. 4 (THE MAP — keystone of Part 0):** the 7-stop request journey and the control at each
stop · "a control acts only on what its layer sees" (the master rule) · authN (sees token) vs
authZ (knows data) as different layers = IDOR/BOLA · injection as cross-layer data→structure
confusion (SQLi/cmd/XSS/prompt all one shape) · TLS protects transit not endpoints · the
defense-in-depth table (which layers can/can't stop a given attack) · System A vs B (layers
invariant, enforcing component moves) · the full annotated System B reference diagram.

**Recurring reasoning patterns added in Ch. 4:**
11. *"Place any threat on the 7-stop map; the controls that can address it are those at/above
    its layer that can SEE it."* (This is the book's core analytical move.)
12. *"AuthN sees the token; authZ knows the data model — they are different layers."*
13. *"Injection = data from one layer interpreted as structure/instructions by the next; the
    fix is always to separate the data channel from the instruction channel."*

**Ch. 5:** three-lens model (process / network service / data custodian) as a universal
component-audit checklist · the 5 recurring insecure defaults (no auth, bind-all, no TLS,
overpowered default account, dangerous features) · why defaults are structurally bad
(pre-hostile-net design, convenience-for-adoption, invisible dev trust boundary, backcompat) ·
intermediary risk amplification (proxy/cache/broker compromise is transitive) · component
posture for PostgreSQL(pg_hba)/Redis(CONFIG-RCE)/Mongo(NoSQLi)/RabbitMQ(guest)/Nginx ·
classify-before-you-cache · loopback as a real but fragile foundation.

**Recurring reasoning patterns added in Ch. 5:**
14. *"Apply the three-lens model to any component: process / network service / data custodian."*
15. *"Assume every new component ships trusting the network, with a powerful default account,
    and without transport encryption — verify, then fix."*
16. *"Intermediaries concentrate data, and concentrated data concentrates risk."*

**Ch. 6 (closes Part 0):** the isolation ladder as a *decision tool* with a cost axis ·
hypervisor internals (VT-x/AMD-V, EPT/NPT second-level translation, IOMMU) = why VM > container ·
container = clone+namespaces = shared kernel (the one sentence) · microVMs (Firecracker/Kata) &
gVisor as middle rungs; Lambda/Fargate already use them · control plane & IAM as THE cloud
perimeter (data read over public API by identity, invisible to network) · shared-responsibility
gradient (host rows move up, data/IAM/config never move) · non-root buys capability-escape
defense not kernel-bug defense · the §5 rung-selection decision procedure · Fargate is a HIGHER
isolation rung than EKS-on-EC2.

**Recurring reasoning patterns added in Ch. 6:**
17. *"Match the isolation rung to the threat; choose the lowest rung that defeats it, then add
    depth — never maximize isolation blindly (cost/ops are finite risks too)."*
18. *"In the cloud, identity is the perimeter; identity and configuration are ALWAYS yours,
    on every rung, no matter how managed the service."*

---

## Forward dependencies to honor

These are chapters that later material explicitly depends on. When writing the dependent
chapter, reference back rather than re-explaining.

| Later chapter | Depends on | Why |
|---|---|---|
| 76 Security Groups vs NACLs | 19 TCP state machine | "Stateful" is meaningless without connection state |
| 104 NetworkPolicy | 37 netfilter | NetworkPolicy is compiled into netfilter/eBPF rules |
| 93 What a container is | 38 namespaces/cgroups | Containers are those primitives, nothing more |
| 50 SSRF | 78 IMDS, 16 DNS | SSRF's cloud impact runs through metadata and DNS |
| 60 JWT | 25–26 crypto | Signature validation requires understanding signatures |
| 61 OAuth/OIDC | 59 HTTP security model | Redirect/cookie semantics drive the flows |
| 84 Packet journey | 28 TLS, 29 HTTP/2 | Termination points depend on protocol behavior |
| 100 API server lifecycle | 72 IAM evaluation | Same authz reasoning pattern, different system |
| 136 Prompt injection | 45 root causes | It is a code/data confusion bug, a classic class |

---

## Decisions made

1. **AWS is the primary cloud.** Azure/GCP appear only as deltas, to preserve depth.
2. **Networking gets 24 chapters.** It is the single biggest gap between a backend
   engineer and a cloud security engineer, and every cloud control is a network control.
3. **Exercise answers are separated** into a `## Solutions` section per chapter.
4. **Three recurring systems (A/B/C)** carry examples across parts so knowledge compounds.
5. **Offensive material is defensive-purposed** and scoped to authorized/lab targets.
6. **Windows/AD is minimized** to identity intersections only.
7. **Chapter files are self-contained** but cross-reference rather than repeat.

---

## Unresolved / to revisit

- Decide whether Part 14 needs a dedicated chapter on Active Directory attack paths
  (currently folded into Chapter 125 credential attacks + Chapter 62 Kerberos).
- Consider an appendix on Azure/GCP mappings after Part 7 is complete.
- Consider a separate appendix of cheat-sheets (tcpdump filters, jq/CloudTrail queries,
  kubectl security one-liners) once the relevant parts are written.

---

## Labs written so far

_(none yet — see `LAB_INDEX.md`)_
