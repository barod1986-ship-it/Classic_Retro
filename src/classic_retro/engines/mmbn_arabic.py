"""Arabic support for the *Mega Man Battle Network* script engine.

The game draws every character in its own 8x16 cell, which suits its
monospace Latin font but not Arabic, whose letters join and vary in width.
So every translated line is drawn whole, right to left: HarfBuzz shapes the
Arabic runs with the reference font (``font.shaped_text``) and Latin words
(PET, WWW) keep the game's own glyphs as left-to-right islands. The line is
then cut into 8-pixel cells from its right end; the cells of a page (the text
between two box clears, at most 60 cells) form a glyph bank of their own, and
the page's characters are cell numbers of that bank.

The ROM overlay (``classic_retro.rom.mmbn_arabic``) finds the bank of the
page being drawn from the address of its text: ``Text_CopyCharTile`` then
copies cell ``code`` of the bank instead of glyph ``code`` of the font, and
``Text_LoadCharTileLayout`` puts the ``n``-th cell of a line in column
``27 - n`` instead of ``8 + n``, so every line grows leftwards from the right
edge of the box.

Commands keep their order and their byte form. Mouth animations (``<``,
``>``) move to the cell boundary where their text ends; after a wait inside
a line the next text starts in a new cell, so it only appears after the wait.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mmbn import (
    BACKGROUND,
    BOX_COLUMNS,
    BOX_LINES,
    CELL_HEIGHT,
    CELL_WIDTH,
    CLEAR,
    FIRST_COLUMN,
    INK,
    MOUTH,
    NEWLINE,
    PAGE_CELLS,
    SHADE,
    SYMBOL_LEAD,
    MmbnCommand,
    Piece,
    cell_data,
    cell_pixels,
    font_cell,
    glyph_code,
    notation_skeleton,
)
from classic_retro.font.shaped_text import ShapedLineRenderer

FONT_SIZE = 11
# Arabic letters sit on row 11 of the 16-row cell: at 11 px the reference
# font's forms span rows 0 (hamza above alef) to 15 (the tail of final yeh).
BASELINE = 11
# The game's capitals end on row 13; three rows up they sit on the Arabic
# baseline (words with digits, which start on row 2, move up two rows).
LATIN_ROW_SHIFT = -3
INK_LEVEL = 150
SHADE_LEVEL = 60
RIGHT_MARGIN = 1
LINE_PIXELS = BOX_COLUMNS * CELL_WIDTH
# Cell numbers stop below 0xE5, the first two-byte character lead.
PAGE_CODES = SYMBOL_LEAD
LAST_COLUMN = FIRST_COLUMN + BOX_COLUMNS - 1

# Latin words keep the game's glyphs, a cell each: letters, digits, and a dot
# or a space between them (MegaMan.EXE, Recov10 A).
LATIN_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.")
_LATIN_RUN = re.compile(r"[A-Za-z0-9]+(?:[ .][A-Za-z0-9]+)*")
# Commands a translated page may use: none of them prints or moves the text
# (flags, flag checks, items given, waits, mugshots, the player's animation...).
ALLOWED_COMMANDS = frozenset(
    {0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7}
    | {0xF9, 0xFA, 0xFC}
)
_BIDI_CONTROLS = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _presentation_form(character: str) -> bool:
    return "\ufb50" <= character <= "\ufdff" or "\ufe70" <= character <= "\ufeff"


def placeholder_latin_cells() -> dict[str, tuple[tuple[int, ...], ...]]:
    """Stand-ins for the game's Latin glyphs when no ROM is at hand (checks, previews)."""
    box = tuple(
        tuple(
            INK if 3 <= y <= 13 and 1 <= x <= 6 and (x in (1, 6) or y in (3, 13)) else BACKGROUND
            for x in range(CELL_WIDTH)
        )
        for y in range(CELL_HEIGHT)
    )
    return dict.fromkeys(LATIN_CHARACTERS, box)


def game_latin_cells(rom: bytes, font_address: int) -> dict[str, tuple[tuple[int, ...], ...]]:
    """The game's glyphs for Latin letters and digits."""
    return {
        character: font_cell(rom, font_address, glyph_code(character))
        for character in LATIN_CHARACTERS
    }


@dataclass(frozen=True, slots=True)
class MmbnLine:
    """A drawn line: its cells right to left, and where each of its commands goes."""

    cells: tuple[bytes, ...]
    boundaries: tuple[int, ...]
    width: int
    image: Image.Image = field(compare=False, repr=False)


class MmbnLineRenderer:
    """Draw logical Arabic lines (with Latin islands) and cut them into cells."""

    def __init__(
        self,
        font_path: Path,
        latin: dict[str, tuple[tuple[int, ...], ...]] | None = None,
    ) -> None:
        self.shaper = ShapedLineRenderer(font_path, FONT_SIZE)
        self.latin = latin if latin is not None else placeholder_latin_cells()
        missing = LATIN_CHARACTERS - set(self.latin)
        if missing:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, "No Latin cell for " + "".join(sorted(missing))
            )

    def text_width(self, text: str) -> float:
        return sum(self._run_width(run, latin) for run, latin in split_runs(text))

    def _run_width(self, run: str, latin: bool) -> float:
        return CELL_WIDTH * len(run) if latin else self.shaper.width(run)

    def _draw_text(self, text: str, right: float, width: int) -> tuple[Image.Image, float]:
        """``text`` on a layer ``width`` wide with its right edge at ``right``; its advance."""
        layer = Image.new("L", (width, CELL_HEIGHT), 0)
        pen = right
        for run, latin in split_runs(text):
            run_width = self._run_width(run, latin)
            left = pen - run_width
            if latin:
                self._draw_latin(layer, run, round(left))
            else:
                self.shaper.draw(layer, run, left, BASELINE)
            pen = left
        return layer, right - pen

    def _draw_latin(self, layer: Image.Image, run: str, left: int) -> None:
        pixels = layer.load()
        cells = [self.latin[character] for character in run if character != " "]
        # The game's digits start a row above its capitals: a word with digits
        # moves up less, so its top row stays in the cell.
        top = min(
            (y for cell in cells for y, row in enumerate(cell) if SHADE in row or INK in row),
            default=0,
        )
        shift = max(LATIN_ROW_SHIFT, -top)
        for number, character in enumerate(run):
            if character == " ":
                continue
            cell = self.latin[character]
            for y, row in enumerate(cell):
                target_y = y + shift
                for x, value in enumerate(row):
                    target_x = left + number * CELL_WIDTH + x
                    if value in (SHADE, INK) and 0 <= target_x < layer.width:
                        if not 0 <= target_y < CELL_HEIGHT:
                            raise ClassicRetroError(
                                ErrorCode.FONT_BUILD_FAILED,
                                f"Latin glyph {character!r} leaves the cell",
                            )
                        coverage = 255 if value == INK else 110
                        pixels[target_x, target_y] = max(pixels[target_x, target_y], coverage)

    def render(self, items: Iterable[Piece]) -> MmbnLine:
        """One line: its text runs and the commands between them, in logical order."""
        # The line ends at ``width`` on a canvas twice the box width (so an
        # overflow can be measured) plus a cell to catch ink past the margin.
        width = 2 * LINE_PIXELS
        canvas = Image.new("L", (width + CELL_WIDTH, CELL_HEIGHT), 0)
        pen: float = width - RIGHT_MARGIN
        ink_left = width
        boundaries: list[int] = []
        wait = False
        for item in items:
            if isinstance(item, MmbnCommand):
                boundaries.append(_cells_from(width, ink_left))
                wait = wait or item.code != MOUTH
                continue
            layer, advance = self._draw_text(item, pen, canvas.width)
            if wait:
                # The text after a wait starts in a cell of its own.
                limit = width - CELL_WIDTH * _cells_from(width, ink_left)
                right_ink = _ink_right(layer)
                if right_ink is not None and right_ink >= limit:
                    pen -= right_ink - limit + 1
                    layer, advance = self._draw_text(item, pen, canvas.width)
                wait = False
            canvas = ImageChops.lighter(canvas, layer)
            left_ink = _ink_left(layer)
            if left_ink is not None:
                ink_left = min(ink_left, left_ink)
            pen -= advance
        right_ink = _ink_right(canvas)
        if right_ink is not None and right_ink >= width:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, "A glyph reaches past the right edge of the box"
            )
        cells = _cells_from(width, ink_left)
        if cells > BOX_COLUMNS:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"A line needs {width - ink_left}px ({cells} cells); the box holds "
                f"{BOX_COLUMNS} cells ({LINE_PIXELS}px)",
            )
        indices = canvas.crop((width - LINE_PIXELS, 0, width, CELL_HEIGHT)).point(_quantize)
        cut = tuple(
            _cell(indices, LINE_PIXELS - CELL_WIDTH * (number + 1)) for number in range(cells)
        )
        return MmbnLine(cut, tuple(boundaries), width - ink_left, indices)


def _quantize(value: int) -> int:
    return INK if value >= INK_LEVEL else SHADE if value >= SHADE_LEVEL else BACKGROUND


def _ink_left(layer: Image.Image) -> int | None:
    bbox = layer.point(lambda value: 255 if value >= SHADE_LEVEL else 0).getbbox()
    return None if bbox is None else bbox[0]


def _ink_right(layer: Image.Image) -> int | None:
    bbox = layer.point(lambda value: 255 if value >= SHADE_LEVEL else 0).getbbox()
    return None if bbox is None else bbox[2] - 1


def _cells_from(right: int, ink_left: int) -> int:
    """Cells, counted from ``right``, that hold every ink column from ``ink_left`` on."""
    return 0 if ink_left >= right else (right - 1 - ink_left) // CELL_WIDTH + 1


def _cell(indices: Image.Image, left: int) -> bytes:
    pixels = indices.load()
    return cell_data([[pixels[left + x, y] for x in range(CELL_WIDTH)] for y in range(CELL_HEIGHT)])


def split_runs(text: str) -> tuple[tuple[str, bool], ...]:
    """Arabic runs and Latin words (``True``) in logical order."""
    runs: list[tuple[str, bool]] = []
    position = 0
    for match in _LATIN_RUN.finditer(text):
        if match.start() > position:
            runs.append((text[position : match.start()], False))
        runs.append((match.group(), True))
        position = match.end()
    if position < len(text):
        runs.append((text[position:], False))
    return tuple(runs)


def check_text(text: str) -> None:
    """Reject what the line renderer cannot draw faithfully."""
    for character in text:
        if character in _BIDI_CONTROLS:
            raise ClassicRetroError(
                ErrorCode.EXPLICIT_BIDI_CONTROL, "MMBN Arabic text takes no bidi controls"
            )
        if _presentation_form(character):
            raise ClassicRetroError(
                ErrorCode.PRE_SHAPED_ARABIC_INPUT,
                f"Write logical Arabic, not presentation form U+{ord(character):04X}",
            )
        if unicodedata.category(character) == "Mn":
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_ARABIC_MARK,
                f"MMBN Arabic v1 has no vowel marks (U+{ord(character):04X})",
            )
        if "\u0660" <= character <= "\u0669" or "\u06f0" <= character <= "\u06f9":
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT, "Write numbers with the game's digits (0-9)"
            )
        if character in "{}<>\\":
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"Stray {character!r} in text")


@dataclass(frozen=True, slots=True)
class MmbnArabicPage:
    """A page of a translated section: where it starts and its bank of cells."""

    start: int
    cells: tuple[bytes, ...]
    line_cells: tuple[int, ...]
    line_widths: tuple[int, ...]
    lines: tuple[MmbnLine, ...] = field(compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class MmbnArabicScript:
    """A translated section: its bytes and its pages."""

    data: bytes
    pages: tuple[MmbnArabicPage, ...]


def validate_command_skeleton(source: tuple[str, ...], pieces: tuple[Piece, ...]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    target = notation_skeleton(pieces)
    if target != source:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            "MMBN commands differ from the original: " + "".join(source) + " != " + "".join(target),
        )


def check_pieces(pieces: tuple[Piece, ...]) -> None:
    for piece in pieces:
        if isinstance(piece, str):
            if "{char " in piece:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT, "Arabic pages take no {char ...} codes"
                )
            check_text(piece)
        elif piece.code not in ALLOWED_COMMANDS or piece.data[:2] == b"\xea\xff":
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"MMBN Arabic v1 does not support {piece.notation!r} (write item names as text)",
            )


def split_pages(pieces: tuple[Piece, ...]) -> list[list[Piece]]:
    """Pieces of every page: a box clear (``E9``) ends a page, and the next starts after it."""
    pages: list[list[Piece]] = [[]]
    for piece in pieces:
        pages[-1].append(piece)
        if isinstance(piece, MmbnCommand) and piece.code == CLEAR:
            pages.append([])
    if not pages[-1] and len(pages) > 1:
        pages.pop()
    return pages


def split_lines(pieces: Iterable[Piece]) -> list[list[Piece]]:
    lines: list[list[Piece]] = [[]]
    for piece in pieces:
        if isinstance(piece, MmbnCommand) and piece.is_newline:
            lines.append([])
        else:
            lines[-1].append(piece)
    return lines


class MmbnArabicEncoder:
    """Encode a translated section: pre-drawn cells per page, commands kept in order."""

    def __init__(self, renderer: MmbnLineRenderer) -> None:
        self.renderer = renderer

    def encode(self, pieces: tuple[Piece, ...]) -> MmbnArabicScript:
        check_pieces(pieces)
        data = bytearray()
        pages = []
        for page_pieces in split_pages(pieces):
            start = len(data)
            lines = split_lines(page_pieces)
            drawn = [self.renderer.render(line) for line in lines]
            for number, line in enumerate(drawn):
                if line.cells and number >= BOX_LINES:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW, f"A MMBN box holds {BOX_LINES} lines"
                    )
            total = sum(len(line.cells) for line in drawn)
            if total > PAGE_CELLS:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A page needs {total} cells; the tile buffer holds {PAGE_CELLS}",
                )
            codes: dict[bytes, int] = {}
            for line in drawn:
                for cell in line.cells:
                    codes.setdefault(cell, len(codes))
            if len(codes) > PAGE_CODES:
                raise ClassicRetroError(
                    ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                    f"A page has {len(codes)} distinct cells; codes stop at {PAGE_CODES:#x}",
                )
            for number, (line, line_pieces) in enumerate(zip(drawn, lines, strict=True)):
                if number:
                    data.append(NEWLINE)
                commands = [piece for piece in line_pieces if isinstance(piece, MmbnCommand)]
                emitted = 0
                for command, boundary in zip(commands, line.boundaries, strict=True):
                    data += bytes(codes[cell] for cell in line.cells[emitted:boundary])
                    emitted = max(emitted, boundary)
                    data += command.data
                data += bytes(codes[cell] for cell in line.cells[emitted:])
            pages.append(
                MmbnArabicPage(
                    start=start,
                    cells=tuple(codes),
                    line_cells=tuple(len(line.cells) for line in drawn),
                    line_widths=tuple(line.width for line in drawn),
                    lines=tuple(drawn),
                )
            )
        return MmbnArabicScript(data=bytes(data), pages=tuple(pages))


# Colours of the dialogue box: palette 15 of the text layer, as mGBA shows it.
PREVIEW_COLOURS = {
    0: (0, 0, 0),
    BACKGROUND: (246, 246, 246),
    SHADE: (205, 205, 205),
    INK: (49, 57, 57),
}
_BOX_BORDER = (40, 56, 120)


def page_preview(page: MmbnArabicPage) -> Image.Image:
    """A page as the hooks lay it out: cell ``n`` of a line in column ``27 - n``."""
    columns = LAST_COLUMN + 2
    image = Image.new("RGB", (columns * CELL_WIDTH, BOX_LINES * CELL_HEIGHT + 8), _BOX_BORDER)
    ImageDraw.Draw(image).rectangle(
        (FIRST_COLUMN * CELL_WIDTH - 2, 2, (LAST_COLUMN + 1) * CELL_WIDTH + 1, image.height - 3),
        fill=PREVIEW_COLOURS[BACKGROUND],
    )
    for row, line in enumerate(page.lines[:BOX_LINES]):
        for number, cell in enumerate(line.cells):
            left = (LAST_COLUMN - number) * CELL_WIDTH
            for y, values in enumerate(cell_pixels(cell)):
                for x, value in enumerate(values):
                    image.putpixel((left + x, 4 + row * CELL_HEIGHT + y), PREVIEW_COLOURS[value])
    return image


def pages_sheet(pages: list[tuple[str, MmbnArabicPage]]) -> Image.Image:
    """Page previews one under another, each with its key on the left, at twice the size."""
    label = 110
    previews = [(key, page_preview(page)) for key, page in pages]
    width = label + 2 * max(image.width for _, image in previews)
    height = sum(2 * image.height + 6 for _, image in previews)
    sheet = Image.new("RGB", (width, height), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for key, image in previews:
        draw.text((4, y + 4), key, fill=(220, 220, 140))
        sheet.paste(image.resize((image.width * 2, image.height * 2), Image.NEAREST), (label, y))
        y += 2 * image.height + 6
    return sheet


def cells_needed(renderer: MmbnLineRenderer, text: str) -> int:
    """Cells of a line of plain text (no commands), for writing translations."""
    return math.ceil((renderer.text_width(text) + RIGHT_MARGIN) / CELL_WIDTH)
