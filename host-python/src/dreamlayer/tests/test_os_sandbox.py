"""test_os_sandbox.py — the OS-sandbox wrapper around the subprocess plugin jail.

The wrapper is only *used* where bwrap/nsjail actually work; these pin the
construction logic (capability→network mapping, read-only binds) and the
graceful no-tool path, so it stays correct on hosts that do have the tools.
"""
from __future__ import annotations

from dreamlayer.plugins import os_sandbox


def test_no_tool_means_no_wrapper(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: None)
    assert os_sandbox.wrapper(["network"], "/tmp/x") == []


def test_bwrap_maps_the_network_capability(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: "bwrap")
    no_net = os_sandbox.wrapper([], "/tmp/pkg")
    with_net = os_sandbox.wrapper(["network"], "/tmp/pkg")
    assert no_net[0] == "bwrap"
    assert "--unshare-net" in no_net           # denied network → empty net namespace
    assert "--unshare-net" not in with_net     # granted network → net shared
    assert "--ro-bind-try" in no_net           # the package dir, read-only
    assert "--die-with-parent" in no_net       # child dies with the host


def test_nsjail_maps_the_network_capability(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: "nsjail")
    assert "--disable_clone_newnet" in os_sandbox.wrapper([], "/tmp/pkg")
    assert "--disable_clone_newnet" not in os_sandbox.wrapper(["network"], "/tmp/pkg")


def test_bwrap_clears_and_rebuilds_the_jail_environment(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: "bwrap")
    cmd = os_sandbox.wrapper([], "/tmp/pkg")

    assert "--clearenv" in cmd
    assert dict(os_sandbox._JAIL_ENV) == {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp",
    }
    for name, value in os_sandbox._JAIL_ENV:
        assert ["--setenv", name, value] in [
            cmd[i:i + 3] for i in range(len(cmd) - 2)]


def test_nsjail_rebuilds_the_jail_environment(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: "nsjail")
    cmd = os_sandbox.wrapper([], "/tmp/pkg")

    for name, value in os_sandbox._JAIL_ENV:
        assert ["--env", f"{name}={value}"] in [
            cmd[i:i + 2] for i in range(len(cmd) - 1)]


def test_dl_sandbox_none_disables(monkeypatch):
    monkeypatch.setenv("DL_SANDBOX", "none")
    os_sandbox._probe_cache.clear()
    assert os_sandbox.available() is None
    assert os_sandbox.wrapper([], "/tmp/pkg") == []


def test_describe_is_honest(monkeypatch):
    monkeypatch.setattr(os_sandbox, "available", lambda: None)
    assert os_sandbox.describe() == "os-sandbox: none (plain subprocess)"
    monkeypatch.setattr(os_sandbox, "available", lambda: "bwrap")
    assert "bwrap" in os_sandbox.describe()
