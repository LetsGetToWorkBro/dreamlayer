from .bridge.emulator_bridge import EmulatorBridge
from .orchestrator.orchestrator import Orchestrator
def build(db_path=":memory:"): return Orchestrator(EmulatorBridge(), db_path=db_path)
if __name__ == "__main__":
    o = build(); print(o.boot("../halo-lua"))
