"""test_pipelines_privacy.py — defense-in-depth capture gate on the pipeline
primitives (audit 2026-07-15).

The two CRITICAL raw-media-to-cloud paths (describe_poetic's raw JPEG egress
and the tier-3 raw-transcript LLM call) are gated at their PRODUCERS in the
orchestrator. These tests pin the SECOND line of defense: a DIRECT caller of the
pipeline primitives must ALSO be refused when the veil is up. They fail on revert
of the in-primitive gate — with the gate removed, the paused-veil calls proceed
to the cloud client / DB write, and the assertions below break.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

from dreamlayer.memory.db import MemoryDB
from dreamlayer.pipelines import vision
from dreamlayer.pipelines.ingest import IngestPipeline


class _Veil:
    """Minimal privacy stub mirroring the real PrivacyGate.allow_capture()."""

    def __init__(self, on: bool):
        self._on = on

    def allow_capture(self) -> bool:
        return self._on


def _fake_openai_async(response=None):
    """A stand-in for the lazily-imported ``openai`` module. AsyncOpenAI records
    whether the cloud client was ever constructed — the tell for a cloud POST."""
    fake = types.SimpleNamespace()
    fake.AsyncOpenAI = MagicMock()
    if response is not None:
        fake.AsyncOpenAI.return_value.chat.completions.create = AsyncMock(
            return_value=response
        )
    return fake


def _vlm_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = text
    return resp


# ---------------------------------------------------------------------------
# describe_poetic — raw JPEG must NOT reach the cloud VLM while veiled
# ---------------------------------------------------------------------------

class TestDescribePoeticCaptureGate:
    def test_paused_gate_no_cloud_post(self, monkeypatch):
        """FAIL-ON-REVERT: with a valid API key present, the ONLY thing between
        the raw JPEG and a cloud POST is the privacy gate. A paused gate must
        return '' and never construct the cloud client."""
        fake = _fake_openai_async(_vlm_response("light on glass"))
        monkeypatch.setitem(sys.modules, "openai", fake)

        class Cfg:
            openai_api_key = "sk-test-fake-key"

        result = asyncio.run(
            vision.describe_poetic(
                b"\xff\xd8\xff\xe0rawjpeg", "describe", config=Cfg(),
                privacy=_Veil(False),
            )
        )
        assert result == ""
        fake.AsyncOpenAI.assert_not_called()  # raw frame never left the device

    def test_open_gate_reaches_cloud(self, monkeypatch):
        """Positive control: an OPEN gate (and default) still performs the call,
        proving the deny assertion above is not vacuous."""
        fake = _fake_openai_async(_vlm_response("  soft dawn on the sill  "))
        monkeypatch.setitem(sys.modules, "openai", fake)

        class Cfg:
            openai_api_key = "sk-test-fake-key"

        result = asyncio.run(
            vision.describe_poetic(
                b"\xff\xd8\xff\xe0rawjpeg", "describe", config=Cfg(),
                privacy=_Veil(True),
            )
        )
        assert result == "soft dawn on the sill"
        fake.AsyncOpenAI.assert_called_once()

    def test_default_gate_is_permissive(self, monkeypatch):
        """Omitting the gate keeps the existing signature working (AlwaysOnGate)."""
        fake = _fake_openai_async(_vlm_response("quiet room"))
        monkeypatch.setitem(sys.modules, "openai", fake)

        class Cfg:
            openai_api_key = "sk-test-fake-key"

        result = asyncio.run(
            vision.describe_poetic(b"\xff\xd8jpeg", "describe", config=Cfg())
        )
        assert result == "quiet room"


# ---------------------------------------------------------------------------
# IngestPipeline.ingest — transcript must NOT persist while veiled
# ---------------------------------------------------------------------------

class TestIngestCaptureGate:
    def test_paused_gate_persists_nothing(self):
        """FAIL-ON-REVERT: a paused veil must no-op the write — no MemoryEvent
        and no commitment row. With the gate removed this transcript extracts a
        promise + object + place and persists them, breaking these asserts."""
        db = MemoryDB(":memory:")
        pipeline = IngestPipeline(db, use_spacy=False)

        events = pipeline.ingest(
            "I'll leave the keys on the kitchen counter for Sarah by Friday.",
            privacy=_Veil(False),
        )

        assert events == []
        assert db.memories() == []
        assert db.commitments() == []

    def test_instance_level_paused_gate_persists_nothing(self):
        """The gate can also be wired at construction time (privacy=...)."""
        db = MemoryDB(":memory:")
        pipeline = IngestPipeline(db, use_spacy=False, privacy=_Veil(False))

        events = pipeline.ingest("I left my keys on the kitchen counter.")

        assert events == []
        assert db.memories() == []

    def test_open_gate_persists(self):
        """Positive control: an open gate still extracts and persists, proving
        the deny assertions above are meaningful."""
        db = MemoryDB(":memory:")
        pipeline = IngestPipeline(db, use_spacy=False)

        events = pipeline.ingest(
            "I left my keys on the kitchen counter.", privacy=_Veil(True),
        )

        assert events, "open gate must still extract events"
        assert db.memories(), "open gate must still persist memories"

    def test_default_gate_is_permissive(self):
        """Omitting the gate keeps the existing signature working (AlwaysOnGate)."""
        db = MemoryDB(":memory:")
        pipeline = IngestPipeline(db, use_spacy=False)

        events = pipeline.ingest("I left my keys on the kitchen counter.")

        assert events
        assert db.memories()
