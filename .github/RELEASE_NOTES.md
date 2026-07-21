The biggest batch yet. Juno actually speaks now, the Brain grew real senses — hearing, sight, even the night sky — and the Capabilities page got rebuilt around one honest number: how awake your Brain actually is. Everything below is opt-in, lazy-imported, and falls back gracefully with nothing installed — the core app is exactly as light as it was yesterday.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/v08_setup.png" alt="Juno's first-run setup walkthrough" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle. Already on 0.7.0? The app updates itself now — check the menu.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.7.0

### Juno speaks

Turn her on and the Brain answers out loud, entirely on-device — no cloud voice, no API credits. Kokoro (82M params, strikingly natural) is used when installed; Piper is the always-available fallback. There's even an opt-in path where she speaks in her *own* voice, cloned offline from her existing clips. And a live interpreter (Meta's SeamlessM4T) can translate a real conversation in your ear, both directions, audio never leaving the Brain.

### The Capabilities page, rebuilt

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/v08_capabilities.png" alt="The Capabilities page with the new awakening meter" />

One number at the top now: how awakened your Brain is, as a percent and a level — Dormant climbing to Ascendant — broken down by tier (Memory, Hearing, Sight, Understanding, and more) so you can see exactly what installing a pack unlocks. Four new packs join the original five: **Interpreter** (the live speech translator), **World Sense** (hearing beyond speech — alarms, doorbell, breaking glass, birdsong, on-device OCR and barcode reading, a sense of depth), **Stargazer** (name the planets and catch the ISS crossing, computed fully offline from local star data), and **Mind Palace** (a temporal knowledge graph and spaced-repetition rehearsal, so the Brain resurfaces a name right before you'd forget it).

### The world got senses

The Brain now notices sound it isn't listening *to* — a smoke alarm, a kettle, glass breaking, a doorbell — and taps you, without ever fingerprinting a voice. On a walk it can name the birdsong overhead. Point it at a barcode and it checks the product against your dietary rules. Show it a menu, a receipt, or a whiteboard and it reads the text, on-device, every line scrubbed for names before it surfaces. Show it a math equation and it reads that too.

### Bridges to what you already run

If you self-host Immich, Home Assistant, Dawarich, Syncthing, screenpipe, or ActivityWatch, the Brain can now read from them as memory sources — your own photos, your own house, your own location history, all on your own LAN, nothing routed through us. And the tincan bond can now ride an off-grid LoRa mesh (Meshtastic) for miles of range with no wifi and no cell signal at all.

### Pairing by sound

A new fallback for connecting your phone: the Brain sings the short pairing code as a near-ultrasonic chirp, and a phone in earshot catches it out of the air — no camera, no typing. The QR and typed-code paths are unchanged; this just adds a third way in when neither is convenient.

### The full glasses demo, on the Live Lens

Live captions, Dream Mode's real synesthesia (an actual scene describer painting the mood, not a placeholder), memory-echo ghosts layered over what you're looking at, and a client-verified privacy receipt you can check yourself, cryptographically, without trusting the panel to tell the truth. Two phones running Confluence now share one dreamed sky together, on the real rendering engine both sides trust.

### Ten desktop fixes

Collapsible pairing QR, one clean app icon everywhere, a visible per-item download queue, an expandable status tray, first-run walkthrough (that's Juno at the top of this page), searchable settings, a reachable bug-report button, and Learn's cards all running live animation now.

### Meeting mode + consent-based recognition

Recognition is consent-aware now — introduce someone once ("this is Sarah") and the Brain remembers them; a genuine stranger is still never identified. Turn on Meeting mode and it captures attendees, notes, and the action items pulled out of what was actually said.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- Every integration above is opt-in and lazily imported — install nothing extra and the app behaves exactly as it did in 0.7.0. The Capabilities page is the honest map of what each one costs and unlocks.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
