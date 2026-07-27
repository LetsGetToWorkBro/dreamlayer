"""Shared module-level helpers for the Orchestrator ops mixins.

Moved out of orchestrator.py so the mixin modules can import them without a
cycle (orchestrator imports the mixins; the mixins import from here).
Behaviour is byte-identical to the originals.
"""
from __future__ import annotations
import json
import urllib.request


def _default_http_get(url: str, token: str = "") -> dict:
    """Minimal GET the message poller uses to reach the paired Mac mini Brain."""
    headers = {"X-DreamLayer-Token": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _default_http_post(url: str, body: dict, token: str = "") -> dict:
    """Minimal POST used to push the Juno profile to the paired Mac mini Brain."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-DreamLayer-Token"] = token
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_scene_reply(text: str):
    """Parse a vision tier's one-line scene classification into a GlanceReading.
    Tolerant: 'SCENE: form — density=0.7 fields=4' and looser shapes both work."""
    import re
    from .glance import GlanceReading, SCENES
    t = (text or "").strip()
    m = re.search(r"scene\s*[:\-]?\s*([a-z_]+)", t, re.IGNORECASE)
    scene = (m.group(1).lower() if m else "")
    if scene not in SCENES:
        # Fall back to the first known scene word anywhere in the reply — but not
        # "sky", which unlike "form"/"shelf"/"menu" is ordinary scenery language: a
        # vision tier describing "a clear sky above a person" or "sky and a shelf of
        # bottles" means the PERSON and the SHELF, and this loose scan was hijacking
        # both into a scene the reply never classified.
        loose = {s for s in SCENES if s != "sky"}
        scene = next((w for w in re.findall(r"[a-z_]+", t.lower()) if w in loose), "unknown")
    signals: dict = {}
    d = re.search(r"density\s*=\s*([0-9.]+)", t, re.IGNORECASE)
    if d:
        try: signals["text_density"] = float(d.group(1))
        except ValueError: pass
    f = re.search(r"fields?\s*=\s*(\d+)", t, re.IGNORECASE)
    if f:
        signals["form_fields"] = int(f.group(1))
    # `items` is now asked for in the prompt, because on the glasses the vision tier
    # is the ONLY witness for a shelf — image statistics are not allowed to claim
    # one, and there is no phone detector on this path.
    it = re.search(r"items?\s*=\s*(\d+)", t, re.IGNORECASE)
    if it:
        signals["items"] = max(0, min(24, int(it.group(1))))
    lg = re.search(r"lang\w*\s*=\s*([a-z\-]+)", t, re.IGNORECASE)
    if lg:
        signals["language"] = lg.group(1).lower()
    # An explicit tag wins over the shape of the prose. The old test was
    # `question=yes  OR  "?" in t`, so a reply that said `question=no` and then
    # asked the wearer anything ("Anything else?") -- or that wrote `fields=?`
    # for an unknown count -- set question=True and fired "Answer it" (0.62) over
    # a page of dense legal prose instead of offering "Plain words". The bare-`?`
    # sniff survives only as a fallback for a reply that omits the tag entirely.
    q = re.search(r"question\s*=\s*(yes|true|1|no|false|0)", t, re.IGNORECASE)
    if q is not None:
        signals["question"] = q.group(1).lower() in ("yes", "true", "1")
    elif "?" in t:
        signals["question"] = True
    conf = 0.8 if scene != "unknown" else 0.3
    return GlanceReading(scene, conf, signals)


def _parse_taste_reply(text: str):
    """Parse a vision tier's shelf/menu listing into TasteItems. Lenient about
    the 'NAME | ingredients | price | rating' shape: missing fields are fine,
    '?' means unknown, a bare '$3.20' or '4.6' anywhere in a field is picked up."""
    import re
    from .taste import TasteItem
    items = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if not line or line.startswith(("NAME", "http")):
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0].strip(" .")
        if not name or name == "?":
            continue
        text_field = parts[1] if len(parts) > 1 and parts[1] not in ("?", "") else ""
        price = rating = None
        pm = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", parts[2]) if len(parts) > 2 else None
        if pm:
            price = float(pm.group(1))
        rm = re.search(r"(\d(?:\.\d)?)\s*(?:/\s*5|★|stars?)?", parts[3]) if len(parts) > 3 else None
        if rm:
            try:
                r = float(rm.group(1))
                rating = r if 0 <= r <= 5 else None
            except ValueError:
                pass
        items.append(TasteItem(label=name, text=text_field, price=price, rating=rating))
    return items
