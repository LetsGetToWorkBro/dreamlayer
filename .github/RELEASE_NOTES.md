A cleanup pass on 0.8.0: a triple-audit of the Live Lens plus a batch of reported-bug fixes. Nothing new to learn here, just things that should have worked already, working.

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle. Already on 0.7.0+? The app updates itself — check the menu.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## Fixed since 0.8.0

- **Live Lens QR pairing** — the pairing QR scans reliably now.
- **Honest warm-up state** — while the on-device vision model is loading, the Live Lens now says so ("vision loading…") instead of looking like it's just slow to recognize things; and a stalled asset load can no longer hang the page forever — it falls back cleanly instead.
- **Download All** actually queues everything now, and the packs page reflects real state as installs complete.
- **App icon** is full-bleed on both platforms — the padded/boxed look some setups showed is gone.
- **Lens Builder 404s** — its theme, fonts, and script assets used to 404 as siblings of the page; they're served from one consistent path now.
- **Closing the panel window doesn't quit the Brain.** DreamLayer is a menu-bar appliance — the red button / Cmd-W now tucks the window away and drops back to the tray, the same posture as minimizing, instead of ending the process.
- **Update checks are quieter and safer.** A one-time check a few seconds after launch, off the main thread — never a background poll, never a silent install. If something newer exists, the menu badges itself; you still choose when to install.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
