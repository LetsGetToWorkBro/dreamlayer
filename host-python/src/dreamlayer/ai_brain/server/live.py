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


def world_look(brain, arr, ambient: bool = False,
               lens: str = "", lens_args: "dict | None" = None,
               scene: str = "") -> dict:
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
    if lens and not ambient:
        # A deliberate "look closer" through ONE named frontier lens (read math,
        # read a document, sense depth, find a named thing, segment, name the
        # sky, dream-stylize). These live on WorldLensHost.look_lens, are all
        # on-device, and self-describe when their pack isn't installed. Veil is
        # enforced inside look_lens (a veiled look is blind). A frontier lens is
        # a DELIBERATE tap only — an ambient (passive-loop) frame ignores it, so
        # the several-a-minute loop never runs a heavy lens or writes a trace.
        try:
            wl = brain.world_lens()
        except Exception as exc:                    # noqa: BLE001
            log.warning("[live] world lens unavailable for lens %s: %s", lens, exc)
            wl = None
        if wl is None:
            return {"ok": False, "lens": lens, "reason": "lens unavailable"}
        # A pick that came from the glance chooser carries the scene it was
        # offered for — teach the arbiter this choice so tomorrow's ambiguous
        # glance leans your way ("it learns you"). Best-effort, and ONLY for a
        # genuine chooser pick: a lens the chooser actually posts (doc/math →
        # the read/math candidates), and NEVER under the veil — the shield writes
        # nothing to disk, priors included. Any other ?lens=…&scene=… is ignored,
        # so a crafted request can't bloat the priors file or write while blinded.
        try:
            from .glance_live import TEACH_LENS
        except Exception:                           # noqa: BLE001
            TEACH_LENS = {}
        if scene and lens in TEACH_LENS and getattr(wl, "glance_arbiter", None) is not None:
            try:
                may_learn = bool(wl.privacy.allow_capture())
            except Exception:                       # noqa: BLE001
                may_learn = False                   # unreadable posture → fail closed
            if may_learn:
                try:
                    wl.glance_arbiter.reinforce(scene, TEACH_LENS[lens])
                except Exception:                   # noqa: BLE001
                    pass
        res = wl.look_lens(arr, lens, lens_args)
        if isinstance(res, dict) and res.get("ok"):
            brain.activity.add("look", f"Looked closer with the {lens} lens")
        return res if isinstance(res, dict) else {"ok": False, "lens": lens}
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
    # Auto lens selection: on a deliberate tap (shield down) the glance arbiter
    # decides the lens from what's in view — you never pick a mode. It fires the
    # clear winner, or offers a one-tap chooser when it's genuinely ambiguous
    # (text that could be read OR solved). "object"/veiled/none hands back to the
    # object-recognition floor below, which keeps all its behaviour.
    if wl is not None:
        try:
            g = wl.glance(arr)
        except Exception as exc:                # noqa: BLE001 — never break a look
            log.warning("[live] glance failed: %s", exc)
            g = None
        if isinstance(g, dict) and g.get("kind") == "offer":
            brain.activity.add("look", "Offered a lens choice")
            return {"ok": True, "glance": "offer", "scene": g.get("scene"),
                    "card": g.get("card")}
        if isinstance(g, dict) and g.get("kind") == "fire":
            brain.activity.add("look", f"Auto lens · {g.get('lens')}")
            return {"ok": True, "glance": "fire", "lens": g.get("lens"),
                    "card": g.get("card"), "action": g.get("action")}
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


def look(brain, data: bytes, ambient: bool = False,
         lens: str = "", lens_args: "dict | None" = None, scene: str = "") -> dict:
    """One browser Look: decode the posted frame in memory, run the unified
    pipeline (:func:`world_look`). Frames never touch disk; the wearer's
    egress shield makes the look local-only; a plugin row is built from the
    extracted label/fields, never the pixels. ``ambient`` marks a passive
    continuous-loop frame (local-only, no ledger, no egress). ``lens`` routes
    the frame through a single named frontier lens (math/doc/depth/find/
    segment/sky/dream) instead of object recognition."""
    return world_look(brain, decode_frame(data), ambient=ambient,
                      lens=lens, lens_args=lens_args, scene=scene)


# The phone as the live mic: it streams raw mono Int16 PCM chunks (already
# downsampled to 16 kHz in the browser) and the Brain transcribes them on-device.
MAX_AUDIO_BYTES = 2_000_000          # ~1 MB is ~30 s of 16k int16; a chunk is <1 s


def decode_audio(body: bytes, src_rate: int = 0):
    """Decode a streamed chunk of little-endian mono Int16 PCM into float samples
    at :data:`capture.SAMPLE_RATE`. The browser normally sends 16 kHz already;
    if a client's AudioContext ran at another rate (iOS/Android are 44.1/48 kHz)
    it is linearly resampled here. A malformed chunk decodes to [] — dropped,
    never fatal."""
    import array
    import sys
    from ...orchestrator.capture import SAMPLE_RATE
    if not body:
        return []
    a = array.array("h")
    usable = len(body) - (len(body) % 2)         # whole 16-bit samples only
    try:
        a.frombytes(bytes(body[:usable]))
    except Exception:                            # noqa: BLE001
        return []
    if sys.byteorder == "big":                   # the wire is little-endian
        a.byteswap()
    floats = [s / 32768.0 for s in a]
    src = int(src_rate or 0)
    if not floats or src == SAMPLE_RATE or src <= 0:
        return floats            # already 16 kHz / unknown rate → no resample
    if not (4000 <= src <= 192000):
        # An implausible sample rate is dropped, NOT resampled: a tiny src (e.g.
        # ?sr=1) would upsample a ~1M-sample body to billions of samples and OOM
        # the Brain. The plausible-audio band caps the output at ≤ 4× the input.
        return []
    n_out = int(len(floats) * SAMPLE_RATE / src)
    if n_out <= 0:
        return []
    ratio = src / float(SAMPLE_RATE)
    last = len(floats) - 1
    out = []
    for i in range(n_out):                       # linear resample src → 16 kHz
        pos = i * ratio
        i0 = int(pos)
        frac = pos - i0
        i1 = i0 + 1 if i0 < last else last
        out.append(floats[i0] * (1.0 - frac) + floats[i1] * frac)
    return out


def hear(brain, body: bytes, src_rate: int = 0, stop: bool = False) -> dict:
    """The phone-as-live-mic endpoint body: a chunk of on-device Int16 PCM in,
    ear status out. ``stop=True`` ends the phone-fed ear. Every consent/Veil/PII/
    on-device gate lives inside :meth:`Brain.hear_remote` / ``stop_remote_ear`` —
    this is only the decode + resample seam."""
    if stop:
        brain.stop_remote_ear()
        return {"ok": True, "remote_listening": False}
    # Check consent BEFORE doing any decode/resample work: no audio is parsed for
    # an install where the phone mic was never enabled (also blunts the DoS above
    # — nothing is allocated for an un-consented caller). hear_remote re-checks.
    if not getattr(brain.config, "remote_listen_enabled", False):
        return {"ok": False, "reason": "disabled",
                "detail": "turn on Listening on the Live Lens first"}
    pcm = decode_audio(body, src_rate)
    return brain.hear_remote(pcm)


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
            .replace("__JUNO__", _juno_data_uri())
            .replace("__NONCE__", attr))


_JUNO_URI: str = ""


def _juno_data_uri() -> str:
    """Juno's real pixel sprite (server/assets/juno_da_still.png, ~5 KB) as a
    data: URI, so the tour needs no new route and stays same-origin under the
    strict CSP (img-src allows data:). Cached after the first read; absent
    asset → empty src (the tour still runs, text-only)."""
    global _JUNO_URI
    if _JUNO_URI:
        return _JUNO_URI
    try:
        import base64
        from pathlib import Path
        p = Path(__file__).resolve().parent / "assets" / "juno_da_still.png"
        _JUNO_URI = "data:image/png;base64," + base64.b64encode(
            p.read_bytes()).decode()
    except Exception:
        _JUNO_URI = ""
    return _JUNO_URI


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
    /* palette.lua, verbatim — the glasses' teal-on-black system, not a phosphor
       terminal. Teal is the ACCENT (rails, labels, chrome); the answer itself is
       near-white (--ink), exactly the renderer.lua hierarchy. */
    --teal:#2CC79A; --teal-bright:#00FFAA; --teal-dim:#1A7A60;
    --ink:#ECF0F1; --ink2:#A8B8C0; --ghost:#58686F;
    --amber:#FFAA00; --attention:#E06B52; --border:#2A3C44; --bg:#000000;
    --plate:rgba(6,10,11,.72); --lens: min(80vmin, 560px);
  }
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  html,body{height:100dvh;min-height:100%;background:var(--bg);overflow:hidden;
    font:14px/1.45 -apple-system,"SF Pro Text","Helvetica Neue","Segoe UI",system-ui,Roboto,sans-serif;
    color:var(--ink)}
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
    border:1px solid rgba(44,199,154,.5);
    box-shadow:0 0 44px rgba(44,199,154,.16), inset 0 0 60px rgba(44,199,154,.05);
    display:flex;align-items:center;justify-content:center;text-align:center;
    transition:box-shadow .3s}
  #lens:active{box-shadow:0 0 60px rgba(44,199,154,.3), inset 0 0 60px rgba(44,199,154,.1)}
  /* the glass itself: a 256px round display, scaled — the device card renderer
     (renderer.lua) draws HERE, over the camera, inside the circle */
  #glass{position:absolute;inset:0;width:100%;height:100%;border-radius:50%;
    pointer-events:none;opacity:0;transition:opacity .35s}
  #glass.on{opacity:1}
  /* a sweeping ring while a look is in flight — the "it's thinking" tell */
  #lens.scan{animation:pulse 1.1s ease-in-out infinite}
  @keyframes pulse{0%,100%{box-shadow:0 0 40px rgba(44,199,154,.14),inset 0 0 60px rgba(44,199,154,.05)}
    50%{box-shadow:0 0 72px rgba(44,199,154,.42),inset 0 0 70px rgba(44,199,154,.12)}}
  #hud{white-space:pre;letter-spacing:.03em;font-size:clamp(13px,2.6vmin,19px);
    color:var(--ink);text-shadow:0 0 10px rgba(0,255,170,.45);opacity:0;transition:opacity .28s;
    max-width:82%;padding:10px 14px;border-radius:10px;background:var(--plate);
    backdrop-filter:blur(3px)}
  #hud:empty{padding:0;background:none}
  #hud.on{opacity:1}
  #hint{position:fixed;left:50%;top:calc(46% + var(--lens)/2 + 14px);
    transform:translateX(-50%);color:var(--teal-dim);font-size:12px;
    letter-spacing:.1em;text-transform:uppercase;transition:opacity .3s;text-align:center}
  /* the rich object panel — provider rows the glass would draw */
  #panel{position:fixed;left:50%;bottom:calc(env(safe-area-inset-bottom,0px) + 92px);
    transform:translateX(-50%);width:min(88vw,440px);opacity:0;pointer-events:none;
    transition:opacity .3s;background:var(--plate);border:1px solid rgba(44,199,154,.28);
    border-radius:12px;padding:12px 14px;backdrop-filter:blur(4px)}
  #panel.on{opacity:1}
  #panel .ptitle{font-size:15px;color:var(--teal);letter-spacing:.02em;margin-bottom:6px}
  #panel .prow{display:flex;justify-content:space-between;gap:10px;font-size:13px;
    color:#ECF0F1;padding:3px 0;border-top:1px solid rgba(44,199,154,.1)}
  #panel .prow .psrc{color:var(--teal-dim);font-size:11px;text-transform:uppercase;
    letter-spacing:.08em;white-space:nowrap}
  #panel .pfoot{margin-top:6px;color:var(--teal-dim);font-size:11px;letter-spacing:.06em}
  /* status chips */
  #chips{position:fixed;top:calc(env(safe-area-inset-top,0px) + 10px);left:0;right:0;
    display:flex;justify-content:center;gap:8px;flex-wrap:wrap;padding:0 10px}
  .chip{border:1px solid rgba(44,199,154,.35);border-radius:3px;padding:3px 9px;
    font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--teal-dim);
    background:rgba(5,8,7,.6);backdrop-filter:blur(2px);cursor:default}
  .chip b{color:var(--teal);font-weight:normal}
  .chip.warn{color:var(--amber);border-color:rgba(255,196,107,.45)}
  #veilbtn,#livebtn{cursor:pointer;user-select:none}
  #veilbtn.on{color:var(--amber);border-color:rgba(255,196,107,.6)}
  #livebtn.on b{color:var(--teal)}
  /* right-edge camera controls: torch + zoom (shown only when supported) */
  #controls{position:fixed;right:calc(env(safe-area-inset-right,0px) + 10px);top:50%;
    transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;align-items:center}
  #controls button{width:46px;height:46px;border-radius:50%;font-size:18px;
    background:rgba(5,8,7,.66);border:1px solid rgba(44,199,154,.4);color:var(--teal);
    backdrop-filter:blur(2px);display:flex;align-items:center;justify-content:center;cursor:pointer}
  #controls button[aria-pressed="true"]{color:var(--amber);border-color:var(--amber)}
  #zoomwrap{display:flex;flex-direction:column;gap:6px;align-items:center}
  /* ask bar */
  #bar{position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;
    padding:10px 12px calc(env(safe-area-inset-bottom,0px) + 12px);
    background:linear-gradient(transparent, rgba(5,8,7,.9) 42%)}
  #q{flex:1;background:rgba(5,8,7,.82);border:1px solid rgba(44,199,154,.4);
    border-radius:3px;color:var(--teal);padding:11px 12px;font:inherit;min-width:0}
  #q::placeholder{color:var(--teal-dim)}
  #q:focus{outline:none;border-color:var(--teal)}
  button{background:rgba(5,8,7,.8);border:1px solid rgba(44,199,154,.5);
    border-radius:3px;color:var(--teal);font:inherit;padding:11px 14px;cursor:pointer}
  button:active{background:rgba(44,199,154,.15)}
  #mic[aria-pressed="true"]{color:var(--amber);border-color:var(--amber)}
  /* full-screen notices (no camera / no token / no link) */
  .notice{position:fixed;left:50%;top:46%;transform:translate(-50%,-50%);
    width:min(86vw,420px);border:1px solid rgba(255,196,107,.5);border-radius:4px;
    background:rgba(5,8,7,.94);color:var(--amber);padding:16px 18px;font-size:13px;z-index:9}
  .notice h2{font-size:13px;letter-spacing:.14em;margin-bottom:8px}
  .notice p{color:#CDBB96;margin-top:6px}
  .notice code{color:var(--teal)}
  .notice .act{margin-top:12px;display:flex;gap:8px}
  .notice .act button{font:12px inherit;letter-spacing:.06em;padding:8px 14px;border-radius:4px}
  .codein{display:flex;gap:8px;margin-top:8px}
  .codein input{flex:1;min-width:0;font:18px ui-monospace,Menlo,monospace;letter-spacing:3px;
    text-align:center;padding:8px;border:1px solid var(--teal-dim);border-radius:4px;
    background:#0E1416;color:var(--teal)}
  .codein button{font:13px inherit;letter-spacing:.06em;padding:0 14px;border-radius:4px;
    border:1px solid var(--teal);background:transparent;color:var(--teal);cursor:pointer}
  .pairmsg{min-height:1.1em;color:var(--amber)}
  #privacy{position:fixed;bottom:calc(env(safe-area-inset-bottom,0px) + 66px);
    left:0;right:0;text-align:center;color:var(--teal-dim);font-size:10.5px;
    letter-spacing:.06em;padding:0 16px;pointer-events:none;transition:opacity .3s}
  #privacy.hide{opacity:0}
  /* live captions — the room's speech on the glass (the glasses' Live Caption
     feature; here through the phone's own speech service, said plainly) */
  #ccbtn.on{color:var(--amber);border-color:rgba(255,196,107,.6)}
  #captions{position:fixed;left:0;right:0;
    bottom:calc(env(safe-area-inset-bottom,0px) + 60px);
    display:flex;justify-content:center;padding:0 14px;pointer-events:none;
    opacity:0;transition:opacity .3s;z-index:3}
  #captions.on{opacity:1}
  #captions .cc{max-width:min(92vw,560px);background:rgba(6,10,11,.76);
    border-radius:10px;padding:7px 13px;font:15px/1.5 inherit;
    color:var(--ink);text-align:center;backdrop-filter:blur(3px);white-space:pre-wrap}
  #captions .cc .iim{color:var(--teal-dim)}
  #captions .cc .csrc{display:block;font-size:9.5px;color:var(--teal-dim);
    letter-spacing:.11em;text-transform:uppercase;margin-top:4px}
  /* Juno's first-run tour: anchored coach marks over the REAL controls.
     The card owns pointer events; the spotlight ring never does — the lens,
     veil, and ask bar stay clickable throughout (the e2e clicks them). */
  #tour{position:fixed;inset:0;pointer-events:none;z-index:8;opacity:0;transition:opacity .4s}
  #tour.on{opacity:1}
  #tourring{position:fixed;border:2px solid rgba(44,199,154,.85);border-radius:14px;
    pointer-events:none;box-shadow:0 0 0 6000px rgba(3,6,5,.45), 0 0 24px rgba(44,199,154,.5);
    transition:all .35s ease;display:none}
  #tourcard{position:fixed;left:50%;transform:translateX(-50%);
    bottom:calc(env(safe-area-inset-bottom,0px) + 96px);width:min(88vw,420px);
    pointer-events:auto;background:rgba(5,10,8,.94);border:1px solid rgba(44,199,154,.4);
    border-radius:14px;padding:12px 14px;display:flex;gap:12px;align-items:flex-start;
    backdrop-filter:blur(5px)}
  #tourcard img{width:44px;height:44px;image-rendering:pixelated;flex:none;margin-top:2px}
  #tourcard .tourbody{flex:1}
  #tourtext b{color:var(--teal);font-weight:normal;display:block;font-size:13px;
    letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}
  #tourtext{font-size:13px;line-height:1.5;color:#ECF0F1}
  #touracts{display:flex;gap:8px;margin-top:9px}
  #touracts button{padding:6px 14px;border-radius:16px;font-size:12px}
  #touracts .ghost{border-color:rgba(44,199,154,.25);color:var(--teal-dim)}
  /* confluence: the chip lives only in dream mode; the code card is the one
     piece of chrome — the three words two humans speak to each other */
  #confbtn{display:none}
  body[data-dream="on"] #confbtn{display:inline-block}
  #confbtn.on{color:var(--amber);border-color:rgba(255,196,107,.6)}
  #confcard{position:fixed;left:50%;top:24%;transform:translateX(-50%);
    width:min(86vw,360px);z-index:8;background:rgba(5,10,8,.95);
    border:1px solid rgba(44,199,154,.4);border-radius:14px;padding:14px 16px;
    backdrop-filter:blur(5px);display:none}
  #confcard.on{display:block}
  /* the glance chooser — a glass dialog of one-tap lens options */
  #chooser{position:fixed;left:50%;top:calc(46% + var(--lens)/2 + 14px);
    transform:translateX(-50%);z-index:9;width:min(84vw,320px);display:none;
    background:rgba(5,10,8,.86);border:1px solid rgba(44,199,154,.35);
    border-radius:16px;padding:12px;backdrop-filter:blur(6px);text-align:center;
    box-shadow:0 8px 40px rgba(0,0,0,.5),0 0 30px rgba(44,199,154,.12);
    animation:chooserIn .22s ease-out both}
  #chooser.show{display:block}
  @keyframes chooserIn{from{opacity:0;transform:translateX(-50%) translateY(8px)}
    to{opacity:1;transform:translateX(-50%) translateY(0)}}
  #chooserq{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
    color:var(--teal-dim);margin-bottom:9px}
  #chooseropts{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
  .choosebtn{appearance:none;border:1px solid rgba(44,199,154,.45);
    background:rgba(44,199,154,.08);color:#ECF0F1;font-size:13.5px;font-weight:600;
    padding:9px 15px;border-radius:11px;cursor:pointer;transition:transform .1s,background .15s}
  .choosebtn:hover,.choosebtn:focus{background:rgba(44,199,154,.18);transform:translateY(-1px)}
  .choosebtn:active{transform:scale(.96)}
  #confcard h3{font-size:12px;letter-spacing:.14em;color:var(--teal);
    text-transform:uppercase;margin-bottom:8px}
  #confcard p{font-size:12.5px;color:#ECF0F1;line-height:1.5;margin:6px 0}
  #confcard .code{font-size:20px;letter-spacing:2px;color:var(--amber);
    text-align:center;margin:10px 0;user-select:all}
  #confcard input{width:100%;font:15px ui-monospace,Menlo,monospace;
    letter-spacing:1px;text-align:center;padding:9px;border-radius:8px;
    border:1px solid var(--teal-dim);background:#0E1416;color:var(--teal)}
  #confcard .acts{display:flex;gap:8px;margin-top:11px}
  #confcard .acts button{flex:1;padding:8px 0;border-radius:16px;font-size:12px}
  #confmsg{min-height:1.1em;color:var(--amber);font-size:12px;margin-top:6px}
  /* privacy receipt: the tamper-evident ledger, VERIFIED on this phone. The
     card mirrors the confluence card; the verdict rail turns green only when
     THIS browser re-checked the Ed25519 chain and it held. */
  #rcptcard{position:fixed;left:50%;top:16%;transform:translateX(-50%);
    width:min(90vw,400px);max-height:74vh;z-index:8;background:rgba(5,10,8,.96);
    border:1px solid rgba(44,199,154,.4);border-radius:14px;padding:14px 16px;
    backdrop-filter:blur(5px);display:none;flex-direction:column}
  #rcptcard.on{display:flex}
  #rcptcard h3{font-size:12px;letter-spacing:.14em;color:var(--teal);
    text-transform:uppercase;margin-bottom:8px}
  #rcptverdict{border-left:3px solid var(--teal-dim);padding-left:9px;margin:2px 0 8px}
  #rcptverdict.ok{border-left-color:var(--teal)}
  #rcptverdict.bad{border-left-color:var(--amber)}
  #rcpthead{font-size:13px;color:#EAF6EE;line-height:1.4}
  #rcptsub{font-size:11.5px;color:var(--teal-dim);line-height:1.45;margin-top:3px}
  #rcptlist{list-style:none;overflow-y:auto;margin:4px 0 2px;
    border-top:1px solid rgba(42,60,68,.5)}
  #rcptlist li{display:flex;gap:8px;align-items:baseline;padding:6px 0;
    border-bottom:1px solid rgba(42,60,68,.35)}
  #rcptlist li.bad{border-left:2px solid var(--amber);padding-left:7px}
  #rcptlist .rk{font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
    color:var(--teal-dim);flex:none;width:60px}
  #rcptlist .rt{flex:1;min-width:0;font-size:12px;color:#ECF0F1;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #rcptlist .rs{flex:none;font:10px ui-monospace,Menlo,monospace;color:var(--teal-dim)}
  #rcptcard .acts{display:flex;gap:8px;margin-top:10px}
  #rcptcard .acts button{flex:1;padding:8px 0;border-radius:16px;font-size:12px}
  #rcptbtn.on{color:var(--teal);border-color:rgba(44,199,154,.6)}
  /* short viewports (landscape phones, split view): the card moves to the TOP
     so it can never sit over the lens it is pointing at (refute 2026-07-21) */
  @media (max-height: 540px){
    #tourcard{bottom:auto;top:calc(env(safe-area-inset-top,0px) + 56px)}
  }
  #tourdots{color:var(--teal-dim);font-size:11px;margin-left:auto;align-self:center}
  @media (prefers-reduced-motion: reduce){ #hud,#panel,#tour,#tourring{transition:none} #lens.scan,#chooser{animation:none} }
</style>
</head>
<body>
<video id="cam" autoplay playsinline muted></video>
<div id="veilshade"></div>
<canvas id="overlay" aria-hidden="true"></canvas>
<div id="lens" role="button" aria-label="Look — recognize what the camera sees" tabindex="0">
  <canvas id="glass" aria-hidden="true"></canvas>
  <div id="hud" aria-live="polite"></div>
</div>
<div id="hint">tap the lens to look</div>
<div id="panel" aria-live="polite"></div>
<div id="chips">
  <span class="chip" id="link">&#9679; <b id="linkst">linking&hellip;</b></span>
  <span class="chip" id="vision" hidden><b id="visionst"></b></span>
  <span class="chip" id="tier" hidden><b id="tiertx"></b></span>
  <span class="chip on" id="livebtn" role="switch" aria-checked="true" tabindex="0">&#9673; <b id="livest">live</b></span>
  <span class="chip" id="veilbtn" role="switch" aria-checked="false" tabindex="0">veil <b id="veilst">off</b></span>
  <span class="chip" id="confbtn" role="button" tabindex="0" title="Share the sky with someone">entangle</span>
  <span class="chip" id="ccbtn" role="switch" aria-checked="false" tabindex="0" title="Live captions (your phone's speech service)" hidden>CC</span>
  <span class="chip" id="hearbtn" role="switch" aria-checked="false" tabindex="0" title="Let the Brain hear and remember — the phone is the mic, transcribed on-device">&#127908; <b id="hearst">listen</b></span>
  <span class="chip" id="rcptbtn" role="button" tabindex="0" title="Verify the privacy receipt on this phone">&#128274; proof</span>
  <span class="chip" id="tourbtn" role="button" tabindex="0" title="Show the tour again">?</span>
</div>
<div id="chooser" role="dialog" aria-label="Pick a lens">
  <div id="chooserq">What do you want?</div>
  <div id="chooseropts"></div>
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
<div id="confcard" role="dialog" aria-label="Entangle two skies">
  <h3>Confluence</h3>
  <div id="confbody"></div>
  <div id="confmsg"></div>
</div>
<div id="rcptcard" role="dialog" aria-label="Privacy receipt">
  <h3>Privacy receipt</h3>
  <div id="rcptverdict"><div id="rcpthead"></div><div id="rcptsub"></div></div>
  <ul id="rcptlist"></ul>
  <div class="acts">
    <button id="rcptverify" type="button">Re-verify</button>
    <button id="rcptclose" type="button" class="ghost">Close</button>
  </div>
</div>
<div id="tour" aria-live="polite">
  <div id="tourring"></div>
  <div id="tourcard">
    <img id="tourjuno" alt="Juno" src="__JUNO__">
    <div class="tourbody">
      <div id="tourtext"><b>JUNO</b><span id="tourmsg"></span></div>
      <div id="touracts">
        <button id="tournext" type="button">Next</button>
        <button id="tourskip" type="button" class="ghost">Skip</button>
        <span id="tourdots"></span>
      </div>
    </div>
  </div>
</div>
<div id="captions" aria-live="polite"><div class="cc"></div></div>
<div id="privacy">camera &rarr; your Brain on your LAN &middot; frames are never stored &middot; plugin rows see the label, never the pixels</div>
<script__NONCE__>
"use strict";
const BOOT = __BOOT__;
const LOOP_MS = 1600;               /* continuous-look cadence (Brain round-trip) */

/* ---- credential: URL fragment -> sessionStorage, then scrubbed ---------- */
let TOKEN = sessionStorage.getItem("dl-live-token") || "";
let PENDING_CODE = "";
if (location.hash.startsWith("#t=")) {
  TOKEN = decodeURIComponent(location.hash.slice(3));
  sessionStorage.setItem("dl-live-token", TOKEN);
  history.replaceState(null, "", location.pathname);   /* never re-shared */
} else if (location.hash.startsWith("#c=")) {
  /* the panel's QR carries the SHORT pairing code (a far sparser, easier-to-
     scan matrix than the 32-char token); redeemed for the token on boot */
  PENDING_CODE = decodeURIComponent(location.hash.slice(3)).replace(/\D/g, "");
  history.replaceState(null, "", location.pathname);
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
let hudTimer = null, hudHoldUntil = 0, hudIsDetector = false;
function showHud(lines, o){
  o = o || {};
  const hud = $("hud");
  hud.textContent = (Array.isArray(lines) ? lines : wrapLines(lines)).join("\n");
  hud.classList.add("on");
  hudIsDetector = !!o._detector;
  clearTimeout(hudTimer);
  if (!o.persist) hudTimer = setTimeout(() => hud.classList.remove("on"), o.ms || 6000);
  /* a deliberate message (a tap/ask result, a toast) HOLDS the HUD so the live
     on-device label doesn't immediately overwrite it; the detector's own updates
     pass _detector and respect this window */
  if (!o._detector) hudHoldUntil = performance.now() + (o.ms || 6000);
}
function hideDetectorHud(){   /* drop a stale LIVE label when nothing's in view; never a held result */
  if (hudIsDetector) { $("hud").classList.remove("on"); hudIsDetector = false; }
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

/* ---- the glass: the DEVICE card renderer, ported ------------------------
   A recognition on the real glasses is drawn by halo-lua/display/renderer.lua
   as the object-family card (draw_object_recall, "Meridian Solid": the place a
   translucent field of light, the object a diamond jewel with orbit arcs, you
   a dot at the bottom, a gradient trace connecting the two). This is a
   faithful port of that draw — same 256px space, same geometry constants,
   same palette.lua colors, same typography.lua sizes — fed by the SAME
   ObjectPanel the Brain returns, the codebase's four-interpreter pattern
   (figment.js / figment_stage.lua / interpreter.py / stage.rs) applied to the
   card renderer. Nothing here is invented UI: layout renderer.lua:596,
   palette halo-lua/display/palette.lua, type sizes typography.lua. */
const GP = {                      /* palette.lua, verbatim */
  text_primary:"#ECF0F1", text_secondary:"#A8B8C0", text_ghost:"#58686F",
  memory_trace:"#00FFAA", border_subtle:"#2A3C44",
  confidence_low:"#FFAA00", confidence_med:"#00FFAA", confidence_high:"#B8FFE9"
};
const GT = { lg:17, md:13, sm:10 };            /* typography.lua sizes */
let glassTimer = null;
function glassCtx(){
  const cv = $("glass");
  const px = cv.clientWidth * (window.devicePixelRatio || 1);
  if (cv.width !== px) { cv.width = px; cv.height = px; }
  const ctx = cv.getContext("2d");
  const s = px / 256;                          /* the 256px round display, scaled */
  ctx.setTransform(s, 0, 0, s, 0, 0);
  ctx.clearRect(0, 0, 256, 256);
  return ctx;
}
function gtext(ctx, str, cx, y, color, size){
  /* the device face is DejaVuSans-Bold (typography.lua) — a clean weighted sans,
     never a monospace terminal font. Mirror it on the glass card. */
  ctx.font = "600 " + (GT[size || "md"]) + 'px -apple-system,"SF Pro Text","Helvetica Neue",system-ui,sans-serif';
  ctx.fillStyle = color; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(str, cx, y);
}
function garc(ctx, x, y, r, a0, a1, color){    /* device arc(): degrees, 0=east */
  ctx.beginPath();
  ctx.arc(x, y, r, a0 * Math.PI / 180, a1 * Math.PI / 180);
  ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.stroke();
}
function gdiamond(ctx, x, y, d, color){
  ctx.beginPath();
  ctx.moveTo(x, y - d); ctx.lineTo(x + d, y); ctx.lineTo(x, y + d);
  ctx.lineTo(x - d, y); ctx.closePath();
  ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.stroke();
}
function glassClear(){
  clearTimeout(glassTimer);
  $("glass").classList.remove("on");
}
/* draw_object_recall (renderer.lua:596) — geometry verbatim from the device */
function glassObjectCard(card){
  const ctx = glassCtx();
  /* the device's display is DARK with emissive pixels — the card brings its
     own glass, else 1-px strokes wash out over a bright live scene */
  ctx.beginPath(); ctx.arc(128, 128, 128, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(4,8,6,.68)"; ctx.fill();
  const conf = Number(card.confidence || 0);
  const jcol = conf >= 0.75 ? GP.confidence_high
             : conf < 0.40 ? GP.confidence_low : GP.confidence_med;
  /* the place, as a translucent field: MAT.glass_disc(CX,112,62) */
  ctx.beginPath(); ctx.arc(128, 112, 62, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(44,199,154,.07)"; ctx.fill();
  ctx.strokeStyle = "rgba(44,199,154,.22)"; ctx.lineWidth = 1; ctx.stroke();
  /* gradient trace you -> object: grad_bezier(128,192, 168,140, 132,102) */
  const grad = ctx.createLinearGradient(128, 192, 132, 102);
  grad.addColorStop(0, GP.border_subtle); grad.addColorStop(1, GP.memory_trace);
  ctx.beginPath(); ctx.moveTo(128, 192);
  ctx.quadraticCurveTo(168, 140, 132, 102);
  ctx.strokeStyle = grad; ctx.lineWidth = 1.6; ctx.stroke();
  /* the object jewel at (128,88): diamonds jd=9 / di=4 + 3 orbit arcs r=14 */
  ctx.save(); ctx.shadowColor = jcol; ctx.shadowBlur = 7;
  gdiamond(ctx, 128, 88, 9, jcol);
  gdiamond(ctx, 128, 88, 4, GP.memory_trace);
  garc(ctx, 128, 88, 14,   0,  90, jcol);
  garc(ctx, 128, 88, 14, 120, 210, jcol);
  garc(ctx, 128, 88, 14, 240, 330, jcol);
  ctx.restore();
  /* you, at the bottom of the scene: circle(128,198,3) + bloom */
  ctx.save(); ctx.shadowColor = GP.memory_trace; ctx.shadowBlur = 6;
  ctx.beginPath(); ctx.arc(128, 198, 3, 0, 2 * Math.PI);
  ctx.fillStyle = GP.memory_trace; ctx.fill(); ctx.restore();
  /* type: time eyebrow, OBJECT label, hero place, [ detail ] bracket */
  const obj = String(card.label || card.primary || "").toUpperCase();
  const footer = String(card.footer || "");
  gtext(ctx, footer, 128, 50, GP.text_ghost, "sm");
  gtext(ctx, obj, 128, 66, GP.memory_trace, "md");
  /* place: the memory row carries it when the ring knows one ("last at X") */
  const grows = Array.isArray(card.rows) ? card.rows : [];
  const memRow = grows.find(r => String(r.source||"").startsWith("memory"));
  const m = memRow && /last at (.+)$/.exec(String(memRow.detail || memRow.value || ""));
  if (m) gtext(ctx, m[1], 128, 150, GP.text_primary, "lg");
  let detail = String((grows[0] || {}).label || card.detail || "");
  if (detail.length > 18) detail = detail.slice(0, 17) + "…";
  if (detail) gtext(ctx, "[ " + detail + " ]", 128, 176, GP.text_secondary, "md");
  gend(card.dismiss_ms || 3500);
}

/* ---- the frontier lens cards, on the SAME glass engine ------------------
   Each is a bespoke draw in the 256px space (renderer.lua idiom) reusing the
   object card's primitives — the dark glass disc, gtext/garc/gdiamond, the
   palette.lua colors, the .on fade + glassTimer dismiss — so a Read / Math /
   Distance / Find / Scene / Sky look renders as a native card, not a text
   plate. Shared helpers first. */
function gback(ctx){                              /* the dark emissive disc */
  ctx.beginPath(); ctx.arc(128, 128, 128, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(4,8,6,.68)"; ctx.fill();
}
function gend(ms){                                /* fade the card on + auto-dismiss */
  $("glass").classList.add("on");
  clearTimeout(glassTimer);
  glassTimer = setTimeout(glassClear, ms || 4200);
}
function gwrap(str, n){                           /* soft-wrap to lines of ~n chars */
  const words = String(str || "").split(/\s+/).filter(Boolean);
  const out = []; let line = "";
  for (const w of words){
    if ((line + " " + w).trim().length > n){ if (line) out.push(line); line = w; }
    else line = (line ? line + " " : "") + w;
  }
  if (line) out.push(line);
  return out.length ? out : (str ? [String(str).slice(0, n)] : []);
}
function groundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function glassMathCard(j){                        /* Math -> LaTeX, a lit slate */
  const ctx = glassCtx(); gback(ctx);
  ctx.beginPath(); ctx.arc(128, 122, 66, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(44,199,154,.06)"; ctx.fill();
  ctx.strokeStyle = "rgba(44,199,154,.22)"; ctx.lineWidth = 1; ctx.stroke();
  ctx.save(); ctx.shadowColor = GP.confidence_high; ctx.shadowBlur = 8;
  garc(ctx, 128, 84, 15, 205, 335, GP.confidence_high);
  gtext(ctx, "∑", 128, 84, GP.confidence_high, "lg");   /* summation glyph jewel */
  ctx.restore();
  gtext(ctx, "MATH", 128, 50, GP.text_ghost, "sm");
  const lines = gwrap(String(j.latex || "").trim(), 22).slice(0, 3);
  if (lines.length) lines.forEach((ln, i) => gtext(ctx, ln, 128, 118 + i * 18, GP.text_primary, i ? "sm" : "md"));
  else gtext(ctx, "no equation in view", 128, 122, GP.text_secondary, "sm");
  gtext(ctx, "[ LaTeX ]", 128, 192, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 5200);
}
function glassDocCard(j){                          /* Read -> a page reading in */
  const ctx = glassCtx(); gback(ctx);
  ctx.save(); ctx.strokeStyle = "rgba(168,184,192,.5)"; ctx.lineWidth = 1.4;
  groundRect(ctx, 94, 64, 68, 92, 6); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(148, 64); ctx.lineTo(162, 78); ctx.lineTo(148, 78);
  ctx.closePath(); ctx.stroke(); ctx.restore();
  ctx.save(); ctx.shadowColor = GP.memory_trace; ctx.shadowBlur = 4;
  ctx.strokeStyle = GP.memory_trace; ctx.lineWidth = 1.2;
  for (let i = 0; i < 6; i++){ const y = 80 + i * 11;
    ctx.beginPath(); ctx.moveTo(102, y); ctx.lineTo(102 + (i % 3 === 2 ? 32 : 50), y); ctx.stroke(); }
  ctx.restore();
  gtext(ctx, "READ", 128, 50, GP.text_ghost, "sm");
  const lines = gwrap(String(j.text || "").trim(), 26).slice(0, 2);
  if (lines.length) lines.forEach((ln, i) => gtext(ctx, ln, 128, 178 + i * 15, GP.text_primary, "sm"));
  else gtext(ctx, "no text in view", 128, 184, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 5600);
}
function glassDepthCard(j){                        /* Distance -> a proximity gauge */
  const ctx = glassCtx(); gback(ctx);
  const cn = Number(j.closeness);                  /* NaN-safe: a non-numeric closeness reads as "—", never "NaN%" */
  const c = Number.isFinite(cn) ? Math.max(0, Math.min(1, cn)) : null;
  ctx.strokeStyle = "rgba(44,199,154,.16)"; ctx.lineWidth = 1;
  [26, 46, 66].forEach(r => { ctx.beginPath(); ctx.arc(128, 112, r, 0, 2 * Math.PI); ctx.stroke(); });
  gtext(ctx, "DISTANCE", 128, 50, GP.text_ghost, "sm");
  if (c != null){
    const col = c >= 0.66 ? GP.confidence_low : c >= 0.33 ? GP.confidence_med : GP.confidence_high;
    ctx.save(); ctx.shadowColor = col; ctx.shadowBlur = 8;
    ctx.beginPath(); ctx.arc(128, 112, 66, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * c);
    ctx.strokeStyle = col; ctx.lineWidth = 3.4; ctx.stroke(); ctx.restore();
    gtext(ctx, Math.round(c * 100) + "%", 128, 108, col, "lg");
    gtext(ctx, c >= 0.66 ? "very close" : c >= 0.33 ? "nearby" : "far off", 128, 128, GP.text_secondary, "sm");
  } else gtext(ctx, "—", 128, 112, GP.text_secondary, "lg");
  gtext(ctx, "[ relative depth ]", 128, 192, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 4600);
}
function glassFindCard(j){                          /* Find -> a reticle + hits */
  const ctx = glassCtx(); gback(ctx);
  const found = Array.isArray(j.found) ? j.found : [];
  garc(ctx, 128, 108, 44, 0, 360, GP.border_subtle);
  ctx.strokeStyle = GP.memory_trace; ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(128, 58); ctx.lineTo(128, 72); ctx.moveTo(128, 144); ctx.lineTo(128, 158);
  ctx.moveTo(76, 108); ctx.lineTo(90, 108); ctx.moveTo(166, 108); ctx.lineTo(180, 108); ctx.stroke();
  gtext(ctx, "FIND", 128, 50, GP.text_ghost, "sm");
  if (found.length){
    ctx.save(); ctx.shadowColor = GP.confidence_high; ctx.shadowBlur = 7;
    gdiamond(ctx, 128, 108, 7, GP.confidence_high); ctx.restore();
    found.slice(0, 3).forEach((f, i) => {
      const cf = Number(f.confidence);             /* NaN-safe: drop a bad confidence, don't render "NaN%" */
      const pct = Number.isFinite(cf) ? "  " + Math.round(Math.max(0, Math.min(1, cf)) * 100) + "%" : "";
      gtext(ctx, (f.term || "") + pct, 128, 150 + i * 16, GP.text_primary, "sm");
    });
  } else gtext(ctx, "not in view", 128, 108, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 4600);
}
function glassSegmentCard(j){                       /* Scene -> lit region wedges */
  const ctx = glassCtx(); gback(ctx);
  const rn = Number(j.regions);                    /* NaN-safe: a non-numeric region count draws nothing, not "NaN" */
  const n = Number.isFinite(rn) ? Math.max(0, Math.min(12, Math.round(rn))) : 0;
  const k = Math.max(1, n);
  for (let i = 0; i < k; i++){
    const a0 = (i / k) * 2 * Math.PI - Math.PI / 2, a1 = ((i + 1) / k) * 2 * Math.PI - Math.PI / 2;
    ctx.beginPath(); ctx.moveTo(128, 110); ctx.arc(128, 110, 60, a0, a1); ctx.closePath();
    ctx.fillStyle = "rgba(44,199,154," + (0.05 + 0.035 * (i % 3)) + ")"; ctx.fill();
    ctx.strokeStyle = "rgba(44,199,154,.3)"; ctx.lineWidth = 1; ctx.stroke();
  }
  gtext(ctx, "SCENE", 128, 50, GP.text_ghost, "sm");
  gtext(ctx, String(n), 128, 106, GP.memory_trace, "lg");
  gtext(ctx, n === 1 ? "region" : "regions", 128, 128, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 4200);
}
function glassSkyCard(j){                           /* Sky -> a named star map */
  const ctx = glassCtx(); gback(ctx);
  const pts = [[96, 80], [150, 72], [120, 100], [170, 110], [88, 120], [138, 130], [112, 150], [160, 146]];
  ctx.strokeStyle = "rgba(184,255,233,.25)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(96, 80); ctx.lineTo(120, 100); ctx.lineTo(150, 72);
  ctx.moveTo(120, 100); ctx.lineTo(138, 130); ctx.lineTo(160, 146); ctx.stroke();
  pts.forEach((p, i) => { ctx.save(); ctx.shadowColor = GP.confidence_high; ctx.shadowBlur = (i % 2 ? 6 : 3);
    ctx.fillStyle = GP.text_primary; ctx.beginPath();
    ctx.arc(p[0], p[1], (i % 3 === 0 ? 2 : 1.3), 0, 2 * Math.PI); ctx.fill(); ctx.restore(); });
  gtext(ctx, "SKY", 128, 50, GP.text_ghost, "sm");
  const lines = gwrap(String(j.line || "").trim(), 26).slice(0, 2);
  if (lines.length) lines.forEach((ln, i) => gtext(ctx, ln, 128, 180 + i * 16, GP.text_primary, "sm"));
  else gtext(ctx, "the sky, named", 128, 186, GP.text_secondary, "sm");
  gend(j.dismiss_ms || 5600);
}

/* ---- ambient cards the Brain PUSHES (over the /live/events channel) -------
   Not a reply to a look — the Brain surfaces these on its own: a sound-safety
   tap, the morning brief, a memory nudge. Same glass, same primitives. */
function glassTasteCard(j){                          /* TasteLens — the pick + the why */
  const ctx = glassCtx(); gback(ctx);
  ctx.beginPath(); ctx.arc(128, 116, 66, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(44,199,154,.06)"; ctx.fill();
  ctx.strokeStyle = "rgba(44,199,154,.22)"; ctx.lineWidth = 1; ctx.stroke();
  gtext(ctx, "BEST PICK", 128, 52, GP.text_ghost, "sm");
  const pick = String(j.primary || "").trim();
  if (pick) gtext(ctx, gwrap(pick, 18)[0] || pick, 128, 92, GP.text_primary, "lg");
  else gtext(ctx, "nothing to compare", 128, 108, GP.text_secondary, "sm");
  const why = String(j.detail || "").trim();
  if (why) gtext(ctx, gwrap(why, 28)[0] || "", 128, 116, GP.memory_trace, "sm");
  const items = Array.isArray(j.items) ? j.items.slice(0, 3) : [];
  items.forEach((it, i) => gtext(ctx, gwrap(String(it), 30)[0] || "", 128, 146 + i * 16, GP.text_secondary, "sm"));
  gend(j.dismiss_ms || 6000);
}
function glassHarkCard(c){                          /* Listen! — a sound-safety tap */
  const ctx = glassCtx(); gback(ctx);
  const urgent = c.importance === "urgent";
  const col = urgent ? GP.confidence_low : GP.memory_trace;    /* amber vs phosphor */
  ctx.save(); ctx.shadowColor = col; ctx.shadowBlur = urgent ? 12 : 7;
  garc(ctx, 128, 108, 46, 0, 360, col);                        /* the attention ring */
  garc(ctx, 128, 108, 40, 200, 340, col);
  ctx.fillStyle = col; ctx.fillRect(126, 88, 4, 24);           /* the ! stroke */
  ctx.beginPath(); ctx.arc(128, 120, 2.4, 0, 2 * Math.PI); ctx.fill(); ctx.restore();
  gtext(ctx, c.eyebrow || "LISTEN", 128, 50, col, "sm");
  const lines = gwrap(String(c.primary || "").trim(), 24).slice(0, 2);
  lines.forEach((ln, i) => gtext(ctx, ln, 128, 168 + i * 15, GP.text_primary, "sm"));
  if (c.detail) gtext(ctx, String(c.detail).slice(0, 30), 128, 168 + lines.length * 15 + 2, GP.text_ghost, "sm");
  gend(c.dismiss_ms || (urgent ? 9000 : 6000));
}
function glassBriefCard(c){                          /* the morning brief */
  const ctx = glassCtx(); gback(ctx);
  ctx.beginPath(); ctx.arc(128, 118, 64, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(44,199,154,.05)"; ctx.fill();
  ctx.strokeStyle = "rgba(44,199,154,.2)"; ctx.lineWidth = 1; ctx.stroke();
  garc(ctx, 128, 96, 20, 180, 360, GP.confidence_high);        /* a rising sun */
  ctx.strokeStyle = "rgba(184,255,233,.4)"; ctx.lineWidth = 1;
  [-28, -8, 12, 32].forEach(dx => { ctx.beginPath(); ctx.moveTo(128 + dx, 68); ctx.lineTo(128 + dx, 60); ctx.stroke(); });
  gtext(ctx, c.eyebrow || "YOUR DAY", 128, 46, GP.memory_trace, "sm");
  const head = gwrap(String(c.primary || "").trim(), 26).slice(0, 2);
  head.forEach((ln, i) => gtext(ctx, ln, 128, 120 + i * 15, GP.text_primary, "sm"));
  const bl = Array.isArray(c.bullets) ? c.bullets : [];
  bl.slice(0, 2).forEach((b, i) => gtext(ctx, "· " + (gwrap(String(b), 26)[0] || ""), 128, 166 + i * 15, GP.text_secondary, "sm"));
  gend(c.dismiss_ms || 8000);
}
function glassEventCard(c){                          /* any pushed card with no bespoke renderer */
  const ctx = glassCtx(); gback(ctx);
  garc(ctx, 128, 108, 44, 0, 360, GP.border_subtle);
  ctx.save(); ctx.shadowColor = GP.memory_trace; ctx.shadowBlur = 6;
  gdiamond(ctx, 128, 108, 6, GP.memory_trace); ctx.restore();
  gtext(ctx, String(c.eyebrow || "JUNO").toUpperCase().slice(0, 18), 128, 50, GP.text_ghost, "sm");
  const lines = gwrap(String(c.primary || c.text || "").trim(), 24).slice(0, 3);
  if (lines.length) lines.forEach((ln, i) => gtext(ctx, ln, 128, 150 + i * 15, GP.text_primary, "sm"));
  else gtext(ctx, "…", 128, 128, GP.text_secondary, "md");
  gend(c.dismiss_ms || 6000);
}

/* ---- dream mode: the glasses' double-tap, on the phone ------------------
   The real thing's mechanics, scoped here the way the phone app's
   DreamCanvas already does: DOUBLE-TAP toggles it (orchestrator on_button
   "double_tap" → DreamEngine), and the render replays the SAME models —
   mic_reactor.py's two-band palette weather (low FFT bins = atmospheric
   pressure on the Cb/storm axis, high bins = energy on the Cr/ember axis,
   amplitude = luma), imu_reactor.py's curl-noise line field (12 vectors),
   and dream_renderer.lua's 24-particle core clipped inside r=96, over "the
   day, dimmed". Cadence 2 Hz = DreamEngine.AMBIENT_HZ. Client-only like
   DreamCanvas — nothing egresses; the veil quiets the feeds; the mic is
   released the moment dream ends. */
let dreamOn = false, dreamRaf = null, dreamAudio = null, dreamAnalyser = null;
let dreamGen = 0;                 /* bumped on every enter/exit — an await that
                                     resolves after its dream ended must STOP the
                                     stream it got, not attach it (refute F7/F8) */
let dreamACtx = null, dreamLastTick = 0, dreamT = 0;
const DREAM_TICK_MS = 500;                 /* 2 Hz — DreamEngine.AMBIENT_HZ */
const dweather = {pressure: 0, energy: 0, luma: 0.35};
const dmotion = {mag: 0};
const dparticles = [];
for (let i = 0; i < 24; i++)               /* 24 particles, as the device */
  dparticles.push({a: i / 24 * Math.PI * 2, r: 28 + (i * 53) % 62,
                   v: 0.0006 + ((i * 31) % 10) / 11000});
function ycbcr(y, cb, cr){                 /* the palette cmd's color space */
  const Y = y * 255, r = Y + 1.402 * cr * 128, b = Y + 1.772 * cb * 128,
        g = Y - 0.344 * cb * 128 - 0.714 * cr * 128;
  const c = v => Math.max(0, Math.min(255, v | 0));
  return "rgb(" + c(r) + "," + c(g) + "," + c(b) + ")";
}
function onDreamMotion(e){
  const a = (e.accelerationIncludingGravity || e.acceleration || {});
  const m = Math.abs(a.x || 0) + Math.abs(a.y || 0) + Math.abs(a.z || 0);
  dmotion.mag = dmotion.mag * 0.8 + Math.min(1, Math.abs(m - 9.8) / 12) * 0.2;
}
async function enterDream(){
  dreamOn = true;
  const myGen = ++dreamGen;
  if (confOn) _confResync = true;    /* rejoin mid-bond → one forced emit */
  document.body.setAttribute("data-dream", "on");
  clearTimeout(loopTimer);                 /* dream replaces memory-mode looks */
  renderPanel(null); glassClear(); clearOverlayOnce(); hideDetectorHud(); hideChooser();
  $("hint").textContent = "dream mode · double-tap to wake";
  try {                                    /* mic weather — asked inside the tap */
    if (!veil) {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      if (myGen !== dreamGen || !dreamOn || veil) {   /* dream ended mid-prompt */
        try { stream.getTracks().forEach(t => t.stop()); } catch (e) {}
        return;
      }
      dreamAudio = stream;
      dreamACtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = dreamACtx.createMediaStreamSource(dreamAudio);
      dreamAnalyser = dreamACtx.createAnalyser();
      dreamAnalyser.fftSize = 256;
      src.connect(dreamAnalyser);
    }
  } catch (e) { dreamAnalyser = null; }    /* no mic → motion/time weather only */
  try { if (window.DeviceMotionEvent && DeviceMotionEvent.requestPermission)
          await DeviceMotionEvent.requestPermission(); } catch (e) {}
  if (myGen !== dreamGen || !dreamOn) { exitDream(); return; }  /* ended mid-prompt */
  window.addEventListener("devicemotion", onDreamMotion);
  $("glass").classList.add("on");
  dreamRaf = requestAnimationFrame(dreamFrame);
}
function exitDream(){
  dreamOn = false;
  dreamGen++;                      /* invalidate any enterDream still awaiting */
  confHide(); confState = null; confBlend = null;
  dreamScene = null; dreamGhost = null; giftColors = null;   /* the scene wakes too */
  document.body.setAttribute("data-dream", "off");
  if (dreamRaf != null) { cancelAnimationFrame(dreamRaf); dreamRaf = null; }
  window.removeEventListener("devicemotion", onDreamMotion);
  try { if (dreamAudio) dreamAudio.getTracks().forEach(t => t.stop()); } catch (e) {}
  try { if (dreamACtx) dreamACtx.close(); } catch (e) {}
  dreamAudio = null; dreamAnalyser = null; dreamACtx = null;
  glassClear();
  setLive(liveOn);                         /* restores the hint + ambient loop */
}
function toggleDream(){ if (dreamOn) exitDream(); else enterDream(); }
function dreamTick(){                      /* the 2 Hz reactor pass */
  let pressure = 0, energy = 0, amp = 0;
  if (dreamAnalyser && !veil) {
    const bins = new Uint8Array(dreamAnalyser.frequencyBinCount);
    dreamAnalyser.getByteFrequencyData(bins);
    let lo = 0, hi = 0;
    for (let i = 1; i <= 8; i++) lo += bins[i];
    for (let i = 24; i < 96; i++) hi += bins[i];
    for (let i = 0; i < bins.length; i++) amp += bins[i];
    pressure = lo / (8 * 255); energy = hi / (72 * 255);
    amp = amp / (bins.length * 255);
  }
  /* becalmed drift when quiet/veiled — the sky never flatlines */
  dweather.pressure = dweather.pressure * 0.7 + (pressure + dmotion.mag * 0.3) * 0.3;
  dweather.energy   = dweather.energy * 0.7 + energy * 0.3;
  dweather.luma     = 0.3 + Math.min(0.4, amp * 0.8 + dmotion.mag * 0.15);
  confBeat();                        /* the shared sky rides the same 2 Hz */
  if (performance.now() - _lastSceneT >= SCENE_MS) {   /* the scene, at 4 s */
    _lastSceneT = performance.now();
    dreamSceneBeat();
  }
}
function dreamCurl(x, y, t){               /* cheap curl of a drifting field */
  const n = (a, b) => Math.sin(a * 0.061 + t * 0.00021 + Math.sin(b * 0.047 - t * 0.00013));
  return Math.atan2(n(x + 13, y) - n(x - 13, y), n(x, y - 13) - n(x, y + 13));
}
function dreamFrame(ts){
  if (!dreamOn) return;
  dreamRaf = requestAnimationFrame(dreamFrame);
  if (ts - dreamLastTick >= DREAM_TICK_MS) { dreamLastTick = ts; dreamTick(); }
  dreamT = ts;
  const ctx = glassCtx();
  /* the day, dimmed (HZ.draw dim=true) — a change of light, not a scene cut */
  ctx.beginPath(); ctx.arc(128, 128, 128, 0, 2 * Math.PI);
  ctx.fillStyle = "rgba(3,6,5," + (0.78 - dweather.luma * 0.25).toFixed(3) + ")";
  ctx.fill();
  const sky = ycbcr(dweather.luma, 0.18 + dweather.pressure * 0.5,
                    -0.10 - dweather.pressure * 0.15);
  const ember = ycbcr(dweather.luma + 0.1, -0.12, 0.14 + dweather.energy * 0.55);
  /* line field: 12 curl vectors bending with motion (imu_reactor) */
  ctx.strokeStyle = sky; ctx.lineWidth = 1.1; ctx.globalAlpha = 0.7;
  for (let i = 0; i < 12; i++) {
    const gx = 44 + (i % 4) * 56, gy = 52 + ((i / 4) | 0) * 66;
    const a = dreamCurl(gx, gy, ts) + dmotion.mag * Math.sin(ts * 0.002 + i);
    const L = 14 + dweather.pressure * 12;
    ctx.beginPath(); ctx.moveTo(gx - Math.cos(a) * L, gy - Math.sin(a) * L);
    ctx.lineTo(gx + Math.cos(a) * L, gy + Math.sin(a) * L); ctx.stroke();
  }
  /* particles: the midground core, clipped inside r=96, agitated by energy */
  ctx.globalAlpha = 1;
  for (const p of dparticles) {
    p.a += p.v * (1 + dweather.energy * 6 + dmotion.mag * 2);
    const r = Math.min(96 - 3, p.r * (1 + dweather.energy * 0.12));
    const x = 128 + Math.cos(p.a) * r, y = 128 + Math.sin(p.a) * r;
    ctx.beginPath(); ctx.arc(x, y, 1.6, 0, 2 * Math.PI);
    ctx.fillStyle = ember; ctx.fill();
  }
  ctx.globalAlpha = 1;
  drawGiftWash(ctx);                 /* a gifted moment washing the glass */
  drawConfluence(ctx);               /* the shared sky, when two are dreaming */
  drawSynesthesia(ctx);              /* the scene, read as a phrase + a gesture */
  drawGhost(ctx);                    /* a memory echo — one of your kept moments
                                        drifting up in the dream (a reverie, not
                                        a location match: this phone has no GPS) */
  if (!(dreamScene && performance.now() < dreamSceneUntil))
    gtext(ctx, "DREAM", 128, 36, GP.text_ghost, "sm");
}

/* ---- the dream's scene layer: the REAL SynesthesiaCard + memory echoes ----
   Every SCENE_INTERVAL (the device's 4 s cadence) a frame goes to the Brain's
   OWN vision (world_lens._describe — it never leaves the Brain, and it degrades
   to the honest offline mood cycle with no model), coming back as a six-word
   phrase + a three-shape gestural sprite; and when a place you SAVED matches, a
   dim memory-echo ghost surfaces it. Same primitives the glasses run
   (SceneDescriber + GhostLayer), just fed by this phone's camera. */
const SCENE_MS = 4000;               /* SCENE_INTERVAL_S = 4.0 (dream_mode/engine) */
let dreamScene = null, dreamSceneUntil = 0;
let dreamGhost = null, dreamGhostUntil = 0;
let _sceneBusy = false, _lastSceneT = 0;
async function dreamSceneBeat(){
  if (!dreamOn || veil || _sceneBusy || !camReady()) return;
  _sceneBusy = true;
  try {
    const c = captureFrame(512);
    if (!c) return;
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.8));
    if (!blob || !dreamOn || veil) return;   /* woke / veiled mid-capture */
    const rsp = await fetchJSON("/dreamlayer/live/dream/scene",
      {method: "POST", headers: HDRS(), body: blob}, 12000);
    const j = rsp.json || {};
    const now = performance.now();
    if (j.scene) { dreamScene = j.scene; dreamSceneUntil = now + (j.scene.dismiss_ms || 4000); }
    if (j.ghost) { dreamGhost = j.ghost; dreamGhostUntil = now + (j.ghost.dismiss_ms || 8000); }
  } catch (e) { /* a missed scene is just a quieter dream */ }
  finally { _sceneBusy = false; }
}
function hexRgb(n){ n = n | 0; return "rgb(" + ((n>>16)&255) + "," + ((n>>8)&255) + "," + (n&255) + ")"; }
function drawGesture(ctx, kind, x, y, sz){
  ctx.beginPath();
  if (kind === "line") { ctx.moveTo(x - sz, y); ctx.lineTo(x + sz, y); ctx.stroke(); }
  else if (kind === "rect") { ctx.strokeRect(x - sz/2, y - sz/2, sz, sz); }
  else if (kind === "triangle") {
    ctx.moveTo(x, y - sz/2); ctx.lineTo(x + sz/2, y + sz/2);
    ctx.lineTo(x - sz/2, y + sz/2); ctx.closePath(); ctx.stroke();
  } else { ctx.arc(x, y, sz/2, 0, 2 * Math.PI); ctx.stroke(); }
}
function drawSynesthesia(ctx){
  if (!dreamScene || performance.now() >= dreamSceneUntil) return;
  const phrase = String(dreamScene.description || dreamScene.primary || "");
  gtext(ctx, "DREAM", 128, 64, GP.text_ghost, "sm");
  const words = phrase.split(/\s+/).filter(Boolean);
  const mid = Math.ceil(words.length / 2);           /* the six words, two lines */
  gtext(ctx, words.slice(0, mid).join(" "), 128, 88, GP.text_primary, "sm");
  const l2 = words.slice(mid).join(" ");
  if (l2) gtext(ctx, l2, 128, 102, GP.text_primary, "sm");
  const shapes = Array.isArray(dreamScene.shapes) ? dreamScene.shapes : [];
  if (!shapes.length) return;                         /* the gestural sprite */
  const col = hexRgb(dreamScene.dominant_color || 0x2CC79A);
  ctx.save();
  ctx.beginPath(); ctx.arc(128, 128, 126, 0, 2 * Math.PI); ctx.clip();
  ctx.globalAlpha = 0.85; ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 2;
  for (const s of shapes) {
    const x = 44 + (Math.max(0, Math.min(127, s.x | 0)) / 127) * 168;   /* [44,212] */
    const y = 140 + (Math.max(0, Math.min(127, s.y | 0)) / 127) * 42;   /* [140,182] */
    drawGesture(ctx, s.kind, x, y, Math.max(6, Math.min(38, (s.size | 0) * 0.62)));
  }
  ctx.restore();
}
function drawGhost(ctx){
  if (!dreamGhost || performance.now() >= dreamGhostUntil) return;
  const g = dreamGhost;
  ctx.save();
  ctx.globalAlpha = Number(g.opacity) || 0.20;        /* the device's 20% ghost */
  gtext(ctx, "MEMORY ECHO", 128, 190, GP.text_ghost, "sm");
  gtext(ctx, String(g.summary || g.primary || ""), 128, 206, GP.memory_trace, "sm");
  const detail = String(g.detail || "");
  if (detail) gtext(ctx, detail, 128, 220, GP.text_ghost, "sm");
  ctx.restore();
}


/* ---- Juno's first-run tour: the pro walkthrough of the REAL controls -----
   Anchored coach marks stepping through the actual elements — tap-to-look,
   double-tap dream, the veil, ask-your-memory — with tips. Shown once
   (localStorage), replayable from the ? chip. Text lands via textContent;
   the spotlight ring never takes pointer events, so every control stays
   live (and the e2e's direct clicks keep working) while the tour is up. */
const TOUR_STEPS = [
  {a: null, t: "I\u2019m Juno \u2014 your lens into DreamLayer. Give me thirty seconds and I\u2019ll show you how to see the way the glasses do."},
  {a: "lens", t: "Tap the lens for a closer look. I read the thing in view and draw the same card the glasses draw \u2014 price tags convert, books rate, and what you\u2019ve seen before says so. Tip: fill the circle with ONE thing."},
  {a: "lens", t: "Double-tap and I dream. Your mic becomes the weather, moving the phone bends the light \u2014 all on this phone, nothing leaves. Double-tap again to wake me."},
  {a: "veilbtn", t: "The veil is your privacy switch. Veil down, I\u2019m deliberately blind \u2014 no looks, no memory, no trace. Your posture, mirrored everywhere."},
  {a: "q", t: "Ask your memory anything \u2014 \u201cwhere did I last see my keys?\u201d Recall runs on YOUR Brain, on your LAN. Tip: pinch to zoom; the torch button appears when your camera has one."},
  {a: null, t: "That\u2019s the tour \u2014 the real system, without the glass. Point me at something."}
];
let tourStep = -1;
function tourSeen(){ try { return !!localStorage.getItem("dl-live-tour"); } catch (e) { return true; } }
function tourMark(){ try { localStorage.setItem("dl-live-tour", "1"); } catch (e) {} }
function startTour(force){
  if (!force && (tourSeen() || _pairNotice)) return;  /* pairing first — the tour
                                                         follows a successful redeem */
  tourStep = -1;
  $("tour").classList.add("on");
  tourNext();
}
function endTour(){
  $("tour").classList.remove("on");
  $("tourring").style.display = "none";
  tourMark();
}
function placeRing(st){
  const ring = $("tourring");
  const el = st && st.a && $(st.a);
  if (!el) { ring.style.display = "none"; return; }
  const r = el.getBoundingClientRect();
  ring.style.display = "block";
  ring.style.left = (r.left - 8) + "px";
  ring.style.top = (r.top - 8) + "px";
  ring.style.width = (r.width + 16) + "px";
  ring.style.height = (r.height + 16) + "px";
  ring.style.borderRadius = st.a === "lens" ? "50%" : "14px";
}
function tourNext(){
  tourStep++;
  if (tourStep >= TOUR_STEPS.length) { endTour(); return; }
  const st = TOUR_STEPS[tourStep];
  $("tourmsg").textContent = st.t;                    /* untrusted-safe by habit */
  $("tourdots").textContent = (tourStep + 1) + " / " + TOUR_STEPS.length;
  $("tournext").textContent = tourStep === TOUR_STEPS.length - 1 ? "Begin" : "Next";
  placeRing(st);
}
/* rotate/resize mid-tour: re-anchor the spotlight to where the control IS */
window.addEventListener("resize", () => {
  if ($("tour").classList.contains("on") && tourStep >= 0)
    placeRing(TOUR_STEPS[tourStep]);
});
$("tournext").onclick = tourNext;
$("tourskip").onclick = endTour;
$("tourbtn").onclick = () => startTour(true);
$("tourbtn").onkeydown = e => { if (e.key===" "||e.key==="Enter") startTour(true); };


/* ---- confluence: two skies, one room -------------------------------------
   The REAL two-wearer layer, through the Brain as the meeting point. This
   client only speaks and paints: it posts my weather beat (state + palette
   slots) at the dream 2 Hz and renders exactly the frames MY EntangledSky
   returns — a blended palette when merged, a seam with the peer's half-sky
   (seam_dd / gap_deg / peer_rgb) when split, a solo frame when the peer
   fades. All bond math, authentication, hysteresis, and staleness live
   server-side in the real BondManager/EntangledSky — nothing is faked here,
   and nothing but weather numbers ever leaves this phone. */
let CONF_SID = "";
try {
  CONF_SID = sessionStorage.getItem("dl-live-csid") || "";
  if (!CONF_SID) {
    CONF_SID = (crypto.randomUUID ? crypto.randomUUID()
                : String(Math.floor(performance.now())) + "-" +
                  String((crypto.getRandomValues(new Uint32Array(2))[0])));
    sessionStorage.setItem("dl-live-csid", CONF_SID);
  }
} catch (e) { CONF_SID = "sid-" + String(performance.now() | 0); }
let confOn = false;                 /* an offer or bond is live for this side */
let confState = null;               /* {mode, tg, seamDeg, gapDeg, peerRgb} */
let confBlend = null;               /* merged palette slots from MY sky */
let giftColors = null, giftUntil = 0;   /* a Weather Gift washing my glass, 30 s */
function confSlots(){
  /* my four palette slots, in the device's 10-bit YCbCr slot shape — the
     same two-band weather that drives the solo dream (sky = pressure on the
     Cb/storm axis, energy = ember on the Cr axis, luma = amplitude) */
  const y = Math.round(Math.max(0, Math.min(1, dweather.luma)) * 255) * 4;
  const q = v => Math.round((Math.max(-1, Math.min(1, v)) * 128 + 128)) * 4;
  const sky = {idx: 1, y: y, cb: q(0.18 + dweather.pressure * 0.5),
               cr: q(-0.10 - dweather.pressure * 0.15)};
  const ember = {idx: 2, y: Math.min(1023, y + 100), cb: q(-0.12),
                 cr: q(0.14 + dweather.energy * 0.55)};
  return [sky, ember,
          {idx: 3, y: Math.max(0, y - 120), cb: sky.cb, cr: sky.cr},
          {idx: 4, y: Math.max(0, y - 200), cb: ember.cb, cr: ember.cr}];
}
function confMyState(){
  return Math.min(1, dweather.pressure * 0.5 + dweather.energy * 0.5);
}
function slotRgb(c){
  const y = (c.y || 512) / 4, cb = (c.cb || 512) / 4 - 128, cr = (c.cr || 512) / 4 - 128;
  const cl = v => Math.max(0, Math.min(255, v | 0));
  return "rgb(" + cl(y + 1.402 * cr) + "," + cl(y - 0.344 * cb - 0.714 * cr) +
         "," + cl(y + 1.772 * cb) + ")";
}
let _confBusy = false, _confResync = false;
async function confBeat(){
  if (!confOn || !dreamOn || _confBusy) return;   /* one beat in flight — a slow
                                                     link must not pile up stale
                                                     out-of-order frames */
  _confBusy = true;
  try {
    const rsp = await fetchJSON("/dreamlayer/live/weather", {
      method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
      body: JSON.stringify({sid: CONF_SID, state: confMyState(),
                            colors: confSlots(), resync: _confResync})}, 4000);
    _confResync = false;
    const j = rsp.json || {};
    for (const f of (j.frames || [])) applyConfFrame(f);
    if (j.entangled === false && !j.waiting) setConfOn(false);
  } catch (e) { /* a missed beat is just weather */ }
  finally { _confBusy = false; }
}
function applyConfFrame(f){
  if (!f || !f.t && !f.mode) return;
  if (f.t === "gift") {              /* a moment they chose to hand me */
    giftColors = Array.isArray(f.colors) && f.colors.length ? f.colors : null;
    if (giftColors) { giftUntil = performance.now() + 30000;   /* GIFT_PLAY_S */
                      showHud(["a gift · their sky"], {ms: 2600}); }
    return;
  }
  if (f.t === "palette") { confBlend = f.colors || null; return; }
  if (f.mode === "solo") { confState = null; confBlend = null; return; }
  if (f.mode === "merged") {
    confState = {mode: "merged", tg: (f.tg | 0)};
    return;
  }
  if (f.mode === "split") {
    confState = {mode: "split", tg: (f.tg | 0),
                 seamDeg: (f.seam_dd | 0) / 10,
                 gapDeg: (f.gap_deg | 0),
                 peerRgb: Array.isArray(f.peer_rgb) ? f.peer_rgb : [60, 70, 75]};
    confBlend = null;
  }
}
function drawConfluence(ctx){
  /* the shared sky, over the dream, inside the glass circle */
  if (!confState) return;
  if (confState.mode === "merged") {
    /* one coherent front: a soft ring breathing with togetherness */
    const a = 0.10 + (confState.tg / 100) * 0.25;
    ctx.save();
    ctx.beginPath(); ctx.arc(128, 128, 120, 0, 2 * Math.PI);
    let col = "rgba(44,199,154," + a.toFixed(3) + ")";
    if (confBlend) {
      const skySlot = confBlend.find(c => (c.idx | 0) === 1);
      if (skySlot) col = slotRgb(skySlot);
      ctx.globalAlpha = a;
    }
    ctx.strokeStyle = col; ctx.lineWidth = 5; ctx.stroke();
    ctx.restore();
    gtext(ctx, "TOGETHER " + confState.tg + "%", 128, 226, GP.text_ghost, "sm");
    return;
  }
  /* split: the sky divides — my half keeps my weather, the peer's half
     arrives as one ready RGB; the seam stands at seam_dd, its gap widening
     with divergence, its softness fading with togetherness */
  const th = (confState.seamDeg || -90) * Math.PI / 180;
  const gap = (confState.gapDeg || 8) * Math.PI / 180;
  const [pr, pg, pb] = confState.peerRgb;
  ctx.save();
  ctx.beginPath(); ctx.arc(128, 128, 127, 0, 2 * Math.PI); ctx.clip();
  ctx.beginPath();
  ctx.moveTo(128, 128);
  ctx.arc(128, 128, 130, th + gap / 2, th + Math.PI - gap / 2);
  ctx.closePath();
  ctx.fillStyle = "rgba(" + pr + "," + pg + "," + pb + ",0.38)";
  ctx.fill();
  const soft = Math.max(0.15, 1 - (confState.tg / 100));
  for (const t of [th, th + Math.PI]) {
    ctx.beginPath();
    ctx.moveTo(128 + Math.cos(t) * 30, 128 + Math.sin(t) * 30);
    ctx.lineTo(128 + Math.cos(t) * 127, 128 + Math.sin(t) * 127);
    ctx.strokeStyle = "rgba(255,196,107," + (0.25 + soft * 0.45).toFixed(3) + ")";
    ctx.lineWidth = 1 + soft * 2.5;
    ctx.stroke();
  }
  ctx.restore();
  gtext(ctx, "APART " + (100 - confState.tg) + "%", 128, 226, GP.text_ghost, "sm");
}
function drawGiftWash(ctx){
  /* a Weather Gift: their recorded sky washes over mine for 30 s, fading as it
     plays, then my own weather flows back. One authenticated palette, nothing
     more — the real confluence.gift, rendered as light. */
  if (!giftColors || performance.now() >= giftUntil) return;
  const remain = (giftUntil - performance.now()) / 30000;   /* 1 -> 0 */
  const slot = giftColors.find(c => (c.idx | 0) === 1) || giftColors[0];
  if (!slot) return;
  ctx.save();
  ctx.beginPath(); ctx.arc(128, 128, 128, 0, 2 * Math.PI); ctx.clip();
  ctx.globalAlpha = 0.12 + remain * 0.30;
  ctx.fillStyle = slotRgb(slot);
  ctx.beginPath(); ctx.arc(128, 128, 128, 0, 2 * Math.PI); ctx.fill();
  ctx.restore();
  gtext(ctx, "A GIFT · THEIR SKY", 128, 240, GP.text_ghost, "sm");
}
async function confGift(){
  try {
    const j = await confApi("/dreamlayer/live/confluence/gift",
                            {sid: CONF_SID, colors: confSlots()});
    if (j.ok) { confHide(); showHud(["your sky · sent"], {ms: 2600}); }
    else $("confmsg").textContent = j.error || "couldn't send the sky";
  } catch (e) { $("confmsg").textContent = "brain unreachable"; }
}
function setConfOn(on){
  confOn = on;
  if (!on) { confState = null; confBlend = null; }
  $("confbtn").classList.toggle("on", on);
}
function confCard(mode, code){
  const card = $("confcard"), body = $("confbody"), msg = $("confmsg");
  body.textContent = ""; msg.textContent = "";
  const p = t => { const el = document.createElement("p"); el.textContent = t; body.appendChild(el); };
  const btn = (t, fn, ghost) => {
    const b = document.createElement("button"); b.type = "button";
    b.textContent = t; if (ghost) b.className = "ghost"; b.onclick = fn; return b;
  };
  const acts = document.createElement("div"); acts.className = "acts";
  if (mode === "choose") {
    p("Share the sky with someone dreaming on this Brain. One of you gets a code; the other speaks it back.");
    acts.appendChild(btn("Get a code", confPropose));
    acts.appendChild(btn("I have a code", () => confCard("enter"), true));
  } else if (mode === "code") {
    p("Say these three words to them — the code IS the bond:");
    const c = document.createElement("div"); c.className = "code";
    c.textContent = code; body.appendChild(c);
    p("Keep dreaming. The moment they enter it, your skies meet.");
    acts.appendChild(btn("Done", confHide));
  } else if (mode === "enter") {
    p("Type the words they spoke:");
    const inp = document.createElement("input");
    inp.id = "confcode"; inp.autocomplete = "off";
    inp.placeholder = "amber-birch"; body.appendChild(inp);
    acts.appendChild(btn("Entangle", confAccept));
    acts.appendChild(btn("Back", () => confCard("choose"), true));
    setTimeout(() => inp.focus(), 60);
  } else if (mode === "bonded") {
    p("Entangled. The sky is shared while you both dream — merged when your weathers agree, split when they part.");
    p("Or hand them this exact moment: your sky washes over theirs for thirty seconds, then their own weather flows back.");
    acts.appendChild(btn("Give my sky", confGift));
    acts.appendChild(btn("Untangle", confDissolve, true));
    acts.appendChild(btn("Close", confHide, true));
  }
  body.appendChild(acts);
  card.classList.add("on");
}
function confHide(){ $("confcard").classList.remove("on"); }
async function confApi(path, body){
  const rsp = await fetchJSON(path, {
    method: "POST",
    headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
    body: JSON.stringify(body)}, 6000);
  return rsp.json || {};
}
async function confPropose(){
  try {
    const j = await confApi("/dreamlayer/live/confluence/propose", {sid: CONF_SID});
    if (j.code) { setConfOn(true); confCard("code", j.code); }
    else $("confmsg").textContent = j.error || "couldn't make a code";
  } catch (e) { $("confmsg").textContent = "brain unreachable"; }
}
async function confAccept(){
  const code = ($("confcode") && $("confcode").value) || "";
  try {
    const j = await confApi("/dreamlayer/live/confluence/accept",
                            {sid: CONF_SID, code: code});
    if (j.ok) { setConfOn(true); confHide(); showHud(["skies entangled"], {ms: 2600}); }
    else $("confmsg").textContent = j.error || "that code didn't take";
  } catch (e) { $("confmsg").textContent = "brain unreachable"; }
}
async function confDissolve(){
  try { await confApi("/dreamlayer/live/confluence/dissolve", {sid: CONF_SID}); }
  catch (e) { /* the room stale-drops it anyway */ }
  setConfOn(false); confHide();
  showHud(["skies apart"], {ms: 2200});
}
$("confbtn").onclick = () => {
  if (!dreamOn) return;
  confCard(confOn ? "bonded" : "choose");
};
$("confbtn").onkeydown = e => {
  if ((e.key === " " || e.key === "Enter") && dreamOn)
    confCard(confOn ? "bonded" : "choose");
};

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
/* a persistent warm-up chip — the HUD gets overwritten by ambient results, so
   the honest "the on-device stack is still loading" signal lives here, next to
   the link chip, until the detector is on (tier chip takes over) or it falls
   back to the Brain loop */
function setVisionChip(on){
  const c = $("vision"); if (!c) return;
  if (on) { $("visionst").textContent = "vision loading…"; c.hidden = false; }
  else { c.hidden = true; }
}

/* ---- veil: the wearer's posture, mirrored here -------------------------- */
function setVeil(on, o){
  o = o || {};
  veil = on;
  $("veilst").textContent = on ? "on" : "off";
  $("veilbtn").classList.toggle("on", on);
  $("veilbtn").setAttribute("aria-checked", String(on));
  if (on) { renderPanel(null); clearOverlayOnce(); glassClear(); hideChooser();
            if (hearOn) _hearClose();     /* veil deafens the ear (mic released, intent kept) */
            if (dreamOn) exitDream(); }   /* wipe live surfaces; veil wakes the
                                             dream so the mic is RELEASED, not
                                             merely ignored */
  if (!o.silent) showHud(on ? "veil down · on-device only" : "veil lifted", {ms:2400});
  if (!on && liveOn) scheduleLoop(500);
  if (!on && hearOn && !hearCtx) _hearOpen();  /* shield lifted → the ear resumes */
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
/* Render a frontier-lens result (math/doc/depth/find/segment/dream) on the HUD.
   Kept separate from renderResult so the default object flow is untouched. */
function renderLens(j){
  if (dreamOn) return;
  if (!j) { showHud("look failed", {ms:2600}); return; }
  if (j.veiled) { showHud("the veil is down — turn it off to look closer", {ms:2800}); return; }
  if (j.need) { showHud("install the " + (j.pack || "required") + " pack for this lens", {ms:3600}); return; }
  if (j.need_location) { showHud("the sky lens needs your location", {ms:2800}); return; }
  /* a lens result draws its own glass card on the circle — the flat plate steps
     aside, exactly like the object card does (renderResult). */
  $("hud").classList.remove("on");
  switch (j.lens) {
    case "math": glassMathCard(j); break;
    case "doc": glassDocCard(j); break;
    case "depth": glassDepthCard(j); break;
    case "find": glassFindCard(j); break;
    case "segment": glassSegmentCard(j); break;
    case "sky": glassSkyCard(j); break;
    default:
      if (j.ok === false) { showHud(j.reason || "look failed", {ms:2600}); return; }
      showHud("done", {ms:1600}); return;
  }
  blip();
}
/* Render an auto-glance decision: fire draws the chosen lens's card, offer pops
   the one-tap chooser. The manual picker path uses renderLens directly. */
function renderGlance(j){
  if (dreamOn || !j) return;
  if (j.glance === "offer") { showChooser(j.card, j.scene); return; }
  if (j.glance === "fire") {
    const c = j.card || {};
    /* the arbiter fired a lens whose pack is missing: the card self-describes
       ({need:…}) — surface "install the pack" honestly instead of silently
       dropping to object-naming (audit 2026-07-23). renderLens owns that copy. */
    if (c.need || c.need_location || c.ok === false) { renderLens(c); return; }
    $("hud").classList.remove("on");
    if (c.type === "ObjectPanelCard") glassObjectCard(c);   /* translate */
    else if (c.type === "TasteCard") glassTasteCard(c);      /* shelf/menu pick */
    else if (c.lens === "math") glassMathCard(c);
    else if (c.lens === "doc") glassDocCard(c);
    else { renderLens(c); return; }
    blip();
  }
}
/* the glance chooser — a small glass dialog of 2–3 one-tap lens options, shown
   only when the look is genuinely ambiguous (e.g. text you could read OR solve).
   A pick runs that lens AND teaches the arbiter (scene→lens), so it leans your
   way next time. DOM (not canvas) because it's interactive, like the receipt
   and confluence dialogs. */
const LENS_FOR_ACTION = { read: "doc", math: "math", taste: "", translate: "", juno: "" };
function showChooser(card, scene){
  const box = $("chooser"); if (!box || dreamOn) return;
  const opts = (card && card.options) || [];
  $("chooserq").textContent = (card && card.eyebrow) || "What do you want?";
  const wrap = $("chooseropts"); wrap.textContent = "";
  opts.slice(0, 3).forEach(o => {
    const b = document.createElement("button");
    b.className = "choosebtn"; b.textContent = o.label || o.lens || "This";
    b.onclick = (ev) => {
      ev.stopPropagation(); hideChooser();
      const key = (o.action in LENS_FOR_ACTION) ? LENS_FOR_ACTION[o.action] : o.action;
      pickLens(key, scene);
    };
    wrap.appendChild(b);
  });
  box.classList.add("show");
  clearTimeout(window._chooserT);
  window._chooserT = setTimeout(hideChooser, (card && card.dismiss_ms) || 6000);
}
function hideChooser(){ const b = $("chooser"); if (b) b.classList.remove("show"); clearTimeout(window._chooserT); }
function pickLens(lensKey, scene){ lookNow(false, lensKey || "", scene || ""); }
function renderResult(j, auto){
  if (dreamOn) return;             /* a look in flight when dream began must not
                                      stomp the shared glass canvas, then hide it
                                      3.5s later via glassTimer (refute F10) */
  if (!j || j.ok === false) {
    if (!auto) showHud(j && j.reason ? j.reason : "look failed", {ms:3000});
    return;
  }
  if (j.label) {
    noHitStreak = 0;
    setTier(j.tier || "laptop");
    renderPanel(j.panel);
    if (!auto && j.panel) {
      /* a deliberate tap draws the DEVICE card on the glass circle — the same
         object-family art the glasses render for this panel. The card IS the
         read, so the flat HUD plate steps aside instead of stacking on it. */
      $("hud").classList.remove("on");
      glassObjectCard(j.panel);
      blip();
    } else {
      showHud(j.lines && j.lines.length ? j.lines : wrapLines(j.label), {persist: liveOn});
      if (!auto) blip();
    }
  } else {
    noHitStreak++;
    renderPanel(null);
    if (j.degraded && !auto) { showHud("smart lens hiccuped · retrying", {ms:2600}); return; }
    if (!auto) showHud("point at an object · move closer", {ms:3000});
    else if (noHitStreak >= 4) { showHud("looking for something to recognize…", {ms:2400}); noHitStreak = 0; }
  }
}
async function lookNow(auto, forceLens, forceScene){
  if (veil) { if (!auto) showHud("the veil is down", {ms:2200}); return; }
  if (!camReady()) { if (!auto) showHud("camera not ready…", {ms:1800}); return; }
  if (looking) return;
  if (!auto) hideChooser();                 /* a fresh look dismisses a stale chooser */
  looking = true; scan(true);
  if (!auto) showHud("looking…", {persist:true});
  try {
    const c = captureFrame(720);
    if (!c) throw new Error("no frame");
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
    if (!blob) throw new Error("no frame");
    /* The on-device detector can come online WHILE we were capturing this frame
       (toBlob yields). An ambient look must not fire its Brain round-trip once
       the browser is recognizing locally — that stray poll is the "it's just
       naming objects again" server hop, and it's the exact frame that laps the
       e2e idle check. Re-check right before the network call, not only at the
       top, so the race is actually closed. */
    if (auto && (detectorActive || !liveOn || document.hidden || dreamOn || veil)) return;
    const t0 = performance.now();
    /* auto (ambient) frames stay local-only + leave no trace server-side; a
       deliberate tap escalates to the full lens (VLM/plugins/memory/ledger),
       where the glance arbiter reads the scene and fires the right lens on its
       own — no mode is ever picked by hand — while ambient stays object-only. */
    /* The lens is NEVER chosen by hand — DreamLayer adapts. A plain look lets the
       glance arbiter read the scene and fire the right lens on its own (or offer a
       one-tap chooser when it's genuinely ambiguous — text you could read OR
       solve). The ONLY non-empty `sel` is a lens the arbiter's OWN chooser posted
       back, which also teaches it (scene→lens) so it leans your way next time. */
    const sel = (forceLens != null) ? forceLens : "";
    let url = auto ? "/dreamlayer/live/look?ambient=1" : "/dreamlayer/live/look";
    if (sel) {
      const qp = new URLSearchParams({lens: sel});
      if (forceScene) qp.set("scene", forceScene);   /* teach the arbiter this pick */
      url = "/dreamlayer/live/look?" + qp.toString();
    }
    const rsp = await fetchJSON(url,
      {method: "POST", headers: HDRS(), body: blob}, auto ? 6000 : 9000);
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) { needsPairing(); return; }
    if (sel) renderLens(rsp.json);                         /* manual / chosen lens */
    else if (rsp.json && rsp.json.glance) renderGlance(rsp.json);  /* auto: fire / chooser */
    else renderResult(rsp.json, auto);                    /* object floor / ambient */
  } catch (e) {
    if (e && e.name === "AbortError") { if (!auto) showHud("timed out · try again", {ms:2600}); }
    else { setLink(false, 0); if (!auto) showHud("brain unreachable", {ms:3000}); }
  } finally { looking = false; scan(false); }
}
/* tap = look; DOUBLE-tap = dream mode — the glasses' exact button grammar
   (orchestrator on_button: single glance, double_tap toggles dream). The
   single look waits one double-tap window so the gestures never collide. */
let _tapT = 0, _tapTimer = null;
$("lens").onclick = () => {
  const now = performance.now();
  if (now - _tapT < 300) {
    clearTimeout(_tapTimer); _tapT = 0;
    toggleDream(); return;
  }
  _tapT = now;
  _tapTimer = setTimeout(() => { if (!dreamOn) lookNow(false); }, 300);
};
$("lens").onkeydown = e => {
  if (e.key===" "||e.key==="Enter") { if (dreamOn) exitDream(); else lookNow(false); }
  if (e.key==="d"||e.key==="D") toggleDream();
};

/* ---- the continuous live loop (the glasses never wait for a tap) --------
   This is the Brain-round-trip ambient loop, the fallback when the on-device
   detector isn't available. When the detector IS running (detectorActive), the
   browser recognizes locally every frame and this server loop stays idle. */
let loopTimer = null, booted = false, detectorActive = false;
function scheduleLoop(delay){
  clearTimeout(loopTimer);
  /* don't run while: paused, unpaired (behind the pairing modal — else we burn
     camera+network 401ing every tick), backgrounded (battery), before the boot
     posture-seed lands (so the FIRST look already knows the veil), or when the
     on-device detector is doing the recognizing */
  if (!liveOn || _pairNotice || document.hidden || !booted || detectorActive
      || dreamOn) return;                  /* dream replaces memory-mode looks */
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

/* Exchange the short code for the token → paired (token in sessionStorage),
   the same end state as the token link. ONE implementation behind two entry
   points: the typed-code modal and the QR-carried #c= auto-redeem at boot. */
async function doRedeem(raw){
  const code = (raw || "").replace(/\D/g, "");
  if (code.length < 8) return {ok:false, msg:"Enter the 8-digit code from the panel."};
  try {
    const rsp = await fetch("/dreamlayer/live/redeem",
      {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
    let j = {}; try { j = await rsp.json(); } catch (_) {}
    if (rsp.ok && j.token) {
      TOKEN = j.token;
      sessionStorage.setItem("dl-live-token", TOKEN);
      setLink(true, 0);
      if (liveOn) scheduleLoop(600);
      startEvents();                   /* the Brain can now push ambient cards */
      return {ok:true};
    }
    return {ok:false, msg: rsp.status === 429
      ? "too many tries — wait a minute, then a fresh code from the panel"
      : "wrong or expired code — get a fresh one from the panel"};
  } catch (e) { return {ok:false, msg:"brain unreachable"}; }
}
async function redeemCode(raw, noticeEl){
  const msg = noticeEl.querySelector("#pairMsg");
  msg.textContent = "connecting…";
  const r = await doRedeem(raw);
  if (r.ok) {
    noticeEl.remove(); _pairNotice = null;
    showHud("connected · tap the lens", {ms:3000});
    return;
  }
  msg.textContent = r.msg || "couldn't connect";
}

/* ---- optional voice: honest about whose ears these are ------------------ */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  $("mic").hidden = false;
  let rec = null;
  $("mic").onclick = () => {
    if (rec) { rec.stop(); return; }
    const wasCC = captionsOn;
    if (wasCC) stopCaptions(true);        /* one recognizer at a time — pause CC */
    rec = new SR(); rec.lang = navigator.language || "en-US";
    $("mic").setAttribute("aria-pressed", "true");
    showHud("listening (phone speech service)", {ms:3200});
    rec.onresult = e => { $("q").value = e.results[0][0].transcript; ask(); };
    rec.onend = () => {
      $("mic").setAttribute("aria-pressed", "false"); rec = null;
      if (wasCC) startCaptions();          /* resume the captions we paused */
    };
    rec.start();
  };
}

/* ---- live captions: the room's speech, on the glass ----------------------
   The glasses' Live Caption feature, on the phone through the phone's OWN
   speech service (said plainly, like the ask mic). A continuous recognizer
   streams interim + final text into a budget-clamped strip. It is deaf under
   the veil and while backgrounded (the mic is never held hot), and auto-restarts
   when the browser ends a segment. HONEST SCOPE: the transcript is drawn locally
   and never sent to the Brain — but the browser's Web Speech API processes the
   AUDIO in ITS OWN cloud (Chrome→Google, Safari→Apple), so captions are NOT
   offline and are NOT covered by the Brain's LAN-only guarantee. The on-glass
   source label names "your phone's speech service" so the wearer knows whose ear
   it is — this is deliberately distinct from the Brain's on-device ear (the
   Listen button), which never leaves the LAN. */
let captionsOn = false, captionRec = null, captionFinal = "";
function ccAvailable(){ return !!SR; }
if (ccAvailable()) $("ccbtn").hidden = false;
function renderCaptions(finalText, interim){
  const box = $("captions").firstElementChild;
  box.textContent = "";
  const tail = (finalText || "").split(/\s+/).slice(-14).join(" ");   /* ~2 lines */
  if (tail) box.appendChild(document.createTextNode(tail + " "));
  if (interim) {
    const s = document.createElement("span"); s.className = "iim";
    s.textContent = interim; box.appendChild(s);
  }
  const src = document.createElement("span"); src.className = "csrc";
  src.textContent = "live caption · your phone's speech service";
  box.appendChild(src);
  $("captions").classList.toggle("on", captionsOn && !!(tail || interim));
}
function startCaptions(){
  if (!ccAvailable() || veil || captionRec) return;
  captionsOn = true;
  $("ccbtn").classList.add("on");
  $("ccbtn").setAttribute("aria-checked", "true");
  $("privacy").classList.add("hide");
  try {
    captionRec = new SR();
    captionRec.lang = navigator.language || "en-US";
    captionRec.continuous = true;
    captionRec.interimResults = true;
    captionRec.onresult = e => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) captionFinal = (captionFinal + " " + r[0].transcript).trim();
        else interim += r[0].transcript;
      }
      renderCaptions(captionFinal, interim);
    };
    captionRec.onerror = ev => { if (ev && ev.error === "not-allowed") stopCaptions(); };
    captionRec.onend = () => {           /* the browser ends segments — re-arm */
      captionRec = null;
      if (captionsOn && !veil && !document.hidden) { try { startCaptions(); } catch (e) {} }
    };
    captionRec.start();
    renderCaptions(captionFinal, "");
  } catch (e) { stopCaptions(); }
}
function stopCaptions(keepFlag){
  if (!keepFlag) {
    captionsOn = false;
    $("ccbtn").classList.remove("on");
    $("ccbtn").setAttribute("aria-checked", "false");
    $("privacy").classList.remove("hide");
    $("captions").classList.remove("on");
  }
  try { if (captionRec) { captionRec.onend = null; captionRec.stop(); } } catch (e) {}
  captionRec = null;
}
function toggleCaptions(){ if (captionsOn) stopCaptions(); else startCaptions(); }
$("ccbtn").onclick = toggleCaptions;
$("ccbtn").onkeydown = e => { if (e.key === " " || e.key === "Enter") toggleCaptions(); };

/* ---- the phone as the live mic: hear + remember --------------------------
   The wearable's always-on ear, living on the PHONE (not the Mac). Tap it and
   grant mic permission and the phone streams what the room says to your paired
   Brain over the LAN; the Brain transcribes it ON-DEVICE (VAD → ASR ladder) and
   folds it into memory. Distinct from CC above: CC draws the phone's own speech
   on the glass and stores nothing; THIS remembers, and the audio is transcribed
   on the Brain and uploaded nowhere past it. OFF until you tap it (a real opt-in
   the Brain persists as remote_listen_enabled); deaf under the veil and while
   backgrounded — the mic is released, never held hot; the raw PCM is downsampled
   to 16 kHz on the phone and posted in short chunks, never buffered to disk. */
let hearOn = false, hearCtx = null, hearStream = null, hearProc = null;
let hearChunks = [], hearFlush = null;
const HEAR_SR = 16000, HEAR_POST_MS = 320;
function _hearAvailable(){
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
            (window.AudioContext || window.webkitAudioContext));
}
if (_hearAvailable()) $("hearbtn").hidden = false; else $("hearbtn").hidden = true;
function _downTo16k(input, inRate){                 /* Float32 @inRate → Int16 @16k */
  const ratio = inRate / HEAR_SR;
  const outLen = Math.max(0, Math.floor(input.length / ratio));
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++){
    const start = Math.floor(i * ratio), end = Math.floor((i + 1) * ratio);
    let sum = 0, c = 0;
    for (let j = start; j < end && j < input.length; j++){ sum += input[j]; c++; }
    let v = c ? sum / c : 0;
    v = v < -1 ? -1 : v > 1 ? 1 : v;
    out[i] = (v * 32767) | 0;
  }
  return out;
}
let hearWarned = false;   /* one-shot: the Brain has no ASR to transcribe with */
function _flushHear(){
  if (!hearOn) return;
  if (veil || document.hidden){ hearChunks = []; return; }  /* never stream veiled/bg */
  if (!hearChunks.length) return;
  let total = 0; for (const a of hearChunks) total += a.length;
  const merged = new Int16Array(total); let off = 0;
  for (const a of hearChunks){ merged.set(a, off); off += a.length; }
  hearChunks = [];
  /* READ the response — the ear is honest about its own limits. If the Brain has
     no speech-to-text (no Sharp Ears pack), holding the mic hot while nothing is
     transcribed is a lie the "listening" chip tells. Say so once and release the
     mic instead of pretending to listen (audit 2026-07-23). */
  fetch("/dreamlayer/live/hear?sr=" + HEAR_SR,
        {method: "POST", headers: Object.assign(
          {"Content-Type": "application/octet-stream"}, HDRS()),
         body: merged.buffer})
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (j && j.ok === false && j.reason === "no-asr" && !hearWarned){
        hearWarned = true;
        showHud(j.detail || "the Brain can't transcribe yet — install the Sharp Ears pack to let it hear", {ms:4600});
        stopHearing();     /* don't keep the mic hot for a pipeline that can't hear */
      }
    })
    .catch(() => {});
}
function _hearOpen(){                                /* acquire mic + tap the PCM */
  if (hearCtx || veil) return;
  navigator.mediaDevices.getUserMedia(
    {audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}})
    .then(stream => {
      // re-check the FULL posture on resolution: the veil could have gone up (or
      // the page been backgrounded) while getUserMedia was in flight — never
      // open an AudioContext under the shield (the mic must stay released)
      if (!hearOn || veil || document.hidden){ stream.getTracks().forEach(t => t.stop()); return; }
      hearStream = stream;
      hearCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = hearCtx.createMediaStreamSource(stream);
      hearProc = hearCtx.createScriptProcessor(4096, 1, 1);
      hearProc.onaudioprocess = e => {
        if (!hearOn || veil || document.hidden) return;
        hearChunks.push(_downTo16k(e.inputBuffer.getChannelData(0), hearCtx.sampleRate));
      };
      src.connect(hearProc); hearProc.connect(hearCtx.destination);
      hearFlush = setInterval(_flushHear, HEAR_POST_MS);
    })
    .catch(() => { showHud("microphone permission is needed to listen", {ms:2800});
                   stopHearing(); });
}
function _hearClose(){                               /* release the mic + timers */
  if (hearFlush){ clearInterval(hearFlush); hearFlush = null; }
  try { if (hearProc){ hearProc.onaudioprocess = null; hearProc.disconnect(); } } catch (e) {}
  try { if (hearCtx) hearCtx.close(); } catch (e) {}
  try { if (hearStream) hearStream.getTracks().forEach(t => t.stop()); } catch (e) {}
  hearProc = null; hearCtx = null; hearStream = null; hearChunks = [];
  fetch("/dreamlayer/live/hear?stop=1", {method: "POST", headers: HDRS()}).catch(() => {});
}
async function startHearing(){
  if (hearOn || veil || !_hearAvailable()) return;
  hearOn = true; hearWarned = false;   /* re-check ASR each fresh start (pack may now be installed) */
  $("hearbtn").classList.add("on"); $("hearbtn").setAttribute("aria-checked", "true");
  $("hearst").textContent = "listening";
  try {                                             /* persist the opt-in first */
    await fetch("/dreamlayer/config",
      {method: "POST", headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
       body: JSON.stringify({remote_listen_enabled: true})});
  } catch (e) {}
  _hearOpen();
}
function stopHearing(keep){
  if (!keep){                                       /* full off → revoke consent */
    hearOn = false;
    $("hearbtn").classList.remove("on"); $("hearbtn").setAttribute("aria-checked", "false");
    $("hearst").textContent = "listen";
    fetch("/dreamlayer/config",
      {method: "POST", headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
       body: JSON.stringify({remote_listen_enabled: false})}).catch(() => {});
  }
  _hearClose();
}
function toggleHearing(){ if (hearOn) stopHearing(); else startHearing(); }
$("hearbtn").onclick = toggleHearing;
$("hearbtn").onkeydown = e => { if (e.key === " " || e.key === "Enter") toggleHearing(); };
/* veil + backgrounding release the mic but KEEP the intent, so it resumes when
   the shield lifts / the page returns (mirrors the caption discipline) */
document.addEventListener("visibilitychange", () => {
  if (!hearOn) return;
  if (document.hidden) _hearClose(); else if (!veil && !hearCtx) _hearOpen();
});

/* ---- the Brain's push channel: ambient cards it surfaces on its own -------
   The other half of the HUD — not a reply to a look. Over Server-Sent Events
   (/dreamlayer/live/events) the Brain PUSHES cards it decides to raise: a
   sound-safety tap (smoke alarm/glass/siren), the morning brief, a memory
   nudge. EventSource auto-reconnects; the token rides the query because
   EventSource can't set headers (the server never logs it). Only cards ride
   this — no captured audio/pixels — and the Brain veil-gates every non-safety
   push, so under the shield only a safety alert can arrive. */
let evSource = null;
function startEvents(){
  if (evSource || !TOKEN || !window.EventSource) return;
  try {
    evSource = new EventSource("/dreamlayer/live/events?t=" + encodeURIComponent(TOKEN));
    evSource.onmessage = e => {
      let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
      if (ev && ev.card) renderEvent(ev);
    };
    evSource.onerror = () => {};       /* EventSource retries on its own */
  } catch (e) { evSource = null; }
}
function stopEvents(){ try { if (evSource) evSource.close(); } catch (e) {} evSource = null; }
function renderEvent(ev){
  if (dreamOn) return;                 /* never stomp the dream canvas */
  const c = ev.card, t = c && c.type;
  if (t === "HarkCard"){ glassHarkCard(c); try { blip(); } catch (e) {} scan(true); setTimeout(() => scan(false), 500); }
  else if (t === "MorningBriefCard") glassBriefCard(c);
  else glassEventCard(c);              /* any future card type still shows something */
}

/* ---- privacy receipt: the tamper-evident ledger, VERIFIED on THIS phone ----
   GET /dreamlayer/receipt is the hash-chained, Ed25519-signed activity ledger
   + the public key. We verify it HERE, offline: the SHA-256 chain always, and
   the signature when this browser exposes WebCrypto Ed25519 (iOS 17+/Chromium
   137+). The canonical bytes reproduce Python's json.dumps(sort_keys=True,
   separators=(',',':'), ensure_ascii=True) EXACTLY — a known-answer self test
   guards canonCore(), and we degrade to chain-only rather than raise a false
   alarm if it ever drifts. Nothing from the Brain is trusted: the green verdict
   is this phone's own arithmetic, drawn XSS-safe via textContent. */
let RECEIPT = null, ED25519 = null;
function _pyStr(s){ s = (s == null) ? "" : String(s); let o = '"';
  for (const ch of s){ const cp = ch.codePointAt(0);
    if (ch === '"') o += '\\"'; else if (ch === '\\') o += '\\\\';
    else if (cp === 8) o += '\\b'; else if (cp === 9) o += '\\t'; else if (cp === 10) o += '\\n';
    else if (cp === 12) o += '\\f'; else if (cp === 13) o += '\\r';
    else if (cp < 0x20) o += '\\u' + cp.toString(16).padStart(4, '0');
    else if (cp < 0x7F) o += ch;      /* 0x20-0x7E literal; DEL (0x7F) is NOT
                                         printable-ASCII — Python's ensure_ascii
                                         escapes it to \\u007f, so we must too, or
                                         an honest record with a 0x7F byte would
                                         mis-verify as tampered (refute 2026-07-21) */
    else if (cp > 0xFFFF){ const c = cp - 0x10000;
      o += '\\u' + (0xD800 + (c >> 10)).toString(16).padStart(4, '0')
        +  '\\u' + (0xDC00 + (c & 0x3FF)).toString(16).padStart(4, '0'); }
    else o += '\\u' + cp.toString(16).padStart(4, '0'); }
  return o + '"'; }
/* ts is a float from time.time(); Python renders an integer-valued float "N.0" */
function _pyFloat(v){ v = Number(v); return Number.isInteger(v) ? v.toFixed(1) : String(v); }
function canonCore(r){ return '{"kind":' + _pyStr(r.kind) + ',"prev":' + _pyStr(r.prev || "")
  + ',"seq":' + String(r.seq) + ',"text":' + _pyStr(r.text) + ',"ts":' + _pyFloat(r.ts) + '}'; }
function _canonHead(h){ return '{"count":' + String(h.count) + ',"head":' + _pyStr(h.head) + ',"last_seq":' + String(h.last_seq) + '}'; }
const _rcptEnc = new TextEncoder();
async function _sha256hex(bytes){ const h = await crypto.subtle.digest("SHA-256", bytes);
  return Array.prototype.map.call(new Uint8Array(h), b => b.toString(16).padStart(2, '0')).join(''); }
function _hexToBytes(h){ h = h || ""; const a = new Uint8Array(Math.floor(h.length / 2));
  for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
async function _probeEd25519(){ if (ED25519 !== null) return ED25519;
  try { await crypto.subtle.importKey("raw", new Uint8Array(32), {name: "Ed25519"}, false, ["verify"]); ED25519 = true; }
  catch (e) { ED25519 = false; } return ED25519; }
async function _edVerify(pubHex, sigHex, bytes){
  try { const k = await crypto.subtle.importKey("raw", _hexToBytes(pubHex), {name: "Ed25519"}, false, ["verify"]);
    return await crypto.subtle.verify({name: "Ed25519"}, k, _hexToBytes(sigHex), bytes); }
  catch (e) { return false; } }
/* known-answer: matches the Python vector in test_receipt_verify_vectors.py */
function _canonSelfTest(){
  const r = {seq: 2, ts: 1700000000.0, kind: "plugin",
             text: "emoji 🎉 and quote \" and backslash \\", prev: "deadbeef"};
  return canonCore(r) === '{"kind":"plugin","prev":"deadbeef","seq":2,"text":"emoji \\ud83c\\udf89 and quote \\" and backslash \\\\","ts":1700000000.0}'; }
function _rcptRow(rec, bad){
  const li = document.createElement("li");
  if (bad) li.className = "bad";
  const k = document.createElement("span"); k.className = "rk"; k.textContent = String(rec.kind || "");
  const t = document.createElement("span"); t.className = "rt"; t.textContent = String(rec.text || rec.kind || "");
  const s = document.createElement("span"); s.className = "rs"; s.textContent = "seq " + String(rec.seq);
  li.appendChild(k); li.appendChild(t); li.appendChild(s);
  return li;
}
function _renderRecs(badSet){
  const ul = $("rcptlist"); ul.textContent = "";
  const recs = (RECEIPT && RECEIPT.records) || [];
  if (!recs.length) {
    const li = document.createElement("li"); li.textContent = "Nothing recorded yet.";
    ul.appendChild(li); return;
  }
  for (let i = recs.length - 1; i >= 0; i--)
    ul.appendChild(_rcptRow(recs[i], badSet && badSet.has(i)));
}
async function loadReceipt(){
  const rsp = await fetchJSON("/dreamlayer/receipt", {headers: HDRS()}, 9000);
  if (rsp.status === 401) { RECEIPT = null; return "pair"; }
  RECEIPT = rsp.json || null;
  return RECEIPT ? "" : "unreachable";
}
async function verifyReceipt(){
  const head = $("rcpthead"), sub = $("rcptsub"), verdict = $("rcptverdict");
  verdict.className = ""; head.textContent = "Verifying on this phone…"; sub.textContent = "";
  const ld = await loadReceipt();
  if (ld === "pair") { head.textContent = "Pair this phone first";
    sub.textContent = "Connect to your Brain to fetch its signed receipt."; _renderRecs(null); return; }
  if (ld === "unreachable") { verdict.className = "bad"; head.textContent = "Brain unreachable";
    sub.textContent = "Couldn’t fetch the receipt — try again."; _renderRecs(null); return; }
  const r = RECEIPT; const recs = r.records || [];
  _renderRecs(null);
  if (!recs.length) { head.textContent = "No activity recorded yet";
    sub.textContent = r.pubkey ? "The ledger is signed and empty — nothing to prove yet."
                               : "Install the privacy extra so the Brain signs its ledger.";
    return; }
  const canonOK = _canonSelfTest();
  const sigSupported = (await _probeEd25519()) && !!r.pubkey && canonOK;
  let chainOK = true, seqOK = true, sigOK = true, firstBroken = -1;
  let prev = recs[0].prev || "";
  const base = recs[0].seq;
  for (let i = 0; i < recs.length; i++) { const rec = recs[i]; const bytes = _rcptEnc.encode(canonCore(rec));
    if (i > 0 && (rec.prev || "") !== prev) { chainOK = false; if (firstBroken < 0) firstBroken = i; }
    if (rec.seq !== base + i) seqOK = false;
    if (sigSupported && !(await _edVerify(r.pubkey, rec.sig || "", bytes))) { sigOK = false; if (firstBroken < 0) firstBroken = i; }
    prev = await _sha256hex(bytes); }
  let attested = null, tailShort = false, unattested = false, headVerified = false;
  const h = r.head;
  if (sigSupported && h && h.sig) {
    const hOK = await _edVerify(r.pubkey, h.sig, _rcptEnc.encode(_canonHead(h)));
    if (!hOK) { chainOK = false; if (firstBroken < 0) firstBroken = recs.length - 1; }
    else { headVerified = true; attested = h.count; const lastSeq = recs[recs.length - 1].seq;
      if (h.last_seq === lastSeq) { if (h.head !== prev) { chainOK = false; if (firstBroken < 0) firstBroken = recs.length - 1; } }
      else if (h.last_seq < lastSeq) { unattested = true; }
      else { tailShort = true; } } }
  const signedLedger = !!r.pubkey;
  const hardTamper = !chainOK || !seqOK || (sigSupported && !sigOK) || unattested;
  const tailComplete = !signedLedger || (sigSupported && headVerified && !tailShort);
  const fullyVerified = signedLedger && sigSupported && !hardTamper && tailComplete;
  // trust-on-first-use: a signature only proves "consistent under SOME key". A
  // malicious Brain could mint a fresh key and sign a laundered ledger, which
  // would read green — unless we pin the key on first sight and flag a CHANGE.
  // Pinned per-origin (localStorage is already origin-scoped to this Brain);
  // we pin only a fully-verified key, never a tampered one (refute 2026-07-21).
  const fp = signedLedger ? (r.pubkey.slice(0, 8) + "…" + r.pubkey.slice(-4)) : "";
  let keyStatus = "none";
  if (signedLedger) {
    try {
      const pinned = localStorage.getItem("dl-rcpt-key");
      if (!pinned) { if (fullyVerified) localStorage.setItem("dl-rcpt-key", r.pubkey); keyStatus = "first"; }
      else if (pinned === r.pubkey) keyStatus = "same";
      else keyStatus = "changed";
    } catch (e) { keyStatus = "none"; }   /* storage blocked → can't pin */
  }
  const keyChanged = keyStatus === "changed";
  const trulyVerified = fullyVerified && !keyChanged;
  if (trulyVerified) {
    verdict.className = "ok";
    head.textContent = "Verified on this phone · authentic, unaltered";
    sub.textContent = recs.length + (attested && attested > recs.length ? " of " + attested : "")
      + " actions · chain + Ed25519 signature checked here · key " + fp
      + (keyStatus === "first" ? " (trusted from now on)" : "");
    _renderRecs(null);
  } else if (hardTamper) {
    verdict.className = "bad";
    head.textContent = unattested ? "Tampering detected · unattested entries" : "Tampering detected · entry " + (firstBroken + 1);
    sub.textContent = unattested
      ? "The ledger carries entries beyond its signed length — records were appended without the Brain’s key."
      : !chainOK ? "A hash-chain link is broken — an entry was altered or removed after signing."
      : (!seqOK ? "A sequence number is missing — an entry was deleted."
                : "A signature failed — a record was changed after it was signed.");
    const bad = new Set(); for (let i = Math.max(firstBroken, 0); i < recs.length; i++) bad.add(i);
    _renderRecs(bad);
  } else if (keyChanged) {
    verdict.className = "bad";
    head.textContent = "Signing key changed";
    sub.textContent = "This ledger is internally valid, but it’s signed by a DIFFERENT key (" + fp
      + ") than the one this phone trusted before. If you didn’t reset your Brain, don’t trust it.";
    _renderRecs(null);
  } else if (!signedLedger) {
    head.textContent = "Unsigned ledger";
    sub.textContent = "The chain is internally consistent, but this Brain isn’t signing receipts (no privacy extra).";
  } else if (!sigSupported) {
    head.textContent = "Chain intact · signature not checked here";
    sub.textContent = "Every action seals the one before it, but this browser can’t run Ed25519 — verify the signature on the desktop panel.";
  } else if (tailShort) {
    head.textContent = "Recent entries may be missing";
    sub.textContent = "The signed length is " + attested + ", but only " + recs.length + " were returned. The shown actions are authentic — re-verify.";
  } else {
    head.textContent = "Can’t confirm completeness";
    sub.textContent = "The shown actions are authentic, but the signed length anchor is missing — re-verify.";
  }
}
function openReceipt(){ $("rcptcard").classList.add("on"); verifyReceipt(); }
$("rcptbtn").onclick = openReceipt;
$("rcptbtn").onkeydown = e => { if (e.key === " " || e.key === "Enter") openReceipt(); };
$("rcptclose").onclick = () => $("rcptcard").classList.remove("on");
$("rcptverify").onclick = verifyReceipt;

/* ---- backgrounding: stop looking, save battery, resume clean ------------ */
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (dreamOn) exitDream();      /* background tabs keep capturing audio —
                                      the mic must not stay hot (refute F9) */
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
        const r = await fetchJSON("/dreamlayer/status", {headers: HDRS()}, 8000);
        setLink(r.ok, performance.now() - t0);
      } catch (e) { setLink(false, 0); }
    }
    heartbeat();
  }, 10000);
}

/* ---- on-device detector: real recognition IN THE PHONE, zero setup ------
   MediaPipe EfficientDet-Lite0 runs continuous object detection on the video
   frames, right here in the browser — nothing leaves the phone, and no Brain
   vision model is needed, so it's smart for EVERYONE out of the box. Boxes
   anchor labels to the world like the glasses. It degrades cleanly: if the model
   can't load (old device, blocked), the Brain ambient loop takes over. A person
   is NEVER boxed or named — the same "never identify a stranger" line the Brain
   holds, enforced client-side too. All same-origin (the CSP forbids off-origin
   fetches), so the frames never leave the phone for the on-device pass. */
let detector = null, rafId = null, lastDetect = 0, detectFails = 0, overlayDirty = false;
const DETECT_MS = 90;                 /* ~11 fps — smooth, easy on the battery */
const DETECT_MAX_FAILS = 12;          /* ~1s of persistent runtime failure → give up */

/* The MediaPipe module (137 KB) + the FilesetResolver are shared by BOTH the
   object detector and the gesture recognizer — resolve them once and memoize so
   neither re-imports the bundle. (The heavy 9.4 MB WASM is actually compiled
   inside each createFromOptions call, so it still compiles twice; the win isn't
   dedup — it's that we load the two SEQUENTIALLY, below, so their compiles don't
   contend, the detector reaches ready sooner, and the gesture's WASM fetch then
   reuses the detector's warm HTTP cache.) */
let _visionMod = null, _filesetP = null;
function visionFileset(){
  if (!_filesetP) _filesetP = (async () => {
    _visionMod = await import("/dreamlayer/live/assets/vision_bundle.mjs");
    return _visionMod.FilesetResolver.forVisionTasks("/dreamlayer/live/assets/wasm");
  })();
  return _filesetP;
}
/* A stalled asset fetch (headers sent, stream hangs) never resolves NOR rejects,
   so without a cap loadDetector's promise chain would hang forever: the page
   would sit at data-detector="loading" with a "vision loading…" chip that never
   comes true, and — because gestures start in loadDetector's finally — they'd
   never load either. Bound the wait so a stall falls back cleanly instead. Kept
   comfortably above the e2e's 40s detector budget so a slow-but-progressing load
   is never cut off. */
const DETECT_LOAD_MS = 60000;
function withTimeout(p, ms, label){
  return Promise.race([p, new Promise((_, rej) =>
    setTimeout(() => rej(new Error((label || "load") + " timed out")), ms))]);
}
async function loadDetector(){
  /* a visible "warming up" state so the first seconds aren't mistaken for the
     server just naming objects (the honest answer to "is the stack loaded?") */
  document.body.setAttribute("data-detector", "loading");
  setVisionChip(true);
  showHud("loading on-device vision…", {ms:2400, _detector:true});
  try {
    const fileset = await withTimeout(visionFileset(), DETECT_LOAD_MS, "vision runtime");
    detector = await withTimeout(_visionMod.ObjectDetector.createFromOptions(fileset, {
      baseOptions: {modelAssetPath: "/dreamlayer/live/assets/models/efficientdet_lite0.tflite"},
      scoreThreshold: 0.42, maxResults: 6, runningMode: "VIDEO",
      categoryDenylist: ["person"]}), DETECT_LOAD_MS, "detector model");
    detectorActive = true;
    clearTimeout(loopTimer);          /* the browser recognizes now — idle the server loop */
    setVisionChip(false);             /* warm-up done; the tier chip now reads "on-device" */
    setTier("laptop");
    showHud("on-device vision ✨", {ms:1800});
    document.body.setAttribute("data-detector", "on");   /* status (styleable + testable) */
    startDetectLoop();
  } catch (e) {
    fallBackToServer(e, "unavailable");
  } finally {
    /* Gestures load only AFTER the detector attempt SETTLES — success, error, or
       the timeout above — never alongside its warm-up, so their WASM compiles
       don't contend and the detector (the thing that stops the server naming
       loop) wins the race. The timeout guarantees this finally always runs, so a
       stalled detector can't strand gestures. They share the memoized fileset +
       warm HTTP cache, so this stays cheap. */
    startGesture();
  }
}
/* Load OR runtime failure → stop the detector and hand recognition back to the
   Brain ambient loop, so a mid-session WebGL context loss (common on mobile
   under memory pressure) can never leave the page silently blind (refute
   2026-07-20). */
function fallBackToServer(e, why){
  detectorActive = false;
  try { if (detector && detector.close) detector.close(); } catch (_) {}
  detector = null;
  if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; }
  clearOverlayOnce(); hideDetectorHud(); setVisionChip(false);
  document.body.setAttribute("data-detector", "off");
  if (window.console)
    console.warn("[live] on-device detector " + (why || "failed") + " — using Brain looks:", e);
  if (liveOn && booted) scheduleLoop(400);
}
function startDetectLoop(){ if (rafId == null) rafId = requestAnimationFrame(detectTick); }
function clearOverlayOnce(){
  if (!overlayDirty) return;          /* skip the redundant per-frame clear while idle */
  const cv = $("overlay"), ctx = cv.getContext("2d");
  if (ctx) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height); }
  overlayDirty = false;
}
function detectTick(ts){
  rafId = requestAnimationFrame(detectTick);
  if (!detectorActive || !detector || !liveOn || veil || document.hidden
      || !camReady() || !booted || dreamOn) {
    clearOverlayOnce(); hideDetectorHud(); return;    /* idle: wipe boxes + stale label */
  }
  if (ts - lastDetect < DETECT_MS) return;
  lastDetect = ts;
  let res = null;
  try { res = detector.detectForVideo($("cam"), ts); detectFails = 0; }
  catch (e) {
    if (++detectFails >= DETECT_MAX_FAILS) fallBackToServer(e, "failed at runtime");
    return;
  }
  paintDetections(res);
}
function paintDetections(res){
  const cv = $("overlay"), v = $("cam"), ctx = cv.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;            /* crisp brackets on retina */
  const cw = cv.clientWidth, ch = cv.clientHeight;
  const bw = Math.round(cw * dpr), bh = Math.round(ch * dpr);
  if (cv.width !== bw) cv.width = bw;
  if (cv.height !== bh) cv.height = bh;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);              /* draw in CSS px, scaled to device */
  ctx.clearRect(0, 0, cw, ch);
  const vw = v.videoWidth, vh = v.videoHeight;
  if (!vw || !vh) { overlayDirty = false; return; }
  const scale = Math.max(cw / vw, ch / vh);            /* object-fit: cover */
  const ox = (cw - vw * scale) / 2, oy = (ch - vh * scale) / 2;
  const dets = ((res && res.detections) || [])
    .map(d => ({name: ((d.categories && d.categories[0]) || {}).categoryName || "",
                score: ((d.categories && d.categories[0]) || {}).score || 0,
                box: d.boundingBox}))
    .filter(d => d.name && d.name !== "person" && d.box);   /* NEVER a person */
  /* The glasses don't box the room — they hold ONE focus. Pick the dominant
     thing in view (largest × most-confident) and mark just that; everything else
     stays unadorned, so the passive HUD reads like the glass, not a detector
     demo. The name rides the single HUD line below, never a label plate. */
  let top = null, topA = 0;
  for (const d of dets) {
    const a = d.box.width * d.box.height * d.score;
    if (a > topA) { topA = a; top = d; }
  }
  if (top) {
    const x = top.box.originX * scale + ox, y = top.box.originY * scale + oy;
    drawFocus(ctx, x, y, top.box.width * scale, top.box.height * scale);
  }
  overlayDirty = !!top;
  /* update the live label only when no tap/ask result is holding the HUD */
  if (performance.now() >= hudHoldUntil && !looking && !asking && !veil) {
    if (top) showHud([top.name + " · " + Math.round(top.score * 100) + "%"],
                     {persist:true, _detector:true});
    else hideDetectorHud();           /* nothing in view → drop the stale live label */
  }
}
function drawFocus(ctx, x, y, w, h){
  /* one quiet focus mark on the dominant object — corner ticks in the phosphor,
     no label plate (the HUD line carries the name). The glass's language: a
     single held focus, never a wall of boxes. */
  const c = Math.max(10, Math.min(26, w / 4, h / 4));
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(44,199,154,.72)";
  ctx.shadowColor = "rgba(44,199,154,.5)"; ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.moveTo(x, y + c); ctx.lineTo(x, y); ctx.lineTo(x + c, y);
  ctx.moveTo(x + w - c, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + c);
  ctx.moveTo(x + w, y + h - c); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - c, y + h);
  ctx.moveTo(x + c, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - c);
  ctx.stroke(); ctx.shadowBlur = 0;
}

/* ---- on-device hand gestures — HUD navigation without a tap ------------------
   The SAME vendored MediaPipe runtime that powers the object detector also ships
   a GestureRecognizer. It reads hand GEOMETRY only (21 landmarks + a canned
   gesture enum) — never a face, never identity — entirely in-browser on the
   phone's <video>, so nothing about the hand leaves the device and it never
   touches the server look path or person_guard. It drives NAVIGATION, not
   recognition:
     point up   → look at what's in front of you   (lookNow)
     open palm  → clear the HUD                     (glassClear)
     victory    → toggle dream mode                 (toggleDream)
   A gesture fires ONCE when a new hand-shape appears (debounced) — never
   repeatedly while the hand is held. Failure to load is a silent no-op: gestures
   are a bonus, the tap grammar is always there. */
let gesturer = null, gRaf = null, gLastRun = 0, gFails = 0;
let gLastFired = "", gStable = "", gStableCount = 0;
const GESTURE_MS = 120;                /* ~8 fps — lighter than the detector loop */
const GESTURE_MAX_FAILS = 12;
const GESTURE_STABLE = 2;              /* frames a shape must hold before it fires */
const GESTURE_RELEASE = 4;            /* frames the hand must LEAVE before it re-arms */
const GESTURE_MIN_SCORE = 0.6;
const GESTURE_ACTIONS = {
  /* point-up asks the Brain "what's this?" — but a look POSTs the camera frame,
     and dream mode's contract is "nothing egresses", so never look while
     dreaming (lookNow itself has no dream guard — the tap/key paths gate it
     externally, so the gesture path must too) */
  Pointing_Up: () => { if (!dreamOn) lookNow(false); },
  Open_Palm:   () => { glassClear(); hideDetectorHud(); },
  Victory:     () => toggleDream()
};
let _gestureStarted = false;
function startGesture(){        /* idempotent: fallBackToServer can re-enter loadDetector's finally */
  if (_gestureStarted) return;
  _gestureStarted = true;
  loadGesture();
}
async function loadGesture(){
  try {
    const fileset = await withTimeout(visionFileset(), DETECT_LOAD_MS, "vision runtime");
    gesturer = await withTimeout(_visionMod.GestureRecognizer.createFromOptions(fileset, {
      baseOptions: {modelAssetPath: "/dreamlayer/live/assets/models/gesture_recognizer.task"},
      numHands: 1, runningMode: "VIDEO"}), DETECT_LOAD_MS, "gesture model");
    document.body.setAttribute("data-gesture", "on");   /* status (styleable + testable) */
    gRaf = requestAnimationFrame(gestureTick);
  } catch (e) {           /* a stall or failure settles to "off", never hangs data-gesture unset */
    document.body.setAttribute("data-gesture", "off");
    if (window.console) console.warn("[live] gesture recognizer unavailable:", e);
  }
}
function gestureTick(ts){
  gRaf = requestAnimationFrame(gestureTick);
  /* idle guards mirror the detector's — but NOT dreamOn: a Victory must be able
     to leave dream mode, and lookNow already no-ops while dreaming */
  if (!gesturer || !liveOn || veil || document.hidden || !camReady() || !booted) return;
  if (ts - gLastRun < GESTURE_MS) return;
  gLastRun = ts;
  let res = null;
  try { res = gesturer.recognizeForVideo($("cam"), ts); gFails = 0; }
  catch (e) {
    if (++gFails >= GESTURE_MAX_FAILS) {           /* runtime death → stop, silently */
      try { if (gesturer && gesturer.close) gesturer.close(); } catch (_) {}
      gesturer = null;
      if (gRaf != null) { cancelAnimationFrame(gRaf); gRaf = null; }
      document.body.setAttribute("data-gesture", "off");
    }
    return;
  }
  const g = ((res && res.gestures && res.gestures[0]) || [])[0];
  let name = (g && g.categoryName) || "None";
  const score = (g && g.score) || 0;
  /* a below-threshold read is "no clear gesture" — treat it as None for
     latching so a confidence dip on a HELD hand can't look like a new shape */
  if (name !== "None" && score < GESTURE_MIN_SCORE) name = "None";
  /* debounce on the STABLE shape, not the per-frame read: a shape must hold for
     GESTURE_STABLE frames to fire, and the hand must LEAVE (read None) for
     GESTURE_RELEASE frames before the same shape can fire again. So one hold =
     one action — a mid-hold score dip or a 1-frame dropout never re-fires. */
  if (name === gStable) { if (gStableCount < 64) gStableCount++; }
  else { gStable = name; gStableCount = 1; }
  if (gStable === "None") {
    if (gStableCount >= GESTURE_RELEASE) gLastFired = "";   /* hand truly gone → re-arm */
    return;
  }
  if (gStableCount < GESTURE_STABLE) return;   /* not held long enough yet */
  if (gStable === gLastFired) return;          /* already fired for this hold */
  gLastFired = gStable;                         /* consume the slot (mapped or not) */
  const act = GESTURE_ACTIONS[gStable];
  if (!act) return;
  showHud("gesture: " + gStable.replace("_", " ").toLowerCase(), {ms:900});
  try { act(); } catch (_) {}
}

/* ---- boot --------------------------------------------------------------- */
setLive(true);
startCam();
loadDetector();                       /* progressive enhancement — non-blocking; it
                                         loads the on-device gestures once it settles,
                                         so the two never contend during warm-up */
(async () => {                                    /* first link check + posture seed */
  /* a QR that carried the SHORT pairing code (#c=) redeems for the token
     BEFORE the status probe — else an about-to-pair phone 401s and pops the
     pairing modal a beat before it's connected */
  if (!TOKEN && PENDING_CODE) {
    try {
      const r = await doRedeem(PENDING_CODE);
      if (r.ok) showHud("connected · tap the lens", {ms:2600});
    } catch (e) { /* fall through to the status probe / pairing modal */ }
    PENDING_CODE = "";
  }
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
  startEvents();                 /* subscribe to the Brain's push channel (no-op unpaired) */
  startTour(false);              /* first-timers meet Juno; ? replays the tour */
  scheduleLoop(400);
  heartbeat();
})();
</script>
</body>
</html>
"""
