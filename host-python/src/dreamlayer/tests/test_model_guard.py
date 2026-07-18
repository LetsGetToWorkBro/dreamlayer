"""ML-model supply-chain integrity + offline-posture fetch gate (A1).

The Brain loads ML weights from public CDNs unsigned, and several formats are
pickle — loading a swapped/MITM'd checkpoint is RCE that no source scanner sees
(refute 2026-07-18: the tree had zero offline flags, zero checksums, zero
weights_only guards). model_guard is the three-layer answer; these pin it:

 * pinned integrity — a wrong file raises, a right file passes, unpinned warns
   (or hard-fails under strict);
 * offline-posture gate — offline/incognito/LAN-only sets HF_HUB_OFFLINE so no
   hub loader can reach a CDN;
 * no-pickle-RCE — safe_torch_load forces weights_only=True.
"""
from __future__ import annotations

import sys
import types

import pytest

from dreamlayer import model_guard
from dreamlayer.model_guard import (
    ModelFetchBlocked, ModelIntegrityError,
)


# --- hashing + verification --------------------------------------------------

def test_verify_file_passes_on_match_and_raises_on_tamper(tmp_path):
    f = tmp_path / "weights.bin"
    f.write_bytes(b"the trusted bytes")
    good = model_guard.sha256_file(f)
    assert model_guard.verify_file(f, good) is True
    # a single flipped byte is a different hash → tampering
    f.write_bytes(b"the trusted byteS")
    with pytest.raises(ModelIntegrityError):
        model_guard.verify_file(f, good)


def test_verify_tree_flags_a_missing_pinned_file(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"a")
    files = {"a.bin": model_guard.sha256_file(tmp_path / "a.bin"),
             "b.bin": "0" * 64}
    with pytest.raises(ModelIntegrityError):
        model_guard.verify_tree(tmp_path, files)


def test_verify_tree_empty_pins_is_unpinned(tmp_path):
    assert model_guard.verify_tree(tmp_path, {}) is False


def test_verify_path_pinned_match_ok_mismatch_raises(tmp_path):
    root = tmp_path / "mymodel"
    root.mkdir()
    (root / "model.safetensors").write_bytes(b"weights")
    sha = model_guard.sha256_file(root / "model.safetensors")
    lock = {"models": {"mymodel": {"files": {"model.safetensors": sha}}}}
    assert model_guard.verify_path("mymodel", root, lock=lock) is True
    # corrupt the file → mismatch raises regardless of strict
    (root / "model.safetensors").write_bytes(b"evil")
    with pytest.raises(ModelIntegrityError):
        model_guard.verify_path("mymodel", root, lock=lock, strict=False)


def test_verify_path_unpinned_warns_but_hard_fails_under_strict(tmp_path):
    lock = {"models": {"m": {"files": {}}}}
    # not strict → returns False (advisory), does not raise
    assert model_guard.verify_path("m", tmp_path, lock=lock, strict=False) is False
    # strict → raises
    with pytest.raises(ModelIntegrityError):
        model_guard.verify_path("m", tmp_path, lock=lock, strict=True)


def test_verify_path_single_sha_form(tmp_path):
    f = tmp_path / "one.bin"
    f.write_bytes(b"single")
    sha = model_guard.sha256_file(f)
    lock = {"models": {"one": {"sha256": sha}}}
    assert model_guard.verify_path("one", f, lock=lock) is True


# --- the shipped models.lock -------------------------------------------------

def test_shipped_lock_loads_and_declares_the_known_models():
    lock = model_guard.load_lock()             # packaged models.lock
    models = model_guard.known_models(lock)
    assert models, "models.lock should declare the on-device models"
    for expected in ("all-MiniLM-L6-v2", "yolo11n.pt", "en_core_web_sm"):
        assert expected in models
        assert "source" in models[expected]


def test_load_lock_tolerates_missing_or_malformed(tmp_path):
    assert model_guard.load_lock(tmp_path / "nope.lock") == {}
    bad = tmp_path / "bad.lock"
    bad.write_text("{not json")
    assert model_guard.load_lock(bad) == {}


# --- posture-gated fetch -----------------------------------------------------

@pytest.mark.parametrize("posture,expected", [
    ("connected", True), ("online", True), ("", True),
    ("lan_only", False), ("incognito", False), ("offline", False),
])
def test_posture_allows_fetch_string(posture, expected):
    assert model_guard.posture_allows_fetch(posture) is expected


def test_posture_none_defaults_allow_unless_env(monkeypatch):
    monkeypatch.delenv("DL_MODELS_OFFLINE", raising=False)
    assert model_guard.posture_allows_fetch(None) is True
    monkeypatch.setenv("DL_MODELS_OFFLINE", "1")
    assert model_guard.posture_allows_fetch(None) is False


def test_posture_object_incognito_and_lan_only():
    class _Cfg:
        network_mode = "connected"
        lan_only = False

    class _Brain:
        def __init__(self, incog, lan):
            self._incog = incog
            self.config = _Cfg()
            self.config.lan_only = lan
            self.config.network_mode = "lan_only" if lan else "connected"

        def incognito_now(self):
            return self._incog

    assert model_guard.posture_allows_fetch(_Brain(False, False)) is True
    assert model_guard.posture_allows_fetch(_Brain(True, False)) is False   # incognito wins
    assert model_guard.posture_allows_fetch(_Brain(False, True)) is False   # lan_only


def test_apply_offline_posture_sets_and_clears_hf_flags(monkeypatch):
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("_DL_SET_" + k, raising=False)
    # offline → flags on
    model_guard.apply_offline_posture("lan_only")
    import os
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    # back to connected → our flags cleared again
    model_guard.apply_offline_posture("connected")
    assert "HF_HUB_OFFLINE" not in os.environ


def test_apply_offline_posture_respects_operator_export(monkeypatch):
    import os
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")          # operator's own choice
    monkeypatch.delenv("_DL_SET_HF_HUB_OFFLINE", raising=False)
    model_guard.apply_offline_posture("connected")     # must NOT clobber it
    assert os.environ.get("HF_HUB_OFFLINE") == "1"


def test_offline_guard_restores_env(monkeypatch):
    import os
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    with model_guard.offline_guard("offline") as fetch:
        assert fetch is False
        assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert "HF_HUB_OFFLINE" not in os.environ          # restored


def test_require_fetch_allowed_blocks_when_offline():
    with pytest.raises(ModelFetchBlocked):
        model_guard.require_fetch_allowed("incognito", "all-MiniLM-L6-v2")
    model_guard.require_fetch_allowed("connected", "all-MiniLM-L6-v2")   # no raise


def test_require_fetch_allowed_uses_live_process_decision(monkeypatch):
    """A loader with no posture in hand (ultralytics) must respect the live
    offline session set by apply_offline_posture."""
    for k in ("HF_HUB_OFFLINE", "_DL_ORIG_HF_HUB_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    model_guard.apply_offline_posture("lan_only")        # go offline
    with pytest.raises(ModelFetchBlocked):
        model_guard.require_fetch_allowed(model_id="yolo11n.pt")   # no posture arg
    model_guard.apply_offline_posture("connected")       # back online
    model_guard.require_fetch_allowed(model_id="yolo11n.pt")       # no raise


def test_apply_offline_posture_restores_operator_zero(monkeypatch):
    """An operator's explicit HF_HUB_OFFLINE=0 (I want online) must be RESTORED
    after an offline→online cycle, not left stuck at our '1' (refute 2026-07-18)."""
    import os
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.delenv("_DL_ORIG_HF_HUB_OFFLINE", raising=False)
    model_guard.apply_offline_posture("lan_only")        # we override to "1"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    model_guard.apply_offline_posture("connected")       # restore their "0"
    assert os.environ["HF_HUB_OFFLINE"] == "0"


# --- no-pickle-RCE torch load ------------------------------------------------

def test_safe_torch_load_forces_weights_only(monkeypatch):
    seen = {}

    def _fake_load(path, **kw):
        seen.update(kw)
        return "loaded"

    fake_torch = types.ModuleType("torch")
    fake_torch.load = _fake_load
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert model_guard.safe_torch_load("x.pt") == "loaded"
    assert seen.get("weights_only") is True


def test_safe_torch_load_degrades_on_old_torch(monkeypatch):
    calls = []

    def _fake_load(path, **kw):
        calls.append(kw)
        if "weights_only" in kw:
            raise TypeError("load() got an unexpected keyword 'weights_only'")
        return "loaded-legacy"

    fake_torch = types.ModuleType("torch")
    fake_torch.load = _fake_load
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert model_guard.safe_torch_load("x.pt") == "loaded-legacy"
    assert len(calls) == 2 and "weights_only" not in calls[1]   # retried without it


def test_safe_torch_load_does_not_disarm_on_an_unrelated_typeerror(monkeypatch):
    """A TypeError NOT about weights_only (e.g. a modern torch choking on a
    crafted checkpoint) must propagate — retrying without weights_only would
    strip the RCE guard (refute 2026-07-18)."""
    def _fake_load(path, **kw):
        raise TypeError("something else entirely")

    fake_torch = types.ModuleType("torch")
    fake_torch.load = _fake_load
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    with pytest.raises(TypeError):
        model_guard.safe_torch_load("x.pt")


def test_verify_tree_rejects_a_path_escape(tmp_path):
    (tmp_path / "safe.bin").write_bytes(b"ok")
    lock_files = {"../escape.bin": "0" * 64}
    with pytest.raises(ModelIntegrityError):
        model_guard.verify_tree(tmp_path, lock_files)


def test_verify_all_never_raises_on_missing_or_malformed(tmp_path):
    """Missing pinned file, unreadable file, and a non-dict lock entry are all
    collected, never propagated (refute 2026-07-18: FileNotFoundError leaked)."""
    lock = {"models": {
        "missing": {"sha256": "0" * 64},          # file absent under root
        "weird": ["not", "a", "dict"],            # malformed entry
    }}
    results = {r["model"]: r for r in model_guard.verify_all(tmp_path, lock)}
    assert results["missing"]["ok"] is False and results["missing"]["error"]
    assert results["weird"]["pinned"] is False


def test_prefer_safetensors():
    assert model_guard.prefer_safetensors({"prefer": "safetensors"}) is True
    assert model_guard.prefer_safetensors({"prefer": "pytorch"}) is False
    assert model_guard.prefer_safetensors({}) is False


# --- verify_all (CLI / release bootstrap) ------------------------------------

def test_verify_all_collects_results_without_raising(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "w.bin").write_bytes(b"ok")
    sha = model_guard.sha256_file(good / "w.bin")
    lock = {"models": {
        "good": {"files": {"w.bin": sha}},
        "bad": {"files": {"w.bin": "0" * 64}},
        "unpinned": {"files": {}},
    }}
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "w.bin").write_bytes(b"tampered")
    results = {r["model"]: r for r in model_guard.verify_all(tmp_path, lock)}
    assert results["good"]["ok"] is True
    assert results["bad"]["ok"] is False and results["bad"]["error"]
    assert results["unpinned"]["pinned"] is False
