"""Script engine of *Mega Man Battle Network* (GBA).

Dialogue is stored in script archives: a table of u16 offsets, one per
section and relative to the archive (so the first offset is twice the section
count), followed by the sections. ``Text_LoadDialogue`` starts section ``n``
at ``archive + offsets[n]`` and ``Text_Main`` runs it byte by byte:

- bytes below ``0xE5`` are characters, and ``0xE5``/``0xE6`` + a byte are more
  (``E5 xx`` are the punctuation and symbols of the USA font);
- bytes from ``0xE7`` are commands: ``E7`` ends the script, ``E8`` starts a
  new line, ``E9`` clears the box (a new page), ``EA`` waits, ``EB`` waits for
  a key, ``ED`` shows or hides a mugshot, ``EE`` moves its mouth, ``F2`` opens
  the box, ``F5`` locks the player, ``F6`` jumps to another section, ``FB``
  prints a key item's name... Their lengths follow the tables of the game's
  layout pass (``JT_LayoutCommand``), which skips them the same way.

Every character is an 8x16 cell (two 4bpp tiles) in a box of 3 lines of 20
columns: ``Text_CopyCharTile`` copies glyph ``code`` of the dialogue font into
the next of 60 slots of a tile buffer, and on every frame the page is laid
out again from its start, slot ``n`` going to column ``8 + x`` of its line
(``Text_LoadCharTileLayout``). A page ends at ``E9``, which empties the buffer.

The notation follows the script sources of the Silenthal/bn1 disassembly:
``<`` and ``>`` start and stop the mugshot's mouth (``EE 02``/``EE 01``),
``\\p`` waits for a key, ``\\n`` ends a line and other commands are written
``{name arguments}`` (decimal numbers). Characters without a Unicode
equivalent are ``{char XX}`` (``{char E5XX}``) and commands without a name
here are ``{raw XX XX ...}``.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
SYMBOL_LEAD = 0xE5
KANJI_LEAD = 0xE6
FIRST_COMMAND = 0xE7
NEWLINE = 0xE8
CLEAR = 0xE9
KEY_WAIT = 0xEB
MOUTH = 0xEE
PRINT = 0xFB

CELL_WIDTH = 8
CELL_HEIGHT = 16
TILE_BYTES = 32
CELL_BYTES = 64
FONT_GLYPHS = 512
BOX_COLUMNS = 20
BOX_LINES = 3
# The tile buffer at 0x020037E0 holds 0xF00 bytes: 60 cells, 3 full lines.
PAGE_CELLS = BOX_COLUMNS * BOX_LINES
FIRST_COLUMN = 8
# Palette indices of the dialogue font: box colour, anti-aliasing, ink.
BACKGROUND = 1
SHADE = 2
INK = 3

# The USA font: digits, letters and (after E5) punctuation; the Japanese kana
# slots of the original font are filled with blocks.
_CHARACTERS: dict[int, str] = {
    0x00: " ",
    **{0x01 + digit: str(digit) for digit in range(10)},
    0x5E: "-",
    **{0x5F + letter: chr(ord("A") + letter) for letter in range(26)},
    **{0x79 + letter: chr(ord("a") + letter) for letter in range(26)},
}
_SYMBOLS: dict[int, str] = {
    0x00: "!", 0x01: "‼", 0x02: "?", 0x03: '"', 0x04: "„", 0x05: "#", 0x07: "$", 0x08: "%",
    0x09: "&", 0x0A: "'", 0x0B: "(", 0x0C: ")", 0x0D: "~", 0x14: ",", 0x15: "。", 0x16: ".",
    0x17: "・", 0x18: "/", 0x1A: "_", 0x1B: "「", 0x1C: "」", 0x1D: "[", 0x1E: "]",
    0x25: "↑", 0x26: "→", 0x27: "↓", 0x28: "←", 0x2A: "α", 0x2B: "β", 0x2C: "@", 0x2D: "★",
    0x2E: "♥", 0x2F: "♪", 0x31: "♂", 0x32: "♀", 0x36: ":", 0x37: ";", 0x38: "…", 0x3A: "+",
    0x3B: "×", 0x3C: "÷", 0x3D: "=", 0x3F: "*",
}  # fmt: skip
_CODES: dict[str, bytes] = {
    **{text: bytes((code,)) for code, text in _CHARACTERS.items()},
    **{text: bytes((SYMBOL_LEAD, code)) for code, text in _SYMBOLS.items()},
}

# Command lengths: fixed, or by the byte after the command (layout tables).
_FIXED_LENGTHS: dict[int, int] = {
    0xE7: 3, 0xE8: 1, 0xE9: 3, 0xEB: 1, 0xEE: 2, 0xF0: 3, 0xF2: 2, 0xF5: 2, 0xF9: 2, 0xFE: 3,
}  # fmt: skip
_SUB_LENGTHS: dict[int, dict[int, int]] = {
    0xEA: {0x00: 4, 0x01: 4, 0xFF: 4},
    0xEC: {0x00: 3, 0x01: 2, 0x02: 2},
    0xED: {0x00: 4, 0x01: 2, 0x02: 3},
    0xEF: {0x00: 3, 0x01: 3},
    0xF3: {0x00: 4, 0x04: 4, 0x08: 4},
    0xF4: {0x00: 6, 0x04: 6, 0x08: 5, 0x0C: 6, 0x10: 6, 0x14: 6, 0x18: 6},
    0xF6: {0x00: 3},
    0xF7: {0x00: 7, 0x01: 7, 0x02: 4, 0x03: 7, 0x04: 7, 0x10: 8, 0x11: 8, 0x12: 5, 0x14: 8},
    0xF8: {0x00: 4, 0x04: 6, 0x08: 9, 0x0C: 2, 0x10: 6},
    0xFA: {0x00: 2, 0x04: 3, 0x08: 2, 0x0C: 2, 0x10: 2},
    0xFB: {0x00: 4, 0x04: 4, 0x08: 5, 0x0C: 4},
    0xFC: {0x00: 4, 0x04: 4, 0x08: 2, 0x0C: 2, 0x10: 2, 0x14: 4, 0x18: 4},
    # FD 10 reads nine bytes (the layout pass skips eight; the battle ends the page).
    0xFD: {0x08: 2, 0x0C: 3, 0x10: 9, 0x14: 4, 0x18: 2},
}
# Commands that end a section: E7 end, F1 choice, F6 jump (F6 00 FF goes
# on), EA FF stop.
_ENDINGS = frozenset({0xE7, 0xF1, 0xF6})

# Named commands: (bytes before the arguments, argument sizes).
_NAMED: dict[str, tuple[bytes, tuple[int, ...]]] = {
    "end": (b"\xe7", (2,)),
    "cls": (b"\xe9", (2,)),
    "fd": (b"\xea\x00", (2,)),
    "d": (b"\xea\x01", (2,)),
    "stop": (b"\xea\xff", (2,)),
    "speed": (b"\xec\x00", (1,)),
    "skip_on": (b"\xec\x01", ()),
    "skip_off": (b"\xec\x02", ()),
    "pic": (b"\xed\x00", (1, 1)),
    "hidepic": (b"\xed\x01", ()),
    "picpal": (b"\xed\x02", (1,)),
    "a": (b"\xee", (1,)),
    "pad": (b"\xef\x00", (1,)),
    "col": (b"\xef\x01", (1,)),
    "dialog_up": (b"\xf2\x00", ()),
    "dialog_down": (b"\xf2\x01", ()),
    "dialog_show": (b"\xf2\x02", ()),
    "dialog_hide": (b"\xf2\x03", ()),
    "input_off": (b"\xf5\x00", ()),
    "input_on": (b"\xf5\x01", ()),
    "jump": (b"\xf6\x00", (1,)),
    "pal": (b"\xf9", (1,)),
    "key": (b"\xfb\x00", (1, 1)),
}
_SHORTHANDS: dict[bytes, str] = {b"\xee\x02": "<", b"\xee\x01": ">", b"\xeb": "\\p", b"\xe8": "\n"}
_SHORTHAND_BYTES = {notation: data for data, notation in _SHORTHANDS.items()}

_COMMAND_NOTATION = re.compile(r"\{([a-z_]+)((?: [0-9A-Fa-f]+)*)\}")


class MmbnEngineAdapter(EngineAdapter):
    id = "gba.mmbn"
    display_name = "Mega Man Battle Network GBA script engine"
    platform_ids = ("gba",)


@dataclass(frozen=True, slots=True)
class MmbnCommand:
    """A script command with its bytes and notation."""

    data: bytes
    notation: str

    @property
    def code(self) -> int:
        return self.data[0]

    @property
    def ends_section(self) -> bool:
        if self.data == b"\xf6\x00\xff":
            return False
        return self.code in _ENDINGS or self.data[:2] == b"\xea\xff"

    @property
    def is_newline(self) -> bool:
        return self.data == bytes((NEWLINE,))

    @property
    def is_key_print(self) -> bool:
        """``{key N}``: the name of a key item, printed from the item table."""
        return self.data[:2] == bytes((PRINT, 0x00))


Piece = str | MmbnCommand


def command_length(data: bytes, index: int) -> int:
    code = data[index]
    if code in _FIXED_LENGTHS:
        return _FIXED_LENGTHS[code]
    if code == 0xF1:
        # A choice: F1, its own length, flags, then one target per option.
        if index + 1 >= len(data):
            raise ClassicRetroError(ErrorCode.TOKEN_ORDER_VIOLATION, "Choice cut short")
        return data[index + 1]
    if code == 0xFD and index + 2 < len(data) and data[index + 1] in (0x00, 0x04):
        # Rewards: FD 00 zenny (4 bytes each), FD 04 chips (2 bytes each).
        return 6 + data[index + 2] * (4 if data[index + 1] == 0x00 else 2)
    lengths = _SUB_LENGTHS.get(code)
    if lengths is None or index + 1 >= len(data) or data[index + 1] not in lengths:
        sub = f" {data[index + 1]:02X}" if index + 1 < len(data) else ""
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"Unknown MMBN command {code:02X}{sub} at byte {index}",
        )
    return lengths[data[index + 1]]


def _command_notation(data: bytes) -> str:
    if data in _SHORTHANDS:
        return _SHORTHANDS[data]
    for name, (prefix, sizes) in _NAMED.items():
        if data.startswith(prefix) and len(data) == len(prefix) + sum(sizes):
            if name == "key" and data[-1] != 0:
                break
            values = []
            position = len(prefix)
            for size in sizes:
                values.append(int.from_bytes(data[position : position + size], "little"))
                position += size
            if name == "key":
                values = values[:1]
            return "{" + " ".join((name, *map(str, values))) + "}"
    return "{raw " + data.hex(" ").upper() + "}"


def decode_command(data: bytes, index: int) -> MmbnCommand:
    length = command_length(data, index)
    raw = data[index : index + length]
    if len(raw) != length:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION, f"Command {data[index]:02X} cut short at byte {index}"
        )
    return MmbnCommand(raw, _command_notation(raw))


def character_text(data: bytes, index: int) -> tuple[str, int]:
    """Notation of the character at ``index`` and the index after it."""
    code = data[index]
    if code in (SYMBOL_LEAD, KANJI_LEAD):
        if index + 1 >= len(data):
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"Two-byte character cut short at byte {index}"
            )
        second = data[index + 1]
        if code == SYMBOL_LEAD and second in _SYMBOLS:
            return _SYMBOLS[second], index + 2
        return f"{{char {code:02X}{second:02X}}}", index + 2
    if code in _CHARACTERS:
        return _CHARACTERS[code], index + 1
    return f"{{char {code:02X}}}", index + 1


def split_script(data: bytes) -> tuple[Piece, ...]:
    """Text runs and commands of a script, all of ``data`` (see ``section_script``)."""
    pieces: list[Piece] = []
    text: list[str] = []
    index = 0
    while index < len(data):
        if data[index] >= FIRST_COMMAND:
            if text:
                pieces.append("".join(text))
                text.clear()
            command = decode_command(data, index)
            pieces.append(command)
            index += len(command.data)
            continue
        character, index = character_text(data, index)
        text.append(character)
    if text:
        pieces.append("".join(text))
    return tuple(pieces)


def script_notation(data: bytes) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_script(data)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Commands in order, without line ends (which may move) and key item names (text)."""
    return tuple(
        piece.notation
        for piece in pieces
        if isinstance(piece, MmbnCommand) and not piece.is_newline and not piece.is_key_print
    )


def command_skeleton(data: bytes) -> tuple[str, ...]:
    return notation_skeleton(split_script(data))


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and commands (``{char ..}`` is kept inside the runs)."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "{" and text.startswith("{char ", index):
            close = text.find("}", index)
            if close < 0:
                raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "Unclosed {char ...}")
            run.append(text[index : close + 1])
            index = close + 1
            continue
        command: MmbnCommand | None = None
        if character == "{":
            match = _COMMAND_NOTATION.match(text, index)
            if match is None:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, f"Unknown or unmatched command at {text[index:]!r}"
                )
            command = _parse_command(match.group(1), match.group(2).split())
            index = match.end()
        elif character in "<>\n":
            command = MmbnCommand(_SHORTHAND_BYTES[character], character)
            index += 1
        elif character == "\\":
            if not text.startswith("\\p", index):
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, f"Unknown escape at {text[index:]!r}"
                )
            command = MmbnCommand(bytes((KEY_WAIT,)), "\\p")
            index += 2
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


def _parse_command(name: str, arguments: list[str]) -> MmbnCommand:
    if name == "raw":
        data = bytes(int(argument, 16) for argument in arguments)
        if not data or data[0] < FIRST_COMMAND or command_length(data, 0) != len(data):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, "{raw ...} must hold exactly one command"
            )
        return MmbnCommand(data, _command_notation(data))
    if name not in _NAMED:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command {{{name}}}")
    prefix, sizes = _NAMED[name]
    if name == "key":
        sizes = sizes[:1]
    if name in ("cls", "end") and not arguments:
        arguments = ["0"]
    if len(arguments) != len(sizes):
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{{{name}}} takes {len(sizes)} argument(s)"
        )
    data = bytearray(prefix)
    for argument, size in zip(arguments, sizes, strict=True):
        value = int(argument, 10)
        if not 0 <= value < 1 << 8 * size:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{{{name}}} argument {value} is out of range"
            )
        data += value.to_bytes(size, "little")
    if name == "key":
        data.append(0)
    return MmbnCommand(bytes(data), _command_notation(bytes(data)))


def encode_text(text: str) -> bytes:
    """Bytes of a text run in the USA font (``{char XX}`` for any other code)."""
    data = bytearray()
    index = 0
    while index < len(text):
        if text.startswith("{char ", index):
            close = text.find("}", index)
            digits = text[index + 6 : close] if close > 0 else ""
            if len(digits) not in (2, 4) or any(c not in "0123456789ABCDEFabcdef" for c in digits):
                raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "Bad {char ...}")
            data += bytes.fromhex(digits)
            index = close + 1
            continue
        code = _CODES.get(text[index])
        if code is None:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"The MMBN font has no {text[index]!r}"
            )
        data += code
        index += 1
    return bytes(data)


def script_bytes(pieces: Iterable[Piece]) -> bytes:
    return b"".join(
        encode_text(piece) if isinstance(piece, str) else piece.data for piece in pieces
    )


def section_script(data: bytes, start: int) -> bytes:
    """The script at ``start``: every byte up to its ending command (included)."""
    index = start
    while index < len(data):
        code = data[index]
        if code < FIRST_COMMAND:
            index += 2 if code in (SYMBOL_LEAD, KANJI_LEAD) else 1
            continue
        command = decode_command(data, index)
        index += len(command.data)
        if command.ends_section:
            return data[start:index]
    raise ClassicRetroError(
        ErrorCode.MISSING_TERMINATOR, f"Script at byte {start} has no ending command"
    )


@dataclass(frozen=True, slots=True)
class ScriptArchive:
    """An archive's address and section offsets (relative to the archive)."""

    address: int
    offsets: tuple[int, ...]

    @classmethod
    def parse(cls, rom: bytes, address: int) -> ScriptArchive:
        start = address - ROM_BASE
        if not 0 <= start < len(rom) - 2:
            raise ClassicRetroError(
                ErrorCode.RESOURCE_OUT_OF_BOUNDS, f"Archive {address:#x} is outside the image"
            )
        (first,) = struct.unpack_from("<H", rom, start)
        if first == 0 or first % 2 or start + first > len(rom):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"No script archive at {address:#x}"
            )
        offsets = struct.unpack_from(f"<{first // 2}H", rom, start)
        if any(offset < first for offset in offsets) or list(offsets) != sorted(offsets):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Archive {address:#x} has a bad offset table"
            )
        return cls(address, offsets)

    def section_address(self, index: int) -> int:
        return self.address + self.offsets[index]

    def raw_section(self, rom: bytes, index: int, length: int) -> bytes:
        start = self.section_address(index) - ROM_BASE
        return rom[start : start + length]

    def section(self, rom: bytes, index: int) -> bytes:
        return section_script(rom, self.section_address(index) - ROM_BASE)

    def extent(self, rom: bytes, index: int) -> bytes:
        """Every byte of a section up to the next one (the last: its script and trailer)."""
        if index + 1 < len(self.offsets):
            return self.raw_section(rom, index, self.offsets[index + 1] - self.offsets[index])
        if self.raw_section(rom, index, len(SECTION_TRAILER)) == SECTION_TRAILER:
            return SECTION_TRAILER
        body = self.section(rom, index)
        if self.raw_section(rom, index, len(body) + 2)[len(body) :] != SECTION_TRAILER:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"The last section of {self.address:#x} has no trailer",
            )
        return body + SECTION_TRAILER


# The disassembly's script builder ends every section with two zero bytes
# (never reached after its ending command); an empty section is just those.
SECTION_TRAILER = b"\0\0"


def build_archive(bodies: Iterable[bytes]) -> bytes:
    """Offset table, then every section body (script and trailer) in order, padded to 4."""
    bodies = list(bodies)
    offset = 2 * len(bodies)
    table = bytearray()
    for body in bodies:
        if offset > 0xFFFF:
            raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Script archive over 64 KiB")
        table += struct.pack("<H", offset)
        offset += len(body)
    data = bytes(table) + b"".join(bodies)
    return data + bytes(-len(data) % 4)


def cell_data(pixels: Iterable[Iterable[int]]) -> bytes:
    """An 8x16 cell of palette indices as the game stores it: top tile, then bottom tile."""
    rows = [list(row) for row in pixels]
    if len(rows) != CELL_HEIGHT or any(len(row) != CELL_WIDTH for row in rows):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "An MMBN cell is 8x16 pixels")
    data = bytearray()
    for row in rows:
        for x in range(0, CELL_WIDTH, 2):
            if not (0 <= row[x] <= 0xF and 0 <= row[x + 1] <= 0xF):
                raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "An MMBN pixel has 4 bits")
            data.append(row[x] | row[x + 1] << 4)
    return bytes(data)


def cell_pixels(data: bytes) -> tuple[tuple[int, ...], ...]:
    if len(data) != CELL_BYTES:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "An MMBN cell is 64 bytes")
    return tuple(
        tuple(data[y * 4 + x // 2] >> 4 * (x & 1) & 0xF for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    )


def font_cell(rom: bytes, font_address: int, code: int) -> tuple[tuple[int, ...], ...]:
    """Glyph ``code`` of the dialogue font (``E5 xx`` is ``0xE5 + xx``)."""
    if not 0 <= code < FONT_GLYPHS:
        raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"No glyph {code:#x} in the font")
    start = font_address - ROM_BASE + code * CELL_BYTES
    return cell_pixels(rom[start : start + CELL_BYTES])


def glyph_code(character: str) -> int:
    """Font glyph of a character (``Text_Main`` draws ``E5 xx`` as glyph ``0xE5 + xx``)."""
    code = _CODES.get(character)
    if code is None:
        raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"The MMBN font has no {character!r}")
    return code[0] if len(code) == 1 else code[0] + code[1]
