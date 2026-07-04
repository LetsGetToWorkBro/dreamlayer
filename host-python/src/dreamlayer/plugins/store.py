"""plugins/store.py — the marketplace client: browse, install, remove.

A `RegistryIndex` is the store catalogue — one JSON the website, the phone, and
the Mac panel all read (git-backed today; a hosted API later, same schema).
Each entry carries the social numbers CurseForge made familiar — downloads,
rating, comment count — plus the manifest bits a client needs to fetch and
verify a plugin.

`PluginStore` is the on-device half: search the index, **install** (fetch →
validate → write, and *refuse* if the gate fails), **remove**, and load what's
installed into a running orchestrator. Downloading is a seam (`fetch_fn`) so it
tests offline; the real one pulls the package from the entry's `url`.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

from .package import PluginPackage, PluginManifest
from .validate import validate, ValidationReport


@dataclass
class StoreEntry:
    name: str
    version: str
    author: str = ""
    description: str = ""
    homepage: str = ""
    url: str = ""                    # where the package is fetched from
    checksum: str = ""
    requires: tuple = ()
    tags: tuple = ()
    downloads: int = 0
    rating: float = 0.0             # 0..5, community average
    ratings_count: int = 0
    comments_count: int = 0
    # store display (the author's own detail page)
    long: tuple = ()                # paragraphs: how it helps you
    forwho: str = ""
    screenshot: str = ""            # image URL or data-URI

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requires"] = list(self.requires)
        d["tags"] = list(self.tags)
        d["long"] = list(self.long)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StoreEntry":
        d = dict(d or {})
        return cls(
            name=str(d.get("name", "")), version=str(d.get("version", "")),
            author=str(d.get("author", "")), description=str(d.get("description", "")),
            homepage=str(d.get("homepage", "")), url=str(d.get("url", "")),
            checksum=str(d.get("checksum", "")),
            requires=tuple(d.get("requires") or ()), tags=tuple(d.get("tags") or ()),
            downloads=int(d.get("downloads", 0) or 0),
            rating=float(d.get("rating", 0.0) or 0.0),
            ratings_count=int(d.get("ratings_count", 0) or 0),
            comments_count=int(d.get("comments_count", 0) or 0),
            long=tuple(d.get("long") or ()), forwho=str(d.get("forwho", "")),
            screenshot=str(d.get("screenshot", "")))


class RegistryIndex:
    def __init__(self, entries: Optional[list] = None):
        self.entries: list = list(entries or [])

    @classmethod
    def from_dict(cls, d: dict) -> "RegistryIndex":
        return cls([StoreEntry.from_dict(e) for e in (d or {}).get("plugins", [])])

    @classmethod
    def from_json(cls, text: str) -> "RegistryIndex":
        return cls.from_dict(json.loads(text or "{}"))

    def get(self, name: str) -> Optional[StoreEntry]:
        return next((e for e in self.entries if e.name == name), None)

    def search(self, query: str = "") -> list:
        q = (query or "").strip().lower()
        if not q:
            return list(self.entries)
        def hit(e):
            hay = " ".join([e.name, e.description, e.author, " ".join(e.tags)]).lower()
            return q in hay
        return [e for e in self.entries if hit(e)]

    def top(self, by: str = "downloads", n: int = 10) -> list:
        key = {"downloads": lambda e: e.downloads,
               "rating": lambda e: (e.rating, e.ratings_count),
               "comments": lambda e: e.comments_count}.get(by, lambda e: e.downloads)
        return sorted(self.entries, key=key, reverse=True)[:max(0, n)]


def load_plugin_object(package: PluginPackage):
    """Instantiate a *validated* package into a live plugin object (execs the
    payload). Only call this after validate() passed."""
    ns: dict = {"__name__": f"dreamlayer_plugin_{package.manifest.name}"}
    exec(compile(package.source, f"<plugin {package.manifest.name}>", "exec"), ns)
    return ns[package.manifest.factory]()


class PluginStore:
    """On-device install/remove, gated by validation. `install_dir` holds the
    packages the user has installed; `fetch_fn(url) -> package-json` downloads a
    package's manifest+source (the seam a real HTTP fetch fills)."""

    def __init__(self, install_dir, index: Optional[RegistryIndex] = None,
                 fetch_fn: Optional[Callable[[str], str]] = None,
                 host_capabilities=frozenset()):
        self.dir = Path(install_dir)
        self.index = index or RegistryIndex()
        self._fetch = fetch_fn
        self.host_capabilities = frozenset(host_capabilities)

    # -- what's installed ----------------------------------------------------

    def installed(self) -> list:
        if not self.dir.exists():
            return []
        return sorted(p.name for p in self.dir.iterdir()
                      if (p / "manifest.json").exists())

    def is_installed(self, name: str) -> bool:
        return (self.dir / name / "manifest.json").exists()

    # -- install / remove ----------------------------------------------------

    def _fetch_package(self, entry: StoreEntry) -> PluginPackage:
        if self._fetch is None:
            raise RuntimeError("no fetch_fn wired")
        raw = self._fetch(entry.url)
        d = json.loads(raw) if isinstance(raw, str) else raw
        return PluginPackage(manifest=PluginManifest.from_dict(d["manifest"]),
                             source=d["source"])

    def install(self, name: str) -> ValidationReport:
        """Fetch → validate → write. Refuses (returns the failing report,
        installs nothing) unless the gate passes clean."""
        entry = self.index.get(name)
        if entry is None:
            r = ValidationReport()
            r.add_error(f"'{name}' is not in the registry")
            return r
        try:
            package = self._fetch_package(entry)
        except Exception as e:
            r = ValidationReport()
            r.add_error(f"download failed: {e!r}")
            return r
        # the registry's advertised checksum must match what we fetched, too
        if entry.checksum and package.manifest.checksum != entry.checksum:
            r = ValidationReport()
            r.add_error("registry checksum does not match the fetched package")
            return r
        report = validate(package, self.host_capabilities)
        if report.ok:
            package.write(self.dir / package.manifest.name)
        return report

    def install_package(self, package: PluginPackage) -> ValidationReport:
        """Install a package you already hold (sideload). Same gate."""
        report = validate(package, self.host_capabilities)
        if report.ok:
            package.write(self.dir / package.manifest.name)
        return report

    def remove(self, name: str) -> bool:
        d = self.dir / name
        if d.exists():
            shutil.rmtree(d)
            return True
        return False

    # -- load installed into a running host ----------------------------------

    def load_installed(self, orchestrator) -> list:
        """Validate-then-load every installed plugin into the orchestrator.
        Re-validates on load (defence in depth), skips any that no longer pass.
        Returns the LoadResult from the orchestrator."""
        plugins = []
        for name in self.installed():
            try:
                package = PluginPackage.load(self.dir / name)
            except Exception:
                continue
            if not validate(package, self.host_capabilities).ok:
                continue                       # was fine at install, isn't now
            try:
                plugins.append(load_plugin_object(package))
            except Exception:
                continue
        return orchestrator.load_plugins(plugins)
