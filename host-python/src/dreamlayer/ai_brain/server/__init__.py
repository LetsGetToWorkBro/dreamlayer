"""ai_brain.server — the Brain that runs on your Mac mini.

Config + a local index over your chosen folders + a control panel + the API
the phone calls. Run it:  python -m dreamlayer.ai_brain.server
"""
from .store import BrainConfig, QueryHistory
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer
from .server import Brain, make_brain_server, authorize

__all__ = [
    "BrainConfig", "QueryHistory", "FileIndex",
    "OllamaBackend", "make_synthesizer", "vision_answer",
    "Brain", "make_brain_server", "authorize",
]
