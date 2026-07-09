# Open source

DreamLayer is licensed **Apache-2.0**, whole repo — the firmware, the
orchestrator, the Brain, the phone app, the plugin system, all of it. The
reasoning is recorded in `docs/OPEN_SOURCE.md`: Apache over MIT for the
patent grant (this is AR), Apache over AGPL because the moat is velocity
and ecosystem, and whole-repo over open-core because the lenses *are* the
engine.

## The kit

- **LICENSE** — the canonical Apache-2.0 text.
- **NOTICE** — the one reservation: the *DreamLayer* name, the ring mark,
  and dreamlayer.app are trademarks (Apache section 6) — forks take the
  code, not the identity.
- **CONTRIBUTING.md** — DCO rather than CLA (`git commit -s`,
  inbound = outbound Apache); the one-license rule (no GPL/AGPL
  dependencies in core — which is also why every integration is an
  *optional* adapter); the add-alongside seam convention; and the one
  command that must stay green:
  `pytest -q -m "not hardware and not benchmark"`.
- **SECURITY.md** — private disclosure to security@dreamlayer.app, 72-hour
  acknowledgment, 90-day coordinated window; the plugin capability gate and
  the Veil contract are explicitly in scope.
- **CODE_OF_CONDUCT.md** — Contributor Covenant 2.1, plus one
  project-specific clause: the privacy contract is a values commitment, and
  trying to sneak a weakening of it past review is a conduct issue, not
  just a technical one.
- Issue templates (bug, lens idea, plugin submission), a PR template with
  DCO and privacy-contract checkboxes, and a funding hook.

## The first ten minutes: hello-lens

`examples/hello-lens/` is the builder onramp: the smallest real plugin —
one file, one card renderer, a store-valid manifest with a real checksum —
plus a ten-minute README covering the capability model, local testing,
packaging, and shipping to the registry. The tutorial **cannot rot**: a CI
test runs the exact committed folder through the real store machinery
(manifest shape, checksum integrity, the full validation gate, a registry
load with the capability granted, and the clean named skip without it).

Three doors, in order of ambition: run hello-lens, drive the
[simulator](simulator.md) and the test suite, then extend the engine
itself — every seam in [Integrations](integrations.md) is a place a
contribution slots in without touching the core.

## Status, honestly

The repository is license-complete and public-*intent*: every file, policy,
and piece of site copy is written to be true the moment the visibility
flips, and `docs/OPEN_SOURCE.md` carries the remaining go-public checklist
(the flip itself, the DCO app, sponsors, standing good-first-issues). Until
that switch, "open source" describes the licensing and the architecture —
both already real — rather than a public repo you can clone today.
