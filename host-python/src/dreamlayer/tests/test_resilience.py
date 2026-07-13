"""Resilience made visible: the per-seam health ledger, the latency
contract, designed failure cards, and the camera frame budget.

Silent degradation is right for the wearer and wrong for the builder —
these tests pin the rule that every degrading `except` records BEFORE it
degrades, and that a wearer who asks and gets nothing sees an honest card
instead of silence."""
import time


from dreamlayer.ai_brain.router import BrainRouter
from dreamlayer.ai_brain.schema import Answer
from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.hud import cards
from dreamlayer.orchestrator.budgets import run_with_deadline
from dreamlayer.orchestrator.frame_budget import FrameBudget
from dreamlayer.orchestrator.health import HealthLedger
from dreamlayer.orchestrator.orchestrator import Orchestrator


class _DeadBrain:
    tier = "mac"

    def ask(self, query):
        raise ConnectionError("mac asleep")

    def explain(self, frame, label, want="quick"):
        raise ConnectionError("mac asleep")


class _SlowBrain:
    tier = "cloud"
    is_cloud = True

    def ask(self, query):
        time.sleep(0.2)
        return Answer(text="late", tier="cloud")


class _GoodBrain:
    tier = "device"

    def ask(self, query):
        return Answer(text="42", tier="device")

    def explain(self, frame, label, want="quick"):
        return Answer(text=f"a {label}", tier="device")


class TestHealthLedger:
    def test_records_and_snapshots(self):
        h = HealthLedger(now_fn=lambda: 100.0)
        h.record_failure("cloud", ConnectionError("down"))
        h.record_failure("cloud", ConnectionError("still down"))
        h.record_ok("cloud")
        snap = h.snapshot()["cloud"]
        assert snap["failures"] == 2 and snap["successes"] == 1
        assert "still down" in snap["last_error"]

    def test_router_records_dead_tier_and_still_answers(self):
        h = HealthLedger()
        r = BrainRouter(health=h)
        r.add_knowledge(_DeadBrain())
        r.add_knowledge(_GoodBrain())
        ans = r.ask("meaning of life")
        assert ans is not None and ans.text == "42"       # skipped, not fatal
        assert h.failures("brain:mac") == 1               # …and RECORDED
        assert h.snapshot()["brain:device"]["successes"] == 1

    def test_orchestrator_brain_failure_recorded_and_carded(self):
        orch = Orchestrator(EmulatorBridge())
        orch.ask_brain = lambda q: (_ for _ in ()).throw(ConnectionError("x"))
        sent = []
        orch.bridge.send_card = lambda card, event="": sent.append((card, event))
        out = orch.handle_voice("hey what do I owe marcus")
        assert out["answer"] == ""                        # degrades for the wearer
        assert orch.health.failures("brain") == 1         # visible to the builder
        assert any(c.get("kind") == "brain_unreachable" for c, _ in sent)


class TestLatencyContract:
    def test_deadline_returns_default_and_records(self):
        h = HealthLedger()
        out = run_with_deadline(lambda: time.sleep(0.3) or "late", 50,
                                health=h, seam="test")
        assert out is None
        assert h.failures("deadline") == 1

    def test_fast_call_unaffected(self):
        assert run_with_deadline(lambda: "quick", 500) == "quick"

    def test_zero_disables(self):
        assert run_with_deadline(lambda: "always", 0) == "always"

    def test_router_deadline_skips_slow_cloud(self):
        h = HealthLedger()
        r = BrainRouter(cloud_opt_in=True, health=h, deadline_ms=50)
        r.add_knowledge(_SlowBrain())
        r.add_knowledge(_GoodBrain())
        ans = r.ask("anything")
        assert ans.text == "42"                           # slow tier abandoned
        assert h.failures("deadline") == 1


class TestFailureCards:
    def test_cards_exist_and_never_black(self):
        b = cards.brain_unreachable()
        assert b["type"] == "ErrorCard" and b["lines"]
        c = cards.couldnt_see()
        assert c["type"] == "LowConfidenceCard" and c["lines"]

    @staticmethod
    def _flat_frame():
        import numpy as np
        return np.zeros((16, 16), dtype=np.float32)   # no contrast: unrecognisable

    def test_deliberate_look_at_nothing_gets_honest_card(self):
        orch = Orchestrator(EmulatorBridge())
        sent = []
        orch.bridge.send_card = lambda card, event="": sent.append((card, event))
        panel = orch.look_at_object(frame=self._flat_frame())
        assert panel is None
        assert any(e == "couldnt_see" for _, e in sent)

    def test_veiled_look_stays_silent(self):
        orch = Orchestrator(EmulatorBridge())
        orch.privacy.pause()
        sent = []
        orch.bridge.send_card = lambda card, event="": sent.append((card, event))
        orch.look_at_object(frame=self._flat_frame())
        assert not any(e == "couldnt_see" for _, e in sent)


class TestFrameBudget:
    def test_ambient_duty_cycle(self):
        clock = {"t": 0.0}
        fb = FrameBudget(ambient_interval_ms=4000, now_fn=lambda: clock["t"])
        assert fb.allow_ambient()
        clock["t"] += 1.0
        assert not fb.allow_ambient()          # inside the interval: dropped
        clock["t"] += 3.5
        assert fb.allow_ambient()
        assert fb.stats()["ambient_dropped"] == 1

    def test_staleness(self):
        clock = {"t": 10.0}
        fb = FrameBudget(stale_ms=1500, now_fn=lambda: clock["t"])
        assert fb.fresh(frame_ts=9.0)          # 1.0 s old
        assert not fb.fresh(frame_ts=8.0)      # 2.0 s old — the past

    def test_dream_camera_feed_is_duty_cycled(self):
        orch = Orchestrator(EmulatorBridge())
        orch.enter_dream()
        fed = []
        orch.dream.feed_camera = lambda jpeg: fed.append(jpeg)
        for ms in (0, 100, 200):               # 3 frames inside one interval
            orch.on_scene_frame({"camera_jpeg": b"x"}, now_ms=ms)
        assert len(fed) == 1

    def test_health_snapshot_shape(self):
        orch = Orchestrator(EmulatorBridge())
        snap = orch.health_snapshot()
        assert set(snap) == {"seams", "maturity", "frames", "plugins"}
