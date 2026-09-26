"""Arabic support for the *Phantom Hourglass* (Nintendo DS) text engine.

The ROM overlay (``classic_retro.rom.phantom_hourglass_arabic``) turns the
message printer right to left without changing how it moves its pen. The
printer still lays a line out from the left; a hook draws each right-to-left
glyph at the mirror of its place on the canvas:

    x' = canvas width - x - glyph width

A line then starts at the box's right edge, as far in as the pen starts on the
left, and grows leftwards; the typewriter reveals it from the right. A
translated message holds its glyphs in right-to-left paint order: the first
glyph of a line is its rightmost one, which for Arabic is the reading order.

The right-to-left glyphs are the forms of the reference font, drawn into the
game's font (``zeldaDS_15.nftr``) in place of its 170 kana, which no text of
the game uses: their codes (``ARABIC_CODES``, ``3041`` to ``30FC``) are the
codes the hook mirrors. Only the characters the script uses get codes, in a
fixed order (the space, the punctuation drawn here, then the forms by code
point), so the same characters always get the same codes. Every glyph of a
translated line is right to left, its spaces and punctuation included, so the
whole line mirrors; the game's own glyphs are drawn where it draws them.

A glyph is up to 14 pixels wide and 16 rows tall; its width is its advance and
the printer's letter spacing, so the glyphs the printer lays out a pixel apart
meet once mirrored. The forms are drawn at the size of the game's letters
(``SIZES`` from 11 pixels down, the largest where every form fits) on row 11 as
baseline. Seen and sheen, alone or at a word's end, are wider than a cell and
take two glyphs, the right half first. Coverage from ``INK_LEVEL`` is the full
ink (3) and from ``SOFT_LEVEL`` the lightest (1), as the game smooths its own
letters; a dot that falls between pixels keeps its strongest pixel as ink.
``.``, ``!`` and ``:`` are drawn by hand on the baseline.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.phantom_hourglass import (
    BOX_WIDTH,
    CELL_HEIGHT,
    CELL_WIDTH,
    COLOUR,
    LETTER_SPACING,
    LINE_FEED,
    LINE_SPACING,
    PAGE_LINES,
    PEN_START,
    TIMING,
    escape_colour,
    pages,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    INK_THRESHOLD,
    DrawnForm,
    FormDoesNotFit,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    pattern_pixels,
)
from classic_retro.font.nftr import GlyphWidth
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.text.bmg import (
    NEWLINE,
    BmgEscape,
    Piece,
    notation_skeleton,
    split_lines,
)
from classic_retro.text.commands import command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

INK = 3
SOFT = 1
BASELINE = 11
INK_LEVEL = INK_THRESHOLD
SOFT_LEVEL = 48
# A dot whose coverage stays under the ink level keeps its strongest pixel.
MARK_LEVEL = 60
SIZES = range(11, 7, -1)
SPACE_WIDTH = 5
# The codes of the font's kana, in order: the Arabic glyphs' codes. The hook
# mirrors every code from RTL_FIRST to RTL_LAST.
ARABIC_CODES = (*range(0x3041, 0x3094), *range(0x30A1, 0x30F7), 0x30FC)
RTL_FIRST = ARABIC_CODES[0]
RTL_LAST = ARABIC_CODES[-1]
# How wide a line of the prologue may be: from the pen's start to as far from
# the box's other edge.
LINE_WIDTH = BOX_WIDTH - 2 * PEN_START
# Drawn by hand, on the baseline, like the game's own punctuation.
_HAND_DRAWN: dict[str, tuple[int, tuple[str, ...]]] = {
    ".": (BASELINE - 2, ("##", "##")),
    "!": (BASELINE - 10, ("##", "##", "##", "##", "##", "##", "..", "..", "##", "##")),
    ":": (BASELINE - 8, ("##", "##", "..", "..", "..", "..", "##", "##")),
}
# Forms wider than a cell at the game's size: two glyphs each.
_SPLIT_NAMES = {"SEEN": ("ISOLATED", "FINAL"), "SHEEN": ("ISOLATED", "FINAL")}
SPLIT_FORMS = frozenset(
    unicodedata.lookup(f"ARABIC LETTER {letter} {form} FORM")
    for letter, forms in _SPLIT_NAMES.items()
    for form in forms
)
# The escapes a translation may hold: the typewriter's timing and colours.
_ESCAPE_KINDS = frozenset({TIMING, COLOUR})


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic glyphs can draw, in the order codes follow."""
    return (" ", *_HAND_DRAWN, *arabic_presentation_repertoire())


def ph_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes for the characters a script uses: the space, the punctuation, then the forms.

    A split form takes two codes, its right half's then its left half's.
    """
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], "Phantom Hourglass Arabic")
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="Phantom Hourglass Arabic glyphs",
        doubled=SPLIT_FORMS,
    )


@dataclass(frozen=True, slots=True)
class PhGlyph:
    """An Arabic glyph: its width and a full cell of pixel values (0, 1 soft, 3 ink)."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    @property
    def widths(self) -> GlyphWidth:
        """The font's widths: the bitmap is ``width`` wide, the pen moves a pixel less."""
        return GlyphWidth(0, self.width, self.width - LETTER_SPACING)


def ph_glyph(
    ink: Iterable[tuple[int, int]],
    width: int,
    soft: Iterable[tuple[int, int]] = (),
    left: int = 0,
) -> PhGlyph:
    """Columns ``left``..``left + width`` of a form as a glyph; nothing may leave the cell."""
    ink = {(x - left, y) for x, y in ink if left <= x < left + width}
    soft = {(x - left, y) for x, y in soft if left <= x < left + width} - ink
    if not LETTER_SPACING <= width <= CELL_WIDTH or any(
        not 0 <= y < CELL_HEIGHT for _, y in ink | soft
    ):
        raise FormDoesNotFit
    pixels = tuple(
        tuple(INK if (x, y) in ink else SOFT if (x, y) in soft else 0 for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    )
    return PhGlyph(width, pixels)


def _parts(character: str, form: DrawnForm) -> tuple[PhGlyph, ...]:
    """A form as one glyph, or a split form as its right half then its left half."""
    if character not in SPLIT_FORMS:
        return (ph_glyph(form.ink, form.advance, form.soft),)
    left = form.advance // 2
    return (
        ph_glyph(form.ink, form.advance - left, form.soft, left),
        ph_glyph(form.ink, left, form.soft),
    )


@dataclass(frozen=True, slots=True)
class PhArabicFont:
    """Every Arabic glyph by code, and each character's codes in paint order."""

    glyphs: dict[int, PhGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def code_width(self, code: int) -> int:
        return self.glyphs[code].width


def build_ph_arabic_font(
    font_path: Path, glyph_map: GlyphCodes, *, sizing: Iterable[str] | None = None
) -> PhArabicFont:
    """Rasterize the forms ``glyph_map`` holds and add the space and the hand-drawn marks.

    The size is the largest of ``SIZES`` where every form of ``sizing`` fits:
    the whole repertoire by default, so a new word never changes the size of
    the others (a test may give a few forms of its own font).
    """
    used = {
        character
        for character in glyph_map.characters
        if character != " " and character not in _HAND_DRAWN
    }
    sized = set(arabic_presentation_repertoire() if sizing is None else sizing)
    drawn = tuple(sorted(sized | used, key=ord))
    _, size, parts = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        lambda font: _glyphs(font, drawn),
        "Selected font cannot fit the Phantom Hourglass 14x16 glyphs",
    )
    parts[" "] = (ph_glyph((), SPACE_WIDTH),)
    for character, (top, rows) in _HAND_DRAWN.items():
        parts[character] = (ph_glyph(pattern_pixels(rows, top=top), len(rows[0]) + 2),)
    glyphs: dict[int, PhGlyph] = {}
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
    return PhArabicFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, tuple[PhGlyph, ...]] | None:
    """Every form at this size as its glyphs, or None when one leaves its cell."""
    try:
        return {character: _parts(character, _drawn(font, character)) for character in characters}
    except FormDoesNotFit:
        return None


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(
        font,
        character,
        BASELINE,
        ink_level=INK_LEVEL,
        soft_level=SOFT_LEVEL,
        mark_level=MARK_LEVEL,
    )
    # Smoothing right of the advance would fall on the glyph painted before.
    soft = frozenset(pixel for pixel in form.soft if pixel[0] < form.advance)
    return DrawnForm(form.ink, soft, form.advance)


# ---------------------------------------------------------------------------
# Encoding translated messages


def check_escapes(pieces: Sequence[Piece]) -> None:
    for piece in pieces:
        if isinstance(piece, BmgEscape) and piece.kind not in _ESCAPE_KINDS:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"Phantom Hourglass Arabic v1 does not support {piece.notation}",
            )


def _paint_line(line: Sequence[Piece]) -> list[Piece]:
    """One line in right-to-left paint order; escapes keep their order and split the text."""
    escapes: dict[str, BmgEscape] = {}
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(line):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
            continue
        token_id = f"e{number}"
        escapes[token_id] = piece
        tokens.append(
            command_token(token_id, TokenKind.CONTROL, piece.notation, name=piece.notation)
        )
    stream = TokenStream(tuple(tokens))
    reject_mirrored(stream, "Phantom Hourglass Arabic v1")
    reject_combining_marks(stream, "Phantom Hourglass Arabic font v1")
    painted: list[Piece] = []
    for token in rtl_paint_order(legacy_renderer_pipeline(), stream).tokens:
        if isinstance(token, TextToken):
            painted.append(token.text)
        elif isinstance(token, InlineToken):
            painted.append(escapes[token.id])
    return painted


def paint_lines(pieces: Sequence[Piece]) -> list[list[Piece]]:
    """Each line of a translated message, shaped and in right-to-left paint order."""
    check_escapes(pieces)
    return [_paint_line(line) for line in split_lines(pieces)]


def painted_characters(pieces: Sequence[Piece]) -> set[str]:
    """The characters (shaped forms, spaces, punctuation) a message draws."""
    return {
        character
        for line in paint_lines(pieces)
        for piece in line
        if isinstance(piece, str)
        for character in piece
    }


@dataclass(frozen=True, slots=True)
class PhArabicEncoding:
    """A translated message as the file stores it and, with a font, its lines' widths."""

    pieces: tuple[Piece, ...]
    line_widths: tuple[int, ...] | None


class PhArabicEncoder:
    """Convert logical Arabic messages into the game's right-to-left glyph codes."""

    def __init__(self, glyph_map: GlyphCodes, font: PhArabicFont | None = None) -> None:
        self.sequences: Mapping[str, tuple[int, ...]] = glyph_map.sequences
        self.font = font

    def encode(self, pieces: Sequence[Piece], line_width: int = LINE_WIDTH) -> PhArabicEncoding:
        output: list[Piece] = []
        widths: list[int] = []
        for number, line in enumerate(paint_lines(pieces)):
            if number:
                output.append(NEWLINE)
            width = 0
            for piece in line:
                if isinstance(piece, BmgEscape):
                    output.append(piece)
                    continue
                codes = [code for character in piece for code in self.codes(character)]
                output.append("".join(map(chr, codes)))
                if self.font is not None:
                    width += sum(self.font.code_width(code) for code in codes)
            widths.append(width)
        stored = _merged(output)
        if self.font is None:
            return PhArabicEncoding(stored, None)
        for number, width in enumerate(widths, 1):
            if width > line_width:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {width}px; the box's lines hold {line_width}px",
                )
        return PhArabicEncoding(stored, tuple(widths))

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "Phantom Hourglass Arabic")


def _merged(pieces: Sequence[Piece]) -> tuple[Piece, ...]:
    merged: list[Piece] = []
    for piece in pieces:
        if isinstance(piece, str) and merged and isinstance(merged[-1], str):
            merged[-1] += piece
        elif piece != "":
            merged.append(piece)
    return tuple(merged)


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's escapes and line ends must equal the original's."""
    require_same_commands("Phantom Hourglass", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The prologue: white letters on black, a name in blue.
PREVIEW_BACKGROUND = (0, 0, 0)
PREVIEW_COLOURS = {0: (248, 248, 248), 3: (72, 160, 248)}
PREVIEW_MARGIN = 4
LINE_HEIGHT = LINE_FEED + LINE_SPACING


def font_preview(font: PhArabicFont) -> Image.Image:
    """Atlas of the Arabic glyphs: ink white, smoothing grey, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixels[y][x]
        if value == INK:
            return (255, 255, 255)
        if value == SOFT:
            return (110, 110, 110)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), CELL_WIDTH, CELL_HEIGHT, colour)


def message_preview(font: PhArabicFont, pieces: Sequence[Piece]) -> Image.Image:
    """A translated message as the prologue's box shows it: its pages side by side,
    the first on the right, each line from the box's right edge leftwards.

    ``pieces`` is the stored message, in paint order.
    """
    size = (BOX_WIDTH + 2 * PREVIEW_MARGIN, PAGE_LINES * LINE_HEIGHT + 2 * PREVIEW_MARGIN)
    images = []
    colour = 0
    for page in pages(pieces):
        image = Image.new("RGB", size, PREVIEW_BACKGROUND)
        for row, line in enumerate(page):
            right = PREVIEW_MARGIN + BOX_WIDTH - PEN_START
            top = PREVIEW_MARGIN + row * LINE_HEIGHT
            for piece in line:
                if isinstance(piece, BmgEscape):
                    changed = escape_colour(piece)
                    colour = colour if changed is None else changed
                    continue
                for character in piece:
                    glyph = font.glyphs[ord(character)]
                    right -= glyph.width
                    _draw_glyph(image, glyph, right, top, colour)
        images.append(image)
    return pages_right_to_left(images or [Image.new("RGB", size, PREVIEW_BACKGROUND)])


def _draw_glyph(image: Image.Image, glyph: PhGlyph, left: int, top: int, colour: int) -> None:
    red, green, blue = PREVIEW_COLOURS.get(colour, PREVIEW_COLOURS[0])
    for y, values in enumerate(glyph.pixels):
        for x, value in enumerate(values[: glyph.width]):
            if value and 0 <= left + x < image.width:
                scale = value / INK
                pixel = (round(red * scale), round(green * scale), round(blue * scale))
                image.putpixel((left + x, top + y), pixel)


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 120)
