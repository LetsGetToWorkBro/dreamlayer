"""v2/compiler.py — RealityCompilerV2: the Rehearsal paradigm, end to end.

    rc = RealityCompilerV2(vault_dir="~/.dreamlayer/vault")

    session = rc.rehearse("Rolling rounds")
    session.double_tap()
    session.say("rolling - three minutes")
    session.say("last ten seconds, pulse")
    session.say("then it starts again")
    result = session.finish()          # infer → verify → run-through

    if result.ok:
        rc.keep(result.figment)        # sign + vault
        rc.deploy(result.figment.id)   # put + hot-swap onto the stage
    else:
        print(result.teach)            # the failure, in beats

Also carries the v1 compatibility surface:

    rc.compile_text("3 minute round timer with 20 seconds overtime")

which reuses the v1 IntentParser and lifts the intent to a Figment.
Deprecated — see docs/RC_V2_PICKED.md — but every v1 phrasing keeps
working until the Repertoire replaces it.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import budgets, compat
from .budgets import BudgetReport
from .deployer import DeployRecord, StageDeployer
from .figment import Figment
from .playback import PlaybackFrame, run_through
from .rehearsal import RehearsalResult, RehearsalSession
from .vault import Vault, VaultEntry


@dataclass
class TextCompileResult:
    """Result of the deprecated v1-text surface."""
    figment: Figment
    report: BudgetReport
    playback: list[PlaybackFrame]

    @property
    def ok(self) -> bool:
        return self.report.ok


class RealityCompilerV2:
    def __init__(self, vault_dir: Optional[Path | str] = None,
                 bridge=None) -> None:
        if vault_dir is None:
            vault_dir = Path(tempfile.mkdtemp(prefix="dreamlayer_vault_"))
        self.vault = Vault(vault_dir)
        self.deployer = StageDeployer(self.vault, bridge=bridge)

    # ------------------------------------------------------------------
    # The paradigm: rehearse → keep → deploy
    # ------------------------------------------------------------------

    def rehearse(self, name: str = "Rehearsed behavior") -> RehearsalSession:
        """Open the stage."""
        return RehearsalSession(name=name)

    def keep(self, fig: Figment) -> VaultEntry:
        """Sign with the session key and store in the Repertoire.
        Verifies budgets first — nothing unproven gets a signature."""
        budgets.verify_or_raise(fig)
        return self.vault.keep(fig)

    def deploy(self, figment_id: str) -> DeployRecord:
        record = self.deployer.deploy(figment_id)
        if record.success:
            self.vault.record_performance(figment_id, {"action": "deploy"})
        return record

    def revoke(self, figment_id: str) -> DeployRecord:
        return self.deployer.revoke(figment_id)

    def repertoire(self) -> list[VaultEntry]:
        return self.vault.list()

    # ------------------------------------------------------------------
    # v1 compatibility surface (deprecated)
    # ------------------------------------------------------------------

    def compile_text(self, text: str) -> TextCompileResult:
        """v1's plain-English input, lifted to a Figment.

        Deprecated: kept so every v1 phrasing keeps working. Reuses the
        v1 IntentParser (offline pattern-matcher) unchanged.
        """
        # TODO(rename): dreamlayer.reality_compiler.intent_parser after rename PR lands
        from memoscape.reality_compiler.intent_parser import IntentParser

        intent = IntentParser().parse(text)
        fig = compat.lift(intent)
        report = budgets.verify(fig)
        frames = run_through(fig) if report.ok else []
        return TextCompileResult(figment=fig, report=report, playback=frames)

    def compile_intent(self, intent) -> TextCompileResult:
        """Lift a v1 BehaviorIntent directly (templates dropped into v2)."""
        fig = compat.lift(intent)
        report = budgets.verify(fig)
        frames = run_through(fig) if report.ok else []
        return TextCompileResult(figment=fig, report=report, playback=frames)
