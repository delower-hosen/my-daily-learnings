# Chapter 1 — The Machine Underneath: CPU, Memory, Storage, and the Illusions They Maintain

---

## 1. Why This Matters

You have written software for seven years. In that time you have almost certainly never
needed to know what a page table is, and your code worked fine. That is not an accident —
it is the entire point of the machine. Modern computers are elaborate illusion engines.
They present every process with a private, contiguous, apparently infinite memory space;
a CPU that appears to be running only your code; and files that appear to be sitting
somewhere waiting to be read. None of these things are literally true.

Security is what happens when the illusions leak.

Consider a few incidents you already half-know:

- **Heartbleed (2014)** was not a cryptography failure. TLS was fine. A bounds check was
  missing, so a server returned adjacent heap memory to whoever asked — memory that
  happened to contain other users' session cookies and the server's private key. To
  understand why that memory was *there*, next to the buffer, you need to understand the
  heap.
- **Meltdown and Spectre (2018)** broke the boundary between kernel memory and user
  memory — a boundary enforced by hardware — using nothing but timing measurements. The
  CPU's speculative execution left traces in the cache. Every cloud provider on earth
  patched hypervisors in a panic, because in a multi-tenant cloud, "another process" can
  mean "another company."
- **Every container escape you will read about in Part 10** comes down to one fact: the
  container and the host share one kernel, and the kernel is one program in one address
  space. Namespaces are bookkeeping, not walls.

As a cloud security engineer you will be asked questions like: *Is it safe to run two
customers' workloads on the same EC2 instance? What does "encrypted at rest" actually
protect against? If an attacker gets code execution in our API container, what can they
read?* You cannot answer any of these from the application layer. The answers live in the
CPU's privilege model, the MMU, and the storage stack.

This chapter is the floor of the building. Everything else in this book — every packet,
every syscall, every container, every VPC — sits on the mechanisms described here.

---

## 2. Prerequisites

- You can read C-like pseudocode. (You will not need to write C.)
- You have used Linux and know what `ps`, `top`, and `cat` do.
- Binary and hexadecimal are covered properly in Chapter 7; if you are shaky, skim it
  first. For this chapter, knowing that `0xFF` is 255 is enough.

---

## 3. Mental Model

Hold this picture. We will refine it, but the shape stays correct:

```
+--------------------------------------------------------------+
|  YOUR PROCESS (ASP.NET Core API, PID 1842)                    |
|                                                               |
|  Thinks it has:                                               |
|    - the whole machine's memory, starting at address 0        |
|    - a CPU running its code continuously                      |
|    - files it can read by name                                |
+--------------------------------------------------------------+
        |  every one of these beliefs is maintained by:
        v
+--------------------------------------------------------------+
|  THE KERNEL (Linux)                                           |
|    - schedules threads onto CPUs (illusion of continuity)     |
|    - programs the MMU (illusion of private memory)            |
|    - implements filesystems over block devices (illusion of   |
|      files)                                                   |
+--------------------------------------------------------------+
        |  which is enforced by:
        v
+--------------------------------------------------------------+
|  THE HARDWARE                                                 |
|    - CPU privilege rings (who may execute which instructions) |
|    - MMU + page tables (which physical memory is visible)     |
|    - devices: RAM, NVMe, NIC                                  |
+--------------------------------------------------------------+
```

**The single most important idea in this chapter:** the boundaries that keep your process
from reading another process's memory are not enforced by the language, the framework, or
the operating system's good intentions. They are enforced by *hardware*, configured by
the kernel, on every single memory access. When someone tells you a security boundary
exists, the correct question is always: *what hardware or cryptographic mechanism
enforces it, and who can reconfigure that mechanism?*

A second idea, equally important: **the machine is a hierarchy of caches, and caches are
observable**. Speed differences leak information. That sentence will reappear in the
side-channel section, in the TLS timing-attack section (Chapter 25), and in the
password-comparison section (Chapter 52).

---

## 4. Fundamentals

### 4.1 The CPU: a very fast, very literal machine

A CPU does one thing in a loop, forever:

```
fetch   -> read the instruction at the address in the program counter (PC/RIP)
decode  -> work out what it means
execute -> do it
retire  -> commit the result, advance the PC
```

Everything else — operating systems, containers, microservices, Kubernetes — is built out
of that loop and nothing else.

The CPU's working state lives in **registers**: a few dozen slots of 64 bits each, on the
CPU die itself, accessible in well under a nanosecond. On x86-64 you will see names like
`RAX`, `RBX`, `RCX`, `RDX`, `RSI`, `RDI`, `RSP`, `RBP`, `R8`–`R15`, plus `RIP` (the
instruction pointer) and `RFLAGS` (status bits). On ARM64 (which is what AWS Graviton
instances and Apple Silicon run) they are `X0`–`X30`, `SP`, `PC`, `PSTATE`.

Three registers matter to security more than the rest:

| Register | Role | Why security cares |
|---|---|---|
| `RIP` / `PC` | Address of the next instruction | Control-flow hijacking means making this point at attacker-chosen code |
| `RSP` / `SP` | Top of the current stack | Stack overflows overwrite saved return addresses that will be loaded into `RIP` |
| `CR3` (x86) / `TTBR` (ARM) | Physical address of the current page table | Whoever controls this controls what memory the machine can see *at all* |

An **Instruction Set Architecture (ISA)** is the contract between software and CPU: which
instructions exist, what registers exist, how memory is addressed. x86-64 and ARM64 are
different ISAs, which is why a container image built for `linux/amd64` will not run on
Graviton without emulation — a fact that will matter in Chapter 94 when we discuss
multi-architecture image builds and their supply-chain implications.

### 4.2 Privilege rings: the hardware's idea of "root"

x86 defines four privilege levels, ring 0 through ring 3. In practice operating systems
use exactly two:

```
   Ring 0  --  KERNEL MODE
               Can execute privileged instructions:
                 - load CR3 (change the address space)
                 - modify page tables
                 - talk to hardware directly (IN/OUT, MMIO)
                 - halt the CPU, mask interrupts

   Ring 3  --  USER MODE
               Can execute ordinary arithmetic, loads, stores.
               Attempting a privileged instruction = #GP fault
               -> trap to ring 0 -> kernel usually kills the process (SIGSEGV/SIGILL)
```

With virtualization, a level is effectively added *beneath* ring 0: the hypervisor runs in
a mode (VMX root on Intel, EL2 on ARM) that the guest kernel cannot reach. So on an EC2
instance the stack is:

```
Ring 3  : your ASP.NET Core process
Ring 0  : the guest Linux kernel (inside your EC2 VM)
VMX root: the hypervisor (AWS Nitro — but see §12; Nitro moves most of it to hardware)
```

**This is the most important hierarchy in cloud security.** "Root on the box" means ring 0
in a guest VM. It does not mean control of the hypervisor, and it certainly does not mean
control of other tenants. A great deal of cloud security architecture is about making sure
that a compromise stops at one of these rings.

Note the asymmetry, though: ring 0 sees *everything* in its VM. Root can read any process's
memory (`/proc/PID/mem`), load kernel modules, disable auditing, and modify the running
kernel. This is why "the attacker got root on the container host" is a catastrophic
sentence, and why Part 10 spends a whole chapter on not giving containers a path to it.

### 4.3 Memory: the illusion of a private address space

Here is the fact that surprises most application engineers: **the addresses in your
program are fake**. When your C# code holds a reference, and that reference is ultimately
a pointer like `0x7f3c2a4b1000`, that number does not identify a location in RAM. It is a
**virtual address**, and it is meaningful only inside your process.

The **MMU (Memory Management Unit)**, a hardware unit inside the CPU, translates virtual
addresses to **physical addresses** on every single memory access, using data structures
called **page tables** that the kernel builds.

Memory is managed in fixed-size chunks called **pages**, normally 4 KiB (x86-64 also
supports 2 MiB and 1 GiB "huge pages"). A 64-bit virtual address is split into an index
path through a multi-level tree plus an offset:

```
x86-64, 4-level paging, 48-bit virtual addresses:

 63    48 47    39 38    30 29    21 20    12 11         0
+--------+--------+--------+--------+--------+------------+
| sign   |  PML4  |  PDPT  |   PD   |   PT   |   offset   |
| extend |  9 bit |  9 bit |  9 bit |  9 bit |   12 bit   |
+--------+--------+--------+--------+--------+------------+
             |        |        |        |          |
   CR3 ------+        |        |        |          |
   points to the PML4 |        |        |          |
   table; each level  |        |        |          |
   indexes the next --+--------+--------+          |
                                       |           |
                    final entry gives physical     |
                    page frame number, offset -----+
                    selects the byte within it
```

Walk that with an example. The CPU needs virtual address `0x00007F3C2A4B1123`:

1. Read `CR3` → physical address of this process's PML4 table.
2. Bits 47–39 of the address index into the PML4 → entry pointing to a PDPT.
3. Bits 38–30 index the PDPT → entry pointing to a Page Directory.
4. Bits 29–21 index the PD → entry pointing to a Page Table.
5. Bits 20–12 index the PT → a **Page Table Entry (PTE)** containing the physical page
   frame number *and permission bits*.
6. Bits 11–0 (`0x123`) are the offset inside that 4 KiB page.

Step 5 is where security lives. A PTE is not just "where is this page"; it carries flags:

| PTE flag | Meaning | Security role |
|---|---|---|
| **P** (Present) | Page is in RAM | If clear → page fault (may mean swapped out, or invalid) |
| **R/W** | Writable | Read-only pages protect code and constants |
| **U/S** (User/Supervisor) | Accessible from ring 3? | **This is the user/kernel memory boundary** |
| **NX / XD** (No-Execute) | Data here may not be executed | Kills classic "inject shellcode into a buffer" attacks |
| **A / D** (Accessed/Dirty) | Set by hardware on use/write | Used by swapping, and by forensic tooling |

So when a process tries to read kernel memory, the MMU sees U/S = supervisor while the CPU
is in ring 3, refuses the translation, and raises a **page fault**. The kernel's fault
handler decides what happened and typically delivers `SIGSEGV`. You have seen this as a
segfault; now you know it is a hardware event, not a software check.

**Why this matters to you specifically:** when we get to Chapter 50 (SSRF) and Chapter 96
(container escape), the question will repeatedly be "can this code read memory it should
not?" The answer always reduces to: is there a page table entry mapping that memory into
this address space with the right permission bits? If yes, no amount of application-level
validation matters.

### 4.4 The anatomy of a process's address space

Every Linux process gets a layout roughly like this (x86-64, simplified):

```
0xFFFFFFFFFFFFFFFF  +------------------------+
                    |    KERNEL SPACE        |   U/S = supervisor
                    |    (mapped, but        |   unreachable from ring 3
                    |     inaccessible)      |
0xFFFF800000000000  +------------------------+
                    |    (non-canonical      |
                    |     hole — invalid)    |
0x00007FFFFFFFFFFF  +------------------------+
                    |    stack               |   grows DOWN
                    |      |                 |   RW, NX
                    |      v                 |
                    +------------------------+
                    |  shared libraries      |   libc, OpenSSL, .NET runtime
                    |  (mmap region)         |   code: R-X   data: RW-
                    +------------------------+
                    |      ^                 |
                    |      |                 |
                    |    heap                |   grows UP (brk/mmap)
                    +------------------------+   RW, NX
                    |    .bss  (zero-init)   |   RW
                    |    .data (initialized) |   RW
                    |    .rodata (constants) |   R-- (read-only!)
                    |    .text (code)        |   R-X (read+execute, NOT writable)
0x0000000000400000  +------------------------+
                    |    unmapped guard      |   NULL dereference lands here
0x0000000000000000  +------------------------+
```

Several security-relevant observations fall straight out of this diagram:

1. **`.text` is read-execute, not writable.** You cannot overwrite a function's code in a
   normal process. Combined with the heap and stack being no-execute (NX), you get
   **W^X** ("write xor execute"): no page is both writable and executable. This single
   policy killed an entire generation of exploits and forced attackers to invent
   return-oriented programming (§10.2).
2. **Address 0 is deliberately unmapped.** That is why a null-pointer dereference
   segfaults instead of silently reading garbage — there is no PTE for page 0.
3. **The heap and stack are adjacent to other data.** Heartbleed worked because a read ran
   off the end of one heap allocation into neighboring allocations. Nothing in hardware
   distinguishes "your buffer" from "the buffer next to it" — they are in the same page,
   with the same permissions.
4. **Shared libraries are mapped into every process that uses them**, but their code pages
   are shared physical memory mapped read-only into many address spaces. One copy of libc
   in RAM, many virtual mappings. Efficient — and also why a vulnerability in a shared
   library affects everything at once (Chapter 112).

### 4.5 The memory hierarchy, and why speed is a security problem

RAM is slow compared to the CPU. Absurdly slow. The CPU compensates with caches:

| Level | Typical size | Typical latency | Rough cycles |
|---|---|---|---|
| Registers | ~1 KB | ~0.3 ns | <1 |
| L1 cache | 32–64 KB per core | ~1 ns | ~4 |
| L2 cache | 512 KB–2 MB per core | ~4 ns | ~14 |
| L3 cache | 8–64 MB, **shared between cores** | ~15 ns | ~50 |
| RAM (DRAM) | GBs | ~80–100 ns | ~300 |
| NVMe SSD | TBs | ~50–100 µs | ~300,000 |
| Network (same AZ) | — | ~0.5–1 ms | ~3,000,000 |
| Network (cross-region) | — | ~70–150 ms | ~500,000,000 |

Internalize the shape of that table; it explains most performance work you will ever do.
But the security consequence is the line marked in bold: **L3 is shared between cores**,
and on a cloud host, cores are shared between tenants.

If I can measure how long my own memory access takes, I can tell whether a cache line was
already loaded. If your code's behavior determined whether it was loaded, I have learned
something about your data without ever reading it. That is the engine behind:

- **Spectre / Meltdown** and the whole family of transient-execution attacks,
- **cache-timing attacks against AES** implementations that use lookup tables,
- **timing attacks on string comparison** — which is why you compare HMACs and password
  hashes with constant-time comparison functions (Chapters 25 and 52).

You do not need to implement these attacks. You need the reflex: *if the duration of an
operation depends on a secret, the secret is partly public.*

### 4.6 Storage: the illusion of files

Under `File.ReadAllText("appsettings.json")` sits a stack that looks like this:

```
application: File.ReadAllText(path)
      |
      v
runtime:     open(2) / read(2) syscalls  ---- ring 3 -> ring 0 boundary
      |
      v
kernel VFS:  resolve path -> inode -> filesystem driver
      |
      v
page cache:  is this block already in RAM?  (usually yes -> return immediately)
      |  no
      v
filesystem:  ext4/xfs: map file offset -> logical block numbers
      |
      v
block layer: I/O scheduler, queueing
      |
      v
device:      NVMe driver -> SSD controller -> flash translation layer -> NAND
```

Three security consequences of that stack, each of which comes back later:

1. **The page cache means "deleted" data is often still in RAM**, and dirty pages may not
   have reached disk. Forensics (Chapter 121) exploits this; so do attackers with root.
2. **SSDs do not overwrite in place.** The flash translation layer writes new blocks and
   marks old ones for garbage collection, so "shredding" a file on an SSD does not
   reliably destroy the old contents. This is precisely why cloud providers and serious
   organizations rely on **crypto-shredding**: encrypt the data, and destroy the key
   instead of the data. Chapter 80 (KMS) is built on this idea.
3. **"Encryption at rest" protects the physical medium, not your application.** If the OS
   mounts the volume and the process can read the file, encryption at rest has already
   been transparently undone for that reader. It defends against a stolen disk, a
   decommissioned drive, or a snapshot copied to another account. It does not defend
   against SQL injection. Being precise about this distinction in a design review is one
   of the fastest ways to sound like an engineer rather than a checklist-reader.

---

## 5. Deep Technical Explanation

### 5.1 What actually happens on a context switch

Your API process is one of hundreds on the box. The illusion of continuous execution is
maintained by the scheduler swapping threads on and off CPUs thousands of times a second.

A timer interrupt fires (or a thread blocks on I/O). Then:

```
1. CPU switches to ring 0, jumps to the interrupt handler via the IDT
   (Interrupt Descriptor Table), pushing the interrupted RIP/RSP/RFLAGS
   onto the kernel stack.
2. Kernel saves the outgoing thread's register state into its
   task_struct / thread_struct.
3. Scheduler picks the next runnable thread (CFS / EEVDF on modern Linux).
4. If the new thread belongs to a DIFFERENT process:
       load the new CR3  ->  the entire address space changes
       (TLB must be flushed or tagged — see below)
5. Restore the new thread's saved registers.
6. IRET / SYSRET back to ring 3, at the new thread's RIP.
```

Step 4 is expensive, and the expense is itself a security story. The **TLB (Translation
Lookaside Buffer)** is a small cache of recent virtual→physical translations; without it,
every memory access would need a 4-level page walk. Changing `CR3` invalidates those
entries. Modern CPUs mitigate this with **PCID/ASID** tags so multiple address spaces can
coexist in the TLB.

Then Meltdown happened. The mitigation, **KPTI (Kernel Page Table Isolation)**, stopped
mapping most of the kernel into user page tables at all, forcing a page-table switch on
*every* syscall — a 5–30% syscall-heavy performance hit across the industry. A hardware
information leak turned into a global, permanent tax on every syscall-heavy workload. Keep
that in mind the next time someone treats a "theoretical" side channel as unimportant.

### 5.2 Page faults: the mechanism behind almost everything clever

A **page fault** is the CPU telling the kernel "I could not complete this translation."
Not all faults are errors. There are three broad kinds:

| Kind | Cause | Kernel's response |
|---|---|---|
| **Minor fault** | Page is in RAM but not mapped into this process (e.g. shared library already loaded, or page cache hit) | Add the PTE, resume |
| **Major fault** | Page must be fetched from disk (swap, or first read of an mmap'd file) | Issue I/O, block the thread, resume later |
| **Invalid access** | No mapping, or permission violation (write to read-only, execute NX, user touching supervisor) | Deliver `SIGSEGV` (usually fatal) |

This machinery is what makes these possible:

- **Lazy allocation.** `malloc(1 GB)` does not consume 1 GB. The kernel promises address
  space; physical pages are allocated on first touch. This is why container memory limits
  behave surprisingly (Chapter 93) and why a process's *virtual* size (VSZ) is a nearly
  useless metric compared to *resident* size (RSS).
- **Copy-on-write (COW).** `fork()` does not copy memory. Both processes share pages
  marked read-only; the first write faults, and the kernel copies just that page. This is
  why forking a big process is cheap — and why `fork()`-based servers can leak secrets
  between workers if a secret was in memory before the fork.
- **Demand paging of executables.** Your binary is `mmap`'d, not read into RAM. Pages load
  as execution touches them.
- **Guard pages.** An unmapped page placed deliberately at the end of a region so an
  overflow faults instead of silently corrupting the neighbor. Modern allocators and
  thread stacks use these. This is a *hardware-enforced* bounds check, and it is the model
  for a lot of defensive design: make the failure loud and immediate rather than silent
  and exploitable.

### 5.3 The stack, and how control flow gets hijacked

The stack holds function-call bookkeeping. On x86-64, a call frame looks roughly like:

```
higher addresses
        +---------------------------+
        |  caller's frame           |
        +---------------------------+
        |  function arguments       |   (beyond the 6 passed in registers)
        +---------------------------+
        |  RETURN ADDRESS           |  <-- pushed by CALL. This is the prize.
        +---------------------------+
        |  saved RBP                |
        +---------------------------+
        |  local variables          |
        |    char buffer[64];       |  <-- overflow writes UPWARD from here...
        +---------------------------+
lower addresses          ^
                         RSP
```

Note the geometry: the buffer is at a *lower* address than the return address, and
`strcpy`-style writes move *upward*. Write 80 bytes into a 64-byte buffer and you have
overwritten the saved return address. When the function executes `ret`, the CPU pops that
value into `RIP` and starts executing there. You now control the program counter.

This is the canonical memory-safety bug, and understanding its geometry is worth the
effort even though you write C# and TypeScript, for three reasons:

1. **Your dependencies are written in C.** OpenSSL, zlib, libxml2, image codecs, the
   PostgreSQL client library, the .NET runtime itself. CVEs in these are what Chapter 112
   (SCA) is about, and reading a CVE description intelligently requires this model.
2. **Managed runtimes have unsafe seams**: `unsafe`/`stackalloc`/`Marshal` in C#, native
   node modules, `ctypes` in Python, and serialization surfaces.
3. **The defenses are a template for security engineering in general** — see §11.

### 5.4 Threads, cores, and shared state

A **process** is an address space plus resources (file descriptors, credentials). A
**thread** is a schedulable flow of execution *within* an address space. Threads in a
process share everything: heap, globals, file descriptors, and crucially the process's
security context.

That last point has real consequences:

- There is no meaningful security boundary between threads. If your ASP.NET Core app
  handles Tenant A's request on thread 7 and Tenant B's on thread 12, the only thing
  separating their data is your code's correctness. This is exactly why multi-tenancy bugs
  (Chapter 51) are so common and so damaging: the isolation is *logical*, implemented in
  application code, with no hardware backing it.
- Anything cached in a static/singleton is visible to all requests. A misplaced
  `static CurrentUser` — or an `AsyncLocal` used incorrectly, or an HttpClient handler
  holding per-user auth state — becomes a cross-tenant data leak. This class of bug has
  hit major SaaS products repeatedly.
- Race conditions between threads are not just correctness bugs; they are a vulnerability
  class (TOCTOU, Chapter 55).

The escalating ladder of isolation strength, which you will use constantly in design
reviews:

```
WEAKEST   threads in one process        - no boundary, code correctness only
          processes on one kernel       - MMU-enforced memory isolation,
                                          shared kernel attack surface
          containers on one kernel      - the above + namespaces/cgroups
                                          (still ONE kernel)
          VMs on one hypervisor         - separate kernels, hypervisor boundary
          separate physical hosts       - no shared silicon, no side channels
STRONGEST separate accounts/networks    - separate control planes and blast radius
```

Every isolation decision in Parts 7–11 is a choice of a rung on this ladder, traded off
against cost, latency, and operational complexity. Memorize the ladder.

---

## 6. Internals: Seeing It Directly

Linux exposes all of this through `/proc`. Chapter 32 covers `/proc` properly; here we use
just enough to make the abstractions visible.

### 6.1 The memory map of a real process

```bash
# Start something long-lived; a .NET app is ideal since it is your stack.
$ dotnet run --project ./LedgerApi &
$ pgrep -f LedgerApi
1842

$ cat /proc/1842/maps | head -20
```

Representative output (addresses vary run to run — that is ASLR, §11.2):

```
55d4f1a00000-55d4f1a24000 r--p 00000000 fd:01 1443591  /usr/lib/dotnet/dotnet
55d4f1a24000-55d4f1ab8000 r-xp 00024000 fd:01 1443591  /usr/lib/dotnet/dotnet
55d4f1ab8000-55d4f1ae9000 r--p 000b8000 fd:01 1443591  /usr/lib/dotnet/dotnet
55d4f1aea000-55d4f1aec000 rw-p 000e9000 fd:01 1443591  /usr/lib/dotnet/dotnet
55d4f3c1b000-55d4f3e9e000 rw-p 00000000 00:00 0        [heap]
7f2c40000000-7f2c40021000 rw-p 00000000 00:00 0
7f2c48f00000-7f2c48f28000 r--p 00000000 fd:01 1447102  /usr/lib/x86_64-linux-gnu/libc.so.6
7f2c48f28000-7f2c490b0000 r-xp 00028000 fd:01 1447102  /usr/lib/x86_64-linux-gnu/libc.so.6
7f2c490b0000-7f2c490ff000 r--p 001b0000 fd:01 1447102  /usr/lib/x86_64-linux-gnu/libc.so.6
7ffd8b3e1000-7ffd8b402000 rw-p 00000000 00:00 0        [stack]
7ffd8b4f7000-7ffd8b4fb000 r--p 00000000 00:00 0        [vvar]
7ffd8b4fb000-7ffd8b4fd000 r-xp 00000000 00:00 0        [vdso]
```

Read the columns:

- **Address range** — the virtual addresses covered by this mapping.
- **Permissions** — `r`, `w`, `x`, and `p` (private) or `s` (shared).
- **Offset, device, inode, path** — which file backs this mapping, if any.

Now read it as a security engineer:

- Every file-backed mapping appears **three or four times**, with different permissions:
  `r--` (read-only data), `r-x` (code), `r--`/`rw-` (relocations and writable data). The
  loader deliberately splits a binary into regions with the minimum permissions each
  needs. That is least privilege, implemented in page-table flags, for a single process.
- **No mapping has both `w` and `x`.** That is W^X, visible in the output. If you ever see
  `rwxp` in a production process's maps, something is generating code at runtime (a JIT —
  which is legitimate for .NET and V8) or something is very wrong. Knowing which of those
  it is, for a given host, is a real detection opportunity.
- `[stack]` is `rw-p`: writable, not executable. Shellcode written there cannot run.
- `[vdso]` is the "virtual dynamic shared object", a page of kernel-provided code mapped
  into every process so that cheap calls like `gettimeofday()` avoid a full syscall. It is
  a deliberate, controlled hole in the user/kernel boundary — and a favorite object of
  study for exploit developers precisely because it is executable and always mapped.

### 6.2 Resident vs virtual memory

```bash
$ ps -o pid,vsz,rss,comm -p 1842
  PID    VSZ   RSS COMMAND
 1842 2847120 78432 dotnet
```

`VSZ` ≈ 2.8 GB of address space reserved. `RSS` ≈ 78 MB actually resident in RAM. The .NET
runtime reserves large regions for the GC heap and commits them lazily. This is why
"the container is using 2.8 GB!" is usually a misreading, and why container OOM kills are
driven by RSS (and cgroup accounting), not VSZ. Chapter 93 returns to this.

More detail:

```bash
$ cat /proc/1842/status | grep -E 'VmPeak|VmSize|VmRSS|Threads'
VmPeak:  2847120 kB
VmSize:  2847120 kB
VmRSS:     78432 kB
Threads:      21
```

### 6.3 Watching the ring transition

Every interaction with the outside world crosses ring 3 → ring 0. `strace` makes those
crossings visible:

```bash
$ strace -f -e trace=openat,read,write,socket,connect -p 1842
```

You will see, for a single HTTP request hitting a PostgreSQL-backed endpoint, something
like:

```
[pid 1851] epoll_wait(8, ...)                 = 1
[pid 1851] accept4(10, {sa_family=AF_INET, sin_port=htons(52344), ...}, ...) = 24
[pid 1851] read(24, "GET /api/accounts/42 HTTP/1.1\r\n"..., 4096) = 412
[pid 1851] sendto(19, "Q\0\0\0002SELECT * FROM accounts WHE"..., 51, ...) = 51
[pid 1851] recvfrom(19, "T\0\0\0\36\0\1id\0\0\0@\t\0\1\0\0\0\27\0\4"..., 16384, ...) = 218
[pid 1851] write(24, "HTTP/1.1 200 OK\r\nContent-Type: a"..., 287) = 287
```

Sit with that output for a moment, because it is the whole book in miniature. Your elegant
`await _db.Accounts.FindAsync(id)` is, at the boundary, a byte string written to a socket
file descriptor. The framework, the ORM, the connection pool — all of it collapses into
`sendto(19, "Q\0\0\0002SELECT * FROM accounts WHERE ...")`.

And notice what is plainly visible: the SQL text, on the wire, as a string. Chapter 46
(SQL injection) becomes obvious the moment you have seen this. If the query text is built
by concatenation, then whatever the attacker put into the URL is right there in that
buffer, and PostgreSQL has no way to know which bytes were the developer's intent and
which were the attacker's. **The database does not receive your intent; it receives a
string.**

---

## 7. Real-World Example: Ledger API on a 2-vCPU VPS

System A from the book plan, on a modest VPS:

```
+------------------------------------------------------------------+
|  VPS: 2 vCPU, 4 GB RAM, Ubuntu 22.04                              |
|                                                                   |
|  PID 1  systemd                           (ring 0 services below) |
|  PID 640  nginx: master   [root]                                  |
|  PID 641  nginx: worker   [www-data]     RSS 12 MB                |
|  PID 1842 dotnet LedgerApi [ledger]      RSS 78 MB, 21 threads    |
|  PID 1990 postgres: main  [postgres]     RSS 210 MB (+ shared)    |
|  PID 2101 redis-server    [redis]        RSS 45 MB                |
|  PID 2240 rabbitmq beam.smp [rabbitmq]   RSS 120 MB               |
|                                                                   |
|  ONE Linux kernel. ONE physical memory. ONE page cache.           |
+------------------------------------------------------------------+
```

Now ask the questions that make you a security engineer rather than an operator:

**Q: If an attacker achieves code execution as the `ledger` user, what can they read?**

Not application logic — *page tables and file permissions*. They can read:
- All of PID 1842's memory (it is their own process): connection strings, JWT signing
  keys, cached tokens, decrypted rows, every secret the app ever loaded.
- Any file readable by `ledger`: `appsettings.Production.json`, `.env`, log files.
- Not PostgreSQL's memory directly — different UID, and `/proc/1990/mem` is protected by
  `ptrace_scope` and UID checks. But they do not need it: they have the database
  credentials in their own address space, and can just connect.

That last sentence is the entire lesson. Memory isolation between processes is real and
hardware-enforced, and it is routinely *irrelevant*, because the credentials that bypass
it are sitting in the compromised process. **Isolation boundaries are only as strong as
the credentials that cross them.** This observation drives Chapter 68 (secrets) and
Chapter 73 (least-privilege IAM roles).

**Q: What if they get root?**

Every boundary above collapses. Root can read `/proc/*/mem` for any process, attach with
`ptrace`, load a kernel module, read raw disk (bypassing file permissions entirely), and
disable logging. This is why Chapter 33 spends real time on not needing root, and why
Chapter 95 insists containers run as non-root.

**Q: Where does "encrypted at rest" help here?**

Only if someone steals the disk or a snapshot. With the system running, PostgreSQL has the
volume mounted and decrypted; the page cache holds plaintext. It is a genuine control
against a real threat (media disposal, snapshot exfiltration to another account — see
Chapter 78) and no control at all against the threats above. Say it precisely in reviews.

---

## 8. Hands-On Demonstration

Run these on ENV-1 (Linux VM or WSL2). Each one makes an abstraction visible.

### 8.1 Prove that virtual addresses are per-process

```bash
$ cat > addr.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
int global = 42;
int main(void) {
    int local = 7;
    printf("pid=%d  &global=%p  &local=%p\n", getpid(), (void*)&global, (void*)&local);
    sleep(30);
    return 0;
}
EOF
$ gcc -o addr addr.c
$ ./addr & ./addr &
```

Output (illustrative):

```
pid=3301  &global=0x55e8d2c04010  &local=0x7ffe3b8a1e4c
pid=3302  &global=0x561a9b204010  &local=0x7ffc9d2f7a9c
```

Two processes, two different addresses for *the same global variable* — because of ASLR
(§11.2). Disable ASLR temporarily and the addresses become identical:

```bash
$ setarch $(uname -m) -R ./addr & setarch $(uname -m) -R ./addr &
pid=3310  &global=0x555555558010  &local=0x7ffffffede2c
pid=3311  &global=0x555555558010  &local=0x7ffffffede2c
```

Identical virtual addresses, completely separate physical memory. The illusion, exposed.
This is also, concisely, why ASLR exists: in the second case an attacker knows exactly
where everything is.

### 8.2 Watch a page fault happen

```bash
$ /usr/bin/time -v ./addr 2>&1 | grep -E 'Maximum resident|page faults'
	Maximum resident set size (kbytes): 1664
	Major (requiring I/O) page faults: 0
	Minor (reclaiming a frame) page faults: 72
```

72 minor faults to start a trivial program: mapping libc, the loader, the stack, the heap.
Zero major faults because everything was already in the page cache. Run it after
`echo 3 | sudo tee /proc/sys/vm/drop_caches` and you will see major faults appear.

### 8.3 Prove W^X is enforced

```bash
$ cat > wx.c <<'EOF'
#include <stdio.h>
#include <string.h>
// 0xC3 = RET. Harmless, but it must EXECUTE to return normally.
unsigned char code[] = {0xC3};
int main(void) {
    void (*fn)(void) = (void(*)(void))code;   // code[] lives in .data -> RW, NX
    printf("about to call into a data page...\n");
    fn();
    printf("returned fine (NX not enforced?)\n");
    return 0;
}
EOF
$ gcc -o wx wx.c && ./wx
about to call into a data page...
Segmentation fault (core dumped)
```

The segfault *is the security control working*. The MMU refused to fetch an instruction
from a page whose PTE has the NX bit set, raised a fault, and the kernel killed the
process. No antivirus, no scanning, no heuristics — a hardware bit.

Confirm the kernel agrees:

```bash
$ dmesg | tail -2
[12345.678] wx[3402]: segfault at 55a3d2f04010 ip 000055a3d2f04010 sp 00007ffd...
            error 15 in wx[55a3d2f03000+1000]
```

`error 15` decodes to: user-mode (bit 2), instruction fetch (bit 4), protection violation
(bit 0) — precisely "ring 3 tried to execute a page it may not execute."

### 8.4 Observe the cache hierarchy (the side-channel primitive)

```bash
$ sudo apt-get install -y linux-tools-common linux-tools-generic
$ perf stat -e cache-references,cache-misses,instructions,cycles \
    dd if=/dev/zero of=/dev/null bs=1M count=2000 2>&1 | tail -12
```

Then compare a sequential vs random access pattern over a 512 MB array. The timing gap
(often 5–20×) is not a performance curiosity: it is the measurement primitive on which
every cache side-channel attack is built. If a secret-dependent branch determines which
cache line gets touched, an attacker who can measure their own access latency to that line
learns the secret.

### 8.5 Read another process's memory (with privilege)

```bash
$ ./addr &
[1] 3501
$ sudo grep -A1 heap /proc/3501/maps
5581ae5a9000-5581ae5ca000 rw-p 00000000 00:00 0    [heap]

# Read that range straight out of the live process:
$ sudo dd if=/proc/3501/mem bs=1 skip=$((0x5581ae5a9000)) count=64 2>/dev/null | xxd | head
```

It works, because you are root. Try it as an unprivileged user against a process you do
not own, and it fails with `EPERM` — enforced by UID checks plus
`/proc/sys/kernel/yama/ptrace_scope`.

**Take the lesson seriously:** any secret loaded into a process's memory is readable by
root on that host, and by anything that can achieve code execution in that process. This
is the honest limit of every "secure secret storage" story. Chapter 68 is about shrinking
the window (short-lived credentials) rather than pretending the window closes.

---

## 9. Security Implications

Collecting the threads:

| Mechanism | What it protects | What it does NOT protect against |
|---|---|---|
| Ring 0/3 separation | User code cannot touch kernel memory or hardware | Kernel vulnerabilities; root; side channels |
| Page tables + MMU | Process A cannot read process B | Root; stolen credentials held in A; shared-kernel escapes |
| NX / W^X | Injected data cannot be executed | ROP/JOP (reusing existing code) |
| ASLR | Attacker does not know where things are | Info leaks that disclose addresses; low-entropy 32-bit cases |
| Stack canaries | Detects linear stack smashing | Targeted overwrites that skip the canary; heap bugs |
| Encryption at rest | Stolen disks, snapshots, decommissioned media | Any attacker with a live, mounted system |
| Hypervisor isolation | Cross-VM memory access | Side channels; hypervisor escapes; control-plane compromise |

And the meta-lesson, worth more than the table: **every control has a precise threat it
addresses and an equally precise set it does not.** A security engineer who can state both
halves is useful. One who only knows that "we enable encryption at rest" is a compliance
checkbox with a salary.

---

## 10. Attack Scenarios

### 10.1 Memory disclosure (the Heartbleed shape)

```
Attacker sends: "here is a 4-byte payload, please echo back 65535 bytes"
Server:         memcpy(response, payload_ptr, 65535);   // trusts attacker's length
Result:         65531 bytes of whatever happened to be adjacent on the heap
```

Why the adjacent bytes were interesting: heap allocations cluster. Session buffers, TLS
keys, and recently processed request data all live in the same arenas. The attacker does
not choose what leaks, but they can ask repeatedly and sift.

**The transferable lesson:** a length field that the attacker controls, used without
validation against the actual buffer size, is a memory-disclosure primitive. You will meet
the same shape at the application layer — pagination parameters, `?limit=`, GraphQL depth,
Range headers — where the leak is rows instead of bytes (Chapter 51).

### 10.2 Return-oriented programming (why W^X was not the end)

NX stopped attackers from executing injected shellcode. So they stopped injecting code.

Instead, the attacker overflows the stack with a *chain of addresses*, each pointing at a
short sequence of existing, legitimate, already-executable instructions ending in `ret` —
a **gadget**. `ret` pops the next address, which runs the next gadget. Enough gadgets, and
the attacker has assembled an arbitrary program out of the victim's own code.

```
Stack after the overflow:
   +----------------------+
   | addr of gadget 1     |  pop rdi; ret        <- sets up argument
   +----------------------+
   | "/bin/sh" string ptr |
   +----------------------+
   | addr of gadget 2     |  pop rsi; ret
   +----------------------+
   | 0                    |
   +----------------------+
   | addr of execve@libc  |                      <- the payoff
   +----------------------+
```

Nothing is written to a writable page and executed. W^X is fully respected, and fully
bypassed. This is the single best illustration in computing of a principle you should
carry into every design review: **attackers do not break your control; they make it
irrelevant.** Expect it. Design so that bypassing one control still leaves them facing
another.

### 10.3 Transient execution (Spectre / Meltdown, 2018)

CPUs speculate: they execute past branches before knowing whether the branch was taken,
discarding results if wrong. Architecturally invisible. But the *cache* is not rolled back.

```
if (index < array_length) {        // attacker trains this to predict "true"
    value = array[index];          // speculatively executed with an OUT-OF-BOUNDS index
    temp  = probe[value * 4096];   // loads a cache line chosen by the secret byte
}
// branch resolves false, results discarded — but probe[] line is now cached
// attacker times access to each probe[] line to recover `value`
```

Meltdown (a related variant) let a user process read kernel memory this way — a total
break of the ring boundary, in hardware, by design rather than by bug. Mitigations: KPTI,
microcode updates, compiler barriers, and disabling hyper-threading in some multi-tenant
contexts.

**Why a cloud security engineer must know this:** it is the clearest argument for the
isolation ladder in §5.4. When someone asks "can we run untrusted customer code next to
our workloads on the same host?", the honest answer involves this attack class, and the
usual conclusion is: separate instances, or dedicated hosts, or accept the risk explicitly
with compensating controls. (It is also the reason AWS offers dedicated hosts and why some
regulated workloads pay for them.)

### 10.4 Cold boot and physical memory attacks

DRAM retains contents for seconds to minutes after power loss, longer if chilled. An
attacker with physical access can power-cycle into a minimal OS and dump RAM, recovering
disk-encryption keys. DMA-capable ports (Thunderbolt, PCIe) have historically allowed
direct memory reads bypassing the CPU entirely; IOMMU configuration is the defense.

Mostly out of scope for cloud work — which is itself the point. **A major, underrated
benefit of public cloud is that physical attacks move into the provider's threat model**,
backed by their physical security program, and out of yours. Shared responsibility (Chapter
71) starts here, at the silicon.

---

## 11. Defensive Techniques

### 11.1 W^X / NX / DEP

**Mechanism:** the NX bit in the PTE. **Enabled by:** default, everywhere, for decades.
**Verify:** `grep nx /proc/cpuinfo` (CPU support); `readelf -l binary | grep GNU_STACK` —
you want `RW` (not `RWE`) on the stack segment.

Residual risk: ROP/JOP. Managed runtimes with JITs must map pages RWX transiently; .NET
and V8 mitigate this with W^X-mode JIT that maps the same physical memory twice — once
writable, once executable — so no single mapping is both.

### 11.2 ASLR

**Mechanism:** randomize the base addresses of stack, heap, mmap region, and (with PIE) the
executable itself at each execution. An attacker who does not know where libc is cannot
build a reliable ROP chain.

```bash
$ cat /proc/sys/kernel/randomize_va_space
2          # 0=off, 1=stack/mmap, 2=full (stack, mmap, heap, and PIE binaries)

$ checksec --file=/usr/bin/curl     # from the `checksec` package
RELRO      STACK CANARY  NX     PIE      RPATH   SYMBOLS  FORTIFY
Full RELRO Canary found  NX on  PIE on   No RPATH  No Symbols  Yes
```

Residual risk: **any information leak defeats it.** One leaked pointer in an error message,
stack trace, or crash dump can de-randomize an entire module. This is precisely why
verbose error handling is a security issue and not merely untidy (Chapter 58) — a stack
trace in a 500 response is an ASLR bypass primitive in the right circumstances.

### 11.3 Stack canaries

The compiler places a random value between the locals and the return address, and checks
it before `ret`. A linear overflow smashes it, and the program aborts.

```
| buffer[64] | CANARY | saved RBP | return address |
                 ^
     overflow must cross this to reach the return address
```

Build with `-fstack-protector-strong` (default in most distro toolchains). Residual risk:
bugs that write at an arbitrary offset rather than linearly; and canary disclosure through
an info leak.

### 11.4 Control-flow integrity

Modern hardware adds:
- **Intel CET shadow stacks** — a second, protected copy of return addresses; a mismatch
  faults. This directly attacks ROP.
- **ARM Pointer Authentication (PAC)** — a cryptographic MAC embedded in unused pointer
  bits, verified before use.
- **Compiler CFI** (`-fsanitize=cfi` in Clang, Control Flow Guard on Windows) — validates
  indirect call targets against a known set.

### 11.5 Memory-safe languages

The highest-leverage control of all, and the one you can actually influence as an
architect. C# (outside `unsafe`), TypeScript, Python, Go, Rust, and Java eliminate the
*entire class* of bugs described in §5.3 by construction: bounds are checked, use-after-free
is prevented by GC or ownership, and type confusion is prevented by the type system.

CISA, NSA, and Microsoft have all published the same finding: roughly **70% of serious CVEs
in large C/C++ codebases are memory-safety issues**. You already work in memory-safe
languages. When you write a security recommendation about a new component, remember that
"write it in a memory-safe language" removes 70% of a category, which beats any scanner in
your pipeline. This is the difference between *eliminating* a vulnerability class and
*detecting instances of it* — always prefer elimination, and the rest of this book will
keep making that distinction.

### 11.6 Hardware memory encryption (cloud-relevant)

- **AMD SEV/SEV-SNP** and **Intel TDX**: encrypt guest memory with keys the hypervisor
  cannot access, so a compromised or malicious hypervisor cannot read guest RAM.
- **AWS Nitro Enclaves**: an isolated execution environment carved off an EC2 instance,
  with no persistent storage, no interactive access, and no external networking —
  attestable via cryptographic measurement, which can be required in a KMS key policy
  (Chapter 80) so that a key is only usable by an enclave running a specific image.

These matter when your threat model includes the *infrastructure operator*: regulated
finance, healthcare, key-management services, or multi-party computation.

---

## 12. Production Architecture: What This Means in the Cloud

When you launch an EC2 instance, here is what is actually beneath you:

```
+------------------------------------------------------------------+
|  AWS physical host                                                |
|                                                                   |
|  +------------------+  +------------------+  +------------------+ |
|  | YOUR EC2 VM      |  | Another tenant   |  | Another tenant   | |
|  |  guest kernel    |  |  guest kernel    |  |  guest kernel    | |
|  |  your processes  |  |                  |  |                  | |
|  +------------------+  +------------------+  +------------------+ |
|            |                    |                     |           |
|  +---------------------------------------------------------------+|
|  |  Nitro Hypervisor (minimal KVM-based; most I/O offloaded)      ||
|  +---------------------------------------------------------------+|
|  |  Nitro Cards (dedicated hardware: VPC networking, EBS,         ||
|  |  instance storage, security chip / root of trust)              ||
|  +---------------------------------------------------------------+|
|  |  CPU, RAM, NVMe                                                ||
+------------------------------------------------------------------+
```

The architectural insight worth carrying: AWS reduced the hypervisor's job by moving
networking, storage, and management onto **separate physical cards with their own
processors**. The trust surface shrinks because the code that could betray you is smaller
and largely not running on the same CPU as your workload. There is also, deliberately, no
mechanism for an AWS operator to log into the hypervisor and inspect guest memory.

That is a design pattern you should steal, and it recurs throughout this book:
**shrink the trusted computing base, and move privileged functions onto separate
enforcement points rather than adding privilege to the thing you already run.** It is the
same reasoning behind sidecar proxies (Chapter 86), admission controllers (Chapter 105),
and separate security tooling accounts (Chapter 74).

Your responsibilities in this picture (Chapter 71 formalizes this as the shared
responsibility model):

| AWS handles | You handle |
|---|---|
| Physical security, hypervisor, host firmware | Guest OS patching (unless serverless) |
| Hardware root of trust, side-channel mitigation at host level | Instance configuration, IMDSv2, SSM |
| Isolation between VMs | Isolation between *your* workloads (§5.4 ladder) |
| Storage media destruction | Encryption configuration, key policy, data classification |

---

## 13. Common Mistakes

1. **Believing "encrypted at rest" protects a running system.** It protects media. Say so
   precisely, every time. (Real consequence: teams skip field-level encryption for PII
   because "the disk is encrypted," then leak it through a SQL injection bug.)
2. **Treating VSZ as memory usage.** Leads to wrong container limits and confusing OOM
   kills. Use RSS, and in containers, use cgroup accounting (Chapter 93).
3. **Assuming threads are isolated.** They are not. Multi-tenant data in one process is
   protected only by your code's correctness.
4. **Assuming root is the top.** In a VM, root is ring 0 *of a guest*. Below it: hypervisor,
   firmware, hardware root of trust. Above it, in the cloud: the control plane, where an
   IAM role may be far more powerful than root on any single box.
5. **Believing a deleted file on an SSD is gone.** Use crypto-shredding for anything that
   matters.
6. **Dismissing timing differences.** If duration depends on a secret, the secret leaks.
   Use constant-time comparison for MACs, tokens, and password hashes.
7. **Leaving stack traces in production responses.** Beyond the obvious information
   disclosure, they can de-randomize ASLR and reveal exact dependency versions for CVE
   matching.
8. **Thinking memory-safety CVEs are irrelevant to managed-language shops.** Your
   dependency tree is full of C. So is your base image.

---

## 14. Troubleshooting

| Symptom | Likely cause | How to confirm |
|---|---|---|
| Process killed, no application log | OOM killer or cgroup limit | `dmesg -T \| grep -i 'killed process'`; `journalctl -k`; in containers check `memory.events` |
| "Segmentation fault" | Invalid memory access | `dmesg` for the fault address and error code; enable core dumps (`ulimit -c unlimited`), inspect with `gdb` |
| High CPU, low throughput | Cache thrashing or excessive context switching | `perf stat` (cache-misses, context-switches); `vmstat 1` |
| Sudden latency increase after patching | KPTI/Spectre mitigations on syscall-heavy load | `cat /sys/devices/system/cpu/vulnerabilities/*`; measure syscall rate with `perf stat -e raw_syscalls:sys_enter` |
| Memory grows forever | Leak, or fragmentation, or lazily-committed reservations | Compare VSZ vs RSS trend; `pmap -x PID`; for .NET, `dotnet-counters` and `dotnet-gcdump` |
| App works as root, fails as service user | File permissions, or a capability needed (e.g. binding port 80) | `strace -f -e trace=openat,bind` and look for `EACCES`/`EPERM` |

---

## 15. Practical Lab

### LAB 1.1 — Anatomy of a Running Process

**Objective.** Make every abstraction in this chapter concrete on a real, non-trivial
process: see its address space, its permission regions, its ring crossings, and prove the
hardware memory protections are active.

**Cost.** Free. **Environment.** ENV-1 (Linux VM or WSL2). **Time.** 45–60 minutes.

**Prerequisites.**

```bash
sudo apt-get update
sudo apt-get install -y build-essential strace gdb binutils procps \
                        linux-tools-generic checksec
# .NET optional but recommended, since it is your stack:
# https://learn.microsoft.com/dotnet/core/install/linux-ubuntu
```

**Architecture.**

```
  [ your terminal ]                    [ target process ]
        |                                     |
        |-- /proc/PID/maps ------------------>|  address space layout
        |-- /proc/PID/status --------------->|  RSS, threads, capabilities
        |-- strace -p PID ------------------->|  ring 3 -> ring 0 crossings
        |-- gdb -p PID ---------------------->|  registers, stack, memory
```

**Steps.**

*Step 1 — Create a target with interesting memory behavior.*

```bash
mkdir -p ~/lab01 && cd ~/lab01
cat > target.c <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

char  global_secret[64] = "SECRET_API_KEY_a1b2c3d4e5f6";   /* .data  */
const char rodata_msg[] = "this string is read-only";      /* .rodata*/

int main(void) {
    char *heap = malloc(1024);
    strcpy(heap, "heap allocation contents");
    char stack_buf[128];
    strcpy(stack_buf, "stack buffer contents");

    printf("pid            = %d\n", getpid());
    printf("&global_secret = %p\n", (void*)global_secret);
    printf("&rodata_msg    = %p\n", (void*)rodata_msg);
    printf("heap           = %p\n", (void*)heap);
    printf("&stack_buf     = %p\n", (void*)stack_buf);
    printf("&main          = %p\n", (void*)main);
    fflush(stdout);

    for (;;) { sleep(5); }    /* stay alive for inspection */
}
EOF
gcc -g -o target target.c
./target &
```

*Step 2 — Map every printed address to a region.*

```bash
PID=$(pgrep -n target)
cat /proc/$PID/maps
```

**Expected:** each address from step 1 falls inside a region in `maps`. Record which, and
the permission string for each. You should be able to state, for every one, *why* it has
those permissions.

*Step 3 — Prove `.rodata` really is read-only.*

```bash
gdb -p $PID -batch \
    -ex 'print rodata_msg' \
    -ex 'set {char}rodata_msg = 88' \
    -ex 'print rodata_msg'
```

**Expected:** `Cannot access memory at address ...` or a write error. GDB is root-capable
here and *still* cannot write, because the page's PTE has no write permission. Contrast
with `global_secret`, which writes successfully.

*Step 4 — Extract the secret from the live process.*

```bash
sudo gdb -p $PID -batch -ex 'x/s global_secret'
# or, without gdb:
sudo grep -a 'SECRET_API_KEY' /proc/$PID/mem 2>/dev/null || \
  sudo dd if=/proc/$PID/mem bs=1 \
     skip=$(( $(gdb -p $PID -batch -ex 'print &global_secret' \
              | grep -o '0x[0-9a-f]*') )) count=64 2>/dev/null | strings
```

**Expected:** the secret, in plaintext. **Security implication:** any secret in a process's
memory is recoverable by root or by code execution in that process. Environment variables,
`appsettings.json` values, and secrets fetched from a vault are all equally exposed once
loaded. What varies is *how long* they are valid — which is the entire argument for
short-lived credentials in Chapter 68.

*Step 5 — Count ring transitions.*

```bash
sudo strace -c -p $PID &
sleep 20
kill %2 2>/dev/null
```

**Expected:** a summary dominated by `nanosleep`/`clock_nanosleep`. Each call is a ring
3→0→3 round trip. Compare with a busy process (`strace -c -p $(pgrep -n dotnet)` during
load) to see thousands of `epoll_wait`, `read`, `write`, `futex`.

*Step 6 — Verify the process's protections.*

```bash
checksec --file=./target
cat /proc/sys/kernel/randomize_va_space
# restart the target a few times; confirm addresses change each run
for i in 1 2 3; do ./target & sleep 0.3; done
pkill target
```

**Security implications.** Write down, in your own words: (a) which boundary stopped the
`.rodata` write, (b) which boundary did *not* stop reading the secret and why, (c) what
would have to change for step 4 to fail.

**Attack scenario.** Assume an attacker gained code execution as your service user through
a deserialization bug (Chapter 54). Using only what you learned above, enumerate what they
can read without any further exploitation. Include: connection strings, JWT signing keys
in memory, decrypted PII from recent requests, and any cloud credentials the SDK cached.

**Hardening.**

1. Prefer short-lived credentials (IAM roles, IRSA) over long-lived secrets — the window
   of exposure shrinks from "forever" to "minutes."
2. Restrict `ptrace`: `sudo sysctl -w kernel.yama.ptrace_scope=1` (or 2/3 for stricter).
3. Run services as dedicated non-root users so one compromise does not read another's memory.
4. Disable core dumps for services handling secrets (`LimitCORE=0` in the systemd unit) —
   core files are full memory images written to disk.

**Verification.**

```bash
sysctl kernel.yama.ptrace_scope       # expect 1 or higher
systemctl show ledger-api -p LimitCORE
ps -o user,comm -p $(pgrep -d, -f 'dotnet|nginx|postgres')   # expect distinct users
```

**Cleanup.**

```bash
pkill target; cd ~ && rm -rf ~/lab01
```

---

## 16. Exercises

Answers are in §Solutions, at the end of the chapter. Do not read ahead.

### Concept questions

**1.1** A process reads virtual address `0x7f3c2a4b1000` and another process reads the same
address at the same moment. Explain, in terms of specific hardware and kernel structures,
why they do not see the same data. Which register and which table are involved?

**1.2** Why is `malloc(1024 * 1024 * 1024)` usually instant and usually successful, even on
a machine with 4 GB of RAM and no swap? What must happen before the memory is actually
consumed, and what fails if it is not available then?

**1.3** Explain precisely what "no-execute" prevents and what it does not. Then explain why
ROP exists and what that implies about layered defenses generally.

**1.4** Your team says "we're safe from memory-corruption bugs because we write C# and
TypeScript." Give three specific, concrete reasons that statement is incomplete.

**1.5** A colleague proposes running two customers' untrusted workloads as two processes on
one VM, arguing that "the MMU gives us hardware isolation." Evaluate this using the
isolation ladder from §5.4. What are they right about, and what are the three strongest
counter-arguments?

### Debugging problems

**1.6** A .NET service in a container with a 512 MB limit is killed regularly. Logs show
nothing. `docker stats` showed ~300 MB before the kill. `ps` shows VSZ of 2.4 GB. Walk
through your diagnosis: what do you check, in what order, and what are the three most
likely root causes?

**1.7** After a kernel upgrade, a service's p99 latency rose 25%. CPU utilization rose
similarly. The application did not change. The workload is proxy-like: many small
reads/writes on sockets. What is your hypothesis, and exactly how do you confirm or reject
it?

**1.8** An application intermittently returns fragments of *other users'* data in API
responses — never consistently, and never the same field. No database query returns the
wrong rows (verified by query logging). List the three most likely causes given this
chapter, ranked, with the observation that would distinguish them.

### Security scenarios

**1.9** A vulnerability scanner flags a critical CVE in `libwebp` inside your ASP.NET Core
container image. The app does not process images. Do you patch immediately? Construct the
full argument — for and against — and state what you would need to know to decide.

**1.10** Your company is told by a customer that the platform must guarantee "no AWS
employee can read our data in memory." What is technically possible, what would you
architect, and what would you refuse to promise?

### Architecture questions

**1.11** Design the isolation model for a platform that runs customer-supplied Python code
(a "scripting rules engine" feature). Cover: the isolation rung you choose and why, the
side-channel exposure you accept, what happens if isolation fails, and your detection
strategy. Assume 2,000 customers and sub-second execution requirements.

**1.12** You need to hold a signing key that no single compromise can expose. Using only
concepts from this chapter, sketch an architecture. What are the remaining ways it can be
compromised?

### Hands-on exercises

**1.13** Write and run a program that mmaps a page `PROT_READ|PROT_WRITE`, writes an
instruction to it, calls it (observe the crash), then `mprotect`s it to
`PROT_READ|PROT_EXEC` and calls it again (observe success). Explain what changed in the
page tables.

**1.14** Using `/proc/PID/smaps`, find which mapping in a running .NET or Node process has
the largest `Private_Dirty` value. Explain what that region is and why it dominates.

**1.15** Measure the cost of a ring transition: write a loop calling `getpid()` one million
times, then a loop calling it via the vDSO-cached path or a pure userspace function.
Compare with `perf stat`. Explain the difference in terms of §5.1.

### Interview questions (senior / staff level)

**1.16** "Walk me through what happens, from the hardware up, when a process reads a file
that is not in the page cache."

**1.17** "We're evaluating whether to run a multi-tenant SaaS with per-tenant containers or
per-tenant VMs. Argue both sides, then tell me what you'd actually do and what would change
your mind."

**1.18** "What does 'encryption at rest' protect against? Be specific about the threats it
does and does not address."

**1.19** "Explain Spectre to a product manager in ninety seconds, then explain to me why it
changed cloud architecture."

**1.20** "An attacker has code execution in one of our API pods. Take me through what they
can reach, in order, and where our controls should stop them."

---

## 17. Summary

- The computer maintains illusions: private memory, continuous execution, files. Security
  is what happens when they leak.
- The CPU runs a fetch-decode-execute loop and enforces privilege with **rings**. Ring 3 is
  user mode; ring 0 is the kernel; the hypervisor sits beneath both.
- **Virtual addresses are fake.** The MMU translates them via page tables on every access,
  and the PTE's permission bits (`R/W`, `U/S`, `NX`) are where memory security is actually
  enforced — in hardware, not in software checks.
- A process's address space separates code (`r-x`), constants (`r--`), and data (`rw-`),
  producing **W^X**. NX killed shellcode injection; ROP made it irrelevant — the permanent
  lesson being that attackers bypass controls rather than break them.
- **Page faults** are the mechanism behind lazy allocation, copy-on-write, demand paging,
  and guard pages.
- **Threads share everything**; there is no security boundary between them. The isolation
  ladder runs threads → processes → containers → VMs → hosts → accounts, and every cloud
  design picks a rung.
- The **memory hierarchy is observable**, so timing leaks secrets. This underpins Spectre,
  cache attacks, and the requirement for constant-time comparisons.
- **Storage is not what it looks like**: page cache holds plaintext, SSDs do not overwrite
  in place, and crypto-shredding is the reliable delete.
- **Every control protects against a specific threat and not others.** Being able to state
  both halves is the core professional skill introduced here.
- In the cloud, the provider takes the physical and hypervisor layers into their threat
  model; you own everything from the guest OS up, plus the control plane.

---

## 18. Knowledge Check

Answer without looking back. If you cannot, reread the referenced section.

1. Which register points to the current page table root, and what happens to the TLB when
   it changes? (§4.3, §5.1)
2. What are the three page-table permission bits that matter most to security, and what
   does each prevent? (§4.3)
3. Why does a null-pointer dereference produce a segfault rather than reading garbage? (§4.4)
4. What is the difference between a minor and a major page fault? (§5.2)
5. Draw the stack frame layout and mark where a buffer overflow overwrites the return
   address. (§5.3)
6. Name the six rungs of the isolation ladder, weakest to strongest. (§5.4)
7. Why does W^X not prevent exploitation? (§10.2)
8. What does ASLR protect against, and what single class of bug defeats it? (§11.2)
9. Why is "encrypted at rest" irrelevant to a SQL injection attack? (§4.6, §7)
10. What did AWS change architecturally with Nitro, and what general design principle does
    it illustrate? (§12)

---

## 19. Further Exploration

- `man 5 proc` — the definitive reference for `/proc`. Read the `maps`, `smaps`, `status`
  sections properly; you will use them for the rest of your career.
- **"What Every Programmer Should Know About Memory"**, Ulrich Drepper. Long, old, still the
  best explanation of the memory hierarchy in existence.
- **meltdownattack.com** and **spectreattack.com** — the original papers are unusually
  readable; read at least the introductions.
- **AWS Nitro System security whitepaper** — read it before Chapter 71; it is the clearest
  public description of a real hypervisor trust model.
- `/sys/devices/system/cpu/vulnerabilities/` — on any Linux box, read every file. It tells
  you exactly which transient-execution attacks your hardware is vulnerable to and which
  mitigations are active. Do this on an EC2 instance and compare instance families.
- **checksec** and **hardening-check** — run them against binaries in your base container
  images. You will be surprised what is missing.

---

## Solutions

### 1.1
Each process has its own page-table tree. The `CR3` register (x86-64; `TTBR0_EL1` on ARM64)
holds the physical address of the root table (PML4). On a context switch between processes,
the kernel loads a different value into `CR3`, so the same virtual address translates
through a different tree to a different physical page frame. The TLB caches translations,
so it must be flushed or, on modern CPUs, tagged with a PCID/ASID so entries from different
address spaces can coexist safely.

### 1.2
`malloc` of 1 GB typically reserves address space via `mmap` without committing physical
memory. The kernel creates a VMA (virtual memory area) and returns a pointer; no page
frames are allocated and no PTEs are populated. Physical pages are allocated on **first
touch**, via a minor page fault. If memory is unavailable at that point, the fault cannot
be satisfied and the OOM killer selects a victim process — which is why the failure shows
up as a kill far from the allocation site, and why VSZ is a poor capacity metric. (Behavior
depends on `vm.overcommit_memory`; the default, 0, is heuristic overcommit.)

### 1.3
NX prevents *instruction fetch* from pages whose PTE has the NX bit set — typically stack,
heap, and data. It defeats attacks that write attacker-supplied machine code into a data
buffer and jump to it. It does **not** prevent an attacker from redirecting control flow to
code that is already executable and legitimately mapped. ROP exploits exactly that: chain
short gadgets from the existing binary and libraries, driven by a stack of return addresses.
The general lesson is that a control eliminates a *technique*, not a *goal*; attackers find
another technique. Therefore defenses must be layered (ASLR to hide gadget addresses, CFI
and shadow stacks to validate control flow, memory-safe languages to remove the initial
corruption), and you should assume any single control will eventually be routed around.

### 1.4
(a) Your dependency tree contains substantial C/C++: OpenSSL, zlib, libxml2, image codecs,
the .NET runtime and GC, native Node modules, database client libraries. Their CVEs are
your CVEs. (b) Managed languages have explicit unsafe seams — `unsafe`/`stackalloc`/
`Marshal`/P-Invoke in C#, native addons in Node, `ctypes`/C extensions in Python. (c) The
base container image and the host kernel are C, and a memory-safety bug in the kernel is a
container escape (Chapter 96). A fourth, worth adding: memory safety removes *memory
corruption*, not injection, access control, SSRF, or logic flaws — which are the bulk of
what actually gets exploited in cloud applications.

### 1.5
They are right that the MMU provides genuine, hardware-enforced memory isolation between
processes: neither process can read the other's memory by address. The counter-arguments:
(1) **Shared kernel** — both processes call into the same kernel, so one kernel
vulnerability (or a permissive syscall reachable from their code) escalates to full host
compromise, defeating the boundary entirely. (2) **Shared everything else** — filesystem,
network namespace, `/proc`, process listing, UIDs; untrusted code can read world-readable
files, enumerate processes, and reach the network including the instance metadata service.
(3) **Side channels** — shared L3 cache and SMT siblings allow cache-timing observation
across processes; hardware isolation does not cover timing. Plus (4): resource exhaustion
by one tenant affects the other without cgroup limits. For untrusted code, the appropriate
rung is at least VM-level isolation (Firecracker microVMs, or gVisor as a middle option),
not process-level.

### 1.6
Order of diagnosis: (1) Confirm it is an OOM kill — `dmesg -T | grep -i 'killed process'`
and the container's exit code (137 = SIGKILL) and `memory.events` / `memory.max` in the
cgroup. (2) Ignore VSZ entirely; .NET reserves large GC regions lazily. Compare RSS *plus*
page cache charged to the cgroup — cgroup v2 counts page cache, so heavy file I/O can push
a container over its limit even when the heap is small. (3) Check the .NET GC mode: Server
GC sizes heaps per core and can far exceed expectations in a limited container; also check
whether the runtime sees the cgroup limit (`DOTNET_GCHeapHardLimit`, or that the container
runtime exposes limits correctly). Most likely root causes: (a) Server GC with high core
count in a low-memory container, (b) page cache from logging/file I/O charged to the cgroup,
(c) a genuine leak or large-object-heap fragmentation. `docker stats` showing 300 MB is a
point-in-time sample and may simply have missed the spike — capture continuously.

### 1.7
Hypothesis: the kernel upgrade enabled or strengthened transient-execution mitigations
(KPTI, retpolines, IBPB/STIBP, or MDS buffer clears). These add cost to every syscall and
context switch, which is exactly the profile of a proxy-like workload. Confirm by:
(1) `cat /sys/devices/system/cpu/vulnerabilities/*` before/after (compare against the old
kernel's values if recorded, or a peer host still on the old kernel); (2) `perf stat -e
raw_syscalls:sys_enter,context-switches` to establish syscall rate and confirm the workload
is syscall-dominated; (3) A/B test a single host booted with mitigations relaxed —
`mitigations=off` is a *diagnostic only*, never a production remedy on shared hardware;
(4) If confirmed, reduce syscall count (larger buffers, batching, io_uring) rather than
disabling mitigations.

### 1.8
Ranked: (1) **Shared mutable state across requests in one process** — a static/singleton
cache, an incorrectly scoped DI registration (a singleton depending on a scoped
per-user service), or misuse of `AsyncLocal`/`ThreadStatic`. Distinguishing observation:
the leak correlates with concurrency, and the leaked data belongs to a user who made a
request at nearly the same moment. (2) **A shared cache with a key collision** — Redis
keys missing the tenant discriminator. Distinguishing observation: leaked values are
*repeatable* for the same key, and appear only for cacheable endpoints; flushing the cache
changes behavior. (3) **Response buffer reuse / serialization bug** — a pooled buffer
(`ArrayPool`, `RecyclableMemoryStream`) returned without clearing, or a custom serializer
reusing state. Distinguishing observation: fragments appear at the *end* of responses or as
trailing garbage, mismatched with the response schema, and vary with response size. The
common factor, and the chapter's point: threads share the process, so none of these is
prevented by any hardware boundary.

### 1.9
Arguments for patching immediately: you cannot be certain the library is unreachable —
transitive callers are hard to enumerate, a future code change may reach it, and
"we don't process images" is often falsified by avatar upload, PDF generation, or a
dependency that thumbnails attachments. Patching a base image is cheap and routine.
Arguments against dropping everything: exploitability depends on reachability, and treating
every CVE as an emergency destroys the team's ability to respond to the ones that matter.
What you need to know: is the library actually loaded (`ldd`, `lsof` on a running
container), is there a call path from any request handler (reachability analysis, Chapter
112), is the input attacker-controlled, and is there a VEX statement from the vendor. The
professional answer: patch it in the normal base-image refresh cycle (days), not as an
incident, *unless* reachability analysis shows a path from untrusted input — and fix the
systemic issue by rebuilding images on a schedule so this decision stops being ad hoc.

### 1.10
Technically possible today: AWS Nitro Enclaves (isolated, no persistent storage, no
interactive access, cryptographic attestation), combined with KMS key policies that require
a specific enclave measurement (PCR values) before releasing a key. Also relevant: AMD
SEV-SNP–backed instances. What you would architect: process the sensitive data only inside
the enclave; the parent instance holds ciphertext and never sees the key; key release is
gated on attestation; audit via CloudTrail on the KMS calls. What you refuse to promise:
"no AWS employee could ever" is an absolute claim about someone else's supply chain,
firmware, and physical operations. Promise instead the specific, verifiable properties:
memory is not accessible to the parent instance or hypervisor operator interface, key
release is attestation-gated, and the design is auditable — and document the residual risk
(hardware supply chain, undiscovered vulnerabilities in the attestation path).

### 1.11
A defensible design: run each execution in a **microVM** (Firecracker) or gVisor sandbox
rather than a bare process or container, because customer-supplied code is untrusted by
definition and the shared-kernel rung is not adequate. Use a warm pool of pre-booted
sandboxes to meet sub-second latency, destroying each after a single execution (no reuse
across tenants). No network egress by default; no credentials in the environment; strict
CPU/memory/wall-clock limits via cgroups; seccomp profile restricting syscalls. Side-channel
exposure accepted: co-resident tenants on shared L3 could in principle observe timing; if a
tenant is high-sensitivity, offer dedicated hosts. If isolation fails: assume host
compromise, so the host holds nothing of value — no cloud credentials beyond a
minimal-scope role, no shared data volumes, and the host lives in an isolated subnet and
ideally an isolated account. Detection: syscall anomaly monitoring (Falco, Chapter 107),
egress attempts from a should-be-egress-less network (VPC Flow Logs, Chapter 82), execution
time and resource outliers, and sandbox crash rate as a canary.

### 1.12
Sketch: keep the private key inside a hardware security module or an attested enclave —
KMS with an asymmetric CMK, CloudHSM, or a Nitro Enclave holding the key. The key is never
present in any general-purpose process's memory; the application sends a *digest* and
receives a *signature*. Access to the signing operation is authorized by IAM and logged in
CloudTrail; rate limits bound abuse. Remaining compromise paths: (a) an attacker who obtains
permission to call the signing API can sign arbitrary content without ever seeing the key —
so the real control is authorization plus rate limiting plus alerting on volume, not key
secrecy; (b) compromise of the identity or role that holds that permission; (c) a bug in
the enclave/HSM firmware; (d) an insider with administrative control over the key policy.
Note the shape of the answer: protecting the *key* is easy, protecting the *capability* is
the hard part — a theme that returns in Chapter 80.

### 1.13
The program should `mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0)`,
write `0xC3` (RET) into it, cast to a function pointer and call — this faults, because the
PTE for that page has NX set. Then call `mprotect(page, 4096, PROT_READ|PROT_EXEC)` and
call again — this succeeds. What changed: `mprotect` asked the kernel to update the VMA's
protection flags and rewrite the corresponding PTEs, clearing NX and clearing the write
permission. The page's *physical* contents never moved; only the permission bits in the
page table changed. Note that you cannot get `PROT_WRITE|PROT_EXEC` simultaneously under a
W^X policy (SELinux, hardened kernels, or `MDWE`), which is exactly why JITs use dual
mappings of the same physical memory.

### 1.14
Typically the GC heap (an anonymous `rw-p` mapping) for .NET, or the V8 heap for Node.
`Private_Dirty` counts pages that are modified and not shared with any other process — i.e.
memory this process genuinely owns and which must be written to swap if reclaimed. It
dominates because the managed heap is per-process, constantly written, and not file-backed.
Contrast with the `r-x` mappings of shared libraries, which show large `Shared_Clean` values
because the same physical pages are mapped into every process using that library.

### 1.15
`getpid()` in glibc is *not* cached in current versions (the cache was removed), so the loop
performs one real syscall per iteration: roughly 50–300 ns each depending on hardware and
mitigation state. A pure userspace function call is ~1–2 ns. `perf stat` shows the syscall
loop with far higher `context-switches`-adjacent counters and dramatically more cycles per
iteration. The difference is the ring transition: register save, privilege-level change,
possible page-table switch under KPTI, kernel entry work, and the return path. Compare
against `clock_gettime()`, which *is* served by the vDSO without entering the kernel — the
gap between `getpid()` and `clock_gettime()` isolates the cost of the ring transition itself.

### 1.16
Expected shape of a strong answer: `read()` is invoked → `syscall` instruction triggers a
ring 3→0 transition (under KPTI, a page-table switch) → kernel validates the fd against the
process's file descriptor table → VFS dispatches to the filesystem driver via the inode →
the page cache is consulted and misses → the filesystem maps the file offset to logical
block numbers → the block layer queues a request → the NVMe driver rings a doorbell, the
device DMAs data into kernel memory and raises an interrupt → the calling thread was
blocked (a major page fault if this was an mmap'd access) and is now made runnable → data
is copied into the user buffer (or mapped, with zero-copy paths) → return to ring 3. Bonus
points for mentioning readahead, the I/O scheduler, and that the second read of the same
file returns from the page cache with no device involvement at all.

### 1.17
Containers: faster startup, higher density, lower cost, simpler operations, mature tooling;
but one shared kernel, so a kernel vulnerability or a misconfigured capability is a
cross-tenant compromise. VMs: separate kernels, far stronger boundary, aligns with most
compliance expectations; but slower start, lower density, higher cost and operational load.
What I would actually do: it depends on what the tenants run. If tenants only consume *my*
application and never supply code, containers with strong controls (non-root, seccomp,
dropped capabilities, NetworkPolicy, per-tenant namespaces) plus logical isolation in the
application are reasonable — the dominant risk is then application authorization bugs
(Chapter 51), not kernel escapes. If tenants supply code or the data is high-sensitivity
(regulated finance/health), microVMs. What would change my mind: a compliance requirement
mandating physical or hypervisor separation; evidence of tenant-supplied code; a specific
customer's threat model that includes other tenants as adversaries; or an incident.

### 1.18
It protects against threats to the *storage medium*: a stolen or lost disk, a
decommissioned drive that was not destroyed, a backup tape, a snapshot copied to another
account or region, and — in cloud — a snapshot shared publicly by mistake. It does **not**
protect against anything with legitimate access to the running system: SQL injection, a
compromised application process, a malicious insider with database credentials, an
over-permissioned IAM role reading objects through the service API, or root on the host.
The precise framing: encryption at rest moves the protection to *key access control*, so
the real security question becomes "who can use the key, and is that logged?" — which is
why KMS key policies and CloudTrail matter more than the checkbox.

### 1.19
For a PM: "Modern chips guess what your program will do next and start doing it early, then
undo it if they guessed wrong. Undoing leaves fingerprints in the chip's memory cache.
Researchers found you can read those fingerprints to recover data you were never allowed to
see — including data belonging to other customers on the same physical machine." For an
engineer: it broke an isolation boundary that was assumed absolute and enforced in hardware,
it could not be fully fixed in software, mitigations cost real performance permanently, and
it forced the industry to accept that CPU microarchitectural state is a shared resource and
therefore a covert channel. Architecturally it strengthened the case for dedicated
instances for high-sensitivity workloads, drove hyper-threading to be disabled in some
multi-tenant contexts, and accelerated hardware memory encryption (SEV-SNP, TDX, Nitro
Enclaves).

### 1.20
Expected progression: the process's own memory first (config, connection strings, cached
credentials, JWT signing keys, in-flight PII) → the filesystem readable by the pod's user →
the ServiceAccount token at
`/var/run/secrets/kubernetes.io/serviceaccount/token` and what its RBAC allows (Chapter 101)
→ the instance metadata service for node credentials if IMDSv2 hop limits and NetworkPolicy
do not block it (Chapters 78, 104) → other pods and services reachable on the network,
constrained only by NetworkPolicy (Chapter 104) → databases and queues whose credentials
were in memory → the cloud control plane via whatever role the workload holds (Chapter 108).
Controls that should stop them, in order: short-lived scoped credentials, a minimal
ServiceAccount with no unnecessary RBAC, `automountServiceAccountToken: false` where
unused, NetworkPolicy default-deny for egress, IMDSv2 with hop limit 1 (or blocked
entirely, using IRSA/Pod Identity instead), least-privilege IAM on the workload role,
database permissions scoped to the tables actually needed, and detection on anomalous API
calls in CloudTrail and the Kubernetes audit log.

---

*Next: Chapter 2 — The Kernel Boundary: Processes, Threads, System Calls, and Privilege
Rings. We will take the ring 3 → ring 0 transition seen briefly in §6.3 and examine it
instruction by instruction, because every security decision an operating system makes
happens at that boundary.*
