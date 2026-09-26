"""Arabic support for the cutscene scripts of *Castlevania: Symphony of the Night*.

The game types a speaker's lines with glyphs of its 8x8 font, each copied into
the image of the line being typed (in VRAM) eight pixels right of the one
before. The overlay (``classic_retro.rom.sotn_arabic``) keeps that typewriter
and gives it a second font: a code from ``0x80`` is a glyph of the Arabic
font, which a hook draws into an image of the line in RAM at the pen, the pen
starting each line at its right edge (``LINE_RIGHT``) and moving left by each
glyph's width; the whole line then goes to VRAM. A line fills from the right,
and the typewriter reveals it from the right. A translated message holds its
glyphs in right-to-left paint order: the first glyph of a line is its
rightmost one. The speaker's name is drawn the same way, from the right edge,
into an image of its own.

The dialogue's lines are made 16 rows apart (they were 12), three to a box:
the glyphs are 16 rows tall and up to 16 pixels wide, drawn from the reference
font at the largest size where every form fits, on row 12. Their pixels stay
off the top row, which keeps lines apart. Coverage becomes two colours of the
dialogue's palette: 6, the grey of the English letters, from ``INK_LEVEL``,
and 2, a darker grey that smooths the strokes, from ``SOFT_LEVEL``. The space
is a glyph of its own (``SPACE_WIDTH`` pixels), and ``.``, ``!`` and ``:``,
which the reference font lacks, are drawn by hand. Codes ``0x80``..``0xFF``
go to the characters the script uses: the space, the punctuation, then the
forms.

A line may hold ``LINE_WIDTH`` pixels, the English lines' own room: they start
at column 8 of the line image and the longest (19 letters) ends at column 160,
where the Arabic lines end. The box's right end stays clear, as in English:
the boss's health bar shows there while the last message is on screen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import (
    reject_combining_marks,
    reject_mirrored,
    reject_text_newlines,
    rtl_paint_order,
)
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.sotn import (
    ARGUMENTS,
    GLYPH_START,
    LINE_BREAK,
    Piece,
    SotnCommand,
    notation_skeleton,
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
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

ARABIC_CODES = tuple(range(0x80, 0x100))
GLYPH_ROWS = 16
GLYPH_COLUMNS = 16
GLYPH_BYTES = GLYPH_ROWS * GLYPH_COLUMNS // 2
BASELINE = 12
TOP_ROW = 1
INK = 6
SOFT = 2
INK_LEVEL = 140
SOFT_LEVEL = 60
SIZES = range(16, 7, -1)
SPACE_WIDTH = 4
# The line image: 192 pixels, a line's text ending at LINE_RIGHT; the English
# lines start at column 8 and end by column 160.
LINE_PIXELS = 192
LINE_RIGHT = 160
LINE_WIDTH = LINE_RIGHT - 8
# Three lines show at a time; a fourth scrolls the box.
VISIBLE_LINES = 3
# Punctuation the reference font lacks, drawn on the baseline.
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    ".": ("##", "##"),
    "!": ("##", "##", "##", "##", "##", "##", "..", "##", "##"),
    ":": ("##", "##", "..", "..", "..", "##", "##"),
}
# The dots of final and isolated yeh reach below the glyph: raised a row.
_RAISED_FORMS = frozenset("ﻱﻲ")


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    return (" ", *_PUNCTUATION_INK, *arabic_presentation_repertoire())


def sotn_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from 0x80 for the characters a script uses, in the font's order."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], "SOTN Arabic")
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="SOTN Arabic glyphs",
    )


@dataclass(frozen=True, slots=True)
class SotnGlyph:
    """A glyph of the Arabic font: its advance and 16 rows of 16 pixels."""

    width: int
    pixels: tuple[tuple[int, ...], ...]

    def stored(self) -> bytes:
        """16 rows of 8 bytes, as the hook reads them: pixel x in the low nibble when even."""
        data = bytearray()
        for row in self.pixels:
            for x in range(0, GLYPH_COLUMNS, 2):
                data.append(row[x] | row[x + 1] << 4)
        return bytes(data)


def sotn_glyph(values: Mapping[tuple[int, int], int], width: int) -> SotnGlyph:
    """A glyph of ``width`` from pixel values; nothing may lie outside its advance."""
    if not 1 <= width <= GLYPH_COLUMNS:
        raise FormDoesNotFit
    if any(not (0 <= x < width and TOP_ROW <= y < GLYPH_ROWS) for x, y in values):
        raise FormDoesNotFit
    pixels = tuple(
        tuple(values.get((x, y), 0) for x in range(GLYPH_COLUMNS)) for y in range(GLYPH_ROWS)
    )
    return SotnGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class SotnFont:
    """Every glyph by code, and each character's code."""

    glyphs: dict[int, SotnGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def width(self, code: int) -> int:
        return self.glyphs[code].width

    def glyph_table(self) -> bytes:
        """The glyphs from 0x80 to the last one, ``GLYPH_BYTES`` each; blank where none."""
        blank = bytes(GLYPH_BYTES)
        return b"".join(
            self.glyphs[code].stored() if code in self.glyphs else blank
            for code in range(ARABIC_CODES[0], max(self.glyphs) + 1)
        )

    def width_table(self) -> bytes:
        """A width for each code from 0x80; 0 where there is no glyph."""
        return bytes(self.glyphs[code].width if code in self.glyphs else 0 for code in ARABIC_CODES)


def build_sotn_font(
    font_path: Path, glyph_map: GlyphCodes, *, sizing: Iterable[str] | None = None
) -> SotnFont:
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
        "Selected font cannot fit the SOTN 16x16 glyphs",
    )
    rendered[" "] = sotn_glyph({}, SPACE_WIDTH)
    for character, rows in _PUNCTUATION_INK.items():
        ink = pattern_pixels(rows, top=BASELINE - len(rows))
        rendered[character] = sotn_glyph(dict.fromkeys(ink, INK), len(rows[0]) + 1)
    glyphs: dict[int, SotnGlyph] = {}
    sequences: dict[str, tuple[int, ...]] = {}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        sequences[character] = codes
        glyphs[codes[0]] = rendered[character]
    return SotnFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _glyphs(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> dict[str, SotnGlyph] | None:
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


def _glyph(form: DrawnForm) -> SotnGlyph:
    """The form's pixels as the palette's colours; the grey beyond its advance left out."""
    soft = {pixel for pixel in form.soft if pixel[0] < form.advance}
    return sotn_glyph({**dict.fromkeys(soft, SOFT), **dict.fromkeys(form.ink, INK)}, form.advance)


# ---------------------------------------------------------------------------
# Encoding translated messages


def arabic_command_token(token_id: str, command: SotnCommand) -> InlineToken:
    kind = TokenKind.LINE_BREAK if command.code == LINE_BREAK else TokenKind.CONTROL
    return command_token(token_id, kind, command.data.hex(" "), name=f"{command.code:02X}")


def paint_stream(pieces: Sequence[Piece]) -> TokenStream:
    """A message in right-to-left paint order."""
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"t{number}", piece))
    stream = TokenStream(tuple(tokens))
    reject_text_newlines(stream, "Write a line end as a new line of the notation")
    reject_mirrored(stream, "SOTN Arabic v1")
    reject_combining_marks(stream, "SOTN Arabic font v1")
    return rtl_paint_order(legacy_renderer_pipeline(), stream)


def painted_characters(pieces: Sequence[Piece]) -> set[str]:
    """The characters a message paints."""
    return {
        character
        for token in paint_stream(pieces).tokens
        if isinstance(token, TextToken)
        for character in token.text
    }


@dataclass(frozen=True, slots=True)
class SotnPlace:
    """A glyph as the hook draws it: ``pen`` pixels left of the line's right edge, ``width`` wide."""

    code: int
    pen: int
    width: int

    @property
    def left(self) -> int:
        """Its first column in the line image."""
        return LINE_RIGHT - self.pen - self.width


@dataclass(frozen=True, slots=True)
class SotnLine:
    places: tuple[SotnPlace, ...]

    @property
    def width(self) -> int:
        return sum(place.width for place in self.places)


def lay_out(data: bytes, width: Mapping[int, int] | None = None) -> tuple[SotnLine, ...]:
    """The lines of a translated message's bytes, each glyph where the hook draws it."""
    lines: list[SotnLine] = []
    places: list[SotnPlace] = []
    pen = 0
    index = 0
    while index < len(data):
        code = data[index]
        if code >= GLYPH_START:
            glyph_width = width[code] if width is not None else 0
            places.append(SotnPlace(code, pen, glyph_width))
            pen += glyph_width
            index += 1
            continue
        if code == LINE_BREAK:
            lines.append(SotnLine(tuple(places)))
            places, pen = [], 0
        index += 1 + ARGUMENTS[code]
    lines.append(SotnLine(tuple(places)))
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class SotnArabicEncoding:
    """A translated message's bytes and, with a font, its lines."""

    data: bytes
    lines: tuple[SotnLine, ...] | None

    @property
    def line_widths(self) -> tuple[int, ...] | None:
        return None if self.lines is None else tuple(line.width for line in self.lines)


class SotnArabicEncoder:
    """Convert logical Arabic in notation into the script's bytes, in paint order."""

    def __init__(self, glyph_map: GlyphCodes, font: SotnFont | None = None) -> None:
        self.sequences: Mapping[str, tuple[int, ...]] = glyph_map.sequences
        self.font = font

    def encode(self, pieces: Sequence[Piece]) -> SotnArabicEncoding:
        data = bytearray()
        for token in paint_stream(pieces).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    data += bytes(self.codes(character))
                continue
            data += bytes(command_codes(token, "SOTN"))
        if self.font is None:
            return SotnArabicEncoding(bytes(data), None)
        lines = lay_out(
            bytes(data), {code: glyph.width for code, glyph in self.font.glyphs.items()}
        )
        for number, line in enumerate(lines, 1):
            if line.width > LINE_WIDTH:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {line.width}px; a line holds {LINE_WIDTH}px",
                )
        return SotnArabicEncoding(bytes(data), lines)

    def encode_name(self, text: str) -> SotnArabicEncoding:
        """A speaker's name: text only, one line."""
        if not text or "\n" in text or "{" in text:
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "A name is one line of text")
        return self.encode((text,))

    def codes(self, character: str) -> tuple[int, ...]:
        codes = self.sequences.get(character)
        if codes is not None:
            return codes
        raise no_glyph(character, "SOTN Arabic")


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; line ends are its own."""
    require_same_commands("SOTN", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The box's dark blue, and the palette's two greys.
PREVIEW_COLOURS = {0: (24, 32, 88), INK: (205, 205, 205), SOFT: (131, 131, 131)}
PREVIEW_MARGIN = 6
NAME_COLOUR = (60, 72, 140)


def font_preview(font: SotnFont) -> Image.Image:
    """Atlas of the glyphs: ink white, grey grey, width dark red, baseline blue."""
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

    return glyph_atlas(len(codes), GLYPH_COLUMNS, GLYPH_ROWS, colour)


def _draw_line(image: Image.Image, font: SotnFont, line: SotnLine, top: int) -> None:
    for place in line.places:
        left = PREVIEW_MARGIN + place.left
        for y, values in enumerate(font.glyphs[place.code].pixels):
            for x, value in enumerate(values[: place.width]):
                if value:
                    image.putpixel((left + x, top + y), PREVIEW_COLOURS[value])


def message_preview(font: SotnFont, name: bytes, data: bytes) -> Image.Image:
    """A translated message as the box types it: the name, then every line, from the right.

    The box shows three lines at a time; the preview stacks them all, a dim
    rule under every third.
    """
    widths = {code: glyph.width for code, glyph in font.glyphs.items()}
    lines = lay_out(data, widths)
    height = 2 * PREVIEW_MARGIN + GLYPH_ROWS * (1 + len(lines))
    image = Image.new("RGB", (LINE_PIXELS + 2 * PREVIEW_MARGIN, height), PREVIEW_COLOURS[0])
    for x in range(PREVIEW_MARGIN, PREVIEW_MARGIN + LINE_PIXELS):
        image.putpixel((x, PREVIEW_MARGIN + GLYPH_ROWS - 1), NAME_COLOUR)
    _draw_line(image, font, lay_out(name, widths)[0], PREVIEW_MARGIN)
    for number, line in enumerate(lines):
        top = PREVIEW_MARGIN + GLYPH_ROWS * (1 + number)
        _draw_line(image, font, line, top)
        if number % VISIBLE_LINES == VISIBLE_LINES - 1 and number + 1 < len(lines):
            for x in range(PREVIEW_MARGIN, PREVIEW_MARGIN + LINE_PIXELS, 2):
                image.putpixel((x, top + GLYPH_ROWS - 1), NAME_COLOUR)
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 150)
