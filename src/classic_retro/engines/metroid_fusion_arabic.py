"""Arabic support for the *Metroid Fusion* text engine.

The ROM overlay (``classic_retro.rom.metroid_fusion_arabic``) turns the
new-file intro's text right to left without changing how its routines move
their pen. They still lay a line out from the left; for a text of the Arabic
bank, the hooks draw each glyph at the mirror of its place on a line of
``LINE_WIDTH`` pixels:

    left' = LINE_WIDTH - pen - width

A line then starts at the right edge and grows leftwards, and the typewriter
reveals it from the right. The glyphs are not flipped: only their places are
mirrored. A translated text holds them in right-to-left paint order, the
first glyph of a line being its rightmost one.

The right-to-left glyphs have codes from 0x9000 (``RTL_GLYPH_CODES``): the
game's ``DrawCharacter`` reads glyph ``c`` at ``0x08682FAC + 32 * c``, which
for these codes falls in the padding at the end of the image, where the
overlay puts their sheet; a hook gives their widths. Every glyph takes two
tile columns, so it may be 16 pixels wide: no form is split.

Glyphs are drawn in the game's style, ink (2) inside a one-pixel outline (3)
on all eight sides, from the reference font at the largest size whose forms
fit the 16x16 cell with their outline: ink on rows 1..14, the letters on the
baseline of row 11. Joined letters touch: a form has no outline column on a
side where it joins its neighbour, and its ink reaches that edge. At the
reference size, hamza above alef is drawn by hand above a shortened alef, and
final and isolated yeh are raised a row. The space is the game's own
(``SPACE``, 6 pixels), and ``.``, ``!`` and ``:`` are drawn by hand.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.metroid_fusion import (
    ARROW,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    INK,
    NEW_PAGE,
    NEWLINE,
    OUTLINE,
    TILE_BYTES,
    TILE_ROW_BYTES,
    WAIT,
    MfCommand,
    Piece,
    notation_skeleton,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    Pixel,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    drop_shadow,
    largest_fitting_size,
    pattern_pixels,
    raised_form,
)
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.font.tiles import pack_4bpp
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

BASELINE = 11
INK_LEVEL = 140
SIZES = range(14, 7, -1)
# The outline needs a free row above and below the ink.
TOP_INK_ROW = 1
BOTTOM_INK_ROW = GLYPH_ROWS - 2
# The game's space and its width in the USA font; the ROM build checks it.
SPACE = 0x0040
SPACE_WIDTH = 6
# Right-to-left glyph codes: 0x9000 up, one code every two in each row of 32
# (a glyph uses the next code's tiles for its right half), rows of 32 codes
# alternating with the rows of their lower halves.
RTL_FIRST_CODE = 0x9000
RTL_CODE_SPAN = 0x800
CODES_PER_ROW = 64
GLYPHS_PER_ROW = 16
SHEET_ROW_BYTES = 2 * TILE_ROW_BYTES
RTL_GLYPH_CODES = tuple(
    RTL_FIRST_CODE + CODES_PER_ROW * row + 2 * slot
    for row in range(RTL_CODE_SPAN // CODES_PER_ROW)
    for slot in range(GLYPHS_PER_ROW)
)
# Punctuation the reference font lacks, drawn on the baseline.
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    ".": ("##", "##"),
    "!": ("##", "##", "##", "##", "##", "..", "##", "##"),
    ":": ("##", "##", "..", "..", "##", "##"),
}
# Hamza above alef reaches row 0 at the reference size: the font's alef, cut
# below a hamza drawn on rows 1-2.
_HAMZA_MARK = ("..", "##", "#.")
_MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {
    "ﺃ": ("ﺍ", _HAMZA_MARK),
    "ﺄ": ("ﺎ", _HAMZA_MARK),
}
# The dots of final and isolated yeh reach row 15: these forms are raised a
# row; the final form keeps a pixel on the joining row.
_RAISED_FORMS = frozenset("ﻱﻲ")
# The eight neighbours of an ink pixel that its outline covers.
_RING = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)

# The text routines: a line of 224 pixels; the intro's two-line strip and the
# ship computer's box, or a monologue page of nine lines.
LINE_WIDTH = 224
STRIP = "strip"
PAGE = "page"
LINES_PER_PAGE = {STRIP: 2, PAGE: 9}


def mf_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Right-to-left codes for ``characters``, in order."""
    return assign_glyph_codes(characters, RTL_GLYPH_CODES, what="Metroid Fusion Arabic glyphs")


@lru_cache(maxsize=1)
def build_metroid_fusion_arabic_glyph_map() -> GlyphCodes:
    """The game's space, then the drawn punctuation and the forms at their own codes."""
    assigned = mf_glyph_codes((*_PUNCTUATION_INK, *arabic_presentation_repertoire()))
    return GlyphCodes((" ", *assigned.characters), {" ": (SPACE,), **assigned.sequences})


@dataclass(frozen=True, slots=True)
class MfRtlGlyph:
    """A right-to-left glyph: its width and 16 rows of 16 pixels."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def tiles(self) -> tuple[bytes, bytes, bytes, bytes]:
        """Its four 4bpp tiles: top left, top right, bottom left, bottom right."""
        data = pack_4bpp(self.pixels)
        return (
            data[:TILE_BYTES],
            data[TILE_BYTES : 2 * TILE_BYTES],
            data[2 * TILE_BYTES : 3 * TILE_BYTES],
            data[3 * TILE_BYTES :],
        )


def outlined_glyph(ink: Iterable[Pixel], *, joins_left: bool, joins_right: bool) -> MfRtlGlyph:
    """Ink with its outline, one column of outline on each side that does not join.

    The ink's first column is 0; on a joining side the ink reaches the edge,
    where the neighbour's ink goes on. Raises ``FormDoesNotFit`` when the glyph
    leaves the 16x16 cell.
    """
    left = 0 if joins_left else 1
    placed = {(x + left, y) for x, y in ink}
    width = max(x for x, _ in placed) + 1 + (0 if joins_right else 1)
    if width > GLYPH_COLUMNS or any(not TOP_INK_ROW <= y <= BOTTOM_INK_ROW for _, y in placed):
        raise FormDoesNotFit
    outline = {
        (x, y) for x, y in drop_shadow(placed, _RING, width, GLYPH_ROWS) if x >= 0 and y >= 0
    }
    pixels = tuple(
        tuple(
            INK if (x, y) in placed else OUTLINE if (x, y) in outline else 0
            for x in range(GLYPH_COLUMNS)
        )
        for y in range(GLYPH_ROWS)
    )
    return MfRtlGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class MfRtlFont:
    """Every right-to-left glyph by code, and each character's codes in paint order."""

    glyphs: dict[int, MfRtlGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def width(self, code: int) -> int:
        return SPACE_WIDTH if code == SPACE else self.glyphs[code].width

    def sheet(self) -> bytes:
        """The glyphs' tiles as ``DrawCharacter`` reads them, from code ``RTL_FIRST_CODE``.

        A row holds 16 glyphs: their top tiles (two each), then their bottom tiles.
        """
        rows = max(code - RTL_FIRST_CODE for code in self.glyphs) // CODES_PER_ROW + 1
        sheet = bytearray(rows * SHEET_ROW_BYTES)
        for code, glyph in self.glyphs.items():
            start = (code - RTL_FIRST_CODE) * TILE_BYTES
            top_left, top_right, bottom_left, bottom_right = glyph.tiles()
            for offset, tile in (
                (0, top_left),
                (TILE_BYTES, top_right),
                (TILE_ROW_BYTES, bottom_left),
                (TILE_ROW_BYTES + TILE_BYTES, bottom_right),
            ):
                sheet[start + offset : start + offset + TILE_BYTES] = tile
        return bytes(sheet)

    def width_table(self) -> bytes:
        """A width for every code from ``RTL_FIRST_CODE``; 0 where there is no glyph."""
        table = bytearray(RTL_CODE_SPAN)
        for code, glyph in self.glyphs.items():
            table[code - RTL_FIRST_CODE] = glyph.width
        return bytes(table)


def build_metroid_fusion_rtl_font(
    font_path: Path, *, glyph_map: GlyphCodes | None = None
) -> MfRtlFont:
    """Rasterize the Arabic forms into outlined 16x16 glyphs and add the drawn punctuation."""
    glyph_map = glyph_map or build_metroid_fusion_arabic_glyph_map()
    arabic = tuple(
        character
        for character in glyph_map.characters
        if character != " " and character not in _PUNCTUATION_INK
    )
    _, size, glyphs = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), tuple(sorted(arabic, key=ord))),
        SIZES,
        lambda font: _outlined_forms(font, arabic),
        "Selected font cannot fit the Metroid Fusion 16x16 glyphs",
    )
    for character, rows in _PUNCTUATION_INK.items():
        if character in glyph_map.characters:
            ink = pattern_pixels(rows, top=BASELINE - len(rows))
            glyphs[character] = outlined_glyph(ink, joins_left=False, joins_right=False)
    by_code: dict[int, MfRtlGlyph] = {}
    sequences: dict[str, tuple[int, ...]] = {}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        sequences[character] = codes
        if character != " ":
            by_code[codes[0]] = glyphs[character]
    return MfRtlFont(glyphs=by_code, sequences=sequences, font_size=size)


def _outlined_forms(
    font: ImageFont.FreeTypeFont, characters: tuple[str, ...]
) -> dict[str, MfRtlGlyph] | None:
    """Every form at this size, outlined, or None when one leaves the 16x16 cell."""
    try:
        rendered = {
            character: draw_form(font, character, BASELINE, ink_level=INK_LEVEL)
            for character in characters
            if character not in _MARKED_ALEF
        }
        for composed, (alef, mark) in _MARKED_ALEF.items():
            if composed in characters:
                source = rendered.get(alef) or draw_form(font, alef, BASELINE, ink_level=INK_LEVEL)
                rendered[composed] = alef_with_mark(composed, source, mark)
        for character in _RAISED_FORMS & set(rendered):
            rendered[character] = raised_form(
                character, rendered[character], height=BOTTOM_INK_ROW + 1, baseline=BASELINE
            )
        return {character: _outlined(character, form) for character, form in rendered.items()}
    except FormDoesNotFit:
        return None


def _outlined(character: str, form: DrawnForm) -> MfRtlGlyph:
    return outlined_glyph(
        form.ink,
        joins_left=joins_left_neighbour(character),
        joins_right=joins_right_neighbour(character),
    )


# ---------------------------------------------------------------------------
# Encoding translated texts


def arabic_command_token(token_id: str, command: MfCommand) -> InlineToken:
    if command.unit == NEWLINE:
        kind = TokenKind.LINE_BREAK
    elif command.unit == NEW_PAGE:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return command_token(token_id, kind, f"{command.unit:04X}", name=f"{command.unit:04X}")


def arabic_stream(pieces: Sequence[Piece], prefix: str = "t") -> TokenStream:
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"{prefix}{number}", piece))
    return TokenStream(tuple(tokens))


def _supported(unit: int) -> bool:
    return unit in (NEWLINE, NEW_PAGE, ARROW) or unit & 0xFF00 == WAIT


@dataclass(frozen=True, slots=True)
class MfArabicEncoding:
    """A translated text (without its final ``FF00``) and, with a font, its line widths."""

    units: tuple[int, ...]
    line_widths: tuple[int, ...] | None


class MfArabicEncoder:
    """Convert logical Arabic text into Metroid Fusion units in right-to-left paint order."""

    def __init__(self, font: MfRtlFont | None = None) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.font = font
        self.sequences: Mapping[str, tuple[int, ...]] = (
            font.sequences
            if font is not None
            else build_metroid_fusion_arabic_glyph_map().sequences
        )

    def encode(self, pieces: Sequence[Piece], renderer: str = STRIP) -> MfArabicEncoding:
        for piece in pieces:
            if isinstance(piece, MfCommand) and not _supported(piece.unit):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Metroid Fusion Arabic v1 does not support {piece.notation}",
                )
        limit = LINES_PER_PAGE[renderer]
        stream = arabic_stream(pieces)
        reject_mirrored(stream, "Metroid Fusion Arabic v1")
        reject_combining_marks(stream, "Metroid Fusion Arabic font v1")
        units: list[int] = []
        lines: list[int] = [0]
        page_lines = 1
        for token in rtl_paint_order(self.pipeline, stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    for code in self.codes(character):
                        units.append(code)
                        lines[-1] += self._width(code)
                continue
            (unit,) = command_codes(token, "Metroid Fusion")
            units.append(unit)
            if unit == NEWLINE:
                lines.append(0)
                page_lines += 1
                if page_lines > limit:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A page of the {renderer} holds {limit} lines",
                    )
            elif unit == NEW_PAGE:
                lines.append(0)
                page_lines = 1
        if self.font is None:
            return MfArabicEncoding(tuple(units), None)
        for number, width in enumerate(lines, 1):
            if width > LINE_WIDTH:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {width}px; it holds {LINE_WIDTH}px",
                )
        return MfArabicEncoding(tuple(units), tuple(lines))

    def _width(self, code: int) -> int:
        return self.font.width(code) if self.font is not None else 0

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "Metroid Fusion Arabic")


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's control units must equal the original's; only line ends may move."""
    require_same_commands("Metroid Fusion", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The screen: a line from x = 8 to 232 on a 240-pixel screen, 16 pixels a
# line, white ink in a dark outline over the cutscene.
PREVIEW_COLOURS = {0: (24, 36, 80), INK: (248, 248, 248), OUTLINE: (16, 16, 24)}
PREVIEW_WIDTH = 240
PREVIEW_RIGHT = 8 + LINE_WIDTH
PREVIEW_ARROW = (240, 200, 40)


def font_preview(font: MfRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, outline grey, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixels[y][x]
        if value == INK:
            return (255, 255, 255)
        if value == OUTLINE:
            return (110, 110, 130)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), GLYPH_COLUMNS, GLYPH_ROWS, colour)


def message_preview(font: MfRtlFont, units: Sequence[int], renderer: str = STRIP) -> Image.Image:
    """A translated text as the intro shows it: pages side by side, the first on the right.

    Every line ends at the right edge of the text and grows leftwards. The
    arrow that waits for A is a triangle: at the bottom left in the strip, in
    the middle under the text on a page.
    """
    lines = LINES_PER_PAGE[renderer]
    pages = [_page(lines)]
    pen = 0
    row = 0
    for unit in units:
        if unit == NEWLINE:
            pen, row = 0, row + 1
        elif unit == NEW_PAGE:
            pages.append(_page(lines))
            pen, row = 0, 0
        elif unit == ARROW:
            _arrow(pages[-1], renderer, row)
        elif unit & 0xFF00 == WAIT:
            continue
        else:
            width = font.width(unit)
            if unit != SPACE:
                glyph = font.glyphs[unit]
                left = PREVIEW_RIGHT - pen - width
                for y, values in enumerate(glyph.pixels):
                    for x, value in enumerate(values[:width]):
                        if value:
                            pages[-1].putpixel(
                                (left + x, 4 + row * GLYPH_ROWS + y), PREVIEW_COLOURS[value]
                            )
            pen += width
    return pages_right_to_left(pages)


def _page(lines: int) -> Image.Image:
    return Image.new("RGB", (PREVIEW_WIDTH, lines * GLYPH_ROWS + 8), PREVIEW_COLOURS[0])


def _arrow(page: Image.Image, renderer: str, row: int) -> None:
    if renderer == STRIP:
        left, top = 1, page.height - 7
    else:
        left, top = PREVIEW_WIDTH // 2 - 5, 4 + (row + 1) * GLYPH_ROWS
    ImageDraw.Draw(page).polygon(
        [(left, top), (left + 6, top), (left + 3, top + 3)], fill=PREVIEW_ARROW
    )


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 120)
