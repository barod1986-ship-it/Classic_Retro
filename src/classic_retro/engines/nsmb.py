"""The *New Super Mario Bros.* (Nintendo DS) text engine.

The menus and prompts of the game (the file select, the world map's menu,
the pause menu, the save and quit prompts, the Star Coin gates) are the
messages of three BMG files: ``script/course.bmg`` (the world map),
``script/data.bmg`` (the file select) and ``script/game.bmg`` (a level).
They are UTF-16 texts with line ends and two kinds of escape:

- ``{FF:0000cc00}``: the colour of the glyphs that follow, colour ``cc``
  (0 is the text colour; 1 marks a number, 2 a choice that cannot be taken);
- ``{01:0100}``: a number the game writes in at that place (the Star Coins a
  gate asks for), in the font's digits.

The game draws a message with the font ``font_a.NFTR`` (11x15 cells, two bits
per pixel, of which the glyphs use one value) and a shadow it adds itself,
one pixel right, below and on the diagonal. It lays every line out from the
left and centres it on its own. The font lives in a NARC archive
(``message/common/USA``) inside the ARM9 binary, packed as "LZ77" followed by
BIOS LZ77 data.

A message is written here in a notation: its text, ``\\n`` for a line end and
each escape as ``{KK:argument}`` in hex, as above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.bmg import BmgEscape, Piece

COLOUR = 0xFF
NUMBER = 0x01
NEWLINE = "\n"
MESSAGE_FILES = ("script/course.bmg", "script/data.bmg", "script/game.bmg")
FONT_ARCHIVE = "message/common/USA"
FONT_FILE = f"{FONT_ARCHIVE}/font_a.NFTR"
# The font's cell and the magic before its packed data.
CELL_WIDTH = 11
CELL_HEIGHT = 15
PACKED_MAGIC = b"LZ77"

_ESCAPE = re.compile(r"\{([0-9A-F]{2}):([0-9A-F]*)\}")


class NsmbEngineAdapter(EngineAdapter):
    id = "nds.nsmb"
    display_name = "New Super Mario Bros. DS text engine (BMG messages, NFTR font)"
    platform_ids = ("nds",)


def colour_escape(colour: int) -> BmgEscape:
    return BmgEscape(COLOUR, b"\x00\x00" + colour.to_bytes(2, "little"))


def escape_colour(escape: BmgEscape) -> int | None:
    """The colour an escape sets, or None when it sets none."""
    if escape.kind == COLOUR and len(escape.argument) == 4 and escape.argument[:2] == b"\0\0":
        return int.from_bytes(escape.argument[2:], "little")
    return None


def parse_notation(text: str) -> tuple[Piece, ...]:
    """A message from its notation; braces only ever open an escape."""
    pieces: list[Piece] = []
    position = 0
    for match in _ESCAPE.finditer(text):
        _plain(text[position : match.start()], pieces)
        argument = match.group(2)
        if len(argument) % 2:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Odd escape argument in {match.group(0)}"
            )
        pieces.append(BmgEscape(int(match.group(1), 16), bytes.fromhex(argument)))
        position = match.end()
    _plain(text[position:], pieces)
    return tuple(pieces)


def _plain(text: str, pieces: list[Piece]) -> None:
    if "{" in text or "}" in text:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"Braces open escapes ({{KK:argument}}), not text: {text!r}",
        )
    if text:
        pieces.append(text)


def text_notation(pieces: Sequence[Piece]) -> str:
    return "".join(piece if isinstance(piece, str) else piece.notation for piece in pieces)


def notation_skeleton(pieces: Sequence[Piece]) -> tuple[str, ...]:
    """The escapes and line ends of a message, in order."""
    skeleton: list[str] = []
    for piece in pieces:
        if isinstance(piece, BmgEscape):
            skeleton.append(piece.notation)
        else:
            skeleton.extend(NEWLINE * piece.count(NEWLINE))
    return tuple(skeleton)


def split_lines(pieces: Sequence[Piece]) -> list[list[Piece]]:
    """A message's lines; an escape stays on the line where it stands."""
    lines: list[list[Piece]] = [[]]
    for piece in pieces:
        if isinstance(piece, BmgEscape):
            lines[-1].append(piece)
            continue
        parts = piece.split(NEWLINE)
        for number, part in enumerate(parts):
            if number:
                lines.append([])
            if part:
                lines[-1].append(part)
    return lines
