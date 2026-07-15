"""social_lens/renderer.py — HUD card renderer for SocialLens.

Converts a SocialLensResult into a HUD render dict.
Applies display suppression rules:
  - No face detected → brief error card (2.5s)
  - Face detected, no match → grey no-match card (2.5s)
  - Match found → full contact card (5s) with confidence color

Confidence color coding:
  >= 85%  → green  (high confidence)
  70-84%  → yellow (medium confidence)
  65-69%  → orange (low confidence, at threshold)
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta
from typing import Optional

from .schema import ContactRecord, SocialLensResult
from ..hud import cards as C

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# Minimum face detection confidence to attempt matching at all
MIN_FRAME_CONFIDENCE = 0.40

AVATAR_SIZE = 32           # 32×32 @ 4bpp TxSprite
WHY_WINDOW_DAYS = 30       # "why this person matters right now" lookback


class SocialLensRenderer:
    """Converts a SocialLensResult into a HUD card dict."""

    def render(self, result: Optional[SocialLensResult]) -> Optional[dict]:
        """Return a HUD card dict, or None if nothing to display."""
        if result is None:
            return None
        # Suppress if frame quality is too poor even for a no-face card
        if result.frame_confidence < MIN_FRAME_CONFIDENCE and not result.no_face:
            return None
        return result.to_hud_card()


# ---------------------------------------------------------------------------
# Halo Cinema v1 — contact avatar sprites (docs/HALO_CINEMA_V1.md Phase 4)
# ---------------------------------------------------------------------------

class AvatarCache:
    """32×32 contact avatar sprites, generated once at contact-add time.

    Privacy contract: avatars exist ONLY for registered contacts. There is
    no path from an unmatched face or a stranger to an avatar — get() takes
    a ContactRecord, and callers for no-match results never reach it
    (enforced by build_person_context_card and tested in
    test_social_lens_avatar.py).
    """

    def __init__(self) -> None:
        self._avatars: dict[str, "Image.Image"] = {}

    def add_contact(self, contact: ContactRecord) -> Optional["Image.Image"]:
        """Generate + cache the avatar for a newly added contact."""
        if not _HAS_PIL:
            return None
        avatar = _render_avatar(contact)
        self._avatars[contact.contact_id] = avatar
        return avatar

    def get(self, contact: ContactRecord) -> Optional["Image.Image"]:
        """Return the cached avatar, generating it on first use."""
        cached = self._avatars.get(contact.contact_id)
        if cached is not None:
            return cached
        return self.add_contact(contact)

    def has(self, contact_id: str) -> bool:
        return contact_id in self._avatars

    def __len__(self) -> int:
        return len(self._avatars)


def _render_avatar(contact: ContactRecord) -> "Image.Image":
    """Deterministic geometric avatar: initial glyph inside a hue ring
    derived from the contact_id hash. Same contact → same avatar, no
    biometric content whatsoever (nothing derived from the face embedding)."""
    digest = hashlib.sha256(contact.contact_id.encode()).digest()
    hue = digest[0] / 255.0
    r, g, b = _hsv_rgb(hue, 0.55, 0.85)
    img = Image.new("RGB", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, AVATAR_SIZE - 2, AVATAR_SIZE - 2], outline=(r, g, b), width=2)
    # orbital tick from second hash byte
    ang = digest[1] / 255.0 * 2 * math.pi
    tx = AVATAR_SIZE / 2 + 12 * math.cos(ang)
    ty = AVATAR_SIZE / 2 + 12 * math.sin(ang)
    draw.ellipse([tx - 2, ty - 2, tx + 2, ty + 2], fill=(r, g, b))
    initial = (contact.name or "?")[0].upper()
    draw.text((AVATAR_SIZE // 2, AVATAR_SIZE // 2), initial,
              fill=(255, 255, 255), anchor="mm")
    return img


def _hsv_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    rgb = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))


# ---------------------------------------------------------------------------
# "Why this person matters right now"
# ---------------------------------------------------------------------------

def why_this_person(retriever, name: str,
                    now: Optional[datetime] = None) -> str:
    """Highest-scoring memory involving `name` within the last 30 days,
    reduced to one HUD line. Empty string when nothing qualifies."""
    if retriever is None or not name:
        return ""
    try:
        scored = retriever.search(name, top_k=8)
    except Exception:
        return ""
    now = now or datetime.now()
    cutoff = now - timedelta(days=WHY_WINDOW_DAYS)
    for _score, mem in scored:
        summary = (mem.get("summary") or "") if isinstance(mem, dict) else ""
        if name.lower() not in summary.lower():
            continue
        ts = mem.get("ts") or mem.get("created_at") or ""
        if ts:
            try:
                if datetime.fromisoformat(str(ts)) < cutoff:
                    continue
            except ValueError:
                pass   # unparseable timestamp: keep (better warm than silent)
        return summary[:48]
    return ""


def build_person_context_card(
    result: SocialLensResult,
    retriever=None,
    avatar_cache: Optional[AvatarCache] = None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """PersonContextCard v2 for a matched contact.

    (a) name as PRIMARY, (b) why-line from the memory layer, (c) confidence
    halo around the 32×32 avatar sprite. Returns None for no-face/no-match
    results — a non-contact NEVER produces a card with an avatar.
    """
    if result is None or result.no_face or result.no_match or result.match is None:
        return None
    m = result.match
    if not m.is_match:
        return None
    contact = m.contact

    why = why_this_person(retriever, contact.name, now=now)
    avatar = avatar_cache.get(contact) if avatar_cache is not None else None

    card = C.person_context(
        contact.name,
        headline=contact.context_line(),
        detail=contact.last_met and f"Met {contact.last_met}" or "",
    )
    card["why"] = why
    card["confidence"] = m.confidence
    card["conf_color"] = C.T.conf_color(m.confidence)
    card["has_avatar"] = avatar is not None
    card["contact_id"] = contact.contact_id
    if why:
        card["lines"] = [contact.name, why, card["detail"]]
    return card
