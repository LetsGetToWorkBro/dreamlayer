"""orchestrator/recall_context.py — Shared sensor context passed to all modules."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RecallContext:
    """Live sensor snapshot passed to every DreamLayer sub-system on each tick."""
    mic_fft: Optional[list[float]] = None
    mic_amplitude: Optional[float] = None
    imu_pose: Optional[dict] = None
    imu_delta: Optional[dict] = None
    camera_frame: Optional[bytes] = None
    place_signature: Optional[str] = None
    world_anchors: list[dict] = field(default_factory=list)
    transcript: Optional[str] = None
    query_text: Optional[str] = None

    def has_camera(self) -> bool:
        return self._camera_frame is not None and len(self._camera_frame) > 0

    @property
    def _camera_frame(self):
        return self.camera_frame
