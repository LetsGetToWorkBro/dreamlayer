"""face_live.py — recognising the people you introduced, inside the Brain.

The face model is only half of this. `SocialLens` — the thing that would
CONSUME a face embedding — is constructed in exactly one non-test place, and it
is the `Orchestrator` the shipped Brain never builds:

    $ grep -rn "SocialLens(" src/dreamlayer --include=*.py | grep -v /tests/
    orchestrator/orchestrator.py:387:  self.social = SocialLens(privacy=self.privacy)

    $ grep -rn "\\.identify(" src/dreamlayer --include=*.py | grep -v /tests/
    orchestrator/ops_world_lenses.py:525      # an Orchestrator mixin
    lucid_recall/router.py:70                 # LucidRecall, also Orchestrator-only

So plugging a model into `truth_lens/face_embed.py` alone would have produced a
working embedder that nothing in the product ever called — the same shape as
`decisions/0001`, one lens over. This module is the other half: it runs the
consented recall path Brain-side, the way `ear.py`, `glance_live.py` and
`retention_live.py` do, without dragging in an `Orchestrator` (a second
`MemoryDB` and a heavy reasoning graph beside the Brain's own).

WHAT THIS WILL AND WILL NOT DO
------------------------------

It answers exactly one question: **"is this one of the people I introduced?"**
It cannot answer "who is this stranger", and there is no configuration in which
it can. The index it searches contains only contacts the wearer deliberately
enrolled; a face that matches none of them produces "I don't know them yet",
which is the same answer the build without a face model gives.

Four locks, each of which alone is enough to keep it silent:

  1. **No model.** A default install has no `face` extra and no weights, so
     `FaceEmbedder` declines every frame (`truth_lens/face_backends.py`).
  2. **The wearer's switch.** `BrainConfig.face_recognition` is False on a fresh
     install and is never flipped on by this code.
  3. **The Veil.** Incognito / quiet hours means the Brain logs nothing, so a
     frame is dropped before it reaches the model — fail CLOSED, as everywhere
     else: an unreadable posture counts as veiled.
  4. **An empty index.** With nobody enrolled there is nothing to match, and
     `identify` says so rather than reaching for the model at all.

TEMPLATES OF PEOPLE WHO DID NOT CONSENT
---------------------------------------

Answering the question at all means computing a template for the face in front
of the camera, and the wearer does not get to decide in advance whether that
face belongs to a contact or to a stranger on the pavement. Two rules make that
defensible, and both are enforced here rather than promised in a docstring:

  * **A non-matching template is discarded immediately.** It exists as a local
    variable for the duration of one `identify()` call and is never written to
    the index, never returned to the caller, never put in the activity ledger,
    and never logged. `_discard` is where that happens, and it is deliberately
    the only exit from the no-match path.
  * **Only ONE template is ever computed per frame, and it is the subject's.**
    The backend embeds the largest, most central face and nothing else, so a
    bystander in the background never has a biometric template computed at all
    (`face_backends._subject`). Detection sees them; recognition does not.

Enrolment is the only writer. A template reaches disk only through `enrol`,
which is called for a contact the wearer named — never from `identify`.

AMBIENT
-------

"Ambient" (recognise continuously, with no deliberate look) is a SEPARATE
switch from face recognition itself, and it is not in `BrainConfig` at all:
it is `$DL_FACE_AMBIENT`, it is off unless explicitly set, and
`ambient_allowed` refuses it outright in a frozen/release build no matter what
the environment says. That asymmetry is the point — a testing default that
silently becomes the ship default is the bug class this codebase keeps
producing (an uncalled `RetentionSweep`, a gated `probe_ollama` beside an
ungated `_gen`), so the testing switch and the shipped switch are different
names in different places, and the shipped one cannot be turned on by accident.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

log = logging.getLogger("dreamlayer.face")

FACE_INDEX_FILE = "face_index.json"

# The env switch for ambient recognition. Deliberately NOT a BrainConfig field:
# a panel toggle is a thing a release build ships with, and this must not be.
AMBIENT_ENV = "DL_FACE_AMBIENT"

# The in-app consent the WEARER accepts before any of this runs. Versioned, so
# changing the terms re-prompts instead of silently inheriting an old consent —
# an agreement to different words is not this agreement.
#
# Read the second paragraph honestly, because it is the one that matters: this
# consent is the wearer's, and in auto-enrol mode the people being enrolled are
# NOT the ones accepting. No in-app flow can obtain their agreement, because
# they never touch the app. The wearer is accepting a risk on their behalf.
CONSENT_VERSION = "2026-07-29.auto-enrol.v1"
CONSENT_TEXT = (
    "Face recall stores a mathematical template of faces your camera sees, on "
    "this device. Templates are biometric identifiers.\n\n"
    "With auto-enrol ON, this includes people who have not agreed and cannot "
    "agree here — bystanders, passers-by, anyone in frame. Collecting "
    "biometric identifiers without the subject's consent is restricted or "
    "unlawful in some places (for example Illinois' BIPA and GDPR Article 9). "
    "By continuing you accept responsibility for how you use this.\n\n"
    "You can turn it off, erase every stored face, and see how many are held, "
    "at any time."
)

# Unnamed auto-enrolled identities are NOT cold-forever. A named contact is
# someone the wearer chose to keep; an unnamed one is a stranger the camera
# happened to see, and keeping those permanently makes the store grow without
# bound with people the wearer could not identify if asked. They age out on the
# warm window unless naming promotes them.
UNNAMED_TTL_DAYS_DEFAULT = 90.0


def ambient_allowed() -> bool:
    """Whether continuous, un-prompted face recognition may run.

    False unless `$DL_FACE_AMBIENT` is explicitly truthy, and False in a frozen
    (release) build REGARDLESS of the environment — a shipped app cannot be
    talked into ambient recognition by an env var in a plist or a launch agent.
    Testing with friends who consented verbally happens on a source checkout;
    that is the one place this returns True.
    """
    if bool(getattr(sys, "frozen", False)):
        # A release bundle. Say so once, loudly enough to find in a log, and
        # refuse — this branch existing is the promise being kept.
        log.warning("[face] ambient recognition is not available in a release "
                    "build; ignoring %s", AMBIENT_ENV)
        return False
    return os.environ.get(AMBIENT_ENV, "").strip().lower() in (
        "1", "true", "yes", "on")


class _FaceGate:
    """The Veil, read on every frame. Mirrors `ear._EarGate` and
    `world_lens._LookGate`: incognito / quiet hours means no capture, and an
    unreadable posture FAILS CLOSED (veiled), because an unreadable trust signal
    must never resolve to "point the camera at someone's face"."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False


class FaceRecall:
    """The consented face index, and the one question it answers.

    Built once and cached on the Brain (`Brain.face_recall()`), like the world
    lens. Holds the wearer's enrolled contacts and a `ContactIndex` over them,
    reusing the existing 0.65 threshold and 0.08 top-2 margin rather than
    inventing new ones — those constants were written for exactly this model's
    output space (512-d L2-normalised ArcFace).
    """

    def __init__(self, brain):
        self.brain = brain
        self.privacy = _FaceGate(brain)
        self._lock = threading.RLock()
        self._embedder = None
        self._index = None
        self._loaded = False
        # Per-identity bookkeeping the ContactRecord dataclass has no room for:
        # whether it was auto-enrolled, how often it has been seen, when last.
        # Kept beside the index in the same file so the two cannot drift.
        self._meta: dict = {}

    # -- lazy pieces -------------------------------------------------------

    def _get_embedder(self):
        if self._embedder is None:
            from ...truth_lens.face_embed import FaceEmbedder
            self._embedder = FaceEmbedder()
        return self._embedder

    def _get_index(self):
        """The ContactIndex, loaded from disk on first use."""
        if self._index is None:
            from ...social_lens.index import ContactIndex
            self._index = ContactIndex()
        if not self._loaded:
            self._loaded = True
            self._load()
        return self._index

    @property
    def path(self):
        from pathlib import Path
        return Path(self.brain.cfg_dir) / FACE_INDEX_FILE

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        p = self.path
        if not p.exists():
            return
        try:
            rows = json.loads(p.read_text()) or []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[face] index unreadable: %s", type(exc).__name__)
            return
        from ...social_lens.schema import ContactRecord
        for row in rows if isinstance(rows, list) else []:
            try:
                emb = [float(x) for x in (row.get("embedding") or [])]
                if not emb:
                    continue
                cid = str(row["contact_id"])
                self._index.add(ContactRecord(
                    contact_id=cid,
                    name=str(row.get("name") or ""),
                    embedding=emb))
                self._meta[cid] = {"auto": bool(row.get("auto")),
                                   "seen": int(row.get("seen") or 0),
                                   "first_ts": float(row.get("first_ts") or 0.0),
                                   "last_ts": float(row.get("last_ts") or 0.0)}
            except Exception:                        # noqa: BLE001 — skip a bad row
                continue

    def _save(self) -> None:
        rows = [{"contact_id": c.contact_id, "name": c.name,
                 "embedding": [float(x) for x in (c.embedding or [])],
                 **{k: v for k, v in (self._meta.get(c.contact_id) or {}).items()}}
                for c in self._index.all()]
        try:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(rows))
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)   # biometric templates at rest
            except OSError:
                pass
        except Exception as exc:                     # noqa: BLE001
            log.warning("[face] index save failed: %s", type(exc).__name__)

    # -- state -------------------------------------------------------------

    @property
    def model_available(self) -> bool:
        """Whether a real face model could answer on this install."""
        try:
            return bool(self._get_embedder().available)
        except Exception:                            # noqa: BLE001
            return False

    @property
    def consented(self) -> bool:
        """Whether the wearer has accepted the CURRENT in-app consent text.

        Versioned on purpose: accepting the old wording is not acceptance of new
        wording, so changing the terms re-prompts rather than inheriting.
        """
        got = str(getattr(self.brain.config, "face_consent_version", "") or "")
        return got == CONSENT_VERSION

    def accept_consent(self, version: str = "") -> dict:
        """Record the wearer's in-app acceptance. The ONLY way consent is set —
        nothing else in this module writes it, so acceptance is always a
        deliberate act rather than a side effect."""
        version = (version or CONSENT_VERSION).strip()
        if version != CONSENT_VERSION:
            return {"ok": False, "error": "stale consent version",
                    "required": CONSENT_VERSION}
        try:
            self.brain.config.face_consent_version = CONSENT_VERSION
            self.brain.save()
        except Exception as exc:                     # noqa: BLE001
            return {"ok": False, "error": f"could not record consent: {exc}"}
        try:
            self.brain.activity.add(
                "face", f"Accepted face-recall consent ({CONSENT_VERSION})")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "version": CONSENT_VERSION}

    def revoke_consent(self) -> dict:
        """Withdraw consent. Recall stops immediately; stored faces are NOT
        silently deleted, because a wipe is a separate deliberate act — call
        forget_all for that. Reported so the panel can offer both."""
        try:
            self.brain.config.face_consent_version = ""
            self.brain.save()
            self.brain.activity.add("face", "Withdrew face-recall consent")
        except Exception as exc:                     # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "still_stored": self._get_index().size}

    @property
    def auto_enrol(self) -> bool:
        """Enrol every face seen, including people who did not agree."""
        return bool(getattr(self.brain.config, "face_auto_enrol", False))

    @property
    def enabled(self) -> bool:
        """Whether recall may run at all: consent, the wearer's switch, a model."""
        if not self.consented:
            return False
        if not bool(getattr(self.brain.config, "face_recognition", False)):
            return False
        return self.model_available

    def _ask_consent(self, context: str) -> None:
        """Draw the consent prompt — the "Ask first" HUD feature.

        `consent_required_card` has existed the whole time and nothing a shipped
        Brain could reach ever called it, so a face operation refused for want of
        consent returned `{"known": false, "reason": "no-consent"}` as JSON and
        the glass stayed blank. The wearer got silence where the product promises
        a question.

        Two things this deliberately is NOT:

          * not a consent MECHANISM. Acceptance is still `POST
            /dreamlayer/face/consent` against a versioned text, and the refusal
            above already returned before the embedder ran. This draws the state;
            it cannot grant anything, and the card's "Hold to allow" is a pointer
            to that route rather than a second path into it.
          * not veil-piercing. `veil_ok=False`: under the shield nothing is being
            captured, so there is no access to ask about, and the veil branch
            returns before this is ever reached.

        `context` names WHICH operation was refused, because "Allow access?" with
        no object is a prompt the wearer cannot answer.
        """
        try:
            from ...hud import cards
            self.brain.push_event("consent_required",
                                  cards.consent_required_card(context),
                                  veil_ok=False)
        except Exception as exc:                     # noqa: BLE001 — a card must
            log.warning("[face] consent card push failed: %s",   # never cost the
                        type(exc).__name__)                      # refusal itself

    def status(self) -> dict:
        """What the panel shows. Counts and capability only — never a name,
        never a vector."""
        index = self._get_index()
        unnamed = sum(1 for c in index.all() if not c.name)
        return {"enabled": self.enabled,
                "model": self.model_available,
                "ambient": ambient_allowed(),
                "consented": self.consented,
                "consent_version": CONSENT_VERSION,
                "auto_enrol": self.auto_enrol,
                "enrolled": index.size,
                # the count that matters for what the wearer is holding: how
                # many stored faces belong to people who never named themselves
                "unnamed": unnamed}

    # -- the template rule -------------------------------------------------

    @staticmethod
    def _discard(template) -> None:
        """Drop a template that matched nobody.

        The only exit from the no-match path, so there is exactly one place to
        read to know what happens to a bystander's biometrics. It does not
        persist, does not log, and does not return the vector: the local goes
        out of scope and that is the whole lifecycle. Overwriting the buffer
        first is not attempted — Python would make that theatre, not a
        guarantee — so what is promised here is only what is enforced: it is
        never written anywhere.
        """
        del template

    # -- the question ------------------------------------------------------

    def identify(self, frame) -> dict:
        """Is this one of the people the wearer introduced?

        Returns {"known": True, "name", "contact_id", "confidence"} for a
        confident match against an ENROLLED contact, and {"known": False} with a
        reason otherwise. Never raises, never names anyone who was not enrolled,
        and never reports a face it could not place as anything but unknown.
        """
        if not self.privacy.allow_capture():
            return {"known": False, "reason": "veiled"}
        if not self.consented:
            self._ask_consent("recognising a face in view")
            return {"known": False, "reason": "no-consent",
                    "consent_required": CONSENT_VERSION}
        if not bool(getattr(self.brain.config, "face_recognition", False)):
            return {"known": False, "reason": "off"}
        index = self._get_index()
        if index.size == 0 and not self.auto_enrol:
            # Nobody is enrolled and we are not enrolling, so the answer cannot
            # be yes. Return BEFORE the model runs: with no possible match there
            # is no reason to compute a template for whoever is in frame.
            # Auto-enrol deliberately skips this: an empty index is precisely
            # when the first face gets stored.
            return {"known": False, "reason": "nobody-enrolled"}
        au = self._get_embedder().process_frame(frame)
        if au is None:
            return {"known": False, "reason": "no-face"}
        template = list(au.embedding or [])
        if not template:
            return {"known": False, "reason": "no-face"}
        match = index.search(template)
        if match is None:
            if self.auto_enrol:
                # THE CONSEQUENTIAL BRANCH. With auto-enrol on, a face that
                # matches nobody is STORED rather than discarded — including a
                # bystander who never agreed and could not have. This is the
                # wearer's accepted risk (see CONSENT_TEXT), and it is the one
                # place in this file where a template outlives the call for
                # someone who did not ask for that.
                return self._auto_enrol(template)
            # Not enrolling: a stranger's template dies here and the wearer is
            # told the honest thing. Nothing about this face is recorded — not
            # the vector, not a count, not a ledger line.
            self._discard(template)
            return {"known": False, "reason": "no-match"}
        self._discard(template)
        cid = match.contact.contact_id
        seen = self._note_seen(cid)
        return {"known": True, "name": match.contact.name,
                "contact_id": cid,
                "unnamed": not bool(match.contact.name),
                "seen_count": seen,
                "confidence": float(match.confidence)}

    # -- auto-enrolment ----------------------------------------------------

    def _auto_enrol(self, template) -> dict:
        """Store a face nobody named, so it is recognised next time.

        It gets a stable id and NO name. A generated placeholder name would be
        worse than nothing: `identify` would answer `name: "person-8842"`, which
        reads like knowledge and is noise. An unnamed identity is honest — "you
        have seen this person before, three times" is true and useful, and the
        wearer can name them later with `name_identity`.
        """
        from ...social_lens.schema import ContactRecord
        cid = f"auto-{int(time.time() * 1000)}-{len(template) % 97}"
        with self._lock:
            index = self._get_index()
            index.add(ContactRecord(contact_id=cid, name="",
                                    embedding=[float(x) for x in template]))
            self._meta[cid] = {"auto": True, "seen": 1,
                               "first_ts": time.time(), "last_ts": time.time()}
            self._save()
        return {"known": True, "name": "", "contact_id": cid,
                "unnamed": True, "seen_count": 1, "auto_enrolled": True,
                "confidence": 1.0}

    def name_identity(self, contact_id: str, name: str) -> dict:
        """Give an auto-enrolled identity a name.

        This PROMOTES it: a named contact is someone the wearer chose to keep,
        so it stops ageing out on the unnamed window and becomes cold-forever
        like every other contact.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "a name is required"}
        with self._lock:
            index = self._get_index()
            rec = index.get(contact_id)
            if rec is None:
                return {"ok": False, "error": "no such identity"}
            from ...social_lens.schema import ContactRecord
            index.add(ContactRecord(contact_id=contact_id, name=name,
                                    embedding=list(rec.embedding or [])))
            meta = self._meta.setdefault(contact_id, {})
            meta["auto"] = False                     # named: no longer a stranger
            meta["named_ts"] = time.time()
            self._save()
        try:
            self.brain.activity.add("face", f"Named a remembered face: {name}")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "contact_id": contact_id, "name": name}

    def _note_seen(self, contact_id: str) -> int:
        """Count encounters. Only for identities already stored — this never
        creates a record, so it cannot become a back door to enrolment."""
        with self._lock:
            if self._get_index().get(contact_id) is None:
                return 0
            meta = self._meta.setdefault(contact_id, {"auto": False, "seen": 0})
            meta["seen"] = int(meta.get("seen", 0)) + 1
            meta["last_ts"] = time.time()
            self._save()
            return int(meta["seen"])

    def sweep_unnamed(self, ttl_days: float = UNNAMED_TTL_DAYS_DEFAULT) -> int:
        """Drop auto-enrolled identities the wearer never named.

        A named contact is a deliberate keep and stays cold-forever. An unnamed
        one is a stranger the camera happened to see; keeping those permanently
        grows the store without bound with people the wearer could not identify
        if asked. Called by the retention sweep on the warm window.
        """
        if ttl_days <= 0:
            return 0
        cutoff = time.time() - ttl_days * 86400.0
        dropped = 0
        with self._lock:
            index = self._get_index()
            for rec in list(index.all()):
                meta = self._meta.get(rec.contact_id) or {}
                if rec.name or not meta.get("auto"):
                    continue                          # named or hand-enrolled
                if float(meta.get("last_ts", 0.0)) >= cutoff:
                    continue                          # seen recently
                index.remove(rec.contact_id)
                self._meta.pop(rec.contact_id, None)
                dropped += 1
            if dropped:
                self._save()
        return dropped

    # -- enrolment: the only writer ----------------------------------------

    def enrol(self, name: str, frame, contact_id: str = "") -> dict:
        """Remember this face as this person. The only path that stores one.

        Called for someone the wearer just named — an introduction they chose to
        keep — never from `identify`. Refuses while veiled, refuses without a
        name, and refuses when no model can produce a template, so an enrolment
        never silently stores nothing.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "a name is required"}
        if not self.privacy.allow_capture():
            return {"ok": False, "error": "veiled"}
        if not self.consented:
            self._ask_consent("remembering this face")
            return {"ok": False, "error": "consent not accepted",
                    "consent_required": CONSENT_VERSION}
        if not bool(getattr(self.brain.config, "face_recognition", False)):
            return {"ok": False, "error": "face recognition is off"}
        if not self.model_available:
            return {"ok": False, "error": "no face model installed"}
        au = self._get_embedder().process_frame(frame)
        if au is None or not au.embedding:
            return {"ok": False, "error": "no face in view"}
        from ...social_lens.schema import ContactRecord
        cid = (contact_id or "").strip() or f"face-{int(time.time() * 1000)}"
        with self._lock:
            index = self._get_index()
            index.add(ContactRecord(contact_id=cid, name=name,
                                    embedding=[float(x) for x in au.embedding]))
            self._save()
        # The ledger records the ACT, because enrolling a biometric is exactly
        # the kind of thing the wearer must be able to see they did. The name is
        # theirs and already on the People screen; the vector never appears.
        try:
            self.brain.activity.add("face", f"Enrolled a face for {name}")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "contact_id": cid, "name": name,
                "enrolled": index.size}

    # -- forgetting --------------------------------------------------------

    def forget(self, contact_id: str) -> dict:
        with self._lock:
            index = self._get_index()
            had = index.get(contact_id) is not None
            index.remove(contact_id)
            self._save()
        return {"ok": True, "removed": had, "enrolled": index.size}

    def forget_all(self) -> int:
        """Drop every enrolled face. Called by the wearer's erase-everything —
        a face template is the most personal thing here, so it must not be the
        one store an erase forgets to reach."""
        with self._lock:
            index = self._get_index()
            n = index.size
            index.load([])
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError as exc:
                log.warning("[face] index unlink failed: %s", exc)
                self._save()
        return n


def build_face_recall(brain) -> FaceRecall:
    return FaceRecall(brain)
