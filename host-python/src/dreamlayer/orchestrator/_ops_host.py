"""orchestrator/_ops_host.py — the typed host surface the ops_* mixins share.

The Orchestrator was decomposed into cohesive ``ops_*`` mixins (IngestOps,
StasisOps, …). Every mixin reads and writes attributes — and calls sibling
methods — that live on the single composed ``Orchestrator`` host, so from a
*standalone* mixin those look undeclared and mypy rightly flags every
``self.privacy`` / ``self.db`` / ``self._clock()`` as ``attr-defined``.

``OpsHost`` names that contract once. Each mixin inherits it
(``class IngestOps(OpsHost): ...``) so mypy sees the shared shape, while at
runtime ``OpsHost`` is *empty*: the whole body lives under ``if
TYPE_CHECKING:`` and ``from __future__ import annotations`` keeps every
annotation a string, so nothing is imported, assigned, or defined when the
module actually runs. Inheriting it therefore changes no behaviour — it only
teaches the type checker the mixin↔host coupling the composed class already
guarantees at construction time (see ``Orchestrator._init_*`` builders).

The real attribute *values* are still built by the Orchestrator's
dependency-ordered ``__init__``; this file only declares their types.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Every import here is type-checking only. Because annotations are strings
    # (PEP 563), declaring the surface can never introduce a runtime import
    # cycle, no matter how tangled the real dependency graph is.
    import threading

    from ..ai_brain import BrainRouter, PerceptionRouter
    from ..ai_brain.world_check import WorldChecker
    from ..bridge.base import BridgeBase
    from ..confluence import TinCan
    from ..confluence.taps import TapCollector
    from ..config import Config
    from ..dream_mode import DreamEngine
    from ..dream_mode.premonition import RecurrenceModel
    from ..ember import EmberStore
    from ..lucid_recall import LucidRecall
    from ..memory.db import MemoryDB
    from ..memory.embeddings import EmbeddingProvider
    from ..memory.privacy import PrivacyGate
    from ..memory.proactive import ProactiveEngine
    from ..memory.retention import RetentionReport
    from ..memory.retrieval import Retriever
    from ..memory.ring_buffer import SemanticRingBuffer
    from ..object_lens import DietaryProfile, ObjectLens
    from ..pipelines.ingest import IngestPipeline
    from ..plugins.events import PluginEventBus
    from ..rem import RetrievalBias
    from ..rem.nightly import NightWatch
    from ..rosetta import RosettaLens
    from ..social_lens import SocialLens
    from ..truth_lens.analyzer import TruthLens
    from .adaptive_confidence import DismissalTracker
    from .anticipation import AnticipationEngine
    from .answer_ahead import AnswerAhead
    from .attention import AttentionPolicy
    from .candor import CandorMirror
    from .capability_log import CapabilityLedger
    from .commitment_drift import CommitmentDriftEngine
    from .consistency import ConsistencyEngine
    from .conversation import ConversationLedger
    from .frame_budget import FrameBudget
    from .glance import GlanceArbiter
    from .health import HealthLedger
    from .horizon_composer import HorizonComposer
    from .maturity import MaturityGate, ResidentGate
    from .passive_capture import SilentCapture
    from .passive_injector import PassiveEventInjector
    from .provenance import ProvenanceLens
    from .quest import QuestLog
    from .scholar import Scholar
    from .state import HostState
    from .stasis import StasisStack
    from .taste import TasteLens
    from .tell import TellEngine
    from .time_scrub import TimeScrubSession
    from .user_model import UserModel
    from .veritas import Veritas
    from .waypath import WaypathLens


class OpsHost:
    """Shared-state + shared-behaviour surface for the ``ops_*`` mixins.

    Inheriting this is a *typing-only* act — the body below runs only under a
    type checker. See the module docstring for why that is zero-cost.
    """

    if TYPE_CHECKING:
        # -- Shared state (built by Orchestrator._init_* in dependency order) --
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
        tincan: TinCan | None

        # -- Additional shared state the mixins use (not in the original
        #    inline surface; completes the host contract) --
        brain_url: str
        brain_token: str
        glasses_id: str | None
        mac_mini_connected: bool
        incognito: bool
        juno_session_s: float
        confluence_outbox: list[dict]
        wake_sources: set[str]
        wake_feedback: dict[str, bool]
        _credibility: dict
        _speaker_flags: dict
        _recent_glance_intent: tuple[str, float]

        # -- Internal shared state: initialised to None/0.0 in
        #    Orchestrator.__init__ and given a real value by a mixin method.
        #    Declared here (once) as the Optional it truly is, so neither side
        #    conflicts over whether it can be None. --
        last_retention: RetentionReport | None
        last_stasis_compost: dict | None
        _ember_active: tuple[int, float] | None
        _stasis_gaze: tuple[Any, Any, float] | None
        _stasis_last_replay: tuple[int, float] | None
        _candor_drift: str | None
        _last_person: dict | None
        _active_figment: str | None
        _rosetta_figment_id: str | None
        _msg_seen_ts: float
        _premonition_seen_ts: float
        _msg_poll_stop: threading.Event | None
        _tick_stop: threading.Event | None
        _stasis_offered: dict[int, float]

        # -- Shared behaviour: methods defined on the composed host or on a
        #    sibling mixin, invoked cross-mixin. Signatures mirror the real
        #    definitions so mypy's override check keeps them in sync. --
        def _clock(self) -> float: ...
        def _maybe_publish_profile(self) -> None: ...
        def focus_active(self, now: float | None = None) -> bool: ...
        def ask_juno(self, text: str) -> dict: ...
        def find_way(self, subject: str, heading_deg: float = 0.0) -> Any: ...
        def morning_tending(self, reel: Any = None,
                            now: float | None = None) -> list: ...
        def freeze_context(self, now: float | None = None,
                           source: str = "gesture") -> dict | None: ...
        def resume_stasis(self, frame_id: int | None = None,
                          now: float | None = None) -> dict | None: ...
        def pin_stasis(self, frame_id: int | None = None) -> dict | None: ...
        def compost_stasis(self, now: float | None = None) -> dict: ...
        def stasis_note_gaze(self, panel: Any,
                             now: float | None = None) -> dict | None: ...
        def publish_people(self, http_post: Any = None) -> dict | None: ...
        def publish_plugin_event(self, kind: str,
                                 payload: dict | None = None) -> None: ...
