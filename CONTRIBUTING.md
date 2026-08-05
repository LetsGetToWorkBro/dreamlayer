# Contributing to DreamLayer

Thanks for wanting to build on the layer. This is the short version — the
design philosophy lives in [`docs/PLATFORM.md`](docs/PLATFORM.md) and the
integration conventions in [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

## The ground rules

1. **Everything is Apache-2.0, inbound = outbound.** By submitting a
   contribution you license it under the repository's
   [Apache License 2.0](LICENSE), the same terms you received it under.
   No CLA — we use the **Developer Certificate of Origin** instead: sign
   your commits with `git commit -s`, which adds the `Signed-off-by:` line
   certifying you have the right to submit the work
   (see [developercertificate.org](https://developercertificate.org)).

2. **One license in core.** Don't add dependencies under GPL/AGPL or other
   copyleft licenses to the Python package or apps — permissive
   (MIT/BSD/Apache/ISC) only. Optional integrations follow the same rule.

3. **Add alongside, don't break.** New capabilities land as optional seams:
   lazy `try/except ImportError` with a working fallback, dependency declared
   in an extras group (never core `[project].dependencies`), and tests that
   pass with the dependency absent. The core must always run with nothing
   installed. `memory/embeddings.py` is the canonical example; 58 adapters
   in the tree follow it.

4. **Privacy is structural.** No memory write without a capture guard, the
   Veil must silence everything, and nothing identifies strangers. PRs that
   weaken these are declined regardless of technical quality.

## Running the suite

```bash
pip install -e "host-python[dev]"
cd host-python && python -m pytest -q -m "not hardware and not benchmark and not real_model"
```

That command must be green with zero optional dependencies installed — it's
the invariant the whole optional-capability system rests on. Device-needing
tests are marked `hardware`; latency budgets are marked `benchmark`;
heavy-model tests are marked `real_model`.

### Verification traps this codebase has actually hit

[`CLAUDE.md`](CLAUDE.md) collects the specific ways work here has gone wrong —
mostly checks that passed because they examined nothing, and seams that were
importable but unreachable. Worth five minutes before a first PR, and worth
re-reading before trusting a green run on something subtle.

## Good first contributions

- A new **lens or plugin** — start from the ten-minute tutorial in
  [`examples/hello-lens/`](examples/hello-lens/) (a complete, store-valid
  plugin CI keeps honest), then see `plugins/package.py` and the validation
  gate in `plugins/validate.py`.
- A real-path adapter test for an optional integration you actually have
  installed.
- Docs: anything in `docs/` that confused you is a bug.

## Process

We follow the [Code of Conduct](CODE_OF_CONDUCT.md). Open an issue before large changes (architecture, new subsystems) so design
is agreed before code. Small fixes: just send the PR. Maintainers make final
product calls — see [`docs/OPEN_SOURCE.md`](docs/OPEN_SOURCE.md) for
governance.

### Check `decisions/` before re-raising a finding

[`decisions/`](decisions/) records findings that were investigated and closed
**without** a code change — refuted, accepted as a known risk, or confirmed and
deferred. Audits keep re-deriving the same conclusions at full cost, and a
finding that leaves no commit behind leaves no trace at all. If you are about to
report something in the security, privacy, or dead-code family, skim the index
first; you may find the hour has already been spent, with the evidence.

Every entry names the check that would overturn it, so a stale conclusion can be
refuted rather than believed. If you run that check and it comes back the other
way, say so — that is the most useful thing the directory can produce. Closing a
finding without a code change means adding an entry; `TEMPLATE.md` has the shape,
and a test enforces it.

The directory holds **decisions only** — never descriptions of how code works.
Code answers that by being read and run; a prose copy drifts silently and cannot
be executed. `decisions/README.md` explains why that line is drawn where it is.

### Security remediations get an adversarial re-audit

Any change that fixes a security/privacy finding — veil/capture gates, auth,
plugin isolation, cloud egress, or a concurrency/data-integrity fix — must be
**re-audited adversarially before it is trusted as closed**, especially when
the fix was written and reviewed in one sitting (a self-review shares its own
blind spots). Passing tests and a confident writeup are not proof the finding
is closed. The pass runs independent reviewers each tasked to *refute* a slice
of the fix (find where it is vacuous, incomplete at a sibling call-site,
bypassable via another path, or fails open), verifies every claim in the real
code, and fixes what survives — each with a test that fails on revert. This
has repeatedly caught live leaks a green suite declared fixed. The method is
captured as the `refute-remediation` skill (`.claude/skills/`).
