"""ai_brain/tray_windows.py — the Brain as a Windows system-tray appliance.

The Windows twin of menubar.py: the same always-on status item — a dot that
shows health at a glance, one-click Incognito, "Sync now", and "Open panel" —
with the same wording, fed from ``/dreamlayer/status`` through the same pure
``menubar.status_summary`` (reused, not duplicated). Start-at-login is an
HKCU ``...\\CurrentVersion\\Run`` registry value, the LaunchAgent's Windows
equivalent: reversible (``--uninstall-login`` deletes it), per-user, and no
COM shortcut plumbing.

The GUI needs ``pystray`` + Pillow (chosen because both are tiny pure wheels,
Pillow is already a base dependency, and pystray drives the real Win32
notify-icon API — no toolkit, no build step) and a running Brain server; both
are loaded lazily so this module imports (and no-ops) on macOS/Linux/CI,
exactly like the macOS modules do. The pure parts — the status→dot-color map
and the Run-entry command — are unit-tested; ``python -m
dreamlayer.ai_brain.tray_windows --install-login`` writes the Run entry, and
with no flags it runs the tray.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

from .menubar import DEFAULT_PORT, fetch_status, status_summary

# the Run-key value name — the reversible unit --uninstall-login deletes
RUN_VALUE = "DreamLayer"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# traffic-light dot colors, keyed by the status_summary icon (same semantics
# as the menu bar: green healthy, yellow cloud-unconfigured, shades for
# incognito, grey offline). Values are the panel's Platinum palette.
DOT_COLORS = {
    "\U0001F7E2": "#1F8A3D",     # green — healthy      (panel --success)
    "\U0001F7E1": "#E6A700",     # yellow — cloud on but unconfigured
    "\U0001F576": "#333399",     # sunglasses — incognito (panel --hi)
    "⚪": "#8A9296",             # white — offline       (panel --ghost)
}
OFFLINE_COLOR = DOT_COLORS["⚪"]


# ---------------------------------------------------------------------------
# Pure core (unit-tested)
# ---------------------------------------------------------------------------

def dot_color(summary: dict | None) -> str:
    """The tray dot's color for a status_summary() view. Unknown/absent →
    the offline grey (never a fake green)."""
    if not summary:
        return OFFLINE_COLOR
    return DOT_COLORS.get(summary.get("icon", ""), OFFLINE_COLOR)


def _quote(arg: str) -> str:
    """Quote one argument for a Windows Run-key command line. Run values are
    plain command lines, so a path with spaces must be quoted; embedded
    double quotes are escaped the way CommandLineToArgvW expects."""
    a = str(arg)
    if a and not any(c in a for c in ' \t"'):
        return a
    return '"' + a.replace('"', r'\"') + '"'


def login_command(program: str, args: list[str] | None = None) -> str:
    """The exact command line an HKCU Run entry runs at login. Pure —
    returns the string that will be written to the registry."""
    return " ".join(_quote(a) for a in [program, *(args or [])])


def build_login_entry(directory: str | None = None, token: str = "",
                      port: int = DEFAULT_PORT,
                      executable: str | None = None,
                      frozen: bool | None = None) -> str:
    """The start-at-login command for this install (pure; unit-tested).

    Bundled app (PyInstaller): the exe IS the appliance — server + tray in
    one process — so the entry is just the exe (plus --dir/--port when
    non-default). Source install: mirror the macOS LaunchAgent exactly and
    register the headless server. Binds 0.0.0.0 on purpose for the same
    reason install_launch_agent does: the login entry IS the always-on
    appliance the phone pairs with, so it must be LAN-reachable; safety
    comes from the token (a non-loopback bind with no token mints one on
    first run — server __main__).
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    exe = executable or sys.executable
    if frozen:
        args = []
        if directory:
            args += ["--dir", directory]
        if port != DEFAULT_PORT:
            args += ["--port", str(port)]
        return login_command(exe, args)
    args = ["-m", "dreamlayer.ai_brain.server",
            "--host", "0.0.0.0", "--port", str(port)]
    if directory:
        args += ["--dir", directory]
    if token:
        args += ["--token", token]
    return login_command(exe, args)


# ---------------------------------------------------------------------------
# Registry install/uninstall (Windows only; the construction above is pure)
# ---------------------------------------------------------------------------

def install_login_entry(directory: str | None = None, token: str = "",
                        port: int = DEFAULT_PORT,
                        value_name: str = RUN_VALUE) -> str:
    """Write the HKCU Run entry so the Brain starts at login. Returns the
    command written. Raises OSError off-Windows (there is no registry)."""
    if sys.platform != "win32":
        raise OSError("the HKCU Run registry exists only on Windows")
    import winreg
    cmd = build_login_entry(directory, token, port)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, cmd)
    return cmd


def uninstall_login_entry(value_name: str = RUN_VALUE) -> bool:
    """Delete the HKCU Run entry. True if one was removed, False if there
    was none. Raises OSError off-Windows."""
    if sys.platform != "win32":
        raise OSError("the HKCU Run registry exists only on Windows")
    import winreg
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                              winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
            return True
    except FileNotFoundError:
        return False


def read_login_entry(value_name: str = RUN_VALUE) -> str | None:
    """The currently-installed Run command, or None. Raises OSError off-Windows."""
    if sys.platform != "win32":
        raise OSError("the HKCU Run registry exists only on Windows")
    import winreg
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                              winreg.KEY_QUERY_VALUE) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return str(val)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# The tray app (pystray; Windows only)
# ---------------------------------------------------------------------------

def _dot_image(color: str, size: int = 64):
    """A filled status dot as a PIL image (transparent square, centered disc)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 8
    d.ellipse((pad, pad, size - pad, size - pad), fill=color)
    return img


def run_tray(directory: str | None = None, port: int = DEFAULT_PORT) -> int:
    try:
        import pystray
        from pystray import Menu, MenuItem
    except Exception:
        print("The tray app needs pystray (Windows):  pip install pystray")
        return 1
    import os
    import webbrowser
    from .server.store import BrainConfig
    cfg_dir = directory or os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    token = BrainConfig.load(cfg_dir).token

    state: dict = {"summary": status_summary(None), "incognito": False}

    def _api(path, method="GET", body=b"{}"):
        url = f"http://127.0.0.1:{port}{path}"
        headers = {"X-DreamLayer-Token": token, "Content-Type": "application/json"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers=headers,
                                     data=(body if method == "POST" else None),
                                     method=method)
        with opener.open(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))

    def refresh(icon):
        st = fetch_status(port, token)
        state["summary"] = status_summary(st)
        state["incognito"] = bool((st or {}).get("incognito"))
        icon.icon = _dot_image(dot_color(state["summary"]))
        icon.title = state["summary"]["title"]
        icon.update_menu()

    def open_panel(icon, item):
        url = f"http://127.0.0.1:{port}/"
        # a real native window (WebView2) if we can; else the browser
        try:
            from .webview_window_windows import open_panel_window
            if open_panel_window(url, "DreamLayer"):
                return
        except Exception:
            pass
        webbrowser.open(url)

    def sync_now(icon, item):
        for ep in ("/dreamlayer/calendar/sync", "/dreamlayer/contacts/sync",
                   "/dreamlayer/reminders/sync"):
            try:
                _api(ep, "POST")
            except Exception:
                pass
        try:
            icon.notify("Synced calendar, contacts, reminders", "DreamLayer")
        except Exception:
            pass
        refresh(icon)

    def toggle_incognito(icon, item):
        want = not state["incognito"]
        try:
            # Only flip the network posture. lan_only already forces cloud
            # off (BrainConfig.cloud_ready), and leaving incognito restores
            # the remembered cloud_enabled preference. The tray isn't a
            # cloud-preference authority, so it must NOT post cloud_enabled
            # (same contract as the macOS menu bar).
            _api("/dreamlayer/config", "POST", json.dumps(
                {"network_mode": "lan_only" if want else "connected"}
            ).encode())
        except Exception:
            pass
        refresh(icon)

    def quit_app(icon, item):
        icon.stop()

    menu = Menu(
        MenuItem("Open panel", open_panel, default=True),
        MenuItem("Sync now", sync_now),
        MenuItem("Incognito", toggle_incognito,
                 checked=lambda item: state["incognito"]),
        Menu.SEPARATOR,
        MenuItem(lambda item: state["summary"]["lines"][0], None, enabled=False),
        Menu.SEPARATOR,
        MenuItem("Quit DreamLayer", quit_app),
    )
    icon = pystray.Icon("DreamLayer", _dot_image(OFFLINE_COLOR),
                        "DreamLayer", menu)

    def setup(icon):
        icon.visible = True
        refresh(icon)

        def loop():
            import time
            while icon.visible:
                time.sleep(15)
                try:
                    refresh(icon)
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    icon.run(setup=setup)
    return 0


def main(argv=None) -> int:
    import argparse
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default — same posture as menubar.main.
    from ..logging_setup import configure_logging
    configure_logging()
    ap = argparse.ArgumentParser(description="DreamLayer Brain tray app (Windows)")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--install-login", action="store_true",
                    help="write an HKCU Run entry so the Brain starts at login")
    ap.add_argument("--uninstall-login", action="store_true",
                    help="remove the start-at-login Run entry")
    ap.add_argument("--token", default="")
    args = ap.parse_args(argv)
    if args.install_login or args.uninstall_login:
        if sys.platform != "win32":
            print("start-at-login via the registry is Windows-only "
                  "(on macOS use:  python -m dreamlayer.ai_brain.menubar --install-login)")
            return 1
        if args.uninstall_login:
            removed = uninstall_login_entry()
            print("Removed the start-at-login entry." if removed
                  else "No start-at-login entry to remove.")
            return 0
        cmd = install_login_entry(args.dir, args.token, args.port)
        print(f"Wrote HKCU\\{RUN_KEY}\\{RUN_VALUE}\n  {cmd}")
        return 0
    return run_tray(args.dir, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
