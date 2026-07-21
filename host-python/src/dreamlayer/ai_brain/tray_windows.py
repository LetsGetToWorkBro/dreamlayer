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
from pathlib import Path

from .menubar import (DEFAULT_PORT, _authed_api, _TokenCache, check_for_update,
                      fetch_status, status_summary)

# the Run-key value name — the reversible unit --uninstall-login deletes
RUN_VALUE = "DreamLayer"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# What the Windows tray actually syncs. Contacts and Reminders are macOS-only
# (the panel marks them unavailable on Windows), so the tray must NOT claim to
# have synced them — only Calendar. The old toast said "Synced calendar,
# contacts, reminders", which was dishonest on Windows (audit 2026-07-17).
SYNC_ENDPOINTS = ("/dreamlayer/calendar/sync",)
SYNC_TOAST = "Synced calendar"

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
    non-default). Source install: register the headless server. Binds 0.0.0.0
    on purpose for the same reason install_launch_agent does: the login entry
    IS the always-on appliance the phone pairs with, so it must be
    LAN-reachable.

    The pairing token is NEVER put on this command line. An HKCU Run value is
    readable by every process running as the user (Task Manager's command
    column, ``reg query``, any ps-equivalent), so ``--token <secret>`` in the
    entry leaked the pairing secret registry-/ps-visible. Instead the launched
    server reads the token from the on-disk ``brain_config.json`` (0600-
    equivalent), exactly like the macOS launch-agent fix — so the `token`
    parameter is accepted for signature/API compatibility but deliberately not
    emitted here (install_login_entry persists it to config instead). A
    non-loopback bind with no persisted token still mints one on first run
    (server __main__), so start-at-login keeps working either way (audit
    2026-07-17).
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
    # NB: no `--token` — see the docstring. The token lives in brain_config.json.
    return login_command(exe, args)


# ---------------------------------------------------------------------------
# Registry install/uninstall (Windows only; the construction above is pure)
# ---------------------------------------------------------------------------

def install_login_entry(directory: str | None = None, token: str = "",
                        port: int = DEFAULT_PORT,
                        value_name: str = RUN_VALUE) -> str:
    """Write the HKCU Run entry so the Brain starts at login. Returns the
    command written. Raises OSError off-Windows (there is no registry).

    A supplied token is persisted to ``brain_config.json`` (the 0600-equivalent
    on-disk config the launched server reads) rather than written onto the Run
    command line, so the pairing secret never becomes registry-/ps-visible. The
    command itself carries no token (see build_login_entry)."""
    if sys.platform != "win32":
        raise OSError("the HKCU Run registry exists only on Windows")
    import os
    import winreg
    from .server.store import BrainConfig
    if token:
        # translate the old `--token <secret>` intent into config: the server
        # this entry launches reads the token from disk, not from argv.
        cfg_dir = directory or os.environ.get(
            "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
        cfg = BrainConfig.load(cfg_dir)
        if cfg.token != token:
            cfg.token = token
            cfg.save(cfg_dir)
        # Pin the login command to the SAME dir we just wrote the token to.
        # build_login_entry omits --dir when directory is None, but cfg_dir was
        # resolved from DREAMLAYER_DIR/default HERE; if that env var was set only
        # in the install shell (not a persisted user var), the login server would
        # re-resolve a DIFFERENT dir, find no token, and mint a fresh one —
        # silently dropping the operator's token and breaking the paired phone.
        # Passing the resolved dir makes install-time and login-time agree
        # (refute 2026-07-17).
        directory = cfg_dir
    cmd = build_login_entry(directory, port=port)
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

_ASSETS_DIR = Path(__file__).resolve().parent / "server" / "assets"
_MENU_SPRITE = _ASSETS_DIR / "juno_menu.png"     # mono pixel Juno, tinted live
_TRAY_SPRITE = _ASSETS_DIR / "juno_tray.png"     # full-color Juno (badge fallback)
_INK = (6, 19, 22)


def _dot_image(color: str, size: int = 64):
    """Pixel Juno tinted head-to-wing in the status color — the same treatment
    the Mac menu bar wears (the tested dot_color contract is untouched; this is
    only rendering). At tray size (~16px) a corner badge shrinks to a few
    pixels, but a whole-body tint reads at a glance — below ~24px she IS the
    light. The tint is applied here from the mono sprite so dot_color stays the
    single color authority. Fallbacks, in order: the full-color Juno wearing a
    badge dot, then the old ring-and-core mark — the art degrades, never fails."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        mono = Image.open(_MENU_SPRITE).convert("RGBA")
        c = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        px = mono.load()
        for y in range(mono.height):
            for x in range(mono.width):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                px[x, y] = tuple(round(_INK[i] + (c[i] - _INK[i]) * lum)
                                 for i in range(3)) + (a,)
        art = mono.resize((size, size), Image.NEAREST)  # 32 -> 64 stays crisp
        img.paste(art, (0, 0), art)
        return img
    except Exception:
        pass
    try:
        art = Image.open(_TRAY_SPRITE).convert("RGBA")
        art = art.resize((size, size), Image.NEAREST)   # 128 -> 64 stays crisp
        img.paste(art, (0, 0), art)
        r = size * 11 // 64                             # the site set's badge: 11px dot at 32
        x1 = y1 = size - 1
        x0, y0 = x1 - 2 * r, y1 - 2 * r
        d.ellipse((x0 - 2, y0 - 2, x1 + 2, y1 + 2), fill=_INK + (255,))
        d.ellipse((x0, y0, x1, y1), fill=color)
        g = max(2, size // 16)                          # single top-lit glint pixel
        d.rectangle((x0 + g + g // 2, y0 + g + g // 2,
                     x0 + 2 * g + g // 2, y0 + 2 * g + g // 2), fill=(255, 255, 255, 165))
        return img
    except Exception:
        pass
    pad = size // 8
    stroke = max(2, size // 6)
    # a whisper of dark halo behind the ring so it reads on light taskbars
    d.ellipse((pad - 2, pad - 2, size - pad + 2, size - pad + 2),
              outline=(10, 16, 18, 90), width=stroke + 4)
    d.ellipse((pad, pad, size - pad, size - pad), outline=color, width=stroke)
    core = size // 2 - size // 7
    d.ellipse((core, core, size - core, size - core), fill=color)
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
    auth = _TokenCache(cfg_dir, BrainConfig.load)

    def _token():
        # Re-read from config if the cache is empty. On a slow first run the
        # server mints/persists the token just after the UI started, and a cached
        # empty token would leave the dot permanently grey (authorize needs the
        # exact token even from loopback). An auth failure in _api() also clears
        # the cache, so this re-reads a ROTATED token without a restart.
        return auth.get()

    state: dict = {"summary": status_summary(None), "incognito": False}

    def _api(path, method="GET", body=b"{}"):
        # _authed_api carries the cached token and, on a 401/403, invalidates the
        # cache so the next _token() re-reads a rotated token from config.
        return _authed_api(port, auth, path, method, body)

    def refresh(icon):
        # Route the passive poll through the auth-aware fetch_status: a 401/403
        # invalidates the cache so the NEXT tick re-reads a rotated token from
        # config and the dot self-heals — no user action needed (same contract
        # as the macOS menu bar; fetch_status is the shared helper).
        st = fetch_status(port, _token(), auth=auth)
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
        # Only what Windows actually syncs — Calendar. Contacts/Reminders are
        # macOS-only, so the toast must not claim them (SYNC_ENDPOINTS/SYNC_TOAST).
        for ep in SYNC_ENDPOINTS:
            try:
                _api(ep, "POST")
            except Exception:
                pass
        try:
            icon.notify(SYNC_TOAST, "DreamLayer")
        except Exception:
            pass
        refresh(icon)

    def check_updates(icon, item):
        # Click-only: the network fetch runs ONLY here, never on the refresh
        # loop. Offline/error degrades to a "couldn't check" toast. Run it OFF
        # the message-loop thread — pystray invokes menu callbacks on the thread
        # pumping the loop, so a slow/timing-out fetch would freeze the tray for
        # up to the fetch timeout per click (same fix as the macOS menu bar;
        # audit 2026-07-17).
        def _work():
            res = check_for_update()
            if res["status"] != "update":
                try:
                    icon.notify(res["message"], "DreamLayer")
                except Exception:
                    pass
                return
            # In-app update: download → digest-verify → Authenticode gate →
            # run the installer. Today's builds aren't code-signed yet, so the
            # gate will honestly refuse and we fall back to the Releases page
            # — the moment builds are signed, the same click installs in-app.
            try:
                from .updater import perform_update
                icon.notify("Downloading update…", "DreamLayer")
                ok, msg = perform_update()
            except Exception:
                ok, msg = False, "updater unavailable"
            try:
                icon.notify(msg if ok else f"{res['message']} — {msg}",
                            "DreamLayer")
            except Exception:
                pass
            if not ok:
                try:
                    webbrowser.open(res["url"])
                except Exception:
                    pass
        threading.Thread(target=_work, daemon=True).start()

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
        MenuItem("Check for updates", check_updates),
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
