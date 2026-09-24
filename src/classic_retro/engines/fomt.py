"""Text engine of *Harvest Moon: Friends of Mineral Town* (GBA).

Dialogue lives in two places:

- **event scripts**: a table of pointers to RIFF files of form ``SCR `` whose
  ``CODE`` chunk is the bytecode and whose ``STR `` chunk holds the strings
  (a count, an offset per string from the end of the offset table, then
  NUL-terminated strings). The game's RIFF size field counts the whole file,
  header included, and its loader does not pad chunks;
- **story scenes** such as the opening's flashback: NUL-terminated strings
  and speaker names reached through the literal pools of their code.

A string is ASCII with a few control bytes: ``0x05`` waits for a key,
``0x0C`` clears the box, ``0x0D`` returns to the start of the line and
``0x0A`` goes down a line (the game writes ``0D 0A`` between lines; a line
feed on the last of the box's three lines scrolls it). A character the font
cannot draw on its own (the game's glyph routine returns 0) is the lead byte
of a pair: Shift-JIS pairs such as ``81 49`` (a full-width ``!``), and the
placeholders expanded when drawn. Scripts write the player's name as
``FF 21`` (``FF 21``..``FF 2D`` name the player, the farm, the dog...); the
story scenes' expander takes a lone ``FF``, so ``FF`` followed by ``?`` is the
name and a question mark there.

The text box draws fixed 8-pixel cells into sprites: each of its three
lines is seven 32x16 sprites, 28 cells, and the cursor wraps at 28. Every
glyph is two tiles tall: the game unpacks 1bpp glyphs (12 rows, drawn from
row 2) into 4bpp tiles, colour 1 for the ink and colour 2 for a shadow one
pixel to the right and one down-right.

The notation writes printable ASCII as itself, ``0D 0A`` as a line end, and
``{wait}``, ``{clear}``, ``{name}`` (the player's name) for the rest; any
other byte is ``{XX}`` (hex), a Shift-JIS pair ``{XX XX}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
END = 0x00
WAIT = 0x05
LINE_FEED = 0x0A
CLEAR = 0x0C
CARRIAGE_RETURN = 0x0D
PLACEHOLDER = 0xFF
# FF 21: the player's name in event scripts.
SCRIPT_NAME_CODE = 0x21
BOX_COLUMNS = 28
BOX_LINES = 3
CELL_WIDTH = 8
CELL_HEIGHT = 16
INK = 1
SHADOW = 2
# The pixels a glyph's ink shadows, relative to it.
SHADOW_OFFSETS = ((1, 0), (1, 1))

_SJIS_LEADS = frozenset(range(0x81, 0xA0)) | frozenset(range(0xE0, 0xEB))
_NOTATION_TOKEN = re.compile(r"\{([^{}]*)\}")


class FomtEngineAdapter(EngineAdapter):
    id = "gba.fomt"
    display_name = "Harvest Moon: Friends of Mineral Town GBA text engine"
    platform_ids = ("gba",)


class PlaceholderStyle(Enum):
    """How a text's name placeholder is written."""

    SCRIPT = "script"  # FF 21
    STORY = "story"  # a lone FF


@dataclass(frozen=True, slots=True)
class FomtCommand:
    """A control code of a string, with its bytes."""

    data: bytes
    notation: str

    @property
    def is_newline(self) -> bool:
        return self.notation == "\n"


WAIT_COMMAND = FomtCommand(bytes([WAIT]), "{wait}")
CLEAR_COMMAND = FomtCommand(bytes([CLEAR]), "{clear}")
NEWLINE_COMMAND = FomtCommand(bytes([CARRIAGE_RETURN, LINE_FEED]), "\n")

Piece = str | FomtCommand


def name_command(style: PlaceholderStyle) -> FomtCommand:
    if style is PlaceholderStyle.SCRIPT:
        return FomtCommand(bytes([PLACEHOLDER, SCRIPT_NAME_CODE]), "{name}")
    return FomtCommand(bytes([PLACEHOLDER]), "{name}")


def _hex(data: bytes) -> str:
    return "{" + data.hex(" ").upper() + "}"


def split_text(data: bytes, style: PlaceholderStyle) -> tuple[Piece, ...]:
    """Split a string (without its NUL) into text runs and commands."""
    pieces: list[Piece] = []
    text: list[str] = []

    def command(item: FomtCommand) -> None:
        if text:
            pieces.append("".join(text))
            text.clear()
        pieces.append(item)

    index = 0
    while index < len(data):
        byte = data[index]
        if byte == END:
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION, f"NUL inside a string at {index}"
            )
        if byte == WAIT:
            command(WAIT_COMMAND)
        elif byte == CLEAR:
            command(CLEAR_COMMAND)
        elif byte == CARRIAGE_RETURN and data[index + 1 : index + 2] == bytes([LINE_FEED]):
            command(NEWLINE_COMMAND)
            index += 1
        elif byte == PLACEHOLDER:
            if style is PlaceholderStyle.STORY:
                command(name_command(style))
            elif index + 1 < len(data):
                code = data[index + 1]
                command(
                    name_command(style)
                    if code == SCRIPT_NAME_CODE
                    else FomtCommand(data[index : index + 2], _hex(data[index : index + 2]))
                )
                index += 1
            else:
                raise ClassicRetroError(
                    ErrorCode.TOKEN_ORDER_VIOLATION, f"Placeholder cut short at {index}"
                )
        elif byte in _SJIS_LEADS and index + 1 < len(data):
            text.append(_hex(data[index : index + 2]))
            index += 1
        elif 0x20 <= byte < 0x7F and chr(byte) not in "{}":
            text.append(chr(byte))
        else:
            command(FomtCommand(data[index : index + 1], _hex(data[index : index + 1])))
        index += 1
    if text:
        pieces.append("".join(text))
    return tuple(pieces)


def text_notation(pieces: Iterable[Piece]) -> str:
    return "".join(piece if isinstance(piece, str) else piece.notation for piece in pieces)


def command_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """The commands in order, line ends excluded (a translation may move them)."""
    return tuple(
        piece.notation
        for piece in pieces
        if isinstance(piece, FomtCommand) and not piece.is_newline
    )


def parse_notation(notation: str, style: PlaceholderStyle) -> tuple[Piece, ...]:
    """Pieces of a translation: text, line ends and ``{wait}``/``{clear}``/``{name}``."""
    known = {"wait": WAIT_COMMAND, "clear": CLEAR_COMMAND, "name": name_command(style)}
    pieces: list[Piece] = []
    for number, line in enumerate(notation.split("\n")):
        if number:
            pieces.append(NEWLINE_COMMAND)
        position = 0
        for match in _NOTATION_TOKEN.finditer(line):
            if match.start() > position:
                pieces.append(line[position : match.start()])
            token = match.group(1)
            if token not in known:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command {{{token}}}"
                )
            pieces.append(known[token])
            position = match.end()
        if position < len(line):
            pieces.append(line[position:])
    for piece in pieces:
        if isinstance(piece, str) and ("{" in piece or "}" in piece):
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"Stray brace in {piece!r}")
    return tuple(pieces)


def read_string(data: bytes, offset: int) -> bytes:
    """The NUL-terminated string at ``offset`` (without its NUL)."""
    end = data.find(b"\0", offset)
    if end < 0:
        raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"No NUL after {offset:#x}")
    return data[offset:end]


# ---------------------------------------------------------------------------
# Event scripts (RIFF "SCR ")

RIFF = b"RIFF"
SCRIPT_FORM = b"SCR "
CODE_CHUNK = b"CODE"
STRING_CHUNK = b"STR "


@dataclass(frozen=True, slots=True)
class FomtScript:
    """An event script: its chunks in order (name, data)."""

    chunks: tuple[tuple[bytes, bytes], ...]

    @classmethod
    def read(cls, data: bytes, offset: int) -> FomtScript:
        if data[offset : offset + 4] != RIFF or data[offset + 8 : offset + 12] != SCRIPT_FORM:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"No RIFF SCR file at {offset:#x}"
            )
        (size,) = struct.unpack_from("<I", data, offset + 4)
        chunks: list[tuple[bytes, bytes]] = []
        position = 12
        # The game's loader reads chunk headers while the offset is within the
        # size (which counts the whole file) and adds no padding.
        while position + 8 <= size:
            name = data[offset + position : offset + position + 4]
            (length,) = struct.unpack_from("<I", data, offset + position + 4)
            start = offset + position + 8
            if position + 8 + length > size:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_BASELINE_MISMATCH, f"Chunk {name!r} passes the end of the file"
                )
            chunks.append((bytes(name), bytes(data[start : start + length])))
            position += 8 + length
        if position != size:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, "RIFF chunks do not fill the file"
            )
        return cls(tuple(chunks))

    def chunk(self, name: bytes) -> bytes:
        for chunk_name, data in self.chunks:
            if chunk_name == name:
                return data
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"No {name!r} chunk")

    @property
    def strings(self) -> tuple[bytes, ...]:
        data = self.chunk(STRING_CHUNK)
        (count,) = struct.unpack_from("<I", data, 0)
        base = 4 + 4 * count
        offsets = struct.unpack_from(f"<{count}I", data, 4)
        return tuple(read_string(data, base + offset) for offset in offsets)

    def with_strings(self, strings: Sequence[bytes]) -> FomtScript:
        """The same script with a new string chunk (the code keeps its indices)."""
        if len(strings) != len(self.strings):
            raise ClassicRetroError(
                ErrorCode.RESOURCE_SET_MISMATCH,
                f"A script with {len(self.strings)} strings cannot take {len(strings)}",
            )
        offsets: list[int] = []
        text = bytearray()
        for string in strings:
            if b"\0" in string:
                raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "A string cannot hold NUL")
            offsets.append(len(text))
            text += string + b"\0"
        if len(text) % 2:
            text.append(0)
        chunk = struct.pack(f"<I{len(strings)}I", len(strings), *offsets) + bytes(text)
        return FomtScript(
            tuple((name, chunk if name == STRING_CHUNK else data) for name, data in self.chunks)
        )

    def to_bytes(self) -> bytes:
        body = SCRIPT_FORM + b"".join(
            name + struct.pack("<I", len(data)) + data for name, data in self.chunks
        )
        return RIFF + struct.pack("<I", 8 + len(body)) + body
