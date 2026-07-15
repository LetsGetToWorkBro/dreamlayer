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

class AlwaysOnGate:
    """The one shared "no veil wired" gate. Capture and recall are always
    allowed. This is the permissive default a lens falls back to when it is
    constructed WITHOUT a PrivacyGate — the isolated-unit-test / example /
    SDK-preview case, where there is no veil to honor.

    It replaces four independent copy-pasted ``_AlwaysOn`` classes that used to
    live in object_lens / social_lens / truth_lens. Consolidating them means the
    permissive fallback has ONE definition to audit, and a lens that wants the
    strict posture can pass ``NullGate()`` instead. In production the
    Orchestrator always injects the real PrivacyGate, so neither fallback is
    reached on a live device."""
    def allow_capture(self) -> bool:
        return True

    def allow_recall(self) -> bool:
        return True


class NullGate:
    """The fail-CLOSED gate: capture and recall are always denied. Pass this to
    a lens when 'no gate wired' must mean 'keep nothing' rather than 'keep
    everything' — the safe default for any path that handles the wearer's own
    perception without an explicit veil to consult."""
    def allow_capture(self) -> bool:
        return False

    def allow_recall(self) -> bool:
        return False


def requires_capture(method):
    """Decorator: short-circuit a capture/write method to ``None`` when the
    instance's veil denies capture. The instance must expose a gate as
    ``self._privacy`` (or ``self.privacy``).

    A MISSING gate now fails CLOSED (deny), not open. The old "no gate → allow"
    default made a decorated method safe only by luck — every caller had to
    remember to wire a gate, and one that forgot would capture while veiled yet
    read as protected in review (re-audit 2026-07-15). A path that wants the
    permissive posture must say so explicitly with ``AlwaysOnGate()`` — which is
    exactly what every lens already does (``self._privacy = privacy or
    AlwaysOnGate()``), so this is a no-op for them and a footgun-closer for any
    future class. Mirrors this module's ``NullGate`` safe-default philosophy.
    One idiom in place of the ~18 hand-written ``if not
    self._privacy.allow_capture(): return`` variants the 2026-07-14 audit found
    scattered across 36 modules."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        gate = getattr(self, "_privacy", None) or getattr(self, "privacy", None)
        if gate is None or not gate.allow_capture():
            return None
        return method(self, *args, **kwargs)
    return wrapper


def requires_recall(method):
    """Decorator: short-circuit a read-back/recall method to ``None`` when the
    instance's veil denies recall (a full pause; incognito still recalls). Same
    gate-resolution rules as ``requires_capture`` — a missing gate fails CLOSED
    (deny), so a decorated recall on a gate-less instance surfaces nothing."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        gate = getattr(self, "_privacy", None) or getattr(self, "privacy", None)
        if gate is None or not gate.allow_recall():
            return None
        return method(self, *args, **kwargs)
    return wrapper


# NB: there is deliberately no purge_* helper here. Forgetting must go through
# memory.retrieval.Retriever.purge_memory / purge_all, which delete the row AND
# evict the vector from the ANN index. Two free functions used to live here that
# called db.purge_* directly — they skipped the index, so a "forget" routed
# through them left the memory recallable by similarity. They had no callers;
# rather than leave the trap in the module named "privacy", they are removed.
