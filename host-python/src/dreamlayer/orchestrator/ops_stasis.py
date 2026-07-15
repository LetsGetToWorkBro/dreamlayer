"""ops_stasis — save states for your mind, on the coordinator (docs/STASIS.md).

A mixin the Orchestrator inherits; every method here runs on the shared
self, so self.stasis (the StasisStack), self.ring, self.bridge and the
privacy gate resolve exactly like every other ops cluster.

The loop this file owns:

  DOUBLE_NOD / "hold that thought" ──▶ freeze_context ──▶ shutter + ribbon
        (zero words, zero decisions: the ring already holds the state)
                          │
              nothing. no badge, no nag.
                          │
  TILT_REVEAL / "where was I" ────────▶ resume_stasis ──▶ the choreography
  same place / same object (ambient) ─▶ stasis_on_place ─▶ ribbon offer only
                          │
      untouched ~7 days ──▶ compost (rides the REM night) ──▶ warm memory

The replay choreography is ordered by how context reinstatement actually
works — context first, content last: the scene, then your overlays and
anchors, then the transcript tail stepping to your final utterance rendered
verbatim, dash included. Then a beat of silence. Stasis never summarizes or
completes the thought — an AI paraphrase would replace your problem state
with its own — so the phone tier alone is the whole product.

Veil contract (all five rules, mechanically checkable in the tests):
freeze while veiled is a silent no-op (allow_capture); resume is a read
(allow_recall — incognito can still resume, a full veil cannot); events
carrying meta.private never enter a snapshot; nothing raw is ever stored
(semantic events and card dicts only); and the ambient offer path runs
behind the same capture gate as on_place itself.
"""
from __future__ import annotations

from typing import Any

from ._ops_host import OpsHost

import json

from ..hud import cards
from .stasis import TAIL_S, FreezeFrame, StasisStack  # noqa: F401  (re-export)

# The ribbon offer for one frame repeats no sooner than this — same shape
# as GhostLayer's GHOST_COOLDOWN_S: an offer, once per return, never a nag.
OFFER_COOLDOWN_S = 120.0
# A verbatim utterance / gaze panel counts as "current" for a freeze if it
# happened within the snapshot tail — context older than the window is the
# previous thought, not this one.
GAZE_STALE_S = 180.0
# NOD_SAVE within this window after a replay pins the frame (the "I'll get
# back to this next month" escape hatch, on the card you're looking at).
REPLAY_PIN_WINDOW_S = 30.0

_REPLAY_STEP_MS = 2200      # each transcript-tail card holds this long
_REPLAY_SCENE_MS = 2600     # the scene card opens the choreography
_REPLAY_FINAL_MS = 9000     # the unfinished sentence holds; you finish it


def _serialize_event(bucket) -> dict:
    """A ring bucket → a plain dict. Semantic fields only — meta rides along
    minus anything heavy, and the raw frame (if an event ever carried one)
    is structurally impossible to include."""
    ev = bucket.event
    return {
        "kind": getattr(ev, "kind", "") or "memory",
        "summary": getattr(ev, "summary", "") or "",
        "confidence": float(getattr(ev, "confidence", 0.5) or 0.5),
        "ts": float(bucket.ts),
        "source": getattr(bucket, "source", "") or "",
    }


def _is_private(ev) -> bool:
    meta = getattr(ev, "meta", None) or {}
    return bool(meta.get("private")) or getattr(ev, "source", "") == "veiled"


def _age_label(created_ts: float, now: float) -> str:
    hours = max(0.0, now - created_ts) / 3600.0
    if hours < 1.0:
        return "moments ago"
    if hours < 8.0:
        return "earlier today"
    if hours < 36.0:
        return "yesterday"
    return f"{int(hours // 24)} days ago"


class StasisOps(OpsHost):

    # ------------------------------------------------------------------
    # Freeze: the shutter closes; your brain gets permission to let go
    # ------------------------------------------------------------------

    def freeze_context(self, now: float | None = None,
                       source: str = "gesture") -> dict | None:
        """Snapshot the problem state and its context binding. Costs zero
        words: everything captured already existed before the gesture.
        Veiled → silent no-op (rule 1): the shutter never closes and
        nothing is stored."""
        if not self.privacy.allow_capture():
            return None
        now = self._clock() if now is None else now

        window = [_serialize_event(b) for b in self.ring.since(now - TAIL_S)
                  if not _is_private(b.event)]

        utter, utter_ts = getattr(self, "_stasis_last_utterance", ("", 0.0))
        final_utterance = utter if now - utter_ts <= TAIL_S else ""

        gaze_card, gaze_key = None, ""
        gaze = getattr(self, "_stasis_gaze", None)
        if gaze is not None and now - gaze[2] <= GAZE_STALE_S:
            gaze_key, gaze_card = gaze[0], gaze[1]

        ctx = getattr(self.dream, "_ctx", None)
        anchors = list(getattr(ctx, "world_anchors", None) or [])
        place = getattr(ctx, "place_signature", None) or \
            getattr(self, "_stasis_last_place", "") or ""
        pose = getattr(ctx, "imu_pose", None)

        frame = FreezeFrame(
            id=0, created_ts=now, place_signature=place,
            imu_pose=dict(pose) if isinstance(pose, dict) else None,
            ring_window=window, final_utterance=final_utterance,
            gaze_context=gaze_card, gaze_key=gaze_key,
            overlays=list(getattr(self, "_stasis_overlays", []) or []),
            anchors=anchors, meta={"source": source},
        )
        frame = self._stasis_persist(frame)
        for evicted in self.stasis.push(frame):
            self._stasis_compost_one(evicted, now, reason="depth")

        # the affordance: a 400ms shutter dim and a ribbon settling into the
        # periphery — an acknowledgment, not a card (nothing to read)
        self.bridge.send_raw({"t": "stasis", "mode": "freeze"})
        self.publish_plugin_event("stasis_freeze", {
            "frame_id": frame.id, "place": place, "gaze": gaze_key,
            "events": len(window), "has_utterance": bool(final_utterance)})
        return {"ok": True, "frame_id": frame.id, "events": len(window),
                "final_utterance": final_utterance, "depth": len(self.stasis)}

    # ------------------------------------------------------------------
    # Resume: context first, content last, then a beat of silence
    # ------------------------------------------------------------------

    def resume_stasis(self, frame_id: int | None = None,
                      now: float | None = None) -> dict | None:
        """Replay a freeze-frame as an 8–12s choreography of cards. A read,
        so it runs behind allow_recall (rule 2): incognito can resume; the
        full veil cannot. Never summarizes — the final card is the wearer's
        own last sentence, verbatim, unfinished. The dash is the handoff."""
        if not self.privacy.allow_recall():
            return None
        now = self._clock() if now is None else now
        frame = (self.stasis.get(frame_id) if frame_id is not None
                 else self.stasis.top())
        if frame is None:
            self.bridge.send_card(cards.juno_reply("Nothing on hold.", "answer"),
                                  event="stasis_empty")
            return {"ok": False, "reason": "no frames"}

        played = []
        for card in self._stasis_choreography(frame, now):
            self.bridge.send_card(card, event="stasis_replay")
            played.append(card["type"])

        healed = frame.resumed(now)
        self.stasis.replace_frame(healed)
        self._stasis_sync_row(healed)
        self._stasis_last_replay = (healed.id, now)
        self.bridge.send_raw({"t": "stasis", "mode": "clear"})
        self.publish_plugin_event("stasis_resume", {
            "frame_id": healed.id, "resume_count": healed.resume_count,
            "freshness": frame.freshness(now)})
        return {"ok": True, "frame_id": healed.id, "cards": played,
                "freshness": frame.freshness(now)}

    def _stasis_choreography(self, frame: FreezeFrame, now: float) -> list[dict]:
        """The replay, ordered by how reconsolidation works: (1) the scene,
        (2) your overlays and anchors restore, (3) the transcript tail steps
        to (4) the final utterance — larger, verbatim, including the sentence
        you never finished. Cooler frames get one extra orienting line
        (context reinstatement needs more scaffolding as traces cool)."""
        out: list[dict] = []
        freshness = frame.freshness(now)

        if frame.gaze_context:
            scene = {**frame.gaze_context, "dismiss_ms": _REPLAY_SCENE_MS}
            out.append(scene)
        if freshness != "fresh" or not frame.gaze_context:
            where = frame.place_signature or "where you left it"
            out.append(self._stasis_node_card(
                eyebrow="STASIS", primary=_age_label(frame.created_ts, now),
                footer=where, index=0, total=1,
                dismiss_ms=_REPLAY_SCENE_MS))

        for overlay in frame.overlays:
            out.append({**overlay, "dismiss_ms": _REPLAY_STEP_MS})
        for a in frame.anchors:
            out.append({**cards.world_anchor_card(
                summary=a.get("summary", ""), place=a.get("place", ""),
                ts_label=a.get("ts_label", ""),
                confidence=a.get("confidence")),
                "dismiss_ms": _REPLAY_STEP_MS})

        tail = [e for e in frame.ring_window if e.get("summary")][-3:]
        for i, e in enumerate(tail):
            out.append(self._stasis_node_card(
                eyebrow=e["kind"].upper(), primary=e["summary"],
                footer="", index=i, total=max(len(tail), 1),
                dismiss_ms=_REPLAY_STEP_MS))

        if frame.final_utterance:
            out.append(self._stasis_node_card(
                eyebrow="YOU WERE SAYING", primary=frame.final_utterance,
                footer="…", index=max(len(tail) - 1, 0),
                total=max(len(tail), 1), dismiss_ms=_REPLAY_FINAL_MS,
                final=True))
        return out

    @staticmethod
    def _stasis_node_card(eyebrow: str, primary: str, footer: str,
                          index: int, total: int, dismiss_ms: int,
                          final: bool = False) -> dict:
        """Replay steps reuse the TimeScrubNodeCard renderer (time_scrub.py
        shape) — Stasis resume is a scrub pointed at a frozen window. The
        dismiss_ms override is what turns the sticky scrub node into a
        self-advancing choreography step."""
        return {
            "type": "TimeScrubNodeCard",
            "dismiss_ms": dismiss_ms,
            "index": index,
            "total": total,
            "kind": "stasis",
            "summary": primary,
            "ts_label": eyebrow,
            "confidence": 1.0 if final else 0.8,
            "primary": primary,
            "footer": footer,
            "source": "stasis",
            "meta": {"stasis_final": final},
            "lines": [eyebrow, primary, footer],
            "layout": {
                "progress": {"value": index / max(total - 1, 1)},
                "eyebrow": {"x": 128, "y": 56, "size": "sm",
                            "color": 0x2CC79A, "tracking": 2},
                "primary": {"x": 128, "y": 100, "size": "hero",
                            "color": 0xECF0F1},
                "footer": {"x": 128, "y": 148, "size": "sm",
                           "color": 0x58686F},
            },
        }

    # ------------------------------------------------------------------
    # The ambient offer: it offers; it never plays unbidden
    # ------------------------------------------------------------------

    def stasis_on_place(self, signature: str,
                        now: float | None = None) -> dict | None:
        """The wearer returned to a frozen context: the ribbon glyph
        reappears in the periphery, glowing softly — a raw frame, not a
        card, so it competes with nothing. Debounced per frame; one offer
        per return (rule 5: callers are already capture-gated, and the
        read side is gated here)."""
        now = self._clock() if now is None else now
        self._stasis_last_place = signature or ""
        if not self.privacy.allow_recall():
            return None
        frame = self.stasis.match_context(place_signature=signature)
        return self._stasis_offer(frame, now)

    def stasis_note_gaze(self, panel, now: float | None = None) -> dict | None:
        """Called from the Juno look flow: remember what's open (the freeze
        snapshot needs it) and, if the gaze landed on a frozen frame's
        object, make the same quiet offer."""
        now = self._clock() if now is None else now
        try:
            key = panel.sighting.key()
            self._stasis_gaze = (key, panel.to_hud_card(), now)
        except Exception:
            return None
        if not self.privacy.allow_recall():
            return None
        return self._stasis_offer(self.stasis.match_context(gaze_key=key), now)

    def _stasis_offer(self, frame, now: float) -> dict | None:
        if frame is None:
            return None
        offered = getattr(self, "_stasis_offered", None)
        if offered is None:
            offered = self._stasis_offered = {}
        last = offered.get(frame.id, 0.0)
        if now - last < OFFER_COOLDOWN_S:
            return None
        offered[frame.id] = now
        self.bridge.send_raw({"t": "stasis", "mode": "offer"})
        return {"offered": frame.id}

    # ------------------------------------------------------------------
    # Decay: things quietly return to the soil
    # ------------------------------------------------------------------

    def compost_stasis(self, now: float | None = None) -> dict:
        """Dissolve frames past their half-life: the bookmark goes, the
        final utterance stays as an ordinary warm memory (findable by
        recall search, no longer an active bookmark). Runs during the REM
        night — unresumed thoughts fold into memory while you sleep."""
        now = self._clock() if now is None else now
        composted = [self._stasis_compost_one(f, now, reason="decay")
                     for f in self.stasis.compost_due(now)]
        return {"composted": composted, "live": len(self.stasis)}

    def pin_stasis(self, frame_id: int | None = None) -> dict | None:
        """The escape hatch: NOD_SAVE on a replay card pins the frame so it
        never composts (meta.pinned — the same immortality flag retention
        honors everywhere else)."""
        frame = (self.stasis.get(frame_id) if frame_id is not None
                 else self.stasis.top())
        if frame is None:
            return None
        pinned = frame.pinned()
        self.stasis.replace_frame(pinned)
        self._stasis_sync_row(pinned, row_pinned=True)
        self.bridge.send_card(cards.saved_memory("Held."), event="stasis_pinned")
        return {"pinned": pinned.id}

    def stasis_status(self, now: float | None = None) -> dict:
        now = self._clock() if now is None else now
        return {
            "live": len(self.stasis),
            "frames": [{"id": f.id, "freshness": f.freshness(now),
                        "decay": round(f.decay(now), 3),
                        "pinned": bool(f.meta.get("pinned")),
                        "resumes": f.resume_count}
                       for f in self.stasis.frames()],
        }

    # ------------------------------------------------------------------
    # Persistence (kind="stasis" memories rows; nothing raw, ever)
    # ------------------------------------------------------------------

    def _stasis_summary(self, frame: FreezeFrame) -> str:
        if frame.final_utterance:
            return frame.final_utterance
        if frame.gaze_key:
            return f"held thought · {frame.gaze_key}"
        return "held thought"

    def _stasis_persist(self, frame: FreezeFrame) -> FreezeFrame:
        """One text row, embedded and indexed like every other ingest path,
        with the whole freeze-frame riding meta.stasis. Degrades honestly:
        if persist fails the frame still lives in the stack for the session
        (id stays 0; compost then simply has no row to retire)."""
        summary = self._stasis_summary(frame)
        try:
            emb = self.embedder.embed(summary)
            mid = self.db.add_memory(kind="stasis", summary=summary,
                                     embedding=emb, confidence=0.8,
                                     meta={"stasis": frame.to_payload()})
            self.retriever.index_memory(mid, emb)
        except Exception as exc:
            self.health.record_failure("stasis", exc)
            return frame
        from dataclasses import replace
        return replace(frame, id=mid)

    def _stasis_sync_row(self, frame: FreezeFrame,
                         row_pinned: bool = False) -> None:
        if not frame.id:
            return
        meta: dict[str, Any] = {"stasis": frame.to_payload()}
        if row_pinned or frame.meta.get("pinned"):
            meta["pinned"] = True
        try:
            self.db.update_meta(frame.id, meta)
        except Exception as exc:
            self.health.record_failure("stasis", exc)

    def _stasis_compost_one(self, frame: FreezeFrame, now: float,
                            reason: str) -> dict:
        """Retire the bookmark row (ANN-safe) and write what mattered — the
        final utterance — back as an ordinary memory. Nothing is lost that
        was worth keeping; nothing keeps demanding attention."""
        if frame.id:
            try:
                self.retriever.purge_memory(frame.id)
            except Exception as exc:
                self.health.record_failure("stasis", exc)
        summary = self._stasis_summary(frame)
        mid = 0
        try:
            emb = self.embedder.embed(summary)
            mid = self.db.add_memory(
                kind="memory", summary=summary, embedding=emb,
                confidence=0.6,
                meta={"stasis_compost": True, "reason": reason,
                      "place_signature": frame.place_signature,
                      "frozen_ts": frame.created_ts})
            self.retriever.index_memory(mid, emb)
        except Exception as exc:
            self.health.record_failure("stasis", exc)
        return {"frame_id": frame.id, "memory_id": mid, "reason": reason}

    def _stasis_load(self) -> None:
        """Boot restore: live frames survive an orchestrator restart via
        their kind="stasis" rows."""
        frames = []
        for row in self.db.memories(kind="stasis"):
            try:
                payload = json.loads(row.get("meta") or "{}").get("stasis")
                if payload:
                    frames.append(FreezeFrame.from_payload(row["id"], payload))
            except (ValueError, TypeError, KeyError):
                continue
        self.stasis.load(frames)
