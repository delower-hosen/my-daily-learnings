# Chapter 30 — SSH Internals: Transport, Authentication, Channels, Tunnels, and Key Hygiene

---

## 1. Why This Matters

SSH (Secure Shell) is how engineers access servers — and therefore one of the most security-critical and
most-attacked services on the internet (Chapter 10: `0.0.0.0/0` on port 22 is a top finding). It is also a
beautiful applied example of the cryptography you just built (Chapters 25–28): SSH establishes its own secure
channel (key exchange + symmetric AEAD), authenticates with public keys (Chapter 26), and provides tunnels
that are a double-edged security tool. This chapter completes Part 1 by covering SSH internals and the key
hygiene that is a core operational-security practice.

For a cloud security engineer, SSH matters because:

1. **SSH access is a primary attack target and a primary access-control decision** — port 22 exposed to the
   internet is relentlessly brute-forced; how you provide and control SSH access (keys, bastions, SSM) is a
   core decision (Chapters 10, 78).
2. **SSH key management is a real, often-neglected problem** — SSH keys are long-lived credentials that
   accumulate, are rarely rotated, and grant access; poor key hygiene (shared keys, no rotation, keys on
   disk, `authorized_keys` sprawl) is a common finding.
3. **SSH tunnels/port-forwarding are a double-edged tool** — legitimately for secure access, but also an
   exfiltration/pivoting channel (like DNS/ICMP tunneling — Chapters 17, 23) that attackers use.
4. **The modern cloud alternative (SSM Session Manager)** eliminates open SSH ports and long-lived keys —
   a better model you should know (Chapter 78).

The core idea: **SSH provides secure remote access by establishing its own encrypted channel (key exchange +
symmetric AEAD — like TLS, Chapters 26–28), authenticating with public-key cryptography (Chapter 26 — the
preferred method over passwords), and multiplexing channels (shells, port-forwards/tunnels) over that
connection. It is a top attack target (brute-forced when exposed) and a key-management challenge (long-lived
keys accumulate). The modern cloud direction eliminates open SSH ports and long-lived keys (SSM Session
Manager, short-lived certificates).** SSH is applied cryptography for remote access, with key hygiene and
access control as the core security practices, completing Part 1's networking foundation.

---

## 2. Prerequisites

- **Chapters 25–28** (SSH uses key exchange, symmetric AEAD, and public-key auth — the same cryptography as
  TLS). Chapter 26 (asymmetric keys — SSH key pairs), Chapter 15 §5 (SSH first-connect TOFU — host key
  verification).
- Chapter 3 (SSH is a service on port 22 — bind/exposure), Chapter 10 (`0.0.0.0/0` on 22 — the top finding),
  Chapter 2 §7 (privilege — SSH access to a host).
- Forward: Chapter 78 (SSM Session Manager — the cloud alternative), Chapter 68 (secrets/key management),
  Chapter 33 (Linux users/access).

---

## 3. Mental Model

**SSH is secure remote access built on the same cryptography as TLS: it establishes its own encrypted channel
(key exchange + symmetric AEAD — Chapters 26, 25), authenticates the server (via its host key) and the client
(preferably via public keys — Chapter 26), then multiplexes channels (shells, port-forwards/tunnels) over the
connection. It is a top attack target and a key-management challenge; the modern cloud direction removes open
SSH ports and long-lived keys.**

```
   SSH = its own secure channel (key exchange + symmetric AEAD, like TLS) + public-key authentication + channels

   THE CONNECTION (like TLS — Chapters 26-28):
     1. Transport layer: key exchange (ECDHE-like) establishes a shared symmetric key; server presents its
        HOST KEY (the client verifies it — first-connect TOFU, Chapter 15 §5; then it's pinned in known_hosts).
     2. Authentication layer: the CLIENT authenticates — PUBLIC KEY (preferred, Chapter 26) or password (weak).
     3. Connection layer: multiplex CHANNELS over the encrypted connection: interactive shell, command exec,
        PORT FORWARDING / TUNNELS (local, remote, dynamic/SOCKS).

   SECURITY REALITIES:
     - Port 22 exposed = relentlessly BRUTE-FORCED (Chapter 10: 0.0.0.0/0 on 22 = top finding).
     - Public-key auth >> password auth (keys not brute-forceable like passwords).
     - SSH keys = LONG-LIVED credentials that accumulate, rarely rotate -> KEY HYGIENE is critical.
     - Tunnels = double-edged (secure access AND exfiltration/pivoting — Chapters 17, 23).
     - Modern cloud: SSM Session Manager (no open port, no keys), short-lived SSH certificates (Chapter 78).
```

Three ideas:

1. **SSH is applied cryptography for remote access.** Its three layers (transport = secure channel via key
   exchange + AEAD; authentication = public-key or password; connection = channels) mirror TLS (Chapters
   26–28): establish an encrypted, authenticated channel, then use it. Public-key authentication (Chapter 26)
   is the preferred method — keys can't be brute-forced like passwords.
2. **SSH is a top attack target and a key-management challenge.** Exposed port 22 is relentlessly
   brute-forced (Chapter 10 — the top `0.0.0.0/0` finding), so access control (keys not passwords, restrict
   the source, bastion/SSM) matters. And SSH keys are long-lived credentials that accumulate (in
   `authorized_keys`, on developer machines) and are rarely rotated — **key hygiene** (rotation, no shared
   keys, protected private keys, `authorized_keys` audit) is a core, often-neglected practice.
3. **The modern cloud direction eliminates open ports and long-lived keys.** **SSM Session Manager** (Chapter
   78) provides SSH-like access with *no open port* (access brokered through the AWS API, IAM-authenticated,
   logged) and *no keys*; **short-lived SSH certificates** (an internal CA signs ephemeral SSH certs, like
   Chapter 27's PKI for SSH) replace long-lived keys. These address SSH's core weaknesses (exposed ports,
   long-lived keys).

**The security framing:** SSH is secure remote access — applied cryptography (Chapters 25–28) with public-key
authentication — but its operational security rests on access control (not exposing port 22 broadly, using
keys not passwords, restricting the source, using bastions/SSM) and key hygiene (rotation, protected private
keys, no sharing, `authorized_keys` audit). Tunnels are a double-edged tool (secure access and exfiltration).
The modern cloud direction (SSM Session Manager, short-lived certificates) eliminates the exposed-port and
long-lived-key weaknesses — the recommended model (Chapter 78). SSH completes Part 1 as the practical
application of the networking and cryptography foundation to remote access.

---

## 4. Fundamentals

### 4.1 The SSH connection (three layers, like TLS)

SSH establishes a secure connection in three layers (mirroring TLS — Chapters 26–28):

```
   1. TRANSPORT LAYER: establishes the encrypted channel.
      - Key exchange (ECDHE-like, e.g. curve25519-sha256) -> shared symmetric key (forward secrecy, Ch26).
      - The SERVER presents its HOST KEY (an asymmetric key pair) proving its identity; the client verifies it.
      - Then symmetric AEAD (e.g. chacha20-poly1305, aes-gcm — Chapter 25) protects the channel.
   2. AUTHENTICATION LAYER: the CLIENT authenticates to the server.
      - Public-key (preferred), password (weaker), keyboard-interactive, host-based, etc.
   3. CONNECTION LAYER: multiplex CHANNELS over the encrypted connection.
      - Interactive shell, remote command execution, port forwarding (tunnels), SFTP/SCP (file transfer).
```

The parallel to TLS is exact: transport (key exchange + AEAD = TLS's handshake + record protocol),
authentication (public-key = TLS's client cert / mTLS, Chapter 28), connection (channels = multiplexed
streams). SSH is essentially "TLS-like secure channel + authentication + multiplexed channels, purpose-built
for remote access." It uses the same cryptography (Chapters 25–28), which is why understanding TLS makes SSH
familiar.

### 4.2 Host key verification (SSH's trust bootstrapping — TOFU)

When you first connect to an SSH server, it presents its **host key**, and you verify it — SSH's
trust-bootstrapping (Chapter 15 §5's TOFU):

```
   First connection: "The authenticity of host 'server (1.2.3.4)' can't be established.
     ED25519 key fingerprint is SHA256:... Are you sure you want to continue connecting (yes/no)?"
   -> You accept (TOFU — trust on first use, Chapter 15 §5), and the host key is PINNED in ~/.ssh/known_hosts.
   Subsequent connections: the client checks the host key matches known_hosts.
   If it CHANGES: "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! ... POSSIBLE MITM!" -> connection refused.
```

Host key verification is SSH's answer to the bootstrapping trust problem (Chapter 15 §5): it uses **TOFU with
pinning** — you trust the host key on first connection (weak — you can't verify it then, unless you have the
fingerprint out-of-band), but it's pinned in `known_hosts` and *changes are detected* (a changed host key
means a possible MITM or a reinstalled server). This is the "managed TOFU" from Chapter 15 §5 — weaker than
PKI's pre-installed anchor (TLS/certificates — Chapter 27), but it detects later changes. The security lesson:
verify the host key fingerprint out-of-band on first connect for sensitive servers (don't blindly accept),
and *never ignore* a changed-host-key warning (it's a potential MITM). SSH certificates (§4.6) improve this by
having a CA sign host keys (like PKI), so clients verify via the CA rather than TOFU.

### 4.3 Public-key authentication (the preferred method — Chapter 26 applied)

SSH's preferred client authentication is **public-key authentication** (Chapter 26):

```
   The user has a KEY PAIR: private key (~/.ssh/id_ed25519, SECRET — Chapter 26 §4.1) + public key.
   The user's PUBLIC key is placed in the server's ~/.ssh/authorized_keys (for their account).
   Authentication: the server challenges the client to prove it holds the private key (a signature — Chapter
     26 §4.3); the client signs, the server verifies with the public key -> authenticated. No password sent.

   Why public-key >> password:
     - Keys are not brute-forceable like passwords (a strong key is infeasible to guess).
     - No secret is sent to the server (the private key never leaves the client).
     - Passwords are phishable, reusable, and brute-forced (Chapter 10 — exposed port 22 brute-force).
```

Public-key authentication (Chapter 26 §4.3 applied to SSH) is strongly preferred over passwords: the private
key stays on the client (never sent), keys aren't brute-forceable, and it eliminates the password-brute-force
attack that plagues exposed SSH (Chapter 10). Best practice: **disable password authentication entirely**
(`PasswordAuthentication no` in sshd_config) and use only public keys — this defeats brute-forcing outright.
Use modern key types (Ed25519 — Chapter 26 §4.1, smaller/faster; or RSA 3072+), protect the private key
(passphrase + file permissions 600 — Chapter 26 §4.1), and use an SSH agent to avoid repeatedly entering the
passphrase.

### 4.4 SSH key hygiene (the core operational practice)

SSH keys are **long-lived credentials** that accumulate and are rarely managed — making **key hygiene** a
core, often-neglected practice:

```
   THE KEY-MANAGEMENT PROBLEM:
     - SSH keys don't expire (unlike certificates) -> they live forever unless rotated.
     - authorized_keys accumulates keys (departed employees, old keys, shared keys) -> sprawl.
     - Private keys sit on developer machines, in CI systems, in scripts -> exposure risk.
     - Shared keys (one key for many people/systems) -> no accountability, wide blast radius.
   KEY HYGIENE (the practices):
     - One key per person/purpose (accountability, not shared).
     - Rotate keys periodically; REMOVE keys of departed people/decommissioned systems from authorized_keys.
     - Protect private keys (passphrase, file permissions 600, agent; ideally hardware — YubiKey, or KMS).
     - AUDIT authorized_keys across the fleet (who has access to what?).
     - Prefer SHORT-LIVED SSH CERTIFICATES (§4.6) over long-lived keys (they expire automatically).
```

Key hygiene is where SSH security most often fails operationally: keys don't expire, so `authorized_keys`
accumulates keys from departed employees and old systems (sprawl), private keys proliferate on machines and in
CI (exposure), and shared keys destroy accountability and widen blast radius. The practices: one key per
person/purpose (no sharing), rotation, removing stale keys, protecting private keys (passphrase + permissions
+ hardware/agent), and auditing `authorized_keys` fleet-wide. The stronger answer is **short-lived SSH
certificates** (§4.6) — they expire automatically, eliminating the accumulation/rotation problem. This is the
SSH instance of the general credential-hygiene principle (short-lived > long-lived — Chapters 1, 68).

### 4.5 SSH tunnels and port forwarding (the double-edged tool)

SSH can **forward ports** (tunnel traffic) over the encrypted connection — a powerful, double-edged tool:

```
   LOCAL forwarding (-L): forward a local port to a remote destination THROUGH the SSH server.
     ssh -L 5432:db.internal:5432 bastion  -> localhost:5432 tunnels to db.internal:5432 via the bastion.
     Legit use: securely reach an internal service (the DB) through a bastion.
   REMOTE forwarding (-R): forward a remote port back to the local side.
     ssh -R 8080:localhost:80 remote  -> the remote's port 8080 tunnels to your local port 80.
     RISK: exposes a local service through the remote (and a compromised remote can reach back).
   DYNAMIC forwarding (-D): a SOCKS proxy tunneling arbitrary traffic through the SSH server.
     ssh -D 1080 server  -> a SOCKS proxy on localhost:1080 tunneling all traffic via the server.

   DOUBLE-EDGED: legitimate secure access, BUT also an EXFILTRATION/PIVOTING channel:
     - An attacker with SSH access uses tunnels to pivot into internal networks and exfiltrate data
       (like DNS/ICMP tunneling — Chapters 17, 23), evading egress controls.
     - Reverse tunnels (-R) can create persistent backdoors.
```

SSH tunnels are legitimately used for secure access (reaching an internal service through a bastion — the
classic bastion pattern) but are equally a **pivoting and exfiltration tool** for attackers: with SSH access,
an attacker tunnels into internal networks (bypassing network segmentation — Chapter 13) and exfiltrates data
over the encrypted SSH connection (evading egress controls — like DNS/ICMP tunneling, Chapters 17, 23), and
reverse tunnels can create backdoors. So SSH access is powerful — it's not just shell access but a network
pivot. Security implications: restrict/disable port forwarding where not needed (`AllowTcpForwarding no`),
monitor SSH connections and tunneling, and recognize that granting SSH access grants network-pivot capability
(a blast-radius consideration). The double-edged nature is the recurring "feature = attack tool" pattern
(Chapters 5, 9, 17, 23).

### 4.6 SSH certificates and the modern cloud direction (SSM)

Two modern improvements address SSH's core weaknesses (exposed ports, long-lived keys):

- **SSH certificates:** instead of long-lived keys in `authorized_keys`, an internal **SSH CA** signs
  **short-lived SSH certificates** (like PKI for SSH — Chapter 27): a user authenticates to the CA (via SSO/
  MFA), gets a short-lived certificate (hours), and uses it to SSH; the server trusts the CA (not individual
  keys). Benefits: no `authorized_keys` sprawl (trust the CA, not each key), automatic expiry (short-lived —
  §4.4), central control (revoke at the CA), and host-key certificates (CA-signed host keys, fixing TOFU —
  §4.2). Tools: Teleport, HashiCorp Vault SSH, Netflix BLESS, smallstep. This is the SSH equivalent of
  short-lived certificates + PKI (Chapters 26, 27) — the modern best practice.
- **AWS SSM Session Manager (Chapter 78 — the cloud direction):** provides SSH-like shell access with **NO
  open SSH port** (access is brokered through the AWS API — the instance connects *out* to SSM, so no inbound
  port 22), **NO SSH keys** (IAM authentication — the instance's SSM agent + your IAM permissions), **full
  logging** (every session logged in CloudTrail/S3), and **no bastion needed**. This eliminates SSH's biggest
  weaknesses (exposed port 22 brute-forcing, key management) entirely — access is IAM-authenticated, logged,
  and requires no inbound port. It is the **recommended cloud approach** for instance access (Chapter 78).

The modern direction: **eliminate open SSH ports and long-lived keys** — via SSM Session Manager (no port, no
keys, IAM-auth, logged — the cloud best practice) or short-lived SSH certificates (CA-signed, auto-expiring).
Both address the exposed-port brute-force problem (Chapter 10) and the key-hygiene problem (§4.4). For a cloud
security engineer, **prefer SSM Session Manager** for instance access (no port 22 exposure, IAM-controlled,
logged); if SSH is needed, use short-lived certificates and restrict access (bastion, source-IP,
key-only-auth).

---

## 5. Deep Technical Explanation: SSH as Applied Cryptography and the Access-Control/Key-Hygiene Core

SSH is the practical application of Part 1's cryptography (Chapters 25–28) to remote access — and understanding
it as applied cryptography, plus recognizing that its security rests on access control and key hygiene (not
the cryptography, which is sound), is the synthesis.

**SSH is TLS-like cryptography purpose-built for remote access:** SSH's three layers mirror TLS exactly —
transport (key exchange + symmetric AEAD, with forward secrecy — Chapters 25, 26), authentication (public-key,
like TLS mTLS — Chapters 26, 28), and connection (multiplexed channels, like HTTP/2 streams — Chapter 29). It
uses the same primitives (ECDHE-like key exchange, ChaCha20-Poly1305/AES-GCM AEAD, Ed25519/RSA keys), so
everything from Chapters 25–28 applies. The cryptography is sound — SSH's security failures are almost never
cryptographic; they are **operational**: exposed ports, weak authentication (passwords), and poor key
hygiene. This is the Chapter 25 §5 lesson (correct usage > algorithm choice) applied to a protocol: the crypto
is fine; the failures are misuse (password auth, exposed port 22, key sprawl).

**SSH's security rests on access control and key hygiene (the operational core):** because the cryptography is
sound, SSH security is about *how you use it*:

1. **Access control** — the exposed-port problem (Chapter 10: `0.0.0.0/0` on port 22 is relentlessly
   brute-forced). Defenses: use public-key auth only (disable passwords — defeats brute-force outright),
   restrict the source (bastion, source-IP, VPN), and ideally *eliminate the open port* (SSM Session Manager
   — §4.6). Granting SSH access is granting host access *and network-pivot capability* (via tunnels — §4.5), a
   blast-radius consideration.
2. **Key hygiene** — the long-lived-credential problem (§4.4): SSH keys don't expire, accumulate in
   `authorized_keys`, proliferate on machines/CI, and shared keys destroy accountability. This is the SSH
   instance of the general credential-hygiene principle: **short-lived > long-lived** (Chapters 1 §7, 68). The
   answer is one-key-per-person + rotation + audit, and ultimately **short-lived certificates** (§4.6) that
   expire automatically — the same "shrink the credential window" principle as short-lived cloud credentials
   (Chapters 1, 68).

**Tunnels make SSH access more than shell access (the blast-radius point):** SSH port-forwarding (§4.5) means
SSH access is a *network pivot* — an attacker with SSH access tunnels into internal networks (bypassing
segmentation — Chapter 13) and exfiltrates over the encrypted connection (evading egress — like DNS/ICMP
tunneling, Chapters 17, 23). So the blast radius of SSH access is not just "a shell on this host" but
"network access from this host, encrypted and hard to inspect." This double-edged nature (the feature =
attack-tool pattern — Chapters 5, 9, 17, 23) means SSH access should be granted carefully, forwarding
restricted where not needed, and SSH connections monitored.

**The modern direction eliminates SSH's structural weaknesses:** SSH's two core problems — exposed ports
(brute-force) and long-lived keys (hygiene) — are structural, and the modern answers eliminate them: **SSM
Session Manager** (no open port — access via the AWS API with the instance connecting out; no keys — IAM auth;
logged) removes both the exposed-port and key problems entirely, and **short-lived SSH certificates** (CA-
signed, auto-expiring — like PKI, Chapter 27) remove the key-hygiene problem. This is the culmination of
several book themes: short-lived credentials (Chapters 1, 68), PKI/certificates over raw keys (Chapters 26,
27), identity-based access (IAM — Chapter 6), and no-open-ports (the exposed-service problem — Chapters 3, 10).
For a cloud security engineer, the recommendation is clear: **prefer SSM Session Manager** (or short-lived
certificates) over traditional key-based SSH with an open port.

The unifying insight: **SSH is applied cryptography (Chapters 25–28) for remote access — TLS-like secure
channel + public-key authentication + multiplexed channels — whose cryptography is sound but whose security
rests on operational practices: access control (public-key-only auth, restrict source, eliminate the open
port) against the top attack target (brute-forced port 22 — Chapter 10), and key hygiene (short-lived >
long-lived, one-key-per-person, rotation, audit) against the long-lived-credential problem; with tunnels
making SSH access a network-pivot (blast-radius consideration), and the modern cloud direction (SSM Session
Manager — no port, no keys, IAM-auth, logged; short-lived SSH certificates) eliminating SSH's structural
weaknesses.** SSH completes Part 1 as the practical application of its networking and cryptography foundation
to the security-critical problem of remote access.

---

## 6. Internals: SSH in Practice

### 6.1 Key generation and public-key auth (Chapter 26 applied)

```bash
# Generate a modern SSH key pair (Ed25519 — Chapter 26 §4.1):
$ ssh-keygen -t ed25519 -C "you@example.com"          # creates ~/.ssh/id_ed25519 (private) + .pub (public)
#   Set a PASSPHRASE (protects the private key if the file is stolen — Chapter 26 §4.1).
$ chmod 600 ~/.ssh/id_ed25519                          # protect the private key (§4.3)

# Place the public key on the server (into ~/.ssh/authorized_keys for your account):
$ ssh-copy-id -i ~/.ssh/id_ed25519.pub user@server     # or manually append the .pub to authorized_keys

# Connect (public-key auth — no password sent, §4.3):
$ ssh -i ~/.ssh/id_ed25519 user@server
# Use an agent to avoid re-entering the passphrase:
$ ssh-add ~/.ssh/id_ed25519
```

Ed25519 keys (Chapter 26 §4.1 — modern, small, fast), a passphrase-protected private key with 600 permissions
(§4.3), the public key in `authorized_keys`, and public-key auth (no password sent). This is the preferred SSH
authentication (§4.3).

### 6.2 Harden the SSH server (sshd_config)

```bash
# Key sshd_config hardening (the access-control practices — §4.3, §4.5):
$ sudo grep -E '^(PasswordAuthentication|PermitRootLogin|AllowTcpForwarding|PubkeyAuthentication|Port)' /etc/ssh/sshd_config
# Recommended:
#   PasswordAuthentication no      # DISABLE passwords -> defeats brute-force (§4.3) — the key setting
#   PubkeyAuthentication yes        # public-key only
#   PermitRootLogin no              # no direct root login (use sudo — Chapter 2, 33)
#   AllowTcpForwarding no           # disable tunnels if not needed (§4.5 — limit pivoting)
#   AllowUsers / AllowGroups        # restrict who can SSH
#   Port 22 (or a non-default port — minor obscurity, not a real control)
$ sudo systemctl reload sshd
```

`PasswordAuthentication no` is the single most impactful hardening (defeats brute-force — §4.3); plus no root
login, restricted forwarding (§4.5), and restricted users. These are the access-control practices (§5).

### 6.3 Host key verification and known_hosts (§4.2)

```bash
# First connect: verify the host key fingerprint OUT-OF-BAND (don't blindly accept — §4.2):
$ ssh user@server                                      # shows the fingerprint; verify it, then accept (TOFU)
$ ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub     # (on the server) the fingerprint to verify against
# The host key is pinned in ~/.ssh/known_hosts. A CHANGED host key -> warning -> possible MITM (§4.2):
$ cat ~/.ssh/known_hosts | head
# NEVER blindly clear known_hosts on a warning without understanding why the key changed.
```

Verify the host key fingerprint out-of-band on first connect (§4.2 — TOFU with pinning, Chapter 15 §5), and
never ignore a changed-host-key warning (possible MITM). SSH certificates (§4.6) improve this (CA-signed host
keys).

### 6.4 Audit key hygiene and SSH access (§4.4)

```bash
# Audit authorized_keys (who has access — the key-sprawl problem, §4.4):
$ for u in $(cut -d: -f1 /etc/passwd); do
    f="/home/$u/.ssh/authorized_keys"; [ -f "$f" ] && echo "== $u ==" && ssh-keygen -lf "$f" 2>/dev/null; done
# Look for: stale keys (departed people), shared keys, weak key types. Remove stale keys.
$ sudo grep -r "" /root/.ssh/authorized_keys 2>/dev/null    # root's authorized_keys (should be empty/minimal)

# Audit SSH connections (§4.5 — pivoting/tunneling detection):
$ sudo grep sshd /var/log/auth.log | grep -E 'Accepted|Failed' | tail   # successful/failed logins (Ch36)
$ ss -tnp | grep :22                                      # active SSH connections
```

Auditing `authorized_keys` fleet-wide (§4.4 — the key-sprawl/hygiene problem) and SSH logins/connections (for
brute-force and pivoting) are core operational-security practices. Stale keys (departed people) and shared
keys are common findings.

### 6.5 The modern cloud alternative (SSM — §4.6, Chapter 78)

```bash
# AWS SSM Session Manager — SSH-like access with NO open port, NO keys, IAM-auth, logged (§4.6, Chapter 78):
$ aws ssm start-session --target i-0abc123                # a shell, brokered via the AWS API — no port 22!
#   Requires: the SSM agent on the instance, an instance role allowing SSM, and your IAM permission.
#   Every session is logged (CloudTrail/S3). No inbound port, no SSH keys to manage.
# This eliminates SSH's exposed-port (Chapter 10) and key-management (§4.4) problems — the cloud best practice.
```

SSM Session Manager (§4.6, Chapter 78) is the recommended cloud approach — no open port 22, no SSH keys, IAM
authentication, full logging. It eliminates SSH's two structural weaknesses (exposed port brute-force, key
management).

---

## 7. Real-World Example: SSH in the Ledger System

**Ledger's SSH access model, evolving toward the modern direction:**

- **System A (VPS):** engineers access the VPS via SSH. Hardening (§4.2, §4.3): **public-key auth only**
  (`PasswordAuthentication no` — defeats the relentless port-22 brute-forcing, Chapter 10), **no root login**
  (sudo instead — Chapters 2, 33), **restricted source** (SSH only from a bastion or the office/VPN IP —
  Chapter 10, not `0.0.0.0/0`), Ed25519 keys with passphrases (Chapter 26), and host-key verification.
- **Key hygiene (§4.4):** Ledger audits `authorized_keys` (removing departed engineers' keys — the sprawl
  problem), uses one key per person (accountability), and rotates keys — the core operational practice. But
  long-lived keys remain a liability.
- **System B/C (AWS) — the modern direction (§4.6, Chapter 78):** Ledger uses **SSM Session Manager** for
  instance access — **no open port 22** (no brute-force target — Chapter 10), **no SSH keys** (IAM
  authentication — the instance role + engineer's IAM permission), **full session logging** (CloudTrail/S3 —
  Chapter 82), and **no bastion**. This eliminates SSH's structural weaknesses. Where SSH is still needed,
  Ledger uses **short-lived SSH certificates** (an internal SSH CA — §4.6) instead of long-lived keys.
- **Tunnels (§4.5):** Ledger restricts SSH port-forwarding (`AllowTcpForwarding no` where not needed) —
  recognizing that SSH access is a network-pivot (an attacker could tunnel into internal networks / exfiltrate
  — Chapters 13, 17, 23). SSM's controlled, logged access further limits this.
- **Access as blast radius (§5):** Ledger treats SSH/SSM access as high-privilege (host access + network
  pivot), granting it minimally (least privilege — Chapter 2), logging it, and preferring IAM-controlled SSM
  (auditable, revocable) over standing SSH keys.

The SSH decisions Ledger makes: public-key-only auth (no passwords — defeats brute-force), restrict source
(not `0.0.0.0/0` — Chapter 10), no root login, key hygiene (audit/rotate/one-per-person), restrict tunneling,
and — the modern direction — **SSM Session Manager (no port, no keys, IAM-auth, logged)** or short-lived SSH
certificates. The failures Ledger avoids: exposed port 22 with passwords (brute-forced), key sprawl (stale/
shared keys), unrestricted tunneling (pivoting), and unlogged access.

The Ledger takeaway: **SSH is Ledger's remote access — hardened with public-key-only auth (defeating
brute-force), restricted source, no root login, and key hygiene — but the modern direction eliminates SSH's
structural weaknesses via SSM Session Manager (no open port, no keys, IAM-authenticated, logged) or
short-lived SSH certificates, which Ledger prefers for cloud instance access (Chapter 78); with SSH access
treated as high-privilege (host + network-pivot capability) granted minimally and logged.** This completes
Part 1's networking foundation applied to the security-critical problem of remote access.

---

## 8. Hands-On Demonstration

### LAB 30.1 — SSH: Keys, Hardening, Tunnels, and Key Hygiene

**Objective.** Set up public-key authentication (Chapter 26 applied), harden the SSH server (defeat
brute-force), observe host-key verification (TOFU), demonstrate a tunnel (double-edged), and audit key
hygiene — with the modern SSM direction noted.

**Cost.** Free. **Environment.** ENV-1 + ENV-2 (a container as an SSH server). **Time.** 60 minutes.

**Steps.**

*Step 1 — Generate a key pair and set up public-key auth.*

```bash
ssh-keygen -t ed25519 -f ~/lab30_key -N "labpass" -C "lab"   # Ed25519 key with a passphrase (Ch26)
chmod 600 ~/lab30_key
# Start an SSH server container:
docker run -d --name sshlab -p 2222:22 rastasheep/ubuntu-sshd:18.04 2>/dev/null || \
  docker run -d --name sshlab -p 2222:22 linuxserver/openssh-server 2>/dev/null
sleep 3
# (Configure the container to accept your public key — varies by image; conceptually:)
docker exec sshlab bash -c 'mkdir -p /root/.ssh' 2>/dev/null
docker cp ~/lab30_key.pub sshlab:/tmp/key.pub 2>/dev/null
docker exec sshlab bash -c 'cat /tmp/key.pub >> /root/.ssh/authorized_keys' 2>/dev/null
```

*Step 2 — Observe host-key verification (TOFU — §4.2).*

```bash
ssh -i ~/lab30_key -p 2222 root@localhost "echo connected"   # first connect: host-key fingerprint prompt (TOFU)
# The host key is now pinned in ~/.ssh/known_hosts. Inspect it:
ssh-keygen -F '[localhost]:2222' 2>/dev/null || grep '2222' ~/.ssh/known_hosts
```

Observe the first-connect fingerprint prompt (TOFU — §4.2, Chapter 15 §5) and the pinning in known_hosts. A
changed host key would warn (possible MITM).

*Step 3 — Harden the SSH server (defeat brute-force — §4.3).*

```bash
docker exec sshlab bash -c '
  sed -i "s/^#*PasswordAuthentication.*/PasswordAuthentication no/" /etc/ssh/sshd_config   # KEY: disable passwords
  sed -i "s/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/" /etc/ssh/sshd_config
  grep -E "PasswordAuthentication|PermitRootLogin" /etc/ssh/sshd_config' 2>/dev/null
# PasswordAuthentication no defeats brute-forcing outright (§4.3) — the single most impactful setting.
```

*Step 4 — Demonstrate a tunnel (double-edged — §4.5).*

```bash
# Local forward: tunnel a local port to a destination through the SSH server (§4.5):
# (Conceptually) ssh -L 8888:some-internal-host:80 -p 2222 root@localhost
echo "ssh -L localport:dest:destport bastion  -> reach an internal service through the SSH server (tunnel)."
echo "Double-edged: legit secure access, AND an attacker's pivot/exfiltration channel (Chapters 13,17,23)."
# Restrict tunneling where not needed: AllowTcpForwarding no
```

*Step 5 — Audit key hygiene (§4.4) and note the modern direction.*

```bash
docker exec sshlab bash -c 'ssh-keygen -lf /root/.ssh/authorized_keys 2>/dev/null'   # who has access (audit)
echo "Key hygiene: one key per person, rotate, remove stale keys, protect private keys, audit authorized_keys."
echo "MODERN DIRECTION (Chapter 78): SSM Session Manager (no open port, no keys, IAM-auth, logged) or"
echo "  short-lived SSH certificates (CA-signed, auto-expiring) — eliminates exposed-port + key problems."
```

**Security implications.** Write down: (a) SSH = applied cryptography (key exchange + AEAD + public-key auth —
Chapters 25–28); (b) public-key-only auth (disable passwords) defeats brute-force (§4.3, Chapter 10); (c)
host-key verification is TOFU-with-pinning (§4.2, verify out-of-band, never ignore changes); (d) key hygiene
is the core operational practice (short-lived > long-lived — §4.4); (e) tunnels are double-edged (access AND
pivot/exfil — §4.5); (f) the modern direction eliminates open ports and long-lived keys (SSM/certificates —
§4.6).

**Cleanup.**
```bash
docker rm -f sshlab 2>/dev/null; rm -f ~/lab30_key ~/lab30_key.pub
ssh-keygen -R '[localhost]:2222' 2>/dev/null
```

---

## 9. Security Implications

- **SSH is applied cryptography for remote access** — its three layers (transport = key exchange + symmetric
  AEAD with forward secrecy; authentication = public-key preferred; connection = multiplexed channels) mirror
  TLS (Chapters 25–28). The cryptography is sound; SSH's failures are **operational** (exposed ports, weak
  auth, key hygiene).
- **SSH is a top attack target** — exposed port 22 (`0.0.0.0/0` — Chapter 10) is relentlessly brute-forced.
  **Public-key-only authentication (disable passwords) defeats brute-force outright** — the single most
  impactful hardening; plus no root login, restrict the source (bastion/VPN/source-IP), and ideally
  **eliminate the open port** (SSM — §4.6).
- **Host-key verification is SSH's trust bootstrapping** — **TOFU with pinning** (Chapter 15 §5): trust on
  first connect (verify the fingerprint out-of-band for sensitive servers), pinned in known_hosts, changes
  detected (never ignore a changed-host-key warning — possible MITM). SSH certificates (CA-signed host keys)
  improve this.
- **Key hygiene is the core operational practice** — SSH keys are **long-lived credentials that accumulate**
  (`authorized_keys` sprawl), proliferate, and are rarely rotated; shared keys destroy accountability.
  Practices: one key per person, rotate, remove stale keys, protect private keys, audit `authorized_keys`
  fleet-wide. The stronger answer is **short-lived SSH certificates** (short-lived > long-lived — Chapters 1,
  68).
- **SSH tunnels are double-edged** — legitimate secure access AND an exfiltration/pivoting channel (like DNS/
  ICMP tunneling — Chapters 17, 23); SSH access is a **network-pivot** (blast-radius consideration). Restrict
  forwarding where not needed; monitor SSH.
- **The modern cloud direction eliminates SSH's structural weaknesses** — **SSM Session Manager** (no open
  port, no keys, IAM-auth, logged — the recommended cloud approach, Chapter 78) or short-lived SSH
  certificates (CA-signed, auto-expiring). Prefer these over traditional key-based SSH with an open port.

---

## 10. Attack Scenarios

1. **SSH brute-force** (§4.3, Chapter 10): exposed port 22 with password auth relentlessly brute-forced/
   credential-stuffed. Defense: public-key-only (disable passwords), restrict source, SSM (no port).
2. **Stolen/leaked private key** (Chapter 26): a leaked SSH private key grants access. Defense: passphrase +
   file permissions + hardware/agent; short-lived certificates; rotate.
3. **Key sprawl / stale keys** (§4.4): `authorized_keys` accumulating departed-employee/shared keys → orphaned
   access. Defense: audit, remove stale keys, one-key-per-person, certificates.
4. **SSH tunneling for pivoting/exfiltration** (§4.5, Chapters 13, 17, 23): an attacker with SSH access
   tunnels into internal networks and exfiltrates over the encrypted connection. Defense: restrict forwarding,
   monitor, treat SSH access as network-pivot.
5. **Host-key MITM** (§4.2): a changed/spoofed host key (ignored warning) → MITM. Defense: verify fingerprints
   out-of-band, never ignore warnings, SSH host certificates.
6. **Reverse-tunnel backdoor** (§4.5): a reverse tunnel (-R) creating persistent access. Defense: restrict/
   monitor forwarding.
7. **Weak configuration** — password auth enabled, root login allowed, weak key types, no source restriction.
   Defense: harden sshd_config (§6.2).

---

## 11. Defensive Techniques

- **Disable password authentication; use public keys only** (`PasswordAuthentication no`) — defeats
  brute-force outright (§4.3, Chapter 10); the single most impactful SSH hardening.
- **Eliminate the open SSH port where possible — prefer SSM Session Manager** (no open port, no keys,
  IAM-auth, logged — §4.6, Chapter 78) for cloud instance access; if SSH is needed, restrict the source
  (bastion, VPN, source-IP — never `0.0.0.0/0`, Chapter 10).
- **Harden sshd_config** (§6.2): `PasswordAuthentication no`, `PermitRootLogin no` (use sudo), `AllowTcpForwarding
  no` where tunnels aren't needed (§4.5), restrict users (`AllowUsers`/`AllowGroups`).
- **Practice key hygiene** (§4.4): one key per person (accountability), rotate keys, remove stale keys from
  `authorized_keys`, protect private keys (passphrase + permissions 600 + agent/hardware), and **audit
  `authorized_keys` fleet-wide**.
- **Prefer short-lived SSH certificates** (CA-signed, auto-expiring — §4.6) over long-lived keys — the SSH
  instance of short-lived > long-lived credentials (Chapters 1, 68); also fixes host-key TOFU (CA-signed host
  keys).
- **Verify host keys out-of-band on first connect** for sensitive servers (§4.2), and **never ignore a
  changed-host-key warning** (possible MITM).
- **Restrict and monitor SSH tunneling** (§4.5) — treat SSH access as network-pivot capability; disable
  forwarding where not needed; monitor SSH connections and logins (Chapter 36) for brute-force and pivoting.
- **Use modern key types** (Ed25519 — Chapter 26) and current SSH versions; disable weak ciphers/algorithms.

---

## 12. Production Architecture

SSH/remote access, VPS vs cloud, toward the modern direction:

```
 NEED                     APPROACH                          SYSTEM A (VPS)        SYSTEM B/C (AWS)
 ---------------------    ------------------------------    -------------------   -------------------------
 remote shell access      minimize exposure                 SSH (hardened)        SSM Session Manager (preferred)
 authentication           public-key only (no passwords)    keys / certificates   IAM (SSM) / short-lived certs
 exposed port             restrict source / eliminate       bastion + source-IP   NO open port (SSM connects out)
 key management           hygiene (audit/rotate)            manual (risky)        IAM (no keys) / SSH CA (short-lived)
 access logging           auth logs (Chapter 36)            /var/log/auth.log     CloudTrail/S3 (every session)
 tunnels/pivoting         restrict forwarding                AllowTcpForwarding no  SSM (controlled) / restrict
 host-key trust           TOFU + verify / host certs        known_hosts / CA      SSH host certs / SSM
```

The architectural principle: **SSH is applied cryptography for remote access whose security rests on
operational practices — public-key-only authentication (defeating the top attack, port-22 brute-force),
minimized exposure (restrict source, or eliminate the open port), and key hygiene (short-lived > long-lived) —
with the modern cloud direction (SSM Session Manager: no open port, no keys, IAM-authenticated, logged; or
short-lived SSH certificates) eliminating SSH's structural weaknesses (exposed ports, long-lived keys).** For
a cloud security engineer, **prefer SSM Session Manager** for instance access (no port 22 exposure, IAM-
controlled, fully logged, no key management) — it addresses the exposed-service problem (Chapters 3, 10) and
the key-hygiene problem (§4.4) at once, and aligns with the book's themes of short-lived credentials (Chapters
1, 68), identity-based access (Chapter 6), PKI over raw keys (Chapters 26, 27), and no-open-ports. Where SSH
is required, harden it (public-key-only, restrict source, key hygiene, short-lived certificates). SSH
completes Part 1 as the practical application of its networking-and-cryptography foundation to remote access.

---

## 13. Common Mistakes

1. **Exposed port 22 with password auth** (`0.0.0.0/0` — Chapter 10) — relentlessly brute-forced; disable
   passwords, restrict source, prefer SSM.
2. **Password authentication enabled** — brute-forceable; use public keys only (§4.3).
3. **Key sprawl / stale keys** in `authorized_keys` (departed employees, shared keys) — audit/rotate (§4.4).
4. **Unprotected private keys** (no passphrase, wrong permissions, on shared machines) — theft risk (Chapter
   26).
5. **Ignoring changed-host-key warnings** — possible MITM (§4.2).
6. **Unrestricted SSH tunneling** — pivoting/exfiltration (§4.5).
7. **Direct root login** — use sudo (Chapters 2, 33).
8. **Long-lived keys instead of short-lived certificates / SSM** — the structural weakness the modern
   direction fixes (§4.6).
9. **Not logging SSH access** — losing the audit trail (Chapter 36); SSM logs every session.
10. **Security-by-obscurity (non-standard port) as the control** — minor obscurity, not a real control;
    disable passwords and restrict source instead.

---

## 14. Troubleshooting

| Symptom / concern | Issue | Fix |
|---|---|---|
| SSH brute-force in logs | exposed port 22 + passwords | disable passwords (public-key only); restrict source; SSM (§4.3, §4.6) |
| "Permission denied (publickey)" | key not in authorized_keys / wrong permissions | check authorized_keys, key permissions (600), correct key (§6.1) |
| "REMOTE HOST IDENTIFICATION HAS CHANGED" | host key changed (reinstall or MITM) | verify out-of-band WHY it changed; don't blindly clear (§4.2) |
| Orphaned access (departed employee) | stale key in authorized_keys | audit and remove stale keys (§4.4) |
| SSH used to pivot/exfiltrate | tunneling abused | restrict AllowTcpForwarding; monitor; treat SSH as network-pivot (§4.5) |
| Managing many SSH keys is unwieldy | long-lived key sprawl | short-lived certificates / SSM (§4.6) |
| Need auditable instance access | traditional SSH not logged centrally | SSM Session Manager (logs every session — §4.6, Chapter 78) |
| Private key exposure | unprotected key | passphrase + permissions + hardware/agent; rotate (Chapter 26) |

---

## 15. Practical Lab

Lab 30.1 is in §8. Register it in the lab index. Extension: set up short-lived SSH certificates with a small
SSH CA (or explore Teleport/Vault SSH in a lab) — a user gets a short-lived certificate to SSH, the server
trusts the CA (not individual keys), and the certificate auto-expires — demonstrating the modern alternative to
long-lived keys (§4.6, the SSH instance of short-lived credentials — Chapters 1, 68). Then compare with SSM
Session Manager (if you have AWS) — no port, no keys, IAM-auth, logged (Chapter 78) — the recommended cloud
approach. This shows the modern direction that eliminates SSH's structural weaknesses.

---

## 16. Exercises

### Concept questions

**30.1** Explain SSH's three layers and how they mirror TLS (Chapters 25–28). Why is SSH's cryptography sound
but its security operational?

**30.2** Explain why public-key authentication is preferred over passwords, and how disabling passwords
defeats brute-force.

**30.3** Explain SSH host-key verification as TOFU-with-pinning (Chapter 15 §5), its weakness, and how SSH
certificates improve it.

**30.4** Explain the SSH key-hygiene problem and the practices (including short-lived certificates) that
address it.

**30.5** Explain why SSH tunnels are double-edged and why SSH access is a network-pivot (blast-radius
consideration).

### Debugging problems

**30.6** SSH logs show thousands of failed login attempts from many IPs. Explain and remediate.

**30.7** A "REMOTE HOST IDENTIFICATION HAS CHANGED" warning appears. Walk through what it means and your
response.

**30.8** A departed employee's access needs revoking, but they had SSH keys. Explain the problem and the fix
(and how certificates/SSM would have prevented it).

### Security scenarios

**30.9** Design secure remote access for a fleet of cloud instances, comparing traditional hardened SSH,
short-lived SSH certificates, and SSM Session Manager.

**30.10** Explain why SSH access should be treated as high-privilege (host + network-pivot), and how you'd
grant, restrict, and monitor it.

### Architecture questions

**30.11** Explain how the modern SSH direction (SSM, short-lived certificates) embodies the book's themes
(short-lived credentials, identity-based access, PKI over raw keys, no-open-ports — Chapters 1, 6, 10, 26, 27,
68).

**30.12** Design an SSH-certificate-based access system (bridge to Chapters 27, 67) for a distributed team.

### Hands-on exercises

**30.13** Set up public-key SSH authentication and disable password auth; verify brute-force is defeated.

**30.14** Audit `authorized_keys` across accounts and identify stale/shared keys.

**30.15** Demonstrate an SSH tunnel and explain its double-edged nature; then note the SSM alternative.

### Interview questions

**30.16** "How would you secure SSH access to your servers?"

**30.17** "Why is public-key authentication better than passwords for SSH?"

**30.18** "What's the problem with SSH key management, and how do you solve it?"

**30.19** "What is SSM Session Manager and why is it preferred over traditional SSH in the cloud?"

**30.20** "Why are SSH tunnels a security concern?"

---

## 17. Summary

- **SSH is applied cryptography for remote access** — its three layers (transport = key exchange + symmetric
  AEAD with forward secrecy; authentication = public-key preferred; connection = multiplexed channels) mirror
  TLS (Chapters 25–28), using the same primitives. The **cryptography is sound; SSH's security is
  operational** (exposed ports, weak auth, key hygiene) — the Chapter 25 §5 lesson (correct usage > algorithm)
  applied to a protocol.
- **SSH is a top attack target** — exposed port 22 (`0.0.0.0/0` — Chapter 10) is relentlessly brute-forced.
  **Public-key-only authentication (disable passwords) defeats brute-force outright** (the single most
  impactful hardening); plus no root login, restrict the source, and ideally **eliminate the open port** (SSM).
- **Host-key verification is TOFU-with-pinning** (Chapter 15 §5) — trust on first connect (verify out-of-band
  for sensitive servers), pinned in known_hosts, changes detected (never ignore a changed-host-key warning —
  possible MITM); SSH certificates (CA-signed host keys) improve it.
- **Key hygiene is the core operational practice** — SSH keys are long-lived credentials that accumulate
  (`authorized_keys` sprawl), proliferate, and rarely rotate; shared keys destroy accountability. Practices:
  one key per person, rotate, remove stale keys, protect private keys, audit fleet-wide — and prefer
  **short-lived SSH certificates** (short-lived > long-lived — Chapters 1, 68).
- **SSH tunnels are double-edged** — legitimate secure access AND an exfiltration/pivoting channel (like DNS/
  ICMP tunneling — Chapters 17, 23); SSH access is a **network-pivot** (blast-radius consideration) —
  restrict forwarding, monitor.
- **The modern cloud direction eliminates SSH's structural weaknesses** — **SSM Session Manager** (no open
  port, no keys, IAM-authenticated, logged — the recommended cloud approach, Chapter 78) or short-lived SSH
  certificates (CA-signed, auto-expiring). Prefer these. SSH completes Part 1 — the networking-and-cryptography
  foundation applied to remote access, embodying the book's themes (short-lived credentials, identity-based
  access, PKI over raw keys, no-open-ports).

---

## 18. Knowledge Check

1. What are SSH's three layers, and how do they mirror TLS? (§4.1, §5)
2. Why is public-key auth preferred, and how does disabling passwords defeat brute-force? (§4.3)
3. What is host-key verification, and its weakness? (§4.2)
4. What is the SSH key-hygiene problem, and the practices that address it? (§4.4)
5. Why are SSH tunnels double-edged? (§4.5)
6. What is SSM Session Manager, and why is it preferred? (§4.6)
7. Why is SSH's cryptography sound but its security operational? (§5)
8. Why is SSH access a network-pivot / blast-radius consideration? (§4.5, §5)
9. How do short-lived SSH certificates improve on long-lived keys? (§4.4, §4.6)
10. What is the single most impactful SSH hardening? (§4.3)

---

## 19. Further Exploration

- The SSH RFCs (4251–4254) — the three layers (transport, authentication, connection).
- `man sshd_config` and `man ssh_config` — the hardening options (§6.2); and Mozilla's OpenSSH guidelines.
- Teleport, HashiCorp Vault SSH, Netflix BLESS, smallstep — short-lived SSH certificate systems (§4.6).
- AWS SSM Session Manager documentation (Chapter 78) — the cloud-preferred no-port, no-key, IAM-auth, logged
  access.
- fail2ban / SSH brute-force mitigations — defense-in-depth for exposed SSH (though public-key-only + restrict
  source is the primary defense).
- This completes Part 1 (Networking, Chapters 7–30). Next: Part 2 — Linux Deep Dive (Chapter 31, Boot to
  Login) — the operating-system internals a security engineer needs, building on Part 0's foundations.

---

## Solutions

### 30.2
Public-key authentication is preferred over passwords for SSH because it eliminates the attacks that plague
password auth. With password authentication, the user sends a password to the server, which is: **brute-
forceable** (an exposed SSH server on port 22 is relentlessly attacked with password guesses/credential
stuffing — Chapter 10), **phishable/reusable** (passwords can be stolen and reused), and **a secret sent over
the connection** (to the server, which must handle it). With public-key authentication (Chapter 26 §4.3), the
user has a key pair; the *public* key is placed in the server's `authorized_keys`, and the *private* key stays
on the client. Authentication is a challenge-response: the server challenges the client to prove it holds the
private key, the client *signs* a challenge with the private key (Chapter 26 §4.3), and the server verifies
the signature with the public key — **no secret is ever sent to the server**, and the private key never leaves
the client. This is superior because: (1) a strong key (Ed25519/RSA 3072+) is infeasible to brute-force
(unlike a password), (2) nothing brute-forceable or phishable is transmitted, and (3) the server never handles
a password. **Disabling password authentication entirely (`PasswordAuthentication no`) defeats brute-force
outright** — because there is no password to guess, the relentless password-guessing attacks against exposed
SSH simply cannot succeed (they get "permission denied (publickey)" regardless of the password tried). This is
the single most impactful SSH hardening: with passwords disabled and public-key-only auth, the top SSH attack
(brute-force) is eliminated. (The stronger evolution is short-lived SSH certificates or SSM, which also remove
the long-lived-key management problem.)

### 30.16
Securing SSH access, in priority order: (1) **Eliminate the open port where possible — prefer SSM Session
Manager** (Chapter 78) for cloud instances: no inbound port 22 (the instance's SSM agent connects out, so
there's no brute-force target — Chapter 10), no SSH keys to manage (IAM authentication), and every session is
logged (CloudTrail/S3). This addresses SSH's two biggest weaknesses at once. (2) If SSH is needed, **disable
password authentication and use public keys only** (`PasswordAuthentication no`) — the single most impactful
hardening, defeating brute-force outright. (3) **Restrict the source** — never expose port 22 to `0.0.0.0/0`
(Chapter 10); allow SSH only from a bastion host, a VPN, or specific source IPs. (4) **Disable direct root
login** (`PermitRootLogin no` — use sudo, Chapters 2, 33). (5) **Practice key hygiene** — one key per person
(accountability), rotate keys, remove stale keys from `authorized_keys` (audit fleet-wide), and protect
private keys (passphrase + permissions 600 + agent/hardware); or better, use **short-lived SSH certificates**
(CA-signed, auto-expiring) to eliminate the key-management problem. (6) **Restrict tunneling** (`AllowTcpForwarding
no` where not needed) — SSH access is a network-pivot (§4.5). (7) **Log and monitor** SSH access (Chapter 36)
for brute-force and pivoting; SSM logs every session automatically. (8) Use modern key types (Ed25519) and
current SSH versions. The overarching approach: minimize exposure (SSM or restricted source), strong
authentication (public-key/certificates, no passwords), least-privilege access (treat SSH as high-privilege —
host + network-pivot), and logging — with SSM Session Manager as the preferred cloud solution that addresses
the exposed-port and key-management problems structurally.

### 30.19
AWS SSM (Systems Manager) Session Manager provides SSH-like interactive shell access to instances but
eliminates SSH's two biggest structural weaknesses: **no open SSH port** and **no SSH keys**. How it works:
the instance runs the SSM agent, which connects *outbound* to the SSM service (so there is no inbound port 22
to expose or brute-force — Chapter 10); access is authenticated by **IAM** (you need IAM permission to start a
session, and the instance needs an instance role allowing SSM), so there are no SSH keys to distribute,
rotate, or leak; and **every session is logged** (to CloudTrail/S3/CloudWatch), providing a complete audit
trail. It's preferred over traditional SSH in the cloud because it directly addresses SSH's core operational
problems: (1) **no exposed port 22** — eliminating the relentless brute-force attack surface (the top SSH
finding — Chapter 10) and removing the need for a bastion host or open inbound rules; (2) **no key
management** — eliminating the key-hygiene problem (sprawl, stale keys, leaked private keys, rotation — §4.4)
since access is IAM-based, not key-based; (3) **full logging/auditability** — every session is recorded
(unlike traditional SSH, which needs separate logging setup); (4) **IAM integration** — access is granted/
revoked via IAM (Chapter 6), so it's centrally controlled, auditable, and revocable (revoke the IAM
permission, and access is gone — no orphaned keys). It aligns with the book's themes: identity-based access
(IAM — Chapter 6), no-open-ports (Chapters 3, 10), no-long-lived-credentials (Chapters 1, 68), and
auditability (Chapter 82). For these reasons, SSM Session Manager is the recommended approach for cloud
instance access (Chapter 78); traditional SSH is reserved for cases where SSM isn't available, and then it's
hardened (public-key-only, restricted source, short-lived certificates). The trade-off is a dependency on the
SSM agent and IAM, and slightly different ergonomics, but the security benefits (no port, no keys, IAM-auth,
logged) are decisive.

---

*This completes Part 1 — Networking From First Principles (Chapters 7–30) — and, with Part 0 (Chapters 1–6),
the foundational half of the book: the machine, the kernel, sockets, the request map, production components,
the isolation ladder, and the full networking stack from bits to SSH, with cryptography, PKI, and TLS. Next:
Part 2 — Linux Deep Dive for Security Engineers, beginning with Chapter 31 (Boot to Login) — the
operating-system internals that host everything, building on Part 0's process/kernel foundations toward the
Capstone Project 1 (harden a Linux server) that follows Part 2.*
