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
- `plugins/` — the package format and validation gate (a plugin escaping its
  declared capabilities is a vulnerability)
- `landing/`, `web/` — the sites

Especially interesting: anything that lets a memory be written while the
Privacy Veil is down, leaks raw media that should have been structured
meaning, bypasses pairing/token auth on the Brain, or lets a plugin exceed
its capability grant.

## Not in scope

- Denial of service against your own local Brain
- Issues requiring physical possession of an unlocked device
- The demo/simulator content
