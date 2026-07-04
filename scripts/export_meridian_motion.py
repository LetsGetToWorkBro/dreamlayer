"""Export Meridian Lumen motion sequences as PNG frames + animated GIFs.

Steps the integrated device Lua (renderer/horizon/focus/prism) on a
controlled 50ms clock through the raster harness and writes every shown
frame — the headless way to SEE the aurora flow, the focus physics, the
palette chase, the shatter, the wake ring, and the prism bloom before a
device session.

Usage:
    python scripts/export_meridian_motion.py [out_dir]
(defaults to out/meridian_motion/)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "host-python" / "src"))

from dreamlayer.bridge.lua_raster import LuaRasterHarness  # noqa: E402

TICK_MS = 50

DAY_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " 450,102, 380,101, 100,101, -60,302,"
    " -300,102, -350,101, -700,102, -860,102,"
    " -1350,222, -2100,212, 580,401, -900,601 } }"
)

OBJECT_CARD = """{
  type = "ObjectRecallCard", object = "KEYS", primary = "Keys",
  place = "Kitchen table", detail = "beside blue notebook",
  last_seen = "Last seen 7:42 PM", confidence = 0.9, origin_deg = 0,
}"""

SAVED_CARD = '{ type = "SavedMemoryCard", primary = "House keys" }'
LOADING_CARD = '{ type = "LoadingCard" }'


class Session:
    def __init__(self) -> None:
        self.h = LuaRasterHarness()
        self.h.execute("__now = 0")
        self.h.execute('_r  = require("display.renderer")')
        self.h.execute('_hz = require("display.horizon")')
        self.h.execute('require("display/dream_renderer")')
        self.h.execute('_pr = require("display/prism")')
        self.h.execute("_r.bind(nil, function() return __now end)")
        self.h.execute("_hz._now_ms = function() return __now end")
        self.h.sync_dynamic_slots()
        self.now = 0

    def run(self, ms: int) -> None:
        for _ in range(max(1, ms // TICK_MS)):
            self.now += TICK_MS
            self.h.execute(f"__now = {self.now}")
            self.h.execute("_r.tick()")

    def run_prism(self, ms: int) -> None:
        for _ in range(max(1, ms // TICK_MS)):
            self.now += TICK_MS
            self.h.execute(f"__now = {self.now}")
            self.h.execute(
                "frame.display.clear(0x000000); "
                f"_pr.draw({self.now}); frame.display.show()")

    def save_gif(self, out: Path, name: str, since: int = 0) -> None:
        frames = [f for f in self.h.display.frames[since:]]
        if not frames:
            return
        out.mkdir(parents=True, exist_ok=True)
        seq_dir = out / name
        seq_dir.mkdir(exist_ok=True)
        rgba = []
        for i, f in enumerate(frames):
            img = self.h.display._circular(f)
            img.save(seq_dir / f"{i:03d}.png")
            rgba.append(img.convert("RGB"))
        rgba[0].save(out / f"{name}.gif", save_all=True,
                     append_images=rgba[1:], duration=TICK_MS, loop=0)
        print(f"wrote {out / (name + '.gif')} ({len(rgba)} frames)")

    def frame_count(self) -> int:
        return len(self.h.display.frames)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "out" / "meridian_motion"

    # 1. Wake ring + aurora idle (the day assembles, then the light flows)
    s = Session()
    s.h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    s.h.execute("_hz.wake(50)")
    s.run(3000)
    s.save_gif(out, "wake_and_aurora")

    # 2. Focus law: condense -> glint -> hold -> recede -> arrival pulse
    s = Session()
    s.h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    s.run(200)
    mark = s.frame_count()
    s.h.execute(f"_r.show_card({OBJECT_CARD})")
    s.run(900)
    s.h.execute("_r.dismiss()")
    s.run(700)
    s.save_gif(out, "focus_physics", since=mark)

    # 3. Save moment: burst + chime over the day
    s = Session()
    s.h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    s.run(200)
    mark = s.frame_count()
    s.h.execute(f"_r.show_card({SAVED_CARD})")
    s.run(1400)
    s.save_gif(out, "save_moment", since=mark)

    # 4. Loading palette chase (light runs the stationary ring)
    s = Session()
    s.h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    s.run(200)
    mark = s.frame_count()
    s.h.execute(f"_r.show_card({LOADING_CARD})")
    s.run(1800)
    s.save_gif(out, "loading_chase", since=mark)

    # 5. Promise shatter: cracking -> shattered while idle
    s = Session()
    s.h.execute("_hz.on_frame({ t='horizon', seq=1, paused=0, "
                "v={ -1350,242, -300,102 } }, 0)")
    s.run(400)
    mark = s.frame_count()
    s.h.execute("_hz.on_frame({ t='horizon', seq=2, paused=0, "
                f"v={{ -1350,252, -300,102 }} }}, {s.now})")
    s.run(900)
    s.save_gif(out, "promise_shatter", since=mark)

    # 6. Prism bloom + breathing rotation
    s = Session()
    s.h.execute('_pr.on_prism({ active = 1, intensity = 70, symmetry = 6 })')
    s.run_prism(3600)
    s.save_gif(out, "prism_bloom")


if __name__ == "__main__":
    main()
