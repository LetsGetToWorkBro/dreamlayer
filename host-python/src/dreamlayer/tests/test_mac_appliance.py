"""test_mac_appliance.py — one-click Ollama pull + the menu-bar appliance core.

The rumps GUI is macOS-only, but its brains are pure: the status summary and
the LaunchAgent plist. The model pull talks to Ollama's HTTP API through an
injectable poster.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.ai_brain.server.backends import pull_model
from dreamlayer.ai_brain import menubar


# -- one-click Ollama pull ----------------------------------------------------

def test_pull_model_reports_success():
    calls = {}
    def poster(url, payload, timeout):
        calls["url"] = url; calls["name"] = payload["name"]
        return {"status": "success"}
    r = pull_model(BrainConfig(), "llama3.2", poster=poster)
    assert r == {"ok": True, "status": "success", "model": "llama3.2"}
    assert calls["url"].endswith("/api/pull") and calls["name"] == "llama3.2"


def test_pull_model_handles_failure_and_empty():
    def boom(url, payload, timeout):
        raise ConnectionError("no ollama")
    r = pull_model(BrainConfig(), "llama3.2", poster=boom)
    assert r["ok"] is False and "ollama" in r["status"].lower()
    assert pull_model(BrainConfig(), "")["ok"] is False       # no name


def test_brain_pull_model_logs_on_success(tmp_path):
    from dreamlayer.ai_brain.server import Brain
    cfg = tmp_path / "cfg"; cfg.mkdir()
    BrainConfig(token="t").save(cfg)
    brain = Brain(cfg)
    # patch the module-level pull to avoid a real network call
    import dreamlayer.ai_brain.server.backends as be
    orig = be.pull_model
    be.pull_model = lambda config, name: {"ok": True, "status": "success", "model": name}  # type: ignore[assignment,misc]  # test monkeypatch
    try:
        r = brain.pull_model("llama3.2")
    finally:
        be.pull_model = orig
    assert r["ok"]
    assert any(i["kind"] == "model" for i in brain.activity.recent())


# -- menu-bar status summary --------------------------------------------------

def test_status_summary_green_yellow_incognito_offline():
    green = menubar.status_summary({"model": "ollama", "cloud": True,
                                    "cloud_ready": True, "stats": {"files": 12}})
    assert green["icon"] == "\U0001F7E2" and "Online" in green["title"]

    yellow = menubar.status_summary({"cloud": True, "cloud_ready": False,
                                     "stats": {"files": 0}})
    assert yellow["icon"] == "\U0001F7E1"

    incog = menubar.status_summary({"incognito": True, "stats": {"files": 3}})
    assert "Incognito" in incog["title"]

    off = menubar.status_summary(None)
    assert off["icon"] == "⚪" and "offline" in off["title"].lower()


# -- launch-at-login plist ----------------------------------------------------

def test_launch_agent_plist_is_valid_and_runs_the_server():
    xml = menubar.launch_agent_plist(
        ["/usr/bin/python3", "-m", "dreamlayer.ai_brain.server", "--port", "7777"],
        working_dir="/Users/me")
    assert xml.startswith("<?xml") and "<plist" in xml
    assert "dreamlayer.ai_brain.server" in xml
    assert "<key>RunAtLoad</key>" in xml and "<true/>" in xml
    assert "vision.dreamlayer.brain" in xml
    # well-formed XML
    import xml.etree.ElementTree as ET
    ET.fromstring(xml)


def test_install_launch_agent_writes_plist(tmp_path, monkeypatch):
    monkeypatch.setattr(menubar.Path, "home", lambda: tmp_path)
    cfg = str(tmp_path / "cfg")
    p = menubar.install_launch_agent(directory=cfg, token="rune", port=7778)
    assert p.exists() and p.name == "vision.dreamlayer.brain.plist"
    body = p.read_text()
    # The pairing token must NEVER land in the plist ProgramArguments: the plist
    # is readable and argv shows in `ps`, so a `--token <secret>` there leaked
    # the pairing secret exactly like the Windows HKCU Run value did (refute
    # 2026-07-17). It is persisted to brain_config.json instead, and the plist
    # is pinned to that --dir so login-time resolves the same config.
    assert "--token" not in body and "rune" not in body
    assert "7778" in body
    assert "--dir" in body and cfg in body
    assert BrainConfig.load(cfg).token == "rune"
    # The login agent IS the LAN appliance the phone pairs with, so it must
    # opt into a network-reachable bind explicitly (re-audit 2026-07). A bare
    # `python -m …server` stays loopback; only this deployment path binds 0.0.0.0.
    assert "--host" in body and "0.0.0.0" in body


def test_install_launch_agent_pins_dir_even_when_directory_is_none(tmp_path, monkeypatch):
    # Regression: with directory=None the plist previously carried no --dir, so a
    # DREAMLAYER_DIR set only in the install shell would send the token to dir A
    # while the login agent re-resolved dir B, found none, and minted a fresh one
    # (breaking the paired phone). The token dir is now pinned into the plist.
    monkeypatch.setattr(menubar.Path, "home", lambda: tmp_path)
    envdir = str(tmp_path / "envcfg")
    monkeypatch.setenv("DREAMLAYER_DIR", envdir)
    p = menubar.install_launch_agent(directory=None, token="rune", port=7778)
    body = p.read_text()
    assert "--token" not in body and "rune" not in body
    assert "--dir" in body and envdir in body
    assert BrainConfig.load(envdir).token == "rune"
