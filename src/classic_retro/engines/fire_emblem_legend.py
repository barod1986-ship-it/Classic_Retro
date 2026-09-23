"""The opening legend of *Fire Emblem: The Sacred Stones* as Arabic images.

Before a new game the legend of the Sacred Stones is shown as seven full-screen
subtitle images (``gOpSubtitleGfxLut``: LZ77 tiles, LZ77 tile map and a
display time each), not as text. Each image is 240x160 on palette 3: index 0
is transparent and 1..13 is a ramp from cream (full coverage) to dark brown
(the anti-aliased edge). Lines are centred and 24 pixels apart.

The tile map is ``width - 1``, ``height - 1`` (bytes) and then one u16 entry
per tile, bottom row first (``TmApplyTsa``); the game adds the tile base and
palette. Tiles of image 2 ("The Sacred Stones") are loaded at ``0x06005000``,
between the stone background and the tile map, which leaves 128 tiles; the
others start at ``0x06001000``.

The Arabic lines are shaped with HarfBuzz (``font.shaped_text``) at the size
where the font's alef is as tall as the English capitals (10 pixels).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.shaped_text import ShapedLineRenderer

SCREEN_WIDTH = 240
SCREEN_HEIGHT = 160
TILE = 8
TILES_X = SCREEN_WIDTH // TILE
TILES_Y = SCREEN_HEIGHT // TILE
TILE_BYTES = 32
LINE_PITCH = 24
# Text keeps 8 pixels from each screen edge, like the English images.
MAX_LINE_WIDTH = SCREEN_WIDTH - 16
# Baseline below the centre of a line: Arabic ink spans about -12..+5 pixels.
BASELINE_DROP = 4
ALEF_HEIGHT = 10
RAMP_LEVELS = 13
COVERAGE_FLOOR = 40
SUBTITLE_COUNT = 7
TITLE_SUBTITLE = 2
TITLE_TILE_BUDGET = 128
TILE_BUDGET = 512

# gPal_OpSubtitle (USA), for previews; index 0 is transparent in the game.
USA_SUBTITLE_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0), (248, 248, 240), (240, 240, 232), (232, 232, 216), (224, 216, 200),
    (216, 208, 184), (208, 200, 176), (200, 184, 160), (192, 176, 144), (184, 168, 128),
    (176, 152, 120), (168, 144, 104), (128, 112, 72), (96, 72, 40), (56, 40, 16), (0, 0, 0),
)  # fmt: skip


def legend_font_size(font_path: Path) -> int:
    """Pixel size at which the font's alef is as tall as the English capitals."""
    font = TTFont(font_path.expanduser())
    cmap = font.getBestCmap() or {}
    if 0x0627 not in cmap:
        raise ClassicRetroError(ErrorCode.MISSING_GLYPH, "The font has no alef (U+0627)")
    bounds = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[cmap[0x0627]].draw(bounds)
    if bounds.bounds is None or bounds.bounds[3] <= 0:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "The font's alef has no outline")
    return max(8, round(ALEF_HEIGHT * font["head"].unitsPerEm / bounds.bounds[3]))


def validate_legend_lines(lines: tuple[str, ...]) -> None:
    """Arabic letters, spaces and punctuation only: no marks, no bidi runs to reorder."""
    if not 1 <= len(lines) <= 5:
        raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, "A legend image holds 1 to 5 lines")
    for line in lines:
        for character in line:
            category = unicodedata.category(character)
            if category.startswith("M"):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_ARABIC_MARK,
                    f"Legend lines take no combining marks: U+{ord(character):04X}",
                )
            if category.startswith(("L", "N")) and "ARABIC" not in unicodedata.name(character, ""):
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT,
                    f"Legend lines take Arabic letters only, not {character!r}",
                )


def _ramp() -> list[int]:
    """Coverage 0..255 -> palette index (0, or 13 dark edge .. 1 cream)."""
    table = []
    for coverage in range(256):
        if coverage < COVERAGE_FLOOR:
            table.append(0)
        else:
            step = (255 - coverage) * (RAMP_LEVELS - 1) / (255 - COVERAGE_FLOOR)
            table.append(1 + round(step))
    return table


@dataclass(frozen=True, slots=True)
class LegendImage:
    """Palette indices (row-major bytes), the lines and their widths."""

    pixels: bytes
    lines: tuple[str, ...]
    widths: tuple[int, ...]

    def preview(self) -> Image.Image:
        image = Image.frombytes("P", (SCREEN_WIDTH, SCREEN_HEIGHT), self.pixels)
        image.putpalette([value for colour in USA_SUBTITLE_PALETTE for value in colour])
        return image


def render_legend_image(renderer: ShapedLineRenderer, lines: tuple[str, ...]) -> LegendImage:
    """Centre the lines on a 240x160 canvas and map coverage onto the palette ramp."""
    validate_legend_lines(lines)
    canvas = Image.new("L", (SCREEN_WIDTH, SCREEN_HEIGHT), 0)
    widths = []
    for number, line in enumerate(lines):
        width = renderer.width(line)
        if width > MAX_LINE_WIDTH:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Legend line {line!r} needs {width:.0f}px; the screen holds {MAX_LINE_WIDTH}px",
            )
        centre = SCREEN_HEIGHT / 2 + (number - (len(lines) - 1) / 2) * LINE_PITCH
        renderer.draw(canvas, line, (SCREEN_WIDTH - width) / 2, round(centre) + BASELINE_DROP)
        widths.append(round(width))
    pixels = canvas.point(_ramp()).tobytes()
    return LegendImage(pixels=pixels, lines=lines, widths=tuple(widths))


@dataclass(frozen=True, slots=True)
class EncodedLegend:
    tiles: bytes
    tile_map: bytes

    @property
    def tile_count(self) -> int:
        return len(self.tiles) // TILE_BYTES


def encode_legend_image(image: LegendImage, budget: int = TILE_BUDGET) -> EncodedLegend:
    """Unique 4bpp tiles (tile 0 blank) and the bottom-up tile map ``TmApplyTsa`` reads."""
    tiles = [bytes(TILE_BYTES)]
    index = {tiles[0]: 0}
    rows: list[list[int]] = []
    for tile_y in range(TILES_Y):
        row = []
        for tile_x in range(TILES_X):
            data = bytearray()
            for y in range(TILE):
                start = (tile_y * TILE + y) * SCREEN_WIDTH + tile_x * TILE
                pixels = image.pixels[start : start + TILE]
                data += bytes(pixels[x] | pixels[x + 1] << 4 for x in range(0, TILE, 2))
            tile = bytes(data)
            if tile not in index:
                index[tile] = len(tiles)
                tiles.append(tile)
            row.append(index[tile])
        rows.append(row)
    if len(tiles) > budget:
        raise ClassicRetroError(
            ErrorCode.RELOCATION_OVERFLOW,
            f"Legend image needs {len(tiles)} tiles; its VRAM holds {budget}",
        )
    tile_map = bytearray((TILES_X - 1, TILES_Y - 1))
    for row in reversed(rows):
        for entry in row:
            tile_map += entry.to_bytes(2, "little")
    return EncodedLegend(tiles=b"".join(tiles), tile_map=bytes(tile_map))


def decode_legend_image(tiles: bytes, tile_map: bytes) -> bytes:
    """Palette indices back from tiles and a tile map (flips honoured), for verification."""
    width, height = tile_map[0] + 1, tile_map[1] + 1
    pixels = bytearray(width * TILE * height * TILE)
    entries = [
        int.from_bytes(tile_map[2 + 2 * n : 4 + 2 * n], "little") for n in range(width * height)
    ]
    for number, entry in enumerate(entries):
        tile_y = height - 1 - number // width
        tile_x = number % width
        tile = tiles[(entry & 0x3FF) * TILE_BYTES : (entry & 0x3FF) * TILE_BYTES + TILE_BYTES]
        for y in range(TILE):
            for x in range(TILE):
                source_x = TILE - 1 - x if entry & 0x400 else x
                source_y = TILE - 1 - y if entry & 0x800 else y
                byte = tile[source_y * 4 + source_x // 2]
                value = byte >> 4 if source_x & 1 else byte & 0xF
                pixels[(tile_y * TILE + y) * width * TILE + tile_x * TILE + x] = value
    return bytes(pixels)


def legend_budget(index: int) -> int:
    return TITLE_TILE_BUDGET if index == TITLE_SUBTITLE else TILE_BUDGET


def legend_sheet(images: list[LegendImage]) -> Image.Image:
    """All images side by side (four per row) for review."""
    columns = 4
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (SCREEN_WIDTH + 4) + 4, rows * (SCREEN_HEIGHT + 4) + 4))
    for number, image in enumerate(images):
        x = 4 + (number % columns) * (SCREEN_WIDTH + 4)
        y = 4 + (number // columns) * (SCREEN_HEIGHT + 4)
        sheet.paste(image.preview().convert("RGB"), (x, y))
    return sheet
