"""Arabic support for the *Advance Wars* text engine.

The ROM overlay (``classic_retro.rom.advance_wars_arabic``) turns the dialogue
printer right to left without changing how it moves its pen. The printer
still draws a line from left to right into its row of 8x16 tile columns; for
a message of the Arabic bank, the hooks put each column into the tilemap at
its mirror inside the text area, with the hardware's horizontal flip:

    column' = 2 * left + 21 - column      (22 columns from ``left``)

A line then starts at the right edge of the box and grows leftwards, and the
typewriter reveals it from the right. The glyphs of the right-to-left font
are stored flipped, so the flip shows them the right way round. A translated
message holds these glyphs in right-to-left paint order: the first glyph of
a line is its rightmost one.

The printer puts a one-pixel gap before every glyph but the first of a line;
the hooks leave it out in Arabic text, so joined letters touch, and the
glyphs carry their own spacing (``glyph_raster``'s advance rule).

Glyphs are drawn from the reference font at the largest size whose forms fit
the 16-row cell on the game's baseline (row 13, like its Latin letters). A
glyph is at most 8 pixels wide, as in the game's font; a wider form
(``SPLIT_FORMS``) is two glyphs, its right part painted first. Coverage
becomes the game's two ink values: 0xA (the text colour) from ``INK_LEVEL``
of 255, 0x4 (the grey around its strokes) from ``SOFT_LEVEL``.

The player's name (``{15}``) is drawn from the game's own font: the hooks
reverse it while it is drawn and flip each letter, so it reads left to right
inside the Arabic line. A Yes/No question (``{16}``) gets its answers on its
last line (``CHOICE_LABELS``), laid out around the cursor's two places, which
the hooks mirror; Left and Right swap with them.
"""

from __future__ import annotations

import struct
import unicodedata
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
from classic_retro.engines.advance_wars import (
    CHOICES,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    NAME,
    NEWLINE,
    PAGE,
    TILE,
    AwCommand,
    AwFont,
    Piece,
    notation_skeleton,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    raised_form,
)
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

BASELINE = 13
INK_LEVEL = 140
SOFT_LEVEL = 60
INK = 0xA
SOFT = 0x4
SPLIT_WIDTH = 2 * GLYPH_COLUMNS
SPACE = 0x20
# The game's space (two pixels) and the gap after it.
SPACE_ADVANCE = 3
# A blank pixel, to place the answers of a question.
THIN_SPACE = chr(0x2009)
# Codes the printer takes for glyphs: not 0x00, the control codes below 0x18
# (0x01..0x08 and 0x10..0x13 are glyphs too, but the message scanner of the
# script's message command reads them as the start of a two-byte code) or the
# colours 0x80..0x83.
RTL_GLYPH_CODES = (*range(0x18, 0x80), *range(0x84, 0x100))
# Copies of the game's glyphs for Arabic text, at their own codes: sentence
# punctuation and Western digits, each with a free column after its ink.
LATIN_COPIES: dict[str, int] = {
    ".": 0x2E, "!": 0x21, ":": 0x3A, "-": 0x2D,
    **{str(digit): 0x30 + digit for digit in range(10)},
}  # fmt: skip
# Their widths in the USA font; the ROM build checks the game's glyphs.
LATIN_WIDTHS: dict[str, int] = {
    ".": 1, "!": 3, ":": 1, "-": 3, "0": 6, "1": 5,
    **{str(digit): 6 for digit in range(2, 10)},
}  # fmt: skip
ARABIC_CODES = tuple(
    code for code in RTL_GLYPH_CODES if code != SPACE and code not in LATIN_COPIES.values()
)
# Forms wider than 8 pixels at the reference font's size: two glyphs each.
_SPLIT_NAMES = {
    "SEEN": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "SHEEN": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "SAD": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "DAD": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "TAH": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "ZAH": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "FEH": ("ISOLATED", "FINAL"),
    "QAF": ("ISOLATED", "FINAL"),
    "KAF": ("ISOLATED",),
    "HEH": ("INITIAL", "MEDIAL"),
    "ALEF MAKSURA": ("ISOLATED", "FINAL"),
    "YEH": ("ISOLATED", "FINAL"),
    "YEH WITH HAMZA ABOVE": ("ISOLATED", "FINAL"),
}
SPLIT_FORMS = frozenset(
    unicodedata.lookup(f"ARABIC LETTER {letter} {form} FORM")
    for letter, forms in _SPLIT_NAMES.items()
    for form in forms
)
# The dots of final and isolated yeh fall one row below the cell: these forms
# are raised by a row; the final form keeps a pixel on the joining row.
_RAISED_FORMS = frozenset(
    unicodedata.lookup(f"ARABIC LETTER YEH {form} FORM") for form in ("ISOLATED", "FINAL")
)

# The dialogue box: 22 columns of 8 pixels from its left column. The last line
# of a page leaves a column for the key arrow after it.
LINE_WIDTH = 22 * TILE
PAGE_END_WIDTH = 21 * TILE - 1
LINES_PER_PAGE = 2
# The player's name: six characters of at most 7 pixels, and a free column each.
NAME_WIDTH = 6 * 8
# The answers of a question and where the cursor stands, in pixels from the
# line's start (tile columns 1 and 5 of the line, mirrored on screen).
CHOICE_LABELS = ("نعم", "لا")
CHOICE_CURSORS = (TILE, 5 * TILE)
CHOICE_GAP = 1


def aw_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes of the right-to-left font for ``characters``, in order; a split form takes two."""
    return assign_glyph_codes(
        characters, ARABIC_CODES, what="Advance Wars right-to-left glyphs", doubled=SPLIT_FORMS
    )


@lru_cache(maxsize=1)
def build_advance_wars_arabic_glyph_map() -> GlyphCodes:
    """The space and the Latin copies at their own codes, then the thin space and the forms."""
    assigned = aw_glyph_codes((THIN_SPACE, *arabic_presentation_repertoire()))
    fixed = {" ": (SPACE,), **{character: (code,) for character, code in LATIN_COPIES.items()}}
    return GlyphCodes((" ", *LATIN_COPIES, *assigned.characters), {**fixed, **assigned.sequences})


@dataclass(frozen=True, slots=True)
class AwRtlGlyph:
    """A right-to-left glyph: its advance and 16 rows of 8 pixels as seen on screen."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def stored(self) -> bytes:
        """The glyph flipped inside its advance: 16 rows of 8 pixels, 4 bytes each."""
        return b"".join(
            struct.pack(
                "<I",
                sum(value << 4 * (self.width - 1 - x) for x, value in enumerate(row[: self.width])),
            )
            for row in self.pixels
        )


def _glyph(values: Mapping[tuple[int, int], int], width: int, left: int = 0) -> AwRtlGlyph:
    """Pixels ``left``..``left + width`` of a drawn form; nothing outside the advance."""
    if not 1 <= width <= GLYPH_COLUMNS:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, f"Glyph advance {width} is not 1..8")
    pixels = tuple(
        tuple(values.get((left + x, y), 0) if x < width else 0 for x in range(GLYPH_COLUMNS))
        for y in range(GLYPH_ROWS)
    )
    return AwRtlGlyph(width, pixels)


def _split(values: Mapping[tuple[int, int], int], width: int) -> tuple[AwRtlGlyph, ...]:
    """One glyph, or the form's right part then its left part (paint order)."""
    if width <= GLYPH_COLUMNS:
        return (_glyph(values, width),)
    left = width - GLYPH_COLUMNS
    return (_glyph(values, GLYPH_COLUMNS, left), _glyph(values, left))


@dataclass(frozen=True, slots=True)
class AwRtlFont:
    """Every right-to-left glyph by code, and each character's codes in paint order."""

    glyphs: dict[int, AwRtlGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def width(self, character: str) -> int:
        return sum(self.glyphs[code].width for code in self.sequences[character])

    def tables(self, address: int) -> bytes:
        """The font at ``address``: 256 glyph pointers, 256 widths, then the glyphs.

        A code without a glyph has width 0 and points to the first glyph.
        """
        codes = sorted(self.glyphs)
        glyph_start = address + 4 * 256 + 256
        pointers = {code: glyph_start + 64 * number for number, code in enumerate(codes)}
        table = struct.pack("<256I", *(pointers.get(code, glyph_start) for code in range(256)))
        widths = bytes(self.glyphs[code].width if code in self.glyphs else 0 for code in range(256))
        return table + widths + b"".join(self.glyphs[code].stored() for code in codes)


def latin_rtl_glyphs(game_font: AwFont) -> dict[str, AwRtlGlyph]:
    """The game's own glyphs for ``LATIN_COPIES``, each with a free column after its ink."""
    glyphs = {}
    for character, code in LATIN_COPIES.items():
        width = game_font.widths[code]
        if width != LATIN_WIDTHS[character]:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"The game's {character!r} differs from the USA font",
            )
        source = game_font.glyphs[code]
        values = {
            (x, y): value for y, row in enumerate(source) for x, value in enumerate(row) if value
        }
        glyphs[character] = _glyph(values, width + 1)
    return glyphs


def placeholder_latin_glyphs() -> dict[str, AwRtlGlyph]:
    """Stand-ins with the game's advances when no ROM is at hand (checks, previews)."""
    glyphs = {}
    for character, width in LATIN_WIDTHS.items():
        if character in ".:":
            values = {(0, 12): INK} | ({(0, 7): INK} if character == ":" else {})
        elif character == "!":
            values = {(1, y): INK for y in (4, 5, 6, 7, 8, 9, 12)}
        elif character == "-":
            values = {(x, 8): INK for x in range(width)}
        else:
            values = {
                (x, y): INK
                for x in range(width)
                for y in range(3, 13)
                if x in (0, width - 1) or y in (3, 12)
            }
        glyphs[character] = _glyph(values, width + 1)
    return glyphs


def build_advance_wars_rtl_font(
    font_path: Path,
    latin: dict[str, AwRtlGlyph] | None = None,
    *,
    glyph_map: GlyphCodes | None = None,
) -> AwRtlFont:
    """Rasterize the Arabic forms into 8x16 glyphs and add the Latin copies."""
    glyph_map = glyph_map or build_advance_wars_arabic_glyph_map()
    latin = latin if latin is not None else placeholder_latin_glyphs()
    arabic = tuple(
        character
        for character in glyph_map.characters
        if character not in LATIN_COPIES and character not in (" ", THIN_SPACE)
    )
    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), tuple(sorted(arabic, key=ord))),
        range(14, 5, -1),
        lambda font: _forms(font, arabic),
        "Selected font cannot fit the Advance Wars 8x16 glyphs",
    )
    glyphs: dict[int, AwRtlGlyph] = {SPACE: _glyph({}, SPACE_ADVANCE)}
    sequences: dict[str, tuple[int, ...]] = {" ": (SPACE,)}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        if character == " ":
            continue
        if character == THIN_SPACE:
            parts: tuple[AwRtlGlyph, ...] = (_glyph({}, 1),)
        elif character in LATIN_COPIES:
            parts = (latin[character],)
        else:
            form = rendered[character]
            parts = _split(_values(form), form.advance)
        if len(parts) != len(codes):
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                f"U+{ord(character):04X} is {len(parts)} glyphs; the map gives it {len(codes)}",
            )
        glyphs.update(zip(codes, parts, strict=True))
        sequences[character] = codes
    return AwRtlFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _forms(
    font: ImageFont.FreeTypeFont, characters: tuple[str, ...]
) -> dict[str, DrawnForm] | None:
    """Every form at this size, or None when one leaves its 8x16 glyph (16 wide if split)."""
    try:
        rendered = {character: _rasterize(font, character) for character in characters}
    except FormDoesNotFit:
        return None
    for character in _RAISED_FORMS & set(rendered):
        rendered[character] = raised_form(
            character, rendered[character], height=GLYPH_ROWS, baseline=BASELINE
        )
    if any(not 0 <= y < GLYPH_ROWS for form in rendered.values() for _, y in form.ink | form.soft):
        return None
    return rendered


def _rasterize(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE, ink_level=INK_LEVEL, soft_level=SOFT_LEVEL)
    if form.advance > (SPLIT_WIDTH if character in SPLIT_FORMS else GLYPH_COLUMNS):
        raise FormDoesNotFit
    return form


def _values(form: DrawnForm) -> dict[tuple[int, int], int]:
    """The form's pixels as the font's values: 0xA ink, 0x4 soft."""
    return {**dict.fromkeys(form.soft, SOFT), **dict.fromkeys(form.ink, INK)}


# ---------------------------------------------------------------------------
# Encoding translated messages


def arabic_command_token(token_id: str, command: AwCommand) -> InlineToken:
    if command.code == NEWLINE:
        kind = TokenKind.LINE_BREAK
    elif command.code == PAGE:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return command_token(token_id, kind, command.data.hex(" "), name=f"{command.code:02X}")


def arabic_stream(pieces: Sequence[Piece], prefix: str = "t") -> TokenStream:
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"{prefix}{number}", piece))
    return TokenStream(tuple(tokens))


# Control codes an Arabic message may hold: line ends, pages, the player's
# name and the questions.
SUPPORTED_COMMANDS = frozenset({NEWLINE, PAGE, NAME, *CHOICES})


@dataclass(frozen=True, slots=True)
class AwArabicEncoding:
    """A translated message (without its final 0x00) and, with a font, its line widths."""

    body: bytes
    line_widths: tuple[int, ...] | None


class AwArabicEncoder:
    """Convert logical Arabic text into Advance Wars bytes in right-to-left paint order."""

    def __init__(self, font: AwRtlFont | None = None) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.font = font
        self.sequences: Mapping[str, tuple[int, ...]] = (
            font.sequences if font is not None else build_advance_wars_arabic_glyph_map().sequences
        )

    def encode(self, pieces: Sequence[Piece]) -> AwArabicEncoding:
        for piece in pieces:
            if isinstance(piece, AwCommand) and piece.code not in SUPPORTED_COMMANDS:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Advance Wars Arabic v1 does not support {piece.notation}",
                )
        stream = arabic_stream(pieces)
        reject_mirrored(stream, "Advance Wars Arabic v1")
        reject_combining_marks(stream, "Advance Wars Arabic font v1")
        data = bytearray()
        lines: list[int] = [0]
        page_lines = 1
        empty_line = True
        for token in rtl_paint_order(self.pipeline, stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    for code in self.codes(character):
                        data.append(code)
                        lines[-1] += self._width(code)
                empty_line = empty_line and not token.text
                continue
            codes = bytes(command_codes(token, "Advance Wars"))
            if codes[0] in CHOICES:
                if not empty_line:
                    raise ClassicRetroError(
                        ErrorCode.TOKEN_ORDER_VIOLATION,
                        "A question's answers need a line of their own: put a line end before "
                        + AwCommand(codes).notation,
                    )
                labels = self._choice_labels()
                data += labels
                lines[-1] = sum(self._width(code) for code in labels)
            elif codes[0] == NAME:
                lines[-1] += NAME_WIDTH
                empty_line = False
            data += codes
            if codes[0] in (NEWLINE, PAGE):
                empty_line = True
            if codes[0] == NEWLINE:
                lines.append(0)
                page_lines += 1
                if page_lines > LINES_PER_PAGE:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A page of the dialogue box holds {LINES_PER_PAGE} lines",
                    )
            elif codes[0] == PAGE:
                self._check_width(lines[-1], PAGE_END_WIDTH, len(lines))
                lines.append(0)
                page_lines = 1
        if self.font is None:
            return AwArabicEncoding(bytes(data), None)
        for number, width in enumerate(lines, 1):
            self._check_width(width, LINE_WIDTH, number)
        return AwArabicEncoding(bytes(data), tuple(lines))

    def _check_width(self, width: int, limit: int, number: int) -> None:
        if self.font is not None and width > limit:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Line {number} needs {width}px; it holds {limit}px",
            )

    def _width(self, code: int) -> int:
        return self.font.glyphs[code].width if self.font is not None else 0

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None and character != THIN_SPACE:
            return codes
        raise no_glyph(character, "Advance Wars Arabic")

    def _choice_labels(self) -> bytes:
        """The answers' line up to its choice code: each answer a pixel past its cursor."""
        data = bytearray()
        pen = 0
        for cursor, label in zip(CHOICE_CURSORS, CHOICE_LABELS, strict=True):
            if pen > cursor - CHOICE_GAP:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW, "The answers of a question overlap its cursor"
                )
            start = cursor + TILE + CHOICE_GAP
            data += self._blank(start - pen)
            pen = start
            stream = TokenStream((TextToken(label),))
            for token in rtl_paint_order(self.pipeline, stream).tokens:
                assert isinstance(token, TextToken)
                for character in token.text:
                    for code in self.codes(character):
                        data.append(code)
                        pen += self._width(code)
        return bytes(data)

    def _blank(self, width: int) -> bytes:
        """Spaces, then thin spaces, ``width`` pixels in all (without a font: spaces)."""
        space = self.sequences[" "][0]
        if self.font is None:
            return bytes((space,)) * max(1, width // SPACE_ADVANCE)
        thin = self.sequences[THIN_SPACE][0]
        spaces, rest = divmod(width, SPACE_ADVANCE)
        return bytes((space,)) * spaces + bytes((thin,)) * rest


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's control codes must equal the original's; only line ends may move."""
    require_same_commands("Advance Wars", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The dialogue box's paper and its text palette (the ink and the shades of the
# game's glyphs), and the text area: from x = 56 to 232 on a 240-pixel screen,
# 16 pixels a line.
PREVIEW_COLOURS = {
    0: (238, 230, 197),
    SOFT: (172, 172, 148),
    0x5: (131, 123, 115),
    0x6: (106, 98, 90),
    0x7: (90, 82, 74),
    INK: (16, 8, 8),
}
PREVIEW_LEFT = 56
PREVIEW_RIGHT = PREVIEW_LEFT + LINE_WIDTH
PREVIEW_WIDTH = 240
PREVIEW_HEIGHT = LINES_PER_PAGE * GLYPH_ROWS + 8


def font_preview(font: AwRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, advance dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixels[y][x]
        if value == INK:
            return (255, 255, 255)
        if value:
            return (140, 140, 160)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), GLYPH_COLUMNS, GLYPH_ROWS, colour)


def message_preview(font: AwRtlFont, body: bytes) -> Image.Image:
    """A translated message as the dialogue box shows it: pages side by side, first on the right.

    Every line starts at the right edge of the text area and grows leftwards;
    the player's name is a grey box, the key arrow and the cursor are triangles.
    """
    pages = [_page()]
    pen = 0
    row = 0
    turned = False
    for byte in body:
        if turned:
            pages.append(_page())
            turned = False
        if byte == NEWLINE:
            pen, row = 0, row + 1
        elif byte == PAGE:
            # The key arrow takes the column after the pen's.
            _triangle(pages[-1], PREVIEW_LEFT + TILE * (20 - pen // TILE), row, down=True)
            pen, row, turned = 0, 0, True
        elif byte == NAME:
            top = 4 + row * GLYPH_ROWS
            ImageDraw.Draw(pages[-1]).rectangle(
                (PREVIEW_RIGHT - pen - NAME_WIDTH, top + 4, PREVIEW_RIGHT - pen - 2, top + 12),
                fill=(150, 150, 150),
            )
            pen += NAME_WIDTH
        elif byte in CHOICES:
            _triangle(pages[-1], PREVIEW_RIGHT - CHOICE_CURSORS[0] - TILE, row, down=False)
        else:
            glyph = font.glyphs[byte]
            left = PREVIEW_RIGHT - pen - glyph.width
            for y, values in enumerate(glyph.pixels):
                for x, value in enumerate(values[: glyph.width]):
                    if value:
                        pages[-1].putpixel(
                            (left + x, 4 + row * GLYPH_ROWS + y), PREVIEW_COLOURS[value]
                        )
            pen += glyph.width
    return pages_right_to_left(pages)


def _page() -> Image.Image:
    page = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), PREVIEW_COLOURS[0])
    ImageDraw.Draw(page).rectangle((0, 0, PREVIEW_LEFT - 8, PREVIEW_HEIGHT), fill=(200, 120, 200))
    return page


def _triangle(page: Image.Image, left: int, row: int, *, down: bool) -> None:
    top = 4 + row * GLYPH_ROWS + (8 if down else 4)
    if down:
        points = [(left + 1, top), (left + 6, top), (left + 3, top + 4)]
    else:
        # The cursor points left, at the answer on its left.
        points = [(left + 6, top), (left + 6, top + 6), (left + 2, top + 3)]
    ImageDraw.Draw(page).polygon(points, fill=(230, 200, 0))


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 120)
