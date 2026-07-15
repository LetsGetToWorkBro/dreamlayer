from __future__ import annotations
import os, json
from ..orchestrator.orchestrator import Orchestrator
from ..bridge.emulator_bridge import EmulatorBridge

FX = os.path.join(os.path.dirname(__file__), "fixtures")

def _load(name):
    # `with` so the fixture file descriptor is closed, not leaked (the bare
    # json.load(open(...)) left it dangling until GC).
    with open(os.path.join(FX, name)) as f:
        return json.load(f)

def new_orch():
    return Orchestrator(EmulatorBridge(), db_path=":memory:")

def object_recall():
    o = new_orch(); o.bridge.connect()
    o.ingest_scene(_load("object_keys_scene.json"))
    return o, o.ask("where did I leave my keys")

def commitment_recall():
    o = new_orch(); o.bridge.connect()
    o.ingest_conversation(_load("conversation_invoice.json"))
    return o, o.ask("what did I promise Jordan")

def proactive_recall():
    o = new_orch(); o.bridge.connect()
    place = _load("place_invoice_memory.json")
    pid = o.db.add_place(place["place"]["name"], place["place"]["signature"])
    o.db.add_memory("conversation", place["summary"], confidence=place["confidence"],
                    place_id=pid, meta={"person": place["person"]})
    return o, o.on_place(place["place"]["signature"])

def privacy_pause():
    o = new_orch(); o.bridge.connect()
    o.pause()
    blocked = o.ingest_scene(_load("object_keys_scene.json"))
    return o, blocked

def object_wallet():
    o = new_orch(); o.bridge.connect()
    o.ingest_scene(_load("object_wallet_scene.json"))
    return o, o.ask("where is my wallet")

def object_glasses():
    o = new_orch(); o.bridge.connect()
    o.ingest_scene(_load("object_glasses_scene.json"))
    return o, o.ask("where are my glasses")

def commitment_multi():
    o = new_orch(); o.bridge.connect()
    o.ingest_conversation(_load("conversation_invoice.json"))
    o.ingest_conversation(_load("conversation_deal.json"))
    return o, o.ask("what did I promise Marcus")

def commitment_multi_person():
    o = new_orch(); o.bridge.connect()
    o.ingest_conversation(_load("conversation_multicommit.json"))
    return o, o.ask("what did I promise Sofia")

def proactive_coffeeshop():
    o = new_orch(); o.bridge.connect()
    place = _load("place_coffeeshop_memory.json")
    pid = o.db.add_place(place["place"]["name"], place["place"]["signature"])
    o.db.add_memory("conversation", place["summary"], confidence=place["confidence"],
                    place_id=pid, meta={"person": place["person"]})
    return o, o.on_place(place["place"]["signature"])

def proactive_gym():
    o = new_orch(); o.bridge.connect()
    place = _load("place_gym_memory.json")
    pid = o.db.add_place(place["place"]["name"], place["place"]["signature"])
    o.db.add_memory("conversation", place["summary"], confidence=place["confidence"],
                    place_id=pid, meta={"person": place["person"]})
    return o, o.on_place(place["place"]["signature"])

def low_confidence_recall():
    o = new_orch(); o.bridge.connect()
    o.ingest_scene(_load("object_lowconf_scene.json"))
    return o, o.ask("where is my bag")

def no_memory_recall():
    o = new_orch(); o.bridge.connect()
    return o, o.ask("where are my keys")

def resume_after_pause():
    o = new_orch(); o.bridge.connect()
    o.pause()
    blocked = o.ingest_scene(_load("object_keys_scene.json"))
    o.resume()
    saved = o.ingest_scene(_load("object_wallet_scene.json"))
    return o, blocked, saved

def unknown_query():
    o = new_orch(); o.bridge.connect()
    return o, o.ask("what is the weather today")
