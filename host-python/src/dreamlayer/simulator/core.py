"""simulator/core.py — the simulated Halo: real stack, virtual glass.

HaloSimulator owns a real Orchestrator on an EmulatorBridge and plays the
part of the missing hardware:

- **voice** — your typed line IS the transcript the mic+ASR seam would
  deliver; it runs through the real "Hey Juno" surface (commands, learns,
  intents, native timers).
- **eyes** — "look at" picks a synthetic camera frame (each face is a
  distinct frame, exactly how the test-suite faces work), so introductions
  enroll a contact and a later glance fires the real recall card.
- **stage** — the raw figment envelopes the orchestrator sends over the
  bridge (`figment_put/swap/text/revoke`) are delivered to the reference
  Figment interpreter — the Python twin of `halo-lua/app/figment_stage.lua`,
  parity-pinned by test_rc2_lua_stage.py — and ticked with real wall-clock
  time, so a "set a timer for 2 minutes" counts down for real.
- **glass** — frame_png() renders what the display would show right now:
  a running figment, else the last HUD card via the golden-image card
  renderer, else the ambient ready ring. The Privacy Veil blacks it out.
"""
from __future__ import annotations

import io
import logging
import math
import threading
import time
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

from ..bridge.emulator_bridge import EmulatorBridge
from ..orchestrator.orchestrator import Orchestrator
from ..reality_compiler.v2.figment import Figment
from ..reality_compiler.v2.interpreter import Stage
from ..hud import renderer as hud_renderer
from ..hud import themes as T

SIZE = 256

# The faces the simulator can "look at": each is a distinct constant frame,
# which the pre-hardware face-embedding stub hashes into a distinct identity —
# the same trick the test suite uses. Who they ARE is up to you: introduce one
# ("this is my colleague Sarah…") and the glasses will know them next glance.
FACES: dict[str, float] = {"face-a": 0.82, "face-b": 0.37, "face-c": 0.61}

# figment display rows → y centers on the 256px glass (5 rows, centered block)
_ROW_Y = (66, 100, 130, 160, 194)
_SIZE_TOKEN = {"hero": "hero", "xl": "xl", "lg": "lg", "md": "md", "sm": "sm"}


def _token_rgb(token: str) -> tuple[int, int, int]:
    """Semantic color token → RGB via the HUD theme table."""
    return T.to_rgb(getattr(T, (token or "text_primary").upper(), T.TEXT_PRIMARY))


class HaloSimulator:
    """One simulated Halo: real orchestrator, virtual display. Thread-safe —
    the HTTP server calls in from multiple request threads."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.bridge = EmulatorBridge()
        self.bridge.connect()
        self.orc = Orchestrator(self.bridge)
        self._figments: dict[str, Figment] = {}
        self.stage: Optional[Stage] = None
        self._stage_id: Optional[str] = None
        self._raw_cursor = 0
        self._last_tick = time.monotonic()
        self.transcript: list[dict] = []      # {who, line}
        self._say("juno", "Halo simulator ready. Talk to me.")

    # ------------------------------------------------------------------
    # inputs — the hardware seams, simulated
    # ------------------------------------------------------------------

    def _frame_for(self, look: Optional[str]):
        v = FACES.get(look or "")
        if v is None:
            return None
        return np.full((32, 32), v, dtype=np.float32)

    def _say(self, who: str, line: str) -> None:
        if line:
            self.transcript.append({"who": who, "line": str(line)[:200]})
            del self.transcript[:-30]

    def voice(self, text: str, look: Optional[str] = None) -> dict:
        """A spoken line (typed = the ASR seam). With a face in view the
        line goes through handle_voice(frame=…) so introductions and scholar
        work; otherwise through the full "Hey Juno" command surface."""
        text = (text or "").strip()
        if not text:
            return {"ok": False, "say": ""}
        with self._lock:
            self._say("you", text)
            frame = self._frame_for(look)
            try:
                if frame is not None:
                    r = self.orc.handle_voice(text, frame=frame) or {}
                    say = r.get("say") or r.get("answer") or ""
                else:
                    r = self.orc.ask_juno(text) or {}
                    say = r.get("text") or r.get("say") or ""
            except Exception:  # never let a demo line kill the sim
                # log the detail for the operator; don't echo internal exception
                # text into the browser transcript (audit 2026-07-14).
                logging.getLogger("dreamlayer.simulator").warning(
                    "voice() failed", exc_info=True)
                r, say = {"intent": "error"}, "(something went wrong — see logs)"
            self._drain()
            self._say("juno", say)
            return {"ok": True, "say": say, "intent": r.get("intent", "")}

    def glance(self, look: Optional[str] = None) -> dict:
        """Look at the person in view — the Social Lens recall moment."""
        with self._lock:
            frame = self._frame_for(look)
            if frame is None:
                self._say("juno", "(nobody in view)")
                return {"ok": False, "say": "Nobody in view."}
            out = None
            try:
                out = self.orc.look_at_person(frame)
            except Exception:
                out = None
            self._drain()
            if out and out.get("person"):
                r = (out.get("rescue") or {})
                bits = [b for b in (r.get("relation"), r.get("note")) if b]
                say = f"That's {out['person']}" + (f" — {', '.join(bits)}." if bits else ".")
            else:
                say = "I don't know them yet — introduce us."
            self._say("juno", say)
            return {"ok": True, "say": say, "recall": out or {}}

    def gesture(self, name: str) -> dict:
        """A temple tap ("single"/"double"/"long") — delivered to the running
        figment first (that's the device contract), else dismisses the card."""
        with self._lock:
            self._tick()
            handled = False
            if self.stage is not None and not self.stage.ended:
                handled = self.stage.inject(name)
                if self.stage.ended:
                    self.stage = None
                    self._stage_id = None
            if not handled and name == "long":
                self.bridge.last_card = None   # dismiss whatever's showing
                handled = True
            return {"ok": True, "handled": handled}

    def veil(self, on: bool) -> dict:
        """The Privacy Veil — the glasses go deaf and blind."""
        with self._lock:
            (self.orc.privacy.pause() if on else self.orc.privacy.resume())
            self._say("juno", "Veil down — I see and keep nothing." if on
                      else "Veil up. I'm with you again.")
            return {"ok": True, "veiled": on}

    # ------------------------------------------------------------------
    # the figment stage — envelopes in, ticks forward
    # ------------------------------------------------------------------

    def _drain(self) -> None:
        """Deliver any raw envelopes the orchestrator just sent over the
        bridge to the (virtual) device stage, exactly as BLE would."""
        frames = self.bridge.raw_frames
        while self._raw_cursor < len(frames):
            env = frames[self._raw_cursor]
            self._raw_cursor += 1
            t = env.get("t")
            if t == "figment_put":
                try:
                    self._figments[env["id"]] = Figment.from_dict(env["figment"])
                except Exception:
                    pass
            elif t == "figment_swap":
                fig = self._figments.get(env.get("id", ""))
                if fig is not None:
                    self.stage = Stage(fig)
                    self._stage_id = fig.id
                    self._last_tick = time.monotonic()
            elif t == "figment_text":
                if self.stage is not None:
                    self.stage.inject("text", env.get("text", ""))
            elif t == "figment_revoke":
                if env.get("id") in (self._stage_id, None):
                    self.stage = None
                    self._stage_id = None

    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        if self.stage is not None and not self.stage.ended and dt > 0:
            self.stage.step(dt)

    # ------------------------------------------------------------------
    # the glass — what the display shows right now
    # ------------------------------------------------------------------

    def frame_image(self) -> Image.Image:
        with self._lock:
            self._tick()
            self._drain()
            if not self.orc.privacy.allow_capture():
                return hud_renderer.render({"type": "PrivacyVeilCard"})
            if self.stage is not None:
                if self.stage.ended:
                    self.stage = None
                    self._stage_id = None
                else:
                    return self._paint_figment()
            card = self.bridge.last_card
            if card:
                try:
                    return hud_renderer.render(card)
                except Exception:
                    pass
            return self._paint_ready()

    def frame_png(self) -> bytes:
        buf = io.BytesIO()
        self.frame_image().save(buf, "PNG")
        return buf.getvalue()

    def _paint_figment(self) -> Image.Image:
        """Draw a DisplayFrame the way the device stage lays it out: rows of
        text on the round glass, with the final-window pulse breathing."""
        assert self.stage is not None   # a figment is on stage when this paints
        f = self.stage.frame()
        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")
        if f.pulse_on and f.pulse_color:
            r, g, b = _token_rgb(f.pulse_color)
            d.ellipse([6, 6, SIZE - 7, SIZE - 7], outline=(r, g, b, 200), width=3)
            d.ellipse([12, 12, SIZE - 13, SIZE - 13], outline=(r, g, b, 70), width=5)
        # painted strokes (the "draw on your lens" layer) — beneath the text so
        # the words stay legible on top of the art
        _STROKE_PX = {"sm": 2, "md": 4, "lg": 7}
        for gl in f.glyphs:
            pts = [(x * SIZE, y * SIZE) for x, y in gl.points]
            if len(pts) >= 2:
                d.line(pts, fill=_token_rgb(gl.color),
                       width=_STROKE_PX.get(gl.width, 4), joint="curve")
        for ln in f.lines:
            if not ln.text:
                continue
            y = _ROW_Y[max(0, min(len(_ROW_Y) - 1, ln.row))]
            font = hud_renderer._font(_SIZE_TOKEN.get(ln.size, "md"))
            d.text((SIZE // 2, y), ln.text, font=font,
                   fill=_token_rgb(ln.color), anchor="mm")
        img.putalpha(hud_renderer._mask())
        return img.convert("RGB")

    def _paint_ready(self) -> Image.Image:
        """Ambient ready: a quiet ring with a breathing dot — the glass at
        rest, phase-locked to the wall clock so the poll animates it."""
        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")
        r, g, b = T.to_rgb(T.ACCENT_MEMORY)
        breathe = 0.45 + 0.3 * (0.5 + 0.5 * math.sin(time.monotonic() * 1.6))
        d.ellipse([104, 104, 152, 152], outline=(r, g, b, int(160 * breathe)), width=2)
        d.ellipse([124, 124, 132, 132], fill=(r, g, b, int(255 * breathe)))
        tr, tg, tb = T.to_rgb(T.TEXT_GHOST)
        d.text((SIZE // 2, 190), "listening for what matters",
               font=hud_renderer._font("xs"), fill=(tr, tg, tb, 255), anchor="mm")
        img.putalpha(hud_renderer._mask())
        return img.convert("RGB")

    # ------------------------------------------------------------------
    # state for the page
    # ------------------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            self._tick()
            fig = None
            if self.stage is not None and not self.stage.ended:
                fig = {"id": self._stage_id, "scene": self.stage.current,
                       "remaining": round(self.stage.remaining(), 1)}
            return {
                "state": self.bridge.state,
                "veiled": not self.orc.privacy.allow_capture(),
                "figment": fig,
                # count-only, never the names: /sim/state is unauthenticated
                # localhost, so a local process must not be able to enumerate
                # everyone the wearer has met (refute 2026-07: the name list
                # leaked here even after the transcript was coarsened).
                "people": len(self.orc.social_people()),
                # who-only: /sim/state is unauthenticated localhost, so any
                # local process can read it. Never hand it the raw spoken
                # content (names / debts / notes) — expose only the speaker
                # label per utterance so the dev tool can still show THAT
                # speech happened, not what was said. (audit 2026-07-15: the
                # raw transcript leaked verbatim over /sim/state.)
                "transcript": [{"who": t["who"]} for t in self.transcript[-14:]],
            }
