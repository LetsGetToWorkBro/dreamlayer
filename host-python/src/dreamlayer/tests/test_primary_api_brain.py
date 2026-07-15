"""Primary API brain — plug in your own agent (Hermes, OpenClaw, any
OpenAI-compatible / Anthropic / Gemini endpoint) as the MAIN answerer.

The load-bearing property is local-vs-remote awareness, which the cloud tier
does not have: an endpoint on this machine or LAN answers freely and is NOT
cloud egress (it stays reachable while incognito, like the on-device tier); a
remote endpoint is a real boundary, so it is veil-gated (no_cloud / incognito)
and, when it fires, counted + logged BEFORE the request exactly like the cloud
tier. These tests pin every branch and the invariants a plug-in-any-API feature
must not regress.
"""
from __future__ import annotations

import dreamlayer.ai_brain.server.backends as be
from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.backends import (
    api_chat, api_test, is_local_endpoint,
)
from dreamlayer.ai_brain.server.store import BrainConfig


# --- the locality classifier (the one piece with no prior analog) -----------

class TestIsLocalEndpoint:
    def test_loopback_and_lan_are_local(self):
        for u in ("http://localhost:11434", "http://127.0.0.1:1234/v1",
                  "http://[::1]:8080", "http://192.168.1.9:11434",
                  "http://10.0.0.5", "http://172.16.4.4:9000",
                  "http://169.254.1.1", "http://hermes.local:8000"):
            assert is_local_endpoint(u) is True, u

    def test_public_hosts_are_remote(self):
        for u in ("https://api.openai.com", "https://example.com",
                  "http://8.8.8.8", "https://myagent.fly.dev"):
            assert is_local_endpoint(u) is False, u

    def test_bare_hostname_is_remote_failsafe(self):
        # a DNS search domain could resolve a bare name to a public host, so we
        # cannot claim it is local — fail safe toward egress (refute-remediation).
        for u in ("http://ai", "http://intranet:8000", "http://ollama:11434"):
            assert is_local_endpoint(u) is False, u

    def test_reserved_ranges_agree_with_the_js_mirror_remote(self):
        # ipaddress.is_private also claims TEST-NET / 0.0.0.0/8 / benchmarking,
        # which the panel's JS classifier does not — so the old code disagreed
        # with its own warning. The explicit rule treats them all as remote.
        for u in ("http://0.1.2.3", "http://192.0.2.5", "http://198.18.0.1",
                  "http://[fc00::1]", "http://[fe80::1]"):
            assert is_local_endpoint(u) is False, u

    def test_malformed_url_never_raises(self):
        # a bad IPv6 literal used to raise ValueError out of urlsplit, 500-ing
        # public()/status on every poll and surviving restart. Now → remote.
        for u in ("", "not a url", "http://[::1", "http://[fc00::/v1", "://x"):
            assert is_local_endpoint(u) is False, u


# --- the request adapter reads the api_* group, not cloud_* -----------------

class TestApiChatAdapter:
    def test_api_chat_reads_api_fields_via_injected_post(self):
        cfg = BrainConfig(api_provider="custom",
                          api_base_url="http://localhost:1234", api_model="hermes")
        seen = {}

        def fake(url, payload):
            seen.update(url=url, model=payload["model"])
            return {"text": "hi from hermes"}

        assert api_chat(cfg, "hello", http_post=fake) == "hi from hermes"
        assert seen == {"url": "http://localhost:1234", "model": "hermes"}

    def test_api_test_reports_ok_and_missing(self):
        cfg = BrainConfig(api_base_url="http://localhost:1234", api_model="m")
        assert api_test(cfg, http_post=lambda u, p: {"text": "OK"})["ok"] is True
        assert api_test(BrainConfig())["ok"] is False   # no endpoint set


# --- the primary tier through a real Brain ----------------------------------

def _brain(tmp_path, base_url, **cfg):
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token="t", model="api", api_provider="custom",
                api_base_url=base_url, api_model="hermes", **cfg).save(d)
    return Brain(d)


class TestPrimaryApiRouting:
    def setup_method(self):
        self._orig = be.api_chat

    def teardown_method(self):
        be.api_chat = self._orig

    def test_local_endpoint_answers_and_is_not_egress(self, tmp_path):
        brain = _brain(tmp_path, "http://localhost:1234")
        be.api_chat = lambda config, q, **k: "LOCAL HERMES"
        ans = brain.ask("what's my lease?")
        assert ans is not None and ans.text == "LOCAL HERMES"
        assert ans.tier == "laptop"                 # on-device class
        assert brain.config.cloud_calls == 0        # NOT egress
        assert not any(i["kind"] == "cloud-egress"
                       for i in brain.activity.recent())

    def test_local_endpoint_still_answers_while_incognito(self, tmp_path):
        # a localhost agent is on-device, so the veil does not silence it
        brain = _brain(tmp_path, "http://127.0.0.1:1234", network_mode="lan_only")
        be.api_chat = lambda config, q, **k: "STILL HERE"
        assert brain.incognito_now() is True
        ans = brain.ask("q", no_cloud=True)
        assert ans is not None and ans.text == "STILL HERE"
        assert brain.config.cloud_calls == 0

    def test_remote_endpoint_answers_and_counts_egress(self, tmp_path):
        brain = _brain(tmp_path, "https://myagent.example.com")
        be.api_chat = lambda config, q, **k: "REMOTE ANSWER"
        ans = brain.ask("q")
        assert ans is not None and ans.tier == "cloud"   # it left the device
        assert brain.config.cloud_calls == 1
        assert any(i["kind"] == "cloud-egress"
                   for i in brain.activity.recent())

    def test_remote_endpoint_silenced_by_no_cloud(self, tmp_path):
        # the wearer's incognito reaches here: a remote primary API must not
        # egress, and falls back to the on-device keyword index instead.
        brain = _brain(tmp_path, "https://myagent.example.com")
        called = {"n": 0}

        def spy(config, q, **k):
            called["n"] += 1
            return "SHOULD NOT SEND"
        be.api_chat = spy
        ans = brain.ask("q", no_cloud=True)
        assert called["n"] == 0                     # never reached the endpoint
        assert brain.config.cloud_calls == 0        # no egress
        assert ans is None                          # empty index → falls through

    def test_remote_endpoint_silenced_by_incognito(self, tmp_path):
        brain = _brain(tmp_path, "https://myagent.example.com",
                       network_mode="lan_only")
        be.api_chat = lambda config, q, **k: "SHOULD NOT SEND"
        brain.ask("q")
        assert brain.config.cloud_calls == 0

    def test_remote_egress_counted_even_when_endpoint_errors(self, tmp_path):
        # the query already left the device; a later error/empty must still be
        # on the ledger (mirrors the cloud-tier invariant).
        brain = _brain(tmp_path, "https://myagent.example.com")

        def boom(config, q, **k):
            raise RuntimeError("agent down")
        be.api_chat = boom
        ans = brain.ask("q")
        assert ans is None
        assert brain.config.cloud_calls == 1        # counted despite the failure

    def test_api_key_never_leaks_in_public(self, tmp_path):
        brain = _brain(tmp_path, "https://myagent.example.com", api_key="sk-secret")
        pub = brain.config.public()
        assert pub["api_key"] == "set"
        assert "sk-secret" not in str(pub)
        assert pub["api_configured"] is True and pub["api_is_local"] is False

    def test_malformed_api_url_does_not_brick_public_or_status(self, tmp_path):
        # Finding A (refute-remediation): a bad IPv6 literal used to raise
        # ValueError out of urlsplit inside public()/api_is_local, 500-ing every
        # status poll and surviving restart. It must degrade to remote instead.
        brain = _brain(tmp_path, "http://[::1")       # malformed, persisted
        pub = brain.config.public()                    # must not raise
        assert pub["api_is_local"] is False            # unparseable → remote
        assert pub["api_configured"] is True
        assert brain.ask("q") is None                  # ask() must not raise either

    def test_apply_config_persists_and_wires_the_api_tier(self, tmp_path):
        d = tmp_path / "cfg"
        d.mkdir()
        BrainConfig(token="t").save(d)
        brain = Brain(d)
        brain.apply_config({"model": "api", "api_provider": "custom",
                            "api_base_url": "http://localhost:9999",
                            "api_model": "myllm", "api_key": "k"})
        assert brain.config.model == "api"
        assert brain.config.api_base_url == "http://localhost:9999"
        # model=="api" leaves the index a pure keyword retriever (the fallback)
        assert brain.index.synthesizer is None
