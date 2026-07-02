"""object_lens/integrations/laptop_companion.py — a reference integration.

This is the worked example of filling an Object Lens seam. A *companion
agent* runs on your laptop, reads the OS "recently opened" list and battery,
and serves them on your local network. The phone (host-python) fetches that
over the LAN and feeds it to the LaptopProvider — no cloud, offline.

The contract (deliberately tiny):

    GET  {base_url}/dreamlayer/context
    header  X-DreamLayer-Token: <paired token>
    200  {"recent_files": [str, …], "battery": int, "hostname": str}
    401  wrong/absent token

Two halves live here:

  laptop_data_source(base_url, token) -> a fetch callable
      wrap it in a PolledSource and hand it to LaptopProvider. That's the
      whole phone-side wiring.

  serve_companion(data_provider, token=…) -> a running fake companion
      a real companion is a menu-bar app; this in-process server implements
      the same contract so the round-trip is testable and demoable end to
      end (see test_object_lens_integrations.py and run_demo_object_companion).

The real macOS/Windows agent is out of scope for this repo — but anything
that speaks this three-line contract drops straight in.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

CONTEXT_PATH = "/dreamlayer/context"
TOKEN_HEADER = "X-DreamLayer-Token"


# ---------------------------------------------------------------------------
# Phone side: the fetch callable
# ---------------------------------------------------------------------------

def _urllib_get(url: str, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=headers)
    # localhost/LAN calls must ignore any configured HTTP proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def laptop_data_source(base_url: str, token: str = "",
                       http_get: Optional[Callable] = None,
                       timeout: float = 2.0) -> Callable[[], dict]:
    """Return a fetch() for the companion. Wrap it in a PolledSource.

    http_get(url, headers, timeout) -> dict is injectable for tests; the
    default uses urllib (stdlib, proxy-bypassed for the LAN).
    """
    get = http_get or _urllib_get
    url = base_url.rstrip("/") + CONTEXT_PATH
    headers = {TOKEN_HEADER: token} if token else {}

    def fetch() -> dict:
        return get(url, headers, timeout)

    return fetch


# ---------------------------------------------------------------------------
# Laptop side (reference / fake): a server that speaks the contract
# ---------------------------------------------------------------------------

class Companion:
    """A running reference companion. .url is where the phone points."""

    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread):
        self._server = server
        self._thread = thread
        host, port = server.server_address[:2]
        self.url = f"http://{host}:{port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self): return self
    def __exit__(self, *exc): self.stop()


def serve_companion(data_provider: Callable[[], dict], token: str = "",
                    host: str = "127.0.0.1", port: int = 0) -> Companion:
    """Start a reference companion serving `data_provider()` at CONTEXT_PATH.

    port=0 picks a free port; read the address from the returned Companion.url.
    """
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):        # keep the test output quiet
            pass

        def do_GET(self):
            if self.path.rstrip("/") != CONTEXT_PATH:
                self.send_response(404); self.end_headers(); return
            if token and self.headers.get(TOKEN_HEADER) != token:
                self.send_response(401); self.end_headers(); return
            try:
                body = json.dumps(data_provider() or {}).encode("utf-8")
            except Exception:
                self.send_response(500); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return Companion(server, thread)
