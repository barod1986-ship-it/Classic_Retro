"""Nitro fonts (NFTR), the bitmap fonts of Nintendo DS games.

An NFTR file holds blocks after a 16-byte header:

- ``FINF``: the font's line feed, the glyph drawn for unknown characters and
  the offsets of the other blocks;
- ``CGLP``: the glyphs, all one cell (width x height) of 1, 2 or 4 bits per
  pixel, each a bit stream of its rows, most significant bit first, padded to
  a whole number of bytes;
- ``CWDH``: for each glyph its left bearing, the width of its bitmap and its
  advance;
- ``CMAP`` blocks, chained: which glyph each character code draws, as a range
  (type 0), a table (type 1) or pairs (type 2).

``NftrFont`` reads a font and changes glyphs and widths in place: the layout of
the file never changes, so a changed font has the size of the original.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

Glyph = tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class GlyphWidth:
    left: int
    width: int
    advance: int


class NftrFont:
    """A DS bitmap font whose glyphs and widths can be read and replaced."""

    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)
        magic, bom, _, size, header_size, blocks = struct.unpack_from("<4sHHIHH", data, 0)
        if magic != b"RTFN" or bom != 0xFEFF or size != len(data):
            raise ClassicRetroError(ErrorCode.INVALID_FONT_PROFILE, "Not an NFTR font")
        found: dict[bytes, list[int]] = {}
        position = header_size
        for _ in range(blocks):
            block, block_size = struct.unpack_from("<4sI", data, position)
            if block_size < 8 or position + block_size > len(data):
                raise ClassicRetroError(ErrorCode.INVALID_FONT_PROFILE, "NFTR block out of range")
            found.setdefault(block, []).append(position)
            position += block_size
        for block in (b"FNIF", b"PLGC", b"HDWC", b"PAMC"):
            if block not in found:
                raise ClassicRetroError(
                    ErrorCode.INVALID_FONT_PROFILE, f"NFTR font has no {block[::-1].decode()} block"
                )
        info = found[b"FNIF"][0]
        self.line_feed = data[info + 9]
        (self.unknown_glyph,) = struct.unpack_from("<H", data, info + 10)
        glyphs = found[b"PLGC"][0]
        (
            self.cell_width,
            self.cell_height,
            self.glyph_bytes,
            self.baseline,
            self.max_width,
            self.bits,
        ) = struct.unpack_from("<BBHBBB", data, glyphs + 8)
        if self.bits not in (1, 2, 4) or (
            self.glyph_bytes * 8 < self.cell_width * self.cell_height * self.bits
        ):
            raise ClassicRetroError(ErrorCode.INVALID_FONT_PROFILE, "Unsupported NFTR glyph cell")
        self._glyphs = glyphs + 16
        (glyphs_size,) = struct.unpack_from("<I", data, glyphs + 4)
        self.glyph_count = (glyphs_size - 16) // self.glyph_bytes
        widths = found[b"HDWC"][0]
        self.first_width, self.last_width = struct.unpack_from("<HH", data, widths + 8)
        self._widths = widths + 16
        self.codes = self._character_map(found[b"PAMC"])

    def _character_map(self, blocks: Sequence[int]) -> dict[int, int]:
        codes: dict[int, int] = {}
        data = self.data
        for block in blocks:
            first, last, kind = struct.unpack_from("<HHH", data, block + 8)
            table = block + 20
            if kind == 0:
                (glyph,) = struct.unpack_from("<H", data, table)
                codes.update({code: glyph + code - first for code in range(first, last + 1)})
            elif kind == 1:
                for number, code in enumerate(range(first, last + 1)):
                    (glyph,) = struct.unpack_from("<H", data, table + 2 * number)
                    if glyph != 0xFFFF:
                        codes[code] = glyph
            elif kind == 2:
                (count,) = struct.unpack_from("<H", data, table)
                for number in range(count):
                    code, glyph = struct.unpack_from("<HH", data, table + 2 + 4 * number)
                    codes[code] = glyph
            else:
                raise ClassicRetroError(
                    ErrorCode.INVALID_FONT_PROFILE, f"Unknown NFTR character map type {kind}"
                )
        return codes

    def _check(self, index: int) -> None:
        if not 0 <= index < self.glyph_count:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No glyph {index} in the font")

    def glyph(self, index: int) -> Glyph:
        """The glyph's rows of pixel values."""
        self._check(index)
        start = self._glyphs + index * self.glyph_bytes
        bits = int.from_bytes(self.data[start : start + self.glyph_bytes], "big")
        total = 8 * self.glyph_bytes
        mask = (1 << self.bits) - 1
        return tuple(
            tuple(
                (bits >> (total - (y * self.cell_width + x + 1) * self.bits)) & mask
                for x in range(self.cell_width)
            )
            for y in range(self.cell_height)
        )

    def width(self, index: int) -> GlyphWidth:
        if not self.first_width <= index <= self.last_width:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No width for glyph {index}")
        left, width, advance = struct.unpack_from(
            "<bBB", self.data, self._widths + 3 * (index - self.first_width)
        )
        return GlyphWidth(left, width, advance)

    def set_glyph(self, index: int, rows: Glyph, width: GlyphWidth) -> None:
        """Replace a glyph's pixels (a full cell of rows) and its widths."""
        self._check(index)
        self.width(index)
        limit = 1 << self.bits
        if len(rows) != self.cell_height or any(
            len(row) != self.cell_width or any(not 0 <= value < limit for value in row)
            for row in rows
        ):
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                f"A glyph is {self.cell_width}x{self.cell_height} values below {limit}",
            )
        if not (-128 <= width.left < 128 and 0 <= width.width < 256 and 0 <= width.advance < 256):
            raise ClassicRetroError(ErrorCode.INVALID_FONT_PROFILE, "Glyph widths out of range")
        bits = 0
        for row in rows:
            for value in row:
                bits = bits << self.bits | value
        bits <<= 8 * self.glyph_bytes - self.cell_width * self.cell_height * self.bits
        start = self._glyphs + index * self.glyph_bytes
        self.data[start : start + self.glyph_bytes] = bits.to_bytes(self.glyph_bytes, "big")
        struct.pack_into(
            "<bBB",
            self.data,
            self._widths + 3 * (index - self.first_width),
            width.left,
            width.width,
            width.advance,
        )

    def to_bytes(self) -> bytes:
        return bytes(self.data)
