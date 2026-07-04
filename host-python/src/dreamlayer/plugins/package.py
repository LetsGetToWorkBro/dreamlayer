"""plugins/package.py — the distributable unit of a plugin.

A published plugin is a **manifest + a code payload**. The manifest is the
label on the tin — who wrote it, what it needs, and a checksum of the code so
tampering is detectable. The payload is one Python module that exposes a
`register(ctx)` factory (the same shape `plugins/base.py` already loads).

    manifest.json
      {
        "name": "face-synth",
        "version": "0.1.0",
        "entry": "plugin:face_synth_plugin",   # module:factory
        "author": "you",
        "requires": ["midi"],                    # capabilities it asks for
        "api": "1",
        "checksum": "sha256:…"                   # of plugin.py, integrity
      }
    plugin.py         # the code

Nothing here executes code — that's the validation gate's job (validate.py).
This module only *describes and integrity-checks* a package, so a store can
list it and a client can verify it before ever importing it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

API_VERSION = "1"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([\-+][0-9A-Za-z.\-]+)?$")
ENTRY_RE = re.compile(r"^[A-Za-z_][\w]*:[A-Za-z_][\w]*$")

# capabilities a plugin may request. A manifest asking for one outside this set
# is rejected — no undeclared reach.
KNOWN_CAPABILITIES = frozenset({
    "object_lens", "glance", "perception", "cards", "ring", "vision",
    "mesh", "midi", "network", "fs",
})


def sha256_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class PluginManifest:
    name: str
    version: str
    entry: str                       # "module:factory"
    author: str = ""
    description: str = ""
    homepage: str = ""
    requires: tuple = ()             # capability names
    api: str = API_VERSION
    checksum: str = ""               # sha256 of the code payload
    signature: str = ""              # author signature (reserved; verified later)

    # -- (de)serialise -------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requires"] = list(self.requires)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PluginManifest":
        d = dict(d or {})
        return cls(
            name=str(d.get("name", "")),
            version=str(d.get("version", "")),
            entry=str(d.get("entry", "")),
            author=str(d.get("author", "")),
            description=str(d.get("description", "")),
            homepage=str(d.get("homepage", "")),
            requires=tuple(d.get("requires") or ()),
            api=str(d.get("api", API_VERSION)),
            checksum=str(d.get("checksum", "")),
            signature=str(d.get("signature", "")),
        )

    # -- shape validation (no code runs) -------------------------------------

    def problems(self) -> list:
        """Everything wrong with the *manifest* itself — names, versions,
        capabilities, api. Integrity (checksum vs code) is checked in validate."""
        out = []
        if not NAME_RE.match(self.name or ""):
            out.append(f"bad name: {self.name!r} (lowercase, digits, hyphens)")
        if not VERSION_RE.match(self.version or ""):
            out.append(f"bad version: {self.version!r} (expected semver x.y.z)")
        if not ENTRY_RE.match(self.entry or ""):
            out.append(f"bad entry: {self.entry!r} (expected module:factory)")
        if self.api != API_VERSION:
            out.append(f"unsupported api {self.api!r} (this host speaks {API_VERSION})")
        unknown = [c for c in self.requires if c not in KNOWN_CAPABILITIES]
        if unknown:
            out.append("unknown capabilities: " + ", ".join(map(str, unknown)))
        if not self.checksum.startswith("sha256:"):
            out.append("missing or malformed checksum")
        return out

    @property
    def module(self) -> str:
        return self.entry.split(":", 1)[0]

    @property
    def factory(self) -> str:
        return self.entry.split(":", 1)[1]


@dataclass
class PluginPackage:
    """A manifest paired with its code payload (kept as text; nothing imports
    it here). Load from a directory (manifest.json + <module>.py) or build in
    memory for tests."""
    manifest: PluginManifest
    source: str                      # the code payload, verbatim

    def checksum_ok(self) -> bool:
        return bool(self.manifest.checksum) and \
            sha256_of(self.source) == self.manifest.checksum

    # -- disk round-trip -----------------------------------------------------

    @classmethod
    def load(cls, directory) -> "PluginPackage":
        d = Path(directory)
        manifest = PluginManifest.from_dict(json.loads((d / "manifest.json").read_text()))
        source = (d / f"{manifest.module}.py").read_text()
        return cls(manifest=manifest, source=source)

    def write(self, directory) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps(self.manifest.to_dict(), indent=2))
        (d / f"{self.manifest.module}.py").write_text(self.source)
        return d

    @classmethod
    def build(cls, *, name, version, entry, source, author="", description="",
              homepage="", requires=(), signature="") -> "PluginPackage":
        """Make a package from source, stamping the checksum for you (authoring
        helper — a real publish tool would sign here too)."""
        m = PluginManifest(name=name, version=version, entry=entry, author=author,
                           description=description, homepage=homepage,
                           requires=tuple(requires), checksum=sha256_of(source),
                           signature=signature)
        return cls(manifest=m, source=source)
