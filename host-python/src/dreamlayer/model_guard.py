"""model_guard.py — ML-model supply-chain integrity + offline-posture fetch gate.

Every code scanner in this repo (Semgrep, gitleaks, cargo-audit, pip-audit) reads
*source*. But the Brain's real trusted-input surface is its ML **weights**, pulled
from public CDNs — HuggingFace hub, the ultralytics GitHub CDN, torch.hub — and
several formats (`.pt`, speechbrain/pyannote checkpoints) are Python **pickle**:
loading one is arbitrary code execution the scanners can't see, because the
payload is *data*, not code. A swapped or MITM'd weight file is an RCE that ships
straight past the whole toolchain. Nothing here checked that today (the recon
found zero offline flags, zero checksums, zero `weights_only` guards anywhere).

Three layered controls, all dependency-light and fail-safe:

1. **Offline-by-default posture gate.** HuggingFace, transformers,
   sentence-transformers, faster-whisper, speechbrain, open_clip and diart honor
   the env flags ``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE``.
   :func:`apply_offline_posture` sets them process-wide from the wearer's posture.
   Because those libs read the flag into an import-time constant, the flag is set
   as early as ``import dreamlayer`` when ``DL_MODELS_OFFLINE`` is exported, and a
   loader additionally passes ``local_files_only`` per-call (the reliable lever
   for a runtime posture change). Loaders that do NOT honor those env flags —
   ultralytics and ``torch.hub``, which fetch from their own CDNs — must call
   :func:`require_fetch_allowed` to refuse a download while offline. First-run
   bootstrap (``dreamlayer setup models``) is the one sanctioned fetch window.

2. **Pinned integrity.** ``models.lock`` is a sha256 manifest of the trusted
   weight files. :func:`verify_path` / :func:`verify_tree` check on-disk bytes
   against the lock *before* they are trusted; a mismatch raises
   :class:`ModelIntegrityError`. An unpinned model warns, or hard-fails under
   ``DL_MODELS_STRICT=1``.

3. **No-pickle-RCE default.** :func:`safe_torch_load` forces
   ``weights_only=True`` and :func:`prefer_safetensors` reports when a
   safetensors sibling should win — so even attacker-controlled bytes cannot
   execute on load, on any torch version.

Fail-safe throughout: the guard NEVER makes a load path *fail open*. A missing
lock, an unreadable file, or a torch too old for ``weights_only`` degrades to a
logged warning (or a hard error under strict mode), never a silent trust.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("dreamlayer.model_guard")

LOCK_FILENAME = "models.lock"

# The env flags every HuggingFace-stack loader consults. Setting these is the
# single lever that turns off ALL model egress at once.
_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}


class ModelIntegrityError(Exception):
    """On-disk model bytes do not match the pinned sha256 in models.lock."""


class ModelFetchBlocked(RuntimeError):
    """A model download was requested while the wearer's posture forbids it."""


# -- the lock manifest --------------------------------------------------------
def _default_lock_path() -> Path:
    return Path(__file__).with_name(LOCK_FILENAME)


def load_lock(path: Optional[Path | str] = None) -> dict:
    """Read models.lock. Returns ``{}`` (not an error) when it is absent or
    malformed — the guard then treats every model as *unpinned* and warns,
    rather than blocking loads on a missing manifest."""
    p = Path(path) if path is not None else _default_lock_path()
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[model_guard] no usable %s (%s); models are unpinned", p.name, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def known_models(lock: Optional[dict] = None) -> dict:
    lock = lock if lock is not None else load_lock()
    models = lock.get("models")
    return models if isinstance(models, dict) else {}


# -- hashing + verification ---------------------------------------------------
def sha256_file(path: Path | str, _bufsize: int = 1 << 20) -> str:
    """Streaming sha256 of a file — never loads the whole (multi-GB) weight into
    memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def _strict_default() -> bool:
    return os.environ.get("DL_MODELS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")


def verify_file(path: Path | str, expected_sha256: str) -> bool:
    """True iff *path* hashes to *expected_sha256*. Raises ModelIntegrityError on
    a mismatch (a present-but-wrong file is tampering) OR when a pinned file is
    missing/unreadable — so a caller only ever has to catch ModelIntegrityError,
    never a bare OSError (refute 2026-07-18: verify_all leaked FileNotFoundError)."""
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise ModelIntegrityError(f"cannot read pinned model file {path}: {exc}") from exc
    if actual.lower() != str(expected_sha256).lower():
        raise ModelIntegrityError(
            f"integrity check FAILED for {path}: expected {expected_sha256}, got {actual}")
    return True


def verify_tree(root: Path | str, files: dict) -> bool:
    """Verify a set of ``{relpath: sha256}`` under *root*. A pinned file that is
    missing is a failure; an empty pin set means 'unpinned' and returns False."""
    root = Path(root).resolve()
    if not files:
        return False
    for rel, expected in files.items():
        fp = (root / rel).resolve()
        # containment: models.lock is the trust anchor this feature introduces, so
        # a relpath of '../..' or an absolute path must not escape the model dir.
        if fp != root and not fp.is_relative_to(root):
            raise ModelIntegrityError(f"pinned model path escapes its root: {rel!r}")
        if not fp.exists():
            raise ModelIntegrityError(f"pinned model file missing: {fp}")
        verify_file(fp, expected)
    return True


def verify_path(model_id: str, path: Path | str, *,
                lock: Optional[dict] = None, strict: Optional[bool] = None) -> bool:
    """Verify an on-disk model *path* against its models.lock pin.

    Returns True when it verifies, False when the model is *unpinned* (no sha256
    in the lock yet) — in which case it warns, or raises ModelIntegrityError if
    strict mode is on (arg, else ``DL_MODELS_STRICT``). Raises ModelIntegrityError
    on a genuine hash mismatch regardless of strictness: a wrong file is never
    tolerated.
    """
    strict = _strict_default() if strict is None else strict
    entry = known_models(lock).get(model_id) or {}
    files = entry.get("files") if isinstance(entry, dict) else None
    single = entry.get("sha256") if isinstance(entry, dict) else None

    if files:
        return verify_tree(path, files)
    if single:
        return verify_file(path, single)

    # unpinned: infrastructure is in place, this model just has no hash yet.
    msg = (f"[model_guard] {model_id!r} is UNPINNED in {LOCK_FILENAME} — loading "
           f"unverified bytes from {path}")
    if strict:
        raise ModelIntegrityError(msg + " (DL_MODELS_STRICT is set)")
    log.warning(msg)
    return False


# -- posture-gated fetch ------------------------------------------------------
def posture_allows_fetch(posture=None) -> bool:
    """Decide whether model *downloads* are permitted for the given posture.

    Accepts, duck-typed: a Brain-like object (``incognito_now()`` and/or a
    ``config.network_mode``/``lan_only``), a BrainConfig-like object, a bare
    string ("connected"/"lan_only"/"incognito"/"offline"), or None. Offline,
    incognito, and LAN-only all forbid fetch; the product-default "connected"
    posture allows it. Fail-safe: an unrecognised value forbids fetch (better a
    blocked first-run than a silent CDN reach while the wearer thinks they are
    offline)."""
    if posture is None:
        # No posture supplied → honour an explicit operator override, else allow
        # (the connected product default; first-run bootstrap needs to fetch).
        env = os.environ.get("DL_MODELS_OFFLINE", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            return False
        return True
    if isinstance(posture, str):
        return posture.strip().lower() in ("connected", "online", "")
    # object: incognito wins, then network_mode/lan_only
    inc = getattr(posture, "incognito_now", None)
    try:
        if callable(inc) and inc():
            return False
    except Exception:
        return False
    cfg = getattr(posture, "config", posture)
    if getattr(cfg, "lan_only", False):
        return False
    mode = getattr(cfg, "network_mode", "connected")
    return str(mode).strip().lower() == "connected"


def offline_env(allow_fetch: bool) -> dict:
    """The env vars to *set* for this fetch decision. Empty when fetch is allowed
    (we never force offline on the connected default)."""
    return {} if allow_fetch else dict(_OFFLINE_ENV)


# The live process-wide fetch decision, updated by apply_offline_posture, so a
# loader can consult it via require_fetch_allowed() with no posture in hand.
_FETCH_ALLOWED = True
# Marker prefix recording the operator's ORIGINAL value of a flag before we
# overrode it, so going back online restores it EXACTLY (a "\0" value means the
# flag was originally unset). Stored in the env (not a module global) so it is
# naturally scoped and test-isolated via monkeypatch.
_ORIG_PREFIX = "_DL_ORIG_"
_UNSET = "__DL_UNSET__"     # a value no operator would set a flag to (not "\0" — env vars can't hold NUL)


def apply_offline_posture(posture=None, *, allow_fetch: Optional[bool] = None) -> dict:
    """Set (or clear) the process-wide offline flags to match posture.

    When fetch is forbidden, ``HF_HUB_OFFLINE`` &co are set to "1" so every
    hub-backed loader in the process refuses to reach a CDN. When it is allowed we
    restore each flag to the operator's EXACT original value (including an explicit
    ``=0`` or an unset), never leaving our "1" stuck (refute 2026-07-18: a non-"1"
    operator export was overwritten to "1" and never restored). Returns the
    applied env dict. Idempotent; safe to call on every posture change."""
    global _FETCH_ALLOWED
    fetch = allow_fetch if allow_fetch is not None else posture_allows_fetch(posture)
    _FETCH_ALLOWED = fetch
    if fetch:
        for k in _OFFLINE_ENV:
            marker = _ORIG_PREFIX + k
            if marker in os.environ:
                orig = os.environ.pop(marker)
                if orig == _UNSET:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = orig       # restore the operator's exact value
    else:
        for k, v in _OFFLINE_ENV.items():
            marker = _ORIG_PREFIX + k
            if marker not in os.environ:        # remember the original ONCE
                os.environ[marker] = os.environ.get(k, _UNSET)
            os.environ[k] = v
        log.info("[model_guard] offline posture: model downloads disabled (HF_HUB_OFFLINE=1)")
    return offline_env(fetch)


@contextlib.contextmanager
def offline_guard(posture=None, *, allow_fetch: Optional[bool] = None):
    """Temporarily apply the offline flags for a block, restoring prior env."""
    fetch = allow_fetch if allow_fetch is not None else posture_allows_fetch(posture)
    saved = {k: os.environ.get(k) for k in _OFFLINE_ENV}
    try:
        if not fetch:
            os.environ.update(_OFFLINE_ENV)
        yield fetch
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def require_fetch_allowed(posture=None, model_id: str = "model") -> None:
    """Raise ModelFetchBlocked when a download is forbidden. For a loader (e.g.
    ultralytics/torch.hub, which don't honour HF_HUB_OFFLINE) that would otherwise
    silently reach a CDN on first use while the wearer is offline. With no posture
    supplied it consults the LIVE process decision set by apply_offline_posture,
    so a loader with no posture in hand still respects an offline session."""
    allowed = _FETCH_ALLOWED if posture is None else posture_allows_fetch(posture)
    if not allowed:
        raise ModelFetchBlocked(
            f"refusing to download {model_id!r}: the wearer's posture is offline/"
            f"incognito/LAN-only. Fetch models once via 'dreamlayer setup models' "
            f"while connected, or switch network mode.")


# -- no-pickle-RCE torch load -------------------------------------------------
def safe_torch_load(path: Path | str, **kw):
    """``torch.load`` with ``weights_only=True`` forced on — the pickle→RCE
    guard. A ``.pt``/``.pth`` checkpoint is a pickle; weights_only refuses to run
    arbitrary reduce ops during unpickling, so a malicious checkpoint cannot
    execute. Callers that genuinely need a full object must pass
    ``weights_only=False`` explicitly (and own that risk); the default here is
    safe on every torch version that supports the kwarg, and degrades with a
    loud warning on ancient ones."""
    import torch  # local import: torch is an optional heavyweight dep
    kw.setdefault("weights_only", True)
    try:
        return torch.load(path, **kw)
    except TypeError as exc:
        # ONLY treat the "unexpected keyword 'weights_only'" TypeError as the
        # old-torch signal. Any OTHER TypeError (e.g. one raised while a modern
        # torch processes a crafted checkpoint) must propagate — retrying without
        # weights_only would disarm the RCE guard we exist to hold (refute
        # 2026-07-18).
        if "weights_only" not in str(exc):
            raise
        kw.pop("weights_only", None)
        log.warning("[model_guard] torch too old for weights_only=True; loading %s "
                    "as a trusted pickle — upgrade torch to close the RCE path", path)
        return torch.load(path, **kw)


def prefer_safetensors(entry: dict) -> bool:
    """True when a model's lock entry declares safetensors as the trusted format,
    so a loader should pass ``use_safetensors=True`` and never touch the pickle
    sibling."""
    return isinstance(entry, dict) and str(entry.get("prefer", "")).lower() == "safetensors"


def verify_all(root: Path | str, lock: Optional[dict] = None) -> list[dict]:
    """Verify every pinned model under a models *root* dir (for the CLI /
    release-bootstrap check). Returns a per-model result list; never raises —
    collects failures so the CLI can report them all at once."""
    out = []
    for model_id, entry in known_models(lock).items():
        entry = entry if isinstance(entry, dict) else {}     # a malformed lock entry
        files = entry.get("files")
        rec = {"model": model_id, "pinned": bool(files or entry.get("sha256")),
               "ok": None, "error": None}
        if not rec["pinned"]:
            out.append(rec)
            continue
        try:
            rec["ok"] = verify_path(model_id, Path(root) / model_id, lock=lock, strict=False)
        except (ModelIntegrityError, OSError) as exc:        # missing/unreadable file too
            rec["ok"] = False
            rec["error"] = str(exc)
        out.append(rec)
    return out
