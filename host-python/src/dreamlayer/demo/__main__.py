"""CLI: render a storyboard to overlays + preview.

    python -m dreamlayer.demo <name> <out_dir>
    python -m dreamlayer.demo --list

`<name>` is a storyboard from dreamlayer.demo.storyboards; with no name a small
built-in sampler is rendered so the tool always runs.
"""
from __future__ import annotations

import sys

from .scene import Scene, Beat, render_scene


def _sampler() -> Scene:
    return Scene("sampler", beats=[
        Beat("fact_check", 0.5, 4.0, anchor=(0.5, 0.42), label="Veritas"),
        Beat("answer_ahead", 4.2, 8.0, anchor=(0.5, 0.46), label="Answer-ahead"),
        Beat("hark", 8.2, 11.5, anchor=(0.5, 0.4), label="Listen!"),
    ])


def main(argv: list[str]) -> int:
    args = [a for a in argv if a]
    if "--list" in args:
        try:
            from .storyboards import SCENES
            print("\n".join(sorted(SCENES)))
        except Exception:
            print("sampler")
        return 0

    name = args[0] if args else "sampler"
    out = args[1] if len(args) > 1 else f"demo_out/{name}"

    if name == "all":
        from .storyboards import build_all
        root = args[1] if len(args) > 1 else "demo_out"
        manifests = build_all(root)
        for nm, m in manifests.items():
            print(f"rendered '{nm}' → {root}/{nm} "
                  f"({len(m['beats'])} beats, {m['duration']}s)")
        return 0

    if name == "catalog":
        from .catalog import build_catalog
        root = args[1] if len(args) > 1 else "demo_out/catalog"
        manifests = build_catalog(root)
        master = manifests["master"]
        print(f"rendered {len(manifests) - 1} feature clips + master "
              f"({len(master['beats'])} features, {master['duration']}s) → {root}")
        return 0

    scene = None
    if name != "sampler":
        try:
            from .storyboards import SCENES
            scene = SCENES.get(name)
        except Exception:
            scene = None
    if scene is None:
        scene = _sampler()

    manifest = render_scene(scene, out)
    print(f"rendered '{scene.name}' → {out} "
          f"({len(manifest['beats'])} beats, {manifest['duration']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
