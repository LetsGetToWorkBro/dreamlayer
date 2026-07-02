# The life layer — Saga, Wayfinding, Candor

(Display names. The code symbols stay `QuestLog`, `compile_skill`,
`ConsistencyEngine` — no symbol churn.)

Three features that make everyday life legible on the glasses. None is a new
subsystem; each is a thin, well-tested layer on substrate DreamLayer already
had. All three are fully on-device — no new sensors, no cloud.

Try them together: `python scripts/run_demo_life_layer.py`

---

## Saga — your commitments, as a personal RPG

`orchestrator/quest.py` (the Life Quest Engine)

Commitment Drift already models a promise as a living object with a state
ladder (blooming → shattered), behavior signals (nudge/keep/break), and
heal-credit momentum. The Quest layer is the narrative skin: a commitment is
a **quest**, `keep()` is a **completion**, and the drift state becomes a
status you can read.

- **XP & levels**: completing pays `BASE_XP`; levels widen as they climb
  (L2@100, L3@300, L4@600 …) so early wins come fast and mastery is slow.
- **Streaks**: consecutive completions multiply the reward (`STREAK_XP` per
  link); a `break()`/abandon resets the chain to zero.
- **Rescue bonus**: completing a quest that had slipped to *drifting* or
  *cracking* pays `RESCUE_XP` — saving one from the brink is worth more.
- **Momentum**: `tend()` (a nudge) heals a quest without paying XP — XP is for
  finishing. The half-life on heal credit is the streak/momentum model that
  was already half-built in the drift engine.
- Durable tally (`xp`, `streak`, `level`) persists to the vault; private
  commitments never surface (the drift engine refuses `meta.private`).

Orchestrator: `quests()`, `complete_quest()`, `abandon_quest()`,
`quest_stats()`. A completion surfaces a `QuestRewardCard`.

## Wayfinding — a procedure you step through hands-free

`reality_compiler/v2/skill.py`

Cooking, a repair, a BJJ sequence: a curated step list that plays on the HUD.
It compiles **straight to a Figment** — the same total, budget-verified scene
machine the device already runs — so a skill is as bounded and safe as any
rehearsed behavior: no loops, every timed exit consumes real time, worst-case
cost is provable before signing.

- Each step is a scene. A **tap** (`single`) advances; a **timed step**
  ("boil for 8 minutes") also advances itself on the clock, hands-free; a
  **long-press** bails to the end.
- A duration named in a step becomes its timer automatically
  (`parse_skill`). A saturating `step` counter drives the "n/N" readout, and
  timed steps show a live `{remaining_s}` countdown with a final-window pulse.
- `compile_skill(name, steps)` returns `(figment, budget_report)` — the report
  proves the overlay fits the constraint envelope.

Orchestrator: `build_skill(name, text)` → a deploy-ready verified Figment.

## Candor — does this contradict what you already recorded?

`orchestrator/consistency.py` (the inward twin of Truth Lens)

The privacy-respecting reimagining of "fact-check". No cloud, no web, no
external claim of truth — it only ever compares a new statement against *your
own* memories on the device and flags when the two can't both be true. It
never says which is right, only that they disagree, so you can notice.

Three contradiction kinds over a shared subject (≥2 shared content words):

- **negation** — one side asserts, the other denies ("Priya prefers tea, not
  coffee" vs "Priya prefers coffee").
- **antonym** — opposite states named (open/closed, on/off, early/late …).
- **value** — different numbers/times for the same thing ("standup at 10" vs
  "standup at 11").

Deterministic, offline heuristics over the memory ring. Private memories
(`meta.private`) are never compared, and the orchestrator gates the whole
check behind the Privacy Veil.

Orchestrator: `check_consistency(claim)` — veil-gated, surfaces a
`ConsistencyCard` when it fires.

## Tests

- `test_quest.py` — levels, streaks, rescue bonus, abandon, level-up,
  persistence, and orchestrator wiring.
- `test_skill.py` — parsing, budget-verified compilation, and running the
  compiled Figment on the real Stage (tap advance, timed self-advance, tap
  skips a timer, long-press bail, untimed step waits).
- `test_consistency.py` — the three contradiction kinds, false-positive
  guards, the privacy exclusions, and the card.
