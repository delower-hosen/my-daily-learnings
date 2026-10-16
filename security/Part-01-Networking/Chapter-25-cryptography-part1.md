# Chapter 25 — Cryptography Part 1: Symmetric Encryption, Modes, Hashes, MACs, and Randomness

---

## 1. Why This Matters

Cryptography is the mathematical foundation of nearly every security control that provides confidentiality,
integrity, or authenticity: TLS (Chapter 28), PKI (Chapter 27), JWTs (Chapter 60), password storage (Chapter
52), KMS and encryption at rest (Chapter 80), secrets (Chapter 68), and signed software artifacts (Chapter
113). You have referenced "encryption," "hashing," and "signatures" throughout the book; this chapter and the
next build them properly.

For a cloud security engineer, the goal is not to *design* cryptographic algorithms (never do that) but to
**use them correctly** — and using them correctly requires understanding what each primitive provides, what
it does *not*, and the classic misuses. The stakes are concrete:

1. **Choosing the right primitive for the goal** — confidentiality (encryption), integrity/authenticity
   (MAC/signature), password storage (slow hash), or a fingerprint (fast hash). Using the wrong one (e.g.
   encryption for integrity, or a fast hash for passwords) is a serious, common error.
2. **The golden rule — never roll your own crypto** — and its corollary, *never roll your own crypto usage
   either*: use vetted libraries and high-level constructions (AEAD, not raw ciphers) correctly. Most
   crypto failures are *misuse* (wrong mode, reused nonce, no integrity, timing leaks), not broken
   algorithms.
3. **Randomness is a cryptographic dependency** — weak randomness breaks everything (predictable keys,
   tokens, IVs). Using a cryptographically secure RNG (CSPRNG) is non-negotiable.
4. **Timing and side channels** (Chapter 1 §4.5) — non-constant-time comparison of secrets (MACs,
   passwords) leaks them; this is why constant-time comparison exists.

The core idea: **cryptography provides distinct primitives for distinct goals — symmetric encryption
(confidentiality, with a shared key), hashes (fast fingerprints, one-way), MACs (integrity + authenticity
with a shared key), and AEAD (encryption + integrity together) — and using them correctly means choosing the
right primitive, using vetted high-level constructions (AEAD), never rolling your own, depending on a secure
RNG (CSPRNG), and comparing secrets in constant time. Symmetric crypto is fast and needs a shared key
(Chapter 26 solves key distribution with asymmetric crypto).** This chapter covers the symmetric primitives
and the correct-usage rules; Chapter 26 covers asymmetric crypto and key exchange, and together they
underpin TLS (Chapter 28).

---

## 2. Prerequisites

- Chapter 7 (bytes/hex/encoding — crypto operates on bytes; Base64/hex are encoding not encryption — §recall
  Chapter 7 §4.7), Chapter 1 §4.5 (cache/timing side channels — the basis for constant-time comparison).
- The distinction between encoding (reversible, no key — Chapter 7) and encryption (needs a key) — reinforced
  here.
- Forward: Chapter 26 (asymmetric), Chapter 27 (PKI), Chapter 28 (TLS) build on this.

---

## 3. Mental Model

**Cryptography provides different tools for different security goals — and the fundamental skill is matching
the primitive to the goal. Symmetric encryption gives confidentiality with a shared key; hashes give a
one-way fingerprint (no key); MACs give integrity + authenticity with a shared key; AEAD combines encryption
and integrity. Using the wrong tool for the goal is the most common crypto error.**

```
   GOAL                              PRIMITIVE                        NEEDS A KEY?
   -------------------------------   ------------------------------   ------------
   Confidentiality (hide data)       Symmetric encryption (AES)       yes (shared)
   Integrity + authenticity          MAC (HMAC)                       yes (shared)
   Confidentiality + integrity       AEAD (AES-GCM, ChaCha20-Poly1305) yes (shared)   <- USE THIS for encryption
   One-way fingerprint               Hash (SHA-256)                   no
   Password storage                  SLOW hash (bcrypt/scrypt/Argon2) no (+salt)      <- NOT a fast hash!
   Random keys/tokens/IVs            CSPRNG (getrandom/urandom)       n/a

   The golden rules:
     1. NEVER roll your own crypto (algorithms OR usage) — use vetted libraries and high-level constructions.
     2. Match the primitive to the goal (encryption ≠ integrity; fast hash ≠ password storage).
     3. Use AEAD for encryption (confidentiality + integrity together) — not raw ciphers.
     4. Use a CSPRNG for all randomness — never a regular PRNG.
     5. Compare secrets in CONSTANT TIME (MACs, tokens) — avoid timing side channels.
```

Three ideas:

1. **Different primitives for different goals.** Encryption ≠ integrity ≠ authenticity ≠ fingerprinting ≠
   password storage. Each has its primitive, and using the wrong one (encryption alone for integrity, a fast
   hash for passwords, a hash alone for authenticity) is a serious, common error. The skill is matching.
2. **Symmetric crypto is fast but needs a shared key.** Symmetric encryption (AES) and MACs (HMAC) use a
   *shared secret key* both parties have — fast and efficient, but with the **key distribution problem**
   (how do both parties get the shared key securely?). Asymmetric crypto (Chapter 26) solves distribution;
   symmetric does the bulk work. TLS uses asymmetric to exchange a symmetric key, then symmetric for the
   data (Chapter 28).
3. **Correct usage matters more than algorithm choice.** Modern algorithms (AES, SHA-256, HMAC) are not
   broken; most crypto failures are *misuse* — wrong mode (ECB), reused nonce, missing integrity (encryption
   without a MAC), weak randomness, non-constant-time comparison. Using vetted high-level constructions
   (AEAD, a good password hash, a CSPRNG) correctly is the job.

**The security framing:** cryptography is a toolbox of primitives, each providing a specific property, and
the cloud security engineer's job is to *use them correctly* — match the primitive to the goal, use vetted
high-level constructions (AEAD for encryption, Argon2/bcrypt for passwords, HMAC for integrity, CSPRNG for
randomness), never roll your own, and avoid the classic misuses (ECB mode, nonce reuse, missing integrity,
weak RNG, timing leaks). Symmetric crypto (this chapter) is fast and needs a shared key; Chapter 26's
asymmetric crypto solves key distribution, and Chapter 28's TLS combines them.

---

## 4. Fundamentals

### 4.1 Symmetric encryption (confidentiality with a shared key)

**Symmetric encryption** uses the *same key* to encrypt and decrypt. The standard is **AES (Advanced
Encryption Standard)**, a block cipher operating on 128-bit blocks with 128/192/256-bit keys:

```
   plaintext + key --[AES encrypt]--> ciphertext
   ciphertext + key --[AES decrypt]--> plaintext
   (same key both directions -> "symmetric")
```

Key points:

- **AES is a block cipher** — it encrypts fixed 128-bit blocks. To encrypt arbitrary-length data, you use a
  **mode of operation** (§4.2), which is where most encryption errors happen.
- **AES is fast** (hardware-accelerated — AES-NI instructions) and secure with proper usage. AES-256 is the
  common choice; AES-128 is also secure.
- **ChaCha20** is a modern stream cipher, an alternative to AES (fast in software, used where AES-NI is
  absent — mobile). ChaCha20-Poly1305 is a common AEAD (§4.3).
- **The key must be secret and shared** — the key distribution problem (§3, Chapter 26).
- **Encryption provides confidentiality only, NOT integrity** — a critical point (§4.4). Encryption without
  integrity is malleable (an attacker can modify ciphertext to alter the plaintext in some modes) — which is
  why you use AEAD (§4.3), not raw encryption.

### 4.2 Modes of operation (and the ECB disaster)

A block cipher encrypts one block; a **mode of operation** extends it to arbitrary data. The mode choice is
critical, and the classic error is **ECB**:

```
   ECB (Electronic Codebook) — NEVER USE:
     Each block is encrypted independently with the same key.
     -> IDENTICAL plaintext blocks produce IDENTICAL ciphertext blocks.
     -> Patterns in the plaintext are VISIBLE in the ciphertext (the infamous "ECB penguin" image:
        encrypting a bitmap with ECB leaves the image outline visible).
     ECB leaks structure and is trivially attackable. NEVER use ECB.

   Better modes:
     CBC (Cipher Block Chaining): each block XORed with the previous ciphertext + an IV (random per message).
       -> identical plaintexts produce different ciphertexts (with a random IV). But CBC alone has no
          integrity (padding-oracle attacks) and requires a separate MAC.
     CTR (Counter): turns the block cipher into a stream cipher; needs a unique nonce per message.
     GCM (Galois/Counter Mode): CTR + built-in authentication = AEAD (§4.3) — THE modern choice.
```

The lessons: (1) **NEVER use ECB** — it leaks plaintext structure (the ECB penguin is the canonical
demonstration). (2) **Modes need a unique IV/nonce per message** — reusing an IV/nonce breaks security
(reveals plaintext relationships in CBC; catastrophically breaks GCM/CTR). (3) **Most modes provide
confidentiality only, not integrity** — you need a MAC too, which is why **AEAD (§4.3) is the modern default:
it combines encryption and integrity correctly, removing the chance to get the combination wrong.**

### 4.3 AEAD — the modern default (encryption + integrity together)

**AEAD (Authenticated Encryption with Associated Data)** combines encryption and integrity/authenticity in
one construction, removing the error-prone "encrypt then MAC separately" step:

```
   AEAD encrypt(key, nonce, plaintext, associated_data) -> ciphertext + authentication tag
   AEAD decrypt(key, nonce, ciphertext, tag, associated_data) -> plaintext, OR fails if tampered

   Provides:
     - CONFIDENTIALITY (the ciphertext hides the plaintext)
     - INTEGRITY + AUTHENTICITY (the tag detects any tampering with the ciphertext OR the associated data)
   Common AEAD: AES-GCM, ChaCha20-Poly1305.
   "Associated data": data authenticated but not encrypted (e.g. headers) -- integrity without confidentiality.
```

Why AEAD is the modern default:

- **It combines confidentiality and integrity correctly.** Raw encryption (CBC, CTR) provides only
  confidentiality; combining it with a MAC ("encrypt-then-MAC") correctly is error-prone (MAC-then-encrypt
  and encrypt-and-MAC have flaws; ordering and implementation matter). AEAD does it right, in one
  vetted construction — **use AEAD, not raw encryption + a separate MAC.**
- **It authenticates associated data** — headers/metadata that need integrity but not confidentiality can be
  included in the authentication without being encrypted.
- **The nonce must be unique per (key, message)** — reusing a nonce with the same key in GCM is
  **catastrophic** (it can reveal the plaintext and the authentication key). Nonce management is the main
  AEAD pitfall; use a random nonce (with sufficient length) or a counter, never reuse.

TLS 1.3 (Chapter 28) uses AEAD exclusively (AES-GCM, ChaCha20-Poly1305) — the modern standard. When you need
to encrypt data, **use an AEAD from a vetted library** (libsodium's `crypto_secretbox`, or your language's
AEAD), which handles the combination correctly.

### 4.4 The critical rule: encryption ≠ integrity

A recurring, serious error: **encryption alone does not provide integrity.** Encryption hides the data
(confidentiality) but does not, by itself, detect tampering:

```
   With encryption ALONE (no integrity, e.g. CTR or CBC without a MAC):
     An attacker who cannot read the ciphertext can still MODIFY it, and in some modes (CTR, CBC) the
     modification produces predictable changes in the decrypted plaintext (malleability).
     -> The recipient decrypts tampered data without knowing it was tampered.
   Example: a CTR-mode ciphertext where flipping a ciphertext bit flips the corresponding plaintext bit ->
     an attacker can alter a message ("transfer $10" -> "transfer $90") without the key.
```

So **you almost always need integrity with encryption** — which is exactly what AEAD provides (§4.3). The
rule: **use AEAD (which combines both) for encryption; never use raw encryption without integrity.** This
error — encryption without integrity — has caused real vulnerabilities (padding oracles, malleability
attacks), and it is why "we encrypted it" is not enough; you need "we encrypted AND authenticated it" (AEAD).
The general lesson: **confidentiality and integrity are separate properties requiring separate (or combined
via AEAD) mechanisms** — a distinction that recurs (encryption at rest gives confidentiality of media, not
integrity or access control — Chapter 1; a MAC gives integrity, not confidentiality).

### 4.5 Hashes (one-way fingerprints)

A **cryptographic hash** maps arbitrary input to a fixed-size output (a digest/fingerprint), with key
properties:

```
   hash(input) -> fixed-size digest (e.g. SHA-256 -> 256 bits / 32 bytes / 64 hex chars)
   Properties:
     - Deterministic: same input -> same digest
     - One-way (preimage resistance): infeasible to find the input from the digest
     - Collision resistant: infeasible to find two inputs with the same digest
     - Avalanche: a tiny input change -> a completely different digest
   Standard: SHA-256 (SHA-2 family), SHA-3. AVOID: MD5, SHA-1 (broken — collisions found).
```

Uses and misuses:

- **Uses:** integrity verification (does this file match its known hash?), fingerprinting/deduplication,
  content-addressing (Git commits, OCI image digests — Chapter 94), and as a building block (HMAC — §4.6,
  signatures — Chapter 26).
- **MD5 and SHA-1 are broken** (practical collisions found) — never use them for security (a collision means
  two different inputs with the same hash, breaking integrity/signature guarantees). Use SHA-256+.
- **A hash alone provides integrity only if the hash is trusted/authenticated** — anyone can recompute a
  hash, so a hash *published alongside* data does not prevent an attacker from replacing both. Integrity
  against an *attacker* requires a **keyed** construction (MAC — §4.6) or a signature (Chapter 26), OR the
  hash delivered over an authenticated channel. (A hash verifies *accidental* corruption or matches a
  *trusted* reference; a MAC/signature verifies against a *deliberate* attacker.)
- **CRITICAL: a plain hash is NOT for password storage** (§4.7) — a fast hash is exactly wrong for passwords.

### 4.6 MACs (integrity + authenticity with a shared key)

A **MAC (Message Authentication Code)** provides integrity *and* authenticity using a shared secret key:

```
   MAC(key, message) -> tag
   The recipient (who has the shared key) recomputes MAC(key, message) and checks it equals the tag.
   -> Detects tampering (integrity) AND proves the sender had the key (authenticity).
   An attacker WITHOUT the key cannot forge a valid tag.
   Standard: HMAC (HMAC-SHA256) — a hash-based MAC construction.
```

Key points:

- **A MAC is keyed** — unlike a plain hash (which anyone can compute), a MAC requires the secret key, so it
  proves authenticity (the sender had the key) as well as integrity. This is the difference between "this
  data wasn't accidentally corrupted" (hash) and "this data came from someone with the key and wasn't
  tampered" (MAC).
- **HMAC** is the standard MAC construction (HMAC-SHA256), used in TLS (Chapter 28), JWT (HS256 — Chapter
  60), API request signing (AWS SigV4 — Chapter 71), and webhook verification.
- **A MAC provides integrity/authenticity, NOT confidentiality** — the message is not hidden (unless also
  encrypted). For both, use AEAD (§4.3), which is essentially encryption + a MAC done correctly.
- **Compare MACs in constant time** (§4.8) — comparing a MAC byte-by-byte with early exit leaks timing
  (Chapter 1 §4.5), letting an attacker forge a tag incrementally. Use a constant-time comparison function.

### 4.7 Password storage (the special case — slow hashes)

Password storage is a distinct, critical case where using the wrong primitive (a fast hash) is a severe,
common error:

```
   WRONG: store hash(password) with a fast hash (SHA-256, MD5).
     -> An attacker who steals the database can brute-force/dictionary-attack the fast hashes at billions
        of guesses/second (GPUs), cracking most passwords. Fast hashes are DESIGNED to be fast -> bad here.

   RIGHT: store a SLOW, salted, memory-hard hash: Argon2 (preferred), scrypt, or bcrypt.
     - SLOW/tunable work factor: deliberately expensive (millions of times slower than SHA-256) so
       brute-forcing is infeasible.
     - SALT (unique random per password): prevents precomputed rainbow tables and identical-password detection.
     - MEMORY-HARD (Argon2/scrypt): resists GPU/ASIC acceleration.
```

The rule: **NEVER store passwords with a fast hash (SHA-256/MD5); use a slow, salted, memory-hard password
hash (Argon2id preferred, or scrypt/bcrypt) with an appropriate work factor.** This is one of the most
important and most-violated crypto rules — a fast hash for passwords means a stolen database is quickly
cracked (Chapter 52 covers authentication in depth). The reason is counterintuitive: for most crypto you want
speed, but for password storage you want *slowness* (to make brute-forcing expensive), plus salting (to
prevent precomputation) and memory-hardness (to resist specialized hardware). Chapter 52 details this; the
principle here is that password storage is a special case requiring a purpose-built slow hash, never a
general-purpose fast one.

### 4.8 Randomness (the cryptographic dependency) and constant-time comparison

Two correct-usage essentials that break everything if wrong:

**Randomness — use a CSPRNG:**

```
   Cryptographic keys, IVs/nonces, tokens, salts, session IDs — ALL require cryptographically secure
   randomness. Use a CSPRNG (Cryptographically Secure PRNG):
     - Linux: getrandom() / /dev/urandom (Chapter 3 §4.2)
     - Languages: secrets (Python), crypto.randomBytes (Node), RandomNumberGenerator (C#), crypto/rand (Go)
   NEVER use a regular PRNG (rand(), Math.random(), java.util.Random) for security — they are PREDICTABLE
     (seeded deterministically), so an attacker can predict keys/tokens/IVs -> total compromise.
```

Weak randomness is a total break: predictable session tokens (account takeover), predictable keys
(decryption), predictable IVs/nonces (breaking encryption). Always use a CSPRNG; this is non-negotiable and a
common vulnerability (using `Math.random()` for a token — Chapter 52).

**Constant-time comparison:**

```
   Comparing secrets (MACs, tokens, password-hash results) with a normal comparison (==, memcmp) that
   EXITS EARLY on the first differing byte leaks TIMING (Chapter 1 §4.5): the comparison takes longer the
   more leading bytes match, letting an attacker guess the secret byte-by-byte by measuring response times.
   -> Use a CONSTANT-TIME comparison (hmac.compare_digest, crypto.timingSafeEqual, CryptographicOperations.
      FixedTimeEquals) that always takes the same time regardless of where the mismatch is.
```

Constant-time comparison prevents timing side-channel attacks on secret comparison (Chapter 1 §4.5) — a
subtle but real vulnerability (timing attacks have recovered MACs and tokens). Always use the constant-time
comparison function for secrets.

---

## 5. Deep Technical Explanation: Correct Usage Over Algorithm Choice

The defining lesson of applied cryptography — and the one a cloud security engineer must internalize — is
that **correct usage matters far more than algorithm choice, because modern algorithms are not broken; the
failures are misuse.** Understanding *why* reframes how you approach crypto.

**The golden rule and its real meaning:** "Never roll your own crypto" is universally cited but often
misunderstood as "don't invent algorithms" (true, but rare). The deeper meaning is **"never roll your own
crypto *usage* either"** — don't combine primitives yourself (encrypt-then-MAC by hand), don't manage nonces/
IVs manually if you can avoid it, don't implement comparison or key derivation yourself. Use **vetted,
high-level constructions** that make correct usage the default: AEAD (not raw cipher + hand-rolled MAC), a
password-hashing library (not hash + salt by hand), a CSPRNG (not a seeded PRNG), libsodium/your platform's
crypto (not OpenSSL primitives assembled yourself). The reason: the primitives are correct, but *combining*
them correctly is subtle and error-prone, and the high-level constructions encode the correct combination.

**The catalogue of misuse (why usage dominates):** essentially every real-world crypto vulnerability is
misuse, not a broken algorithm:

- **ECB mode** (§4.2) — leaks plaintext structure (the penguin). The algorithm (AES) is fine; the mode is
  wrong.
- **Nonce/IV reuse** (§4.2, §4.3) — catastrophic in GCM/CTR (reveals plaintext, breaks authentication). The
  algorithm is fine; the usage reused a nonce.
- **Encryption without integrity** (§4.4) — malleability, padding oracles. The encryption is fine; integrity
  is missing (use AEAD).
- **Fast hash for passwords** (§4.7) — cracked quickly. SHA-256 is fine; it is the wrong tool for passwords
  (use a slow hash).
- **Weak randomness** (§4.8) — predictable keys/tokens. The algorithm is fine; the RNG is predictable (use a
  CSPRNG).
- **Non-constant-time comparison** (§4.8) — timing leaks the secret. The MAC is fine; the comparison leaks.
- **MD5/SHA-1** (§4.5) — actually-broken algorithms (collisions), the exception that proves the rule (and the
  fix is to use a non-broken hash, still a "usage" choice).

Every item is fixed by *using the right construction correctly*, not by inventing better crypto. This is why
the cloud security engineer's cryptographic competence is *not* algorithm design (never do that) but
**correct selection and usage**: match the primitive to the goal (§3), use vetted high-level constructions
(AEAD, Argon2, HMAC, CSPRNG), avoid the classic misuses, and rely on well-tested libraries and managed
services (KMS — Chapter 80 — handles key management and correct usage for you).

**The primitives-to-goals mapping is the core skill** (§3): confidentiality → AEAD; integrity/authenticity →
MAC (or AEAD); fingerprint → hash; password storage → slow hash; randomness → CSPRNG. Getting this mapping
right, and using the vetted construction for each, is 90% of applied crypto. The remaining 10% is nonce
management, constant-time comparison, and key management (Chapter 26, 80) — all of which vetted libraries and
managed services increasingly handle.

**Why symmetric crypto needs a partner (the bridge to Chapter 26):** symmetric crypto (this chapter) is fast
and does the bulk work, but it has the **key distribution problem** — both parties need the same secret key,
and getting it to both securely (without an attacker intercepting it) is unsolved by symmetric crypto alone.
Chapter 26's asymmetric cryptography solves this (public-key exchange lets parties agree on a shared symmetric
key over an insecure channel), and Chapter 28's TLS combines them: asymmetric to establish a shared symmetric
key, then fast symmetric AEAD for the data. So symmetric crypto is the workhorse, asymmetric is the key
distributor, and together they are TLS. Understanding symmetric primitives and their correct usage (this
chapter) is the foundation for that combination.

The unifying insight: **applied cryptography is about correct usage, not algorithm design — match the
primitive to the goal, use vetted high-level constructions (AEAD, slow password hashes, HMAC, CSPRNG), never
roll your own (algorithms or usage), and avoid the classic misuses (ECB, nonce reuse, encryption without
integrity, fast-hash passwords, weak RNG, timing leaks). Modern algorithms are sound; the failures are
misuse.** This mindset — humility about crypto (use vetted tools correctly, don't invent) — is the
professional standard, and it extends to relying on managed services (KMS — Chapter 80) that handle key
management and correct usage.

---

## 6. Internals: Using Cryptographic Primitives Correctly

### 6.1 Symmetric encryption done right (AEAD)

```python
# CORRECT: use an AEAD (encryption + integrity together) from a vetted library.
# Python with the `cryptography` library (AES-GCM):
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
key = AESGCM.generate_key(bit_length=256)          # a proper key
aesgcm = AESGCM(key)
nonce = os.urandom(12)                               # UNIQUE nonce per message (CSPRNG!) — never reuse
ciphertext = aesgcm.encrypt(nonce, b"secret data", b"associated-header")  # AEAD: encrypt + authenticate
plaintext = aesgcm.decrypt(nonce, ciphertext, b"associated-header")       # fails if tampered
# Even simpler & harder to misuse: libsodium (PyNaCl) crypto_secretbox — manages the details.
```

The correct pattern: an **AEAD** (AES-GCM here), a **unique CSPRNG nonce per message** (never reused —
§4.3), and associated data authenticated. The library handles the confidentiality+integrity combination
correctly. Contrast the wrong patterns (ECB, raw CBC without a MAC, reused nonce) — never do those.

### 6.2 Hashing and MACs

```python
import hashlib, hmac
# Hash (fingerprint — SHA-256, NOT for passwords):
digest = hashlib.sha256(b"data").hexdigest()        # a fingerprint; anyone can compute it

# MAC (integrity + authenticity — HMAC with a shared key):
key = b"shared-secret-key"
tag = hmac.new(key, b"message", hashlib.sha256).hexdigest()
# Verify with CONSTANT-TIME comparison (§4.8) — NOT ==:
is_valid = hmac.compare_digest(tag, received_tag)   # constant-time; avoids timing leak (Chapter 1 §4.5)
```

Note: SHA-256 for a fingerprint (unkeyed, anyone can compute), HMAC-SHA256 for integrity/authenticity
(keyed), and **`hmac.compare_digest` for constant-time comparison** — never `==` for secrets.

### 6.3 Password storage (slow hash)

```python
# CORRECT: a slow, salted, memory-hard password hash (Argon2 via argon2-cffi):
from argon2 import PasswordHasher
ph = PasswordHasher()                                # sensible defaults (memory-hard, tunable)
hash = ph.hash("user-password")                       # salted + slow; store this
ph.verify(hash, "user-password")                      # verify (constant-time, raises on mismatch)
# WRONG (never): hashlib.sha256(password) — fast hash, crackable at billions/sec (§4.7)
```

Use a password-hashing library (Argon2id preferred; bcrypt/scrypt acceptable) — never a fast hash. The
library handles salting, work factors, and verification correctly (Chapter 52).

### 6.4 Secure randomness

```python
import secrets                                        # Python's CSPRNG module
token = secrets.token_urlsafe(32)                     # a secure random token (session ID, etc.)
key = secrets.token_bytes(32)                          # secure random key material
# WRONG (never for security): random.random(), random.randint() — predictable PRNG (§4.8)
```

```bash
# On Linux, the source is getrandom()/urandom (Chapter 3 §4.2):
$ head -c 32 /dev/urandom | xxd    # raw CSPRNG bytes
```

Always a CSPRNG (`secrets` in Python, `crypto.randomBytes` in Node, `RandomNumberGenerator` in C#) — never a
regular PRNG.

### 6.5 The ECB penguin (why mode matters — demonstration)

```bash
# Demonstrate ECB leaking structure (conceptual — the famous "ECB penguin"):
# Encrypting a bitmap image with AES-ECB leaves the image outline visible, because identical plaintext
# blocks (e.g. same-color regions) produce identical ciphertext blocks (§4.2).
# (Search "ECB penguin" — the canonical visual proof that ECB leaks patterns and must never be used.)
echo "ECB: identical plaintext blocks -> identical ciphertext blocks -> patterns leak. NEVER use ECB."
```

The ECB penguin is the canonical demonstration that mode choice matters and ECB must never be used — a fast,
memorable proof of "correct usage over algorithm choice."

---

## 7. Real-World Example: Cryptography in the Ledger System

**Where Ledger uses cryptographic primitives (and must use them correctly):**

- **TLS (Chapters 4, 28):** all traffic uses TLS, which uses symmetric AEAD (AES-GCM/ChaCha20-Poly1305) for
  the data after an asymmetric key exchange (Chapter 26). Ledger uses vetted TLS libraries — never
  implementing crypto itself.
- **Password storage (Chapter 52):** Ledger stores user passwords with **Argon2id** (a slow, salted,
  memory-hard hash — §4.7), never a fast hash. A stolen database is not quickly crackable. This is a critical
  correct-usage decision.
- **JWT signing (Chapter 60):** Ledger's JWTs are signed with **HMAC-SHA256 (HS256)** — a MAC providing
  integrity/authenticity — or asymmetric signatures (RS256/ES256 — Chapter 26). The signature is verified in
  **constant time** (§4.8), and the payload is understood to be readable Base64 (not secret — Chapter 7,
  Chapter 60).
- **Session tokens and secrets (Chapter 68):** generated with a **CSPRNG** (§4.8) — predictable tokens would
  be account takeover.
- **API request signing (AWS SigV4 — Chapter 71):** AWS API requests are signed with HMAC — a MAC — proving
  authenticity to AWS.
- **Encryption at rest / KMS (Chapters 1, 80):** RDS/S3 encryption uses AES-GCM via KMS envelope encryption
  (Chapter 80); KMS handles key management and correct usage — Ledger does not roll its own.
- **Data-at-rest field encryption (if any):** for sensitive fields, Ledger would use an AEAD (AES-GCM) via
  KMS/a vetted library — encryption *with* integrity (§4.4), never raw encryption.

The correct-usage decisions Ledger makes: AEAD (not raw ciphers) for encryption; Argon2id (not a fast hash)
for passwords; HMAC for integrity/signing; CSPRNG for all tokens/keys; constant-time comparison for
secrets; and vetted libraries / KMS (never rolling its own crypto). The failures Ledger avoids: fast-hash
passwords (crackable DB), encryption without integrity (malleable), weak RNG (predictable tokens),
non-constant-time comparison (timing leaks), and homegrown crypto.

The Ledger takeaway: **cryptography in Ledger is about correct usage — matching the primitive to the goal
(AEAD for encryption, Argon2 for passwords, HMAC for integrity, CSPRNG for randomness), using vetted
libraries and KMS (never rolling its own), and avoiding the classic misuses — with symmetric crypto (this
chapter) doing the fast bulk work under TLS and at-rest encryption, and asymmetric crypto (Chapter 26)
handling key distribution.** The professional posture is cryptographic humility: use vetted tools correctly,
don't invent.

---

## 8. Hands-On Demonstration

### LAB 25.1 — Using Cryptographic Primitives Correctly

**Objective.** Practice correct usage of each primitive — AEAD encryption, hashing vs MACs, slow password
hashing, secure randomness, and constant-time comparison — and see the classic misuses (ECB, fast-hash
passwords, weak RNG) and why they fail.

**Cost.** Free. **Environment.** ENV-1 (Python with `cryptography`, `argon2-cffi`). **Time.** 45–60 minutes.

**Steps.**

*Step 1 — AEAD encryption (confidentiality + integrity).*

```bash
pip install cryptography argon2-cffi 2>/dev/null
python3 - <<'PY'
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
key = AESGCM.generate_key(bit_length=256); a = AESGCM(key)
nonce = os.urandom(12)                                # unique CSPRNG nonce per message
ct = a.encrypt(nonce, b"transfer $10", b"header")     # AEAD: encrypt + authenticate
print("decrypt OK:", a.decrypt(nonce, ct, b"header"))
# Tamper with the ciphertext -> AEAD detects it (integrity):
tampered = bytearray(ct); tampered[0] ^= 1
try: a.decrypt(nonce, bytes(tampered), b"header")
except Exception as e: print("tamper detected (integrity works):", type(e).__name__)
PY
```

**Expected:** decryption succeeds for the real ciphertext; tampering is *detected* (an exception) — AEAD
provides integrity (§4.4). Contrast: raw encryption without integrity would decrypt the tampered data
silently.

*Step 2 — Hash vs MAC.*

```bash
python3 - <<'PY'
import hashlib, hmac
print("hash (anyone can compute):", hashlib.sha256(b"data").hexdigest()[:16], "...")
key = b"shared-secret"
tag = hmac.new(key, b"message", hashlib.sha256).hexdigest()
print("MAC (needs the key):", tag[:16], "...")
print("constant-time verify:", hmac.compare_digest(tag, tag))   # §4.8 — never use ==
PY
```

*Step 3 — Password storage: slow vs fast (why fast is wrong).*

```bash
python3 - <<'PY'
import hashlib, time
from argon2 import PasswordHasher
# Fast hash (WRONG for passwords) — measure how fast (crackable):
t=time.time(); [hashlib.sha256(b"password").hexdigest() for _ in range(100000)]
print(f"SHA-256: 100k hashes in {time.time()-t:.3f}s (billions/sec on a GPU -> crackable)")
# Slow hash (RIGHT) — deliberately expensive:
ph = PasswordHasher(); t=time.time(); h = ph.hash("password")
print(f"Argon2: 1 hash in {time.time()-t:.3f}s (deliberately slow -> brute-force infeasible)")
print("verify:", ph.verify(h, "password"))
PY
```

**Expected:** SHA-256 does 100k hashes in a fraction of a second (so a stolen DB of SHA-256 password hashes
is cracked fast — the wrong tool); Argon2 takes meaningful time per hash (making brute-force infeasible — the
right tool). This is the §4.7 lesson made concrete.

*Step 4 — Secure randomness.*

```bash
python3 - <<'PY'
import secrets, random
print("CSPRNG token (secure):", secrets.token_urlsafe(24))
# WRONG: random.random() is predictable (seeded) — never for security:
random.seed(42); print("PRNG (predictable if seed known):", random.random())
random.seed(42); print("PRNG again (SAME — predictable!):", random.random())
PY
```

**Expected:** the CSPRNG token is unpredictable; the regular PRNG produces the *same* value when re-seeded —
demonstrating it is predictable and unsafe for security (§4.8).

*Step 5 — Constant-time comparison.*

```bash
python3 - <<'PY'
import hmac
# Use constant-time comparison for secrets (§4.8) — not == (which can leak timing):
secret = "a1b2c3d4"; received = "a1b2c3d4"
print("constant-time equal:", hmac.compare_digest(secret, received))
# (== would exit early on the first mismatch, leaking timing — the vulnerability constant-time prevents.)
PY
```

**Security implications.** Write down: (a) match the primitive to the goal (AEAD/encryption, MAC/integrity,
hash/fingerprint, slow-hash/passwords, CSPRNG/randomness); (b) AEAD provides confidentiality AND integrity
(encryption alone does not — §4.4); (c) fast hash ≠ password storage (use Argon2 — §4.7); (d) CSPRNG for all
randomness (§4.8); (e) constant-time comparison for secrets (§4.8); (f) never roll your own — use vetted
libraries.

**Cleanup.** None.

---

## 9. Security Implications

- **Cryptography provides distinct primitives for distinct goals** — symmetric encryption (confidentiality,
  shared key), hash (one-way fingerprint, no key), MAC (integrity + authenticity, shared key), AEAD
  (confidentiality + integrity together). **Matching the primitive to the goal** is the core skill;
  mismatches (encryption for integrity, fast hash for passwords) are the common serious errors.
- **Correct usage matters more than algorithm choice** — modern algorithms (AES, SHA-256, HMAC) are sound;
  essentially all real crypto failures are **misuse**: ECB mode, nonce/IV reuse, encryption without
  integrity, fast-hash passwords, weak RNG, non-constant-time comparison, MD5/SHA-1.
- **Never roll your own crypto — algorithms OR usage.** Use vetted high-level constructions (AEAD, not raw
  ciphers; a password-hashing library; HMAC; a CSPRNG) that encode correct combination, and managed services
  (KMS — Chapter 80).
- **Encryption ≠ integrity** (§4.4) — encryption alone is malleable; use **AEAD** (confidentiality +
  integrity together). Confidentiality and integrity are separate properties.
- **Password storage is a special case** — use a **slow, salted, memory-hard hash (Argon2id/scrypt/bcrypt)**,
  NEVER a fast hash (SHA-256/MD5), because a stolen DB of fast hashes is quickly cracked (Chapter 52).
- **Randomness is a cryptographic dependency** — use a **CSPRNG** for all keys/tokens/IVs/salts; a regular
  PRNG is predictable and a total break.
- **Compare secrets in constant time** (§4.8) — non-constant-time comparison leaks timing (Chapter 1 §4.5),
  enabling byte-by-byte forgery.
- **Symmetric crypto is fast but needs a shared key** (the key distribution problem) — Chapter 26's
  asymmetric crypto solves distribution; Chapter 28's TLS combines them.

---

## 10. Attack Scenarios (crypto misuse)

1. **ECB mode** (§4.2): identical plaintext blocks → identical ciphertext (the penguin) → structure leaks;
   patterns/data recoverable. Defense: never ECB; use AEAD.
2. **Nonce/IV reuse** (§4.2, §4.3): reusing a GCM nonce with the same key reveals plaintext and the auth key
   (catastrophic). Defense: unique CSPRNG nonce per message; use libraries that manage it.
3. **Encryption without integrity** (§4.4): malleability (bit-flipping to alter plaintext), padding oracles.
   Defense: AEAD (encryption + integrity).
4. **Fast-hash password cracking** (§4.7): a stolen DB of SHA-256/MD5 password hashes cracked at billions/sec.
   Defense: Argon2id/scrypt/bcrypt (slow, salted, memory-hard).
5. **Weak randomness** (§4.8): predictable session tokens (account takeover), predictable keys/IVs. Defense:
   CSPRNG.
6. **Timing attack on comparison** (§4.8, Chapter 1 §4.5): non-constant-time MAC/token comparison leaks the
   secret byte-by-byte. Defense: constant-time comparison.
7. **MD5/SHA-1 collisions** (§4.5): forged files/certificates with the same hash. Defense: SHA-256+.
8. **Homegrown crypto** (§5): invented algorithms/combinations with subtle flaws. Defense: vetted libraries/
   managed services; never roll your own.

---

## 11. Defensive Techniques

- **Match the primitive to the goal** (§3): confidentiality → **AEAD** (AES-GCM/ChaCha20-Poly1305);
  integrity/authenticity → **MAC** (HMAC) or AEAD; fingerprint → **hash** (SHA-256+); password storage →
  **slow hash** (Argon2id); randomness → **CSPRNG**.
- **Use AEAD for encryption** — never raw ciphers or hand-combined encrypt-then-MAC; AEAD provides
  confidentiality + integrity correctly (§4.3, §4.4).
- **Never roll your own crypto (algorithms or usage)** — use vetted, high-level libraries (libsodium,
  platform crypto) and managed services (**KMS** — Chapter 80, which handles key management and correct
  usage).
- **Store passwords with a slow, salted, memory-hard hash** (Argon2id preferred; scrypt/bcrypt acceptable)
  with an appropriate work factor — NEVER a fast hash (§4.7, Chapter 52).
- **Use a CSPRNG for all cryptographic randomness** (keys, tokens, IVs/nonces, salts, session IDs) — never a
  regular PRNG (§4.8).
- **Compare secrets in constant time** (`hmac.compare_digest`, `crypto.timingSafeEqual`,
  `CryptographicOperations.FixedTimeEquals`) — never `==`/`memcmp` for MACs/tokens/hash results (§4.8).
- **Never reuse nonces/IVs** with the same key (catastrophic in GCM) — use unique CSPRNG nonces or counters,
  or libraries that manage nonces.
- **Avoid broken algorithms** (MD5, SHA-1, ECB, DES/3DES, RC4) — use current standards (AES-GCM,
  ChaCha20-Poly1305, SHA-256/SHA-3, HMAC, Argon2, and Chapter 26's asymmetric standards).
- **Rely on managed services for key management** (KMS, secrets managers — Chapters 68, 80) — key management
  is the hardest part; let managed services handle it correctly.

---

## 12. Production Architecture

Cryptographic primitives in production, and how managed services handle correct usage:

```
 GOAL                     PRIMITIVE (correct usage)         SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------    -------------------   -------------------------
 confidentiality (transit) TLS AEAD (Chapter 28)             TLS library           ACM certs + TLS (managed)
 confidentiality (at rest) AES-GCM via envelope encryption   library + key mgmt     KMS envelope encryption (Ch80)
 integrity/authenticity    HMAC / AEAD                        library               KMS/SigV4 (Ch71)
 password storage          Argon2id (slow, salted)           argon2 library         same (app-level)
 randomness                CSPRNG                             getrandom/urandom      same (+ KMS for keys)
 signing (JWT/artifacts)   HMAC or asymmetric (Ch26)          library               KMS asymmetric / signing (Ch113)
 key management            (the hard part)                    manual (risky)         KMS (Ch80) — managed, correct
 secret comparison         constant-time                      library function      library function
```

The architectural principle: **use cryptographic primitives correctly by matching the primitive to the goal,
using vetted high-level constructions (AEAD, Argon2, HMAC, CSPRNG), and relying on managed services (KMS,
secrets managers) for the hardest part — key management — rather than rolling your own.** Symmetric crypto
(this chapter) does the fast bulk work (TLS data, at-rest encryption); Chapter 26's asymmetric crypto handles
key distribution and signing; and managed services (KMS — Chapter 80) increasingly handle key management and
correct usage, so the cloud security engineer's job is correct *selection and integration*, not
implementation. The professional posture — cryptographic humility (use vetted tools correctly, never invent)
— is the standard, because the failures are always misuse, not broken algorithms.

---

## 13. Common Mistakes

1. **Using the wrong primitive for the goal** — encryption for integrity, a fast hash for passwords, a hash
   for authenticity (needs a MAC). Match the primitive to the goal.
2. **Rolling your own crypto** (algorithms or usage/combinations) — subtle flaws; use vetted libraries/KMS.
3. **ECB mode** — leaks structure (the penguin); use AEAD.
4. **Encryption without integrity** — malleability; use AEAD.
5. **Nonce/IV reuse** — catastrophic in GCM; unique nonces.
6. **Fast hash for passwords** — crackable DB; use Argon2id/scrypt/bcrypt (§4.7).
7. **Regular PRNG for security** — predictable; use a CSPRNG.
8. **Non-constant-time comparison of secrets** — timing leak; use constant-time comparison.
9. **MD5/SHA-1** — broken; use SHA-256+.
10. **Confusing encoding with encryption** — Base64/hex are encoding, not encryption (Chapter 7); they
    provide no confidentiality.

---

## 14. Troubleshooting

| Symptom / concern | Issue | Fix |
|---|---|---|
| Need to encrypt data | which primitive? | AEAD (AES-GCM/ChaCha20-Poly1305) — confidentiality + integrity |
| Need to store passwords | which primitive? | slow salted hash (Argon2id/scrypt/bcrypt) — NEVER a fast hash |
| Need integrity/authenticity | which primitive? | MAC (HMAC) or AEAD; a hash alone is not enough vs an attacker |
| Encrypted data can be tampered | no integrity (raw encryption) | use AEAD (§4.4) |
| Ciphertext shows patterns | ECB mode | use AEAD; never ECB (§4.2) |
| Tokens/keys predictable | weak RNG (regular PRNG) | use a CSPRNG (§4.8) |
| Suspected timing attack on comparison | non-constant-time compare | use constant-time comparison (§4.8) |
| Certificate/file forged with same hash | MD5/SHA-1 collision | use SHA-256+ (§4.5) |
| Key management is hard/risky | rolling your own | use KMS / a secrets manager (Chapters 68, 80) |

---

## 15. Practical Lab

Lab 25.1 is in §8. Register it in the lab index. Extension: take a piece of insecure crypto code (e.g. one
that stores passwords with SHA-256, encrypts with AES-ECB, uses `random` for tokens, and compares MACs with
`==`) and fix each issue (Argon2id, AES-GCM, `secrets`, `hmac.compare_digest`), documenting why each original
was wrong — a direct exercise in the correct-usage-over-algorithm-choice lesson and the misuse catalogue
(§5).

---

## 16. Exercises

### Concept questions

**25.1** Match each goal to its primitive (confidentiality, integrity/authenticity, fingerprint, password
storage, randomness) and explain why using the wrong one is a serious error.

**25.2** Explain why "encryption ≠ integrity" and what AEAD provides. Why is AEAD the modern default for
encryption?

**25.3** Explain why a fast hash (SHA-256) is wrong for password storage and what to use instead, with the
three properties the right choice needs.

**25.4** Explain the difference between a hash and a MAC, and when each provides integrity against an
attacker.

**25.5** Explain why "correct usage matters more than algorithm choice," with three examples of misuse of
sound algorithms.

### Debugging problems

**25.6** A code review finds passwords stored with `sha256(password)`. Explain the risk and the fix.

**25.7** Encrypted data is being tampered with undetected. What is missing, and how do you fix it?

**25.8** Session tokens are being predicted/guessed. Diagnose and fix.

### Security scenarios

**25.9** You must add field-level encryption for sensitive data. Specify the primitive, the key management,
the nonce handling, and how you ensure integrity — and what you would NOT do.

**25.10** Review a homegrown "encryption" scheme (custom algorithm, fixed IV, no integrity) and explain
every problem and the correct approach.

### Architecture questions

**25.11** Explain how symmetric crypto's key distribution problem motivates asymmetric crypto (Chapter 26)
and how TLS (Chapter 28) combines them.

**25.12** Explain the role of a managed service (KMS — Chapter 80) in correct cryptographic usage and key
management.

### Hands-on exercises

**25.13** Implement correct AEAD encryption/decryption with a unique nonce and demonstrate tamper detection.

**25.14** Demonstrate the speed difference between a fast hash and a slow password hash, and explain the
security implication.

**25.15** Fix a piece of insecure crypto code (SHA-256 passwords, ECB, `random` tokens, `==` MAC compare).

### Interview questions

**25.16** "How do you store passwords securely, and why not just hash them?"

**25.17** "What's the difference between encryption, hashing, and a MAC?"

**25.18** "Why is 'never roll your own crypto' the rule, and what does it really mean?"

**25.19** "What is AEAD and why use it?"

**25.20** "Why does randomness matter in cryptography, and what do you use?"

---

## 17. Summary

- **Cryptography provides distinct primitives for distinct goals** — **symmetric encryption** (AES;
  confidentiality, shared key), **hash** (SHA-256; one-way fingerprint, no key), **MAC** (HMAC; integrity +
  authenticity, shared key), and **AEAD** (AES-GCM/ChaCha20-Poly1305; confidentiality + integrity together).
  **Matching the primitive to the goal** is the core skill.
- **Correct usage matters more than algorithm choice** — modern algorithms are sound; essentially all real
  failures are **misuse**: **ECB** (leaks structure — the penguin), **nonce/IV reuse** (catastrophic in
  GCM), **encryption without integrity** (malleability — use AEAD), **fast-hash passwords** (crackable),
  **weak RNG** (predictable), **non-constant-time comparison** (timing leak), **MD5/SHA-1** (broken).
- **Never roll your own crypto — algorithms OR usage.** Use vetted high-level constructions (**AEAD**, a
  **password-hashing library**, **HMAC**, a **CSPRNG**) that encode correct combination, and managed services
  (**KMS** — Chapter 80).
- **Encryption ≠ integrity** — use **AEAD** (both together); confidentiality and integrity are separate
  properties.
- **Password storage is a special case** — a **slow, salted, memory-hard hash (Argon2id/scrypt/bcrypt)**,
  never a fast hash (Chapter 52).
- **Randomness is a cryptographic dependency** — use a **CSPRNG** for all keys/tokens/IVs/salts; a regular
  PRNG is a total break. **Compare secrets in constant time** (Chapter 1 §4.5).
- **Symmetric crypto is fast but needs a shared key** (the key distribution problem) — Chapter 26's
  asymmetric crypto solves distribution, Chapter 28's TLS combines them. The professional posture is
  cryptographic humility: use vetted tools correctly, never invent.

---

## 18. Knowledge Check

1. Match each goal to its primitive and explain a wrong-primitive error. (§3, §4)
2. Why does encryption not provide integrity, and what does AEAD provide? (§4.3, §4.4)
3. Why is a fast hash wrong for passwords, and what are the three properties of the right choice? (§4.7)
4. What is the difference between a hash and a MAC? (§4.5, §4.6)
5. Why is ECB never used? (§4.2)
6. Why is nonce reuse catastrophic in GCM? (§4.3)
7. Why must you use a CSPRNG, not a regular PRNG? (§4.8)
8. Why compare secrets in constant time? (§4.8, Chapter 1 §4.5)
9. What does "never roll your own crypto" really mean? (§5)
10. Why does symmetric crypto need asymmetric crypto (Chapter 26)? (§5)

---

## 19. Further Exploration

- "Cryptographic Right Answers" (Latacora / earlier versions) — a concise, opinionated guide to which
  primitives to use (AEAD, Argon2, etc.) — the correct-usage cheat sheet.
- libsodium documentation — a library designed to make correct usage the default (crypto_secretbox, etc.).
- The "ECB penguin" — the canonical visual proof that mode matters (§4.2).
- OWASP Password Storage Cheat Sheet — the authoritative password-hashing guidance (§4.7, Chapter 52).
- NIST recommendations for AES modes, hash functions, and RNGs — the standards.
- Chapter 26 next (asymmetric crypto and key exchange) — solves symmetric's key distribution problem, and
  together with this chapter underpins PKI (27), TLS (28), and JWT/signing (60, 113).

---

## Solutions

### 25.1
Goal → primitive: **Confidentiality** (hide data) → symmetric encryption / **AEAD** (AES-GCM). **Integrity +
authenticity** (detect tampering, prove sender had the key) → **MAC** (HMAC) or AEAD. **Fingerprint**
(one-way identifier) → **hash** (SHA-256). **Password storage** → **slow, salted, memory-hard hash**
(Argon2id/scrypt/bcrypt). **Randomness** (keys/tokens/IVs) → **CSPRNG**. Using the wrong one is a serious
error because each primitive provides a specific property and lacks others: (a) using **encryption for
integrity** fails because encryption alone is malleable — an attacker can tamper with ciphertext undetected
(§4.4); you need a MAC or AEAD. (b) Using a **fast hash for passwords** fails because fast hashes are
crackable at billions/sec, so a stolen DB is quickly broken (§4.7); you need a deliberately slow hash. (c)
Using a **plain hash for authenticity** fails because anyone can compute a hash, so it does not prove the
sender had a key (§4.5, §4.6); you need a keyed MAC or a signature. (d) Using a **regular PRNG for
randomness** fails because it is predictable, so keys/tokens are guessable (§4.8); you need a CSPRNG. The
core skill of applied crypto is matching the primitive to the goal; the common serious errors are all
mismatches.

### 25.16
Never store passwords with a plain (fast) hash like SHA-256 or MD5, because fast hashes are *designed* to be
fast — an attacker who steals the password database can compute billions of guesses per second on GPUs,
cracking most passwords via dictionary/brute-force attacks quickly. Instead, use a **slow, salted,
memory-hard password-hashing function** — **Argon2id** (preferred), or **scrypt** or **bcrypt** — with an
appropriate work factor. Three properties make these right: (1) **slow/tunable work factor** — deliberately
expensive (millions of times slower than SHA-256) so each guess costs meaningful time, making brute-forcing
infeasible; (2) **unique random salt per password** — prevents precomputed rainbow-table attacks and hides
whether two users have the same password; (3) **memory-hardness** (Argon2/scrypt) — requires significant
memory per hash, resisting GPU/ASIC acceleration that would otherwise speed up cracking. So the counterintuitive
point is that for password storage you want *slowness* (unlike most crypto where you want speed), because the
threat is offline brute-forcing of a stolen database. Use a vetted library (argon2-cffi, bcrypt) that handles
salting, the work factor, and verification (in constant time) correctly — never hash-and-salt by hand, and
never a fast hash. (Chapter 52 covers authentication and password handling in depth.)

### 25.18
"Never roll your own crypto" is the rule because cryptography is extraordinarily subtle — small mistakes
(a reused nonce, a wrong mode, a missing integrity check, a non-constant-time comparison, a predictable RNG,
an off-by-one in a combination) completely break security in ways that are not visible from testing (the code
"works," it just is not secure). Cryptographic algorithms and constructions are designed and vetted by
experts over years of analysis; a homegrown algorithm or combination almost certainly has flaws that
attackers will find. The rule is usually understood as "don't invent new algorithms" (true, but rare in
practice), but its **deeper meaning is "don't roll your own crypto *usage* either"** — don't combine
primitives yourself (hand-rolling encrypt-then-MAC), don't manage nonces/IVs manually if avoidable, don't
implement key derivation or comparison yourself. Instead, use **vetted, high-level constructions** that make
correct usage the default: AEAD (not raw cipher + a hand-built MAC), a password-hashing library (not
hash+salt by hand), a CSPRNG (not a seeded PRNG), libsodium or your platform's crypto (not OpenSSL primitives
assembled yourself), and managed services (KMS) for key management. The reason is that the primitives are
correct but *combining and using* them correctly is where the failures are (§5's misuse catalogue: ECB, nonce
reuse, missing integrity, fast-hash passwords, weak RNG, timing leaks — all misuse of sound algorithms). So
the professional posture is cryptographic humility: select the right vetted construction, use it correctly per
its documentation, and rely on managed services for the hardest parts (key management) — never invent, whether
algorithms or their combination.

---

*Next: Chapter 26 — Cryptography Part 2: Asymmetric Keys, Signatures, Key Exchange, and Forward Secrecy. We
solve symmetric crypto's key distribution problem with public-key cryptography — how parties agree on a shared
key over an insecure channel (Diffie-Hellman/ECDHE), how digital signatures provide authenticity and
non-repudiation, and how forward secrecy protects past sessions — the foundation of PKI (Chapter 27) and TLS
(Chapter 28).*
