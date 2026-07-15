"""hud/export_cinema_v2_prototypes.py

Phase 3 driver: run the Meridian Lua prototypes
(halo-lua/display/cinema_v2_prototypes/) through the raster harness and
export PNGs to assets/cinema_v2/prototypes/<element>/.

Usage:
    uv run python -m dreamlayer.hud.export_cinema_v2_prototypes
"""
from __future__ import annotations

from pathlib import Path

from ..bridge.lua_raster import LuaRasterHarness


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "halo-lua" / "main.lua").exists():
            return parent
    raise FileNotFoundError("repo root not found")


def _fresh() -> LuaRasterHarness:
    h = LuaRasterHarness()
    h.sync_dynamic_slots()
    return h


def export_all(out_root: Path | None = None) -> list[Path]:
    root = _repo_root()
    out_root = out_root or (root / "assets" / "cinema_v2" / "prototypes")
    written: list[Path] = []

    def save(h: LuaRasterHarness, rel: str) -> None:
        path = out_root / rel
        h.display.save_frame(path)
        written.append(path)

    # -- horizon states ------------------------------------------------
    h = _fresh()
    proto = 'require("display.cinema_v2_prototypes.proto_horizon")'
    for name in ("typical_day", "quiet_morning", "empty_boot",
                 "stale_link", "paused", "dream_dim"):
        h.execute(f'{proto}.render("{name}")')
        save(h, f"horizon/{name}.png")

    # -- focus law -----------------------------------------------------
    h = _fresh()
    proto = 'require("display.cinema_v2_prototypes.proto_focus")'
    for t in (0, 45, 90, 140, 180, 240):
        h.execute(f"{proto}.render_condense({t}, 0.9)")
        save(h, f"focus/condense_t{t:03d}.png")
    for conf in (0.9, 0.5, 0.2):
        h.execute(f"{proto}.render_hold({conf})")
        save(h, f"focus/hold_conf{int(conf * 100):03d}.png")
    for t in (40, 100, 160, 300):
        h.execute(f"{proto}.render_recede({t})")
        save(h, f"focus/recede_t{t:03d}.png")
    h.execute(f"{proto}.render_reduced(0.9)")
    save(h, "focus/reduce_motion.png")

    # -- promise arc ----------------------------------------------------
    h = _fresh()
    proto = 'require("display.cinema_v2_prototypes.proto_promise_arc")'
    for name in ("ladder", "stacked", "shattered_past"):
        h.execute(f'{proto}.render("{name}")')
        save(h, f"promise_arc/{name}.png")

    # -- testimony thread ------------------------------------------------
    h = _fresh()
    proto = 'require("display.cinema_v2_prototypes.proto_testimony")'
    for name in ("clean_truthful", "elevated_mixed", "stranger_insufficient"):
        h.execute(f'{proto}.render("{name}")')
        save(h, f"testimony/{name}.png")
    for t in (440, 640, 880, 1120):
        h.execute(f'{proto}.render("elevated_mixed", {t})')
        save(h, f"testimony/enter_t{t:04d}.png")

    # -- weather ---------------------------------------------------------
    h = _fresh()
    proto = 'require("display.cinema_v2_prototypes.proto_weather")'
    h.execute(f"{proto}.render_memory_idle()")
    save(h, "weather/memory_idle.png")
    for mood in ("quiet", "storm"):
        h.execute(f'{proto}.render_dream("{mood}")')
        save(h, f"weather/dream_{mood}.png")
    h.execute(f"{proto}.render_anchor_echo()")
    save(h, "weather/anchor_echo.png")

    return written


if __name__ == "__main__":
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default (audit 2026-07-14: configure at every entry).
    from ..logging_setup import configure_logging
    configure_logging()
    for p in export_all():
        print("saved", p)
