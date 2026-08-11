"""The moondream adapter must never construct the cloud client.

Found 2026-08-11 while scoping #647: in EVERY packaged release of moondream —
the locked 1.3.0 included, not just the 2.x that #635 proposed — ``vl()`` is a
factory whose default return is a CloudVL, and CloudVL.query() POSTs the
base64 frame to api.moondream.ai with the auth header merely omitted when
there is no api_key. The frame leaves the device; only the *answer* fails.
The adapter sits on the ambient camera loop (live.py -> default_classifier),
so the shipped ``md.vl()`` bare call was wearer frames to a third party with
no Veil check and no consent sink. The fix is ``vl(local=True)``, which
selects the on-device Photon runtime and raises where it cannot run.

Two guards, per CLAUDE.md #6: the behavioural test drives the real adapter
through a fake ``moondream`` module shaped like the real factory, and the AST
test is a source tripwire for the one thing behaviour cannot see — a NEW
``vl()`` call site added somewhere the fake module isn't installed.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest


def _fake_moondream(monkeypatch, calls):
    """Install a fake ``moondream`` module mirroring the real factory shape.

    Mirrors 1.3.0/2.0.1 exactly: bare vl() returns a cloud client. Here the
    cloud client's query() raises AssertionError instead of doing network I/O,
    so a regression to bare vl() cannot silently pass by accident — the
    adapter would swallow the error and return None, and the positive
    assertion below would fail loudly.
    """

    class _CloudVL:
        def query(self, img, prompt):  # pragma: no cover - reaching this IS the bug
            raise AssertionError(
                "CloudVL.query() called: the adapter constructed the cloud "
                "client — a wearer frame would have left the device here.")

    class _LocalVL:
        def query(self, img, prompt):
            return {"answer": "Mug"}

    mod = types.ModuleType("moondream")

    def vl(api_key=None, endpoint=None, local=False, **kwargs):
        calls.append({"api_key": api_key, "local": local, **kwargs})
        return _LocalVL() if local else _CloudVL()

    mod.vl = vl
    monkeypatch.setitem(sys.modules, "moondream", mod)
    return mod


class TestTheFrameNeverLeavesTheDevice:
    def test_the_adapter_constructs_the_local_runtime_and_classifies(
            self, monkeypatch):
        pytest.importorskip("PIL")
        pytest.importorskip("numpy")
        from PIL import Image

        from dreamlayer.object_lens.classify_backends import MoondreamClassifier

        calls: list[dict] = []
        _fake_moondream(monkeypatch, calls)
        monkeypatch.setattr(MoondreamClassifier, "available", True)

        clf = MoondreamClassifier()
        result = clf(Image.new("RGB", (8, 8)))

        # Both directions in one place: the classify succeeded THROUGH the
        # local client (a cloud construction would have raised in query() and
        # surfaced here as None), and the factory saw local=True explicitly.
        assert result == ("Mug", clf.confidence)
        assert calls == [{"api_key": None, "local": True}]

    def test_a_dead_local_runtime_degrades_to_none_not_to_cloud(
            self, monkeypatch):
        """Where Photon cannot start (no CUDA/MPS — every CI runner), the
        adapter must yield None so the ladder moves on, never retry via the
        cloud path. Mirrors the RuntimeError kestrel raises at device pick."""
        pytest.importorskip("PIL")
        from PIL import Image

        from dreamlayer.object_lens.classify_backends import MoondreamClassifier

        mod = types.ModuleType("moondream")
        state = {"bare_calls": 0}

        def vl(api_key=None, endpoint=None, local=False, **kwargs):
            if not local:
                state["bare_calls"] += 1
                raise AssertionError("cloud construction attempted")
            raise RuntimeError(
                "Photon local inference needs a supported accelerator")

        mod.vl = vl
        monkeypatch.setitem(sys.modules, "moondream", mod)
        monkeypatch.setattr(MoondreamClassifier, "available", True)

        clf = MoondreamClassifier()
        assert clf(Image.new("RGB", (8, 8))) is None
        assert state["bare_calls"] == 0


class TestNobodyAddsABareVlCall:
    """Source tripwire (deliberately, per CLAUDE.md #6): the behavioural tests
    above exercise MoondreamClassifier, but a NEW call site in another class
    or module would dodge them. Every ``.vl(...)`` call in the object-lens
    package must carry ``local=True`` as a literal keyword."""

    def test_every_vl_call_in_object_lens_says_local_true(self):
        pkg = (Path(__file__).resolve().parents[1] / "object_lens")
        files = sorted(pkg.glob("*.py"))
        assert files, f"object_lens package not found at {pkg}"

        vl_calls = 0
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else None)
                if name != "vl":
                    continue
                vl_calls += 1
                ok = any(
                    kw.arg == "local"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in node.keywords)
                assert ok, (
                    f"{path.name}:{node.lineno}: vl() call without a literal "
                    f"local=True — in every packaged moondream release the "
                    f"default is a cloud client that transmits the frame "
                    f"before auth fails. See this file's docstring.")

        # The scan is not vacuous: the adapter's own call must be in it.
        assert vl_calls >= 1, (
            "found no vl() calls at all — the extractor is broken or the "
            "adapter moved; fix the glob before trusting this green")
