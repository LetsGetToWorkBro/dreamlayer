The biggest update since the app went two-platform. The phone's World Lens now actually recognizes things on its own, the whole project has a proper dark mode, Juno found her voice, and there's a Pokemon card plugin in the store. Also two full security audit passes, because that's the job.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.5.1

- World Lens got smart. Point your phone's camera at the world and it now recognizes what it sees continuously, with zero setup. The detector runs inside the phone's browser itself, so recognition happens before anything even thinks about leaving the device. Rich result panels, real camera controls, and a pile of connection-reliability fixes came along with it.
- Midnight Platinum. Dark mode, everywhere: the website, the Brain panel, and the phone app all follow your system theme now, in the same brushed-platinum language as the light side. Your retinas at 2am are welcome.
- Juno speaks. Click her and she answers with sound, on the site, the panel, and the phone. Small thing, changes the feel completely.
- Learn is organized. The lens catalogue in the panel is grouped into eight chapters now instead of one long wall, and every lens still plays its real animation, drawn by the actual device renderer.
- Capabilities install actually installs. The one-click capability installs in the panel were quietly broken in some setups; now they stream real progress and show before/after meters so you can see what you got.
- Pairing by short code. Connecting your phone's World Lens to the Brain is now a six-character code instead of URL surgery, with an attempt cap and transport checks so the code can't be brute-forced or leaked.
- DreamShell. There's a terminal in the project now, on desktop and phone. It does more than it says it does.
- New plugin: Pokemon card prices. Look at a card, see what it's worth: the near-mint figure, the condition-adjusted price, and the low-high band, right on the glass. In the store with its real screenshot like everything else.
- Two full security audits of everything shipped since 0.4.0, then an audit of the audit. Everything found was fixed with a test that fails if it ever comes back, including a panel XSS and a decompression-bomb DoS in the image path.
- And a few things this page will not tell you about. Tap around.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, lenses, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- "Check for updates" in the menu points at this repo's releases page, only when you click it, never in the background.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes. Release assets carry Sigstore cosign bundles, so you can verify the bytes came from this repo's CI.
- Found something broken? There's a button for that in the panel. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
