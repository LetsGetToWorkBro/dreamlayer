# DreamLayer Brain — macOS app (.dmg)

Packages the Brain as a double-click **menu-bar app** so you don't need the
terminal. Launch it, get a DreamLayer dot in the menu bar, click it to open the
control panel or quit. State still lives in `~/.dreamlayer`, same as the CLI.

- `app_main.py` — the bundled entry: starts the Brain server on a background
  thread, then runs the rumps menu bar on the main thread.
- `setup_app.py` — py2app build config (produces `dist/DreamLayer.app`,
  `LSUIElement` = no Dock icon).
- `entitlements.plist` — hardened-runtime + AppleEvents entitlements for signing.
- `icon.png` — 1024² source; CI turns it into `dreamlayer.icns`.
- The build/sign/notarize/dmg pipeline lives in
  `.github/workflows/build-macos-app.yml`.

## Get the .dmg (recommended: CI)

A macOS `.app`/`.dmg` must be built **on macOS**, so the workflow runs on a
GitHub `macos-14` runner.

1. Add these repo secrets (Settings → Secrets and variables → Actions):

   | Secret | What it is |
   | --- | --- |
   | `MACOS_CERT_P12_BASE64` | Your **Developer ID Application** cert + private key, exported from Keychain as a `.p12`, then `base64` encoded |
   | `MACOS_CERT_PASSWORD` | Password you set on that `.p12` |
   | `MACOS_SIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
   | `APPLE_ID` | Apple ID email for notarization |
   | `APPLE_TEAM_ID` | 10-char Team ID |
   | `APPLE_APP_PASSWORD` | App-specific password (create at appleid.apple.com → Sign-In & Security) |
   | `KEYCHAIN_PASSWORD` | Any string; password for the ephemeral CI keychain |

   Export the cert as base64 on your Mac:
   ```sh
   base64 -i DeveloperID.p12 | pbcopy   # paste into MACOS_CERT_P12_BASE64
   ```

2. Run it: **Actions → Build macOS app (.dmg) → Run workflow** (or push a tag
   like `v0.5.0`, which also attaches the `.dmg` to a GitHub Release).

3. Download the `DreamLayer-dmg` artifact. Because it's signed + notarized +
   stapled, it opens with a **normal double-click** — drag DreamLayer to
   Applications, done.

## Build locally on a Mac (unsigned, for testing)

```sh
cd host-python
pip install .            # dreamlayer + deps
pip install py2app rumps
cd packaging
# make the icon (once):
mkdir -p DreamLayer.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s icon.png --out DreamLayer.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) icon.png --out DreamLayer.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns DreamLayer.iconset -o dreamlayer.icns
python setup_app.py py2app
open dist/DreamLayer.app
```
An unsigned local build works, but Gatekeeper flags it on first open
(right-click → Open once). The CI build above avoids that.

## First-run permissions (grant once)

The Brain reads your calendar/contacts/reminders and (optionally) Messages &
Mail to build your daily brief. macOS will prompt the first time; you grant them
to **DreamLayer** (not to Terminal):

- **Automation** — allow when prompted (Calendar / Contacts / Reminders).
- **Full Disk Access** — System Settings → Privacy & Security → Full Disk
  Access → add DreamLayer. Only needed for iMessage/Mail history.
- **Local network / firewall** — allow incoming connections so the phone can
  reach the panel on `:7777`.
- **Ollama** (optional) — for the local LLM; install separately from ollama.com.
  Without it the Brain runs in keyword-only mode.
