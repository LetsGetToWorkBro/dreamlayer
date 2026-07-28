# Handoff — read this before touching anything

Working state as of 2026-07-27. Written for whoever picks this up next.

---

## The task in front of you

**Step 2: face recognition.** Step 1 (retention) is done — see below. The owner
made retention the prerequisite because storing face templates under a retention
policy that does not run is materially worse than storing text under it.

### Step 1 — retention (DONE, 2026-07-28)

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
  is a row that is GONE from a real file after a real boot. It was
  mutation-tested against the boot hook.
- `decisions/0001` is now `fixed` (a new status — see `decisions/README.md`),
  and the docs' retention claims were made confident again in the same change.

### Step 2 — face recognition

The owner has explicitly asked for this, reversing an earlier "no". Their four
answers, verbatim in intent:

1. **No in-app consent flow to start.** Testing with friends who consent
   verbally. Do not build a consent UI as a blocker.
2. **Ambient to start**, gesture-triggered later.
3. **Retention first** — yes.
4. **Licensing** — not a concern for now.

The seam already exists and is documented as such: `truth_lens/face_embed.py:52`
calls `embed_fn` *"the hole a real on-device model plugs into"*. `ContactIndex`
already has the 0.65 threshold and 0.08 top-2 margin. `social_lens/
introduction.py` already enrols on introduction. You are plugging in a model,
not building a subsystem.

Recommended model: **InsightFace ArcFace `buffalo_l`** via ONNX — 512-d output
matches `FaceEmbedder`'s existing contract exactly, onnxruntime is already an
extra, and `models.lock` + `model_guard.py` already exist to hash-pin weights.

**Two things that are not negotiable, because they were promised:**

- **Ambient must be an explicit flag, OFF in release builds.** A testing default
  that silently becomes the ship default is the exact bug class this codebase
  keeps producing (`RetentionSweep` uncalled, `probe_ollama` gated but `_gen`
  not, `/brain/look` gated but `/brain/explain` not). Make the two impossible to
  confuse.
- **Non-matching face templates are discarded immediately** — never persisted,
  never logged. Answering "is this one of my contacts?" requires computing a
  template for every face in frame, including bystanders who consented to
  nothing. Discarding is what keeps that defensible.

### Step 3 — the copy, timed to the release

`host-python/src/dreamlayer/tests/test_advertised_claims.py` **will fail** when a
real model ships. That is deliberate: it is a tripwire that forces the website
copy to change before the capability can reach users.

Do not change the copy early. Right now *"the shipped face embedder cannot
return an identity at all"* is **true** of the shipped build; changing it before
a model ships would make the site wrong in the other direction.

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

**Open and unresolved:** Task list item #58 (tray icons, dock-click, Learn
glass) is stale and needs a build to verify. `decisions/0001` (retention) is
closed — the fix is step 1 above.

---

## One standing instruction from the owner

The website and knowledge base are promises. When you change what the software
does, check whether a claim on `dreamlayer.app` or the knowledge base just
became false, and fix it in the same change. `test_advertised_claims.py` pins
the ones that matter; when it fails, that is the system working, not an
obstacle.
