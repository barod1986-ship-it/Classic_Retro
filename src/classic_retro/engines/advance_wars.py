"""Text engine of *Advance Wars* (GBA).

A message is ASCII, one byte a character, with control codes, ended by 0x00:

- ``0D`` ends a line; ``0F`` waits for a key, then clears the box for the next
  page;
- ``15`` inserts the player's name (a string in RAM);
- ``16`` asks Yes/No after the text (``17``: No first; ``14`` as ``16``);
- ``09 xx`` draws an icon, ``0A xx`` and ``0B`` set printer options (``0B``
  takes a parameter only when it is 0x80..0x89), ``0C`` clears the box and
  ``0E`` pauses;
- ``80``..``83`` select the text colour.

Any other byte is a glyph of the font. Event scripts are commands of four
words; command ``0x19`` shows the message its second word points to, in the
dialogue box: a portrait on the left and two lines of text from tile column 7
of the box's map, 16 pixels a line.

The printer draws one character a frame. Before each character except the
first of a line it moves the pen one pixel (``0x08012C7C``), then draws the
glyph (``0x08052230``) into the current pair of 4bpp tiles (the top and
bottom halves of an 8x16 column) at the pen's offset inside it, spilling into
the next pair, and writes the pair into the tilemap as the pen reaches it
(``0x08012064``). The font has 256 glyphs, each with a pointer and a width in
two tables: 16 rows of (width + 1) / 2 bytes, two pixels a byte (the left one
in the low nibble), at most 8 pixels wide. Pixel 0xA takes the text colour;
0x4..0x7 are the shades around the strokes.

The notation writes printable ASCII as itself, ``0D`` as a line end, the
other control codes as ``{XX}`` or ``{XX YY}`` (hex) and any other byte as
``{char XX}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
END = 0x00
NEWLINE = 0x0D
PAGE = 0x0F
NAME = 0x15
YES_NO = 0x16
NO_YES = 0x17
CHOICES = frozenset({0x14, YES_NO, NO_YES})
COLOURS = frozenset(range(0x80, 0x84))
# Control codes; every other byte but 0x00 is a glyph.
COMMANDS = frozenset({*range(0x09, 0x10), *CHOICES, NAME, *COLOURS})
# The option code 0B takes its next byte only when that is 0x80..0x89.
OPTION = 0x0B
OPTION_PARAMETERS = range(0x80, 0x8A)
PARAMETER_COMMANDS = frozenset({0x09, 0x0A})

# The font: 256 glyph pointers, then 256 widths.
FONT_POINTERS = 0x083097F0
FONT_WIDTHS = 0x08309BF0
FONT_GLYPHS = 256
GLYPH_ROWS = 16
GLYPH_COLUMNS = 8
TILE = 8

_NOTATION_COMMAND = re.compile(r"\{([0-9A-Fa-f]{2})((?: [0-9A-Fa-f]{2})?)\}")
_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{2})\}")


class AdvanceWarsEngineAdapter(EngineAdapter):
    id = "gba.advance-wars"
    display_name = "Advance Wars GBA text engine"
    platform_ids = ("gba",)


@dataclass(frozen=True, slots=True)
class AwCommand:
    """A control code with its parameter, if any."""

    data: bytes

    @property
    def code(self) -> int:
        return self.data[0]

    @property
    def is_newline(self) -> bool:
        return self.code == NEWLINE

    @property
    def notation(self) -> str:
        if self.is_newline:
            return "\n"
        return "{" + self.data.hex(" ").upper() + "}"


Piece = str | AwCommand


def command_length(data: bytes, index: int) -> int:
    """Length of the control code at ``index``."""
    code = data[index]
    if code in PARAMETER_COMMANDS or (
        code == OPTION and index + 1 < len(data) and data[index + 1] in OPTION_PARAMETERS
    ):
        if index + 2 > len(data):
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION, f"Command {code:02X} cut short at {index}"
            )
        return 2
    return 1


def message_text(data: bytes, start: int) -> bytes:
    """The message at ``start``, without its final 0x00."""
    index = start
    while index < len(data):
        byte = data[index]
        if byte == END:
            return bytes(data[start:index])
        index += command_length(data, index) if byte in COMMANDS else 1
    raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, f"No end after {start:#x}")


def read_message(rom: bytes, address: int) -> bytes:
    offset = address - ROM_BASE
    if not 0 <= offset < len(rom):
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside the image")
    return message_text(rom, offset)


def split_text(body: bytes) -> tuple[Piece, ...]:
    """Text runs and control codes of a message."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(body):
        byte = body[index]
        if byte in COMMANDS:
            if run:
                pieces.append("".join(run))
                run.clear()
            length = command_length(body, index)
            pieces.append(AwCommand(bytes(body[index : index + length])))
            index += length
            continue
        run.append(chr(byte) if 0x20 <= byte < 0x7F and chr(byte) not in "{}" else _char(byte))
        index += 1
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def _char(byte: int) -> str:
    return f"{{char {byte:02X}}}"


def text_notation(body: bytes) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(body)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Control codes in order, without the line ends that follow text (which may move)."""
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


def command_skeleton(body: bytes) -> tuple[str, ...]:
    return notation_skeleton(split_text(body))


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and control codes (``{char XX}`` stays inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            command = AwCommand(bytes((NEWLINE,)))
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
                    ErrorCode.UNENCODABLE_TEXT, f"Unknown or unmatched command at {text[index:]!r}"
                )
            data = bytes(int(part, 16) for part in (match.group(1) + match.group(2)).split())
            takes_parameter = data[0] in PARAMETER_COMMANDS or (
                data[0] == OPTION and len(data) == 2 and data[1] in OPTION_PARAMETERS
            )
            if data[0] not in COMMANDS or len(data) != (2 if takes_parameter else 1):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{match.group(0)} is not a control code"
                )
            command = AwCommand(data)
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


def encode_text(text: str) -> bytes:
    """Bytes of a text run in the game's font (ASCII and ``{char XX}``)."""
    data = bytearray()
    index = 0
    while index < len(text):
        char = _NOTATION_CHAR.match(text, index)
        if char is not None:
            data.append(int(char.group(1), 16))
            index = char.end()
            continue
        code = ord(text[index])
        if not 0x20 <= code < 0x7F:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"The Advance Wars font has no {text[index]!r}"
            )
        data.append(code)
        index += 1
    return bytes(data)


def text_bytes(pieces: Iterable[Piece]) -> bytes:
    return b"".join(
        encode_text(piece) if isinstance(piece, str) else piece.data for piece in pieces
    )


Pixels = tuple[tuple[int, ...], ...]


def glyph_pixels(data: bytes, width: int) -> Pixels:
    """16 rows of ``width`` pixels from the font's packed rows."""
    per_row = (width + 1) // 2
    return tuple(
        tuple(data[y * per_row + x // 2] >> 4 * (x % 2) & 0xF for x in range(width))
        for y in range(GLYPH_ROWS)
    )


@dataclass(frozen=True, slots=True)
class AwFont:
    """The game's 256 glyphs: widths and pixels."""

    widths: tuple[int, ...]
    glyphs: tuple[Pixels, ...]

    @classmethod
    def read(cls, rom: bytes, pointers: int = FONT_POINTERS, widths: int = FONT_WIDTHS) -> AwFont:
        table = struct.unpack_from(f"<{FONT_GLYPHS}I", rom, pointers - ROM_BASE)
        sizes = tuple(rom[widths - ROM_BASE : widths - ROM_BASE + FONT_GLYPHS])
        glyphs = []
        for pointer, width in zip(table, sizes, strict=True):
            if width > GLYPH_COLUMNS:
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED, f"A glyph {width} pixels wide is not 1..8"
                )
            start = pointer - ROM_BASE
            if not 0 <= start < len(rom):
                raise ClassicRetroError(
                    ErrorCode.INVALID_REFERENCE, f"Glyph pointer {pointer:#x} is outside the image"
                )
            length = GLYPH_ROWS * ((width + 1) // 2)
            glyphs.append(glyph_pixels(rom[start : start + length], width))
        return cls(sizes, tuple(glyphs))


def line_widths(body: bytes, font: AwFont) -> tuple[int, ...]:
    """The pixel width of every line as the printer lays it out (a pixel between glyphs)."""
    widths = [0]
    first = True
    for piece in split_text(body):
        if isinstance(piece, AwCommand):
            if piece.is_newline or piece.code == PAGE:
                widths.append(0)
                first = True
            continue
        for code in encode_text(piece):
            widths[-1] += font.widths[code] + (0 if first else 1)
            first = False
    return tuple(widths)
