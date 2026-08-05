"""The model learns your words overnight — `mlx_train`, Brain-side.

WHAT THIS CLOSES
----------------
`rem/nightly_mlx.py` had no trainer (`decisions/0008`) and `MLXBackend` loaded
its model with no `adapter_path`, so even a perfect fine-tune would have written
a file nothing could read. Both are fixed; this is the part that decides WHEN,
and — more importantly — what happens when the wearer deletes something.

RETRAIN-ON-FORGET IS THE ONLY HONEST DELETION STORY
---------------------------------------------------
Nothing un-trains a LoRA. "Forget that" deletes a memory row, and if that row's
sentences are in an adapter's weights they stay there, in every answer, for as
long as the adapter is loaded. There is no surgical removal — the research does
not exist at this scale, and pretending otherwise would be the worst overclaim
in the product.

So the guarantee this offers is the one that is actually true:

    delete a row  →  every adapter whose manifest lists it is STALE
    stale adapter →  not loaded, and rebuilt on the next nightly run

That makes deletion take effect at the next run rather than instantly, and
saying so is the point. `adapter.json` beside the weights is what makes it
checkable at all: without a record of which rows produced which adapter, "was
the thing I deleted in there?" is unanswerable, and an unanswerable privacy
question is a no.

WHEN IT RUNS
------------
In the dream window, once a day, and only when the wearer has switched it on.
Off by default and a SECOND opt-in on top of memory itself, for the same reason
the ear is: training a model on your own words is a bigger commitment than
remembering them, because the weights outlive the rows.

Never while incognito, and the trainer's own privacy gate is passed through
rather than duplicated — the corpus is built under `allow_capture`, so a veiled
Brain collects nothing and refuses with a reason rather than training on a
partial night.
"""
from __future__ import annotations

from .veil import VeilGate

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("dreamlayer.train_live")

#: The dream window. Late enough that the wearer has stopped adding to the day,
#: early enough to be finished before they pick the machine up.
TRAIN_HOUR = 3

#: How often the scheduler wakes to check the hour. A fine-tune is a once-a-day
#: job, so this only has to be finer than an hour.
TICK_S = 900.0

MANIFEST = "adapter.json"


class _Rows:
    """The `.memories()` shape `MlxNightlyTrainer` reads, over a plain list.

    The trainer takes a "ring" because that is what the Orchestrator would have
    handed it; the Brain has a store instead. One adapter class rather than
    changing the trainer's contract, so `rem/` stays loadable without the server
    package.
    """

    def __init__(self, rows):
        self._rows = list(rows or [])

    def memories(self):
        return self._rows


class NightlyTrain:
    """The overnight fine-tune, scheduled and held for the session."""

    def __init__(self, brain, trainer=None, now_fn=time.time):
        self.brain = brain
        self._trainer = trainer
        self._now = now_fn
        self._stop: threading.Event | None = None
        self._last_day = ""
        #: Adapters genuinely written. The promotion proof — mlx being
        #: importable says nothing, and a run that refused for a good reason
        #: (too few examples, veiled) is the feature working, not the
        #: capability driving.
        self.trained = 0
        self.runs = 0
        self.last_reason = ""

    # --------------------------------------------------------------- adapter

    def adapter_dir(self) -> str:
        got = (getattr(self.brain.config, "mlx_adapter_dir", "") or "").strip()
        if got:
            return os.path.expanduser(got)
        return str(Path(self.brain.cfg_dir) / "adapter")

    def rows(self) -> list:
        """The raw memory rows, as `MlxNightlyTrainer` wants them.

        `Brain.memories()` is the phone's Memories TAB — a curated blend of
        places, people and reminders, assembled for display. Training on that
        would teach the model the shape of a UI list. This reads the store
        itself, through the same `_memory_db_path` the retention sweep and the
        erase path use, so the corpus and the deletion story can never end up
        pointed at different files.
        """
        try:
            from .retention_live import _memory_db_path
            path = _memory_db_path(self.brain)
            if not path or not os.path.exists(path):
                return []
            from ...memory.db import MemoryDB
            db = MemoryDB(path)
            try:
                return db.memories()
            finally:
                try:
                    db.conn.close()
                except Exception:                    # noqa: BLE001
                    pass
        except Exception as exc:                     # noqa: BLE001
            log.info("[train] store unreadable: %s", type(exc).__name__)
            return []

    def manifest(self) -> dict:
        try:
            raw = (Path(self.adapter_dir()) / MANIFEST).read_text(encoding="utf-8")
            got = json.loads(raw)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def trained_rows(self) -> set:
        """Row ids baked into the adapter currently on disk."""
        try:
            return {int(r) for r in (self.manifest().get("rows") or [])}
        except (TypeError, ValueError):
            return set()

    def is_stale(self) -> bool:
        """Whether the adapter holds a row the wearer has since deleted.

        Asked against the LIVE store: a row that is gone cannot be un-trained,
        so the adapter that carries it must stop being used. Comparing ids is
        enough and the manifest deliberately holds nothing else — a manifest
        containing the sentences would be a second copy of the corpus sitting
        outside every retention sweep.
        """
        baked = self.trained_rows()
        if not baked:
            return False
        try:
            rows = self.rows()
            if not rows:
                raise RuntimeError("no rows")
            live = {int(r.get("id")) for r in rows if r.get("id") is not None}
        except Exception as exc:                     # noqa: BLE001
            # Unreadable store → treat as stale. Fail-closed here means the
            # wearer gets the base model, which is a worse answer and not a
            # broken promise; fail-open means possibly answering from weights
            # built on something they deleted.
            log.info("[train] store unreadable, adapter treated as stale: %s",
                     type(exc).__name__)
            return True
        return not baked <= live

    def retire(self) -> bool:
        """Take a stale adapter out of use. Returns whether anything moved.

        The weights are RENAMED rather than deleted — `.stale` beside them — so
        a wearer who deletes a row by accident has not also destroyed a night of
        compute, and `MLXBackend.adapter_path` (which globs `*.safetensors`)
        stops finding them either way.
        """
        d = Path(self.adapter_dir())
        moved = False
        try:
            for w in list(d.glob("*.safetensors")):
                w.rename(w.with_suffix(w.suffix + ".stale"))
                moved = True
            if moved:
                (d / MANIFEST).rename(d / (MANIFEST + ".stale"))
        except OSError as exc:
            log.warning("[train] could not retire the adapter: %s", exc)
        if moved:
            log.info("[train] adapter retired — a trained row was deleted")
        return moved

    def enforce_forget(self) -> bool:
        """The deletion story, run on demand and before every training run."""
        if self.is_stale():
            return self.retire()
        return False

    # --------------------------------------------------------------- training

    def trainer(self):
        if self._trainer is None:
            from ...rem.nightly_mlx import MlxNightlyTrainer
            self._trainer = MlxNightlyTrainer(
                adapter_dir=self.adapter_dir(),
                model=(getattr(self.brain.config, "mlx_model", "") or ""))
        return self._trainer

    def enabled(self) -> bool:
        return bool(getattr(self.brain.config, "nightly_train_enabled", False))

    def run_once(self) -> dict:
        """One fine-tune. Returns the summary as a dict for the status surface.

        Enforces the deletion story FIRST: a stale adapter is retired before a
        new one is built, so a run that then fails leaves the wearer on the base
        model rather than on weights holding something they deleted.
        """
        if not self.enabled():
            return {"trained": False, "reason": "not enabled"}
        self.enforce_forget()
        self.runs += 1
        try:
            s = self.trainer().train_nightly(
                _Rows(self.rows()), privacy=VeilGate(self.brain))
        except Exception as exc:                     # noqa: BLE001 — never fail a night
            log.warning("[train] run failed: %s", type(exc).__name__)
            self.last_reason = f"error: {type(exc).__name__}"
            return {"trained": False, "reason": self.last_reason}
        self.last_reason = s.reason
        if s.trained:
            self.trained += 1
            # The backend caches its model for the session, so a fresh adapter
            # changes nothing until it reloads. Without this the wearer trains
            # overnight and keeps getting the base model until they restart the
            # Brain — a feature that works and looks broken.
            self._reload_backend()
        return {"trained": bool(s.trained), "reason": s.reason,
                "examples": s.examples, "adapter": s.adapter_path}

    def _reload_backend(self) -> None:
        try:
            b = getattr(self.brain, "_backend", None)
            if b is not None and hasattr(b, "_ensure"):
                b._model = None
                b._tokenizer = None
                b.adapter_loaded = False
        except Exception as exc:                     # noqa: BLE001
            log.info("[train] backend reload skipped: %s", type(exc).__name__)

    # -------------------------------------------------------------- scheduler

    def start(self, tick_s: float = TICK_S) -> bool:
        """Wake in the dream window and train. False when nothing is switched on.

        No thread for a Brain that has not opted in — which is almost all of
        them, and a daemon waking every fifteen minutes to rediscover that is a
        cost with no payoff.
        """
        if self._stop is not None:
            return True
        if not self.enabled():
            return False
        stop = threading.Event()
        self._stop = stop

        def loop():
            while not stop.wait(tick_s):
                try:
                    self.tick()
                except Exception:                    # noqa: BLE001
                    log.warning("[train] tick failed", exc_info=True)
        threading.Thread(target=loop, daemon=True,
                         name="dreamlayer-train").start()
        return True

    def tick(self) -> bool:
        """Train if we are in the window and have not already today."""
        now = self._now()
        lt = time.localtime(now)
        day = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour != TRAIN_HOUR or self._last_day == day:
            return False
        # Marked BEFORE the run, not after: a fine-tune takes hours, and a run
        # that is still going when the next tick fires must not start a second
        # one on the same machine.
        self._last_day = day
        self.run_once()
        return True

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    # ---------------------------------------------------------------- report

    def driving(self) -> bool:
        """An adapter genuinely written. Not mlx being importable, and not a
        run having happened: a run that refused because the corpus was too
        small is the guard working, not the capability."""
        return self.trained > 0

    def status(self) -> dict:
        m = self.manifest()
        return {"enabled": self.enabled(), "runs": self.runs,
                "trained": self.trained, "reason": self.last_reason,
                "adapter_rows": len(m.get("rows") or []),
                "stale": self.is_stale(), "live": self.driving()}


def nightly(brain) -> NightlyTrain:
    got = getattr(brain, "_nightly_train", None)
    if got is None:
        got = NightlyTrain(brain)
        brain._nightly_train = got
    return got
