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


class FakeCloudKnowledge:
    tier, is_cloud, is_remote = "cloud", True, False

    def ask(self, q):
        from dreamlayer.ai_brain import Answer
        return Answer(text="from the cloud", tier="cloud")


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

    def test_relay_url_round_trips(self):
        b = PairingBundle(brain_url="http://mbp.local:7777", token="t",
                          relay_url="https://relay.dreamlayer.vision/abc")
        back = decode_pairing(encode_pairing(b))
        assert back.relay_url == "https://relay.dreamlayer.vision/abc"

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
# The three brain switches — phone default · Mac mini upgrade · cloud · incognito
# ---------------------------------------------------------------------------

class TestBrainModes:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_default_is_phone_brain_cloud_on(self):
        orc = self._orc()
        # the phone is the brain until a Mac mini is paired; cloud on by default
        assert orc.brain.local_only and orc.brain.cloud_opt_in
        assert not orc.incognito
        assert orc.brain_status() == {"brain": "phone", "cloud": True,
                                      "incognito": False, "glasses": False}

    def test_connect_mac_mini_upgrades_the_local_brain(self):
        orc = self._orc()
        orc.connect_mac_mini(True)
        assert not orc.brain.local_only
        assert orc.brain_status()["brain"] == "mac_mini"
        orc.connect_mac_mini(False)                 # drop it → back to phone
        assert orc.brain.local_only

    def test_cloud_is_its_own_switch(self):
        orc = self._orc()
        orc.use_cloud(False)
        assert orc.brain.local_only and not orc.brain.cloud_opt_in
        orc.use_cloud(True)
        assert orc.brain.cloud_opt_in

    def test_incognito_forces_cloud_off_and_restores(self):
        orc = self._orc()
        assert orc.brain.cloud_opt_in                # remembered preference: on
        orc.set_incognito(True)
        assert orc.incognito and not orc.brain.cloud_opt_in
        # you cannot re-enable cloud while incognito holds it down
        orc.use_cloud(True)
        assert not orc.brain.cloud_opt_in
        # leaving incognito restores the remembered preference (on)
        orc.set_incognito(False)
        assert orc.brain.cloud_opt_in

    def test_compat_shim_still_maps_modes(self):
        orc = self._orc()
        orc.set_brain_mode("home")
        assert not orc.brain.cloud_opt_in and not orc.brain.local_only
        assert orc.brain_mode == "home"
        orc.set_brain_mode("connected")
        assert orc.brain.cloud_opt_in and not orc.brain.local_only
        orc.set_brain_mode("phone", cloud=False)
        assert orc.brain.local_only and not orc.brain.cloud_opt_in

    def test_phone_with_cloud_skips_mac_mini_reaches_cloud(self):
        router = BrainRouter(cloud_opt_in=True, local_only=True)
        router.add_knowledge(FakeRemoteKnowledge())            # mac mini (skip)
        router.add_knowledge(FakeCloudKnowledge())             # cloud (allowed)
        ans = router.ask("anything")
        assert ans is not None and ans.text == "from the cloud"

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
