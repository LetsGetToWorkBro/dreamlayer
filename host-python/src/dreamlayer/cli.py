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

def _load_package(path_str: str):
    """Resolve a CLI target to a PluginPackage: a plugin dir, or a packaged
    ``.json`` ({manifest, source})."""
    from dreamlayer.sdk import PluginManifest, PluginPackage, package_from_dir
    p = Path(path_str)
    if p.is_dir():
        return package_from_dir(p)
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

For a plugin with no lifecycle or settings, a one-liner works too:
`from dreamlayer.sdk import make_plugin` and
`return make_plugin("{name}", register, requires=("cards",))`.
"""


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
    from dreamlayer.sdk import SDK_VERSION
    plugin_json = json.dumps({
        "name": name,
        "version": "0.1.0",
        "entry": "plugin:plugin",
        "api": "2",
        "min_sdk": SDK_VERSION,
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
from pathlib import Path

from dreamlayer.sdk import package_from_dir, validate, KNOWN_CAPABILITIES

HERE = Path(__file__).parent


def test_passes_the_gate():
    pkg = package_from_dir(HERE)
    report = validate(pkg, host_capabilities=frozenset(KNOWN_CAPABILITIES))
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


def cmd_info(args) -> int:
    from dreamlayer.sdk import contributions
    from dreamlayer.plugins.store import load_plugin_object
    try:
        pkg = _load_package(args.path)
    except Exception as e:
        _err(f"{BAD} {e}")
        return 2
    m = pkg.manifest
    contribs = contributions(load_plugin_object(pkg))
    if args.json:
        _p(json.dumps({"name": m.name, "version": m.version, "api": m.api,
                       "min_sdk": m.min_sdk, "requires": list(m.requires),
                       "official": m.official, "pricing": m.pricing,
                       "contributes": contribs}, indent=2))
        return 0
    _p(f"{m.name}  v{m.version}  (api {m.api}"
       + (f", min_sdk {m.min_sdk}" if m.min_sdk else "") + ")")
    if m.official:
        _p("  ✓ official — DreamLayer team")
    _p(f"  needs: {', '.join(m.requires) or 'no special access'}")
    _p(f"  price: {(m.pricing or {}).get('model', 'free')}")
    if contribs:
        _p("  contributes:")
        for kind, v in contribs.items():
            _p(f"    • {kind}: {', '.join(v) if isinstance(v, list) else v}")
    else:
        _p("  contributes: (nothing detected)")
    return 0


def _store_banner(card_img, size=(640, 340)):
    """Compose a 256 device card, alpha-masked, centred on a dark store banner."""
    from PIL import Image
    bg = Image.new("RGB", size, (10, 15, 16))
    card = card_img.convert("RGBA")
    x = (size[0] - card.width) // 2
    y = (size[1] - card.height) // 2
    bg.paste(card, (x, y), card)
    return bg


def cmd_preview(args) -> int:
    from dreamlayer.sdk import render_card
    try:
        pkg = _load_package(args.path)
    except Exception as e:
        _err(f"{BAD} {e}")
        return 2
    card = None
    if args.card:
        try:
            card = json.loads(args.card)
        except Exception as e:
            _err(f"{BAD} --card is not valid JSON: {e}")
            return 2
    elif Path(args.path).is_dir():                # honour a plugin.json preview_card
        try:
            meta = json.loads((Path(args.path) / "plugin.json").read_text(encoding="utf-8"))
            card = meta.get("preview_card")
        except Exception:
            card = None
    from dreamlayer.plugins.store import load_plugin_object
    try:
        img = render_card(load_plugin_object(pkg), card)
    except ValueError as e:
        _err(f"{BAD} {e}")
        return 2
    if args.shot:
        img = _store_banner(img)
    elif args.scale and args.scale > 1:
        from PIL import Image
        img = img.resize((img.width * args.scale, img.height * args.scale), Image.NEAREST)
    out = Path(args.output) if args.output else Path(f"{pkg.manifest.name}-preview.png")
    img.save(out)
    _p(f"{OK} rendered {pkg.manifest.name}'s card through the device renderer → {out}")
    return 0


def _watch_sig(d: Path):
    sig = []
    for f in ("plugin.py", "plugin.json"):
        p = d / f
        sig.append(p.stat().st_mtime if p.exists() else 0.0)
    return tuple(sig)


def _dev_pass(path: str, brain_url: str, tok: str) -> None:
    from dreamlayer.sdk import validate, KNOWN_CAPABILITIES
    try:
        pkg = _load_package(path)
    except Exception as e:
        _p(f"  {BAD} {e}")
        return
    report = validate(pkg, host_capabilities=frozenset(KNOWN_CAPABILITIES))
    if not report.ok:
        for e in report.errors:
            _p(f"  {BAD} {e}")
        return
    _p(f"  {OK} {pkg.manifest.name} v{pkg.manifest.version} — gate green"
       + (f" ({len(report.warnings)} warning(s))" if report.warnings else ""))
    if brain_url:
        body = {"manifest": pkg.manifest.to_dict(), "source": pkg.source,
                "grant": list(pkg.manifest.requires)}
        resp = _request(brain_url + "/dreamlayer/plugins/install", tok, body)
        if resp.get("ok"):
            _p(f"  {OK} reloaded on {brain_url}")
        else:
            why = resp.get("error") or (resp.get("errors") or ["reload failed"])[0]
            _p(f"  {BAD} reload failed: {why}")


def cmd_dev(args) -> int:
    d = Path(args.path)
    if not d.is_dir():
        _err(f"{BAD} dev watches a plugin directory: {args.path}")
        return 2
    url, tok = _brain(args)
    dest = f" → {url}" if url else ""
    _p(f"{ARROW} watching {d}{dest} — edit plugin.py / plugin.json (Ctrl-C to stop)")
    _dev_pass(str(d), url, tok)               # initial pass
    if args.once:
        return 0
    import time
    last = _watch_sig(d)
    try:
        while True:
            time.sleep(max(0.2, args.interval))
            sig = _watch_sig(d)
            if sig != last:
                last = sig
                _p(f"{ARROW} change detected — re-checking")
                _dev_pass(str(d), url, tok)
    except KeyboardInterrupt:
        _p("\nstopped.")
    return 0


def cmd_list(args) -> int:
    if getattr(args, "entry_points", False):
        from dreamlayer.sdk import discover
        found = discover()
        if not found:
            _p(f"no entry-point plugins found (declare "
               f'[project.entry-points."dreamlayer.plugins"] in a plugin package)')
            return 0
        for d in found:
            _p(f"  {d.name}  → {d.value}" + (f"  ({d.dist} {d.version})" if d.dist else ""))
        return 0
    url, tok = _brain(args)
    if args.installed and not url:
        _err(f"{BAD} --installed needs a Brain — pass --brain URL or set DREAMLAYER_BRAIN")
        return 2
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


# --- memories: your data is a file -------------------------------------------

def _mem_db(args) -> str:
    """Resolve the memory SQLite path: --db, else $DREAMLAYER_DB, else the
    Brain's default (~/.dreamlayer/dreamlayer.db)."""
    raw = getattr(args, "db", None) or os.environ.get("DREAMLAYER_DB")
    if raw:
        return str(Path(raw).expanduser())
    return str(Path.home() / ".dreamlayer" / "dreamlayer.db")


def _veil_blocked(db_path: str):
    """The Privacy Veil, as a launch-time gate for the detached browser. Honest
    scope: a standalone CLI can't see live orchestrator state, so it honors two
    explicit, checkable signals — $DREAMLAYER_VEIL, or a `veil.lock` beside the
    db. Returns (blocked, reason)."""
    v = os.environ.get("DREAMLAYER_VEIL", "").strip().lower()
    if v in {"1", "true", "on", "yes"}:
        return True, "DREAMLAYER_VEIL is set"
    lock = Path(db_path).resolve().parent / "veil.lock"
    if lock.exists():
        return True, f"the privacy veil is up ({lock})"
    return False, ""


def cmd_mem_path(args) -> int:
    """Print where your memory lives — 'your data is one file, here it is'."""
    db = _mem_db(args)
    p = Path(db)
    if p.exists():
        kb = p.stat().st_size / 1024
        _p(f"{db}  ({kb:.1f} KB)")
    else:
        _p(f"{db}  (no file yet — the Brain creates it on first memory)")
    return 0


def cmd_mem_browse(args) -> int:
    """Open your memory as a browsable, SQL-queryable database (read-only)."""
    db = _mem_db(args)
    if not Path(db).exists():
        _err(f"{BAD} no memory file at {db} — pass --db PATH or set DREAMLAYER_DB")
        return 2
    blocked, reason = _veil_blocked(db)
    if blocked:
        _err(f"{BAD} not opening your memory: {reason}. Lower the veil first.")
        return 2
    from dreamlayer.memory.datasette_app import MemoryExplorer
    ex = MemoryExplorer(db)
    meta = ex.write_metadata()
    cmd = ex.command(port=args.port, metadata_path=meta)
    if args.print_cmd or not ex.available:
        if not ex.available and not args.print_cmd:
            _p(f"{WARN} datasette isn't installed (pip install 'dreamlayer[infra]'). Run:")
        _p(cmd)
        return 0
    import shlex
    import subprocess
    _p(f"{ARROW} serving your memory read-only at http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    subprocess.run(shlex.split(cmd))
    return 0


def cmd_mem_export(args) -> int:
    """Copy your memory file somewhere — it's yours to take."""
    import shutil
    db = _mem_db(args)
    if not Path(db).exists():
        _err(f"{BAD} no memory file at {db} — pass --db PATH or set DREAMLAYER_DB")
        return 2
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db, dest)
    kb = dest.stat().st_size / 1024
    _p(f"{OK} exported your memory → {dest}  ({kb:.1f} KB)")
    return 0


def cmd_mem_import(args) -> int:
    """Restore a memory file into place (refuses to clobber without --force)."""
    import shutil
    src = Path(args.src)
    if not src.exists():
        _err(f"{BAD} no file to import at {src}")
        return 2
    db = Path(_mem_db(args))
    if db.exists() and not args.force:
        _err(f"{BAD} {db} already exists — pass --force to overwrite it")
        return 2
    db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, db)
    _p(f"{OK} imported {src} → {db}")
    return 0


def cmd_mem_burn(args) -> int:
    """Delete your memory file. Destructive — requires --yes."""
    db = Path(_mem_db(args))
    if not db.exists():
        _p(f"{db}  (already gone)")
        return 0
    if not args.yes:
        _err(f"{BAD} refusing to burn {db} without --yes (this permanently deletes "
             f"your memory)")
        return 2
    db.unlink()
    _p(f"{OK} burned your memory — {db} is gone")
    return 0


# --- figment golf: the compiler is the referee -------------------------------

def _load_figment(path_str: str):
    """Load a figment from a bare figment .json or a {figment: ...} listing."""
    from dreamlayer.reality_compiler.v2.figment import Figment
    d = json.loads(Path(path_str).read_text(encoding="utf-8"))
    if isinstance(d.get("figment"), dict):
        d = d["figment"]
    return Figment.from_dict(d)


def cmd_golf_verify(args) -> int:
    """Verify a figment against the sandbox budgets and score it per byte."""
    try:
        fig = _load_figment(args.path)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        _err(f"{BAD} not a figment: {exc}")
        return 2
    from dreamlayer.reality_compiler.v2.golf import referee
    r = referee(fig)
    if getattr(args, "json", False):
        _p(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    sc = r["score"]
    _p(f"{OK if r['ok'] else BAD} "
       f"{'BUDGETS OK' if r['ok'] else 'BUDGETS VIOLATED'}  "
       f"(display ≤{r['proof']['worst_display_hz']:g}Hz, "
       f"emit ≤{r['proof']['worst_emit_per_sec']:g}/s)")
    for v in r["violations"]:
        _p(f"  {BAD} {v}")
    _p(f"{ARROW} golf score {sc['golf_score']}  "
       f"(expressiveness {sc['expressiveness']} in {sc['bytes']} bytes)")
    _p(f"    scenes={sc['scenes']}  events={sc['distinct_events']}  "
       f"counters={sc['counters']}  pulses={sc['pulses']}  "
       f"emits={sc['emits']}  lines={sc['lines']}")
    return 0 if r["ok"] else 1


def cmd_pack_validate(args) -> int:
    """Run the sensory gate on an earcon/haptic pack (INNOVATION 1.5)."""
    try:
        pack = json.loads(Path(args.path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as exc:
        _err(f"{BAD} can't read pack: {exc}")
        return 2
    from dreamlayer.plugins.packs import validate_pack
    ok, reasons = validate_pack(pack)
    if ok:
        _p(f"{OK} pack '{pack.get('name','?')}' passes the sensory gate")
        return 0
    _p(f"{BAD} pack failed the sensory gate")
    for r in reasons:
        _p(f"  {BAD} {r}")
    return 1


def cmd_figment_safety(args) -> int:
    """Show a figment's proof-carrying safety card before you install it."""
    try:
        fig = _load_figment(args.path)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        _err(f"{BAD} not a figment: {exc}")
        return 2
    from dreamlayer.reality_compiler.v2.safety import render_text, safety_card
    card = safety_card(fig)
    if getattr(args, "json", False):
        _p(json.dumps(card, indent=2))
    else:
        _p(render_text(card))
    return 0 if card["ok"] else 1


def cmd_bench_perception(args) -> int:
    """The 350ms Club (INNOVATION 1.4): race a perceptor to name what it's
    looking at inside the Tier-0 glance budget. The deadline runner drops any
    answer over budget, so the score rewards being right *and* fast."""
    from dreamlayer.object_lens import bench
    if not bench.available():
        _err(f"{BAD} the perception bench needs numpy — install the 'perception' extra")
        return 2
    res = bench.run_perception_bench(deadline_ms=args.deadline)
    if getattr(args, "json", False):
        _p(json.dumps(res.as_dict(), indent=2))
        return 0
    _p(f"350ms Club — perception bench (budget {args.deadline:g}ms)")
    _p(f"  images     {res.n}")
    _p(f"  correct    {res.correct}/{res.n}  ({res.accuracy*100:.1f}%)")
    _p(f"  over budget {res.dropped}  (dropped, counted wrong)")
    _p(f"  latency    mean {res.mean_ms:.2f}ms · p95 {res.p95_ms:.2f}ms")
    _p(f"  {OK} score  {res.score:.4f}   (accuracy × how far under budget)")
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

    info = sub.add_parser("info", help="show a plugin's manifest + what it contributes")
    info.add_argument("path", nargs="?", default=".", help="plugin directory or package .json")
    info.add_argument("--json", action="store_true", help="machine-readable output")
    info.set_defaults(func=cmd_info)

    prev = sub.add_parser("preview", help="render the plugin's HUD card through the real device renderer")
    prev.add_argument("path", nargs="?", default=".", help="plugin directory or package .json")
    prev.add_argument("--card", help="sample card as JSON (else plugin.json preview_card, else default)")
    prev.add_argument("--shot", action="store_true", help="compose a 640×340 store banner")
    prev.add_argument("--scale", type=int, default=1, help="nearest-neighbour upscale for the 256px card")
    prev.add_argument("-o", "--output", help="output PNG (default: <name>-preview.png)")
    prev.set_defaults(func=cmd_preview)

    dev = sub.add_parser("dev", help="watch a plugin and re-check (+ reload) on every save")
    dev.add_argument("path", nargs="?", default=".", help="plugin directory (default: .)")
    dev.add_argument("--brain", help="reinstall to this Brain on each change")
    dev.add_argument("--token", help="Brain token (or set DREAMLAYER_TOKEN)")
    dev.add_argument("--interval", type=float, default=1.0, help="poll seconds (default: 1.0)")
    dev.add_argument("--once", action="store_true", help="run a single pass and exit")
    dev.set_defaults(func=cmd_dev)

    ls = sub.add_parser("list", help="list the registry catalogue or a Brain's installed plugins")
    ls.add_argument("--installed", action="store_true", help="list what a Brain is running")
    ls.add_argument("--entry-points", dest="entry_points", action="store_true",
                    help="list plugins advertised via importlib entry points")
    ls.add_argument("--brain", help="Brain base URL (or set DREAMLAYER_BRAIN)")
    ls.add_argument("--token", help="Brain token (or set DREAMLAYER_TOKEN)")
    ls.add_argument("--registry", help="path to a registry index.json")
    ls.set_defaults(func=cmd_list)

    # memories — your data is one file, and here is the SQL prompt over it
    mem = groups.add_parser("memories", help="browse your memory (it's just a file)")
    msub = mem.add_subparsers(dest="cmd")

    mpath = msub.add_parser("path", help="print where your memory file lives")
    mpath.add_argument("--db", help="memory sqlite path (or set DREAMLAYER_DB)")
    mpath.set_defaults(func=cmd_mem_path)

    mbrowse = msub.add_parser("browse", help="open your memory as a read-only, SQL-queryable web UI")
    mbrowse.add_argument("--db", help="memory sqlite path (or set DREAMLAYER_DB)")
    mbrowse.add_argument("--port", type=int, default=8001, help="local port (default: 8001)")
    mbrowse.add_argument("--print", dest="print_cmd", action="store_true",
                         help="print the launch command instead of serving")
    mbrowse.set_defaults(func=cmd_mem_browse)

    mexport = msub.add_parser("export", help="copy your memory file somewhere (it's yours)")
    mexport.add_argument("dest", help="destination path for the copy")
    mexport.add_argument("--db", help="memory sqlite path (or set DREAMLAYER_DB)")
    mexport.set_defaults(func=cmd_mem_export)

    mimport = msub.add_parser("import", help="restore a memory file into place")
    mimport.add_argument("src", help="the memory file to import")
    mimport.add_argument("--db", help="memory sqlite path (or set DREAMLAYER_DB)")
    mimport.add_argument("--force", action="store_true", help="overwrite an existing memory file")
    mimport.set_defaults(func=cmd_mem_import)

    mburn = msub.add_parser("burn", help="permanently delete your memory file")
    mburn.add_argument("--db", help="memory sqlite path (or set DREAMLAYER_DB)")
    mburn.add_argument("--yes", action="store_true", help="confirm the deletion")
    mburn.set_defaults(func=cmd_mem_burn)

    # golf — score a figment's expressiveness per byte; the compiler referees
    golf = groups.add_parser("golf", help="score a figment's expressiveness per byte (budgets are the referee)")
    gsub = golf.add_subparsers(dest="cmd")
    gv = gsub.add_parser("verify", help="verify a figment against the sandbox budgets and score it")
    gv.add_argument("path", help="a figment .json (bare figment, or a {figment: ...} listing)")
    gv.add_argument("--json", action="store_true", help="machine-readable output")
    gv.set_defaults(func=cmd_golf_verify)

    # figment — proof-carrying behaviors: see what an install CANNOT do
    fig = groups.add_parser("figment", help="inspect a figment (proof-carrying safety card)")
    fsub = fig.add_subparsers(dest="cmd")
    fs = fsub.add_parser("safety", help="show the safety card — what this behavior CANNOT do")
    fs.add_argument("path", help="a figment .json (bare figment, or a {figment: ...} listing)")
    fs.add_argument("--json", action="store_true", help="machine-readable output")
    fs.set_defaults(func=cmd_figment_safety)

    # packs — earcon/haptic packs: the store's sensory gate
    packs = groups.add_parser("packs", help="validate an earcon/haptic pack")
    psub = packs.add_subparsers(dest="cmd")
    pv = psub.add_parser("validate", help="run the sensory gate on a pack .json")
    pv.add_argument("path", help="a pack .json (name + haptics + earcons)")
    pv.set_defaults(func=cmd_pack_validate)

    # bench — race a perceptor inside the glance budget (the 350ms Club)
    bench = groups.add_parser("bench", help="benchmark perception against the glance budget")
    bsub = bench.add_subparsers(dest="cmd")
    bp = bsub.add_parser("perception", help="accuracy × latency under the 350ms glance deadline")
    bp.add_argument("--deadline", type=float, default=350.0,
                    help="glance budget in ms (default: 350)")
    bp.add_argument("--json", action="store_true", help="machine-readable output")
    bp.set_defaults(func=cmd_bench_perception)

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
