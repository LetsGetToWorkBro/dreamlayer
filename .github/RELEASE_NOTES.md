0.3.0 was the week I tried to break the Brain and couldn't. 0.4.0 is the release where your phone becomes the glasses. Any phone browser on your LAN can now draw the real HUD from a real camera frame, the app's Look screen runs the exact same pipeline, and the Brain can hand you a signed receipt proving what it did. There was also a full adversarial security audit the morning of this build, because shipping day is exactly when you should be paranoid.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel, Home, Platinum" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.3.0

- The phone is the glasses now. Your Brain serves a page on your LAN that turns any phone browser into the Halo: tap the glass, a real camera frame runs the full World-lens pipeline in your Brain (recognizer, Object Lens, your installed plugins), and the exact HUD the glasses would draw renders back in the circle. The phone app's Look screen is the same single pipeline, and it now shows the on-glass preview: the same budget-clamped lines the Halo would draw, five lines max, 24 bytes each, because that's the real display budget. One pipeline, three surfaces, zero mockups.
- Looks respect the shield. In incognito, LAN-only, or quiet hours, a look still answers, but from a local-only classifier: the panel says "local only", nothing leaves the machine, nothing is traced. Frames are never stored anywhere on any path, and plugin rows see the recognized label, never the pixels.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/motion/object_recall.gif" alt="The real HUD renderer, animating" />

- Privacy receipts you can verify. The panel and the phone now show a signed receipt of what your Brain did: Ed25519 signature over a hash chain, verified on your device, with trust-on-first-use key pinning. And as of this morning's audit, a keychain-backed watermark means a rolled-back or wiped ledger can't pretend to be a clean one. Don't trust the checkmark, verify it. The button is right there.
- Bundled plugins run on Windows now too. First-party plugins are pinned by content hash and run in-process on both platforms, through the same safety gate as everything else in the store.
- The morning-of-release audit. An adversarial pass over the Brain's request surface on the day of this build: a panel XSS reachable from a hostile calendar name, a DNS-rebinding hole that now gets a 421 before the panel token is ever served, CSP on the token-bearing pages, upload path confinement so a crafted filename can't write outside the watched folder, an SSRF guard so a cloud-hosted Brain can't be turned into a credential proxy, and state files born owner-only on both platforms. One item came in through coordinated disclosure. Every fix ships with a revert-failing regression test, the suite stands at 3568 passing, and the mitigations are recorded in `SECURITY.md`.
- `dreamlayer setup models` is one command that bootstraps the `[privacy]` NER models, so on-device redaction works out of the box instead of after a scavenger hunt.
- Community fixes are in the engine now. This release carries several from Peter Z, including a real bug in the vector search SQL and hardened coverage across the voice pipeline. Last release the store got its first plugin from someone who isn't me. This release the engine got its first fixes from someone who isn't me. That's the trend line I wanted.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_capabilities.png" alt="Capabilities, Platinum" />

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does. Until then, the browser lens and the app's Look are the honest stand-in, and they run the same code the glasses will.
- "Check for updates" in the menu points at this repo's releases page now, only when you click it, never in the background.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets also carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? Open an issue with logs and I'll actually read it. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
