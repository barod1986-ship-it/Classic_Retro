"""Arabic support for the *Pokémon Mystery Dungeon: Red Rescue Team* text engine.

The ROM overlay (``classic_retro.rom.pmd_arabic``) adds right-to-left glyphs
to the game's charmap under two-byte codes ``0x84XX`` (the game draws any code
its charmap holds; ``0x84`` only has two symbols of its own). Byte 8 of their
charmap entry, zero in every original glyph, is set to 1: when the game draws
such a glyph, the hooks place it at the mirrored position of the text cursor
inside its window,

    draw_x = window_width * 8 - cursor - glyph_width

so the game's own layout (left margin, ``{CENTER_ALIGN}``, line ends) turns
into its right-to-left counterpart. A translated string holds only these
glyphs, spaces included, and this module stores every line in right-to-left
paint order: its first glyph is the rightmost one.

Glyphs are 12x12 four-bit bitmaps like the game's (ink ``0xF``; the game adds
the colour and its drop shadow). Arabic letters sit on row 7 (the game's
Latin letters on row 8, one row lower) and may use all 12 rows: the hooks draw
right-to-left glyphs with 12 rows instead of 11. A form wider than 12 pixels
(seen and sheen at the reference size) is split into two glyphs drawn side by
side, and hamza or madda above alef get a small drawn mark (see _MARKED_ALEF).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pmd import (
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    INK,
    NEWLINE_COMMAND,
    PAGE_COMMANDS,
    STYLE_SHADOW,
    Piece,
    PmdCommand,
    glyph_bitmap,
    notation_skeleton,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    drawn_mark,
    largest_fitting_size,
)
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

ARABIC_LEAD = 0x84
# Second bytes for right-to-left glyphs: 0x8486/0x8487 are the game's own
# symbols; '~' and 0x7F are skipped to keep every byte printable.
ARABIC_TRAILS = tuple(trail for trail in range(0x40, 0xFD) if trail not in (0x7E, 0x7F, 0x86, 0x87))
RTL_FLAG = 1
# Charmap style of every right-to-left glyph: a plain glyph with the game's shadow.
RTL_STYLE = STYLE_SHADOW

BASELINE = 8
LATIN_ROW_SHIFT = -1
SPACE_ADVANCE = 4
SPLIT_WIDTH = 2 * GLYPH_COLUMNS

# Copies of the game's own glyphs for right-to-left text, moved onto the
# Arabic baseline: sentence punctuation and Western digits. The ROM build
# checks these advances (USA ``kanji_a``) before copying the bitmaps.
LATIN_COPIES = ".!:-0123456789"
USA_LATIN_WIDTHS: dict[str, int] = {
    ".": 3, "!": 4, ":": 3, "-": 5, **dict.fromkeys("0123456789", 6),
}  # fmt: skip
# Forms that may be wider than a glyph; they get two codes.
SPLIT_FORMS = "ﺱﺲﺵﺶﺹﺺﺽﺾ"
# At this size the reference font draws the Arabic comma as two pixels; these
# follow its slanted Kufi comma at a readable size (rows end on the baseline).
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    "،": (".#", ".#", "#.", "#."),
    "؛": (".#", ".#", "#.", "#.", "..", "#.", "#."),
}
# Hamza and madda above alef reach above the tallest letters (or touch the
# alef) at this size: these forms are drawn as the font's alef, cut one row
# below the mark, with a small hamza (from the alef's stroke to the left) or
# madda (centred on it) on the top rows.
_HAMZA_MARK = ("##", "#.")
_MADDA_MARK = ("###",)
_MARKED_ALEF: dict[str, tuple[str, tuple[str, ...], int]] = {
    "ﺃ": ("ﺍ", _HAMZA_MARK, 0),
    "ﺄ": ("ﺎ", _HAMZA_MARK, 0),
    "ﺁ": ("ﺍ", _MADDA_MARK, -1),
    "ﺂ": ("ﺎ", _MADDA_MARK, -1),
}


class PmdTextBox(StrEnum):
    """Where a string is shown, which decides its widest line and its line count."""

    FLOATING = "floating"
    DIALOGUE = "dialogue"
    MENU = "menu"


# Widest line: the dialogue box and the personality test's floating text are
# 26 tiles (208 pixels) with 4-pixel margins; a menu window grows with its
# widest item, which stays well inside the screen.
LINE_WIDTH: dict[PmdTextBox, int] = {
    PmdTextBox.FLOATING: 200,
    PmdTextBox.DIALOGUE: 200,
    PmdTextBox.MENU: 160,
}
# The typewriter prints three 11-pixel lines per box, then waits for a key.
LINES_PER_BOX: dict[PmdTextBox, int] = {
    PmdTextBox.FLOATING: 3,
    PmdTextBox.DIALOGUE: 3,
    PmdTextBox.MENU: 1,
}
ALLOWED_COMMANDS: dict[PmdTextBox, frozenset[str]] = {
    PmdTextBox.FLOATING: frozenset({"CENTER_ALIGN", "WAIT_PRESS", "EXTRA_MSG", "NEWLINE"}),
    PmdTextBox.DIALOGUE: frozenset({"CENTER_ALIGN", "WAIT_PRESS", "EXTRA_MSG", "NEWLINE"}),
    PmdTextBox.MENU: frozenset(),
}


def code_bytes(code: int) -> bytes:
    return bytes((code >> 8, code & 0xFF))


def pmd_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes ``84 XX`` for ``characters`` in order; a form that may split takes two."""
    return assign_glyph_codes(
        characters,
        (ARABIC_LEAD << 8 | trail for trail in ARABIC_TRAILS),
        what="PMD right-to-left glyphs",
        doubled=SPLIT_FORMS,
    )


@lru_cache(maxsize=1)
def build_pmd_arabic_glyph_map() -> GlyphCodes:
    """The space first, then the Latin copies and the Arabic forms."""
    return pmd_glyph_codes((" ", *LATIN_COPIES, *arabic_presentation_repertoire()))


@dataclass(frozen=True, slots=True)
class PmdRtlGlyph:
    """A right-to-left glyph: advance and 12x12 pixels (ink ``0xF``)."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def bitmap(self) -> bytes:
        return glyph_bitmap(self.pixels)


def _glyph(
    ink: set[tuple[int, int]], width: int, offset: int = 0, *, columns: int = GLYPH_COLUMNS
) -> PmdRtlGlyph:
    """Pixels ``offset .. offset + columns`` of ``ink`` as one glyph cell."""
    pixels = tuple(
        tuple(INK if x < columns and (x + offset, y) in ink else 0 for x in range(GLYPH_COLUMNS))
        for y in range(GLYPH_ROWS)
    )
    return PmdRtlGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class PmdRtlFont:
    """Every right-to-left glyph by code, and each character's paint-order codes."""

    glyphs: dict[int, PmdRtlGlyph]
    sequences: dict[str, tuple[int, ...]]
    space: int
    font_size: int

    def advances(self) -> dict[int, int]:
        return {code: glyph.width for code, glyph in self.glyphs.items()}


def latin_rtl_glyphs(
    pixels: dict[str, tuple[tuple[int, ...], ...]], widths: dict[str, int]
) -> dict[str, PmdRtlGlyph]:
    """The game's own glyphs for ``LATIN_COPIES`` moved onto the Arabic baseline."""
    glyphs = {}
    for character in LATIN_COPIES:
        source = pixels.get(character)
        if source is None:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The game font has no {character!r} to copy"
            )
        ink = {
            (x, y + LATIN_ROW_SHIFT)
            for y, row in enumerate(source)
            for x, value in enumerate(row)
            if value
        }
        if any(not 0 <= y < GLYPH_ROWS for _, y in ink):
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, f"Game glyph {character!r} leaves the glyph cell"
            )
        glyphs[character] = _glyph(ink, widths[character])
    return glyphs


def placeholder_latin_glyphs() -> dict[str, PmdRtlGlyph]:
    """Stand-ins with the game's advances when no ROM is at hand (checks, previews)."""
    glyphs = {}
    for character in LATIN_COPIES:
        if character == "-":
            ink = {(x, 4) for x in range(3)}
        elif character in ".:":
            ink = {(1, 7)} | ({(1, 3)} if character == ":" else set())
        elif character == "!":
            ink = {(1, y) for y in range(1, 6)} | {(1, 7)}
        else:
            # A digit-sized box.
            ink = {(x, y) for x in range(4) for y in range(1, 8) if x in (0, 3) or y in (1, 7)}
        glyphs[character] = _glyph(ink, USA_LATIN_WIDTHS[character])
    return glyphs


def build_pmd_rtl_font(
    font_path: Path,
    latin: dict[str, PmdRtlGlyph] | None = None,
    *,
    glyph_map: GlyphCodes | None = None,
) -> PmdRtlFont:
    """Rasterize the Arabic forms into 12x12 cells and add the Latin copies."""
    glyph_map = glyph_map or build_pmd_arabic_glyph_map()
    latin = latin if latin is not None else placeholder_latin_glyphs()
    arabic = tuple(
        character
        for character in glyph_map.characters
        if character != " " and character not in LATIN_COPIES and character not in _PUNCTUATION_INK
    )
    # Hamza and madda over alef are drawn from the alef forms, not from the font.
    outlined = tuple(character for character in arabic if character not in _MARKED_ALEF)
    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), outlined),
        range(12, 5, -1),
        lambda font: _forms(font, arabic),
        "Selected font cannot fit the PMD 12x12 glyph cell",
    )
    space = glyph_map.code(" ")
    assert space is not None
    glyphs: dict[int, PmdRtlGlyph] = {space: _glyph(set(), SPACE_ADVANCE)}
    sequences: dict[str, tuple[int, ...]] = {" ": (space,)}
    for character in glyph_map.characters:
        codes = glyph_map.sequences[character]
        if character == " ":
            continue
        if character in LATIN_COPIES:
            pieces: tuple[PmdRtlGlyph, ...] = (latin[character],)
        elif character in _PUNCTUATION_INK:
            pieces = (_glyph(*drawn_mark(_PUNCTUATION_INK[character], BASELINE)),)
        else:
            form = rendered[character]
            pieces = _split(character, form.ink, form.advance)
        for code, piece in zip(codes, pieces, strict=False):
            glyphs[code] = piece
        sequences[character] = codes[: len(pieces)]
    return PmdRtlFont(glyphs=glyphs, sequences=sequences, space=space, font_size=size)


def _split(
    character: str, ink: set[tuple[int, int]] | frozenset[tuple[int, int]], width: int
) -> tuple[PmdRtlGlyph, ...]:
    """One glyph, or its right part then its left part (paint order)."""
    if width <= GLYPH_COLUMNS:
        return (_glyph(ink, width),)
    left = width - GLYPH_COLUMNS
    return (_glyph(ink, GLYPH_COLUMNS, left), _glyph(ink, left, columns=left))


def _forms(
    font: ImageFont.FreeTypeFont, characters: tuple[str, ...]
) -> dict[str, DrawnForm] | None:
    """Every form at this size, or None when one leaves the 12x12 cell (rows around the
    row-8 anchor, and 12 columns or 24 for a form that splits)."""
    try:
        rendered = {
            character: _rasterize(font, character)
            for character in characters
            if character not in _MARKED_ALEF
        }
        for composed, (alef, mark, shift) in _MARKED_ALEF.items():
            if composed in characters:
                if alef not in rendered:
                    rendered[alef] = _rasterize(font, alef)
                rendered[composed] = alef_with_mark(composed, rendered[alef], mark, shift)
    except FormDoesNotFit:
        return None
    if any(_leaves_cell(form.ink) for form in rendered.values()):
        return None
    return rendered


def _leaves_cell(ink: frozenset[tuple[int, int]]) -> bool:
    return any(not 0 <= y < GLYPH_ROWS for _, y in ink)


def _rasterize(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE)
    limit = SPLIT_WIDTH if character in SPLIT_FORMS else GLYPH_COLUMNS
    if form.advance > limit:
        raise FormDoesNotFit
    return form


def font_preview(font: PmdRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        if glyph.pixels[y][x]:
            return (255, 255, 255)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), GLYPH_COLUMNS, GLYPH_ROWS, colour)


def string_preview(font: PmdRtlFont, data: bytes, box: PmdTextBox) -> Image.Image:
    """An encoded string laid out like the game: boxes side by side, key arrows in grey.

    The typewriter starts lines at x = 4 (menu items at 8) in a 26-tile window
    (a menu is as wide as its item plus two tiles); ``{CENTER_ALIGN}`` centres
    the rest of the line, and every glyph is drawn at the mirrored cursor.
    """
    start = 8 if box is PmdTextBox.MENU else 4
    lines = [_line_width(font, data, 0)]
    width = 26 * 8 if box is not PmdTextBox.MENU else (lines[0] // 8 + 2) * 8
    height = LINES_PER_BOX[box] * 11 + 3
    boxes = [Image.new("RGB", (width, height), (24, 32, 72))]
    x, y = start, 2
    index = 0
    while index < len(data) and data[index]:
        byte = data[index]
        if byte == ARABIC_LEAD:
            glyph = font.glyphs[byte << 8 | data[index + 1]]
            left = width - x - glyph.width
            for row in range(GLYPH_ROWS):
                for column in range(GLYPH_COLUMNS):
                    if glyph.pixels[row][column] and 0 <= left + column < width:
                        if y + row < height:
                            boxes[-1].putpixel((left + column, y + row), (255, 255, 255))
            x += glyph.width
            index += 2
            continue
        if byte == ord("\n"):
            x, y = start, y + 11
        elif data[index + 1] == ord("+"):
            x = (width - _line_width(font, data, index + 2)) // 2
        elif data[index + 1] == ord("W") and box is PmdTextBox.DIALOGUE:
            # The floating text's arrow stays below the text, at the screen's centre.
            arrow = width - x - 14 + 3
            ImageDraw.Draw(boxes[-1]).polygon(
                [(arrow, y + 4), (arrow + 8, y + 4), (arrow + 4, y + 8)], fill=(150, 150, 150)
            )
        elif data[index + 1] == ord("P"):
            boxes.append(Image.new("RGB", (width, height), (24, 32, 72)))
            x, y = start, 2
        index += 1 if byte == ord("\n") else 2
    return pages_right_to_left(boxes)


def _line_width(font: PmdRtlFont, data: bytes, index: int) -> int:
    """GetStringLineWidth from ``index``: glyph widths up to the line or box end."""
    total = 0
    while index < len(data) and data[index] and data[index] != ord("\n"):
        if data[index] == ARABIC_LEAD:
            total += font.glyphs[data[index] << 8 | data[index + 1]].width
        elif data[index + 1] == ord("P"):
            break
        index += 2
    return total


def strings_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 90)


def pmd_command_token(token_id: str, command: PmdCommand) -> InlineToken:
    if command.name == NEWLINE_COMMAND.name:
        kind = TokenKind.LINE_BREAK
    elif command.name in PAGE_COMMANDS:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return command_token(token_id, kind, command.data.hex(" "), name=command.name)


def pmd_stream(pieces: tuple[Piece, ...], prefix: str = "t") -> TokenStream:
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(pmd_command_token(f"{prefix}{number}", piece))
    return TokenStream(tuple(tokens))


@dataclass(frozen=True, slots=True)
class PmdArabicEncoding:
    data: bytes
    widths: tuple[int, ...]


class PmdArabicEncoder:
    """Convert logical Arabic text into PMD bytes in right-to-left paint order."""

    def __init__(self, font: PmdRtlFont | None = None) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.font = font
        glyph_map = build_pmd_arabic_glyph_map()
        if font is not None:
            self.sequences = dict(font.sequences)
            self.advances: dict[int, int] | None = font.advances()
        else:
            # Without a font, forms that may split keep one code and widths are unknown.
            self.sequences = {
                character: codes[:1] for character, codes in glyph_map.sequences.items()
            }
            self.advances = None

    def encode(self, pieces: tuple[Piece, ...], box: PmdTextBox) -> PmdArabicEncoding:
        """Encode a string (with its terminator) and measure its lines against ``box``."""
        allowed = ALLOWED_COMMANDS[box]
        for piece in pieces:
            if isinstance(piece, PmdCommand) and piece.name not in allowed:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"PMD Arabic v1 does not support {piece.notation!r} in {box} text",
                )
        stream = pmd_stream(pieces)
        reject_mirrored(stream, "PMD Arabic v1")
        reject_combining_marks(stream, "PMD Arabic font v1")
        data = bytearray()
        widths = [0]
        lines_in_box = 1
        for token in rtl_paint_order(self.pipeline, stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    for code in self.code_sequence(character):
                        data += code_bytes(code)
                        if self.advances is not None:
                            widths[-1] += self.advances[code]
                continue
            command = bytes(command_codes(token, "PMD"))
            data += command
            if token.name == NEWLINE_COMMAND.name:
                widths.append(0)
                lines_in_box += 1
            elif token.name in PAGE_COMMANDS:
                widths.append(0)
                lines_in_box = 1
            if lines_in_box > LINES_PER_BOX[box]:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A PMD {box} box holds {LINES_PER_BOX[box]} line(s)",
                )
        if self.advances is not None:
            limit = LINE_WIDTH[box]
            for number, width in enumerate(widths, 1):
                if width > limit:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"Line {number} needs {width}px; a PMD {box} line holds {limit}px",
                    )
        data.append(0)
        return PmdArabicEncoding(data=bytes(data), widths=tuple(widths))

    def code_sequence(self, character: str) -> tuple[int, ...]:
        sequence = self.sequences.get(character)
        if sequence is not None:
            return sequence
        raise no_glyph(character, "PMD Arabic")


def validate_command_skeleton(source: tuple[str, ...], pieces: tuple[Piece, ...]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    require_same_commands("PMD", source, notation_skeleton(pieces), "".join)
