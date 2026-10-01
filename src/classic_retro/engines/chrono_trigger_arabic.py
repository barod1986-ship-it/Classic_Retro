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
``LAST_PEN``). ``{line}`` ends a line where it stands; ``{box auto}`` starts
a box that does not wait for the button, as the game's timed scenes do after
a pause; ``{choice}`` at a line's start leaves the choice cursor its room at
the line's right (``CHOICE_PEN``), on the lines the game's event makes the
choices (the build checks them); ``{pause 00}``, which closes the box,
starts the message over: the text after it is laid out as a message of its
own, as the game shows it. A message that starts with a speaker's name and a
colon has its other lines and boxes indented, as the game's English does. A
``{name}`` token writes that member's name: its width is reckoned as the
widest name the game lets the player give (``NAME_WIDTH``); ``{member 1}``,
``{Epoch}`` and ``{code 11}`` write a name the same way, ``{item}`` and
``{code 12 xx}`` an item's or a technique's name (``ITEM_WIDTH``),
``{code 0D}``, ``{code 0E}`` and ``{code 0F}`` a number of three, five or
eight digits (``DIGIT_WIDTH``), and ``{pause xx}`` passes to the game
(``command_piece``).

A translation keeps the original's commands: its skeleton
(``notation_skeleton``: every command it writes, in order, as the engine's
skeleton reads them) must equal the original's
(``engines.chrono_trigger.command_skeleton``), which leaves out the same
layout the encoder writes itself: the new lines and the new boxes after the
button, plain or indented (``engines.chrono_trigger.LAYOUT_CODES``), and the
word "Nadia", which the translation writes in Arabic.
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
from classic_retro.arabic.paint import (
    MIRRORED_BRACKETS,
    reject_combining_marks,
    reject_mirrored,
    rtl_paint_order,
)
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.chrono_trigger import (
    BOX,
    BOX_AUTO,
    BOX_AUTO_INDENTED,
    BOX_INDENTED,
    END,
    LINE,
    LINE_INDENTED,
    NAMES,
    PAUSE,
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
    # The quotes and the brackets: a right-to-left run shows each mirrored, and
    # the painter does not mirror, so each is drawn as its mirror image.
    "«": (("#.#..", ".#.#.", "..#.#", ".#.#.", "#.#.."), 3),
    "»": (("..#.#", ".#.#.", "#.#..", ".#.#.", "..#.#"), 3),
    "(": (("#..", ".#.", "..#", "..#", "..#", "..#", "..#", "..#", ".#.", "#.."), 0),
    ")": (("..#", ".#.", "#..", "#..", "#..", "#..", "#..", "#..", ".#.", "..#"), 0),
    # The note the game's font has, for a song.
    "♪": (
        ("...#..", "...##.", "...#.#", "...#..", "...#..", "...#..", ".###..", "####..", ".##..."),
        0,
    ),
}
MIRRORED_SIGNS = frozenset("()«»")
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
# A choice's line: the cursor's two tiles and a gap, at the line's right.
CHOICE_PEN = 28
LAST_PEN = 240
MAX_LINES = 4
# A name the player gives: five letters, the widest of the name screen's 11
# pixels each; an item's or a technique's name, the widest of the game's; a
# digit of the game's font, the widest.
NAME_WIDTH = 5 * 11
ITEM_WIDTH = 80
DIGIT_WIDTH = 8
NAME_CODES = {name: code for code, name in NAMES.items()}
MEMBER_CODES = {"member 1": 0x1B, "member 2": 0x1C, "member 3": 0x1D, "Epoch": 0x20, "item": 0x1F}
# The codes a translation writes with ``{code xx}``, and the width the layout
# reckons for what the game draws there; ``{code 12 xx}`` takes its byte.
CODE_WIDTHS = {
    0x0D: 3 * DIGIT_WIDTH,
    0x0E: 5 * DIGIT_WIDTH,
    0x0F: 8 * DIGIT_WIDTH,
    0x10: 0,
    0x11: NAME_WIDTH,
    0x12: ITEM_WIDTH,
}
LINE_BREAK = "{line}"
BOX_AUTO_TOKEN = "{box auto}"
CHOICE_TOKEN = "{choice}"
MESSAGE_END_TOKEN = "{pause 00}"
_TOKEN = re.compile(r"\{([^{}]*)\}")
_PAUSE_TOKEN = re.compile(r"^pause ([0-9A-F]{2})$")
_CODE_TOKEN = re.compile(r"^code ([0-9A-F]{2})(?: ([0-9A-F]{2}))?$")
_BOX_SPLIT = re.compile(r"(\n|\{box auto\})")
# A speaker's name and a colon at a message's start: a name the game writes counts.
_SPEAKER = re.compile(r"^(?:\{[^{}]*\}|[^:{}\n]){1,30}: ")
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
    reject_mirrored(stream, PROFILE, MIRRORED_BRACKETS - MIRRORED_SIGNS)
    reject_combining_marks(stream, PROFILE)
    painted = rtl_paint_order(legacy_renderer_pipeline(), stream)
    return "".join(token.text for token in painted.tokens if isinstance(token, TextToken))


@dataclass(frozen=True, slots=True)
class Command:
    """A code a translation writes: its bytes and the width the layout reckons."""

    data: bytes
    width: int


def name_code(token: str) -> int:
    """The code of a ``{name}`` token of the notation."""
    if token not in NAME_CODES:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")
    return NAME_CODES[token]


def command_piece(token: str) -> Command:
    """The command a token of the notation writes, or the error for one it cannot."""
    if token in NAME_CODES:
        return Command(bytes((NAME_CODES[token],)), NAME_WIDTH)
    if token in MEMBER_CODES:
        code = MEMBER_CODES[token]
        return Command(bytes((code,)), ITEM_WIDTH if token == "item" else NAME_WIDTH)
    pause = _PAUSE_TOKEN.match(token)
    if pause:
        return Command(bytes((PAUSE, int(pause.group(1), 16))), 0)
    code_token = _CODE_TOKEN.match(token)
    if code_token:
        code = int(code_token.group(1), 16)
        argument = code_token.group(2)
        if code in CODE_WIDTHS and (argument is None) == (code != 0x12):
            data = bytes((code,)) if argument is None else bytes((code, int(argument, 16)))
            return Command(data, CODE_WIDTHS[code])
    raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")


def _pieces(word: str) -> list[str | Command]:
    """A word's text runs and commands, in reading order."""
    out: list[str | Command] = []
    at = 0
    for match in _TOKEN.finditer(word):
        if match.start() > at:
            out.append(word[at : match.start()])
        out.append(command_piece(match.group(1)))
        at = match.end()
    if at < len(word):
        out.append(word[at:])
    return out


def _words(segment: str) -> list[list[str | Command]]:
    """A line's words, split at the spaces outside its tokens (``{pause 0F}`` holds
    one), each its pieces; an empty line has none, and an empty word (two spaces, a
    space at an end) is refused."""
    if not segment:
        return []
    words: list[list[str | Command]] = [[]]

    def text(run: str) -> None:
        for number, part in enumerate(run.split(" ")):
            if number:
                words.append([])
            if part:
                words[-1].append(part)

    at = 0
    for match in _TOKEN.finditer(segment):
        text(segment[at : match.start()])
        words[-1].append(command_piece(match.group(1)))
        at = match.end()
    text(segment[at:])
    if not all(words):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A line of the message has two spaces, or one at an end"
        )
    return words


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """A line of the notation: whether it is a choice's, and its words' pieces."""

    choice: bool
    words: tuple[tuple[str | Command, ...], ...]


@dataclass(frozen=True, slots=True)
class ParsedBox:
    """A box of the notation: whether it follows without the button, and its lines."""

    auto: bool
    lines: tuple[ParsedLine, ...]


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """A message of the notation, as the game shows one: its boxes, the first of
    which decides whether a speaker's name indents the rest."""

    speaker: bool
    boxes: tuple[ParsedBox, ...]


def _parse_line(text: str) -> ParsedLine:
    choice = text.startswith(CHOICE_TOKEN)
    if choice:
        text = text[len(CHOICE_TOKEN) :]
    if CHOICE_TOKEN in text:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"{CHOICE_TOKEN} goes at the start of a line"
        )
    return ParsedLine(choice, tuple(tuple(word) for word in _words(text)))


def parse_notation(notation: str) -> tuple[ParsedMessage, ...]:
    """The notation's messages (one after each ``{pause 00}``), their boxes and lines."""
    messages = []
    for text in notation.split(MESSAGE_END_TOKEN):
        parts = _BOX_SPLIT.split(text)
        boxes = []
        separator = ""
        for number, part in enumerate(parts):
            if number % 2:
                separator = part
                continue
            lines = tuple(_parse_line(line) for line in part.split(LINE_BREAK))
            boxes.append(ParsedBox(separator == BOX_AUTO_TOKEN, lines))
        messages.append(ParsedMessage(bool(_SPEAKER.match(parts[0])), tuple(boxes)))
    return tuple(messages)


def notation_skeleton(notation: str) -> tuple[str, ...]:
    """A translation's commands in order, in the notation, the layout left out: what
    ``engines.chrono_trigger.command_skeleton`` gives for the bytes the encoder
    writes."""
    stream = bytearray()
    for number, message in enumerate(parse_notation(notation)):
        if number:
            stream += bytes((PAUSE, 0x00))
        for box in message.boxes:
            if box.auto:
                stream.append(BOX_AUTO)
            for line in box.lines:
                for word in line.words:
                    for piece in word:
                        if isinstance(piece, Command):
                            stream += piece.data
    return command_skeleton(bytes(stream))


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a message paints."""
    used = {" "}
    for message in parse_notation(notation):
        for box in message.boxes:
            for line in box.lines:
                for word in line.words:
                    for piece in word:
                        if isinstance(piece, str):
                            used |= set(paint_text(piece))
    return used


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line: its bytes, where its pen starts and where it ends, and whether it is a
    choice's line (``{choice}``)."""

    data: bytes
    start: int
    end: int
    choice: bool = False


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

    def word(self, word: str | Sequence[str | Command]) -> tuple[bytes, int]:
        """A word's bytes, in the order they are painted from the right, and its width."""
        data = bytearray()
        width = 0
        for piece in _pieces(word) if isinstance(word, str) else word:
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
        data = bytearray()
        laid: list[tuple[LaidLine, ...]] = []
        for number, message in enumerate(parse_notation(notation)):
            if number:
                data += bytes((PAUSE, 0x00))
            speaker = message.speaker
            for box_number, box in enumerate(message.boxes):
                if box_number:
                    if box.auto:
                        data.append(BOX_AUTO_INDENTED if speaker else BOX_AUTO)
                    else:
                        data.append(BOX_INDENTED if speaker else BOX)
                lines = self.box(box, first=not box_number, speaker=speaker)
                for index, line in enumerate(lines):
                    if index:
                        data.append(LINE_INDENTED if speaker else LINE)
                    data += line.data
                if self.font is not None and len(lines) > MAX_LINES:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"Box {len(laid) + 1} needs {len(lines)} lines; the box shows {MAX_LINES}",
                    )
                laid.append(tuple(lines))
        data.append(END)
        return EncodedMessage(bytes(data), tuple(laid) if self.font is not None else None)

    def box(self, box: ParsedBox | str, *, first: bool, speaker: bool) -> list[LaidLine]:
        """A box's lines, a word at a time: a line breaks where the next word would pass
        ``LAST_PEN``, and at each ``{line}``. Under a speaker's name every line but the
        message's first is indented, a line the layout breaks too; a choice's line starts
        with spaces that take the pen on to ``CHOICE_PEN``."""
        if isinstance(box, str):
            box = ParsedBox(False, tuple(_parse_line(line) for line in box.split(LINE_BREAK)))
        space = self.codes(" ")
        space_width = self.font.width(space[0]) if self.font is not None else SPACE_WIDTH
        indent = LINE_INDENT if speaker else LINE_START
        lines: list[LaidLine] = []
        for number, parsed in enumerate(box.lines):
            start = LINE_START if first and not number else indent
            lead = _choice_lead(start, space_width) if parsed.choice else 0
            line = bytearray(space * lead)
            pen = origin = start + lead * space_width
            written = False
            for word in parsed.words:
                codes, width = self.word(word)
                gap = space_width if written else 0
                if written and self.font is not None and pen + gap + width > LAST_PEN:
                    lines.append(LaidLine(bytes(line), start, pen, parsed.choice))
                    # The engine starts the next line at the indent, as after a {line}.
                    start = indent
                    lead = _choice_lead(start, space_width) if parsed.choice else 0
                    line = bytearray(space * lead)
                    pen = origin = start + lead * space_width
                    gap = 0
                if gap:
                    line += space
                line += codes
                pen += gap + width
                written = True
                if self.font is not None and pen > LAST_PEN:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A word needs {width}px; a line holds {LAST_PEN - origin}px",
                    )
            lines.append(LaidLine(bytes(line), start, pen, parsed.choice))
        return lines


def _choice_lead(start: int, space_width: int) -> int:
    """The spaces a choice's line starts with: the engine starts the line's pen at
    ``start``, and the spaces take it on to ``CHOICE_PEN``, as the English indents its
    choices, so the cursor's tiles on the line's right hold none of the text."""
    return max(0, -(-(CHOICE_PEN - start) // space_width))


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
    the mirror of the pen; a name, a number or an item is a grey block as wide as the
    layout reckons it."""
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
            at = 0
            while at < len(line.data):
                code = line.data[at]
                if code < ARABIC_CODES[0]:
                    width, length = _command_width(line.data, at)
                    for dx in range(width):
                        image.putpixel((MIRROR - pen - width + dx, y + 6), (150, 150, 150))
                    pen += width
                    at += length
                    continue
                glyph = font.glyphs[code]
                _draw(image, glyph, MIRROR - pen - glyph.width, y)
                pen += glyph.width
                at += 1
    return image


def _command_width(data: bytes, at: int) -> tuple[int, int]:
    """The width the layout reckons for the command at ``at``, and its length."""
    code = data[at]
    if code in NAMES or code in (0x1B, 0x1C, 0x1D, 0x20, 0x11):
        return NAME_WIDTH, 1
    if code == 0x1F:
        return ITEM_WIDTH, 1
    if code == 0x12:
        return ITEM_WIDTH, 2
    if code == PAUSE:
        return 0, 2
    return CODE_WIDTHS.get(code, 0), 1


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
