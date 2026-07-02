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

## Out of scope / known notes

- **GitHub repo slug** is still `memoscape` (and the default clone
  directory with it). Renaming the repo is a Settings action on GitHub;
  old URLs redirect after rename.
- **Env var rename is breaking** for anyone with `MEMOSCAPE_*` in a local
  `.env` — intentional per "the name is gone," called out here instead of
  shipping a compat shim.
- **Pre-existing breakage, unchanged by this PR:**
  `scripts/run_demo_wallet.py` and `scripts/run_demo_multi_commit.py`
  import a module-level `render` that PR #8's renderer refactor moved into
  `CardRenderer.render` — they were already broken on main before this
  migration and fail identically after it.
- Git history (old commit messages, merged PR titles) necessarily retains
  the old names.

## Verification

- host-python: `pytest -q` → 609 passed (same count as pre-migration).
- root: `pytest -q` → 159 passed, 1 skipped.
- `scripts/run_demo_rc_v2.py` runs end-to-end post-rename.
- `git ls-files` contains no path and no content matching
  `memoscape|Memoscape|MEMOSCAPE|lie_lens|face_recall|LieLens|FaceRecall`.
