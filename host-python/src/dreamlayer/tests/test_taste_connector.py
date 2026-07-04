"""test_taste_connector.py — the shop-provider extension point + the Open Food
Facts connector plugin.

Pins that a plugin can register a TasteLens price/review provider, that
TasteLens consults it in ranking, and the OFF connector's pure logic (query,
parse, lookup with an injected fetch) + its plugin registration and network
capability gate.
"""
from __future__ import annotations

import json

from dreamlayer.plugins import make_plugin, PluginContext, PluginRegistry, PluginPackage, validate
from dreamlayer.plugins.openfoodfacts import (
    build_query, parse_product, lookup, off_shop_fn, openfoodfacts_plugin,
    NUTRISCORE_RATING,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.taste import TasteLens, TasteItem
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- the extension point ------------------------------------------------------

def test_a_plugin_can_register_a_shop_provider():
    reg: list = []
    ctx = PluginContext(shop_registry=reg, capabilities=frozenset({"network"}))
    ctx.add_shop_provider(lambda label, attrs: {"rating": 5.0})
    assert len(reg) == 1 and reg[0]("x", {})["rating"] == 5.0
    assert ctx.added["shop_provider"]


def test_orchestrator_taste_uses_a_plugin_shop_provider():
    orc = Orchestrator(FakeBridge())
    orc.load_plugins([make_plugin(
        "rater", lambda c: c.add_shop_provider(
            lambda label, attrs: {"A": {"rating": 2.0}, "B": {"rating": 5.0}}.get(label, {})))])
    # neither item carries a rating on the shelf — the plugin supplies it
    ranked = orc.taste_lens.rank([TasteItem("A"), TasteItem("B")])
    assert ranked[0].label == "B"                      # the connector decided
    assert any("5★" in r for r in ranked[0].reasons)


def test_shop_provider_isolation():
    orc = Orchestrator(FakeBridge())
    orc.load_plugins([
        make_plugin("boom", lambda c: c.add_shop_provider(
            lambda l, a: (_ for _ in ()).throw(RuntimeError("down")))),
        make_plugin("good", lambda c: c.add_shop_provider(lambda l, a: {"rating": 4.0})),
    ])
    ranked = orc.taste_lens.rank([TasteItem("A")])       # boom is skipped, good applies
    assert any("4★" in r for r in ranked[0].reasons)


# -- the Open Food Facts connector: pure logic --------------------------------

def test_build_query_encodes_the_label():
    url = build_query("oat drink")
    assert "search_terms=oat+drink" in url and "nutriscore_grade" in url


def test_parse_product_maps_grade_and_allergens():
    got = parse_product({"nutriscore_grade": "a", "brands": "Oatly, Inc",
                         "allergens_tags": ["en:gluten", "en:soybeans"]})
    assert got["rating"] == NUTRISCORE_RATING["a"] and got["nutriscore"] == "A"
    assert got["allergens"] == ["gluten", "soybeans"] and got["brand"] == "Oatly"


def test_parse_product_omits_missing_fields():
    assert parse_product({"product_name": "Mystery"}) == {}   # no grade → no rating


def test_lookup_with_an_injected_fetch():
    body = json.dumps({"products": [
        {"product_name": "Dark Chocolate", "nutriscore_grade": "c"}]})
    got = lookup("dark chocolate", lambda url: body)
    assert got["rating"] == NUTRISCORE_RATING["c"] and got["nutriscore"] == "C"


def test_lookup_swallows_failures():
    assert lookup("x", lambda url: (_ for _ in ()).throw(OSError("no net"))) == {}
    assert lookup("x", lambda url: "not json") == {}
    assert lookup("", lambda url: "{}") == {}


def test_off_shop_fn_shifts_a_ranking():
    def fetch(url):
        # both queries resolve; A grades better than B
        grade = "a" if "apple" in url else "e"
        return json.dumps({"products": [{"nutriscore_grade": grade}]})
    lens = TasteLens(shop_fn=off_shop_fn(fetch))
    ranked = lens.rank([TasteItem("apple bar"), TasteItem("candy bar")])
    assert ranked[0].label == "apple bar"              # better Nutri-Score wins


# -- it loads as a plugin, gated on network -----------------------------------

def test_off_plugin_registers_and_is_network_gated():
    reg: list = []
    # no network capability → skipped
    ctx0 = PluginContext(shop_registry=reg, capabilities=frozenset())
    r0 = PluginRegistry(ctx0); r0.load(openfoodfacts_plugin(fetch_fn=lambda u: "{}"))
    assert r0.result.loaded == []           # requires network, absent here
    # with network → registers a shop provider
    ctx = PluginContext(shop_registry=reg, capabilities=frozenset({"network"}))
    r = PluginRegistry(ctx); r.load(openfoodfacts_plugin(fetch_fn=lambda u: "{}"))
    assert r.result.loaded == ["open-food-facts"] and len(reg) == 1


def test_off_packaged_passes_the_validation_gate():
    # the shipped source imports urllib → must declare network, and does
    src = ("from dreamlayer.plugins.openfoodfacts import openfoodfacts_plugin\n"
           "def p():\n return openfoodfacts_plugin()\n")
    pkg = PluginPackage.build(name="open-food-facts", version="0.1.0",
                              entry="plugin:p", requires=("network",), source=src)
    report = validate(pkg, host_capabilities=frozenset({"network"}))
    assert report.ok, report.errors
