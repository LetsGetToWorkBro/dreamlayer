"""ai_brain/server/intro_live.py — "Hi, I'm Maya", remembered.

Name Capture is the reason most people say they want glasses like these: you
meet someone, they tell you their name, and an hour later you still have it.
`social_lens/introduction.py` has implemented that the whole time — a closed
grammar of self-introductions, a consent flow, an offer card and a kept card —
and `scripts/lens_reachability.py` reported it as **"[no Brain-side
constructor]"**. Nothing on the shipped product ever built an
`IntroductionCapture`, so the ear heard "Hi, I'm Maya" and nothing happened.
Both its cards sat in the HUD checker's undeclared bucket, built and never
pushed.

This is that constructor.

Where the name is written, and why here rather than in the module
-----------------------------------------------------------------
`IntroductionCapture` accepts an `index`/`enricher` to write through, and this
host deliberately passes neither. On the Brain the honest roster is
`people.json` — `Brain.add_person`, what `/dreamlayer/people` serves and the
phone's People screen shows, described in its own docstring as "everyone you've
introduced to the Brain". `social_people` is a MIRROR the glasses hub pushes,
not a store the Brain owns, and `FaceRecall`'s `ContactIndex` is the *consented
biometric* index — a name heard aloud is not a face template and must not be
written there.

So the module keeps what it is good at (the grammar and the consent flow) and
the Brain keeps the write, which is already veil-gated and already visible.

The consent shape, which is the point
-------------------------------------
Hearing a name saves NOTHING. It stages an offer that expires by itself
(`OFFER_TTL_S`, 12s) and asks. Only a deliberate confirm writes anything. That
is the module's own default (`auto_keep=False`) and this host keeps it, behind
its own opt-in on top of the microphone's:

  * `listen_enabled` — the ear is open at all;
  * `intro_capture_enabled` — introductions are listened for;
  * `intro_auto_keep` — a third, separately-stated opt-in for keeping without
    being asked. Off by default, and it is the only setting here that can write
    a name without the wearer confirming it in the moment.

The Veil closes the ear: a name heard while veiled is neither kept nor offered.
Fails closed on an unreadable posture, like every other gate in this file's
neighbourhood.
"""
from __future__ import annotations

from .veil import VeilGate

import logging

log = logging.getLogger("dreamlayer.intro_live")


class IntroHost:
    """Hears self-introductions on the Brain and turns a confirmed one into a
    person you know."""

    def __init__(self, brain):
        self.brain = brain
        self.privacy = VeilGate(brain)
        self._capture = None
        # Honesty bits, on the pattern the ear and the dream lens use: a switch
        # being on proves nothing. `offered` counts names actually recognised by
        # the grammar; `kept` counts names actually written.
        self.offered_count = 0
        self.kept_count = 0

    # -- construction ------------------------------------------------------

    def _cap(self):
        """Build the capture on first use and keep it — the pending offer lives
        on it, so a fresh instance per utterance would drop every offer the
        moment it was made."""
        if self._capture is None:
            try:
                from ...social_lens.introduction import IntroductionCapture
                self._capture = IntroductionCapture(privacy=self.privacy)
            except Exception as exc:                 # noqa: BLE001
                log.warning("[intro] unavailable: %s", type(exc).__name__)
                return None
        # `auto_keep` is read fresh rather than fixed at construction: the wearer
        # can turn it off mid-conversation and that must take effect on the next
        # thing said, not at the next restart.
        self._capture.auto_keep = self._auto_keep()
        return self._capture

    def _enabled(self) -> bool:
        return bool(getattr(self.brain.config, "intro_capture_enabled", False))

    def _auto_keep(self) -> bool:
        return bool(getattr(self.brain.config, "intro_auto_keep", False))

    # -- hearing -----------------------------------------------------------

    def heard(self, text: str) -> dict | None:
        """One utterance from the ear. Returns the card pushed, or None.

        Called from `EarHost.ingest_caption` AFTER the PII scrub, so the words
        the grammar sees are the words the store kept. No frame is passed — the
        ear is audio only, so a heard introduction is a NAME, never a face
        template. That is a deliberate limit, not an oversight: pairing a name
        with whichever face the camera happened to hold at that instant is a
        guess, and a wrong guess here attaches a stranger's name to someone.
        """
        if not self._enabled():
            return None
        cap = self._cap()
        if cap is None:
            return None
        try:
            card = cap.heard(text)
        except Exception as exc:                     # noqa: BLE001 — never break
            log.warning("[intro] parse failed: %s", type(exc).__name__)
            return None
        if not card:
            return None                              # not a self-introduction
        self.offered_count += 1
        if card.get("type") == "IntroKeptCard":
            # auto_keep wrote it already inside the module; mirror it into the
            # Brain's own roster so the People screen agrees with the card.
            self._remember(cap, card)
        self._push(card)
        return card

    # -- deciding ----------------------------------------------------------

    def confirm(self, **extra) -> dict:
        """Keep the name currently offered. The only path that writes without
        `intro_auto_keep`, and it exists to be driven by a deliberate tap."""
        cap = self._cap()
        if cap is None or cap.pending is None:
            return {"ok": False, "reason": "nothing offered"}
        try:
            record = cap.confirm(**extra)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[intro] confirm failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "error"}
        if record is None:
            # The offer expired between the card being drawn and the tap landing.
            # Saying so beats writing a name the wearer may have stopped looking
            # at twelve seconds ago.
            return {"ok": False, "reason": "the offer expired"}
        card = {"type": "IntroKeptCard", "dismiss_ms": 5000, "eyebrow": "KEPT",
                "primary": record.name,
                "detail": "introduced themselves — kept",
                "footer": "on your device · veil silences this",
                "has_face": False, "contact_id": record.contact_id,
                "lines": ["KEPT", record.name, "introduced themselves — kept"]}
        written = self._write(record.name)
        self._push(card)
        return {"ok": True, "name": record.name,
                "contact_id": record.contact_id, "written": written}

    def dismiss(self) -> dict:
        """Let the offer go. Explicit, so "no" is an action the wearer can take
        rather than something they have to wait out."""
        cap = self._cap()
        if cap is None:
            return {"ok": False, "reason": "unavailable"}
        had = cap.pending is not None
        cap.dismiss()
        return {"ok": True, "dismissed": had}

    def status(self) -> dict:
        cap = self._capture
        pending = getattr(cap, "pending", None) if cap is not None else None
        return {
            "enabled": self._enabled(),
            "auto_keep": self._auto_keep(),
            "listening": self._listening(),
            # The NAME of a live offer is already on the wearer's own glass, so
            # echoing it to their own paired phone tells them nothing they are
            # not looking at. Counts otherwise — never who.
            "pending": bool(pending),
            "offered": self.offered_count,
            "kept": self.kept_count,
        }

    def _listening(self) -> bool:
        try:
            st = self.brain.ear_status()
            return bool(st.get("listening") or st.get("remote_listening"))
        except Exception:                            # noqa: BLE001
            return False

    # -- writing -----------------------------------------------------------

    def _remember(self, cap, card) -> None:
        self._write(str(card.get("primary") or ""))

    def _write(self, name: str) -> bool:
        """Into the Brain's own roster. `add_person` refuses under the shield on
        its own, so a name that arrives as the veil closes is dropped there too
        — two gates, and the inner one is the store's."""
        name = (name or "").strip()
        if not name:
            return False
        try:
            self.brain.add_person(name, note="Introduced themselves")
        except Exception as exc:                     # noqa: BLE001
            log.warning("[intro] could not write: %s", type(exc).__name__)
            return False
        self.kept_count += 1
        try:
            # A COUNT and a kind, never the name — the activity log is read back
            # over the wire and a name is the whole of what was captured here.
            self.brain.activity.add("intro", "Kept a name from an introduction")
        except Exception:                            # noqa: BLE001
            pass
        return True

    def _push(self, card: dict) -> int:
        try:
            # veil_ok=False: this card is nothing but a name someone said.
            return int(self.brain.push_event("intro", card, veil_ok=False) or 0)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[intro] push failed: %s", type(exc).__name__)
            return 0
