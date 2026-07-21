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
  dreamlayer/                  — memory storage, pipelines (internal)
  halo_bridge.py              — BLE hardware transport
"""
__version__ = "0.8.0"
__all__ = []


def _apply_offline_env_early() -> None:
    """Honour an operator/packaged-app DL_MODELS_OFFLINE at PACKAGE import — before
    any submodule imports the HuggingFace stack.

    HF/transformers/sentence-transformers read HF_HUB_OFFLINE into module-level
    constants AT IMPORT TIME, so setting the flag later (in the Brain's posture
    gate) is too late for a lib already imported (refute 2026-07-18). Doing it here,
    at the very first `import dreamlayer`, guarantees the flag is in the environment
    before those libraries are ever imported, so a wearer who starts the Brain in
    offline mode truly cannot fetch. Runtime incognito toggles are additionally
    handled per-call (e.g. local_files_only in the loaders)."""
    import os
    if os.environ.get("DL_MODELS_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on"):
        for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
                  "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
            os.environ.setdefault(k, "1")


_apply_offline_env_early()
