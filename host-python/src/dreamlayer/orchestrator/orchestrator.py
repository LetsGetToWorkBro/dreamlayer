from __future__ import annotations
import os
from ..memory.db import MemoryDB
from ..memory.retrieval import Retriever
from ..memory.proactive import ProactiveEngine
from ..memory.privacy import PrivacyGate
from ..memory.embeddings import MockEmbeddingProvider, OpenAIEmbeddingProvider
from ..memory.ring_buffer import SemanticRingBuffer
from ..pipelines import vision, speech
from ..pipelines.ingest import IngestPipeline
from ..pipelines.extraction import extract_commitments
from ..config import CONFIG
from .passive_capture import SilentCapture
from .passive_injector import PassiveEventInjector
from .commitment_drift import CommitmentDriftEngine
from .time_scrub import TimeScrubSession
from .tell import TellEngine
from .state import HostState
from ..dream_mode import DreamEngine
from . import intents, answer_builder
from ..hud import cards


class Orchestrator:
    def __init__(self, bridge, db_path=":memory:", config=None):
        cfg = config or CONFIG
        self.bridge = bridge
        self.db = MemoryDB(db_path)
        self.config = cfg
        self.state = HostState()

        if getattr(cfg, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
            self.embedder = OpenAIEmbeddingProvider(cfg)
        else:
            self.embedder = MockEmbeddingProvider()

        self.retriever = Retriever(self.db, self.embedder)
        self.privacy   = PrivacyGate()
        self.proactive = ProactiveEngine(self.db, privacy=self.privacy)

        if getattr(cfg, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
            self.pipeline = IngestPipeline.with_llm(self.db, cfg)
        else:
            self.pipeline = IngestPipeline(self.db)

        # Passive recall primitives
        self.ring = SemanticRingBuffer(cfg.passive_ring_capacity)
        self.silent_capture = SilentCapture(self, self.ring, self.privacy, cfg.capture_min_interval_ms)
        self.passive = PassiveEventInjector(self.bridge, self.ring, cfg.passive_min_confidence)

        # Drift / scrub / tell engines
        self.drift_engine = CommitmentDriftEngine(self.ring)
        self._scrub_session: TimeScrubSession | None = None
        self.tell_engine = TellEngine(self.ring)

        # Dream Mode engine (starts stopped; activated on double_tap)
        self.dream = DreamEngine(
            bridge=bridge,
            db=self.db,
            privacy=self.privacy,
        )

        # Wire vision pipeline into SceneDescriber if LLM available
        if getattr(cfg, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
            self.dream.describer.set_vision_fn(self._vision_describe)

        bridge.on_event(self._on_event)

    # ------------------------------------------------------------------
    # Vision fn for SceneDescriber (poetic 6-word VLM mode)
    # ------------------------------------------------------------------

    async def _vision_describe(self, jpeg_bytes: bytes, prompt: str) -> str:
        """Async vision callable wired into SceneDescriber.

        Calls the existing vision pipeline in poetic mode: returns a
        short evocative description rather than a structured memory.
        """
        try:
            result = await vision.describe_poetic(jpeg_bytes, prompt, config=self.config)
            return result
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self, lua_root):
        info = self.bridge.connect()
        self.bridge.load_lua_app(lua_root)
        self.bridge.send_command("show_ready")
        return info

    # ------------------------------------------------------------------
    # Dream Mode entry / exit
    # ------------------------------------------------------------------

    def enter_dream(self) -> None:
        """Switch to Dream Mode: start ambient engine, notify glasses."""
        self.state.enter_dream()
        self.dream.start()
        self.bridge.send_raw({"t": "dream_enter"})

    def exit_dream(self) -> None:
        """Return to Memory Mode: stop ambient engine, notify glasses."""
        self.dream.stop()
        self.dream.ghost.clear_cache()
        self.state.exit_dream()
        self.bridge.send_raw({"t": "dream_exit"})
        self.bridge.send_command("show_ready")

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_scene(self, scene):
        if not self.privacy.allow_capture():
            return None
        mem = vision.extract_object_memory(scene)
        emb = self.embedder.embed(f"{mem['object']} {mem['place']} {mem['detail']}")
        mid = self.db.add_memory(
            "object",
            f"{mem['object']} at {mem['place']}",
            embedding=emb,
            confidence=mem["confidence"],
            meta=mem,
        )
        self.bridge.send_card(cards.saved_memory(mem["object"]), event="memory_saved")
        return mid

    def ingest_conversation(self, conv, place_id=None, context=None):
        """Ingest a conversation via the three-tier NLP pipeline."""
        if not self.privacy.allow_capture():
            return []
        db_ids = []
        if isinstance(conv, str):
            transcript = conv
        else:
            parsed = speech.extract_conversation(conv)
            transcript = parsed.get("summary", "")
            emb = self.embedder.embed(transcript)
            conv_mid = self.db.add_memory(
                "conversation",
                transcript,
                embedding=emb,
                confidence=0.7,
                place_id=place_id,
                meta={"person": parsed["participants"][-1] if parsed.get("participants") else None},
            )
            db_ids.append(conv_mid)
            for c in extract_commitments(conv):
                cid = self.db.add_commitment(c["person"], c["task"], c["due"], conv_mid, c["confidence"])
                db_ids.append(cid)
        events = self.pipeline.ingest(transcript, context=context)
        import json as _json
        for ev in events:
            emb = self.embedder.embed(ev.summary)
            self.db.conn.execute("UPDATE memories SET embedding=? WHERE id=?", (_json.dumps(emb), ev.db_id))
            db_ids.append(ev.db_id)
        self.db.conn.commit()
        self.bridge.send_card(cards.saved_memory(""), event="memory_saved")
        return db_ids

    # ------------------------------------------------------------------
    # Passive entrypoints
    # ------------------------------------------------------------------

    def on_scene_frame(self, scene: dict, *, now_ms: int | None = None):
        """Process a scene frame — feeds Dream Mode if active."""
        if self.state.is_dream():
            jpeg = scene.get("camera_jpeg") or scene.get("camera_frame")
            if jpeg:
                self.dream.feed_camera(jpeg)
            imu_pose  = scene.get("imu_pose")
            imu_delta = scene.get("imu_delta")
            if imu_pose:
                self.dream.feed_imu(imu_pose, imu_delta or {})
        return self.silent_capture.capture_scene(scene, now_ms=now_ms)

    def on_audio_frame(self, transcript: str, *, context: dict | None = None, now_ms: int | None = None):
        """Process an audio frame — feeds mic data to Dream Mode if active."""
        if self.state.is_dream() and context:
            fft       = context.get("mic_fft")
            amplitude = context.get("mic_amplitude", 0.0)
            if fft is not None:
                self.dream.feed_mic(fft, float(amplitude))
        return self.silent_capture.capture_transcript(transcript, context=context, now_ms=now_ms)

    def tick(self) -> dict | None:
        """Drive passive event injection (~4 Hz)."""
        return self.passive.tick()

    # ------------------------------------------------------------------
    # Commitment Drift
    # ------------------------------------------------------------------

    def tick_drift(self, now: float | None = None) -> list[dict]:
        alert_records = self.drift_engine.tick(now=now)
        hud_cards = []
        for rec in alert_records:
            meta = rec.event.meta or {}
            card = cards.commitment_drift({
                "task":        rec.event.summary,
                "person":      meta.get("person", ""),
                "drift_state": rec.state,
                "decay":       rec.decay,
                "due":         meta.get("due", ""),
                "confidence":  rec.event.confidence,
            })
            self.bridge.send_card(card, event="drift_alert")
            hud_cards.append(card)
        return hud_cards

    # ------------------------------------------------------------------
    # Time-Scrub Halo
    # ------------------------------------------------------------------

    def start_scrub(self, lookback_s: float = 3600.0, now: float | None = None) -> dict | None:
        self._scrub_session = TimeScrubSession(self.ring, lookback_s=lookback_s, now=now)
        return self._scrub_session.current()

    def scrub(self, direction: str) -> dict | None:
        if self._scrub_session is None:
            return None
        if direction == "forward":
            return self._scrub_session.forward()
        return self._scrub_session.back()

    def scrub_select(self, index: int) -> dict | None:
        if self._scrub_session is None:
            return None
        return self._scrub_session.select(index)

    # ------------------------------------------------------------------
    # Tell
    # ------------------------------------------------------------------

    def tell_check(self, transcript: str, confidence: float = 0.80) -> dict | None:
        result = self.tell_engine.check(transcript, confidence=confidence)
        if result.fired and result.card:
            self.bridge.send_card(result.card, event="deviation_alert")
            return result.card
        return None

    # ------------------------------------------------------------------
    # Active recall
    # ------------------------------------------------------------------

    def ask(self, query):
        self.bridge.send_command("ask")
        intent = intents.classify(query)
        if intent["intent"] == "object_recall":
            card = answer_builder.build_object_answer(self.retriever.search(query, kind="object"))
        elif intent["intent"] == "commitment_recall":
            card = answer_builder.build_commitment_answer(self.db.commitments(person=intent.get("person")))
        else:
            card = cards.low_confidence()
        self.bridge.send_card(card)
        return card

    def on_place(self, signature):
        """Handle place signature match — feeds Dream Mode ghost layer if active."""
        if not self.privacy.allow_capture():
            return None
        p = self.proactive.on_place(signature)

        if self.state.is_dream():
            anchors = []
            if p:
                anchors = [{
                    "id":         str(getattr(p, "id", signature)),
                    "summary":    getattr(p, "summary",  ""),
                    "place":      getattr(p, "place",    ""),
                    "ts_label":   getattr(p, "ts_label", ""),
                    "confidence": getattr(p, "confidence", None),
                }]
            self.dream.feed_place(signature, anchors)
            return None

        card = answer_builder.build_proactive(p)
        if card:
            self.bridge.send_card(card, event="proactive_trigger")
        return card

    # ------------------------------------------------------------------
    # Privacy
    # ------------------------------------------------------------------

    def pause(self):
        self.privacy.pause()
        self.bridge.inject_event("privacy_pause")
        self.bridge.send_card(cards.privacy_veil(), event="privacy_pause")

    def resume(self):
        self.privacy.resume()
        self.bridge.inject_event("privacy_resume")
        self.bridge.send_command("resume")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _on_event(self, name, payload):
        if name == "long_press":
            self.pause() if not self.privacy.paused else self.resume()
        elif name == "double_tap":
            if self.state.is_dream():
                self.exit_dream()
            else:
                self.enter_dream()
