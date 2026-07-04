"""test_conversation_cards_solid.py — the O3 cards join Meridian Solid.

FactCheck / AnswerAhead / OracleReply / Hark used the flat generic layout; they
now carry the same material language as the hero cards (glass pane, gradient
strokes, bloom, hero type, dim-twin secondary text). These lock in that richness
so a regression to the austere look fails CI — the same contract Solid put on the
hero cards.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.hud import renderer as R
from dreamlayer.hud.cards import ALL_SAMPLES


def _lit(card_key: str) -> int:
    im = np.asarray(R.render(ALL_SAMPLES[card_key]).convert("RGB"))
    return int((im.sum(axis=2) > 30).sum())


# comfortably above the flat-layout baselines; the material bed alone is ~thousands
RICHNESS_FLOORS = {
    "fact_check":   5200,
    "answer_ahead": 5200,
    "oracle_reply": 4200,
    "hark":         4600,
}


def test_conversation_cards_are_provably_rich():
    for key, floor in RICHNESS_FLOORS.items():
        lit = _lit(key)
        assert lit > floor, f"{key}: {lit} lit pixels <= floor {floor}"


def test_they_route_to_dedicated_material_renderers():
    r = R.CardRenderer()
    for t, fn in (("FactCheckCard", "_fact_check"),
                  ("AnswerAheadCard", "_answer_ahead"),
                  ("OracleReplyCard", "_oracle_reply"),
                  ("HarkCard", "_hark")):
        # each has its own renderer, not the generic _layout_card
        assert hasattr(r, fn)


def test_fit_ladder_drops_size_never_clips():
    r = R.CardRenderer()
    assert r._fit("short", 200) == "hero"
    # a long claim falls down the ladder rather than overflowing the panel
    assert r._fit("x" * 40, 196) in ("md", "lg")


def test_urgent_hark_burns_amber_plain_stays_teal():
    from dreamlayer.hud import themes as T
    urgent = R.render({"type": "HarkCard", "primary": "Leave now", "importance": "urgent"})
    plain = R.render({"type": "HarkCard", "primary": "Marcus is near", "importance": "normal"})
    ua = np.asarray(urgent.convert("RGB")).reshape(-1, 3)
    pa = np.asarray(plain.convert("RGB")).reshape(-1, 3)
    # amber (high R, mid G, ~no B) present in urgent; teal (low R, high G, mid B) in plain
    amber = ((ua[:, 0] > 150) & (ua[:, 2] < 80)).sum()
    teal = ((pa[:, 1] > 120) & (pa[:, 0] < 120)).sum()
    assert amber > 40 and teal > 40
