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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import budgets, compat
from .budgets import BudgetReport
from .deployer import DeployRecord, StageDeployer
from .figment import Figment
from .playback import PlaybackFrame, run_through
from .rehearsal import RehearsalSession
from .grammar_mine import GrammarMiner
from .repertoire_ranker import RepertoireRanker
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
                 bridge=None, now_fn=None) -> None:
        if vault_dir is None:
            vault_dir = Path(tempfile.mkdtemp(prefix="dreamlayer_vault_"))
        self.vault = Vault(vault_dir)
        self.deployer = StageDeployer(self.vault, bridge=bridge)
        self._now = now_fn or time.time
        # the compiler teaches itself (5.3): rank the repertoire by how you
        # actually use it. Rebuilt from the vault log so it survives a restart.
        self.ranker = RepertoireRanker()
        self._hydrate_ranker()
        # grammar mining (5.3): count the words people try to say that the
        # closed grammar can't hear yet, so its roadmap is a measurement.
        self.miner = GrammarMiner(self.vault.root / "grammar_mine.json")

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
            hour = self._hour()
            self.vault.record_performance(figment_id, {"action": "deploy", "hour": hour})
            self.ranker.observe(figment_id, "deploy", hour)
        return record

    def record_outcome(self, figment_id: str, outcome: str,
                       scene: Optional[str] = None,
                       elapsed: Optional[float] = None) -> None:
        """Log how a deployed figment ended — "complete" (reached its terminal
        scene) or "banish" (killed). For a banish, `scene`/`elapsed` say where it
        was killed, which drives rehearsal refinement (5.3). Feeds the ranker
        and is kept in the vault log so the lesson survives a restart."""
        if outcome not in ("complete", "banish"):
            return
        ctx: dict[str, Any] = {"action": outcome}
        if scene is not None:
            ctx["scene"] = scene
        if elapsed is not None:
            ctx["elapsed"] = round(float(elapsed), 1)
        self.vault.record_performance(figment_id, ctx)
        self.ranker.observe(figment_id, outcome)

    def refine_proposal(self, figment_id: str, min_banishes: int = 2):
        """If a figment keeps getting banished at the same scene, propose the
        edit — "you end this around 20:00 of 25:00, shorten it?" Returns a
        RefineProposal or None."""
        from .refine import propose_refinement
        try:
            entry = self.vault.load(figment_id)
        except KeyError:
            return None
        return propose_refinement(entry.figment,
                                  self.vault.performance_history(figment_id),
                                  min_banishes=min_banishes)

    def apply_refinement(self, proposal) -> VaultEntry:
        """Materialise a proposed refinement: a budget-verified, re-signed
        variant with the offending scene shortened and the lineage recorded.
        Both the original and the variant stay in the vault."""
        from .refine import build_variant
        variant = build_variant(self.vault.load(proposal.figment_id).figment,
                                proposal.scene, proposal.suggested_sec)
        return self.keep(variant)      # verifies budgets + signs

    def mine_utterance(self, text: str) -> None:
        """Feed one spoken beat to the grammar miner (5.3). A beat that fell out
        of the closed grammar (became a label) contributes its words to the
        near-miss counts; a recognised command teaches nothing."""
        from .rehearsal import parse_utterance
        try:
            self.miner.observe(text, parse_utterance(text))
        except Exception:
            pass                          # mining never affects a rehearsal

    def grammar_candidates(self, top: int = 10, min_count: int = 2) -> list[dict]:
        """The words people keep trying to say that the grammar can't hear yet."""
        return self.miner.candidates(top=top, min_count=min_count)

    def suggest(self, hour: Optional[int] = None) -> Optional[dict]:
        """The best machine for right now, or None. "Gym? Start the usual?" """
        h = self._hour() if hour is None else int(hour) % 24
        return self.ranker.suggest(self.repertoire(), h)

    def revoke(self, figment_id: str) -> DeployRecord:
        return self.deployer.revoke(figment_id)

    def repertoire(self) -> list[VaultEntry]:
        return self.vault.list()

    def ranked_repertoire(self, hour: Optional[int] = None) -> list[VaultEntry]:
        """The repertoire ordered by fit-for-now (best first)."""
        h = self._hour() if hour is None else int(hour) % 24
        return self.ranker.rank(self.repertoire(), h)

    def _hour(self) -> int:
        return time.localtime(self._now()).tm_hour

    def _hydrate_ranker(self) -> None:
        history = {e.figment.id: self.vault.performance_history(e.figment.id)
                   for e in self.repertoire()}
        self.ranker.hydrate(history)

    # ------------------------------------------------------------------
    # v1 compatibility surface (deprecated)
    # ------------------------------------------------------------------

    def compile_text(self, text: str) -> TextCompileResult:
        """v1's plain-English input, lifted to a Figment.

        Deprecated: kept so every v1 phrasing keeps working. Reuses the
        v1 IntentParser (offline pattern-matcher) unchanged.
        """
        from dreamlayer.reality_compiler.intent_parser import IntentParser

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
