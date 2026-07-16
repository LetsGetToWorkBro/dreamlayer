# DreamLayer Brain — the double-click apps

Packages the Brain as a double-click **always-on appliance** so you don't need
the terminal: a **menu-bar app** on macOS (.dmg) and a **system-tray app** on
Windows (installer). Launch it, get a DreamLayer dot, click it to open the
control panel or quit. State lives in `~/.dreamlayer` on both, same as the CLI.

- `app_main.py` — the shared bundled entry: starts the Brain server on a
  background thread, then runs the platform appliance on the main thread
  (rumps menu bar on macOS, pystray tray on Windows).
- `windows/` — the Windows build: `make_ico.py`, `make_installer_art.py`
  (the Platinum wizard bitmaps), `DreamLayer.spec` (PyInstaller),
  `installer.iss` (Inno Setup). See the Windows section below.

## macOS (.dmg)

- `setup_app.py` — py2app build config (produces `dist/DreamLayer.app`,
  `LSUIElement` = no Dock icon).
- `entitlements.plist` — hardened-runtime + AppleEvents entitlements for signing.
- `icon.png` — 1024² source; CI turns it into `dreamlayer.icns`.
- `make_dmg_art.py` — the Platinum `.dmg` window background (the dusk gradient
  off the icon, Chicago wordmark, a drag arrow to Applications) at 1x and @2x;
  CI staples them into a HiDPI tiff and hands it to `create-dmg` along with the
  volume icon. Generated at build time like the Windows wizard art — never
  committed.
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

---

# Windows (installer)

The same Brain as a **system-tray app**: `DreamLayer.exe` runs the server on a
background thread and a tray dot (green / yellow / incognito / grey) with the
same menu as the Mac menu bar — Open panel (a native WebView2 window, browser
fallback), Sync now, Incognito, Quit. The panel, pairing, and phone flows are
identical; what differs is stated honestly in the panel (no iMessage on
Windows; mail reads from a local Thunderbird profile; calendars come from
`.ics` files/URLs).

## Get the installer (recommended: CI)

The workflow runs on a GitHub `windows-latest` runner
(`.github/workflows/build-windows-app.yml`):

1. **Actions → Build Windows app (installer) → Run workflow** (or push a `v*`
   tag, which also attaches `DreamLayer-Setup.exe` to the GitHub Release).
2. Download the `DreamLayer-windows` artifact.

**Authenticode signing (optional).** Unsigned builds work but trip Defender
SmartScreen (below). To sign, add these repo secrets and CI signs both the exe
and the installer with `signtool`:

| Secret | What it is |
| --- | --- |
| `WINDOWS_CERT_PFX_BASE64` | Your code-signing cert + private key as a `.pfx`, base64-encoded |
| `WINDOWS_CERT_PASSWORD` | Password for that `.pfx` |

## Build locally on Windows

```powershell
cd host-python
pip install .                        # dreamlayer + deps
pip install pystray pywebview zeroconf cryptography pyinstaller
cd packaging\windows
python make_ico.py                   # icon.png/icon_small.png -> dreamlayer.ico
python make_installer_art.py         # -> wizard.bmp / wizard-small.bmp (Platinum installer art)
pyinstaller DreamLayer.spec          # -> dist\DreamLayer\DreamLayer.exe
iscc /DAppVersion=0.5.0 installer.iss   # -> Output\DreamLayer-Setup.exe
```

The installer is **per-user** (no admin prompt): it copies the app under
`%LOCALAPPDATA%\Programs\DreamLayer`, adds a Start-menu entry, and offers
"Start DreamLayer when you sign in" (an HKCU Run entry — the same one
`python -m dreamlayer.ai_brain.tray_windows --install-login` /
`--uninstall-login` manages). Uninstalling removes the app and that Run entry
but **leaves `~/.dreamlayer`** (settings, index, history) in place — the
uninstaller says so.

## First-run on Windows (the honest version)

- **Defender SmartScreen** — an unsigned build shows "Windows protected your
  PC" on first launch: click **More info → Run anyway**. This is Windows'
  Gatekeeper moment; a signed CI build (secrets above) builds reputation and
  eventually opens without it.
- **Windows Firewall** — on first launch Windows asks to allow incoming
  connections for DreamLayer. **Allow on private networks** — the phone can't
  reach the panel on `:7777` without it. The Brain still binds the LAN behind
  a pairing token minted on first run.
- **WebView2** — "Open panel" uses the Edge WebView2 runtime (preinstalled on
  Windows 11 and most 10 machines). Without it the panel simply opens in your
  browser instead.
- **Ollama** (optional) — install from ollama.com for written answers;
  without it the Brain runs in keyword mode, exactly like the Mac.
- **What the Brain can read here** — your chosen folders, Thunderbird mail
  (if present, and only when you flip the switch), and `.ics` calendar
  files/URLs. iMessage, macOS Contacts and Reminders don't exist on Windows;
  the panel reports each honestly instead of pretending.
