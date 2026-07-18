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
    still evicting Users/Everyone. It runs on EVERY save (skipped on POSIX):
    save() writes a fresh mkstemp temp and os.replace()s it onto the target, and
    os.replace/MoveFileEx DISCARDS the destination DACL — the temp carries only
    the directory-inherited ACL — so the owner-only DACL must be re-applied each
    save or the very next save (e.g. pairing writing the token) reverts it to the
    inherited baseline (refute 2026-07-17: a create-only gate silently
    un-hardened the file). The nt-gated test parses the real DACL after a save
    AND a re-save, and a wiring test confirms the hardener runs on every save
    with the final target path.
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

def test_save_hardens_acl_on_every_save(tmp_path, monkeypatch):
    # cross-platform wiring + revert guard: save() writes a fresh mkstemp temp
    # and os.replace()s it onto the target, which on Windows (MoveFileExW) makes
    # the temp BECOME the target and DISCARDS the explicit owner-only DACL — the
    # temp only ever carried the directory-inherited ACL. So the hardener MUST
    # run on EVERY save (create AND every overwrite) with the final target path,
    # or the owner-only ACL is lost on the very next save (e.g. pairing writing
    # the token). A create-only gate silently un-hardened the file (refute
    # 2026-07-17). On POSIX the hardener is a no-op, but this is the exact wiring
    # that runs (and matters) on the Windows leg.
    cfg = tmp_path / "cfg"
    d = str(cfg)
    target = str(cfg / store.CONFIG_FILE)
    calls: list[str] = []
    monkeypatch.setattr(store, "_harden_windows_acl", lambda p: calls.append(p))

    # every save hardens the DIRECTORY first (so the temp/target are born private
    # by inheritance), then the FINAL target file after the atomic swap.
    BrainConfig(token="tok").save(cfg)
    assert calls == [d, target]

    # a second save re-hardens BOTH again, because os.replace discarded the file
    # DACL and the dir harden is re-asserted every save too.
    BrainConfig(token="tok2", api_key="k").save(cfg)
    assert calls == [d, target, d, target]

    # a third save — pin that it's genuinely every save, not merely twice
    BrainConfig(token="tok3").save(cfg)
    assert calls == [d, target] * 3


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
    # to exactly the current user + SYSTEM + Administrators (item 1/5) — and,
    # the coverage the create-only-gate bug slipped through, that the owner-only
    # DACL STILL holds after a RE-SAVE. os.replace/MoveFileEx makes a fresh
    # mkstemp temp BECOME the target and discards its explicit DACL (the temp
    # only carried the inherited ACL), so the hardener must re-apply on every
    # save or the second save leaves the config at the inherited baseline.
    cfg = tmp_path / "cfg"
    target = cfg / store.CONFIG_FILE

    import getpass
    sid = store._current_user_sid() or ""
    user = getpass.getuser()

    def assert_owner_only():
        out = subprocess.run(["icacls", str(target)],
                             capture_output=True, text=True).stdout

        # /inheritance:r removed inherited ACEs — none of the "(I)" inherited
        # flags should remain in the listing.
        assert "(I)" not in out, out
        # NO broadly-scoped principal may appear in the hardened DACL — the whole
        # point is other regular users (Users/Everyone) can no longer read it.
        for broad in ("Everyone", "Authenticated Users",
                      "BUILTIN\\Users", "\\Users:"):
            assert broad not in out, f"{broad!r} unexpectedly in DACL:\n{out}"

        # SYSTEM and Administrators are re-granted alongside the user (well-known
        # SIDs S-1-5-18 / S-1-5-32-544), so stripping inheritance didn't lock out
        # AV/backup/OS agents. They resolve to names, but tolerate raw-SID.
        assert ("NT AUTHORITY\\SYSTEM" in out) or ("S-1-5-18" in out), out
        assert ("Administrators" in out) or ("S-1-5-32-544" in out), out

        # the current user IS granted (by resolved account name or by SID)
        assert (sid and sid in out) or (user and user in out), out

        # every surviving ACE is Full control (":(F)"), matching the three grants
        assert ":(F)" in out, out

    # first save creates the file → owner-only DACL is set
    BrainConfig(token="tok", cloud_api_key="ck", api_key="ak").save(cfg)
    assert_owner_only()

    # a SECOND save overwrites target via os.replace (which discards its DACL);
    # the owner-only ACL must be RE-APPLIED, so the DACL STILL holds after it.
    BrainConfig(token="tok2", cloud_api_key="ck2", api_key="ak2").save(cfg)
    assert_owner_only()


def test_owner_only_icacls_argv_is_inheritance_stripped_and_narrow():
    # Cross-platform guard on the exact DACL shape (the nt-only test can't run on
    # Linux CI): inheritance stripped, Full control to EXACTLY current-user +
    # SYSTEM + Administrators, NO broad principal. A revert that drops
    # /inheritance:r, reorders/breaks the grant, or adds a broad principal
    # (Everyone S-1-1-0, Users) fails HERE, on every platform.
    argv = store._owner_only_icacls_argv("C:\\state\\brain_config.json",
                                         "S-1-5-21-TEST-1001")
    assert argv is not None
    assert argv[0] == "icacls"
    assert argv[1] == "C:\\state\\brain_config.json"
    assert "/inheritance:r" in argv
    grants = {a for a in argv if a.startswith("*")}
    assert grants == {"*S-1-5-18:F", "*S-1-5-32-544:F", "*S-1-5-21-TEST-1001:F"}
    joined = " ".join(argv)
    for broad in ("S-1-1-0", "*S-1-1-0", ":(OI)", "Everyone", "Users", "BU"):
        assert broad not in joined, f"{broad!r} unexpectedly in argv: {argv}"


def test_owner_only_icacls_argv_fails_closed_on_missing_sid():
    # No user SID → return None so the caller SKIPS hardening entirely (leaving
    # the — separately hardened — dir-inherited baseline). It must NEVER fall
    # back to a broad grant. A revert that emitted an argv on a missing SID fails.
    assert store._owner_only_icacls_argv("C:\\x", None) is None
    assert store._owner_only_icacls_argv("C:\\x", "") is None


@posix_only
def test_state_dir_is_owner_only_on_posix(tmp_path):
    # On POSIX the state dir must be chmod 0o700 so a $DREAMLAYER_DIR placed under
    # a world-readable parent (e.g. a shared /tmp) doesn't leak the secrets via
    # the directory's mode.
    cfg = tmp_path / "cfg"
    BrainConfig(token="tok").save(cfg)
    assert (cfg.stat().st_mode & 0o777) == 0o700
