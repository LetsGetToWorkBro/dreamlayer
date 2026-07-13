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
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_PORT = 7777
AGENT_LABEL = "vision.dreamlayer.brain"


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


def launch_agent_plist(program_args: list[str], label: str = AGENT_LABEL,
                       working_dir: str | None = None,
                       env: dict | None = None) -> str:
    """A launchd LaunchAgent plist (XML) that runs `program_args` at login and
    keeps it alive. Pure — returns the XML string."""
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
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'  <key>Label</key>\n  <string>{_xml(label)}</string>\n'
        f'  <key>ProgramArguments</key>\n  <array>\n{arr(program_args)}  </array>\n'
        f'{envblock}{wd}'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        '  <key>KeepAlive</key>\n  <true/>\n'
        '</dict>\n</plist>\n'
    )


def _xml(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def agent_path(label: str = AGENT_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def install_launch_agent(directory: str | None = None, token: str = "",
                         port: int = DEFAULT_PORT) -> Path:
    """Write (and return) a LaunchAgent plist that starts the Brain at login."""
    args = [sys.executable, "-m", "dreamlayer.ai_brain.server", "--port", str(port)]
    if directory:
        args += ["--dir", directory]
    if token:
        args += ["--token", token]
    p = agent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(launch_agent_plist(args, working_dir=directory or str(Path.home())))
    return p


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
# The menu-bar app (rumps; macOS only)
# ---------------------------------------------------------------------------

def run_menubar(directory: str | None = None, port: int = DEFAULT_PORT) -> int:
    try:
        import rumps
    except Exception:
        print("The menu-bar app needs rumps (macOS):  pip install rumps")
        return 1
    from .server.store import BrainConfig
    cfg_dir = directory or os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    token = BrainConfig.load(cfg_dir).token

    class App(rumps.App):
        def __init__(self):
            super().__init__("⚪", quit_button="Quit DreamLayer")
            self.menu = ["Open panel", "Sync now", "Incognito", None, "Status"]
            self.refresh(None)
            rumps.Timer(self.refresh, 15).start()

        def _api(self, path, method="GET", body=b"{}"):
            url = f"http://127.0.0.1:{port}{path}"
            headers = {"X-DreamLayer-Token": token, "Content-Type": "application/json"}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers=headers,
                                         data=(body if method == "POST" else None),
                                         method=method)
            with opener.open(req, timeout=6) as r:
                return json.loads(r.read().decode("utf-8"))

        def refresh(self, _):
            s = status_summary(fetch_status(port, token))
            self.title = s["icon"]
            self.menu["Status"].title = s["lines"][0]
            self.menu["Incognito"].state = bool(
                (fetch_status(port, token) or {}).get("incognito"))

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
    ap = argparse.ArgumentParser(description="DreamLayer Brain menu-bar app")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--install-login", action="store_true",
                    help="write a LaunchAgent so the Brain starts at login")
    ap.add_argument("--token", default="")
    args = ap.parse_args(argv)
    if args.install_login:
        p = install_launch_agent(args.dir, args.token, args.port)
        print(f"Wrote {p}\nLoad it now with:  launchctl load {p}")
        return 0
    return run_menubar(args.dir, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
