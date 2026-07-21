This one is about the phone and the Mac growing up. The Live Lens in your phone's browser is now a true 1:1 stand-in for the glasses, the app updates itself from the menu bar, and Juno gives you the tour the first time you open the lens.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle. This is also the last time you should need this page on a Mac: from 0.7.0 on, the app updates itself.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.6.0

- Live Lens is now 1:1 with the glasses. Every lens in the catalogue runs in your phone's browser, drawing the real device card the real renderer would draw, and the pairing QR actually scans on the first try. Double-tap the lens and you're in Dream Mode, exactly the gesture the glasses will use.
- The app updates itself. "Check for updates" now downloads and installs right from the menu bar, with live progress in the menu item, and relaunches into the new copy. Every byte is verified before it touches anything: the download must match the sha256 the release declares, and the install stages a copy and swaps, so a failed update can never eat your working app. On Windows the same core is wired but honestly refuses until the builds are code signed; it falls back to this page.
- One download queue. Capability packs, store plugins, and model pulls now share a single queue with live progress and a "Download all" button, instead of racing each other.
- Juno gives the tour. First time you open the Live Lens, she walks you through the actual controls: tap to look, double-tap for dreams, the veil, asking your memory. Six steps, shown once, replayable from the ? chip.
- The Mac app behaves like a Mac app. Clicking the Dock icon opens the panel, the panel window shows up in Cmd-Tab with the real icon, the app icon sits on Apple's squircle grid instead of getting boxed, and the menu-bar Juno is a proper template icon now: the system colors it, and her shape carries the status (solid online, outline offline, slash for veil).
- Three adversarial audit waves over all of it, every confirmed finding fixed with a test that fails if it comes back. The ones worth knowing: "Erase all memories" now also drops the hot sighting ring, a remembered "cupboard" can no longer fabricate a "seen before" for a cup, and the mic can never stay hot after Dream Mode ends, including when you background the tab.
- Pack installs are sturdier: one fragile dependency no longer sinks the whole pack, and whatever can install does, with the pack's full pins held so nothing drifts.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- Updates remain click-only. The app never checks in the background; nothing phones home.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
