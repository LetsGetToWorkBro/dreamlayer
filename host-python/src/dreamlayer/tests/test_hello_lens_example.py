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
    assert "make_plugin" in readme
    # the tutorial teaches the actual CLI, not a hand-rolled hashing snippet
    assert "dreamlayer plugins pack" in readme


def test_example_obeys_the_sdk_import_contract():
    # SDK.md says "import only from dreamlayer.sdk" — the flagship tutorial
    # must obey its own rule or newcomers copy the wrong import
    src = (EXAMPLE / "hello_lens.py").read_text()
    assert "from dreamlayer.sdk import" in src
    assert "from dreamlayer.plugins import" not in src


def test_the_documented_cli_loads_this_example():
    # "dreamlayer plugins validate examples/hello-lens/" is the documented first
    # step; the SDK loader must accept the example's layout or that step is broken
    from dreamlayer.sdk import (package_from_dir, validate as sdk_validate,
                                KNOWN_CAPABILITIES)
    pkg = package_from_dir(str(EXAMPLE))
    assert sdk_validate(pkg, frozenset(KNOWN_CAPABILITIES)).ok


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
