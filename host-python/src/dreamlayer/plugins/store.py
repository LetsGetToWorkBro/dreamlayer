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

from .package import PluginPackage, PluginManifest, sha256_of
from .validate import validate, ValidationReport

# The reviewed first-party catalogue is trusted in-process by CONTENT-HASH pin,
# not by a signing key. This is the label a hash-pinned first-party plugin loads
# under (mirrors validate.py's `report.publisher` for the signed path).
_FIRST_PARTY_PUBLISHER = "DreamLayer First-Party"


def load_first_party_pins() -> dict:
    """The shipped content-hash pins for the reviewed first-party catalogue
    (``plugins/first_party.json``): plugin name → ``"sha256:…"`` of its exact
    reviewed source. This is the runtime half of the curated-registry trust
    model — a first-party plugin loads in-process because its installed bytes
    match a hash we reviewed and shipped, with no private key to custody and no
    per-build secret to leak. Ships inside the package so a frozen Brain has it.

    Fail-safe: any problem (file absent, unreadable, malformed) returns ``{}`` so
    NOTHING is treated as first-party and every installed plugin routes to the
    isolation jail — the pin can only ever *grant* trust, never withhold the
    default-deny."""
    try:
        raw = json.loads((Path(__file__).with_name("first_party.json")).read_text())
        pins = raw.get("plugins", {})
        return {k: v for k, v in pins.items()
                if isinstance(k, str) and isinstance(v, str) and v.startswith("sha256:")}
    except Exception:
        return {}


@dataclass
class StoreEntry:
    name: str
    version: str
    author: str = ""
    official: bool = False          # published by the DreamLayer team
    api: str = "1"                  # plugin API version the manifest targets
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
    # pricing: a reserved, forward-compatible seam. Everything ships free today
    # ({"model":"free"}); a paid marketplace fills in model/price later.
    pricing: dict = field(default_factory=lambda: {"model": "free"})
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
        pricing = d.get("pricing")
        return cls(
            name=str(d.get("name", "")), version=str(d.get("version", "")),
            author=str(d.get("author", "")), official=bool(d.get("official", False)),
            api=str(d.get("api", "1") or "1"),
            description=str(d.get("description", "")),
            homepage=str(d.get("homepage", "")), url=str(d.get("url", "")),
            checksum=str(d.get("checksum", "")),
            requires=tuple(d.get("requires") or ()), tags=tuple(d.get("tags") or ()),
            downloads=int(d.get("downloads", 0) or 0),
            rating=float(d.get("rating", 0.0) or 0.0),
            ratings_count=int(d.get("ratings_count", 0) or 0),
            comments_count=int(d.get("comments_count", 0) or 0),
            pricing=dict(pricing) if isinstance(pricing, dict) else {"model": "free"},
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
                 host_capabilities=frozenset(),
                 trusted_keys: Optional[dict] = None,
                 first_party: Optional[dict] = None):
        self.dir = Path(install_dir)
        self.index = index or RegistryIndex()
        self._fetch = fetch_fn
        self.host_capabilities = frozenset(host_capabilities)
        # publisher name -> Ed25519 pubkey hex (registry/keys.json). When set,
        # any SIGNED package must be signed by a registered key; unsigned
        # packages stay curated-registry-trust (warning, not refusal).
        self.trusted_keys = trusted_keys
        # plugin name -> "sha256:…" content pin for the reviewed first-party
        # catalogue. A pinned plugin loads in-process cross-platform without a
        # kernel sandbox — the keyless half of the curated-registry trust model.
        # Default is EMPTY (no first-party trust) so a bare store is hermetic and
        # the grant is explicit at the wiring site: the Brain passes
        # first_party=load_first_party_pins() (server.py). Pass a dict to trust a
        # custom catalogue.
        self.first_party = dict(first_party or {})

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
        report = validate(package, self.host_capabilities,
                          trusted_keys=self.trusted_keys)
        if report.ok:
            package.write(self.dir / package.manifest.name)
        return report

    def install_package(self, package: PluginPackage) -> ValidationReport:
        """Install a package you already hold (sideload). Same gate."""
        report = validate(package, self.host_capabilities,
                          trusted_keys=self.trusted_keys)
        if report.ok:
            package.write(self.dir / package.manifest.name)
        return report

    def remove(self, name: str) -> bool:
        d = self.dir / name
        if d.exists():
            shutil.rmtree(d)
            return True
        return False

    # -- trust: reviewed first-party by content pin --------------------------

    def _first_party_publisher(self, package: PluginPackage) -> str:
        """The first-party publisher label if this package is a reviewed
        first-party plugin pinned by content hash, else "".

        The pin is checked against the sha256 of the ACTUAL installed source
        bytes (recomputed here), never the manifest's self-declared ``checksum``
        or ``official`` flag — both of which an attacker controls. So a
        look-alike that borrows a first-party *name* but ships different code
        hashes differently, misses the pin, and stays in the jail; and a genuine
        first-party plugin whose installed bytes were tampered with after
        install also misses the pin and is refused in-process trust.

        Scope (honest): the pinned source is a thin first-party connector that
        re-exports reviewed module code from the Brain's OWN package (its TCB),
        so the pin protects the installed package's integrity while the delegated
        module shares the Brain's integrity (editing it needs write access to the
        Brain's package = already a full compromise). These connectors load
        IN-PROCESS on the remotely-reachable world lens, so their human review is
        load-bearing — a request-controlled-URL bug in one is an in-process
        SSRF from the Brain host."""
        if not self.first_party:
            return ""
        want = self.first_party.get(package.manifest.name)
        if want and sha256_of(package.source) == want:
            return _FIRST_PARTY_PUBLISHER
        return ""

    # -- load installed into a running host ----------------------------------

    def load_installed(self, orchestrator, isolate: str = "untrusted",
                       require_sandbox: Optional[bool] = None) -> list:
        """Validate-then-load every installed plugin into the orchestrator.
        Re-validates on load (defence in depth), skips any that no longer pass.

        isolate="untrusted" (default): packages NOT signed by a trusted key run
        in a capability-mediated jail (WASM when a runtime is present, else the
        subprocess host in plugins/isolation.py) instead of the host; only their
        pure-data providers cross the jail. This is the secure default for
        user-installed third-party code — it never gets ambient authority on the
        host just for being installed. Two things earn in-process host authority,
        both anchored in what WE reviewed (never the package's own claims): a
        package signed by a REGISTERED publisher (a key in trusted_keys), or a
        reviewed FIRST-PARTY plugin whose installed source matches a content-hash
        pin in plugins/first_party.json. A self-signature alone earns nothing.
        The first-party pin is what lets the bundled connector plugins run
        in-process on Windows/Mac, where no kernel sandbox (bwrap/nsjail) exists;
        it is keyless, so there is no signing secret to custody or leak. (The
        on-glass Orchestrator.load_plugins path also loads reviewed first-party
        code in-process; this store path is what the remotely-reachable world
        lens uses, and it now trusts the same catalogue by pin.)
        isolate="trusted": everything runs in-process — the curated deployment
        where every installed package has been read and vouched for.

        Honest isolation posture (re-audit 2026-07): the subprocess jail confines
        by *process* + a thin RPC surface, but the child still executes the
        plugin's module code with the host user's OS authority *unless* a kernel
        sandbox (bwrap/nsjail) or the WASM tier wraps it. When neither is present
        the boundary silently degraded to "just a subprocess." Now it is loud:
        every degraded load is recorded to health + the capability log, exposed
        on `self.isolation_notices`, and — when `require_sandbox` is true
        (param, or env DL_REQUIRE_SANDBOX=1) — it FAILS CLOSED: the plugin is not
        loaded at all rather than run without the kernel boundary the deployment
        demanded.

        Isolation tiers, weakest→strongest: bare subprocess < subprocess + a
        kernel sandbox (bwrap/nsjail, os_sandbox.py) < the WASI subprocess tier
        (wasm_host.py) < the in-process Component-Model host (wasm_component_host.py,
        capability ``wasm_plugins``), which gives a WASM *guest* zero ambient
        authority and links only its declared capabilities. That strongest tier
        binds the WIT contract (plugins/dreamlayer.wit) and applies to WASM-guest
        packages; today's plugins ship Python module code, so this loader routes
        them through the subprocess/WASI tiers above — the component host is the
        forward path a `.wasm`-guest package format targets.

        Returns the in-process LoadResult; the isolated hosts are stored on
        `self.isolated` (call .stop() to reclaim)."""
        import os as _os
        if require_sandbox is None:
            require_sandbox = _os.environ.get("DL_REQUIRE_SANDBOX", "") == "1"
        plugins = []
        self.isolated = []
        self.isolation_notices: list = []      # degraded-posture load records
        for name in self.installed():
            try:
                package = PluginPackage.load(self.dir / name)
            except Exception:
                continue
            report = validate(package, self.host_capabilities,
                              trusted_keys=self.trusted_keys)
            if not report.ok:
                continue                       # was fine at install, isn't now
            # Trust to run IN-PROCESS (host authority + the real ctx) requires a
            # REGISTERED publisher — report.publisher is non-empty only when the
            # signature verifies against a key in trusted_keys. A mere valid
            # self-signature is NOT enough (audit 2026-07-14 CRITICAL): with
            # trusted_keys=None every self-signed package would otherwise earn
            # host authority and read the whole MemoryDB in-process. "Signed"
            # proves the author signed their own code; only an allowlisted key
            # proves *we* chose to trust it. trusted_keys=None therefore means
            # "trust nothing in-process" — everything unreviewed goes to the jail.
            # In-process host authority is earned two ways, both anchored in
            # something WE reviewed, never the package's own claims:
            #   1. report.publisher — a valid signature by a key in trusted_keys
            #      (registered third-party / owner-custodied signing).
            #   2. a first-party content-hash pin — the installed source bytes
            #      match plugins/first_party.json, the reviewed catalogue. This
            #      is what lets the bundled connector plugins run in-process on
            #      Windows/Mac, where no kernel sandbox (bwrap/nsjail) exists.
            # Everything else is untrusted and routes to the isolation jail.
            trusted_inproc = bool(report.publisher) or bool(self._first_party_publisher(package))
            if isolate == "untrusted" and not trusted_inproc:
                # unreviewed / not-registered → an isolation tier, not the host. Prefer
                # the WASM jail when a runtime is configured (no ambient
                # authority); else the capability-mediated subprocess jail.
                from .isolation import SubprocessPluginHost
                from . import wasm_host, os_sandbox
                is_wasm = wasm_host.available()
                Host = wasm_host.WasmPluginHost if is_wasm else SubprocessPluginHost
                pname = package.manifest.name
                health = getattr(orchestrator, "health", None)
                caplog = getattr(orchestrator, "capability_log", None)

                # Decide the isolation posture BEFORE launching anything: a bare
                # subprocess would run the plugin's module code with the host
                # user's OS authority. When require_sandbox is set and no kernel
                # boundary is available, we must not even start the child — fail
                # closed means the untrusted code never executes at all.
                kernel_boundary = is_wasm or bool(os_sandbox.available())
                if not kernel_boundary:
                    note = (f"plugin '{pname}' isolated by process only — no "
                            "OS/WASM sandbox present (no kernel boundary)")
                    self.isolation_notices.append(note)
                    if health is not None:
                        health.record_failure(f"plugin:{pname}", RuntimeError(note))
                    if caplog is not None:
                        caplog.record(pname, "degraded:no-os-sandbox")
                    if require_sandbox:
                        continue             # fail closed — never launch the child

                host = Host(self.dir / name, package.manifest.requires,
                            health=health, name=pname, caplog=caplog)
                try:
                    if host.start():
                        host.register_into(orchestrator)
                        self.isolated.append(host)
                        if caplog is not None:
                            caplog.grant(pname, package.manifest.requires)
                except Exception:
                    host.stop()
                continue
            try:
                plugins.append(load_plugin_object(package))
            except Exception:
                continue
        return orchestrator.load_plugins(plugins)
