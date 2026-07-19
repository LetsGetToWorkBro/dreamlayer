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
