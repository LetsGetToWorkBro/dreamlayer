#!/usr/bin/env python3
"""dreamlayer_companion.py — the laptop-side agent for the Object Lens.

This is the small program you run on your laptop so that, when you look at
it through the Halo glasses, the Object Lens can show your recent files and
battery. It reads that from the OS and serves it on your local network on
the DreamLayer companion contract:

    GET  http://<this-laptop>:7777/dreamlayer/context
    header  X-DreamLayer-Token: <shared pairing token>
    200  {"recent_files": [...], "battery": 82, "hostname": "studio-mbp"}

Everything stays on your LAN — the phone (the DreamLayer hub) fetches this
directly; nothing goes to any cloud. Only your paired phone, holding the
token, can read it.

Stdlib only — no dependencies. Run:

    python3 dreamlayer_companion.py --token rune-birch

Then pair the phone with the same token. Leave it running (see README for
launch-at-login). macOS / Windows / Linux.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTEXT_PATH = "/dreamlayer/context"
TOKEN_HEADER = "X-DreamLayer-Token"

# folders whose most-recently-touched files stand in for "recent files".
# Robust and private (your own folders), and identical across OSes — no
# fragile parsing of OS jump-lists / bookmark blobs.
DEFAULT_DIRS = ["Desktop", "Documents", "Downloads"]
MAX_RECENT = 5


# ---------------------------------------------------------------------------
# Reading the laptop's own context
# ---------------------------------------------------------------------------

def recent_files(dirs=None, home=None, limit=MAX_RECENT) -> list[str]:
    """The most recently modified real files across a few of your folders."""
    home = Path(home) if home else Path.home()
    dirs = dirs or DEFAULT_DIRS
    found: list[tuple[float, str]] = []
    for d in dirs:
        base = home / d
        if not base.is_dir():
            continue
        try:
            for entry in os.scandir(base):
                if entry.is_file(follow_symlinks=False) \
                        and not entry.name.startswith("."):
                    found.append((entry.stat().st_mtime, entry.name))
        except OSError:
            continue
    found.sort(reverse=True)
    return [name for _mtime, name in found[:limit]]


def battery_percent() -> int | None:
    """Battery level as an int percent, or None if there's no battery."""
    system = platform.system()
    try:
        if system == "Linux":
            for bat in sorted(Path("/sys/class/power_supply").glob("BAT*")):
                cap = (bat / "capacity")
                if cap.exists():
                    return int(cap.read_text().strip())
        elif system == "Darwin":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                 text=True, timeout=3).stdout
            for tok in out.replace(";", " ").split():
                if tok.endswith("%"):
                    return int(tok[:-1])
        elif system == "Windows":
            out = subprocess.run(
                ["WMIC", "PATH", "Win32_Battery", "Get",
                 "EstimatedChargeRemaining"],
                capture_output=True, text=True, timeout=3).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def build_context(dirs=None, home=None) -> dict:
    """The JSON the companion serves."""
    ctx: dict = {"recent_files": recent_files(dirs=dirs, home=home),
                 "hostname": socket.gethostname()}
    batt = battery_percent()
    if batt is not None:
        ctx["battery"] = batt
    return ctx


# ---------------------------------------------------------------------------
# Serving it
# ---------------------------------------------------------------------------

def make_server(token: str, host: str, port: int,
                context_fn=build_context) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):           # stay quiet
            pass

        def do_GET(self):
            if self.path.rstrip("/") != CONTEXT_PATH:
                self.send_response(404); self.end_headers(); return
            if token and self.headers.get(TOKEN_HEADER) != token:
                self.send_response(401); self.end_headers(); return
            try:
                body = json.dumps(context_fn()).encode("utf-8")
            except Exception:
                self.send_response(500); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DreamLayer laptop companion")
    ap.add_argument("--token", default=os.environ.get("DREAMLAYER_TOKEN", ""),
                    help="pairing secret; the phone must send the same one")
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address (0.0.0.0 = reachable on your LAN)")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--insecure", action="store_true",
                    help="allow LAN binding without a token (not recommended)")
    args = ap.parse_args(argv)

    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not args.token and not loopback and not args.insecure:
        print("refusing to serve on the LAN without --token "
              "(anyone could read your files). set --token, or pass "
              "--insecure to override.", file=sys.stderr)
        return 2

    server = make_server(args.token, args.host, args.port)
    ip = _lan_ip()
    print(f"DreamLayer companion serving on "
          f"http://{ip}:{args.port}{CONTEXT_PATH}")
    print(f"  hostname: {socket.gethostname()}")
    print(f"  token:    {'set' if args.token else '(none — open)'}")
    print("  pair the phone with this token; leave this running. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        server.server_close()
    return 0


def _lan_ip() -> str:
    """Best-effort local IP the phone would use (no packets actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())
