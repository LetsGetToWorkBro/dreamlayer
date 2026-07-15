from __future__ import annotations
import os
from ..logging_setup import with_correlation_id
from ..memory.db import MemoryDB
from ..memory.retrieval import Retriever
from ..memory.proactive import ProactiveEngine
from ..memory.privacy import PrivacyGate
from ..memory.ring_buffer import SemanticRingBuffer
from ..pipelines.ingest import IngestPipeline
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
from ..rem.nightly import NightWatch
from ..confluence.taps import TapCollector
from ..hud import cards
# The module-level helpers moved to ._ops_helpers to break the mixin import
# cycle; re-exported here so `from ...orchestrator import _parse_scene_reply`
# (and the http/parse siblings) keeps resolving for existing callers/tests.
from ._ops_helpers import (          # noqa: F401  (re-export for compatibility)
    _default_http_get, _default_http_post,
    _parse_scene_reply, _parse_taste_reply,
)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Types for the shared-state surface below. Imported only for type
    # checking (and cheap, since `from __future__ import annotations` keeps
    # every annotation a string) so declaring the mixin<->host contract can
    # never introduce an import cycle at runtime.
    from ..bridge.base import BridgeBase
    from ..config import Config
    from ..memory.embeddings import EmbeddingProvider
    from .health import HealthLedger
    from .capability_log import CapabilityLedger
    from .maturity import MaturityGate, ResidentGate
    from .adaptive_confidence import DismissalTracker
    from .frame_budget import FrameBudget
    from ..ember import EmberStore
    from .stasis import StasisStack
    from .anticipation import AnticipationEngine
    from .conversation import ConversationLedger
    from ..social_lens import SocialLens
    from ..lucid_recall import LucidRecall
    from .attention import AttentionPolicy
    from .veritas import Veritas
    from ..ai_brain.world_check import WorldChecker
    from ..truth_lens.analyzer import TruthLens
    from .answer_ahead import AnswerAhead
    from .user_model import UserModel
    from .scholar import Scholar
    from .taste import TasteLens
    from .glance import GlanceArbiter
    from ..ai_brain import PerceptionRouter
    from ..plugins.events import PluginEventBus
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
from .ops_ember import EmberOps
from .ops_stasis import StasisOps


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
    EmberOps,
    StasisOps,
):
    # ------------------------------------------------------------------
    # Shared-state surface
    # ------------------------------------------------------------------
    # The ops_* mixins are split by concern but every one of them reads and
    # writes attributes on this single Orchestrator host. Declaring the surface
    # here makes that coupling explicit and typed: mypy sees the mixin<->host
    # contract, and a reader sees the whole shape in one place instead of
    # reverse-engineering it from a ~350-line constructor. `from __future__
    # import annotations` keeps each entry a string, so nothing is assigned at
    # class scope — the real values are built by the _init_* builders below.
    bridge: BridgeBase
    db: MemoryDB
    config: Config
    state: HostState
    health: HealthLedger
    embedder: EmbeddingProvider
    capability_log: CapabilityLedger
    retriever: Retriever
    privacy: PrivacyGate
    proactive: ProactiveEngine
    maturity: MaturityGate | ResidentGate
    dismissals: DismissalTracker
    frame_budget: FrameBudget
    pipeline: IngestPipeline
    ring: SemanticRingBuffer
    silent_capture: SilentCapture
    passive: PassiveEventInjector
    embers: EmberStore
    stasis: StasisStack
    drift_engine: CommitmentDriftEngine
    _scrub_session: TimeScrubSession | None
    tell_engine: TellEngine
    consistency: ConsistencyEngine
    provenance: ProvenanceLens
    candor: CandorMirror
    brain: BrainRouter
    anticipation: AnticipationEngine
    conversation: ConversationLedger
    social: SocialLens
    attention: AttentionPolicy
    veritas: Veritas
    world_check: WorldChecker
    truth: TruthLens
    answer_ahead: AnswerAhead
    user: UserModel
    object_lens: ObjectLens
    lucid: LucidRecall
    dietary: DietaryProfile
    rosetta: RosettaLens
    waypath: WaypathLens
    scholar: Scholar
    taste_lens: TasteLens
    glance_arbiter: GlanceArbiter
    perception: PerceptionRouter
    quest: QuestLog
    rem_bias: RetrievalBias
    nightwatch: NightWatch | None
    premonition: RecurrenceModel
    horizon: HorizonComposer
    dream: DreamEngine
    tap_collector: TapCollector
    plugin_events: PluginEventBus

    def __init__(self, bridge, db_path=":memory:", config=None):
        cfg = config or CONFIG
        # Construction is dependency-ordered: each builder below leaves the
        # attributes the next one reads already on self, so the call sequence
        # IS the dependency graph. The order is load-bearing — self.brain must
        # exist before the object lens (AIProvider) and the cloud_ok closure
        # read it, self.retriever.ember_store is set only after self.embers,
        # and the bridge.on_event(...) wiring is strictly last — so do not
        # reorder these calls.
        self._init_core(bridge, cfg, db_path)
        self._init_passive_recall(cfg)
        self._init_ember_stasis(db_path)
        self._init_reasoning_engines()
        self._init_brain_tier()
        self._init_juno_attention(db_path)
        self._init_object_lenses(db_path)
        self._init_dream_rem_horizon(cfg, bridge)
        self._init_confluence_plugins(cfg)
        bridge.on_event(self._on_event)

    # ------------------------------------------------------------------
    # Construction — dependency-ordered builders
    # ------------------------------------------------------------------

    def _init_core(self, bridge, cfg, db_path) -> None:
        """Core spine every other subsystem hangs off: the bridge, the memory
        DB, config and host state, the per-seam health ledger, the embedder
        ladder + capability log, the retriever, the privacy gate + proactive
        engine, the cold-start maturity arc, the adaptive-confidence dismissal
        tracker, the camera frame budget and the ingest pipeline."""
        self.bridge = bridge
        self.db = MemoryDB(db_path)
        self.config = cfg
        self.state = HostState()

        # Embedder ladder: local MiniLM → OpenAI (key) → hashing lexical model,
        # first available (memory.embeddings.default_embedder). The offline
        # default is a real char-ngram embedder, not the 32-d mock fixture.
        # Per-seam failure ledger: every degrading except records here first —
        # silent for the wearer, visible to the builder (health_snapshot()).
        from .health import HealthLedger
        self.health = HealthLedger()

        from ..memory.embeddings import default_embedder
        # a real-embedder degrade (network/quota) is recorded, not silent — and
        # never poisons the store with a wrong-dimension vector (see the provider)
        self.embedder = default_embedder(
            cfg, on_error=lambda e: self.health.record_failure("embed", e))
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
        self.last_tending = []          # last night's staged Ember offers
        self.last_stasis_compost = None  # last night's Stasis compost report

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
            # tier-3 LLM extraction ships the raw transcript to the cloud, so it
            # is governed by the Cloud switch, not merely by an API key being
            # present (audit 2026-07-14 CRITICAL). cloud_opt_in is forced off by
            # incognito, so this one predicate honors both switches. Late-bound:
            # self.brain is created below, but cloud_ok() only runs at ingest.
            self.pipeline = IngestPipeline.with_llm(
                self.db, cfg,
                cloud_ok=lambda: bool(getattr(self.brain, "cloud_opt_in", False)))
        else:
            self.pipeline = IngestPipeline(self.db)

    def _init_passive_recall(self, cfg) -> None:
        """Passive recall primitives: the semantic ring buffer, the silent
        capture gate and the passive event injector (whose cadence follows the
        config knob and whose clock is a late-bound closure over self._clock so
        the DST harness can swap in a SimClock)."""
        # Passive recall primitives
        self.ring = SemanticRingBuffer(cfg.passive_ring_capacity)
        self.silent_capture = SilentCapture(self, self.ring, self.privacy, cfg.capture_min_interval_ms)
        self.passive = PassiveEventInjector(
            self.bridge, self.ring, cfg.passive_min_confidence,
            # the config knob is the cadence authority now, not a comment in
            # tick(); the late-binding clock follows a swapped self._clock
            # (the DST harness drives it with a SimClock)
            tick_interval_ms=cfg.passive_tick_interval_ms,
            clock=lambda: self._clock())

    def _init_ember_stasis(self, db_path) -> None:
        """Ember (memories you tend until they live in you) and Stasis (save
        states for your mind). The ember store is wired into the retriever so
        purge_all() reaches engrams by construction; the stasis stack plus its
        ephemeral session state is restored from the vault via _stasis_load()."""
        # Ember: memories you tend until they live in you (docs/EMBER.md).
        # Its own DB file beside the memory DB — engrams are records of what
        # the WEARER knows, so they survive the retention *lifecycle* (nightly
        # sweeps, hot-ring purge) by construction. They do NOT survive the
        # wearer's explicit erase-everything: that reaches the ember file too,
        # and it does so through the retrieval primitive below — wiring the
        # store into the Retriever means purge_all() wipes engrams by
        # construction, never by a caller remembering to.
        from ..ember import EmberStore
        self.embers = EmberStore(":memory:" if db_path == ":memory:"
                                else db_path + ".ember")
        self.retriever.ember_store = self.embers
        self._ember_active = None   # (engram_id, prompted_ts) while a glow holds

        # Stasis: save states for your mind (docs/STASIS.md). The stack is
        # in-memory (three deep, like the drift engine's records); each live
        # frame also rides a kind="stasis" memories row so a held thought
        # survives a restart. Ephemeral session state (last verbatim
        # utterance, last gaze panel, offer debounce) lives on self.
        from .stasis import StasisStack
        self.stasis = StasisStack()
        self._stasis_last_utterance = ("", 0.0)   # (verbatim text, ts)
        self._stasis_gaze = None                  # (key, panel card, ts)
        self._stasis_overlays: list[dict] = []    # active overlay card dicts
        self._stasis_offered: dict[int, float] = {}
        self._stasis_last_place = ""
        self._stasis_last_replay = None           # (frame_id, ts)
        self._stasis_load()

    def _init_reasoning_engines(self) -> None:
        """On-device reasoning engines over the ring: commitment drift, the
        time-scrub session, the Tell engine, fact consistency (Candor) and
        belief genealogy (Provenance), plus the Candor Mirror self-coach."""
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
        self._candor_drift = None    # drift line captured for the debrief (OpsHost: str | None)

    def _init_brain_tier(self) -> None:
        """The AI brain and everything mounted directly around it: the three
        independent brain switches (phone/mac-mini, cloud, incognito), live
        message-notification toggles, the anticipation engine, the conversation
        ledger + captions, the Social Lens and the on-glass figment seams
        (banished figments, the optional rc_deployer / capture_provenance)."""
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
        self._last_person = None    # who you last looked at (OpsHost: dict | None)
        self._active_figment = None  # native timer/clock on the glasses stage (OpsHost: str | None)
        self._rosetta_figment_id = None  # Rosetta Live figment on stage (OpsHost: str | None)
        # Figments the wearer killed on-glass (double long-press). The banish
        # gesture works with no host; when the event does arrive we honor it
        # durably. rc_deployer is an optional seam — whoever owns a vault-backed
        # StageDeployer (the Brain's rc/* endpoints) wires it so a banished
        # figment lands on the revocation list, not just off the stage.
        self._banished_figments: set[str] = set()
        self.rc_deployer = None                  # seam: StageDeployer or None
        self.capture_provenance = None           # seam: CaptureProvenance (N2)

    def _init_juno_attention(self, db_path) -> None:
        """The Juno assistant surface and its perception/verification stack:
        wake sources + session, the attention policy, Veritas + WorldChecker,
        the Discernment fusion state, the Truth Lens, Answer-ahead, the on-device
        user model (persisted beside the vault) and Focus mode."""
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

    def _init_object_lenses(self, db_path) -> None:
        """The look-at-a-thing lenses and their perception tier: the Object Lens
        (with its recognizer and AI/Label/Rosetta providers — AIProvider needs
        self.brain, built already), the DietaryProfile, RosettaLens, Waypath,
        Scholar, TasteLens, the Glance Arbiter (priors beside the vault) and the
        Tier-0 PerceptionRouter."""
        # Object Lens: look at a thing -> a contextual panel (objects, not
        # people). Ships with the memory provider + the (inert) AI explainer;
        # register integration seams (laptop/car/plant) at the app layer.
        # Tier-1 recognizer: the best real vision backend that's installed
        # (YOLO → MLX → moondream → CLIP), else the dependency-free
        # HeuristicVisionClassifier as the offline base rung. That heuristic maps
        # confidence honestly to [0,1), so a wall or noise scores below the
        # recognizer's min_confidence gate and is rejected rather than labelled —
        # real pixel-reading recognition with no ML deps, without false objects.
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

        # Lucid Recall ("ask and receive"): the on-demand query router that
        # turns a question into one answer card — FACE queries to the Social
        # Lens, FACT queries to your own memory. Was an unwired island (audit:
        # "nothing wires it into the orchestrator; its memory_index.get() is
        # implemented nowhere"). Now composed from the real pieces and gated:
        # the memory index reads through the Retriever (consulting the mem0
        # layer first when installed), and the keyword classifier is upgraded to
        # the usearch DenseRouter when the semantic-recall extras are present.
        # Every optional piece has a fallback, so the offline default path is
        # byte-identical to the keyword+Retriever configuration.
        from ..lucid_recall import LucidRecall, RetrieverRecallIndex
        from ..lucid_recall.usearch_router import DenseRouter
        from ..lucid_recall.schema import QueryType
        _mem0 = None
        try:
            from ..lucid_recall.mem0_layer import Mem0Layer
            _m = Mem0Layer(privacy=self.privacy)
            if getattr(_m, "_mem", None) is not None:   # only when mem0 truly loaded
                _mem0 = _m
        except Exception:
            _mem0 = None
        _classify_fn = None
        if DenseRouter.available:
            _dr = DenseRouter(self.embedder)
            for _ex in ("who is this", "what is their name", "do i know them"):
                _dr.add("face", _ex)
            for _ex in ("what did we discuss", "what do i know about", "last time we talked"):
                _dr.add("fact", _ex)

            def _classify_fn(text, _dr=_dr):     # noqa: E306  (compose DenseRouter in)
                lbl = _dr.route(text, threshold=0.35)
                return {"face": QueryType.FACE, "fact": QueryType.FACT}.get(lbl)
        self.lucid = LucidRecall(
            social_lens=self.social,
            memory_index=RetrieverRecallIndex(self.retriever, mem0=_mem0),
            privacy=self.privacy,
            classify_fn=_classify_fn)

    def _init_dream_rem_horizon(self, cfg, bridge) -> None:
        """The nightly / future-facing layer: the Life Quest engine, REM
        retrieval bias (wired into the retriever's purge primitive), NightWatch,
        the Premonition recurrence model, the Meridian Horizon Frame composer and
        the Dream Mode engine."""
        # REM: last night's verdicts brighten the morning; Premonition:
        # future ghosts. Both feed the composer; both are inert when empty.
        vault_dir = getattr(cfg, "vault_dir", None)
        # Life Quest Engine: Commitment Drift, told as a personal RPG.
        self.quest = QuestLog(self.drift_engine, vault_dir=vault_dir)
        self.rem_bias = (RetrievalBias.load(vault_dir) if vault_dir
                         else RetrievalBias())
        # forget-that / erase-everything must reach the consolidation bias too,
        # by construction — wire it into the retrieval purge primitive the same
        # way the ember sidecar is, so no caller has to remember (audit 2026-07-14).
        self.retriever.bias_store = self.rem_bias
        self.retriever.bias_dir = vault_dir
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

    def _init_confluence_plugins(self, cfg) -> None:
        """The app-layer attachment seams and the plugin surface: Confluence
        bonds / tincan / tap collector / outbox, the GhostMode mesh + Beacon,
        the plugin registry and the always-present typed plugin event bus, and
        the final LLM-gated wiring of the vision pipeline into the dream
        describer."""
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


    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self, lua_root):
        info = self.bridge.connect()
        self.bridge.load_lua_app(lua_root)
        self.bridge.send_command("show_ready")
        return info


    def tick(self) -> dict | None:
        """Drive passive event injection and the Horizon Frame stream. Call as
        often as you like: the injector self-throttles to the configured
        passive_tick_interval_ms and the composer rate-limits the stream.

        Recall-gated (P1-7 / re-audit): the passive loop *proactively surfaces*
        memory, so a full pause veil must silence it — otherwise pre-pause
        hot-ring events keep being drawn while the wearer believes capture and
        recall are both off. Incognito still allows it (recall, not capture)."""
        self._premonition_sweep()
        self._tincan_sweep()
        self.tick_horizon()
        if not self.privacy.allow_recall():
            return None
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


    def forget_person(self, contact_id: str) -> None:
        """Forget one person *everywhere* the hub keys content by them: their
        contact + dossier (Social Lens, incl. the enricher notes/relation/debts),
        their deception baseline + anomaly log (Truth Lens), and their day-recall
        conversation dossier/timeline (keyed by speaker name). TruthLens.forget
        and the conversation ledger were never reached from the forget path
        (audit 2026-07-14 + refute 2026-07), so a forgotten person left resident
        judgments and transcripts behind."""
        contact = None
        idx = getattr(self.social, "_index", None)
        if idx is not None:
            contact = idx.get(contact_id)
        self.social.remove_contact(contact_id)
        self.truth.forget(contact_id)
        # getattr on an Any-typed value trips a typeshed overload false-positive
        # (it matches the `default: bool` overload); the call is valid at runtime.
        if contact is not None and getattr(contact, "name", ""):  # type: ignore[arg-type]
            self.conversation.forget(contact.name)

    def erase_all_memories(self) -> dict:
        """Erase everything on the hub — every store that holds recallable
        content, not just the vector DB. The audit flagged that the wearer's
        'erase everything' missed the MAIN store (Retriever.purge_all had no
        caller); a refute pass then showed "everything" was still dishonest —
        the deception baselines, contacts, conversation ledger, and the on-disk
        user model all survived. This scrubs them all, by construction:

          - Retriever.purge_all() → MemoryDB rows + ANN index + ember engrams
            (VACUUMed) + REM consolidation bias
          - Truth Lens per-contact deception baselines + anomaly log
            (forget_all, NOT the session-only reset())
          - Social Lens contacts, face vectors, and enricher dossiers
          - the conversation ledger (day-recall dossiers + timeline)
          - the on-disk user model (name, interests, who-you-talk-with)
          - the hot ring buffer of recent verbatim utterances
          - the Premonition recurrence model (place/time patterns)
          - Waypath anchors
        """
        self.retriever.purge_all()          # rows + ANN + ember VACUUM + REM bias
        self.truth.forget_all()             # deception baselines + anomaly log
        self.social.forget_all()            # contacts + face vectors + dossiers
        self.conversation.clear()           # day-recall ledger
        self.user.forget_all()              # learned model, in RAM and on disk
        self.ring.clear()                   # recent verbatim utterances
        self.premonition.clear()            # learned recurrence (place/time)
        n_way = self.waypath.forget_all()   # stashed-thing anchors
        return {"ok": True, "waypath_cleared": n_way}

    def lucid_query(self, text: str = "", frame=None) -> dict:
        """Lucid Recall's public surface: a question (and optionally what you're
        looking at) -> a single HUD answer card. FACE queries resolve against
        your own contacts through the Social Lens; FACT queries against your own
        memory. Recall-gated by construction (the router short-circuits on
        allow_recall()), so a full pause veil returns an empty 'No result' card.
        Returns the card dict ready for the bridge."""
        return self.lucid.query(text or None, camera_frame=frame).to_hud_card()

    @with_correlation_id
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


    @with_correlation_id
    def handle_voice(self, text: str, frame=None) -> dict:
        """Route a spoken (already-transcribed) line to an intent. 'Ask/recall'
        run straight through to the brain and return the answer; a 'scholar'
        intent reads what you're looking at (needs the current `frame`); the
        rest come back as a structured intent for the hub to execute (reply,
        locate, brief, missed). The mic + speech-to-text is a device seam."""
        from .voice import detect_wake, parse_intent
        # While an Ember prompt holds the floor, un-wake-worded speech is the
        # reach (graded, never judged aloud); a wake word always bypasses —
        # addressing Juno wins over the glow (ops_ember.ember_attempt).
        if self.ember_prompt_active() and not detect_wake(text)[0]:
            return self.ember_attempt(text)
        it = parse_intent(text)
        if it.kind == "stasis_freeze":
            res = self.freeze_context(source="voice")
            return {"intent": "stasis_freeze",
                    "ok": bool(res), **(res or {})}
        if it.kind == "stasis_resume":
            res = self.resume_stasis()
            return {"intent": "stasis_resume",
                    "ok": bool(res and res.get("ok")), **(res or {})}
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
                # Both a tap-away AND a silent expire are the wearer NOT
                # engaging — the maturity docstring and adaptive_confidence both
                # treat expire as a dismissal. Counting only 'tap' let an ignored
                # (expired) card lower the dismiss rate, promoting the very
                # wearer who tuned it out. Match the two signals.
                self.maturity.observe_card(
                    dismissed=p.get("method") in ("tap", "expire"))
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
            # Atomic decide-and-flip so two concurrent double-taps can't both
            # read the same mode and drop one of the toggles (audit 2026-07-14
            # §7). The side-effecting enter/exit_dream then re-asserts the same
            # mode idempotently under the same lock.
            if self.state.toggle_dream():
                self.enter_dream()
            else:
                self.exit_dream()
