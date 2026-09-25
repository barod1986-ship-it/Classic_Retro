"""Text engine of *Tactics Ogre: The Knight of Lodis* (GBA).

A scene's text is a block. The table at ``SCENE_TEXTS`` holds, for each of
its ``SCENES`` entries, the block's offset from the table; the scene's script
reads its entry (several entries can share a block). A block starts with a
table of 16-bit offsets from the block's start, one for each message, ended
by ``FFFF``. A message is a 16-bit header, whose bits 4 and 5 give the lines
of a page (``lines_per_page``), then its bytes up to ``FF``:

- ``00``..``7F`` are glyphs of the font (``FONT_WIDTHS``, ``FONT_GLYPHS``):
  ``A``..``Z`` from ``00``, ``a``..``z`` from ``1A``, ``0``..``9`` from ``34``,
  then punctuation (``LATIN_CODES``);
- ``88`` ends a line and ``89`` is a space, 6 pixels wide;
- ``8A`` starts a new page; ``8B`` shows what follows at once (a speaker's
  name, on the first line) and ``8C`` goes back to the typewriter; ``8E``
  waits for A before the next page and ``8D`` at the end of the message; the
  other bytes up to ``91`` are flags of one byte;
- ``80``, ``81``, ``82``, ``83``, ``84``, ``86`` and ``87`` take the next byte:
  ``80xx`` draws name ``xx`` from RAM (the player's), ``81xx`` icon ``xx`` and
  ``87xx`` name ``xx`` of the list at ``NAME_LIST`` (the characters' names);
- ``85`` starts a choice, whose options follow as texts of their own; this
  notation does not read it, nor any byte from ``92`` to ``FE``, which the
  game's routines do not read either.

The dialogue routines (``0x08015188``, one byte a frame) draw a glyph at a
time with ``0x0801B0C8``, from the left of a line, into columns of two 8x8
tiles; a hook can place it elsewhere. The window's width is its longest line,
measured by ``0x080143E0`` with the widths of the font, rounded up to whole
columns.

The notation writes the Latin codes as ASCII, ``88`` as a line end, ``89`` as
a space, the other commands as ``{XX}`` or ``{XXYY}`` (hex) and any other
glyph as ``{char XX}``.
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
END = 0xFF
NEWLINE = 0x88
SPACE = 0x89
NEW_PAGE = 0x8A
INSTANT = 0x8B
TYPED = 0x8C
LAST_WAIT = 0x8D
PAGE_WAIT = 0x8E
RAM_NAME = 0x80
ICON = 0x81
CHOICE = 0x85
NAME = 0x87
GLYPH_CODES = 0x80
# Commands that take the next byte, and those of one byte.
ARGUMENT_COMMANDS = frozenset((0x80, 0x81, 0x82, 0x83, 0x84, 0x86, 0x87))
FLAG_COMMANDS = frozenset(range(NEW_PAGE, 0x92))
# Commands that break or wait: the others act inside a line.
_BREAKS = frozenset((NEWLINE, NEW_PAGE, LAST_WAIT, PAGE_WAIT))
TABLE_END = 0xFFFF

SCENE_TEXTS = 0x08784298
SCENES = 70
NAME_LIST = 0x086254D8
FONT_WIDTHS = 0x0815DE6C
FONT_GLYPHS = 0x0815DEC4
GLYPH_ROWS = 16
GLYPH_COLUMNS = 8
GLYPH_BYTES = GLYPH_ROWS * GLYPH_COLUMNS // 2
SPACE_WIDTH = 6
INK = 1
SOFT = 2

LATIN_CODES: dict[int, str] = {
    **{code: chr(ord("A") + code) for code in range(26)},
    **{0x1A + code: chr(ord("a") + code) for code in range(26)},
    **{0x34 + digit: str(digit) for digit in range(10)},
    **dict(zip(range(0x3E, 0x50), "!?.,:&_%'()<>+-*/=", strict=True)),
    0x51: '"',
    0x52: "…",
}
_LATIN = {character: code for code, character in LATIN_CODES.items()}

_NOTATION_CHAR = re.compile(r"\{char ([0-9A-Fa-f]{2})\}")
_NOTATION_COMMAND = re.compile(r"\{([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})?\}")


class TacticsOgreEngineAdapter(EngineAdapter):
    id = "gba.tactics-ogre"
    display_name = "Tactics Ogre: The Knight of Lodis GBA text engine"
    platform_ids = ("gba",)


@dataclass(frozen=True, slots=True)
class ToCommand:
    """A command: a line end, a page, a wait, a speed, a name, an icon or a flag."""

    code: int
    argument: int | None = None

    def __post_init__(self) -> None:
        takes_argument = self.code in ARGUMENT_COMMANDS
        if not (takes_argument or self.code in FLAG_COMMANDS or self.code == NEWLINE) or (
            takes_argument != (self.argument is not None)
        ):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{self.code:02X} is not a command here"
            )

    @property
    def is_newline(self) -> bool:
        return self.code == NEWLINE

    @property
    def is_inline(self) -> bool:
        """A command inside a line (a speed, a name, an icon, a flag): no break or wait."""
        return self.code not in _BREAKS

    @property
    def data(self) -> bytes:
        return bytes((self.code,) if self.argument is None else (self.code, self.argument))

    @property
    def notation(self) -> str:
        if self.is_newline:
            return "\n"
        return "{" + self.data.hex().upper() + "}"


Piece = str | ToCommand


def lines_per_page(header: int) -> int:
    """The lines of a page of a message with this header (bits 4 and 5)."""
    return header >> 4 & 3


@dataclass(frozen=True, slots=True)
class ToBlock:
    """A scene's block: where it is and each message's offset from it."""

    address: int
    offsets: tuple[int, ...]

    def message_address(self, index: int) -> int:
        return self.address + self.offsets[index]


def _offset(rom: bytes, address: int, length: int = 1) -> int:
    offset = address - ROM_BASE
    if not 0 <= offset <= len(rom) - length:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"{address:#x} is outside the image")
    return offset


def scene_block_address(rom: bytes, scene: int) -> int:
    """Where the block of scene entry ``scene`` is."""
    if not 0 <= scene < SCENES:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No scene entry {scene}")
    entry = SCENE_TEXTS + 4 * scene
    return SCENE_TEXTS + struct.unpack_from("<I", rom, _offset(rom, entry, 4))[0]


def read_block(rom: bytes, address: int) -> ToBlock:
    """A block's message offsets, up to the table's ``FFFF``."""
    offsets = []
    start = _offset(rom, address, 2)
    while True:
        (offset,) = struct.unpack_from("<H", rom, start + 2 * len(offsets))
        if offset == TABLE_END:
            return ToBlock(address, tuple(offsets))
        offsets.append(offset)
        if len(offsets) > 0x800:
            raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No block at {address:#x}")


def text_bytes(data: bytes, offset: int) -> bytes:
    """The bytes from ``offset`` up to (without) the final ``FF``."""
    index = offset
    while index < len(data):
        code = data[index]
        if code == END:
            return bytes(data[offset:index])
        index += 2 if code in ARGUMENT_COMMANDS else 1
    raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, f"No end after {offset:#x}")


def read_message(rom: bytes, address: int) -> tuple[int, bytes]:
    """A message's header and its bytes up to (without) the final ``FF``."""
    start = _offset(rom, address, 2)
    (header,) = struct.unpack_from("<H", rom, start)
    return header, text_bytes(rom, start + 2)


def read_name(rom: bytes, index: int) -> bytes:
    """Name ``index`` of the list the ``87xx`` command reads, up to its ``FF``."""
    pointer = NAME_LIST + 4 * index
    (address,) = struct.unpack_from("<I", rom, _offset(rom, pointer, 4))
    return text_bytes(rom, _offset(rom, address))


def split_text(data: bytes) -> tuple[Piece, ...]:
    """Text runs and commands."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(data):
        code = data[index]
        if code < GLYPH_CODES:
            run.append(LATIN_CODES.get(code) or f"{{char {code:02X}}}")
            index += 1
            continue
        if code == SPACE:
            run.append(" ")
            index += 1
            continue
        if code in ARGUMENT_COMMANDS:
            if index + 1 >= len(data):
                raise ClassicRetroError(
                    ErrorCode.TOKEN_ORDER_VIOLATION, f"{code:02X} without its byte"
                )
            command = ToCommand(code, data[index + 1])
        elif code == NEWLINE or code in FLAG_COMMANDS:
            command = ToCommand(code)
        else:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{code:02X} is not supported"
            )
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(command)
        index += len(command.data)
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def text_notation(data: bytes) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(data)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Commands in order, without the line ends that follow text (which may move).

    A line end still follows text across inline commands (a speed, a name).
    """
    skeleton: list[str] = []
    after_text = False
    for piece in pieces:
        if isinstance(piece, str):
            after_text = after_text or bool(piece)
            continue
        if not (piece.is_newline and after_text):
            skeleton.append(piece.notation)
        if not piece.is_inline:
            after_text = False
    return tuple(skeleton)


def command_skeleton(data: bytes) -> tuple[str, ...]:
    return notation_skeleton(split_text(data))


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and commands (``{char XX}`` stays inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            command = ToCommand(NEWLINE)
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
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command at {text[index:]!r}"
                )
            code = int(match.group(1), 16)
            argument = int(match.group(2), 16) if match.group(2) else None
            if code == NEWLINE:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, "Write a line end as a new line"
                )
            command = ToCommand(code, argument)
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
    """Bytes of a text run in the game's font (the Latin codes, spaces and ``{char XX}``)."""
    codes = []
    index = 0
    while index < len(text):
        char = _NOTATION_CHAR.match(text, index)
        if char is not None:
            code = int(char.group(1), 16)
            if code >= GLYPH_CODES:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{char.group(0)} is not a glyph"
                )
            codes.append(code)
            index = char.end()
            continue
        character = text[index]
        code = SPACE if character == " " else _LATIN.get(character)
        if code is None:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"The Tactics Ogre font has no {character!r}"
            )
        codes.append(code)
        index += 1
    return bytes(codes)


def pieces_bytes(pieces: Iterable[Piece]) -> bytes:
    return b"".join(
        encode_text(piece) if isinstance(piece, str) else piece.data for piece in pieces
    )


Pixels = tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class ToFont:
    """The game's font: a width and an 8x16 glyph for each code below ``GLYPH_CODES``."""

    widths: bytes
    glyphs: bytes

    @classmethod
    def read(cls, rom: bytes) -> ToFont:
        widths_start = _offset(rom, FONT_WIDTHS, GLYPH_CODES)
        glyphs_start = _offset(rom, FONT_GLYPHS, GLYPH_BYTES * GLYPH_CODES)
        return cls(
            bytes(rom[widths_start : widths_start + GLYPH_CODES]),
            bytes(rom[glyphs_start : glyphs_start + GLYPH_BYTES * GLYPH_CODES]),
        )

    def width(self, code: int) -> int:
        return SPACE_WIDTH if code == SPACE else self.widths[code]

    def glyph(self, code: int) -> Pixels:
        """16 rows of 8 pixels, a row after another as the dialogue draws them."""
        start = GLYPH_BYTES * code
        return unpack_4bpp(self.glyphs[start : start + GLYPH_BYTES], GLYPH_COLUMNS, GLYPH_ROWS)


# ---------------------------------------------------------------------------
# Layout: where the dialogue draws every glyph


@dataclass(frozen=True, slots=True)
class ToPlace:
    """A glyph as the dialogue draws it: at ``pen`` on its line, ``width`` wide."""

    code: int
    pen: int
    width: int

    @property
    def end(self) -> int:
        return self.pen + self.width


@dataclass(frozen=True, slots=True)
class ToLine:
    """A line of a page: its number there and its glyphs; ``waits`` for A at its end."""

    page: int
    number: int
    places: tuple[ToPlace, ...]
    waits: bool = False

    @property
    def width(self) -> int:
        """Where the pen stops: the end of the line's last glyph."""
        return max((place.end for place in self.places), default=0)


def lay_out(data: bytes, width: Callable[[int], int]) -> tuple[ToLine, ...]:
    """The lines of a message's bytes as the dialogue lays them out, from the left.

    A name (``80xx``, ``87xx``) and an icon take no room in this model: the
    Arabic text spells its names out and has no icons.
    """
    lines: list[ToLine] = []
    page = number = pen = 0
    places: list[ToPlace] = []
    waits = False

    def close() -> None:
        lines.append(ToLine(page, number, tuple(places), waits))
        places.clear()

    for piece in _codes(data):
        if isinstance(piece, int):
            glyph_width = width(piece)
            places.append(ToPlace(piece, pen, glyph_width))
            pen += glyph_width
        elif piece.code in (LAST_WAIT, PAGE_WAIT):
            waits = True
        elif piece.code == NEWLINE:
            close()
            number, pen, waits = number + 1, 0, False
        elif piece.code == NEW_PAGE:
            close()
            page, number, pen, waits = page + 1, 0, 0, False
    close()
    return tuple(lines)


def _codes(data: bytes) -> Iterable[int | ToCommand]:
    """Glyph codes (spaces too) and commands, in order."""
    index = 0
    while index < len(data):
        code = data[index]
        if code < GLYPH_CODES or code == SPACE:
            yield code
            index += 1
            continue
        if code in ARGUMENT_COMMANDS:
            command = ToCommand(code, data[index + 1] if index + 1 < len(data) else None)
        else:
            command = ToCommand(code)
        yield command
        index += len(command.data)


def page_lines(lines: Sequence[ToLine]) -> dict[int, int]:
    """How many lines each page holds."""
    counts: dict[int, int] = {}
    for line in lines:
        counts[line.page] = max(counts.get(line.page, 0), line.number + 1)
    return counts
