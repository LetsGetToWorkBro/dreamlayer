"""test_pairing_and_brainmode.py — one-code pairing + phone-as-brain mode."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from dreamlayer.pairing import (
    PairingBundle, encode_pairing, decode_pairing, connect_all,
)
from dreamlayer.ai_brain import BrainRouter, MockKnowledgeBrain
from dreamlayer.ai_brain.server import BrainConfig, Brain, make_brain_server


class FakeRemoteKnowledge:
    tier, is_cloud, is_remote = "laptop", False, True

    def ask(self, q):
        from dreamlayer.ai_brain import Answer
        return Answer(text="from the mac mini", tier="laptop")


# ---------------------------------------------------------------------------
# Pairing code
# ---------------------------------------------------------------------------

class TestPairingCode:
    def test_round_trip(self):
        b = PairingBundle(brain_url="http://mbp.local:7777", token="rune-birch",
                          glasses_id="HALO-9F2A")
        code = encode_pairing(b)
        assert code.startswith("dreamlayer:")
        back = decode_pairing(code)
        assert back.brain_url == b.brain_url and back.token == b.token
        assert back.glasses_id == "HALO-9F2A"

    def test_decode_tolerates_bare_base64(self):
        code = encode_pairing(PairingBundle(brain_url="http://x", token="t"))
        bare = code.split(":", 1)[1]
        assert decode_pairing(bare).brain_url == "http://x"

    def test_connect_all_wires_brain_and_glasses(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        orc = Orchestrator(FakeBridge())
        bundle = PairingBundle(brain_url="http://mbp.local:7777", token="t",
                               glasses_id="HALO-1")
        status = connect_all(orc, bundle)
        assert status["brain"] and status["glasses"]
        assert orc.glasses_id == "HALO-1"
        assert orc.brain.has_vision()          # remote tier registered


# ---------------------------------------------------------------------------
# Brain modes — connected / home / phone
# ---------------------------------------------------------------------------

class TestBrainModes:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_default_connected(self):
        orc = self._orc()
        assert orc.brain_mode == "connected"
        assert orc.brain.cloud_opt_in and not orc.brain.local_only

    def test_home_drops_cloud_keeps_mac_mini(self):
        orc = self._orc()
        orc.set_brain_mode("home")
        assert not orc.brain.cloud_opt_in and not orc.brain.local_only

    def test_phone_is_the_brain_on_device_only(self):
        orc = self._orc()
        orc.set_brain_mode("phone")
        assert orc.brain.local_only and not orc.brain.cloud_opt_in

    def test_phone_mode_skips_the_remote_tier(self):
        router = BrainRouter(cloud_opt_in=True)
        router.add_knowledge(FakeRemoteKnowledge())                 # mac mini
        router.add_knowledge(MockKnowledgeBrain({"doc": "on-device answer here"}))
        # connected: the remote (first, allowed) answers
        assert router.ask("answer").text == "from the mac mini"
        # phone-only: the remote is skipped, the on-device brain answers
        router.set_local_only(True)
        ans = router.ask("answer")
        assert ans is not None and "on-device answer" in ans.text


# ---------------------------------------------------------------------------
# /pair endpoint (localhost only) hands out a code the phone decodes
# ---------------------------------------------------------------------------

class TestPairEndpoint:
    def test_pair_code_from_localhost(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        brain = Brain(cfg)
        server = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            req = urllib.request.Request(url + "/dreamlayer/pair",
                                         headers={"X-DreamLayer-Token": "tok"})
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            data = json.loads(op.open(req, timeout=5).read())
            bundle = decode_pairing(data["code"])
            assert bundle.token == "tok" and bundle.brain_url.startswith("http")
        finally:
            server.shutdown(); server.server_close()
