"""test_plugin_official_and_v2.py — the first-party catalogue is an *official*
DreamLayer-team publisher on API v2, priced free through a reserved seam; the
four migrated plugins persist their settings; and the static-scan from-import
bypass is closed.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from dreamlayer.plugins import (
    PluginPackage, PluginManifest, PluginContext, PluginRegistry, StoreEntry,
    validate, scan_source, sha256_of,
)

REPO = Path(__file__).resolve().parents[4]
ALL_CAPS = frozenset({"object_lens", "glance", "perception", "cards", "ring",
                      "vision", "mesh", "midi", "network", "shop"})


class FakeDB:
    """Minimal settings-backed db (get_setting/set_setting), like MemoryDB."""
    def __init__(self):
        self.kv: dict = {}

    def get_setting(self, key):
        return self.kv.get(key)

    def set_setting(self, key, value):
        self.kv[key] = value


def _run(plugin, db=None, caps=ALL_CAPS, shop_registry=None):
    """Load + start a plugin exactly as the host does (scoped register/start)."""
    ctx = PluginContext(capabilities=caps, config={}, db=db,
                        shop_registry=shop_registry)
    reg = PluginRegistry(ctx)
    reg.load_all([plugin])
    reg.start_all()
    return ctx, reg


def _packages():
    return sorted(glob.glob(str(REPO / "registry" / "packages" / "*.json")))


# -- the shipped catalogue: official, DreamLayer Team, API v2, free, valid ----

class TestOfficialCatalogue:
    def test_every_package_is_official_v2_free_and_valid(self):
        for f in _packages():
            d = json.load(open(f, encoding="utf-8"))
            m = d["manifest"]
            assert m["author"] == "DreamLayer Team", f
            assert m["official"] is True, f
            assert m["api"] == "2", f
            assert m["pricing"] == {"model": "free"}, f
            assert sha256_of(d["source"]) == m["checksum"], f
            pkg = PluginPackage(manifest=PluginManifest.from_dict(m),
                                source=d["source"])
            report = validate(pkg, host_capabilities=ALL_CAPS)
            assert report.ok, (f, report.errors)

    def test_index_agrees_with_manifests(self):
        idx = json.load(open(REPO / "registry" / "index.json", encoding="utf-8"))
        by = {p["name"]: p for p in idx["plugins"]}
        assert len(by) == len(_packages())
        for f in _packages():
            m = json.load(open(f, encoding="utf-8"))["manifest"]
            e = by[m["name"]]
            assert e["author"] == "DreamLayer Team" and e["official"] is True
            assert e["api"] == "2" and e["pricing"] == {"model": "free"}
            assert e["checksum"] == m["checksum"]
            assert e["description"] == m["description"]      # no drift
            assert e["homepage"] == m["homepage"]            # no drift

    def test_store_entry_and_manifest_round_trip_the_new_fields(self):
        e = StoreEntry.from_dict({"name": "x", "version": "1.0.0",
                                  "official": True, "api": "2",
                                  "pricing": {"model": "free"}})
        assert e.official and e.api == "2" and e.pricing == {"model": "free"}
        d = e.to_dict()
        assert d["official"] is True and d["pricing"] == {"model": "free"}
        m = PluginManifest.from_dict({"name": "x", "version": "1.0.0",
                                      "entry": "p:f", "official": True,
                                      "api": "2", "pricing": {"model": "free"}})
        assert m.official and m.api == "2" and m.pricing == {"model": "free"}
        # an entry with no pricing still reads as free (forward-compatible seam)
        assert StoreEntry.from_dict({"name": "y", "version": "1"}).pricing == {"model": "free"}


# -- scanner: the from-import bypass is closed --------------------------------

class TestScannerFromImport:
    def test_from_os_import_danger_is_caught(self):
        assert scan_source("from os import system\nsystem('x')", ()) != []
        assert scan_source("from shutil import rmtree", ()) != []
        assert scan_source("from subprocess import run", ()) != []

    def test_benign_from_imports_stay_clean(self):
        assert scan_source("from os import path, getcwd", ()) == []
        assert scan_source("from os import remove", ("fs",)) == []   # declared → ok


# -- the four migrated plugins persist their settings (API v2) ----------------

class TestMigratedPluginSettings:
    def test_currency_persists_home_currency(self):
        from dreamlayer.plugins.currency import currency_plugin, CurrencyPlugin
        db = FakeDB()
        caps = frozenset({"object_lens", "network"})
        p = currency_plugin()
        assert isinstance(p, CurrencyPlugin)          # it's a v2 class now
        _run(p, db, caps=caps)
        assert p.provider.home == "USD"
        p.set_home("eur")
        assert p.provider.home == "EUR"
        # a fresh instance restores the saved choice from the same db
        p2 = currency_plugin()
        _run(p2, db, caps=caps)
        assert p2.provider.home == "EUR"

    def test_face_synth_persists_scale(self):
        from dreamlayer.plugins.face_synth import face_synth_plugin, SCALES
        db = FakeDB()
        caps = frozenset({"midi"})
        p = face_synth_plugin()
        _run(p, db, caps=caps)
        p.set_scale("minor")
        assert p.synth.scale == SCALES["minor"]
        p2 = face_synth_plugin()
        _run(p2, db, caps=caps)
        assert p2.synth.scale == SCALES["minor"]

    def test_air_drums_persists_and_applies_sensitivity(self):
        from dreamlayer.plugins.air_drums import air_drums_plugin
        db = FakeDB()
        caps = frozenset({"midi"})
        p = air_drums_plugin()
        _run(p, db, caps=caps)
        assert p.kit.sensitivity == 1.0
        p.set_sensitivity(0.5)
        hit = p.kit.strike("down", 1.0)               # 1.0 * 0.5 → softer
        assert hit is not None and hit.velocity < 100
        p2 = air_drums_plugin()
        _run(p2, db, caps=caps)
        assert p2.kit.sensitivity == 0.5

    def test_openfoodfacts_reads_persisted_cache_ttl(self):
        from dreamlayer.plugins.openfoodfacts import openfoodfacts_plugin
        db = FakeDB()
        db.set_setting("plugin:open-food-facts", json.dumps({"cache_ttl": 60.0}))
        reg_list: list = []
        _ctx, reg = _run(openfoodfacts_plugin(fetch_fn=lambda u: "{}"),
                         db=db, caps=frozenset({"network"}),
                         shop_registry=reg_list)
        assert reg.result.loaded == ["open-food-facts"]
        assert len(reg_list) == 1                      # registered with the setting present
