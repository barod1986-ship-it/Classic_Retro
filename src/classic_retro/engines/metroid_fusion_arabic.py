"""Arabic support for the *Metroid Fusion* text engine.

The ROM overlay (``classic_retro.rom.metroid_fusion_arabic``) turns the
new-file intro's text and the briefings on the map right to left without
changing how their routines move their pen. They still lay a line out from
the left; the hooks draw each right-to-left glyph at the mirror of its place
on a line of ``LINE_WIDTH`` pixels:

    left' = LINE_WIDTH - pen - width

A line then starts at the right edge and grows leftwards, and the typewriter
reveals it from the right. The glyphs are not flipped: only their places are
mirrored. A translated text holds them in right-to-left paint order, the
first glyph of a line being its rightmost one.

The right-to-left glyphs have codes from 0xB040 (``RTL_GLYPH_CODES``), which
every routine draws as glyphs (a briefing reads 0x8000 up as commands but
``Bxxx`` other than ``B001``..``B003``): the game's ``DrawCharacter`` reads
glyph ``c`` at ``0x08682FAC + 32 * c``, which for these codes falls in the
padding at the end of the image, where the overlay puts their sheet; a hook
gives their widths. Every glyph takes two tile columns, so it may be 16 pixels
wide: no form is split.

Glyphs are drawn in the game's style, ink (2) inside a one-pixel outline (3)
on all eight sides, from the reference font at the largest size whose forms
fit the 16x16 cell with their outline: ink on rows 1..14, the letters on the
baseline of row 11. Joined letters touch: a form has no outline column on a
side where it joins its neighbour, and its ink reaches that edge. A dot whose
coverage stays just under the ink level keeps its strongest pixel (medial
beh's, at the reference size). At the reference size, hamza above alef is
drawn by hand above a shortened alef, and final and isolated yeh are raised a
row. The space is the game's own
(``SPACE``, 6 pixels), and ``.``, ``!`` and ``:`` are drawn by hand.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
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
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    INK,
    INTRO,
    NAVIGATION,
    NEW_PAGE,
    NEWLINE,
    OUTLINE,
    PEN_SET,
    QUESTION,
    TILE_BYTES,
    TILE_ROW_BYTES,
    MfCommand,
    MfLine,
    Piece,
    is_command,
    lay_out,
    moved_pen,
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
# A dot whose coverage stays under the ink level keeps its strongest pixel.
MARK_LEVEL = 60
SIZES = range(14, 7, -1)
# The outline needs a free row above and below the ink.
TOP_INK_ROW = 1
BOTTOM_INK_ROW = GLYPH_ROWS - 2
# The game's space and its width in the USA font; the ROM build checks it.
SPACE = 0x0040
SPACE_WIDTH = 6
# Right-to-left glyph codes: 0xB040 up, one code every two in each row of 32
# (a glyph uses the next code's tiles for its right half), rows of 32 codes
# alternating with the rows of their lower halves. A briefing reads 0x8000 up
# as commands but the glyphs Bxxx (from B004) and Dxxx; the first row starts
# past B001..B003.
RTL_FIRST_CODE = 0xB040
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
# ship computer's box, a monologue page of nine lines, a briefing's two-line
# box and the objective question (a line, then its two options).
LINE_WIDTH = 224
STRIP = "strip"
PAGE = "page"
BRIEFING = "briefing"
QUESTION_BOX = "question"
LINES_PER_PAGE = {STRIP: 2, PAGE: 9, BRIEFING: 2, QUESTION_BOX: 2}
RENDERER_DIALECTS = {STRIP: INTRO, PAGE: INTRO, BRIEFING: NAVIGATION, QUESTION_BOX: QUESTION}
# A stretch of a line, in pixels from its start: (start, end).
Span = tuple[int, int]
# Where a line ends on the 240-pixel screen: it starts at x = 8.
LINE_RIGHT = 8 + LINE_WIDTH
# The question's cursor stands this far left of an option's end.
QUESTION_CURSOR_GAP = 12


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
            character: _drawn(font, character)
            for character in characters
            if character not in _MARKED_ALEF
        }
        for composed, (alef, mark) in _MARKED_ALEF.items():
            if composed in characters:
                source = rendered.get(alef) or _drawn(font, alef)
                rendered[composed] = alef_with_mark(composed, source, mark)
        for character in _RAISED_FORMS & set(rendered):
            rendered[character] = raised_form(
                character, rendered[character], height=BOTTOM_INK_ROW + 1, baseline=BASELINE
            )
        return {character: _outlined(character, form) for character, form in rendered.items()}
    except FormDoesNotFit:
        return None


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    return draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)


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
        dialect = RENDERER_DIALECTS[renderer]
        for piece in pieces:
            if isinstance(piece, MfCommand) and not is_command(piece.unit, dialect):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"The {renderer} does not read {piece.notation} as a command",
                )
        stream = arabic_stream(pieces)
        reject_mirrored(stream, "Metroid Fusion Arabic v1")
        reject_combining_marks(stream, "Metroid Fusion Arabic font v1")
        units: list[int] = []
        for token in rtl_paint_order(self.pipeline, stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    units.extend(self.codes(character))
                continue
            units.extend(command_codes(token, "Metroid Fusion"))
        lines = lay_out(units, self._width, dialect)
        _check_lines(lines, renderer)
        if renderer == QUESTION_BOX and (not units or is_command(units[-1], dialect)):
            # The question reads the unit after its last glyph as the end.
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION, "The question must end with a glyph"
            )
        if self.font is None:
            return MfArabicEncoding(tuple(units), None)
        for number, line in enumerate(lines, 1):
            if line.width > LINE_WIDTH:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {line.width}px; it holds {LINE_WIDTH}px",
                )
            _check_overlap(line, number)
        return MfArabicEncoding(tuple(units), tuple(line.width for line in lines))

    def _width(self, code: int) -> int:
        return self.font.width(code) if self.font is not None else 0

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "Metroid Fusion Arabic")


def _check_lines(lines: Sequence[MfLine], renderer: str) -> None:
    """Every page holds its lines; a briefing's box scrolls only when the reader presses A."""
    limit = LINES_PER_PAGE[renderer]
    for line in lines:
        if renderer == BRIEFING:
            if line.start == NEWLINE and line.number >= limit:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A briefing's box holds {limit} lines: a line end on the second would "
                    "scroll it at once ({FC00} waits for A, {FD00} clears the box)",
                )
        elif line.number >= limit:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW, f"A page of the {renderer} holds {limit} lines"
            )


def _check_overlap(line: MfLine, number: int) -> None:
    """A pen command must not put a glyph over another (spaces are blank)."""
    end = None
    for place in sorted(line.places, key=lambda place: place.pen):
        if place.unit == SPACE:
            continue
        if end is not None and place.pen < end:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW, f"Line {number}: glyphs overlap at pen {place.pen}"
            )
        end = place.end


def question_options(units: Sequence[int], width: Callable[[int], int]) -> tuple[Span, ...]:
    """Where the question's options lie on its second line: from pen to end.

    An option is the glyphs a ``83xx`` puts on the line, spaces aside.
    """
    # Each option's start and, once it has a glyph, its end.
    options: list[list[int]] = []
    pen = 0
    second_line = False
    for unit in units:
        if unit == NEWLINE:
            second_line, pen = True, 0
        elif is_command(unit, QUESTION):
            pen = moved_pen(unit, pen, QUESTION)
            if second_line and unit & 0xFF00 == PEN_SET:
                options.append([])
        else:
            glyph_width = width(unit)
            if options and unit != SPACE:
                option = options[-1]
                if not option:
                    option.append(pen)
                option[1:] = [pen + glyph_width]
            pen += glyph_width
    return tuple((option[0], option[1]) for option in options if option)


def question_cursor_x(option: Span) -> int:
    """The x of the question's cursor on an option: left of its mirrored place.

    The cursor is a triangle pointing right, drawn from x - 1 to x + 5 as it
    bobs; an option at ``start``..``end`` on the line shows at ``LINE_RIGHT - end``
    up to ``LINE_RIGHT - start`` on the screen.
    """
    return LINE_RIGHT - option[1] - QUESTION_CURSOR_GAP


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; only line ends may move.

    A pen advance (``80xx``) keeps its place, not its amount.
    """
    require_same_commands("Metroid Fusion", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The screen: a line from x = 8 to 232 on a 240-pixel screen, 16 pixels a
# line, white ink in a dark outline over the cutscene or in the briefing's
# box. A briefing draws colour n as 2 + 2n (ink) and 3 + 2n (outline): its
# palette has red, magenta, yellow, green, blue and cyan for colours 1 to 6,
# each outlined in black.
_BRIEFING_INKS = (
    (255, 0, 0),
    (255, 0, 255),
    (255, 255, 0),
    (0, 255, 0),
    (0, 0, 255),
    (0, 255, 255),
)
PREVIEW_COLOURS = {
    0: (24, 36, 80),
    INK: (248, 248, 248),
    OUTLINE: (16, 16, 24),
    **{INK + 2 * colour: ink for colour, ink in enumerate(_BRIEFING_INKS, 1)},
    **{OUTLINE + 2 * colour: (0, 0, 0) for colour in range(1, len(_BRIEFING_INKS) + 1)},
}
PREVIEW_WIDTH = 240
PREVIEW_RIGHT = LINE_RIGHT
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
    """A translated text as the game shows it: pages side by side, the first on the right.

    Every line ends at the right edge of the text and grows leftwards; a
    briefing's colours show. The arrow that waits for A is a triangle: at the
    bottom left in the strip, in the middle under the text on a page and at
    the bottom of a briefing's box. The question's cursor points at its first
    option, from its left.
    """
    lines = lay_out(units, font.width, RENDERER_DIALECTS[renderer])
    rows = max(LINES_PER_PAGE[renderer], *(line.number + 1 for line in lines))
    pages = [_page(rows) for _ in range(lines[-1].page + 1)]
    for line in lines:
        page = pages[line.page]
        for place in line.places:
            if place.unit == SPACE:
                continue
            left = PREVIEW_RIGHT - place.end
            shift = 2 * place.colour
            for y, values in enumerate(font.glyphs[place.unit].pixels):
                for x, value in enumerate(values[: place.width]):
                    if value:
                        colour = PREVIEW_COLOURS.get(value + shift, PREVIEW_COLOURS[value])
                        page.putpixel((left + x, 4 + line.number * GLYPH_ROWS + y), colour)
        if line.waits:
            _arrow(page, renderer, line.number)
    if renderer == QUESTION_BOX:
        options = question_options(units, font.width)
        if options:
            _cursor(pages[0], question_cursor_x(options[0]))
    return pages_right_to_left(pages)


def _page(lines: int) -> Image.Image:
    return Image.new("RGB", (PREVIEW_WIDTH, lines * GLYPH_ROWS + 8), PREVIEW_COLOURS[0])


def _arrow(page: Image.Image, renderer: str, row: int) -> None:
    if renderer == STRIP:
        left, top = 1, page.height - 7
    elif renderer == PAGE:
        left, top = PREVIEW_WIDTH // 2 - 5, 4 + (row + 1) * GLYPH_ROWS
    else:
        left, top = PREVIEW_WIDTH // 2 - 3, page.height - 5
    ImageDraw.Draw(page).polygon(
        [(left, top), (left + 6, top), (left + 3, top + 3)], fill=PREVIEW_ARROW
    )


def _cursor(page: Image.Image, x: int) -> None:
    top = 4 + GLYPH_ROWS + 4
    ImageDraw.Draw(page).polygon(
        [(x + 1, top), (x + 1, top + 7), (x + 4, top + 4)], fill=PREVIEW_ARROW
    )


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 120)
