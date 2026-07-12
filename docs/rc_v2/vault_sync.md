# Serverless, conflict-free Vault sync

*Module: `reality_compiler/v2/vault_sync.py` · Tests: `test_vault_sync.py` ·
Extra: `pip install dreamlayer[sync]`*

## The problem

The Vault (`vault.py`) is the user's Repertoire — their kept Figments and,
just as load-bearing, their **revocations**. A user with more than one device
(phone + a spare, phone → new phone on upgrade, an heirloom rhythm passed on)
expects that Repertoire to be the same everywhere. But the privacy contract
(`docs/PRIVACY_MODEL.md`) forbids a server holding their figments — so sync has
to happen **directly between the user's own devices**, over whatever channel is
handy: BLE, AirDrop, a QR of the blob, a LAN socket.

Peer-to-peer sync over an unreliable channel is exactly where a naive
"newest wall-clock wins" design quietly loses data:

- a blob is dropped, or delivered twice, or arrives out of order;
- two devices edit their Vaults while apart and later meet;
- clocks disagree, so "newest" is a lie.

## The approach: a CRDT, not a merge

Sync state is a **Conflict-free Replicated Data Type** (Loro). CRDT merge is
commutative, associative, and idempotent, so:

- replaying a blob twice is a no-op;
- receiving blobs in any order yields the same state;
- `A → B → A` converges — there is no "which device is authoritative" question
  and no merge conflict to resolve by hand.

The CRDT mirrors two maps:

| container  | key → value                                   | semantics |
|------------|-----------------------------------------------|-----------|
| `figments` | id → `{content_hash, figment, kept_at, origin}` | last-writer-wins register per id |
| `revoked`  | id → `True`                                   | **grow-only** set — monotone |

Revocation as a grow-only set is the crucial choice: durable revocation is
inherently monotone (`docs/RC_V2_ATTACKS.md` A2), and monotone state is the
friendliest possible thing for a CRDT. Once any device revokes an id, that fact
can only spread, never un-happen.

## Materializing back into the Vault

After merge, `materialize()` reconciles the CRDT into the local Vault in a fixed
order so the safety properties hold regardless of concurrency:

1. **Revocations first.** Every revoked id is unioned into the local revocation
   list *before* any re-keep is considered — so a stale device re-adding a
   figment the user already banished can never resurrect it. **Revoke wins.**
2. **Re-keep active figments** that are new here and pass an integrity check:
   the embedded `content_hash` (key-independent, from `signer.content_hash`)
   must equal the recomputed hash of the figment body. A figment mutated in
   transit fails this and is **refused, not kept** (surfaced in
   `SyncReport.tampered`, `ok == False`).

## Why re-signing is correct, not a downgrade

The per-install signature is HMAC (`signer.py`) — symmetric, so a figment
signed by device A's key cannot be verified by device B without sharing the key,
which would break the per-install model. So a synced figment is **re-kept
locally**, re-signing with *this* install's key. Provenance stays per-install
(exactly as `keep()` always worked); end-to-end **integrity** is carried by the
key-independent `content_hash`. The origin device's `kept_at` is preserved so
the figment's place in the Repertoire timeline survives the crossing.

## API

```python
a = VaultSync(vault_a, peer="phone"); a.stage()
b = VaultSync(vault_b, peer="tablet")
report = b.merge(a.export_bytes())   # a's repertoire lands on b, conflict-free
# report.added / report.revoked / report.unchanged / report.tampered
```

`export_bytes()` returns a self-contained snapshot blob for any transport;
`merge()` = stage + import + materialize, the one call a device makes on a peer
blob. The exchange is symmetric — both sides `merge` the other's blob and
converge.

## Guarantees, tested

- **Convergence** under scrambled + duplicated delivery across three devices.
- **Idempotency** — replaying a blob adds nothing the second time.
- **Revoke wins** over a concurrent keep, and propagates to a device that never
  held the figment.
- **Tamper refusal** — a lying `content_hash`, or honest hash over a swapped
  body, is refused and never enters the Vault.
