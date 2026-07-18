"""ai_brain/server/store.py — the Brain's own state: config + query history.

This is the "load your info / connect your stuff" layer. Everything the
control panel edits lives here, persisted as plain JSON so it's easy to
inspect, back up, or hand-edit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CONFIG_FILE = "brain_config.json"
HISTORY_FILE = "brain_history.jsonl"
ACTIVITY_FILE = "brain_activity.jsonl"

# A crashed save between mkstemp and the atomic replace can leave a
# uniquely-named "<config>.<rand>.tmp" orphan (the per-writer temp no longer
# self-limits to one fixed name the way "<config>.tmp" did). save() sweeps such
# orphans, but only ones older than this grace window, so a CONCURRENT saver's
# in-flight temp is never yanked out from under its own replace.
_TMP_REAP_GRACE = 60.0

log = logging.getLogger("dreamlayer.ai_brain.server.store")


def replace_atomic(src, dst, timeout: float = 10.0, burst: int = 50) -> None:
    """os.replace that rides out Windows share-mode contention.

    POSIX rename is atomic and never takes the retry path. On Windows,
    replacing a file that a reader holds open raises PermissionError
    (Python's open() doesn't request FILE_SHARE_DELETE), and the reader may
    keep it open for whole GIL slices at a time. Caught by the Windows CI
    leg: under a reader/writer storm the first PermissionError killed the
    writing thread and lost every later write — and a first fix that
    *sampled* a few dozen instants at a fixed interval still starved,
    because the samples landed while some reader held the file. So this
    scans instead: tight bursts of attempts (an open-read-close reader
    always leaves gaps between its opens), separated by short jittered
    breathers that break lockstep with reader cadence. After `timeout`
    seconds a final attempt re-raises, so a file held open *permanently*
    by another program still fails loudly instead of spinning forever."""
    import random
    deadline = time.monotonic() + timeout
    delay = 0.0005
    while True:
        for _ in range(burst):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                continue
        if time.monotonic() >= deadline:
            os.replace(src, dst)        # the loud final attempt
            return
        time.sleep(random.uniform(0.0, delay))
        delay = min(delay * 2, 0.05)


def _reap_stale_tmps(d: Path) -> None:
    """Best-effort sweep of orphaned '<config>.*.tmp' temps in `d`.

    save() writes to a per-writer unique tempfile.mkstemp temp, then atomically
    replaces the target with it. A hard crash BETWEEN mkstemp and replace leaves
    that uniquely-named temp behind and — unlike the old fixed '<config>.tmp'
    name, which the next save reused/overwrote — a unique name is never touched
    again, so orphans would accumulate forever (refute 2026-07-17). Only temps
    older than _TMP_REAP_GRACE are removed, so a concurrent saver's just-created
    temp is left alone (its own replace still needs it). All errors are
    swallowed: reaping is hygiene, never a reason to fail a save."""
    cutoff = time.time() - _TMP_REAP_GRACE
    try:
        candidates = list(d.glob(CONFIG_FILE + ".*.tmp"))
    except OSError:
        return
    for f in candidates:
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _current_user_sid() -> Optional[str]:
    """The calling process's user SID as a string ("S-1-5-...") on Windows.

    Read straight off the process token (OpenProcessToken + GetTokenInformation
    for TokenUser), so it's locale- and domain-independent — unlike a username,
    which icacls would have to resolve through whatever the box's naming context
    is. Returns None on any failure; the caller falls back to the account name.
    """
    import ctypes
    from ctypes import wintypes

    TOKEN_QUERY = 0x0008
    TokenUser = 1
    # WinDLL exists only on Windows; this fn is only reached on nt (guarded by
    # _harden_windows_acl), but mypy checks it on every platform.
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    # Declare argtypes/restypes explicitly. ctypes otherwise assumes every arg
    # and return is a C int, which on Win64 truncates 64-bit HANDLEs and SID
    # pointers to 32 bits — the old code only "worked" by luck of handle
    # sign-extension. Pinning the signatures makes the marshalling correct.
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
                token, TokenUser, buf, size, ctypes.byref(size)):
            return None
        # TOKEN_USER begins with SID_AND_ATTRIBUTES { PSID Sid; ... }; the SID
        # pointer is the first machine-word of the buffer.
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        str_sid = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(
                ctypes.c_void_p(psid), ctypes.byref(str_sid)):
            return None
        try:
            return str_sid.value
        finally:
            kernel32.LocalFree(str_sid)
    finally:
        kernel32.CloseHandle(token)


def _harden_windows_acl(path: str) -> None:
    """Windows only: restrict `path` to the current user + LocalSystem + the
    Administrators group, so no *other regular user* can read it.

    POSIX chmod(0o600) is a no-op for ACLs on Windows — it toggles just the
    read-only attribute and sets NO ACL, so a secret config's confidentiality
    would rest entirely on whatever ACLs it inherited from the user profile.
    This strips inheritance and re-grants Full control to exactly three
    principals:

      * ``S-1-5-18``     LocalSystem     — AV, backup, and OS agents run here;
      * ``S-1-5-32-544`` Administrators  — admin tooling / the elevated installer;
      * the current user's SID           — the app itself.

    Stripping inheritance also drops the inherited SYSTEM/Administrators ACEs,
    so they MUST be re-granted or a plain ``/grant:r *<userSID>:F`` would lock
    out AV/backup/OS-agent readers (and, if the user grant itself failed, the
    app). Confidentiality vs other regular users is still preserved — Users and
    Everyone are gone — while SYSTEM/Administrators (which can read anything on
    the box anyway) keep access. Both well-known SIDs are locale- and
    domain-independent, so this holds regardless of language pack or domain.

    The grantee is the process-token SID, never a bare account name: on a
    domain-joined box a bare ``getpass.getuser()`` name can fail to map once
    inheritance is stripped, leaving the file unreadable by the app — the
    lockout path. So if the SID can't be resolved we do NOT strip inheritance
    behind a possibly-unmappable grant; we skip the whole ACL step and leave the
    file at its inherited-profile baseline (already not world-readable), logging
    a warning. Never leave the file in a state the app can't read.

    Best-effort by contract: any failure is logged and swallowed — the
    POSIX-correct 0o600 already ran, and persisting the privacy posture must
    never crash on ACL plumbing. A hard no-op on non-Windows, so the POSIX save
    path is not touched (returns before importing anything).
    """
    if os.name != "nt":
        return
    import subprocess

    try:
        sid = _current_user_sid()
    except Exception as exc:             # ctypes/token lookup is fragile; degrade
        log.warning("owner-only ACL: SID lookup failed for %s (%s); leaving the "
                    "inherited ACL baseline (the state dir is hardened too)",
                    path, exc)
        return
    argv = _owner_only_icacls_argv(path, sid)
    if argv is None:
        log.warning("owner-only ACL: could not resolve the current-user SID for "
                    "%s; leaving the inherited ACL baseline (the state dir is "
                    "hardened too)", path)
        return
    try:
        subprocess.run(
            argv, check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log.warning("owner-only ACL hardening failed for %s: %s", path, exc)


def _owner_only_icacls_argv(path: str, user_sid: Optional[str]) -> Optional[list]:
    """The icacls invocation that strips inheritance and grants Full control to
    exactly current-user + LocalSystem + Administrators — the owner-only DACL.

    Returns None when the user SID is missing/empty: the caller MUST then skip
    hardening (leaving the file at its — now dir-hardened — inherited baseline)
    and never fall back to a broad grant. LocalSystem (S-1-5-18) and
    Administrators (S-1-5-32-544) are locale/domain-independent well-known SIDs,
    kept alongside the user so stripping inheritance doesn't evict OS/AV/backup
    readers (or the app). icacls accepts ``*<SID>`` for a grantee, so the grant
    stays locale/domain-independent even after the resolved-name ACEs are
    dropped. Extracted as a pure builder so a cross-platform test can pin the
    exact grant shape (inheritance stripped, no broad principal, fail-closed on a
    missing SID) without a Windows box."""
    if not user_sid:
        return None
    return ["icacls", path, "/inheritance:r", "/grant:r",
            "*S-1-5-18:F",        # LocalSystem
            "*S-1-5-32-544:F",    # Administrators
            "*" + user_sid + ":F"]


def _harden_state_dir(d) -> None:
    """Make the Brain's state DIRECTORY owner-only, so every file created inside
    it — brain_config.json and its mkstemp temp, plus the history/activity logs —
    is born private BY INHERITANCE.

    The per-file _harden_windows_acl runs only AFTER the config is written and
    atomically swapped in, and it is SKIPPED entirely when the current-user SID
    can't be resolved. That left two gaps a refute pass found (2026-07-18): (1) a
    per-save window where the mkstemp temp / post-replace target carry only the
    directory-INHERITED ACL until icacls runs, and (2) on SID-lookup failure the
    file is left at that inherited baseline forever. Both are safe ONLY if the
    directory itself is owner-only — which, under a broad $DREAMLAYER_DIR (e.g.
    C:\\ProgramData\\Dreamlayer, whose default ACL grants BUILTIN\\Users read),
    it is NOT unless hardened here. icacls applies (OI)(CI) inheritance by
    default, so children inherit the owner-only grant; POSIX chmod 0o700 does the
    same. The docstring's old promise that the inherited baseline is "already not
    world-readable" is only TRUE once this runs. Best-effort, like the file
    harden — never crash a save on ACL plumbing."""
    try:
        os.chmod(d, 0o700)          # POSIX owner-only dir; inert (read-only bit) on NTFS
    except OSError:
        pass
    # Windows dir ACL: (OI)(CI) so children inherit owner-only; a no-op on POSIX.
    _harden_windows_acl(str(d))


def _is_allowed_root(path: str) -> bool:
    """True if `path` may be indexed by the Brain.

    Default-deny allow-list: the path must resolve to somewhere under the
    user's own home tree, or under the OS temp tree (used by legitimate
    export/scratch workflows and the test harness). Anything else — a system
    directory (/etc, /var, /usr, /System), another user's home, or the
    filesystem root — is refused. The path is fully resolved first so `..`
    and symlink escapes can't smuggle a disallowed target past the check.
    Non-existent paths are permitted as long as they resolve under an allowed
    root, so a temporarily-missing folder can still be watched.
    """
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    try:
        allowed_roots = [Path.home().resolve(),
                         Path(tempfile.gettempdir()).resolve()]
    except (OSError, RuntimeError, ValueError):
        return False
    for root in allowed_roots:
        if p == root or root in p.parents:
            return True
    return False


# Dot-directories whose contents are secrets-at-rest by convention. ~/.config is
# deliberately excluded — too broad, it holds ordinary app state — so this stays
# to the clearly-secret ones (private keys, cloud creds, GPG keyrings).
_SECRET_DOTDIRS = (".ssh", ".aws", ".gnupg")


def _state_dir() -> Optional[Path]:
    """The Brain's OWN state directory, resolved exactly the way every entry
    point resolves it ($DREAMLAYER_DIR, else ~/.dreamlayer). It holds
    brain_config.json — the pairing token + cloud_api_key + api_key in CLEAR —
    plus the query/activity logs. None if it can't be resolved."""
    base = os.environ.get("DREAMLAYER_DIR") or str(Path.home() / ".dreamlayer")
    try:
        return Path(base).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_index_denied(path: str) -> bool:
    """True if `path` must be kept OUT of the Brain's index even when it passes
    the _is_allowed_root allow-list (i.e. resolves under the user's home tree).

    The allow-list permits anything under home, but the Brain's OWN state dir
    lives there too — and its brain_config.json holds the pairing token and both
    provider API keys in clear, while brain_history/activity hold past queries. A
    '.json' target matches index.TEXT_EXTS, so without this denylist a symlink
    inside a watched folder pointing at <statedir>/brain_config.json — or simply
    adding <statedir> as a watched folder — would ingest those secrets and make
    them RECALLABLE via /brain/ask, undercutting the 0o600/ACL secret-at-rest
    work (refute-remediation 2026-07-17). Common secret-at-rest dotdirs (~/.ssh,
    ~/.aws, ~/.gnupg) are refused for the same reason. The path is fully resolved
    first so `..`/symlink escapes can't smuggle a denied target past the check;
    an unresolvable path is refused (default-deny). This is index-only, distinct
    from _is_allowed_root, so the Windows calendar reader can still load its
    <statedir>/calendars/*.ics feeds (which never reach the index)."""
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return True
    sd = _state_dir()
    if sd is not None and (p == sd or sd in p.parents):
        return True
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    for name in _SECRET_DOTDIRS:
        root = home / name
        if p == root or root in p.parents:
            return True
    return False


@dataclass
class BrainConfig:
    """Everything the Brain reads and how it thinks. Editable from the panel."""
    folders: list[str] = field(default_factory=list)   # watched directories
    model: str = "keyword"          # "keyword" | "ollama" | "mlx" | "api"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_vision_model: str = "llama3.2-vision"
    ollama_embed_model: str = "nomic-embed-text"
    email_enabled: bool = False     # macOS Mail / iMessage read (Phase 3 seam)
    summarize_emails: bool = False  # shorten emails to a glance before relaying
    # network posture (product default = connected): "connected" reaches the
    # internet + cloud; "lan_only" is the advanced home-only mode.
    network_mode: str = "connected"
    cloud_enabled: bool = False     # cloud tier is opt-in — off until enabled
    token: str = ""                 # pairing secret the phone must send
    # billing tier (seam only — no paywall). "free" = local & open, grants
    # everything today. A future "cloud" plan is where hosted capabilities
    # (managed AI, sync, relay) would attach. See server.PLAN_CAPS.
    plan: str = "free"
    # -- cloud provider (batch 2) — the tier that leaves the device ------
    # provider: openai | anthropic | gemini | openrouter | ollama | custom
    # (see backends.PROVIDER_PRESETS). Ollama is local + free + needs no key.
    cloud_provider: str = "openai"
    cloud_base_url: str = "https://api.openai.com"
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini"
    cloud_calls: int = 0            # lifetime count of cloud egress
    # -- primary API brain — plug in your own agent as the MAIN answerer -----
    # When model == "api", the first-pass answer is routed to this endpoint
    # (OpenClaw, Hermes, LM Studio, vLLM, a local Ollama, any OpenAI-compatible
    # / Anthropic / Gemini API) instead of the on-device keyword/Ollama tier.
    # Distinct from cloud_* (the escalation tier) so the two can point at
    # different places. Egress is decided by the endpoint's LOCALITY, not by
    # this being a "cloud" field: a localhost/LAN endpoint answers freely and
    # is not egress; a remote one is counted, logged, and veil-gated exactly
    # like the cloud tier (see Brain._ask_primary_api).
    api_provider: str = "custom"    # a PROVIDER_PRESETS key (wire format)
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    # -- knowledge depth (batch 3) --------------------------------------
    semantic_search: bool = False   # embed + rank (needs an embed model)
    index_extensions: list[str] = field(default_factory=list)   # [] = defaults
    max_file_kb: int = 2000
    exclude_globs: list[str] = field(default_factory=list)
    # -- ops (batch 4) ---------------------------------------------------
    quiet_hours: str = ""           # "22:00-07:00" → auto-incognito window
    retention_days: int = 0         # 0 = keep forever
    brief_hour: int = -1            # deliver the morning brief at this hour; -1 = off
    # -- calendar sync (macOS Calendar.app → agenda) --------------------
    calendar_sync: bool = False     # pull events from Calendar.app on a poll
    calendar_names: list[str] = field(default_factory=list)  # [] = all calendars
    calendar_days: int = 14         # how far ahead to pull
    # portable calendar feeds (the Windows reader; harmless elsewhere):
    # .ics file paths or http(s) URLs, on top of <cfg>/calendars/*.ics.
    # URL feeds are never fetched while incognito (see windows_sources).
    calendar_ics: list[str] = field(default_factory=list)
    # -- contacts + reminders sync (macOS) ------------------------------
    contacts_sync: bool = False     # pull Contacts.app into the People registry
    reminders_sync: bool = False    # pull open Reminders.app to-dos
    reminder_lists: list[str] = field(default_factory=list)  # [] = all lists
    # -- optional capabilities (dreamlayer/capabilities.py) --------------
    # keys the panel switched OFF — the persisted twin of DL_DISABLE_<KEY>,
    # so the bundled app remembers the choice across restarts
    disabled_caps: list[str] = field(default_factory=list)

    @property
    def lan_only(self) -> bool:
        return self.network_mode == "lan_only"

    def cloud_ready(self) -> bool:
        """Cloud can actually answer: allowed by posture AND configured.

        Ollama-local runs on-device with no key, so it only needs a model;
        every other provider also needs an API key.
        """
        if self.network_mode == "lan_only" or not self.cloud_enabled:
            return False
        if not self.cloud_model:
            return False
        if self.cloud_provider == "ollama":
            return True
        return bool(self.cloud_api_key)

    def api_configured(self) -> bool:
        """Is a primary API brain wired (base URL present)?"""
        return bool((self.api_base_url or "").strip())

    def api_is_local(self) -> bool:
        """Does the primary API endpoint live on this machine / LAN? If so it is
        NOT cloud egress and stays reachable while incognito; if remote, it is
        gated and logged like the cloud tier. Drives the panel's privacy
        warning. Unconfigured → False (nothing to reach)."""
        if not self.api_configured():
            return False
        from .backends import is_local_endpoint      # lazy: avoid import cycle
        return is_local_endpoint(self.api_base_url)

    def add_folder(self, path: str) -> bool:
        # SECURITY: default-deny allow-list. A token holder must not be able to
        # point the Brain at /etc, another user's home, or the filesystem root
        # (audit 2026-07-14 — "accepts any path with no allow-list"). This is a
        # fast-fail at the front door; _is_allowed_root is also re-checked at the
        # walk sink (index.reindex) and on every other writer (sanitize_folders,
        # called from load + import_backup), so the allow-list holds no matter
        # how a path reaches config.folders — not just via this handler
        # (refute-remediation 2026-07). Storage stays expanduser-only
        # (unresolved) so downstream comparisons — missing_folders,
        # _write_upload, the index — see the same string they always did.
        if not _is_allowed_root(path):
            return False
        p = str(Path(path).expanduser())
        if p not in self.folders:
            self.folders.append(p)
            return True
        return False

    def remove_folder(self, path: str) -> bool:
        p = str(Path(path).expanduser())
        if p in self.folders:
            self.folders.remove(p)
            return True
        return False

    def sanitize_folders(self) -> None:
        """Drop any watched folder that isn't allow-listed. Called on load and
        after a restore, so a hand-edited/pre-remediation config file or a
        crafted backup cannot reintroduce a path the add-folder gate would have
        refused (refute-remediation 2026-07)."""
        self.folders = [f for f in self.folders if _is_allowed_root(f)]

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, cfg_dir: Path | str) -> "BrainConfig":
        p = Path(cfg_dir) / CONFIG_FILE
        try:
            raw = p.read_text()
        except FileNotFoundError:
            return cls()                  # no config yet — first run
        except OSError as exc:
            # PermissionError etc.: a config the new owner-only ACL (Windows) or
            # a bad mode made unreadable to THIS process would otherwise crash
            # load — dropping the wearer out of Incognito and losing their
            # watched folders. A missing-OR-unreadable config falls back to
            # defaults, never raises (refute-remediation 2026-07-17). ``exists()``
            # was dropped here: it re-raises PermissionError on an unreadable path
            # exactly like read_text, so guarding read_text alone still crashed.
            log.warning("brain_config load: %s unreadable (%s); using defaults",
                        p, exc)
            return cls()
        try:
            data = json.loads(raw)
            known = {f.name for f in field_list(cls)}
            inst = cls(**{k: v for k, v in data.items() if k in known})
            inst.sanitize_folders()   # a tampered/legacy file can't smuggle disallowed roots
            return inst
        except (ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self, cfg_dir: Path | str) -> None:
        # tmp + atomic replace: a plain write_text can be caught torn by a crash
        # or AV lock mid-write, and BrainConfig.load() turns a JSONDecodeError
        # into cls() DEFAULTS — silently dropping the wearer out of Incognito
        # (network_mode → "connected") and losing their watched folders. The
        # config store holds the privacy posture, so it must never half-write
        # (audit 2026-07-15). replace_atomic also rides out Windows share-mode
        # contention, matching the JSON stores.
        d = Path(cfg_dir)
        d.mkdir(parents=True, exist_ok=True)
        # Harden the DIRECTORY first, so the mkstemp temp and the swapped-in
        # target are born owner-only by inheritance — closing the pre-icacls
        # write window and the fail-to-inherited gap when the per-file SID lookup
        # is skipped (refute 2026-07-18). Must precede _reap_stale_tmps/mkstemp.
        _harden_state_dir(d)
        _reap_stale_tmps(d)   # sweep crash-orphaned unique temps (age-gated)
        target = d / CONFIG_FILE
        # This file holds the pairing token AND the provider API keys
        # (cloud_api_key/api_key) in clear, so it must never be group/world
        # readable. write_text lands at the umask default (0o644 on POSIX),
        # which the login-entry fix (token moved off the HKCU Run value / the
        # LaunchAgent plist into this file) turned into a fresh world-readable
        # secret leak.
        #
        # The temp is a per-writer UNIQUE file from tempfile.mkstemp: it opens
        # O_EXCL at mode 0o600, so it is private from its first byte AND no two
        # savers can collide on it. The old fixed "<config>.tmp" opened without
        # O_EXCL was reopen-and-truncate: a stale 0o644 tmp left by a crash or an
        # older build would be reused KEEPING its world-readable mode, leaking
        # the secrets through the temp (refute 2026-07-17). 0o600 is re-asserted
        # on the swapped-in target, and _harden_windows_acl adds the owner-only
        # ACL that chmod cannot express on Windows (no-op elsewhere).
        payload = json.dumps(asdict(self), indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(d), prefix=CONFIG_FILE + ".",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
            replace_atomic(tmp, str(target))
        except Exception:
            try:
                os.unlink(tmp)             # no torn/readable residue if it fails
            except OSError:
                pass
            raise
        try:
            os.chmod(target, 0o600)         # re-assert after the atomic swap
        except OSError:
            pass
        # Windows ACL; no-op on POSIX. Re-applied on EVERY save, unconditionally:
        # save() writes a fresh tempfile.mkstemp temp and os.replace()s it onto
        # target (MoveFileExW on Windows), which makes the temp BECOME the target
        # — and that temp carries only the directory-INHERITED ACL, not the
        # explicit owner-only DACL. So os.replace/MoveFileEx DISCARDS the
        # destination DACL every save; the owner-only ACL must be re-applied each
        # time or the very next save (e.g. pairing writing the token) leaves the
        # config at its inherited-profile baseline. Config saves are infrequent
        # (pairing, folder add/remove, incognito toggle, config patches), not a
        # hot path, so the per-save icacls + token lookup is acceptable
        # (refute 2026-07-17: a create-only gate silently un-hardened the file).
        _harden_windows_acl(str(target))

    def public(self) -> dict:
        """Config for the panel — never leaks the token or any provider key."""
        d = asdict(self)
        d["token"] = "set" if self.token else ""
        d["cloud_api_key"] = "set" if self.cloud_api_key else ""
        d["api_key"] = "set" if self.api_key else ""
        d["cloud_ready"] = self.cloud_ready()
        d["api_configured"] = self.api_configured()
        d["api_is_local"] = self.api_is_local()
        return d


def field_list(cls):
    import dataclasses
    return dataclasses.fields(cls)


class QueryHistory:
    """An append-only log of what you asked and what came back."""

    def __init__(self, cfg_dir: Path | str, limit: int = 500):
        self.path = Path(cfg_dir) / HISTORY_FILE
        self.limit = limit

    def add(self, query: str, answer: str, tier: str,
            sources: Optional[list[str]] = None, ts: Optional[float] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": ts if ts is not None else time.time(), "query": query,
               "answer": answer, "tier": tier, "sources": sources or []}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def recent(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        out = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def prune(self, days: int) -> int:
        return _prune_jsonl(self.path, days)

    def restore(self, items) -> None:
        _restore_jsonl(self.path, items)


def _receipt_core(rec: dict) -> dict:
    """The signed core of an activity record — the fields a receipt attests."""
    return {"seq": rec["seq"], "ts": rec["ts"], "kind": rec["kind"],
            "text": rec["text"], "prev": rec["prev"]}


def _receipt_hash(core: dict) -> str:
    """sha256 of a record's canonical core — the chain link the next record binds."""
    data = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


class ActivityLog:
    """Everything the Brain did — folders, files, searches, cloud/incognito
    toggles, pairing — as a single newest-first feed for the panel.

    On a camera-and-mic device the ledger IS the privacy promise, so it is
    tamper-evident: when a `signer` (Ed25519) is supplied, each record carries a
    monotonic `seq`, the `prev` sha256 of the previous record's core (a hash
    chain), and a `sig` over that core. A third party handed only the PUBLIC key
    can then `verify()` that no record was modified, reordered, or dropped from
    the middle by anyone without the private key — "trust us we were incognito"
    becomes a checkable receipt (`/dreamlayer/receipt`). The signer is optional
    and additive: with none, or on an existing unsigned log, it behaves exactly
    as before and `recent()` is unchanged (refute 2026-07-18: the ledger was a
    freely-rewritable text file with clear()/prune()/restore() and no signature).
    """

    def __init__(self, cfg_dir: Path | str, signer=None):
        self.path = Path(cfg_dir) / ACTIVITY_FILE
        self._head_path = self.path.with_name(self.path.name + ".head")
        self._signer = signer
        self._head_hash = ""            # sha256 of the last record's core ("" = genesis)
        self._next_seq = 0
        self._loaded = False

    # -- the signed head anchor (defeats tail truncation) ---------------------
    # A hash chain alone protects edits/reorders/mid-deletions, but NOTHING
    # anchors its LENGTH: a valid prefix of a valid chain is itself a valid chain,
    # so an attacker can chop the most-recent (incriminating) records and verify()
    # would still pass (refute 2026-07-18). This separate, key-SIGNED checkpoint
    # attests the current high-water mark {last_seq, head, count}; verify() checks
    # the file's tail against it, so a truncation an attacker can't re-sign is
    # caught. The owner (with the key) re-signs it on every add/prune/restore.
    def _write_head(self) -> None:
        if self._signer is None:
            return
        core = {"last_seq": self._next_seq - 1, "head": self._head_hash,
                "count": self._next_seq}
        doc = {**core, "sig": self._signer.sign(core)}
        self._head_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._head_path.with_name(self._head_path.name + ".tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, self._head_path)

    def _read_head(self) -> Optional[dict]:
        """The verified head anchor, or None (absent / unverifiable / no signer)."""
        if self._signer is None or not self._head_path.exists():
            return None
        try:
            doc = json.loads(self._head_path.read_text())
            core = {"last_seq": doc["last_seq"], "head": doc["head"],
                    "count": doc["count"]}
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None
        if not self._signer.verify(core, doc.get("sig", "")):
            return None                        # a forged/edited anchor is no anchor
        return core

    # -- the chain head (lazy: from the SIGNED anchor, not attacker file state) --
    def _load_head(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        head = self._read_head()
        if head is not None:
            # trust the signed checkpoint, so a record an attacker APPENDED (with a
            # bogus seq/prev to poison the next add) cannot redirect our chain.
            self._next_seq = head["last_seq"] + 1
            self._head_hash = head["head"]
            return
        recs = self._read_all()                # legacy / no anchor yet
        for rec in recs:
            if "seq" in rec and "prev" in rec:
                self._next_seq = rec["seq"] + 1
                try:
                    self._head_hash = _receipt_hash(_receipt_core(rec))
                except (KeyError, TypeError):
                    self._head_hash = ""

    def add(self, kind: str, text: str, ts: Optional[float] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ts = ts if ts is not None else time.time()
        rec: dict = {"ts": ts, "kind": kind, "text": text}
        if self._signer is not None:
            self._load_head()
            rec["seq"] = self._next_seq
            rec["prev"] = self._head_hash
            core = _receipt_core(rec)
            rec["sig"] = self._signer.sign(core)
            self._head_hash = _receipt_hash(core)
            self._next_seq += 1
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self._write_head()                     # advance the signed high-water mark

    def _read_all(self) -> list[dict]:
        """All records, oldest-first (file order)."""
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def recent(self, n: int = 40) -> list[dict]:
        return list(reversed(self._read_all()[-n:]))

    # -- verification ---------------------------------------------------------
    def verify(self) -> dict:
        """Walk the chain and report integrity. ``ok`` is True when every SIGNED
        record verifies against the public key AND its prev-link is intact.
        Unsigned/legacy records are reported (``unsigned``), never flagged as
        tampered. Fail-safe: with no signer or no cryptography, ``ok`` is False
        and ``reason`` explains why it is unverifiable, never a misleading True."""
        recs = self._read_all()
        signer = self._signer
        pub = getattr(signer, "public_key_hex", "") if signer else ""
        if signer is None or not getattr(signer, "available", False) or not pub:
            return {"ok": False, "records": len(recs), "signed": 0, "unsigned": len(recs),
                    "first_broken": None, "pubkey": pub,
                    "reason": "no Ed25519 receipt key (install the 'privacy' extra)"}
        expected_prev: Optional[str] = ""
        signed = unsigned = 0
        first_broken = None
        last_seq_seen = -1
        running_head = ""
        for i, rec in enumerate(recs):
            if "sig" not in rec or "seq" not in rec or "prev" not in rec:
                unsigned += 1
                expected_prev = None           # chain continuity is unknown past a gap
                continue
            try:
                core = _receipt_core(rec)
            except KeyError:
                first_broken = first_broken if first_broken is not None else i
                continue
            link_ok = expected_prev is None or rec["prev"] == expected_prev
            sig_ok = signer.verify(core, rec["sig"])
            if not (link_ok and sig_ok):
                first_broken = first_broken if first_broken is not None else rec.get("seq", i)
            else:
                signed += 1
                last_seq_seen = rec["seq"]
            expected_prev = _receipt_hash(core)
            running_head = expected_prev
        ok = first_broken is None and unsigned == 0 and signed == len(recs)
        out = {"ok": ok, "records": len(recs), "signed": signed, "unsigned": unsigned,
               "first_broken": first_broken, "pubkey": pub}
        # Tail-truncation check against the signed head anchor. An attacker who
        # chops recent records can't re-sign the checkpoint, so a stale
        # last_seq/count/head betrays the cut.
        head = self._read_head()
        if head is not None:
            if head["last_seq"] > last_seq_seen or head["count"] > signed \
                    or (ok and running_head != head["head"]):
                out["ok"] = False
                out["truncated"] = True
                if out["first_broken"] is None:
                    out["first_broken"] = last_seq_seen + 1     # first missing seq
                out["reason"] = (f"tail truncated: anchor attests {head['count']} "
                                 f"records up to seq {head['last_seq']}, file has "
                                 f"{signed} up to seq {last_seq_seen}")
        elif signed > 0:
            # a signed log with NO valid anchor: the anchor was deleted (or a
            # pre-anchor legacy log). Fail-safe — report it rather than pass.
            out["ok"] = False
            out["reason"] = "signed log has no valid head anchor (deleted or legacy)"
        return out

    def receipt(self, n: int = 2000) -> dict:
        """A portable, third-party-verifiable proof of what the Brain did: the
        records (with their seq/prev/sig), the public key to check them against,
        and this Brain's own verify() result."""
        recs = self._read_all()[-n:]
        return {"pubkey": getattr(self._signer, "public_key_hex", "") if self._signer else "",
                "algorithm": "ed25519-sha256-chain",
                "records": recs,
                # the signed high-water mark, so a third party given only the last
                # `n` records can still detect a truncated tail (records may start
                # mid-chain, but head.last_seq/count attest the true length).
                "head": self._read_head(),
                "verification": self.verify()}

    # -- owner edits: re-chain the survivors so the receipt stays consistent ---
    def _rechain(self, recs: list[dict]) -> None:
        """Rewrite the log, re-numbering + re-signing `recs` from a fresh genesis.
        A legitimate owner edit (prune/restore) with the key in hand re-attests
        the surviving records; an attacker WITHOUT the key cannot, so their edit
        fails verify()."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prev, seq = "", 0
        with self.path.open("w") as f:
            for src in recs:
                rec = {"ts": src.get("ts", time.time()),
                       "kind": src.get("kind", ""), "text": src.get("text", "")}
                if self._signer is not None:
                    rec["seq"] = seq
                    rec["prev"] = prev
                    core = _receipt_core(rec)
                    rec["sig"] = self._signer.sign(core)
                    prev = _receipt_hash(core)
                    seq += 1
                f.write(json.dumps(rec) + "\n")
        self._head_hash, self._next_seq, self._loaded = prev, seq, True
        self._write_head()                     # re-attest the new (owner-signed) head

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        if self._head_path.exists():
            self._head_path.unlink()           # drop the anchor with the log
        self._head_hash, self._next_seq, self._loaded = "", 0, True

    def prune(self, days: int) -> int:
        if self._signer is None:
            return _prune_jsonl(self.path, days)
        if days <= 0 or not self.path.exists():
            return 0
        cutoff = time.time() - days * 86400
        recs = self._read_all()
        kept = [r for r in recs if r.get("ts", 0) >= cutoff]
        removed = len(recs) - len(kept)
        if removed:
            self._rechain(kept)
        return removed

    def restore(self, items) -> None:
        if self._signer is None:
            _restore_jsonl(self.path, items)
            return
        # `items` arrives newest-first (as recent()/state export produce it).
        self._rechain(list(reversed(list(items or []))))


def activity_receipt_signer(cfg_dir: Path | str):
    """Load-or-create the persistent Ed25519 seed that signs the activity receipt.

    The seed is the root of trust for the tamper-evident privacy ledger, so it is
    held by the secret_store (OS keychain / enclave when available, an owner-only
    file otherwise) rather than as a bare plaintext file. The file backend uses
    the same ``receipt.key`` path and format existing installs already have, and
    get_or_create() reads through every backend first, so upgrading to a keychain
    keeps the same public key and every past receipt still verifies. Returns a
    sign_crypto.Signer, or None when the `cryptography` extra is absent (the
    ledger then stays plain, fail-safe)."""
    try:
        from ...reality_compiler.sign_crypto import Signer
    except Exception:
        return None
    if not getattr(Signer, "available", False):
        return None
    from ...secret_store import SecretStore
    store = SecretStore(cfg_dir)
    key = store.get_or_create("receipt", lambda: os.urandom(32))
    if len(key) < 32:                                # corrupt/short existing seed
        key = os.urandom(32)
        store.set("receipt", key)
    return Signer(key)


def _restore_jsonl(path: Path, items) -> None:
    """Rewrite a jsonl log from a newest-first list (as recent() returns)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for rec in reversed(list(items or [])):
            f.write(json.dumps(rec) + "\n")


def _prune_jsonl(path: Path, days: int) -> int:
    """Drop records older than `days` from a jsonl log. Returns rows removed."""
    if days <= 0 or not path.exists():
        return 0
    cutoff = time.time() - days * 86400
    kept, removed = [], 0
    for line in path.read_text().splitlines():
        try:
            if json.loads(line).get("ts", 0) >= cutoff:
                kept.append(line)
            else:
                removed += 1
        except json.JSONDecodeError:
            continue
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed


def in_quiet_hours(spec: str, now: Optional[float] = None) -> bool:
    """True if `now` falls in a "HH:MM-HH:MM" window (wraps past midnight)."""
    if not spec or "-" not in spec:
        return False
    try:
        a, b = spec.split("-", 1)
        ah, am = (int(x) for x in a.split(":"))
        bh, bm = (int(x) for x in b.split(":"))
    except (ValueError, TypeError):
        return False
    lt = time.localtime(now if now is not None else time.time())
    cur = lt.tm_hour * 60 + lt.tm_min
    start, end = ah * 60 + am, bh * 60 + bm
    if start == end:
        return False
    return start <= cur < end if start < end else (cur >= start or cur < end)
