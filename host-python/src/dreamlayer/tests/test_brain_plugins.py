"""test_brain_plugins.py — the Mac Brain's plugin marketplace surface.

Pins the Brain's plugin store wiring: capabilities it can grant, sideload
install through the gate (and rejection of an un-grantable or dangerous one),
state listing, and removal — the endpoints the panel and phone drive.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import Brain
from dreamlayer.plugins import PluginPackage, sha256_of

GOOD_SRC = ("from dreamlayer.plugins import make_plugin\n"
            "def p():\n return make_plugin('tidy', lambda c: None)\n")


def good_pkg():
    return PluginPackage.build(name="tidy", version="1.0.0", entry="plugin:p",
                               source=GOOD_SRC, author="tester")


def body_for(pkg):
    return {"manifest": pkg.manifest.to_dict(), "source": pkg.source}


def test_brain_grants_expected_capabilities(tmp_path):
    b = Brain(tmp_path)
    caps = b.plugin_capabilities()
    assert {"object_lens", "glance", "cards", "midi"} <= caps
    # keyword model, no cloud → no vision; connected posture → network
    assert "vision" not in caps


def test_sideload_install_lists_and_removes(tmp_path):
    b = Brain(tmp_path)
    assert b.plugins_state()["installed"] == []
    res = b.install_plugin(body_for(good_pkg()))
    assert res["ok"]
    state = b.plugins_state()
    assert [p["name"] for p in state["installed"]] == ["tidy"]
    assert b.remove_plugin("tidy")["ok"]
    assert b.plugins_state()["installed"] == []


def test_install_rejects_dangerous_undeclared_code(tmp_path):
    b = Brain(tmp_path)
    bad = PluginPackage.build(name="sneaky", version="1.0.0", entry="plugin:p",
                              source="import subprocess\ndef p():\n return None\n")
    res = b.install_plugin(body_for(bad))
    assert not res["ok"] and any("subprocess" in e for e in res["errors"])
    assert b.plugins_state()["installed"] == []      # nothing written


def test_install_rejects_a_capability_the_brain_wont_grant(tmp_path):
    b = Brain(tmp_path)
    # fs is withheld by default → a plugin requiring it can't install here
    needs_fs = PluginPackage.build(name="filer", version="1.0.0", entry="plugin:p",
                                   requires=("fs",),
                                   source="from dreamlayer.plugins import make_plugin\n"
                                          "def p():\n return make_plugin('filer', lambda c: None, requires=('fs',))\n")
    res = b.install_plugin(body_for(needs_fs))
    assert not res["ok"] and any("fs" in e for e in res["errors"])


def test_install_needs_a_package_or_name(tmp_path):
    b = Brain(tmp_path)
    res = b.install_plugin({})
    assert not res["ok"] and res["errors"]


def test_plugins_state_exposes_author_detail(tmp_path):
    # the panel/phone detail view reads long/forwho/screenshot from here, so an
    # author's own store copy shows on-device, not just on the website.
    b = Brain(tmp_path)
    rich = PluginPackage.build(
        name="tidy", version="1.0.0", entry="plugin:p", source=GOOD_SRC,
        author="tester", description="keeps things tidy",
        long=("how it helps you", "and a second paragraph"),
        forwho="for the tidy-minded",
        screenshot="https://dreamlayer.app/plugin-shots/tidy.png")
    assert b.install_plugin(body_for(rich))["ok"]
    entry = b.plugins_state()["installed"][0]
    assert entry["long"] == ["how it helps you", "and a second paragraph"]
    assert entry["forwho"] == "for the tidy-minded"
    assert entry["screenshot"] == "https://dreamlayer.app/plugin-shots/tidy.png"
