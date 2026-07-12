"""Serverless multi-device Vault sync over a Loro CRDT (v2/vault_sync.py).

Proves the properties that make peer-to-peer sync trustworthy: merge converges
regardless of exchange order or duplication, durable revocation wins over a
stale re-keep, and a figment mutated in transit is refused rather than kept.

Needs loro; skipped headlessly when absent (pip install dreamlayer[sync])."""
import json

import pytest

loro = pytest.importorskip("loro")

from dreamlayer.reality_compiler.v2 import native            # noqa: E402
from dreamlayer.reality_compiler.v2.figment import Figment   # noqa: E402
from dreamlayer.reality_compiler.v2.signer import content_hash  # noqa: E402
from dreamlayer.reality_compiler.v2.vault import Vault        # noqa: E402
from dreamlayer.reality_compiler.v2.vault_sync import (       # noqa: E402
    VaultSync, SyncReport,
)


def _vault(tmp_path, name):
    return Vault(tmp_path / name)


def _active_ids(vault):
    return sorted(e.figment.id for e in vault.list())


class TestConvergence:
    def test_disjoint_keeps_merge_both_ways(self, tmp_path):
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(30)
        y = native.interval_figment(30, 15, rounds=3)
        va.keep(x)
        vb.keep(y)

        a = VaultSync(va, peer="phone")
        b = VaultSync(vb, peer="tablet")
        a.stage()
        b.stage()
        rb = b.merge(a.export_bytes())
        ra = a.merge(b.export_bytes())

        assert _active_ids(va) == _active_ids(vb) == sorted([x.id, y.id])
        assert x.id in rb.added and y.id in ra.added
        assert rb.ok and ra.ok

    def test_merge_is_idempotent(self, tmp_path):
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(45)
        va.keep(x)
        a = VaultSync(va, peer="phone")
        a.stage()
        blob = a.export_bytes()

        b = VaultSync(vb, peer="tablet")
        first = b.merge(blob)
        second = b.merge(blob)          # replay the exact same blob
        third = b.merge(blob)

        assert first.added == [x.id]
        assert second.added == [] and third.added == []
        assert second.unchanged >= 1
        assert _active_ids(vb) == [x.id]

    def test_out_of_order_and_duplicate_delivery_converges(self, tmp_path):
        # three devices, blobs delivered in a scrambled, duplicated order
        vs = [_vault(tmp_path, n) for n in ("a", "b", "c")]
        figs = [native.timer_figment(10), native.timer_figment(20),
                native.clock_figment()]
        for v, f in zip(vs, figs):
            v.keep(f)
        syncs = [VaultSync(v, peer=p) for v, p in zip(vs, "abc")]
        for s in syncs:
            s.stage()
        blobs = [s.export_bytes() for s in syncs]

        # everyone imports everyone's blob twice, in a rotated order
        for i, s in enumerate(syncs):
            order = blobs[i:] + blobs[:i] + blobs      # scrambled + duplicated
            for blob in order:
                s.merge(blob)

        want = sorted(f.id for f in figs)
        assert all(_active_ids(v) == want for v in vs)


class TestRevocationWins:
    def test_revoke_beats_concurrent_keep(self, tmp_path):
        # A and B both hold X. A revokes it while apart. After sync, X is
        # revoked everywhere and never resurfaces as active.
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(30)
        va.keep(x)
        vb.keep(x)                       # B independently kept the same figment
        va.revoke(x.id)

        a = VaultSync(va, peer="phone")
        b = VaultSync(vb, peer="tablet")
        a.stage()
        b.stage()
        rb = b.merge(a.export_bytes())
        ra = a.merge(b.export_bytes())

        assert x.id in rb.revoked
        assert _active_ids(va) == [] and _active_ids(vb) == []
        assert va.is_revoked(x.id) and vb.is_revoked(x.id)
        # re-staging + re-merging can't undo it (monotone)
        assert x.id not in a.merge(b.export_bytes()).added

    def test_revocation_propagates_to_a_device_that_never_had_it(self, tmp_path):
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(30)
        va.keep(x)
        va.revoke(x.id)                  # A kept then banished before B ever saw
        a = VaultSync(va, peer="phone")
        a.stage()
        b = VaultSync(vb, peer="tablet")
        rb = b.merge(a.export_bytes())

        assert x.id in rb.revoked
        assert vb.is_revoked(x.id)
        assert _active_ids(vb) == []     # never materialized as active


class TestIntegrity:
    def test_tampered_figment_is_refused_not_kept(self, tmp_path):
        vb = _vault(tmp_path, "b")
        fig = native.timer_figment(30)
        # forge a CRDT blob whose stored content_hash lies about the figment
        doc = loro.LoroDoc()
        rec = {"content_hash": "0" * 16, "figment": fig.to_dict(),
               "kept_at": 1.0, "origin": "evil"}
        doc.get_map("figments").insert(fig.id, json.dumps(rec, sort_keys=True))
        doc.commit()
        blob = doc.export(loro.ExportMode.Snapshot())

        b = VaultSync(vb, peer="tablet")
        report = b.merge(blob)
        assert fig.id in report.tampered
        assert not report.ok
        assert _active_ids(vb) == []     # refused, never entered the vault

    def test_mutated_content_under_a_valid_hash_is_refused(self, tmp_path):
        vb = _vault(tmp_path, "b")
        fig = native.timer_figment(30)
        good_hash = content_hash(fig)
        # keep the honest hash but swap the body for a different figment
        evil_body = native.interval_figment(60, 30, rounds=9).to_dict()
        doc = loro.LoroDoc()
        rec = {"content_hash": good_hash, "figment": evil_body,
               "kept_at": 1.0, "origin": "evil"}
        doc.get_map("figments").insert(fig.id, json.dumps(rec, sort_keys=True))
        doc.commit()
        blob = doc.export(loro.ExportMode.Snapshot())

        report = VaultSync(vb, peer="t").merge(blob)
        assert fig.id in report.tampered and _active_ids(vb) == []


class TestFidelity:
    def test_kept_at_survives_the_crossing(self, tmp_path):
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(30)
        entry = va.keep(x, kept_at=1234.5)
        a = VaultSync(va, peer="phone")
        a.stage()
        VaultSync(vb, peer="tablet").merge(a.export_bytes())
        assert vb.load(x.id).kept_at == pytest.approx(1234.5)

    def test_signature_is_reminted_with_the_local_key(self, tmp_path):
        # the synced figment must verify under B's key, not A's — provenance is
        # per-install, integrity is carried by content_hash
        va, vb = _vault(tmp_path, "a"), _vault(tmp_path, "b")
        x = native.timer_figment(30)
        va.keep(x)
        a = VaultSync(va, peer="phone")
        a.stage()
        VaultSync(vb, peer="tablet").merge(a.export_bytes())
        loaded = vb.load(x.id)           # load() verifies against B's key
        assert loaded.figment.id == x.id
        assert vb.signer.verify(loaded.figment, loaded.sig)


class TestAvailability:
    def test_reports_str(self):
        r = SyncReport(added=["a"], revoked=["b"], unchanged=2)
        assert "added=['a']" in str(r) and r.ok
        assert not SyncReport(tampered=["x"]).ok
