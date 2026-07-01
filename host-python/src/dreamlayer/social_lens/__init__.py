"""social_lens — Personal contacts facial recognition for Brilliant Halo.

(Formerly: face_recall)

Public API
----------
    from dreamlayer.social_lens import SocialLens

    sl = SocialLens(contact_registry=my_contacts)
    result = sl.identify(camera_frame)
    if result.match:
        card = result.to_hud_card()

Architecture
------------
  Stage 1  embedder   — 512-d MobileFaceNet embedding
  Stage 2  index      — FAISS HNSW cosine search over personal contacts
  Stage 3  enricher   — name, company, notes, last-met from Memoscape memory
  Stage 4  renderer   — SocialLensCard HUD output
"""
from .analyzer import SocialLens
from .schema import ContactRecord, SocialLensResult, MatchResult

__all__ = ["SocialLens", "ContactRecord", "SocialLensResult", "MatchResult"]
