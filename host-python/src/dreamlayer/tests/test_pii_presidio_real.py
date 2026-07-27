"""test_pii_presidio_real.py — the PII redactor against the REAL presidio engine.

Everything else that touches `pii_presidio` runs the regex fallback: presidio is
an optional dep (`privacy` extra) and it needs a spaCy *model* on top, so the
ordinary suite has no engine to exercise. That left the presidio branch of
`PiiRedactor.redact` — the one that runs on the mac profile, the one the privacy
policy's "structured meaning, never raw" claim rests on — with zero coverage
anywhere in CI (issue #528).

These tests are `real_model`-marked, so they are deselected by default and run in
the `real-models` job, which now installs `.[privacy]` and downloads
`en_core_web_sm`. That job FAILS on a skip, so "presidio wasn't installed" can no
longer read as green.

`importorskip` is the gate for a dev box without the extra. Once past it these
tests ASSERT rather than skip: presidio present but the analyzer still None means
the spaCy model is missing, which is a broken install, not an absent capability,
and the difference is exactly what this file exists to tell you.
"""
from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")

from dreamlayer.memory import pii_presidio as P   # noqa: E402  (after importorskip)

pytestmark = pytest.mark.real_model


@pytest.fixture(scope="module")
def real() -> P.PiiRedactor:
    """A redactor with a live presidio analyzer behind it."""
    r = P.PiiRedactor()
    assert r.available, (
        "presidio imported but PiiRedactor.available is False — the module-level "
        "probe and the instance disagree")
    assert r._analyzer is not None, (
        "presidio is installed but nlp_setup.analyzer_engine() returned None — "
        "the en_core_web_sm spaCy model is missing, so every redaction silently "
        "fell back to regex. Run `python -m spacy download en_core_web_sm`.")
    assert r._anon is not None, "analyzer built but the anonymizer did not"
    return r


@pytest.fixture(scope="module")
def regex_only() -> P.PiiRedactor:
    """The same class with the engine removed — the four profiles that ship
    without the `privacy` extra, for differential comparison."""
    r = P.PiiRedactor()
    r._analyzer = None
    return r


# --------------------------------------------------------------------------
# The engine is real
# --------------------------------------------------------------------------

def test_the_analyzer_is_a_live_presidio_engine(real):
    """The single assertion that would have caught #528. Everything below is
    only meaningful if this holds."""
    assert type(real._analyzer).__name__ == "AnalyzerEngine"
    supported = set(real._analyzer.get_supported_entities(language="en"))
    # the entity set the redactor actually asks for must be recognisable
    missing = [e for e in P._SAFE_ENTITIES if e not in supported]
    assert not missing, f"_SAFE_ENTITIES asks for entities presidio can't see: {missing}"


# --------------------------------------------------------------------------
# What presidio buys over the regex sweep
# --------------------------------------------------------------------------

def test_presidio_strips_an_iban_the_regex_sweep_cannot(real, regex_only):
    """The module comment claims 'deeper alphanumeric IDs (IBAN, crypto,
    passport, license) still need presidio'. This is that claim, executed."""
    text = "wire the deposit to GB33BUKB20201555555555 tomorrow"
    assert "GB33BUKB20201555555555" not in real.redact(text)
    assert "IBAN_CODE" in real.redact(text)
    # and the fallback genuinely cannot — otherwise the claim is decoration
    assert "GB33BUKB20201555555555" in regex_only.redact(text)


def test_presidio_labels_a_passport_the_regex_sweep_only_blurs(real, regex_only):
    text = "passport 340020013 is in the drawer"
    out = real.redact(text)
    assert "340020013" not in out and "US_PASSPORT" in out
    # the fallback still redacts it, just as a mislabelled phone number — the
    # number does not survive either way, which is the part that matters
    assert "340020013" not in regex_only.redact(text)


# --------------------------------------------------------------------------
# What presidio must NOT do — the product contract
# --------------------------------------------------------------------------

def test_the_real_engine_keeps_names_places_and_dates(real):
    """`_SAFE_ENTITIES` deliberately omits PERSON, LOCATION, DATE_TIME and NRP:
    'the product's whole purpose is remembering people'. Presidio recognises all
    four, so this is the entity scoping doing real work, not a coincidence."""
    text = "Call Sarah Chen about the Oakland lease on 2026-08-14"
    assert real.redact(text) == text

    # prove the omission is load-bearing: unscoped, presidio does scrub them
    unscoped = real._analyzer.analyze(text=text, language="en")
    found = {r.entity_type for r in unscoped}
    assert found & {"PERSON", "LOCATION", "DATE_TIME"}, (
        f"presidio saw none of PERSON/LOCATION/DATE_TIME in {text!r} "
        f"(saw {found}) — this test is no longer proving the scoping matters")


def test_iso_dates_survive_both_backends_identically(real, regex_only):
    """The `_ISO_RUN` shield exists to 'restore parity between the two backends'
    after the fallback ate every date. Parity, verified against the real engine
    rather than asserted in a comment."""
    for text in ("dentist on 2026-08-14",
                 "meet between 2024-01-01 and 2026-12-31",
                 "renewed 2026-12-31, invoiced 2027-01-01"):
        assert real.redact(text) == text
        assert regex_only.redact(text) == text


# --------------------------------------------------------------------------
# Presidio must never redact LESS than the fallback
# --------------------------------------------------------------------------

def test_an_ssn_presidio_rejects_is_still_stripped(real):
    """Presidio's US_SSN recogniser rejects digit patterns it judges impossible,
    so `123-45-6789` came back VERBATIM with the `privacy` extra installed and as
    `<SSN>` without it — installing an optional dependency made the redactor
    scrub less. `redact` now runs the regex sweep after presidio, so the two
    compose into the union. Revert that and this fails."""
    out = real.redact("SSN 123-45-6789 on the intake form")
    assert "123-45-6789" not in out, (
        "an SSN survived the redactor on a presidio-equipped box")


def test_a_pattern_presidio_accepts_keeps_its_precise_label(real):
    """The union must not cost the better label: where presidio does fire, its
    entity name survives the second pass."""
    out = real.redact("SSN 457-55-5462 on the intake form")
    assert "457-55-5462" not in out and "US_SSN" in out


def test_the_regex_sweep_finds_nothing_left_to_chew_on(real):
    """The second pass runs over presidio's OUTPUT, so it must be idempotent on
    placeholders — `<US_SSN>` holds no digits and must not become `<US_NUM>` or
    similar nonsense."""
    once = real.redact("card 4111 1111 1111 1111 and ssn 457-55-5462")
    assert once == real.redact(once), f"redaction is not idempotent: {once!r}"


@pytest.mark.parametrize("text,secret", [
    ("email me at sarah.chen@example.com", "sarah.chen@example.com"),
    ("call +1 415 555 0132 tonight", "415 555 0132"),
    ("card 4111 1111 1111 1111 expires soon", "4111 1111 1111 1111"),
])
def test_the_ordinary_identifiers_still_go(real, text, secret):
    assert secret not in real.redact(text)


# --------------------------------------------------------------------------
# The other presidio consumer: the stranger defence
# --------------------------------------------------------------------------

@pytest.fixture
def guard():
    """`person_guard` on its REAL analyzer. Every other test of this module
    injects a fake one, so the wiring nlp_setup -> engine -> label_is_a_person
    had never actually run."""
    from dreamlayer.object_lens import person_guard
    person_guard._analyzer_override = None
    person_guard.reset_caches()
    assert person_guard._get_analyzer() is not None, (
        "person_guard could not build a presidio analyzer — the text layer of "
        "the stranger defence is silently off")
    yield person_guard
    person_guard.reset_caches()


def test_the_lone_given_name_the_docstring_promises_is_caught(guard):
    """The module advertises catching 'a lone given name like "Maya"'. Against
    the real engine the bare label scored NOTHING — the promise was only ever
    kept by the fake analyzer the other tests inject. The label is now analysed
    inside a carrier sentence; revert that and this fails."""
    assert guard.label_is_a_person("Maya") is True
    for name in ("Diego", "Aisha", "Tom", "Sarah Chen", "Maya Patel"):
        assert guard.label_is_a_person(name) is True, f"{name!r} not caught"


def test_ordinary_object_labels_do_not_defer(guard):
    """A false positive here costs the wearer a named object, so it is not a
    privacy failure — but it is still wrong, and the bare-label form had four of
    them across 85 labels ('mouse' and 'napkin' among them)."""
    for label in ("wooden chair", "laptop", "houseplant", "keyboard",
                  "mouse", "napkin", "backpack", "traffic light", "bicycle"):
        assert guard.label_is_a_person(label) is False, f"{label!r} deferred"


def test_the_carrier_sentence_cannot_vote_on_its_own(guard):
    """The frame wraps the label in real words; a PERSON found in the CARRIER
    rather than the label must not count. An empty-ish label is the direct
    probe — 'I met .' has no label span to hit."""
    assert guard.label_is_a_person("   ") is False
    assert guard.label_is_a_person("") is False


def test_mug_is_the_known_false_positive(guard):
    """Documented, not hidden: 'mug' is a real surname and en_core_web_sm tags
    it PERSON at 0.85 in any frame we tried. It survives here because this layer
    can only ADD a deferral — the cost is that one look at a mug declines to name
    it, never that a stranger gets named. If a future model or frame fixes it,
    this test fails and should simply be deleted."""
    assert guard.label_is_a_person("mug") is True
