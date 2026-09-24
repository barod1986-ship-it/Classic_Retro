"""Arabic support for the *Mario & Luigi: Superstar Saga* text engine.

The ROM overlay (``classic_retro.rom.mlss_arabic``) adds a right-to-left font
as font 1 of the printer's three font lists (empty in the USA image): a
translated character is the prefix ``0xFE`` and a code of that font, so the
game's measuring passes, which size the speech bubbles and centre the
subtitles, already count the new glyphs. When the printer draws a glyph of
this font, the hook mirrors its pen position inside the text area,

    draw_x = box_width * 8 + left_margin - right_margin - pen_x - glyph_width

so a left-aligned line starts at the right margin and grows leftwards, and a
centred line stays centred. A translated message holds only these glyphs,
spaces included, in right-to-left paint order: the first glyph of a line is
its rightmost one.

Glyphs are 16x12 cells (the game's are 8x12): the letters are drawn from the
reference font at the largest size whose forms fit, on a baseline at row 9 so
that they end on row 8 like the game's Latin letters. Coverage becomes the
two ink values of the game's fonts: 1 (the text colour) from ``INK_LEVEL`` of
255, 3 (the colour after it: the light grey of the speech bubbles, the blue
edge of the subtitles) from ``SOFT_LEVEL``. Hamza above alef and the tails of
final and isolated yeh do not fit at that size; see ``_MARKED_ALEF`` and
``_RAISED_FORMS``.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.paint import reject_combining_marks, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mlss import (
    COMMAND,
    END,
    FONT_GLYPHS,
    NEWLINE,
    PAGE,
    TILE,
    MlssCommand,
    MlssFont,
    MlssLayout,
    Piece,
    command_length,
    glyph_bytes,
    measure_text,
    notation_skeleton,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream

ARABIC_PREFIX = 0xFE
ARABIC_FONT_INDEX = COMMAND - ARABIC_PREFIX
# Codes of the right-to-left font: printable, never 0x00 or 0xFF, and below
# the font prefixes so that no pass can take one for a prefix.
ARABIC_CODES = tuple(range(0x21, 0xFA))
CELL_WIDTH = 16
CELL_HEIGHT = 12
BASELINE = 9
INK_LEVEL = 140
SOFT_LEVEL = 60
TEXT = 1
SOFT = 3
SPACE_ADVANCE = 4
# Widest line: the game's boxes grow with the header up to 25 tiles for most
# of its own messages.
MAX_LINE_WIDTH = 25 * TILE

# Copies of the game's own glyphs (the speech bubbles' font) for Arabic text,
# by character: sentence punctuation and Western digits. The game's letters
# already end on row 8, like the Arabic ones. Quotation marks are drawn
# mirrored: in right-to-left text the opening guillemet is painted first, on
# the right, pointing right.
LATIN_COPIES: dict[str, int] = {
    ".": 0x2E, "!": 0x21, ":": 0x3A, "-": 0x2D,
    **{str(digit): 0x30 + digit for digit in range(10)},
    "«": 0xBB, "»": 0xAB,
}  # fmt: skip
# Their advances in right-to-left text: the game's glyphs keep their free
# column on the left, so each copy is widened until a column stays free after
# its ink too (the USA font's "«" is also narrower than its ink). The ROM build
# checks that the game's glyphs give these.
RTL_LATIN_WIDTHS: dict[str, int] = {
    ".": 4, "!": 5, ":": 4, "-": 7, "0": 8, "1": 6, "2": 8, "3": 8, "4": 8, "5": 8,
    "6": 8, "7": 7, "8": 8, "9": 8, "«": 8, "»": 8,
}  # fmt: skip
# Hamza above alef reaches above the cell at this size: these forms are the
# font's alef, cut one row below a small drawn hamza (rows 0-1).
_HAMZA_MARK = ("##", "#.")
_MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {
    "ﺃ": ("ﺍ", _HAMZA_MARK),
    "ﺄ": ("ﺎ", _HAMZA_MARK),
}
# The dots of final and isolated yeh fall one row below the cell: these forms
# are raised by a row; the final form keeps a pixel on the joining row.
_RAISED_FORMS = frozenset("ﻱﻲ")
# The font cannot mirror these, and the shared bidi step does not apply rule L4.
_MIRRORED = frozenset("()[]{}<>‹›")


@dataclass(frozen=True, slots=True)
class MlssArabicGlyphMap:
    """Character -> code of the right-to-left font."""

    space: int
    codes: dict[str, int]

    def all_codes(self) -> tuple[int, ...]:
        return (self.space, *sorted(self.codes.values()))


@lru_cache(maxsize=1)
def build_mlss_arabic_glyph_map() -> MlssArabicGlyphMap:
    characters = (*LATIN_COPIES, *arabic_presentation_repertoire())
    if 1 + len(characters) > len(ARABIC_CODES):
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"Right-to-left glyphs need {1 + len(characters)} codes; "
            f"the font has {len(ARABIC_CODES)}",
        )
    codes = iter(ARABIC_CODES)
    space = next(codes)
    return MlssArabicGlyphMap(
        space=space, codes={character: next(codes) for character in characters}
    )


@dataclass(frozen=True, slots=True)
class MlssRtlGlyph:
    """A right-to-left glyph: advance and 16x12 pixels (values 0, 1 and 3)."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def data(self) -> bytes:
        return glyph_bytes(self.pixels, CELL_WIDTH, CELL_HEIGHT)


def _glyph(values: dict[tuple[int, int], int], width: int) -> MlssRtlGlyph:
    """Pixels inside the advance only: a glyph never paints over its neighbours."""
    if not 1 <= width <= CELL_WIDTH:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, f"Glyph advance {width} is not 1..16")
    pixels = tuple(
        tuple(values.get((x, y), 0) if x < width else 0 for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    )
    return MlssRtlGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class MlssRtlFont:
    """Every right-to-left glyph by code, and each character's code."""

    glyphs: dict[int, MlssRtlGlyph]
    codes: dict[str, int]
    space: int
    font_size: int

    def game_font(self) -> MlssFont:
        """The font as the printer reads it (unused codes: empty, one pixel wide)."""
        empty = bytes(CELL_WIDTH * CELL_HEIGHT // 4)
        widths = tuple(
            self.glyphs[code].width if code in self.glyphs else 1 for code in range(FONT_GLYPHS)
        )
        glyphs = tuple(
            self.glyphs[code].data() if code in self.glyphs else empty
            for code in range(FONT_GLYPHS)
        )
        return MlssFont(CELL_WIDTH, CELL_HEIGHT, widths, glyphs)


def latin_rtl_glyphs(game_font: MlssFont) -> dict[str, MlssRtlGlyph]:
    """The game's own glyphs for ``LATIN_COPIES``, in the right-to-left cell."""
    glyphs = {}
    for character, code in LATIN_COPIES.items():
        source = game_font.pixels(code)
        values = {
            (x, y): value for y, row in enumerate(source) for x, value in enumerate(row) if value
        }
        if not values:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The game font has no {character!r} to copy"
            )
        width = max(game_font.widths[code], max(x for x, _ in values) + 2)
        if width != RTL_LATIN_WIDTHS[character]:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"The game's {character!r} differs from the USA font",
            )
        glyphs[character] = _glyph(values, width)
    return glyphs


def placeholder_latin_glyphs() -> dict[str, MlssRtlGlyph]:
    """Stand-ins with the game's advances when no ROM is at hand (checks, previews)."""
    glyphs = {}
    for character in LATIN_COPIES:
        width = RTL_LATIN_WIDTHS[character]
        if character in ".:":
            values = {(1, 7): TEXT, (1, 8): TEXT} | (
                {(1, 3): TEXT, (1, 4): TEXT} if character == ":" else {}
            )
        elif character == "!":
            values = {(2, y): TEXT for y in (1, 2, 3, 4, 5, 7, 8)}
        elif character == "-":
            values = {(x, 5): TEXT for x in range(1, 6)}
        else:
            values = {
                (x, y): TEXT
                for x in range(1, width - 1)
                for y in range(1, 9)
                if x in (1, width - 2) or y in (1, 8)
            }
        glyphs[character] = _glyph(values, width)
    return glyphs


def build_mlss_rtl_font(
    font_path: Path,
    latin: dict[str, MlssRtlGlyph] | None = None,
    *,
    glyph_map: MlssArabicGlyphMap | None = None,
) -> MlssRtlFont:
    """Rasterize the Arabic forms into 16x12 cells and add the Latin copies."""
    glyph_map = glyph_map or build_mlss_arabic_glyph_map()
    font_path = font_path.expanduser()
    if not font_path.is_file():
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"Arabic font file not found: {font_path}"
        )
    latin = latin if latin is not None else placeholder_latin_glyphs()
    arabic = tuple(character for character in glyph_map.codes if character not in LATIN_COPIES)
    # Hamza above alef is drawn from the plain alef forms, not from the font.
    outlined = {character for character in arabic if character not in _MARKED_ALEF}
    outlined |= {alef for composed, (alef, _) in _MARKED_ALEF.items() if composed in arabic}
    font_data = contextual_font_data(font_path, tuple(sorted(outlined, key=ord)))
    size, rendered = _choose_size(font_data, arabic)
    glyphs: dict[int, MlssRtlGlyph] = {glyph_map.space: _glyph({}, SPACE_ADVANCE)}
    for character, code in glyph_map.codes.items():
        if character in LATIN_COPIES:
            glyphs[code] = latin[character]
        else:
            values, width = rendered[character]
            glyphs[code] = _glyph(values, width)
    return MlssRtlFont(
        glyphs=glyphs, codes=dict(glyph_map.codes), space=glyph_map.space, font_size=size
    )


class _DoesNotFit(Exception):
    pass


Rendered = tuple[dict[tuple[int, int], int], int]


def _choose_size(font_data: bytes, characters: tuple[str, ...]) -> tuple[int, dict[str, Rendered]]:
    """Largest size whose forms fit the 16x12 cell on the row-9 baseline."""
    for size in range(14, 5, -1):
        font = ImageFont.truetype(
            BytesIO(font_data), size=size, layout_engine=ImageFont.Layout.BASIC
        )
        try:
            rendered = {
                character: _rasterize(font, character)
                for character in characters
                if character not in _MARKED_ALEF
            }
            for composed, (alef, mark) in _MARKED_ALEF.items():
                if composed in characters:
                    source = rendered[alef] if alef in rendered else _rasterize(font, alef)
                    rendered[composed] = _marked_alef(composed, source, mark)
            for character in _RAISED_FORMS & set(rendered):
                rendered[character] = _raised(character, rendered[character])
        except _DoesNotFit:
            continue
        if any(_leaves_cell(values) for values, _ in rendered.values()):
            continue
        return size, rendered
    raise ClassicRetroError(
        ErrorCode.FONT_BUILD_FAILED, "Selected font cannot fit the MLSS 16x12 glyph cell"
    )


def _leaves_cell(values: dict[tuple[int, int], int]) -> bool:
    return any(not 0 <= y < CELL_HEIGHT for _, y in values)


def _rasterize(font: ImageFont.FreeTypeFont, character: str) -> Rendered:
    margin = CELL_HEIGHT
    cell = Image.new("L", (CELL_WIDTH * 4, CELL_HEIGHT + 2 * margin), 0)
    left, _, right, _ = font.getbbox(character, anchor="ls")
    ImageDraw.Draw(cell).text(
        (CELL_WIDTH - left, margin + BASELINE), character, font=font, fill=255, anchor="ls"
    )
    pixels = cell.load()
    coverage = {
        (x, y - margin): pixels[x, y]
        for y in range(cell.height)
        for x in range(cell.width)
        if pixels[x, y] >= SOFT_LEVEL
    }
    ink = [(x, y) for (x, y), level in coverage.items() if level >= INK_LEVEL]
    if not ink:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Selected font produced an empty glyph for U+{ord(character):04X}",
        )
    ink_left = min(x for x, _ in ink)
    ink_right = max(x for x, _ in ink) - ink_left
    values = {
        (x - ink_left, y): TEXT if level >= INK_LEVEL else SOFT
        for (x, y), level in coverage.items()
        if x >= ink_left
    }
    if joins_right_neighbour(character):
        # Medial and final forms end at their last ink column, touching the
        # glyph painted before them (on their right).
        width = ink_right + 1
    else:
        width = max(math.ceil(font.getlength(character)), right - left, ink_right + 1)
        if not joins_left_neighbour(character) and width == ink_right + 1:
            width += 1
    if width > CELL_WIDTH:
        raise _DoesNotFit
    return values, width


def _marked_alef(character: str, alef: Rendered, mark: tuple[str, ...]) -> Rendered:
    """The alef cut one row below ``mark``, with the mark drawn from its stroke."""
    values, width = alef
    stroke = min(x for (x, _), value in values.items() if value == TEXT)
    kept = {(x, y): value for (x, y), value in values.items() if y > len(mark)}
    if not any(value == TEXT for value in kept.values()):
        raise _DoesNotFit
    for y, row in enumerate(mark):
        for x, pixel in enumerate(row):
            if pixel == "#":
                kept[(stroke + x, y)] = TEXT
    left = min(x for x, _ in kept)
    kept = {(x - left, y): value for (x, y), value in kept.items()}
    right = max(x for (x, _), value in kept.items() if value == TEXT)
    if joins_right_neighbour(character):
        width = right + 1
    else:
        width = max(width - left, right + 2)
    return kept, width


def _raised(character: str, rendered: Rendered) -> Rendered:
    """One row up when the form reaches below the cell, keeping its join."""
    values, width = rendered
    if max(y for _, y in values) < CELL_HEIGHT:
        return rendered
    raised = {(x, y - 1): value for (x, y), value in values.items()}
    if joins_right_neighbour(character):
        raised[(width - 1, BASELINE - 1)] = TEXT
    return raised, width


def arabic_command_token(token_id: str, command: MlssCommand) -> InlineToken:
    if command.code == NEWLINE:
        kind = TokenKind.LINE_BREAK
    elif command.code == PAGE:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return InlineToken(
        id=token_id,
        kind=kind,
        movement=TokenMovement.ORDERED,
        name=f"FF{command.code:02X}",
        args={"codes": command.data.hex(" ")},
    )


def arabic_stream(pieces: Sequence[Piece], prefix: str = "t") -> TokenStream:
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"{prefix}{number}", piece))
    return TokenStream(tuple(tokens))


@dataclass(frozen=True, slots=True)
class MlssArabicEncoding:
    """A translated text (``FF 0A`` included) and, with a font, its layout."""

    body: bytes
    layout: MlssLayout | None

    def header(self) -> tuple[int, int]:
        if self.layout is None:
            raise ClassicRetroError(
                ErrorCode.INLINE_WIDTH_UNKNOWN, "The header needs the right-to-left font"
            )
        return self.layout.header()


class MlssArabicEncoder:
    """Convert logical Arabic text into MLSS bytes in right-to-left paint order."""

    def __init__(
        self, font: MlssRtlFont | None = None, *, base_font: MlssFont | None = None
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.font = font
        glyph_map = build_mlss_arabic_glyph_map()
        self.codes = dict(font.codes) if font is not None else dict(glyph_map.codes)
        self.space = font.space if font is not None else glyph_map.space
        self.fonts: list[MlssFont | None] | None = None
        if font is not None:
            # Font 0 only gives an empty line its height: the game's 12 rows.
            base = base_font or MlssFont(8, CELL_HEIGHT, (1,) * FONT_GLYPHS, (b"",) * FONT_GLYPHS)
            self.fonts = [base, *([None] * 5)]
            self.fonts[ARABIC_FONT_INDEX] = font.game_font()

    def encode(self, pieces: Sequence[Piece]) -> MlssArabicEncoding:
        """Encode a message text; its last piece must be ``FF 0A``."""
        if not pieces or not isinstance(pieces[-1], MlssCommand) or not pieces[-1].is_end:
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "Arabic text must end with FF 0A")
        for piece in pieces:
            if isinstance(piece, str):
                mirrored = sorted({character for character in piece if character in _MIRRORED})
                if mirrored:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TEXT,
                        "MLSS Arabic v1 cannot mirror bracket glyphs: " + "".join(mirrored),
                    )
        stream = arabic_stream(pieces)
        reject_combining_marks(stream, "MLSS Arabic font v1")
        data = bytearray()
        for token in rtl_paint_order(self.pipeline, stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    data += bytes((ARABIC_PREFIX, self.code(character)))
            else:
                data += bytes.fromhex(str(token.args["codes"]))
        body = bytes(data)
        if self.fonts is None:
            return MlssArabicEncoding(body, None)
        layout = measure_text(body, self.fonts)
        for number, width in enumerate(layout.line_widths, 1):
            if width > MAX_LINE_WIDTH:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {width}px; an MLSS line holds {MAX_LINE_WIDTH}px",
                )
        return MlssArabicEncoding(body, layout)

    def code(self, character: str) -> int:
        if character == " ":
            return self.space
        code = self.codes.get(character)
        if code is not None:
            return code
        if unicodedata.category(character).startswith("L") and "ARABIC" in unicodedata.name(
            character, ""
        ):
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"No MLSS Arabic glyph for U+{ord(character):04X}"
            )
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"MLSS Arabic text has no glyph for {character!r}"
        )


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    target = notation_skeleton(pieces)
    if target != source:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            "MLSS commands differ from the original: " + "".join(source) + " != " + "".join(target),
        )


# Palette of the previews: the speech bubbles' white box, ink and grey.
PREVIEW_COLOURS = {0: (248, 248, 248), TEXT: (56, 56, 56), SOFT: (160, 160, 168)}
# Previews draw a page as the opening's printers lay it out: a box five tiles
# wider than the header's width, 16 pixels of margin left of the text and 24
# right of it (the key arrow's corner). The game places the box itself.
LEFT_MARGIN = 16
RIGHT_MARGIN = 24
BOX_EXTRA_TILES = 5


def font_preview(font: MlssRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, advance dark red, baseline blue."""
    codes = sorted(font.glyphs)
    cell_w, cell_h = CELL_WIDTH + 2, CELL_HEIGHT + 2
    atlas = Image.new("RGB", (16 * cell_w, math.ceil(len(codes) / 16) * cell_h), (40, 40, 40))
    for index, code in enumerate(codes):
        glyph = font.glyphs[code]
        origin_x = (index % 16) * cell_w + 1
        origin_y = (index // 16) * cell_h + 1
        for y in range(CELL_HEIGHT):
            for x in range(CELL_WIDTH):
                value = glyph.pixels[y][x]
                colour = (0, 0, 0)
                if value == TEXT:
                    colour = (255, 255, 255)
                elif value == SOFT:
                    colour = (140, 140, 160)
                elif x >= glyph.width:
                    colour = (70, 20, 20)
                elif y == BASELINE - 1:
                    colour = (20, 20, 70)
                atlas.putpixel((origin_x + x, origin_y + y), colour)
    return atlas


def message_preview(font: MlssRtlFont, header: tuple[int, int], body: bytes) -> Image.Image:
    """A translated message laid out like the printer: pages side by side, first on the right.

    Lines start at the right margin (mirrored left alignment) or are centred
    after ``FF 35``; ``FF 3n`` doubles glyphs; every glyph lands at the mirrored
    pen position.
    """
    width = (header[0] + BOX_EXTRA_TILES) * TILE
    height = max(header[1] * TILE, CELL_HEIGHT) + 8
    area = width - LEFT_MARGIN - RIGHT_MARGIN
    pages = [Image.new("RGB", (width, height), PREVIEW_COLOURS[0])]
    centred = False
    double_width = double_height = 0
    x = y = 0
    line_start = True
    line_height = CELL_HEIGHT
    index = 0
    while index < len(body):
        byte = body[index]
        if byte == COMMAND:
            code = body[index + 1]
            length = command_length(body, index)
            if code in (NEWLINE, PAGE):
                y += line_height if not line_start else CELL_HEIGHT
                line_start, line_height = True, CELL_HEIGHT
                if code == PAGE:
                    pages.append(Image.new("RGB", (width, height), PREVIEW_COLOURS[0]))
                    y = 0
            elif 0x30 <= code <= 0x33:
                double_height, double_width = code & 1, code >> 1 & 1
            elif code in (0x34, 0x35, 0x36):
                centred = code == 0x35
            index += length
            continue
        if line_start:
            line_width = _line_width(font, body, index) << double_width
            x = (area - line_width) // 2 if centred else 0
            line_height = CELL_HEIGHT << double_height
            line_start = False
        if byte == ARABIC_PREFIX:
            glyph = font.glyphs.get(body[index + 1])
            index += 2
        else:
            glyph = None
            index += 1
        if glyph is None:
            continue
        drawn = glyph.width << double_width
        left = LEFT_MARGIN + area - x - drawn
        top = 4 + y + line_height - (CELL_HEIGHT << double_height)
        for row in range(CELL_HEIGHT):
            for column in range(CELL_WIDTH):
                value = glyph.pixels[row][column]
                if not value:
                    continue
                for dy in range(1 << double_height):
                    for dx in range(1 << double_width):
                        px = left + (column << double_width) + dx
                        py = top + (row << double_height) + dy
                        if 0 <= px < width and 0 <= py < height:
                            pages[-1].putpixel((px, py), PREVIEW_COLOURS[value])
        x += drawn
    image = Image.new("RGB", (len(pages) * (width + 4) - 4, height), (0, 0, 0))
    for number, page in enumerate(reversed(pages)):
        image.paste(page, (number * (width + 4), 0))
    return image


def _line_width(font: MlssRtlFont, body: bytes, index: int) -> int:
    """Advances of the right-to-left glyphs from ``index`` to the line's end."""
    total = 0
    while index < len(body):
        if body[index] == COMMAND:
            if body[index + 1] in (NEWLINE, PAGE, END):
                break
            index += command_length(body, index)
            continue
        if body[index] == ARABIC_PREFIX:
            glyph = font.glyphs.get(body[index + 1])
            total += glyph.width if glyph is not None else 0
            index += 2
            continue
        index += 1
    return total


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    label = 120
    width = label + max(image.width for _, image in images)
    sheet = Image.new("RGB", (width, sum(image.height + 4 for _, image in images)), (12, 12, 12))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for key, image in images:
        draw.text((2, y + 2), key, fill=(200, 200, 120))
        sheet.paste(image, (width - image.width, y))
        y += image.height + 4
    return sheet
