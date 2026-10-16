# GLOSSARY

Every important technical term in the book, with a definition, why it matters to a cloud
security engineer, related concepts, and where it is taught.

Terms are added as chapters are written. Within each letter, newer entries are appended,
so ordering inside a letter is by introduction rather than strictly alphabetical.

---

## A

**ASLR (Address Space Layout Randomization)** — randomizing the base addresses of the
stack, heap, mmap region and executable at each execution.
*Why it matters:* it is why an attacker who controls the instruction pointer still cannot
reliably build an exploit — and why an information leak (a stack trace in a 500 response)
is a security bug rather than untidiness.
*Related:* W^X, ROP, PIE, information disclosure. *Taught in:* Ch. 1 §11.2.

**Address space** — the set of virtual addresses a process can use, defined by its page
tables.
*Why it matters:* the process boundary *is* an address-space boundary, enforced by the MMU.
*Related:* MMU, page table, CR3, context switch. *Taught in:* Ch. 1 §4.3–4.4.

## B

## C

**Capabilities (Linux)** — root's powers split into ~40 discrete units (e.g.
`CAP_NET_BIND_SERVICE`, `CAP_SYS_ADMIN`, `CAP_NET_RAW`) that can be granted or dropped
individually.
*Why it matters:* they are a per-operation permission model — the OS-level equivalent of a
scoped IAM policy — and "drop ALL, add none" is the correct default for most workloads.
*Related:* setuid, seccomp, bounding set, least privilege. *Taught in:* Ch. 2 §4.2, §8.3; Ch. 33.

**cgroups** — kernel resource-accounting and limiting groups (CPU, memory, PIDs, I/O).
*Why it matters:* they bound denial-of-service by one workload against others and are one of
the five container containment dimensions.
*Related:* namespaces, containers, OOM, RSS. *Taught in:* Ch. 2 §3; Ch. 38; Ch. 93.

**Cache side channel** — inferring secret data by measuring how long memory accesses take,
because cached lines are faster.
*Why it matters:* it defeats isolation that hardware otherwise enforces, which is why
untrusted multi-tenant workloads on shared cores carry real risk.
*Related:* Spectre, Meltdown, constant-time comparison, L3 cache. *Taught in:* Ch. 1 §4.5, §10.3.

**Context switch** — saving one thread's CPU state and restoring another's; across
processes, the page-table root register changes too.
*Why it matters:* it is where address-space isolation is applied, and where KPTI's cost is paid.
*Related:* TLB, CR3, scheduler, KPTI. *Taught in:* Ch. 1 §5.1.

**Copy-on-write (COW)** — sharing pages read-only after fork, copying only on first write.
*Why it matters:* makes fork cheap; also means secrets in memory before a fork are
inherited by every child.
*Related:* page fault, fork, page table. *Taught in:* Ch. 1 §5.2.

**Crypto-shredding** — destroying data by destroying its encryption key rather than
overwriting the data.
*Why it matters:* SSDs and cloud storage cannot be reliably overwritten in place, so key
destruction is the only dependable delete.
*Related:* KMS, encryption at rest, flash translation layer. *Taught in:* Ch. 1 §4.6; Ch. 80.

## D

**Defense in depth** — layering independent controls so a failure at one is caught by another.
*Why it matters:* the §5.1 request-map table shows which layers can and cannot stop a given
attack; depth means at least one *can*, plus a backstop.
*Related:* isolation ladder, blast radius, the request map. *Taught in:* Ch. 4 §5.1; Ch. 43.

## E

**Encryption at rest** — encrypting data as stored on a medium, transparently decrypted for
authorized readers.
*Why it matters:* it protects stolen disks, snapshots and decommissioned media — and
nothing else. Stating that limit precisely is a core professional skill.
*Related:* KMS, crypto-shredding, page cache. *Taught in:* Ch. 1 §4.6, §7; Ch. 80.

## F

**File descriptor (fd)** — a per-process integer index into the kernel's table of open
files, sockets, pipes and devices.
*Why it matters:* an fd *is* a capability — access is checked at `open()`, not at each use —
so fds survive privilege drops and (without `O_CLOEXEC`) `execve`, making leaked fds an
escalation path.
*Related:* socket, capability, O_CLOEXEC, privilege drop. *Taught in:* Ch. 2 §4.5; Ch. 3.

## G

## H

**Hypervisor** — software/hardware layer running multiple guest VMs on one physical machine,
each believing it owns the hardware.
*Why it matters:* the VM isolation boundary is enforced here via CPU virtualization extensions
and second-level address translation (EPT/NPT) — hardware-enforced, small attack surface,
which is why VMs isolate more strongly than containers.
*Related:* VM, EPT/NPT, IOMMU, Nitro, isolation ladder. *Taught in:* Ch. 6 §4.1; Ch. 1 §12.

## I

**IDOR / BOLA (Broken Object/Function Level Authorization)** — accessing another user's
resource by supplying its identifier, because the app authenticates but fails to authorize
per-resource.
*Why it matters:* the #1 web vulnerability class; it passes every network/transport/authN
control because the attacker is a legitimate authenticated user — only Stop 6 authorization
(and RLS as backstop) catches it.
*Related:* authorization, authentication, the request map, RLS. *Taught in:* Ch. 4 §4/§5.1; Ch. 51.

**Injection** — untrusted data from one layer interpreted as structure/instructions by the
next (SQL, shell command, HTML/JS, LLM prompt).
*Why it matters:* one abstract shape underlies SQLi, command injection, XSS, and prompt
injection; the universal fix is to separate the data channel from the instruction channel
(parameterization, encoding, argument arrays).
*Related:* the request map, parameterized query, XSS, prompt injection. *Taught in:* Ch. 4 §9; Ch. 46–48, 136.

**Control plane** — the API surface through which cloud resources are provisioned, configured,
and (for managed data services) accessed, as opposed to the data plane.
*Why it matters:* in the cloud it is the primary attack surface — an attacker with IAM
permissions reaches data over the public API with no network access; the control plane is also
the audit surface (CloudTrail).
*Related:* IAM, shared responsibility, CloudTrail, the perimeter. *Taught in:* Ch. 6 §4.4.

**Isolation ladder** — threads < processes < containers < VMs < hosts < accounts, ordered
by strength of the boundary between workloads.
*Why it matters:* every multi-tenancy and workload-placement decision is a choice of a
rung, traded against cost, latency and operational complexity.
*Related:* namespaces, hypervisor, multi-tenancy, blast radius. *Taught in:* Ch. 1 §5.4.

## J

## K

## L

## M

**microVM** — a minimal, fast-booting virtual machine running a single container-like workload,
giving hardware VM isolation at container-like density (Firecracker, Kata).
*Why it matters:* the middle rung of the isolation ladder and the right answer for untrusted
code that must not share a kernel; AWS Lambda and Fargate run on Firecracker.
*Related:* isolation ladder, hypervisor, container, gVisor. *Taught in:* Ch. 6 §4.3.

**MMU (Memory Management Unit)** — CPU hardware that translates virtual to physical
addresses via page tables on every memory access.
*Why it matters:* process memory isolation is enforced here, in hardware, not by software
checks.
*Related:* page table, PTE, TLB, virtual address. *Taught in:* Ch. 1 §4.3.

**Memory safety** — the property that a program cannot read or write outside the bounds of
valid, live objects.
*Why it matters:* ~70% of serious CVEs in large C/C++ codebases are memory-safety bugs;
choosing a memory-safe language *eliminates* the class instead of detecting instances.
*Related:* buffer overflow, use-after-free, ROP, SCA. *Taught in:* Ch. 1 §5.3, §11.5.

## N

**Namespaces (Linux)** — kernel feature that gives a process an isolated view of a global
resource: PID, network, mount, UTS, IPC, user, cgroup, time.
*Why it matters:* they are what makes a process "a container"; but they hide rather than
protect — the kernel underneath is shared, so they are a hardening boundary, not a trust one.
*Related:* clone, cgroups, container, user namespace. *Taught in:* Ch. 2 §4.1; Ch. 38; Ch. 93.

**no_new_privs** — a per-process flag that permanently blocks gaining privilege via
`execve` (setuid, file capabilities).
*Why it matters:* it forecloses the OS's only privilege-escalation channel and is a required
precondition for an unprivileged process to install a seccomp filter.
*Related:* execve, seccomp, capabilities, allowPrivilegeEscalation. *Taught in:* Ch. 2 §5.1, §11.

**NX / No-Execute bit** — a page-table permission bit marking memory as non-executable.
*Why it matters:* it eliminated shellcode injection into data buffers and forced attackers
into ROP — the clearest example of attackers routing around a control rather than breaking it.
*Related:* W^X, DEP, ROP, PTE. *Taught in:* Ch. 1 §4.3, §11.1.

## O

## P

**Page fault** — a CPU exception raised when a virtual address cannot be translated with
the requested permission.
*Why it matters:* the mechanism behind lazy allocation, copy-on-write, demand paging, guard
pages, and the segfault you get on an illegal access.
*Related:* MMU, PTE, minor/major fault, OOM. *Taught in:* Ch. 1 §5.2.

**Page table / PTE** — the kernel-built tree the MMU walks to translate addresses; a PTE
holds a physical frame number plus permission bits (R/W, User/Supervisor, NX).
*Why it matters:* those bits are where memory security is actually enforced.
*Related:* MMU, CR3, W^X, KPTI. *Taught in:* Ch. 1 §4.3.

**ptrace** — the syscall behind debuggers and `strace`, allowing one process to read/write
another's memory and registers.
*Why it matters:* it defeats process memory isolation for any process of the same UID with no
kernel bug required — the reason to run distinct services as distinct users and to set
`ptrace_scope`.
*Related:* file descriptor, YAMA, isolation ladder, gdb. *Taught in:* Ch. 2 §9.3.

**Privilege ring** — CPU-enforced privilege level; ring 3 is user mode, ring 0 kernel mode,
with the hypervisor beneath both.
*Why it matters:* "root" means ring 0 of one guest — not control of the hypervisor, and not
control of the cloud control plane.
*Related:* system call, hypervisor, shared responsibility. *Taught in:* Ch. 1 §4.2, §12.

## Q

## R

**ROP (Return-Oriented Programming)** — building an exploit from short sequences of
existing executable code ("gadgets") chained by return addresses, writing no new code.
*Why it matters:* it fully respects W^X while fully defeating it; the template for how
attackers bypass rather than break controls.
*Related:* NX, ASLR, stack canary, CFI. *Taught in:* Ch. 1 §10.2.

**RSS vs VSZ** — resident set size (physical memory in use) versus virtual size (address
space reserved).
*Why it matters:* container limits and OOM kills track RSS and cgroup accounting; VSZ is
nearly meaningless for capacity planning.
*Related:* lazy allocation, cgroups, OOM killer. *Taught in:* Ch. 1 §6.2.

## S

**Shared responsibility model** — the division of security duties between cloud provider and
customer, which shifts up the stack per service.
*Why it matters:* the provider absorbs host/kernel/runtime as you move to higher abstractions,
but data, IAM, and configuration are *always* the customer's — which is why misconfiguration
and identity mistakes cause most cloud breaches.
*Related:* control plane, IAM, IaaS/serverless, the responsibility gradient. *Taught in:* Ch. 6 §5.2.

**seccomp (seccomp-bpf)** — a per-process, irreversible filter over which syscalls a process
may make, evaluated by a BPF program before dispatch.
*Why it matters:* it shrinks the reachable kernel attack surface — a stronger control than
patching one CVE, since it covers undiscovered bugs in blocked paths — but sees only syscall
numbers and scalar args, not pointer contents.
*Related:* system call, capabilities, LSM, no_new_privs, io_uring. *Taught in:* Ch. 2 §5.4, §15; Ch. 95, 105.

**Spectre / Meltdown** — transient (speculative) execution attacks leaking data across
privilege boundaries through cache timing.
*Why it matters:* they broke a hardware-enforced boundary, forced KPTI (a permanent
syscall performance tax), and reshaped multi-tenant cloud architecture.
*Related:* cache side channel, KPTI, SMT, Nitro Enclaves. *Taught in:* Ch. 1 §10.3.

**Stack canary** — a random value between locals and the saved return address, verified
before return.
*Why it matters:* detects linear stack smashing; defeated by non-linear writes or canary
disclosure.
*Related:* buffer overflow, ROP, `-fstack-protector`. *Taught in:* Ch. 1 §11.3.

**System call** — the controlled entry point from user mode into the kernel.
*Why it matters:* the only way a process touches the outside world, so it is the natural
place to observe and restrict behavior (strace, seccomp, Falco).
*Related:* ring, seccomp, vDSO. *Taught in:* Ch. 1 §6.3; Ch. 2.

## T

**Three-lens model** — assess any component as a *process* (which user, blast radius), a
*network service* (bind, auth, encryption, reachability), and a *data custodian* (what data,
its access model, encryption).
*Why it matters:* a universal, fast audit checklist that maps onto the request-map layers and
applies to managed cloud services too (via console/API instead of `ss`).
*Related:* insecure defaults, the request map, blast radius. *Taught in:* Ch. 5 §3, §6.

**TLB (Translation Lookaside Buffer)** — a CPU cache of recent virtual-to-physical
translations.
*Why it matters:* address-space switches invalidate it, which is why KPTI cost the industry
measurable performance on syscall-heavy workloads.
*Related:* MMU, context switch, PCID, KPTI. *Taught in:* Ch. 1 §5.1.

## U

## V

## W

**W^X (write xor execute)** — the policy that no memory page is simultaneously writable and
executable.
*Why it matters:* visible directly in `/proc/PID/maps`; an `rwx` mapping in production is
either a JIT or an incident.
*Related:* NX, JIT dual mapping, ROP. *Taught in:* Ch. 1 §4.4, §11.1.

## X

## Y

## Z
