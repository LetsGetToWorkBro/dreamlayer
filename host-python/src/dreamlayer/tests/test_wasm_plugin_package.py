"""The `.wasm` package format, end to end: author → gate → store → the glass.

`wasm_plugins` was dormant not for want of a runtime — wasmtime has been
installed and `WasmCapabilityHost` has enforced capabilities for months — but
because nothing could REACH it. Three separate gaps, each of which alone kept
the strongest isolation tier unreachable:

  1. There was no package format. `store.load_installed` routed on
     `wasm_host.available()` (the *subprocess* WASI tier) and never asked
     whether the package itself was a guest.
  2. The gate refused every wasm package it was handed. A `.wasm` payload rides
     in `source` as base64, `scan_source` parsed base64 as Python, and the
     answer was always `syntax error: cannot assign to expression`.
  3. The host could not pass a guest a string. `log`, which the WIT calls "the
     minimum a plugin needs to speak to the host at all", received two integers
     and had no way to read the bytes they pointed at.

So these tests are deliberately layered: the binary reader, the format, the
gate, guest memory, and finally one package that goes all the way from
`build_wasm` to a `PanelRow` on the object lens — because each layer working
alone is exactly the condition that held before, and it added up to nothing.
"""
import json

import pytest

wasmtime = pytest.importorskip("wasmtime")

from dreamlayer.plugins import wasm_scan                          # noqa: E402
from dreamlayer.plugins.package import PluginManifest, PluginPackage  # noqa: E402
from dreamlayer.plugins.store import PluginStore                  # noqa: E402
from dreamlayer.plugins.validate import scan_wasm, validate       # noqa: E402
from dreamlayer.plugins.wasm_component_host import (              # noqa: E402
    ALWAYS_GRANTED, MemoryOutOfBounds, MemoryUnavailable, WasmCapabilityHost,
    capability_of_function, granted_interfaces, needs_memory,
)
from dreamlayer.plugins.wasm_plugin_host import (                 # noqa: E402
    ALLOC_EXPORT, MAX_ROWS, RESPONSE_CAP, WasmComponentPluginHost,
)

ROWS = {"rows": [{"label": "from wasm", "detail": "zero ambient authority"}]}


def _wat_escape(text: str) -> str:
    """WAT string literal — everything outside printable ASCII as \\hh."""
    return "".join(c if 32 <= ord(c) < 127 and c not in '"\\'
                   else "\\%02x" % ord(c) for c in text)


def guest_wat(response=None, *, imports=(), calls=(), ret=None,
              memory=True, alloc=True, build="dl_build"):
    """A guest implementing the ABI, parameterised by every way it can go wrong.

    The canned response is copied over the request buffer in place and its
    length returned — the ABI in one instruction sequence, which is the point:
    a plugin author does not need a toolchain to write one.
    """
    body = json.dumps(ROWS if response is None else response,
                      separators=(",", ":"))
    n = len(body.encode("utf-8"))
    ret = n if ret is None else ret
    parts = []
    for mod, field, n_params, result in imports:
        params = f'(param {" ".join(["i32"] * n_params)})' if n_params else ""
        parts.append(f'(import "{mod}" "{field}" '
                     f'(func ${field} {params}{result}))')
    # The buffer the host is handed lives at 4096 and may run RESPONSE_CAP
    # long; the canned reply sits above it so a large reply cannot clobber the
    # very bytes it is about to copy from.
    return f"""(module
  {chr(10).join(parts)}
  {'(memory (export "memory") 1)' if memory else '(memory 1)'}
  (data (i32.const 32768) "{_wat_escape(body)}")
  {f'(func (export "{ALLOC_EXPORT}") (param i32) (result i32) i32.const 4096)'
   if alloc else ''}
  (func (export "{build}") (param $ptr i32) (param $len i32) (param $cap i32)
        (result i32)
    {chr(10).join(calls)}
    local.get $ptr i32.const 32768 i32.const {n} memory.copy
    i32.const {ret}))"""


def guest(**kw) -> bytes:
    return bytes(wasmtime.wat2wasm(guest_wat(**kw)))


LOG_IMPORT = ("dreamlayer", "log", 2, "")
NET_IMPORT = ("dreamlayer", "net_get", 1, " (result i32)")
CARDS_IMPORT = ("dreamlayer", "show_card", 2, "")


def package(*, wasm=None, requires=("object_lens",), entry="demo:dl_build",
            name="wasm-demo", **kw) -> PluginPackage:
    return PluginPackage.build_wasm(name=name, version="1.0.0", entry=entry,
                                    wasm=guest(**kw) if wasm is None else wasm,
                                    requires=requires)


# ---------------------------------------------------------------- the reader

class TestBinaryReader:
    """`wasm_scan` reads imports and exports with no runtime, because the gate
    runs at install time on machines that have no runtime installed."""

    def test_reads_imports_and_exports_of_a_real_module(self):
        payload = guest(imports=[LOG_IMPORT],
                        calls=["local.get $ptr local.get $len call $log"])
        assert wasm_scan.module_imports(payload) == [("dreamlayer", "log")]
        names = {n for n, _ in wasm_scan.module_exports(payload)}
        assert {"memory", ALLOC_EXPORT, "dl_build"} <= names

    def test_a_module_importing_nothing_reads_as_no_imports(self):
        assert wasm_scan.module_imports(guest()) == []

    def test_bad_magic_is_refused(self):
        with pytest.raises(wasm_scan.MalformedModule) as ei:
            wasm_scan.module_imports(b"NOPE\x01\x00\x00\x00")
        assert "not a WebAssembly module" in str(ei.value)

    def test_unsupported_version_is_refused(self):
        with pytest.raises(wasm_scan.MalformedModule) as ei:
            wasm_scan.module_imports(b"\0asm\x63\x00\x00\x00")
        assert "unsupported WebAssembly version" in str(ei.value)

    def test_a_truncated_module_raises_rather_than_reading_short(self):
        payload = guest(imports=[LOG_IMPORT],
                        calls=["local.get $ptr local.get $len call $log"])
        with pytest.raises(wasm_scan.MalformedModule):
            wasm_scan.module_imports(payload[:12])       # cut mid-section

    def test_a_truncation_never_understates_what_a_guest_imports(self):
        # The hazard a section-at-a-time reader has: a module cut short BEFORE
        # its import section parses cleanly and reads as "imports nothing" — a
        # short read reported as a clean bill of health. The format carries no
        # total length, so that prefix is indistinguishable from a genuinely
        # tiny module; the answer is not "detect the truncation" but "never
        # report fewer imports than the bytes you were given contain".
        #
        # Swept over every prefix. Most are refused outright (no exports yet, or
        # a section cut mid-way); the ones that pass are prefixes carrying the
        # whole import section, and they must still name the import. A prefix
        # that dropped the import while keeping the exports would pass the gate
        # while hiding the guest's reach — that is what this pins.
        want = ("memory", ALLOC_EXPORT, "dl_build")
        payload = guest(imports=[NET_IMPORT],
                        calls=["i32.const 1 call $net_get drop"])
        refused = clean = 0
        for cut in range(len(payload) + 1):
            if scan_wasm(payload[:cut], ("network",), expect_exports=want):
                refused += 1
            else:
                assert wasm_scan.module_imports(payload[:cut]) == [
                    ("dreamlayer", "net_get")]
                clean += 1
        assert refused and clean                 # neither branch is vacuous

    def test_an_overlong_leb128_is_refused_rather_than_looped_on(self):
        # Section id 2, then a length whose continuation bit never clears. An
        # unbounded shift loop is how a parser becomes the bug it prevents.
        payload = b"\0asm\x01\x00\x00\x00" + b"\x02" + b"\xff" * 8
        with pytest.raises(wasm_scan.MalformedModule) as ei:
            wasm_scan.module_imports(payload)
        assert "LEB128" in str(ei.value) or "truncated" in str(ei.value)

    def test_an_unknown_import_kind_is_refused_not_skipped(self):
        # imports: count 1, module "a", field "b", kind 0x09 (no such externkind)
        body = b"\x01\x01a\x01b\x09"
        payload = (b"\0asm\x01\x00\x00\x00" + b"\x02"
                   + bytes([len(body)]) + body)
        with pytest.raises(wasm_scan.MalformedModule) as ei:
            wasm_scan.module_imports(payload)
        assert "unknown import kind" in str(ei.value)


# ---------------------------------------------------------------- the format

class TestPackageFormat:
    def test_round_trips_to_identical_bytes(self, tmp_path):
        pkg = package()
        pkg.write(tmp_path)
        assert PluginPackage.load(tmp_path).wasm_bytes() == pkg.wasm_bytes()

    def test_the_payload_lands_as_dot_wasm_not_dot_py(self, tmp_path):
        package().write(tmp_path)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["demo.wasm",
                                                              "manifest.json"]

    def test_kind_is_in_the_signing_payload(self):
        pkg = package()
        assert pkg.signing_payload()["kind"] == "wasm"

    def test_retagging_a_signed_package_changes_what_was_signed(self):
        # Flipping `kind` chooses WHICH HOST RUNS THE CODE. If it were outside
        # the signed payload, an attacker holding a signed package could pick
        # the sandbox — which is the same as picking no sandbox.
        pkg = package()
        before = pkg.signing_payload()
        pkg.manifest.kind = "python"
        assert pkg.signing_payload() != before

    def test_a_manifest_with_no_kind_is_a_python_package(self):
        # Every manifest written before this field existed. Defaulting the
        # other way would send them all to a host that cannot run them.
        m = PluginManifest.from_dict({"name": "old", "version": "1.0.0",
                                      "entry": "plugin:plugin"})
        assert m.kind == "python" and m.is_wasm is False

    def test_kind_survives_a_manifest_round_trip(self, tmp_path):
        # The bug this pins: `from_dict` dropped `kind`, so a reloaded wasm
        # package looked like Python and the loader went looking for demo.py.
        package().write(tmp_path)
        assert PluginPackage.load(tmp_path).manifest.is_wasm is True

    def test_wasm_bytes_refuses_a_python_package(self):
        pkg = PluginPackage.build(name="p", version="1.0.0",
                                  entry="plugin:plugin", source="x = 1\n")
        with pytest.raises(ValueError) as ei:
            pkg.wasm_bytes()
        assert "python package" in str(ei.value)

    def test_an_unreadable_payload_is_named_not_swallowed(self):
        pkg = package()
        pkg.source = "not base64 !!!"
        with pytest.raises(ValueError) as ei:
            pkg.wasm_bytes()
        assert "unreadable wasm payload" in str(ei.value)

    def test_the_checksum_still_covers_the_payload(self):
        pkg = package()
        assert pkg.checksum_ok()
        pkg.source = pkg.source[:-8] + "AAAAAAAA"
        assert not pkg.checksum_ok()

    def test_a_python_package_is_unaffected(self, tmp_path):
        pkg = PluginPackage.build(name="p", version="1.0.0",
                                  entry="plugin:plugin", source="x = 1\n")
        pkg.write(tmp_path)
        assert (tmp_path / "plugin.py").read_text() == "x = 1\n"
        assert PluginPackage.load(tmp_path).manifest.is_wasm is False


# ------------------------------------------------------------------- the gate

CAPS = frozenset({"object_lens", "network", "cards"})


class TestTheGate:
    def test_a_clean_guest_passes(self):
        assert validate(package(), CAPS).ok

    def test_base64_is_no_longer_scanned_as_python(self):
        # The regression that made every wasm package uninstallable: base64 is
        # not Python, so step 3 answered `syntax error` for all of them.
        report = validate(package(), CAPS)
        assert not any("syntax error" in e for e in report.errors)

    def test_a_guest_reaching_past_its_manifest_is_refused(self):
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"],
                      requires=("object_lens",))
        report = validate(pkg, CAPS)
        assert not report.ok
        # The message names the word the AUTHOR would have to write in their
        # manifest (`network`), not the WIT interface name (`net`).
        assert any("requires:[network]" in e for e in report.errors)

    def test_declaring_it_lets_the_same_guest_through(self):
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"],
                      requires=("object_lens", "network"))
        assert validate(pkg, CAPS).ok

    def test_an_import_outside_the_host_namespace_is_refused(self):
        pkg = package(imports=[("env", "sneaky", 0, "")], calls=["call $sneaky"])
        report = validate(pkg, CAPS)
        assert any("outside the host surface" in e for e in report.errors)

    def test_an_unknown_host_function_is_refused(self):
        pkg = package(imports=[("dreamlayer", "bogus", 0, "")],
                      calls=["call $bogus"])
        report = validate(pkg, CAPS)
        assert any("unknown host function" in e for e in report.errors)

    def test_a_guest_with_no_memory_is_refused_by_name(self):
        report = validate(package(memory=False), CAPS)
        assert any("exports no 'memory'" in e for e in report.errors)

    def test_a_guest_with_no_allocator_is_refused_by_name(self):
        report = validate(package(alloc=False), CAPS)
        assert any(f"exports no '{ALLOC_EXPORT}'" in e for e in report.errors)

    def test_a_guest_missing_the_export_its_manifest_names_is_refused(self):
        pkg = package(build="something_else")
        report = validate(pkg, CAPS)
        assert any("exports no 'dl_build'" in e for e in report.errors)

    def test_a_malformed_payload_is_refused_not_skipped(self):
        pkg = package(wasm=b"\0asm\x01\x00\x00\x00\x02\xff")
        report = validate(pkg, CAPS)
        assert not report.ok
        assert any("not a usable WebAssembly module" in e for e in report.errors)

    def test_an_unreadable_payload_fails_the_gate(self):
        pkg = package()
        pkg.source = "not base64 !!!"
        pkg.manifest.checksum = __import__(
            "dreamlayer.plugins.package", fromlist=["sha256_of"]
        ).sha256_of(pkg.source)          # honest checksum, unusable payload
        assert not validate(pkg, CAPS).ok

    def test_log_needs_no_declaration(self):
        # The one interface that carries no authority — the host writes its own
        # line and never the guest's bytes — so a guest may always speak.
        pkg = package(imports=[LOG_IMPORT],
                      calls=["local.get $ptr local.get $len call $log"],
                      requires=())
        assert validate(pkg, CAPS).ok
        assert "log" in granted_interfaces(())

    def test_capability_names_translate_both_ways(self):
        assert granted_interfaces(("network",)) == set(ALWAYS_GRANTED) | {"net"}
        assert capability_of_function("net_get") == "network"
        assert capability_of_function("show_card") == "cards"
        assert capability_of_function("nope") == ""

    def test_requires_the_guest_cannot_use_are_ignored_not_fatal(self):
        # `requires` is one field shared with Python packages, so it carries
        # names that mean nothing to a guest.
        assert granted_interfaces(("object_lens", "glance")) == set(ALWAYS_GRANTED)

    def test_smoke_instantiates_the_guest(self):
        assert validate(package(), CAPS, run_smoke=True).ok

    def test_smoke_catches_a_guest_that_cannot_instantiate(self):
        # A module whose import the linker will not define — caught by the
        # runtime's own parser, the check `scan_wasm` mirrors statically.
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"],
                      requires=("object_lens",))
        from dreamlayer.plugins.validate import _smoke_wasm
        assert _smoke_wasm(pkg) and "instantiate" in _smoke_wasm(pkg)[0]

    def test_scan_wasm_is_clean_for_a_well_formed_guest(self):
        assert scan_wasm(package().wasm_bytes(), ("object_lens",),
                         expect_exports=("memory", ALLOC_EXPORT,
                                         "dl_build")) == []


# --------------------------------------------------------------- guest memory

class TestGuestMemory:
    """The host could not read a `(ptr, len)` at all, so the two string-passing
    capabilities of the four could not carry anything."""

    def _host(self, impls=None, **kw):
        h = WasmCapabilityHost(guest(**kw), granted=["log", "cards"],
                               impls=impls or {})
        h.instantiate()
        return h

    def test_the_host_reads_what_the_guest_wrote(self):
        seen = []
        pkg_wasm = guest(imports=[LOG_IMPORT],
                         calls=["local.get $ptr local.get $len call $log"])
        h = WasmCapabilityHost(
            pkg_wasm, granted=["log"],
            impls={"log": needs_memory(
                lambda host, p, n: seen.append(host.read_str(p, n)))})
        h.instantiate()
        ptr = h.call(ALLOC_EXPORT, RESPONSE_CAP)
        h.write_mem(ptr, b'{"label":"mug"}')
        h.call("dl_build", ptr, 15, RESPONSE_CAP)
        assert seen == ['{"label":"mug"}']

    def test_needs_memory_is_opt_in(self):
        # An impl's arity is not a reliable signal — a `log` impl legitimately
        # takes two ints — so an unmarked impl must keep the signature it had.
        seen = []
        h = WasmCapabilityHost(
            guest(imports=[LOG_IMPORT],
                  calls=["local.get $ptr local.get $len call $log"]),
            granted=["log"], impls={"log": lambda p, n: seen.append((p, n))})
        h.instantiate()
        h.call("dl_build", 4096, 3, RESPONSE_CAP)
        assert seen == [(4096, 3)]

    def test_a_span_past_the_end_is_refused(self):
        h = self._host()
        size = h.memory().data_len(h.store)
        with pytest.raises(MemoryOutOfBounds) as ei:
            h.read_mem(size - 4, 4096)
        assert "runs past guest memory" in str(ei.value)

    def test_a_negative_span_is_refused(self):
        with pytest.raises(MemoryOutOfBounds):
            self._host().read_mem(-1, 4)

    def test_a_write_past_the_end_is_refused(self):
        h = self._host()
        size = h.memory().data_len(h.store)
        with pytest.raises(MemoryOutOfBounds):
            h.write_mem(size - 2, b"four")

    def test_a_guest_exporting_no_memory_cannot_be_read(self):
        h = WasmCapabilityHost(guest(memory=False), granted=["log"])
        h.instantiate()
        assert h.memory() is None
        with pytest.raises(MemoryUnavailable):
            h.read_mem(0, 1)

    def test_reading_before_instantiate_is_refused(self):
        h = WasmCapabilityHost(guest(), granted=["log"])
        with pytest.raises(MemoryUnavailable):
            h.read_mem(0, 1)

    def test_a_bad_span_never_reaches_the_bytes(self):
        h = self._host()
        h.write_mem(4096, b"secret")
        with pytest.raises(MemoryOutOfBounds):
            h.read_mem(4096, h.memory().data_len(h.store))


class TestHostFunctionResults:
    """Result arity decides what a host function may hand back, and getting it
    wrong traps the GUEST from inside a host call — which reads like the
    plugin's fault and is not."""

    def _call(self, impls, imports, calls, granted):
        h = WasmCapabilityHost(guest(imports=imports, calls=calls),
                               granted=granted, impls=impls)
        h.instantiate()
        return h.call("dl_build", 4096, 0, RESPONSE_CAP)

    def test_a_void_capability_with_no_impl_does_not_trap(self):
        # Granting `cards` and never implementing show_card used to trap every
        # guest that called it: the stub returned 0 for a no-result function.
        assert self._call({}, [CARDS_IMPORT],
                          ["i32.const 0 i32.const 0 call $show_card"],
                          ["cards"]) > 0

    def test_an_impl_returning_a_value_for_a_void_import_does_not_trap(self):
        assert self._call({"show_card": lambda p, n: 0}, [CARDS_IMPORT],
                          ["i32.const 0 i32.const 0 call $show_card"],
                          ["cards"]) > 0

    def test_an_impl_returning_none_for_an_i32_import_yields_zero(self):
        h = WasmCapabilityHost(
            guest(imports=[NET_IMPORT],
                  calls=["i32.const 7 call $net_get drop"]),
            granted=["net"], impls={"net_get": lambda rid: None})
        h.instantiate()
        assert h.call("dl_build", 4096, 0, RESPONSE_CAP) > 0
        assert h.calls == [("net", "net_get", (7,))]


# --------------------------------------------------- the host, and the store

class _Registry:
    def __init__(self):
        self.providers = []

    def register(self, provider):
        self.providers.append(provider)


class _Lens:
    def __init__(self):
        self.registry = _Registry()


class _Loaded:
    loaded: list = []


class FakeOrchestrator:
    def __init__(self):
        self.object_lens = _Lens()

    def load_plugins(self, plugins):
        return _Loaded()


class _Sighting:
    label: str = "mug"
    confidence: float = 0.9
    attributes: dict = {}


def _installed(tmp_path, pkg, caps=CAPS):
    store = PluginStore(tmp_path / "store", host_capabilities=caps)
    assert store.install_package(pkg).ok, store.install_package(pkg).errors
    return store


class TestPluginHost:
    def _host(self, tmp_path, pkg, requires=("object_lens",)):
        pkg.write(tmp_path / "pkg")
        h = WasmComponentPluginHost(tmp_path / "pkg", requires, name="demo")
        return h

    def test_rows_come_back_from_the_guest(self, tmp_path):
        h = self._host(tmp_path, package())
        assert h.start()
        assert h.build_rows({"label": "mug"}) == [
            {"label": "from wasm", "detail": "zero ambient authority"}]

    def test_a_guest_that_speaks_to_the_host_starts(self, tmp_path, caplog):
        # `requires` is manifest vocabulary and the host links WIT interfaces.
        # Handing the raw list over grants `log` to nobody, so a guest that
        # merely logs fails to instantiate — and every test using a guest that
        # imports nothing would still pass.
        import logging
        caplog.set_level(logging.INFO, logger="dreamlayer.wasm_plugin_host")
        pkg = package(imports=[LOG_IMPORT],
                      calls=["local.get $ptr local.get $len call $log"])
        h = self._host(tmp_path, pkg)
        assert h.start()
        assert h.build_rows({"label": "mug"})
        # …and the line it wrote never carries the guest's own text — nor the
        # plugin's name, which rides the `extra={}` redaction seam instead of
        # the message string (the ONE path logging_setup scrubs).
        said = [r for r in caplog.records if "guest said" in r.getMessage()]
        assert said
        assert "mug" not in said[-1].getMessage()
        assert "wasm-demo" not in said[-1].getMessage()
        assert said[-1].plugin == "demo" and said[-1].chars == 15

    def test_a_declared_capability_links_under_the_manifest_name(self, tmp_path):
        # The author writes `network`; the WIT interface is `net`. Without the
        # translation the guest is refused for importing what it declared.
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"],
                      requires=("object_lens", "network"))
        h = self._host(tmp_path, pkg, requires=("object_lens", "network"))
        assert h.start()
        assert h.build_rows({"label": "mug"})

    def test_an_undeclared_capability_is_still_refused(self, tmp_path):
        # The control: the translation must widen the vocabulary, not the grant.
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"],
                      requires=("object_lens",))
        assert self._host(tmp_path, pkg, requires=("object_lens",)).start() \
            is False

    def test_nothing_to_say_is_no_rows(self, tmp_path):
        h = self._host(tmp_path, package(ret=-1))
        assert h.start()
        assert h.build_rows({"label": "mug"}) == []

    def test_malformed_json_from_the_guest_is_not_an_exception(self, tmp_path):
        h = self._host(tmp_path, package(response="{{{ not json"))
        assert h.start()
        assert h.build_rows({"label": "mug"}) == []

    def test_an_over_long_response_is_dropped(self, tmp_path):
        h = self._host(tmp_path, package(ret=RESPONSE_CAP + 1))
        assert h.start()
        assert h.build_rows({"label": "mug"}) == []

    def test_rows_are_bounded(self, tmp_path):
        many = {"rows": [{"label": f"r{i}", "detail": ""} for i in range(200)]}
        h = self._host(tmp_path, package(response=many))
        assert h.start()
        assert len(h.build_rows({"label": "mug"})) == MAX_ROWS

    def test_a_python_package_is_not_started(self, tmp_path):
        pkg = PluginPackage.build(name="p", version="1.0.0",
                                  entry="plugin:plugin", source="x = 1\n")
        assert self._host(tmp_path, pkg).start() is False

    def test_a_guest_that_cannot_instantiate_fails_quietly(self, tmp_path):
        pkg = package(imports=[NET_IMPORT],
                      calls=["i32.const 1 call $net_get drop"])
        h = self._host(tmp_path, pkg, requires=("object_lens",))
        assert h.start() is False           # not an exception — one bad plugin
        assert h.build_rows({"label": "mug"}) == []   # and still no rows

    def test_build_rows_before_start_is_empty(self, tmp_path):
        assert self._host(tmp_path, package()).build_rows({}) == []

    def test_stop_is_quiet_and_repeatable(self, tmp_path):
        h = self._host(tmp_path, package())
        h.start()
        h.stop()
        h.stop()
        assert h.build_rows({"label": "mug"}) == []


class TestStoreRouting:
    def test_a_wasm_package_reaches_the_component_host(self, tmp_path):
        store = _installed(tmp_path, package())
        orc = FakeOrchestrator()
        try:
            result = store.load_installed(orc)
            assert result.loaded == []            # never in-process
            assert [type(h).__name__ for h in store.isolated] == [
                "WasmComponentPluginHost"]
        finally:
            for h in store.isolated:
                h.stop()

    def test_the_guest_is_a_kernel_boundary_on_its_own(self, tmp_path,
                                                       monkeypatch):
        # The claim: a wasm guest carries the fail-closed default WITHOUT any
        # OS sandbox and WITHOUT the subprocess WASI runtime. Both are forced
        # absent here, which is the posture on every Mac and Windows Brain.
        from dreamlayer.plugins import os_sandbox, wasm_host
        monkeypatch.setattr(os_sandbox, "available", lambda: None)
        monkeypatch.setattr(wasm_host, "available", lambda: False)
        store = _installed(tmp_path, package())
        orc = FakeOrchestrator()
        try:
            store.load_installed(orc, require_sandbox=True)
            assert len(store.isolated) == 1
            assert store.isolation_notices == []   # no degraded-posture record
        finally:
            for h in store.isolated:
                h.stop()

    def test_a_python_package_in_the_same_posture_is_refused(self, tmp_path,
                                                             monkeypatch):
        # The control for the test above: without a guest there is no boundary,
        # so the same store refuses to run the plugin at all.
        from dreamlayer.plugins import os_sandbox, wasm_host
        monkeypatch.setattr(os_sandbox, "available", lambda: None)
        monkeypatch.setattr(wasm_host, "available", lambda: False)
        pkg = PluginPackage.build(name="pyplug", version="1.0.0",
                                  entry="plugin:plugin",
                                  source="def plugin():\n    return None\n")
        store = _installed(tmp_path, pkg)
        store.load_installed(FakeOrchestrator(), require_sandbox=True)
        assert store.isolated == []
        assert any("no kernel boundary" in n for n in store.isolation_notices)

    def test_the_guests_rows_reach_the_object_lens(self, tmp_path):
        store = _installed(tmp_path, package())
        orc = FakeOrchestrator()
        try:
            store.load_installed(orc)
            provider, = orc.object_lens.registry.providers
            assert provider.matches(_Sighting()) is True
            rows = provider.build(_Sighting())
            assert [(r.label, r.detail, r.source) for r in rows] == [
                ("from wasm", "zero ambient authority", "wasm-demo")]
        finally:
            for h in store.isolated:
                h.stop()

    def test_a_silent_guest_matches_nothing(self, tmp_path):
        store = _installed(tmp_path, package(ret=-1))
        orc = FakeOrchestrator()
        try:
            store.load_installed(orc)
            provider, = orc.object_lens.registry.providers
            assert provider.matches(_Sighting()) is False
            assert provider.build(_Sighting()) == []
        finally:
            for h in store.isolated:
                h.stop()

    def test_build_without_a_matching_cache_still_asks_the_guest(self, tmp_path):
        # The registry calls matches() then build(); a caller that skips
        # matches() (or asks about a different sighting) must still get rows,
        # not the previous sighting's.
        store = _installed(tmp_path, package())
        orc = FakeOrchestrator()
        try:
            store.load_installed(orc)
            provider, = orc.object_lens.registry.providers
            assert len(provider.build(_Sighting())) == 1
        finally:
            for h in store.isolated:
                h.stop()


EXTISM_ROWS = {"rows": [{"label": "from extism", "detail": "made incapable"}]}


def extism_wat(response=None, *, imports=True, func="run"):
    """An Extism guest against the runtime's own PDK ABI — alloc a buffer,
    copy the reply into it byte by byte, hand it to `output_set`.

    Hand-written rather than compiled so the test needs no Rust/Go toolchain,
    and so every failure mode below is one edit away from the working one.
    """
    body = json.dumps(EXTISM_ROWS if response is None else response,
                      separators=(",", ":"))
    n = len(body.encode("utf-8"))
    imp = ('(import "extism:host/env" "alloc" (func $alloc (param i64) (result i64)))\n'
           '(import "extism:host/env" "store_u8" (func $store_u8 (param i64 i32)))\n'
           '(import "extism:host/env" "output_set" (func $output_set (param i64 i64)))'
           ) if imports else ""
    guts = ("""
    (local.set $off (call $alloc (i64.const %d)))
    (block $done (loop $l
      (br_if $done (i32.ge_u (local.get $i) (i32.const %d)))
      (call $store_u8 (i64.add (local.get $off) (i64.extend_i32_u (local.get $i)))
                      (i32.load8_u (local.get $i)))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br $l)))
    (call $output_set (local.get $off) (i64.const %d))""" % (n, n, n)
            ) if imports else ""
    return f"""(module
  {imp}
  (memory 1)
  (data (i32.const 0) "{_wat_escape(body)}")
  (func (export "{func}") (result i32)
    (local $off i64) (local $i i32){guts}
    (i32.const 0)))"""


def extism_guest(**kw) -> bytes:
    return bytes(wasmtime.wat2wasm(extism_wat(**kw)))


def extism_package(*, entry="demo:run", requires=("object_lens",), **kw):
    return PluginPackage.build_wasm(name="extism-demo", version="1.0.0",
                                    entry=entry, wasm=extism_guest(**kw),
                                    kind="extism", requires=requires)


class TestExtismRuntime:
    """The second runtime, on the same package format. `extism_host.py` was
    complete and tested and had exactly one caller — its own tests — because
    nothing on disk was ever an Extism guest."""

    @pytest.fixture(autouse=True)
    def _requires_the_extism_runtime(self):
        """Gated on the dependency this class actually uses.

        The file's only guard is `importorskip("wasmtime")` at the top, and
        these tests need `extism` as well — a different package with a
        different native runtime. While CI installed neither, the whole file
        skipped and the mis-gating was invisible; installing wasmtime (#630)
        unskipped the file and these five failed on an absent `extism` with
        `ExtismPluginHost.start()` returning a bare False, which reads as a
        broken host rather than a missing wheel.

        A skip that names the right reason is the whole point — see
        CLAUDE.md #1 on skips that examined nothing.
        """
        pytest.importorskip("extism")

    def test_the_package_is_the_same_format_with_another_kind(self, tmp_path):
        pkg = extism_package()
        assert pkg.manifest.is_extism and not pkg.manifest.is_wasm
        assert pkg.manifest.carries_wasm
        pkg.write(tmp_path)
        assert (tmp_path / "demo.wasm").exists()
        assert PluginPackage.load(tmp_path).wasm_bytes() == pkg.wasm_bytes()

    def test_kind_extism_is_in_the_signing_payload(self):
        assert extism_package().signing_payload()["kind"] == "extism"

    def test_the_gate_accepts_the_runtimes_own_abi(self):
        # An Extism guest imports `extism:host/env`. Scanned against the
        # component host's namespace it would read as reaching outside the
        # host surface — the check has to know whose runtime it is.
        assert validate(extism_package(), CAPS).ok

    def test_the_same_guest_fails_the_component_hosts_scan(self):
        payload = extism_guest()
        assert scan_wasm(payload, ("object_lens",))          # dreamlayer's view
        assert scan_wasm(payload, ("object_lens",),
                         host_module="extism:host/env") == []

    def test_a_guest_reaching_outside_the_runtime_is_refused(self):
        pkg = PluginPackage.build_wasm(
            name="liar", version="1.0.0", entry="demo:run", kind="extism",
            wasm=bytes(wasmtime.wat2wasm(
                '(module (import "env" "sneaky" (func $s))'
                ' (func (export "run") (result i32) call $s i32.const 0))')),
            requires=("object_lens",))
        report = validate(pkg, CAPS)
        assert any("outside the extism:host/env surface" in e
                   for e in report.errors)

    def test_a_guest_missing_its_entry_export_is_refused(self):
        pkg = extism_package(entry="demo:not_there")
        assert any("exports no 'not_there'" in e
                   for e in validate(pkg, CAPS).errors)

    def test_smoke_calls_the_guest_for_real(self):
        assert validate(extism_package(), CAPS, run_smoke=True).ok

    def test_smoke_catches_a_guest_that_traps(self):
        from dreamlayer.plugins.validate import _smoke_extism
        pkg = PluginPackage.build_wasm(
            name="trapper", version="1.0.0", entry="demo:run", kind="extism",
            wasm=bytes(wasmtime.wat2wasm(
                '(module (memory 1) (func (export "run") (result i32)'
                ' unreachable))')))
        issues = _smoke_extism(pkg)
        assert issues and "returned nothing" in issues[0]

    def test_smoke_does_not_fail_a_guest_with_nothing_to_say(self):
        # `{}` is not a real sighting, and "no rows for this one" is the answer
        # a well-behaved provider gives most of the time. Treating an empty
        # reply as breakage would fail the gate on correct plugins.
        from dreamlayer.plugins.validate import _smoke_extism
        assert _smoke_extism(extism_package(imports=False)) == []

    def test_rows_come_back_from_the_guest(self, tmp_path):
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        extism_package().write(tmp_path / "pkg")
        h = ExtismPluginHost(tmp_path / "pkg", ("object_lens",), name="demo")
        assert h.start()
        assert h.build_rows({"label": "mug"}) == [
            {"label": "from extism", "detail": "made incapable"}]

    def test_a_wasm_package_is_not_started_by_the_extism_host(self, tmp_path):
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        package().write(tmp_path / "pkg")
        assert ExtismPluginHost(tmp_path / "pkg", ()).start() is False

    def test_a_silent_guest_is_no_rows_not_an_exception(self, tmp_path):
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        extism_package(imports=False).write(tmp_path / "pkg")
        h = ExtismPluginHost(tmp_path / "pkg", (), name="demo")
        assert h.start()
        assert h.build_rows({"label": "mug"}) == []

    def test_rows_are_bounded(self, tmp_path):
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        many = {"rows": [{"label": f"r{i}", "detail": ""} for i in range(200)]}
        extism_package(response=many).write(tmp_path / "pkg")
        h = ExtismPluginHost(tmp_path / "pkg", (), name="demo")
        assert h.start()
        assert len(h.build_rows({"label": "mug"})) == MAX_ROWS

    def test_build_rows_before_start_is_empty(self, tmp_path):
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        extism_package().write(tmp_path / "pkg")
        assert ExtismPluginHost(tmp_path / "pkg", ()).build_rows({}) == []

    def test_the_store_routes_and_the_rows_reach_the_lens(self, tmp_path,
                                                          monkeypatch):
        # Same claim as the component host's: the guest is a boundary on its
        # own, with no OS sandbox and no subprocess WASI runtime present.
        from dreamlayer.plugins import os_sandbox, wasm_host
        monkeypatch.setattr(os_sandbox, "available", lambda: None)
        monkeypatch.setattr(wasm_host, "available", lambda: False)
        store = _installed(tmp_path, extism_package())
        orc = FakeOrchestrator()
        try:
            store.load_installed(orc, require_sandbox=True)
            assert [type(h).__name__ for h in store.isolated] == [
                "ExtismPluginHost"]
            assert store.isolation_notices == []
            provider, = orc.object_lens.registry.providers
            assert provider.matches(_Sighting()) is True
            assert [(r.label, r.source) for r in provider.build(_Sighting())] \
                == [("from extism", "extism-demo")]
        finally:
            for h in store.isolated:
                h.stop()

    def test_the_two_runtimes_are_counted_separately(self, tmp_path):
        # A wearer running one is not running the other, so the capability
        # promotions must not borrow each other's proof.
        from dreamlayer.plugins import extism_plugin_host, wasm_plugin_host
        from dreamlayer.plugins.extism_plugin_host import ExtismPluginHost
        extism_package().write(tmp_path / "pkg")
        h = ExtismPluginHost(tmp_path / "pkg", (), name="demo")
        before = wasm_plugin_host.live_guests()
        assert h.start()
        assert extism_plugin_host.live_guests() >= 1
        assert wasm_plugin_host.live_guests() == before
        h.stop()
        assert extism_plugin_host.live_guests() == 0

    def test_the_cli_loads_an_extism_project(self, tmp_path):
        from dreamlayer.cli import _load_package
        (tmp_path / "demo.wasm").write_bytes(extism_guest())
        (tmp_path / "manifest.json").write_text(json.dumps({
            "name": "extism-demo", "version": "1.0.0", "entry": "demo:run",
            "kind": "extism", "requires": ["object_lens"]}))
        pkg = _load_package(str(tmp_path))
        assert pkg.manifest.is_extism and validate(pkg, CAPS).ok


class TestAuthoringPath:
    def test_package_from_wasm_dir_builds_a_gate_passing_package(self, tmp_path):
        from dreamlayer.sdk import package_from_wasm_dir
        (tmp_path / "demo.wasm").write_bytes(guest())
        (tmp_path / "manifest.json").write_text(json.dumps({
            "name": "wasm-demo", "version": "1.0.0", "entry": "demo:dl_build",
            "requires": ["object_lens"]}))
        pkg = package_from_wasm_dir(tmp_path)
        assert pkg.manifest.is_wasm and validate(pkg, CAPS).ok

    def test_a_missing_payload_names_the_file(self, tmp_path):
        from dreamlayer.sdk import package_from_wasm_dir
        (tmp_path / "manifest.json").write_text(json.dumps({
            "name": "x", "version": "1.0.0", "entry": "demo:dl_build"}))
        with pytest.raises(FileNotFoundError) as ei:
            package_from_wasm_dir(tmp_path)
        assert "demo.wasm is missing" in str(ei.value)

    def _project(self, tmp_path, kind="wasm"):
        (tmp_path / "demo.wasm").write_bytes(guest())
        (tmp_path / "manifest.json").write_text(json.dumps({
            "name": "wasm-demo", "version": "1.0.0", "entry": "demo:dl_build",
            "kind": kind, "requires": ["object_lens"]}))
        return tmp_path

    def test_the_cli_loads_a_wasm_project(self, tmp_path):
        # One routing rule serves `validate`, `pack`, `install` and `dev
        # --watch` — they all resolve their target through `_load_package`.
        from dreamlayer.cli import _load_package
        pkg = _load_package(str(self._project(tmp_path)))
        assert pkg.manifest.is_wasm and pkg.wasm_bytes()[:4] == b"\0asm"

    def test_the_cli_validates_one_green(self, tmp_path, capsys):
        from dreamlayer.cli import main
        assert main(["plugins", "validate", str(self._project(tmp_path))]) == 0

    def test_the_cli_still_reads_a_python_project(self, tmp_path):
        from dreamlayer.cli import _load_package
        (tmp_path / "plugin.py").write_text("def plugin():\n    return None\n")
        (tmp_path / "plugin.json").write_text(json.dumps({
            "name": "py-demo", "version": "1.0.0", "entry": "plugin:plugin"}))
        assert _load_package(str(tmp_path)).manifest.is_wasm is False

    def test_the_dev_watcher_notices_a_recompiled_guest(self, tmp_path):
        # A watcher that only knows about plugin.py sits still through the one
        # edit a wasm author actually makes.
        import os
        from dreamlayer.cli import _watch_sig
        d = self._project(tmp_path)
        before = _watch_sig(d)
        os.utime(d / "demo.wasm", (1_700_000_000, 1_700_000_000))
        assert _watch_sig(d) != before
