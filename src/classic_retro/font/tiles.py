"""Game Boy Advance 4bpp tiles: the pixel format of most glyph cells.

A tile is 8x8 pixels of 4-bit palette indices, row by row, two pixels a byte,
the left one in the low nibble. A cell larger than a tile is several tiles,
stored row by row (``columns=False``) or column by column (``columns=True``).
"""

from __future__ import annotations

from collections.abc import Sequence

from classic_retro.core.errors import ClassicRetroError, ErrorCode

TILE = 8
TILE_BYTES = 32


def _grid(width: int, height: int, columns: bool) -> list[tuple[int, int]]:
    """Top-left pixel of every tile in storage order."""
    across, down = range(0, width, TILE), range(0, height, TILE)
    if columns:
        return [(x, y) for x in across for y in down]
    return [(x, y) for y in down for x in across]


def pack_4bpp(pixels: Sequence[Sequence[int]], *, columns: bool = False) -> bytes:
    """The tiles of an image whose sides are multiples of 8 pixels."""
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    if not width or width % TILE or height % TILE or any(len(row) != width for row in pixels):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"A {width}x{height} image is not whole 8x8 tiles"
        )
    data = bytearray()
    for left, top in _grid(width, height, columns):
        for row in pixels[top : top + TILE]:
            for x in range(left, left + TILE, 2):
                low, high = row[x], row[x + 1]
                if not (0 <= low <= 0xF and 0 <= high <= 0xF):
                    raise ClassicRetroError(
                        ErrorCode.FONT_BUILD_FAILED, "A 4bpp pixel is a palette index 0-15"
                    )
                data.append(low | high << 4)
    return bytes(data)


def unpack_4bpp(
    data: bytes, width: int, height: int, *, columns: bool = False
) -> tuple[tuple[int, ...], ...]:
    """The pixels of ``width`` x ``height`` stored as 4bpp tiles."""
    if width % TILE or height % TILE or len(data) != width * height // 2:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"{len(data)} bytes are not a {width}x{height} image"
        )
    rows = [[0] * width for _ in range(height)]
    for number, (left, top) in enumerate(_grid(width, height, columns)):
        tile = data[number * TILE_BYTES : (number + 1) * TILE_BYTES]
        for y in range(TILE):
            for x in range(0, TILE, 2):
                value = tile[y * 4 + x // 2]
                rows[top + y][left + x] = value & 0xF
                rows[top + y][left + x + 1] = value >> 4
    return tuple(tuple(row) for row in rows)
