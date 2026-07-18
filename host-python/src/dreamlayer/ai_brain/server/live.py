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

from ...reality_compiler.v2.figment import MAX_LINES, MAX_TEXT_LEN

log = logging.getLogger("dreamlayer.live")

# A camera frame is a downscaled JPEG a phone posts a few times a minute —
# 4 MiB is generous headroom for that and a hard wall against abuse (the
# server's _raw() turns anything larger into a 413 before reading it).
MAX_FRAME_BYTES = 4 * 1024 * 1024

# Frames are thumbnailed to this max side before classification: the vision
# ladder's features are scale-tolerant and this bounds CPU per look.
_MAX_SIDE = 512

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
    bytes aren't an image or Pillow isn't installed. Never touches disk."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.thumbnail((_MAX_SIDE, _MAX_SIDE))
        return np.asarray(im.convert("RGB"))
    except Exception:
        return None


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


def _local_look(brain, arr) -> dict:
    """The egress-shielded rung: the in-process classifier ladder only. Runs
    while the wearer's shield is up (incognito) — nothing leaves, nothing is
    written — and as the honest floor when the World lens can't serve."""
    try:
        hit = _classifier()(arr)
    except Exception as exc:                      # a backend blew up mid-frame
        log.warning("[live] vision ladder failed: %s", exc)
        hit = None
    if not hit:
        return {"ok": True, "label": "", "confidence": 0.0, "tier": "laptop",
                "lines": wrap_hud_lines("nothing I recognize yet")}
    label, conf = hit
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
    if not brain.incognito_now():             # incognito ⇒ leave no on-disk trace
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


def world_look(brain, arr) -> dict:
    """One unified Look — the single pipeline behind BOTH the browser's tap and
    the phone app's shutter, so the two surfaces are one thing.

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
    if brain.incognito_now():
        out = _local_look(brain, arr)
        out["local_only"] = True                # the shield is up — say so
        return _with_min_panel(out)
    wl = None
    try:
        wl = brain.world_lens()
    except Exception as exc:
        log.warning("[live] world lens unavailable: %s", exc)
    panel = None
    if wl is not None:
        try:
            panel = wl.look(arr)
        except Exception as exc:                # a look never dies on a provider
            log.warning("[live] world look failed: %s", exc)
    if panel is None:
        return _with_min_panel(_local_look(brain, arr))   # the honest floor
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


def look(brain, data: bytes) -> dict:
    """One browser Look: decode the posted frame in memory, run the unified
    pipeline (:func:`world_look`). Frames never touch disk; the wearer's
    egress shield makes the look local-only; a plugin row is built from the
    extracted label/fields, never the pixels."""
    return world_look(brain, decode_frame(data))


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
# glass. NOT an f-string: raw braces below are CSS/JS.
_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>DreamLayer &middot; Live Lens</title>
<style__NONCE__>
  :root{
    --phos:#7DFFA8; --phos-dim:#3F8F5C; --amber:#FFC46B; --bg:#050807;
    --lens: min(78vmin, 560px);
  }
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  html,body{height:100%;background:var(--bg);overflow:hidden;
    font:14px/1.45 ui-monospace,Menlo,Consolas,monospace;color:var(--phos)}
  video{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;
    filter:saturate(.85) brightness(.9)}
  /* the world dims beyond the lens — attention lives in the circle */
  #veilshade{position:fixed;inset:0;pointer-events:none;
    background:radial-gradient(circle calc(var(--lens)/2) at 50% 46%,
      rgba(5,8,7,0) 62%, rgba(5,8,7,.62) 100%);}
  #lens{position:fixed;left:50%;top:46%;width:var(--lens);height:var(--lens);
    transform:translate(-50%,-50%);border-radius:50%;cursor:pointer;
    border:1px solid rgba(125,255,168,.5);
    box-shadow:0 0 44px rgba(125,255,168,.16), inset 0 0 60px rgba(125,255,168,.05);
    display:flex;align-items:center;justify-content:center;text-align:center}
  #lens:active{box-shadow:0 0 60px rgba(125,255,168,.3), inset 0 0 60px rgba(125,255,168,.1)}
  #hud{white-space:pre;letter-spacing:.06em;font-size:clamp(13px,2.6vmin,19px);
    text-shadow:0 0 10px rgba(125,255,168,.75);opacity:0;transition:opacity .28s}
  #hud.on{opacity:1}
  #hint{position:fixed;left:50%;top:calc(46% + var(--lens)/2 + 14px);
    transform:translateX(-50%);color:var(--phos-dim);font-size:12px;
    letter-spacing:.1em;text-transform:uppercase}
  /* status chips */
  #chips{position:fixed;top:calc(env(safe-area-inset-top,0px) + 10px);left:0;right:0;
    display:flex;justify-content:center;gap:8px;flex-wrap:wrap;padding:0 10px}
  .chip{border:1px solid rgba(125,255,168,.35);border-radius:3px;padding:3px 9px;
    font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--phos-dim);
    background:rgba(5,8,7,.55);backdrop-filter:blur(2px)}
  .chip b{color:var(--phos);font-weight:normal}
  .chip.warn{color:var(--amber);border-color:rgba(255,196,107,.45)}
  #veilbtn{cursor:pointer;user-select:none}
  #veilbtn.on{color:var(--amber);border-color:rgba(255,196,107,.6)}
  /* ask bar */
  #bar{position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;
    padding:10px 12px calc(env(safe-area-inset-bottom,0px) + 12px);
    background:linear-gradient(transparent, rgba(5,8,7,.88) 40%)}
  #q{flex:1;background:rgba(5,8,7,.8);border:1px solid rgba(125,255,168,.4);
    border-radius:3px;color:var(--phos);padding:11px 12px;font:inherit;min-width:0}
  #q::placeholder{color:var(--phos-dim)}
  #q:focus{outline:none;border-color:var(--phos)}
  button{background:rgba(5,8,7,.8);border:1px solid rgba(125,255,168,.5);
    border-radius:3px;color:var(--phos);font:inherit;padding:11px 14px;cursor:pointer}
  button:active{background:rgba(125,255,168,.15)}
  #mic[aria-pressed="true"]{color:var(--amber);border-color:var(--amber)}
  /* full-screen notices (no camera / no token) */
  .notice{position:fixed;left:50%;top:46%;transform:translate(-50%,-50%);
    width:min(86vw,420px);border:1px solid rgba(255,196,107,.5);border-radius:4px;
    background:rgba(5,8,7,.92);color:var(--amber);padding:16px 18px;font-size:13px}
  .notice h2{font-size:13px;letter-spacing:.14em;margin-bottom:8px}
  .notice p{color:#CDBB96;margin-top:6px}
  .notice code{color:var(--phos)}
  #privacy{position:fixed;bottom:calc(env(safe-area-inset-bottom,0px) + 68px);
    left:0;right:0;text-align:center;color:var(--phos-dim);font-size:10.5px;
    letter-spacing:.08em;padding:0 16px}
  @media (prefers-reduced-motion: reduce){ #hud{transition:none} }
</style>
</head>
<body>
<video id="cam" autoplay playsinline muted></video>
<div id="veilshade"></div>
<div id="lens" role="button" aria-label="Look — classify what the camera sees" tabindex="0">
  <div id="hud" aria-live="polite"></div>
</div>
<div id="hint">tap the lens to look</div>
<div id="chips">
  <span class="chip" id="link">&#9679; <b id="linkst">linking&hellip;</b></span>
  <span class="chip" id="tier" hidden><b id="tiertx"></b></span>
  <span class="chip" id="veilbtn" role="switch" aria-checked="false" tabindex="0">veil <b id="veilst">off</b></span>
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

/* ---- credential: URL fragment -> sessionStorage, then scrubbed ---------- */
let TOKEN = sessionStorage.getItem("dl-live-token") || "";
if (location.hash.startsWith("#t=")) {
  TOKEN = decodeURIComponent(location.hash.slice(3));
  sessionStorage.setItem("dl-live-token", TOKEN);
  history.replaceState(null, "", location.pathname);   /* never re-shared */
}
const HDRS = () => TOKEN ? {"X-DreamLayer-Token": TOKEN} : {};

const $ = id => document.getElementById(id);
let veil = false, holdTimer = null;

/* ---- HUD: one thought at a time, the glass's budget --------------------- */
const enc = new TextEncoder();
function wrapLines(text){
  const out = []; let cur = "";
  for (let w of (text||"").split(/\\s+/).filter(Boolean)) {
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
    while (enc.encode(last + "\\u2026").length > BOOT.maxTextLen) last = last.slice(0,-1);
    out[BOOT.maxLines-1] = last + "\\u2026";
  }
  return out;
}
function card(lines, holdMs){
  const hud = $("hud");
  hud.textContent = lines.join("\\n");
  hud.classList.add("on");
  blip();
  clearTimeout(holdTimer);
  holdTimer = setTimeout(() => hud.classList.remove("on"), holdMs || 6000);
}
function showText(text, holdMs){ card(wrapLines(text), holdMs); }

/* a quiet synthesized hark — no assets, no autoplay (first card follows a tap) */
let actx = null;
function blip(){
  try {
    actx = actx || new (window.AudioContext||window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain();
    o.frequency.value = 880; g.gain.value = 0.04;
    o.connect(g); g.connect(actx.destination);
    o.start(); o.stop(actx.currentTime + 0.06);
  } catch (e) { /* silence is fine */ }
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
function setVeil(on){
  veil = on;
  $("veilst").textContent = on ? "on" : "off";
  $("veilbtn").classList.toggle("on", on);
  $("veilbtn").setAttribute("aria-checked", String(on));
  showText(on ? "veil down \\u00b7 on-device only" : "veil lifted", 2600);
}
$("veilbtn").onclick = () => setVeil(!veil);
$("veilbtn").onkeydown = e => { if (e.key===" "||e.key==="Enter") setVeil(!veil); };

/* ---- camera ------------------------------------------------------------- */
let camOK = false;
async function startCam(){
  if (!window.isSecureContext) {
    notice("CAMERA NEEDS THE SECURE LINK",
      "<p>Browsers only open cameras on a secure page. Start the Brain with <code>--tls</code> and scan the <b>https</b> QR from the panel (accept the one-time certificate warning &mdash; it is your own Brain's).</p><p>Asking works right here meanwhile.</p>");
    return;
  }
  try {
    const s = await navigator.mediaDevices.getUserMedia(
      {video: {facingMode: "environment"}, audio: false});
    $("cam").srcObject = s; camOK = true;
  } catch (e) {
    notice("CAMERA DECLINED",
      "<p>Grant camera access to look at the world. Asking still works below.</p>");
  }
}
function notice(title, html){
  const n = document.createElement("div");
  n.className = "notice"; n.innerHTML = "<h2>"+title+"</h2>"+html;
  n.onclick = () => n.remove();
  document.body.appendChild(n);
}

/* ---- look: frame -> YOUR brain -> label (never during the veil) --------- */
let looking = false;
async function lookNow(){
  if (veil) { showText("the veil is down", 2200); return; }
  if (!camOK) { showText("no camera \\u00b7 ask below", 2600); return; }
  if (looking) return;
  looking = true;
  showText("looking\\u2026", 8000);
  try {
    const v = $("cam");
    const k = Math.min(1, 512 / Math.max(v.videoWidth, v.videoHeight));
    const c = document.createElement("canvas");
    c.width = (v.videoWidth * k) | 0; c.height = (v.videoHeight * k) | 0;
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.8));
    const t0 = performance.now();
    const rsp = await fetch("/dreamlayer/live/look",
      {method: "POST", headers: HDRS(), body: blob});
    const j = await rsp.json();
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) return needsPairing();
    if (j.ok && j.lines) { card(j.lines); setTier(j.tier || "laptop"); }
    else showText(j.reason || "look failed", 4000);
  } catch (e) { setLink(false, 0); showText("brain unreachable", 4000); }
  finally { looking = false; }
}
$("lens").onclick = lookNow;
$("lens").onkeydown = e => { if (e.key===" "||e.key==="Enter") lookNow(); };

/* ---- ask: the production route, the wearer's posture attached ----------- */
async function ask(){
  const q = $("q").value.trim();
  if (!q) return;
  $("q").value = "";
  showText("thinking\\u2026", 12000);
  try {
    const t0 = performance.now();
    const rsp = await fetch("/dreamlayer/brain/ask", {
      method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, HDRS()),
      body: JSON.stringify({query: q, no_cloud: veil})});
    const j = await rsp.json();
    setLink(rsp.ok, performance.now() - t0);
    if (rsp.status === 401) return needsPairing();
    if (j.text) { showText(j.text, 9000); setTier(j.tier); }
    else showText(veil ? "nothing on-device" : "no answer", 4000);
  } catch (e) { setLink(false, 0); showText("brain unreachable", 4000); }
}
$("send").onclick = ask;
$("q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });

function needsPairing(){
  notice("NOT PAIRED",
    "<p>Open the panel on the Brain's computer &rarr; <b>Connections &rarr; Live Lens</b> and scan the QR &mdash; the link carries your pairing token.</p>");
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
    showText("listening (phone speech service)", 3200);
    rec.onresult = e => { $("q").value = e.results[0][0].transcript; ask(); };
    rec.onend = () => { $("mic").setAttribute("aria-pressed", "false"); rec = null; };
    rec.start();
  };
}

/* ---- boot --------------------------------------------------------------- */
startCam();
(async () => {                                    /* first link check */
  try {
    const t0 = performance.now();
    const r = await fetch("/dreamlayer/status", {headers: HDRS()});
    setLink(r.ok, performance.now() - t0);
    if (r.status === 401) needsPairing();
  } catch (e) { setLink(false, 0); }
})();
</script>
</body>
</html>
"""
