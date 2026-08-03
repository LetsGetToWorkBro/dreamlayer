"""mDNS discovery (python-zeroconf) — the Mac companion advertises
`_dreamlayer._tcp.local`, the phone finds it automatically (no IP typing).

ADD-alongside: new module. Lazy-imports zeroconf (extras group `infra`); when
absent, advertise()/discover() no-op (returns False / []) so pairing falls back
to the existing manual/QR flow unchanged.
"""
from __future__ import annotations
import logging
import socket

log = logging.getLogger("dreamlayer.discovery")

try:
    from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceListener  # type: ignore
    _HAS_ZC = True
except ImportError:
    _HAS_ZC = False

SERVICE = "_dreamlayer._tcp.local."

#: Substrings that make a TXT key a secret. Matched on the LOWERCASED key so
#: casing cannot slip one through. Deliberately broad — the cost of dropping an
#: innocent key called "authors" is a missing hint in a discovery record; the
#: cost of publishing one called "auth" is the pairing token on open multicast.
_SECRET_HINTS = ("token", "secret", "key", "pass", "auth", "cred", "sig")


def _public_only(properties) -> dict:
    """The TXT record, with anything that looks like a credential removed.

    A whitelist would be safer still, but it would also mean this module has to
    know every property a future caller legitimately wants to publish. This is
    the shape that keeps the guarantee — *no secret leaves here* — without
    making the module the gatekeeper of what a discovery hint may say.
    """
    out = {}
    for k, v in (properties or {}).items():
        key = str(k)
        if any(h in key.lower() for h in _SECRET_HINTS):
            # The KEY, never the value — this line must not reprint the secret
            # it just refused to broadcast — and the key rides `extra` rather
            # than the message string, which is the only redaction seam
            # `logging_setup.JsonLineFormatter` has. A key literally named
            # "token" interpolated into a message is what
            # `test_logging_discipline.py` exists to catch, and it is right to:
            # the scanner cannot tell a key name from a key.
            log.warning("[discovery] refusing to publish a secret-looking "
                        "TXT key", extra={"txt_key": key})
            continue
        out[key] = v
    return out


class Discovery:
    available = _HAS_ZC

    def __init__(self):
        self._zc = None
        self._info = None

    def advertise(self, port: int, name: str = "DreamLayer Brain", token: str = "",
                  addresses: "list[str] | None" = None,
                  properties: "dict | None" = None) -> bool:
        """Publish this Brain on the LAN. True once the service is registered.

        `addresses` is the caller's list of dotted-quad IPv4s, most-reachable
        first, and passing it is strongly preferred. The fallback below —
        `gethostbyname(gethostname())` — is a single guess that returns
        127.0.0.1 on a great many Linux boxes and picks an arbitrary interface
        on a multi-NIC host. Advertising an address the phone cannot reach is
        the same defect as refute 2026-07-20, where a Docker/VirtualBox adapter
        floated above the real LAN and went into the pairing QR; the Brain
        solved it once already in `server.lan_ip_candidates`, and this parameter
        is how that answer gets here instead of being re-derived worse.

        `properties` becomes the TXT record and is filtered here rather than
        trusted: a zeroconf TXT is unauthenticated multicast that any device or
        passive listener on the LAN reads in the clear, so a secret in it
        defeats the pairing it is meant to protect (audit 2026-07-15). `token`
        stays in the signature for call-compatibility and is never published,
        and any property whose key looks secret is dropped with a warning —
        the caller cannot opt in, because the whole point is that this channel
        has no reader you can authenticate.
        """
        if not _HAS_ZC:
            return False
        try:
            self._zc = Zeroconf()
            addrs = [socket.inet_aton(a) for a in (addresses or []) if a]
            if not addrs:
                addrs = [socket.inet_aton(
                    socket.gethostbyname(socket.gethostname()))]
            self._info = ServiceInfo(
                SERVICE, f"{name}.{SERVICE}", addresses=addrs, port=port,
                properties=_public_only(properties))
            self._zc.register_service(self._info)
            return True
        except Exception as exc:
            log.error("[discovery] advertise failed: %s", exc)
            return False

    def stop(self) -> None:
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
            if self._zc:
                self._zc.close()
        except Exception:
            pass
        self._zc = self._info = None

    def discover(self, timeout: float = 2.0) -> list[dict]:
        """Return [{name, host, port}] found on the LAN, or [] with no dep."""
        if not _HAS_ZC:
            return []
        found: list[dict] = []

        # _L is only defined/instantiated on the _HAS_ZC path (guarded above),
        # so subclassing ServiceListener never runs when the dep is absent —
        # the module still imports cleanly there. With the dep present it makes
        # _L satisfy zeroconf's ServiceListener protocol for ServiceBrowser.
        class _L(ServiceListener):
            def add_service(self, zc, type_, name):
                try:
                    info = zc.get_service_info(type_, name)
                    if info and info.addresses:
                        found.append({
                            "name": name,
                            "host": socket.inet_ntoa(info.addresses[0]),
                            "port": info.port,
                        })
                except Exception:
                    pass

            def update_service(self, *a):
                pass

            def remove_service(self, *a):
                pass

        try:
            import time
            zc = Zeroconf()
            ServiceBrowser(zc, SERVICE, _L())
            time.sleep(timeout)
            zc.close()
        except Exception as exc:
            log.error("[discovery] browse failed: %s", exc)
        return found
