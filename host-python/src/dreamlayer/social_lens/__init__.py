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

Name-you-were-told capture
---------------------------
    # someone says "Hi, I'm Maya" — you are only *offered* the name
    card = fr.offer_introduction("hi, I'm Maya", frame=camera_frame)
    if card:                       # an IntroOfferCard — nothing saved yet
        send_to_hud(card)          # it asks; it never states a saved fact
    # a deliberate double-tap keeps her — only now is Maya your contact
    fr.confirm_introduction()

    # want the name kept the instant it's heard? opt in with
    # SocialLens(auto_keep_introductions=True) and offer_introduction()
    # returns the KeptCard directly.

  Consent-first on a self-introduction (the default): hearing only
  offers, and nothing is enrolled until you deliberately confirm — so
  only people you *chose* to keep are stored, never on hearing alone.
  Spoken (closed offline grammar of self-introductions only — never
  bystanders), in-place (writes to your local contacts, no lookup, no
  network), and veiled-silent. A kept introduction is recallable by face
  on the very next identify(), and the conversation ledger grows its
  dossier from there.

Introduced by someone else
---------------------------
    # "this is my colleague Sarah" / "meet my brother Dan" / "have you met Tom"
    card = fr.offer_introduction("this is my colleague Sarah", frame=frame)

  Third-party introductions work the same as self-introductions — the
  contact is created from the face in view — and the stated relationship
  or role ("colleague", "brother") is kept as the first dossier note. This
  is how you meet people in a professional setting or through family.

Meet someone on the spot
------------------------
    # you supply the name for the person you're looking at
    fr.meet("Sarah", frame=frame, note="runs marketing")

  Creates the contact from the face + the name you gave it (or updates an
  existing one). The voice path ("Juno, this is my colleague Sarah, she
  runs marketing") routes here.

Jot a note on the spot
----------------------
    # "Juno, remember Maya's into rock climbing"
    fr.add_note("into rock climbing", who="Maya")   # by name
    # or note whoever you just looked at:
    fr.identify(frame); fr.add_note("just got a puppy")

  The note is appended to that person's own contact and shows on the
  recall card the next time you see them (SocialLensResult.to_hud_card
  → card["note"]). Deliberate, local, veil-gated — same discipline as
  everything else here.

Privacy
-------
  Your embeddings never leave the device.
  No stranger lookup. No public DB. No cloud.
  Only matches — and only remembers — people you were introduced to
  and chose to keep. "I've met them before, remind me," never
  "identify this stranger."
"""
from .analyzer import SocialLens
from .introduction import (
    IntroductionCapture, IntroductionOffer, parse_introduction,
)
from .schema import ContactRecord, SocialLensResult, MatchResult

__all__ = [
    "SocialLens", "ContactRecord", "SocialLensResult", "MatchResult",
    "IntroductionCapture", "IntroductionOffer", "parse_introduction",
]
