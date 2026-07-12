"""Pin the selene Lua-lint config so it can't silently rot even where the
selene binary isn't installed: the files exist, parse, declare the device
std, and stay in sync with .luacheckrc's globals + ignores."""
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
HALO = REPO / "halo-lua"


def test_selene_toml_parses_and_targets_the_device_std():
    cfg = tomllib.loads((HALO / "selene.toml").read_text())
    assert cfg["std"] == "lua53+dreamlayer"
    # cosmetic lints stay out of the gate, mirroring .luacheckrc's ignores
    assert cfg["rules"]["unused_variable"] == "allow"
    assert cfg["rules"]["empty_if"] == "allow"


def test_selene_std_declares_the_device_globals():
    yaml = pytest.importorskip("yaml")
    std = yaml.safe_load((HALO / "dreamlayer.yml").read_text())
    assert std["base"] == "lua53"
    # the same globals .luacheckrc grants: frame (read), halo + tick (writable)
    assert std["globals"]["frame"]["property"] == "read-only"
    assert "halo" in std["globals"]
    assert "_dreamlayer_tick" in std["globals"]


def test_selene_globals_match_luacheckrc():
    rc = (HALO / ".luacheckrc").read_text()
    yaml = pytest.importorskip("yaml")
    std = yaml.safe_load((HALO / "dreamlayer.yml").read_text())
    for g in ("frame", "halo", "_dreamlayer_tick"):
        assert g in rc, f"{g} missing from .luacheckrc"
        assert g in std["globals"], f"{g} missing from selene std"


def test_ci_runs_selene():
    wf = (REPO / ".github" / "workflows" / "lua.yml").read_text()
    assert "selene" in wf and "cargo install selene" in wf
