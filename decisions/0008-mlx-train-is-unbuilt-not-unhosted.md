---
id: 0008
title: mlx_train is the one capability that cannot be re-hosted, because its trainer was never written
status: confirmed-deferred
date: 2026-08-03
area: rem/nightly_mlx.py
---

## Claim

`mlx_train` was the last entry in the reachability report's NOT YET HOSTED
BRAIN-SIDE bucket, whose blurb reads *"Each is a complete seam whose only
consumer is the Orchestrator the shipped Brain never builds."* Nine capabilities
left that bucket during 2026-08-02/03 by being re-hosted Brain-side, and the
claim under this one was that it would go the same way: point a scheduler at
`MlxNightlyTrainer.train_nightly` and the local model starts adapting overnight,
as the capability's own gain text promises — *"baseline model never adapts; this
fine-tunes it overnight on your own memories"*, impact 4.

## Verdict

It is not the same shape as the other nine: the seam is incomplete, not
unhosted, so wiring a scheduler to it would produce a nightly job that reliably
reports "training not implemented" — a scheduled no-op dressed as a capability.

## Evidence

The training branch does not train. `train_nightly` imports `mlx_lm.lora` as an
availability probe and then returns without calling it:

```
$ sed -n '70,79p' host-python/src/dreamlayer/rem/nightly_mlx.py
        try:
            # The LoRA training step is not implemented yet: nothing below
            # invokes a trainer or writes an adapter, so report the work as
            # not done rather than claim a success that never ran. The import
            # probe stays as the mlx-lm availability gate.
            from mlx_lm import lora as _lora  # type: ignore  # noqa: F401
            return TrainSummary(trained=False,
                                reason="training not implemented",
                                examples=len(examples))
```

That comment is the module being honest about itself, and it predates this
audit. `trained` is False on every branch of the function; no branch writes an
adapter, and `adapter_path` is never set.

Nothing outside its own tests calls it:

```
$ grep -rn "train_nightly" host-python/src/dreamlayer --include=*.py | grep -v nightly_mlx.py
host-python/src/dreamlayer/tests/test_integration_seams_pr5.py:130:    s = t.train_nightly(_Ring(), privacy=_Veil(True))
host-python/src/dreamlayer/tests/test_integration_seams_pr5.py:155:    s = MlxNightlyTrainer().train_nightly(_Ring(), privacy=_Veil(True))
```

And the existing test asserts the unimplemented state deliberately — the suite
already pins "must not claim a success that never ran".

The scheduling half of the claim is separately true and is NOT the blocker: the
Brain runs several daemon schedulers (`start_retention_scheduler`,
`start_brief_scheduler`, `start_source_sync`, and `start_home_hud` as of today),
so a nightly hook is a five-line job whenever there is something to hook.

## What would overturn this

`MlxNightlyTrainer.train_nightly` returning `trained=True` with a real
`adapter_path` on an Apple-silicon Mac with `mlx`/`mlx-lm` installed:

```
$ python -c "from dreamlayer.rem.nightly_mlx import MlxNightlyTrainer as T; \
             print(T().train_nightly(ring))"
```

Anything other than `trained=False` means the trainer exists and this record is
stale — wire the scheduler at that point.

## Consequences

**Do not wire a scheduler to it now.** A nightly job whose only possible outcome
is `reason="training not implemented"` would move the capability out of the
report's honest bucket without changing anything a wearer experiences, which is
the exact reclassification-instead-of-work that splitting `_BY_DESIGN` was meant
to make impossible (see `scripts/capability_reachability.py`).

**Do not write the LoRA loop blind.** mlx and mlx-lm are macOS/Apple-silicon
only and cannot be imported, let alone run, in this repo's CI or on the machine
this audit was performed from. Writing a training loop that has never executed
once, that reads the wearer's own memories, and reporting it as a shipped
capability, is the overclaim the whole capability-honesty effort exists to
remove. It needs a Mac, a real model, and a human watching the first run.

**What a future fix has to touch**, in order:

1. `train_nightly`'s try-block — the actual `mlx_lm.lora` invocation and an
   adapter written to `adapter_dir`.
2. `_collect` — it currently returns a flat list of raw `summary` strings.
   A LoRA fine-tune wants formatted pairs, and the privacy question is sharper
   here than anywhere else in the tree: everything else this audit wired is
   transient (a card, a frame, a poll), whereas a fine-tuned adapter is the
   wearer's memories baked into weights that outlive any retention sweep. The
   Veil check in `_collect` gates the read; it says nothing about what deletion
   means afterwards.
3. Only then a scheduler, and a proof-based `DL_WIRED_MLX_TRAIN` that follows an
   adapter genuinely written — never `_HAS_MLX`.

The report keeps `mlx_train` visible with its own accurate reason rather than
being moved to `_BY_DESIGN`. Filing it as a design decision would be false: the
wearer really does lose something, and somebody really should build it.
