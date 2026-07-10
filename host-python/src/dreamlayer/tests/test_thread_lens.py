"""test_thread_lens.py — Thread Lens (INNOVATION_SESSION 4.1): steal color from
the world. Extract a palette from a snapshot, save it as a taught memory; the
image is never stored, only the swatches. Veil-gated."""
from __future__ import annotations

from io import BytesIO

from dreamlayer.main import build
from dreamlayer.object_lens.palette_extract import extract_palette


def _bands(colors) -> bytes:
    """A PNG of vertical color bands."""
    from PIL import Image
    w, h, n = 60, 20, len(colors)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        c = colors[min(n - 1, x * n // w)]
        for y in range(h):
            px[x, y] = c
    b = BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _dominant_channel(hexs):
    """Which of r/g/b dominates in each swatch."""
    out = []
    for hx in hexs:
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        out.append("rgb"[[r, g, b].index(max(r, g, b))])
    return out


def test_extract_palette_returns_valid_hex_swatches():
    sw = extract_palette(_bands([(220, 20, 20), (20, 220, 20), (20, 20, 220)]), k=6)
    assert 3 <= len(sw) <= 6
    assert all(len(s) == 7 and s.startswith("#") for s in sw)
    # red, green, and blue bands should each surface a dominant-channel swatch
    doms = set(_dominant_channel(sw))
    assert {"r", "g", "b"}.issubset(doms)


def test_extract_palette_handles_garbage():
    assert extract_palette(b"not an image") == []


def test_thread_saves_a_palette_memory():
    orch = build(":memory:")
    r = orch.thread(_bands([(200, 30, 30), (30, 200, 30)]), place="Oaxaca market")
    assert r["ok"] and len(r["swatches"]) >= 2 and r["place"] == "Oaxaca market"
    rows = orch.db.conn.execute(
        "SELECT summary, meta FROM memories WHERE kind='taught'").fetchall()
    assert rows and rows[0][0].startswith("palette ")
    import json
    assert json.loads(rows[0][1])["place"] == "Oaxaca market"


def test_thread_is_veil_gated():
    orch = build(":memory:")
    orch.privacy.pause()
    assert orch.thread(_bands([(1, 2, 3)]))["ok"] is False


def test_thread_reports_no_palette_on_garbage():
    orch = build(":memory:")
    assert orch.thread(b"nope")["ok"] is False
