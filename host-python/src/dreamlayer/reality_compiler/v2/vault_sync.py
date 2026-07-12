"""v2/vault_sync.py — serverless, conflict-free multi-device Vault sync.

A user with two devices (phone + a spare, phone + tablet, an heirloom passed to
a new phone) wants their Repertoire — the kept Figments and, just as importantly,
their revocations — to be the same everywhere, *without a server holding their
figments*. The privacy contract forbids a cloud copy; sync happens directly
between the user's own devices (BLE, AirDrop, a QR of the blob, a LAN socket).

Peer-to-peer sync over an unreliable channel is where naive "last writer wins
by wall-clock" quietly loses data: a dropped exchange, a reordered one, two
devices editing while apart. So the sync state is a CRDT (Loro): merge is
commutative, associative, and idempotent — replay a blob twice, receive them
out of order, sync A→B→A, and the result is identical. There is no merge
conflict to resolve by hand and no "which device is authoritative" question.

The CRDT mirrors two pieces of vault state:

  figments: id -> {content_hash, figment, kept_at, origin}
  revoked:  id -> True          (grow-only: durable revocation is monotone)

Materializing the merged CRDT back into a Vault:

  * a figment in the CRDT, absent locally, **not revoked**, whose embedded
    content_hash matches its content, is re-kept locally. The signature is
    re-minted with *this* install's session key (provenance stays per-install,
    exactly as keep() always worked); end-to-end integrity is pinned by the
    key-independent content_hash, so a figment mutated in transit is refused.
  * every revoked id is unioned into the local revocation list. Revocation
    **wins** over any concurrent re-keep — a stale device re-adding a figment
    the user already banished cannot resurrect it.

Seam pattern: loro is a lazy import behind ``available``; with it absent the
class raises a clear error at construction and the rest of the system is
unaffected (pip install dreamlayer[sync]).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .figment import Figment
from .signer import SigningError, content_hash
from .vault import Vault

try:  # pragma: no cover - exercised both ways in CI via the extra
    import loro as _loro
    available = True
except Exception:  # pragma: no cover
    _loro = None
    available = False

_FIGMENTS = "figments"
_REVOKED = "revoked"


@dataclass
class SyncReport:
    """What a merge did to the local vault — surfaced to the UI and health."""
    added: list[str] = field(default_factory=list)        # newly re-kept ids
    revoked: list[str] = field(default_factory=list)       # newly revoked ids
    unchanged: int = 0                                      # already in step
    tampered: list[str] = field(default_factory=list)      # content_hash mismatch

    @property
    def ok(self) -> bool:
        return not self.tampered

    def __str__(self) -> str:
        return (f"SyncReport(added={self.added}, revoked={self.revoked}, "
                f"unchanged={self.unchanged}, tampered={self.tampered})")


class VaultSync:
    """CRDT-backed sync for one :class:`Vault`.

    Typical exchange between two of a user's devices::

        a = VaultSync(vault_a, peer="phone"); a.stage()
        b = VaultSync(vault_b, peer="tablet"); b.stage()
        report_b = b.merge(a.export_bytes())   # a's repertoire lands on b
        report_a = a.merge(b.export_bytes())   # and vice versa

    After both merges the two vaults hold the same active figments and the same
    revocation set, regardless of exchange order or duplication.
    """

    def __init__(self, vault: Vault, peer: str = "",
                 blob: Optional[bytes] = None) -> None:
        if not available:
            raise RuntimeError(
                "VaultSync needs the 'loro' CRDT library — "
                "pip install dreamlayer[sync]")
        self.vault = vault
        self.peer = peer or "device"
        self.doc = _loro.LoroDoc()
        if blob is not None:
            self.doc.import_(blob)

    # ------------------------------------------------------------------
    # Local vault -> CRDT
    # ------------------------------------------------------------------

    def stage(self) -> None:
        """Fold the current vault state into the CRDT (idempotent).

        Every active entry is (re)published with its content_hash and origin;
        every revoked id is marked. Publishing an unchanged entry is a no-op at
        the CRDT layer, so staging repeatedly costs nothing and never regresses.
        """
        figs = self.doc.get_map(_FIGMENTS)
        rev = self.doc.get_map(_REVOKED)
        for entry in self.vault.list(include_revoked=True):
            fid = entry.figment.id
            if entry.revoked:
                if rev.get_value().get(fid) is not True:
                    rev.insert(fid, True)
                continue
            record = {
                "content_hash": content_hash(entry.figment),
                "figment": entry.figment.to_dict(),
                "kept_at": entry.kept_at,
                "origin": self.peer,
            }
            payload = json.dumps(record, sort_keys=True)
            cur = figs.get_value().get(fid)
            if cur != payload:
                figs.insert(fid, payload)
        # local revocations that predate this doc (revoked.json) also fold in
        for fid in self.vault._revoked():
            if rev.get_value().get(fid) is not True:
                rev.insert(fid, True)
        self.doc.commit()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def export_bytes(self) -> bytes:
        """A self-contained snapshot blob — hand it to a peer over any channel.
        Importing it is order- and duplicate-independent."""
        self.doc.commit()
        return self.doc.export(_loro.ExportMode.Snapshot())

    def import_bytes(self, blob: bytes) -> None:
        """Merge a peer's blob into the CRDT (no vault writes yet)."""
        self.doc.import_(blob)

    # ------------------------------------------------------------------
    # CRDT -> local vault
    # ------------------------------------------------------------------

    def materialize(self) -> SyncReport:
        """Reconcile the merged CRDT into the vault. Revocation wins; a figment
        whose content doesn't match its embedded hash is refused, not kept."""
        report = SyncReport()
        figs = self.doc.get_map(_FIGMENTS).get_value()
        revoked_ids = set(self.doc.get_map(_REVOKED).get_value().keys())

        # 1) revocations first, so a re-keep below can never beat a banish
        already_revoked = self.vault._revoked()
        for fid in sorted(revoked_ids):
            if fid not in already_revoked:
                self.vault.revoke(fid)
                report.revoked.append(fid)

        # 2) re-keep active figments that are new here and content-verified
        for fid in sorted(figs):
            if fid in revoked_ids:
                continue
            try:
                record = json.loads(figs[fid])
                fig = Figment.from_dict(record["figment"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                report.tampered.append(fid)
                continue
            if content_hash(fig) != record.get("content_hash"):
                report.tampered.append(fid)      # mutated in transit — refuse
                continue
            local = self._local_hash(fid)
            if local == record.get("content_hash"):
                report.unchanged += 1
                continue
            self.vault.keep(fig, kept_at=record.get("kept_at"))
            report.added.append(fid)
        return report

    def merge(self, blob: bytes) -> SyncReport:
        """stage + import + materialize — the one call a device makes on a peer
        blob. Staging first ensures our own state is in the doc before merge, so
        the exchange is symmetric."""
        self.stage()
        self.import_bytes(blob)
        return self.materialize()

    # ------------------------------------------------------------------

    def _local_hash(self, figment_id: str) -> Optional[str]:
        try:
            entry = self.vault.load(figment_id)
        except (KeyError, SigningError):
            return None
        return content_hash(entry.figment)
