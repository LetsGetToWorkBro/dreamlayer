"""test_taste.py — TasteLens: the real-world choice juno.

Pins the pure ranking (dietary veto beats everything, budget gate, rating +
cheaper-is-better, stable ties), the pluggable shop_fn enrichment, the honest
unavailable state, the reply parser, the veil gate, the card, and the
end-to-end path where the arbiter routes a shelf look to TasteLens.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.taste import TasteLens, TasteItem
from dreamlayer.orchestrator.orchestrator import Orchestrator, _parse_taste_reply
from dreamlayer.orchestrator.glance import classify_coarse, GlanceArbiter, GlanceReading
from dreamlayer.object_lens.label import DietaryProfile
from dreamlayer.hud import cards
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def frame():
    return np.zeros((8, 8), dtype=np.float32)


# -- the pure ranking ---------------------------------------------------------

def test_dietary_veto_sinks_an_item_however_good():
    prof = DietaryProfile(avoid={"dairy"})
    items = [TasteItem("Milk Chocolate", text="milk, cocoa", rating=5.0, price=2.0),
             TasteItem("Dark Chocolate", text="cocoa, sugar", rating=4.0, price=3.0)]
    ranked = TasteLens().rank(items, profile=prof)
    assert ranked[0].label == "Dark Chocolate" and ranked[0].ok
    assert ranked[-1].label == "Milk Chocolate" and not ranked[-1].ok
    assert any("avoid: dairy" in r for r in ranked[-1].reasons)


def test_rating_and_cheaper_win_among_eligible():
    items = [TasteItem("A", rating=4.0, price=5.0),
             TasteItem("B", rating=4.0, price=2.0),   # same rating, cheaper
             TasteItem("C", rating=3.0, price=2.0)]
    ranked = TasteLens().rank(items)
    assert ranked[0].label == "B"                     # cheaper breaks the rating tie
    assert [r.label for r in ranked] == ["B", "A", "C"]


def test_budget_gates_but_does_not_veto():
    items = [TasteItem("Cheap", rating=3.0, price=4.0),
             TasteItem("Lux", rating=5.0, price=40.0)]
    ranked = TasteLens().rank(items, budget=10.0)
    assert ranked[0].label == "Cheap" and ranked[0].ok
    assert ranked[-1].label == "Lux" and not ranked[-1].ok
    assert any("over $10" in r for r in ranked[-1].reasons)


def test_ties_are_stable_by_label():
    items = [TasteItem("Zebra", rating=4.0), TasteItem("Apple", rating=4.0)]
    ranked = TasteLens().rank(items)
    assert [r.label for r in ranked] == ["Apple", "Zebra"]


# -- the pluggable shop_fn (a price/review plugin) ---------------------------

def test_shop_fn_fills_missing_rating_and_shifts_order():
    def shop(label, attrs):
        return {"A": {"rating": 2.0}, "B": {"rating": 5.0}}.get(label, {})
    items = [TasteItem("A"), TasteItem("B")]            # no ratings on the shelf
    ranked = TasteLens(shop_fn=shop).rank(items)
    assert ranked[0].label == "B"                       # the plugin's rating decided
    assert any("5★" in r for r in ranked[0].reasons)


def test_shop_fn_failure_is_swallowed():
    def shop(label, attrs): raise RuntimeError("cloud down")
    ranked = TasteLens(shop_fn=shop).rank([TasteItem("A", rating=4.0)])
    assert ranked[0].label == "A"                       # ranked on shelf data alone


# -- the read seam + unavailable ---------------------------------------------

def test_look_is_unavailable_when_nothing_reads():
    r = TasteLens(read_fn=lambda f: []).look(frame())
    assert r.unavailable and r.winner is None


def test_look_ranks_what_it_reads():
    lens = TasteLens(read_fn=lambda f: [TasteItem("A", rating=3.0),
                                        TasteItem("B", rating=5.0)])
    r = lens.look(frame())
    assert not r.unavailable and r.winner.label == "B"


# -- the reply parser ---------------------------------------------------------

def test_parse_taste_reply():
    items = _parse_taste_reply(
        "Oat Milk | oats, water | $3.20 | 4.6\n"
        "- Whole Milk | milk | 2.50 | 4.0\n"
        "? | | |")
    assert [i.label for i in items] == ["Oat Milk", "Whole Milk"]
    assert items[0].price == 3.20 and items[0].rating == 4.6
    assert items[1].price == 2.50


# -- the card -----------------------------------------------------------------

def test_taste_card_shape():
    lens = TasteLens(read_fn=lambda f: [
        TasteItem("Oat Milk", rating=4.6, price=3.2),
        TasteItem("Whole Milk", text="milk", rating=4.0, price=2.5)])
    ranking = lens.look(frame())
    card = cards.taste(ranking)
    assert card["type"] == "TasteCard" and card["primary"] == "Oat Milk"
    assert not card["unavailable"] and card["items"]


def test_taste_card_unavailable_state():
    card = cards.taste(TasteLens(read_fn=lambda f: []).look(frame()))
    assert card["unavailable"] and card["primary"] == ""


# -- routing: a shelf look goes to TasteLens ---------------------------------

def test_a_shelf_scene_routes_to_taste():
    d = GlanceArbiter().arbitrate(classify_coarse({"items": 4}))
    assert d.kind == "fire" and d.winner.lens == "taste"


# -- end to end through the orchestrator -------------------------------------

def test_orchestrator_taste_sends_a_card_and_ranks():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.dietary.avoid.add("dairy")

    class A:
        # "Oat Milk" would false-positive the substring dietary matcher on
        # "milk"; "Almond Drink" is the honest dairy-free label.
        text = ("Almond Drink | almonds, water | $3.20 | 4.6\n"
                "Whole Milk | milk, cream | 2.50 | 4.8")
        tier = "cloud"
        def is_empty(self): return False
    orc.brain.explain = lambda f, p, want="quick": A()
    ranking = orc.taste(frame())
    # whole milk rates higher but is vetoed for dairy → the almond drink wins
    assert ranking.winner.label == "Almond Drink"
    tcards = [c for c in br.raw if c.get("t") == "card" and c.get("type") == "TasteCard"]
    assert tcards


def test_orchestrator_taste_is_veil_gated():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.privacy.pause()
    ranking = orc.taste(frame())
    assert ranking.unavailable          # veil → nothing read → honest card
