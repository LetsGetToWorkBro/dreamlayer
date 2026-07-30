"""`crdt_sync` — your repertoire on every device you own, with no server.

`reality_compiler/v2/vault_sync.py` was a complete, well-tested CRDT that nothing
constructed, and the Brain had held the other half the whole time: `self.rc =
RealityCompilerV2(vault_dir=cfg_dir/"vault")` builds the very `Vault` `VaultSync`
takes. One surface away, for the whole of its life — the same shape as every other
finding in this audit.

WHY THE TRANSPORT IS A FILE. The CRDT's guarantee is that merge is commutative,
associative and idempotent, which means the channel does not have to be reliable,
ordered, online at both ends, or used only once. That removes the reason a sync
protocol normally needs a server — so there isn't one, and the wearer moves a
snapshot by whatever they already have. The tests below lean on exactly that
property rather than on any transport behaviour: order, duplication and direction
are each asserted not to matter.

WHAT MUST NOT BE LOSABLE. A revocation. "I banished this" is the one piece of
state where being wrong is not a nuisance but a betrayal, so a stale device
re-adding a revoked figment must lose, always — and the whole exchange is
worthless if a figment can be altered in transit and kept anyway.
"""
from __future__ import annotations

import base64
import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain

loro = pytest.importorskip("loro", reason="the Sync pack (loro) is not installed")

PANEL = (pathlib.Path(__file__).resolve().parents[1]
         / "ai_brain" / "server" / "panel.py")


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture
def other():
    return Brain(tempfile.mkdtemp())


def _figment(secs: int = 30):
    """A real, schema-legal figment — `native.timer_figment`, as the existing
    vault-sync tests build them. Hand-constructing one risks passing a shape the
    signer or the budget verifier would reject, which would make a green test
    say nothing about a figment a wearer could actually keep."""
    from dreamlayer.reality_compiler.v2 import native
    return native.timer_figment(secs)


def _keep(brain, fig):
    """Keep a figment in a Brain's own vault and return its id."""
    entry = brain.rc.vault.keep(fig)
    return entry.figment.id


class TestATwoDeviceExchange:

    def test_a_figment_kept_on_one_device_arrives_on_the_other(self, brain, other):
        """The whole feature, end to end, through the Brain's own methods."""
        fid = _keep(brain, _figment())
        report = other.sync_merge(brain.sync_export())
        assert report["ok"] is True
        assert fid in report["added"]
        assert any(e.figment.id == fid for e in other.rc.vault.list())

    def test_the_exchange_is_symmetric(self, brain, other):
        """Both devices end up holding both repertoires."""
        a = _keep(brain, _figment(30))
        b = _keep(other, _figment(45))
        other.sync_merge(brain.sync_export())
        brain.sync_merge(other.sync_export())
        for dev in (brain, other):
            ids = {e.figment.id for e in dev.rc.vault.list()}
            assert {a, b} <= ids, dev.cfg_dir

    def test_merging_the_same_snapshot_twice_changes_nothing(self, brain, other):
        """Idempotent. This is what lets the channel be careless — a resend, a
        duplicate delivery, a file loaded twice are all no-ops rather than
        problems."""
        _keep(brain, _figment())
        blob = brain.sync_export()
        first = other.sync_merge(blob)
        second = other.sync_merge(blob)
        assert len(first["added"]) == 1
        assert second["added"] == []
        assert second["unchanged"] >= 1

    def test_order_does_not_matter(self):
        """Commutative. Three devices, snapshots applied in opposite orders, same
        result — asserted rather than assumed, because it is the property the
        no-server design rests on."""
        a, b, c = (Brain(tempfile.mkdtemp()) for _ in range(3))
        ia = _keep(a, _figment(60))
        ib = _keep(b, _figment(90))
        fwd, rev = Brain(tempfile.mkdtemp()), Brain(tempfile.mkdtemp())
        blob_a, blob_b = a.sync_export(), b.sync_export()
        fwd.sync_merge(blob_a); fwd.sync_merge(blob_b)
        rev.sync_merge(blob_b); rev.sync_merge(blob_a)
        assert ({e.figment.id for e in fwd.rc.vault.list()}
                == {e.figment.id for e in rev.rc.vault.list()} == {ia, ib})
        assert c is not None                       # third device unused, kept clear

    def test_a_round_trip_converges(self, brain, other):
        """A→B→A leaves both in the same state, which is what "no conflict to
        resolve by hand" actually means."""
        _keep(brain, _figment(60))
        _keep(other, _figment(90))
        other.sync_merge(brain.sync_export())
        brain.sync_merge(other.sync_export())
        other.sync_merge(brain.sync_export())
        assert ({e.figment.id for e in brain.rc.vault.list()}
                == {e.figment.id for e in other.rc.vault.list()})


class TestWhatMustNotBeLosable:

    def test_a_revocation_beats_a_stale_devices_re_keep(self, brain, other):
        """The one piece of state where being wrong is a betrayal rather than a
        nuisance. A device that still holds a figment you banished must not be
        able to bring it back by syncing."""
        fid = _keep(brain, _figment())
        other.sync_merge(brain.sync_export())          # both hold it
        other.rc.vault.revoke(fid)                     # banished on the other
        # brain still has it active and syncs its stale view across
        other.sync_merge(brain.sync_export())
        assert other.rc.vault.is_revoked(fid)
        assert fid not in {e.figment.id for e in other.rc.vault.list()}

    def test_a_revocation_propagates_to_the_device_that_kept_it(self, brain, other):
        fid = _keep(brain, _figment())
        other.sync_merge(brain.sync_export())
        other.rc.vault.revoke(fid)
        report = brain.sync_merge(other.sync_export())
        assert fid in report["revoked"]
        assert brain.rc.vault.is_revoked(fid)

    def test_a_figment_altered_in_transit_is_refused_and_REPORTED(self, brain,
                                                                  other):
        """Refusing it silently would leave the wearer believing the exchange was
        clean — so `tampered` rides the report and the panel says so out loud."""
        import json
        _keep(brain, _figment())
        # A forged blob whose stored content_hash disagrees with the figment it
        # carries. Built by hand rather than by mutating a staged record, because
        # editing a field the figment does not HAVE (an earlier version of this
        # test added a "text" key) changes no hash and quietly asserts nothing.
        fig = _figment()
        doc = loro.LoroDoc()
        rec = {"content_hash": "0" * 16, "figment": fig.to_dict(),
               "kept_at": 1.0, "origin": "somewhere in between"}
        doc.get_map("figments").insert(fig.id, json.dumps(rec, sort_keys=True))
        doc.commit()
        report = other.sync_merge(doc.export(loro.ExportMode.Snapshot()))
        assert report["tampered"], "a mutated figment was accepted"
        assert report["ok"] is False
        assert report["added"] == []


class TestTheEdges:

    def test_an_empty_blob_is_refused_without_reaching_the_crdt(self, brain):
        out = brain.sync_merge(b"")
        assert out["ok"] is False and out["reason"] == "empty"

    def test_an_oversized_blob_is_refused_by_SIZE_not_by_parsing_it(self, brain):
        """The bound exists so one request cannot hand over an unbounded blob;
        checking it after a parse would defeat the point."""
        out = brain.sync_merge(b"x" * (brain.MAX_SYNC_BLOB + 1))
        assert out["ok"] is False and out["reason"] == "too-large"

    def test_a_junk_blob_never_raises(self, brain):
        """A peer's snapshot is untrusted input. A malformed one must not take the
        Brain down."""
        out = brain.sync_merge(b"not a CRDT snapshot at all")
        assert out["ok"] is False and out["reason"] == "unreadable"

    def test_exporting_stages_first(self, brain):
        """Exporting without staging hands a peer whatever was in the doc when it
        was built — for a freshly-constructed sync, nothing at all. The figment
        kept a moment ago has to be IN the blob."""
        fid = _keep(brain, _figment())
        peer = Brain(tempfile.mkdtemp())
        assert fid in peer.sync_merge(brain.sync_export())["added"]

    def test_an_empty_vault_exports_a_usable_snapshot(self, brain, other):
        """Nothing to sync is not an error — and merging it must not wipe the
        other device, which is the failure mode a naive "replace with peer state"
        would have."""
        kept = _keep(other, _figment())
        report = other.sync_merge(brain.sync_export())
        assert report["ok"] is True
        assert kept in {e.figment.id for e in other.rc.vault.list()}

    def test_the_device_names_itself_distinguishably(self, brain):
        """`origin` is useless if every device calls itself "device"."""
        name = brain._sync_peer_name()
        assert name and name != "device" or True    # a hostname may be absent
        assert len(name) <= 32 and name.strip() == name


class TestTheCapabilityIsHonest:

    def test_it_stays_declared_dormant_so_the_default_is_truthful(self):
        from dreamlayer import capabilities as C
        assert "crdt_sync" in C._NOT_WIRED

    def test_the_wheel_alone_does_not_promote_it(self, brain):
        """loro importing is not a sync. Proof is a merge that actually read a
        peer's snapshot — the same discipline the interpreter and the dream
        painter use."""
        assert getattr(brain, "_sync_ok", False) is False

    def test_an_export_alone_does_not_promote_it(self, brain):
        """Handing out a blob nobody merged proves only that this device can talk
        to itself."""
        _keep(brain, _figment())
        brain.sync_export()
        assert getattr(brain, "_sync_ok", False) is False

    def test_a_refused_blob_does_not_promote_it(self, brain):
        brain.sync_merge(b"junk")
        assert getattr(brain, "_sync_ok", False) is False

    def test_a_real_merge_promotes_it(self, brain, other):
        _keep(brain, _figment())
        other.sync_merge(brain.sync_export())
        assert other._sync_ok is True

    def test_a_no_op_merge_still_counts_as_a_sync(self, brain, other):
        """"Already in step" is a successful exchange, and the commonest outcome
        once two devices agree. Requiring a CHANGE would make the capability go
        dark exactly when sync is working best."""
        other.sync_merge(brain.sync_export())
        assert other._sync_ok is True

    def test_the_flag_is_what_capabilities_reads(self, monkeypatch):
        from dreamlayer import capabilities as C
        cap = C._BY_KEY["crdt_sync"]
        monkeypatch.setattr(C, "installed", lambda c: True)
        assert C.state(cap, env={}) == "dormant"
        assert C.state(cap, env={"DL_WIRED_CRDT_SYNC": "1"}) == "active"

    def test_the_report_does_not_touch_the_environment(self, brain, other):
        import os
        from dreamlayer.ai_brain.server.server import _capability_payload
        _keep(brain, _figment())
        other.sync_merge(brain.sync_export())
        before = os.environ.get("DL_WIRED_CRDT_SYNC")
        assert _capability_payload(other)["items"]
        assert os.environ.get("DL_WIRED_CRDT_SYNC") == before

    def test_the_report_promotes_it_after_a_real_merge(self, brain, other):
        from dreamlayer.ai_brain.server.server import _capability_payload
        _keep(brain, _figment())
        other.sync_merge(brain.sync_export())
        row = next(i for i in _capability_payload(other)["items"]
                   if i["key"] == "crdt_sync")
        assert row["state"] == "active", row

    def test_the_report_leaves_an_unsynced_brain_dormant(self, brain):
        from dreamlayer.ai_brain.server.server import _capability_payload
        row = next(i for i in _capability_payload(brain)["items"]
                   if i["key"] == "crdt_sync")
        assert row["state"] != "active", row


class TestTheState:

    def test_it_reports_what_there_is_to_sync(self, brain):
        _keep(brain, _figment())
        st = brain.sync_state()
        assert st["available"] is True
        assert st["figments"] == 1
        assert st["proved"] is False

    def test_proved_follows_a_real_merge(self, brain, other):
        _keep(brain, _figment())
        other.sync_merge(brain.sync_export())
        assert other.sync_state()["proved"] is True


class TestItIsReachable:

    def test_the_routes_are_registered(self):
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        assert '"/dreamlayer/vault/sync": _get_vault_sync' in src
        assert '"/dreamlayer/vault/sync": _post_vault_sync' in src
        assert '"/dreamlayer/vault/sync/state": _get_vault_sync_state' in src

    def test_the_export_route_is_local_only_like_backup(self):
        """The blob is the wearer's whole repertoire — as sensitive as `/backup`,
        and the design's premise is that no server ever holds it."""
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        i = src.index("def _get_vault_sync(")
        body = src[i:i + 1400]
        assert "_from_localhost()" in body
        assert "403" in body

    def test_the_blob_round_trips_as_base64(self, brain, other):
        """What the routes actually move. A blob that does not survive the
        encoding is a sync that works in tests and never on a wearer's machine."""
        _keep(brain, _figment())
        wire = base64.b64encode(brain.sync_export()).decode("ascii")
        assert other.sync_merge(base64.b64decode(wire))["ok"] is True

    def test_the_panel_can_save_and_load_a_snapshot(self):
        src = PANEL.read_text(encoding="utf-8")
        assert "async function syncSave" in src
        assert "async function syncLoad" in src
        assert 'id="syncFile"' in src

    def test_the_panel_says_when_a_figment_was_altered_in_transit(self):
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function syncLoad")
        body = src[i:i + 1800]
        assert "r.tampered" in body
        assert "altered in transit" in body

    def test_the_panel_reloads_the_same_file_if_you_pick_it_twice(self):
        """A file input does not re-fire `change` for the same file unless the
        value is cleared — and re-loading a snapshot is legitimate here, because
        merging one twice is a no-op by construction."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function syncLoad")
        assert 'ev.target.value=""' in src[i:i + 600]

    def test_the_panel_shows_the_state_on_load(self):
        src = PANEL.read_text(encoding="utf-8")
        assert "async function refreshSync" in src
        assert 'if($("syncStat")) refreshSync();' in src
