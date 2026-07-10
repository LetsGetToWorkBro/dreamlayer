"""test_heirloom_figments.py — Heirloom figments (INNOVATION_SESSION 5.5): a
dedication rides in the signed canonical data, so a behavior is provably its
author's, and the vault surfaces an "Inherited" section."""
from __future__ import annotations

from dreamlayer.reality_compiler.v2 import RealityCompilerV2
from dreamlayer.reality_compiler.v2.vault import Vault


def _fig(name="Rolling rounds"):
    rc = RealityCompilerV2()
    s = rc.rehearse(name)
    s.double_tap()
    s.say("rolling - three minutes")
    s.say("last ten seconds, pulse")
    s.say("then it starts again")
    return s.finish().figment


def test_dedicate_rides_in_the_signed_canonical_json():
    fig = _fig()
    assert fig.dedication() is None
    fig.dedicate("for Grandma, who proofed bread at dawn")
    assert fig.dedication().startswith("for Grandma")
    # part of what gets signed — provably hers
    assert "dedication" in fig.canonical_json()


def test_vault_inherited_lists_only_dedicated(tmp_path):
    v = Vault(tmp_path)
    v.keep(_fig("plain timer"))                 # no dedication
    heir = _fig("heirloom")
    heir.dedicate("for Dad")                    # dedicate BEFORE keep (it's signed)
    v.keep(heir)
    inherited = v.inherited()
    assert [e.figment.id for e in inherited] == [heir.id]
    assert inherited[0].figment.dedication() == "for Dad"


def test_heirloom_survives_a_vault_roundtrip(tmp_path):
    heir = _fig()
    heir.dedicate("for the trail crew, 2009")
    Vault(tmp_path).keep(heir)
    # a fresh Vault over the same dir re-verifies the signature and reads it back
    reloaded = Vault(tmp_path).inherited()
    assert len(reloaded) == 1
    assert reloaded[0].figment.dedication() == "for the trail crew, 2009"
