from __future__ import annotations
from ..memory.db import MemoryDB
from ..memory.retrieval import Retriever
from ..memory.proactive import ProactiveEngine
from ..memory.privacy import PrivacyGate
from ..memory.embeddings import MockEmbeddingProvider
from ..pipelines import vision, speech, extraction
from . import intents, answer_builder
from ..hud import cards


class Orchestrator:
    def __init__(self, bridge, db_path=":memory:"):
        self.bridge = bridge
        self.db = MemoryDB(db_path)
        self.embedder = MockEmbeddingProvider()
        self.retriever = Retriever(self.db, self.embedder)
        self.privacy = PrivacyGate()
        # Pass privacy gate into ProactiveEngine so it can honour pause state
        self.proactive = ProactiveEngine(self.db, privacy=self.privacy)
        bridge.on_event(self._on_event)

    def boot(self, lua_root):
        info = self.bridge.connect()
        self.bridge.load_lua_app(lua_root)
        self.bridge.send_command("show_ready")
        return info

    def ingest_scene(self, scene):
        if not self.privacy.allow_capture():
            return None
        mem = vision.extract_object_memory(scene)
        emb = self.embedder.embed(
            f"{mem['object']} {mem['place']} {mem['detail']}"
        )
        mid = self.db.add_memory(
            "object",
            f"{mem['object']} at {mem['place']}",
            embedding=emb,
            confidence=mem["confidence"],
            meta=mem,
        )
        self.bridge.send_card(
            cards.saved_memory(mem["object"]), event="memory_saved"
        )
        return mid

    def ingest_conversation(self, conv, place_id=None):
        if not self.privacy.allow_capture():
            return []
        parsed = speech.extract_conversation(conv)
        emb = self.embedder.embed(parsed["summary"])
        mid = self.db.add_memory(
            "conversation",
            parsed["summary"],
            embedding=emb,
            confidence=0.7,
            place_id=place_id,
            meta={"person": parsed["participants"][-1]
                  if parsed["participants"] else None},
        )
        return [
            self.db.add_commitment(
                c["person"], c["task"], c["due"], mid, c["confidence"]
            )
            for c in extraction.extract_commitments(conv)
        ]

    def ask(self, query):
        self.bridge.send_command("ask")
        intent = intents.classify(query)
        if intent["intent"] == "object_recall":
            card = answer_builder.build_object_answer(
                self.retriever.search(query, kind="object")
            )
        elif intent["intent"] == "commitment_recall":
            card = answer_builder.build_commitment_answer(
                self.db.commitments(person=intent.get("person"))
            )
        else:
            card = cards.low_confidence()
        self.bridge.send_card(card)
        return card

    def on_place(self, signature):
        # ProactiveEngine now enforces pause internally; double-checked here
        # so on_place is a safe no-op even if called while paused.
        if not self.privacy.allow_capture():
            return None
        p = self.proactive.on_place(signature)
        card = answer_builder.build_proactive(p)
        if card:
            self.bridge.send_card(card, event="proactive_trigger")
        return card

    def pause(self):
        self.privacy.pause()
        self.bridge.inject_event("privacy_pause")
        self.bridge.send_card(cards.privacy_paused(), event="privacy_pause")

    def resume(self):
        self.privacy.resume()
        self.bridge.inject_event("privacy_resume")
        self.bridge.send_command("resume")

    def _on_event(self, name, payload):
        if name == "long_press":
            self.pause() if not self.privacy.paused else self.resume()
