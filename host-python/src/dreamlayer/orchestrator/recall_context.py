"""recall_context.py — unified context object passed through the recall pipeline.

All fields beyond the original listen_count / card_count are Optional so
existing callers (orchestrator, tests) need zero changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecallContext:
    # --- original fields ---
    listen_count: int = 0
    card_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    # --- dream / generative engine inputs ---
    camera_frame: Optional[bytes] = None        # JPEG thumbnail from glasses
    mic_fft: Optional[list[float]] = None       # 32-band magnitude array (0.0-1.0)
    mic_amplitude: Optional[float] = None       # RMS amplitude (0.0-1.0)
    imu_pose: Optional[dict] = None             # {"pitch": float, "yaw": float, "roll": float}
    imu_delta: Optional[dict] = None            # angular velocity since last tick
    world_anchors: Optional[list[dict]] = None  # matched memory anchors at current place
    place_signature: Optional[str] = None       # current location hash
    speaker: Optional[str] = None               # detected speaker label if known

    def has_camera(self) -> bool:
        return self.camera_frame is not None and len(self.camera_frame) > 0

    def has_imu(self) -> bool:
        return self.imu_pose is not None

    def has_mic(self) -> bool:
        return self.mic_fft is not None or self.mic_amplitude is not None
