"""test_openlibrary.py — the Open Library shop-provider connector (#199).

Mirrors test_taste_connector.py's Open Food Facts coverage: pins the
connector's pure logic (query, parse, lookup with an injected fetch), its
plugin registration + network capability gate, and the offline/failure
fallback. No real HTTP: every test fakes `fetch_fn` the same way the OFF
tests do — a plain callable the connector treats as the network seam.
"""
from __future__ import annotations

import json

from dreamlayer.plugins import PluginContext, PluginRegistry, PluginPackage, validate
from dreamlayer.plugins.openlibrary import (
    build_query, parse_book, lookup, ol_shop_fn, openlibrary_plugin,
)
from dreamlayer.orchestrator.taste import TasteLens, TasteItem


# -- the Open Library connector: pure logic -----------------------------------

def test_build_query_encodes_the_label():
    url = build_query("the hobbit")
    assert "q=the+hobbit" in url and "ratings_average" in url


def test_build_query_handles_an_isbn_the_same_way():
    # Open Library's search endpoint auto-detects an ISBN in `q=` — one query
    # shape covers both title and ISBN lookups, same as the issue asks.
    url = build_query("0140328726")
    assert "q=0140328726" in url


def test_parse_book_maps_rating_author_and_year():
    got = parse_book({"title": "Fantastic Mr Fox", "author_name": ["Roald Dahl"],
                      "first_publish_year": 1970, "edition_count": 139,
                      "ratings_average": 3.982301, "ratings_count": 113})
    assert got["rating"] == 3.98 and got["author"] == "Roald Dahl"
    assert got["first_publish_year"] == 1970 and got["editions"] == 139


def test_parse_book_omits_missing_fields():
    assert parse_book({"title": "Mystery"}) == {}            # no rating, no author
    # a rating average with zero votes is not a real score — omitted
    assert parse_book({"ratings_average": 4.5, "ratings_count": 0}) == {}


def test_lookup_with_an_injected_fetch():
    body = json.dumps({"docs": [
        {"title": "Dune", "ratings_average": 4.6, "ratings_count": 900}]})
    got = lookup("dune", lambda url: body)
    assert got["rating"] == 4.6


def test_lookup_swallows_failures_and_returns_empty():
    # offline / connection error
    assert lookup("x", lambda url: (_ for _ in ()).throw(OSError("no net"))) == {}
    # malformed body
    assert lookup("x", lambda url: "not json") == {}
    # no match
    assert lookup("x", lambda url: json.dumps({"docs": []})) == {}
    # no label to look up at all
    assert lookup("", lambda url: "{}") == {}


def test_ol_shop_fn_shifts_a_ranking():
    def fetch(url):
        # both queries resolve; Dune rates higher than the other title
        rating = 4.8 if "dune" in url else 2.0
        return json.dumps({"docs": [{"ratings_average": rating, "ratings_count": 5}]})
    lens = TasteLens(shop_fn=ol_shop_fn(fetch))
    ranked = lens.rank([TasteItem("dune"), TasteItem("some other book")])
    assert ranked[0].label == "dune"                        # better rating wins


# -- it loads as a plugin, gated on network -----------------------------------

def test_ol_plugin_registers_and_is_network_gated():
    reg: list = []
    # no network capability → skipped (the offline/undeclared-reach path)
    ctx0 = PluginContext(shop_registry=reg, capabilities=frozenset())
    r0 = PluginRegistry(ctx0)
    r0.load(openlibrary_plugin(fetch_fn=lambda u: "{}"))
    assert r0.result.loaded == []
    # with network → registers a shop provider
    ctx = PluginContext(shop_registry=reg, capabilities=frozenset({"network"}))
    r = PluginRegistry(ctx)
    r.load(openlibrary_plugin(fetch_fn=lambda u: "{}"))
    assert r.result.loaded == ["open-library"] and len(reg) == 1


def test_ol_shop_provider_returns_empty_when_offline_not_raises():
    # the shipped plugin, wired to a fetch_fn that always fails (simulating no
    # network) — the registered shop provider must come back empty, never raise.
    reg: list = []
    ctx = PluginContext(shop_registry=reg, capabilities=frozenset({"network"}))
    r = PluginRegistry(ctx)
    def offline_fetch(url):
        raise OSError("network unreachable")
    r.load(openlibrary_plugin(fetch_fn=offline_fetch))
    shop = reg[0]
    assert shop("the hobbit", {}) == {}                     # falsy, same as `or {}` expects


def test_ol_packaged_passes_the_validation_gate():
    # the shipped source imports urllib → must declare network, and does
    src = ("from dreamlayer.plugins.openlibrary import openlibrary_plugin\n"
           "def p():\n return openlibrary_plugin()\n")
    pkg = PluginPackage.build(name="open-library", version="0.1.0",
                              entry="plugin:p", requires=("network",), source=src)
    report = validate(pkg, host_capabilities=frozenset({"network"}))
    assert report.ok, report.errors
