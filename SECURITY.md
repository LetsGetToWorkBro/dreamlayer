# Security Policy

DreamLayer is a privacy product; security reports get priority attention.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Email **security@dreamlayer.app** with a description, reproduction steps,
and impact assessment. You'll get an acknowledgment within 72 hours and a
remediation plan or status update within 14 days. We follow coordinated
disclosure: we ask for up to 90 days before public disclosure, and we credit
reporters (unless you prefer otherwise) in the release notes.

## Scope

- `host-python/` — the Brain server, memory engine, orchestrator, lenses
  (pairing, token auth, capture guards, the Veil contract)
- `phone-app/` — the iOS/Expo hub
- `registry-api/` — the Cloudflare Worker
- `host-python/src/dreamlayer/plugins/` and the git-backed `registry/` — the
  package format and validation gate (a plugin escaping its declared
  capabilities is a vulnerability)
- `landing/`, `web/` — the sites

Especially interesting: anything that lets a memory be written while the
Privacy Veil is down, leaks raw media that should have been structured
meaning, bypasses pairing/token auth on the Brain, or lets a plugin exceed
its capability grant.

## Supply-chain integrity

Getting the code right is only half of it — you also have to trust that the
bits you run are the bits we built, from the dependencies we vetted:

- **Release signing** — the macOS `.dmg` is codesigned + notarized and the
  Windows installer is Authenticode-signed; release artifacts are additionally
  signed (`sign-release.yml`) and an SBOM is published (`sbom.yml`).
- **Build provenance (SLSA)** — every `.dmg`/installer carries a signed
  `actions/attest-build-provenance` statement of *where* it was built (this repo,
  this workflow, this commit). Verify with
  `gh attestation verify <artifact> -R <owner>/<repo>` — signing proves *who*
  signed, provenance proves the build's *origin*.
- **Dependency CVEs** — `pip-audit` (`dep-audit.yml`) scans resolved versions on
  dependency changes; `dependency-review.yml` blocks a PR that *introduces* a
  vulnerable dependency; Dependabot security updates open a fix PR automatically
  when a patched release lands.
- **Triaged advisories (audit 2026-07-19)** — a full OSV sweep of the committed
  lockfiles (`uv.lock`, `package-lock.json`, `Cargo.lock`) found the open
  advisories are all in *optional* extras or *build* tooling — none in the core
  Brain runtime, and none with a clean upstream fix to bump to today:
  - `chromadb` (optional `memory` vector-store extra) — GHSA-f4j7-r4q5-qw2c; no
    fixed release exists yet (the latest version is still affected). The vector
    store is optional and off by default, with built-in `sqlite-vec` / `lancedb`
    alternatives. Monitored for an upstream patch.
  - `Pillow` — the DoS advisories are fixed in 12.x, but the glasses SDK
    `brilliant-msg` caps `pillow<12` and the `vision` extra (moondream /
    ultralytics) caps `pillow<11`, so the lock holds the newest allowed
    (11.3.0 / 10.4.0). Untrusted image decoding is separately hardened (figment
    decoder fuzzing + WASM resource limits). Unblocks when `brilliant-msg`
    admits pillow 12.
  - `diskcache`, `datasette` (optional infra / transitive) and `uuid` (the Expo
    *build* toolchain, not shipped in the app) — moderate, local/info-only or
    dev-only, with no clean release fix.
- **License hygiene** — a license gate fails the build on strong-copyleft
  (GPL/AGPL) dependencies in the security-critical surface it scans (crypto / PII
  / LLM / server); LGPL (weak copyleft) is allowed, matching the PR
  dependency-review. Known exception: the optional **vision** extra ships
  **ultralytics (YOLO) under AGPL-3.0** — a proprietary distribution that enables
  vision needs an Ultralytics commercial license or AGPL compliance. This is
  acknowledged explicitly in the gate rather than silently skipped.
- **Model integrity** — ML weights (a pickle-RCE surface no source scanner sees)
  are pinned by sha256 (`models.lock` / `model_guard`), loaded `weights_only`,
  and fetched only when the wearer's posture allows.

Tracked hardening (follow-up): pinning third-party GitHub Actions by commit SHA
rather than tag (OpenSSF Scorecard `Pinned-Dependencies`) — our own reusable
steps and the release-critical path are the priority.

## Not in scope

- Denial of service against your own local Brain
- Issues requiring physical possession of an unlocked device
- The demo/simulator content
