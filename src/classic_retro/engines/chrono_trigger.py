"""Text engine of *Chrono Trigger* (Super NES): the dialogue.

The game's dialogue is kept in string tables: a table is a run of 16-bit
pointers into its own bank, each to a string that ends with a zero; an event
names the table (a 24-bit address) and a string by its number. A string's
bytes are:

- ``00`` its end;
- ``01``-``02`` then a byte: a character of two bytes (the Japanese kanji's
  codes; the US script does not use them in dialogue);
- ``03`` then a byte: a pause of fifteen frames that many times; ``03 00``
  closes the box where it stands, and a table may name the bytes after it
  as a message of its own (the opening's first string runs on through the
  next five, a pause of nothing between each);
- ``05`` a new line, ``06`` a new line indented under a speaker's name;
  ``0B`` a new box, ``0C`` a new box indented, each after the player's
  button; ``09`` and ``0A`` a new box at once, without the button (after a
  pause, in a timed scene); ``07`` and ``08`` a new line, plain or
  indented, after the player's button, the box kept, which the dialogue
  never uses;
- ``0D``-``0F`` a number and ``11`` a character's name, from the event's own
  values; ``12`` then a byte: a technique's or an enemy's name, or a word;
- ``13``-``19`` the party's names (Crono, Marle, Lucca, Robo, Frog, Ayla,
  Magus), ``1A`` Crono's again (from his name's own address), ``1B``-``1D``
  the party's members in battle order, ``1E`` the word "Nadia", the
  princess's own name, ``1F`` an item's name, ``20`` the flying time
  machine's (the Epoch's);
- ``21``-``9F`` a word of the substring dictionary (``DICTIONARY_TABLE``: 127
  pointers into its bank, each to a length byte and that many characters);
- ``A0``-``FF`` a character of the dialogue font: capitals, small letters,
  digits, then signs (``CHARACTERS``).

A string's notation writes its characters as text, a dictionary word as its
characters and every other code as a ``{token}``. The codes' routines are in
the table at $C2:5903 (``TextCtrlCodeTable`` in the dscotton/ct_disassembly
disassembly).

A string's command skeleton (``command_skeleton``) is its codes below the
dictionary in that notation, in order, each with its byte, but the layout
codes (``LAYOUT_CODES``): the new line and the new box after the button,
plain or indented, which the Arabic encoder writes itself as it lays its
own lines and boxes out; nor the characters of two bytes
(``WIDE_CHARACTERS``) and the word "Nadia" (``WORD_CODES``), which are text.
A box without the button and a line after it (``KEPT_CODES``) are kept,
plain: the encoder decides their indent as it does the others'. A
translation must keep the rest: the pauses, the names, the numbers, the
words and any code it cannot write. The skeleton skips every byte from the
dictionary on, so it reads an Arabic string (``engines.chrono_trigger_arabic``),
whose glyph codes replace the characters and dictionary words, as it reads an
English one.

A table's strings are named by their number in it (``table_count``: how
many, from its first pointer, which points just past the table).
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
LINE_WAIT = 0x07
LINE_WAIT_INDENTED = 0x08
BOX_AUTO = 0x09
BOX_AUTO_INDENTED = 0x0A
BOX = 0x0B
BOX_INDENTED = 0x0C
NADIA = 0x1E
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
    LINE_WAIT: "line wait",
    LINE_WAIT_INDENTED: "line+ wait",
    BOX_AUTO: "box auto",
    BOX_AUTO_INDENTED: "box+ auto",
    BOX: "box",
    BOX_INDENTED: "box+",
    0x1A: "Crono",
    0x1B: "member 1",
    0x1C: "member 2",
    0x1D: "member 3",
    NADIA: "Nadia",
    0x1F: "item",
    0x20: "Epoch",
    **NAMES,
}
# Codes followed by one byte of their own.
WITH_BYTE = frozenset((0x01, 0x02, PAUSE, 0x12))
# The characters of two bytes: text, not commands.
WIDE_CHARACTERS = frozenset((0x01, 0x02))
# The codes the Arabic encoder writes itself, laying its own lines and boxes
# out; a translation keeps every other code (``command_skeleton``).
LAYOUT_CODES = frozenset((LINE, LINE_INDENTED, BOX, BOX_INDENTED))
# A box without the button and a new line after the button (the box kept),
# which a translation keeps, and the plain code the skeleton writes each as:
# the encoder chooses the indent.
KEPT_CODES = {
    LINE_WAIT: LINE_WAIT,
    LINE_WAIT_INDENTED: LINE_WAIT,
    BOX_AUTO: BOX_AUTO,
    BOX_AUTO_INDENTED: BOX_AUTO,
}
# Codes that write a fixed word of the game's: text, which a translation
# writes in Arabic.
WORD_CODES = frozenset((NADIA,))


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


def code_notation(code: int, argument: int | None = None) -> str:
    """A code below the dictionary as the notation writes it: ``{line+}``, ``{Lucca}``,
    ``{pause 0F}`` with its byte, ``{code 10}`` for one without a name."""
    if (argument is None) == (code in WITH_BYTE):
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"Code {code:#04x} takes {'a byte' if code in WITH_BYTE else 'no byte'}",
        )
    if argument is not None:
        name = "pause" if code == PAUSE else f"code {code:02X}"
        return f"{{{name} {argument:02X}}}"
    return f"{{{TOKENS[code]}}}" if code in TOKENS else f"{{code {code:02X}}}"


def _code_at(data: bytes, at: int) -> tuple[int, int | None, int]:
    """The code at ``at``: itself, its byte (or None) and its length."""
    code = data[at]
    if code not in WITH_BYTE:
        return code, None, 1
    if at + 1 >= len(data):
        raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"Code {code:#04x} lacks its byte")
    return code, data[at + 1], 2


def command_skeleton(data: bytes) -> tuple[str, ...]:
    """The string's commands in order, in the notation, but the layout codes and the
    characters of two bytes.

    ``data`` is a string with its zero or without; every byte from the
    dictionary on (a word, a character, an Arabic glyph) is skipped.
    """
    skeleton: list[str] = []
    at = 0
    while at < len(data):
        code = data[at]
        if code == END:
            break
        if code >= DICTIONARY_CODES[0]:
            at += 1
            continue
        code, argument, length = _code_at(data, at)
        if code not in LAYOUT_CODES and code not in WIDE_CHARACTERS and code not in WORD_CODES:
            skeleton.append(code_notation(KEPT_CODES.get(code, code), argument))
        at += length
    return tuple(skeleton)


def string_notation(data: bytes, words: tuple[bytes, ...]) -> str:
    """A string's notation (``data`` without its zero, or with it)."""
    text = []
    at = 0
    while at < len(data):
        code = data[at]
        if code == END:
            break
        if code >= FIRST_CHARACTER:
            text.append(character(code))
            at += 1
        elif code in DICTIONARY_CODES:
            text.append("".join(character(byte) for byte in words[code - DICTIONARY_CODES[0]]))
            at += 1
        else:
            code, argument, length = _code_at(data, at)
            text.append(code_notation(code, argument))
            at += length
    return "".join(text)


def table_string(rom: bytes, table: int, index: int) -> int:
    """The file offset of string ``index`` of the table at file offset ``table``."""
    (pointer,) = struct.unpack_from("<H", rom, table + 2 * index)
    return (table & ~0xFFFF) + pointer


def table_count(rom: bytes, table: int) -> int:
    """How many strings the table at file offset ``table`` names: its first pointer
    points just past its last entry."""
    (pointer,) = struct.unpack_from("<H", rom, table)
    start = table & 0xFFFF
    if pointer <= start or (pointer - start) % 2:
        raise ClassicRetroError(
            ErrorCode.INVALID_TEXT_TABLE, f"No string table at {table:#x}: its first pointer"
        )
    return (pointer - start) // 2
