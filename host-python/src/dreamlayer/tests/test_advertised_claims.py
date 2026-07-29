"""test_advertised_claims.py — the promises on the website, pinned to the code.

dreamlayer.app and the knowledge base make specific, checkable promises about
what this software will and will not do. Those are the claims a user relies on
when they decide to wear the thing, and they are the only claims we cannot fix
after the fact with an apology.

Every test here quotes the public sentence it defends and fails if the code
stops keeping it. A marketing claim with no test behind it is a claim that
drifts — the 2026-07-27 sweep of the site found three that already had:

  * "A retention lifecycle … hot purged after REM, warm 90 days" — the sweep
    had no live caller, so nothing ever expired. The copy was corrected, then
    the code was fixed (decisions/0001) and the copy made confident again; what
    is pinned below is now the live wiring, not its absence.
  * "no voice cloning … absent from the codebase by design" — a cloning engine
    IS present. What is actually true, and is now what we say, is narrower and
    stronger: it can only ever clone Juno's own baked clips.
  * "2,302 passing tests" — stale by roughly half.

The first two are pinned below. Deliberately NOT pinned: anything needing an
optional dependency, so this file stays green on a zero-extras install — the
promises here are about the SHIPPED default, which is the configuration a user
actually gets.

The 2026-07-29 sweep found a fourth, and it was the biggest:

  * "No stranger face lookup … the shipped face embedder cannot return an
    identity at all … there is no setting that turns stranger recognition on."
    A real recogniser now ships behind the opt-in `face` extra, and
    `BrainConfig.face_auto_enrol` is exactly that setting: with it on, a face
    matching nobody is PERSISTED rather than discarded, including bystanders
    who never agreed and cannot agree in the app. The copy was corrected in the
    same commit as the capability, so the site is never ahead of the build.

    What survived, and is pinned below because a narrow true claim is worth
    more than a broad false one: the DEFAULT build still cannot identify
    anyone, `face` is still in no deployment profile, matching is still local
    only — no public database, no cloud face search — and erase-everything and
    the retention sweep still reach every stored template.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

_SRC = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[4]

# The user-facing surfaces corrected on 2026-07-29. The drift guards below read
# these; on an installed wheel they are absent and the guards skip.
_PUBLIC_COPY = (
    "landing/privacy.html",
    "landing/index.html",
    "docs/gitbook/privacy.md",
    "docs/gitbook/perception-memory.md",
    "docs/gitbook/guide/privacy.md",
)


def _public_copy() -> dict:
    """The corrected pages, whitespace-flattened so a reflow cannot smuggle a
    retracted sentence back past a substring check."""
    out = {}
    for rel in _PUBLIC_COPY:
        p = _REPO / rel
        if not p.exists():
            pytest.skip(f"{rel} not on disk (installed wheel, not a checkout)")
        out[rel] = re.sub(r"\s+", " ", p.read_text()).lower()
    return out


# --------------------------------------------------------------------------
# "A default install cannot recognise a face at all … the face model ships
# only in the optional `face` package, which is in no install profile, and
# without it every frame is declined."
# --------------------------------------------------------------------------

pytestmark_note = "see docs privacy.html § Deliberately not built"


@pytest.mark.no_face_double
def test_the_shipped_face_embedder_cannot_identify_anyone():
    """The site's hardest promise. The PRODUCTION embedder (the autouse test
    double is opted out of here) must decline, not guess.

    A real model now EXISTS behind the opt-in `face` extra, so this asserts what
    the copy actually claims: the SHIPPED build — the default install, with no
    `face` pack and no weights — cannot return an identity. The invariant that
    keeps that true is that `face` is in no deployment profile, which is
    asserted separately and unconditionally below, because it cannot be
    satisfied by a machine simply not having installed something.

    The default build is pinned deterministically by conftest (opting out of the
    face double also pins the backend to absent), so this asserts the same thing
    on a bare CI runner and on a developer machine that opted into the pack —
    a local install must never flip a claim about what ships.

    What must NOT happen silently is a BUILD shipping the pack: that is the
    step-3 copy change (see HANDOFF), and
    `test_the_face_pack_is_in_no_deployment_profile` is the guard that fires if
    anyone tries.
    """
    from dreamlayer.truth_lens.face_embed import FaceEmbedder

    emb = FaceEmbedder()
    assert emb.available is False, (
        "the shipped FaceEmbedder reports itself available — something wired a "
        "real face model into the default build. The site says a default "
        "install cannot recognise a face at all; correct that copy first.")

    rng = np.random.default_rng(7)
    for _ in range(8):
        frame = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        assert emb.process_frame(frame) is None, (
            "the shipped face embedder returned an embedding for an arbitrary "
            "frame — face recognition is reachable in the default build")


def test_the_face_pack_is_in_no_deployment_profile():
    """What actually keeps "the shipped face embedder cannot return an identity"
    true, and the one check a machine cannot accidentally satisfy by not having
    installed something.

    Every target this project ships is a `profile-*` extra. If `face` ever
    appears inside one, the default install for that target gains a face model
    and the site's sentence becomes false the moment the build goes out — so
    this is the tripwire that must fire BEFORE the copy is wrong, not after."""
    import re
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[3] / "pyproject.toml")
    if not pyproject.exists():                    # installed wheel, not a checkout
        pytest.skip("pyproject.toml not on disk")
    text = pyproject.read_text()
    offenders = [
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if re.match(r"\s*profile-[a-z]+\s*=", line) and
        re.search(r"[\[,]\s*face\s*[,\]]", line.split("=", 1)[1])
    ]
    assert not offenders, (
        f"the `face` extra was added to deployment profile(s) {offenders} — a "
        f"default install for that target now ships a face model, so "
        f"landing/privacy.html and docs/gitbook/privacy.md are about to be "
        f"false. Change the copy in the same commit (HANDOFF step 3).")


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
# The auto-enrol copy, 2026-07-29. The site now says a specific, narrow, ugly
# thing instead of a broad comfortable falsehood, and every clause of it is
# pinned here so it cannot drift back in either direction — neither into
# "we don't do that" nor into a vaguer, safer-sounding overstatement.
# --------------------------------------------------------------------------

def test_a_fresh_install_has_face_recall_off_unconsented_and_not_enrolling():
    """"Recognition is off by default … auto-enrol is a further switch, off by
    default … a default install has no weights and declines every frame."

    Three separate defaults, asserted separately, because the copy claims each
    one on its own and a reader relies on all three."""
    from dreamlayer.ai_brain.server.store import BrainConfig

    cfg = BrainConfig()
    assert cfg.face_recognition is False, (
        "a fresh BrainConfig has face recognition ON — every public page says "
        "it is off until the wearer switches it on")
    assert cfg.face_auto_enrol is False, (
        "a fresh BrainConfig auto-enrols faces — the site says auto-enrol is a "
        "further switch that is off by default. This one stores biometric "
        "templates of people who never agreed; it must never ship on.")
    assert cfg.face_consent_version == "", (
        "a fresh install already counts as having accepted the biometric "
        "consent — the consent gate is the only thing standing between a "
        "default install and a bystander's template")


def test_the_consent_version_quoted_in_the_docs_is_the_one_the_code_requires():
    """docs/gitbook/privacy.md quotes the consent version by value. A version
    bump that does not reach the docs leaves the page describing terms nobody
    is being asked to accept."""
    from dreamlayer.ai_brain.server.face_live import CONSENT_VERSION

    doc = _REPO / "docs" / "gitbook" / "privacy.md"
    if not doc.exists():
        pytest.skip("docs not on disk")
    assert CONSENT_VERSION in doc.read_text(), (
        f"the consent version is now {CONSENT_VERSION!r}, which appears "
        f"nowhere in docs/gitbook/privacy.md — the Consent moments section "
        f"quotes it, so either update the page or stop quoting a version")


def test_the_consent_text_names_biometrics_bystanders_and_the_statutes():
    """The public copy tells the wearer the consent screen "names biometric
    templates, bystanders, BIPA and GDPR Article 9 outright". That is a claim
    about words the wearer will actually read, so it is checked against them."""
    from dreamlayer.ai_brain.server.face_live import CONSENT_TEXT

    low = CONSENT_TEXT.lower()
    for phrase in ("biometric", "cannot agree", "bipa", "article 9"):
        assert phrase in low, (
            f"the consent text no longer says {phrase!r}. The site promises "
            f"this text names biometric identifiers, the people who cannot "
            f"agree, and the statutes — do not quietly soften it.")


def test_erase_everything_reaches_the_stored_face_templates():
    """"Erase all memories deletes every stored template."

    A face template is the most personal thing the device holds and it lives in
    its own file, outside the memory DB — exactly the shape of store a wipe
    forgets. Behaviour is pinned in test_face_recognition.py; this is the
    claim-to-code link, and it fails if the call is dropped."""
    server = (_SRC / "ai_brain" / "server" / "server.py").read_text()
    assert "fr.forget_all()" in server, (
        "the Brain's erase no longer calls forget_all() on the face index — "
        "landing/privacy.html and docs/gitbook/privacy.md both promise that "
        "erasing everything deletes every stored face template")


def test_the_unnamed_face_sweep_has_a_live_caller():
    """"Auto-enrolled faces you never name are deleted by the Brain's retention
    sweep once they have not been seen for the warm window (90 days by
    default)."

    decisions/0001 is the reason this test exists: an uncalled sweep already
    made a retention promise false once. A stored biometric that ages out only
    in the docs is the same bug with worse consequences."""
    live = (_SRC / "ai_brain" / "server" / "retention_live.py").read_text()
    assert "sweep_unnamed(policy.warm_days)" in live, (
        "the Brain-side retention sweep no longer drops unnamed auto-enrolled "
        "faces on the warm window — the public copy says they age out on their "
        "own, so either restore the call or correct the copy")

    from dreamlayer.ai_brain.server import face_live
    assert face_live.UNNAMED_TTL_DAYS_DEFAULT == 90.0, (
        "the unnamed-face window moved off 90 days, which is the number the "
        "public pages print")


def test_face_matching_never_leaves_the_device():
    """"Never a public database: matching only ever happens against the index on
    your own hardware."

    The one half of the old promise that survived intact, and the half worth
    defending hardest. No named face-search vendor anywhere, and no network
    client in the three modules the recall path is made of."""
    vendors = re.compile(r"clearview|pimeyes|faceplusplus|face\+\+|rekognition",
                         re.I)
    hits = [str(p.relative_to(_SRC)) for p in _SRC.rglob("*.py")
            if "tests" not in p.parts and vendors.search(p.read_text())]
    assert not hits, (
        f"an external face-identification service is referenced in {hits} — "
        f"every public page promises no public database and no cloud face "
        f"search anywhere in the codebase")

    net = re.compile(r"\b(?:import\s+(?:requests|httpx|socket|urllib)"
                     r"|from\s+(?:requests|httpx|socket|urllib))")
    for rel in ("truth_lens/face_backends.py",
                "ai_brain/server/face_live.py",
                "social_lens/index.py"):
        body = (_SRC / rel).read_text()
        assert not net.search(body), (
            f"{rel} now imports a network client. The recall path — embed, "
            f"match, store — is promised to be entirely local; a face template "
            f"crossing the wire would falsify every privacy page at once.")


def test_the_retracted_face_promises_did_not_come_back():
    """The 2026-07-29 sweep retracted these exact sentences because the code
    stopped keeping them. This is the tripwire for a well-meaning revert: any
    of them reappearing means the site is ahead of the build again."""
    retracted = {
        "landing/privacy.html": [
            "cannot return an identity at all",
            "no setting that turns stranger recognition on",
            "keep a face database",
        ],
        "landing/index.html": [
            "never strangers, never a public database",
            "introductions only, never strangers",
            "no stranger identification",
            "no stranger lookup",
        ],
        "docs/gitbook/privacy.md": [
            "no stranger face lookup",
            "the first, second and fourth are absent from the codebase",
        ],
        "docs/gitbook/perception-memory.md": [
            "**no stranger lookup.**",
            "the index contains only contacts you enrolled",
            "the invariants are architectural, not policy",
        ],
        "docs/gitbook/guide/privacy.md": [
            "no stranger identification",
            "the capability simply does not exist in the product",
        ],
    }
    copy = _public_copy()
    back = [f"{rel}: {phrase!r}"
            for rel, phrases in retracted.items()
            for phrase in phrases
            if phrase in copy[rel]]
    assert not back, (
        f"retracted claim(s) are back in the public copy: {back}. Each was "
        f"falsified against committed code on 2026-07-29 — `face_auto_enrol` "
        f"persists a template for a face that matched nobody. Re-check "
        f"ai_brain/server/face_live.py before restoring any of them.")


def test_the_public_copy_discloses_auto_enrol():
    """The other direction, and the one that actually protects a bystander: a
    page may not describe face recall while omitting the switch that stores
    people who never agreed. Silence is how the old copy became false."""
    copy = _public_copy()
    silent = [rel for rel, body in copy.items() if "auto-enrol" not in body
              and "auto_enrol" not in body]
    assert not silent, (
        f"{silent} describe face recall without mentioning auto-enrol. The "
        f"shipped setting stores biometric templates of people who cannot "
        f"consent; a privacy page that omits it is false by omission.")


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
# "A retention lifecycle, and it runs … the Brain sweeps both windows when it
# starts and hourly while it is running" — docs/gitbook/perception-memory.md,
# and the privacy page's memory-lifecycle bullet.
#
# The sweep found this claim FALSE on 2026-07-27; the copy was corrected to say
# so, and this test pinned the un-wiring. It was fixed on 2026-07-28 and the
# copy is confident again, so what this pins is now the other direction: the
# claim is live, and the wiring it depends on has to stay wired.
# --------------------------------------------------------------------------

def test_the_retention_lifecycle_has_a_live_caller():
    """decisions/0001, closed. The docs say memory ages out on its own, so a
    boot must reach the sweep. Behaviour — rows actually disappearing — is
    pinned in test_brain_retention_boot.py; this is the claim-to-code link."""
    import ast
    server = (_SRC / "ai_brain" / "server" / "server.py").read_text()
    tree = ast.parse(server)
    brain = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "Brain")
    ctor = next(n for n in brain.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    init = ast.get_source_segment(server, ctor) or ""
    assert "self.sweep_retention()" in init, (
        "Brain.__init__ no longer sweeps retention — the docs promise memory "
        "ages out on its own, so either restore the call or correct the copy "
        "in docs/gitbook/perception-memory.md and privacy.md")

    live = (_SRC / "ai_brain" / "server" / "retention_live.py").read_text()
    assert "RetentionSweep(" in live, (
        "the Brain-side sweep no longer builds a RetentionSweep — re-check "
        "decisions/0001 before believing anything still expires")


def test_the_lifecycle_was_not_fixed_by_resurrecting_the_orchestrator():
    """The wrong fix, kept out by test. Giving `maybe_dream_tonight` a caller
    would stand a second MemoryDB and a reasoning graph up beside the Brain's
    own — what ear.py:4-10 records the team choosing twice not to do."""
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
        f"Orchestrator path was resurrected. The shipped Brain does not build "
        f"an Orchestrator; retention lives in ai_brain/server/retention_live.py.")
