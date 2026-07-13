"""ops_dream_rem — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ..rem import RetrievalBias
from ..rem.bias import event_key
from .time_scrub import TimeScrubSession


class DreamRemOps:

    # ------------------------------------------------------------------
    # Dream Mode entry / exit
    # ------------------------------------------------------------------

    def enter_dream(self) -> None:
        """Switch to Dream Mode: start ambient engine, notify glasses."""
        self.state.enter_dream()
        self.dream.start()
        self.bridge.send_raw({"t": "dream_enter"})
        self.publish_plugin_event("dream_enter", {})
        # the day's capture is over — persist any batch-buffered ANN adds now
        ann = getattr(self.retriever, "ann", None)
        if ann is not None and hasattr(ann, "flush"):
            ann.flush()


    def exit_dream(self) -> None:
        """Return to Memory Mode: stop ambient engine, notify glasses."""
        self.dream.stop()
        self.dream.ghost.clear_cache()
        self.state.exit_dream()
        self.bridge.send_raw({"t": "dream_exit"})
        self.bridge.send_command("show_ready")
        self.publish_plugin_event("dream_exit", {})


    def maybe_dream_tonight(self, charging: bool):
        """The NightWatch gate: run REM when charging at night, apply the
        verdicts to the durable bias the Horizon already reads. After a
        night runs, the retention lifecycle turns over: the hot ring is
        purged past its window and the warm store is swept — REM promotion
        is the only road from hot to lasting (memory/retention.py)."""
        if self.nightwatch is None:
            return None
        reel = self.nightwatch.maybe_run(charging, self.ring,
                                         drift=self.drift_engine,
                                         privacy=self.privacy)
        if reel is not None:
            self.rem_bias = RetrievalBias.load(self.nightwatch.vault_dir)
            self.horizon._rem = self.rem_bias
            from ..memory.retention import RetentionPolicy, RetentionSweep
            policy = RetentionPolicy(
                hot_hours=getattr(self.config, "retention_hot_hours", 24.0),
                warm_days=getattr(self.config, "retention_warm_days", 90.0))
            sweep = RetentionSweep(self.db, policy, bias=self.rem_bias,
                                   ann=self.retriever.ann)
            self.last_retention = sweep.sweep()
            sweep.purge_hot(self.ring)
        return reel


    def rem_feedback(self, kind: str, summary: str, keep: bool) -> float:
        """Morning-reel keep/fade: one gesture per reel item feeds the bias
        directly (+keep / −fade), persisted to the vault the Horizon reads.
        Returns the item's new bias."""
        from .. import rem as _rem  # noqa: F401  (namespace clarity)
        key = event_key(kind, summary)
        self.rem_bias.apply({key: 0.15 if keep else -0.15})
        if self.nightwatch is not None:
            self.rem_bias.save(self.nightwatch.vault_dir)
        return self.rem_bias.get(key)


    def never_dream_about(self, topic: str, top_k: int = 5) -> int:
        """"Don't dream about that": tag the memories matching `topic` with
        meta.no_dream so consolidation never touches them again. They stay
        fully retrievable — this gates the night, not the memory. Returns
        how many memories were tagged."""
        import json as _json
        tagged = 0
        for _score, m in self.retriever.search(topic, top_k=top_k):
            try:
                meta = _json.loads(m.get("meta") or "{}")
            except (TypeError, ValueError):
                meta = {}
            if meta.get("no_dream"):
                continue
            meta["no_dream"] = True
            self.db.conn.execute("UPDATE memories SET meta=? WHERE id=?",
                                 (_json.dumps(meta), m["id"]))
            self.db.conn.commit()
            tagged += 1
        # the live ring too — tonight's dream draws from it directly
        words = {w.lower() for w in topic.split() if len(w) > 2}
        for buffered in self.ring.since(0.0):
            ev = buffered.event
            summary_words = {w.lower()
                             for w in (getattr(ev, "summary", "") or "").split()}
            if words & summary_words:
                meta = getattr(ev, "meta", None)
                if isinstance(meta, dict):
                    meta["no_dream"] = True
                    tagged += 1
        return tagged


    def tick_horizon(self, now: float | None = None) -> dict | None:
        """Compose and send the day-ring when due or changed. While
        privacy-paused only the empty pause frame flows — the absence of
        marks must be deliverable (docs/cinema_v2/horizon_frame.md)."""
        frame = self.horizon.maybe_frame(now, paused=self.privacy.paused)
        if frame is not None:
            self.bridge.send_raw(frame)
        return frame


    # ------------------------------------------------------------------
    # Time-Scrub Halo
    # ------------------------------------------------------------------

    def start_scrub(self, lookback_s: float = 3600.0, now: float | None = None,
                    show: bool = False) -> dict | None:
        self._scrub_session = TimeScrubSession(self.ring, lookback_s=lookback_s, now=now)
        card = self._scrub_session.current()
        if show and card is not None:
            self.bridge.send_card(card, event="scrub")
        return card


    def rewind_scrub(self, now: float | None = None) -> dict | None:
        """Rewind the whole day *on the glasses*: load today's moments into the
        time-scrub engine and flash the most-recent node. Twist/tap forward and
        back with scrub(); the phone Rewind shows the same day as a list."""
        import time
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        elapsed = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
        # back to midnight, but always at least the last hour — otherwise a
        # rewind just after midnight is blank even though you were just doing
        # something a few minutes ago (those moments sit before the date line).
        return self.start_scrub(lookback_s=max(elapsed, 3600.0), now=now, show=True)


    def scrub(self, direction: str, show: bool = True) -> dict | None:
        if self._scrub_session is None:
            return None
        card = (self._scrub_session.forward() if direction == "forward"
                else self._scrub_session.back())
        if show and card is not None:
            self.bridge.send_card(card, event="scrub")
        return card


    def scrub_select(self, index: int) -> dict | None:
        if self._scrub_session is None:
            return None
        return self._scrub_session.select(index)
