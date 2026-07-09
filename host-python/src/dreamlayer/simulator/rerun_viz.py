"""Rerun multimodal timeline — camera, IMU, audio, text on one temporal axis for
a cinematic debug view of ghost_layer / scene_describer / imu_reactor.

ADD-alongside: new module. Lazy-imports rerun-sdk (extras group `infra`); when
absent every log_* call is a no-op, so instrumenting code paths costs nothing
without the dep.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.rerun_viz")

try:
    import rerun as rr  # type: ignore
    _HAS_RERUN = True
except ImportError:
    _HAS_RERUN = False


class Timeline:
    available = _HAS_RERUN

    def __init__(self, app_id: str = "dreamlayer", spawn: bool = False):
        self._on = False
        if _HAS_RERUN:
            try:
                rr.init(app_id, spawn=spawn)
                self._on = True
            except Exception as exc:
                log.warning("[rerun] init failed: %s; no-op", exc)

    def at(self, seconds: float) -> None:
        if self._on:
            try:
                rr.set_time_seconds("t", seconds)
            except Exception:
                pass

    def log_text(self, path: str, text: str) -> None:
        if self._on:
            try:
                rr.log(path, rr.TextLog(text))
            except Exception:
                pass

    def log_scalar(self, path: str, value: float) -> None:
        if self._on:
            try:
                rr.log(path, rr.Scalar(value))
            except Exception:
                pass

    def log_image(self, path: str, image) -> None:
        if self._on:
            try:
                rr.log(path, rr.Image(image))
            except Exception:
                pass
