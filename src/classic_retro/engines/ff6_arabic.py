"""Arabic support for the dialogue of *Final Fantasy III* (USA, Super NES).

The game draws a letter a frame with a variable-width font: the letter's
glyph (sixteen pixels across, a bit each, eleven rows) is shifted to the
pen, ORed into a buffer of a cell of 16x16 pixels and sent to the tiles'
memory, with a shadow a pixel to its right in the second plane; the pen
moves on by the letter's width (``engines.ff6``). The overlay
(``classic_retro.rom.ff6_arabic``) sends a translated message's reading to its
Arabic text, whose bytes from ``20`` are glyphs of an Arabic font of its own
(``ARABIC_CODES``), the bytes below keeping their meaning (the line's end,
the page's end, the names, the pauses); an Arabic line is laid out whole by
the hook when it starts, from the box's right edge (``RIGHT_EDGE``) leftwards
into a buffer of the line's cells, sent to the tiles' memory in the next
vertical blank, and the game's own draw is left idle for it.

A glyph is ``GLYPH_ROWS`` (15) rows of ``GLYPH_WIDTH`` (16) pixels, a bit
each, its ink from its left column, and a width (the pen's advance; a form
that joins the glyph on its right has its stroke run on to its edge, as
Chrono Trigger's do). The hook draws a glyph at any pixel with no shifting:
the overlay writes each glyph in ``SHIFTS`` (9) variants, shifted right by 0
to 8 pixels into three bytes a row (``variant_data``), and the shadow is the
next variant in the second plane. The forms are drawn from the reference
font at the largest size where every form of the repertoire and every digit
fits the rows on its baseline (``BASELINE``); the merged dots of small
letters are drawn apart (``separated_dots``); the punctuation the reference
font lacks or draws too small is drawn by hand (``PUNCTUATION``); the space
is a blank glyph ``SPACE_WIDTH`` wide.

A translation's notation is a line for each page of the message (the box
shows ``MAX_LINES`` lines and waits for the button between pages): the
encoder lays each page out itself, a word at a time, in lines from the
right edge to ``LEFT_EDGE``; ``{line}`` ends a line where it stands. A
``{Terra}`` token (``engines.ff6.NAMES``) writes that character's name from
the translation's own names (``encode_name``), as wide as its glyphs; the
pauses and button waits (``PASSING_COMMANDS``) pass through as tokens. The
gil amount, the item and the spell are not for an Arabic message: the game
writes them in its own letters.

A translation keeps the original's commands: its skeleton
(``notation_skeleton``: every token but ``{line}``, in order) must equal the
original's (``engines.ff6.command_skeleton``), which leaves out the same
layout the encoder writes itself: the lines, the pages and the spaces.
``validate_command_skeleton`` refuses a translation that drops, adds or moves
any other command.
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
from classic_retro.engines.ff6 import (
    COMMAND_CODES,
    COMMANDS,
    END,
    LINE,
    LINE_END,
    LINE_START,
    LINES,
    NAME_CODES,
    NAME_FIRST,
    NAME_LAST,
    PAGE,
    SPACES,
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
    raised_marks,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Final Fantasy III Arabic"
ENGINE = "Final Fantasy III"
# A byte of an Arabic message from here is a glyph of the Arabic font.
ARABIC_CODES = tuple(range(0x20, 0x100))
FIRST_CODE = ARABIC_CODES[0]
# A glyph: 15 rows of 16 pixels, on the cell's rows 0-14, its baseline on row 10.
GLYPH_WIDTH = 16
GLYPH_ROWS = 15
BASELINE = 10
SIZES = range(15, 8, -1)
WIDEST = GLYPH_WIDTH
# The hook's copy of a glyph: 9 variants shifted right by 0-8 pixels, 3 bytes a row.
SHIFTS = 9
ROW_BYTES = 3
VARIANT_BYTES = GLYPH_ROWS * ROW_BYTES
GLYPH_BYTES = SHIFTS * VARIANT_BYTES
INK = 1
CLEAR = 0
INK_LEVEL = 128
MARK_LEVEL = 60
DIGITS = "0123456789"
SPACE_WIDTH = 4
# The box: a line's glyphs end at the right edge and may reach the left one.
RIGHT_EDGE = LINE_END
LEFT_EDGE = LINE_START
LINE_WIDTH = RIGHT_EDGE - LEFT_EDGE
MAX_LINES = LINES
# A name's glyphs, in the message's codes, then $FF: NAME_STRIDE bytes an entry.
NAME_STRIDE = 32
NAME_END = 0xFF
NAME_WIDTH_MAX = 64
# Punctuation drawn by hand: rows of ink, from how many rows above the baseline.
PUNCTUATION: dict[str, tuple[tuple[str, ...], int]] = {
    ".": (("##", "##"), 1),
    ",": (("##", "##", ".#"), 1),
    ":": (("##", "##", "..", "..", "##", "##"), 5),
    "!": (("##",) * 5 + ("..", "##", "##"), 7),
    "-": (("####",), 3),
    "…": (("#.#.#",), 0),
    "،": ((".##", ".##", "##.", "#.."), 2),
    "؛": ((".##", ".##", "...", ".##", ".##", "##.", "#.."), 5),
    "؟": ((".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."), 7),
    # The quotes and the brackets: a right-to-left run shows each mirrored, and
    # the painter does not mirror, so each is drawn as its mirror image.
    "«": (("#.#..", ".#.#.", "..#.#", ".#.#.", "#.#.."), 6),
    "»": (("..#.#", ".#.#.", "#.#..", ".#.#.", "..#.#"), 6),
    "(": (("#..", ".#.", "..#", "..#", "..#", "..#", "..#", "..#", ".#.", "#.."), 9),
    ")": (("..#", ".#.", "#..", "#..", "#..", "#..", "#..", "#..", ".#.", "..#"), 9),
    # The opera's note, which the English writes with the font's note icon.
    "♪": (
        ("...#..", "...##.", "...#.#", "...#..", "...#..", "...#..", ".###..", "####..", ".##..."),
        9,
    ),
}
# The brackets drawn mirrored above: the painter lets them through.
MIRRORED_SIGNS = frozenset("()«»")
# Hamza above alef reaches above the cell at some sizes: the font's alef, cut
# below a hamza drawn on the top rows. The tail of final and isolated yeh can
# reach below it: those forms are raised a row, the final keeping its joining pixel.
_HAMZA = ("##", "#.")
MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {"ﺃ": ("ﺍ", _HAMZA), "ﺄ": ("ﺎ", _HAMZA)}
RAISED_FORMS = frozenset("ﻱﻲ")
LINE_BREAK = "{line}"
# A page that starts with this has its lines centred: each starts with a SPACES
# command whose byte is the pixels from the right edge to the line.
CENTER = "{center}"
LAYOUT_TOKENS = frozenset((LINE_BREAK, CENTER))
# A choice's mark: the pen moves to a cell's edge, then the cursor's cell (which
# the line leaves) is the next cell down, at the right of the choice's text.
CHOICE = COMMAND_CODES["Choice"]
CHOICE_WIDTH = 16
CELL_WIDTH = 16
# Commands a translation may write: the names, the pauses and button waits, and
# a choice's mark.
PASSING_COMMANDS = frozenset((*NAME_CODES, "Wait", "Pause", "Key", "KeyAfter", "Choice"))
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SPACES_OUTSIDE_TOKENS = re.compile(r" (?![^{}]*\})")


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font can draw, in the order codes follow."""
    order = (" ", *PUNCTUATION, *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def ff6_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from ``ARABIC_CODES`` for the characters a translation uses, in the font's order."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what=f"{PROFILE} glyphs",
    )


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class Ff6Glyph:
    """A glyph: its width (the pen's advance) and its 15 rows of 16 bits of ink."""

    width: int
    rows: tuple[tuple[int, ...], ...]

    def words(self) -> tuple[int, ...]:
        """Each row as the font's word: the leftmost pixel in bit 15."""
        return tuple(sum(0x8000 >> x for x, value in enumerate(row) if value) for row in self.rows)

    def variant_data(self) -> bytes:
        """The hook's ``GLYPH_BYTES``: for each shift of 0 to 8 pixels, the rows as
        three bytes, the glyph's 16 pixels shifted right by that much in 24."""
        data = bytearray()
        for shift in range(SHIFTS):
            for word in self.words():
                window = (word << 8) >> shift
                data += bytes((window >> 16 & 0xFF, window >> 8 & 0xFF, window & 0xFF))
        return bytes(data)


@dataclass(frozen=True, slots=True)
class Ff6Font:
    """The Arabic glyphs by code, and the size they were drawn at."""

    glyphs: Mapping[int, Ff6Glyph]
    font_size: int

    def width(self, code: int) -> int:
        try:
            return self.glyphs[code].width
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"The Arabic font has no glyph {code:#04x}"
            ) from None


def glyph_from_ink(ink: Collection[Pixel], width: int) -> Ff6Glyph:
    """Ink in the glyph's rows, ``width`` the advance. Raises ``FormDoesNotFit`` when
    the ink leaves the glyph or the width passes it."""
    if not 0 < width <= WIDEST or any(
        not 0 <= x < WIDEST or not 0 <= y < GLYPH_ROWS for x, y in ink
    ):
        raise FormDoesNotFit
    pixels = set(ink)
    return Ff6Glyph(
        width,
        tuple(
            tuple(INK if (x, y) in pixels else CLEAR for x in range(WIDEST))
            for y in range(GLYPH_ROWS)
        ),
    )


def form_glyph(character: str, ink: Collection[Pixel], advance: int) -> Ff6Glyph:
    """A drawn form: as wide as its advance, with a pixel free after its ink, but for
    a form that joins the glyph on its right, whose stroke runs on to its edge."""
    right = max(x for x, _ in ink)
    width = right + 1 if joins_right_neighbour(character) else max(advance, right + 2)
    return glyph_from_ink(ink, width)


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)
    return raised_marks(separated_dots(character, form), GLYPH_ROWS - 1)


def _drawn_glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, Ff6Glyph] | None:
    """Every character at this size, or None when one leaves its rows."""
    try:
        glyphs = {}
        for character in characters:
            if character in MARKED_ALEF:
                alef, mark = MARKED_ALEF[character]
                form = alef_with_mark(character, _drawn(font, alef), mark)
            else:
                form = _drawn(font, character)
            if character in RAISED_FORMS:
                form = raised_form(character, form, height=GLYPH_ROWS, baseline=BASELINE)
            glyphs[character] = form_glyph(character, form.ink, form.advance)
        return glyphs
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(character: str) -> Ff6Glyph:
    rows, above = PUNCTUATION[character]
    ink = pattern_pixels(rows, top=BASELINE - above)
    return glyph_from_ink(ink, len(rows[0]) + 2)


def space_glyph() -> Ff6Glyph:
    return Ff6Glyph(SPACE_WIDTH, tuple((CLEAR,) * WIDEST for _ in range(GLYPH_ROWS)))


def build_ff6_font(
    font_path: Path,
    glyph_map: GlyphCodes,
    used: Collection[str],
    *,
    sizing: Iterable[str] | None = None,
) -> Ff6Font:
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
        f"Selected font cannot fit {ENGINE}'s glyphs of {WIDEST}x{GLYPH_ROWS} pixels",
    )
    for character in PUNCTUATION:
        rendered[character] = hand_drawn_glyph(character)
    rendered[" "] = space_glyph()
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        if code is None:
            raise no_glyph(character, PROFILE)
        glyphs[code] = rendered[character]
    return Ff6Font(glyphs, size)


BANK = 0x10000
GLYPH_FILL = 0xFF


def glyph_table(font: Ff6Font, base: int, capacity: int) -> tuple[bytes, bytes, bytes]:
    """What the hook reads: a width a code of ``ARABIC_CODES`` (0 where the font has
    no glyph), a 24-bit address a code (``base`` + the glyph's offset, the bank its
    third byte), and the glyph data, the variants of each glyph the font has in the
    order of the codes; a glyph never crosses a bank, so the data is padded to the
    next bank where one would, and it must fit ``capacity`` bytes from ``base``."""
    if base % BANK:
        raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "The glyphs start a bank")
    widths = bytearray()
    addresses = bytearray()
    data = bytearray()
    for code in ARABIC_CODES:
        glyph = font.glyphs.get(code)
        if glyph is None:
            widths.append(0)
            addresses += (0).to_bytes(3, "little")
            continue
        if len(data) % BANK + GLYPH_BYTES > BANK:
            data += bytes((GLYPH_FILL,)) * (BANK - len(data) % BANK)
        if len(data) + GLYPH_BYTES > capacity:
            raise ClassicRetroError(
                ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                f"{PROFILE} glyphs: {len(font.glyphs)} glyphs do not fit their banks",
            )
        widths.append(glyph.width)
        addresses += (base + len(data)).to_bytes(3, "little")
        data += glyph.variant_data()
    return bytes(widths), bytes(addresses), bytes(data)


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
    """A command of the text: its bytes, and its name's code when it is a name."""

    data: bytes
    name: int | None = None


def command(token: str) -> Command:
    """A ``{token}`` of the notation: a name, or a passing command with its byte or without."""
    name, _, argument = token.partition(" ")
    if name not in PASSING_COMMANDS:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")
    code = COMMAND_CODES[name]
    if COMMANDS[code][1] == 2:
        if not re.fullmatch(r"[0-9A-F]{2}", argument):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"{{{token}}}: {name} takes a byte, as {{{name} 01}}",
            )
        return Command(bytes((code, int(argument, 16))))
    if argument:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{{{token}}}: {name} takes no byte"
        )
    return Command(bytes((code,)), code if name in NAME_CODES else None)


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
    ``engines.ff6.command_skeleton`` gives for the bytes the encoder writes."""
    return tuple(
        part
        for match in _TOKEN.finditer(notation)
        if f"{{{match.group(1)}}}" not in LAYOUT_TOKENS
        for part in command_skeleton(command(match.group(1)).data)
    )


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a message paints."""
    used = {" "}
    for page in notation.split("\n"):
        for segment in _uncentred(page).split(LINE_BREAK):
            for word in _words(segment):
                for piece in _pieces(word):
                    if isinstance(piece, str):
                        used |= set(paint_text(piece))
    return used


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line: its bytes and its width in pixels, from the right edge."""

    data: bytes
    width: int


@dataclass(frozen=True, slots=True)
class EncodedMessage:
    """A translated message's bytes (its end included) and, with a font, its pages."""

    data: bytes
    pages: tuple[tuple[LaidLine, ...], ...] | None


class Ff6ArabicEncoder:
    """Convert a logical Arabic message (a line a page) into the hook's bytes.

    With a font, the lines are laid out by their pixels and the names' widths
    (``name_widths``: by the name's code, from ``encode_name``); without, the
    codes are ``ff6_glyph_codes``' and no layout.
    """

    def __init__(
        self,
        glyph_map: GlyphCodes,
        font: Ff6Font | None = None,
        name_widths: Mapping[int, int] | None = None,
    ) -> None:
        self.glyph_map = glyph_map
        self.font = font
        self.name_widths = dict(name_widths or {})

    def codes(self, painted: str) -> bytes:
        output = bytearray()
        for character in painted:
            code = self.glyph_map.code(character)
            if code is None:
                raise no_glyph(character, PROFILE)
            output.append(code)
        return bytes(output)

    def width(self, codes: bytes, pen: int = RIGHT_EDGE) -> int:
        """How wide the codes draw from ``pen``: the glyphs' widths, a name's from its
        entry, a choice's mark the pixels to a cell's edge and then its cell."""
        if self.font is None:
            return 0
        width = 0
        at = 0
        while at < len(codes):
            code = codes[at]
            if NAME_FIRST <= code <= NAME_LAST:
                if code not in self.name_widths:
                    raise ClassicRetroError(
                        ErrorCode.MISSING_GLYPH, f"No Arabic name for {COMMANDS[code][0]}"
                    )
                width += self.name_widths[code]
            elif code == CHOICE:
                width += choice_advance(pen - width)
            elif code == SPACES:
                width += codes[at + 1]
            elif code >= FIRST_CODE:
                width += self.font.width(code)
            at += COMMANDS[code][1] if code in COMMANDS else 1
        return width

    def word(self, word: str, pen: int = RIGHT_EDGE) -> tuple[bytes, int]:
        """A word's bytes, in the order they are painted from the right, and its width
        from ``pen``."""
        data = bytearray()
        for piece in _pieces(word):
            if isinstance(piece, Command):
                data += piece.data
            else:
                data += self.codes(paint_text(piece))
        return bytes(data), self.width(bytes(data), pen)

    def encode(self, notation: str) -> EncodedMessage:
        """The message's bytes: each page's lines, ``LINE`` between them; ``PAGE``
        between pages, but after a full page, which the game turns itself; then
        the end."""
        pages_text = notation.split("\n")
        data = bytearray()
        laid: list[tuple[LaidLine, ...]] = []
        for number, page in enumerate(pages_text):
            lines = self.page(page)
            if len(lines) > MAX_LINES:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Page {number + 1} needs {len(lines)} lines; the box shows {MAX_LINES}",
                )
            for index, line in enumerate(lines):
                if index:
                    data.append(LINE)
                data += line.data
            if number + 1 < len(pages_text):
                data.append(LINE if len(lines) == MAX_LINES else PAGE)
            laid.append(tuple(lines))
        data.append(END)
        return EncodedMessage(bytes(data), tuple(laid) if self.font is not None else None)

    def page(self, page: str) -> list[LaidLine]:
        """A page's lines, a word at a time: a line breaks where the next word would
        pass ``LINE_WIDTH``, and at each ``{line}``. A page that starts with
        ``{center}`` has each line centred with a spaces command, when there is a
        font to measure by."""
        centred = page.startswith(CENTER)
        lines = self._lines(_uncentred(page))
        if not centred or self.font is None:
            return lines
        centred_lines = []
        for line in lines:
            if CHOICE in line.data:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    "A choice's mark is not centred: its cell moves with the line",
                )
            indent = (LINE_WIDTH - line.width) // 2
            data = bytes((SPACES, indent)) + line.data if indent else line.data
            centred_lines.append(LaidLine(data, line.width + indent))
        return centred_lines

    def _lines(self, page: str) -> list[LaidLine]:
        space = self.codes(" ")
        space_width = self.font.width(space[0]) if self.font is not None else SPACE_WIDTH
        lines: list[LaidLine] = []
        for segment in page.split(LINE_BREAK):
            line = bytearray()
            width = 0
            for word in _words(segment):
                gap = space_width if line else 0
                codes, word_width = self.word(word, RIGHT_EDGE - width - gap)
                if line and self.font is not None and width + gap + word_width > LINE_WIDTH:
                    lines.append(LaidLine(bytes(line), width))
                    line, width, gap = bytearray(), 0, 0
                    codes, word_width = self.word(word, RIGHT_EDGE)
                if gap:
                    line += space
                line += codes
                width += gap + word_width
                if self.font is not None and width > LINE_WIDTH:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"A word needs {word_width}px; a line holds {LINE_WIDTH}px",
                    )
            lines.append(LaidLine(bytes(line), width))
        return lines


def choice_advance(pen: int) -> int:
    """The pixels a choice's mark takes at ``pen``: to the edge of the pen's cell,
    then the cell for its cursor, as the hook moves the pen."""
    return pen - max(pen - pen % CELL_WIDTH - CHOICE_WIDTH, 0)


def _uncentred(page: str) -> str:
    """The page without its ``{center}`` mark, which may only start it."""
    if page.startswith(CENTER):
        page = page[len(CENTER) :]
    if CENTER in page:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, "{center} starts a page: it goes first"
        )
    return page


def encode_name(encoder: Ff6ArabicEncoder, key: str, text: str) -> tuple[bytes, int]:
    """A character's name in the message's codes, in the order they are painted, and
    its width: what the hook draws in place of the name the player gave."""
    if not text or " " in text or "{" in text:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"{key}: a name is one word without commands"
        )
    codes, width = encoder.word(text)
    if len(codes) >= NAME_STRIDE:
        raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, f"{key}: the name is too long")
    if width > NAME_WIDTH_MAX:
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW, f"{key}: a name is {NAME_WIDTH_MAX}px wide at most"
        )
    return codes, width


# ---------------------------------------------------------------------------
# What the game shows: the line the hook lays out


def laid_out_line(
    data: bytes, font: Ff6Font, names: Mapping[int, bytes]
) -> list[tuple[int, Ff6Glyph]]:
    """Where the hook draws each glyph of a line: its left pixel and the glyph, from
    the right edge leftwards; a name's glyphs from its entry (``names``: by the
    name's code)."""
    placed: list[tuple[int, Ff6Glyph]] = []
    pen = RIGHT_EDGE

    def draw(code: int) -> None:
        nonlocal pen
        glyph = font.glyphs[code]
        pen -= glyph.width
        placed.append((pen, glyph))

    at = 0
    while at < len(data):
        code = data[at]
        if code in (END, LINE, PAGE):
            break
        if NAME_FIRST <= code <= NAME_LAST:
            for glyph_code in names[code]:
                draw(glyph_code)
        elif code == CHOICE:
            pen -= choice_advance(pen)
        elif code == SPACES:
            pen -= data[at + 1]
        elif code >= FIRST_CODE:
            draw(code)
        at += COMMANDS[code][1] if code in COMMANDS else 1
    return placed


# ---------------------------------------------------------------------------
# Previews

PREVIEW_INK = (248, 248, 248)
PREVIEW_SHADOW = (16, 16, 24)
PREVIEW_BACKGROUND = (32, 48, 112)
LINE_HEIGHT = 16
PREVIEW_MARGIN = 4
SCREEN_WIDTH = 256


def font_preview(font: Ff6Font) -> Image.Image:
    """Atlas of the glyphs in their 16x15 cells, the width's end dark red."""
    entries = [font.glyphs[code] for code in sorted(font.glyphs)]

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = entries[number]
        if x >= glyph.width:
            return (70, 20, 20)
        return PREVIEW_INK if glyph.rows[y][x] else PREVIEW_BACKGROUND

    return glyph_atlas(len(entries), WIDEST, GLYPH_ROWS, colour)


def _draw(image: Image.Image, glyph: Ff6Glyph, x: int, top: int) -> None:
    """The glyph's ink, its shadow a pixel right where there is no ink."""
    for y, row in enumerate(glyph.rows):
        for column, value in enumerate(row):
            if value and 0 <= x + column < image.width:
                image.putpixel((x + column, top + y), PREVIEW_INK)
    for y, row in enumerate(glyph.rows):
        for column, value in enumerate(row):
            at = x + column + 1
            if value and 0 <= at < image.width and image.getpixel((at, top + y)) != PREVIEW_INK:
                image.putpixel((at, top + y), PREVIEW_SHADOW)


def message_preview(
    encoded: EncodedMessage, font: Ff6Font, names: Mapping[int, bytes]
) -> Image.Image:
    """Each page as the screen shows it: 256 pixels, a line every 16 rows, the glyphs
    from the right edge leftwards at the pixels the hook draws them; a name from
    its entry."""
    if encoded.pages is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the font")
    height = MAX_LINES * LINE_HEIGHT + 2 * PREVIEW_MARGIN
    image = Image.new("RGB", (SCREEN_WIDTH, height * len(encoded.pages)), (12, 12, 12))
    for number, page in enumerate(encoded.pages):
        top = number * height
        for x in range(2, image.width - 2):
            for y in range(top + 2, top + height - 2):
                image.putpixel((x, y), PREVIEW_BACKGROUND)
        for row, line in enumerate(page):
            y = top + PREVIEW_MARGIN + row * LINE_HEIGHT
            for x, glyph in laid_out_line(line.data, font, names):
                _draw(image, glyph, x, y)
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
