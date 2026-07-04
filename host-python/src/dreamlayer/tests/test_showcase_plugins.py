"""test_showcase_plugins.py — the four new store plugins.

Each demonstrates a different plugin hook: Currency (object-lens + network),
HUD Reactions (cards + mesh), Filler-Word Counter (perception + cards), Air
Drums (midi). Pins their logic and that every one passes the safety gate.
"""
from __future__ import annotations

from dreamlayer.plugins import PluginPackage, PluginManifest, sha256_of, validate

ALL_CAPS = frozenset({"object_lens", "glance", "perception", "cards", "ring",
                      "vision", "mesh", "midi", "network", "shop"})


def _package(name, module, factory, requires):
    source = (f"from dreamlayer.plugins.{module} import {factory}\n\n"
              f"def plugin():\n    return {factory}()\n")
    m = PluginManifest(name=name, version="0.1.0", entry="plugin:plugin",
                       author="dreamlayer", requires=requires,
                       checksum=sha256_of(source))
    return PluginPackage(manifest=m, source=source)


SPECS = [
    ("currency-converter", "currency", "currency_plugin", ("object_lens", "network")),
    ("hud-reactions", "reactions", "reactions_plugin", ("cards", "mesh")),
    ("filler-word-counter", "filler", "filler_plugin", ("perception", "cards")),
    ("air-drums", "air_drums", "air_drums_plugin", ("midi",)),
]


def test_all_showcase_plugins_pass_the_gate():
    for name, module, factory, requires in SPECS:
        pkg = _package(name, module, factory, requires)
        report = validate(pkg, host_capabilities=ALL_CAPS)
        assert report.ok, (name, report.errors)
        assert pkg.checksum_ok()


# -- Currency Converter -------------------------------------------------------

def test_currency_converts_a_foreign_price():
    from dreamlayer.plugins.currency import CurrencyProvider, convert, format_money
    from dreamlayer.object_lens.schema import ObjectSighting
    assert convert(10, 1.1) == 11.0
    assert format_money(13.63, "USD") == "$13.63"
    prov = CurrencyProvider(home="USD",
                            rates_fetch=lambda b, q: 1.09 if b == "EUR" else None)
    s = ObjectSighting(label="price", confidence=0.9,
                       attributes={"amount": 12.5, "currency": "EUR"})
    assert prov.matches(s)
    row = prov.build(s)[0]
    assert row.label == "$13.63" and "EUR" in row.detail
    # your home currency isn't "foreign" — no row
    assert not prov.matches(ObjectSighting("price", 0.9,
                            attributes={"amount": 5, "currency": "USD"}))


# -- HUD Reactions ------------------------------------------------------------

def test_reactions_gossip_only_a_symbol():
    from dreamlayer.plugins.reactions import reaction_body, read_reaction, Reactions

    class FakeMesh:
        def __init__(self): self.sent = []
        def emit(self, kind, body): self.sent.append((kind, body)); return True
        def receive(self, wire): return object()   # authenticated peer

    class Ctx:
        def __init__(self, mesh): self.mesh = mesh; self.config = {}

    assert reaction_body("fire") == {"r": "fire"}
    assert read_reaction({"r": "clap"}) == "👏"
    mesh = FakeMesh()
    r = Reactions(Ctx(mesh))
    card = r.throw("fire")
    assert card["emoji"] == "🔥" and mesh.sent == [("reaction", {"r": "fire"})]
    peer = r.received({"body": {"r": "love"}})
    assert peer and peer["emoji"] == "❤️" and peer["mine"] is False


# -- Filler-Word Counter ------------------------------------------------------

def test_filler_counter_tallies_and_defers():
    from dreamlayer.plugins.filler import count_fillers, FillerCounter
    assert count_fillers("So basically I um think") == 2
    fc = FillerCounter()
    assert fc.listen("like you know it's fine").keyword == "filler"
    assert fc.listen("a clean sentence") is None      # nothing to flag
    assert fc.total == 2
    assert fc.perceive(object()) is None              # not a vision tier


# -- Air Drums ----------------------------------------------------------------

def test_air_drums_maps_zones_to_gm_drums():
    from dreamlayer.plugins.air_drums import AirDrums, hit_for, DRUM_CHANNEL
    assert hit_for("nowhere") is None
    kick = hit_for("down", 1.0)
    assert kick.note == 36 and kick.velocity == 127 and kick.channel == DRUM_CHANNEL
    status, note, vel = kick.as_midi()
    assert status == (0x90 | DRUM_CHANNEL) and note == 36
    sent = []
    ad = AirDrums(midi_out=lambda m: sent.append(m))
    hit = ad.strike("right", 0.5)
    assert hit.label == "hihat" and sent == [hit.as_midi()]
