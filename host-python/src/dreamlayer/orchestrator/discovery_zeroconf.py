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


class Discovery:
    available = _HAS_ZC

    def __init__(self):
        self._zc = None
        self._info = None

    def advertise(self, port: int, name: str = "DreamLayer Brain", token: str = "") -> bool:
        if not _HAS_ZC:
            return False
        try:
            self._zc = Zeroconf()
            addr = socket.inet_aton(socket.gethostbyname(socket.gethostname()))
            self._info = ServiceInfo(
                SERVICE, f"{name}.{SERVICE}", addresses=[addr], port=port,
                properties={"token": token} if token else {})
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
