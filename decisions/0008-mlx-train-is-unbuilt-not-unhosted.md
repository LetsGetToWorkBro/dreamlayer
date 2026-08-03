---
id: 0008
title: mlx_train is the one capability that cannot be re-hosted, because its trainer was never written
status: needs-recheck
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

**(Superseded in part on 2026-08-03 — the trainer was written. The diagnosis below
stands and is why it needed BUILDING rather than wiring; see Consequences for
what now exists and what is still unverified.)**

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

**The trainer was built on 2026-08-03**, at the owner's direction and with an
Apple-silicon Mac available to verify on. The verdict above is why it was a
build and not a wiring job, and it is left standing for that reason. Two gaps
had to close, not one — the second was found only while doing the work:

1. `rem/nightly_mlx.py` now trains. It runs `python -m mlx_lm.lora` as a
   SUBPROCESS rather than importing the trainer: it cannot take the Brain down,
   it can be killed mid-run (which is what "one gesture, everything stops"
   requires of a multi-hour job), and mlx-lm's CLI has been far more stable
   across versions than its Python entry points.
2. **`MLXBackend` could not load an adapter at all.** `mlx_lm.load()` was called
   with no `adapter_path`, so even a perfect fine-tune would have written a file
   nothing could read. This was not in the original record because it had not
   been looked for — the capability was two gaps deep, not one.

`config.mlx_model` / `mlx_max_tokens` / `mlx_adapter_dir` are real fields now.
`MLXBackend` had been reading the first two through `getattr(config, …, default)`
against fields that were never declared, so the Apple-silicon answer tier ran on
a hard-coded model with no way to change it from any surface the product ships.

### The privacy work, which was the actual reason to be careful

`_collect` used to be one `allow_capture()` check over raw summaries. The corpus
is now built to a stricter rule than any other read path in the tree:

* **Another person's words are never trained on.** A row carrying `said_by` is
  somebody else speaking. Their sentences are in the wearer's memory because the
  wearer was there; that is not consent to train a model on them, and there is
  no mechanism by which they could withdraw it. Read from the row AND from its
  `meta`, because the ring and the store keep the same field in two shapes.
* **Index rows are not language.** `person`/`place`/`object` rows are catalogue
  entries ("Person: Marcus"); a model trained on them learns to emit lists.
* **A manifest, always.** `adapter.json` beside the weights records which row
  ids produced them — ids only, never the text, or it would be a second copy of
  the corpus sitting outside every retention sweep.

### Deletion: retrain-on-forget, because nothing else is true

Nothing un-trains a LoRA. The guarantee the product now makes, and the only one
it can keep:

    delete a row  ->  every adapter whose manifest lists it is STALE
    stale adapter ->  taken out of use, and rebuilt on the next nightly run

`Brain.forget_memory` enforces it on the ERASE path, not only on the nightly
tick, so a wearer who just deleted something is not answered from weights built
on it until 3am. Retiring RENAMES the weights (`.stale`) rather than deleting
them, so an accidental forget does not also destroy a night of compute, and
`MLXBackend.adapter_path` globs `*.safetensors` so the rename is what unloads
it. An unreadable store is treated as stale: the wearer gets the base model,
which is a worse answer rather than a broken promise.

It is off by default — a second opt-in on top of memory itself, for the same
reason the ear is.

## Still unverified, and this is the part that needs a human

**No line of the training path has ever executed.** mlx and mlx-lm are
Apple-silicon only and absent from CI and from the machine this was written on,
so the subprocess runner is faked in every test. What IS tested for real is
everything that decides what may be baked into weights, plus the deletion story
— the half whose mistakes cannot be undone.

### Runbook for the first real run

On the Mac mini Brain, with `pip install "dreamlayer[platform]"` (mlx, mlx-lm):

```
# 1. switch it on, and point the answer tier at MLX
$ curl -s localhost:7777/dreamlayer/config -X POST \
    -H 'X-DreamLayer-Token: <token>' \
    -d '{"model":"mlx","nightly_train_enabled":true}'

# 2. run it now rather than waiting for 3am
$ python -c "
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.train_live import nightly
b = Brain('~/.dreamlayer')
print(nightly(b).run_once())"
```

What each outcome means:

| output | meaning |
|---|---|
| `{'trained': False, 'reason': 'too few examples (N < 200)'}` | working correctly — the Brain has not heard enough yet |
| `{'trained': False, 'reason': 'mlx-lm exited 2: …'}` | the CLI flags drifted; the exact argv is in the log line above it |
| `{'trained': False, 'reason': 'mlx-lm exited 0 but wrote no adapter'}` | it ran and produced nothing — do not trust a `trained: True` from a patched version until this is understood |
| `{'trained': True, 'adapter': '…/adapter'}` | check `adapter.json` lists row ids and no text, then ask the Brain something and confirm `MLXBackend.adapter_loaded` is True |

The single most likely breakage is the mlx-lm argv. It is logged verbatim
(`[nightly_mlx] <python> -m mlx_lm.lora --model …`) before the run precisely so
the first failure is a two-minute fix rather than a mystery.

**Flip this record to `confirmed` once a real adapter has been written and an
answer has demonstrably come back through it.** Until then it is
`needs-recheck`, and `DL_WIRED_MLX_TRAIN` — which follows an adapter genuinely
written, never `_HAS_MLX` — will stay dark on every machine including the one
that ships it.
