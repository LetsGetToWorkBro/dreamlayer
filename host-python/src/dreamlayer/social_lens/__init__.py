"""social_lens — Personal contacts facial recognition for Brilliant Halo.

MODE 1 ONLY: matches faces against YOUR own address book.
100% on-device (phone). Zero third-party face databases. Legal everywhere.

Public API
----------
    from dreamlayer.social_lens import SocialLens

    fr = SocialLens(contact_registry=my_contacts)

    # On double-tap (IMU trigger):
    result = fr.identify(camera_frame)
    if result:
        card = result.to_hud_card()   # send to HUD renderer

Architecture
------------
  Stage 1  embedder   — 512-d MobileFaceNet embedding from camera frame
  Stage 2  index      — FAISS HNSW cosine search over personal contacts
  Stage 3  enricher   — load full contact record (name, company, notes, last-met)
  Stage 4  renderer   — SocialLensCard HUD output

Privacy
-------
  Your embeddings never leave the device.
  No stranger lookup. No public DB. No cloud.
  Only matches people already in your personal contacts.
"""
from .analyzer import SocialLens
from .schema import ContactRecord, SocialLensResult, MatchResult

__all__ = ["SocialLens", "ContactRecord", "SocialLensResult", "MatchResult"]
