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
    cert_p, key_p = d / CERT_NAME, d / KEY_NAME
    lan = _lan_ip()

    if cert_p.exists() and key_p.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
            now = datetime.datetime.now(datetime.timezone.utc)
            # not_valid_after_utc arrived in cryptography 42; older versions
            # expose the naive not_valid_after — normalize so reuse works on
            # both instead of silently re-minting every start.
            expiry = getattr(cert, "not_valid_after_utc", None)
            if expiry is None:
                expiry = cert.not_valid_after.replace(
                    tzinfo=datetime.timezone.utc)
            if lan in _san_ips(cert) and expiry > now:
                return cert_p, key_p          # still names this LAN IP — reuse
        except Exception:
            pass                              # unreadable — re-mint below

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DreamLayer Brain")])
    sans: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if lan != "127.0.0.1":
        sans.append(x509.IPAddress(ipaddress.ip_address(lan)))
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
    key_p.chmod(0o600)                        # belt + braces on reuse
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("[tls] minted self-signed cert for %s", [str(s) for s in sans])
    return cert_p, key_p


def make_ssl_context(cert_path: str | Path, key_path: str | Path) -> ssl.SSLContext:
    """A server-side TLS context pinned to modern minimums."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert_path), str(key_path))
    return ctx
