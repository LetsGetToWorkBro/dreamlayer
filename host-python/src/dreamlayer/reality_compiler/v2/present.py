"""v2/present.py — render the Rehearsal state into phone-facing shapes.

The phone's Rehearsal screen mirrors the Reality Compiler v2 state over the
local bridge. The heavy lifting (inference, budgets, signing, deploy) stays in
host-python; this module is the thin, tested translation layer that turns the
authoritative objects — Beats, Figments, VaultEntries — into the plain dicts
the UI draws, so the phone never re-implements the grammar or the machine.

Nothing here computes semantics; it only *reads* already-verified objects:

  score_from_beats(beats)      -> [{kind, text, reading, foldedSec}]
  figment_brief(fig)           -> {trigger, length}
  repertoire_entry(entry, id)  -> {id, name, trigger, length, signed, active}
"""
from __future__ import annotations

from typing import Optional

# how the machine's trigger events read to a person
_TRIGGER_LABEL = {
    "single": "tap",
    "double": "double-tap",
    "long": "hold",
}


def score_from_beats(beats) -> list:
    """The performed beats as a timeline the phone draws: each beat's kind, its
    raw utterance (for `say`), the choreographer's plain-words reading, and a
    folded duration when the beat spoke one (so the UI can show ⋯3:00⋯)."""
    out = []
    for b in beats or []:
        folded = None
        if b.parsed and b.parsed[0] == "duration":
            folded = b.parsed[2]
        elif b.kind == "dwell" and b.seconds:
            folded = b.seconds
        out.append({
            "kind": b.kind,
            "text": b.text,
            "reading": b.reading(),
            "foldedSec": folded,
        })
    return out


def playback_rows(frames, limit: int = 24) -> list:
    """The time-folded run-through as rows the phone previews before keeping:
    each sampled frame's sim-time, the lines on the HUD, and whether it was a
    folded stretch or a pulse frame. This is the "watch what you authored"
    surface — the same frames the reference stage produced."""
    rows = []
    for pf in (frames or [])[:limit]:
        body = " / ".join(ln.text for ln in sorted(pf.frame.lines,
                                                    key=lambda l: l.row))
        rows.append({
            "t": round(pf.t_sim, 1),
            "label": pf.label,
            "text": body,
            "folded": bool(pf.folded),
            "pulse": bool(pf.frame.pulse_on),
        })
    return rows


def _main_duration(fig) -> Optional[float]:
    """The longest timed scene — the behaviour's headline length."""
    best = None
    for scene in fig.scenes.values():
        d = scene.duration_sec
        if d is not None and (best is None or d > best):
            best = d
    return best


def _has_pulse(fig) -> bool:
    return any(getattr(s, "pulse", None) is not None for s in fig.scenes.values())


def _fmt_len(secs: Optional[float]) -> str:
    if not secs:
        return "instant"
    secs = int(round(secs))
    return f"{secs // 60}:{secs % 60:02d}" if secs >= 60 else f"{secs}s"


def figment_brief(fig) -> dict:
    """A one-line description of a figment for a Repertoire card: how it's
    triggered and how long it runs. Read from the machine itself — the initial
    (armed) scene owns the trigger; the longest scene owns the length."""
    initial = fig.scenes.get(fig.initial)
    trigger = "auto"
    if initial is not None and initial.on:
        # the armed scene waits on exactly one trigger event
        for ev in ("double", "single", "long"):
            if ev in initial.on:
                trigger = _TRIGGER_LABEL[ev]
                break
        else:
            first = next(iter(initial.on))
            trigger = _TRIGGER_LABEL.get(first, first)
    length = _fmt_len(_main_duration(fig))
    if _has_pulse(fig):
        length += " + pulse"
    return {"trigger": trigger, "length": length}


def repertoire_entry(entry, active_id: Optional[str] = None) -> dict:
    """A kept figment as a Repertoire card. `active_id` is the figment the
    Brain last deployed (on stage now); everything else is armed-and-ready."""
    fig = entry.figment
    brief = figment_brief(fig)
    return {
        "id": fig.id,
        "name": fig.name,
        "trigger": brief["trigger"],
        "length": brief["length"],
        "signed": bool(entry.sig) and not entry.revoked,
        "active": (fig.id == active_id) and not entry.revoked,
    }
