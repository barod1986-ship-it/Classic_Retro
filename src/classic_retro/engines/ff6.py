"""Text engine of *Final Fantasy III* (USA, Super NES): the field dialogue.

The dialogue is a table of 16-bit offsets (``DLG_POINTERS``, ``DLG_COUNT``
entries) from the text at ``DLG_TEXT`` (bank $CD); a message whose number is
``DLG_BANK_INCREMENT``'s word or more counts from the next bank ($CE). The
event script gives the message's number (``$D0``), ``GetDlgPtr`` sets the
pointer (``$C9``-``$CB``) and the engine draws a letter a frame
(``UpdateDlgText``), reading with ``lda [$c9],y``. A message's bytes are:

- ``00`` its end: the window waits for the button and closes;
- ``01`` the end of a line, ``13`` the end of a page (the window waits for
  the button and clears), ``14`` then a byte: that many spaces;
- ``02``-``0F`` a character's name (``NAMES``: Terra to Umaro), ``10`` a
  pause of a second, ``11`` then a byte: a pause of that many quarter
  seconds, ``12`` waiting for the button, ``16`` then a byte: the pause then
  the button, ``15`` a choice's mark, ``19`` the gil amount, ``1A`` the
  item's name, ``1B`` the spell's name (``COMMANDS``); ``1C``-``1F`` then a
  byte: the Japanese game's letters beyond the first 256, unused;
- ``20``-``7F`` a letter of the dialogue font (``CHARACTERS``: the capitals,
  the small letters, the digits, the signs, the icons; ``7F`` the space);
- ``80``-``FF`` a pair of letters (``DTE_CODES``) from the table at
  ``DTE_TABLE`` (``dte_pairs``).

The letters are drawn with a variable-width font: ``FONT_WIDTHS`` holds a
width a letter, ``LARGE_FONT`` a glyph a letter of ``GLYPH_BYTES`` (eleven
rows of sixteen pixels, a bit each), drawn at the pen (``$BF``, from
``LINE_START``) into a buffer of cells of 16x16 pixels sent to the tiles'
memory a cell a frame. A line ends where the next word would pass
``LINE_END``; the box shows ``LINES`` lines and waits for the button when
they are full. The names follow the everything8215/ff6 disassembly
(``field/text.asm``).

A message's notation writes its letters as text, a pair as its letters, an
icon as a ``{token}`` and a command as a ``{token}`` too, with its byte as
two hex digits where it has one: ``{line}``, ``{page}``, ``{Spaces 03}``,
``{Terra}``, ``{Wait}``, ``{Pause 04}``, ``{Key}``, ``{KeyAfter 04}``,
``{Choice}``, ``{Gil}``, ``{Item}``, ``{Spell}``.

A message's command skeleton (``command_skeleton``) is its commands in that
notation, in order, but the layout commands (``LAYOUT_COMMANDS``): the
line's end, the page's end and the spaces, which the Arabic encoder writes
itself as it lays its own lines and pages out. A translation must keep the
rest: the names, the pauses, the button waits, the choice marks, the gil, the
item and the spell. The skeleton skips every byte that is not a command, so
it reads an Arabic message (``engines.ff6_arabic``), whose glyph codes
replace the letters and pairs, as it reads an English one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

# The dialogue: the first message number of bank $CE (a word), the table of
# offsets, the text, and the text's block ($1F100 bytes, the disassembly's
# fixed block, over banks $CD and $CE).
DLG_BANK_INCREMENT = 0xCCE600
DLG_POINTERS = 0xCCE602
DLG_COUNT = 3084
DLG_TEXT = 0xCD0000
DLG_END = 0xCEF100
# The pairs of letters: two bytes a code from $80 at $C0:DFA0.
DTE_TABLE = 0xC0DFA0
DTE_FIRST = 0x80
DTE_CODES = tuple(range(0x80, 0x100))
# The dialogue font: a width a letter ($00-$FF), then a glyph a letter from
# $20: 22 bytes, eleven rows of a 16-bit word, the leftmost pixel in bit 15.
FONT_WIDTHS = 0xC48FC0
FONT_WIDTH_COUNT = 0x100
LARGE_FONT = 0xC490C0
GLYPH_BYTES = 22
GLYPH_ROWS = 11
FIRST_LETTER = 0x20
# The box: the pen starts at 4 and a letter must end before 224; four lines.
LINE_START = 4
LINE_END = 0xE0
LINES = 4
END = 0x00
SPACE = 0x7F
NAMES = ("Terra Locke Cyan Shadow Edgar Sabin Celes Strago Relm Setzer Mog Gau Gogo Umaro").split()
NAME_FIRST = 0x02
# code: (name, bytes with the command's own)
COMMANDS: dict[int, tuple[str, int]] = {
    0x01: ("line", 1),
    **{NAME_FIRST + number: (name, 1) for number, name in enumerate(NAMES)},
    0x10: ("Wait", 1),
    0x11: ("Pause", 2),
    0x12: ("Key", 1),
    0x13: ("page", 1),
    0x14: ("Spaces", 2),
    0x15: ("Choice", 1),
    0x16: ("KeyAfter", 2),
    0x19: ("Gil", 1),
    0x1A: ("Item", 1),
    0x1B: ("Spell", 1),
    0x1C: ("Extra1C", 2),
    0x1D: ("Extra1D", 2),
    0x1E: ("Extra1E", 2),
    0x1F: ("Extra1F", 2),
}
COMMAND_CODES = {name: code for code, (name, _) in COMMANDS.items()}
LINE = COMMAND_CODES["line"]
PAGE = COMMAND_CODES["page"]
SPACES = COMMAND_CODES["Spaces"]
NAME_CODES = {name: NAME_FIRST + number for number, name in enumerate(NAMES)}
NAME_LAST = NAME_FIRST + len(NAMES) - 1
# The commands the Arabic encoder writes itself; a translation keeps every other.
LAYOUT_COMMANDS = frozenset((LINE, PAGE, SPACES))
# The letters, from the disassembly's dialog_en table.
CHARACTERS: dict[int, str] = {
    **{0x20 + number: letter for number, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
    **{0x3A + number: letter for number, letter in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{0x54 + number: digit for number, digit in enumerate("0123456789")},
    0x5E: "!",
    0x5F: "?",
    0x60: "/",
    0x61: ":",
    0x62: "”",
    0x63: "'",
    0x64: "-",
    0x65: ".",
    0x66: ",",
    0x67: "…",
    0x68: ";",
    0x69: "#",
    0x6A: "+",
    0x6B: "(",
    0x6C: ")",
    0x6D: "%",
    0x6E: "~",
    0x6F: "*",
    0x70: "@",
    0x72: "=",
    0x73: "“",
    SPACE: " ",
}
CHARACTER_CODES = {character: code for code, character in CHARACTERS.items()}
ICONS: dict[int, str] = {
    0x71: "Note",
    0x76: "Holy",
    0x77: "Times",
    0x78: "Lightning",
    0x79: "Wind",
    0x7A: "Earth",
    0x7B: "Ice",
    0x7C: "Fire",
    0x7D: "Water",
    0x7E: "Poison",
}
ICON_CODES = {name: code for code, name in ICONS.items()}


class Ff6EngineAdapter(EngineAdapter):
    id = "snes.ff6-dialogue"
    display_name = "Final Fantasy III dialogue"
    platform_id = "snes"


def hirom_offset(address: int) -> int:
    """A HiROM address (bank $C0-$FF, or its mirror $40-$7D) as a ROM offset."""
    bank, low = address >> 16, address & 0xFFFF
    if 0xC0 <= bank <= 0xFF:
        return (bank - 0xC0) << 16 | low
    if 0x40 <= bank <= 0x7D:
        return (bank - 0x40) << 16 | low
    raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"${address:06X} is not in the ROM")


def hirom_address(offset: int) -> int:
    """A ROM offset as its HiROM address in banks $C0-$FF."""
    return (0xC0 + (offset >> 16)) << 16 | offset & 0xFFFF


def dte_pairs(rom: bytes) -> dict[int, str]:
    """The pair of letters of every pair code, from the ROM's table."""
    at = hirom_offset(DTE_TABLE)
    pairs = {}
    for code in DTE_CODES:
        first, second = rom[at + 2 * (code - DTE_FIRST) : at + 2 * (code - DTE_FIRST) + 2]
        pairs[code] = character(first) + character(second)
    return pairs


def font_widths(rom: bytes) -> tuple[int, ...]:
    """The width of every letter, by code."""
    at = hirom_offset(FONT_WIDTHS)
    return tuple(rom[at : at + FONT_WIDTH_COUNT])


def byte_length(code: int) -> int:
    """How many bytes a code takes with its own."""
    return COMMANDS[code][1] if code in COMMANDS else 1


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A message where it is stored: its number (what the event script gives), its
    address and its bytes, its end included."""

    number: int
    address: int
    data: bytes


def bank_increment(rom: bytes) -> int:
    """The first message number whose offset counts from bank $CE."""
    (value,) = struct.unpack_from("<H", rom, hirom_offset(DLG_BANK_INCREMENT))
    return value


def pointer_table(rom: bytes) -> tuple[int, ...]:
    return struct.unpack_from(f"<{DLG_COUNT}H", rom, hirom_offset(DLG_POINTERS))


def message_address(rom: bytes, number: int) -> int:
    """Where message ``number`` starts, as the engine finds it."""
    if not 0 <= number < DLG_COUNT:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No message {number}")
    offset = pointer_table(rom)[number]
    bank = DLG_TEXT + (0x10000 if number >= bank_increment(rom) else 0)
    return bank + offset


def _message_end(rom: bytes, start: int, limit: int) -> int:
    """The offset after the end of the message at ``start``."""
    at = start
    while at < limit:
        code = rom[at]
        at += byte_length(code)
        if code == END:
            return at
    raise ClassicRetroError(
        ErrorCode.MISSING_TERMINATOR, f"The message at {hirom_address(start):#08x} has no end"
    )


def message_at(rom: bytes, number: int) -> StoredMessage:
    """Message ``number``, from its pointer to its end."""
    address = message_address(rom, number)
    start = hirom_offset(address)
    limit = hirom_offset(DLG_END - 1) + 1
    if not hirom_offset(DLG_TEXT) <= start < limit:
        raise ClassicRetroError(
            ErrorCode.REFERENCE_OUT_OF_BOUNDS, f"Message {number} points outside the text"
        )
    return StoredMessage(number, address, bytes(rom[start : _message_end(rom, start, limit)]))


def messages(rom: bytes) -> tuple[StoredMessage, ...]:
    """Every message, by number."""
    return tuple(message_at(rom, number) for number in range(DLG_COUNT))


def character(code: int) -> str:
    try:
        return CHARACTERS[code]
    except KeyError:
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No character {code:#04x}") from None


def command_notation(code: int, argument: int | None = None) -> str:
    """A command as the notation writes it: ``{Key}``, or ``{Pause 04}`` with its byte."""
    name, length = COMMANDS[code]
    if (argument is None) != (length == 1):
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"{{{name}}} takes {'a byte' if length == 2 else 'no byte'}",
        )
    return f"{{{name}}}" if argument is None else f"{{{name} {argument:02X}}}"


def _command_at(data: bytes, at: int) -> tuple[int, int | None, int]:
    """The command at ``at``: its code, its byte (or None) and its length."""
    code = data[at]
    length = COMMANDS[code][1]
    if at + length > len(data):
        raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"Command {code:#04x} lacks its byte")
    return code, data[at + 1] if length == 2 else None, length


def command_skeleton(data: bytes) -> tuple[str, ...]:
    """The message's commands in order, in the notation, but the layout commands.

    ``data`` is a message with its end or without; every byte that is not a
    command (a letter, a pair, an icon, an Arabic glyph) is skipped.
    """
    skeleton: list[str] = []
    at = 0
    while at < len(data):
        code = data[at]
        if code == END:
            break
        if code not in COMMANDS:
            at += 1
            continue
        code, argument, length = _command_at(data, at)
        if code not in LAYOUT_COMMANDS:
            skeleton.append(command_notation(code, argument))
        at += length
    return tuple(skeleton)


def message_notation(data: bytes, pairs: dict[int, str]) -> str:
    """A message's notation (``data`` with its end or without)."""
    text = []
    at = 0
    while at < len(data):
        code = data[at]
        if code == END:
            break
        if code in COMMANDS:
            code, argument, length = _command_at(data, at)
            text.append(command_notation(code, argument))
            at += length
        elif code in CHARACTERS:
            text.append(CHARACTERS[code])
            at += 1
        elif code in ICONS:
            text.append(f"{{{ICONS[code]}}}")
            at += 1
        elif code in pairs:
            text.append(pairs[code])
            at += 1
        else:
            raise ClassicRetroError(
                ErrorCode.UNKNOWN_TEXT_BYTE, f"No code {code:#04x} in a message"
            )
    return "".join(text)


def glyph_rows(rom: bytes, code: int) -> tuple[int, ...]:
    """A letter's glyph from the ROM's font: eleven words, the leftmost pixel in bit 15."""
    if not FIRST_LETTER <= code < FONT_WIDTH_COUNT:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No glyph for {code:#04x}")
    at = hirom_offset(LARGE_FONT) + (code - FIRST_LETTER) * GLYPH_BYTES
    return struct.unpack_from(f"<{GLYPH_ROWS}H", rom, at)
