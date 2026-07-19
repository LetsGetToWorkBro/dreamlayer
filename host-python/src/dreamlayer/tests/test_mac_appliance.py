"""test_mac_appliance.py — one-click Ollama pull + the menu-bar appliance core.

The rumps GUI is macOS-only, but its brains are pure: the status summary and
the LaunchAgent plist. The model pull talks to Ollama's HTTP API through an
injectable poster.
"""
from __future__ import annotations

import urllib.error

import pytest

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


def test_status_icon_paths_ship_and_never_fake_green():
    import os

    # every traffic-light state maps to a sprite that actually ships
    for icon, name in menubar.STATUS_ICONS.items():
        p = menubar.status_icon_path({"icon": icon})
        assert p.endswith(name) and os.path.exists(p)

    # unknown/absent → the offline sprite, mirroring dot_color's honesty rule
    assert menubar.status_icon_path(None).endswith("juno_status_offline.png")
    assert menubar.status_icon_path({"icon": "??"}).endswith("juno_status_offline.png")


# -- stale-token recovery: a mid-session rotation is picked up, no restart ------

def test_menu_bar_recovers_from_a_rotated_pairing_token(tmp_path):
    # The menu bar caches the pairing token and, before this fix, re-read it from
    # config ONLY while empty (the grey-dot startup-race fix). So once a NON-empty
    # token was cached it was never re-read for the process lifetime: a mid-session
    # token ROTATION (the panel "rotate" action mints a new token into
    # brain_config.json) stranded the UI on the OLD token → every loopback call
    # 401s → a permanent grey dot until restart. The fix: an _api 401/403 clears
    # the cache so the next _token() re-reads the fresh token.
    cfg = tmp_path / "cfg"; cfg.mkdir()
    BrainConfig(token="old").save(cfg)

    auth = menubar._TokenCache(str(cfg), BrainConfig.load)
    assert auth.get() == "old"                       # cached the initial token

    # the panel rotates the token: a NEW token is persisted to brain_config.json …
    BrainConfig(token="new").save(cfg)
    # … but a non-empty cache still hands out the stale token (the bug's setup):
    assert auth.get() == "old"

    # an _api call authenticating with the stale token comes back 401
    class _Opener401:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized",
                                         {}, None)

    with pytest.raises(urllib.error.HTTPError):
        menubar._authed_api(7777, auth, "/dreamlayer/config", "POST",
                            b"{}", opener=_Opener401())

    # the 401 INVALIDATED the cache → the next read recovers the rotated token
    # WITHOUT a restart. The reverted "re-read only while empty" logic (no
    # invalidate on auth failure) would stay stuck on "old" and fail here.
    assert auth.get() == "new"


class _Resp:
    """A minimal urlopen()-style response for the injected opener below."""
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RotatingOpener:
    """401s while the request still carries the stale "old" token; serves a
    healthy /status once the request carries the rotated "new" token. Proves the
    PASSIVE poll re-reads the fresh token after invalidation, with no server."""
    GREEN = (b'{"model":"ollama","cloud":true,"cloud_ready":true,'
             b'"stats":{"files":1}}')

    def __init__(self):
        self.tokens_seen = []

    def open(self, req, timeout=None):
        import urllib.error
        tok = req.headers.get("X-dreamlayer-token")   # urllib capitalizes keys
        self.tokens_seen.append(tok)
        if tok == "new":
            return _Resp(self.GREEN)
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)


def test_passive_refresh_self_heals_from_a_rotated_token_no_user_action(tmp_path):
    # THE PASSIVE-PATH GAP: the status dot is driven by fetch_status on the 15s
    # refresh tick, NOT by _authed_api (which only runs on Sync/Incognito). Before
    # this fix fetch_status swallowed every error and NEVER touched the token
    # cache, so after a mid-session rotation the passive tick re-sent the stale
    # cached token forever → the dot went grey and STAYED grey until the user
    # clicked something. The fix: fetch_status invalidates the cache on a 401/403
    # so the NEXT tick re-reads the rotated token and the dot recovers on its own.
    cfg = tmp_path / "cfg"; cfg.mkdir()
    BrainConfig(token="old").save(cfg)
    auth = menubar._TokenCache(str(cfg), BrainConfig.load)
    assert auth.get() == "old"                       # cached the initial token

    # the panel rotates the token: config now holds "new", cache still "old"
    BrainConfig(token="new").save(cfg)
    assert auth.get() == "old"                        # stale cache hands out old

    opener = _RotatingOpener()
    # tick 1 — the PASSIVE poll authenticates with the stale cached token and
    # 401s. It returns None (grey dot this tick, honest for a genuine outage)
    # AND, crucially, invalidates the cache. No _authed_api / user action here.
    st = menubar.fetch_status(7777, auth.get(), auth=auth, opener=opener)
    assert st is None                                 # grey dot preserved

    # the 401 invalidated the cache → the next read picks up the rotated token …
    assert auth.get() == "new"

    # tick 2 — the very next passive poll now carries "new" and recovers a GREEN
    # dot, with NO user action taken. The reverted fetch_status (never
    # invalidating) would keep sending "old", stay 401, and fail this assertion.
    st2 = menubar.fetch_status(7777, auth.get(), auth=auth, opener=opener)
    assert st2 is not None
    assert menubar.status_summary(st2)["icon"] == "\U0001F7E2"   # green — healed
    assert opener.tokens_seen == ["old", "new"]


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


def test_launch_agent_args_source_brings_up_a_server_with_the_menubar(monkeypatch):
    # The source LaunchAgent runs the MENU-BAR module entry (never the headless
    # `-m dreamlayer.ai_brain.server`)…
    args = menubar.launch_agent_args(
        directory="/Users/me/.dreamlayer", port=7777,
        executable="/usr/bin/python3", frozen=False)
    assert args[:4] == ["/usr/bin/python3", "-m",
                        "dreamlayer.ai_brain.menubar", "--dir"]
    assert "dreamlayer.ai_brain.server" not in args
    assert "--port" not in args              # default port omitted
    # …but that entry (menubar.main → run_menubar) must now bring up the Brain
    # server TOO, not just a menu bar pointed at a server that never starts (a
    # permanently grey/offline dot with no pairing target). Finding A: assert the
    # login-autostart entry requests a server (serve=True).
    captured = {}

    def fake_run_menubar(directory=None, port=menubar.DEFAULT_PORT, serve=False):
        captured["serve"] = serve
        captured["dir"] = directory
        return 0
    monkeypatch.setattr(menubar, "run_menubar", fake_run_menubar)
    assert menubar.main(["--dir", "/Users/me/.dreamlayer"]) == 0
    assert captured["serve"] is True         # the autostart serves, not just UI


def test_source_autostart_serves_on_0_0_0_0_with_a_pairing_token(monkeypatch):
    # The other half of Finding A: the server the source autostart starts binds
    # 0.0.0.0 (LAN-reachable pairing target) and mints a pairing token on first
    # run — exactly like the frozen .app's app_main._serve. Without this the dot
    # stays grey and the paired phone has no target.
    import dreamlayer.ai_brain.server.server as srv
    captured: dict = {}

    class _Cfg:
        token = ""

    class _FakeBrain:
        def __init__(self, d):
            self.config = _Cfg()

        def save(self):
            captured["saved"] = True

        def start_watching(self): ...
        def start_brief_scheduler(self): ...
        def start_calendar_sync(self): ...

    class _FakeServer:
        def serve_forever(self):
            captured["served"] = True        # returns at once so _serve_brain ends

    def _capture(brain, host, port):
        # mint happened before bind → token present when we authenticate
        captured["host"] = host
        captured["port"] = port
        captured["token"] = brain.config.token
        return _FakeServer()

    monkeypatch.setattr(srv, "Brain", _FakeBrain)
    monkeypatch.setattr(srv, "make_brain_server", _capture)
    status: dict = {}
    menubar._serve_brain("/tmp/x", 7777, status)     # thread target, run inline
    assert status.get("bound") is True and status.get("error") is None
    assert captured["host"] == "0.0.0.0"             # LAN-reachable, not loopback
    assert captured["port"] == 7777
    assert captured["token"]                          # a pairing token was minted
    assert captured.get("served") is True


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


def test_check_for_update_prerelease_and_nonsemver_dont_false_current():
    # Finding C: the version compare must NEVER claim "up to date" it can't
    # justify. The old truncating parser read 1.2.3-rc1 == 1.2.3 (an rc user
    # never saw the stable release) and mapped a non-semver latest → (0,) (which
    # masked a real newer release).
    #
    # A pre-release running version is offered the stable release (rc sorts
    # BELOW its release):
    rc = menubar.check_for_update(current="1.2.3-rc1",
                                  fetch_fn=_fake_release("v1.2.3"))
    assert rc["status"] == "update"
    assert rc["latest"] == "v1.2.3"
    # A stable running version is NOT told to "downgrade" to a pre-release:
    stable = menubar.check_for_update(current="1.2.3",
                                      fetch_fn=_fake_release("v1.2.3-rc1"))
    assert stable["status"] == "current"
    # A non-semver latest tag ("nightly"/"stable") must NOT read as "current" —
    # surface the release so the user can open it, never a false "up to date":
    ns = menubar.check_for_update(current="1.2.3",
                                  fetch_fn=_fake_release("nightly"))
    assert ns["status"] != "current"
    assert ns["latest"] == "nightly"
    assert "up to date" not in ns["message"].lower()
    # …and the clean cases still work: v-prefix equals bare, equal → current.
    eq = menubar.check_for_update(current="1.2.3", fetch_fn=_fake_release("v1.2.3"))
    assert eq["status"] == "current"
    newer = menubar.check_for_update(current="1.2.3",
                                     fetch_fn=_fake_release("v1.2.4"))
    assert newer["status"] == "update"
    older = menubar.check_for_update(current="1.3.0",
                                     fetch_fn=_fake_release("v1.2.9"))
    assert older["status"] == "current"


def test_check_for_update_targets_the_releases_repo():
    assert menubar.RELEASES_REPO == "LetsGetToWorkBro/dreamlayer"
    assert menubar.RELEASES_API.endswith(
        "/repos/LetsGetToWorkBro/dreamlayer/releases/latest")


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
