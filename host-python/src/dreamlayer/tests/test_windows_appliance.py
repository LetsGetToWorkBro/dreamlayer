"""test_windows_appliance.py — the Windows system-tray appliance core.

The pystray GUI is Windows-only, but its brains are pure (mirroring
test_mac_appliance.py): the status→dot-color map, the start-at-login Run
command, and the reuse of menubar.status_summary. The registry round-trip
itself runs only on Windows (the CI leg exercises it); everywhere else the
construction is what's tested — same split as the LaunchAgent plist writer.
"""
from __future__ import annotations

import sys

import pytest

from dreamlayer.ai_brain import menubar, tray_windows


# -- the status dot reuses the menu bar's pure summary --------------------------

def test_dot_color_traffic_light():
    green = menubar.status_summary({"model": "ollama", "cloud": True,
                                    "cloud_ready": True, "stats": {"files": 12}})
    assert tray_windows.dot_color(green) == "#1F8A3D"

    yellow = menubar.status_summary({"cloud": True, "cloud_ready": False,
                                     "stats": {"files": 0}})
    assert tray_windows.dot_color(yellow) == "#E6A700"

    incog = menubar.status_summary({"incognito": True, "stats": {"files": 3}})
    assert tray_windows.dot_color(incog) == "#333399"

    off = menubar.status_summary(None)
    assert tray_windows.dot_color(off) == tray_windows.OFFLINE_COLOR


def test_dot_color_never_fakes_health():
    # absent or unrecognised state must read offline-grey, never green
    assert tray_windows.dot_color(None) == tray_windows.OFFLINE_COLOR
    assert tray_windows.dot_color({"icon": "??"}) == tray_windows.OFFLINE_COLOR


def test_status_lines_are_shared_with_the_mac_menu():
    # the tray shows the exact lines the Mac menu shows — one pure core
    s = menubar.status_summary({"model": "keyword", "stats": {"files": 2}})
    assert s["lines"][0] == "Status: Online"
    assert any(line == "Model: keyword" for line in s["lines"])


# -- start-at-login: the Run-entry command (pure) -------------------------------

def test_build_login_entry_source_mirrors_the_launch_agent():
    cmd = tray_windows.build_login_entry(
        directory="C:\\Users\\me\\.dreamlayer", token="rune", port=7778,
        executable="C:\\Python311\\python.exe", frozen=False)
    assert cmd.startswith("C:\\Python311\\python.exe -m dreamlayer.ai_brain.server")
    # The login entry IS the LAN appliance the phone pairs with, so it must
    # opt into a network-reachable bind explicitly — exactly like the macOS
    # LaunchAgent (see test_mac_appliance.py).
    assert "--host 0.0.0.0" in cmd
    assert "--port 7778" in cmd
    assert "--dir" in cmd
    # SECURITY (audit 2026-07-17): the pairing token is NEVER on the command
    # line. An HKCU Run value is readable by any process running as the user, so
    # `--token <secret>` there leaked the pairing secret registry-/ps-visible.
    # The launched server reads the token from brain_config.json instead.
    assert "--token" not in cmd and "rune" not in cmd


def test_login_entry_never_embeds_the_pairing_token():
    # Even when a token is passed, build_login_entry must not emit it — the
    # command a Run key holds is world-readable to every user-level process.
    secret = "s3cr3t-pairing-abcdef0123456789"
    src = tray_windows.build_login_entry(
        directory=r"C:\Users\me\.dreamlayer", token=secret, port=7778,
        executable=r"C:\Python311\python.exe", frozen=False)
    frozen = tray_windows.build_login_entry(
        directory=r"D:\state", token=secret, port=7778,
        executable=r"C:\Apps\DreamLayer.exe", frozen=True)
    for cmd in (src, frozen):
        assert secret not in cmd
        assert "--token" not in cmd
    # …and the source entry still launches the server, which resolves the token
    # from the on-disk config it points at via --dir.
    assert "-m dreamlayer.ai_brain.server" in src
    assert "--dir" in src


def test_appliance_resolves_pairing_token_from_on_disk_config(tmp_path):
    # The other half of the fix: the process the login entry launches reads the
    # pairing token from brain_config.json (0600-equivalent) — no token needed
    # on argv. Constructing a Brain over a cfg dir loads exactly the persisted
    # token, which is what run_tray/the server authenticate with.
    from dreamlayer.ai_brain.server import Brain
    from dreamlayer.ai_brain.server.store import BrainConfig
    BrainConfig(token="persisted-secret").save(tmp_path)
    assert Brain(tmp_path).config.token == "persisted-secret"


def test_build_login_entry_frozen_is_just_the_app():
    cmd = tray_windows.build_login_entry(
        executable=r"C:\Program Files\DreamLayer\DreamLayer.exe", frozen=True)
    # the bundled exe is server + tray in one process — no module invocation
    assert cmd == '"C:\\Program Files\\DreamLayer\\DreamLayer.exe"'


def test_build_login_entry_frozen_keeps_nondefault_dir_and_port():
    cmd = tray_windows.build_login_entry(
        directory=r"D:\brain state", port=7779,
        executable=r"C:\Apps\DreamLayer.exe", frozen=True)
    assert cmd == r'C:\Apps\DreamLayer.exe --dir "D:\brain state" --port 7779'


def test_login_command_quotes_spaces_and_escapes_quotes():
    assert tray_windows.login_command(r"C:\a b\x.exe", ["--dir", 'we"ird']) == \
        '"C:\\a b\\x.exe" --dir "we\\"ird"'
    # nothing to quote → written verbatim
    assert tray_windows.login_command("py.exe", ["--port", "7777"]) == \
        "py.exe --port 7777"


# -- registry round-trip (Windows only — the CI leg runs this) ------------------

@pytest.mark.skipif(sys.platform != "win32", reason="HKCU registry is Windows-only")
def test_install_uninstall_login_round_trip():
    value = "DreamLayerTest"
    try:
        written = tray_windows.install_login_entry(
            directory=None, token="", port=7777, value_name=value)
        assert tray_windows.read_login_entry(value) == written
        assert "dreamlayer" in written.lower()
        assert tray_windows.uninstall_login_entry(value) is True
    finally:
        tray_windows.uninstall_login_entry(value)   # idempotent cleanup
    assert tray_windows.read_login_entry(value) is None
    assert tray_windows.uninstall_login_entry(value) is False


# -- the module loads-and-no-ops off Windows ------------------------------------

def test_run_tray_declines_politely_without_pystray(monkeypatch, capsys):
    # simulate pystray being absent (it isn't a dependency on CI/Linux)
    import builtins
    real_import = builtins.__import__

    def no_pystray(name, *a, **kw):
        if name == "pystray":
            raise ImportError("no pystray here")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_pystray)
    assert tray_windows.run_tray() == 1
    assert "pystray" in capsys.readouterr().out


def test_main_install_login_declines_off_windows(monkeypatch, capsys):
    if sys.platform == "win32":
        pytest.skip("this asserts the off-Windows refusal")
    assert tray_windows.main(["--install-login"]) == 1
    out = capsys.readouterr().out
    assert "Windows-only" in out and "menubar" in out
