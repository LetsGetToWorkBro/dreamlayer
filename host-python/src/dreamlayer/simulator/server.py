"""simulator/server.py — serve the simulated Halo to a browser.

    python -m dreamlayer.simulator [--port 8765]

Stdlib-only (like the Brain server): a ThreadingHTTPServer around one
HaloSimulator. Local dev tool — binds 127.0.0.1 by default and carries no
token; it simulates *a* Halo, it holds none of your data.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import HaloSimulator
from .page import PAGE


def make_simulator_server(sim: HaloSimulator | None = None,
                          host: str = "127.0.0.1",
                          port: int = 8765) -> ThreadingHTTPServer:
    sim = sim or HaloSimulator()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console for the transcript
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n)) or {}
            except Exception:
                return {}

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/sim/frame.png":
                self._send(200, sim.frame_png(), "image/png")
            elif path == "/sim/state":
                self._json(200, sim.state())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            b = self._body()
            if path == "/sim/voice":
                self._json(200, sim.voice(b.get("text", ""), b.get("look") or None))
            elif path == "/sim/glance":
                self._json(200, sim.glance(b.get("look") or None))
            elif path == "/sim/gesture":
                self._json(200, sim.gesture(str(b.get("name", "single"))))
            elif path == "/sim/veil":
                self._json(200, sim.veil(bool(b.get("on"))))
            else:
                self._json(404, {"error": "not found"})

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.simulator = sim  # reachable for tests
    return srv


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="DreamLayer Halo simulator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    # Glass Desk — the zero-hardware devkit: watch a plugin dir and re-render its
    # card through the real device renderer on every save.
    ap.add_argument("--watch", metavar="PLUGIN_DIR",
                    help="Glass Desk: live-render a plugin's card on every save")
    ap.add_argument("--out", help="Glass Desk output PNG (default: <dir>/.glass/glass.png)")
    ap.add_argument("--interval", type=float, default=1.0, help="Glass Desk poll seconds")
    ap.add_argument("--once", action="store_true", help="Glass Desk: render one frame and exit")
    args = ap.parse_args(argv)
    if args.watch:
        from .glass_desk import watch
        out = watch(args.watch, out_path=args.out, interval=args.interval,
                    once=args.once)
        if args.once:
            print(f"◐ Glass Desk rendered {out}")
        return
    srv = make_simulator_server(host=args.host, port=args.port)
    print(f"\n  ◐ DreamLayer Halo Simulator\n"
          f"    http://{args.host}:{args.port}\n\n"
          f"  Talk to Juno. Set a timer. Introduce someone. Drop the veil.\n"
          f"  Every pixel is the real stack — only the hardware is simulated.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
