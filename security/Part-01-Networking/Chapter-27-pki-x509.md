# Chapter 27 — PKI and X.509: Certificates, CAs, Chains, Revocation, and Certificate Transparency

---

## 1. Why This Matters

Chapter 26 left a gap: key exchange (ECDHE) lets two parties agree on a shared key over an insecure channel,
but it does not, by itself, prove *who you are exchanging keys with* — an active attacker could MITM the
exchange. **PKI (Public Key Infrastructure)** fills that gap: it is the trust system that binds a public key
to an identity (a domain name, an organization) via signatures from trusted authorities, so you can verify
you are talking to the *right* party. PKI is what makes TLS (Chapter 28) actually secure, and it underpins
identity across the internet.

For a cloud security engineer, PKI matters because:

1. **Certificate management is a core operational responsibility** — issuing, renewing, and revoking TLS
   certificates (ACM, Let's Encrypt), and the #1 preventable outage cause is **expired certificates**.
2. **Certificate validation is where TLS security lives** — if validation is broken (disabled, misconfigured),
   TLS provides encryption but not authentication, and MITM becomes possible (a common, serious bug).
3. **The trust model has failure modes** — CA compromise, mis-issuance, and rogue CAs are real threats, and
   the defenses (CAA — Chapter 16, Certificate Transparency, pinning) are things you configure and monitor.
4. **mTLS and internal PKI** — service-to-service authentication (Chapter 64), workload identity (Chapter 67),
   and Kubernetes/mesh certificates all use PKI, often a private/internal CA you operate.

The core idea: **PKI binds a public key to an identity through a chain of digital signatures (Chapter 26)
anchored in trusted root Certificate Authorities. A certificate is a signed statement "this public key
belongs to this identity"; a client verifies the chain of signatures up to a pre-trusted root, checks the
identity matches and the certificate is valid (dates, not revoked), and thereby trusts the public key — which
authenticates the key exchange (Chapter 26) and makes TLS secure. The trust model has real failure modes (CA
compromise, mis-issuance, expiry) with corresponding defenses (revocation, CAA, Certificate Transparency,
short lifetimes, automation).** PKI is the trust foundation that turns encryption into authenticated,
MITM-resistant communication.

---

## 2. Prerequisites

- **Chapter 26** (asymmetric signatures — the mechanism of certificates; key exchange — what PKI
  authenticates; the "key exchange must be authenticated" note). Chapter 25 (hashes — certificates sign
  hashes).
- Chapter 15 §5 (the bootstrapping trust problem — PKI is the trust-anchor solution) and Chapter 16 §4.3
  (CAA records — a PKI defense).
- Forward: Chapter 28 (TLS — combines PKI + key exchange + symmetric AEAD), Chapters 64, 67 (mTLS, workload
  identity).

---

## 3. Mental Model

**PKI answers the question key exchange left open — "who am I exchanging keys with?" — by binding a public key
to an identity through a chain of signatures anchored in pre-trusted root CAs. A certificate is a signed
statement "this public key belongs to this identity," and you trust it by verifying the signature chain up to
a root your system already trusts.**

```
   THE CHAIN OF TRUST (verify from the certificate UP to a pre-trusted root):

   Root CA (self-signed; its public key is PRE-INSTALLED in your OS/browser trust store — the TRUST ANCHOR)
     | signs
   Intermediate CA (signed by the root)
     | signs
   Server certificate ("this public key belongs to example.com", signed by the intermediate)

   VERIFICATION (what a client does when it receives the server's certificate):
     1. Check the SIGNATURE chain: server cert signed by intermediate, intermediate by root (Chapter 26).
     2. Check the root is in the client's TRUST STORE (pre-trusted — the anchor).
     3. Check the IDENTITY matches (the cert's name = the domain being connected to).
     4. Check VALIDITY (not expired, not before valid date).
     5. Check REVOCATION (not revoked — CRL/OCSP).
     -> If all pass, TRUST the public key -> use it to authenticate the key exchange (Chapter 26) -> TLS secure.
```

Three ideas:

1. **A certificate is a signed identity-to-key binding.** It says "this public key belongs to this identity
   (domain/org)," signed by a CA (Chapter 26 signature). The signature is what makes it trustworthy — anyone
   can verify it with the CA's public key, but only the CA could produce it.
2. **Trust chains to a pre-installed root (the trust anchor).** Your OS/browser ships with a **trust store**
   of root CA public keys (pre-trusted — the solution to the bootstrapping problem from Chapter 15 §5). A
   certificate is trusted if its signature chains up to one of these roots. This is how you can trust a
   certificate for a site you've never visited — the chain leads to a root you already trust.
3. **Validation is multi-step and all steps matter.** Verifying signature chain + trusted root + identity
   match + validity dates + not revoked. Skipping *any* (especially identity match or the whole validation)
   breaks TLS authentication — the common, serious bug of "TLS with validation disabled."

**The security framing:** PKI is the trust infrastructure that binds public keys to identities via signatures
anchored in pre-trusted roots, enabling authentication of parties you've never met — which is what
authenticates key exchange (Chapter 26) and makes TLS (Chapter 28) MITM-resistant (an attacker can't produce
a valid certificate for the real name). Its correctness depends on every validation step, and its trust model
has failure modes (CA compromise, mis-issuance, expiry) addressed by revocation, CAA, Certificate
Transparency, short lifetimes, and automation. PKI is also the bootstrapping-trust solution (Chapter 15 §5)
made concrete: pre-installed root trust anchors let you verify rather than trust-on-first-use.

---

## 4. Fundamentals

### 4.1 Certificates (X.509) — the signed identity-to-key binding

A **certificate** (X.509 format) is a signed document binding a public key to an identity. Its key fields:

```
   Subject: the identity (e.g. CN=example.com, or the Subject Alternative Names — SANs — listing domains)
   Subject Public Key: the public key being bound to this identity (Chapter 26)
   Issuer: the CA that signed this certificate
   Validity: Not Before / Not After (the certificate's lifetime — EXPIRY is the #1 outage cause, §4.6)
   Serial Number: unique per CA (used for revocation)
   Extensions: SANs (the domains covered — modern validation uses SANs, not CN), key usage, etc.
   Signature: the CA's signature over all the above (Chapter 26) -- what makes it trustworthy
```

Key points:

- **The certificate binds the public key to the identity, and the CA's signature vouches for the binding.**
  Anyone with the CA's public key can verify the signature, confirming the CA asserted "this key belongs to
  this identity."
- **Subject Alternative Names (SANs)** list the domain(s) the certificate covers — modern validation checks
  the SANs (the old Common Name / CN is deprecated for name matching). A certificate can cover multiple
  domains (SANs) or a wildcard (`*.example.com`).
- **Validity dates matter operationally** — an expired certificate is rejected by clients, causing outages
  (§4.6); expiry is the most common preventable TLS outage.
- **Encoding:** certificates are typically PEM (Base64 — Chapter 7) or DER (binary), often in `.crt`/`.pem`/
  `.cer` files; the private key (Chapter 26 §4.1 — the crown jewel) is separate and secret.

### 4.2 Certificate Authorities (CAs) and the chain of trust

A **Certificate Authority (CA)** is a trusted entity that issues (signs) certificates. The trust model is
hierarchical:

```
   ROOT CA: self-signed; its public key is PRE-INSTALLED in OS/browser TRUST STORES (the trust anchor).
     Root private keys are kept OFFLINE / in HSMs (extremely protected — a root compromise is catastrophic).
   INTERMEDIATE CA: signed by the root; does the actual issuing (so the root key stays offline/safe).
   END-ENTITY (server) CERTIFICATE: signed by an intermediate; the certificate a server presents.

   The chain: server cert <- intermediate <- root (pre-trusted). A client verifies each signature up to
   the root in its trust store. Servers must send the FULL chain (server cert + intermediates) so the client
   can build it to a trusted root (a common misconfiguration: missing intermediates -> validation fails).
```

Key points:

- **The trust store is the set of pre-trusted roots** — shipped with your OS/browser (managed by the OS/
  browser vendors and CA/Browser Forum standards). Trusting a root means trusting every certificate it (and
  its intermediates) signs — so root inclusion is tightly governed.
- **Roots are kept offline; intermediates do the issuing** — so the root private key (whose compromise would
  be catastrophic, invalidating everything) is maximally protected, while intermediates (revocable if
  compromised) do the day-to-day signing.
- **Servers must send the full chain** (leaf + intermediates) — a common misconfiguration is sending only the
  leaf certificate, so clients that don't have the intermediate cached can't build the chain to a trusted
  root, causing validation failures (works in some browsers that cache/fetch intermediates, fails in others —
  a confusing bug).

### 4.3 Certificate validation (where TLS security lives)

When a client receives a server's certificate (in the TLS handshake — Chapter 28), it **validates** it — and
every step matters:

```
   1. SIGNATURE CHAIN: verify the leaf is signed by an intermediate, the intermediate by a root (Chapter 26).
   2. TRUSTED ROOT: verify the chain terminates at a root in the client's trust store (the anchor).
   3. IDENTITY MATCH: verify the certificate's SANs include the domain being connected to (CRITICAL —
        without this, any valid certificate for ANY domain would be accepted -> MITM).
   4. VALIDITY: verify current time is within Not Before / Not After (not expired).
   5. REVOCATION: verify the certificate is not revoked (CRL/OCSP — §4.4).
   -> All pass -> the public key is trusted -> authenticate the key exchange (Chapter 26) -> TLS secure.
```

The security-critical points:

- **Identity match (step 3) is what prevents MITM.** If a client skips the identity check, an attacker with
  *any* valid certificate (for a domain they control) could MITM a connection to a *different* domain — the
  cert is validly signed, but for the wrong name. Checking the SANs match the connected domain is what ensures
  you're talking to the right party. Skipping it is a classic, serious bug.
- **Disabling validation entirely is catastrophic and common** — code that does "accept all certificates" or
  "skip verification" (e.g. `verify=False`, `InsecureSkipVerify`, disabling cert checks "to make it work")
  turns TLS into encryption-without-authentication, enabling MITM (Chapters 9, 26). This is one of the most
  common serious TLS mistakes (often done to work around a cert error, leaving MITM open permanently).
- **All steps are necessary** — a valid signature from a trusted root for an expired or wrong-name or revoked
  certificate must still be rejected. Vetted TLS libraries do all steps correctly; the bug is usually
  *disabling* or *misconfiguring* them.

### 4.4 Revocation (CRL, OCSP, OCSP stapling)

Certificates have a validity period, but sometimes a certificate must be invalidated *before* expiry (private
key compromised, mis-issued, domain transferred) — **revocation**:

```
   CRL (Certificate Revocation List): the CA publishes a list of revoked certificate serial numbers.
     Clients download and check it. Problem: CRLs get large; clients often don't check reliably.
   OCSP (Online Certificate Status Protocol): the client asks the CA's OCSP responder "is this cert revoked?"
     Problems: latency (an extra round-trip), privacy (the CA sees what you're visiting), and OCSP responders
     can be unavailable -> clients often "soft-fail" (proceed if OCSP is unreachable) -> weak.
   OCSP STAPLING: the SERVER fetches a signed OCSP response and "staples" it to the TLS handshake, so the
     client gets revocation status without contacting the CA (solves latency/privacy). The modern approach.
```

The revocation reality: **revocation is historically weak** — CRLs are unwieldy, OCSP has latency/privacy/
availability problems and clients often soft-fail (proceeding when revocation can't be checked, defeating the
purpose). The industry response has shifted toward **short-lived certificates** (§4.6) — if certificates
expire quickly (e.g. 90 days for Let's Encrypt, moving toward even shorter), revocation matters less (a
compromised cert is valid for a short window). Modern practice: **OCSP stapling** where revocation is checked,
and **short lifetimes + automation** as the primary strategy (so revocation is less relied upon). Knowing that
revocation is weak (soft-fail) is important — you cannot fully rely on revocation to undo a compromised
certificate; short lifetimes and rapid re-issuance are the more reliable approach.

### 4.5 CA compromise, mis-issuance, and Certificate Transparency

The trust model's central risk: **a CA is trusted to issue certificates only to legitimate identity owners,
but CAs can be compromised or make mistakes (mis-issuance)** — issuing a certificate for a domain to the
wrong party, which enables MITM of that domain:

- **CA compromise / mis-issuance:** if a CA is hacked or tricked, it can issue a valid certificate for
  *your* domain to an *attacker* — who can then MITM connections to your domain (the certificate validates
  correctly, because it's genuinely signed by a trusted CA). This has happened (DigiNotar 2011 — a CA
  compromise led to fraudulent Google certificates used to MITM Iranian users; the CA was removed from trust
  stores and went bankrupt).
- **The problem:** any trusted CA can issue a certificate for any domain, so the security depends on *every*
  trusted CA behaving correctly — a large trust surface (hundreds of CAs in a trust store).

Defenses (things you configure/monitor):

- **CAA records (Chapter 16 §4.3):** DNS records specifying *which CAs* may issue certificates for your
  domain — limiting the trust surface (only your chosen CA can issue, reducing mis-issuance risk).
- **Certificate Transparency (CT):** CAs must log every certificate they issue to public, append-only,
  auditable **CT logs**. So any certificate issued for your domain — including a mis-issued/fraudulent one —
  is publicly visible, and you can *monitor* CT logs for unexpected certificates for your domains (detecting
  mis-issuance). Browsers require certificates to be in CT logs (a certificate not logged is rejected). CT
  makes mis-issuance *detectable* rather than silent — a major defense.
- **Certificate pinning (use cautiously):** an application pins the expected certificate/public key, rejecting
  others even if validly signed — defeating mis-issuance for that app. But pinning is operationally risky (a
  cert change breaks the app if the pin isn't updated), so it's used carefully (mobile apps, high-security
  contexts) and largely superseded by CT + CAA for the general web.

The security takeaway: **the PKI trust model's central weakness is that any trusted CA can issue for any
domain (CA compromise/mis-issuance enables MITM), and the modern defenses are CAA (limit which CAs can issue),
Certificate Transparency (make all issuance publicly auditable so mis-issuance is detectable), and cautious
pinning** — with CT monitoring of your domains being a concrete, valuable practice.

### 4.6 Certificate lifecycle, expiry, and automation

The operational reality of PKI is the **certificate lifecycle**, and its dominant failure mode is **expiry**:

```
   Lifecycle: request (CSR) -> validation (domain/org validation by the CA) -> issuance -> deployment ->
              RENEWAL (before expiry!) -> revocation (if needed) -> expiry.
   THE #1 PREVENTABLE OUTAGE: a certificate EXPIRES because renewal was missed -> clients reject it -> outage.
     (Famous examples: major services down for hours due to an expired certificate.)
```

The dominant lesson: **automate certificate management** — expiry is entirely preventable, yet expired
certificates cause frequent, embarrassing outages because manual renewal is missed. Modern practice:

- **Automated issuance and renewal:** **Let's Encrypt + ACME** (automated, free, 90-day certs auto-renewed),
  **AWS Certificate Manager (ACM)** (managed certs, auto-renewed for AWS services), cert-manager (Kubernetes).
  Automation removes the manual-renewal failure.
- **Short lifetimes** (90 days and shrinking, toward days) — reduce the impact of a compromised cert (§4.4)
  and *force* automation (you can't manually renew every 90 days at scale, so you must automate). The industry
  is deliberately shortening lifetimes to force automation and reduce revocation reliance.
- **Monitoring/alerting on expiry** — alert well before expiry as a backstop (even with automation, monitor).

The cloud reality: **ACM (managed, auto-renewed) removes most certificate-management burden for AWS
services** — you request a cert, ACM validates (via DNS/email) and auto-renews, and it's used by ALB/
CloudFront/etc. This is a major operational security win (no expired-cert outages, no private-key handling —
ACM keeps the private key). For non-ACM cases, Let's Encrypt/cert-manager automate similarly.

---

## 5. Deep Technical Explanation: PKI as the Trust Layer That Authenticates Everything

PKI is the *trust layer* that turns cryptographic capabilities (Chapter 26) into verifiable identity — and
understanding its role, its bootstrapping-trust solution, and its failure modes is what makes it usable.

**PKI completes key exchange (the authentication gap):** Chapter 26 showed that key exchange (ECDHE)
establishes a shared key but is MITM-able without authentication — an attacker could exchange keys with each
side separately. PKI provides that authentication: the server presents a certificate (a CA-signed binding of
its public key to its domain name), the client validates it (chain to a trusted root + identity match +
validity + revocation), and thereby confirms it's exchanging keys with the *real* domain owner (who alone has
the private key matching the certified public key). So **PKI is what makes TLS actually secure** — without it,
TLS would be encryption to an unauthenticated (possibly attacker) endpoint. The certificate authenticates the
key exchange; the key exchange establishes the symmetric key; symmetric AEAD (Chapter 25) transfers the data —
this is the full TLS architecture (Chapter 28), and PKI is its trust foundation.

**PKI solves the bootstrapping trust problem (Chapter 15 §5) with pre-installed anchors:** recall the
bootstrapping problem — to verify something, you need a prior trust anchor. PKI's answer is the **trust store
of pre-installed root CA public keys** shipped with your OS/browser. Because you already trust these roots
(installed out-of-band, by the OS/browser vendor), you can verify any certificate that chains up to them —
including for sites you've never visited. This is the *strong* solution to bootstrapping (a pre-installed
anchor) versus the *weak* solution (trust-on-first-use, as in DHCP/ARP — Chapter 15 §5). PKI is the concrete
realization of "bootstrap trust with a pre-installed anchor," and it is why the web can have authenticated
communication between strangers. The trade-off is that you must trust the root CAs (and the CA ecosystem) —
which is the source of PKI's failure modes.

**PKI's failure modes and their defenses (the trust model's fragility):** the trust model concentrates trust
in CAs, and its weaknesses are:

1. **CA compromise / mis-issuance** (§4.5) — any trusted CA can issue for any domain, so a compromised or
   negligent CA can enable MITM of any domain. Defense: **CAA** (limit which CAs issue for your domain),
   **Certificate Transparency** (make all issuance publicly auditable, so mis-issuance is *detectable* by
   monitoring CT logs for your domains), and cautious **pinning**. CT is the major structural defense — it
   doesn't prevent mis-issuance but makes it visible.
2. **Weak revocation** (§4.4) — CRLs/OCSP are unreliable (soft-fail), so you can't fully rely on revoking a
   compromised certificate. Defense: **short lifetimes** (a compromised cert is valid briefly) + automation.
3. **Validation bugs** (§4.3) — disabling or misconfiguring validation (skipping identity check, "accept all
   certs") turns TLS into unauthenticated encryption, enabling MITM. Defense: use vetted TLS libraries with
   validation *on*; never disable validation; treat "verify=False" as a serious finding.
4. **Expiry** (§4.6) — the dominant *operational* failure, causing outages. Defense: **automation** (ACM,
   Let's Encrypt/ACME, cert-manager) + monitoring.

**The cloud shifts PKI toward managed and short-lived (the modern direction):** managed certificate services
(ACM) remove private-key handling and manual renewal (the two biggest operational risks — key exposure and
expiry). Short lifetimes + automation reduce revocation reliance and compromise windows. Internal PKI for
mTLS/workload identity (Chapters 64, 67) is increasingly automated (cert-manager, service mesh, SPIFFE) with
very short-lived certificates (hours) — pushing the "short-lived + automated" model to its logical end
(certificates so short-lived that revocation is nearly irrelevant and compromise windows are tiny). This is
the direction of modern PKI: managed, automated, short-lived, with CT for auditability.

The unifying insight: **PKI is the trust layer that binds public keys to identities via CA signatures
anchored in pre-installed root trust stores, authenticating key exchange (making TLS secure) and solving the
bootstrapping trust problem with pre-installed anchors — with failure modes (CA compromise/mis-issuance, weak
revocation, validation bugs, expiry) addressed by CAA, Certificate Transparency, short lifetimes +
automation, and correct validation.** The cloud security engineer's job is operational and configural: automate
certificate lifecycle (never expire), never disable validation, limit issuance (CAA) and monitor it (CT), use
managed services (ACM) and short lifetimes, and protect private keys (Chapter 26). PKI turns Chapter 26's
signatures and key exchange into the authenticated, MITM-resistant identity that TLS (Chapter 28) and the
whole trusted internet depend on.

---

## 6. Internals: Working with Certificates and PKI

### 6.1 Inspect a certificate and its chain

```bash
# Fetch and inspect a server's certificate (the TLS handshake — Chapter 28):
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
    openssl x509 -noout -text | grep -E 'Subject:|Issuer:|Not Before|Not After|DNS:|Signature Algorithm'
#   Subject/SANs (identity), Issuer (the CA), validity dates, signature algorithm (Chapter 26).

# See the FULL chain (leaf + intermediates) the server sends (§4.2):
$ openssl s_client -connect example.com:443 -servername example.com -showcerts </dev/null 2>/dev/null | \
    grep -E 'subject=|issuer='
# A complete chain shows leaf -> intermediate -> (root, trusted locally). Missing intermediates = a finding.

# Check expiry (the #1 outage — §4.6):
$ echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
    openssl x509 -noout -dates
```

Inspecting the Subject/SANs (identity), Issuer (CA), validity (expiry), and the full chain is the core
certificate-analysis skill. Missing intermediates (§4.2) and near-expiry dates (§4.6) are common findings.

### 6.2 Validate a certificate (all the steps)

```bash
# Verify a certificate chains to a trusted root (§4.3 steps 1-2):
$ openssl s_client -connect example.com:443 -servername example.com </dev/null 2>&1 | grep 'Verify return'
    Verify return code: 0 (ok)                 # 0 = valid; nonzero = a validation failure (which step?)
# Common failure codes: expired (10), self-signed (18), unable to get local issuer (missing intermediate, 20),
#   hostname mismatch (identity check — the CRITICAL step 3).
$ curl -v https://example.com 2>&1 | grep -iE 'SSL certificate|verify'   # curl does full validation by default
```

The `Verify return code` tells you whether validation passed and, if not, which step failed (expired,
untrusted root, missing intermediate, name mismatch). Note: `curl`/browsers do full validation *including the
identity match* by default — the security is in *not disabling* it (§4.3).

### 6.3 The catastrophic anti-pattern (never do this)

```bash
# NEVER disable certificate validation "to make it work" — this breaks TLS authentication (§4.3):
#   curl -k / --insecure           <- accepts ANY certificate (MITM-able) — for testing ONLY, never production
#   verify=False (Python requests) <- disables validation — a serious vulnerability
#   InsecureSkipVerify: true (Go)  <- same
#   rejectUnauthorized: false (Node)<- same
# These turn TLS into encryption-WITHOUT-authentication -> MITM (Chapters 9, 26). A common serious bug.
echo "Disabling cert validation = encryption without authentication = MITM. NEVER in production."
```

This is the most common serious TLS mistake — disabling validation (often to work around a cert error),
leaving MITM open. It should be treated as a serious finding in code review (Chapter 111). The fix is to fix
the certificate/trust issue, never to disable validation.

### 6.4 Certificate Transparency and CAA (the mis-issuance defenses)

```bash
# CAA — which CAs may issue for your domain (§4.5, Chapter 16 §4.3):
$ dig CAA example.com +short              # e.g. 0 issue "letsencrypt.org" -> only Let's Encrypt may issue

# Certificate Transparency — monitor CT logs for certificates issued for YOUR domains (§4.5):
#   crt.sh (a CT log search) shows all certs issued for a domain — check for unexpected ones.
$ curl -s "https://crt.sh/?q=example.com&output=json" | jq '.[].name_value' | sort -u | head
# Unexpected certificates for your domain in CT logs = possible mis-issuance -> investigate.
```

CAA limits *which* CAs can issue for your domain (reducing mis-issuance risk — §4.5); CT logs (searchable via
crt.sh) let you *monitor* for unexpected certificates issued for your domains (detecting mis-issuance). Both
are concrete, valuable PKI defenses you configure/monitor.

### 6.5 Managed certificates (ACM) and automation

```bash
# AWS Certificate Manager — managed, auto-renewed certs (no private-key handling, no expiry — §4.6):
$ aws acm list-certificates --query 'CertificateSummaryList[].{domain:DomainName,arn:CertificateArn}'
$ aws acm describe-certificate --certificate-arn <arn> --query 'Certificate.{status:Status,renewal:RenewalEligibility,notAfter:NotAfter}'
# ACM validates (DNS/email), auto-renews, and keeps the private key — used by ALB/CloudFront. No expiry outages.
# Let's Encrypt/ACME (certbot) and cert-manager (Kubernetes) provide similar automation for non-ACM cases.
```

Managed/automated certificate services (ACM, Let's Encrypt/ACME, cert-manager) remove the two biggest PKI
operational risks — private-key handling and expiry (§4.6). Using them is a major operational security win.

---

## 7. Real-World Example: PKI in the Ledger System

**Where Ledger uses and manages PKI:**

- **Public TLS certificates (Chapters 4, 28):** Ledger's `ledger.example` uses certificates issued by a
  trusted CA (via **ACM** in System B — managed, auto-renewed, no private-key handling; or Let's Encrypt on
  the VPS). Clients validate the chain to a trusted root + identity match + validity + revocation (§4.3),
  authenticating the ECDHE key exchange (Chapter 26) → TLS secure.
- **Automated lifecycle (§4.6):** Ledger uses **ACM auto-renewal** (or ACME/certbot on the VPS) so
  certificates never expire — avoiding the #1 outage. Plus monitoring/alerting on expiry as a backstop.
- **Never disabling validation (§4.3):** Ledger's code (HttpClient calls to Stripe, internal services) uses
  full certificate validation — never `verify=False`/`-k`/`InsecureSkipVerify` (a serious finding in code
  review — Chapter 111). This is what makes its outbound TLS actually secure (not MITM-able).
- **CAA + CT monitoring (§4.5):** Ledger sets **CAA records** (Chapter 16) limiting which CA can issue for
  `ledger.example`, and **monitors CT logs** (crt.sh/API) for unexpected certificates for its domains —
  detecting mis-issuance/CA compromise.
- **Internal PKI / mTLS (Chapters 64, 67):** for service-to-service authentication (System C — Kubernetes/
  mesh), Ledger runs an **internal CA** (cert-manager / service mesh / SPIFFE) issuing **short-lived**
  certificates (hours) to workloads — mutual TLS where each service authenticates the other via certificates
  (workload identity — Chapter 67). Short lifetimes make revocation nearly irrelevant and compromise windows
  tiny.
- **Private key protection (Chapter 26 §4.1):** Ledger's certificate private keys are protected — ACM keeps
  them (never exposed); on the VPS, file permissions; for internal PKI, KMS/short lifetimes.

The PKI decisions Ledger makes: managed/automated certificates (ACM — no expiry, no key handling); never
disable validation; CAA + CT monitoring for mis-issuance; internal short-lived certs for mTLS/workload
identity; and private-key protection. The failures Ledger avoids: expired certs (automation), disabled
validation (MITM), unlimited issuance (CAA), silent mis-issuance (CT monitoring), and exposed private keys
(ACM/KMS).

The Ledger takeaway: **PKI is Ledger's trust foundation — certificates authenticating TLS (making it
MITM-resistant), managed and automated (ACM — no expiry, no key handling), with validation never disabled,
mis-issuance limited (CAA) and monitored (CT), and internal short-lived certificates for mTLS/workload
identity — turning Chapter 26's signatures and key exchange into authenticated, verifiable identity across
Ledger's services.** This completes the trust story that key exchange left open and sets up TLS (Chapter 28).

---

## 8. Hands-On Demonstration

### LAB 27.1 — Certificates, Chains, Validation, and the Trust Model

**Objective.** Inspect real certificates and chains, understand and verify validation (all steps, especially
identity match), see the catastrophic effect of disabling validation, and use CT/CAA to detect/limit
mis-issuance.

**Cost.** Free. **Environment.** ENV-1 (openssl, curl, dig). **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Inspect a certificate and its chain.*

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | \
  openssl x509 -noout -text | grep -E 'Subject:|Issuer:|Not Before|Not After|DNS:|Signature Algorithm'
# Identify: the identity (Subject/SANs), the CA (Issuer), validity (expiry), signature algorithm (Chapter 26).
openssl s_client -connect example.com:443 -servername example.com -showcerts </dev/null 2>/dev/null | \
  grep -E 'subject=|issuer='                # the full chain (leaf -> intermediate -> root)
```

*Step 2 — Verify validation (and see failure codes).*

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>&1 | grep 'Verify return'
# 0 = valid. Try a known-bad site to see a failure:
openssl s_client -connect expired.badssl.com:443 -servername expired.badssl.com </dev/null 2>&1 | grep 'Verify return'  # expired
openssl s_client -connect wrong.host.badssl.com:443 -servername wrong.host.badssl.com </dev/null 2>&1 | grep -iE 'Verify|mismatch'  # name mismatch
curl -v https://self-signed.badssl.com 2>&1 | grep -iE 'certificate|verify'   # untrusted -> curl rejects
```

**Expected:** valid sites return code 0; badssl.com's deliberately-broken sites (expired, wrong-host,
self-signed) fail validation — demonstrating the validation steps (§4.3) working. Note the *identity match*
failure (wrong.host) — the critical MITM-preventing step.

*Step 3 — See the catastrophic anti-pattern (disabling validation).*

```bash
# curl -k accepts ANY certificate (MITM-able) — demonstrating why disabling validation is dangerous:
curl -sk https://self-signed.badssl.com >/dev/null && echo "curl -k accepted an untrusted cert (MITM-able!)"
curl -s https://self-signed.badssl.com >/dev/null 2>&1 || echo "curl (default, validation ON) correctly REJECTED it"
# The contrast: default validation rejects the bad cert; -k (disabled validation) accepts it -> MITM open.
```

**Expected:** default curl rejects the untrusted cert (validation working); `curl -k` accepts it
(validation disabled → MITM-able). This is the §4.3/§6.3 lesson: disabling validation breaks TLS
authentication — never in production.

*Step 4 — CAA and Certificate Transparency (mis-issuance defenses).*

```bash
dig CAA example.com +short                    # which CAs may issue (§4.5, §6.4) — limits mis-issuance
# Monitor CT logs for certs issued for a domain (detect mis-issuance — §4.5):
curl -s "https://crt.sh/?q=example.com&output=json" 2>/dev/null | jq -r '.[].name_value' 2>/dev/null | sort -u | head
# Unexpected certificates for YOUR domain = possible mis-issuance -> investigate.
```

**Security implications.** Write down: (a) a certificate is a CA-signed identity-to-key binding (Chapter 26
signature); (b) validation = chain to trusted root + identity match + validity + revocation, all steps matter,
identity match prevents MITM; (c) disabling validation = encryption without authentication = MITM (never);
(d) the trust model's risk is CA mis-issuance, defended by CAA (limit) + CT (detect); (e) expiry is the #1
outage → automate (ACM/ACME); (f) PKI authenticates the key exchange (Chapter 26) making TLS secure.

**Cleanup.** None.

---

## 9. Security Implications

- **PKI binds public keys to identities via CA signatures anchored in pre-trusted root trust stores** —
  authenticating the key exchange (Chapter 26) so TLS (Chapter 28) is MITM-resistant (an attacker can't
  produce a valid certificate for the real name). It is the trust layer that makes encryption *authenticated*.
- **PKI is the bootstrapping-trust solution** (Chapter 15 §5) — pre-installed root trust anchors let you
  *verify* certificates (even for sites never visited) rather than trust-on-first-use.
- **Certificate validation is where TLS security lives** — chain to trusted root + **identity match** (the
  MITM-preventing step) + validity + revocation. **Disabling validation** (`verify=False`, `-k`,
  `InsecureSkipVerify`) turns TLS into unauthenticated encryption = MITM — a common, serious bug.
- **The trust model's central weakness is CA compromise/mis-issuance** — any trusted CA can issue for any
  domain. Defenses: **CAA** (limit which CAs issue for your domain), **Certificate Transparency** (public,
  auditable logs of all issuance → mis-issuance is *detectable* by monitoring), cautious **pinning**.
- **Revocation is weak** (CRL/OCSP soft-fail) — you can't fully rely on revoking a compromised cert; the
  modern answer is **short lifetimes + automation** (a compromised cert is valid briefly).
- **Expiry is the #1 preventable outage** — **automate** the lifecycle (ACM, Let's Encrypt/ACME, cert-manager)
  and monitor; managed services (ACM) also remove private-key handling.
- **Private keys are the crown jewel** (Chapter 26 §4.1) — protect absolutely (ACM/KMS/file permissions).
  Modern direction: managed, automated, short-lived certificates, with CT for auditability.

---

## 10. Attack Scenarios

1. **Disabled/broken certificate validation** (§4.3): code accepting any certificate (`verify=False`/`-k`) →
   MITM (Chapters 9, 26). The most common serious TLS bug. Defense: never disable validation; fix the cert
   issue instead.
2. **CA compromise / mis-issuance** (§4.5): a compromised/negligent CA issues a valid cert for your domain to
   an attacker → MITM (DigiNotar 2011). Defense: CAA (limit issuers), CT monitoring (detect), pinning.
3. **Expired certificate** (§4.6): missed renewal → clients reject → outage (availability). Defense:
   automation (ACM/ACME) + monitoring.
4. **Missing intermediate certificates** (§4.2): server sends only the leaf → validation fails for clients
   without the cached intermediate. Defense: send the full chain.
5. **Private key compromise** (Chapter 26): a leaked cert private key lets an attacker impersonate/decrypt.
   Defense: protect keys (ACM/KMS); revoke + reissue (relying on short lifetimes given weak revocation).
6. **Identity-match bypass** (§4.3): validating the signature but not the name → any valid cert accepted for
   any domain → MITM. Defense: always check SANs match the connected domain (vetted libraries do).
7. **Rogue/untrusted CA in the trust store** (§4.2): a malicious CA added to a trust store (e.g. corporate
   MITM proxy, or malware) → can issue trusted certs for any domain. Defense: control trust stores; monitor.

---

## 11. Defensive Techniques

- **Never disable certificate validation** — treat `verify=False`, `curl -k`, `InsecureSkipVerify`,
  `rejectUnauthorized: false` as serious findings (Chapter 111); fix the underlying cert/trust issue instead.
  Validation (chain + identity match + validity + revocation) is what makes TLS authenticated.
- **Automate the certificate lifecycle** — use **ACM** (managed, auto-renewed, no key handling), **Let's
  Encrypt/ACME**, or **cert-manager** (Kubernetes); expiry is entirely preventable and the #1 outage. Monitor
  expiry as a backstop.
- **Limit and monitor issuance** — set **CAA records** (which CAs may issue for your domain — Chapter 16) and
  **monitor Certificate Transparency logs** (crt.sh/API) for unexpected certificates for your domains
  (detecting mis-issuance/CA compromise).
- **Use short-lived certificates** — reduces compromise windows and revocation reliance (revocation is weak);
  push toward automation and, for internal PKI/mTLS, very short lifetimes (hours — Chapters 64, 67).
- **Protect private keys absolutely** (Chapter 26 §4.1) — ACM/KMS keep them; on hosts, strict file
  permissions; for internal PKI, short lifetimes + KMS.
- **Send the full certificate chain** (leaf + intermediates) to avoid validation failures (§4.2).
- **Control trust stores** — know what root CAs your systems trust; a rogue/added CA (corporate MITM proxy,
  malware) can issue trusted certs for any domain; monitor and manage trust stores.
- **Use OCSP stapling** where revocation checking is needed (better than client OCSP — §4.4); but rely
  primarily on short lifetimes given revocation's weakness.

---

## 12. Production Architecture

PKI/certificate management, VPS vs cloud, and the modern direction:

```
 NEED                     APPROACH                          SYSTEM A (VPS)        SYSTEM B (AWS)
 ---------------------    ------------------------------    -------------------   -------------------------
 public TLS certs         managed/automated, auto-renewed    Let's Encrypt/certbot ACM (managed, auto-renew, no key)
 avoid expiry (§4.6)      automation + monitoring            ACME cron + alerts    ACM auto-renew + alerts
 limit issuance (§4.5)    CAA records                        CAA (Chapter 16)      CAA (Route 53)
 detect mis-issuance      CT monitoring                      crt.sh monitoring     crt.sh/API monitoring
 validation (§4.3)        never disable                      code review (Ch111)   code review + config
 internal mTLS (Ch64,67)  internal CA, short-lived           self-managed CA       cert-manager / mesh / Private CA
 private key protection   ACM/KMS/file permissions           file permissions      ACM/KMS (never exposed)
 revocation (§4.4)        short lifetimes > revocation        short-lived + OCSP staple  short-lived + ACM
```

The architectural principle: **PKI is the trust layer that authenticates TLS (and identity generally) by
binding keys to identities via CA signatures anchored in pre-trusted roots — operationalized by automating
the certificate lifecycle (never expire — ACM/ACME/cert-manager), never disabling validation, limiting
issuance (CAA) and monitoring it (CT), using short-lived certificates (reducing compromise windows and
revocation reliance), and protecting private keys (ACM/KMS).** The cloud direction is managed, automated, and
short-lived: ACM removes expiry and key-handling for public certs; internal PKI (cert-manager/mesh/SPIFFE)
issues very short-lived certs for mTLS/workload identity (Chapters 64, 67). PKI turns Chapter 26's signatures
and key exchange into the authenticated, MITM-resistant identity that TLS (Chapter 28) and the trusted
internet depend on — and the security engineer's job is operational (automate, don't disable validation,
CAA+CT, short-lived, protect keys), because the algorithms are sound and the failures are operational
(expiry, disabled validation, mis-issuance).

---

## 13. Common Mistakes

1. **Disabling certificate validation** (`verify=False`/`-k`/`InsecureSkipVerify`) — MITM; the #1 serious TLS
   bug (§4.3).
2. **Expired certificates** — missed renewal → outage; automate (§4.6).
3. **Missing intermediate certificates** — validation fails for some clients (§4.2); send the full chain.
4. **Not checking identity match** (or a library that doesn't) — any valid cert accepted → MITM (§4.3).
5. **No CAA / no CT monitoring** — unlimited/undetected mis-issuance (§4.5).
6. **Relying on revocation** to undo a compromised cert — revocation is weak (soft-fail); use short lifetimes
   (§4.4).
7. **Exposed/mishandled private keys** — impersonation/decryption (Chapter 26); protect (ACM/KMS).
8. **Rogue/unmonitored trust stores** — an added malicious CA issues trusted certs for any domain (§4.2).
9. **Manual certificate management at scale** — leads to missed renewals; automate.
10. **Long-lived certificates** — larger compromise windows; prefer short-lived + automation.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| "Certificate expired" errors, site down | missed renewal (§4.6) | `openssl x509 -dates`; automate renewal (ACM/ACME) |
| Cert works in browser, fails elsewhere | missing intermediate (§4.2) | `s_client -showcerts`; send the full chain |
| "Certificate name mismatch" | SANs don't include the domain (§4.3) | check SANs; reissue with the correct name |
| "Unable to get local issuer" | untrusted root or missing intermediate | check the chain; is the root in the trust store? |
| App "works" only with validation disabled | a cert/trust issue being worked around dangerously | FIX the cert/chain; never leave validation disabled (§4.3) |
| Unexpected certificate for your domain | mis-issuance / CA compromise (§4.5) | CT logs (crt.sh); investigate; revoke; set CAA |
| MITM despite TLS | validation disabled or a rogue trusted CA | check for disabled validation, trust-store additions |
| Revoked cert still accepted | weak revocation (soft-fail) (§4.4) | rely on short lifetimes; OCSP stapling; reissue |

---

## 15. Practical Lab

Lab 27.1 is in §8. Register it in the lab index. Extension: build your own tiny internal PKI with openssl —
create a root CA, an intermediate, and a server certificate (the chain — §4.2), then validate the chain and
demonstrate that a certificate with the wrong name or expired dates fails validation (§4.3). This makes the
chain-of-trust and validation concrete and mirrors what an internal CA (cert-manager/mesh — Chapters 64, 67)
does for mTLS. Then set CAA and check CT logs for a domain you control.

---

## 16. Exercises

### Concept questions

**27.1** Explain what a certificate is, what a CA does, and how the chain of trust works up to a pre-trusted
root. How does this authenticate the key exchange (Chapter 26)?

**27.2** List the certificate validation steps and explain why the identity-match step is critical for
preventing MITM.

**27.3** Explain why disabling certificate validation is catastrophic, and what it turns TLS into.

**27.4** Explain the trust model's central weakness (CA mis-issuance) and the defenses (CAA, Certificate
Transparency, pinning).

**27.5** Explain why revocation is weak and why the industry moved toward short-lived certificates.

### Debugging problems

**27.6** A certificate works in Chrome but fails with an "unable to get local issuer" error in a script.
Diagnose and fix.

**27.7** A service outage is traced to TLS. What's the most likely cause, and how do you prevent recurrence?

**27.8** You find `verify=False` in application code. Explain the risk and the fix.

### Security scenarios

**27.9** Design the certificate management strategy for a cloud application (public certs + internal mTLS),
addressing expiry, validation, mis-issuance, revocation, and private-key protection.

**27.10** You discover an unexpected certificate for your domain in a CT log. Walk through your response.

### Architecture questions

**27.11** Explain how PKI completes the trust story that key exchange (Chapter 26) left open, and how
certificate + key exchange + symmetric AEAD combine into TLS (Chapter 28).

**27.12** Design an internal PKI for service-to-service mTLS/workload identity (bridge to Chapters 64, 67),
explaining short lifetimes and automation.

### Hands-on exercises

**27.13** Inspect a real certificate and its chain, identifying the identity, CA, validity, and signature.

**27.14** Demonstrate certificate validation succeeding for a valid site and failing for expired/wrong-name/
self-signed sites (badssl.com).

**27.15** Set a CAA record and check CT logs for a domain you control.

### Interview questions

**27.16** "How does a browser know it can trust a website's certificate?"

**27.17** "What happens if you disable certificate validation, and why do people do it?"

**27.18** "What is Certificate Transparency and what problem does it solve?"

**27.19** "Why do certificates expire, and what's the operational implication?"

**27.20** "What is the biggest weakness of the PKI trust model, and how is it addressed?"

---

## 17. Summary

- **PKI binds public keys to identities via CA digital signatures (Chapter 26) anchored in pre-installed root
  trust stores** — a **certificate** is a signed statement "this public key belongs to this identity," and
  you trust it by verifying the signature **chain** up to a **root your system pre-trusts** (the trust
  anchor). This **authenticates the key exchange** (Chapter 26), making TLS (Chapter 28) MITM-resistant.
- **PKI is the strong solution to the bootstrapping trust problem** (Chapter 15 §5) — pre-installed root
  anchors let you *verify* rather than trust-on-first-use, enabling authenticated communication between
  strangers.
- **Validation is where TLS security lives** — chain to trusted root + **identity match** (the MITM-preventing
  step) + validity (not expired) + revocation. **Disabling validation** (`verify=False`/`-k`/
  `InsecureSkipVerify`) turns TLS into unauthenticated encryption = MITM — the #1 serious TLS bug.
- **The trust model's central weakness is CA compromise/mis-issuance** (any trusted CA can issue for any
  domain — DigiNotar 2011). Defenses: **CAA** (limit which CAs issue for your domain), **Certificate
  Transparency** (public auditable logs → mis-issuance is *detectable* by monitoring), cautious **pinning**.
- **Revocation is weak** (CRL/OCSP soft-fail) — the modern answer is **short lifetimes + automation** (a
  compromised cert is valid briefly). **Expiry is the #1 preventable outage** — **automate** the lifecycle
  (ACM/Let's Encrypt-ACME/cert-manager) and monitor; managed services (ACM) also remove private-key handling.
- **Private keys are the crown jewel** (Chapter 26) — protect absolutely (ACM/KMS/file permissions). The
  modern direction is managed, automated, short-lived certificates with CT for auditability, and internal PKI
  (cert-manager/mesh/SPIFFE) for mTLS/workload identity (Chapters 64, 67). PKI turns Chapter 26's signatures
  and key exchange into the authenticated identity that TLS and the trusted internet depend on.

---

## 18. Knowledge Check

1. What is a certificate, and how does the chain of trust work to a pre-trusted root? (§3, §4.2)
2. List the validation steps; why is identity match critical? (§4.3)
3. What does disabling validation turn TLS into? (§4.3)
4. What is the trust model's central weakness, and the defenses? (§4.5)
5. Why is revocation weak, and what replaced reliance on it? (§4.4)
6. Why is expiry the #1 outage, and how is it prevented? (§4.6)
7. How does PKI solve the bootstrapping trust problem? (§5, Chapter 15)
8. What is Certificate Transparency and what does it enable? (§4.5)
9. What does CAA do? (§4.5, Chapter 16)
10. How does PKI authenticate the key exchange (Chapter 26)? (§5)

---

## 19. Further Exploration

- badssl.com — a site with deliberately-broken certificates (expired, wrong-host, self-signed, etc.) to test
  validation (§8) — invaluable for understanding validation failures.
- crt.sh — search Certificate Transparency logs for your domains (§4.5, §6.4); set up CT monitoring/alerting.
- Let's Encrypt / ACME documentation and cert-manager (Kubernetes) — the automation that prevents expiry.
- The DigiNotar 2011 incident — the definitive CA-compromise case study (§4.5) and why CT exists.
- RFC 5280 (X.509), RFC 6962 (Certificate Transparency), RFC 8659 (CAA) — the specifications.
- Chapter 28 next (TLS) — combines PKI (this chapter) + key exchange (Chapter 26) + symmetric AEAD (Chapter
  25) into the full secure channel; Chapters 64, 67 apply internal PKI to mTLS/workload identity.

---

## Solutions

### 27.2
Certificate validation steps: (1) **Signature chain** — verify the leaf certificate is signed by an
intermediate CA, the intermediate by the root (each signature verified with the signer's public key —
Chapter 26). (2) **Trusted root** — verify the chain terminates at a root CA in the client's trust store (the
pre-installed anchor). (3) **Identity match** — verify the certificate's Subject Alternative Names include the
domain being connected to. (4) **Validity** — verify the current time is within Not Before / Not After (not
expired). (5) **Revocation** — verify the certificate is not revoked (CRL/OCSP). The **identity-match step
(3) is critical for preventing MITM** because without it, an attacker who holds *any* validly-signed
certificate (for a domain they legitimately control) could present it when MITM-ing a connection to a
*different* domain — the certificate is genuinely signed by a trusted CA and chains correctly (steps 1-2
pass), it's valid and not revoked (steps 4-5 pass), so if the client doesn't check that the certificate's
name matches the domain it's actually connecting to, it would accept the attacker's certificate and establish
a "secure" connection with the attacker. The identity check ensures you're not just talking to *someone with
a valid certificate* but to *the right party* — the one whose certificate names the domain you intended. This
is why skipping the hostname/SAN check (a real bug in some custom validation code) breaks TLS authentication
even when the rest of validation is done, and why vetted TLS libraries always perform it by default. All five
steps are necessary, but identity match is the one that specifically ties the trusted certificate to the
intended destination.

### 27.3
Disabling certificate validation turns TLS from **authenticated encryption** into **unauthenticated
encryption** — it still encrypts the traffic (confidentiality against a passive eavesdropper), but it no
longer verifies *who* the other party is, which means an active man-in-the-middle attacker can intercept the
connection, present *their own* certificate (which would normally be rejected), and the client accepts it —
so the client establishes an encrypted connection *with the attacker*, who decrypts, reads/modifies, and
re-encrypts to the real server (a full MITM — Chapters 9, 26). The encryption provides no protection because
it's encryption *to the attacker*. This is catastrophic and, unfortunately, common: developers disable
validation (`verify=False` in Python requests, `curl -k`/`--insecure`, `InsecureSkipVerify: true` in Go,
`rejectUnauthorized: false` in Node) usually to work around a certificate error (a self-signed cert in dev, a
missing intermediate, an expired cert) — and then the disabled validation is left in, often reaching
production, where it permanently opens MITM. It's one of the most serious and frequent TLS mistakes, and it
should be treated as a critical finding in code review (Chapter 111). The correct response is *never* to
disable validation but to fix the underlying issue: install the proper CA/intermediate, use a valid
certificate, or (in dev) add the specific dev CA to the trust store — so validation stays on and TLS remains
authenticated.

### 27.16
A browser trusts a website's certificate through PKI's chain of trust anchored in pre-installed root CAs.
The browser (and OS) ships with a **trust store** of trusted root Certificate Authority public keys,
installed out-of-band by the browser/OS vendor (the trust anchor). When the browser connects to a website
(in the TLS handshake — Chapter 28), the server presents its **certificate** — a document binding the
server's public key to its domain name, **signed by a CA** (Chapter 26 signature). The browser **validates**
it: (1) it verifies the signature chain — the server's certificate is signed by an intermediate CA, which is
signed by a root CA (each signature checked with the signer's public key); (2) it verifies that chain
terminates at a root in its trust store (the pre-trusted anchor); (3) it checks the certificate's names
(SANs) include the domain being visited (the identity match — preventing acceptance of a valid cert for the
wrong domain); (4) it checks the certificate hasn't expired; (5) it checks revocation status. If all pass,
the browser trusts that the public key genuinely belongs to that domain, and uses it to authenticate the key
exchange (Chapter 26) — confirming it's establishing an encrypted channel with the *real* domain owner (who
alone holds the private key matching the certified public key), not an impostor. So the browser can trust a
certificate for a site it's never visited because the certificate chains up to a root the browser already
trusts. Bonus points: mention that browsers also require the certificate to appear in Certificate
Transparency logs (making mis-issuance detectable), and that the security depends on not disabling validation
and on the CA ecosystem behaving correctly (the trust model's weakness, addressed by CAA/CT).

### 27.20
The biggest weakness of the PKI trust model is that **any CA trusted by a client can issue a valid
certificate for any domain** — so the security of every domain depends on *every* trusted CA (hundreds in a
typical trust store) behaving correctly and staying uncompromised. If a CA is compromised or negligent
(**mis-issuance**), it can issue a genuinely-valid certificate for *your* domain to an *attacker*, who can
then MITM connections to your domain — and the certificate validates correctly (it's properly signed by a
trusted CA, chains to a trusted root, has the right name), so clients accept it. This is not hypothetical:
the **DigiNotar** compromise (2011) led to fraudulent Google certificates used to MITM Iranian users, and the
CA was removed from trust stores and went bankrupt. The trust surface is large and concentrated. It's
addressed by three defenses: (1) **CAA records** (Chapter 16) — DNS records specifying *which* CAs may issue
certificates for your domain, so only your chosen CA can (a compliant CA refuses to issue if CAA doesn't
authorize it), shrinking the trust surface for your domain; (2) **Certificate Transparency (CT)** — CAs must
log every certificate they issue to public, append-only, auditable logs, and browsers reject certificates not
in CT logs, so any certificate issued for your domain (including a fraudulent one) is *publicly visible* and
you can **monitor CT logs** to *detect* mis-issuance (CT doesn't prevent it but makes it detectable rather
than silent — the major structural defense); and (3) **certificate pinning** (used cautiously) — an
application pins the expected certificate/key, rejecting others even if validly signed, defeating
mis-issuance for that app (but operationally risky, so largely superseded by CT+CAA for the general web).
Additionally, short-lived certificates limit the window of a compromised/mis-issued cert. So the weakness is
the broad, concentrated trust in CAs, and the modern defense is limit-and-detect: CAA to limit which CAs can
issue, and CT to make all issuance auditable and mis-issuance detectable.

---

*Next: Chapter 28 — TLS Byte by Byte: 1.2 vs 1.3 Handshakes, Key Schedule, Cipher Suites, mTLS, SNI. We now
combine everything from Chapters 25–27 — symmetric AEAD (25), key exchange + signatures (26), and PKI/
certificates (27) — into the full TLS protocol: the handshake that authenticates the server and establishes a
forward-secret symmetric key, the differences between TLS 1.2 and 1.3, mTLS for mutual authentication, and
the configuration that makes it secure.*
