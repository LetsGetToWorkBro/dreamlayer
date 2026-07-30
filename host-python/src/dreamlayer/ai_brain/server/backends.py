"""ai_brain/server/backends.py — the model backend (Ollama on the Mac mini).

The Brain's smarts are pluggable. Default is keyword-only (no model, works
everywhere). Point it at Ollama and it gains a chat model (to write answers
from retrieved passages) and a vision model (to explain what you look at).

OllamaBackend speaks Ollama's local HTTP API; `http_post(url, payload)` is
injectable so it's testable without Ollama running.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from ..schema import Answer

log = logging.getLogger("dreamlayer.backends")


# Cloud providers the panel offers. `wire` is the on-the-wire format the
# adapter speaks; `base_url`/`model` are pre-fills the panel suggests (still
# user-editable). `needs_key` drives whether the panel shows the API-key field
# — Ollama runs locally with no key (free + private).
PROVIDER_PRESETS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI", "base_url": "https://api.openai.com",
        "model": "gpt-4o-mini", "needs_key": True, "wire": "openai"},
    "anthropic": {
        "label": "Anthropic", "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-haiku-latest", "needs_key": True, "wire": "anthropic"},
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-1.5-flash", "needs_key": True, "wire": "gemini"},
    "openrouter": {
        "label": "OpenRouter", "base_url": "https://openrouter.ai/api",
        "model": "openai/gpt-4o-mini", "needs_key": True, "wire": "openai"},
    "groq": {
        # Groq's OpenAI-compatible surface lives under /openai/v1 (docs:
        # console.groq.com/docs/openai). The /v1 in the base means
        # _build_request appends only /chat/completions, not /v1/chat/….
        "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile", "needs_key": True, "wire": "openai"},
    "together": {
        # Together AI, OpenAI-compatible (docs: docs.together.ai).
        "label": "Together AI", "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "needs_key": True, "wire": "openai"},
    "deepseek": {
        # DeepSeek, OpenAI-compatible (docs: api-docs.deepseek.com). Host root
        # like OpenAI — _build_request adds /v1/chat/completions, which DeepSeek
        # accepts (its /v1 is a compat alias, unrelated to model version).
        "label": "DeepSeek", "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat", "needs_key": True, "wire": "openai"},
    "ollama": {
        "label": "Ollama · local", "base_url": "http://localhost:11434",
        "model": "llama3.2", "needs_key": False, "wire": "openai"},
    "dreamlayer": {
        # The hosted tier's managed-AI proxy (docs/CLOUD.md): an OpenAI-
        # compatible endpoint at api.dreamlayer.app; the "key" is the account
        # token, so there is no provider key to wire. Rides the same egress
        # ledger and incognito gate as every other cloud provider.
        "label": "DreamLayer Cloud", "base_url": "https://api.dreamlayer.app",
        "model": "dreamlayer-standard", "needs_key": True, "wire": "openai"},
    "custom": {
        "label": "Custom (OpenAI-compatible)", "base_url": "",
        "model": "", "needs_key": True, "wire": "openai"},
}


# The one definition of "on my device / my LAN", used verbatim by BOTH the
# server (egress accounting + veil gating) and the panel's JS warning, so the
# two never disagree. Deliberately EXPLICIT and narrow — loopback, the three
# RFC-1918 private v4 blocks, IPv4/IPv6 link-local, and IPv6 loopback — rather
# than ipaddress.is_private, which also claims TEST-NET / benchmarking / CGNAT
# ranges that are not "your device" and whose looseness the JS mirror can't
# match. Anything outside this set — a public IP, a bare hostname (which a DNS
# search domain could resolve to a public host), an exotic reserved range, or
# an unparseable URL — is REMOTE and treated as egress. Fail-safe by design:
# over-counting a call as leaving the device is harmless; under-counting one
# that actually left is a privacy lie.
# NOTE 169.254.0.0/16 is deliberately ABSENT. It was here as "link-local, so
# it's on my network" -- but it is the same range as _BLOCKED_NETS below, where
# every cloud's instance-metadata service lives. Any call site that asked only
# `is_local_endpoint` therefore treated cloud-credential space as a trusted
# on-device endpoint: exempt from the egress counter, exempt from the veil, and
# described to the wearer as "on your device". Link-local is not somewhere a
# model endpoint ever legitimately lives.
_LOCAL_NETS = tuple(__import__("ipaddress").ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128",
    # IPv6 unique-local (fd00::/8) is the ordinary way an IPv6-only home LAN
    # addresses itself, so an IPv6 LAN's own Ollama box has to read as local —
    # otherwise the posture gate refuses the very endpoint `lan_only` exists to
    # permit. fe80::/10 (v6 link-local) is deliberately NOT here: it is in
    # _BLOCKED_NETS, and listing a blocked range as "local" is precisely the
    # overlap that made 169.254/16 read as on-device. One range, one meaning.
    #
    # fd00::/8, not fc00::/7: RFC 4193 sets L=1 for locally-assigned ULAs, so
    # fd00::/8 is the range real networks use and fc00::/8 is unassigned. The
    # egress seal permits the wider fc00::/7, which CONTAINS this — that is fine,
    # and the parity test checks containment rather than identity for exactly that
    # reason (the seal is deliberately a superset).
    "fd00::/8"))


def is_local_endpoint(base_url: str) -> bool:
    """True when an endpoint lives on THIS machine or the local network — so it
    is NOT cloud egress and stays reachable while incognito, exactly like the
    Mac-mini/Ollama tier. A remote (public) endpoint, a bare hostname, or an
    unparseable URL returns False and is treated as egress: counted, logged,
    and veil-gated. See _LOCAL_NETS for the exact rule (mirrored in panel.py's
    isLocalUrl)."""
    try:
        host = (urllib.parse.urlsplit(base_url or "").hostname or "").strip().lower()
    except ValueError:
        return False                       # malformed URL (e.g. bad IPv6) → remote
    if not host:
        return False
    # The root-anchored FQDN forms ("localhost.", "nas.local.") are the same
    # names; a trailing dot is DNS syntax, not a different host.
    h = host.rstrip(".")
    if h == "localhost" or h.endswith(".local"):
        return True
    # Same canonicaliser as the block guard, so the two agree about what an
    # address IS. It also restores the shorthand forms a person actually types:
    # `127.1` is genuine loopback, and refusing it broke a legitimate endpoint.
    ip = _canon_ip(host)
    if ip is None:
        return False                       # hostname (bare or public) → remote
    return any(ip in net for net in _LOCAL_NETS if ip.version == net.version)


# Addresses that are NEVER a legitimate model endpoint and are the classic SSRF
# pivot: link-local auto-config space, where every major cloud's instance
# metadata service (IMDS) lives — 169.254.169.254 on AWS/GCP/Azure/DO/Oracle,
# fd00:ec2::254 for AWS IPv6. A model base_url resolving here is refused OUTRIGHT
# at the request chokepoint (_provider_chat) and kept out of the stored config,
# so a token holder / rebound page / CSRF cannot turn the Brain into an IMDS
# credential-theft proxy when it runs on a cloud instance (audit 2026-07-19).
_BLOCKED_NETS = tuple(__import__("ipaddress").ip_network(n) for n in (
    "169.254.0.0/16", "fe80::/10"))
_BLOCKED_HOSTS = frozenset({"169.254.169.254", "fd00:ec2::254",
                            "::ffff:169.254.169.254"})


def _canon_ip(host: str):
    """Every spelling of an IP literal, reduced to one address — or None.

    `ipaddress.ip_address` accepts ONLY dotted-quad and canonical IPv6, so a
    guard built on it alone matched a *string*, not a destination. All of these
    reach 169.254.169.254 and all of them slipped past it:

        0251.0376.0251.0376   octal dotted
        0xa9fea9fe            hex 32-bit
        2852039166            decimal 32-bit
        169.254.43518         partial / mixed
        169.254.169.254.      root-anchored trailing dot
        [::ffff:a9fe:a9fe]    IPv4-mapped, written in hex groups

    So: strip the trailing dot, unwrap an IPv4-mapped/compatible v6 address to
    its v4 form, and hand anything else to `inet_aton`, which implements the
    same permissive parse the C library — and therefore the socket — uses.
    Returns an `IPv4Address`/`IPv6Address`, or None when the host is a name."""
    import ipaddress
    import socket
    h = (host or "").strip().strip("[]").rstrip(".")
    if not h:
        return None
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        # Not a canonical literal. `inet_aton` accepts octal, hex, and the
        # short forms; it rejects hostnames, which is exactly the split we want.
        try:
            return ipaddress.ip_address(socket.inet_aton(h))
        except (OSError, ValueError):
            return None
    # An IPv4 address wearing a v6 costume is still that IPv4 address.
    mapped = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
    return mapped or ip


def _is_loopback(base_url: str) -> bool:
    """True only when the endpoint is on THIS machine. Distinct from
    `is_local_endpoint`, which also spans the LAN -- and the difference is what
    the receipt needs, because the LAN is somebody else's computer."""
    try:
        host = (urllib.parse.urlsplit(base_url or "").hostname or "").strip().lower()
    except ValueError:
        return False
    if host in ("localhost", "localhost."):
        return True
    ip = _canon_ip(host)
    return bool(ip is not None and ip.is_loopback)


def is_blocked_endpoint(base_url: str) -> bool:
    """True when `base_url`'s host is link-local / cloud-metadata space — an
    endpoint the Brain must never fetch. Only IP-literal hosts are judged here
    (a hostname like ``metadata.google.internal`` is already egress via
    is_local_endpoint=False and DNS-resolved by the OS); this stops the direct
    IP-literal IMDS pivot. Non-IP hosts return False.

    Judges the ADDRESS, not the spelling — see `_canon_ip`. Matching spellings
    let five different renderings of 169.254.169.254 through `POST /config`,
    `POST /restore`, the redirect guard and `_provider_chat` alike."""
    try:
        host = (urllib.parse.urlsplit(base_url or "").hostname or "").strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    if host.rstrip(".") in _BLOCKED_HOSTS:
        return True
    ip = _canon_ip(host)
    if ip is None:
        return False
    return any(ip in net for net in _BLOCKED_NETS if ip.version == net.version)


def _build_request(provider: str, base_url: str, model: str, key: str, prompt: str):
    """Return (wire, url, body_dict, headers) for a provider/endpoint tuple.

    Three wire formats, all hand-rolled (no SDK): OpenAI-compatible chat
    completions (openai/openrouter/ollama/custom), Anthropic messages, and
    Gemini generateContent. Pure — unit-testable without a network. Shared by
    the cloud-escalation tier (cloud_* config) and the primary API-brain tier
    (api_* config), so both speak the same adapters from one place."""
    provider = provider or "openai"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    wire = preset["wire"]
    base = (base_url or preset["base_url"]).rstrip("/")
    key = key or ""
    if wire == "anthropic":
        url = base + "/v1/messages"
        body = {"model": model, "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"}
    elif wire == "gemini":
        url = (f"{base}/v1beta/models/{model}:generateContent"
               f"?key={urllib.parse.quote(key)}")
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json"}
    else:  # openai-compatible
        # Don't double the version segment: many local servers (LM Studio,
        # llama.cpp, vLLM) are addressed with the /v1 already in the base URL,
        # and one-click discovery hands those back verbatim. base + "/v1/…"
        # would then POST to /v1/v1/chat/completions and 404.
        suffix = "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
        url = base + suffix
        body = {"model": model,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
        if key:  # Ollama-local sends no key
            headers["Authorization"] = "Bearer " + key
    return wire, url, body, headers


def _build_cloud_request(config, prompt: str):
    """Back-compat shim: build a request from the cloud_* config group."""
    return _build_request(getattr(config, "cloud_provider", "openai") or "openai",
                          config.cloud_base_url, config.cloud_model,
                          config.cloud_api_key or "", prompt)


def _parse_cloud_response(wire: str, d: dict) -> str:
    """Pull the answer text out of a provider's JSON response."""
    if wire == "anthropic":
        parts = d.get("content") or []
        return "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict)).strip()
    if wire == "gemini":
        cands = d.get("candidates") or [{}]
        parts = ((cands[0].get("content") or {}).get("parts")) or [{}]
        return "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict)).strip()
    choices = d.get("choices") or [{}]
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _urllib_post(url: str, payload: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    opener = _guarded_opener()
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _urllib_get(url: str, timeout: float = 4.0) -> dict:
    opener = _guarded_opener()
    with opener.open(urllib.request.Request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


_STREAM_MAX_LINE = 1 << 20        # 1 MiB — a progress line is ~100 bytes; a
#                                   newline-less flood is the OOM this caps.
_STREAM_MAX_TOTAL = 512 << 20     # generous backstop; real progress is a few MB.


def _urllib_post_stream(url: str, payload: dict, timeout: float, on_line) -> None:
    """POST and read a newline-delimited JSON stream (Ollama's /api/pull with
    stream:true), invoking ``on_line(obj)`` per parsed object. Used to surface
    live pull progress instead of blocking on one giant response.

    The read is BOUNDED (per-line and total): a misbehaving or hostile endpoint
    that returns one enormous newline-less line can no longer exhaust the pull
    thread's memory (audit 2026-07-20)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    opener = _guarded_opener()

    def _emit(chunk: bytes) -> None:
        line = chunk.decode("utf-8", "replace").strip()
        if not line:
            return
        try:
            on_line(json.loads(line))
        except ValueError:
            pass                               # a partial/non-JSON keep-alive line

    with opener.open(req, timeout=timeout) as resp:
        buf = b""
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _STREAM_MAX_TOTAL:
                raise ValueError("pull progress stream exceeded its size cap")
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                _emit(raw)
            if len(buf) > _STREAM_MAX_LINE:    # no newline in sight → flood
                raise ValueError("pull progress line exceeded its size cap")
        _emit(buf)                             # trailing line without a newline


def pull_model_stream(config, name: str, on_progress=None, streamer=None) -> dict:
    """Pull an Ollama model, reporting live progress via ``on_progress(percent,
    detail)`` as it streams — so a multi-GB pull shows a moving bar instead of a
    single request that blocks for minutes and times the browser out. Returns
    {ok, status, model}. ``streamer`` is injectable for tests."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "status": "no model name", "model": ""}
    url = (getattr(config, "ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    result = {"ok": False, "status": "", "model": name}

    def handle(obj):
        if not isinstance(obj, dict):
            return
        err = obj.get("error")
        if err:
            result["status"] = str(err)[:200]
            return
        st = obj.get("status", "")
        if st:
            result["status"] = st
        if st and "success" in str(st).lower():
            result["ok"] = True
        total, done = obj.get("total"), obj.get("completed")
        pct = None
        if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
            pct = max(0, min(100, round(100.0 * done / total)))
        if on_progress is not None:
            on_progress(pct, st or "")

    stream = streamer or (lambda u, p, t, cb: _urllib_post_stream(u, p, t, cb))
    try:
        stream(url + "/api/pull", {"name": name, "stream": True}, 3600.0, handle)
    except Exception as e:                     # unreachable Ollama, mid-stream drop
        result["status"] = f"could not reach Ollama: {e}"
        return result
    return result


# Well-known local agent servers, by default port. Discovery probes each for a
# model list; a hit means the agent is running and can be connected in one tap
# with nothing to type. Every probe is a LOCALHOST address, so a discovered
# agent is on-device by construction — one-click connect can never wire a
# remote endpoint. base_url is what gets saved verbatim (the /v1 forms are
# handled by _build_request's no-double-/v1 rule).
_LOCAL_AGENT_PROBES = (
    {"label": "Ollama", "provider": "ollama",
     "base_url": "http://localhost:11434",
     "models_url": "http://localhost:11434/api/tags"},
    {"label": "LM Studio", "provider": "custom",
     "base_url": "http://localhost:1234/v1",
     "models_url": "http://localhost:1234/v1/models"},
    {"label": "Jan", "provider": "custom",
     "base_url": "http://localhost:1337/v1",
     "models_url": "http://localhost:1337/v1/models"},
    {"label": "vLLM", "provider": "custom",
     "base_url": "http://localhost:8000/v1",
     "models_url": "http://localhost:8000/v1/models"},
    {"label": "llama.cpp / LocalAI", "provider": "custom",
     "base_url": "http://localhost:8080/v1",
     "models_url": "http://localhost:8080/v1/models"},
    {"label": "Text-Gen-WebUI", "provider": "custom",
     "base_url": "http://localhost:5000/v1",
     "models_url": "http://localhost:5000/v1/models"},
    {"label": "GPT4All", "provider": "custom",
     "base_url": "http://localhost:4891/v1",
     "models_url": "http://localhost:4891/v1/models"},
    {"label": "KoboldCpp", "provider": "custom",
     "base_url": "http://localhost:5001/v1",
     "models_url": "http://localhost:5001/v1/models"},
)


def _models_from(data: dict) -> list:
    """Model names out of either shape: Ollama /api/tags ({models:[{name}]}) or
    OpenAI-compatible /v1/models ({data:[{id}]})."""
    out = []
    for m in ((data.get("models") or data.get("data") or [])
              if isinstance(data, dict) else []):
        name = (isinstance(m, dict) and (m.get("name") or m.get("id"))) or ""
        if name:
            out.append(name)
    return out


def discover_local_agents(timeout: float = 0.6, getter=None) -> list:
    """Find agent servers already running on this Mac for a one-click connect.

    Probes the well-known local ports concurrently and returns the reachable
    ones with their model lists: [{label, provider, base_url, models}]. Every
    endpoint is localhost, so anything returned is on-device — connecting one
    can never wire a remote/egress endpoint. `getter(url, timeout)->dict` is
    injectable for tests."""
    import concurrent.futures as _f
    get = getter or _urllib_get

    def probe(a: dict):
        try:
            data = get(a["models_url"], timeout)
        except Exception:
            return None                       # not running / not reachable
        return {"label": a["label"], "provider": a["provider"],
                "base_url": a["base_url"], "models": _models_from(data)}

    found = []
    with _f.ThreadPoolExecutor(max_workers=len(_LOCAL_AGENT_PROBES)) as ex:
        for r in ex.map(probe, _LOCAL_AGENT_PROBES):
            if r is not None:
                found.append(r)
    return found


def _posture_forbids_egress(config) -> bool:
    """True when the wearer's posture forbids off-box egress — LAN-only or a
    quiet-hours window. Mirrors ``Brain.incognito_now()`` but reads only the
    config, so a bare backend function can honor posture without the Brain."""
    from .store import in_quiet_hours
    return bool(getattr(config, "lan_only", False)
                or in_quiet_hours(getattr(config, "quiet_hours", "") or ""))


def probe_ollama(config, timeout: float = 4.0) -> dict:
    """Is Ollama up, and which of the configured models are pulled?

    Returns {reachable, url, models, want, have} so the panel can show a live
    setup status per model instead of failing silently.
    """
    url = (getattr(config, "ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    want = {"chat":   getattr(config, "ollama_chat_model", "") or "",
            "vision": getattr(config, "ollama_vision_model", "") or "",
            "embed":  getattr(config, "ollama_embed_model", "") or ""}
    # A REMOTE ollama_url is egress. Honor posture: in Incognito/LAN-only don't
    # reach an off-box endpoint (a localhost probe is not egress and still
    # runs). Mirrors the pull path's gate — the probe was the missed sibling
    # call-site reached by /model/status (15s poll) and /health (audit 2026-07-20).
    if not is_local_endpoint(url) and _posture_forbids_egress(config):
        return {"reachable": False, "url": url, "models": [], "want": want,
                "have": {k: False for k in want}, "blocked": "posture"}
    try:
        data = _urllib_get(url + "/api/tags", timeout)
        names = [m.get("name", "") for m in (data.get("models") or [])]
    except Exception:
        return {"reachable": False, "url": url, "models": [], "want": want,
                "have": {k: False for k in want}}

    def present(name: str) -> bool:
        if not name:
            return False
        base = name.split(":")[0]
        return any(n == name or n.split(":")[0] == base for n in names)

    return {"reachable": True, "url": url, "models": names, "want": want,
            "have": {k: present(v) for k, v in want.items()}}


def pull_model(config, name: str, poster: Optional[Callable[[str, dict, float], dict]] = None
               ) -> dict:
    """Pull an Ollama model by name via the local HTTP API (no CLI needed).

    Blocking; Ollama streams progress but we wait for completion. `poster` is
    injectable for tests. Returns {ok, status, model}.
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "status": "no model name", "model": ""}
    url = (getattr(config, "ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    post = poster or (lambda u, p, t: _urllib_post(u, p, t))
    try:
        # stream:false makes Ollama return once the pull finishes
        res = post(url + "/api/pull", {"name": name, "stream": False}, 1800.0)
    except Exception as e:
        return {"ok": False, "status": f"could not reach Ollama: {e}", "model": name}
    status = (res or {}).get("status", "")
    ok = status == "success" or "success" in str(status).lower()
    return {"ok": ok, "status": status or "unknown", "model": name}


class OllamaBackend:
    """Chat + vision + embeddings via a local Ollama server."""

    def __init__(self, config, http_post: Optional[Callable] = None,
                 timeout: float = 30.0, on_egress: Optional[Callable] = None):
        self.config = config
        self._post = http_post or (lambda u, p: _urllib_post(u, p, timeout))
        # Called with the endpoint URL immediately BEFORE a request that leaves
        # this machine, so the Brain can count and log it. Optional so a bare
        # backend still works; when absent the posture gate below still holds.
        self._on_egress = on_egress

    def _endpoint(self, path: str) -> Optional[str]:
        """Resolve an Ollama URL, refusing the ones we must not reach.

        Ollama is presented to the wearer as the on-device tier -- the panel says
        "questions never leave your device and it keeps working while incognito".
        That is true for 127.0.0.1 and false the moment `ollama_url` points at
        another box, which is a supported setup ("run Ollama on your gaming PC").
        Before this, that case had NO posture gate, NO locality check, NO egress
        count and NO ledger entry, while `probe_ollama` right above already had
        all of them -- so a veiled `ask` shipped the wearer's notes (and, with
        semantic search on, the entire indexed corpus via /api/embeddings) to
        another machine, reported tier "laptop", and left the counter at 0.

        Returns None when the request must not be made."""
        url = (getattr(self.config, "ollama_url", "") or "").rstrip("/")
        if not url:
            return None
        # Link-local / cloud-metadata space is never a model endpoint.
        if is_blocked_endpoint(url):
            log.warning("[ollama] endpoint refused: link-local / metadata address")
            return None
        if not is_local_endpoint(url):
            if _posture_forbids_egress(self.config):
                return None                  # the shield is up: do not reach out
            self._note(url, remote=True)
        elif not _is_loopback(url):
            # A LAN box is NOT "on your device". `lan_only` legitimately permits
            # it -- that is what the mode name means -- but the wearer's notes
            # still crossed the room to another computer, so the receipt has to
            # show it. Reported separately from cloud egress rather than folded
            # into `cloud_calls`, because calling a LAN hop a cloud call would be
            # its own inaccuracy. (An earlier version of this comment claimed a
            # LAN host was already counted "like any other egress". It was not.)
            self._note(url, remote=False)
        return url + path

    def _note(self, url: str, remote: bool) -> None:
        if self._on_egress is None:
            return
        try:
            self._on_egress(url, remote)
        except TypeError:                    # a 1-arg hook (tests, older callers)
            try:
                self._on_egress(url)
            except Exception:                # noqa: BLE001
                pass
        except Exception:                    # noqa: BLE001 - never break the ask
            pass

    def _gen(self, model: str, prompt: str, images=None) -> str:
        payload = {"model": model, "prompt": prompt, "stream": False}
        if images:
            payload["images"] = images
        url = self._endpoint("/api/generate")
        if url is None:
            return ""
        out = self._post(url, payload)
        return (out or {}).get("response", "").strip()

    def chat(self, prompt: str) -> str:
        return self._gen(self.config.ollama_chat_model, prompt)

    def vision(self, label: str, image_b64: Optional[str], want: str) -> str:
        detail = "one rich, useful sentence" if want == "more" else "a few words"
        prompt = (f"You are looking at what appears to be a {label}. In "
                  f"{detail}, say what it is and the single most useful thing "
                  f"to know about it. Be concrete.")
        imgs = [image_b64] if image_b64 else None
        return self._gen(self.config.ollama_vision_model, prompt, images=imgs)

    def describe(self, prompt: str, image_b64: Optional[str]) -> str:
        """Run the vision model against an arbitrary prompt — the low-level seam
        the World Lens's structured recognizer uses to ask "what is this and
        what does it read" and get back fields (a price, a title, an ISBN), not
        just the fixed sentence :meth:`vision` produces. Same model, same wire;
        the caller owns the prompt and parses the reply."""
        imgs = [image_b64] if image_b64 else None
        return self._gen(self.config.ollama_vision_model, prompt, images=imgs)

    def embed(self, text: str) -> list:
        # The highest-volume egress on this backend by far: a reindex embeds
        # every indexed file, one request per chunk.
        url = self._endpoint("/api/embeddings")
        if url is None:
            return []
        out = self._post(url, {"model": self.config.ollama_embed_model,
                               "prompt": text})
        return (out or {}).get("embedding", []) or []


def _host_of(url: str) -> str:
    """scheme://host:port, lower-cased — the identity a credential is scoped to."""
    try:
        s = urllib.parse.urlsplit(url or "")
        return f"{(s.scheme or '').lower()}://{(s.netloc or '').lower()}"
    except ValueError:
        return ""


class _NoBlockedRedirect(urllib.request.HTTPRedirectHandler):
    """Re-apply the SSRF guard to every redirect hop.

    `is_blocked_endpoint` was checked once, against the URL the caller supplied,
    and then `opener.open` happily followed a 302 wherever it pointed. One
    redirect to 169.254.169.254 was enough to read cloud instance-metadata
    credentials back through the model reply -- the exact "turn the Brain into an
    IMDS credential-theft proxy" the guard's own comment says it prevents. A
    guard that only inspects the first hop does not guard a redirect chain."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if is_blocked_endpoint(newurl):
            raise urllib.error.HTTPError(
                newurl, code,
                "redirect refused: link-local / cloud-metadata address",
                headers, fp)
        # A CROSS-HOST redirect must not carry the wearer's provider key. urllib
        # strips the body on a 30x but KEEPS the Authorization header, so a 302
        # from a compromised or typo'd endpoint to any public host handed over
        # `Bearer sk-…` and returned the attacker's body as the model's answer.
        # Blocking link-local was never enough for that: the destination that
        # matters here is "not the host I authenticated to".
        out = super().redirect_request(req, fp, code, msg, headers, newurl)
        if out is not None and _host_of(newurl) != _host_of(req.get_full_url()):
            for h in ("Authorization", "Proxy-Authorization", "X-Api-Key",
                      "Api-Key", "X-Goog-Api-Key"):
                out.remove_header(h)
                out.remove_header(h.capitalize())
        return out


def _guarded_opener():
    """A urllib opener with no proxy and no unguarded redirects. Every model
    endpoint fetch must use this, not `build_opener(ProxyHandler({}))`."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _NoBlockedRedirect())


def _provider_chat(provider: str, base_url: str, model: str, key: str,
                   prompt: str, http_post: Optional[Callable] = None,
                   timeout: float = 30.0) -> str:
    """Ask any provider/endpoint, dispatched on wire format. Injectable
    http_post short-circuits to a test double (posts {model, prompt} to the
    base URL and reads {text})."""
    # SSRF guard: never reach a link-local / cloud-metadata endpoint, whichever
    # tier configured it. Refused before the injectable http_post too, so a test
    # double can't be pointed at IMDS either (audit 2026-07-19).
    if is_blocked_endpoint(base_url):
        raise ValueError("endpoint refused: link-local / cloud-metadata address")
    if http_post is not None:
        out = http_post(base_url, {"model": model, "prompt": prompt})
        return (out or {}).get("text", "").strip()
    wire, url, body, headers = _build_request(provider, base_url, model, key, prompt)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    opener = _guarded_opener()
    with opener.open(req, timeout=timeout) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    return _parse_cloud_response(wire, d)


def cloud_chat(config, prompt: str, http_post: Optional[Callable] = None,
               timeout: float = 30.0) -> str:
    """Ask the configured CLOUD-escalation model. Supports OpenAI, Anthropic,
    Gemini, OpenRouter, Ollama-local, and any custom OpenAI-compatible endpoint
    — dispatched on config.cloud_provider. Injectable for tests."""
    return _provider_chat(getattr(config, "cloud_provider", "openai") or "openai",
                          config.cloud_base_url, config.cloud_model,
                          config.cloud_api_key or "", prompt, http_post, timeout)


def api_chat(config, prompt: str, http_post: Optional[Callable] = None,
             timeout: float = 30.0) -> str:
    """Ask the wearer's own PRIMARY external API/agent (the api_* config group:
    OpenClaw, Hermes, LM Studio, vLLM, a local Ollama, any OpenAI-compatible /
    Anthropic / Gemini endpoint). Same wire adapters as cloud_chat, but a
    SEPARATE config group so the primary brain and the cloud-escalation tier
    are independent and can point at different places. The caller
    (Brain._ask_primary_api) owns the local-vs-remote egress accounting."""
    return _provider_chat(getattr(config, "api_provider", "custom") or "custom",
                          config.api_base_url, config.api_model,
                          config.api_key or "", prompt, http_post, timeout)


def cloud_test(config, http_post: Optional[Callable] = None) -> dict:
    """A tiny round-trip so the panel can say 'connected' or show the error."""
    try:
        txt = cloud_chat(config, "Reply with the single word: OK",
                         http_post=http_post, timeout=15.0)
        return {"ok": bool(txt), "reply": txt[:80]}
    except Exception as e:  # noqa: BLE001 — surface any provider error verbatim
        return {"ok": False, "error": str(e)[:200]}


def api_test(config, http_post: Optional[Callable] = None) -> dict:
    """Same round-trip against the PRIMARY API brain (api_* config), so the
    panel's 'Test connection' can confirm the wearer's own agent replies."""
    if not (getattr(config, "api_base_url", "") or "").strip():
        return {"ok": False, "error": "no endpoint set"}
    try:
        txt = api_chat(config, "Reply with the single word: OK",
                       http_post=http_post, timeout=15.0)
        return {"ok": bool(txt), "reply": txt[:80]}
    except Exception as e:  # noqa: BLE001 — surface any provider error verbatim
        return {"ok": False, "error": str(e)[:200]}


def make_synthesizer(backend: Any) -> Callable:
    """Turn retrieved passages into a written answer via the chat model.

    Typed by the one method it uses rather than by a union of backend classes:
    the union had to be widened for every new tier (MLX, then exo) even though
    the body only ever calls `chat(prompt)->str`, which is the actual contract.
    """
    def synth(query: str, passages: list[tuple[str, str]]) -> str:
        context = "\n\n".join(f"[{name}] {text}" for name, text in passages)
        prompt = (f"Answer the question using only the notes below. Cite "
                  f"nothing you can't see. If they don't answer it, say so.\n\n"
                  f"Notes:\n{context}\n\nQuestion: {query}\nAnswer:")
        return backend.chat(prompt)
    return synth


def vision_answer(backend: Any, label: str,
                  image_b64: Optional[str], want: str) -> Optional[Answer]:
    """Explain an object. With no backend, return None (the tier declines).

    A TEXT-ONLY backend declines the same way. Not every tier sees: exo serves
    `/v1/chat/completions` and no images, so `ExoClusterBackend` deliberately has
    no `vision()`. The check is explicit rather than left to the except clause
    below, so "this tier cannot see" and "this tier failed" stay distinguishable
    to a reader — they were already indistinguishable to the caller.
    """
    if backend is None or not hasattr(backend, "vision"):
        return None
    try:
        text = backend.vision(label, image_b64, want)
    except Exception:
        return None
    if not text:
        return None
    return Answer(text=text, tier="laptop", sources=["vision"], confidence=0.7)
