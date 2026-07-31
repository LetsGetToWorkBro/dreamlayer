"""ai_brain/server/voice_live.py — who is speaking, so a memory has an author.

THE GAP THIS FILLS. `lens_hosts` has answered "what did Marcus say last time"
and "what did Marcus promise" since `they_said`/`their_word` were written, both
matching on `meta["said_by"]`. Nothing ever set it. `ear.py` said so in prose —
*"nothing in this product ever populates `speaker`"* — and named the reason:
knowing who spoke means voiceprinting whoever is in earshot, which `voice_guard`
exists to forbid without consent. So the memory-based Truth Lens had no live
input at all: it worked only for utterances the wearer typed in themselves.

This is the consented producer. It mirrors `face_live.py` deliberately and almost
line for line, because a voiceprint is the same KIND of thing as a face template —
a biometric identifier — and the wearer deserves the same switches, the same
versioned consent, the same "erase everything" button, and the same honesty about
who is being enrolled without being asked.

TEMPLATES OF PEOPLE WHO DID NOT CONSENT. With auto-enrol on, every voice the
microphone hears is stored, including people who never agreed and cannot agree
here — they never touch the app. The wearer accepts that risk on their behalf;
`CONSENT_TEXT` says so in those words rather than burying it.

THE ONE THING THIS FILE REFUSES. `ECAPASpeaker.embed` falls back to a HASH of the
audio's string form when speechbrain is absent. That fallback is a plumbing
stand-in, not a voice: the same person yields a different vector every utterance,
and two strangers can collide. Identifying with it would attach real names to the
wrong people and write those names into memory as fact. So `model_available` is
gated on a model that actually loaded, and with no model this whole layer declines
— the ear keeps working exactly as it does today, unattributed. That is the
`tagger_live` lesson (a present wheel with no model reported live for a seam that
could only return nothing) applied where being wrong is defamatory rather than
merely empty.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid

log = logging.getLogger("dreamlayer.voice")

VOICE_INDEX_FILE = "voice_index.json"

#: The in-app consent the WEARER accepts. Versioned, so changing the terms
#: re-prompts rather than silently inheriting an old agreement.
CONSENT_VERSION = "2026-07-30.voice-auto-enrol.v1"
CONSENT_TEXT = (
    "Voice recall stores a mathematical template of voices your microphone "
    "hears, on this device. Voiceprints are biometric identifiers.\n\n"
    "With auto-enrol ON, this includes people who have not agreed and cannot "
    "agree here — anyone within earshot. Collecting biometric identifiers "
    "without the subject's consent is restricted or unlawful in some places "
    "(for example Illinois' BIPA and GDPR Article 9). Recording or attributing "
    "speech may also fall under two-party consent laws where you are. By "
    "continuing you accept responsibility for how you use this.\n\n"
    "What it changes: things people say near you get stored with their name "
    "attached, so you can ask what someone told you before. You can turn it "
    "off, erase every stored voice, and see how many are held, at any time."
)

#: Cosine similarity above which two utterances are the same speaker.
#:
#: NOT the face index's 0.65/0.08 — those were chosen for 512-d L2-normalised
#: ArcFace output and do not transfer to a different model's space. ECAPA-TDNN on
#: VoxCeleb is normally operated near 0.25–0.35 cosine for verification; 0.40 is
#: deliberately above that band, because the cost of a false match here is not a
#: missed greeting but a sentence attributed to the wrong person and stored as
#: what they said. A missed match costs an unattributed memory, which is exactly
#: what the product does today.
MATCH_THRESHOLD = 0.40

#: How far the best match must beat the runner-up. A room of similar voices
#: should produce "I am not sure" rather than a coin flip between two people.
MATCH_MARGIN = 0.06

#: A speech segment shorter than this is not enough voice to identify anyone.
#: Short utterances ("yeah", "mm") produce unstable embeddings, and an unstable
#: embedding auto-enrolled becomes a phantom speaker that never matches again.
MIN_SEGMENT_S = 1.0

#: Unnamed auto-enrolled voices age out; named ones are a deliberate keep and
#: stay. Mirrors the face store's window for the same reason — a store of people
#: the wearer could not identify if asked should not grow without bound.
UNNAMED_TTL_DAYS_DEFAULT = 90.0


class _VoiceGate:
    """The Veil, read before any voiceprint is computed. Mirrors `_EarGate` /
    `_FaceGate`: incognito or quiet hours means no capture, and an unreadable
    posture FAILS CLOSED, because an unreadable trust signal must never resolve
    to "take a biometric of whoever is talking"."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False


def _cosine(a, b) -> float:
    """Cosine similarity, computed here rather than via
    `ECAPASpeaker.similarity`.

    That helper is a bare dot product, which is only cosine for unit vectors —
    and `embed()` returns the model's raw output, which is NOT normalised. Using
    it would make the threshold above meaningless (it would scale with utterance
    loudness), so the normalisation happens where the comparison does.
    """
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class VoiceRecall:
    """The consented voice index, and the one question it answers.

    Built once and cached on the Brain (`Brain.voice_recall()`), like the world
    lens and the face index.
    """

    def __init__(self, brain):
        self.brain = brain
        self.privacy = _VoiceGate(brain)
        self._lock = threading.RLock()
        self._embedder = None
        self._embedder_built = False
        # contact_id -> {"name", "vec", "auto", "seen", "first_ts", "last_ts"}
        self._people: dict = {}
        self._loaded = False

    # -- storage -----------------------------------------------------------

    @property
    def path(self):
        return self.brain.cfg_dir / VOICE_INDEX_FILE

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            p = self.path
            rows = json.loads(p.read_text()) if p.exists() else []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[voice] index unreadable: %s", type(exc).__name__)
            rows = []
        for r in rows if isinstance(rows, list) else []:
            try:
                cid = str(r["contact_id"])
                self._people[cid] = {
                    "name": str(r.get("name", "") or ""),
                    "vec": [float(x) for x in (r.get("vec") or [])],
                    "auto": bool(r.get("auto", True)),
                    "seen": int(r.get("seen", 0) or 0),
                    "first_ts": float(r.get("first_ts", 0) or 0),
                    "last_ts": float(r.get("last_ts", 0) or 0),
                }
            except Exception:                        # noqa: BLE001 — one bad row
                continue

    def _save(self) -> None:
        rows = [{"contact_id": cid, **{k: v for k, v in rec.items()}}
                for cid, rec in self._people.items()]
        try:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(rows))
            tmp.replace(self.path)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[voice] index save failed: %s", type(exc).__name__)

    # -- the model ---------------------------------------------------------

    def _get_embedder(self):
        if not self._embedder_built:
            self._embedder_built = True
            try:
                from ...orchestrator.speaker_ecapa import ECAPASpeaker
                spk = ECAPASpeaker()
                # `available` is the WHEEL; `_model` is a model that actually
                # loaded. Only the second one can identify a person — see the
                # module docstring on why the hash fallback must never be used
                # to attach a name to a voice.
                self._embedder = spk if getattr(spk, "_model", None) is not None else None
            except Exception as exc:                 # noqa: BLE001
                log.info("[voice] no speaker model: %s", type(exc).__name__)
                self._embedder = None
        return self._embedder

    @property
    def model_available(self) -> bool:
        return self._get_embedder() is not None

    # -- consent -----------------------------------------------------------

    @property
    def consented(self) -> bool:
        got = str(getattr(self.brain.config, "voice_consent_version", "") or "")
        return got == CONSENT_VERSION

    def accept_consent(self, version: str = "") -> dict:
        version = (version or CONSENT_VERSION).strip()
        if version != CONSENT_VERSION:
            return {"ok": False, "error": "consent text has changed",
                    "required": CONSENT_VERSION}
        self.brain.config.voice_consent_version = CONSENT_VERSION
        self.brain.save()
        try:
            self.brain.activity.add(
                "voice", f"Accepted voice-recall consent ({CONSENT_VERSION})")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "version": CONSENT_VERSION}

    def revoke_consent(self) -> dict:
        """Withdrawing consent ERASES the templates, it does not merely stop
        collecting. A stored biometric taken under an agreement the wearer has
        withdrawn is exactly the thing they withdrew."""
        self.brain.config.voice_consent_version = ""
        self.brain.config.voice_recognition = False
        self.brain.config.voice_auto_enrol = False
        self.brain.save()
        dropped = self.forget_all()
        try:
            self.brain.activity.add(
                "voice", f"Revoked voice consent and erased {dropped} voiceprint(s)")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "erased": dropped}

    @property
    def auto_enrol(self) -> bool:
        return bool(getattr(self.brain.config, "voice_auto_enrol", False)
                    and self.consented)

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.brain.config, "voice_recognition", False)
                    and self.consented)

    # -- the question ------------------------------------------------------

    def identify(self, audio, duration_s: float = 0.0) -> dict:
        """Whose voice is this? A name, or an honest "I don't know".

        Never raises — it is called from the capture loop — and never names
        anyone who was not enrolled.
        """
        if not self.privacy.allow_capture():
            return {"known": False, "reason": "veiled"}
        if not self.consented:
            return {"known": False, "reason": "no-consent",
                    "consent_required": CONSENT_VERSION}
        if not self.enabled:
            return {"known": False, "reason": "off"}
        if not self.model_available:
            # No model: decline rather than fall back to the hash vector. The
            # ear keeps working, unattributed, exactly as it does today.
            return {"known": False, "reason": "no-voice-model"}
        if duration_s and duration_s < MIN_SEGMENT_S:
            return {"known": False, "reason": "too-short"}
        self._load()
        if not self._people and not self.auto_enrol:
            # Nobody enrolled and not enrolling: the answer cannot be yes, so
            # return BEFORE computing a biometric of whoever is talking.
            return {"known": False, "reason": "nobody-enrolled"}
        try:
            vec = [float(x) for x in (self._get_embedder().embed(audio) or [])]
        except Exception as exc:                     # noqa: BLE001
            log.warning("[voice] embed failed: %s", type(exc).__name__)
            return {"known": False, "reason": "embed-failed"}
        if not vec:
            return {"known": False, "reason": "no-voice"}
        cid, score, runner_up = self._best(vec)
        if cid is None or score < MATCH_THRESHOLD or (score - runner_up) < MATCH_MARGIN:
            if self.auto_enrol:
                # THE CONSEQUENTIAL BRANCH. A voice matching nobody is STORED,
                # including a bystander's. The wearer's accepted risk; see
                # CONSENT_TEXT.
                return self._auto_enrol(vec)
            return {"known": False, "reason": "no-match"}
        seen = self._note_seen(cid)
        rec = self._people[cid]
        return {"known": True, "name": rec["name"], "contact_id": cid,
                "unnamed": not bool(rec["name"]), "seen_count": seen,
                "confidence": round(float(score), 4)}

    def _best(self, vec):
        """(contact_id, best_score, runner_up_score) over the stored voices."""
        scored = sorted(((_cosine(vec, r["vec"]), cid)
                         for cid, r in self._people.items() if r.get("vec")),
                        reverse=True)
        if not scored:
            return None, 0.0, 0.0
        best, cid = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        return cid, best, second

    def _auto_enrol(self, vec) -> dict:
        """Store a voice nobody named, so it is recognised next time.

        No generated placeholder name, for the reason the face store gives: a
        name like "speaker-8842" reads as knowledge and is noise. Unnamed is
        honest — "you have heard this person four times" is true and useful —
        and `name_identity` promotes it when the wearer knows who it was.
        """
        # UUID, not a millisecond timestamp. An id of the shape
        # `auto-{int(time.time()*1000)}-{len(vec) % 97}` looks unique and is not:
        # every embedding from one model has the SAME length, so the second term
        # is a constant, and two speakers enrolled inside the same millisecond
        # get the same id — the second silently overwriting the first. That is a
        # biometric record replaced by a different person's, and it showed up the
        # first time two voices were enrolled back to back in a test.
        cid = f"auto-{uuid.uuid4().hex[:16]}"
        now = time.time()
        with self._lock:
            self._people[cid] = {"name": "", "vec": [float(x) for x in vec],
                                 "auto": True, "seen": 1,
                                 "first_ts": now, "last_ts": now}
            self._save()
        return {"known": True, "name": "", "contact_id": cid, "unnamed": True,
                "seen_count": 1, "auto_enrolled": True, "confidence": 1.0}

    def name_identity(self, contact_id: str, name: str) -> dict:
        """Give an auto-enrolled voice a name — and PROMOTE it out of the
        unnamed window, because a named voice is a deliberate keep.

        This is the moment `said_by` starts carrying something a lens can match
        on: until a voice has a name, `their_word("Marcus")` has nothing to find.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "a name is required"}
        self._load()
        with self._lock:
            rec = self._people.get(contact_id)
            if rec is None:
                return {"ok": False, "error": "no such voice"}
            rec["name"] = name[:64]
            rec["auto"] = False
            rec["named_ts"] = time.time()
            self._save()
        try:
            self.brain.activity.add("voice", "Named a remembered voice")
        except Exception:                            # noqa: BLE001
            pass
        return {"ok": True, "contact_id": contact_id, "name": rec["name"]}

    def _note_seen(self, contact_id: str) -> int:
        """Count encounters. Only for voices already stored, so it can never
        become a back door to enrolment."""
        with self._lock:
            rec = self._people.get(contact_id)
            if rec is None:
                return 0
            rec["seen"] = int(rec.get("seen", 0)) + 1
            rec["last_ts"] = time.time()
            self._save()
            return int(rec["seen"])

    def sweep_unnamed(self, ttl_days: float = UNNAMED_TTL_DAYS_DEFAULT) -> int:
        """Drop auto-enrolled voices the wearer never named."""
        self._load()
        if ttl_days <= 0:
            return 0
        cutoff = time.time() - ttl_days * 86400.0
        with self._lock:
            gone = [cid for cid, r in self._people.items()
                    if r.get("auto") and float(r.get("last_ts", 0)) < cutoff]
            for cid in gone:
                self._people.pop(cid, None)
            if gone:
                self._save()
        return len(gone)

    def forget(self, contact_id: str) -> dict:
        self._load()
        with self._lock:
            gone = self._people.pop(contact_id, None) is not None
            if gone:
                self._save()
        return {"ok": gone}

    def forget_all(self) -> int:
        self._load()
        with self._lock:
            n = len(self._people)
            self._people = {}
            self._save()
        return n

    def people(self) -> list:
        """The stored voices, WITHOUT their vectors.

        A voiceprint is the biometric; a listing exists so the wearer can see
        and manage what is held, and handing the templates back over the wire on
        every poll would be shipping the thing itself to draw a list of names.
        """
        self._load()
        return sorted(
            ({"contact_id": cid, "name": r["name"], "auto": bool(r.get("auto")),
              "seen": int(r.get("seen", 0)),
              "last_ts": float(r.get("last_ts", 0))}
             for cid, r in self._people.items()),
            key=lambda r: (-r["seen"], r["contact_id"]))

    def status(self) -> dict:
        self._load()
        named = sum(1 for r in self._people.values() if r.get("name"))
        return {"enabled": self.enabled,
                "auto_enrol": self.auto_enrol,
                "consented": self.consented,
                "consent_version": CONSENT_VERSION,
                "model_available": self.model_available,
                "stored": len(self._people),
                "named": named,
                "unnamed": len(self._people) - named}

    # -- the capture-loop seam --------------------------------------------

    def resolver(self):
        """`speaker_resolver(embedding) -> label` for `CapturePipeline`.

        The pipeline computes the embedding itself (through `self.speaker`) and
        hands it here for a NAME. Returning "" is the honest answer for an
        unknown or unnamed voice, and it matters: `said_by` must only ever hold
        a name a lens can match on. An auto-enrolled id like "auto-1738…" in that
        field would make `owed()` treat the wearer's own promises as somebody
        else's — the ledger stays clean only while `said_by` means "a named other
        person".
        """
        def _resolve(embedding) -> str:
            try:
                if not self.enabled or not self.model_available:
                    return ""
                if not self.privacy.allow_capture():
                    return ""
                self._load()
                vec = [float(x) for x in (embedding or [])]
                if not vec:
                    return ""
                cid, score, runner_up = self._best(vec)
                if (cid is None or score < MATCH_THRESHOLD
                        or (score - runner_up) < MATCH_MARGIN):
                    if self.auto_enrol:
                        self._auto_enrol(vec)        # remembered, still unnamed
                    return ""
                self._note_seen(cid)
                return str(self._people[cid].get("name") or "")
            except Exception as exc:                 # noqa: BLE001 — capture loop
                log.warning("[voice] resolve failed: %s", type(exc).__name__)
                return ""
        return _resolve
