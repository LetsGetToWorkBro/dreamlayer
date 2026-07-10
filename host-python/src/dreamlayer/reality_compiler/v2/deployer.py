"""v2/deployer.py — signed figments onto the stage: put, swap, revoke.

Unlike v1 (which uploaded a whole generated main.lua and restarted the
app), v2 never ships code: the fixed stage is already on Halo, and
deployment is sending data. Hot-swap replaces the running behavior
between ticks; revoke clears it; no reboot either way.

Gate order, enforced here regardless of caller:
  1. the figment verifies against its stored signature (session key)
  2. the figment id is not on the vault's revocation list
  3. the budget proof passes (re-checked — defense in depth)

Dry-run mode (default, no hardware) records the exact envelopes that
would be sent, which the demo and tests inspect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import transport
from .budgets import verify
from .figment import Figment
from .signer import SigningError
from .vault import Vault


@dataclass
class DeployRecord:
    success: bool
    mode: str                    # "dry_run" | "hardware"
    action: str                  # "put+swap" | "swap" | "revoke"
    message: str = ""
    envelopes: list[dict] = field(default_factory=list)


class StageDeployer:
    """Deploys vault figments to the Halo stage over a bridge.

    bridge: object with `async send(raw: bytes)` (e.g. the scripts/
    halo_bridge.py BLE transport). None → dry-run.
    """

    def __init__(self, vault: Vault, bridge=None,
                 require_author_sig: bool = False) -> None:
        self.vault = vault
        self.bridge = bridge
        self.sent: list[dict] = []       # every envelope ever handed over
        self._on_device: set[str] = set()
        # Sharing gate: self-authored figments ride the per-install HMAC
        # session key. A figment that arrived from OUTSIDE this install
        # (meta.origin == "shared") must additionally carry a verifiable
        # Ed25519 author signature — flip this on for any install that
        # accepts shared figments. HMAC can't prove authorship to a third
        # party; asymmetric signatures can.
        self.require_author_sig = require_author_sig

    # ------------------------------------------------------------------

    @staticmethod
    def _author_sig_ok(fig) -> bool:
        """Verify meta.author_sig/author_pubkey over the figment body
        (with the signature fields excluded). Unverifiable (no cryptography
        installed) counts as NOT ok — never trust what can't be checked."""
        from ..sign_crypto import verify_detached
        meta = getattr(fig, "meta", None) or {}
        sig, pub = meta.get("author_sig", ""), meta.get("author_pubkey", "")
        if not (sig and pub):
            return False
        body = fig.to_dict()
        body_meta = dict(body.get("meta") or {})
        body_meta.pop("author_sig", None)
        body_meta.pop("author_pubkey", None)
        body["meta"] = body_meta
        return verify_detached(body, sig, pub) is True

    def deploy(self, figment_id: str) -> DeployRecord:
        """put (if needed) + hot-swap. Refuses unsigned/revoked/unproven."""
        try:
            entry = self.vault.load(figment_id)
        except (KeyError, SigningError) as exc:
            return self._refuse("put+swap", str(exc))
        if entry.revoked:
            return self._refuse("put+swap",
                                f"figment {figment_id} is revoked")
        meta = getattr(entry.figment, "meta", None) or {}
        if self.require_author_sig and meta.get("origin") == "shared" \
                and not self._author_sig_ok(entry.figment):
            return self._refuse(
                "put+swap",
                f"shared figment {figment_id} has no verifiable Ed25519 "
                "author signature")
        report = verify(entry.figment)
        if not report.ok:
            return self._refuse("put+swap",
                                f"budget proof failed: {report.violations[0]}")

        envelopes = []
        if figment_id not in self._on_device:
            envelopes.append(transport.put_envelope(entry.figment))
        envelopes.append(transport.swap_envelope(figment_id))
        self._send(envelopes)
        self._on_device.add(figment_id)
        return DeployRecord(True, self._mode(), "put+swap",
                            f"{entry.figment.name!r} live on stage "
                            "(hot-swap, no reboot)", envelopes)

    def revoke(self, figment_id: str) -> DeployRecord:
        """Durable revocation: vault list + device clear."""
        self.vault.revoke(figment_id)
        envelopes = [transport.revoke_envelope(figment_id)]
        self._send(envelopes)
        self._on_device.discard(figment_id)
        return DeployRecord(True, self._mode(), "revoke",
                            f"figment {figment_id} revoked", envelopes)

    def push_text(self, figment_id: str, text: str) -> DeployRecord:
        envelopes = [transport.text_envelope(figment_id, text)]
        self._send(envelopes)
        return DeployRecord(True, self._mode(), "text", "", envelopes)

    def push_event(self, name: str) -> DeployRecord:
        """Deliver a physical-world signal (e.g. "ble:3") to the running
        figment. Unlike put/swap/revoke it carries no figment id — it's a
        transient scene signal, acted on only if the active figment's grammar
        lists that name; the device ignores it otherwise. No signing gate: an
        event grants no authority, it can only *advance* a machine you already
        installed and proved, within that machine's own rate limits."""
        envelopes = [transport.event_envelope(name)]
        self._send(envelopes)
        return DeployRecord(True, self._mode(), "event", "", envelopes)

    # ------------------------------------------------------------------

    def _refuse(self, action: str, why: str) -> DeployRecord:
        return DeployRecord(False, self._mode(), action,
                            f"REFUSED: {why}")

    def _mode(self) -> str:
        return "hardware" if self.bridge is not None else "dry_run"

    def _send(self, envelopes: list[dict]) -> None:
        for env in envelopes:
            self.sent.append(env)
            if self.bridge is not None:
                self.bridge.send(transport.frame(env))
