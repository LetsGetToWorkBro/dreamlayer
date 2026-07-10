"""v2/vault.py — local, signed storage for kept Figments (the Repertoire).

Privacy contract (docs/PRIVACY_MODEL.md applies):
  - figments live only in the vault directory on the phone
  - every entry is signed by the install's session key at keep-time
  - nothing leaves the vault except through an explicit export()
  - revocation is durable: a revoked id stays on the revocation list and
    the deployer refuses it even if a file with that id reappears

Layout:  <dir>/figments/<id>.json   {"figment": …, "sig": …, "kept_at": …}
         <dir>/revoked.json         ["id", …]
         <dir>/history/<id>.jsonl   one line per performance (pattern memory)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .figment import Figment
from .signer import SessionSigner, SigningError


@dataclass
class VaultEntry:
    figment: Figment
    sig: str
    kept_at: float
    revoked: bool

    @property
    def active(self) -> bool:
        return not self.revoked


class Vault:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        (self.root / "figments").mkdir(parents=True, exist_ok=True)
        (self.root / "history").mkdir(parents=True, exist_ok=True)
        self.signer = SessionSigner(self.root)

    # ------------------------------------------------------------------
    # Keep / load / list
    # ------------------------------------------------------------------

    def keep(self, fig: Figment) -> VaultEntry:
        """Sign and store. The Figment must already be budget-verified."""
        sig = self.signer.sign(fig)
        entry = {"figment": fig.to_dict(), "sig": sig, "kept_at": time.time()}
        self._path(fig.id).write_text(json.dumps(entry, indent=2))
        return VaultEntry(fig, sig, entry["kept_at"], revoked=False)

    def load(self, figment_id: str) -> VaultEntry:
        path = self._path(figment_id)
        if not path.exists():
            raise KeyError(f"no figment {figment_id!r} in vault")
        raw = json.loads(path.read_text())
        fig = Figment.from_dict(raw["figment"])
        sig = raw.get("sig", "")
        self.signer.verify_or_raise(fig, sig)
        return VaultEntry(fig, sig, raw.get("kept_at", 0.0),
                          revoked=figment_id in self._revoked())

    def list(self, include_revoked: bool = False) -> list[VaultEntry]:
        entries = []
        for path in sorted((self.root / "figments").glob("*.json")):
            try:
                entry = self.load(path.stem)
            except (SigningError, KeyError, json.JSONDecodeError):
                continue  # tampered or corrupt entries never surface
            if entry.active or include_revoked:
                entries.append(entry)
        return entries

    def inherited(self) -> list[VaultEntry]:
        """The *Inherited* section: kept figments carrying a dedication
        (`meta.dedication`) — an author's rhythm, signed and provably theirs,
        that outlives every device (INNOVATION_SESSION 5.5). Newest first."""
        heirlooms = [e for e in self.list() if e.figment.dedication()]
        return sorted(heirlooms, key=lambda e: e.kept_at, reverse=True)

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, figment_id: str) -> None:
        revoked = self._revoked()
        revoked.add(figment_id)
        (self.root / "revoked.json").write_text(json.dumps(sorted(revoked)))

    def is_revoked(self, figment_id: str) -> bool:
        return figment_id in self._revoked()

    def _revoked(self) -> set[str]:
        path = self.root / "revoked.json"
        if not path.exists():
            return set()
        return set(json.loads(path.read_text()))

    # ------------------------------------------------------------------
    # Explicit export — the only way a figment leaves the phone
    # ------------------------------------------------------------------

    def export(self, figment_id: str, dest: Path | str) -> Path:
        entry = self.load(figment_id)
        if entry.revoked:
            raise SigningError(f"figment {figment_id} is revoked — not exportable")
        dest = Path(dest)
        payload = {
            "figment": entry.figment.to_dict(),
            "sig": entry.sig,
            "exported_at": time.time(),
        }
        dest.write_text(json.dumps(payload, indent=2))
        return dest

    # ------------------------------------------------------------------
    # Performance history (pattern memory — feeds the Echo follow-up)
    # ------------------------------------------------------------------

    def record_performance(self, figment_id: str,
                           context: Optional[dict] = None) -> None:
        line = json.dumps({"t": time.time(), **(context or {})})
        with (self.root / "history" / f"{figment_id}.jsonl").open("a") as fh:
            fh.write(line + "\n")

    def performance_history(self, figment_id: str) -> list[dict]:
        path = self.root / "history" / f"{figment_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln]

    def _path(self, figment_id: str) -> Path:
        safe = "".join(c for c in figment_id if c.isalnum() or c in "-_")
        return self.root / "figments" / f"{safe}.json"
