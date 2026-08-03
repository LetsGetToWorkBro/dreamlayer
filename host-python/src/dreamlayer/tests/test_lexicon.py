"""test_lexicon.py — a rare word heard in conversation, defined on the glass (#471).

Three layers, and every one of them runs FULLY OFFLINE:

  * the rarity gate (`ai_brain/server/lexicon_live.py`) — a tokenizer and four
    deterministic tests, no model, no network, no I/O beyond a bundled text
    asset;
  * the connector (`plugins/dictionaryapi.py`) — exercised through its
    `fetch_fn` seam with a canned dictionaryapi.dev reply, exactly as
    `test_openlibrary.py` exercises Open Library. The shipped `_default_fetch`
    is never called here;
  * the wiring (`EarHost.ingest_caption`) — the hook the maintainer named on the
    issue, in place of the `Orchestrator.ingest_caption` the issue body pointed
    at (nothing in the shipped Brain constructs an Orchestrator).

THE ASSERTIONS THAT ARE ABOUT SAFETY RATHER THAN FEATURES are the ones to keep:
`fetch` is a counting spy in every gate test, so "no card was drawn" and
"nothing left the device" are checked separately. They are different failures —
a lookup that happens and is then hushed has already egressed.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server import lexicon_live as LX
from dreamlayer.hud import cards
from dreamlayer.plugins.dictionaryapi import (
    ENTRIES_URL, build_query, define_fn, lookup, parse_entry,
)


# A real dictionaryapi.dev body, trimmed to the fields the connector reads.
CANNED = json.dumps([{
    "word": "undulating",
    "phonetic": "/ˈʌndjʊleɪtɪŋ/",
    "meanings": [{
        "partOfSpeech": "verb",
        "definitions": [
            {"definition": "To move in a smooth wavelike motion.",
             "example": "the undulating hills"},
            {"definition": "A second sense nobody should see."},
        ],
    }],
}])

# …and the body it returns for a word it has no entry for (with a 404, which the
# shipped fetch raises on — this is the shape a lenient fetcher would hand over).
NO_ENTRY = json.dumps({"title": "No Definitions Found",
                       "message": "Sorry pal, we couldn't find definitions."})


class _Fetch:
    """A counting fetch seam. The count is the egress assertion."""

    def __init__(self, body=CANNED):
        self.body = body
        self.urls: list = []

    def __call__(self, url):
        self.urls.append(url)
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    @property
    def calls(self) -> int:
        return len(self.urls)


@pytest.fixture
def brain():
    return Brain(pathlib.Path(tempfile.mkdtemp()))


def _ear(brain, fetch=None, **cfg):
    """An ear with Lexicon wired to a fake fetch and the config applied."""
    for k, v in cfg.items():
        setattr(brain.config, k, v)
    ear = EarHost(brain)
    ear.lexicon._define = define_fn(fetch or _Fetch())
    return ear


def _drawn(brain):
    """Cards that genuinely reached a stream, in order. Counts deliveries."""
    got: list = []

    class _Q:
        def put_nowait(self, ev):
            got.append(ev)

    brain._event_subs = [_Q()]
    return got


# ---------------------------------------------------------------------------
# The rarity gate — pure logic, no model, no network
# ---------------------------------------------------------------------------

class TestTheRarityGate:

    def test_a_rare_word_is_offered(self):
        assert LX.is_rare("undulating")
        assert LX.rare_word("the fields were undulating in the wind") == "undulating"

    @pytest.mark.parametrize("word", [
        "something", "everything", "beautiful", "conversation", "questions",
        "interesting", "absolutely", "installation", "attendance", "historical",
        "remembered", "wonderfully", "difficult", "important",
    ])
    def test_a_common_word_is_not(self, word):
        """The list plus `stems()`: one entry covers a whole family, including
        the derivations English piles on ("install" covers "installation")."""
        assert not LX.is_rare(word), f"{word} would have drawn a card"

    def test_a_short_word_is_never_offered(self):
        """Short words are overwhelmingly common ones; being told what "amber"
        means is what makes a wearer switch a feature off."""
        assert not LX.is_rare("amber")
        assert not LX.is_rare("x" * (LX.MIN_LEN - 1))

    def test_an_absurdly_long_token_is_refused(self):
        """An ASR run-on, not a word — and it also bounds what can reach the
        connector."""
        assert not LX.is_rare("x" * (LX.MAX_LEN + 1))

    def test_a_capitalised_token_is_refused(self):
        """The model-free name guard. A capital anywhere means a proper noun or
        an acronym, and a surname is exactly the thing that must not reach a
        third-party dictionary — so the whole class is refused rather than
        classified. `person_guard.label_is_a_person` is NOT used: it is
        Presidio/spaCy-backed, i.e. a model, and this gate must work on a Brain
        with nothing installed."""
        assert not LX.is_rare("Kowalczyk")
        assert not LX.is_rare("Undulating")
        assert not LX.is_rare("NASDAQ")
        assert LX.rare_word("Undulating hills, said Kowalczyk") == ""

    def test_a_non_alphabetic_token_is_refused(self):
        assert not LX.is_rare("don't")
        assert not LX.is_rare("covid19")
        assert LX.rare_word("call 5551234567 about the lease") == ""

    def test_at_most_one_word_per_utterance_and_the_first_one_wins(self):
        """Three unusual words in a line is a line to follow, not three cards."""
        got = LX.rare_word("the perspicacious pangolin was undulating")
        assert got == "perspicacious"

    def test_the_gate_needs_no_network_and_no_model(self):
        """The "no model, no network" claim, read off the IMPORTS rather than
        off the prose. Everything before `class LexiconRead` is the gate; the
        connector is imported lazily inside the host and is not part of it.

        `ast` rather than a substring scan on purpose: the module docstring
        explains at length why `person_guard` is NOT used, and a text search
        cannot tell an explanation from a call."""
        import ast
        tree = ast.parse(pathlib.Path(LX.__file__).read_text(encoding="utf-8"))
        gate = [n for n in tree.body if not (isinstance(n, ast.ClassDef)
                                             and n.name == "LexiconRead")]
        imported: set = set()
        for node in gate:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    imported |= {a.name.split(".")[0] for a in sub.names}
                elif isinstance(sub, ast.ImportFrom):
                    imported.add((sub.module or "").split(".")[0])
                    imported |= {a.name for a in sub.names}
        for banned in ("urllib", "http", "socket", "requests", "numpy", "torch",
                       "spacy", "presidio_analyzer", "person_guard",
                       "dictionaryapi", "transformers"):
            assert banned not in imported, (
                f"the rarity gate imports {banned} — it is supposed to be pure "
                f"logic (imports found: {sorted(imported)})")

    def test_the_word_list_actually_loaded(self):
        """Non-vacuity. With an empty list every long word reads as rare, so a
        gate that quietly lost its asset would pass every "is rare" test above
        and fail every "is not" one — this pins that the asset is real."""
        assert len(LX.common_words()) > 2000

    def test_an_empty_word_list_disables_the_feature_rather_than_defining_everything(
            self, brain, monkeypatch):
        """The failure direction that matters. A missing/unreadable asset must
        make Lexicon do NOTHING, not treat the whole language as rare and ship
        every long word a wearer says to a third party."""
        monkeypatch.setattr(LX, "_COMMON", frozenset())
        monkeypatch.setattr(LX, "_ASSET", pathlib.Path("/nonexistent/words.txt"))
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        assert ear.lexicon.enabled is False
        assert ear.lexicon.note_transcript("the fields were undulating") == 0
        assert fetch.calls == 0


# ---------------------------------------------------------------------------
# The connector — the openlibrary.py pattern, offline through `fetch_fn`
# ---------------------------------------------------------------------------

class TestTheDictionaryConnector:

    def test_build_query_pins_the_host_and_the_word(self):
        url = build_query("undulating")
        assert url == f"{ENTRIES_URL}/undulating"

    def test_build_query_refuses_anything_that_is_not_one_word(self):
        """THE EGRESS GUARANTEE, enforced in the connector and not only at the
        caller: "ship only the single word, never the utterance". Percent-
        encoding a sentence still SENDS the sentence, so the shape is refused."""
        for bad in ("the lease is due friday", "undulating hills", "5551234567",
                    "o'brien", "../../etc/passwd", "", "x" * 60):
            with pytest.raises(ValueError):
                build_query(bad)

    def test_build_query_lowercases_before_the_check(self):
        assert build_query("Undulating") == f"{ENTRIES_URL}/undulating"

    def test_parse_entry_takes_the_first_sense_and_the_part_of_speech(self):
        got = parse_entry(json.loads(CANNED))
        assert got["sense"] == "To move in a smooth wavelike motion."
        assert got["part_of_speech"] == "verb"
        assert got["word"] == "undulating"

    def test_parse_entry_treats_the_payload_as_untrusted(self):
        """It came off the network. A non-list, a null nested anywhere, a number
        where a string belongs — each yields {} rather than an exception or a
        card built out of None."""
        for hostile in (None, {}, "text", [None], [{"meanings": None}],
                        [{"meanings": [{"definitions": [{"definition": 7}]}]}],
                        [{"meanings": [{"definitions": [{"definition": "  "}]}]}]):
            assert parse_entry(hostile) == {}

    def test_lookup_with_an_injected_fetch(self):
        got = lookup("undulating", _Fetch())
        assert got["sense"].startswith("To move in a smooth")

    def test_lookup_swallows_every_failure_and_returns_empty(self):
        assert lookup("undulating", _Fetch(OSError("no net"))) == {}   # offline
        assert lookup("undulating", _Fetch("not json")) == {}          # malformed
        assert lookup("undulating", _Fetch(NO_ENTRY)) == {}            # no entry
        assert lookup("the whole utterance", _Fetch()) == {}           # refused shape
        assert lookup("", _Fetch()) == {}                              # nothing to ask

    def test_define_fn_caches_so_a_repeated_word_costs_one_request(self):
        fetch = _Fetch()
        define = define_fn(fetch, ttl=300.0, now_fn=lambda: 1000.0)
        assert define("undulating")["sense"]
        assert define("undulating")["sense"]
        assert fetch.calls == 1

    def test_define_fn_caches_a_miss_too(self):
        """`ol_shop_fn`'s rule, and here it is also a privacy property: a word
        with no entry — a proper noun that slipped the gate, say — is not sent
        again and again."""
        fetch = _Fetch(NO_ENTRY)
        define = define_fn(fetch, ttl=300.0, now_fn=lambda: 1000.0)
        assert define("kowalczyk") == {}
        assert define("kowalczyk") == {}
        assert fetch.calls == 1

    def test_the_shipped_fetch_uses_the_hardened_egress_primitives(self):
        """Not a behaviour test — a copy-paste-regression test. `_egress.py`
        exists because a new connector reintroduces response-OOM and
        SSRF-via-redirect by copying an old one."""
        src = pathlib.Path(
            LX.__file__).parent.parent.parent / "plugins" / "dictionaryapi.py"
        body = src.read_text(encoding="utf-8")
        assert "from ._egress import no_redirect_opener, read_capped" in body
        fetch = body.split("def _default_fetch(", 1)[1]
        assert "no_redirect_opener()" in fetch and "read_capped(" in fetch
        assert "urlopen(" not in fetch, "a bare urlopen follows redirects"


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

class TestTheCard:

    def test_the_word_is_the_hero_and_the_sense_is_the_answer(self):
        c = cards.lexicon(word="undulating", sense="moving in a wavelike motion",
                          part_of_speech="verb")
        assert c["type"] == "LexiconCard"
        assert c["eyebrow"] == "LEXICON"
        assert c["primary"] == "undulating"
        assert c["detail"] == "moving in a wavelike motion"
        assert c["footer"] == "verb"

    def test_lines_honour_the_glass_budget(self):
        """5 lines x 24 UTF-8 bytes. The sense is arbitrary third-party text, so
        it is clamped rather than trusted to fit."""
        c = cards.lexicon(word="undulating", sense="lorem ipsum dolor " * 40)
        assert len(c["lines"]) <= 5
        for line in c["lines"]:
            assert len(line.encode("utf-8")) <= 24, line

    def test_an_unbroken_sense_is_clamped_by_bytes_not_characters(self):
        """A character budget is a byte budget only for ASCII, and a dictionary
        sense is exactly where that stops being true."""
        c = cards.lexicon(word="coöperate", sense="ö" * 200)
        for line in c["lines"]:
            assert len(line.encode("utf-8")) <= 24, line

    def test_it_survives_empty_input(self):
        c = cards.lexicon()
        assert c["type"] == "LexiconCard" and c["primary"] == ""

    def test_it_is_in_all_samples_for_the_export_pipeline(self):
        assert cards.ALL_SAMPLES["lexicon"]["type"] == "LexiconCard"

    def test_the_live_lens_has_a_branch_for_it(self):
        """The Brain's ONLY surface is the Live Lens, whose generic renderer
        draws eyebrow and primary AND NOTHING ELSE. For this card the entire
        answer is in `detail`, so without a branch it would put the word the
        wearer could not place on the glass and drop what it means."""
        live = (pathlib.Path(LX.__file__).with_name("live.py")
                .read_text(encoding="utf-8"))
        assert 't === "LexiconCard"' in live
        body = live.split("function glassLexiconCard(", 1)[1][:1600]
        assert "c.detail" in body, "the branch drops the definition"


# ---------------------------------------------------------------------------
# The wiring: EarHost.ingest_caption — the hook the maintainer named
# ---------------------------------------------------------------------------

class TestItHangsOffTheEarsCaptionPath:

    def test_the_ear_defines_a_rare_word_it_hears(self, brain):
        ear = _ear(brain, lexicon_enabled=True)
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating in the evening light")
        assert [e["kind"] for e in drawn] == ["lexicon"]
        card = drawn[0]["card"]
        assert card["type"] == "LexiconCard" and card["primary"] == "undulating"
        assert card["detail"].startswith("To move in a smooth")
        assert ear.lexicon.proved is True and ear.lexicon.defined_count == 1

    def test_the_hook_is_ingest_caption_and_not_the_orchestrator(self):
        """The maintainer's correction, pinned. `Orchestrator.ingest_caption` is
        unreachable from the shipped Brain (`decisions/0001`), so a Lexicon
        wired there would be a feature no wearer could reach."""
        src = pathlib.Path(LX.__file__).with_name("ear.py").read_text(encoding="utf-8")
        body = src.split("def ingest_caption(", 1)[1].split("\n    # -- ", 1)[0]
        assert "self.lexicon.note_transcript(text)" in body
        orch = (pathlib.Path(LX.__file__).parents[2] / "orchestrator"
                / "ops_conversation.py").read_text(encoding="utf-8")
        assert "lexicon" not in orch.lower(), (
            "Lexicon leaked into the Orchestrator's caption path — the exact "
            "address the maintainer corrected on issue #471")

    def test_it_is_fed_the_scrubbed_text(self):
        """The egress rule the maintainer flagged: the word must be taken from
        the REDACTED text, or a contact identifier could be handed to a
        third-party dictionary. Pinned the same way the fact-checker's is."""
        src = pathlib.Path(LX.__file__).with_name("ear.py").read_text(encoding="utf-8")
        body = src.split("def ingest_caption(", 1)[1]
        assert body.index("default_redactor") < body.index("self.lexicon.note_transcript")

    def test_a_failure_inside_lexicon_never_costs_the_utterance_its_memory(self, brain):
        ear = _ear(brain, lexicon_enabled=True)
        ear.lexicon.note_transcript = lambda *a, **k: (  # type: ignore[method-assign]
            _ for _ in ()).throw(RuntimeError("boom"))
        docs: list = []
        brain.index.add_documents = lambda pairs: docs.extend(pairs)  # type: ignore[assignment]
        ear.ingest_caption("the fields were undulating")     # must not raise
        assert ear.heard_count == 1
        assert any("undulating" in text for _n, text in docs)


# ---------------------------------------------------------------------------
# Opt-in, dedupe, and failing quiet
# ---------------------------------------------------------------------------

class TestTheSwitch:

    def test_it_is_off_by_default(self):
        from dreamlayer.ai_brain.server.store import BrainConfig
        assert BrainConfig().lexicon_enabled is False

    def test_off_means_no_card_and_no_request(self, brain):
        fetch = _Fetch()
        ear = _ear(brain, fetch)                      # lexicon_enabled left False
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating")
        assert drawn == [] and fetch.calls == 0

    def test_the_wearer_can_actually_reach_the_switch(self):
        """A Brain-side flag with no control is the defect this repo is built
        around — `test_interrupt_prefs.py`'s header is seven switches that
        "called `set(...)` and `persist(...)` and stopped". So the panel row, the
        render and the setter are all pinned: the switch exists, it shows the
        stored value, and flipping it writes the field the ear reads."""
        panel = (pathlib.Path(LX.__file__).with_name("panel.py")
                 .read_text(encoding="utf-8"))
        assert 'id="lexicon" onchange="saveLexicon()"' in panel
        assert '$("lexicon").checked=!!c.config.lexicon_enabled' in panel
        assert "lexicon_enabled:on" in panel
        # …and the disclosure names the egress, since this is the only switch on
        # that page that turns one on.
        assert "api.dictionaryapi.dev" in panel

    def test_it_can_be_written_over_the_wire(self, brain):
        brain.apply_config({"lexicon_enabled": True})
        assert brain.config.lexicon_enabled is True
        assert brain.config.public()["lexicon_enabled"] is True

    def test_an_unreadable_config_fails_closed(self, brain):
        """An opt-in that egresses fails CLOSED, unlike an interruption
        preference: the feature the wearer never switched on must not be able to
        turn itself on because a config read raised."""
        ear = _ear(brain, lexicon_enabled=True)

        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("config unreadable")

        brain.config = _Boom()                        # type: ignore[assignment]
        assert ear.lexicon.enabled is False


class TestItDoesNotSpamTheSameWord:

    def test_the_same_rare_word_is_defined_once_per_session(self, brain):
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating")
        ear.ingest_caption("still undulating, look at it")
        ear.ingest_caption("undulating again")
        assert [e["kind"] for e in drawn] == ["lexicon"], "the same word popped twice"
        assert fetch.calls == 1
        assert ear.lexicon.defined_count == 1

    def test_a_word_with_no_definition_is_not_asked_about_twice(self, brain):
        """Dedupe on the WORD, not on the card, and that is what keeps a proper
        noun the gate let through from being sent repeatedly."""
        fetch = _Fetch(NO_ENTRY)
        ear = _ear(brain, fetch, lexicon_enabled=True)
        drawn = _drawn(brain)
        ear.ingest_caption("kowalczyk lives here")
        ear.ingest_caption("kowalczyk again")
        assert drawn == [] and fetch.calls == 1

    def test_a_different_rare_word_still_gets_its_card(self, brain):
        ear = _ear(brain, _Fetch(), lexicon_enabled=True)
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating")
        ear.ingest_caption("a perspicacious remark")
        assert len(drawn) == 2

    def test_the_dedupe_set_cannot_grow_without_bound(self, brain):
        ear = _ear(brain, _Fetch(), lexicon_enabled=True)
        for i in range(ear.lexicon.DEDUPE_MAX + 50):
            ear.lexicon._remember(f"word{i}")
        assert len(ear.lexicon._seen) == ear.lexicon.DEDUPE_MAX


class TestItFailsQuiet:

    def test_offline_draws_nothing_and_never_an_error_card(self, brain):
        """"A missing definition is not an event." An error card mid-conversation
        would be worse than the silence it replaces."""
        ear = _ear(brain, _Fetch(OSError("network unreachable")),
                   lexicon_enabled=True)
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating")
        assert drawn == []
        assert ear.lexicon.proved is False

    def test_a_word_the_dictionary_does_not_know_draws_nothing(self, brain):
        ear = _ear(brain, _Fetch(NO_ENTRY), lexicon_enabled=True)
        assert ear.lexicon.note_transcript("the fields were undulating") == 0

    def test_a_connector_that_raises_outright_draws_nothing(self, brain):
        ear = _ear(brain, lexicon_enabled=True)
        ear.lexicon._define = lambda w: (_ for _ in ()).throw(RuntimeError("x"))
        assert ear.lexicon.note_transcript("the fields were undulating") == 0

    def test_a_card_builder_failure_never_reaches_the_caller(self, brain, monkeypatch):
        ear = _ear(brain, lexicon_enabled=True)
        monkeypatch.setattr(cards, "lexicon",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
        assert ear.lexicon.note_transcript("the fields were undulating") == 0


# ---------------------------------------------------------------------------
# The three gates. Each asserts the card AND the egress, separately.
# ---------------------------------------------------------------------------

class TestTheVeilAndTheEgressShield:

    def test_the_veil_suppresses_both_the_card_and_the_lookup(self, brain):
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        drawn = _drawn(brain)
        brain.incognito_now = lambda: True             # type: ignore[method-assign]
        ear.ingest_caption("the fields were undulating")
        assert drawn == [], "a card was drawn under the Veil"
        assert fetch.calls == 0, "a word left the device under the Veil"

    def test_the_lan_only_posture_is_the_egress_shield_and_stops_the_lookup(self, brain):
        """Brain-side, the Veil and the egress shield are ONE signal:
        `incognito_now()` is True while LAN-only, in quiet hours, or inside a
        private zone (`server.py`). So this is the shield's own term, asserted
        through the real posture rather than through a stubbed method."""
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True, network_mode="lan_only")
        drawn = _drawn(brain)
        assert brain.incognito_now() is True
        ear.ingest_caption("the fields were undulating")
        assert drawn == [] and fetch.calls == 0

    def test_note_transcript_re_checks_the_veil_on_its_own(self, brain):
        """`ingest_caption` already returns while veiled. This is the second
        lock, for the caller that is not `ingest_caption` — the one path in the
        ear that can put a word on the network does not get to rely on someone
        else having checked."""
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        brain.incognito_now = lambda: True             # type: ignore[method-assign]
        assert ear.lexicon.note_transcript("the fields were undulating") == 0
        assert fetch.calls == 0

    def test_an_unreadable_posture_veils_rather_than_egresses(self, brain):
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        brain.incognito_now = lambda: (                # type: ignore[method-assign]
            _ for _ in ()).throw(RuntimeError("?"))
        assert ear.lexicon.note_transcript("the fields were undulating") == 0
        assert fetch.calls == 0

    def test_the_capture_veil_is_not_pierced_by_this_card(self, brain):
        """`veil_ok=False`: this card exists because of something the room said.
        Only a categorical safety alert pierces the shield."""
        src = pathlib.Path(LX.__file__).read_text(encoding="utf-8")
        push = src.split("def _draw(", 1)[1]
        assert 'push_event("lexicon", cards.lexicon(' in push
        assert "veil_ok=False)" in push


class TestFocusHushesIt:

    def test_focus_is_enforced_at_the_one_funnel(self):
        """Not a check of its own: `Brain.push_event` is where `focus_mode` is
        enforced for every live feed, and the codebase's stated reason for
        keeping it there is that a parallel mechanism is a second thing to keep
        in step."""
        assert "lexicon" in Brain.FOCUS_HUSHED

    def test_focus_draws_no_card(self, brain):
        ear = _ear(brain, lexicon_enabled=True, focus_mode=True)
        drawn = _drawn(brain)
        ear.ingest_caption("the fields were undulating")
        assert drawn == [], "Focus did not hush the definition"

    def test_focus_does_not_even_spend_the_request(self, brain):
        """The card is certain to be hushed, so asking the dictionary first
        would be egress with nothing on the other end. Read from the funnel's
        OWN predicate, so it cannot drift from `FOCUS_HUSHED`."""
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True, focus_mode=True)
        ear.ingest_caption("the fields were undulating")
        assert fetch.calls == 0

    def test_focus_still_does_not_stop_capture(self, brain):
        """The whole difference between Focus and the Veil, restated for this
        feature: the utterance is still heard and still stored."""
        brain.config.focus_mode = True
        brain.config.lexicon_enabled = True
        ear = _ear(brain, _Fetch())
        docs: list = []
        brain.index.add_documents = lambda pairs: docs.extend(pairs)  # type: ignore[assignment]
        ear.ingest_caption("the fields were undulating")
        assert ear.heard_count == 1
        assert any("undulating" in text for _n, text in docs)
        assert brain.incognito_now() is False, "Focus must not raise the shield"

    def test_an_unreadable_preference_fails_OPEN(self, brain):
        """A preference is about attention and fails open; the Veil is about the
        record and fails closed. Getting these backwards turns a privacy control
        into a reliability bug, or the reverse.

        The observable is the LOOKUP, not the card: this stub replaces the
        funnel's own predicate, so `push_event` — which calls it too, and whose
        real implementation has its own fail-open guard — is broken by the
        fixture rather than by the code under test. Reaching the lookup at all
        is what proves the early consult did not swallow the utterance."""
        fetch = _Fetch()
        ear = _ear(brain, fetch, lexicon_enabled=True)
        brain._may_interrupt = lambda kind: (          # type: ignore[method-assign]
            _ for _ in ()).throw(RuntimeError("?"))
        ear.lexicon.note_transcript("the fields were undulating")
        assert fetch.calls == 1, "an unreadable preference silenced the feature"

    def test_the_funnels_own_preference_check_fails_open_on_a_bad_config(self, brain):
        """…and the real mechanism, unstubbed: `Brain._may_interrupt` answers
        True when the config cannot be read at all."""
        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("config unreadable")

        brain.config = _Boom()                         # type: ignore[assignment]
        assert brain._may_interrupt("lexicon") is True
