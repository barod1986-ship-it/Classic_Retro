"""Arabic support for the dialogue of *Shining Force II* (Mega Drive).

The game reads a string a symbol at a time and draws each character from a
variable-width font, one bit a pixel, 15 rows of up to 12 pixels, at the pen,
which then moves on by its width; the window's inside is 216 pixels
(``engines.sf2``). The overlay (``classic_retro.rom.sf2_arabic``) reads a
translated string from its Arabic text, not compressed, where every symbol
below the commands (``ARABIC_CODES``) is a glyph of an Arabic font of its own,
15 rows of up to 16 pixels, and the commands keep their meaning. The hook draws
each glyph at the mirror of the pen, ``RIGHT - pen - width``, while the pen
moves on as the game's does, so a line starts at the window's right; a name,
an item, a spell, a class or a number the game writes is drawn whole, left to
right, in the English font, at the mirror of its place.

The Arabic glyphs are drawn as the game's letters are: one colour, no shadow,
from the reference font at the largest size where every form of the repertoire
and every digit fits the cell, on the English letters' baseline
(``BASELINE``). The merged dots of small letters are drawn apart
(``separated_dots``); the punctuation the reference font lacks or draws too
small is drawn by hand (``PUNCTUATION``); the space keeps the game's symbol,
which speaks no sound.

A translation's notation is the English's: its tags pass to the game as they
are (``{N}``, ``{W1}``, ``{W2}``, ``{CLEAR}``, ``{NAME;0}``...). The encoder lays
the text out in lines as wide as the game's itself, a word at a time, and ends
a line with ``{N}`` where the next word would not fit; ``{N}`` in the
translation ends a line where it stands. A name the game writes is reckoned as
wide as a long one (``ISLAND_WIDTHS``).

A translation keeps the original's commands: its skeleton
(``notation_skeleton``: every tag but ``{N}``, in order, as the notation
writes it) must equal the original's (``engines.sf2.command_skeleton``), which
leaves out the same layout the encoder writes itself: the new line
(``engines.sf2.LAYOUT_COMMANDS``). ``validate_command_skeleton`` refuses a
translation that drops, adds or moves any other tag.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import check_logical_arabic, no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.sf2 import (
    END,
    FIRST_COMMAND,
    NEW_LINE,
    SPACE,
    TAGS,
    TAGS_WITH_ARGUMENT,
    command_skeleton,
)
from classic_retro.font.arabic_outline import contextual_font_data, joins_right_neighbour
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    Pixel,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    pattern_pixels,
    raised_form,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Shining Force II Arabic"
ENGINE = "Shining Force II"
# A symbol of an Arabic string below the commands is a glyph of the Arabic font,
# but 7C and 7D, which the game draws without a pause; the space keeps the game's
# symbol, which speaks no sound.
ARABIC_CODES = tuple(code for code in range(0x02, FIRST_COMMAND) if code not in (0x7C, 0x7D))
SPACE_CODE = SPACE
GLYPH_BYTES = 32
WIDEST = 16
ROWS = 15
# The row under the Arabic letters: the row under the English capitals.
BASELINE = 12
LOWEST_ROW = ROWS - 1
SIZES = range(14, 7, -1)
INK_LEVEL = 140
MARK_LEVEL = 60
DIGITS = "0123456789"
SPACE_WIDTH = 5
# Punctuation drawn by hand: rows of ink, from how many rows above the baseline.
PUNCTUATION: dict[str, tuple[tuple[str, ...], int]] = {
    ".": (("#",), 1),
    ",": ((".#", "#."), 1),
    ":": (("#", ".", ".", "#"), 5),
    "!": (("#",) * 6 + (".", "#"), 8),
    "-": (("###",), 4),
    "…": (("#.#.#",), 1),
    "،": ((".#", "#.", "##"), 3),
    "؛": ((".#", "#.", "##", "..", "#."), 6),
    "؟": ((".##.", "#..#", "#...", ".#..", "..#.", "....", "..#."), 7),
}
# Hamza above alef reaches over the cell: the font's alef, cut below a hamza
# drawn on the top rows. The tail and dots of final and isolated yeh reach
# below it: those forms are raised a row, the final keeping its joining pixel.
_HAMZA = ("##", "#.")
MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {"ﺃ": ("ﺍ", _HAMZA), "ﺄ": ("ﺎ", _HAMZA)}
RAISED_FORMS = frozenset("ﻱﻲ")
# The game's layout: the pen starts at 2, a line's last glyph starts at 204 at
# most (the game breaks the line past it) and ends by 214; the mirror of the pen
# is 216 - pen.
RIGHT = 216
LINE_START = 2
LAST_START = 204
LINE_END = 214
LINE_HEIGHT = 16
# What the game writes at run time, reckoned as wide as a long one: a name (7
# letters of the widest 10 pixels), an item, a spell or a class (12 of 8), a
# number (5 digits of 8).
ISLAND_WIDTHS = {
    "LEADER": 70,
    "NAME": 70,
    "ITEM": 96,
    "SPELL": 96,
    "CLASS": 96,
    "#": 40,
}
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SPACES_OUTSIDE_TOKENS = re.compile(r" (?![^{}]*\})")


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    order = (*PUNCTUATION, *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def sf2_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from ``ARABIC_CODES`` for the characters a translation uses, in the font's
    order; the space keeps ``SPACE_CODE``."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order) - {" "})
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    codes = assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="Shining Force II Arabic glyphs",
    )
    if " " not in used:
        return codes
    return GlyphCodes(
        (" ", *codes.characters), {" ": (SPACE_CODE,), **dict(codes.sequences.items())}
    )


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class Sf2Glyph:
    """A glyph: its width (the pen's advance) and its ink, 15 rows of 16 pixels."""

    width: int
    rows: tuple[tuple[bool, ...], ...]

    def data(self) -> bytes:
        """The game's 32 bytes: a word of the width less one, then a word a row, the
        leftmost pixel in the top bit."""
        output = bytearray((max(self.width - 1, 0)).to_bytes(2, "big"))
        for row in self.rows:
            bits = 0
            for x, ink in enumerate(row):
                if ink:
                    bits |= 0x8000 >> x
            output += bits.to_bytes(2, "big")
        return bytes(output)


@dataclass(frozen=True, slots=True)
class Sf2Font:
    """The Arabic glyphs by code, and the size they were drawn at."""

    glyphs: Mapping[int, Sf2Glyph]
    font_size: int

    def width(self, code: int) -> int:
        try:
            return self.glyphs[code].width
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The Arabic font has no glyph {code:#04x}"
            ) from None


def ink_glyph(ink: Collection[Pixel], width: int) -> Sf2Glyph:
    """Ink in a cell of 15 rows, all of it inside the width (2 to 16 pixels)."""
    if not 2 <= width <= WIDEST or any(
        not 0 <= x < width or not 0 <= y <= LOWEST_ROW for x, y in ink
    ):
        raise FormDoesNotFit
    pixels = set(ink)
    return Sf2Glyph(
        width,
        tuple(tuple((x, y) in pixels for x in range(WIDEST)) for y in range(ROWS)),
    )


def form_glyph(character: str, ink: Collection[Pixel], advance: int) -> Sf2Glyph:
    """A drawn form: as wide as its advance, but for a form that joins the glyph on its
    right, whose stroke runs on to its edge; any other keeps a free column."""
    right = max(x for x, _ in ink)
    width = right + 1 if joins_right_neighbour(character) else max(advance, right + 2)
    return ink_glyph(ink, width)


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)
    return separated_dots(character, form)


def _form(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    if character in MARKED_ALEF:
        alef, mark = MARKED_ALEF[character]
        form = alef_with_mark(character, _drawn(font, alef), mark)
    else:
        form = _drawn(font, character)
    if character in RAISED_FORMS:
        form = raised_form(character, form, height=ROWS, baseline=BASELINE)
    return form


def _drawn_glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, Sf2Glyph] | None:
    """Every character at this size, or None when one leaves the cell."""
    try:
        glyphs = {}
        for character in characters:
            form = _form(font, character)
            glyphs[character] = form_glyph(character, form.ink, form.advance)
        return glyphs
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(character: str) -> Sf2Glyph:
    rows, above = PUNCTUATION[character]
    return ink_glyph(pattern_pixels(rows, top=BASELINE - above), len(rows[0]) + 1)


def build_sf2_font(
    font_path: Path,
    glyph_map: GlyphCodes,
    used: Collection[str],
    *,
    sizing: Iterable[str] | None = None,
) -> Sf2Font:
    """The glyphs of the ``used`` characters.

    The size is the largest where every character of ``sizing`` fits: the whole
    repertoire and the digits, whatever the text uses, so a new string never
    changes the size of the others (a test may give a few characters).
    """
    drawable = {*arabic_presentation_repertoire(), *DIGITS}
    wanted = {character for character in used if character != " "}
    unknown = sorted(wanted - drawable - set(PUNCTUATION))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    drawn_set = set(drawable if sizing is None else sizing) | (wanted - set(PUNCTUATION))
    drawn = tuple(sorted(drawn_set - set(PUNCTUATION) - {" "}, key=ord))
    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        lambda font: _drawn_glyphs(font, drawn),
        "Selected font cannot fit Shining Force II's glyphs of 15 rows",
    )
    for character in PUNCTUATION:
        rendered[character] = hand_drawn_glyph(character)
    rendered[" "] = Sf2Glyph(SPACE_WIDTH, tuple((False,) * WIDEST for _ in range(ROWS)))
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        if code is None:
            raise no_glyph(character, PROFILE)
        glyphs[code] = rendered[character]
    return Sf2Font(glyphs, size)


# ---------------------------------------------------------------------------
# Encoding translated strings


def paint_text(text: str) -> str:
    """Logical text in the order it is painted from the right, its letters shaped."""
    check_logical_arabic(text, PROFILE)
    stream = TokenStream((TextToken(text),))
    reject_mirrored(stream, PROFILE)
    reject_combining_marks(stream, PROFILE)
    painted = rtl_paint_order(legacy_renderer_pipeline(), stream)
    return "".join(token.text for token in painted.tokens if isinstance(token, TextToken))


@dataclass(frozen=True, slots=True)
class Command:
    """A tag of the notation: its symbols, how wide the game draws what it writes, and
    whether it ends the line."""

    data: bytes
    width: int
    new_line: bool = False


def command(tag: str) -> Command:
    """A ``{tag}`` of the notation, as the English writes it."""
    name, _, argument = tag.partition(";")
    if not argument and name in TAGS:
        return Command(bytes((TAGS[name],)), ISLAND_WIDTHS.get(name, 0), name == "N")
    if argument and name in TAGS_WITH_ARGUMENT and argument.isdigit() and int(argument) < 0xEE:
        width = ISLAND_WIDTHS["NAME"] if name == "NAME" else 0
        return Command(bytes((TAGS_WITH_ARGUMENT[name], int(argument))), width)
    raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No tag {{{tag}}}")


def _pieces(word: str) -> list[str | Command]:
    """A word's text runs and tags, in reading order."""
    out: list[str | Command] = []
    at = 0
    for match in _TOKEN.finditer(word):
        if match.start() > at:
            out.append(word[at : match.start()])
        out.append(command(match.group(1)))
        at = match.end()
    if at < len(word):
        out.append(word[at:])
    return out


def _words(segment: str) -> list[str]:
    """A line's words, split at the spaces outside tags; an empty line has none."""
    if not segment:
        return []
    words = _SPACES_OUTSIDE_TOKENS.split(segment)
    if not all(words):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A line of the string has a space at an end, or two"
        )
    return words


def _segments(notation: str) -> list[str]:
    """The notation cut at each ``{N}``: the lines it asks for."""
    return notation.split("{N}")


def notation_skeleton(notation: str) -> tuple[str, ...]:
    """A translation's tags in order, in the notation, ``{N}`` left out: what
    ``engines.sf2.command_skeleton`` gives for the symbols the encoder writes."""
    return tuple(
        part
        for match in _TOKEN.finditer(notation)
        for part in command_skeleton(command(match.group(1)).data)
    )


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a string paints."""
    used = {" "}
    for segment in _segments(notation):
        for word in _words(segment):
            for piece in _pieces(word):
                if isinstance(piece, str):
                    used |= set(paint_text(piece))
    return used


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line: its symbols and where its pen ends."""

    data: bytes
    end: int


@dataclass(frozen=True, slots=True)
class EncodedString:
    """A translated string's symbols (its end included) and, with a font, its lines."""

    data: bytes
    lines: tuple[LaidLine, ...] | None


class Sf2ArabicEncoder:
    """Convert a logical Arabic string, in the English's notation, into the hook's symbols."""

    def __init__(self, glyph_map: GlyphCodes, font: Sf2Font | None = None) -> None:
        self.glyph_map = glyph_map
        self.font = font

    def codes(self, painted: str) -> bytes:
        output = bytearray()
        for character in painted:
            code = self.glyph_map.code(character)
            if code is None:
                raise no_glyph(character, PROFILE)
            output.append(code)
        return bytes(output)

    def word(self, word: str) -> tuple[bytes, list[int]]:
        """A word's symbols, in the order they are painted from the right, and the width
        of each glyph or of what the game writes (0 for a tag that draws nothing)."""
        data = bytearray()
        widths: list[int] = []
        for piece in _pieces(word):
            if isinstance(piece, Command):
                data += piece.data
                if piece.width:
                    widths.append(piece.width)
            else:
                codes = self.codes(paint_text(piece))
                data += codes
                if self.font is not None:
                    widths += [self.font.width(code) for code in codes]
        return bytes(data), widths

    def encode(self, notation: str) -> EncodedString:
        """The string's symbols: its lines, ``{N}`` between them, then its end."""
        data = bytearray()
        laid: list[LaidLine] = []
        for number, segment in enumerate(_segments(notation)):
            if number:
                data.append(NEW_LINE)
            lines = self.segment(segment)
            for index, line in enumerate(lines):
                if index:
                    data.append(NEW_LINE)
                data += line.data
            laid += lines
        data.append(END)
        return EncodedString(bytes(data), tuple(laid) if self.font is not None else None)

    def segment(self, segment: str) -> list[LaidLine]:
        """A segment's lines, a word at a time: a line breaks before the word whose
        glyphs would start past ``LAST_START`` or end past ``LINE_END``."""
        space = self.codes(" ")
        space_width = self.font.width(space[0]) if self.font is not None else SPACE_WIDTH
        lines: list[LaidLine] = []
        line = bytearray()
        pen = LINE_START
        for word in _words(segment):
            codes, widths = self.word(word)
            gap = [space_width] if line else []
            if line and self.font is not None and not _fits(pen, gap + widths):
                lines.append(LaidLine(bytes(line), pen))
                line, pen, gap = bytearray(), LINE_START, []
            if gap:
                line += space
            line += codes
            if self.font is not None:
                if not _fits(pen, gap + widths):
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A word needs {sum(widths)}px; a line holds {LINE_END - LINE_START}px",
                    )
                pen += sum(gap + widths)
        lines.append(LaidLine(bytes(line), pen))
        return lines


def _fits(pen: int, widths: Sequence[int]) -> bool:
    """Whether glyphs of these widths, from the pen, each start by ``LAST_START`` and
    end by ``LINE_END``."""
    for width in widths:
        if pen > LAST_START or pen + width > LINE_END:
            return False
        pen += width
    return True


# ---------------------------------------------------------------------------
# Previews

PREVIEW_INK = (248, 248, 248)
PREVIEW_BACKGROUND = (28, 36, 120)
PREVIEW_MARGIN = 6


def font_preview(font: Sf2Font) -> Image.Image:
    """Atlas of the glyphs in their 16x15 cells, the width's end dark red."""
    entries = [font.glyphs[code] for code in sorted(font.glyphs)]

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = entries[number]
        if x >= glyph.width:
            return (70, 20, 20)
        return PREVIEW_INK if glyph.rows[y][x] else PREVIEW_BACKGROUND

    return glyph_atlas(len(entries), WIDEST, ROWS, colour)


def _draw(image: Image.Image, glyph: Sf2Glyph, x: int, top: int) -> None:
    for y, row in enumerate(glyph.rows):
        for column, ink in enumerate(row[: glyph.width]):
            if ink and 0 <= x + column < image.width:
                image.putpixel((x + column, top + y), PREVIEW_INK)


def message_preview(encoded: EncodedString, font: Sf2Font) -> Image.Image:
    """The string's lines as the window shows them: 216 pixels, 16 rows apart, the
    glyphs at the mirror of the pen; what the game writes is a grey block."""
    if encoded.lines is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the font")
    width = RIGHT + 2 * PREVIEW_MARGIN
    height = LINE_HEIGHT * len(encoded.lines) + 2 * PREVIEW_MARGIN
    image = Image.new("RGB", (width, height), PREVIEW_BACKGROUND)
    blocks = {}
    for tag, symbol in {**TAGS, "NAME;": TAGS_WITH_ARGUMENT["NAME"]}.items():
        blocks[symbol] = ISLAND_WIDTHS.get(tag.rstrip(";"), 0)
    for row, line in enumerate(encoded.lines):
        pen = LINE_START
        top = PREVIEW_MARGIN + row * LINE_HEIGHT
        at = 0
        while at < len(line.data):
            symbol = line.data[at]
            at += 1
            if symbol >= FIRST_COMMAND:
                if symbol in TAGS_WITH_ARGUMENT.values():
                    at += 1
                block = blocks.get(symbol, 0)
                for dx in range(block):
                    image.putpixel(
                        (PREVIEW_MARGIN + RIGHT - pen - block + dx, top + 8), (150, 150, 150)
                    )
                pen += block
                continue
            glyph = font.glyphs[symbol]
            _draw(image, glyph, PREVIEW_MARGIN + RIGHT - pen - glyph.width, top)
            pen += glyph.width
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
