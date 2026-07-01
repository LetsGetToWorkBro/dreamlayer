"""Deployer gates, transport envelopes, hot-swap and revoke flows."""
import json

import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END,
    Vault, StageDeployer, RealityCompilerV2,
    FIGMENT_PUT, FIGMENT_SWAP, FIGMENT_REVOKE,
)
from dreamlayer.reality_compiler.v2 import transport


def make_fig(name="Timer") -> Figment:
    f = Figment(name=name, initial="a")
    f.add_scene(Scene(id="a", duration_sec=10.0,
                      lines=[TextLine("hi", row=1)],
                      on_timeout=[Transition(target=END)]))
    return f


@pytest.fixture
def rig(tmp_path):
    vault = Vault(tmp_path / "vault")
    return vault, StageDeployer(vault)


class TestTransport:
    def test_frame_roundtrip(self):
        env = transport.put_envelope(make_fig())
        raw = transport.frame(env)
        assert int.from_bytes(raw[:4], "big") == len(raw)
        assert transport.parse_frame(raw) == json.loads(
            json.dumps(env, sort_keys=True))

    def test_envelope_types_match_lua_constants(self):
        # keep in lockstep with halo-lua/ble/message_types.lua
        from pathlib import Path
        lua = (Path(__file__).resolve().parents[4]
               / "halo-lua" / "ble" / "message_types.lua").read_text()
        for const in (FIGMENT_PUT, FIGMENT_SWAP, FIGMENT_REVOKE,
                      transport.FIGMENT_TEXT, transport.FIGMENT_ACK,
                      transport.FIGMENT_EVENT):
            assert f'"{const}"' in lua, f"{const} missing from message_types.lua"


class TestDeployGates:
    def test_deploy_signed_figment(self, rig):
        vault, dep = rig
        fig = make_fig()
        vault.keep(fig)
        rec = dep.deploy(fig.id)
        assert rec.success
        assert [e["t"] for e in rec.envelopes] == [FIGMENT_PUT, FIGMENT_SWAP]

    def test_refuses_unknown(self, rig):
        _, dep = rig
        rec = dep.deploy("nope")
        assert not rec.success and "REFUSED" in rec.message

    def test_refuses_revoked(self, rig):
        vault, dep = rig
        fig = make_fig()
        vault.keep(fig)
        vault.revoke(fig.id)
        rec = dep.deploy(fig.id)
        assert not rec.success and "revoked" in rec.message

    def test_refuses_tampered(self, rig):
        vault, dep = rig
        fig = make_fig()
        vault.keep(fig)
        path = vault._path(fig.id)
        raw = json.loads(path.read_text())
        raw["figment"]["name"] = "Evil"
        path.write_text(json.dumps(raw))
        rec = dep.deploy(fig.id)
        assert not rec.success and "signature" in rec.message

    def test_reverifies_budgets_at_deploy(self, rig):
        # defense in depth: even a signed entry is re-proven before send
        vault, dep = rig
        fig = make_fig()
        fig.scenes["a"].duration_sec = 0.1        # illegal, sign anyway
        entry = {"figment": fig.to_dict(),
                 "sig": vault.signer.sign(fig), "kept_at": 0}
        vault._path(fig.id).write_text(json.dumps(entry))
        rec = dep.deploy(fig.id)
        assert not rec.success and "budget proof" in rec.message

    def test_hot_swap_skips_re_put(self, rig):
        vault, dep = rig
        a, b = make_fig("A"), make_fig("B")
        vault.keep(a); vault.keep(b)
        dep.deploy(a.id)
        dep.deploy(b.id)
        rec = dep.deploy(a.id)                    # already on device
        assert [e["t"] for e in rec.envelopes] == [FIGMENT_SWAP]

    def test_revoke_sends_clear_and_forgets(self, rig):
        vault, dep = rig
        fig = make_fig()
        vault.keep(fig)
        dep.deploy(fig.id)
        rec = dep.revoke(fig.id)
        assert rec.envelopes[0]["t"] == FIGMENT_REVOKE
        assert not dep.deploy(fig.id).success     # durably refused


class TestCompilerFacade:
    def test_keep_refuses_unproven(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path)
        fig = make_fig()
        fig.scenes["a"].duration_sec = 0.1
        with pytest.raises(Exception, match="BUDGETS"):
            rc.keep(fig)

    def test_full_loop(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path)
        s = rc.rehearse("Rolling rounds")
        s.double_tap()
        s.say("rolling - three minutes")
        s.say("last ten seconds, pulse")
        r = s.finish()
        assert r.ok
        rc.keep(r.figment)
        assert rc.deploy(r.figment.id).success
        assert [e.figment.name for e in rc.repertoire()] == ["Rolling rounds"]
        rc.revoke(r.figment.id)
        assert rc.repertoire() == []
