"""Text engine of *Final Fantasy II* (USA, Super NES): the field dialogue.

The dialogue is kept in three banks (``BANKS``), each a table of 16-bit
offsets from the bank's text, then the text: the map dialogue (bank 0, what
the townspeople say, a map's messages one after another from its table
entry), and two banks of event dialogue (banks 1 and 2, the story's, a table
entry a message). The engine keeps the bank's number in ``$DD`` and the next
byte's offset in ``$0772``, and reads a byte with ``GetByte`` (``lda
f:MapDlg,x``). A message's bytes are:

- ``00`` its end: the window waits for the button and closes; ``06`` its end
  too, the window closing at once;
- ``01`` the end of a row (the rest of it spaces), ``09`` an empty row (or
  the rest of this one), ``02`` then a byte: that many spaces;
- ``03`` then a byte: a song; ``04`` then a byte: a character's name (six
  letters at most); ``05`` then a byte: a pause; ``07`` the item's name;
  ``08`` the gil amount (``COMMANDS``);
- ``42``-``5B`` the capitals, ``5C``-``75`` the small letters, ``80``-``89``
  the digits, ``C0``-``C9`` the signs, ``FF`` the space (``CHARACTERS``);
  ``21``-``41`` and ``79``-``7F`` icons (``ICONS``), ``15`` a blank tile;
- ``8A``-``BF`` and ``CA``-``FE`` a pair of letters (``DTE_CODES``) from the
  table at ``DTE_TABLE`` (``dte_pairs``).

The game decodes a message into a buffer of four rows of ``ROW`` (26) codes,
a code a tile of the dialogue font (``FONT``: 256 tiles of two bits a pixel,
copied whole to the tiles of the third background), and sends the buffer to
the tilemap a row at a time with a blank row above each. When the four rows
are full the page is shown; the message goes on from where it stopped when
the player presses the button. The names follow the everything8215/ff4
disassembly (``field/window.asm``).

A message's notation writes its characters as text, a pair of letters as its
letters, an icon as a ``{token}`` and a command as a ``{token}`` too, with its
byte as two hex digits: ``{line}``, ``{blank}``, ``{Spaces 03}``, ``{Song 2A}``,
``{Name 00}``, ``{Wait 10}``, ``{Item}``, ``{Gil}``, and ``{Close}`` for the
end that closes at once.

A message's command skeleton (``command_skeleton``) is its commands in that
notation, in order, but the layout commands (``LAYOUT_COMMANDS``): the row's
end, the empty row and the spaces, which the Arabic encoder writes itself as
it lays its own rows and pages out. A translation must keep the rest: the
songs, the names, the pauses, the item, the gil and the end that closes at
once. The skeleton skips every byte that is not a command, so it reads an
Arabic message (``engines.ff4_arabic``), whose glyph codes replace the
letters and pairs, as it reads an English one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

# The dialogue font: 256 tiles of 16 bytes at $0A:F000, the tile a code.
FONT = 0x0AF000
FONT_TILE_BYTES = 16
FONT_TILES = 0x100
# The pairs of letters: two bytes a code from $80 at $13:9700 (codes below $8A unused).
DTE_TABLE = 0x139700
DTE_FIRST = 0x80
DTE_CODES = tuple(range(0x8A, 0xC0)) + tuple(range(0xCA, 0xFF))
# The buffer: four rows of 26 codes a page.
ROW = 26
ROWS = 4
PAGE = ROW * ROWS
END = 0x00
CLOSE = 0x06
SPACE = 0xFF
BLANK_TILE = 0x15
# code: (name, bytes with the command's own)
COMMANDS: dict[int, tuple[str, int]] = {
    0x01: ("line", 1),
    0x02: ("Spaces", 2),
    0x03: ("Song", 2),
    0x04: ("Name", 2),
    0x05: ("Wait", 2),
    0x06: ("Close", 1),
    0x07: ("Item", 1),
    0x08: ("Gil", 1),
    0x09: ("blank", 1),
}
COMMAND_CODES = {name: code for code, (name, _) in COMMANDS.items()}
LINE = COMMAND_CODES["line"]
BLANK = COMMAND_CODES["blank"]
NAME = COMMAND_CODES["Name"]
ITEM = COMMAND_CODES["Item"]
GIL = COMMAND_CODES["Gil"]
# The commands the Arabic encoder writes itself; a translation keeps every other.
LAYOUT_COMMANDS = frozenset((LINE, COMMAND_CODES["Spaces"], BLANK))
TERMINATORS = frozenset((END, CLOSE))
# How many tiles the game writes for a name, an item and the gil amount at most.
NAME_CELLS = 6
ITEM_CELLS = 9
GIL_CELLS = 6
CHARACTERS: dict[int, str] = {
    **{0x42 + number: letter for number, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
    **{0x5C + number: letter for number, letter in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{0x80 + number: digit for number, digit in enumerate("0123456789")},
    0xC0: "'",
    0xC1: ".",
    0xC2: "-",
    0xC3: "…",
    0xC4: "!",
    0xC5: "?",
    0xC6: "%",
    0xC7: "/",
    0xC8: ":",
    0xC9: ",",
    SPACE: " ",
}
CHARACTER_CODES = {character: code for code, character in CHARACTERS.items()}
ICONS: dict[int, str] = {
    BLANK_TILE: "Blank",
    **dict(
        enumerate(
            (
                "Petrify Frog Mini Pig Mute Darkness Poison Float Claw Rod Staff DarkSword "
                "Sword Paladin Spear Knife Katana Star Boomerang Axe Wrench Music Bow Arrow "
                "Hammer Whip Shield Helmet Armor Glove Black White Call"
            ).split(),
            start=0x21,
        )
    ),
    **dict(enumerate("Tent Potion Dress Ring Crystal Key Tail".split(), start=0x79)),
}
ICON_CODES = {name: code for code, name in ICONS.items()}
# Codes the tilemap shows left to right even in an Arabic message: the icons and
# the digits (the gil amount's). The letters' codes are Arabic glyphs there.
ISLAND_CODES = frozenset(range(0x21, 0x42)) | frozenset(range(0x79, 0x8A))


@dataclass(frozen=True, slots=True)
class DialogueBank:
    """A bank of the dialogue: the engine's number for it, its table of offsets and
    the text they count from (LoROM addresses), and where its text ends."""

    number: int
    name: str
    pointers: int
    entries: int
    text: int
    end: int  # the address after the last message's end

    def table(self, rom: bytes) -> tuple[int, ...]:
        at = lorom_offset(self.pointers)
        return struct.unpack_from(f"<{self.entries}H", rom, at)


# The map dialogue ($11:8000: 384 entries, a map's messages from each) and the
# event dialogue ($10:8000: 512 entries; $13:A500: 256 entries); each bank's text
# ends with an empty message, then padding ($FF).
BANKS = (
    DialogueBank(0, "map", 0x118000, 384, 0x118300, 0x11FFFB),
    DialogueBank(1, "event1", 0x108000, 512, 0x108400, 0x10FE21),
    DialogueBank(2, "event2", 0x13A500, 256, 0x13A700, 0x13CD90),
)
BANK_BY_NUMBER = {bank.number: bank for bank in BANKS}


class Ff4EngineAdapter(EngineAdapter):
    id = "snes.ff4-dialogue"
    display_name = "Final Fantasy II dialogue"
    platform_id = "snes"


def lorom_offset(address: int) -> int:
    """A LoROM address ($bb:8000-$bb:FFFF, bank $00-$7D or $80-$FF) as a ROM offset."""
    bank, low = address >> 16 & 0x7F, address & 0xFFFF
    if low < 0x8000:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"${address:06X} is not in the ROM")
    return bank * 0x8000 + low - 0x8000


def lorom_address(offset: int) -> int:
    """A ROM offset as its LoROM address in banks $00-$7D."""
    return (offset // 0x8000) << 16 | 0x8000 | offset % 0x8000


def dte_pairs(rom: bytes) -> dict[int, str]:
    """The pair of letters of every pair code, from the ROM's table."""
    at = lorom_offset(DTE_TABLE)
    pairs = {}
    for code in DTE_CODES:
        first, second = rom[at + 2 * (code - DTE_FIRST) : at + 2 * (code - DTE_FIRST) + 2]
        pairs[code] = character(first) + character(second)
    return pairs


def byte_length(code: int) -> int:
    """How many bytes a code takes with its own."""
    return COMMANDS[code][1] if code in COMMANDS else 1


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A message where it is stored: its bank, its offset from the bank's text (what
    the engine's ``$0772`` holds at its start) and its bytes, its end included."""

    bank: int
    offset: int
    data: bytes

    @property
    def address(self) -> int:
        return BANK_BY_NUMBER[self.bank].text + self.offset


def _message_end(rom: bytes, start: int, limit: int) -> int:
    """The offset after the terminator of the message at ``start``."""
    at = start
    while at < limit:
        code = rom[at]
        at += byte_length(code)
        if code in TERMINATORS:
            return at
    raise ClassicRetroError(
        ErrorCode.MISSING_TERMINATOR, f"The message at {lorom_address(start):#08x} has no end"
    )


def messages(rom: bytes, bank: int) -> tuple[StoredMessage, ...]:
    """Every message of the bank, in the order of their offsets: from each table entry
    to the next entry's start (a map's messages one after another) or the text's end."""
    dialogue = BANK_BY_NUMBER[bank]
    text = lorom_offset(dialogue.text)
    limit = lorom_offset(dialogue.end - 1) + 1
    starts = sorted({text + offset for offset in dialogue.table(rom)})
    if starts and not text <= starts[-1] < limit:
        raise ClassicRetroError(
            ErrorCode.REFERENCE_OUT_OF_BOUNDS,
            f"A {dialogue.name} dialogue entry points outside the text",
        )
    found: list[StoredMessage] = []
    for start, stop in zip(starts, [*starts[1:], limit], strict=True):
        at = start
        while at < stop:
            end = _message_end(rom, at, limit)
            found.append(StoredMessage(bank, at - text, bytes(rom[at:end])))
            at = end
    return tuple(found)


def message_at(rom: bytes, bank: int, offset: int) -> StoredMessage:
    """The message that starts at ``offset`` of the bank's text."""
    for message in messages(rom, bank):
        if message.offset == offset:
            return message
    raise ClassicRetroError(
        ErrorCode.INVALID_REFERENCE, f"No message starts at {offset:#06x} of bank {bank}"
    )


def character(code: int) -> str:
    try:
        return CHARACTERS[code]
    except KeyError:
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No character {code:#04x}") from None


def command_notation(code: int, argument: int | None = None) -> str:
    """A command as the notation writes it: ``{Item}``, or ``{Wait 10}`` with its byte."""
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
    command (a character, a pair, an icon, an Arabic glyph) is skipped. An end
    that closes at once is a command (``{Close}``).
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
        if code == CLOSE:
            break
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
            if code == CLOSE:
                break
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
