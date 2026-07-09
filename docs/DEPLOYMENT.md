# Deployment profiles — switching capabilities on

DreamLayer's 58 optional integrations are wired as lazy adapters with working
fallbacks (the full map is [`INTEGRATIONS.md`](INTEGRATIONS.md)). Nothing is
required; everything is *switchable*. This page is the operator's guide:
**one install per target, one command to see what's on, one env var to turn
any capability off without uninstalling it.**

```
pick a profile  →  install it  →  read the report  →  run the tests  →  deploy
```

## 1 · Pick a profile

A profile is a pyproject extras group that composes the capability groups a
target should carry. Pick ONE per machine:

| Target | Install | What switches on | What stays off |
|---|---|---|---|
| **Halo bridge host** | `pip install -e ".[profile-halo]"` | BLE stack (`brilliant-ble/msg`) | every model — the glasses draw cards, they don't think |
| **Pocket hub / phone-class** | `pip install -e ".[profile-phone]"` | vector recall, local embeddings, VAD + local ASR, structured intent, LLM routing | heavy vision, speaker ID, NLP, training |
| **Mac Brain** | `pip install -e ".[profile-mac]"` | everything local: memory, voice, intelligence, vision, causal, infra, privacy, platform | nothing (MLX/CoreML auto-skip off-macOS) |
| **Cloud runner** | `pip install -e ".[profile-cloud]"` | structured output, LLM routing, NLP/intelligence, causal, privacy | device stack, local vision/ASR, dashboards |

`uv` users: `uv sync --extra profile-mac` (same groups; `uv.lock` regenerates
on first sync after the pyproject change).

Notes that keep the table honest:

- **The phone app itself is React Native** — `profile-phone` is for a
  phone-*class* Python hub (a small always-on box, a dev laptop standing in
  for the pocket tier), not for Expo.
- **macOS-only capabilities** (`mlx`, `coremltools`) carry environment markers
  and simply don't install elsewhere; the report shows them `unsupported`
  rather than `missing` on Linux.
- **Ollama and exo are runtimes, not pip packages.** No profile installs them —
  run the service and the adapters find it (`--probe` below checks liveness).
- Two research-grade integrations (**diart**, the **facial-AU** backends) are
  deliberately in no profile; install them manually per their adapters'
  docstrings.

## 2 · Read the report

```bash
python -m dreamlayer.capabilities                       # human table
python -m dreamlayer.capabilities --json                # machine-readable
python -m dreamlayer.capabilities --profile profile-mac # one target's view
python -m dreamlayer.capabilities --probe               # also ping ollama/exo
```

States and what to do about them:

| State | Meaning | Action |
|---|---|---|
| `active` | installed and allowed — the adapter's real path runs | none |
| `off` | installed, but `DL_DISABLE_*` set — fallback runs by choice | unset the env var |
| `missing` | not installed — fallback runs | install the extra shown in the last column |
| `unsupported` | wrong platform (macOS-only elsewhere) | expected; nothing to do |
| `external` | a service, not a library | start it; verify with `--probe` |

The same data is importable — `from dreamlayer.capabilities import report,
enabled` — so the Brain panel or a plugin can surface it without shelling out.

## 3 · Flags: installed but off

Every capability has a kill-switch env var, `DL_DISABLE_<KEY>` (the report's
`flag` field), honored at report time and available to adapters via
`capabilities.enabled(key)`:

```bash
DL_DISABLE_LOCAL_ASR=1 python -m dreamlayer.ai_brain.server --token …
```

Use it for gradual rollout (ship the Mac profile, enable speaker ID a week
later), A/B latency tests, or emergency shut-off of one model without touching
the environment. Unset = on. The seams' own lazy `_HAS_X` guards remain the
runtime source of truth; the flag is the deliberate override on top.

## 4 · The switch-on checklist (per capability)

1. `pip install -e ".[<extra>]"` — the extra named in the report row.
2. `python -m dreamlayer.capabilities | grep <key>` → `active`.
3. Run the seam's real-path tests (they auto-unskip once the dep imports):
   `pytest -q -k <adapter>` under `src/dreamlayer/tests/test_integration_seams_pr*.py`.
4. Latency-sensitive path? Run the budget tests: `pytest -m benchmark -q`.
5. Deploy with the same env (systemd unit / launchd plist / Dockerfile carry
   the `DL_DISABLE_*` lines, if any).

Fallback drill (should always pass — it's what CI runs):
`pytest -q -m "not hardware and not benchmark"` with no extras installed.

## 5 · CI

The default workflow already runs the zero-deps fallback suite on every push —
that is the invariant that makes profiles safe (any machine, any subset, same
behavior contract). When real-path validation in CI becomes worth the minutes,
add a matrix job per profile:

```yaml
strategy:
  matrix: { profile: [profile-phone, profile-cloud] }   # mac profile needs a mac runner
steps:
  - run: pip install -e "host-python[${{ matrix.profile }},dev]"
  - run: cd host-python && python -m dreamlayer.capabilities
  - run: cd host-python && pytest -q -m "not hardware and not benchmark"
```

## Design notes (why it's built this way)

- **No eager imports.** The report probes with `importlib.util.find_spec`,
  which reads metadata without executing modules — a broken native wheel can't
  crash startup, and boot cost stays zero. (Trade-off: a broken wheel shows
  `installed`; its adapter still falls back safely at import time.)
- **No second gating system.** Adapters keep their `try/except → fallback`
  guards as runtime truth; `capabilities.py` is observability over them, plus
  one optional env override. There is no registry call sites must consult.
- **No hand-maintained sync.** Per-capability profile membership is *derived*
  from the profile→extras map, and `tests/test_capabilities.py` asserts
  `capabilities.py` ↔ `pyproject.toml` equality in both directions — drift is
  a red test, not a stale comment.
