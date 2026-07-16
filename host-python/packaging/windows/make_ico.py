"""make_ico.py — build dreamlayer.ico from the shared packaging art.

    cd host-python/packaging/windows
    python make_ico.py            # -> dreamlayer.ico

The Windows twin of the .icns step in build-macos-app.yml, with the same
size split: the detailed "little Mac" icon (icon.png) can't read below
~64px, so the small slots (16/24/32) use the dedicated simplified mark
(icon_small.png — the teal ring on the dusk squircle) and the larger slots
downscale icon.png. Pillow only — no ImageMagick to install.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ART = HERE.parent                       # host-python/packaging

# (pixel size, source art) — largest first; Explorer/taskbar pick per-DPI
SLOTS = [
    (256, "icon.png"),
    (128, "icon.png"),
    (64, "icon.png"),
    (48, "icon.png"),
    (32, "icon_small.png"),
    (24, "icon_small.png"),
    (16, "icon_small.png"),
]


def main() -> int:
    frames = []
    for size, name in SLOTS:
        src = Image.open(ART / name).convert("RGBA")
        frames.append(src.resize((size, size), Image.LANCZOS))
    out = HERE / "dreamlayer.ico"
    frames[0].save(out, format="ICO", append_images=frames[1:])
    print(f"wrote {out} ({', '.join(str(s) for s, _ in SLOTS)} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
