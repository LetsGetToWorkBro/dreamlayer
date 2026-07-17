"""test_config_perms.py — secret-at-rest hardening for brain_config.json.

brain_config.json persists the pairing token AND both provider API keys
(cloud_api_key / api_key) in cleartext (store.BrainConfig). These tests pin the
three-part hardening of BrainConfig.save():

  * FIX 3 — the 0o600 fix shipped with NO regression test. On POSIX the saved
    config must be mode 0o600 (owner-only), never group/world readable, and it
    must actually hold the secrets. Reverting the O_CREAT-0o600 / re-assert
    chmod widens the mode to the 0o644 umask default and fails
    test_saved_config_is_mode_0600_and_holds_secrets.

  * FIX 2 — the temp is now a per-writer UNIQUE tempfile.mkstemp (O_EXCL, mode
    0o600) instead of a fixed shared "<config>.tmp" reopened without O_EXCL. A
    stale world-readable tmp left by a crash/old build can no longer be
    reopen-truncated into leaking the fresh secrets through a 0o644 handle.

  * FIX 1 — on Windows chmod(0o600) only toggles the read-only bit and sets NO
    ACL, so save() adds an owner-only ACL step: strip inheritance, then grant
    Full control to the current user PLUS the locale/domain-independent
    well-known SIDs S-1-5-18 (LocalSystem) and S-1-5-32-544 (Administrators) —
    so stripping inheritance doesn't lock out AV/backup/OS-agent readers while
    still evicting Users/Everyone. It runs only when the config is first created
    (the DACL persists across the atomic in-place re-saves), and is skipped on
    POSIX; the nt-gated test parses the real DACL and a wiring test confirms the
    create-runs / unchanged-resave-skips gating.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import stat
import subprocess
import threading
import time

import pytest

from dreamlayer.ai_brain.server import store
from dreamlayer.ai_brain.server import BrainConfig


posix_only = pytest.mark.skipif(os.name == "nt",
                                reason="POSIX file-mode semantics")


# -- FIX 3: the saved config is owner-only and actually holds the secrets ------

@posix_only
def test_saved_config_is_mode_0600_and_holds_secrets(tmp_path):
    cfg = tmp_path / "cfg"
    BrainConfig(token="pair-secret",
                cloud_api_key="sk-cloud-xyz",
                api_key="sk-primary-abc").save(cfg)
    target = cfg / store.CONFIG_FILE
    assert target.exists()

    # exactly owner rw, nothing else — reverting the 0o600 fix fails HERE
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    # and, said the other way: NOT one bit of group/world access
    assert not (target.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))

    # the file really is the cleartext secret store we just hardened
    data = json.loads(target.read_text())
    assert data["token"] == "pair-secret"
    assert data["cloud_api_key"] == "sk-cloud-xyz"
    assert data["api_key"] == "sk-primary-abc"


@posix_only
def test_resave_over_existing_config_stays_0600(tmp_path):
    # a second save (overwriting the target) must not widen the mode back out
    cfg = tmp_path / "cfg"
    BrainConfig(token="a").save(cfg)
    BrainConfig(token="b", api_key="k").save(cfg)
    target = cfg / store.CONFIG_FILE
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["token"] == "b"


# -- FIX 2: the temp is unique + private from birth, never a shared 0644 name --

@posix_only
def test_temp_is_private_from_birth_and_not_the_stale_shared_name(tmp_path,
                                                                  monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # a crash / old build could leave a WORLD-READABLE file at the OLD fixed
    # temp name. The pre-fix code reopened+truncated exactly this path, writing
    # the fresh secrets through a 0o644 handle mid-save.
    stale = cfg / (store.CONFIG_FILE + ".tmp")
    stale.write_text("{}")
    os.chmod(stale, 0o644)

    seen: dict = {}
    real_replace = store.replace_atomic

    def spy_replace(src, dst, *a, **k):
        seen["src"] = str(src)
        seen["mode"] = os.stat(src).st_mode & 0o777
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store, "replace_atomic", spy_replace)

    BrainConfig(token="tok", api_key="k").save(cfg)

    # the file actually swapped in was private (0o600) BEFORE it held secrets…
    assert seen["mode"] == 0o600
    # …and it was a fresh unique temp, NOT the stale world-readable shared name
    assert seen["src"] != str(stale)

    target = cfg / store.CONFIG_FILE
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["api_key"] == "k"


def test_no_leftover_temp_after_save(tmp_path):
    # the unique temp is renamed onto the target; our writer leaves nothing
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    BrainConfig(token="tok").save(cfg)
    assert list(cfg.glob(store.CONFIG_FILE + ".*")) == []


# -- FINDING 3: a crash-orphaned UNIQUE temp is reaped by the next save --------

def test_stale_tmp_orphan_is_reaped_on_save(tmp_path):
    # FIX 2 made the temp a per-writer UNIQUE name, which no longer self-limits
    # the way the old fixed "<config>.tmp" did: a hard crash between mkstemp and
    # replace leaves "<config>.<rand>.tmp" that nothing ever reuses, so orphans
    # would accumulate forever. The next save must sweep such stale temps.
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    orphan = cfg / (store.CONFIG_FILE + ".deadbeef.tmp")
    orphan.write_text("{}")
    old = time.time() - 3600                       # a crash from a while ago
    os.utime(orphan, (old, old))
    assert orphan.exists()

    BrainConfig(token="tok").save(cfg)

    assert not orphan.exists()                     # reaped
    assert list(cfg.glob(store.CONFIG_FILE + ".*")) == []


def test_reap_spares_a_concurrent_writers_fresh_temp(tmp_path):
    # age-gated: a just-created temp (a concurrent saver's in-flight file) must
    # NOT be yanked out from under its own replace — only aged orphans go.
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    fresh = cfg / (store.CONFIG_FILE + ".inflight.tmp")
    fresh.write_text("{}")                         # mtime = now → too young

    BrainConfig(token="tok").save(cfg)

    assert fresh.exists()                          # spared


# -- FINDING 2: an unreadable config falls back to defaults, never crashes -----

def test_load_of_unreadable_config_falls_back_to_defaults(tmp_path, monkeypatch,
                                                          caplog):
    # a config the new owner-only ACL / a bad mode made unreadable to THIS
    # process raises PermissionError on read. load() must degrade to defaults
    # (not crash, and not silently keep the wearer out of Incognito).
    cfg = tmp_path / "cfg"
    BrainConfig(token="pair-secret", network_mode="lan_only",
                folders=[str(tmp_path)]).save(cfg)

    real_read_text = pathlib.Path.read_text

    def boom(self, *a, **k):
        if self.name == store.CONFIG_FILE:
            raise PermissionError("owner-only ACL denies this process")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", boom)

    with caplog.at_level(logging.WARNING):
        loaded = BrainConfig.load(cfg)             # must not raise

    # DEFAULTS, not the persisted secret config
    assert loaded.token == ""
    assert loaded.network_mode == "connected"
    assert loaded.folders == []
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_load_of_missing_config_is_defaults_and_silent(tmp_path, caplog):
    # the common first-run path (no file yet) still returns defaults with no
    # WARNING — a missing config is not an error.
    cfg = tmp_path / "cfg"
    with caplog.at_level(logging.WARNING):
        loaded = BrainConfig.load(cfg)
    assert loaded.token == "" and loaded.network_mode == "connected"
    assert not any(r.levelname == "WARNING" for r in caplog.records)


@posix_only
def test_concurrent_saves_never_collide_or_widen_mode(tmp_path):
    # unique per-writer temps mean 8 threads can't clobber one shared tmp; the
    # final file is always complete JSON at 0o600, with no orphaned temps.
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    errors: list[str] = []

    def worker(i):
        try:
            for _ in range(20):
                BrainConfig(token=f"t{i}", api_key=f"k{i}").save(cfg)
        except Exception as exc:                       # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    target = cfg / store.CONFIG_FILE
    assert target.stat().st_mode & 0o777 == 0o600
    json.loads(target.read_text())                     # never torn
    assert list(cfg.glob(store.CONFIG_FILE + ".*")) == []


# -- FIX 1: the Windows owner-only ACL step ------------------------------------

def test_save_hardens_acl_on_create_but_skips_unchanged_resave(tmp_path,
                                                               monkeypatch):
    # cross-platform wiring + item 3: the ACL hardener shells icacls and does a
    # token lookup, so save() must run it ONLY when it would change something —
    # on the first create of the file — and SKIP it on a later re-save that
    # overwrites an already-hardened target (the owner-only DACL persists across
    # the atomic in-place replace). On POSIX the hardener is a no-op, but this is
    # the exact gating that runs (and matters) on the Windows leg.
    cfg = tmp_path / "cfg"
    calls: list[str] = []
    monkeypatch.setattr(store, "_harden_windows_acl", lambda p: calls.append(p))

    # first save creates the file → hardener runs with the FINAL target path
    BrainConfig(token="tok").save(cfg)
    assert calls == [str(cfg / store.CONFIG_FILE)]

    # a second save overwrites the existing target → hardener is NOT re-run
    BrainConfig(token="tok2", api_key="k").save(cfg)
    assert calls == [str(cfg / store.CONFIG_FILE)]   # still just the one create


@posix_only
def test_harden_windows_acl_is_a_noop_on_posix(tmp_path):
    # explicit contract: on POSIX the hardener returns without touching the file
    # or raising — it must never shell out to icacls (absent here).
    f = tmp_path / "secret.json"
    f.write_text("x")
    os.chmod(f, 0o600)
    store._harden_windows_acl(str(f))                  # must not raise
    assert f.stat().st_mode & 0o777 == 0o600           # unchanged


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL semantics")
def test_windows_config_acl_is_owner_only(tmp_path):
    # runs only on test-windows: prove the ACL step actually reshaped the real
    # DACL — inheritance disabled, no broad principal, and Full control granted
    # to exactly the current user + SYSTEM + Administrators (item 1/5).
    cfg = tmp_path / "cfg"
    BrainConfig(token="tok", cloud_api_key="ck", api_key="ak").save(cfg)
    target = cfg / store.CONFIG_FILE

    out = subprocess.run(["icacls", str(target)],
                         capture_output=True, text=True).stdout

    # /inheritance:r removed inherited ACEs — none of the "(I)" inherited flags
    # should remain in the listing.
    assert "(I)" not in out, out
    # NO broadly-scoped principal may appear in the hardened DACL — the whole
    # point is that other regular users (Users/Everyone) can no longer read it.
    for broad in ("Everyone", "Authenticated Users",
                  "BUILTIN\\Users", "\\Users:"):
        assert broad not in out, f"{broad!r} unexpectedly still in DACL:\n{out}"

    # SYSTEM and Administrators are re-granted alongside the user (well-known
    # SIDs S-1-5-18 / S-1-5-32-544), so stripping inheritance didn't lock out
    # AV/backup/OS agents. They resolve to names, but tolerate raw-SID display.
    assert ("NT AUTHORITY\\SYSTEM" in out) or ("S-1-5-18" in out), out
    assert ("Administrators" in out) or ("S-1-5-32-544" in out), out

    # the current user IS granted (by resolved account name or by SID)
    import getpass
    sid = store._current_user_sid() or ""
    user = getpass.getuser()
    assert (sid and sid in out) or (user and user in out), out

    # every surviving ACE is Full control (":(F)"), matching the three grants
    assert ":(F)" in out, out
