"""Arabic support for the dialogue of *The Legend of Zelda: A Link to the Past* (Super NES).

The game writes a message out into a buffer, then draws it a character at a
time with a variable-width font of 8x16 pixels, two bits each, into the tiles
of three lines of 168 pixels (``engines.alttp``): each character at the pen of
its line, which then moves on by its width. The overlay
(``classic_retro.rom.alttp_arabic``) parses a translated message from its
Arabic text, where every byte below ``67`` and from ``80`` to ``E6``
(``ARABIC_CODES``) is a glyph of an Arabic font of its own, 16x16 pixels, and
the commands keep their meaning. The hook draws each glyph at the mirror of
the pen, ``LINE_WIDTH - pen - width``, while the pen moves on as the game's
does, so a line starts at the right; the player's name and the numbers the
game writes are drawn as a block, left to right, in the English font, at the
mirror of their place. The lines are shown a tile further right than the
English's, so they end against the window's right side as the English's start
against its left.

The Arabic glyphs are drawn in the game's style: white strokes (``INK``) with a
dark outline all round (``OUTLINE``), but on a side where the letter joins the
next, whose stroke runs on to the glyph's edge; from the reference font at the
largest size where every form of the repertoire and every digit fits the cell
with its outline, on the row above the English letters' last (``BASELINE``).
The merged dots of small letters are drawn apart (``separated_dots``); the
punctuation the reference font lacks or draws too small is drawn by hand
(``PUNCTUATION``).

A translation's notation is a page for each line of text: the game shows three
lines, and a page ends with a wait for the button (``{Waitkey}``) before the next
scrolls in. The encoder lays each page out itself, a word at a time, in lines
of ``LINE_WIDTH`` pixels; ``{line}`` ends a line where it stands. It writes the
engine's line changes as the English does: the second line ``{2}``, the third
``{3}``, each next one ``{Scroll}``. The commands that tell nothing about the
layout pass through as tokens (``{Window 02}``, ``{Speed 03}``, ``{Wait 01}``...);
``{Name}`` writes the player's name, reckoned as wide as the widest name the
game lets the player give (``NAME_WIDTH``).

A translation keeps the original's commands: its skeleton
(``notation_skeleton``: every token but ``{line}``, in order, as the notation
writes it) must equal the original's (``engines.alttp.command_skeleton``),
which leaves out the same layout the encoder writes itself: the lines to
write on, the scroll and the wait for the button between pages
(``engines.alttp.LAYOUT_COMMANDS``). ``validate_command_skeleton`` refuses a
translation that drops, adds or moves any other command.
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
from classic_retro.engines.alttp import (
    COMMAND_CODES,
    COMMANDS,
    END,
    FIRST_COMMAND,
    LINE_2,
    LINE_3,
    NAME,
    SCROLL,
    SPACE,
    WAIT_KEY,
    command_skeleton,
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
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "A Link to the Past Arabic"
ENGINE = "A Link to the Past"
# A byte of an Arabic message below the commands, or from $80 to $E6, is a glyph
# of the Arabic font; the space keeps the game's code, which types no sound.
ARABIC_CODES = tuple(code for code in range(FIRST_COMMAND) if code != SPACE) + tuple(
    range(0x80, 0xE7)
)
SPACE_CODE = SPACE
GLYPH_BYTES = 64
CELL = 16
# The row under the Arabic letters: two rows above the English letters' last,
# so the tails below them fit the cell with their outline.
BASELINE = 11
TOP_INK_ROW = 1
BOTTOM_INK_ROW = CELL - 2
SIZES = range(14, 7, -1)
# Pixel values: the outline, the stroke.
CLEAR = 0
OUTLINE = 1
INK = 2
INK_LEVEL = 140
MARK_LEVEL = 60
DIGITS = "0123456789"
SPACE_WIDTH = 4
# Punctuation drawn by hand: rows of ink, from how many rows above the baseline.
PUNCTUATION: dict[str, tuple[tuple[str, ...], int]] = {
    ".": (("##", "##"), 2),
    ",": ((".#", "##", "#."), 2),
    ":": (("##", "##", "..", "..", "##", "##"), 6),
    "!": (("##",) * 6 + ("..", "##", "##"), 9),
    "-": (("####",), 4),
    "…": (("#.#.#",), 1),
    "،": ((".#", "##", "##"), 3),
    "؛": ((".#", "##", "##", "..", "##", "##"), 6),
    "؟": ((".###.", "#...#", "#....", ".##..", "..#..", ".....", "..#.."), 7),
}
# Hamza above alef reaches the outline's row: the font's alef, cut below a
# hamza drawn on rows 1-2. The dots of final and isolated yeh reach the lowest
# row: those forms are raised a row, the final keeping its joining pixel.
_HAMZA = ("..", "##", "#.")
MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {"ﺃ": ("ﺍ", _HAMZA), "ﺄ": ("ﺎ", _HAMZA)}
RAISED_FORMS = frozenset("ﻱﻲ")
# The eight neighbours of an ink pixel that its outline covers.
_RING = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
# The game's layout: a line is 21 tiles; the box shows three lines.
LINE_WIDTH = 168
MAX_LINES = 3
# A name the player gives: six letters, the widest of the English font's 7
# pixels each; a number the game writes: a digit.
NAME_WIDTH = 6 * 7
NUMBER_WIDTH = 6
LINE_BREAK = "{line}"
# Commands a translation may write, with their byte or without.
PASSING_COMMANDS = frozenset(("Window", "Speed", "Wait", "Sound", "Color", "Number"))
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SPACES_OUTSIDE_TOKENS = re.compile(r" (?![^{}]*\})")


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    order = (*PUNCTUATION, *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def alttp_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
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
        what="A Link to the Past Arabic glyphs",
    )
    if " " not in used:
        return codes
    return GlyphCodes(
        (" ", *codes.characters), {" ": (SPACE_CODE,), **dict(codes.sequences.items())}
    )


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class AlttpGlyph:
    """A glyph: its width (the pen's advance) and its 16 rows of 16 two-bit values."""

    width: int
    rows: tuple[tuple[int, ...], ...]

    def data(self) -> bytes:
        """The hook's 64 bytes: a row is plane 0, then plane 1, 16 bits each, the leftmost
        pixel in bit 15, the low byte first."""
        output = bytearray()
        for row in self.rows:
            for plane in (0, 1):
                bits = 0
                for x, value in enumerate(row):
                    if value >> plane & 1:
                        bits |= 0x8000 >> x
                output += bits.to_bytes(2, "little")
        return bytes(output)


@dataclass(frozen=True, slots=True)
class AlttpFont:
    """The Arabic glyphs by code, and the size they were drawn at."""

    glyphs: Mapping[int, AlttpGlyph]
    font_size: int

    def width(self, code: int) -> int:
        try:
            return self.glyphs[code].width
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The Arabic font has no glyph {code:#04x}"
            ) from None


def outlined_glyph(ink: Collection[Pixel], *, joins_left: bool, joins_right: bool) -> AlttpGlyph:
    """Ink with its outline, a column of outline on each side that does not join.

    The ink's first column is 0; on a joining side the ink reaches the glyph's
    edge, where the neighbour's goes on. Raises ``FormDoesNotFit`` when the glyph
    leaves the 16x16 cell.
    """
    left = 0 if joins_left else 1
    placed = {(x + left, y) for x, y in ink}
    width = max(x for x, _ in placed) + 1 + (0 if joins_right else 1)
    if width > CELL or any(not TOP_INK_ROW <= y <= BOTTOM_INK_ROW for _, y in placed):
        raise FormDoesNotFit
    outline = {(x, y) for x, y in drop_shadow(placed, _RING, width, CELL) if x >= 0 and y >= 0}
    return AlttpGlyph(
        width,
        tuple(
            tuple(
                INK if (x, y) in placed else OUTLINE if (x, y) in outline else CLEAR
                for x in range(CELL)
            )
            for y in range(CELL)
        ),
    )


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
        form = raised_form(character, form, height=BOTTOM_INK_ROW + 1, baseline=BASELINE)
    return form


def _outlined_forms(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, AlttpGlyph] | None:
    """Every character at this size, outlined, or None when one leaves the cell."""
    try:
        return {
            character: outlined_glyph(
                _form(font, character).ink,
                joins_left=joins_left_neighbour(character),
                joins_right=joins_right_neighbour(character),
            )
            for character in characters
        }
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(character: str) -> AlttpGlyph:
    rows, above = PUNCTUATION[character]
    ink = pattern_pixels(rows, top=BASELINE - above)
    return outlined_glyph(ink, joins_left=False, joins_right=False)


def blank_glyph(width: int) -> AlttpGlyph:
    return AlttpGlyph(width, tuple((CLEAR,) * CELL for _ in range(CELL)))


def build_alttp_font(
    font_path: Path,
    glyph_map: GlyphCodes,
    used: Collection[str],
    *,
    sizing: Iterable[str] | None = None,
) -> AlttpFont:
    """The glyphs of the ``used`` characters.

    The size is the largest where every character of ``sizing`` fits: the whole
    repertoire and the digits, whatever the text uses, so a new message never
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
        lambda font: _outlined_forms(font, drawn),
        "Selected font cannot fit A Link to the Past's 16x16 glyphs",
    )
    for character in PUNCTUATION:
        rendered[character] = hand_drawn_glyph(character)
    rendered[" "] = blank_glyph(SPACE_WIDTH)
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        if code is None:
            raise no_glyph(character, PROFILE)
        glyphs[code] = rendered[character]
    return AlttpFont(glyphs, size)


# ---------------------------------------------------------------------------
# Encoding translated messages


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
    """A command of the text: its bytes, and how wide the game draws what it writes."""

    data: bytes
    width: int


def command(token: str) -> Command:
    """A ``{token}`` of the notation: ``{Name}``, or a passing command with its byte."""
    name, _, argument = token.partition(" ")
    if name == "Name" and not argument:
        return Command(bytes((NAME,)), NAME_WIDTH)
    if name not in PASSING_COMMANDS:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")
    code = COMMAND_CODES[name]
    if COMMANDS[code][1] != 2 or not re.fullmatch(r"[0-9A-F]{2}", argument):
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"{{{token}}}: {name} takes a byte, as {{{name} 01}}",
        )
    return Command(bytes((code, int(argument, 16))), NUMBER_WIDTH if name == "Number" else 0)


def _pieces(word: str) -> list[str | Command]:
    """A word's text runs and commands, in reading order."""
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
    """A line's words, split at the spaces outside tokens; an empty line has none."""
    if not segment:
        return []
    words = _SPACES_OUTSIDE_TOKENS.split(segment)
    if not all(words):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A line of the message has a space at an end, or two"
        )
    return words


def notation_skeleton(notation: str) -> tuple[str, ...]:
    """A translation's commands in order, in the notation, ``{line}`` left out: what
    ``engines.alttp.command_skeleton`` gives for the bytes the encoder writes."""
    return tuple(
        part
        for match in _TOKEN.finditer(notation)
        if f"{{{match.group(1)}}}" != LINE_BREAK
        for part in command_skeleton(command(match.group(1)).data)
    )


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a message paints."""
    used = {" "}
    for page in notation.split("\n"):
        for segment in page.split(LINE_BREAK):
            for word in _words(segment):
                for piece in _pieces(word):
                    if isinstance(piece, str):
                        used |= set(paint_text(piece))
    return used


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line: its bytes and how far its pen goes."""

    data: bytes
    width: int


@dataclass(frozen=True, slots=True)
class EncodedMessage:
    """A translated message's bytes (its end included) and, with a font, its pages."""

    data: bytes
    pages: tuple[tuple[LaidLine, ...], ...] | None


class AlttpArabicEncoder:
    """Convert a logical Arabic message (a line a page) into the hook's bytes."""

    def __init__(self, glyph_map: GlyphCodes, font: AlttpFont | None = None) -> None:
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

    def word(self, word: str) -> tuple[bytes, int]:
        """A word's bytes, in the order they are painted from the right, and its width."""
        data = bytearray()
        width = 0
        for piece in _pieces(word):
            if isinstance(piece, Command):
                data += piece.data
                width += piece.width
            else:
                codes = self.codes(paint_text(piece))
                data += codes
                if self.font is not None:
                    width += sum(self.font.width(code) for code in codes)
        return bytes(data), width

    def encode(self, notation: str) -> EncodedMessage:
        """The message's bytes: each page's lines, the line changes before them as the
        game's English writes them, a wait for the button between pages."""
        data = bytearray()
        pages: list[tuple[LaidLine, ...]] = []
        number = 0
        for index, page in enumerate(notation.split("\n")):
            lines = self.page(page)
            if self.font is not None and len(lines) > MAX_LINES:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Page {index + 1} needs {len(lines)} lines; the box shows {MAX_LINES}",
                )
            if index:
                data.append(WAIT_KEY)
            for line in lines:
                if number == 1:
                    data.append(LINE_2)
                elif number == 2:
                    data.append(LINE_3)
                elif number > 2:
                    data.append(SCROLL)
                data += line.data
                number += 1
            pages.append(tuple(lines))
        data.append(END)
        return EncodedMessage(bytes(data), tuple(pages) if self.font is not None else None)

    def page(self, page: str) -> list[LaidLine]:
        """A page's lines, a word at a time: a line breaks where the next word would pass
        ``LINE_WIDTH``, and at each ``{line}``."""
        space = self.codes(" ")
        space_width = self.font.width(space[0]) if self.font is not None else SPACE_WIDTH
        lines: list[LaidLine] = []
        for segment in page.split(LINE_BREAK):
            line = bytearray()
            pen = 0
            for word in _words(segment):
                codes, width = self.word(word)
                gap = space_width if line else 0
                if line and self.font is not None and pen + gap + width > LINE_WIDTH:
                    lines.append(LaidLine(bytes(line), pen))
                    line, pen, gap = bytearray(), 0, 0
                if gap:
                    line += space
                line += codes
                pen += gap + width
                if self.font is not None and pen > LINE_WIDTH:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A word needs {width}px; a line holds {LINE_WIDTH}px",
                    )
            lines.append(LaidLine(bytes(line), pen))
        return lines


# ---------------------------------------------------------------------------
# Previews

PREVIEW_COLOURS = {INK: (248, 248, 248), OUTLINE: (24, 24, 40)}
PREVIEW_BACKGROUND = (40, 56, 120)
PREVIEW_MARGIN = 8


def font_preview(font: AlttpFont) -> Image.Image:
    """Atlas of the glyphs in their 16x16 cells, the width's end dark red."""
    entries = [font.glyphs[code] for code in sorted(font.glyphs)]

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = entries[number]
        if x >= glyph.width:
            return (70, 20, 20)
        return PREVIEW_COLOURS.get(glyph.rows[y][x], PREVIEW_BACKGROUND)

    return glyph_atlas(len(entries), CELL, CELL, colour)


def _draw(image: Image.Image, glyph: AlttpGlyph, x: int, top: int) -> None:
    for y, row in enumerate(glyph.rows):
        for column, value in enumerate(row[: glyph.width]):
            colour = PREVIEW_COLOURS.get(value)
            if colour is not None and 0 <= x + column < image.width:
                image.putpixel((x + column, top + y), colour)


def message_preview(encoded: EncodedMessage, font: AlttpFont) -> Image.Image:
    """Each page as the box shows it: lines of 168 pixels 16 rows apart, the glyphs at the
    mirror of the pen; a name or number is a grey block as wide as the layout reckons it."""
    if encoded.pages is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the font")
    height = MAX_LINES * CELL + 2 * PREVIEW_MARGIN
    width = LINE_WIDTH + 2 * PREVIEW_MARGIN
    image = Image.new("RGB", (width, height * len(encoded.pages)), (12, 12, 12))
    blocks = {NAME: NAME_WIDTH, COMMAND_CODES["Number"]: NUMBER_WIDTH}
    for number, page in enumerate(encoded.pages):
        top = number * height
        for x in range(2, width - 2):
            for y in range(top + 2, top + height - 2):
                image.putpixel((x, y), PREVIEW_BACKGROUND)
        for row, line in enumerate(page):
            pen = 0
            y = top + PREVIEW_MARGIN + row * CELL
            at = 0
            while at < len(line.data):
                code = line.data[at]
                if code in blocks:
                    for dx in range(blocks[code]):
                        image.putpixel(
                            (PREVIEW_MARGIN + LINE_WIDTH - pen - blocks[code] + dx, y + 8),
                            (150, 150, 150),
                        )
                    pen += blocks[code]
                    at += COMMANDS[code][1]
                    continue
                if code in COMMANDS:
                    at += COMMANDS[code][1]
                    continue
                glyph = font.glyphs[code]
                _draw(image, glyph, PREVIEW_MARGIN + LINE_WIDTH - pen - glyph.width, y)
                pen += glyph.width
                at += 1
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
