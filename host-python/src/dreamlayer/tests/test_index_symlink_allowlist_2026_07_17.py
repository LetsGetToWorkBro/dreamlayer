"""test_index_symlink_allowlist_2026_07_17.py — revert-failing test for the
per-FILE allow-list guard at the index walk sink (refute-remediation 2026-07-17).

store._is_allowed_root guards folder ROOTS, but FileIndex.reindex walks each
watched folder with rglob("*") and reads every text file it finds. A symlink
dropped inside an allow-listed folder can RESOLVE to a target OUTSIDE the user's
tree (~/watched/notes.txt -> /etc/passwd; .txt matches TEXT_EXTS), and the
root-level gate never sees that per-file swap (TOCTOU). The fix re-checks
_is_allowed_root (which resolve()s) on every walked path, so the escaping
symlink is skipped rather than ingested and surfaced via /brain/ask.

Revert-failing: drop the per-file _is_allowed_root check at the walk sink and the
symlink's target content lands in the index.
"""
from __future__ import annotations

import os

import pytest

from dreamlayer.ai_brain.server import store
from dreamlayer.ai_brain.server.index import FileIndex
from dreamlayer.ai_brain.server.store import BrainConfig


def _narrow_allowlist(tmp_path, monkeypatch):
    """Point HOME/USERPROFILE and the temp root at ``allowed/`` so ``outside/``
    is genuinely outside the allow-list (real HOME/tmp on CI both contain
    pytest's tmp_path, so the allow-list must be narrowed to tell a refused
    escape from an allowed one). Returns (allowed_dir, outside_dir)."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(allowed))            # POSIX Path.home()
    monkeypatch.setenv("USERPROFILE", str(allowed))     # Windows Path.home()
    monkeypatch.delenv("HOMEDRIVE", raising=False)       # don't let these override
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.setattr(store.tempfile, "gettempdir", lambda: str(allowed))
    return allowed, outside


class TestReindexSymlinkAllowlist:
    def test_symlink_escaping_allowlist_is_not_indexed(self, tmp_path, monkeypatch):
        allowed, outside = _narrow_allowlist(tmp_path, monkeypatch)

        # a readable secret OUTSIDE the allow-list — the symlink's real target
        secret = outside / "passwd.txt"
        secret.write_text("ROOTSECRET x:0:0:root:/root:/bin/sh")

        # the watched folder is allow-listed (under the narrowed HOME)
        watched = allowed / "watched"
        watched.mkdir()
        (watched / "notes.txt").write_text("LEGITNOTE the rent is 2400.")
        try:
            os.symlink(secret, watched / "escape.txt")   # resolves outside the tree
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable (Windows without privilege)")

        cfg = BrainConfig(folders=[str(watched)])
        idx = FileIndex(cfg)
        idx.reindex()

        blob = "\n".join(p for _, p in idx._passages)
        assert "LEGITNOTE" in blob          # the real sibling file IS indexed
        assert "ROOTSECRET" not in blob     # the escaping symlink is NOT
        assert "escape.txt" not in {name for name, _ in idx._passages}

    def test_symlink_to_allowed_target_is_still_indexed(self, tmp_path, monkeypatch):
        # A symlink whose target resolves INSIDE the allow-list stays indexed —
        # the guard refuses only escapes, so legitimate files behave identically.
        allowed, _ = _narrow_allowlist(tmp_path, monkeypatch)
        inside = allowed / "elsewhere"
        inside.mkdir()
        target = inside / "memo.txt"
        target.write_text("INSIDENOTE signed the lease.")

        watched = allowed / "watched"
        watched.mkdir()
        try:
            os.symlink(target, watched / "link.txt")     # resolves inside the tree
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable (Windows without privilege)")

        cfg = BrainConfig(folders=[str(watched)])
        idx = FileIndex(cfg)
        idx.reindex()

        blob = "\n".join(p for _, p in idx._passages)
        assert "INSIDENOTE" in blob         # an in-tree symlink target is read


class TestStateDirIsNeverIndexed:
    """FINDING 1 (privacy): the Brain's OWN state dir resolves UNDER home, so it
    passes _is_allowed_root — but brain_config.json holds the pairing token +
    provider API keys in clear and '.json' is a TEXT_EXTS. The index denylist
    (store._is_index_denied) must keep those secrets out of the index whether
    they're reached by a symlink or by adding the state dir as a watched folder,
    so they can never be recalled via /brain/ask. Revert-failing: drop the
    _is_index_denied guard at the walk sink and the token lands in a passage."""

    def test_symlink_into_state_dir_config_is_not_indexed(self, tmp_path,
                                                          monkeypatch):
        allowed, _ = _narrow_allowlist(tmp_path, monkeypatch)
        # the state dir lives under the (narrowed) HOME, so it is allow-listed;
        # only the denylist keeps its secret config out of the index.
        statedir = allowed / ".dreamlayer"
        statedir.mkdir()
        monkeypatch.setenv("DREAMLAYER_DIR", str(statedir))
        (statedir / "brain_config.json").write_text(
            '{"token": "PAIRSECRET-tok", "cloud_api_key": "sk-CLOUDKEY",'
            ' "api_key": "sk-PRIMARYKEY"}')

        watched = allowed / "watched"
        watched.mkdir()
        (watched / "notes.txt").write_text("LEGITNOTE the rent is 2400.")
        try:
            os.symlink(statedir / "brain_config.json", watched / "cfg.json")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable (Windows without privilege)")

        cfg = BrainConfig(folders=[str(watched)])
        idx = FileIndex(cfg)
        idx.reindex()

        blob = "\n".join(p for _, p in idx._passages)
        assert "LEGITNOTE" in blob          # the ordinary sibling IS indexed
        assert "PAIRSECRET" not in blob     # ...but the token is NOT
        assert "sk-CLOUDKEY" not in blob
        assert "sk-PRIMARYKEY" not in blob

    def test_adding_state_dir_as_watched_folder_indexes_no_secret(self, tmp_path,
                                                                  monkeypatch):
        allowed, _ = _narrow_allowlist(tmp_path, monkeypatch)
        statedir = allowed / ".dreamlayer"
        statedir.mkdir()
        monkeypatch.setenv("DREAMLAYER_DIR", str(statedir))
        (statedir / "brain_config.json").write_text('{"token": "PAIRSECRET-tok"}')

        cfg = BrainConfig(folders=[str(statedir)])
        idx = FileIndex(cfg)
        idx.reindex()

        blob = "\n".join(p for _, p in idx._passages)
        assert "PAIRSECRET" not in blob     # the whole state dir is denied
