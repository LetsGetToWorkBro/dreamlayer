"""ai_brain/menubar.py — the Brain as a macOS menu-bar appliance.

Turns the control-panel-in-a-tab into an always-on status item: a dot that
shows health at a glance, one-click Incognito, "Sync now", and "Open panel".
Plus a LaunchAgent so the Brain starts at login.

The GUI needs `rumps` (macOS only) and a running Brain server; both are loaded
lazily so this module imports anywhere. The pure parts — the status summary and
the LaunchAgent plist — are unit-tested; `python -m dreamlayer.ai_brain.menubar
--install-login` writes the plist, and with no flags it runs the menu bar.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
import urllib.request
from pathlib import Path

DEFAULT_PORT = 7777
AGENT_LABEL = "vision.dreamlayer.brain"

# Opt-in "Check for updates" (CLICK ONLY — never polled in the background). The
# releases live in a dedicated public repo; a click compares the running
# version to the latest published tag. The network fetch is an injectable seam
# so tests run fully offline (see check_for_update).
RELEASES_REPO = "LetsGetToWorkBro/dreamlayer-releases"
RELEASES_API = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"


# ---------------------------------------------------------------------------
# Pure core (unit-tested)
# ---------------------------------------------------------------------------

def status_summary(state: dict | None) -> dict:
    """Turn a /dreamlayer/status payload into a menu-bar view:
    {icon, title, lines}. Icon is a traffic-light emoji for the title item."""
    if not state or state.get("error"):
        return {"icon": "⚪", "title": "DreamLayer — offline",
                "lines": ["Brain not reachable"]}
    if state.get("incognito"):
        icon = "\U0001F576"                     # sunglasses — private
        head = "Incognito"
    elif state.get("cloud") and not state.get("cloud_ready"):
        icon = "\U0001F7E1"                     # yellow — cloud on but unconfigured
        head = "Cloud not configured"
    else:
        icon = "\U0001F7E2"                     # green — healthy
        head = "Online"
    files = (state.get("stats") or {}).get("files", 0)
    model = state.get("model", "keyword")
    lines = [f"Status: {head}",
             f"Model: {model}",
             f"Cloud: {'on' if state.get('cloud') else 'off'}",
             f"Indexed: {files} file(s)"]
    if state.get("phone_ago") is not None and state["phone_ago"] < 120:
        lines.append("Phone: connected")
    return {"icon": icon, "title": f"DreamLayer — {head}", "lines": lines}


def current_version() -> str:
    """The running app version — ``dreamlayer.__version__`` (falls back to
    ``0.0.0`` if the package metadata is somehow unavailable)."""
    try:
        from dreamlayer import __version__
        return str(__version__)
    except Exception:
        return "0.0.0"


def _parse_version(tag: str):
    """Parse a ``vX.Y.Z[-pre]`` tag into a comparable key, or ``None`` if it
    isn't clean semver.

    The key is ``(major, minor, patch, is_release, pre_key)`` so a pre-release
    (``1.2.3-rc1``) orders strictly BELOW its release (``1.2.3``) — an rc user is
    then offered the stable release instead of being told "up to date". Non-semver
    tags (``stable``, ``nightly``) and versions with non-numeric cores return
    ``None`` so the caller never claims "up to date" against a tag it cannot
    actually compare (the old ``_version_tuple`` truncated ``3-rc1``→``3`` and
    mapped ``stable``→``(0,)``, both of which masked a real newer release; audit
    2026-07-17)."""
    s = (tag or "").strip().lstrip("vV")
    if not s:
        return None
    s = s.split("+", 1)[0]                 # drop build metadata (ignored)
    core, _, pre = s.partition("-")
    parts = core.split(".")
    if not (1 <= len(parts) <= 3) or not all(p.isdigit() for p in parts):
        return None
    nums = tuple(int(p) for p in parts) + (0,) * (3 - len(parts))
    if not pre:
        return (nums, 1, ())               # a release sorts ABOVE any pre-release
    # numeric identifiers sort below alphanumeric ones (semver precedence)
    pre_key = tuple((0, int(idn)) if idn.isdigit() else (1, idn)
                    for idn in pre.split("."))
    return (nums, 0, pre_key)


def _default_update_fetch(url: str, timeout: float) -> bytes:
    """The real GitHub fetch, routed through the hardened egress primitives
    (no-redirect opener + capped read) with a short timeout. Swapped out in
    tests via ``check_for_update(fetch_fn=...)`` so nothing hits the network."""
    from dreamlayer.plugins._egress import no_redirect_opener, read_capped
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "DreamLayer"})
    with no_redirect_opener().open(req, timeout=timeout) as r:
        # The releases/latest JSON (assets list + release body) routinely exceeds
        # the shared 512 KiB egress default, which would surface as a false
        # "couldn't check for updates". Cap generously at 4 MiB (audit 2026-07-17).
        return read_capped(r, 4 * 1024 * 1024)


def check_for_update(current: str | None = None, fetch_fn=None,
                     timeout: float = 6.0) -> dict:
    """Compare the running version to the latest GitHub release. CLICK-ONLY —
    never called in the background. ``fetch_fn(url, timeout) -> bytes`` is an
    injectable seam (defaults to the real GitHub fetch) so tests run fully
    offline. Never raises: any network/parse error degrades to a
    'couldn't check' result. Returns ``{status, message, current, latest, url}``
    with ``status`` one of ``'update' | 'current' | 'error'``."""
    cur = current or current_version()
    fetch = fetch_fn or _default_update_fetch
    try:
        raw = fetch(RELEASES_API, timeout)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        latest = str(data.get("tag_name") or data.get("name") or "").strip()
        url = str(data.get("html_url") or RELEASES_PAGE)
    except Exception:
        return {"status": "error", "message": "Couldn't check for updates",
                "current": cur, "latest": None, "url": RELEASES_PAGE}
    if not latest:
        return {"status": "error", "message": "Couldn't check for updates",
                "current": cur, "latest": None, "url": RELEASES_PAGE}
    lv, cv = _parse_version(latest), _parse_version(cur)
    if lv is not None and cv is not None:
        if lv > cv:
            return {"status": "update", "message": f"Update available: {latest}",
                    "current": cur, "latest": latest, "url": url}
        return {"status": "current", "message": "You're up to date",
                "current": cur, "latest": latest, "url": url}
    # The tags aren't cleanly comparable semver (a pre-release/non-semver latest
    # like "stable"/"nightly", or a running version we can't parse). NEVER claim
    # "up to date" against a tag we can't compare — that hid a real newer release.
    # If the strings are identical it's genuinely the same build; otherwise
    # surface the release and let the user decide (audit 2026-07-17).
    if latest.strip().lstrip("vV") == (cur or "").strip().lstrip("vV"):
        return {"status": "current", "message": "You're up to date",
                "current": cur, "latest": latest, "url": url}
    return {"status": "update",
            "message": f"A release is available: {latest} — open to check",
            "current": cur, "latest": latest, "url": url}


def launch_agent_plist(program_args: list[str], label: str = AGENT_LABEL,
                       working_dir: str | None = None,
                       env: dict | None = None,
                       stdout_path: str | None = None,
                       stderr_path: str | None = None,
                       throttle_interval: int | None = None) -> str:
    """A launchd LaunchAgent plist (XML) that runs `program_args` at login and
    keeps it alive. Pure — returns the XML string.

    ``stdout_path``/``stderr_path`` add StandardOutPath/StandardErrorPath so a
    login-time crash leaves a trail instead of vanishing; ``throttle_interval``
    adds ThrottleInterval so a boot-failing agent doesn't respawn on launchd's
    10s KeepAlive floor forever."""
    def arr(items):
        return "".join(f"    <string>{_xml(a)}</string>\n" for a in items)
    envblock = ""
    if env:
        rows = "".join(
            f"    <key>{_xml(k)}</key><string>{_xml(v)}</string>\n"
            for k, v in env.items())
        envblock = f"  <key>EnvironmentVariables</key>\n  <dict>\n{rows}  </dict>\n"
    wd = (f"  <key>WorkingDirectory</key>\n  <string>{_xml(working_dir)}</string>\n"
          if working_dir else "")

    def _pathkey(key, val):
        return (f"  <key>{key}</key>\n  <string>{_xml(val)}</string>\n"
                if val else "")
    logs = (_pathkey("StandardOutPath", stdout_path)
            + _pathkey("StandardErrorPath", stderr_path))
    throttle = (f"  <key>ThrottleInterval</key>\n"
                f"  <integer>{int(throttle_interval)}</integer>\n"
                if throttle_interval is not None else "")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'  <key>Label</key>\n  <string>{_xml(label)}</string>\n'
        f'  <key>ProgramArguments</key>\n  <array>\n{arr(program_args)}  </array>\n'
        f'{envblock}{wd}{logs}{throttle}'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        '  <key>KeepAlive</key>\n  <true/>\n'
        '</dict>\n</plist>\n'
    )


def _xml(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def agent_path(label: str = AGENT_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _app_executable() -> str:
    """The macOS .app launcher that runs app_main (server + menu bar in one
    process). Inside a py2app bundle ``sys.executable`` is
    ``.../Contents/MacOS/python`` — the launcher that actually boots app_main is
    ``.../Contents/MacOS/DreamLayer``, so prefer it when present."""
    exe = Path(sys.executable)
    launcher = exe.parent / "DreamLayer"
    if launcher != exe and launcher.exists():
        return str(launcher)
    return sys.executable


def launch_agent_args(directory: str | None = None, port: int = DEFAULT_PORT,
                      executable: str | None = None,
                      frozen: bool | None = None) -> list[str]:
    """ProgramArguments for the login LaunchAgent: the MENU-BAR APP the .app
    runs (server + menu bar in ONE process), NOT the headless
    ``-m dreamlayer.ai_brain.server`` it used to run. The old plist gave login
    autostart a server with no UI, while the .app gave UI with no login
    registration — the two didn't compose. Now login autostart launches the
    full app (audit 2026-07-17). Frozen (.app): the bundle launcher. Source: the
    menubar module entry. Pure; unit-tested.

    No ``--host`` on the command line: the appliance binds 0.0.0.0 internally
    (app_main._serve), so start-at-login stays the LAN-reachable pairing target
    without leaking that intent onto argv."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        args = [executable or _app_executable()]
    else:
        args = [executable or sys.executable, "-m", "dreamlayer.ai_brain.menubar"]
    if directory:
        args += ["--dir", directory]
    if port != DEFAULT_PORT:
        args += ["--port", str(port)]
    return args


def install_launch_agent(directory: str | None = None, token: str = "",
                         port: int = DEFAULT_PORT) -> Path:
    """Write (and return) a LaunchAgent plist that starts the full app at login.

    Runs the MENU-BAR APP the .app runs (see launch_agent_args), so login
    autostart gives the same server + menu bar the double-click app does — the
    old plist ran the headless `-m …server`, which had no UI. The appliance
    binds 0.0.0.0 internally, so it stays the LAN-reachable pairing target.

    The pairing token is NEVER put in the plist ProgramArguments. The plist under
    ~/Library/LaunchAgents is readable, and argv is visible to any `ps`, so a
    `--token <secret>` there leaked the pairing secret exactly like the Windows
    HKCU Run value did. Instead the token is persisted to brain_config.json (the
    launched app reads it from disk via BrainConfig.load — the same path
    run_menubar and server __main__ already use), and the plist is pinned to that
    --dir so login-time and install-time agree on where the token lives
    (refute 2026-07-17; this is the macOS half of the Windows tray fix)."""
    if token:
        from .server.store import BrainConfig
        cfg_dir = directory or os.environ.get(
            "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
        cfg = BrainConfig.load(cfg_dir)
        if cfg.token != token:
            cfg.token = token
            cfg.save(cfg_dir)
        directory = cfg_dir   # pin the plist --dir to where the token lives
    # NB: no `--token` — the launched app reads it from brain_config.json.
    args = launch_agent_args(directory, port=port)
    # Point the agent's stdout/stderr at the same <state>/brain.log the windowed
    # process writes (logging_setup), and add a ThrottleInterval so a boot-failing
    # agent doesn't respawn on launchd's 10s KeepAlive floor forever.
    state = directory or os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    log_path = str(Path(state) / "brain.log")
    p = agent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(launch_agent_plist(
        args, working_dir=directory or str(Path.home()),
        stdout_path=log_path, stderr_path=log_path, throttle_interval=30))
    return p


def uninstall_launch_agent(label: str = AGENT_LABEL) -> bool:
    """Remove the login LaunchAgent plist (best-effort ``launchctl unload`` on
    macOS first). Returns True if a plist was removed, False if none existed —
    the macOS mirror of the Windows tray's ``--uninstall-login`` (until now only
    Windows had an uninstall path)."""
    p = agent_path(label)
    if not p.exists():
        return False
    if sys.platform == "darwin":
        try:
            import subprocess
            subprocess.run(["launchctl", "unload", str(p)],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    p.unlink()
    return True


# ---------------------------------------------------------------------------
# Live status fetch (used by the GUI)
# ---------------------------------------------------------------------------

def fetch_status(port: int = DEFAULT_PORT, token: str = "") -> dict | None:
    url = f"http://127.0.0.1:{port}/dreamlayer/status"
    headers = {"X-DreamLayer-Token": token} if token else {}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Brain server (for the SOURCE login autostart — see run_menubar(serve=...))
# ---------------------------------------------------------------------------

def _serve_brain(directory: str | None, port: int,
                 status: dict | None = None) -> None:
    """Start the Brain HTTP server and serve forever — the daemon-thread target
    for the SOURCE login autostart (``python -m dreamlayer.ai_brain.menubar``).

    Mirrors ``packaging/app_main._serve`` (the frozen .app's server start): bind
    0.0.0.0 so the paired phone can reach it, mint a 128-bit pairing token on
    first run, and record a bind failure in ``status`` instead of dying silently
    on the daemon thread. WITHOUT this the source LaunchAgent brought up a menu
    bar against a server that never started — a permanently grey/offline dot,
    nothing bound on 0.0.0.0, and no pairing target (regression, audit
    2026-07-17). The frozen path is unaffected: app_main starts the server and
    calls ``run_menubar(serve=False)``."""
    from .server.server import Brain, make_brain_server
    cfg_dir = directory or os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    brain = Brain(cfg_dir)
    if not brain.config.token:                     # first run — mint a pairing token
        brain.config.token = secrets.token_hex(16)
        brain.save()
    brain.start_watching()
    brain.start_brief_scheduler()
    brain.start_calendar_sync()
    try:
        server = make_brain_server(brain, host="0.0.0.0", port=port)
    except Exception as exc:                        # bind failed (port in use, …)
        logging.getLogger("dreamlayer.appliance").error(
            "Brain server failed to start on port %s: %s", port, exc)
        if status is not None:
            status["error"] = exc
        return
    if status is not None:
        status["bound"] = True
    server.serve_forever()


def serve_brain_in_background(directory: str | None, port: int) -> dict:
    """Spawn :func:`_serve_brain` on a background daemon thread and return the
    status dict the caller can poll for ``bound``/``error``. Used by the source
    login autostart so the menu bar has a live 0.0.0.0 Brain server to talk to."""
    status: dict = {}
    threading.Thread(target=_serve_brain, args=(directory, port, status),
                     daemon=True).start()
    return status


# ---------------------------------------------------------------------------
# The menu-bar app (rumps; macOS only)
# ---------------------------------------------------------------------------

def run_menubar(directory: str | None = None, port: int = DEFAULT_PORT,
                serve: bool = False) -> int:
    try:
        import rumps
    except Exception:
        print("The menu-bar app needs rumps (macOS):  pip install rumps")
        return 1
    from .server.store import BrainConfig
    cfg_dir = directory or os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    if serve:
        # SOURCE login autostart (python -m dreamlayer.ai_brain.menubar): bring up
        # the Brain server in THIS process too, so the menu bar has a live
        # 0.0.0.0 server + pairing token to talk to. The frozen .app already
        # starts its server in app_main and calls run_menubar(serve=False), so
        # this never double-serves there (audit 2026-07-17).
        serve_brain_in_background(cfg_dir, port)
    auth = {"token": BrainConfig.load(cfg_dir).token}

    def _token() -> str:
        # Re-read from config if the first read was empty. On a slow first run
        # the server mints/persists the token just after the UI started, and a
        # cached empty token would leave the dot permanently grey (authorize
        # needs the exact token even from loopback).
        if not auth["token"]:
            auth["token"] = BrainConfig.load(cfg_dir).token
        return auth["token"]

    class App(rumps.App):
        def __init__(self):
            super().__init__("⚪", quit_button="Quit DreamLayer")
            self.menu = ["Open panel", "Sync now", "Incognito", None,
                         "Check for Updates", None, "Status"]
            self.refresh(None)
            rumps.Timer(self.refresh, 15).start()

        def _api(self, path, method="GET", body=b"{}"):
            url = f"http://127.0.0.1:{port}{path}"
            headers = {"X-DreamLayer-Token": _token(),
                       "Content-Type": "application/json"}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers=headers,
                                         data=(body if method == "POST" else None),
                                         method=method)
            with opener.open(req, timeout=6) as r:
                return json.loads(r.read().decode("utf-8"))

        def refresh(self, _):
            st = fetch_status(port, _token())       # fetch ONCE per tick (was twice)
            s = status_summary(st)
            self.title = s["icon"]
            # Show every status line — Status/Model/Cloud/Indexed (+Phone) — not
            # just lines[0]; the summary already builds them all.
            self.menu["Status"].title = "   ".join(s["lines"])
            self.menu["Incognito"].state = bool((st or {}).get("incognito"))

        def _clicked_open_panel(self):
            url = f"http://127.0.0.1:{port}/"
            # a real native window (WKWebView) if we can; else the browser
            try:
                from .webview_window import open_panel_window
                if open_panel_window(url, "DreamLayer"):
                    return
            except Exception:
                pass
            import webbrowser
            webbrowser.open(url)

        @rumps.clicked("Open panel")
        def open_panel(self, _):
            self._clicked_open_panel()

        @rumps.clicked("Check for Updates")
        def check_updates(self, _):
            # Click-only: the network fetch runs ONLY here, never on the timer.
            # Run it OFF the rumps main/UI thread — a slow or timing-out fetch on
            # the UI thread froze the whole menu bar for up to the fetch timeout
            # per click. A worker does the fetch and posts the result when it
            # returns (audit 2026-07-17).
            def _work():
                res = check_for_update()
                rumps.notification(
                    "DreamLayer", res["message"],
                    res.get("url") if res["status"] == "update" else "")
            threading.Thread(target=_work, daemon=True).start()

        @rumps.clicked("Sync now")
        def sync_now(self, _):
            for ep in ("/dreamlayer/calendar/sync", "/dreamlayer/contacts/sync",
                       "/dreamlayer/reminders/sync"):
                try:
                    self._api(ep, "POST")
                except Exception:
                    pass
            rumps.notification("DreamLayer", "", "Synced calendar, contacts, reminders")

        @rumps.clicked("Incognito")
        def toggle_incognito(self, sender):
            want = not sender.state
            try:
                # Only flip the network posture. lan_only already forces cloud
                # off (BrainConfig.cloud_ready), and leaving incognito restores
                # the remembered cloud_enabled preference. The menu bar isn't a
                # cloud-preference authority, so it must NOT post cloud_enabled:
                # doing so force-enabled the opt-in-off cloud on incognito-off.
                self._api("/dreamlayer/config", "POST", json.dumps(
                    {"network_mode": "lan_only" if want else "connected"}
                ).encode())
            except Exception:
                pass
            self.refresh(None)

    App().run()
    return 0


def main(argv=None) -> int:
    import argparse
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default (audit 2026-07-14: configure at every entry).
    from ..logging_setup import configure_logging
    configure_logging()
    ap = argparse.ArgumentParser(description="DreamLayer Brain menu-bar app")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--install-login", action="store_true",
                    help="write a LaunchAgent so the app starts at login")
    ap.add_argument("--uninstall-login", action="store_true",
                    help="remove the start-at-login LaunchAgent")
    ap.add_argument("--token", default="")
    args = ap.parse_args(argv)
    if args.uninstall_login:
        p = agent_path()
        removed = uninstall_launch_agent()
        print(f"Removed {p}" if removed else "No LaunchAgent to remove.")
        return 0
    if args.install_login:
        p = install_launch_agent(args.dir, args.token, args.port)
        print(f"Wrote {p}\nLoad it now with:  launchctl load {p}")
        return 0
    # No flags → this IS the login-autostart entry the LaunchAgent runs, so it
    # must bring up the Brain server (serve=True), not just a menu bar pointed at
    # a server that never starts (audit 2026-07-17).
    return run_menubar(args.dir, args.port, serve=True)


if __name__ == "__main__":
    raise SystemExit(main())
