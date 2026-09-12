# Deep Dive 13 — TLS and Applied Cryptography

**Prerequisite:** [Chapter 13 §13.5](../13-networking.md) · [Chapter 17 §17.7](../17-security-architecture.md)

**What the map said:** *"TLS provides confidentiality, integrity and authentication. Use 1.3. The #1 mistake is not serving the intermediate certificate. Automate renewal and alert at 30/14/7 days."*

**What this deep dive does:** walks both handshakes message by message and explains exactly what TLS 1.3 removed and why, derives forward secrecy from the key-exchange mechanics, decodes cipher suite names, opens an X.509 certificate field by field and walks chain validation step by step, explains why "works in Chrome, fails in curl" is almost always one specific bug, covers session resumption and the 0-RTT replay problem, explains why OCSP is nearly useless and what replaced it, and ends with a diagnosis procedure and the performance numbers that drive capacity planning.

---

## Contents

```
1.  What TLS provides — and what it does not
2.  The TLS 1.2 handshake, message by message
3.  The TLS 1.3 handshake — and what was removed
4.  ⭐ Forward secrecy, derived
5.  Cipher suites, decoded
6.  AEAD: GCM and ChaCha20-Poly1305
7.  The TLS 1.3 key schedule
8.  X.509: the certificate, field by field
9.  ⭐ Chain validation, step by step
10. ⭐ The missing intermediate — "works in Chrome, fails in curl"
11. SNI, ALPN and Encrypted Client Hello
12. Session resumption: IDs, tickets and PSK
13. ⭐ Session ticket keys and the forward-secrecy trap
14. ⭐ 0-RTT and the replay problem
15. Revocation: CRL, OCSP, stapling — and why it mostly failed
16. ⭐ Short-lived certificates: the actual answer
17. Certificate Transparency
18. mTLS and workload identity
19. ⭐ The eight common failures and how to tell them apart
20. Diagnosis: the commands
21. ⭐ Performance: the numbers that drive capacity
22. Post-quantum: what is already shipping
23. Configuration
24. What an architect takes from this
```

---

## 1. What TLS provides — and what it does not

```
✅ CONFIDENTIALITY   an observer cannot read the plaintext
✅ INTEGRITY         tampering is detected (and with AEAD, cannot be
                     separated from decryption)
✅ AUTHENTICATION    ⭐ the SERVER proves it controls the private key
                     matching a certificate a trusted CA issued for
                     that hostname
```

```
❌ ⭐ IT DOES NOT PROVE THE SERVER IS TRUSTWORTHY.
   It proves the server is who its certificate says. A phishing site
   with a valid Let's Encrypt certificate is "secure" in TLS's sense.

❌ ⭐ IT DOES NOT HIDE METADATA.
   The destination IP, the packet sizes, the timing, and — in TLS 1.2
   and 1.3 without ECH — ⭐ THE HOSTNAME (SNI, §11) are all visible.

❌ ⭐ IT DOES NOT AUTHENTICATE THE CLIENT, unless you configure mTLS (§18).

❌ ⭐ IT PROTECTS DATA IN TRANSIT ONLY. Once terminated, the data is
   plaintext. A TLS-terminating load balancer means everything behind
   it is unencrypted unless you re-encrypt (Chapter 13 §13.5).
```

> **The most common architectural misunderstanding: "we have HTTPS, so we're secure."** TLS solves exactly three problems on one hop. Chapter 17's threat model exists because the other problems are still there.

---

## 2. The TLS 1.2 handshake, message by message

Two round trips before any application data. Worth knowing because TLS 1.2 is still widely deployed and because the differences illuminate what 1.3 fixed.

```
CLIENT                                              SERVER
  │                                                    │
  │──── ClientHello ──────────────────────────────────►│  ⭐ RTT 1
  │       client_random (32 B)
  │       cipher_suites[]          ⭐ everything the client supports
  │       extensions:
  │         ⭐ server_name (SNI)   — PLAINTEXT
  │         supported_groups       — curves for ECDHE
  │         signature_algorithms
  │         ⭐ alpn                — "h2", "http/1.1"
  │                                                    │
  │◄─── ServerHello ───────────────────────────────────│
  │       server_random (32 B)
  │       ⭐ chosen cipher_suite
  │◄─── Certificate ───────────────────────────────────│  ⭐ SENT IN PLAINTEXT
  │       the chain: leaf, intermediate(s)                  in TLS 1.2
  │◄─── ServerKeyExchange ─────────────────────────────│
  │       ⭐ server's EPHEMERAL ECDHE public key
  │       + a SIGNATURE over (client_random, server_random, key)
  │         ⭐ proving the server holds the certificate's private key
  │◄─── ServerHelloDone ───────────────────────────────│
  │                                                    │
  │──── ClientKeyExchange ────────────────────────────►│  ⭐ RTT 2
  │       client's ephemeral ECDHE public key
  │       ⭐ both sides can now compute the shared secret
  │──── ChangeCipherSpec ─────────────────────────────►│
  │──── Finished (ENCRYPTED) ─────────────────────────►│
  │       ⭐ a MAC over the entire handshake transcript
  │         — this is what prevents downgrade attacks
  │                                                    │
  │◄─── ChangeCipherSpec ──────────────────────────────│
  │◄─── Finished (ENCRYPTED) ──────────────────────────│
  │                                                    │
  │◄══════ APPLICATION DATA ══════════════════════════►│  ⭐ after 2 RTT
```

```
⭐ THE COST: 2 full round trips, ON TOP of TCP's 1 RTT (Deep Dive 12 §2).

  On a 100 ms RTT link:
     TCP handshake   100 ms
     TLS handshake   200 ms
     ⭐ 300 ms before the first byte of the HTTP request is sent.
```

```
⭐ AND THE `Finished` MESSAGE IS THE DOWNGRADE DEFENCE:
   It is a MAC computed over EVERY handshake message exchanged. If an
   attacker stripped strong cipher suites from the ClientHello, the
   transcripts differ, the MACs do not match, and the handshake fails.
```

---

## 3. The TLS 1.3 handshake — and what was removed

```
CLIENT                                              SERVER
  │                                                    │
  │──── ClientHello ──────────────────────────────────►│  ⭐ RTT 1
  │       client_random
  │       cipher_suites[]  ⭐ only 5 exist now
  │       ⭐ key_share      — the client GUESSES the group and sends
  │                           its ephemeral public key IMMEDIATELY
  │       supported_versions, signature_algorithms, SNI, ALPN
  │                                                    │
  │◄─── ServerHello ───────────────────────────────────│
  │       server_random, chosen suite
  │       ⭐ key_share      — server's ephemeral public key
  │       ⭐⭐ FROM HERE ON, EVERYTHING IS ENCRYPTED
  │◄─── {EncryptedExtensions} ─────────────────────────│
  │◄─── {Certificate} ─────────────────────────────────│  ⭐ ENCRYPTED now
  │◄─── {CertificateVerify} ───────────────────────────│
  │       a signature over the transcript
  │◄─── {Finished} ────────────────────────────────────│
  │                                                    │
  │──── {Finished} ───────────────────────────────────►│
  │◄══════ APPLICATION DATA ══════════════════════════►│  ⭐ after 1 RTT
```

### What made 1 RTT possible

```
⭐ THE KEY MOVE: the client SPECULATIVELY sends a key_share in the
   FIRST message, guessing which group the server will choose
   (X25519 in practice).

  ⭐ If the guess is right → 1 RTT.
  ⭐ If wrong → the server sends HelloRetryRequest naming the group
     it wants, and the client retries. That costs 2 RTT — the same
     as TLS 1.2, and no worse.

⭐ TLS 1.2 could not do this because the cipher suite determined the
   key exchange, and that was negotiated in the first exchange.
```

### ⭐ What TLS 1.3 removed, and why

This list is the most instructive part of TLS 1.3. Each removal closed a class of attack.

| Removed | Why |
|---------|-----|
| ⭐ **RSA key exchange** | No forward secrecy (§4). A compromised server key decrypts all recorded past traffic. |
| ⭐ **Static DH** | Same reason |
| ⭐ **All CBC-mode ciphers** | BEAST, Lucky13, POODLE — a decade of padding-oracle attacks |
| ⭐ **RC4** | Statistical biases; practically broken |
| ⭐ **3DES** | Sweet32 (64-bit block birthday attack) |
| ⭐ **Compression** | CRIME — compression ratio leaks plaintext |
| ⭐ **Renegotiation** | A long history of attacks; replaced by key update |
| ⭐ **Custom DH groups** | Logjam — servers using weak or backdoored parameters |
| ⭐ **MD5/SHA-1 signatures** | Collision attacks |
| ⭐ **Non-AEAD ciphers** | Encrypt-then-MAC ordering mistakes |

```
⭐ THE DESIGN PHILOSOPHY: TLS 1.2 was a menu of options, and
   ⭐ MOST OF THE ATTACKS ON IT TARGETED THE BAD OPTIONS OR THE
      NEGOTIATION BETWEEN THEM.

   TLS 1.3 removed the choices. ⭐ There are exactly FIVE cipher
   suites, all AEAD, all forward-secret.

⭐ THIS IS A GENERAL SECURITY-ARCHITECTURE LESSON: configurability
   is attack surface. A protocol with one safe option is safer than
   one with twenty options of which three are safe.
```

---

## 4. ⭐ Forward secrecy, derived

The property that justifies removing RSA key exchange, and the one worth being able to explain.

### RSA key exchange — no forward secrecy

```
1. The server's certificate contains its LONG-LIVED RSA public key.
2. ⭐ The client generates the pre-master secret and ENCRYPTS IT with
   that public key.
3. The server decrypts it with its long-lived private key.
4. Both derive the session keys from it.
```

```
⭐ THE FATAL PROPERTY:

  An attacker records the encrypted traffic today and stores it.
  ⭐ THREE YEARS LATER they obtain the server's private key
     (a breach, a subpoena, a stolen backup, Heartbleed).

  ⭐ THEY CAN NOW DECRYPT EVERY RECORDED SESSION, retroactively.
     The private key was used directly to protect the session key.
```

### (EC)DHE — forward secrecy

```
1. ⭐ Both sides generate an EPHEMERAL key pair, FOR THIS SESSION ONLY.
2. They exchange public halves.
3. ⭐ Each computes the shared secret using its own private half:
       client: shared = client_private × server_public
       server: shared = server_private × client_public
   ⭐ These are equal — that is the Diffie-Hellman property.
4. ⭐ BOTH EPHEMERAL PRIVATE KEYS ARE THEN DISCARDED.
5. The certificate's long-lived key is used ⭐ ONLY TO SIGN the
   exchange, proving the server's identity — never to encrypt anything.
```

```
⭐ THE RESULT:

  Compromising the server's long-term private key later lets the
  attacker IMPERSONATE the server going forward —
  ⭐ BUT IT REVEALS NOTHING ABOUT PAST SESSIONS, because the
     ephemeral keys that protected them no longer exist anywhere.
```

```
⭐ "FORWARD SECRECY" = a compromise TODAY does not compromise
   the PAST.

⭐ THIS IS WHY TLS 1.3 MADE IT MANDATORY, and why "record now,
   decrypt later" is the threat model that drove the change —
   the same threat model now driving post-quantum deployment (§22).
```

---

## 5. Cipher suites, decoded

### TLS 1.2 — four components in one name

```
   TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
       └─┬──┘ └┬┘      └────┬────┘ └──┬──┘
         │     │            │         │
         │     │            │         └─ ⭐ PRF hash (key derivation)
         │     │            └─────────── ⭐ bulk cipher + mode (AEAD)
         │     └──────────────────────── ⭐ AUTHENTICATION
         │                                 (the certificate's key type)
         └────────────────────────────── ⭐ KEY EXCHANGE
```

```
⭐ READING THEM:

  TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256   ✅ ideal for TLS 1.2
     ECDHE  = forward secret ✓
     ECDSA  = ⭐ an ECDSA certificate — much faster to sign (§21)
     AES_128_GCM = AEAD ✓

  TLS_RSA_WITH_AES_128_CBC_SHA              ❌ AVOID
     ⭐ RSA key exchange → NO forward secrecy (§4)
     ⭐ CBC + separate SHA MAC → padding-oracle family

  TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384     ✅ fine
```

### TLS 1.3 — only the AEAD

```
⭐ In TLS 1.3 the cipher suite names ONLY the AEAD and the hash.
   Key exchange and authentication are negotiated SEPARATELY
   (via key_share and signature_algorithms).

⭐ THE COMPLETE LIST — there are only five:

  TLS_AES_128_GCM_SHA256          ⭐ the default; fast with AES-NI
  TLS_AES_256_GCM_SHA384          larger keys, marginally slower
  TLS_CHACHA20_POLY1305_SHA256    ⭐ faster WITHOUT AES-NI (mobile)
  TLS_AES_128_CCM_SHA256          constrained/IoT
  TLS_AES_128_CCM_8_SHA256        IoT, truncated tag
```

```
⭐ THE PRACTICAL CONSEQUENCE: TLS 1.3 cipher configuration is nearly
   a non-decision. Enable the first three and stop thinking about it.
   ⭐ Most "cipher suite hardening" guides are about TLS 1.2 and are
      increasingly irrelevant.
```

---

## 6. AEAD: GCM and ChaCha20-Poly1305

```
⭐ AEAD = Authenticated Encryption with Associated Data.
   ⭐ ENCRYPTION AND AUTHENTICATION IN ONE OPERATION,
      with one key and one pass.
```

### Why AEAD replaced encrypt-then-MAC

```
⭐ The old approach combined a cipher (AES-CBC) with a separate MAC
   (HMAC-SHA1). THE ORDERING MATTERED, and TLS 1.2 got it wrong:

     ⭐ MAC-then-Encrypt (what TLS did) means the receiver must
        DECRYPT BEFORE IT CAN VERIFY — so it processes attacker-chosen
        ciphertext, and ⭐ timing differences in padding validation leak
        information.

   ⭐ That is the root of Lucky13, POODLE and the padding-oracle family.

⭐ AEAD makes the ordering unrepresentable. There is one operation;
   it either authenticates and decrypts, or it fails. No oracle.
```

### AES-GCM

```
⭐ AES in Counter mode for encryption + GHASH (Galois field
   multiplication) for authentication.

✅ ⭐ EXTREMELY FAST with AES-NI + PCLMULQDQ instructions:
   1-4 GB/s per core. Essentially free on modern server CPUs.
✅ Parallelisable (counter mode)

❌ ⭐ NONCE REUSE IS CATASTROPHIC.
   Reusing a (key, nonce) pair with GCM does not merely leak
   plaintext relationships — ⭐ IT REVEALS THE AUTHENTICATION KEY,
   letting an attacker forge arbitrary messages.
   ⭐ TLS avoids this by deriving the nonce from a per-record
      sequence number that cannot repeat within a key's lifetime.
```

### ChaCha20-Poly1305

```
⭐ A stream cipher (ChaCha20) + a one-time MAC (Poly1305).

✅ ⭐ FAST IN SOFTWARE — 3× faster than AES-GCM on CPUs WITHOUT
   AES-NI (most mobile devices, older ARM, some embedded)
✅ ⭐ CONSTANT-TIME BY DESIGN — no table lookups, so it is naturally
   immune to the cache-timing attacks that plague naive AES
✅ More forgiving of nonce handling than GCM

⭐ THIS IS WHY BOTH EXIST: servers with AES-NI prefer AES-GCM;
   mobile clients without it prefer ChaCha20. ⭐ A well-configured
   server offers both and lets the CLIENT'S PREFERENCE decide —
   which is the opposite of the old "server picks" advice.
```

```
# ⭐ Modern guidance: respect client cipher preference for this reason
ssl_prefer_server_ciphers off;    # nginx, for TLS 1.3
```

---

## 7. The TLS 1.3 key schedule

Worth seeing once, because it shows the principle of **key separation** that good cryptographic design depends on.

```
                    PSK (or 0 if none)
                          │
                    HKDF-Extract
                          ▼
                  ⭐ EARLY SECRET ──────► binder_key
                          │         └───► ⭐ client_early_traffic_secret (0-RTT, §14)
                    Derive-Secret
                          │
                       + ECDHE shared secret
                    HKDF-Extract
                          ▼
                  ⭐ HANDSHAKE SECRET ──► client_handshake_traffic_secret
                          │          └──► server_handshake_traffic_secret
                    Derive-Secret                 ⭐ (encrypts the certificate)
                          │
                       + 0
                    HKDF-Extract
                          ▼
                  ⭐ MASTER SECRET ─────► client_application_traffic_secret
                                    ├───► server_application_traffic_secret
                                    ├───► exporter_master_secret
                                    └───► ⭐ resumption_master_secret (§12)
```

```
⭐ THE PRINCIPLES ON DISPLAY:

  1. ⭐ KEY SEPARATION — handshake keys and application keys are
     DIFFERENT. Compromising one does not compromise the other.

  2. ⭐ DIRECTION SEPARATION — client→server and server→client use
     DIFFERENT keys. A reflected record cannot be replayed back.

  3. ⭐ EVERY SECRET IS DERIVED FROM THE FULL TRANSCRIPT, so any
     tampering anywhere in the handshake produces different keys
     and the Finished check fails.

  4. ⭐ HKDF (extract-then-expand) is used throughout, rather than
     ad-hoc constructions — TLS 1.2's PRF was bespoke.
```

---

## 8. X.509: the certificate, field by field

```bash
openssl x509 -in cert.pem -noout -text
```

```
Certificate:
    Data:
        Version: 3 (0x2)
        ⭐ Serial Number: 04:8f:2a:...        ← unique per CA; used in revocation
        Signature Algorithm: ecdsa-with-SHA256
        ⭐ Issuer: C=US, O=Let's Encrypt, CN=R11
        Validity
            ⭐ Not Before: Sep  1 00:00:00 2026 GMT
            ⭐ Not After : Nov 30 23:59:59 2026 GMT
        ⭐ Subject: CN=api.example.com         ← ⭐ LEGACY. Ignored for
                                                  hostname validation.
        Subject Public Key Info:
            Public Key Algorithm: id-ecPublicKey
                Public-Key: (256 bit)
                ASN1 OID: prime256v1            ← P-256
        X509v3 extensions:
            ⭐ X509v3 Subject Alternative Name:
                DNS:api.example.com, DNS:www.api.example.com
                ⭐ ← THE ONLY PLACE HOSTNAMES ARE VALIDATED
            ⭐ X509v3 Basic Constraints: critical
                CA:FALSE                        ← ⭐ a leaf cannot sign others
            X509v3 Key Usage: critical
                Digital Signature
            ⭐ X509v3 Extended Key Usage:
                TLS Web Server Authentication
            ⭐ Authority Information Access:
                OCSP - URI:http://r11.o.lencr.org
                ⭐ CA Issuers - URI:http://r11.i.lencr.org/    ← §10
            ⭐ CT Precertificate SCTs:           ← §17
                Signed Certificate Timestamp: ...
```

### ⭐ The Common Name is dead

```
⭐ CN (Common Name) WAS the hostname field. It is NOT used any more.

  • RFC 2818 deprecated it in 2000
  • ⭐ Chrome REMOVED CN fallback in version 58 (2017)
  • All modern clients validate ONLY against Subject Alternative Name

⭐ A CERTIFICATE WITH A CN BUT NO SAN FAILS EVERYWHERE.

  ⭐ THIS IS THE #1 SELF-SIGNED-CERTIFICATE MISTAKE. The old openssl
     one-liners in tutorials produce CN-only certificates that fail
     with a name-mismatch error that mentions a name that is right there
     in the certificate.
```

```bash
# ⭐ Generating a self-signed cert CORRECTLY (with SAN)
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem \
  -days 365 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:api.local,IP:127.0.0.1"
#          ⭐ ^^^^^^^^^^^^^^^^^^^^ without this, nothing will trust it
```

### Basic Constraints — the critical extension

```
⭐ Basic Constraints: CA:TRUE means "this certificate may sign others".

⭐ HISTORICALLY THIS WAS NOT CHECKED PROPERLY, which meant ANY valid
   leaf certificate could sign a certificate for ANY domain.
   ⭐ Moxie Marlinspike demonstrated this against multiple
      implementations. It is now validated universally and marked
      `critical`, which means a client that does not understand the
      extension MUST reject the certificate.
```

---

## 9. ⭐ Chain validation, step by step

```
       ┌────────────────────────────┐
       │ ROOT CA (self-signed)      │  ⭐ IN THE CLIENT'S TRUST STORE
       │ CN=ISRG Root X1            │     — NOT sent by the server
       │ CA:TRUE                    │
       └─────────────┬──────────────┘
                     │ signs
       ┌─────────────▼──────────────┐
       │ INTERMEDIATE CA            │  ⭐ THE SERVER MUST SEND THIS
       │ CN=R11                     │
       │ CA:TRUE, pathLen:0         │
       └─────────────┬──────────────┘
                     │ signs
       ┌─────────────▼──────────────┐
       │ LEAF                       │  ⭐ the server's own certificate
       │ SAN=api.example.com        │
       │ CA:FALSE                   │
       └────────────────────────────┘
```

### The validation algorithm

```
⭐ 1. BUILD THE CHAIN from the leaf upward to a certificate in the
      trust store. (May require AIA fetching — §10.)

⭐ 2. VERIFY EACH SIGNATURE: each certificate's signature must verify
      against its issuer's public key.

⭐ 3. CHECK VALIDITY DATES on every certificate in the chain,
      against the CLIENT'S CLOCK. (Clock skew → "not yet valid" — §19.)

⭐ 4. CHECK BASIC CONSTRAINTS: every non-leaf must have CA:TRUE,
      and pathLen must not be exceeded.

⭐ 5. CHECK KEY USAGE / EXTENDED KEY USAGE: the leaf must permit
      serverAuth; CAs must permit keyCertSign.

⭐ 6. CHECK NAME CONSTRAINTS if the CA has them (a CA may be
      restricted to certain domains — used for corporate CAs).

⭐ 7. CHECK REVOCATION (§15) — in practice, often skipped or soft-failed.

⭐ 8. VERIFY THE HOSTNAME against the leaf's SAN entries,
      including wildcard rules.
```

### ⭐ Wildcard rules — narrower than people expect

```
  *.example.com  MATCHES     api.example.com
                             www.example.com
  ⭐             DOES NOT    example.com          ← the apex is NOT covered
  ⭐             DOES NOT    a.b.example.com      ← ONE label only

⭐ You need BOTH in the SAN to cover the apex and subdomains:
     DNS:example.com, DNS:*.example.com

⭐ And `*.*.example.com` is invalid — one wildcard, leftmost label only.
```

---

## 10. ⭐ The missing intermediate — "works in Chrome, fails in curl"

The single most common TLS deployment bug, and the reason Chapter 13 said to test with `openssl`, not a browser.

```
⭐ THE SERVER MUST SEND: leaf + all intermediates (⭐ NOT the root).
   The root is already in the client's trust store; sending it wastes
   bytes but is harmless.

⭐ IF THE INTERMEDIATE IS MISSING, the client cannot build a chain
   from the leaf to a trusted root.
```

### Why it "works" in a browser

```
⭐ BROWSERS HIDE THE BUG in two ways:

  1. ⭐ AIA FETCHING — the leaf's Authority Information Access
     extension contains a URL for the issuing certificate.
     ⭐ Browsers FETCH IT. curl, openssl, Java, Go and Python
        generally DO NOT.

  2. ⭐ INTERMEDIATE CACHING — once a browser has seen an
     intermediate from any site, it caches it and reuses it.
     ⭐ So the developer's browser works because it visited another
        site using the same CA.
```

```
⭐ THE RESULT: the site works perfectly for the person who deployed it,
   and fails for:
     • curl / wget
     • Java clients (⭐ notoriously strict)
     • Go's crypto/tls
     • Python requests
     • Mobile apps
     • ⭐ Any server-to-server integration
     • A browser in a fresh profile / incognito on a new device
```

### Detecting it — do not trust your browser

```bash
# ⭐ THE TEST. Note: -showcerts prints exactly what the SERVER SENT.
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -showcerts </dev/null 2>/dev/null | grep -E 's:|i:'

# ✅ CORRECT — two certificates, forming a chain:
#  0 s:CN=api.example.com
#    i:C=US, O=Let's Encrypt, CN=R11        ← issuer of the leaf
#  1 s:C=US, O=Let's Encrypt, CN=R11        ← ⭐ the INTERMEDIATE, sent
#    i:C=US, O=Internet Security Research Group, CN=ISRG Root X1

# ❌ BROKEN — only one certificate:
#  0 s:CN=api.example.com
#    i:C=US, O=Let's Encrypt, CN=R11
#    ⭐ (nothing else) — the intermediate is MISSING
```

```bash
# ⭐ And the verification result line:
openssl s_client -connect api.example.com:443 -servername api.example.com \
  </dev/null 2>&1 | grep -E 'Verify return code|Verification'
# ✅ Verify return code: 0 (ok)
# ❌ ⭐ Verify return code: 21 (unable to verify the first certificate)
#                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                              ⭐ THIS EXACT MESSAGE = missing intermediate
```

### The fix

```
⭐ CONCATENATE leaf THEN intermediate(s), IN THAT ORDER, into one file.
   ⭐ ORDER MATTERS — leaf first. Some clients tolerate wrong order;
      many do not.

  cat leaf.pem intermediate.pem > fullchain.pem

⭐ Let's Encrypt / certbot already produce this as `fullchain.pem`.
   ⭐ THE BUG IS ALMOST ALWAYS POINTING THE SERVER AT `cert.pem`
      INSTEAD OF `fullchain.pem`.
```

```nginx
ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;  # ⭐ NOT cert.pem
ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
```

> **Check this on every TLS endpoint you own, with `openssl`, not a browser.** It takes ten seconds per endpoint and it is one of the highest-hit-rate checks in this entire book.

---

## 11. SNI, ALPN and Encrypted Client Hello

### SNI — Server Name Indication

```
⭐ THE PROBLEM IT SOLVES: one IP address, many HTTPS sites. The server
   must choose which certificate to present — but it must do so BEFORE
   it has seen any HTTP request, because TLS comes first.

⭐ SNI puts the hostname in the ClientHello extension.
```

```
⭐ THE PRIVACY PROBLEM: SNI IS PLAINTEXT, in both TLS 1.2 and TLS 1.3.
   ⭐ Anyone on the path sees exactly which hostname you are visiting,
      even though everything else is encrypted.

   ⭐ It is used for censorship, for corporate filtering, and for
      traffic analysis. It is the single largest metadata leak in TLS.
```

```
⭐ A COMMON FAILURE: a client that does NOT send SNI gets the server's
   DEFAULT virtual host's certificate → a hostname mismatch error.

  ⭐ openssl s_client DOES NOT SEND SNI UNLESS YOU PASS -servername.
     This causes enormous confusion when debugging:

     openssl s_client -connect api.example.com:443
     ⭐ → may return the WRONG certificate

     openssl s_client -connect api.example.com:443 -servername api.example.com
     ⭐ → correct
```

### ALPN — Application-Layer Protocol Negotiation

```
⭐ The client lists protocols it supports IN THE ClientHello;
   the server picks one.

     h2         HTTP/2 over TLS
     http/1.1   HTTP/1.1
     h3         HTTP/3 (over QUIC)

⭐ HTTP/2 OVER TLS **REQUIRES** ALPN. There is no upgrade mechanism.
   ⭐ If your load balancer does not negotiate `h2` via ALPN, clients
      silently fall back to HTTP/1.1 — and you lose multiplexing
      without any error. Check it (§20).
```

### ECH — Encrypted Client Hello

```
⭐ ECH encrypts the ClientHello (including SNI) using a public key
   published in DNS (an HTTPS/SVCB record).

  ⭐ The "outer" ClientHello carries a generic public name; the real
     one is inside the encrypted "inner" ClientHello.

⭐ It replaces ESNI, which failed because encrypting only the SNI
   field left other fingerprintable material in the clear.

⭐ STATUS: supported by Cloudflare and Firefox/Chrome behind flags;
   ⭐ it requires DNS (and ideally DoH/DoT, or the DNS lookup leaks
      the hostname anyway). Worth knowing the direction of travel.
```

---

## 12. Session resumption: IDs, tickets and PSK

A full handshake costs 1–2 RTT plus expensive asymmetric cryptography. Resumption avoids both.

### Session IDs (TLS 1.2) — stateful

```
⭐ The server generates a session ID and STORES the session state
   server-side. The client presents the ID to resume.

❌ ⭐ REQUIRES SHARED STATE ACROSS THE SERVER FLEET.
   With 20 load-balanced servers and no shared cache, a client
   resuming against a different server gets a full handshake.
   ⭐ Resumption rate collapses to ~5%.
```

### Session tickets (RFC 5077) — stateless

```
⭐ The server ENCRYPTS the session state with a SERVER-HELD TICKET KEY
   and gives the ciphertext to the client. The client presents the
   ticket to resume; the server decrypts it.

✅ ⭐ STATELESS — no server-side storage.
✅ Works across a fleet, ⭐ PROVIDED ALL SERVERS SHARE THE TICKET KEY.

❌ ⭐ AND THAT SHARED KEY IS A FORWARD-SECRECY PROBLEM (§13).
```

### TLS 1.3 — unified PSK

```
⭐ TLS 1.3 unifies both under PSK (Pre-Shared Key) resumption.

  After the handshake, the server sends ⭐ NewSessionTicket
  (one or more). The client includes a `pre_shared_key` extension
  on the next connection.

⭐ RESUMED HANDSHAKE: 1 RTT, and NO ASYMMETRIC CRYPTOGRAPHY —
   which is where most of the CPU cost lives (§21).

⭐ With psk_dhe_ke (the default), resumption ALSO performs a fresh
   ECDHE, so ⭐ the resumed session retains forward secrecy.
   Plain psk_ke does not, and should be avoided.
```

---

## 13. ⭐ Session ticket keys and the forward-secrecy trap

A widespread misconfiguration that silently destroys the forward secrecy you configured ECDHE to get.

```
⭐ THE TICKET KEY ENCRYPTS SESSION STATE — INCLUDING MATERIAL FROM
   WHICH SESSION KEYS CAN BE DERIVED.

  ⭐ IF AN ATTACKER OBTAINS THE TICKET KEY, THEY CAN DECRYPT EVERY
     SESSION RESUMED WITH A TICKET ENCRYPTED UNDER IT.

  ⭐ SO: A LONG-LIVED, NEVER-ROTATED TICKET KEY IS EXACTLY THE
     "ONE KEY DECRYPTS EVERYTHING" PROBLEM THAT FORWARD SECRECY
     EXISTS TO PREVENT (§4).
```

```
⭐ THE COMMON MISCONFIGURATION:

  A fleet of servers needs a SHARED ticket key so resumption works
  across them. So an operator generates one, puts it in a config file
  or a Kubernetes Secret, and ⭐ IT NEVER CHANGES. For years.

  ⭐ Forward secrecy is now theatre: one file compromises all
     recorded traffic.
```

### Doing it correctly

```nginx
# ⭐ nginx: rotate ticket keys, keeping old ones for decryption only
ssl_session_ticket_key /etc/nginx/ticket_keys/current.key;   # encrypt + decrypt
ssl_session_ticket_key /etc/nginx/ticket_keys/prev.key;      # ⭐ decrypt only
ssl_session_ticket_key /etc/nginx/ticket_keys/prev2.key;     # ⭐ decrypt only

# ⭐ Rotate hourly or daily; distribute via your secret manager.
# ⭐ The FIRST key listed is used to ENCRYPT; the others only DECRYPT,
#    so in-flight tickets keep working across a rotation.

ssl_session_timeout 1h;          # ⭐ bound ticket lifetime
```

```
⭐ THE SIMPLER ALTERNATIVE IF YOU CANNOT ROTATE PROPERLY:

  ssl_session_tickets off;

  ⭐ You lose stateless resumption (and pay full handshakes), but you
     do not have a long-lived master key sitting in a config file.

⭐ For most deployments, a shared session CACHE (ssl_session_cache
   with a shared Redis/memcached backend) plus tickets OFF is a
   defensible middle ground.
```

> **This is one of the most common gaps between "we configured TLS correctly" and "we actually have forward secrecy".** If your ticket key has not rotated since deployment, you do not have it.

---

## 14. ⭐ 0-RTT and the replay problem

TLS 1.3's most dangerous feature, and one you must decide about deliberately.

```
⭐ 0-RTT (early data): on a RESUMED connection, the client sends
   APPLICATION DATA IN ITS VERY FIRST FLIGHT, alongside the ClientHello.

  ⭐ ZERO round trips before the request is sent.
  ⭐ Encrypted with a key derived from the PSK alone.
```

```
CLIENT                                    SERVER
  │──── ClientHello + PSK ────────────────►│
  │     ⭐ + EARLY DATA (the HTTP request!) │
  │                                         │
  │◄─── ServerHello, {Finished} ────────────│
  │◄─── ⭐ HTTP RESPONSE ───────────────────│
```

### ⭐ The replay vulnerability

```
⭐ THE EARLY-DATA KEY IS DERIVED FROM THE PSK ONLY.
   ⭐ IT CONTAINS NO SERVER-CONTRIBUTED RANDOMNESS — because the
      server has not spoken yet.

  ⭐ THEREFORE: an attacker who captures the 0-RTT flight can REPLAY
     IT VERBATIM to the same server, or to a DIFFERENT server in the
     same cluster, and it will decrypt and execute correctly.

⭐ THE ATTACKER CANNOT READ IT. But they can MAKE IT HAPPEN AGAIN.
```

```
⭐ THE CONSEQUENCE:

  ✅ SAFE in early data:    GET /api/products
                            HEAD, OPTIONS — ⭐ IDEMPOTENT requests

  ❌ ⭐ CATASTROPHIC:       POST /api/transfer {"amount": 10000}
                            ⭐ Replay it 50 times → 50 transfers.
                            DELETE, PATCH, any state change
```

### The mitigations

```
⭐ 1. RESTRICT BY METHOD — the standard server-side defence
```
```nginx
ssl_early_data on;

# ⭐ Reject early data for anything non-idempotent
if ($ssl_early_data = "1") {
    set $early_flag "E";
}
# ⭐ Pass it to the application so IT can decide:
proxy_set_header Early-Data $ssl_early_data;
```

```
⭐ 2. THE APPLICATION MUST CHECK IT (RFC 8470)

   If the `Early-Data: 1` header is present and the request is not
   safe to replay, ⭐ respond 425 Too Early. The client then retries
   the request over the fully-established connection.
```

```
⭐ 3. SINGLE-USE TICKETS + A REPLAY CACHE
   The server records which tickets have been used for early data and
   rejects reuse. ⭐ Hard to do correctly across a distributed fleet —
   which is exactly where the attacker replays to a different node.

⭐ 4. SHORT TICKET LIFETIME — bounds the replay window.

⭐ 5. TURN IT OFF.
   ssl_early_data off;   ← ⭐ the default, and the right choice unless
                            you have explicitly designed for it.
```

> **0-RTT trades a round trip for a replay vulnerability that your application must handle.** For a CDN serving idempotent GETs it is a clear win. For an API that accepts writes, enabling it without the 425 handling is a genuine security bug. **Decide it deliberately; do not enable it because a hardening guide listed it as a performance option.**

---

## 15. Revocation: CRL, OCSP, stapling — and why it mostly failed

```
⭐ THE PROBLEM: a certificate is valid for months. If its private key
   is compromised on day 3, how does a client learn not to trust it?
```

### CRL — Certificate Revocation List

```
⭐ The CA publishes a signed list of revoked serial numbers.

❌ ⭐ THEY BECAME ENORMOUS — megabytes for a large CA
❌ ⭐ Cached for hours or days → a stale list
❌ ⭐ Most clients stopped downloading them entirely
```

### OCSP — Online Certificate Status Protocol

```
⭐ The client asks the CA "is serial X still valid?" in real time.

❌ ⭐ PRIVACY: THE CA LEARNS EVERY SITE YOU VISIT. A significant leak.
❌ ⭐ LATENCY: an extra DNS lookup + HTTP request in the handshake path
❌ ⭐ AVAILABILITY: if the OCSP responder is down, what do you do?

⭐⭐ AND THE ANSWER TO THAT LAST QUESTION IS WHY OCSP FAILED:

   ⭐ BROWSERS SOFT-FAIL. If the OCSP responder is unreachable,
      THEY PROCEED ANYWAY.

   ⭐ WHICH MEANS AN ATTACKER WHO CAN PRESENT A REVOKED CERTIFICATE
      CAN ALSO BLOCK THE OCSP REQUEST — and the client proceeds.

   ⭐ OCSP PROVIDES ESSENTIALLY NO PROTECTION AGAINST AN ACTIVE
      NETWORK ATTACKER, WHICH IS THE ONLY ATTACKER THAT MATTERS HERE.
```

### OCSP stapling — a real improvement

```
⭐ THE SERVER fetches its OWN OCSP response periodically and
   STAPLES it into the TLS handshake.

✅ ⭐ No privacy leak — the client never contacts the CA
✅ ⭐ No added latency — it arrives with the certificate
✅ The response is signed by the CA, so the server cannot forge it
✅ ⭐ One fetch per server per few hours, not one per client connection
```

```nginx
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
resolver 1.1.1.1 8.8.8.8 valid=300s;    # ⭐ REQUIRED, and often forgotten
```

```
⭐ BUT STAPLING IS STILL SOFT-FAIL unless the certificate carries the
   ⭐ MUST-STAPLE extension (OCSP Must-Staple, RFC 7633), which tells
      clients to REFUSE a handshake without a valid stapled response.

   ⭐ Must-Staple is rarely used because it turns an OCSP outage into
      a site outage. That trade-off is why revocation remains
      fundamentally unsolved in the public PKI.
```

```bash
# ⭐ Is stapling actually working? (a very common silent misconfiguration)
openssl s_client -connect example.com:443 -servername example.com -status \
  </dev/null 2>/dev/null | grep -A2 'OCSP Response Status'
# ✅ OCSP Response Status: successful (0x0)
# ❌ ⭐ "OCSP response: no response sent"  ← stapling is NOT working
```

---

## 16. ⭐ Short-lived certificates: the actual answer

```
⭐ IF REVOCATION IS UNRELIABLE, MAKE IT UNNECESSARY:
   ISSUE CERTIFICATES THAT EXPIRE BEFORE REVOCATION WOULD MATTER.
```

```
  Traditional:     1-2 years   ⭐ revocation is essential and broken
  Let's Encrypt:   90 days     ⭐ revocation matters less
  ⭐ Current CA/B  47 days     (phasing in through 2029)
     Forum direction
  ⭐ Let's Encrypt 6 days      (short-lived profile, 2025)
  ⭐ Service mesh:  1-24 hours ⭐ revocation is irrelevant
```

```
⭐ THE TRADE-OFF THAT MAKES IT WORK:

  Short-lived certificates are ONLY viable with ⭐ FULLY AUTOMATED
  ISSUANCE AND DEPLOYMENT. A 6-day certificate renewed by hand is an
  outage every week.

  ⭐ SO THE INDUSTRY SHIFT IS REALLY: "automate certificate management
     completely, and then revocation stops being a problem."
```

```
⭐ THE ARCHITECTURAL IMPLICATION FOR YOU:

  ⭐ Certificate renewal must be AUTOMATED, MONITORED, and TESTED —
     not a calendar reminder. Chapter 13 §13.5's "alert at 30/14/7 days"
     is a safety net for an automated system, not a process.

  ⭐ And every internal certificate counts too: service mesh certs,
     mTLS client certs, internal CAs, Kubernetes API server certs.
     ⭐ These are the ones with no monitoring and no automation, and
        they are the ones that cause the 3 AM outage.
```

---

## 17. Certificate Transparency

```
⭐ THE PROBLEM CT SOLVES: a CA (or an attacker who compromises one)
   can issue a valid certificate for ANY domain. The domain owner
   has no way to know.

  ⭐ This happened: DigiNotar (2011, certificates for *.google.com
     used against Iranian users), TÜRKTRUST, Symantec.
```

```
⭐ THE MECHANISM: every publicly trusted certificate MUST be submitted
   to ⭐ APPEND-ONLY, PUBLICLY AUDITABLE CT LOGS.

  The log returns an ⭐ SCT (Signed Certificate Timestamp), which is
  embedded in the certificate (or delivered via OCSP or a TLS extension).

  ⭐ Chrome REQUIRES valid SCTs from qualifying logs. A certificate
     without them is rejected.
```

```
⭐ WHY IT WORKS: the logs are Merkle trees, so the log operator
   CANNOT retroactively remove or alter an entry without detection
   by auditors.

  ⭐ Mis-issuance becomes PUBLIC AND DETECTABLE, rather than silent.
```

### ⭐ Monitor CT logs for your own domains

```
⭐ THIS IS A FREE, HIGH-VALUE SECURITY CONTROL THAT ALMOST NOBODY USES.

  Anyone issuing a certificate for YOUR domain — a rogue CA, a
  compromised DNS account, a well-meaning team in another department,
  ⭐ an attacker who obtained domain control — appears in a public log
  within minutes.
```

```bash
# ⭐ Query crt.sh for every certificate ever issued for your domain
curl -s 'https://crt.sh/?q=%25.example.com&output=json' | \
  jq -r '.[] | "\(.not_before)  \(.issuer_name)  \(.name_value)"' | sort -u

# ⭐ Set up continuous monitoring:
#    • Cert Spotter (SSLMate) — free tier
#    • Facebook CT Monitor
#    • crt.sh RSS per domain
#    ⭐ Alert on ANY certificate you did not issue.
```

> **Add CT monitoring for your domains. It takes ten minutes, costs nothing, and it is the only mechanism that detects a certificate issued for your domain without your knowledge.**

---

## 18. mTLS and workload identity

```
⭐ MUTUAL TLS: the CLIENT also presents a certificate. The server
   requests it with a CertificateRequest message and validates it
   the same way the client validated the server's.
```

```
STANDARD TLS:   the client verifies the server
⭐ mTLS:        BOTH verify each other
                ⭐ → the connection itself carries an authenticated
                     identity for both parties
```

### Why it matters architecturally

```
⭐ mTLS replaces "requests from inside the VPC are trusted"
   (Chapter 05's fallacy #4) with ⭐ CRYPTOGRAPHIC SERVICE IDENTITY.

  ✅ Every service call is authenticated, not merely encrypted
  ✅ ⭐ A compromised pod cannot impersonate another service
  ✅ Authorisation can be based on identity, not IP (which changes)
  ✅ ⭐ This is the enforcement mechanism behind Zero Trust
     (Chapter 17 §17.8)
```

### The operational problem, and how service meshes solve it

```
⭐ THE PROBLEM: mTLS means EVERY SERVICE needs a certificate,
   distributed, renewed and revoked. At 50 services × 20 pods each,
   ⭐ that is 1,000 certificates to manage.

⭐ THE SOLUTION — SPIFFE/SPIRE + a service mesh:

  ⭐ SPIFFE ID: a URI identity in the certificate's SAN
      spiffe://prod.example.com/ns/payments/sa/payment-api

  • ⭐ The mesh's control plane issues certificates automatically
    based on workload attestation (which pod, which service account,
    which node)
  • ⭐ CERTIFICATES LIVE 1-24 HOURS and rotate automatically
  • ⭐ Revocation becomes unnecessary (§16)
  • ⭐ The application code is unchanged — the sidecar handles it all
```

```
⭐ THIS IS THE STRONGEST ARGUMENT FOR A SERVICE MESH (Chapter 15 §15.5):
   not the retries or the observability, but that ⭐ it makes fleet-wide
   mTLS with short-lived certificates operationally feasible.
   Doing it by hand at scale is not realistic.
```

---

## 19. ⭐ The eight common failures and how to tell them apart

| # | Failure | Error text | Root cause | Fix |
|---|---------|-----------|------------|-----|
| 1 | ⭐ **Expired certificate** | `certificate has expired` | Renewal automation failed or was never set up | Automate + alert (§16) |
| 2 | ⭐ **Missing intermediate** | `unable to get local issuer certificate` / `Verify return code: 21` | Server sends only the leaf | ⭐ Serve `fullchain.pem` (§10) |
| 3 | ⭐ **Hostname mismatch** | `Hostname mismatch` / `CN doesn't match` | SAN lacks the hostname, or ⭐ **no SAN at all** | Reissue with the correct SAN (§8) |
| 4 | **Untrusted root** | `self signed certificate in certificate chain` | Private CA not in the trust store | Distribute the CA cert, or use a public CA |
| 5 | ⭐ **Clock skew** | `certificate is not yet valid` | ⭐ Client clock is behind (Deep Dive 02) | Fix NTP on the **client** |
| 6 | ⭐ **SNI not sent** | Wrong certificate returned | Old client, or `openssl` without `-servername` | ⭐ Pass `-servername`; upgrade the client (§11) |
| 7 | **Protocol/cipher mismatch** | `handshake failure` / `no shared cipher` | Old client vs TLS-1.3-only server | Check which versions are enabled |
| 8 | ⭐ **Wrong chain order** | Intermittent failures by client | Chain not leaf-first | ⭐ Reorder: leaf, then intermediates (§10) |

```
⭐ THE TWO THAT LOOK IDENTICAL BUT ARE NOT:

  #2 (missing intermediate) and #4 (untrusted root) both produce
  "cannot verify". ⭐ Distinguish them with -showcerts:

    • ⭐ Only ONE certificate in the output  → #2, missing intermediate
    • ⭐ Full chain present, but the root is not trusted → #4
```

```
⭐ AND #5 IS ALWAYS THE CLIENT'S CLOCK, NOT THE SERVER'S.
   "not yet valid" means the client believes the current time is
   before Not Before. A container with a broken clock, a VM restored
   from a snapshot (Deep Dive 02 §2), or a device with a dead RTC.
```

---

## 20. Diagnosis: the commands

```bash
# ═══ ⭐ THE ONE COMMAND TO START WITH ═══
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -showcerts </dev/null

# ⭐ Read, in order:
#   • the certificate chain (s: and i: lines)      → §10
#   • "Verify return code: 0 (ok)"                 → chain validity
#   • "Protocol : TLSv1.3"                         → version
#   • "Cipher : TLS_AES_128_GCM_SHA256"            → §5
#   • "ALPN protocol: h2"                          → §11
```

```bash
# ═══ EXPIRY ═══
echo | openssl s_client -connect api.example.com:443 -servername api.example.com \
  2>/dev/null | openssl x509 -noout -dates -subject -ext subjectAltName
# notBefore=Sep  1 00:00:00 2026 GMT
# notAfter=Nov 30 23:59:59 2026 GMT
# subject=CN=api.example.com
# X509v3 Subject Alternative Name:
#     DNS:api.example.com, DNS:www.api.example.com

# ⭐ Days remaining — put this in a monitoring check
echo | openssl s_client -connect api.example.com:443 -servername api.example.com \
  2>/dev/null | openssl x509 -noout -checkend $((30*86400)) \
  || echo "⭐ EXPIRES WITHIN 30 DAYS"
```

```bash
# ═══ ⭐ VERIFY THE CHAIN AS A STRICT CLIENT WOULD ═══
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -verify_return_error -verify 5 </dev/null
# ⭐ -verify_return_error makes it FAIL rather than warn — use this,
#    because the default output buries the problem.
```

```bash
# ═══ PROTOCOL SUPPORT ═══
for v in tls1 tls1_1 tls1_2 tls1_3; do
  echo -n "$v: "
  openssl s_client -connect api.example.com:443 -servername api.example.com \
    -$v </dev/null >/dev/null 2>&1 && echo "⭐ supported" || echo "not supported"
done
# ⭐ tls1 and tls1_1 should NOT be supported.
```

```bash
# ═══ OCSP STAPLING (§15) ═══
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -status </dev/null 2>/dev/null | grep -A3 'OCSP Response'

# ═══ ALPN / HTTP2 (§11) ═══
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -alpn h2 </dev/null 2>/dev/null | grep ALPN
# ⭐ ALPN protocol: h2      ← HTTP/2 will be used
# ⭐ (no ALPN negotiated)   ← silently falling back to HTTP/1.1

# ═══ ⭐ THE COMPREHENSIVE SCAN ═══
testssl.sh --full api.example.com
# or SSL Labs: https://www.ssllabs.com/ssltest/
```

```bash
# ═══ INSPECT A LOCAL CERTIFICATE ═══
openssl x509 -in cert.pem -noout -text
openssl verify -CAfile chain.pem cert.pem
# ⭐ Does the private key match the certificate?
diff <(openssl x509 -in cert.pem -noout -modulus) \
     <(openssl rsa  -in key.pem  -noout -modulus) && echo "⭐ key matches"
```

---

## 21. ⭐ Performance: the numbers that drive capacity

### The handshake cost

```
⭐ A FULL HANDSHAKE COSTS:
   • 1-2 network round trips (§2, §3)
   • ⭐ ASYMMETRIC CRYPTOGRAPHY — the dominant CPU cost

⭐ THE KEY ASYMMETRY, and it is the opposite of what people assume:

   RSA-2048:   sign ~1,500/s per core   ⭐ verify ~40,000/s per core
   ECDSA P-256: sign ~25,000/s per core    verify ~10,000/s per core

   ⭐ THE SERVER SIGNS. THE CLIENT VERIFIES.

   ⭐ SO ECDSA IS ROUGHLY 15× FASTER FOR THE SERVER.
```

```
⭐ THE PRACTICAL CONSEQUENCE:

  A server with an RSA-2048 certificate is limited to roughly
  ⭐ 1,500 NEW TLS HANDSHAKES PER SECOND PER CORE.

  The same server with an ECDSA P-256 certificate:
  ⭐ ~25,000 per second per core.

⭐ FOR A HIGH-CONNECTION-RATE SERVICE, SWITCHING TO ECDSA IS ONE OF
   THE LARGEST AVAILABLE WINS — and it is a certificate change,
   not a code change.
```

```nginx
# ⭐ Serve BOTH — clients that support ECDSA get the fast path;
#    ancient clients still work.
ssl_certificate     /etc/ssl/ecdsa-fullchain.pem;
ssl_certificate_key /etc/ssl/ecdsa-privkey.pem;
ssl_certificate     /etc/ssl/rsa-fullchain.pem;
ssl_certificate_key /etc/ssl/rsa-privkey.pem;
```

### The bulk encryption cost

```
⭐ WITH AES-NI (all modern server CPUs):
   AES-128-GCM: ⭐ 1-4 GB/s per core — effectively free

⭐ WITHOUT AES-NI:
   AES-128-GCM: ~150 MB/s per core
   ⭐ ChaCha20-Poly1305: ~500 MB/s per core  ← 3× faster

⭐ THIS IS WHY BOTH EXIST (§6), and why you should let the CLIENT
   choose (ssl_prefer_server_ciphers off).
```

### Session resumption — the biggest lever

```
⭐ RESUMED HANDSHAKE: no asymmetric cryptography at all.

  ⭐ MEASURED: a resumed handshake costs roughly 5-10% of a full one
     in CPU terms.

⭐ SO RESUMPTION RATE IS A CAPACITY METRIC:

     50% resumption  → roughly half the TLS CPU
     90% resumption  → ⭐ roughly one tenth
```

```bash
# ⭐ Measure your resumption rate
# nginx: log $ssl_session_reused
log_format tls '$ssl_protocol $ssl_cipher ⭐ reused=$ssl_session_reused';
# then: awk '{print $3}' access.log | sort | uniq -c
```

```
⭐ IF YOUR RESUMPTION RATE IS LOW, CHECK:
   • ⭐ Tickets disabled, or ticket keys not shared across the fleet (§13)
   • ⭐ Session cache too small or not shared
   • ssl_session_timeout too short
   • ⭐ A load balancer terminating TLS per-connection without
     session sharing
```

### And the zero-copy cost

```
⭐ REMEMBER DEEP DIVE 10 §5 AND CHAPTER 13: enabling TLS DISABLES
   sendfile() zero-copy, because the data must be encrypted in
   user space.

  ⭐ For a file/object server or Kafka, that is a 20-40% throughput
     reduction independent of the handshake cost.

  ⭐ (kTLS — kernel TLS — restores zero-copy by moving symmetric
     encryption into the kernel. Supported by nginx and available in
     modern Linux; worth investigating for high-throughput static
     content.)
```

---

## 22. Post-quantum: what is already shipping

```
⭐ THE THREAT: "HARVEST NOW, DECRYPT LATER."

  An adversary records encrypted traffic today and stores it until a
  cryptographically relevant quantum computer exists. Shor's algorithm
  then breaks ⭐ RSA, ECDSA and ECDH — every key exchange and signature
  in use today.

⭐ FORWARD SECRECY (§4) DOES NOT HELP, because the ephemeral ECDHE
   exchange itself is what gets broken.
```

```
⭐ THE TIMELINE THAT MATTERS: data that must stay confidential for
   10+ years is ALREADY AT RISK, because it is being recorded now.
```

### What is deployed today

```
⭐ HYBRID KEY EXCHANGE — combine a classical and a post-quantum
   algorithm, so the session is secure if EITHER holds.

  ⭐ X25519MLKEM768   (X25519 + ML-KEM-768, formerly Kyber)

  ⭐ ALREADY ENABLED BY DEFAULT in Chrome and Firefox, and supported
     by Cloudflare, AWS and Google. ⭐ A meaningful fraction of public
     TLS traffic is already post-quantum-protected for key exchange.
```

```
⭐ WHAT IS NOT YET DEPLOYED: post-quantum SIGNATURES (ML-DSA/Dilithium,
   SLH-DSA/SPHINCS+). They are much larger than ECDSA signatures
   (kilobytes vs 64 bytes), which inflates every certificate chain
   and every handshake. ⭐ The CA ecosystem transition has not begun
   in earnest.

⭐ AND THE ASYMMETRY IS FINE: signatures only need to be
   quantum-resistant BEFORE a quantum computer exists (you cannot
   retroactively forge a past signature). ⭐ KEY EXCHANGE needs it NOW,
   because of harvest-now-decrypt-later. That is exactly why key
   exchange was done first.
```

```bash
# ⭐ Is your endpoint offering post-quantum key exchange?
openssl s_client -connect example.com:443 -servername example.com \
  -groups X25519MLKEM768 </dev/null 2>&1 | grep -i 'Negotiated\|group'
```

> **The architect's action today: make sure your TLS termination layer (CDN, load balancer, ingress) is on a version that supports hybrid key exchange, and enable it.** It is a configuration change with no downside, and it protects anything recorded from today onward.

---

## 23. Configuration

```nginx
# ═══ PROTOCOL (§3) ═══
ssl_protocols TLSv1.2 TLSv1.3;          # ⭐ TLSv1.3 only if all clients support it
ssl_prefer_server_ciphers off;           # ⭐ let the client choose (§6)

# ⭐ TLS 1.2 suites — forward-secret AEAD only (§5)
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;

ssl_ecdh_curve X25519:prime256v1:secp384r1;   # ⭐ X25519 first

# ═══ ⭐ CERTIFICATES — fullchain, and BOTH key types (§10, §21) ═══
ssl_certificate     /etc/ssl/ecdsa-fullchain.pem;   # ⭐ NOT cert.pem
ssl_certificate_key /etc/ssl/ecdsa-privkey.pem;
ssl_certificate     /etc/ssl/rsa-fullchain.pem;
ssl_certificate_key /etc/ssl/rsa-privkey.pem;

# ═══ SESSION RESUMPTION (§12-13) ═══
ssl_session_cache shared:SSL:50m;        # ⭐ ~200,000 sessions
ssl_session_timeout 1h;
ssl_session_tickets on;
ssl_session_ticket_key /etc/nginx/keys/current.key;   # ⭐ ROTATE THESE (§13)
ssl_session_ticket_key /etc/nginx/keys/prev.key;

# ═══ ⭐ 0-RTT (§14) — off unless you have implemented 425 handling ═══
ssl_early_data off;
# If on:  proxy_set_header Early-Data $ssl_early_data;

# ═══ OCSP STAPLING (§15) ═══
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/ssl/chain.pem;
resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;   # ⭐ required for stapling

# ═══ HTTP/2 (§11) ═══
http2 on;

# ═══ SECURITY HEADERS (Chapter 17 §17.5) ═══
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
```

```
⭐ AND THE OPERATIONAL REQUIREMENTS THAT MATTER MORE THAN ANY OF THE ABOVE:

  ⭐ 1. AUTOMATED renewal (certbot, cert-manager, ACME) — for EVERY
        certificate, including internal ones
  ⭐ 2. ALERT at 30/14/7 days on every certificate, including
        internal mTLS and service mesh CAs
  ⭐ 3. ROTATE session ticket keys (§13)
  ⭐ 4. MONITOR CT logs for your domains (§17)
  ⭐ 5. TEST WITH openssl, NOT A BROWSER (§10)
  ⭐ 6. INVENTORY every certificate — the one you forget is the one
        that expires
```

---

## 24. What an architect takes from this

**1. TLS authenticates the server's identity, not its trustworthiness**, and it hides nothing about *where* you are connecting — SNI is plaintext. It solves exactly three problems on one hop.

**2. TLS 1.3's main contribution is removal.** It deleted RSA key exchange, CBC modes, compression, renegotiation and custom DH groups — because most attacks on TLS 1.2 targeted the bad options or the negotiation between them. **Configurability is attack surface.**

**3. Forward secrecy means a key compromise today does not decrypt recorded past traffic.** It is now mandatory — and **a never-rotated session ticket key silently destroys it** (§13). Check yours.

**4. The missing intermediate is the single most common TLS deployment bug**, and browsers hide it via AIA fetching and caching. **Test every endpoint with `openssl s_client -showcerts`, not a browser.** Ten seconds each, very high hit rate.

**5. `Verify return code: 21` means missing intermediate. A CN with no SAN fails everywhere. "Not yet valid" is always the client's clock.** Those three mappings resolve most TLS incidents immediately.

**6. 0-RTT is replayable by design.** Enabling it without RFC 8470's `425 Too Early` handling is a genuine security bug for any API that accepts writes. It is off by default for a reason.

**7. OCSP soft-fail makes revocation nearly useless against an active attacker** — the attacker who can present a revoked certificate can also block the OCSP check. **Short-lived, fully automated certificates are the industry's actual answer**, and that means certificate renewal must be automated infrastructure, not a calendar reminder.

**8. ECDSA certificates are ~15× faster for the server than RSA**, because the server signs and RSA signing is the slow direction. For a high-connection-rate service this is a large win available through a certificate change alone.

**9. Session resumption rate is a capacity metric.** A resumed handshake costs 5–10% of a full one. If your rate is low, your ticket keys are probably not shared across the fleet.

**10. Certificate Transparency monitoring is free and almost nobody does it.** It is the only way to detect a certificate issued for your domain without your knowledge.

**11. mTLS with short-lived, auto-rotated certificates is what makes Zero Trust real** — and doing it for 1,000 workloads by hand is not feasible, which is the strongest argument for a service mesh.

**12. Post-quantum hybrid key exchange is already shipping in browsers and CDNs.** Harvest-now-decrypt-later means long-lived confidential data is at risk *today*. Enabling `X25519MLKEM768` at your edge is a configuration change with no downside.

---

## Exercises

1. Run `openssl s_client -showcerts` against every public TLS endpoint you own. How many are missing an intermediate?
2. Check whether any certificate in your estate has a CN but no SAN. What happens when a modern client connects to it?
3. Explain forward secrecy to a colleague in four sentences, including why TLS 1.3 removed RSA key exchange.
4. Find your session ticket keys. When were they last rotated? If never, explain what that means for the forward secrecy you configured.
5. Measure your TLS session resumption rate from access logs. If it is below 50%, diagnose why.
6. Test whether ALPN negotiates `h2` on your endpoints. If not, you are silently on HTTP/1.1.
7. Verify OCSP stapling is actually working on your endpoints (most that configure it do not have the `resolver` line).
8. Benchmark RSA-2048 vs ECDSA P-256 handshakes with `openssl speed`. Compute the capacity difference for your connection rate.
9. Enable 0-RTT on a test server and demonstrate a replay with a captured early-data flight. Then implement the `425 Too Early` response.
10. Set up Certificate Transparency monitoring for your domains. Review every certificate issued in the last year — do you recognise them all?
11. Inventory every TLS certificate in your systems, including internal mTLS, service mesh CAs, and Kubernetes components. How many have expiry monitoring?
12. Check whether your edge supports hybrid post-quantum key exchange. If not, find out when it will.
13. Construct each of the eight failures in §19 on a test server and record the exact error message each client library produces.
14. Write the runbook entry for "certificate expired in production at 3 AM", including how to issue an emergency certificate and how to verify the chain before deploying it.

---

**Next in this series:** Deep Dive 14 — HTTP/1.1, /2 and /3 on the wire

**Back to:** [Deep Dives](README.md) · [Chapter 13](../13-networking.md) · [Chapter 17](../17-security-architecture.md) · [The Map](../README.md)
