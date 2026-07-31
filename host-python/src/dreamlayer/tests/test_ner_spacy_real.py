"""test_ner_spacy_real.py — the Social Lens NER and the commitment parser
against the REAL spaCy pipeline (issue #454).

`social_lens/ner_spacy.py` and `orchestrator/commitment_nlp.py` both lazy-import
spaCy (the `nlp` capability, `intelligence` extra) and both degrade to a regex
extractor when it is absent. spaCy is not in the dev extras and the pipeline it
needs — `en_core_web_sm`, ~12 MB — is not a pip dependency at all. So the only
two tests either module had, `test_commitment_nlp_fallback` and
`test_ner_and_diarize_fallback` in test_integration_seams_pr2.py, exercise the
regex fallback — they say so in their names. The branch the capability table
advertises — "baseline pulls names/promises with regex that breaks on real
sentences; this parses them properly" — had no test at all.

This is the follow-up in the real-path series (#396/#428/#432/#417) and keeps
their shape: `importorskip` for the optional package, a clean skip with the
remedy in the reason if the model itself cannot load (as in
test_embedder_local_real.py), and every real-path test spying on the fallback so
a silent `except -> regex` degrade fails instead of passing vacuously (#396).

Marked `real_model` at module level, the way test_pii_presidio_real.py is: the
`en_core_web_sm` download is exactly the "needs a real backend installed" case
the marker gates, and real-models.yml already installs `spacy>=3,<4` and runs
`python -m spacy download en_core_web_sm` for the presidio suite, so this file
needs no workflow change to run there. That job FAILS on a skip, so "spaCy
wasn't installed" cannot read as green.

Every real-path assertion is DIFFERENTIAL: it names what the regex fallback
produces on the same input, so the test measures what spaCy buys rather than
just that spaCy ran. The last test drives the same four inputs through the regex
path with the pipeline dropped, so the values every assert above it must never
accept are written down and executed rather than described.
"""
from __future__ import annotations

import pytest

pytest.importorskip("spacy")

import spacy  # noqa: E402  (after importorskip)

from dreamlayer.orchestrator.commitment_nlp import CommitmentNLP  # noqa: E402
from dreamlayer.social_lens.ner_spacy import SpacyNER  # noqa: E402

pytestmark = pytest.mark.real_model

# Bound at import, BEFORE any monkeypatch: the tests below compare spaCy's answer
# against what the fallback would have said, and they must call the genuine
# fallback to do it — not the spy that the same tests install to prove the
# fallback never ran.
_REAL_HEURISTIC = SpacyNER._heuristic          # staticmethod(text) -> list[str]
_REAL_REGEX = CommitmentNLP._regex_extract     # (self, text) -> Commitment | None

_MODEL_MISSING = (
    "en_core_web_sm could not be loaded — it is a ~12 MB spaCy pipeline, not a "
    "pip dependency of the `intelligence` extra. Run "
    "`python -m spacy download en_core_web_sm` to run this file.")

# --- the discriminating inputs, and why each one discriminates ----------------
# LOWERCASE_NAME: the heuristic is `[A-Z][a-z]+`, so a name typed in lowercase is
# invisible to it — it answers []. spaCy's NER reads context, not capitalisation.
LOWERCASE_NAME = "I met sarah chen at the cafe"
# TWO_TOKEN_NAME: one PERSON and one ORG in a sentence that also carries a
# capitalised weekday. The heuristic returns five capitalised fragments and calls
# all of them people.
TWO_TOKEN_NAME = "Sarah Chen from Overpass Studio said the lease is due Friday"
# PROMISE: the regex extractor skips word 0 by design ("usually a verb like
# Send/Remind"), which decapitates a sentence that opens on the subject's given
# name — it answers "Chen". Its `action` is the whole sentence back.
PROMISE = "Sarah Chen promised to send the lease next week"
# LOWERCASE_PROMISE: lowercase subject again, this time through the commitment
# parser, where the regex extractor finds no subject at all.
LOWERCASE_PROMISE = "i told sarah chen i would send the deck tomorrow"


@pytest.fixture(scope="module")
def ner() -> SpacyNER:
    """A SpacyNER with a genuinely loaded pipeline behind it."""
    n = SpacyNER()
    assert n.available, (
        "spacy imported but SpacyNER.available is False — the module-level probe "
        "and the class attribute disagree")
    if n._nlp is None:
        pytest.skip(_MODEL_MISSING)
    return n


@pytest.fixture(scope="module")
def commitments() -> CommitmentNLP:
    """A CommitmentNLP with a genuinely loaded pipeline behind it."""
    c = CommitmentNLP()
    assert c.available, (
        "spacy imported but CommitmentNLP.available is False — the module-level "
        "probe and the class attribute disagree")
    if c._nlp is None:
        pytest.skip(_MODEL_MISSING)
    return c


@pytest.fixture
def fallbacks(monkeypatch) -> list[tuple[str, str]]:
    """Spy on BOTH regex fallbacks and record every call.

    `SpacyNER.people` and `CommitmentNLP.extract` each wrap their spaCy branch in
    `try/except -> log.warning -> fallback`, so a broken pipeline still returns an
    answer. That is right for production and fatal for a test: without this spy a
    real-path assertion the fallback happens to satisfy would pass green while the
    real path never ran. Every test below asserts this list is empty, so any
    silent degrade — a model that failed to load, a parse that raised, a future
    refactor that routes through the regex — turns the test red instead.
    """
    calls: list[tuple[str, str]] = []

    def heuristic_spy(text: str) -> list[str]:
        calls.append(("SpacyNER._heuristic", text))
        return _REAL_HEURISTIC(text)

    def regex_spy(self, text):
        calls.append(("CommitmentNLP._regex_extract", text))
        return _REAL_REGEX(self, text)

    monkeypatch.setattr(SpacyNER, "_heuristic", staticmethod(heuristic_spy))
    monkeypatch.setattr(CommitmentNLP, "_regex_extract", regex_spy)
    return calls


# --------------------------------------------------------------------------
# The pipeline is real
# --------------------------------------------------------------------------

def test_the_pipeline_is_a_live_spacy_model(ner, commitments):
    """The one assertion that makes everything below meaningful: `_nlp` is a
    loaded spaCy Language with the two components this file leans on — the NER
    that finds PERSON/ORG and the parser that supplies the ROOT."""
    for obj in (ner, commitments):
        assert isinstance(obj._nlp, spacy.language.Language)
        assert obj._nlp.lang == "en"
        assert "ner" in obj._nlp.pipe_names
    # `_spacy_extract` reads `t.dep_ == "ROOT"`, which only a parser assigns
    assert "parser" in commitments._nlp.pipe_names


# --------------------------------------------------------------------------
# social_lens/ner_spacy.py — what the NER buys over `_heuristic`
# --------------------------------------------------------------------------

def test_a_lowercase_name_the_heuristic_cannot_see(ner, fallbacks):
    """`_heuristic` matches `\\b([A-Z][a-z]+)\\b`, so a name the wearer typed (or
    an ASR transcript produced) in lowercase does not exist for it. The evidence
    is asserted, not assumed: the heuristic's own output on this exact string is
    the empty list, which is also why this test cannot pass through the
    fallback — [] fails the assert."""
    assert _REAL_HEURISTIC(LOWERCASE_NAME) == [], (
        "the heuristic now sees a lowercase name — this input no longer "
        "discriminates and the test needs a new one")
    assert ner.people(LOWERCASE_NAME) == ["sarah chen"]
    assert fallbacks == []                     # the real NER answered


def test_a_two_token_name_stays_one_person(ner, fallbacks):
    """spaCy returns the PERSON as one span. The heuristic shreds the sentence
    into every capitalised token, so the same name arrives as two separate
    "people" — plus the company and the weekday, which are not people at all."""
    assert _REAL_HEURISTIC(TWO_TOKEN_NAME) == [
        "Sarah", "Chen", "Overpass", "Studio", "Friday"]
    assert ner.people(TWO_TOKEN_NAME) == ["Sarah Chen"]
    assert fallbacks == []


def test_the_weekday_and_the_company_are_not_people(ner, fallbacks):
    """The heuristic's false positives are the expensive half: an introduction
    or dossier built from it gets a person named Friday and a person named
    Studio. spaCy's PERSON label excludes both."""
    people = ner.people(TWO_TOKEN_NAME)
    assert fallbacks == []
    assert "Friday" not in people and "Studio" not in people
    # and the heuristic really does hand both of them over as people
    assert {"Friday", "Studio"} <= set(_REAL_HEURISTIC(TWO_TOKEN_NAME))


def test_the_org_the_regex_path_has_no_concept_of(ner, fallbacks):
    """`orgs()` has no heuristic at all — every path out of it that is not the
    NER returns a bare `[]`. So a non-empty result here is only reachable
    through the real NER,
    and the ORG span is one the token-level heuristic could not have assembled
    even in principle."""
    assert ner.orgs(TWO_TOKEN_NAME) == ["Overpass Studio"]
    assert fallbacks == []
    assert "Overpass Studio" not in _REAL_HEURISTIC(TWO_TOKEN_NAME)


# --------------------------------------------------------------------------
# orchestrator/commitment_nlp.py — what the dependency parse buys over the regex
# --------------------------------------------------------------------------

def test_the_full_subject_survives_a_sentence_that_opens_on_it(commitments, fallbacks):
    """`_regex_extract` skips word 0 on the theory it is a verb ("Send"/"Remind"),
    so a sentence starting with the subject's given name loses it: the regex
    answers "Chen". The NER reads the whole PERSON span."""
    assert _REAL_REGEX(commitments, PROMISE).subject == "Chen"
    c = commitments.extract(PROMISE)
    assert fallbacks == []
    assert c is not None and c.subject == "Sarah Chen"


def test_the_action_is_the_root_lemma_not_the_whole_sentence(commitments, fallbacks):
    """`CommitmentDriftEngine.nudge()` wants structure. The regex extractor's
    `action` is the input string echoed back — no structure at all — while the
    dependency parse names the ROOT verb and lemmatises it."""
    assert _REAL_REGEX(commitments, PROMISE).action == PROMISE
    c = commitments.extract(PROMISE)
    assert fallbacks == []
    assert c is not None and c.action == "promise"
    assert c.deadline == "next week"


def test_a_lowercase_subject_the_regex_extractor_misses_entirely(commitments, fallbacks):
    """Same lowercase blind spot as the NER, one layer up: the regex extractor
    returns `subject=None`, i.e. a commitment with nobody attached to it."""
    assert _REAL_REGEX(commitments, LOWERCASE_PROMISE).subject is None
    c = commitments.extract(LOWERCASE_PROMISE)
    assert fallbacks == []
    assert c is not None and c.subject == "sarah chen"
    assert c.deadline == "tomorrow"


# --------------------------------------------------------------------------
# The fallback still works — and the spy above really does catch it
# --------------------------------------------------------------------------

def test_forcing_the_fallback_is_visible_to_the_spy(ner, commitments, fallbacks):
    """The mutation check, executed rather than described. Drop the pipeline (the
    state of every box without the model) and the same four inputs come back with
    the regex answers the tests above reject — and the spy records the calls, so
    none of those tests could have gone green this way."""
    blind = SpacyNER()
    blind._nlp = None
    deaf = CommitmentNLP()
    deaf._nlp = None

    assert blind.people(LOWERCASE_NAME) == []
    assert blind.people(TWO_TOKEN_NAME) == [
        "Sarah", "Chen", "Overpass", "Studio", "Friday"]
    assert blind.orgs(TWO_TOKEN_NAME) == []
    assert deaf.extract(PROMISE).subject == "Chen"
    assert deaf.extract(LOWERCASE_PROMISE).subject is None

    assert [name for name, _ in fallbacks] == [
        "SpacyNER._heuristic"] * 2 + ["CommitmentNLP._regex_extract"] * 2
