# Chapter 28 — TLS Byte by Byte: 1.2 vs 1.3 Handshakes, Key Schedule, Cipher Suites, mTLS, SNI

---

## 1. Why This Matters

TLS is the protocol that secures nearly all internet traffic — every HTTPS request, every secure API call,
every database connection you protect, every service-to-service hop (Chapter 4 Stop 4). It is the synthesis
of the last three chapters: symmetric AEAD (Chapter 25), key exchange + signatures (Chapter 26), and PKI/
certificates (Chapter 27) combined into one protocol that authenticates the server and establishes a
forward-secret encrypted channel. You have referenced TLS as "the backstop" against every on-path attacker
(ARP, DNS, routing, DHCP MITM — Chapters 9, 12, 15, 17); this chapter shows how it actually works.

For a cloud security engineer, TLS matters because:

1. **TLS is the load-bearing confidentiality/integrity control** — it is what makes an untrusted network
   survivable (Chapters 9, 43, Zero Trust). Understanding its handshake, guarantees, and limits is essential.
2. **TLS configuration is a security responsibility** — version (1.2 vs 1.3), cipher suites, forward secrecy,
   certificate validation (Chapter 27) — and misconfiguration (weak versions/ciphers, no forward secrecy,
   broken validation) is a common finding.
3. **Where TLS terminates is an architectural decision** (Chapter 4 §Stop 4) — the "TLS protects transit, not
   endpoints" principle, and the WAF-after-termination requirement (Chapters 4, 22).
4. **mTLS is the foundation of service-to-service auth and Zero Trust** (Chapters 64, 67, 86, 87) — mutual
   certificate authentication for workloads.

The core idea: **TLS combines PKI/certificates (server authentication — Chapter 27), asymmetric key exchange
(establishing a shared symmetric key with forward secrecy — Chapter 26), and symmetric AEAD (encrypting the
data — Chapter 25) into a handshake-then-transfer protocol. The handshake authenticates the server (via its
certificate) and agrees on a forward-secret symmetric key over the insecure channel; then fast symmetric AEAD
protects all the application data. TLS 1.3 streamlined and hardened this (fewer round-trips, forward secrecy
required, weak options removed). TLS is the load-bearing control against on-path attackers — protecting
transit between endpoints, with configuration (version, ciphers, forward secrecy, validation) and termination
point being the security decisions.** This chapter assembles Chapters 25–27 into the secure channel
everything depends on.

---

## 2. Prerequisites

- **Chapters 25 (symmetric AEAD), 26 (key exchange, signatures, forward secrecy), 27 (PKI, certificates,
  validation)** — TLS is their synthesis; this chapter assumes all three.
- Chapter 19 (TCP — TLS runs over TCP), Chapter 24 (packet analysis — you captured TLS handshakes), Chapter 4
  §Stop 4 (TLS on the request map), and the "TLS as backstop" references throughout Part 1.
- Chapter 18 §4.6 (QUIC — TLS 1.3 is built into QUIC/HTTP3).

---

## 3. Mental Model

**TLS is a handshake-then-transfer protocol that combines the three cryptographic building blocks: the
handshake uses PKI (Chapter 27) to authenticate the server and asymmetric key exchange (Chapter 26) to agree
on a shared symmetric key with forward secrecy, over the insecure TCP connection; then all application data is
protected with fast symmetric AEAD (Chapter 25). It is the load-bearing control that makes an untrusted
network survivable.**

```
   TLS = PKI (authenticate) + key exchange (establish key, forward secrecy) + symmetric AEAD (transfer data)

   THE HANDSHAKE (over the established TCP connection — Chapter 19):
     1. Client Hello: "I support these TLS versions, cipher suites; here's my key-exchange share (ECDHE);
                       SNI = the server name I want" (Chapter 26 key exchange; SNI — §4.5)
     2. Server Hello + Certificate: "chosen version/cipher; my key-exchange share; here's my CERTIFICATE
                       (Chapter 27) proving I'm this domain" + a signature over the handshake
     3. Client: VALIDATES the certificate (Chapter 27 — chain/identity/validity/revocation), then both
                derive the SAME shared symmetric key from the ECDHE shares (Chapter 26 — forward secrecy)
     4. Both switch to SYMMETRIC AEAD (Chapter 25) for all application data.

   THE RESULT: an authenticated (you're talking to the real server), confidential + integrity-protected
     (AEAD), forward-secret channel over an untrusted network. THE backstop against on-path attackers.
```

Three ideas:

1. **TLS is the synthesis of Chapters 25–27.** PKI authenticates (the certificate proves the server's
   identity — Chapter 27), key exchange establishes the shared symmetric key with forward secrecy (ECDHE —
   Chapter 26), and symmetric AEAD encrypts the data (Chapter 25). Each chapter's building block plays its
   role: authenticate, establish, transfer.
2. **The handshake authenticates and establishes; then symmetric AEAD transfers.** The (slow, asymmetric)
   handshake happens once per connection to authenticate the server and agree on a key; then all the data uses
   fast symmetric AEAD — the asymmetric-establishes/symmetric-transfers partnership (Chapter 26 §5) realized.
3. **TLS is the load-bearing control against on-path attackers.** Because the server is authenticated (via its
   certificate — an attacker can't produce a valid cert for the real name) and the channel is confidential +
   integrity-protected + forward-secret, an on-path attacker (ARP/DNS/routing/DHCP MITM — Chapters 9, 12, 15,
   17) sees only ciphertext and cannot impersonate the server. This is why TLS is "the backstop" — it makes
   the untrusted network survivable (Zero Trust — Chapter 43).

**The security framing:** TLS is where all the cryptography converges into the practical secure channel. Its
security depends on: the certificate validation (Chapter 27 — authentication; disabling it breaks everything),
forward secrecy (Chapter 26 — ECDHE, protecting the past), modern version/ciphers (1.3 or 1.2 with strong
AEAD ciphersuites — no weak/deprecated options), and correct termination (TLS protects transit between
endpoints — where it terminates is architectural). TLS 1.3 hardened the protocol (removed weak options,
required forward secrecy, reduced round-trips). It is the load-bearing control, so its configuration is a core
security responsibility.

---

## 4. Fundamentals

### 4.1 The TLS 1.3 handshake (the modern default)

TLS 1.3 (the current standard) streamlined the handshake to one round-trip (1-RTT) and hardened it. The flow:

```
   (over an established TCP connection — Chapter 19)
   CLIENT --> ClientHello:
       - supported TLS versions (1.3), cipher suites (AEAD only — §4.3)
       - the client's ECDHE key share (Chapter 26 — the client already sends its key-exchange share!)
       - SNI (server name — which site; §4.5), and other extensions
   SERVER --> ServerHello + {EncryptedExtensions, Certificate, CertificateVerify, Finished}:
       - chosen version/cipher; the server's ECDHE key share
       - the server's CERTIFICATE (Chapter 27) + CertificateVerify (a signature over the handshake, Chapter 26)
         proving the server holds the private key for the certified public key
       - (from Certificate onward, already ENCRYPTED using keys derived from the ECDHE shares)
   CLIENT: validates the certificate (Chapter 27), verifies the signature, --> Finished
   -> Both derive the shared symmetric keys (from ECDHE — forward secrecy) and exchange application data (AEAD).
```

Key TLS 1.3 improvements (why it's the modern default):

- **Faster (1-RTT):** the client sends its key share in the ClientHello, so the key exchange completes in one
  round-trip (vs 2-RTT in TLS 1.2). **0-RTT resumption** is possible for repeat connections (with a replay
  caveat — §4.6).
- **Forward secrecy REQUIRED** (Chapter 26 §4.5) — only ECDHE key exchange; RSA key transport (no forward
  secrecy) is removed. Every TLS 1.3 connection has forward secrecy.
- **AEAD only** (Chapter 25 §4.3) — only authenticated-encryption ciphers (AES-GCM, ChaCha20-Poly1305); the
  broken/weak options (RC4, CBC-mode issues, non-AEAD) are removed.
- **Most of the handshake is encrypted** — including the certificate (in TLS 1.2 the certificate was sent in
  the clear); this improves privacy (less metadata visible — Chapter 24 §4.5), though SNI is still visible
  (unless Encrypted Client Hello — §4.5).
- **Simplified, hardened** — many legacy/weak features removed, reducing misconfiguration and attack surface.

The takeaway: **prefer TLS 1.3** — it is faster, has forward secrecy required, AEAD only, and fewer weak
options, making it both more secure and harder to misconfigure. TLS 1.2 (with strong configuration) is
acceptable; older versions (1.0/1.1, SSL) are deprecated and must be disabled (§4.4).

### 4.2 TLS 1.2 vs 1.3 (and what to disable)

TLS 1.2 is still widely deployed and, *configured well*, is acceptable — but it has weaknesses TLS 1.3 fixed:

```
   TLS 1.2: 2-RTT handshake; forward secrecy OPTIONAL (must choose ECDHE ciphersuites); allows non-AEAD
     ciphers (CBC-mode with known issues, and historically RC4); certificate sent in the clear; more
     configuration options -> more ways to misconfigure (weak ciphers, no forward secrecy, RSA key transport).
   TLS 1.3: 1-RTT; forward secrecy REQUIRED (ECDHE only); AEAD only; certificate encrypted; simplified/hardened.

   MUST DISABLE (deprecated/broken):
     - SSL 2.0, SSL 3.0 (POODLE), TLS 1.0, TLS 1.1 (deprecated, weak) -> disable all
     - Weak ciphers: RC4, DES/3DES, export ciphers, non-forward-secret (RSA key transport), CBC-mode issues
     - Weak parameters: small DH groups, weak curves
```

The configuration decisions (a core security responsibility): **enable TLS 1.3 (and 1.2 for compatibility),
disable TLS 1.0/1.1 and SSL entirely, use only strong AEAD cipher suites with forward secrecy (ECDHE), and
disable weak ciphers/parameters.** Tools like Mozilla's SSL Configuration Generator and SSL Labs (§6.3)
provide vetted configurations and grade your TLS. Weak version/cipher configuration is a common finding
(enabling TLS 1.0, weak ciphers, no forward secrecy) that scanners and compliance flag.

### 4.3 Cipher suites (what gets negotiated)

A **cipher suite** specifies the algorithms TLS uses for a connection. In TLS 1.3 they're simplified:

```
   TLS 1.3 cipher suite (just the AEAD + hash, since key exchange/signature are separate):
     TLS_AES_256_GCM_SHA384          (AES-256-GCM AEAD, SHA-384 for the key schedule)
     TLS_CHACHA20_POLY1305_SHA256    (ChaCha20-Poly1305 AEAD)
   TLS 1.2 cipher suite (specifies everything):
     TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
     |    |     |       |            |
     |    ECDHE |       AES-256-GCM  SHA-384 (MAC/PRF)
     |    (key  RSA     (AEAD symmetric — Chapter 25)
     |    exchange, (signature/auth — Chapter 26)
     |    forward
     |    secrecy — Ch26)
     TLS = the protocol
```

Reading a TLS 1.2 cipher suite decomposes into the three chapters: **ECDHE** (key exchange, forward secrecy —
Chapter 26), **RSA/ECDSA** (the server's certificate signature type — Chapter 26/27), **AES-256-GCM** (the
symmetric AEAD — Chapter 25), **SHA-384** (the hash for the key schedule/MAC — Chapter 25). A *good* cipher
suite has ECDHE (forward secrecy) + an AEAD cipher (AES-GCM/ChaCha20-Poly1305); a *bad* one lacks forward
secrecy (RSA key transport) or uses a weak cipher (RC4, CBC-mode, DES). TLS 1.3 simplifies this by fixing key
exchange to ECDHE and requiring AEAD, so the cipher suite only names the AEAD+hash — removing the chance to
choose a weak combination. The security check: ensure only strong, forward-secret, AEAD cipher suites are
enabled (§6.3).

### 4.4 Certificate validation in TLS (Chapter 27 applied)

The TLS handshake is where certificate validation (Chapter 27 §4.3) happens — it is the authentication step:

```
   In the handshake (§4.1), the server sends its Certificate + CertificateVerify (a signature proving it
   holds the private key). The client VALIDATES (Chapter 27):
     1. Chain of signatures up to a trusted root (trust store)
     2. IDENTITY MATCH: the certificate's SANs include the SNI/domain being connected to (prevents MITM)
     3. Validity (not expired), 4. Revocation
     5. CertificateVerify signature: proves the server holds the private key (not just presenting a stolen cert)
   -> If validation passes, the server is authenticated -> the key exchange is authenticated -> TLS is secure.
   -> If validation is DISABLED (Chapter 27 §4.3) -> encryption without authentication -> MITM.
```

This is the critical link: **TLS's authentication IS certificate validation (Chapter 27).** The handshake's
security rests on the client validating the server's certificate — and the CertificateVerify signature
additionally proves the server *holds the private key* (so an attacker can't just replay a stolen certificate;
they'd need the private key to produce the signature). Disabling validation (Chapter 27 §4.3) breaks TLS's
entire authentication guarantee, leaving only encryption-to-an-unknown-party (MITM). Everything from Chapter
27 applies here — this is where it's used.

### 4.5 SNI, Encrypted Client Hello, and what's visible

**SNI (Server Name Indication)** is the extension where the client tells the server *which* domain it wants
(so a server hosting many domains presents the right certificate). Its security relevance:

```
   SNI is sent in the ClientHello, historically in the CLEAR (even in TLS 1.3, until ECH) -> a network
   observer sees WHICH SITE you're connecting to (the domain), even though the content is encrypted.
   -> SNI is the metadata that packet analysis can read despite encryption (Chapter 24 §4.5).
   ENCRYPTED CLIENT HELLO (ECH): the emerging fix — encrypts the ClientHello (including SNI), hiding the
   destination site from network observers. Not yet universal.
```

The consequences: (1) **SNI reveals the destination site to network observers** — so "we use HTTPS" hides the
*content* but not *which site* you visit (via SNI), a privacy limitation and a metadata source for analysis
(Chapter 24 §4.5) and for domain-based filtering. (2) **ECH is closing this gap** (encrypting SNI), improving
privacy but reducing SNI-based visibility (like DoH/QUIC — Chapters 17, 18 — the same privacy-vs-visibility
trade-off). For a cloud security engineer: SNI is currently a useful metadata source (which site, for
detection/filtering) and a privacy consideration (it leaks the destination), with ECH shifting the balance
toward privacy.

### 4.6 mTLS, session resumption, and other features

Several TLS features matter for security:

- **mTLS (mutual TLS):** normally only the *server* is authenticated (via its certificate); the *client* is
  not (client authentication happens at the application layer — passwords, tokens). **mTLS** adds *client*
  certificate authentication — the client also presents a certificate the server validates, so *both* parties
  are authenticated by certificates. This is the foundation of **service-to-service authentication** (Chapter
  64), **workload identity** (Chapter 67), and **Zero Trust networking** (Chapters 86, 87 — service mesh
  mTLS): each service proves its identity to the other via certificates (from an internal PKI — Chapter 27).
  mTLS is how you get mutual cryptographic authentication between workloads without shared secrets.
- **Session resumption (0-RTT):** TLS 1.3 allows resuming a prior session with 0-RTT (sending application
  data in the first message) for speed — but 0-RTT data is **replayable** (an attacker can resend it), so it
  must only be used for idempotent requests (a security caveat — don't put state-changing requests in 0-RTT).
- **TLS termination:** TLS protects transit between two endpoints; where it *terminates* (the edge/CDN, the
  load balancer, the application) is an architectural decision (Chapter 4 §Stop 4) — after termination, the
  data is plaintext, so a WAF must sit after termination to inspect it (Chapters 4, 22), and internal hops
  after termination need re-encryption (mTLS/TLS) if the network is untrusted (east-west encryption — Chapter
  86).

### 4.7 TLS as the load-bearing control (the Part 1 synthesis)

TLS is referenced throughout Part 1 as "the backstop" / "the load-bearing control" against on-path attackers.
This chapter shows why:

```
   Against every on-path attacker (Part 1):
     ARP spoofing (Ch9), DNS spoofing (Ch17), routing/BGP hijack (Ch12), rogue DHCP (Ch15) -> all give the
     attacker on-path position (they can read/redirect traffic).
   TLS defeats them for confidentiality/integrity/authentication:
     - The attacker sees only CIPHERTEXT (confidentiality — AEAD, Chapter 25) -> can't read the data.
     - The attacker can't TAMPER undetected (integrity — AEAD) -> can't modify the data.
     - The attacker can't IMPERSONATE the server (authentication — they can't produce a valid certificate
       for the real name, Chapter 27) -> the client refuses the connection.
   -> On-path position becomes nearly useless. TLS makes the untrusted network survivable (Zero Trust — Ch43).
   (What TLS does NOT stop: the attacker seeing metadata — endpoints, SNI, timing, volume — Chapter 24 §4.5;
    and DoS/connection reset. And TLS protects TRANSIT, not the ENDPOINTS or post-termination hops.)
```

This is the culmination of Part 1's recurring theme: **the network is untrusted (ARP/DNS/routing/DHCP are all
attackable — Chapters 8–17), so you don't trust it — you use TLS to authenticate the endpoints and encrypt the
transit, making on-path position useless.** TLS is the load-bearing control because it doesn't depend on the
network being trustworthy — it authenticates cryptographically (via PKI) and encrypts (via AEAD), so a fully
compromised network (an attacker on-path at every hop) still yields only ciphertext to an attacker who cannot
impersonate the endpoints. This is Zero Trust at the transport layer (Chapter 43), and it's why "encrypt
everything, even internal" (Chapters 5, 9) is the standing recommendation.

---

## 5. Deep Technical Explanation: TLS as the Convergence of All Cryptography

TLS is where the entire cryptographic edifice of Chapters 25–27 converges into the practical secure channel —
and understanding it as that convergence, and as the load-bearing control it is, is the synthesis of Part 1.

**TLS assembles the three building blocks into one protocol:**

- **PKI/certificates (Chapter 27) provide authentication** — the server presents a certificate binding its
  public key to its domain, the client validates it (chain to trusted root + identity match + validity +
  revocation), and the CertificateVerify signature proves the server holds the private key. This answers "who
  am I talking to?" — the question key exchange alone couldn't (Chapter 26 §4.2's MITM gap). Without this, TLS
  would be encryption to an unauthenticated party.
- **Asymmetric key exchange (Chapter 26) establishes the shared key with forward secrecy** — ECDHE lets client
  and server agree on a shared symmetric key over the insecure TCP connection, with fresh ephemeral keys per
  session giving forward secrecy (past sessions safe even if a key later leaks). This answers "how do we get a
  shared key over an insecure channel?" — solving Chapter 25's key distribution problem.
- **Symmetric AEAD (Chapter 25) protects the data** — once the shared key is established, all application data
  uses fast AEAD (AES-GCM/ChaCha20-Poly1305), providing confidentiality + integrity. This is the bulk work,
  done efficiently by symmetric crypto.

The handshake orchestrates these: authenticate (PKI) + establish key with forward secrecy (ECDHE) → then
transfer data (AEAD). It is the **asymmetric-establishes/symmetric-transfers partnership** (Chapter 26 §5) with
**PKI providing the authentication** — the complete secure-channel architecture. Reading a TLS connection's
details (§6) shows all three: the certificate (PKI), the "Server Temp Key: ECDH" (key exchange + forward
secrecy), and the cipher (AEAD).

**TLS 1.3's hardening is the "correct usage by default" principle (Chapter 25 §5) applied to a protocol:** TLS
1.2's flexibility (optional forward secrecy, non-AEAD ciphers, RSA key transport, many options) created many
ways to misconfigure it insecurely — the same "misuse, not broken algorithms" problem. TLS 1.3 removes the
insecure options: forward secrecy is *required* (ECDHE only), AEAD is *required* (no weak ciphers), the
handshake is simplified. So TLS 1.3 makes secure configuration the default and misconfiguration harder — the
protocol-level version of "use vetted constructions that make correct usage the default" (Chapter 25 §5). This
is why preferring TLS 1.3 is both more secure and more foolproof.

**TLS is the load-bearing control because it doesn't depend on network trust:** Part 1 demonstrated
exhaustively that the network is untrusted — ARP (Chapter 9), DNS (Chapter 17), routing/BGP (Chapter 12), and
DHCP (Chapter 15) are all attackable, giving an attacker on-path position. The recurring conclusion was "TLS
is the backstop." TLS earns this because its guarantees are *cryptographic*, not network-dependent: it
authenticates the endpoint via PKI (an on-path attacker can't produce a valid certificate for the real name —
they'd need the private key), encrypts via AEAD (an on-path attacker sees only ciphertext), and provides
integrity (tampering is detected) and forward secrecy (past sessions safe). So a *fully compromised network* —
an attacker on-path at every hop — still cannot read, tamper with, or impersonate a TLS-protected connection.
This is Zero Trust at the transport layer (Chapter 43): don't trust the network; authenticate and encrypt the
endpoints. It's why "encrypt everything, including internal traffic" (Chapters 5, 9) is the standing rule, and
why mTLS (mutual authentication) extends this to service-to-service (Chapters 64, 86, 87).

**TLS's limits define what else you need:** TLS protects *transit between two endpoints*, so (1) it doesn't
protect the *endpoints* (a compromised server sees plaintext — you need application/host security), (2)
*where it terminates* is architectural (after termination, data is plaintext — WAF sits after termination,
internal hops need re-encryption — Chapters 4, 22, 86), (3) it leaks *metadata* (endpoints, SNI, timing,
volume — Chapter 24 §4.5, ECH closing SNI), and (4) it doesn't stop *DoS*. Understanding these limits defines
the complementary controls (application security, termination architecture, metadata analysis, DoS defenses).

The unifying insight: **TLS is the convergence of all cryptography — PKI (authenticate), key exchange
(establish key, forward secrecy), and symmetric AEAD (transfer data) — into the practical secure channel that
is the load-bearing control against on-path attackers (making the untrusted network survivable, Zero Trust),
with TLS 1.3 hardening it (correct-usage-by-default), configuration (version/ciphers/forward secrecy/
validation) being a core security responsibility, and its limits (transit-only, termination-architectural,
metadata-leaking) defining the complementary controls.** It is where Part 1's cryptography chapters and the
"network is untrusted → use TLS" theme culminate, and it underpins HTTPS (Chapter 29), API security (Part 5),
mTLS/service mesh (Chapters 64, 86), and encryption everywhere in the book.

---

## 6. Internals: Inspecting and Configuring TLS

### 6.1 Watch a TLS handshake (the synthesis visible)

```bash
# Full handshake detail (see version, cipher, certificate, key exchange — the 3 building blocks):
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
    grep -E 'Protocol|Cipher|Server Temp Key|Verify return'
#   Protocol: TLSv1.3            -> the version (§4.1, §4.2)
#   Cipher: TLS_AES_256_GCM...   -> the AEAD symmetric cipher (Chapter 25)
#   Server Temp Key: X25519      -> ECDHE key exchange = FORWARD SECRECY (Chapter 26)
#   Verify return code: 0 (ok)   -> certificate validation passed (Chapter 27)
# All three building blocks (PKI/cert, ECDHE/forward secrecy, AEAD) visible in one command.

# The certificate (Chapter 27):
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
    openssl x509 -noout -subject -issuer -dates
```

This one command shows TLS as the synthesis: the certificate (PKI — Chapter 27), the ECDHE temp key (key
exchange + forward secrecy — Chapter 26), and the AEAD cipher (Chapter 25) — the three chapters converged.
`Verify return code: 0` confirms validation (Chapter 27) passed.

### 6.2 Capture a TLS handshake (Chapter 24)

```bash
# Capture the handshake and observe what's visible vs encrypted (Chapter 24 §4.5):
$ sudo tcpdump -n 'tcp port 443 and host example.com' -c 15
# In Wireshark: filter "tls.handshake" -> see ClientHello (versions, ciphers, SNI), ServerHello,
#   Certificate (TLS 1.2: in clear; TLS 1.3: encrypted). The application data is encrypted (§4.7, Ch24).
$ openssl s_client -connect example.com:443 -servername example.com  # interactive; see the full handshake
```

Capturing shows the handshake (ClientHello with SNI/versions/ciphers, ServerHello, Certificate) and that the
application data is encrypted — the Chapter 24 encryption limit (metadata visible, payload not), and SNI as
visible metadata (§4.5).

### 6.3 Grade and configure TLS (the security responsibility)

```bash
# Grade a server's TLS (version, ciphers, forward secrecy, cert) — SSL Labs (web) or testssl.sh (CLI):
$ testssl.sh example.com 2>/dev/null | grep -E 'TLS 1|cipher|forward secrecy|Rating'
#   Checks: TLS versions enabled (1.0/1.1 = finding), cipher strength, forward secrecy, cert validity, known
#   vulns (POODLE, Heartbleed, etc.). SSL Labs gives an A-F grade.

# Modern secure config (via Mozilla SSL Config Generator — vetted): enable TLS 1.3 (+1.2), disable 1.0/1.1/SSL,
#   only strong AEAD forward-secret cipher suites. Example nginx directives:
#     ssl_protocols TLSv1.3 TLSv1.2;
#     ssl_ciphers <Mozilla-generated strong AEAD ciphers>;
#     ssl_prefer_server_ciphers off;   # (TLS 1.3 client preference)
```

TLS grading (SSL Labs / testssl.sh) and vetted configuration (Mozilla SSL Config Generator) are the tools for
the configuration responsibility (§4.2): enable 1.3/1.2, disable 1.0/1.1/SSL, strong AEAD forward-secret
ciphers only. A low grade (weak versions/ciphers, no forward secrecy) is a common, scannable finding.

### 6.4 mTLS (mutual authentication)

```bash
# mTLS: the client also presents a certificate the server validates (§4.6):
$ openssl s_client -connect service.internal:443 -cert client.crt -key client.key -CAfile ca.crt
#   The client presents client.crt (its identity); the server validates it against ca.crt.
# In service mesh (Chapter 86), mTLS is automatic between sidecars (workload identity — Chapter 67).
```

mTLS adds client-certificate authentication — the foundation of service-to-service auth (Chapter 64) and Zero
Trust (Chapters 86, 87). The client proves its identity via a certificate (from an internal CA — Chapter 27),
so both parties are cryptographically authenticated.

---

## 7. Real-World Example: TLS in the Ledger System

**Where and how Ledger uses TLS:**

- **Public HTTPS (Chapters 4, 29):** all client traffic to `ledger.example` uses **TLS 1.3** (via CloudFront/
  ALB with ACM certificates — Chapter 27), with **forward secrecy** (ECDHE required), **AEAD ciphers**, and
  **certificate validation** — the synthesis of Chapters 25–27. This is the load-bearing control making the
  untrusted internet survivable (§4.7).
- **Configuration (§4.2):** Ledger enables TLS 1.3 (+ 1.2 for compatibility), **disables TLS 1.0/1.1 and
  SSL**, uses only strong forward-secret AEAD cipher suites (via Mozilla's config), and validates its config
  with SSL Labs/testssl.sh (aiming for an A grade) — the configuration responsibility.
- **TLS termination (§4.6, Chapter 4 §Stop 4):** TLS terminates at CloudFront/ALB, where the **WAF inspects
  the decrypted HTTP** (Chapters 4, 22, 85). After termination, internal hops (ALB→ECS, service→service) are
  re-encrypted where the network is untrusted (east-west — Chapter 86), or protected by the VPC + mTLS.
- **Internal mTLS (Chapters 64, 86, 87):** in System C (Kubernetes/mesh), Ledger uses **mTLS between
  services** (§4.6) — each service authenticates the other via short-lived certificates from an internal CA
  (cert-manager/mesh — Chapter 27), providing workload identity (Chapter 67) and Zero Trust networking.
- **App→DB/cache TLS (Chapter 5):** Ledger uses TLS for connections to RDS/ElastiCache (the internal hops
  that leave loopback — Chapters 5, 9), so an on-path attacker on the internal network gets only ciphertext.
- **Outbound TLS validation (Chapter 27):** Ledger's outbound calls (Stripe, APIs) use full certificate
  validation — never disabled (`verify=False` is a serious finding — Chapter 27 §4.3, Chapter 111).
- **TLS as the backstop (§4.7):** against every on-path attacker in Ledger's environment (ARP/DNS/routing/
  DHCP MITM — largely mitigated by the VPC SDN internally, but real for external and hybrid paths), TLS
  ensures the attacker sees only ciphertext and can't impersonate — the load-bearing control (Zero Trust —
  Chapter 43).

The TLS decisions Ledger makes: TLS 1.3 (+1.2), disable weak versions/ciphers, forward secrecy required,
validation never disabled, WAF after termination, re-encrypt internal hops (mTLS/TLS), and mTLS for
service-to-service. The failures Ledger avoids: weak versions/ciphers (scannable finding), no forward secrecy
(harvest-now-decrypt-later), disabled validation (MITM), plaintext internal hops (on-path exposure), and
unauthenticated service-to-service traffic.

The Ledger takeaway: **TLS is Ledger's load-bearing confidentiality/integrity/authentication control — the
synthesis of AEAD (25), key exchange + forward secrecy (26), and PKI/certificates (27) — configured securely
(1.3/1.2, disable weak, forward secrecy, never disable validation), terminated at a controlled point (WAF
after), re-encrypted on untrusted internal hops, and extended to mutual authentication (mTLS) for
service-to-service — making the untrusted network survivable (Zero Trust) across all of Ledger's paths.** This
is where Part 1's cryptography and "network is untrusted" theme culminate for Ledger.

---

## 8. Hands-On Demonstration

### LAB 28.1 — TLS: The Synthesis, Configuration, and mTLS

**Objective.** Observe TLS as the synthesis of Chapters 25–27 (certificate + ECDHE/forward secrecy + AEAD),
grade a server's TLS configuration, see the encryption limit and SNI, and set up mTLS (mutual authentication).

**Cost.** Free. **Environment.** ENV-1 (openssl, testssl.sh optional). **Time.** 60 minutes.

**Steps.**

*Step 1 — TLS as the synthesis (all three building blocks in one connection).*

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
  grep -E 'Protocol|Cipher|Server Temp Key|Verify return'
# Identify: Protocol (version — §4.1/4.2), Cipher (AEAD — Chapter 25), Server Temp Key (ECDHE/forward
#   secrecy — Chapter 26), Verify return 0 (certificate validation — Chapter 27). The 3 chapters converged.
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -issuer -dates   # the certificate (Chapter 27)
```

**Expected:** TLSv1.3, an AEAD cipher, an ECDH temp key (forward secrecy), verify code 0, and the
certificate — TLS as the synthesis of Chapters 25–27 in one connection (§5).

*Step 2 — Grade the TLS configuration (the security responsibility).*

```bash
# testssl.sh (if available) or SSL Labs (web: ssllabs.com/ssltest) — check versions, ciphers, forward secrecy:
testssl.sh --protocols --fs example.com 2>/dev/null | grep -E 'TLS 1|forward' || \
  echo "Use SSL Labs (ssllabs.com/ssltest) to grade; check: TLS 1.0/1.1 disabled, forward secrecy, strong ciphers"
# A good config: TLS 1.3 (+1.2), NO TLS 1.0/1.1/SSL, forward secrecy on all, strong AEAD ciphers -> grade A.
```

*Step 3 — The encryption limit and SNI (Chapter 24 §4.5).*

```bash
sudo tcpdump -n 'tcp port 443 and host example.com' -c 10 &
curl -s https://example.com > /dev/null; sleep 1
# The handshake (ClientHello with SNI, ServerHello) is visible; application data is encrypted.
# SNI reveals WHICH site (metadata) even though content is encrypted (§4.5, Chapter 24).
```

*Step 4 — Set up mTLS (mutual authentication).*

```bash
mkdir -p ~/lab28 && cd ~/lab28
# Create a CA and client+server certs (an internal PKI — Chapter 27):
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 1 \
  -keyout ca.key -out ca.crt -subj "/CN=Lab CA" 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout server.key -out server.csr -subj "/CN=localhost" 2>/dev/null
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 1 -out server.crt 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout client.key -out client.csr -subj "/CN=client" 2>/dev/null
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 1 -out client.crt 2>/dev/null
# Start an mTLS server (requires a client cert — §4.6):
openssl s_server -accept 8443 -cert server.crt -key server.key -CAfile ca.crt -Verify 1 -quiet &
sleep 1
# Connect WITH a client cert (mutual auth succeeds) vs WITHOUT (rejected):
echo "test" | openssl s_client -connect localhost:8443 -cert client.crt -key client.key -CAfile ca.crt 2>&1 | grep -i 'verify\|CONNECTED' | head
echo "test" | openssl s_client -connect localhost:8443 -CAfile ca.crt 2>&1 | grep -i 'error\|alert' | head  # no client cert -> rejected
kill %2 2>/dev/null
```

**Expected:** the connection *with* a client certificate succeeds (mutual authentication — both parties
authenticated by certificates); *without* a client cert, the server rejects it. This is mTLS (§4.6) — the
foundation of service-to-service auth (Chapter 64) and Zero Trust (Chapters 86, 87).

**Security implications.** Write down: (a) TLS = PKI (auth) + ECDHE (key exchange, forward secrecy) + AEAD
(data) — the synthesis of Chapters 25–27; (b) configuration is a responsibility (1.3/1.2, disable weak,
forward secrecy, strong AEAD); (c) SNI leaks which site (metadata — Chapter 24); (d) validation is TLS's
authentication (never disable — Chapter 27); (e) mTLS adds mutual auth (service-to-service, Zero Trust); (f)
TLS is the load-bearing control against on-path attackers (§4.7).

**Cleanup.**
```bash
cd ~ && rm -rf ~/lab28
```

---

## 9. Security Implications

- **TLS is the synthesis of Chapters 25–27** — **PKI/certificates authenticate the server** (Chapter 27),
  **asymmetric key exchange (ECDHE) establishes a forward-secret shared symmetric key** (Chapter 26), and
  **symmetric AEAD protects the data** (Chapter 25). The handshake authenticates + establishes; symmetric AEAD
  transfers — the asymmetric-establishes/symmetric-transfers partnership with PKI authentication.
- **TLS is the load-bearing control against on-path attackers** (ARP/DNS/routing/DHCP MITM — Chapters 9, 12,
  15, 17): the attacker sees only ciphertext (AEAD), can't tamper (integrity), and can't impersonate the
  server (can't produce a valid certificate — Chapter 27). It makes the untrusted network survivable — **Zero
  Trust at the transport layer** (Chapter 43), and the basis of "encrypt everything, including internal."
- **TLS 1.3 hardened the protocol** (correct-usage-by-default — Chapter 25 §5) — 1-RTT, **forward secrecy
  required** (ECDHE only), **AEAD only**, most of the handshake encrypted, weak options removed. **Prefer
  1.3** (+1.2 for compatibility); **disable TLS 1.0/1.1/SSL and weak ciphers** — a core configuration
  responsibility and common finding.
- **Certificate validation IS TLS's authentication** (Chapter 27) — disabling it (`verify=False`/`-k`) turns
  TLS into unauthenticated encryption = MITM.
- **SNI leaks which site** to network observers (metadata — Chapter 24 §4.5); **Encrypted Client Hello (ECH)**
  closes this (privacy-vs-visibility trade-off).
- **mTLS adds mutual (client) authentication** — the foundation of service-to-service auth (Chapter 64),
  workload identity (Chapter 67), and Zero Trust networking / service mesh (Chapters 86, 87).
- **TLS protects transit, not endpoints** (Chapter 4 §Stop 4) — where it terminates is architectural (WAF
  after termination — Chapters 4, 22; re-encrypt untrusted internal hops — Chapter 86); it leaks metadata; it
  doesn't stop DoS.

---

## 10. Attack Scenarios

1. **On-path MITM defeated by TLS** (§4.7): ARP/DNS/routing/DHCP MITM (Chapters 9, 12, 15, 17) — TLS defeats
   it (ciphertext, no tampering, can't impersonate). The attack that TLS is the backstop against.
2. **Disabled/broken certificate validation** (Chapter 27 §4.3, §4.4): `verify=False`/`-k` → MITM. The #1
   serious TLS bug.
3. **Weak version/cipher configuration** (§4.2): TLS 1.0/1.1, weak ciphers (RC4, DES), no forward secrecy —
   downgrade attacks, cracking, harvest-now-decrypt-later. Defense: 1.3/1.2, strong AEAD, forward secrecy.
4. **Downgrade attacks** (§4.2): forcing a weaker version/cipher (POODLE on SSL 3.0, etc.). Defense: disable
   weak versions; TLS 1.3's design resists downgrade.
5. **SSL stripping** (Chapter 9 §4.4): downgrading HTTPS to HTTP before TLS engages. Defense: HSTS (§Chapter
   4 §Stop 0) — the browser refuses HTTP.
6. **Historical TLS implementation bugs** (Heartbleed — Chapter 1, BEAST, POODLE): flaws in TLS
   implementations/versions. Defense: patch; use modern versions/libraries.
7. **0-RTT replay** (§4.6): replaying TLS 1.3 0-RTT data. Defense: only idempotent requests in 0-RTT.
8. **Plaintext post-termination / unencrypted internal hops** (§4.6): data plaintext after TLS terminates, or
   internal hops unencrypted → on-path exposure internally. Defense: re-encrypt (mTLS/TLS) untrusted hops.

---

## 11. Defensive Techniques

- **Use TLS 1.3 (+ 1.2 for compatibility); disable TLS 1.0/1.1 and SSL entirely** — and use only strong,
  forward-secret AEAD cipher suites (via Mozilla SSL Config Generator). Grade with SSL Labs/testssl.sh (aim
  for A); weak versions/ciphers are a common scannable finding.
- **Require forward secrecy (ECDHE)** (Chapter 26 §4.5) — automatic in TLS 1.3; explicitly configure in 1.2.
  Protects against harvest-now-decrypt-later.
- **Never disable certificate validation** (Chapter 27 §4.3) — validation IS TLS's authentication; `verify=
  False`/`-k`/`InsecureSkipVerify` = MITM. A serious finding (Chapter 111).
- **Use HSTS (preload)** — prevents SSL stripping (downgrade to HTTP before TLS engages — Chapters 4, 9).
- **Terminate TLS at a controlled point** and inspect after termination (WAF — Chapters 4, 22, 85);
  **re-encrypt untrusted internal hops** (east-west — Chapter 86) rather than assuming internal = safe.
- **Use mTLS for service-to-service authentication** (Chapters 64, 86, 87) — mutual certificate auth from an
  internal PKI (Chapter 27), the foundation of workload identity (Chapter 67) and Zero Trust networking.
- **Manage certificates properly** (Chapter 27) — automate (ACM/ACME), never expire, protect private keys,
  CAA + CT monitoring.
- **Patch TLS implementations** — historical bugs (Heartbleed, POODLE, BEAST) were implementation/version
  flaws; keep libraries and versions current (class-elimination — Chapter 1).
- **Encrypt everything, including internal traffic** — TLS is the load-bearing control that doesn't depend on
  network trust (§4.7); Zero Trust (Chapter 43). Use idempotent-only requests for 0-RTT.

---

## 12. Production Architecture

TLS in production — the synthesis, configuration, termination, and mTLS:

```
 ASPECT                   APPROACH                          SYSTEM A (VPS)        SYSTEM B/C (AWS)
 ---------------------    ------------------------------    -------------------   -------------------------
 version/ciphers          TLS 1.3 (+1.2), disable weak      nginx (Mozilla cfg)   ALB/CloudFront policies (managed)
 certificates (Ch27)      automated, valid, forward-secret  Let's Encrypt         ACM (managed, auto-renew)
 termination (Ch4 §Stop4) controlled point + WAF after      nginx + ModSecurity   CloudFront/ALB + AWS WAF (Ch85)
 internal hops            re-encrypt untrusted (east-west)  TLS app→DB (Ch5)      mTLS mesh (Ch86) / TLS to RDS
 service-to-service       mTLS (mutual auth)                (limited)             service mesh mTLS (Ch64,86,87)
 validation (Ch27)        never disable                     code review (Ch111)   code review + config
 HSTS                     enable (preload)                  nginx header          CloudFront/ALB header
 grading                  SSL Labs / testssl.sh             periodic scan         + config policies + scans
```

The architectural principle: **TLS is the load-bearing confidentiality/integrity/authentication control —
the synthesis of PKI (authenticate), key exchange (establish key, forward secrecy), and symmetric AEAD
(transfer) — configured securely (1.3/1.2, disable weak, forward secrecy, never disable validation),
terminated at a controlled point (WAF after), re-encrypted on untrusted internal hops, and extended to mutual
authentication (mTLS) for service-to-service (Zero Trust).** It makes the untrusted network survivable, which
is why "encrypt everything, including internal" is the standing rule (Chapters 5, 9, 43). In the cloud,
managed services (ACM certificates, ALB/CloudFront TLS policies, service mesh mTLS) handle much of the
configuration and certificate management correctly, so the security engineer's job is selecting secure
policies, never disabling validation, terminating with a WAF, re-encrypting internal hops, and using mTLS for
workload identity. TLS is where Part 1's cryptography (25–27) and "network is untrusted" theme (8–17)
culminate into the secure channel underpinning HTTPS (29), API security (Part 5), and everything encrypted.

---

## 13. Common Mistakes

1. **Disabling certificate validation** (`verify=False`/`-k`) — MITM (Chapter 27); the #1 serious TLS bug.
2. **Weak versions/ciphers** — TLS 1.0/1.1, RC4/DES, no forward secrecy (§4.2); a scannable finding.
3. **No forward secrecy** — RSA key transport / non-ECDHE (Chapter 26); harvest-now-decrypt-later.
4. **No HSTS** — SSL stripping possible (Chapters 4, 9).
5. **Assuming internal = safe** — unencrypted internal hops exposed to on-path attackers; re-encrypt (§4.6,
   Chapters 5, 9, 86).
6. **WAF before TLS termination** — can't inspect ciphertext (Chapters 4, 22); WAF must be after termination.
7. **Expired/mismanaged certificates** (Chapter 27) — outages; automate.
8. **State-changing requests in 0-RTT** — replayable (§4.6).
9. **Not using mTLS for service-to-service** where mutual authentication is needed (Chapters 64, 86, 87).
10. **Confusing "we use TLS" with security** — TLS protects transit, not endpoints; validation must be on,
    version/ciphers strong, and it doesn't hide metadata (SNI) or stop DoS.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Low SSL Labs grade | weak versions/ciphers, no forward secrecy | `testssl.sh`; enable 1.3/1.2, disable weak, ECDHE |
| Handshake failure | version/cipher mismatch, cert issue | `openssl s_client` (see version/cipher/verify); check config |
| "Certificate" errors | validation failure (Chapter 27) | `s_client` Verify return code; fix cert/chain (Ch27) |
| App works only with validation disabled | a cert/trust issue worked around dangerously | FIX the cert; never disable validation (Chapter 27 §4.3) |
| MITM despite TLS | validation disabled or rogue trusted CA | check for disabled validation; trust store (Ch27) |
| Internal traffic sniffable | unencrypted internal hop | re-encrypt (TLS/mTLS); don't assume internal safe (§4.6) |
| WAF not inspecting HTTPS | WAF before TLS termination | place WAF after termination (Chapters 4, 22, 85) |
| HTTP downgrade / SSL stripping | no HSTS | enable HSTS preload (Chapters 4, 9) |
| Which site visible despite HTTPS | SNI in the clear | expected (§4.5); ECH closes it (privacy) |

---

## 15. Practical Lab

Lab 28.1 is in §8. Register it in the lab index. Extension: capture and fully dissect a TLS 1.3 handshake in
Wireshark (Chapter 24), identifying the ClientHello (versions/ciphers/SNI/key share), ServerHello, the
encrypted certificate, and where application data begins (all encrypted) — seeing the synthesis of Chapters
25–27 on the wire. Then grade a server you control with SSL Labs, fix any findings (weak versions/ciphers, no
forward secrecy), and re-grade to an A. This proves TLS-configuration competence — a core responsibility.

---

## 16. Exercises

### Concept questions

**28.1** Explain how TLS combines the three cryptographic building blocks (Chapters 25–27) — what each
provides and its role in the handshake.

**28.2** Explain the TLS 1.3 handshake and how it improves on TLS 1.2 (round-trips, forward secrecy, ciphers,
encryption).

**28.3** Explain why TLS is "the load-bearing control against on-path attackers" — what it defeats and what it
doesn't.

**28.4** Explain what a cipher suite specifies (decompose one) and what makes it strong vs weak.

**28.5** Explain mTLS and why it's the foundation of service-to-service authentication and Zero Trust.

### Debugging problems

**28.6** A server gets a low SSL Labs grade. What do you check and fix?

**28.7** An outbound API call fails with a certificate error; a developer "fixes" it with `verify=False`.
Explain the danger and the correct fix.

**28.8** Internal service-to-service traffic is found to be sniffable. Diagnose and fix.

### Security scenarios

**28.9** Design the TLS strategy for a cloud application: version/ciphers, certificates, termination, internal
hops, and service-to-service — naming the control for each.

**28.10** Explain "TLS protects transit, not endpoints" and its architectural consequences (termination, WAF,
internal encryption).

### Architecture questions

**28.11** Explain how TLS synthesizes Chapters 25–27 and is the culmination of Part 1's "network is untrusted"
theme (bridge to Chapter 43, Zero Trust).

**28.12** Design service-to-service mTLS for a microservices platform (bridge to Chapters 64, 67, 86, 87).

### Hands-on exercises

**28.13** Inspect a TLS connection and identify all three building blocks (certificate, ECDHE/forward secrecy,
AEAD cipher).

**28.14** Grade a server's TLS and fix any weak-version/cipher/forward-secrecy findings.

**28.15** Set up mTLS with an internal CA and demonstrate mutual authentication (connection with/without a
client cert).

### Interview questions

**28.16** "Walk me through what happens in a TLS handshake."

**28.17** "How does TLS use both asymmetric and symmetric cryptography, and PKI?"

**28.18** "What's the difference between TLS 1.2 and 1.3, and what would you disable?"

**28.19** "What is mTLS and when do you use it?"

**28.20** "Why is TLS the backstop against on-path network attacks, and what are its limits?"

---

## 17. Summary

- **TLS is the synthesis of Chapters 25–27** — **PKI/certificates authenticate the server** (Chapter 27),
  **asymmetric key exchange (ECDHE) establishes a forward-secret shared symmetric key** (Chapter 26), and
  **symmetric AEAD protects the data** (Chapter 25). The handshake authenticates + establishes the key; then
  fast symmetric AEAD transfers the data — the asymmetric-establishes/symmetric-transfers partnership with PKI
  authentication.
- **TLS is the load-bearing control against on-path attackers** (ARP/DNS/routing/DHCP MITM — Chapters 9, 12,
  15, 17): the attacker sees only ciphertext (AEAD), can't tamper (integrity), can't impersonate the server
  (can't produce a valid certificate — Chapter 27). It makes the untrusted network survivable — **Zero Trust
  at the transport layer** (Chapter 43), the basis of "encrypt everything, including internal."
- **TLS 1.3 hardened the protocol** (correct-usage-by-default) — 1-RTT, **forward secrecy required** (ECDHE
  only), **AEAD only**, handshake mostly encrypted, weak options removed. **Prefer 1.3** (+1.2 for
  compatibility); **disable TLS 1.0/1.1/SSL and weak ciphers** — a core configuration responsibility and
  common finding (grade with SSL Labs/testssl.sh).
- **Certificate validation IS TLS's authentication** (Chapter 27) — disabling it (`verify=False`/`-k`) = MITM.
  A cipher suite decomposes into key exchange (ECDHE — forward secrecy) + signature (RSA/ECDSA) + AEAD cipher
  + hash; strong = ECDHE + AEAD.
- **SNI leaks which site** to observers (metadata — Chapter 24 §4.5); **ECH** closes it. **mTLS** adds mutual
  (client) authentication — the foundation of service-to-service auth (Chapter 64), workload identity (Chapter
  67), and Zero Trust networking / service mesh (Chapters 86, 87).
- **TLS protects transit, not endpoints** (Chapter 4 §Stop 4) — where it terminates is architectural (WAF
  after termination — Chapters 4, 22; re-encrypt untrusted internal hops — Chapter 86); it leaks metadata; it
  doesn't stop DoS. TLS is where Part 1's cryptography (25–27) and "network is untrusted" theme (8–17)
  culminate into the secure channel underpinning HTTPS (29), API security (Part 5), and encryption everywhere.

---

## 18. Knowledge Check

1. How does TLS combine the three building blocks (Chapters 25–27)? (§3, §5)
2. Describe the TLS 1.3 handshake and its improvements over 1.2. (§4.1, §4.2)
3. Why is TLS the load-bearing control against on-path attackers? (§4.7, §5)
4. Decompose a cipher suite; what makes it strong? (§4.3)
5. Why is certificate validation TLS's authentication, and what breaks if disabled? (§4.4, Chapter 27)
6. What does SNI leak, and what closes it? (§4.5)
7. What is mTLS and its use cases? (§4.6)
8. What should you disable in TLS configuration? (§4.2)
9. Why is forward secrecy required, and what does it protect? (§4.1, Chapter 26)
10. What does TLS protect, and what does it not (transit vs endpoints, metadata, DoS)? (§4.6, §5)

---

## 19. Further Exploration

- RFC 8446 (TLS 1.3) — the modern protocol; and RFC 5246 (TLS 1.2) for comparison.
- SSL Labs (ssllabs.com/ssltest) and testssl.sh — grade and analyze TLS configurations; Mozilla SSL Config
  Generator for vetted configs (§6.3).
- The Illustrated TLS 1.3 Connection (tls13.xargs.org) — a byte-by-byte walkthrough of a real handshake.
- Historical TLS attacks (Heartbleed, POODLE, BEAST, CRIME) — implementation/version flaws and why modern
  versions/patching matter.
- Encrypted Client Hello (ECH) — the SNI-encryption development (§4.5).
- Service mesh mTLS (Istio/Linkerd) and SPIFFE/SPIRE — mTLS/workload identity at scale (Chapters 64, 67, 86,
  87). Chapter 29 next (HTTP) — the application protocol TLS carries.

---

## Solutions

### 28.1
TLS combines the three cryptographic building blocks from Chapters 25–27, each playing a specific role in the
handshake: **(1) PKI/certificates (Chapter 27) provide authentication** — the server presents a certificate
binding its public key to its domain name, and the client validates it (chain to a trusted root + identity
match + validity + revocation) plus a CertificateVerify signature proving the server holds the private key;
this answers "who am I talking to?" and prevents MITM (an attacker can't produce a valid certificate for the
real domain). **(2) Asymmetric key exchange (Chapter 26) establishes the shared symmetric key with forward
secrecy** — client and server exchange ECDHE key shares in the handshake and each derives the same shared
secret over the insecure TCP connection, with fresh ephemeral keys per session giving forward secrecy (past
sessions safe if a key later leaks); this answers "how do we agree on a key over an insecure channel?" and
solves the key distribution problem. **(3) Symmetric AEAD (Chapter 25) protects the application data** — once
the shared key is derived, all data uses fast AEAD (AES-GCM/ChaCha20-Poly1305) providing confidentiality +
integrity; this is the efficient bulk work. The handshake orchestrates them: authenticate (PKI) + establish
key with forward secrecy (ECDHE) → then transfer data (AEAD) — the asymmetric-establishes/symmetric-transfers
partnership (Chapter 26 §5) with PKI authentication. So TLS is where all of Part 1's cryptography converges:
you can see all three in one connection (`openssl s_client`: the certificate = PKI, "Server Temp Key: ECDH" =
key exchange/forward secrecy, the cipher = AEAD).

### 28.16
The TLS handshake (over an established TCP connection — Chapter 19) authenticates the server and establishes a
forward-secret shared symmetric key, then switches to symmetric encryption for data. In TLS 1.3 (1-RTT):
(1) the **client sends a ClientHello** with its supported versions and cipher suites, its **ECDHE key share**
(Chapter 26 — the client sends its key-exchange share upfront), the **SNI** (which server name it wants), and
extensions. (2) The **server responds** with a ServerHello (chosen version/cipher, its ECDHE key share) and,
now encrypted (using keys derived from the ECDHE shares), its **Certificate** (Chapter 27 — proving its
identity), a **CertificateVerify** signature (Chapter 26 — proving it holds the certificate's private key,
not just replaying a stolen cert), and a Finished message. (3) The **client validates the certificate**
(Chapter 27 — chain to a trusted root, identity/SNI match, validity, revocation) and the signature, then
sends its Finished. (4) Both sides now have the **same shared symmetric key** (derived from the ECDHE shares
— forward secrecy, Chapter 26) and switch to **symmetric AEAD** (Chapter 25 — AES-GCM/ChaCha20-Poly1305) for
all application data. The result is an authenticated (you're talking to the real server), confidential +
integrity-protected, forward-secret channel over an untrusted network. Bonus: mention TLS 1.3's improvements
over 1.2 (1-RTT vs 2-RTT, forward secrecy required, AEAD only, certificate encrypted), that validation is
what makes it secure (disabling it = MITM), and that SNI is visible (metadata) unless ECH is used.

### 28.20
TLS is the backstop against on-path network attacks because its security guarantees are **cryptographic, not
network-dependent** — so even a fully compromised network (an attacker on-path at every hop via ARP spoofing,
DNS spoofing, routing/BGP hijack, or rogue DHCP — Chapters 9, 12, 15, 17) cannot defeat it. Specifically:
(1) **confidentiality** — the attacker sees only ciphertext (symmetric AEAD, Chapter 25), so they can't read
the data; (2) **integrity** — the attacker can't tamper with the data undetected (AEAD authentication); (3)
**authentication** — the attacker can't impersonate the server, because they can't produce a valid
certificate for the real domain (they'd need the server's private key — Chapter 27), so a validating client
refuses the connection to an impostor; and (4) **forward secrecy** (ECDHE — Chapter 26) protects past
sessions even if a key later leaks. So on-path position — which Part 1 showed is achievable through many
attackable network protocols — becomes nearly useless against TLS, making the untrusted network survivable
(Zero Trust at the transport layer — Chapter 43), which is why "encrypt everything, including internal" is the
standing rule. Its **limits**: TLS protects **transit between two endpoints**, not the endpoints themselves
(a compromised server/client sees plaintext — you need application/host security); **where it terminates is
architectural** (after termination the data is plaintext, so a WAF must sit after termination and untrusted
internal hops need re-encryption — Chapters 4, 22, 86); it **leaks metadata** (endpoints, SNI, timing, volume
— Chapter 24 §4.5, with ECH closing SNI); it **doesn't stop DoS** (an attacker can still flood or reset
connections); and it depends entirely on **validation being enabled** (disabling it = unauthenticated
encryption = MITM — Chapter 27) and on **strong configuration** (weak versions/ciphers/no-forward-secrecy
undermine it). So TLS defeats on-path attackers for confidentiality/integrity/authentication of transit, and
those limits define the complementary controls (endpoint security, termination architecture, metadata
analysis, DoS defenses, validation, strong config).

---

*This completes the cryptography and secure-channel arc. Next: Chapter 29 — HTTP/1.1, HTTP/2, HTTP/3:
Semantics, Framing, Multiplexing, and Security Differences. Having secured the channel with TLS, we examine
the application protocol it carries — the HTTP the web runs on, its versions and their framing/security
differences (including request smuggling and HTTP/3-over-QUIC), completing the request map's transport-and-
application layers (Chapter 4).*
