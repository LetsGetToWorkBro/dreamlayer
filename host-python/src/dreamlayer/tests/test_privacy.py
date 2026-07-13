from dreamlayer.simulator import scenarios
from dreamlayer.memory.privacy import PrivacyGate
from dreamlayer.memory.proactive import ProactiveEngine
from dreamlayer.memory.db import MemoryDB


def test_pause_blocks_capture():
    orch, blocked = scenarios.privacy_pause()
    assert orch.privacy.paused is True
    assert blocked is None


def test_gate_logic():
    g = PrivacyGate()
    assert g.allow_capture() is True
    g.pause()
    assert g.allow_capture() is False
    g.resume()
    assert g.allow_capture() is True


def test_capture_vs_recall_gates():
    # The pinned two-veil contract, as one truth table:
    #   capture blocked by EITHER veil; recall blocked ONLY by pause.
    g = PrivacyGate()
    assert g.allow_capture() and g.allow_recall()          # both open

    g.set_incognito(True)
    assert not g.allow_capture()                           # incognito stops keeping
    assert g.allow_recall()                                # …but recall still works

    g.set_incognito(False)
    g.pause()
    assert not g.allow_capture() and not g.allow_recall()  # full veil: deaf+blind

    g.set_incognito(True)                                  # both down
    assert not g.allow_capture() and not g.allow_recall()
    g.resume()                                             # lift pause, incognito holds
    assert not g.allow_capture()                           # incognito still stops keeping
    assert g.allow_recall()                                # recall back


def test_paused_card_renders():
    orch, _ = scenarios.privacy_pause()
    assert orch.bridge.last_card["type"] == "PrivacyVeilCard"


def test_paused_card_text():
    orch, _ = scenarios.privacy_pause()
    c = orch.bridge.last_card
    assert c["primary"] == "Privacy Veil"
    assert "Nothing is being captured" in c["lines"]


def test_resume_allows_capture_again():
    orch, blocked, saved = scenarios.resume_after_pause()
    assert blocked is None
    assert saved is not None


def test_emulator_refuses_content_while_paused():
    from dreamlayer.bridge.emulator_bridge import EmulatorBridge
    b = EmulatorBridge()
    b.connect()
    b.inject_event("privacy_pause")
    b.send_card({"type": "ObjectRecallCard", "primary": "Keys"})
    assert b.last_card["type"] == "PrivacyVeilCard"


# ---------------------------------------------------------------------------
# NEW: proactive surfacing must be blocked while paused
# ---------------------------------------------------------------------------
def test_proactive_blocked_during_pause():
    """ProactiveEngine must return None when a paused PrivacyGate is supplied."""
    db = MemoryDB(":memory:")
    privacy = PrivacyGate()

    # Seed a high-confidence place memory
    pid = db.add_place("Office", "work_office")
    db.add_memory(
        "conversation",
        "You discussed the invoice",
        confidence=0.8,
        place_id=pid,
        meta={"person": "Jordan"},
    )

    engine = ProactiveEngine(db, privacy=privacy)

    # Sanity: not paused → should surface
    assert engine.on_place("work_office") is not None

    # Pause → must return None
    privacy.pause()
    assert engine.on_place("work_office") is None

    # Resume → surfaces again
    privacy.resume()
    assert engine.on_place("work_office") is not None


def test_orchestrator_on_place_blocked_during_pause():
    """orchestrator.on_place() must return None while paused."""
    _, card_before = scenarios.proactive_recall()
    assert card_before is not None

    # Build a fresh orch in the paused state
    import json
    from dreamlayer.simulator.scenarios import new_orch
    o = new_orch()
    o.bridge.connect()
    # Seed a proactive memory
    place_data = json.loads(open(
        __import__('os').path.join(
            __import__('os').path.dirname(__file__),
            "..", "simulator", "fixtures", "place_invoice_memory.json"
        )
    ).read())
    pid = o.db.add_place(place_data["place"]["name"], place_data["place"]["signature"])
    o.db.add_memory(
        "conversation", place_data["summary"],
        confidence=place_data["confidence"], place_id=pid,
        meta={"person": place_data["person"]},
    )
    # Pause, then trigger proactive
    o.pause()
    result = o.on_place(place_data["place"]["signature"])
    assert result is None


# Re-audit 2026-07: two recall surfaces bypassed the veil. Pin them shut.

def test_ask_is_veiled_during_pause():
    """orch.ask() is a recall surface — a full pause veil must block it, drawing
    the Privacy Veil card instead of recalling from memory."""
    from dreamlayer.simulator.scenarios import new_orch
    o = new_orch()
    o.bridge.connect()
    o.db.add_memory("object", "keys on the piano", confidence=0.9,
                    meta={"object": "Keys", "place": "piano"})
    # sanity: unpaused, ask recalls (some card that isn't the veil)
    assert o.ask("where are my keys").get("type") != "PrivacyVeilCard"
    o.pause()
    card = o.ask("where are my keys")
    assert card.get("type") == "PrivacyVeilCard"   # veiled, no recall drawn


def test_passive_tick_is_silent_during_pause():
    """The passive loop proactively surfaces memory — a full pause veil must
    silence it, or pre-pause hot-ring events keep being drawn while the wearer
    believes recall is off."""
    from dreamlayer.simulator.scenarios import new_orch
    from dreamlayer.pipelines.ingest import MemoryEvent
    o = new_orch()
    o.bridge.connect()
    ev = MemoryEvent(
        kind="object", summary="keys at kitchen counter", confidence=0.95,
        meta={"object": "Keys", "place": "Kitchen counter", "detail": ""},
        source="passive", db_id=99)
    # unpaused, this event would surface; paused, tick() must stay silent
    o.ring.append(ev)
    o.pause()
    assert o.tick() is None                         # nothing surfaced under the veil
