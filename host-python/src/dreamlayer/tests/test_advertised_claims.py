"""test_advertised_claims.py — the promises on the website, pinned to the code.

dreamlayer.app and the knowledge base make specific, checkable promises about
what this software will and will not do. Those are the claims a user relies on
when they decide to wear the thing, and they are the only claims we cannot fix
after the fact with an apology.

Every test here quotes the public sentence it defends and fails if the code
stops keeping it. A marketing claim with no test behind it is a claim that
drifts — the 2026-07-27 sweep of the site found three that already had:

  * "A retention lifecycle … hot purged after REM, warm 90 days" — the sweep
    has no live caller, so nothing ever expired. Copy corrected; the code fix
    is tracked in decisions/0001.
  * "no voice cloning … absent from the codebase by design" — a cloning engine
    IS present. What is actually true, and is now what we say, is narrower and
    stronger: it can only ever clone Juno's own baked clips.
  * "2,302 passing tests" — stale by roughly half.

The first two are pinned below. Deliberately NOT pinned: anything needing an
optional dependency, so this file stays green on a zero-extras install — the
promises here are about the SHIPPED default, which is the configuration a user
actually gets.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

_SRC = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# "No stranger face lookup … the shipped face embedder cannot return an
# identity at all — with no face model present it declines every frame rather
# than guessing, so there is no setting that turns stranger recognition on."
# --------------------------------------------------------------------------

pytestmark_note = "see docs privacy.html § Deliberately not built"


@pytest.mark.no_face_double
def test_the_shipped_face_embedder_cannot_identify_anyone():
    """The site's hardest promise. The PRODUCTION embedder (the autouse test
    double is opted out of here) must decline, not guess."""
    from dreamlayer.truth_lens.face_embed import FaceEmbedder

    emb = FaceEmbedder()
    assert emb.available is False, (
        "the shipped FaceEmbedder reports itself available — something wired a "
        "real face model into the default build, which the site says we do not do")

    rng = np.random.default_rng(7)
    for _ in range(8):
        frame = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        assert emb.process_frame(frame) is None, (
            "the shipped face embedder returned an embedding for an arbitrary "
            "frame — stranger recognition is reachable in the default build")


@pytest.mark.no_face_double
def test_a_uniform_frame_does_not_assert_a_face():
    """The old stub called a 1x1 white pixel a face at 100%. Uniform and
    degenerate frames must still decline."""
    from dreamlayer.truth_lens.face_embed import FaceEmbedder

    emb = FaceEmbedder()
    for frame in (np.zeros((32, 32, 3), np.uint8),
                  np.full((32, 32, 3), 255, np.uint8),
                  np.ones((1, 1, 3), np.uint8) * 255):
        assert emb.process_frame(frame) is None


# --------------------------------------------------------------------------
# "DreamLayer never clones your voice, or anyone else's … the only reference
# clips it is ever given are her own pre-recorded takes, hard-coded in the app.
# No microphone audio … is ever used as a voice reference."
# --------------------------------------------------------------------------

def test_the_only_voice_clone_reference_is_junos_own_baked_clips():
    """Pins the shape of the single production call site. If someone ever wires
    user or bystander audio into CloneTTS, this fails — and the promise on the
    site would have to change before the code could ship."""
    server = (_SRC / "ai_brain" / "server" / "server.py").read_text()

    sites = [m for m in re.finditer(r"CloneTTS\(([^)]*)\)", server)]
    assert len(sites) == 1, (
        f"expected exactly one CloneTTS construction in server.py, found "
        f"{len(sites)}: {[s.group(0) for s in sites]}. Every additional one is a "
        f"new chance to point voice cloning at somebody's actual voice.")

    # the reference list must be built from the baked juno_*.mp3 assets, in the
    # ~10 lines above the call — not from config, a request body, or a mic buffer
    call_at = sites[0].start()
    window = server[max(0, call_at - 600):call_at]
    assert 'glob("juno_*.mp3")' in window, (
        "the CloneTTS reference clips are no longer the hard-coded juno_*.mp3 "
        "assets. The site promises no voice but Juno's is ever cloned.")


def test_no_module_feeds_captured_audio_into_the_clone_engine():
    """A blunt cross-check on the promise: nothing outside the voice-clone module
    itself and its tests may even mention CloneTTS, so there is no second path
    in that the pinned call site above would miss."""
    hits = []
    for path in _SRC.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if path.name in ("voice_clone.py",):
            continue
        if "CloneTTS" in path.read_text():
            hits.append(str(path.relative_to(_SRC)))
    assert hits == ["ai_brain/server/server.py"], (
        f"CloneTTS is referenced from unexpected modules: {hits}")


# --------------------------------------------------------------------------
# "Cloud AI is off by default and opt-in."
# --------------------------------------------------------------------------

def test_cloud_is_off_in_a_fresh_config():
    """The site says off by default, in bold, twice. A fresh install must agree."""
    from dreamlayer.ai_brain.server.store import BrainConfig

    cfg = BrainConfig()
    assert cfg.cloud_enabled is False, (
        "a fresh BrainConfig has cloud AI ON — the site says it is off by default")
    assert cfg.cloud_calls == 0
    assert not cfg.cloud_api_key, "a fresh install ships with a cloud key set"


# --------------------------------------------------------------------------
# The claim the sweep found FALSE, kept honest here so it cannot silently
# become true-again-but-unnoticed, or false-again after a fix.
# --------------------------------------------------------------------------

def test_retention_sweep_is_still_unwired_or_the_docs_need_updating():
    """decisions/0001: nothing on the device expires, because RetentionSweep is
    built only inside a nightly pass with no production caller.

    The docs now say so out loud. When someone wires it up, THIS test fails —
    which is the reminder to go and make the documentation optimistic again.
    That is the intended direction of travel; the test exists so the copy and
    the code cannot drift apart a second time."""
    ops = (_SRC / "orchestrator" / "ops_dream_rem.py").read_text()
    assert "RetentionSweep(" in ops, "the sweep moved — re-check decisions/0001"

    callers = []
    for path in _SRC.rglob("*.py"):
        if "tests" in path.parts or path.name == "ops_dream_rem.py":
            continue
        body = path.read_text()
        if re.search(r"\.maybe_dream_tonight\s*\(", body):
            callers.append(str(path.relative_to(_SRC)))
    assert not callers, (
        f"maybe_dream_tonight now has production caller(s) {callers} — the "
        f"retention lifecycle may finally be live. Re-verify decisions/0001, and "
        f"if it now runs, restore the confident wording in the docs' "
        f"perception-memory page and delete this test.")
