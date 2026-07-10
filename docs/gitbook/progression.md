# Progression — the Saga

The Saga (`host-python/src/dreamlayer/ai_brain/saga.py`, quests in
`orchestrator/quest.py`) is DreamLayer's progression system: a rank, a level,
XP, and a set of achievements that unlock as you actually *use* the
ecosystem. It is durable (`saga.json` beside the Brain's config), served by
the Brain (`GET /dreamlayer/saga`), recorded by one endpoint
(`POST /dreamlayer/saga/record` with `{event}`), and rendered by the phone's
Saga screen.

![The Saga screen — rank, XP, and the achievement ledger](assets/phone/saga.png)

## Ranks and levels

XP accumulates through quests and explore badges; levels follow a triangular
curve (`100 * (level-1) * level / 2` cumulative — level 2 at 100 XP, level 3
at 300, and so on) up to **level 30**. Seven ranks mark the arc:

| Level | Rank |
|---|---|
| 1 | Sleeper |
| 3 | Dreamer |
| 6 | Lucid |
| 10 | Seer |
| 15 | Juno |
| 21 | Luminary |
| 28 | Architect of Memory |

## Achievements

Three categories, every one unlocked by a real event in the ecosystem.
Progress is monotonic; unlocking grants XP, and XP can cascade-unlock the
level milestones.

### Milestones — reaching a level

First Light (2), Waking (5), Lucid (10), Farsight (15), Juno's Eye (20),
Luminous (25), Architect of Memory (30).

### Quests — the Commitment Drift game

The QuestLog wraps commitment drift in narrative: every tracked promise is a
quest; completing one earns 50 XP base, **rescuing** one already drifting or
cracking adds 40, and each consecutive keep adds a 12 XP streak bonus.
Rewards render as QuestRewardCards (QUEST COMPLETE / LEVEL UP / RANK UP).
Badges: **Keeper** (first quest, 80 XP), **From the Brink** (first rescue,
120), **Unbroken** (a streak of 5, 150), **Relentless** (streak of 10, 300),
**Devoted** (25 quests, 400).

### Explore — one badge per capability (150 XP each)

| Badge | Unlocked by | Event |
|---|---|---|
| Entangled | pairing the trio | `pair` |
| Second Mind | connecting a Mac mini | `mac` |
| Reach Beyond | first cloud answer | `cloud` |
| Veiled | first incognito session | `incognito` |
| Hey Juno | first voice wake | `juno_wake` |
| Face to Name | first dossier | `dossier` |
| Total Recall | first recall answered | `recall` |
| Dawn | first morning brief | `brief` |
| Timekeeper | calendar sync on | `calendar` |
| Inner Circle | contacts sync on | `contacts` |
| The List | reminders sync on | `reminders` |
| Deep Focus | first focus session | `focus` |
| Rewind | first day scrubbed | `rewind` |
| Listen | first hark | `hark` |
| Local Mind | an Ollama model pulled | `model` |
| The Vault | first backup downloaded | `backup` |
| Well Read | first folder indexed | `folder` |

## How events flow

The Brain records many events itself as side effects (pairing, folder adds,
sync toggles, backups, model pulls, briefs); the hub and phone record the
rest through `POST /dreamlayer/saga/record` — for example, the phone fires
`focus` when you enable Focus mode, and the glasses' recall, hark, and wake
moments arrive from the orchestrator. `GET /dreamlayer/saga` returns the
whole profile — XP, level, rank, next rank, and every achievement's what,
how, and unlock state — which is exactly what the phone renders.
