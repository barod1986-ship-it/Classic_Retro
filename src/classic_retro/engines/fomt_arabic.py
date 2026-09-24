"""Arabic support for the *Harvest Moon: Friends of Mineral Town* text box.

The game draws every character in a fixed 8x16 cell, which suits its
monospace Latin font but not Arabic, whose letters join and vary in width.
So every translated line is drawn whole, right to left: HarfBuzz shapes it
with the reference font (``font.shaped_text``), the ink gets the game's
shadow (one pixel right and one down-right), and the line is cut into
8-pixel cells from its right end. The cells of all translations form one
bank; cell ``n`` is the two-byte code ``F0 + n // 189``, ``0x40 + n % 189``
(``F0 40``..``FA FC``). The ROM overlay's glyph hook copies a cell where the
game would unpack a glyph, and its text box hook draws a line's ``n``-th
character in column ``27 - n``: lines grow leftwards from the right edge of
the box and the typewriter reveals them from the right.

The player's name keeps the game's Latin glyphs: ``{name}`` is ``FD 21``,
which the overlay's expander hooks replace by the name reversed, each
character as ``FB xx`` (the game's glyph ``xx``, drawn mirrored like a
cell), so the name reads left to right inside the right-to-left line. A
line with the name keeps ``NAME_CELLS`` cells for the longest name.

Speaker names use 16x16 cells, ``FC 40``..``FC FC``: the game's name tag
draws the name four bytes per 32-pixel sprite, two such codes. A translated
tag is right-aligned in its six cells.

At this size the reference font's hamza on a carrier (``أ إ ؤ ئ``) is a
stroke of two or three pixels that reads as part of the letter, so the
renderer draws the carrier's base letter (``ا و ى``) and a drawn hamza where
the font puts its own (found by comparing the two glyphs at a large size).
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fomt import (
    BOX_COLUMNS,
    BOX_LINES,
    CELL_HEIGHT,
    CELL_WIDTH,
    CLEAR_COMMAND,
    INK,
    NEWLINE_COMMAND,
    SHADOW,
    SHADOW_OFFSETS,
    WAIT_COMMAND,
    FomtCommand,
    Piece,
    command_skeleton,
)
from classic_retro.font.shaped_text import ShapedGlyph, ShapedLineRenderer

FONT_SIZE = 10
# Arabic letters sit on row 11 of the 16-row cell (flat letters end on row
# 10): the reference font's forms then span rows 1 to 14, their shadow row 15.
BASELINE = 11
INK_LEVEL = 128
RIGHT_MARGIN = 1
LINE_PIXELS = BOX_COLUMNS * CELL_WIDTH
LAST_COLUMN = BOX_COLUMNS - 1
# The naming screen takes up to twelve characters, a cell each.
NAME_CELLS = 12
# Pixels between Arabic text and the player's name after it (about a space).
NAME_GAP = 3

CELL_LEAD = 0xF0
CELL_LEADS = 11
ISLAND_LEAD = 0xFB
TAG_LEAD = 0xFC
PLACEHOLDER_LEAD = 0xFD
TRAIL_FIRST = 0x40
TRAIL_LAST = 0xFC
TRAILS = TRAIL_LAST - TRAIL_FIRST + 1
MAX_CELLS = CELL_LEADS * TRAILS
MAX_TAG_CELLS = TRAILS
NAME_CODE = bytes([PLACEHOLDER_LEAD, 0x21])

TAG_CELL_WIDTH = 16
# The tag takes twelve bytes: six two-byte codes of 16 pixels (96 pixels).
TAG_CELLS = 6

# Hamza carriers: the base letter drawn in their place, and where the hamza goes.
ABOVE = "above"
BELOW = "below"
HAMZA_CARRIERS = {
    "\u0623": ("\u0627", ABOVE),
    "\u0625": ("\u0627", BELOW),
    "\u0624": ("\u0648", ABOVE),
    "\u0626": ("\u0649", ABOVE),
}
# The drawn hamza (``#`` is ink), one blank row away from its letter.
HAMZA = ("##", "#.")
HAMZA_GAP = 1
PROBE_SIZE = 100

_BIDI_CONTROLS = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
# Characters a translation may use besides Arabic letters.
PUNCTUATION = frozenset(" .!:\u060c\u061b\u061f")
DIGITS = frozenset("0123456789")


def _presentation_form(character: str) -> bool:
    return "\ufb50" <= character <= "\ufdff" or "\ufe70" <= character <= "\ufeff"


def check_text(text: str) -> None:
    """Reject what the cell renderer cannot draw faithfully."""
    for character in text:
        if character in _BIDI_CONTROLS:
            raise ClassicRetroError(
                ErrorCode.EXPLICIT_BIDI_CONTROL, "FoMT Arabic text takes no bidi controls"
            )
        if _presentation_form(character):
            raise ClassicRetroError(
                ErrorCode.PRE_SHAPED_ARABIC_INPUT,
                f"Write logical Arabic, not presentation form U+{ord(character):04X}",
            )
        if unicodedata.category(character) == "Mn":
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_ARABIC_MARK,
                f"FoMT Arabic v1 has no vowel marks (U+{ord(character):04X})",
            )
        if not (
            "\u0621" <= character <= "\u064a" or character in PUNCTUATION or character in DIGITS
        ):
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT,
                f"FoMT Arabic text cannot draw {character!r} (U+{ord(character):04X})",
            )


# ---------------------------------------------------------------------------
# Cells: 4bpp tiles, two tall; 8-pixel cells are two tiles, 16-pixel cells four
# (top left, top right, bottom left, bottom right).

Pixels = tuple[tuple[int, ...], ...]


def cell_data(pixels: Sequence[Sequence[int]]) -> bytes:
    """The tiles of a cell (8 or 16 pixels wide, 16 tall), line by line."""
    width = len(pixels[0])
    data = bytearray()
    for tile_row in range(CELL_HEIGHT // 8):
        for tile_column in range(width // 8):
            for y in range(8):
                row = pixels[tile_row * 8 + y]
                for x in range(tile_column * 8, tile_column * 8 + 8, 2):
                    data.append(row[x] | (row[x + 1] << 4))
    return bytes(data)


def cell_pixels(data: bytes, width: int = CELL_WIDTH) -> Pixels:
    columns = width // 8
    rows: list[list[int]] = [[0] * width for _ in range(CELL_HEIGHT)]
    for tile in range(len(data) // 32):
        tile_row, tile_column = divmod(tile, columns)
        for y in range(8):
            for x in range(0, 8, 2):
                value = data[tile * 32 + y * 4 + x // 2]
                rows[tile_row * 8 + y][tile_column * 8 + x] = value & 0xF
                rows[tile_row * 8 + y][tile_column * 8 + x + 1] = value >> 4
    return tuple(tuple(row) for row in rows)


def with_shadow(ink: Sequence[Sequence[bool]]) -> list[list[int]]:
    """Ink as colour 1 and the game's shadow (right, down-right) as colour 2."""
    height, width = len(ink), len(ink[0])
    pixels = [[INK if ink[y][x] else 0 for x in range(width)] for y in range(height)]
    for y in range(height):
        for x in range(width):
            if not ink[y][x]:
                continue
            for dx, dy in SHADOW_OFFSETS:
                if 0 <= x + dx < width and 0 <= y + dy < height and not ink[y + dy][x + dx]:
                    pixels[y + dy][x + dx] = SHADOW
    return pixels


@dataclass(frozen=True, slots=True)
class FomtRun:
    """Drawn text: its cells from right to left and its width in pixels."""

    cells: tuple[bytes, ...]
    width: int


class FomtCellRenderer:
    """Draw Arabic runs right to left and cut them into cells."""

    def __init__(self, font_path: Path) -> None:
        self.shaper = ShapedLineRenderer(font_path, FONT_SIZE)
        self._probe = ShapedLineRenderer(font_path, PROBE_SIZE)
        self._anchors: dict[tuple[str, str], tuple[float, str]] = {}

    def width(self, text: str) -> float:
        return self.shaper.width(text)

    def _hamza_anchor(self, carrier: ShapedGlyph, base: ShapedGlyph) -> tuple[float, str]:
        """Where the font draws the hamza of ``carrier``: x from the origin (in
        font-size units) and above or below; the base glyph lacks it."""
        key = (carrier.character, base.character)
        if key not in self._anchors:
            size = (4 * PROBE_SIZE, 3 * PROBE_SIZE)
            baseline = 2 * PROBE_SIZE
            layers = []
            for glyph in (carrier, base):
                layer = Image.new("L", size, 0)
                self._probe.draw_glyphs(
                    layer, [ShapedGlyph(glyph.character, 0.0, 0.0, 0.0)], PROBE_SIZE, baseline
                )
                layers.append(layer.point(lambda value: 255 if value >= INK_LEVEL else 0))
            bbox = ImageChops.subtract(layers[0], layers[1]).getbbox()
            if bbox is None:
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED, "The font draws no hamza on a carrier"
                )
            centre = ((bbox[0] + bbox[2]) / 2 - PROBE_SIZE) / PROBE_SIZE
            place = ABOVE if (bbox[1] + bbox[3]) / 2 < baseline - PROBE_SIZE / 4 else BELOW
            self._anchors[key] = (centre, place)
        return self._anchors[key]

    def ink(self, text: str, width: int, right: float) -> list[list[bool]]:
        """1bpp ink of ``text`` with its right end at ``right`` on a ``width``-pixel line."""
        check_text(text)
        glyphs = self.shaper.shape(text)
        base_text = "".join(HAMZA_CARRIERS.get(character, (character,))[0] for character in text)
        bases = self.shaper.shape(base_text) if base_text != text else glyphs
        if len(bases) != len(glyphs):
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, f"Hamza carriers change the shaping of {text!r}"
            )
        left = right - sum(glyph.advance for glyph in glyphs)
        drawn: list[ShapedGlyph] = []
        hamzas: list[tuple[float, str]] = []
        pen = left
        for glyph, base in zip(glyphs, bases, strict=True):
            if glyph.character != base.character:
                centre, place = self._hamza_anchor(glyph, base)
                hamzas.append((pen + glyph.x_offset + centre * FONT_SIZE, place))
                drawn.append(
                    ShapedGlyph(base.character, glyph.advance, glyph.x_offset, glyph.y_offset)
                )
            else:
                drawn.append(glyph)
            pen += glyph.advance
        canvas = Image.new("L", (width, CELL_HEIGHT), 0)
        self.shaper.draw_glyphs(canvas, drawn, left, BASELINE)
        pixels = canvas.load()
        ink = [[pixels[x, y] >= INK_LEVEL for x in range(width)] for y in range(CELL_HEIGHT)]
        for centre, place in hamzas:
            _draw_hamza(ink, centre, place)
        return ink

    def run(
        self,
        text: str,
        cell_width: int = CELL_WIDTH,
        right_margin: int = RIGHT_MARGIN,
        min_cells: int = 0,
        left_gap: int | None = None,
    ) -> FomtRun:
        """``text`` in cells, from its right end: ``right_margin`` pixels stay free
        at the right, so the shadow of the first column keeps its cell.

        With ``left_gap`` the text ends ``left_gap`` pixels from the left edge
        of its cells instead (its final spaces dropped), for text the player's
        name follows: the cells' spare pixels go to the right.
        """
        if left_gap is not None:
            text = text.rstrip(" ")
        advance = self.width(text)
        spare = 2 * cell_width
        cells = max(min_cells, math.ceil((advance + right_margin + (left_gap or 0)) / cell_width))
        width = cells * cell_width + spare
        right = width - right_margin if left_gap is None else spare + left_gap + advance
        ink = self.ink(text, width, right)
        columns = [x for x in range(width) if any(ink[y][x] for y in range(CELL_HEIGHT))]
        if columns:
            if columns[-1] >= width - right_margin:
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED, f"Ink reaches the right margin in {text!r}"
                )
            if columns[0] == 0:
                raise ClassicRetroError(
                    ErrorCode.FONT_BUILD_FAILED, f"Ink reaches too far left in {text!r}"
                )
            cells = max(cells, math.ceil((width - columns[0]) / cell_width))
        pixels = with_shadow(ink)
        cut = tuple(
            cell_data(
                [
                    row[width - cell_width * (number + 1) : width - cell_width * number]
                    for row in pixels
                ]
            )
            for number in range(cells)
        )
        return FomtRun(cut, round(advance))


def _draw_hamza(ink: list[list[bool]], centre: float, place: str) -> None:
    """The drawn hamza over (or under) the letter's ink at column ``centre``."""
    width = len(HAMZA[0])
    left = math.floor(centre - width / 2 + 0.5)
    columns = [x for x in range(left, left + width) if 0 <= x < len(ink[0])]
    rows = [y for y in range(CELL_HEIGHT) if any(ink[y][x] for x in columns)]
    if not rows:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "No letter under a hamza")
    if place == ABOVE:
        top = rows[0] - HAMZA_GAP - len(HAMZA)
    else:
        top = rows[-1] + HAMZA_GAP + 1
    if top < 0 or top + len(HAMZA) > CELL_HEIGHT - 1:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A hamza leaves the cell")
    for y, pattern in enumerate(HAMZA):
        for x, mark in enumerate(pattern):
            if mark == "#" and 0 <= left + x < len(ink[0]):
                ink[top + y][left + x] = True


# ---------------------------------------------------------------------------
# Banks of cells and the encoding of translations


@dataclass(slots=True)
class CellBank:
    """Distinct cells in first-use order, and their codes."""

    cells: list[bytes] = field(default_factory=list)
    _index: dict[bytes, int] = field(default_factory=dict)

    def code(self, cell: bytes) -> bytes:
        if cell not in self._index:
            if len(self.cells) >= MAX_CELLS:
                raise ClassicRetroError(
                    ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                    f"The translations need more than {MAX_CELLS} distinct cells",
                )
            self._index[cell] = len(self.cells)
            self.cells.append(cell)
        return cell_code(self._index[cell])


def cell_code(index: int) -> bytes:
    lead, trail = divmod(index, TRAILS)
    return bytes([CELL_LEAD + lead, TRAIL_FIRST + trail])


def code_cell(code: bytes) -> int:
    """The bank index of a two-byte cell code."""
    if not (CELL_LEAD <= code[0] < CELL_LEAD + CELL_LEADS and TRAIL_FIRST <= code[1] <= TRAIL_LAST):
        raise ClassicRetroError(ErrorCode.UNKNOWN_TEXT_BYTE, f"Not a cell code: {code.hex()}")
    return (code[0] - CELL_LEAD) * TRAILS + code[1] - TRAIL_FIRST


@dataclass(slots=True)
class TagBank:
    """Distinct 16x16 name tag cells and their codes (``FC xx``)."""

    cells: list[bytes] = field(default_factory=list)
    _index: dict[bytes, int] = field(default_factory=dict)

    def code(self, cell: bytes) -> bytes:
        if cell not in self._index:
            if len(self.cells) >= MAX_TAG_CELLS:
                raise ClassicRetroError(
                    ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                    f"The name tags need more than {MAX_TAG_CELLS} distinct cells",
                )
            self._index[cell] = len(self.cells)
            self.cells.append(cell)
        return bytes([TAG_LEAD, TRAIL_FIRST + self._index[cell]])


@dataclass(frozen=True, slots=True)
class FomtLine:
    """A laid-out line: its items (cells right to left, or the name) in order."""

    items: tuple[FomtRun | FomtCommand, ...]
    cells: int


@dataclass(frozen=True, slots=True)
class FomtArabicText:
    """An encoded translation: its bytes and its lines as drawn."""

    data: bytes
    lines: tuple[FomtLine, ...]
    pages: tuple[tuple[int, ...], ...]


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    target = command_skeleton(pieces)
    if target != source:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            "FoMT commands differ from the original: " + "".join(source) + " != " + "".join(target),
        )


class FomtArabicEncoder:
    """Encode translations into cell codes, sharing one bank of cells."""

    def __init__(self, renderer: FomtCellRenderer, bank: CellBank | None = None) -> None:
        self.renderer = renderer
        self.bank = bank if bank is not None else CellBank()

    def lay_out(self, pieces: Sequence[Piece]) -> tuple[list[FomtLine], list[list[int]]]:
        """Lines of a translation, and the lines of each page (between clears).

        The box shows three lines; a line feed on the third scrolls it, and a
        clear empties it. Neither may remove text the player has not seen at a
        ``{wait}``, and a translation ends with one.
        """
        lines: list[FomtLine] = []
        pages: list[list[int]] = [[]]
        items: list[FomtRun | FomtCommand] = []
        cells = 0
        # The lines in the box, oldest first: whether they hold unread text.
        unread = [False]

        def end_line() -> None:
            nonlocal items, cells
            if cells > BOX_COLUMNS:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A line needs {cells} cells (the name counts {NAME_CELLS}); "
                    f"the box holds {BOX_COLUMNS}",
                )
            pages[-1].append(len(lines))
            lines.append(FomtLine(tuple(items), cells))
            items, cells = [], 0

        def check_read(flags: list[bool]) -> None:
            if any(flags):
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    "Text leaves the box before a {wait} shows it (a fourth line or a clear)",
                )

        for number, piece in enumerate(pieces):
            if isinstance(piece, str):
                if not piece:
                    continue
                follows = pieces[number + 1] if number + 1 < len(pieces) else None
                named = isinstance(follows, FomtCommand) and follows.notation == "{name}"
                run = self.renderer.run(piece, left_gap=NAME_GAP if named else None)
                items.append(run)
                cells += len(run.cells)
                unread[-1] = True
            elif piece.is_newline:
                end_line()
                if len(unread) == BOX_LINES:
                    check_read(unread[:1])
                    unread.pop(0)
                unread.append(False)
            elif piece.notation == CLEAR_COMMAND.notation:
                check_read(unread)
                items.append(piece)
                end_line()
                pages.append([])
                unread = [False]
            elif piece.notation == WAIT_COMMAND.notation:
                items.append(piece)
                unread = [False] * len(unread)
            elif piece.notation == "{name}":
                items.append(piece)
                cells += NAME_CELLS
                unread[-1] = True
            else:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"FoMT Arabic v1 does not support {piece.notation!r}",
                )
        end_line()
        check_read(unread)
        return lines, pages

    def encode(self, pieces: Sequence[Piece]) -> FomtArabicText:
        lines, pages = self.lay_out(pieces)
        data = bytearray()
        for number, line in enumerate(lines):
            if number and not (line_ends_page(lines[number - 1])):
                data += NEWLINE_COMMAND.data
            for item in line.items:
                if isinstance(item, FomtRun):
                    for cell in item.cells:
                        data += self.bank.code(cell)
                elif item.notation == "{name}":
                    data += NAME_CODE
                else:
                    data += item.data
        return FomtArabicText(
            bytes(data), tuple(lines), tuple(tuple(page) for page in pages if page)
        )


def line_ends_page(line: FomtLine) -> bool:
    return (
        bool(line.items)
        and isinstance(line.items[-1], FomtCommand)
        and (line.items[-1].notation == CLEAR_COMMAND.notation)
    )


def render_tag(renderer: FomtCellRenderer, name: str, bank: TagBank) -> bytes:
    """A speaker name for the name tag: codes in left-to-right order, right-aligned."""
    run = renderer.run(name, cell_width=TAG_CELL_WIDTH, min_cells=TAG_CELLS)
    if len(run.cells) > TAG_CELLS:
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW,
            f"The name tag holds {TAG_CELLS * TAG_CELL_WIDTH}px; {name!r} needs {run.width + 1}px",
        )
    return b"".join(bank.code(cell) for cell in reversed(run.cells))


# ---------------------------------------------------------------------------
# Previews

# The dialogue box's colours as mGBA shows them (the box is light yellow).
PREVIEW_COLOURS = {0: (248, 240, 168), INK: (0, 0, 0), SHADOW: (208, 192, 88)}
_BOX_BORDER = (200, 176, 72)
_NAME_BACKGROUND = (232, 216, 120)
_NAME_SAMPLE = "Jack"


def _draw_cell(
    image: Image.Image, data: bytes, left: int, top: int, width: int = CELL_WIDTH
) -> None:
    for y, row in enumerate(cell_pixels(data, width)):
        for x, value in enumerate(row):
            if value:
                image.putpixel((left + x, top + y), PREVIEW_COLOURS[value])


def page_preview(lines: Sequence[FomtLine]) -> Image.Image:
    """A box as the hooks lay it out: character ``n`` of a line in column ``27 - n``."""
    margin = 8
    image = Image.new(
        "RGB", (LINE_PIXELS + 2 * margin, BOX_LINES * (CELL_HEIGHT + 1) + 8), _BOX_BORDER
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, image.width - 3, image.height - 3), fill=PREVIEW_COLOURS[0])
    for row, line in enumerate(lines[:BOX_LINES]):
        top = 4 + row * (CELL_HEIGHT + 1)
        column = 0
        for item in line.items:
            if isinstance(item, FomtRun):
                for cell in item.cells:
                    _draw_cell(image, cell, margin + (LAST_COLUMN - column) * CELL_WIDTH, top)
                    column += 1
            elif item.notation == "{name}":
                # The name in the game's glyphs, reversed and mirrored: it
                # reads left to right; a stand-in here.
                right = margin + (LAST_COLUMN - column + 1) * CELL_WIDTH
                width = len(_NAME_SAMPLE) * CELL_WIDTH
                draw.rectangle(
                    (right - width + 1, top + 2, right - 2, top + 12), fill=_NAME_BACKGROUND
                )
                draw.text((right - width + 2, top + 1), _NAME_SAMPLE, fill=(0, 0, 0))
                column += len(_NAME_SAMPLE)
    return image


def text_pages(text: FomtArabicText) -> list[list[FomtLine]]:
    """The lines of every box the text fills (a fourth line scrolls: a new box)."""
    boxes: list[list[FomtLine]] = []
    for page in text.pages:
        lines = [text.lines[number] for number in page]
        for start in range(0, len(lines), BOX_LINES):
            box = lines[start : start + BOX_LINES]
            if any(line.cells for line in box):
                boxes.append(box)
    return boxes


def tag_preview(codes: bytes, bank: TagBank) -> Image.Image:
    image = Image.new("RGB", (TAG_CELLS * TAG_CELL_WIDTH + 8, CELL_HEIGHT + 4), _BOX_BORDER)
    ImageDraw.Draw(image).rectangle(
        (1, 1, image.width - 2, image.height - 2), fill=PREVIEW_COLOURS[0]
    )
    for number in range(0, len(codes), 2):
        cell = bank.cells[codes[number + 1] - TRAIL_FIRST]
        _draw_cell(image, cell, 4 + number // 2 * TAG_CELL_WIDTH, 2, TAG_CELL_WIDTH)
    return image


def previews_sheet(previews: Iterable[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left, at twice the size."""
    label = 150
    items = list(previews)
    width = label + 2 * max(image.width for _, image in items)
    height = sum(2 * image.height + 6 for _, image in items)
    sheet = Image.new("RGB", (width, height), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for key, image in items:
        draw.text((4, y + 4), key, fill=(220, 220, 140))
        sheet.paste(image.resize((image.width * 2, image.height * 2), Image.NEAREST), (label, y))
        y += 2 * image.height + 6
    return sheet
