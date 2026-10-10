"""The Arabic glyphs drawn into Polished Crystal's fonts: the 8x8 typefaces and the VWF.

The game's 1bpp fonts (``gfx/font/*.png``) hold the characters ``$80-$ff`` as
8x8 tiles, sixteen a row (code ``$80`` is tile 0). ``draw_font`` writes every
Arabic glyph at its code and the redrawn punctuation at theirs; the bold
typeface takes each glyph emboldened by one pixel to the left. Every typeface is
drawn over the game's Normal font (``typefaces``): Arabic has one style, which
the Bold option emboldens. Black is ink, white is paper, as in the game's own
PNGs.

The variable-width font (``gfx/font/vwf.png``, the same layout) measures each
glyph by its leading columns that are not grey (``tools/vwf``): a glyph is drawn
at the tile's left, then grey columns fill the tile. ``vwf_columns`` crops each
8x8 form to its ink, keeps one pixel of a joining stroke on a joining side (so
joined letters touch while the font stays narrow) and gives a side that does not
join the next letter one blank column, the gap between words and letters.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence

from PIL import Image

from classic_retro.engines.pokemon_gen2_arabic.forms import CODES, PRESENTATION_GLYPH, shape
from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS, PUNCTUATION_GLYPHS

# The typefaces the overlay writes (gfx/font/<name>.png), all drawn over the
# Normal font. The engine keeps Normal and Bold (and Unown, which keeps its own
# glyphs); the other five are written as well, so no font file of the tree is left
# with Latin glyphs at the Arabic codes.
TYPEFACES = ("normal", "narrow", "bold", "italic", "serif", "chicago", "micr")
BOLD_TYPEFACES = frozenset({"bold"})

INK, PAPER, GREY = 0, 255, 170
BASELINE = 5
# Pixels of a joining stroke kept on each joined side of a VWF glyph.
KASHIDA = 1
FIRST_CODE = 0x80
SPACE_CODE = 0x7F


def _tile_origin(code: int) -> tuple[int, int]:
    index = code - FIRST_CODE
    return (index % 16) * 8, (index // 16) * 8


def bold_rows(rows: Sequence[str]) -> list[str]:
    """Every stroke one pixel wider to the left, never into column 0 but on the baseline."""
    out = []
    for row_index, row in enumerate(rows):
        cells = list(row)
        for column in range(1, 8):
            if row[column] == "#" and cells[column - 1] == "." and (column > 1 or row_index == 5):
                cells[column - 1] = "#"
        out.append("".join(cells))
    return out


def _draw(image: Image.Image, code: int, rows: Sequence[str]) -> None:
    x0, y0 = _tile_origin(code)
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            image.putpixel((x0 + x, y0 + y), INK if cell == "#" else PAPER)


def draw_font(image: Image.Image, bold: bool = False) -> Image.Image:
    """The font image (any mode) with the Arabic glyphs and punctuation drawn in, as L."""
    font = image.convert("L")
    for glyph, code in CODES.items():
        _draw(font, code, bold_rows(GLYPHS[glyph]) if bold else GLYPHS[glyph])
    for code, rows in PUNCTUATION_GLYPHS.items():
        _draw(font, code, rows)
    return font


def typefaces(normal: Image.Image) -> dict[str, Image.Image]:
    """Every typeface's image, drawn over the game's Normal font."""
    return {name: draw_font(normal, bold=name in BOLD_TYPEFACES) for name in TYPEFACES}


def png_bytes(image: Image.Image) -> bytes:
    """The image as the PNG Pillow writes for ``image.save("x.png")``."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _columns(rows: Sequence[str]) -> list[str]:
    return ["".join(row[column] for row in rows) for column in range(8)]


def _is_kashida(column: str) -> bool:
    return all((cell == "#") == (row == BASELINE) for row, cell in enumerate(column))


def vwf_columns(rows: Sequence[str]) -> list[str]:
    """An 8x8 form -> the columns of its VWF glyph, left to right."""
    columns = _columns(rows)
    joins_next = rows[BASELINE][0] == "#"
    joined_before = rows[BASELINE][7] == "#"
    inked = [column for column in range(8) if "#" in columns[column]]
    if not inked:
        return ["." * 8]
    low, high = min(inked), max(inked)
    if joins_next:
        run = 0
        while run < 8 and _is_kashida(columns[run]):
            run += 1
        low = max(0, run - KASHIDA) if run else 0
    if joined_before:
        run = 0
        while run < 8 and _is_kashida(columns[7 - run]):
            run += 1
        high = min(7, 7 - run + KASHIDA) if run else 7
    out = columns[low : high + 1]
    if not joins_next:
        out = ["." * 8, *out]
    if not 1 <= len(out) <= 8:
        raise ValueError(f"VWF glyph of {len(out)} columns")
    return out


def _draw_vwf_tile(image: Image.Image, code: int, columns: Sequence[str]) -> None:
    x0, y0 = _tile_origin(code)
    for x in range(8):
        for y in range(8):
            if x < len(columns):
                value = INK if columns[x][y] == "#" else PAPER
            else:
                value = GREY
            image.putpixel((x0 + x, y0 + y), value)


def vwf_glyphs() -> dict[int, list[str]]:
    """Code -> VWF columns of every Arabic glyph and redrawn punctuation."""
    glyphs = {code: vwf_columns(GLYPHS[glyph]) for glyph, code in CODES.items()}
    for code, rows in PUNCTUATION_GLYPHS.items():
        glyphs[code] = vwf_columns(rows)
    return glyphs


def draw_vwf_font(image: Image.Image) -> Image.Image:
    """``vwf.png`` with every Arabic glyph and the redrawn punctuation, as L."""
    font = image.convert("L")
    for code, columns in vwf_glyphs().items():
        _draw_vwf_tile(font, code, columns)
    return font


def tile_glyph(image: Image.Image, code: int) -> tuple[list[str], int]:
    """(columns, width) of a VWF tile as the game measures it; the space is 4 wide."""
    if code == SPACE_CODE:
        return ["." * 8] * 4, 4
    x0, y0 = _tile_origin(code)
    columns = []
    for x in range(8):
        column = [image.getpixel((x0 + x, y0 + y)) for y in range(8)]
        if all(value == GREY for value in column):
            break
        columns.append("".join("#" if value == INK else "." for value in column))
    return columns, len(columns)


def vwf_widths(vwf: Image.Image, space: Image.Image) -> dict[int, int]:
    """Pixel width of every code ``$7f-$ff`` in the VWF font (``vwf.png``, ``space.png``)."""
    vwf = vwf.convert("L")
    widths = {code: tile_glyph(vwf, code)[1] for code in range(FIRST_CODE, 0x100)}
    space = space.convert("L")
    widths[SPACE_CODE] = next((x for x in range(8) if space.getpixel((x, 0)) == GREY), 8)
    return widths


# The characters the VWF strings use beside the Arabic forms -> their codes.
VWF_CHARACTERS: dict[str, int] = {
    " ": SPACE_CODE,
    **{chr(0x30 + digit): 0xE0 + digit for digit in range(10)},
    ".": 0x9C,
    ",": 0x9D,
    "?": 0x9E,
    "!": 0x9F,
    "“": 0xBA,
    "-": 0xBC,
    ":": 0xBD,
    **{char: CODES[glyph] for char, glyph in PRESENTATION_GLYPH.items()},
}


def vwf_text_width(text: str, widths: Mapping[int, int]) -> int:
    """Pixel width of a logical (or already shaped) line in the VWF font."""
    shaped = text if any(char in PRESENTATION_GLYPH for char in text) else shape(text)
    return sum(widths[VWF_CHARACTERS[char]] for char in shaped if char in VWF_CHARACTERS)
