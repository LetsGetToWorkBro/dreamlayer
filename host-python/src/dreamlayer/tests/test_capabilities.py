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
    vocab = {"active", "off", "dormant", "missing", "unsupported", "external"}
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
    assert C.PROFILES, "no profiles declared — this loop would check nothing"
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


# --- the capability table describes real files and real extras ---------------
# Individual capabilities have bespoke seam assertions scattered across the
# suite (barcode, dream_style, graph_recall, exo_cluster, …). That covers the
# ones somebody happened to write a test for. A seam renamed out from under a
# capability WITHOUT such a test kept claiming a file that no longer existed,
# and the report — which is a promise to the wearer about what their glasses
# can do — went on citing it. These ask the question of all 67 at once.
#
# "every extra a capability names is declared" is NOT here: it already exists
# above as test_every_cap_extra_exists_in_pyproject. A second copy was written
# and deleted — this repo's own worked example is twelve hand-written Veil
# gates whose docstrings each promised they mirrored the others, so a duplicate
# assertion is not free even when both copies happen to be right.

def _dists(extra: str) -> set:
    return {re.split(r"[<>=!~;\[\s]", r.strip(), maxsplit=1)[0].lower().replace("_", "-")
            for r in _optional_deps().get(extra, [])}


#: Import name != distribution name. Both are real and neither is guessable
#: from the other, so they are written down rather than pattern-matched: a
#: normalisation loose enough to derive `TTS` from `coqui-tts` is loose enough
#: to accept a genuinely wrong pairing. A new entry here should be a deliberate
#: line in a diff.
IMPORT_NAME_IS_NOT_THE_DIST = {
    "TTS": "coqui-tts",
    "hulearn": "human-learn",
    "zxingcpp": "zxing-cpp",
    "sherpa_onnx": "sherpa-onnx",
    "rerun": "rerun-sdk",
    "panns_inference": "panns-inference",
    "lightrag": "lightrag-hku",
    "piper": "piper-tts",
    "surya": "surya-ocr",
}


def _provided_by(module: str, dists: set) -> bool:
    mapped = IMPORT_NAME_IS_NOT_THE_DIST.get(module)
    if mapped:
        return mapped in dists
    return module.lower().replace("_", "-") in dists


class TestEveryCapabilityPointsAtSomethingReal:
    def test_the_check_is_not_looking_at_an_empty_table(self):
        """CAPABILITIES is imported, not globbed, but every other assertion in
        this class is a loop — and a loop over an empty list passes. The floor
        is a non-vacuity guard, not a size policy (CLAUDE.md #1)."""
        assert len(C.CAPABILITIES) >= 50, (
            f"only {len(C.CAPABILITIES)} capabilities — the table has probably "
            f"stopped being read rather than shrinking by half")

    def test_every_single_path_seam_exists(self):
        """`seam` is free text: some name two files, one names a docs recipe.
        Only the ones that are exactly one .py path are checked — the rest
        cannot be resolved without guessing, and a check that guesses is worse
        than none."""
        pkg = Path(C.__file__).parent
        checked, missing = 0, []
        for c in C.CAPABILITIES:
            if not re.fullmatch(r"[\w/.\-]+\.py", c.seam or ""):
                continue
            checked += 1
            if not (pkg / c.seam).exists():
                missing.append(f"{c.key} -> {c.seam}")
        assert checked >= 40, (
            f"only {checked} seams were path-shaped — the seam field's format "
            f"has changed and this test is now reading almost nothing")
        assert not missing, (
            "capabilities naming a seam file that does not exist; the report "
            "promises the wearer a feature and cites a deleted file:\n  "
            + "\n  ".join(missing))

    def test_every_capability_is_installable_by_its_own_extra(self):
        """The project's own recurring question, one layer down: importable is
        not installable. A capability can name a real module and a real extra
        that does not contain it, and then `pip install dreamlayer[extra]`
        completes and the capability stays dark forever.

        Any-of, deliberately: `sound_events` ladders PANNs then sherpa-onnx and
        the second engine lives in `voice`. The requirement is that AT LEAST
        ONE engine arrives with the extra the capability tells you to install.
        """
        broken = []
        for c in C.CAPABILITIES:
            if c.extra is None or c.kind != "python" or not c.modules:
                continue
            dists = _dists(c.extra)
            if not any(_provided_by(m, dists) for m in c.modules):
                broken.append(f"{c.key}: imports {list(c.modules)}, but "
                              f"[{c.extra}] installs {sorted(dists)}")
        assert not broken, (
            "capabilities that installing their own extra cannot switch "
            "on:\n  " + "\n  ".join(broken))

    def test_the_alias_table_has_no_stale_rows(self):
        """The other direction. An alias kept after its capability is gone
        makes the check above quietly more permissive than it reads."""
        used = {m for c in C.CAPABILITIES for m in c.modules}
        stale = sorted(set(IMPORT_NAME_IS_NOT_THE_DIST) - used)
        assert not stale, (
            f"{stale} are in IMPORT_NAME_IS_NOT_THE_DIST but no capability "
            f"imports them — drop the rows")
