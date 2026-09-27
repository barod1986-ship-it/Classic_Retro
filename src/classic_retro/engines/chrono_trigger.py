"""Text engine of *Chrono Trigger* (Super NES): the dialogue.

The game's dialogue is kept in string tables: a table is a run of 16-bit
pointers into its own bank, each to a string that ends with a zero; an event
names the table (a 24-bit address) and a string by its number. A string's
bytes are:

- ``00`` its end;
- ``01``-``02`` then a byte: a character of two bytes (the Japanese kanji's
  codes; the US script does not use them in dialogue);
- ``03`` then a byte: a pause of that many frames;
- ``05`` a new line, ``06`` a new line indented under a speaker's name;
  ``0B`` a new box, ``0C`` a new box indented; ``07``-``0A`` the same, the
  line or box kept waiting for the player's button;
- ``0D``-``0F`` a number and ``11`` a character's name, from the event's own
  values; ``12`` then a byte: a technique's or an enemy's name, or a word;
- ``13``-``19`` the party's names (Crono, Marle, Lucca, Robo, Frog, Ayla,
  Magus), ``1A`` Crono's again (from his name's own address), ``1B``-``1D``
  the party's members in battle order, ``1E`` Nadia, the princess's own name,
  ``1F`` an item's name, ``20`` the flying time machine's (the Epoch's);
- ``21``-``9F`` a word of the substring dictionary (``DICTIONARY_TABLE``: 127
  pointers into its bank, each to a length byte and that many characters);
- ``A0``-``FF`` a character of the dialogue font: capitals, small letters,
  digits, then signs (``CHARACTERS``).

A string's notation writes its characters as text, a dictionary word as its
characters and every other code as a ``{token}``. The codes' routines are in
the table at $C2:5903 (``TextCtrlCodeTable`` in the dscotton/ct_disassembly
disassembly).
"""

from __future__ import annotations

import struct

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

# $DE:FA00: the substring dictionary's pointer table, its entries in bank $DE.
DICTIONARY_TABLE = 0x1EFA00
DICTIONARY_BANK = 0x1E0000
DICTIONARY_CODES = range(0x21, 0xA0)
FIRST_CHARACTER = 0xA0
# The dialogue font's characters from $A0: letters, digits, signs; "" is none.
CHARACTERS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!?/“”:&()'.,=-+%♪ ♥…∞#"
) + "\x00" * 12
assert len(CHARACTERS) == 0x60
END = 0x00
PAUSE = 0x03
LINE = 0x05
LINE_INDENTED = 0x06
BOX = 0x0B
BOX_INDENTED = 0x0C
NAMES = {
    0x13: "Crono",
    0x14: "Marle",
    0x15: "Lucca",
    0x16: "Robo",
    0x17: "Frog",
    0x18: "Ayla",
    0x19: "Magus",
}
TOKENS = {
    LINE: "line",
    LINE_INDENTED: "line+",
    BOX: "box",
    BOX_INDENTED: "box+",
    0x07: "line wait",
    0x08: "line+ wait",
    0x09: "box wait",
    0x0A: "box+ wait",
    0x1A: "Crono",
    0x1B: "member 1",
    0x1C: "member 2",
    0x1D: "member 3",
    0x1E: "Nadia",
    0x1F: "item",
    0x20: "Epoch",
    **NAMES,
}
# Codes followed by one byte of their own.
WITH_BYTE = frozenset((0x01, 0x02, PAUSE, 0x12))


class ChronoTriggerEngineAdapter(EngineAdapter):
    id = "snes.chrono-trigger-dialogue"
    display_name = "Chrono Trigger dialogue"
    platform_ids = ("snes",)


def dictionary(rom: bytes) -> tuple[bytes, ...]:
    """The 127 dictionary words, from code $21."""
    pointers = struct.unpack_from(f"<{len(DICTIONARY_CODES)}H", rom, DICTIONARY_TABLE)
    words = []
    for pointer in pointers:
        at = DICTIONARY_BANK + pointer
        words.append(bytes(rom[at + 1 : at + 1 + rom[at]]))
    return tuple(words)


def string_bytes(rom: bytes, offset: int) -> bytes:
    """A string's bytes from ``offset`` to its zero, included."""
    at = offset
    while at < len(rom):
        code = rom[at]
        if code == END:
            return bytes(rom[offset : at + 1])
        at += 2 if code in WITH_BYTE else 1
    raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"No end to the string at {offset:#x}")


def character(code: int) -> str:
    text = CHARACTERS[code - FIRST_CHARACTER]
    if text == "\x00":
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No character {code:#04x}")
    return text


def string_notation(data: bytes, words: tuple[bytes, ...]) -> str:
    """A string's notation (``data`` without its zero, or with it)."""
    text = []
    at = 0
    while at < len(data):
        code = data[at]
        at += 1
        if code == END:
            break
        if code >= FIRST_CHARACTER:
            text.append(character(code))
        elif code in DICTIONARY_CODES:
            text.append("".join(character(byte) for byte in words[code - DICTIONARY_CODES[0]]))
        elif code in WITH_BYTE:
            if at >= len(data):
                raise ClassicRetroError(
                    ErrorCode.MISSING_TERMINATOR, f"Code {code:#04x} lacks its byte"
                )
            name = "pause" if code == PAUSE else f"code {code:02X}"
            text.append(f"{{{name} {data[at]:02X}}}")
            at += 1
        elif code in TOKENS:
            text.append(f"{{{TOKENS[code]}}}")
        else:
            text.append(f"{{code {code:02X}}}")
    return "".join(text)


def table_string(rom: bytes, table: int, index: int) -> int:
    """The file offset of string ``index`` of the table at file offset ``table``."""
    (pointer,) = struct.unpack_from("<H", rom, table + 2 * index)
    return (table & ~0xFFFF) + pointer
