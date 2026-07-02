#!/usr/bin/env python3
"""scripts/run_demo_life_layer.py — the life layer: quests, skills, consistency.

Three features that turn everyday life into legible, on-device experiences,
all built on substrate DreamLayer already had:

  Life Quest Engine   Commitment Drift, told as a personal RPG — complete a
                      commitment to earn XP, build a streak, rescue one from
                      the brink for a bonus.
  Instant Skill Overlay  a step list compiled to a budget-verified Figment
                      you step through hands-free (tap advances, timed steps
                      advance themselves).
  Fact Consistency    a new statement checked against your *own* memories —
                      never the cloud — flagging when they can't both be true.

Run:  python scripts/run_demo_life_layer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.memory.ring_buffer import SemanticRingBuffer          # noqa: E402
from dreamlayer.pipelines.ingest import MemoryEvent                   # noqa: E402
from dreamlayer.orchestrator.commitment_drift import CommitmentDriftEngine  # noqa: E402
from dreamlayer.orchestrator.quest import QuestLog                    # noqa: E402
from dreamlayer.orchestrator.consistency import ConsistencyEngine     # noqa: E402
from dreamlayer.reality_compiler.v2 import (                          # noqa: E402
    compile_skill, parse_skill, Stage,
)

BASE = 1_700_000_000.0
H = 3600.0


def hr(title): print(f"\n{'─' * 4} {title} {'─' * (48 - len(title))}")


def demo_quests():
    hr("Life Quest Engine")
    ring = SemanticRingBuffer(capacity=50)
    for summary, due in [("send Marcus the contract", "3h"),
                         ("book the dentist", "2h"),
                         ("water the plants", "6h")]:
        ring.append(MemoryEvent(kind="task", summary=summary, confidence=0.8,
                                meta={"due": due}), ts=BASE)
    log = QuestLog(CommitmentDriftEngine(ring), now_fn=lambda: BASE)

    now = BASE + 1.9 * H         # the dentist quest is cracking by now
    for q in log.quests(now=now):
        print(f"  {q.title:<26} {q.status:<10} +{q.reward_xp} XP")
    print("  → you finish the contract, then rescue the dentist from the brink:")
    for subj in ("contract", "dentist"):
        r = log.complete(subj, now=now)
        tag = "  (rescued!)" if r.rescued else ""
        lvl = "  LEVEL UP" if r.leveled_up else ""
        print(f"     kept '{subj}': +{r.xp} XP, {r.streak}× streak{tag}{lvl}")
    s = log.stats()
    print(f"  Level {s.level} · {s.xp} XP · {int(s.level_progress*100)}% to next")


def demo_skill():
    hr("Instant Skill Overlay")
    fig, report = compile_skill("Pour-over coffee", parse_skill("""
      1. Rinse the filter, discard the water
      2. Add 30g coffee, medium grind
      3. Bloom: pour 60g water, wait 30s
      4. Pour to 500g in slow circles
      5. Draw down 3 minutes, then serve
    """))
    print(f"  compiled {len(fig.scenes)} steps → {report}")
    st = Stage(fig)
    print("  stepping through hands-free (tap advances; timed steps self-advance):")
    guard = 0
    while not st.frame().ended and guard < 40:
        fr = st.frame()
        top = fr.lines[0].text if fr.lines else ""
        print(f"     step {st.counters['step']}/{len(fig.scenes)}: {top}")
        # a timed step advances itself; an untimed one waits for the tap
        s = fig.scenes[fr.scene]
        if s.duration_sec:
            st.step(s.duration_sec)
        else:
            st.inject("single")
        guard += 1
    print("  done — the overlay ended on its own.")


def demo_consistency():
    hr("Fact Consistency (on-device)")
    ring = SemanticRingBuffer(capacity=50)
    for summary in ["the team standup is at 10",
                    "the office door code is 4417",
                    "Priya prefers tea, not coffee"]:
        ring.append(MemoryEvent(kind="memory", summary=summary, confidence=0.8),
                    ts=BASE)
    eng = ConsistencyEngine(ring)
    for claim in ["the team standup is at 11",       # value clash
                  "Priya prefers coffee",            # negation clash
                  "the office door code is 4417"]:    # agrees — no flag
        r = eng.check(claim)
        if r.fired:
            print(f"  ⚑ \"{claim}\"")
            print(f"       clashes ({r.reason}) with: \"{r.prior_summary}\"")
        else:
            print(f"  ✓ \"{claim}\" — consistent with your memory")
    print("  (nothing left the device; no cloud, no web lookup)")


def main() -> int:
    print("\nDreamLayer — the life layer\n")
    demo_quests()
    demo_skill()
    demo_consistency()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
