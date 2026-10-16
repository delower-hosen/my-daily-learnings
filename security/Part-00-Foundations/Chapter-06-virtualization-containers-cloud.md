# Chapter 6 — Virtualization, Containers, and Cloud: What "a Server" Means Now

---

## 1. Why This Matters

Chapters 1–5 built up the picture of a single machine: a CPU enforcing rings, a kernel
enforcing isolation between processes, sockets reaching the network, and components holding
data. This chapter takes that picture and asks the question that defines modern
infrastructure: **when there is no single machine — when "a server" is a slice of someone
else's hardware, a process pretending to be a host, or a function that exists for 200
milliseconds — what does security even mean?**

This is the bridge chapter. It closes Part 0 by lifting everything you have learned into the
abstractions you will spend the rest of the book securing: virtual machines, containers, and
cloud services. And it makes precise the single most important framework in cloud security,
introduced informally in Chapter 1 §5.4 and referenced ever since — **the isolation ladder** —
because every architectural decision in Parts 7 through 11 is, at bottom, a choice of a rung on
that ladder.

The stakes are concrete. As a cloud security engineer you will constantly answer questions
whose correct answer depends entirely on understanding these abstractions:

- "Can we run this untrusted customer workload next to our own?" — a question about isolation
  strength, answerable only if you know what a container actually isolates versus a VM.
- "The vendor says it's 'serverless,' so is it our responsibility to patch it?" — a question
  about the shared responsibility model, which shifts with every abstraction level.
- "If this Lambda function is compromised, what's the blast radius?" — a question about what
  an ephemeral, credential-bearing function can reach.
- "Why is the container escape in this CVE 'critical' when we run containers as non-root?" — a
  question about the shared kernel and what non-root does and does not buy you.

The recurring danger, which this chapter arms you against, is **the abstraction hiding the
security boundary**. A container *feels* like a lightweight VM, so engineers reason about it as
if it were one — and that mistaken mental model is the root of a large fraction of container
security incidents. The whole job here is to keep the abstraction's convenience while never
losing sight of what is actually enforcing (or not enforcing) the boundary underneath.

---

## 2. Prerequisites

- All of Part 0 so far. Especially Chapter 1 §4.2 (rings), §5.4 (the isolation ladder), §12
  (Nitro); Chapter 2 §4.1 (containers as `clone()` with namespace flags); and Chapter 5's
  three-lens model.
- You have run VMs (or EC2) and Docker containers, and have at least seen Kubernetes.
- Deep treatment of each layer comes later: containers in Part 10, Kubernetes in Part 11, AWS
  in Part 7. This chapter places them and establishes the reasoning; it does not exhaust them.

---

## 3. Mental Model

**Every "server" abstraction is a trade between isolation strength and efficiency, made by
choosing what to share.** The more you share, the cheaper and faster — and the weaker the
boundary.

```
   WHAT IS SHARED                          ISOLATION      COST/DENSITY   EXAMPLE
   ------------------------------------    ----------     ------------   ----------------
   Nothing (separate physical hardware)    strongest      most expensive dedicated hosts
   Hardware, separate hypervisor guests    very strong    expensive      EC2 instances / VMs
   Kernel shared, isolated microVM per WL   strong        moderate       Firecracker/Fargate
   Kernel shared, namespaces/cgroups        moderate       cheap          containers
   Process shared, logical separation       weakest        cheapest       multi-tenant app
```

This is the isolation ladder from Chapter 1 §5.4, now annotated with the *cost* axis that
makes it a real engineering decision rather than "always pick the strongest." Read it as: the
strength of the boundary is inversely proportional to how much is shared, and the cost is
proportional to the strength. Every rung is a legitimate choice for *some* workload; the
security engineer's job is to match the rung to the threat.

**The master question for any abstraction:** *what is the boundary, what enforces it, and who
can reconfigure the enforcer?* (This is reasoning pattern #1 from Chapter 1, now the organizing
principle of the whole chapter.)

- VM boundary: enforced by the CPU's virtualization extensions and the hypervisor. Reconfigured
  by: whoever controls the hypervisor (the cloud provider).
- Container boundary: enforced by the shared kernel's namespaces, cgroups, capabilities, and
  seccomp. Reconfigured by: root on the host, and anyone who can change the container's runtime
  config.
- Cloud service boundary: enforced by the provider's control plane and IAM. Reconfigured by:
  whoever holds the IAM permissions — which is why cloud IAM (Parts 6–7) is *the* perimeter.

**Second model — the responsibility gradient.** As you move up the abstraction stack, the
provider takes over more of the stack, and your responsibility narrows but never disappears —
it *shifts upward*, toward configuration and identity:

```
   IaaS (EC2)         you: OS, runtime, app, data, config, identity
   Containers (ECS)   you: image, app, data, config, identity  (provider: host, kernel*)
   Serverless (Lambda) you: code, data, config, identity        (provider: everything below)
   SaaS               you: data, config, identity               (provider: the application)
```

Note the constant at the right edge of every row: **identity and configuration are always
yours.** No matter how much the provider manages, *you* decide who can access what (IAM) and
*you* decide the settings (is the bucket public? is the DB encrypted?). This is why the vast
majority of cloud breaches are not provider failures but customer misconfigurations and
identity mistakes — and why Parts 6–9 (IAM, cloud, IaC) are the heart of the book.

---

## 4. Fundamentals

### 4.1 Virtualization: one machine pretending to be many

A **hypervisor** (or Virtual Machine Monitor) runs multiple guest operating systems on one
physical machine, each believing it has the hardware to itself. The illusion machinery of
Chapter 1, applied one level down: just as the kernel gives each process a private address
space, the hypervisor gives each VM a private *machine*.

Two flavors:

- **Type 1 (bare-metal):** the hypervisor runs directly on hardware (VMware ESXi, Xen, KVM as
  used by cloud providers, Hyper-V, AWS Nitro). This is what clouds run.
- **Type 2 (hosted):** the hypervisor runs as an application on a host OS (VirtualBox, VMware
  Workstation, Docker Desktop's VM). This is what you run on a laptop.

The hardware support that makes it efficient and secure:

- **CPU virtualization extensions** (Intel VT-x, AMD-V): a privilege mode *beneath* ring 0
  (VMX root / SVM), so the guest kernel runs at "ring 0" but the hypervisor is even more
  privileged and intercepts sensitive operations (Chapter 1 §4.2).
- **Second-level address translation** (Intel EPT, AMD NPT): the MMU (Chapter 1 §4.3) gains a
  *second* translation stage. Guest-virtual → guest-physical → host-physical. The guest cannot
  address host memory at all, because its "physical" addresses are themselves translated by
  hardware the guest cannot touch. **This is the memory boundary between VMs, and it is
  enforced in silicon.**
- **IOMMU** (VT-d, AMD-Vi): translates device DMA addresses, so a device assigned to one guest
  cannot DMA into another's memory.

The security consequence, stated precisely: **the VM boundary is a hardware-enforced memory and
device isolation boundary, mediated by a comparatively small hypervisor.** The attack surface a
guest presents to the host is the narrow set of "VM exits" (the operations the hypervisor must
handle), not the full ~350-syscall kernel interface a container presents. This is *why* VMs are
higher on the isolation ladder than containers, and the reason is now concrete rather than
asserted: fewer, simpler, hardware-mediated interactions versus many, complex, software-mediated
ones.

VM escapes exist (VENOM, various VMware/Xen bugs), but they are rare, expensive, and target the
small hypervisor surface. Container escapes are comparatively common because the shared-kernel
surface is enormous (Chapter 2 §10.3: Dirty COW, Dirty Pipe).

### 4.2 Containers: processes wearing a costume

You already have the correct definition from Chapter 2 §4.1: **a container is a process (or
group of processes) started with `clone()` using namespace flags, constrained by cgroups, with
reduced capabilities and usually a seccomp filter.** There is no "container" object in the
Linux kernel. It is a bundle of isolation primitives applied to ordinary processes.

The primitives (each gets full treatment in Chapter 38 and Part 10):

- **Namespaces** — isolate what a process can *see*: PID (its own process tree), network (its
  own interfaces and ports), mount (its own filesystem view), UTS (hostname), IPC, user (its
  own UID mapping), cgroup, time. A process in a PID namespace sees itself as PID 1 and cannot
  see host processes. *But the processes are still on the host's process list, in the host's
  kernel.*
- **cgroups** — limit and account what a process can *consume*: CPU, memory, PIDs, I/O. This
  bounds noisy-neighbor and resource-exhaustion DoS (Chapter 3 §5.4).
- **Capabilities + seccomp** — restrict what a process can *do* to the shared kernel (Chapter 2
  §4.2, §5.4).

The image format matters too. An **OCI image** is layers of filesystem tarballs plus metadata,
content-addressed by digest (Part 10). The security-relevant facts:

- The image is the software supply chain (Part 12): every layer, including the base image,
  brings its own dependencies and CVEs.
- Images are usually built *once* and run *everywhere*, so a vulnerability in a base image is a
  fleet-wide vulnerability, and a compromised image is a compromised fleet — the intermediary
  amplification of Chapter 5 §5.1, applied to the build pipeline.

**The one sentence to never forget:** *containers on one host share one kernel.* Every
consequence of container security flows from it:

- A kernel vulnerability reachable from an allowed syscall escapes every container on the host
  (Chapter 2 §10.3).
- "Root in a container" is real UID 0 on the host kernel, restricted only by capabilities and
  namespaces — one missing restriction (`--privileged`, an added capability, a mounted
  `docker.sock`, a hostPath mount) is host root (Chapter 3 §10.4, Chapter 2 §Solutions 2.18).
- Namespaces *hide* rather than *protect*: parts of `/sys`, `/proc`, the kernel log, and some
  sysctls leak host information or provide escape paths (Chapter 2 §13, Chapter 96).

### 4.3 microVMs: the middle rung

The obvious tension — VMs are strong but heavy, containers are light but weak — produced a
middle rung: **microVMs**. A minimal VM (tiny device model, fast boot, low memory overhead)
running a single container-like workload, giving *hardware VM isolation* with *container-like
density and speed*.

- **Firecracker** (AWS): boots in ~125 ms, minimal device model, purpose-built for
  multi-tenant serverless. It is what runs **AWS Lambda** and **Fargate** under the hood.
- **Kata Containers**: OCI-compatible containers that each run inside a lightweight VM,
  drop-in for Kubernetes where the shared-kernel risk is unacceptable.
- **gVisor** (Google): a *different* approach — a user-space kernel that intercepts container
  syscalls and implements them itself, shrinking the host-kernel surface without a full VM. A
  middle-middle rung: stronger than raw containers, weaker than a real VM, with a performance
  cost on syscall-heavy workloads.

Why this matters to you: when the answer to "can we run untrusted code next to our workloads?"
is "containers aren't enough but full VMs are too heavy," microVMs are the engineering answer,
and knowing they exist (and that Lambda/Fargate already use them) lets you reach for the right
rung instead of over- or under-isolating. This is the concrete resolution to the multi-tenancy
questions raised repeatedly in Chapters 1–2.

### 4.4 Cloud services: the control plane is the machine

Move one more level up and the physical machine disappears entirely. When you use S3, RDS,
Lambda, or DynamoDB, there is no "server" you administer. There is an **API** (the control
plane) that you call to provision, configure, and use resources, and the provider runs the
data plane.

This is the deepest conceptual shift in the book, so state it plainly: **in the cloud, the
primary attack surface moves from the network and the host to the control plane and its
identity system.** The consequences:

- **IAM is the new perimeter.** In System A, reaching PostgreSQL required network access
  (Chapter 3). In the cloud, an attacker with the right IAM permissions reads your S3 bucket or
  your DynamoDB table *over the public API*, from anywhere, with no network access to any host
  of yours (Chapters 6-IAM, 72). The firewall never sees them. This is why an over-permissioned
  IAM role or a leaked access key is often *worse* than a compromised host.
- **Configuration is code, and misconfiguration is the top breach cause.** A public S3 bucket,
  an RDS with `PubliclyAccessible=true`, a security group open to the world — these are the
  cloud's dominant failure mode (Chapters 79, 82), and they are *your* responsibility on every
  rung (§3, the responsibility gradient).
- **The blast radius is defined by identity, not by network reach.** What a compromised
  workload can do is determined by the IAM role it carries, which is why least-privilege roles
  (Chapter 73) and short-lived credentials (Chapter 68) are the central controls.
- **Everything is logged in the control plane** (CloudTrail, Chapter 82, 117) — which is both
  the attacker's risk and your detection surface. Every API call, including the malicious ones,
  is recorded.

Serverless (Lambda) is the extreme case and the clearest teacher:

```
   A Lambda function:
     - exists only while running (ephemeral; often <1s)
     - has no persistent host you patch (provider owns the runtime, on Firecracker)
     - carries an IAM ROLE that IS its identity and its blast radius
     - is triggered by events (API Gateway, S3, SQS, EventBridge)
```

The security model inverts: there is almost no host to harden, almost no network to firewall
(though you can VPC-attach it), and the entire security question becomes **what can this
function's IAM role do, and what untrusted input reaches its code?** — i.e., identity plus
application security (Chapter 4 Stops 6–7), with the OS and network layers largely handed to the
provider. Lambda is Part 0's whole argument in miniature: as the abstraction rises, security
concentrates in identity and configuration.

---

## 5. Deep Technical Explanation: The Isolation Ladder as a Decision Tool

The ladder is not trivia; it is a decision procedure. For a given workload, walk it:

**Step 1 — Classify the trust of the workload and its neighbors.**

- Is the code trusted (yours) or untrusted (customer-supplied, third-party plugins)?
- Are the neighbors trusted (your other services) or untrusted (other tenants, other
  customers)?
- What is the sensitivity of the data each touches (Chapter 5 §3, classification)?

**Step 2 — Identify the threat the boundary must stop.**

- Just noisy-neighbor resource contention? cgroups suffice (any rung).
- Accidental cross-workload data access by *your* code? Logical separation + good IAM.
- *Deliberate* escape attempts by untrusted code sharing the host? You need at least microVM
  isolation, because containers share the kernel and the kernel is the escape surface.
- A malicious co-tenant using side channels (Chapter 1 §10.3)? Separate hosts / dedicated
  instances.

**Step 3 — Choose the lowest rung that stops the threat, then add depth.**

The principle is *not* "always maximize isolation" — that wastes money and operational
capacity, which are finite and whose exhaustion is its own risk. It is "choose the lowest rung
that defeats the actual threat, then add compensating controls (defense in depth) so a failure
of that rung is not catastrophic."

Worked examples, which are exactly the judgments you will make:

| Workload | Neighbors | Threat | Rung chosen | Why |
|---|---|---|---|---|
| Your microservices, tenant data separated in-app | Your other services | app authz bugs, not kernel escape | hardened containers | code is trusted; kernel-escape threat is low; add non-root, seccomp, NetworkPolicy, per-tenant IAM |
| Customer-supplied scripts (rules engine) | Each other + your platform | deliberate escape, side channels | microVM per execution (Firecracker) | code is untrusted; shared kernel is inadequate; single-use, no creds, no egress |
| CI build of untrusted PRs | Other builds, your creds | supply-chain, escape | ephemeral microVM/isolated account | build code is untrusted by definition; destroy after; no standing credentials |
| Regulated data processing | Even the infra operator | operator access, side channels | dedicated host / Nitro Enclave | threat model includes the provider; hardware memory encryption |
| Stateless public web tier | Your other web pods | commodity attacks | containers + WAF + autoscale | trusted code, low blast radius, cost/density matters |

The table *is* the skill. An engineer who can produce it for a novel system — matching rung to
threat with justification, then layering defenses — is doing the core work of cloud security
architecture (Part 15).

### 5.1 Non-root in a container: what it does and does not buy

A frequent confusion, worth resolving precisely because it recurs. Running a container as
non-root (Chapter 2 §11):

**Buys you:** if the process is compromised, the attacker starts as an unprivileged user, so
file-permission and capability restrictions apply; many escape techniques that need root
capabilities (mounting, module loading) are foreclosed; and it composes with `no_new_privs` to
block setuid escalation.

**Does NOT buy you:** protection against a *kernel* vulnerability. A Dirty Pipe–style bug
(Chapter 2 §10.3) is reachable from an unprivileged process, because it is a bug in a syscall
any user may call. Non-root raises the bar for *capability-based* escapes; it does nothing for
*kernel-bug* escapes. The only defense against the latter is a different rung (microVM) or a
patched kernel.

So "we run non-root" is a true and valuable statement that answers one class of question and
not another — exactly the "every control has a specific threat it addresses and specific
threats it does not" discipline from Chapter 1 §9. State both halves in a review.

### 5.2 The shared responsibility model, made precise

"Shared responsibility" is often recited as a slogan; make it a table you can apply per
service, because the line moves with every rung (§3) and getting it wrong is how things fall
through the cracks:

```
                          EC2      ECS/EKS   Fargate   Lambda    S3/DynamoDB
                          (IaaS)   (containers) (serverless containers) (serverless) (managed)
 Physical/hardware        AWS      AWS       AWS       AWS       AWS
 Hypervisor               AWS      AWS       AWS       AWS       AWS
 Host OS / kernel         YOU*     YOU*/AWS  AWS       AWS       AWS
 Container runtime        n/a      YOU/AWS   AWS       AWS       n/a
 Guest OS patching        YOU      YOU(node) AWS       AWS       AWS
 Application code         YOU      YOU       YOU       YOU       n/a
 Data                     YOU      YOU       YOU       YOU       YOU
 IAM / access control     YOU      YOU       YOU       YOU       YOU
 Network config (SG/VPC)  YOU      YOU       YOU       YOU*      YOU
 Encryption config        YOU      YOU       YOU       YOU       YOU
```

(*EKS: you patch the nodes but not the managed control plane; Lambda networking is yours only
if VPC-attached; S3 network config is bucket policy + VPC endpoints.)

Two readings of this table are load-bearing:

1. **Moving up a rung transfers rows to AWS** — Fargate takes the kernel and runtime off your
   plate versus ECS-on-EC2, which is a real security benefit (fewer things you can get wrong).
   This is a legitimate reason to prefer higher abstractions: *reducing your responsibility
   surface reduces your mistake surface.*
2. **The bottom rows never move.** Data, IAM, and encryption config are yours on every rung.
   The cloud cannot secure your data against your own over-permissioned role or your own public
   bucket. This is why "we moved to serverless so security is handled" is dangerously wrong —
   serverless removes the *host* responsibilities and leaves the *identity and configuration*
   responsibilities, which are where breaches actually happen.

---

## 6. Internals: Seeing the Boundaries

### 6.1 A container is just processes on the host

```bash
# Start a container:
$ docker run -d --name demo alpine sleep 3600
$ CPID=$(docker inspect -f '{{.State.Pid}}' demo)

# From the HOST, the "contained" process is right there in the host's process list:
$ ps -o pid,user,comm -p $CPID
   PID USER     COMMAND
 48213 root     sleep

# It has its own namespaces (what it SEES is isolated)...
$ sudo ls -l /proc/$CPID/ns
lrwxrwxrwx ... net -> 'net:[4026532xxx]'     # different inode = different namespace
lrwxrwxrwx ... pid -> 'pid:[4026532xxx]'
lrwxrwxrwx ... mnt -> 'mnt:[4026532xxx]'
# ...but compare to PID 1's namespaces to confirm which are shared vs isolated:
$ sudo ls -l /proc/1/ns/net /proc/$CPID/ns/net
```

The lesson made tangible: the container's `sleep` is host PID 48213, a normal process the host
kernel schedules and can inspect, that merely has a different *view* via namespaces. There is no
wall — there is a filtered view of a shared world. Contrast this with a VM, where from the host
you see one `qemu`/`firecracker` process and *cannot* enumerate the guest's processes at all —
because the guest is behind a hardware memory boundary, not a namespace filter.

### 6.2 Watching capabilities and the escape surface

```bash
# What can this container's root actually do? (Chapter 2 §14)
$ docker exec demo cat /proc/self/status | grep -i cap
$ capsh --decode=$(docker exec demo cat /proc/self/status | awk '/CapEff/{print $2}')

# The dangerous configurations, visible on the host:
$ docker inspect demo -f '{{.HostConfig.Privileged}} {{.HostConfig.CapAdd}} {{.Mounts}}'
```

If `Privileged` is `true`, or `CapAdd` includes `SYS_ADMIN`, or a mount includes
`/var/run/docker.sock` or `/` — these are the escape configurations (Chapter 3 §10.4, Chapter
96). Auditing this across a fleet is a real, recurring task.

### 6.3 The cloud control plane, observed

There is no host to `ssh` into for a managed service, so the "internals" are API calls:

```bash
# Who can do what to this bucket? (the real access boundary, not a network one)
$ aws s3api get-bucket-policy --bucket ledger-data
$ aws s3api get-public-access-block --bucket ledger-data     # the "is it public?" check

# What is this Lambda's blast radius? Its role's permissions:
$ aws lambda get-function-configuration --function-name ledger-worker --query Role
$ aws iam list-attached-role-policies --role-name ledger-worker-role

# Every action, including malicious ones, is here:
$ aws cloudtrail lookup-events --max-results 5
```

Internalize the shift: for a VM you inspect `/proc` and `ss`; for a cloud service you inspect
IAM policies and CloudTrail. The *questions* are the same three lenses (Chapter 5 §3) — process
(the role's blast radius), network service (the resource policy / VPC access), data custodian
(what it holds, encryption) — but the *tools* are API calls, because the control plane *is* the
machine.

---

## 7. Real-World Example: Ledger Across Three Rungs

The Ledger system, the same application, placed on three rungs, showing how the security model
shifts:

**System A — VPS (containers on one host, or bare processes):**
```
One VPS, one kernel. Isolation between app/DB/cache/queue = processes + loopback binds
  (Chapters 3, 5). Blast radius of a host compromise = everything on the box.
  Your responsibility: the entire stack, OS up.
```

**System B — AWS ECS Fargate (microVM per task):**
```
Each ECS task runs in its own Firecracker microVM (Chapter 6 §4.3). Tasks are isolated
  at the VM boundary, not just namespaces — a kernel bug in one task does not reach another.
  RDS/ElastiCache are managed (provider owns host/kernel).
  Isolation between tiers = security groups (network) + IAM (control plane).
  Blast radius of a task compromise = that task's IAM role + what its SG can reach.
  Your responsibility: image, app, data, IAM, config. AWS: host, kernel, runtime.
```

**System C — EKS (containers on shared nodes) + microVM option:**
```
Pods share a node's kernel (back down a rung from Fargate!) — so kernel-escape risk returns,
  mitigated by non-root, seccomp, PSS, and NetworkPolicy (Part 11), OR by running
  sensitive/untrusted pods on Fargate profiles (microVM) within the same cluster.
  Isolation between pods = namespaces + NetworkPolicy + RBAC + (optionally) microVM.
  Blast radius = the pod's ServiceAccount (RBAC) + IRSA IAM role + NetworkPolicy reach.
```

The instructive comparison is B versus C: **Fargate is a *higher* isolation rung than
EKS-on-EC2**, because Fargate gives each task a microVM while EKS pods share the node's kernel.
Teams often assume "Kubernetes = more secure" because it is more sophisticated; on the isolation
axis specifically, plain EKS pods are *lower* on the ladder than Fargate tasks. A cloud security
engineer must be able to say this precisely and recommend Fargate profiles for the pods that
warrant a higher rung — matching rung to threat (§5) even *within* one cluster.

Across all three, the constants hold (Chapter 4 §7, Chapter 5 §7): the application-layer
controls (authN, authZ, parameterization) are identical, and *identity and configuration are
always yours*. What changes is which rung provides workload isolation and how much of the host
stack the provider absorbs.

---

## 8. Hands-On Demonstration

### LAB 6.1 — Prove the Container/VM Boundary Difference

**Objective.** Demonstrate empirically that a container shares the host kernel (and is
therefore a weaker boundary) while observing exactly which resources are isolated versus
shared, then reason about what this means for placement decisions.

**Cost.** Free. **Environment.** ENV-2. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — The container shares the host kernel (prove it).*

```bash
$ uname -r                                  # host kernel version
5.15.0-91-generic
$ docker run --rm alpine uname -r           # container's kernel...
5.15.0-91-generic                           # ...IDENTICAL. There is only one kernel.
```

There is no separate kernel to patch per container; patch the host and every container is
patched, and a host-kernel CVE affects every container at once. Contrast: a VM would report its
*own* kernel version, independent of the host.

*Step 2 — Namespaces isolate the view, not the substance.*

```bash
$ docker run -d --name iso alpine sleep 600
$ CPID=$(docker inspect -f '{{.State.Pid}}' iso)
$ docker exec iso ps aux                     # container sees ONLY its own processes (PID 1 = sleep)
$ ps aux | grep -w $CPID                     # host sees the SAME process with a real host PID
$ sudo nsenter -t $CPID -p -n ps aux         # enter the container's namespaces from the host
```

The process exists once, in the host kernel; the container merely has a filtered *view*.

*Step 3 — Demonstrate the shared-kernel blast radius (safely).*

```bash
# A container can see host kernel state that namespaces do NOT isolate:
$ docker run --rm alpine cat /proc/version   # host kernel build string — leaks host info
$ docker run --rm alpine dmesg 2>&1 | head   # blocked by default cap drop — good
$ docker run --rm --cap-add SYS_ADMIN alpine sh -c 'echo has SYS_ADMIN now'  # escape-enabling
```

*Step 4 — Show the escape configurations (do NOT run these in production).*

```bash
# THESE ARE THE DANGEROUS CONFIGS — demonstrating detection, not exploitation:
$ docker run --rm --privileged alpine sh -c 'ls /dev | head'   # sees host devices!
# vs the safe default:
$ docker run --rm alpine sh -c 'ls /dev | head'                # minimal /dev
```

With `--privileged`, the container sees host block devices (`/dev/sda`), from which reading the
host filesystem is trivial — a total escape. This is the single most dangerous flag in Docker,
and Step 4 shows *why* by showing what it exposes.

*Step 5 — Compare to a microVM (if available).*

```bash
# If you have gVisor (runsc) installed:
$ docker run --rm --runtime=runsc alpine uname -r
# runsc reports a DIFFERENT, gVisor-provided kernel version — the syscall surface is
# intercepted in user space, not passed to the host kernel. A higher rung.
```

**Security implications.** Write down: (a) why patching one host patches all its containers;
(b) why a kernel CVE is a fleet-wide container risk; (c) exactly what `--privileged` exposed
and why it is an escape; (d) which rung you would place an untrusted workload on and why.

**Attack scenario.** Given a container with `--cap-add SYS_ADMIN` or a mounted `docker.sock`
(Chapter 3 §10.4), describe the escape path to host root without running it. Then describe how
you would *detect* such a container across a fleet (`docker inspect` audit, or a Kubernetes
admission policy rejecting it — Chapter 105).

**Hardening.** For each dangerous configuration seen, state the control that prevents it:
non-root + `cap-drop ALL` + `no-new-privileges` + read-only rootfs + seccomp (Chapter 2 §11),
and — for genuinely untrusted workloads — a higher rung (gVisor/Kata/Fargate/microVM).

**Verification.**
```bash
docker inspect iso -f 'Privileged={{.HostConfig.Privileged}} Caps={{.HostConfig.CapAdd}}'
```

**Cleanup.**
```bash
docker rm -f iso 2>/dev/null
```

---

## 9. Security Implications

- **Isolation strength is inversely proportional to what is shared.** The isolation ladder
  (nothing → hardware → microVM → kernel → process) is the master framework; every placement
  decision is a rung choice.
- **VM boundary = hardware-enforced, small hypervisor surface.** Container boundary = software,
  shared kernel, huge surface. This is *why* VMs isolate more strongly, now grounded in EPT/NPT
  and the VM-exit surface.
- **Containers share one kernel** — the single fact from which all container security flows: a
  kernel CVE escapes all containers, and "root in a container" is one misconfiguration from
  host root.
- **microVMs (Firecracker/Kata) and gVisor** are the middle rungs, giving stronger isolation at
  container-like density; Lambda and Fargate already use them.
- **In the cloud, the control plane and IAM are the perimeter**, not the network. An attacker
  with IAM permissions reaches your data over the public API without touching a host.
- **Identity and configuration are always your responsibility**, on every rung — which is why
  misconfiguration and identity mistakes, not provider failures, cause most cloud breaches.
- **Moving up the abstraction stack transfers host responsibilities to the provider** (a real
  security benefit) **but never transfers data, IAM, or config responsibilities** (where
  breaches happen).
- **Match the rung to the threat; do not maximize isolation blindly** — then add defense in
  depth so a rung's failure is not catastrophic.

---

## 10. Attack Scenarios

1. **Container escape via misconfiguration** (`--privileged`, `SYS_ADMIN`, `docker.sock`,
   hostPath) → host root → all containers on the host. No kernel bug needed (Chapter 3 §10.4,
   Chapter 96). Detection: config audit / admission control.
2. **Container escape via kernel CVE** (Dirty Pipe class) → host root, from an *unprivileged*
   container, defeating non-root. Only a higher rung or a patched kernel stops it (§5.1).
3. **Cross-tenant side channel** on shared cores (Spectre class, Chapter 1 §10.3) → data leak
   without any escape. Stopped only by separate hosts/dedicated instances.
4. **IAM-based data theft** — a leaked access key or over-permissioned role reads S3/DynamoDB
   over the public API, from anywhere, invisible to the network firewall (§4.4, Part 7). The
   dominant cloud attack.
5. **Serverless credential abuse** — a compromised Lambda uses its role to pivot; its blast
   radius is exactly what the role can do (§4.4).
6. **Supply-chain via image** — a poisoned base image or dependency compromises the whole fleet
   that runs it (§4.2, Part 12).
7. **Misconfiguration at scale** — public bucket, public RDS, world-open SG — the cloud's top
   breach cause, and always the customer's responsibility (§5.2).

---

## 11. Defensive Techniques

- **Choose the rung deliberately** (§5): untrusted code or untrusted neighbors → microVM/
  dedicated; trusted code with logical tenant separation → hardened containers; regulated/
  operator-in-threat-model → enclaves/dedicated hosts.
- **Harden containers as if the kernel boundary will fail** (because it might): non-root,
  `cap-drop ALL`, `no-new-privileges`, read-only rootfs, seccomp, NetworkPolicy (Chapter 2 §11,
  Parts 10–11) — defense in depth atop the rung.
- **Never use escape-enabling configs** without extraordinary justification: no `--privileged`,
  no `docker.sock` mounts, no host namespaces, no unnecessary capabilities. Enforce with
  admission policy (Chapter 105).
- **Patch kernels promptly** — it is the only defense against kernel-CVE escapes for
  shared-kernel workloads; or move those workloads to managed nodes/Fargate where the provider
  patches.
- **Treat IAM as the perimeter**: least-privilege roles (Chapter 73), short-lived credentials
  (Chapter 68), no long-lived keys, MFA, and permission boundaries.
- **Prevent and detect misconfiguration**: policy-as-code (Chapter 91), `get-public-access-
  block` and Config rules (Chapter 82), block public access org-wide.
- **Use the control plane for detection**: CloudTrail on every API call, GuardDuty on anomalies
  (Chapter 82).
- **Right-size responsibility**: prefer higher abstractions to shed host-level mistakes, while
  never assuming they shed identity/config responsibility.

---

## 12. Production Architecture

How the rungs coexist in a real cloud platform — because mature systems use *multiple* rungs,
each matched to its workload:

```
+---------------------------------------------------------------------------+
|  AWS Account(s) — control plane, IAM = the perimeter (Parts 6-7)          |
|                                                                           |
|  Public web tier:   ECS Fargate (microVM) behind ALB+WAF                  |
|                     trusted code, low blast radius, cost/density matter    |
|                                                                           |
|  Internal services: EKS (containers, shared node kernel)                  |
|                     trusted code; hardened (non-root/seccomp/PSS/NetPol)   |
|                     + Fargate profiles for higher-sensitivity pods         |
|                                                                           |
|  Untrusted code:    Lambda in a locked-down account, no standing creds,   |
|  (plugins/rules)    OR per-execution Firecracker microVMs, no egress      |
|                                                                           |
|  Regulated compute: Nitro Enclaves (operator in threat model)             |
|                                                                           |
|  Managed data:      RDS / DynamoDB / S3 — provider owns host/kernel;      |
|                     YOU own IAM, encryption, network config, data         |
|                                                                           |
|  Every layer:       least-priv IAM roles, CloudTrail, GuardDuty, Config   |
+---------------------------------------------------------------------------+
```

The architectural maturity signal is *heterogeneity matched to threat*: the same platform runs
Fargate for the web tier, containers for internal services, microVMs/Lambda for untrusted code,
and enclaves for regulated data — each rung chosen by the §5 decision procedure, unified by IAM
as the perimeter and the control plane as the detection surface. A platform that runs
*everything* on one rung is either over-paying (all VMs) or under-isolating (all shared-kernel
containers). The engineer's contribution is the mapping.

---

## 13. Common Mistakes

1. **Reasoning about containers as lightweight VMs.** They share the kernel; the boundary is
   software and far weaker. This mental-model error is the root of most container incidents.
2. **Assuming "non-root container" means "safe from escape."** It stops capability-based
   escapes, not kernel-bug escapes (§5.1).
3. **Assuming "Kubernetes = more secure."** Plain EKS pods share a node kernel — a *lower* rung
   than Fargate microVMs (§7).
4. **Believing serverless/managed = "security handled."** The provider takes host
   responsibilities; identity and configuration — where breaches happen — remain yours (§5.2).
5. **Treating the network as the perimeter in the cloud.** IAM is the perimeter; data is read
   over the public API by identity, not by network path (§4.4).
6. **Maximizing isolation blindly** (all VMs, everything dedicated), wasting cost and
   operational capacity whose exhaustion is its own risk — instead of matching rung to threat.
7. **Using `--privileged` / mounting `docker.sock` / host namespaces** for convenience,
   creating trivial escape paths.
8. **Not patching shared kernels**, leaving the one defense against kernel-CVE escapes unused.
9. **One-rung platforms** — running untrusted code on the same rung as trusted code.
10. **Forgetting that images are the supply chain** — a compromised or vulnerable base image is
    a fleet-wide problem (Part 12).

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Container OOM-killed at low apparent memory | cgroup limit + page cache counted (Ch.1 §6.2) | `cat /sys/fs/cgroup/.../memory.max` & `.current`; `memory.events` |
| "It works on my laptop, fails in prod" | dev = Docker Desktop VM; prod = shared kernel/policy | compare kernel, seccomp, caps, user, read-only fs |
| Container can't do X (mount, bind low port, ptrace) | dropped capability (by design) | `capsh --decode`; add the *specific* cap or redesign |
| Lambda can't reach a resource | IAM role missing permission, or not VPC-attached | check role policy; check VPC config; CloudTrail AccessDenied |
| S3 data accessible unexpectedly | bucket policy / public access block / IAM | `get-public-access-block`, `get-bucket-policy`, IAM Access Analyzer |
| Suspected escape | privileged/hostPath/capability misconfig or kernel CVE | `docker inspect` for Privileged/CapAdd/Mounts; kernel version vs known CVEs |
| Higher latency on gVisor/microVM | syscall interception / VM overhead | expected trade-off for the isolation; profile syscall rate |

---

## 15. Practical Lab

Lab 6.1 is in §8. Register it in the lab index. Extension (requires AWS): create a Lambda
function with an over-broad role, then use the console/CLI to (a) enumerate exactly what its
role can do (its blast radius), (b) scope the role to least privilege, and (c) confirm via
CloudTrail that a removed permission now produces `AccessDenied`. This is the cloud analogue of
the container hardening lab and a preview of Part 7.

---

## 16. Exercises

### Concept questions

**6.1** State the isolation ladder from memory, with what is shared at each rung and the
resulting trade-off. Place EC2, Fargate, EKS-on-EC2, Lambda, and a multi-tenant app on it.

**6.2** Explain, in terms of specific hardware and kernel mechanisms, *why* a VM is a stronger
isolation boundary than a container. Do not just assert it — name the enforcers.

**6.3** "We run our containers as non-root, so we're protected against container escape."
Evaluate precisely: what does this protect against and what does it not?

**6.4** Explain why, in the cloud, an over-permissioned IAM role can be more dangerous than a
compromised host. What is "the perimeter" in a cloud environment?

**6.5** Walk the shared responsibility line for EC2, Fargate, and Lambda. What moves to the
provider as you go up, and what never moves?

### Debugging problems

**6.6** A pod is OOM-killed reporting ~200 MB used against a 512 MB limit. Explain the likely
cause using Chapters 1 and 6, and give the diagnostic commands.

**6.7** An untrusted-code sandbox built on hardened containers (non-root, seccomp, cap-drop) is
compromised via a kernel CVE and the attacker reaches the host. The team asks "our hardening
was correct — why did it fail?" Answer precisely and propose the fix.

**6.8** A Lambda function that worked in testing fails in production with `AccessDenied` on an
S3 call. The code is unchanged. Walk through the diagnosis and the two most likely causes.

### Security scenarios

**6.9** You must run customer-supplied Python (a rules engine), 2,000 tenants, sub-second
latency. Choose the isolation rung, justify it against the §5 decision procedure, and specify
what happens if isolation fails and how you detect it. (Compare your answer to Chapter 1
§Solutions 1.11.)

**6.10** Leadership wants to "move everything to serverless because it's more secure." Give a
balanced, precise response: what security improves, what does not, and what new responsibilities
appear.

### Architecture questions

**6.11** Design a platform that runs your trusted microservices, untrusted third-party plugins,
and regulated data processing. Assign each to a rung with justification, and describe the
unifying controls (IAM, detection) across all of them.

**6.12** Argue whether "Kubernetes is more secure than plain EC2" is true, false, or
ill-posed. Use the isolation ladder and the shared responsibility model to make your case.

### Hands-on exercises

**6.13** Prove the shared kernel: show that `uname -r` matches on host and container, and that a
container process appears on the host process list with a real PID. Explain both.

**6.14** Audit a set of running containers for escape-enabling configurations (privileged,
added capabilities, sensitive mounts, host namespaces) and produce a findings list. Then write
the admission-policy pseudocode that would have rejected each.

**6.15** (AWS) Enumerate the effective permissions of a workload's IAM role and reduce it to
least privilege, verifying via CloudTrail that removed permissions now deny.

### Interview questions

**6.16** "What actually is a container, and why isn't it a security boundary in the way a VM
is?"

**6.17** "Walk me up the isolation ladder and tell me when you'd choose each rung."

**6.18** "In the cloud, what is the perimeter? Why do most breaches happen despite firewalls?"

**6.19** "Explain the shared responsibility model to me for three different AWS services, and
tell me what customers most often get wrong."

**6.20** "We need to run untrusted code. Walk me through your isolation design and what happens
when it fails."

---

## 17. Summary

- Every "server" abstraction is a trade between **isolation strength and efficiency, made by
  choosing what to share** — the **isolation ladder**: separate hardware > VMs > microVMs >
  containers > shared process. Strength is inversely proportional to sharing; cost is
  proportional to strength.
- **VMs** isolate via hardware (VT-x/AMD-V, EPT/NPT second-level translation, IOMMU) mediated
  by a small hypervisor with a narrow VM-exit surface — a *hardware-enforced* boundary.
- **Containers are processes with namespaces, cgroups, capabilities, and seccomp, sharing one
  kernel.** That shared kernel is the source of all container security reasoning: kernel CVEs
  escape all containers, and "root in a container" is one misconfiguration from host root.
- **microVMs (Firecracker/Kata) and gVisor** occupy the middle rungs; Lambda and Fargate use
  them, so serverless already runs on microVM isolation.
- **In the cloud, the control plane and IAM are the perimeter.** An attacker with IAM
  permissions reads your data over the public API, invisible to the network firewall — which is
  why IAM (Parts 6–7) is the heart of the book and misconfiguration/identity mistakes are the
  top breach causes.
- **The shared responsibility model shifts up each rung**: the provider absorbs host, kernel,
  and runtime as you ascend (a real benefit), **but data, IAM, and configuration are always
  yours.** Serverless removes host responsibilities and keeps the ones where breaches happen.
- **Non-root** stops capability-based escapes, not kernel-bug escapes — state both halves.
- The skill is **matching the rung to the threat** (the §5 decision procedure), then layering
  defense in depth so a rung's failure is not catastrophic — not maximizing isolation blindly.

---

## 18. Knowledge Check

1. Name the rungs of the isolation ladder and what is shared at each. (§3, §5)
2. Which hardware mechanisms enforce the VM memory boundary? (§4.1)
3. What is the one sentence from which all container security follows? (§4.2)
4. What do Firecracker and gVisor each provide, and how do they differ? (§4.3)
5. Why is IAM "the perimeter" in the cloud? (§4.4)
6. What does running non-root in a container protect against, and what not? (§5.1)
7. In the shared responsibility model, which rows never move to the provider? (§5.2)
8. Why is a Fargate task a higher isolation rung than an EKS-on-EC2 pod? (§7)
9. What does `--privileged` expose, and why is it an escape? (§8)
10. What is the §5 decision procedure for choosing an isolation rung? (§5)

---

## 19. Further Exploration

- **AWS Nitro System** and **Firecracker** whitepapers/papers — the clearest public
  descriptions of real hypervisor and microVM trust models. Read before Part 7.
- **gVisor** documentation (the "What is gVisor" and security model pages) — an unusually clear
  explanation of shrinking the kernel attack surface.
- `man 7 namespaces`, `man 7 cgroups` — the primitives; Chapter 38 goes deep, but read the
  overviews now.
- The **AWS Shared Responsibility Model** page — then draw the §5.2 table yourself for three
  services without looking.
- Run Lab 6.1, then read a real container-escape write-up (a `--privileged` escape or a
  Dirty Pipe container escape) and map each step to this chapter's mechanisms.
- **CIS Benchmarks** for Docker and Kubernetes — skim now for the shape of container hardening;
  you will implement them in Parts 10–11.

---

## Solutions

### 6.1
Rungs, strongest to weakest, by what is shared: **separate physical hardware** (nothing shared;
strongest; most expensive) — dedicated hosts; **VMs** (hardware shared, separate hypervisor
guests with hardware-enforced memory isolation; very strong; expensive) — EC2; **microVMs**
(kernel-per-workload in a minimal VM; strong; moderate) — Fargate, Lambda (Firecracker);
**containers** (kernel shared, namespaces/cgroups; moderate; cheap) — EKS-on-EC2 pods;
**shared process/logical** (process shared, app-level separation; weakest; cheapest) —
multi-tenant app. Placement: EC2 = VM rung; Fargate = microVM rung; EKS-on-EC2 = container
rung; Lambda = microVM rung (surprises some people); multi-tenant app = shared-process rung.
Trade-off: strength ↓ and cost ↓ as sharing ↑.

### 6.2
A VM's memory boundary is enforced by the MMU's **second-level address translation** (Intel
EPT / AMD NPT): guest-virtual → guest-physical → host-physical, where the final stage uses
tables the guest cannot access, so the guest literally cannot form an address into host or
peer-guest memory. **CPU virtualization extensions** (VT-x/AMD-V) run the guest kernel in a
mode beneath ring 0, trapping sensitive operations to the hypervisor. The **IOMMU** (VT-d/
AMD-Vi) confines device DMA. Crucially, the guest interacts with the hypervisor only through a
small, well-defined set of **VM exits**, so the attack surface is narrow and hardware-mediated.
A container, by contrast, is isolated only by the shared kernel's software bookkeeping
(namespaces filter views, cgroups limit resources), and its processes call directly into the
same ~350-syscall, ~30-million-line kernel as the host — an enormous, software-enforced
surface. Fewer, simpler, hardware-mediated interactions (VM) versus many, complex,
software-mediated ones (container) is why the VM boundary is stronger.

### 6.3
Non-root protects against **capability-based** escapes and post-compromise privilege: the
attacker starts as an unprivileged user, so file permissions apply, capabilities that require
root (mounting, module loading, many device operations) are unavailable, and combined with
`no_new_privs` setuid escalation is blocked. It does **not** protect against a **kernel
vulnerability**: bugs like Dirty Pipe (Chapter 2 §10.3) are reachable from an unprivileged
process because they are flaws in syscalls any user may call, so an unprivileged container can
still escape via a kernel bug. Non-root raises the bar for capability escapes and does nothing
for kernel-bug escapes. The correct statement is "non-root is necessary and valuable but
addresses only one escape class; kernel-bug escapes require a patched kernel or a higher
isolation rung (microVM)." State both halves.

### 6.4
In the cloud, data is accessed through the provider's public API, authorized by IAM — not
gated by your network. An over-permissioned role (or a leaked access key with that role) lets
an attacker call `s3:GetObject` or `dynamodb:Scan` from anywhere on the internet, reading your
data without ever touching a host, a VPC, or a firewall — the network controls never see them.
A compromised host, by contrast, is bounded by what that host can reach and often by network
segmentation, and it leaves host-level traces. So the IAM role's permissions define the blast
radius independent of network position, and a broad role is a broad blast radius reachable
globally. "The perimeter" in the cloud is therefore **identity** — the IAM system and the
control plane — not the network. This is why least privilege, short-lived credentials, and
IAM monitoring are the central cloud controls.

### 6.5
**EC2 (IaaS):** AWS owns hardware and hypervisor; you own the guest OS (patching), runtime,
app, data, network config, IAM, and encryption config. **Fargate (serverless containers):**
AWS additionally owns the host OS, kernel, and container runtime (each task in a microVM); you
own the image, app, data, network config, IAM, encryption. **Lambda (serverless):** AWS owns
everything down to and including the runtime; you own the code, data, config, IAM, and (only
if VPC-attached) networking. What moves to AWS as you ascend: OS/kernel patching, runtime
management, and increasingly the host. What **never** moves: **data, IAM/access control, and
encryption/configuration** — these are yours on every rung, which is why "we went serverless"
does not remove the responsibilities where breaches actually occur.

### 6.6
Cause: the cgroup memory limit counts more than the process's RSS — it includes page cache
charged to the cgroup (Chapter 1 §6.2), and for .NET the runtime may size heaps aggressively
(Server GC per core) or not see the cgroup limit. The ~200 MB "used" is likely a point-in-time
RSS sample missing a spike, or excludes page cache from file I/O/logging that the cgroup counts.
Diagnostics: `cat /sys/fs/cgroup/<path>/memory.max` and `memory.current` and `memory.events`
(the `oom_kill` counter and `max` events); `kubectl describe pod` for exit code 137
(SIGKILL/OOM); check GC mode and whether `DOTNET_GCHeapHardLimit` / the runtime's cgroup
awareness is set; capture `memory.current` continuously to catch the spike. Fix: right-size the
limit, constrain the GC to the cgroup, and reduce page-cache pressure (less local file I/O).

### 6.7
The hardening was correct *for its rung* and addressed the escape classes that rung can
address — capability-based escapes, privilege escalation, syscall surface reduction. But
non-root/seccomp/cap-drop do not close **kernel-bug** escapes, because the vulnerability is in
the shared kernel reachable from an allowed syscall by an unprivileged process (§5.1, Chapter 2
§10.3). The mistake was the *rung choice*, not the hardening: **untrusted code should not share
a kernel with anything of value.** Fix: move untrusted-code execution to a higher rung —
per-execution microVMs (Firecracker) or gVisor — so a kernel bug in the guest does not reach
the host; keep the container hardening as defense in depth; ensure the host holds nothing
valuable (no standing credentials, isolated account/subnet) so even a successful escape is
contained; and patch kernels promptly. The lesson: hardening within a rung cannot substitute
for choosing the right rung against the actual threat.

### 6.8
`AccessDenied` on an unchanged code path means the *authorization* changed or differs between
environments — this is an IAM/config issue, not a code issue. Diagnosis: (1) Check the
function's **execution role** in production versus test — the prod role likely lacks the
`s3:GetObject` (and possibly `s3:ListBucket`) permission on that bucket/prefix, or a permission
boundary / SCP denies it; confirm in CloudTrail (the `AccessDenied` event names the principal,
action, and resource). (2) Check the **resource side** — a bucket policy or the bucket's
account may deny the role, or the object is KMS-encrypted and the role lacks `kms:Decrypt` on
the key (a very common cause: S3 access granted but KMS decrypt missing). Two most likely
causes: the prod execution role is more restrictive than test's, or the bucket uses a KMS key
the role cannot use. Fix: grant the least-privilege permission (including `kms:Decrypt` if
applicable) and verify via CloudTrail that the call now succeeds. This is the "identity is the
perimeter" and "config is always yours" lesson in miniature.

### 6.9
Rung: **per-execution microVM (Firecracker)** or a warm pool of gVisor sandboxes — not
hardened containers, because customer-supplied code is untrusted by definition and the
shared-kernel rung is inadequate against deliberate escape (§5, §Solutions 6.7). Meet
sub-second latency with a pre-booted warm pool, assigning one sandbox per execution and
destroying it after (no reuse across tenants → no cross-tenant residue). Constraints: no
network egress by default; no cloud credentials in the environment (the host holds a
minimal-scope role at most); strict CPU/memory/wall-clock cgroup limits; seccomp; isolated
subnet and ideally isolated account. If isolation fails: the host must hold nothing of value,
so a successful escape yields an empty, credential-less, egress-less host in an isolated blast
radius. Detection: syscall-anomaly monitoring (Falco/eBPF, Chapter 107), egress attempts from
a should-be-egress-less network (VPC Flow Logs, Chapter 82), execution-time/resource outliers,
and sandbox crash rate as an exploitation canary. (Matches Chapter 1 §Solutions 1.11, now with
the rung named explicitly as microVM/gVisor.)

### 6.10
What improves: the provider absorbs host OS and kernel patching, the container runtime, and
much of the network attack surface (fewer things to misconfigure at those layers); workloads
run on microVM isolation (Firecracker) by default; scaling and availability are managed. What
does **not** improve — and is where most breaches occur: **IAM/identity** (the function's role
is its blast radius, and over-permissioning is the top risk), **configuration** (public
resources, encryption settings), **application security** (Chapter 4 Stops 6–7 — injection,
authz, SSRF are all still yours; SSRF is arguably *worse* because the function's credentials
are one metadata call away), and **data protection**. New responsibilities/challenges:
per-function least-privilege roles at scale, event-source security (an S3 or SQS trigger is an
attack surface), dependency/supply-chain security in the deployment package, secrets
management, cold-start and ephemerality complicating some monitoring, and harder traditional
network controls. Balanced conclusion: serverless is a genuine security *improvement at the
host/OS layers* and a *responsibility shift* toward identity, config, and app security — "more
secure" only if you invest where the responsibility landed.

### 6.11
Assign by rung (the §5 procedure): **trusted microservices** → hardened containers on EKS
(shared node kernel acceptable because code is trusted and blast radius is bounded by
NetworkPolicy + least-priv IRSA roles), with non-root/seccomp/PSS and Fargate profiles for any
higher-sensitivity services. **Untrusted third-party plugins** → per-execution microVMs
(Firecracker) or gVisor, no standing credentials, no egress, single-use, in an isolated
account — because untrusted code must not share a kernel with value. **Regulated data
processing** → Nitro Enclaves (or dedicated hosts), because the threat model may include the
infrastructure operator and side channels; hardware memory encryption and attestation-gated key
release (Chapter 80). Unifying controls across all rungs: **IAM as the perimeter** (least-priv
roles per workload, short-lived credentials, permission boundaries, SCPs), **the control plane
as the detection surface** (CloudTrail on every API call, GuardDuty, Config rules for
misconfiguration), **network segmentation** (private subnets, SGs, NetworkPolicy, egress
control), and **policy-as-code** to prevent escape-enabling configs (Chapters 91, 105). The
platform is heterogeneous by rung but unified by identity and detection.

### 6.12
The statement is **ill-posed** as written, because "Kubernetes" and "plain EC2" are not the
same kind of thing and "more secure" is unqualified. Precisely: on the **isolation axis**,
plain EKS pods share a node's kernel — a *lower* rung than a dedicated EC2 VM per workload, and
lower than Fargate microVMs — so Kubernetes is not inherently more isolating. On the
**operational/policy axis**, Kubernetes offers stronger built-in mechanisms (RBAC,
NetworkPolicy, admission control, declarative config, standardized hardening) that make it
easier to enforce least privilege and segmentation at scale than hand-managed EC2 — so it can
yield a more *consistently* secured fleet. On the **shared responsibility axis**, EKS shifts
control-plane management to AWS while you still own nodes and workloads; plain EC2 leaves more
to you. Conclusion: neither is "more secure" absolutely; Kubernetes trades weaker per-workload
isolation (shared node kernel) for stronger, more uniform policy and automation — and the right
comparison is workload-by-workload against the isolation ladder and the responsibility model,
choosing Fargate/microVMs within the cluster for workloads that need a higher rung.

### 6.13
`uname -r` on the host and inside `docker run --rm alpine uname -r` return the identical kernel
version because there is only one kernel — the container is processes on the host kernel, not a
separate OS (§4.2, §6.1). Then: `docker run -d --name x alpine sleep 600; CPID=$(docker inspect
-f '{{.State.Pid}}' x); ps -p $CPID -o pid,comm` shows the container's `sleep` with a real host
PID, while `docker exec x ps aux` shows it as PID 1 — the same process, two views, because the
PID namespace re-numbers the process's *view* without moving it out of the host kernel's process
table. Explanation: namespaces isolate what a process *sees* (its own PID tree, network,
mounts) but the process itself exists once, in the shared host kernel, schedulable and
inspectable from the host — the concrete proof that a container is not a VM.

### 6.14
Expected approach: iterate containers (`docker ps -q`) and for each inspect the escape-enabling
settings — `docker inspect -f '{{.Name}} priv={{.HostConfig.Privileged}}
caps={{.HostConfig.CapAdd}} pid={{.HostConfig.PidMode}} net={{.HostConfig.NetworkMode}}
mounts={{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}'`. Flag as findings: `Privileged=
true`; `CapAdd` containing `SYS_ADMIN`/`SYS_PTRACE`/`SYS_MODULE`/`NET_ADMIN`; `PidMode=host` or
`NetworkMode=host`; mounts of `/var/run/docker.sock`, `/`, `/proc`, `/sys`, or host device
paths; `runAsUser=0`/no `USER`. Admission-policy pseudocode (Chapter 105 / Kyverno-OPA shape):
`deny if securityContext.privileged == true; deny if capabilities.add intersects {SYS_ADMIN,...};
deny if hostPID or hostNetwork or hostPATH mounts of sensitive paths; deny if
runAsNonRoot != true; require seccompProfile != Unconfined`. The output is a findings list plus
the preventive control for each, connecting runtime audit (detect) to admission policy
(prevent).

### 6.15
Expected: identify the workload's role (`aws lambda get-function-configuration --query Role`, or
the EC2/ECS task role), enumerate attached and inline policies (`aws iam
list-attached-role-policies`, `list-role-policies`, `get-policy-version`), and — better — use
IAM Access Analyzer / `aws iam simulate-principal-policy` or the last-accessed data
(`get-service-last-accessed-details`) to find which permissions are actually used versus
granted. Reduce to least privilege by replacing broad actions/resources (`s3:*` on `*`) with the
specific actions on specific ARNs the workload uses. Verify by removing a suspected-unused
permission and confirming, via CloudTrail, that any call needing it now logs `AccessDenied`
(and that legitimate operations still succeed). The exercise mirrors the container-hardening lab
in the identity domain: measure actual behavior, grant only that, and prove the removed
capability now denies — the "eliminate, then verify" discipline (Chapter 1 §11.5) applied to
IAM.

### 6.16
A container is a process (or process group) started with `clone()` using namespace flags,
constrained by cgroups, with reduced Linux capabilities and usually a seccomp filter — there is
no distinct "container" kernel object (Chapter 2 §4.1). It is not a security boundary like a VM
because **all containers on a host share one kernel**: namespaces filter what a process *sees*
(PID/network/mount/etc.) and cgroups limit what it *consumes*, but the processes run in the
same kernel, calling the same ~350 syscalls into the same ~30M-line codebase as the host. So a
kernel vulnerability reachable from an allowed syscall (Dirty COW, Dirty Pipe) escapes every
container regardless of hardening, and "root in a container" is real host UID 0 restricted only
by capabilities/namespaces — one misconfiguration (`--privileged`, added `SYS_ADMIN`, mounted
`docker.sock`, hostPath) from host root. A VM, by contrast, is isolated by hardware
(EPT/NPT, VT-x) behind a small hypervisor with a narrow VM-exit surface. Containers are an
excellent *hardening* boundary and a poor *trust* boundary; use VMs/microVMs where mutually
untrusted code shares hardware.

### 6.17
Bottom to top: **shared process / logical** — cheapest, weakest; only for your own trusted
multi-tenant code where isolation is app-level, with strong per-tenant IAM and keying; a bug is
a cross-tenant leak. **Containers (shared kernel)** — cheap, moderate; for trusted first-party
workloads where the threat is app bugs and noisy neighbors, not kernel escape; harden with
non-root/seccomp/cap-drop/NetworkPolicy. **microVMs (Firecracker/Kata) / gVisor** — moderate
cost, strong; when you need near-container density but the workload or its neighbors are
untrusted, or you want to defeat kernel-escape risk (this is what Lambda/Fargate use). **VMs** —
expensive, very strong; strong tenant separation, compliance alignment, per-workload kernels.
**Separate physical hardware / dedicated hosts** — most expensive, strongest; when the threat
includes side channels from co-tenants or the infrastructure operator, or regulation demands
physical separation. Choose the *lowest* rung that defeats the actual threat (the §5
procedure), then add defense in depth; I'd move up a rung for untrusted code, untrusted
neighbors, regulated data, or after an incident, and down for cost/density when code and
neighbors are trusted and blast radius is bounded.

### 6.18
The perimeter is **identity — IAM and the control plane** — not the network. Cloud data is read
and resources are controlled through the provider's public API, authorized by IAM, so an
attacker with the right permissions (a leaked key, an over-permissioned or assumed role) reads
S3/DynamoDB/etc. from anywhere on the internet without touching a host, VPC, or firewall — the
network controls never see the request. Most breaches happen despite firewalls because the
firewall guards the *network* path while the actual access happens over the *API* path via
identity: misconfigured public resources (public buckets, public RDS), leaked long-lived
credentials, and over-broad roles are the dominant causes, and none of them are network
problems. Firewalls/security groups remain necessary for the workloads that *do* live on the
network, but in the cloud the primary controls are least-privilege IAM, short-lived
credentials, blocking public access, and control-plane monitoring (CloudTrail/GuardDuty).

### 6.19
**EC2:** AWS secures hardware and hypervisor; the customer patches the guest OS, secures the
app, configures the network (SGs), manages IAM, and configures encryption. Most-often-wrong:
unpatched OS, over-broad security groups, and instance roles with excessive permissions plus
IMDSv1 (SSRF → credential theft). **S3:** AWS secures the storage infrastructure and
durability; the customer controls bucket policy, public-access settings, IAM, and encryption.
Most-often-wrong: public buckets and over-broad bucket/IAM policies — the archetypal cloud
breach. **Lambda:** AWS secures everything down to the runtime; the customer secures the code,
the execution role, and event-source config. Most-often-wrong: over-permissioned execution
roles (the function's blast radius) and unvalidated event input (injection/SSRF with
credentials one metadata call away). The through-line customers get wrong on every service:
**identity and configuration** — precisely the rows that never move to the provider (§5.2).

### 6.20
Design (the §5 procedure): classify the code as untrusted and the neighbors/data as things it
must not reach; the threat is deliberate escape and side channels, so the shared-kernel rung is
inadequate — choose **per-execution microVMs (Firecracker)** or gVisor, single-use, never
reused across tenants. Strip the environment: no standing cloud credentials, no service-account
token, no egress by default, strict CPU/memory/wall-clock cgroup limits, seccomp, isolated
subnet and account. Add defense in depth: run the sandbox host with nothing of value on it, so
a successful escape lands in an empty, credential-less, egress-less, isolated environment. When
isolation fails (assume it will): the blast radius is bounded to that host because it holds no
credentials and can reach nothing; detection fires on the anomaly. Detection: syscall-anomaly
monitoring (Falco/eBPF), any egress attempt from an egress-less network (Flow Logs), resource/
time outliers, and sandbox crash rate as an exploitation canary. Recovery: destroy the host,
rotate anything it could conceivably have touched, investigate via the recorded telemetry. The
answer names the rung, strips the environment, bounds the blast radius, and plans for failure —
the whole Part 0 discipline applied.

---

*This concludes Part 0. You now hold the mental model the rest of the book fills in: the machine
(Ch. 1), the kernel boundary (Ch. 2), how programs reach the world (Ch. 3), the request map
(Ch. 4), the production components (Ch. 5), and the isolation ladder and cloud abstractions
(Ch. 6). Next: Part 1 — Networking From First Principles, beginning with Chapter 7, Bits, Bytes,
Binary and Hex — because before we can read a packet, we must read the bytes it is made of. The
first capstone project, "Harden a Linux server and prove it," follows Part 2 and will exercise
everything from Chapters 1–6.*
