"""examples/hello-lens is the first-plugin tutorial — this test runs that
exact folder through the REAL store machinery, so the tutorial cannot rot:
if the example stops validating, loading, or matching its checksum, CI fails."""
from __future__ import annotations

from pathlib import Path

from dreamlayer.plugins.base import PluginContext, PluginRegistry
from dreamlayer.plugins.package import PluginPackage, sha256_of
from dreamlayer.plugins.validate import validate

EXAMPLE = Path(__file__).parents[3].parent / "examples" / "hello-lens"


def test_example_folder_exists_with_tutorial():
    assert (EXAMPLE / "hello_lens.py").is_file()
    assert (EXAMPLE / "manifest.json").is_file()
    readme = (EXAMPLE / "README.md").read_text()
    assert "make_plugin" in readme and "sha256_of" in readme


def test_example_is_a_valid_store_package():
    pkg = PluginPackage.load(EXAMPLE)
    assert pkg.manifest.problems() == []
    # drift-proof: the committed checksum matches the committed source
    assert pkg.checksum_ok(), "hello_lens.py changed — regenerate manifest checksum"
    assert pkg.manifest.checksum == sha256_of(pkg.source)
    report = validate(pkg, host_capabilities=frozenset({"cards"}))
    assert report.ok, report.errors


def test_example_loads_through_the_registry():
    pkg = PluginPackage.load(EXAMPLE)
    ns: dict = {"__name__": "hello_lens"}
    exec(compile(pkg.source, "hello_lens.py", "exec"), ns)
    plugin = ns["make"]()
    reg = PluginRegistry(PluginContext(capabilities=frozenset({"cards"})))
    assert reg.load(plugin) is True
    assert "hello-lens" in reg.result.loaded
    # and without the capability it skips cleanly, exactly as the tutorial says
    reg2 = PluginRegistry(PluginContext(capabilities=frozenset()))
    assert reg2.load(ns["make"]()) is False
    assert any("cards" in reason for _, reason in reg2.result.skipped)
