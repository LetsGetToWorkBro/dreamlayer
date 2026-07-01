"""reality_compiler.v2 — the Rehearsal paradigm.

You don't describe the behavior — you perform it once, and the glasses
learn the choreography. Performances compile to Figments: total,
statically-budgeted, signed scene-machines interpreted by a fixed
on-device stage (halo-lua/app/figment_stage.lua). No user code ever
ships to Halo.

Docs: docs/RC_V2_PICKED.md (why), docs/rc_v2/rehearsal.md (what),
docs/RC_V2_ATTACKS.md (how it holds).
"""
from .figment import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, FigmentError, END, SELF,
)
from .budgets import verify, verify_or_raise, BudgetReport, Violation
from .interpreter import Stage, DisplayFrame
from .rehearsal import RehearsalSession, RehearsalResult, Beat, parse_utterance
from .choreographer import Choreographer, InferenceError
from .teach import TeachCard, teach_violations, teach_inference
from .playback import run_through, render_png, transcript, PlaybackFrame
from .signer import SessionSigner, SigningError, content_hash
from .vault import Vault, VaultEntry
from .compat import lift, ALL_V1_TYPES
from .transport import (
    FIGMENT_PUT, FIGMENT_SWAP, FIGMENT_REVOKE, FIGMENT_TEXT,
    FIGMENT_ACK, FIGMENT_EVENT,
)
from .deployer import StageDeployer, DeployRecord
from .compiler import RealityCompilerV2, TextCompileResult

__all__ = [
    "Figment", "Scene", "TextLine", "PulseSpec", "CounterDecl", "CounterOp",
    "Guard", "Transition", "FigmentError", "END", "SELF",
    "verify", "verify_or_raise", "BudgetReport", "Violation",
    "Stage", "DisplayFrame",
    "RehearsalSession", "RehearsalResult", "Beat", "parse_utterance",
    "Choreographer", "InferenceError",
    "TeachCard", "teach_violations", "teach_inference",
    "run_through", "render_png", "transcript", "PlaybackFrame",
    "SessionSigner", "SigningError", "content_hash",
    "Vault", "VaultEntry",
    "lift", "ALL_V1_TYPES",
    "FIGMENT_PUT", "FIGMENT_SWAP", "FIGMENT_REVOKE", "FIGMENT_TEXT",
    "FIGMENT_ACK", "FIGMENT_EVENT",
    "StageDeployer", "DeployRecord",
    "RealityCompilerV2", "TextCompileResult",
]
