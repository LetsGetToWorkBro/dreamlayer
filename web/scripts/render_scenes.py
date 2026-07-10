"""Render the landing page's source assets from the real product renderer.

Everything visual on the site that reads as "the HUD" comes out of this script,
which only calls the repo's own tooling:

  scenes/<name>/   demo storyboards (dreamlayer.demo) — transparent emissive
                   overlays + manifest.json + poster.png
  plates/          synth_plate POV stand-ins at 16:9 and 9:16, one seed per act
  cards/           individual HUD cards, emissive-keyed to transparent RGBA
  motion/          real device animations (Lua renderer via the raster harness)

Usage:  python3 scripts/render_scenes.py [out_root]   (default: .asset-src)
Deterministic: fixed seeds, fixed card content — reruns are byte-stable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
REPO = WEB.parent

from dreamlayer.demo.plate import synth_plate            # noqa: E402
from dreamlayer.demo.emissive import emissive, glow      # noqa: E402
from dreamlayer.demo.scene import Scene, Beat, render_scene  # noqa: E402
from dreamlayer.demo.storyboards import SCENES           # noqa: E402
from dreamlayer.hud import cards, renderer               # noqa: E402

# The three shipped storyboards used by the pinned acts.
STORYBOARDS = ["veritas", "answer_ahead", "owe_someone"]

# The Juno act, composed here from the same real cards the storyboards use.
def _juno() -> Scene:
    return Scene("juno", size=(1080, 1920), beats=[
        Beat(cards.listening(source="voice"),
             t_in=0.8, t_out=3.4, anchor=(0.5, 0.44), width=0.5,
             label="wake — it hears you"),
        Beat(cards.spoken_caption("You", "Book the corner table for four, and tell Priya."),
             t_in=1.4, t_out=5.2, anchor=(0.5, 0.82), width=0.6, glow=False,
             label="you ask for the whole errand"),
        Beat(cards.juno_reply("Booked for 7:30. Priya has the time.", "action"),
             t_in=5.6, t_out=11.0, anchor=(0.5, 0.44), width=0.52,
             label="done — both halves"),
    ], note="Ask it to do anything; the reply is the receipt.")

# Curated cards for the hero, catalog grid, and privacy section.
CARD_KEYS = [
    "answer_ahead", "fact_check", "juno_reply", "hark",
    "commitment_recall", "commitment_drift", "object_recall",
    "privacy_veil", "forget_last", "morning_brief", "person_dossier",
    "truth_gauge", "live_caption", "saved_memory", "query_listening",
]

# One plate seed per section so each act sits in a subtly different room.
PLATE_SEEDS = {"hero": 5, "veritas": 7, "answer_ahead": 11,
               "owe_someone": 23, "juno": 41, "close": 13}
PLATE_WIDE = (1600, 900)
PLATE_TALL = (810, 1440)


def main(out_root: str = ".asset-src") -> None:
    root = (WEB / out_root).resolve() if not Path(out_root).is_absolute() \
        else Path(out_root)

    # 1. Storyboard scenes (real overlays + manifests).
    for name in STORYBOARDS:
        m = render_scene(SCENES[name], root / "scenes" / name)
        print(f"scene {name}: {len(m['beats'])} beats, {m['duration']}s")
    m = render_scene(_juno(), root / "scenes" / "juno")
    print(f"scene juno: {len(m['beats'])} beats, {m['duration']}s")

    # 2. POV plates.
    plates = root / "plates"
    plates.mkdir(parents=True, exist_ok=True)
    for name, seed in PLATE_SEEDS.items():
        synth_plate(PLATE_WIDE, seed).save(plates / f"{name}-wide.png")
        synth_plate(PLATE_TALL, seed).save(plates / f"{name}-tall.png")
    print(f"plates: {len(PLATE_SEEDS)} seeds x 2 aspects")

    # 3. Individual cards, emissive-keyed like the scene overlays.
    cards_dir = root / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    for key in CARD_KEYS:
        img = glow(emissive(renderer.render(cards.ALL_SAMPLES[key])))
        img.save(cards_dir / f"{key}.png")
    print(f"cards: {len(CARD_KEYS)} emissive renders")

    # 4. Real device motion (Lua renderer stepped headlessly; needs lupa).
    motion = root / "motion"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "export_meridian_motion.py"),
         str(motion)],
        check=True, cwd=REPO,
    )
    print(f"motion: exported to {motion}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".asset-src")
