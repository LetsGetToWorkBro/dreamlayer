"""Who is speaking, when nobody knows who they are.

`diarization` answers a different question from `speaker_id`. That one asks
*who is this* and matches a voiceprint against people the wearer enrolled; this
one asks *how many voices are in this segment and when did they change*, and
answers with `spk0`/`spk1` — tags that mean nothing outside the stream that
made them, are matched against nothing, and are never persisted.

`DiartDiarizer` has existed with a working single-speaker fallback and no
caller. The consequence was quiet and specific: an unidentified conversation
folded into the ledger with every turn attributed to the same nobody, so two
people talking read as one person contradicting themselves — which is exactly
what the Candor and Veritas paths key on.
"""
from __future__ import annotations

import pytest

from dreamlayer.orchestrator.capture import CapturePipeline


class FakeDiarizer:
    """The `turns()` contract `DiartDiarizer` promises."""

    def __init__(self, turns=None, boom=False):
        self._turns, self.boom = turns, boom
        self.calls = 0

    def turns(self, audio):
        self.calls += 1
        if self.boom:
            raise RuntimeError("diart fell over")
        return self._turns


class FakeOrch:
    def __init__(self):
        self.captions: list = []
        self.health = None

    def hear(self, text):
        return None

    def ingest_caption(self, text, speaker=""):
        self.captions.append((text, speaker))


def _pipe(**kw):
    return CapturePipeline(FakeOrch(), **kw)


TWO = [{"speaker": "spk0", "start": 0.0, "end": 1.0},
       {"speaker": "spk1", "start": 1.0, "end": 3.5}]
ONE = [{"speaker": "spk0", "start": 0.0, "end": None}]


class TestTheLabel:
    def test_two_voices_get_the_one_that_held_the_segment(self):
        p = _pipe(diarizer=FakeDiarizer(TWO))
        assert p._diarized_label(b"audio") == "spk1"      # 2.5s beats 1.0s

    def test_one_voice_stays_unattributed(self):
        # The fallback answers exactly this for everything, and "" is what the
        # whole downstream already reads as unattributed. `spk0` on a solo
        # utterance would put a pseudo-speaker in the ledger where there is
        # honestly nobody.
        assert _pipe(diarizer=FakeDiarizer(ONE))._diarized_label(b"a") == ""

    def test_no_diarizer_is_no_label(self):
        assert _pipe()._diarized_label(b"a") == ""

    def test_no_turns_at_all_is_no_label(self):
        assert _pipe(diarizer=FakeDiarizer([]))._diarized_label(b"a") == ""
        assert _pipe(diarizer=FakeDiarizer(None))._diarized_label(b"a") == ""

    def test_a_diarizer_that_explodes_never_breaks_capture(self):
        p = _pipe(diarizer=FakeDiarizer(boom=True))
        assert p._diarized_label(b"a") == ""

    def test_malformed_spans_do_not_raise(self):
        bad = [{"speaker": "spk0", "start": "x", "end": None},
               {"speaker": "spk1", "start": 0.0, "end": 2.0}]
        assert _pipe(diarizer=FakeDiarizer(bad))._diarized_label(b"a") == "spk1"

    def test_a_turn_with_no_speaker_is_ignored(self):
        rows = [{"start": 0.0, "end": 9.0}, {"speaker": "spk1",
                                             "start": 0.0, "end": 1.0}]
        # Only one NAMED voice → not a turn-take.
        assert _pipe(diarizer=FakeDiarizer(rows))._diarized_label(b"a") == ""

    def test_it_counts_the_voices_it_heard(self):
        p = _pipe(diarizer=FakeDiarizer(TWO))
        p._diarized_label(b"a")
        assert p.last_voices == 2
        p2 = _pipe(diarizer=FakeDiarizer(ONE))
        p2._diarized_label(b"a")
        assert p2.last_voices == 1


class TestANameAlwaysWins:
    """Identity beats an anonymous tag, and the diarizer is not even asked."""

    class _Speaker:
        def embed(self, seg):
            return [0.1, 0.2]

    def _identified(self, name, diarizer):
        p = _pipe(speaker=self._Speaker(), speaker_resolver=lambda e: name,
                  enrolled_speakers=["Maya"], diarizer=diarizer)
        p.asr = type("A", (), {"transcribe": staticmethod(lambda s: "hello")})()
        p._seg = [b"audio"]          # a pending segment for _endpoint to close
        return p

    def test_a_resolved_name_is_kept(self):
        d = FakeDiarizer(TWO)
        p = self._identified("Maya", d)
        p._endpoint(0.0)
        assert p.orch.captions == [("hello", "Maya")]
        assert d.calls == 0, "the diarizer was consulted despite a known name"

    def test_an_unresolved_speaker_falls_through_to_the_tag(self):
        d = FakeDiarizer(TWO)
        p = self._identified("", d)
        p._endpoint(0.0)
        assert p.orch.captions == [("hello", "spk1")]
        assert d.calls == 1

    def test_with_no_diarizer_it_is_unattributed_exactly_as_before(self):
        p = self._identified("", None)
        p._endpoint(0.0)
        assert p.orch.captions == [("hello", "")]


class TestTheEarBuildsItOnce:
    def test_the_seam_is_held_not_rebuilt(self, monkeypatch):
        # diart clusters WITHIN a stream, so a fresh diarizer per segment would
        # restart the labels every utterance and `spk0` would be a different
        # person each time.
        import dreamlayer.ai_brain.server.ear as ear_mod
        built = []

        class _D:
            _pipeline = object()

            def __init__(self):
                built.append(1)

        import dreamlayer.social_lens.diarize_diart as dd
        monkeypatch.setattr(dd, "DiartDiarizer", _D)
        host = ear_mod.EarHost.__new__(ear_mod.EarHost)
        host._diar = None
        assert host._diarizer() is not None
        assert host._diarizer() is not None
        assert len(built) == 1

    def test_a_fallback_only_diarizer_is_not_held_at_all(self, monkeypatch):
        # `_pipeline is None` means diart is absent and `turns()` can only ever
        # answer its own single-speaker null — a seam that returns nothing but
        # its fallback is a claim, not a capability, so it is not attached.
        import dreamlayer.ai_brain.server.ear as ear_mod
        import dreamlayer.social_lens.diarize_diart as dd

        class _D:
            _pipeline = None
        monkeypatch.setattr(dd, "DiartDiarizer", _D)
        host = ear_mod.EarHost.__new__(ear_mod.EarHost)
        host._diar = None
        assert host._diarizer() is None

    def test_an_import_failure_is_not_fatal(self, monkeypatch):
        import dreamlayer.ai_brain.server.ear as ear_mod
        import dreamlayer.social_lens.diarize_diart as dd

        def _boom():
            raise RuntimeError("no diart")
        monkeypatch.setattr(dd, "DiartDiarizer", _boom)
        host = ear_mod.EarHost.__new__(ear_mod.EarHost)
        host._diar = None
        assert host._diarizer() is None


class TestTheRealAdapter:
    """Against `DiartDiarizer` itself — the shape the pipeline speaks to."""

    def test_the_fallback_is_a_single_speaker_turn(self):
        from dreamlayer.social_lens.diarize_diart import DiartDiarizer
        d = DiartDiarizer()
        if d._pipeline is not None:              # pragma: no cover — diart here
            pytest.skip("diart installed; the fallback is not what runs")
        assert d.turns(b"audio") == [{"speaker": "spk0", "start": 0.0,
                                      "end": None}]

    def test_the_fallback_produces_no_label_through_the_pipeline(self):
        # The floor, stated end to end: with diart absent nothing changes —
        # the capture path attributes exactly as much as it did before.
        from dreamlayer.social_lens.diarize_diart import DiartDiarizer
        d = DiartDiarizer()
        if d._pipeline is not None:              # pragma: no cover
            pytest.skip("diart installed")
        assert _pipe(diarizer=d)._diarized_label(b"audio") == ""


class TestTheCapabilityIsProven:
    def test_one_voice_never_promotes_it(self):
        p = _pipe(diarizer=FakeDiarizer(ONE))
        p._diarized_label(b"a")
        assert p.last_voices == 1                # the fallback's own answer

    def test_a_split_segment_is_the_proof(self):
        p = _pipe(diarizer=FakeDiarizer(TWO))
        p._diarized_label(b"a")
        assert p.last_voices > 1

    def test_the_report_reads_the_live_pipeline(self):
        import inspect
        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert "DL_WIRED_DIARIZATION" in src
        assert "last_voices" in src, (
            "the promotion must follow a genuinely split segment, not the "
            "wheel being importable")
