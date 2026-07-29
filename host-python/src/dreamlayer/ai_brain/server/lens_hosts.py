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

    def observe(self, kind: str, summary: str, meta=None, ts=None) -> bool:
        """Put one statement the wearer made into the ring.

        Veil-gated at the door: while incognito the Brain logs nothing, so the
        utterance is dropped rather than recorded. Returns whether it landed, so
        a caller can tell 'veiled' from 'stored' instead of guessing.
        """
        summary = (summary or "").strip()
        if not summary:
            return False
        if not self.privacy.allow_capture():
            return False
        try:
            from ...pipelines.ingest import MemoryEvent
            self.ring.append(MemoryEvent(kind=str(kind or "memory"),
                                         summary=summary,
                                         meta=dict(meta or {})),
                             ts=ts, source="live")
            return True
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lenses] observe failed: %s", type(exc).__name__)
            return False

    def purge_hot(self, cutoff_ts: float) -> int:
        """Drop ring entries older than the hot window. Called by
        `retention_live` so this store ages out on the same policy as every
        other hot store rather than inventing its own."""
        try:
            return int(self.ring.purge_before(cutoff_ts))
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
        statements and the stasis file is a held thought — both are memory, and
        a wipe that leaves them is the residue `purge_memories` exists to
        prevent."""
        n = 0
        try:
            n = len(self.ring)
            self.ring.clear()
        except Exception:                            # noqa: BLE001
            pass
        try:
            if self.stasis_path.exists():
                self.stasis_path.unlink()
        except OSError:
            pass
        self._stasis = None
        return n


def build_lenses(brain) -> BrainLenses:
    return BrainLenses(brain)
