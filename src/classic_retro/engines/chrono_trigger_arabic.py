"""Arabic support for the dialogue of *Chrono Trigger* (Super NES).

The game draws a string a character at a time with a variable-width font of
12x12 pixels, two bits each (``engines.chrono_trigger``): each glyph is ORed
into a buffer of tiles at the pen, which then moves on by the glyph's width.
The overlay (``classic_retro.rom.chrono_trigger_arabic``) sends a translated
string's reading to its Arabic text, where every byte from ``21`` is a glyph
of an Arabic font of its own (``ARABIC_CODES``) and the bytes below keep their
meaning (line and box breaks, pauses, names). The hook draws each glyph at the
mirror of the pen, ``MIRROR - pen - width``, while the pen moves on as the
game's does, so a line starts at the box's right side and the game's indent
falls on the right; the names the game writes (and its numbers) are drawn as
a block, left to right, at the mirror of their place.

The Arabic glyphs are drawn in the game's style: white ink (``INK``) with a
dark shadow a pixel right and below (``SHADOW``) and darker in the corner
(``CORNER``), all of it inside the glyph's width, from the reference font at
the largest size where every form of the repertoire and every digit fits the
cell on its baseline (``BASELINE``: the row under the English letters). The
merged dots of small letters are drawn apart (``separated_dots``); the
punctuation the reference font lacks or draws too small is drawn by hand
(``PUNCTUATION``); the space is a blank glyph.

A translation's notation is a line for each box of the message: the encoder
lays each box out itself, a word at a time, in the lines of a box
(``MAX_LINES``) as wide as the game's (from the pen at ``LINE_START`` to
``LAST_PEN``). A message that starts with a speaker's name and a colon has
its other lines and boxes indented, as the game's English does. A ``{name}``
token writes that member's name: its width is reckoned as the widest name
the game lets the player give (``NAME_WIDTH``).

A translation keeps the original's commands: its skeleton
(``notation_skeleton``: every token but ``{line}``, in order, as the notation
writes it) must equal the original's
(``engines.chrono_trigger.command_skeleton``), which leaves out the same
layout the encoder writes itself: the new lines and the new boxes, plain or
indented, waiting for the button or not (``engines.chrono_trigger.LAYOUT_CODES``).
``validate_command_skeleton`` refuses a translation that drops, adds or moves
any other code; ``{Crono}`` stands for both codes that write his name.
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
from classic_retro.engines.chrono_trigger import (
    BOX,
    BOX_INDENTED,
    END,
    LINE,
    LINE_INDENTED,
    NAMES,
    command_skeleton,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_right_neighbour,
)
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
    raised_marks,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Chrono Trigger Arabic"
ENGINE = "Chrono Trigger"
# A byte of an Arabic string from here is a glyph of the Arabic font.
ARABIC_CODES = tuple(range(0x21, 0x100))
GLYPH_BYTES = 48
CELL = 12
# The row under the English capitals, which the Arabic letters sit on.
BASELINE = 8
SIZES = range(13, 7, -1)
WIDEST = 12
# Pixel values: the ink, its shadow right and below, the shadow's corner.
CLEAR = 0
SHADOW = 1
CORNER = 2
INK = 3
INK_LEVEL = 128
MARK_LEVEL = 60
DIGITS = "0123456789"
SPACE_WIDTH = 4
# Punctuation drawn by hand: rows of ink from the cell's top row.
PUNCTUATION: dict[str, tuple[tuple[str, ...], int]] = {
    ".": (("##", "##"), 6),
    ",": (("##", "##", ".#"), 6),
    ":": (("##", "##", "..", "..", "##", "##"), 2),
    "!": (("##",) * 5 + ("..", "##", "##"), 0),
    "-": (("####",), 4),
    "…": (("#.#.#",), 7),
    "،": ((".#", "##", "##"), 5),
    "؛": ((".#", "##", "##", "..", "##", "##"), 2),
    "؟": ((".###.", "#...#", "#....", ".##..", "..#..", ".....", "..#.."), 0),
}
# Hamza above alef reaches above the cell: the font's alef, cut below a hamza
# drawn on the top rows. The tail and dots of final and isolated yeh reach
# below it: those forms are raised a row, the final keeping its joining pixel.
_HAMZA = ("##", "#.")
MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {"ﺃ": ("ﺍ", _HAMZA), "ﺄ": ("ﺎ", _HAMZA)}
RAISED_FORMS = frozenset("ﻱﻲ")
# The game's layout: where a line starts (the pen), where an indented one
# does, and the last pen a line may reach: the box's text ends on pen 240, as
# the English's widest lines do. The mirror of the pen is 256 - pen.
MIRROR = 256
LINE_START = 8
LINE_INDENT = 20
LAST_PEN = 240
MAX_LINES = 4
# A name the player gives: five letters, the widest of the name screen's 11
# pixels each.
NAME_WIDTH = 5 * 11
NAME_CODES = {name: code for code, name in NAMES.items()}
LINE_BREAK = "{line}"
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SPEAKER = re.compile(r"^[^:{}]{1,24}: ")
_AROUND = ((1, 0), (0, 1))


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    order = (" ", *PUNCTUATION, *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def chrono_trigger_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from ``ARABIC_CODES`` for the characters a translation uses, in the font's order."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="Chrono Trigger Arabic glyphs",
    )


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class CtGlyph:
    """A glyph: its width (the pen's advance) and its 12 rows of 12 two-bit values."""

    width: int
    rows: tuple[tuple[int, ...], ...]

    def data(self) -> bytes:
        """The hook's 48 bytes: 12 rows of the left 8 pixels (two planes each), then the
        right 4 pixels the same way, in the high nibble."""
        left = bytearray(24)
        right = bytearray(24)
        for y, row in enumerate(self.rows):
            for x, value in enumerate(row):
                for plane in (0, 1):
                    if value >> plane & 1:
                        if x < 8:
                            left[2 * y + plane] |= 0x80 >> x
                        else:
                            right[2 * y + plane] |= 0x80 >> (x - 8)
        return bytes(left + right)


@dataclass(frozen=True, slots=True)
class CtFont:
    """The Arabic glyphs by code, and the size they were drawn at."""

    glyphs: Mapping[int, CtGlyph]
    font_size: int

    def width(self, code: int) -> int:
        try:
            return self.glyphs[code].width
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The Arabic font has no glyph {code:#04x}"
            ) from None


def shaded_glyph(ink: Collection[Pixel], width: int) -> CtGlyph:
    """Ink in the game's style: a shadow right and below, its corner darker, all inside
    the width."""
    if width > WIDEST or any(not 0 <= x < width or not 0 <= y < CELL - 1 for x, y in ink):
        raise FormDoesNotFit
    pixels = dict.fromkeys(ink, INK)
    for x, y in ink:
        for dx, dy in _AROUND:
            if x + dx < width and (x + dx, y + dy) not in pixels:
                pixels[x + dx, y + dy] = SHADOW
    for x, y in ink:
        corner = (x + 1, y + 1)
        if x + 1 < width and corner not in pixels:
            pixels[corner] = CORNER
    return CtGlyph(
        width,
        tuple(tuple(pixels.get((x, y), CLEAR) for x in range(WIDEST)) for y in range(CELL)),
    )


def form_glyph(character: str, ink: Collection[Pixel], advance: int) -> CtGlyph:
    """A drawn form: as wide as its advance and its shadow, but for a form that joins the
    glyph on its right, whose stroke runs on to its edge."""
    right = max(x for x, _ in ink)
    width = right + 1 if joins_right_neighbour(character) else max(advance, right + 2)
    return shaded_glyph(ink, width)


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)
    return raised_marks(separated_dots(character, form), CELL - 2)


def _drawn_glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, CtGlyph] | None:
    """Every character at this size, or None when one leaves the cell."""
    try:
        glyphs = {}
        for character in characters:
            if character in MARKED_ALEF:
                alef, mark = MARKED_ALEF[character]
                form = alef_with_mark(character, _drawn(font, alef), mark)
            else:
                form = _drawn(font, character)
            if character in RAISED_FORMS:
                form = raised_form(character, form, height=CELL - 1, baseline=BASELINE)
            glyphs[character] = form_glyph(character, form.ink, form.advance)
        return glyphs
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(character: str) -> CtGlyph:
    rows, top = PUNCTUATION[character]
    return shaded_glyph(pattern_pixels(rows, top=top), len(rows[0]) + 2)


def build_chrono_trigger_font(
    font_path: Path,
    glyph_map: GlyphCodes,
    used: Collection[str],
    *,
    sizing: Iterable[str] | None = None,
) -> CtFont:
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
        lambda font: _drawn_glyphs(font, drawn),
        "Selected font cannot fit Chrono Trigger's 12x12 glyphs",
    )
    for character in PUNCTUATION:
        rendered[character] = hand_drawn_glyph(character)
    rendered[" "] = CtGlyph(SPACE_WIDTH, tuple((CLEAR,) * WIDEST for _ in range(CELL)))
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        if code is None:
            raise no_glyph(character, PROFILE)
        glyphs[code] = rendered[character]
    return CtFont(glyphs, size)


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


def name_code(token: str) -> int:
    """The code of a ``{name}`` token of the notation."""
    if token not in NAME_CODES:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")
    return NAME_CODES[token]


def _pieces(word: str) -> list[str | int]:
    """A word's text runs and names, in reading order."""
    out: list[str | int] = []
    at = 0
    for match in _TOKEN.finditer(word):
        if match.start() > at:
            out.append(word[at : match.start()])
        out.append(name_code(match.group(1)))
        at = match.end()
    if at < len(word):
        out.append(word[at:])
    return out


def _words(segment: str) -> list[str]:
    words = segment.strip().split(" ")
    if not all(words):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A line of the message is empty or has two spaces"
        )
    return words


def notation_skeleton(notation: str) -> tuple[str, ...]:
    """A translation's names in order, in the notation, ``{line}`` left out: what
    ``engines.chrono_trigger.command_skeleton`` gives for the bytes the encoder writes."""
    return tuple(
        part
        for match in _TOKEN.finditer(notation)
        if f"{{{match.group(1)}}}" != LINE_BREAK
        for part in command_skeleton(bytes((name_code(match.group(1)),)))
    )


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a message paints."""
    used = {" "}
    for box in notation.split("\n"):
        for segment in box.split(LINE_BREAK):
            for word in _words(segment):
                for piece in _pieces(word):
                    if isinstance(piece, str):
                        used |= set(paint_text(piece))
    return used


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line: its bytes, where its pen starts and where it ends."""

    data: bytes
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class EncodedMessage:
    """A translated message's bytes (its zero included) and, with a font, its boxes."""

    data: bytes
    boxes: tuple[tuple[LaidLine, ...], ...] | None


class ChronoTriggerArabicEncoder:
    """Convert a logical Arabic message (a line a box) into the hook's bytes."""

    def __init__(self, glyph_map: GlyphCodes, font: CtFont | None = None) -> None:
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
            if isinstance(piece, int):
                data.append(piece)
                width += NAME_WIDTH
            else:
                codes = self.codes(paint_text(piece))
                data += codes
                if self.font is not None:
                    width += sum(self.font.width(code) for code in codes)
        return bytes(data), width

    def encode(self, notation: str) -> EncodedMessage:
        boxes = notation.split("\n")
        speaker = bool(_SPEAKER.match(boxes[0]))
        data = bytearray()
        laid: list[tuple[LaidLine, ...]] = []
        for number, box in enumerate(boxes):
            if number:
                data.append(BOX_INDENTED if speaker else BOX)
            lines = self.box(box, first=not number, speaker=speaker)
            for index, line in enumerate(lines):
                if index:
                    data.append(LINE_INDENTED if speaker else LINE)
                data += line.data
            if self.font is not None and len(lines) > MAX_LINES:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Box {number + 1} needs {len(lines)} lines; the box shows {MAX_LINES}",
                )
            laid.append(tuple(lines))
        data.append(END)
        return EncodedMessage(bytes(data), tuple(laid) if self.font is not None else None)

    def box(self, box: str, *, first: bool, speaker: bool) -> list[LaidLine]:
        """A box's lines, a word at a time: a line breaks where the next word would pass
        ``LAST_PEN``, and at each ``{line}``. Under a speaker's name every line but the
        message's first is indented."""
        space = self.codes(" ")
        space_width = self.font.width(space[0]) if self.font is not None else SPACE_WIDTH
        indent = LINE_INDENT if speaker else LINE_START
        lines: list[LaidLine] = []
        start = LINE_START if first else indent
        for number, segment in enumerate(box.split(LINE_BREAK)):
            if number:
                start = indent
            line = bytearray()
            pen = start
            for word in _words(segment):
                codes, width = self.word(word)
                gap = space_width if line else 0
                if line and self.font is not None and pen + gap + width > LAST_PEN:
                    lines.append(LaidLine(bytes(line), start, pen))
                    start = indent
                    line, pen, gap = bytearray(), start, 0
                if gap:
                    line += space
                line += codes
                pen += gap + width
                if self.font is not None and pen > LAST_PEN:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A word needs {width}px; a line holds {LAST_PEN - start}px",
                    )
            lines.append(LaidLine(bytes(line), start, pen))
        return lines


# ---------------------------------------------------------------------------
# Previews

PREVIEW_COLOURS = {INK: (248, 248, 248), SHADOW: (40, 40, 56), CORNER: (24, 24, 32)}
PREVIEW_BACKGROUND = (86, 94, 118)
LINE_HEIGHT = 16
PREVIEW_MARGIN = 4


def font_preview(font: CtFont) -> Image.Image:
    """Atlas of the glyphs in their 12x12 cells, the width's end dark red."""
    entries = [font.glyphs[code] for code in sorted(font.glyphs)]

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = entries[number]
        if x >= glyph.width:
            return (70, 20, 20)
        return PREVIEW_COLOURS.get(glyph.rows[y][x], PREVIEW_BACKGROUND)

    return glyph_atlas(len(entries), WIDEST, CELL, colour)


def _draw(image: Image.Image, glyph: CtGlyph, x: int, top: int) -> None:
    for y, row in enumerate(glyph.rows):
        for column, value in enumerate(row[: glyph.width]):
            colour = PREVIEW_COLOURS.get(value)
            if colour is not None and 0 <= x + column < image.width:
                image.putpixel((x + column, top + y), colour)


def message_preview(encoded: EncodedMessage, font: CtFont) -> Image.Image:
    """Each box as the game shows it: 256 pixels, a line every 16 rows, the glyphs at
    the mirror of the pen; a name is a grey block as wide as ``NAME_WIDTH``."""
    if encoded.boxes is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the font")
    height = MAX_LINES * LINE_HEIGHT + 2 * PREVIEW_MARGIN
    image = Image.new("RGB", (MIRROR, height * len(encoded.boxes)), (12, 12, 12))
    for number, box in enumerate(encoded.boxes):
        top = number * height
        for x in range(4, MIRROR - 4):
            for y in range(top + 2, top + height - 2):
                image.putpixel((x, y), PREVIEW_BACKGROUND)
        for row, line in enumerate(box):
            pen = line.start
            y = top + PREVIEW_MARGIN + row * LINE_HEIGHT
            for code in line.data:
                if code in NAMES:
                    for dx in range(NAME_WIDTH):
                        image.putpixel((MIRROR - pen - NAME_WIDTH + dx, y + 6), (150, 150, 150))
                    pen += NAME_WIDTH
                    continue
                glyph = font.glyphs[code]
                _draw(image, glyph, MIRROR - pen - glyph.width, y)
                pen += glyph.width
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
