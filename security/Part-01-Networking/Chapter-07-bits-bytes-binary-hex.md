# Chapter 7 — Bits, Bytes, Binary and Hex: Reading Data the Way the Wire Sees It

---

## 1. Why This Matters

Part 1 is going to teach you networking by reading actual packets — because, as Chapter 4
established, every security control operates on data at some layer, and you cannot reason about
what a control sees unless you can read the bytes. Before you can read a packet, you must be
fluent in the alphabet packets are written in: **binary and hexadecimal**.

You are a senior engineer, so you know binary exists and roughly what hex is. This chapter is
not "what is a bit." It is the specific, operational fluency a security engineer needs:

- **Reading a subnet mask as bits** so that CIDR (Chapter 10) is arithmetic you do in your
  head, not a calculator you reach for. `/26` is a network prefix; you should *see* the 26 ones.
- **Decoding a packet header in a hex dump** — the TCP flags byte, the IP version nibble, the
  TTL — so that Wireshark and tcpdump output (Chapter 24) is legible rather than intimidating.
- **Understanding byte order (endianness)** so that "network byte order" in Chapter 3's socket
  code makes sense and so that you are not fooled when a value looks backwards in memory.
- **Reading bitmasks and flags** because permissions (Chapter 1's PTE bits, Chapter 2's
  capability masks), TCP flags, IP fragmentation flags, and firewall matches are all bit
  operations. You already saw `capsh --decode=00000000a80425fb` in Chapter 2 — this chapter is
  why that hex string means fourteen specific capabilities.
- **Recognizing encodings** (hex, Base64, URL-encoding, percent-encoding) on sight, because
  attackers use encoding to smuggle payloads past filters (Chapter 85, WAF evasion) and you
  must be able to decode what you are looking at.

The deeper reason: **security is frequently about the gap between how two parties interpret the
same bytes.** A WAF sees `%2e%2e%2f` as a string; the filesystem sees `../` (Chapter 53). A
parser sees `0x00` as a terminator; another sees it as data (null-byte injection). Endianness
confusion, sign confusion, encoding confusion — these are not academic. They are the raw
material of exploitation. To spot them you must be able to read the bytes both ways.

This is a short, dense, foundational chapter. Work the exercises until the conversions are
automatic; the rest of Part 1 assumes them.

---

## 2. Prerequisites

- Basic arithmetic and comfort with the idea of number bases.
- Chapter 1 §4.3 (you saw bit fields in the page table entry) and Chapter 2 §4.2 (capability
  masks) — this chapter formalizes reading such bit fields.
- A terminal with `python3`, `printf`, `xxd`, and `bc` available.

---

## 3. Mental Model

**A computer stores and transmits only bits. Every richer thing — a number, a character, an IP
address, a permission set — is an *agreement* about how to interpret a group of bits.** Security
bugs live where two parties hold different agreements.

```
   The SAME 8 bits:  0100 0001
        |
        +-- as an unsigned integer  -> 65
        +-- as a signed integer     -> 65 (positive; high bit is 0)
        +-- as an ASCII character   -> 'A'
        +-- as a bitmask/flags       -> bits 0 and 6 are set
        +-- as two hex nibbles       -> 0x41
        +-- as part of a UTF-8 seq   -> a single-byte code point 'A'
```

The bits do not carry their own meaning. The meaning comes from the code that reads them. So the
recurring security question of this chapter is: **do all parties that touch these bytes agree on
how to interpret them?** When they do not — when the sender means "length in big-endian" and the
receiver reads little-endian, or the WAF decodes once and the app decodes twice — you have a
vulnerability.

**Three groupings you must know cold:**

```
   1 bit    = one binary digit (0 or 1)
   1 nibble = 4 bits          = exactly one hex digit  (0x0 .. 0xF)
   1 byte   = 8 bits          = two hex digits         (0x00 .. 0xFF = 0 .. 255)
   values in a byte: 0 to 255 (unsigned), or -128 to 127 (signed)
```

The nibble = one hex digit relationship is the whole reason hex exists in this field: **hex is
just a human-readable shorthand for binary, four bits at a time.** Once you internalize that,
hex dumps stop being a wall of characters and become groups of four-bit patterns you can read.

---

## 4. Fundamentals

### 4.1 Binary: base 2

Each position is a power of 2. For one byte (8 bits), the positions are:

```
   bit position:   7    6    5    4    3    2    1    0
   place value:   128   64   32   16    8    4    2    1
   example byte:   1    1    0    0    0    0    0    1   = 128+64+1 = 193
```

The **most significant bit (MSB)** is bit 7 (value 128); the **least significant bit (LSB)** is
bit 0 (value 1). "Set a bit" means make it 1; "clear a bit" means make it 0.

Two conversions you must be able to do in your head or on paper instantly:

**Binary → decimal:** add the place values of the set bits. `1100 0001` = 128 + 64 + 1 = 193.

**Decimal → binary:** subtract the largest fitting power of 2 repeatedly. 193: fits 128
(remainder 65), fits 64 (remainder 1), fits 1 (remainder 0) → `1100 0001`.

The eight place values `128 64 32 16 8 4 2 1` are worth memorizing as a chant, because subnet
masks are built from them (Chapter 10): a mask octet is always some number of leading 1s, giving
exactly these values: `10000000`=128, `11000000`=192, `11100000`=224, `11110000`=240,
`11111000`=248, `11111100`=252, `11111110`=254, `11111111`=255. Those eight numbers —
128,192,224,240,248,252,254,255 — are the only legal subnet-mask octet values, and knowing them
on sight makes subnetting trivial.

### 4.2 Hexadecimal: base 16, the language of dumps

Hex uses 16 digits: `0 1 2 3 4 5 6 7 8 9 A B C D E F`, where A=10 through F=15. One hex digit is
exactly one nibble (4 bits):

```
   hex  binary   dec        hex  binary   dec
   0    0000     0          8    1000     8
   1    0001     1          9    1001     9
   2    0010     2          A    1010     10
   3    0011     3          B    1011     11
   4    0100     4          C    1100     12
   5    0101     5          D    1101     13
   6    0110     6          E    1110     14
   7    0111     7          F    1111     15
```

Memorize this table. It is sixteen rows and it unlocks all hex reading. With it:

**Hex → binary:** replace each hex digit with its 4-bit pattern. `0xC1` → `1100 0001`.
**Binary → hex:** group bits into nibbles from the right, replace each with its hex digit.
`1100 0001` → `C1`.

Notice `0xC1` = `1100 0001` = 193 — the same byte from §4.1, three notations. Being able to flip
between them without thinking is the fluency this chapter is for.

Hex prefixes you will see: `0x41` (C, most languages), `41h` (assembly), `\x41` (string escapes),
`%41` (URL-encoding — note it is hex!), `U+0041` (Unicode code point). All mean the byte 0x41.

### 4.3 Bytes, and why 255 matters everywhere

A byte holds `0x00` to `0xFF`, i.e. 0 to 255. This is why:

- **IPv4 octets go 0–255** (Chapter 10) — each octet is one byte.
- **`255.255.255.0` is a subnet mask** — three all-ones bytes and one all-zeros byte.
- **A TTL of 255** is the maximum (Chapter 12) — it is one byte.
- **HTTP status codes are not bytes** (they are 3-digit decimals) — a good reminder that not
  everything is a byte, and you must know each field's actual encoding.

The 0–255 range is also a classic bug source: an 8-bit counter that wraps from 255 to 0
(integer overflow), a length field that cannot express a value ≥ 256, a signed byte that reads
0x80–0xFF as negative. These wrap/overflow/sign issues are a vulnerability class (Chapter 46 and
the memory-safety discussion of Chapter 1 §5.3), and they all start with "this value doesn't fit
in the bits allotted."

### 4.4 Bitmasks and flags: reading meaning out of individual bits

Many protocol and permission fields pack several boolean flags into one byte, one bit each. You
read them with **bitwise operations**:

```
   AND (&)  : bit is 1 only if BOTH are 1     -> test/extract bits ("is this flag set?")
   OR  (|)  : bit is 1 if EITHER is 1         -> set bits
   XOR (^)  : bit is 1 if bits DIFFER          -> toggle bits, and simple ciphers
   NOT (~)  : flip every bit                   -> invert a mask
   <<  >>   : shift bits left/right            -> multiply/divide by 2, move fields
```

**Testing a flag** is the operation you will do most. To ask "is bit 4 set in byte `x`?", AND
with a mask that has only bit 4 set (`0x10`):

```
   x        = 1001 0110   (0x96)
   mask     = 0001 0000   (0x10, bit 4)
   x & mask = 0001 0000   (0x10, non-zero) -> bit 4 IS set
```

This is exactly how the kernel reads PTE permission bits (Chapter 1 §4.3), how it reads
capability masks (Chapter 2), how TCP flags are decoded (Chapter 19), and how a firewall matches
flag combinations. It is one operation, reused everywhere.

**The TCP flags byte** is the canonical example you will meet in Chapter 19, previewed here so
the bit-reading has a concrete payoff:

```
   bit:   7    6    5    4    3    2    1    0
   flag: CWR  ECE  URG  ACK  PSH  RST  SYN  FIN

   A SYN packet:      0000 0010  = 0x02  (only SYN set)
   A SYN-ACK packet:  0001 0010  = 0x12  (SYN + ACK)
   An ACK packet:     0001 0000  = 0x10  (only ACK)
   A FIN-ACK:         0001 0001  = 0x11  (FIN + ACK)
   An RST:            0000 0100  = 0x04  (RST)
```

When you see `Flags [S]` in tcpdump, or `0x012` in a Wireshark TCP flags field, you now know
exactly which bits are set. A firewall rule that "blocks packets with SYN set but ACK clear" (to
block new inbound connections while allowing replies) is testing `flags & 0x12 == 0x02` — a
bitmask test you can now read. This is not abstract; it is how stateful and stateless packet
filtering (Chapter 76, security groups vs NACLs) actually works.

### 4.5 Endianness: the order of bytes

A single byte has no order problem. But a multi-byte value — a 16-bit port, a 32-bit IP address,
a 32-bit sequence number — must be stored/transmitted as a *sequence* of bytes, and there are two
conventions:

```
   The 32-bit value 0x0A00010B  (which is IP 10.0.1.11):

   BIG-ENDIAN (most significant byte first) — "network byte order":
       byte0  byte1  byte2  byte3
       0x0A   0x00   0x01   0x0B      reads left-to-right like we write numbers

   LITTLE-ENDIAN (least significant byte first) — x86/ARM memory:
       byte0  byte1  byte2  byte3
       0x0B   0x01   0x00   0x0A      reversed
```

The rules you must hold:

- **Networks use big-endian ("network byte order").** Every multi-byte field in IP, TCP, UDP,
  etc. is big-endian on the wire. This is why Chapter 3's socket code called `htons(443)` —
  "host to network short" — to convert the port to big-endian before putting it in a
  `sockaddr`. If you forget, you bind port 47873 (0xBB01) instead of 443 (0x01BB).
- **x86 and ARM are little-endian in memory.** So a value in a memory dump looks byte-reversed
  compared to how you write it, and compared to how it appears on the wire.

The security relevance is real and twofold. First, **reading dumps correctly**: a 4-byte IP in a
memory dump on x86 appears reversed; the same IP on the wire appears in order. Misreading
endianness leads to wrong conclusions in forensics and exploit analysis. Second, **parsing
bugs**: mismatched endianness assumptions between systems (or between a client and server written
by different teams) produce wrong lengths and offsets, which is a rich source of buffer
mis-sizing and protocol confusion. When you craft or analyze packets (Chapter 24), endianness is
constantly in play.

### 4.6 Character encodings: bytes ↔ text

Text is bytes plus an agreement about which bytes mean which characters.

- **ASCII** (7-bit, 0x00–0x7F): the original. `'A'`=0x41, `'a'`=0x61, `'0'`=0x30, space=0x20,
  newline=0x0A, carriage return=0x0D. The `\r\n` (0x0D 0x0A) line ending is everywhere in HTTP
  (Chapter 29) and its handling is central to request smuggling (Chapter 57) and header
  injection.
- **UTF-8** (variable-width, 1–4 bytes): backward-compatible with ASCII for 0x00–0x7F, uses
  multi-byte sequences above. Security-critical because *the same character can sometimes be
  encoded multiple ways* (overlong encodings — historically a filter-bypass, now forbidden but
  still seen in attacks), and because normalization differences between components create the
  interpretation gaps attackers exploit (Chapter 53).
- **The null byte** (0x00): a string terminator in C. "Null-byte injection" (`file.php%00.jpg`)
  historically tricked a C-based check into seeing `.jpg` while the C string operation stopped
  at the null and opened `file.php` — a two-parties-disagree bug in its purest form.

You do not need to memorize the ASCII table, but you should know the ranges (digits 0x30–0x39,
uppercase 0x41–0x5A, lowercase 0x61–0x7A) and the control characters (`\0`, `\t`=0x09, `\n`=0x0A,
`\r`=0x0D) on sight, because they appear constantly in dumps and payloads.

### 4.7 Transport encodings: hex, Base64, URL-encoding

These are not character sets; they are ways to represent arbitrary bytes as safe ASCII text, and
you must recognize them instantly because attackers layer them to evade filters.

- **Hex encoding**: each byte → two hex digits. `Hi` → `4869`. Doubles the size. Seen in tokens,
  hashes, and `\x` escapes.
- **Base64**: 3 bytes → 4 ASCII characters from `[A-Za-z0-9+/]`, padded with `=`. Increases size
  ~33%. **Recognize it by:** the character set, length a multiple of 4, and trailing `=`/`==`.
  Ubiquitous: JWT parts (Chapter 60), Basic auth headers, API keys, email attachments, and data
  URIs. **Base64 is encoding, not encryption** — a JWT's payload is Base64 of readable JSON, not
  a secret. Confusing the two is a common and dangerous mistake (Chapter 60).
- **URL/percent-encoding**: unsafe bytes → `%` + two hex digits. Space → `%20`, `/` → `%2F`,
  `.` → `%2E`. **This is where WAF evasion lives:** `../` = `%2e%2e%2f` = `%252e%252e%252f`
  (double-encoded) = `..%c0%af` (overlong UTF-8). A filter that decodes once and compares, but
  hands the still-partly-encoded string to a component that decodes again, is bypassed (Chapter
  53, 85). You must be able to decode these by hand to analyze an attack.

The meta-skill: when you see a blob of text in a request or log, identify its encoding
(hex? Base64? URL-encoded? layered?), decode it, and see what is actually there. A surprising
amount of security work is exactly this — decoding what the attacker encoded to hide.

---

## 5. Deep Technical Explanation: Reading a Packet Header by Hand

Let us decode a real IPv4 header from a hex dump, using only this chapter's skills. This is the
payoff — it is exactly what Wireshark does for you, done by hand so you understand it.

Here are the first 20 bytes (the IPv4 header) of a captured packet:

```
   45 00 00 3c 1c 46 40 00 40 06 b1 e6 0a 00 01 0b 0a 00 02 0a
```

Decode field by field (the IPv4 header format is Chapter 10; here we practice the byte-reading):

```
   45        -> two nibbles: 4 and 5
                4 = IP version 4
                5 = header length in 32-bit words = 5 words = 20 bytes (no options)
   00        -> DSCP/ECN (type of service) = 0
   00 3c     -> total length = 0x003C = 60 bytes (big-endian!)
   1c 46     -> identification = 0x1C46
   40 00     -> flags + fragment offset: 0x40 = 0100 0000 -> bit 6 set = "Don't Fragment"
   40        -> TTL = 0x40 = 64  (a Linux default — Chapter 12)
   06        -> protocol = 6 = TCP  (17 would be UDP, 1 ICMP)
   b1 e6     -> header checksum = 0xB1E6
   0a 00 01 0b -> source IP: 10.0.1.11   (each byte one octet: 0x0a=10, 0x00=0, 0x01=1, 0x0b=11)
   0a 00 02 0a -> dest IP:   10.0.2.10
```

Read what just happened. With nothing but nibble-splitting (`45`→version 4, header length 5),
big-endian awareness (`00 3c`→60, not `3c 00`→15360), a bit test (`40`→DF flag), and the
byte-per-octet rule (`0a 00 01 0b`→10.0.1.11), you decoded a packet header by hand. Every field a
firewall or IDS inspects — version, length, TTL, protocol, addresses, flags — you just read. This
is not a party trick; it is the literacy that makes Chapters 10, 12, 19, and 24 comprehensible
instead of magical, and it is what lets you sanity-check a tool's decode or read a payload the
tool does not parse.

The security payoff is immediate: an IDS/firewall rule like "drop TCP packets to 10.0.2.10 with
TTL < 5" (a traceroute/scan heuristic) is now something you can see the bytes for. A crafted
packet with an illegal header length or a fragment-offset trick (Chapter 22) is something you can
spot in the dump.

---

## 6. Internals: The Tools That Convert For You

You will not usually convert by hand — but you must be *able* to, and you must know the tools.

### 6.1 One-liners for every conversion

```bash
# Decimal <-> hex <-> binary with python (the swiss-army knife):
$ python3 -c "print(hex(193), bin(193))"          # 0xc1 0b11000001
$ python3 -c "print(0xc1, 0b11000001)"            # 193 193
$ python3 -c "print(int('11000001', 2))"          # 193

# With bc:
$ echo "obase=16; 193" | bc                        # C1
$ echo "obase=2; 193"  | bc                        # 11000001
$ echo "ibase=16; C1"  | bc                        # 193  (input must be uppercase)

# printf for quick formatting:
$ printf '%d\n' 0xc1                                # 193
$ printf '0x%02X\n' 193                             # 0xC1
$ printf '%08d\n' $(echo "obase=2;193"|bc)          # 11000001
```

### 6.2 xxd — the hex dump you will live in

```bash
$ echo -n "GET / HTTP/1.1" | xxd
00000000: 4745 5420 2f20 4854 5450 2f31 2e31       GET / HTTP/1.1

# left: offset  middle: hex (2 bytes per group)  right: ASCII (. for non-printable)
$ echo -n "Hi" | xxd -b                            # binary instead of hex
00000000: 01001000 01101001                        Hi
$ xxd -r                                            # reverse: hex back to bytes
```

Read the middle and right columns together: hex for precision, ASCII for readability. When you
`tcpdump -X` (Chapter 24), this is the format you get, and you will spot `GET`, `Host:`,
`\r\n` (as `0d0a`), and Base64 blobs by eye.

### 6.3 Encoding/decoding on the command line

```bash
# Base64:
$ echo -n "admin:password" | base64                 # YWRtaW46cGFzc3dvcmQ=
$ echo "YWRtaW46cGFzc3dvcmQ=" | base64 -d           # admin:password  (Basic auth decoded!)

# URL-encoding:
$ python3 -c "import urllib.parse as u; print(u.quote('../etc/passwd'))"   # ..%2Fetc%2Fpasswd
$ python3 -c "import urllib.parse as u; print(u.unquote('%2e%2e%2f'))"     # ../

# Hex:
$ echo -n "Hi" | xxd -p                             # 4869
$ echo "4869" | xxd -r -p                           # Hi

# JWT payload (Base64url of JSON — NOT a secret):
$ echo "eyJzdWIiOiIxMjMiLCJyb2xlIjoiYWRtaW4ifQ" | base64 -d 2>/dev/null   # {"sub":"123","role":"admin"}
```

That last line is a security lesson in one command: a JWT payload is *readable*, not encrypted —
Base64 is reversible by anyone. Chapter 60 depends on you having felt this.

---

## 7. Real-World Example: Decoding an Attack Payload

A log line from the Ledger Nginx access log shows a suspicious request:

```
GET /api/files?path=%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd HTTP/1.1
```

Decode it with §4.7:

```
%2e = 0x2E = '.'      %2f = 0x2F = '/'
%2e%2e%2f = "../"
-> path = "../../../etc/passwd"
```

A path-traversal attempt (Chapter 53), URL-encoded to slip past naive string matching. Now
suppose the WAF blocks the literal string `../` but decodes only once. The attacker sends:

```
%252e%252e%252f
```

Decode once: `%25`=`%`, so this becomes `%2e%2e%2f`. The WAF, decoding once, sees `%2e%2e%2f`
(no literal `../`) and allows it. But the application framework decodes *again* (or the web
server does), turning it into `../`. **Two parties, two decodings, one bypass.** You can only
see this coming if you can decode by hand and count the layers.

This is the entire lesson of the chapter applied: the bytes are the same; the interpretations
differ; the gap is the vulnerability. Chapter 85 (WAF) and Chapter 53 (path traversal) are
built on it, and neither is comprehensible without the byte-level fluency you are building here.

---

## 8. Hands-On Demonstration

### LAB 7.1 — Byte-Level Fluency Drills and a Real Decode

**Objective.** Build automatic fluency in binary/hex/decimal conversion, bitmask testing, and
encoding recognition, then decode a real captured packet header and a layered attack payload by
hand and verify with tools.

**Cost.** Free. **Environment.** ENV-1. **Time.** 45–60 minutes.

**Steps.**

*Step 1 — Conversion drills (do these on paper first, then check).*

```bash
# Convert these by hand, then verify:
# 200 -> binary? 172 -> binary? 0xC0A8 -> decimal? 11111110 -> decimal?
python3 -c "print(bin(200), bin(172), 0xC0A8, int('11111110',2))"
# expect: 0b11001000 0b10101100 49320 254
```

Confirm you got `172 = 10101100` and `254 = 11111110` — you will see these exact values as
subnet-mask octets in Chapter 10.

*Step 2 — Bitmask/flag testing (the TCP flags byte).*

```bash
# Which flags are set in each byte? Work it out, then verify:
python3 - <<'PY'
FLAGS = {0x80:"CWR",0x40:"ECE",0x20:"URG",0x10:"ACK",0x08:"PSH",0x04:"RST",0x02:"SYN",0x01:"FIN"}
for b in (0x02, 0x12, 0x10, 0x11, 0x14):
    print(f"0x{b:02x}", "->", [n for m,n in FLAGS.items() if b & m])
PY
# 0x02 -> SYN ; 0x12 -> ACK,SYN ; 0x10 -> ACK ; 0x11 -> ACK,FIN ; 0x14 -> ACK,RST
```

`0x14` (ACK+RST) is what you get when you connect to a closed port behind some firewalls — a
byte you will learn to recognize in Chapter 19 and Chapter 123 (nmap).

*Step 3 — Decode the IPv4 header from §5 by hand, then verify.*

```bash
python3 - <<'PY'
hdr = bytes.fromhex("45 00 00 3c 1c 46 40 00 40 06 b1 e6 0a 00 01 0b 0a 00 02 0a".replace(" ",""))
print("version      :", hdr[0] >> 4)
print("header words :", hdr[0] & 0x0F, "-> bytes:", (hdr[0] & 0x0F)*4)
print("total length :", int.from_bytes(hdr[2:4], "big"))
print("flags byte   :", f"0x{hdr[6]:02x}", "DF set:", bool(hdr[6] & 0x40))
print("TTL          :", hdr[8])
print("protocol     :", hdr[9], "(6=TCP,17=UDP,1=ICMP)")
print("src IP       :", ".".join(str(b) for b in hdr[12:16]))
print("dst IP       :", ".".join(str(b) for b in hdr[16:20]))
PY
```

Compare each printed value to what you decoded by hand in §5. Note `hdr[0] >> 4` (shift to get
the high nibble = version) and `hdr[0] & 0x0F` (mask to get the low nibble = header length) —
the two bit operations that split one byte into two fields.

*Step 4 — Endianness demonstration.*

```bash
python3 - <<'PY'
port = 443
print("port 443 as bytes, network (big-endian):", (port).to_bytes(2,"big").hex())   # 01bb
print("port 443 as bytes, x86 memory (little)  :", (port).to_bytes(2,"little").hex()) # bb01
# If you forgot htons() and sent little-endian, the peer reads:
print("misread as big-endian:", int.from_bytes((port).to_bytes(2,"little"), "big"))   # 47873
PY
```

Feel the bug: forgetting byte-order conversion turns port 443 into 47873. This is why Chapter 3's
code called `htons()`.

*Step 5 — Decode the layered attack payload from §7.*

```bash
python3 - <<'PY'
import urllib.parse as u
p1 = "%2e%2e%2f%2e%2e%2fetc%2fpasswd"
p2 = "%252e%252e%252fetc%252fpasswd"
print("single-encoded:", u.unquote(p1))
print("double-encoded, decoded ONCE:", u.unquote(p2))
print("double-encoded, decoded TWICE:", u.unquote(u.unquote(p2)))
PY
# single -> ../../etc/passwd
# once   -> %2e%2e%2fetc%2fpasswd   (a naive WAF sees THIS and allows it)
# twice  -> ../etc/passwd            (the app decodes again and traversal happens)
```

**Security implications.** Write down: (a) how the double-encoding bypasses a single-decode WAF;
(b) the general principle (two parties, different number of decodings); (c) how you would
correctly defend (decode fully and repeatedly until stable, then validate — or better, avoid
path-from-input entirely, Chapter 53).

**Verification / self-test.** Without tools, convert `240`, `224`, `248` to binary and confirm
they are valid subnet-mask octets (leading 1s only). Identify whether `YWRtaW4=` is hex,
Base64, or URL-encoded (answer in Solutions), and decode it.

**Cleanup.** None needed.

---

## 9. Security Implications

- **Meaning is an agreement about bits; security bugs live where agreements differ.** Endianness
  mismatches, sign confusion, encoding-layer mismatches, and normalization differences are all
  the same root cause and a real vulnerability class.
- **You must read bitmasks fluently** because permissions (PTE bits, capabilities, file modes),
  protocol flags (TCP, IP), and firewall matches are all bit tests.
- **Network byte order is big-endian**; forgetting to convert is a real bug (Chapter 3's
  `htons`), and misreading endianness leads to wrong forensic conclusions.
- **Encodings (hex, Base64, URL) are recognizable and reversible.** Base64 is *not* encryption;
  a JWT payload is readable. Attackers layer encodings to evade filters, and only hand-decoding
  reveals the bypass.
- **Reading a hex dump is a core skill** — it makes tcpdump/Wireshark output and raw payloads
  legible, which the rest of Part 1 requires.

---

## 10. Attack Scenarios

1. **Encoding-based filter bypass** (§7): URL-, double-URL-, or overlong-UTF-8-encoding a
   payload past a WAF or input filter that decodes fewer times than the downstream component
   (Chapters 53, 85).
2. **Null-byte injection** (`file.php%00.jpg`): a length-vs-terminator disagreement between a
   length-based check and a C null-terminated string (§4.6).
3. **Integer overflow/wrap** (§4.3): a value exceeding its bit width wraps, defeating a size or
   bounds check — a memory-safety and logic-bug source (Chapters 1, 46).
4. **Endianness/parsing confusion**: mismatched byte-order assumptions between systems producing
   wrong lengths/offsets, enabling buffer mis-sizing (Chapter 22, protocol parsing).
5. **Base64-as-obfuscation in payloads and C2**: malware and exfiltration Base64-encode data so
   it survives text channels and looks innocuous; recognizing it is a detection skill (Chapters
   13, 17).
6. **Homoglyph/Unicode confusion**: visually identical characters with different code points used
   in phishing domains and to bypass string comparisons (Chapter 17).

---

## 11. Defensive Techniques

- **Canonicalize before you validate.** Fully decode input (repeatedly, until the output stops
  changing) and normalize (Unicode NFC, path canonicalization) *before* applying any filter or
  comparison — so all parties share one interpretation (Chapter 53). Better still, avoid
  building sensitive structures (paths, queries, commands) from input at all (Chapter 4 §9).
- **Validate against allow-lists on the canonical form**, not deny-lists on the raw form —
  deny-lists lose to the encoding you did not think of (the seccomp arch-check lesson, Chapter 2
  §5.4).
- **Use fixed-width, explicitly-signed types and check bounds** to prevent overflow/wrap; prefer
  memory-safe languages that check by construction (Chapter 1 §11.5).
- **Be explicit about byte order** in any wire protocol code (`htons`/`ntohs` and their kin);
  never assume host order on the wire.
- **Treat Base64/hex as encoding, never as a security control.** If it must be secret, encrypt
  it (Chapters 25–26).
- **Log and inspect the decoded form** in detection so encoded attacks are visible (Chapter 118).

---

## 12. Production Architecture

Byte-level literacy is not itself an architecture, but it underpins these architectural controls
you will build later, and it is worth seeing the connection now:

- **WAF placement and configuration** (Chapter 85) depends on where and how many times each layer
  decodes — a decode-mismatch is an architectural bug.
- **Protocol parsers at trust boundaries** (the edge, Chapter 4 Stop 5; request smuggling,
  Chapter 57) must agree byte-for-byte on framing; disagreements are exploitable.
- **Detection pipelines** (Chapter 118) must normalize and decode before matching, or attackers
  hide in encodings.
- **Cryptographic material** (keys, tokens, certificates — Chapters 25–28) is transported as
  hex/Base64/DER; reading it requires this fluency.

The architectural principle: **normalize to a canonical byte representation at the earliest trust
boundary, once, and have every downstream component agree on it.** The alternative — each
component decoding independently — guarantees the interpretation gaps this chapter is about.

---

## 13. Common Mistakes

1. **Treating Base64 as encryption/secrecy.** It is reversible by anyone (§4.7, §6.3).
2. **Deny-listing raw input** instead of allow-listing the canonical form — beaten by encoding.
3. **Decoding a different number of times than the downstream component** (§7) — the WAF-bypass
   classic.
4. **Forgetting byte-order conversion** in wire code (`htons`), binding/reading wrong values.
5. **Assuming one character = one byte** (breaks on UTF-8 multi-byte and breaks length checks).
6. **Ignoring integer width/sign**, allowing wrap-around past bounds checks.
7. **Misreading endianness in dumps**, drawing wrong forensic conclusions.
8. **Not recognizing an encoding** in a payload/log, and therefore not decoding it during
   analysis.

---

## 14. Troubleshooting

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Value looks "backwards" in a memory dump | little-endian host representation | reverse the bytes; compare with the wire form (§4.5) |
| Port/length is wildly wrong on the wire | missing `htons`/`ntohs` byte-order conversion | check for endianness conversion; `xxd` the field |
| Filter passes an obviously malicious string | encoding bypass (URL/double/overlong) | decode fully and repeatedly (§6.3, §7) |
| Length check passes but buffer overflows | integer overflow/wrap or sign confusion | check the field's width and signedness (§4.3) |
| "Corrupt" text with strange characters | wrong character encoding assumed (UTF-8 vs Latin-1) | `file`, `iconv`, inspect bytes with `xxd` |
| A token "won't decrypt" | it is encoded (Base64/hex), not encrypted | `base64 -d` / `xxd -r -p` first (§6.3) |

---

## 15. Practical Lab

Lab 7.1 is in §8. Register it in the lab index. Extension: capture a single packet with
`sudo tcpdump -c1 -X -i any 'tcp port 443'` and decode its Ethernet + IP + TCP headers by hand
from the `-X` hex output, verifying each field against Wireshark. This is the direct bridge to
Chapter 24's packet-analysis workshop.

---

## 16. Exercises

### Concept questions

**7.1** Explain why hex is the natural notation for binary data, in terms of the nibble. How many
bits does one hex digit represent, and one byte?

**7.2** The byte `0xB4` — give its value as an unsigned integer, as a signed 8-bit integer, and
as a bit pattern. Which bits are set?

**7.3** Explain network byte order. Why did Chapter 3's socket code call `htons(443)`, and what
goes wrong if you omit it?

**7.4** Why is Base64 not a security control? Illustrate with a JWT.

**7.5** Explain, using the "two parties, different interpretation" model, how a double-URL-encoded
payload bypasses a single-decode WAF.

### Debugging problems

**7.6** A service binds to "port 443" but connections fail, and `ss -tlpn` shows it listening on
47873. What happened, and what is the fix?

**7.7** A length-prefixed protocol parser occasionally reads far past the buffer. The length
field is one byte. Give two distinct byte-level causes and how you would confirm each.

**7.8** A log shows `%25%32%65%25%32%65%25%32%66`. Decode it fully. How many decoding passes are
required to reach the final form, and what is it?

### Security scenarios

**7.9** Your WAF blocks `../` and `..%2f`. An attacker still achieves path traversal. Give three
distinct byte-level techniques they might have used and the correct defense for all three.

**7.10** During incident response you find a suspicious cookie value: a long string of
`[A-Za-z0-9+/]` ending in `==`. What is it, how do you inspect it safely, and what would you
look for?

### Hands-on exercises

**7.11** Write the eight legal subnet-mask octet values (from `/1` to `/8` within an octet) in
binary and decimal, from memory, then verify. (Preview of Chapter 10.)

**7.12** Decode this TCP flags sequence captured during a connection: `0x02, 0x12, 0x10, 0x18,
0x11, 0x10`. Name each and state what phase of a TCP connection it represents. (Preview of
Chapter 19.)

**7.13** Given the hex dump `48 54 54 50 2f 31 2e 31 20 34 30 31`, decode it as ASCII by hand,
then verify with `xxd -r -p`. What HTTP element is it?

### Interview questions

**7.14** "Walk me through decoding an IPv4 header from a hex dump."

**7.15** "Why is endianness a security concern, not just a correctness one?"

**7.16** "An attacker sends a payload your filter should have caught. Before you look at the
filter, what byte-level tricks do you consider?"

**7.17** "Is Base64-encoding sensitive data in a config file acceptable? Explain."

---

## 17. Summary

- Computers store and transmit only bits; every richer meaning is an **agreement** about how to
  interpret groups of bits, and **security bugs live where two parties' agreements differ**.
- **1 nibble = 4 bits = 1 hex digit; 1 byte = 8 bits = 2 hex digits = 0–255.** Hex is
  human-readable binary, four bits at a time.
- The eight place values `128 64 32 16 8 4 2 1` and the eight legal subnet-mask octets
  (128,192,224,240,248,252,254,255) should be automatic — they make CIDR arithmetic mental.
- **Bitmask testing (`x & mask`)** decodes protocol flags (TCP, IP), permission bits (PTE,
  capabilities, file modes), and firewall matches — one operation reused everywhere.
- **Network byte order is big-endian**; forgetting conversion (`htons`) is a real bug, and
  misreading endianness misleads forensics.
- **Encodings (hex, Base64, URL) are recognizable and reversible; Base64 is not encryption.**
  Attackers layer encodings to evade filters, exploiting decode-count mismatches between
  components — visible only if you can hand-decode.
- **Reading a hex dump** (with `xxd`, and by hand) makes packet headers and payloads legible, the
  literacy the rest of Part 1 assumes.
- Defensively: **canonicalize (fully decode + normalize) once at the earliest trust boundary,
  then allow-list on the canonical form** — so all parties share one interpretation.

---

## 18. Knowledge Check

1. How many bits in a nibble, a byte? How many hex digits represent a byte? (§3)
2. Convert 172 to binary and 0xC0 to decimal without a tool. (§4.1–4.2)
3. What are the only legal subnet-mask octet values, and why? (§4.1)
4. How do you test whether bit 4 is set in a byte? (§4.4)
5. Decode the TCP flags byte 0x12. (§4.4)
6. What is network byte order, and why did `htons(443)` matter? (§4.5)
7. Why is a JWT payload readable, and what does that imply? (§4.7, §6.3)
8. How does a double-URL-encoded payload bypass a single-decode filter? (§7)
9. Decode the first byte of an IPv4 header, `0x45`. (§5)
10. What is the correct defensive order: validate then decode, or decode then validate? (§11)

---

## 19. Further Exploration

- Keep a hex/decimal/binary conversion table taped to your monitor for a week; the fluency comes
  fast with exposure.
- CyberChef (gchq.github.io/CyberChef) — the "cyber swiss army knife" for chaining
  encode/decode/analyze operations. Recreate the §7 double-encoding bypass in it.
- `man ascii` — the full table; note the ranges rather than memorizing.
- Wireshark: capture any packet, then toggle between the decoded view and the raw bytes
  (bottom pane) and match each field to its bytes — the §5 exercise, interactively.
- Read the JWT spec's note that the payload is Base64url of JSON and is *not* confidential — the
  single most useful thing to internalize before Chapter 60.
- For endianness depth: `man 3 htons`, and Danny Cohen's classic "On Holy Wars and a Plea for
  Peace" (the paper that named big/little-endian).

---

## Solutions

### 7.1
Hex is natural for binary because one hex digit represents exactly one nibble (4 bits), so any
byte is exactly two hex digits with no ambiguity or wasted space. Binary is precise but long and
error-prone to read (`11000001`); decimal (193) hides the bit structure; hex (`0xC1`) is compact
*and* reversible to bits at a glance (C=1100, 1=0001). One hex digit = 4 bits; one byte = 8 bits
= 2 hex digits.

### 7.2
`0xB4` = `1011 0100`. Unsigned: 128+32+16+4 = 180. Signed 8-bit (two's complement): the high bit
is set, so it is negative: `1011 0100` → invert `0100 1011` → +1 = `0100 1100` = 76, so the value
is −76. Bits set: 7, 5, 4, 2 (values 128, 32, 16, 4).

### 7.3
Network byte order is big-endian: multi-byte fields are transmitted most-significant-byte-first.
`htons(443)` ("host to network short") converts the 16-bit port from the host's byte order (
little-endian on x86/ARM) to big-endian before placing it in the `sockaddr` structure. If you
omit it on a little-endian host, 443 (`0x01BB`) is placed as bytes `BB 01`, which the network and
peer interpret as `0xBB01` = 47873 — so you bind or connect to the wrong port. The conversion is
a no-op on big-endian hosts, which is why forgetting it can "work on one machine and fail on
another."

### 7.4
Base64 is a reversible encoding — it maps arbitrary bytes to a safe ASCII character set and back
with no key, so anyone can decode it. It provides no confidentiality. A JWT illustrates this: it
is three Base64url segments (`header.payload.signature`); the payload decodes to plain JSON like
`{"sub":"123","role":"admin"}` readable by anyone (`base64 -d`). The *signature* provides
integrity/authenticity (you cannot forge it without the key), but the payload is not secret. So
you must never put secrets in a JWT payload assuming Base64 hides them, and never treat a Base64
blob as protected — if it must be secret, encrypt it.

### 7.5
The WAF and the application are two parties that both decode the input, but a different number of
times. The attacker double-encodes `../` as `%252e%252e%252f` (where `%25` is an encoded `%`).
The WAF decodes once, producing `%2e%2e%2f` — which contains no literal `../` or `..%2f`, so its
filter passes it. The WAF forwards the still-once-encoded string. The application (or web server)
decodes again, producing `../`, and the traversal happens. Same bytes, two interpretations
because of two decode counts: the vulnerability is the gap between them, not either component
alone. Defense: decode fully and repeatedly until the string stops changing, normalize, then
validate — and ensure all components agree on the canonical form.

### 7.6
The service (or its config) placed the port in host byte order instead of network byte order —
it failed to call `htons()` (or the equivalent). 443 = `0x01BB`; sent little-endian as `BB 01`
and interpreted big-endian on the wire = `0xBB01` = 47873, which is exactly what `ss` reports.
Fix: convert the port to network byte order before binding (`htons(443)`), or in higher-level
code ensure the port is passed as an integer the library will convert correctly. Confirm by
noting 47873 = 0xBB01 is the byte-swap of 443 = 0x01BB.

### 7.7
(1) **Sign confusion:** the length byte is read as *signed*, so a value like `0xFF` is
interpreted as −1 (or a large value after a faulty conversion), defeating a `len < BUFSIZE`
check or producing a huge `memcpy` length. Confirm: check the declared type of the length
variable and test with a high-bit-set length byte. (2) **Unit/width mismatch:** the one-byte
length is treated as a count in a different unit (words vs bytes) or is multiplied/added to
without bounds checking, or a 1-byte field cannot express the true length (≥256) so it wraps and
the parser reads a stale larger value. Confirm: feed lengths around 127/128 and 255/0 boundaries
and watch behavior; inspect whether the code validates the length against the *actual* remaining
buffer. Both are the "value doesn't fit / is misinterpreted in its bits" class (§4.3).

### 7.8
`%25%32%65` : `%25`=`%`, `%32`=`2`, `%65`=`e` → `%2e`. So the string decodes in the first pass to
`%2e%2e%2f`, and in the second pass `%2e%2e%2f` → `../`. Two decoding passes are required. Final
form: `../` (a single traversal step). The full input `%25%32%65%25%32%65%25%32%66` → pass 1:
`%2e%2e%2f` → pass 2: `../`. It is a triple-obfuscation (each character of `%2e` itself encoded),
and it defeats any filter that does not decode to a fixed point.

### 7.9
Techniques: (1) **Double (or triple) URL-encoding** — `%252e%252e%252f` (decodes to `%2e%2e%2f`
then `../`), bypassing a filter that decodes fewer times. (2) **Overlong / alternate UTF-8
encoding** — `..%c0%af` or `%e0%80%af` for `/` (historically accepted by some decoders), which
does not match `..%2f`. (3) **Alternate separators / mixed encoding / backslashes** — `..%5c`
(`\`) on systems treating `\` as a separator, or `%2e%2e/` (mixing encoded and literal). Correct
defense for all three: do not deny-list encodings at all — **canonicalize fully** (decode
repeatedly to a fixed point, normalize Unicode and path), then either allow-list the canonical
path against an expected set or, best, **never construct filesystem paths from user input**
(map an opaque identifier to a known safe path, Chapter 53). Deny-listing raw byte patterns is
structurally doomed because there are unbounded equivalent encodings.

### 7.10
It is almost certainly **Base64** (character set `[A-Za-z0-9+/]`, `==` padding, length a multiple
of 4). Inspect it safely by decoding without executing: `echo "<value>" | base64 -d | xxd`
(pipe through `xxd` so non-printable/binary content is shown as hex rather than dumped to the
terminal, which avoids terminal-escape mischief). Look for: readable JSON (a serialized session
or token — check for `role`/`admin`/`user` fields and whether it is signed), a serialized object
(a deserialization risk, Chapter 54 — e.g. Java/PHP/.NET object markers), binary that is itself
another encoding or ciphertext, or PII. Determine whether the value is signed/encrypted or merely
encoded (if it decodes to plain readable data, it is unprotected and possibly tamperable — test
whether modifying it is accepted). Note it could also be Base64url (`-`/`_` instead of `+`/`/`),
common in JWTs and cookies.

### 7.11
Legal subnet-mask octet values are runs of leading 1s: `/1`→`10000000`=128, `/2`→`11000000`=192,
`/3`→`11100000`=224, `/4`→`11110000`=240, `/5`→`11111000`=248, `/6`→`11111100`=252,
`/7`→`11111110`=254, `/8`→`11111111`=255. Each is the previous plus the next place value
(128, +64, +32, +16, +8, +4, +2, +1). They are the only legal values because a subnet mask is
always a contiguous block of 1s followed by 0s (no gaps), so within an octet only these eight
(plus 0) can occur. Memorizing them makes Chapter 10's subnetting mental arithmetic.

### 7.12
`0x02` = SYN (client opens: SYN_SENT). `0x12` = SYN+ACK (server responds: SYN_RCVD). `0x10` = ACK
(client completes the handshake: ESTABLISHED — this is the three-way handshake). `0x18` = ACK+PSH
(data transfer: PSH pushes buffered data to the app). `0x11` = FIN+ACK (one side begins closing).
`0x10` = ACK (acknowledging the FIN). So the sequence is: connection establishment (SYN, SYN-ACK,
ACK), data transfer (PSH-ACK), then connection teardown (FIN-ACK, ACK) — the full life of a TCP
connection, which Chapter 19 details.

### 7.13
`48`=H `54`=T `54`=T `50`=P `2f`=/ `31`=1 `2e`=. `31`=1 `20`=(space) `34`=4 `30`=0 `31`=1 →
`HTTP/1.1 401`. It is the start of an HTTP response status line — HTTP version 1.1, status code
401 (Unauthorized). Verify: `echo "485454502f312e3120343031" | xxd -r -p` → `HTTP/1.1 401`.

### 7.14
Take the bytes in order and split by field using nibble/mask/big-endian operations: byte 0 high
nibble = version (`4`), low nibble = header length in 32-bit words (×4 = header bytes); byte 1 =
DSCP/ECN; bytes 2–3 = total length (big-endian); bytes 4–5 = identification; bytes 6–7 = flags
(top 3 bits: reserved, DF, MF) + 13-bit fragment offset (so test byte 6 with `& 0x40` for DF,
`& 0x20` for MF); byte 8 = TTL; byte 9 = protocol (6 TCP, 17 UDP, 1 ICMP); bytes 10–11 = header
checksum; bytes 12–15 = source IP (one octet per byte); bytes 16–19 = destination IP; any
remaining bytes up to the header length are options. Demonstrate on `45 00 00 3c ...`: version 4,
20-byte header, total length 60, DF set, TTL 64, TCP, src 10.0.1.11, dst 10.0.2.10. Bonus: note
big-endian for total length and that the source/dest IPs read directly as octets.

### 7.15
Because a byte-order mismatch changes the *value* two systems compute from the same bytes, and
values drive security decisions. Concretely: a length or offset field misread due to endianness
produces a wrong size, enabling buffer over-reads/writes (Chapter 22, memory-safety); an address
or port misread routes/filters incorrectly; a comparison against an expected value silently fails
or succeeds. In exploit development and forensics, misreading endianness in a dump yields wrong
addresses and wrong conclusions. And when two implementations (client/server, or a parser and a
validator) assume different byte orders, the interpretation gap is exploitable — the same
"two parties disagree" root cause as encoding bypasses. So endianness is a correctness issue that
becomes a security issue precisely because security depends on all parties computing the same
value from the same bytes.

### 7.16
Before blaming the filter, consider that the *same payload* can be represented many ways the
filter may not have normalized: URL-encoding, double/triple URL-encoding, overlong or alternate
UTF-8 encodings, mixed case where matching is case-sensitive, alternate separators (`\` vs `/`),
null-byte truncation (`%00`), Unicode normalization differences and homoglyphs, whitespace/comment
insertion (for SQL/HTML), and layered encodings (Base64 inside URL-encoding). The common thread
is that the filter and the downstream component canonicalize differently or a different number of
times. The fix is not another deny-list entry but canonicalization to a fixed point plus
allow-listing on the canonical form — so I would check what canonicalization the filter does and
whether it matches the consumer, rather than adding one more pattern.

### 7.17
Base64-encoding sensitive data in a config file is **not** acceptable as a security measure,
because Base64 is trivially reversible by anyone who reads the file (`base64 -d`) — it provides
zero confidentiality and only obscures the value from casual glancing, which creates a false
sense of protection. It is acceptable only as a *transport/formatting* convenience (e.g. encoding
binary key material so it fits in a text field), never as protection. If the data is sensitive it
must be either kept out of the file entirely (fetched at runtime from a secrets manager with
short-lived credentials, Chapter 68) or encrypted with a key managed separately (Chapters 25–26,
80). The correct reflex: "Base64 in a config = plaintext in a config."

---

*Next: Chapter 8 — Layer 2: MAC Addresses, Ethernet Frames, NICs, Switches, and Broadcast
Domains. Now that you can read bytes and headers, we start at the bottom of the network stack —
the frame — and build upward, decoding real Ethernet headers with the skills from this chapter.*
