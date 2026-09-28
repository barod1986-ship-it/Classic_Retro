"""Text engine of *The Legend of Zelda: A Link to the Past* (Super NES): the dialogue.

The messages are stored one after another, with no table: the game finds each
message's start when it boots (``CreateMessagePointers``), from
``MESSAGE_DATA`` ($1C:8000) on, going on at ``MESSAGE_DATA_EXTRA`` ($0E:DF40)
where a message starts with ``SWITCH_BANK``, until ``FINISH``. A message is
numbered by its place in that order. Its bytes are:

- ``00``-``62`` a character of the dialogue font (``CHARACTERS``): capitals,
  small letters, digits, signs, the pad's buttons and arrows, hearts, the space
  (``59``);
- ``67``-``7E`` a command (``COMMANDS``), some followed by a byte of their own:
  the line to write on (``74``-``76``), a scroll to a new last line (``73``), a
  wait for the button (``7E``), a pause, the typing speed, the window's kind and
  place, a colour, a sound, the player's name (``6A``), a number (``6C``), the
  choices of an answer;
- ``7F`` the message's end;
- ``88``-``E8`` a word of the dictionary (``WORD_DICTIONARY``: 97 pointers into
  its bank, each word running to the next's start).

To show a message the game first writes it out into a buffer, a byte a
character (its dictionary words and the player's name written out), then draws
the buffer a character a frame. The names follow the spannerisms/usdasm
disassembly.

A message's notation writes its characters as text, a dictionary word as its
characters, a sign of the font that is not a letter as a ``{token}`` and a
command as a ``{token}`` too, with its byte as two hex digits.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

# LoROM: bank $00 is the ROM's first 32 KiB, at $8000-$FFFF; so is each next bank.
MESSAGE_DATA = 0x0E0000  # $1C:8000
MESSAGE_DATA_EXTRA = 0x075F40  # $0E:DF40
WORD_DICTIONARY = 0x074703  # $0E:C703: 97 pointers into bank $0E, then the last word's end
DICTIONARY_BANK = 0x070000 - 0x8000
DICTIONARY_CODES = range(0x88, 0x88 + 97)
FIRST_COMMAND = 0x67
END = 0x7F
SWITCH_BANK = 0x80
FINISH = 0xFF
SPACE = 0x59
# The dialogue font's characters by code; a sign that is not a letter is a token.
CHARACTERS: tuple[str, ...] = (
    *"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!?-.,…>()",
    "{Ankh}",
    "{Waves}",
    "{Snake}",
    "{LinkL}",
    "{LinkR}",
    '"',
    "{Up}",
    "{Down}",
    "{Left}",
    "{Right}",
    "'",
    "{1HeartL}",
    "{1HeartR}",
    "{2HeartL}",
    "{3HeartL}",
    "{3HeartR}",
    "{4HeartL}",
    "{4HeartR}",
    " ",
    "<",
    "{A}",
    "{B}",
    "{X}",
    "{Y}",
    # The name screen's own I, i, ! and space.
    "I",
    "i",
    "!",
    " ",
)
assert len(CHARACTERS) == 0x63
# code: (name, bytes with the command's own)
COMMANDS: dict[int, tuple[str, int]] = {
    0x67: ("NextPic", 1),
    0x68: ("Choose", 1),
    0x69: ("Item", 1),
    0x6A: ("Name", 1),
    0x6B: ("Window", 2),
    0x6C: ("Number", 2),
    0x6D: ("Position", 2),
    0x6E: ("ScrollSpd", 2),
    0x6F: ("Selchg", 1),
    0x70: ("Crash", 1),
    0x71: ("Choose3", 1),
    0x72: ("Choose2", 1),
    0x73: ("Scroll", 1),
    0x74: ("1", 1),
    0x75: ("2", 1),
    0x76: ("3", 1),
    0x77: ("Color", 2),
    0x78: ("Wait", 2),
    0x79: ("Sound", 2),
    0x7A: ("Speed", 2),
    0x7B: ("Mark", 1),
    0x7C: ("Mark2", 1),
    0x7D: ("Clear", 1),
    0x7E: ("Waitkey", 1),
}
COMMAND_CODES = {name: code for code, (name, _) in COMMANDS.items()}
NAME = COMMAND_CODES["Name"]
SCROLL = COMMAND_CODES["Scroll"]
LINE_2 = COMMAND_CODES["2"]
LINE_3 = COMMAND_CODES["3"]
WAIT_KEY = COMMAND_CODES["Waitkey"]


class AlttpEngineAdapter(EngineAdapter):
    id = "snes.alttp-dialogue"
    display_name = "A Link to the Past dialogue"
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


def dictionary(rom: bytes) -> tuple[bytes, ...]:
    """The 97 dictionary words, from code $88."""
    pointers = struct.unpack_from(f"<{len(DICTIONARY_CODES) + 1}H", rom, WORD_DICTIONARY)
    return tuple(
        bytes(rom[DICTIONARY_BANK + start : DICTIONARY_BANK + end])
        for start, end in zip(pointers, pointers[1:], strict=False)
    )


def byte_length(code: int) -> int:
    """How many bytes a code takes with its own."""
    return COMMANDS[code][1] if code in COMMANDS else 1


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A message where it is stored: its ROM offset and its bytes, its end included."""

    offset: int
    data: bytes


def messages(rom: bytes) -> tuple[StoredMessage, ...]:
    """Every message, numbered by its place, found as the game finds them."""
    found: list[StoredMessage] = []
    at = start = MESSAGE_DATA
    while True:
        if at >= len(rom):
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "The messages have no end")
        code = rom[at]
        if code == FINISH:
            return tuple(found)
        if code == SWITCH_BANK:
            at = start = MESSAGE_DATA_EXTRA
            continue
        at += byte_length(code)
        if code == END:
            found.append(StoredMessage(start, bytes(rom[start:at])))
            start = at


def character(code: int) -> str:
    try:
        return CHARACTERS[code]
    except IndexError:
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"No character {code:#04x}") from None


def message_notation(data: bytes, words: tuple[bytes, ...]) -> str:
    """A message's notation (``data`` with its end or without)."""
    text = []
    at = 0
    while at < len(data):
        code = data[at]
        if code == END:
            break
        if code < FIRST_COMMAND:
            text.append(character(code))
            at += 1
        elif code in COMMANDS:
            name, length = COMMANDS[code]
            if at + length > len(data):
                raise ClassicRetroError(
                    ErrorCode.MISSING_TERMINATOR, f"Command {code:#04x} lacks its byte"
                )
            text.append(f"{{{name} {data[at + 1]:02X}}}" if length == 2 else f"{{{name}}}")
            at += length
        elif code in DICTIONARY_CODES:
            text.append("".join(character(byte) for byte in words[code - DICTIONARY_CODES[0]]))
            at += 1
        else:
            raise ClassicRetroError(
                ErrorCode.UNKNOWN_TEXT_BYTE, f"No code {code:#04x} in a message"
            )
    return "".join(text)
