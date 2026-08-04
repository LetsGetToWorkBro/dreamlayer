# decisions/

Findings that were **investigated and closed without a code change**, and the
reasoning that closed them.

Audits keep re-deriving the same conclusions. A finding gets raised, someone
spends an hour proving it unreachable, the session ends, and the next audit
raises it again — at full cost, with no memory that the question was already
settled. This directory is where that hour goes so it is only spent once.

## What belongs here

One file per **decision**, not per bug:

* **`refuted`** — the claim was wrong, or real at a primitive but unreachable
  through any shipping caller.
* **`accepted-risk`** — the claim is true, and we are deliberately living with
  it. The rationale, and what would change our minds.
* **`confirmed-deferred`** — the claim is true and unfixed. Why it is not fixed
  yet, and what fixing it would take.
* **`needs-recheck`** — we acted on this conclusion but have not re-verified it
  against current code. An honest debt marker, not a resting state.
* **`fixed`** — an entry that WAS one of the above and has since been fixed.
  Reserved for entries that cannot simply be deleted: ones the public docs link
  to, or whose reasoning is the record (0001's prescribed fix was itself wrong,
  and the correction is the valuable part). A `fixed` entry names the commit's
  regression test and re-points `What would overturn this` at the *fix*.

A finding that was fixed does not otherwise belong here. Its record is the
commit and the regression test. This directory is mainly for the ones that
leave no other trace.

## What must NEVER go here

**Descriptions of how the code currently works.** No architecture notes, no
module summaries, no "how X works" pages.

That rule is not stylistic. On 2026-07-27 the `person_guard` docstring claimed
it caught "a lone given name like `Maya`". Against the real analyzer, bare
`"Maya"` scored nothing — the claim had been false since it was written, kept
alive by tests that injected a fake. Any process that compiles source prose into
a knowledge page would have faithfully reproduced that falsehood, added a
citation, and made it *more* trusted than the docstring it came from.

Code answers "how does this work" by being read and run. A summary of code is a
second copy that drifts silently and cannot be executed. Decisions are different:
they are about a moment, they are inert, and re-deriving them is expensive. That
asymmetry is the whole reason this directory exists and the boundary it must not
cross.

## The rule that keeps entries honest

Every entry carries a **`What would overturn this`** section: the specific,
runnable check that flips the verdict.

An entry without one is an assertion, and assertions rot. An entry with one is a
claim someone can refute in a minute — including the person who wrote it. When
that check starts coming back the other way, change the status. Do not delete
the entry; supersede it, so the reversal is legible too.

Evidence must be **reproducible commands with their output**, not prose. "I
checked and it's unreachable" is worth nothing in six months. `grep -rn
"RetentionSweep(" src/dreamlayer | grep -v /tests/` → one hit, inside a function
with no production caller, is worth something.

## Format

Copy `TEMPLATE.md`. Number files sequentially: `NNNN-short-slug.md`.

Front-matter fields (`id`, `title`, `status`, `date`, `area`) are validated by
`host-python/src/dreamlayer/tests/test_decisions_log.py`, which also checks that
every entry has the required sections. That test is the only thing standing
between this directory and a pile of free text.

## Index

| id | status | title |
|----|--------|-------|
| [0001](0001-retention-lifecycle-never-runs.md) | fixed | Nothing on the device ever expires — the retention lifecycle has no live caller |
| [0002](0002-object-lens-none-path-unreachable.md) | refuted | `default_classifier()` cannot return `None` in production |
| [0003](0003-person-guard-mug-false-positive.md) | accepted-risk | Presidio tags `"mug"` as a PERSON, and we ship it |
| [0004](0004-presidio-real-tests-did-not-exist.md) | refuted | Issue #528's Presidio tests were not being skipped — they did not exist |
| [0005](0005-vector-store-ranking-unreachable.md) | refuted | `VectorStore` ranking is unreachable — but not for the reason first given |
| [0006](0006-causal-fusion-was-a-fixed-heuristic.md) | accepted-risk | `causal_fusion` inferred nothing causally and returned None either way — dropped |
| [0007](0007-the-twenty-one-dormant-capabilities.md) | confirmed-deferred | Each of the 21 dormant capabilities, and what is actually blocking it |
| [0008](0008-mlx-train-is-unbuilt-not-unhosted.md) | confirmed-deferred | mlx_train's trainer was never written, so it needed building rather than wiring |
| [0009](0009-veil-recall-semantics.md) | confirmed-deferred | The Veil's recall semantics genuinely differ across lenses, and the split is now declared rather than accidental |
