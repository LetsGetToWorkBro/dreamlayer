from __future__ import annotations
import json
import os
from ..memory.db import MemoryDB
from ..memory.retrieval import Retriever
from ..memory.proactive import ProactiveEngine
from ..memory.privacy import PrivacyGate
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
from .candor import CandorMirror
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
from ..rem.bias import event_key
from ..rem.nightly import NightWatch
from ..confluence.taps import TapCollector
from . import intents, answer_builder
from ..hud import cards
# The module-level helpers moved to ._ops_helpers to break the mixin import
# cycle; re-exported here so `from ...orchestrator import _parse_scene_reply`
# (and the http/parse siblings) keeps resolving for existing callers/tests.
from ._ops_helpers import (          # noqa: F401  (re-export for compatibility)
    _default_http_get, _default_http_post,
    _parse_scene_reply, _parse_taste_reply,
)
from .ops_ingest import IngestOps
from .ops_dream_rem import DreamRemOps
from .ops_confluence import ConfluenceOps
from .ops_world_lenses import WorldLensOps
from .ops_brain_switches import BrainSwitchOps
from .ops_messages import MessagesOps
from .ops_conversation import ConversationOps
from .ops_juno_attention import JunoAttentionOps
from .ops_commitments import CommitmentRecallOps
from .ops_plugins import PluginOps


class Orchestrator(
    IngestOps,
    DreamRemOps,
    ConfluenceOps,
    WorldLensOps,
    BrainSwitchOps,
    MessagesOps,
    ConversationOps,
    JunoAttentionOps,
    CommitmentRecallOps,
    PluginOps,
):
    def __init__(self, bridge, db_path=":memory:", config=None):
        cfg = config or CONFIG
        self.bridge = bridge
        self.db = MemoryDB(db_path)
        self.config = cfg
        self.state = HostState()

        # Embedder ladder: local MiniLM → OpenAI (key) → hashing lexical model,
        # first available (memory.embeddings.default_embedder). The offline
        # default is a real char-ngram embedder, not the 32-d mock fixture.
        from ..memory.embeddings import default_embedder
        self.embedder = default_embedder(cfg)

        # Per-seam failure ledger: every degrading except records here first —
        # silent for the wearer, visible to the builder (health_snapshot()).
        from .health import HealthLedger
        self.health = HealthLedger()
        from .capability_log import CapabilityLedger
        # what each plugin actually does with its capabilities — a log the
        # wearer can inspect (see ops_plugins.capability_report).
        self.capability_log = CapabilityLedger()

        self.retriever = Retriever(self.db, self.embedder,
                                   ann=self._build_ann(db_path))
        self.privacy   = PrivacyGate()
        self.proactive = ProactiveEngine(self.db, privacy=self.privacy)

        # Cold-start arc: a real install (persistent DB) earns proactive
        # output in stages (OBSERVER → APPRENTICE → RESIDENT); ephemeral
        # sessions (demos, tests, the simulator) skip the arc.
        from .maturity import MaturityGate, ResidentGate
        self.maturity = (MaturityGate(self.db) if db_path != ":memory:"
                         else ResidentGate())
        self.last_retention = None      # last nightly RetentionReport

        # Adaptive confidence: per-card-type dismissal tracking. Real installs
        # persist the window; ephemeral (:memory:) sessions keep it in RAM so
        # tests stay deterministic. ProactiveEngine reads its suggested lift.
        from .adaptive_confidence import DismissalTracker
        self.dismissals = DismissalTracker(persist=(db_path != ":memory:"))
        self.proactive.dismissals = self.dismissals

        # Camera frames cost capture + BLE transfer + battery on hardware —
        # ambient frames are duty-cycled here (deliberate looks always pass).
        from .frame_budget import FrameBudget
        self.frame_budget = FrameBudget(
            ambient_interval_ms=cfg.capture_min_interval_ms)

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
        # Candor Mirror (2.7): the inward self-coach — your own pace + fillers,
        # a live arc and an after-the-fact debrief. Veil-gated, self-only.
        self.candor = CandorMirror(privacy=self.privacy)
        self._candor_drift: str | None = None    # drift line captured for the debrief
        # AI brain (docs/AI_BRAIN.md): three independent switches, not one dial.
        #   • the phone is the brain by default (on-device, works anywhere);
        #     connect_mac_mini() upgrades it with a bigger local brain + your
        #     files when your Mac mini is reachable.
        #   • use_cloud() is its own switch — cloud reach for the hardest,
        #     non-personal asks, on in any brain. On by default (best answer
        #     wherever you are); nothing private ever leaves regardless.
        #   • set_incognito() is the privacy shield — forces cloud off and
        #     pauses capture for the session (replaces the old "home" mode).
        # health: tier failures are skipped-not-fatal AND recorded; each tier
        # call runs under the Juno-ask latency budget (budgets.py).
        from .budgets import JUNO_ASK_MS
        self.brain = BrainRouter(cloud_opt_in=False, local_only=True,
                                 health=self.health,
                                 deadline_ms=JUNO_ASK_MS)
        self._cloud_pref = False              # cloud is opt-in; remembered across incognito
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
        self._last_person: dict | None = None    # who you last looked at (for on-the-spot notes)
        self._active_figment: str | None = None  # native timer/clock on the glasses stage
        self._rosetta_figment_id: str | None = None  # Rosetta Live figment on stage
        # Figments the wearer killed on-glass (double long-press). The banish
        # gesture works with no host; when the event does arrive we honor it
        # durably. rc_deployer is an optional seam — whoever owns a vault-backed
        # StageDeployer (the Brain's rc/* endpoints) wires it so a banished
        # figment lands on the revocation list, not just off the stage.
        self._banished_figments: set[str] = set()
        self.rc_deployer = None                  # seam: StageDeployer or None
        self.capture_provenance = None           # seam: CaptureProvenance (N2)
        # Juno — the assistant. "Hey Juno" wakes it; tap / gaze / raise are
        # multimodal alternatives. On wake it shows a Listening ring + (device
        # seams) an earcon and a haptic tick, then stays open a short session so
        # follow-ups need no wake word.
        self.juno_until = 0.0
        self.juno_session_s = 20.0
        self.wake_sources = {"voice", "tap", "gaze", "raise"}
        self.wake_feedback = {"visual": True, "audio": True, "haptic": True}
        self._last_hark = -1e9                  # rate-limit Juno's "Listen!"
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
        # knowledge tier the Juno asks).
        from .answer_ahead import AnswerAhead
        self.answer_ahead = AnswerAhead(answer_fn=self._answer_question)
        self.copilot_on = False
        # User model — the Juno learns you: the topics you return to, who you
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
        # Tier-1 recognizer: the best real vision backend that's installed
        # (YOLO → moondream → CLIP), else None so the recognizer's deterministic
        # mock stays authoritative — the suite runs unchanged with no vision deps.
        from ..object_lens.recognizer import ObjectRecognizer
        from ..object_lens.classify_backends import default_classifier
        _clf = default_classifier()
        _recognizer = ObjectRecognizer(classify_fn=_clf) if _clf else None
        self.object_lens = ObjectLens(ring=self.ring, privacy=self.privacy,
                                      recognizer=_recognizer)
        self.object_lens.registry.register(AIProvider(self.brain))
        # Label (your own facts about a product) + Rosetta (translate seen text)
        self.dietary = DietaryProfile()
        # Rosetta: wire the offline Argos backend when installed (extras
        # `platform`); absent → translate_fn=None, identical no-op behavior.
        from ..rosetta_argos import ArgosTranslator, make_translate_fn
        self.rosetta = RosettaLens(
            translate_fn=make_translate_fn() if ArgosTranslator.available else None,
            engine="argos")
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
        # v2 plugin event bus: typed, veil-gated moments (card/glance/place/
        # dream/veil/mesh) that subscribed plugins react to. Always present so
        # publish sites need no None-guard; cheap when nothing subscribes.
        from ..plugins.events import PluginEventBus
        self.plugin_events = PluginEventBus(veil=self.privacy, health=self.health,
                                            caplog=self.capability_log)

        # Wire vision pipeline into SceneDescriber if LLM available
        if getattr(cfg, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
            self.dream.describer.set_vision_fn(self._vision_describe)

        bridge.on_event(self._on_event)


    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self, lua_root):
        info = self.bridge.connect()
        self.bridge.load_lua_app(lua_root)
        self.bridge.send_command("show_ready")
        return info


    def tick(self) -> dict | None:
        """Drive passive event injection (~4 Hz) and the Horizon Frame
        stream (rate-limited inside the composer)."""
        self._premonition_sweep()
        self._tincan_sweep()
        self.tick_horizon()
        return self.passive.tick()


    def _clock(self) -> float:
        import time
        return time.monotonic()


    def health_snapshot(self) -> dict:
        """Everything the builder needs to diagnose 'why is it mush': the
        per-seam failure ledger, the maturity arc, and the frame budget."""
        return {"seams": self.health.snapshot(),
                "maturity": self.maturity.summary(),
                "frames": self.frame_budget.stats(),
                "plugins": self.capability_log.report()}


    def ask_juno(self, text: str) -> dict:
        """The full "Hey Juno" surface: run a device command if it is one
        ("turn on focus", "go incognito", "rewind my day"), otherwise answer
        from your brain — device → Mac mini → cloud, so it can pull up anything
        about you or the wider world. Replies as text on the glasses in Juno's
        own voice. Returns {intent, text, executed, ...}."""
        from .commands import parse_command
        from . import persona
        # first: is this you teaching Juno about yourself? ("call me Sam",
        # "remember that I prefer aisle seats") — it learns and confirms.
        learned = self.user.learn(text)
        if learned is not None:
            if learned["kind"] == "name":
                line = persona.confirm("learned_name", name=learned["value"])
            else:
                line = persona.confirm("learned_pref")
            self.bridge.send_card(cards.juno_reply(line, "action"), event="juno")
            self.publish_profile()          # a teach is worth pushing right away
            return {"intent": "learn", "text": line, "executed": True,
                    "learned": learned}
        cmd = parse_command(text)
        if cmd is not None:
            line, executed, intent = self._run_command(cmd)
            self.bridge.send_card(cards.juno_reply(line, "action"), event="juno")
            return {"intent": intent, "text": line, "executed": executed}
        # not a command → knowledge / conversation. Your questions also reveal
        # what you care about, so the Juno keeps learning as you ask.
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
        elif res.get("say"):
            # native behaviors that already speak their own confirmation:
            # stash/locate, timers, notes, debts, meet
            line = res["say"]
        else:
            line = persona.dunno()
        self.bridge.send_card(cards.juno_reply(line, "answer"), event="juno")
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
            except Exception as exc:
                # designed failure, never gaslight: record the seam, tell the
                # wearer what happened and what still works
                self.health.record_failure("brain", exc)
                self.bridge.send_card(cards.brain_unreachable(),
                                      event="brain_unreachable")
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
        if it.kind == "note_person":
            return self._note_about_person(it.args.get("who"),
                                           it.args.get("note", ""))
        if it.kind == "meet_person":
            return self._meet_person(it.args.get("who"), it.args.get("relation"),
                                     it.args.get("note"), frame)
        if it.kind == "debt":
            return self._debt(it.args.get("who"), it.args.get("dir", "they_owe"),
                              it.args.get("what", ""))
        if it.kind == "debt_settle":
            return self._debt_settle(it.args.get("who"))
        if it.kind in ("timer", "interval", "clock"):
            return self._native_behavior(it.kind, it.args)
        if it.kind == "timer_cancel":
            return self._native_cancel()
        if it.kind == "stash":
            return self._stash(it.args.get("subject", ""), it.args.get("place", ""))
        if it.kind == "locate":
            return self._locate(it.args.get("subject", ""))
        return {"intent": it.kind, **it.args}


    def _native_behavior(self, intent: str, args: dict) -> dict:
        """Build a timer / interval / clock and deploy it straight to the glasses
        stage over the bridge — no Brain, no vault. This is why "set a timer"
        works with just the hub and glasses. A clock time-query just answers."""
        import time as _t
        from ..reality_compiler.v2 import native, transport
        a = args or {}
        if intent == "clock" and a.get("mode") == "time":
            return {"intent": "clock", "ok": True, "say": _t.strftime("It's %-I:%M %p.")}
        if not self.privacy.allow_capture():
            return {"intent": intent, "ok": False, "say": "Not while you're incognito."}
        fig = None
        say = ""
        if intent == "timer":
            secs = float(a.get("seconds") or 0)
            if secs <= 0:
                return {"intent": "timer", "ok": False, "say": "How long a timer?"}
            fig = native.timer_figment(secs, label=a.get("label") or "Timer")
            say = f"Timer set for {native.spoken_duration(secs)}."
        elif intent == "interval":
            work = float(a.get("work") or 0)
            rest = float(a.get("rest") or 0)
            rounds = a.get("rounds")
            if work <= 0 or rest <= 0:
                return {"intent": "interval", "ok": False, "say": "How long on and off?"}
            fig = native.interval_figment(work, rest, rounds=rounds,
                                          label=a.get("label") or "Intervals")
            r = f" for {int(rounds)} rounds" if rounds else " until you hold to stop"
            say = (f"Intervals: {native.spoken_duration(work)} on, "
                   f"{native.spoken_duration(rest)} off{r}.")
        else:  # clock
            fig = native.clock_figment()
            say = "Clock's up. Hold to dismiss it."
        # put + hot-swap straight onto the glasses stage
        self.bridge.send_raw(transport.put_envelope(fig))
        self.bridge.send_raw(transport.swap_envelope(fig.id))
        if intent == "clock":
            self.bridge.send_raw(transport.text_envelope(fig.id, _t.strftime("%-I:%M %p")))
        self._active_figment = fig.id
        return {"intent": intent, "ok": True, "say": say, "figment_id": fig.id}


    def _native_cancel(self) -> dict:
        from ..reality_compiler.v2 import transport
        if self._active_figment:
            self.bridge.send_raw(transport.revoke_envelope(self._active_figment))
            self._active_figment = None
        return {"intent": "timer_cancel", "ok": True, "say": "Stopped."}


    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _on_event(self, name, payload):
        # device telemetry: card dismissals feed the maturity arc (a "tap"
        # is the wearer swatting a card away — the trust signal that decides
        # how much proactive output the system has earned)
        if name == "TEL":
            p = payload or {}
            # per-card-type adaptive confidence (both SHOWN and DISMISSED feed
            # the sliding window; on_telemetry_event wants the raw TEL shape)
            self.dismissals.on_telemetry_event({"t": "TEL", **p})
            if p.get("event") == "CARD_DISMISSED":
                self.maturity.observe_card(dismissed=p.get("method") == "tap")
            elif p.get("event") == "CARD_SHOWN":
                # a card actually reached the glass — the moment plugins react to
                self.publish_plugin_event(
                    "card_shown", {"card_type": p.get("card_type", "")})
            return
        # the wearer banished a figment on-glass — honor it durably: never
        # re-deploy it, and revoke it in the vault when a deployer is wired
        if name == "figment_event" and (payload or {}).get("tag") == "banished":
            fid = (payload or {}).get("id")
            if fid:
                self._banished_figments.add(fid)
                if self._active_figment == fid:
                    self._active_figment = None
                if self.rc_deployer is not None:
                    try:
                        self.rc_deployer.revoke(fid)
                    except Exception:
                        pass  # revocation retries when the deployer reappears
            return
        # Nod to Remember — an on-glass IMU gesture (imu_gesture envelope):
        # your neck is the save button (NOD_SAVE pins), a shake dismisses.
        if name == "imu_gesture":
            self.on_imu_gesture((payload or {}).get("gesture", ""),
                                (payload or {}).get("confidence", 0.0))
            return
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
