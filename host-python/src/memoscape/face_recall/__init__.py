"""face_recall — Personal contacts facial recognition for Brilliant Halo.

MODE 1 ONLY: matches faces against YOUR own address book.
100% on-device (phone). Zero third-party face databases. Legal everywhere.

Public API
----------
    from memoscape.face_recall import FaceRecall

    fr = FaceRecall(contact_registry=my_contacts)

    # On double-tap (IMU trigger):
    result = fr.identify(camera_frame)
    if result:
        card = result.to_hud_card()   # send to HUD renderer

Architecture
------------
  Stage 1  embedder   — 512-d MobileFaceNet embedding from camera frame
  Stage 2  index      — FAISS HNSW cosine search over personal contacts
  Stage 3  enricher   — load full contact record (name, company, notes, last-met)
  Stage 4  renderer   — FaceRecallCard HUD output

Privacy
-------
  Your embeddings never leave the device.
  No stranger lookup. No public DB. No cloud.
  Only matches people already in your personal contacts.
"""
from .analyzer import FaceRecall
from .schema import ContactRecord, FaceRecallResult, MatchResult

__all__ = ["FaceRecall", "ContactRecord", "FaceRecallResult", "MatchResult"]
