# Chapter 26 — Cryptography Part 2: Asymmetric Keys, Signatures, Key Exchange, and Forward Secrecy

---

## 1. Why This Matters

Chapter 25 ended on a problem: symmetric crypto is fast but needs a *shared* key, and getting that key to
both parties securely over an insecure network (the internet) is unsolved by symmetric crypto alone — the
**key distribution problem**. Asymmetric (public-key) cryptography solves it, and in doing so provides the
foundation for nearly everything that authenticates identity and establishes secure channels: TLS key
exchange (Chapter 28), digital signatures for certificates (PKI — Chapter 27), JWT signing (RS256/ES256 —
Chapter 60), SSH keys (Chapter 30), signed software artifacts (Chapter 113), and code/commit signing.

For a cloud security engineer, asymmetric crypto matters because:

1. **It solves key distribution** — enabling two parties who have never met to establish a shared secret over
   an insecure channel (Diffie-Hellman/ECDHE), the foundation of TLS.
2. **Digital signatures provide authenticity and non-repudiation** — proving *who* created something (a
   certificate, a token, a signed artifact) in a way that anyone can verify with the public key but only the
   holder of the private key can produce.
3. **Public/private key pairs are everywhere in cloud** — SSH access, TLS certificates, JWT verification, KMS
   asymmetric keys, artifact signing (Sigstore/cosign — Chapter 113), and IAM's underlying trust.
4. **Forward secrecy** protects past communications even if a key is later compromised — a critical property
   you should require of TLS (Chapter 28).

The core idea: **asymmetric cryptography uses a *pair* of mathematically-related keys — a public key (shared
freely) and a private key (kept secret) — where what one key does, only the other can undo. This solves two
problems symmetric crypto cannot: key distribution (agree on a shared symmetric key over an insecure channel
via key exchange like ECDHE, giving forward secrecy) and authenticity (digital signatures — sign with the
private key, verify with the public key, proving who created something). Asymmetric crypto is slow, so it is
used to establish keys and sign, while fast symmetric crypto (Chapter 25) does the bulk data encryption —
the combination that is TLS (Chapter 28).** This chapter completes the cryptographic foundation, and together
with Chapter 25 it underpins PKI (27) and TLS (28).

---

## 2. Prerequisites

- **Chapter 25** (symmetric crypto, the key distribution problem, hashes/MACs, correct-usage rules, CSPRNG) —
  this chapter solves the problem Chapter 25 posed and builds on its primitives.
- Chapter 7 (bytes/encoding — keys and signatures are byte strings, often Base64/hex/PEM-encoded).
- Forward: Chapter 27 (PKI — signatures + trust chains), Chapter 28 (TLS — key exchange + certificates
  combined), Chapter 60 (JWT signing), Chapter 30 (SSH keys).

---

## 3. Mental Model

**Asymmetric crypto uses a key *pair*: a public key you share freely and a private key you keep secret, where
the two are mathematically linked so that what one does only the other can undo. This gives two capabilities
symmetric crypto lacks: (1) key exchange — two parties agree on a shared symmetric key over an insecure
channel (Diffie-Hellman/ECDHE), and (2) digital signatures — sign with the private key, anyone verifies with
the public key (authenticity + non-repudiation). Asymmetric is slow, so it establishes keys and signs; fast
symmetric crypto does the bulk work.**

```
   THE KEY PAIR:  private key (SECRET, kept by owner) + public key (SHARED freely)
     - What the PRIVATE key does, the PUBLIC key verifies/undoes, and vice versa.

   TWO CAPABILITIES:

   1. KEY EXCHANGE (solve key distribution — Chapter 25's problem):
        Two parties, over an INSECURE channel, agree on a shared SYMMETRIC key that an eavesdropper
        cannot compute (Diffie-Hellman / ECDHE). -> They now have a shared key for fast symmetric encryption.
        With EPHEMERAL keys (ECDHE) -> FORWARD SECRECY (past sessions safe even if a long-term key leaks).

   2. DIGITAL SIGNATURES (authenticity + non-repudiation):
        Owner SIGNS a message with their PRIVATE key -> anyone VERIFIES with the PUBLIC key.
        Proves: the message came from the private-key holder (authenticity) and wasn't altered (integrity),
                and the signer cannot deny it (non-repudiation).

   ASYMMETRIC IS SLOW -> use it to establish keys and sign; use fast SYMMETRIC (Ch25) for bulk data. = TLS (Ch28)
```

Three ideas:

1. **The key pair asymmetry solves distribution.** Because the public key can be shared freely (no secret to
   distribute) while the private key stays secret, two parties can use public-key techniques to agree on a
   shared symmetric key over an insecure channel without an eavesdropper learning it — solving Chapter 25's
   key distribution problem. This is the foundation of TLS.
2. **Signatures provide authenticity that MACs cannot at scale.** A MAC (Chapter 25) proves authenticity but
   requires a *shared* key (both parties have it, so either could have produced the tag — no non-repudiation,
   and it doesn't scale to strangers). A *signature* uses the *private* key (only the owner has it), verified
   by the *public* key (anyone can verify) — so it proves *who specifically* signed (non-repudiation) and
   works between parties who have never shared a secret (the basis of certificates — Chapter 27).
3. **Asymmetric is slow; combine with symmetric.** Public-key operations are far slower than symmetric ones,
   so they are used sparingly — to *establish* a shared symmetric key (key exchange) and to *sign* (small
   digests) — while fast symmetric AEAD (Chapter 25) does the bulk data encryption. TLS (Chapter 28) is
   exactly this combination: asymmetric to set up, symmetric to transfer.

**The security framing:** asymmetric cryptography completes the toolkit by solving what symmetric cannot —
key distribution (via key exchange, with forward secrecy) and scalable authenticity (via signatures, the
basis of PKI). It is slow, so it partners with symmetric crypto: establish keys and authenticate with
asymmetric, transfer data with symmetric. This partnership is the architecture of TLS (Chapter 28), and the
signature capability is the architecture of PKI/certificates (Chapter 27), JWTs (Chapter 60), and artifact
signing (Chapter 113). The correct-usage rules from Chapter 25 still apply (never roll your own; use vetted
libraries; protect the private key absolutely).

---

## 4. Fundamentals

### 4.1 Public and private keys

Asymmetric cryptography is built on a **key pair** of mathematically-related keys:

```
   PRIVATE key: kept SECRET by the owner. Used to DECRYPT (in encryption schemes) or to SIGN.
   PUBLIC key:  shared FREELY (published, in certificates, etc.). Used to ENCRYPT (to the owner) or to VERIFY.
   The relationship: derived from hard mathematical problems (factoring for RSA; elliptic-curve discrete log
     for ECC), such that knowing the public key does NOT let you compute the private key.
```

Two algorithm families:

- **RSA:** based on the difficulty of factoring large numbers. Widely used, well-understood; keys are large
  (2048-bit minimum, 3072/4096 for higher security) and operations are slower. Used for signatures and (less
  now) key transport.
- **ECC (Elliptic Curve Cryptography):** based on the elliptic-curve discrete-log problem. **Smaller keys for
  equivalent security** (a 256-bit ECC key ≈ a 3072-bit RSA key) and faster — the modern preference. Curves:
  P-256, P-384, and Ed25519/X25519 (modern, fast, safe curves). ECDSA/EdDSA for signatures, ECDH/ECDHE for
  key exchange.

The absolute rule: **the private key must be protected absolutely** — it is the identity/secret. If the
private key leaks, an attacker can impersonate the owner (sign as them) and decrypt data encrypted to them.
This is why private keys are stored in HSMs/KMS (Chapter 80), protected file permissions (SSH keys — Chapter
30), and never transmitted. Public keys, by contrast, are meant to be shared (that is the point).

### 4.2 Key exchange (solving key distribution) — Diffie-Hellman/ECDHE

The headline capability: **key exchange** lets two parties agree on a shared symmetric key over an insecure
channel without an eavesdropper learning it — solving Chapter 25's key distribution problem. The mechanism is
**Diffie-Hellman (DH)**, in modern form **ECDHE (Elliptic Curve Diffie-Hellman Ephemeral)**:

```
   Diffie-Hellman (conceptually):
     Both parties agree on public parameters. Each generates a private value and derives a public value.
     They exchange PUBLIC values (over the insecure channel — an eavesdropper sees these).
     Each combines their own private value with the other's public value to compute the SAME shared secret.
     -> Both now have a shared secret; the eavesdropper, seeing only the public values, CANNOT compute it
        (the math — discrete log — makes it infeasible).
   The shared secret becomes (via a key derivation function) the symmetric key for fast AEAD (Chapter 25).
```

Two critical properties:

- **It solves key distribution:** two parties who have never shared a secret establish one over an insecure
  channel. This is what makes TLS possible (Chapter 28) — your browser and a server you've never contacted
  agree on a symmetric key an eavesdropper cannot learn.
- **Ephemeral (ECDHE) gives forward secrecy** (§4.5): if each session uses a fresh, ephemeral DH key pair
  (discarded after), then compromising a long-term key later does *not* let an attacker decrypt past
  sessions — a critical property.

**Note:** plain DH/ECDHE provides key agreement but *not authentication* — an active MITM could do a
DH exchange with each side separately (a man-in-the-middle of the key exchange). So key exchange must be
*authenticated* — combined with signatures/certificates (§4.3, Chapter 27) proving you exchanged keys with
the *right* party. TLS (Chapter 28) authenticates the ECDHE with the server's certificate.

### 4.3 Digital signatures (authenticity + non-repudiation)

The second capability: **digital signatures** prove who created a message and that it wasn't altered:

```
   SIGNING:   signature = Sign(private_key, hash(message))    -- the owner signs (with their PRIVATE key)
   VERIFYING: Verify(public_key, message, signature) -> valid/invalid   -- anyone verifies (with the PUBLIC key)

   Provides:
     - AUTHENTICITY: the message came from the holder of the private key (only they could sign)
     - INTEGRITY: the message wasn't altered (the hash would differ)
     - NON-REPUDIATION: the signer cannot deny signing (only they have the private key) — unlike a MAC
   Algorithms: RSA signatures (RS256), ECDSA (ES256), EdDSA (Ed25519).
   Note: you sign the HASH of the message (efficient; the hash represents the message — Chapter 25 §4.5).
```

The key distinction from a MAC (Chapter 25 §4.6):

- **A MAC uses a *shared* key** — both parties have it, so either could have produced the tag. It proves the
  message came from *someone with the key* but not *which one* (no non-repudiation), and requires a shared
  secret (doesn't scale to strangers).
- **A signature uses the *private* key** — only the owner has it, verified by the *public* key anyone can
  have. It proves the message came from *that specific owner* (non-repudiation) and works between parties who
  never shared a secret. This is why **certificates** (Chapter 27) use signatures: a CA signs a certificate
  with its private key, and anyone can verify it with the CA's public key, establishing trust at scale.

Signatures are the foundation of: **PKI/certificates** (Chapter 27 — a CA signs certificates), **JWTs**
(Chapter 60 — RS256/ES256 asymmetric signing, where the issuer signs and services verify with the public key
without sharing a secret), **software/artifact signing** (Chapter 113 — Sigstore/cosign), **code/commit
signing**, and **DNSSEC** (Chapter 17). The pattern — sign with private, verify with public, non-repudiation,
scales to strangers — is why asymmetric signatures are ubiquitous for authenticity at scale.

### 4.4 Asymmetric encryption (and why it's used sparingly)

Asymmetric crypto *can* encrypt directly (encrypt with the recipient's public key, only they can decrypt with
their private key), but it is used sparingly:

```
   Encrypt with recipient's PUBLIC key -> only the recipient's PRIVATE key can decrypt.
   -> Anyone can send an encrypted message to the owner without a pre-shared key.
   BUT: asymmetric encryption is SLOW and limited in the data size it can encrypt.
   -> HYBRID ENCRYPTION: encrypt the data with a fast symmetric key (AEAD), then encrypt just the
      symmetric key with the recipient's public key. (The efficient, standard pattern — e.g. KMS envelope
      encryption, Chapter 80; PGP; older TLS key transport.)
```

The practical reality: **direct asymmetric encryption is rare; hybrid encryption is the norm** — use
asymmetric to protect a symmetric key, then symmetric AEAD for the data (§3's slow-establish/fast-transfer
pattern). KMS envelope encryption (Chapter 80) is exactly this: data encrypted with a data key (symmetric
AEAD), the data key encrypted with a KMS key (asymmetric or symmetric master key). Modern TLS (Chapter 28)
actually prefers *key exchange* (ECDHE, §4.2) over key transport (asymmetric encryption of a key), because
key exchange provides forward secrecy — but the hybrid principle (asymmetric to establish, symmetric to
transfer) holds.

### 4.5 Forward secrecy (protecting the past)

**Forward secrecy (FS/PFS — Perfect Forward Secrecy)** is a critical property: past communications stay
secure even if a long-term private key is later compromised:

```
   WITHOUT forward secrecy (e.g. RSA key transport):
     The session key is encrypted with the server's long-term RSA key.
     An attacker who RECORDS the encrypted traffic now, and LATER steals the server's private key, can
     decrypt ALL the recorded past sessions. -> "harvest now, decrypt later."

   WITH forward secrecy (ECDHE — ephemeral key exchange):
     Each session uses a FRESH, EPHEMERAL DH key pair, discarded after the session.
     The session key is never encrypted with a long-term key; it's derived from ephemeral values.
     -> Stealing the long-term key later does NOT help decrypt past recorded sessions (the ephemeral keys
        are gone). Each session is independently protected.
```

Forward secrecy defeats the "harvest now, decrypt later" attack (an adversary — e.g. a nation-state —
records encrypted traffic hoping to decrypt it later by stealing keys or via future cryptanalysis). It is
provided by **ephemeral key exchange (ECDHE)**, which is why modern TLS (1.3 — Chapter 28) *requires* forward
secrecy (only ECDHE, no RSA key transport). You should **require forward secrecy** in TLS configuration — it
is a critical property, especially against powerful adversaries and for long-lived data confidentiality. This
is a concrete, checkable TLS configuration requirement (Chapter 28).

### 4.6 Post-quantum cryptography (the horizon)

A forward-looking note: **quantum computers, if built at scale, would break current asymmetric crypto** (RSA
and ECC — Shor's algorithm efficiently factors and solves discrete logs), though not symmetric crypto/hashes
significantly (Grover's algorithm only halves their effective strength, addressed by larger keys). This
motivates **post-quantum cryptography (PQC)** — new asymmetric algorithms (lattice-based, e.g. ML-KEM/Kyber
for key exchange, ML-DSA/Dilithium for signatures) resistant to quantum attacks, now being standardized
(NIST) and beginning to deploy (TLS is adding hybrid PQC key exchange). The security relevance now:

- **"Harvest now, decrypt later" makes PQC urgent for long-lived confidentiality** — data encrypted today
  with ECDHE could be decrypted by a future quantum computer if recorded now, so highly-sensitive long-lived
  data is a reason to adopt PQC (or hybrid) key exchange sooner.
- **The migration is coming** — cloud providers and TLS are adding PQC/hybrid modes; a cloud security
  engineer should be aware of crypto-agility (the ability to swap algorithms) and the PQC transition.

You do not need PQC depth now, but awareness that current asymmetric crypto is quantum-vulnerable
(motivating forward secrecy + eventual PQC migration) is part of a modern crypto understanding.

---

## 5. Deep Technical Explanation: Asymmetric Crypto Completes the Toolkit

Asymmetric cryptography's role is best understood as *completing* the cryptographic toolkit by solving the two
problems symmetric crypto (Chapter 25) fundamentally cannot — and then partnering with symmetric crypto for
efficiency. This partnership *is* the architecture of secure communication.

**Problem 1 it solves — key distribution (the enabler of TLS):** symmetric crypto needs both parties to have
the same secret key, but there is no way, using symmetric crypto alone, to get that key to both parties over
an insecure channel without an eavesdropper capturing it (you'd need a secure channel to establish the secure
channel — a chicken-and-egg problem). Asymmetric **key exchange (Diffie-Hellman/ECDHE)** breaks this: because
the *public* values can be exchanged openly (no secret to protect) while each party keeps a private value,
they compute a shared secret an eavesdropper cannot, over the insecure channel itself. This is arguably the
most important idea in applied cryptography — it is what makes encrypted communication between strangers (your
browser and any website) possible, and it is the foundation of TLS (Chapter 28). Combined with ephemeral keys
(ECDHE), it also provides **forward secrecy** (§4.5), protecting the past.

**Problem 2 it solves — scalable authenticity (the enabler of PKI):** a MAC (Chapter 25) proves authenticity
but needs a *shared* secret, so it doesn't scale (you can't share a secret with every party in advance) and
provides no non-repudiation (both holders could produce the tag). Asymmetric **signatures** break this: the
private key (only the owner has it) signs, and the public key (anyone can have it) verifies — proving *which
specific owner* signed (non-repudiation) and working between parties who never shared a secret. This scales
authenticity to the whole internet: a **Certificate Authority** signs certificates with its private key, and
everyone (whose software has the CA's public key) can verify them — the trust model of PKI (Chapter 27) and
thus of TLS server authentication, JWT verification (Chapter 60), and artifact signing (Chapter 113).

**The partnership with symmetric crypto (the efficiency architecture):** asymmetric operations are orders of
magnitude slower than symmetric ones, so asymmetric crypto is used *sparingly* — only to establish keys (key
exchange) and to sign (small hashes) — while fast symmetric AEAD (Chapter 25) does the bulk data encryption.
This is the universal pattern:

- **TLS (Chapter 28):** asymmetric (ECDHE key exchange + certificate signature verification) to authenticate
  and establish a shared symmetric key, then fast symmetric AEAD (AES-GCM/ChaCha20-Poly1305) for all the data.
- **Hybrid encryption / KMS envelope encryption (Chapter 80):** asymmetric (or a symmetric master key) to
  protect a symmetric data key, then symmetric AEAD for the data.
- **Signed-then-symmetric-transferred:** sign with asymmetric (authenticity), transfer with symmetric.

The unifying insight: **asymmetric cryptography completes the toolkit by solving key distribution (via key
exchange — enabling encrypted communication between strangers, with forward secrecy) and scalable
authenticity (via signatures — enabling PKI and trust at scale, with non-repudiation), and it partners with
fast symmetric crypto (asymmetric to establish/authenticate, symmetric to transfer) — this partnership being
the architecture of TLS, hybrid encryption, and every secure channel.** The private key is the crown jewel
(protect it absolutely — HSM/KMS); forward secrecy protects the past (require it); and the whole thing must
be *authenticated* (key exchange alone is MITM-able — it needs signatures/certificates to prove you're
exchanging with the right party, which is Chapter 27's PKI). The correct-usage humility from Chapter 25 still
governs: use vetted libraries, protect private keys, require forward secrecy, and let managed services (KMS)
handle key management.

---

## 6. Internals: Working with Asymmetric Keys

### 6.1 Generate and inspect key pairs

```bash
# Generate an ECC key pair (modern, preferred — smaller/faster than RSA):
$ openssl ecparam -name prime256v1 -genkey -noout -out private.pem    # P-256 private key (SECRET!)
$ openssl ec -in private.pem -pubout -out public.pem                   # derive the public key (shareable)
$ chmod 600 private.pem                                                 # protect the private key (§4.1)

# Or Ed25519 (modern, fast, safe):
$ openssl genpkey -algorithm ed25519 -out ed_private.pem
$ openssl pkey -in ed_private.pem -pubout -out ed_public.pem

# RSA (still common; larger):
$ openssl genrsa -out rsa_private.pem 3072                              # 3072-bit RSA private key
$ openssl rsa -in rsa_private.pem -pubout -out rsa_public.pem

# Inspect:
$ openssl pkey -in private.pem -text -noout | head                     # key details
```

Note: the private key is `chmod 600` (owner-only — §4.1); the public key is shareable. ECC (P-256/Ed25519) is
smaller and faster than RSA for equivalent security (§4.1) — the modern preference.

### 6.2 Sign and verify

```bash
# Sign a file with the private key, verify with the public key (§4.3):
$ echo "important message" > message.txt
$ openssl dgst -sha256 -sign private.pem -out message.sig message.txt   # SIGN (private key)
$ openssl dgst -sha256 -verify public.pem -signature message.sig message.txt   # VERIFY (public key)
Verified OK
# Tamper with the message -> verification fails (integrity + authenticity):
$ echo "tampered" >> message.txt
$ openssl dgst -sha256 -verify public.pem -signature message.sig message.txt
Verification Failure
```

This demonstrates the signature capability (§4.3): sign with private, verify with public; tampering is
detected; only the private-key holder could produce a valid signature (authenticity + non-repudiation).

### 6.3 Key exchange (ECDHE) conceptually

```bash
# Diffie-Hellman key agreement (each party derives the same shared secret from their private + the other's public):
$ openssl ecparam -name prime256v1 -genkey -noout -out alice_priv.pem
$ openssl ec -in alice_priv.pem -pubout -out alice_pub.pem
$ openssl ecparam -name prime256v1 -genkey -noout -out bob_priv.pem
$ openssl ec -in bob_priv.pem -pubout -out bob_pub.pem
# Alice computes the shared secret from HER private + BOB's public:
$ openssl pkeyutl -derive -inkey alice_priv.pem -peerkey bob_pub.pem -out alice_shared.bin
# Bob computes the SAME shared secret from HIS private + ALICE's public:
$ openssl pkeyutl -derive -inkey bob_priv.pem -peerkey alice_pub.pem -out bob_shared.bin
$ diff alice_shared.bin bob_shared.bin && echo "SAME shared secret (key exchange works)"
```

Both parties derive the *same* shared secret from their own private key and the other's public key, without
transmitting the secret — solving key distribution (§4.2). With ephemeral keys per session, this gives
forward secrecy (§4.5). (The shared secret is then run through a KDF to produce the symmetric key.)

### 6.4 Verify TLS forward secrecy and key exchange

```bash
# Check a server's TLS uses ECDHE (forward secrecy — §4.5) and inspect its certificate (signed — §4.3):
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
    grep -E 'Cipher|Server Temp Key|Protocol'
#   "Server Temp Key: ECDH ..." -> ECDHE in use -> forward secrecy (good)
#   "Cipher: ...GCM..." -> AEAD symmetric cipher for the data (Chapter 25)
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
    openssl x509 -noout -text | grep -E 'Signature Algorithm|Public Key'   # the cert's signature + key
```

The `Server Temp Key: ECDH` confirms forward secrecy (ECDHE key exchange — §4.5); the cipher (AES-GCM) is the
symmetric AEAD for the data (Chapter 25) — the asymmetric-establishes/symmetric-transfers partnership (§5)
visible in one command. Requiring ECDHE (forward secrecy) is a checkable TLS config item (Chapter 28).

---

## 7. Real-World Example: Asymmetric Crypto in the Ledger System

**Where Ledger uses asymmetric cryptography:**

- **TLS (Chapters 4, 28):** every TLS connection uses **ECDHE key exchange** (asymmetric — §4.2) to establish
  a shared symmetric key (with **forward secrecy** — §4.5), authenticated by the server's **certificate**
  (whose signature — §4.3 — Ledger verifies via PKI, Chapter 27), then fast symmetric AEAD (Chapter 25) for
  the data. This is the asymmetric-establishes/symmetric-transfers partnership (§5).
- **Certificates (PKI — Chapter 27):** Ledger's TLS certificates are **signed by a CA** (asymmetric signature
  — §4.3); browsers/clients verify the signature with the CA's public key. Ledger protects its certificate
  *private keys* absolutely (in ACM/KMS — §4.1, Chapter 80).
- **JWT signing (Chapter 60):** Ledger's JWTs can use **asymmetric signing (RS256/ES256 — §4.3)** where the
  issuer signs with a private key and *services verify with the public key* — so services need only the
  public key (no shared secret to distribute to every service), a key advantage of asymmetric over HMAC
  (shared-secret) signing for a distributed system.
- **SSH access (Chapter 30):** engineers access hosts with **SSH key pairs** (asymmetric — §4.1); the public
  key is on the server, the private key stays with the engineer (protected — §4.1).
- **KMS envelope encryption (Chapter 80):** at-rest encryption uses **hybrid encryption** (§4.4) — a
  symmetric data key encrypted by a KMS key; KMS can use asymmetric keys for signing/encryption operations.
- **Artifact/image signing (Chapter 113):** Ledger signs container images/artifacts (Sigstore/cosign) with
  **asymmetric signatures** (§4.3), verified in the pipeline/at admission (Chapter 105) — proving provenance.
- **Forward secrecy requirement (§4.5):** Ledger requires ECDHE in its TLS configuration so past sessions are
  safe even if a key later leaks — a checkable config item (Chapter 28).

The asymmetric capabilities Ledger relies on: key exchange (TLS, with forward secrecy), signatures (certs,
JWTs, artifacts, SSH), and hybrid encryption (KMS) — all with private keys protected absolutely (KMS/ACM/file
permissions) and forward secrecy required. The partnership with symmetric crypto (Chapter 25) is everywhere:
asymmetric establishes/authenticates, symmetric transfers.

The Ledger takeaway: **asymmetric cryptography solves key distribution (TLS key exchange with forward
secrecy) and provides scalable authenticity (certificate/JWT/artifact/SSH signatures) for Ledger, partnering
with fast symmetric crypto (asymmetric establishes and authenticates, symmetric transfers) — the architecture
of TLS (Chapter 28) and PKI (Chapter 27) — with private keys protected absolutely (KMS/ACM/file permissions,
Chapter 80) and forward secrecy required.** This completes the cryptographic foundation for the PKI and TLS
chapters that follow.

---

## 8. Hands-On Demonstration

### LAB 26.1 — Asymmetric Keys, Signatures, and Key Exchange

**Objective.** Generate key pairs, sign and verify (authenticity/non-repudiation), perform a Diffie-Hellman
key exchange (solving key distribution), verify TLS forward secrecy, and understand the
asymmetric-establishes/symmetric-transfers partnership.

**Cost.** Free. **Environment.** ENV-1 (openssl). **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Generate a key pair and inspect.*

```bash
mkdir -p ~/lab26 && cd ~/lab26
openssl ecparam -name prime256v1 -genkey -noout -out private.pem   # P-256 private (secret)
openssl ec -in private.pem -pubout -out public.pem                  # public (shareable)
chmod 600 private.pem                                               # protect the private key (§4.1)
ls -l private.pem public.pem                                        # note the private key is 600
openssl pkey -in private.pem -text -noout | head                    # inspect
```

*Step 2 — Sign and verify (authenticity, non-repudiation, tamper detection).*

```bash
echo "transfer approved by CFO" > doc.txt
openssl dgst -sha256 -sign private.pem -out doc.sig doc.txt         # SIGN with private (§4.3)
openssl dgst -sha256 -verify public.pem -signature doc.sig doc.txt  # VERIFY with public -> Verified OK
# Tamper -> verification fails:
echo " (altered)" >> doc.txt
openssl dgst -sha256 -verify public.pem -signature doc.sig doc.txt  # -> Verification Failure
```

**Expected:** valid signature verifies; tampering is detected. Only the private-key holder could sign
(authenticity + non-repudiation); anyone with the public key can verify (§4.3).

*Step 3 — Key exchange (solving key distribution).*

```bash
# Two parties derive the SAME shared secret over an insecure channel (§4.2):
openssl ecparam -name prime256v1 -genkey -noout -out alice.pem; openssl ec -in alice.pem -pubout -out alice_pub.pem
openssl ecparam -name prime256v1 -genkey -noout -out bob.pem;   openssl ec -in bob.pem -pubout -out bob_pub.pem
openssl pkeyutl -derive -inkey alice.pem -peerkey bob_pub.pem -out alice_shared.bin   # Alice: her priv + Bob's pub
openssl pkeyutl -derive -inkey bob.pem -peerkey alice_pub.pem -out bob_shared.bin     # Bob: his priv + Alice's pub
diff alice_shared.bin bob_shared.bin && echo "SAME shared secret -> key distribution solved (no secret transmitted)"
```

**Expected:** Alice and Bob derive the identical shared secret from their own private key and the other's
public key, without transmitting the secret — solving Chapter 25's key distribution problem (§4.2). This
shared secret becomes the symmetric key for fast AEAD.

*Step 4 — Verify TLS forward secrecy (the partnership in action).*

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
  grep -E 'Protocol|Cipher|Server Temp Key'
# "Server Temp Key: ECDH ..." = ECDHE = forward secrecy (§4.5); "Cipher: ...GCM" = symmetric AEAD for data.
```

**Expected:** `Server Temp Key: ECDH` (forward secrecy via ECDHE — §4.5) and an AEAD cipher (symmetric,
Chapter 25) — the asymmetric-establishes/symmetric-transfers partnership (§5) visible in one connection.

**Security implications.** Write down: (a) asymmetric solves key distribution (key exchange — §4.2) and
scalable authenticity (signatures — §4.3, non-repudiation, scales to strangers, unlike a MAC); (b) the
private key is the crown jewel (protect absolutely — §4.1); (c) forward secrecy (ECDHE) protects past
sessions (require it — §4.5); (d) asymmetric is slow → partners with fast symmetric (asymmetric
establishes/authenticates, symmetric transfers — §5); (e) key exchange must be *authenticated* (certificates
— Chapter 27) or it's MITM-able.

**Cleanup.**
```bash
cd ~ && rm -rf ~/lab26
```

---

## 9. Security Implications

- **Asymmetric cryptography solves the two problems symmetric cannot** (Chapter 25): **key distribution**
  (via key exchange — Diffie-Hellman/ECDHE, enabling a shared symmetric key over an insecure channel between
  strangers) and **scalable authenticity** (via signatures — sign with private, verify with public,
  non-repudiation, scaling to parties who never shared a secret).
- **Signatures differ from MACs** (Chapter 25): a MAC uses a *shared* key (no non-repudiation, doesn't scale
  to strangers); a signature uses the *private* key verified by the *public* key (non-repudiation, scales) —
  which is why **certificates (PKI — Chapter 27), JWTs (Chapter 60), and artifact signing (Chapter 113)** use
  signatures.
- **Asymmetric is slow → partner with symmetric** (§5): use asymmetric to *establish* keys (key exchange) and
  *sign*, fast symmetric AEAD to *transfer* data. This partnership is the architecture of **TLS** (Chapter
  28), **hybrid/envelope encryption** (KMS — Chapter 80), and every secure channel.
- **The private key is the crown jewel** — protect it absolutely (HSM/KMS — Chapter 80, file permissions —
  SSH Chapter 30); its leak means impersonation and decryption. Public keys are shared freely.
- **Forward secrecy (ECDHE) protects the past** — require it in TLS (Chapter 28); it defeats "harvest now,
  decrypt later" (recording traffic to decrypt after stealing a key).
- **Key exchange must be authenticated** — plain DH/ECDHE is MITM-able; it must be combined with signatures/
  certificates (Chapter 27) to prove you exchanged keys with the *right* party.
- **Post-quantum crypto is on the horizon** — current asymmetric crypto (RSA/ECC) is quantum-vulnerable,
  making forward secrecy and eventual PQC migration relevant for long-lived confidentiality ("harvest now,
  decrypt later").

---

## 10. Attack Scenarios

1. **Private key compromise** (§4.1): a leaked private key lets an attacker impersonate the owner (sign as
   them, obtain certificates) and decrypt data encrypted to them. Defense: protect private keys absolutely
   (HSM/KMS, file permissions); rotate; revoke (Chapter 27).
2. **MITM of unauthenticated key exchange** (§4.2): an active attacker does a DH exchange with each side
   separately, MITM-ing the channel. Defense: authenticate the key exchange with signatures/certificates
   (Chapter 27, 28).
3. **"Harvest now, decrypt later"** (§4.5, §4.6): record encrypted traffic now, decrypt later by stealing a
   key (no forward secrecy) or via future quantum computers. Defense: forward secrecy (ECDHE); PQC for
   long-lived data.
4. **Weak keys / weak algorithms** (§4.1): too-small RSA keys (< 2048), broken curves, or old algorithms.
   Defense: current key sizes/curves (RSA 3072+, P-256/Ed25519); avoid deprecated ones.
5. **Signature verification bugs** (§4.3, Chapter 60): failing to verify a signature, accepting "none"
   algorithm (the JWT alg-confusion attack — Chapter 60), or key confusion (RS256 vs HS256). Defense:
   verify correctly with the right key/algorithm; use vetted libraries.
6. **Weak randomness in key generation** (Chapter 25 §4.8): predictable private keys from a weak RNG.
   Defense: CSPRNG for key generation.
7. **Quantum threat (future)** (§4.6): quantum computers breaking RSA/ECC. Defense: crypto-agility, PQC
   migration.

---

## 11. Defensive Techniques

- **Protect private keys absolutely** — store in HSMs/KMS (Chapter 80), use strict file permissions (SSH keys
  — Chapter 30), never transmit them, rotate them, and have a revocation plan (Chapter 27). The private key
  is the identity/secret.
- **Require forward secrecy (ECDHE)** in TLS configuration (Chapter 28) — protects past sessions against key
  compromise and "harvest now, decrypt later." A checkable config item (§6.4).
- **Authenticate key exchanges** — plain DH/ECDHE is MITM-able; combine with certificate-based
  authentication (PKI — Chapter 27, TLS — Chapter 28) to prove the peer's identity.
- **Use current algorithms and key sizes** — ECC (P-256/Ed25519) preferred (smaller/faster); RSA 3072+ if
  used; avoid weak keys, broken curves, and deprecated algorithms.
- **Verify signatures correctly** — with the right public key and algorithm; reject "none"/algorithm
  confusion (Chapter 60); use vetted libraries. Prefer asymmetric signing (public-key verification) for
  distributed verification (JWTs, artifacts — Chapters 60, 113).
- **Use hybrid encryption / managed key management** — asymmetric to protect a symmetric key, symmetric AEAD
  for data (§4.4); rely on KMS envelope encryption (Chapter 80) rather than rolling your own.
- **Use a CSPRNG for key generation** (Chapter 25 §4.8) — predictable keys are a total break.
- **Plan for crypto-agility and PQC** — be able to swap algorithms; track the post-quantum transition,
  especially for long-lived sensitive data (§4.6).
- **Never roll your own** (Chapter 25 §5) — use vetted libraries and managed services for all asymmetric
  operations.

---

## 12. Production Architecture

Asymmetric crypto in production, and how it partners with symmetric crypto and managed services:

```
 USE                      ASYMMETRIC ROLE                   SYMMETRIC PARTNER (Ch25)   SYSTEM B (AWS)
 ---------------------    ------------------------------    -----------------------    -------------------------
 TLS (Chapter 28)         ECDHE key exchange + cert verify  AEAD for the data          ACM certs + TLS (managed)
 certificates (Ch27)      CA signs / clients verify         n/a                        ACM / private CA (Ch27)
 JWT signing (Ch60)       RS256/ES256 (sign/verify pub)     (or HMAC shared-secret)    app + KMS asymmetric keys
 at-rest (envelope, Ch80) protect the data key              AEAD data key              KMS envelope encryption
 SSH (Chapter 30)         key-pair auth                     (session AEAD)             SSH keys / SSM
 artifact signing (Ch113) sign/verify provenance            n/a                        Sigstore/cosign + KMS
 key management           (the crown jewel)                 (data keys)                KMS / CloudHSM (managed)
 forward secrecy          ECDHE (require it)                per-session AEAD keys       enforced in TLS config
```

The architectural principle: **asymmetric cryptography completes the toolkit — solving key distribution (key
exchange, with forward secrecy) and scalable authenticity (signatures, with non-repudiation) — and partners
with fast symmetric crypto (asymmetric establishes/authenticates, symmetric transfers), which is the
architecture of TLS, envelope encryption, and every secure channel; with private keys protected absolutely by
managed services (KMS/CloudHSM/ACM) and forward secrecy required.** The cloud security engineer's job is
correct selection and integration — require forward secrecy, protect private keys in KMS, verify signatures
correctly, use current algorithms, and rely on managed services for key management — not implementation
(never roll your own). Together with Chapter 25 (symmetric) and the correct-usage discipline, this completes
the cryptographic foundation for PKI (Chapter 27) and TLS (Chapter 28), which combine key exchange +
certificates + symmetric AEAD into the secure channels everything else depends on.

---

## 13. Common Mistakes

1. **Leaking/mishandling private keys** — the crown jewel; protect absolutely (KMS/HSM/file permissions).
2. **No forward secrecy** — using RSA key transport instead of ECDHE, exposing past sessions to "harvest
   now, decrypt later" (§4.5); require ECDHE.
3. **Unauthenticated key exchange** — plain DH/ECDHE without certificate authentication is MITM-able (§4.2).
4. **Weak keys/algorithms** — too-small RSA, broken curves, deprecated algorithms.
5. **Signature verification bugs** — not verifying, accepting "none"/alg confusion (Chapter 60), wrong key.
6. **Confusing MAC and signature** — using a shared-secret MAC where non-repudiation/public verification is
   needed (or vice versa) (§4.3).
7. **Direct asymmetric encryption of large data** — slow/limited; use hybrid encryption (§4.4).
8. **Weak RNG for key generation** — predictable keys (Chapter 25 §4.8).
9. **Rolling your own** — use vetted libraries/managed services (Chapter 25 §5).
10. **Ignoring the PQC horizon** for long-lived sensitive data (§4.6).

---

## 14. Troubleshooting

| Symptom / concern | Issue | Fix |
|---|---|---|
| Need to establish a key with a stranger | key distribution | asymmetric key exchange (ECDHE) — §4.2 |
| Need to prove who signed something (verifiable by anyone) | authenticity/non-repudiation | asymmetric signature (not a MAC) — §4.3 |
| Need past sessions safe if a key leaks | no forward secrecy | require ECDHE — §4.5, §6.4 |
| TLS not using forward secrecy | RSA key transport / no ECDHE | configure ECDHE ciphersuites (Chapter 28); check "Server Temp Key" |
| Suspected MITM of key exchange | unauthenticated exchange | authenticate with certificates (Chapter 27) |
| JWT signature accepted when it shouldn't be | alg confusion / "none" | verify with the right algorithm/key; vetted library (Chapter 60) |
| Private key exposure risk | key stored insecurely | move to KMS/HSM; file permissions; rotate (Chapter 80) |
| Long-lived data confidentiality vs future quantum | harvest-now-decrypt-later | forward secrecy now; plan PQC migration (§4.6) |

---

## 15. Practical Lab

Lab 26.1 is in §8. Register it in the lab index. Extension: build a complete hybrid-encryption scheme by hand
using vetted primitives — generate a symmetric AEAD key, encrypt data with it (Chapter 25), then encrypt the
symmetric key with a recipient's public key (§4.4) — and reverse it, demonstrating the
asymmetric-protects-the-key/symmetric-encrypts-the-data pattern that underlies KMS envelope encryption
(Chapter 80) and TLS (Chapter 28). Then verify a real server's TLS forward secrecy and certificate signature
(§6.4).

---

## 16. Exercises

### Concept questions

**26.1** Explain the two problems asymmetric crypto solves that symmetric cannot, and how each is solved (key
exchange, signatures).

**26.2** Explain the difference between a MAC (Chapter 25) and a digital signature — what each proves, and why
signatures scale and provide non-repudiation.

**26.3** Explain forward secrecy: what it protects, how ECDHE provides it, and what attack it defeats.

**26.4** Explain why asymmetric crypto is used sparingly and how it partners with symmetric crypto (hybrid
encryption / TLS).

**26.5** Explain why key exchange must be authenticated, and what provides that authentication.

### Debugging problems

**26.6** A TLS server does not provide forward secrecy. Explain the risk and the fix.

**26.7** A JWT signed with RS256 is being verified incorrectly (or a "none" algorithm is accepted). Explain
the risk and the correct verification.

**26.8** A private key was committed to a git repository. Explain the impact and the response.

### Security scenarios

**26.9** Design the signing architecture for a distributed system where many services must verify tokens
issued by one authority, without sharing a secret. Explain why asymmetric signing (not HMAC) fits.

**26.10** Explain "harvest now, decrypt later" and how forward secrecy and post-quantum crypto address it for
long-lived sensitive data.

### Architecture questions

**26.11** Explain how asymmetric key exchange + certificate signatures + symmetric AEAD combine into TLS
(bridge to Chapters 27, 28).

**26.12** Explain how KMS envelope encryption uses the hybrid pattern (asymmetric/symmetric partnership) and
why it's used for at-rest encryption (bridge to Chapter 80).

### Hands-on exercises

**26.13** Generate a key pair, sign and verify a document, and demonstrate tamper detection.

**26.14** Perform a Diffie-Hellman key exchange and show both parties derive the same shared secret.

**26.15** Verify a real server's TLS forward secrecy (ECDHE) and inspect its certificate's signature.

### Interview questions

**26.16** "What problem does asymmetric cryptography solve that symmetric can't?"

**26.17** "What's the difference between a MAC and a digital signature?"

**26.18** "What is forward secrecy and why does it matter?"

**26.19** "How does TLS use both asymmetric and symmetric cryptography?"

**26.20** "Why must you protect the private key, and how?"

---

## 17. Summary

- **Asymmetric cryptography uses a key pair** — a **public key** (shared freely) and a **private key** (kept
  secret) — mathematically linked so what one does only the other can undo. It solves the two problems
  symmetric crypto (Chapter 25) cannot.
- **Problem 1: key distribution** — **key exchange (Diffie-Hellman/ECDHE)** lets two parties agree on a
  shared symmetric key over an insecure channel between strangers (an eavesdropper seeing the public values
  cannot compute the secret) — the foundation of TLS (Chapter 28). With **ephemeral keys (ECDHE)** it
  provides **forward secrecy** (§4.5), protecting past sessions against later key compromise ("harvest now,
  decrypt later").
- **Problem 2: scalable authenticity** — **digital signatures** (sign with private, verify with public)
  prove *which specific owner* created something (**non-repudiation**) and scale to parties who never shared a
  secret — unlike a MAC (shared secret, no non-repudiation). This is the basis of **certificates (PKI —
  Chapter 27), JWTs (Chapter 60), and artifact signing (Chapter 113)**.
- **Asymmetric is slow → partner with symmetric** — use asymmetric to *establish* keys (key exchange) and
  *sign*, fast symmetric AEAD (Chapter 25) to *transfer* data. This partnership is the architecture of TLS,
  **hybrid/envelope encryption** (KMS — Chapter 80), and every secure channel.
- **The private key is the crown jewel** — protect it absolutely (HSM/KMS, file permissions); its leak means
  impersonation and decryption. **Require forward secrecy (ECDHE)** in TLS. **Authenticate key exchanges**
  (plain DH is MITM-able — needs certificates).
- **Post-quantum crypto is on the horizon** — current asymmetric crypto (RSA/ECC) is quantum-vulnerable,
  making forward secrecy and eventual PQC migration relevant for long-lived confidentiality. The correct-usage
  humility from Chapter 25 governs: use vetted libraries/managed services, protect private keys, never invent.
  This completes the cryptographic foundation for PKI (Chapter 27) and TLS (Chapter 28).

---

## 18. Knowledge Check

1. What two problems does asymmetric crypto solve, and how? (§3, §4.2, §4.3)
2. How does key exchange solve key distribution? (§4.2)
3. What is the difference between a MAC and a signature? (§4.3)
4. What is forward secrecy, how does ECDHE provide it, and what attack does it defeat? (§4.5)
5. Why is asymmetric crypto used sparingly, and how does it partner with symmetric? (§4.4, §5)
6. Why must key exchange be authenticated? (§4.2, §5)
7. Why is the private key the crown jewel, and how is it protected? (§4.1)
8. Why do certificates/JWTs/artifacts use signatures rather than MACs? (§4.3)
9. What is "harvest now, decrypt later," and what addresses it? (§4.5, §4.6)
10. How do asymmetric and symmetric crypto combine into TLS? (§5)

---

## 19. Further Exploration

- The original Diffie-Hellman paper concept (key agreement over an insecure channel) — the foundational idea.
- "Cryptographic Right Answers" (Chapter 25 ref) for asymmetric choices (Ed25519/X25519, ECDSA/P-256).
- The TLS 1.3 handshake (Chapter 28) — see key exchange (ECDHE) + certificate signatures + symmetric AEAD
  combined; and RFC 8446.
- NIST post-quantum cryptography standardization (ML-KEM/Kyber, ML-DSA/Dilithium) — the PQC horizon (§4.6).
- Practice `openssl` key generation, signing, and ECDH (§6, Lab 26.1); verify real servers' forward secrecy.
- Chapters 27 (PKI — how signatures + trust chains create verifiable identity) and 28 (TLS — the full
  combination) build directly on this; Chapter 60 (JWT) and Chapter 113 (artifact signing) apply signatures.

---

## Solutions

### 26.1
Symmetric crypto (Chapter 25) is fast but has two limitations asymmetric crypto solves: **(1) Key
distribution** — symmetric encryption requires both parties to share the same secret key, but there is no way
using symmetric crypto alone to get that key to both over an insecure channel without an eavesdropper
capturing it (a chicken-and-egg problem). Asymmetric **key exchange (Diffie-Hellman/ECDHE)** solves it:
because the *public* values can be exchanged openly (no secret to protect) while each party keeps a private
value, both compute the *same* shared secret from their own private value and the other's public value, and
an eavesdropper seeing only the public values cannot compute it (the discrete-log math makes it infeasible).
So two strangers establish a shared symmetric key over the insecure channel itself — the foundation of TLS.
**(2) Scalable authenticity** — a MAC proves authenticity but needs a *shared* secret (doesn't scale to
strangers, and provides no non-repudiation since both holders could produce the tag). Asymmetric **digital
signatures** solve it: the owner signs with their *private* key (only they have it), and anyone verifies with
the *public* key — proving *which specific owner* signed (non-repudiation) and working between parties who
never shared a secret. This scales authenticity to the whole internet (certificates, PKI). So asymmetric
crypto completes the toolkit by enabling encrypted communication between strangers (key exchange) and
verifiable identity at scale (signatures), then partners with fast symmetric crypto for the bulk work.

### 26.3
Forward secrecy (also Perfect Forward Secrecy) is the property that past communications remain secure even if
a long-term private key is later compromised. It protects *the past* — recorded encrypted sessions cannot be
decrypted later even if the server's long-term key is stolen. **ECDHE (Elliptic Curve Diffie-Hellman
Ephemeral) provides it** by using a *fresh, ephemeral* key pair for each session's key exchange, discarded
after the session: the session's symmetric key is derived from these ephemeral values and is *never*
encrypted with or derivable from the long-term key. So there is no long-term key that, once stolen, unlocks
past sessions — each session's ephemeral keys are gone, and each session is independently protected. It
**defeats the "harvest now, decrypt later" attack**: an adversary (e.g. a nation-state) records encrypted
traffic now, hoping to decrypt it later by stealing the server's private key (or via future cryptanalysis/
quantum computers). Without forward secrecy (e.g. RSA key transport, where the session key is encrypted with
the long-term key), stealing that key later decrypts all recorded past sessions. With forward secrecy,
stealing the long-term key later yields nothing for past sessions. This is why modern TLS (1.3 — Chapter 28)
*requires* forward secrecy (ECDHE only), and why you should require it in TLS configuration — it is
especially important for long-lived data confidentiality and against powerful adversaries, and it is a
checkable config item ("Server Temp Key: ECDH" in `openssl s_client`).

### 26.9
For a distributed system where many services must verify tokens issued by one authority without sharing a
secret, use **asymmetric signing** (RS256/ES256/EdDSA), not a shared-secret MAC (HMAC/HS256). Design: the
issuing authority holds a **private key** (protected in KMS/HSM — Chapter 80) and *signs* each token with it;
every service holds only the corresponding **public key** and *verifies* the signature with it. Why
asymmetric fits and HMAC does not: (1) **No shared secret to distribute** — with HMAC, every verifying
service would need the *same secret key* the issuer uses to sign, so the secret must be distributed to (and
protected in) every service; any one compromised service leaks the signing secret, letting an attacker *forge*
tokens. With asymmetric signing, services hold only the *public* key (not secret; leaking it lets no one
forge tokens), and only the issuer holds the private signing key — so a compromised verifying service cannot
forge tokens. (2) **Scales to many verifiers and to parties that never coordinated** — new services just need
the public key (published, e.g. via a JWKS endpoint), no secret provisioning. (3) **Non-repudiation** — only
the issuer could have signed. So the architecture is: issuer signs with a KMS-protected private key; services
fetch and cache the public key (JWKS) and verify signatures with it, rejecting "none"/algorithm confusion
(Chapter 60) and using the correct algorithm. This is exactly why production JWT/OIDC systems use asymmetric
signing (RS256/ES256) with a JWKS-published public key (Chapter 60, 61), and why HMAC (shared-secret) signing
is appropriate only for a single service verifying its own tokens, not for distributed verification.

### 26.16
Asymmetric cryptography solves two problems that symmetric cryptography fundamentally cannot: **key
distribution** and **scalable authenticity**. On key distribution: symmetric encryption needs both parties to
have the same secret key, but there's no way, using symmetric crypto alone, to get that shared key to both
parties over an insecure channel (like the internet) without an eavesdropper capturing it — you'd need an
already-secure channel to establish the secure channel. Asymmetric **key exchange (Diffie-Hellman/ECDHE)**
breaks this: the parties exchange *public* values openly (nothing secret to protect) and each combines their
own private value with the other's public value to compute the *same* shared secret, which an eavesdropper
seeing only the public values cannot compute — so two strangers agree on a symmetric key over the insecure
channel itself. This is what makes encrypted communication between any browser and any website (TLS) possible.
On authenticity: a shared-secret MAC can't scale (you can't pre-share a secret with everyone) and gives no
non-repudiation; asymmetric **signatures** let the owner sign with a private key that anyone can verify with
the public key, proving *which* owner signed and scaling to parties who never shared a secret — the basis of
certificates, PKI, and JWT verification. Because asymmetric operations are slow, they're used to *establish*
keys and *sign*, while fast symmetric crypto does the bulk data encryption — the combination that is TLS. In
short: symmetric is fast but can't safely distribute keys or scale authenticity; asymmetric solves both, and
they partner together.

---

*This completes the cryptographic primitives (Chapters 25–26). Next: Chapter 27 — PKI and X.509:
Certificates, CAs, Chains, Revocation, and Certificate Transparency. We combine asymmetric signatures
(this chapter) with a trust hierarchy to answer the question key exchange left open — "how do I know I'm
exchanging keys with the *right* party?" — building the certificate/trust infrastructure that authenticates
TLS (Chapter 28) and underpins identity across the internet.*
