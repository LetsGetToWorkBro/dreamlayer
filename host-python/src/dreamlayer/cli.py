"""dreamlayer — command-line tools for building and shipping plugins.

    dreamlayer plugins new my-plugin     # scaffold a working starter
    dreamlayer plugins validate .        # run the store's gate locally
    dreamlayer plugins pack .            # build the publishable package JSON
    dreamlayer plugins install .         # sideload it to a paired Brain
    dreamlayer plugins list --installed  # what a Brain is running

Stdlib only (argparse + urllib), so it installs with the base package and runs
anywhere. The SDK is imported lazily inside handlers, so ``--help`` is instant.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")

OK, BAD, WARN, ARROW = "✓", "✗", "⚠", "→"


# --- small output helpers ----------------------------------------------------

def _p(msg=""):
    print(msg)


def _err(msg):
    print(msg, file=sys.stderr)


def _class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-")) + "Plugin"


def _card_type(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-")) + "Card"


# --- turning a directory / file into a validated-shaped package --------------

def _pkg_from_dir(d: Path):
    """Build a PluginPackage from a plugin directory (plugin.json + plugin.py).
    The manifest's checksum is stamped from plugin.py, which becomes the code
    payload the gate scans and runs."""
    from dreamlayer.sdk import PluginManifest, PluginPackage, sha256_of
    meta_path, src_path = d / "plugin.json", d / "plugin.py"
    if not meta_path.exists() or not src_path.exists():
        raise FileNotFoundError(
            f"{d} is not a plugin directory (needs plugin.json + plugin.py)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = src_path.read_text(encoding="utf-8")
    meta = dict(meta)
    meta["checksum"] = sha256_of(source)
    meta.setdefault("entry", "plugin:plugin")
    return PluginPackage(manifest=PluginManifest.from_dict(meta), source=source)


def _load_package(path_str: str):
    """Resolve a CLI target to a PluginPackage: a plugin dir, or a packaged
    ``.json`` ({manifest, source})."""
    from dreamlayer.sdk import PluginManifest, PluginPackage
    p = Path(path_str)
    if p.is_dir():
        return _pkg_from_dir(p)
    if p.is_file() and p.suffix == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        if "manifest" not in d or "source" not in d:
            raise ValueError(f"{p} is not a package (expected keys: manifest, source)")
        return PluginPackage(manifest=PluginManifest.from_dict(d["manifest"]),
                             source=d["source"])
    raise FileNotFoundError(f"{path_str}: not a plugin directory or a package .json")


# --- HTTP to a Brain (stdlib urllib) ----------------------------------------

def _brain(args):
    url = args.brain or os.environ.get("DREAMLAYER_BRAIN", "")
    tok = args.token or os.environ.get("DREAMLAYER_TOKEN", "")
    return url.rstrip("/"), tok


def _request(url: str, token: str, body=None):
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-DreamLayer-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # connection refused, DNS, timeout
        return {"ok": False, "error": repr(e)}


# --- scaffolding -------------------------------------------------------------

def _scaffold(name: str, author: str) -> dict:
    cls, card = _class_name(name), _card_type(name)
    plugin_py = f'''"""{name} — a DreamLayer plugin.

Scaffolded by `dreamlayer plugins new`. This is an API v2 plugin: a HUD card
plus one persisted setting. Edit register() to wire into the layer, then run
`dreamlayer plugins validate .` and `pytest` as you build.
"""
from dreamlayer.sdk import make_plugin  # noqa: F401  (handy for simple plugins)


def _draw_card(draw, card):
    """Paint the plugin's HUD card. `draw` is Pillow-style; the display is a
    256x256 additive surface (white on black). `card` is the dict your logic
    emits and the host renders."""
    text = str(card.get("text", "hello from {name}"))
    draw.text((128, 128), text, anchor="mm", fill=(255, 255, 255))


class {cls}:
    """A minimal API v2 plugin. Declares only the capabilities it uses."""

    name = "{name}"
    version = "0.1.0"
    requires = ("cards",)          # this plugin draws its own HUD card

    def __init__(self):
        self._settings = None
        self.greeting = "hello"

    def register(self, ctx):
        # ctx is the narrow SDK surface. Capture a name-bound settings handle so
        # setters work even outside a lifecycle callback.
        self._settings = ctx.settings
        ctx.add_card_renderer("{card}", _draw_card)

    def start(self, ctx):
        # restore anything you persisted last session
        if self._settings is not None:
            self.greeting = self._settings.get("greeting", "hello")

    def set_greeting(self, text):
        """A host-invoked setter that persists across sessions."""
        self.greeting = str(text)
        if self._settings is not None:
            self._settings.set("greeting", self.greeting)


def plugin():
    """Entry factory. plugin.json's `entry` ("plugin:plugin") points here."""
    return {cls}()
'''
    plugin_json = json.dumps({
        "name": name,
        "version": "0.1.0",
        "entry": "plugin:plugin",
        "api": "2",
        "author": author,
        "description": f"A one-line summary of what {name} does.",
        "requires": ["cards"],
        "forwho": "Who this plugin is for.",
        "long": [
            "A short paragraph on how it helps the wearer.",
            "Another paragraph — this copy travels with the plugin into the store.",
        ],
        "screenshot": "",
    }, indent=2) + "\n"
    test_py = f'''"""Local gate for {name} — the same checks the store runs."""
import json
from pathlib import Path

from dreamlayer.sdk import (
    PluginManifest, PluginPackage, validate, sha256_of, KNOWN_CAPABILITIES,
)

HERE = Path(__file__).parent


def _package():
    src = (HERE / "plugin.py").read_text(encoding="utf-8")
    meta = json.loads((HERE / "plugin.json").read_text(encoding="utf-8"))
    meta["checksum"] = sha256_of(src)
    return PluginPackage(manifest=PluginManifest.from_dict(meta), source=src)


def test_passes_the_gate():
    report = validate(_package(), host_capabilities=frozenset(KNOWN_CAPABILITIES))
    assert report.ok, report.errors
'''
    readme = f'''# {name}

A DreamLayer plugin. Built against the [DreamLayer SDK](https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/docs/SDK.md).

## Develop

```bash
dreamlayer plugins validate .     # integrity + capability scan + smoke test
pytest                            # the same gate, as a test
dreamlayer plugins pack .         # -> {name}-0.1.0.json (publishable)
dreamlayer plugins install . --brain http://localhost:8765   # sideload to a Brain
```

Edit `plugin.py` (your code) and `plugin.json` (name, capabilities, store copy).
Declare every capability you use in `requires` — the gate refuses undeclared
reach. Open a pull request against the registry to publish.
'''
    return {"plugin.py": plugin_py, "plugin.json": plugin_json,
            "test_plugin.py": test_py, "README.md": readme}


# --- commands ----------------------------------------------------------------

def cmd_new(args) -> int:
    name = args.name
    if not NAME_RE.match(name):
        _err(f"{BAD} invalid name {name!r} — use lowercase letters, digits, and hyphens")
        return 2
    dest = Path(args.dir) / name
    if dest.exists():
        _err(f"{BAD} {dest} already exists")
        return 2
    dest.mkdir(parents=True)
    for fname, content in _scaffold(name, args.author).items():
        (dest / fname).write_text(content, encoding="utf-8")
    _p(f"{OK} created {dest}/  (plugin.py · plugin.json · test_plugin.py · README.md)")
    _p("")
    _p("Next:")
    _p(f"  cd {dest}")
    _p("  dreamlayer plugins validate .")
    _p("  pytest")
    return 0


def _print_report(label: str, report) -> int:
    _p(f"  capabilities: {', '.join(report.capabilities) or '(none)'}")
    for w in report.warnings:
        _p(f"  {WARN} {w}")
    for e in report.errors:
        _p(f"  {BAD} {e}")
    if report.ok:
        _p(f"{OK} {label} passes the gate" + (f" ({len(report.warnings)} warning(s))" if report.warnings else ""))
        return 0
    _p(f"{BAD} {label} failed the gate ({len(report.errors)} error(s))")
    return 1


def cmd_validate(args) -> int:
    from dreamlayer.sdk import validate, KNOWN_CAPABILITIES
    try:
        pkg = _load_package(args.path)
    except Exception as e:
        _err(f"{BAD} {e}")
        return 2
    # validate as if the host can grant everything, so only real problems fail.
    report = validate(pkg, host_capabilities=frozenset(KNOWN_CAPABILITIES))
    _p(f"{pkg.manifest.name} v{pkg.manifest.version} (api {pkg.manifest.api})")
    return _print_report(pkg.manifest.name, report)


def cmd_pack(args) -> int:
    try:
        pkg = _load_package(args.path)
    except Exception as e:
        _err(f"{BAD} {e}")
        return 2
    out = Path(args.output) if args.output else \
        Path(f"{pkg.manifest.name}-{pkg.manifest.version}.json")
    payload = {"manifest": pkg.manifest.to_dict(), "source": pkg.source}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _p(f"{OK} wrote {out}  (checksum {pkg.manifest.checksum})")
    return 0


def cmd_install(args) -> int:
    url, tok = _brain(args)
    if not url:
        _err(f"{BAD} no Brain — pass --brain URL or set DREAMLAYER_BRAIN")
        return 2
    target = args.target
    p = Path(target)
    if p.is_dir() or (p.is_file() and p.suffix == ".json"):
        try:
            pkg = _load_package(target)
        except Exception as e:
            _err(f"{BAD} {e}")
            return 2
        body = {"manifest": pkg.manifest.to_dict(), "source": pkg.source,
                "grant": list(pkg.manifest.requires)}
        label = pkg.manifest.name
    elif NAME_RE.match(target):
        body = {"name": target, "grant": []}   # needs a registry wired on the Brain
        label = target
    else:
        _err(f"{BAD} {target}: not a plugin directory, a package .json, or a plugin name")
        return 2
    _p(f"{ARROW} installing {label} to {url} …")
    resp = _request(url + "/dreamlayer/plugins/install", tok, body)
    if resp.get("ok"):
        for w in resp.get("warnings", []):
            _p(f"  {WARN} {w}")
        _p(f"{OK} installed {label}")
        return 0
    for e in (resp.get("errors") or [resp.get("error", "install failed")]):
        _p(f"  {BAD} {e}")
    return 1


def cmd_list(args) -> int:
    url, tok = _brain(args)
    if url and args.installed:
        resp = _request(url + "/dreamlayer/plugins", tok)
        installed = resp.get("installed", [])
        if not installed:
            _p("no plugins installed")
            return 0
        for p in installed:
            tag = " ✓ official" if p.get("official") else ""
            _p(f"  {p.get('name')}  v{p.get('version','')}  {p.get('author','')}{tag}")
        return 0
    # otherwise list the registry catalogue
    idx_path = Path(args.registry) if args.registry else Path("registry/index.json")
    if not idx_path.exists():
        _err(f"{BAD} no registry index at {idx_path} (pass --registry, or --installed --brain URL)")
        return 2
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    for p in idx.get("plugins", []):
        price = (p.get("pricing") or {}).get("model", "free")
        tag = " ✓ official" if p.get("official") else ""
        _p(f"  {p.get('name')}  v{p.get('version','')}  [{price}]{tag}  — {p.get('description','')[:60]}")
    return 0


# --- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dreamlayer", description="Build and ship DreamLayer plugins.")
    parser.add_argument("--version", action="store_true", help="print the SDK version and exit")
    groups = parser.add_subparsers(dest="group")

    plugins = groups.add_parser("plugins", help="build, validate, and install plugins")
    sub = plugins.add_subparsers(dest="cmd")

    new = sub.add_parser("new", help="scaffold a working starter plugin")
    new.add_argument("name", help="plugin name (lowercase-with-hyphens)")
    new.add_argument("--dir", default=".", help="parent directory (default: .)")
    new.add_argument("--author", default="your-name", help="author for the manifest")
    new.set_defaults(func=cmd_new)

    val = sub.add_parser("validate", help="run the store's gate on a plugin locally")
    val.add_argument("path", help="a plugin directory or a packaged .json")
    val.set_defaults(func=cmd_validate)

    pack = sub.add_parser("pack", help="build the publishable package .json")
    pack.add_argument("path", help="a plugin directory")
    pack.add_argument("-o", "--output", help="output path (default: <name>-<version>.json)")
    pack.set_defaults(func=cmd_pack)

    inst = sub.add_parser("install", help="sideload a plugin to a paired Brain")
    inst.add_argument("target", help="a plugin directory, a package .json, or a registry name")
    inst.add_argument("--brain", help="Brain base URL (or set DREAMLAYER_BRAIN)")
    inst.add_argument("--token", help="Brain token (or set DREAMLAYER_TOKEN)")
    inst.set_defaults(func=cmd_install)

    ls = sub.add_parser("list", help="list the registry catalogue or a Brain's installed plugins")
    ls.add_argument("--installed", action="store_true", help="list what a Brain is running")
    ls.add_argument("--brain", help="Brain base URL (or set DREAMLAYER_BRAIN)")
    ls.add_argument("--token", help="Brain token (or set DREAMLAYER_TOKEN)")
    ls.add_argument("--registry", help="path to a registry index.json")
    ls.set_defaults(func=cmd_list)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        from dreamlayer.sdk import __version__
        _p(f"dreamlayer sdk {__version__}")
        return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
