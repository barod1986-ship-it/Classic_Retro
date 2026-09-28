"""Arabic support for the dialogue of *Final Fantasy II* (USA, Super NES).

The game decodes a message into rows of ``ROW`` (26) codes and sends each row
to the tilemap as it is, a code a tile of the dialogue font, with a blank row
of tiles above it (``engines.ff4``). The overlay (``classic_retro.rom.ff4_arabic``)
gives the Arabic forms tiles of their own (``ARABIC_CODES``: the pair codes,
whose tiles the font leaves blank, and the letters' codes, whose tiles the hook
replaces while an Arabic page shows and puts back for an English one) and hooks
the engine so that an Arabic message's pair codes are glyphs, each row is shown
mirrored (its first code at the right) and the row above holds the top halves
of the glyphs: a form is drawn in a cell of 8x16 pixels (``CELL`` by
``CELL_HEIGHT``), or two cells side by side when it is wider (``MAX_CELLS``);
each cell's bottom half is a tile the message writes, and its top half, when
it is not blank, a tile the message names just before it, with a code from
``TileSet.top_first`` on. Identical halves share a tile, so the free slots go
a long way (``tile_set``). The forms are drawn from the reference font at
the largest size where every form fits (``SIZES``), white on the window's blue
(``INK`` over ``BACKGROUND``), their joining strokes carried to the cell's edges
(``placed_glyph``). The signs the game's font has keep its tiles
(``SIGN_CODES``); the Arabic comma, semicolon and question mark are drawn by
hand (``PUNCTUATION``); the digits are the game's (``engines.ff4.CHARACTERS``).

A row is written in reading order, its first glyph the rightmost; the hook
mirrors the row, then turns each run of the game's own codes (``ISLAND_CODES``:
a name, an item, the gil amount, digits) back so it reads left to right. The
encoder writes a literal run of those codes reversed (``compensate_islands``)
so the hook's turn lays it out left to right.

A translation's notation is a page a line: the box shows four rows
(``engines.ff4.ROWS``), and a message goes on to its next page when the player
presses the button. The encoder lays each page out itself, a word at a time, in
rows of 26 cells; ``{line}`` ends a row where it stands, ``{blank}`` is an
empty row. The commands that tell nothing about the layout pass through as
tokens (``{Name 00}``, ``{Song 2A}``, ``{Wait 10}``, ``{Gil}``), and ``{Close}``
at the very end closes the window at once. A name is written by the hook from
the translation's own names (``encode_name``), reckoned
``NAME_CELLS`` wide; the gil amount is the game's digits, ``GIL_CELLS`` wide.
``{Item}`` is not for an Arabic message: the item's name is in the letters'
codes.

A translation keeps the original's commands: its skeleton (``notation_skeleton``:
every token but ``{line}`` and ``{blank}``, in order) must equal the original's
(``engines.ff4.command_skeleton``), which leaves out the same layout the encoder
writes itself. ``validate_command_skeleton`` refuses a translation that drops,
adds or moves any other command.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import check_logical_arabic, no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff4 import (
    BLANK,
    CHARACTER_CODES,
    CLOSE,
    COMMAND_CODES,
    COMMANDS,
    END,
    GIL_CELLS,
    ISLAND_CODES,
    LINE,
    NAME_CELLS,
    ROW,
    ROWS,
    SPACE,
    command_skeleton,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    Pixel,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    largest_fitting_size,
    pattern_pixels,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.commands import require_same_commands
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Final Fantasy II Arabic"
ENGINE = "Final Fantasy II"
# The tiles an Arabic message may use: the letters' codes, whose tiles the hook
# replaces while an Arabic page shows (``LETTER_CODES``), and the pair codes,
# which never reach the tilemap in English and whose tiles are blank, but
# $F1-$F5 and $F7-$FF, the window's own pieces. A top half's code is a pair code.
LETTER_CODES = tuple(range(0x42, 0x76))
PAIR_CODES = tuple(range(0x8A, 0xC0)) + tuple(range(0xCA, 0xF1)) + (0xF6,)
ARABIC_CODES = LETTER_CODES + PAIR_CODES
SPACE_CODE = SPACE
# A cell: a tile wide, two tiles tall; a wide form takes two cells.
CELL = 8
CELL_HEIGHT = 16
TILE_ROWS = 8
TILE_BYTES = 16
MAX_CELLS = 2
# The row the letters sit on: four rows left below for the tails.
BASELINE = 11
# Pixel values: the window's blue, the letters' white.
BACKGROUND = 1
INK = 3
INK_LEVEL = 110
MARK_LEVEL = 60
SIZES = range(12, 7, -1)
# The joining stroke: rows at a form's edge this close to the baseline carry on.
STROKE_ROWS = range(BASELINE - 4, BASELINE + 2)
DIGITS = "0123456789"
# Signs the game's font draws: their tiles, which the hook mirrors with the Arabic.
SIGN_CODES = {sign: CHARACTER_CODES[sign] for sign in "'.-…!?%/:,"}
# Punctuation drawn by hand: rows of ink, from how many rows above the baseline.
PUNCTUATION: dict[str, tuple[tuple[str, ...], int]] = {
    "،": ((".##", ".##", "##.", "#.."), 2),
    "؛": ((".##", ".##", "...", ".##", ".##", "##.", "#.."), 5),
    "؟": ((".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."), 7),
}
_HAMZA = ("..", "##", "#.")
MARKED_ALEF: dict[str, tuple[str, tuple[str, ...]]] = {"ﺃ": ("ﺍ", _HAMZA), "ﺄ": ("ﺎ", _HAMZA)}
LINE_BREAK = "{line}"
BLANK_ROW = "{blank}"
# Commands a translation may write, with their byte or without. {Item} is not among
# them: the item's name is in the letters' codes, whose tiles are Arabic while an
# Arabic page shows.
PASSING_COMMANDS = frozenset(("Song", "Name", "Wait", "Gil", "Close"))
COMMAND_CELLS = {COMMAND_CODES["Name"]: NAME_CELLS, COMMAND_CODES["Gil"]: GIL_CELLS}
# A character's name for an Arabic message comes from the translation's own names
# (``rom.ff4_arabic_script.NAME_KEYS``); the hook writes it in ``NAME_CELLS`` at most.
_TOKEN = re.compile(r"\{([^{}]*)\}")
_SPACES_OUTSIDE_TOKENS = re.compile(r" (?![^{}]*\})")


def pack_tile(rows: Sequence[Sequence[int]]) -> bytes:
    """A tile of the font: 8 rows of 8 two-bit values, each row its low plane then its
    high plane, the leftmost pixel in bit 7."""
    data = bytearray()
    for row in rows:
        low = high = 0
        for x, value in enumerate(row):
            if value & 1:
                low |= 0x80 >> x
            if value & 2:
                high |= 0x80 >> x
        data += bytes((low, high))
    return bytes(data)


def unpack_tile(data: bytes) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(
            (data[y * 2] >> (7 - x) & 1) | (data[y * 2 + 1] >> (7 - x) & 1) << 1 for x in range(8)
        )
        for y in range(TILE_ROWS)
    )


BLANK_TOP = pack_tile([[BACKGROUND] * CELL for _ in range(TILE_ROWS)])
SPACE_TILE = BLANK_TOP


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic font draws, in the order codes follow."""
    order = (*PUNCTUATION, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


# ---------------------------------------------------------------------------
# Glyphs


@dataclass(frozen=True, slots=True)
class Ff4Glyph:
    """A form's cells and its 16 rows of 8 values a cell: the background or the ink."""

    cells: int
    rows: tuple[tuple[int, ...], ...]

    def tile(self, cell: int, half: int) -> bytes:
        """The tile of cell ``cell`` (0 the left), ``half`` 0 the top, 1 the bottom."""
        return pack_tile(
            [
                row[cell * CELL : (cell + 1) * CELL]
                for row in self.rows[half * TILE_ROWS : (half + 1) * TILE_ROWS]
            ]
        )


@dataclass(frozen=True, slots=True)
class Ff4Font:
    """The glyphs by character, and the size they were drawn at."""

    glyphs: Mapping[str, Ff4Glyph]
    font_size: int

    def cells(self, character: str) -> int:
        try:
            return self.glyphs[character].cells
        except KeyError:
            raise no_glyph(character, PROFILE) from None


def placed_glyph(ink: Collection[Pixel], *, joins_left: bool, joins_right: bool) -> Ff4Glyph:
    """Ink in one cell, or two when wider: a form that joins on either side against
    the cell's right edge, where the letter before it in reading order stands, its
    stroke carried on to the left edge when it joins there; a form that joins
    neither side centred. On a joining side the rows of the stroke at the ink's
    edge carry on to the cell's edge. Raises ``FormDoesNotFit`` when the ink leaves
    the cells."""
    if not ink:
        raise FormDoesNotFit
    width = max(x for x, _ in ink) + 1
    cells = (width + CELL - 1) // CELL
    if cells > MAX_CELLS or any(not 0 <= y < CELL_HEIGHT for _, y in ink):
        raise FormDoesNotFit
    cell_width = cells * CELL
    if joins_right or joins_left:
        shift = cell_width - width
    else:
        shift = (cell_width - width) // 2
    placed = {(x + shift, y) for x, y in ink}
    right = max(x for x, _ in placed)
    left = min(x for x, _ in placed)
    if joins_right:
        placed |= {
            (x, y) for y in _stroke_rows(placed, right) for x in range(right + 1, cell_width)
        }
    if joins_left:
        placed |= {(x, y) for y in _stroke_rows(placed, left) for x in range(left)}
    rows = tuple(
        tuple(INK if (x, y) in placed else BACKGROUND for x in range(cell_width))
        for y in range(CELL_HEIGHT)
    )
    return Ff4Glyph(cells, rows)


def _stroke_rows(placed: Collection[Pixel], column: int) -> set[int]:
    """The rows of the joining stroke at ``column``: those near the baseline with ink
    there, or every row with ink there when none is near."""
    edge = {y for x, y in placed if x == column}
    near = {y for y in edge if y in STROKE_ROWS}
    return near or edge


def _drawn(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    form = draw_form(font, character, BASELINE, ink_level=INK_LEVEL, mark_level=MARK_LEVEL)
    return separated_dots(character, form)


def _form(font: ImageFont.FreeTypeFont, character: str) -> DrawnForm:
    if character in MARKED_ALEF:
        alef, mark = MARKED_ALEF[character]
        return alef_with_mark(character, _drawn(font, alef), mark)
    return _drawn(font, character)


def _placed_forms(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, Ff4Glyph] | None:
    """Every character at this size, placed, or None when one leaves its cells."""
    try:
        return {
            character: placed_glyph(
                _form(font, character).ink,
                joins_left=joins_left_neighbour(character),
                joins_right=joins_right_neighbour(character),
            )
            for character in characters
        }
    except FormDoesNotFit:
        return None


def hand_drawn_glyph(character: str) -> Ff4Glyph:
    rows, above = PUNCTUATION[character]
    ink = pattern_pixels(rows, top=BASELINE - above)
    return placed_glyph(ink, joins_left=False, joins_right=False)


def build_ff4_font(
    font_path: Path, used: Collection[str], *, sizing: Iterable[str] | None = None
) -> Ff4Font:
    """The glyphs of the ``used`` characters.

    The size is the largest where every character of ``sizing`` fits its cells
    (the whole repertoire, whatever the text uses; a test may give a few
    characters) and the ``used`` characters' tiles fit the free codes
    (``tiles_needed``): a translation that grows past them is drawn a size
    smaller, and a message that changes nothing keeps the size.
    """
    drawable = set(arabic_presentation_repertoire())
    wanted = {character for character in used if character not in _GAME_CHARACTERS}
    unknown = sorted(wanted - drawable - set(PUNCTUATION))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    drawn_set = set(drawable if sizing is None else sizing) | (wanted - set(PUNCTUATION))
    drawn = tuple(sorted(drawn_set - set(PUNCTUATION), key=ord))
    punctuation = {character: hand_drawn_glyph(character) for character in PUNCTUATION}

    def fits(font: ImageFont.FreeTypeFont) -> dict[str, Ff4Glyph] | None:
        rendered = _placed_forms(font, drawn)
        if rendered is None:
            return None
        glyphs = {**rendered, **punctuation}
        return (
            rendered if tiles_needed({c: glyphs[c] for c in wanted}) <= len(ARABIC_CODES) else None
        )

    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        fits,
        "Selected font cannot fit Final Fantasy II's cells of 8x16 pixels and its free tiles",
    )
    rendered.update(punctuation)
    return Ff4Font({character: rendered[character] for character in wanted}, size)


def tiles_needed(glyphs: Mapping[str, Ff4Glyph]) -> int:
    """How many tiles the glyphs take: their distinct bottom halves and their distinct
    top halves that are not blank (``tile_set``)."""
    bottoms = {glyph.tile(cell, 1) for glyph in glyphs.values() for cell in range(glyph.cells)}
    tops = {glyph.tile(cell, 0) for glyph in glyphs.values() for cell in range(glyph.cells)}
    return len(bottoms) + len(tops - {BLANK_TOP})


# The characters the game's own tiles draw: the space, the digits and the signs.
_GAME_CHARACTERS = frozenset({" ", *DIGITS, *SIGN_CODES})


@dataclass(frozen=True, slots=True)
class TileSet:
    """What the overlay writes into the font: a tile a code, the bottom halves at
    the lowest free codes and the top halves at the highest, ``top_first`` the
    first code that is a top; and the codes of each character, a cell at a time
    from the right, each cell its top's code (when its top is not blank) then its
    bottom's."""

    tiles: Mapping[int, bytes]
    top_first: int
    codes: GlyphCodes
    font_size: int


def tile_set(font: Ff4Font, characters: Iterable[str]) -> TileSet:
    """The tiles of the ``characters`` the font draws and their codes: each distinct
    bottom half takes the next code from the low end of ``ARABIC_CODES``, each
    distinct top half the next from the high end; the space, the digits and the
    signs keep the game's codes."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order) - _GAME_CHARACTERS)
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    drawn = tuple(character for character in order if character in used)
    bottoms: dict[bytes, int] = {}
    tops: dict[bytes, int] = {}
    low = list(ARABIC_CODES)
    high = list(reversed(PAIR_CODES))
    sequences: dict[str, tuple[int, ...]] = {}
    for character in drawn:
        glyph = font.glyphs[character]
        sequence: list[int] = []
        # The right cell first: the row is written from the right.
        for cell in reversed(range(glyph.cells)):
            top = glyph.tile(cell, 0)
            if top != BLANK_TOP:
                if top not in tops:
                    tops[top] = _take(high, low, drawn)
                sequence.append(tops[top])
            bottom = glyph.tile(cell, 1)
            if bottom not in bottoms:
                bottoms[bottom] = _take(low, high, drawn)
            sequence.append(bottoms[bottom])
        sequences[character] = tuple(sequence)
    game = {" ": (SPACE_CODE,), **{d: (CHARACTER_CODES[d],) for d in DIGITS}}
    game |= {sign: (code,) for sign, code in SIGN_CODES.items()}
    kept = {character: sequence for character, sequence in game.items() if character in used}
    codes = GlyphCodes((*kept, *drawn), {**kept, **sequences})
    tiles = {code: tile for tile, code in bottoms.items()}
    tiles |= {code: tile for tile, code in tops.items()}
    top_first = min(tops.values()) if tops else max(PAIR_CODES) + 1
    return TileSet(tiles, top_first, codes, font.font_size)


def _take(end: list[int], other_end: list[int], drawn: Sequence[str]) -> int:
    """The next free code from ``end``, gone from ``other_end`` too."""
    if not end:
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"{PROFILE} glyphs: {len(drawn)} forms need more than {len(ARABIC_CODES)} tiles",
        )
    code = end.pop(0)
    if code in other_end:
        other_end.remove(code)
    return code


def ff4_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes for a translation checked without the font: each Arabic character one
    code from ``ARABIC_CODES`` in the font's order, as if a cell wide with a blank
    top; the space, the digits and the signs the game's codes. A build takes its
    codes from ``tile_set``."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order) - _GAME_CHARACTERS)
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    drawn = tuple(character for character in order if character in used)
    codes = assign_glyph_codes(drawn, ARABIC_CODES, what=f"{PROFILE} glyphs")
    game = {" ": (SPACE_CODE,), **{d: (CHARACTER_CODES[d],) for d in DIGITS}}
    game |= {sign: (code,) for sign, code in SIGN_CODES.items()}
    kept = {character: sequence for character, sequence in game.items() if character in used}
    return GlyphCodes((*kept, *codes.characters), {**kept, **dict(codes.sequences.items())})


# ---------------------------------------------------------------------------
# Encoding translated messages


def paint_text(text: str) -> str:
    """Logical text in the order it is painted from the right, its letters shaped."""
    check_logical_arabic(text, PROFILE)
    stream = TokenStream((TextToken(text),))
    reject_mirrored(stream, PROFILE)
    reject_combining_marks(stream, PROFILE)
    painted = rtl_paint_order(legacy_renderer_pipeline(), stream)
    return "".join(token.text for token in painted.tokens if isinstance(token, TextToken))


@dataclass(frozen=True, slots=True)
class Command:
    """A command of the text: its bytes, and how many cells the game writes for it."""

    data: bytes
    cells: int


def command(token: str) -> Command:
    """A ``{token}`` of the notation: a passing command with its byte or without."""
    name, _, argument = token.partition(" ")
    if name not in PASSING_COMMANDS:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, f"No token {{{token}}}")
    code = COMMANDS_BY_NAME[name]
    if COMMANDS[code][1] == 2:
        if not re.fullmatch(r"[0-9A-F]{2}", argument):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"{{{token}}}: {name} takes a byte, as {{{name} 01}}",
            )
        return Command(bytes((code, int(argument, 16))), COMMAND_CELLS.get(code, 0))
    if argument:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{{{token}}}: {name} takes no byte"
        )
    return Command(bytes((code,)), COMMAND_CELLS.get(code, 0))


COMMANDS_BY_NAME = COMMAND_CODES


def _pieces(word: str) -> list[str | Command]:
    """A word's text runs and commands, in reading order."""
    out: list[str | Command] = []
    at = 0
    for match in _TOKEN.finditer(word):
        if match.start() > at:
            out.append(word[at : match.start()])
        out.append(command(match.group(1)))
        at = match.end()
    if at < len(word):
        out.append(word[at:])
    return out


def _words(segment: str) -> list[str]:
    """A row's words, split at the spaces outside tokens; an empty row has none."""
    if not segment:
        return []
    words = _SPACES_OUTSIDE_TOKENS.split(segment)
    if not all(words):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, "A line of the message has a space at an end, or two"
        )
    return words


def _split_close(notation: str) -> tuple[str, bool]:
    """The notation without a ``{Close}`` at its end, and whether it had one."""
    if notation.endswith("{Close}"):
        return notation[: -len("{Close}")], True
    return notation, False


def notation_skeleton(notation: str) -> tuple[str, ...]:
    """A translation's commands in order, in the notation, ``{line}`` and ``{blank}``
    left out: what ``engines.ff4.command_skeleton`` gives for the bytes the encoder
    writes."""
    body, closes = _split_close(notation)
    if "{Close}" in body:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, "{Close} ends the message: it goes last"
        )
    skeleton = tuple(
        part
        for match in _TOKEN.finditer(body)
        if f"{{{match.group(1)}}}" not in (LINE_BREAK, BLANK_ROW)
        for part in command_skeleton(command(match.group(1)).data)
    )
    return skeleton + ("{Close}",) if closes else skeleton


def validate_command_skeleton(source_skeleton: Sequence[str], notation: str) -> None:
    """The translation's commands, but the layout, must equal the original's."""
    require_same_commands(ENGINE, tuple(source_skeleton), notation_skeleton(notation), "".join)


def message_characters(notation: str) -> set[str]:
    """The characters a message paints."""
    used = {" "}
    body, _ = _split_close(notation)
    for page in body.split("\n"):
        for segment in page.split(LINE_BREAK):
            for row in segment.split(BLANK_ROW):
                for word in _words(row):
                    for piece in _pieces(word):
                        if isinstance(piece, str):
                            used |= set(paint_text(piece))
    return used


def compensate_islands(codes: bytes) -> bytes:
    """Each run of the game's own codes reversed: the hook turns it back after
    mirroring the row, so it reads left to right."""
    out = bytearray()
    run = bytearray()
    for code in codes:
        if code in ISLAND_CODES:
            run.append(code)
            continue
        out += run[::-1]
        run.clear()
        out.append(code)
    return bytes(out + run[::-1])


@dataclass(frozen=True, slots=True)
class LaidRow:
    """A row: its bytes and how many cells they fill."""

    data: bytes
    cells: int


@dataclass(frozen=True, slots=True)
class EncodedMessage:
    """A translated message's bytes (its end included) and, with the tiles, its pages."""

    data: bytes
    pages: tuple[tuple[LaidRow, ...], ...] | None


class Ff4ArabicEncoder:
    """Convert a logical Arabic message (a page a line) into the hook's bytes.

    With the tiles (``tile_set``), the codes are theirs and the rows are laid out
    by their cells; without, the codes are ``ff4_glyph_codes``' and no layout.
    """

    def __init__(self, glyph_map: GlyphCodes, tiles: TileSet | None = None) -> None:
        self.glyph_map = glyph_map
        self.tiles = tiles

    @property
    def font(self) -> TileSet | None:
        return self.tiles

    def cells(self, codes: bytes) -> int:
        """How many cells the codes fill: a bottom half each, a top half none."""
        if self.tiles is None:
            return len(codes)
        return sum(code < self.tiles.top_first for code in codes)

    def codes(self, painted: str) -> bytes:
        output = bytearray()
        for character in painted:
            sequence = self.glyph_map.sequence(character)
            if sequence is None:
                raise no_glyph(character, PROFILE)
            output += bytes(sequence)
        return bytes(output)

    def word(self, word: str) -> tuple[bytes, int]:
        """A word's bytes, in the order they are painted from the right, and its cells."""
        data = bytearray()
        cells = 0
        for piece in _pieces(word):
            if isinstance(piece, Command):
                data += piece.data
                cells += piece.cells
            else:
                codes = compensate_islands(self.codes(paint_text(piece)))
                data += codes
                cells += self.cells(codes)
        return bytes(data), cells

    def encode(self, notation: str) -> EncodedMessage:
        """The message's bytes: each page's rows, each ended as the game's English ends
        a row, a page short of four rows filled with empty rows, then the end."""
        body, closes = _split_close(notation)
        if "{Close}" in body:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, "{Close} ends the message: it goes last"
            )
        data = bytearray()
        pages: list[tuple[LaidRow, ...]] = []
        page_texts = body.split("\n")
        for index, page in enumerate(page_texts):
            rows = self.page(page)
            if len(rows) > ROWS:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Page {index + 1} needs {len(rows)} rows; the box shows {ROWS}",
                )
            for row in rows:
                data += row.data
                data.append(LINE)
            if index + 1 < len(page_texts):
                data += bytes((BLANK,)) * (ROWS - len(rows))
            pages.append(tuple(rows))
        data.append(CLOSE if closes else END)
        return EncodedMessage(bytes(data), tuple(pages) if self.tiles is not None else None)

    def page(self, page: str) -> list[LaidRow]:
        """A page's rows, a word at a time: a row breaks where the next word would pass
        ``ROW`` cells, at each ``{line}``, and ``{blank}`` is an empty row."""
        rows: list[LaidRow] = []
        for segment in page.split(LINE_BREAK):
            parts = segment.split(BLANK_ROW)
            for number, part in enumerate(parts):
                if number:
                    rows.append(LaidRow(b"", 0))
                if not part and number:
                    continue
                rows += self._rows(part)
        return rows

    def _rows(self, segment: str) -> list[LaidRow]:
        rows: list[LaidRow] = []
        row = bytearray()
        pen = 0
        for word in _words(segment):
            codes, cells = self.word(word)
            gap = 1 if row else 0
            if row and pen + gap + cells > ROW:
                rows.append(LaidRow(bytes(row), pen))
                row, pen, gap = bytearray(), 0, 0
            if gap:
                row.append(SPACE_CODE)
            row += codes
            pen += gap + cells
            if pen > ROW:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A word needs {cells} cells; a row holds {ROW}",
                )
        rows.append(LaidRow(bytes(row), pen))
        return rows


def encode_name(encoder: Ff4ArabicEncoder, key: str, text: str) -> bytes:
    """A character's name in the message's codes, in reading order, at most
    ``NAME_CELLS`` cells: what the hook writes in place of the name the player gave."""
    if not text or " " in text or "{" in text:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"{key}: a name is one word without commands"
        )
    codes, cells = encoder.word(text)
    if cells > NAME_CELLS:
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW, f"{key}: a name fills {NAME_CELLS} cells at most"
        )
    return codes


# ---------------------------------------------------------------------------
# What the game shows: the buffer the engine fills and the rows the hook sends


_BLOCKS = {COMMAND_CODES["Name"]: NAME_CELLS, COMMAND_CODES["Gil"]: GIL_CELLS}


def decoded_rows(data: bytes, top_first: int) -> list[list[tuple[int, int]]]:
    """The rows the engine's decoder fills from the message: ``ROW`` cells a row,
    each its code and its top's code (the space's where the row above is blank);
    a name, an item or the gil amount as that many cells of its command's
    negative code (the game writes the text there); a row padded with spaces."""
    cells: list[tuple[int, int]] = []
    pending = SPACE_CODE
    at = 0
    while at < len(data):
        code = data[at]
        if code == END or code == CLOSE:
            break
        if code in COMMANDS:
            _, length = COMMANDS[code]
            if code == LINE:
                while len(cells) % ROW:
                    cells.append((SPACE_CODE, SPACE_CODE))
            elif code == BLANK:
                cells.append((SPACE_CODE, SPACE_CODE))
                while len(cells) % ROW:
                    cells.append((SPACE_CODE, SPACE_CODE))
            elif code == COMMAND_CODES["Spaces"]:
                cells += [(SPACE_CODE, SPACE_CODE)] * data[at + 1]
            elif code in _BLOCKS:
                cells += [(-code, SPACE_CODE)] * _BLOCKS[code]
            at += length
            continue
        if code >= top_first and code in ARABIC_CODES:
            pending = code
        else:
            cells.append((code, pending))
            pending = SPACE_CODE
        at += 1
    while len(cells) % ROW:
        cells.append((SPACE_CODE, SPACE_CODE))
    return [cells[start : start + ROW] for start in range(0, len(cells), ROW)]


def shown_row(row: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """A row as the hook sends it: mirrored, each run of the game's own codes (and of
    the cells a command's text takes) turned back to read left to right."""
    shown = list(reversed(row))
    start = 0
    while start < len(shown):
        if not _island(shown[start][0]):
            start += 1
            continue
        end = start
        while end < len(shown) and _island(shown[end][0]):
            end += 1
        shown[start:end] = reversed(shown[start:end])
        start = end
    return shown


def _island(code: int) -> bool:
    return code < 0 or code in ISLAND_CODES


# ---------------------------------------------------------------------------
# Previews

PREVIEW_COLOURS = {INK: (248, 248, 248), BACKGROUND: (40, 56, 120)}
PREVIEW_BACKGROUND = (40, 56, 120)
PREVIEW_BLOCK = (150, 150, 150)
PREVIEW_MARGIN = 8


def font_preview(tiles: TileSet) -> Image.Image:
    """Atlas of the tiles by code, in the order of their codes, the tops among them."""
    codes = sorted(tiles.tiles)
    pixels = [unpack_tile(tiles.tiles[code]) for code in codes]

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        return PREVIEW_COLOURS.get(pixels[number][y][x], PREVIEW_BACKGROUND)

    return glyph_atlas(len(codes), CELL, TILE_ROWS, colour)


def _draw_tile(image: Image.Image, tile: bytes, x: int, y: int) -> None:
    for row, values in enumerate(unpack_tile(tile)):
        for column, value in enumerate(values):
            image.putpixel((x + column, y + row), PREVIEW_COLOURS.get(value, PREVIEW_BACKGROUND))


def message_preview(encoded: EncodedMessage, tiles: TileSet) -> Image.Image:
    """Each page as the box shows it: four rows of 26 cells, 16 rows of pixels each,
    the rows mirrored as the hook sends them; the game's own tiles (a name, an item,
    the gil, digits, signs) as grey blocks."""
    if encoded.pages is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the font")
    rows = decoded_rows(encoded.data, tiles.top_first)
    pages = [rows[start : start + ROWS] for start in range(0, max(len(rows), 1), ROWS)]
    height = ROWS * CELL_HEIGHT + 2 * PREVIEW_MARGIN
    width = ROW * CELL + 2 * PREVIEW_MARGIN
    image = Image.new("RGB", (width, height * len(pages)), (12, 12, 12))
    for number, page in enumerate(pages):
        top = number * height
        for x in range(2, width - 2):
            for y in range(top + 2, top + height - 2):
                image.putpixel((x, y), PREVIEW_BACKGROUND)
        for row_number, row in enumerate(page):
            y = top + PREVIEW_MARGIN + row_number * CELL_HEIGHT
            for cell, (code, above_code) in enumerate(shown_row(row)):
                x = PREVIEW_MARGIN + cell * CELL
                tile = tiles.tiles.get(code)
                if code != SPACE_CODE and tile is None:
                    for dx in range(1, CELL - 1):
                        for dy in range(TILE_ROWS + 1, CELL_HEIGHT - 1):
                            image.putpixel((x + dx, y + dy), PREVIEW_BLOCK)
                    continue
                if tile is not None:
                    _draw_tile(image, tile, x, y + TILE_ROWS)
                above = tiles.tiles.get(above_code)
                if above is not None:
                    _draw_tile(image, above, x, y)
    return image


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 110)
