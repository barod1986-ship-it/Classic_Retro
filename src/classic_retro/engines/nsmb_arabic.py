"""Arabic support for the *New Super Mario Bros.* (DS) text engine.

The game centres every line of a message on its own and draws it at once, from
the left; nothing types a line out, wraps it or aligns it to one side. A
translated message is therefore stored in visual order: each line holds its
glyphs from the leftmost to the rightmost, the reverse of the order it is read
in, and the game draws it as it is. No routine of the game changes.

The glyphs are the forms of the reference font, drawn into the game's font
(``font_a.NFTR``) in place of its 166 kana, which the English game never
shows; their codes become the Arabic glyphs' codes (``ARABIC_CODES``), given
only to the characters the script uses. A glyph is 11x15 pixels; a form wider
than that (``SPLIT_FORMS``) is two glyphs, its left half first. The forms are
drawn at the largest size where every form of the repertoire fits the cell on
row 11 as baseline, two rows above the Latin letters' baseline, because
Arabic letters reach further below it: alef with hamza gets a hamza drawn by
hand (``alef_with_mark``) and final and isolated yeh are raised a row. Ink is
the glyphs' one value (1), as in the game's letters; the game draws the
shadow. The space is a glyph of ``SPACE_WIDTH`` pixels, and ``.``, ``!`` and
``:`` are drawn by hand on the Arabic baseline.

Colours are laid out again: every glyph keeps the colour it has in the
logical text, colour escapes go where the colour changes in visual order, and
each line ends in the colour its logical text ends in. A number the game
writes in (``{01:..}``) is one unit of its line, and its digits read left to
right, as numbers do in Arabic. A line holds Arabic, spaces, punctuation and
that number only: anything with a direction of its own would need the bidi
algorithm's reordering, not a reversed line.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.nsmb import (
    CELL_HEIGHT,
    CELL_WIDTH,
    NEWLINE,
    NUMBER,
    colour_escape,
    escape_colour,
    notation_skeleton,
    split_lines,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    INK_THRESHOLD,
    DrawnForm,
    FormDoesNotFit,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    pattern_pixels,
    raised_form,
)
from classic_retro.font.nftr import GlyphWidth
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.bmg import BmgEscape, Piece
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    TokenKind,
    TokenMovement,
    TokenStream,
)

BASELINE = 11
INK = 1
INK_LEVEL = INK_THRESHOLD
# A dot whose coverage stays under the ink level keeps its strongest pixel.
MARK_LEVEL = 60
SIZES = range(14, 7, -1)
SPLIT_WIDTH = 2 * CELL_WIDTH
SPACE_WIDTH = 4
# The codes of the font's kana, in order: the Arabic glyphs' codes.
ARABIC_CODES = (
    *range(0x3041, 0x3090),
    0x3092,
    0x3093,
    *range(0x30A1, 0x30F0),
    *range(0x30F2, 0x30F7),
    0x30FC,
)
# Punctuation the reference font lacks, drawn on the Arabic baseline.
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    ".": ("##", "##"),
    "!": ("##", "##", "##", "##", "##", "..", "##", "##"),
    ":": ("##", "##", "..", "..", "##", "##"),
}
# Hamza above alef reaches above the cell at the reference size: the font's
# alef, cut below a hamza drawn on rows 0-1.
_HAMZA_MARK = ("##", "#.")
_MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {
    "ﺃ": ("ﺍ", _HAMZA_MARK),
    "ﺄ": ("ﺎ", _HAMZA_MARK),
}
# The dots of final and isolated yeh reach below the cell: these forms are
# raised a row; the final form keeps a pixel on the joining row.
_RAISED_FORMS = frozenset("ﻱﻲ")
# Forms wider than a cell at the reference font's size: two glyphs each.
_SPLIT_NAMES = {
    "SEEN": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "SHEEN": ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"),
    "SAD": ("ISOLATED", "FINAL"),
    "DAD": ("ISOLATED", "FINAL"),
    "FEH": ("ISOLATED", "FINAL"),
}
SPLIT_FORMS = frozenset(
    unicodedata.lookup(f"ARABIC LETTER {letter} {form} FORM")
    for letter, forms in _SPLIT_NAMES.items()
    for form in forms
)
# The game writes a Star Coin count in the font's digits (7 pixels wide, but 0
# and 1): two digits at most.
NUMBER_WIDTH = 14


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    return (" ", *_PUNCTUATION_INK, *arabic_presentation_repertoire())


def nsmb_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes for the characters a script uses: the space, the punctuation, then the forms.

    A split form takes two codes, its left half's then its right half's.
    """
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], "New Super Mario Bros. Arabic")
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="New Super Mario Bros. Arabic glyphs",
        doubled=SPLIT_FORMS,
    )


@dataclass(frozen=True, slots=True)
class NsmbGlyph:
    """An Arabic glyph: its width and a full cell of pixel values."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    @property
    def widths(self) -> GlyphWidth:
        return GlyphWidth(0, self.width, self.width)


def nsmb_glyph(ink: Iterable[tuple[int, int]], width: int, left: int = 0) -> NsmbGlyph:
    """Columns ``left``..``left + width`` of some ink as a glyph; nothing may leave the cell."""
    ink = {(x - left, y) for x, y in ink if left <= x < left + width}
    if not 1 <= width <= CELL_WIDTH or any(not 0 <= y < CELL_HEIGHT for _, y in ink):
        raise FormDoesNotFit
    pixels = tuple(
        tuple(INK if (x, y) in ink else 0 for x in range(CELL_WIDTH)) for y in range(CELL_HEIGHT)
    )
    return NsmbGlyph(width, pixels)


def _parts(character: str, form: DrawnForm) -> tuple[NsmbGlyph, ...]:
    """A form as one glyph, or a split form as its left half then its right half."""
    if character not in SPLIT_FORMS:
        return (nsmb_glyph(form.ink, form.advance),)
    left = form.advance // 2
    return (
        nsmb_glyph(form.ink, left),
        nsmb_glyph(form.ink, form.advance - left, left),
    )


@dataclass(frozen=True, slots=True)
class NsmbArabicFont:
    """Every Arabic glyph by code, and each character's codes in visual order."""

    glyphs: dict[int, NsmbGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def code_width(self, code: int) -> int:
        return self.glyphs[code].width

    def width(self, character: str) -> int:
        return sum(self.glyphs[code].width for code in self.sequences[character])


def build_nsmb_arabic_font(
    font_path: Path, glyph_map: GlyphCodes, *, sizing: Iterable[str] | None = None
) -> NsmbArabicFont:
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
    alefs = {alef for marked, (alef, _) in _MARKED_ALEF.items() if marked in sized | used}
    drawn = tuple(sorted(sized | used | alefs, key=ord))
    _, size, forms = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        lambda font: _forms(font, drawn),
        "Selected font cannot fit the New Super Mario Bros. 11x15 glyphs",
    )
    parts: dict[str, tuple[NsmbGlyph, ...]] = {
        character: _parts(character, form) for character, form in forms.items()
    }
    parts[" "] = (nsmb_glyph((), SPACE_WIDTH),)
    for character, rows in _PUNCTUATION_INK.items():
        ink = pattern_pixels(rows, top=BASELINE - len(rows))
        parts[character] = (nsmb_glyph(ink, len(rows[0]) + 1),)
    glyphs: dict[int, NsmbGlyph] = {}
    sequences: dict[str, tuple[int, ...]] = {}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        if len(codes) != len(parts[character]):
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                f"U+{ord(character):04X} is {len(parts[character])} glyphs; "
                f"the map gives it {len(codes)}",
            )
        glyphs.update(zip(codes, parts[character], strict=True))
        sequences[character] = codes
    return NsmbArabicFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _forms(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> dict[str, DrawnForm] | None:
    """Every form at this size, or None when one leaves its cell (two cells if split)."""
    try:
        forms = {
            character: _drawn(font, character)
            for character in characters
            if character not in _MARKED_ALEF
        }
        for composed, (alef, mark) in _MARKED_ALEF.items():
            if composed in characters:
                forms[composed] = alef_with_mark(
                    composed, forms.get(alef) or _drawn(font, alef), mark
                )
        for character in _RAISED_FORMS & set(forms):
            forms[character] = raised_form(
                character, forms[character], height=CELL_HEIGHT, baseline=BASELINE
            )
    except FormDoesNotFit:
        return None
    for character, form in forms.items():
        limit = SPLIT_WIDTH if character in SPLIT_FORMS else CELL_WIDTH
        if form.advance > limit or any(not 0 <= y < CELL_HEIGHT for _, y in form.ink):
            return None
    return forms


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    return draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)


# ---------------------------------------------------------------------------
# Encoding translated messages


@dataclass(frozen=True, slots=True)
class Unit:
    """What a line shows at one place: a character or the number, in a colour."""

    value: str | BmgEscape
    colour: int


def check_escapes(pieces: Sequence[Piece]) -> None:
    for piece in pieces:
        if isinstance(piece, BmgEscape) and escape_colour(piece) is None and piece.kind != NUMBER:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"New Super Mario Bros. Arabic v1 does not support {piece.notation}",
            )


def visual_lines(pieces: Sequence[Piece]) -> list[tuple[list[Unit], int]]:
    """Each line's units in visual order (left to right) and the colour it ends in."""
    check_escapes(pieces)
    text = [piece for piece in pieces if isinstance(piece, str)]
    stream = TokenStream(tuple(TextToken(part) for part in text))
    reject_mirrored(stream, "New Super Mario Bros. Arabic v1")
    reject_combining_marks(stream, "New Super Mario Bros. Arabic font v1")
    lines: list[tuple[list[Unit], int]] = []
    colour = 0
    for line in split_lines(pieces):
        logical: list[Unit] = []
        for piece in line:
            if isinstance(piece, BmgEscape):
                changed = escape_colour(piece)
                if changed is None:
                    logical.append(Unit(piece, colour))
                else:
                    colour = changed
                continue
            logical.extend(Unit(character, colour) for character in piece)
        lines.append((_reversed_line(logical), colour))
    return lines


def _reversed_line(logical: list[Unit]) -> list[Unit]:
    """The line shaped and in visual order, which must be its logical order reversed."""
    tokens: list[TextToken | InlineToken] = []
    for number, unit in enumerate(logical):
        if isinstance(unit.value, BmgEscape):
            tokens.append(
                InlineToken(
                    id=f"n{number}",
                    kind=TokenKind.VARIABLE,
                    movement=TokenMovement.FREE,
                    name="number",
                )
            )
        elif tokens and isinstance(tokens[-1], TextToken):
            tokens[-1] = TextToken(tokens[-1].text + unit.value)
        else:
            tokens.append(TextToken(unit.value))
    result = legacy_renderer_pipeline().process(TokenStream(tuple(tokens)))
    shaped = _flat(result.shaped.tokens)
    visual = _flat(result.visual.tokens)
    if len(shaped) != len(logical) or visual != shaped[::-1]:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT,
            "A New Super Mario Bros. line is stored reversed: it may hold Arabic, spaces, "
            "punctuation and the number, not text of its own direction (Latin letters, digits)",
        )
    units = [
        Unit(unit.value if isinstance(unit.value, BmgEscape) else form, unit.colour)
        for unit, form in zip(logical, shaped, strict=True)
    ]
    return units[::-1]


def _flat(tokens: Sequence[TextToken | InlineToken]) -> list[str]:
    flat: list[str] = []
    for token in tokens:
        if isinstance(token, TextToken):
            flat.extend(token.text)
        else:
            flat.append(f"\x00{token.id}")
    return flat


def painted_characters(pieces: Sequence[Piece]) -> set[str]:
    """The characters (shaped forms) a message draws."""
    return {
        unit.value
        for units, _ in visual_lines(pieces)
        for unit in units
        if isinstance(unit.value, str)
    }


@dataclass(frozen=True, slots=True)
class NsmbArabicEncoding:
    """A translated message as the file stores it and, with a font, its lines' widths."""

    pieces: tuple[Piece, ...]
    line_widths: tuple[int, ...] | None


class NsmbArabicEncoder:
    """Convert logical Arabic messages into the game's visual-order BMG texts."""

    def __init__(self, glyph_map: GlyphCodes, font: NsmbArabicFont | None = None) -> None:
        self.sequences: Mapping[str, tuple[int, ...]] = glyph_map.sequences
        self.font = font

    def encode(self, pieces: Sequence[Piece], line_width: int) -> NsmbArabicEncoding:
        output: list[Piece] = []
        widths: list[int] = []
        shown = 0
        lines = visual_lines(pieces)
        for number, (units, end_colour) in enumerate(lines):
            if number:
                output.append(NEWLINE)
            width = 0
            for unit in units:
                if unit.colour != shown:
                    output.append(colour_escape(unit.colour))
                    shown = unit.colour
                if isinstance(unit.value, BmgEscape):
                    output.append(unit.value)
                    width += NUMBER_WIDTH
                    continue
                codes = self.codes(unit.value)
                output.append("".join(map(chr, codes)))
                if self.font is not None:
                    width += sum(self.font.code_width(code) for code in codes)
            if end_colour != shown:
                output.append(colour_escape(end_colour))
                shown = end_colour
            widths.append(width)
        if self.font is None:
            return NsmbArabicEncoding(_merged(output), None)
        for number, width in enumerate(widths, 1):
            if width > line_width:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {width}px; this message's lines hold {line_width}px",
                )
        return NsmbArabicEncoding(_merged(output), tuple(widths))

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "New Super Mario Bros. Arabic")


def _merged(pieces: Sequence[Piece]) -> tuple[Piece, ...]:
    merged: list[Piece] = []
    for piece in pieces:
        if isinstance(piece, str) and merged and isinstance(merged[-1], str):
            merged[-1] += piece
        else:
            merged.append(piece)
    return tuple(merged)


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's escapes and line ends must equal the original's."""
    require_same_commands("New Super Mario Bros.", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The file select's band: white letters with the game's grey shadow; a number
# in orange, a choice that cannot be taken in grey.
PREVIEW_BACKGROUND = (57, 182, 123)
PREVIEW_SHADOW = (98, 97, 98)
PREVIEW_COLOURS = {0: (246, 246, 246), 1: (255, 170, 60), 2: (170, 170, 170)}
PREVIEW_MARGIN = 6
_SHADOW = ((1, 0), (0, 1), (1, 1))
# A number stands for two digits the game writes in.
_DIGIT = ("#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#####")


def font_preview(font: NsmbArabicFont) -> Image.Image:
    """Atlas of the Arabic glyphs: ink white, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        if glyph.pixels[y][x] == INK:
            return (255, 255, 255)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), CELL_WIDTH, CELL_HEIGHT, colour)


def message_preview(font: NsmbArabicFont, pieces: Sequence[Piece], line_width: int) -> Image.Image:
    """A translated message as the game draws it: every line centred, with the shadow.

    ``pieces`` is the stored message, in visual order.
    """
    lines = _stored_lines(font, pieces)
    image = Image.new(
        "RGB",
        (line_width + 2 * PREVIEW_MARGIN, len(lines) * CELL_HEIGHT + 2 * PREVIEW_MARGIN),
        PREVIEW_BACKGROUND,
    )
    for number, line in enumerate(lines):
        width = sum(width for width, _, _ in line)
        left = PREVIEW_MARGIN + (line_width - width) // 2
        top = PREVIEW_MARGIN + number * CELL_HEIGHT
        ink: list[tuple[int, int, int]] = []
        for advance, pixels, colour in line:
            ink.extend((left + x, top + y, colour) for x, y in pixels)
            left += advance
        for x, y, _ in ink:
            for dx, dy in _SHADOW:
                if 0 <= x + dx < image.width and 0 <= y + dy < image.height:
                    image.putpixel((x + dx, y + dy), PREVIEW_SHADOW)
        for x, y, colour in ink:
            image.putpixel((x, y), PREVIEW_COLOURS.get(colour, PREVIEW_COLOURS[0]))
    return image


def _stored_lines(
    font: NsmbArabicFont, pieces: Sequence[Piece]
) -> list[list[tuple[int, set[tuple[int, int]], int]]]:
    """Each stored line as (advance, ink pixels, colour) per glyph or number."""
    digit = pattern_pixels(_DIGIT, top=BASELINE - len(_DIGIT))
    number = digit | {(x + NUMBER_WIDTH // 2, y) for x, y in digit}
    lines: list[list[tuple[int, set[tuple[int, int]], int]]] = [[]]
    colour = 0
    for piece in pieces:
        if isinstance(piece, BmgEscape):
            changed = escape_colour(piece)
            if changed is not None:
                colour = changed
            else:
                lines[-1].append((NUMBER_WIDTH, number, colour))
            continue
        for character in piece:
            if character == NEWLINE:
                lines.append([])
                continue
            glyph = font.glyphs[ord(character)]
            pixels = {
                (x, y)
                for y, row in enumerate(glyph.pixels)
                for x, value in enumerate(row)
                if value == INK
            }
            lines[-1].append((glyph.width, pixels, colour))
    return lines


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 150)
