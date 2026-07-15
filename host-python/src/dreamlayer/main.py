from .bridge.emulator_bridge import EmulatorBridge
from .orchestrator.orchestrator import Orchestrator
def build(db_path=":memory:"): return Orchestrator(EmulatorBridge(), db_path=db_path)
if __name__ == "__main__":
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default (audit 2026-07-14: configure at every entry).
    from .logging_setup import configure_logging
    configure_logging()
    o = build(); print(o.boot("../halo-lua"))
