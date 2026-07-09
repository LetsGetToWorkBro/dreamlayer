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
cd host-python && python -m pytest -q -m "not hardware and not benchmark"
```

That command must be green with zero optional dependencies installed — it's
the invariant the whole optional-capability system rests on. Device-needing
tests are marked `hardware`; latency budgets are marked `benchmark`.

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
