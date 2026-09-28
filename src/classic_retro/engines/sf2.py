"""Text engine of *Shining Force II* (Mega Drive): the dialogue.

The game's 4267 strings are kept in 17 text banks (``TEXT_BANKS_POINTER``
points to their table), 256 a bank: a string's number shifted right 8 is its
bank, and inside the bank the strings follow each other, each a length byte
and that many bytes of Huffman code. A string is decoded a symbol at a time:
the tree for a symbol depends on the symbol before it (``TREE_OFFSETS``, from
``TREE_DATA``; the first symbol's tree is the end's, ``FE``), and a tree is a
string of bits, 0 a branch and 1 a leaf, preorder, whose leaves' symbols are
stored before it in reverse order. A string's bits choose the left branch (0)
or the right (1).

A symbol is:

- ``01`` the space, ``02``-``50`` a character of the dialogue font
  (``CHARACTERS``): digits, capitals, small letters, signs;
- ``EE``-``FD`` a command (``COMMANDS``): ``{DICT}`` the string going on where
  the pen is (a string's first character otherwise starts a new line when the
  pen is not at a line's start), a new line (``{N}``), a wait for the button
  that closes the window (``{W1}``) or keeps it (``{W2}``), a pause, the window
  cleared, a name, an item, a spell, a class or a number the game writes;
  ``{NAME;x}`` and ``{COLOR;x}`` take the next symbol;
- ``FE`` the end.

The names follow the ShiningForceCentral/SF2DISASM disassembly: its tags are
the notation's (``{N}``, ``{W1}``, ``{LEADER}``...), and a string's notation writes
its characters as text and every command as its tag.

A string's command skeleton (``command_skeleton``) is its commands in that
notation, in order, each with its argument, but the layout command
(``LAYOUT_COMMANDS``): the new line, which the Arabic encoder writes itself
as it lays its own lines out. A translation must keep the rest: the waits,
the pauses, the window cleared, the names, items, spells, classes and numbers
the game writes, the colours. The skeleton skips every symbol below the
commands, so it reads an Arabic string (``engines.sf2_arabic``), whose glyph
codes replace the characters, as it reads an English one.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

TEXT_BANKS_POINTER = 0x028000  # p_pt_TextBanks: the address of the banks' table
TEXT_BANKS = 17
STRINGS_PER_BANK = 256
STRINGS = 4267
TREE_OFFSETS = 0x02E196  # TextBankTreeOffsets: a word for each symbol before
TREE_DATA = 0x02E394  # TextBankTreeData
FONT_POINTER = 0x02800C  # p_font_VariableWidth
FONT_GLYPH_BYTES = 32
ASCII_TO_SYMBOL = 0x00666E  # table_AsciiToTextSymbolMap: a symbol for each ASCII byte
SPACE = 0x01
FIRST_COMMAND = 0xEE
END = 0xFE
# The dialogue font's characters, from symbol 01; "" is a symbol no text uses.
CHARACTERS: tuple[str, ...] = (
    " ",
    *"0123456789",
    *"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    *"abcdefghijklmnopqrstuvwxyz",
    "_",
    *"-.,!?",
    "“",
    "”",
    *"'()#%&+/:",
)
assert len(CHARACTERS) == 80
# symbol: (tag, whether the next symbol is its argument)
COMMANDS: dict[int, tuple[str, bool]] = {
    0xEE: ("DICT", False),
    0xEF: ("N", False),
    0xF0: ("D2", False),
    0xF1: ("#", False),
    0xF2: ("NAME", False),
    0xF3: ("LEADER", False),
    0xF4: ("ITEM", False),
    0xF5: ("SPELL", False),
    0xF6: ("CLASS", False),
    0xF7: ("W2", False),
    0xF8: ("D1", False),
    0xF9: ("D3", False),
    0xFA: ("W1", False),
    0xFB: ("CLEAR", False),
    0xFC: ("NAME", True),
    0xFD: ("COLOR", True),
}
TAGS = {tag: symbol for symbol, (tag, argument) in COMMANDS.items() if not argument}
TAGS_WITH_ARGUMENT = {tag: symbol for symbol, (tag, argument) in COMMANDS.items() if argument}
NEW_LINE = TAGS["N"]
# The command the Arabic encoder writes itself, laying its own lines out; a
# translation keeps every other command (``command_skeleton``).
LAYOUT_COMMANDS = frozenset((NEW_LINE,))


class Sf2EngineAdapter(EngineAdapter):
    id = "megadrive.sf2-dialogue"
    display_name = "Shining Force II dialogue"
    platform_ids = ("megadrive",)


def _long(rom: bytes, offset: int) -> int:
    return struct.unpack_from(">I", rom, offset)[0]


def text_banks(rom: bytes) -> tuple[int, ...]:
    """The 17 banks' addresses."""
    table = _long(rom, TEXT_BANKS_POINTER)
    return struct.unpack_from(f">{TEXT_BANKS}I", rom, table)


def string_offset(rom: bytes, index: int) -> int:
    """Where a string's length byte is."""
    if not 0 <= index < STRINGS:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No string {index:#x}")
    at = text_banks(rom)[index // STRINGS_PER_BANK]
    for _ in range(index % STRINGS_PER_BANK):
        at += 1 + rom[at]
    return at


def string_bytes(rom: bytes, index: int) -> bytes:
    """A string's bytes as stored: its length byte and its code."""
    at = string_offset(rom, index)
    return bytes(rom[at : at + 1 + rom[at]])


@dataclass(frozen=True, slots=True)
class HuffmanTrees:
    """The trees, one for each symbol before, and their leaves' symbols."""

    offsets: tuple[int, ...]
    data: bytes

    @classmethod
    def read(cls, rom: bytes) -> HuffmanTrees:
        """The trees from the ROM: the last one ends where the text banks start."""
        count = (TREE_DATA - TREE_OFFSETS) // 2
        offsets = struct.unpack_from(f">{count}H", rom, TREE_OFFSETS)
        return cls(offsets, bytes(rom[TREE_DATA : text_banks(rom)[0]]))

    def decode(self, code: bytes) -> list[int]:
        """The symbols of a string's code, to its end (``FE``) included."""
        bits = _Bits(code)
        symbols: list[int] = []
        previous = END
        while True:
            symbol = self._symbol(previous, bits)
            symbols.append(symbol)
            if symbol == END:
                return symbols
            previous = symbol

    def _symbol(self, previous: int, bits: _Bits) -> int:
        if previous >= len(self.offsets):
            raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No tree after {previous:#04x}")
        start = self.offsets[previous]
        tree = _Bits(self.data[start:])
        skipped = 0
        while True:
            if tree.next():
                if skipped >= start:
                    raise ClassicRetroError(
                        ErrorCode.UNKNOWN_TEXT_BYTE, f"Tree {previous:#04x} runs out of symbols"
                    )
                return self.data[start - 1 - skipped]
            if bits.next():
                pending = 0
                while True:
                    if tree.next():
                        skipped += 1
                        if pending == 0:
                            break
                        pending -= 1
                    else:
                        pending += 1


class _Bits:
    """Bits from the most significant of each byte."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def next(self) -> int:
        byte, bit = divmod(self.at, 8)
        if byte >= len(self.data):
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "A string runs past its code")
        self.at += 1
        return self.data[byte] >> (7 - bit) & 1


def decode_string(rom: bytes, index: int, trees: HuffmanTrees | None = None) -> list[int]:
    """A string's symbols, its end included (an empty string is its length byte 1)."""
    data = string_bytes(rom, index)
    if data[0] == 1:
        return [END]
    return (trees or HuffmanTrees.read(rom)).decode(data[1:])


def character(symbol: int) -> str:
    if not 1 <= symbol <= len(CHARACTERS):
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No character {symbol:#04x}")
    return CHARACTERS[symbol - 1]


def tag_notation(symbol: int, argument: int | None = None) -> str:
    """A command as the notation writes it: ``{W2}``, or ``{NAME;0}`` with its argument."""
    tag, takes_argument = COMMANDS[symbol]
    if (argument is None) == takes_argument:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"{{{tag}}} takes {'an argument' if takes_argument else 'no argument'}",
        )
    return f"{{{tag}}}" if argument is None else f"{{{tag};{argument}}}"


def _command_at(symbols: Sequence[int], at: int) -> tuple[int, int | None, int]:
    """The command at ``at``: its symbol, its argument (or None) and its length."""
    symbol = symbols[at]
    tag, takes_argument = COMMANDS[symbol]
    if not takes_argument:
        return symbol, None, 1
    if at + 1 >= len(symbols):
        raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, f"{{{tag}}} lacks its value")
    return symbol, symbols[at + 1], 2


def command_skeleton(symbols: Sequence[int]) -> tuple[str, ...]:
    """The string's commands in order, in the notation, but the layout commands.

    ``symbols`` are a string's with its end or without; every symbol below the
    commands (a character, an Arabic glyph) is skipped.
    """
    skeleton: list[str] = []
    at = 0
    while at < len(symbols):
        symbol = symbols[at]
        if symbol == END:
            break
        if symbol < FIRST_COMMAND:
            at += 1
            continue
        symbol, argument, length = _command_at(symbols, at)
        if symbol not in LAYOUT_COMMANDS:
            skeleton.append(tag_notation(symbol, argument))
        at += length
    return tuple(skeleton)


def notation(symbols: Sequence[int]) -> str:
    """Symbols (their end included or not) in the notation."""
    text = []
    at = 0
    while at < len(symbols):
        symbol = symbols[at]
        if symbol == END:
            break
        if symbol < FIRST_COMMAND:
            text.append(character(symbol))
            at += 1
            continue
        symbol, argument, length = _command_at(symbols, at)
        text.append(tag_notation(symbol, argument))
        at += length
    return "".join(text)


def font_address(rom: bytes) -> int:
    return _long(rom, FONT_POINTER)


def font_width(rom: bytes, symbol: int) -> int:
    """A character's width in the dialogue font: its first word's low nibble plus one."""
    (word,) = struct.unpack_from(">H", rom, font_address(rom) + (symbol - 1) * FONT_GLYPH_BYTES)
    return (word & 0xF) + 1 if word & 0xF else 0
