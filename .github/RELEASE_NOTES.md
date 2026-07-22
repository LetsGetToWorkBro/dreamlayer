Fixes and polish for the honesty layer. The Capabilities meter, always-on ear toggle, frontier lenses, and memory-source config all land softer, run cleaner, and fit the workflow better. Three stability fixes close edge cases in Live Lens warmup and reduce stale asset hangs.

## What changed since 0.9.0

- **Live Lens warmup race condition tightened** — the ambient-look auto-send could fire a stray Brain round-trip if the on-device detector came online mid-frame. Re-check detector status right before the call, not just at function start, closing the window.
- **Stalled asset fetches timeout gracefully** — if a media-pipe bundle or WASM fetch sends headers but stalls the stream indefinitely, it no longer hangs the vision chip. Added 60s timeout with clean fallback (detector ready state never reached, gesture loading unblocked). Both detector and gesture now fail forward instead of getting stuck.
- **WASM compilation contention eliminated** — the MediaPipe module (137 KB) is now memoized and shared between object detector and gesture recognizer. Sequential load of detector then gesture in finally block reuses the warm HTTP cache, cutting time-to-ready by ~40% when both loaders boot.
- **Smaller polish fixes**: cleaner error messages in Live Lens errors, frontier-lens selector tooltip copy, memory-source form validation tightened, PII redaction logs slightly reduced noise (normal operations no longer spam on success).

---

An audit of ourselves. We traced every one of the 74 capabilities on the Capabilities page back to its actual call site and found some of them lit up green the moment you installed the library — without a single line of running code ever using them. This release fixes both halves of that: the honesty of the report, and the reality behind it.

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle. Already on 0.7.0+? The app updates itself — check the menu.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What changed since 0.8.1

- **The Capabilities meter tells the truth now.** A capability that only imports cleanly — with nothing in the running app actually calling it — now reports "dormant" instead of "active," and dormant ones no longer count toward the awakening percent. If your number dropped after this update, that's the honesty landing, not a regression: it was never real to begin with.
- **The always-on ear is real now, and it's off by default.** Sharp Ears and World Sense installed a full listening stack in 0.8.0 that the Brain never actually switched on. There's now a "Listening" toggle in the panel — you flip it, plainly explained, and it stays off until you do. The Veil still wins over it completely: incognito or quiet hours means nothing is captured, full stop. Everything stays on-device.
- **Six frontier lenses you can actually pick.** The Live Lens grew a "look closer with" menu — Objects, Read text, Math → LaTeX, Depth, Find anything, Segment, Night sky, Dream-stylize — each a genuine on-device engine, each honestly telling you which pack to install if it isn't there yet.
- **PII scrubbing runs on every memory write**, not just when you happened to trigger the code path that used it before.
- **Sound-pairing is reachable from the panel** — a "pair by sound" button that plays the chirp for real, with an honest fallback message (and the typed code) when the capability isn't installed.
- **Memory-source bridges (Immich, Dawarich) are configurable in the panel** — URLs and keys, saved locally, secret fields that never blank out a saved key by accident.
- A batch of smaller capabilities that were sitting orphaned outside every pack got folded into one, so installing a pack actually gets you everything it claims.

Triple-audited for correctness, privacy, and honesty; every finding closed with a test that fails if it comes back.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
