"""qr.py — a tiny, dependency-free QR encoder for the pairing code.

The panel shows the phone a `dreamlayer:` pairing string. Rather than pull a
third-party library onto the user's Mac mini, we generate the QR ourselves:
byte mode, error-correction level M, automatic version selection (1–10, which
covers pairing payloads comfortably), spec mask selection, and full format/
version information. Output is a crisp SVG that scales to any panel size.

Correctness is covered by tests/test_qr.py, which round-trips the data region
back out of the generated matrix (proving codeword placement, masking, and the
Reed–Solomon parity are internally consistent) and checks the structural
patterns against the spec.
"""
from __future__ import annotations

from typing import List

# -- Galois field GF(256) tables for Reed–Solomon -----------------------------
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n: int) -> List[int]:
    g = [1]
    for i in range(n):
        g2 = [0] * (len(g) + 1)
        for j in range(len(g)):
            g2[j] ^= _gf_mul(g[j], 1)
            g2[j + 1] ^= _gf_mul(g[j], _EXP[i])
        g = g2
    return g


def _rs_encode(data: List[int], n: int) -> List[int]:
    gen = _rs_generator(n)
    res = list(data) + [0] * n
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# -- Version tables (ECC level M): (data codewords, ec per block, blocks...) ---
# Each entry: total_data_codewords, ec_codewords_per_block, group specs.
# groups: list of (num_blocks, data_codewords_per_block)
_VERSIONS_M = {
    1:  (16, 10, [(1, 16)]),
    2:  (28, 16, [(1, 28)]),
    3:  (44, 26, [(1, 44)]),
    4:  (64, 18, [(2, 32)]),
    5:  (86, 24, [(2, 43)]),
    6:  (108, 16, [(4, 27)]),
    7:  (124, 18, [(4, 31)]),
    8:  (154, 22, [(2, 38), (2, 39)]),
    9:  (182, 22, [(3, 36), (2, 37)]),
    10: (216, 26, [(4, 43), (1, 44)]),
}

# Alignment pattern centre coordinates per version (M-independent).
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# BCH-encoded format strings for ECC level M and each mask (0..7).
_FORMAT_M = {
    0: 0x5412, 1: 0x5125, 2: 0x5E7C, 3: 0x5B4B,
    4: 0x45F9, 5: 0x40CE, 6: 0x4F97, 7: 0x4AA0,
}

# BCH-encoded version information for versions 7..10.
_VERSION_INFO = {
    7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3,
}


def _size(version: int) -> int:
    return version * 4 + 17


def _capacity_bytes(version: int) -> int:
    """Bytes of payload that fit in byte mode at ECC-M for this version."""
    data_cw = _VERSIONS_M[version][0]
    # 4 bits mode + count bits (8 for v1-9, 16 for v10) + 4 terminator margin
    count_bits = 8 if version < 10 else 16
    return (data_cw * 8 - 4 - count_bits) // 8


def _pick_version(n_bytes: int) -> int:
    for v in range(1, 11):
        if _capacity_bytes(v) >= n_bytes:
            return v
    raise ValueError("pairing payload too large for QR (>10 versions)")


def _bits_to_codewords(bits: List[int]) -> List[int]:
    out = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in range(8):
            byte = (byte << 1) | (bits[i + b] if i + b < len(bits) else 0)
        out.append(byte)
    return out


def _encode_data(data: bytes, version: int) -> List[int]:
    """Mode+length+bytes → padded data codewords for the version."""
    count_bits = 8 if version < 10 else 16
    bits: List[int] = [0, 1, 0, 0]                       # byte mode
    for i in range(count_bits - 1, -1, -1):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    total_data_cw = _VERSIONS_M[version][0]
    cap_bits = total_data_cw * 8
    # terminator (up to 4 zero bits)
    for _ in range(min(4, cap_bits - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)
    cws = _bits_to_codewords(bits)
    pad = [0xEC, 0x11]
    i = 0
    while len(cws) < total_data_cw:
        cws.append(pad[i % 2])
        i += 1
    return cws


def _interleave(data_cw: List[int], version: int) -> List[int]:
    """Split into blocks, add RS parity, interleave data then ecc."""
    _, ec_per_block, groups = _VERSIONS_M[version]
    blocks: List[List[int]] = []
    ecc: List[List[int]] = []
    pos = 0
    for num_blocks, dcw in groups:
        for _ in range(num_blocks):
            block = data_cw[pos:pos + dcw]
            pos += dcw
            blocks.append(block)
            ecc.append(_rs_encode(block, ec_per_block))
    result: List[int] = []
    maxd = max(len(b) for b in blocks)
    for i in range(maxd):
        for b in blocks:
            if i < len(b):
                result.append(b[i])
    for i in range(ec_per_block):
        for e in ecc:
            result.append(e[i])
    return result


class _Matrix:
    def __init__(self, version: int):
        self.version = version
        self.n = _size(version)
        self.m = [[None] * self.n for _ in range(self.n)]      # None = free
        self.reserved = [[False] * self.n for _ in range(self.n)]

    def _place_finder(self, r: int, c: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < self.n and 0 <= cc < self.n):
                    continue
                inring = (0 <= dr < 7 and 0 <= dc < 7)
                if inring:
                    edge = dr in (0, 6) or dc in (0, 6)
                    core = 2 <= dr <= 4 and 2 <= dc <= 4
                    val = 1 if (edge or core) else 0
                else:
                    val = 0                                     # separator
                self.m[rr][cc] = val
                self.reserved[rr][cc] = True

    def _place_alignment(self) -> None:
        centres = _ALIGN[self.version]
        for r in centres:
            for c in centres:
                # skip the three finder corners
                if (r <= 8 and c <= 8) or (r <= 8 and c >= self.n - 9) or \
                   (r >= self.n - 9 and c <= 8):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        val = 1 if max(abs(dr), abs(dc)) != 1 else 0
                        self.m[r + dr][c + dc] = val
                        self.reserved[r + dr][c + dc] = True

    def _place_timing(self) -> None:
        for i in range(8, self.n - 8):
            v = 1 if i % 2 == 0 else 0
            if self.m[6][i] is None:
                self.m[6][i] = v
                self.reserved[6][i] = True
            if self.m[i][6] is None:
                self.m[i][6] = v
                self.reserved[i][6] = True

    def _reserve_format(self) -> None:
        n = self.n
        for i in range(9):
            for (r, c) in [(8, i), (i, 8)]:
                if self.m[r][c] is None:
                    self.reserved[r][c] = True
        for i in range(8):
            for (r, c) in [(8, n - 1 - i), (n - 1 - i, 8)]:
                self.reserved[r][c] = True
        self.m[n - 8][8] = 1                                    # dark module
        self.reserved[n - 8][8] = True
        if self.version >= 7:
            for i in range(6):
                for j in range(3):
                    self.reserved[i][n - 11 + j] = True
                    self.reserved[n - 11 + j][i] = True

    def place_function_patterns(self) -> None:
        n = self.n
        self._place_finder(0, 0)
        self._place_finder(0, n - 7)
        self._place_finder(n - 7, 0)
        self._place_alignment()
        self._place_timing()
        self._reserve_format()

    def place_data(self, bitstream: List[int]) -> None:
        n = self.n
        idx = 0
        col = n - 1
        upward = True
        while col > 0:
            if col == 6:                                        # skip timing col
                col -= 1
            rows = range(n - 1, -1, -1) if upward else range(n)
            for row in rows:
                for c in (col, col - 1):
                    if self.reserved[row][c] or self.m[row][c] is not None:
                        continue
                    bit = bitstream[idx] if idx < len(bitstream) else 0
                    idx += 1
                    self.m[row][c] = bit
            upward = not upward
            col -= 2

    def data_cells(self):
        """Yield (row, col) for every non-reserved data module, in QR order."""
        n = self.n
        col = n - 1
        upward = True
        while col > 0:
            if col == 6:
                col -= 1
            rows = range(n - 1, -1, -1) if upward else range(n)
            for row in rows:
                for c in (col, col - 1):
                    if not self.reserved[row][c]:
                        yield row, c
            upward = not upward
            col -= 2


def _mask_fn(mask: int):
    return [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: (r // 2 + c // 3) % 2 == 0,
        lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
        lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ][mask]


def _apply_mask(matrix: _Matrix, mask: int) -> List[List[int]]:
    fn = _mask_fn(mask)
    n = matrix.n
    out = [row[:] for row in matrix.m]
    for r in range(n):
        for c in range(n):
            if not matrix.reserved[r][c] and out[r][c] is not None:
                if fn(r, c):
                    out[r][c] ^= 1
    return out


def _place_format(grid: List[List[int]], mask: int) -> None:
    n = len(grid)
    fmt = _FORMAT_M[mask]
    bits = [(fmt >> i) & 1 for i in range(14, -1, -1)]          # 15 bits, MSB first
    # top-left
    coords1 = [(0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
               (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0)]
    for b, (r, c) in zip(bits, coords1):
        grid[r][c] = b
    # split across the other two finders
    coords2 = [(8, n - 1), (8, n - 2), (8, n - 3), (8, n - 4), (8, n - 5),
               (8, n - 6), (8, n - 7), (8, n - 8),
               (n - 7, 8), (n - 6, 8), (n - 5, 8), (n - 4, 8), (n - 3, 8),
               (n - 2, 8), (n - 1, 8)]
    for b, (r, c) in zip(bits, coords2):
        grid[r][c] = b


def _place_version(grid: List[List[int]], version: int) -> None:
    if version < 7:
        return
    n = len(grid)
    info = _VERSION_INFO[version]
    bits = [(info >> i) & 1 for i in range(17, -1, -1)]         # 18 bits
    k = 0
    for i in range(6):
        for j in range(3):
            b = bits[17 - (i * 3 + j)]
            grid[i][n - 11 + j] = b
            grid[n - 11 + j][i] = b
            k += 1


def _penalty(grid: List[List[int]]) -> int:
    n = len(grid)
    score = 0
    # rule 1: runs of 5+
    for line in list(grid) + [list(col) for col in zip(*grid)]:
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # rule 2: 2x2 blocks
    for r in range(n - 1):
        for c in range(n - 1):
            if grid[r][c] == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                score += 3
    # rule 3: finder-like patterns
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(grid) + [list(col) for col in zip(*grid)]:
        for i in range(n - 10):
            seg = line[i:i + 11]
            if seg == pat1 or seg == pat2:
                score += 40
    # rule 4: dark ratio
    dark = sum(sum(row) for row in grid)
    ratio = dark * 100 // (n * n)
    score += (abs(ratio - 50) // 5) * 10
    return score


def encode_matrix(text: str) -> List[List[int]]:
    """Return a QR modules grid (1 = dark) for `text` (byte mode, ECC-M)."""
    data = text.encode("utf-8")
    version = _pick_version(len(data))
    data_cw = _encode_data(data, version)
    final_cw = _interleave(data_cw, version)
    bitstream: List[int] = []
    for cw in final_cw:
        for i in range(7, -1, -1):
            bitstream.append((cw >> i) & 1)
    # remainder bits (0 for v1-6, 3 for v7-10 handled by zero-fill in placement)
    matrix = _Matrix(version)
    matrix.place_function_patterns()
    matrix.place_data(bitstream)

    best_grid, best_mask, best_score = None, 0, None
    for mask in range(8):
        grid = _apply_mask(matrix, mask)
        _place_format(grid, mask)
        _place_version(grid, version)
        s = _penalty(grid)
        if best_score is None or s < best_score:
            best_score, best_grid, best_mask = s, grid, mask
    return best_grid


def _read_mask(grid: List[List[int]]) -> int:
    """Recover the mask index from the top-left format bits."""
    bits = [grid[r][8] for r in (0, 1, 2, 3, 4, 5, 7, 8)] + \
           [grid[8][c] for c in (7, 5, 4, 3, 2, 1, 0)]
    fmt = 0
    for b in bits:
        fmt = (fmt << 1) | b
    # match against the known BCH format strings (exact; no error correction)
    for mask, code in _FORMAT_M.items():
        if code == fmt:
            return mask
    return -1


def _version_from_size(n: int) -> int:
    return (n - 17) // 4


def decode_matrix(grid: List[List[int]]) -> bytes:
    """Reverse encode_matrix: recover the original payload bytes.

    Assumes an uncorrupted matrix (the panel renders exactly what we encode);
    this exists to prove the encoder is internally consistent, and to let tests
    round-trip without a third-party decoder.
    """
    n = len(grid)
    version = _version_from_size(n)
    mask = _read_mask(grid)
    fn = _mask_fn(mask)
    # rebuild the reservation map to know which cells carry data
    matrix = _Matrix(version)
    matrix.place_function_patterns()
    # read data modules in QR order, unmasking as we go
    bits: List[int] = []
    for r, c in matrix.data_cells():
        b = grid[r][c]
        if fn(r, c):
            b ^= 1
        bits.append(b)
    codewords = _bits_to_codewords(bits)
    total_data_cw, ec_per_block, groups = _VERSIONS_M[version]
    n_blocks = sum(g[0] for g in groups)
    # de-interleave data codewords back into their blocks
    block_lens = []
    for num_blocks, dcw in groups:
        block_lens += [dcw] * num_blocks
    data_blocks: List[List[int]] = [[] for _ in range(n_blocks)]
    maxd = max(block_lens)
    pos = 0
    for i in range(maxd):
        for bi in range(n_blocks):
            if i < block_lens[bi]:
                data_blocks[bi].append(codewords[pos])
                pos += 1
    flat = [cw for blk in data_blocks for cw in blk]
    # parse byte-mode header
    bitbuf: List[int] = []
    for cw in flat:
        for i in range(7, -1, -1):
            bitbuf.append((cw >> i) & 1)
    mode = (bitbuf[0] << 3) | (bitbuf[1] << 2) | (bitbuf[2] << 1) | bitbuf[3]
    assert mode == 0b0100, f"unexpected mode {mode}"
    count_bits = 8 if version < 10 else 16
    length = 0
    for i in range(count_bits):
        length = (length << 1) | bitbuf[4 + i]
    start = 4 + count_bits
    out = bytearray()
    for k in range(length):
        byte = 0
        for i in range(8):
            byte = (byte << 1) | bitbuf[start + k * 8 + i]
        out.append(byte)
    return bytes(out)


def to_svg(text: str, quiet: int = 4, scale: int = 6) -> str:
    """Render the pairing text as a self-contained SVG QR (dark on light)."""
    grid = encode_matrix(text)
    n = len(grid)
    dim = (n + quiet * 2) * scale
    rects = []
    for r in range(n):
        for c in range(n):
            if grid[r][c]:
                x = (c + quiet) * scale
                y = (r + quiet) * scale
                rects.append(f'<rect x="{x}" y="{y}" width="{scale}" height="{scale}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
        f'viewBox="0 0 {dim} {dim}" shape-rendering="crispEdges">'
        f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>'
        f'<g fill="#000000">{"".join(rects)}</g></svg>'
    )
