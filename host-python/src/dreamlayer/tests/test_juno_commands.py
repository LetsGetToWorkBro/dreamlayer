"""test_juno_commands.py — "Hey Juno, *do* something" + Juno's voice.

Juno runs the device on command, answers questions from your brain, and
replies as text in its own DreamLayer persona.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.commands import parse_command
from dreamlayer.orchestrator import persona
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _replies(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "JunoReplyCard"]


# -- the command grammar ------------------------------------------------------

def test_parses_device_commands():
    assert parse_command("Hey Juno, turn on focus").kind == "focus"
    assert parse_command("turn off focus").args["on"] is False
    assert parse_command("go incognito").kind == "incognito"
    assert parse_command("turn off captions") == parse_command("hide captions")
    assert parse_command("rewind my day").kind == "rewind"
    assert parse_command("sync my calendar").args["what"] == "calendar"
    assert parse_command("remind me to call the plumber").args["title"] == "call the plumber"
    assert parse_command("what's my level").kind == "saga"


def test_a_question_is_not_a_command():
    assert parse_command("what did Marcus need?") is None
    assert parse_command("who painted Guernica") is None


# -- Juno runs the device ---------------------------------------------------

def test_juno_executes_a_local_switch_and_confirms():
    br = FakeBridge()
    orc = Orchestrator(br)
    out = orc.ask_juno("turn on focus")
    assert out["intent"] == "focus" and out["executed"] is True
    assert orc.focus_active()                             # it actually happened
    assert _replies(br)[-1]["primary"] == persona.confirm("focus_on")


def test_juno_toggles_incognito_and_rewind():
    orc = Orchestrator(FakeBridge())
    assert orc.ask_juno("go incognito")["executed"] and orc.incognito
    assert orc.ask_juno("rewind my day")["intent"] == "rewind"


def test_cross_device_command_comes_back_as_an_intent():
    orc = Orchestrator(FakeBridge())
    out = orc.ask_juno("sync my contacts")
    assert out["intent"] == "sync" and out["executed"] is False   # app relays to the Brain
    assert "contacts" in out["text"]


# -- Juno answers, in voice -------------------------------------------------

def test_a_question_gets_an_answer_card_in_persona():
    br = FakeBridge()
    orc = Orchestrator(br)
    out = orc.ask_juno("what did Marcus need?")
    assert out["intent"] == "recall"
    assert _replies(br)[-1]["type"] == "JunoReplyCard"          # answered as text


def test_hey_juno_wakes_then_runs_the_command():
    br = FakeBridge()
    orc = Orchestrator(br)
    out = orc.hear("Hey Juno, turn on focus")
    assert out["intent"] == "focus" and orc.focus_active()
    kinds = [c["type"] for c in br.raw if c.get("t") == "card"]
    assert "ListeningCard" in kinds and "JunoReplyCard" in kinds


# -- the persona itself -------------------------------------------------------

def test_persona_lines_are_in_character():
    assert "Focus" in persona.confirm("focus_on")
    assert persona.confirm("sync", what="calendar") == "Syncing your calendar."
    assert persona.frame("") == persona.dunno()              # honest miss, never silent
    assert persona.frame("The lease is due Friday.") == "The lease is due Friday."
    assert "Juno" in persona.PERSONA_PROMPT
