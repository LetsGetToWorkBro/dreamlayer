import threading
from dataclasses import dataclass, field


@dataclass
class HostState:
    """The host's live posture, shared across threads.

    ``mode`` is written on the bridge/button callback thread (on_button's
    double_tap toggles Memory<->Dream) and read on the capture daemon thread
    (ops_ingest.on_scene_frame/on_audio_frame call ``is_dream()``) and on the
    HTTP/simulator threads. A single str assignment or compare is atomic under
    CPython, so a bare flag flip or read needs no lock — but the *toggle* is a
    compound check-then-act (read ``is_dream()`` → write ``enter_dream()`` /
    ``exit_dream()``). Run from two threads that two-step split lets a pair of
    toggles interleave and silently drop one. A reentrant lock serializes every
    mode transition so ``toggle_dream()`` is atomic against them all
    (audit 2026-07-14 §7).

    ``connected`` / ``paused`` / ``last_card_type`` remain independent
    single-writer scalars with no cross-field invariant, so — per the audit's
    "don't add ceremonial locks" guidance — they are left as plain atomic
    attributes rather than wrapped.
    """
    connected: bool = False
    paused: bool = False
    last_card_type: str = ""
    mode: str = "MEMORY"   # "MEMORY" | "DREAM"
    # RLock (reentrant) so toggle_dream() can call the guarded enter/exit_dream
    # while already holding it. Excluded from equality/repr so HostState stays a
    # comparable value object.
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False)

    def is_dream(self) -> bool:
        with self._lock:
            return self.mode == "DREAM"

    def enter_dream(self) -> None:
        with self._lock:
            self.mode = "DREAM"

    def exit_dream(self) -> None:
        with self._lock:
            self.mode = "MEMORY"

    def toggle_dream(self) -> bool:
        """Atomically flip Memory<->Dream in one critical section and report
        whether we are now in Dream. Replaces the check-then-act pair
        (``is_dream()`` then ``enter_dream()``/``exit_dream()``) that, split
        across the read and the write, let two concurrent toggles interleave
        and lose one. Returns True if now in Dream Mode, False if now in
        Memory Mode."""
        with self._lock:
            if self.mode == "DREAM":
                self.mode = "MEMORY"
                return False
            self.mode = "DREAM"
            return True
