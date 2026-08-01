"""plugins/wasm_scan.py — read a WASM module's imports and exports, no runtime.

`validate.py` screens a Python plugin by parsing it to an AST *without running
it*. A `.wasm` package needs the same courtesy at the same moment — install
time, on whatever machine the wearer is holding — and wasmtime is an optional
dependency (the ``platform`` extra). So the reader here is hand-rolled against
the binary format rather than borrowed from the runtime: a gate that only works
where the runtime is installed is a gate that is missing exactly where the
weakest hosts are.

It reads two sections and skips the rest:

    id 2  import   — (module, field) for every import the guest declares
    id 7  export   — (name, kind) for every export it offers

which is enough to answer both questions the gate asks: *does this guest reach
for a power its manifest never declared*, and *does it export the functions the
host is about to call*.

SAME STANDING AS `scan_source`: A LINT, NOT THE BOUNDARY
-------------------------------------------------------
`validate.scan_source` spells out that an AST screen cannot enforce a capability
model, and points at the sandbox as the thing that actually stands between a
hostile plugin and the wearer. The wasm story is the happier one — for a guest,
the capability model IS enforced, by
`wasm_component_host.WasmCapabilityHost._refuse_undeclared`, using wasmtime's
own parser, before a single guest instruction runs. This module exists to move
that same answer EARLIER, so a lying package is refused at install rather than
at load. If a malformed module could fool the reader here, the runtime check
still catches it; nothing downstream trusts this file's word for safety.

Every parse error is fatal by design. A section this reader cannot follow means
it can no longer trust its own offsets, and a scanner that resynchronises after
a desync is a scanner that can be desynced ON PURPOSE — so it raises, the gate
reports the module as unusable, and the package does not install.
"""
from __future__ import annotations

from typing import Iterator, List, Tuple

MAGIC = b"\0asm"

#: Binary-format versions this reader understands. Only 1 has ever shipped; a
#: module claiming another is refused rather than parsed hopefully.
SUPPORTED_VERSIONS = (1,)

SECTION_IMPORT = 2
SECTION_EXPORT = 7

#: `externkind` bytes, shared by the import and export sections.
KIND_FUNC, KIND_TABLE, KIND_MEMORY, KIND_GLOBAL = 0x00, 0x01, 0x02, 0x03


class MalformedModule(ValueError):
    """The bytes are not a WASM module this reader can follow."""


class _Reader:
    """A bounds-checked cursor over untrusted bytes. Every primitive either
    returns exactly what it promised or raises — there is no short read."""

    def __init__(self, buf: bytes):
        self.buf = buf
        self.i = 0

    @property
    def done(self) -> bool:
        return self.i >= len(self.buf)

    def take(self, n: int) -> bytes:
        if n < 0 or self.i + n > len(self.buf):
            raise MalformedModule(f"truncated: wanted {n} bytes at {self.i}")
        out = self.buf[self.i:self.i + n]
        self.i += n
        return out

    def byte(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        """LEB128, bounded to the five bytes a u32 can occupy. The bound is the
        point: an unbounded shift loop over attacker-chosen bytes is how a
        parser turns into the bug it was written to prevent."""
        out = shift = 0
        for _ in range(5):
            b = self.byte()
            out |= (b & 0x7F) << shift
            if not b & 0x80:
                return out
            shift += 7
        raise MalformedModule("overlong LEB128 integer")

    def name(self) -> str:
        """A WASM `name`: a length-prefixed UTF-8 byte string. Undecodable
        bytes are replaced rather than raising — a guest with a mangled import
        name should be reported as importing something unrecognisable, not
        crash the gate."""
        return self.take(self.u32()).decode("utf-8", "replace")

    def limits(self) -> None:
        """Skip a `limits` (table/memory). Bit 0 of the flag means a max
        follows; the other bits (shared, memory64) change nothing we read."""
        flag = self.byte()
        self.u32()                              # min
        if flag & 0x01:
            self.u32()                          # max


def sections(payload: bytes) -> Iterator[Tuple[int, bytes]]:
    """Yield `(section_id, body)` for each section, header verified first."""
    r = _Reader(payload)
    if r.take(4) != MAGIC:
        raise MalformedModule("not a WebAssembly module (bad magic)")
    version = int.from_bytes(r.take(4), "little")
    if version not in SUPPORTED_VERSIONS:
        raise MalformedModule(f"unsupported WebAssembly version {version}")
    while not r.done:
        sid = r.byte()
        yield sid, r.take(r.u32())


def section_bodies(payload: bytes) -> dict:
    """`{section_id: body}` for the whole module, LAST wins for a repeat.

    Every section is walked even when the caller wants one, and that is
    deliberate: stopping at the section of interest would let a module
    truncated before its import section answer "imports nothing" — a short read
    reported as a clean bill of health, which is the one answer this reader
    must never give.
    """
    out: dict = {}
    for sid, body in sections(payload):
        out[sid] = body
    return out


def module_imports(payload: bytes) -> List[Tuple[str, str]]:
    """`[(module, field), ...]` — everything the guest asks the host for."""
    for sid, body in section_bodies(payload).items():
        if sid != SECTION_IMPORT:
            continue
        r = _Reader(body)
        out: List[Tuple[str, str]] = []
        for _ in range(r.u32()):
            mod, field = r.name(), r.name()
            kind = r.byte()
            # The descriptor has to be consumed even though we don't use it —
            # it is what separates this import from the next one.
            if kind == KIND_FUNC:
                r.u32()                         # type index
            elif kind == KIND_TABLE:
                r.byte()                        # reftype
                r.limits()
            elif kind == KIND_MEMORY:
                r.limits()
            elif kind == KIND_GLOBAL:
                r.byte()                        # valtype
                r.byte()                        # mutability
            else:
                raise MalformedModule(f"unknown import kind 0x{kind:02x}")
            out.append((mod, field))
        return out
    return []                                   # a module may import nothing


def module_exports(payload: bytes) -> List[Tuple[str, int]]:
    """`[(name, kind), ...]` — everything the guest offers the host."""
    for sid, body in section_bodies(payload).items():
        if sid != SECTION_EXPORT:
            continue
        r = _Reader(body)
        out: List[Tuple[str, int]] = []
        for _ in range(r.u32()):
            name = r.name()
            kind = r.byte()
            r.u32()                             # index into the kind's space
            out.append((name, kind))
        return out
    return []
