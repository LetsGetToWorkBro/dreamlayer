"""lens_hosts.py — the lenses that had no way into the shipped Brain.

`scripts/lens_reachability.py` found 12 of the 28 Python lenses declared in
`lenses.py` outside the Brain's entire import closure — not merely uncalled, but
unloadable from the product. Retention (`decisions/0001`) and the Social Lens
(#542) were the same shape and were fixed the same way: run the real primitive
Brain-side, never resurrect the `Orchestrator`.

This module is the host for the ones that share a dependency, plus the ones that
need nothing but somewhere to live:

    Provenance         trace a belief to where you got it
    Candor             your own story, kept consistent
    Commitment Drift   promises as physics objects, decaying until tended
    Saga               those promises as a personal RPG
    Stasis             freeze a thought, resume inside it
    Premonition        your rhythms, shimmering slightly ahead of now
    Inner Weather      your body churns the core; the room storms the rim

THE RING IS THE ACTUAL MISSING PIECE
------------------------------------

Provenance, Candor and Commitment Drift each take a `ring` and call
`ring.latest(...)` / `ring.since(...)`. That is a `SemanticRingBuffer` of what
the wearer SAID — and the Brain had nothing of the kind. The ear writes
transcribed utterances into `brain.index` (a document index, rebuilt from disk
at boot), and `WorldLensHost.ring` holds SIGHTINGS from looks. Neither is a
timeline of the wearer's own statements, so all three lenses would have been
wired to an empty room.

So the ring here is new, and it is the reason this is a build rather than glue.
Two decisions in it are load-bearing:

  * **It is hot-tier, matching `memory/retention.py`.** In-memory, capacity-
    bounded, and swept by `retention_live` on the same `retention_hot_hours`
    window as every other hot store. A durable ring would be a new permanent
    record of everything the wearer says, which is a bigger privacy promise than
    this feature is worth.
  * **It is warm-SEEDED at first use**, from the memory store's recent rows.
    Purely in-memory would mean Candor forgets your story every restart and
    quietly answers "no contradiction" because it has nothing to compare
    against — a lens that is silent for the wrong reason, which is the failure
    mode this whole audit is about.

Everything the ring holds is already stored: it is a view over rows the Brain
wrote, not a second copy of anything new. The Veil applies at the door, as
everywhere else: `observe` drops an utterance while incognito rather than
letting it into the ring.
"""
from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger("dreamlayer.lenses")

RING_CAPACITY = 256          # a few days of statements, not a transcript
SEED_LIMIT = 200             # warm rows pulled in at first use
STASIS_FILE = "stasis.json"

# Memory kinds worth putting in the ring. A sighting is not a statement, and the
# lenses here reason about what the wearer SAID; `object` rows would drown the
# signal Candor and Provenance look for.
SPOKEN_KINDS = frozenset({"conversation", "promise", "task", "taught", "memory",
                          "heard", "person"})


def _due_text(due_ts) -> str:
    """A due timestamp as the glass says it. Empty when there is no due date —
    `CommitmentDriftEngine` falls back to a 48-hour lifetime in that case, and
    inventing "in 2 days" from an implementation default would put a deadline
    on the glass that the wearer never gave."""
    if not due_ts:
        return ""
    import time as _t
    left = float(due_ts) - _t.time()
    if left < 0:
        return "overdue"
    if left < 3600:
        return f"in {max(1, int(left // 60))} min"
    if left < 86400:
        return f"in {int(left // 3600)} h"
    return f"in {int(left // 86400)} d"


class _LensGate:
    """The Veil, fail-closed — identical posture to `ear._EarGate`,
    `world_lens._LookGate` and `face_live._FaceGate`. An unreadable trust signal
    resolves to veiled, never to 'record it'."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class BrainLenses:
    """The lens set, built once and cached on the Brain.

    Every lens is lazy: constructing this object touches no model, opens no
    file and reads no database, because it is built on the Brain's first use of
    ANY lens and most sessions will use none of them.
    """

    def __init__(self, brain):
        self.brain = brain
        self.privacy = _LensGate(brain)
        self._lock = threading.RLock()
        self._ring = None
        self._seeded = False
        self._provenance = None
        self._candor = None
        self._drift = None
        self._saga = None
        self._stasis = None
        self._premonition = None
        self._weather = None

    # -- the ring ----------------------------------------------------------

    @property
    def ring(self):
        """The wearer's recent statements. Seeded once, then appended to."""
        with self._lock:
            if self._ring is None:
                from ...memory.ring_buffer import SemanticRingBuffer
                self._ring = SemanticRingBuffer(RING_CAPACITY)
            if not self._seeded:
                self._seeded = True                  # set FIRST: a failing seed
                self._seed()                         # must not retry every call
            return self._ring

    def _seed(self) -> None:
        """Fill the ring from the memory store's recent rows.

        Without this the three ring lenses answer from an empty timeline after
        every restart — and answer *quietly*, which reads exactly like "nothing
        to report". Best-effort: a missing or unreadable store leaves the ring
        empty and the lenses honestly say they have nothing yet.
        """
        try:
            from .retention_live import _memory_db_path
            path = _memory_db_path(self.brain)
            if not path or not os.path.exists(path):
                return
            from ...memory.db import MemoryDB
            db = MemoryDB(path)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] ring seed unavailable: %s", type(exc).__name__)
            return
        try:
            from datetime import datetime
            from ...pipelines.ingest import MemoryEvent
            rows = [r for r in db.memories()
                    if (r.get("kind") or "") in SPOKEN_KINDS]
            for row in rows[-SEED_LIMIT:]:
                try:
                    raw = row.get("created_at") or ""
                    ts = datetime.fromisoformat(raw).timestamp() if raw else None
                except ValueError:
                    ts = None
                if ts is None:
                    continue                          # unknown age: same rule as
                                                      # retention — do not guess
                meta = {}
                try:
                    meta = json.loads(row.get("meta") or "{}")
                except (TypeError, ValueError):
                    pass
                self._ring.append(
                    MemoryEvent(kind=str(row.get("kind") or "memory"),
                                summary=str(row.get("summary") or ""),
                                confidence=float(row.get("confidence") or 0.5),
                                meta=meta if isinstance(meta, dict) else {},
                                db_id=int(row.get("id") or 0)),
                    ts=ts, source="seed")
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] ring seed failed: %s", type(exc).__name__)
        finally:
            try:
                db.conn.close()
            except Exception:                        # noqa: BLE001
                pass

    def observe(self, kind: str, summary: str, meta=None, ts=None,
                via: str = "", person: str = "", confidence: float = 0.6) -> bool:
        """Put one statement into the ring.

        Veil-gated at the door: while incognito the Brain logs nothing, so the
        utterance is dropped rather than recorded. Returns whether it landed, so
        a caller can tell 'veiled' from 'stored' instead of guessing.

        `via` and `person` are what make Provenance able to answer honestly, and
        they are the caller's job because only the caller knows. `via` is HOW
        this reached the Brain — "said" when the wearer deliberately spoke or
        typed it (`/dreamlayer/voice`, `/dreamlayer/lens/observe`), "heard" when
        the room ear picked it out of ambient audio. Provenance treats
        `_FIRSTHAND_VIA` ("said"/"saw"/"observed"/"did"/"firsthand") as
        firsthand and everything else as second-hand, so passing the wrong one
        does not merely lose detail — it makes the lens claim you witnessed
        something you overheard. When the caller does not know, pass nothing:
        the lens falls back to "recorded", which is neither firsthand nor
        attributed to anyone.

        `person` is who said it. Nothing in this product does speaker
        diarization (`ear.py:129-131` — that is a deliberate limit, not a gap),
        so on the ambient path it is always empty and Provenance renders the
        attribution as "you". The one place it is genuinely known is a voice
        intent that names someone ("note that Ana said…"), and that path passes
        it.

        `confidence` matters more than it looks: `ProvenanceLens` skips
        anything below 0.20 and `ConsistencyEngine` below 0.30, so a default of
        0.0 would make both lenses silently ignore every live utterance while
        looking like they were wired.
        """
        summary = (summary or "").strip()
        if not summary:
            return False
        if not self.privacy.allow_capture():
            return False
        try:
            from ...pipelines.ingest import MemoryEvent
            m = dict(meta or {})
            if via:
                m.setdefault("via", via)
            if person:
                m.setdefault("person", person)
            self.ring.append(MemoryEvent(kind=str(kind or "memory"),
                                         summary=summary,
                                         confidence=float(confidence),
                                         meta=m),
                             ts=ts, source="live")
            return True
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] observe failed: %s", type(exc).__name__)
            return False

    def ingest_utterance(self, text: str, *, via: str = "heard",
                         person: str = "") -> dict:
        """One line of speech in; the ring fed, and Candor's answer out.

        This is the caller the lens set never had. `observe()` was the only live
        append path and nothing called it, so on a shipped Brain the ring was
        empty at every moment — and an empty ring does not make these lenses
        fail, it makes them AGREE WITH YOU. Candor finds no contradiction,
        Provenance finds no source, Commitment Drift finds no promise slipping.
        Every one of them reports the reassuring answer, which is the exact
        failure mode `decisions/0001` is about.

        Two things go into the ring per utterance, and both are needed:

          * the line itself, so Candor and Provenance have a statement to
            compare against;
          * whatever tier-1 extraction finds in it — `promise`, `task`,
            `person` — with their own kinds and meta, because Commitment Drift
            reads `ring.latest(kind="task")` and nothing else. A ring of
            undifferentiated "heard" blobs leaves Drift and Saga permanently
            empty no matter how much is said.

        Extraction is tier-1 only: pure regex over the text, no store, no model.
        The Brain writes no memory rows here — the ring is hot-tier and swept,
        and adding a durable writer is a separate decision with its own privacy
        surface, not something to slip in behind a lens.

        Veil-gated by `observe`, so an incognito utterance lands nowhere and
        Candor is never even asked. Never raises: this sits on the capture loop.
        """
        text = (text or "").strip()
        out: dict = {"observed": 0, "candor": None}
        if not text:
            return out
        if not self.privacy.allow_capture():
            return out
        # Candor FIRST, before anything from this utterance is in the ring.
        # Order is load-bearing, not style: extraction turns "I won't pay the
        # deposit" into a `promise`/`task` row whose summary drops the negator,
        # and comparing the line against a fragment of ITSELF fires a
        # contradiction on every negated sentence the wearer says. Checking
        # against the prior baseline only is also what the Orchestrator does
        # (`ops_world_lenses.check_consistency` is handed the new claim, never
        # a ring that already holds it).
        try:
            out["candor"] = self.candor_check(text)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] candor on ingest failed: %s",
                        type(exc).__name__)
        kind = "conversation" if via in ("said", "typed") else "heard"
        if self.observe(kind, text, via=via, person=person):
            out["observed"] += 1
        try:
            from ...pipelines.ingest import extract_events
            for ev in extract_events(text):
                if ev.kind not in SPOKEN_KINDS:
                    continue                     # objects and places are not
                                                 # statements — see SPOKEN_KINDS
                meta = dict(ev.meta or {})
                if self.observe(ev.kind, ev.summary, meta=meta, via=via,
                                person=meta.get("person") or person,
                                confidence=float(ev.confidence)):
                    out["observed"] += 1
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] extract failed: %s", type(exc).__name__)
        return out

    def purge_hot(self, cutoff_ts: float) -> int:
        """Drop ring entries older than the hot window. Called by
        `retention_live` so this store ages out on the same policy as every
        other hot store rather than inventing its own.

        Two deliberate narrowings:

          * A ring that was never built holds nothing, so this returns 0 rather
            than touching `self.ring` — reading that property SEEDS from the
            memory database, and an hourly sweep must not be what opens the
            store on a Brain that has used no lens.
          * `COLD_KINDS` are exempt from the AGE bound, because they are exempt
            from it on disk too. A promise due Friday is a `task` row that
            `memory/retention.py` keeps forever; expiring its ring view after
            24 h would delete an in-force commitment out from under Commitment
            Drift (48 h lifetime) and Saga, and the lens would report the
            promise as simply never made. Capacity still bounds them.
        """
        if self._ring is None:
            return 0
        try:
            from ...memory.retention import COLD_KINDS
            return int(self._ring.purge_before(cutoff_ts, keep_kinds=COLD_KINDS))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] hot purge failed: %s", type(exc).__name__)
            return 0

    # -- the lenses --------------------------------------------------------

    @property
    def provenance(self):
        if self._provenance is None:
            from ...orchestrator.provenance import ProvenanceLens
            self._provenance = ProvenanceLens(self.ring)
        return self._provenance

    @property
    def candor(self):
        if self._candor is None:
            from ...orchestrator.consistency import ConsistencyEngine
            self._candor = ConsistencyEngine(self.ring)
        return self._candor

    @property
    def drift(self):
        if self._drift is None:
            from ...orchestrator.commitment_drift import CommitmentDriftEngine
            self._drift = CommitmentDriftEngine(self.ring)
        return self._drift

    @property
    def saga(self):
        if self._saga is None:
            from ...orchestrator.quest import QuestLog
            self._saga = QuestLog(self.drift, vault_dir=self._vault())
        return self._saga

    @property
    def premonition(self):
        if self._premonition is None:
            from ...dream_mode.premonition import RecurrenceModel
            self._premonition = RecurrenceModel()
            self._premonition.observe_buffer(self.ring)
        return self._premonition

    @property
    def weather(self):
        if self._weather is None:
            from ...dream_mode.inner_weather import InnerWeather
            self._weather = InnerWeather(privacy=self.privacy)
        return self._weather

    def weather_tick(self, payload=None) -> list:
        """Advance Inner Weather from a phone sensor payload.

        `InnerWeather.sample` reads `ctx.imu_delta`, `ctx.imu_pose` and
        `ctx.extra["self_prosody"]` off a context OBJECT — it was written for the
        glasses, where the orchestrator hands it a live sensor frame. The Brain
        has no IMU of its own, but the phone does and already posts heading and
        tilt on the live path, so this adapts that payload into the shape the
        lens expects instead of leaving the lens unreachable for want of three
        attribute names.

        With no sensors at all the lens sees zeros and reports calm, which is
        honest: no motion was observed. It does NOT invent a reading.
        """
        payload = payload or {}

        class _Ctx:
            imu_delta = payload.get("imu_delta") or {}
            imu_pose = payload.get("imu_pose") or {}
            extra = payload.get("extra") or {}

        try:
            return list(self.weather.tick(_Ctx()) or [])
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] weather tick failed: %s", type(exc).__name__)
            return []

    @property
    def stasis(self):
        if self._stasis is None:
            from ...orchestrator.stasis import StasisStack
            self._stasis = StasisStack()
            self._load_stasis()
        return self._stasis

    # -- the answers, veil-gated -------------------------------------------
    #
    # Every method below is what a route calls. They are here rather than in
    # `server.py` for one reason: the Veil. `trace()` and `check()` read a
    # timeline of what was said in front of the wearer, which is exactly the
    # kind of read the shield exists to stop — and a gate that lives in the
    # route handler is a gate the next caller forgets. The Orchestrator's
    # precedent gates on `allow_capture` (`ops_world_lenses.py:37`); `_LensGate`
    # makes `allow_recall` the same predicate, so this gates on recall and the
    # two agree. A veiled call returns None — never an empty result, which a
    # caller would render as "nothing to report".

    def trace(self, claim: str):
        """Provenance: where did this belief come from?

        Returns the result dict, `None` while veiled, and `{"found": False}`
        when the ring holds nothing bearing on the claim. Those three are
        deliberately distinguishable: "I am not allowed to say", "I have never
        heard of this" and "here is where you got it" are different answers and
        a wearer deserves to know which one they got.
        """
        claim = (claim or "").strip()
        if not claim:
            return {"found": False, "claim": "", "reason": "empty-claim"}
        if not self.privacy.allow_recall():
            return None
        try:
            r = self.provenance.trace(claim)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] trace failed: %s", type(exc).__name__)
            return {"found": False, "claim": claim, "reason": "lens-error"}
        if not r.found:
            return {"found": False, "claim": claim}
        import time as _t
        now = _t.time()
        return {
            "found": True,
            "claim": r.claim,
            "status": r.status,
            "corroboration": r.corroboration,
            "contradiction": r.contradiction,
            "origin": {"summary": r.origin.summary, "who": r.origin.who,
                       "via": r.origin.via, "when_ts": r.origin.when_ts,
                       "attribution": r.origin.attribution(now)},
            "supports": [{"summary": s.summary, "who": s.who, "via": s.via,
                          "when_ts": s.when_ts} for s in r.supports],
            "card": r.card,
        }

    def candor_check(self, claim: str, push: bool = True):
        """Candor: does this contradict something you said before?

        `push` sends the card to the glass. The card's FOOTER carries the prior
        statement, which is the lens's whole proposition — a surface that drops
        footers renders "You said different before" with no "before" in it, so
        the full card goes out and the renderer's job is to show it.
        """
        claim = (claim or "").strip()
        if not claim:
            return {"fired": False, "claim": ""}
        if not self.privacy.allow_recall():
            return None
        try:
            r = self.candor.check(claim)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] candor failed: %s", type(exc).__name__)
            return {"fired": False, "claim": claim, "reason": "lens-error"}
        out = {"fired": r.fired, "claim": claim, "reason": r.reason,
               "prior": r.prior_summary, "detail": r.detail, "card": r.card}
        if r.fired and push and r.card:
            self._push("candor", r.card)
        return out

    # -- commitments --------------------------------------------------------

    @staticmethod
    def _drift_json(rec) -> dict:
        return {"subject": (rec.event.summary or "").strip(),
                "state": rec.state, "decay": round(float(rec.decay), 3),
                "created_ts": rec.created_ts, "due_ts": rec.due_ts,
                "resolved": rec.resolved, "bloomed": rec.bloomed,
                "person": (rec.event.meta or {}).get("person") or ""}

    def drift_tick(self, push: bool = True) -> dict:
        """Advance every commitment and surface the ones that just slipped.

        This is the lens's clock. Nothing else moves a commitment down the
        ladder, so without a scheduled caller Commitment Drift is a lens that
        only ever reports the state a promise had when it was made — which
        looks exactly like a promise nobody is worried about.
        """
        if not self.privacy.allow_recall():
            return {"ok": False, "reason": "veiled"}
        try:
            alerts = self.drift.tick()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] drift tick failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "lens-error"}
        rows = [self._drift_json(r) for r in alerts]
        if push:
            for rec in alerts:
                self._push("commitment_drift", self._drift_card(rec))
        return {"ok": True, "alerts": rows,
                "records": [self._drift_json(r) for r in self.drift.all_records()]}

    @staticmethod
    def _drift_card(rec) -> dict:
        """The REAL `CommitmentDriftCard`, from `hud/cards.py`.

        An earlier version of this built a lookalike dict by hand, which is the
        subtler half of the parity problem: `renderer.lua` has a dedicated
        `draw_commitment_drift` keyed on the type, and it reads `task`,
        `person`, `drift_state` and `decay` — none of which a hand-rolled
        `{primary, detail, footer}` carries. The card would have drawn, wrong,
        and looked fine in JSON. `scripts/hud_reachability.py` exists because
        that gap is invisible from the Brain side.
        """
        from ...hud import cards
        return cards.commitment_drift({
            "task": (rec.event.summary or "a promise").strip(),
            "person": (rec.event.meta or {}).get("person") or "",
            "drift_state": rec.state,
            "decay": float(rec.decay),
            "due": _due_text(rec.due_ts),
        })

    def tend(self, subject: str):
        """Nudge a commitment — progress without finishing it."""
        if not self.privacy.allow_recall():
            return None
        try:
            rec = self.saga.tend(subject)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] tend failed: %s", type(exc).__name__)
            return None
        return self._drift_json(rec) if rec is not None else None

    # -- the same commitments, as a game ------------------------------------

    def quests(self) -> dict:
        if not self.privacy.allow_recall():
            return {"ok": False, "reason": "veiled"}
        try:
            qs = self.saga.quests()
            st = self.saga.stats()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] quests failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "lens-error"}
        from dataclasses import asdict
        return {"ok": True,
                "quests": [{**asdict(q), "card": q.to_hud_card()} for q in qs],
                "stats": asdict(st)}

    def quest_complete(self, subject: str, push: bool = True):
        """Keep a promise: pay the XP, push the reward, unlock the badges.

        The badge half is the part that was missing rather than merely unwired.
        `saga.py` declares five quest achievements — Keeper, From the Brink,
        Unbroken, Relentless, Devoted — each keyed to an event id
        (`quest_done` / `quest_rescue` / `streak`) that **nothing in the
        codebase ever emitted**. The phone's badge grid rendered all five as
        permanently locked and no sequence of user actions could change that.
        `QuestLog` keeps its own tally; this mirrors it into the Saga profile
        the phone actually reads, using absolute `count=` for the streak so a
        streak of 5 unlocks Unbroken rather than incrementing a counter five
        separate times.
        """
        if not self.privacy.allow_recall():
            return None
        try:
            reward = self.saga.complete(subject)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] quest complete failed: %s", type(exc).__name__)
            return None
        if reward is None:
            return None
        unlocked = self._saga_profile_record(reward)
        card = reward.to_hud_card()
        if push:
            self._push("quest_reward", card)
        from dataclasses import asdict
        return {**asdict(reward), "card": card, "badges_unlocked": unlocked}

    def _saga_profile_record(self, reward) -> list:
        """Mirror a quest completion into the Saga badge profile. Best-effort:
        a failure here costs a badge, never the completion itself."""
        out: list = []
        rec = getattr(self.brain, "saga_record", None)
        if rec is None:
            return out
        try:
            out += list(rec("quest_done") or [])
            if reward.rescued:
                out += list(rec("quest_rescue") or [])
            if reward.streak:
                out += list(rec("streak", count=int(reward.streak)) or [])
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] saga badge record failed: %s",
                        type(exc).__name__)
        return out

    def quest_abandon(self, subject: str) -> bool:
        if not self.privacy.allow_recall():
            return False
        try:
            return bool(self.saga.abandon(subject))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] quest abandon failed: %s", type(exc).__name__)
            return False

    # -- rhythms ------------------------------------------------------------

    def predictions(self) -> list:
        """Premonition: what usually happens next, if the pattern is strong
        enough to say so. The model is fed from the ring at first use and
        re-fed here, so a prediction reflects everything heard since."""
        if not self.privacy.allow_recall():
            return []
        try:
            self.premonition.observe_buffer(self.ring)
            return [{"kind": p.kind, "expected_ts": p.expected_ts,
                     "confidence": round(float(p.confidence), 3),
                     "place": p.place, "hour": p.hour}
                    for p in self.premonition.predict()]
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] predict failed: %s", type(exc).__name__)
            return []

    # -- holding a thought --------------------------------------------------

    def freeze(self, note: str = "", gaze=None):
        """Stasis: put the current thought on the stack and keep it.

        ONE DELIBERATE NARROWING, stated because it changes what the lens is.
        The Orchestrator's `FreezeFrame.final_utterance` is documented as
        verbatim — "the whole point is handing back *your* unfinished sentence,
        dash included". The Brain never holds an unscrubbed utterance: the ear
        runs the PII redactor BEFORE anything is stored (`ear.py:115-120`), and
        the ring is downstream of that. So what this replays is the SCRUBBED
        line, and a resume can hand back a sentence with a phone number filed
        off. Restoring true verbatim would mean keeping raw transcript text
        the Brain deliberately does not keep — a new privacy surface, not
        plumbing — so the narrowing stands and is written down instead.
        """
        if not self.privacy.allow_capture():
            return None
        import time as _t
        now = _t.time()
        try:
            from ...orchestrator.stasis import FreezeFrame, TAIL_S
            window = [{"kind": b.event.kind, "summary": b.event.summary,
                       "ts": b.ts} for b in self.ring.since(now - TAIL_S)]
            tail = (note or "").strip()
            if not tail and window:
                tail = window[-1]["summary"]
            frame = FreezeFrame(
                # not a memories-row id: the Brain persists frames to
                # `stasis.json`, not to a `kind="stasis"` row, so this is a
                # millisecond stamp — unique, ordered, and never colliding with
                # a real row id because nothing here reads one.
                id=int(now * 1000),
                created_ts=now,
                ring_window=window,
                final_utterance=tail,
                gaze_context=gaze,
            )
            evicted = self.stasis.push(frame)
            self.save_stasis()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] freeze failed: %s", type(exc).__name__)
            return None
        card = self._stasis_card("HELD", tail or "a thought", "resume it any time")
        self._push("stasis", card)
        return {"ok": True, "id": frame.id, "held": len(self.stasis),
                "evicted": [f.id for f in evicted],
                "utterance": tail, "card": card}

    def resume(self, frame_id=None):
        """Pick a held thought back up. Without an id, the top of the stack —
        "where was I" means the most recent one, which is what a wearer saying
        it out loud means too."""
        if not self.privacy.allow_recall():
            return None
        import time as _t
        now = _t.time()
        try:
            frame = (self.stasis.get(int(frame_id)) if frame_id is not None
                     else self.stasis.top())
            if frame is None:
                return {"ok": False, "reason": "nothing-held"}
            fresh = frame.resumed(now)
            self.stasis.replace_frame(fresh)
            self.save_stasis()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] resume failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "lens-error"}
        card = self._stasis_card(
            "WHERE YOU WERE", fresh.final_utterance or "a held thought",
            fresh.freshness(now))
        self._push("stasis", card)
        return {"ok": True, "id": fresh.id,
                "utterance": fresh.final_utterance,
                "freshness": fresh.freshness(now),
                "resume_count": fresh.resume_count,
                "window": list(fresh.ring_window), "card": card}

    def pin(self, frame_id) -> bool:
        """Pin a held thought so it never composts — the "I'll get back to this
        next month" escape hatch, and the same word `meta.pinned` means
        everywhere else in retention."""
        if not self.privacy.allow_capture():
            return False
        try:
            frame = self.stasis.get(int(frame_id))
            if frame is None:
                return False
            if frame.meta.get("pinned"):
                return True              # already pinned — no second confirmation
            self.stasis.replace_frame(frame.pinned())
            self.save_stasis()
            # The keep, confirmed on the glass. "Held." is verbatim from the
            # Orchestrator's own pin path and is the WHOLE payload that draws —
            # both renderers read `primary` and nothing else here. Note what is
            # deliberately absent: the wearer's held sentence. A confirmation
            # that quotes what it kept would push captured speech over the event
            # stream, which is the one thing the ear's redaction rules exist to
            # prevent.
            from ...hud import cards
            self._push("saved_memory", cards.saved_memory("Held."))
            return True
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] pin failed: %s", type(exc).__name__)
            return False

    def compost(self) -> int:
        """Dissolve held thoughts past their half-life. Pinned frames sit at
        decay 0 forever and are never due, so this cannot take one."""
        try:
            import time as _t
            due = self.stasis.compost_due(_t.time())
            if due:
                self.save_stasis()
            return len(due)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] compost failed: %s", type(exc).__name__)
            return 0

    def frames(self) -> list:
        if not self.privacy.allow_recall():
            return []
        import time as _t
        now = _t.time()
        try:
            return [{"id": f.id, "utterance": f.final_utterance,
                     "created_ts": f.created_ts,
                     "freshness": f.freshness(now),
                     "decay": round(f.decay(now), 3),
                     "resume_count": f.resume_count,
                     "pinned": bool(f.meta.get("pinned"))}
                    for f in self.stasis.frames()]
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] frames failed: %s", type(exc).__name__)
            return []

    @staticmethod
    def _stasis_card(eyebrow: str, primary: str, footer: str) -> dict:
        return {"type": "StasisCard", "dismiss_ms": 5000, "eyebrow": eyebrow,
                "primary": primary[:80], "detail": "", "footer": footer,
                "color": "accent_memory",
                "lines": [eyebrow, primary[:80], footer]}

    def _push(self, kind: str, card) -> None:
        """Send a card to the glass. Never veil_ok: every lens here reads the
        wearer's own timeline, and none of them is a safety alert — the one
        category `ear.note_acoustic_context` lets pierce the shield."""
        if not card:
            return
        try:
            self.brain.push_event(kind, card, veil_ok=False)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] push failed: %s", type(exc).__name__)

    def status(self) -> dict:
        """What the lens set can answer right now — for `/dreamlayer/lenses`
        and the capabilities probe. Reports the ring WITHOUT seeding it, so a
        status read never opens the memory store."""
        n = len(self._ring) if self._ring is not None else 0
        return {"ok": True, "ring": n, "seeded": self._seeded,
                "veiled": not self.privacy.allow_recall(),
                "held": len(self._stasis) if self._stasis is not None else 0,
                "lenses": ["provenance", "candor", "drift", "saga", "stasis",
                           "premonition", "weather"]}

    # -- stasis persistence ------------------------------------------------
    # A held thought that does not survive a restart is not a save state, which
    # is the entire premise of the lens ("freeze a thought, resume inside it").

    def _vault(self):
        from pathlib import Path
        d = Path(self.brain.cfg_dir) / "vault"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return d

    @property
    def stasis_path(self):
        from pathlib import Path
        return Path(self.brain.cfg_dir) / STASIS_FILE

    def _load_stasis(self) -> None:
        """Rebuild `FreezeFrame`s from disk. `StasisStack.load` wants frame
        OBJECTS, not the dicts we persist, so the reconstruction happens here —
        and per row, so one corrupt frame costs that thought rather than every
        held thought."""
        p = self.stasis_path
        if not p.exists():
            return
        try:
            rows = json.loads(p.read_text()) or []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] stasis unreadable: %s", type(exc).__name__)
            return
        from ...orchestrator.stasis import FreezeFrame
        frames = []
        for row in rows if isinstance(rows, list) else []:
            try:
                frames.append(FreezeFrame(**row))
            except Exception:                        # noqa: BLE001 — skip one
                continue
        if frames:
            try:
                self._stasis.load(frames)
            except Exception as exc:                 # noqa: BLE001
                log.warning("[lenses] stasis load failed: %s", type(exc).__name__)

    def save_stasis(self) -> None:
        """`FreezeFrame` is a plain dataclass with no serializer of its own, so
        `asdict` is the contract. Everything inside it is already
        dict-serializable semantic data by that class's own design."""
        from dataclasses import asdict
        try:
            frames = [asdict(f) for f in self.stasis.frames()]
            tmp = self.stasis_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(frames))
            os.replace(tmp, self.stasis_path)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] stasis save failed: %s", type(exc).__name__)

    def forget_all(self) -> int:
        """Erase-everything must reach these too. The ring is the wearer's own
        statements, the stasis file is a held thought, and the quest tally is a
        behavioural record of how reliably they keep promises — all three are
        memory, and a wipe that leaves them is the residue `purge_memories`
        exists to prevent.

        The quest tally is the one that used to survive. `QuestLog` writes
        `<cfg_dir>/vault/quest_log.json` and re-reads it on next construction,
        so before this an erase-everything left `xp=50, streak=1,
        achievements=['Keeper']` on disk and a freshly built lens set reported
        them straight back. The Orchestrator has the same hole; the difference
        is that this path claims to close it.

        Every cached lens is dropped too, not only the two with files. `saga`
        holds the tally in memory, `drift` holds records keyed to ring buckets
        and `premonition` holds learned slots — keeping any of them past a wipe
        means the next read answers from state the wearer just erased.
        """
        n = 0
        try:
            if self._ring is not None:
                n = len(self._ring)
                self._ring.clear()
            self._seeded = False        # a re-seed after a wipe must find the
                                        # store empty; the erase truncates it
        except Exception:                            # noqa: BLE001
            pass
        for path in (self.stasis_path, self.quest_path):
            try:
                if path is not None and path.exists():
                    path.unlink()
            except OSError:
                pass
        self._stasis = None
        self._saga = None
        self._drift = None
        self._provenance = None
        self._candor = None
        self._premonition = None
        self._weather = None
        return n

    @property
    def quest_path(self):
        """`<cfg_dir>/vault/quest_log.json` — read straight off `QuestLog`'s own
        constant so a rename there cannot leave this pointed at a stale name and
        silently stop erasing the file."""
        from ...orchestrator.quest import TALLY_FILE
        v = self._vault()
        return (v / TALLY_FILE) if v is not None else None


def build_lenses(brain) -> BrainLenses:
    return BrainLenses(brain)
