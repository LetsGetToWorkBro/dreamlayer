# DreamLayer — concurrency model

The hub (Orchestrator) and the Brain server are mostly single-threaded request/
tick code with a small, deliberate set of background workers. This document is
the honest inventory — what runs on which thread, how they hand off, and the two
clock conventions to be aware of. It exists because "how is this concurrent?"
had no single answer before.

## The main thread

Almost everything runs here, synchronously:
- The **Orchestrator tick** (`Orchestrator.tick`, ~4 Hz when driven) and every
  public method (`glance`, `handle_voice`, `ingest_caption`, `look_at_object`,
  the lens wrappers). These are pure/synchronous — call, mutate state, emit a
  card via `self.bridge`, return.
- The **Brain HTTP server** is a stdlib `ThreadingHTTPServer`, so each request
  is handled on a short-lived worker thread, but request handlers touch only
  their own `Brain` state under the GIL and finish fast.

## Background daemon threads (opt-in, explicit start/stop)

Each is spawned by an explicit `start_*` call, runs a `while not stop_event`
loop, and is torn down by the matching `stop_*`. All are daemon threads (they
never block interpreter exit). Pattern origin: `start_message_polling`.

| Worker | Started by | Loop | Stopped by |
|---|---|---|---|
| Message polling | `start_message_polling()` | polls the Brain feed, flashes new incoming messages | `stop_message_polling()` (sets `_msg_poll_stop`) |
| Context pulse | `start_pulse(context_fn)` | feeds live context to anticipation/attention each interval | `stop_pulse()` (sets `_tick_stop`) |
| Capture pipeline | `CapturePipeline.start()` | pulls PCM from the mic source, VAD-gates, transcribes, routes to `hear`/`ingest_caption` | `.stop()` |
| BLE loop (real device) | `RealBridge._ensure_loop()` | a dedicated asyncio loop on thread `dreamlayer-ble`; sends marshalled via `run_coroutine_threadsafe` | bridge disconnect |
| World-check worker | `WorldChecker` (`ai_brain/world_check.py`) | one serial `ThreadPoolExecutor(max_workers=1)` runs off-caption-path verifications under a deadline | pool shutdown |
| Latency-budget pool | `orchestrator/budgets.py` | shared `ThreadPoolExecutor(max_workers=4)` for per-tier deadlines; abandoned calls finish in the background and are dropped | process exit |

Rule of thumb: **the hub owns no thread you didn't start.** A fresh
`Orchestrator(bridge)` spawns nothing until a `start_*` is called — which is why
the test suite (thousands of constructions) stays deterministic.

## asyncio

Two async surfaces, both isolated from the sync main thread:
- **DreamEngine ambient loop** (`dream_mode/engine.py`, 2 Hz) — runs on the
  asyncio loop when one is active; `start()` is a safe no-op when no loop is
  running (test-safety), so it never blocks a synchronous caller.
- **`_vision_describe`** is `async` because the vision pipeline is; it's awaited
  by the DreamEngine describer, never by the sync hub path.
- **RealBridge** owns its *own* asyncio loop on a dedicated thread and marshals
  every call in via `run_coroutine_threadsafe(...)` — the sync hub never touches
  that loop directly.

There is no single global event loop the whole system shares; async is used
locally where a subsystem is inherently async, and bridged back to sync at the
seam.

## The two clock conventions (a known hazard)

Two clocks coexist deliberately, and mixing them is the one real footgun:

- **`self._clock()` → `time.monotonic()`** — used for *durations and cooldowns*
  that must be immune to wall-clock jumps (Juno session window, glance-intent
  freshness, hark pacing). Never persist a monotonic value; it's meaningless
  across processes.
- **`time.time()` (wall clock)** — used where a method takes a `now: float |
  None` parameter, for *timestamps* that get stored or compared to stored
  values (memory `created_at`, retention windows, REM seeds, maturity arc).

When adding a method: if the value is a stopwatch, use `_clock()`; if it's a
timestamp that lands in the DB or a card, use `time.time()`/the injected `now`.
The extracted ops mixins preserve whichever clock each method already used — the
decomposition changed no clocks.

## Structured logging

`DL_LOG_JSON=1` switches the root handler to one JSON line per record
(`dreamlayer/logging_setup.py`, wired in the Brain's `__main__`). Off by default;
purely a formatting change, so it's safe to leave on in a service/CI context to
get machine-parseable logs across all these threads.
