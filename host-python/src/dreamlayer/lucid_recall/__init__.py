"""lucid_recall — On-demand face/name/fact retrieval cards.

Lucid Recall is the explicit query layer of DreamLayer.
The user asks a question (voice or gesture) and receives
a high-confidence answer card on the Halo HUD.

Routes queries to the appropriate lens:
  - Face/name queries  → SocialLens
  - Fact queries       → MemoryIndex
  - Person context     → ContactEnricher + MemoryIndex

Public API
----------
    from dreamlayer.lucid_recall import LucidRecall

    lr = LucidRecall(social_lens=sl, memory_index=mi)
    result = lr.query("Who is this?", camera_frame=frame)
    card = result.to_hud_card()
"""
from .router import LucidRecall
from .schema import LucidRecallResult, QueryType
from .index_adapter import RetrieverRecallIndex

__all__ = ["LucidRecall", "LucidRecallResult", "QueryType",
           "RetrieverRecallIndex"]
