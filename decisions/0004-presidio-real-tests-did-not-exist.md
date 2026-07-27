---
id: 0004
title: Issue #528's Presidio tests were not being skipped — they did not exist
status: refuted
date: 2026-07-27
area: ci/real-models
---

## Claim

Issue #528, from an outside contributor: the `real-models` workflow installs
neither the `privacy` extra nor a spaCy model, so "every Presidio real-path test
`importorskip`s there". The report named the affected file and offered a patch
adding `.[privacy]` and `python -m spacy download en_core_web_sm`.

## Verdict

Refuted **as reported**: the named file did not exist and no `real_model`-marked
Presidio test existed anywhere, so nothing was being skipped and the proposed
patch would have changed nothing. The underlying concern was nevertheless real
in a stronger form, and was fixed in PR #531.

## Evidence

At the time of the report, on `main`:

```
$ ls src/dreamlayer/tests/ | grep -i presidio
(no output)

$ grep -rln "real_model" src/dreamlayer
tests/conftest.py  tests/test_voice_pipeline_real.py  tests/test_vision_bench.py
tests/test_embedder_local_real.py  tests/test_retrieval_quality.py
tests/test_embedder_static.py  pyproject.toml
```

`pytest -m "real_model"` selects by mark. With no marked Presidio test, adding
the dependency changes the selected set not at all.

What *was* true: exactly half the marked tests — 5 of 10 — were vanishing,
because `model2vec` (2 tests) and `silero-vad` / `faster-whisper` (3 tests) were
absent from the same install step. And the Presidio path had no coverage in any
job, because it had no tests at all.

## What would overturn this

Nothing — this entry describes a specific historical state, and PR #531 changed
it. `test_pii_presidio_real.py` now exists, so the filename the issue cited is
accurate going forward. The entry is kept because the *reasoning* is what is
reusable, not the state.

## Consequences

The generalisable lesson, which is why this is written down rather than just
closed:

- **A confident, well-formatted bug report is a compiled artifact and can be
  wrong.** This one carried a file path and line numbers. Trusting it over the
  tree would have shipped a no-op and closed the issue as fixed.
- **Verify the cited location exists before designing a fix around it.** One
  `ls` was the whole cost.
- **A report can be wrong in its particulars and right in its thesis.** The
  correct response was neither to apply the patch nor to close the issue, but to
  find the true instance of the mechanism the reporter had identified. Closing
  it as "cannot reproduce" would have left 5 of 10 tests silently skipping.
- The durable fix was not the install list — it was making the job **fail on any
  skip**, so the next missing backend cannot hide. Prefer the guard that detects
  the class of problem over the patch that fixes today's instance.
