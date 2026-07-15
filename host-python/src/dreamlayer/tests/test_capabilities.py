"""Capability report + deployment profiles — logic, CLI, and (the important
part) drift-proofing: capabilities.py, the adapters' extras, and pyproject's
profile groups are asserted equal, so 'keep these in sync' is a test failure
instead of a comment."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


from dreamlayer import capabilities as C

PYPROJECT = Path(__file__).parents[3] / "pyproject.toml"


def _optional_deps() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["optional-dependencies"]


# --- core logic, exercised through synthetic caps (no optional deps needed) ---

def _cap(**kw) -> C.Cap:
    base: dict = dict(key="probe_test", title="t", tier="test",
                modules=("json",), extra="memory", seam="x.py")
    base.update(kw)
    return C.Cap(**base)


def test_installed_uses_find_spec_not_import():
    assert C.installed(_cap(modules=("json",))) is True          # stdlib: present
    assert C.installed(_cap(modules=("definitely_not_a_module_xyz",))) is False
    # any-of semantics: one resolvable name is enough
    assert C.installed(_cap(modules=("nope_xyz", "os"))) is True
    # a hostile name must not raise out of the probe
    assert C.installed(_cap(modules=("...broken..name",))) is False


def test_env_flag_turns_installed_into_off():
    cap = _cap(modules=("json",))
    assert C.state(cap, env={}) == "active"
    assert C.state(cap, env={cap.flag_env: "1"}) == "off"
    assert C.state(cap, env={cap.flag_env: "false"}) == "active"   # explicit no
    assert C.enabled("vector_search", env={"DL_DISABLE_VECTOR_SEARCH": "1"}) is False


def test_state_vocabulary():
    assert C.state(_cap(modules=("nope_xyz",)), env={}) == "missing"
    assert C.state(_cap(modules=(), kind="service"), env={}) == "external"
    import sys
    darwin_cap = _cap(modules=("json",), kind="darwin")
    expected = "active" if sys.platform == "darwin" else "unsupported"
    assert C.state(darwin_cap, env={}) == expected


def test_report_covers_every_cap_with_unique_keys():
    rows = C.report(env={})
    assert len(rows) == len(C.CAPABILITIES)
    keys = [r["key"] for r in rows]
    assert len(set(keys)) == len(keys)
    assert sum(C.summary(env={}).values()) == len(C.CAPABILITIES)
    # whatever the machine has installed, states stay within the vocabulary
    vocab = {"active", "off", "missing", "unsupported", "external"}
    assert {r["state"] for r in rows} <= vocab


def test_profiles_derived_not_hand_listed():
    vec = next(c for c in C.CAPABILITIES if c.key == "vector_search")
    assert set(vec.profiles) == {"profile-phone", "profile-mac"}
    ext = next(c for c in C.CAPABILITIES if c.kind == "service")
    assert ext.profiles == ()                       # services install nothing


# --- drift-proofing against pyproject.toml -----------------------------------

def test_every_cap_extra_exists_in_pyproject():
    groups = set(_optional_deps())
    for cap in C.CAPABILITIES:
        if cap.extra is not None:
            assert cap.extra in groups, f"{cap.key} references missing extra {cap.extra!r}"


def test_profile_groups_match_pyproject_exactly():
    deps = _optional_deps()
    toml_profiles = {k: v for k, v in deps.items() if k.startswith("profile-")}
    assert set(toml_profiles) == set(C.PROFILES), "profile set drifted"
    for name, entries in toml_profiles.items():
        assert len(entries) == 1, f"{name} must be one self-referential extra"
        m = re.fullmatch(r"dreamlayer\[([\w,\- ]+)\]", entries[0])
        assert m, f"{name} entry {entries[0]!r} is not dreamlayer[...]"
        toml_extras = {e.strip() for e in m.group(1).split(",")}
        assert toml_extras == set(C.PROFILES[name]), f"{name} extras drifted"
        # and every referenced extra must itself exist
        assert toml_extras <= set(deps), f"{name} references undefined extras"


def test_profile_extras_only_reference_adapter_groups():
    non_profile = {k for k in _optional_deps() if not k.startswith("profile-")}
    for extras in C.PROFILES.values():
        assert set(extras) <= non_profile


# --- CLI ----------------------------------------------------------------------

def test_cli_json_roundtrips(capsys):
    assert C.main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {"capabilities", "summary", "profiles"} <= set(out)
    assert len(out["capabilities"]) == len(C.CAPABILITIES)


def test_cli_profile_filter(capsys):
    assert C.main(["--json", "--profile", "profile-phone"]) == 0
    rows = json.loads(capsys.readouterr().out)["capabilities"]
    assert rows and all("profile-phone" in r["profiles"] for r in rows)
    assert all(r["kind"] != "service" for r in rows)


def test_cli_plain_table(capsys):
    assert C.main([]) == 0
    text = capsys.readouterr().out
    assert "DreamLayer capabilities" in text
    assert "vector_search" in text and "switch on with" in text


def test_probe_service_never_raises():
    exo = next(c for c in C.CAPABILITIES if c.key == "exo_cluster")
    assert C.probe_service(exo, timeout=0.2) in (True, False)
    assert C.probe_service(_cap(kind="service", modules=())) is False  # unknown key


def test_disabled_service_reports_off_not_external():
    """Audit 2026-07-14: DL_DISABLE_* must be honored for service caps too."""
    from dreamlayer import capabilities as caps
    svc = next((c for c in caps.CAPABILITIES if c.kind == "service"), None)
    if svc is None:
        return
    assert caps.state(svc, env={}) == "external"
    assert caps.state(svc, env={svc.flag_env: "1"}) == "off"
    assert caps.enabled("definitely-not-a-real-key") is False   # no KeyError
