"""updater.py — download-and-install updates from inside the app.

"Check for updates" used to end at the GitHub Releases PAGE; this module
finishes the job in-app: pick the platform asset off the release the existing
click-only check found, download it with progress, verify it, and install.

Trust model (an updater is a supply-chain surface, so every hop is checked):
  * the release lookup rides the same click-only fetch as check_for_update —
    never polled in the background, never while the egress shield would deny
    an explicit user action;
  * the downloaded bytes must match the sha256 **digest the release API
    declares** for the asset (GitHub computes it at upload) — a mismatch
    deletes the file and fails loudly;
  * macOS: the .dmg must then pass Gatekeeper assessment (`spctl` — Developer
    ID signature + notarization) before it is ever mounted;
  * Windows: the installer must carry a valid Authenticode signature before
    it is ever launched (skippable only for the known-unsigned pre-release
    builds, and then said plainly to the caller);
  * the version compare in check_for_update already refuses downgrades.

Every network/process touch is an injectable seam so the suite runs offline.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# The asset each platform installs, exactly as build-macos-app.yml /
# build-windows-app.yml publish them.
ASSET_BY_PLATFORM = {
    "darwin": "DreamLayer.dmg",
    "win32": "DreamLayer-Setup.exe",
}

MAX_ASSET_BYTES = 500 * 1024 * 1024      # hard wall far above any real build
_CHUNK = 256 * 1024


def pick_asset(release: dict, platform: str | None = None) -> Optional[dict]:
    """The release asset this platform installs: {name, url, sha256, size}.
    None when the release carries no asset for this platform (source-only
    releases exist) or the API gave no digest (never install unverifiable
    bytes)."""
    want = ASSET_BY_PLATFORM.get(platform or sys.platform)
    if not want:
        return None
    for a in release.get("assets") or []:
        if a.get("name") != want:
            continue
        digest = str(a.get("digest") or "")
        if not digest.startswith("sha256:"):
            return None                   # no declared digest → no install
        url = str(a.get("browser_download_url") or "")
        # pinned to THIS repo's release downloads — a manipulated release JSON
        # must not be able to point the download anywhere else (refute A1-2)
        if not url.startswith(
                "https://github.com/LetsGetToWorkBro/dreamlayer/releases/download/"):
            return None
        return {"name": want, "url": url,
                "sha256": digest.split(":", 1)[1].lower(),
                "size": int(a.get("size") or 0)}
    return None


def _default_open(url: str, timeout: float):
    """Stream-open the asset URL. GitHub asset downloads redirect to the
    objects CDN, so redirects are allowed here — integrity comes from the
    sha256 check against the API-declared digest, not the transport path."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "DreamLayer-updater"})
    return urllib.request.build_opener().open(req, timeout=timeout)


def download_verified(asset: dict, dest_dir: Path | str | None = None,
                      open_fn: Callable = _default_open,
                      progress: Optional[Callable[[int, int], None]] = None,
                      timeout: float = 60.0) -> Path:
    """Download the asset and verify its sha256 against the API-declared
    digest. Returns the verified file path; raises ValueError on any
    mismatch/overrun (deleting the partial file first). ``progress(done,
    total)`` fires per chunk for a UI meter."""
    dest_dir = Path(dest_dir or tempfile.mkdtemp(prefix="dreamlayer-update-"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / asset["name"]
    total = int(asset.get("size") or 0)
    h = hashlib.sha256()
    done = 0
    try:
        with open_fn(asset["url"], timeout) as r, open(out, "wb") as f:
            while True:
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_ASSET_BYTES:
                    raise ValueError("update download exceeded the size wall")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(done, total)
    except Exception:
        out.unlink(missing_ok=True)
        raise
    if h.hexdigest().lower() != asset["sha256"]:
        out.unlink(missing_ok=True)
        raise ValueError("update failed its sha256 check — refusing to install")
    return out


def gatekeeper_ok(dmg: Path, run: Callable = subprocess.run) -> bool:
    """macOS: True only when Gatekeeper accepts the dmg (Developer ID +
    notarization) — checked BEFORE the image is ever mounted."""
    try:
        res = run(["spctl", "-a", "-t", "open", "--context",
                   "context:primary-signature", str(dmg)],
                  capture_output=True, timeout=60)
        return res.returncode == 0
    except Exception:
        return False


def authenticode_ok(exe: Path, run: Callable = subprocess.run) -> bool:
    """Windows: True only when the installer carries a Valid Authenticode
    signature (checked before it is ever launched)."""
    try:
        res = run(["powershell", "-NoProfile", "-Command",
                   f"(Get-AuthenticodeSignature '{exe}').Status"],
                  capture_output=True, timeout=60, text=True)
        return res.returncode == 0 and (res.stdout or "").strip() == "Valid"
    except Exception:
        return False


def install_macos(dmg: Path, app_dir: str = "/Applications",
                  run: Callable = subprocess.run) -> bool:
    """Mount the verified dmg, swap DreamLayer.app into /Applications, unmount,
    relaunch the new copy. Returns False (leaving the old app untouched) on
    any step failing — a botched update must never eat the working install."""
    if not gatekeeper_ok(dmg, run=run):
        return False                      # the gate is code, not convention (A3-5)
    mount = None
    try:
        res = run(["hdiutil", "attach", "-nobrowse", "-readonly", str(dmg)],
                  capture_output=True, timeout=120, text=True)
        if res.returncode != 0:
            return False
        for line in (res.stdout or "").splitlines():
            if "/Volumes/" in line:
                mount = line.split("\t")[-1].strip()
        if not mount:
            return False
        src = Path(mount) / "DreamLayer.app"
        dst = Path(app_dir) / "DreamLayer.app"
        # ditto to a staging sibling, then swap — never a half-copied bundle
        stage = dst.with_name("DreamLayer.app.update")
        if run(["ditto", str(src), str(stage)], capture_output=True,
               timeout=600).returncode != 0:
            run(["rm", "-rf", str(stage)], capture_output=True, timeout=120)
            return False
        # swap with rollback (refute A3-1/A3-2): park the old bundle, move the
        # new one in; on failure put the old one back. The old app is deleted
        # LAST, only after the new one is in place — never rm-then-hope.
        old = dst.with_name("DreamLayer.app.old")
        run(["rm", "-rf", str(old)], capture_output=True, timeout=120)
        had_old = dst.exists()
        if had_old and run(["mv", str(dst), str(old)], capture_output=True,
                           timeout=120).returncode != 0:
            run(["rm", "-rf", str(stage)], capture_output=True, timeout=120)
            return False
        if run(["mv", str(stage), str(dst)], capture_output=True,
               timeout=120).returncode != 0:
            if had_old:
                run(["mv", str(old), str(dst)], capture_output=True, timeout=120)
            return False
        run(["rm", "-rf", str(old)], capture_output=True, timeout=120)
        run(["open", "-n", str(dst)], capture_output=True, timeout=60)
        return True
    finally:
        if mount:
            run(["hdiutil", "detach", mount], capture_output=True, timeout=120)


def install_windows(exe: Path, start: Optional[Callable] = None) -> bool:
    """Launch the verified installer (per-user, no admin prompt) and let it
    take over; the caller exits the running app."""
    try:
        if not authenticode_ok(exe):
            return False                  # the gate is code, not convention (A3-5)
        if start is None:
            import os
            start = os.startfile            # type: ignore[attr-defined]
        start(str(exe))
        return True
    except Exception:
        return False


def is_upgrade(latest_tag: str, current: str) -> bool:
    """Install-time downgrade refusal (refute A4): True ONLY when latest_tag
    parses and is strictly newer than current. Uncomparable tags refuse —
    check_for_update may OFFER them for a human to inspect, but nothing
    auto-installs a version it cannot compare."""
    from .menubar import _parse_version
    lv, cv = _parse_version(latest_tag), _parse_version(current)
    if lv is None or cv is None:
        return False
    return lv > cv


def perform_update(current: str | None = None, fetch_fn=None,
                   platform: str | None = None,
                   progress: Optional[Callable[[int, int], None]] = None,
                   download=None, install=None) -> tuple:
    """The whole in-app update, end to end: fetch the latest release (the same
    click-only fetch check_for_update uses), refuse non-upgrades, pick the
    platform asset, download + digest-verify, then install behind the platform
    signature gate. Returns (ok, message). Every step injectable for offline
    tests; any failure returns a plain-English reason so the caller can fall
    back to opening the Releases page."""
    import json as _json
    from .menubar import RELEASES_API, _default_update_fetch, current_version
    cur = current or current_version()
    fetch = fetch_fn or _default_update_fetch
    try:
        release = _json.loads(fetch(RELEASES_API, 10.0))
    except Exception:
        return False, "couldn't reach the release feed"
    tag = str(release.get("tag_name") or "")
    if not is_upgrade(tag, cur):
        return False, f"no upgrade (running {cur}, latest {tag or 'unknown'})"
    asset = pick_asset(release, platform=platform)
    if asset is None:
        return False, "this release has no verifiable installer for this machine"
    try:
        path = (download or download_verified)(asset, progress=progress)
    except Exception as exc:
        return False, f"download failed verification: {exc}"
    plat = platform or sys.platform
    installer = install or (install_macos if plat == "darwin" else install_windows)
    if not installer(path):
        return False, ("the installer didn't pass its signature gate or the "
                       "swap failed — nothing was changed")
    return True, f"updated to {tag} — restarting"
