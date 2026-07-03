"""Run the DreamLayer Brain:  python -m dreamlayer.ai_brain.server

    python -m dreamlayer.ai_brain.server --dir ~/.dreamlayer --token rune-birch

Opens the control panel at http://<host>:<port>/ — add folders, drag files
in, pick your model, ask questions, see history. The phone pairs with the
same token.
"""
from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

from .server import Brain, make_brain_server


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DreamLayer Brain server")
    ap.add_argument("--dir", default=os.environ.get(
        "DREAMLAYER_DIR", str(Path.home() / ".dreamlayer")))
    ap.add_argument("--token", default=os.environ.get("DREAMLAYER_TOKEN", ""))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7777)
    args = ap.parse_args(argv)

    brain = Brain(args.dir)
    if args.token:
        brain.config.token = args.token
        brain.save()

    brain.start_watching()            # auto-reindex when watched folders change
    brain.start_brief_scheduler()     # deliver the morning brief at brief_hour
    brain.start_calendar_sync()       # pull macOS Calendar.app into the agenda
    server = make_brain_server(brain, host=args.host, port=args.port)
    ip = _lan_ip()
    print(f"DreamLayer Brain — control panel at http://{ip}:{args.port}/")
    print(f"  watching {len(brain.config.folders)} folder(s), "
          f"{brain.index.stats()['files']} files indexed")
    print(f"  token: {'set' if brain.config.token else '(none)'}   "
          f"model: {brain.config.model}")
    print("  Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
