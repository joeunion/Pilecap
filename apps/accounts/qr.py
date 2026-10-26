"""A QR symbol, encoded here and drawn as inline SVG. **No library, no fetch.**

Design J2-c asks the enrolment frame for "a QR, rendered by us from the TOTP
URI Zitadel returns". Three words in that sentence are the whole of why this
module exists:

* **by us** — a hosted image service would be the enrolment secret of every
  person in the deployment, handed to a third party in a query string, on the
  one screen where the secret is the thing being protected. There is no
  acceptable third party for this payload.
* **rendered** — the entrance fetches nothing (`test_no_frame_fetches_anything`
  and the shell's own no-fetch property). An `<img src=…>` is a fetch even when
  it is same-origin, and a sign-in page that can fail to load its QR is a page
  that renders an empty box on the one screen a person cannot get past.
* **from the URI** — the payload is `otpauth://totp/…?secret=…`, 60–120 bytes
  of ASCII. That is the whole population this module has to encode, which is
  why byte mode at error-correction level M over versions 1–10 is the declared
  envelope rather than an apology: it covers 216 bytes, and `TooLong` is raised
  rather than a symbol nobody can scan being returned.

**Why not a dependency.** `qrcode` (and `segno`, and `Pillow` behind the
first) would be three new packages on the supply-chain leg, in the request
path of the sign-in door, to draw a 33×33 grid of squares from a specification
that has not moved since 2006 (first principles 12: convenience does not
create permanent dependencies). The encoder is ~250 lines of arithmetic with
no I/O, no state and no configuration, and every table in it is in the
specification. The plan sanctions an in-tree encoder and names the shape
("an SVG built in-tree"); this is that.

**What is NOT here, and is not wanted.** Kanji, alphanumeric and numeric
modes (a URI is bytes); ECI; structured append; micro QR; versions above 10;
error-correction levels other than M. Each one is capacity or robustness this
payload does not need, and every one of them is a branch the tests would have
to reach. Level M rather than L because the symbol is read off a screen by a
phone camera at an angle, and rather than Q/H because those cost a version
and the version costs modules on a 400px-wide viewport.

**The one safety property, stated because `svg()` returns a `SafeString`.**
Nothing that goes in comes out as markup. The payload is turned into *modules*
— booleans — by `encode()`, and `svg()` writes integers and a fixed skeleton
around them. There is no interpolation path from the argument to the document,
which is why marking the result safe is a fact about this function rather than
a promise about its caller. The rendered symbol carries no text at all: the
secret is printed by the frame, in its own element, escaped by the template
engine like any other value.
"""

from __future__ import annotations

from django.utils.safestring import SafeString, mark_safe

__all__ = ["MAX_BYTES", "TooLong", "encode", "svg"]


class TooLong(ValueError):
    """The payload does not fit the declared envelope (version 10, level M).

    Raised rather than silently truncated or silently promoted to a version
    this module has no tables for: a QR symbol that encodes half a URI scans
    perfectly and enrols nobody.
    """


# --- the specification's tables, for versions 1–10 at level M ----------------
#
# Every number below is from ISO/IEC 18004. They are typed here rather than
# derived because there is nothing to derive them FROM — they are the
# specification — and the self-consistency of each row is checked by the
# tests: data codewords + ecc codewords must equal the version's total.

#: Total codewords (data + error correction) per version.
_TOTAL_CODEWORDS = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 8: 242, 9: 292, 10: 346}

#: Level M's block structure per version:
#: `(ecc codewords per block, [data codewords in each block])`.
_BLOCKS_M: dict[int, tuple[int, list[int]]] = {
    1: (10, [16]),
    2: (16, [28]),
    3: (26, [44]),
    4: (18, [32, 32]),
    5: (24, [43, 43]),
    6: (16, [27, 27, 27, 27]),
    7: (18, [31, 31, 31, 31]),
    8: (22, [38, 38, 39, 39]),
    9: (22, [36, 36, 36, 37, 37]),
    10: (26, [43, 43, 43, 43, 44]),
}

#: Alignment-pattern centre coordinates per version (version 1 has none).
_ALIGNMENT = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

#: Remainder bits appended after the last codeword, per version.
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

#: Level M's two-bit indicator in the format information.
_ECC_LEVEL_M = 0b00

#: Byte mode's four-bit indicator.
_BYTE_MODE = 0b0100

#: The largest payload the declared envelope holds, in bytes. Version 10 at
#: level M carries 216 data codewords; the header spends 4 bits of mode and 16
#: bits of character count at that version, which is two and a half codewords.
MAX_BYTES = 216 - 3


# --- GF(256), for the Reed-Solomon remainder ---------------------------------
#
# The field is the specification's: x^8 + x^4 + x^3 + x^2 + 1 (0x11D). Two
# tables, built once at import, because a log/antilog pair turns every
# multiplication in the encoder into one addition.

_EXP: list[int] = [0] * 512
_LOG: list[int] = [0] * 256


def _build_tables() -> None:
    value = 1
    for power in range(255):
        _EXP[power] = value
        _LOG[value] = power
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for power in range(255, 512):
        _EXP[power] = _EXP[power - 255]


_build_tables()


def _mul(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return _EXP[_LOG[left] + _LOG[right]]


def _generator(degree: int) -> list[int]:
    """The generator polynomial for `degree` error-correction codewords."""
    poly = [1]
    for power in range(degree):
        product = [0] * (len(poly) + 1)
        for index, coefficient in enumerate(poly):
            product[index] ^= coefficient
            product[index + 1] ^= _mul(coefficient, _EXP[power])
        poly = product
    return poly


def _remainder(data: list[int], degree: int) -> list[int]:
    """The `degree` error-correction codewords for one block."""
    poly = _generator(degree)
    working = list(data) + [0] * degree
    for index in range(len(data)):
        lead = working[index]
        if lead:
            for offset, coefficient in enumerate(poly):
                working[index + offset] ^= _mul(coefficient, lead)
    return working[len(data) :]


# --- the bit stream ----------------------------------------------------------


def _version_for(payload: bytes) -> int:
    """The smallest version of the ten whose level-M capacity holds `payload`."""
    for version in sorted(_BLOCKS_M):
        count_bits = 8 if version < 10 else 16
        needed = 4 + count_bits + 8 * len(payload)
        if needed <= sum(_BLOCKS_M[version][1]) * 8:
            return version
    raise TooLong(
        f"{len(payload)} bytes does not fit a version-10 level-M symbol "
        f"({MAX_BYTES} bytes is the declared envelope of apps/accounts/qr.py)"
    )


def _codewords(payload: bytes, version: int) -> list[int]:
    """Mode, count, data, terminator, padding — then the interleaved blocks."""
    count_bits = 8 if version < 10 else 16
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        bits.extend((value >> shift) & 1 for shift in range(width - 1, -1, -1))

    put(_BYTE_MODE, 4)
    put(len(payload), count_bits)
    for byte in payload:
        put(byte, 8)

    capacity = sum(_BLOCKS_M[version][1]) * 8
    # The terminator is up to four zero bits, and is shorter when the symbol is
    # nearly full — a fixed four would overflow the last codeword.
    bits.extend([0] * min(4, capacity - len(bits)))
    bits.extend([0] * (-len(bits) % 8))

    words = [
        int("".join(str(bit) for bit in bits[at : at + 8]), 2) for at in range(0, len(bits), 8)
    ]
    # The specification's two pad codewords, alternating, starting with 0xEC.
    pad = (0xEC, 0x11)
    spent = 0
    while len(words) < capacity // 8:
        words.append(pad[spent % 2])
        spent += 1

    ecc_length, block_sizes = _BLOCKS_M[version]
    blocks: list[tuple[list[int], list[int]]] = []
    at = 0
    for size in block_sizes:
        data = words[at : at + size]
        at += size
        blocks.append((data, _remainder(data, ecc_length)))

    interleaved: list[int] = []
    for index in range(max(len(data) for data, _ in blocks)):
        interleaved.extend(data[index] for data, _ in blocks if index < len(data))
    for index in range(ecc_length):
        interleaved.extend(ecc[index] for _, ecc in blocks)
    return interleaved


# --- the symbol --------------------------------------------------------------


def _finders(matrix: list[list[int]], fixed: list[list[bool]], size: int) -> None:
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        for down in range(-1, 8):
            for across in range(-1, 8):
                row, column = top + down, left + across
                if not (0 <= row < size and 0 <= column < size):
                    continue
                on_ring = down in (0, 6) or across in (0, 6)
                in_core = 2 <= down <= 4 and 2 <= across <= 4
                inside = 0 <= down <= 6 and 0 <= across <= 6
                matrix[row][column] = 1 if inside and (on_ring or in_core) else 0
                fixed[row][column] = True


def _alignment(matrix: list[list[int]], fixed: list[list[bool]], size: int, version: int) -> None:
    centres = _ALIGNMENT[version]
    if not centres:
        return
    last = centres[-1]
    for row in centres:
        for column in centres:
            if (row, column) in ((6, 6), (6, last), (last, 6)):
                continue
            for down in range(-2, 3):
                for across in range(-2, 3):
                    edge = abs(down) == 2 or abs(across) == 2
                    centre = down == 0 and across == 0
                    matrix[row + down][column + across] = 1 if edge or centre else 0
                    fixed[row + down][column + across] = True


def _reserve_format(fixed: list[list[bool]], size: int, version: int) -> None:
    for index in range(9):
        if index != 6:
            fixed[8][index] = True
            fixed[index][8] = True
    fixed[8][6] = True
    fixed[6][8] = True
    for index in range(8):
        fixed[8][size - 1 - index] = True
        fixed[size - 1 - index][8] = True
    if version >= 7:
        for index in range(18):
            row, column = divmod(index, 3)
            fixed[size - 11 + column][row] = True
            fixed[row][size - 11 + column] = True


def _skeleton(version: int) -> tuple[list[list[int]], list[list[bool]], int]:
    size = 4 * version + 17
    matrix = [[0] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]
    _finders(matrix, fixed, size)
    for index in range(8, size - 8):
        bit = 1 if index % 2 == 0 else 0
        matrix[6][index] = bit
        matrix[index][6] = bit
        fixed[6][index] = True
        fixed[index][6] = True
    _alignment(matrix, fixed, size, version)
    matrix[4 * version + 9][8] = 1
    fixed[4 * version + 9][8] = True
    _reserve_format(fixed, size, version)
    return matrix, fixed, size


def _place(matrix: list[list[int]], fixed: list[list[bool]], size: int, bits: list[int]) -> None:
    """The zigzag, from the bottom-right corner, skipping the timing column."""
    at = 0
    column = size - 1
    upward = True
    while column > 0:
        if column == 6:
            column -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in (0, 1):
                if not fixed[row][column - offset]:
                    matrix[row][column - offset] = bits[at] if at < len(bits) else 0
                    at += 1
        upward = not upward
        column -= 2


def _masked(row: int, column: int, pattern: int) -> bool:
    if pattern == 0:
        return (row + column) % 2 == 0
    if pattern == 1:
        return row % 2 == 0
    if pattern == 2:
        return column % 3 == 0
    if pattern == 3:
        return (row + column) % 3 == 0
    if pattern == 4:
        return (row // 2 + column // 3) % 2 == 0
    if pattern == 5:
        return (row * column) % 2 + (row * column) % 3 == 0
    if pattern == 6:
        return ((row * column) % 2 + (row * column) % 3) % 2 == 0
    return ((row + column) % 2 + (row * column) % 3) % 2 == 0


def _format_bits(pattern: int) -> int:
    data = (_ECC_LEVEL_M << 3) | pattern
    rest = data
    for _ in range(10):
        rest = (rest << 1) ^ (0x537 * ((rest >> 9) & 1))
    return ((data << 10) | rest) ^ 0x5412


def _version_bits(version: int) -> int:
    rest = version
    for _ in range(12):
        rest = (rest << 1) ^ (0x1F25 * ((rest >> 11) & 1))
    return (version << 12) | rest


#: Where each of the format string's 15 bits goes, as `(row, column)`, bit 0
#: first. **TWO COPIES, AND THEY ARE NOT MIRROR IMAGES OF EACH OTHER** —
#: which is exactly the trap this table exists to close.
#:
#: The rung that wrote this module transcribed the reference implementation's
#: `set_module(x, y, …)` as `matrix[x][y]`, and that call takes x as the
#: COLUMN and y as the ROW. The result placed all 30 format modules
#: transposed, every symbol carried a format field a decoder reads
#: bit-reversed, and **not one symbol this module produced was readable by
#: any real scanner** — while an in-tree reader that borrowed the same
#: helpers decoded every one of them, because it made the same mistake in
#: the other direction. V-A-W3 found it with zxing-cpp and jsQR; the table
#: below is pinned bit-for-bit against `segno` in
#: `test_signin_door.py::test_the_format_field_is_the_one_the_specification_
#: publishes`, for all eight masks.
_FORMAT_CELLS_FIRST: tuple[tuple[int, int], ...] = (
    *((index, 8) for index in range(6)),
    (7, 8),
    (8, 8),
    (8, 7),
    *((8, 14 - index) for index in range(9, 15)),
)


def _format_cells_second(size: int) -> tuple[tuple[int, int], ...]:
    return (
        *((8, size - 1 - index) for index in range(8)),
        *((size - 15 + index, 8) for index in range(8, 15)),
    )


def _stamp(matrix: list[list[int]], size: int, version: int, pattern: int) -> None:
    fmt = _format_bits(pattern)
    for cells in (_FORMAT_CELLS_FIRST, _format_cells_second(size)):
        for index, (row, column) in enumerate(cells):
            matrix[row][column] = (fmt >> index) & 1
    matrix[size - 8][8] = 1
    if version >= 7:
        info = _version_bits(version)
        for index in range(18):
            row, column = divmod(index, 3)
            bit = (info >> index) & 1
            matrix[size - 11 + column][row] = bit
            matrix[row][size - 11 + column] = bit


def _penalty(matrix: list[list[int]], size: int) -> int:
    """The specification's four penalty rules, summed. Lower is a better mask."""
    score = 0
    lines = [list(row) for row in matrix]
    lines += [[matrix[row][column] for row in range(size)] for column in range(size)]
    for line in lines:
        run, previous = 1, line[0]
        for cell in line[1:]:
            if cell == previous:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, previous = 1, cell
        if run >= 5:
            score += 3 + (run - 5)
        for at in range(size - 10):
            window = line[at : at + 11]
            if window in ([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]):
                score += 40
    for row in range(size - 1):
        for column in range(size - 1):
            block = {
                matrix[row][column],
                matrix[row][column + 1],
                matrix[row + 1][column],
                matrix[row + 1][column + 1],
            }
            if len(block) == 1:
                score += 3
    dark = sum(sum(row) for row in matrix)
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


def encode(payload: str) -> list[list[bool]]:
    """The module matrix for `payload`: `True` is a dark module.

    Byte mode, level M, the smallest of versions 1–10 that holds it, and the
    mask chosen by the specification's own penalty score rather than fixed —
    a fixed mask is how a symbol picks up a run of eight identical rows that a
    camera reads as a timing pattern.
    """
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise TooLong(
            f"{len(encoded)} bytes does not fit a version-10 level-M symbol "
            f"({MAX_BYTES} bytes is the declared envelope of apps/accounts/qr.py)"
        )
    version = _version_for(encoded)
    words = _codewords(encoded, version)
    bits = [(word >> shift) & 1 for word in words for shift in range(7, -1, -1)]
    bits += [0] * _REMAINDER[version]

    base, fixed, size = _skeleton(version)
    _place(base, fixed, size, bits)

    def stamped(pattern: int) -> list[list[int]]:
        candidate = [list(row) for row in base]
        for row in range(size):
            for column in range(size):
                if not fixed[row][column] and _masked(row, column, pattern):
                    candidate[row][column] ^= 1
        _stamp(candidate, size, version, pattern)
        return candidate

    best = stamped(0)
    best_score = _penalty(best, size)
    for pattern in range(1, 8):
        candidate = stamped(pattern)
        score = _penalty(candidate, size)
        if score < best_score:
            best, best_score = candidate, score
    return [[cell == 1 for cell in row] for row in best]


def svg(payload: str, *, pixels: int = 208, quiet: int = 4) -> SafeString:
    """`payload` as an inline SVG element, sized in CSS pixels.

    **Black on white, always, in both themes.** A QR symbol is read by a
    camera looking for a light field with dark modules in it, and a dark-mode
    palette that inverted it would be a symbol a phone will not decode. The
    white here is the quiet zone as much as the background: four modules of it
    on every side, which is the specification's minimum and the reason `quiet`
    is a number with a default rather than a decoration.

    The result is marked safe because it contains nothing derived from
    `payload` except module coordinates — see this module's docstring.
    """
    modules = encode(payload)
    size = len(modules) + 2 * quiet
    path = "".join(
        f"M{column + quiet} {row + quiet}h1v1h-1z"
        for row, line in enumerate(modules)
        for column, dark in enumerate(line)
        if dark
    )
    # Marked safe on the property stated in the module docstring: every
    # character below is either a literal of this function or a decimal
    # integer derived from a module coordinate. `payload` reaches `encode`
    # and nothing else.
    return mark_safe(  # noqa: S308 — only literals and integers from module coordinates, above
        f'<svg viewBox="0 0 {size} {size}" width="{pixels}" height="{pixels}" '
        f'role="img" aria-label="A square code to scan with an authenticator app" '
        f'shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
        f'<path d="{path}" fill="#000000"/>'
        f"</svg>"
    )
