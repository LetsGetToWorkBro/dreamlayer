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
import base64
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

API_VERSION = "1"                    # default a manifest gets if it omits `api`
SUPPORTED_API = frozenset({"1", "2"})  # v1 (register-only) and v2 (lifecycle+events)
# The SDK contract version this host implements (dreamlayer.sdk.__version__ reads
# it). A manifest may declare `min_sdk`; a plugin needing a newer SDK than the
# host provides is refused early with a clear message (see validate.sdk_supports).
SDK_VERSION = "1.0.0"


def _semver(v: str) -> tuple:
    """(major, minor, patch) ints from 'x.y.z' (pre-release/build ignored);
    a malformed version sorts as (0, 0, 0)."""
    core = re.split(r"[-+]", str(v or ""), 1)[0]
    parts = (core.split(".") + ["0", "0", "0"])[:3]
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


def sdk_supports(min_sdk: str, host_sdk: str = SDK_VERSION) -> bool:
    """True if a host at `host_sdk` satisfies a plugin's `min_sdk` requirement.
    An empty/absent requirement is always satisfied."""
    if not min_sdk:
        return True
    return _semver(host_sdk) >= _semver(min_sdk)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([\-+][0-9A-Za-z.\-]+)?$")
ENTRY_RE = re.compile(r"^[A-Za-z_][\w]*:[A-Za-z_][\w]*$")

# capabilities a plugin may request. A manifest asking for one outside this set
# is rejected — no undeclared reach.
KNOWN_CAPABILITIES = frozenset({
    "object_lens", "glance", "perception", "cards", "ring", "vision",
    # "knowledge": register a knowledge-answer tier the router consults for the
    # wearer's recall query text in EVERY mode. A plugin must declare it to
    # reach add_knowledge_brain (audit 2026-07-14 — the exfil vector was that
    # any plugin could register a brain fed the query and ship it off-device).
    "knowledge",
    # "memory": read the wearer's kept memories/commitments/places through the
    # capability-scoped, veil-gated PluginContext.memory facade. A plugin must
    # declare it to read anything back; the host grants it only deliberately
    # (the default orchestrator never does), so by default the facade refuses —
    # the fail-closed posture the audit 2026-07-14 CRITICAL asks for (the raw
    # MemoryDB must never be a plugin-facing surface).
    "memory",
    "mesh", "midi", "network", "fs", "shop",
    # DreamLayer Cloud entitlements (server.PLAN_CAPS["cloud"], docs/CLOUD.md).
    # Declarable by any manifest; GRANTED only on a cloud-plan Brain — a plugin
    # that requires one simply doesn't load on the free plan, the same skip as
    # any other missing capability. Union-only: free plugins are unaffected.
    "cloud_ai", "cloud_sync", "cloud_relay",
})


def sha256_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class PluginManifest:
    name: str
    version: str
    entry: str                       # "module:factory"
    author: str = ""
    official: bool = False           # published by the DreamLayer team
    description: str = ""             # one-line summary
    homepage: str = ""
    requires: tuple = ()             # capability names
    api: str = API_VERSION
    min_sdk: str = ""                # lowest dreamlayer.sdk version this needs
    # pricing: a reserved, forward-compatible seam. Free today ({"model":"free"});
    # a paid marketplace fills in model/price/currency later. No payment code
    # ships against it yet.
    pricing: dict = field(default_factory=lambda: {"model": "free"})
    # Which host runs the payload:
    #   "python" — a module + factory (the original, and still the default)
    #   "wasm"   — a WebAssembly guest in wasm_component_host, in-process with
    #              zero ambient authority and its declared capabilities linked
    #   "extism" — the same `.wasm` under the Extism runtime, which links NO
    #              host functions at all: incapable rather than inspected
    # It is in `signing_payload` because flipping it changes WHICH HOST RUNS THE
    # CODE — an attacker who could retag a signed package would be choosing the
    # sandbox, which is the same as choosing no sandbox.
    kind: str = "python"
    checksum: str = ""               # sha256 of the code payload
    signature: str = ""              # Ed25519 author signature over the code payload
    pubkey: str = ""                 # author's Ed25519 public key, hex
    # -- store display (optional; authors ship these so the detail view is
    #    theirs, not the store's) ------------------------------------------
    long: tuple = ()                 # paragraphs: how it helps you
    forwho: str = ""                 # a short "who it's for"
    screenshot: str = ""             # image URL or data-URI for a preview

    # -- (de)serialise -------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requires"] = list(self.requires)
        d["long"] = list(self.long)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PluginManifest":
        d = dict(d or {})
        return cls(
            name=str(d.get("name", "")),
            version=str(d.get("version", "")),
            entry=str(d.get("entry", "")),
            author=str(d.get("author", "")),
            official=bool(d.get("official", False)),
            description=str(d.get("description", "")),
            homepage=str(d.get("homepage", "")),
            requires=tuple(d.get("requires") or ()),
            api=str(d.get("api", API_VERSION)),
            min_sdk=str(d.get("min_sdk", "")),
            pricing=(dict(d["pricing"]) if isinstance(d.get("pricing"), dict)
                     else {"model": "free"}),
            # A manifest with no `kind` is a Python package — every one
            # written before this field existed. Defaulting the OTHER way would
            # send an old package to a wasm host that cannot run it.
            kind=str(d.get("kind") or "python"),
            checksum=str(d.get("checksum", "")),
            signature=str(d.get("signature", "")),
            pubkey=str(d.get("pubkey", "")),
            long=tuple(d.get("long") or ()),
            forwho=str(d.get("forwho", "")),
            screenshot=str(d.get("screenshot", "")),
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
        if self.api not in SUPPORTED_API:
            out.append(f"unsupported api {self.api!r} "
                       f"(this host speaks {sorted(SUPPORTED_API)})")
        unknown = [c for c in self.requires if c not in KNOWN_CAPABILITIES]
        if unknown:
            out.append("unknown capabilities: " + ", ".join(map(str, unknown)))
        if not self.checksum.startswith("sha256:"):
            out.append("missing or malformed checksum")
        return out

    @property
    def _kind(self) -> str:
        return (self.kind or "python").strip().lower()

    @property
    def is_wasm(self) -> bool:
        """A guest for the in-process Component-Model host."""
        return self._kind == "wasm"

    @property
    def is_extism(self) -> bool:
        """A guest for the Extism runtime — the same `.wasm` on disk, a
        different sandbox and a different ABI. Kept as a separate `kind` rather
        than a flag beside `wasm`, because the two are not interchangeable: an
        Extism guest imports `extism:host/env` and would fail to instantiate in
        the component host, and a component guest expects `(ptr, len)` in and a
        length back where Extism hands the PDK bytes."""
        return self._kind == "extism"

    @property
    def carries_wasm(self) -> bool:
        """True when the payload on disk is a `.wasm` binary, whichever runtime
        runs it. This is what the format cares about; `is_wasm`/`is_extism` are
        what the LOADER cares about."""
        return self.is_wasm or self.is_extism

    @property
    def module(self) -> str:
        """The payload's basename on disk — `<module>.py` or `<module>.wasm`."""
        return self.entry.split(":", 1)[0]

    @property
    def factory(self) -> str:
        """Python: the factory callable. WASM: the exported entry function.

        Same field, because it answers the same question — "what does the host
        call?" — and keeping one field means `signing_payload` covers both
        without a second security-relevant name to remember.
        """
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

    # -- author signing -------------------------------------------------------

    @property
    def signed(self) -> bool:
        return bool(self.manifest.signature and self.manifest.pubkey)

    def signing_payload(self) -> dict:
        """The canonical bytes the author signature covers. It binds the code
        (via its sha256) *and* the security-relevant manifest fields — so an
        attacker who takes a signed package and widens its ``requires`` or
        redirects its ``entry`` invalidates the signature, not just one who
        edits the code. Store-detail copy (long/forwho/screenshot/description)
        is deliberately excluded, so authors can revise their write-up without
        re-signing."""
        m = self.manifest
        return {
            "name": m.name,
            "version": m.version,
            "entry": m.entry,
            "api": m.api,
            "min_sdk": m.min_sdk,
            "requires": sorted(m.requires),
            "kind": m.kind,
            "source_sha256": sha256_of(self.source),
        }

    def sign_with(self, signer) -> "PluginPackage":
        """Stamp the author's Ed25519 signature + public key over
        ``signing_payload()`` (the code hash + the security-relevant manifest
        fields). `signer` is a reality_compiler.sign_crypto.Signer holding the
        author's seed; it must have a real keypair (the HMAC fallback has no
        public half and would produce an unverifiable package)."""
        pub = getattr(signer, "public_key_hex", "")
        if not pub:
            raise ValueError(
                "author signing needs Ed25519 (install the 'privacy' extra); "
                "the HMAC fallback cannot produce a publishable public key")
        self.manifest.signature = signer.sign(self.signing_payload())
        self.manifest.pubkey = pub
        return self

    # -- disk round-trip -----------------------------------------------------

    # A wasm payload is BINARY, and `source` is text — so it round-trips as
    # base64. That keeps every existing invariant exactly as it was: the
    # checksum still covers `source`, `signing_payload` still hashes `source`,
    # and base64 is injective, so binding the text binds the bytes. The
    # alternative — a second binary field — would have meant a second checksum
    # rule and a second thing for a signature to miss.

    @classmethod
    def load(cls, directory) -> "PluginPackage":
        d = Path(directory)
        manifest = PluginManifest.from_dict(json.loads((d / "manifest.json").read_text()))
        if manifest.carries_wasm:
            raw = (d / f"{manifest.module}.wasm").read_bytes()
            source = base64.b64encode(raw).decode("ascii")
        else:
            source = (d / f"{manifest.module}.py").read_text()
        return cls(manifest=manifest, source=source)

    def write(self, directory) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps(self.manifest.to_dict(), indent=2))
        if self.manifest.carries_wasm:
            (d / f"{self.manifest.module}.wasm").write_bytes(self.wasm_bytes())
        else:
            (d / f"{self.manifest.module}.py").write_text(self.source)
        return d

    def wasm_bytes(self) -> bytes:
        """The guest module. Raises for a Python package rather than returning
        something a wasm host would then fail on obscurely."""
        if not self.manifest.carries_wasm:
            raise ValueError(f"{self.manifest.name!r} is a python package")
        try:
            return base64.b64decode(self.source, validate=True)
        except Exception as exc:
            raise ValueError(
                f"{self.manifest.name!r} carries an unreadable wasm payload") from exc

    @classmethod
    def build(cls, *, name, version, entry, source, author="", description="",
              homepage="", requires=(), signature="", kind="python",
              long=(), forwho="", screenshot="") -> "PluginPackage":
        """Make a package from source, stamping the checksum for you (authoring
        helper — a real publish tool would sign here too). `long`/`forwho`/
        `screenshot` are the author's own store-detail copy; they ride in the
        manifest but *not* the checksum (which covers the code payload only), so
        an author can revise their write-up without re-signing the code."""
        m = PluginManifest(name=name, version=version, entry=entry, author=author,
                           description=description, homepage=homepage, kind=kind,
                           requires=tuple(requires), checksum=sha256_of(source),
                           signature=signature, long=tuple(long), forwho=forwho,
                           screenshot=screenshot)
        return cls(manifest=m, source=source)

    @classmethod
    def build_wasm(cls, *, name, version, entry, wasm: bytes, kind="wasm",
                   **kw) -> "PluginPackage":
        """Authoring helper for a WASM guest. `entry` is `"<module>:<export>"` —
        the basename it lands on disk as, and the function the host calls.
        `kind="extism"` builds the same payload for the Extism runtime."""
        return cls.build(name=name, version=version, entry=entry, kind=kind,
                         source=base64.b64encode(wasm).decode("ascii"), **kw)
