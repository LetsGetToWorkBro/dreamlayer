# Handoff — read this before touching anything

Working state as of 2026-07-29. Written for whoever picks this up next.

---

## The task in front of you

**Step 3 is the lens-coverage gap below.** Steps 1 (retention) and 2 (face
recognition) are done and merged — kept here as context, not work.

### The lens gap — four lenses the phone cannot reach (audit 2026-07-29)

The phone camera path does **not** use the `Orchestrator`, which is correct and
deliberate: `WorldLensHost` (`ai_brain/server/world_lens.py`) is the Brain-side
host. It imports shared primitives *from* the `orchestrator` package (`TasteLens`,
`GlanceArbiter`, `CapabilityLedger`) but never constructs an `Orchestrator`.

It is **not 1:1 with the lens classes**, and that is the open work. Verified:

```
$ for c in TruthLens ProvenanceLens Scholar YesterlightController; do \
    grep -rn "$c(" src/dreamlayer --include=*.py | grep -v /tests/; done
truth_lens/__init__.py, orchestrator/orchestrator.py          # TruthLens
orchestrator/orchestrator.py, orchestrator/capture_provenance.py  # ProvenanceLens
orchestrator/orchestrator.py, orchestrator/glance.py          # Scholar
dream_mode/engine.py   (DreamEngine — itself orchestrator-only)  # Yesterlight
```

All four are declared as lenses in `lenses.py`, all four have real modules on
disk, and none has any reference from `ai_brain/` — so they are invisible from
the phone, the same disease as retention (`decisions/0001`) and the Social Lens
(fixed in #542). **Truth Lens, Provenance, Scholar and Yesterlight are the
remaining Orchestrator-only lenses.** Scholar is the most user-visible of the
four ("read a test → the answer; a form → what to write in each field").

Fix them the way the last three were fixed: re-implement Brain-side against the
Brain's own state, do **not** resurrect the Orchestrator.

**What already works, so you do not re-audit it:**

- **The glass does pick its own lens.** `GlanceArbiter` is built in
  `WorldLensHost.__init__` (via `glance_live.build_live_arbiter`) and `glance()`
  arbitrates every look: fire the clear winner, offer a chooser when genuinely
  ambiguous, else the object floor. It learns per-scene priors, and a
  priors-forced fire still carries `alts` so the roads not taken stay reachable.
- **All 8 arbiter candidates dispatch to something real.** Verified in
  `_run_glance_lens`: read→`look_lens("doc")`, math→`look_lens("math")`,
  depth/sky/segment→`look_lens(action)`, translate→`look(facet="ai")`,
  taste→`taste()`, juno→the object floor. No candidate bids for a lens that
  cannot run.
- **`find` IS reachable.** Spoken intent lands via `/live/intent` →
  `note_spoken_intent` → `pending_intent()`, and `world_lens.py:576` runs
  `look_lens(frame, "find", {"terms": …})`. **The comment in `glance_live.py`
  calling that "the next tier of this work" is STALE** — fix the comment when
  you are next in that file.
- Deliberately not auto-fired: `find` (needs nouns a bare frame cannot supply),
  `dream` (a deliberate style tap), and `person` (every face defers to
  `person_guard`; the arbiter must never try to identify a stranger).

### Step 1 — retention (DONE, #541)

Wired Brain-side, following the `ear.py` / `glance_live.py` precedent rather
than resurrecting the `Orchestrator` the shipped Brain never builds:

- `ai_brain/server/retention_live.py` runs the existing `RetentionSweep`
  primitive against the Brain's own `MemoryDB`.
- Called from `Brain.__init__` beside the `retention_days` log prune, and again
  hourly via `Brain.start_retention_scheduler` — boot alone would mean nothing
  ages out on a machine that stays awake, and the hot ring is in-memory, so boot
  is the one moment it is guaranteed to be empty.
- Windows come from `config.py` (`retention_hot_hours` / `retention_warm_days`),
  read live. Conservatism kept: unknown age → keep, pinned → never expires,
  entities cold-forever, any failure → keep.
- `tests/test_brain_retention_boot.py` is the proof, and every assertion in it
  is a row that is GONE from a real file after a real boot. Mutation-tested.
- `decisions/0001` is now `fixed` (a new status — see `decisions/README.md`),
  and the docs' retention claims were made confident again in the same change.

### Step 2 — face recognition (DONE, #542)

InsightFace `buffalo_l` (SCRFD + ArcFace r50, ONNX/CPU) behind a new opt-in
`face` extra, plus the Brain-side consumer that did not exist — `SocialLens` was
`Orchestrator`-only, so the model alone would have been `decisions/0001` one lens
over. `ai_brain/server/face_live.py` + `POST /dreamlayer/face/{enrol,identify,
forget}` + `GET /dreamlayer/face`.

Both non-negotiables are enforced and mutation-tested: ambient is `$DL_FACE_AMBIENT`
(**not** a `BrainConfig` field — a panel toggle is a thing a release build ships
with) and is refused outright in a frozen build; a non-matching template is
discarded with no disk write, no ledger line, no log. Only ONE template is
computed per frame — the subject's — so a bystander never has a biometric
computed at all.

**Three things carried forward from #542, still open:**

1. **`models.lock` ships `insightface/buffalo_l` UNPINNED.** Capture the hashes
   on a clean, connected, trusted box (`dreamlayer models pin`) before any build
   ships the face pack. The weights the PR was verified against arrived over a
   sandbox proxy, which is not that box.
2. **0.65 / 0.08 are still uncalibrated.** The `real_model` tests pin only the
   DECLINE direction (noise, flat, empty frames). Cross-photo accuracy is
   untested — this repo has no face photographs and should not gain any.
   `social_lens/index.py` says these are placeholders until the Rig 3 perception
   bench runs an ROC over genuine/impostor pairs. Do not treat them as validated.
3. **Two guards must not drift again.** `test_logging_discipline.py` (AST,
   authoritative) and `.semgrep/dreamlayer.yml` (regex twin) contradicted each
   other about `type(exc).__name__` and cost a review round. A test now pins them
   agreeing; keep it that way.

### The face copy, timed to the release (still pending)

The copy is deliberately UNCHANGED, and still correct: the default install has
no `face` pack and no weights, so the shipped embedder still declines every
frame. `face` is in no `profile-*` extra, which is what keeps the sentence true.

The tripwire moved in #542 and is now sharper, so do not look for the old one.
`test_advertised_claims.py` asserts the default build's behaviour
unconditionally (conftest pins the backend absent for `no_face_double` tests, so
a developer who installs the pack locally no longer flips the assertion), and
`test_the_face_pack_is_in_no_deployment_profile` is the guard that actually
fires: **the moment `face` is added to a deployment profile, it fails.** That is
the signal to change the copy — before the build ships, not after.

What must change when it does ship (exact sentences are in the test docstrings):
- `landing/privacy.html` — "cannot return an identity at all", and "keep a face
  database" (a consented index *with face vectors* is a face database — needs
  the same precision treatment the voice-cloning line got)
- `docs/gitbook/privacy.md` — "absent from the codebase, not switched off"
- The iOS purpose strings and App Store privacy declaration — face templates are
  **biometric identifiers**, and the current declaration says camera is QR-only.
- `"No stranger face lookup"` and `"no public face database"` both **survive**
  if you stay consent-only. That is the line worth defending, because it is true.

---

## Repo landmines that cost real time this session

**`decisions/` — read it before re-raising any finding.** Findings closed without
a code change live there with evidence and the check that would overturn them.
Skim the index first; the hour may already be spent. See `CONTRIBUTING.md`.

**The docs site is GENERATED.** `letsgettoworkbro.github.io/dreamlayer-docs` is
build output. `scripts/build_gitbook_site.py` renders `docs/gitbook/*.md` from
THIS repo and deploys to that repo's `gh-pages`. **Never edit HTML in
`dreamlayer-docs`** — the next deploy silently reverts it. I did this, and only
caught it because a redeploy landed mid-PR and conflicted. Also note that repo's
default branch is `gh-pages`, not `main`.

**`Orchestrator` is not in the shipped product.** Constructed only in `main.py`
(emulator) and `simulator/`. Whole features that "live on the Orchestrator" are
invisible to users. Check before assuming any Orchestrator-owned capability
runs:
```
grep -rn "Orchestrator(" src/dreamlayer --include=*.py | grep -v /tests/
```

**Verify claims with commands, never from memory.** `decisions/0005` is a
refutation I wrote that was directionally right and specifically wrong — "no
production code constructs that class" when two modules do. It was one `grep`
from being correct and would have collapsed the first time anyone checked.

**Mutation-test every regression test.** Revert the fix; the test must fail.
Four tests written earlier in this project could not fail — one reimplemented
the production logic inside the test file. Commit first, then mutate, then
restore: a `git checkout --` during mutation testing once reverted four files
holding uncommitted work.

---

## Conventions

- **Branch:** `claude/dreamlayer-audit-k4xjv5`. It gets merged and deleted each
  round — start each new piece with
  `git fetch origin main && git checkout -B claude/dreamlayer-audit-k4xjv5 origin/main`.
  Never stack on merged history. `git remote prune origin` first if
  `--force-with-lease` complains about stale info.
- **DCO required:** `git commit -s` on every commit.
- **No `gh` CLI.** Use the `mcp__github__*` tools.
- **Squash merge.** Rebase merge returns 405 on this repo.
- **Never put the model identifier in commits, PRs, or code comments.**
- **Full gate:**
  ```
  cd host-python && python -m pytest -q -m "not hardware and not benchmark and not real_model"
  python -m ruff check src/dreamlayer && python -m mypy src/dreamlayer
  ```
  Currently **4496 passed, 22 skipped**. Takes ~4.5 min.
- **PR template** is at `.github/pull_request_template.md` — mirror its
  headings, and only tick boxes you actually verified.

---

## Recently merged (context, not work)

| PR | What |
|----|------|
| #530 | Full-stack audit: Veil leaks, face embedder failing closed, phone location leak |
| #531 | `real-models` CI job actually runs the real models; now fails on any skip |
| #533 | `decisions/` directory + validator |
| #534 | Voice-cloning claim corrected; `test_advertised_claims.py` |
| #535 | Docs claims fixed at source (`docs/gitbook/*.md`) |
| #541 | Retention wired Brain-side; `decisions/0001` closed |
| #542 | Face recognition: ArcFace behind the `face` extra + the Brain-side consumer |

**Open and unresolved:** the lens-coverage gap at the top of this file (Truth
Lens, Provenance, Scholar, Yesterlight are Orchestrator-only), the three
carry-forwards from #542, and the face copy when a build ships the pack. Task
list item #58 (tray icons, dock-click, Learn glass) is stale and needs a build
to verify. `decisions/0001` (retention) is closed.

---

## One standing instruction from the owner

The website and knowledge base are promises. When you change what the software
does, check whether a claim on `dreamlayer.app` or the knowledge base just
became false, and fix it in the same change. `test_advertised_claims.py` pins
the ones that matter; when it fails, that is the system working, not an
obstacle.
