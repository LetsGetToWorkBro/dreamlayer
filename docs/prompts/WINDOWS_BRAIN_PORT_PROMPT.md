# Prompt: Bring the DreamLayer Brain to Windows (parity with the macOS app)

> Paste everything below the line into a Claude (Fable 5) session opened on
> this repository. Best run in plan mode first: let it produce the plan, review
> it, then approve implementation.

---

You are working in the DreamLayer repository. Your task: ship the **Brain as a
first-class Windows application** with the same functionality, features, and
UI/UX as the macOS menu-bar app — a double-click installer, an always-on
system-tray appliance, and the same control panel.

## The one fact that shapes everything

The Brain's engine (`host-python/`) is already cross-platform Python — the
server, indexing, panel, and answer paths run anywhere. What is macOS-only is
the **appliance shell** and a handful of **Apple data sources**. This is NOT a
rewrite: it is a Windows shell around the same engine, plus honest Windows
equivalents (or honest absences) for the Apple-only seams. One codebase; the
repo's existing pattern is guarded imports that load-and-no-op off-platform —
follow it everywhere.

## Ground truth to read first

- `host-python/packaging/` — the macOS app: `app_main.py` (server on a daemon
  thread + rumps menu bar on main), `setup_app.py` (py2app, LSUIElement),
  `entitlements.plist`, and `packaging/README.md` (the .dmg pipeline and
  first-run permissions story you will mirror).
- `host-python/src/dreamlayer/ai_brain/menubar.py` — the menu-bar appliance:
  a **pure, unit-tested core** (`status_summary`, LaunchAgent plist writer)
  with the rumps GUI loaded lazily. Traffic-light status dot, one-click
  Incognito, "Sync now", "Open panel", start-at-login via
  `--install-login`. Your tray app mirrors this structure exactly.
- `host-python/src/dreamlayer/ai_brain/webview_window.py` — the native panel
  window (PyObjC + WKWebView), every import guarded, returns False → browser
  fallback. Your Windows twin follows the same contract.
- `host-python/src/dreamlayer/ai_brain/server/macos_sources.py` — iMessage
  (SQLite `chat.db`) and Apple Mail (`.emlx`) readers: parsing is pure and
  unit-tested against fixtures; OS access returns `[]` off-macOS. Sending is
  approval-gated.
- `host-python/src/dreamlayer/ai_brain/server/brain_calendar.py` + the
  `start_calendar_sync()` seam in `server.py` — macOS Calendar → agenda, built
  as an injectable seam for tests.
- `host-python/src/dreamlayer/ai_brain/mlx_backend.py` — Apple-Silicon-only by
  design; `available` is already False elsewhere. Nothing to port: Ollama and
  the seven cloud presets are the Windows answer paths.
- `.github/workflows/build-macos-app.yml` — the build/sign/notarize/release
  pipeline your Windows workflow parallels.
- `docs/AI_BRAIN.md`, `docs/PRIVACY_MODEL.md`, `host-python/src/dreamlayer/`
  capability reporting — the Brain reports what it can and cannot do
  **honestly**; Windows must join that system, never fake a capability.

## The work

### 1. Windows tray appliance (`ai_brain/tray_windows.py` or similar)
Mirror `menubar.py`'s architecture: a pure, unit-testable core + a lazily
imported GUI (recommend `pystray` + `Pillow` for the icon; pick and justify).

- Status dot with the same traffic-light semantics, fed from
  `/dreamlayer/status` exactly like `status_summary` does today (reuse it —
  it's pure; don't duplicate it).
- Menu: Open panel, Incognito toggle, Sync now, status lines, Quit — same
  items, same wording as the Mac menu.
- Start at login: the LaunchAgent equivalent is a `--install-login` flag that
  writes a Startup-folder shortcut or `HKCU\...\Run` entry (pick one, make it
  reversible with `--uninstall-login`, and unit-test the pure
  entry-construction part like the plist writer is tested today).
- A Windows `app_main.py` twin (or a platform branch in it): server on a
  daemon thread, tray on the main thread, same first-run token minting, state
  in `~/.dreamlayer` via `Path.home()` as today.

### 2. Native panel window
A Windows counterpart to `webview_window.py` using WebView2 (via `pywebview`
or `webview2` bindings — justify the pick, prefer the lightest dependency).
Same contract: guarded imports, loads-and-no-ops elsewhere, any failure
returns False and the caller falls back to the browser tab. Same window title,
size, and behavior as the Mac panel window so the product feels identical.

### 3. Windows data sources — honest equivalents, honest absences
Create `server/windows_sources.py` in the image of `macos_sources.py` (pure
parsing, fixture-tested; OS access returns `[]` off-Windows):

- **Mail**: no Apple Mail on Windows. If a low-dependency, local, read-only
  source exists on the user's machine (e.g. Thunderbird's local maildir/mbox),
  wire it behind the same capability flag; otherwise report the capability as
  unavailable on Windows. Never scrape Outlook via COM automation silently —
  if you add an Outlook seam, it is opt-in, read-only, and clearly surfaced in
  the panel like Mail/Messages are on macOS.
- **Messages**: iMessage does not exist on Windows — report it honestly
  unavailable (the capabilities system already knows how to say this).
- **Calendar**: mirror the injectable-seam design: an ICS-file/URL source is
  the portable answer; wire it through the same `start_calendar_sync()` seam
  so the agenda works identically.
- Update the capabilities/panel copy so a Windows user sees exactly what their
  Brain can and cannot read, in the same plain voice as macOS.

### 4. Packaging & installer
- PyInstaller (windowed, one-dir) building `DreamLayer.exe` with a proper
  `.ico` generated from `packaging/icon.png`, plus an installer (Inno Setup
  recommended; WiX/MSI acceptable — justify) that installs per-user, creates
  the Start-menu entry, offers "start at login", and uninstalls cleanly
  (leaving `~/.dreamlayer` user data in place, stated in the uninstaller).
- New workflow `.github/workflows/build-windows-app.yml` on `windows-latest`,
  paralleling the macOS one: build → smoke-launch → upload artifact → attach
  to `v*` tag releases. Support optional Authenticode signing via repo
  secrets, and document the SmartScreen reality for unsigned builds the way
  `packaging/README.md` documents Gatekeeper.
- `packaging/README.md` gains a Windows section (or a sibling
  `README-windows.md`): CI path, local build path, and the first-run story —
  Defender SmartScreen, the Windows Firewall prompt for `:7777` (needed so the
  phone can reach the panel), Ollama optional.

### 5. Cross-platform hygiene sweep
Audit the engine for silent POSIX assumptions now that Windows is a real
target: path handling (no hardcoded `/` joins or `~` expansion outside
`Path`), atomic writes (`os.replace` semantics on Windows), file watching on
NTFS, long-path and reserved-filename edge cases in the indexer, port-in-use
behavior, and console-less operation (a windowed exe has no stdout — make
sure logging goes to a file under `~/.dreamlayer` and nothing crashes on
`print`). Fix what you find with tests.

### 6. Tests & CI
- Every pure core you add is unit-tested like its macOS twin (tray status,
  login-entry writer, windows_sources parsers against fixtures).
- Add a `windows-latest` leg to the pytest workflow (at minimum the ai_brain
  and indexer suites) so Windows regressions fail CI, not users.
- Update `docs/TESTING.md` with the Windows walkthrough: install, launch,
  pair the phone, ask from the panel.

## Constraints (non-negotiable)

- The privacy contract is the architecture: server binds localhost by default
  and the LAN exposure remains a deliberate user act; nothing marked private
  leaves; capture stays veil-gated; no new telemetry, no new cloud calls.
- Honest capability reporting: a Windows Brain that can't read iMessage says
  so — it never pretends, stubs with fake data outside Demo paths, or fails
  silently.
- One codebase, guarded imports: every Windows module loads (and no-ops) on
  macOS/Linux/CI, exactly as the macOS modules do today.
- The panel HTML/design (Platinum) is shared and already cross-platform — do
  not fork or restyle it.
- macOS behavior byte-for-byte unchanged; the existing test suite
  (3,000+ tests) stays green.

## Definition of done

1. On a clean Windows 11 machine (or CI smoke test approximating it):
   download installer → double-click → tray dot appears → panel opens in a
   native window → first-run pairing token minted.
2. The phone app pairs with the Windows Brain over LAN and gets answers
   (keyword mode with zero setup; written answers with Ollama installed).
3. Incognito from the tray behaves exactly as on macOS (verified against the
   existing incognito tests).
4. `--install-login` / `--uninstall-login` round-trip cleanly.
5. Full pytest suite green on Linux **and** the Windows CI leg green.
6. Docs updated: packaging README, TESTING.md, AI_BRAIN.md capability notes.

Work in review-sized commits (tray core, panel window, sources, packaging,
CI, docs), each with its tests.
