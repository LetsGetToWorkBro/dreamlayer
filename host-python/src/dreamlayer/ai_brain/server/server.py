"""ai_brain/server/server.py — the Brain server (runs on your Mac mini).

Serves the control panel and the API the phone and the panel both call:

    GET  /                          control panel
    GET  /dreamlayer/config         config (token-safe) + index stats
    POST /dreamlayer/config         update model / connections
    POST /dreamlayer/folders        {action: add|remove, path}  → reindex
    POST /dreamlayer/upload?folder=&name=   drag-drop a file in → reindex
    POST /dreamlayer/brain/ask      {query} → Answer (logged to history)
    POST /dreamlayer/rc/compose     {prompt} → verified figment ("Ask Juno")
    POST /dreamlayer/rc/feed        {text} → stream text into the live lens slot
    POST /dreamlayer/rc/emit        {tag, text} → lens emit → Brain → slot (ask)
    POST /dreamlayer/brain/explain  {label, image?, want?} → Answer
    POST /dreamlayer/brain/look     {image?|label, attrs?, lens?} → World-lens panel
    GET  /dreamlayer/history        recent questions

All /dreamlayer/* calls require the pairing token (when one is set); the
panel page is injected with the token only when opened from localhost.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from ..exo_cluster import ExoClusterBackend
    from ..mlx_backend import MLXBackend

import threading
import time

# Module logger. configure_logging() (wired at the server entrypoint in
# __main__.py) attaches the handler; call sites just log. Best-effort failures
# that used to `except Exception: pass` now surface here instead of vanishing
# (audit 2026-07-14, Error-Handling B-→A-).
log = logging.getLogger("dreamlayer.ai_brain.server")

from ..schema import Answer
from .store import (BrainConfig, QueryHistory, ActivityLog, replace_atomic,
                    activity_receipt_signer, activity_receipt_watermark)
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer, probe_ollama
from .panel import render_panel
# Brain method clusters extracted into sibling mixin modules (the orchestrator's
# ops_* pattern). Behaviour-preserving: every method still runs on the shared
# Brain ``self``. ``_spoken_duration`` is re-exported for backwards-compat.
from .brain_rc import RCOps, _spoken_duration  # noqa: F401
from .brain_calendar import CalendarOps
from .brain_social import SocialOps
from .brain_reminders import ReminderOps
from .brain_waypath import WaypathOps
from .brain_sources import SourceOps

TOKEN_HEADER = "X-DreamLayer-Token"

# --- HTTP request-surface hardening (audit 2026-07-17, "HTTP surface" B-→A) ---
# Bounded reads, a per-connection socket timeout, a wall-clock body deadline,
# and a worker-thread ceiling keep an authed/loopback caller from driving
# unbounded memory, filling the disk, pinning a worker with slowloris (or a
# byte-dribbling slow-POST), or exhausting the process's threads. All are module
# constants so they are tunable in one place and assertable from tests.
MAX_JSON_BODY = 16 * 1024 * 1024        # 16 MiB — cap for JSON bodies (_body/_raw)
MAX_UPLOAD_BODY = 64 * 1024 * 1024      # 64 MiB — larger cap for file uploads
SOCKET_TIMEOUT_S = 30.0                 # per-connection socket timeout — bounds BOTH recv and send
MAX_REQUEST_BODY_SECONDS = 30.0         # wall-clock cap on reading a full body (anti slow-POST)
MAX_REQUEST_HEADER_SECONDS = 30.0       # wall-clock cap on the request line + headers (anti slow-header slowloris)
MAX_CONCURRENT_REQUESTS = 64            # worker-thread ceiling (anti thread-exhaustion)
MAX_EVENT_SUBS = 6                      # concurrent /live/events streams (each holds a worker thread)


# Content-Security-Policy for the token-bearing panel/builder pages. The panel is
# built on inline event handlers (onclick=/onchange=), so — unlike the Live page,
# which nonces its one inline block and can forbid inline entirely — it must keep
# 'unsafe-inline' for scripts/styles. What the policy still buys is the backstop
# the panel had NONE of: even if an injected node's handler runs, connect-src and
# img-src are pinned to 'self' (+ the one real off-origin the panel talks to, the
# cloud waitlist), so the panel TOKEN cannot be silently exfiltrated by fetch/XHR/
# WebSocket or an image beacon to an attacker origin. default-src 'self' blocks
# external script/frames, object-src 'none' kills plugin vectors, base-uri 'none'
# blocks a <base> hijack of every relative fetch, and frame-ancestors 'none'
# stops the panel being framed for clickjacking. This is the read-side companion
# to the same-origin write guard and the DNS-rebind Host allowlist.
PANEL_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' https://api.dreamlayer.app; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'")

# The builder page carries the SAME policy but permits a same-origin <base> — it
# injects "<base href='/dreamlayer/build/'>" so its relative assets resolve under
# the builder mount. base-uri 'self' still forbids pointing the base off-origin,
# so the same-origin, no-off-origin-fetch guarantees hold.
BUILDER_CSP = PANEL_CSP.replace("base-uri 'none'", "base-uri 'self'")


class _RequestTooLarge(Exception):
    """A request body exceeded its size cap → mapped to HTTP 413. Carries the
    cap so the handler can report it without re-deriving it."""

    def __init__(self, limit: int):
        super().__init__(f"request body exceeds {limit} bytes")
        self.limit = limit


class _BadContentLength(Exception):
    """A malformed (non-numeric) Content-Length header → mapped to HTTP 400
    instead of an unhandled int() ValueError surfacing as a 500 traceback."""


class _LengthRequired(Exception):
    """A body the server cannot length-delimit — a request carrying a
    ``Transfer-Encoding`` (e.g. chunked) header but no usable Content-Length.
    Python's http.server does not decode chunked bodies, so treating it as an
    empty body silently accepted a real payload (a 0-byte /upload artifact
    reported ok). Mapped to HTTP 411 Length Required (audit 2026-07-17,
    refute-remediation finding 2)."""


class _RequestTimeout(Exception):
    """The request body did not fully arrive within MAX_REQUEST_BODY_SECONDS of
    wall-clock time. The per-recv socket timeout only bounds a single stalled
    recv; a slow-POST that dribbles a byte just under it resets that clock
    indefinitely, pinning a worker thread and a semaphore slot. This
    total-duration bound is what actually reclaims them. Mapped to HTTP 408
    (audit 2026-07-17, refute-remediation finding 1)."""


def authorize(token: str, provided, from_localhost: bool) -> bool:
    """The Brain's access policy, as one pure decision.

    * A token is configured → every caller must present exactly it, on-box or
      off (constant-time compare so a wrong token can't be timed out byte by
      byte).
    * No token is configured → a tokenless brain is a *local dev* brain, so
      only loopback callers are trusted. A LAN peer is never let in through an
      empty token — the launcher mints one for any network-reachable bind
      (ai_brain/server/__main__.py), so in practice the empty-token case only
      happens on a deliberately loopback-only run.
    """
    if token:
        import hmac
        return isinstance(provided, str) and hmac.compare_digest(provided, token)
    return bool(from_localhost)

# Billing-tier seam (no paywall). Extra capabilities each plan grants ON TOP OF
# the always-free base set in Brain.plugin_capabilities(). `free` adds nothing —
# everything works locally & open. A future hosted plan (managed AI, sync,
# relay) would list its capabilities here; the base set is never taken away.
PLAN_CAPS: dict[str, frozenset] = {
    "free": frozenset(),
    # The hosted tier (docs/CLOUD.md). Union-only: these are ADDED on top of
    # the always-free base set — a plan can never remove a capability.
    #   cloud_ai     managed AI, no key to wire (api.dreamlayer.app proxy)
    #   cloud_sync   E2E-encrypted cross-device sync + off-site backup
    #   cloud_relay  hosted mesh relay (GhostMode/Beacon beyond BLE range)
    "cloud": frozenset({"cloud_ai", "cloud_sync", "cloud_relay"}),
}

# What each cloud capability means, for the panel's Plan section.
PLAN_CAP_INFO: dict[str, str] = {
    "cloud_ai": "Managed AI — answers with no key to wire, billed by us",
    "cloud_sync": "Encrypted sync — your memory follows you across devices",
    "cloud_relay": "Private relay — GhostMode and the Beacon work beyond Bluetooth range",
}


def _route_probe_ip() -> str | None:
    """The source IP for the default route — one address, the classic probe."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def lan_ip_candidates() -> list[str]:
    """Every private LAN IPv4 the phone might reach, the DEFAULT-ROUTE one first.

    The default-route probe is the OS's own answer to "which interface reaches
    off-box" — the single strongest reachability signal — so it LEADS, and is
    never reordered below an enumerated address. The hostname's other A-records
    follow (deduped) as alternates: they populate the cert SANs (so whichever LAN
    IP the phone dials matches the cert, surviving multi-NIC and a DHCP lease
    change) and are the fallback if the probe isn't a usable LAN address.

    We deliberately do NOT rank by address range: an earlier version floated a
    192.168/172 host-only/Docker/VirtualBox adapter above the real default-route
    10.x LAN, advertising the UNREACHABLE virtual IP in the QR (refute
    2026-07-20). Only true RFC1918 ranges are kept — a phone reaches the Brain
    over a home/office LAN, never a documentation/TEST-NET/CGNAT block (Python's
    is_private is broader than RFC1918 and would let 203.0.113.x through)."""
    import ipaddress
    found: list[str] = []

    def _add(ip):
        if ip and ip not in found:
            found.append(ip)

    _add(_route_probe_ip())                # the default route leads — never demoted
    try:                                   # every A record the host resolves to
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        for a in addrs:
            _add(a)
    except OSError:
        pass

    _lan_nets = (ipaddress.ip_network("10.0.0.0/8"),
                 ipaddress.ip_network("172.16.0.0/12"),
                 ipaddress.ip_network("192.168.0.0/16"))

    def _ok(ip: str) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return a.version == 4 and any(a in net for net in _lan_nets)

    return [ip for ip in found if _ok(ip)]     # insertion order: probe first


def lan_ip() -> str:
    """This machine's LAN address — the one the phone can actually reach.

    The default-route interface (see :func:`lan_ip_candidates`), which is right on
    a plain LAN and on a host with virtual/bridge adapters alike. Falls back to
    the raw probe, then loopback, if nothing RFC1918 is enumerable.
    """
    cands = lan_ip_candidates()
    if cands:
        return cands[0]
    return _route_probe_ip() or "127.0.0.1"




def _hour_label(ts: float) -> str:
    """'2 PM' for an hour block in the rewind timeline."""
    lt = time.localtime(ts)
    h = lt.tm_hour
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


class Brain(RCOps, CalendarOps, SocialOps, ReminderOps, WaypathOps, SourceOps):
    """The Brain's live state: config + index + history, rebuilt on change.

    The coordinator holds __init__/ask/_ask_cloud/save/config and inherits its
    cohesive method clusters from sibling mixins (RCOps, CalendarOps, SocialOps,
    ReminderOps, WaypathOps, SourceOps) — the same ops_* pattern the orchestrator
    uses. Every mixin method runs on this shared self.
    """

    def __init__(self, cfg_dir: Path | str, sources_fn=None, messages_fn=None,
                 calendar_reader_fn=None, calendar_list_fn=None):
        self.cfg_dir = Path(cfg_dir)
        # Harden the state dir owner-only ONCE, up front — before any config,
        # history, activity, or receipt-key file is created inside it — so every
        # secret-bearing file is born private BY INHERITANCE rather than at the
        # process umask (world-readable on a shared box). Previously only
        # store.save() hardened the dir, so a tokenless loopback run's
        # brain_history/activity.jsonl could be created world-readable before the
        # first save ever ran (audit 2026-07-19). Best-effort; never crashes ctor.
        try:
            from .store import _harden_state_dir
            self.cfg_dir.mkdir(parents=True, exist_ok=True)
            _harden_state_dir(self.cfg_dir)
        except OSError:
            pass
        # Serializes the cfg_dir JSON stores (agenda/people/contacts/reminders):
        # the server is threaded, so concurrent authed POSTs could otherwise
        # interleave a read-modify-write and lose or corrupt data (audit
        # 2026-07-14). Re-entrant so a helper can nest inside a held section.
        self._store_lock = threading.RLock()
        # Serializes the cloud-egress counter (config.cloud_calls). The threaded
        # server can run two cloud asks concurrently; a bare ``+= 1`` is a
        # non-atomic load-add-store that loses a count under that race, so the
        # ledger the panel promises ("every one is logged") could silently
        # undercount. A dedicated Lock — not the store RLock, which guards the
        # JSON files — keeps the critical section to just the increment
        # (audit 2026-07-17). Touch the counter only via ``bump_cloud_calls``.
        self._egress_lock = threading.Lock()
        self.config = BrainConfig.load(self.cfg_dir)
        self._env_disabled: set = set()
        self._sync_disabled_env()      # panel per-cap toggles must reach adapters
        self._ear = None               # the always-on ear (EarHost, the Mac's own mic)
        self._remote_ear = None        # the phone-fed ear (EarHost over RemoteMicSource)
        self._remote_mic = None        # the push buffer the phone streams into
        self._sync_ear_wired()         # ear caps read 'dormant' until it's running
        # the Live Lens event bus: the Brain PUSHES ambient cards (a sound-safety
        # tap, the morning brief, a commitment nudge) to connected phones over SSE
        self._event_subs: list = []    # one Queue per connected /live/events stream
        from .geo import LastFix
        self._last_fix = LastFix()     # in memory only; never written to disk
        self._zone_was = ""            # last announced zone, for edge detection
        self._event_lock = threading.Lock()
        # guards _spoken_intent, so a look POPS it in one step (concurrent
        # looks otherwise both saw the same utterance)
        self._intent_lock = threading.Lock()
        # Model supply-chain gate: when the wearer's posture is offline/incognito/
        # LAN-only, set HF_HUB_OFFLINE &co process-wide so NO ML loader (embedder,
        # ASR, speaker, CLIP…) can silently reach a CDN. One call gates every
        # HuggingFace-stack loader at once; re-applied on posture change via
        # _apply_model_posture(). Fail-safe: never raises, never blocks a load.
        self._apply_model_posture()
        self.history = QueryHistory(self.cfg_dir)
        # Hidden-layer discoveries (prism, junocolors, ...): a tiny persisted
        # set so a secret found once on any of this Brain's surfaces stays
        # found. Names only — nothing sensitive lives here.
        self._discoveries_path = self.cfg_dir / "discoveries.json"
        try:
            import json as _json
            loaded = _json.loads(self._discoveries_path.read_text())
            # Validate on LOAD, not just on write (add_discovery): a hand-edited
            # or attacker-planted discoveries.json must not inject arbitrary
            # strings into the set — which discoveries() reflects to clients, and
            # which (mixed str/int) would make its sorted() raise an unhandled
            # 500 on the GET. Keep only the known names (refute 2026-07-20).
            self._discoveries = {n for n in loaded
                                 if n in self._KNOWN_DISCOVERIES}
        except Exception:
            self._discoveries = set()
        self.activity = ActivityLog(
            self.cfg_dir, signer=activity_receipt_signer(self.cfg_dir),
            watermark=activity_receipt_watermark(self.cfg_dir))
        self.index = FileIndex(self.config)
        # W3: live memory sources (screenpipe/ActivityWatch/Immich/Dawarich) +
        # the LightRAG knowledge graph + the FSRS rehearsal store. All lazily
        # built by SourceOps and config-gated; None/0.0 until first use.
        self._graph = None
        self._graph_built = False
        self._src_stop: threading.Event | None = None
        self.last_sources_sync = 0.0
        self._rehearsal_store = None
        # Platform sources: macOS reads Messages/Mail/Calendar.app; Windows
        # reads Thunderbird mbox + .ics feeds (windows_sources). Each module
        # returns [] off its platform, so this dispatch only picks the honest
        # default — injected seams always win, and macOS wiring is unchanged.
        default_cal_list: Callable[..., Any]
        if platform.system() == "Windows":
            from . import windows_sources as _srcmod
            default_cal_list = lambda: _srcmod.list_calendars(config=self.config)  # noqa: E731
        else:
            from . import macos_sources as _srcmod  # type: ignore[no-redef]
            default_cal_list = _srcmod.list_calendars
        # message/mail documents (folded in when email is enabled)
        self._sources_fn = sources_fn or _srcmod.collect_documents
        # the live feed the glasses read hands-free (this box is the bridge)
        self._messages_fn = messages_fn or _srcmod.recent_messages
        # calendar → agenda sync (both are injectable seams for tests)
        self._calendar_reader = calendar_reader_fn or _srcmod.read_calendar_events
        self._calendar_lister = calendar_list_fn or default_cal_list
        # Contacts + Reminders readers (injectable seams for tests; the macOS
        # readers return [] anywhere else — there is no Windows equivalent to
        # read, and that absence is reported honestly, never stubbed)
        from .macos_sources import (read_contacts, read_reminders,
                                    list_reminder_lists, list_mail_accounts)
        self._contacts_reader = read_contacts
        self._reminders_reader = read_reminders
        self._reminder_lister = list_reminder_lists
        # the Mail accounts the panel's scope picker offers ([] = all)
        self._mail_account_lister = list_mail_accounts
        self._sig = None
        self._last_phone_ts = 0.0        # last authed request from off-box (the phone)
        self._started_ts = time.time()
        # per-seam failure ledger — the panel's answer to "why is it mush?"
        from ...orchestrator.health import HealthLedger
        self.health = HealthLedger()
        self.last_index_ts = 0.0
        self.email_docs = 0
        self.last_brief: dict | None = None
        self.last_long_brief: dict | None = None
        self._brief_ran_day: tuple[int, int] | None = None
        self._brief_stop: threading.Event | None = None
        self._cal_stop = None   # (BrainHost declares: threading.Event | None)
        self.last_calendar_sync = 0.0
        self.last_contacts_sync = 0.0
        self.last_reminders_sync = 0.0
        # Saga: the ecosystem progression the phone shows — ranks, level, and
        # achievements. Brain-hosted so the phone (and hub) can read/record it.
        from ...saga import SagaProfile
        self.saga = SagaProfile(self.cfg_dir)
        # Plugin marketplace (docs/MARKETPLACE.md): the Brain hosts the plugins
        # the user installs. Every package is validated (integrity + capability
        # scan + smoke test) before it's written; the panel and phone manage them.
        from ...plugins import PluginStore
        from ...plugins.store import load_first_party_pins
        # first_party = the reviewed first-party catalogue's content-hash pins
        # (plugins/first_party.json). It lets the bundled connector plugins run
        # in-process on Windows/Mac — where no kernel sandbox (bwrap/nsjail)
        # exists, so an unpinned plugin would fail closed and never execute.
        # Keyless: trust rides the reviewed source hash, not a signing secret.
        from ...plugins import registry_client as _regc
        self.plugins = PluginStore(self.cfg_dir / "plugins",
                                   host_capabilities=self.plugin_capabilities(),
                                   first_party=load_first_party_pins(),
                                   # pinned registry fetcher for the in-app store's
                                   # 1-click install (name → pinned package URL);
                                   # only called on install, so no egress at boot.
                                   fetch_fn=_regc.fetch_package)
        # Juno's profile of you (name, interests, people, remembered prefs).
        # Built on the glasses hub from the conversation stream, then *pushed*
        # here so the phone can read it — the hub->Brain bridge. Just a mirror;
        # the Brain never writes it, only stores what the hub sends.
        self.profile: dict = self._load_profile()
        # Social memory mirror (hub -> Brain, like the profile): everyone you've
        # met with their relation, notes, and debts, so the phone's People
        # screen can read and edit them. The hub owns the truth; this is a
        # mirror the phone drives.
        self.social_people: list = self._load_people()
        # Consent-based recognition: teach the person guard who you've MET, so an
        # introduced person is recognized (the Social Lens's point) and only a
        # genuine stranger is deferred. The guard reads this on every look; it's
        # mtime-cached, so this is a cheap closure over the roster.
        try:
            from ...object_lens import person_guard as _pg
            _pg.set_known_people(self.known_names)
        except Exception:                              # noqa: BLE001 — never fail Brain boot
            pass
        # Waypath: where you left your things. "I left my bike at the north rack"
        # → a spoken anchor; "where's my bike?" reads it back. Persisted so the
        # phone's typed-voice loop (stash then locate) is self-contained here,
        # independent of the glasses hub (which keeps its own IMU anchors).
        from ...orchestrator.waypath import WaypathLens
        self.waypath = WaypathLens()
        self._load_waypath()
        # …and the half that never existed: an anchor dropped because the
        # glasses SAW you walk away from something, not because you narrated
        # it. The ambient look loop feeds this (live._trail_frame); the tracker
        # is optional and gives it stable identity when supervision is
        # installed — `SupervisionTracker` has taken a centroid list since it
        # was written and nothing in the tree ever produced one.
        from ...orchestrator.object_trail import ObjectTrail
        tracker = None
        try:
            from ...dream_mode.track_supervision import SupervisionTracker
            tracker = SupervisionTracker()
        except Exception:                              # noqa: BLE001
            pass
        self.object_trail = ObjectTrail(tracker=tracker)
        # Reality Compiler v2 (the Rehearsal paradigm, docs/RC_V2_*.md): the
        # phone performs a behavior as beats; the Brain infers → verifies →
        # signs → hot-swaps a Figment. The vault (signed, on-device storage)
        # lives beside the Brain's config so kept figments persist. No bridge
        # is wired here yet, so deploys run in dry-run (they record the exact
        # BLE envelopes) until the glasses transport is attached.
        from ...reality_compiler.v2.compiler import RealityCompilerV2
        self.rc = RealityCompilerV2(vault_dir=self.cfg_dir / "vault")
        self._rc_pending: dict = {}          # figment_id → Figment awaiting keep
        self._rc_active = None  # the figment on stage (BrainHost declares: str | None)
        # emit→reaction capability handlers. A lens emits a capability tag, the
        # Brain runs the matching handler and streams the result back to the
        # glass — but only for a capability the active lens actually declared
        # (reality_compiler/v2/capabilities.py). `ask` is the one host-computed
        # reaction; `translate`/`look` carry their own payload (the phone/hub
        # did the work) and route straight to the slot.
        self._capability_handlers: dict = {"ask": self._cap_ask}
        self._watch_stop: threading.Event | None = None
        self._retention_stop: threading.Event | None = None
        # retention: drop logs older than the configured window on boot
        if self.config.retention_days:
            self.history.prune(self.config.retention_days)
            self.activity.prune(self.config.retention_days)
        # ...and age the MEMORY store out by the same lifecycle the docs
        # describe (hot 24 h / warm 90 d / cold forever). This is NOT gated on
        # retention_days: that setting is about the ask history and activity
        # LOG, and its 0 default means "keep logs forever" — the memory
        # lifecycle has its own windows in config.py, with their own defaults.
        # Until now nothing on the device expired at all (decisions/0001); the
        # sweep it wanted lives on an Orchestrator this Brain never builds, so
        # retention_live runs the same primitive against the Brain's own store.
        self.sweep_retention()
        self._wire_model()
        self.reindex()

    # -- plugin marketplace --------------------------------------------------

    def plugin_capabilities(self) -> frozenset:
        """What this Brain can safely grant a plugin. The always-available
        extension points, plus midi (the Mac has it); mesh + shop (the
        GhostMode-broadcast and TasteLens-connector seams — a plugin that emits
        to a mesh/shop that isn't wired just no-ops, same as perception/glance
        pre-hardware); vision when a vision model or cloud is available; network
        unless incognito. fs/subprocess are withheld — a plugin needing them is
        rejected."""
        caps = {"object_lens", "glance", "perception", "cards", "ring", "midi",
                "mesh", "shop"}
        if self.config.model == "ollama" or self.config.cloud_ready():
            caps.add("vision")
        if not self.config.lan_only:
            caps.add("network")
        # Billing-tier seam (no paywall today): the free plan grants everything
        # above; a future hosted plan would add its capabilities here. Kept as a
        # union so `free` never removes a capability — see BrainConfig.plan.
        caps |= PLAN_CAPS.get(getattr(self.config, "plan", "free"), frozenset())
        return frozenset(caps)

    def plan_summary(self) -> dict:
        """The Plan section's data: current plan, what Cloud adds (with human
        meaning), and which of those entitlements are active now. Union-only —
        the free plan's capabilities are never listed as removable."""
        plan = getattr(self.config, "plan", "free")
        cloud_caps = sorted(PLAN_CAPS.get("cloud", frozenset()))
        return {
            "plan": plan if plan in PLAN_CAPS else "free",
            "cloud_caps": [{"key": c, "info": PLAN_CAP_INFO.get(c, c),
                            "active": plan == "cloud"} for c in cloud_caps],
        }

    def plugins_state(self) -> dict:
        from ...plugins import PluginPackage
        installed = []
        for name in self.plugins.installed():
            try:
                pkg = PluginPackage.load(self.plugins.dir / name)
                m = pkg.manifest
                installed.append({"name": m.name, "version": m.version,
                                  "author": m.author, "official": m.official,
                                  "api": m.api, "requires": list(m.requires),
                                  "description": m.description, "long": list(m.long),
                                  "forwho": m.forwho, "screenshot": m.screenshot})
            except Exception:
                # a single unreadable/corrupt package must not blank the whole
                # list — degrade to a stub row, but record why (was a silent
                # pass that hid a broken install).
                log.warning("plugin %r failed to load for state listing",
                            name, exc_info=True)
                installed.append({"name": name, "version": "", "author": "", "requires": []})
        return {"installed": installed,
                "capabilities": sorted(self.plugin_capabilities())}

    def install_plugin(self, body: dict) -> dict:
        """Install a plugin, validated. Accepts a sideloaded package
        ({manifest, source}) or a registry name (needs a wired registry)."""
        from ...plugins import PluginPackage, PluginManifest, ValidationReport
        if body.get("source") and body.get("manifest"):
            pkg = PluginPackage(manifest=PluginManifest.from_dict(body["manifest"]),
                                source=str(body["source"]))
            report = self.plugins.install_package(pkg)
            label = pkg.manifest.name
        elif body.get("name"):
            report = self.plugins.install(str(body["name"]))
            label = str(body["name"])
        else:
            report = ValidationReport()
            report.add_error("provide a package (manifest+source) or a registry name")
            label = "?"
        if report.ok:
            self.activity.add("plugin", f"Installed plugin {label}")
            self._invalidate_world_lens()   # a new connector can join a look
        return {"ok": report.ok, "errors": report.errors,
                "warnings": report.warnings, "state": self.plugins_state()}

    _KNOWN_DISCOVERIES = ("prism", "junocolors")

    def discoveries(self) -> list:
        return sorted(self._discoveries)

    def add_discovery(self, name: str) -> bool:
        """Record a hidden-layer discovery. Unknown names are refused so the
        store can't be grown arbitrarily by a token holder."""
        if name not in self._KNOWN_DISCOVERIES:
            return False
        if name in self._discoveries:
            return True
        self._discoveries.add(name)
        try:
            import json as _json
            self._discoveries_path.write_text(_json.dumps(sorted(self._discoveries)))
        except Exception:
            pass                      # a failed write only forgets, never breaks
        return True

    def store_catalogue(self) -> dict:
        """The in-app plugin store: fetch the pinned registry catalogue and
        return it (each entry flagged with whether it's already installed). This
        is EGRESS to the registry, so it honors the wearer's posture — refused in
        Incognito / LAN-only. No wearer data leaves; only the catalogue comes
        back (fast-follow 2026-07-19)."""
        if self.incognito_now():
            return {"error": "the plugin store needs the network — you're in "
                             "Incognito or LAN-only right now"}
        from ...plugins import registry_client
        from ...plugins.store import RegistryIndex
        try:
            raw = registry_client.fetch_index()
        except Exception as e:                       # network / parse failure
            return {"error": f"couldn't reach the plugin store: {e}"}
        self.plugins.index = RegistryIndex.from_dict(raw)
        installed = set(self.plugins.installed())
        items = []
        for ent in self.plugins.index.entries:
            d = ent.to_dict()
            d["installed"] = ent.name in installed
            items.append(d)
        self.activity.add("plugin", "Browsed the plugin store")
        return {"plugins": items, "updated": str(raw.get("updated", ""))}

    def store_install(self, name: str) -> dict:
        """One-click install from the store: fetch the pinned package for `name`,
        verify the registry checksum, run the capability/sandbox gate, and write
        only if it passes — all via the existing PluginStore.install(). Posture
        gated like the catalogue."""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "errors": ["no plugin name"]}
        if self.incognito_now():
            return {"ok": False, "errors": ["the plugin store needs the network — "
                                            "you're in Incognito or LAN-only right now"]}
        # ensure the index is loaded so install() can verify the checksum against it
        if self.plugins.index.get(name) is None:
            cat = self.store_catalogue()
            if cat.get("error"):
                return {"ok": False, "errors": [cat["error"]]}
        report = self.plugins.install(name)
        if report.ok:
            self.activity.add("plugin", f"Installed {name} from the store")
            self._invalidate_world_lens()
        return {"ok": report.ok, "errors": report.errors,
                "warnings": report.warnings, "state": self.plugins_state()}

    def remove_plugin(self, name: str) -> dict:
        ok = self.plugins.remove(name)
        if ok:
            self.activity.add("plugin", f"Removed plugin {name}")
            self._invalidate_world_lens()   # its provider should leave a look too
        return {"ok": ok, "state": self.plugins_state()}

    def reindex(self) -> dict:
        self.index.reindex()
        self.email_docs = 0
        if self.config.email_enabled:
            try:
                docs = self._sources_fn(self.config)
                self.email_docs = len(docs)
                self.index.add_documents(docs)
            except Exception as exc:
                # degrade (keyword search still works) but on the record — a
                # silent pass here hid a broken mail source (audit 2026-07-14).
                self.health.record_failure("index:email", exc)
        # W3: fold the live local sources in too (when the wearer switched them
        # on) — a folder reindex also freshens screen/desk/photo/place memory.
        self.maybe_sync_sources()
        self._sig = self._signature()
        self.last_index_ts = time.time()
        return self.index.stats()

    # -- auto-reindex when watched folders change ------------------------

    def _signature(self):
        sig = []
        for folder in self.config.folders:
            base = Path(folder).expanduser()
            if base.is_dir():
                try:
                    for f in base.rglob("*"):
                        if f.is_file():
                            sig.append((str(f), f.stat().st_mtime_ns))
                except OSError:
                    # a folder that vanished or denied access mid-walk just
                    # contributes nothing to the change signature — genuinely
                    # ignorable (the next poll re-scans); narrowed to OSError.
                    pass
        return tuple(sorted(sig))

    def poll(self) -> bool:
        """Reindex if the watched folders changed since last scan."""
        if self._signature() != self._sig:
            self.reindex()
            return True
        return False

    def start_watching(self, interval: float = 3.0) -> None:
        if self._watch_stop is not None:
            return
        # React instead of asking. A watchdog observer per folder turns "a note
        # you saved becomes answerable within three seconds" into "…as you save
        # it", and stops a full stat sweep of every watched file twenty times a
        # minute forever. `fs_watch_live` debounces, because one save is many
        # events and `poll()` reindexes.
        started = 0
        try:
            from .fs_watch_live import IDLE_INTERVAL_S, watchers
            started = watchers(self).start()
        except Exception:                            # noqa: BLE001 — never fail boot
            log.warning("folder watchers unavailable", exc_info=True)
        if started:
            # The timer STAYS, slowed to insurance. Not for the missing-wheel
            # case — that one never reaches here — but because a watcher that
            # is running can still miss things: network mounts, some FUSE
            # filesystems and containerised bind-mounts deliver events
            # unreliably or not at all, which is why watchdog ships a polling
            # observer of its own. Dropping the sweep would go silent on
            # exactly the setups that were already weakest.
            interval = IDLE_INTERVAL_S
        self._watch_stop = threading.Event()

        def loop():
            while not self._watch_stop.wait(interval):
                try:
                    self.poll()
                except Exception:
                    # the watch thread must survive a bad scan (a vanished
                    # folder, a racing edit) — but log so a persistently dead
                    # watcher is visible instead of silently stopped.
                    log.warning("folder watch poll failed", exc_info=True)
        threading.Thread(target=loop, daemon=True).start()

    def stop_watching(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None
        # Observers run their own threads and a pending debounce holds a timer;
        # leaving either behind would reindex after the wearer asked us to stop.
        try:
            from .fs_watch_live import watchers
            watchers(self).stop()
        except Exception:                            # noqa: BLE001
            pass

    # -- the memory lifecycle (ai_brain/server/retention_live.py) -------------

    def sweep_retention(self) -> dict:
        """Age memory out by policy: warm rows past their window are deleted
        from the store (and their vectors from the ANN index), the live hot
        ring is dropped past its own. Cold entities, pinned rows and rows of
        unknown age are kept. Never raises — a failed sweep keeps everything."""
        try:
            from .retention_live import sweep_retention
            return sweep_retention(self)
        except Exception:                            # noqa: BLE001 — never fail boot
            log.warning("retention sweep failed", exc_info=True)
            return {"ok": False, "swept": 0, "expired": 0, "hot_purged": 0}

    def start_retention_scheduler(self, interval: float | None = None) -> None:
        """Turn the lifecycle over on a cadence, not just at boot.

        A Brain that stays up for a month would otherwise sweep once and then
        never again — "nothing ages out on its own" with extra steps — and the
        hot ring only ever has anything in it while the process is running, so
        boot is precisely the moment it is guaranteed to be empty."""
        if self._retention_stop is not None:
            return
        from .retention_live import SWEEP_INTERVAL_S
        every = SWEEP_INTERVAL_S if interval is None else interval
        self._retention_stop = threading.Event()
        stop = self._retention_stop

        def loop():
            while not stop.wait(every):
                try:
                    self.sweep_retention()
                except Exception:
                    # keep the thread alive across a bad sweep; log so a
                    # persistently failing lifecycle is visible, not silent.
                    log.warning("retention sweep run failed", exc_info=True)
        threading.Thread(target=loop, daemon=True).start()

    def stop_retention_scheduler(self) -> None:
        if self._retention_stop is not None:
            self._retention_stop.set()
            self._retention_stop = None

    def _wire_model(self) -> None:
        """Point the index/vision at the configured backend."""
        if self.config.model == "ollama":
            self._backend: OllamaBackend | MLXBackend | ExoClusterBackend | None = OllamaBackend(
                self.config, on_egress=self._note_model_egress)
            self.index.synthesizer = make_synthesizer(self._backend)
            self.index.embedder = (self._backend.embed
                                   if self.config.semantic_search else None)
        elif self.config.model == "mlx":
            # Apple-Silicon-native answer path (mlx-lm). Same chat() contract as
            # Ollama, so make_synthesizer works unchanged. Falls back to Ollama
            # if MLX isn't actually available on this machine.
            from ..mlx_backend import MLXBackend
            if MLXBackend.available:
                self._backend = MLXBackend(self.config)
                self.index.synthesizer = make_synthesizer(self._backend)
                self.index.embedder = None   # embeddings ride the embedder ladder
            else:
                self._backend = OllamaBackend(
                    self.config, on_egress=self._note_model_egress)
                self.index.synthesizer = make_synthesizer(self._backend)
                self.index.embedder = (self._backend.embed
                                       if self.config.semantic_search else None)
        elif self.config.model == "exo":
            # One model spread across the machines the wearer already owns. Text
            # only: `make_synthesizer` needs just `chat()`, and the vision router
            # tests for a `vision` method, so a look reports honestly blind
            # rather than raising into a swallowed AttributeError.
            #
            # Embeddings stay off for the same reason MLX leaves them off — exo
            # serves no embeddings endpoint, so semantic search would silently
            # degrade to keyword while the panel claimed it was on.
            from ..exo_cluster import ExoClusterBackend
            self._backend = ExoClusterBackend(
                base_url=self.config.exo_url, model=self.config.exo_model,
                config=self.config, on_egress=self._note_model_egress)
            self.index.synthesizer = make_synthesizer(self._backend)
            self.index.embedder = None
        else:
            # keyword AND api: the local index stays a pure keyword retriever.
            # For "api", the first-pass answer is routed to the external agent
            # in ask(); the keyword index is the graceful fallback for when that
            # endpoint is unreachable, or (if remote) silenced by the veil.
            self._backend = None
            self.index.synthesizer = None
            self.index.embedder = None
        # the World lens closes over this backend; a rewire means the next look
        # rebuilds against the new vision tier.
        self._world_lens = None
        # the knowledge graph also closes over the local backend (its LLM +
        # embedder) — a rewire re-arms the lazy build against the new tier.
        self._graph_built = False
        self._graph = None

    def save(self) -> None:
        self.config.save(self.cfg_dir)

    def _note_model_egress(self, url: str, remote: bool = True) -> None:
        """Record a model request that is about to leave this machine.

        `OllamaBackend` calls this before any non-loopback request, and tells us
        which kind it is. A REMOTE host is cloud egress: counted in `cloud_calls`
        and logged as `cloud-egress`. A LAN host is not cloud — folding it into
        the cloud counter would misreport it — but it is still another computer,
        so it gets its own `lan-model` ledger row. Either way the receipt stops
        describing it as "on your device". Never raises into the ask path."""
        try:
            host = urllib.parse.urlsplit(url).netloc or url
            if remote:
                self.bump_cloud_calls()
                self.activity.add("cloud-egress",
                                  f"Asked the model host {host[:60]}")
            else:
                self.activity.add("lan-model",
                                  f"Asked the model host {host[:60]} on your network")
            self.save()
        except Exception as exc:                     # noqa: BLE001
            log.debug("[brain] egress note failed: %s", exc)

    def bump_cloud_calls(self, n: int = 1) -> None:
        """Atomically advance the cloud-egress ledger (config.cloud_calls).

        Every egress site — both ask paths and the endpoint-test probe — routes
        its increment through here so the load-add-store runs under
        ``_egress_lock`` and can't lose a count when two egress events race on
        the threaded server (audit 2026-07-17). Small, targeted critical section:
        just the increment; the surrounding activity-log + save stay outside."""
        with self._egress_lock:
            self.config.cloud_calls += n

    def _sync_disabled_env(self) -> None:
        """Mirror config.disabled_caps into os.environ as DL_DISABLE_<KEY>=1, so
        the panel's per-capability toggle actually reaches the ADAPTERS (they read
        the env flag via capabilities.enabled/disabled), not merely the report.
        Before this the toggle only rewrote the report's local env copy, so
        "Turn off" was cosmetic at runtime. We only ever clear flags WE set (via
        _env_disabled), so a deploy-time DL_DISABLE_* the operator exported by
        hand — the documented ops-level override — is never stepped on."""
        import os as _os
        try:
            from ...capabilities import CAPABILITIES
        except Exception:
            return
        off = {c.flag_env for c in CAPABILITIES
               if c.key in set(self.config.disabled_caps or [])}
        for flag in self._env_disabled - off:      # re-enabled → clear only our own
            if _os.environ.get(flag) == "1":
                _os.environ.pop(flag, None)
        for flag in off:
            _os.environ[flag] = "1"
        self._env_disabled = off

    # -- the always-on ear (opt-in voice capture) --------------------------

    def _sync_ear_wired(self) -> None:
        """Reflect the ear's LIVE state into the capability report: while it's
        actually listening, set DL_WIRED_<KEY> for each cap it drives so they
        read 'active' (installed → really on); otherwise clear them so they read
        the honest 'dormant'. This is what keeps the awakening meter truthful —
        the voice caps count only while the microphone is genuinely open."""
        import os as _os
        from .ear import EAR_CAPS
        # Promote ONLY the caps the ear is genuinely driving right now (it tracks
        # them in active_caps — e.g. faster-whisper → local_asr, not moonshine/
        # onnx; a tagger only when one built). A blanket promotion would lie about
        # engines that aren't running (audit finding).
        # Either ear counts — the Mac's own mic (self._ear) OR the phone streaming
        # in (self._remote_ear). Union the caps each is genuinely driving right now.
        active: frozenset = frozenset()
        for _e in (self._ear, self._remote_ear):
            if _e is not None and _e.listening:
                active = active | _e.active_caps
                # `live_interpret` is NOT in `active_caps`, deliberately. That set
                # is fixed when the microphone opens, and interpreting is toggled
                # afterwards — and its honesty bit needs a segment to have come
                # back genuinely translated, which can only happen later still. So
                # it is asked for fresh here, every sync.
                if getattr(_e, "interpreting", False):
                    active = active | {"live_interpret"}
                # `wake_word` is asked fresh for the same reason and on a
                # stricter test: not "a spotter was built" but "a spotter has
                # FIRED on this run". `hear()` answers on the text regex too,
                # and that has always worked — the capability being measured is
                # the acoustic engine, so only its own hits may promote it.
                try:
                    if _e.wake_live():
                        active = active | {"wake_word"}
                except Exception:                # noqa: BLE001
                    pass
        # `onnx_speech` is asked of the BRAIN, not of either ear: one engine
        # backs up to four seams and both ears share it, so counting it per-ear
        # would double it and tie it to whichever ear happened to be open. The
        # proof is an adapter having produced a real ANSWER — every one of them
        # has a null it can return forever with no model loaded, and
        # `SherpaVAD`'s null is `True`, which would look like a working gate.
        try:
            _sh = getattr(self, "_sherpa_stack", None)
            if _sh is not None and _sh.driving():
                active = active | {"onnx_speech"}
        except Exception:                        # noqa: BLE001
            pass
        for key in EAR_CAPS:
            flag = "DL_WIRED_" + key.upper()
            if key in active:
                _os.environ[flag] = "1"
            else:
                _os.environ.pop(flag, None)

    def start_ear(self, mic=None) -> dict:
        """Open the always-on ear IF the wearer has opted in (listen_enabled).
        Best-effort and non-fatal: a missing engine/mic returns {ok:False,...}
        and changes nothing. Refreshes the capability report either way."""
        if not getattr(self.config, "listen_enabled", False):
            return {"ok": False, "reason": "disabled",
                    "detail": "turn Listening on first"}
        if self._ear is None:
            from .ear import EarHost
            self._ear = EarHost(self)
            # A fresh EarHost starts with the interpreter OFF, so the persisted
            # setting is pushed in AT CONSTRUCTION rather than after a successful
            # start. A wearer whose start fails for want of a speech engine, then
            # installs the pack and retries, must not need a second toggle to get
            # back the interpreter they already turned on.
            self._apply_interpret()
            self._apply_truth_lens()
        try:
            res = self._ear.start(mic)
        except Exception as exc:                    # noqa: BLE001 — never fatal
            log.error("[ear] start failed: %s", exc)
            res = {"ok": False, "reason": "error", "detail": str(exc)}
        self._sync_ear_wired()
        if res.get("ok"):
            self.activity.add("ear", "Listening turned on (on-device voice capture)")
        return res

    def stop_ear(self) -> None:
        """Close the ear and mark its capabilities dormant again."""
        if self._ear is not None:
            self._ear.stop()
            self.activity.add("ear", "Listening turned off")
        self._sync_ear_wired()

    def ear_status(self) -> dict:
        """Live ear state for the panel: whether it's listening and how much it's
        heard. Includes `enabled` (the persisted opt-in) so the switch and the
        runtime state can disagree honestly (opted-in but no mic, say)."""
        st = self._ear.status() if self._ear is not None else {
            "listening": False, "heard_count": 0, "last_heard": ""}
        st["enabled"] = bool(getattr(self.config, "listen_enabled", False))
        # the phone can be the live mic instead of (or besides) the Mac's own —
        # report whether a phone stream is currently driving an ear
        st["remote_listening"] = bool(self._remote_ear is not None
                                      and self._remote_ear.listening)
        st["remote_enabled"] = bool(getattr(self.config,
                                            "remote_listen_enabled", False))
        # The room read's persisted opt-in, alongside the runtime facts the ear
        # already reported — so the switch and what it is actually doing can
        # disagree honestly (opted in, but no microphone open yet).
        st["truth_enabled"] = bool(getattr(self.config,
                                           "truth_lens_enabled", False))
        return st

    def dream_neural_ready(self) -> bool:
        """Has the NEURAL dream painter genuinely produced a picture, and can it
        still? Two conditions, and both are needed.

        Proof (`_dream_neural_ok`, set by the dream lens on a real painting) is
        what stops onnxruntime's mere presence reading as a working painter — the
        wheel imports long before a model loads, and a loaded session can still
        fail on a frame. The path check is what stops the proof outliving the
        setup: clearing the model path must take the capability back down, because
        "it worked once this process" is not "it works now".
        """
        if not getattr(self, "_dream_neural_ok", False):
            return False
        try:
            return bool(self.world_lens()._dream_model_path())
        except Exception:                        # noqa: BLE001
            return False

    def dream_state(self) -> dict:
        """What the panel needs to describe the painter honestly."""
        path = str(getattr(self.config, "dream_model_path", "") or "").strip()
        resolved = ""
        try:
            resolved = self.world_lens()._dream_model_path()
        except Exception:                        # noqa: BLE001
            resolved = ""
        import os as _os
        return {
            "path": path,
            # A path that is set but does not resolve is the case worth surfacing:
            # the wearer thinks the neural painter is on and is getting the wash.
            "found": bool(resolved),
            "from_env": bool(_os.environ.get("DL_DREAM_MODEL")),
            "proved": bool(getattr(self, "_dream_neural_ok", False)),
            "active": self.dream_neural_ready(),
        }

    def set_interpret(self, on: bool = True, target: str = "") -> dict:
        """Turn the live interpreter on/off across BOTH ears and persist it.

        Both, because the Mac's own microphone and the phone acting as the mic are
        two `EarHost`s and the wearer set one switch — a toggle that reached only
        the local ear would look dead to anyone using the Live Lens as their mic,
        which is the more likely way to use an interpreter at all (it is the ear
        you take to the conversation).

        Persisted so it survives a restart, and reported back with what is
        actually true rather than what was asked for.
        """
        tgt = (str(target or "").strip()
               or getattr(self.config, "interpret_target", "en") or "en")
        self.config.interpret_enabled = bool(on)
        self.config.interpret_target = tgt[:8]
        self.save()
        out: dict = {"ok": True, "on": bool(on), "target": self.config.interpret_target}
        for ear in (self._ear, self._remote_ear):
            if ear is not None:
                out = ear.set_interpret(bool(on), self.config.interpret_target)
        # A capability that just stopped being driven must go dormant now, not at
        # the next poll — the same reason start/stop_ear both re-sync.
        self._sync_ear_wired()
        if on and not out.get("can_interpret"):
            # Honest, and NOT an error: the switch is legitimately set, it simply
            # cannot do anything until the pack is installed. The wearer sees the
            # reason instead of a dead toggle.
            log.info("[interpret] enabled with no interpreter installed")
        self.activity.add("ear", "Live interpreter turned %s (%s)"
                          % ("on" if on else "off", self.config.interpret_target))
        return out

    def _apply_interpret(self) -> None:
        """Push the persisted interpreter setting into an ear that just opened.

        Without this the setting was write-only across a restart: `EarHost` is
        constructed fresh with `_interpret_on = False`, so a wearer who had the
        interpreter on, restarted the Brain and turned Listening back on would get
        a silent ear and a panel switch that said it was on.
        """
        on = bool(getattr(self.config, "interpret_enabled", False))
        tgt = getattr(self.config, "interpret_target", "en") or "en"
        for ear in (self._ear, self._remote_ear):
            if ear is not None:
                try:
                    ear.set_interpret(on, tgt)
                except Exception:                    # noqa: BLE001 — never block
                    pass

    def set_truth_lens(self, on: bool = True) -> dict:
        """Turn "Read the room" on/off across BOTH ears and persist it.

        Both ears for the same reason the interpreter reaches both: the Mac's own
        microphone and the phone acting as the mic are two `EarHost`s and the
        wearer set one switch. The phone is the more likely one here — it is the
        ear you carry into the conversation you actually wanted read.
        """
        self.config.truth_lens_enabled = bool(on)
        self.save()
        out: dict = {"ok": True, "on": bool(on)}
        for ear in (self._ear, self._remote_ear):
            if ear is not None:
                try:
                    out = ear.set_truth(bool(on))
                except Exception:                    # noqa: BLE001 — never block
                    pass
        self.activity.add("ear", "Room read turned %s" % ("on" if on else "off"))
        return out

    def _apply_truth_lens(self) -> None:
        """Push the persisted room-read setting into an ear that just opened.

        Same write-only-setting trap `_apply_interpret` exists to close: a fresh
        `EarHost` builds its `TruthRead` switched OFF, so without this a wearer
        who had the read on, restarted, and turned Listening back on would get a
        silent gauge under a switch that said it was running."""
        on = bool(getattr(self.config, "truth_lens_enabled", False))
        for ear in (self._ear, self._remote_ear):
            if ear is not None:
                try:
                    ear.set_truth(on)
                except Exception:                    # noqa: BLE001 — never block
                    pass

    def hear_remote(self, pcm) -> dict:
        """The phone is the live mic: feed a chunk of the audio it captured
        on-device into the ear. The wearable hears the room you're in, not the
        room the Mac sits in — that's the point.

        Same gates as the local ear, by construction: OFF unless the wearer
        opted in (listen_enabled); the Veil wins (EarHost drops every utterance
        while incognito/quiet-hours — nothing is stored); PII is scrubbed before
        any write; transcription is on-device; nothing is uploaded. Lazily opens
        a remote-fed ear on the first chunk and pushes `pcm` (mono floats already
        at SAMPLE_RATE) into it; the phone ends it by toggling off (stop_remote_
        ear) or going silent (the endpoint times it out). Never raises."""
        if not getattr(self.config, "remote_listen_enabled", False):
            return {"ok": False, "reason": "disabled",
                    "detail": "turn on Listening on the Live Lens first"}
        if self._remote_ear is None:
            from .ear import EarHost
            self._remote_ear = EarHost(self)
            self._apply_interpret()      # see start_ear: at construction, not
            self._apply_truth_lens()     # after a start that may not succeed
        if self._remote_mic is None:
            from ...orchestrator.capture import RemoteMicSource
            self._remote_mic = RemoteMicSource()
        if not self._remote_ear.listening:
            try:
                res = self._remote_ear.start(self._remote_mic)
            except Exception as exc:                 # noqa: BLE001 — never fatal
                log.error("[ear] remote start failed: %s", exc)
                return {"ok": False, "reason": "error", "detail": str(exc)}
            if not res.get("ok"):
                return res                           # e.g. no on-device ASR engine
            self._sync_ear_wired()
            self.activity.add("ear", "Phone became the live mic (on-device voice)")
        if pcm:
            try:
                self._remote_mic.push(pcm)
            except Exception:                        # noqa: BLE001 — never 500 a look
                pass
        return {"ok": True, "remote_listening": True,
                **self._remote_ear.status()}

    def stop_remote_ear(self) -> None:
        """Stop the phone-fed ear (the phone toggled Listening off or went away)
        and mark its capabilities dormant again if no other ear is running."""
        if self._remote_ear is not None:
            self._remote_ear.stop()
            self.activity.add("ear", "Phone stopped being the live mic")
        self._sync_ear_wired()

    # -- the Live Lens event bus (Brain → phone push, over SSE) ------------

    def subscribe_events(self):
        """Register a new /live/events stream. Returns a bounded Queue the SSE
        handler drains, or None when the small subscriber cap is reached (a
        handful of phones — an SSE stream holds a worker thread, so the cap keeps
        long-lived streams from starving the request pool)."""
        import queue
        q: "queue.Queue" = queue.Queue(maxsize=64)
        with self._event_lock:
            if len(self._event_subs) >= MAX_EVENT_SUBS:
                return None
            self._event_subs.append(q)
        # DELIBERATELY NOT a posture greeting on this queue. Enqueueing one here
        # was tried and reverted: a fresh subscription yielding an EMPTY queue is
        # a contract 21 tests across three files encode on purpose, because it is
        # what makes "this push reached N streams" checkable at all. Announcing
        # the posture to a connecting phone is worth something; it is not worth
        # making every push-counting assertion in the suite conditional on a
        # greeting. Posture reaches the glass through `announce_posture` on the
        # transition, which is the moment that actually changes what is true.
        return q

    MAX_PRIVATE_ZONES = 32

    def edit_zones(self, action: str, name: str = "", radius_m: float = 150.0) -> dict:
        """Add or remove a private zone. Add uses the CURRENT position.

        A dedicated route rather than raw `private_zones` config writes, for two
        reasons: a client editing the list wholesale can drop a zone by
        accident, and nobody is going to hand-enter a coordinate. "Make HERE a
        private zone" is the only ergonomic way to create one, and it needs a
        fix the client does not have to know about.

        The count is capped — every zone is a haversine on every position
        report, and an unbounded list is a slow `incognito_now()` on the hot
        path every gate calls.
        """
        action = (action or "").strip().lower()
        name = (name or "").strip()[:48]
        zones = list(getattr(self.config, "private_zones", None) or [])
        if action == "remove":
            if not name:
                return {"ok": False, "error": "which zone?"}
            keep = [z for z in zones if str((z or {}).get("name") or "").strip().lower()
                    != name.lower()]
            if len(keep) == len(zones):
                return {"ok": False, "error": "no zone by that name"}
            self.config.private_zones = keep
            self.save()
            self.activity.add("privacy", "Removed a private zone")
            # Leaving the list may lift the shield — re-evaluate and announce,
            # or the glass keeps a "capture suspended" card for a zone that no
            # longer exists.
            self._resync_zone()
            return {"ok": True, "zones": self.zone_list()}
        if action != "add":
            return {"ok": False, "error": f"unknown action: {action}"}
        if len(zones) >= self.MAX_PRIVATE_ZONES:
            return {"ok": False,
                    "error": f"at most {self.MAX_PRIVATE_ZONES} zones"}
        fix = self.here()
        if not fix:
            return {"ok": False, "error": "no-fix",
                    "detail": "the phone has not reported a position yet"}
        try:
            radius = float(radius_m)
        except (TypeError, ValueError):
            radius = 150.0
        # A zero or negative radius is a zone that can never match — a shield
        # the wearer thinks they have and does not. Clamped, not accepted.
        radius = max(10.0, min(radius, 5000.0))
        if any(str((z or {}).get("name") or "").strip().lower() == name.lower()
               for z in zones) and name:
            return {"ok": False, "error": "a zone by that name already exists"}
        zones.append({"name": name or "this area", "lat": fix["lat"],
                      "lon": fix["lon"], "radius_m": radius})
        self.config.private_zones = zones
        self.save()
        self.activity.add("privacy", "Added a private zone")
        self._resync_zone()
        return {"ok": True, "zones": self.zone_list()}

    def zone_list(self) -> list:
        """The zones, with whether the wearer is inside each right now."""
        here = self.here()
        out = []
        for z in getattr(self.config, "private_zones", None) or []:
            if not isinstance(z, dict):
                continue
            inside = False
            if here:
                try:
                    from .geo import haversine_m
                    inside = haversine_m(float(z["lat"]), float(z["lon"]),
                                         here["lat"], here["lon"]) <= float(z["radius_m"])
                except (KeyError, TypeError, ValueError):
                    inside = False
            out.append({"name": z.get("name") or "this area",
                        "radius_m": z.get("radius_m"),
                        "lat": z.get("lat"), "lon": z.get("lon"),
                        "inside": inside})
        return out

    def _resync_zone(self) -> None:
        """Re-evaluate zone membership after the LIST changed rather than after
        the position did, and announce a crossing if one happened.

        Editing zones can cross the boundary without the wearer moving an inch:
        deleting the zone you are standing in lifts the shield, and adding one
        raises it. Without this the card and the shield disagree until the next
        position report."""
        zone = self.private_zone_now()
        if zone == self._zone_was:
            return
        self._zone_was = zone
        if zone:
            self.announce_posture(True, zone=zone)
        else:
            self.announce_posture(bool(self.incognito_now()))

    def note_location(self, lat, lon, accuracy_m=0.0,
                      heading_deg=None) -> dict:
        """Take a position report and announce any zone the wearer just crossed.

        NOT veil-gated, and that is a deliberate exception rather than an
        oversight. A private zone contributes to `incognito_now()`, so refusing
        fixes while incognito would mean the Brain could never learn it had
        LEFT a zone — the shield would latch on the first entry and stay up
        forever. This is the input that decides the shield; it cannot be gated
        on the shield's own output. Nothing is stored: the fix lives in memory
        and dies with the process.
        """
        from .geo import valid_coord
        if not valid_coord(lat, lon):
            return {"ok": False, "error": "not a coordinate"}
        self._last_fix.set(lat, lon, accuracy_m, heading_deg=heading_deg)
        zone = self.private_zone_now()
        if zone != self._zone_was:
            entered, self._zone_was = zone, zone
            # ENTERING draws the zone card; LEAVING hands off to the ordinary
            # posture announcement, which pushes ReadyCard — and that matters
            # for the same reason it did for the veil pair: `private_zone_card`
            # is `dismiss_ms: 0`, so without something replacing it the glass
            # keeps promising "capture suspended" after capture resumed.
            if entered:
                self.announce_posture(True, zone=entered)
            else:
                self.announce_posture(bool(self.incognito_now()))
            try:
                self.activity.add("privacy", "Entered a private zone"
                                  if entered else "Left a private zone")
            except Exception:                       # noqa: BLE001
                pass
        return {"ok": True, "zone": zone, "veiled": bool(self.incognito_now())}

    def announce_posture(self, veiled: bool, zone: str = "") -> int:
        """Draw the privacy shield going up or coming down.

        `privacy_veil()` and `ready()` are both declared HUD features that no
        shipped Brain could produce — `decisions/0001` at the card layer, and
        the pair has to be wired TOGETHER rather than one at a time:

          * VEIL UP pushes `veil_ok=True`. This is not borrowing the safety
            flag loosely — it is the only way the card can exist. `push_event`
            drops every non-`veil_ok` push while `incognito_now()`, so a card
            announcing the shield would be suppressed by the shield. It meets
            the stated bar for the flag: it carries NO captured content (the
            builder takes no arguments and emits two fixed strings). The flag
            also stamps `safety: true` on the envelope, which is read only by
            the server's own queue-eviction policy — no client branches on it.

          * VEIL DOWN pushes `ready()`, and this half is the load-bearing one.
            PrivacyVeilCard is `dismiss_ms: 0` — stays until replaced — so
            without something to replace it the glass would keep reading
            "Nothing is being captured" after capture resumed. A stale card is
            usually cosmetic; a stale PRIVACY card is a false assurance, which
            is the worst error this product can make. `ready()` is the honest
            successor state: the Brain is live again.
        """
        from ...hud import cards
        try:
            if veiled:
                # A zone names WHERE the shield came from; a plain veil cannot.
                # Same `veil_ok=True` and for the same reason — the card would
                # otherwise be suppressed by the shield it is announcing.
                card = (cards.private_zone_card(zone) if zone
                        else cards.privacy_veil())
                return self.push_event(
                    "private_zone" if zone else "privacy_veil", card, veil_ok=True)
            return self.push_event("ready", cards.ready(), veil_ok=False)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[brain] posture card push failed: %s", type(exc).__name__)
            return 0

    def unsubscribe_events(self, q) -> None:
        with self._event_lock:
            try:
                self._event_subs.remove(q)
            except ValueError:
                pass

    # ---------------------------------------------------------------- what
    # may interrupt you. Classified by KIND at the one funnel every card goes
    # through, rather than by a flag threaded through twenty call sites — the
    # threading is how a new push site ends up ungated without anyone noticing.

    #: Cards the Brain surfaces UNASKED. "Proactive cards" in the phone's own
    #: words: "let the glasses surface the right card unasked — events,
    #: arrivals, people". Everything not in here is a response to something the
    #: wearer did (pinning a memory, freezing a thought, asking to rewind) or a
    #: feature they switched on that is now doing its job, and suppressing
    #: either would be answering a question with silence.
    PROACTIVE_KINDS = frozenset({
        "proactive_memory", "commitment_recall", "commitment_drift", "brief",
        "object_recall", "they_said", "candor", "hark",
    })

    #: …and which of the three cue kinds each belongs to, for the app's picker.
    #: `hark` is deliberately absent: it is the tap-on-the-shoulder tier and has
    #: its own switch, so filing it under a cue would give it two masters.
    CUE_OF_KIND = {
        "brief": "event", "commitment_recall": "event",
        "commitment_drift": "event",
        "proactive_memory": "person", "they_said": "person", "candor": "person",
        "object_recall": "place",
    }

    #: Focus mode hushes more than the proactive set — the phone says "cards,
    #: captions, and pop-ups hush; capture keeps running (unlike incognito)".
    #: So the live feeds join the list, and only DIRECT RESPONSES survive:
    #: ready, saved_memory, forget_last, consent_required, stasis, quest_reward,
    #: time_scrub. Capture is untouched either way, which is the whole
    #: difference between this and the Veil.
    FOCUS_HUSHED = PROACTIVE_KINDS | frozenset({
        "caption", "interpret", "truth", "answer_ahead", "fact_check", "intro",
        "listening",
    })

    def _may_interrupt(self, kind: str) -> bool:
        """Is the wearer accepting this kind of interruption right now?

        Fails OPEN, unlike the Veil, and the asymmetry is the point: an
        unreadable *preference* must not silence a smoke alarm, while an
        unreadable *posture* must not leak. Getting these two backwards is how a
        privacy control becomes a reliability bug or the reverse.
        """
        try:
            cfg = self.config
            if getattr(cfg, "focus_mode", False) and kind in self.FOCUS_HUSHED:
                return False
            if kind not in self.PROACTIVE_KINDS:
                return True
            if not getattr(cfg, "proactive_cards", True):
                return False
            if kind == "hark":
                return bool(getattr(cfg, "proactive_alerts", True))
            cue = self.CUE_OF_KIND.get(kind)
            if cue is not None:
                return bool(getattr(cfg, f"cue_{cue}", True))
            return True
        except Exception:                            # noqa: BLE001 — see above
            return True

    @staticmethod
    def _lua_root() -> str:
        """The `halo-lua/` bundle in a source checkout, or "" from a wheel.

        Empty is not a failure: a Halo already running the app is driven fine
        without a fresh bundle push, and refusing to connect over a missing
        source tree would strand a working pair of glasses on every packaged
        install.
        """
        try:
            root = Path(__file__).resolve().parents[5] / "halo-lua"
            return str(root) if root.is_dir() else ""
        except Exception:                            # noqa: BLE001
            return ""

    def halo_connect(self, kind: str = "emulator", lua_root: str = "") -> dict:
        """Bring up the link to the glasses and start forwarding cards.

        The link joins `_event_subs` — the same fan-out the Live Lens SSE
        stream joins — so every producer in the Brain reaches the glass without
        knowing the glass exists.
        """
        try:
            from .halo_link import build_bridge, link
            ln = link(self)
            if ln.bridge is None:
                ln.bridge = build_bridge(kind)
            if ln.bridge is None:
                return {"ok": False, "reason": f"bridge {kind!r} unavailable"}
            if not lua_root:
                lua_root = self._lua_root()
            return ln.connect(lua_root)
        except Exception as exc:                     # noqa: BLE001
            log.warning("halo connect failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "unavailable"}

    def halo_disconnect(self) -> dict:
        try:
            from .halo_link import link
            return link(self).disconnect()
        except Exception:                            # noqa: BLE001
            return {"ok": False, "reason": "unavailable"}

    def halo_status(self) -> dict:
        try:
            from .halo_link import link
            return link(self).status()
        except Exception:                            # noqa: BLE001
            return {"connected": False, "sent": 0, "driving": False}

    def observe_card(self, kind: str, confidence, dismissed: bool) -> bool:
        """Record the wearer's reaction to one card. True if it became a label.

        This is the input side of the only learned control in the Brain, and it
        is the half that did not exist: `dismiss_ms` is a client-side expiry
        timer, so nothing ever told the Brain that a card was swatted.
        """
        try:
            from .attention_live import gate
            return gate(self).observe(kind, confidence, dismissed)
        except Exception as exc:                     # noqa: BLE001
            log.debug("[attention] could not record: %s", type(exc).__name__)
            return False

    def attention_summary(self) -> dict:
        """What the gate has learned, for the panel and the capability probe."""
        try:
            from .attention_live import gate
            return gate(self).summary()
        except Exception:                            # noqa: BLE001
            return {"labelled": 0, "swatted": 0, "bar": 0.0, "fitted": False}

    def lucid_query(self, text: str = "", frame=None) -> dict:
        """One question, routed to the face or the memory (`lucid_live`)."""
        try:
            from .lucid_live import lucid
            return lucid(self).query(text, frame)
        except Exception as exc:                     # noqa: BLE001
            log.warning("lucid query failed: %s", type(exc).__name__)
            return {"ok": False, "answer": "", "kind": "unknown",
                    "confidence": 0.0}

    def dream_pose(self, pose: dict, colors=None, amplitude: float = 0.0,
                   fft=None) -> dict:
        """One Dream Mode beat from the phone: head pose, and the light here.

        Two lenses ride this. The pose drives **Yesterlight** — a held upward
        look dials the Horizon back through the day. The colours, when the phone
        sends them, are recorded into the weather ledger so there IS a past to
        walk back into; a place with nothing recorded correctly refuses to arm
        rather than inventing an ambience it never saw.

        The place signature comes from the Brain rather than the phone: a client
        that could name its own place could replay somebody else's.
        """
        try:
            from .dream_reactors import reactors
            r = reactors(self)
            place = ""
            try:
                place = str(self.private_zone_now() or "") or str(
                    getattr(self, "_zone_was", "") or "")
            except Exception:                        # noqa: BLE001
                place = ""
            # The phone sends the raw SPECTRUM and the Brain decides the
            # weather, so the palette logic lives in `MicReactor` once rather
            # than being re-derived in JavaScript. `colors` is still accepted
            # for a caller that has already computed them (the ledger takes
            # either), but `fft` is the path that lights both surfaces.
            if fft:
                r.note_mic(fft, amplitude, place)
            elif colors:
                r.note_weather(place, colors, amplitude)
            sent = r.note_pose(pose if isinstance(pose, dict) else {}, place)
            return {"ok": True, "frames": sent, **r.status()}
        except Exception as exc:                     # noqa: BLE001
            log.warning("dream pose failed: %s", type(exc).__name__)
            return {"ok": False, "frames": 0}

    def dream_status(self) -> dict:
        try:
            from .dream_reactors import reactors
            return reactors(self).status()
        except Exception:                            # noqa: BLE001
            return {"timbre_frames": 0, "yesterlight_frames": 0,
                    "yesterlight_active": False}

    def push_raw(self, frame: dict) -> int:
        """Fan a RAW dream frame out to every connected surface.

        Dream Mode's reactors paint the rim and the Horizon directly rather than
        raising a card — `{"t": "timbre", …}`, `{"t": "yesterlight", …}` — so
        they cannot ride `push_event`, whose payload slot is a card the Live
        Lens renders.

        The Veil is applied here and NOT skippable: every raw frame this method
        carries derives from live signal (who is speaking, where you are, what
        the light was), so `veil_ok` has no meaning for it. The bridge applies
        its own `pause_allows_raw` gate on top, which is the device's rule
        rather than the wearer's posture — both hold.
        """
        if not isinstance(frame, dict) or not frame.get("t"):
            return 0
        try:
            if self.incognito_now():
                return 0
        except Exception:                            # noqa: BLE001 — unreadable → drop
            return 0
        ev = {"kind": "raw", "safety": False, "raw": dict(frame)}
        with self._event_lock:
            subs = list(self._event_subs)
        sent = 0
        for q in subs:
            try:
                q.put_nowait(ev)
                sent += 1
            except Exception:                        # noqa: BLE001 — full, drop
                continue
        return sent

    def _attention_allows(self, kind: str, card) -> bool:
        """The learned interruption bar (`attention_live`). Fails OPEN, like
        `_may_interrupt` and for the same reason.

        The confidence is read off the CARD rather than threaded through every
        `push_event` call site: the builders in `hud/cards.py` already put it
        there for rendering (`conf_color`), so the number the wearer sees on the
        card is the same number the gate judges. A second, hand-passed value
        could drift from the drawn one, and then the gate would be reasoning
        about a confidence nobody was ever shown.
        """
        try:
            if not isinstance(card, dict):
                return True
            from .attention_live import gate
            return gate(self).allows(kind, card.get("confidence"))
        except Exception:                            # noqa: BLE001 — see above
            return True

    def push_event(self, kind: str, card=None, veil_ok: bool = False) -> int:
        """Fan a card out to every connected Live Lens. Veil-gated by default:
        an ambient push (the morning brief, a memory nudge) is SUPPRESSED while
        incognito / quiet-hours — the glasses stay quiet under the shield.
        `veil_ok=True` is for categorical safety alerts (a smoke alarm) that carry
        no captured content. Fails closed (drops) on an unreadable posture. A slow
        client's full queue drops the event for that client, never blocks. Returns
        how many streams it reached."""
        if not veil_ok:
            try:
                if self.incognito_now():
                    return 0
            except Exception:                        # noqa: BLE001 — unreadable → drop
                return 0
            # …and then the wearer's interruption preferences. AFTER the Veil,
            # never instead of it: a preference is about attention, the Veil is
            # about the record, and a card allowed by one still has to clear the
            # other. `veil_ok` skips both — a categorical safety alert is not a
            # notification the wearer opted out of.
            if not self._may_interrupt(kind):
                return 0
            # …and last, the bar the wearer's own swats set. AFTER the two
            # above and never instead of either: this is the softest of the
            # three — a preference the wearer never stated in words, inferred
            # from what they swatted away — so it gets the least authority and
            # the most conservative failure. Only proactive kinds, only cards
            # that state a confidence, and open on anything unreadable.
            if kind in self.PROACTIVE_KINDS and not self._attention_allows(kind, card):
                return 0
        ev: dict = {"kind": kind, "safety": bool(veil_ok)}
        if isinstance(card, dict):
            ev["card"] = card
        with self._event_lock:
            subs = list(self._event_subs)
        sent = 0
        for q in subs:
            try:
                q.put_nowait(ev)
                sent += 1
            except Exception:                        # noqa: BLE001 — full
                # A stalled reader (backgrounded phone, TCP zero-window) is exactly
                # the state in which a smoke alarm matters most, and the default
                # policy drops the NEWEST event — so a burst of ambient cards could
                # bury the one that matters. A SAFETY push instead evicts the oldest
                # non-safety event to make room, and only gives up if the queue is
                # somehow all safety (audit 2026-07-23).
                if not veil_ok:
                    continue
                if self._evict_for_safety(q):
                    try:
                        q.put_nowait(ev)
                        sent += 1
                    except Exception:                # noqa: BLE001
                        pass
        return sent

    @staticmethod
    def _evict_for_safety(q) -> bool:
        """Drop the oldest non-safety event from a full queue. True if room was
        made. Order is preserved for everything kept."""
        kept = []
        dropped = False
        try:
            while True:
                try:
                    item = q.get_nowait()
                except Exception:                    # noqa: BLE001 — empty
                    break
                if not dropped and not (isinstance(item, dict) and item.get("safety")):
                    dropped = True                   # this one makes the room
                    continue
                kept.append(item)
            for item in kept:                        # put the survivors back in order
                try:
                    q.put_nowait(item)
                except Exception:                    # noqa: BLE001
                    break
        except Exception:                            # noqa: BLE001 — never break a push
            return False
        return dropped

    # Self-test kinds → the card the real publisher would push, built by the SAME
    # hud.cards builders and rendered by the SAME phone renderers. Every one is
    # stamped selftest=True so it can never be mistaken for the real event.
    # "nudge" was removed: NudgeCard had no cards.py builder, no bespoke renderer
    # and no publisher anywhere, so self-testing it demonstrated a card the Brain
    # never emits (audit 2026-07-23).
    SELFTEST_KINDS = ("hark", "brief")
    MAX_SELFTEST_PER_MIN = 6

    def push_selftest(self, kind: str = "hark") -> dict:
        """Push ONE clearly-labelled self-test card to every connected Live Lens.

        This exists because the ambient half of the HUD was undemonstrable: a
        sound-safety tap needs a real smoke alarm (plus the sound-events pack) and
        the brief only self-pushes at its configured hour, so there was no way to
        prove the push channel and the card renderers actually work end to end.

        Honesty rules this deliberately obeys:
          * the card is stamped ``selftest: True`` and carries a SELF-TEST eyebrow,
            so it never masquerades as a real alarm or a real brief;
          * it is **never** ``veil_ok`` — a self-test must not borrow a real safety
            alert's privilege to pierce the shield, and being suppressed under the
            veil is itself the proof the shield works;
          * it invents no data: the brief self-test carries no memory content and
            the hark self-test names itself as a test tone, not a detected sound.
        Returns {ok, kind, delivered} — delivered==0 means nothing is listening
        (or the veil is up), which is a true answer, not a failure."""
        k = str(kind or "hark").strip().lower()
        if k not in self.SELFTEST_KINDS:
            return {"ok": False, "error": "unknown self-test kind",
                    "kinds": list(self.SELFTEST_KINDS)}
        from ...hud import cards
        if k == "brief":
            card = cards.morning_brief(
                text="Self-test — your brief would appear here.",
                bullets=["this card is a self-test", "no memories were read"])
        else:
            card = cards.hark(clue="Self-test — the tap works.",
                              detail="a test tone, not a real alert",
                              importance="normal")
        # Rate-limited: without this an authed caller can flood the bounded event
        # queues (burying a real safety card) and pump the signed ledger, scrubbing
        # the panel's audit window — measured at 1804 pushes/s (audit 2026-07-23).
        now = time.monotonic()
        recent = [t for t in getattr(self, "_selftest_hits", []) if now - t < 60.0]
        if len(recent) >= self.MAX_SELFTEST_PER_MIN:
            self._selftest_hits = recent
            return {"ok": False, "error": "self-test is rate-limited",
                    "retry_after_s": int(60 - (now - recent[0])) + 1}
        recent.append(now)
        self._selftest_hits = recent
        card = dict(card)
        card["selftest"] = True
        card["eyebrow"] = "SELF-TEST"
        # The device renderers hard-code the eyebrow and drop unknown fields, so the
        # marker would vanish on the glasses' own card path — carry it in the fields
        # they DO render, and never borrow a real tap's earcon/haptic/flash.
        lines = [x for x in (card.get("lines") or []) if x]
        card["lines"] = ["SELF-TEST"] + [ln for ln in lines[1:]] if lines else ["SELF-TEST"]
        for borrowed in ("earcon", "haptic", "flash"):
            card.pop(borrowed, None)
        delivered = self.push_event(k, card)            # never veil_ok
        try:
            self.activity.add("selftest", f"Pushed a {k} self-test card")
        except Exception:                               # noqa: BLE001
            pass
        with self._event_lock:
            listeners = len(self._event_subs)
        reason = ""
        if delivered == 0:
            reason = "veiled" if self._veiled_quiet() else (
                "no listeners" if listeners == 0 else "queues full")
        return {"ok": True, "kind": k, "delivered": delivered,
                "listeners": listeners, "reason": reason}

    def _veiled_quiet(self) -> bool:
        """True when the shield is up — so a 0-delivery self-test can say WHY."""
        try:
            return bool(self.incognito_now())
        except Exception:                               # noqa: BLE001
            return True                                 # unreadable → assume shielded

    # Tier 3: a spoken intent is only "yours" for a few seconds. Long enough to
    # say "where are my keys" and raise the phone; short enough that it never
    # steers a look you take minutes later.
    INTENT_TTL_S = 20.0

    def note_spoken_intent(self, text: str) -> dict:
        """Parse a spoken phrase into a lens intent and hold it briefly.

        Fed by BOTH ears: the Brain's own on-device transcript (the Sharp Ears
        pack, via EarHost) and the phone's speech service (POST /live/intent), so
        whichever ear you have, the words steer the lens. Veil-gated: under the
        shield nothing is remembered, not even for a second."""
        from .spoken_intent import parse_spoken_intent
        try:
            if self.incognito_now():
                return {"ok": False, "reason": "veiled"}
        except Exception:                            # noqa: BLE001 — unreadable → closed
            return {"ok": False, "reason": "veiled"}
        parsed = parse_spoken_intent(text)
        if not parsed:
            self._spoken_intent = None
            return {"ok": True, "intent": ""}        # heard, matched nothing — honest
        self._spoken_intent = (parsed, time.monotonic())
        return {"ok": True, "intent": parsed["intent"], "terms": parsed["terms"]}

    def pending_intent(self) -> "dict | None":
        """The fresh spoken intent, or None. Consumed by the next look.

        Veil-gated on the way OUT as well as in. `note_spoken_intent` refuses to
        remember under the shield, but raising the shield after an utterance left
        the transcript readable here — only the accident of `world_lens.glance`
        checking the posture first kept it off the veiled path, and one new caller
        would have undone that. Reading it while veiled also DROPS it, so the
        shield actively clears speech rather than merely declining to serve it."""
        # POP, not peek. The caller used to read here and clear afterwards, and
        # ThreadingHTTPServer serves concurrent looks — with two looks in flight the
        # window between the two steps let one utterance steer both. Measured at
        # 18-34% under a shortened switch interval. Taking it out under the lock, in
        # one step, removes the window rather than narrowing it.
        with self._intent_lock:
            got = getattr(self, "_spoken_intent", None)
            self._spoken_intent = None
            if not got:
                return None
            try:
                veiled = bool(self.incognito_now())
            except Exception:                        # noqa: BLE001 — unreadable → closed
                veiled = True
            if veiled:
                return None
            parsed, ts = got
            if (time.monotonic() - ts) > self.INTENT_TTL_S:
                return None
            return parsed

    def clear_intent(self) -> None:
        with self._intent_lock:
            self._spoken_intent = None

    def list_mail_accounts(self) -> list:
        """The Mail accounts available to scope to (for the panel's picker)."""
        try:
            return self._mail_account_lister()
        except Exception:
            return []

    def apply_config(self, updates: dict) -> None:
        # Capture the prior model-endpoint URLs so a patch that points one at
        # link-local / cloud-metadata space is rejected by reverting to the prior
        # value — the SSRF endpoint never persists (audit 2026-07-19).
        _url_fields = ("ollama_url", "cloud_base_url", "api_base_url", "exo_url")
        _prev_urls = {k: getattr(self.config, k, "") for k in _url_fields}
        for k in ("model", "ollama_url", "ollama_chat_model",
                  "ollama_vision_model", "ollama_embed_model",
                  "exo_url", "exo_model",
                  "email_enabled", "mail_accounts", "summarize_emails",
                  "cloud_enabled",
                  "network_mode", "cloud_provider", "cloud_base_url",
                  "cloud_api_key", "cloud_model", "plan",
                  "api_provider", "api_base_url", "api_key", "api_model",
                  "semantic_search", "index_extensions", "max_file_kb",
                  "exclude_globs", "quiet_hours", "retention_days", "brief_hour",
                  "calendar_sync", "calendar_names", "calendar_days",
                  "calendar_ics",
                  "contacts_sync", "reminders_sync", "reminder_lists",
                  "sources_sync", "immich_base_url", "immich_api_key",
                  "home_assistant_url", "home_assistant_token",
                  "dawarich_url", "dawarich_api_key", "listen_enabled",
                  "remote_listen_enabled", "captions_enabled", "answer_ahead_enabled",
                  "interpret_enabled", "interpret_target", "truth_lens_enabled",
                  "intro_capture_enabled", "intro_auto_keep",
                  "proactive_cards", "proactive_alerts", "focus_mode",
                  "cue_event", "cue_person", "cue_place",
                  "fact_check_enabled", "wake_sources", "wake_feedback",
                  "dream_model_path",
                  "private_zones",
                  "face_recognition", "face_auto_enrol",
                  "voice_recognition", "voice_auto_enrol"):
            if k in updates:
                # a secret field echoed back as its "set" mask means "unchanged":
                # don't clobber the real key with the sentinel (public() masks
                # these, so the panel round-trips the placeholder).
                if k in ("immich_api_key", "home_assistant_token",
                         "dawarich_api_key") and updates[k] == "set":
                    continue
                # Type-check against the CURRENT value's type. JSON was written
                # straight onto the dataclass, so `{"quiet_hours": 5}` returned
                # 200, persisted the int, and then `in_quiet_hours` raised
                # TypeError on `"-" not in 5` -- permanently breaking
                # GET /dreamlayer/status (which the panel renders as "Brain
                # offline") until someone hand-edited brain_config.json. A field
                # the wearer cannot have meant is a 400, not a stored value.
                cur = getattr(self.config, k, None)
                val = updates[k]
                # `isinstance(True, int)` is True in Python, so a bool sailed
                # through the int branch and STUCK: once `retention_days` held
                # True, the bool branch (checked first) refused every attempt to
                # set it back to a number, so one request permanently wedged the
                # field — and for `retention_days` that silently switched the
                # signed privacy ledger from keep-forever to 24-hour deletion,
                # with no way to undo it short of hand-editing the JSON. Bools are
                # therefore tested and EXCLUDED explicitly, in both directions.
                if isinstance(cur, bool):
                    if not isinstance(val, bool):
                        log.warning("[brain] refused %s: expected a boolean", k)
                        continue
                elif isinstance(cur, int):
                    if isinstance(val, bool) or not isinstance(val, int):
                        log.warning("[brain] refused %s: expected a number", k)
                        continue
                elif isinstance(cur, str):
                    if not isinstance(val, str):
                        log.warning("[brain] refused %s: expected a string", k)
                        continue
                elif isinstance(cur, (list, tuple)):
                    # There was no collection check at all, so `index_extensions`
                    # accepted a dict and every consumer that iterates it broke.
                    if not isinstance(val, list):
                        log.warning("[brain] refused %s: expected a list", k)
                        continue
                setattr(self.config, k, val)
        from .backends import is_blocked_endpoint
        for uk in _url_fields:
            if uk in updates and is_blocked_endpoint(getattr(self.config, uk, "") or ""):
                setattr(self.config, uk, _prev_urls[uk])   # reject: keep the prior endpoint
                log.warning("[brain] refused a link-local/metadata %s endpoint", uk)
        self._wire_model()
        self.save()
        # A posture change (network_mode / quiet_hours) re-arms the model fetch
        # gate: flip to lan_only and HF_HUB_OFFLINE goes on before the next load.
        if {"network_mode", "quiet_hours"} & set(updates):
            self._apply_model_posture()
        # The interpreter lives on the EarHosts, not just in config. Without this
        # the panel's switch persisted and did nothing until the next ear restart —
        # write-only settings are how a feature looks broken while reading "on".
        if {"interpret_enabled", "interpret_target"} & set(updates):
            self._apply_interpret()
            self._sync_ear_wired()
        # Same trap, same fix: the room read lives on the EarHosts too, so a
        # config POST that only wrote the flag would persist a switch that did
        # nothing until the next ear restart.
        if "truth_lens_enabled" in updates:
            self._apply_truth_lens()
        # turning a sync on (or changing its filter) → pull immediately
        try:
            if updates.get("calendar_sync") or ("calendar_names" in updates and self.config.calendar_sync):
                self.sync_calendar()
            if updates.get("contacts_sync"):
                self.sync_contacts()
            if updates.get("reminders_sync") or ("reminder_lists" in updates and self.config.reminders_sync):
                self.sync_reminders()
            if updates.get("sources_sync"):
                self.sync_sources()
            if "listen_enabled" in updates:
                # the wearer flipped the always-on ear — honor it immediately
                if self.config.listen_enabled:
                    self.start_ear()
                else:
                    self.stop_ear()
            if "remote_listen_enabled" in updates and not self.config.remote_listen_enabled:
                # opting the phone-mic out stops the phone-fed ear at once (it
                # can't self-start again without the phone streaming AND consent)
                self.stop_remote_ear()
        except Exception:
            # a failed opportunistic sync must not fail the config write that
            # triggered it (the sync loop retries on schedule); log so a broken
            # macOS source doesn't fail silently (was a silent pass).
            log.warning("post-config macOS sync failed", exc_info=True)
        if updates.get("cloud_enabled"):
            self.saga_record("cloud")
        if updates.get("network_mode") == "lan_only":
            self.saga_record("incognito")

    def incognito_now(self) -> bool:
        """Effective privacy shield: LAN-only, a quiet-hours window, OR a
        private zone.

        Private zones are a THIRD TERM HERE rather than a suppression path of
        their own, and that is the whole design. `private_zone_card` says
        "CAPTURE SUSPENDED · Memory resumes when you leave", and the only way to
        make that sentence true is for the wearer's existing shield to be up:
        every gate in the product already consults this one method — the ear,
        captions, answer-ahead, the lens ring, face recall, ambient pushes —
        so a zone suppresses all of them at once and none of them had to be
        taught about zones. A parallel mechanism would be a second thing to keep
        in step, and the first one it fell out of step with would be a card
        promising a silence the Brain was not keeping.
        """
        from .store import in_quiet_hours
        if self.config.lan_only or in_quiet_hours(self.config.quiet_hours):
            return True
        return bool(self.private_zone_now())

    def private_zone_now(self) -> str:
        """Name of the private zone the wearer is currently inside, else "".

        Fails OPEN, unlike most gates here, and the asymmetry is deliberate: a
        zone that cannot be evaluated (no fix, a stale fix, malformed config)
        must not silently veil the Brain forever. The wearer has other, explicit
        shields; an unreadable geofence that quietly disabled capture would look
        exactly like the product being broken, with no way to tell.
        """
        zones = getattr(self.config, "private_zones", None) or []
        if not zones:
            return ""
        try:
            fix = self.here()
            if not fix:
                return ""
            from .geo import zone_containing
            return zone_containing(zones, fix["lat"], fix["lon"])
        except Exception as exc:                    # noqa: BLE001
            log.warning("[brain] zone check failed: %s", type(exc).__name__)
            return ""

    def here(self) -> Optional[dict]:
        """The wearer's current position, or None.

        Two sources, freshest wins. The phone's own report (POST
        /dreamlayer/location) is the live one; Dawarich is the fallback for a
        wearer who already self-hosts a location history and would rather not
        have the phone push as well. Neither is stored by this method.
        """
        fix = self._last_fix.get()
        if fix:
            return fix
        base = getattr(self.config, "dawarich_url", "")
        if not base:
            return None
        try:
            from ...memory.source_dawarich import default_dawarich
            from .geo import FIX_MAX_AGE_S, valid_coord
            src = default_dawarich(base, getattr(self.config, "dawarich_api_key", ""))
            if src is None:
                return None
            last = src.last()
            if not last or not valid_coord(last.get("lat"), last.get("lon")):
                return None
            age = time.time() - float(last.get("ts") or 0.0)
            if age > FIX_MAX_AGE_S:
                return None                        # a track point is not a fix
            return {"lat": float(last["lat"]), "lon": float(last["lon"]),
                    "accuracy_m": 0.0, "ts": float(last["ts"]),
                    "age_s": round(age, 1)}
        except Exception as exc:                    # noqa: BLE001
            log.debug("[brain] dawarich fix unavailable: %s", type(exc).__name__)
            return None

    def _apply_model_posture(self) -> None:
        """Set the process-wide HF offline flags to match the wearer's posture,
        so ML loaders can't reach a CDN while offline/incognito. Fail-safe:
        model_guard is optional and this never raises into the caller."""
        try:
            from ... import model_guard
            model_guard.apply_offline_posture(self)
        except Exception as exc:                    # pragma: no cover - defensive
            log.debug("[brain] model posture gate skipped: %s", exc)

    def missing_folders(self) -> list:
        return [f for f in self.config.folders
                if not Path(f).expanduser().is_dir()]

    def ask(self, query: str, no_cloud: bool = False) -> Optional[Answer]:
        # no_cloud carries the WEARER's session posture from the hub (incognito,
        # or hub-cloud switched off). It is authoritative over the Brain's own
        # cloud config: a paired hub that says no_cloud must never egress to the
        # cloud here, even if this Mac is configured cloud_ready(). Direct panel
        # callers pass no_cloud=False and keep the Brain's own config.
        # Primary tier: when the wearer has plugged in their own agent
        # (model == "api"), it answers first. A LOCAL agent answers freely; a
        # REMOTE one is silenced by no_cloud/incognito and falls through to the
        # on-device keyword index below (never a dead end).
        ans = None
        if self.config.model == "api":
            ans = self._ask_primary_api(query, no_cloud)
        if ans is None:
            # temporal knowledge-graph tier (LightRAG): "what's connected, and
            # when" — consulted before the keyword index, fully on-device (built
            # by the Brain's own local model + embedder). None when absent.
            g = self.graph_answer(query)
            if g:
                ans = Answer(text=str(g).strip(), sources=["memory-graph"],
                             tier="laptop", confidence=0.6)
        if ans is None:
            ans = self.index.ask(query)
        if ans is None and not no_cloud \
                and self.config.cloud_ready() and not self.incognito_now():
            ans = self._ask_cloud(query)
        if ans is not None:
            # The panel says incognito "logs nothing". history.jsonl holds the
            # question AND the verbatim answer, and GET /history serves both, so
            # writing here under the shield made that claim false. Fail closed:
            # a posture check that raises is treated as veiled.
            try:
                veiled = self.incognito_now()
            except Exception:                        # noqa: BLE001
                veiled = True
            if not veiled:
                self.history.add(query, ans.text, ans.tier, ans.sources)
                self.saga_record("recall")
        return ans

    def _ask_primary_api(self, query: str, no_cloud: bool = False) -> Optional[Answer]:
        """Route the first-pass answer to the wearer's own external API/agent
        (OpenClaw, Hermes, LM Studio, vLLM, a local Ollama, any OpenAI-compatible
        / Anthropic / Gemini endpoint), with LOCAL-vs-REMOTE awareness the cloud
        tier lacks:

          * LOCAL endpoint (localhost / LAN): answers freely, is NOT egress, and
            stays reachable while incognito — same status as the on-device tier.
          * REMOTE endpoint: a real boundary, so it is gated by the wearer's veil
            (no_cloud / incognito) and, when it does fire, counted + logged
            BEFORE the request exactly like _ask_cloud (a failed or empty call
            still left the device and must be on the ledger).

        Returns None (→ caller falls back to the keyword index) when nothing is
        wired, when a remote endpoint is veiled, or when the endpoint errors /
        returns empty."""
        from .backends import api_chat, is_local_endpoint
        base = (self.config.api_base_url or "").strip()
        if not base:
            return None
        local = is_local_endpoint(base)
        if not local:
            # remote agent = egress: honor the wearer's posture first…
            if no_cloud or self.incognito_now():
                return None
            # …then account for it before the request (mirrors _ask_cloud's
            # count-log-save-before-call ordering — reaching here means the
            # query is leaving the device).
            self.bump_cloud_calls()
            self.activity.add("cloud-egress", f"Asked your API brain: {query[:70]}")
            self.save()
        try:
            text = api_chat(self.config, query)
            self.health.record_ok("api-brain")
        except Exception as exc:
            self.health.record_failure("api-brain", exc)
            text = ""
        if not text:
            return None
        # a local agent is a "laptop"-class on-device answer; a remote one is
        # cloud-class (it left the device), so it stamps the cloud tier.
        return Answer(text=text, tier=("laptop" if local else "cloud"),
                      sources=["api"], confidence=0.6)

    def _ask_cloud(self, query: str) -> Optional[Answer]:
        """The one place data leaves the device — logged every single time.

        The count + egress-log happen BEFORE the request and BEFORE any
        empty/error guard (re-audit 2026-07): reaching here means the query is
        about to be sent to the provider, so a call that later errors or returns
        empty STILL left the device and must be on the ledger. Counting only
        successful answers silently under-reported egress — a real gap for a
        product whose panel promises "every one is logged"."""
        # Route through the litellm unifier when the `llm` extra is installed —
        # one interface over OpenAI/Anthropic/Gemini/Ollama + ~100 providers with
        # fallback — else litellm_chat transparently delegates to the built-in
        # cloud_chat, so this is behaviour-identical with zero new deps. (Before,
        # the Brain always called cloud_chat directly and the llm_router cap was
        # dead-on-install — the adapter imported but was never on the live path.)
        from ..litellm_backend import litellm_chat
        self.bump_cloud_calls()                         # the query is leaving now
        self.activity.add("cloud-egress", f"Asked the cloud: {query[:70]}")
        self.save()
        try:
            text = litellm_chat(self.config, query)
            self.health.record_ok("cloud")
        except Exception as exc:
            self.health.record_failure("cloud", exc)   # degrade, but on the record
            text = ""
        if not text:
            return None
        return Answer(text=text, tier="cloud", sources=["cloud"], confidence=0.6)

    def explain(self, label: str, image_b64, want: str) -> Optional[Answer]:
        """The phone Look screen's second tap ("tell me more"). VEIL-GATED.

        This was a bare `vision_answer(...)` while both siblings refuse
        correctly -- `/live/look` returns `local_only` and `/brain/look` returns
        `{"veiled": true}`. So the one route with no gate shipped the wearer's
        byte-identical posted JPEG to whatever `ollama_url` points at while the
        device was meant to be deliberately blind, and reported `tier:"laptop"`
        with the egress counter still reading zero. Fail closed: a posture check
        that raises means veiled."""
        try:
            veiled = self.incognito_now()
        except Exception:                            # noqa: BLE001
            veiled = True
        if veiled:
            return None
        return vision_answer(self._backend, label, image_b64, want)

    def world_lens(self):
        """The on-glass World lenses (Object Lens / Juno + TasteLens) run inside
        this Brain — the pre-hardware stand-in a phone photo looks through
        (ai_brain/server/world_lens.py). Built once and cached (loading installed
        plugins isn't free); invalidated when a plugin or the model changes so a
        fresh look picks up the new set. Returns None if it can't be built."""
        wl = getattr(self, "_world_lens", None)
        if wl is None:
            try:
                from .world_lens import build_world_lens
                wl = build_world_lens(self)
            except Exception:
                log.warning("world lens unavailable", exc_info=True)
                wl = None
            self._world_lens = wl
        return wl

    def _invalidate_world_lens(self) -> None:
        """Drop the cached World lens so the next look rebuilds it — call after a
        plugin install/remove or a model rewire changes what a look can do."""
        self._world_lens = None

    def lenses(self):
        """The lens set that had no way into the Brain until now
        (ai_brain/server/lens_hosts.py): Provenance, Candor, Commitment Drift,
        Saga, Stasis, Premonition, Inner Weather. Built once and cached; every
        lens inside is lazy, so this costs nothing until one is used."""
        ls = getattr(self, "_lenses", None)
        if ls is None:
            try:
                from .lens_hosts import build_lenses
                ls = build_lenses(self)
            except Exception:
                log.warning("lens hosts unavailable", exc_info=True)
                ls = None
            self._lenses = ls
        return ls

    def face_recall(self):
        """Recognising the people you INTRODUCED — never a stranger
        (ai_brain/server/face_live.py). Built once and cached; the index of
        consented faces is read from disk on first use, not here, so a Brain
        that never looks at anyone never loads it. Returns None if it can't be
        built, which every caller must read as "no answer", not "not a
        contact"."""
        fr = getattr(self, "_face_recall", None)
        if fr is None:
            try:
                from .face_live import build_face_recall
                fr = build_face_recall(self)
            except Exception:
                log.warning("face recall unavailable", exc_info=True)
                fr = None
            self._face_recall = fr
        return fr

    def intro(self):
        """Name Capture (ai_brain/server/intro_live.py) — the constructor
        `scripts/lens_reachability.py` reported missing. Built once and cached,
        because the PENDING OFFER lives on it: a fresh instance per utterance
        would drop every offer the moment it was made. Returns None when it
        cannot be built, which callers read as "no capture", never as "no name
        was said"."""
        ih = getattr(self, "_intro", None)
        if ih is None:
            try:
                from .intro_live import IntroHost
                ih = IntroHost(self)
            except Exception:
                log.warning("name capture unavailable", exc_info=True)
                ih = None
            self._intro = ih
        return ih

    def voice_recall(self):
        """Recognising WHO IS SPEAKING, so a memory has an author
        (ai_brain/server/voice_live.py). Built once and cached, like the face
        index; the stored voiceprints are read from disk on first use, so a Brain
        that never listens never loads them. Returns None when it cannot be
        built, which every caller must read as "no answer", never as "a
        stranger"."""
        vr = getattr(self, "_voice_recall", None)
        if vr is None:
            try:
                from .voice_live import VoiceRecall
                vr = VoiceRecall(self)
            except Exception:
                log.warning("voice recall unavailable", exc_info=True)
                vr = None
            self._voice_recall = vr
        return vr

    def summarize(self, text: str, max_chars: int = 220) -> str:
        """One-glance summary of a long email. Uses the local model when there
        is one; otherwise clips to the first sentence — never blocks the feed."""
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        if self._backend is not None:
            try:
                s = self._backend.chat(
                    "Summarize this email in one short sentence a person can "
                    "read at a glance. Just the sentence:\n\n" + text[:2000])
                if s and s.strip():
                    return s.strip()
            except Exception:
                # best-effort model summary; on any backend failure we fall
                # through to the clip below so the feed never blocks. Debug —
                # an unreachable model here is an expected degrade, not alarming.
                log.debug("summarize backend call failed; clipping instead",
                          exc_info=True)
        head = text.split(". ")[0].strip()
        return head if 0 < len(head) <= max_chars else text[:max_chars].rstrip() + "…"

    def maybe_run_brief(self, now: float | None = None) -> bool:
        """If it's the configured brief hour and today's brief hasn't run yet,
        generate it and stash it for delivery. Returns True when it ran."""
        hour = self.config.brief_hour
        if hour is None or hour < 0:
            return False
        lt = time.localtime(now if now is not None else time.time())
        day = (lt.tm_year, lt.tm_yday)
        if lt.tm_hour != hour or getattr(self, "_brief_ran_day", None) == day:
            return False
        self._brief_ran_day = day
        b = self.brief()
        self.last_brief = {"text": b["text"], "bullets": b["bullets"],
                           "ts": time.time()}
        self.activity.add("brief", "Morning brief ready")
        # push it to any connected Live Lens as a real card (veil-gated: a brief
        # is memory-derived, so it's suppressed while incognito / quiet-hours)
        try:
            from ...hud import cards
            self.push_event("brief", cards.morning_brief(
                text=b.get("text", ""), bullets=b.get("bullets") or []))
        except Exception:                            # noqa: BLE001 — never fail a brief
            pass
        return True

    def start_brief_scheduler(self, interval: float = 60.0) -> None:
        if getattr(self, "_brief_stop", None) is not None:
            return
        self._brief_stop = threading.Event()

        def loop():
            while not self._brief_stop.wait(interval):
                try:
                    self.maybe_run_brief()
                except Exception:
                    # keep the scheduler thread alive across a bad brief run;
                    # log so a recurring failure surfaces (was a silent pass).
                    log.warning("brief scheduler run failed", exc_info=True)
        threading.Thread(target=loop, daemon=True).start()

    def export_backup(self) -> dict:
        """A full, restorable snapshot of the Brain — config (incl. secrets),
        query history, activity, and agenda. Handed out only to the local
        panel, so it never crosses the network."""
        self.saga_record("backup")
        return {
            "version": _version(),
            "config": asdict(self.config),
            "history": self.history.recent(2000),
            "activity": self.activity.recent(2000),
            "agenda": self.calendar(200),
        }

    def import_backup(self, data: dict) -> None:
        from .store import field_list
        cfg = data.get("config") or {}
        known = {f.name for f in field_list(BrainConfig)}
        # A restored backup is request data. `apply_config` vets endpoint fields
        # against is_blocked_endpoint; this path did not, so a crafted /restore
        # persisted `ollama_url: http://169.254.169.254` and the next ask read
        # cloud instance-metadata credentials back as the answer.
        from .backends import is_blocked_endpoint
        for k, v in cfg.items():
            if k not in known:
                continue
            if k.endswith("_url") and isinstance(v, str) and is_blocked_endpoint(v):
                log.warning("[brain] restore: refused %s (link-local/metadata)", k)
                continue
            setattr(self.config, k, v)
        # A restored backup writes config.folders straight from request data,
        # bypassing add_folder's allow-list — filter it through the same
        # primitive so a crafted/legacy backup can't smuggle /etc (or another
        # user's home) into the watched set (refute-remediation 2026-07).
        self.config.sanitize_folders()
        self.save()
        if isinstance(data.get("history"), list):
            self.history.restore(data["history"])
        if isinstance(data.get("activity"), list):
            self.activity.restore(data["activity"])
        if isinstance(data.get("agenda"), list):
            self._save_json("agenda.json", data["agenda"])
        self._wire_model()
        self.reindex()

    # -- cfg_dir JSON stores: locked read-modify-write + atomic write ---------
    def _load_json(self, name: str, default):
        """Read a cfg_dir JSON store under the store lock."""
        with self._store_lock:
            p = self.cfg_dir / name
            try:
                val = json.loads(p.read_text()) if p.exists() else default
            except (OSError, ValueError, UnicodeDecodeError):
                # a missing/corrupt/half-written store degrades to the default
                # rather than crashing a request — but on the record, since a
                # silent default here once masked a truncated file (audit
                # 2026-07-14). Narrowed so a programming error still surfaces.
                log.warning("store %s unreadable; using default", name,
                            exc_info=True)
                val = default
            return val if isinstance(val, type(default)) else default

    def _save_json(self, name: str, obj) -> None:
        """Atomically write a cfg_dir JSON store (temp + os.replace) under the
        store lock, so a concurrent read can never see a half-written file and
        two writers can never interleave. The replace retries briefly on
        Windows, where a concurrent reader holding the store open makes
        os.replace raise PermissionError (see store.replace_atomic)."""
        with self._store_lock:
            p = self.cfg_dir / name
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(obj))
            replace_atomic(tmp, p)

    def saga_record(self, event: str, count: int | None = None) -> list:
        """Advance the Saga profile for an ecosystem event and unlock any badges
        (feature use + the level milestones it crosses). Returns newly-unlocked
        names; logs them to the activity feed."""
        fresh = (self.saga.record(event, count=count) if count is not None
                 else self.saga.record(event))
        fresh += self.saga.note_level(self.saga.snapshot()["level"])
        return fresh

    def _load_profile(self) -> dict:
        p = self.cfg_dir / "profile.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (OSError, ValueError, UnicodeDecodeError):
                # corrupt/half-written profile mirror → empty (the hub re-pushes
                # it). Narrowed + logged so a real read bug can't hide here.
                log.warning("profile.json unreadable; starting empty",
                            exc_info=True)
                return {}
        return {}

    def _retriever_for_purge(self):
        """(Retriever, MemoryDB) over the live store, or (None, None).

        Built exactly as `purge_memories` builds it, so a single "forget that"
        reaches the same stores an erase-everything does. Sharing the shape is
        the point: the ANN index is the one that bites — a row deleted while its
        embedding survives is a memory the wearer was told is gone and that
        vector search still finds.
        """
        import os as _os
        db_path = str(_memory_db_path(self))
        if not _os.path.exists(db_path):
            return None, None
        from ...memory.ann_index import PersistentAnnIndex
        from ...memory.db import MemoryDB
        from ...memory.retrieval import Retriever
        db = MemoryDB(db_path)
        dim = db.get_setting("embedder_dim")
        ann = (PersistentAnnIndex(db_path + ".usearch", int(dim))
               if PersistentAnnIndex.available and dim else None)
        return Retriever(db, None, ann), db

    def forget_last_preview(self, push: bool = True) -> dict:
        """What "forget that" would erase — and the card that asks.

        The FIRST half of a two-step. `forget_last_card` is a declared HUD
        feature whose own copy is "Hold to confirm • Tap to cancel", so wiring
        it as a one-way push would have drawn a question with no way to answer
        it — the shape of half-wiring this project keeps finding. The second
        half is `forget_memory`, and it requires the id this returns.

        Veil-gated as RECALL, not as capture: naming the last thing you said
        back to you is a read of the timeline, and under the shield the Brain
        does not answer reads.
        """
        if self.incognito_now():
            return {"ok": False, "reason": "veiled"}
        try:
            _r, db = self._retriever_for_purge()
            if db is None:
                return {"ok": False, "reason": "no-store"}
            rows = db.memories()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[brain] forget preview failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "error"}
        if not rows:
            return {"ok": False, "reason": "nothing-to-forget"}
        # newest by id: `created_at` is a string and rows arrive in insert order,
        # but an explicit max on the primary key does not depend on either.
        row = max(rows, key=lambda r: int(r.get("id") or 0))
        label = (row.get("summary") or "").strip()
        pushed = 0
        if push and label:
            try:
                from ...hud import cards
                # The card QUOTES the memory, so it is the wearer's own content
                # going to their own glass — the same class of push as
                # SavedMemoryCard, and veil-gated the same way.
                pushed = self.push_event("forget_last",
                                         cards.forget_last_card(label[:60]),
                                         veil_ok=False)
            except Exception:                        # noqa: BLE001
                pushed = 0
        return {"ok": True, "id": int(row.get("id") or 0), "label": label,
                "kind": row.get("kind") or "", "pushed": pushed}

    def forget_memory(self, memory_id) -> dict:
        """Erase one memory everywhere — the SECOND half of "forget that".

        The caller must name the id `forget_last_preview` returned. That is the
        confirmation, and it is also a race guard: between the wearer asking and
        confirming, the ear can land a new utterance, and a confirm that meant
        "the newest one" would then delete something they never saw.

        Goes through `Retriever.purge_memory`, never `MemoryDB.purge_memory`
        alone — the row, the ANN vector, any alternate vector store and the REM
        consolidation bias have to move together, or "forget that" leaves a
        memory that is gone from the list and still findable by search.
        """
        try:
            mid = int(memory_id)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "bad-id"}
        try:
            retr, db = self._retriever_for_purge()
            if db is None:
                return {"ok": False, "reason": "no-store"}
            if not any(int(r.get("id") or 0) == mid for r in db.memories()):
                # Already gone, or never here. Idempotent rather than an error:
                # a double-confirm from a flaky connection must not read as a
                # failure to erase.
                return {"ok": True, "forgotten": 0, "reason": "not-found"}
            retr.purge_memory(mid)
        except Exception as exc:                     # noqa: BLE001
            log.error("[brain] forget failed: %s", exc)
            return {"ok": False, "reason": "error"}
        try:
            self.activity.add("privacy", "Forgot one memory")
        except Exception:                            # noqa: BLE001
            pass
        pushed = 0
        try:
            from ...hud import cards
            pushed = self.push_event("saved_memory",
                                     cards.saved_memory("Forgotten."),
                                     veil_ok=False)
        except Exception:                            # noqa: BLE001
            pushed = 0
        return {"ok": True, "forgotten": 1, "pushed": pushed}

    def purge_memories(self) -> dict:
        """The phone's "Erase all memories" honored where the memories actually
        live: the MEMORY DATABASE is purged through the same cascade a "forget
        that" uses (rows, vectors, the ANN index and the ember sidecar), and
        every Waypath anchor is dropped and the store rewritten, so a later
        refresh can't quietly resurrect what the user erased. People and
        reminders are mirrors of their own surfaces (People tab, Reminders) and
        are not deleted here — erasing memories is not deleting your contacts.

        The memory DB was the gap, and it was the whole point of the button. The
        phone's copy reads "Erase all memories. This cannot be undone."; this
        method cleared only the anchors and the ember sidecar, so every
        conversation, promise, place signature and commitment stayed in
        ~/.dreamlayer/dreamlayer.db and was still readable with sqlite3 — and
        still served by this Brain's own /dreamlayer/memory/file route. The
        method that DID reach all of it, `Orchestrator.erase_all_memories()`, had
        no production caller at all.

        The Ember practice goes too: engrams hold verbatim ANSWERS (and cues
        and staged offers carry memory content), so erase-everything empties
        the <db>.ember sidecar — purged and VACUUMed so the bytes leave the
        disk, not deleted as a file (the hub may hold it open). Surviving the
        retention lifecycle is Ember's design; surviving the owner's explicit
        wipe would be a privacy residue (docs/EMBER.md)."""
        import os as _os
        n = self.waypath.forget_all()
        self._save_waypath()
        # The trail is held only in memory, but it is a list of the wearer's
        # things and where they were — erase-everything has to reach it too, or
        # the next departure re-anchors what was just wiped.
        try:
            self.object_trail.forget_all()
        except Exception:                            # noqa: BLE001
            pass
        # The memory DB, through the real cascade. Wired exactly the way
        # `_ember_burn` wires it, so vectors and the ANN index go too — a row
        # deleted while its embedding survives is a memory you can still find.
        n_rows = 0
        db_path = str(_memory_db_path(self))
        if _os.path.exists(db_path):
            try:
                from ...memory.ann_index import PersistentAnnIndex
                from ...memory.db import MemoryDB
                from ...memory.retrieval import Retriever
                db = MemoryDB(db_path)
                n_rows = len(db.memories())
                dim = db.get_setting("embedder_dim")
                ann = (PersistentAnnIndex(db_path + ".usearch", int(dim))
                       if PersistentAnnIndex.available and dim else None)
                Retriever(db, None, ann).purge_all()
            except Exception as exc:                 # noqa: BLE001
                log.error("[brain] memory purge failed: %s", exc)
                return {"ok": False, "error": f"memory purge failed: {exc}",
                        "purged": n, "embers_purged": 0}
        n_ember = 0
        ember_path = _ember_store_path(self)
        if _os.path.exists(ember_path):
            from ...ember import EmberStore
            store = EmberStore(ember_path)
            n_ember = len(store.engrams(include_burned=True))
            store.purge_all()
        # The World-lens hot ring holds sighting memory ("seen before N×") —
        # an explicit erase must drop it too, or pre-erase sightings surface
        # on the very next look (refute 2026-07-21: purge left the cached
        # host, and its ring, alive).
        self._invalidate_world_lens()
        # Enrolled FACE templates are the most personal thing the device holds —
        # a biometric identifier, not a memory of one — so erase-everything must
        # reach them. They live in their own file (face_index.json), outside the
        # memory DB and the ember sidecar, which is exactly how a store gets
        # forgotten by a wipe that "erases everything".
        n_faces = 0
        fr = self.face_recall()
        if fr is not None:
            try:
                n_faces = fr.forget_all()
            except Exception as exc:                 # noqa: BLE001
                log.error("[brain] face index purge failed: %s", exc)
                return {"ok": False, "error": f"face purge failed: {exc}",
                        "purged": n, "memories_purged": n_rows,
                        "embers_purged": n_ember}
        self._face_recall = None
        # The statement ring and any held thought are memory too — a wipe that
        # leaves them is exactly the residue this method exists to prevent.
        n_lens = 0
        ls = self.lenses()
        if ls is not None:
            try:
                n_lens = ls.forget_all()
            except Exception as exc:                 # noqa: BLE001
                log.warning("[brain] lens purge failed: %s", exc)
        self._lenses = None
        self.activity.add("privacy",
                          f"Erased kept memories ({n_rows} memory row(s), "
                          f"{n} anchor(s), {n_ember} ember(s), "
                          f"{n_faces} enrolled face(s), "
                          f"{n_lens} statement(s))")
        return {"ok": True, "purged": n, "memories_purged": n_rows,
                "embers_purged": n_ember, "faces_purged": n_faces,
                "statements_purged": n_lens}

    def missed(self, since: float = 0.0) -> dict:
        """"What did I miss?" — the incoming texts and emails since you last
        looked, spoken as a short line. Uses the same message source as the
        brief; `since` defaults to the last few hours."""
        import time as _t
        if since <= 0:
            since = _t.time() - 6 * 3600
        try:
            msgs = self._messages_fn(self.config, 40) if self.config.email_enabled else []
        except Exception:
            # the macOS message source is best-effort; a failure means "nothing
            # to report", not an error to the caller. Log so a broken source is
            # visible (was silent).
            log.warning("message source failed in missed()", exc_info=True)
            msgs = []
        incoming = [m for m in msgs if not m.get("from_me") and m.get("ts", 0) > since]
        texts = [m for m in incoming if m.get("channel") != "email"]
        emails = [m for m in incoming if m.get("channel") == "email"]
        if not incoming:
            return {"intent": "missed", "ok": True, "texts": 0, "emails": 0,
                    "say": "Nothing while you were away."}
        who = ", ".join(dict.fromkeys(
            (m.get("who") or "").strip() for m in texts if m.get("who")))
        bits = []
        if texts:
            bits.append(f"{len(texts)} text{'s' if len(texts) != 1 else ''}"
                        + (f" from {who[:60]}" if who else ""))
        if emails:
            bits.append(f"{len(emails)} email{'s' if len(emails) != 1 else ''}")
        return {"intent": "missed", "ok": True, "texts": len(texts),
                "emails": len(emails), "say": "You missed " + " and ".join(bits) + "."}

    def voice_reply(self, to: str, text: str) -> dict:
        """A spoken/typed "reply to Priya saying on my way" — stage the reply
        (drafting one with the model if you didn't dictate the words) and hand it
        back for the app to send. Never auto-sends: sending stays a deliberate
        tap in Messages."""
        to = (to or "").strip()
        text = (text or "").strip()
        if not to:
            return {"intent": "reply", "ok": False, "say": "Reply to whom?"}
        if not text:
            sug = self.suggest_replies(f"(reply to {to})", n=1)
            text = sug[0] if sug else ""
        return {"intent": "reply", "ok": True, "to": to, "text": text,
                "say": (f"Reply to {to}: “{text}” — open Messages to send."
                        if text else f"Open Messages to reply to {to}.")}

    def memories(self, limit: int = 40) -> dict:
        """A read of DreamLayer's own kept memory for the phone's Memories tab,
        assembled from what the Brain holds: places you saved (Waypath), people
        you've met and favors owed (Social Lens), and dated reminders. Not raw
        recordings — the moments that matter. Timestamped rows sort newest
        first (an upcoming reminder floats to the very top); people and open
        debts are living memory with no event time, so they carry ts=0 and
        settle at the bottom instead of masquerading as fresh."""
        import time as _t
        from datetime import date
        now = _t.time()
        today = date.fromtimestamp(now)

        def when(ts: float) -> str:
            if not ts:
                return ""
            # calendar days, not 24h buckets — so tomorrow's reminder reads
            # "Tomorrow", not "Yesterday", and a same-day dawn stash stays today
            days = (date.fromtimestamp(ts) - today).days
            # clock12/tm_mday, not the glibc-only no-pad strftime flags,
            # which raise ValueError on Windows
            from ...reality_compiler.v2.native import clock12
            lt = _t.localtime(ts)
            clock = clock12(ts)
            if days == 0:
                return clock
            if days == -1:
                return "Yesterday, " + clock
            if days == 1:
                return "Tomorrow, " + clock
            if -7 < days < 7:
                return _t.strftime("%a, ", lt) + clock
            return f"{_t.strftime('%b', lt)} {lt.tm_mday}, " + clock

        rows = []
        # places you saved (Waypath) — real timestamps
        for a in self.waypath.anchors():
            loc = f"at {a.place}" if a.place else "somewhere you saved"
            rows.append(("Place", f"Your {a.subject} — {loc}", a.ts or now, when(a.ts)))
        # people you've met + favors owed (Social Lens) — living memory, undated
        for p in self.social_people:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            detail = ", ".join([x for x in [p.get("relation", "")]
                                + (p.get("notes") or [])[:1] if x])
            rows.append(("Person", name + (f" — {detail}" if detail else ""),
                         0.0, p.get("last_seen", "") or ""))
            for d in (p.get("debts") or []):
                dl = d.strip()
                low = dl.lower()
                if low.startswith("you owe"):
                    s = f"You owe {name} {dl[7:].strip()}"
                elif low.startswith("owes you"):
                    s = f"{name} {dl}"
                else:
                    s = f"{name}: {dl}"
                rows.append(("Promise", s, 0.0, "open"))
        # dated reminders (Promise)
        for r in self.reminders():
            ts = float(r.get("ts", 0) or 0)
            if ts:
                rows.append(("Promise", r["title"], ts, when(ts)))

        rows.sort(key=lambda x: (-x[2], x[1].lower()))
        out = [{"id": f"m{i}", "kind": kind, "summary": summary,
                "createdAt": label, "ts": int(ts * 1000)}
               for i, (kind, summary, ts, label) in enumerate(rows[:limit])]
        return {"memories": out}

    def set_profile(self, data: dict) -> dict:
        """Store the Juno profile the glasses hub just pushed (a mirror, so the
        phone can read it). Keeps only the known shape; persists to profile.json."""
        d = data if isinstance(data, dict) else {}

        def _list(key, limit):
            v = d.get(key)
            return [str(x) for x in v][:limit] if isinstance(v, list) else []

        self.profile = {
            "name": str(d.get("name", "") or ""),
            "interests": _list("interests", 12),
            "people": _list("people", 12),
            "preferences": _list("preferences", 40),
            "observations": int(d.get("observations", 0) or 0),
        }
        try:
            self._save_json("profile.json", self.profile)
        except OSError:
            # persistence is best-effort here (the in-memory mirror is already
            # updated and the hub re-pushes on reconnect); a disk error must not
            # fail the request, but it must not vanish either. Narrowed so a
            # serialization bug (TypeError) surfaces instead of being swallowed.
            log.warning("failed to persist profile.json", exc_info=True)
        return self.profile

    def pull_model(self, name: str) -> dict:
        """One-click Ollama model pull. Re-probes after so status updates."""
        from .backends import pull_model as _pull
        res = _pull(self.config, name)
        if res.get("ok"):
            self.activity.add("model", f"Pulled model {res.get('model', name)}")
            self._wire_model()
            self.saga_record("model")
        return res

    # -- rewind my day: one merged timeline of what happened -------------

    def rewind(self, now: float | None = None) -> dict:
        """Today, grouped into hour blocks: what the Brain did (activity), the
        messages it relayed, and the events on the agenda — one scrubable
        timeline for the phone. Reads only what the Brain already has."""
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
        items = []
        for a in self.activity.recent(200):
            ts = float(a.get("ts", 0) or 0)
            if ts >= day_start:
                items.append({"ts": ts, "kind": a.get("kind", "activity"),
                              "text": a.get("text", "")})
        try:
            msgs = self._messages_fn(self.config, 50) if self.config.email_enabled else []
            for m in msgs:
                ts = float(m.get("ts", 0) or 0)
                if ts >= day_start and not m.get("from_me"):
                    who = m.get("who", "")
                    body = m.get("subject") or m.get("text", "")
                    items.append({"ts": ts, "kind": "message",
                                  "text": f"{who}: {body}".strip(": ")})
        except Exception:
            # message source is best-effort in the rewind timeline; a failure
            # just omits messages from the view. Logged (was silent).
            log.warning("message source failed in rewind()", exc_info=True)
        for e in self.calendar(50):
            if day_start <= e["ts"] < day_start + 86400:
                items.append({"ts": e["ts"], "kind": "event", "text": e["title"]})
        blocks: dict[int, list] = {}
        for it in items:
            hr = int((it["ts"] - day_start) // 3600)
            blocks.setdefault(hr, []).append(it)
        out = []
        for hr in sorted(blocks):
            evs = sorted(blocks[hr], key=lambda x: x["ts"])
            out.append({"hour": hr, "label": _hour_label(day_start + hr * 3600),
                        "count": len(evs), "items": evs})
        return {"blocks": out, "count": len(items)}

    def suggest_replies(self, text: str, n: int = 3) -> list:
        """A few short, natural replies to an incoming message — pick one by
        tap now, by voice later. Model-generated with a canned fallback."""
        text = (text or "").strip()
        if self._backend is not None and text:
            try:
                raw = self._backend.chat(
                    f"Suggest {n} short, natural one-line replies to this "
                    f"message. One per line, no numbering, no quotes:\n\n" + text)
                lines = [ln.strip("-•\" ").strip() for ln in raw.splitlines() if ln.strip()]
                if lines:
                    return lines[:n]
            except Exception:
                # best-effort model suggestions; fall through to the canned
                # replies below on any backend failure. Debug — expected when no
                # model is wired.
                log.debug("suggest_replies backend call failed; using canned",
                          exc_info=True)
        return ["On my way", "Give me a few", "Thanks!"][:n]

    def brief(self, agenda=None, since: float = 0.0, depth: str = "short",
              commitments=None, memories=None) -> dict:
        """A morning brief at one of two depths.

        `depth="short"` (default) is the one-glance version: today's agenda +
        what's new, turned by the model into a warm couple of sentences (or the
        structured points with no model). `depth="long"` walks the whole
        morning in sections — Today, Due, Waiting on you, Messages, Yesterday —
        each item spelled out, and the model writes a few skimmable paragraphs.

        The phone passes what only it holds: `agenda` (calendar/commitment
        lines it already folds), `commitments` (open promises), and `memories`
        (yesterday's kept moments). `since` powers 'what did I miss'.
        """
        long = str(depth).lower() == "long"
        agenda = [a for a in (agenda or []) if a]
        events = []
        for e in self.calendar(8 if long else 5):     # today's events lead the brief
            when = time.strftime("%I:%M %p", time.localtime(e["ts"])).lstrip("0") if e["ts"] else ""
            events.append(e["title"] + (f" at {when}" if when else ""))
        day_end = time.time() + 86400
        due = [r for r in self.reminders() if 0 < r.get("ts", 0) <= day_end]
        due_lines = ["Reminder: " + r["title"] for r in due[:(8 if long else 3)]]
        # W6: names worth resurfacing this morning (FSRS rehearsal) — the moment
        # to relearn a name is before you next see them.
        rehearse = self.rehearsals_due(limit=(5 if long else 2))
        rehearse_lines = ["Remember: " + str(r.get("text", "")).strip()
                          for r in rehearse if str(r.get("text", "")).strip()]
        try:
            msgs = self._messages_fn(self.config, 30 if long else 20) if self.config.email_enabled else []
        except Exception:
            # best-effort message source; the brief still assembles without it.
            log.warning("message source failed in brief()", exc_info=True)
            msgs = []
        incoming = [m for m in msgs if not m.get("from_me") and m.get("ts", 0) > since]
        texts = [m for m in incoming if m.get("channel") != "email"]
        emails = [m for m in incoming if m.get("channel") == "email"]
        commitments = [c for c in (commitments or []) if c]
        memories = [m for m in (memories or []) if m]

        # -- the short brief: the original one-glance contract, unchanged ------
        if not long:
            bullets = list(agenda) + events + due_lines + rehearse_lines
            if texts:
                who = ", ".join(dict.fromkeys(m.get("who", "") for m in texts if m.get("who")))
                bullets.append(f"{len(texts)} new text{'s' if len(texts) != 1 else ''}"
                               + (f" (from {who[:60]})" if who else ""))
            for m in emails[:3]:
                subj = (m.get("subject") or m.get("text", "")[:40]).strip()
                if subj:
                    bullets.append(f"Email: {subj}")
            if not bullets:
                bullets = ["Nothing pressing — a clear morning."]
            text = "  ·  ".join(bullets)
            if self._backend is not None:
                try:
                    s = self._backend.chat(
                        "Write a warm, two-sentence morning brief from these points. "
                        "Be concrete, natural, and brief — no preamble:\n\n"
                        + "\n".join("- " + b for b in bullets))
                    if s and s.strip():
                        text = s.strip()
                except Exception:
                    # best-effort model prose; keep the structured join above on
                    # failure so the brief always returns. Debug (no-model case).
                    log.debug("brief short model call failed; using join",
                              exc_info=True)
            self.saga_record("brief")
            return {"text": text, "bullets": bullets, "depth": "short",
                    "missed": {"texts": len(texts), "emails": len(emails)}}

        # -- the long brief: sectioned, each item spelled out ------------------
        text_lines = []
        for m in texts:
            who = (m.get("who") or "Someone").strip()
            body = (m.get("text") or "").strip().replace("\n", " ")
            text_lines.append(f"{who}: {_clip_brief(body, 80)}" if body else who)
        email_lines = []
        for m in emails:
            subj = (m.get("subject") or m.get("text", "")[:60]).strip().replace("\n", " ")
            who = (m.get("who") or "").strip()
            if subj:
                email_lines.append(f"{who} — {subj}" if who else subj)

        sections = []
        if agenda or events:
            sections.append({"title": "Today", "items": list(agenda) + events})
        if due_lines:
            sections.append({"title": "Due", "items": [d.replace("Reminder: ", "") for d in due_lines]})
        if commitments:
            sections.append({"title": "Waiting on you", "items": commitments})
        if text_lines or email_lines:
            items = list(text_lines)
            if email_lines:
                items += ["✉ " + e for e in email_lines[:6]]
            sections.append({"title": "Messages", "items": items})
        if memories:
            sections.append({"title": "Yesterday", "items": memories})
        if not sections:
            sections = [{"title": "Today", "items": ["Nothing pressing — a clear morning."]}]

        bullets = [f"{s['title']}: " + "; ".join(s["items"]) for s in sections]
        text = "\n\n".join(f"{s['title']}\n" + "\n".join("• " + i for i in s["items"])
                           for s in sections)
        if self._backend is not None:
            try:
                prompt = (
                    "Write a thorough but skimmable morning brief in a few short "
                    "paragraphs. Lead with what's on today, then what's due and who's "
                    "waiting on the reader, then notable messages, then a line on "
                    "yesterday. Warm, concrete, second person, no preamble or headers:\n\n"
                    + "\n".join(f"[{s['title']}]\n" + "\n".join("- " + i for i in s["items"])
                                for s in sections))
                s = self._backend.chat(prompt)
                if s and s.strip():
                    text = s.strip()
            except Exception:
                # best-effort model prose; the sectioned text above stands in on
                # failure. Debug (expected when no model is wired).
                log.debug("brief long model call failed; using sections",
                          exc_info=True)
        self.saga_record("brief")
        return {"text": text, "bullets": bullets, "sections": sections,
                "depth": "long",
                "missed": {"texts": len(texts), "emails": len(emails)}}


def _memory_db_path(brain: Brain) -> Path:
    """Where the orchestrator's memory SQLite lives — the same file the CLI's
    `dreamlayer memories` resolves ($DREAMLAYER_DB, else <cfg_dir>/dreamlayer.db)."""
    import os
    raw = os.environ.get("DREAMLAYER_DB") or str(Path(brain.cfg_dir) / "dreamlayer.db")
    return Path(raw).expanduser()


# --- Ember (docs/EMBER.md): the phone's tending ritual + ceremony -------------

def _ember_store_path(brain: Brain):
    """The Ember store lives beside the memory DB (orchestrator convention:
    <db>.ember) — same resolution as the CLI's `dreamlayer ember`."""
    return str(_memory_db_path(brain)) + ".ember"


def _ember_state(brain: Brain) -> dict:
    """GET /dreamlayer/ember — the practice, for the phone. Engram rows ship
    cue + curve only: the ANSWER never leaves the hub. The reveal card on the
    glasses is the single surface that renders it; the phone shows the cue
    and how the wearer's own memory is doing. Tending candidates DO carry
    their summaries — the wearer can't choose what to keep unseen."""
    import os as _os
    import time as _time
    path = _ember_store_path(brain)
    if not _os.path.exists(path):
        return {"ok": True, "exists": False, "status": {}, "candidates": [],
                "engrams": [], "offers": []}
    from ...ember import EmberStore
    store = EmberStore(path)
    now = _time.time()
    day = 86400.0

    def row(e):
        return {"id": e.id, "cue": e.cue,
                "stability_days": round(e.state.stability, 1),
                "reps": e.state.reps, "lapses": e.state.lapses,
                "due_in_days": round((e.state.due_ts - now) / day, 1),
                "kept_days": int((now - e.kept_at) / day),
                "graduated": e.state.graduated, "burned": e.burned,
                "anchored": bool(e.place_signature)}

    return {
        "ok": True, "exists": True,
        "status": store.status(now),
        "candidates": [{"id": c.id, "kind": c.kind, "summary": c.summary,
                        "cue": c.cue, "salience": c.salience}
                       for c in store.candidates()],
        "engrams": [row(e) for e in store.engrams(include_burned=True)],
        "offers": [row(e) for e in store.graduated_unburned()],
    }


def _ember_tend(brain: Brain, body: dict) -> dict:
    """POST /dreamlayer/ember/tend {candidate_id, keep} — the morning choice.
    Keeps are capped per day here too (the ritual's contract holds no matter
    which surface makes the choice)."""
    import os as _os
    import time as _time
    path = _ember_store_path(brain)
    if not _os.path.exists(path):
        return {"ok": False, "error": "no ember store yet"}
    from ...ember import EmberStore
    from ...ember.tending import MAX_KEEPS_PER_DAY
    from ...rem.bias import event_key
    store = EmberStore(path)
    cid = int(body.get("candidate_id") or 0)
    keep = bool(body.get("keep"))
    now = _time.time()
    if not keep:
        ok = store.resolve_candidate(cid, kept=False) is not None
        return {"ok": ok}
    kept_today = sum(1 for e in store.engrams() if now - e.kept_at < 86400.0)
    if kept_today >= MAX_KEEPS_PER_DAY:
        return {"ok": False, "error": "tending is a ritual, not an inbox",
                "kept_today": kept_today}
    c = store.resolve_candidate(cid, kept=True)
    if c is None:
        return {"ok": False, "error": "offer already resolved"}
    e = store.keep(event_key(c.kind, c.summary), c.cue, c.summary, now,
                   place_signature=c.place_signature,
                   source_memory_id=c.source_memory_id,
                   meta={"kind": c.kind})
    return {"ok": True, "engram_id": e.id, "cue": e.cue,
            "kept_today": kept_today + 1}


def _ember_burn(brain: Brain, body: dict) -> dict:
    """POST /dreamlayer/ember/burn {engram_id, consent: true} — the ceremony,
    honored where the recording actually lives. The purge goes through the
    Retriever so the ANN vector dies with the row (a burn that leaves the
    moment recallable by similarity would be a lie), and the cue-only pinned
    tombstone is planted for the anniversary Ember lens."""
    import os as _os
    import time as _time
    path = _ember_store_path(brain)
    if not _os.path.exists(path):
        return {"ok": False, "error": "no ember store yet"}
    from ...ember import EmberStore, ceremony
    from ...memory.ann_index import PersistentAnnIndex
    from ...memory.db import MemoryDB
    from ...memory.retrieval import Retriever
    store = EmberStore(path)
    db_path = str(_memory_db_path(brain))
    db = MemoryDB(db_path) if _os.path.exists(db_path) else None
    retriever = None
    if db is not None:
        ann = None
        dim = db.get_setting("embedder_dim")
        if PersistentAnnIndex.available and dim:
            ann = PersistentAnnIndex(db_path + ".usearch", int(dim))
        retriever = Retriever(db, None, ann)
    try:
        receipt = ceremony.burn(
            store, int(body.get("engram_id") or 0),
            consent=(body.get("consent") is True),
            now=_time.time(), retriever=retriever, db=db)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    brain.activity.add("privacy",
                       f"Ember burned a graduated recording ({receipt.cue!r})")
    return {"ok": True, "engram_id": receipt.engram_id, "cue": receipt.cue,
            "reps": receipt.reps,
            "purged_memory_id": receipt.purged_memory_id,
            "tombstone_memory_id": receipt.tombstone_memory_id}


def _memory_file(brain: Brain) -> dict:
    """Panel readout for 'your memory is a file' — no CLI needed."""
    from ...memory.datasette_app import MemoryExplorer
    p = _memory_db_path(brain)
    return {
        "path": str(p),
        "exists": p.exists(),
        "bytes": p.stat().st_size if p.exists() else 0,
        "datasette": MemoryExplorer.available,
        "browse_cmd": MemoryExplorer(str(p)).command(port=8001),
    }


def _memory_browse(brain: Brain) -> dict:
    """Launch the read-only Datasette browser over the memory file (local-only).
    Returns a URL when datasette is installed, else the command to run."""
    from ...memory.datasette_app import MemoryExplorer
    info = _memory_file(brain)
    if not info["exists"]:
        return {"available": False, "error": "no memory file yet", "command": info["browse_cmd"]}
    ex = MemoryExplorer(info["path"])
    if not MemoryExplorer.available:
        return {"available": False, "command": ex.command(port=8001)}
    import shlex
    import subprocess
    try:
        meta = ex.write_metadata()
        subprocess.Popen(shlex.split(ex.command(port=8001, metadata_path=meta)))
        return {"available": True, "url": "http://127.0.0.1:8001"}
    except Exception as exc:
        return {"available": False, "error": str(exc), "command": ex.command(port=8001)}


def _memory_export(brain: Brain, dest: str) -> dict:
    """Copy the memory file somewhere (local-only). It's the user's data."""
    import shutil
    info = _memory_file(brain)
    if not info["exists"]:
        return {"ok": False, "error": "no memory file to export"}
    if not (dest or "").strip():
        return {"ok": False, "error": "no destination given"}
    d = Path(dest).expanduser()
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info["path"], d)
    return {"ok": True, "dest": str(d), "bytes": d.stat().st_size}


def _cloud_view_payload(brain: Brain) -> dict:
    """What DreamLayer Cloud can see — the opaque byte-shapes only, never content
    (INNOVATION_SESSION Category 6 / B16). The trust centerpiece: render the
    nothing. The server stores ciphertext, room ids, and counts; this reports
    exactly those, and names — in the client's own words — what it can never see.
    Honest today: with no cloud configured, the answer is 'the server holds
    nothing', which is the point."""
    try:
        caps = set(brain.plugin_capabilities())
    except Exception:
        # defensive: capability enumeration should not fail, but the cloud view
        # must render regardless. Log loudly if it ever does (that's a bug).
        log.warning("plugin_capabilities failed in cloud view", exc_info=True)
        caps = set()
    enabled = bool({"cloud_sync", "cloud_relay", "cloud_ai"} & caps)
    return {
        "enabled": enabled,
        # {bytes, last_backup_ts} once a ciphertext backup exists; None ⇒ nothing
        # stored. The server can never open it — the key is your passphrase.
        "vault": None,
        # rooms the device participates in: an opaque id + a member count, never
        # who. The relay routes; it does not read.
        "relay": {"rooms": []},
        "listings": 0,
        "cannot_see": [
            "your memories — the SQLite file never leaves the device unencrypted",
            "who you are — bonds are pairwise keys; the relay learns only a room id",
            "what a figment means — a dozen integers cross the wire, nothing more",
        ],
    }


def _builder_dir() -> "Optional[Path]":
    """Where the browser lens-builder assets live. Prefers a copy bundled into
    the package (an installed/notarized app), falls back to the repo's landing/
    (running from source, as here). None if neither is present."""
    here = Path(__file__).resolve()
    for cand in (here.parent / "assets" / "build",
                 here.parents[5] / "landing"):
        if (cand / "lens-builder.html").exists():
            return cand
    return None


def _builder_asset(name: str) -> "Optional[str]":
    d = _builder_dir()
    if d is None or "/" in name or ".." in name:
        return None
    fp = d / "assets" / "lens" / name
    return fp.read_text(encoding="utf-8") if fp.is_file() else None


_JUNO_CTYPES = {
    "js": "application/javascript; charset=utf-8",
    "mp4": "video/mp4", "webm": "video/webm",
    "webp": "image/webp", "png": "image/png",
}


def _juno_asset(name: str) -> "Optional[tuple[bytes, str]]":
    """Read a Juno sprite asset (script, packed clip, or poster) from the
    landing bundle. Binary-safe. None for anything unknown or path-escaping."""
    d = _builder_dir()
    if d is None or "/" in name or ".." in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    ctype = _JUNO_CTYPES.get(ext)
    if ctype is None:
        return None
    fp = d / "assets" / "juno" / name
    return (fp.read_bytes(), ctype) if fp.is_file() else None


_LIVE_ASSET_CTYPES = {
    ".mjs": "text/javascript", ".js": "text/javascript",
    ".wasm": "application/wasm", ".tflite": "application/octet-stream",
    ".task": "application/octet-stream",   # MediaPipe gesture recognizer bundle
}


def _live_asset(name: str) -> "Optional[tuple[bytes, str]]":
    """Read a Live Lens static asset (the vendored on-device detector: the
    MediaPipe loader .mjs, its WASM runtime, and the .tflite model) from
    ``assets/mediapipe/``. Subpaths (``wasm/…``) are allowed but confined to that
    directory — a resolved path that escapes it (``..``) or an unknown extension
    returns None. Binary-safe; these are non-secret, immutable, so the caller
    caches them hard."""
    base = (Path(__file__).resolve().parent / "assets" / "mediapipe").resolve()
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    ctype = _LIVE_ASSET_CTYPES.get(ext)
    if ctype is None:
        return None
    try:
        fp = (base / name).resolve()
        fp.relative_to(base)                       # confine to the assets dir
    except (ValueError, OSError):
        return None                                # path escape / bad name
    return (fp.read_bytes(), ctype) if fp.is_file() else None


# --- Juno's local voice (Piper) — synthesized on the Brain, played by the client
_JUNO_TTS: dict = {}


def _juno_tts(brain):
    """A per-Brain cached TTS engine for Juno's voice. Preference: Kokoro-82M (the
    natural on-device default) → her OWN cloned voice (XTTS from the baked
    juno_*.mp3 clips) → a Piper voice (`juno.onnx` in <cfg>/voices/, else any /
    $DL_PIPER_VOICE). Cached once ready so the model loads a single time; a
    not-ready instance is cheap to re-probe, so installing an engine later just
    works on the next call. Never raises."""
    key = str(getattr(brain, "cfg_dir", "") or "")
    inst = _JUNO_TTS.get(key)
    if inst is not None and getattr(inst, "ready", False):
        return inst
    inst = None
    # 0) Kokoro-82M — Juno's default on-device voice (natural, Apache-2.0, no cloud)
    try:
        from ...orchestrator.tts_kokoro import KokoroTTS
        k = KokoroTTS()
        if k.ready:
            inst = k
    except Exception:                                  # noqa: BLE001 — voice is never load-bearing
        inst = None
    # 1) her OWN cloned voice (XTTS from the baked juno_*.mp3 clips), if installed
    if inst is None:
        try:
            from ...orchestrator.voice_clone import CloneTTS
            refs = sorted((Path(__file__).resolve().parent / "assets").glob("juno_*.mp3"))
            clone = CloneTTS(refs)
            if clone.ready:
                inst = clone
        except Exception:                              # noqa: BLE001
            inst = None
    # 2) else a Piper voice (a cloned juno.onnx if present, else any / $DL_PIPER_VOICE)
    if inst is None:
        try:
            from ...orchestrator.tts_piper import PiperTTS, find_voice_model
            vdir = Path(brain.cfg_dir) / "voices" if getattr(brain, "cfg_dir", None) else None
            dirs = (vdir,) if vdir else ()
            juno = find_voice_model(str(vdir / "juno.onnx"), ()) if vdir else None
            inst = PiperTTS(voice_model=(str(juno) if juno else None), dirs=dirs)
        except Exception:                              # noqa: BLE001
            inst = None
    _JUNO_TTS[key] = inst
    return inst


def _builder_page(token: str) -> "Optional[str]":
    """The builder HTML, rewritten to load figment.js from the Brain and told
    it's same-origin (so it hides the URL/token inputs and deploys relatively).
    The token rides in only for a localhost request — exactly like the panel."""
    d = _builder_dir()
    if d is None:
        return None
    html = (d / "lens-builder.html").read_text(encoding="utf-8")
    # A same-origin <base> so EVERY relative asset resolves under the builder
    # mount (/dreamlayer/build/assets/…) and one static handler serves them —
    # the theme CSS/JS, fonts and images used to 404 as siblings of the page.
    # Must come first in <head>, before any asset ref. The deploy calls are
    # ABSOLUTE (/dreamlayer/rc/*) so <base> never touches them; it needs the
    # builder CSP to allow base-uri 'self' (BUILDER_CSP).
    base = '<base href="/dreamlayer/build/">'
    if "<head>" in html:
        html = html.replace("<head>", "<head>\n" + base, 1)
    else:                                          # tolerate <head attrs> / no head
        html = base + html
    # The lens engine + Juno sprite keep their explicit same-origin rewrites (a
    # flat, cache-stable path served pre-<base>); everything else rides the base.
    html = html.replace("./assets/lens/figment.js", "/dreamlayer/build/figment.js")
    html = html.replace("./assets/lens/qr.js", "/dreamlayer/build/qr.js")
    html = html.replace("./assets/lens/icons.js", "/dreamlayer/build/icons.js")
    html = html.replace("./assets/juno/juno.js", "/dreamlayer/build/juno/juno.js")
    inject = ("<script>window.__DL_BUILD__="
              + json.dumps({"token": token, "sameOrigin": True})
              + ";</script>")
    return html.replace("</head>", inject + "</head>", 1)


_BUILDER_CTYPES = {
    "html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "mjs": "application/javascript; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
    "ico": "image/x-icon", "mp4": "video/mp4", "webm": "video/webm",
    "mp3": "audio/mpeg", "map": "application/json",
}


def _builder_static(relpath: str) -> "Optional[tuple[bytes, str]]":
    """Serve any file under the builder's ``assets/`` dir (theme CSS/JS, fonts,
    images, the lens engine) so the same-origin builder page renders fully.
    Returns (bytes, content_type), or None for missing / unknown-type / a path
    that escapes ``assets/`` (traversal-safe: the resolved file must stay inside).
    """
    d = _builder_dir()
    if d is None:
        return None
    root = (d / "assets").resolve()
    try:
        fp = (root / relpath).resolve()
    except Exception:
        return None
    if fp != root and root not in fp.parents:      # no ../ escape out of assets/
        return None
    if not fp.is_file():
        return None
    ctype = _BUILDER_CTYPES.get(fp.suffix.lower().lstrip("."))
    if ctype is None:
        return None
    return (fp.read_bytes(), ctype)


def _brain_view_payload(brain: Brain) -> dict:
    """The Brain as a cartridge (INNOVATION_SESSION 3.1): the live tier ladder —
    on-device → Mac mini → cloud — each with the round-trip latency the router
    actually measured (health ledger), plus which model is loaded and the cloud/
    incognito switches. Makes the router's judgment visible and swappable."""
    seams = {}
    try:
        seams = brain.health.snapshot()
    except Exception:
        # defensive: the health snapshot should always render; if it can't, the
        # tier ladder still returns. Log — an exception here signals a real bug.
        log.warning("health snapshot failed in brain view", exc_info=True)
        seams = {}
    cloud_on = bool(brain.config.cloud_enabled) and not brain.config.lan_only
    incognito = brain.incognito_now()

    def tier(seam_key, name, note, enabled):
        s = seams.get(f"brain:{seam_key}", {})
        ok, fail = int(s.get("successes", 0)), int(s.get("failures", 0))
        total = ok + fail
        return {
            "id": seam_key, "name": name, "note": note, "enabled": enabled,
            "latency_ms": s.get("latency_ms"),          # None until it has answered
            "answered": ok, "failed": fail,
            "reliability": round(ok / total, 2) if total else None,
            "seen": total > 0,
        }

    mac_on = not brain.config.lan_only            # local-only ("phone is the brain") drops the remote tier
    tiers = [
        tier("device", "On-device", "small, instant, always yours", True),
        tier("mac_mini", "Mac mini", "bigger local model, over your own files", mac_on),
        tier("cloud", "Cloud",
             "the hardest, non-personal asks" if cloud_on else "off — nothing leaves the device",
             cloud_on and not incognito),
    ]
    # the tier that would answer now = the highest-preference enabled one
    active = next((t["id"] for t in tiers if t["enabled"]), "device")
    return {
        "model": brain.config.model,               # the loaded cartridge
        "cloud_provider": getattr(brain.config, "cloud_provider", "") or "",
        "cloud": cloud_on,
        "incognito": incognito,
        "active_tier": active,
        "tiers": tiers,
    }


def _capability_payload(brain: Brain) -> dict:
    """Live optional-capability report for the panel (dreamlayer/capabilities.py)
    with the panel's own persisted off-switches applied. Env DL_DISABLE_* still
    works as the ops-level override; `config.disabled_caps` is the same switch
    made durable, since the bundled .app has no env of its own to edit."""
    import os
    import sys
    from ...capabilities import (PROFILES, packs_report, report, summary,
                                 pack_installer_available, power_stats, tiers)
    env = dict(os.environ)
    for key in brain.config.disabled_caps:
        env.setdefault("DL_DISABLE_" + key.upper(), "1")
    # `social_graph` is promoted HERE rather than by a long-lived flag, because it
    # has no start/stop event to hang one on the way the ear does — a graph is
    # simply built and answered on demand. Computed fresh into this local env copy
    # (never os.environ), so the report cannot go stale in either direction: no
    # flag to leave set after the last meeting is deleted, and none to forget to
    # set after the first is recorded. The test is deliberately strict — networkx
    # present AND a non-empty graph — since networkx over an empty graph answers
    # every query with nothing, exactly as the fallback does.
    try:
        if brain.social_graph_wired():
            env["DL_WIRED_SOCIAL_GRAPH"] = "1"
    except Exception:                           # noqa: BLE001 — never 500 the report
        pass
    # `dream_style` on the same terms, and PROOF-based for the same reason the
    # ear's interpreter is: onnxruntime importing says nothing about a model
    # loading, and a loaded session can still fail on a frame. `_dream_neural_ok`
    # is set by the lens only after the neural painter has genuinely produced a
    # picture. It is re-checked against the configured path so removing the model
    # takes the capability back down — proof that it once worked is not a claim
    # that it still can.
    try:
        if brain.dream_neural_ready():
            env["DL_WIRED_DREAM_STYLE"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `crdt_sync`, same discipline: loro importing is not a sync. The flag follows
    # a merge that actually read a peer's snapshot on this process.
    try:
        if getattr(brain, "_sync_ok", False):
            env["DL_WIRED_CRDT_SYNC"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `speaker_id` — the strictest of the lot, because being wrong here attaches a
    # real name to the wrong person's words. Promoted only when a speaker model
    # ACTUALLY LOADED (not merely the speechbrain wheel, whose absence makes
    # `embed` return a hash of the audio's string form) AND the wearer has
    # consented AND the switch is on. Any of those missing and the ear runs
    # unattributed, which is the honest default.
    try:
        vr = brain.voice_recall()
        if vr is not None and vr.enabled and vr.model_available:
            env["DL_WIRED_SPEAKER_ID"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `wasm_plugins`, same rule again: wasmtime importing is not a guest. The
    # flag follows a `.wasm` package that is instantiated RIGHT NOW in the
    # in-process component host — capability-enforced, zero ambient authority —
    # because that is the only condition under which the tier is in use. Remove
    # the plugin and the capability goes back down.
    try:
        from ...plugins.wasm_plugin_host import live_guests
        if live_guests() > 0:
            env["DL_WIRED_WASM_PLUGINS"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `extism_plugins` — the second WASM runtime, same rule and its own count,
    # because the two hosts confine differently and a wearer running one is not
    # running the other.
    try:
        from ...plugins.extism_plugin_host import live_guests as _extism_live
        if _extism_live() > 0:
            env["DL_WIRED_EXTISM_PLUGINS"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `object_tracking` — supervision importing is not a tracked object, and
    # neither is a ByteTrack that was constructed and never handed a centroid
    # (which is what it was for as long as nothing produced any). The flag
    # follows the ambient trail having actually keyed a sighting by track id,
    # through the real library rather than its centroid fallback.
    try:
        if brain.object_trail.tracking_live():
            env["DL_WIRED_OBJECT_TRACKING"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `diarization` — diart importing is not a diarized turn, and neither is a
    # pipeline that has only ever heard one voice (its fallback answers exactly
    # that for everything). The flag follows the capture pipeline having
    # genuinely SPLIT a segment into more than one anonymous speaker.
    try:
        # Either ear counts, exactly as the ear's own cap union does above: the
        # Mac's own mic or the phone streaming in.
        for _e in (getattr(brain, "_ear", None),
                   getattr(brain, "_remote_ear", None)):
            pipe = getattr(_e, "_pipe", None)
            if pipe is not None and getattr(pipe, "last_voices", 0) > 1:
                env["DL_WIRED_DIARIZATION"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `memory_dedup` — near-duplicate collapsing over what the wearer is shown.
    # The flag follows a scrub list that ACTUALLY merged something: collapsing
    # is on the read path unconditionally, so "the code ran" is not evidence,
    # and a wearer who never repeats themselves has nothing to dedup and should
    # not be told the capability is doing work.
    try:
        _ls = getattr(brain, "_lenses", None)
        _r = getattr(_ls, "_ring", None) if _ls is not None else None
        if _r is not None:
            from ...memory.dedup import collapse as _collapse
            _rows = _r.latest(limit=200)
            if len(_collapse(_rows, lambda b: (b.event.summary or ""))) < len(_rows):
                env["DL_WIRED_MEMORY_DEDUP"] = "1"
    except Exception:                               # noqa: BLE001
        pass
    # `coreml_ondevice` — the Apple Neural Engine rung of the vision ladder. The
    # flag follows a real prediction, never `available`: the adapter used to
    # return None on both branches of its only statement, so a wheel being
    # importable was never evidence of anything. A compiled model on disk is not
    # either — only a label that came back.
    try:
        from ...object_lens.classify_backends import CoreMLClassifier
        from .live import _classifier as _vision_ladder
        _rung = _vision_ladder()
        if isinstance(_rung, CoreMLClassifier) and _rung.predictions > 0:
            env["DL_WIRED_COREML_ONDEVICE"] = "1"
    except Exception:                               # noqa: BLE001
        pass
    # `typed_models` — the Veil as a type invariant on the ring's keep path.
    # The flag follows an invariant that has actually VETTED an append, not a
    # gate having been handed over: a ring nothing has been kept into is a
    # tripwire nobody has crossed, and reporting that as a live guarantee is
    # the same overclaim as calling an importable adapter wired.
    try:
        for _r in (getattr(getattr(brain, "_lenses", None), "_ring", None),
                   getattr(getattr(brain, "_world_lens", None), "ring", None)):
            if getattr(_r, "veil_checks", 0) > 0:
                env["DL_WIRED_TYPED_MODELS"] = "1"
    except Exception:                               # noqa: BLE001
        pass
    # `persona_tuning` — the wearer's interruption bar, and the flag follows a
    # bar that `tune()` genuinely RETURNED from their own swats. Not hulearn
    # being importable, and not the gate existing: a gate whose history is too
    # short, or whose wearer reacted the same way to everything, refuses and
    # reports 0.0 — which is the honest answer, and not a wired capability.
    try:
        from .attention_live import gate as _attn_gate
        if _attn_gate(brain).tuning_live():
            env["DL_WIRED_PERSONA_TUNING"] = "1"
    except Exception:                               # noqa: BLE001
        pass
    # `fs_watch` — the folders reacting instead of being asked. The flag
    # follows a change event genuinely DELIVERED, never an observer having
    # started: starting one on a network mount that emits nothing looks
    # identical to starting one that works, right up until the wearer saves a
    # file and waits — and what keeps working in that case is the timer, so
    # reporting the watcher live would name the wrong mechanism.
    try:
        _fw = getattr(brain, "_fs_watchers", None)
        if _fw is not None and _fw.driving():
            env["DL_WIRED_FS_WATCH"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `lan_discovery` — the Brain's presence on the LAN. Weaker evidence than
    # the rest of this block, and worth naming as such: mDNS gives a publisher
    # no way to learn that anything listened, so there is no "it answered" to
    # wait for. `registered` is the strongest proof available and is still much
    # more than `import zeroconf` — an address was found, a service was
    # accepted, and the beacon is live on this LAN right now. It goes back down
    # when the Brain stops advertising, which is what makes it a state.
    try:
        _bcn = getattr(brain, "_beacon", None)
        if _bcn is not None and _bcn.driving():
            env["DL_WIRED_LAN_DISCOVERY"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `nlp` — the parse behind commitments, and the flag follows a FIELD the
    # regex had left empty and the parser filled. Not `CommitmentNLP.available`,
    # which is only "spacy imported": the extractor honours the floor, so on a
    # sentence the regex already handles the parser correctly adds nothing, and
    # that is the fallback working rather than the capability driving. It also
    # does not follow "the pass ran" — `sharpen` runs on every commitment row
    # whether or not spaCy is installed.
    try:
        from .nlp_live import nlp_live as _nlp
        if getattr(brain, "_nlp_live", None) is not None and _nlp(brain).live():
            env["DL_WIRED_NLP"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    # `event_bus` — a `MeshEventBus` exists only around a MeshManager that has
    # joined a circle, and until GhostMode was reachable nothing ever joined
    # one. The flag follows a circle live on this Brain right now, so it goes
    # back down when the evening ends.
    try:
        from .live_circle import room as _circle_room
        if _circle_room(brain).members_live() > 0:
            env["DL_WIRED_EVENT_BUS"] = "1"
    except Exception:                           # noqa: BLE001
        pass
    packs = packs_report(env=env)
    for p in packs:                             # overlay live install progress
        job = _PACK_JOBS.get(p["key"])
        if job:
            p["install"] = dict(job)
    return {"items": report(env=env), "summary": summary(env=env),
            # the awakening meter + the group headers the page opens with
            "stats": power_stats(env=env), "tiers": tiers(),
            "profiles": {k: list(v) for k, v in PROFILES.items()},
            "disabled": list(brain.config.disabled_caps),
            "packs": packs,
            # py2app/PyInstaller set sys.frozen. The bundle can't pip-install into
            # ITSELF, but it CAN install packs into the writable sidecar when it
            # carries pip — pack_installable says which, so the panel offers the
            # one-click 'Install pack' whenever it will actually work and only
            # falls back to 'runs on a source install' when it truly can't.
            "frozen": bool(getattr(sys, "frozen", False)),
            "pack_installable": pack_installer_available()}


# --- pack installer ----------------------------------------------------------
# One-click upgrade for SOURCE installs: pip-installs a curated pack's pinned
# requirements into this very environment, in a background thread, one pack at
# a time. The frozen .app refuses (a sealed signed bundle can't modify itself)
# and the panel words that honestly. `_PACK_RUNNER` is injectable for tests.

_PACK_JOBS: dict = {}            # pack key -> {"state","detail","ts"}
_PACK_LOCK = threading.Lock()
_PIP_TIMEOUT_S = 3600.0          # hard wall on a pip install (module-level so tests can shorten it)


# --- Live Lens short pairing code ---------------------------------------------
# The Live Lens link carries the Brain token in its URL FRAGMENT — a scanned QR
# delivers it, but a hand-typed URL drops it, so a phone that can't scan is
# stuck. This vault issues a short numeric code the wearer reads off the panel
# and types on the live page to redeem the token. It is a network-reachable
# token handout, so it is deliberately narrow:
#   * 8 digits (1e8 space), generated with secrets;
#   * exactly ONE code active at a time (issuing a new one voids the old);
#   * a short TTL (issued only when the wearer is actively pairing);
#   * SINGLE-USE — a successful redeem consumes it;
#   * a wrong guess never consumes it (so an attacker can't void the real one),
#     but every attempt is brute-force locked out on the SHARED auth limiter;
#   * a GLOBAL per-code attempt cap on top of the per-IP lockout, so an attacker
#     rotating source IPs (an IPv6 /64) still can't out-guess one code's life.
_LIVE_CODE_DIGITS = 8
_LIVE_CODE_TTL_S = 300.0         # 5 minutes
_LIVE_CODE_MAX_ATTEMPTS = 100    # total guesses against ONE code before it self-voids


class _LiveCodeVault:
    """One active, short-lived, single-use code → the Brain token."""

    def __init__(self, now_fn=time.monotonic):
        self._lock = threading.Lock()
        self._now = now_fn
        self._code: str = ""
        self._token: str = ""
        self._expiry: float = 0.0
        self._attempts: int = 0

    def issue(self, token: str, ttl: float = _LIVE_CODE_TTL_S) -> str:
        import secrets
        code = "".join(secrets.choice("0123456789") for _ in range(_LIVE_CODE_DIGITS))
        with self._lock:
            self._code = code
            self._token = token
            self._expiry = self._now() + ttl
            self._attempts = 0
        return code

    def current(self) -> str:
        """The active, UNEXPIRED code without issuing (and voiding) a new one —
        so a second delivery channel (pair-by-sound) hands out the SAME code the
        QR/typed path already showed, never a colliding one. "" when none is live."""
        with self._lock:
            return self._code if (self._code and self._now() < self._expiry) else ""

    def redeem(self, code: str):
        """Return the token for a correct, unexpired code (and consume it), else
        None. A wrong or expired code returns None WITHOUT consuming a live one."""
        import hmac
        # A wrong/odd guess must never RAISE: hmac.compare_digest() throws on a
        # non-ASCII string, which would escape the handler as a 500 AND land
        # *before* the caller's record_failure() — an un-throttled traceback DoS
        # that the per-IP lockout never sees. The code is always ASCII digits, so
        # reject anything else up front (the format is public — this leaks nothing).
        if not isinstance(code, str) or not code or not code.isascii():
            return None
        with self._lock:
            if not self._code or self._now() >= self._expiry:
                self._code = ""; self._token = ""; self._expiry = 0.0
                return None
            # Global attempt cap (IP-independent): the per-IP HTTP lockout can be
            # sidestepped by rotating source addresses, so bound total guesses
            # against ANY one code. Over the cap → void it; the wearer regenerates.
            self._attempts += 1
            if self._attempts > _LIVE_CODE_MAX_ATTEMPTS:
                self._code = ""; self._token = ""; self._expiry = 0.0
                return None
            if not hmac.compare_digest(code, self._code):
                return None                       # wrong guess — leave the real code live
            tok = self._token
            self._code = ""; self._token = ""; self._expiry = 0.0   # single-use
            return tok


def _pip_env() -> dict:
    """A pip environment with the index-redirecting vars stripped, so an
    inherited ``PIP_INDEX_URL`` / ``PIP_EXTRA_INDEX_URL`` / ``PIP_CONFIG_FILE``
    (env or a dropped pip.conf) can't silently point a pack install at an
    attacker's index. Curated packs always resolve from the default PyPI."""
    import os
    env = dict(os.environ)
    for k in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CONFIG_FILE"):
        env.pop(k, None)
    return env


def _pip_progress_parser(job: dict, total: int):
    """Turn pip's line output into an honest, monotonic job percent.

    pip narrates its work — "Collecting x", "Downloading x (12.3 MB)", "Using
    cached x", "Installing collected packages" — so a bar can move on REAL
    events instead of a fake ticker. The denominator grows as pip discovers
    transitive deps (start from the pack's own requirement count), download
    events advance 5→85, the install phase pins 90, and _install_pack sets 100
    on success. max() keeps the bar from ever sliding backward."""
    seen: set = set()
    done: set = set()

    def bump(p: int) -> None:
        job["percent"] = max(int(job.get("percent") or 0), max(0, min(99, p)))

    def on_line(raw: str) -> None:
        line = raw.strip()
        if line.startswith("Collecting "):
            name = line.split(None, 1)[1].split("==")[0].split(">=")[0].split("[")[0]
            seen.add(name)
            job["detail"] = f"resolving {name}"
            bump(5 + int(80 * len(done) / max(total, len(seen))))
        elif line.startswith(("Downloading ", "Using cached ")) or " Downloading " in line:
            token = line.replace("Using cached ", "Downloading ").split("Downloading ", 1)[-1]
            done.add(token.split()[0] if token else line)
            job["detail"] = f"downloading {len(done)} of ~{max(total, len(seen))}"
            bump(5 + int(80 * len(done) / max(total, len(seen))))
        elif line.startswith("Installing collected packages"):
            job["detail"] = "installing…"
            bump(90)

    return on_line


def _req_name(req: str) -> str:
    """The bare distribution name from a requirement string, for a human note
    ('pylsl<2,>=1' -> 'pylsl')."""
    import re
    m = re.match(r"\s*([A-Za-z0-9._-]+)", req or "")
    return m.group(1) if m else (req or "").strip()


def _install_resilient(reqs: list, on_line, once) -> tuple:
    """Install a pack's requirements so ONE fragile dependency can't fail the
    whole pack. Try the fast batch first (shared-dependency resolution in a single
    pip run); if that fails, install each requirement on its OWN and salvage
    everything installable, naming only what genuinely couldn't be added (refute
    2026-07-21: the Operator pack's 19-package long tail meant a single build /
    wheel failure marked the ENTIRE pack "failed — pip exited 1", even though 18
    of 19 would install). ``once(subset)`` runs one pip install of that subset.

    Returns (ok, detail): ok=True when ALL installed; a ``"PARTIAL:…"`` detail when
    some installed and some didn't (the pack is usable, minus the named few); a
    plain failure only when nothing could be installed."""
    ok, detail = once(list(reqs))
    if ok or len(reqs) <= 1:
        return ok, detail
    installed: list = []
    failed: list = []
    for r in reqs:
        o, _ = once([r])
        (installed if o else failed).append(r)
    if not failed:
        return True, "installed"
    # Some extras are build-only (no universal wheel — frame-sdk, birdnetlib):
    # they fail deterministically on a machine without a compiler. Skip those
    # from the failure accounting so a pack whose ONLY gaps are build-only deps
    # completes instead of re-looping "Retry the rest" forever on a dep that can
    # never install here. We still ATTEMPTED them above, so a machine that CAN
    # build them gets them.
    from ...capabilities import PACK_OPTIONAL_REQS
    hard = [r for r in failed if _req_name(r).lower() not in PACK_OPTIONAL_REQS]
    skipped = [r for r in failed if _req_name(r).lower() in PACK_OPTIONAL_REQS]
    if not hard:
        if skipped:
            sn = ", ".join(_req_name(r) for r in skipped)
            return True, ("installed — skipped %d build-only extra%s (%s: needs a "
                          "compiler; the rest of the pack is active)"
                          % (len(skipped), "" if len(skipped) == 1 else "s", sn))
        return True, "installed"
    names = ", ".join(_req_name(r) for r in hard)
    if installed:
        return False, ("PARTIAL:added %d of %d — couldn't add %s (needs a build "
                       "tool or a wheel this machine doesn't have; the rest of "
                       "the pack is active)"
                       % (len(installed), len(reqs), names))
    return False, ("couldn't add the pack's packages (%s) — %s"
                   % (names, (detail or "pip failed")[-160:]))


def _constraints_file(reqs: list):
    """The pack's FULL pin list as a pip constraints file. The per-package
    salvage loop passes it with -c so each lone install still resolves inside
    the pack's own pins — without it, N independent resolutions could up/
    downgrade shared deps the batch resolver had refused, and the union would
    be reported as "installed" (refute 2026-07-21, pack-salvage audit)."""
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", prefix="dl-pack-c-",
                                    delete=False)
    f.write("\n".join(reqs) + "\n")
    f.close()
    return f.name


def _pip_subprocess_once(reqs: list, on_line=None, constraints=None) -> tuple:
    """Source-install runner: pip install `reqs` into this interpreter's
    environment, streaming each output line into `on_line` (progress). Returns
    (ok, last_output_lines). One pip invocation — the resilient wrapper (_run_pip)
    handles the salvage retry."""
    import subprocess
    import sys
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir",
           "--progress-bar", "off", *reqs]
    if constraints:
        cmd += ["-c", str(constraints)]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                env=_pip_env())
        tail: list = []
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip())
            if len(tail) > 6:
                tail.pop(0)
            if on_line:
                try:
                    on_line(line)
                except Exception:               # a progress hiccup never kills pip
                    pass
        code = proc.wait(timeout=_PIP_TIMEOUT_S)
        return code == 0, "\n".join(tail)
    except Exception as exc:                     # pip missing, timeout, decode error…
        return False, str(exc)
    finally:
        # Never leave a detached pip running (a wait() timeout or a mid-stream
        # exception would otherwise orphan the child AND let a retry launch a
        # SECOND concurrent pip, since the job flips to "failed" while the first
        # still installs). Kill it and reap so the fd/process can't leak.
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


def _run_pip(reqs: list, on_line=None) -> tuple:
    """Default pack runner (source install): resilient batch-then-per-package so
    one fragile dependency can't fail the whole pack (see _install_resilient)."""
    all_reqs = list(reqs)
    import os as _os
    cpath = None
    try:
        try:
            # ONE constraints file per run, removed afterwards (a leak of one
            # temp file per salvage attempt — refute 2026-07-21); creation
            # failure degrades to no constraints, never a dead job thread
            cpath = _constraints_file(all_reqs) if len(all_reqs) > 1 else None
        except Exception:
            cpath = None
        return _install_resilient(
            all_reqs, on_line,
            lambda subset: _pip_subprocess_once(
                subset, on_line,
                # salvage runs one req at a time — constrain each to the
                # pack's own pins so N independent resolutions can't drift
                # from what the batch resolver checked
                constraints=cpath if len(subset) < len(all_reqs) else None))
    finally:
        if cpath:
            try:
                _os.unlink(cpath)
            except OSError:
                pass


# Variable-arity by contract: a runner may take (reqs) or (reqs, on_line=…);
# _install_pack's _call_runner feeds on_line only to one that declares it. The
# permissive annotation lets tests inject a 1-arg lambda without a mypy clash.
_PACK_RUNNER: "Callable[..., tuple]" = _run_pip


def _pip_target_once(reqs: list, target: str, on_line=None,
                     constraints=None) -> tuple:
    """Frozen-app single-shot: install `reqs` into a WRITABLE sidecar via in-process
    pip ``--target`` (a sealed, code-signed bundle has no external python/pip to shell
    out to, and must not — can not — install into itself). pip runs inside THIS
    interpreter, so it resolves wheels for the bundled Python's own version and
    platform. Progress: in-process pip narrates through the ``pip`` logger, so a
    temporary handler feeds `on_line` the same lines the subprocess path parses —
    no stdout redirection games (which would be process-global and thread-unsafe).
    Returns (ok, detail). Absent pip → a clear failure, never a crash — the panel
    then still shows the honest source-install note (audit 2026-07-19)."""
    try:
        from pip._internal.cli.main import main as pip_main
    except Exception as exc:                     # pip not bundled in this build
        return False, f"this build can't add packs (pip unavailable: {exc})"
    argv = ["install", "--target", str(target), "--upgrade", "--no-input",
            "--no-cache-dir", "--disable-pip-version-check",
            "--no-warn-script-location", "--progress-bar", "off", *reqs]
    if constraints:
        argv += ["-c", str(constraints)]
    import logging
    import os

    class _LineHandler(logging.Handler):         # pip's narration → on_line
        def emit(self, record):
            try:
                if on_line:
                    on_line(record.getMessage())
            except Exception:                    # progress must never break pip
                pass

    handler = _LineHandler()
    pip_logger = logging.getLogger("pip")
    saved = {k: os.environ.pop(k, None)           # in-process pip reads these live;
             for k in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CONFIG_FILE")}
    pip_logger.addHandler(handler)
    try:
        code = pip_main(argv)
    except SystemExit as e:                       # pip can raise SystemExit
        code = e.code if isinstance(e.code, int) else 1
    except Exception as exc:                       # noqa: BLE001 — never crash the job thread
        return False, str(exc)[-400:]
    finally:
        pip_logger.removeHandler(handler)
        for k, v in saved.items():                # restore the caller's environment
            if v is not None:
                os.environ[k] = v
    if code == 0:
        import importlib
        importlib.invalidate_caches()             # so find_spec sees the new packages now
        return True, "installed"
    return False, f"pip exited {code}"


def _run_pip_target(reqs: list, target: str, on_line=None) -> tuple:
    """Frozen-app pack runner: resilient batch-then-per-package into the sidecar so
    one fragile dependency can't fail the whole pack (see _install_resilient)."""
    all_reqs = list(reqs)
    import os as _os
    cpath = None
    try:
        try:
            cpath = _constraints_file(all_reqs) if len(all_reqs) > 1 else None
        except Exception:
            cpath = None
        return _install_resilient(
            all_reqs, on_line,
            lambda subset: _pip_target_once(
                subset, target, on_line,
                constraints=cpath if len(subset) < len(all_reqs) else None))
    finally:
        if cpath:
            try:
                _os.unlink(cpath)
            except OSError:
                pass


_PACK_RUNNER_FROZEN: "Callable[..., tuple]" = _run_pip_target


# --- Unified download queue ---------------------------------------------------
# One serial queue over the EXISTING install machineries: capability packs
# (_install_pack jobs), model pulls (_pull_model_async jobs), and store
# plugins (brain.store_install). Items run one at a time in enqueue order;
# the panel polls /dreamlayer/downloads for positions + live progress, and
# "Download all" is just enqueue-many. Only a still-queued item can cancel —
# the underlying machineries have no mid-flight cancel, and pretending
# otherwise would lie about what's on disk.
_DL_QUEUE: list = []
_DL_LOCK = threading.Lock()
_DL_WORKER: dict = {"t": None}
_DL_KINDS = ("pack", "model", "plugin")


def _dl_snapshot() -> list:
    with _DL_LOCK:
        out = []
        pos = 0
        for it in _DL_QUEUE:
            d = {k: it[k] for k in ("id", "kind", "key", "state", "detail",
                                    "percent")}
            if it["state"] == "queued":
                d["position"] = pos
            if it["state"] in ("queued", "running"):
                pos += 1
            out.append(d)
        return out


def _dl_enqueue(brain: Brain, kind: str, key: str) -> dict:
    kind, key = (kind or "").strip(), (key or "").strip()
    if kind not in _DL_KINDS or not key:
        return {"error": "unknown download kind or empty name"}
    with _DL_LOCK:
        live = sum(1 for i in _DL_QUEUE if i["state"] in ("queued", "running"))
        if live >= 64:                       # cross-request growth cap (refute F4)
            return {"error": "the queue is full — let some downloads finish"}
        for it in _DL_QUEUE:
            if (it["kind"], it["key"]) == (kind, key) and \
                    it["state"] in ("queued", "running"):
                return {"ok": True, "id": it["id"], "note": "already queued"}
        item = {"id": max((i["id"] for i in _DL_QUEUE), default=0) + 1,
                "kind": kind, "key": key, "state": "queued",
                "detail": "queued", "percent": 0}
        _DL_QUEUE.append(item)
        t = _DL_WORKER.get("t")
        if t is None or not t.is_alive():
            t = threading.Thread(target=_dl_drain, args=(brain,), daemon=True)
            _DL_WORKER["t"] = t
            t.start()
        return {"ok": True, "id": item["id"]}


def _dl_cancel(item_id: int) -> dict:
    with _DL_LOCK:
        for it in _DL_QUEUE:
            if it["id"] == item_id and it["state"] == "queued":
                it["state"], it["detail"] = "cancelled", "cancelled"
                return {"ok": True}
    return {"error": "only a still-queued download can be cancelled"}


def _dl_next():
    with _DL_LOCK:
        # prune finished rows EVERY pass (not only at drain) so a long-running
        # item can't let the list grow unboundedly across requests (refute F4)
        done = [x for x in _DL_QUEUE
                if x["state"] in ("done", "failed", "partial", "cancelled")]
        for x in done[:-20]:
            _DL_QUEUE.remove(x)
        for it in _DL_QUEUE:
            if it["state"] == "queued":
                it["state"], it["detail"] = "running", "starting…"
                return it
        # drained: clear the worker slot UNDER THE LOCK — an enqueue landing
        # between this decision and the thread dying saw is_alive()==True and
        # stranded its item with no worker (refute F3)
        _DL_WORKER["t"] = None
        return None


def _dl_drain(brain: Brain) -> None:
    while True:
        it = _dl_next()
        if it is None:
            return
        try:
            _dl_run_one(brain, it)
        except Exception as exc:                  # noqa: BLE001 — queue never dies
            it["state"], it["detail"] = "failed", str(exc)[-160:]


_DL_BUSY = ("another pack is already installing",
            "too many downloads at once")


def _dl_live_job(kind: str, key: str, job: dict) -> dict:
    """The LIVE job dict to poll. _pull_model_async returns a shallow COPY
    (its worker mutates the original in _PULL_JOBS), so polling the return
    value showed 0%/pulling forever and wedged the queue for the full hour
    (refute F1). Packs already return the live dict."""
    if kind == "model":
        with _PULL_LOCK:
            return _PULL_JOBS.get(key, job)
    return job


def _dl_run_one(brain: Brain, it: dict, poll_s: float = 1.0,
                max_polls: int = 3600) -> None:
    kind, key = it["kind"], it["key"]
    if kind == "plugin":
        # bound the synchronous store install — a stalled registry fetch must
        # not wedge the single queue worker forever (refute F5)
        box: dict = {}

        def _go():
            try:
                box["res"] = brain.store_install(key)
            except Exception as exc:              # noqa: BLE001
                box["res"] = {"error": str(exc)[-160:]}
        t = threading.Thread(target=_go, daemon=True)
        t.start()
        t.join(timeout=180)
        res = box.get("res")
        if res is None:
            it["state"], it["detail"] = "failed", "plugin install timed out"
        elif res.get("ok"):
            it["state"], it["percent"], it["detail"] = "done", 100, "installed"
        else:
            errs = res.get("errors") or [res.get("error") or "install failed"]
            it["state"], it["detail"] = "failed", str(errs[0])[-160:]
        return
    launch = _install_pack if kind == "pack" else _pull_model_async
    job = launch(brain, key)
    polls = 0
    while "error" in job and any(b in str(job["error"]) for b in _DL_BUSY):
        # a DIRECT panel install/pull is mid-flight — WAIT for our turn
        # instead of failing the whole batch spuriously (refute F2/F7)
        it["detail"] = "waiting for the current install to finish…"
        polls += 1
        if polls >= max_polls:
            it["state"], it["detail"] = "failed", "timed out waiting in line"
            return
        time.sleep(poll_s)
        job = launch(brain, key)
    if "error" in job:
        it["state"], it["detail"] = "failed", str(job["error"])[-160:]
        return
    for _ in range(polls, max_polls):             # ≤1h per item
        live = _dl_live_job(kind, key, job)
        st = live.get("state")
        it["percent"] = int(live.get("percent") or 0)
        it["detail"] = str(live.get("detail") or st or "")[:160]
        if st in ("done", "failed", "partial"):
            it["state"] = st
            return
        time.sleep(poll_s)
    it["state"], it["detail"] = "failed", "timed out after an hour"


def _install_pack(brain: Brain, pack_key: str) -> dict:
    """Validate and launch a pack install. Returns the job dict (or an error).

    In a SOURCE run, packs pip-install into the environment. In the FROZEN app
    they install into the writable sidecar (<cfg>/site-packages, added to
    sys.path at startup) via pip --target — so the one-click 'Install pack' works
    in the bundled app too, instead of demanding a source install (audit
    2026-07-19). If the frozen build carries no pip, the job fails honestly and
    the panel keeps the source-install wording."""
    import sys
    from ...capabilities import pack_requirements, pack_site_dir
    reqs = pack_requirements(pack_key)
    if not reqs:
        return {"error": f"unknown pack: {pack_key}"}
    if brain.incognito_now():                    # pip → PyPI is egress; honor posture
        return {"error": "installing a pack needs the network — you're in "
                         "Incognito or LAN-only right now"}
    frozen = bool(getattr(sys, "frozen", False))
    with _PACK_LOCK:
        if any(j.get("state") == "installing" for j in _PACK_JOBS.values()):
            return {"error": "another pack is already installing"}
        job = {"state": "installing", "percent": 0,
               "detail": f"{len(reqs)} packages", "ts": time.time()}
        _PACK_JOBS[pack_key] = job

    on_line = _pip_progress_parser(job, len(reqs))

    def _call_runner(runner, *args):
        """Injected test runners are plain `lambda reqs:` — only feed on_line
        to a runner that declares it, so the seam stays backward-compatible."""
        import inspect
        try:
            if "on_line" in inspect.signature(runner).parameters:
                return runner(*args, on_line=on_line)
        except (TypeError, ValueError):
            pass
        return runner(*args)

    def work():
        if frozen:
            ok, detail = _call_runner(_PACK_RUNNER_FROZEN, reqs,
                                      str(pack_site_dir(brain.cfg_dir)))
        else:
            ok, detail = _call_runner(_PACK_RUNNER, reqs)
        detail = detail or ""
        if ok:
            job["state"], job["percent"] = "done", 100
            tail = " — reload the panel; restart the Brain if a capability stays dark"
            # keep the honest "skipped a build-only extra" note when there was one
            job["detail"] = (detail + tail) if detail.startswith("installed — skipped") \
                else ("installed" + tail)
        elif detail.startswith("PARTIAL:"):     # some installed, a few couldn't —
            job["state"], job["percent"] = "partial", 100   # the pack is still usable
            job["detail"] = detail[len("PARTIAL:"):]
        else:
            job["state"] = "failed"
            job["percent"] = job.get("percent", 0)
            job["detail"] = detail[-400:] or "failed"
        job["ts"] = time.time()
        brain.activity.add("config", f"Pack {pack_key} install "
                           + {"done": "finished", "partial": "partly finished"}
                           .get(job["state"], "failed"))

    threading.Thread(target=work, daemon=True).start()
    brain.activity.add("config", f"Pack {pack_key} install started")
    return job


# --- Ollama model pull (background + progress) --------------------------------
# A multi-GB pull (llama3.2-vision ≈ 8 GB) over one blocking request times the
# browser out long before it finishes and shows no progress — so the "Pull"
# button looks broken. Mirror the pack installer: kick a background thread that
# STREAMS Ollama's pull progress into a job the panel polls, so the request
# returns instantly and the panel shows a moving %.
_PULL_JOBS: dict = {}                    # model name -> {"state","percent","detail","ts"}
_PULL_LOCK = threading.Lock()
_PULL_JOBS_MAX = 32
_PULL_JOB_TTL_S = 600.0
_PULL_MAX_INFLIGHT = 3           # cap concurrent downloads (chat+vision+embed)


def _model_name_ok(name: str) -> bool:
    """Reject a model ref that pins an explicit registry HOST, so a one-click
    pull can only reach Ollama's DEFAULT registry — never an attacker-chosen
    `evil.example/backdoor:latest`. Ollama refs are `[host[:port]/]ns/name[:tag]`,
    so a host shows up as a dotted or port-bearing FIRST path segment (a bare
    `name:tag` or `library/name` carries no host and is fine)."""
    n = (name or "").strip()
    if not n or any(ord(c) < 32 or c.isspace() for c in n):
        return False
    # Ollama resolves the registry HOST by COMPONENT COUNT: `host/namespace/name`
    # (3 parts) pins an explicit host, and a 2-part `host[:port]/name` does too
    # when the first part looks like a host. A default-registry ref is at most
    # `namespace/name`, so reject anything carrying a host component. (Audit
    # 2026-07-20: a single-label host `evilhost/ns/model` slipped the old
    # dotted-first-segment test — `evilhost` has no dot/colon but IS the host.)
    parts = n.split("/")
    if len(parts) >= 3:                          # host/namespace/name → explicit host
        return False
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0]):
        return False                            # host[:port]/name → explicit host
    return True


def _prune_pull_jobs(now: float) -> None:
    """Bound _PULL_JOBS: drop terminal (done/failed) jobs past their TTL and
    cap the dict, so pulling many distinct names can't grow it (and the status
    payload it serializes) without limit. Caller holds _PULL_LOCK."""
    for k in [k for k, v in _PULL_JOBS.items()
              if v.get("state") in ("done", "failed")
              and (now - float(v.get("ts", now))) > _PULL_JOB_TTL_S]:
        _PULL_JOBS.pop(k, None)
    if len(_PULL_JOBS) > _PULL_JOBS_MAX:          # evict oldest non-active first
        for k, _v in sorted(_PULL_JOBS.items(), key=lambda kv: kv[1].get("ts", 0)):
            if len(_PULL_JOBS) <= _PULL_JOBS_MAX:
                break
            if _PULL_JOBS.get(k, {}).get("state") != "pulling":
                _PULL_JOBS.pop(k, None)


def _pull_model_async(brain: Brain, name: str) -> dict:
    """Start (or return the in-flight) background pull for `name`. Returns the
    job dict immediately — never blocks on the download. Posture-gated (no pull
    while Incognito/LAN-only, matching the store endpoints) and host-validated
    (the name can't repoint the pull at a non-default registry)."""
    name = (name or "").strip()
    if not name:
        return {"error": "no model name"}
    if not _model_name_ok(name):
        return {"error": "that model name isn't allowed — it points at a "
                         "non-default registry host"}
    if brain.incognito_now():
        return {"error": "pulling a model needs the network — you're in "
                         "Incognito or LAN-only right now"}
    now = time.time()
    with _PULL_LOCK:
        _prune_pull_jobs(now)
        cur = _PULL_JOBS.get(name)
        if cur and cur.get("state") == "pulling":
            return dict(cur)             # already pulling this name — don't start a second
        # Global in-flight cap: a caller firing many distinct names would spawn
        # an unbounded number of daemon threads and "pulling" dict entries the
        # cap-eviction can't drop (audit 2026-07-20). Refuse past the ceiling.
        if sum(1 for v in _PULL_JOBS.values()
               if v.get("state") == "pulling") >= _PULL_MAX_INFLIGHT:
            return {"error": "too many downloads at once — let a model finish first"}
        job = {"state": "pulling", "percent": 0, "detail": "starting…", "ts": now}
        _PULL_JOBS[name] = job

    def prog(pct, detail):
        if pct is not None:
            job["percent"] = pct
        if detail:
            job["detail"] = detail
        job["ts"] = time.time()

    def work():
        from .backends import pull_model_stream
        res = pull_model_stream(brain.config, name, on_progress=prog)
        ok = bool(res.get("ok"))
        job["state"] = "done" if ok else "failed"
        job["detail"] = "pulled" if ok else (res.get("status") or "failed")[:200]
        if ok:
            job["percent"] = 100
        job["ts"] = time.time()
        brain.activity.add("config", f"Model {name} pull "
                           + ("finished" if ok else "failed"))

    threading.Thread(target=work, daemon=True).start()
    brain.activity.add("config", f"Model {name} pull started")
    return dict(job)


def make_brain_server(brain: Brain, host: str = "127.0.0.1",
                      port: int = 7777, *,
                      tls_port: "Optional[int]" = None) -> ThreadingHTTPServer:
    # the token is read live in _authed (via authorize) so rotation applies;
    # nothing here needs to close over it. tls_port is advertisement only —
    # it tells /dreamlayer/live/link that a sibling https listener exists
    # (started by __main__ --tls) so the panel can hand out the secure link
    # a phone browser needs before it may open its camera.

    # Brute-force lockout on the token endpoint: without it a LAN attacker could
    # grind the Brain token unthrottled (audit 2026-07-14 — the limiter existed
    # but was never wired). Keyed by client IP, off-box attempts only (loopback
    # is the local dev/panel path); a burst of wrong tokens locks that IP out.
    from ...pairing_ratelimit import LockoutLimiter
    # ONE limiter per Brain, shared across listeners. make_brain_server is called
    # a second time for the TLS sibling (tls.start_tls_sibling); without sharing,
    # each port would get its own counter — a LAN attacker grinding the token
    # would get 2× the attempts and a lockout on one port wouldn't apply to the
    # other (audit 2026-07-20). Hang it off the Brain so both listeners agree.
    _shared = getattr(brain, "_shared_auth_limiter", None)
    if _shared is None:
        _shared = LockoutLimiter(max_attempts=10, window_s=60.0, lockout_s=300.0)
        try:
            setattr(brain, "_shared_auth_limiter", _shared)
        except Exception:                         # brain may forbid new attrs
            pass
    _auth_limiter: LockoutLimiter = _shared

    # The Live Lens short pairing code lives on the Brain too, shared across both
    # listeners for the same reason the limiter is (one active code, not one per
    # port). A phone that can't scan the QR types this code to redeem the token.
    _shared_vault = getattr(brain, "_shared_live_vault", None)
    if _shared_vault is None:
        _shared_vault = _LiveCodeVault()
        try:
            setattr(brain, "_shared_live_vault", _shared_vault)
        except Exception:
            pass
    _live_vault: _LiveCodeVault = _shared_vault

    class Handler(BaseHTTPRequestHandler):
        # Per-connection socket timeout: StreamRequestHandler.setup() applies
        # this via self.connection.settimeout(), so a slowloris client that opens
        # a socket and dribbles (or never finishes) its request can no longer pin
        # a worker thread forever — the read raises socket.timeout and the worker
        # is reclaimed (audit 2026-07-17, anti-slowloris). settimeout() bounds
        # BOTH recv and send, and a single 30 s bound is deliberately kept for
        # both. A more generous SEND window buys nothing real: the only large
        # responses (a /backup export, static assets) are _from_localhost()-only
        # and drain sub-second over loopback/LAN, while the genuinely remote
        # (phone) endpoints return small JSON — no real workload needs >30 s to
        # write. But a flat multi-minute send bound WOULD arm a slow-read DoS: a
        # client that triggers a large response and then STOPS READING pins a
        # worker thread blocked in sendall() — holding a semaphore slot — for the
        # whole window, so ~64 non-reading clients exhaust the pool for that long.
        # Bounding send at 30 s too caps that pin at 30 s (audit 2026-07-18,
        # reverted the send-timeout bump — slow-read pool-exhaustion DoS).
        #
        # But `timeout` is only a PER-RECV bound. The request line + headers are
        # read by the stdlib (readline + parse_request) BEFORE do_*/auth runs, so
        # a slowloris that dribbles one header byte just under the 30 s per-recv
        # window resets that clock forever — pinning a worker AND a bounded
        # semaphore slot entirely PRE-AUTH. A refute pass (2026-07-18) showed ~64
        # such connections lock the whole server out at near-zero bandwidth; the
        # bounded semaphore turns it into a clean deterministic lockout. The body
        # read already defends this with a MAX_REQUEST_BODY_SECONDS wall-clock
        # cap (_read_capped); handle_one_request below arms the same total-time
        # guard around the pre-dispatch header phase.
        timeout = SOCKET_TIMEOUT_S

        def handle_one_request(self):
            # Wall-clock bound on the request line + headers, disarmed the instant
            # parsing completes (before the handler's own — legitimately long —
            # work and the separately-bounded response write). A Timer fires from
            # another thread and shuts the socket down, unblocking the dribbling
            # recv so the worker (and its semaphore slot) is reclaimed.
            watchdog = threading.Timer(MAX_REQUEST_HEADER_SECONDS,
                                       self._abort_slow_request)
            watchdog.daemon = True
            self._header_watchdog = watchdog
            watchdog.start()
            try:
                super().handle_one_request()
            finally:
                watchdog.cancel()
                self._header_watchdog = None

        def parse_request(self):
            ok = super().parse_request()
            # Request line + headers are fully read now — disarm the header
            # watchdog so it can't fire during dispatch/handler work or the body
            # read (which carries its own MAX_REQUEST_BODY_SECONDS deadline).
            wd = getattr(self, "_header_watchdog", None)
            if wd is not None:
                wd.cancel()
                self._header_watchdog = None
            return ok

        def _abort_slow_request(self):
            # Runs on the Timer thread: force the blocked header read to return by
            # shutting the connection down. Best-effort — the socket may already be
            # torn down, or the request may have just completed.
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def log_message(self, *a):
            pass

        # -- helpers ----------------------------------------------------
        def _json(self, code, obj):
            # Deliberately NO CORS headers. The Brain is a local API that can hold
            # secrets (backup, token, memory) and its default token is empty, so
            # cross-origin *reads* must stay blocked — a drive-by page a wearer
            # visits connects from loopback and would otherwise pass the local
            # gates. One-click "Deploy to my Brain" works because the builder is
            # served *same-origin* at /dreamlayer/build; the phone uses native
            # networking (not subject to CORS). A cross-origin web tool cannot
            # reach this API, by design.
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            tok = brain.config.token        # read live so token rotation applies
            from_local = self._from_localhost()
            ip = self.client_address[0]
            # throttle off-box token grinding: while an IP is locked out, refuse
            # before even checking the token (a correct token during lockout is
            # still refused — that is the point).
            gated = bool(tok) and not from_local
            if gated and not _auth_limiter.allow(ip):
                return False
            ok = authorize(tok, self.headers.get(TOKEN_HEADER), from_local)
            if gated:
                if ok:
                    _auth_limiter.record_success(ip)
                else:
                    _auth_limiter.record_failure(ip)   # a wrong/absent token
            # a successful token-carrying request from off-box is the phone
            if ok and tok and not from_local:
                brain._last_phone_ts = time.time()
            return ok

        def _from_localhost(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1",
                                              "::ffff:127.0.0.1")

        def _is_tls(self) -> bool:
            """True when this request arrived on the TLS sibling listener (its
            socket is wrapped by ssl.wrap_socket in tls.start_tls_sibling), so a
            response body is encrypted on the wire. Used to keep the Live Lens
            token off a cleartext LAN hop."""
            import ssl
            return isinstance(self.connection, ssl.SSLSocket)

        def _host_allowed(self) -> bool:
            """DNS-rebinding defense (the read side of the same-origin policy the
            _same_origin_write CSRF guard enforces for writes).

            A page on an attacker domain whose DNS is rebound to 127.0.0.1 can
            fetch the Brain *as its own origin*: the socket peer is loopback, so
            _from_localhost() trusts it and _get_root() hands the panel token to
            that page's JavaScript — token theft with a single visit, no CORS to
            stop it (the browser thinks it's talking to the attacker's own site).
            A browser CANNOT forge the Host header, though, so a rebound request
            still carries the attacker's hostname. Refuse any Host whose name is
            not an IP literal, ``localhost``, an mDNS ``.local`` name, or this
            machine's own hostname — exactly the set the TLS cert SANs name and
            the panel (127.0.0.1/localhost) and phone (LAN IP or ``host.local``)
            actually dial. IP literals and ``.local`` names are not remotely
            rebindable, so this shuts the rebind path without touching the real
            loopback/LAN/mDNS callers. A request with NO Host (an HTTP/1.0 CLI or
            the phone's native networking) is not a browser and cannot be a
            rebind vector, so it is allowed."""
            import ipaddress
            raw = self.headers.get("Host")
            if not raw:
                return True                    # non-browser client; browsers always send Host
            host = raw.strip()
            if host.startswith("["):           # bracketed IPv6, optional :port
                hostname = host[1:host.index("]")] if "]" in host else host[1:]
            elif host.count(":") == 1:         # host:port (IPv4 / name)
                hostname = host.rsplit(":", 1)[0]
            else:                              # bare host or bare (unbracketed) IPv6
                hostname = host
            hostname = hostname.strip().lower()
            if not hostname:
                return False
            if hostname == "localhost" or hostname.endswith(".local"):
                return True
            try:
                ipaddress.ip_address(hostname)
                return True                    # any IP literal — never DNS-rebindable
            except ValueError:
                pass
            try:
                if hostname == (socket.gethostname() or "").strip().lower():
                    return True
            except OSError:
                pass
            return False

        @staticmethod
        def _own_names() -> set:
            """Every name this machine answers to, WITHOUT touching the resolver.

            This used to call socket.getfqdn(), which can do a reverse lookup, and
            cached it behind a lock — but the lock was held across the resolve, so a
            slow or blackholed DNS server serialised every write behind one lookup
            (measured: 64 concurrent POSTs each took the full 3s, and a plain GET
            queued 7.1s behind a POST burst). gethostname() is a syscall against a
            local string and cannot block, so the cache and its failure mode are
            both gone."""
            names = {"localhost", "localhost.local"}
            try:
                n = (socket.gethostname() or "").strip().lower().rstrip(".")
            except OSError:
                return names
            if n:
                names.add(n)
                base = n.split(".")[0]
                if base:
                    names.update({base, base + ".local"})
                if not n.endswith(".local"):
                    names.add(n + ".local")
            return names

        def _write_host_ok(self) -> bool:
            """A stricter Host test than the rebind guard, applied to WRITES only.

            `_host_allowed` accepts ANY ``.local`` name, because an mDNS name is not
            remotely rebindable — fine for reads. But it means a LAN attacker running
            an mDNS responder for ``evil.local`` pointed at this Brain gets a Host
            AND an Origin that match each other, satisfying the CSRF guard: a page
            the wearer merely visits could then POST as a same-origin caller. So a
            write must additionally arrive at a name we ACTUALLY answer to — an IP
            literal, localhost, or this machine's own (m)DNS name. Reads are
            untouched, so nothing about phone reachability changes."""
            import ipaddress
            raw = self.headers.get("Host")
            if not raw:
                return True                    # non-browser client; no CSRF vector
            host = raw.strip()
            if host.startswith("["):
                hostname = host[1:host.index("]")] if "]" in host else host[1:]
            elif host.count(":") == 1:
                hostname = host.rsplit(":", 1)[0]
            else:
                hostname = host
            hostname = hostname.strip().lower().rstrip(".")
            if not hostname:
                return False
            try:
                ipaddress.ip_address(hostname)
                return True                    # an IP literal is not a claimed name
            except ValueError:
                pass
            if hostname in self._own_names():
                return True
            # A SINGLE-LABEL mDNS name. This is the concession that keeps the phone
            # working: requiring the write to arrive at gethostname()'s own label
            # broke every machine whose Bonjour name differs from it, which is
            # routine — mDNS collision renaming appends "-2", and macOS keeps a
            # LocalHostName separate from the hostname. The symptom was the worst
            # kind: the page loaded and then every action failed, with pairing
            # reporting "wrong or expired code" forever.
            #
            # It is still strictly tighter than the read guard, which takes ANY
            # `.local`: a multi-label name is refused, so `evil.vm.local`,
            # `127.0.0.1.evil.local` and `vm.local.evil.com` cannot slip through, and
            # neither can a non-mDNS name like `evil.example`. What remains is an
            # active mDNS rebind on the same LAN against a TOKENLESS Brain — a real
            # but much narrower attack than the one this closed, and one a paired
            # token defeats outright, since an attacker's page cannot read it.
            return hostname.endswith(".local") and hostname.count(".") == 1

        def _same_origin_write(self) -> bool:
            """CSRF guard for state-changing (POST) requests.

            A tokenless loopback Brain authorizes any local caller (authorize()
            trusts loopback), and the panel's own JSON adapters mean _body()
            parses a request body whatever its Content-Type is. That combination
            is CSRF-able: a page the wearer merely visits can fire a *simple*
            cross-origin POST (text/plain body, no CORS preflight) at
            http://127.0.0.1:<port>/dreamlayer/config and — without ever reading
            the response — repoint the PRIMARY answer tier
            (model=api + api_base_url) at an attacker endpoint, silently
            exfiltrating every later non-incognito query and letting the attacker
            forge the answers the wearer sees.

            Browsers attach an UNFORGEABLE Origin header to every cross-origin
            POST (even the simple one that skips preflight), so a mutating
            request whose Origin is present and does not match the Host it
            arrived on is a cross-site forgery — refuse it. Native callers (the
            phone's React-Native networking) and CLI tools send no Origin and are
            unaffected; the same-origin panel's Origin always matches its Host.
            This closes the write side of the same-origin policy the read side
            (no CORS headers on _json) already enforces."""
            origin = self.headers.get("Origin")
            if not origin:
                return True             # native app / CLI — no browser origin
            try:
                origin_host = urllib.parse.urlsplit(origin).netloc.lower()
            except ValueError:
                return False
            host = (self.headers.get("Host") or "").lower()
            return bool(origin_host) and origin_host == host

        def _read_capped(self, max_bytes: int) -> bytes:
            """Read the request body, bounded by ``max_bytes`` AND a wall-clock
            deadline.

            An authed/loopback caller must not be able to drive unbounded memory
            or fill the disk, so the whole body is never allocated first: a
            Content-Length that declares more than the cap is refused *before a
            single byte is read* (→ 413), and an accepted body is read at most
            up to the cap (which the declared length is already ≤). A malformed
            (non-numeric) Content-Length is rejected as 400 rather than raising
            an unhandled ``int()`` ValueError deep in a handler as a 500
            (audit 2026-07-17).

            Two subtler defects a refute pass confirmed (audit 2026-07-17):

            * Slow-POST (finding 1): the per-recv socket timeout is an
              *inactivity* timeout — a client that dribbles one byte just under
              it resets that clock forever, pinning a worker + a semaphore slot.
              So the body is read in bounded slices (``read1`` → one recv each)
              against a MAX_REQUEST_BODY_SECONDS wall-clock deadline; exceeding
              it aborts the read (→ 408) regardless of per-recv activity. The
              per-recv timeout still bounds a single stalled recv; this ADDS a
              total-duration bound and leaves a steady upload that finishes
              within the cap untouched.

            * Undelimitable body (finding 2): Python's http.server does not decode
              chunked bodies, so a POST carrying a ``Transfer-Encoding`` header
              but no usable Content-Length would otherwise return b"" — silently
              accepted as empty (a 0-byte /upload artifact reported ok). A body we
              cannot length-delimit is rejected (→ 411) instead of forged into an
              empty one. A genuinely empty body (no Transfer-Encoding, absent or
              zero Content-Length) stays a valid empty body."""
            raw = self.headers.get("Content-Length")
            if not raw:
                # A body was indicated but can't be length-delimited (chunked /
                # any Transfer-Encoding with no Content-Length): reject rather
                # than forge an empty body. A plain bodyless POST (no
                # Transfer-Encoding) is still a valid empty body.
                if self.headers.get("Transfer-Encoding"):
                    raise _LengthRequired()
                return b""
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise _BadContentLength()
            if n <= 0:
                return b""
            if n > max_bytes:
                raise _RequestTooLarge(max_bytes)   # oversize — nothing read
            # n is already ≤ the cap here, so this allocates at most the cap.
            # Read in bounded slices against a wall-clock deadline: ``read1``
            # does at most one recv and returns whatever arrived, so the deadline
            # is re-checked after every recv instead of blocking inside a single
            # read(n) that a byte-dribbling slow-POST could stretch indefinitely
            # (each dribbled byte otherwise resets the per-recv socket timeout).
            deadline = time.monotonic() + MAX_REQUEST_BODY_SECONDS
            chunks = []
            remaining = n
            while remaining > 0:
                if time.monotonic() > deadline:
                    raise _RequestTimeout()
                chunk = self.rfile.read1(min(remaining, 65536))
                if not chunk:
                    break                            # client closed early — take what came
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)

        def _body(self) -> dict:
            raw = self._read_capped(MAX_JSON_BODY)
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else {}
            # RecursionError belongs here: json.loads recurses per nesting
            # level, so a deeply nested body raised straight out of the
            # handler and the connection died with no response at all.
            except (ValueError, UnicodeDecodeError, RecursionError):
                return {}
            # Every caller does _body().get(...); a non-object JSON body
            # (list/str/int/null) would AttributeError and, since do_POST only
            # catches the body-size errors, escape the handler as an unhandled
            # 500. The return type says dict — enforce it so one odd request
            # can't crash any POST handler (refute 2026-07-20).
            return parsed if isinstance(parsed, dict) else {}

        def _raw(self, max_bytes: int = MAX_JSON_BODY) -> bytes:
            return self._read_capped(max_bytes)

        # -- GET handlers (one named method per endpoint) ---------------
        # Public handlers run BEFORE the auth gate (static, same-origin assets
        # + the panel). Everything below the auth gate is token/localhost gated.
        def _get_root(self, path, qs):
            """The local control panel (token injected only for localhost).

            The token rides `self._write_host_ok()` as well as the peer address.
            The read-side Host allowlist accepts ANY `.local` name, so a LAN
            attacker running an mDNS responder for `evil.local` pointed at
            127.0.0.1 got this page, same-origin, with `const TOKEN="…"` in it —
            defeating the very mitigation `_write_host_ok`'s own docstring relies
            on ("an attacker's page cannot read it"). It could: the credential was
            on the READ path, which that guard did not cover. This is the panel,
            whose JS performs every write, so it is the higher-value page of the
            two. The page still serves at any allowed Host; only the credential
            is withheld."""
            token_ok = self._from_localhost() and self._write_host_ok()
            html = render_panel(brain.config.token if token_ok else "",
                                os_name=platform.system())
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", PANEL_CSP)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_builder(self, path, qs):
            """The no-code lens builder, served same-origin (INNOVATION 5,
            Category 1) so "Deploy to my Brain" needs no CORS and no pasted
            token. Same posture as the panel: the token is injected only for a
            localhost request. No CORS header on purpose — this HTML carries the
            injected Brain token (localhost only), so it must stay same-origin;
            it's loaded by navigation, never fetch(). Same `_write_host_ok()`
            requirement as `_get_root` -- a token must not ride an mDNS name an
            attacker chose."""
            html = _builder_page(brain.config.token
                                 if (self._from_localhost()
                                     and self._write_host_ok()) else "")
            if html is None:
                self._json(404, {"error": "builder assets not found"}); return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", BUILDER_CSP)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_builder_static(self, path, qs):
            """Any file under the builder's assets/ dir — theme CSS/JS, fonts,
            images, the lens engine — served same-origin so the <base>-anchored
            builder page renders fully. Public + read-only + traversal-safe."""
            res = _builder_static(path[len("/dreamlayer/build/assets/"):])
            if res is None:
                self._json(404, {"error": "not found"}); return
            body, ctype = res
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_live(self, path, qs):
            """The Live Lens — a phone browser becomes the glasses (live.py).
            PUBLIC like the builder, but stricter: this HTML embeds NO token in
            any case; the credential rides the URL fragment of the link/QR the
            panel hands out (see _get_live_link), so the page itself is inert."""
            import secrets
            from .live import render_live
            # Per-response nonce for the sole inline <style>/<script>, so a strict
            # CSP can permit THIS page's own inline code while blocking any
            # injected <script>/<img onerror> from executing — the token lives in
            # the page's sessionStorage, so an innerHTML regression here would be
            # token theft; the CSP is the backstop the page had none of (refute
            # 2026-07-18). default-src 'none' + connect-src 'self' also pins the
            # "zero external fetches" claim: no off-origin load can slip in.
            nonce = secrets.token_urlsafe(16)
            body = render_live(nonce).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # 'self' + 'wasm-unsafe-eval' let the SAME-ORIGIN on-device detector
            # load (its MediaPipe module + WASM), scoped to THIS page only (the
            # panel keeps the stricter nonce-only policy). 'wasm-unsafe-eval'
            # permits WASM compilation, NOT arbitrary JS eval; connect-src stays
            # 'self' so the model/WASM (and every look) still can't leave the
            # Brain. worker-src covers MediaPipe's internal worker. The inline
            # page code still requires the nonce.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; "
                f"script-src 'self' 'wasm-unsafe-eval' 'nonce-{nonce}'; "
                f"style-src 'nonce-{nonce}'; "
                "img-src 'self' data: blob:; media-src 'self' blob:; "
                "connect-src 'self'; worker-src 'self' blob:; "
                # 'none' has no frame-ancestors fallback under default-src, so name
                # it — a camera/token page must not be framable (clickjacking).
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            # belt-and-suspenders for the 'self' in script-src: never MIME-sniff a
            # same-origin response into an executable type.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_builder_asset(self, path, qs):
            """Same-origin JS assets for the served builder page — no CORS."""
            js = _builder_asset(path.rsplit("/", 1)[1])
            if js is None:
                self._json(404, {"error": "not found"}); return
            body = js.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_juno_asset(self, path, qs):
            """Juno's sprite kit for the panel: her UMD compositor script and
            the packed colour+matte clips it composites (mp4/webm) plus the
            still poster (webp). Same-origin, static, no token."""
            name = path[len("/dreamlayer/build/juno/"):]
            data = _juno_asset(name)
            if data is None:
                self._json(404, {"error": "not found"}); return
            body, ctype = data
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def _get_live_asset(self, path, qs):
            """The Live Lens on-device detector assets (MediaPipe loader/WASM +
            the .tflite model), served same-origin and public — they hold no
            secrets and the page fetches them before pairing. Same-origin is
            REQUIRED: the live page's CSP forbids any off-origin fetch, so the
            'no external fetches' / LAN-appliance promise holds even with the
            in-browser detector (the model + WASM never leave your Brain, and no
            camera frame ever leaves the phone for the on-device pass)."""
            name = path[len("/dreamlayer/live/assets/"):]
            data = _live_asset(name)
            if data is None:
                self._json(404, {"error": "not found"}); return
            body, ctype = data
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("X-Content-Type-Options", "nosniff")  # serve the declared type only
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
            self.end_headers()
            self.wfile.write(body)

        def _get_panel_asset(self, path, qs):
            """Bundled panel imagery (cinematic stills, HUD thumbnails) —
            static, read-only, no token needed so the page can paint."""
            name = path[len("/panel-assets/"):]
            if "/" in name or ".." in name:
                self._json(404, {"error": "not found"}); return
            fp = Path(__file__).resolve().parent / "assets" / name
            if not fp.is_file():
                self._json(404, {"error": "not found"}); return
            ctype = {"webp": "image/webp", "png": "image/png",
                     "jpg": "image/jpeg", "svg": "image/svg+xml",
                     "js": "text/javascript",
                     "mp3": "audio/mpeg",
                     "woff2": "font/woff2"}.get(
                         name.rsplit(".", 1)[-1].lower(),
                         "application/octet-stream")
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)

        def _get_config(self, path, qs):
            """Config snapshot + index stats + plan summary."""
            self._json(200, {"config": brain.config.public(),
                             "stats": brain.index.stats(),
                             "plan": brain.plan_summary()})

        def _get_brain_tiers(self, path, qs):
            """The Brain ceremony (3.1): tier ladder + measured latency."""
            self._json(200, _brain_view_payload(brain))

        def _get_status(self, path, qs):
            """Live Brain status: model, cloud posture, freshness, folders,
            and the per-source permission state (macOS TCC).

            `source_status()` is what tells a *denied* Mail/Calendar read apart
            from an empty one; carrying it here lets the panel say "grant
            access" instead of showing a silent empty."""
            from .macos_sources import source_status
            # `detail` is the raw exception text of the denial
            # (`f"{type(exc).__name__}: {exc}"`) and can echo a store path or
            # other on-box state; the on-box panel gets it, but an off-box
            # paired phone gets status+ts only, so nothing about this machine's
            # layout leaves the box. Same split as /dreamlayer/model/status.
            local = self._from_localhost()
            sources = {k: {"status": v.get("status"), "ts": v.get("ts", 0),
                           **({"detail": v.get("detail", "")} if local else {})}
                       for k, v in source_status().items()}
            ago = None
            if brain._last_phone_ts:
                ago = max(0, int(time.time() - brain._last_phone_ts))
            idx_ago = (int(time.time() - brain.last_index_ts)
                       if brain.last_index_ts else None)
            self._json(200, {
                "brain": True,
                "model": brain.config.model,
                "cloud": bool(brain.config.cloud_enabled) and not brain.config.lan_only,
                "cloud_ready": brain.config.cloud_ready(),
                "cloud_calls": brain.config.cloud_calls,
                # primary API brain, if the wearer plugged one in
                "api": brain.config.model == "api",
                "api_configured": brain.config.api_configured(),
                "api_local": brain.config.api_is_local(),
                "incognito": brain.incognito_now(),
                "quiet": brain.incognito_now() and not brain.config.lan_only,
                "phone_ago": ago,
                "index_ago": idx_ago,
                "missing": brain.missing_folders(),
                "email_docs": brain.email_docs,
                "stats": brain.index.stats(),
                "source_status": sources,
            })

        def _get_meetings(self, path, qs):
            """Your meetings — attendees, notes, and the action items pulled from
            them. Local; your own words never leave the Brain."""
            try:
                self._json(200, {"meetings": brain.meetings(50)})
            except Exception:                          # noqa: BLE001
                self._json(200, {"meetings": []})

        def _get_tts(self, path, qs):
            """Whether Juno can speak, and in which voice — so the panel/phone
            can show the toggle honestly. No synthesis here."""
            tts = _juno_tts(brain)
            self._json(200, {"ready": bool(tts and tts.ready),
                             "voice": (tts.voice_name if tts else "")})

        def _post_tts(self, path, qs):
            """Synthesize Juno's voice for a line of text and return the WAV.

            Audio goes the RIGHT direction: the (headless) Brain synthesizes
            locally — Kokoro/Piper on CPU, no cloud, no API credits — and hands the
            WAV to the client that actually has a speaker (the panel here, the phone
            or the glasses on the LAN). When TTS isn't set up (no engine or no
            voice model) it's a clean 204 so the caller just stays silent."""
            text = str((self._body() or {}).get("text", "") or "").strip()
            if not text:
                self._json(400, {"error": "no text"}); return
            tts = _juno_tts(brain)
            wav = tts.synthesize(text[:600]) if (tts and tts.ready) else None
            if not wav:
                self.send_response(204); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(wav)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(wav)

        def _get_token(self, path, qs):
            """The pairing token — handed only to the local panel."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            self._json(200, {"token": brain.config.token})

        def _get_backup(self, path, qs):
            """Full state export — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "backup is local-only"}); return
            self._json(200, brain.export_backup())

        def _get_health(self, path, qs):
            """Version, disk use, ollama probe, uptime, seam health."""
            try:
                du = sum(f.stat().st_size for f in brain.cfg_dir.rglob("*") if f.is_file())
            except OSError:
                du = 0
            oms = None
            if brain.config.model == "ollama":
                t0 = time.time()
                if probe_ollama(brain.config, timeout=3).get("reachable"):
                    oms = int((time.time() - t0) * 1000)
            self._json(200, {"version": _version(), "disk_kb": du // 1000,
                             "ollama_ms": oms,
                             "uptime_s": int(time.time() - brain._started_ts),
                             "seams": brain.health.snapshot()})

        def _get_capabilities(self, path, qs):
            """Optional-capability install/enable state."""
            self._json(200, _capability_payload(brain))

        def _get_juno(self, path, qs):
            """How Juno may be woken, and how she says she is listening.

            The Brain wakes nothing — the glasses hub does — so this route
            exists so the hub can PULL what the wearer chose on their phone. It
            is the same direction `ops_juno_attention.py` already reads
            `/dreamlayer/brief/latest` in, and it is why these two settings are
            persisted here rather than being invented as a Brain behaviour they
            are not.

            `interrupts` rides along because it is the same question asked of
            the other surface: what is this wearer willing to be interrupted by
            right now. The Brain enforces those itself at `push_event`; they are
            reported so the hub's own cards can agree with the Brain's.
            """
            cfg = brain.config
            self._json(200, {
                "wake_sources": list(getattr(cfg, "wake_sources", []) or []),
                "wake_feedback": list(getattr(cfg, "wake_feedback", []) or []),
                "interrupts": {
                    "proactive_cards": bool(getattr(cfg, "proactive_cards", True)),
                    "proactive_alerts": bool(getattr(cfg, "proactive_alerts", True)),
                    "focus_mode": bool(getattr(cfg, "focus_mode", False)),
                    "cue_event": bool(getattr(cfg, "cue_event", True)),
                    "cue_person": bool(getattr(cfg, "cue_person", True)),
                    "cue_place": bool(getattr(cfg, "cue_place", True)),
                    "fact_check": bool(getattr(cfg, "fact_check_enabled", False)),
                },
            })

        def _get_ear(self, path, qs):
            """Live state of the always-on ear (opt-in voice capture): whether
            it's enabled, whether the microphone is actually open, and how much
            it's heard. The panel polls this to show the truthful runtime state
            alongside the persisted Listening switch."""
            self._json(200, brain.ear_status())

        def _post_interpret(self, path, qs):
            """Turn the live cross-language interpreter on/off.

            `{"on": true, "target": "en"}` — `target` is the language Juno speaks
            back IN (the one you understand), not the one being spoken; SeamlessM4T
            detects the source itself. Rides the ear, so Listening must be on for
            anything to be heard; this reports `can_interpret: false` with a reason
            rather than pretending when the pack is absent."""
            b = self._body()
            self._json(200, brain.set_interpret(bool(b.get("on", True)),
                                                str(b.get("target", "") or "")))

        def _post_halo(self, path, qs):
            """Bring the glasses link up or down: `{"action": "connect"|
            "disconnect", "bridge": "emulator"|"real"}`.

            The one control the wearer needs, because everything else is
            automatic: once connected, the link is a subscriber on the same
            fan-out the Live Lens uses, so every card the phone shows the glass
            shows too — including cards added long after this route was written.
            """
            b = self._body()
            if str(b.get("action", "connect")) == "disconnect":
                self._json(200, brain.halo_disconnect())
                return
            self._json(200, brain.halo_connect(
                str(b.get("bridge", "emulator") or "emulator")))

        def _get_halo(self, path, qs):
            self._json(200, brain.halo_status())

        def _post_lucid(self, path, qs):
            """`{"q": "what did we say about the lease"}` → one answer.

            The router decides for itself whether the question wants the camera
            or the memory; the caller does not have to know, which is the whole
            point of the lens.
            """
            b = self._body()
            self._json(200, brain.lucid_query(str(b.get("q", "") or "")))

        def _post_dream_pose(self, path, qs):
            """A Dream Mode beat: `{"pose": {"pitch": -0.6}, "colors": [...],
            "amplitude": 0.3}`.

            The phone already samples `devicemotion` for the dream weather; this
            is the same stream, put to a second use. Deliberately cheap — it
            carries no captured content, only a head angle and the colours the
            wearer's own glasses are already showing.
            """
            b = self._body()
            self._json(200, brain.dream_pose(
                b.get("pose") if isinstance(b.get("pose"), dict) else {},
                b.get("colors"), float(b.get("amplitude") or 0.0),
                b.get("fft")))

        def _post_attention(self, path, qs):
            """What the wearer did with a card: `{"kind", "confidence",
            "dismissed"}`.

            The one signal that never used to cross back from the glass. Every
            card auto-expired on a `dismiss_ms` timer, so the Brain could not
            tell a card the wearer read from one they swatted away — and with
            no such record, any tuner has nothing to tune on.

            Deliberately cheap and unauthenticated beyond the usual do_POST
            guards: it carries no captured content, only a card kind and the
            confidence the card already displayed. A hostile caller can skew
            their OWN interruption bar, which is a setting they can also just
            change.
            """
            b = self._body()
            ok = brain.observe_card(str(b.get("kind", "") or ""),
                                    b.get("confidence"),
                                    bool(b.get("dismissed", False)))
            self._json(200, {"ok": True, "labelled": bool(ok),
                             **brain.attention_summary()})

        def _post_intro(self, path, qs):
            """Decide a staged introduction: `{"action": "confirm"|"dismiss"}`.

            The consent step. Hearing a name only ever OFFERS; this is the
            deliberate keep, driven by a tap on the card. Extra fields
            (company, role, notes, email) ride along to seed the dossier."""
            b = self._body()
            ih = brain.intro()
            if ih is None:
                self._json(200, {"ok": False, "reason": "unavailable"})
                return
            if str(b.get("action", "confirm")) == "dismiss":
                self._json(200, ih.dismiss())
                return
            extra = {k: b[k] for k in ("company", "role", "notes", "email")
                     if isinstance(b.get(k), str) and b[k].strip()}
            self._json(200, ih.confirm(**extra))

        def _get_intro(self, path, qs):
            """Name Capture state: the switches, whether an offer is live, and
            how many names have been offered and kept. Counts only — the name on
            a live offer is already on the wearer's own glass."""
            ih = brain.intro()
            self._json(200, ih.status() if ih is not None
                       else {"enabled": False, "reason": "unavailable"})

        def _post_truth(self, path, qs):
            """Turn "Read the room" on/off.

            `{"on": true}`. Rides the ear, so Listening must be on for anything to
            be heard. Reads DELIVERY — voice stress and word choice — and never
            claims to read a face: the micro-expression stages have no detector
            behind them and draw as empty slots, which the returned `channels`
            states outright rather than leaving to be inferred from the gauge."""
            b = self._body()
            self._json(200, brain.set_truth_lens(bool(b.get("on", True))))

        def _get_cloud(self, path, qs):
            """Cloud tier view (provider, posture, egress)."""
            self._json(200, _cloud_view_payload(brain))

        def _get_memory_file(self, path, qs):
            """The memory DB file descriptor for the panel."""
            self._json(200, _memory_file(brain))

        def _get_history(self, path, qs):
            """Newest-first activity feed (questions + actions)."""
            self._json(200, {"items": _activity_feed(brain, 40)})

        def _get_receipt(self, path, qs):
            """A verifiable privacy receipt: the tamper-evident activity records
            (seq/prev/sig), the Ed25519 public key to check them against, and
            this Brain's own verify() result — so a wearer or a bystander can
            independently confirm what the Brain did was not altered."""
            self._json(200, brain.activity.receipt())

        def _get_rehearsal(self, path, qs):
            """Names/facts worth resurfacing right now (FSRS rehearsal), most-
            overdue first — the Rehearsal surface's feed."""
            try:
                limit = int(qs.get("limit", ["5"])[0])
            except (ValueError, IndexError):
                limit = 5
            self._json(200, {"items": brain.rehearsals_due(limit),
                             "engine": brain._rehearsal().engine_name})

        def _post_rehearsal(self, path, qs):
            """Record a rehearsal outcome (rating: again|hard|good|easy) and
            schedule the next review."""
            b = self._body()
            item_id = str(b.get("id", "")).strip()
            if not item_id:
                self._json(400, {"error": "id required"}); return
            out = brain.review_rehearsal(item_id, str(b.get("rating", "good")))
            self._json(200, {"item": out})

        def _post_sealed_recall(self, path, qs):
            """Answer under a whole-process egress seal — on-device tiers only —
            and return the answer alongside the signed receipt attesting nothing
            left the device."""
            b = self._body()
            query = str(b.get("query", "")).strip()
            if not query:
                self._json(400, {"error": "query required"}); return
            self._json(200, brain.sealed_recall(query))

        def _get_calendar(self, path, qs):
            """Upcoming agenda events."""
            self._json(200, {"items": brain.calendar()})

        def _get_people(self, path, qs):
            """The People registry."""
            self._json(200, {"items": brain.people()})

        def _get_calendars(self, path, qs):
            """Available macOS calendars + current sync settings (for the picker)."""
            self._json(200, {"items": brain.list_calendars(),
                             "sync": brain.config.calendar_sync,
                             "selected": brain.config.calendar_names,
                             "last_sync": brain.last_calendar_sync})

        def _get_mail_accounts(self, path, qs):
            """Available Mail accounts + the current scope (for the picker)."""
            self._json(200, {"items": brain.list_mail_accounts(),
                             "enabled": brain.config.email_enabled,
                             "selected": brain.config.mail_accounts})

        def _get_vault_sync(self, path, qs):
            """This device's repertoire as a CRDT snapshot, base64 in JSON.

            The blob is the wearer's kept figments, so this is exactly as
            sensitive as `/backup` and carries the same LOCAL-ONLY rule: a token
            holder reaching in from off-box can read the Brain, but handing them
            the whole repertoire in one call is a different kind of access, and
            the design's premise is that no server ever holds these.

            base64 in JSON rather than raw bytes so it rides the same authenticated
            JSON path as everything else and a wearer can move it by any channel
            they like — AirDrop, a QR, a file on a stick."""
            if not self._from_localhost():
                self._json(403, {"error": "sync export is local-only"}); return
            import base64 as _b64
            blob = brain.sync_export()
            if not blob:
                self._json(200, {"ok": False, "reason": "no-crdt",
                                 "detail": "install the Sync pack (loro)",
                                 "blob": ""})
                return
            self._json(200, {"ok": True, "bytes": len(blob),
                             "peer": brain._sync_peer_name(),
                             "blob": _b64.b64encode(blob).decode("ascii")})

        def _post_vault_sync(self, path, qs):
            """Merge another of your devices' snapshots into this vault.

            `{"blob": "<base64>"}`. Order- and duplicate-independent by
            construction, so re-posting the same snapshot is a no-op rather than a
            problem — which is what lets this work over a channel with no
            protocol at all."""
            import base64 as _b64
            b = self._body()
            raw = b.get("blob") or ""
            try:
                blob = _b64.b64decode(raw, validate=True) if raw else b""
            except Exception:                        # noqa: BLE001 — peer input
                self._json(200, {"ok": False, "reason": "unreadable",
                                 "detail": "that snapshot was not valid base64"})
                return
            self._json(200, brain.sync_merge(blob))

        def _get_vault_sync_state(self, path, qs):
            """Whether sync can run here, and how much there is to sync."""
            self._json(200, brain.sync_state())

        def _get_voice(self, path, qs):
            """Runtime state of voice recall, plus the list of stored voices.

            Counts, names and capability — never a vector. A voiceprint is the
            biometric itself; the wearer needs to see and manage what is held,
            not have the templates handed back on every poll."""
            from .voice_live import CONSENT_TEXT
            vr = brain.voice_recall()
            if vr is None:
                self._json(200, {"available": False,
                                 "error": "voice recall unavailable"})
                return
            out = dict(vr.status())
            out["consent_text"] = CONSENT_TEXT
            out["people"] = vr.people()
            out["listening"] = bool(getattr(brain.config, "listen_enabled", False))
            self._json(200, out)

        def _post_voice_consent(self, path, qs):
            """Accept or revoke voice-recall consent. `{"accept": false}` also
            ERASES every stored voiceprint — withdrawing consent has to remove
            what was taken under it, not merely stop taking more."""
            vr = brain.voice_recall()
            if vr is None:
                self._json(200, {"ok": False, "error": "voice recall unavailable"})
                return
            b = self._body()
            if b.get("accept") is False:
                self._json(200, vr.revoke_consent())
                return
            self._json(200, vr.accept_consent(str(b.get("version", "") or "")))

        def _post_voice_name(self, path, qs):
            """Name an auto-enrolled voice. Body: {contact_id, name}.

            This is the moment `said_by` starts carrying something the lenses can
            match on — until a voice has a name, `their_word` has nothing to
            find."""
            vr = brain.voice_recall()
            if vr is None:
                self._json(200, {"ok": False, "error": "voice recall unavailable"})
                return
            b = self._body()
            self._json(200, vr.name_identity(str(b.get("contact_id", "")),
                                             str(b.get("name", ""))))

        def _post_voice_forget(self, path, qs):
            """Forget one stored voice, or all of them with `{"all": true}`."""
            vr = brain.voice_recall()
            if vr is None:
                self._json(200, {"ok": False, "error": "voice recall unavailable"})
                return
            b = self._body()
            if b.get("all"):
                self._json(200, {"ok": True, "erased": vr.forget_all()})
                return
            self._json(200, vr.forget(str(b.get("contact_id", ""))))

        def _get_dream(self, path, qs):
            """State of the neural dream painter: the model path, whether it
            resolves, and whether it has actually painted anything yet."""
            self._json(200, brain.dream_state())

        def _get_social_graph(self, path, qs):
            """The relationship graph built from your recorded meetings.

            `?a=…&b=…` asks what two people have in common and how you get from one
            to the other; with no names it returns the whole graph. Reports which
            engine answered, because "communities" means densely-connected clusters
            with networkx and only connected components without it."""
            a = (qs.get("a", [""])[0] or "").strip()
            b = (qs.get("b", [""])[0] or "").strip()
            if a and b:
                self._json(200, brain.social_mutual(a, b))
                return
            self._json(200, brain.social_graph_state())

        def _get_contacts(self, path, qs):
            """Contacts sync state + count pulled from Contacts.app."""
            self._json(200, {"sync": brain.config.contacts_sync,
                             "last_sync": brain.last_contacts_sync,
                             "count": len([p for p in brain.people()
                                           if p.get("source") == "contacts"])})

        def _get_reminders(self, path, qs):
            """Open reminders + lists + sync settings."""
            self._json(200, {"items": brain.reminders(),
                             "lists": brain.list_reminder_lists(),
                             "sync": brain.config.reminders_sync,
                             "selected": brain.config.reminder_lists,
                             "last_sync": brain.last_reminders_sync})

        def _get_rewind(self, path, qs):
            """The Rewind view."""
            self._json(200, brain.rewind())

        def _get_saga(self, path, qs):
            """The Saga badge snapshot."""
            self._json(200, brain.saga.snapshot())

        def _get_ember(self, path, qs):
            """The practice, cue + curve only — answers never leave the hub."""
            self._json(200, _ember_state(brain))

        def _get_plugins(self, path, qs):
            """Installed plugin state."""
            self._json(200, brain.plugins_state())

        def _get_discoveries(self, path, qs):
            """The hidden layer's memory: which secrets this Brain's wearer
            has found. Names only."""
            self._json(200, {"found": brain.discoveries()})

        def _post_discoveries(self, path, qs):
            """Record a discovery (validated against the known set)."""
            name = str(self._body().get("name", ""))
            if brain.add_discovery(name):
                self._json(200, {"found": brain.discoveries()})
            else:
                self._json(400, {"error": "unknown discovery"})

        def _post_plugins_store(self, path, qs):
            """The in-app plugin store catalogue (fetched from the pinned
            registry; posture-gated). It egresses AND mutates Brain state, so it
            is a POST and inherits do_POST's _same_origin_write() CSRF guard. As a
            GET it was forgeable by a no-Origin <img>/navigation — which
            _same_origin_write deliberately allows for native/CLI callers — so a
            page the wearer merely visited could force the no-egress Brain to
            phone home; making it a POST closes that (audit 2026-07-20)."""
            self._json(200, brain.store_catalogue())

        def _get_rc_repertoire(self, path, qs):
            """The Reality Compiler Repertoire: kept figments the phone lists."""
            self._json(200, brain.rc_repertoire())

        def _get_social_people(self, path, qs):
            """Your social memory: everyone met, notes, relations, debts."""
            self._json(200, brain.social_people_state())

        def _get_memories(self, path, qs):
            """The phone's Memories tab: places you saved, people met, favors
            owed, dated reminders — assembled from what the Brain holds."""
            self._json(200, brain.memories())

        def _get_profile(self, path, qs):
            """What the Juno has learned about you (mirrored from the hub)."""
            self._json(200, brain.profile)

        def _get_brief_latest(self, path, qs):
            """The last short brief."""
            self._json(200, brain.last_brief or {})

        def _get_brief_long_latest(self, path, qs):
            """The last long brief."""
            self._json(200, brain.last_long_brief or {})

        def _get_messages_recent(self, path, qs):
            """The live Messages/Mail feed the glasses read hands-free."""
            if not brain.config.email_enabled:
                self._json(200, {"items": [], "enabled": False}); return
            try:
                items = brain._messages_fn(brain.config, 20)
            except Exception:
                # best-effort live feed; an unreachable macOS source yields an
                # empty feed rather than a 500. Logged (was silent).
                log.warning("message source failed for /messages/recent",
                            exc_info=True)
                items = []
            if brain.config.summarize_emails:
                for it in items:
                    if it.get("channel") == "email":
                        it["summary"] = brain.summarize(it.get("text", ""))
            self._json(200, {"items": items, "enabled": True,
                             "summarize_emails": brain.config.summarize_emails})

        def _get_model_status(self, path, qs):
            """Probe the configured Ollama endpoint, plus any in-flight pull
            progress so the panel can render a live % and stop polling when a
            pull finishes."""
            out = probe_ollama(brain.config)
            # `detail` is Ollama's raw status and can echo the configured
            # endpoint (e.g. "could not reach Ollama: <url>"); the on-box panel
            # gets it, but an off-box paired phone gets state+percent only, so
            # the endpoint/topology never leaves the box (audit 2026-07-20).
            local = self._from_localhost()
            with _PULL_LOCK:
                out["pulls"] = {k: {"state": v.get("state"),
                                    "percent": v.get("percent", 0),
                                    **({"detail": v.get("detail", "")} if local else {})}
                                for k, v in _PULL_JOBS.items()}
            self._json(200, out)

        def _get_api_discover(self, path, qs):
            """One-click discovery: which local agent servers are running right
            now (Ollama, LM Studio, vLLM, …). Local-only — it port-probes this
            Mac, so a paired phone must not be able to trigger it."""
            if not self._from_localhost():
                self._json(403, {"error": "discovery is local-only"}); return
            from .backends import discover_local_agents
            self._json(200, {"agents": discover_local_agents()})

        def _get_browse(self, path, qs):
            """A server-side folder picker (the panel navigates the Mac's own
            filesystem) — local-only, like pairing."""
            if not self._from_localhost():
                self._json(403, {"error": "browse is local-only"}); return
            self._json(200, _browse_dir(qs.get("path", [""])[0]))

        def _get_pair(self, path, qs):
            """A pairing code for the phone — only handed to the local panel."""
            if not self._from_localhost():
                self._json(403, {"error": "pairing is local-only"}); return
            from ...pairing import PairingBundle, encode_pairing
            # the code must point the phone at an address it can reach on the
            # LAN — never the loopback/Host the local browser used.
            port = self.server.server_address[1]
            ip = lan_ip()
            if ip and ip != "127.0.0.1":
                url = f"http://{ip}:{port}"
            else:
                url = "http://" + (self.headers.get("Host") or f"127.0.0.1:{port}")
            bundle = PairingBundle(brain_url=url, token=brain.config.token)
            brain.activity.add("pair", "Generated a pairing code for the phone")
            brain.saga_record("pair")
            code = encode_pairing(bundle)
            from .qr import to_svg
            self._json(200, {"code": code, "url": url, "qr": to_svg(code)})

        def _get_downloads(self, path, qs):
            """The unified download queue — positions + live progress.
            Local-only like the writes: pip/pull error tails can carry local
            filesystem paths a paired phone has no business reading (F6)."""
            if not self._from_localhost():
                self._json(403, {"error": "downloads are managed on this Mac"})
                return
            self._json(200, {"queue": _dl_snapshot()})

        def _get_live_link(self, path, qs):
            """The Live Lens link + QR — only handed to the local panel, exactly
            like the pairing code (the link carries the token, so the link IS
            the credential). The token rides the URL FRAGMENT, which browsers
            never send over the wire, so it can't leak into logs. When --tls is
            on we hand out the https link — the one whose secure context lets a
            phone browser open its camera."""
            if not self._from_localhost():
                self._json(403, {"error": "the Live Lens link is local-only"}); return
            port = self.server.server_address[1]
            ip = lan_ip()
            host = ip if ip and ip != "127.0.0.1" else "127.0.0.1"
            frag = "#t=" + urllib.parse.quote(brain.config.token or "")
            http_url = f"http://{host}:{port}/dreamlayer/live"
            tls_port = getattr(self.server, "tls_port", None)
            https_url = (f"https://{host}:{tls_port}/dreamlayer/live"
                         if tls_port else "")
            base_url = https_url or http_url
            best = base_url + frag
            from .qr import to_svg
            brain.activity.add("look", "Generated a Live Lens link")
            # A short code the wearer can type on the live page if the phone
            # can't scan the QR — only meaningful when a token exists to hand out
            # (a tokenless Brain is loopback-only; a LAN phone can't reach it).
            code = _live_vault.issue(brain.config.token) if brain.config.token else ""
            # The QR encodes the SHORT code (#c=) instead of the 32-char token
            # (#t=) whenever a code exists: a sparser matrix (lower QR version →
            # bigger modules at the same render size) that a phone camera locks
            # onto off a glossy screen far more reliably — the #1 "the QR won't
            # scan" cause. The page redeems #c= for the token on load (same
            # paired end state); Copy-link still hands out the full token URL.
            qr_payload = (base_url + "#c=" + code) if (code and https_url) else best
            # ^ #c= ONLY on the https link: /live/redeem refuses non-TLS
            #   callers, so an http QR carrying a code could never pair
            #   (refute F1) — http keeps the fragment token, which never
            #   rides the wire at all.
            self._json(200, {
                "url": best, "http_url": http_url + frag,
                "https": bool(https_url),
                "code": code,
                # Can a PHONE redeem this code? `_post_live_redeem` refuses any
                # non-loopback caller without TLS, so on an http-only Brain the
                # code is real (loopback can redeem it) but useless to the phone
                # — and `live.py` maps that 403 to "wrong or expired code", so the
                # panel printed a code, the phone refused it, and the wearer was
                # told they had mistyped. The panel reads this flag and offers the
                # typed-code path only when it can actually work.
                "code_offbox": bool(https_url and code),
                "note": ("scan with the phone camera — accept the one-time "
                         "certificate warning (it is this Brain's own)"
                         if https_url else
                         "cameras need a secure page: restart the Brain with "
                         "--tls for the https link; asking works over http"),
                "qr": to_svg(qr_payload)})

        def _get_pair_sound(self, path, qs):
            """Pair by SOUND — the QR-free fallback. The Brain "sings" the same
            short, single-use pairing code as a near-ultrasonic ggwave chirp; a
            phone in earshot catches it and redeems via /dreamlayer/live/redeem,
            exactly as if the code were scanned or typed. Local-only (like the QR
            handout). Returns the code, whether sound is available, and — when it
            is — a base64 WAV the panel plays. Absent ggwave, `available` is False
            and the panel keeps the QR."""
            if not self._from_localhost():
                self._json(403, {"error": "pairing is local-only"}); return
            if not brain.config.token:
                self._json(200, {"available": False, "code": "",
                                 "reason": "no token — this Brain is loopback-only"})
                return
            from ...soundlink import default_soundlink, SOUND_TAG
            link = default_soundlink()
            # Reuse a live code if the panel already issued one (e.g. via
            # /live/link's QR) so the SUNG code is the SAME credential the QR
            # shows — the single-code vault holds one at a time, so issuing a
            # fresh one here would silently void the QR (audit 2026-07-21).
            code = _live_vault.current()
            if not code:
                if link is None:
                    # can't sing AND no code to reuse → don't burn one, so the
                    # QR/typed path this call falls back to stays valid
                    self._json(200, {
                        "available": False, "code": "", "wav_b64": "",
                        "note": "install the soundlink pack (ggwave) to pair by "
                                "sound; the QR and typed code still work"})
                    return
                code = _live_vault.issue(brain.config.token)
            wav_b64 = ""
            if link is not None:
                import base64
                # a short scheme tag so a listener knows this chirp is a DreamLayer
                # pairing code (not stray audio) — mirrors the QR's dreamlayer: prefix
                wav = link.encode_wav(SOUND_TAG + code)
                if wav:
                    wav_b64 = base64.b64encode(wav).decode("ascii")
            if wav_b64:
                brain.activity.add("pair", "Sang a pairing code over sound")
            self._json(200, {
                "available": bool(wav_b64),
                "code": code,
                "ultrasound": True,
                "wav_b64": wav_b64,
                "note": ("hold your phone near this Mac and tap Listen — the "
                         "code is sung as a near-ultrasonic chirp"
                         if wav_b64 else
                         "install the soundlink pack (ggwave) to pair by sound; "
                         "the QR and typed code still work")})

        def _get_live_events(self, path, qs):
            """The Live Lens event stream (Server-Sent Events): the Brain PUSHES
            ambient cards to the phone — a sound-safety tap, the morning brief, a
            memory nudge — the half of the HUD that isn't a reply to a look.

            Registered PUBLIC because EventSource can't set headers, so the token
            rides the query (?t=…); the server never logs it (log_message is a
            no-op) and the DNS-rebind guard already ran in do_GET. We
            self-authenticate here with the same throttle as the header path, then
            hold the connection open and drain the Brain's event bus. No captured
            content rides this channel — only cards the Brain chose to surface,
            and push_event veil-gates every non-safety push."""
            tok = brain.config.token
            from_local = self._from_localhost()
            presented = (qs.get("t", [""])[0] or "")
            ip = self.client_address[0]
            gated = bool(tok) and not from_local
            if gated and not _auth_limiter.allow(ip):
                self._json(429, {"error": "locked out"}); return
            ok = authorize(tok, presented, from_local)
            if gated:
                _auth_limiter.record_success(ip) if ok else _auth_limiter.record_failure(ip)
            if not ok:
                self._json(401, {"error": "unauthorised"}); return
            if gated:
                brain._last_phone_ts = time.time()        # an authed off-box stream is the phone
            q = brain.subscribe_events()
            if q is None:
                self._json(503, {"error": "too many event streams"}); return
            import json as _json
            import queue as _queue
            import socket as _socket
            try:                                          # detect a half-open peer (no FIN)
                self.connection.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
            except Exception:                             # noqa: BLE001
                pass
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")   # no proxy buffering
                self.end_headers()
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=15)
                    except _queue.Empty:
                        # heartbeat — AND re-check the token so rotating it (to
                        # revoke a lost phone) cuts an already-open stream within
                        # ~15 s, not only on its next reconnect (refute LOW-1).
                        if gated and not authorize(brain.config.token, presented, from_local):
                            break
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    body = _json.dumps(ev, separators=(",", ":"))
                    self.wfile.write(("data: " + body + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass                                          # the phone went away
            finally:
                brain.unsubscribe_events(q)

        # -- GET route table --------------------------------------------
        # exact-path public routes, resolved BEFORE the auth gate
        _GET_PUBLIC = {
            "/": _get_root,
            "/dreamlayer/live": _get_live,
            "/dreamlayer/live/events": _get_live_events,
            "/dreamlayer/build": _get_builder,
            "/dreamlayer/build/figment.js": _get_builder_asset,
            "/dreamlayer/build/qr.js": _get_builder_asset,
            "/dreamlayer/build/icons.js": _get_builder_asset,
        }
        # prefix/dynamic public routes (ordered fallback, still pre-auth)
        _GET_PUBLIC_PREFIX = [
            ("/dreamlayer/build/assets/", _get_builder_static),
            ("/dreamlayer/build/juno/", _get_juno_asset),
            ("/dreamlayer/live/assets/", _get_live_asset),
            ("/panel-assets/", _get_panel_asset),
        ]
        # exact-path routes, resolved AFTER the auth gate

        # -- the lens set (ai_brain/server/lens_hosts.py) -------------------
        # Provenance, Candor, Commitment Drift, Saga, Stasis, Premonition and
        # Inner Weather each ran on the Orchestrator and had no way to the
        # phone. These are that way. Each handler is a thin seam: the veil gate,
        # the lens call and the card push all live in `lens_hosts`, so a route
        # added later cannot forget the gate.

        def _lenses_or_503(self):
            """The lens set, or None with a 503 already sent. `lenses()` returns
            None only when the module itself failed to import, which is a broken
            install rather than a wearer-facing state — so it is a 503, not an
            empty answer a client would render as "no promises are slipping"."""
            ls = brain.lenses()
            if ls is None:
                self._json(503, {"ok": False, "error": "lens set unavailable"})
            return ls

        def _get_lenses(self, path, qs):
            """What the lens set can answer right now: how many statements are
            in the hot ring, how many thoughts are held, whether the veil is
            down. Reads nothing from disk."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.status())

        def _get_provenance(self, path, qs):
            """Trace a belief: ?claim=the+venue+is+booked. `null` means the
            veil is down — distinct from {"found": false}, which means the
            Brain has genuinely never heard it."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, {"result": ls.trace(qs.get("claim", [""])[0])})

        def _get_quests(self, path, qs):
            """Commitments as quests, plus the XP/level/streak tally.
            `/dreamlayer/saga` is a DIFFERENT thing (the ecosystem badge
            profile), which is why this is not called that."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.quests())

        def _get_drift(self, path, qs):
            """Every tracked commitment and how far it has slipped. Ticks the
            engine first, so a GET is also the clock — a phone that polls this
            keeps promises decaying even with nothing else running."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.drift_tick())

        def _get_stasis(self, path, qs):
            """The held thoughts, freshest first."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, {"frames": ls.frames()})

        def _post_location(self, path, qs):
            """The phone reports where it is: {lat, lon, accuracy_m}.

            Held in memory only — no row, no index entry, no file. Its whole
            job is to decide whether a private zone's shield is up and to give
            Waypath a bearing. Deliberately NOT veil-gated: a zone contributes
            to the shield, so gating this on the shield would latch it up
            forever the first time the wearer walked into one."""
            b = self._body()
            self._json(200, brain.note_location(
                b.get("lat"), b.get("lon"), b.get("accuracy_m", 0.0),
                heading_deg=b.get("heading_deg")))

        def _post_zones(self, path, qs):
            """Add or remove a private zone.

            `{"action":"add","name":"the flat","radius_m":150}` marks the
            CURRENT position; `{"action":"remove","name":"the flat"}` drops one.
            Add needs a position report first — nobody hand-enters a
            coordinate, which is why this exists rather than raw config writes."""
            b = self._body()
            self._json(200, brain.edit_zones(b.get("action", ""),
                                             b.get("name", ""),
                                             b.get("radius_m", 150.0)))

        def _get_zones(self, path, qs):
            """The zones, each with whether you are inside it right now."""
            self._json(200, {"zones": brain.zone_list(),
                             "max": brain.MAX_PRIVATE_ZONES,
                             "has_fix": bool(brain.here())})

        def _get_where(self, path, qs):
            """Current fix and zone state, for the phone's own UI. Coarse: the
            zone NAME and whether the shield is up, never the coordinate."""
            fix = brain.here()
            self._json(200, {"has_fix": bool(fix),
                             "age_s": (fix or {}).get("age_s"),
                             "zone": brain.private_zone_now(),
                             "veiled": bool(brain.incognito_now()),
                             "zones": len(getattr(brain.config, "private_zones", []) or [])})

        def _get_they_said(self, path, qs):
            """Did they tell you something different last time?
            `?person=Ana&claim=the+deposit+is+1400`.

            `person` is REQUIRED and never inferred — nothing in this product
            does speaker diarization, and guessing would put a false
            contradiction against a named individual."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.they_said(qs.get("person", [""])[0],
                                             qs.get("claim", [""])[0]))

        def _get_their_word(self, path, qs):
            """Everything this person told you, and what they promised:
            `?person=Ana`. Their promises are kept separate from yours —
            what you owe and what you are owed are opposite ledgers."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.their_word(qs.get("person", [""])[0]))

        def _get_owed(self, path, qs):
            """Open commitments, most-urgent first, and draws the top one.

            Distinct from `/dreamlayer/drift`: drift FIRES when a promise slips
            (an interruption), this ANSWERS "what do I owe?" (a question)."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.owed())

        def _get_resurface(self, path, qs):
            """A name or fact worth bringing back now, from the FSRS rehearsal
            store — a new surface over state the morning brief already reads."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.resurface())

        def _get_forget_last(self, path, qs):
            """What "forget that" WOULD erase, and the card that asks. Erases
            nothing — POST the returned id to confirm."""
            self._json(200, brain.forget_last_preview())

        def _post_forget_last(self, path, qs):
            """Confirm: erase the memory whose id the GET returned.

            The id echo IS the confirmation, and it is a race guard — the ear
            can land a new utterance between asking and confirming, and a
            confirm meaning "the newest" would then erase something unseen."""
            body = self._body()
            self._json(200, brain.forget_memory(body.get("id")))

        def _get_factcheck(self, path, qs):
            """World-check a claim: `?claim=the+wall+fell+in+1975`.

            GET rather than POST because it is a read — it stores nothing. It
            can reach the wearer's cloud tier, but only through `brain.ask`,
            which already refuses egress while incognito or with cloud off.
            `fired: false` covers an unverifiable claim, an unreachable tier
            and a cooling speaker alike — all "nothing worth interrupting for"."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, ls.fact_check(qs.get("claim", [""])[0]))

        def _get_scrub(self, path, qs):
            """Rewind your day: `?index=N` steps back through the hot ring,
            0 = most recent, and draws that node on the glass. `index` is
            clamped, not rejected — a phone holding a stale position after a
            retention sweep gets the oldest node rather than a 400."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            try:
                idx = int((qs.get("index", ["0"])[0] or "0").strip())
            except ValueError:
                idx = 0
            self._json(200, ls.scrub(idx))

        def _get_premonition(self, path, qs):
            """What usually happens next — only where the pattern is strong
            enough that the model will say so."""
            ls = self._lenses_or_503()
            if ls is not None:
                self._json(200, {"predictions": ls.predictions()})

        def _get_face(self, path, qs):
            """Runtime state of face recall: whether the wearer's switch is on,
            whether a model is actually installed, whether ambient is permitted
            here, and how many faces are enrolled. Counts and capability only —
            never a name, never a vector."""
            from .face_live import CONSENT_TEXT
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"enabled": False, "model": False,
                                 "ambient": False, "enrolled": 0})
                return
            # the exact words the acceptance is recorded against travel with the
            # state, so the panel can never show different terms than the ones
            # `accept_consent` versions
            self._json(200, {**fr.status(), "consent_text": CONSENT_TEXT})

        _GET_ROUTES = {
            "/dreamlayer/config": _get_config,
            "/dreamlayer/brain/tiers": _get_brain_tiers,
            "/dreamlayer/status": _get_status,
            "/dreamlayer/token": _get_token,
            "/dreamlayer/backup": _get_backup,
            "/dreamlayer/health": _get_health,
            "/dreamlayer/capabilities": _get_capabilities,
            "/dreamlayer/ear": _get_ear,
            "/dreamlayer/juno": _get_juno,
            "/dreamlayer/face": _get_face,
            "/dreamlayer/lenses": _get_lenses,
            "/dreamlayer/provenance": _get_provenance,
            "/dreamlayer/quests": _get_quests,
            "/dreamlayer/drift": _get_drift,
            "/dreamlayer/stasis": _get_stasis,
            "/dreamlayer/premonition": _get_premonition,
            "/dreamlayer/scrub": _get_scrub,
            "/dreamlayer/factcheck": _get_factcheck,
            "/dreamlayer/owed": _get_owed,
            "/dreamlayer/theysaid": _get_they_said,
            "/dreamlayer/where": _get_where,
            "/dreamlayer/zones": _get_zones,
            "/dreamlayer/their": _get_their_word,
            "/dreamlayer/resurface": _get_resurface,
            "/dreamlayer/forget/last": _get_forget_last,
            "/dreamlayer/cloud": _get_cloud,
            "/dreamlayer/memory/file": _get_memory_file,
            "/dreamlayer/history": _get_history,
            "/dreamlayer/receipt": _get_receipt,
            "/dreamlayer/rehearsal": _get_rehearsal,
            "/dreamlayer/calendar": _get_calendar,
            "/dreamlayer/people": _get_people,
            "/dreamlayer/intro": _get_intro,
            "/dreamlayer/halo": _get_halo,
            "/dreamlayer/calendars": _get_calendars,
            "/dreamlayer/mail/accounts": _get_mail_accounts,
            "/dreamlayer/contacts": _get_contacts,
            "/dreamlayer/social/graph": _get_social_graph,
            "/dreamlayer/dream": _get_dream,
            "/dreamlayer/voice": _get_voice,
            "/dreamlayer/vault/sync": _get_vault_sync,
            "/dreamlayer/vault/sync/state": _get_vault_sync_state,
            "/dreamlayer/reminders": _get_reminders,
            "/dreamlayer/rewind": _get_rewind,
            "/dreamlayer/saga": _get_saga,
            "/dreamlayer/ember": _get_ember,
            "/dreamlayer/plugins": _get_plugins,
            "/dreamlayer/discoveries": _get_discoveries,
            "/dreamlayer/rc/repertoire": _get_rc_repertoire,
            "/dreamlayer/social/people": _get_social_people,
            "/dreamlayer/memories": _get_memories,
            "/dreamlayer/profile": _get_profile,
            "/dreamlayer/brief/latest": _get_brief_latest,
            "/dreamlayer/brief/long/latest": _get_brief_long_latest,
            "/dreamlayer/messages/recent": _get_messages_recent,
            "/dreamlayer/model/status": _get_model_status,
            "/dreamlayer/tts": _get_tts,
            "/dreamlayer/meetings": _get_meetings,
            "/dreamlayer/api/discover": _get_api_discover,
            "/dreamlayer/browse": _get_browse,
            "/dreamlayer/pair": _get_pair,
            "/dreamlayer/pair/sound": _get_pair_sound,
            "/dreamlayer/live/link": _get_live_link,
            "/dreamlayer/downloads": _get_downloads,
        }

        # -- routing ----------------------------------------------------
        def do_GET(self):
            # DNS-rebind guard first — BEFORE the public routes, because _get_root
            # is a public route that injects the panel token for any loopback peer.
            if not self._host_allowed():
                self._json(421, {"error": "host not allowed"}); return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            # public routes resolve first — static assets + the panel are served
            # without a token (same gate ordering as before the route table)
            handler = self._GET_PUBLIC.get(path)
            if handler is None:
                for prefix, h in self._GET_PUBLIC_PREFIX:
                    if path.startswith(prefix):
                        handler = h; break
            if handler is not None:
                handler(self, path, qs); return
            # everything else is behind the token/localhost gate
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            handler = self._GET_ROUTES.get(path)
            if handler is None:
                self._json(404, {"error": "not found"}); return
            handler(self, path, qs)

        # -- POST handlers (one named method per endpoint) --------------
        # The auth gate runs first in do_POST, so every handler below is
        # token/localhost gated; a few add their own local-only sub-gate.
        def _post_memory_browse(self, path, qs):
            """Browse the memory DB — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "browsing memory is local-only"}); return
            self._json(200, _memory_browse(brain))

        def _post_memory_export(self, path, qs):
            """Export the memory DB to a destination — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "export is local-only"}); return
            self._json(200, _memory_export(brain, self._body().get("dest", "")))

        def _post_folders(self, path, qs):
            """Add or remove a watched folder, then persist + reindex."""
            b = self._body()
            p = b.get("path", "")
            if b.get("action") == "add":
                if brain.config.add_folder(p):
                    brain.activity.add("folder", f"Added folder {p}")
                    brain.saga_record("folder")
            elif b.get("action") == "remove":
                brain.config.remove_folder(p)
                brain.activity.add("folder", f"Removed folder {p}")
            brain.save(); brain.reindex()
            self._json(200, {"config": brain.config.public(),
                             "stats": brain.index.stats()})

        def _post_config(self, path, qs):
            """Apply a config patch, log notable posture changes, reindex."""
            body = self._body()
            # The EFFECTIVE posture, not the raw flag: `incognito_now()` is
            # lan_only OR a quiet-hours window, and a patch that clears lan_only
            # inside quiet hours does not lift the shield. Reading the flag
            # would announce a veil-down that did not happen.
            veiled_before = bool(brain.incognito_now())
            before = (brain.config.model, brain.config.cloud_enabled,
                      brain.config.network_mode, brain.config.email_enabled,
                      brain.config.captions_enabled)
            brain.apply_config(body)
            brain.reindex()
            if "model" in body and brain.config.model != before[0]:
                brain.activity.add("model", f"Model set to {brain.config.model}")
            if "cloud_enabled" in body and brain.config.cloud_enabled != before[1]:
                brain.activity.add("cloud", "Cloud enabled" if brain.config.cloud_enabled else "Cloud disabled")
            if "network_mode" in body and brain.config.network_mode != before[2]:
                brain.activity.add("privacy", "Incognito on" if brain.config.lan_only else "Incognito off")
            if "email_enabled" in body and brain.config.email_enabled != before[3]:
                brain.activity.add("config", "Email & iMessage " + ("on" if brain.config.email_enabled else "off"))
            # Captions put the room's speech on a screen, so the switch belongs
            # in the tamper-evident record alongside the other posture changes —
            # a wearer reading their receipt should see when it went on.
            if "captions_enabled" in body and brain.config.captions_enabled != before[4]:
                brain.activity.add("privacy", "Live captions "
                                   + ("on" if brain.config.captions_enabled else "off"))
            # …and say it on the glass, not only in the activity log. Only on a
            # TRANSITION: re-POSTing the same posture must not re-push a card,
            # and the panel saves the whole config on every switch.
            veiled_now = bool(brain.incognito_now())
            if veiled_now != veiled_before:
                brain.announce_posture(veiled_now)
            self._json(200, {"config": brain.config.public()})

        def _post_capabilities(self, path, qs):
            """One-click on/off for an INSTALLED optional capability — the
            persisted twin of DL_DISABLE_<KEY>. Never installs anything."""
            from ...capabilities import CAPABILITIES
            b = self._body()
            key = str(b.get("key", ""))
            if key not in {c.key for c in CAPABILITIES}:
                self._json(400, {"error": f"unknown capability: {key}"}); return
            off = set(brain.config.disabled_caps)
            (off.add if b.get("disabled") else off.discard)(key)
            brain.config.disabled_caps = sorted(off)
            brain.save()
            brain._sync_disabled_env()      # make the toggle actually reach the adapter
            brain.activity.add("config", f"Capability {key} "
                               + ("switched off" if b.get("disabled") else "switched on"))
            self._json(200, _capability_payload(brain))

        def _post_packs(self, path, qs):
            """One-click pack install (source installs only; allowlisted —
            the client names a curated pack, never a package). Local-only: it
            runs pip on the host, so like the model pull it is an on-box action,
            not something an off-box paired phone may trigger (audit 2026-07-20)."""
            if not self._from_localhost():
                self._json(403, {"error": "installing a pack is local-only"}); return
            b = self._body()
            job = _install_pack(brain, str(b.get("pack", "")))
            if "error" in job:
                self._json(400, job); return
            self._json(200, _capability_payload(brain))

        def _post_upload(self, path, qs):
            """Drag-drop a file into a watched folder, then reindex."""
            folder = (qs.get("folder", [""])[0])
            name = Path(qs.get("name", ["dropped.txt"])[0]).name
            ok = _write_upload(brain, folder, name, self._raw(MAX_UPLOAD_BODY))
            if ok:
                brain.activity.add("upload", f"Added {name}")
            brain.reindex()
            self._json(200 if ok else 400,
                       {"ok": ok, "stats": brain.index.stats()})

        def _post_brain_ask(self, path, qs):
            """Answer a question. A paired hub that is incognito / hub-cloud-off
            sends no_cloud; honor it over this Brain's own cloud config (the
            privacy posture is the wearer's, not the Mac's)."""
            b = self._body()
            query = b.get("query", "")
            # A meeting command holds the thread across the conversation: "start a
            # meeting with Sarah and Marcus", "note that we ship Friday", "end
            # the meeting" — captured (attendees + action items) rather than
            # answered.
            try:
                mc = brain.meeting_command(query)
            except Exception:                          # noqa: BLE001
                mc = None
            if mc:
                self._json(200, {"text": mc.get("say", ""), "tier": "local",
                                 "sources": [], "confidence": 1.0,
                                 "intent": mc.get("intent"), "meeting": mc.get("meeting")})
                return
            # An introduction is a CONSENT moment, not a question: "this is Sarah"
            # / "meet Sarah from Acme" enrolls Sarah into the People roster (so
            # the Social Lens can recognize her next time) and confirms — instead
            # of trying to answer it as a query.
            intro = None
            try:
                intro = brain.introduce(query)
            except Exception:                          # noqa: BLE001
                intro = None
            if intro:
                nm = intro["name"]
                note = f" — {intro['note']}" if intro.get("note") else ""
                self._json(200, {"text": f"Good to meet {nm}{note}. I'll remember.",
                                 "tier": "local", "sources": [], "confidence": 1.0,
                                 "intent": "introduce", "enrolled": intro})
                return
            # "who is Sarah" / "what do I know about Marcus" → the person dossier
            # card, built from YOUR records (roster + mirror + your own memory).
            # Roster-gated: it only fires for someone you introduced, so a general
            # question ("who is the mayor") falls through to normal recall below.
            try:
                dq = brain.dossier_query(query)
            except Exception:                          # noqa: BLE001
                dq = None
            if dq:
                # carry the provenance of any file passage the dossier used, rather
                # than reporting certainty with empty sources (audit 2026-07-23)
                self._json(200, {"text": dq.get("say", ""), "tier": "local",
                                 "sources": (dq.get("dossier") or {}).get("sources") or [],
                                 "confidence": 1.0,
                                 "intent": "dossier", "who": dq.get("who"),
                                 "card": dq.get("card"),
                                 "dossier": dq.get("dossier")})
                return
            ans = brain.ask(query, no_cloud=bool(b.get("no_cloud")))
            self._json(200, _answer_json(ans))

        def _post_live_look(self, path, qs):
            """One Live Lens look: a JPEG frame in, a budget-clamped HUD card
            out — the SAME unified pipeline as /brain/look (live.world_look).
            The frame is decoded in memory and never persisted; under the
            wearer's egress shield the look is local-only (classifier ladder,
            zero egress, no trace — test_live_lens pins it), and outside it the
            plugin providers see extracted fields, never pixels. The frame cap
            rides the same 413-before-read machinery as every body.

            ``?ambient=1`` marks a continuous-loop frame (the live page's passive
            "what am I looking at" cadence, several a minute): it runs the LOCAL
            classifier only — no remote vision, no plugins, and no activity-ledger
            trace — so the loop never floods the ledger or auto-egresses a frame.
            A deliberate tap (no ambient flag) escalates to the full world lens."""
            from . import live as live_mod
            ambient = qs.get("ambient", ["0"])[0] in ("1", "true")
            # ?lens=math|doc|depth|find|segment|sky|dream routes the frame
            # through a single frontier lens instead of object recognition;
            # lens_args ride the query (terms for find, lat/lon for sky).
            lens = (qs.get("lens", [""])[0] or "").strip().lower()
            # a chooser-tap carries the scene it was offered for → teach the arbiter
            scene = (qs.get("scene", [""])[0] or "").strip().lower()
            lens_args = None
            if lens:
                lens_args = {}
                if qs.get("terms"):
                    # Bounded the way the spoken path is: each term becomes a
                    # YOLO-World class that is CLIP text-encoded on a freshly
                    # built model, so 5000 of them from one query string was a
                    # free way to pin the CPU. Same caps as spoken_intent.
                    from .spoken_intent import MAX_TERMS
                    lens_args["terms"] = [
                        t.strip()[:48] for t in qs["terms"][0][:512].split(",")
                        if t.strip()][:MAX_TERMS]
                for k in ("lat", "lon"):
                    if qs.get(k):
                        try:
                            lens_args[k] = float(qs[k][0])
                        except ValueError:
                            pass
            # the phone's own on-device scene cues (coarse labels + a count +
            # person-present) ride the query so the arbiter decides from what the
            # PHONE can already see, not just image statistics (Tier 1)
            cues = live_mod.parse_cues(qs)
            data = self._raw(live_mod.MAX_FRAME_BYTES)
            self._json(200, live_mod.look(brain, data, ambient=ambient, cues=cues,
                                          lens=lens, lens_args=lens_args, scene=scene))

        def _post_live_hear(self, path, qs):
            """The phone is the live mic: a chunk of on-device Int16 PCM in, ear
            status out. The audio the PHONE hears (the room you're in) is streamed
            to the Brain, transcribed on-device (VAD → ASR ladder) and folded into
            memory — nothing is uploaded past the Brain. Consent-gated
            (remote_listen_enabled) and Veil-gated inside the ear: incognito /
            quiet-hours drops every utterance. ``?sr=<rate>`` is the phone's
            sample rate (resampled to 16 kHz); ``?stop=1`` ends the ear. The body
            rides the same 413-before-read cap as every other post."""
            from . import live as live_mod
            stop = qs.get("stop", ["0"])[0] in ("1", "true")
            try:
                sr = int(qs.get("sr", ["0"])[0])
            except (ValueError, TypeError):
                sr = 0
            body = b"" if stop else self._raw(live_mod.MAX_AUDIO_BYTES)
            self._json(200, live_mod.hear(brain, body, src_rate=sr, stop=stop))

        def _post_scholar(self, path, qs):
            """Scholar: read a question, a form, or dense text.
            `?mode=answer|form|explain`, `?q=` the spoken question (answer) or
            the purpose (form). Body is the JPEG, same cap and same
            never-persisted decode as a look.

            Scholar lived outside the Brain's import closure entirely — no code
            path could load it, so this route is the whole of its reachability
            from the phone."""
            from . import live as live_mod
            mode = (qs.get("mode", ["answer"])[0] or "answer").strip().lower()
            arg = (qs.get("q", [""])[0] or "").strip()
            data = self._raw(live_mod.MAX_FRAME_BYTES)
            self._json(200, live_mod.scholar(brain, data, mode=mode, arg=arg))

        def _post_live_dream_scene(self, path, qs):
            """One Dream-Mode scene beat: a JPEG frame in, the REAL
            SynesthesiaCard (six-word phrase + gestural sprite) and — when a
            saved place-memory matches — a WorldAnchorCard ghost out. The frame
            is decoded in memory and never persisted; it never leaves the Brain
            (world_lens._describe keeps it local), and under the wearer's veil
            both cards are None. The frame cap rides the same 413-before-read
            machinery as a look."""
            from . import live as live_mod
            from .live_dream import dream
            data = self._raw(live_mod.MAX_FRAME_BYTES)
            self._json(200, dream(brain).scene(data))

        def _post_live_redeem(self, path, qs):
            """Exchange the short Live Lens pairing code for the token.

            PUBLIC — resolved before the auth gate, because the phone redeeming
            has no token yet (that's the whole point). But it is the ONE
            unauthenticated write, so it is hardened at every turn:
              * do_POST already ran the DNS-rebind (_host_allowed) and CSRF
                (_same_origin_write) guards, so a rebound/cross-origin page can't
                reach here;
              * every attempt is brute-force locked out on the SHARED auth
                limiter keyed by client IP — a grinder locked out of the token
                endpoint is locked out here too, and vice-versa, so 8 digits
                behind a 10-tries/60 s → 5-min lockout is unbruteforceable inside
                the code's own 5-min life;
              * the vault gives one code, single-use, that a wrong guess never
                consumes.
            The token then rides the JSON response over the same channel the
            page will use it on (https when the camera path is live)."""
            # The token leaves in the RESPONSE BODY, so it must ride an encrypted
            # hop: only a loopback caller (not sniffable) or a TLS connection may
            # redeem. The live camera path needs https anyway (getUserMedia wants
            # a secure context), so this costs the real flow nothing and closes a
            # cleartext-token-over-LAN leak — the fragment path it supplements is
            # careful to keep the token off the wire (refute 2026-07-20).
            if not (self._from_localhost() or self._is_tls()):
                self._json(403, {"error": "redeem the code over the secure (https) link"}); return
            ip = self.client_address[0]
            if not _auth_limiter.allow(ip):
                self._json(429, {"error": "too many attempts — wait a minute"}); return
            code = str(self._body().get("code", "")).strip()
            tok = _live_vault.redeem(code)
            if not tok:
                _auth_limiter.record_failure(ip)
                self._json(401, {"error": "wrong or expired code"}); return
            _auth_limiter.record_success(ip)
            brain.activity.add("pair", "Live Lens paired by code")
            self._json(200, {"token": tok})

        def _post_plugins_install(self, path, qs):
            """Install a plugin from the posted descriptor."""
            self._json(200, brain.install_plugin(self._body()))

        def _post_plugins_store_install(self, path, qs):
            """One-click install a store plugin by name (pinned fetch → the same
            checksum + capability/sandbox gate as a pasted package). Local-only:
            installing code onto the host is an on-box action, matching the model
            pull's bar — an off-box paired phone must not install software
            (audit 2026-07-20)."""
            if not self._from_localhost():
                self._json(403, {"error": "installing is local-only"}); return
            self._json(200, brain.store_install(self._body().get("name", "")))

        def _post_conf_propose(self, path, qs):
            """Confluence (Live Lens): mint a bond offer — the three-word code
            the two humans speak to each other. Real BondManager underneath."""
            from .live_confluence import room
            b = self._body()
            self._json(200, room(brain).propose(str(b.get("sid", ""))))

        def _post_conf_accept(self, path, qs):
            from .live_confluence import room
            b = self._body()
            self._json(200, room(brain).accept(str(b.get("sid", "")),
                                               str(b.get("code", ""))))

        def _post_conf_dissolve(self, path, qs):
            from .live_confluence import room
            b = self._body()
            self._json(200, room(brain).dissolve(str(b.get("sid", ""))))

        def _post_conf_gift(self, path, qs):
            """Confluence Weather Gift: hand my current sky to the bonded peer as
            a 30 s wash on their glass. Real confluence.gift underneath — one
            authenticated palette snapshot, veil-silenced, nothing persisted."""
            from .live_confluence import room
            b = self._body()
            self._json(200, room(brain).gift(str(b.get("sid", "")),
                                             b.get("colors") or []))

        def _post_circle_form(self, path, qs):
            """GhostMode: start a circle and get the three-word code to say to
            the room. The real confluence.mesh.MeshManager underneath — group
            keys, HMAC'd packets, replay and stranger rejection — which nothing
            in the tree had ever constructed, so this headline was unreachable
            from every surface a wearer has."""
            from .live_circle import room
            b = self._body()
            self._json(200, room(brain).form(str(b.get("sid", ""))))

        def _post_circle_join(self, path, qs):
            from .live_circle import room
            b = self._body()
            self._json(200, room(brain).join(str(b.get("sid", "")),
                                             str(b.get("group", "")),
                                             str(b.get("code", ""))))

        def _post_circle_leave(self, path, qs):
            from .live_circle import room
            b = self._body()
            self._json(200, room(brain).leave(str(b.get("sid", ""))))

        def _post_circle_alias(self, path, qs):
            """Name a pulse locally — "that one is Maya". Never crosses: the
            mesh carries anonymous member ids and nothing else."""
            from .live_circle import room
            b = self._body()
            self._json(200, room(brain).alias(str(b.get("sid", "")),
                                              str(b.get("member", "")),
                                              str(b.get("name", ""))))

        def _post_circle_pulse(self, path, qs):
            """One beat into the circle: my feeling out, everyone's in, plus the
            differentially-private summary of how the room feels. The veil
            silences the sending half completely."""
            from .live_circle import room
            b = self._body()
            self._json(200, room(brain).pulse(
                str(b.get("sid", "")), str(b.get("kind", "weather")),
                b.get("body") or {}))

        def _post_live_weather(self, path, qs):
            """One dream-cadence weather beat: my state+palette in, MY sky's
            frames out (merged blend / split seam / solo) — the real
            EntangledSky per side, HMAC'd packets between them, nothing
            persisted anywhere."""
            from .live_confluence import room
            b = self._body()
            self._json(200, room(brain).weather(
                str(b.get("sid", "")), b.get("state", 0.0),
                b.get("colors") or [], resync=bool(b.get("resync"))))

        def _post_downloads_enqueue(self, path, qs):
            """Queue downloads (packs / models / plugins) — accepts one item
            or {"items": [...]} for Download All. Local-only, matching the
            pack/plugin/model install bar."""
            if not self._from_localhost():
                self._json(403, {"error": "downloads are managed on this Mac"})
                return
            b = self._body()
            items = b.get("items") if isinstance(b.get("items"), list) else [b]
            out = [_dl_enqueue(brain, str((i or {}).get("kind", "")),
                               str((i or {}).get("key", "")))
                   for i in items[:32]]
            self._json(200, {"ok": True, "queued": out,
                             "queue": _dl_snapshot()})

        def _post_downloads_cancel(self, path, qs):
            if not self._from_localhost():
                self._json(403, {"error": "downloads are managed on this Mac"})
                return
            try:
                item_id = int(self._body().get("id") or 0)
            except (TypeError, ValueError):
                item_id = 0
            self._json(200, _dl_cancel(item_id))

        def _post_plugins_remove(self, path, qs):
            """Remove an installed plugin by name."""
            self._json(200, brain.remove_plugin(self._body().get("name", "")))

        def _post_rc_rehearse(self, path, qs):
            """Rehearse a figment from a name + beats."""
            b = self._body()
            self._json(200, brain.rc_rehearse(b.get("name", ""),
                                              b.get("beats") or []))

        def _post_rc_keep(self, path, qs):
            """Keep a rehearsed figment in the repertoire."""
            self._json(200, brain.rc_keep(self._body().get("figment_id", "")))

        def _post_rc_deploy(self, path, qs):
            """Deploy a kept figment."""
            self._json(200, brain.rc_deploy(self._body().get("figment_id", "")))

        def _post_rc_revoke(self, path, qs):
            """Revoke a deployed figment."""
            self._json(200, brain.rc_revoke(self._body().get("figment_id", "")))

        def _post_rc_compose(self, path, qs):
            """"Ask Juno" — describe a lens in words, get a verified figment
            back into the builder (offline intent parser; not deployed)."""
            self._json(200, brain.rc_compose(self._body().get("prompt", "")))

        def _post_rc_feed(self, path, qs):
            """Stream host text (translation / camera label / memory) into the
            running lens's {slot} — the world-facing showcases' live wire."""
            b = self._body()
            self._json(200, brain.rc_feed(b.get("text", ""), b.get("source", "")))

        def _post_rc_emit(self, path, qs):
            """The lens emitted a tag; act on it and stream the result back
            (emit "ask" → Brain answers into the slot). no_cloud carries the
            wearer's session posture: an "ask" emit must honor Incognito/
            Cloud-off just like /brain/ask."""
            b = self._body()
            self._json(200, brain.rc_emit(b.get("tag", ""), b.get("text", ""),
                                          no_cloud=bool(b.get("no_cloud"))))

        def _post_rc_import(self, path, qs):
            """The no-code browser builder's "Deploy to my Brain"."""
            # ONE read. `self._body()` consumes the socket, so calling it twice
            # left the second `_read_capped` blocking on a drained connection for
            # the full SOCKET_TIMEOUT_S with no response at all -- 64 such bodies
            # (a few KB) held every worker and took the public panel offline. On a
            # pipelined connection the second read ate the NEXT request instead.
            body = self._body()
            self._json(200, brain.rc_import(body.get("figment") or body))

        def _post_event(self, path, qs):
            """The $6 physical-events kit (INNOVATION 1.6): a sensor out in the
            world POSTs a named signal to the figment on stage.
              /dreamlayer/event/ble/3  → "ble:3"   (numeric code channel)
              /dreamlayer/event/mail   → "mail"    (named)"""
            rest = path[len("/dreamlayer/event/"):].strip("/")
            parts = rest.split("/")
            if parts[0] == "ble" and len(parts) == 2 and parts[1].isdigit():
                name = f"ble:{parts[1]}"
            else:
                name = parts[0]
            self._json(200, brain.rc_event(name))

        def _post_social_people(self, path, qs):
            """The hub pushes its social-memory snapshot here."""
            self._json(200, brain.receive_people(self._body()))

        def _post_social_people_edit(self, path, qs):
            """A phone edit: add/remove a note, set relation, settle debts."""
            self._json(200, brain.edit_person(self._body()))

        def _post_memories_purge(self, path, qs):
            """"Erase all memories" from the phone's danger zone — honored here
            so a later refresh can't resurrect what was erased."""
            self._json(200, brain.purge_memories())

        def _post_ember_tend(self, path, qs):
            """The morning choice: keep an offer (capped) or let it go."""
            self._json(200, _ember_tend(brain, self._body()))

        def _post_ember_burn(self, path, qs):
            """The ceremony — explicit consent only, ANN-safe purge, cue-only
            tombstone (docs/EMBER.md)."""
            self._json(200, _ember_burn(brain, self._body()))

        def _post_brief(self, path, qs):
            """Assemble a brief; the last long brief is kept for the phone."""
            b = self._body()
            out = brain.brief(agenda=b.get("agenda"),
                              since=b.get("since", 0) or 0,
                              depth=b.get("depth", "short"),
                              commitments=b.get("commitments"),
                              memories=b.get("memories"))
            if out.get("depth") == "long":     # keep the last long brief for the phone
                brain.last_long_brief = {**out, "ts": time.time()}
            # "brief me now" can also reach the GLASS — the panel button used to
            # return JSON while any connected Live Lens got nothing. OPT-IN
            # (`push: true`) on purpose: brief() echoes the caller's own `agenda`
            # into the text, so a default-on push would make this route an
            # arbitrary-text-onto-every-glass primitive as a side effect of merely
            # fetching a brief (audit 2026-07-23). push_event stays veil-gated.
            if b.get("push") is True:
                # report the delivery count: a silently-swallowed push would
                # reproduce the very bug this fixes (200 OK, nothing on the glass)
                try:
                    from ...hud import cards
                    out["pushed"] = brain.push_event("brief", cards.morning_brief(
                        text=out.get("text", ""), bullets=out.get("bullets") or []))
                except Exception as exc:       # noqa: BLE001 — never fail the brief
                    out["pushed"] = 0
                    out["push_error"] = str(exc)[:120]
            self._json(200, out)

        def _post_live_intent(self, path, qs):
            """The phone heard you speak. Turn the words into a lens intent that
            the NEXT look obeys — the difference between guessing what you want
            and being told. Only the transcript crosses (the phone's own speech
            service produced it); it is length-capped, parsed, and dropped after
            20s. Veil-gated inside note_spoken_intent."""
            b = self._body() or {}
            said = str((b.get("text") if isinstance(b, dict) else "") or "")[:240]
            self._json(200, brain.note_spoken_intent(said))

        def _post_live_selftest(self, path, qs):
            """Prove the ambient push channel + card renderers work, without a real
            smoke alarm and without waiting for the brief hour. Authed like every
            other write; the card is stamped SELF-TEST and is never veil_ok, so it
            can't be used to spoof a safety alert (nor to pierce the shield)."""
            # Call _body() bare. It already returns {} for an absent/empty/non-JSON
            # body, and its exceptions (_RequestTooLarge/_BadContentLength/
            # _LengthRequired/_RequestTimeout) are what do_POST maps to 413/400/411/
            # 408 — catching them here answered 200 to a malformed request and left
            # an undrained chunked body that desynced the keep-alive connection
            # (audit 3, HIGH).
            b = self._body() or {}
            kind = str((b.get("kind") if isinstance(b, dict) else None)
                       or qs.get("kind", ["hark"])[0])
            out = brain.push_selftest(kind)
            self._json(200 if out.get("ok") else 400, out)

        def _post_replies(self, path, qs):
            """Suggest quick replies to a message."""
            b = self._body()
            self._json(200, {"replies": brain.suggest_replies(b.get("text", ""))})

        def _post_voice(self, path, qs):
            """Route a spoken/typed line: ask/recall answered here, the rest
            returned as a structured intent for the app to act on."""
            from ...orchestrator.voice import parse_intent
            vb = self._body()
            it = parse_intent(vb.get("text", ""))
            if it.kind in ("ask", "recall"):
                # honor the wearer's posture: a voice "ask" reaches the same
                # cloud sink as /brain/ask, so it must carry no_cloud too
                # (a paired hub that is incognito must not egress here).
                ans = brain.ask(it.args.get("query", ""),
                                no_cloud=bool(vb.get("no_cloud")))
                out = {"intent": it.kind, "query": it.args.get("query", ""),
                       "answer": ans.text if ans is not None else ""}
                # Juno's answer, drawn as well as returned. This is the seam and
                # not `/dreamlayer/brain/ask`, deliberately: the Live Lens page
                # posts to THAT route and already draws the answer itself, so
                # pushing there would draw it twice on the surface that asked.
                # Nothing that calls `/dreamlayer/voice` subscribes to the event
                # stream, so this is the one non-duplicating place to push from.
                #
                # ONE CARD PER WEARER UTTERANCE. `locate` already pushes its own
                # ObjectRecallCard (`brain_waypath.waypath_locate`), and several
                # other branches below carry a `say` string. If a generic
                # "push a JunoReplyCard whenever the response has `say`" is ever
                # added, it MUST exclude every branch that pushes its own card —
                # stash, locate, note_person, meet_person, debt, debt_settle,
                # reply, stasis_freeze, stasis_resume — or one question draws two
                # cards saying the same thing in different words.
                #
                # It pushes `ans.text`, never `vb["text"]`. Echoing the caller's
                # string would turn this route into the arbitrary-text-onto-every-
                # glass primitive the selftest push refuses to become.
                reply = (out["answer"] or "").strip()
                if reply:
                    try:
                        from ...hud import cards
                        out["pushed"] = brain.push_event(
                            "juno", cards.juno_reply(reply[:160], "answer"),
                            veil_ok=False)
                    except Exception:        # noqa: BLE001 — never cost the answer
                        out["pushed"] = 0
                self._json(200, out)
            elif it.kind == "brief":
                self._json(200, {"intent": "brief", **brain.brief()})
            elif it.kind in ("timer", "interval", "clock"):
                # native behaviors Juno builds & runs (docs/RC_V2): a
                # timer/interval compiles to a Figment on the stage; a
                # clock time-query just answers
                self._json(200, brain.rc_native(it.kind, it.args))
            elif it.kind == "timer_cancel":
                self._json(200, brain.rc_native_cancel())
            elif it.kind in ("note_person", "meet_person", "debt", "debt_settle"):
                # full parity with the hub: apply to the people mirror the
                # People screen reads, so typed voice works like spoken
                self._json(200, brain.voice_social(it.kind, it.args))
            elif it.kind == "stash":
                self._json(200, brain.waypath_stash(
                    it.args.get("subject", ""), it.args.get("place", "")))
            elif it.kind == "locate":
                self._json(200, brain.waypath_locate(it.args.get("subject", "")))
            elif it.kind == "missed":
                self._json(200, brain.missed(it.args.get("since", 0) or 0))
            elif it.kind == "reply":
                self._json(200, brain.voice_reply(
                    it.args.get("to", ""), it.args.get("text", "")))
            elif it.kind in ("stasis_freeze", "stasis_resume"):
                # `orchestrator/voice.py:342,345` has parsed "hold that thought"
                # and "where was I" into these two intents for as long as the
                # grammar has existed, and this branch did not exist — so both
                # fell through to the `else` below, returned 200 with a bare
                # {"intent": "stasis_freeze"}, and `phone-app/app/now.tsx:110`
                # rendered the literal string "(stasis_freeze)" on screen. A
                # wearer saying "hold that thought" got an acknowledgement and
                # nothing held. That is worse than an unimplemented feature: it
                # looks like it worked.
                ls = brain.lenses()
                if ls is None:
                    self._json(200, {"intent": it.kind, "ok": False,
                                     "reason": "lens set unavailable"})
                    return
                r = (ls.freeze(it.args.get("note", ""))
                     if it.kind == "stasis_freeze" else ls.resume())
                # `None` is the veil, and it must not read as failure-to-parse:
                # under the shield the Brain holds nothing and says so.
                self._json(200, {"intent": it.kind,
                                 **(r or {"ok": False, "reason": "veiled"})})
            else:
                self._json(200, {"intent": it.kind, **it.args})

        def _post_calendar(self, path, qs):
            """Add or remove an agenda event ({title, ts, place[, remove]})."""
            b = self._body()
            if b.get("remove"):
                items = brain.remove_event(b.get("title", ""), b.get("ts"))
            else:
                items = brain.add_event(b.get("title", ""),
                                        b.get("ts", 0) or 0, b.get("place", ""))
            self._json(200, {"items": items})

        def _post_calendar_sync(self, path, qs):
            """Pull macOS Calendar.app into the agenda now."""
            self._json(200, brain.sync_calendar())

        def _post_contacts_sync(self, path, qs):
            """Pull macOS Contacts.app into the People registry now."""
            self._json(200, brain.sync_contacts())

        def _post_reminders_sync(self, path, qs):
            """Pull open Reminders.app to-dos now."""
            self._json(200, brain.sync_reminders())

        def _post_saga_record(self, path, qs):
            """The hub / phone reports an ecosystem event it drove (e.g. a voice
            wake, a dossier, focus, rewind) so its badge can unlock."""
            ev = self._body().get("event", "")
            self._json(200, {"unlocked": brain.saga_record(ev) if ev else [],
                             "saga": brain.saga.snapshot()})

        def _post_profile(self, path, qs):
            """The glasses hub pushes its Juno profile snapshot so the phone can
            read it (the hub->Brain bridge). Mirror-only."""
            self._json(200, brain.set_profile(self._body()))

        def _post_model_pull(self, path, qs):
            """Start a one-click Ollama pull — local-only. Returns immediately
            with the job (state=pulling); the panel polls /model/status for the
            live %. A multi-GB pull no longer blocks the request until it
            finishes (which timed the browser out with no progress)."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            self._json(200, _pull_model_async(brain, self._body().get("model", "")))

        def _post_report(self, path, qs):
            """Assemble an in-app bug report (the wearer's words + sanitized,
            PII-free diagnostics) and a prefilled GitHub-issue link. Local-only
            and nothing is sent automatically — the panel shows the text and the
            wearer chooses to open the issue or copy it."""
            if not self._from_localhost():
                self._json(403, {"error": "reporting is local-only"}); return
            b = self._body()
            self._json(200, _build_bug_report(
                brain, b.get("summary", ""), b.get("detail", ""),
                bool(b.get("include_diag", True))))

        def _post_people(self, path, qs):
            """Introduce/update or remove a person ({name, note, tags[, remove]})."""
            b = self._body()
            if b.get("remove"):
                items = brain.remove_person(b.get("name", ""))
            else:
                items = brain.add_person(b.get("name", ""), b.get("note", ""),
                                         b.get("tags"))
            self._json(200, {"items": items})

        def _post_brain_explain(self, path, qs):
            """Explain a label / image at the requested depth."""
            b = self._body()
            ans = brain.explain(b.get("label", ""), b.get("image"),
                                b.get("want", "quick"))
            self._json(200, _answer_json(ans))

        def _post_brain_look(self, path, qs):
            """Look at a photo → a World-lens panel — the on-glass experience run
            in the Brain so a phone photo stands in for the glasses.

            Body: {image? (base64), label?, attrs?, lens? ("object"|"taste"),
            facet?, confidence?, budget?}. The image mode rides live.world_look —
            THE unified pipeline shared with the browser's Live Lens — so both
            surfaces are one thing: full plugin panel outside the egress shield,
            an honest local-only look inside it, and the same budget-clamped
            glass `lines` from the one formatter. The `label`/taste modes
            exercise plugin providers directly and stay veiled under the shield.
            Returns {ok, panel|card, lines?} or an honest {ok:false, reason}."""
            from ...object_lens.schema import ObjectSighting
            from ...object_lens.vision_recognizer import b64_to_frame
            from . import live as live_mod
            b = self._body()
            lens = str(b.get("lens", "object") or "object")
            facet = b.get("facet") or None
            label = str(b.get("label", "") or "").strip()
            if lens == "object" and not label and not facet:
                out = live_mod.world_look(brain, b64_to_frame(b.get("image")))
                out["lens"] = "object"
                self._json(200, out)
                return
            wl = brain.world_lens()
            if wl is None:
                self._json(200, {"ok": False, "reason": "vision lens unavailable"})
                return
            if wl.veiled():
                self._json(200, {"ok": False, "veiled": True,
                                 "reason": "Incognito — Juno isn't looking."})
                return
            if lens == "taste":
                ranking = wl.taste(b64_to_frame(b.get("image")),
                                   budget=b.get("budget"))
                if ranking is None or ranking.unavailable:
                    self._json(200, {"ok": False,
                                     "reason": "couldn't read a shelf here"})
                    return
                from ...hud import cards
                self._json(200, {"ok": True, "lens": "taste",
                                 "card": cards.taste(ranking, unavailable=False)})
                return
            # object lens (Juno) — deterministic label mode / an explicit facet
            if label:
                attrs = b.get("attrs")
                try:
                    conf = float(b.get("confidence", 0.9))
                except (TypeError, ValueError):
                    conf = 0.9
                sighting = ObjectSighting(
                    label=label, confidence=max(0.0, min(1.0, conf)),
                    attributes=attrs if isinstance(attrs, dict) else {})
                panel = wl.look_sighting(sighting, facet=facet)
            else:
                panel = wl.look(b64_to_frame(b.get("image")), facet=facet)
            if panel is not None:
                # world_look records image looks; the label and image+facet
                # branches must not under-report (refute 2026-07-21) — and
                # the veil is re-checked at write time (a veil dropped
                # mid-request must not land a ledger line)
                try:
                    if not brain.incognito_now():
                        seen = label or getattr(panel.sighting, "label", "")
                        brain.activity.add("look", f"Lens saw {seen}")
                except Exception:
                    pass
            if panel is None:
                self._json(200, {"ok": False, "reason": "couldn't make it out"})
                return
            card = panel.to_hud_card()
            self._json(200, {"ok": True, "lens": "object", "panel": card,
                             "lines": live_mod.panel_lines(card)})

        def _post_reindex(self, path, qs):
            """Re-index all watched folders."""
            stats = brain.reindex()
            brain.activity.add("index", "Re-indexed your folders")
            self._json(200, {"stats": stats, "missing": brain.missing_folders()})

        def _post_token_rotate(self, path, qs):
            """Rotate the pairing token — local-only; devices must re-pair."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            import secrets
            # 128-bit, matching the launcher (__main__.py) — a rotated token must
            # not be weaker than the one it replaces (audit 2026-07-14: rotate
            # minted token_hex(8) = 64-bit vs the launcher's token_hex(16)).
            brain.config.token = secrets.token_hex(16)
            brain.save()
            brain.activity.add("privacy", "Rotated the pairing token — devices must re-pair")
            self._json(200, {"token": brain.config.token})

        def _post_clear(self, path, qs):
            """Clear history / activity / folders — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            what = self._body().get("what", "")
            if what in ("history", "all"): brain.history.clear()
            if what in ("activity", "all"): brain.activity.clear()
            if what in ("folders", "all"):
                brain.config.folders = []; brain.save(); brain.reindex()
            # don't re-seed the activity log we just cleared
            if what in ("history", "folders"):
                brain.activity.add("config", f"Cleared {what}")
            self._json(200, {"ok": True, "stats": brain.index.stats()})

        def _account_remote_test(self, provider, base, label) -> "dict | None":
            """A 'Test connection' probe still leaves the device when the
            endpoint is REMOTE — so it must obey the SAME rule as a real query:
            refused while incognito, and counted+logged as egress otherwise.
            Before this, the test path fired a fixed prompt PLUS the wearer's API
            key to a public host uncounted and even while incognito, directly
            contradicting the panel's promise ('counted and logged … silenced
            while you're incognito'). Locality is judged on the EFFECTIVE base
            (a blank base_url falls back to the provider preset, which is
            remote), so a blank-but-preset endpoint isn't under-counted. Returns
            a refusal dict to short-circuit, or None to proceed; a local/unset
            endpoint is not egress. (audit 2026-07-15, sibling-call-site of
            _ask_cloud / _ask_primary_api.)"""
            from .backends import is_local_endpoint, PROVIDER_PRESETS
            preset = PROVIDER_PRESETS.get(provider or "custom",
                                          PROVIDER_PRESETS["custom"])
            effective = (base or "").strip() or preset.get("base_url", "")
            if not effective or is_local_endpoint(effective):
                return None                     # on-device / unset: free
            if brain.incognito_now():
                return {"ok": False, "error":
                        "a remote endpoint isn't tested while you're incognito"}
            brain.bump_cloud_calls()
            brain.activity.add("cloud-egress", label)
            brain.save()
            return None

        def _post_cloud_test(self, path, qs):
            """Probe the configured cloud provider — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            refusal = self._account_remote_test(
                brain.config.cloud_provider, brain.config.cloud_base_url,
                "Tested the cloud endpoint")
            if refusal is not None:
                self._json(200, refusal); return
            from .backends import cloud_test
            self._json(200, cloud_test(brain.config))

        def _post_api_test(self, path, qs):
            """Probe the wearer's primary API brain (api_* config) — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            refusal = self._account_remote_test(
                brain.config.api_provider, brain.config.api_base_url,
                "Tested your API brain")
            if refusal is not None:
                self._json(200, refusal); return
            from .backends import api_test
            self._json(200, api_test(brain.config))

        def _post_restore(self, path, qs):
            """Restore full state from a backup — local-only."""
            if not self._from_localhost():
                self._json(403, {"error": "restore is local-only"}); return
            brain.import_backup(self._body())
            brain.activity.add("config", "Restored from a backup")
            self._json(200, {"ok": True, "config": brain.config.public()})

        def _post_message_draft(self, path, qs):
            """Build an (unsent) send-script for a message draft."""
            from .macos_sources import MessageDraft, build_send_script
            b = self._body()
            d = MessageDraft(channel=b.get("channel", "imessage"),
                             to=b.get("to", ""), subject=b.get("subject", ""),
                             text=b.get("text", ""))
            self._json(200, {"script": build_send_script(d)})

        def _post_message_send(self, path, qs):
            """Actually send a message — local-only, explicit approval."""
            if not self._from_localhost():
                self._json(403, {"error": "local-only"}); return
            from .macos_sources import MessageDraft, send_message
            b = self._body()
            d = MessageDraft(channel=b.get("channel", "imessage"),
                             to=b.get("to", ""), subject=b.get("subject", ""),
                             text=b.get("text", ""))
            try:
                res = send_message(d, approved=bool(b.get("approved")))
                brain.activity.add("message", f"Sent a {d.channel} to {d.to}")
                self._json(200, res)
            except Exception as e:  # noqa: BLE001
                self._json(400, {"error": str(e)[:200]})

        # -- POST route table -------------------------------------------
        # exact-path routes (all behind the auth gate applied in do_POST)
        # -- recognising the people you introduced (face_live.py) ------------
        # Token-gated, not local-only, on purpose: the phone IS the enrolment
        # surface — you are looking at the person through it — exactly like the
        # look path. Every other gate (the wearer's switch, the Veil, a model
        # actually being installed) lives in FaceRecall and is checked there, so
        # these routes cannot become a way around them.

        def _post_face_enrol(self, path, qs):
            """Remember this face as this person. Body: {name, image (base64),
            contact_id?}. The ONLY route that stores a face template, and it
            stores one only for a person the wearer just named."""
            from ...object_lens.vision_recognizer import b64_to_frame
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"ok": False, "error": "face recall unavailable"})
                return
            b = self._body()
            self._json(200, fr.enrol(str(b.get("name", "")),
                                     b64_to_frame(b.get("image")),
                                     str(b.get("contact_id", "") or "")))

        def _post_face_identify(self, path, qs):
            """Is this one of the people I introduced? Body: {image (base64)}.

            Answers about ENROLLED contacts only and never about anyone else: a
            face matching nobody comes back {known: false} with a reason, and its
            template is discarded before this returns. The response deliberately
            carries no vector and no geometry — there is nothing in it about a
            person who did not consent."""
            from ...object_lens.vision_recognizer import b64_to_frame
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"known": False, "reason": "unavailable"})
                return
            self._json(200, fr.identify(b64_to_frame(self._body().get("image"))))

        def _post_face_consent(self, path, qs):
            """Record or withdraw the wearer's in-app consent.
            Body: {accept: true, version} or {accept: false}.

            GET /dreamlayer/face returns the version that must be accepted, and
            the text lives in `face_live.CONSENT_TEXT` so the panel renders the
            exact words the acceptance is recorded against."""
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"ok": False, "error": "face recall unavailable"})
                return
            b = self._body()
            if b.get("accept") is True:
                self._json(200, fr.accept_consent(str(b.get("version", ""))))
            else:
                self._json(200, fr.revoke_consent())

        def _post_face_name(self, path, qs):
            """Name an auto-enrolled identity. Body: {contact_id, name}.
            Promotes it out of the unnamed-TTL sweep."""
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"ok": False, "error": "face recall unavailable"})
                return
            b = self._body()
            self._json(200, fr.name_identity(str(b.get("contact_id", "")),
                                             str(b.get("name", ""))))

        # -- the lens set, write side --------------------------------------

        def _post_lens_observe(self, path, qs):
            """Put a statement the WEARER made into the ring. Body:
            {text[, person]}.

            `via="said"` here and only here: this route is the wearer typing or
            speaking on purpose, which is the one thing on the Brain that is
            genuinely firsthand. The room ear posts through `ingest_caption`
            with `via="heard"` instead, so Provenance can tell "you saw this"
            from "someone near you mentioned it"."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            b = self._body()
            self._json(200, ls.ingest_utterance(str(b.get("text", "")),
                                                via="said",
                                                person=str(b.get("person", ""))))

        def _post_candor_check(self, path, qs):
            """Does this contradict something already recorded? Body: {claim}.
            Pushes the ConsistencyCard to the glass when it fires."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"result": ls.candor_check(
                str(self._body().get("claim", "")))})

        def _post_drift_tend(self, path, qs):
            """Nudge a commitment — momentum, no XP. Body: {subject}."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"record": ls.tend(
                str(self._body().get("subject", "")))})

        def _post_quest_complete(self, path, qs):
            """Keep a promise: XP, streak, reward card, and the Saga badges
            (`quest_done`/`quest_rescue`/`streak`) that nothing used to emit.
            Body: {subject}. `reward: null` means no such open commitment."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"reward": ls.quest_complete(
                str(self._body().get("subject", "")))})

        def _post_quest_abandon(self, path, qs):
            """Let a commitment go: the streak breaks. Body: {subject}."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"ok": ls.quest_abandon(
                str(self._body().get("subject", "")))})

        def _post_stasis_freeze(self, path, qs):
            """Hold the current thought. Body: {[note]} — a note overrides the
            last thing heard as the line a resume hands back."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, ls.freeze(str(self._body().get("note", "")))
                       or {"ok": False, "reason": "veiled"})

        def _post_stasis_resume(self, path, qs):
            """Pick a held thought back up. Body: {[id]} — no id means the top
            of the stack, which is what "where was I" means out loud."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, ls.resume(self._body().get("id"))
                       or {"ok": False, "reason": "veiled"})

        def _post_stasis_pin(self, path, qs):
            """Pin a held thought so it never composts. Body: {id}."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"ok": ls.pin(self._body().get("id"))})

        def _post_inner_weather(self, path, qs):
            """One Inner Weather beat from the phone's sensors. Body:
            {imu_delta, imu_pose, extra}. Returns the frames the glass would
            render (churn geometry, storm events).

            NOT the same lens as `/dreamlayer/live/weather`, which is
            Confluence's shared EntangledSky between two people. This one is
            the wearer's own body: motion, micro-tremor and self-prosody fused
            into a single churn value."""
            ls = self._lenses_or_503()
            if ls is None:
                return
            self._json(200, {"frames": ls.weather_tick(self._body())})

        def _post_face_forget(self, path, qs):
            """Forget one enrolled face. Body: {contact_id}."""
            fr = brain.face_recall()
            if fr is None:
                self._json(200, {"ok": False, "error": "face recall unavailable"})
                return
            self._json(200, fr.forget(str(self._body().get("contact_id", ""))))

        _POST_ROUTES = {
            "/dreamlayer/memory/browse": _post_memory_browse,
            "/dreamlayer/memory/export": _post_memory_export,
            "/dreamlayer/plugins/store": _post_plugins_store,
            "/dreamlayer/folders": _post_folders,
            "/dreamlayer/config": _post_config,
            "/dreamlayer/capabilities": _post_capabilities,
            "/dreamlayer/packs": _post_packs,
            "/dreamlayer/report": _post_report,
            "/dreamlayer/upload": _post_upload,
            "/dreamlayer/brain/ask": _post_brain_ask,
            "/dreamlayer/plugins/install": _post_plugins_install,
            "/dreamlayer/downloads/enqueue": _post_downloads_enqueue,
            "/dreamlayer/live/confluence/propose": _post_conf_propose,
            "/dreamlayer/live/confluence/accept": _post_conf_accept,
            "/dreamlayer/live/confluence/dissolve": _post_conf_dissolve,
            "/dreamlayer/live/confluence/gift": _post_conf_gift,
            "/dreamlayer/live/circle/form": _post_circle_form,
            "/dreamlayer/live/circle/join": _post_circle_join,
            "/dreamlayer/live/circle/leave": _post_circle_leave,
            "/dreamlayer/live/circle/alias": _post_circle_alias,
            "/dreamlayer/live/circle/pulse": _post_circle_pulse,
            "/dreamlayer/live/weather": _post_live_weather,
            "/dreamlayer/downloads/cancel": _post_downloads_cancel,
            "/dreamlayer/discoveries": _post_discoveries,
            "/dreamlayer/plugins/store/install": _post_plugins_store_install,
            "/dreamlayer/plugins/remove": _post_plugins_remove,
            "/dreamlayer/rc/rehearse": _post_rc_rehearse,
            "/dreamlayer/rc/keep": _post_rc_keep,
            "/dreamlayer/rc/deploy": _post_rc_deploy,
            "/dreamlayer/rc/revoke": _post_rc_revoke,
            "/dreamlayer/rc/compose": _post_rc_compose,
            "/dreamlayer/rc/feed": _post_rc_feed,
            "/dreamlayer/rc/emit": _post_rc_emit,
            "/dreamlayer/rc/import": _post_rc_import,
            "/dreamlayer/face/enrol": _post_face_enrol,
            "/dreamlayer/face/identify": _post_face_identify,
            "/dreamlayer/face/forget": _post_face_forget,
            "/dreamlayer/face/consent": _post_face_consent,
            "/dreamlayer/face/name": _post_face_name,
            "/dreamlayer/voice/consent": _post_voice_consent,
            "/dreamlayer/voice/name": _post_voice_name,
            "/dreamlayer/voice/forget": _post_voice_forget,
            "/dreamlayer/lens/observe": _post_lens_observe,
            "/dreamlayer/candor/check": _post_candor_check,
            "/dreamlayer/drift/tend": _post_drift_tend,
            "/dreamlayer/quests/complete": _post_quest_complete,
            "/dreamlayer/quests/abandon": _post_quest_abandon,
            "/dreamlayer/stasis/freeze": _post_stasis_freeze,
            "/dreamlayer/stasis/resume": _post_stasis_resume,
            "/dreamlayer/stasis/pin": _post_stasis_pin,
            "/dreamlayer/weather": _post_inner_weather,
            "/dreamlayer/social/people": _post_social_people,
            "/dreamlayer/social/people/edit": _post_social_people_edit,
            "/dreamlayer/memories/purge": _post_memories_purge,
            "/dreamlayer/forget/last": _post_forget_last,
            "/dreamlayer/location": _post_location,
            "/dreamlayer/zones": _post_zones,
            "/dreamlayer/interpret": _post_interpret,
            "/dreamlayer/truth": _post_truth,
            "/dreamlayer/intro": _post_intro,
            "/dreamlayer/attention": _post_attention,
            "/dreamlayer/dream/pose": _post_dream_pose,
            "/dreamlayer/lucid": _post_lucid,
            "/dreamlayer/halo": _post_halo,
            "/dreamlayer/vault/sync": _post_vault_sync,
            "/dreamlayer/ember/tend": _post_ember_tend,
            "/dreamlayer/ember/burn": _post_ember_burn,
            "/dreamlayer/brief": _post_brief,
            "/dreamlayer/live/selftest": _post_live_selftest,
            "/dreamlayer/live/intent": _post_live_intent,
            "/dreamlayer/replies": _post_replies,
            "/dreamlayer/voice": _post_voice,
            "/dreamlayer/calendar": _post_calendar,
            "/dreamlayer/calendar/sync": _post_calendar_sync,
            "/dreamlayer/contacts/sync": _post_contacts_sync,
            "/dreamlayer/reminders/sync": _post_reminders_sync,
            "/dreamlayer/saga/record": _post_saga_record,
            "/dreamlayer/profile": _post_profile,
            "/dreamlayer/model/pull": _post_model_pull,
            "/dreamlayer/tts": _post_tts,
            "/dreamlayer/people": _post_people,
            "/dreamlayer/brain/explain": _post_brain_explain,
            "/dreamlayer/brain/look": _post_brain_look,
            "/dreamlayer/reindex": _post_reindex,
            "/dreamlayer/token/rotate": _post_token_rotate,
            "/dreamlayer/clear": _post_clear,
            "/dreamlayer/cloud/test": _post_cloud_test,
            "/dreamlayer/api/test": _post_api_test,
            "/dreamlayer/restore": _post_restore,
            "/dreamlayer/message/draft": _post_message_draft,
            "/dreamlayer/message/send": _post_message_send,
            "/dreamlayer/live/look": _post_live_look,
            "/dreamlayer/live/hear": _post_live_hear,
            "/dreamlayer/scholar": _post_scholar,
            "/dreamlayer/live/dream/scene": _post_live_dream_scene,
            "/dreamlayer/rehearsal/review": _post_rehearsal,
            "/dreamlayer/recall/sealed": _post_sealed_recall,
        }
        # prefix/dynamic routes (ordered fallback for non-exact paths)
        _POST_ROUTES_PREFIX = [
            ("/dreamlayer/event/", _post_event),
        ]
        # PUBLIC POSTs — resolved BEFORE the auth gate (the caller has no token
        # yet). Still behind do_POST's rebind + CSRF guards. The redeem handler
        # carries its own brute-force lockout; keep this set to that one route.
        _POST_PUBLIC = {
            "/dreamlayer/live/redeem": _post_live_redeem,
        }

        def do_POST(self):
            # DNS-rebind guard first (mirrors do_GET): a rebound page must not
            # reach a mutating handler even on a tokenless loopback Brain.
            if not self._host_allowed():
                self._json(421, {"error": "host not allowed"}); return
            parsed = urllib.parse.urlparse(self.path)
            path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
            # CSRF guard first: a forged cross-origin write must be refused even
            # when it would otherwise be authorized (tokenless loopback trusts
            # any local caller). Native/CLI callers carry no Origin and pass.
            if not self._write_host_ok():
                self._json(421, {"error": "host not allowed for writes"}); return
            if not self._same_origin_write():
                self._json(403, {"error": "cross-origin write refused"}); return
            # PUBLIC POSTs (only /live/redeem) resolve BEFORE the auth gate — the
            # caller has no token yet. They still passed the rebind + CSRF guards
            # above, and each carries its own throttle. Non-public routes fall
            # through the auth gate exactly as before.
            handler = self._POST_PUBLIC.get(path)
            if handler is None:
                if not self._authed():
                    self._json(401, {"error": "unauthorised"}); return
                handler = self._POST_ROUTES.get(path)
                if handler is None:
                    for prefix, h in self._POST_ROUTES_PREFIX:
                        if path.startswith(prefix):
                            handler = h; break
            if handler is None:
                self._json(404, {"error": "not found"}); return
            # The body is read lazily inside each handler (via _body/_raw), so
            # the size/format guards land here where the response can still be
            # chosen: an oversize body is a 413 and a malformed Content-Length a
            # 400 — never an unhandled 500 (audit 2026-07-17).
            try:
                handler(self, path, qs)
            except _RequestTooLarge as exc:
                self.close_connection = True   # don't drain the oversize body
                self._json(413, {"error": "request body too large",
                                 "limit": exc.limit})
            except _BadContentLength:
                self.close_connection = True
                self._json(400, {"error": "invalid Content-Length"})
            except _LengthRequired:
                # a body we can't length-delimit (chunked, no Content-Length):
                # demand a length instead of writing a phantom empty body.
                self.close_connection = True
                self._json(411, {"error": "Content-Length required"})
            except _RequestTimeout:
                # the body didn't fully arrive within the wall-clock deadline —
                # a byte-dribbling slow-POST; abort so the worker + slot free up.
                self.close_connection = True
                self._json(408, {"error": "request body read timed out"})
            except OSError:
                # A socket-level fault -- a slow-POST that hit the read deadline
                # as a bare TimeoutError, a peer that vanished, a broken pipe --
                # is NOT an application error and must keep the old behaviour:
                # close the connection. Writing a 500 into a dead socket just
                # raises again, and it would defeat the slowloris timeout.
                self.close_connection = True
                raise
            except Exception:                    # noqa: BLE001
                # The catch-all do_GET has had all along. Without it, anything
                # other than the four body faults above escaped to
                # socketserver.handle_error: a traceback on stderr, the
                # connection dropped, and ZERO bytes to the client. A JSON field
                # with the wrong TYPE was enough -- `{"query": 5}` to
                # /dreamlayer/brain/ask hit `.lower()` on an int -- across a
                # dozen handlers. A caller deserves a status code, and a
                # keep-alive connection must not die on a bad field.
                # Log the matched HANDLER, never the request path. The path is
                # caller-supplied — the prefix routes above match on a prefix
                # and carry an arbitrary tail (`/dreamlayer/event/<anything>`),
                # so writing it verbatim puts attacker text in the operator's
                # log (CodeQL py/log-injection). urlparse leaves %0A encoded and
                # the request line can't hold a bare CR/LF, so forged log LINES
                # aren't reachable today, but that's a property of two layers
                # below us, not of this call. The handler's name comes from our
                # own route table and identifies the endpoint just as well.
                #
                # Bound to a local first, and deliberately not called `*name`:
                # .semgrep/dreamlayer.yml's pii-in-log-message keys on the
                # interpolated expression's TEXT, so an inline
                # `getattr(handler, "__name__", …)` reads as a sensitive
                # identifier to it. The rule is right to be blunt about that
                # substring; the fix is to hand it a value whose name says what
                # this actually is.
                route = getattr(handler, "__name__", "?")
                log.exception("[brain] unhandled error in POST route %s", route)
                self._json(500, {"error": "internal"})

    class _BrainServer(ThreadingHTTPServer):
        # sibling https listener's port (set by the factory when __main__
        # started one with --tls) — advertised by /dreamlayer/live/link so the
        # panel can hand out the secure URL a phone camera requires.
        tls_port: "Optional[int]" = None

        # The stdlib default (allow_reuse_address = 1) is a POSIX convenience:
        # it lets a restart rebind through TIME_WAIT. On Windows SO_REUSEADDR
        # means something else entirely — "bind even if another socket is
        # actively LISTENING" — so two Brains could silently share :7777 with
        # undefined delivery. There a busy port must fail loudly
        # (WSAEADDRINUSE) instead; Windows needs no flag to rebind after a
        # clean close, so nothing is lost.
        allow_reuse_address = os.name != "nt"

        # Bounded concurrency: ThreadingHTTPServer spawns one thread per
        # connection unbounded, so a flood of sockets could exhaust the
        # process's threads (thread-exhaustion DoS). A BoundedSemaphore caps the
        # in-flight worker count — the accept loop blocks (backpressure) once the
        # ceiling is reached instead of spawning without limit, and each worker
        # releases its slot when it finishes (audit 2026-07-17). Sized well above
        # normal panel/phone load so healthy traffic never queues.
        _slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

        def process_request(self, request, client_address):
            # Runs in the serve_forever accept loop: acquiring here throttles new
            # connections when the pool is saturated rather than in the worker.
            self._slots.acquire()
            try:
                super().process_request(request, client_address)
            except BaseException:
                self._slots.release()   # thread never started — don't leak a slot
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._slots.release()

    server = _BrainServer((host, port), Handler)
    server.tls_port = tls_port          # advertised by /dreamlayer/live/link
    return server


def _write_upload(brain: Brain, folder: str, name: str, data: bytes) -> bool:
    # only into a folder the Brain already watches (no arbitrary writes)
    target = str(Path(folder).expanduser())
    if target not in brain.config.folders:
        return False
    # `name` is attacker-influenced. Path(target) / name silently ESCAPES the
    # watched folder when name is absolute (pathlib drops the left side:
    # Path("/w") / "/home/u/.bashrc" == Path("/home/u/.bashrc")) or contains
    # ".."/separators — an arbitrary-write-anywhere primitive. Force a bare
    # basename, then confirm the fully-resolved destination is genuinely inside
    # the watched folder (defeats a symlink planted at target/name too), and
    # never let it land on an auto-run / secret / Brain-state file even within a
    # watched dir — that is the RCE/persistence escalation (audit 2026-07-19).
    from .store import _is_write_denied
    raw = str(name)
    base = Path(raw).name
    # A legitimate upload name is ALWAYS a bare filename (the panel/phone send the
    # File object's basename). A name that isn't already its own basename —
    # absolute, or carrying "/", "\\", ".." or a trailing slash — is an attack or
    # a bug; refuse it outright rather than silently relocate it.
    if not base or base in (".", "..") or base != raw:
        return False
    try:
        troot = Path(target).resolve()
        dest = troot / base
        rdest = dest.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if rdest.parent != troot and troot not in rdest.parents:
        return False
    if _is_write_denied(str(rdest)):
        return False
    try:
        dest.write_bytes(data)
        return True
    except OSError:
        return False


def _clip_brief(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _version() -> str:
    try:
        import dreamlayer
        return getattr(dreamlayer, "__version__", "0.0.0")
    except ImportError:
        # the package should always import from within itself; fall back only
        # for that narrow case rather than masking any other error.
        return "0.0.0"


# --- in-app bug reporting ----------------------------------------------------
# A "Report a problem" flow inside the app: assemble the wearer's description
# plus a STRICTLY SANITIZED diagnostic summary (version, OS, capability counts,
# seam failure counts — NO folder paths, queries, URLs, keys, or any PII) and a
# prefilled GitHub-issue link. Nothing is sent automatically: the wearer reviews
# the assembled text and chooses to open the issue or copy it (audit 2026-07-19).
_REPORT_REPO = "LetsGetToWorkBro/dreamlayer"


def _report_diagnostics(brain: Brain) -> str:
    """A privacy-safe, PII-free diagnostic block for a bug report. Only coarse
    counts and product versions — never a path, query, endpoint, key, or the
    wearer's data."""
    import platform as _pf
    try:
        from ...capabilities import summary as _cap_summary
        caps = _cap_summary()
    except Exception:
        caps = {}
    try:
        files = int(brain.index.stats().get("files", 0))
    except Exception:
        files = 0
    up = int(time.time() - getattr(brain, "_started_ts", time.time()))
    uptime = f"{up // 3600}h" if up >= 3600 else f"{max(up, 0) // 60}m"
    try:
        seams = brain.health.snapshot() or {}
    except Exception:
        seams = {}
    bad = [f"{n}({(s or {}).get('failures', 0)})"
           for n, s in sorted(seams.items()) if (s or {}).get("failures", 0)]
    # config.model is normally a tier keyword (keyword/ollama/mlx/api) or a
    # simple model ref — never an endpoint or a path. But apply_config writes it
    # unvalidated, so redact anything with a path/host shape: a slash/backslash,
    # a `~`/`.` prefix, an IPv4, a `:port`, a scheme, or userinfo. This stops a
    # report from publishing a filesystem path (with the wearer's username) or an
    # endpoint someone set into the field (audit 2026-07-20 — the old `://`/`@`
    # test missed bare `host:port`, a LAN IP, and `/Users/<user>/…gguf`).
    import re as _re
    _model = str(brain.config.model or "")
    if ("/" in _model or "\\" in _model or "@" in _model or _model[:1] in ("~", ".")
            or _re.search(r"\d+\.\d+\.\d+\.\d+", _model)
            or _re.search(r":\d{2,}", _model)):
        _model = "(custom)"
    lines = [
        f"DreamLayer {_version()} · {_pf.system()} {_pf.machine()} · "
        f"Python {_pf.python_version()}",
        f"model: {_model[:60]} · index: {files} files · uptime: {uptime}",
    ]
    if caps:
        lines.append("capabilities: " + " · ".join(
            f"{caps[k]} {k}" for k in ("active", "off", "missing") if caps.get(k)))
    if bad:
        lines.append("seams with failures: " + ", ".join(bad))
    return "\n".join(lines)


def _build_bug_report(brain: Brain, summary: str, detail: str,
                      include_diag: bool = True) -> dict:
    """Assemble {title, body, github_url} for an in-app bug report. The body
    carries the wearer's words plus the sanitized diagnostics; github_url is a
    prefilled new-issue link (truncated to stay under browser/GitHub URL limits,
    while `body` keeps the full text for the copy-to-clipboard action)."""
    import urllib.parse as _up
    summary = (summary or "").strip()[:120] or "App issue"
    detail = (detail or "").strip()
    body = detail or "_(what happened, and what you expected)_"
    if include_diag:
        body += ("\n\n---\n**Diagnostics** (no personal data):\n```\n"
                 + _report_diagnostics(brain) + "\n```")
    body += "\n\n_Reported from the DreamLayer app._"

    def _url(b: str) -> str:
        q = _up.urlencode({"title": summary, "body": b, "labels": "bug"})
        return f"https://github.com/{_REPORT_REPO}/issues/new?{q}"

    # Bound the ENCODED url, not the source length: one multibyte char expands to
    # ~9–12 percent-encoded bytes, so a source-char cap doesn't bound the url for
    # non-ASCII input. Shrink the body until the built url fits, then keep it.
    _tail = "\n\n…(truncated — use “Copy report” for the full text)"
    url = _url(body)
    trimmed = body
    while len(url) > 6000 and len(trimmed) > 64:
        trimmed = trimmed[: int(len(trimmed) * 0.8)]
        url = _url(trimmed + _tail)
    return {"title": summary, "body": body, "github_url": url}


def _answer_json(ans: Optional[Answer]) -> dict:
    if ans is None:
        return {"text": "", "tier": "", "sources": [], "confidence": 0.0}
    return {"text": ans.text, "tier": ans.tier, "sources": ans.sources,
            "confidence": ans.confidence}


def _activity_feed(brain: Brain, n: int = 40) -> list[dict]:
    """One newest-first feed: questions + every action the Brain took."""
    items = []
    for h in brain.history.recent(n):
        items.append({"ts": h.get("ts", 0), "kind": "ask",
                      "query": h.get("query", ""), "text": h.get("answer", ""),
                      "tier": h.get("tier", "")})
    for a in brain.activity.recent(n):
        items.append({"ts": a.get("ts", 0), "kind": a.get("kind", "event"),
                      "text": a.get("text", "")})
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return items[:n]


def _browse_dir(raw: str) -> dict:
    """List the subfolders of a directory so the panel can walk the Mac's own
    filesystem — folders only, hidden entries skipped."""
    base = Path(raw).expanduser() if raw else Path.home()
    try:
        base = base.resolve()
    except OSError:
        base = Path.home()
    if not base.is_dir():
        base = Path.home()
    dirs = []
    try:
        for e in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if e.is_dir() and not e.name.startswith("."):
                dirs.append(e.name)
    except OSError:
        # a permission-denied or vanished directory just lists no children —
        # genuinely ignorable for a folder picker; narrowed to OSError.
        pass
    parent = str(base.parent) if base.parent != base else ""
    return {"path": str(base), "parent": parent, "dirs": dirs,
            "home": str(Path.home())}
