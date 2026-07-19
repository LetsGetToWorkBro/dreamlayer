"""test_pokemon_price.py — the Pokémon Price object-lens connector.

Pins the connector's pure logic (query build with optional number/set, card
parse, the TCGplayer→Cardmarket price pick, lookup with an injected fetch), that
the provider folds a priced card into a look-at-a-thing panel row and caches by
card, and its plugin registration + object_lens/network capability gate.
Everything here runs with no network and no API key.
"""
from __future__ import annotations

import json

from dreamlayer.plugins import PluginContext, PluginRegistry, PluginPackage, validate
from dreamlayer.plugins.pokemon_price import (
    build_query, parse_card, best_price, lookup,
    PokemonPriceProvider, pokemon_price_plugin,
)
from dreamlayer.object_lens.schema import ObjectSighting


def _sighting(kind="card", **attrs) -> ObjectSighting:
    attrs.setdefault("kind", kind)
    return ObjectSighting(label="card", confidence=0.9, attributes=attrs)


# -- pure logic ---------------------------------------------------------------

def test_build_query_encodes_name():
    url = build_query("Charizard")
    assert 'name%3A%22Charizard%22' in url          # name:"Charizard", url-encoded
    assert "pageSize=1" in url and "number" not in url


def test_build_query_pins_number_and_set_when_present():
    url = build_query("Charizard", number="4", set_id="base1")
    assert 'number%3A%224%22' in url and 'set.id%3A%22base1%22' in url


def test_best_price_prefers_holofoil_market_with_a_band():
    card = {"tcgplayer": {"prices": {
        "normal": {"market": 5.0},
        "holofoil": {"low": 240.0, "mid": 300.0, "high": 450.0, "market": 310.0},
    }}}
    p = best_price(card)
    assert p["variant"] == "holofoil" and p["market"] == 310.0 and p["sym"] == "$"
    assert p["low"] == 240.0 and p["high"] == 450.0


def test_best_price_falls_back_to_mid_then_to_cardmarket():
    # no market → use mid
    assert best_price({"tcgplayer": {"prices": {"normal": {"mid": 7.5}}}})["market"] == 7.5
    # no tcgplayer at all → Cardmarket trend, in euros
    cm = best_price({"cardmarket": {"prices": {"trendPrice": 12.0}}})
    assert cm["market"] == 12.0 and cm["sym"] == "€" and cm["source"] == "cardmarket"
    # nothing usable → {}
    assert best_price({"tcgplayer": {"prices": {"normal": {"low": None}}}}) == {}


def test_parse_card_maps_present_fields_only():
    got = parse_card({
        "name": "Charizard", "number": "4", "rarity": "Rare Holo",
        "set": {"name": "Base Set"},
        "tcgplayer": {"prices": {"holofoil": {"market": 310.0, "low": 240.0, "high": 450.0}}},
    })
    assert got["name"] == "Charizard" and got["number"] == "4"
    assert got["set"] == "Base Set" and got["rarity"] == "Rare Holo"
    assert got["price"]["market"] == 310.0 and got["price"]["variant"] == "holofoil"


def test_parse_card_omits_missing_fields():
    assert parse_card({"name": "Pikachu"}) == {"name": "Pikachu"}   # no set/number/price


def test_lookup_with_an_injected_fetch():
    body = json.dumps({"data": [{"name": "Blastoise", "number": "9",
                                 "tcgplayer": {"prices": {"holofoil": {"market": 88.0}}}}]})
    got = lookup("Blastoise", lambda url: body)
    assert got["name"] == "Blastoise" and got["number"] == "9"
    assert got["price"]["market"] == 88.0


def test_lookup_swallows_failures():
    assert lookup("x", lambda url: (_ for _ in ()).throw(OSError("no net"))) == {}
    assert lookup("x", lambda url: "not json") == {}
    assert lookup("", lambda url: '{"data":[]}') == {}          # nothing to ask


# -- the object-lens provider -------------------------------------------------

def test_provider_matches_a_card_sighting_with_a_name():
    p = PokemonPriceProvider(fetch_fn=lambda u: "{}")
    assert p.matches(_sighting(name="Charizard"))
    assert not p.matches(_sighting(kind="card"))               # a name is required
    assert not p.matches(_sighting(kind="person", name="Bob"))  # not a card kind


def test_provider_builds_a_price_row():
    body = json.dumps({"data": [{
        "name": "Charizard", "number": "4", "rarity": "Rare Holo",
        "set": {"name": "Base Set"},
        "tcgplayer": {"prices": {"holofoil": {"low": 240.0, "high": 450.0, "market": 310.0}}}}]})
    p = PokemonPriceProvider(fetch_fn=lambda u: body)
    rows = p.build(_sighting(name="Charizard", number="4"))
    assert len(rows) == 1 and rows[0].source == "pokemon-price" and rows[0].kind == "stat"
    assert "Charizard" in rows[0].label
    assert "$310 market" in rows[0].detail
    assert "$240–$450" in rows[0].detail and "Base Set" in rows[0].detail


def test_provider_caches_by_card():
    calls = {"n": 0}
    def fetch(url):
        calls["n"] += 1
        return json.dumps({"data": [{"name": "X", "tcgplayer": {"prices": {"normal": {"market": 1.0}}}}]})
    clock = {"t": 0.0}
    p = PokemonPriceProvider(fetch_fn=fetch, ttl=100.0, now_fn=lambda: clock["t"])
    p.build(_sighting(name="x"))
    p.build(_sighting(name="x"))                                # same card → one fetch
    assert calls["n"] == 1
    clock["t"] = 200.0                                          # past the TTL → refetch
    p.build(_sighting(name="x"))
    assert calls["n"] == 2


def test_provider_degrades_when_nothing_is_found():
    p = PokemonPriceProvider(fetch_fn=lambda u: '{"data":[]}')
    rows = p.build(_sighting(name="Nobody"))
    assert rows[0].kind == "info" and "no card found" in rows[0].detail


def test_provider_says_so_when_a_card_has_no_price():
    body = json.dumps({"data": [{"name": "Promo", "set": {"name": "Black Star"}}]})
    p = PokemonPriceProvider(fetch_fn=lambda u: body)
    rows = p.build(_sighting(name="Promo"))
    assert rows[0].kind == "info" and "price unavailable" in rows[0].detail
    assert "Black Star" in rows[0].detail


# -- it loads as a plugin, gated on object_lens + network ---------------------

def test_plugin_registers_and_is_capability_gated():
    # missing network → skipped
    ctx0 = PluginContext(object_registry=None, capabilities=frozenset({"object_lens"}))
    r0 = PluginRegistry(ctx0)
    r0.load(pokemon_price_plugin(fetch_fn=lambda u: "{}"))
    assert r0.result.loaded == []                              # requires network too
    # with both caps → registers an object provider
    ctx = PluginContext(capabilities=frozenset({"object_lens", "network"}))
    r = PluginRegistry(ctx)
    r.load(pokemon_price_plugin(fetch_fn=lambda u: "{}"))
    assert r.result.loaded == ["pokemon-price"]
    assert ctx.added["object_provider"]


def test_plugin_persists_and_restores_the_api_key():
    ctx = PluginContext(capabilities=frozenset({"object_lens", "network"}))
    plug = pokemon_price_plugin(fetch_fn=lambda u: "{}")
    reg = PluginRegistry(ctx)
    reg.load(plug)
    plug.set_api_key("key-xyz")
    # a fresh instance on the same context restores it on start()
    plug2 = pokemon_price_plugin(fetch_fn=lambda u: "{}")
    reg2 = PluginRegistry(ctx)
    reg2.load(plug2)
    reg2.start_all()
    assert plug2.provider.api_key == "key-xyz"


def test_packaged_passes_the_validation_gate():
    src = ("from dreamlayer.plugins.pokemon_price import pokemon_price_plugin\n"
           "def p():\n return pokemon_price_plugin()\n")
    pkg = PluginPackage.build(name="pokemon-price", version="0.1.0",
                              entry="plugin:p", requires=("object_lens", "network"),
                              source=src)
    report = validate(pkg, host_capabilities=frozenset({"object_lens", "network"}))
    assert report.ok, report.errors
