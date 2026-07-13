"""Run the DreamLayer Brain:  python -m dreamlayer.ai_brain.server

    python -m dreamlayer.ai_brain.server --dir ~/.dreamlayer --token rune-birch

Opens the control panel at http://<host>:<port>/ — add folders, drag files
in, pick your model, ask questions, see history. The phone pairs with the
same token.
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
from pathlib import Path

from .server import Brain, make_brain_server

# A bind that only loopback can reach may run tokenless (local dev); anything
# else is reachable by other devices on the network and must be authenticated.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"})


def _is_loopback_host(host: str) -> bool:
    return host in _LOOPBACK_HOSTS


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
    # Loopback by DEFAULT (re-audit 2026-07): a bare `python -m …server` must
    # not expose the brain to the LAN. Reaching it from the phone is an opt-in —
    # pass --host 0.0.0.0 (the login-agent installer and the pairing flow do),
    # which then mandates a minted token below. The default was 0.0.0.0, so
    # "localhost by default" was claimed but not true; this makes it true.
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    args = ap.parse_args(argv)

    # opt-in structured logging (DL_LOG_JSON=1 → one JSON line per record);
    # a no-op formatting change otherwise, so default output is unchanged.
    from ...logging_setup import configure_logging
    configure_logging()

    brain = Brain(args.dir)
    if args.token:
        brain.config.token = args.token
        brain.save()

    # Security: never serve an unauthenticated brain on a network-reachable
    # interface. If the bind isn't loopback-only and no token was set (or
    # persisted from a previous run), mint one now and show it so the phone
    # can pair. A loopback-only bind may stay tokenless for local dev.
    minted_token = False
    if not brain.config.token and not _is_loopback_host(args.host):
        brain.config.token = secrets.token_hex(16)
        brain.save()
        minted_token = True

    brain.start_watching()            # auto-reindex when watched folders change
    brain.start_brief_scheduler()     # deliver the morning brief at brief_hour
    brain.start_calendar_sync()       # pull macOS Calendar.app into the agenda
    server = make_brain_server(brain, host=args.host, port=args.port)
    ip = _lan_ip()
    print(f"DreamLayer Brain — control panel at http://{ip}:{args.port}/")
    print(f"  watching {len(brain.config.folders)} folder(s), "
          f"{brain.index.stats()['files']} files indexed")
    if minted_token:
        print("  ⚠ network-reachable bind with no token — generated one:")
        print(f"    token: {brain.config.token}")
        print("    enter it on the phone to pair (or pass --token next time).")
    else:
        print(f"  token: {'set' if brain.config.token else '(none — loopback only)'}   "
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
