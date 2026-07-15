"""test_cli.py — the `dreamlayer plugins` CLI: scaffold → validate → pack, plus
the guarded install/list paths. Exercises main() directly (exit codes + output).
"""
from __future__ import annotations

import json

from dreamlayer import cli


def _new(tmp_path, name="demo-plugin"):
    rc = cli.main(["plugins", "new", name, "--dir", str(tmp_path), "--author", "Ada"])
    return rc, tmp_path / name


def test_new_scaffolds_a_working_plugin(tmp_path, capsys):
    rc, d = _new(tmp_path)
    assert rc == 0
    for f in ("plugin.py", "plugin.json", "test_plugin.py", "README.md"):
        assert (d / f).exists(), f
    meta = json.loads((d / "plugin.json").read_text())
    assert meta["name"] == "demo-plugin" and meta["api"] == "2"
    assert (d / "plugin.py").read_text().startswith('"""demo-plugin')
    assert "✓ created" in capsys.readouterr().out


def test_new_rejects_a_bad_name(tmp_path):
    assert cli.main(["plugins", "new", "Bad Name", "--dir", str(tmp_path)]) == 2


def test_new_refuses_to_overwrite(tmp_path):
    _new(tmp_path)
    assert cli.main(["plugins", "new", "demo-plugin", "--dir", str(tmp_path)]) == 2


def test_validate_passes_the_scaffold(tmp_path, capsys):
    _, d = _new(tmp_path)
    rc = cli.main(["plugins", "validate", str(d)])
    out = capsys.readouterr().out
    assert rc == 0 and "passes the gate" in out


def test_validate_catches_a_bad_plugin(tmp_path, capsys):
    _, d = _new(tmp_path)
    # inject an undeclared dangerous op → the static scan must fail it
    (d / "plugin.py").write_text(
        "import socket\n" + (d / "plugin.py").read_text(), encoding="utf-8")
    rc = cli.main(["plugins", "validate", str(d)])
    out = capsys.readouterr().out
    assert rc == 1 and "failed the gate" in out and "socket" in out


def test_pack_writes_a_valid_package(tmp_path):
    _, d = _new(tmp_path)
    out = tmp_path / "demo.json"
    assert cli.main(["plugins", "pack", str(d), "-o", str(out)]) == 0
    pkg = json.loads(out.read_text())
    assert pkg["manifest"]["name"] == "demo-plugin"
    assert pkg["manifest"]["checksum"].startswith("sha256:")
    assert "class DemoPluginPlugin" in pkg["source"]
    # the packed .json re-validates
    assert cli.main(["plugins", "validate", str(out)]) == 0


def test_install_without_a_brain_guides(tmp_path, capsys):
    _, d = _new(tmp_path)
    rc = cli.main(["plugins", "install", str(d)])   # no --brain, no env
    assert rc == 2 and "no Brain" in capsys.readouterr().err


def test_list_registry_catalogue(tmp_path, capsys):
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps({"plugins": [
        {"name": "face-synth", "version": "0.1.0", "official": True,
         "pricing": {"model": "free"}, "description": "head as a controller"}]}))
    rc = cli.main(["plugins", "list", "--registry", str(idx)])
    out = capsys.readouterr().out
    assert rc == 0 and "face-synth" in out and "[free]" in out and "official" in out


def test_info_shows_manifest_and_contributions(tmp_path, capsys):
    _, d = _new(tmp_path)
    rc = cli.main(["plugins", "info", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "demo-plugin" in out and "contributes" in out and "card_renderer" in out


def test_info_json(tmp_path, capsys):
    _, d = _new(tmp_path)
    capsys.readouterr()                           # drop the scaffold's "created" line
    assert cli.main(["plugins", "info", str(d), "--json"]) == 0
    import json as _json
    data = _json.loads(capsys.readouterr().out)
    assert data["name"] == "demo-plugin" and data["contributes"]["card_renderer"]


def test_contributions_maps_extension_points():
    from dreamlayer.sdk import contributions
    from dreamlayer.plugins.filler import filler_plugin
    from dreamlayer.plugins.currency import currency_plugin
    fc = contributions(filler_plugin())
    assert fc["card_renderer"] == ["FillerCard"] and fc["perceptor"] == 1
    cc = contributions(currency_plugin())
    assert cc["object_provider"] == 1 and "card_renderer" not in cc


def test_preview_writes_a_device_png(tmp_path):
    _, d = _new(tmp_path)
    out = tmp_path / "shot.png"
    rc = cli.main(["plugins", "preview", str(d), "-o", str(out)])
    assert rc == 0 and out.exists() and out.stat().st_size > 0
    from PIL import Image
    assert Image.open(out).size == (256, 256)


def test_preview_shot_makes_a_store_banner(tmp_path):
    _, d = _new(tmp_path)
    out = tmp_path / "banner.png"
    assert cli.main(["plugins", "preview", str(d), "--shot", "-o", str(out)]) == 0
    from PIL import Image
    assert Image.open(out).size == (640, 340)


def test_dev_once_validates_the_scaffold(tmp_path, capsys):
    _, d = _new(tmp_path)
    rc = cli.main(["plugins", "dev", str(d), "--once"])
    out = capsys.readouterr().out
    assert rc == 0 and "gate green" in out


def test_list_entry_points_runs(capsys):
    # no dreamlayer.plugins entry points in the test env → friendly note, exit 0
    rc = cli.main(["plugins", "list", "--entry-points"])
    assert rc == 0


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert "dreamlayer sdk" in capsys.readouterr().out


# --- entrypoint: structured logging + top-level error handling ---------------

def test_main_configures_logging_at_the_entrypoint(monkeypatch):
    # a CLI run must be debuggable from logs alone — the entrypoint wires
    # configure_logging (audit 2026-07-14: only the Brain server did before).
    import dreamlayer.logging_setup as ls
    called = []
    monkeypatch.setattr(ls, "configure_logging", lambda *a, **k: called.append(True))
    cli.main(["--version"])
    assert called == [True]


def test_main_reports_a_handler_error_cleanly(tmp_path, capsys, monkeypatch):
    # an unexpected handler exception exits 1 with a one-line reason, not a
    # raw traceback.
    def boom(_args):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(cli, "cmd_new", boom)
    rc = cli.main(["plugins", "new", "x-plugin", "--dir", str(tmp_path)])
    assert rc == 1
    assert "kaboom" in capsys.readouterr().err


def test_main_reraises_the_traceback_under_dl_debug(tmp_path, monkeypatch):
    import pytest
    def boom(_args):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(cli, "cmd_new", boom)
    monkeypatch.setenv("DL_DEBUG", "1")
    with pytest.raises(RuntimeError):
        cli.main(["plugins", "new", "x-plugin", "--dir", str(tmp_path)])
