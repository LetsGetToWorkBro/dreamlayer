# Implementation plan — wiring HUD cards from the Brain

Verified against the tree at `/home/user/dreamlayer` (clean working tree). Every line number, signature and grep in this plan was re-run, not carried over. Three empirical results drive decisions below:

1. **`self.push_event(...)` inside `WaypathOps` is a hard mypy failure today.** I injected the call and ran the real checker:
   `src/dreamlayer/ai_brain/server/brain_waypath.py:73: error: "WaypathOps" has no attribute "push_event"  [attr-defined]` — file restored.
2. **`push_event` reaches exactly one renderer, and it is not `halo-lua`.** `renderEvent` (`live.py:2875-2891`) has bespoke branches for `HarkCard`, `MorningBriefCard`, `PersonDossierCard` only; everything else falls to `glassEventCard` (`live.py:1387-1397`), which draws **`c.eyebrow` and `c.primary` and nothing else**.
3. `python3 scripts/hud_reachability.py` currently reports **18** cards with no Brain-side producer. This plan takes it to **15**.

Consequence of (2) that the per-card audit applied to FactCheck/TruthLens/AnswerAhead but **not** to ObjectRecall: `object_recall()` puts the object name in `primary` and the **place in `place`** (`hud/cards.py:88-105`), and `renderer.lua:651` draws `place` as the hero. Pushed to the Live Lens as-is, "where's my bike" renders **`JUNO / bike`** — the object echoed back, the answer dropped. That is not a card worth shipping. **Batch A therefore adds the renderer branch before the producer exists**, so no intermediate state draws a gutted card.

---

## Part 1 — The wire-now batches, one file at a time

Four cards were proposed as `wire-now`; three survive. `DeviationAlertCard` was already correctly downgraded (a measured score of 0.12–0.24 against a 0.55 threshold is not a producer). `SavedMemoryCard`, `JunoReplyCard` and `ObjectRecallCard` ship, in this order.

### Batch A — `host-python/src/dreamlayer/ai_brain/server/live.py` (renderer first)

**Why first:** `ObjectRecallCard` has no bespoke branch on the Brain's only glass. Landing the push before the branch ships a one-word card. This batch is inert on its own — a branch for a type nothing pushes yet.

**Edit A1** — add a renderer beside `glassDossierCard` (defined `live.py:1322`). Mirror `renderer.lua:646-653`'s slot semantics exactly: `last_seen` is the eyebrow, the object is the label, **`place` is the hero**.

```js
function glassObjectRecallCard(c){                   /* WHERE YOU LEFT IT */
  const ctx = glassCtx(); gback(ctx);
  garc(ctx, 128, 150, 52, 0, 360, GP.border_subtle);        /* the place as a field */
  ctx.save(); ctx.shadowColor = GP.memory_trace; ctx.shadowBlur = 7;
  gdiamond(ctx, 128, 96, 7, GP.memory_trace); ctx.restore(); /* the thing as a jewel */
  gtext(ctx, String(c.last_seen || "").slice(0, 24), 128, 50, GP.text_ghost, "sm");
  gtext(ctx, String(c.object || c.primary || "").slice(0, 20), 128, 70, GP.memory_trace, "sm");
  const place = gwrap(String(c.place || "").trim(), 22).slice(0, 2);
  place.forEach((ln, i) => gtext(ctx, ln, 128, 150 + i * 16, GP.text_primary, "md"));
  gend(c.dismiss_ms || 3500);
}
```

**Edit A2** — in `renderEvent` (`live.py:2875`), insert one line before the `else glassEventCard(c);` fallthrough at `live.py:2890`:

```js
  else if (t === "ObjectRecallCard") glassObjectRecallCard(c);
```

Do **not** add `blip()`/`scan()`. Only `HarkCard` earns a sound; `object_recall()` supplies no `earcon` and must not borrow one.

**Do not touch** `glassEventCard` itself. `SavedMemoryCard` (`primary: "Held."`, no eyebrow) and `JunoReplyCard` (`eyebrow: "JUNO"`, `primary: <answer>`) are *exactly* eyebrow+primary cards — the generic renderer is the right renderer for both, and adding branches for them is churn.

---

### Batch B — `host-python/src/dreamlayer/ai_brain/server/_brain_host.py`

Pure type declaration. No runtime effect — the entire class body is under `if TYPE_CHECKING` (module docstring, lines 10-16).

**Edit B1** — after line 86 (`def incognito_now(self) -> bool: ...`), inside the `if TYPE_CHECKING:` block, at the same indent:

```python
        # The Live Lens push channel. Declared here because WaypathOps now
        # pushes an ObjectRecallCard on a found locate, and push_event is
        # defined on the composed Brain (server.py:967), not on any mixin.
        def push_event(self, kind: str, card: Any = None,
                       veil_ok: bool = False) -> int: ...
```

`Any` is already imported (line 20). This is mandatory, not tidiness: `.github/workflows/pytest.yml:55` runs `python -m mypy src/dreamlayer` over the whole tree, `brain_waypath` is not in the `ignore_errors` list (`pyproject.toml:196-218`), and I reproduced the failure above.

**Check:** `cd host-python && python -m mypy src/dreamlayer/ai_brain/server/_brain_host.py` → clean.

---

### Batch C — `host-python/src/dreamlayer/ai_brain/server/brain_waypath.py` — **ObjectRecallCard**

**Edit C1** — in `WaypathOps.waypath_locate` (def line 64), replace the found-branch return at lines 73-75:

```python
        pushed = 0
        if cue.place:                    # nothing spatial to draw otherwise
            try:
                from .brain_social import _ago      # (ts, now=None) — NOT live_dream._ago
                from ...hud import cards
                ts = next((getattr(a, "ts", 0.0) for a in self.waypath.anchors()
                           if (getattr(a, "subject", "") or "").strip().lower()
                              == (cue.subject or "").strip().lower()), 0.0)
                pushed = self.push_event("object_recall", cards.object_recall({
                    "object":     cue.subject,   # the STORED anchor, never the caller's arg
                    "place":      cue.place,     # renderer.lua:651 draws this as the HERO
                    "detail":     "",            # cue.text is "at <place>" — the same words twice
                    "last_seen":  _ago(ts),      # "" when Anchor.ts is 0 (waypath.py:42)
                    "confidence": 0.9,           # live_dream.py:145 scores these same anchors 0.9
                }), veil_ok=False)
            except Exception:            # noqa: BLE001 — a card must never fail the answer
                pushed = 0
        return {"intent": "locate", "ok": True, "found": True,
                "subject": cue.subject, "place": cue.place, "detail": cue.text,
                "pushed": pushed,
                "say": f"Your {cue.subject} — {cue.text}."}
```

Do **not** touch the not-found branch (lines 70-72).

Five things are load-bearing and each was re-verified:

- **The `cue.place` guard.** `waypath_stash` accepts `place=""` (`brain_waypath.py:55-63`, fed by `server.py:5037-5038`). `waypath.py:123` then makes `cue.text = "somewhere you saved it"` with `place=""` — an ObjectRecallCard whose hero slot is blank.
- **`detail=""`.** `remember_place` sets place only (`waypath.py:83-87`), so `has_bearing()` is always False Brain-side and `waypath.py:123` yields `text = "at " + place`. Passing it as `detail` prints the place twice at two different clip bounds (22 vs 18, `cards.py:84-86`).
- **`confidence=0.9`, not `None`.** `renderer.lua:602` initialises `jcol = P.confidence_med` and only overrides inside `if conf then` — `nil` renders as *medium confidence*, not neutral. 0.9 is the value `live_dream.py:145` already assigns these exact anchors.
- **`cue.subject`, never the caller's string.** `locate` does a substring match (`waypath.py:106-108`), so the argument and the anchor can differ. Rule 3: the argument must not be rendered or logged.
- **`pushed` in the response.** This copies the precedent at `server.py:4966-4974` and its documented rationale — *"a silently-swallowed push would reproduce the very bug this fixes (200 OK, nothing on the glass)"*. It also makes the behavioural test a pure function call with no SSE plumbing.

**Acceptance:** `python3 scripts/hud_reachability.py` → 17.

---

### Batch D — `host-python/src/dreamlayer/ai_brain/server/lens_hosts.py` — **SavedMemoryCard**

**Edit D1** — in `BrainLenses.pin` (def line 728), replace the body of the `try` at lines 733-740:

```python
        try:
            frame = self.stasis.get(int(frame_id))
            if frame is None:
                return False
            if frame.meta.get("pinned"):
                return True                    # already pinned — no second flash
            self.stasis.replace_frame(frame.pinned())
            self.save_stasis()
            from ...hud import cards
            self._push("saved_memory", cards.saved_memory("Held."))
            return True
```

`"Held."` is verbatim from `orchestrator/ops_stasis.py:326` and is the *whole* payload that draws: `renderer.lua:517` reads `card.primary` only, `glassEventCard` reads `primary` + an eyebrow fallback. A two-key card is exactly enough. `frame.meta` is the same dict already read at `lens_hosts.py:769`, so the guard needs nothing new.

No `_brain_host` change: `_push` (`lens_hosts.py:782-791`) is a method on `BrainLenses`, which holds a real `self.brain`. `_push` hard-codes `veil_ok=False` at line 789 — do not route around it.

**Acceptance:** `python3 scripts/hud_reachability.py` → 16.

---

### Batch E — `host-python/src/dreamlayer/ai_brain/server/server.py` — **JunoReplyCard**

**Edit E1** — in the nested `_post_voice` (def line 5009), replace the ask/recall response at lines 5021-5022:

```python
                out = {"intent": it.kind, "query": it.args.get("query", ""),
                       "answer": ans.text if ans is not None else ""}
                reply = out["answer"].strip()
                if reply:
                    try:
                        from ...hud import cards
                        out["pushed"] = brain.push_event(
                            "juno", cards.juno_reply(reply[:160], "answer"),
                            veil_ok=False)
                    except Exception:      # noqa: BLE001 — never fail the answer
                        out["pushed"] = 0
                self._json(200, out)
```

- `ans` is the local already bound at 5019-5020; `brain` is the closure variable the handler already uses.
- `from ...hud import cards` resolves to `dreamlayer.hud.cards` — the identical form at `server.py:1526` and `server.py:4969`.
- `kind="answer"` matches `_juno_say`'s tone for ask/recall; event kind `"juno"` matches its default (`orchestrator.py:816`).
- `[:160]` matches `ops_confluence.py:130`. The honest reason is payload hygiene on a fan-out queue capped at `maxsize=64` (`server.py:953`) — **not** glass overrun; both renderers already truncate (`glassEventCard` wraps to 24 and slices 3; `draw_juno_reply` calls `text_block(..., 3)`).
- **No log line.** The reply is derived from the wearer's memory; `tests/test_logging_discipline.py` forbids interpolating it.

**Explicitly out of scope for this batch** — see Part 2: do **not** wire `res["say"]` on the action branches (5029/5035/5039-5042), and do **not** add this push to `_post_brain_ask` (`server.py:4597`).

**Acceptance:** `python3 scripts/hud_reachability.py` → 15.

---

## Part 2 — Cards that would push at the same moment

Per-card analysis cannot see these. Two are real, and both are created by *the obvious next edit*, not by this plan.

### Collision 1 (real, and one edit away) — ObjectRecallCard + JunoReplyCard on `POST /dreamlayer/voice`

`waypath_locate` returns **`"say": f"Your {cue.subject} — {cue.text}."`** (`brain_waypath.py:75`), and `_post_voice` routes `locate` at `server.py:5039-5040`. The ask/recall branch returns `"answer"`, not `"say"` — so today the two are mutually exclusive and there is no bug.

The moment anyone generalises the JunoReply push to *"push a JunoReplyCard whenever the response carries `say`"* — the natural, tidy-looking follow-up that the per-card note explicitly parks as "a separate change" — a single "where's my bike" pushes **two cards in one request**: an ObjectRecallCard reading `bike / at the north rack`, and a JunoReplyCard reading `Your bike — at the north rack`. Same words, two cards, one question.

**Write this rule into the code.** Add it as a comment above Edit E1:

```python
                # ONE card per wearer utterance. `locate` already pushes its own
                # ObjectRecallCard (brain_waypath.waypath_locate); if a generic
                # `say` -> juno_reply push is ever added below, it MUST exclude
                # every branch that pushes its own card, or one question draws two.
```

The branches that must be excluded from any future `say`-driven push: `stash`, `locate`, `note_person`, `meet_person`, `debt`, `debt_settle`, `reply`, `stasis_freeze`, `stasis_resume`.

### Collision 2 (real, on a different surface) — JunoReplyCard + the Live Lens's own answer

`_post_brain_ask` (`server.py:4597`, `ans` at 4650) is the route the Live Lens page itself posts to (`live.py:2449`), and it already draws its own answer locally at `live.py:2464` (`showHud(j.text); setTier(j.tier); speak(j.text)`). Adding the same push there means the page that asked draws the answer twice — once as its own HUD, once as a pushed card.

`_post_voice` is provably the non-duplicating seam: `grep -rn "live/events\|EventSource" phone-app/src phone-app/app` returns nothing, so the client that calls `/dreamlayer/voice` has no SSE subscriber at all. **Wire `_post_voice` only.**

### Checked and cleared

- **SavedMemoryCard vs StasisCard.** `freeze` pushes at `lens_hosts.py:694`, `resume` at `:721`, `pin` now at `:741`. Three distinct routes, three distinct wearer actions. `lenses.tsx:254` only renders Pin when `!f.pinned`, and the new `meta.pinned` guard closes the direct-POST re-flash.
- **ObjectRecallCard vs WaypathCard.** The Orchestrator pushes a WaypathCard on the found branch (`ops_world_lenses.py:319-321`); the Brain has no WaypathCard producer and this plan adds none. No overlap — but see the mapping note below.

### One mapping divergence to record, not to hide

The Orchestrator's found-locate pushes a **WaypathCard**; **ObjectRecallCard** is what its *not-found* branch produces, via `retrace` (`ops_commitments.py:92 → 129-131`). Batch C therefore introduces a **new producer mapping**, not parity. It is defensible — `grep -rn WaypathCard halo-lua/` returns nothing, so WaypathCard has no glass branch at all and `hud/renderer.py:657` sends it to the generic layout — but write it down in the commit message. Do not describe Batch C as "matching the hub".

Second divergence, same batch: the Orchestrator gates *both* arms of `_locate` on recall (`ops_commitments.py:86 → ops_world_lenses.py:316-317`, returning "Not while you're incognito."). The Brain's `waypath_locate` has **no gate on the JSON**. Wiring the card does not create that gap, but it does mean that under the shield the phone still speaks the answer while the glass stays dark. State that; do not call it parity.

---

## Part 3 — The one behavioural test per card

Each is a real `Brain` on a temp dir, following the `test_live_events.py:22-24` fixture (`Brain(tempfile.mkdtemp())`). Each names the mutation that must make it fail — a test that survives its own mutation is not proving the wiring.

### ObjectRecallCard

**Do:** `b.waypath_stash("bike", "the north rack")`, then `q = b.subscribe_events()`, then `out = b.waypath_locate("bike")`.

**Must appear:** `out["pushed"] == 1`; `ev = q.get_nowait()`; `ev["kind"] == "object_recall"`; `ev["safety"] is False`; `ev["card"]["type"] == "ObjectRecallCard"`; **`ev["card"]["place"] == "the north rack"`** and `ev["card"]["object"] == "bike"` and `ev["card"]["detail"] == ""` and `ev["card"]["confidence"] == 0.9`.

**Mutation that must fail it:** replace `cards.object_recall({...})` with a hand-rolled `{"type": "ObjectRecallCard", "primary": cue.subject, "detail": cue.text}`. The `place` assertion breaks — which is the whole point, because that hand-roll is precisely what `renderer.lua:651` and `glassObjectRecallCard` read as the hero and would render blank. (This is the `_drift_card` failure the comment at `lens_hosts.py:528-546` documents, reproduced.)

**Second, non-optional assertion in the same test:** stash with `place=""`, locate, assert `out["pushed"] == 0` and the queue is empty. Mutation: delete the `if cue.place:` guard → a card whose hero slot is blank gets pushed.

### SavedMemoryCard

**Do:** freeze a frame through `BrainLenses.freeze(...)`, drain the queue, then `q = b.subscribe_events()` and call `lenses.pin(frame_id)`.

**Must appear:** `ev["kind"] == "saved_memory"`; `ev["safety"] is False`; `ev["card"] == {"type": "SavedMemoryCard", "dismiss_ms": 1200, "primary": "Held.", "lines": ["Held."]}` — assert the **whole dict**, it is four keys.

**Mutation that must fail it:** call `pin(frame_id)` a second time and assert the queue is empty. Removing the `if frame.meta.get("pinned"): return True` guard makes a re-POST re-flash the confirmation for a moment that was already kept.

**Do not** assert that `frame.final_utterance` appears anywhere. Assert the opposite: `"Held." == ev["card"]["primary"]` and the wearer's held sentence is nowhere in `ev`. That is the standing-rule-3 half of this test.

### JunoReplyCard

**Do:** stub `brain.ask` to return an `Answer` with `text="Canberra."`, `q = b.subscribe_events()`, POST `/dreamlayer/voice` with `{"text": "what is the capital of australia"}` (or call the handler as `tests/test_brain_controls.py:243-271` already does).

**Must appear:** response body carries `"pushed": 1`; `ev["kind"] == "juno"`; `ev["safety"] is False`; `ev["card"]["type"] == "JunoReplyCard"`; `ev["card"]["primary"] == "Canberra."`; `ev["card"]["eyebrow"] == "JUNO"`; and **`"earcon" not in ev["card"] and "haptic" not in ev["card"] and "flash" not in ev["card"]`** — the anti-spoof assertion, mirroring the discipline `server.py:1092-1093` applies to self-tests.

**Mutation that must fail it:** push `cards.juno_reply(vb.get("text",""))` — the *caller's question* — instead of `ans.text`. Assert `ev["card"]["primary"] != "what is the capital of australia"`. This is the exact primitive `server.py:4958-4964` refuses to create ("arbitrary-text-onto-every-glass").

### The veil test, once, covering all three

`b.config.network_mode = "lan_only"` (so `incognito_now()` is True, `server.py:1280-1283`), then run all three triggers and assert **`pushed == 0` and every queue is empty**, while the JSON answers still come back non-empty. Mutation: change any `veil_ok=False` to `True` → the test fails. This is the assertion that proves the glass goes dark under the shield while the phone still answers — the divergence recorded in Part 2.

---

## Part 4 — Orchestrator-only, with the sentence to write down

Two cards. Both belong in a short `decisions/` note or a comment beside their builder. The wording is the deliverable — it has to survive someone asking "why didn't you just wire it?"

### ReadyCard

> `ReadyCard` is the device's idle state, not a message about it. Its entire payload is `{"type": "ReadyCard", "dismiss_ms": 0}` — no primary, no eyebrow, nothing to say. On the glasses that is correct: `main.lua:78` files it as `CardQueue.AMBIENT` and `renderer.lua:1828` draws the full Juno-core-and-rings Horizon from the type alone. On the Brain's only surface it cannot be expressed: `push_event` fans out to `/live/events`, whose renderer draws `c.eyebrow || "JUNO"` and `c.primary || c.text` — so a pushed ReadyCard renders a ring, the word JUNO, and a literal ellipsis for six seconds (`dismiss_ms: 0` is falsy in JS and becomes 6000, `live.py:1396`). A card meaning "nothing is happening" cannot be sent over a channel that exists to announce that something is. `docs/gitbook/reference/cards.md:12` already attributes it to boot/resume/connect with Renderer `device`; nothing needs correcting.

### TruthLensCard

> `TruthLensCard` is a biometric read on another person's face and voice, and the Brain has neither the inputs nor the standing to produce it. Its nine `stages` come from `schema.gauge_stages` (`truth_lens/schema.py:240`), which reads `au_frame` / `prosody_frame` / `linguistic_frame`; those arrive through `observe_face` / `observe_voice`, which `docs/gitbook/hardware-seams.md:66` declares hardware seams on the device. `truth_lens/fusion.py:85` needs a calibrated per-contact baseline, and persisting those would be a new durable store of other people's behavioural profiles. `landing/index.html:1603` promises it is "Explicit, never running in the background" — the Brain has no explicit invocation to hang it on, and `analyzer.py:40` sets `EMIT_COOLDOWN_S = 3.0` on a display-update hook, so any plausible Brain trigger (`/live/look`, `/live/hear`) would emit a verdict on a stranger's face every three seconds for as long as the wearer looked at them. This is a product decision about non-consenting third parties, and the shipped design already made it: `ops_conversation.py:132` takes the credibility read as a *modifier* folded into a FactCheckCard footer, never as its own card. Note also that the builder is a subset of the shipped payload — `truth_gauge_card()` omits `is_stranger`, which `truth_lens/renderer.py:44` reads to decide suppression — so "always call the real builder" would make this card *less* honest, not more. That gap in `hud/cards.py:771` should be closed before anyone applies that rule to this type.

### Also not "wire-now", for the record

**`PrivacyVeilCard` — already produced, on the device.** The live producer is the FSM long-press at `halo-lua/app/state_machine.lua:101-103, 135-137, 157-159, 180-182`, bound to the physical button via `main.lua:229-230, 443-450`. `push_event` has no path to `halo-lua` (`grep -rn "send_card" ai_brain/server/*.py` → zero hits), so a Brain push cannot reach the shield notice's actual surface; it would land on the Live Lens page, which already renders the veil from its own status read (`live.py:3390`) and its own button (`live.py:1955`). `docs/gitbook/reference/cards.md:37` — "the veil lands | device" — is already exactly true. **If anyone proposes `veil_ok=True` for it, refuse on the eviction argument:** `server.py:981` stamps `ev["safety"]`, and `_evict_for_safety` (`server.py:1008-1031`) uses that stamp to drop the oldest non-safety event from a full queue. A `veil_ok` privacy notice would evict a queued smoke-alarm HarkCard. `push_selftest`'s docstring (`server.py:1051-1057`) already ruled on this exact argument in the opposite direction.

**`SynesthesiaCard` — already produced, under the other key.** `live_dream.py` and `dream_mode/scene_describer.py:118` both build `synesthesia_card_v2`, and both are Brain-reachable. The checker flags it because `demo/catalog.py:53` points `Feature("inner", ...)` at the stale `"synesthesia"` sample key. This is a **catalogue fix, not a wiring job** — and it is *not* free, so it does not belong in the batches above: changing the key leaves a stale committed `preview.webp` (26,642 bytes, regenerated only by `tools/demo-kit/gen.py:208-209`) under `docs/gitbook/lenses.md:59`, where it sits beneath the **Inner Weather** bullet — a different surface entirely (`lens_hosts.py:381`, served at `/dreamlayer/weather`, which returns renderer frames, never a card). Decide the title/blurb question first, then change the key, then regenerate. Do not let the checker's green push this through.

---

## Part 5 — needs-new-input, with size and decision flags

| Card | Missing input | Size | Flag |
|---|---|---|---|
| **CommitmentRecallCard** | A firsthand-utterance producer that actually runs. `useLensStore.observe` (`useLensStore.ts:226-242`) has **zero call sites** — `lenses.tsx` calls `st.pin` and nothing else, and `via="typed"` appears nowhere in the tree. Needs either a UI affordance on `lenses.tsx`, or speaker attribution on the ear path. | Small (a text field) for option (a). Option (b) is not small. | — for (a). **Biometric** for (b): distinguishing the wearer's promise from a bystander's means voiceprinting everyone in earshot, which `orchestrator/voice_guard.py:1-24` forbids by design. |
| **ProactiveMemoryCard** | A Brain-side arrival event: a place signature, a source to compute it from, and place-keyed memory rows to join against. All three absent — `grep -rn add_memory ai_brain/` returns nothing. | Large. | **New durable store.** Place signatures are a record of where the wearer has been; rule 2 requires `retention_live.py` to sweep it and `Brain.purge_memories` (`server.py:1643-1735`) to reach it *before* the first push. Note `renderer.lua:701-706` hardcodes the eyebrow "LAST TIME HERE" — the location claim is baked into the glass and no producer can soften it. |
| **PrivateZoneCard** | Everything upstream: no way to mark a place private (no `BrainConfig` field, no `apply_config` allowlist key, no route, no panel control), no location input, no place-identity primitive. | Feature, not a wire-up. | **New durable store** + a posture decision (does a zone flip the same `incognito_now()` posture, or a third one?). **Do not** drive it off a proxy the Brain already has — a card asserting "CAPTURE SUSPENDED" while `ear.ingest_caption` keeps running is strictly worse than an unreachable builder. |
| **ConsentRequiredCard** | (a) A caller — nothing in the product posts to `/dreamlayer/face/identify` or `/face/enrol`. (b) The **return leg** — the card is an affordance ("Hold to allow • Tap to deny", `dismiss_ms: 0`) and `push_event`'s envelope is one-way. | Medium-large. | **Biometric.** `docs/gitbook/privacy.md:75-78` is emphatic that this is the wearer's consent, not the subject's, and the card's own copy does nothing to distinguish them. The proposed alternative trigger (a `face_recognition` config edge at `server.py:4539-4553`) **does not exist** — `before` is a 4-tuple of model/cloud_enabled/network_mode/email_enabled. |
| **ForgetLastCard** | The forget operation itself. No spoken rule in `spoken_intent._RULES`, no route, and no scoped-undo primitive reaching all three sinks `ingest_caption` writes (`ear.py:143`, `:166`, `:172`) **plus the ANN vector**. | Large, and safety-critical. | **The trap to name explicitly:** `EarHost.last_heard` (`ear.py:122`) is the only "last capture" handle the Brain has, so the naive wiring uses it as the card's label — pushing captured speech over SSE, reversing the decision recorded at `ear.py:307-310`. And the only forget the Brain can perform today is `purge_memories()`, which erases *everything*. A card reading `Forget "…"?` in front of that is a total mismatch between promise and effect. |
| **ListeningCard** | A wake/activation event. `EarHost.hear` (`ear.py:89-93`) is a documented no-op. Also missing the `wake_feedback["visual"]` opt-in the Orchestrator gates on (`ops_juno_attention.py:75`). | Medium. | The renderer is *not* the blocker — `draw_listening` reads every field the builder supplies. `dismiss_ms: 0` with no completion signal means it never goes away. |
| **SpokenCaptionCard** | A **display** consent flag. `listen_enabled` is consent to transcribe on-device, not to display; reusing it silently widens an existing opt-in. Also no `focus_active()` equivalent. | Medium (new `BrainConfig` field + allowlist entry + panel switch). | No new store needed. But note: `draw_spoken_caption` never reads `card.speaker`, and nothing populates it — every caption would render the fallback eyebrow "HEARD" over a bystander's words. And `live.py:2582-2587` already draws cloud-processed captions on that same canvas; the two streams would be indistinguishable. |
| **FactCheckCard** | Four inputs, not one: no `factcheck_enabled` in `BrainConfig`, no allowlist entry, no phone→Brain wire (`switchPatch` sends only `cloud_enabled` and `network_mode`), and no speaker. | Three code changes across two codebases before a single push is legal. | **Do not wire.** Two independent reasons: (1) `veritas.py:231` hardcodes `speaker or "them"`, so an unattributed line gets an invented third-party attribution — and the room ear hears the *wearer* most, so the commonest case is the card telling the wearer a stranger said their own sentence. (2) The cooldown paces the **card**, not the network: `verify_claim` → `brain.ask` fires *before* `world_result` applies `cooling()`, so every checkable line costs an ask, a `brain_history.jsonl` row and possible cloud egress. Measured: 9 of 18 ordinary conversational lines pass `checkable()`. |
| **AnswerAheadCard** | Speaker attribution. This is not merely absent — the Brain evaluates the trigger's *precondition* to "never": `is_mine()` is `speaker == "" or speaker.lower() == "me"` (`conversation.py:41-42`), and `ear.py:279-280` builds `CapturePipeline` with no speaker resolver, so `speaker` is always `""`. | Requires a device seam or a deliberate wearer action. | **Biometric** for the diarization route. `voice_guard.py:1-24` forbids voiceprinting a stranger. Firing without the guard makes a no-wake-word answerer that responds to any question anyone near the wearer asks — and `answer_ahead.py:6` says so in one line: *"No wake word: the glasses simply heard the question."* |
| **TimeScrubNodeCard** | A wearer trigger (no `rewind`/`scrub` in `orchestrator/voice.py`) and a session cursor with a way to *leave* — `dismiss_ms: 0`, no `animations.lua` entry, `main.lua:90` URGENT. | Medium. | Fix the off-by-one first regardless: `time_scrub.py:36,40` enumerates from 0, `0` is truthy in Lua, so the first node's eyebrow reads **"0 / 11"** on hardware while `hud/renderer.py:1231` coerces it to 1 in the golden image. The golden image and the glass disagree by one node today. |
| **DeviationAlertCard** | A real per-claim confidence signal. Not a threshold to tune — `ingest_utterance` has no confidence parameter, and every Brain-minted task row is exactly 0.70 (`pipelines/ingest.py:157`). | Blocked at the input. | **Measured, not argued:** with the repo's own code, `TellEngine.check` scores 0.12 / 0.12 / 0.18 / 0.24 against a 0.55 threshold for confidences 0.6 / 0.8 / 0.85 / 0.9 — and an actual contradiction ("I'm not paying the deposit") scores **0.029**, *lower* than the identical sentence, because the negator dilutes the Jaccard overlap the score multiplies by. The engine is anti-correlated on real contradictions. A producer that provably never fires is not a producer. |

---

## Part 6 — Public copy, per batch

### Becomes **true** when a batch lands

| Batch | Line | Status after |
|---|---|---|
| C | `docs/gitbook/perception-memory.md:130` — *"('where did I leave my keys?') renders the spatial ObjectRecallCard"* | True of the Brain for the first time. "**spatial**" remains an overstatement on the Live Lens (a jewel, a field and a place — no gradient trace); true on halo. Leave or soften to "renders the ObjectRecallCard"; do not delete. |
| C | `docs/gitbook/assets/demo/catalog/catalog.md:19` — *"Where you left it … ObjectRecallCard"* | True. |
| D | `docs/gitbook/assets/demo/catalog/catalog.md:21` — *"Keep a moment"* | True. |
| E | `docs/gitbook/assets/demo/catalog/catalog.md:9` — *"Ask it anything … JunoReplyCard"* | True. |
| E | `docs/gitbook/reference/cards.md:17` — *"JunoReplyCard \| Juno answer/action"* | True of both runtimes. |

### Small edits that make already-listed rows exactly right

- **`docs/gitbook/hud-cards.md:95-96`** (SavedMemoryCard "Appears: … a scene ingested, a conversation captured, a nod-to-save"). The leading clause — *"the instant a moment is kept"* — already covers a pin, so this is not false. But the enumeration is now incomplete. Append `, a held thought pinned`. **Do not widen the leading clause**; the Brain produces this on the pin arm only.
- **`docs/gitbook/reference/cards.md:13`** (`SavedMemoryCard | scene/conversation kept, nod-to-save`). Same fix in the Emitted-by cell: add `, held thought pinned`.
- **`docs/gitbook/reference/cards.md`, the `Renderer` column, rows 13/17/18.** All three read `device`. After these batches the Brain draws them on the **Live Lens**, a second renderer. Either add a footnote under the table or leave it — but know that "device" is now incomplete for exactly these three rows, and say so in the commit.
- **`docs/gitbook/reference/endpoints.md:66`** (`/dreamlayer/voice`). The response body gains `pushed` on the ask/recall and locate branches. Mirror the wording already used at `endpoints.md:77`: *"the response then carries `pushed`, the delivery count."*

### Stays **false**, and this plan does not fix it

- **`landing/index.html:1510`** — *"Keys, wallet, car, water bottle — anchored where you left them, recalled as **direction and distance: '12 m to your left'**."* Brain-side this is unreachable by construction: `waypath_stash` calls `remember_place`, which sets `place` only (`waypath.py:83-87`), so `has_bearing()` is always False and the cue is always `"at <place>"`. Bearing/distance needs the IMU seam. **Batch C makes the card real and leaves this sentence false.** Either amend it to "recalled as the spot in your own words" or accept it as a device-only claim — but do not let Batch C's green checker imply it now holds.

### Already false, independent of any batch — fix now

These four are false today and stay false whatever you wire. They were verified line by line and are listed because rule 4 does not wait for the feature.

- `docs/gitbook/privacy.md:92-93` — *"Private zones — places you mark never-record; entering one shows the PrivateZoneCard"*. No code marks, detects, or honours a zone.
- `docs/gitbook/guide/privacy.md:72-73` — *"Mark a place as never-record; the glasses honor it automatically whenever you are there"*.
- `docs/gitbook/guide/cards.md:70` — *"You marked this place private; nothing records here"*.
- `docs/gitbook/reference/cards.md:39` — Emitted-by *"entering a private zone"*.

Plus the `ForgetLastCard` set, all five sites (`docs/gitbook/privacy.md:94-95`, `privacy.md:86-89`, `guide/privacy.md:70-71`, `guide/faq.md:49-51`, `reference/cards.md:38`) — "'forget that' erases the last capture" is not implemented in either runtime; and `docs/gitbook/guide/truth.md:52`, which claims the Truth Lens *"refuses to judge anyone it has not spent real time with"* while `fusion.py:85-88` routes an uncalibrated subject to `_stranger_fuse` and `truth_lens/renderer.py:44` **inverts** the confidence floor for strangers — so a low-confidence stranger read is the one case *not* suppressed. Fix the code or amend the doc; do not leave both.

---

## Part 7 — Acceptance, in order

```
# after Batch A (live.py)      — inert; no checker change
# after Batch B (_brain_host)  — inert
cd host-python && python -m mypy src/dreamlayer                 # clean, all batches
python3 scripts/hud_reachability.py                             # C→17, D→16, E→15
python -m pytest src/dreamlayer/tests/test_live_events.py \
                 src/dreamlayer/tests/test_waypath_voice.py \
                 src/dreamlayer/tests/test_stasis_ops.py \
                 src/dreamlayer/tests/test_logging_discipline.py \
                 src/dreamlayer/tests/test_reachability_checkers.py
```

One test-file edit is required, and the test itself asks for it: `tests/test_reachability_checkers.py:162-176`, docstring *"18 of 24 declared cards have no Brain-side producer"* → **15 of 24**. Its two assertions survive unchanged (the gap stays non-empty and still contains "Truth, checked live"), and the docstring says exactly what to do: *"read the number, fix the assertion, and keep it pointing at what is still open."*

---

## What I would not do

- **Do not wire `DeviationAlertCard`**, even though the trigger genuinely exists at `lens_hosts.py:293`. The engine scores 0.12–0.24 against a 0.55 threshold on Brain-minted data and scores real contradictions *lower* than identical sentences. Shipping it produces a call site that satisfies the checker and can never fire — the card-layer twin of counting `brain.lenses()` reachable because of a call site inside erase-everything. That is the failure this audit exists to catch, and adding it would blind the checker to the next one.
- **Do not wire `FactCheckCard` or `AnswerAheadCard` by relaxing the speaker guard.** Both cards' entire proposition is *someone else said this*. The Brain's `speaker` is structurally `""`, so relaxing the guard does not make them work — it makes them attribute the wearer's own words to a stranger.
- **Do not add `renderEvent` branches for `SavedMemoryCard` or `JunoReplyCard`.** They are eyebrow+primary cards and `glassEventCard` is already the correct renderer. The branch in Batch A exists because `ObjectRecallCard`'s answer lives in a field the generic renderer drops — that is the only justification, and it should not be generalised.