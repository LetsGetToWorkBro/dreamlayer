#!/usr/bin/env python3
"""Render the Google Play graphics from the assets the repo already owns.

  python3 scripts/make-play-assets.py        (requires Pillow)

Two jobs:

1. Feature graphic (1024x500, required by Play): the little Mac (the splash
   mark, true-alpha) on the brand starfield, "DreamLayer" in Chicago and the
   subtitle in Space Grotesk — the same composition language as the landing
   page. Written to fastlane/metadata/android/en-US/images/featureGraphic.png.

2. Phone screenshots: Play caps phone screenshots at a 2:1 aspect; the App
   Store frames (1290x2796 / 1242x2688) are 2.17:1 and would be rejected.
   Each shot is scaled to fit and pillarboxed onto a 1080x2160 canvas whose
   color is sampled from the shot's own top edge, so the pillars read as more
   backdrop rather than added bars. Locales without a localized set (ko-KR,
   zh-CN) ship the en-US shots, mirroring the App Store setup. Written to
   fastlane/metadata/android/<locale>/images/phoneScreenshots/.
"""
import glob
import os
import random

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "fastlane", "metadata", "android")
CHICAGO = os.path.join(ROOT, "assets", "fonts", "ChicagoFLF.ttf")
GROTESK = os.path.join(
    ROOT, "node_modules", "@expo-google-fonts", "space-grotesk",
    "500Medium", "SpaceGrotesk_500Medium.ttf",
)

# App Store screenshot dirs -> Play locales (ko/zh have no localized shots;
# they take the en-US set, exactly like the App Store listing does)
SHOT_LOCALES = {
    "en-US": "en-US", "es-ES": "es-ES", "fr-FR": "fr-FR", "de-DE": "de-DE",
    "it": "it-IT", "pt-BR": "pt-BR", "ja": "ja-JP",
}
FALLBACK_TO_EN = ["ko-KR", "zh-CN"]


def feature_graphic() -> None:
    W, H = 1024, 500
    img = Image.new("RGB", (W, H))
    # the icon's starfield: deep indigo, darker toward the bottom
    top, bottom = (60, 53, 92), (36, 31, 56)
    for y in range(H):
        t = y / H
        img.paste(
            tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)),
            (0, y, W, y + 1),
        )
    # pixel stars, seeded so the graphic is reproducible bit-for-bit
    rng = random.Random(88)
    d = ImageDraw.Draw(img)
    for _ in range(70):
        x, y = rng.randrange(W), rng.randrange(H)
        s = rng.choice([2, 2, 3])
        c = rng.choice([(255, 255, 255), (200, 200, 220), (140, 140, 170)])
        d.rectangle([x, y, x + s, y + s], fill=c)

    # the little Mac (splash mark, true alpha), on the left
    mac = Image.open(os.path.join(ROOT, "assets", "splash.png")).convert("RGBA")
    mac = mac.resize((400, 400), Image.LANCZOS)
    img.paste(mac, (40, (H - 400) // 2), mac)

    # wordmark + subtitle, sized to the column right of the Mac
    x, col_w = 470, W - 470 - 44
    size = 88
    while size > 40 and ImageFont.truetype(CHICAGO, size).getlength("DreamLayer") > col_w:
        size -= 2
    chicago = ImageFont.truetype(CHICAGO, size)
    grotesk_size = 34
    while ImageFont.truetype(GROTESK, grotesk_size).getlength("Your memory, on your glasses") > col_w:
        grotesk_size -= 2
    grotesk = ImageFont.truetype(GROTESK, grotesk_size)
    d.text((x, 172), "DreamLayer", font=chicago, fill=(255, 255, 255))
    d.text((x + 4, 182 + size + 16), "Your memory, on your glasses", font=grotesk, fill=(184, 184, 184))
    # the brand teal underline — the one accent
    uy = 182 + size + 16 + grotesk_size + 26
    d.rectangle([x + 4, uy, x + 4 + 280, uy + 6], fill=(11, 107, 82))

    out = os.path.join(META, "en-US", "images")
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, "featureGraphic.png"))
    print("wrote", os.path.relpath(os.path.join(out, "featureGraphic.png"), ROOT))


def pillarbox(src: str, dst: str, W: int = 1080, H: int = 2160) -> None:
    shot = Image.open(src).convert("RGB")
    scale = H / shot.height
    w = round(shot.width * scale)
    resized = shot.resize((w, H), Image.LANCZOS)
    # sample the shot's own top edge for the pillar color so the bars blend
    edge = shot.crop((0, 0, shot.width, 8)).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    canvas = Image.new("RGB", (W, H), edge)
    canvas.paste(resized, ((W - w) // 2, 0))
    canvas.save(dst)


def screenshots() -> None:
    for src_locale, play_locale in SHOT_LOCALES.items():
        srcs = sorted(glob.glob(os.path.join(ROOT, "fastlane", "screenshots", src_locale, "0*.png")))
        out = os.path.join(META, play_locale, "images", "phoneScreenshots")
        os.makedirs(out, exist_ok=True)
        for s in srcs:
            pillarbox(s, os.path.join(out, os.path.basename(s)))
        print(f"{play_locale}: {len(srcs)} screenshots")
    en = sorted(glob.glob(os.path.join(META, "en-US", "images", "phoneScreenshots", "0*.png")))
    for play_locale in FALLBACK_TO_EN:
        out = os.path.join(META, play_locale, "images", "phoneScreenshots")
        os.makedirs(out, exist_ok=True)
        for s in en:
            Image.open(s).save(os.path.join(out, os.path.basename(s)))
        print(f"{play_locale}: {len(en)} screenshots (en-US set)")


if __name__ == "__main__":
    feature_graphic()
    screenshots()
