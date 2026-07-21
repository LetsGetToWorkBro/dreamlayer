"""Consent-based recognition — the Social Lens's point: recognize the people you
have MET, defer only genuine strangers.

The old rule ("never identify anyone whose name we can read") was too broad — it
blocked recognizing someone you introduced. Now the person guard consults your
consented roster: a person you've met is allowed through, a stranger still
defers. Enrollment happens the moment someone is introduced.
"""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.object_lens import person_guard as pg
from dreamlayer.social_lens.introductions import parse_introduction

TOKEN = "wren-oak"


@pytest.fixture(autouse=True)
def _clean_roster():
    pg.set_known_people(None)          # start strict
    yield
    pg.set_known_people(None)          # never leak the roster into other tests


# --- the introduction parser -------------------------------------------------

class TestIntroductions:
    def test_common_forms_extract_the_name(self):
        assert parse_introduction("this is Sarah")["name"] == "Sarah"
        assert parse_introduction("I'd like you to meet Marcus")["name"] == "Marcus"
        assert parse_introduction("her name is Priya")["name"] == "Priya"
        assert parse_introduction("Hi, I'm David")["name"] == "David"
        assert parse_introduction("my name is Elena Ruiz")["name"] == "Elena Ruiz"
        assert parse_introduction("remember Tomás")["name"] == "Tomás"

    def test_trailing_context_becomes_a_note(self):
        p = parse_introduction("this is Sarah from marketing")
        assert p["name"] == "Sarah" and "marketing" in p["note"]

    def test_ordinary_speech_does_not_enroll(self):
        assert parse_introduction("I'm sorry about that") is None
        assert parse_introduction("this is great news") is None
        assert parse_introduction("meet me at noon") is None   # "me" is a stop word
        assert parse_introduction("") is None
        assert parse_introduction("where are my keys?") is None


# --- the consent-aware guard -------------------------------------------------

class TestGuardIsConsentAware:
    def test_full_known_name_is_allowed_not_deferred(self):
        pg.set_known_people(lambda: ["Sarah Chen", "Marcus"])
        assert pg.is_known_person("Sarah Chen") is True
        assert pg.defers_person("Sarah Chen") is False        # a person you MET
        assert pg.defers_person("Marcus") is False

    def test_a_stranger_still_defers(self):
        pg.set_known_people(lambda: ["Sarah Chen"])
        assert pg.defers_person("Bob Jones") is True          # not in your roster

    def test_a_shared_first_name_does_not_leak_a_stranger(self):
        # you know Sarah Chen; a different "Sarah Miller" must NOT be un-deferred
        pg.set_known_people(lambda: ["Sarah Chen"])
        assert pg.is_known_person("Sarah Miller") is False
        assert pg.defers_person("Sarah Miller") is True
        # a lone first name is ambiguous → still deferred (recognition leans on
        # face/voice, not a first-name badge)
        assert pg.is_known_person("Sarah") is False

    def test_rosterless_is_the_old_strict_behaviour(self):
        pg.set_known_people(None)
        assert pg.defers_person("Sarah Chen") is True         # every name defers
        assert pg.is_known_person("Sarah Chen") is False

    def test_a_raising_roster_never_breaks_a_look(self):
        def boom():
            raise RuntimeError("roster on fire")
        pg.set_known_people(boom)
        assert pg.is_known_person("Sarah Chen") is False       # fails safe
        assert pg.defers_person("Sarah Chen") is True


# --- the Brain: introduce → roster → recognition ------------------------------

def _brain(tmp_path) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN).save(d)
    return Brain(d)


class TestBrainEnrolment:
    def test_introduce_enrolls_and_known_names_updates(self, tmp_path):
        b = _brain(tmp_path)
        assert b.introduce("this is Sarah Chen from Acme") == {
            "name": "Sarah Chen", "note": "from Acme"}
        assert "Sarah Chen" in b.known_names()
        # and the guard (wired at Brain init to this roster) now recognizes her
        assert pg.defers_person("Sarah Chen") is False
        assert pg.defers_person("Some Stranger") is True

    def test_non_introduction_returns_none(self, tmp_path):
        b = _brain(tmp_path)
        assert b.introduce("what's the weather") is None

    def test_known_names_is_mtime_cached(self, tmp_path):
        b = _brain(tmp_path)
        b.introduce("this is Dana")
        first = b.known_names()
        assert "Dana" in first
        assert b.known_names() == first               # cached, same content


class TestAskEnrolls:
    def test_ask_endpoint_enrolls_on_introduction(self, tmp_path):
        b = _brain(tmp_path)
        server = make_brain_server(b, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            req = urllib.request.Request(
                base + "/dreamlayer/brain/ask",
                data=json.dumps({"query": "this is Priya"}).encode(),
                headers={"X-DreamLayer-Token": TOKEN,
                         "Content-Type": "application/json"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as r:
                out = json.loads(r.read())
            assert out.get("intent") == "introduce"
            assert "Priya" in out["text"]
            assert "Priya" in b.known_names()
        finally:
            server.shutdown(); server.server_close()
