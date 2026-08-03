"""test_nlp_live.py — the parse behind commitments, on the Brain's ingest path.

`nlp` is the only impact-5 entry in the catalogue and it sat under "unreachable
BY DESIGN" because its seam string named `orchestrator/`. That was a path rule,
not a judgement. `CommitmentNLP` was complete, tested and correct; its only
caller was the Orchestrator the shipped Brain never builds (`decisions/0001`).

The bar here is the one every re-hosting in this tree has had to clear: not "the
parser imports", not "the pass ran", but **a field the wearer can see that the
regex had left empty**. `sharpen` runs on every commitment row whether or not
spaCy is installed, so "it was called" proves nothing at all — and because the
extractor honours the floor, on a sentence the regex already handles the parser
correctly adds nothing. That is the fallback working, not the capability
driving, and the tests below are built to tell those two apart.
"""
from __future__ import annotations

import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.nlp_live import COMMITMENT_KINDS, NLPLive, nlp_live
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.pipelines.ingest import extract_events


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


def _brain(tmp_path) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok").save(cfg)
    return Brain(cfg)


#: Sentences whose deadline `pipelines.ingest._DUE_HINTS` misses and
#: `CommitmentNLP` finds. Verified against the real extractors, not imagined:
#: `_DUE_HINTS` requires a literal "by …", so a bare "tonight" or a trailing
#: "on Monday" leaves `due` empty on a promise the wearer definitely gave a
#: deadline for.
DUE_MISSED_BY_REGEX = [
    "I'll call the landlord tonight",
    "Let me send Dana the contract on Monday",
]


class TestItOnlyEverAdds:
    """The property the whole design rests on. A parser that could overwrite a
    field would be a silent regression: the baseline is what has been in front
    of wearers, and nobody would ever see the substitution."""

    def test_an_existing_person_is_never_replaced(self):
        live = NLPLive(brain=None)
        meta = {"person": "Marcus", "due": "by Friday"}
        out = live.sharpen("I'll send Priya the lease by Monday", "promise", meta)
        assert out["person"] == "Marcus"
        assert out["due"] == "by Friday"

    def test_nothing_added_returns_the_same_dict(self):
        """Identity, not equality — a caller must be able to tell 'unchanged'
        from 'improved' without diffing fields, and the counters must not move
        for a pass that did nothing."""
        live = NLPLive(brain=None)
        meta = {"person": "Marcus", "due": "by Friday"}
        assert live.sharpen("I'll send Marcus the lease by Friday",
                            "promise", meta) is meta
        assert live.fields_added == 0
        assert live.sharpened == 0

    def test_an_improved_meta_is_a_copy(self):
        """The caller's dict is never mutated in place. `extract_events` hands
        out `ev.meta` and the ring keeps its own copy; editing the original
        would edit a row that has already been kept."""
        live = NLPLive(brain=None)
        meta = {"person": "", "due": ""}
        out = live.sharpen("I'll call the landlord tonight", "promise", meta)
        assert out is not meta
        assert meta == {"person": "", "due": ""}

    @pytest.mark.parametrize("kind", ["conversation", "person", "object",
                                      "place", "heard", "taught"])
    def test_a_non_commitment_kind_is_left_alone(self, kind):
        """A caption has no subject or deadline to find. Running a parse over
        every utterance would spend the model on sentences with no commitment
        in them — this is a cost guard AND a correctness one."""
        live = NLPLive(brain=None)
        meta = {}
        assert live.sharpen("I'll call the landlord tonight", kind, meta) is meta
        assert live.fields_added == 0

    def test_the_kinds_are_the_ones_the_ingest_path_emits(self):
        """`COMMITMENT_KINDS` is a claim about what exists, not a safety margin.
        Both kinds `extract_events` actually produces must be in it, or the
        wiring silently sharpens nothing."""
        assert {"promise", "task"} <= COMMITMENT_KINDS

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_empty_text_is_not_parsed(self, text):
        live = NLPLive(brain=None)
        meta = {}
        assert live.sharpen(text, "promise", meta) is meta


class TestItActuallyAddsSomething:
    """Non-vacuity. Every assertion below is stated as a DIFFERENCE against
    what `extract_events` produced on the same sentence, so a test that starts
    passing because the baseline improved is a test that stops asserting."""

    @pytest.mark.parametrize("text", DUE_MISSED_BY_REGEX)
    def test_a_deadline_the_baseline_missed_is_filled(self, text):
        base = [e for e in extract_events(text) if e.kind in COMMITMENT_KINDS]
        assert base, f"no commitment event at all in {text!r} — bad fixture"
        assert not (base[0].meta or {}).get("due"), (
            f"the baseline now finds the deadline in {text!r} itself; this case "
            "no longer demonstrates anything and should be replaced")

        live = NLPLive(brain=None)
        out = live.sharpen(text, base[0].kind, dict(base[0].meta or {}))
        assert out.get("due"), "the parser added no deadline either"
        assert live.fields_added >= 1
        assert live.sharpened == 1

    def test_a_task_gets_both_fields_it_never_had(self):
        """`task` rows carry only `{"task": ...}` — no person, no due. So a
        reminder the wearer set is a to-do with no deadline, which is exactly
        the row `CommitmentDriftEngine` reads."""
        text = "I need to send the lease by Friday"
        base = [e for e in extract_events(text) if e.kind == "task"]
        assert base, "bad fixture: no task event"
        assert "due" not in (base[0].meta or {})

        live = NLPLive(brain=None)
        out = live.sharpen(text, "task", dict(base[0].meta or {}))
        assert out.get("due"), "a task still has no deadline after sharpening"

    def test_the_counters_are_fields_not_calls(self):
        """`fields_added` counts FIELDS, `sharpened` counts ROWS. A single
        sentence that fills both is one row and two fields — the distinction is
        what stops a busy capture loop from looking like a productive one."""
        live = NLPLive(brain=None)
        live.sharpen("I need to send the lease by Friday", "task",
                     {"task": "send the lease by Friday"})
        assert live.sharpened == 1
        assert live.fields_added >= 1


class TestTheFloor:
    """The rule every optional dependency in this tree is held to: with the
    dependency absent, the result is never LESS than the baseline."""

    def test_with_the_parser_off_it_still_never_subtracts(self, monkeypatch):
        live = NLPLive(brain=None)
        parser = live.nlp()
        monkeypatch.setattr(parser, "_nlp", None)     # spaCy unavailable
        for text in DUE_MISSED_BY_REGEX:
            base = [e for e in extract_events(text)
                    if e.kind in COMMITMENT_KINDS][0]
            meta = dict(base.meta or {})
            out = live.sharpen(text, base.kind, meta)
            for k, v in meta.items():
                if v:
                    assert out.get(k) == v, f"{k} was lost with spaCy absent"

    def test_the_regex_path_alone_already_beats_the_baseline(self, monkeypatch):
        """Worth pinning, because it is the surprising half: `CommitmentNLP`'s
        own fallback uses a BROADER deadline pattern than `pipelines.ingest`
        does, so re-hosting this helps even on a machine with no spaCy at all.
        The capability is the parse; the wiring is worth more than the parse."""
        live = NLPLive(brain=None)
        monkeypatch.setattr(live.nlp(), "_nlp", None)
        out = live.sharpen("I'll call the landlord tonight", "promise",
                           {"person": "", "due": ""})
        assert out.get("due")


class TestItNeverBreaksTheCaptureLoop:
    """This sits on the path every spoken line takes. A parser that raises must
    cost the wearer a sharper field, never the memory itself."""

    def test_an_extractor_that_raises_returns_the_meta_untouched(self):
        live = NLPLive(brain=None)

        class _Boom:
            def extract(self, text):
                raise RuntimeError("model file is corrupt")

        live._nlp = _Boom()
        meta = {"person": "", "due": ""}
        assert live.sharpen("I'll call the landlord tonight", "promise",
                            meta) is meta
        assert live.fields_added == 0

    def test_a_parser_returning_none_is_not_an_error(self):
        live = NLPLive(brain=None)
        live._nlp = type("_N", (), {"extract": lambda self, t: None})()
        meta = {"due": ""}
        assert live.sharpen("I'll call tonight", "promise", meta) is meta

    def test_a_ner_that_raises_yields_no_names_rather_than_raising(self):
        live = NLPLive(brain=None)
        live._ner = type("_N", (), {
            "people": lambda self, t: (_ for _ in ()).throw(RuntimeError())})()
        assert live.people("Marcus was there") == []


class TestItIsWiredIntoIngest:
    """The link the seven previous re-hostings all turned on: not whether the
    seam exists, but whether the shipped Brain reaches it. Asserted through a
    real `Brain(cfg)` and read back off the RING, because the ring row is what
    Commitment Drift and Saga actually consult."""

    def _due_on_the_ring(self, brain, text):
        brain.lenses().ingest_utterance(text, via="said")
        rows = [b for b in brain.lenses().ring.latest(limit=20)
                if b.event.kind in COMMITMENT_KINDS]
        assert rows, "no commitment landed on the ring at all"
        return (rows[0].event.meta or {}).get("due", "")

    def test_the_ring_row_carries_a_deadline_the_baseline_never_had(self,
                                                                   tmp_path):
        text = "I'll call the landlord tonight"
        assert not (extract_events(text)[0].meta or {}).get("due")
        assert self._due_on_the_ring(_brain(tmp_path), text)

    def test_a_veiled_line_is_not_parsed_at_all(self, tmp_path, monkeypatch):
        """Incognito stops before extraction, so the Veil is not something this
        module has to re-implement — and a veiled minute must not move the
        capability meter either."""
        brain = _brain(tmp_path)
        monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
        brain.lenses().ingest_utterance("I'll call the landlord tonight", via="said")
        assert getattr(brain, "_nlp_live", None) is None

    def test_the_host_is_built_once_and_held(self, tmp_path):
        brain = _brain(tmp_path)
        assert nlp_live(brain) is nlp_live(brain)


class TestThePromotionFollowsProof:
    """`DL_WIRED_NLP` must follow a field added, not a wheel installed."""

    def test_live_is_false_until_a_field_is_added(self):
        live = NLPLive(brain=None)
        assert live.live() is False
        live.sharpen("I'll send Marcus the lease by Friday", "promise",
                     {"person": "Marcus", "due": "by Friday"})
        assert live.live() is False, (
            "a sentence the regex already handled promoted the capability — "
            "that is the fallback working, not the parser driving")
        live.sharpen("I'll call the landlord tonight", "promise",
                     {"person": "", "due": ""})
        assert live.live() is True

    def test_a_brain_that_never_ingested_is_not_promoted(self, tmp_path,
                                                         monkeypatch):
        """And the report must not BUILD the host in order to ask. Constructing
        `NLPLive` to interrogate it would make every capability poll look like
        use, which is the failure the whole promotion scheme exists to avoid."""
        monkeypatch.delenv("DL_WIRED_NLP", raising=False)
        brain = _brain(tmp_path)
        assert "DL_WIRED_NLP" not in self._env(brain, monkeypatch)
        assert getattr(brain, "_nlp_live", None) is None

    def test_a_real_ingest_promotes_it(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_WIRED_NLP", raising=False)
        brain = _brain(tmp_path)
        brain.lenses().ingest_utterance("I'll call the landlord tonight", via="said")
        if not nlp_live(brain).live():
            pytest.skip("neither extractor added a field on this machine")
        assert self._env(brain, monkeypatch)["DL_WIRED_NLP"] == "1"

    @staticmethod
    def _env(brain, monkeypatch) -> dict:
        """The env `_capability_payload` computed, not the state it reported.

        The reported state cannot see this on a machine WITHOUT spaCy: a
        missing wheel rightly outranks any flag, so `nlp` reads "missing"
        whether the parser sharpened anything or not, and a mutation that
        promoted unconditionally would sail past. The flag is what this code
        decides.
        """
        import dreamlayer.capabilities as caps
        seen = {}
        real = caps.report

        def _spy(env=None, **kw):
            seen.update(env or {})
            return real(env=env, **kw)

        monkeypatch.setattr(caps, "report", _spy)
        from dreamlayer.ai_brain.server.server import _capability_payload
        _capability_payload(brain)
        assert seen, "report() was never called — the spy caught nothing"
        return seen

    def test_status_reports_the_same_thing_it_promotes_on(self):
        live = NLPLive(brain=None)
        live.sharpen("I'll call the landlord tonight", "promise",
                     {"person": "", "due": ""})
        st = live.status()
        assert st["live"] is live.live()
        assert st["fields_added"] == live.fields_added
