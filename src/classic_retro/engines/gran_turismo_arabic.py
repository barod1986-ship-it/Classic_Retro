"""Arabic support for the license briefings of *Gran Turismo* (PlayStation).

The game draws a briefing with two of the four fonts of its font page
(GAMEFONT.DAT): the title in font 2, centred, and the paragraphs in font 1,
placed from the left word by word and justified but for each paragraph's last
line. A glyph is one sprite of the page, drawn at the pen, which then moves on
by the glyph's advance less a kerning amount.

The overlay (``classic_retro.rom.gran_turismo_arabic``) gives the Arabic
letters codes of fonts 1 and 2 that the US English never uses
(``ARABIC_CODES``: the Latin-1 letters and signs), draws their glyphs from the
reference font into the page (``place_glyphs``), and mirrors the layout: the
game still measures and places every word from the left, and the hook draws
each one at the mirror of its place (``MIRROR - x - width``), so a paragraph
reads from the right and its last line ends on the right. A word keeps its
glyphs in visual order, as the game draws them, left to right; the words keep
the reading order. The title is one word, its spaces included, which the game
centres.

Fonts 0 to 2 share the low two bits of the page's pixels, which their palettes
read as white (``INK``), black (``OUTLINE``) and clear (``CLEAR``); font 3 has
the high two. Every glyph is white with a black outline a pixel wide all round
but on a side where it joins its neighbour, where its stroke runs on to the
edge. Each font's glyphs come from a cell (``CELLS``) at the largest size
where every form of the repertoire and every digit fits with its outline: 16
rows for the body, baseline on row 11; 26 for the title, baseline on row 19,
for the marks and tails of its larger letters. Each glyph is stored cropped to
its rows, its row offset in the glyph table keeping it in place. Two- and
three-dot letters whose dots merge at the body's size get them redrawn
(``separated_dots``); the dots under yeh, which reach below the title's cell,
move up (``raised_marks``). The digits come from the reference font, the
punctuation it lacks or draws too small (``PUNCTUATION``) by hand; the title's
space is a blank glyph. Every glyph in an Arabic word is one of these, whose
kerning is none, so a word's width is the sum of its glyphs' widths.

The title's cell starts on the box's top row, so the hook draws the Arabic
body ``DROP`` rows lower and its lines ``LINE_STEP`` rows apart (the game's are
12): the box shows ``MAX_LINES`` under the title. The game's own text keeps
its place, its lines and its spacing: the hook tells an Arabic word by its
first glyph. A word may be ``WIDEST_WORD`` pixels wide: a line holds 288 and a
paragraph's first line, indented, 280; a word wider than a line would never
find one.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import check_logical_arabic, is_arabic_letter, no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.gran_turismo import Briefing
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.font.glyph_raster import (
    FormDoesNotFit,
    Pixel,
    arabic_font_file,
    draw_form,
    drop_shadow,
    largest_fitting_size,
    pattern_pixels,
    raised_marks,
    separated_dots,
)
from classic_retro.font.previews import glyph_atlas, preview_sheet
from classic_retro.text.tokens import TextToken, TokenStream

PROFILE = "Gran Turismo Arabic"
# The Latin-1 half but the no-break space (a blank of the game's): 121 codes.
ARABIC_CODES = tuple(code for code in range(0x86, 0x100) if code != 0xA0)
BODY = 1
TITLE = 2
INK = 0
OUTLINE = 2
CLEAR = 3
INK_LEVEL = 128
MARK_LEVEL = 60
DIGITS = "0123456789"
TITLE_SPACE = 6
_AROUND = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)


@dataclass(frozen=True, slots=True)
class GlyphCell:
    """A font's glyph cell: its rows, the baseline row, where the game draws its top row
    (the line's y + ``dy`` - 4), the sizes tried and the widest glyph."""

    rows: int
    baseline: int
    dy: int
    sizes: range
    widest: int


CELLS = {
    BODY: GlyphCell(rows=16, baseline=11, dy=0, sizes=range(13, 6, -1), widest=24),
    TITLE: GlyphCell(rows=26, baseline=19, dy=2, sizes=range(18, 9, -1), widest=32),
}
# Punctuation drawn by hand: the Latin the reference font lacks and, in the
# body, the Arabic comma and semicolon it draws too small to tell from a full
# stop. Each font's rows of ink and the row they start on.
PUNCTUATION: dict[int, dict[str, tuple[tuple[str, ...], int]]] = {
    BODY: {
        ".": (("##", "##"), 9),
        ",": (("##", "##", ".#"), 9),
        ":": (("##", "##", "..", "..", "##", "##"), 5),
        "!": (("##",) * 6 + ("..", "##", "##"), 2),
        "-": (("###",), 7),
        "،": ((".#", "##", "##"), 8),
        "؛": ((".#", "##", "##", "..", "..", "##", "##"), 4),
    },
    TITLE: {
        ".": (("###",) * 3, 16),
        ",": (("###",) * 3 + (".##", ".#."), 16),
        ":": (("###",) * 3 + ("...",) * 3 + ("###",) * 3, 10),
        "!": (("###",) * 8 + ("...",) * 2 + ("###",) * 3, 6),
        "-": (("####",) * 2, 13),
    },
}
# The game's layout: the box's left edge and width, a paragraph's indent, the
# space between words, where the text starts, the title's drop and the rows it
# takes. The hook mirrors an Arabic word in the 320-pixel line and draws it
# DROP rows lower, under the Arabic title's taller cell, and puts an Arabic
# line LINE_STEP rows after the last (the game's are 12).
BOX_LEFT = 16
BOX_WIDTH = 288
INDENT = 8
SPACE = 4
TOP = 64
TITLE_DROP = 2
TITLE_STEP = 24
MIRROR = 320
DROP = 6
LINE_STEP = 15
# The box clips below row 195: seven body lines, the last one's cell ending there.
BOX_BOTTOM = 195
MAX_LINES = 7
WIDEST_WORD = BOX_WIDTH - INDENT


def glyph_characters() -> tuple[str, ...]:
    """Every character the Arabic fonts can draw, in the order codes follow."""
    order = (" ", *PUNCTUATION[BODY], *DIGITS, *arabic_presentation_repertoire())
    return tuple(dict.fromkeys(order))


def gran_turismo_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes from ``ARABIC_CODES`` for the characters a translation uses, in the fonts' order."""
    used = set(characters)
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], PROFILE)
    return assign_glyph_codes(
        (character for character in order if character in used),
        ARABIC_CODES,
        what="Gran Turismo Arabic glyphs",
    )


@dataclass(frozen=True, slots=True)
class GtGlyph:
    """A glyph cropped to its rows: its width (the pen's advance), its first row in the
    cell and its rows of pixel values; a blank glyph has no rows."""

    width: int
    top: int
    rows: tuple[tuple[int, ...], ...]

    @property
    def height(self) -> int:
        return len(self.rows)

    def entry(self, u: int, v: int, dy: int) -> bytes:
        """The glyph table's eight bytes: page position, size, row offset, advance."""
        return bytes((u, v, self.width, self.height, 0, dy + self.top, self.width - 1, self.height))


@dataclass(frozen=True, slots=True)
class GtFont:
    """One of the game's fonts' Arabic glyphs by code, and the size they were drawn at."""

    index: int
    glyphs: Mapping[int, GtGlyph]
    font_size: int

    def measure(self, word: bytes) -> int:
        """A word's width as the game measures it: its glyphs' advances, no kerning."""
        try:
            return sum(self.glyphs[code].width for code in word)
        except KeyError as missing:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"Font {self.index} has no glyph {missing.args[0]:#04x}"
            ) from None


def outlined_glyph(
    ink: Collection[Pixel], cell: GlyphCell, *, joins_left: bool, joins_right: bool
) -> GtGlyph:
    """Ink from column 0, outlined but on its joining sides and cropped to its rows."""
    left = 0 if joins_left else 1
    placed = {(x + left, y) for x, y in ink}
    width = max(x for x, _ in placed) + 1 + (0 if joins_right else 1)
    if any(not 1 <= y <= cell.rows - 2 for _, y in placed) or width > cell.widest:
        raise FormDoesNotFit
    ring = {(x, y) for x, y in drop_shadow(placed, _AROUND, width, cell.rows) if x >= 0}
    rows = [y for _, y in placed | ring]
    top, bottom = min(rows), max(rows)
    return GtGlyph(
        width,
        top,
        tuple(
            tuple(
                INK if (x, y) in placed else OUTLINE if (x, y) in ring else CLEAR
                for x in range(width)
            )
            for y in range(top, bottom + 1)
        ),
    )


def _drawn_glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str], cell: GlyphCell
) -> dict[str, GtGlyph] | None:
    """Every character at this size, or None when one leaves the cell."""
    try:
        glyphs = {}
        for character in characters:
            form = draw_form(
                font, character, cell.baseline, ink_level=INK_LEVEL, mark_level=MARK_LEVEL
            )
            glyphs[character] = outlined_glyph(
                raised_marks(separated_dots(character, form), cell.rows - 2).ink,
                cell,
                joins_left=joins_left_neighbour(character),
                joins_right=joins_right_neighbour(character),
            )
        return glyphs
    except FormDoesNotFit:
        return None


def build_gran_turismo_fonts(
    font_path: Path,
    glyph_map: GlyphCodes,
    *,
    body: Collection[str],
    title: Collection[str],
    sizing: Iterable[str] | None = None,
) -> dict[int, GtFont]:
    """Font 1's glyphs for the ``body`` characters and font 2's for the ``title`` ones.

    Each font's size is the largest where every character of ``sizing`` fits:
    the whole repertoire and the digits, whatever the text uses, so a new word
    never changes the size of the others (a test may give a few characters).
    """
    fonts: dict[int, GtFont] = {}
    for index, used in ((BODY, body), (TITLE, title)):
        cell = CELLS[index]
        hand_drawn = PUNCTUATION[index]
        wanted = {character for character in used if character != " "}
        drawn_set = set(
            (*arabic_presentation_repertoire(), *DIGITS) if sizing is None else sizing
        ) | (wanted - set(hand_drawn))
        drawn = tuple(sorted(drawn_set - set(hand_drawn), key=ord))
        _, size, rendered = largest_fitting_size(
            contextual_font_data(arabic_font_file(font_path), drawn),
            cell.sizes,
            lambda font, drawn=drawn, cell=cell: _drawn_glyphs(font, drawn, cell),
            f"Selected font cannot fit Gran Turismo's font {index} glyphs",
        )
        for character, (rows, top) in hand_drawn.items():
            rendered[character] = outlined_glyph(
                pattern_pixels(rows, top=top), cell, joins_left=False, joins_right=False
            )
        rendered[" "] = GtGlyph(TITLE_SPACE, 0, ())
        glyphs = {}
        for character in used:
            code = glyph_map.code(character)
            if code is None:
                raise no_glyph(character, PROFILE)
            glyphs[code] = rendered[character]
        fonts[index] = GtFont(index, glyphs, size)
    return fonts


# ---------------------------------------------------------------------------
# Encoding translated briefings


def visual_text(text: str) -> str:
    """Logical text in visual order, left to right, its letters shaped."""
    check_logical_arabic(text, PROFILE)
    stream = TokenStream((TextToken(text),))
    reject_mirrored(stream, PROFILE)
    reject_combining_marks(stream, PROFILE)
    painted = rtl_paint_order(legacy_renderer_pipeline(), stream)
    return "".join(token.text for token in painted.tokens if isinstance(token, TextToken))[::-1]


def briefing_characters(
    title: str, paragraphs: Sequence[Sequence[str]]
) -> tuple[set[str], set[str]]:
    """The characters the title paints, and those the paragraphs paint."""
    body = {character for words in paragraphs for word in words for character in visual_text(word)}
    return set(visual_text(title)), body


@dataclass(frozen=True, slots=True)
class GtPlacedWord:
    """A word where it is drawn: its codes, its left edge and its width."""

    codes: bytes
    x: int
    width: int


@dataclass(frozen=True, slots=True)
class GtLine:
    """A body line: its words where the hook draws them, and the line's y as the game
    counts it (the hook draws it ``DROP`` rows lower)."""

    words: tuple[GtPlacedWord, ...]
    y: int


def lay_out_title(title: bytes, font: GtFont) -> GtPlacedWord:
    """The title where the game draws it, centred in the box."""
    width = font.measure(title)
    if width > BOX_WIDTH:
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW, f"The title needs {width}px; the box holds {BOX_WIDTH}px"
        )
    return GtPlacedWord(title, (BOX_WIDTH - width) // 2 + BOX_LEFT, width)


def lay_out_paragraphs(paragraphs: Sequence[Sequence[bytes]], font: GtFont) -> tuple[GtLine, ...]:
    """The body's lines as the game lays them out, each word where the hook draws it."""
    lines: list[GtLine] = []
    y = TOP + TITLE_STEP
    for words in paragraphs:
        widths = [font.measure(word) for word in words]
        for width in widths:
            if width > WIDEST_WORD:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"A word needs {width}px; a word may take {WIDEST_WORD}px",
                )
        start, indent = 0, INDENT
        while start < len(words):
            total, end = indent, start
            while end < len(words):
                step = widths[end] + (SPACE if end > start else 0)
                if total + step > BOX_WIDTH:
                    break
                total, end = total + step, end + 1
            slack = BOX_WIDTH - total
            gaps = max(1, end - start - 1)
            x = indent + BOX_LEFT
            placed = []
            for number in range(end - start):
                width = widths[start + number]
                placed.append(GtPlacedWord(words[start + number], MIRROR - x - width, width))
                x += SPACE + width
                if end < len(words):
                    x += slack * (number + 1) // gaps - slack * number // gaps
            lines.append(GtLine(tuple(placed), y))
            y += LINE_STEP
            start, indent = end, 0
    if len(lines) > MAX_LINES:
        raise ClassicRetroError(
            ErrorCode.TEXT_BOX_OVERFLOW,
            f"The briefing needs {len(lines)} lines; the box shows {MAX_LINES}",
        )
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class EncodedBriefing:
    """A translated briefing's bytes and, with fonts, where its title and words go."""

    briefing: Briefing
    title: GtPlacedWord | None
    lines: tuple[GtLine, ...] | None


class GranTurismoArabicEncoder:
    """Convert a logical Arabic briefing into the game's words, in visual order."""

    def __init__(self, glyph_map: GlyphCodes, fonts: Mapping[int, GtFont] | None = None) -> None:
        self.glyph_map = glyph_map
        self.fonts = fonts

    def codes(self, visual: str) -> bytes:
        output = bytearray()
        for character in visual:
            code = self.glyph_map.code(character)
            if code is None:
                raise no_glyph(character, PROFILE)
            output.append(code)
        return bytes(output)

    def encode(self, title: str, paragraphs: Sequence[Sequence[str]]) -> EncodedBriefing:
        for words in paragraphs:
            for before, after in zip(words, words[1:], strict=False):
                if not _has_arabic(before) and not _has_arabic(after):
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TEXT,
                        f"{before!r} and {after!r} would be drawn the other way round: "
                        "keep a number in one word",
                    )
        title_codes = self.codes(visual_text(title))
        body = tuple(tuple(self.codes(visual_text(word)) for word in words) for words in paragraphs)
        briefing = Briefing(title_codes, body)
        if self.fonts is None:
            return EncodedBriefing(briefing, None, None)
        return EncodedBriefing(
            briefing,
            lay_out_title(title_codes, self.fonts[TITLE]),
            lay_out_paragraphs(body, self.fonts[BODY]),
        )


def _has_arabic(word: str) -> bool:
    return any(is_arabic_letter(character) for character in word)


# ---------------------------------------------------------------------------
# The font page


PAGE_WIDTH = 256
PAGE_ROWS = 256
ROW_BYTES = PAGE_WIDTH // 2


def place_glyphs(
    tiers: Sequence[Sequence[int]], sizes: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Where rectangles of ``sizes`` (width, height) go in the page: each at the first free
    spot from the top left of the first of ``tiers`` with room for it. A tier holds a bit
    for each pixel it keeps out, row by row; a rectangle placed is out of every tier."""
    maps = [list(tier) for tier in tiers]
    places = []
    for width, height in sizes:
        if height == 0:
            places.append((0, 0))
            continue
        for rows in maps:
            spot = _first_fit(rows, width, height)
            if spot is not None:
                break
        else:
            raise ClassicRetroError(
                ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                f"No room in the font page for a {width}x{height} glyph",
            )
        u, v = spot
        for rows in maps:
            for y in range(v, v + height):
                rows[y] |= ((1 << width) - 1) << u
        places.append(spot)
    return places


def _first_fit(rows: Sequence[int], width: int, height: int) -> tuple[int, int] | None:
    full = (1 << PAGE_WIDTH) - 1
    for v in range(PAGE_ROWS - height + 1):
        free = full
        for y in range(v, v + height):
            free &= ~rows[y]
        run = free
        for shift in range(1, width):
            run &= free >> shift
        run &= (1 << (PAGE_WIDTH - width + 1)) - 1
        if run:
            return ((run & -run).bit_length() - 1, v)
    return None


def draw_glyph(page: bytearray, u: int, v: int, glyph: GtGlyph) -> None:
    """The glyph's values into the low two bits of the page's pixels from (u, v)."""
    for y, row in enumerate(glyph.rows):
        for x, value in enumerate(row):
            at = (v + y) * ROW_BYTES + (u + x) // 2
            shift = 4 * ((u + x) % 2)
            page[at] = page[at] & ~(0x3 << shift) & 0xFF | value << shift


# ---------------------------------------------------------------------------
# Previews

# The box's dim background, white ink and black outline.
PREVIEW_COLOURS = {INK: (255, 255, 255), OUTLINE: (0, 0, 0)}
PREVIEW_BACKGROUND = (70, 78, 92)
PREVIEW_MARGIN = 4


def font_preview(fonts: Mapping[int, GtFont]) -> Image.Image:
    """Atlas of the glyphs, the body's then the title's, each in its cell: ink white,
    outline black, the cropped rows grey, the width's end dark red."""
    entries = [
        (index, fonts[index].glyphs[code])
        for index in (BODY, TITLE)
        for code in sorted(fonts[index].glyphs)
    ]
    rows = max(cell.rows for cell in CELLS.values())
    columns = max(cell.widest for cell in CELLS.values())

    def colour(number: int, x: int, y: int) -> tuple[int, int, int]:
        index, glyph = entries[number]
        if x >= glyph.width or y >= CELLS[index].rows:
            return (70, 20, 20)
        row = y - glyph.top
        if not 0 <= row < glyph.height:
            return (50, 50, 50)
        value = glyph.rows[row][x]
        return PREVIEW_COLOURS.get(value, (110, 110, 110))

    return glyph_atlas(len(entries), columns, rows, colour)


def _draw_word(
    image: Image.Image, font: GtFont, word: bytes, x: int, line_y: int, origin: int
) -> None:
    cell = CELLS[font.index]
    for code in word:
        glyph = font.glyphs[code]
        top = line_y + cell.dy - 4 + glyph.top - origin
        for y, row in enumerate(glyph.rows):
            for column, value in enumerate(row):
                colour = PREVIEW_COLOURS.get(value)
                if (
                    colour is not None
                    and 0 <= top + y < image.height
                    and 0 <= x + column < image.width
                ):
                    image.putpixel((x + column, top + y), colour)
        x += glyph.width


def briefing_preview(encoded: EncodedBriefing, fonts: Mapping[int, GtFont]) -> Image.Image:
    """The briefing as the box shows it: rows 64 to 195 of the screen, the title and every
    line where the game draws them, the box's clip marked by a dim rule."""
    if encoded.title is None or encoded.lines is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs the fonts")
    height = BOX_BOTTOM + 1 - TOP
    image = Image.new("RGB", (MIRROR, height + 2 * PREVIEW_MARGIN), PREVIEW_BACKGROUND)
    origin = TOP - PREVIEW_MARGIN
    title = encoded.title
    _draw_word(image, fonts[TITLE], title.codes, title.x, TOP + TITLE_DROP, origin)
    for line in encoded.lines:
        for word in line.words:
            _draw_word(image, fonts[BODY], word.codes, word.x, line.y + DROP, origin)
    for x in range(0, MIRROR, 2):
        image.putpixel((x, PREVIEW_MARGIN - 1), (40, 40, 40))
        image.putpixel((x, PREVIEW_MARGIN + height), (40, 40, 40))
    return image


def briefings_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 60)
