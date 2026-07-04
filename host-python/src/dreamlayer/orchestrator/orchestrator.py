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


def _default_http_post(url: str, body: dict, token: str = "") -> dict:
    """Minimal POST used to push the Oracle profile to the paired Mac mini Brain."""
    import json
    import urllib.request
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-DreamLayer-Token"] = token
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_scene_reply(text: str):
    """Parse a vision tier's one-line scene classification into a GlanceReading.
    Tolerant: 'SCENE: form — density=0.7 fields=4' and looser shapes both work."""
    import re
    from .glance import GlanceReading, SCENES
    t = (text or "").strip()
    m = re.search(r"scene\s*[:\-]?\s*([a-z_]+)", t, re.IGNORECASE)
    scene = (m.group(1).lower() if m else "")
    if scene not in SCENES:
        # fall back to the first known scene word anywhere in the reply
        scene = next((w for w in re.findall(r"[a-z_]+", t.lower()) if w in SCENES), "unknown")
    signals: dict = {}
    d = re.search(r"density\s*=\s*([0-9.]+)", t, re.IGNORECASE)
    if d:
        try: signals["text_density"] = float(d.group(1))
        except ValueError: pass
    f = re.search(r"fields?\s*=\s*(\d+)", t, re.IGNORECASE)
    if f:
        signals["form_fields"] = int(f.group(1))
    lg = re.search(r"lang\w*\s*=\s*([a-z\-]+)", t, re.IGNORECASE)
    if lg:
        signals["language"] = lg.group(1).lower()
    if re.search(r"question\s*=\s*(yes|true|1)", t, re.IGNORECASE) or "?" in t:
        signals["question"] = True
    conf = 0.8 if scene != "unknown" else 0.3
    return GlanceReading(scene, conf, signals)


def _parse_taste_reply(text: str):
    """Parse a vision tier's shelf/menu listing into TasteItems. Lenient about
    the 'NAME | ingredients | price | rating' shape: missing fields are fine,
    '?' means unknown, a bare '$3.20' or '4.6' anywhere in a field is picked up."""
    import re
    from .taste import TasteItem
    items = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if not line or line.startswith(("NAME", "http")):
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0].strip(" .")
        if not name or name == "?":
            continue
        text_field = parts[1] if len(parts) > 1 and parts[1] not in ("?", "") else ""
        price = rating = None
        rest = " ".join(parts[2:]) if len(parts) > 2 else ""
        pm = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", parts[2]) if len(parts) > 2 else None
        if pm:
            price = float(pm.group(1))
        rm = re.search(r"(\d(?:\.\d)?)\s*(?:/\s*5|★|stars?)?", parts[3]) if len(parts) > 3 else None
        if rm:
            try:
                r = float(rm.group(1))
                rating = r if 0 <= r <= 5 else None
            except ValueError:
                pass
        items.append(TasteItem(label=name, text=text_field, price=price, rating=rating))
    return items


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
        # Oracle — the assistant. "Hey Oracle" wakes it; tap / gaze / raise are
        # multimodal alternatives. On wake it shows a Listening ring + (device
        # seams) an earcon and a haptic tick, then stays open a short session so
        # follow-ups need no wake word.
        self.oracle_until = 0.0
        self.oracle_session_s = 20.0
        self.wake_sources = {"voice", "tap", "gaze", "raise"}
        self.wake_feedback = {"visual": True, "audio": True, "haptic": True}
        self._last_hark = -1e9                  # rate-limit Oracle's "Listen!"
        # Attention policy: decides *when* a moment is worth an audible "Listen!"
        # (a commitment slipping, someone you owe, something you left) or an
        # urgent "Watch out!" (leave now). Feeds hark(); never nags (per-key
        # cooldown + hark's pacing). Veil/Focus rules ride on hark.
        from .attention import AttentionPolicy
        self.attention = AttentionPolicy()
        self.attention_on = True                # proactive spoken alerts
        self._tick_stop = None                  # the proactive heartbeat loop
        # Veritas — the live fact-checker. As people talk, it flags when a
        # speaker contradicts their *own* earlier words (offline, from the
        # ledger) and hands checkable claims to the Brain/cloud to verify. Off by
        # default; opt-in per the wearer. World checks go through _verify_claim,
        # a seam that only reaches out when a Brain/cloud tier is available.
        from .veritas import Veritas
        self.veritas = Veritas(verify_fn=self._verify_claim)
        # WorldChecker keeps the world check off the caption hot path: a claim
        # already seen resolves from cache instantly; a new one runs on a
        # single background worker with a hard deadline. Self-contradiction is
        # the instant offline half; this is the fast-as-possible slow half.
        from ..ai_brain.world_check import WorldChecker
        self.world_check = WorldChecker(timeout_s=2.5)
        self.factcheck_on = False
        # Discernment: fuse Veritas (content) with Truth Lens (delivery, fed via
        # note_credibility) and the pattern of prior flags into one graded read.
        self._credibility: dict = {}           # speaker -> latest CredibilityVector
        self._speaker_flags: dict = {}         # speaker -> how often they've flagged
        # Truth Lens (delivery read): the linguistic channel is computed for real
        # from each caption; face (AU) + voice (prosody) are device seams fed via
        # observe_face / observe_voice. Its per-speaker CredibilityVector flows
        # into Discernment through note_credibility. Off by default.
        from ..truth_lens.analyzer import TruthLens
        self.truth = TruthLens(cooldown_s=0.0, privacy=self.privacy)
        self.truthlens_on = False
        # Answer-ahead — overhears a question aimed at you and surfaces the
        # answer from your own knowledge in time to say it yourself. No wake
        # word. Off by default; answers route through _answer_question (the same
        # knowledge tier the Oracle asks).
        from .answer_ahead import AnswerAhead
        self.answer_ahead = AnswerAhead(answer_fn=self._answer_question)
        self.copilot_on = False
        # User model — the Oracle learns you: the topics you return to, who you
        # talk with, what you tell it to remember, what to call you. Built
        # on-device from your own lines + explicit teaches; persisted beside the
        # vault (in-memory for an :memory: db). Feeds the persona's greeting and
        # can bias recall toward what you care about.
        from .user_model import UserModel
        um_path = None
        if db_path and db_path != ":memory:":
            um_path = os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".",
                                   "usermodel.json")
        self.user = UserModel(um_path)
        self._profile_dirty = 0                # debounce profile pushes to the Brain
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
        # Scholar: look at a test question and get the answer; look at a form and
        # get each field spelled out; look at dense legal/technical text and get
        # it in plain words. Reads through the Brain's vision tier (_scholar_read):
        # local model first, cloud only when opted in, never while incognito.
        from .scholar import Scholar
        self.scholar = Scholar(read_fn=self._scholar_read)
        # TasteLens: look at a whole shelf/menu → a ranked pick against your
        # rules (dietary vetoes, budget, rating, price). First-party lens; its
        # price/review data is pluggable (shop_fn, opt-in cloud). Reads the
        # shelf through the Brain's vision tier (_taste_read); ranks against
        # your DietaryProfile. shop_fn is wired by a shop plugin.
        from .taste import TasteLens
        # shop connectors (prices/reviews) plugins register here; TasteLens
        # consults them through _taste_shop. Off by default (empty).
        self._shop_providers: list = []
        self.taste_lens = TasteLens(read_fn=self._taste_read, profile=self.dietary,
                                    shop_fn=self._taste_shop)
        # Glance Arbiter: on a look, decide which lens owns it — fire the clear
        # winner, offer a one-tap chooser when ambiguous, or do nothing. No mode
        # picker; the look decides. Coarse on-device read first, escalating to
        # the Brain's vision only when the cheap read can't tell (two-tier).
        from .glance import GlanceArbiter
        # Learned priors persist beside the vault (same place, same pattern as
        # usermodel.json): read once here, rewritten on each pick. Local file =
        # source of truth, so a glance never waits on the Mac; in-memory for
        # an :memory: db.
        gp_path = None
        if db_path and db_path != ":memory:":
            gp_path = os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".",
                                   "glancepriors.json")
        self.glance_arbiter = GlanceArbiter(priors_path=gp_path)
        self._recent_glance_intent = ("", 0.0)   # (lens-hint, ts) from voice
        # device seam: cheap on-device cues for the coarse glance read (a face
        # flag, a text-density estimate, a detected form grid). None → the
        # coarse read draws from the Tier-0 PerceptionRouter below.
        self._glance_signals_fn = None
        # Tier 0 — on-glass perception. Heuristic today (no model, works
        # offline); on Halo the Ethos-U55 NPU plugs a Vela-compiled int8 model
        # into NpuPerceptor behind the same protocol. Feeds the Glance Arbiter's
        # coarse read and wake-word; a real model upgrades both with no change
        # upstream (add via self.perception.add_perceptor(NpuPerceptor(...))).
        from ..ai_brain import PerceptionRouter
        self.perception = PerceptionRouter()

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
        # GhostMode mesh (2+ wearers) + The Beacon: attached by the app layer
        # when a circle is formed. Same pattern as the pairwise bond above.
        self.mesh = None
        self.beacon = None
        # Plugins: the supported extension surface (docs/PLATFORM.md). None
        # until load_plugins() wires extensions (third-party or first-party)
        # into the object-lens / glance / brain / perception registries.
        self.plugins = None

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

    def _clock(self) -> float:
        import time
        return time.monotonic()

    def glance(self, frame, dwell_ms: float = 0.0, now: float | None = None):
        """The smart look: classify what's in view, let the lenses bid, and act.

        Fires the clear winner straight to the glasses; sends a one-tap chooser
        card when it's genuinely ambiguous; does nothing when nothing fits or
        the veil is down. This is the no-mode-picker entry point — the wearer
        just looks. Returns the GlanceDecision."""
        from .glance import GlanceContext, GlanceReading
        if not self.privacy.allow_capture():
            from .glance import GlanceDecision
            return GlanceDecision("none", GlanceReading())
        reading = self._classify_glance(frame)
        hint, hts = self._recent_glance_intent
        ctx = GlanceContext(
            recent_intent=hint if (self._clock() - hts) < 6.0 else "",
            user_language=getattr(self.config, "user_language", "en") or "en",
            dwell_ms=dwell_ms, focus=self.focus_active(),
            veiled=not self.privacy.allow_capture())
        decision = self.glance_arbiter.arbitrate(reading, ctx)
        if decision.kind == "fire" and decision.winner is not None:
            self._run_glance_action(decision.winner.action, frame,
                                    decision.winner.args)
        elif decision.kind == "offer" and decision.card is not None:
            self.bridge.send_card(decision.card, event="glance")
        return decision

    def choose_glance(self, action: str, frame, args: dict | None = None,
                      scene: str = ""):
        """Act on a chooser pick — and teach the arbiter that, for this kind of
        scene, this is the lens you want."""
        if scene and action:
            lens = {"scholar_answer": "scholar_answer", "scholar_form": "scholar_form",
                    "scholar_explain": "scholar_explain", "translate": "rosetta",
                    "oracle": "oracle", "person": "person"}.get(action, action)
            self.glance_arbiter.reinforce(scene, lens)
        return self._run_glance_action(action, frame, args or {})

    def _run_glance_action(self, action: str, frame, args: dict):
        """Route an arbiter action key to the lens that owns it."""
        if action == "scholar_answer":
            return self.read_answer(frame)
        if action == "scholar_form":
            return self.read_form(frame, purpose=args.get("purpose", ""))
        if action == "scholar_explain":
            return self.explain_text(frame)
        if action == "person":
            return self.look_at_person(frame)
        if action == "translate":
            return self.look_at_object(frame, facet="ai")
        if action == "taste":
            return self.taste(frame)
        return self.look_at_object(frame)     # oracle / default

    def _plugin_capabilities(self) -> frozenset:
        """What this host offers plugins right now — checked against each
        plugin's `requires` at load time (so a vision-needing plugin waits
        until a vision tier is present)."""
        caps = {"object_lens", "glance", "perception", "cards", "ring", "shop"}
        if getattr(self, "mesh", None) is not None:
            caps.add("mesh")
        # the hub can reach the internet unless the Veil / incognito is on
        try:
            if self.privacy.allow_capture():
                caps.add("network")
        except Exception:
            caps.add("network")
        try:
            if self.brain is not None and self.brain.has_vision():
                caps.add("vision")
        except Exception:
            pass
        return frozenset(caps)

    def plugin_context(self, renderer=None, config=None):
        """The narrow surface a plugin is handed, wired to this orchestrator's
        real registries."""
        from ..plugins import PluginContext
        return PluginContext(
            object_registry=self.object_lens.registry,
            glance_arbiter=self.glance_arbiter,
            brain=self.brain, perception=self.perception, renderer=renderer,
            capabilities=self._plugin_capabilities(),
            ring=self.ring, veil=self.privacy, mesh=self.mesh,
            shop_registry=self._shop_providers, config=config)

    def load_plugins(self, plugins, renderer=None, config=None):
        """Load a list of plugins into this orchestrator. Gated by capabilities,
        failures isolated. Returns a LoadResult (loaded / skipped / failed)."""
        from ..plugins import PluginRegistry
        reg = self.plugins or PluginRegistry(self.plugin_context(renderer, config))
        res = reg.load_all(plugins)
        self.plugins = reg
        return res

    def _classify_glance(self, frame):
        """Two-tier scene read. A coarse on-device read runs first (free, from
        cheap signals); when it can't tell a form from a question from prose,
        escalate to the Brain's vision tier for a fine read — spending the big
        model only when it changes the answer."""
        from .glance import classify_coarse, GlanceReading
        lang = getattr(self.config, "user_language", "en") or "en"
        signals = {}
        try:
            if self._glance_signals_fn is not None:
                signals = self._glance_signals_fn(frame) or {}
            else:
                # Tier 0: model-backed on the NPU, heuristic offline.
                signals = self.perception.perceive(frame).as_signals()
        except Exception:
            signals = {}
        reading = classify_coarse(signals, user_language=lang)
        if self.glance_arbiter.is_ambiguous(reading) and getattr(self, "brain", None):
            fine = self._glance_fine_read(frame)
            if fine is not None:
                return fine
        return reading

    def _glance_fine_read(self, frame):
        """Fine scene classification via the Brain's vision tier (Mac / cloud).
        Returns a GlanceReading or None. The vision model is the seam Ollama
        plugs into; offline this simply returns None and the coarse read stands."""
        from .glance import GlanceReading, SCENES
        prompt = ("Classify what is in this image for a glasses assistant. Reply "
                  "on one line: SCENE: <object|text|form|question|foreign_text|"
                  "person|screen> — then optional tags density=<0-1> "
                  "lang=<iso> fields=<n> question=<yes|no>. Nothing else.")
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return None
        return _parse_scene_reply(ans.text)

    def read_answer(self, frame, question: str = "", now: float | None = None):
        """Scholar: read the question in view and put the answer on the glass.
        Works for any subject; `question` optionally carries a spoken ask about
        what's in front of you. Veil-gated; sends a ScholarCard."""
        return self._scholar_send(self.scholar.answer(frame, question=question))

    def read_form(self, frame, purpose: str = "", now: float | None = None):
        """Scholar: read a form and say what to write in each field. `purpose`
        steers the guidance ("renew my passport", "claim the deduction")."""
        return self._scholar_send(self.scholar.form(frame, purpose=purpose))

    def explain_text(self, frame, now: float | None = None):
        """Scholar: summarize dense legal/technical text in plain words, flagging
        anything that commits you or carries risk."""
        return self._scholar_send(self.scholar.explain(frame))

    def _scholar_send(self, result):
        if result is not None and result.card is not None:
            self.bridge.send_card(result.card, event="scholar")
        return result

    def _scholar_read(self, frame, prompt: str):
        """Scholar's vision seam: read the text in a frame and reason about it,
        through the Brain's vision tier — local model first, cloud only when
        opted in, never while incognito. Falls back to the knowledge tier for a
        text-only reply, and returns None when nothing can read it (so Scholar
        shows an honest 'connect a Brain' card instead of guessing)."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            try:                              # no vision tier — try text knowledge
                ans = self.brain.ask(prompt)
            except Exception:
                ans = None
        if ans is None or ans.is_empty():
            return None
        return ans.text

    def taste(self, frame, budget: float | None = None, now: float | None = None):
        """TasteLens: look at a shelf/menu and put the ranked pick on the glass —
        dietary vetoes first, then budget, then rating/price. Veil-gated; sends a
        TasteCard. Reads through the Brain's vision tier; ranks against your
        DietaryProfile with a pluggable shop_fn for prices/reviews."""
        ranking = self.taste_lens.look(frame, budget=budget)
        card = cards.taste(ranking, unavailable=ranking.unavailable)
        self.bridge.send_card(card, event="taste")
        return ranking

    def _taste_shop(self, label, attrs):
        """TasteLens's price/review seam. Merges the registered shop-provider
        plugins (first provider wins per field); returns {} when none are
        installed. Each provider is isolated — one throwing doesn't sink the rest."""
        merged: dict = {}
        for fn in self._shop_providers:
            try:
                data = fn(label, attrs) or {}
            except Exception:
                continue
            for k, v in data.items():
                merged.setdefault(k, v)
        return merged

    def _taste_read(self, frame):
        """TasteLens's vision seam: read a shelf/menu into a list of items,
        through the Brain's vision tier — local first, cloud only when opted in,
        never while incognito. Returns [] when nothing can read it (so the card
        shows the honest 'connect a Brain' state)."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return []
        prompt = ("List the products or dishes in view for a shopping assistant, "
                  "one per line: NAME | ingredients | price | rating(0-5). "
                  "Use '?' for anything unknown. Nothing else.")
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return []
        return _parse_taste_reply(ans.text)

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

    # -- Oracle: wake word + multimodal activation + listening feedback --

    def set_wake_source(self, source: str, on: bool = True) -> None:
        """Enable/disable a way to wake Oracle (voice / tap / gaze / raise)."""
        if on:
            self.wake_sources.add(source)
        else:
            self.wake_sources.discard(source)

    def set_wake_feedback(self, kind: str, on: bool = True) -> None:
        """Toggle a listening cue (visual ring / audio earcon / haptic tick)."""
        if kind in self.wake_feedback:
            self.wake_feedback[kind] = on

    def oracle_listening(self, now: float | None = None) -> bool:
        import time
        return (now if now is not None else time.time()) < self.oracle_until

    def begin_listening(self, source: str = "voice", now: float | None = None):
        """Open Oracle's listening session and show the reassurance cue — a
        Listening ring plus (device seams) an earcon and a haptic tick, per the
        wake_feedback toggles. Returns the card."""
        import time
        now = now if now is not None else time.time()
        self.oracle_until = now + self.oracle_session_s
        fb = self.wake_feedback
        card = cards.listening(source, earcon=fb["audio"], haptic=fb["haptic"])
        if fb["visual"]:
            self.bridge.send_card(card, event="listening")
        return card

    def end_listening(self) -> None:
        self.oracle_until = 0.0

    def oracle_greeting(self) -> str:
        """Oracle's greeting, adapted to what it's learned — by name once it
        knows it. Warms on wake / first line of a session."""
        from . import persona
        return persona.greeting(self.user.address())

    def user_snapshot(self, n: int = 5) -> dict:
        """What the Oracle has learned about you — name, the topics you return
        to, who you talk with most, and what you've told it to remember. For the
        phone's profile screen; a read, never a write."""
        return self.user.snapshot(n).to_dict()

    def publish_profile(self, http_post=None) -> dict | None:
        """Push the Oracle profile to the paired Mac mini Brain (POST
        /dreamlayer/profile) so the phone can read it — the hub->Brain bridge.
        Best-effort and Veil-gated; silent with no Mac mini. `http_post` defaults
        to urllib."""
        if not self.privacy.allow_capture() or not self.brain_url:
            return None
        post = http_post or _default_http_post
        try:
            out = post(self.brain_url.rstrip("/") + "/dreamlayer/profile",
                       self.user_snapshot(), self.brain_token)
            self._profile_dirty = 0
            return out
        except Exception:
            return None

    def _maybe_publish_profile(self) -> None:
        """Debounced push: sync the profile once enough has changed, so a chatty
        day doesn't hammer the Brain. Explicit teaches push immediately."""
        self._profile_dirty += 1
        if self._profile_dirty >= 10:
            self.publish_profile()

    def activate(self, source: str, now: float | None = None):
        """Wake Oracle without a phrase — a tap, a gaze/dwell, or a raise-to-
        speak gesture (the device seam decides which). Enters listening if that
        source is enabled; returns the Listening card or None."""
        if source not in self.wake_sources:
            return None
        return self.begin_listening(source, now)

    def hear(self, text: str, now: float | None = None) -> dict:
        """The wake pipeline for a transcribed line (ASR is the device seam).

          • opens with "Hey Oracle" → wake, then run the command if one follows;
          • Oracle already listening (session window) → treat as a follow-up,
            no wake word needed (continuous-conversation mode);
          • otherwise → idle (Oracle wasn't addressed).
        Each command extends the session so a back-and-forth flows."""
        import time
        from .voice import detect_wake
        now = now if now is not None else time.time()
        heard, remainder = detect_wake(text)
        if heard:
            if "voice" not in self.wake_sources:
                return {"intent": "idle"}
            self.begin_listening("voice", now)
            if remainder:
                self.oracle_until = now + self.oracle_session_s
                return self.ask_oracle(remainder)
            return {"intent": "listening"}
        if self.oracle_listening(now):
            self.oracle_until = now + self.oracle_session_s     # follow-up extends
            return self.ask_oracle(text)
        return {"intent": "idle"}

    def ask_oracle(self, text: str) -> dict:
        """The full "Hey Oracle" surface: run a device command if it is one
        ("turn on focus", "go incognito", "rewind my day"), otherwise answer
        from your brain — device → Mac mini → cloud, so it can pull up anything
        about you or the wider world. Replies as text on the glasses in Oracle's
        own voice. Returns {intent, text, executed, ...}."""
        from .commands import parse_command
        from . import persona
        # first: is this you teaching Oracle about yourself? ("call me Sam",
        # "remember that I prefer aisle seats") — it learns and confirms.
        learned = self.user.learn(text)
        if learned is not None:
            if learned["kind"] == "name":
                line = persona.confirm("learned_name", name=learned["value"])
            else:
                line = persona.confirm("learned_pref")
            self.bridge.send_card(cards.oracle_reply(line, "action"), event="oracle")
            self.publish_profile()          # a teach is worth pushing right away
            return {"intent": "learn", "text": line, "executed": True,
                    "learned": learned}
        cmd = parse_command(text)
        if cmd is not None:
            line, executed, intent = self._run_command(cmd)
            self.bridge.send_card(cards.oracle_reply(line, "action"), event="oracle")
            return {"intent": intent, "text": line, "executed": executed}
        # not a command → knowledge / conversation. Your questions also reveal
        # what you care about, so the Oracle keeps learning as you ask.
        self.user.observe(text)
        res = self.handle_voice(text)
        kind = res.get("intent")
        if kind in ("ask", "recall"):
            line = persona.frame(res.get("answer", ""))
        elif kind == "reply":
            line = (f"Reply to {res.get('to', '')}: “{res.get('text', '')}” "
                    f"— open Messages to send.")
        elif kind == "brief":
            line = "Pulling up your brief."
        elif kind == "missed":
            line = "Here's what you missed."
        else:
            line = persona.dunno()
        self.bridge.send_card(cards.oracle_reply(line, "answer"), event="oracle")
        out = {"intent": kind, "text": line, "executed": False}
        out.update({k: v for k, v in res.items() if k not in ("intent", "answer")})
        return out

    def _run_command(self, cmd) -> tuple:
        """Execute a device Command; returns (in-voice line, executed?, intent).
        Local switches run here and now; cross-device ones (sync, remind, saga)
        come back as an intent the app completes on the Brain."""
        from . import persona
        k, on = cmd.kind, cmd.args.get("on", True)
        if k == "focus":
            (self.set_focus(25) if on else self.clear_focus())
            return persona.confirm("focus_on" if on else "focus_off"), True, "focus"
        if k == "incognito":
            self.set_incognito(on)
            return persona.confirm("incognito_on" if on else "incognito_off"), True, "incognito"
        if k == "captions":
            self.set_captions(on)
            return persona.confirm("captions_on" if on else "captions_off"), True, "captions"
        if k == "proactive":
            self.set_attention(on); self.set_anticipation(on)
            return persona.confirm("proactive_on" if on else "proactive_off"), True, "proactive"
        if k == "cloud":
            self.use_cloud(on)
            return persona.confirm("cloud_on" if on else "cloud_off"), True, "cloud"
        if k == "rewind":
            self.rewind_scrub()
            return persona.confirm("rewind"), True, "rewind"
        if k == "saga":
            return persona.confirm("saga"), False, "saga"
        if k == "sync":
            return persona.confirm("sync", what=cmd.args.get("what")), False, "sync"
        if k == "remind":
            return persona.confirm("remind", title=cmd.args.get("title")), False, "remind"
        return persona.dunno(), False, "unknown"

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

    def handle_voice(self, text: str, frame=None) -> dict:
        """Route a spoken (already-transcribed) line to an intent. 'Ask/recall'
        run straight through to the brain and return the answer; a 'scholar'
        intent reads what you're looking at (needs the current `frame`); the
        rest come back as a structured intent for the hub to execute (reply,
        locate, brief, missed). The mic + speech-to-text is a device seam."""
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
        if it.kind == "scholar":
            mode = it.args.get("mode", "answer")
            # remember the intent briefly, so a look in the next few seconds
            # (even without a frame now) biases the Glance Arbiter that way.
            self._recent_glance_intent = (
                {"answer": "answer", "form": "form", "explain": "explain"}.get(mode, ""),
                self._clock())
            res = None
            if frame is not None:
                if mode == "form":
                    res = self.read_form(frame, purpose=it.args.get("purpose", ""))
                elif mode == "explain":
                    res = self.explain_text(frame)
                else:
                    res = self.read_answer(frame)
            return {"intent": "scholar", "mode": mode,
                    "answer": res.primary if res is not None else "",
                    "ok": bool(res.ok) if res is not None else False}
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
        # the Oracle quietly learns you: your own words shape your interests;
        # whoever you're talking to is someone you talk with.
        if u is not None:
            if u.is_mine():
                self.user.observe(u.text)
            else:
                self.user.note_person(u.speaker)
            self._maybe_publish_profile()
        # Truth Lens: read *how* it was said (delivery) for whoever's speaking,
        # and feed it to Discernment before the fact-check runs. Opt-in.
        if (u is not None and self.truthlens_on and not u.is_mine()
                and not self.focus_active()):
            self._read_delivery(u)
        # Veritas: fact-check the line as it lands — self-contradiction (from the
        # ledger) and a world check (Brain/cloud seam). Opt-in; held during Focus.
        if u is not None and self.factcheck_on and not self.focus_active():
            self._fact_check(u)
        # Answer-ahead: if someone *else* just asked a question, pre-fetch the
        # answer so you can say it yourself. Opt-in; held during Focus.
        if (u is not None and self.copilot_on and not u.is_mine()
                and not self.focus_active()):
            self._answer_ahead(u)
        return u

    def set_copilot(self, on: bool = True) -> None:
        """Turn the answer-ahead copilot on or off."""
        self.copilot_on = on

    def _answer_ahead(self, utterance) -> None:
        prompt = self.answer_ahead.consider(utterance.text, utterance.speaker,
                                             now=utterance.ts)
        if prompt.fired and prompt.card is not None:
            self.bridge.send_card(prompt.card, event="answer_ahead")

    def _answer_question(self, question: str):
        """Answer-ahead seam: ask your knowledge tier for the answer to an
        overheard question. Same path as the Oracle's own asks (Brain, cloud when
        opted in); returns None offline / on a miss, so nothing is surfaced. A
        retrieval-ranked answerer can drop in behind this shape."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        try:
            ans = self.brain.ask(question)
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return None
        return {"text": ans.text, "confidence": float(getattr(ans, "confidence", 0.0) or 0.0),
                "source": getattr(ans, "tier", "") or (ans.sources[0] if ans.sources else "")}

    def set_factcheck(self, on: bool = True) -> None:
        """Turn the live fact-checker (Veritas) on or off."""
        self.factcheck_on = on

    def note_credibility(self, speaker: str, vector) -> None:
        """Hand in the current delivery read (a CredibilityVector) for whoever's
        speaking, so Discernment can fuse *how* they said it with *what* they
        said. Called by the live Truth Lens wiring, or directly by a device."""
        self._credibility[(speaker or "").strip().lower()] = vector

    def set_truthlens(self, on: bool = True) -> None:
        """Turn the live delivery read (Truth Lens → Discernment) on or off."""
        self.truthlens_on = on

    def observe_face(self, frame) -> None:
        """Device seam: hand the Truth Lens a camera frame of the person you're
        with (drives the micro-expression / AU channel + face-match). No-op
        unless the delivery read is on and capture is allowed."""
        if self.truthlens_on and self.privacy.allow_capture():
            self.truth.feed_frame(frame)

    def observe_voice(self, mic_fft, amplitude) -> None:
        """Device seam: hand the Truth Lens a mic FFT window + amplitude (drives
        the voice-stress / prosody channel)."""
        if self.truthlens_on and self.privacy.allow_capture():
            self.truth.feed_audio(mic_fft, amplitude)

    def _read_delivery(self, utterance) -> None:
        """Run the Truth Lens for the current speaker: the linguistic channel
        from this line (real) plus whatever face/voice the device has fed, fused
        against the speaker's baseline → a CredibilityVector into Discernment."""
        who = (utterance.speaker or "").strip()
        self.truth.set_contact(who.lower() or None, who or None)
        self.truth.feed_transcript(utterance.text)
        vector = self.truth.assess()          # ungated: we want reassuring reads too
        if vector is not None:
            self.note_credibility(who, vector)

    def _fact_check(self, utterance) -> None:
        prior = [x.text for x in self.conversation.by_speaker(utterance.speaker)
                 if x is not utterance]
        # Fast half, on this thread: the self-contradiction pass is offline and
        # instant. Skip the world check here (world=False) so the caption
        # pipeline never blocks on the network.
        res = self.veritas.check(utterance.text, utterance.speaker,
                                 prior=prior, now=utterance.ts, world=False)
        if res.fired and res.card is not None:
            self._deliver_fact_check(res, utterance)
            return
        # Slow half, off-path: schedule the world check. It resolves from cache
        # instantly when the claim's been seen, else on a background worker with
        # a hard deadline, and only delivers a verdict worth surfacing.
        if self.veritas.checkable(utterance.text, utterance.speaker):
            self._schedule_world_check(utterance)

    def _schedule_world_check(self, utterance) -> None:
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return
        text, speaker, ts = utterance.text, utterance.speaker, utterance.ts

        def deliver(verdict: dict) -> None:
            # Re-check the gate at delivery time: the veil may have dropped, or
            # Focus started, in the seconds the ask took.
            if not self.factcheck_on or self.focus_active():
                return
            if not self.privacy.allow_capture():
                return
            res = self.veritas.world_result(text, speaker, verdict, now=ts)
            if res.fired and res.card is not None:
                self._deliver_fact_check(res, utterance)

        self.world_check.check_async(text, self.brain.ask, deliver)

    def _deliver_fact_check(self, res, utterance) -> None:
        # Discernment: fuse the content verdict with the current delivery read
        # (Truth Lens, if a recent one exists) and the pattern of prior flags.
        from .discernment import discern
        who = (utterance.speaker or "").strip().lower()
        cred = self._credibility.get(who)
        history = self._speaker_flags.get(who, 0)
        d = discern(res, credibility=cred, history=history)
        self._speaker_flags[who] = history + 1
        card = res.card
        if d.corroboration:                    # re-render the footer with the fused tag
            card = cards.fact_check(verdict=res.verdict, speaker=utterance.speaker or "them",
                                    claim=res.claim, basis=res.basis, detail=res.detail,
                                    corroboration=d.corroboration)
        card["stance"] = d.stance
        card["headline"] = d.headline
        self.bridge.send_card(card, event="fact_check")

    def _verify_claim(self, claim: str):
        """World-check: hand a checkable claim to your knowledge tiers and read
        back a verdict. Routes through the brain router's `ask` — your local
        model first, the cloud tier only if you've opted in (and never while
        incognito, which forces cloud off) — so a world fact can often be checked
        offline, and nothing leaves your devices unless you've allowed it.
        Returns None when no tier can answer, so Veritas falls back to its
        offline self-contradiction pass alone."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        from ..ai_brain.verify import verify_claim
        try:
            return verify_claim(claim, self.brain.ask)
        except Exception:
            return None

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

    def wake(self, http_get=None) -> dict | None:
        """Put the Halo on → the day's brief is waiting. Fetches the brief the
        Brain's scheduler last delivered (GET /dreamlayer/brief/latest on the
        paired Mac mini) and flashes it as a HUD card. Veil-gated; silent if
        there's no brief or no Mac mini. `http_get` defaults to urllib."""
        if not self.privacy.allow_capture() or not self.brain_url:
            return None
        get = http_get or _default_http_get
        try:
            latest = get(self.brain_url.rstrip("/") + "/dreamlayer/brief/latest",
                         self.brain_token)
        except Exception:
            return None
        if not latest or not latest.get("ts"):
            return None
        card = cards.morning_brief(latest.get("text", ""), latest.get("bullets"))
        self.bridge.send_card(card, event="wake")
        return card

    def hark(self, clue: str, detail: str = "", importance: str = "normal",
             now: float | None = None, cooldown_s: float = 120.0):
        """Oracle's "Listen!" — a proactive tap on the shoulder with one thing
        worth hearing (a clue, a heads-up). Rate-limited so it never nags:
        nothing fires within `cooldown_s` of the last hark. Silenced by the
        Privacy Veil; a *normal* hark also holds during Focus, but an *urgent*
        one pierces it. Returns the card sent, or None if hushed."""
        import time
        now = now if now is not None else time.time()
        if not self.privacy.allow_capture():
            return None
        if importance != "urgent" and self.focus_active():
            return None
        if now - getattr(self, "_last_hark", -1e9) < cooldown_s:
            return None
        self._last_hark = now
        card = cards.hark(clue, detail, importance)
        self.bridge.send_card(card, event="hark")
        return card

    def set_attention(self, on: bool = True) -> None:
        self.attention_on = on

    # -- the proactive heartbeat -----------------------------------------

    def pulse(self, context, commitments=None) -> dict:
        """One proactive heartbeat over the current moment: surface anticipation
        cards *and* decide whether Oracle should speak up ("Listen!"/"Watch
        out!"). The device seam assembles the `Context` from live signals (where
        you are, who's in view, calendar, anchors, commitments); start_pulse()
        drives this on an interval. Returns what fired."""
        cues = self.anticipate_tick(context)
        alert = self.attention_tick(context, commitments)
        return {"cues": cues, "alert": alert}

    def start_pulse(self, context_fn, interval: float = 15.0):
        """Run the proactive heartbeat every `interval` seconds. `context_fn()`
        is the device seam — it returns a fresh Context from live sensors each
        tick (or None to skip). Idempotent; safe to call once at startup."""
        import threading
        if self._tick_stop is not None:
            return
        stop = threading.Event()
        self._tick_stop = stop

        def loop():
            while not stop.wait(interval):
                try:
                    ctx = context_fn()
                    if ctx is not None:
                        self.pulse(ctx)
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    def stop_pulse(self) -> None:
        if self._tick_stop is not None:
            self._tick_stop.set()
            self._tick_stop = None

    def attention_tick(self, context, commitments=None):
        """Decide whether this moment deserves a spoken "Listen!" / "Watch out!"
        Runs the attention policy over live context and harks the single most
        important fresh alert (watch-outs first). Returns the card it spoke, or
        None. Never nags: each alert is remembered so it won't repeat, and
        hark() paces + Veil/Focus-gates the rest."""
        if not self.attention_on:
            return None
        import time
        now = getattr(context, "now", None)
        now = now if now is not None else time.time()
        for a in self.attention.evaluate(context, commitments):
            importance = "urgent" if a.level == "watchout" else "normal"
            card = self.hark(a.clue, a.detail, importance, now=now)
            if card is not None:                 # hark actually spoke (passed gates)
                self.attention.mark(a.key, now)
                return card
        return None

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

    def start_scrub(self, lookback_s: float = 3600.0, now: float | None = None,
                    show: bool = False) -> dict | None:
        self._scrub_session = TimeScrubSession(self.ring, lookback_s=lookback_s, now=now)
        card = self._scrub_session.current()
        if show and card is not None:
            self.bridge.send_card(card, event="scrub")
        return card

    def rewind_scrub(self, now: float | None = None) -> dict | None:
        """Rewind the whole day *on the glasses*: load today's moments into the
        time-scrub engine and flash the most-recent node. Twist/tap forward and
        back with scrub(); the phone Rewind shows the same day as a list."""
        import time
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        elapsed = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
        return self.start_scrub(lookback_s=max(elapsed, 60.0), now=now, show=True)

    def scrub(self, direction: str, show: bool = True) -> dict | None:
        if self._scrub_session is None:
            return None
        card = (self._scrub_session.forward() if direction == "forward"
                else self._scrub_session.back())
        if show and card is not None:
            self.bridge.send_card(card, event="scrub")
        return card

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
