"""Arabic support for the *Tactics Ogre: The Knight of Lodis* text engine.

The ROM overlay (``classic_retro.rom.tactics_ogre_arabic``) turns the
dialogue right to left without changing how its routines move their pen. They
still lay a line out from the left; for a message of the Arabic bank, the
hook draws each glyph at the mirror of its place on the window's line, which
is the window's width in whole columns:

    left' = line - pen - width

A line then starts at the right edge of the window and grows leftwards, and
the typewriter reveals it from the right. A translated message holds its
glyphs in right-to-left paint order: the first glyph of a line is its
rightmost one.

The game's font has 128 codes, the whole range its routines read as glyphs.
In a message of the Arabic bank the same codes are the glyphs of the
right-to-left font (``RTL_GLYPH_CODES``), which the hooks measure and draw
from tables of their own; the build gives codes only to the characters the
script uses. Codes 0 and 1 are left out: the dialogue plays its typing sound
for the others.

Glyphs are 16 pixels wide at most and 16 rows tall, drawn from the reference
font at the largest size whose every form fits them. Coverage becomes the
game's two ink values, like its Latin letters: 1 (the text colour) from
``INK_LEVEL`` of 255, 2 (the grey around its strokes) from ``SOFT_LEVEL``. A
glyph's pixels stay inside its advance, so neighbours never overlap: the
hook ORs every glyph into cleared tiles. The space is a glyph of its own
(``SPACE_WIDTH`` pixels), and ``.``, ``!`` and ``:`` are drawn by hand.

A name the text inserts from the game's list of characters (``87xx``) is
written out at build time from the script's Arabic name for it, so the line
holds the name as Arabic glyphs; the list keeps its English names for the
rest of the game.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tactics_ogre import (
    GLYPH_CODES,
    GLYPH_ROWS,
    INK,
    INSTANT,
    LAST_WAIT,
    NAME,
    NEW_PAGE,
    NEWLINE,
    PAGE_WAIT,
    SOFT,
    TYPED,
    Piece,
    ToCommand,
    ToLine,
    lay_out,
    notation_skeleton,
    page_lines,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    pattern_pixels,
    raised_form,
)
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.font.tiles import pack_4bpp
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

BASELINE = 12
INK_LEVEL = 140
SOFT_LEVEL = 60
SIZES = range(16, 7, -1)
# A glyph of the right-to-left font: up to 16 pixels wide, 16 rows tall. Its
# pixels stay off the top row, which keeps lines apart.
RTL_GLYPH_COLUMNS = 16
RTL_GLYPH_BYTES = RTL_GLYPH_COLUMNS * GLYPH_ROWS // 2
TOP_ROW = 1
RTL_GLYPH_CODES = tuple(range(0x02, GLYPH_CODES))
SPACE_WIDTH = 4
# Punctuation the reference font lacks, drawn on the baseline.
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    ".": ("##", "##"),
    "!": ("##", "##", "##", "##", "##", "##", "..", "##", "##"),
    ":": ("##", "##", "..", "..", "..", "##", "##"),
}
# The dots of final and isolated yeh reach below the cell: these forms are
# raised a row; the final form keeps a pixel on the joining row.
_RAISED_FORMS = frozenset("ﻱﻲ")

# The dialogue's window: its lines are its longest line rounded up to whole
# columns, and it is widest at 22 columns (a portrait takes the rest of the
# screen). The header of a message gives the lines of its pages.
COLUMN = 8
LINE_WIDTH = 22 * COLUMN
# Commands an Arabic message may hold: line ends, pages, waits, the speaker's
# name at once then the typewriter, the names of the list (written out) and
# the one-byte flags.
SUPPORTED_COMMANDS = frozenset(
    {NEWLINE, NEW_PAGE, INSTANT, TYPED, LAST_WAIT, PAGE_WAIT, NAME, 0x8F, 0x90, 0x91}
)


def glyph_characters() -> tuple[str, ...]:
    """Every character the right-to-left font can draw, in the order codes follow.

    The repertoire holds the forms and the Arabic comma, semicolon, question
    mark, tatweel and digits.
    """
    return (" ", *_PUNCTUATION_INK, *arabic_presentation_repertoire())


def tactics_ogre_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes for the characters a script uses: the space, the punctuation, then the forms.

    Codes follow that order and the forms' code points, so the same characters
    always get the same codes.
    """
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], "Tactics Ogre Arabic")
    return assign_glyph_codes(
        (character for character in order if character in used),
        RTL_GLYPH_CODES,
        what="Tactics Ogre Arabic glyphs",
    )


@dataclass(frozen=True, slots=True)
class ToRtlGlyph:
    """A right-to-left glyph: its advance and 16 rows of 16 pixels."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def stored(self) -> bytes:
        """Its two columns of 8 pixels, each 16 rows of 4 bytes, as the hook reads them."""
        return pack_4bpp(self.pixels, columns=True)


def rtl_glyph(values: Mapping[tuple[int, int], int], width: int) -> ToRtlGlyph:
    """A glyph of ``width`` from pixel values; nothing may lie outside its advance."""
    if not 1 <= width <= RTL_GLYPH_COLUMNS:
        raise FormDoesNotFit
    if any(not (0 <= x < width and TOP_ROW <= y < GLYPH_ROWS) for x, y in values):
        raise FormDoesNotFit
    pixels = tuple(
        tuple(values.get((x, y), 0) for x in range(RTL_GLYPH_COLUMNS)) for y in range(GLYPH_ROWS)
    )
    return ToRtlGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class ToRtlFont:
    """Every right-to-left glyph by code, and each character's code."""

    glyphs: dict[int, ToRtlGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def width(self, code: int) -> int:
        return self.glyphs[code].width

    def glyph_table(self) -> bytes:
        """The glyphs from code 0 to the last one, ``RTL_GLYPH_BYTES`` each; blank where none."""
        blank = bytes(RTL_GLYPH_BYTES)
        return b"".join(
            self.glyphs[code].stored() if code in self.glyphs else blank
            for code in range(max(self.glyphs) + 1)
        )

    def width_table(self) -> bytes:
        """A width for each of the 128 codes; 0 where there is no glyph."""
        return bytes(
            self.glyphs[code].width if code in self.glyphs else 0 for code in range(GLYPH_CODES)
        )


def build_tactics_ogre_rtl_font(
    font_path: Path, glyph_map: GlyphCodes, *, sizing: Iterable[str] | None = None
) -> ToRtlFont:
    """Rasterize the forms ``glyph_map`` holds and add the space and the drawn punctuation.

    The size is the largest where every form of ``sizing`` fits: the whole
    repertoire, whatever the script uses, so a new word never changes the size
    of the others (a test may give a few forms of its own font).
    """
    used = {
        character
        for character in glyph_map.characters
        if character != " " and character not in _PUNCTUATION_INK
    }
    sized = set(arabic_presentation_repertoire() if sizing is None else sizing)
    drawn = tuple(sorted(sized | used, key=ord))
    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        lambda font: _glyphs(font, drawn),
        "Selected font cannot fit the Tactics Ogre 16x16 glyphs",
    )
    rendered[" "] = rtl_glyph({}, SPACE_WIDTH)
    for character, rows in _PUNCTUATION_INK.items():
        ink = pattern_pixels(rows, top=BASELINE - len(rows))
        rendered[character] = rtl_glyph(dict.fromkeys(ink, INK), len(rows[0]) + 1)
    glyphs: dict[int, ToRtlGlyph] = {}
    sequences: dict[str, tuple[int, ...]] = {}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        sequences[character] = codes
        glyphs[codes[0]] = rendered[character]
    return ToRtlFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, ToRtlGlyph] | None:
    """Every form at this size, or None when one leaves its 16x16 glyph."""
    try:
        rendered = {character: _drawn(font, character) for character in characters}
        for character in _RAISED_FORMS & set(rendered):
            rendered[character] = raised_form(
                character, rendered[character], height=GLYPH_ROWS, baseline=BASELINE
            )
        return {character: _glyph(form) for character, form in rendered.items()}
    except FormDoesNotFit:
        return None


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    return draw_form(font, character, BASELINE, ink_level=INK_LEVEL, soft_level=SOFT_LEVEL)


def _glyph(form: DrawnForm) -> ToRtlGlyph:
    """The form's pixels as the game's values: ink 1, the grey around it 2.

    Grey beyond the advance is left out, where the neighbour's ink goes on.
    """
    soft = {pixel for pixel in form.soft if pixel[0] < form.advance}
    return rtl_glyph({**dict.fromkeys(soft, SOFT), **dict.fromkeys(form.ink, INK)}, form.advance)


# ---------------------------------------------------------------------------
# Encoding translated messages


def arabic_command_token(token_id: str, command: ToCommand) -> InlineToken:
    if command.code == NEWLINE:
        kind = TokenKind.LINE_BREAK
    elif command.code == NEW_PAGE:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return command_token(token_id, kind, command.data.hex(" "), name=f"{command.code:02X}")


def written_names(pieces: Sequence[Piece], names: Mapping[int, str]) -> tuple[Piece, ...]:
    """The pieces with every ``87xx`` written out as its Arabic name, in its text run."""
    result: list[Piece] = []
    for piece in pieces:
        if isinstance(piece, ToCommand) and piece.code == NAME:
            assert piece.argument is not None
            name = names.get(piece.argument)
            if name is None:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"{piece.notation} needs the Arabic name {piece.argument} in the script",
                )
            piece = name
        if isinstance(piece, str) and result and isinstance(result[-1], str):
            result[-1] += piece
        else:
            result.append(piece)
    return tuple(result)


def paint_stream(pieces: Sequence[Piece], names: Mapping[int, str]) -> TokenStream:
    """A message in right-to-left paint order, its names written out."""
    for piece in pieces:
        if isinstance(piece, ToCommand) and piece.code not in SUPPORTED_COMMANDS:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"Tactics Ogre Arabic v1 does not support {piece.notation}",
            )
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(written_names(pieces, names)):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"t{number}", piece))
    stream = TokenStream(tuple(tokens))
    reject_mirrored(stream, "Tactics Ogre Arabic v1")
    reject_combining_marks(stream, "Tactics Ogre Arabic font v1")
    return rtl_paint_order(legacy_renderer_pipeline(), stream)


def painted_characters(pieces: Sequence[Piece], names: Mapping[int, str]) -> set[str]:
    """The characters a message paints."""
    return {
        character
        for token in paint_stream(pieces, names).tokens
        if isinstance(token, TextToken)
        for character in token.text
    }


@dataclass(frozen=True, slots=True)
class ToArabicEncoding:
    """A translated message's bytes (without its final ``FF``) and, with a font, its lines."""

    data: bytes
    lines: tuple[ToLine, ...] | None

    @property
    def line_widths(self) -> tuple[int, ...] | None:
        return None if self.lines is None else tuple(line.width for line in self.lines)


class ToArabicEncoder:
    """Convert logical Arabic text into Tactics Ogre bytes in right-to-left paint order."""

    def __init__(self, glyph_map: GlyphCodes, font: ToRtlFont | None = None) -> None:
        self.sequences: Mapping[str, tuple[int, ...]] = glyph_map.sequences
        self.font = font

    def encode(
        self, pieces: Sequence[Piece], names: Mapping[int, str], lines_per_page: int
    ) -> ToArabicEncoding:
        data = bytearray()
        for token in paint_stream(pieces, names).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    data += bytes(self.codes(character))
                continue
            data += bytes(command_codes(token, "Tactics Ogre"))
        lines = lay_out(bytes(data), self._width)
        for page, count in page_lines(lines).items():
            if count > lines_per_page:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Page {page + 1} has {count} lines; this window holds {lines_per_page}",
                )
        if self.font is None:
            return ToArabicEncoding(bytes(data), None)
        for number, line in enumerate(lines, 1):
            if line.width > LINE_WIDTH:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {line.width}px; the window holds {LINE_WIDTH}px",
                )
        return ToArabicEncoding(bytes(data), lines)

    def _width(self, code: int) -> int:
        return self.font.width(code) if self.font is not None else 0

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "Tactics Ogre Arabic")


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    require_same_commands("Tactics Ogre", source, notation_skeleton(pieces), "".join)


def window_width(lines: Sequence[ToLine]) -> int:
    """The window's line: the longest line rounded up to whole columns."""
    return COLUMN * math.ceil(max(line.width for line in lines) / COLUMN)


# ---------------------------------------------------------------------------
# Previews

# The window: dark ink with olive grey around it, on the window's pale yellow.
PREVIEW_COLOURS = {0: (255, 255, 139), INK: (16, 24, 24), SOFT: (82, 82, 49)}
PREVIEW_MARGIN = 8


def font_preview(font: ToRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, grey grey, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixels[y][x]
        if value == INK:
            return (255, 255, 255)
        if value == SOFT:
            return (120, 120, 120)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), RTL_GLYPH_COLUMNS, GLYPH_ROWS, colour)


def message_preview(font: ToRtlFont, data: bytes, lines_per_page: int) -> Image.Image:
    """A translated message as the window shows it: pages side by side, the first on the right.

    Every line ends at the right edge of the window's line and grows
    leftwards. The window shows no arrow while it waits for A.
    """
    lines = lay_out(data, font.width)
    pages = 1 + max((line.page for line in lines if line.places), default=0)
    width = window_width(lines)
    images = [
        Image.new(
            "RGB",
            (width + 2 * PREVIEW_MARGIN, lines_per_page * GLYPH_ROWS + 2 * PREVIEW_MARGIN),
            PREVIEW_COLOURS[0],
        )
        for _ in range(pages)
    ]
    for line in lines:
        if line.page >= pages:
            continue
        image = images[line.page]
        top = PREVIEW_MARGIN + line.number * GLYPH_ROWS
        for place in line.places:
            left = PREVIEW_MARGIN + width - place.end
            for y, values in enumerate(font.glyphs[place.code].pixels):
                for x, value in enumerate(values[: place.width]):
                    if value:
                        image.putpixel((left + x, top + y), PREVIEW_COLOURS[value])
    return pages_right_to_left(images)


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 150)


def stored_glyph_rows(data: bytes) -> tuple[tuple[int, int], ...]:
    """A stored glyph's 16 rows as the hook reads them: (pixels 0..7, pixels 8..15)."""
    left = struct.unpack_from("<16I", data)
    right = struct.unpack_from("<16I", data, 4 * GLYPH_ROWS)
    return tuple(zip(left, right, strict=True))
