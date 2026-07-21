"""In-app updater — download, verify, refuse. All seams injected; no network.

The updater is a supply-chain surface: these tests pin that nothing installs
without the API-declared sha256 matching the bytes, that unverifiable assets
are never picked at all, and that a bad download is deleted, not left around.
"""
from __future__ import annotations

import hashlib
import io

import pytest

from dreamlayer.ai_brain import updater


def _release(name="DreamLayer.dmg", data=b"dmg-bytes", digest=None, url=None):
    d = digest or "sha256:" + hashlib.sha256(data).hexdigest()
    return {"assets": [{
        "name": name, "digest": d, "size": len(data),
        "browser_download_url": url or f"https://github.com/x/y/releases/download/v1/{name}",
    }]}


class _Reader(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestPickAsset:
    def test_picks_the_platform_asset_with_its_digest(self):
        a = updater.pick_asset(_release(), platform="darwin")
        assert a and a["name"] == "DreamLayer.dmg" and len(a["sha256"]) == 64

    def test_windows_picks_the_installer(self):
        rel = _release(name="DreamLayer-Setup.exe")
        a = updater.pick_asset(rel, platform="win32")
        assert a and a["name"] == "DreamLayer-Setup.exe"

    def test_no_digest_means_no_install(self):
        # unverifiable bytes are never candidates — not even offered
        rel = _release(digest="md5:abc")
        assert updater.pick_asset(rel, platform="darwin") is None
        rel["assets"][0].pop("digest")
        assert updater.pick_asset(rel, platform="darwin") is None

    def test_non_https_url_is_refused(self):
        rel = _release(url="http://github.com/x/y/releases/download/v1/DreamLayer.dmg")
        assert updater.pick_asset(rel, platform="darwin") is None

    def test_unknown_platform_or_missing_asset_is_none(self):
        assert updater.pick_asset(_release(), platform="linux") is None
        assert updater.pick_asset({"assets": []}, platform="darwin") is None


class TestDownloadVerified:
    def test_good_bytes_land_and_progress_fires(self, tmp_path):
        data = b"x" * 700_000
        a = updater.pick_asset(_release(data=data), platform="darwin")
        ticks = []
        out = updater.download_verified(
            a, tmp_path, open_fn=lambda u, t: _Reader(data),
            progress=lambda done, total: ticks.append((done, total)))
        assert out.read_bytes() == data
        assert ticks and ticks[-1][0] == len(data)

    def test_tampered_bytes_are_deleted_not_installed(self, tmp_path):
        a = updater.pick_asset(_release(data=b"genuine"), platform="darwin")
        with pytest.raises(ValueError, match="sha256"):
            updater.download_verified(a, tmp_path,
                                      open_fn=lambda u, t: _Reader(b"evil"))
        assert not (tmp_path / "DreamLayer.dmg").exists()   # no residue

    def test_oversize_stream_is_cut_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater, "MAX_ASSET_BYTES", 1024)
        a = updater.pick_asset(_release(data=b"y" * 4096), platform="darwin")
        with pytest.raises(ValueError, match="size wall"):
            updater.download_verified(a, tmp_path,
                                      open_fn=lambda u, t: _Reader(b"y" * 4096))
        assert not (tmp_path / "DreamLayer.dmg").exists()


class TestPlatformGates:
    def test_gatekeeper_gate_reflects_spctl_verdict(self, tmp_path):
        f = tmp_path / "DreamLayer.dmg"; f.write_bytes(b"d")
        ok = lambda *a, **k: type("R", (), {"returncode": 0})()
        bad = lambda *a, **k: type("R", (), {"returncode": 3})()
        assert updater.gatekeeper_ok(f, run=ok) is True
        assert updater.gatekeeper_ok(f, run=bad) is False

    def test_authenticode_gate_requires_valid(self, tmp_path):
        f = tmp_path / "DreamLayer-Setup.exe"; f.write_bytes(b"e")
        valid = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "Valid"})()
        unsigned = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "NotSigned"})()
        assert updater.authenticode_ok(f, run=valid) is True
        assert updater.authenticode_ok(f, run=unsigned) is False

    def test_gates_fail_closed_when_the_tool_is_missing(self, tmp_path):
        f = tmp_path / "a"; f.write_bytes(b"z")
        boom = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
        assert updater.gatekeeper_ok(f, run=boom) is False
        assert updater.authenticode_ok(f, run=boom) is False
