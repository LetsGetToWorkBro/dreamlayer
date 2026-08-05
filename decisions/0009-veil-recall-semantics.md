---
id: 0009
title: The Veil's recall semantics genuinely differ across lenses, and the split is now declared rather than accidental
status: confirmed-deferred
date: 2026-08-04
area: ai_brain/server/veil.py
---

## Claim

`scripts/lens_reachability.py` flagged **Privacy Veil — `dreamlayer.memory.privacy` [no Brain-side constructor]**, its only annotation.

The literal claim is true and the implied one is false. `PrivacyGate` really is constructed only by `orchestrator.py:230`, which `decisions/0001` records the shipped Brain never builds. But the Veil *is* enforced Brain-side — by **twelve** separately hand-written gate classes, none of which the checker's name-to-name pairing could see.

The strong form, and the reason this is not merely tidiness: **`allow_recall` did not agree across those twelve**, and both diverging sites had argued their case in a docstring without knowing the other existed.

## Verdict

Confirmed — two defensible, contradictory readings of "may I read back what I already know while veiled?" were live simultaneously; the duplication is now removed and the disagreement preserved verbatim and made explicit, because choosing between them is a product decision about what the Veil covers, not a refactor.

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

**Done.** `ai_brain/server/veil.py` holds the single `VeilGate`. `recall` is keyword-only with **no default** — the divergence came from two careful people answering locally a question nobody had written down globally, and a default would re-create that at gate thirteen. All twelve sites migrated with behaviour preserved exactly; `test_veil_gate.py` asserts no `ai_brain/server/` module defines `allow_capture`/`allow_recall` again, that every construction names its posture as a literal, and that `lucid_live.py` is still the only site taking the surviving posture.

**Deferred, and it is the owner's call.** Which reading is right. Both are defensible:

- *Recall follows capture* — a timeline of what was said in front of the wearer is what the shield exists to stop, and "veiled" reading as one thing is easier to trust.
- *Recall survives incognito* — the reference says so in as many words, and quiet hours is a nightly window, so the strict reading means the Brain refuses to answer "what did we decide about the lease?" every night.

Nothing here picks. Changing the split now means editing one literal and one test, and the test failure names this file.

**Watch: `plugins/base.py:110-112`** is a third semantics and the only fail-**open** one —

```
        if v is None or not hasattr(v, "allow_recall"):
            return True
```

A supplied gate lacking the method is treated as permissive. Two of the twelve (`_FaceGate`, `_VoiceGate`) lacked it. **Not reachable today** — `world_lens.plugin_context` passes `self.privacy`, which had it, and after this change every gate has it — so this is a latent hazard, not a live defect. The `v is None` arm is deliberate and correct (the SDK/preview/unit case with no veil wired). The `hasattr` arm is the one worth inverting: if somebody hands you a gate, honour it or refuse it, but do not read a missing method as consent.

**The checker's annotation stays.** `lens_reachability.py` was not wrong to flag this, and its `_brain_side_constructions` docstring already says it is "a signal for a human, not a gate". It found a real thing by a heuristic that could not describe what it found — which is worth leaving in place rather than tuning until it goes quiet.
