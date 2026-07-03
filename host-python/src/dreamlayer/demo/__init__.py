"""dreamlayer.demo — export the real HUD as compositing-ready overlays.

Turn a storyboard (a timed list of real HUD cards) into transparent, emissive
overlay PNGs + a manifest + a preview, ready to drop over first-person footage.
The HUD is always the actual renderer output — the demo never fakes the UI.

    from dreamlayer.demo import Scene, Beat, render_scene
    render_scene(Scene("veritas", beats=[Beat("fact_check", 1.0, 6.0)]), "out/")
"""
from .scene import Scene, Beat, render_scene
from .emissive import emissive, glow

__all__ = ["Scene", "Beat", "render_scene", "emissive", "glow"]
