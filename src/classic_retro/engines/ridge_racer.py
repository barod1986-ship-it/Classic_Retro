"""Text engine of *Ridge Racer* (PlayStation): the program's strings.

Ridge Racer keeps the text of its menus and messages in its program,
SCUS-943.00, as zero-ended strings, each padded with zeros to the next word,
and draws them with two routines of the program: the small font's (a sprite of
8x8 pixels a character, 8 apart) and the large font's (16x16, 16 apart). Each
takes the string's place on the screen, the string and a palette. A
character's code, from the space (0x20), picks the character's cell in the
routine's table; the space itself is not drawn, but moves the pen on.

The strings hold capitals, digits and signs. In the small font four lowercase
letters draw the buttons of a controller (``BUTTONS``): a, b and d the
triangle, the square and the circle of the PlayStation's pad, and c the II of
the NeGcon's. A string's notation is its text with each button as the symbol
it draws.
"""

from __future__ import annotations

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

BUTTONS = {ord("a"): "△", ord("b"): "□", ord("c"): "Ⅱ", ord("d"): "○"}
WORD = 4


class RidgeRacerEngineAdapter(EngineAdapter):
    id = "ps1.ridge-racer-strings"
    display_name = "Ridge Racer program strings"
    platform_ids = ("ps1",)


def program_string(data: bytes, offset: int) -> bytes:
    """The string at ``offset``, up to its zero."""
    end = data.find(b"\x00", offset)
    if not 0 <= offset < len(data) or end < 0:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No string at offset {offset:#x}")
    return data[offset:end]


def string_room(data: bytes, offset: int) -> int:
    """The bytes a string may take: its own, its zero and the zeros after it up to the
    next word. ``offset`` counts from a word boundary, as the program's addresses do."""
    end = offset + len(program_string(data, offset)) + 1
    while end % WORD and end < len(data) and data[end] == 0:
        end += 1
    return end - offset


def string_notation(data: bytes) -> str:
    """A string's text, its buttons as the symbols they draw."""
    text = []
    for code in data:
        if not 0x20 <= code < 0x7F:
            raise ClassicRetroError(
                ErrorCode.UNKNOWN_TEXT_BYTE, f"Byte {code:#04x} is not a character of the fonts"
            )
        text.append(BUTTONS.get(code, chr(code)))
    return "".join(text)
