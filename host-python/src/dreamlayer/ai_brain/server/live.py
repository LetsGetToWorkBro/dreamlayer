"""live.py — the Live Lens: any phone's browser becomes the glasses.

Open one URL (QR from the panel), grant the camera, and the loop is real end
to end: your camera frame goes to YOUR Brain on YOUR LAN and a look runs the
SAME pipeline the glasses will — the World lens (``Brain.world_lens()``: the
VLM-backed structured recognizer with the classifier ladder as its offline
rung, the Object Lens, and your installed plugin providers), so a price tag
comes back converted and a book spine comes back rated, exactly like the
phone app's Look and the future on-glass glance. One formatter
(:func:`panel_lines`) clamps every surface's answer to the display budget the
glasses prove: MAX_LINES x MAX_TEXT_LEN utf-8 bytes (reality_compiler.v2
.figment — the canonical unit shared by all four interpreters). Asks ride the
existing /dreamlayer/brain/ask route, so recall, tiers, and the wearer's
no-cloud posture are the production paths, not simulations.

What this deliberately is NOT (the honest ceiling): a phone screen is opaque
and hand-held — it cannot reproduce the see-through waveguide, the head-mounted
framing, or the all-day ambient presence of the real glass. The Live Lens is
the real SYSTEM without the physical glass, and the page says so.

Privacy invariants (tested):
  * Frames are decoded in memory and never written to disk.
  * The wearer's egress shield (incognito: LAN-only / quiet hours) makes a
    look LOCAL-ONLY: the in-process classifier ladder answers, the plugin
    pipeline and any remote vision are not consulted, and no ledger trace is
    written. Outside the shield, pixels still never ride to a plugin — a
    provider row is built from the extracted label/fields only.
  * The page HTML carries no token; the credential rides the URL FRAGMENT
    (#t=...) of the link/QR the panel hands out local-only, so it never
    appears in request lines or server logs. Same trust model as pairing:
    the code IS the credential.
"""
from __future__ import annotations

import io
import json
import logging
import threading

from ...reality_compiler.v2.figment import MAX_LINES, MAX_TEXT_LEN

log = logging.getLogger("dreamlayer.live")

# A camera frame is a downscaled JPEG a phone posts a few times a minute —
# 4 MiB is generous headroom for that and a hard wall against abuse (the
# server's _raw() turns anything larger into a 413 before reading it).
MAX_FRAME_BYTES = 4 * 1024 * 1024

# A decompression-bomb ceiling on the DECODED pixel count, checked from the
# header BEFORE any pixels are materialised. MAX_FRAME_BYTES bounds the
# *compressed* upload; a tiny PNG/WebP can still declare a huge canvas and
# balloon to hundreds of MB when decoded (a WebP decodes to ~12 bytes/pixel, far
# above the 3 of a raw RGB array — refute 2026-07-20). The browser only ever
# posts a <=720px frame here (see captureFrame), so 16 MP is ~30x real headroom
# yet keeps even a crafted WebP's transient decode bounded (16 MP ~= 190 MB),
# which with the concurrency cap below holds peak RSS to a fraction of a GB. The
# public Live Lens route had NO pre-decode cap at all before this.
MAX_FRAME_PIXELS = 16 * 1024 * 1024

# Frames are thumbnailed to this max side before classification: the vision
# ladder's features are scale-tolerant and this bounds CPU per look.
_MAX_SIDE = 512

# Bound how many frames decode CONCURRENTLY. The server's worker pool is 64
# threads and an authed look is not per-token rate-limited, so 64 simultaneous
# decodes (each up to MAX_FRAME_PIXELS) could still stack GBs of transient RSS.
# This semaphore caps peak decode memory. It is acquired NON-BLOCKING (see
# decode_frame): a burst SHEDS excess frames rather than parking worker threads
# on the semaphore — a blocked decode would hold its worker slot, so a blocking
# acquire just trades a memory-DoS for a thread-starvation-DoS (58 of 64 workers
# parkable on 6 slots — refute 2026-07-20). Shedding is also the right behaviour
# for a real-time lens: the freshest frame matters, not a backlog.
_MAX_CONCURRENT_DECODES = 6
_decode_sem = threading.BoundedSemaphore(_MAX_CONCURRENT_DECODES)

# Mirror the recognizer's min_confidence (ObjectRecognizer default 0.5): the
# local floor must apply the SAME gate the world-lens path does, or a heuristic
# guess the recognizer would reject shows anyway when the look falls to the floor
# (refute 2026-07-20 — incognito and normal disagreed on the identical frame).
_MIN_LOCAL_CONFIDENCE = 0.5

_ladder = None            # lazy vision ladder — built once, on first look


def _classifier():
    """The real vision ladder, built lazily (heavy backends import on use)."""
    global _ladder
    if _ladder is None:
        from ...object_lens.classify_backends import default_classifier
        _ladder = default_classifier()
    return _ladder


def wrap_hud_lines(text: str, max_lines: int = MAX_LINES,
                   max_bytes: int = MAX_TEXT_LEN) -> list[str]:
    """Word-wrap text into the HUD budget: <= max_lines lines of <= max_bytes
    UTF-8 bytes each (the canonical unit — ASCII gets 24 chars, multi-byte
    scripts fewer, exactly like the glass's 24-byte slot buffers). A word that
    alone exceeds the budget is split at the byte boundary; overflow past the
    last line is dropped with a trailing ellipsis-dot marker on that line."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        while len(w.encode("utf-8")) > max_bytes:      # an over-budget word
            if cur:
                lines.append(cur); cur = ""
            head = w
            while len(head.encode("utf-8")) > max_bytes:
                head = head[:-1]
            lines.append(head)
            w = w[len(head):]
        trial = (cur + " " + w).strip()
        if len(trial.encode("utf-8")) <= max_bytes:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while len((last + "…").encode("utf-8")) > max_bytes:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def decode_frame(data: bytes):
    """JPEG/PNG bytes -> RGB pixel array, wholly in memory — or None when the
    bytes aren't an image, are a decompression bomb, or Pillow isn't installed.
    Never touches disk.

    The dimension check reads the header (``Image.open`` is lazy) and refuses an
    over-budget frame BEFORE ``thumbnail()`` forces a full-resolution decode, so a
    crafted small file that declares a huge canvas can never materialise its
    pixels. A bounded semaphore caps concurrent decodes so a burst of authed looks
    can't stack their transient buffers into an OOM."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    if not _decode_sem.acquire(blocking=False):        # all decode slots busy →
        log.warning("[live] decode slots saturated — shedding a frame")
        return None                                    # shed, don't park a worker
    try:
        im = Image.open(io.BytesIO(data))              # lazy — header only
        w, h = im.size
        if w * h > MAX_FRAME_PIXELS:                   # pre-decode bomb guard
            log.warning("[live] frame %dx%d exceeds %d MP — refused "
                        "(decompression-bomb guard)", w, h,
                        MAX_FRAME_PIXELS // (1024 * 1024))
            return None                                # never .thumbnail()/asarray it
        im.thumbnail((_MAX_SIDE, _MAX_SIDE))
        return np.asarray(im.convert("RGB"))
    except Exception:
        return None
    finally:
        _decode_sem.release()


def _clip_bytes(s: str, max_bytes: int = MAX_TEXT_LEN) -> str:
    """Clip one atomic line to the glass's byte budget with an ellipsis mark."""
    if len(s.encode("utf-8")) <= max_bytes:
        return s
    while s and len((s + "…").encode("utf-8")) > max_bytes:
        s = s[:-1]
    return s + "…"


def panel_lines(card: dict) -> list[str]:
    """A World-lens panel card → the exact lines the glass would draw, inside
    the canonical budget (MAX_LINES x MAX_TEXT_LEN bytes). This is THE shared
    formatter: the browser HUD and the phone app's on-glass preview both render
    these bytes, so every surface shows literally the same look.

    Layout mirrors the on-glass ObjectPanelCard: title, then provider rows
    (each an atomic line — a row never word-wraps across lines), then the
    provenance footer (confidence · sources)."""
    lines: list[str] = []
    title = str(card.get("primary") or card.get("label") or "").strip()
    if title:
        lines.append(_clip_bytes(title))
    for r in (card.get("rows") or [])[:MAX_LINES - 2]:
        label = str(r.get("label") or "").strip()
        extra = str(r.get("value") or r.get("detail") or "").strip()
        text = " · ".join(p for p in (label, extra) if p)
        if text:
            lines.append(_clip_bytes(text))
    footer = str(card.get("footer") or "").strip()
    if footer and len(lines) < MAX_LINES:
        lines.append(_clip_bytes(footer))
    return lines[:MAX_LINES]


def _local_look(brain, arr, ledger: bool = True) -> dict:
    """The egress-shielded rung: the in-process classifier ladder only. Runs
    while the wearer's shield is up (incognito) — nothing leaves, nothing is
    written — and as the honest floor when the World lens can't serve.

    ``ledger=False`` additionally suppresses the activity trace for a passive
    continuous-loop (ambient) frame, so the live page's several-a-minute cadence
    never floods the ledger with "saw X" entries."""
    try:
        hit = _classifier()(arr)
    except Exception as exc:                      # a backend blew up mid-frame
        log.warning("[live] vision ladder failed: %s", exc)
        hit = None
    if not hit:
        return {"ok": True, "label": "", "confidence": 0.0, "tier": "laptop",
                "lines": wrap_hud_lines("nothing I recognize yet")}
    label, conf = hit
    # Same confidence floor the world-lens recognizer applies (min_confidence).
    # Without it the floor shows a guess the recognizer would have rejected, and
    # incognito vs. normal disagree on the identical frame (refute 2026-07-20).
    if float(conf) < _MIN_LOCAL_CONFIDENCE:
        return {"ok": True, "label": "", "confidence": 0.0, "tier": "laptop",
                "lines": wrap_hud_lines("nothing I recognize yet")}
    # Never identify a person on the glass. The Live Lens is its OWN hot path: it
    # renders the classifier label directly and does not pass through
    # ObjectRecognizer.recognize()/world_lens, so it must apply the same layered
    # person defence here — else a YOLO "person" (COCO class 0) or a VLM-emitted
    # name walks straight onto the HUD and into the activity ledger (refute
    # 2026-07-18, a sibling call-site the object-lens guard never reached). The
    # frame is in hand, so the optional visual layer runs too. Defer BEFORE the
    # ledger write so no person observation is recorded either.
    from ...object_lens import person_guard
    if person_guard.defers_person(label, frame=arr):
        return {"ok": True, "label": "", "confidence": 0.0, "tier": "laptop",
                "lines": wrap_hud_lines("a person — the Social Lens handles people")}
    try:                                      # incognito/ambient ⇒ no on-disk trace;
        trace = ledger and not brain.incognito_now()   # unreadable posture ⇒ no trace
    except Exception:
        trace = False
    if trace:
        brain.activity.add("look", f"Live Lens saw {label} ({conf:.0%})")
    return {"ok": True, "label": label, "confidence": round(float(conf), 4),
            "tier": "laptop",
            "lines": wrap_hud_lines(f"{label} · {conf:.0%}")}


def _with_min_panel(out: dict) -> dict:
    """Give a classifier-only result the panel SHAPE (title + provenance, no
    rows) so every surface renders one thing — the phone's panel view and the
    browser's lines stay in lockstep even on the local rung."""
    if out.get("ok") and out.get("label"):
        conf = float(out.get("confidence") or 0.0)
        out["panel"] = {"type": "ObjectPanelCard", "primary": out["label"],
                        "label": out["label"], "confidence": conf, "rows": [],
                        "sources": [], "footer": f"{conf:.0%} · on-device"}
    return out


def world_look(brain, arr, ambient: bool = False) -> dict:
    """One unified Look — the single pipeline behind BOTH the browser's tap and
    the phone app's shutter, so the two surfaces are one thing.

    ``ambient=True`` is a passive continuous-loop frame: it takes the LOCAL rung
    only (no remote vision, no plugins, no ledger trace), so the live page's
    watch-the-world cadence stays private, free, and quiet. A deliberate tap
    (``ambient=False``) runs the full lens.

    Outside the egress shield the full World lens runs: structured recognition
    (VLM when configured, the classifier ladder as its built-in rung), the
    Object Lens, and the wearer's installed plugin providers — a price converts,
    a book rates — returned as the panel PLUS the budget-clamped glass lines
    from :func:`panel_lines`. Inside the shield (incognito: LAN-only /
    quiet-hours) the look stays LOCAL-ONLY via :func:`_local_look` — it still
    works, consults nothing remote, and leaves no trace. A person in frame is
    never panelled in any posture (the recognizer defers to the Social Lens);
    the surface just hears "nothing I recognize"."""
    if arr is None:
        return {"ok": False,
                "reason": "not an image I can decode (the Brain needs Pillow)"}
    try:
        incognito = bool(brain.incognito_now())
    except Exception:
        incognito = True                        # unreadable posture → fail closed to local
    if ambient or incognito:
        # A passive continuous-loop frame (ambient) and a veiled look both stay
        # LOCAL: the on-device classifier answers, nothing egresses. Ambient
        # additionally writes NO ledger trace — a several-a-minute loop must not
        # spam "saw X" or auto-egress a frame to a configured remote VLM. A
        # deliberate tap (not ambient, shield down) escalates to the full lens.
        out = _local_look(brain, arr, ledger=not ambient)
        if incognito:
            out["local_only"] = True            # the shield is up — say so
        return _with_min_panel(out)
    wl = None
    degraded = False        # the smart path ERRORED (vs. legitimately found nothing)
    try:
        wl = brain.world_lens()
    except Exception as exc:
        log.warning("[live] world lens unavailable: %s", exc)
        degraded = True
    panel = None
    if wl is not None:
        try:
            panel = wl.look(arr)
        except Exception as exc:                # a look never dies on a provider
            log.warning("[live] world look failed: %s", exc)
            degraded = True
    if panel is None:
        # The honest floor. Flag WHY only when the smart path actually broke — a
        # plain "nothing recognized" is not a degradation, but a lens/provider
        # crash silently masquerading as the 4-bucket floor is (refute 2026-07-20).
        out = _with_min_panel(_local_look(brain, arr))
        if degraded:
            out["degraded"] = True
        return out
    card = panel.to_hud_card()
    label = str(card.get("label") or card.get("primary") or "")
    conf = float(card.get("confidence") or 0.0)
    # provenance: the providers that actually contributed rows (the card keeps
    # them only inside its footer string, so read them off the rows themselves)
    sources = sorted({str(r.get("source") or "").split(" ")[0]
                      for r in (card.get("rows") or []) if r.get("source")})
    brain.activity.add("look", f"Lens saw {label} ({conf:.0%})")
    return {"ok": True, "label": label, "confidence": round(conf, 4),
            "tier": "laptop", "sources": sources,
            "panel": card, "lines": panel_lines(card)}


def look(brain, data: bytes, ambient: bool = False) -> dict:
    """One browser Look: decode the posted frame in memory, run the unified
    pipeline (:func:`world_look`). Frames never touch disk; the wearer's
    egress shield makes the look local-only; a plugin row is built from the
    extracted label/fields, never the pixels. ``ambient`` marks a passive
    continuous-loop frame (local-only, no ledger, no egress)."""
    return world_look(brain, decode_frame(data), ambient=ambient)


def render_live(nonce: str = "") -> str:
    """The Live Lens page. Served PUBLIC (like the builder) because it holds no
    secrets: the token arrives in the URL fragment from the panel's link/QR and
    is kept in sessionStorage client-side, never embedded here.

    ``nonce`` stamps the sole inline <style> and <script> so a strict
    Content-Security-Policy (script-src 'nonce-…', no 'unsafe-inline') can serve
    THIS page's inline code while blocking any injected <script>/<img onerror>
    from executing — the defence-in-depth backstop the page lacked entirely
    (refute 2026-07-18). Empty nonce ⇒ bare tags (the CSP-less test/dev shape)."""
    boot = {"maxLines": MAX_LINES, "maxTextLen": MAX_TEXT_LEN}
    attr = f' nonce="{nonce}"' if nonce else ""
    return (_PAGE
            .replace("__BOOT__", json.dumps(boot))
            .replace("__NONCE__", attr))


# One inline page, zero external fetches (the CSP-of-necessity for a LAN
# appliance). Phosphor-dark like the simulator and the terminal — a screen is
# allowed to be dark; the HUD circle is the one bright thing, exactly like the
# glass. A RAW string so the inline JS reads naturally (single backslashes are
# preserved verbatim into the served script). __BOOT__/__NONCE__ are filled by
# render_live(); raw braces below are CSS/JS.
_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>DreamLayer &middot; Live Lens</title>
<style__NONCE__>
  :root{
    --phos:#7DFFA8; --phos-dim:#3F8F5C; --amber:#FFC46B; --bg:#050807;
    --plate:rgba(5,10,8,.72); --lens: min(80vmin, 560px);
  }
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  html,body{height:100dvh;min-height:100%;background:var(--bg);overflow:hidden;
    font:14px/1.45 ui-monospace,Menlo,Consolas,monospace;color:var(--phos)}
  video{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;
    filter:saturate(.9) brightness(.94)}
  /* the on-device detector paints boxes here, over the video, under the chrome */
  #overlay{position:fixed;inset:0;width:100%;height:100%;pointer-events:none}
  /* the world dims beyond the lens — attention lives in the circle */
  #veilshade{position:fixed;inset:0;pointer-events:none;
    background:radial-gradient(circle calc(var(--lens)/2) at 50% 46%,
      rgba(5,8,7,0) 60%, rgba(5,8,7,.66) 100%);}
  #lens{position:fixed;left:50%;top:46%;width:var(--lens);height:var(--lens);
    transform:translate(-50%,-50%);border-radius:50%;cursor:pointer;
    border:1px solid rgba(125,255,168,.5);
    box-shadow:0 0 44px rgba(125,255,168,.16), inset 0 0 60px rgba(125,255,168,.05);
    display:flex;align-items:center;justify-content:center;text-align:center;
    transition:box-shadow .3s}
  #lens:active{box-shadow:0 0 60px rgba(125,255,168,.3), inset 0 0 60px rgba(125,255,168,.1)}
  /* a sweeping ring while a look is in flight — the "it's thinking" tell */
  #lens.scan{animation:pulse 1.1s ease-in-out infinite}
  @keyframes pulse{0%,100%{box-shadow:0 0 40px rgba(125,255,168,.14),inset 0 0 60px rgba(125,255,168,.05)}
    50%{box-shadow:0 0 72px rgba(125,255,168,.42),inset 0 0 70px rgba(125,255,168,.12)}}
  #hud{white-space:pre;letter-spacing:.05em;font-size:clamp(13px,2.6vmin,19px);
    text-shadow:0 0 10px rgba(125,255,168,.6);opacity:0;transition:opacity .28s;
    max-width:82%;padding:10px 14px;border-radius:10px;background:var(--plate);
    backdrop-filter:blur(3px)}
  #hud:empty{padding:0;background:none}
  #hud.on{opacity:1}
  #hint{position:fixed;left:50%;top:calc(46% + var(--lens)/2 + 14px);
    transform:translateX(-50%);color:var(--phos-dim);font-size:12px;
    letter-spacing:.1em;text-transform:uppercase;transition:opacity .3s;text-align:center}
  /* the rich object panel — provider rows the glass would draw */
  #panel{position:fixed;left:50%;bottom:calc(env(safe-area-inset-bottom,0px) + 92px);
    transform:translateX(-50%);width:min(88vw,440px);opacity:0;pointer-events:none;
    transition:opacity .3s;background:var(--plate);border:1px solid rgba(125,255,168,.28);
    border-radius:12px;padding:12px 14px;backdrop-filter:blur(4px)}
  #panel.on{opacity:1}
  #panel .ptitle{font-size:15px;color:var(--phos);letter-spacing:.02em;margin-bottom:6px}
  #panel .prow{display:flex;justify-content:space-between;gap:10px;font-size:13px;
    color:#DDEFE4;padding:3px 0;border-top:1px solid rgba(125,255,168,.1)}
  #panel .prow .psrc{color:var(--phos-dim);font-size:11px;text-transform:uppercase;
    letter-spacing:.08em;white-space:nowrap}
  #panel .pfoot{margin-top:6px;color:var(--phos-dim);font-size:11px;letter-spacing:.06em}
  /* status chips */
  #chips{position:fixed;top:calc(env(safe-area-inset-top,0px) + 10px);left:0;right:0;
    display:flex;justify-content:center;gap:8px;flex-wrap:wrap;padding:0 10px}
  .chip{border:1px solid rgba(125,255,168,.35);border-radius:3px;padding:3px 9px;
    font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--phos-dim);
    background:rgba(5,8,7,.6);backdrop-filter:blur(2px);cursor:default}
  .chip b{color:var(--phos);font-weight:normal}
  .chip.warn{color:var(--amber);border-color:rgba(255,196,107,.45)}
  #veilbtn,#livebtn{cursor:pointer;user-select:none}
  #veilbtn.on{color:var(--amber);border-color:rgba(255,196,107,.6)}
  #livebtn.on b{color:var(--phos)}
  /* right-edge camera controls: torch + zoom (shown only when supported) */
  #controls{position:fixed;right:calc(env(safe-area-inset-right,0px) + 10px);top:50%;
    transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;align-items:center}
  #controls button{width:46px;height:46px;border-radius:50%;font-size:18px;
    background:rgba(5,8,7,.66);border:1px solid rgba(125,255,168,.4);color:var(--phos);
    backdrop-filter:blur(2px);display:flex;align-items:center;justify-content:center;cursor:pointer}
  #controls button[aria-pressed="true"]{color:var(--amber);border-color:var(--amber)}
  #zoomwrap{display:flex;flex-direction:column;gap:6px;align-items:center}
  /* ask bar */
  #bar{position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;
    padding:10px 12px calc(env(safe-area-inset-bottom,0px) + 12px);
    background:linear-gradient(transparent, rgba(5,8,7,.9) 42%)}
  #q{flex:1;background:rgba(5,8,7,.82);border:1px solid rgba(125,255,168,.4);
    border-radius:3px;color:var(--phos);padding:11px 12px;font:inherit;min-width:0}
  #q::placeholder{color:var(--phos-dim)}
  #q:focus{outline:none;border-color:var(--phos)}
  button{background:rgba(5,8,7,.8);border:1px solid rgba(125,255,168,.5);
    border-radius:3px;color:var(--phos);font:inherit;padding:11px 14px;cursor:pointer}
  button:active{background:rgba(125,255,168,.15)}
  #mic[aria-pressed="true"]{color:var(--amber);border-color:var(--amber)}
  /* full-screen notices (no camera / no token / no link) */
  .notice{position:fixed;left:50%;top:46%;transform:translate(-50%,-50%);
    width:min(86vw,420px);border:1px solid rgba(255,196,107,.5);border-radius:4px;
    background:rgba(5,8,7,.94);color:var(--amber);padding:16px 18px;font-size:13px;z-index:9}
  .notice h2{font-size:13px;letter-spacing:.14em;margin-bottom:8px}
  .notice p{color:#CDBB96;margin-top:6px}
  .notice code{color:var(--phos)}
  .notice .act{margin-top:12px;display:flex;gap:8px}
  .notice .act button{font:12px inherit;letter-spacing:.06em;padding:8px 14px;border-radius:4px}
  .codein{display:flex;gap:8px;margin-top:8px}
  .codein input{flex:1;min-width:0;font:18px ui-monospace,Menlo,monospace;letter-spacing:3px;
    text-align:center;padding:8px;border:1px solid var(--phos-dim);border-radius:4px;
    background:#05100D;color:var(--phos)}
  .codein button{font:13px inherit;letter-spacing:.06em;padding:0 14px;border-radius:4px;
    border:1px solid var(--phos);background:transparent;color:var(--phos);cursor:pointer}
  .pairmsg{min-height:1.1em;color:var(--amber)}
  #privacy{position:fixed;bottom:calc(env(safe-area-inset-bottom,0px) + 66px);
    left:0;right:0;text-align:center;color:var(--phos-dim);font-size:10.5px;
    letter-spacing:.06em;padding:0 16px;pointer-events:none}
  @media (prefers-reduced-motion: reduce){ #hud,#panel{transition:none} #lens.scan{animation:none} }
</style>
</head>
<body>
<video id="cam" autoplay playsinline muted></video>
<canvas id="overlay" aria-hidden="true"></canvas>
<div id="veilshade"></div>
<div id="lens" role="button" aria-label="Look — recognize what the camera sees" tabindex="0">
  <div id="hud" aria-live="polite"></div>
</div>
<div id="hint">tap the lens to look</div>
<div id="panel" aria-live="polite"></div>
<div id="chips">
  <span class="chip" id="link">&#9679; <b id="linkst">linking&hellip;</b></span>
  <span class="chip" id="tier" hidden><b id="tiertx"></b></span>
  <span class="chip on" id="livebtn" role="switch" aria-checked="true" tabindex="0">&#9673; <b id="livest">live</b></span>
  <span class="chip" id="veilbtn" role="switch" aria-checked="false" tabindex="0">veil <b id="veilst">off</b></span>
</div>
<div id="controls">
  <button id="torch" type="button" hidden aria-pressed="false" aria-label="Flashlight" title="Flashlight">&#128161;</button>
  <div id="zoomwrap" hidden>
    <button id="zoomin" type="button" aria-label="Zoom in" title="Zoom in">+</button>
    <button id="zoomout" type="button" aria-label="Zoom out" title="Zoom out">&minus;</button>
  </div>
</div>
<div id="bar">
  <input id="q" type="text" autocomplete="off" enterkeyhint="send"
         placeholder="ask your memory&hellip;" aria-label="Ask your Brain">
  <button id="mic" hidden aria-pressed="false"
          title="Voice uses your phone's speech service, not the Brain's on-device ASR">&#127908;</button>
  <button id="send" aria-label="Send">ask</button>
</div>
<div id="privacy">camera &rarr; your Brain on your LAN &middot; frames are never stored &middot; plugin rows see the label, never the pixels</div>
<script__NONCE__>
"use strict";
const BOOT = __BOOT__;
const LOOP_MS = 1600;               /* continuous-look cadence (Brain round-trip) */

/* ---- credential: URL fragment -> sessionStorage, then scrubbed ---------- */
let TOKEN = sessionStorage.getItem("dl-live-token") || "";
if (location.hash.startsWith("#t=")) {
  TOKEN = decodeURIComponent(location.hash.slice(3));
  sessionStorage.setItem("dl-live-token", TOKEN);
  history.replaceState(null, "", location.pathname);   /* never re-shared */
}
const HDRS = () => TOKEN ? {"X-DreamLayer-Token": TOKEN} : {};

const $ = id => document.getElementById(id);
let veil = false, liveOn = true, camOK = false, looking = false;
let track = null, caps = {}, zoom = 1, torchOn = false;

/* ---- HUD: one thought at a time, the glass's budget --------------------- */
const enc = new TextEncoder();
function wrapLines(text){
  const out = []; let cur = "";
  for (let w of (text||"").split(/\s+/).filter(Boolean)) {
    while (enc.encode(w).length > BOOT.maxTextLen) {
      if (cur) { out.push(cur); cur = ""; }
      let head = w;
      while (enc.encode(head).length > BOOT.maxTextLen) head = head.slice(0, -1);
      out.push(head); w = w.slice(head.length);
    }
    const trial = (cur + " " + w).trim();
    if (enc.encode(trial).length <= BOOT.maxTextLen) cur = trial;
    else { out.push(cur); cur = w; }
  }
  if (cur) out.push(cur);
  if (out.length > BOOT.maxLines) {
    out.length = BOOT.maxLines;
    let last = out[BOOT.maxLines-1];
    while (enc.encode(last + "…").length > BOOT.maxTextLen) last = last.slice(0,-1);
    out[BOOT.maxLines-1] = last + "…";
  }
  return out;
}
let hudTimer = null;
function showHud(lines, o){
  o = o || {};
  const hud = $("hud");
  hud.textContent = (Array.isArray(lines) ? lines : wrapLines(lines)).join("\n");
  hud.classList.add("on");
  clearTimeout(hudTimer);
  if (!o.persist) hudTimer = setTimeout(() => hud.classList.remove("on"), o.ms || 6000);
}
function scan(on){ $("lens").classList.toggle("scan", !!on); }

/* a quiet synthesized hark — no assets, no autoplay (first sound follows a tap) */
let actx = null;
function blip(){
  try {
    actx = actx || new (window.AudioContext||window.webkitAudioContext)();
    if (actx.state === "suspended") actx.resume();
    const o = actx.createOscillator(), g = actx.createGain();
    o.frequency.value = 880; g.gain.value = 0.04;
    o.connect(g); g.connect(actx.destination);
    o.start(); o.stop(actx.currentTime + 0.06);
  } catch (e) { /* silence is fine */ }
}

/* ---- the rich object panel (provider rows), built with textContent (XSS-safe) */
function renderPanel(panel){
  const el = $("panel");
  const rows = panel && Array.isArray(panel.rows) ? panel.rows : [];
  if (!panel || !rows.length) { el.classList.remove("on"); el.textContent = ""; return; }
  el.textContent = "";
  const title = String(panel.primary || panel.label || "").trim();
  if (title) { const t = document.createElement("div"); t.className = "ptitle"; t.textContent = title; el.appendChild(t); }
  for (const r of rows.slice(0, 4)) {
    const row = document.createElement("div"); row.className = "prow";
    const lbl = document.createElement("span");
    lbl.textContent = String(r.label || r.value || r.detail || "").trim();
    if (!lbl.textContent) continue;
    row.appendChild(lbl);
    const src = String(r.source || "").split(" ")[0];
    if (src) { const s = document.createElement("span"); s.className = "psrc"; s.textContent = src; row.appendChild(s); }
    el.appendChild(row);
  }
  const foot = String(panel.footer || "").trim();
  if (foot) { const f = document.createElement("div"); f.className = "pfoot"; f.textContent = foot; el.appendChild(f); }
  el.classList.add("on");
}

/* ---- link + tier chips -------------------------------------------------- */
function setLink(ok, ms){
  $("linkst").textContent = ok ? ("brain " + (ms|0) + "ms") : "no link";
  $("link").classList.toggle("warn", !ok);
}
function setTier(t){
  const tx = t === "cloud" ? "cloud" : "on-device";
  $("tiertx").textContent = tx;
  $("tier").hidden = false;
  $("tier").classList.toggle("warn", t === "cloud");
}

/* ---- veil: the wearer's posture, mirrored here -------------------------- */
function setVeil(on, o){
  o = o || {};
  veil = on;
  $("veilst").textContent = on ? "on" : "off";
  $("veilbtn").classList.toggle("on", on);
  $("veilbtn").setAttribute("aria-checked", String(on));
  if (on) { renderPanel(null); }
  if (!o.silent) showHud(on ? "veil down · on-device only" : "veil lifted", {ms:2400});
  if (!on && liveOn) scheduleLoop(500);
}
$("veilbtn").onclick = () => setVeil(!veil);
$("veilbtn").onkeydown = e => { if (e.key===" "||e.key==="Enter") setVeil(!veil); };

/* ---- live mode: continuous recognition, the glasses default ------------- */
function setLive(on){
  liveOn = on;
  $("livebtn").classList.toggle("on", on);
  $("livebtn").setAttribute("aria-checked", String(on));
  $("livest").textContent = on ? "live" : "tap";
  $("hint").textContent = on ? "watching · tap for a closer look" : "tap the lens to look";
  if (on) { scheduleLoop(400); }
  else { clearTimeout(loopTimer); }
}
$("livebtn").onclick = () => setLive(!liveOn);
$("livebtn").onkeydown = e => { if (e.key===" "||e.key==="Enter") setLive(!liveOn); };

/* ---- camera ------------------------------------------------------------- */
function notice(title, html, actions){
  const n = document.createElement("div");
  n.className = "notice";
  const h = document.createElement("h2"); h.textContent = title; n.appendChild(h);
  const body = document.createElement("div"); body.innerHTML = html; n.appendChild(body);
  if (actions && actions.length) {
    const bar = document.createElement("div"); bar.className = "act";
    for (const a of actions) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = a.label;
      b.onclick = (ev) => { ev.stopPropagation(); a.fn(n); };
      bar.appendChild(b);
    }
    n.appendChild(bar);
  } else {
    n.onclick = () => n.remove();
  }
  document.body.appendChild(n);
  return n;
}
async function startCam(){
  if (!window.isSecureContext) {
    notice("CAMERA NEEDS THE SECURE LINK",
      "<p>Browsers only open cameras on a secure page. Start the Brain with <code>--tls</code> and scan the <b>https</b> QR from the panel (accept the one-time certificate warning &mdash; it is your own Brain's).</p><p>Asking works right here meanwhile.</p>");
    return;
  }
  try {
    const s = await navigator.mediaDevices.getUserMedia(
      {video: {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}, audio: false});
    const v = $("cam");
    v.srcObject = s;
    try { await v.play(); } catch (e) { /* autoplay policies — muted+playsinline usually covers it */ }
    await new Promise(res => {
      if (v.readyState >= 2 && v.videoWidth) return res();
      v.addEventListener("loadedmetadata", () => res(), {once:true});
      setTimeout(res, 3000);                 /* never hang the boot on a slow camera */
    });
    camOK = true;
    initControls();
    if (liveOn) scheduleLoop(500);
  } catch (e) {
    notice("CAMERA DECLINED",
      "<p>Grant camera access to look at the world. Asking still works below.</p>",
      [{label:"Try again", fn:(n)=>{ n.remove(); startCam(); }}]);
  }
}

function initControls(){
  try {
    const s = $("cam").srcObject;
    track = s && s.getVideoTracks ? s.getVideoTracks()[0] : null;
    caps = (track && track.getCapabilities) ? (track.getCapabilities() || {}) : {};
    if (caps.torch) $("torch").hidden = false;
    if (caps.zoom) {
      $("zoomwrap").hidden = false;
      const st = track.getSettings ? track.getSettings() : {};
      zoom = st.zoom || caps.zoom.min || 1;
    }
  } catch (e) { /* controls are best-effort */ }
}
function setZoom(z){
  if (!caps.zoom || !track) return;
  zoom = Math.max(caps.zoom.min, Math.min(caps.zoom.max, z));
  track.applyConstraints({advanced:[{zoom: zoom}]}).catch(()=>{});
}
function zoomStep(){ return caps.zoom ? (caps.zoom.max - caps.zoom.min) / 10 : 0; }
$("zoomin").onclick = () => setZoom(zoom + zoomStep());
$("zoomout").onclick = () => setZoom(zoom - zoomStep());
$("torch").onclick = async () => {
  if (!track) return;
  torchOn = !torchOn;
  try { await track.applyConstraints({advanced:[{torch: torchOn}]});
        $("torch").setAttribute("aria-pressed", String(torchOn)); }
  catch (e) { torchOn = !torchOn; }
};
/* pinch-to-zoom */
let pinch0 = null;
function pinchDist(t){ const dx=t[0].clientX-t[1].clientX, dy=t[0].clientY-t[1].clientY; return Math.hypot(dx,dy); }
document.addEventListener("touchmove", e => {
  if (e.touches.length === 2 && caps.zoom) {
    const d = pinchDist(e.touches);
    if (pinch0) setZoom(zoom * (d / pinch0));
    pinch0 = d; e.preventDefault();
  }
}, {passive:false});
document.addEventListener("touchend", () => { pinch0 = null; });

/* ---- capture: the aimed square, at real resolution ---------------------- */
function camReady(){ const v = $("cam"); return camOK && v.readyState >= 2 && v.videoWidth > 0; }
function captureFrame(maxSide){
  const v = $("cam");
  const vw = v.videoWidth, vh = v.videoHeight;
  if (!vw || !vh) return null;
  const side = Math.min(vw, vh);            /* the centered square the lens frames */
  const sx = (vw - side) / 2, sy = (vh - side) / 2;
  const out = Math.min(maxSide || 720, side);
  const c = document.createElement("canvas");
  c.width = out; c.height = out;
  c.getContext("2d").drawImage(v, sx, sy, side, side, 0, 0, out, out);
  return c;
}

/* ---- fetch with a hard timeout (a hung link never wedges the lens) ------- */
async function fetchJSON(url, opts, timeoutMs){
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), timeoutMs || 9000);
  try {
    const r = await fetch(url, Object.assign({signal: ctrl.signal}, opts));
    let j = {}; try { j = await r.json(); } catch (_) {}
    return {ok: r.ok, status: r.status, json: j};
  } finally { clearTimeout(to); }
}

/* ---- look: frame -> YOUR brain -> label (never during the veil) --------- */
let noHitStreak = 0;
function renderResult(j, auto){
  if (!j || j.ok === false) {
    if (!auto) showHud(j && j.reason ? j.reason : "look failed", {ms:3000});
    return;
  }
  if (j.label) {
    noHitStreak = 0;
    showHud(j.lines && j.lines.length ? j.lines : wrapLines(j.label), {persist: liveOn});
    setTier(j.tier || "laptop");
    renderPanel(j.panel);
    if (!auto) blip();
  } else {
    noHitStreak++;
    renderPanel(null);
    if (j.degraded && !auto) { showHud("smart lens hiccuped · retrying", {ms:2600}); return; }
    if (!auto) showHud("point at an object · move closer", {ms:3000});
    else if (noHitStreak >= 4) { showHud("looking for something to recognize…", {ms:2400}); noHitStreak = 0; }
  }
}
async function lookNow(auto){
  if (veil) { if (!auto) showHud("the veil is down", {ms:2200}); return; }
  if (!camReady()) { if (!auto) showHud("camera not ready…", {ms:1800}); return; }
  if (looking) return;
  looking = true; scan(true);
  if (!auto) showHud("looking…", {persist:true});
  try {
    const c = captureFrame(720);
    if (!c) throw new Error("no frame");
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
    if (!blob) throw new Error("no frame");
    const t0 = performance.now();
    /* auto (ambient) frames stay local-only + leave no trace server-side; a
       deliberate tap escalates to the full lens (VLM/plugins/memory/ledger) */
    const url = auto ? "/dreamlayer/live/look?ambient=1" : "/dreamlayer/live/look";
    const rsp = await fetchJSON(url,
      {method: "POST", headers: HDRS(), body: blob}, auto ? 6000 : 9000);
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) { needsPairing(); return; }
    renderResult(rsp.json, auto);
  } catch (e) {
    if (e && e.name === "AbortError") { if (!auto) showHud("timed out · try again", {ms:2600}); }
    else { setLink(false, 0); if (!auto) showHud("brain unreachable", {ms:3000}); }
  } finally { looking = false; scan(false); }
}
$("lens").onclick = () => lookNow(false);
$("lens").onkeydown = e => { if (e.key===" "||e.key==="Enter") lookNow(false); };

/* ---- the continuous live loop (the glasses never wait for a tap) -------- */
let loopTimer = null, booted = false;
function scheduleLoop(delay){
  clearTimeout(loopTimer);
  /* don't run while: paused, unpaired (behind the pairing modal — else we burn
     camera+network 401ing every tick), backgrounded (battery), or before the
     boot posture-seed lands (so the FIRST look already knows the veil) */
  if (!liveOn || _pairNotice || document.hidden || !booted) return;
  loopTimer = setTimeout(loopTick, delay || LOOP_MS);
}
async function loopTick(){
  if (liveOn && !veil && !document.hidden && camReady() && !looking) {
    await lookNow(true);
  }
  scheduleLoop();
}

/* ---- ask: the production route, the wearer's posture attached ----------- */
let asking = false;
async function ask(){
  const q = $("q").value.trim();
  if (!q || asking) return;
  asking = true;
  $("q").value = "";
  showHud("thinking…", {persist:true});
  try {
    const t0 = performance.now();
    const rsp = await fetchJSON("/dreamlayer/brain/ask", {
      method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
      body: JSON.stringify({query: q, no_cloud: veil})}, 20000);
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) { needsPairing(); return; }
    const j = rsp.json;
    if (j.text) { showHud(j.text, {ms:9000}); setTier(j.tier); }
    else showHud(veil ? "nothing on-device" : "no answer", {ms:4000});
  } catch (e) {
    if (e && e.name === "AbortError") showHud("timed out · try again", {ms:2600});
    else { setLink(false, 0); showHud("brain unreachable", {ms:4000}); }
  } finally { asking = false; }
}
$("send").onclick = ask;
$("q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });

let _pairNotice = null;
function needsPairing(){
  if (_pairNotice) return;                         /* don't stack notices */
  $("hud").classList.remove("on");                 /* drop any stuck "looking…" */
  const n = document.createElement("div");
  n.className = "notice";
  n.innerHTML =
    "<h2>CONNECT THIS PHONE</h2>"+
    "<p>This page opened <b>without its pairing token</b>, so the Brain won't answer yet. "+
    "The easiest way is to <b>point your phone camera at the QR</b> on the panel "+
    "(<b>Connections &rarr; Live Lens</b>) &mdash; it carries the token for you.</p>"+
    "<p>Can't scan? Type the short code shown next to the QR:</p>"+
    "<div class=\"codein\"><input id=\"pairCode\" inputmode=\"numeric\" autocomplete=\"one-time-code\" "+
      "pattern=\"[0-9]*\" maxlength=\"8\" placeholder=\"8-digit code\" aria-label=\"Pairing code\">"+
      "<button id=\"pairGo\" type=\"button\">Connect</button></div>"+
    "<p id=\"pairMsg\" class=\"pairmsg\"></p>";
  n.onclick = e => { if (e.target === n) { n.remove(); _pairNotice = null; } };
  document.body.appendChild(n);
  _pairNotice = n;
  const input = n.querySelector("#pairCode");
  const go = n.querySelector("#pairGo");
  const submit = () => redeemCode(input.value, n);
  go.onclick = submit;
  input.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
  input.focus();
}

/* Exchange the short code for the token, then we're paired — same end state as
   scanning the QR (token in sessionStorage). */
async function redeemCode(raw, noticeEl){
  const code = (raw || "").replace(/\D/g, "");
  const msg = noticeEl.querySelector("#pairMsg");
  if (code.length < 8) { msg.textContent = "Enter the 8-digit code from the panel."; return; }
  msg.textContent = "connecting…";
  try {
    const rsp = await fetch("/dreamlayer/live/redeem",
      {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
    const j = await rsp.json();
    if (rsp.ok && j.token) {
      TOKEN = j.token;
      sessionStorage.setItem("dl-live-token", TOKEN);
      noticeEl.remove(); _pairNotice = null;
      showHud("connected · tap the lens", {ms:3000});
      setLink(true, 0);
      if (liveOn) scheduleLoop(600);
      return;
    }
    msg.textContent = rsp.status === 429
      ? "too many tries — wait a minute, then a fresh code from the panel"
      : "wrong or expired code — get a fresh one from the panel";
  } catch (e) { msg.textContent = "brain unreachable"; }
}

/* ---- optional voice: honest about whose ears these are ------------------ */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  $("mic").hidden = false;
  let rec = null;
  $("mic").onclick = () => {
    if (rec) { rec.stop(); return; }
    rec = new SR(); rec.lang = navigator.language || "en-US";
    $("mic").setAttribute("aria-pressed", "true");
    showHud("listening (phone speech service)", {ms:3200});
    rec.onresult = e => { $("q").value = e.results[0][0].transcript; ask(); };
    rec.onend = () => { $("mic").setAttribute("aria-pressed", "false"); rec = null; };
    rec.start();
  };
}

/* ---- backgrounding: stop looking, save battery, resume clean ------------ */
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(loopTimer);
    try { if (actx && actx.state === "running") actx.suspend(); } catch (e) {}
  } else {
    try { $("cam").play(); } catch (e) {}
    if (liveOn && camOK) scheduleLoop(700);
  }
});

/* ---- link heartbeat: the chip self-heals when the Brain comes back ------- */
function heartbeat(){
  setTimeout(async () => {
    if (!document.hidden && !looking) {
      try {
        const t0 = performance.now();
        const r = await fetch("/dreamlayer/status", {headers: HDRS()});
        setLink(r.ok, performance.now() - t0);
      } catch (e) { setLink(false, 0); }
    }
    heartbeat();
  }, 10000);
}

/* ---- boot --------------------------------------------------------------- */
setLive(true);
startCam();
(async () => {                                    /* first link check + posture seed */
  try {
    const t0 = performance.now();
    const rsp = await fetchJSON("/dreamlayer/status", {headers: HDRS()}, 8000);
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) { needsPairing(); }
    else if (rsp.json && rsp.json.incognito) { setVeil(true, {silent:true}); }
  } catch (e) {
    setLink(false, 0);
    if (!TOKEN) { needsPairing(); }
    else notice("CAN'T REACH YOUR BRAIN",
      "<p>This phone is paired, but your Brain isn't answering. Check that <b>this phone and the Brain are on the same Wi‑Fi</b>, and that the Brain (the Mac app) is awake.</p><p>This clears itself the moment the link is back.</p>",
      [{label:"Retry now", fn:(n)=>{ n.remove(); location.reload(); }}]);
  }
  booted = true;                 /* posture known → the loop may start (or stay
                                    paused if unpaired / veiled / hidden) */
  scheduleLoop(400);
  heartbeat();
})();
</script>
</body>
</html>
"""
