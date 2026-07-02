class PrivacyGate:
    def __init__(self): self._paused = False
    @property
    def paused(self): return self._paused
    def pause(self): self._paused = True
    def resume(self): self._paused = False
    def allow_capture(self) -> bool: return not self._paused
def purge_memory(db, mid): db.purge_memory(mid)
def purge_all(db): db.purge_all()
