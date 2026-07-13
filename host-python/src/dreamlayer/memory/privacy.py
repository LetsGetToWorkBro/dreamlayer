class PrivacyGate:
    """The capture veil. Two independent inputs gate ingest: an explicit
    pause (the user's veil gesture) and the incognito session shield. They are
    separate flags so leaving incognito can never silently clear an explicit
    pause (and vice versa) — capture resumes only when BOTH are down.

    The incognito input exists because set_incognito()'s contract says capture
    stops hub-side during a private session; before it was wired here, only the
    phone app's cooperation enforced that (a gap found by the DST interleaving
    harness, test_dst_orchestrator.py)."""

    def __init__(self):
        self._paused = False
        self._incognito = False

    @property
    def paused(self):
        return self._paused

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def set_incognito(self, on: bool) -> None:
        self._incognito = bool(on)

    def allow_capture(self) -> bool:
        """May we *keep* what we perceive right now? Blocked by either veil —
        an explicit pause or incognito. Use this on capture/write paths."""
        return not (self._paused or self._incognito)

    def allow_recall(self) -> bool:
        """May we *read back* what we already know? Blocked only by the full
        pause veil ("deaf and blind"). Incognito stops keeping new memories,
        not recalling old ones — you can still ask what you already know while
        incognito. Use this on recall/read paths (ask_brain, retrace, find_way,
        recall_conversation, rewind_day)."""
        return not self._paused


def purge_memory(db, mid):
    db.purge_memory(mid)


def purge_all(db):
    db.purge_all()
