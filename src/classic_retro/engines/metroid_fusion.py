"""Text engine of *Metroid Fusion* (GBA).

Text is a string of 16-bit units, ended by ``FF00``. Which of them are
commands depends on the routine that reads the text (its *dialect*):

- ``INTRO``, the new-file intro's routines: ``FE00`` ends a line; ``FD00``
  clears the text for a new page; ``FC00`` shows the next-page arrow and waits
  for A (two in a row wait twice); ``E1xx`` waits ``xx`` frames;
- ``NAVIGATION``, the briefings on the map (``NavigationConversationProcessText``,
  ``0x08079AFC``): every unit from 0x8000 but the glyphs ``Bxxx``, ``Dxxx`` and
  ``Fxxx`` other than those below. ``80xx`` moves the pen ``xx`` pixels, ``81xx``
  sets the colour of the glyphs that follow, ``82xx`` their speed and ``83xx``
  puts the pen at ``xx`` on its line; ``9xxx`` and ``Axxx`` play sounds; ``B001``
  to ``B003`` are events (``B003`` starts the briefing's music) and so is
  ``Cxxx``; ``E000`` shows the target on the map, ``E1xx`` waits ``xx`` frames,
  ``E2xx`` picks a panel and the other ``Exxx`` set flags. The box holds two
  lines: ``FE00`` ends a line (on the second, the box scrolls at once),
  ``FC00`` waits for A and ends the line, ``FD00`` waits for A and clears the
  box, and ``FB00`` asks the objective question, after which the text goes on
  in a cleared box;
- ``QUESTION``, the objective question (``0x0807A0FC``): ``FE00`` ends the
  line, ``80xx`` moves the pen ``xx`` pixels and ``83xx`` puts it at ``xx`` on its
  line (``83A0`` 16 pixels before).

Any other unit is a glyph of the font. The font has a width for each of the
codes 0x000..0x49F (a byte each at ``FONT_WIDTHS``; any other code is 10
pixels wide) and its glyphs in one sheet of 4bpp tiles (``FONT_GRAPHICS``), 32
tiles a row: glyph ``c`` is 16 pixels tall, the tile at ``32 * c`` above the
one at ``32 * c + 0x400``, so glyphs have codes from every other row of 32. A
glyph wider than 8 pixels takes the tiles of the next code too, up to 16
pixels. Pixel 2 is the ink and 3 the outline around it; a colour ``n`` draws
them as ``2 + 2n`` and ``3 + 2n``. The English text uses the Latin codes
0x40..0x5F (space and punctuation), 0x80..0x9F (capitals) and 0xC0..0xDF
(small letters), ASCII shifted by 0x20, 0x40 and 0x60.

``GetCharacterWidth`` (``0x08079118``) reads the widths and ``DrawCharacter``
(``0x0807913C``) ORs a glyph into a row of tiles at a pixel offset, spilling
into the tiles on its right. Every routine lays a line out from the left,
with a pen that the glyphs' widths move on.

The texts are listed by language (the game reads the list of the language
byte at ``0x03000011``; English: 2): the monologues (Samus's narration in
cutscenes, 19 in each list) at ``MONOLOGUE_LANGUAGES``, the briefings (201,
two for each conversation: the briefing and what it says when it comes again)
at ``NAVIGATION_LANGUAGES``, and the messages (74, the objective questions
among them) at ``MESSAGE_LANGUAGES``.

The notation writes the Latin codes as ASCII (not braces), ``FE00`` as a line
end, the other commands of the dialect as ``{XXXX}`` (hex) and any other glyph
as ``{char XXXX}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.tiles import unpack_4bpp

ROM_BASE = 0x08000000
END = 0xFF00
NEWLINE = 0xFE00
NEW_PAGE = 0xFD00
ARROW = 0xFC00
QUESTION_PROMPT = 0xFB00
WAIT = 0xE100
PEN_ADVANCE = 0x8000
COLOUR = 0x8100
PEN_SET = 0x8300
# At 83A0, the question's pen goes 16 pixels before 0xA0.
QUESTION_SECOND_OPTION = 0x83A0
QUESTION_SECOND_OPTION_SHIFT = 0x10

INTRO = "intro"
NAVIGATION = "navigation"
QUESTION = "question"
DIALECTS = (INTRO, NAVIGATION, QUESTION)

FONT_WIDTHS = 0x08576234
FONT_GRAPHICS = 0x08682FAC
FONT_CODES = 0x4A0
DEFAULT_WIDTH = 10
GLYPH_ROWS = 16
GLYPH_COLUMNS = 16
TILE_BYTES = 32
TILE_ROW_BYTES = 0x400
INK = 2
OUTLINE = 3

ENGLISH = 2
MONOLOGUE_LANGUAGES = 0x0879C5A4
MONOLOGUES = 19
NAVIGATION_LANGUAGES = 0x0879C0F0
NAVIGATION_TEXTS = 201
MESSAGE_LANGUAGES = 0x0879CDF4
MESSAGES = 74

# Latin codes: ASCII shifted by 0x20 (space and punctuation), 0x40 (capitals)
# and 0x60 (small letters).
_LATIN_SHIFTS = {0x40: 0x20, 0x80: 0x40, 0xC0: 0x60}
LATIN_CODES = {
    code: chr(code - shift)
    for start, shift in _LATIN_SHIFTS.items()
    for code in range(start, start + 0x20)
    if 0x20 <= code - shift < 0x7F and chr(code - shift) not in "{}"
}
_LATIN = {character: code for code, character in LATIN_CODES.items()}

# Units from 0x8000 that a briefing draws: Bxxx but its events, Dxxx, and Fxxx
# but the commands that end a line.
_NAVIGATION_EVENTS = frozenset((0xB001, 0xB002, 0xB003))
_BREAKS = frozenset((NEWLINE, NEW_PAGE, ARROW, QUESTION_PROMPT))

_NOTATION_COMMAND = re.compile(r"\{([0-9A-Fa-f]{4})\}")
_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{4})\}")


class MetroidFusionEngineAdapter(EngineAdapter):
    id = "gba.metroid-fusion"
    display_name = "Metroid Fusion GBA text engine"
    platform_ids = ("gba",)


def is_command(unit: int, dialect: str = INTRO) -> bool:
    """Whether the routines of ``dialect`` read ``unit`` as a command, not a glyph."""
    if dialect == INTRO:
        return unit in (NEWLINE, NEW_PAGE, ARROW) or unit & 0xFF00 == WAIT
    if dialect == NAVIGATION:
        kind = unit >> 12
        if kind == 0xB:
            return unit in _NAVIGATION_EVENTS
        if kind == 0xF:
            return unit in _BREAKS
        return unit >= 0x8000 and kind != 0xD
    if dialect == QUESTION:
        return unit == NEWLINE or unit & 0xFF00 in (PEN_ADVANCE, PEN_SET)
    raise ValueError(f"Unknown Metroid Fusion dialect {dialect!r}")


@dataclass(frozen=True, slots=True)
class MfCommand:
    """A command unit: a line end, a page, the arrow, a wait, or a briefing's command."""

    unit: int

    @property
    def is_newline(self) -> bool:
        return self.unit == NEWLINE

    @property
    def notation(self) -> str:
        if self.is_newline:
            return "\n"
        return f"{{{self.unit:04X}}}"

    @property
    def is_inline(self) -> bool:
        """A command inside a line (a colour, the pen, a sound, an event): no break or wait."""
        return self.unit not in _BREAKS and self.unit & 0xFF00 != WAIT

    @property
    def skeleton_notation(self) -> str:
        """As a skeleton shows it: a pen advance without its amount (which may change)."""
        if self.unit & 0xFF00 == PEN_ADVANCE:
            return "{80xx}"
        return self.notation


Piece = str | MfCommand


def text_units(data: bytes, offset: int) -> tuple[int, ...]:
    """The units from ``offset`` up to (without) the final ``FF00``."""
    units = []
    index = offset
    while index + 2 <= len(data):
        unit = struct.unpack_from("<H", data, index)[0]
        if unit == END:
            return tuple(units)
        units.append(unit)
        index += 2
    raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, f"No end after {offset:#x}")


def read_text(rom: bytes, address: int) -> tuple[int, ...]:
    offset = address - ROM_BASE
    if not 0 <= offset < len(rom) or offset % 2:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{address:#x} is not a text in the image"
        )
    return text_units(rom, offset)


def pack_units(units: Iterable[int]) -> bytes:
    """Units as the ROM stores them, without the final ``FF00``."""
    values = tuple(units)
    return struct.pack(f"<{len(values)}H", *values)


def split_text(units: Sequence[int], dialect: str = INTRO) -> tuple[Piece, ...]:
    """Text runs and command units."""
    pieces: list[Piece] = []
    run: list[str] = []
    for unit in units:
        if is_command(unit, dialect):
            if run:
                pieces.append("".join(run))
                run.clear()
            pieces.append(MfCommand(unit))
        else:
            run.append(LATIN_CODES.get(unit) or f"{{char {unit:04X}}}")
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def text_notation(units: Sequence[int], dialect: str = INTRO) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(units, dialect)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Commands in order, without the line ends that follow text (which may move).

    A line end still follows text across inline commands (a colour, the pen).
    A pen advance (``80xx``) shows without its amount, which may change.
    """
    skeleton: list[str] = []
    after_text = False
    for piece in pieces:
        if isinstance(piece, str):
            after_text = after_text or bool(piece)
            continue
        if not (piece.is_newline and after_text):
            skeleton.append(piece.skeleton_notation)
        if not piece.is_inline:
            after_text = False
    return tuple(skeleton)


def command_skeleton(units: Sequence[int], dialect: str = INTRO) -> tuple[str, ...]:
    return notation_skeleton(split_text(units, dialect))


def parse_notation(text: str, dialect: str = INTRO) -> tuple[Piece, ...]:
    """Notation as text runs and commands (``{char XXXX}`` stays inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            command = MfCommand(NEWLINE)
            index += 1
        elif character == "{":
            char = _NOTATION_CHAR.match(text, index)
            if char is not None:
                run.append(char.group(0))
                index = char.end()
                continue
            match = _NOTATION_COMMAND.match(text, index)
            unit = int(match.group(1), 16) if match is not None else None
            if unit is None or unit == NEWLINE or not is_command(unit, dialect):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Unknown or unmatched command at {text[index:]!r}",
                )
            command = MfCommand(unit)
            index = match.end()
        elif character == "}":
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "Unmatched '}'")
        else:
            run.append(character)
            index += 1
            continue
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(command)
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def encode_text(text: str, dialect: str = INTRO) -> tuple[int, ...]:
    """Units of a text run in the game's font (the Latin codes and ``{char XXXX}``)."""
    units = []
    index = 0
    while index < len(text):
        char = _NOTATION_CHAR.match(text, index)
        if char is not None:
            unit = int(char.group(1), 16)
            if is_command(unit, dialect) or unit == END:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{char.group(0)} is a command"
                )
            units.append(unit)
            index = char.end()
            continue
        code = _LATIN.get(text[index])
        if code is None:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"The Metroid Fusion font has no {text[index]!r}"
            )
        units.append(code)
        index += 1
    return tuple(units)


def pieces_units(pieces: Iterable[Piece], dialect: str = INTRO) -> tuple[int, ...]:
    units: list[int] = []
    for piece in pieces:
        if isinstance(piece, str):
            units.extend(encode_text(piece, dialect))
        else:
            units.append(piece.unit)
    return tuple(units)


Pixels = tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class MfFont:
    """The game's font: a width for each code below ``FONT_CODES`` and the glyph sheet."""

    widths: tuple[int, ...]
    sheet: bytes

    @classmethod
    def read(cls, rom: bytes) -> MfFont:
        start = FONT_WIDTHS - ROM_BASE
        widths = tuple(rom[start : start + FONT_CODES])
        sheet_start = FONT_GRAPHICS - ROM_BASE
        sheet_end = sheet_start + TILE_BYTES * FONT_CODES + TILE_ROW_BYTES + TILE_BYTES
        if len(widths) != FONT_CODES or sheet_end > len(rom):
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "The font is outside the image")
        return cls(widths, bytes(rom[sheet_start:sheet_end]))

    def width(self, code: int) -> int:
        return self.widths[code] if code < FONT_CODES else DEFAULT_WIDTH

    def glyph(self, code: int) -> Pixels:
        """16 rows of 16 pixels, as ``DrawCharacter`` reads them (both tile columns)."""
        return glyph_pixels(self.sheet, code * TILE_BYTES)


def glyph_pixels(sheet: bytes, offset: int) -> Pixels:
    """16 rows of 16 pixels from a sheet of tiles, 32 tiles a row, at ``offset``."""
    tiles = b"".join(
        sheet[start : start + TILE_BYTES]
        for start in (
            offset,
            offset + TILE_BYTES,
            offset + TILE_ROW_BYTES,
            offset + TILE_ROW_BYTES + TILE_BYTES,
        )
    )
    return unpack_4bpp(tiles, GLYPH_COLUMNS, GLYPH_ROWS)


# ---------------------------------------------------------------------------
# Layout: where the routines draw every glyph


@dataclass(frozen=True, slots=True)
class MfPlace:
    """A glyph as a routine draws it: at ``pen`` on its line, ``width`` wide, in a colour."""

    unit: int
    pen: int
    width: int
    colour: int = 0

    @property
    def end(self) -> int:
        return self.pen + self.width


@dataclass(frozen=True, slots=True)
class MfLine:
    """A line of a page (a briefing's box): its number there, what began it, its glyphs.

    ``start`` is 0 for a page's first line, else the unit that ended the line
    before (``NEWLINE``, or ``ARROW`` in a briefing). ``waits`` is whether the
    reader presses A at its end, where the arrow shows.
    """

    page: int
    number: int
    start: int
    places: tuple[MfPlace, ...]
    waits: bool = False

    @property
    def width(self) -> int:
        """Where the pen stops: the end of the line's rightmost glyph."""
        return max((place.end for place in self.places), default=0)


def moved_pen(unit: int, pen: int, dialect: str) -> int:
    """The pen after a pen command: ``80xx`` moves it, ``83xx`` puts it on its line.

    Only the question reads ``83A0`` as 16 pixels before 0xA0.
    """
    if unit & 0xFF00 == PEN_ADVANCE:
        return pen + (unit & 0xFF)
    if dialect == QUESTION and unit == QUESTION_SECOND_OPTION:
        return (unit & 0xFF) - QUESTION_SECOND_OPTION_SHIFT
    return unit & 0xFF


def lay_out(
    units: Sequence[int], width: Callable[[int], int], dialect: str = INTRO
) -> tuple[MfLine, ...]:
    """The lines of a text as the routines of ``dialect`` lay them out, from the left.

    The model leaves out what a routine does when a line overflows (a
    briefing and the question wrap it, the intro draws on).
    """
    lines: list[MfLine] = []
    page = number = start = pen = colour = 0
    places: list[MfPlace] = []
    waits = False

    def close() -> None:
        lines.append(MfLine(page, number, start, tuple(places), waits))
        places.clear()

    for unit in units:
        if not is_command(unit, dialect):
            glyph_width = width(unit)
            places.append(MfPlace(unit, pen, glyph_width, colour))
            pen += glyph_width
            continue
        kind = unit & 0xFF00
        if dialect == INTRO and unit == ARROW:
            waits = True
        elif unit == NEWLINE or (dialect == NAVIGATION and unit == ARROW):
            waits = waits or unit == ARROW
            close()
            number, start, pen, waits = number + 1, unit, 0, False
        elif unit == NEW_PAGE or (dialect == NAVIGATION and unit == QUESTION_PROMPT):
            waits = waits or dialect == NAVIGATION
            close()
            page, number, start, pen, waits = page + 1, 0, 0, 0, False
        elif dialect == INTRO:
            continue
        elif kind in (PEN_ADVANCE, PEN_SET):
            pen = moved_pen(unit, pen, dialect)
        elif kind == COLOUR:
            colour = unit & 0xFF
    close()
    return tuple(lines)


def line_widths(units: Sequence[int], font: MfFont) -> tuple[int, ...]:
    """The pixel width of every line of an intro text: the glyphs' widths added up."""
    return tuple(line.width for line in lay_out(units, font.width))
