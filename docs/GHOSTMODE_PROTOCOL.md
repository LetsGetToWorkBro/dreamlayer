# The GhostMode Protocol — v1.0

**A wire specification for the DreamLayer glasses-to-glasses mesh.**

> Status: **Stable draft (v1.0).** This document specifies the wire format,
> cryptography, and behaviour of GhostMode — the peer-to-peer mesh that lets
> DreamLayer wearers share *feeling* (weather, bearing, gesture) directly, with
> no cloud, no account, and no server in the transaction. It is published as
> openly as the figment grammar (`reality_compiler/v2/figment.py`) on purpose
> (see §13). A conforming implementation in any language interoperates with the
> reference implementation in `host-python/src/dreamlayer/confluence/`.

The keywords **MUST**, **MUST NOT**, **SHOULD**, **MAY** are used per RFC 2119.

---

## 1. Why this exists (the topology thesis)

Every closed AR platform is a **star**: device → their cloud → device, with the
business at the centre of the star. GhostMode is a **mesh**: a circle of Halos
exchanging tiny signed packets *directly*, over radio, with no centre. Two
DreamLayer wearers on the same trail, in the same blackout, at the same protest
or festival are connected in a way no star-topology product can replicate
without deleting its own business model — the centre would be missing from the
transaction.

This spec is the part of that idea you can build **before silicon**: the wire
format, the crypto, the privacy invariants. When the radio lands, the mesh is
"only" a transport.

**Design goals**
- **Feeling, not content.** Only a weather scalar, a bearing+distance band, or a
  gesture symbol ever crosses. Never speech, never absolute coordinates, never
  names.
- **Anonymous on the wire.** A member is a random id and nothing else. Human
  names ("that pulse is Maya") live only on the observer's own device.
- **No centre, no account.** A group is formed by a spoken human code, not a
  login. There is nothing to sign up for and nothing to seize.
- **Provably bounded.** Packets are tiny and rate-limited; a hostile member
  cannot flood your senses (the same budget discipline as figments).

**Non-goals.** GhostMode is not a messaging system, not a file transport, not a
location-sharing service, and not reliable delivery. It is best-effort presence.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Wearer / member** | A device participating in a group. Identified on the wire only by a random `member_id`. |
| **Group / circle** | A set of members sharing one symmetric **group key**, formed by a human code. |
| **Bond** | The pairwise (2-member) special case (`confluence/bond.py`); GhostMode is the N-member generalisation. |
| **Packet** | One signed, anonymous unit of traffic (§7). |
| **The Beacon** | The first application riding the mesh: a crowd-finder that emits bearing+distance (§10). |
| **Transport** | The `send/recv` seam under the protocol. BLE LE Coded PHY on Halo; an in-memory bus in tests. |

---

## 3. Layering

```
  ┌─────────────────────────────────────────────┐
  │ Application   weather · Beacon(bearing) ·     │  §9, §10
  │               gesture · figment bond: events  │
  ├─────────────────────────────────────────────┤
  │ Mesh          group key · seq · TTL flood ·   │  §6, §7, §8
  │               dedup · replay drop · veil gate │
  ├─────────────────────────────────────────────┤
  │ Frame         canonical JSON + HMAC MAC       │  §7
  ├─────────────────────────────────────────────┤
  │ Transport     BLE LE Coded PHY (S=8) /         │  §5
  │               phone relay / in-memory bus      │
  └─────────────────────────────────────────────┘
```

Nothing above the Transport seam knows the radio; nothing below the Mesh layer
knows the meaning. This is what makes the radio swappable and the privacy claims
auditable.

---

## 4. Versioning

This is protocol **v1**. The version is carried out-of-band at group-formation
time (both sides run the same DreamLayer release today). A future revision that
changes the frame **MUST** add a `v` field to the packet and negotiate the
minimum common version at join; a v1 implementation **MUST** ignore packets whose
`kind` it does not recognise (forward compatibility) rather than reject the
group.

---

## 5. Physical & link layer

- **Radio: BLE 5, LE Coded PHY, coding S=8 (~125 kbps).** Chosen for **range and
  robustness in RF-noise**, not throughput — GhostMode packets are tiny (a
  weather packet is a scalar + four palette indices), so bandwidth is irrelevant
  and range is everything.
- **Reach.** Where two Halos are out of direct radio range, a paired **phone
  relays** for its wearer (the phone is the body; the glasses show). The relay is
  a dumb repeater of already-signed frames — it authenticates nothing and learns
  nothing it could not already see on air.
- **Discovery.** A member advertises presence with a rotating, non-identifying
  advertising payload; connection/gossip carries the frames of §7. The
  advertising payload **MUST NOT** contain a stable identifier, a name, or a
  location.
- **Framing on the wire.** GhostMode frames are transported using the same
  length-prefixed canonical-JSON envelope the rest of DreamLayer uses
  (`reality_compiler/v2/transport.py`: a 4-byte big-endian length header + the
  canonical-JSON body, 16 KiB max frame). A GhostMode body is *far* smaller than
  that cap — see §12.

The Transport is a strict seam: any object providing `send(wire: dict)` and
`recv() -> list[dict]` conforms. The reference `InMemoryBus` stands in for the
coded-PHY flood in tests and the simulator.

---

## 6. Identity & keys

GhostMode has **no accounts and no PKI**. Trust is established by a spoken human
code, exactly like a bond, just shared with more people.

- **Member id.** On joining, a member picks a fresh random id:
  `member_id = 96-bit random`, rendered as 12 lowercase hex chars
  (`secrets.token_hex(6)`). It is ephemeral — a new one **SHOULD** be minted per
  group, and **MUST NOT** be derived from any hardware identifier, name, or
  account.
- **Group id.** The forming member mints `group_id = 96-bit random` (12 hex
  chars).
- **Human code.** The forming member mints a 3-word code from the shared word
  list (`bond.py: _WORDS`), e.g. `amber-tide-fox`, and speaks/shows it to the
  others out-of-band. (A pairwise bond uses 2 words; a group uses 3.)
- **Group key derivation (normative):**

  ```
  group_key = SHA-256( "ghostmesh|" ‖ group_id ‖ "|" ‖ code )      // 32 bytes
  ```

  All members who were told `(group_id, code)` derive the identical 256-bit key.
  Nobody who was not told the code can derive it, and the code never crosses the
  wire.

There is no key rotation within a group's lifetime; a group is short-lived by
design (§11), and forward secrecy across groups is provided by minting a new
`group_id`, code, and member id for each new circle.

---

## 7. Frame format

A GhostMode frame is a **MeshPacket** (`confluence/mesh.py: MeshPacket`).

### 7.1 Fields

| Field | Type | Notes |
|---|---|---|
| `group_id` | string (12 hex) | which circle |
| `sender` | string (12 hex) | the anonymous member id |
| `seq` | integer ≥ 1 | strictly increasing per sender, per group |
| `kind` | string | `"weather"` \| `"bearing"` \| `"gesture"` (§9) |
| `body` | object | small, kind-specific (§9) |
| `mac` | string (24 hex) | authentication tag (§7.3) |

### 7.2 Canonical payload

The **signed payload** is the canonical JSON of the five content fields (i.e.
everything except `mac`), with keys sorted and no whitespace:

```
payload = JSON( {group_id, sender, seq, kind, body}, sort_keys=true, separators=(",", ":") )
```

Canonicalisation is mandatory and is what makes the MAC reproducible across
implementations. `body` is itself canonicalised (its keys sorted) by the same
rule.

### 7.3 Authentication tag

```
mac = HMAC-SHA-256( group_key, payload )   truncated to the first 96 bits
                                           rendered as 24 lowercase hex chars
```

The wire frame is the payload fields plus `mac`:

```
wire = { ...payload_fields, "mac": mac }
```

### 7.4 Test vector (normative)

An implementation is conformant iff it reproduces this MAC bit-for-bit.

```
group_id : 7f3a9c1b2d4e
code     : amber-tide-fox
group_key: 7e98870b287be188f0707eee57bbc1cb5032a1898cf6502d99a055546315fd9e   (SHA-256)

packet   : sender=a1b2c3d4e5f6  seq=1  kind=weather  body={"state":0.62,"colors":[3,7,11,14]}

payload  : {"body":{"colors":[3,7,11,14],"state":0.62},"group_id":"7f3a9c1b2d4e","kind":"weather","sender":"a1b2c3d4e5f6","seq":1}
mac      : 9343bef912ce997c91d611e3

wire     : {"body":{"colors":[3,7,11,14],"state":0.62},"group_id":"7f3a9c1b2d4e","kind":"weather","sender":"a1b2c3d4e5f6","seq":1,"mac":"9343bef912ce997c91d611e3"}
```

---

## 8. Receive rules (normative)

On receiving a `wire`, an implementation **MUST** drop it silently (no error, no
reply, no side effect) if **any** of the following hold, in this order:

1. **Group dead.** The local group is dissolved or older than `GROUP_TTL_S`.
2. **Malformed.** `wire` is missing a required field or a field has the wrong
   type.
3. **Wrong circle.** `group_id` ≠ the local group.
4. **Self-echo.** `sender` == my own `member_id`.
5. **Forged.** `HMAC(group_key, recomputed_payload)` ≠ `mac`
   (constant-time comparison **MUST** be used).
6. **Replay / reorder.** `seq` ≤ the last accepted `seq` from that `sender`.

Only a packet passing all six updates the sender's `MeshMember` state
(`last_seq`, `last_seen`, `kind`, `body`). This is the complete dedup + replay
defence: monotonic per-sender sequence numbers under a MAC the attacker cannot
forge. There is **no acknowledgement and no retransmission** — GhostMode is
best-effort.

**Flood forwarding (mesh relay).** A member that also forwards (a multi-hop
mesh) **MUST** attach a short TTL and dedup by `(sender, seq)` before
re-broadcasting, and **MUST** decrement TTL and drop at zero. v1 reference
deployments are single-hop (phone-relayed); the TTL/dedup rule is specified so
multi-hop forwarders interoperate safely.

---

## 9. Message kinds

`body` is small and kind-specific. Unknown kinds **MUST** be ignored (§4).

| `kind` | `body` | Meaning |
|---|---|---|
| `weather` | `{ "state": float 0..1, "colors": [int×4] }` | Your inner-weather scalar + four palette-bank indices. The only thing a partner's ring carries about your day. |
| `bearing` | `{ "bearing_dd": int 0..3599, "dist": "close"\|"near"\|"far" }` | The Beacon (§10): where you are *relative to yourself*, in decidegrees + a coarse band. |
| `gesture` | `{ "sym": string }` | A single gesture symbol (e.g. a shared TinCan tap pattern id or a `bond:tag:<t>`). |

**Mapping to figment `bond:` events.** The figment grammar's presence events
(`bond:near`, `bond:tag:<t>` — see the figment spec) are produced *from* received
GhostMode packets: a fresh `bearing` packet in the `close`/`near` band raises
`bond:near`; a `gesture` packet whose `sym` matches `t` raises `bond:tag:<t>`.
The mesh is the transport; the figment grammar is what a wearer's *own* installed
behaviours may react to. Both firing sides are already rate-limited, so a
partner's emit cannot flood your figment.

---

## 10. The Beacon (finds your people through a crowd)

The Beacon (`confluence/beacon.py`) is the first application on the mesh and
**ships first**. It rides `kind: "bearing"`.

- **Emit.** A member broadcasts `bearing_dd = round(bearing_deg × 10) mod 3600`
  (0 = ahead, increasing clockwise) and `dist ∈ {close, near, far}` where the
  band is derived from metres: `≤8 m → close`, `≤40 m → near`, else `far`. **A
  raw distance in metres and any absolute coordinate MUST NOT be sent** — only
  the band crosses.
- **Render.** On your rim, each fresh member is a pulse train at their bearing;
  nearer people pulse **faster and brighter** (`close (bright≈160, gap 140 ms)`,
  `near (120, 260)`, `far (90, 420)`). No map, no "where are you" text.
- **Names.** The card shows a member by the **local alias** you set, or a neutral
  tag. A name never crosses the wire.

The Beacon is deliberately the minimum a crowd-finder needs: a direction and a
sense of *warmer / colder*. That is all it is willing to send.

---

## 11. Group lifecycle

- **Form / join.** `form()` mints `(group_id, code)`; others `join(group_id,
  code)`. Both derive the same key (§6).
- **TTL.** A group is live for `GROUP_TTL_S = 8 h` (an evening, not a tracker).
  After that it is dead and all traffic drops until renewed.
- **Quiet fade.** A member that has not been heard for `QUIET_FADE_S = 12 s` is
  no longer *fresh* and fades from the circle's live view (their last state is
  kept but marked stale).
- **Leave.** Leaving is unilateral and local (`leave()` dissolves your view);
  there is no "leave" packet and no permission needed.

### 11.1 Where a circle is formed today

Pre-hardware, the Brain plays the honest role it can — the **meeting point** —
exactly as `live_confluence.py` does for the pairwise bond. `LiveCircle`
(`ai_brain/server/live_circle.py`) holds one real `MeshManager` per session and
an inbox per member, standing in for the coded-PHY flood:

| Route | What it does |
|---|---|
| `POST /dreamlayer/live/circle/form` | mints `(group_id, code)` — the three words you say to the room |
| `POST /dreamlayer/live/circle/join` | joins by code (the group id is optional; nobody says one aloud) |
| `POST /dreamlayer/live/circle/pulse` | one beat: your feeling out, everyone's in, plus the DP group summary |
| `POST /dreamlayer/live/circle/alias` | names a pulse **locally**; never crosses |
| `POST /dreamlayer/live/circle/leave` | unilateral, per §11 |

Everything normative above is enforced by `MeshManager` itself — the room adds
no crypto, no receive rule, and no vocabulary of its own. Traffic in both
directions goes through `MeshEventBus`, which publishes only when the mesh
actually produced a packet, so a subscriber can never observe one the Veil
refused to make.

---

## 12. Rate limiting, size, and duty cycle

- **Packet size.** A GhostMode body is a handful of small fields; a full frame is
  well under 256 bytes and **MUST** stay under the 16 KiB transport cap. An
  implementation **SHOULD** reject an oversized body rather than transmit it.
- **Emit rate.** Application emits (weather, bearing) are ambient and **SHOULD**
  be paced (e.g. bearing at ~1–2 Hz, weather on change). A conforming
  implementation **MUST NOT** allow a remote member's traffic to drive local
  display faster than the figment display budget (≤4 Hz pulse), regardless of
  how fast packets arrive — the *receiver* clamps, exactly as the figment stage
  clamps a pulse.
- **Duty cycle.** The radio is duty-cycled; presence is periodic, not streamed.

These bounds are what make "a hostile member cannot hurt your senses" a
structural fact rather than a policy.

---

## 13. Privacy invariants (what a passive observer learns)

A passive radio observer of GhostMode learns **only**:

- that some anonymous ids are exchanging small packets in some group id;
- packet sizes and timing.

A passive observer learns **nothing** about:

- **who** anyone is (ids are random and ephemeral, names never cross);
- **where** anyone is (only self-relative bearing + a 3-value band ever crosses —
  never coordinates);
- **what** anyone said (speech never crosses; a weather packet is a float + four
  palette indices).

A group member additionally learns the *feeling* traffic of the circle, but
still never a name (aliases are local) or an absolute location. **The Privacy
Veil silences a member's own emit completely** (`emit()` returns nothing while
veiled), so a wearer can go dark unilaterally and instantly.

This is the same contract as a pairwise bond, one level up, and it is why the
protocol can be published in full: reading it does not weaken it.

---

## 14. Security model

- **Authenticity & integrity:** every packet carries an HMAC-SHA-256 (96-bit) tag
  under the group key. An attacker without the key cannot forge or tamper with a
  packet; a bad tag drops silently.
- **Replay & reorder:** monotonic per-sender sequence numbers under the MAC. A
  captured packet cannot be replayed (its `seq` is stale) and cannot be reordered
  into acceptance.
- **Membership:** knowledge of the spoken code *is* membership. There is no
  central authority to compromise. A code is short-lived and shared out-of-band
  (voice, a shown card), never on the wire.
- **Confidentiality:** v1 authenticates but does **not** encrypt the body — and
  it does not need to, because the body is *designed to be safe in the clear*
  (a float, four palette indices, a coarse bearing). This is a deliberate
  minimisation: nothing secret is ever put on the wire, so there is nothing to
  encrypt. (A future profile MAY add authenticated encryption for richer bodies;
  v1 does not carry any.)
- **Forward secrecy across groups:** fresh `group_id` + code + member id per
  circle. Compromising one evening's group key reveals nothing about another.
- **Truncation:** the 96-bit MAC is sized for tiny, short-lived, low-value
  presence traffic where the cost of a forgery is one spurious pulse; it is not a
  general-purpose message authenticator and **MUST NOT** be reused for anything
  carrying content.

**Threat model, explicitly.** GhostMode defends against forgery, tampering,
replay, stranger/self injection, and passive identity/location inference. It does
**not** defend against traffic analysis of packet timing/size by a global passive
adversary (mitigated only by how little is sent), nor against a legitimate group
member misbehaving *within* the tiny allowed vocabulary (mitigated by receiver
rate-clamping and the Veil).

---

## 15. Reference implementation map

| Spec section | Reference code (`host-python/src/dreamlayer/`) |
|---|---|
| Mesh, packet, receive rules, key derivation, MAC | `confluence/mesh.py` (`MeshManager`, `MeshPacket`, `_derive_group_key`, `_mac`) |
| Pairwise (2-member) special case | `confluence/bond.py` (`BondManager`) |
| The Beacon | `confluence/beacon.py` (`Beacon`, `dist_band`, `BeaconContact`) |
| Transport seam / in-memory bus | `confluence/mesh.py` (`MeshTransport`, `InMemoryBus`); `confluence/relay_transport.py` for the phone-relayed path |
| The room a circle is actually formed in | `ai_brain/server/live_circle.py` (`LiveCircle`, routes `/dreamlayer/live/circle/*`) |
| Pub/sub around mesh traffic | `confluence/emitter_pyee.py` (`MeshEventBus`) |
| Frame envelope (length header + canonical JSON) | `reality_compiler/v2/transport.py` |
| Figment `bond:` events produced from packets | `reality_compiler/v2/figment.py` (`BOND_EVENTS`, `bond:tag:<t>`) |
| Platform placement | [`PLATFORM.md`](./PLATFORM.md) Pillar 2 |

---

## 16. Conformance checklist

A conforming GhostMode v1 implementation:

1. derives `group_key` per §6 and reproduces the §7.4 test vector MAC exactly;
2. canonicalises payloads per §7.2 (sorted keys, no whitespace, recursive);
3. applies the six receive rules of §8 in order, dropping silently;
4. enforces monotonic per-sender `seq` and never accepts a replay;
5. sends only the three kinds of §9 with the bodies specified, and ignores
   unknown kinds;
6. never puts a name, an absolute coordinate, a raw distance, or speech on the
   wire (§13);
7. silences its own emit while the Privacy Veil is up;
8. clamps *local display* to the figment display budget regardless of inbound
   packet rate (§12).

---

## 17. Why it is published

The figment grammar is public so that "behaviours are provably safe" can be
*checked*, not trusted. GhostMode is public for the same reason, and one more:
a mesh whose format anyone can implement is a **commons**. A wearer is not a
customer at the edge of someone's star — they are a node in a network that has no
centre to own. That is the thing a closed platform cannot copy without ceasing to
be one, and it is why the buildable half of GhostMode — this document — ships
before the radio does.
