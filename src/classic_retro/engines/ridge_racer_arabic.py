"""Arabic support for the program strings of *Ridge Racer* (PlayStation).

The game draws a string a character at a time, each character a sprite of its
font's page, a cell apart (``engines.ridge_racer``). The overlay
(``classic_retro.rom.ridge_racer_arabic``) hooks both of its text routines: a
string whose first byte is ``CENTRE`` or ``MIRROR`` is Arabic, and the hook
draws it from glyphs of its own, each a sprite as wide as the glyph, out of a
corner of VRAM the game leaves free (``ATLAS_X``: 192x64 pixels of the texture
page at (960, 0)). Any other string goes to the game's routine as before.

An Arabic string is its mode, a parameter, the codes of its glyphs in visual
order (left to right) and a zero:

- ``CENTRE``, n: centred on the English it replaces, n of the font's cells
  wide; the pen starts at ``x + (n * cell - width) / 2``, so a shadow the game
  draws a pixel right and down stays a pixel right and down;
- ``MIRROR``, 128 + d: ending at the mirror of the English's left edge,
  ``320 - x``, moved d pixels.

The codes run from 0x20 (``ARABIC_CODES``): the space's first, then the
buttons, the punctuation, the digits and the contextual forms, as many as the
strings use. The two fonts share the codes; each font's table gives a code's
glyph, its place in the atlas, its size and its row offset from the string's y:

- The small font's letters are seven rows of strokes two pixels wide in the
  palette's colour 1, the rest clear. Its Arabic glyphs are drawn at the
  largest size where every form fits a cell of 15 rows, from four rows above
  the string's y, on the row under the English letters (``CELLS``), in colour
  1, every stroke one pixel wide made two (``emboldened``) but where that would
  join ink that was apart: dots and counters stay open.
- The large font's letters are chrome: a black outline (colour 2) round a
  fill whose colour follows the row (``SHADES``, the palette's 5 to 12),
  lighter on its top and left edges. Its Arabic glyphs are drawn the same way,
  at the largest size where every form fits a cell of 26 rows on the English
  letters' baseline, outlined but on the sides where they join a neighbour.

The buttons of the small font and the punctuation the reference font lacks or
draws too small are drawn by hand (``HAND_DRAWN``); the digits and the other
forms come from the reference font; the space is a blank glyph.
"""

from __future__ import annotations

import struct
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import check_logical_arabic, no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ridge_racer import BUTTONS
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.font.glyph_raster import (
    FormDoesNotFit,
    Pixel,
    arabic_font_file,
    draw_form,
    drop_shadow,
    emboldened,
    largest_fitting_size,
    pattern_pixels,
    raised_marks,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Ridge Racer Arabic"
SMALL = "small"
LARGE = "large"
FONTS = (SMALL, LARGE)
# An Arabic string's first byte, and MIRROR's parameter for no move.
CENTRE = 1
MIRROR = 2
MIRROR_BIAS = 128
SCREEN_WIDTH = 320
# The glyph codes: a table of 128 entries a font, from the space's code.
ARABIC_CODES = tuple(range(0x20, 0xA0))
GLYPH_ENTRY = 8
TABLE_BYTES = GLYPH_ENTRY * len(ARABIC_CODES)
# Pixel values: clear, the small font's colour, the large font's outline.
CLEAR = 0
INK = 1
OUTLINE = 2
INK_LEVEL = 128
MARK_LEVEL = 60
DIGITS = "0123456789"
_AROUND = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)


@dataclass(frozen=True, slots=True)
class GlyphCell:
    """A font's cell: its rows, the row under its letters, the row of the string's y its
    first row is drawn at (``y + top``), the sizes tried, the widest glyph, the space's
    width and the English cell's, a character's step."""

    rows: int
    baseline: int
    top: int
    sizes: range
    widest: int
    space: int
    step: int


CELLS = {
    SMALL: GlyphCell(
        rows=15, baseline=11, top=-4, sizes=range(11, 6, -1), widest=16, space=4, step=8
    ),
    LARGE: GlyphCell(
        rows=26, baseline=19, top=-4, sizes=range(20, 10, -1), widest=32, space=7, step=16
    ),
}
# The large font's fill by the row from the string's y, as the English letters'
# (rows 1 to 14; above and below, the nearest); its top edge and its left edge.
SHADES = (0xC, 0x8, 0x9, 0x7, 0x6, 0x5, 0x5, 0x6, 0x7, 0x8, 0x9, 0x8, 0x7, 0x6)
TOP_EDGE = 0xC
LEFT_EDGE = 0xA
# Glyphs drawn by hand: each font's rows of ink and the row of the string's y
# they start on. The small font's are drawn at its weight, the large font's are
# outlined and shaded as its letters.
HAND_DRAWN: dict[str, dict[str, tuple[tuple[str, ...], int]]] = {
    SMALL: {
        BUTTONS[ord("a")]: (
            ("...#...", "..#.#..", "..#.#..", ".#...#.", ".#...#.", "#.....#", "#######"),
            0,
        ),
        BUTTONS[ord("b")]: (("#######",) + ("#.....#",) * 5 + ("#######",), 0),
        BUTTONS[ord("c")]: (("#######",) + (".##.##.",) * 5 + ("#######",), 0),
        BUTTONS[ord("d")]: (
            ("..###..", ".#...#.", "#.....#", "#.....#", "#.....#", ".#...#.", "..###.."),
            0,
        ),
        ".": (("##", "##"), 5),
        ":": (("##", "##", "..", "##", "##"), 1),
        "!": (("##",) * 4 + ("..", "##", "##"), 0),
        "-": (("####",), 3),
        "،": ((".##", "##.", "##", "##"), 3),
        "؛": ((".##", "##.", "##", "##", "..", "##", "##"), 0),
        "؟": ((".####.", "##..##", "##....", ".###..", "..##..", "......", "..##.."), 0),
    },
    LARGE: {
        ".": (("###",) * 3, 11),
        ":": (("###",) * 3 + ("...",) * 5 + ("###",) * 3, 3),
        "!": (("###",) * 8 + ("...",) * 2 + ("###",) * 3, 1),
        "-": (("#######",) * 2, 7),
    },
}


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic fonts can draw, in the order codes follow."""
    hand_drawn = (*HAND_DRAWN[SMALL], *HAND_DRAWN[LARGE])
    order = (" ", *hand_drawn, *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def ridge_racer_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from ``ARABIC_CODES`` for the characters the strings use, in the fonts' order."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="Ridge Racer Arabic glyphs",
    )


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class RrGlyph:
    """A glyph cropped to its rows: its width (the sprite's, and the pen's advance), its
    first row's offset from the string's y and its rows of colours; a blank glyph has no
    rows."""

    width: int
    dy: int
    rows: tuple[tuple[int, ...], ...]

    @property
    def height(self) -> int:
        return len(self.rows)

    def entry(self, u: int, v: int) -> bytes:
        """The table's eight bytes: page position, size, row offset."""
        if not self.height:
            return struct.pack("<4Bb3x", 0, 0, self.width, 0, 0)
        return struct.pack("<4Bb3x", u, v, self.width, self.height, self.dy)


@dataclass(frozen=True, slots=True)
class RrFont:
    """One font's Arabic glyphs by code, and the size they were drawn at."""

    name: str
    glyphs: Mapping[int, RrGlyph]
    font_size: int

    def measure(self, codes: bytes) -> int:
        """A string's width: its glyphs' widths."""
        try:
            return sum(self.glyphs[code].width for code in codes)
        except KeyError as missing:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH,
                f"The {self.name} font has no glyph {missing.args[0]:#04x}",
            ) from None


def _cropped(colours: Mapping[Pixel, int], width: int, top: int) -> RrGlyph:
    rows = [y for _, y in colours]
    first, last = min(rows), max(rows)
    return RrGlyph(
        width,
        top + first,
        tuple(
            tuple(colours.get((x, y), CLEAR) for x in range(width)) for y in range(first, last + 1)
        ),
    )


def small_glyph(ink: Collection[Pixel], advance: int, cell: GlyphCell) -> RrGlyph:
    """Drawn ink in the small font: its strokes two pixels wide, in colour 1, cropped to
    its rows."""
    bold = emboldened(ink)
    width = max(advance, max(x for x, _ in bold) + 1)
    if any(not 0 <= y < cell.rows for _, y in bold) or width > cell.widest:
        raise FormDoesNotFit
    return _cropped(dict.fromkeys(bold, INK), width, cell.top)


def _shade(pixel: Pixel, ink: Collection[Pixel], cell: GlyphCell, open_left: bool) -> int:
    x, y = pixel
    if (x, y - 1) not in ink:
        return TOP_EDGE
    if (x - 1, y) not in ink and (open_left or x > 0):
        return LEFT_EDGE
    row = min(max(y + cell.top, 1), len(SHADES))
    return SHADES[row - 1]


def large_glyph(
    ink: Collection[Pixel], cell: GlyphCell, *, joins_left: bool, joins_right: bool
) -> RrGlyph:
    """Ink in the large font: shaded, outlined but on its joining sides, cropped to its
    rows."""
    left = 0 if joins_left else 1
    placed = {(x + left, y) for x, y in ink}
    width = max(x for x, _ in placed) + 1 + (0 if joins_right else 1)
    if any(not 1 <= y <= cell.rows - 2 for _, y in placed) or width > cell.widest:
        raise FormDoesNotFit
    ring = {(x, y) for x, y in drop_shadow(placed, _AROUND, width, cell.rows) if x >= 0}
    colours = dict.fromkeys(ring, OUTLINE)
    colours |= {pixel: _shade(pixel, placed, cell, not joins_left) for pixel in placed}
    return _cropped(colours, width, cell.top)


def _drawn_glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str], name: str
) -> dict[str, RrGlyph] | None:
    """Every character at this size, or None when one leaves the cell."""
    cell = CELLS[name]
    # The last row a mark may take: the large font's outline takes a row below it.
    lowest = cell.rows - (1 if name == SMALL else 2)
    try:
        glyphs = {}
        for character in characters:
            form = draw_form(
                font, character, cell.baseline, ink_level=INK_LEVEL, mark_level=MARK_LEVEL
            )
            form = raised_marks(separated_dots(character, form), lowest)
            if name == SMALL:
                glyphs[character] = small_glyph(form.ink, form.advance, cell)
            else:
                glyphs[character] = large_glyph(
                    form.ink,
                    cell,
                    joins_left=joins_left_neighbour(character),
                    joins_right=joins_right_neighbour(character),
                )
        return glyphs
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(name: str, character: str) -> RrGlyph:
    rows, top = HAND_DRAWN[name][character]
    cell = CELLS[name]
    ink = pattern_pixels(rows, top=top - cell.top)
    if name == SMALL:
        return _cropped(dict.fromkeys(ink, INK), len(rows[0]) + 1, cell.top)
    return large_glyph(ink, cell, joins_left=False, joins_right=False)


def build_ridge_racer_fonts(
    font_path: Path,
    glyph_map: GlyphCodes,
    *,
    small: Collection[str],
    large: Collection[str],
    sizing: Iterable[str] | None = None,
) -> dict[str, RrFont]:
    """The small font's glyphs for the ``small`` characters and the large font's for the
    ``large`` ones.

    Each font's size is the largest where every character of ``sizing`` fits: the
    whole repertoire and the digits, whatever the strings use, so a new string never
    changes the size of the others (a test may give a few characters).
    """
    fonts: dict[str, RrFont] = {}
    drawable = {*arabic_presentation_repertoire(), *DIGITS}
    for name, used in ((SMALL, small), (LARGE, large)):
        cell = CELLS[name]
        hand_drawn = HAND_DRAWN[name]
        wanted = {character for character in used if character != " "}
        unknown = sorted(wanted - drawable - set(hand_drawn))
        if unknown:
            raise no_glyph(unknown[0], f"{PROFILE} ({name} font)")
        drawn_set = set(drawable if sizing is None else sizing) | (wanted - set(hand_drawn))
        drawn = tuple(sorted(drawn_set - set(hand_drawn) - {" "}, key=ord))
        _, size, rendered = largest_fitting_size(
            contextual_font_data(arabic_font_file(font_path), drawn),
            cell.sizes,
            lambda font, drawn=drawn, name=name: _drawn_glyphs(font, drawn, name),
            f"Selected font cannot fit Ridge Racer's {name} font",
        )
        for character in hand_drawn:
            rendered[character] = hand_drawn_glyph(name, character)
        rendered[" "] = RrGlyph(cell.space, 0, ())
        glyphs = {}
        for character in used:
            code = glyph_map.code(character)
            if code is None or character not in rendered:
                raise no_glyph(character, f"{PROFILE} ({name} font)")
            glyphs[code] = rendered[character]
        fonts[name] = RrFont(name, glyphs, size)
    return fonts


# ---------------------------------------------------------------------------
# Encoding translated strings


def visual_text(text: str) -> str:
    """Logical text in visual order, left to right, its letters shaped."""
    check_logical_arabic(text, PROFILE)
    stream = TokenStream((TextToken(text),))
    reject_mirrored(stream, PROFILE)
    reject_combining_marks(stream, PROFILE)
    painted = rtl_paint_order(legacy_renderer_pipeline(), stream)
    return "".join(token.text for token in painted.tokens if isinstance(token, TextToken))[::-1]


@dataclass(frozen=True, slots=True)
class EncodedString:
    """A translated string's bytes and, with fonts, its width and where its pen starts."""

    data: bytes
    codes: bytes
    width: int | None
    pen: int | None


def pen_start(mode: int, parameter: int, x: int, width: int, step: int) -> int:
    """Where the hook starts drawing a string ``width`` pixels wide that the game draws at
    ``x``."""
    if mode == CENTRE:
        return x + (parameter * step - width) // 2
    if mode == MIRROR:
        return SCREEN_WIDTH - x - width + parameter - MIRROR_BIAS
    raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"No Arabic string mode {mode}")


class RidgeRacerArabicEncoder:
    """Convert a logical Arabic string into the hook's: mode, parameter, glyphs in visual
    order, zero."""

    def __init__(self, glyph_map: GlyphCodes, fonts: Mapping[str, RrFont] | None = None) -> None:
        self.glyph_map = glyph_map
        self.fonts = fonts

    def codes(self, visual: str) -> bytes:
        output = bytearray()
        for character in visual:
            code = self.glyph_map.code(character)
            if code is None:
                raise no_glyph(character, PROFILE)
            output.append(code)
        return bytes(output)

    def encode(self, text: str, font: str, mode: int, parameter: int, x: int) -> EncodedString:
        if not 0 < parameter < 0x100:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"An Arabic string's parameter is a byte: {parameter}"
            )
        codes = self.codes(visual_text(text))
        data = bytes((mode, parameter)) + codes + b"\x00"
        if self.fonts is None:
            pen_start(mode, parameter, x, 0, CELLS[font].step)
            return EncodedString(data, codes, None, None)
        width = self.fonts[font].measure(codes)
        pen = pen_start(mode, parameter, x, width, CELLS[font].step)
        if pen < 0 or pen + width > SCREEN_WIDTH:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"The string takes pixels {pen} to {pen + width}; the screen has "
                f"0 to {SCREEN_WIDTH}",
            )
        return EncodedString(data, codes, width, pen)


# ---------------------------------------------------------------------------
# The atlas

# The free corner of VRAM: 48 halfwords (192 pixels of four bits) wide and 64
# rows, at (976, 192), which is (64, 192) in the texture page at (960, 0).
ATLAS_X = 976
ATLAS_Y = 192
ATLAS_U = 64
ATLAS_V = 192
ATLAS_WIDTH = 192
ATLAS_ROWS = 64
ATLAS_ROW_BYTES = ATLAS_WIDTH // 2
# GetTPage(0, 0, 960, 0): four-bit pixels, the page at (960, 0).
ATLAS_TPAGE = 960 // 64


def pack_atlas(sizes: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Where rectangles of ``sizes`` (width, height) go in the atlas, the tallest first on
    shelves from the top left: (u, v) in the texture page each; (0, 0) for a blank."""
    order = sorted(
        (index for index, (_, height) in enumerate(sizes) if height),
        key=lambda index: (-sizes[index][1], -sizes[index][0], index),
    )
    places = [(0, 0)] * len(sizes)
    x = y = shelf = 0
    for index in order:
        width, height = sizes[index]
        if x + width > ATLAS_WIDTH:
            x, y, shelf = 0, y + shelf, 0
        if width > ATLAS_WIDTH or y + height > ATLAS_ROWS:
            raise ClassicRetroError(
                ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                f"No room in the atlas ({ATLAS_WIDTH}x{ATLAS_ROWS}) for a {width}x{height} glyph",
            )
        places[index] = (ATLAS_U + x, ATLAS_V + y)
        x += width
        shelf = max(shelf, height)
    return places


@dataclass(frozen=True, slots=True)
class Atlas:
    """The glyphs' pixels, as uploaded (four bits a pixel, the first in the low bits), the
    rows they take and each font's table."""

    pixels: bytes
    rows: int
    tables: dict[str, bytes]
    places: dict[tuple[str, int], tuple[int, int]]


def build_atlas(fonts: Mapping[str, RrFont]) -> Atlas:
    keys = [(name, code) for name in FONTS for code in sorted(fonts[name].glyphs)]
    glyphs = [fonts[name].glyphs[code] for name, code in keys]
    spots = pack_atlas([(glyph.width, glyph.height) for glyph in glyphs])
    places = dict(zip(keys, spots, strict=True))
    rows = max(
        (v - ATLAS_V + glyph.height for glyph, (_, v) in zip(glyphs, spots, strict=True)),
        default=0,
    )
    pixels = bytearray(rows * ATLAS_ROW_BYTES)
    for glyph, (u, v) in zip(glyphs, spots, strict=True):
        for y, row in enumerate(glyph.rows):
            for x, value in enumerate(row):
                column = u - ATLAS_U + x
                at = (v - ATLAS_V + y) * ATLAS_ROW_BYTES + column // 2
                pixels[at] |= value << 4 * (column % 2)
    tables = {}
    for name in FONTS:
        table = bytearray(TABLE_BYTES)
        for code, glyph in fonts[name].glyphs.items():
            u, v = places[name, code]
            at = GLYPH_ENTRY * (code - ARABIC_CODES[0])
            table[at : at + GLYPH_ENTRY] = glyph.entry(u, v)
        tables[name] = bytes(table)
    return Atlas(bytes(pixels), rows, tables, places)


# ---------------------------------------------------------------------------
# Previews

# The small font's white; the large font's outline and a grey-blue chrome.
PREVIEW_COLOURS = {
    INK: (255, 255, 255),
    OUTLINE: (0, 0, 0),
    **{index: (40 + 18 * index, 60 + 16 * index, 90 + 13 * index) for index in range(3, 13)},
}
PREVIEW_BACKGROUND = (58, 60, 52)


def font_preview(fonts: Mapping[str, RrFont]) -> Image.Image:
    """Atlas of the glyphs, the small font's then the large font's, each in its cell:
    the cropped rows grey, the width's end dark red."""
    entries = [
        (name, fonts[name].glyphs[code]) for name in FONTS for code in sorted(fonts[name].glyphs)
    ]
    rows = max(cell.rows for cell in CELLS.values())
    columns = max(cell.widest for cell in CELLS.values())

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        name, glyph = entries[number]
        cell = CELLS[name]
        if x >= glyph.width or y >= cell.rows:
            return (70, 20, 20)
        row = y + cell.top - glyph.dy
        if not 0 <= row < glyph.height:
            return (50, 50, 50)
        return PREVIEW_COLOURS.get(glyph.rows[row][x], (110, 110, 110))

    return glyph_atlas(len(entries), columns, rows, colour)


PREVIEW_ABOVE = 8
PREVIEW_ROWS = 32


def string_preview(encoded: EncodedString, font: RrFont) -> Image.Image:
    """A string on the screen's 320 pixels, from 8 rows above its y: the English cell's
    rows marked by a dim rule each side."""
    if encoded.pen is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the fonts")
    image = Image.new("RGB", (SCREEN_WIDTH, PREVIEW_ROWS), PREVIEW_BACKGROUND)
    x = encoded.pen
    for code in encoded.codes:
        glyph = font.glyphs[code]
        for row, values in enumerate(glyph.rows):
            for column, value in enumerate(values):
                point = (x + column, PREVIEW_ABOVE + glyph.dy + row)
                if value and 0 <= point[0] < image.width and 0 <= point[1] < image.height:
                    image.putpixel(point, PREVIEW_COLOURS.get(value, (110, 110, 110)))
        x += glyph.width
    step = CELLS[font.name].step
    for y in (PREVIEW_ABOVE - 1, PREVIEW_ABOVE + step):
        for column in range(0, 4):
            image.putpixel((column, y), (120, 120, 90))
            image.putpixel((SCREEN_WIDTH - 1 - column, y), (120, 120, 90))
    return image


def strings_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
