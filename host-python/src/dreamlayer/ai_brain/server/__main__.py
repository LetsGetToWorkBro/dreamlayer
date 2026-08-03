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
    # Opt-in https on a sibling port (default: port+1). Phone BROWSERS only
    # open cameras on a secure context, so the Live Lens needs this to see;
    # everything else works over plain http exactly as before. The cert is
    # self-signed, minted once into <dir>/tls/ (needs the `cryptography`
    # package; absent → a clear message and http-only, never a crash).
    # https is served AUTOMATICALLY on a sibling port whenever the bind is
    # network-reachable (a phone can only reach it there, and its browser opens
    # the Live Lens camera only on a secure context). --tls forces it even on a
    # loopback bind; --no-tls turns it off. Absent cryptography → http only.
    ap.add_argument("--tls", action="store_true",
                    help="force https on a loopback bind too (auto on for LAN binds)")
    ap.add_argument("--no-tls", action="store_true",
                    help="never start the https Live Lens listener")
    ap.add_argument("--tls-port", type=int, default=0,
                    help="https port (default: --port + 1)")
    # A live status panel in the terminal instead of one static block at
    # startup. OFF by default and deliberately so: a bare launch must print
    # exactly what it always has (the address, the folder count, the token
    # line), which is what the installer, the docs and the launch tests all
    # read. Needs `rich` (extras group `infra`); without it the panel degrades
    # to a plain status line on the same interval rather than failing.
    ap.add_argument("--dashboard", action="store_true",
                    help="live status panel in the terminal (needs the `infra` pack)")
    args = ap.parse_args(argv)

    # opt-in structured logging (DL_LOG_JSON=1 → one JSON line per record);
    # a no-op formatting change otherwise, so default output is unchanged.
    from ...logging_setup import configure_logging
    configure_logging()

    # Put the pack sidecar (<dir>/site-packages) on sys.path so any packs a
    # bundled app one-click-installed there are importable this run.
    try:
        from ...capabilities import enable_pack_site
        enable_pack_site(args.dir)
    except Exception:                              # never block startup on this
        pass

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
    brain.start_source_sync()         # fold local memory sources in on a poll
    brain.start_retention_scheduler()  # age memory out (hot/warm) while we run
    brain.start_ear()                 # resume the always-on ear if opted in (no-op otherwise)

    # Start the sibling https listener the Live Lens camera needs. AUTO on for a
    # network-reachable (non-loopback) bind — a phone can only reach the Brain
    # there, and its browser opens the camera only on a secure context — so the
    # Live Lens "just works" without the wearer knowing to pass a flag. --tls
    # forces it on a loopback bind too; --no-tls turns it off. Degrades to
    # http-only (never crashes) when cryptography is absent. The http server is
    # told the https port so the panel's Live Lens link advertises the secure URL.
    tls_server = None
    tls_port = 0
    want_tls = (args.tls or not _is_loopback_host(args.host)) and not args.no_tls
    if want_tls:
        from .tls import start_tls_sibling
        tls_server, tls_port = start_tls_sibling(
            brain, args.host, args.dir, args.port, args.tls_port)
        if tls_server is None:
            print("  ⚠ https (Live Lens camera) needs the `cryptography` package "
                  "(pip install 'dreamlayer[privacy]') — serving http only.")

    # the tls_port kwarg rides only when --tls actually started a listener, so
    # the bare-launch call shape stays exactly as it always was (pinned by
    # test_brain_auth_posture's spy).
    if tls_port:
        server = make_brain_server(brain, host=args.host, port=args.port,
                                   tls_port=tls_port)
    else:
        server = make_brain_server(brain, host=args.host, port=args.port)
    try:                                  # the SAME address the panel QR advertises
        from .server import lan_ip
        ip = lan_ip()
    except Exception:
        ip = _lan_ip()
    print(f"DreamLayer Brain — control panel at http://{ip}:{args.port}/")
    if tls_server is not None:
        print(f"  Live Lens (camera) — https://{ip}:{tls_port}/dreamlayer/live"
              "  (panel → Connections → Live Lens for the QR)")
    print(f"  watching {len(brain.config.folders)} folder(s), "
          f"{brain.index.stats()['files']} files indexed")
    # Say where we are, so nothing on the LAN has to be told an IP address by
    # hand. Only on a network-reachable bind: a loopback Brain has nothing to
    # announce, and advertising one would publish a 127.0.0.1 that resolves back
    # to whoever READ it — a phone would "find" a Brain and dial itself.
    #
    # The TXT record carries presence, path and the https port. Never the token:
    # a zeroconf record is unauthenticated multicast that every device on the
    # LAN reads in the clear, so the secret keeps riding the pairing channel
    # (audit 2026-07-15) and `discovery_zeroconf._public_only` enforces it at
    # the boundary rather than trusting this call site.
    if not _is_loopback_host(args.host):
        from ...orchestrator.discovery_zeroconf import Discovery
        from .discovery_live import beacon
        if beacon(brain).advertise(args.port, tls_port=tls_port or None):
            print("  announcing on this network (mDNS) — "
                  "no IP address to type in")
        elif not Discovery.available:
            print("  ⓘ automatic discovery wants the `zeroconf` package "
                  "(pip install 'dreamlayer[infra]') — the pairing QR still "
                  "works.")
    if minted_token:
        print("  ⚠ network-reachable bind with no token — generated one:")
        print(f"    token: {brain.config.token}")
        print("    enter it on the phone to pair (or pass --token next time).")
    else:
        print(f"  token: {'set' if brain.config.token else '(none — loopback only)'}   "
              f"model: {brain.config.model}")
    print("  Ctrl-C to stop.")
    if args.dashboard:
        from ..dashboard_rich import Dashboard, start_dashboard
        if not Dashboard.available:
            print("  ⚠ --dashboard wants the `rich` package "
                  "(pip install 'dreamlayer[infra]') — plain status lines instead.")
        dash = start_dashboard(brain, port=args.port,
                               **({"https": tls_port} if tls_port else {}))
        # Proof, not configuration. `rich` being importable is not evidence the
        # panel draws — a console with no terminal to write to falls through to
        # the plain line with `available` still True. So the capability is
        # promoted only once a table has genuinely been drawn, and the check
        # runs after the first tick rather than at start-up.
        if dash is not None:
            import threading as _th

            def _promote():
                import os as _os
                if dash.rich_renders > 0:
                    _os.environ["DL_WIRED_DASHBOARD"] = "1"
            _th.Timer(2.0, _promote).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        # Withdraw the service BEFORE the socket closes. A beacon left
        # registered after the port is gone advertises a Brain that refuses
        # connections, which is worse than never having advertised — the phone
        # finds it, dials it, and fails.
        try:
            from .discovery_live import beacon
            beacon(brain).stop()
        except Exception:                          # noqa: BLE001
            pass
        server.server_close()
        if tls_server is not None:
            tls_server.shutdown()
            tls_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
