from __future__ import annotations
import json
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
from .horizon_composer import HorizonComposer
from .time_scrub import TimeScrubSession
from .tell import TellEngine
from .consistency import ConsistencyEngine
from .provenance import ProvenanceLens
from .quest import QuestLog
from .waypath import WaypathLens
from ..object_lens import (
    ObjectLens, AIProvider, LabelProvider, RosettaProvider, DietaryProfile,
)
from ..ai_brain import BrainRouter
from ..rosetta import RosettaLens
from .state import HostState
from ..dream_mode import DreamEngine
from ..dream_mode.premonition import RecurrenceModel
from ..rem import RetrievalBias
from ..rem.nightly import NightWatch
from ..confluence.taps import TapCollector
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
        # On-device fact consistency (Candor) + belief genealogy (Provenance).
        self.consistency = ConsistencyEngine(self.ring)
        self.provenance = ProvenanceLens(self.ring)
        # AI brain (docs/AI_BRAIN.md): tiered vision + knowledge. Inert until
        # a tier is enabled (on-device / Mac mini / opt-in cloud), so it ships
        # off by default. Cloud is never crossed without opt_in_cloud().
        self.brain = BrainRouter()
        # Object Lens: look at a thing -> a contextual panel (objects, not
        # people). Ships with the memory provider + the (inert) AI explainer;
        # register integration seams (laptop/car/plant) at the app layer.
        self.object_lens = ObjectLens(ring=self.ring, privacy=self.privacy)
        self.object_lens.registry.register(AIProvider(self.brain))
        # Label (your own facts about a product) + Rosetta (translate seen text)
        self.dietary = DietaryProfile()
        self.rosetta = RosettaLens()          # translate_fn wired by the app
        self.object_lens.registry.register(LabelProvider(self.dietary, self.ring))
        self.object_lens.registry.register(RosettaProvider(self.rosetta))
        # Waypath: point-me-to-my-things from anchors
        self.waypath = WaypathLens()

        # REM: last night's verdicts brighten the morning; Premonition:
        # future ghosts. Both feed the composer; both are inert when empty.
        vault_dir = getattr(cfg, "vault_dir", None)
        # Life Quest Engine: Commitment Drift, told as a personal RPG.
        self.quest = QuestLog(self.drift_engine, vault_dir=vault_dir)
        self.rem_bias = (RetrievalBias.load(vault_dir) if vault_dir
                         else RetrievalBias())
        self.nightwatch = NightWatch(vault_dir) if vault_dir else None
        self.premonition = RecurrenceModel()
        self._premonition_seen_ts = 0.0

        # Meridian: the Horizon Frame composer (docs/cinema_v2/horizon_frame.md)
        self.horizon = HorizonComposer(self.ring, self.drift_engine,
                                       rem=self.rem_bias,
                                       premonition=self.premonition)

        # Dream Mode engine (starts stopped; activated on double_tap)
        self.dream = DreamEngine(
            bridge=bridge,
            db=self.db,
            privacy=self.privacy,
        )

        # Confluence: attached by the app layer when a bond goes live
        self.bonds = None
        self.tincan = None
        self.tap_collector = TapCollector()
        self.confluence_outbox: list[dict] = []

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
        """Drive passive event injection (~4 Hz) and the Horizon Frame
        stream (rate-limited inside the composer)."""
        self._premonition_sweep()
        self._tincan_sweep()
        self.tick_horizon()
        return self.passive.tick()

    def _premonition_sweep(self) -> None:
        """New ring events teach (and confirm) the recurrence model —
        a landed event hardens any ghost that predicted it."""
        newest = self._premonition_seen_ts
        for buffered in self.ring.since(self._premonition_seen_ts + 1e-6):
            ev = buffered.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue
            self.premonition.confirm(getattr(ev, "kind", "memory"),
                                     getattr(ev, "summary", ""),
                                     buffered.ts, meta.get("place"))
            newest = max(newest, buffered.ts)
        self._premonition_seen_ts = newest

    def _tincan_sweep(self) -> None:
        """A finished tap pattern becomes a ping for the bonded peer.
        The app layer drains confluence_outbox to the peer's phone."""
        if self.tincan is None:
            return
        pattern = self.tap_collector.tick()
        if pattern:
            wire = self.tincan.compose(pattern)
            if wire:
                self.confluence_outbox.append(wire)

    # ------------------------------------------------------------------
    # Confluence (two-wearer) plumbing
    # ------------------------------------------------------------------

    def attach_confluence(self, bonds, sky) -> None:
        """A bond went live: entangle the sky and arm the tin can."""
        from ..confluence import TinCan
        self.bonds = bonds
        self.tincan = TinCan(bonds)
        self.dream.confluence = sky

    def detach_confluence(self) -> None:
        self.bonds = None
        self.tincan = None
        self.dream.confluence = None

    def receive_confluence(self, wire: dict) -> None:
        """One entry point for everything the peer's phone sends."""
        from ..confluence import TinCan, unwrap_gift
        if self.bonds is None:
            return
        if "ping" in wire:
            if self.bonds.receive_weather(wire) is not None:
                self.bridge.send_raw(TinCan.render_frame(wire))
        elif "gift" in wire:
            for frame in unwrap_gift(self.bonds, wire):
                self.bridge.send_raw(frame)
        elif self.dream.confluence is not None:
            self.dream.confluence.receive(wire)

    def outgoing_weather(self) -> dict | None:
        """My weather packet for the peer this tick (app layer sends)."""
        if self.bonds is None:
            return None
        pkt = self.bonds.send_weather(self.dream.inner.state,
                                      self.dream.last_palette_colors)
        return pkt.to_wire() if pkt else None

    def on_speaker(self, speaker: str | None,
                   direction_deg: float | None = None) -> None:
        """The social/truth stack identified (or failed to identify) the
        current voice — Timbre renders it at the rim in Dream Mode."""
        self.dream._ctx.speaker = speaker
        if direction_deg is not None:
            self.dream._ctx.extra["voice_direction_deg"] = direction_deg

    def maybe_dream_tonight(self, charging: bool):
        """The NightWatch gate: run REM when charging at night, apply the
        verdicts to the durable bias the Horizon already reads."""
        if self.nightwatch is None:
            return None
        reel = self.nightwatch.maybe_run(charging, self.ring,
                                         drift=self.drift_engine,
                                         privacy=self.privacy)
        if reel is not None:
            self.rem_bias = RetrievalBias.load(self.nightwatch.vault_dir)
            self.horizon._rem = self.rem_bias
        return reel

    def tick_horizon(self, now: float | None = None) -> dict | None:
        """Compose and send the day-ring when due or changed. While
        privacy-paused only the empty pause frame flows — the absence of
        marks must be deliverable (docs/cinema_v2/horizon_frame.md)."""
        frame = self.horizon.maybe_frame(now, paused=self.privacy.paused)
        if frame is not None:
            self.bridge.send_raw(frame)
        return frame

    # ------------------------------------------------------------------
    # Commitment Drift
    # ------------------------------------------------------------------

    def nudge_commitment(self, subject: str, now: float | None = None):
        """Progress toward a commitment (heals it toward bloom)."""
        return self.drift_engine.nudge(subject, now=now)

    def keep_commitment(self, subject: str, now: float | None = None):
        """Mark a commitment kept — bloom and pin."""
        return self.drift_engine.keep(subject, now=now)

    def break_commitment(self, subject: str, now: float | None = None):
        """Mark a commitment broken — shatter and pin."""
        return self.drift_engine.break_(subject, now=now)

    # ------------------------------------------------------------------
    # Life Quest Engine (Commitment Drift as a personal RPG)
    # ------------------------------------------------------------------

    def quests(self, now: float | None = None):
        """Active commitments, seen as quests (most-imperilled first)."""
        return self.quest.quests(now=now)

    def complete_quest(self, subject: str, now: float | None = None):
        """Keep a commitment: award XP, extend the streak, surface a reward."""
        reward = self.quest.complete(subject, now=now)
        if reward is not None:
            self.bridge.send_card(reward.to_hud_card(), event="quest_complete")
        return reward

    def abandon_quest(self, subject: str, now: float | None = None) -> bool:
        return self.quest.abandon(subject, now=now)

    def quest_stats(self):
        return self.quest.stats()

    # ------------------------------------------------------------------
    # Instant Skill Overlay (a procedure compiled to a Figment)
    # ------------------------------------------------------------------

    def build_skill(self, name: str, text: str):
        """Compile a step list into a budget-verified Figment ready to deploy.
        Returns (figment, budget_report)."""
        from ..reality_compiler.v2 import compile_skill, parse_skill
        return compile_skill(name, parse_skill(text))

    # ------------------------------------------------------------------
    # On-device fact consistency
    # ------------------------------------------------------------------

    def check_consistency(self, claim: str, now: float | None = None):
        """Flag when a new statement contradicts your own recorded memories.
        Veil-gated; surfaces a card when it fires. Never touches the cloud."""
        if not self.privacy.allow_capture():
            return None
        result = self.consistency.check(claim, now=now)
        if result.fired:
            self.bridge.send_card(result.card, event="consistency")
        return result

    def trace_provenance(self, claim: str, now: float | None = None):
        """Provenance Lens: trace a belief to its origin and standing in your
        own memory. Veil-gated; surfaces a card when a source is found."""
        if not self.privacy.allow_capture():
            return None
        result = self.provenance.trace(claim, now=now)
        if result.found:
            self.bridge.send_card(result.card, event="provenance")
        return result

    def look_at_object(self, frame, now: float | None = None):
        """Object Lens: recognise the object in view and surface its
        contextual panel. Veil-gated; objects only (people are Social Lens)."""
        panel = self.object_lens.look(frame, now=now)
        if panel is not None:
            self.bridge.send_card(panel.to_hud_card(), event="object_panel")
        return panel

    def find_way(self, subject: str, heading_deg: float = 0.0):
        """Waypath Lens: where is my <thing> / where do I go, as a direction
        + distance from your own anchors. Veil-gated."""
        if not self.privacy.allow_capture():
            return None
        cue = self.waypath.locate(subject, heading_deg)
        card = self.waypath.to_hud_card(cue)
        if card is not None:
            self.bridge.send_card(card, event="waypath")
        return cue

    def translate_seen(self, text: str, target: str = "en"):
        """Rosetta Lens (the eye): translate text you look at. Puente is the
        ear (live voice translation)."""
        return self.rosetta.read(text, target=target)

    # ------------------------------------------------------------------
    # AI brain — knowledge queries (folds into Lucid Recall) + cloud gate
    # ------------------------------------------------------------------

    def ask_brain(self, query: str):
        """Ask your own knowledge (files/mail on the Mac mini brain). Returns
        an Answer, attributed to the tier that answered. Veil-gated."""
        if not self.privacy.allow_capture():
            return None
        answer = self.brain.ask(query)
        if answer is not None and not answer.is_empty():
            self.bridge.send_card(
                cards.answer_card(answer.text, sources=answer.sources,
                                  tier=answer.tier)
                if hasattr(cards, "answer_card") else
                {"type": "AnswerCard", "primary": answer.text,
                 "footer": f"{answer.tier} · {', '.join(answer.sources)}",
                 "lines": [answer.text]},
                event="brain_answer")
        return answer

    def opt_in_cloud(self, on: bool = True) -> None:
        """Allow cloud AI tiers for this session (off by default). Nothing
        crosses to the cloud until this is called."""
        self.brain.opt_in_cloud(on)

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
        source = None
        if intent["intent"] == "object_recall":
            scored = self.retriever.search(query, kind="object")
            card = answer_builder.build_object_answer(scored)
            if scored:
                source = scored[0][1]
        elif intent["intent"] == "commitment_recall":
            commits = self.db.commitments(person=intent.get("person"))
            card = answer_builder.build_commitment_answer(commits)
            if commits:
                source = commits[0]
        else:
            card = cards.low_confidence()
        # Meridian: answers condense from where they live in time — stamp
        # the Focus law's origin angle from the source memory's timestamp
        # (docs/cinema_v2/focus.md). No timestamp -> the card enters from
        # "now", which is the honest default.
        origin_ts = self._source_ts(source)
        if origin_ts is not None and card.get("type") in (
            "ObjectRecallCard", "CommitmentRecallCard"
        ):
            card["origin_deg"] = round(self.horizon.angle_for_ts(origin_ts), 1)
        self.bridge.send_card(card)
        return card

    @staticmethod
    def _source_ts(row) -> float | None:
        """Best-effort event timestamp from a memory/commitment row."""
        if not row:
            return None
        meta = row.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if isinstance(meta, dict) and meta.get("timestamp"):
            try:
                return float(meta["timestamp"])
            except (TypeError, ValueError):
                pass
        created = row.get("created_at")
        if created:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(str(created))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                pass
        return None

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
        # in Dream Mode with a live bond, single taps feed the tin can
        if name == "single_click" and self.state.is_dream() \
                and self.tincan is not None:
            self.tap_collector.collect("single")
            return
        if name == "long_press":
            self.pause() if not self.privacy.paused else self.resume()
        elif name == "double_tap":
            if self.state.is_dream():
                self.exit_dream()
            else:
                self.enter_dream()
