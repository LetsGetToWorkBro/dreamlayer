"""test_ingest_llm.py — tests for the GPT-4o-mini tier-3 extraction path.

All tests mock openai via sys.modules injection so the real openai package
is NOT required to be installed (it is an optional lazy dependency).
"""
from __future__ import annotations
import json
import sys
import types
from unittest.mock import MagicMock, patch
import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.pipelines.ingest import IngestPipeline, MemoryEvent
from dreamlayer.pipelines.llm_client import LLMClient
from dreamlayer.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_response(events: list[dict]) -> MagicMock:
    """Build a mock openai ChatCompletion response."""
    content = json.dumps({"events": events})
    choice  = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _fake_openai_module(mock_resp=None, side_effect=None):
    """Return a SimpleNamespace that looks like the openai module to LLMClient.

    LLMClient does `import openai` then `openai.OpenAI(...)` inside
    _get_client().  Injecting this into sys.modules["openai"] before that
    call is made lets the lazy import resolve to our fake without the real
    package being installed.
    """
    fake = types.SimpleNamespace()
    fake.OpenAI = MagicMock()
    instance = fake.OpenAI.return_value
    if side_effect is not None:
        instance.chat.completions.create.side_effect = side_effect
    elif mock_resp is not None:
        instance.chat.completions.create.return_value = mock_resp
    return fake


@pytest.fixture
def cfg():
    c = Config()
    c.openai_api_key = "sk-test-fake-key"
    c.llm_confidence_threshold = 0.60
    c.llm_word_threshold = 40
    return c


@pytest.fixture
def db():
    return MemoryDB(":memory:")


# ---------------------------------------------------------------------------
# LLMClient unit tests
# ---------------------------------------------------------------------------

class TestLLMClient:
    def _fresh_client(self, cfg) -> LLMClient:
        """Return a LLMClient with the lazy openai cache cleared."""
        client = LLMClient(cfg)
        client._client = None  # ensure _get_client() runs fresh each test
        return client

    def test_returns_memory_events(self, cfg):
        client = self._fresh_client(cfg)
        mock_resp = _make_openai_response([{
            "kind": "object",
            "summary": "Passport is in the safe",
            "confidence": 0.95,
            "meta": {"object": "passport", "place": "safe"},
        }])
        fake_oa = _fake_openai_module(mock_resp=mock_resp)
        with patch.dict(sys.modules, {"openai": fake_oa}):
            events = client.extract("My passport is in the safe.")
        assert len(events) == 1
        assert events[0].kind == "object"
        assert events[0].source == "llm"
        assert events[0].confidence == 0.95

    def test_invalid_kind_skipped(self, cfg):
        client = self._fresh_client(cfg)
        mock_resp = _make_openai_response([{
            "kind": "nonsense",
            "summary": "Whatever",
            "confidence": 0.8,
            "meta": {},
        }])
        fake_oa = _fake_openai_module(mock_resp=mock_resp)
        with patch.dict(sys.modules, {"openai": fake_oa}):
            events = client.extract("Whatever.")
        assert events == []

    def test_api_error_returns_empty(self, cfg):
        client = self._fresh_client(cfg)
        fake_oa = _fake_openai_module(side_effect=RuntimeError("timeout"))
        with patch.dict(sys.modules, {"openai": fake_oa}):
            events = client.extract("Some transcript.")
        assert events == []

    def test_missing_api_key_returns_empty(self):
        cfg = Config()
        cfg.openai_api_key = ""
        client = self._fresh_client(cfg)
        with patch.dict(sys.modules, {}, clear=False):
            # Don't inject openai — _get_client sees no key and returns None
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                events = client.extract("I left my glasses on the table.")
        assert events == []

    def test_context_location_sent_in_user_message(self, cfg):
        """Verify location hint is included in the user message."""
        client = self._fresh_client(cfg)
        captured = {}
        mock_resp = _make_openai_response([])

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return mock_resp

        fake_oa = _fake_openai_module()
        fake_oa.OpenAI.return_value.chat.completions.create.side_effect = fake_create
        with patch.dict(sys.modules, {"openai": fake_oa}):
            client.extract("Glasses on the table.", context={"location": "bedroom"})

        assert "messages" in captured, "create() was never called"
        user_msg = captured["messages"][1]["content"]
        assert "bedroom" in user_msg


# ---------------------------------------------------------------------------
# IngestPipeline tier-3 trigger logic
# ---------------------------------------------------------------------------

class TestTier3Trigger:
    def _pipeline_with_mock_llm(self, db, cfg, llm_events: list[dict]) -> IngestPipeline:
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.extract.return_value = [
            MemoryEvent(
                kind=e["kind"], summary=e["summary"],
                confidence=e.get("confidence", 0.80), source="llm",
                meta=e.get("meta", {}),
            )
            for e in llm_events
        ]
        return IngestPipeline(
            db=db, use_spacy=False, llm=mock_llm,
            llm_confidence_threshold=cfg.llm_confidence_threshold,
            llm_word_threshold=cfg.llm_word_threshold,
        )

    def test_llm_triggered_on_long_transcript(self, db, cfg):
        long_tx = ("word " * 45).strip()  # 45 words > threshold of 40
        pipeline = self._pipeline_with_mock_llm(db, cfg, [{
            "kind": "task", "summary": "Task: do something", "confidence": 0.80
        }])
        pipeline.ingest(long_tx)
        pipeline.llm.extract.assert_called_once()

    def test_llm_not_triggered_on_short_high_confidence(self, db, cfg):
        pipeline = self._pipeline_with_mock_llm(db, cfg, [])
        pipeline.ingest("I left my keys on the kitchen counter.")
        pipeline.llm.extract.assert_not_called()

    def test_cloud_off_never_calls_the_tier3_llm(self, db, cfg):
        """Audit 2026-07-14 CRITICAL: tier-3 ships the raw transcript to the
        cloud, so it must be gated by the Cloud switch, not merely by an API
        key. With cloud_ok()->False the LLM is never called even for a long
        transcript that would otherwise trigger it."""
        pipeline = self._pipeline_with_mock_llm(db, cfg, [{
            "kind": "task", "summary": "Task: do something", "confidence": 0.80
        }])
        pipeline.cloud_ok = lambda: False
        pipeline.ingest(("word " * 45).strip())
        pipeline.llm.extract.assert_not_called()
        # flip the switch on → tier-3 fires as before
        pipeline.cloud_ok = lambda: True
        pipeline.ingest(("word " * 45).strip())
        pipeline.llm.extract.assert_called_once()

    def test_llm_triggered_when_zero_tier1_events(self, db, cfg):
        """Tier-3 fires when tier-1 produces nothing on a non-trivial transcript.

        The sentence is all-lowercase with no location prepositions, no
        promise cues, no task cues, and no capitalised tokens, so tier-1
        returns an empty list and _should_use_llm() returns True.
        """
        pipeline = self._pipeline_with_mock_llm(db, cfg, [{
            "kind": "task", "summary": "Task: call dentist", "confidence": 0.80
        }])
        # All lowercase, no caps, no tier-1 cues — guaranteed zero tier-1 events
        pipeline.ingest("maybe later we should revisit the dentist appointment")
        pipeline.llm.extract.assert_called_once()

    def test_llm_events_merged_and_deduped(self, db, cfg):
        llm_event = {
            "kind": "object",
            "summary": "my keys \u2192 kitchen counter",
            "confidence": 0.95,
        }
        pipeline = self._pipeline_with_mock_llm(db, cfg, [llm_event])
        events = pipeline.ingest("I left my keys on the kitchen counter.")
        obj_summaries = [e.summary for e in events if e.kind == "object"]
        assert len(obj_summaries) == len(set(obj_summaries))

    def test_all_events_have_db_id(self, db, cfg):
        pipeline = self._pipeline_with_mock_llm(db, cfg, [{
            "kind": "person",
            "summary": "Person: Jordan",
            "confidence": 0.90,
            "meta": {"person": "Jordan"},
        }])
        events = pipeline.ingest(
            "Met Jordan at the conference. I'll follow up with her by Monday."
        )
        assert events
        assert all(e.db_id > 0 for e in events)

    def test_llm_failure_falls_back_to_tier1(self, db, cfg):
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.extract.return_value = []
        pipeline = IngestPipeline(
            db=db, use_spacy=False, llm=mock_llm,
            llm_confidence_threshold=0.99,  # force trigger
            llm_word_threshold=0,
        )
        events = pipeline.ingest("I left my keys on the counter.")
        assert any(e.kind == "object" for e in events)
        assert all(e.db_id > 0 for e in events)


# ---------------------------------------------------------------------------
# with_llm constructor
# ---------------------------------------------------------------------------

class TestWithLLMConstructor:
    def test_constructs_pipeline_with_llm(self, db, cfg):
        pipeline = IngestPipeline.with_llm(db, cfg, use_spacy=False)
        assert pipeline.llm is not None
        assert pipeline.llm_confidence_threshold == cfg.llm_confidence_threshold
        assert pipeline.llm_word_threshold == cfg.llm_word_threshold

    def test_config_values_propagated(self, db):
        cfg = Config()
        cfg.openai_api_key = "sk-test"
        cfg.llm_confidence_threshold = 0.50
        cfg.llm_word_threshold = 25
        pipeline = IngestPipeline.with_llm(db, cfg, use_spacy=False)
        assert pipeline.llm_confidence_threshold == 0.50
        assert pipeline.llm_word_threshold == 25
