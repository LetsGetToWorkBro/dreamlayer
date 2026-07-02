# Rename Migration Audit — PRs #6 and #7

Audit date: 2026-07-02. Scope: verify the DreamLayer rebrand PRs did what
their descriptions claim, and complete whatever they left undone.

## What the PRs claimed vs. what the tree contained

**PR #6 (`rebrand-dreamlayer`)** claimed "memoscape → dreamlayer (top-level
package)" and "all internal imports updated." In fact it *added new
parallel packages* (`dreamlayer/truth_lens`, `dreamlayer/social_lens`,
`dreamlayer/lucid_recall`) as fresh rewrites and left every existing
`memoscape.*` package, import, and test untouched. The rewrites were also
slimmer than the originals (e.g. `truth_lens/narrative_store.py` at 60
lines vs. `lie_lens`'s ~140, with a different API).

**PR #7 (`consolidate-dreamlayer`)** claimed hud/, memory/, pipelines/,
bridge/, simulator/ and reality_compiler/ were "migrated" and that
memoscape/ was "replaced with deprecation shims." None of those five
packages were ever created under `dreamlayer/`; only `dream_mode/`,
`orchestrator/` (4 of `app/`'s 13 modules) and a `reality_compiler`
re-export stub were added. The "deprecation shim" was a five-line
docstring in `memoscape/__init__.py` describing memoscape as "the internal
engine for DreamLayer" — the opposite of deprecation. The
`reality_compiler` stub imported `..memoscape_compat`, a package that
never existed, so `import dreamlayer.reality_compiler` raised
ModuleNotFoundError from the day it merged.

## The consequence: divergence, not duplication

Because tests, CI, and all subsequent work stayed pointed at
`memoscape.*`, later PRs developed the *old* tree while the *new* tree
rotted:

- **PR #8 (Halo Cinema)** touched 35 files under `memoscape/*` and exactly
  one under `dreamlayer/*`. Line-level divergence at audit time:
  lie_lens↔truth_lens 745 lines, face_recall↔social_lens 548,
  app/dream↔dream_mode 904.
- Nothing outside `dreamlayer/*` itself imported the #6/#7 rewrites — they
  were dead code.
- Branded identifiers survived everywhere: `MemoscapeFSM`, `MemoscapeApp`,
  `LieLens`/`LieLensResult`/`LieLensRenderer`,
  `FaceRecall`/`FaceRecallResult`/`FaceRecallRenderer`, 10 `MEMOSCAPE_*`
  env vars, `_memoscape_tick`, plus ~112 files referencing the old name
  (docs, Lua comments, scripts, both pyprojects, uv.lock).

## What this PR does

Canonical code = the living `memoscape/*` tree (tested, Cinema-updated).
The stale #6/#7 rewrites are deleted; the living code moves into
`dreamlayer/*` under the intended names; the old name is eliminated.

| Old | New |
|---|---|
| `memoscape.lie_lens` | `dreamlayer.truth_lens` |
| `memoscape.face_recall` | `dreamlayer.social_lens` |
| `memoscape.app.dream` | `dreamlayer.dream_mode` |
| `memoscape.app` (all 13 modules) | `dreamlayer.orchestrator` |
| `memoscape.{hud,memory,pipelines,bridge,simulator,config,main}` | `dreamlayer.*` |
| `memoscape.reality_compiler` (v1) | `dreamlayer.reality_compiler` (beside `v2/`) |
| root `memoscape/` (BLE app: fsm, memory_engine, app) | root `dreamlayer/` |
| `LieLens`, `LieLensResult`, `LieLensRenderer` | `TruthLens`, `TruthLensResult`, `TruthLensRenderer` |
| `FaceRecall`, `FaceRecallResult`, `FaceRecallRenderer` | `SocialLens`, `SocialLensResult`, `SocialLensRenderer` |
| `MemoscapeFSM`, `MemoscapeApp` | `DreamLayerFSM`, `DreamLayerApp` |
| `MEMOSCAPE_*` env vars | `DREAMLAYER_*` (hard rename, no fallback) |
| `_memoscape_tick` (Lua global) | `_dreamlayer_tick` |
| store keys `lie_lens_baseline_*`, `lie_lens_anomaly_*` | `truth_lens_baseline_*`, `truth_lens_anomaly_*` |

Unique #6/#7 additions with no memoscape counterpart are kept:
`dreamlayer.lucid_recall` and `dreamlayer.reality_compiler.v2`.
Both pyprojects now name the project `dreamlayer`; uv.lock regenerated;
docs, README, halo-lua comments, phone-app, `.env.example`, and demo
scripts updated. Zero tracked files contain `memoscape`, `lie_lens`,
`face_recall`, or their camel-case forms.

## Known notes

- **GitHub repo slug**: renamed to `DreamLayer` by the owner
  (2026-07-02). GitHub redirects the old `memoscape` URLs — existing
  clones, the CI checkout, and old links keep working without changes.
- **Env var rename is breaking** for anyone with `MEMOSCAPE_*` in a local
  `.env` — intentional per "the name is gone," called out here instead of
  shipping a compat shim.
- **Legacy demo scripts repaired** (follow-up commit on this PR):
  PR #8's renderer refactor had silently removed the module-level
  `render()` that `run_demo_wallet.py` / `run_demo_multi_commit.py` were
  built on — both were already broken on main. Restored `render()` as a
  thin delegate over a shared `CardRenderer`, and hardened
  `_object_recall` to accept the simulator's structured
  `{"name": …, "near": …}` payloads alongside halo_lab's flat strings.
  All four legacy demos (`wallet`, `multi_commit`, `edge_cases`,
  `cinema`) now run.
- Git history (old commit messages, merged PR titles) necessarily retains
  the old names.

## Divergence-fix proof (added after review)

To confirm no bugfix was stranded in a stale copy, origin/main's
`memoscape/*` trees were re-extracted, run through the identical
path-move + rename pipeline, and diffed against this branch's
`dreamlayer/*`:

- host package: the **only** differences are the nine relative-import
  fixes required by the new layout (`..recall_context` →
  `..orchestrator.recall_context` ×6, `...hud` → `..hud`, `.dream` →
  `..dream_mode`, `..app.orchestrator` → `..orchestrator.orchestrator`).
- root package: **byte-identical**.
- Spot-checked markers all present post-migration: the #8 ghost-layer
  young-clock fix, `place_reactor.py`, the Truth Lens 9-ring gauge
  renderer, and the corrected `deception_score` channel weighting.

## Verification

- host-python: `pytest -q` → 609 passed (same count as pre-migration).
- root: `pytest -q` → 159 passed, 1 skipped.
- `scripts/run_demo_rc_v2.py` runs end-to-end post-rename.
- `git ls-files` contains no path and no content matching
  `memoscape|Memoscape|MEMOSCAPE|lie_lens|face_recall|LieLens|FaceRecall`.
