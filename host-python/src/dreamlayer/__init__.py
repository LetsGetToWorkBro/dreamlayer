"""DreamLayer — A memory layer for the real world.

Package layout
--------------
  dreamlayer.dream_mode       — Ambient loop, Ghost Layer, WorldAnchorCards
  dreamlayer.lucid_recall     — On-demand face/name/fact retrieval cards
  dreamlayer.reality_compiler — Intent parser → codegen → emulator → validator → deployer
  dreamlayer.truth_lens       — 9-stage multimodal deception analysis
  dreamlayer.social_lens      — Contact face-binding, labeling, per-contact baselines
  dreamlayer.orchestrator     — Central coordinator, mode management

Internal engine (memory storage & pipelines):
  memoscape/                  — memory storage, pipelines (internal)
  halo_bridge.py              — BLE hardware transport
"""
__version__ = "0.5.0"
__all__ = []
