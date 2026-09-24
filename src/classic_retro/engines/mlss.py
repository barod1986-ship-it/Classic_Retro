"""Text engine of *Mario & Luigi: Superstar Saga* (GBA).

Story messages are reached through a table of five pointers per message, one
per language, English first (the USA image carries all five). A message is:

- two header bytes: the width of its widest line and the height of its
  tallest page, in 8-pixel tiles; the game sizes the speech bubble or the
  subtitle box from them;
- the text: every byte is a character of the printer's font except ``0xFF``,
  which starts a command of two bytes (``FF xx``), or three for ``xx`` = 0x01
  and 0x0B..0x11 (``FF xx yy``). ``FF 00`` ends a line, ``FF 01 00`` starts a
  new page, ``FF 0A`` ends the message, ``FF 0C nn`` waits ``nn`` frames,
  ``FF 11 01`` waits for a key, ``FF 2n`` sets the colour, ``FF 3n`` the size
  (bit 0 double height, bit 1 double width), ``FF 34``..``FF 36`` the
  alignment of the next lines (left, centre, right), ``FF 4n`` the font list,
  ``FF 5n`` the width of a space;
- zeros up to the next word boundary (at least one: the measuring pass of the
  game stops at a zero byte).

The glyph printer (``0x08199624``) draws one character per call into a 4bpp
tile buffer. Its font list holds six fonts: a byte ``0xFA``..``0xFE`` before a
character selects font 5..1 (all empty in the USA image), any other character
uses font 0. A font is a word whose low byte gives the cell (bits 4-7: width
in 4-pixel units, bits 0-3: height in 4-pixel units), 256 width nibbles
(width - 1, eight per word) and 256 glyphs of two bitplanes (see
``glyph_bytes``); an ink pixel of plane 0 takes the text colour, a pixel of
both planes the colour after it.

The notation writes printable ASCII as itself, ``FF 00`` as a line end and
other commands as ``{FF xx}`` / ``{FF xx yy}`` (hex); any other byte is
``{char XX}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
COMMAND = 0xFF
NEWLINE = 0x00
PAGE = 0x01
END = 0x0A
KEY_WAIT = 0x11
# Commands with a parameter byte: FF 01 xx and FF 0B..FF 11 xx.
PARAMETER_COMMANDS = frozenset({0x01, *range(0x0B, 0x12)})
# A byte FA..FE before a character selects font 5..1 of the printer's list.
FONT_PREFIXES = range(0xFA, 0xFF)
LANGUAGES = 5
GROUP_BYTES = 4 * LANGUAGES
HEADER_BYTES = 2
TILE = 8
FONT_GLYPHS = 256
WIDTH_TABLE_BYTES = FONT_GLYPHS // 2
GLYPHS_OFFSET = 4 + WIDTH_TABLE_BYTES
# The space width of the dialogue printers until an FF 5n changes it.
DEFAULT_SPACE = 6

_NOTATION_COMMAND = re.compile(r"\{FF((?: [0-9A-Fa-f]{2}){1,2})\}")
_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{2})\}")


class MlssEngineAdapter(EngineAdapter):
    id = "gba.mlss"
    display_name = "Mario & Luigi: Superstar Saga GBA text engine"
    platform_ids = ("gba",)


@dataclass(frozen=True, slots=True)
class MlssCommand:
    """A command (``FF xx`` or ``FF xx yy``) with its bytes."""

    data: bytes

    @property
    def code(self) -> int:
        return self.data[1]

    @property
    def is_newline(self) -> bool:
        return self.code == NEWLINE

    @property
    def is_page(self) -> bool:
        return self.code == PAGE

    @property
    def is_end(self) -> bool:
        return self.code == END

    @property
    def notation(self) -> str:
        if self.is_newline:
            return "\n"
        return "{" + self.data.hex(" ").upper() + "}"


Piece = str | MlssCommand


def command_length(data: bytes, index: int) -> int:
    """Length of the command at ``index`` (``data[index]`` is ``0xFF``)."""
    if index + 1 >= len(data):
        raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, f"Command cut short at {index}")
    length = 3 if data[index + 1] in PARAMETER_COMMANDS else 2
    if index + length > len(data):
        raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, f"Command cut short at {index}")
    return length


def message_body(data: bytes, start: int) -> bytes:
    """The text at ``start``, up to and including its ``FF 0A``."""
    index = start
    while index < len(data):
        if data[index] == COMMAND:
            length = command_length(data, index)
            index += length
            if data[index - length + 1] == END:
                return data[start:index]
            continue
        if data[index] == 0:
            break
        index += 1
    raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"Message at {start} has no FF 0A")


@dataclass(frozen=True, slots=True)
class MlssMessage:
    """A message: its two header bytes and its text (``FF 0A`` included)."""

    width_tiles: int
    height_tiles: int
    body: bytes

    @classmethod
    def read(cls, rom: bytes, address: int) -> MlssMessage:
        start = address - ROM_BASE
        if not 0 <= start <= len(rom) - HEADER_BYTES:
            raise ClassicRetroError(
                ErrorCode.REFERENCE_OUT_OF_BOUNDS, f"No message at {address:#x}"
            )
        return cls(rom[start], rom[start + 1], message_body(rom, start + HEADER_BYTES))

    @property
    def header(self) -> bytes:
        return bytes((self.width_tiles, self.height_tiles))

    @property
    def data(self) -> bytes:
        return self.header + self.body

    def stored(self) -> bytes:
        """The message as stored: a zero, then zeros up to a word boundary."""
        data = self.data + b"\0"
        return data + bytes(-len(data) % 4)


def split_text(body: bytes) -> tuple[Piece, ...]:
    """Text runs and commands of a message text."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(body):
        byte = body[index]
        if byte == COMMAND:
            if run:
                pieces.append("".join(run))
                run.clear()
            length = command_length(body, index)
            pieces.append(MlssCommand(body[index : index + length]))
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
    """Commands in order, without the line ends that follow text (which may move).

    A line end after a command or at the start is part of the layout (the
    subtitles start every page with an empty line) and is kept.
    """
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
    """Notation as text runs and commands (``{char XX}`` stays inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            command: MlssCommand | None = MlssCommand(bytes((COMMAND, NEWLINE)))
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
            data = bytes((COMMAND, *(int(part, 16) for part in match.group(1).split())))
            if len(data) != (3 if data[1] in PARAMETER_COMMANDS else 2):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"{match.group(0)} has the wrong length for command {data[1]:02X}",
                )
            command = MlssCommand(data)
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
    """Bytes of a text run in the game's own fonts (ASCII and ``{char XX}``)."""
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
                ErrorCode.UNENCODABLE_TEXT, f"The MLSS fonts have no {text[index]!r}"
            )
        data.append(code)
        index += 1
    return bytes(data)


def text_bytes(pieces: Iterable[Piece]) -> bytes:
    return b"".join(
        encode_text(piece) if isinstance(piece, str) else piece.data for piece in pieces
    )


def glyph_bytes(pixels: Sequence[Sequence[int]], cell_width: int, cell_height: int) -> bytes:
    """A glyph as the printer reads it.

    Pixel values are 0 (none), 1 (plane 0: the text colour) and 3 (both planes:
    the next colour). Columns go by eight: for each group of four rows, a word
    of plane 0 then a word of plane 1, where nibble ``x`` is column ``x`` and
    bit ``k`` of the nibble row ``k`` of the group. The first eight columns
    come first, then the next eight (a 12-pixel cell stores its last four
    columns in half-words: plane 0 in the low one).
    """
    if cell_width not in (8, 12, 16) or cell_height % 4 or not 4 <= cell_height <= 16:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Unsupported MLSS glyph cell")
    if len(pixels) != cell_height or any(len(row) != cell_width for row in pixels):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Glyph does not match its cell")
    data = bytearray()
    for first, columns in ((0, 8), (8, cell_width - 8)):
        if columns <= 0:
            continue
        for group in range(0, cell_height, 4):
            planes = [0, 0]
            for x in range(columns):
                for k in range(4):
                    value = pixels[group + k][first + x]
                    if value not in (0, 1, 3):
                        raise ClassicRetroError(
                            ErrorCode.FONT_BUILD_FAILED, f"Pixel value {value} is not 0, 1 or 3"
                        )
                    for plane in (0, 1):
                        if value >> plane & 1:
                            planes[plane] |= 1 << (4 * x + k)
            if columns == 4:
                data += struct.pack("<HH", *planes)
            else:
                data += struct.pack("<II", *planes)
    return bytes(data)


def glyph_pixels(data: bytes, cell_width: int, cell_height: int) -> tuple[tuple[int, ...], ...]:
    """Inverse of ``glyph_bytes``."""
    rows = [[0] * cell_width for _ in range(cell_height)]
    offset = 0
    for first, columns in ((0, 8), (8, cell_width - 8)):
        if columns <= 0:
            continue
        for group in range(0, cell_height, 4):
            if columns == 4:
                planes = struct.unpack_from("<HH", data, offset)
                offset += 4
            else:
                planes = struct.unpack_from("<II", data, offset)
                offset += 8
            for x in range(columns):
                for k in range(4):
                    value = (planes[0] >> (4 * x + k) & 1) | (planes[1] >> (4 * x + k) & 1) << 1
                    rows[group + k][first + x] = value
    return tuple(tuple(row) for row in rows)


@dataclass(frozen=True, slots=True)
class MlssFont:
    """A printer font: cell size, advance of every code and glyph data."""

    cell_width: int
    cell_height: int
    widths: tuple[int, ...]
    glyphs: tuple[bytes, ...]

    @property
    def glyph_size(self) -> int:
        return self.cell_width * self.cell_height // 4

    @classmethod
    def read(cls, rom: bytes, address: int) -> MlssFont:
        start = address - ROM_BASE
        if not 0 <= start <= len(rom) - GLYPHS_OFFSET:
            raise ClassicRetroError(ErrorCode.REFERENCE_OUT_OF_BOUNDS, f"No font at {address:#x}")
        (header,) = struct.unpack_from("<I", rom, start)
        cell_width, cell_height = (header >> 4 & 0xF) * 4, (header & 0xF) * 4
        if header >> 8 or cell_width not in (8, 12, 16) or cell_height not in (4, 8, 12, 16):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"No MLSS font header at {address:#x}"
            )
        nibbles = struct.unpack_from("<32I", rom, start + 4)
        widths = tuple((nibbles[code >> 3] >> 4 * (code & 7) & 0xF) + 1 for code in range(256))
        size = cell_width * cell_height // 4
        glyphs_start = start + GLYPHS_OFFSET
        if glyphs_start + FONT_GLYPHS * size > len(rom):
            raise ClassicRetroError(ErrorCode.REFERENCE_OUT_OF_BOUNDS, "Font runs past the image")
        glyphs = tuple(
            rom[glyphs_start + code * size : glyphs_start + (code + 1) * size]
            for code in range(FONT_GLYPHS)
        )
        return cls(cell_width, cell_height, widths, glyphs)

    def pixels(self, code: int) -> tuple[tuple[int, ...], ...]:
        return glyph_pixels(self.glyphs[code], self.cell_width, self.cell_height)

    def pack(self) -> bytes:
        if len(self.widths) != FONT_GLYPHS or len(self.glyphs) != FONT_GLYPHS:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A font holds 256 glyphs")
        if any(not 1 <= width <= 16 for width in self.widths):
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Advances are 1..16 pixels")
        if any(len(glyph) != self.glyph_size for glyph in self.glyphs):
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Glyph data has the wrong size")
        data = bytearray(struct.pack("<I", self.cell_width // 4 << 4 | self.cell_height // 4))
        for first in range(0, FONT_GLYPHS, 8):
            word = 0
            for code in range(first, first + 8):
                word |= self.widths[code] - 1 << 4 * (code - first)
            data += struct.pack("<I", word)
        for glyph in self.glyphs:
            data += glyph
        return bytes(data)


@dataclass(frozen=True, slots=True)
class MlssLayout:
    """What the header describes: every line's width and every page's height."""

    line_widths: tuple[int, ...]
    page_heights: tuple[int, ...]

    @property
    def width(self) -> int:
        return max(self.line_widths, default=0)

    @property
    def height(self) -> int:
        return max(self.page_heights, default=0)

    def header(self) -> tuple[int, int]:
        return -(-self.width // TILE), -(-self.height // TILE)


def measure_text(
    body: bytes, fonts: Sequence[MlssFont | None], *, space: int = DEFAULT_SPACE
) -> MlssLayout:
    """Lay a message text out like the game's measuring pass (letter spacing 0).

    ``fonts`` is the printer's font list: ``fonts[0]`` for plain characters,
    ``fonts[n]`` after a prefix byte ``0xFF - n``. A line is as tall as its
    tallest glyph (at least font 0's cell); a page ends at ``FF 01``.
    """
    base = fonts[0]
    if base is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Font 0 is required")
    widths: list[int] = []
    heights: list[int] = []
    x = widest = 0
    line_height = base.cell_height
    page_height = 0
    double_width = double_height = 0
    index = 0
    while index < len(body):
        byte = body[index]
        if byte == COMMAND:
            length = command_length(body, index)
            code = body[index + 1]
            if code in (NEWLINE, PAGE, END):
                widths.append(widest)
                page_height += line_height
                x = widest = 0
                line_height = base.cell_height
                if code != NEWLINE:
                    heights.append(page_height)
                    page_height = 0
                if code == END:
                    return MlssLayout(tuple(widths), tuple(heights))
            elif 0x30 <= code <= 0x33:
                double_height, double_width = code & 1, code >> 1 & 1
            elif 0x50 <= code <= 0x5F:
                space = code & 0xF
            elif 0x60 <= code <= 0x7F:
                x += code - 0x5F
            elif 0x80 <= code <= 0x9F:
                x -= code - 0x7F
            widest = max(widest, x)
            index += length
            continue
        if byte == 0x20:
            x += space
        else:
            font = base
            if byte in FONT_PREFIXES and fonts[COMMAND - byte] is not None:
                font = fonts[COMMAND - byte]
                index += 1
                if index >= len(body):
                    break
                byte = body[index]
            assert font is not None
            x += font.widths[byte] << double_width
            line_height = max(line_height, font.cell_height << double_height)
        widest = max(widest, x)
        index += 1
    raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "Message text has no FF 0A")
