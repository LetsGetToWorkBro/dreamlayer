"""tls.py — an opt-in self-signed certificate so phone BROWSERS can reach the
Brain securely.

Why this exists: the Live Lens runs in a mobile browser, and browsers only
open cameras on a secure context — https, never http://<lan-ip>. The native
phone app can speak LAN cleartext (the #439 ATS work); a browser cannot. So
`--tls` mints one self-signed certificate for THIS Brain, persisted under
<dir>/tls/, and serves the same app on a second https port. The phone shows
one certificate warning the first time — it is the wearer's own appliance
certificate, the standard pattern for LAN appliances — and the camera works
from then on.

Honesty notes:
  * Off by default. A plain `python -m dreamlayer.ai_brain.server` binds
    loopback http, exactly as before.
  * The private key never leaves <dir>/tls/ and is written 0600.
  * cryptography is optional (extras: `verify`); absent -> a clear message,
    the http server runs unchanged, and the Live Lens still answers asks
    (camera needs the https link and says so).
  * If the LAN IP changed since the cert was minted, we re-mint so the SAN
    matches what the phone dials.
"""
from __future__ import annotations

import datetime
import logging
import socket
import ssl
from pathlib import Path
from typing import Optional

log = logging.getLogger("dreamlayer.tls")

CERT_NAME = "brain-cert.pem"
KEY_NAME = "brain-key.pem"
_VALID_DAYS = 3650


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _san_ips(cert) -> set[str]:
    """The IP SANs already inside a cert (cryptography objects)."""
    from cryptography import x509
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return {str(ip) for ip in ext.value.get_values_for_type(x509.IPAddress)}
    except Exception:
        return set()


def ensure_self_signed(cfg_dir: str | Path) -> Optional[tuple[Path, Path]]:
    """Mint (or reuse) this Brain's self-signed cert under <cfg_dir>/tls/.
    Returns (cert_path, key_path), or None when cryptography isn't installed.
    Re-mints automatically when the current LAN IP is missing from the SANs
    (the phone dials the IP, so the cert must name it)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.warning("[tls] cryptography not installed — https unavailable "
                    "(pip install 'dreamlayer[verify]')")
        return None

    import ipaddress

    d = Path(cfg_dir).expanduser() / "tls"
    d.mkdir(parents=True, exist_ok=True)
    # Harden the tls dir owner-only BEFORE the key is written, so the private key
    # is born private by inheritance — 0o600 alone is INERT on NTFS, exactly the
    # secret-at-rest gap store.py's config path already closed. Mirrors the
    # brain_config treatment (refute 2026-07-18: the new tls.py repeated the
    # original 0o600-only mistake for the TLS private key).
    from .store import _harden_state_dir
    _harden_state_dir(d)
    cert_p, key_p = d / CERT_NAME, d / KEY_NAME
    try:                                  # the SAME address the QR advertises
        from .server import lan_ip
        lan = lan_ip()
    except Exception:
        lan = _lan_ip()

    if cert_p.exists() and key_p.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
            # Validate the KEY loads AND matches the cert. A truncated key or a
            # key/cert mismatch (e.g. a crash BETWEEN the key write and the cert
            # write on a prior run) must re-mint HERE, not surface as an uncaught
            # ssl.SSLError at wrap_socket — which runs before serve_forever and
            # would take the WHOLE Brain down (refute 2026-07-18).
            key_obj = serialization.load_pem_private_key(
                key_p.read_bytes(), password=None)
            spki = serialization.PublicFormat.SubjectPublicKeyInfo
            der = serialization.Encoding.DER
            if (key_obj.public_key().public_bytes(der, spki)
                    != cert.public_key().public_bytes(der, spki)):
                raise ValueError("tls key does not match cert")
            now = datetime.datetime.now(datetime.timezone.utc)
            # not_valid_after_utc arrived in cryptography 42; older versions
            # expose the naive not_valid_after — normalize so reuse works on
            # both instead of silently re-minting every start.
            expiry = getattr(cert, "not_valid_after_utc", None)
            if expiry is None:
                expiry = cert.not_valid_after.replace(
                    tzinfo=datetime.timezone.utc)
            if lan in _san_ips(cert) and expiry > now:
                _tighten_key(key_p)           # re-assert owner-only on reuse
                return cert_p, key_p          # still names this LAN IP — reuse
        except Exception:
            pass                              # unreadable/mismatched — re-mint below

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DreamLayer Brain")])
    sans: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    # Name EVERY private LAN IP this host has, not just the default-route one, so
    # the cert matches whichever address the phone dials — surviving a VPN /
    # multi-NIC (the QR may advertise a sibling interface) and a DHCP lease change
    # (refute 2026-07-20). Falls back to the single `lan` if enumeration is empty.
    ips: list[str] = []
    try:
        from .server import lan_ip_candidates
        ips = lan_ip_candidates()
    except Exception:
        pass
    if lan != "127.0.0.1" and lan not in ips:
        ips.append(lan)
    for ip in ips:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    host = socket.gethostname()
    if host:
        sans.append(x509.DNSName(host))
        if not host.endswith(".local"):
            sans.append(x509.DNSName(host + ".local"))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=_VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .sign(key, hashes.SHA256()))

    key_p.touch(mode=0o600, exist_ok=True)
    key_p.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    _tighten_key(key_p)                       # 0o600 + owner-only Windows ACL
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("[tls] minted self-signed cert for %s", [str(s) for s in sans])
    return cert_p, key_p


def _tighten_key(key_p: Path) -> None:
    """Re-assert owner-only on the TLS private key: chmod 0o600 (POSIX) AND the
    Windows owner-only ACL (0o600 is INERT on NTFS — it toggles only the
    read-only bit and sets no ACL). Runs on BOTH the mint and reuse paths, so a
    key restored/copied with a wider mode or ACL is tightened on every start
    (refute 2026-07-18: the reuse path returned the key without re-tightening)."""
    try:
        key_p.chmod(0o600)
    except OSError:
        pass
    from .store import _harden_windows_acl
    _harden_windows_acl(str(key_p))


def make_ssl_context(cert_path: str | Path, key_path: str | Path) -> ssl.SSLContext:
    """A server-side TLS context pinned to modern minimums."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert_path), str(key_path))
    return ctx


def start_tls_sibling(brain, host: str, cfg_dir, http_port: int,
                      tls_port: int = 0):
    """Mint/reuse this Brain's self-signed cert and start the sibling HTTPS
    listener the Live Lens camera needs.

    A phone browser opens its camera only on a SECURE context (https, or
    localhost) — over plain http the Live Lens page loads but the camera never
    starts, which reads to the wearer as "the QR does nothing". This starts an
    https listener on a sibling port so the panel can hand out the secure link.

    Returns ``(tls_server, tls_port)``, or ``(None, 0)`` when ``cryptography`` is
    absent or setup fails — the caller then degrades to http-only, never crashes.
    The listener runs on a daemon thread; keep the returned server to shut it
    down. do_handshake_on_connect=False keeps a stalled ClientHello out of the
    single accept-loop thread — the worker runs the handshake under the same
    per-recv timeout + header watchdog + bounded semaphore as every request
    (refute 2026-07-18), so an unauthenticated LAN peer can't pin new camera
    connections."""
    import threading
    tport = tls_port or (http_port + 1)
    try:
        pair = ensure_self_signed(cfg_dir)        # inside the try: a mkdir/write
        if pair is None:                          # error (non-dir at <dir>/tls,
            return None, 0                        # disk-full, perms) must degrade
        from .server import make_brain_server      # to http-only, never crash the
        ctx = make_ssl_context(*pair)             # Brain (audit 2026-07-20)
        tls_server = make_brain_server(brain, host=host, port=tport,
                                       tls_port=tport)
        tls_server.socket = ctx.wrap_socket(
            tls_server.socket, server_side=True, do_handshake_on_connect=False)
        threading.Thread(target=tls_server.serve_forever, daemon=True).start()
        return tls_server, tport
    except Exception as exc:                      # noqa: BLE001 — degrade, don't crash
        log.warning("[tls] sibling https listener failed to start: %s", exc)
        return None, 0
