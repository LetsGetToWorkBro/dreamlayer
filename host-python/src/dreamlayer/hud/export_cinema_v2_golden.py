"""hud/export_cinema_v2_golden.py

Phase 5 golden exporter: renders every Meridian element in every
reachable state THROUGH THE INTEGRATED DEVICE CODE (display/renderer.lua,
display/horizon.lua, display/focus.lua, display/dream_renderer.lua) via
the raster harness, to assets/cinema_v2/golden/<element>/<state>.png.

This is v2's answer to the v1 black-golden failure
(docs/CINEMA_V1_JUDGMENT.md Wrong #1): the pixels come from the Lua that
ships, driven on a controlled clock — not from a parallel renderer that
can silently diverge.

Usage:
    uv run python -m dreamlayer.hud.export_cinema_v2_golden
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


# A believable day, in wire format (deci-degrees, kind*100+state*10+luma)
DAY_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " 450,102, 380,101, 100,101, -60,302,"     # morning cluster + person pin
    " -300,102, -350,101, -700,102, -860,102,"  # lunch pair + recent
    " -1350,222, -2100,212,"                    # promises: healthy, blooming
    " 580,401 } }"                              # elder tick
)

PROMISE_LADDER_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " -2300,212, -1950,222, -1600,232, -1300,242, -1050,252,"
    " -600,101, -200,102 } }"
)

PROMISE_STACKED_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " -1500,222, -1502,222, -1498,232, -450,101 } }"
)

SHATTERED_PAST_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " -300,252, -700,102, 0,101, -1700,212 } }"
)

TESTIMONY_CARDS = {
    "elevated_mixed": """{
      type = "TruthLensCard", verdict = "ELEVATED", confidence = 0.72,
      origin = { x = 150, y = 96 },
      stages = {
        { confidence = 0.85, direction = "truthful" },
        { confidence = 0.60, direction = "deceptive" },
        { confidence = 0.75, direction = "truthful" },
        { confidence = 0.80, direction = "deceptive" },
        { confidence = 0.55, direction = "truthful" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.70, direction = "deceptive" },
        { confidence = 0.65, direction = "truthful" },
        { confidence = 0.72, direction = "truthful" },
      } }""",
    "clean_truthful": """{
      type = "TruthLensCard", verdict = "CONSISTENT", confidence = 0.88,
      stages = {
        { confidence = 0.90, direction = "truthful" },
        { confidence = 0.85, direction = "truthful" },
        { confidence = 0.80, direction = "truthful" },
        { confidence = 0.88, direction = "truthful" },
        { confidence = 0.75, direction = "truthful" },
        { confidence = 0.70, direction = "truthful" },
        { confidence = 0.92, direction = "truthful" },
        { confidence = 0.86, direction = "truthful" },
        { confidence = 0.88, direction = "truthful" },
      } }""",
    "stranger_insufficient": """{
      type = "TruthLensCard", verdict = "UNKNOWN", confidence = 0.20,
      stages = {
        { confidence = 0.30, direction = "truthful" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.25, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
        { confidence = 0.00, direction = "insufficient" },
      } }""",
}

OBJECT_CARD = """{
  type = "ObjectRecallCard", object = "KEYS", primary = "Keys",
  place = "Kitchen table", detail = "beside blue notebook",
  last_seen = "Last seen 7:42 PM", confidence = 0.9, origin_deg = 0,
}"""


class GoldenSession:
    """Harness + controlled clock + booted integrated modules."""

    def __init__(self) -> None:
        self.h = LuaRasterHarness()
        self.h.execute("__now = 0")
        self.h.execute('_r  = require("display.renderer")')
        self.h.execute('_hz = require("display.horizon")')
        self.h.execute('_dr = require("display.dream_renderer")')
        self.h.execute('_tr = require("display.transitions")')
        self.h.execute("_r.bind(nil, function() return __now end)")
        self.h.execute("_hz._now_ms = function() return __now end")
        self.h.sync_dynamic_slots()

    def now(self, ms: int) -> None:
        self.h.execute(f"__now = {ms}")

    def frame(self, lua_table: str) -> None:
        self.h.execute(f"_hz.on_frame({lua_table}, __now)")

    def tick(self) -> None:
        self.h.execute("_r.tick()")

    def save(self, out_root: Path, rel: str, written: list) -> None:
        path = out_root / rel
        self.h.display.save_frame(path)
        written.append(path)


def export_all(out_root: Path | None = None) -> list[Path]:
    root = _repo_root()
    out_root = out_root or (root / "assets" / "cinema_v2" / "golden")
    written: list[Path] = []

    # ---------------- horizon: the resting states -----------------------
    s = GoldenSession()
    s.now(1000)
    s.frame(DAY_FRAME)
    s.now(2000); s.tick()
    s.save(out_root, "horizon/idle_day.png", written)

    s = GoldenSession()
    s.now(1000)
    s.frame("{ t='horizon', seq=1, paused=0, v={} }")
    s.now(2000); s.tick()
    s.save(out_root, "horizon/idle_empty.png", written)

    s = GoldenSession()
    s.now(1000)
    s.frame("{ t='horizon', seq=1, paused=1, v={} }")
    s.now(2000); s.tick()
    s.save(out_root, "horizon/idle_paused.png", written)

    s = GoldenSession()
    s.now(1000)
    s.frame(DAY_FRAME)
    s.now(45000); s.tick()   # > MER_STALE_MS after the frame
    s.save(out_root, "horizon/idle_stale.png", written)

    # ---------------- promise arc: through the wire codec ----------------
    for name, frame in (("ladder", PROMISE_LADDER_FRAME),
                        ("stacked", PROMISE_STACKED_FRAME),
                        ("shattered_past", SHATTERED_PAST_FRAME)):
        s = GoldenSession()
        s.now(1000)
        s.frame(frame)
        s.now(2000); s.tick()
        s.save(out_root, f"promise_arc/{name}.png", written)

    # ---------------- focus: condense / hold / recede sequences ----------
    s = GoldenSession()
    s.now(1000)
    s.frame(DAY_FRAME)
    s.now(2000)
    s.h.execute(f"_r.show_card({OBJECT_CARD})")
    for t in (40, 90, 140, 180, 240):
        s.now(2000 + t)
        s.tick()
        s.save(out_root, f"focus/condense_t{t:03d}.png", written)
    s.now(3000); s.tick()
    s.save(out_root, "focus/hold_conf090.png", written)
    # low-confidence hold
    s.h.execute(f"_r.show_card({OBJECT_CARD.replace('0.9', '0.2')})")
    s.now(3600); s.tick()
    s.save(out_root, "focus/hold_conf020.png", written)
    # recede
    s.h.execute("_r.dismiss()")
    s.now(3660)
    for t in (40, 100, 150):
        s.now(3660 + t)
        s.tick()
        s.save(out_root, f"focus/recede_t{t:03d}.png", written)
    s.now(3900); s.tick()   # completed: mark pulse frame
    s.save(out_root, "focus/recede_complete_pulse.png", written)

    # reduce_motion variant — via settings, because show_card re-reads the
    # setting on every ENTER (pass-1 golden finding: setting the transitions
    # flag directly was silently overwritten and the golden captured a
    # mislabeled travel frame)
    s = GoldenSession()
    s.now(1000)
    s.frame(DAY_FRAME)
    s.h.execute('require("system.settings").set("reduce_motion", true)')
    s.h.execute(f"_r.show_card({OBJECT_CARD})")
    s.now(1050); s.tick()
    s.save(out_root, "focus/reduce_motion_hold.png", written)

    # ---------------- testimony ------------------------------------------
    # the day stays under the verdict — the paradigm never cuts away
    for name, card in TESTIMONY_CARDS.items():
        s = GoldenSession()
        s.now(1000)
        s.frame(DAY_FRAME)
        s.h.execute(f"_r.show_card({card})")
        s.now(1000 + 400 + 720 + 100)   # settled hold
        s.tick()
        s.save(out_root, f"testimony/{name}.png", written)
    # mid-accumulation sequence
    s = GoldenSession()
    s.now(1000)
    s.frame(DAY_FRAME)
    s.h.execute(f"_r.show_card({TESTIMONY_CARDS['elevated_mixed']})")
    for t in (200, 480, 720, 1000):
        s.now(1000 + t)
        s.tick()
        s.save(out_root, f"testimony/enter_t{t:04d}.png", written)

    # ---------------- weather: dream over the terrain --------------------
    def dream_session(mood: str) -> GoldenSession:
        s = GoldenSession()
        s.now(1000)
        s.frame(DAY_FRAME)
        # Palette weather reproduced through the REAL runtime path. The mic
        # reactor sends { t="palette", colors={ {idx,y,cb,cr}, … } }, which
        # main.lua hands to dream_renderer.apply_palette_shift — an
        # index-based assign_color_ycbcr on the *reserved* sky/energy slots.
        # (The old export shifted via require("display.palette") — the DOT
        # module instance — while these slots live on the SLASH instance
        # require("display/palette"); shift_dynamic("sky") found no
        # reservation and silently no-op'd, so storm == quiet. That was the
        # golden-export footgun, not a device bug: the field is drawn in the
        # slot's live colour, so the index path DOES reach it. Gated by
        # test_dream_weather.)
        s.h.execute("_dr.draw_frame(__now)")   # seed _last_now_ms = 1000
        if mood == "storm":
            # storm-strength absolute YCbCr on slot 1 (sky) and slot 2
            # (energy); apply_palette_shift sets _reactor_until = 1000 + 1200
            # = 2200, so the idle sky-cycle stays off the slots through the
            # now=2000 render and the storm colour survives.
            s.h.execute("""
              _dr.apply_palette_shift({
                { idx = 1, y = 600, cb = 760, cr = 440 },
                { idx = 2, y = 760, cb = 440, cr = 820 },
              })
            """)
        # a plausible rim-tangent field frame (precomputed, as the host sends)
        s.h.execute("""
          local vecs = {}
          for i = 1, 12 do
            local a = (i - 1) * 0.5236 + math.sin(i * 7.13) * 0.45
            local r = 62 + (math.sin(i * 13.7) * 0.5 + 0.5) * 28
            local cx, cy = 128 + r * math.cos(a), 128 + r * math.sin(a)
            local ta = a + 1.5708 + math.sin(i * 3.31) * 0.6
            local ln = 12 + (math.sin(i * 5.77) * 0.5 + 0.5) * 14
            vecs[#vecs+1] = math.floor(cx - ln * math.cos(ta))
            vecs[#vecs+1] = math.floor(cy - ln * math.sin(ta))
            vecs[#vecs+1] = math.floor(cx + ln * math.cos(ta))
            vecs[#vecs+1] = math.floor(cy + ln * math.sin(ta))
          end
          _dr.on_line_field({ v = vecs })
        """)
        return s

    for mood in ("quiet", "storm"):
        s = dream_session(mood)
        s.now(2000)
        s.h.execute("frame.display.clear(0x000000); _dr.draw_frame(__now); frame.display.show()")
        s.save(out_root, f"weather/dream_{mood}.png", written)

    # anchor echo with provenance brighten (settled ghost wake)
    s = dream_session("quiet")
    s.now(2000)
    s.h.execute("""
      frame.display.clear(0x000000)
      _dr.draw_frame(__now)
      __now = __now + 2000
      _dr.render_world_anchor({ primary = "Keys at kitchen counter",
                                detail = "Kitchen \\xE2\\x80\\xA2 12:30",
                                anchor_id = "a1", origin_deg = -30 }, __now - 2000)
      _dr.render_world_anchor({ primary = "Keys at kitchen counter",
                                detail = "Kitchen \\xE2\\x80\\xA2 12:30",
                                anchor_id = "a1", origin_deg = -30 }, __now)
      frame.display.show()
    """)
    s.save(out_root, "weather/anchor_echo.png", written)

    # ---------------- Meridian Solid: recomposed settled holds -----------
    SOLID_CARDS = {
        "saved_memory_hold": '{ type = "SavedMemoryCard", '
                             'primary = "House keys" }',
        "person_context_hold": """{
          type = "PersonContextCard", primary = "Jordan",
          why = "Owes you the contract draft",
          headline = "Sent invoice Wed", detail = "Last seen today",
          confidence = 0.8,
        }""",
        "commitment_recall_hold": """{
          type = "CommitmentRecallCard", person = "Jordan",
          primary = "Send the invoice", due = "Tomorrow before noon",
          confidence = 0.72,
        }""",
    }
    SOLID_CARDS["fact_check_hold"] = """{
      type = "FactCheckCard", verdict = "self_contradiction",
      eyebrow = "THEY SAID DIFFERENT BEFORE",
      primary = "The deal closed at three million.",
      detail = "earlier: we settled at two million",
      footer = "Marcus - elevated - seen before",
    }"""
    SOLID_CARDS["answer_ahead_hold"] = """{
      type = "AnswerAheadCard", primary = "March 14th - two pallets.",
      detail = "When did we last ship to Denver?",
      footer = "Priya - your files",
    }"""
    SOLID_CARDS["juno_reply_hold"] = """{
      type = "JunoReplyCard", kind = "action",
      primary = "Focus on - the world is turned down.",
    }"""
    SOLID_CARDS["hark_hold"] = """{
      type = "HarkCard", importance = "urgent",
      primary = "Marcus is 2 min away - you owe him the lease.",
      detail = "from your last chat",
    }"""
    # World lenses (Scholar / Glance chooser / TasteLens)
    SOLID_CARDS["scholar_answer_hold"] = """{
      type = "ScholarCard", mode = "answer", eyebrow = "ANSWER",
      primary = "Take 400mg twice daily.",
      items = { "Max 1200mg per day", "Not with alcohol" },
    }"""
    SOLID_CARDS["scholar_unavailable_hold"] = """{
      type = "ScholarCard", mode = "answer", unavailable = true,
    }"""
    SOLID_CARDS["glance_choice_hold"] = """{
      type = "GlanceChoiceCard", scene = "a French menu",
      options = { {label = "Translate"}, {label = "Best pick"},
                  {label = "Explain"} },
    }"""
    SOLID_CARDS["taste_hold"] = """{
      type = "TasteCard", eyebrow = "BEST PICK",
      primary = "Oatly Barista", detail = "dairy-free, 4.6 stars",
      items = { "Almond Breeze - 4.1 stars", "x Whole milk - dairy" },
    }"""
    # Missing frames (glass-bound cards that used to render black)
    SOLID_CARDS["listening_hold"] = """{
      type = "ListeningCard", eyebrow = "JUNO", primary = "Listening...",
      detail = "woke by Hey Juno", source = "voice",
    }"""
    SOLID_CARDS["message_hold"] = """{
      type = "MessageCard", headline = "Text", primary = "Priya",
      detail = "Running 10 late, start without me.",
    }"""
    SOLID_CARDS["upcoming_hold"] = """{
      type = "UpcomingCard", headline = "in 5 min", primary = "Standup",
      detail = "Room 4B", minutes = 5,
    }"""
    SOLID_CARDS["here_hold"] = """{
      type = "HereCard", primary = "Your umbrella", detail = "by the door",
    }"""
    SOLID_CARDS["dossier_hold"] = """{
      type = "PersonDossierCard", person = "Marcus",
      headline = "last spoke 2 days ago", detail = "about the lease, the move",
      footer = "you owe him a reply",
    }"""
    SOLID_CARDS["caption_hold"] = """{
      type = "SpokenCaptionCard", eyebrow = "JORDAN",
      primary = "Can you send the invoice today?",
    }"""
    SOLID_CARDS["morning_brief_hold"] = """{
      type = "MorningBriefCard", eyebrow = "YOUR DAY",
      primary = "Three meetings, rain at noon.",
      bullets = { "Standup 9:00", "Dentist 2:30", "Call Mom" },
    }"""
    for name, card in SOLID_CARDS.items():
        s = GoldenSession()
        s.now(1000)
        s.frame(DAY_FRAME)
        s.h.execute(f"_r.show_card({card})")
        # settle far past enter + chime + specular windows: the frame is
        # the card's steady state (deterministic by construction)
        s.now(1000 + 2000)
        s.tick()
        s.save(out_root, f"solid/{name}.png", written)

    return written


if __name__ == "__main__":
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default (audit 2026-07-14: configure at every entry).
    from ..logging_setup import configure_logging
    configure_logging()
    for p in export_all():
        print("saved", p)
