"""Entry-point discovery must not be the way third-party code gets to run.

`plugins/store.py` spends three hundred lines deciding whether an installed
package has earned host authority: a signature from a registered publisher, or a
first-party content-hash pin, and anything unvouched goes into a WASM or
subprocess jail — with `require_sandbox` to refuse outright when no real sandbox
exists on the platform.

`hookspecs.discover_entrypoint_plugins()` walked past every one of those steps.
It called `ep.load()` on everything advertised under the entry-point group, and
**loading an entry point is importing it**: third-party module code ran
in-process, with the host user's full authority, at DISCOVERY time — before any
policy could look at it. `make_pluggy_manager()` did the same thing, so merely
asking for a manager executed whatever was installed.

The setuptools convention cannot be fixed by ordering, because there is no
"before" to inspect: the import IS the load. So the split is the fix. Discovery
enumerates; importing is a separate call; and the caller has to say which entry
points earned it.
"""
from __future__ import annotations

import pytest

from dreamlayer.plugins import hookspecs


class _Ep:
    """An entry point that records whether anything imported it."""

    def __init__(self, name="evil", value="pkg.mod:plugin", boom=False):
        self.name = name
        self.value = value
        self.loaded = False
        self._boom = boom

    def load(self):
        self.loaded = True
        if self._boom:
            raise RuntimeError("import blew up")
        return object()


class _Reg:
    def __init__(self):
        self.loaded = []

    def load(self, p):
        self.loaded.append(p)
        return True


@pytest.fixture
def advertised(monkeypatch):
    """Two packages advertising themselves under the group."""
    eps = [_Ep("alpha", "alpha.plug:main"), _Ep("beta", "beta.plug:main")]
    monkeypatch.setattr(hookspecs, "discover_entrypoints", lambda: list(eps))
    return eps


class TestDiscoveryImportsNothing:
    def test_the_importing_variant_is_gone(self):
        """Named rather than pattern-matched: if it comes back, this fails."""
        assert not hasattr(hookspecs, "discover_entrypoint_plugins")

    def test_discovery_returns_entry_points_not_loaded_objects(self, advertised):
        got = hookspecs.discover_entrypoints()
        assert [e.name for e in got] == ["alpha", "beta"]
        assert not any(e.loaded for e in advertised), "discovery imported code"

    def test_the_value_survives_so_a_policy_has_something_to_judge(self, advertised):
        """The old version threw this away by importing first — a policy needs
        to know WHAT would run before it runs."""
        assert [e.value for e in hookspecs.discover_entrypoints()] == [
            "alpha.plug:main", "beta.plug:main"]


class TestLoadingIsADecision:
    def test_load_into_imports_nothing_by_default(self, advertised):
        reg = _Reg()
        n = hookspecs.load_into(reg)
        assert n == 0
        assert not any(e.loaded for e in advertised)

    def test_the_omission_is_logged_rather_than_silent(self, advertised, caplog):
        """A doorway that quietly ignores what is standing in it is how someone
        concludes their plugin is broken and goes looking for a workaround."""
        import logging
        with caplog.at_level(logging.INFO, logger="dreamlayer.plugins.hookspecs"):
            hookspecs.load_into(_Reg())
        assert any("NOT loaded" in r.getMessage() for r in caplog.records)

    def test_explicit_objects_still_load_untouched(self, advertised):
        """Something the caller already holds has already been decided about."""
        reg = _Reg()
        a, b = object(), object()
        assert hookspecs.load_into(reg, plugins=[a, b]) == 2
        assert reg.loaded == [a, b]
        assert not any(e.loaded for e in advertised)

    def test_a_policy_decides_one_by_one(self, advertised):
        reg = _Reg()
        n = hookspecs.load_into(reg, allow_entrypoints=lambda ep: ep.name == "alpha")
        assert n == 1
        assert advertised[0].loaded is True
        assert advertised[1].loaded is False, "a refused entry point was imported"

    def test_true_means_everything_and_has_to_be_typed_out(self, advertised):
        reg = _Reg()
        assert hookspecs.load_into(reg, allow_entrypoints=True) == 2
        assert all(e.loaded for e in advertised)

    def test_a_policy_that_raises_refuses_rather_than_admits(self, advertised):
        """Fail CLOSED. An exception in the trust decision is not consent."""
        def boom(ep):
            raise RuntimeError("cannot reach the key server")

        reg = _Reg()
        assert hookspecs.load_into(reg, allow_entrypoints=boom) == 0
        assert not any(e.loaded for e in advertised)

    def test_one_bad_import_does_not_take_the_others_down(self, monkeypatch):
        eps = [_Ep("bad", boom=True), _Ep("good")]
        monkeypatch.setattr(hookspecs, "discover_entrypoints", lambda: list(eps))
        reg = _Reg()
        assert hookspecs.load_into(reg, allow_entrypoints=True) == 1


class TestThePluggyDoorwayToo:
    def test_building_a_manager_does_not_load_entry_points(self, monkeypatch):
        """`pm.load_setuptools_entrypoints` imports every advertised package,
        and it used to be called unconditionally — so merely asking for a
        manager ran third-party code."""
        pm = hookspecs.make_pluggy_manager()
        if pm is None:
            pytest.skip("pluggy not installed")
        called = []
        monkeypatch.setattr(type(pm), "load_setuptools_entrypoints",
                            lambda self, g: called.append(g))
        hookspecs.make_pluggy_manager()
        assert called == []

    def test_it_loads_them_when_asked(self, monkeypatch):
        pm = hookspecs.make_pluggy_manager()
        if pm is None:
            pytest.skip("pluggy not installed")
        called = []
        monkeypatch.setattr(type(pm), "load_setuptools_entrypoints",
                            lambda self, g: called.append(g))
        hookspecs.make_pluggy_manager(load_entrypoints=True)
        assert called == [hookspecs.ENTRY_POINT_GROUP]


class TestItSaysWhyInThePlaceSomeoneWouldLook:
    def test_the_module_names_the_model_it_was_bypassing(self):
        import pathlib
        src = (pathlib.Path(hookspecs.__file__)).read_text(encoding="utf-8")
        assert "load_installed" in src
        assert "the import is the load" in src.lower()
