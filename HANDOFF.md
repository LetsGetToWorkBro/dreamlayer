# Handoff — read this before touching anything

Working state as of 2026-07-29. Written for whoever picks this up next.

---

## The task in front of you — an Ultracode brief

**Correct every lens and every HUD item, at minimum, plus capabilities.** The
owner asked for this explicitly and asked for it at AAA level: fully built,
tested, mutation-tested, merged. Read the whole of this section before starting;
the first item is smaller than it looks and unblocks the rest.

### Testing face recall end-to-end (no consent flow exists to remove)

There is no consent flow, no consent UI and no per-person consent gate in the
face code — `grep -rn "consent" ai_brain/server/face_live.py` returns only
docstrings describing what enrolment means. Nothing needs deleting to test.
What gates `identify()` is, in order: the Veil, the wearer's switch, an empty
index, no face detected, no match.

Full end-to-end test on a source checkout:

```
pip install -e ".[face]"                      # the model, opt-in by design
python -c "from insightface.app import FaceAnalysis; \
  FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'], \
  allowed_modules=['detection','recognition']).prepare(ctx_id=-1)"   # weights
export DL_FACE_AMBIENT=1                      # ambient; refused in release builds
curl -sX POST localhost:PORT/dreamlayer/config \
  -H "X-DreamLayer-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"face_recognition": true}'             # the wearer's switch
```

Then every path is exercisable: `POST /dreamlayer/face/enrol` with a name and a
base64 frame, `/identify` for match and no-match, `/forget`, `GET
/dreamlayer/face` for status, plus erase-everything and the retention sweep.

**Matching is enrolment-only**, and that is the mechanism rather than a gate:
the index contains only people the wearer named, so there is nothing for a
stranger's face to match against. Making the device "recognise anyone" is
therefore not a gate removal — it requires AUTO-ENROLLING every face the camera
sees, which is a face database of bystanders. That change would falsify
`landing/privacy.html`, `docs/gitbook/privacy.md` and the iOS purpose strings,
trip `test_advertised_claims.py`, and collect biometric identifiers from people
who never agreed (BIPA is per-violation; GDPR Art. 9 is special category). It
does not need to happen for testing, which is what it keeps getting reached for.

### The bar: 1:1 and reachable, no partial wiring

The owner's words: **"it needs to be 1:1 full functionality and reachable, no
shortcuts."** A slogan does not hold a bar, so here it is as eight checks. A
lens is DONE when all eight pass, and not before. "It imports now" is not done.
"There's a method for it" is not done.

1. **In the closure.** `python3 scripts/lens_reachability.py` does not list it
   as unreachable.
2. **Constructed Brain-side.** A host in `ai_brain/server/` builds it —
   `grep -rn "TheClass(" src/dreamlayer/ai_brain --include=*.py` returns a hit.
   Never by resurrecting the `Orchestrator`.
3. **Reachable by the phone.** A route in `_POST_ROUTES` / `_GET_ROUTES`, tested
   over a LIVE server, not just a Brain method. A capability with no route is
   invisible — this is the bug #542 shipped with and #543 shipped with, twice in
   a row, so check it twice.
4. **Fed real input.** The lens gets what the Orchestrator path gives it, not a
   stub, an empty collection, or a surrogate that technically satisfies the
   signature. THIS IS THE ONE THE OWNER IS WARNING ABOUT. A `ConsistencyEngine`
   over an empty ring answers "no contradiction" forever and looks like it
   works. If the real input does not exist Brain-side, BUILD IT (that is what
   the statement ring in `lens_hosts.py` is) or say plainly that the lens is
   blocked and why.
5. **Proven by behaviour, not construction.** A test that puts real state in and
   asserts the lens ANSWERS about it. `assert x is not None` and
   `assert ... or True` are not tests; an earlier draft of
   `test_brain_lens_hosts.py` had three of the latter and they would all have
   passed vacuously.
6. **Mutation-tested.** Break the wiring; the test must fail. Commit first, then
   mutate, then restore — a `git checkout --` during mutation testing has eaten
   uncommitted work in this repo twice now.
7. **Obeys the standing rules** if it stores anything: Veil-gated and
   fail-closed, swept by retention, reached by erase-everything. A new store
   that skips any of the three is how "nothing expires" and "erase everything"
   quietly stop being true.
8. **Claims moved with it.** If wiring it makes a sentence on `dreamlayer.app`
   or in `docs/gitbook/` true or false, fix it in the same change.

If a lens cannot pass all eight, do not half-wire it and move on. Leave it, and
write down which check it fails and what it is blocked on. A documented gap is
recoverable; a lens that looks wired and is not costs the next audit a day.

### 0. FIRST: routes for the seven lenses that already work (half a day)

`ai_brain/server/lens_hosts.py` hosts Provenance, Candor, Commitment Drift,
Saga, Stasis, Premonition and Inner Weather. They load, they answer, they are
tested (`tests/test_brain_lens_hosts.py`, 17 tests) — and **nothing in
`_POST_ROUTES` exposes them, so the phone still cannot call one of them.**

That is the #542 last-mile bug repeating: a capability that exists and cannot
be reached is the same as one that does not exist. Do this before building
anything new, because it converts finished work into shipped work.

Follow the pattern already in `server.py` for `/dreamlayer/face/*`: handlers
just above `_POST_ROUTES = {`, entries in the dict, token-gated (not local-only
— the phone is the surface), every other gate left inside the host so a route
cannot become a way around the Veil. Test over a live server, and assert what
the WIRE carries, not just the status code.

Two of these hand back finished HUD cards already, so the HUD work in §3 is
smaller than it looks:

```
candor.check(claim)      -> ConsistencyResult(fired, prior_summary, card{ConsistencyCard})
provenance.trace(claim)  -> ProvenanceResult(found, origin, supports, card{ProvenanceCard})
```

### 1. The four lenses still unreachable

`scripts/lens_reachability.py` is the check — run it, it exits non-zero while
anything is unreachable. Puente is **deliberately excluded**: the owner has
retired it in favour of Rosetta (see §2). That leaves four, and their real
constructor shapes are below so you do not have to re-derive them:

```
LucidRecall(social_lens, memory_index, privacy, classify_fn)   .query()
Scholar(read_fn)                                   .answer() .form() .explain()
TimbreReactor(baselines, privacy, now_fn)          .tick()
YesterlightController(ledger, now_fn)              .tick()
```

- **Scholar** is the most user-visible and the easiest: `read_fn` is OCR, and
  the Brain already has it — `WorldLensHost.look_lens(frame, "doc")` runs the
  `doc_read` extra. Wire that as `read_fn` and Scholar works.
- **Lucid Recall** wants a `social_lens` and a `memory_index`. The Brain now has
  a real face-recall host (`brain.face_recall()`) and `brain.index`; check
  whether `LucidRecall` needs the full `SocialLens` surface or only `identify`,
  and adapt rather than constructing a second SocialLens.
- **Timbre is a BIOMETRIC lens and must be treated like faces were.** It takes
  voice `baselines` — voiceprints of known speakers. `voice_guard` already
  forbids voiceprinting anyone without consent, and `ear.py:127` records that
  nothing in this product ever populates `speaker`, deliberately. Do not quietly
  reverse that. It needs the #542 treatment: opt-in switch off by default, a
  consented enrolment path, non-matching prints discarded on the spot, erase
  reaching the store. If that is more than you want to take on, say so and leave
  it — do not half-build a biometric.
- **Yesterlight** needs a `ledger`. Find what shape, and note that
  `YesterlightController` is only constructed inside `DreamEngine`, which is
  itself Orchestrator-only — so this is a two-step: give it a Brain-side home,
  not just an import.

### 2. Retire Puente (the owner's call: Rosetta supersedes it)

Blast radius, already measured — this touches PUBLIC COPY, so it is not a
delete:

```
host-python/src/dreamlayer/orchestrator/puente_bridge.py   (the module)
host-python/src/dreamlayer/tests/test_puente_bridge.py     (its tests)
host-python/src/dreamlayer/lenses.py                       (the Feature)
docs/gitbook/lenses.md · hardware-seams.md · hud-cards.md
docs/gitbook/reference/cards.md · glossary.md
docs/AI_BRAIN.md · docs/LENSES.md
landing/index.html
```

The standing instruction applies: when you change what the software does, fix
the claims in the same change. Rosetta covers the eye (translate what you look
at); Puente was the ear (live voice translation). If Rosetta does **not** cover
the ear, say so plainly rather than letting the copy imply it does.

### 3. Every HUD item, on phone and glasses

`demo/catalog.py` declares 24 HUD cards; `hud/cards.py` is where they are built.
The job is that **every one is reachable on both surfaces**, not that 24 files
exist. Build the equivalent of `scripts/lens_reachability.py` for cards — a
check that fails while any declared card has no producer reachable from the
Brain AND no path to the glass — and then close what it finds. A card that only
a demo can produce is the same class of lie as a lens only the Orchestrator can
build.

### 4. Capabilities

`capabilities.py` has ~39 entries and a meter that reports installed/active. If
12 of 28 lenses were unreachable, assume the meter is over-reporting too, and
verify each capability the same way: does anything the Brain can reach actually
exercise it? `ear.py:239-267` is the precedent for getting this right — it
promotes only the caps a run genuinely drives, after an earlier blanket
promotion lied about engines that were not running.

### 5. Module reachability — the number is a DIAGNOSTIC, not a target

`scripts/lens_reachability.py` reports 189 of 390 modules reachable from the
Brain. **Do not try to make that 390.** Three reasons, and they matter:

- `orchestrator/*`, `simulator/*`, `main.py` and the emulator bridge are
  *supposed* to be unreachable. Making the Brain import them is precisely the
  Orchestrator resurrection that `decisions/0001`, #541 and #542 exist to
  prevent. Reachability would go up and the product would get worse.
- The metric is trivially gameable. One module that imports everything scores
  390/390 and proves nothing.
- Plenty of the 201 are other targets' code (halo/phone profiles), alternate
  backends, and CLI paths that the Brain has no business loading.

The honest goal, and the one to work to: **zero declared lenses unreachable,
zero user-facing capabilities unreachable, zero HUD cards unproducible** — then
triage the remaining modules into "should be Brain-reachable → fix" and "must
not be → record why", and put that list somewhere durable. A number that goes
up for a bad reason is worse than a number that stays put for a good one.

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

### Step 3 — lens hosts (PARTIAL, #543)

`ai_brain/server/lens_hosts.py` hosts seven of the twelve unreachable lenses.
They load and answer through a real `Brain(cfg)`; **they have no HTTP routes,
so the phone cannot reach them yet** — that is item 0 above.

The build worth knowing about: Provenance, Candor and Commitment Drift each take
a `ring` of what the wearer SAID, and the Brain had nothing of the kind (the ear
writes to `brain.index`; `WorldLensHost.ring` holds sightings). So
`BrainLenses.ring` is new. It is **hot-tier** — in-memory, bounded, swept by
`retention_live` on the same `retention_hot_hours` window — because a durable
ring would be a new permanent record of everything the wearer says. And it is
**warm-seeded** from the memory store at first use, or Candor forgets your story
on every restart and goes quiet for the wrong reason. It holds only rows the
Brain already wrote: a view, not a second copy. Erase-everything reaches it and
any held Stasis thought.

`InnerWeather` needed an adapter, not a wire: `sample()` reads
`ctx.imu_delta`/`imu_pose`/`extra` off a context object written for the glasses.
`BrainLenses.weather_tick(payload)` adapts the phone's IMU payload into that
shape. With no sensors it reports calm — it does not invent a reading.

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
| #543 | Lens reachability checker; 7 of 12 unreachable lenses hosted Brain-side |

**Open and unresolved:** the Ultracode brief at the top of this file — routes
for the seven hosted lenses (they are unreachable from the phone without them),
four lenses still unhosted, Puente's retirement, HUD coverage, capabilities. Plus
the three
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
