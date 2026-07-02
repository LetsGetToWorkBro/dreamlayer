"""ai_brain — tiered intelligence for DreamLayer (see docs/AI_BRAIN.md).

On-device → your Mac mini "brain" → opt-in cloud, behind two small
interfaces (VisionBrain / KnowledgeBrain) and a router that prefers the
lowest tier and never crosses to the cloud silently. Phase 1 ships the
router + deterministic mocks so the whole pipeline runs with no model.
"""
from .schema import Answer
from .brains import (
    VisionBrain, KnowledgeBrain, MockVisionBrain, MockKnowledgeBrain,
)
from .router import BrainRouter

__all__ = [
    "Answer", "VisionBrain", "KnowledgeBrain",
    "MockVisionBrain", "MockKnowledgeBrain", "BrainRouter",
]
