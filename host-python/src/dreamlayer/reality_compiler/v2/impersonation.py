"""v2/impersonation.py — screen a figment's *text* for system/safety mimicry
(INNOVATION_SESSION 5.4, "the most dangerous thing").

The sandbox proves *physics*: a figment cannot pulse too fast, emit too often,
or swallow the kill switch — all re-verified on your device. What the sandbox
does **not** bound is *meaning*. A shared figment whose text lies —
"BATTERY CRITICAL — REMOVE GLASSES", "System: security update required", a fake
"message from Maya" — is the one live attack left. It steals authority by
dressing third-party content as the system's own voice.

This module screens that voice. It scans every display line a figment can show
for words that imitate device chrome — power, system, security, alerts,
messaging — and returns human-visible flags. It never *blocks* an install (the
proof already bounds what the figment can do to your senses); it makes the
mimicry legible, so the store and the consent card can say: *this is
third-party content, not the system*. Physics is proven; voice is disclosed.

Principle (name it in the docs): **the sandbox proves physics; provenance
proves voice.**
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .figment import Figment

# Words a figment has no honest reason to use — they exist to impersonate the
# device's own power / system / security / messaging chrome. Grouped so a flag
# can say *which* kind of authority the text is borrowing.
LEXICON: dict[str, tuple[str, ...]] = {
    "power": ("battery", "charging", "low power", "shut down", "shutdown",
              "power off", "remove glasses", "overheat", "overheating"),
    "system": ("system", "firmware", "update required", "reboot", "restart",
               "factory reset", "diagnostic", "os"),
    "security": ("security", "verify your", "password", "passcode", "login",
                 "sign in", "authenticate", "unlock", "account locked"),
    "alarm": ("critical", "warning", "alert", "danger", "emergency",
              "failure", "fatal", "error"),
    "message": ("message from", "incoming call", "voicemail", "notification from",
                "texting you", "is calling"),
}


@dataclass
class Flag:
    """One suspicious phrase found in a figment's text."""
    category: str        # power | system | security | alarm | message
    phrase: str          # the lexicon phrase that matched
    scene: str           # scene id it appeared in
    excerpt: str         # the line it appeared in

    def __str__(self) -> str:
        return (f"[{self.category}] {self.phrase!r} in scene {self.scene!r}: "
                f"{self.excerpt!r}")


def _lines(fig: Figment):
    """Every (scene_id, content) a figment can render, incl. battery-warning
    copy if the compat layer put any there."""
    for sc in fig.scenes.values():
        for ln in sc.lines:
            yield sc.id, ln.content


def screen(fig: Figment) -> list[Flag]:
    """Return the impersonation flags for a figment ([] = clean). Case- and
    whitespace-insensitive; a phrase matches on a word boundary so 'system'
    flags but 'ecosystem' does not."""
    flags: list[Flag] = []
    for scene_id, content in _lines(fig):
        low = content.lower()
        for category, phrases in LEXICON.items():
            for phrase in phrases:
                # word-boundary match; phrases may contain spaces
                if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", low):
                    flags.append(Flag(category, phrase, scene_id, content))
    return flags


def is_shared(fig: Figment) -> bool:
    """A figment authored elsewhere and signed to travel — the case where voice
    provenance matters. `meta.origin == "shared"` is set by the author's
    publish step; the deployer already requires an author signature for it."""
    return str((fig.meta or {}).get("origin", "")).lower() == "shared"


def voice_report(fig: Figment) -> dict:
    """The disclosure a store listing / consent card shows about a figment's
    voice: is it third-party, and does its text borrow system authority?"""
    flags = screen(fig)
    shared = is_shared(fig)
    return {
        "shared": shared,
        # a shared figment always earns the provenance mark (the on-device
        # shield_glyph renders it); first-party figments speak in the system's
        # own voice by definition.
        "provenance_glyph": shared,
        "impersonation": [str(f) for f in flags],
        "categories": sorted({f.category for f in flags}),
        # only a *shared* figment mimicking chrome is the dangerous combination;
        # first-party copy naturally says "battery" in a battery lens.
        "flagged": bool(flags) and shared,
    }
