"""test_scenarios.py — end-to-end scenario tests.

Asserts card payloads produced by the simulator scenarios against the NEW
payload shape (post design-system rewrite, commits 6b66026 / 7d490f6).
"""
from memoscape.simulator import scenarios


def test_proactive_invoice_place():
    _, card = scenarios.proactive_recall()
    assert card is not None
    assert card["type"] == "ProactiveMemoryCard"
    assert card["primary"] == "You discussed the invoice"
    assert card["footer"] == "With Jordan"


def test_proactive_coffeeshop():
    _, card = scenarios.proactive_coffeeshop()
    assert card is not None
    assert card["type"] == "ProactiveMemoryCard"
    assert card["primary"] == "You discussed the partnership deal"
    assert card["footer"] == "With Marcus"


def test_proactive_gym():
    _, card = scenarios.proactive_gym()
    assert card is not None
    assert card["type"] == "ProactiveMemoryCard"
    assert card["footer"] == "With Sofia"


def test_proactive_unknown_place_returns_none():
    from memoscape.simulator.scenarios import new_orch
    o = new_orch()
    o.bridge.connect()
    result = o.on_place("unrecognized_place_signature")
    assert result is None
