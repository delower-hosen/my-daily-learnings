# Chapter 22 — MTU, Fragmentation, Path MTU Discovery, and the Bugs They Cause

---

## 1. Why This Matters

MTU and fragmentation are the networking topics most likely to cause a baffling, intermittent failure —
connections that establish but then hang, work for small requests but fail for large ones, or break only
over a VPN or tunnel. For a cloud security engineer, they matter for three reasons:

1. **PMTU blackholing is a real, hard-to-diagnose outage** — and firewalls that (over-zealously) block ICMP
   are a common cause, making it a place where a security control (blocking ICMP) breaks connectivity in a
   confusing way (Chapter 23).
2. **Fragmentation is an attack surface** — fragment-based attacks (overlapping fragments, tiny fragments,
   fragment floods) evade IDS/firewalls and cause resource exhaustion, and historically caused DoS (Ping of
   Death, teardrop). Reassembly is where several classic vulnerabilities lived.
3. **Tunnels, VPNs, and overlays (VXLAN, WireGuard, container/Kubernetes networking) reduce the effective
   MTU** by adding encapsulation headers, so MTU/fragmentation issues are endemic wherever encapsulation
   happens — which is everywhere in cloud (Chapters 75, 103).

The core idea: **every link has a Maximum Transmission Unit (MTU) — the largest frame it will carry
(typically 1500 bytes for Ethernet). Packets larger than a link's MTU must be fragmented or dropped. Path
MTU Discovery (PMTUD) finds the smallest MTU along a path so senders can avoid fragmentation — but it relies
on ICMP messages that firewalls often block, causing "PMTU blackholes" where large packets vanish silently.
Fragmentation itself is an attack surface (evasion, DoS) that modern practice minimizes.** MTU issues are
where "it works sometimes" bugs and a class of evasion/DoS attacks both live, and where a security control
(ICMP blocking) can cause an outage.

---

## 2. Prerequisites

- Chapter 8 (Ethernet frame, the 1500-byte MTU), Chapter 10 (IP header, fragmentation fields — you decoded
  the DF flag in Chapter 7 §5), Chapter 23 preview (ICMP — PMTUD uses it), Chapter 20 §4.4 (MSS).
- Chapters 19–20 (TCP — MSS derives from MTU; TCP interacts with PMTUD).

---

## 3. Mental Model

**Data must fit in link-sized chunks. The MTU is the largest payload a link carries; a packet too big for a
link's MTU is either fragmented (split) or, if fragmentation is forbidden (DF bit set), dropped with an ICMP
"fragmentation needed" message back to the sender. Path MTU Discovery uses those ICMP messages to find the
smallest MTU on the path — but if the ICMP is blocked, large packets silently vanish (a blackhole).**

```
   MTU = largest payload a link will carry (Ethernet: 1500 bytes; some links less; jumbo frames: 9000).

   A packet larger than the next link's MTU:
     - DF (Don't Fragment) bit CLEAR -> router FRAGMENTS it into MTU-sized pieces, reassembled at the dest.
     - DF bit SET -> router DROPS it and sends ICMP "Fragmentation Needed" (type 3 code 4) to the sender,
        stating the link's MTU -> the sender lowers its packet size (this is PMTUD).

   PMTU BLACKHOLE: DF is set (modern default), the ICMP "Fragmentation Needed" is BLOCKED (by a firewall),
     so the sender never learns to shrink -> large packets are dropped silently -> connection hangs.
     (Small packets work; large ones vanish -> the classic "works sometimes" symptom.)
```

Three ideas:

1. **MTU limits packet size per link, and the path MTU is the minimum along the path.** A packet must fit
   the smallest MTU on its route. Modern TCP sets the **DF bit** and uses **PMTUD** to discover that
   minimum and size segments accordingly (via MSS — Chapter 20 §4.4), avoiding fragmentation.
2. **Fragmentation is increasingly avoided.** IPv4 routers can fragment (DF clear), but fragmentation is
   inefficient, an attack surface (§4.3), and in **IPv6 routers do not fragment at all** — only the sender
   can, via PMTUD. So modern networking relies on PMTUD, not en-route fragmentation.
3. **PMTUD's dependence on ICMP is its fragility.** PMTUD needs the ICMP "Fragmentation Needed" message to
   reach the sender. Firewalls that block *all* ICMP (a common over-correction — Chapter 23) break PMTUD,
   causing **blackholes**: large packets are dropped with no signal, connections hang, and the symptom
   (small requests work, large ones fail) is confusing. This is a security control (ICMP blocking) causing
   an availability failure.

**The security framing:** MTU/fragmentation intersect security in two ways. First, **fragmentation is an
attack surface** — reassembly bugs (Ping of Death, teardrop), evasion (overlapping/tiny fragments confusing
IDS/firewalls), and resource exhaustion (fragment floods). Second, **PMTUD's ICMP dependence means a
security control (blocking ICMP) can cause outages (blackholes)** — a lesson in not over-blocking.
Encapsulation (VPNs, tunnels, overlays — endemic in cloud) reduces effective MTU, making these issues
common. Modern practice minimizes fragmentation (DF + PMTUD, or MSS clamping) and allows the specific ICMP
PMTUD needs.

---

## 4. Fundamentals

### 4.1 MTU and where it comes from

The **MTU (Maximum Transmission Unit)** is the largest payload (IP packet) a link will carry:

```
   Ethernet MTU: 1500 bytes (the standard) -> a max IP packet of 1500 bytes.
   Jumbo frames: up to 9000 bytes (data-center/storage networks; must be supported end to end).
   Tunnels/VPNs/overlays: LESS than 1500, because encapsulation headers eat into it:
     - IPsec/WireGuard: ~1420-1440 (encryption + encapsulation overhead)
     - VXLAN (overlays, Kubernetes/cloud): ~1450 (50 bytes of VXLAN/UDP/IP overhead)
     - GRE, PPPoE, etc.: various reductions
   -> The EFFECTIVE MTU on an encapsulated path is smaller than 1500, which is why tunnels cause MTU bugs.
```

Every interface has an MTU (`ip link` shows it — Chapter 8 §6.1). The **path MTU** is the *minimum* MTU
across all links on a route. Because encapsulation (tunnels, VPNs, overlays) adds headers, the effective
MTU on those paths is reduced — and since cloud networking is built on overlays (VXLAN-style — Chapters 75,
103), sub-1500 effective MTUs are common, making MTU issues endemic in cloud and container environments.

### 4.2 Fragmentation and reassembly

When a packet exceeds a link's MTU and fragmentation is allowed (DF clear), the router **fragments** it:

```
   A 4000-byte IP packet crossing a 1500-byte-MTU link is split into fragments:
     each fragment has the same IP identification field, a fragment offset, and the MF (More Fragments)
     flag (set on all but the last). The DESTINATION reassembles them using these fields.
   Fragmentation fields (IP header, Chapter 10):
     - Identification: groups fragments of the same original packet
     - Flags: DF (don't fragment), MF (more fragments)
     - Fragment Offset: where this fragment belongs in the original
```

Reassembly happens only at the *destination* (routers fragment but do not reassemble). This has costs and
risks:

- **Inefficiency:** fragmentation adds overhead, and losing one fragment means the whole packet must be
  resent (the sender does not know which fragment was lost — a reliability/performance cost).
- **Reassembly is stateful and resource-consuming** at the destination (it must buffer fragments until
  complete) — a DoS surface (fragment floods, §4.3).
- **Reassembly ambiguity** (overlapping fragments, different OSes reassembling differently) is an
  IDS/firewall evasion surface (§4.3).

Because of these, **modern networking avoids en-route fragmentation**: TCP sets DF and uses PMTUD (§4.4);
IPv6 forbids router fragmentation entirely (only the sender fragments, via PMTUD). Fragmentation is legacy
IPv4 behavior increasingly designed out.

### 4.3 Fragmentation as an attack surface

Fragmentation has a long history of security problems:

- **Ping of Death (classic):** send a fragmented ICMP packet that, when reassembled, exceeds the maximum IP
  packet size (65,535 bytes), overflowing the reassembly buffer and crashing the target. A reassembly-buffer
  bug — long patched, but the archetype.
- **Teardrop:** send overlapping/malformed fragments (bad offsets) that crash the reassembly code. Another
  reassembly bug.
- **Overlapping-fragment evasion:** send fragments that *overlap* with conflicting data; different systems
  (the IDS vs the target) resolve the overlap differently, so the IDS sees benign content while the target
  reassembles a malicious payload — an **IDS/firewall evasion** technique (Chapter 13's "two parties
  interpret differently" root cause, at the fragment layer).
- **Tiny-fragment evasion:** split a packet so the TCP header spans fragments, so a firewall filtering on
  TCP header fields (ports/flags) cannot see them in the first fragment — evading the filter.
- **Fragment-flood DoS:** flood incomplete fragments to exhaust the target's reassembly buffers/state.

The defensive lesson: **fragmentation is a source of reassembly bugs and evasion, so modern practice
minimizes it (DF + PMTUD, drop fragments where feasible) and firewalls/IDS must reassemble consistently
before inspecting** (or drop overlapping/tiny fragments). Blocking or normalizing fragments is a common
firewall hardening. The recurring theme: ambiguity in how two systems interpret the same bytes (fragments)
is an evasion surface — the same root cause as encoding bypass (Chapter 7) and request smuggling
(Chapter 57).

### 4.4 Path MTU Discovery (PMTUD) and blackholing

**PMTUD** lets a sender discover the path MTU without fragmentation:

```
   1. The sender sets the DF (Don't Fragment) bit on packets (TCP does this by default).
   2. If a router's next link has a smaller MTU than the packet, it CANNOT fragment (DF set), so it DROPS
      the packet and sends an ICMP "Fragmentation Needed and DF set" (type 3, code 4) back to the sender,
      including the link's MTU.
   3. The sender receives the ICMP, lowers its path-MTU estimate for that destination, and retransmits
      smaller packets. It converges on the path MTU.
```

PMTUD is elegant and standard — but it depends on the ICMP message reaching the sender. The failure:

```
   PMTU BLACKHOLE:
   A firewall (on the path or at the sender/receiver) blocks ICMP (a common over-correction, Chapter 23).
   The ICMP "Fragmentation Needed" never reaches the sender.
   The sender keeps sending large DF packets, which keep being dropped silently.
   -> Symptom: the connection ESTABLISHES (small handshake packets fit), but HANGS when large data flows
      (large packets are dropped). Small requests work; large ones fail. VERY confusing to diagnose.
```

This is the single most important MTU security lesson: **blocking all ICMP breaks PMTUD, causing blackholes
that look like application bugs.** The fix is to **allow the specific ICMP that PMTUD needs** (type 3 code 4
for IPv4; "Packet Too Big" for IPv6, which is *essential* since IPv6 has no router fragmentation) — not
block all ICMP. This is a concrete case where over-blocking a protocol (ICMP) for "security" causes an
availability failure, and the right answer is precise filtering (allow what is needed), not blanket blocking
(Chapter 23 covers ICMP fully). Alternatives when PMTUD cannot be relied upon: **MSS clamping** (§4.5) and
**PLPMTUD** (packetization-layer PMTUD, which infers the MTU without ICMP).

### 4.5 MSS clamping (the tunnel/VPN fix)

**MSS clamping** is the pragmatic fix for MTU issues on tunnels/VPNs/overlays where PMTUD is unreliable:

```
   The TCP MSS (Maximum Segment Size, Chapter 20 §4.4) is negotiated in the handshake, derived from the MTU.
   MSS CLAMPING: a device on the path (a router/firewall/tunnel endpoint) rewrites the MSS in the SYN to a
     lower value matching the (reduced) path MTU, so TCP never sends segments too large for the tunnel.
   -> Avoids fragmentation and blackholing on encapsulated paths without relying on PMTUD's ICMP.
```

MSS clamping is standard on VPN/tunnel endpoints and is the reliable fix for the tunnel-MTU problem
(reduced effective MTU from encapsulation — §4.1). It works by ensuring TCP never generates a segment too
big for the path, sidestepping fragmentation and PMTUD entirely for TCP. It does not help non-TCP traffic
(which needs PMTUD or correct MTU configuration). In Kubernetes/cloud overlays, the CNI/overlay typically
handles MTU (setting a reduced pod MTU) or uses MSS clamping.

### 4.6 MTU in the cloud and containers

Cloud and container networking are built on overlays and thus have MTU considerations:

- **AWS VPC:** standard MTU is 1500; **jumbo frames (9001)** are supported within a VPC (for high-throughput
  intra-VPC traffic) but **not** for traffic leaving the VPC (internet, some VPC peering, VPN) — a common
  gotcha where jumbo-frame-configured instances have issues on external paths.
- **Overlays (VXLAN, and container CNIs like Calico/Flannel):** add encapsulation, reducing pod MTU below
  1500 (e.g. 1450) — Chapters 75, 103. Mismatched pod/node MTU causes the classic "small packets work,
  large ones hang" in Kubernetes.
- **VPNs (Site-to-Site VPN, Client VPN):** reduce effective MTU; MSS clamping is typically applied.
- **PMTUD reliance:** the cloud generally allows the necessary ICMP within the VPC, but paths to/from
  external networks or through appliances that block ICMP can blackhole.

The cloud security engineer's MTU knowledge is mostly practical: **recognize the "small works, large hangs"
blackhole symptom, know that encapsulation (VPN/overlay/jumbo-frame mismatch) reduces effective MTU, ensure
the ICMP PMTUD needs is allowed (not blanket-blocked), and use MSS clamping / correct overlay MTU where
encapsulation applies.**

---

## 5. Deep Technical Explanation: The Two Security Lessons of MTU/Fragmentation

MTU and fragmentation yield two distinct security lessons, both instances of broader themes:

**1. Over-blocking a protocol for "security" causes outages (the ICMP/PMTUD lesson).** The instinct to
"block ICMP for security" (because ping is used in reconnaissance — Chapter 23) breaks PMTUD, causing
blackholes that manifest as mysterious application failures (connections hang on large transfers). This is a
concrete, common example of a security control causing an availability failure through over-application, and
the fix is **precise filtering** (allow the specific ICMP types PMTUD needs — type 3 code 4 for IPv4,
Packet Too Big for IPv6) rather than **blanket blocking**. The general lesson, which recurs throughout the
book (e.g. over-broad deny rules, over-aggressive WAF rules): **security controls must be precise; blanket
blocking of a protocol that has essential functions causes collateral damage.** ICMP is not just ping —
critical control-plane functions (PMTUD, error reporting) depend on it (Chapter 23), and blocking it all is
a classic over-correction.

**2. Reassembly ambiguity is an evasion/DoS surface (the fragmentation lesson).** Fragmentation splits a
packet, and reassembly must reconstruct it — but *how* it reconstructs (handling overlaps, tiny fragments,
malformed offsets) can differ between systems, and reassembly consumes state. This yields: **evasion** (an
IDS/firewall reassembling differently than the target sees benign content while the target reassembles a
malicious payload — the "two parties interpret the same bytes differently" root cause, at the fragment
layer, the same as encoding bypass in Chapter 7 and request smuggling in Chapter 57) and **DoS**
(reassembly-buffer bugs like Ping of Death/teardrop, and fragment-flood state exhaustion). The defensive
response is to **minimize fragmentation** (DF + PMTUD; IPv6 forbids router fragmentation), **reassemble
consistently before inspecting** (or drop overlapping/tiny fragments) in firewalls/IDS, and **patch
reassembly code**. The general lesson: **fragmentation, like any splitting-and-reconstructing process,
introduces interpretation ambiguity and stateful reassembly — both attack surfaces — so minimize it and
normalize before inspecting.**

The unifying insight: MTU/fragmentation is where two recurring themes meet — **precise-not-blanket
filtering** (don't over-block ICMP, breaking PMTUD) and **interpretation ambiguity as an evasion surface**
(fragment reassembly differences). Both are broader than MTU: precise filtering applies to every firewall/
WAF rule, and interpretation ambiguity applies to every place two systems parse the same data (encoding,
request framing, fragments). A cloud security engineer takes from this chapter the practical ability to
diagnose blackholes (small works/large hangs → MTU/PMTUD/ICMP), the discipline to filter ICMP precisely,
the awareness that encapsulation (endemic in cloud) reduces MTU, and the knowledge that fragmentation is a
minimized-by-design attack surface.

---

## 6. Internals: Observing MTU and Fragmentation

### 6.1 Check and test MTU

```bash
$ ip link show eth0 | grep mtu                    # the interface MTU (Chapter 8)
2: eth0: <...> mtu 1500 ...

# Test the path MTU by sending DF (don't-fragment) packets of increasing size:
$ ping -M do -s 1472 -c1 <dest>                    # 1472 payload + 28 (ICMP+IP) = 1500 (fits Ethernet)
$ ping -M do -s 1473 -c1 <dest>                    # 1473+28 = 1501 > 1500 -> "message too long" or dropped
# If 1472 works but 1473 fails with "Frag needed and DF set", the path MTU is ~1500.
# If large sizes fail SILENTLY (timeout) but small work -> PMTU BLACKHOLE (ICMP blocked, §4.4).
```

The `ping -M do -s <size>` test is the definitive MTU/blackhole diagnostic: `-M do` sets DF, `-s` sets the
payload size. Binary-searching the size that starts failing finds the path MTU; a *silent* failure (timeout
rather than a "frag needed" message) indicates a PMTU blackhole (ICMP blocked).

### 6.2 See fragmentation and the DF bit

```bash
$ sudo tcpdump -n -v 'ip[6:2] & 0x3fff != 0 or ip[6] & 0x20 != 0'   # fragmented or MF-set packets
# In verbose tcpdump output, look for "flags [+]" (MF set), "offset N" (a fragment), "DF" (don't fragment).
$ tcpdump -n -v 'host <dest>' | grep -E 'DF|frag|offset'
```

You decoded the DF flag by hand in Chapter 7 §5 (`40 00` → DF set); here tcpdump shows it and any
fragmentation. Seeing fragments (offset/MF) indicates en-route fragmentation is happening (a path-MTU
mismatch without PMTUD); seeing DF set is normal for TCP (PMTUD in use).

### 6.3 Diagnose a blackhole (the "small works, large hangs" symptom)

```bash
# The classic blackhole test: small transfers work, large ones hang.
$ curl -s https://<dest>/small-file      # works (small packets fit)
$ curl -s https://<dest>/large-file      # HANGS (large DF packets dropped, ICMP blocked -> blackhole)
# Confirm with the DF ping test (§6.1): if large DF pings fail silently, it's a PMTU blackhole.
# Check for ICMP blocking on the path (a firewall dropping type 3 code 4 — Chapter 23).
```

This symptom — small works, large hangs, often only over a VPN/tunnel/overlay — is the signature to
recognize instantly. The cause is almost always MTU/PMTUD/ICMP, and the diagnosis is the DF ping test.

### 6.4 MSS clamping and overlay MTU (the fixes)

```bash
# MSS clamping (on a Linux router/tunnel endpoint) — the tunnel/VPN fix (§4.5):
$ sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu
# Or clamp to a specific value for a known tunnel MTU:
$ sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1400

# Kubernetes/overlay: check the pod MTU (should be reduced for the CNI's encapsulation):
$ kubectl run mtu-test --rm -it --image=nicolaka/netshoot -- ip link show eth0 | grep mtu  # e.g. 1450
```

MSS clamping (`--clamp-mss-to-pmtu` or `--set-mss`) is the standard tunnel/VPN MTU fix (§4.5); checking the
pod/overlay MTU diagnoses container-networking MTU issues (Chapter 103). These are the practical remedies for
the encapsulation-reduced-MTU problem.

---

## 7. Real-World Example: MTU Issues in the Ledger Environments

**Where Ledger hits MTU/fragmentation issues:**

- **VPN / hybrid connectivity (Chapter 77):** if Ledger connects on-prem to AWS via Site-to-Site VPN, the
  VPN's encapsulation reduces effective MTU (§4.1). Without **MSS clamping** (§4.5), large packets over the
  VPN are dropped or blackholed — the "small works, large hangs" symptom. AWS's VPN and TGW typically handle
  this, but custom VPN appliances need MSS clamping configured.
- **Kubernetes/EKS overlay (Chapter 103):** the CNI's overlay (VXLAN-style) reduces pod MTU below 1500
  (e.g. 1450). If misconfigured (pod MTU not reduced), pods experience the blackhole symptom on large
  transfers — a common EKS/Kubernetes networking bug. The fix is correct CNI MTU configuration or MSS
  clamping.
- **Jumbo frames within the VPC:** if Ledger enables jumbo frames (9001) for high-throughput intra-VPC
  traffic (e.g. to RDS or between microservices), traffic *leaving* the VPC (internet, some peering) still
  uses 1500 — a mismatch that causes issues for external-bound large packets if not handled (§4.6).
- **ICMP blocking:** if Ledger (or a security team) blocks *all* ICMP on security groups/NACLs/firewalls "for
  security," PMTUD breaks and blackholes appear — a security control causing an outage (§4.4, §5). The fix is
  to allow the specific ICMP PMTUD needs (type 3 code 4 IPv4, Packet Too Big IPv6), not blanket-block ICMP
  (Chapter 23).
- **Fragmentation attacks:** Ledger's edge (WAF, security groups, NACLs, Network Firewall) should handle
  fragments safely — reassemble before inspecting, or drop overlapping/tiny fragments — to prevent evasion
  and reassembly-based DoS (§4.3).

The Ledger takeaway: **MTU/fragmentation issues cluster wherever encapsulation happens (VPN, overlay, jumbo
frames) — endemic in cloud — producing the "small works, large hangs" blackhole symptom, fixed by MSS
clamping / correct overlay MTU and by allowing (not blanket-blocking) the ICMP PMTUD needs; and
fragmentation is a minimized-by-design attack surface (evasion, DoS) that the edge must handle by
reassembling/normalizing before inspecting.** The two security lessons — precise ICMP filtering (not blanket
blocking) and fragment-reassembly hygiene — are the practical takeaways.

---

## 8. Hands-On Demonstration

### LAB 22.1 — MTU, PMTUD, and Diagnosing a Blackhole

**Objective.** Determine the path MTU with DF pings, observe fragmentation, reproduce a PMTU blackhole by
blocking ICMP, and fix it (allow the necessary ICMP / MSS clamping) — building the ability to diagnose the
"small works, large hangs" symptom.

**Cost.** Free. **Environment.** ENV-1 + ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Check interface MTU and test path MTU.*

```bash
ip link show | grep -E 'mtu' | head
# Binary-search the path MTU with DF pings (§6.1):
ping -M do -s 1472 -c1 8.8.8.8    # 1500 total -> should work on standard Ethernet
ping -M do -s 1473 -c1 8.8.8.8    # 1501 total -> "message too long" locally, or dropped upstream
```

**Expected:** 1472 works, 1473 fails (locally with "message too long," or upstream with a frag-needed
message) — the path MTU is ~1500.

*Step 2 — Create a reduced-MTU link and observe the effect (isolated).*

```bash
docker network create --opt com.docker.network.driver.mtu=1400 mtulab 2>/dev/null || \
  docker network create mtulab
docker run -d --name a --network mtulab nicolaka/netshoot sleep 3600
docker run -d --name b --network mtulab nicolaka/netshoot sleep 3600
docker exec a ip link show eth0 | grep mtu     # reduced MTU (e.g. 1400) -- simulates a tunnel/overlay
B=$(docker inspect -f '{{(index .NetworkSettings.Networks "mtulab").IPAddress}}' b)
docker exec a ping -M do -s 1372 -c1 $B         # 1400 total -> works
docker exec a ping -M do -s 1400 -c1 $B         # exceeds 1400 -> fails (path MTU is 1400)
```

*Step 3 — Reproduce a PMTU blackhole (block ICMP).*

```bash
# Block the ICMP "frag needed" so PMTUD cannot signal -> blackhole for large DF packets:
docker exec b sh -c 'apk add --no-cache iptables 2>/dev/null; iptables -A INPUT -p icmp --icmp-type fragmentation-needed -j DROP' 2>/dev/null || \
  echo "(demonstrating the concept: blocking ICMP frag-needed breaks PMTUD)"
# Now large DF packets are dropped SILENTLY (no ICMP signal) -> the sender doesn't shrink -> blackhole.
docker exec a ping -M do -s 1500 -c2 -W2 $B      # times out silently (blackhole symptom)
```

**Expected:** with the ICMP frag-needed blocked, large DF packets fail silently (timeout) instead of
producing a "frag needed" message — the blackhole. Small packets still work. This is the "small works, large
hangs" symptom reproduced.

*Step 4 — Fix it (allow the ICMP / clamp MSS).*

```bash
# Fix 1: allow the ICMP PMTUD needs (don't blanket-block ICMP — §4.4, §5):
docker exec b sh -c 'iptables -D INPUT -p icmp --icmp-type fragmentation-needed -j DROP' 2>/dev/null
# Fix 2 (for tunnels): MSS clamping so TCP never sends too-large segments (§4.5):
docker exec a sh -c 'iptables -t mangle -A OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu' 2>/dev/null
docker exec a ping -M do -s 1372 -c1 $B          # works within MTU; larger fails cleanly (with signal)
```

**Security implications.** Write down: (a) the "small works, large hangs" blackhole symptom and its cause
(MTU + DF + blocked ICMP); (b) blocking ALL ICMP breaks PMTUD (a security control causing an outage) — the
fix is precise filtering (allow type 3 code 4 / Packet Too Big), not blanket blocking; (c) encapsulation
(tunnel/overlay/VPN) reduces effective MTU — endemic in cloud; (d) MSS clamping is the tunnel fix; (e)
fragmentation is a minimized attack surface (evasion/DoS — §4.3).

**Cleanup.**
```bash
docker rm -f a b 2>/dev/null; docker network rm mtulab 2>/dev/null
```

---

## 9. Security Implications

- **MTU limits packet size per link; the path MTU is the minimum along the path.** Encapsulation
  (VPN/overlay/jumbo-frame mismatch) reduces effective MTU — endemic in cloud/containers — causing MTU bugs.
- **PMTUD depends on ICMP; blocking all ICMP breaks it, causing blackholes** where large DF packets vanish
  silently (the "small works, large hangs" symptom). This is a **security control (ICMP blocking) causing an
  availability failure** — the fix is precise filtering (allow the specific ICMP PMTUD needs), not blanket
  blocking. **Precise-not-blanket filtering** is the recurring lesson.
- **Fragmentation is an attack surface** — reassembly bugs (Ping of Death, teardrop), IDS/firewall evasion
  (overlapping/tiny fragments — the "two parties interpret differently" root cause, Chapters 7, 57), and
  fragment-flood DoS. Modern practice minimizes it (DF + PMTUD; IPv6 forbids router fragmentation).
- **MSS clamping is the tunnel/VPN/overlay fix** — ensures TCP never sends segments too large for the
  reduced path MTU, sidestepping fragmentation/PMTUD for TCP.
- **The blackhole symptom is a diagnostic skill** — small transfers work, large ones hang, often only over
  encapsulated paths; the DF ping test (`ping -M do -s`) confirms it.
- **Firewalls/IDS must reassemble/normalize fragments before inspecting** (or drop overlapping/tiny
  fragments) to prevent evasion.

---

## 10. Attack Scenarios

1. **PMTU blackhole (via ICMP over-blocking)** (§4.4): blocking all ICMP breaks PMTUD, causing large-packet
   blackholes — a self-inflicted availability failure, or an attacker inducing it by dropping ICMP on a path
   they control. Defense: allow the specific ICMP; MSS clamping; PLPMTUD.
2. **Overlapping-fragment IDS/firewall evasion** (§4.3): fragments overlap with conflicting data; the IDS
   and target reassemble differently, so a malicious payload evades inspection. Defense: consistent
   reassembly before inspection; drop overlapping fragments.
3. **Tiny-fragment evasion** (§4.3): split so the TCP header spans fragments, evading header-based
   filtering. Defense: require the full TCP header in the first fragment; drop tiny fragments.
4. **Reassembly-buffer attacks (Ping of Death, teardrop)** (§4.3): malformed/oversized fragments crashing
   reassembly code. Defense: patch (long-fixed); drop malformed fragments.
5. **Fragment-flood DoS** (§4.3): flood incomplete fragments to exhaust reassembly buffers/state. Defense:
   fragment reassembly limits/timeouts; rate limiting.
6. **MTU-based blackholing as DoS** (§4.4): an attacker on a path forces MTU issues (dropping ICMP, or MTU
   manipulation) to hang large transfers. Defense: MSS clamping, monitoring, allowing PMTUD ICMP.

---

## 11. Defensive Techniques

- **Allow the ICMP that PMTUD needs — do not blanket-block ICMP.** Permit ICMP type 3 code 4 ("Fragmentation
  Needed") for IPv4 and ICMPv6 "Packet Too Big" for IPv6 (essential — IPv6 has no router fragmentation) on
  firewalls, security groups, and NACLs. Blanket ICMP blocking causes blackholes; precise filtering avoids
  them while still restricting reconnaissance ICMP (Chapter 23).
- **Use MSS clamping on tunnels/VPNs/overlays** (`--clamp-mss-to-pmtu` or `--set-mss`) so TCP never sends
  segments too large for the reduced path MTU — the reliable fix for the encapsulation-MTU problem (§4.5).
- **Configure correct overlay/pod MTU** in Kubernetes/CNI (reduced for encapsulation) to prevent the pod
  blackhole symptom (Chapter 103).
- **Minimize fragmentation** — rely on DF + PMTUD (default for TCP); prefer IPv6's sender-only fragmentation
  model; drop fragments where feasible for services that never legitimately fragment.
- **Reassemble/normalize fragments before inspecting** in firewalls/IDS (or drop overlapping/tiny fragments)
  to prevent evasion; set reassembly buffer limits/timeouts to prevent fragment-flood DoS.
- **Be cautious with jumbo frames** — ensure end-to-end support; remember jumbo frames within a VPC do not
  apply to traffic leaving it (§4.6).
- **Recognize and diagnose the blackhole symptom** — "small works, large hangs" → MTU/PMTUD/ICMP; use the DF
  ping test (`ping -M do -s`); check for ICMP blocking and encapsulation on the path. Monitor for it (it
  presents as intermittent application failures).

---

## 12. Production Architecture

MTU/fragmentation handling, VPS/cloud/containers:

```
 SCENARIO                 MTU CONSIDERATION                DEFENSE / HANDLING
 ---------------------    ------------------------------   ---------------------------------------
 standard Ethernet        1500 MTU                          DF + PMTUD (allow ICMP frag-needed)
 VPN / hybrid (Ch77)      encapsulation reduces MTU         MSS clamping; AWS VPN/TGW handles it
 Kubernetes/overlay (103) VXLAN-style reduces pod MTU       correct CNI MTU / MSS clamping
 jumbo frames in VPC      9001 intra-VPC, 1500 leaving      handle the boundary; don't assume 9001 external
 firewalls / ICMP         blocking all ICMP -> blackholes   allow type 3 code 4 / Packet Too Big (precise)
 fragmentation            evasion + reassembly DoS          reassemble/normalize before inspect; drop bad frags
 IPv6                     no router fragmentation           Packet Too Big ICMP is ESSENTIAL (allow it)
```

The architectural principle: **MTU/fragmentation issues cluster at encapsulation boundaries (VPN, overlay,
jumbo-frame mismatch) — endemic in cloud/containers — and the two security disciplines are precise ICMP
filtering (allow PMTUD's ICMP, never blanket-block) and fragment-reassembly hygiene (minimize
fragmentation, reassemble/normalize before inspecting).** Design encapsulated paths with MSS clamping or
correct reduced MTU, allow the essential PMTUD ICMP (especially for IPv6), and handle fragments safely at
inspection points. The recurring lessons — precise-not-blanket filtering and interpretation-ambiguity as an
evasion surface — make MTU/fragmentation a small but instructive intersection of availability and security,
and the "small works, large hangs" blackhole is a diagnostic skill every network-touching engineer needs.

---

## 13. Common Mistakes

1. **Blocking all ICMP "for security"** — breaking PMTUD and causing blackholes (§4.4, §5); the fix is
   precise filtering.
2. **Not using MSS clamping on tunnels/VPNs/overlays** — large packets blackhole over encapsulated paths
   (§4.5).
3. **Misconfigured overlay/pod MTU** in Kubernetes — the pod blackhole symptom (Chapter 103).
4. **Assuming jumbo frames work end-to-end** — they don't for traffic leaving the VPC (§4.6).
5. **Not recognizing the "small works, large hangs" symptom** — misdiagnosing an MTU blackhole as an
   application bug.
6. **Firewalls/IDS inspecting fragments without consistent reassembly** — evasion via overlapping/tiny
   fragments (§4.3).
7. **No reassembly limits/timeouts** — fragment-flood DoS (§4.3).
8. **Forgetting IPv6 needs Packet Too Big ICMP** — IPv6 has no router fragmentation, so blocking it breaks
   IPv6 PMTUD entirely (§4.4).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Small requests work, large ones hang | PMTU blackhole (ICMP blocked or MTU mismatch) | `ping -M do -s <big>` (silent fail = blackhole); check ICMP filtering, encapsulation |
| Connection establishes then stalls on data | MTU/PMTUD (handshake fits, data packets too big) | DF ping test; MSS clamping; overlay MTU |
| Issues only over VPN/tunnel/overlay | encapsulation reduced MTU | check tunnel MTU; apply MSS clamping (§4.5) |
| Kubernetes pods hang on large transfers | pod/overlay MTU misconfigured | `ip link` in pod; check CNI MTU (Chapter 103) |
| Fragments in captures / performance loss | en-route fragmentation (MTU mismatch, no PMTUD) | tcpdump for offset/MF; enable/allow PMTUD; MSS clamp |
| IPv6 large packets fail, IPv4 works | Packet Too Big ICMP blocked (IPv6 needs it) | allow ICMPv6 Packet Too Big (§4.4) |
| IDS missing attacks in fragments | fragment evasion (overlapping/tiny) | ensure reassembly before inspection; drop bad fragments |

---

## 15. Practical Lab

Lab 22.1 is in §8. Register it in the lab index. Extension: set up a reduced-MTU tunnel (or the Docker
reduced-MTU network), reproduce the blackhole with ICMP blocked, then fix it two ways — (1) allowing the
ICMP frag-needed and (2) MSS clamping — and confirm large transfers work with each. This makes the two fixes
(precise ICMP allowance vs MSS clamping) concrete and teaches the blackhole diagnosis that so often stumps
engineers.

---

## 16. Exercises

### Concept questions

**22.1** Explain MTU, path MTU, and why encapsulation (VPN/overlay) reduces effective MTU. Where is this
endemic?

**22.2** Explain PMTUD and how it depends on ICMP. What is a PMTU blackhole, and why does blocking all ICMP
cause it?

**22.3** Explain three fragmentation-based attacks and why fragmentation is a minimized-by-design attack
surface.

**22.4** What is MSS clamping, and why is it the reliable fix for tunnel/VPN MTU issues?

**22.5** Explain the two security lessons of MTU/fragmentation (precise-not-blanket filtering; reassembly
ambiguity) and how each generalizes beyond MTU.

### Debugging problems

**22.6** A service works for small requests but hangs on large ones, only over the VPN. Diagnose and give
two fixes.

**22.7** Kubernetes pods hang on large data transfers between nodes; small ones work. Diagnose.

**22.8** After a security team "blocked all ICMP for hardening," users report intermittent failures on large
downloads. Explain and fix.

### Security scenarios

**22.9** Explain how an attacker uses fragment overlap to evade an IDS, and how you would configure
inspection to prevent it.

**22.10** A security policy proposes blocking all ICMP. Evaluate it, explain the collateral damage, and
propose the correct precise policy.

### Architecture questions

**22.11** Design MTU handling for a hybrid architecture (on-prem + VPC + VPN + Kubernetes overlay), naming
the fix for each encapsulation boundary.

**22.12** Explain how the "precise-not-blanket filtering" lesson from ICMP/PMTUD applies to firewall/WAF
rule design generally.

### Hands-on exercises

**22.13** Determine the path MTU to several destinations with the DF ping test and identify any blackholes.

**22.14** Reproduce a PMTU blackhole by blocking ICMP frag-needed and fix it two ways (allow ICMP; MSS
clamp).

**22.15** Inspect the pod/overlay MTU in a Kubernetes (or Docker overlay) environment and explain any
reduction.

### Interview questions

**22.16** "A connection establishes but hangs on large transfers. What's your first hypothesis?"

**22.17** "Why is blocking all ICMP a bad idea?"

**22.18** "What is MSS clamping and when do you use it?"

**22.19** "How is fragmentation an attack surface?"

**22.20** "Why are MTU issues common in cloud and container environments?"

---

## 17. Summary

- **MTU** is the largest payload a link carries (Ethernet 1500; jumbo 9000; **encapsulation — VPN/overlay/
  tunnel — reduces effective MTU below 1500**), and the **path MTU** is the minimum along the route.
  Encapsulation-reduced MTU is **endemic in cloud/containers** (VXLAN overlays, VPNs, jumbo-frame mismatch).
- Packets exceeding a link's MTU are **fragmented** (DF clear) or **dropped with an ICMP "Fragmentation
  Needed"** (DF set). **Modern networking minimizes fragmentation** via DF + **PMTUD**; **IPv6 forbids
  router fragmentation** (sender-only).
- **PMTUD depends on ICMP; blocking all ICMP breaks it, causing PMTU blackholes** — large DF packets vanish
  silently, producing the **"small works, large hangs"** symptom. This is a **security control (ICMP
  blocking) causing an availability failure**; the fix is **precise filtering** (allow ICMP type 3 code 4 /
  ICMPv6 Packet Too Big — essential for IPv6), **not blanket blocking**.
- **Fragmentation is an attack surface** — reassembly bugs (Ping of Death, teardrop), IDS/firewall
  **evasion** (overlapping/tiny fragments — the "two parties interpret differently" root cause, Chapters 7,
  57), and **fragment-flood DoS** — so minimize it and **reassemble/normalize before inspecting**.
- **MSS clamping** (`--clamp-mss-to-pmtu`/`--set-mss`) is the reliable **tunnel/VPN/overlay fix** — TCP never
  sends segments too large for the reduced path MTU.
- The two security lessons — **precise-not-blanket filtering** (don't over-block ICMP) and
  **interpretation-ambiguity as an evasion surface** (fragment reassembly) — generalize far beyond MTU. The
  **blackhole diagnosis** (`ping -M do -s`) is a core skill.

---

## 18. Knowledge Check

1. What is MTU, path MTU, and why does encapsulation reduce it? (§4.1)
2. How does PMTUD work and what does it depend on? (§4.4)
3. What is a PMTU blackhole and its symptom? (§4.4, §6.3)
4. Why does blocking all ICMP cause blackholes, and what's the correct policy? (§4.4, §5, §11)
5. Name three fragmentation-based attacks. (§4.3)
6. What is MSS clamping and when is it used? (§4.5)
7. Why does IPv6 especially need Packet Too Big ICMP? (§4.4)
8. What is the "small works, large hangs" symptom and its cause? (§6.3)
9. How does fragment overlap evade IDS? (§4.3, §5)
10. What are the two generalizable security lessons of this chapter? (§5)

---

## 19. Further Exploration

- RFC 1191 (PMTUD), RFC 8201 (IPv6 PMTUD), RFC 4821 (PLPMTUD — PMTUD without ICMP) — the mechanics and the
  ICMP-independent alternative.
- Read about overlapping-fragment IDS evasion (the classic Ptacek & Newsham paper "Insertion, Evasion, and
  Denial of Service") — the definitive treatment of reassembly-ambiguity evasion (bridges to Chapter 57).
- The Ping of Death and teardrop advisories — the reassembly-bug archetypes.
- Kubernetes CNI MTU documentation (Calico/Flannel/AWS VPC CNI) — the overlay-MTU handling (Chapter 103).
- Practice the DF ping test (`ping -M do -s`) to various destinations and over any VPN you use — build the
  blackhole-diagnosis reflex.
- Chapter 23 next (ICMP) — the protocol PMTUD depends on, and the precise-vs-blanket ICMP filtering question
  in full.

---

## Solutions

### 22.2
PMTUD (Path MTU Discovery) lets a sender find the smallest MTU along a path so it can size packets to avoid
fragmentation. Mechanism: the sender sets the **DF (Don't Fragment)** bit on packets; if a router's next
link has a smaller MTU than the packet, it cannot fragment (DF is set), so it **drops the packet and sends an
ICMP "Fragmentation Needed and DF set" (type 3, code 4)** back to the sender, including the constraining
link's MTU; the sender lowers its path-MTU estimate and retransmits smaller packets, converging on the path
MTU. It **depends on ICMP** — specifically that "Fragmentation Needed" message reaching the sender. A **PMTU
blackhole** occurs when that ICMP is blocked (commonly by a firewall blocking all ICMP): the sender never
learns to shrink its packets, so it keeps sending large DF packets that keep being dropped **silently** (no
signal reaches it). The symptom is that the connection establishes (small handshake packets fit) but hangs
when large data flows (large packets vanish) — "small works, large hangs." Blocking all ICMP causes this
because PMTUD's essential signaling message is an ICMP type, so blanket ICMP blocking removes PMTUD's ability
to function; the fix is to allow the specific ICMP (type 3 code 4 for IPv4, Packet Too Big for IPv6 — which
is essential since IPv6 has no router fragmentation) rather than blocking all ICMP.

### 22.10
Blocking all ICMP is a common but harmful over-correction. Rationale offered: ICMP (ping, traceroute) is
used in reconnaissance (Chapter 23), so blocking it "reduces the attack surface." Collateral damage: ICMP is
not just ping — several ICMP types are **essential control-plane functions**, most importantly **PMTUD**
(which relies on ICMP "Fragmentation Needed" type 3 code 4 for IPv4 and "Packet Too Big" for IPv6). Blocking
all ICMP breaks PMTUD, causing **PMTU blackholes** — large packets are silently dropped and connections hang
on large transfers ("small works, large hangs"), a confusing, intermittent availability failure. For IPv6 it
is worse: IPv6 has no router fragmentation, so PMTUD (via Packet Too Big) is the *only* mechanism, and
blocking it breaks IPv6 connectivity for large packets entirely. Other useful ICMP includes destination-
unreachable messages (fast failure signaling). The correct precise policy: **allow the essential ICMP types**
— type 3 code 4 (Fragmentation Needed, IPv4) and ICMPv6 Packet Too Big (essential), and generally
destination-unreachable and time-exceeded (traceroute/error signaling, per risk tolerance) — while
optionally rate-limiting or restricting echo-request/reply (ping) if reconnaissance is a concern. This
achieves the security goal (limiting reconnaissance ping) without breaking PMTUD. The lesson generalizes:
security controls must be **precise**, not blanket; blocking an entire protocol that has essential functions
causes availability failures (the same reasoning applies to over-broad deny rules and over-aggressive WAF
rules).

### 22.16
My first hypothesis is an **MTU / Path MTU Discovery issue** — specifically a **PMTU blackhole**. The
signature (connection establishes but hangs on large transfers) is classic: the handshake and small packets
fit within the path MTU and succeed, but large data packets exceed a smaller MTU somewhere on the path (often
an encapsulated segment — VPN, overlay, tunnel — that reduced the effective MTU), and because the DF bit is
set (modern default) those packets are dropped; if the ICMP "Fragmentation Needed" that PMTUD relies on is
blocked (a common firewall over-correction), the sender never learns to shrink its packets, so they vanish
silently and the connection stalls. To confirm: run the DF ping test (`ping -M do -s <large>` to the
destination) — if large sizes fail *silently* (timeout) while small ones work, it is a PMTU blackhole; also
check whether the path involves a VPN/tunnel/overlay (reduced MTU) and whether ICMP is being blocked. Fixes:
allow the specific ICMP PMTUD needs (type 3 code 4 / Packet Too Big — precise, not blanket), apply **MSS
clamping** on the tunnel/overlay endpoint so TCP never sends oversized segments, and/or set the correct
reduced MTU on the encapsulated interface. This is one of the most common "it works sometimes" bugs, and
recognizing the small-works/large-hangs signature as an MTU issue (rather than an application bug) is the key
diagnostic skill.

### 22.19
Fragmentation is an attack surface in three ways. (1) **Reassembly bugs**: because the destination must
reassemble fragments (buffering them and reconstructing per the identification/offset/MF fields), malformed
fragments can crash or corrupt the reassembly code — classic examples are **Ping of Death** (a fragmented
packet that reassembles to exceed the maximum IP size, overflowing the buffer) and **teardrop** (overlapping/
malformed offsets crashing the reassembler). (2) **IDS/firewall evasion**: an attacker splits a payload so
that the inspecting device and the target **reassemble differently** — e.g. **overlapping fragments** with
conflicting data (the IDS sees benign content while the target reconstructs a malicious payload), or **tiny
fragments** that split the TCP header across fragments so a header-filtering firewall cannot see the ports/
flags in the first fragment. This is the "two parties interpret the same bytes differently" root cause (the
same as encoding bypass in Chapter 7 and request smuggling in Chapter 57), applied at the fragment layer. (3)
**Resource-exhaustion DoS**: reassembly is stateful (the destination buffers incomplete fragments until the
packet is complete or times out), so an attacker floods **incomplete fragments** to exhaust reassembly
buffers/state. Because of all this, fragmentation is **minimized by design** in modern networking (TCP uses
DF + PMTUD to avoid it; IPv6 forbids router fragmentation entirely), and defenses are to **minimize
fragmentation, reassemble/normalize consistently before inspecting** (or drop overlapping/tiny fragments),
set **reassembly limits/timeouts** (against floods), and **patch** reassembly code. The unifying lesson:
splitting-and-reconstructing introduces interpretation ambiguity and stateful reassembly — both attack
surfaces — so minimize it and normalize before inspecting.

---

*Next: Chapter 23 — ICMP, Ping, and Traceroute: Diagnostics and Their Abuse. Having seen PMTUD depend on
ICMP, we cover ICMP fully — its essential functions (error signaling, PMTUD), its diagnostic tools (ping,
traceroute), its abuse (recon, tunneling, redirects, smurf), and the precise-vs-blanket filtering question
that Chapter 22 raised.*
