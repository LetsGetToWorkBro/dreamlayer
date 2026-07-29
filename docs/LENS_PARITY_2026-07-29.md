## Lens parity gap list — 1:1 and reachable

> **Status note, added when the first wave of fixes landed.** This report was
> written against `8666a2e` and is kept verbatim below — it is the measurement,
> not a to-do list, and rewriting it in place would destroy the record of what
> was actually true that day. What has since changed:
>
> **Closed.** Both blockers — the ring is fed (`EarHost.ingest_caption` →
> `BrainLenses.ingest_utterance`) and the lens set is built on a path a user
> reaches. All seven hosted lenses are routed and have a phone surface
> (`app/lenses.tsx`). §3(a) retention (both the never-running purge and the
> masked count), §3(d) Provenance's degenerate inputs (`via` is threaded
> honestly now, so `firsthand` is reachable and the room ear can never claim
> it), §3(e) the "hold that thought" no-op, §3(g) the quest tally surviving an
> erase, the `task` rows deleted by the 24 h hot window, and the five quest
> badges nothing could unlock. Scholar is wired and routed; Puente is retired.
>
> **Still open, and worth reading the detail below for.** §3(b) Inner Weather
> has a route and a lens and **no phone code posts IMU** — the lens is reachable
> and its input is not. §3(c) `/dreamlayer/live/weather` and `/dreamlayer/saga`
> remain decoys for different lenses; the new routes are `/dreamlayer/weather`
> and `/dreamlayer/quests`. Lucid Recall, Timbre (biometric — see §5) and
> Yesterlight are still unreachable. Stasis is wired but shallow: no gaze hook,
> no place signature, no IMU, and its replayed utterance is the PII-scrubbed
> line rather than verbatim, which is a deliberate narrowing recorded in
> `lens_hosts.freeze`. Commitment Drift still reads `kind="task"` only, so a
> `promise` row with a real due date is never tracked — the Orchestrator's own
> design, recorded rather than quietly changed.

*Audited 2026-07-29 at `8666a2e`, working tree clean. Repo root `/home/user/dreamlayer`; paths below are relative to `host-python/src/dreamlayer/` unless prefixed. Every claim here was verified by running a command against the code at that commit; where a claim could not be settled it says so.*

---

### The standard

A lens is done when it is **1:1 with what the primitive can actually do AND reachable from the phone** — not "it imports now", not "there's a method for it", not "the test is green". That means: in the Brain's import closure; constructed by a host in `ai_brain/server/` without resurrecting the `Orchestrator`; exposed by a route in `_GET_ROUTES`/`_POST_ROUTES` (`ai_brain/server/server.py:4372-4411` and `5303-5370`) that a client actually calls; **fed the same real input the Orchestrator path gives it** — not a stub, an empty collection, or a surrogate that satisfies the signature; and proven by a test that puts real state in and asserts the lens answers about it. A lens that is constructible, routed, and answering from an empty input is the failure this list exists to catch: it is silent for the wrong reason, and from the wearer's seat it is indistinguishable from a lens that says "all clear".

---

### 1. The table

Sorted worst-first. Status is one of `unreachable` / `importable-never-called` / `degraded-input` / `full-parity`.

| Lens | Status | What full parity needs | Blocked on |
|---|---|---|---|
| **Lucid Recall** (`lucid_recall`) | unreachable | Brain-side host + constructor `LucidRecall(social_lens, memory_index, privacy, classify_fn)`; route | A `social_lens` surface — `brain.face_recall()` may or may not satisfy it; **not determined** whether `LucidRecall` needs full `SocialLens` or only `identify` |
| **Scholar** (`orchestrator/scholar`) | unreachable | Constructor `Scholar(read_fn)` Brain-side + route | Nothing. `WorldLensHost.look_lens(frame, "doc")` is the `read_fn` and already exists |
| **Timbre** (`dream_mode/timbre_reactor`) | unreachable | Constructor `TimbreReactor(baselines, privacy, now_fn)` + consent path + route | **Voiceprint baselines that do not exist and must not be built casually — see §5.** `ear.py:129-131` records that nothing in this product ever populates `speaker` |
| **Yesterlight** (`dream_mode/yesterlight`) | unreachable | A `ledger` (shape **not determined**), a Brain-side home — it is only ever constructed inside `DreamEngine`, itself Orchestrator-only | An unidentified ledger store; two-step (home + import) |
| **Puente** (`orchestrator/puente_bridge`) | unreachable — **deliberate** | Nothing: owner has retired it in favour of Rosetta. Blast radius incl. public copy is listed in HANDOFF §2 | n/a — needs a copy change, not a wiring change |
| **Stasis** (`orchestrator/stasis`) | importable-never-called | Brain-side `freeze_context`, `resume_stasis` choreography, compost pass, pin, ambient offer, status; routes; a raw-frame or card path to the glass | Verbatim timestamped utterance (conflicts with `ear.py`'s redact-before-store rule), gaze hook, place signature, IMU, overlay tracker, IMU-gesture ingress, no bridge object |
| **Provenance** (`orchestrator/provenance`) | importable-never-called *(and degraded if wired today — see §3)* | A caller for `.trace()`, a veil gate, a route, a `ProvenanceCard` renderer, and **real `meta["person"]` / `meta["via"]`** | Speaker attribution on the write path. `ear.py:97 ingest_caption(text, speaker)` takes a `speaker` arg; nothing populates it, and diarization is deliberately dormant (`EAR_CAPS`, `ear.py:32-39`) |
| **Commitment Drift** (`orchestrator/commitment_drift`) | importable-never-called | A scheduled `tick()`, GET for records, POST nudge/keep/break, a `commitment_drift` card pushed via `push_event` | A Brain-side writer of `kind="task"` memory rows. `pipelines/ingest.py:129-158` already extracts them and is importable; nothing Brain-side runs `IngestPipeline` |
| **Saga / QuestLog** (`orchestrator/quest`) | importable-never-called | GET quests+stats, POST complete/abandon/tend, reward card push, and `saga_record('quest_done'/'quest_rescue'/'streak')` so the badges the phone shows can unlock | Commitment Drift's input chain — `QuestLog` is a pure function over `drift.all_records()` |
| **Candor** (`orchestrator/consistency`) | importable-never-called | A caller on the utterance path, a veil gate, `POST /dreamlayer/candor/check`, a card push, and **a fed ring** | A statement store. Both of its inputs are empty on a Brain-only install (§3) |
| **Premonition** (`dream_mode/premonition`) | importable-never-called | A `predict()` caller on a cadence, a confirm-sweep over new ring events, and a surface for the result | The Brain has no `HorizonComposer` and no dial-mark wire format; ghosts have nowhere to go |
| **Inner Weather** (`dream_mode/inner_weather`) | importable-never-called → **degraded-input if called** | A caller for `weather_tick`, a route, and **a phone that actually posts IMU** | Phone IMU. I could find no phone code posting `imu_delta`/`imu_pose` (§3) |
| **Name Capture** (`social_lens/introduction`), **Privacy Veil** (`memory/privacy`), **REM** (`dreamlayer.rem`) | importable-never-called (no Brain-side constructor per `scripts/lens_reachability.py`) | **Not audited this wave** — flagged from the reachability report only | not determined |
| **Retention** (`memory/retention` via `retention_live.py`) | degraded-input | Build the lens set so the statement-ring leg runs; stop masking its count | Nothing — both are one-line fixes (§3) |
| **Face recall** (`truth_lens` via `face_live.py`) | degraded-input | A client that calls `/dreamlayer/face/*`; the model extra installed | No model in a default install (deliberate); **no client anywhere in the repo** (§3) |
| **Glance Arbiter** (`orchestrator/glance` via `glance_live.py`) | full-parity\* | — | — |

\* Verified: constructed at `ai_brain/server/world_lens.py:153`, called on every live look at `ai_brain/server/live.py:377`, routed as `/dreamlayer/live/look` and `/dreamlayer/brain/look`, and the phone calls `/dreamlayer/brain/look` (`phone-app/src/state/useBrainStore.ts:564`). Its candidate set is **deliberately narrower** than the Orchestrator's (no `person`, no `find`, no `depth`) with reasons written at `glance_live.py:16-34`. I did **not** diff bid-for-bid against `orchestrator/glance.py`, so "full parity" here means the wiring is complete, not that scoring is byte-identical.

---

### 2. Why the seven `lens_hosts.py` lenses are all one gap, not seven

`ai_brain/server/lens_hosts.py` hosts Provenance, Candor, Commitment Drift, Saga, Stasis, Premonition and Inner Weather. All seven are lazy properties. **None of the seven properties is read by any production code** — an AST scan of all 49 files in `ai_brain/` for attribute access on the lens set returns exactly four nodes:

```
retention_live.py:166   ls.purge_hot
server.py:1721          self.lenses
server.py:1724          ls.forget_all
server.py:1465 / 1727   self._lenses
```

Both are teardown paths. `brain.lenses()` has **one** production call site — `server.py:1721`, inside `purge_memories()` — and `server.py:1727` sets `self._lenses = None` two lines later. So in a shipped build `BrainLenses` exists only for the few lines of an erase-everything, and no lens object is ever constructed at all.

Consequence worth stating plainly: `scripts/lens_reachability.py` lists all seven under "reachable (23)". The script's own header calls that list *"an UPPER BOUND, not proof it runs"*, and its `[no Brain-side constructor]` mark is purely syntactic — it matches any `Name(...)` call anywhere in `ai_brain/`, so `StasisStack()` inside an uncalled property satisfies it. **Do not treat a clean reachability run as evidence any of these lenses executes.**

---

### 3. The "technically works" category — wiring that exists and is partial

This is the section the standard is aimed at. Each of these has real Brain-side code that a reader would take for done.

**a) Retention — the statement-ring leg never runs, and its count is masked.**
`retention_live.py:162` reads `ls = getattr(brain, "_lenses", None)` instead of calling `brain.lenses()`. Since `_lenses` is None at every moment except inside an erase-everything, the `ls.purge_hot(cutoff)` at line 166 **never executes in production** — the statement ring the module's comment says "must age out on the SAME window" is not swept at all. Separately, line 166 does `report["hot_purged"] += ...` and line 184 does `report["hot_purged"] = int(ring.purge_before(cutoff))` — a plain assignment that **overwrites** it. So even once the ring is fed, the sweep report and the activity-ledger line ("N sighting(s) past 24h") will under-report by exactly the statement-ring count. *How you'd notice:* you wouldn't — the report is internally consistent and the sweep looks like it worked. This one arms itself the moment anyone wires `observe()`.

**b) Inner Weather — an adapter written against a payload nothing sends.**
`lens_hosts.py:254-276` (`weather_tick`) adapts a phone payload into the `ctx` shape `InnerWeather.sample` expects, and its docstring says *"the phone … already posts heading and tilt on the live path"*. A repo-wide grep for `imu_delta`/`imu_pose`/`self_prosody` across `phone-app/src` and `phone-app/app` returns **nothing**; the only hits outside `orchestrator/` and `dream_mode/` are the adapter's own lines. `weather_tick` also has no non-test caller. If someone routes it today it will receive `{}`, read zeros, and report calm — which the docstring correctly calls "honest", but which is indistinguishable from a working lens reporting a calm wearer. *How you'd notice:* the lens never leaves calm regardless of what the wearer does.

**c) `/dreamlayer/live/weather` and `/dreamlayer/saga` are decoys.**
`/dreamlayer/live/weather` → `_post_live_weather` → `live_confluence.room(brain).weather(...)`, i.e. Confluence's EntangledSky — **not** `BrainLenses.weather`/`InnerWeather`. `/dreamlayer/saga` → `_get_saga` → `brain.saga`, which is `SagaProfile(self.cfg_dir)` (`server.py:391`) — **not** `orchestrator/quest.QuestLog`. Anyone grepping the route table for "weather" or "saga" will conclude those lenses are wired. They are not.

**d) Provenance would answer, and answer wrongly, the moment it is called.** Three verified defects, all category (c):
- `meta["via"]` is written by **no production code in the repo** (11 occurrences, all in `tests/test_provenance.py`). It always resolves to the literal `"recorded"` at `provenance.py:115`, so `_FIRSTHAND_VIA` (`provenance.py:33`) never matches and `status="firsthand"` is unreachable.
- `meta["person"]` is written on **no Brain-reachable path**, so `Source.who` is always `None` and the attribution renders **"you"**. A belief recorded as "Ana said the venue is booked" traces to *"from you"* — wrong in the most misleading direction.
- `provenance.py:132` — `key = s.who or f"{s.via}:{int(s.when_ts // _DAY)}"`. With `who` always None and `via` always constant, **the same person restating the same belief on two different days counts as two independent attributions** and the card reads "CORROBORATED / 2 sources". The reachable status space collapses to {unverified, contested, *falsely* corroborated}.
*How you'd notice:* you wouldn't, unless you tested with a statement you knew came from someone else.

**e) Stasis's voice triggers already parse, and are silently dropped.**
`orchestrator/voice.py:342,345` map "hold that thought" → `stasis_freeze` and "where was I" → `stasis_resume`. `_post_voice` (`server.py:4927-4963`) imports that same `parse_intent` but has no branch for either, so both fall through to `else: self._json(200, {"intent": it.kind, **it.args})`. `phone-app/app/now.tsx:110` renders an unmatched intent as `` `(${r.intent})` ``. **A user who says "hold that thought" today gets a 200 OK and the on-screen text `(stasis_freeze)` while nothing is frozen.** This is worse than absent — it is a working-looking no-op, and it is live in the shipped product.

**f) Face recall has routes and no client.**
`/dreamlayer/face/{enrol,identify,forget,consent,name}` are registered (`server.py:5332-5336`) with a versioned consent gate, a wearer switch (`face_recognition`, default False), a model gate, and `ambient_allowed()` that refuses in frozen builds regardless of env. But a repo-wide grep for those paths returns only `server.py`, `tests/test_face_recognition.py`, `HANDOFF.md` and `docs/gitbook/privacy.md` — **no phone-app screen, no panel UI, no Live Lens call**. Check 3 ("reachable by the phone") passes on the letter and fails on the point. Also: `HANDOFF.md:94-95` currently states *"There is no consent flow, no consent UI and no per-person consent gate in the face code"* — that is **stale**, falsified by `face_live.py:264-296` and the `/face/consent` route added at `9f0f7c5`/`8666a2e`. Fix that line when you touch this.

**g) Erase-everything does not reach the quest tally.**
`BrainLenses.forget_all()` clears the ring and unlinks the stasis file — its docstring says "Erase-everything must reach these too" — but never touches `<cfg_dir>/vault/quest_log.json`, which `QuestLog` writes and re-reads on next load. `purge_memories` only nulls `self._lenses`. Verified empirically in the audit: after `forget_all()` a freshly built lens set still reports `xp=50, streak=1, completed=1, achievements=['Keeper']`. This is a behavioural record of the wearer surviving an erase. The Orchestrator has the same hole, so it is not a regression — but the Brain path explicitly claims to close it.

---

### 4. Blocked on — order the work by unblocking

Nearly everything downstream of `lens_hosts.py` is blocked on **two** things. Fix these two and five lenses unblock at once.

**BLOCKER 1 — the statement ring is never fed (blocks Candor, Provenance, Commitment Drift, Saga, Stasis's snapshot).**
`BrainLenses.observe()` (`lens_hosts.py:176`) is the only live append path and has zero non-test callers. And the warm seed is empty too: `_seed()` filters `MemoryDB` rows to `SPOKEN_KINDS` (`lens_hosts.py:66`), but **no code under `ai_brain/` ever calls `add_memory`** — the one Brain-reachable writer is `ember/ceremony.py:92` with `TOMBSTONE_KIND = "ember"`, which `SPOKEN_KINDS` excludes. Worse: every Brain-side `MemoryDB(...)` construction is guarded by an existence check (`lens_hosts.py:135`, `retention_live.py:118-120`, `server.py:1675`, `server.py:2184`), so **the Brain cannot even create `dreamlayer.db`**. Both tiers are empty by construction on a Brain-only install.
*Note the trap:* `brain.index` (which `ear.py:143` writes to) is **not** a substitute for the warm tier — `ai_brain/server/index.py:156-162` shows it is an in-memory list with no persistence, and `reindex()` at `index.py:86` empties it. It can serve as a live source only.

**BLOCKER 2 — no lens set is ever built (blocks all seven + the retention ring sweep).** `brain.lenses()` needs a production construction path that is not erase-everything.

Then, per lens:

- **Provenance / Timbre / any speaker-aware lens** — blocked on **speaker attribution**. `ingest_caption(text, speaker)` has the parameter; nothing fills it; diarization is dormant by design. Without it, `who` cannot exist and corroboration cannot be measured by source.
- **Commitment Drift** — blocked on a **`kind="task"` writer**. The extractor exists and is importable (`pipelines/ingest.py:129-158`); nothing Brain-side runs it. Also note the **hot-window mismatch**: the drift lifetime is 48 h and due dates run days out, but `retention_hot_hours` defaults to 24 h, so once the ring purge actually runs it will silently delete in-force commitments. `memory/retention.py:31` already exempts `task` as a COLD kind — mirror that.
- **Saga** — blocked on Commitment Drift only.
- **Stasis** — blocked on the most: a live ring, a **timestamped verbatim utterance** (which *conflicts with `ear.py`'s redact-before-store policy — that is a decision, not plumbing*), a gaze hook, a place signature, phone IMU, an overlay tracker, an IMU-gesture ingress path, and a **raw-frame channel**. `halo-lua` ships the complete receiving end (`ble/host_comm_stasis.lua`, `display/stasis.lua`, `renderer.lua`) waiting on `{t="stasis", mode=…}` frames the Brain has no bridge to emit.
- **Premonition** — blocked on a surface. The Orchestrator emits ghosts as `KIND_PREMONITION` marks inside the horizon frame; the Brain has no `HorizonComposer` and `push_event` carries cards, not dial marks.
- **Inner Weather** — blocked on **phone IMU**, which I could not find being posted anywhere.
- **Scholar** — blocked on nothing. Cheapest unblock on the list.
- **Lucid Recall** — blocked on determining whether it needs full `SocialLens` or only `identify`. Not determined here.
- **Yesterlight** — blocked on an unidentified `ledger` shape. Not determined here.
- **Card rendering (all of them)** — *not* blocked on a transport. `Brain.push_event(kind, card, veil_ok)` (`server.py:967`) is the Brain's `bridge.send_card` and is already used by `ear.py:184` and the morning brief. What is missing is the call and a renderer. Note the degradation: every shipped fallback renderer draws `primary` (+ sometimes `detail`) and **drops `footer`** — and `footer` is where `ConsistencyCard` puts the prior statement, i.e. Candor's entire proposition. A generic fallback is not sufficient for these two cards.

---

### 5. Biometric and privacy-sensitive — do not wire without a consent path

- **Timbre (`dream_mode/timbre_reactor`) — BIOMETRIC. Hard stop.** It takes voice `baselines`, i.e. **voiceprints of identified speakers**. `voice_guard` already forbids voiceprinting anyone without consent, and `ear.py:129-131` records that nothing in this product ever populates `speaker` *deliberately*. Wiring Timbre means reversing that. It needs the full face treatment: opt-in switch off by default, a consented enrolment path, versioned consent, non-matching prints discarded on the spot, erase-everything reaching the store, retention sweeping it. **If that is more than you want to take on, leave it and write down why — do not half-build a biometric.**
- **Face recall — BIOMETRIC, already built, gates verified.** Consent version + wearer switch (default off) + model gate + `ambient_allowed()` refusing in frozen builds + `_discard` as the only exit from the no-match path + retention sweeping unnamed faces (`retention_live.py:173-179`). The residual risk to watch is `face_auto_enrol` (`store.py:555`, default `False`): with it on, `identify()` at `face_live.py:378-385` enrols **every face seen, including people who did not agree**. Any UI that exposes that toggle must carry the consent text, and any change to its default falsifies `landing/privacy.html`, `docs/gitbook/privacy.md` and the iOS purpose strings.
- **Provenance / Candor / the statement ring — privacy-sensitive, not biometric.** The ring is a timeline of what the wearer said. `lens_hosts.py` made it hot-tier and swept precisely so it is not a permanent transcript — and §3(a) shows the sweep does not currently run. Any read path (`trace()`, `check()`) must be veil-gated. Note for whoever writes that gate: the Orchestrator's precedent gates on `allow_capture()` (`ops_world_lenses.py:37`), and in `_LensGate` (`lens_hosts.py:84-85`) `allow_recall()` is literally `return self.allow_capture()` — the two are the same predicate, so gate on either but gate on *something*.
- **Stasis — policy conflict, flag before building.** Its climax is replaying the wearer's own unfinished sentence verbatim. `ear.py:115-120` scrubs PII **before** anything is stored and `ear.py:286` deliberately does not echo the last transcript. A verbatim, timestamped utterance slot is a new privacy surface, not plumbing. Decide it explicitly.

---

### 6. How to verify each of these is actually fixed

Run from `/home/user/dreamlayer`. Commit before mutating anything.

```bash
# 0. Closure — must exit 0
python3 scripts/lens_reachability.py; echo "exit=$?"

# 1. Constructed AND READ. Today this returns only lens_hosts.py's own
#    definitions. A fixed lens shows a read from a non-lens_hosts file.
grep -rn "\.candor\|\.provenance\|\.drift\b\|\.saga\b\|\.stasis\b\|\.premonition\|\.weather_tick" \
  --include=*.py host-python/src/dreamlayer/ai_brain | grep -v /tests/ | grep -v lens_hosts.py

# 2. The lens set is built outside erase-everything. Today: exactly one hit,
#    server.py:1721 inside purge_memories.
grep -rn "lenses()" --include=*.py host-python/src/dreamlayer | grep -v /tests/

# 3. Routes exist AND a client calls them. Both halves, per lens:
grep -n "candor\|provenance\|drift\|quest\|stasis\|premonition\|inner_weather" \
  host-python/src/dreamlayer/ai_brain/server/server.py | grep '"/dreamlayer'
grep -rn "/dreamlayer/candor\|/dreamlayer/provenance\|/dreamlayer/quest\|/dreamlayer/stasis" \
  phone-app/src phone-app/app
# (run the same second command for /dreamlayer/face — today it returns nothing)

# 4. FED REAL INPUT — the check that matters. Over a LIVE server:
curl -sX POST localhost:$PORT/dreamlayer/live/hear -H "X-DreamLayer-Token: $TOK" \
  -d '{"text":"the deposit was paid on Friday"}'
python3 -c "import sys; sys.path.insert(0,'host-python/src'); \
 from dreamlayer.ai_brain.server.server import Brain; \
 b=Brain('$CFG'); print('ring:', len(b.lenses().ring))"   # must be > 0, is 0 today
```

Per-lens behavioural assertions — each must FAIL before the fix and PASS after:

```
Candor         two contradictory utterances via POST /dreamlayer/live/hear, then the
               candor route; assert fired=True AND that the card's FOOTER (the prior
               statement) survives to the surface the wearer sees, not just the JSON.
Provenance     record "Ana said the venue is booked", trace "the venue is booked";
               assert origin.who == "Ana" (today: None → renders "you")
               assert status can be "firsthand" for a self-observed statement
                      (today: unreachable — _FIRSTHAND_VIA never matches)
               repeat ONE statement on two different days; assert corroboration == 1
                      (today: 2, card reads "CORROBORATED / 2 sources")
Drift          seed a kind="task" row with due 3d out; advance clock past 24h;
               assert the record still exists after a retention sweep
                      (today the 24h hot purge deletes it once the ring is live)
Saga           complete a quest; assert GET /dreamlayer/saga shows the Keeper badge
                      (today those five badges can never unlock — nothing emits
                       quest_done/quest_rescue/streak)
               then purge_memories; assert <cfg_dir>/vault/quest_log.json is GONE
                      and a fresh lens set reports xp=0 (today: xp=50 survives)
Stasis         curl POST /dreamlayer/voice -d '{"text":"hold that thought"}'
                      assert the response is NOT a bare {"intent":"stasis_freeze"}
                      (today the phone renders the literal string "(stasis_freeze)")
Inner Weather  assert the phone actually POSTs imu_delta/imu_pose on the live path
                      (grep phone-app for those keys — today: zero hits), then assert
                      weather_tick returns something other than calm under motion
Retention      populate BOTH the sighting ring and the statement ring, run one sweep,
                      assert report["hot_purged"] == sum of both
                      (today line 184 overwrites line 166's count)
Face           full end-to-end per HANDOFF's face section (pip install -e ".[face]",
                      weights, DL_FACE_AMBIENT=1, face_recognition:true), then assert
                      a UI surface reaches /dreamlayer/face/identify
```

```bash
# 5. Mutation test — the fix is not proven until this fails.
#    Commit first. Break the wiring (delete the observe() call, or the route entry,
#    or make the veil gate return True unconditionally), run the lens's test,
#    confirm RED, then: git checkout -- <file>
```

```bash
# 6. Claims moved with the code. Any lens you wire — or explicitly declare
#    emulator-only — must have its sentence fixed in the same change:
grep -rn "trace any belief\|shimmer\|hold that thought\|Candor" landing/index.html \
  docs/gitbook/ README.md docs/STASIS.md
python3 -m pytest host-python/src/dreamlayer/tests/test_advertised_claims.py
# Known-false today: landing/index.html:1568 (Premonition ghosts), :1597,:1603
# (Provenance "who told you"), :1602 (Candor), docs/STASIS.md "Tier behavior"
# (claims the Phone tier delivers freeze/decay/resume/verbatim — all four are
# Orchestrator-only), and HANDOFF.md:94-95 (says no face consent flow exists;
# one was added at 9f0f7c5/8666a2e).
```

---

**Not determined in this audit, stated rather than guessed:** the constructor shape `Yesterlight` needs for its `ledger`; whether `LucidRecall` requires the full `SocialLens` surface or only `identify`; whether `glance_live.py`'s bid scoring matches `orchestrator/glance.py` bid-for-bid (wiring verified, scoring not diffed); and the status of Name Capture, Privacy Veil and REM beyond the reachability report's `[no Brain-side constructor]` mark. Also unresolved: if a machine has previously run the emulator (`main.py`) or simulator against the same `$DREAMLAYER_DB`, the warm seed *would* find rows — but no shipped Brain code path creates them, so this cannot be relied on.
