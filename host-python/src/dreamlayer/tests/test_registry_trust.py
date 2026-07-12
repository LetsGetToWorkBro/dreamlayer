"""TUF/Uptane trust model: the attacks whole-package signing can't stop —
key compromise, rollback, freeze, mix-and-match — plus the Uptane guarantee
that a compromised online Director can't introduce an unblessed artifact.
Real Ed25519 (cryptography present)."""
import hashlib

import pytest

pytest.importorskip("cryptography")

from dreamlayer.reality_compiler.sign_crypto import Signer
from dreamlayer.plugins.registry_trust import (
    Role, TrustClient, TrustError, sign_metadata, verify_metadata, meta_hash,
)

NOW = 1_000_000.0
LATER = NOW + 3600.0


def _signer(seed: str) -> Signer:
    return Signer(hashlib.sha256(seed.encode()).digest())


class Repo:
    """A tiny signed metadata repository, for exercising the client."""
    def __init__(self, targets_threshold=1):
        self.root_k = [_signer("root1"), _signer("root2")]
        self.tgt_k = [_signer("tgt1"), _signer("tgt2")]
        self.snap_k = [_signer("snap")]
        self.ts_k = [_signer("ts")]
        self.dir_k = [_signer("director")]
        self.tgt_threshold = targets_threshold
        self._tv = self._sv = self._tsv = 1
        self.targets_entries = {}

    def _pub(self, ks): return [k.public_key_hex for k in ks]

    def root(self, version=1):
        signed = {"version": version, "roles": {
            "root": {"keyids": self._pub(self.root_k), "threshold": 2},
            "targets": {"keyids": self._pub(self.tgt_k),
                        "threshold": self.tgt_threshold},
            "snapshot": {"keyids": self._pub(self.snap_k), "threshold": 1},
            "timestamp": {"keyids": self._pub(self.ts_k), "threshold": 1},
            "director": {"keyids": self._pub(self.dir_k), "threshold": 1},
        }}
        return sign_metadata(signed, self.root_k)

    def add_target(self, name, version, artifact: bytes, requires=None):
        self.targets_entries[f"{name}/{version}"] = {
            "hash": hashlib.sha256(artifact).hexdigest(),
            "length": len(artifact), "requires": requires or []}

    def targets(self, version=None, signers=None):
        v = version or self._tv
        signed = {"version": v, "expires": LATER,
                  "targets": dict(self.targets_entries)}
        return sign_metadata(signed, signers or self.tgt_k)

    def snapshot(self, targets_meta, version=None, expires=LATER):
        v = version or self._sv
        signed = {"version": v, "expires": expires, "meta": {"targets": {
            "version": targets_meta["signed"]["version"],
            "hash": meta_hash(targets_meta["signed"])}}}
        return sign_metadata(signed, self.snap_k)

    def timestamp(self, snapshot_meta, version=None, expires=LATER):
        v = version or self._tsv
        signed = {"version": v, "expires": expires, "meta": {"snapshot": {
            "version": snapshot_meta["signed"]["version"],
            "hash": meta_hash(snapshot_meta["signed"])}}}
        return sign_metadata(signed, self.ts_k)

    def chain(self, **kw):
        t = self.targets(**kw.get("targets", {}))
        s = self.snapshot(t, **kw.get("snapshot", {}))
        ts = self.timestamp(s, **kw.get("timestamp", {}))
        return ts, s, t

    def director(self, selection, expires=LATER, signers=None):
        return sign_metadata({"version": 1, "expires": expires,
                              "selection": selection}, signers or self.dir_k)


ART = b"print('hello from a plugin')"


def _repo():
    r = Repo()
    r.add_target("hello", "1.0", ART, requires=["cards"])
    return r


class TestHappyPath:
    def test_full_chain_verifies_and_target_installs(self):
        r = _repo()
        c = TrustClient(r.root())
        c.update(*r.chain(), now=NOW)
        assert c.target("hello", "1.0")["requires"] == ["cards"]
        assert c.verify_install("hello", "1.0", ART)["length"] == len(ART)

    def test_install_refuses_tampered_artifact(self):
        r = _repo()
        c = TrustClient(r.root()); c.update(*r.chain(), now=NOW)
        with pytest.raises(TrustError):
            c.verify_install("hello", "1.0", ART + b"; evil()")


class TestThresholds:
    def test_root_needs_its_threshold(self):
        r = _repo()
        bad = sign_metadata(r.root()["signed"], [r.root_k[0]])  # 1 of 2
        with pytest.raises(TrustError):
            TrustClient(bad)

    def test_one_stolen_targets_key_below_threshold_cannot_forge(self):
        r = Repo(targets_threshold=2)
        r.add_target("hello", "1.0", ART)
        c = TrustClient(r.root())
        ts, s, _ = r.chain()
        forged = r.targets(signers=[r.tgt_k[0]])          # only 1 of 2 keys
        s2 = r.snapshot(forged); ts2 = r.timestamp(s2)
        with pytest.raises(TrustError):
            c.update(ts2, s2, forged, now=NOW)


class TestAttacks:
    def test_freeze_expired_timestamp_refused(self):
        r = _repo(); c = TrustClient(r.root())
        ts, s, t = r.chain(timestamp={"expires": NOW - 1})
        with pytest.raises(TrustError):
            c.update(ts, s, t, now=NOW)

    def test_rollback_refused(self):
        r = _repo(); c = TrustClient(r.root())
        c.update(*r.chain(timestamp={"version": 5}), now=NOW)
        # replay an older timestamp version → rejected
        with pytest.raises(TrustError):
            c.update(*r.chain(timestamp={"version": 4}), now=NOW)

    def test_mix_and_match_refused(self):
        r = _repo(); c = TrustClient(r.root())
        ts, s, _ = r.chain()
        # present a *different* targets than the snapshot pinned
        r.add_target("evil", "9.9", b"rm -rf")
        other = r.targets(version=1)
        with pytest.raises(TrustError):
            c.update(ts, s, other, now=NOW)


class TestRootRotation:
    def test_rotate_root_with_old_keys_and_higher_version(self):
        r = _repo(); c = TrustClient(r.root())
        new = r.root(version=2)                     # signed by the same root keys
        c.update_root(new)
        assert c.root["version"] == 2
        c.update(*r.chain(), now=NOW)               # still works after rotation

    def test_rotate_root_rejected_without_old_signature(self):
        r = _repo(); c = TrustClient(r.root())
        stranger = _signer("stranger")              # not one of the root keys
        v2 = r.root(version=2)["signed"]
        forged = sign_metadata(v2, [stranger])      # signed by a non-root key
        with pytest.raises(TrustError):
            c.update_root(forged)


class TestDirector:
    def test_director_selecting_blessed_target_ok(self):
        r = _repo(); c = TrustClient(r.root()); c.update(*r.chain(), now=NOW)
        sel = c.director_selection(
            r.director([{"name": "hello", "version": "1.0"}]), now=NOW)
        assert sel == [("hello", "1.0")]

    def test_compromised_director_cannot_introduce_unblessed_artifact(self):
        # the Uptane guarantee: a fully-owned online Director signs a selection
        # for a plugin the offline Image repo never blessed → REFUSED
        r = _repo(); c = TrustClient(r.root()); c.update(*r.chain(), now=NOW)
        stolen = _signer("director")                # the real director key, stolen
        forged = sign_metadata({"version": 1, "expires": LATER, "selection": [
            {"name": "malware", "version": "1.0"}]}, [stolen])
        with pytest.raises(TrustError):
            c.director_selection(forged, now=NOW)

    def test_expired_director_selection_refused(self):
        r = _repo(); c = TrustClient(r.root()); c.update(*r.chain(), now=NOW)
        with pytest.raises(TrustError):
            c.director_selection(
                r.director([{"name": "hello", "version": "1.0"}],
                           expires=NOW - 1), now=NOW)


class TestMetadataPrimitive:
    def test_unknown_key_does_not_count_toward_threshold(self):
        role = Role((_signer("a").public_key_hex,), 1)
        meta = sign_metadata({"x": 1}, [_signer("b")])   # signed by a non-member
        assert verify_metadata(meta, role) is False
