"""P1-10: the plugin gate, hardened at two seams the audit picked open.

1. **Alias bypass in the static scan.** The AST screen matched dangerous calls
   by the *written* name (`os.system(...)`, `from os import system`), so a
   one-line rename slipped straight past it::

       import os as o          # `o` is not on any danger list
       o.system("id")          # ... and neither is `o.system`

   The scanner now tracks import aliases (`import x as y`, `from m import f as
   g`) and resolves the receiver before it consults the call table, so the
   rename is followed to the real module.

2. **Validate-executes-on-install.** The smoke load in step 4 *runs* the
   plugin's module code. It used to be on by default, so the store's
   install/load path executed third-party code just by validating it —
   validating a package is not consent to run it. Smoke is now opt-in
   (`run_smoke=True`): author tooling turns it on to test its own code; the
   store never does.
"""
from __future__ import annotations

from dreamlayer.plugins import PluginPackage, validate, scan_source


# -- 1. alias tracking in the static scan ------------------------------------

class TestAliasBypassIsClosed:
    def test_import_as_then_dangerous_call(self):
        # the exact bypass the audit demonstrated
        issues = scan_source("import os as o\no.system('id')\n", ())
        assert any("os.system" in i for i in issues), issues

    def test_from_import_as_dangerous_callable(self):
        issues = scan_source(
            "from os import system as run\nrun('id')\n", ())
        assert any("os.system" in i or "system" in i for i in issues), issues

    def test_aliased_whole_module_danger(self):
        # `import subprocess as sp; sp.run(...)` — module import is itself flagged,
        # and the aliased call resolves too
        issues = scan_source(
            "import subprocess as sp\nsp.run(['id'])\n", ())
        assert any("subprocess" in i for i in issues), issues

    def test_alias_is_capability_gated_not_blanket(self):
        # the point of the gate is *undeclared* reach: with the capability
        # declared, the aliased call is allowed — proving it's a real mediation,
        # not a blanket ban that a rename could never satisfy.
        issues = scan_source("import os as o\no.system('id')\n", {"subprocess"})
        assert issues == [], issues

    def test_plain_alias_import_without_call_is_clean(self):
        # aliasing a harmless module must not raise a false positive
        assert scan_source("import json as j\nj.dumps({})\n", ()) == []

    def test_full_validate_rejects_the_aliased_bypass(self):
        src = ("from dreamlayer.plugins import make_plugin\n"
               "import os as o\n"
               "def p():\n"
               "    o.system('id')\n"
               "    return make_plugin('x', lambda c: None)\n")
        pkg = PluginPackage.build(name="sneaky-alias", version="1.0.0",
                                  entry="plugin:p", source=src)
        r = validate(pkg, host_capabilities=frozenset({"subprocess"}))
        # host *could* grant subprocess, but the plugin never declared it, so
        # the undeclared os.system reach is still a hard error.
        assert not r.ok
        assert any("os.system" in e for e in r.errors), r.errors


# -- 2. smoke load is off by default (validate must not run plugin code) ------

class TestValidateDoesNotExecuteByDefault:
    def _probe_package(self, sentinel):
        # module-level side effect: writes a file the instant the code runs.
        # `open` needs the fs capability, which we declare + grant so the scan
        # passes and .ok is True either way — isolating "did it execute?".
        src = ("from dreamlayer.plugins import make_plugin\n"
               f"open({str(sentinel)!r}, 'w').close()\n"
               "def p():\n"
               "    return make_plugin('probe', lambda c: None)\n")
        return PluginPackage.build(name="probe", version="1.0.0",
                                   entry="plugin:p", source=src,
                                   requires=("fs",))

    def test_default_does_not_exec_module_code(self, tmp_path):
        sentinel = tmp_path / "executed"
        pkg = self._probe_package(sentinel)
        r = validate(pkg, host_capabilities=frozenset({"fs"}))
        assert r.ok, r.errors
        assert not sentinel.exists()           # the code was NOT run

    def test_opt_in_runs_the_smoke_load(self, tmp_path):
        sentinel = tmp_path / "executed"
        pkg = self._probe_package(sentinel)
        r = validate(pkg, host_capabilities=frozenset({"fs"}), run_smoke=True)
        assert r.ok, r.errors
        assert sentinel.exists()               # author opted in → it ran

    def test_store_install_path_does_not_exec(self, tmp_path):
        # PluginStore.install_package validates without run_smoke — the install
        # path must never execute the package it is deciding whether to store.
        from dreamlayer.plugins import PluginStore
        sentinel = tmp_path / "executed"
        pkg = self._probe_package(sentinel)
        store = PluginStore(tmp_path / "store", host_capabilities=frozenset({"fs"}))
        report = store.install_package(pkg)
        assert report.ok, report.errors
        assert not sentinel.exists()           # stored without ever running it
