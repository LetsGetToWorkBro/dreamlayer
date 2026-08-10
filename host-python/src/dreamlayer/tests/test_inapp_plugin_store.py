"""test_inapp_plugin_store.py — the in-app plugin store (fast-follow 2026-07-19).

Browse the pinned registry and 1-click install inside the app, no web page or
terminal. The fetch is PINNED (client sends a name, never a URL), redirects are
refused, reads are capped, and every install still runs the existing checksum +
capability/sandbox gate. Revert-failing.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import dreamlayer.plugins.registry_client as rc
from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.panel import render_panel

_REPO = Path(__file__).resolve().parents[4]        # …/dreamlayer (repo root)


def _real_getter():
    """Serve the repo's real registry files instead of the network."""
    idx = (_REPO / "registry" / "index.json").read_text()

    def get(url, cap):
        if url == rc.REGISTRY_INDEX_URL:
            return idx
        assert url.startswith(rc.REGISTRY_RAW_BASE)
        return (_REPO / url[len(rc.REGISTRY_RAW_BASE):]).read_text()
    return get


# --- pinned-fetch safety (pure) ---------------------------------------------

def test_fetch_package_refuses_absolute_or_off_host_url():
    for bad in ("https://evil.example/p.json", "//evil/p.json",
                "/etc/passwd", "\\\\host\\share", ""):
        with pytest.raises(ValueError):
            rc.fetch_package(bad, getter=lambda u, c: "{}")


def test_fetch_package_resolves_relative_against_pinned_base():
    seen = {}

    def spy(url, cap):
        seen["url"] = url
        return "{}"
    rc.fetch_package("registry/packages/x-0.1.0.json", getter=spy)
    assert seen["url"] == rc.REGISTRY_RAW_BASE + "registry/packages/x-0.1.0.json"
    assert seen["url"].startswith("https://raw.githubusercontent.com/")


def test_fetch_index_parses(monkeypatch):
    monkeypatch.setattr(rc, "_http_get", _real_getter())
    idx = rc.fetch_index()
    assert isinstance(idx.get("plugins"), list) and idx["plugins"]


# --- browse -----------------------------------------------------------------

def test_store_catalogue_lists_plugins_with_installed_flags(monkeypatch):
    monkeypatch.setattr(rc, "_http_get", _real_getter())
    brain = Brain(tempfile.mkdtemp())
    cat = brain.store_catalogue()
    assert cat.get("error") is None
    assert len(cat["plugins"]) >= 1
    assert all("installed" in p for p in cat["plugins"])
    assert cat["plugins"][0]["installed"] is False


def test_store_is_posture_gated(monkeypatch):
    monkeypatch.setattr(rc, "_http_get", _real_getter())
    brain = Brain(tempfile.mkdtemp())
    brain.config.network_mode = "lan_only"          # Incognito / LAN-only ⇒ no egress
    assert "error" in brain.store_catalogue()
    r = brain.store_install("face-synth")
    assert r["ok"] is False and r["errors"]


# --- 1-click install (through the real checksum + gate) ---------------------

def test_store_install_happy_path(monkeypatch):
    monkeypatch.setattr(rc, "_http_get", _real_getter())
    brain = Brain(tempfile.mkdtemp())
    name = brain.store_catalogue()["plugins"][0]["name"]
    r = brain.store_install(name)
    assert r["ok"] is True
    assert brain.plugins.is_installed(name)


def test_store_install_rejects_a_checksum_mismatch(monkeypatch):
    # a tampered/poisoned package whose bytes no longer match the registry's
    # advertised checksum must be REFUSED and nothing written.
    real = _real_getter()

    def tampering(url, cap):
        body = real(url, cap)
        if url != rc.REGISTRY_INDEX_URL:            # corrupt the package, not the index
            body = body.replace('"source"', '"source_TAMPERED"', 1)
        return body
    monkeypatch.setattr(rc, "_http_get", tampering)
    brain = Brain(tempfile.mkdtemp())
    name = brain.store_catalogue()["plugins"][0]["name"]
    r = brain.store_install(name)
    assert r["ok"] is False
    assert not brain.plugins.is_installed(name)


def test_store_install_unknown_name(monkeypatch):
    monkeypatch.setattr(rc, "_http_get", _real_getter())
    brain = Brain(tempfile.mkdtemp())
    r = brain.store_install("no-such-plugin-xyz")
    assert r["ok"] is False and r["errors"]


# --- panel UI ---------------------------------------------------------------

def test_panel_has_in_app_store_ui_and_no_web_store_link():
    html = render_panel("tok")
    assert "openStore" in html and "installFromStore" in html
    assert 'id="storeGrid"' in html
    # the old outbound web-store link is gone (browse is in-app now)
    assert "dreamlayer.app/plugins.html" not in html


# --- the Veil, over the PACKAGE fetch (#628) ---------------------------------

class TestNoRegistryFetchWhileTheVeilIsUp:
    """#628 — `install_plugin` by registry name fetched the package while the
    Veil was up, and its two siblings refused in the same conditions.

    `PluginStore.install()` reads the already-loaded index and then fetches from
    raw.githubusercontent.com. Two Brain methods reached that fetch;
    `store_install` checked the posture and `install_plugin`'s registry-name
    branch checked on no branch. With a warm index — which browsing the store
    with the Veil DOWN leaves behind — installing by name during Incognito or
    quiet hours opened a connection. What left was that the device is online and
    which plugin it wants: confidentiality, not integrity, since the checksum
    and sandbox gates were never bypassed.

    That is `decisions/0009`'s drift class — hand-written per-call-site Veil
    gates diverging — so the fix is a chokepoint, `Brain._install_from_registry`,
    and these assert it by DRIVING the egress rather than reading the source.
    """

    @staticmethod
    def _brain_with_warm_index(tmp_path):
        """A Brain whose index is loaded, exactly as a store browse leaves it.
        Without this the bug is unreachable: `install()` returns at store.py's
        `entry is None` before opening any socket."""
        from dreamlayer.plugins.store import RegistryIndex
        b = Brain(tmp_path / "cfg")
        b.plugins.index = RegistryIndex.from_dict({"updated": "x", "plugins": [
            {"name": "demo", "version": "1.0.0", "summary": "s", "author": "a",
             "url": "registry/packages/demo.json", "checksum": "deadbeef"}]})
        return b

    @pytest.fixture
    def recorder(self, monkeypatch):
        """Records at the one function that opens a socket, and never lets a
        real one open. A spy on `PluginStore.install` would prove nothing —
        the question is whether a packet leaves."""
        calls: list = []

        def spy(url, cap):
            calls.append(url)
            raise OSError("recorder: no real egress")
        monkeypatch.setattr(rc, "_http_get", spy)
        return calls

    @pytest.mark.parametrize("entry", [
        pytest.param(lambda b: b.install_plugin({"name": "demo"}), id="by-name"),
        pytest.param(lambda b: b.store_install("demo"), id="store-install"),
    ])
    def test_it_opens_no_connection_while_veiled(self, tmp_path, recorder,
                                                 monkeypatch, entry):
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: True)
        entry(b)
        assert recorder == [], (
            f"a package fetch left the device while the Veil was up: {recorder}")

    def test_the_veil_is_the_only_thing_stopping_it(self, tmp_path, recorder,
                                                    monkeypatch):
        """The other direction, and the one that makes the test above mean
        something: with the Veil DOWN the same call DOES reach the registry.
        Without this, deleting the fetch entirely would pass."""
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: False)
        b.install_plugin({"name": "demo"})
        assert [u for u in recorder if u.endswith("demo.json")], (
            "install by name reached no registry package even unveiled — "
            "this test is no longer exercising the fetch")

    def test_a_sideload_still_works_while_veiled(self, tmp_path, recorder,
                                                 monkeypatch):
        """The refusal must be as narrow as the egress. A sideloaded package
        carries its own source and needs no network, so `dreamlayer plugin
        install` stays usable under the shield — gating the whole method rather
        than the registry branch would have taken that away."""
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: True)
        out = b.install_plugin({"manifest": {"name": "sl", "version": "1.0.0"},
                                "source": "print(1)"})
        assert recorder == []
        assert "Incognito" not in " ".join(out["errors"]), (
            f"the sideload path was refused for a network reason: {out}")

    def test_the_refusal_says_why(self, tmp_path, recorder, monkeypatch):
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: True)
        out = b.install_plugin({"name": "demo"})
        assert out["ok"] is False
        assert any("Incognito" in e or "LAN-only" in e for e in out["errors"]), (
            f"refused without saying the posture is why: {out['errors']}")

    def test_an_install_is_on_the_consent_ledger(self, tmp_path, recorder,
                                                 monkeypatch):
        """#611 registered the INDEX fetch, so the ledger said "browsed" and
        never "installed" — the same under-reporting one call along. Counted on
        ATTEMPT, because a socket opens whether or not the download completes,
        and this recorder makes every one of them fail."""
        from dreamlayer.ai_brain.server.consent_gate import consent
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: False)
        b.install_plugin({"name": "demo"})
        sent = {r["key"]: r["sent"] for r in consent(b).report()}
        assert sent["plugin_registry"] >= 1, (
            "a package fetch left the device and the ledger did not count it")

    def test_an_unknown_name_never_reaches_the_network(self, tmp_path, recorder,
                                                       monkeypatch):
        """…and is not counted as a send. The early return is what keeps the
        ledger honest in the other direction."""
        from dreamlayer.ai_brain.server.consent_gate import consent
        b = self._brain_with_warm_index(tmp_path)
        monkeypatch.setattr(type(b), "incognito_now", lambda self: False)
        b.install_plugin({"name": "not-in-the-registry"})
        assert recorder == []
        sent = {r["key"]: r["sent"] for r in consent(b).report()}
        assert sent["plugin_registry"] == 0


class TestThePackageFetchKeepsOneGate:
    """A source tripwire, and it says so.

    The behavioural tests above cover the two call sites that exist. This one
    is about the fourteenth: `decisions/0009` records twelve hand-written Veil
    gates that drifted, #628 was the thirteenth, and the reason it was missed is
    that adding `self.plugins.install(name)` to a new Brain method looks
    complete on its own. `_install_from_registry` owns that fetch so a new
    caller inherits the gate; this fails if somebody routes around it.
    """

    @staticmethod
    def _server_src() -> str:
        import pathlib

        from dreamlayer.ai_brain.server import server as S
        return pathlib.Path(S.__file__).read_text(encoding="utf-8")

    def test_the_scan_actually_reads_the_brain(self):
        """Without this the assertion below passes on an empty string — the
        failure this repo keeps meeting (CLAUDE.md #1)."""
        src = self._server_src()
        assert len(src) > 50_000, f"server.py read as {len(src)} chars"
        assert "_install_from_registry" in src, "the chokepoint is gone"

    def test_only_the_chokepoint_calls_the_registry_install(self):
        """By AST, not by line, so the chokepoint's own call is not a finding
        and a reformatted call site is still one."""
        import ast

        tree = ast.parse(self._server_src())
        callers = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "install"
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == "plugins"):
                    callers.add(fn.name)
        assert callers == {"_install_from_registry"}, (
            f"PluginStore.install() is reached from {sorted(callers)}. Only "
            f"Brain._install_from_registry may call it — anything else does "
            f"not inherit the Veil gate #628 added, which is exactly how "
            f"install_plugin came to differ from store_install.")
