"""The *The Legend of Zelda: Phantom Hourglass* (Nintendo DS) text engine.

Every text of the game is a message of a BMG file, one set per language
(``English/Message/*.bmg``, ``French/...``, ``Spanish/...``): UTF-16 texts
with line ends and escapes, written here in the BMG notation (``text.bmg``).
An escape's kind and the first two bytes of its argument are the game's code
for it. The prologue (``demo.bmg``, messages 0 to 6) uses four:

- ``{01:0A00nnnn}``, ``{01:0E00nnnn}``: the typewriter waits ``nnnn``
  frames (``0E``, the longer waits, mostly ends a page);
- ``{01:1400nnnn}``: the typewriter's pace;
- ``{FF:0000cc00}``: the colour of the glyphs that follow (0 is the text's
  white, 3 the blue of a name).

The player's name is ``{FE:0000}``. Every font is an NFTR file in ``Font``;
the messages use ``zeldaDS_15.nftr``: 14x16 cells of two bits per pixel, three
ink levels (1 to 3, 3 the full colour) that smooth the letters, no shadow, a
line feed of 16 pixels.

A message box is a printer (``UnkStruct_02032f0c`` in zeldaret/ph) that draws
into a NitroSystem character canvas. It lays a line out from the left: its pen
starts at the line's start and moves by each glyph's advance and the letter
spacing (``+0x30``), and a line end moves it down by the line feed and the
line spacing (``+0x34``). The prologue's box is 224 pixels wide (``+0x4A``, a
canvas of 28x8 characters of 4 bits), its pen starts 9 pixels in, letters are
1 pixel apart and lines 2. It shows three lines: the line end after a
page's third line clears the box and starts the next page at the top. The
typewriter draws a glyph at a time, each through ``func_020296e0``
(NitroSystem's ``NNS_G2dCharCanvasDrawChar``) from ``func_020334b4``.
"""

from __future__ import annotations

from collections.abc import Sequence

from classic_retro.adapters.base import EngineAdapter
from classic_retro.text.bmg import BmgEscape, Piece, split_lines

DEMO_MESSAGES = "English/Message/demo.bmg"
FONT_FILE = "Font/zeldaDS_15.nftr"
CELL_WIDTH = 14
CELL_HEIGHT = 16
LINE_FEED = 16
# The prologue's printer: its canvas, where its pen starts, its spacings and
# the lines a page holds.
BOX_WIDTH = 224
PEN_START = 9
LETTER_SPACING = 1
LINE_SPACING = 2
PAGE_LINES = 3

TIMING = 0x01
COLOUR = 0xFF


class PhantomHourglassEngineAdapter(EngineAdapter):
    id = "nds.zelda-ph"
    display_name = "The Legend of Zelda: Phantom Hourglass text engine (BMG messages, NFTR font)"
    platform_ids = ("nds",)


def escape_code(escape: BmgEscape) -> int | None:
    """The game's code for an escape (kind, then the argument's first two bytes)."""
    if len(escape.argument) < 2:
        return None
    return escape.kind << 16 | int.from_bytes(escape.argument[:2], "little")


def escape_colour(escape: BmgEscape) -> int | None:
    """The colour an escape sets, or None when it sets none."""
    if escape.kind == COLOUR and len(escape.argument) == 4 and escape.argument[:2] == b"\0\0":
        return int.from_bytes(escape.argument[2:], "little")
    return None


def pages(pieces: Sequence[Piece]) -> list[list[list[Piece]]]:
    """A message's pages: its lines, three at a time."""
    lines = split_lines(pieces)
    return [lines[start : start + PAGE_LINES] for start in range(0, len(lines), PAGE_LINES)]
