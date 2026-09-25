"""Text engine of *Metroid Fusion* (GBA).

Text is a string of 16-bit units, ended by ``FF00``:

- ``FE00`` ends a line; ``FD00`` clears the text for a new page; ``FC00``
  shows the next-page arrow and waits for A (two in a row wait twice);
- ``E1xx`` waits ``xx`` frames;
- any other unit is a glyph of the font.

The font has a width for each of the codes 0x000..0x49F (a byte each at
``FONT_WIDTHS``; any other code is 10 pixels wide) and its glyphs in one sheet
of 4bpp tiles (``FONT_GRAPHICS``), 32 tiles a row: glyph ``c`` is 16 pixels
tall, the tile at ``32 * c`` above the one at ``32 * c + 0x400``, so glyphs
have codes from every other row of 32. A glyph wider than 8 pixels takes the
tiles of the next code too, up to 16 pixels. Pixel 2 is the ink and 3 the
outline around it. The English text uses the Latin codes 0x40..0x5F (space
and punctuation), 0x80..0x9F (capitals) and 0xC0..0xDF (small letters), ASCII
shifted by 0x20, 0x40 and 0x60.

``GetCharacterWidth`` (``0x08079118``) reads the widths and ``DrawCharacter``
(``0x0807913C``) ORs a glyph into a row of tiles at a pixel offset, spilling
into the tiles on its right.

The monologues (Samus's narration in cutscenes, 19 texts in each of six
languages) are listed by language at ``MONOLOGUE_LANGUAGES``; the game reads
the list of the language byte at ``0x03000011`` (English: 2).

The notation writes the Latin codes as ASCII (not braces), ``FE00`` as a line
end, the other control units as ``{FC00}``, ``{FD00}`` and ``{E1xx}`` (hex),
and any other glyph as ``{char XXXX}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.tiles import unpack_4bpp

ROM_BASE = 0x08000000
END = 0xFF00
NEWLINE = 0xFE00
NEW_PAGE = 0xFD00
ARROW = 0xFC00
WAIT = 0xE100

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

MONOLOGUE_LANGUAGES = 0x0879C5A4
ENGLISH = 2
MONOLOGUES = 19

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

_NOTATION_COMMAND = re.compile(r"\{(F[CD]00|E1[0-9A-Fa-f]{2})\}")
_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{4})\}")


class MetroidFusionEngineAdapter(EngineAdapter):
    id = "gba.metroid-fusion"
    display_name = "Metroid Fusion GBA text engine"
    platform_ids = ("gba",)


def is_command(unit: int) -> bool:
    return unit in (NEWLINE, NEW_PAGE, ARROW) or unit & 0xFF00 == WAIT


@dataclass(frozen=True, slots=True)
class MfCommand:
    """A control unit: a line end, a page, the arrow or a wait."""

    unit: int

    @property
    def is_newline(self) -> bool:
        return self.unit == NEWLINE

    @property
    def notation(self) -> str:
        if self.is_newline:
            return "\n"
        return f"{{{self.unit:04X}}}"


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


def split_text(units: Sequence[int]) -> tuple[Piece, ...]:
    """Text runs and control units."""
    pieces: list[Piece] = []
    run: list[str] = []
    for unit in units:
        if is_command(unit):
            if run:
                pieces.append("".join(run))
                run.clear()
            pieces.append(MfCommand(unit))
        else:
            run.append(LATIN_CODES.get(unit) or f"{{char {unit:04X}}}")
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def text_notation(units: Sequence[int]) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(units)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Control units in order, without the line ends that follow text (which may move)."""
    skeleton: list[str] = []
    after_text = False
    for piece in pieces:
        if isinstance(piece, str):
            after_text = after_text or bool(piece)
            continue
        if not (piece.is_newline and after_text):
            skeleton.append(piece.notation)
        after_text = False
    return tuple(skeleton)


def command_skeleton(units: Sequence[int]) -> tuple[str, ...]:
    return notation_skeleton(split_text(units))


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and control units (``{char XXXX}`` stays inside the runs)."""
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
            if match is None:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Unknown or unmatched command at {text[index:]!r}",
                )
            command = MfCommand(int(match.group(1), 16))
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


def encode_text(text: str) -> tuple[int, ...]:
    """Units of a text run in the game's font (the Latin codes and ``{char XXXX}``)."""
    units = []
    index = 0
    while index < len(text):
        char = _NOTATION_CHAR.match(text, index)
        if char is not None:
            unit = int(char.group(1), 16)
            if is_command(unit) or unit == END:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{char.group(0)} is a control unit"
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


def pieces_units(pieces: Iterable[Piece]) -> tuple[int, ...]:
    units: list[int] = []
    for piece in pieces:
        if isinstance(piece, str):
            units.extend(encode_text(piece))
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


def line_widths(units: Sequence[int], font: MfFont) -> tuple[int, ...]:
    """The pixel width of every line: the glyphs' widths added up."""
    widths = [0]
    for unit in units:
        if unit in (NEWLINE, NEW_PAGE):
            widths.append(0)
        elif not is_command(unit):
            widths[-1] += font.width(unit)
    return tuple(widths)
