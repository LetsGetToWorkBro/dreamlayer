"""Proof-carrying behaviors (INNOVATION_SESSION 3.2): render a figment's budget
proof as a human *safety card* — what the install CANNOT do, before you consent.
Not "promises not to" — *cannot*, and your own device re-checks the proof. No app
store on Earth shows a machine-verified upper bound on what an install can do to
your senses.
"""
from __future__ import annotations

from .budgets import verify
from .figment import (EMIT_REFILL_PER_S, MAX_LINES, MAX_PULSE_HZ, Figment)
from .impersonation import voice_report


def safety_card(fig: Figment) -> dict:
    """The proof, as consent copy. `ok` is the install verdict; if False the
    figment is disqualified and `violations` says why."""
    rep = verify(fig)
    cannot = [
        f"pulse faster than {MAX_PULSE_HZ:g} Hz — the photic-safety cap "
        f"(this one: ≤ {rep.worst_display_hz:g} Hz)",
        f"talk back faster than {EMIT_REFILL_PER_S:g}/s sustained "
        f"(this one: ≤ {rep.worst_emit_per_sec:g}/s)",
        f"show more than {MAX_LINES} lines at once",
        "reach the network, files, camera, or microphone — it is declarative "
        "data, not code",
        "swallow your kill switch — double-long-press banish lives below every "
        "figment",
    ]
    will = [f"run {rep.scene_count} scene(s), each held at least half a second"]
    # voice: the sandbox bounds physics, not meaning. Disclose whether this is
    # third-party content and whether its text borrows system/safety authority.
    voice = voice_report(fig)
    return {
        "ok": rep.ok,
        "violations": [str(v) for v in rep.violations],
        "cannot": cannot,
        "will": will,
        "voice": voice,
        "proof": {
            "scenes": rep.scene_count,
            "worst_display_hz": rep.worst_display_hz,
            "worst_emit_per_sec": rep.worst_emit_per_sec,
        },
    }


def render_text(card: dict) -> str:
    """The safety card as the line-by-line consent prompt a host would show."""
    if not card["ok"]:
        out = ["⚠ This behavior FAILS the sandbox and cannot be installed:"]
        out += [f"    ✗ {v}" for v in card["violations"]]
        return "\n".join(out)
    out = ["This behavior CANNOT:"]
    out += [f"    • {c}" for c in card["cannot"]]
    out.append("This behavior WILL:")
    out += [f"    • {w}" for w in card["will"]]
    voice = card.get("voice") or {}
    if voice.get("shared"):
        out.append("Voice: third-party content, marked with a provenance glyph "
                   "(the sandbox proves physics; provenance proves voice).")
    if voice.get("flagged"):
        out.append("⚠ Its text imitates system messages "
                   f"({', '.join(voice['categories'])}) — this is NOT the system:")
        out += [f"    ! {f}" for f in voice["impersonation"]]
    out.append("(Your device re-checked this proof — it is not a promise.)")
    return "\n".join(out)
