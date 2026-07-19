A same-day patch to 0.5.0, and it's all about the plugin store. If you downloaded 0.5.0 this morning, this is worth the re-download; if you're new, start here.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/plugins.png" alt="The plugin store, front and center" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.5.0

- The store is the page now. Open Plugins and the full catalogue is just there — every plugin with its real on-glass screenshot, the official badge, and a one-click Install. No "browse" click, no second web page, nothing external. Same gate as always: integrity check, capability scan, and a smoke test before anything runs.
- Every plugin wears its shot. The last two listings without screenshots (Open Library and Vinyl Oracle) got theirs — rendered through the actual device renderer with the plugin's real fields, and captioned with exactly what leaves your machine ("only the title leaves", "only artist + title leave"). No concept art in the store, ever.
- Fixed: plugin thumbnails were broken boxes in 0.4.0 and 0.5.0. This morning's security hardening (correctly) blocks the panel from loading remote images — which quietly took the store thumbnails with it. Rather than punch a hole in that policy, the screenshots now ship inside the app and load from your own machine. The security stays; the pictures come back; the panel still fetches nothing from anyone.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- "Check for updates" in the menu points at this repo's releases page, only when you click it, never in the background.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
