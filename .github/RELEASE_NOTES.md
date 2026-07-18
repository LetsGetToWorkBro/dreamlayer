0.2.0 gave the Brain a face and put it on Windows. 0.3.0 is the pass where I tried to break it and couldn't. Both apps got hardened, both got more brains to plug into, and the first plugin someone who isn't me wrote is now in the store.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel, Home, Platinum" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading: drag over the old one, your data doesn't live in the app bundle.

## Install (Windows 10/11)

Download `DreamLayer-Setup.exe` below and run it. Per-user install, no admin prompt, Start menu entry, optional start when you sign in. The Brain lives in the system tray with the same menu as the Mac. Panel opens in a native WebView2 window, or your browser if you don't have the runtime.

Same two first-launch clicks as before: SmartScreen "More info, Run anyway" because this build isn't code signed yet, and the firewall "allow on private networks" so the phone can reach the panel on `:7777`. Uninstalling leaves `~/.dreamlayer` alone.

## What's new since 0.2.0

- I spent a week trying to break my own Brain and then fixed everything I found. Both the Mac and Windows appliances got a hardening pass: bounded worker concurrency so a flood of connections can't exhaust the process, tighter file permissions on your data, a clean start and stop lifecycle, and a manual "Check for updates" in the menu that pings the releases page only when you click it and never in the background. Nothing about how you use it changed. It just holds up better when poked.
- More brains to plug into, one tap each. Groq, Together, and DeepSeek are in as OpenAI-compatible presets, and the panel now one-click discovers GPT4All and KoboldCpp if you're already running them. Local stays local, remote still gets flagged and counted, same as always.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_intelligence.png" alt="Intelligence, Platinum" />

- The first community plugin shipped. Someone who isn't me wrote an Open Library book connector for TasteLens: look at a shelf, get ratings and edition info on the glass, pulled from open data with no key. It went through the same safety gate as everything else. This is the whole bet paying out, the Brain stays small and the connectors come from you.
- The plugin store shows what you're actually getting now. Every listing has a real screenshot of the plugin's on-glass output, not concept art, and a thumbnail on the tile before you open it. Browse it at dreamlayer.app/plugins or from the panel.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_capabilities.png" alt="Capabilities, Platinum" />

- The Mac dmg now wears the same Platinum window dressing as the Windows installer, so the two front doors finally match.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- The full source for the dmg and the exe is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` and `.github/workflows/build-windows-app.yml` are the recipes.
- Found something broken? Open an issue with logs and I'll actually read it. Want to write a plugin? `examples/hello-lens`, and the open issues are the menu.
