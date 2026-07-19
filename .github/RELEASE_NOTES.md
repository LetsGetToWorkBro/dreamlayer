0.4.0 made your phone a stand-in for the glasses. 0.5.0 is the fast-follow that makes the apps themselves nicer to live with: Juno moved into your menu bar, the Learn section came alive, setup lost its rough edges, and the app grew its first community-contributed language. Smaller stories than last release, but you'll feel these every day.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel, Home, Platinum" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.4.0

- Juno IS the status light now. The menu bar on the Mac and the tray on Windows show Juno herself, tinted by what the Brain is doing — and below 24 pixels she becomes the light rather than wearing one. Glance at the corner of your screen and you know the Brain's mood. The panel's browser favicon plays along.
- The Learn section came alive. It now covers all 29 lenses, and clicking one plays the lens's actual on-glass animation — Juno's sparkle fly-in, the introduction bloom, a promise drifting toward the rim of sight. This is not a video of the product; it's the product. The exact rendering engine dreamlayer.app runs now ships inside the app, with a test that fails the build if the two ever drift apart.
- Setup lost its rough edges. The browser Live Lens handles its own TLS setup, pulling a model through Ollama shows real progress instead of a spinner of faith, capability packs install in one click, and the Juno desk accessory can be dragged wherever you like her.
- The app talks back. Found something broken? File it from inside the panel — it lands as a GitHub issue I'll actually read. The plugin store got quicker to browse, sync shows its progress, and the Cloud waitlist is one field inline instead of a prompt box.
- Hindi shipped. The phone app speaks its tenth language, and it's the first one contributed by someone who isn't me — aastha-m22 translated the whole catalog, caught a tricky "temple" (the one on your head, not the building), and iterated through three rounds of review to a clean merge. CONTRIBUTORS.md now exists because it finally has a reason to. (Phone app, so it's not in this download — but it's the same repo, and it's the milestone that matters.)
- Two community-diagnosed engine fixes closed out for good: the vector search now uses the `k = ?` form that every SQLite build serves (no more silent linear-scan on older systems), and the one flaky CI test got its race fixed rather than muted. Both found, diagnosed, and fixed by Peter Z.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/motion/object_recall.gif" alt="The real HUD renderer, animating" />

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does. Until then, the browser lens and the app's Look run the same code the glasses will.
- "Check for updates" in the menu points at this repo's releases page, only when you click it, never in the background.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel now. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
