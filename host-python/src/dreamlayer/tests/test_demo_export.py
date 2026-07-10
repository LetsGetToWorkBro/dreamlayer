"""test_demo_export.py — the HUD → compositing-overlay export tool.

The demo composites the *real* HUD over footage. These check the emissive keying
(black → transparent, lit ink → opaque) and that a scene exports the overlays,
manifest, preview, and poster a compositor needs.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from dreamlayer.demo import Scene, Beat, render_scene, emissive
from dreamlayer.hud import renderer as R
from dreamlayer.hud.cards import ALL_SAMPLES


# -- emissive keying ----------------------------------------------------------

def test_black_becomes_transparent_and_ink_opaque():
    card = R.render(ALL_SAMPLES["fact_check"])
    em = emissive(card)
    arr = np.asarray(em.convert("RGBA"))
    alpha = arr[..., 3]
    assert alpha.min() == 0                 # black background keyed out
    assert alpha.max() > 200                # lit text stays opaque
    # a corner (outside the disc, always black) must be fully transparent
    assert alpha[2, 2] == 0


def test_emissive_preserves_size():
    card = R.render(ALL_SAMPLES["juno_reply"])
    assert emissive(card).size == card.size


# -- scene export -------------------------------------------------------------

def test_render_scene_writes_the_full_bundle(tmp_path):
    scene = Scene("t", beats=[
        Beat("fact_check", 0.2, 1.5, anchor=(0.5, 0.4)),
        Beat("answer_ahead", 1.6, 3.0, anchor=(0.5, 0.5)),
    ], size=(480, 854))
    manifest = render_scene(scene, tmp_path, preview_fps=6)

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "preview.gif").exists()
    assert (tmp_path / "poster.png").exists()
    assert (tmp_path / "overlays" / "beat_00.png").exists()
    assert (tmp_path / "overlays" / "beat_01.png").exists()

    # manifest is valid and complete
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["name"] == "t" and m["size"] == [480, 854]
    assert len(m["beats"]) == 2
    assert m["beats"][0]["card_type"] == "FactCheckCard"
    assert m["beats"][0]["overlay"].endswith("beat_00.png")


def test_overlay_is_transparent_rgba(tmp_path):
    render_scene(Scene("t", beats=[Beat("hark", 0.0, 1.0)], size=(360, 640)),
                tmp_path, preview_fps=4)
    ov = Image.open(tmp_path / "overlays" / "beat_00.png")
    assert ov.mode == "RGBA"
    assert np.asarray(ov)[..., 3].min() == 0     # background is see-through


def test_preview_is_a_multiframe_gif(tmp_path):
    render_scene(Scene("t", beats=[Beat("fact_check", 0.0, 1.0)], size=(360, 640)),
                tmp_path, preview_fps=8)
    gif = Image.open(tmp_path / "preview.gif")
    assert getattr(gif, "n_frames", 1) > 1       # it actually animates


def test_cli_sampler_runs(tmp_path):
    from dreamlayer.demo.__main__ import main
    out = tmp_path / "s"
    assert main(["sampler", str(out)]) == 0
    assert (out / "manifest.json").exists()
