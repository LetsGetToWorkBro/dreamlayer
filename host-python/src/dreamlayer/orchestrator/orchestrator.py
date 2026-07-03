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


def _default_http_get(url: str, token: str = "") -> dict:
    """Minimal GET the message poller uses to reach the paired Mac mini Brain."""
    import json
    import urllib.request
    headers = {"X-DreamLayer-Token": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


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
        # AI brain (docs/AI_BRAIN.md): three independent switches, not one dial.
        #   • the phone is the brain by default (on-device, works anywhere);
        #     connect_mac_mini() upgrades it with a bigger local brain + your
        #     files when your Mac mini is reachable.
        #   • use_cloud() is its own switch — cloud reach for the hardest,
        #     non-personal asks, on in any brain. On by default (best answer
        #     wherever you are); nothing private ever leaves regardless.
        #   • set_incognito() is the privacy shield — forces cloud off and
        #     pauses capture for the session (replaces the old "home" mode).
        self.brain = BrainRouter(cloud_opt_in=True, local_only=True)
        self._cloud_pref = True               # remembered across incognito
        self.mac_mini_connected = False       # phone is the brain until paired
        self.incognito = False
        self.glasses_id = None                # set at pairing
        # Live message pop-ups: a text/email arriving flashes on the glasses.
        # The Mac mini Brain is the bridge (that's where Messages/Mail live);
        # poll_messages() turns new *incoming* ones into HUD cards. Texts and
        # emails are separate toggles (texts are the useful default; emails run
        # long, so the Brain can pre-summarize them). Silenced by the Veil.
        self.notify_texts = True
        self.notify_emails = True
        self._msg_seen_ts = 0.0
        self.brain_url = ""                    # set at pairing (the Mac mini)
        self.brain_token = ""
        self._msg_poll_stop = None
        # Anticipation engine: the right card at the right moment, unasked —
        # place + time + person tied into one ranked moment, deduped, veil-gated.
        # (Distinct from self.proactive, which fires place-signature triggers.)
        from .anticipation import AnticipationEngine
        self.anticipation = AnticipationEngine()
        self.anticipation_on = True             # proactive cards toggle
        # Conversation ledger: transcribed speech (a device seam) becomes live
        # captions, day-recall ("what did they say about X"), a rewind-my-day
        # timeline, and a person dossier on greeting. Never raw audio; Veil-gated.
        from .conversation import ConversationLedger
        self.conversation = ConversationLedger()
        self.captions_on = True                 # show live captions on the glasses
        # Social Lens: look at someone you've met → their name + context, matched
        # on-device against your own contacts (never a stranger lookup). Mounted
        # here so look_at_person() can pair a face match with the conversation
        # dossier. Starts empty; Contacts sync fills it.
        from ..social_lens import SocialLens
        self.social = SocialLens(privacy=self.privacy)
        # Focus mode: a stretch with the interruptions turned down (anticipation,
        # captions, message pop-ups). Distinct from Incognito — capture keeps
        # running. 0 = off; set_focus(minutes) arms it.
        self.focus_until = 0.0
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

    def look_at_object(self, frame, now: float | None = None, facet=None):
        """Oracle (Object Lens): recognise the object and surface its panel.

        facet picks the intent — None = everything; "own" = your own facts
        (private, instant glance); "ai" = let an AI explain/translate it;
        "shop" = prices & reviews. Veil-gated; objects only (people are
        Social Lens)."""
        facets = {facet} if facet else None
        panel = self.object_lens.look(frame, now=now, facets=facets)
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

    # -- the three brain switches ---------------------------------------

    def connect_mac_mini(self, connected: bool = True) -> None:
        """Add (or drop) your Mac mini as the local brain. When connected the
        router uses its bigger local model + your indexed files; when not, the
        phone is the brain (on-device only, more limited but works anywhere)."""
        self.mac_mini_connected = connected
        self.brain.set_local_only(not connected)

    def use_cloud(self, on: bool = True) -> None:
        """The cloud switch — reach for the hardest, non-personal asks. Its own
        control, independent of where the local brain lives; remembered across
        incognito. No-op on the router while incognito holds cloud off."""
        self._cloud_pref = on
        if not self.incognito:
            self.brain.opt_in_cloud(on)

    def set_incognito(self, on: bool = True) -> None:
        """Privacy shield for a session: forces the cloud off (restoring your
        preference when you leave) and marks the session private. Capture is
        paused at the app layer. Replaces the old 'home'/private mode."""
        self.incognito = on
        self.brain.opt_in_cloud(False if on else self._cloud_pref)

    def brain_status(self) -> dict:
        """A compact snapshot for the phone app / panel to render."""
        return {
            "brain":     "mac_mini" if self.mac_mini_connected else "phone",
            "cloud":     bool(self.brain.cloud_opt_in),
            "incognito": self.incognito,
            "glasses":   bool(self.glasses_id),
        }

    # -- live message pop-ups (texts/emails flash on the glasses) --------

    def set_message_notifications(self, on: bool = True) -> None:
        """Both channels at once (convenience)."""
        self.notify_texts = self.notify_emails = on

    def set_text_notifications(self, on: bool = True) -> None:
        self.notify_texts = on

    def set_email_notifications(self, on: bool = True) -> None:
        self.notify_emails = on

    def poll_messages(self, items: list, now: float | None = None) -> list:
        """Turn newly-arrived *incoming* messages into glasses pop-ups.

        `items` is the Brain's recent-messages feed (fetched by the hub from
        /dreamlayer/messages/recent). Only messages newer than the last seen,
        and not sent by you, pop up — texts and emails gated separately, each
        silenced by the Privacy Veil. Emails use the Brain's `summary` when it
        provided one (they run long). Returns the cards it flashed. Idempotent:
        re-polling the same feed shows nothing new.
        """
        cards_sent = []
        newest = self._msg_seen_ts
        for m in sorted(items, key=lambda x: x.get("ts", 0)):
            ts = m.get("ts", 0)
            if ts <= self._msg_seen_ts or m.get("from_me"):
                newest = max(newest, ts)
                continue
            newest = max(newest, ts)
            is_email = m.get("channel") == "email"
            if not (self.notify_emails if is_email else self.notify_texts):
                continue
            if not self.privacy.allow_capture() or self.focus_active():
                continue
            if is_email:
                body = m.get("summary") or (f"{m['subject']} — {m.get('text','')}"
                                            if m.get("subject") else m.get("text", ""))
            else:
                body = m.get("text", "")
            card = cards.message_notification(m.get("who", ""), body,
                                              m.get("channel", "imessage"))
            self.bridge.send_card(card, event="message")
            cards_sent.append(card)
        self._msg_seen_ts = newest
        return cards_sent

    def poll_messages_once(self, http_get=None) -> list:
        """Fetch the Brain's message feed once and flash anything new. A no-op
        with no Mac mini paired (there's no message source without it — iOS
        can't read your texts, so the Mac is the bridge)."""
        if not self.mac_mini_connected or not self.brain_url:
            return []
        getter = http_get or _default_http_get
        try:
            data = getter(self.brain_url.rstrip("/") + "/dreamlayer/messages/recent",
                          self.brain_token)
        except Exception:
            return []
        items = data.get("items", []) if isinstance(data, dict) else []
        return self.poll_messages(items)

    def start_message_polling(self, interval: float = 8.0, http_get=None) -> None:
        """Run poll_messages_once() on a background timer so pop-ups fire on
        their own. Idempotent; stop with stop_message_polling()."""
        if self._msg_poll_stop is not None:
            return
        import threading
        self._msg_poll_stop = threading.Event()

        def loop():
            while not self._msg_poll_stop.wait(interval):
                try:
                    self.poll_messages_once(http_get)
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop_message_polling(self) -> None:
        if self._msg_poll_stop is not None:
            self._msg_poll_stop.set()
            self._msg_poll_stop = None

    def set_anticipation(self, on: bool = True) -> None:
        self.anticipation_on = on

    def set_cue(self, kind: str, on: bool = True) -> None:
        """Toggle one proactive-cue kind (event / person / place) — the app's
        cue picker. Off kinds simply don't surface."""
        self.anticipation.set_kind(kind, on)

    def cue_kinds(self) -> dict:
        """Which cue kinds are on right now (for the app's picker state)."""
        return {k: (k in self.anticipation.enabled_kinds)
                for k in self.anticipation.KINDS}

    # -- focus mode: a stretch with the interruptions turned down --------
    # Distinct from Incognito (which pauses *capture*): focus keeps capturing
    # and answering you, but holds back the unasked stuff — anticipatory cards,
    # live captions, and message pop-ups — for a set number of minutes.

    def set_focus(self, minutes: float = 25.0) -> float:
        import time
        self.focus_until = time.time() + max(0.0, minutes) * 60.0
        return self.focus_until

    def clear_focus(self) -> None:
        self.focus_until = 0.0

    def focus_active(self, now: float | None = None) -> bool:
        import time
        return (now if now is not None else time.time()) < getattr(self, "focus_until", 0.0)

    def anticipate_tick(self, context) -> list:
        """Surface the right anticipatory cards for this moment. Silenced by
        the Privacy Veil and by Focus mode; the engine itself de-dupes so
        nothing nags. Returns the cues it flashed."""
        if (not self.anticipation_on or not self.privacy.allow_capture()
                or self.focus_active()):
            return []
        cues = self.anticipation.tick(context)
        for c in cues:
            self.bridge.send_card(c.card, event="anticipate")
        return cues

    def handle_voice(self, text: str) -> dict:
        """Route a spoken (already-transcribed) line to an intent. 'Ask/recall'
        run straight through to the brain and return the answer; the rest come
        back as a structured intent for the hub to execute (reply, locate,
        brief, missed). The mic + speech-to-text is a device seam."""
        from .voice import parse_intent
        it = parse_intent(text)
        if it.kind in ("ask", "recall"):
            ans = None
            try:
                ans = self.ask_brain(it.args.get("query", ""))
            except Exception:
                ans = None
            return {"intent": it.kind, "query": it.args.get("query", ""),
                    "answer": ans.text if ans is not None else ""}
        return {"intent": it.kind, **it.args}

    # -- conversation ledger: captions, recall, rewind, dossier ----------

    def set_captions(self, on: bool = True) -> None:
        self.captions_on = on

    def ingest_caption(self, text: str, speaker: str = "",
                       ts: float | None = None, show: bool = True):
        """Record one transcribed line (device seam) and, unless captions are
        off, flash it on the glasses. Veil-gated: nothing is kept or shown while
        capture is paused / incognito. Returns the stored Utterance or None."""
        if not self.privacy.allow_capture():
            return None
        u = self.conversation.add(text, speaker, ts)
        if (u is not None and show and self.captions_on
                and not self.focus_active()):
            self.bridge.send_card(
                cards.spoken_caption(u.speaker, u.text), event="caption")
        # a promise you just made becomes a tracked commitment — feeds the
        # dossier, anticipation, and the quest/drift engine.
        if u is not None and u.is_mine():
            self._capture_commitment(u)
        return u

    def _capture_commitment(self, utterance) -> None:
        from .conversation import parse_commitment
        parsed = parse_commitment(utterance.text)
        if not parsed:
            return
        person = self.conversation.last_other_speaker() or "someone"
        try:
            self.db.add_commitment(person, parsed["task"], parsed.get("due") or None,
                                   None, 0.7)
        except Exception:
            pass
        if not self.focus_active():
            self.bridge.send_card(
                cards.commitment_recall({"person": person, "task": parsed["task"],
                                         "due": parsed.get("due", ""), "confidence": 0.7}),
                event="commitment_captured")

    def live_captions(self, n: int = 6) -> list:
        """The last few utterances, oldest→newest, for the caption strip."""
        return self.conversation.captions(n)

    def recall_conversation(self, topic: str, person: str | None = None,
                            limit: int = 8) -> list:
        """'What did they say about X?' — user-initiated, so not Veil-gated."""
        return self.conversation.recall(topic, person, limit)

    def rewind_day(self, now: float | None = None) -> list:
        """A digest of today's conversation, grouped into hour blocks."""
        import time
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
        return self.conversation.timeline(day_start, day_start + 86400)

    def greet(self, person: str, now: float | None = None):
        """Surface a dossier the moment you greet someone the ledger knows.
        Proactive, so Veil-gated. Returns the card sent, or None if unknown or
        silenced."""
        if not self.privacy.allow_capture():
            return None
        d = self.conversation.dossier(person, now)
        if not d.get("known"):
            return None
        card = cards.person_dossier(d)
        self.bridge.send_card(card, event="greet")
        return card

    def load_contact_faces(self, contacts, face_embed_fn=None) -> int:
        """Fan Contacts sync into the on-device face database. Each contact needs
        a 512-d embedding: either supplied on the record, or produced from its
        photo by `face_embed_fn(photo) -> list[float]` (the device seam). Returns
        how many faces were enrolled. Contacts without a usable face are skipped
        (they still live in the Brain's People registry)."""
        from ..social_lens.schema import ContactRecord
        n = 0
        for c in contacts or []:
            name = c.get("name")
            emb = c.get("embedding")
            if emb is None and face_embed_fn is not None and c.get("photo") is not None:
                try:
                    emb = face_embed_fn(c["photo"])
                except Exception:
                    emb = None
            if not name or not emb or len(emb) != 512:
                continue
            try:
                self.social.add_contact(ContactRecord(
                    contact_id=c.get("contact_id", name), name=name, embedding=emb,
                    company=c.get("company"), role=c.get("role"), email=c.get("email")))
                n += 1
            except Exception:
                continue
        return n

    def look_at_person(self, frame, now: float | None = None) -> dict | None:
        """Look at someone → know them. Matches the face against your own
        contacts (on-device, never a stranger lookup) and, when it's someone
        the conversation ledger also knows, follows the identity card with the
        dossier (last spoke, recurring topics, what's open). Veil-gated by
        SocialLens itself. Returns what it surfaced, or None on no match."""
        res = self.social.identify(frame)
        if res is None or res.match is None:
            return None
        name = res.match.contact.name
        identity = res.to_hud_card()
        self.bridge.send_card(identity, event="social")
        out = {"person": name, "confidence": res.match.confidence,
               "identity": identity, "dossier": None}
        d = self.conversation.dossier(name, now)
        if d.get("known"):
            dossier = cards.person_dossier(d)
            self.bridge.send_card(dossier, event="greet")
            out["dossier"] = dossier
        return out

    # -- back-compat aliases (the model is the three switches above) -----

    @property
    def private_mode(self) -> bool:
        return self.incognito

    @property
    def brain_mode(self) -> str:
        if self.incognito:
            return "home"
        return "phone" if self.brain.local_only else "connected"

    def opt_in_cloud(self, on: bool = True) -> None:
        self.use_cloud(on)

    def set_private_mode(self, on: bool = True) -> None:
        self.set_incognito(on)

    def set_brain_mode(self, mode: str, cloud: bool | None = None) -> None:
        """Compat shim over the three switches:
          connected — Mac mini on, cloud on         (best answer wins)
          home      — Mac mini on, incognito         (private, no cloud)
          phone     — phone is the brain             (cloud per `cloud`)"""
        if mode not in ("connected", "home", "phone"):
            raise ValueError(f"unknown brain mode: {mode!r}")
        self.set_incognito(mode == "home")
        self.connect_mac_mini(mode != "phone")
        if cloud is not None:
            self.use_cloud(cloud)
        elif mode == "connected":
            self.use_cloud(True)

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
