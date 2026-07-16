The Brain got a face. The entire control panel is now Mac OS 8.1 Platinum: pinstripe title bars, Chicago type, real window chrome, the works. It matches the new dreamlayer.app desktop, because your local brain and its website should look like they came from the same machine. Same engine underneath. Zero features touched, zero features lost.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_home.png" alt="The Brain panel, Home, Platinum" />

## Install (macOS 12+)

Download `DreamLayer.dmg` below, double-click, drag DreamLayer to Applications. Runs from the menu bar. Signed and notarized, so Gatekeeper stays quiet. Upgrading from 0.1.0: drag over the old one, your data doesn't live in the app bundle.

## What's new since 0.1.0

- The whole panel is a Platinum desktop now. Every card is a proper window with a pinstriped title bar. If you know why the corners look like that, welcome home. If you don't, it still just works.
- Juno lives on the panel as a desk accessory. A little animated window in the corner, "the brain is listening." It is not a mascot, it is a status light with wings.
- Real fonts ship inside the app, ChicagoFLF and Space Grotesk. Nothing is fetched from a CDN, because nothing in this app fetches anything unless you turn cloud on.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_intelligence.png" alt="Intelligence, Platinum" />

- Same brain controls as 0.1.0 under the new paint: keyword search with zero models, Ollama, or plug in whatever agent you already run. One tap, local stays local, remote gets flagged and counted.

<img src="https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/docs/gitbook/assets/panel/platinum_capabilities.png" alt="Capabilities, Platinum" />

- The rest of the family got the same treatment: dreamlayer.app is a Platinum desktop, and the phone app shipped its own Platinum reskin with a new 5-tab layout. Those live in this repo too, they just don't ship in this dmg.

## Good to know

- Still a pre-hardware build. The Brain, panel, phone pairing, plugins, and simulator are real and running. The physical glasses seams (camera, mic, BLE) connect when hardware does.
- The full source for everything in this dmg is this repository. Don't trust me, build it yourself: `.github/workflows/build-macos-app.yml` is the recipe.
- Found something broken? Open an issue with logs and I'll actually read it. Want a lens? `examples/hello-lens`.
