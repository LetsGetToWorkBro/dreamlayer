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
    # Login autostart now launches the full menu-bar APP (server + menu bar in
    # one process), not the headless `-m …server` that had no UI (audit
    # 2026-07-17). The appliance binds 0.0.0.0 internally (app_main._serve), so
    # no --host leaks onto argv.
    assert "dreamlayer.ai_brain.menubar" in body
    assert "dreamlayer.ai_brain.server" not in body
    assert "--host" not in body


def test_launch_agent_args_frozen_is_the_app_bundle():
    # Frozen (.app): the plist runs the bundle launcher directly — the same
    # server + menu bar the double-click app runs, NOT the headless server.
    args = menubar.launch_agent_args(
        directory="/Users/me/.dreamlayer", port=7778,
        executable="/Applications/DreamLayer.app/Contents/MacOS/DreamLayer",
        frozen=True)
    assert args[0] == "/Applications/DreamLayer.app/Contents/MacOS/DreamLayer"
    assert "-m" not in args and "dreamlayer.ai_brain.server" not in args
    assert "--dir" in args and "--port" in args


def test_launch_agent_args_source_runs_the_menubar_not_the_server():
    args = menubar.launch_agent_args(
        directory="/Users/me/.dreamlayer", port=7777,
        executable="/usr/bin/python3", frozen=False)
    # runs the MENU-BAR app entry, never `-m dreamlayer.ai_brain.server`
    assert args[:4] == ["/usr/bin/python3", "-m",
                        "dreamlayer.ai_brain.menubar", "--dir"]
    assert "dreamlayer.ai_brain.server" not in args
    assert "--port" not in args              # default port omitted


def test_install_launch_agent_has_log_paths_and_throttle(tmp_path, monkeypatch):
    # A boot-failing agent otherwise respawns on launchd's 10s KeepAlive floor
    # forever, and a windowed crash vanishes with no console. The plist now
    # points stdout/stderr at <state>/brain.log and sets a ThrottleInterval.
    monkeypatch.setattr(menubar.Path, "home", lambda: tmp_path)
    cfg = str(tmp_path / "cfg")
    p = menubar.install_launch_agent(directory=cfg, token="rune", port=7778)
    body = p.read_text()
    assert "<key>StandardOutPath</key>" in body
    assert "<key>StandardErrorPath</key>" in body
    assert "brain.log" in body
    assert "<key>ThrottleInterval</key>" in body
    import xml.etree.ElementTree as ET
    ET.fromstring(body)                       # still well-formed XML


def test_uninstall_login_removes_the_plist(tmp_path, monkeypatch):
    # The macOS mirror of the Windows tray's --uninstall-login (previously only
    # Windows had an uninstall path).
    monkeypatch.setattr(menubar.Path, "home", lambda: tmp_path)
    p = menubar.install_launch_agent(directory=str(tmp_path / "cfg"),
                                     token="rune", port=7778)
    assert p.exists()
    assert menubar.uninstall_launch_agent() is True
    assert not p.exists()
    assert menubar.uninstall_launch_agent() is False      # idempotent


def test_main_uninstall_login_removes_the_plist(tmp_path, monkeypatch):
    monkeypatch.setattr(menubar.Path, "home", lambda: tmp_path)
    menubar.install_launch_agent(directory=str(tmp_path / "cfg"),
                                 token="rune", port=7778)
    assert menubar.agent_path().exists()
    assert menubar.main(["--uninstall-login"]) == 0
    assert not menubar.agent_path().exists()


# -- opt-in "Check for updates" (click-only; injectable offline seam) ----------

def _fake_release(tag, url="https://example/rel"):
    import json as _json

    def _fetch(fetch_url, timeout):
        assert fetch_url == menubar.RELEASES_API      # hits the releases repo
        return _json.dumps({"tag_name": tag, "html_url": url}).encode()
    return _fetch


def test_check_for_update_reports_available_current_and_error():
    up = menubar.check_for_update(current="0.2.0", fetch_fn=_fake_release("v9.9.9"))
    assert up["status"] == "update" and "9.9.9" in up["message"]
    assert up["url"] == "https://example/rel"

    same = menubar.check_for_update(current="0.2.0", fetch_fn=_fake_release("v0.2.0"))
    assert same["status"] == "current"
    assert "up to date" in same["message"].lower()

    def boom(url, timeout):
        raise ConnectionError("offline")
    err = menubar.check_for_update(current="0.2.0", fetch_fn=boom)
    assert err["status"] == "error" and "check" in err["message"].lower()
    assert err["url"] == menubar.RELEASES_PAGE          # falls back to the page


def test_check_for_update_targets_the_releases_repo():
    assert menubar.RELEASES_REPO == "LetsGetToWorkBro/dreamlayer-releases"
    assert menubar.RELEASES_API.endswith(
        "/repos/LetsGetToWorkBro/dreamlayer-releases/releases/latest")


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
