""""Ask Juno" understands how people actually talk — without giving a model authority.

`rc_compose` is the builder's "Ask Juno" box. It ran the regex `IntentParser`
alone, so it understood the five phrasings its own error message lists and very
little else; the Brain has had a local model the whole time and the seam built to
use it (`LLMIntentParser`) was constructed nowhere.

Wiring it turned up two defects in that seam, and both are pinned here:

  * it CONCATENATED the model's restatement onto the raw text before parsing, so
    the original phrasing's noise outvoted the model — the optional model's
    entire contribution erased by a string join;
  * it gated the model path on `instructor`/`outlines`, neither of which that
    path imports or calls (both imports carry `noqa: F401`). A wearer who wired a
    local model got the bare regex parser until they installed two libraries that
    do nothing here.

The invariant that matters most is the FLOOR: a model can only add a reading the
regex could not reach, never take one away. A suggestion layer that can lose you
a working phrasing is worse than no suggestion layer, and that is the failure
mode this repo keeps finding in optional dependencies.
"""
from __future__ import annotations

import logging

import pytest

from dreamlayer.reality_compiler.intent_parser import IntentParser
from dreamlayer.reality_compiler.intent_parser_llm import LLMIntentParser


def _kind(parser, text):
    """The intent class name, or "miss" — so a table reads at a glance."""
    try:
        return type(parser.parse(text)).__name__
    except ValueError:
        return "miss"


#: (messy phrasing, what a model restating it in the closed grammar would say)
PHRASINGS = [
    ("can you give me something that counts down five minutes and buzzes at the end",
     "5 minute round timer"),
    ("I want to keep score during the match, tap to add a point", "points marker"),
    ("track how long I've been running", "stopwatch"),
    ("show my speech notes so I can read them", "teleprompter"),
    ("remind me to stretch every day", "habit reminder"),
]


class TestTheModelCanOnlyAdd:
    """The floor. Every other benefit is worthless if this can fail."""

    @pytest.mark.parametrize("raw,_hint", PHRASINGS)
    @pytest.mark.parametrize("answer", [
        "banana helicopter",          # confidently wrong
        "",                           # said nothing
        "   ",                        # whitespace
        "I'm sorry, I can't help with that.",
        "```json\n{\"behavior\": \"unknown\"}\n```",
    ])
    def test_a_useless_model_never_costs_a_reading(self, raw, _hint, answer):
        regex_only = _kind(IntentParser(), raw)
        with_model = _kind(LLMIntentParser(llm=lambda _t: answer), raw)
        assert with_model == regex_only, (
            f"the model turned {regex_only} into {with_model} on {raw!r} — a "
            "suggestion layer must never subtract")

    @pytest.mark.parametrize("raw,_hint", PHRASINGS)
    def test_a_model_that_explodes_never_costs_a_reading(self, raw, _hint):
        def boom(_t):
            raise RuntimeError("the model went away")
        assert _kind(LLMIntentParser(llm=boom), raw) == _kind(IntentParser(), raw)

    def test_no_model_wired_is_byte_for_byte_the_regex_parser(self):
        """The module's own headline promise: "with no model wired it IS the
        regex IntentParser, byte-for-byte"."""
        plain, lifted = IntentParser(), LLMIntentParser()
        for raw, _h in PHRASINGS:
            assert _kind(lifted, raw) == _kind(plain, raw)


class TestTheModelActuallyHelps:
    """The other direction — a floor nothing ever rises above is just overhead."""

    def test_messy_phrasings_start_working(self):
        gained = []
        for raw, hint in PHRASINGS:
            before = _kind(IntentParser(), raw)
            after = _kind(LLMIntentParser(llm=lambda _t, h=hint: h), raw)
            if after != before:
                gained.append((raw, before, after))
        assert len(gained) >= 3, (
            f"the model changed only {len(gained)} of {len(PHRASINGS)} readings; "
            "it is not earning the round trip")

    def test_the_restatement_beats_the_raw_texts_noise(self):
        """The concatenation bug, named. "keep score … tap to add a point" hits
        the counter matcher on its own words; the model's "points marker" is the
        right answer and a string join let the wrong one win."""
        raw = "I want to keep score during the match, tap to add a point"
        assert _kind(IntentParser(), raw) == "SimpleCounterIntent"
        assert _kind(IntentParser(), "points marker") == "PointsMarkerIntent"
        got = _kind(LLMIntentParser(llm=lambda _t: "points marker"), raw)
        assert got == "PointsMarkerIntent", (
            "the raw text outvoted the model's restatement — the hint is being "
            "concatenated rather than parsed on its own")

    def test_a_phrasing_the_regex_cannot_reach_at_all(self):
        raw = "track how long I've been running"
        assert _kind(IntentParser(), raw) == "miss"
        assert _kind(LLMIntentParser(llm=lambda _t: "stopwatch"), raw) == "StopwatchIntent"


class TestItDoesNotNeedLibrariesItNeverCalls:
    def test_the_model_path_runs_with_nothing_else_installed(self):
        got = _kind(LLMIntentParser(llm=lambda _t: "stopwatch"),
                    "track how long I've been running")
        assert got == "StopwatchIntent"

    def test_the_seam_does_not_even_import_them(self):
        """It used to import both to decide whether the model path could run,
        and called neither. A module holding a second copy of the capability
        catalogue's dependency claim is a second thing that can be wrong — and
        it WAS wrong, gating a working path on libraries with no part in it.

        If this starts failing, the seam has grown a real dependency and the
        judgement recorded in decisions/0007 needs revisiting, not deleting."""
        import pathlib
        from dreamlayer.reality_compiler import intent_parser_llm as m
        src = pathlib.Path(m.__file__).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        code = code.split('"""', 2)[-1]         # past the module docstring
        for lib in ("instructor", "outlines"):
            assert f"import {lib}" not in code


class TestNothingTheWearerSaidIsLogged:
    """A lens description is the wearer's own words. The house rule is that
    captured content is DRAWN, never logged — and the old handler caught the
    ordinary "not one of the 15" outcome alongside real errors and logged the
    exception, whose message embeds the text verbatim."""

    #: Must MISS the grammar (so the raise path runs) while carrying the kind
    #: of content the rule exists for — a name and a private context.
    SECRET = "something about my therapy sessions with Dr Halloran"

    def test_an_unparseable_request_is_raised_not_logged(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="dreamlayer.intent_parser_llm"):
            with pytest.raises(ValueError):
                LLMIntentParser(llm=lambda _t: "banana").parse(self.SECRET)
        assert self.SECRET not in caplog.text
        assert "therapy" not in caplog.text and "Halloran" not in caplog.text

    def test_a_suggester_fault_logs_the_type_not_the_message(self, caplog):
        def boom(_t):
            raise RuntimeError(f"upstream said: {self.SECRET}")
        with caplog.at_level(logging.DEBUG, logger="dreamlayer.intent_parser_llm"):
            LLMIntentParser(llm=boom).parse("3 minute round timer")
        assert "RuntimeError" in caplog.text        # the fault is still visible
        assert self.SECRET not in caplog.text       # its payload is not


# --------------------------------------------------------------------------
# the live path
# --------------------------------------------------------------------------

class _Backend:
    def __init__(self, reply="", explode=False):
        self.reply, self.explode, self.prompts = reply, explode, []

    def chat(self, prompt):
        self.prompts.append(prompt)
        if self.explode:
            raise RuntimeError("no model")
        return self.reply


def _brain(tmp_path, backend=None, veiled=False, url="http://127.0.0.1:11434"):
    from dreamlayer.ai_brain.server import Brain
    b = Brain(tmp_path)
    b._backend = backend
    b.config.ollama_url = url
    if veiled:
        b.config.network_mode = "lan_only"
        b.incognito_now = lambda: True                      # type: ignore[method-assign]
    return b


class TestAskJunoUsesTheLocalModel:
    def test_a_messy_request_now_composes(self, tmp_path):
        raw = "track how long I've been running"
        assert _brain(tmp_path).rc_compose(raw)["ok"] is False   # no model → as before
        out = _brain(tmp_path, _Backend("stopwatch")).rc_compose(raw)
        assert out["ok"] is True and out["scenes"] >= 1

    def test_the_prompt_asks_for_a_restatement_not_a_lens(self, tmp_path):
        """The model is given the narrowest possible job. If it is ever asked to
        author a behaviour instead, the safety story ("the model only suggests")
        stops being true of the prompt even if it stays true of the code."""
        be = _Backend("stopwatch")
        _brain(tmp_path, be).rc_compose("track how long I've been running")
        assert be.prompts, "the local model was never consulted"
        p = be.prompts[0]
        assert "one of these behaviours" in p and "stopwatch" in p
        assert p.rstrip().endswith("track how long I've been running")

    def test_the_result_still_passes_the_real_gate(self, tmp_path):
        """The model suggested it; the proof still decides. Composing routes
        through the same `compile_intent` every other caller uses, so the figment
        the builder loads is budget-verified here."""
        from dreamlayer.reality_compiler.v2.budgets import verify
        from dreamlayer.reality_compiler.v2.figment import Figment
        out = _brain(tmp_path, _Backend("5 minute round timer")).rc_compose(
            "count down five minutes for me")
        assert out["ok"] is True
        assert verify(Figment.from_dict(out["figment"])).ok

    def test_composing_still_never_deploys(self, tmp_path):
        b = _brain(tmp_path, _Backend("stopwatch"))
        b.rc_compose("track how long I've been running")
        assert getattr(b, "_rc_active", None) is None


class TestTheSuggesterIsGated:
    RAW = "track how long I've been running"

    def test_the_veil_keeps_the_words_on_the_box(self, tmp_path):
        be = _Backend("stopwatch")
        out = _brain(tmp_path, be, veiled=True).rc_compose(self.RAW)
        assert be.prompts == [], "a veiled compose consulted the model"
        assert out["ok"] is False                    # deterministic path, as before

    def test_an_unreadable_posture_fails_closed(self, tmp_path):
        be = _Backend("stopwatch")
        b = _brain(tmp_path, be)
        b.incognito_now = lambda: (_ for _ in ()).throw(RuntimeError("?"))  # type: ignore[method-assign]
        b.rc_compose(self.RAW)
        assert be.prompts == [], "an unreadable posture still sent the words"

    def test_an_off_box_model_is_never_sent_the_wearers_words(self, tmp_path):
        """A remote `ollama_url` receiving a lens description is egress. This
        path declines rather than counting it — the wearer loses a nicety, never
        gets a surprise upload."""
        be = _Backend("stopwatch")
        b = _brain(tmp_path, be, url="http://203.0.113.9:11434")
        out = b.rc_compose(self.RAW)
        assert be.prompts == []
        assert out["ok"] is False

    def test_a_local_url_is_allowed(self, tmp_path):
        be = _Backend("stopwatch")
        for url in ("http://127.0.0.1:11434", "http://localhost:11434",
                    "http://192.168.1.20:11434", ""):
            be.prompts.clear()
            _brain(tmp_path, be, url=url).rc_compose(self.RAW)
            assert be.prompts, f"a local endpoint {url!r} was refused"

    def test_no_backend_is_simply_the_offline_parser(self, tmp_path):
        out = _brain(tmp_path, None).rc_compose(self.RAW)
        assert out["ok"] is False and out["unmatched"] is True

    def test_a_dead_model_does_not_break_the_box(self, tmp_path):
        """A backend that raises must cost the suggestion, never the feature."""
        out = _brain(tmp_path, _Backend(explode=True)).rc_compose(
            "a 5 minute countdown that pulses at the end")
        assert out["ok"] is True, "a dead model took Ask Juno down with it"


# --------------------------------------------------------------------------
# constrained restatement — what `structured_output` was for
# --------------------------------------------------------------------------

class _SchemaBackend:
    """A model server that honours `format`: it answers JSON when constrained
    and prose when not, and records which it was asked for."""

    def __init__(self, constrained=None, loose="", schema_ok=True):
        self.constrained, self.loose = constrained, loose
        self.schema_ok, self.calls = schema_ok, []

    def chat(self, prompt, schema=None):
        self.calls.append(schema)
        if schema is not None:
            return self.constrained if self.schema_ok else ""
        return self.loose


class TestTheRestatementIsConstrained:
    """`outlines` needs the sampler in THIS process and the model here is an
    HTTP call; `instructor` patches an OpenAI client object that does not exist
    on this path; and either would have had the model CHOOSE the behaviour,
    which `intent_parser_llm`'s design explicitly forbids. Constraining the
    server's own sampler leaves the deterministic matcher deciding — the whole
    safety story — and needs no dependency at all."""

    def test_a_constrained_answer_becomes_a_command(self, tmp_path):
        be = _SchemaBackend(constrained='{"behaviour":"round timer",'
                                        '"amount":5,"unit":"minutes"}')
        out = _brain(tmp_path, be).rc_compose("count me down for a five minute round")
        assert out["ok"] is True
        assert be.calls[0] is not None            # constrained on the first ask
        assert len(be.calls) == 1                 # …and never asked twice

    def test_the_schema_names_every_phrasing_the_matcher_reads(self, tmp_path):
        from dreamlayer.ai_brain.server.server import Brain
        parser = IntentParser()
        for phrase in Brain._RESTATE_SCHEMA["properties"]["behaviour"]["enum"]:
            # Every enum member must be a phrasing the deterministic matcher
            # actually accepts, or the constraint guarantees an answer the
            # regex then rejects — worse than not constraining at all.
            assert _kind(parser, phrase) != "miss", phrase

    def test_a_server_that_ignores_format_is_asked_again_plainly(self, tmp_path):
        be = _SchemaBackend(schema_ok=False, loose="stopwatch")
        out = _brain(tmp_path, be).rc_compose("track how long I've been running")
        assert out["ok"] is True
        assert [c is not None for c in be.calls] == [True, False]

    def test_prose_from_a_server_that_ignored_format_is_not_trusted(self, tmp_path):
        # A server without `format` answers prose to the constrained ask too.
        # Treating that as the structured answer would skip the retry AND feed
        # the matcher something the enum never vetted.
        be = _SchemaBackend(constrained="Sure! Here's a stopwatch for you.",
                            loose="stopwatch")
        out = _brain(tmp_path, be).rc_compose("track how long I've been running")
        assert out["ok"] is True and len(be.calls) == 2

    def test_a_behaviour_outside_the_enum_is_refused(self, tmp_path):
        from dreamlayer.ai_brain.server.server import Brain
        assert Brain._restatement_of('{"behaviour":"launch the missiles"}') == ""

    def test_a_backend_with_the_old_signature_still_works(self, tmp_path):
        # `chat(prompt)` — every backend written before the schema existed.
        be = _Backend("stopwatch")
        assert _brain(tmp_path, be).rc_compose(
            "track how long I've been running")["ok"] is True

    def test_the_floor_holds_when_both_asks_are_useless(self, tmp_path):
        be = _SchemaBackend(constrained="{}", loose="")
        raw = "3 minute round timer"                    # the regex can read it
        assert _brain(tmp_path, be).rc_compose(raw)["ok"] is True


class TestRestatementComposition:
    def _of(self, reply):
        from dreamlayer.ai_brain.server.server import Brain
        return Brain._restatement_of(reply)

    def test_a_bare_behaviour_needs_no_number(self):
        assert self._of('{"behaviour":"stopwatch"}') == "stopwatch"

    def test_a_duration_is_kept(self):
        assert self._of('{"behaviour":"round timer","amount":3,'
                        '"unit":"minutes"}') == "round timer 3 minutes"

    def test_a_null_amount_is_dropped(self):
        assert self._of('{"behaviour":"counter","amount":null,'
                        '"unit":null}') == "counter"

    def test_a_nonsense_amount_is_dropped_not_raised(self):
        assert self._of('{"behaviour":"counter","amount":"lots"}') == "counter"

    def test_a_zero_or_negative_amount_is_dropped(self):
        assert self._of('{"behaviour":"counter","amount":0}') == "counter"
        assert self._of('{"behaviour":"counter","amount":-4}') == "counter"

    def test_a_unit_outside_the_two_is_dropped(self):
        assert self._of('{"behaviour":"counter","amount":7,'
                        '"unit":"parsecs"}') == "counter 7"

    def test_anything_that_is_not_an_object_is_refused(self):
        for reply in ("", "not json", "[1,2,3]", '"stopwatch"', "null"):
            assert self._of(reply) == ""


class TestTheSchemaReachesTheWire:
    def test_the_backend_puts_format_on_the_request(self):
        from dreamlayer.ai_brain.server.backends import OllamaBackend

        class Cfg:
            ollama_url = "http://127.0.0.1:11434"
            ollama_chat_model = "llama3"
            network_mode = "auto"
            cloud_enabled = True
        sent = {}

        def post(url, payload):
            sent.update(payload)
            return {"response": '{"behaviour":"stopwatch"}'}
        be = OllamaBackend(Cfg(), http_post=post)
        assert be.chat("hi", schema={"type": "object"}) == \
            '{"behaviour":"stopwatch"}'
        assert sent["format"] == {"type": "object"}

    def test_no_schema_means_no_format_field(self):
        from dreamlayer.ai_brain.server.backends import OllamaBackend

        class Cfg:
            ollama_url = "http://127.0.0.1:11434"
            ollama_chat_model = "llama3"
            network_mode = "auto"
            cloud_enabled = True
        sent = {}

        def post(url, payload):
            sent.update(payload)
            return {"response": "stopwatch"}
        OllamaBackend(Cfg(), http_post=post).chat("hi")
        assert "format" not in sent
