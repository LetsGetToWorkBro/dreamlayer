---
id: 0009
title: Recall is unrestricted; capture fails closed — and two writes filed under recall had to move
status: fixed
date: 2026-08-05
area: ai_brain/server/veil.py
---

## Claim

`scripts/lens_reachability.py` flagged **Privacy Veil — `dreamlayer.memory.privacy` [no Brain-side constructor]**, its only annotation.

The literal claim is true and the implied one is false. `PrivacyGate` really is constructed only by `orchestrator.py:230`, which `decisions/0001` records the shipped Brain never builds. But the Veil *is* enforced Brain-side — by **twelve** separately hand-written gate classes, none of which the checker's name-to-name pairing could see.

The strong form, and the reason this is not merely tidiness: **`allow_recall` did not agree across those twelve**, and both diverging sites had argued their case in a docstring without knowing the other existed.

## Verdict

**Settled by the owner on 2026-08-05: recall is unrestricted.** The dissenting lens was right — incognito is about not KEEPING, so nothing blocks a read. Getting there safely required moving two writes that had been filed under recall. What follows is the original finding, kept because the reasoning is what makes the fix safe.

Originally: two defensible, contradictory readings of "may I read back what I already know while veiled?" were live simultaneously; the duplication is now removed and the disagreement preserved verbatim and made explicit, because choosing between them is a product decision about what the Veil covers, not a refactor.

## Evidence

Twelve classes, and `allow_capture` identical in all of them — which is why the duplication read as harmless:

```
$ python3 - <<'EOF'   # AST-hash each gate's method bodies
...
file                class            allow_capture  allow_recall
dream_reactors.py   _Gate            ff516899       c6a46147
ear.py              _EarGate         ff516899       c6a46147
face_live.py        _FaceGate        ff516899       MISSING
intro_live.py       _IntroGate       ff516899       c6a46147
lens_hosts.py       _LensGate        ff516899       c6a46147
live_circle.py      _PostureGate     ff516899       c6a46147
live_confluence.py  _PostureGate     ff516899       c6a46147
lucid_live.py       _Gate            ff516899       9d466364
train_live.py       _TrainGate       ff516899       c6a46147
truth_live.py       _TruthGate       ff516899       c6a46147
voice_live.py       _VoiceGate       ff516899       MISSING
world_lens.py       _LookGate        ff516899       c6a46147

12 gate classes | distinct allow_capture bodies: 1 | distinct allow_recall bodies: 2
```

The reference semantics, `memory/privacy.py:29-39`:

```
    def allow_capture(self) -> bool:
        """... Blocked by either veil — an explicit pause or incognito."""
        return not (self._paused or self._incognito)

    def allow_recall(self) -> bool:
        """... Blocked only by the full pause veil ("deaf and blind").
        Incognito stops keeping new memories, not recalling old ones — you can
        still ask what you already know while incognito."""
        return not self._paused
```

Both divergent sites reasoned deliberately, and neither cites the other.

`lens_hosts.py:461-465` — recall tied to capture, 17 call sites:

> The Orchestrator's precedent gates on `allow_capture` (`ops_world_lenses.py:37`); `_LensGate` makes `allow_recall` the same predicate, so this gates on recall and the two agree.

`lucid_live.py:172-176` — recall kept open, reached via `lucid_recall/router.py:62`:

> `allow_recall` is deliberately NOT `allow_capture`: incognito stops keeping new memories and does not stop you asking what you already know. Collapsing them would make the lens go silent in exactly the session where a wearer is most likely to want a quiet, private lookup.

Several of the twelve claimed to mirror each other. `lens_hosts.py:89`:

> The Veil, fail-closed — identical posture to `ear._EarGate`, `world_lens._LookGate` and `face_live._FaceGate`.

True of `allow_capture`, false of the pair, and nothing in the suite could tell.

**What a wearer experiences today.** While incognito, in quiet hours, or in a private zone: Lucid Recall still answers; `trace()`, `check()` and the other 15 `lens_hosts` reads return `None` — "I am not allowed to say".

## What would overturn this

That the disagreement is inert — that nothing Brain-reachable calls `allow_recall`, making this dead code rather than a live split. It is not:

```
$ grep -rn "\.allow_recall()" src/dreamlayer/ai_brain --include=*.py | wc -l
17
$ grep -rn "allow_recall" src/dreamlayer/lucid_recall/router.py
62:        if not self._privacy.allow_recall():
```

Both paths run. If a future change removes one side, re-check before treating the remaining posture as the Brain's answer.

## Consequences

**The decision.** Recall is unrestricted for every lens. `VeilGate.allow_recall()` returns `True`, and the posture parameter is gone — it existed only to hold the disagreement, so keeping a two-valued knob with one value in use would be dead scaffolding. `allow_capture` is unchanged and still fails closed.

**What made it unsafe, and what had to move with it.** Opening recall is only safe while recall means *reading*. Two `lens_hosts` methods were gated on `allow_recall` and did no reading at all:

```
resume()          stasis.replace_frame(fresh); save_stasis()
quest_complete()  saga.complete() pays XP; _saga_profile_record() writes badges
```

They were filed under recall because that is what `_LensGate` happened to offer. While recall was closed the miscategorisation was invisible — nothing could fire either way. Open recall and both persist a record of what the wearer did *during* a veiled stretch, which is exactly what the capture gate exists to stop. Both ask `allow_capture` now, because they were never recall questions.

The other fifteen recall-gated methods were checked and are reads. Two heuristic hits were false positives worth naming so nobody re-raises them: `all_records` is a read, and `their_word`'s `append` is to a local list.

**The guard.** `test_veil_gate.py::TestNothingWritesWhileVeiled` drives the real methods against a veiled Brain and spies on the persistence call. Behavioural on purpose: a source scan for write-shaped names produces both false positives and false negatives, and neither tells you whether anything was actually written. Without it, the next action accidentally filed under recall becomes a silent write-while-veiled.

**Watch: `plugins/base.py:110-112`** is a third semantics and the only fail-**open** one —

```
        if v is None or not hasattr(v, "allow_recall"):
            return True
```

A supplied gate lacking the method reads as permissive. Now moot in practice — every gate is `VeilGate` and has it — so this stays a latent hazard rather than a live defect. The `v is None` arm is deliberate and correct (the SDK/preview/unit case with no veil wired). The `hasattr` arm is the one worth inverting: if somebody hands you a gate, honour it or refuse it, but do not read a missing method as consent.

**The checker's annotation stays.** `lens_reachability.py` was not wrong to flag this, and its `_brain_side_constructions` docstring already says it is "a signal for a human, not a gate". It found a real thing by a heuristic that could not describe what it found — worth leaving in place rather than tuning until it goes quiet.
