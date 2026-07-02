"""object_lens.integrations — reference integrations for the seam providers.

Each module shows how to fill an Object Lens seam with a real source. Wrap
the fetch callable in a PolledSource so it's safe to glance at.
"""
from .laptop_companion import (
    laptop_data_source, serve_companion, Companion,
    CONTEXT_PATH, TOKEN_HEADER,
)

__all__ = [
    "laptop_data_source", "serve_companion", "Companion",
    "CONTEXT_PATH", "TOKEN_HEADER",
]
