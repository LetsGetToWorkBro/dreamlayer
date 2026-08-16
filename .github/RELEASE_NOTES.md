The privacy release. We went looking for the gaps between what this project promises and what the code does, and closed every one we found — including one that mattered: an optional vision backend whose library turns out to phone home by default. It never returned an answer without an API key, but the frame still left the device. That path is dead now, three tests deep, and the whole hunt is written up in the repo for anyone to check.

## What changed since 0.9.2

### Privacy, verified

- **The moondream vision backend can no longer reach the cloud.** Every packaged release of the moondream library defaults `vl()` to a *cloud* client that transmits the image before authentication fails. If you had installed the vision pack, the ambient camera loop could send frames to a third-party API — never returning an answer, but the bytes left. The adapter now constructs the on-device runtime only, and three tests (one behavioral, one degradation, one source tripwire) fail if a cloud construction ever comes back.
- **One Veil gate, not twelve.** The incognito check existed as twelve hand-written copies, and two of them disagreed. There is one now, it fails closed on capture and stays open on recall, and a test asserts nothing writes while veiled — by watching the persistence layer, not the return values.
- **Installing a plugin by name no longer fetches while the Veil is up.** The registry fetch is behind the same consent + Veil gate as everything else consequential, and the attempt itself is noted in your ledger.
- **The plugin OS sandbox is enforced, and now tested from inside.** The jail's denial is asserted at the kernel level from within the sandboxed child; the sandbox works on merged-/usr Linux; and the child's environment is built from scratch instead of inherited, so your shell secrets don't ride into a plugin.
- **Consent has one gate and a real surface.** The two keyless connectors the Brain can reach are registered in the consent registry; the six it cannot reach are recorded as such, with the reasoning in `decisions/`.

### The Brain remembers better

- **"Hi, I'm Maya" — remembered.** Name capture from live introductions, and the recognizer only ever matches people you introduced. A stranger stays a stranger.
- **Memories have an author now.** Voice recall knows who was speaking, and the ear can tell two voices apart.
- **The retention lifecycle actually runs.** Memories age, decay, and expire on the shipped Brain — the oldest finding in `decisions/` (0001), finally closed.
- **Your repertoire follows you.** CRDT sync carries it across every device you own, no server involved.
- **A rare word heard in conversation gets defined** on the caption path, quietly.

### Honesty, continued

- **HUD cards: 23 of 24 declared cards now render on the phone**, and the checkers fail in both directions — a card that can't render and a renderer with no card.
- **The capability meter stops lying in the remaining direction.** Installs that couldn't switch a feature on aren't offered; claims a runner never used are dropped; "loadable" no longer counts as "on".
- **Releases are actually signed now.** The signing workflow silently never fired (CI-published releases can't trigger their own automation — a GitHub rule we now route around). v0.9.1 and v0.9.2 were signed retroactively; this release signs on publish.
- **The tests that ran nowhere, run.** 149 tests were silently skipped in every CI environment; the wheels they needed are installed and a weekly triage loop now files an issue when anything—a skipped test, a red gate nobody watches, a waiting contributor—goes unnoticed.

### Quality of life

- **Vision and glasses packs install together now.** The dependency conflict that made the vision pack mutually exclusive with the glasses bridge is gone (six lockfile conflict pairs dissolved).
- **Windows: fewer "file in use" failures.** The atomic-replace retry budget now outlasts Defender-class scans holding files open.
- **macOS Mail reads per-account**, mirroring the calendar allow-list, and the panel tells you when macOS itself is blocking a source.
- **Reduced motion is honored** system-wide, and the missing screen-reader labels are in.
- **Local model discovery** finds Msty and SGLang servers on their default ports.

---

Incremental quality pass on Live Lens and the memory graph. Panel updates and rendering fixes, plus a batch of edge-case closes on the on-glass lenses.

## What changed since 0.9.1

- **Panel rendering pipeline simplified** — reduced redraws on state changes, especially on the Capabilities page when installs complete.
- **Memory graph query speed** — temporal lookups ("who did I meet last week") now use an indexed time cursor instead of full-table scan, cutting latency 60-80% on large brains.
- **Live Lens gesture recognizer** — false-positive swipes significantly reduced; the detector now requires explicit motion vectors instead of just hand-pose changes.
- **Audio-only frontier lens** — when the camera is off but the mic is on (reading mode), audio source direction is now detectable, so you know which speaker just said something.
- **Memory-source sync robustness** — retries on transient network glitches (Immich/Dawarich timeouts) now back off exponentially instead of tight-looping.
- **Polish**: cleaner memory-source error messages, Listening toggle now remembers its state across sessions, fewer stale asset warnings on re-open.

---

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
