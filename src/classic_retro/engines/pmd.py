"""Text engine of *Pokémon Mystery Dungeon: Red Rescue Team* (GBA).

Strings are NUL-terminated bytes, stored uncompressed and reached through
plain pointers (script commands, question tables, menu items). The game's
typewriter (``DrawDialogueBoxString_Async``) and ``DrawStringInternal`` read
them the same way:

- ``#`` starts a format command: ``#+`` centres the rest of the line, ``#W``
  waits for a key, ``#P`` opens a new box, ``#C`` + a byte sets the colour...
- ``$`` starts a placeholder that ``FormatString`` fills in before drawing
  (``$m0`` a Pokémon, ``$n0`` a name, ``$d0`` a number...);
- ``~`` + two hex digits is a character by code (the game writes ``,`` and
  ``'`` this way);
- bytes ``0x81..0x84`` and ``0x87`` start two-byte characters (Shift-JIS
  style: symbols and icons);
- ``\\n`` ends a line; every other byte is a character (ASCII, and
  Windows-1252 for accents).

Glyphs come from the ``kanji_a`` file of the system archive: a ``SIRO``
header points to ``{count, entries}``; every 12-byte entry is ``{bitmap
pointer, code, width, flags, style}`` and entries are sorted by code (the game
binary-searches them). A bitmap is 12 rows of 12 four-bit pixels, three
halfwords per row; in a plain glyph a pixel is ink (``0xF``) or empty, and
the game adds the colour and a drop shadow (style bit 1) while drawing.

The notation used by this toolkit writes commands as ``{NAME}`` or
``{NAME:XX}`` (argument bytes in hex), placeholders as ``{POKEMON_0}``-style
names and line ends as ``\\n``, following the pret/pmd-red charmap names.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

ROM_BASE = 0x08000000
TWO_BYTE_LEADS = frozenset({0x81, 0x82, 0x83, 0x84, 0x87})
NEWLINE = 0x0A
FORMAT = 0x23  # '#'
PLACEHOLDER = 0x24  # '$'
HEX_ESCAPE = 0x7E  # '~'
TERMINATOR = 0x00

GLYPH_ROWS = 12
GLYPH_COLUMNS = 12
GLYPH_ROW_BYTES = 6
GLYPH_BYTES = GLYPH_ROWS * GLYPH_ROW_BYTES
ENTRY_BYTES = 12
INK = 0xF
SIRO_MAGIC = b"SIRO"
STYLE_COLOUR = 1
STYLE_SHADOW = 2

# '#' + key -> (name, argument bytes). ``#=``, ``#y`` and ``#_`` may be
# followed by a '.' that the game skips.
_FORMAT_COMMANDS: dict[int, tuple[str, int]] = {
    ord("+"): ("CENTER_ALIGN", 0),
    ord("W"): ("WAIT_PRESS", 0),
    ord("P"): ("EXTRA_MSG", 0),
    ord("p"): ("EXTRA_MSG_KEEP", 0),
    ord("n"): ("NEW_LINE", 0),
    ord(":"): ("SAVE_X", 0),
    ord("R"): ("RESET", 0),
    ord("r"): ("RESET_ALT", 0),
    ord("="): ("MOVE_X_POSITION", 1),
    ord("y"): ("MOVE_Y_POSITION", 1),
    ord("."): ("SHIFT_X", 1),
    ord(";"): ("RESTORE_X", 1),
    ord("C"): ("COLOR", 1),
    ord("c"): ("COLOR_ALT", 1),
    ord("_"): ("PALETTE_COLOR", 1),
    ord("~"): ("WAIT_FRAMES", 1),
    ord("S"): ("SET_STATE", 2),
}
_DOT_AFTER_ARGUMENT = frozenset({ord("="), ord("y"), ord("_")})
_FORMAT_KEYS = {name: key for key, (name, _) in _FORMAT_COMMANDS.items()}
# Commands after which the next glyph starts a new line or a new box.
LINE_ENDING_COMMANDS = frozenset({"NEW_LINE", "EXTRA_MSG", "EXTRA_MSG_KEEP"})
PAGE_COMMANDS = frozenset({"EXTRA_MSG", "EXTRA_MSG_KEEP"})

# '$' + key -> (name, digits that follow); see FormatString.
_PLACEHOLDERS: dict[int, tuple[str, int]] = {
    ord("i"): ("MOVE_ITEM", 1),
    ord("n"): ("NAME", 1),
    ord("d"): ("VALUE", 1),
    ord("v"): ("NUMBER", 2),
    ord("V"): ("ZERO_NUMBER", 2),
    ord("t"): ("TEAM_NAME", 0),
    ord("h"): ("FRIEND_AREA", 0),
    ord("-"): ("SKIP", 1),
}

_NOTATION = re.compile(r"\{([A-Za-z_]+)(?::([0-9A-Fa-f]+))?\}")


class PmdEngineAdapter(EngineAdapter):
    id = "gba.pmd"
    display_name = "Pokémon Mystery Dungeon GBA text engine"
    platform_ids = ("gba",)


@dataclass(frozen=True, slots=True)
class PmdCommand:
    """A format command, placeholder or line end, with its bytes in the string."""

    name: str
    data: bytes
    notation: str


NEWLINE_COMMAND = PmdCommand("NEWLINE", b"\n", "\n")

Piece = str | PmdCommand


def format_command(name: str, argument: bytes = b"") -> PmdCommand:
    """The ``#`` command called ``name`` (see the charmap names above)."""
    key = _FORMAT_KEYS.get(name)
    if key is None:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown PMD command {name}")
    arguments = _FORMAT_COMMANDS[key][1]
    if len(argument) != arguments:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{{{name}}} takes {arguments} argument byte(s)"
        )
    notation = "{" + name + (":" + argument.hex().upper() if argument else "") + "}"
    return PmdCommand(name, bytes((FORMAT, key)) + argument, notation)


def character_at(data: bytes, index: int) -> tuple[int, int]:
    """``(code, next index)`` for the character at ``index`` (GetNextCharFromStr)."""
    byte = data[index]
    if byte == HEX_ESCAPE:
        digits = data[index + 1 : index + 3]
        if len(digits) != 2 or not all(chr(digit) in "0123456789abcdefABCDEF" for digit in digits):
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"Bad '~' character escape at byte {index}"
            )
        return int(digits.decode("ascii"), 16), index + 3
    if byte in TWO_BYTE_LEADS:
        if index + 1 >= len(data) or data[index + 1] == TERMINATOR:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, f"Two-byte character cut short at byte {index}"
            )
        return byte << 8 | data[index + 1], index + 2
    return byte, index + 1


def character_text(code: int) -> str:
    """Unicode for a one-byte code; anything else becomes ``{CHAR:XX}``."""
    if 0x20 <= code <= 0xFF and code != 0x7F:
        try:
            return bytes((code,)).decode("cp1252")
        except UnicodeDecodeError:
            pass
    return f"{{CHAR:{code:02X}}}"


def _format_command(data: bytes, index: int) -> tuple[PmdCommand | None, int]:
    """The command at ``index`` (a '#'), or None when the '#' is drawn as a glyph."""
    if index + 1 >= len(data):
        return None, index
    key = data[index + 1]
    if key == ord(">"):
        end = index + 2
        while end < len(data) and 0x30 <= data[end] <= 0x39:
            end += 1
        if end < len(data) and data[end] == ord("."):
            end += 1
        raw = data[index:end]
        return PmdCommand("ALIGN_X", raw, "{ALIGN_X:" + raw[2:].hex().upper() + "}"), end
    if key == ord("["):
        close = data.find(b"]", index + 2)
        end = len(data) if close < 0 else close + 1
        raw = data[index:end]
        return PmdCommand("CALLBACK", raw, "{CALLBACK:" + raw[2:].hex().upper() + "}"), end
    known = _FORMAT_COMMANDS.get(key)
    if known is None:
        return None, index
    name, arguments = known
    end = index + 2 + arguments
    if end > len(data):
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION, f"Command {name} cut short at byte {index}"
        )
    command = format_command(name, data[index + 2 : end])
    if key in _DOT_AFTER_ARGUMENT and end < len(data) and data[end] == ord("."):
        end += 1
        command = PmdCommand(name, data[index:end], command.notation[:-1] + ".}")
    return command, end


def _placeholder(data: bytes, index: int) -> tuple[PmdCommand, int]:
    key = data[index + 1] if index + 1 < len(data) else None
    if key == ord("m"):
        if data[index + 2 : index + 3] == b"m":
            return PmdCommand("LEADER", data[index : index + 3], "{LEADER}"), index + 3
        name, digits = "POKEMON", 1
    elif key == ord("$"):
        return PmdCommand("DOLLAR", data[index : index + 2], "{DOLLAR}"), index + 2
    elif key is not None and key in _PLACEHOLDERS:
        name, digits = _PLACEHOLDERS[key]
    else:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown '$' placeholder at byte {index}"
        )
    end = index + 2 + digits
    raw = data[index:end]
    if len(raw) != end - index:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION, f"Placeholder {name} cut short at byte {index}"
        )
    suffix = "".join("_" + chr(digit) for digit in raw[2:])
    return PmdCommand(name, raw, "{" + name + suffix + "}"), end


def _scan(data: bytes) -> Iterator[int | PmdCommand]:
    """Character codes and commands of one string, in order."""
    if TERMINATOR in data:
        raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "A PMD string ends at its first NUL")
    index = 0
    while index < len(data):
        byte = data[index]
        if byte == NEWLINE:
            yield NEWLINE_COMMAND
            index += 1
            continue
        if byte == FORMAT:
            command, end = _format_command(data, index)
            if command is not None:
                yield command
                index = end
                continue
        if byte == PLACEHOLDER:
            command, index = _placeholder(data, index)
            yield command
            continue
        code, index = character_at(data, index)
        yield code


def split_text(data: bytes) -> tuple[Piece, ...]:
    """Text runs and commands of one string (without its terminator)."""
    pieces: list[Piece] = []
    text: list[str] = []
    for item in _scan(data):
        if isinstance(item, int):
            text.append(character_text(item))
            continue
        if text:
            pieces.append("".join(text))
            text.clear()
        pieces.append(item)
    if text:
        pieces.append("".join(text))
    return tuple(pieces)


def pmd_notation(data: bytes) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in split_text(data)
    )


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """Commands and placeholders in order, without line ends (which may move)."""
    return tuple(
        piece.notation
        for piece in pieces
        if isinstance(piece, PmdCommand) and piece.name != NEWLINE_COMMAND.name
    )


def command_skeleton(data: bytes) -> tuple[str, ...]:
    return notation_skeleton(split_text(data))


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation (``{NAME}``/``{NAME:XX}`` commands, ``\\n`` line ends) as pieces.

    Only format commands and line ends are accepted: placeholders and
    character escapes belong to the original script, not to new text.
    """
    pieces: list[Piece] = []
    position = 0
    for match in _NOTATION.finditer(text):
        _text_pieces(text[position : match.start()], pieces)
        argument = bytes.fromhex(match.group(2)) if match.group(2) else b""
        pieces.append(format_command(match.group(1), argument))
        position = match.end()
    _text_pieces(text[position:], pieces)
    return tuple(pieces)


def _text_pieces(text: str, pieces: list[Piece]) -> None:
    for number, line in enumerate(text.split("\n")):
        if number:
            pieces.append(NEWLINE_COMMAND)
        if line:
            if "{" in line or "}" in line:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, f"Unknown or unmatched command in {line!r}"
                )
            pieces.append(line)


def read_string(rom: bytes, address: int) -> bytes:
    """The string at a ROM address, without its terminator."""
    start = address - ROM_BASE
    if not 0 <= start < len(rom):
        raise ClassicRetroError(
            ErrorCode.RESOURCE_OUT_OF_BOUNDS, f"String address {address:#x} is outside the image"
        )
    end = rom.find(b"\0", start)
    if end < 0:
        raise ClassicRetroError(
            ErrorCode.MISSING_TERMINATOR, f"String at {address:#x} has no terminator"
        )
    return rom[start:end]


def line_widths(data: bytes, widths: dict[int, int]) -> tuple[int, ...]:
    """Width in pixels of every line of a string, as ``GetStringLineWidth`` adds them."""
    lines = [0]
    for item in _scan(data):
        if isinstance(item, int):
            if item not in widths:
                raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"No glyph for code {item:#x}")
            lines[-1] += widths[item]
        elif item.name == NEWLINE_COMMAND.name or item.name in LINE_ENDING_COMMANDS:
            lines.append(0)
    return tuple(lines)


def glyph_bitmap(pixels: Iterable[Iterable[int]]) -> bytes:
    """12 rows of 12 four-bit pixels as the game stores them (3 halfwords per row)."""
    rows = [list(row) for row in pixels]
    if len(rows) != GLYPH_ROWS or any(len(row) != GLYPH_COLUMNS for row in rows):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A PMD glyph is 12x12 pixels")
    data = bytearray()
    for row in rows:
        value = 0
        for x, pixel in enumerate(row):
            if not 0 <= pixel <= 0xF:
                raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A PMD pixel has 4 bits")
            value |= pixel << 4 * x
        data += value.to_bytes(GLYPH_ROW_BYTES, "little")
    return bytes(data)


def bitmap_pixels(data: bytes) -> tuple[tuple[int, ...], ...]:
    if len(data) != GLYPH_BYTES:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A PMD glyph bitmap is 72 bytes")
    rows = []
    for y in range(GLYPH_ROWS):
        value = int.from_bytes(data[y * GLYPH_ROW_BYTES : (y + 1) * GLYPH_ROW_BYTES], "little")
        rows.append(tuple(value >> 4 * x & 0xF for x in range(GLYPH_COLUMNS)))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class PmdGlyphEntry:
    """One charmap entry: ``{bitmap, code, width, flags, style}``."""

    code: int
    width: int
    flags: int
    style: int
    bitmap: int

    def pack(self) -> bytes:
        return struct.pack(
            "<IHhBBBB", self.bitmap, self.code, self.width, self.flags, 0, self.style, 0
        )


@dataclass(frozen=True, slots=True)
class PmdCharmap:
    """The ``kanji_a``/``kanji_b`` charmap: entries sorted by character code."""

    file_address: int
    table_address: int
    entries_address: int
    entries: tuple[PmdGlyphEntry, ...]

    @classmethod
    def parse(cls, rom: bytes, file_address: int) -> PmdCharmap:
        start = file_address - ROM_BASE
        if rom[start : start + 4] != SIRO_MAGIC:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"No SIRO file at {file_address:#x}"
            )
        (table,) = struct.unpack_from("<I", rom, start + 4)
        count, entries = struct.unpack_from("<iI", rom, table - ROM_BASE)
        if not 0 < count <= 0x4000:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Charmap at {table:#x} has {count} glyphs"
            )
        parsed = []
        for number in range(count):
            bitmap, code, width, flags, _, style, _ = struct.unpack_from(
                "<IHhBBBB", rom, entries - ROM_BASE + number * ENTRY_BYTES
            )
            parsed.append(PmdGlyphEntry(code, width, flags, style, bitmap))
        codes = [entry.code for entry in parsed]
        if codes != sorted(set(codes)):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, "Charmap entries are not sorted by code"
            )
        return cls(file_address, table, entries, tuple(parsed))

    def entry(self, code: int) -> PmdGlyphEntry | None:
        for entry in self.entries:
            if entry.code == code:
                return entry
        return None

    def widths(self) -> dict[int, int]:
        return {entry.code: entry.width for entry in self.entries}

    def pixels(self, rom: bytes, code: int) -> tuple[tuple[int, ...], ...]:
        entry = self.entry(code)
        if entry is None:
            raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"No glyph for code {code:#x}")
        start = entry.bitmap - ROM_BASE
        return bitmap_pixels(rom[start : start + GLYPH_BYTES])
