"""dream_mode — Ambient loop, Ghost Layer, WorldAnchorCards.

Entry point: DreamEngine

    from dreamlayer.dream_mode import DreamEngine

    engine = DreamEngine(bridge=halo_bridge, db=memory_db)
    engine.start()          # begins 2 Hz ambient loop
    engine.feed_mic(fft, amplitude)
    engine.feed_imu(pose, delta)
    engine.feed_place(signature, anchors)
    engine.stop()

Sub-systems
-----------
  MicReactor      — audio → palette shift BLE frame
  ImuReactor      — motion → geometry distortion BLE frame
  GhostLayer      — place match → WorldAnchorCard
  SceneDescriber  — camera → SynesthesiaCard every ~4s
  SpriteBridge    — sprite animation dispatcher
"""
from .engine import DreamEngine
from .ghost_layer import GhostLayer
from .imu_reactor import ImuReactor
from .mic_reactor import MicReactor
from .scene_describer import SceneDescriber
from .sprite_bridge import SpriteBridge

__all__ = [
    "DreamEngine",
    "GhostLayer",
    "ImuReactor",
    "MicReactor",
    "SceneDescriber",
    "SpriteBridge",
]
