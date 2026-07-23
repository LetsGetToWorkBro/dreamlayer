"""Presidio PII redactor real-path coverage (issue #452): the last of the
real-path series (chroma #396, sqlite-vec #428, lance #432, MiniLM embedder
#417/#448, voice #459). `memory/pii_presidio.py` previously had only its
regex-fallback path exercised, so the ML PII scrubbing that is the whole point
of the `privacy` extra (`presidio_analyzer`, the `pii_redaction` capability)
could silently regress and CI wouldn't notice.

Needs presidio (importorskip), so the whole file skips when the optional dep is
absent -- exactly like test_chroma_store_real.py (#396) and
test_embedder_local_real.py (#448) skip on their own optional deps. It also
needs a spaCy model AnalyzerEngine can load; when the model can't load (the
model isn't a pip dep) the real-path helpers skip cleanly with the
`python -m spacy download en_core_web_sm` hint -- mirroring how
test_embedder_local_real.py skips when the MiniLM weights can't load.

Non-vacuity (the #396 lesson): pii_presidio's real path has a silent
`except -> regex` degrade, so a naive test would pass vacuously if presidio
never ran. Every real-path test here spies on the module-level fallback regexes
(_EMAIL/_SSN/_CARD/_PHONE/_LONGNUM) and asserts they were NEVER called -- the
answer must come from presidio, not the regex -- mirroring how #396's spy
asserted the vector store's linear fallback was never called. The discriminators
are chosen so a degrade to the fallback is not merely detectable but FATAL to
the assertion: a CRYPTO (bitcoin) address and a US_DRIVER_LICENSE are values the
regex fallback provably cannot catch, so forcing the fallback branch leaves them
verbatim and turns the assert red (the mutation check the issue asks for);
TestRegexFallback below is the green-under-that-mutation counterpart.

Scope note (primary evidence over the issue text): pii_presidio._SAFE_ENTITIES
DELIBERATELY excludes PERSON and LOCATION -- the product remembers people by
name, so scrubbing "call <PERSON> about the <LOCATION> lease" would gut recall
(see the module's own comment). So the issue's "name in context" / "street
address" examples do NOT belong to redact(); they belong to the `stranger_
defense` text layer that rides the SAME AnalyzerEngine. That path is covered by
TestPersonGuardRealPath (the issue's bonus), which is where the name-in-context
assertion is honest. Likewise the issue's "SSN-shaped value" is a regex-fallback
catch, not a presidio one (presidio's US_SSN recognizer does not fire on a bare
nnn-nn-nnnn without stronger context), so it is not used as a real-path
discriminator here.
"""
import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("presidio_anonymizer")

from dreamlayer.memory import pii_presidio  # noqa: E402  (after importorskip)
from dreamlayer.object_lens import person_guard  # noqa: E402
from dreamlayer.object_lens.recognizer import _names_a_person  # noqa: E402

# A well-known checksum-valid bitcoin address and a driver-license-shaped id: the
# regex fallback (emails/phones/long digit runs) provably cannot catch either
# (no separator-delimited digit run), so they only get scrubbed on the real
# presidio path -- both are in _SAFE_ENTITIES (CRYPTO, US_DRIVER_LICENSE).
_BTC = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
_DL = "D1234567"


def _real_redactor():
    """A PiiRedactor with a genuinely built presidio analyzer, or a clean skip
    if the spaCy model can't load -- mirrors test_embedder_local_real._real_
    provider()."""
    r = pii_presidio.PiiRedactor()
    if not r.available or r._analyzer is None:
        pytest.skip(
            "presidio analyzer/spaCy model could not be loaded -- run "
            "`python -m spacy download en_core_web_sm` (or install "
            "en_core_web_lg for presidio's default engine)")
    return r


def _fallback_spy(monkeypatch):
    """Record any silent degrade to the regex fallback. On the presidio path
    redact() returns before it touches these module-level patterns, so an empty
    list proves presidio itself produced the answer (the #396 non-vacuity
    lesson, mirroring test_chroma_store_real._fallback_spy)."""
    calls = []

    class _Spy:
        def __init__(self, real):
            self._real = real

        def sub(self, repl, text):
            calls.append(repl)
            return self._real.sub(repl, text)

    for name in ("_EMAIL", "_SSN", "_CARD", "_PHONE", "_LONGNUM"):
        monkeypatch.setattr(pii_presidio, name, _Spy(getattr(pii_presidio, name)))
    return calls


@pytest.mark.real_model
class TestRealPath:
    def test_crypto_address_only_presidio_can_scrub(self, monkeypatch):
        # The sharpest discriminator: the regex fallback leaves a bitcoin address
        # verbatim, so a degrade to it is FATAL here -- the address survives and
        # this assert goes red (the mutation check #452 asks for).
        r = _real_redactor()
        degraded = _fallback_spy(monkeypatch)
        out = r.redact(f"send the deposit to {_BTC} tonight")
        assert degraded == []                       # real presidio path answered
        assert _BTC not in out                       # the address is actually gone
        assert "<CRYPTO>" in out                      # presidio's placeholder

    def test_driver_license_only_presidio_can_scrub(self, monkeypatch):
        # A second alphanumeric id the separator-delimited regex cannot catch.
        r = _real_redactor()
        degraded = _fallback_spy(monkeypatch)
        out = r.redact(f"my driver's license is {_DL} in the glovebox")
        assert degraded == []
        assert _DL not in out
        assert "<US_DRIVER_LICENSE>" in out

    def test_presidio_placeholder_tokens_not_the_regex_ones(self, monkeypatch):
        # For identifiers the regex ALSO catches (email, phone), the real path is
        # still distinguishable: presidio's anonymizer emits <EMAIL_ADDRESS> /
        # <PHONE_NUMBER>, the fallback emits <EMAIL> / <PHONE>. Seeing presidio's
        # tokens (and none of the fallback's) proves presidio, not the regex,
        # produced the answer -- independently of the spy.
        r = _real_redactor()
        degraded = _fallback_spy(monkeypatch)
        out = r.redact("reach me at maya@example.com or call +1 415 555 0132")
        assert degraded == []
        assert "maya@example.com" not in out and "415 555 0132" not in out
        assert "<EMAIL_ADDRESS>" in out and "<PHONE_NUMBER>" in out
        assert "<EMAIL>" not in out and "<PHONE>" not in out   # not the fallback

    def test_redact_for_write_uses_presidio_and_honors_the_veil(self, monkeypatch):
        # The public write-path entry: it scrubs via the same real presidio path,
        # and returns None when the capture veil is down (never a scrubbed string
        # that could still leak on a closed veil).
        r = _real_redactor()
        degraded = _fallback_spy(monkeypatch)
        out = r.redact_for_write(f"wallet {_BTC}")
        assert degraded == []
        assert out is not None and _BTC not in out and "<CRYPTO>" in out

        class _VeilDown:
            def allow_capture(self):
                return False

        assert r.redact_for_write(f"wallet {_BTC}", privacy=_VeilDown()) is None


@pytest.mark.real_model
class TestPersonGuardRealPath:
    """The issue's bonus: object_lens/person_guard.label_is_a_person (the
    stranger_defense text layer) rides the SAME AnalyzerEngine, so a real-path
    test locks it down too."""

    def _require_analyzer(self):
        person_guard.reset_caches()
        if person_guard._get_analyzer() is None:
            pytest.skip(
                "presidio analyzer/spaCy model could not be loaded -- run "
                "`python -m spacy download en_core_web_sm`")

    def test_name_in_context_only_presidio_catches(self):
        # "call Maya about the lease": the deterministic name-shape guard
        # (_names_a_person) misses a lone given name mid-sentence, so a True here
        # can ONLY come from presidio's PERSON NER on the real engine. Asserting
        # the deterministic layer is False first proves it is presidio doing the
        # work, not the shape rule (non-vacuity), and label_is_a_person returns
        # False whenever the analyzer is absent -- so a degrade turns this red.
        self._require_analyzer()
        label = "call Maya about the lease"
        assert _names_a_person(label) is False        # deterministic layer misses it
        assert person_guard.label_is_a_person(label) is True   # presidio catches it

    def test_plain_object_label_is_not_a_person(self):
        # The other side of the boundary: an ordinary object label must NOT defer
        # -- guards against a NER that over-fires and gluts every look.
        self._require_analyzer()
        assert person_guard.label_is_a_person("a wooden chair on the porch") is False


class TestRegexFallback:
    def test_forced_unavailable_degrades_to_regex_without_raising(self, monkeypatch):
        # Force the "presidio not installed" branch even though it IS installed
        # (it must be, to pass this file's importorskip). Proves the fallback
        # regex path works on its own AND is the green-under-mutation counterpart
        # to TestRealPath: the crypto address the real path scrubs SURVIVES here,
        # because the regex fallback genuinely cannot catch it -- so forcing the
        # real path to degrade reddens TestRealPath while this stays green (#452).
        monkeypatch.setattr(pii_presidio, "_HAS_PRESIDIO", False)
        r = pii_presidio.PiiRedactor()
        assert r._analyzer is None                    # regex-only redactor
        out = r.redact(f"send the deposit to {_BTC} tonight")   # must not raise
        assert _BTC in out                            # regex CANNOT scrub crypto
        # the separator-delimited identifiers it CAN catch still go, with the
        # fallback's own <EMAIL> token (never presidio's <EMAIL_ADDRESS>)
        out2 = r.redact("reach me at maya@example.com")
        assert "maya@example.com" not in out2 and "<EMAIL>" in out2
