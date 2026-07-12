"""plugins/registry_trust.py — a TUF/Uptane trust model for the plugin registry.

Whole-package Ed25519 signing (plugins/validate.py) proves "this artifact was
signed by a key." It says nothing about the attacks that actually take down
plugin stores: a **stolen signing key**, a **rollback** to an old vulnerable
version, a **freeze** that pins clients to stale listings, or **mix-and-match**
of metadata from different points in time. TUF (The Update Framework, CNCF-
graduated) answers exactly those, and Uptane specializes it for the topology we
have: an internet-facing selection service that must not be able to mint
artifacts.

This module implements that model natively over the existing Ed25519 signer
(no python-tuf dependency), scoped to what a plugin registry needs:

  roles (root delegates trust, each with a k-of-n signature threshold)
    root       — the offline trust anchor: the pubkeys + thresholds of every
                 role; rotatable, threshold-signed by itself.
    targets    — the offline-signed catalog of blessed {name/version -> hash,
                 length, requires}. This is Uptane's *Image repo* core.
    snapshot   — binds the exact current targets version+hash → kills
                 mix-and-match.
    timestamp  — short-lived, points at the current snapshot with an `expires`
                 → kills freeze (a compromised registry can't silently pin
                 stale/vulnerable metadata; the client detects expiry).
    director   — Uptane's *online* selection service: signs which blessed
                 target a given client should install. It can only *reference*
                 targets the offline Image repo already signed — a fully-owned
                 Director can misdirect among approved plugins, never introduce
                 a new malicious one.

`TrustClient` pins a root and verifies the whole chain, enforcing anti-rollback
(monotonic versions) and anti-freeze (expiry). `now` is injected everywhere so
tests are deterministic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from ..reality_compiler.sign_crypto import verify_detached


class TrustError(ValueError):
    """A metadata chain failed a TUF/Uptane check (rollback/freeze/threshold/…)."""


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def meta_hash(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


@dataclass(frozen=True)
class Role:
    """The keys allowed to sign a role, and how many must (k-of-n)."""
    keyids: tuple                  # Ed25519 public-key hexes
    threshold: int


# ---------------------------------------------------------------------------
# Signing / verifying a metadata object: {signed: <obj>, signatures: [...]}
# ---------------------------------------------------------------------------

def sign_metadata(signed: dict, signers) -> dict:
    """Wrap ``signed`` with detached Ed25519 signatures from each signer. Each
    signature is keyed by the signer's public key (the keyid)."""
    sigs = []
    for s in signers:
        pub = getattr(s, "public_key_hex", "")
        if not pub:
            raise TrustError("a real Ed25519 signer is required (no HMAC keys)")
        sigs.append({"keyid": pub, "sig": s.sign(signed)})
    return {"signed": signed, "signatures": sigs}


def verify_metadata(meta: dict, role: Role) -> bool:
    """True iff at least ``role.threshold`` *distinct* authorized keys have a
    valid signature over ``meta['signed']``. Unknown or duplicate keys don't
    count — so one stolen key below threshold cannot forge."""
    signed = meta.get("signed")
    if signed is None:
        return False
    good = set()
    allowed = set(role.keyids)
    for s in meta.get("signatures", []):
        kid = s.get("keyid", "")
        if kid in allowed and kid not in good:
            if verify_detached(signed, s.get("sig", ""), kid) is True:
                good.add(kid)
    return len(good) >= role.threshold


def _role_from_root(root_signed: dict, name: str) -> Role:
    r = root_signed["roles"][name]
    return Role(tuple(r["keyids"]), int(r["threshold"]))


# ---------------------------------------------------------------------------
# The client: pin a root, verify the chain, gate installs
# ---------------------------------------------------------------------------

class TrustClient:
    """Pins a trusted root and verifies timestamp→snapshot→targets (+ an Uptane
    Director selection), enforcing thresholds, anti-rollback and anti-freeze."""

    def __init__(self, root_meta: dict):
        # the root is the trust anchor; require it be self-signed to threshold
        signed = root_meta.get("signed", {})
        root_role = Role(tuple(signed.get("roles", {}).get("root", {})
                               .get("keyids", [])),
                         int(signed.get("roles", {}).get("root", {})
                             .get("threshold", 1)))
        if not verify_metadata(root_meta, root_role):
            raise TrustError("root is not validly self-signed to threshold")
        self.root_meta = root_meta
        self.root = signed
        self._version = {"root": signed.get("version", 1)}
        self.targets: dict = {}        # verified blessed targets

    def update_root(self, new_root_meta: dict) -> None:
        """Rotate the root: the NEW root must be signed by the OLD root's
        threshold (chain of trust) and carry a higher version."""
        old_role = _role_from_root(self.root, "root")
        if not verify_metadata(new_root_meta, old_role):
            raise TrustError("new root not signed by the current root keys")
        new_signed = new_root_meta["signed"]
        if new_signed.get("version", 0) <= self._version["root"]:
            raise TrustError("root rollback: version did not increase")
        # and it must be self-consistent (signed by its own new root role too)
        self_role = Role(tuple(new_signed["roles"]["root"]["keyids"]),
                         int(new_signed["roles"]["root"]["threshold"]))
        if not verify_metadata(new_root_meta, self_role):
            raise TrustError("new root not self-signed to its own threshold")
        self.root_meta, self.root = new_root_meta, new_signed
        self._version["root"] = new_signed["version"]

    def update(self, timestamp_meta: dict, snapshot_meta: dict,
               targets_meta: dict, now: float) -> None:
        """Verify the full chain and adopt the targets, or raise TrustError."""
        # 1. timestamp: signed by the timestamp role, fresh, not rolled back
        if not verify_metadata(timestamp_meta, _role_from_root(self.root, "timestamp")):
            raise TrustError("timestamp signature/threshold invalid")
        ts = timestamp_meta["signed"]
        self._check_fresh("timestamp", ts, now)
        self._check_rollback("timestamp", ts)

        # 2. snapshot: signed, and its version+hash match what timestamp pins
        if not verify_metadata(snapshot_meta, _role_from_root(self.root, "snapshot")):
            raise TrustError("snapshot signature/threshold invalid")
        snap = snapshot_meta["signed"]
        pinned = ts["meta"]["snapshot"]
        if snap.get("version") != pinned["version"] or \
                meta_hash(snap) != pinned["hash"]:
            raise TrustError("snapshot does not match the timestamp (freeze/"
                             "mix-and-match)")
        self._check_fresh("snapshot", snap, now)
        self._check_rollback("snapshot", snap)

        # 3. targets: signed, and its version+hash match what snapshot pins
        if not verify_metadata(targets_meta, _role_from_root(self.root, "targets")):
            raise TrustError("targets signature/threshold invalid")
        tgt = targets_meta["signed"]
        pinned_t = snap["meta"]["targets"]
        if tgt.get("version") != pinned_t["version"] or \
                meta_hash(tgt) != pinned_t["hash"]:
            raise TrustError("targets does not match the snapshot (mix-and-match)")
        self._check_fresh("targets", tgt, now)
        self._check_rollback("targets", tgt)

        self.targets = dict(tgt.get("targets", {}))

    def _check_fresh(self, role: str, signed: dict, now: float) -> None:
        exp = signed.get("expires")
        if exp is None or now >= float(exp):
            raise TrustError(f"{role} metadata is expired (freeze attack)")

    def _check_rollback(self, role: str, signed: dict) -> None:
        v = int(signed.get("version", 0))
        if v < self._version.get(role, 0):
            raise TrustError(f"{role} rollback: {v} < seen "
                             f"{self._version[role]}")
        self._version[role] = v

    # -- what a client is allowed to install --------------------------------

    def target(self, name: str, version: str) -> Optional[dict]:
        """The blessed target record (hash/length/requires), or None."""
        return self.targets.get(f"{name}/{version}")

    def verify_install(self, name: str, version: str, artifact: bytes) -> dict:
        """Gate an actual download: the artifact must match the offline-signed
        target hash+length. Raises TrustError otherwise."""
        rec = self.target(name, version)
        if rec is None:
            raise TrustError(f"{name}/{version} is not a blessed target")
        if len(artifact) != rec.get("length"):
            raise TrustError("artifact length != signed length")
        if hashlib.sha256(artifact).hexdigest() != rec.get("hash"):
            raise TrustError("artifact hash != signed hash")
        return rec

    def director_selection(self, director_meta: dict, now: float) -> list:
        """Verify an Uptane Director selection (online-signed) and return the
        blessed (name, version) pairs. A selection that names a target the
        offline Image repo never signed is REFUSED — the whole point: a
        compromised Director cannot introduce a new artifact."""
        if not verify_metadata(director_meta, _role_from_root(self.root, "director")):
            raise TrustError("director signature/threshold invalid")
        d = director_meta["signed"]
        self._check_fresh("director", d, now)
        out = []
        for item in d.get("selection", []):
            name, version = item.get("name"), item.get("version")
            if self.target(name, version) is None:
                raise TrustError(
                    f"director selected {name}/{version}, not blessed by the "
                    "offline Image repo — refused")
            out.append((name, version))
        return out
