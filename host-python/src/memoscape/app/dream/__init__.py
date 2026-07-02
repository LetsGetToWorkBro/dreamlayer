"""dream/ — Memoscape Dream Mode (Synesthesia Engine).

Public surface:
    DreamEngine      — orchestrates all dream sub-systems
    MicReactor       — mic FFT → palette shift commands
    ImuReactor       — IMU delta → distortion / line-field commands
    GhostLayer       — place anchors → WorldAnchorCard ghost overlays
    PlaceReactor     — place familiarity → ambient trust palette bias
    SceneDescriber   — camera frame → LFM2-VL → SynesthesiaCard text
    SpriteBridge     — 16-color PNG → TxSprite → BLE bitmap stream
"""
from .engine import DreamEngine
from .mic_reactor import MicReactor
from .imu_reactor import ImuReactor
from .ghost_layer import GhostLayer
from .place_reactor import PlaceReactor
from .scene_describer import SceneDescriber
from .sprite_bridge import SpriteBridge

__all__ = [
    "DreamEngine",
    "MicReactor",
    "ImuReactor",
    "GhostLayer",
    "PlaceReactor",
    "SceneDescriber",
    "SpriteBridge",
]
