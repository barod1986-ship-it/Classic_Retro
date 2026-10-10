"""Arabic lettering for the English words drawn in Polished Crystal's tile graphics.

Some words of the game are not text but pixels of a graphic. The overlay cannot
ship edited PNGs, so it draws the Arabic over the pinned originals at prepare
time: ``outputs(read)`` (or ``apply(tree)`` on a checkout) opens each affected
file, refuses one that is not the pristine file (the SHA-256 of its bytes, and a
PNG's size), clears the English lettering inside exact rectangles and paints the
Arabic, keeping each PNG's mode and size. Everything is computed before anything
is written. Where the English shared tiles between two words, or the Arabic needs
a different arrangement, the tilemap that places the tiles is rewritten too
(``JOBS``); the engine patch (branch fix-graphics) lays out the rest.

What is drawn (``GRAPHICS`` and ``JOBS``):

* gfx/battle/types.png: the 19 type badges (summary, move info, battle, Pokédex);
* gfx/battle/status.png, status-enemy.png, gfx/stats/status.png: the status
  badges (سم شلل نوم حرق جمد);
* gfx/stats/summary_sprites.png: the summary tabs' titles and the "A◀وصف" hint;
  gfx/stats/summary.png: the hidden ability's mark (خ);
* gfx/pack/pack_top.png: the Bag's tab bar, mirrored (DrawPackGFX, _CGB_PackPals);
  gfx/pack/pack_[mfx][0-5].png: the pocket's name under the bag;
* gfx/new_game/init_bg.png: the new game's options footer (InitialOptions, x 7-18);
* gfx/trainer_card/status.png, badges.png, divider.png: the card's headers, on the
  divider's right (TrainerCard_PrintBorder);
* gfx/music_player/bg.png and music_player.tilemap: the channel labels (the
  channels' numbers left of their word) and the noise set's label;
* gfx/type_chart/*: the Type Chart's axes, row and column labels (the tilemap and
  attrmap rebuilt from the image's distinct tiles, as tools/gfx keeps them);
* gfx/pokedex/pokedex0.png, pokedex1.png, oam.png, area.png and the Kanto and
  Orange area maps: the Pokédex's buttons, tabs, banner and region labels;
* gfx/town_map/town_map.png, kanto.bin, orange.bin: the Town Map's region label;
* gfx/pokegear/pokegear.png: the radio's tuning label;
* gfx/pc/pc.png: Bill's PC's party box label;
* gfx/unown_puzzle/start_cancel.png, gfx/trade/border.png, gfx/credits/theend.png.

The lettering is drawn from the overlay's own glyphs (``glyphs.GLYPHS``), shaped
like the translation (``forms.shape``) and cropped to their ink like the VWF
(``fonts.vwf_columns``), in three styles:

* ``BIG``: the 8-row glyphs of the game's font, for labels with a full tile row
  (the pocket tabs and captions, the summary tabs, the radio, the Unown puzzle);
* ``SMALL``: six rows (the glyphs' rows 1-6, joining baseline on row 4), for the
  badges and buttons whose frame leaves six rows inside. Glyphs that reach row 0
  or 7, or would be too wide, have six-row forms of their own (``SMALL_GLYPHS``);
  joined letters share one baseline pixel;
* ``NARROW``: ``SMALL`` with a few narrower forms, for the Type Chart's column
  headers, which stand on end in 17 pixels.

A word is laid out right to left: the first letter on the right, joined letters
touching on the baseline, a blank column after a letter that does not join.
Button names are transliterated (سلكت for SELECT, ستارت for START, A kept as the
button's letter) and the arrow points left (◀, or the small ◂ in the Pokédex).
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from classic_retro.engines.pokemon_gen2_arabic.fonts import vwf_columns
from classic_retro.engines.pokemon_gen2_arabic.forms import PRESENTATION_GLYPH, shape
from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS

# --- glyphs ---------------------------------------------------------------------------

# Six-row forms (drawn on the 8x8 grid, rows 1-6 only, baseline row 5) of the
# glyphs whose 8-row form has ink on row 0 or row 7, or whose dots would touch.
SMALL_GLYPHS: dict[str, tuple[str, ...]] = {
    "alefhamza": (
        "........",
        "...##...",
        "....#...",
        "....#...",
        "....#...",
        "....#...",
        "........",
        "........",
    ),
    "alefmadda": (
        "........",
        "...###..",
        "....#...",
        "....#...",
        "....#...",
        "....#...",
        "........",
        "........",
    ),
    "alefhamzabelow": (
        "........",
        "....#...",
        "....#...",
        "....#...",
        "....#...",
        "....#...",
        "...##...",
        "........",
    ),
    "thal": (
        "........",
        "....#...",
        "........",
        "....#...",
        ".....#..",
        "...#####",
        "........",
        "........",
    ),
    "reh": (
        "........",
        "........",
        "........",
        "........",
        ".......#",
        ".......#",
        ".....##.",
        "........",
    ),
    "zain": (
        "........",
        "........",
        ".......#",
        "........",
        ".......#",
        ".......#",
        ".....##.",
        "........",
    ),
    "waw": (
        "........",
        "........",
        "........",
        ".....##.",
        "....#..#",
        ".....###",
        "...###..",
        "........",
    ),
    "wawhamza": (
        "........",
        ".....##.",
        "........",
        ".....##.",
        "....#..#",
        ".....###",
        "...###..",
        "........",
    ),
    "tehmarbuta": (
        "........",
        "...#.#..",
        "........",
        "...##...",
        "..#..#..",
        "...#####",
        "........",
        "........",
    ),
    "yehhamza.if": (
        "........",
        "...##...",
        "........",
        ".#..##..",
        ".#....#.",
        "..######",
        "........",
        "........",
    ),
    "yehhamza.im": (
        "........",
        "....##..",
        "........",
        ".....#..",
        ".....#..",
        "########",
        "........",
        "........",
    ),
    "beh.if": (
        "........",
        "........",
        "........",
        ".#......",
        ".#......",
        "..######",
        "....#...",
        "........",
    ),
    "beh.im": (
        "........",
        "........",
        "........",
        ".....#..",
        ".....#..",
        "########",
        ".....#..",
        "........",
    ),
    "yeh.if": (
        "........",
        "....##..",
        "...#....",
        ".#..##..",
        ".#....#.",
        "..######",
        "...#.#..",
        "........",
    ),
    "yeh.im": (
        "........",
        "........",
        "........",
        ".....#..",
        ".....#..",
        "########",
        "....#.#.",
        "........",
    ),
    "theh.im": (
        "........",
        ".....#..",
        "....#.#.",
        ".....#..",
        ".....#..",
        "########",
        "........",
        "........",
    ),
    "hah.if": (
        "........",
        "........",
        ".####...",
        "...#.#..",
        "..#...#.",
        "..#....#",
        "...####.",
        "........",
    ),
    "jeem.if": (
        "........",
        "........",
        ".####...",
        "...#.#..",
        "..#...#.",
        "..#..#.#",
        "...####.",
        "........",
    ),
    "khah.if": (
        "........",
        "...#....",
        "........",
        ".####...",
        "..#..#..",
        "..#....#",
        "...####.",
        "........",
    ),
    "jeem.im": (
        "........",
        "........",
        "...###..",
        ".....#..",
        "....#...",
        "########",
        "....#...",
        "........",
    ),
    "khah.im": (
        "........",
        "....#...",
        "........",
        "...###..",
        "....#...",
        "########",
        "........",
        "........",
    ),
    "sheen.if": (
        "........",
        ".....#..",
        "....#.#.",
        "...#.#.#",
        ".#.#.#.#",
        ".#.#####",
        "..#.....",
        "........",
    ),
    "sheen.im": (
        "........",
        "...#....",
        "..#.#...",
        ".#.#.#..",
        ".#.#.#..",
        "########",
        "........",
        "........",
    ),
    "ain.if": (
        "........",
        "........",
        "....###.",
        "...#....",
        "....##..",
        "...#..##",
        "....###.",
        "........",
    ),
    "ghain.if": (
        "........",
        ".....#..",
        "....###.",
        "...#....",
        "....##..",
        "...#..##",
        "....###.",
        "........",
    ),
    "ghain.i": (
        "........",
        "......#.",
        ".....###",
        "....#...",
        "....#...",
        "#####...",
        "........",
        "........",
    ),
    "ghain.m": (
        "........",
        ".....#..",
        "........",
        "...####.",
        "....##..",
        "########",
        "........",
        "........",
    ),
    "qaf.if": (
        "........",
        "....#.#.",
        "........",
        ".....##.",
        "..#.#..#",
        "..#..###",
        "...####.",
        "........",
    ),
    "kaf.im": (
        "........",
        "......#.",
        ".....#..",
        "....#...",
        ".....##.",
        "########",
        "........",
        "........",
    ),
    "meem.if": (
        "........",
        "........",
        "........",
        "....##..",
        "...#..#.",
        "...#####",
        "...#....",
        "........",
    ),
    "heh.m": (
        "........",
        "........",
        "........",
        "....#...",
        "...#.#..",
        "########",
        "....#...",
        "........",
    ),
    "lamalefhamza": (
        "........",
        "..##..#.",
        ".#....#.",
        "..#...#.",
        "...#..#.",
        "..#####.",
        "........",
        "........",
    ),
    "lamalefhamzabelow": (
        "........",
        ".#....#.",
        "..#...#.",
        "..#...#.",
        "...#..#.",
        "..#####.",
        "...##...",
        "........",
    ),
    "lamalefmadda": (
        "........",
        ".###..#.",
        ".#....#.",
        "..#...#.",
        "...#..#.",
        "..#####.",
        "........",
        "........",
    ),
    "lam.if": (
        "........",
        "......#.",
        "......#.",
        "......#.",
        "...#..#.",
        "...#..##",
        "....##..",
        "........",
    ),
    "dal": (
        "........",
        "........",
        "........",
        "....#...",
        ".....#..",
        "...#####",
        "........",
        "........",
    ),
    "hah.im": (
        "........",
        "........",
        "...###..",
        ".....#..",
        "....#...",
        "########",
        "........",
        "........",
    ),
    "meem.im": (
        "........",
        "........",
        "........",
        "...##...",
        "..#..#..",
        "########",
        "........",
        "........",
    ),
}

# Narrower six-row forms for the Type Chart's column headers, which stand on end
# in 17 pixels.
NARROW_GLYPHS: dict[str, tuple[str, ...]] = {
    "yeh.if": (
        "........",
        "........",
        "........",
        "....##..",
        "..#...#.",
        "...#####",
        "...#.#..",
        "........",
    ),
    "dal": (
        "........",
        "........",
        "........",
        ".....#..",
        "......#.",
        ".....###",
        "........",
        "........",
    ),
    "tehmarbuta": (
        "........",
        "....#.#.",
        "........",
        ".....#..",
        "....#.#.",
        ".....###",
        "........",
        "........",
    ),
    "reh": (
        "........",
        "........",
        "........",
        "........",
        ".......#",
        ".......#",
        "......#.",
        "........",
    ),
}

# Signs a label may hold besides the letters, on the 8x8 grid (rows 1-6 for SMALL).
SIGNS: dict[str, tuple[str, ...]] = {
    " ": ("...",) * 8,
    "◀": (
        "......",
        "...#..",
        "..##..",
        ".###..",
        "..##..",
        "...#..",
        "......",
        "......",
    ),
    "◂": (  # a small arrow, for the narrowest buttons
        "....",
        "....",
        "..#.",
        ".##.",
        "..#.",
        "....",
        "....",
        "....",
    ),
    "?": (  # the Arabic question mark, its hook on the left
        "......",
        ".####.",
        ".#....",
        "..##..",
        "...#..",
        "......",
        "...#..",
        "......",
    ),
    "+": (
        "......",
        "......",
        "..#...",
        ".###..",
        "..#...",
        "......",
        "......",
        "......",
    ),
    "A": (
        "......",
        "..#...",
        ".#.#..",
        ".#.#..",
        ".###..",
        ".#.#..",
        ".#.#..",
        "......",
    ),
    "1": (
        "....",
        ".#..",
        "##..",
        ".#..",
        ".#..",
        ".#..",
        "###.",
        "....",
    ),
    "2": (
        ".....",
        ".##..",
        "#..#.",
        "...#.",
        "..#..",
        ".#...",
        "####.",
        ".....",
    ),
}


@dataclass(frozen=True, slots=True)
class Style:
    """A lettering size: the glyph rows it keeps and the six-row overrides it uses."""

    name: str
    rows: tuple[int, ...]
    overrides: Mapping[str, tuple[str, ...]]
    # one baseline pixel between joined letters instead of two
    tight: bool = False

    @property
    def height(self) -> int:
        return len(self.rows)


BIG = Style("big", tuple(range(8)), {})
SMALL = Style("small", tuple(range(1, 7)), SMALL_GLYPHS, tight=True)
NARROW = Style("narrow", tuple(range(1, 7)), {**SMALL_GLYPHS, **NARROW_GLYPHS}, tight=True)


def _glyph_columns(name: str, style: Style) -> list[str]:
    rows = style.overrides.get(name, GLYPHS[name])
    if style is not BIG and name not in style.overrides:
        # row 0 may only hold the top of a stroke that goes on (an ascender)
        top = all(rows[1][x] == "#" for x in range(8) if rows[0][x] == "#")
        if not top or "#" in rows[7]:
            raise ValueError(f"glyph {name} needs a six-row form")
    columns = vwf_columns(rows)
    return ["".join(column[row] for row in style.rows) for column in columns]


def _is_kashida(column: str, style: Style) -> bool:
    baseline = style.rows.index(5)
    return all((cell == "#") == (row == baseline) for row, cell in enumerate(column))


def _sign_columns(char: str, style: Style) -> list[str]:
    rows = SIGNS[char]
    return ["".join(rows[row][x] for row in style.rows) for x in range(len(rows[0]))]


Bitmap = list[str]  # rows, top to bottom; '#' ink, '.' paper


def _trim(columns: list[str]) -> list[str]:
    while columns and "#" not in columns[0]:
        columns.pop(0)
    while columns and "#" not in columns[-1]:
        columns.pop()
    return columns


def render(text: str, style: Style = SMALL, gap: int = 1) -> Bitmap:
    """A logical Arabic label as a bitmap, laid out right to left (no margins).

    ``gap`` blank columns separate the parts of a label that do not join (the
    glyphs' own blank column is replaced by it); a space is three columns.
    Runs of Latin capitals and digits (button names) keep their order.
    """
    chars = list(shape(text))
    # (columns, joins the letter after it) of each character, in logical order
    parts: list[tuple[list[str], bool]] = []
    for char in chars:
        if char in PRESENTATION_GLYPH:
            name = PRESENTATION_GLYPH[char]
            joins_next = GLYPHS[name][5][0] == "#"
            columns = _glyph_columns(name, style)
            if not joins_next:
                columns = _trim(columns)
            elif style.tight and len(columns) > 1 and _is_kashida(columns[0], style):
                columns = columns[1:]
            parts.append((columns, joins_next))
        elif char == " ":
            parts.append((["." * style.height] * 2, False))
        elif char in SIGNS:
            parts.append((_trim(_sign_columns(char, style)), False))
        else:
            raise ValueError(f"{text!r}: no glyph for {char!r}")
    # Visual order: right to left, except runs of Latin capitals and digits.
    visual: list[tuple[list[str], bool]] = []
    index = len(parts)
    while index > 0:
        start = index
        while start > 0 and chars[start - 1] in "A12":
            start -= 1
        if start < index:
            run = parts[start:index]
            # left to right; each part is separated from the one on its right
            visual += [(columns, False) for columns, _ in run]
            index = start
        else:
            visual.append(parts[index - 1])
            index -= 1
    columns: list[str] = []
    for position, (part, joins_left) in enumerate(visual):
        # a part that joins the one on its left touches it; any other is set apart
        if position and not joins_left:
            columns += ["." * style.height] * gap
        columns += part
    columns = _trim(columns)
    return ["".join(column[row] for column in columns) for row in range(style.height)]


def width(bitmap: Bitmap) -> int:
    return len(bitmap[0]) if bitmap else 0


def rotate_ccw(bitmap: Bitmap) -> Bitmap:
    """The bitmap turned a quarter left (its right end on top): read top to bottom."""
    h, w = len(bitmap), width(bitmap)
    return ["".join(bitmap[y][w - 1 - x] for y in range(h)) for x in range(w)]


# --- painting -------------------------------------------------------------------------


def fill(image: Image.Image, box: tuple[int, int, int, int], value: int) -> None:
    """Fill ``box`` (x0, y0, x1, y1 inclusive) with ``value``."""
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            image.putpixel((x, y), value)


def paint(image: Image.Image, x: int, y: int, bitmap: Bitmap, ink: int) -> None:
    for dy, row in enumerate(bitmap):
        for dx, cell in enumerate(row):
            if cell == "#":
                image.putpixel((x + dx, y + dy), ink)


def place(
    image: Image.Image,
    box: tuple[int, int, int, int],
    bitmap: Bitmap,
    ink: int,
    align: str = "center",
    top: int | None = None,
) -> tuple[int, int]:
    """Paint ``bitmap`` inside ``box`` (inclusive), aligned right, left or centred.

    Refuses a bitmap wider or taller than the box. Returns its (x, y).
    """
    x0, y0, x1, y1 = box
    room_w, room_h = x1 - x0 + 1, y1 - y0 + 1
    w, h = width(bitmap), len(bitmap)
    if w > room_w or h > room_h:
        raise ValueError(f"label {w}x{h} does not fit {room_w}x{room_h}")
    if align == "right":
        x = x1 + 1 - w
    elif align == "left":
        x = x0
    else:
        x = x0 + (room_w - w + 1) // 2
    y = y0 + (room_h - h) // 2 if top is None else y0 + top
    paint(image, x, y, bitmap, ink)
    return x, y


# --- the graphics ---------------------------------------------------------------------

WHITE, LIGHT, DARK, BLACK = 255, 170, 85, 0


@dataclass(frozen=True, slots=True)
class Graphic:
    """A pinned PNG and how its lettering is redrawn."""

    path: str
    size: tuple[int, int]
    sha256: str
    draw: Callable[[Image.Image], None]


def pill(image: Image.Image, box: tuple[int, int, int, int], value: int, paper: int) -> None:
    """``box`` (inclusive) filled with ``value``, its four corner pixels left ``paper``."""
    x0, y0, x1, y1 = box
    fill(image, box, value)
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        image.putpixel((x, y), paper)


# Type names (constants/type_constants.asm order), as the type badges show them.
TYPE_NAMES = (
    "عادي",  # NORMAL
    "قتال",  # FIGHTING
    "طائر",  # FLYING
    "سم",  # POISON
    "أرضي",  # GROUND
    "صخري",  # ROCK
    "حشرة",  # BUG
    "شبح",  # GHOST
    "فولاذ",  # STEEL
    "نار",  # FIRE
    "ماء",  # WATER
    "عشب",  # GRASS
    "كهربائي",  # ELECTRIC
    "نفسي",  # PSYCHIC
    "جليد",  # ICE
    "تنين",  # DRAGON
    "ظلام",  # DARK
    "جني",  # FAIRY
    "؟؟؟",  # UNKNOWN_T
)


def draw_type_badges(image: Image.Image) -> None:
    """gfx/battle/types.png: 4x1-tile badges, white letters on a black pill (1bpp).

    The English pill is 7 rows with 5 for the letters; the Arabic one fills the
    tile row (rows 0-7, corners cut) to leave six rows inside (1-6).
    """
    for index, name in enumerate(TYPE_NAMES):
        y = index * 8
        fill(image, (0, y, 31, y + 7), WHITE)
        pill(image, (1, y, 30, y + 7), BLACK, WHITE)
        place(image, (2, y + 1, 29, y + 6), render(name, SMALL), WHITE)


# Status conditions by GetStatusConditionIndex (0 none, 6 fainted: blank).
STATUS_NAMES = {1: "سم", 2: "شلل", 3: "نوم", 4: "حرق", 5: "جمد", 7: "سم"}


def draw_status_badges(image: Image.Image) -> None:
    """gfx/stats/status.png, gfx/battle/status*.png: 2x1-tile status badges.

    Each badge keeps its colours (the pill's and the letters', which differ by
    file and for the toxic badge) and fills the tile row to leave six rows inside.
    """
    for index, name in STATUS_NAMES.items():
        y = index * 8
        counts: dict[int, int] = {}
        for py in range(y + 1, y + 8):
            for px in range(16):
                value = image.getpixel((px, py))
                counts[value] = counts.get(value, 0) + 1
        colours = sorted((count, value) for value, count in counts.items() if value != WHITE)
        body = colours[-1][1]
        ink = colours[-2][1] if len(colours) > 1 else WHITE
        fill(image, (0, y, 15, y + 7), WHITE)
        pill(image, (0, y, 15, y + 7), body, WHITE)
        place(image, (1, y + 1, 14, y + 6), render(name, SMALL), ink)


# The summary screen's tab titles (SUMMARY_TILE_OAM_*_TITLE), 4 tiles each.
SUMMARY_TITLES = ("الخبرة", "القدرة", "الأداة", "الحركة", "اللقاء", "بيضة")


def draw_summary_sprites(image: Image.Image) -> None:
    """gfx/stats/summary_sprites.png: the A-button hint and the tab titles (OAM).

    White is the sprites' transparent colour. The hint's pill fills its tile row
    for six rows of letters: "A◀وصف" (A shows the move's description).
    """
    fill(image, (0, 8, 31, 15), WHITE)
    pill(image, (0, 8, 31, 15), LIGHT, WHITE)
    place(image, (1, 9, 30, 14), render("A◀وصف", SMALL), DARK)
    for index, title in enumerate(SUMMARY_TITLES):
        y = 16 + index * 8
        fill(image, (0, y, 31, y + 7), WHITE)
        place(image, (0, y, 31, y + 7), render(title, BIG), DARK)


def _bold(rows: Sequence[str]) -> list[str]:
    """Every stroke one pixel wider to the left (as the Bold typeface)."""
    out = []
    for row in rows:
        cells = list(row)
        for x in range(1, len(row)):
            if row[x] == "#" and row[x - 1] == ".":
                cells[x - 1] = "#"
        out.append("".join(cells))
    return out


def draw_summary_tiles(image: Image.Image) -> None:
    """gfx/stats/summary.png: the hidden ability's mark (SUMMARY_TILE_HIDDEN_H).

    "H" becomes a bold khah, the first letter of the hidden ability (مخفية).
    """
    x0 = 12 * 8
    fill(image, (x0, 0, x0 + 7, 7), WHITE)
    paint(image, x0, 0, _bold(GLYPHS["khah.if"]), BLACK)


# --- the Bag ---

# Pocket tabs, left to right on the tab bar (the first pocket on the right):
# (PNG tile range, word, colour). The tab bar's tile 19 is the cursor, which
# DrawPackGFX inserts right of the current pocket; a pocket's colour is one of
# the two each column's palette holds (_CGB_PackPals).
POCKET_TABS = (
    ((0, 2), "مهم", DARK),  # Key Items
    ((3, 5), "توت", LIGHT),  # Berries
    ((6, 8), "آلات", DARK),  # TM/HM
    ((9, 11), "كرات", LIGHT),  # Balls
    ((12, 14), "دواء", DARK),  # Medicine
    ((15, 18), "أدوات", LIGHT),  # Items
)
POCKET_CAPTIONS = ("الأدوات", "الدواء", "الكرات", "الآلات", "التوت", "المهم")


def draw_pack_tabs(image: Image.Image) -> None:
    """gfx/pack/pack_top.png: the pocket tab bar, mirrored for right to left.

    The words sit flush right in their tiles (one pixel short of the edge); the
    cursor tile (19) holds a left-pointing arrow on its left side.
    """
    fill(image, (0, 0, 159, 7), BLACK)
    for (first, last), word, colour in POCKET_TABS:
        place(image, (first * 8, 0, last * 8 + 6, 7), render(word, BIG), colour, "right")
    arrow = ["..#", ".##", "###", ".##", "..#"]
    paint(image, 19 * 8 + 1, 1, arrow, WHITE)


def _pack_caption(index: int) -> Callable[[Image.Image], None]:
    def draw(image: Image.Image) -> None:
        """gfx/pack/pack_*N.png: the pocket's name in the band under the bag."""
        fill(image, (0, 32, 39, 39), DARK)
        place(image, (0, 32, 39, 39), render(POCKET_CAPTIONS[index], BIG), WHITE)

    return draw


# --- the new game's options ---


def draw_init_footer(image: Image.Image) -> None:
    """gfx/new_game/init_bg.png: the footer buttons (tiles 3-14, palette 1).

    InitialOptions places the 12 tiles at x 7-18; the first button is on the
    right: SELECT (red, colour 1) shows the option's help, START (blue,
    colour 2) ends the options.
    """
    fill(image, (24, 0, 119, 7), WHITE)
    right = 118
    for text, colour in (("سلكت◀شرح", LIGHT), ("ستارت◀تم", DARK)):
        bitmap = render(text, SMALL)
        left = right - width(bitmap) - 5
        if left < 24:
            raise ValueError("the footer buttons do not fit")
        pill(image, (left, 0, right, 7), colour, WHITE)
        place(image, (left + 2, 1, right - 2, 6), bitmap, WHITE)
        right = left - 3


# --- the trainer card ---


def _card_header(word: str) -> Callable[[Image.Image], None]:
    def draw(image: Image.Image) -> None:
        """gfx/trainer_card/status.png, badges.png: the divider's header (4 tiles).

        Black letters (the English's light shadow would blur the Arabic),
        flush right: TrainerCard_PrintBorder puts the header at the right end
        of the divider.
        """
        fill(image, (0, 0, 31, 7), WHITE)
        place(image, (0, 1, 30, 6), render(word, SMALL), BLACK, "right")

    return draw


def draw_card_divider(image: Image.Image) -> None:
    """gfx/trainer_card/divider.png: the divider's ends, mirrored.

    Tile 1 ($24, left of the header) held the English headers' shared last
    letter; it becomes the dots' end. Tile 0 ($23) is the divider's right end.
    """
    fill(image, (0, 0, 15, 7), WHITE)
    fill(image, (0, 1, 2, 3), LIGHT)  # $24: the dots go on into it
    fill(image, (3, 4, 5, 6), DARK)
    fill(image, (8 + 2, 1, 8 + 4, 3), LIGHT)  # $23: the end, after the header
    fill(image, (8 + 5, 4, 8 + 7, 6), DARK)


# --- the Music Player ---

# The slash across a channel label that is switched off (as the English).
MP_OFF_SLASH = ((19, 20), (16, 18), (13, 15), (11, 12), (8, 10), (5, 7), (3, 4))


def _tile_x(index: int) -> int:
    return (index % 16) * 8


def _tile_y(index: int) -> int:
    return (index // 16) * 8


def _paste_strip(image: Image.Image, strip: Image.Image, tiles: Sequence[int]) -> None:
    """Cut a strip of tiles into the sheet's tiles ``tiles`` (left to right)."""
    for position, index in enumerate(tiles):
        image.paste(
            strip.crop((position * 8, 0, position * 8 + 8, 8)), (_tile_x(index), _tile_y(index))
        )


def _mp_strip(
    parts: Sequence[tuple[tuple[int, int, int, int], Bitmap]], ink: int, off: bool
) -> Image.Image:
    """A 3-tile label: each bitmap flush right in its box; slashed when ``off``."""
    strip = Image.new("L", (24, 8), WHITE)
    for box, bitmap in parts:
        place(strip, box, bitmap, ink, "right")
    if off:
        for row, (x0, x1) in enumerate(MP_OFF_SLASH):
            for x in range(x0, x1 + 1):
                strip.putpixel((x, row), BLACK)
    return strip


def draw_music_player(image: Image.Image) -> None:
    """gfx/music_player/bg.png: the channel labels and the noise set's label.

    Channels 1 and 2 share the word's two tiles ($07 $08, off $11 $12) and
    each has its number's tile ($09, $0a, off $13, $14), which the Arabic puts
    on the left: ChannelsOnTilemaps and the tilemap place it first. A label
    ends a pixel short of the line on its right. The labels of a switched-off
    channel are dim and slashed, as the English.
    """
    for index in range(0x07, 0x1D):
        x, y = _tile_x(index), _tile_y(index)
        fill(image, (x, y, x + 7, y + 7), WHITE)
    word = render("قناة", SMALL)
    labels = (
        (False, BLACK, (0x07, 0x08), (0x09, 0x0A), (0x0B, 0x0C, 0x0D), (0x0E, 0x0F, 0x10)),
        (True, DARK, (0x11, 0x12), (0x13, 0x14), (0x15, 0x16, 0x17), (0x18, 0x19, 0x1A)),
    )
    for off, ink, shared, numbers, wave, noise in labels:
        for number_tile, number in zip(numbers, "12", strict=True):
            parts = (((8, 1, 22, 6), word), ((0, 1, 6, 6), _trim_rows(_sign_bitmap(number))))
            _paste_strip(image, _mp_strip(parts, ink, off), (number_tile, *shared))
        _paste_strip(image, _mp_strip((((0, 1, 22, 6), render("موجة", SMALL)),), ink, off), wave)
        _paste_strip(image, _mp_strip((((0, 1, 22, 6), render("ضجة", SMALL)),), ink, off), noise)
    strip = Image.new("L", (16, 8), WHITE)
    place(strip, (0, 1, 15, 6), render("طقم", SMALL), BLACK, "right")
    _paste_strip(image, strip, (0x1B, 0x1C))


def _sign_bitmap(char: str) -> Bitmap:
    rows = SIGNS[char]
    return [rows[row] for row in SMALL.rows]


def _trim_rows(bitmap: Bitmap) -> Bitmap:
    columns = _trim(["".join(row[x] for row in bitmap) for x in range(width(bitmap))])
    return ["".join(column[y] for column in columns) for y in range(len(bitmap))]


def draw_music_tilemap(data: bytes) -> bytes:
    """gfx/music_player/music_player.tilemap: the channel numbers left of their
    word, the noise set's label at the right end (its number at x 16)."""
    tiles = bytearray(data)
    width_ = 20
    for x, number in ((0, 0x09), (5, 0x0A)):
        if tiles[width_ + x : width_ + x + 3] != bytes((0x07, 0x08, number)):
            raise PristineMismatch("music_player.tilemap: channel labels moved")
        tiles[width_ + x : width_ + x + 3] = bytes((number, 0x07, 0x08))
    row = 2 * width_
    if tiles[row + 16 : row + 20] != bytes((0x1B, 0x1C, 0x7F, 0x7F)):
        raise PristineMismatch("music_player.tilemap: the set's label moved")
    tiles[row + 16 : row + 20] = bytes((0x7F, 0x7F, 0x1B, 0x1C))
    return bytes(tiles)


# --- the Type Chart ---
#
# gfx/type_chart/bg.png is the whole screen; the build keeps its distinct tiles
# (tools/gfx --remove-duplicates --remove-xflip --remove-yflip) and the static
# type_chart.tilemap/.attrmap place them, so the overlay rebuilds both maps from
# the redrawn image the same way (tile ids, VRAM bank and flips; each cell's
# palette is kept). The rows name the attacking type in full; the columns,
# standing on end in 17 pixels (16 for the sprites of Ghost and Steel), use a
# short word where the full one does not fit.

TC_ROW_NAMES = (
    "عادي",
    "قتال",
    "طائر",
    "سم",
    "أرضي",
    "صخري",
    "حشرة",
    "شبح",
    "فولاذ",
    "نار",
    "ماء",
    "عشب",
    "كهرباء",
    "نفسي",
    "جليد",
    "تنين",
    "ظلام",
    "جني",
)
TC_COLUMN_NAMES = (
    "عادي",
    "قتال",
    "طائر",
    "سم",
    "أرض",
    "صخر",
    "حشرة",
    "شبح",
    "صلب",
    "نار",
    "ماء",
    "عشب",
    "كهرب",
    "نفس",
    "جليد",
    "تنين",
    "ظلمة",
    "جني",
)
TC_SPRITE_TYPES = (7, 8)  # Ghost and Steel: drawn by sprites (ob.png)
_LEVEL = {WHITE: 0, LIGHT: 1, DARK: 2, BLACK: 3}
_REVERSED_BITS = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))


def _tile_bytes(image: Image.Image, tx: int, ty: int) -> bytes:
    """One 8x8 tile as rgbgfx -c dmg writes it (2bpp, white is colour 0)."""
    out = bytearray()
    for y in range(8):
        low = high = 0
        for x in range(8):
            colour = _LEVEL[image.getpixel((tx * 8 + x, ty * 8 + y))]
            low |= (colour & 1) << (7 - x)
            high |= (colour >> 1) << (7 - x)
        out += bytes((low, high))
    return bytes(out)


def _flip(tile: bytes, xflip: bool, yflip: bool) -> bytes:
    rows = [tile[i : i + 2] for i in range(0, 16, 2)]
    if yflip:
        rows.reverse()
    if xflip:
        rows = [bytes((_REVERSED_BITS[row[0]], _REVERSED_BITS[row[1]])) for row in rows]
    return b"".join(rows)


def _distinct_tiles(tiles: Sequence[bytes]) -> list[bytes]:
    """tools/gfx --remove-duplicates --remove-xflip --remove-yflip, pass by pass."""
    kept: list[bytes] = []
    for tile in tiles:
        if tile not in kept:
            kept.append(tile)
    for xflip, yflip in ((True, False), (False, True), (True, True)):
        passed: list[bytes] = []
        for tile in kept:
            if _flip(tile, xflip, yflip) not in passed:
                passed.append(tile)
        kept = passed
    return kept


# Distinct tiles 0-254 go to VRAM bank 1 (ids 0-126, then 128-255), the rest to
# bank 0 from id 0 (_TypeChart loads TC_BANK0_TILES of them).
TC_BANK0_TILES = 40


def _tile_place(index: int) -> tuple[int, int]:
    """(tile id, VRAM bank) of distinct tile ``index``."""
    if index < 127:
        return index, 1
    if index < 255:
        return index + 1, 1
    return index - 255, 0


def _type_chart_maps(image: Image.Image, tilemap: bytes, attrmap: bytes) -> tuple[bytes, bytes]:
    tiles = [_tile_bytes(image, tx, ty) for ty in range(18) for tx in range(20)]
    distinct = _distinct_tiles(tiles)
    if len(distinct) > 255 + TC_BANK0_TILES:
        raise ValueError(
            f"type chart: {len(distinct)} distinct tiles, at most {255 + TC_BANK0_TILES}"
        )
    lookup: dict[bytes, tuple[int, bool, bool]] = {}
    for index, tile in enumerate(distinct):
        for xflip, yflip in ((False, False), (True, False), (False, True), (True, True)):
            lookup.setdefault(_flip(tile, xflip, yflip), (index, xflip, yflip))
    new_tiles, new_attrs = bytearray(), bytearray()
    for position, tile in enumerate(tiles):
        attr = attrmap[position]
        xflip, yflip = bool(attr & 0x20), bool(attr & 0x40)
        found = None
        for index, candidate in enumerate(distinct):
            if _flip(candidate, xflip, yflip) == tile:
                found = (index, xflip, yflip)
                break
        index, xflip, yflip = found or lookup[tile]
        tile_id, bank = _tile_place(index)
        new_tiles.append(tile_id)
        new_attrs.append((attr & 0x97) | (bank << 3) | (xflip << 5) | (yflip << 6))
    return bytes(new_tiles), bytes(new_attrs)


def _fill_colour(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    """The most common colour in ``box`` that is not white (a label's ground)."""
    counts: dict[int, int] = {}
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            value = image.getpixel((x, y))
            if value != WHITE:
                counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda value: counts[value])


def _relabel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    bitmap: Bitmap,
    align: str,
    top: int | None = None,
    right_margin: int = 0,
) -> None:
    """A label's ground filled in (the English letters gone), the Arabic in white."""
    fill(image, box, _fill_colour(image, box))
    x0, y0, x1, y1 = box
    place(image, (x0, y0, x1 - right_margin, y1), bitmap, WHITE, align, top)


TC_DIAGONAL = [
    (8, 0),
    (9, 1),
    (10, 1),
    (11, 2),
    (12, 3),
    (13, 3),
    (14, 4),
    (15, 5),
    (16, 5),
    (17, 6),
    (18, 7),
    (19, 7),
    (20, 8),
    (21, 9),
    (22, 9),
    (23, 10),
    (24, 11),
    (25, 11),
    (26, 12),
    (27, 13),
    (28, 13),
    (29, 14),
    (30, 15),
    (31, 15),
    (32, 16),
]


def draw_type_chart_bg(image: Image.Image) -> None:
    """The chart's labels: the corner's two words, the row and column labels."""
    # the corner: "هجوم" (attacker, the rows) below the diagonal, "دفاع" (the
    # defender, the columns) above it, both red (the corner's palette); the
    # English DEF was a sprite (cleared in ob.png). The diagonal keeps a pixel
    # clear of the letters.
    fill(image, (0, 0, 33, 17), WHITE)
    attack = render("هجوم", SMALL)
    defence = render("دفاع", SMALL)
    paint(image, 8, 11, attack, BLACK)
    paint(image, 31 - width(defence) + 1, 0, defence, BLACK)
    ink = {(x, y) for x in range(34) for y in range(18) if image.getpixel((x, y)) == BLACK}
    for x, y in TC_DIAGONAL:
        if not any((x + dx, y + dy) in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            image.putpixel((x, y), LIGHT)
    for column, name in enumerate(TC_COLUMN_NAMES):
        if column in TC_SPRITE_TYPES:
            continue
        x = 34 + 7 * column
        _relabel(image, (x, 0, x + 6, 16), rotate_ccw(render(name, NARROW)), "right")
    for row, name in enumerate(TC_ROW_NAMES):
        if row in TC_SPRITE_TYPES:
            continue
        y = 18 + 7 * row
        _relabel(image, (8, y, 32, y + 6), render(name, SMALL), "right", top=1, right_margin=1)


def draw_type_chart_ob(image: Image.Image) -> None:
    """ob.png (8x16 sprites, two tile rows): DEF cleared, Ghost and Steel labels."""
    fill(image, (8, 0, 23, 15), WHITE)  # DEF ($02, $04): the corner's BG says it
    # the Ghost and Steel column headers ($06, $08)
    for tile_x, name in ((3, TC_COLUMN_NAMES[7]), (4, TC_COLUMN_NAMES[8])):
        x = tile_x * 8 + (1 if tile_x == 3 else 0)
        _relabel(image, (x, 0, x + 6, 15), rotate_ccw(render(name, NARROW)), "right")
    # their row labels ($0e-$14, x 8-32 on screen: the strip's first 25 pixels)
    _relabel(image, (56, 1, 80, 7), render(TC_ROW_NAMES[7], SMALL), "right", top=1, right_margin=1)
    _relabel(image, (56, 8, 80, 14), render(TC_ROW_NAMES[8], SMALL), "right", top=1, right_margin=1)


def _type_chart_job(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    with Image.open(io.BytesIO(sources["gfx/type_chart/bg.png"])) as original:
        bg = original.copy()
    with Image.open(io.BytesIO(sources["gfx/type_chart/ob.png"])) as original:
        ob = original.copy()
    draw_type_chart_bg(bg)
    draw_type_chart_ob(ob)
    tilemap, attrmap = _type_chart_maps(
        bg,
        sources["gfx/type_chart/type_chart.tilemap"],
        sources["gfx/type_chart/type_chart.attrmap"],
    )
    return {
        "gfx/type_chart/bg.png": _png_bytes(bg),
        "gfx/type_chart/ob.png": _png_bytes(ob),
        "gfx/type_chart/type_chart.tilemap": tilemap,
        "gfx/type_chart/type_chart.attrmap": attrmap,
    }


# --- the Pokédex, the Pokégear, the PC ---


def _sheet_strip(image: Image.Image, tiles: Sequence[int], columns: int = 16) -> Image.Image:
    """The tiles ``tiles`` of a sheet ``columns`` tiles wide, side by side."""
    strip = Image.new(image.mode, (8 * len(tiles), 8))
    for position, index in enumerate(tiles):
        x, y = (index % columns) * 8, (index // columns) * 8
        strip.paste(image.crop((x, y, x + 8, y + 8)), (position * 8, 0))
    return strip


def _sheet_paste(
    image: Image.Image, strip: Image.Image, tiles: Sequence[int], columns: int = 16
) -> None:
    for position, index in enumerate(tiles):
        x, y = (index % columns) * 8, (index // columns) * 8
        image.paste(strip.crop((position * 8, 0, position * 8 + 8, 8)), (x, y))


def _refill_rows(
    image: Image.Image, box: tuple[int, int, int, int], colour: int, paper: int = WHITE
) -> None:
    """Each row of ``box`` filled with ``colour`` between its first and last
    pixel of that colour: a button's English letters gone, its shape kept."""
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        xs = [x for x in range(x0, x1 + 1) if image.getpixel((x, y)) == colour]
        if xs:
            for x in range(min(xs), max(xs) + 1):
                image.putpixel((x, y), colour)


def _button(
    image: Image.Image, box: tuple[int, int, int, int], colour: int, paper: int = WHITE
) -> None:
    """A button filling ``box`` (eight rows), its corners rounded by two pixels."""
    x0, y0, x1, y1 = box
    fill(image, box, paper)
    for y in range(y0, y1 + 1):
        inset = 2 if y in (y0, y1) else 1 if y in (y0 + 1, y1 - 1) else 0
        for x in range(x0 + inset, x1 - inset + 1):
            image.putpixel((x, y), colour)


def draw_dex_bg0(image: Image.Image) -> None:
    """gfx/pokedex/pokedex0.png: the list's SELECT and START buttons, the Info tab."""
    strip = _sheet_strip(image, range(0x20, 0x25))  # SEL▶MODE (its left cap is tile $10)
    _refill_rows(strip, (0, 1, 39, 7), DARK)
    place(strip, (0, 1, 36, 6), render("سلكت◂نمط", SMALL), WHITE, "right")
    _sheet_paste(image, strip, range(0x20, 0x25))
    strip = _sheet_strip(image, range(0x30, 0x37))  # START▶SEARCH
    _refill_rows(strip, (0, 1, 55, 7), BLACK)
    place(strip, (2, 1, 53, 6), render("ستارت◂بحث", SMALL), WHITE)
    _sheet_paste(image, strip, range(0x30, 0x37))
    strip = _sheet_strip(image, range(0x2C, 0x2F))  # Info
    fill(strip, (0, 0, 23, 7), BLACK)
    place(strip, (0, 1, 23, 6), render("وصف", SMALL), WHITE)
    _sheet_paste(image, strip, range(0x2C, 0x2F))


def draw_dex_bg1(image: Image.Image) -> None:
    """gfx/pokedex/pokedex1.png: the SELECT (shiny) button and the Area tab."""
    strip = _sheet_strip(image, range(0x00, 0x06))  # SEL▶SHINY, between two rules
    _refill_rows(strip, (0, 1, 47, 7), DARK)
    place(strip, (7, 1, 45, 6), render("سلكت◂لامع", SMALL), WHITE)
    _sheet_paste(image, strip, range(0x00, 0x06))
    strip = _sheet_strip(image, range(0x29, 0x2C))  # Area
    fill(strip, (0, 0, 23, 7), BLACK)
    place(strip, (0, 1, 23, 6), render("موقع", SMALL), WHITE)
    _sheet_paste(image, strip, range(0x29, 0x2C))


def draw_dex_sprites(image: Image.Image) -> None:
    """gfx/pokedex/oam.png: the START (form), SELECT (clear) and A (cry) buttons,
    the Bio and Stats tabs and the hidden ability's mark.

    White is transparent. The SELECT button's word sits in its last tiles
    ($0e $0f and the cap $10), which the area screen shows alone (area.asm).
    """
    strip = Image.new("L", (48, 8), WHITE)  # START▶FORM, $05-$0a
    _button(strip, (0, 0, 47, 7), DARK)
    place(strip, (2, 1, 45, 6), render("ستارت◂شكل", SMALL), LIGHT)
    _sheet_paste(image, strip, range(0x05, 0x0B))
    strip = Image.new("L", (48, 8), WHITE)  # SEL▶CLEAR, $0b-$0f and the cap $10
    _button(strip, (0, 0, 42, 7), DARK)
    select = render("سلكت", SMALL)
    paint(strip, 24, 1, select, LIGHT)
    rest = render("مسح◂", SMALL)
    paint(strip, 22 - width(rest), 1, rest, LIGHT)
    _sheet_paste(image, strip, (0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10))
    fill(image, (8, 8, 15, 15), WHITE)  # $11, the English area hint's "EL": unused
    strip = Image.new("L", (32, 8), WHITE)  # A▶CRY, $12-$15
    _button(strip, (0, 0, 31, 7), DARK)
    place(strip, (2, 1, 29, 6), render("A◂صوت", SMALL), LIGHT)
    _sheet_paste(image, strip, range(0x12, 0x16))
    strip = Image.new("L", (16, 8), WHITE)  # Bio, $18 $19
    place(strip, (0, 1, 15, 6), render("حياة", SMALL), LIGHT)
    _sheet_paste(image, strip, (0x18, 0x19))
    strip = Image.new("L", (24, 8), WHITE)  # Stats, $1a-$1c
    place(strip, (0, 1, 23, 6), render("إحصاء", SMALL), LIGHT)
    _sheet_paste(image, strip, (0x1A, 0x1B, 0x1C))
    fill(image, (104, 8, 111, 15), WHITE)  # H, $1d: the hidden ability (مخفية)
    paint(image, 104, 8, _bold(GLYPHS["khah.if"]), BLACK)


# The regions' names, as the area screen and the Town Map label them.
REGION_NAMES = ("جوتو", "كانتو", "الجزر")


def draw_dex_area(image: Image.Image) -> None:
    """gfx/pokedex/area.png: the "Area Unknown" banner ($34-$3c) and the
    region labels: a cap ($24), then three tiles for each region's name (the
    English shared Johto's and Kanto's last tile): $25-$27, $28-$2a, $2b-$2d."""
    strip = _sheet_strip(image, range(0x34, 0x3D))
    _refill_rows(strip, (0, 0, 71, 7), BLACK)
    place(strip, (2, 1, 69, 6), render("موطن مجهول", SMALL), LIGHT)
    _sheet_paste(image, strip, range(0x34, 0x3D))
    for first, name in zip((0x25, 0x28, 0x2B), REGION_NAMES, strict=True):
        strip = Image.new("L", (24, 8), BLACK)
        place(strip, (0, 1, 21, 6), render(name, SMALL), WHITE, "right")
        _sheet_paste(image, strip, range(first, first + 3))


def _dex_region_maps(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    """The area maps' label rows (row 17, 32-wide maps): Kanto's name ends with
    its own tile, the Islands' label moves a tile right to three name tiles (the
    row's cells share one attribute, so the attrmap stays)."""
    kanto = bytearray(sources["gfx/pokedex/kanto.tilemap"])
    row = 17 * 32
    if kanto[row + 15 : row + 19] != bytes((0x24, 0x28, 0x29, 0x27)):
        raise PristineMismatch("kanto.tilemap: the region label moved")
    kanto[row + 18] = 0x2A
    tiles = bytearray(sources["gfx/pokedex/orange.tilemap"])
    attrs = sources["gfx/pokedex/orange.attrmap"]  # read to check, not written
    if tiles[row + 13 : row + 19] != bytes((0x0A, 0x24, 0x2A, 0x2B, 0x2C, 0x2D)):
        raise PristineMismatch("orange.tilemap: the region label moved")
    if len(set(attrs[row + 13 : row + 19])) != 1:
        raise PristineMismatch("orange.attrmap: the label row's cells differ")
    tiles[row + 13 : row + 19] = bytes((0x0A, 0x0A, 0x24, 0x2B, 0x2C, 0x2D))
    return {
        "gfx/pokedex/kanto.tilemap": bytes(kanto),
        "gfx/pokedex/orange.tilemap": bytes(tiles),
    }


def _dex_area_job(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    out = _dex_region_maps(sources)
    out["gfx/pokedex/area.png"] = _redraw_png(
        "gfx/pokedex/area.png", sources["gfx/pokedex/area.png"], (128, 32), draw_dex_area
    )
    return out


def draw_town_map(image: Image.Image) -> None:
    """gfx/town_map/town_map.png: the Town Map's region label, three tiles each
    (black on white): $37-$39, $3a-$3c, $3d-$3f."""
    for first, name in zip((0x37, 0x3A, 0x3D), REGION_NAMES, strict=True):
        strip = Image.new("L", (24, 8), WHITE)
        place(strip, (0, 1, 22, 6), render(name, SMALL), BLACK, "right")
        _sheet_paste(image, strip, range(first, first + 3))


def _town_map_job(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    """The Town Map's tilemaps (20 wide, row 16): Kanto's label ends with its own
    tile; the Islands' takes three tiles, the first left to the sea."""
    kanto = bytearray(sources["gfx/town_map/kanto.bin"])
    row = 16 * 20
    if kanto[row + 16 : row + 19] != bytes((0x3A, 0x3B, 0x39)):
        raise PristineMismatch("kanto.bin: the region label moved")
    kanto[row + 18] = 0x3C
    orange = bytearray(sources["gfx/town_map/orange.bin"])
    if orange[row + 14 : row + 19] != bytes((0x0A, 0x3C, 0x3D, 0x3E, 0x3F)):
        raise PristineMismatch("orange.bin: the region label moved")
    orange[row + 15] = 0x0A
    return {
        "gfx/town_map/kanto.bin": bytes(kanto),
        "gfx/town_map/orange.bin": bytes(orange),
        "gfx/town_map/town_map.png": _redraw_png(
            "gfx/town_map/town_map.png",
            sources["gfx/town_map/town_map.png"],
            (128, 40),
            draw_town_map,
        ),
    }


def draw_pokegear(image: Image.Image) -> None:
    """gfx/pokegear/pokegear.png: the radio's tuning label ($21-$24)."""
    fill(image, (8, 16, 39, 23), WHITE)
    place(image, (8, 16, 39, 23), render("ضبط", BIG), BLACK)


def draw_pc(image: Image.Image) -> None:
    """gfx/pc/pc.png: the party box's label, over tiles $07-$09 (the top row's
    bottom three lines) and $0a-$0c (the bottom row's top three lines)."""
    top = _sheet_strip(image, (0x07, 0x08, 0x09), columns=17)
    bottom = _sheet_strip(image, (0x0A, 0x0B, 0x0C), columns=17)
    both = Image.new("L", (24, 16), WHITE)
    both.paste(top, (0, 0))
    both.paste(bottom, (0, 8))
    fill(both, (0, 5, 23, 10), DARK)
    place(both, (1, 5, 23, 10), render("فريق", SMALL), BLACK)
    _sheet_paste(image, both.crop((0, 0, 24, 8)), (0x07, 0x08, 0x09), columns=17)
    _sheet_paste(image, both.crop((0, 8, 24, 16)), (0x0A, 0x0B, 0x0C), columns=17)


# --- the Unown puzzle, the link trade, the credits ---


def draw_unown_puzzle(image: Image.Image) -> None:
    """gfx/unown_puzzle/start_cancel.png: "START▶CANCEL" ($0a-$11), white on black."""
    fill(image, (80, 0, 143, 7), BLACK)
    place(image, (80, 0, 143, 7), render("ستارت◀إلغاء", BIG), WHITE)


def draw_trade_border(image: Image.Image) -> None:
    """gfx/trade/border.png: "CABLE TRADE" on the border's top ($17-$1e)."""
    fill(image, (8 * 7, 8, 8 * 15 - 1, 13), LIGHT)
    place(image, (8 * 7, 8, 8 * 15 - 1, 13), render("تبادل بالكابل", SMALL), DARK)


def _scaled(bitmap: Bitmap, factor: int) -> Bitmap:
    return ["".join(cell * factor for cell in row) for row in bitmap for _ in range(factor)]


def draw_the_end(image: Image.Image) -> None:
    """gfx/credits/theend.png: "THE END" (8x2 tiles): the Arabic at twice the
    font's size, black with a light shadow a pixel down and right."""
    fill(image, (0, 0, 63, 15), WHITE)
    word = _scaled(render("النهاية", BIG), 2)
    word = [row[:] for row in word[:15]]  # the font's last row is blank
    x = (63 - width(word)) // 2
    paint(image, x + 1, 1, word, LIGHT)
    paint(image, x, 0, word, BLACK)


PACK_SHA256 = {
    "m0": "5852af4d3562cec0bd31e35afe1d5dd36f229f4eb836bb480c0224c16ff54b15",
    "m1": "098e93a798f192fd4c840b26c0de5fbbd9e73a9371a53f7243a8b72bbc6af525",
    "m2": "0e06b870a1b733886da406ac70c1ffe1ecb5bd87bdedc930556af5aab2bc3058",
    "m3": "8a6adef8d8fac7767c1dfc26aa046f02f43a6d52399d97b376d4b3a68ce88d76",
    "m4": "72241fda370fa528cd89af1f9eec60e1d21e358882e0307e10d59782dfb1b9ad",
    "m5": "09591d1bfd98c2fc66a79ac555555cf0694ea4f3535f1e25ec46f52aaa9ca4c6",
    "f0": "58dd7afee440cb6f6b4fc4646c4ff74b8133ec416192ff7e8628df90f54c34de",
    "f1": "5d6f14938cd83795ff88b796c7826b4e0fee7b794abdfb750ae5f5eb8c727fe4",
    "f2": "1999a256bd8a2d05628ee3489ee0f68ecf98be4eeea78b2e7095fb109cdb7b78",
    "f3": "ce6ee6427f5da4ef3673970b58d483c9aba05aba7b917ff35a589c0505302523",
    "f4": "ac53eaea5dda81ae1d29b739046377e687bce9e70a37639888dc4d834dbaf4c8",
    "f5": "9480a50e2d22aee0266b10a80c011cee96c1995f462e5665b7b5ce7733ffaf34",
    "x0": "441dcf868957503fddd8cbfb3e0a89ccaf08a2663f26407e18f5c1041bc0385e",
    "x1": "50aa624ca482056c4ac9cbbd4f2244431937809087f5210b30a784e48cdc3350",
    "x2": "7336f1edbaf138891ec8f6021bd4cbcbce1eaadce59d07265cd9113c6f1c71d0",
    "x3": "d577dfe8bb9cf9bd2745a23ca519c04dc78175eabf37dc4ff4c1550405fffb43",
    "x4": "8554123b0d18d4320856bcf96d2d61bbdc92b0a0c243f2c221692cbe6d5a58d3",
    "x5": "076a9151fec404a68f57859b201c6325eee8071e67f88c87d4b214a60b7871e0",
}

GRAPHICS: tuple[Graphic, ...] = (
    Graphic(
        "gfx/battle/types.png",
        (32, 160),
        "2521e4b894f4279374b583167799c93d09ec89083ae54604aae67a72b5f94fcf",
        draw_type_badges,
    ),
    Graphic(
        "gfx/stats/status.png",
        (16, 64),
        "113e9daa7dec1b8f79911c1777028b90cc40972f5658f52475b82f9c0cb90c7a",
        draw_status_badges,
    ),
    Graphic(
        "gfx/battle/status.png",
        (16, 64),
        "b6aa06db5aee97ae7da16f12690a4016f075ece2864b563ea3d14af1d3f20640",
        draw_status_badges,
    ),
    Graphic(
        "gfx/battle/status-enemy.png",
        (16, 64),
        "da847fce799ba4a9edcf5c9802d9c801ccee5dcef87f99c753cdf3f9663bd2e3",
        draw_status_badges,
    ),
    Graphic(
        "gfx/stats/summary_sprites.png",
        (32, 80),
        "64a0d39b16f4c57564b1b752c3a296d8d294ba8544c86b8d66cbac54be7695e9",
        draw_summary_sprites,
    ),
    Graphic(
        "gfx/stats/summary.png",
        (144, 8),
        "af6546f46fc4c4984e7b1a3f5bd23098d05c19fd3baebbcaf5e1800096aaa52c",
        draw_summary_tiles,
    ),
    Graphic(
        "gfx/pack/pack_top.png",
        (160, 8),
        "0e3d9601e3dc90112ff66ca38c9490a56b9f05cbecd80052f91de37bfbf82835",
        draw_pack_tabs,
    ),
    *(
        Graphic(f"gfx/pack/pack_{key}.png", (40, 40), digest, _pack_caption(int(key[1])))
        for key, digest in PACK_SHA256.items()
    ),
    Graphic(
        "gfx/trainer_card/status.png",
        (32, 8),
        "70423b3c86d2dca0266106a1c0e878981a1d092664708c7ab82b52d66f4be0d7",
        _card_header("الحالة"),
    ),
    Graphic(
        "gfx/trainer_card/badges.png",
        (32, 8),
        "9268c084a44190fd1901c79e954c82d01dfc044ad0c94f3a3a6d12d9fdd2b9de",
        _card_header("الشارات"),
    ),
    Graphic(
        "gfx/trainer_card/divider.png",
        (48, 8),
        "3e2ac4de7afee28fda3e09af172dabed8a9a604ea824ceb275e6d2f9cb46f7cc",
        draw_card_divider,
    ),
    Graphic(
        "gfx/music_player/bg.png",
        (128, 40),
        "53a9353827493182a0f3e1482baf96c2e2828a14d8908e9698a5998dfd1c93b4",
        draw_music_player,
    ),
    Graphic(
        "gfx/pokedex/pokedex0.png",
        (128, 32),
        "25e73c998a24cc5bf634b5cf80b0865c807aeba859186bccabf85a8877e95ef3",
        draw_dex_bg0,
    ),
    Graphic(
        "gfx/pokedex/pokedex1.png",
        (128, 32),
        "c6c317daa289373a0ed630558f4d657f4f69672a4fce89d8579266c1e22cbcd0",
        draw_dex_bg1,
    ),
    Graphic(
        "gfx/pokedex/oam.png",
        (128, 16),
        "0465e9fcecc6d1df410c67537f7ca8620ec61d44b259fc35d742b912e77c7e84",
        draw_dex_sprites,
    ),
    Graphic(
        "gfx/pokegear/pokegear.png",
        (128, 24),
        "419d43261883c14f8f3e8e0c1114e7aebcce9be4fcb8b7ddb9698d97ced2a652",
        draw_pokegear,
    ),
    Graphic(
        "gfx/pc/pc.png",
        (136, 8),
        "3808ab811d40f40178b8842addac65e3e69876bd852f968d9ed8a2c419a4693b",
        draw_pc,
    ),
    Graphic(
        "gfx/unown_puzzle/start_cancel.png",
        (152, 8),
        "0ae7034d5c12ba7e31c9436a79429a26c83d5f566b3bcabbbd6c5cabf77c0df6",
        draw_unown_puzzle,
    ),
    Graphic(
        "gfx/trade/border.png",
        (128, 16),
        "d231f886a6fca27275831c3f0d18fee847731c3fb00a75387665c0feaac24109",
        draw_trade_border,
    ),
    Graphic(
        "gfx/credits/theend.png",
        (64, 16),
        "bd47c9ddf4b269b7efb0ac28ef267d6c3c297b73fc64ba6a7f7ae045f3ec70da",
        draw_the_end,
    ),
    Graphic(
        "gfx/new_game/init_bg.png",
        (120, 8),
        "6ef8ac2c7759523545524dbd1d17227fcd6e5803c7a057d5278251f4623ca6d7",
        draw_init_footer,
    ),
)


@dataclass(frozen=True, slots=True)
class Job:
    """Files rewritten together (a graphic and the tilemap that places its tiles)."""

    name: str
    sources: Mapping[str, str]  # path -> SHA-256 of the pristine file
    build: Callable[[Mapping[str, bytes]], dict[str, bytes]]
    writes: tuple[str, ...]  # the sources it rewrites


def _music_tilemap_job(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    path = "gfx/music_player/music_player.tilemap"
    return {path: draw_music_tilemap(sources[path])}


JOBS: tuple[Job, ...] = (
    Job(
        "Pokedex area screen",
        {
            "gfx/pokedex/area.png": "86409a8f7d69c92fca183ae98072eb7c5b5804a75c8061e3b8688a705501589e",
            "gfx/pokedex/kanto.tilemap": "f318aa897219ea485f0c95ddfa20f7c048ad07dc3a96c38b86f341e7f5dbaa21",
            "gfx/pokedex/orange.tilemap": "5be81f2a6f5d49c87ccead3aa36e66a1f41bb7e4db0ef69dc13bd958343695a7",
            "gfx/pokedex/orange.attrmap": "60554ca49f234580eb2a18135d5f04791bc5bbb38adeee5acb285f0f782d4204",
        },
        _dex_area_job,
        ("gfx/pokedex/area.png", "gfx/pokedex/kanto.tilemap", "gfx/pokedex/orange.tilemap"),
    ),
    Job(
        "Town Map",
        {
            "gfx/town_map/town_map.png": "c69f1ff90be86d62cd612639376cdaf6538243bbd47c602f0b321f70da3406e9",
            "gfx/town_map/kanto.bin": "1c4bfafed4304d14048ad22229b2e885f3d40f519a731a35f774f80fadca9e22",
            "gfx/town_map/orange.bin": "696680543d5761e1fab96c1778d71d3230a81725a507433c9311d37f2d956dbf",
        },
        _town_map_job,
        ("gfx/town_map/town_map.png", "gfx/town_map/kanto.bin", "gfx/town_map/orange.bin"),
    ),
    Job(
        "type chart",
        {
            "gfx/type_chart/bg.png": "01cbc86792ee940ef720eeef5514c13aa18d3258d9379c1f81e8e8469a7005a0",
            "gfx/type_chart/ob.png": "0cb6272eba52e1b7eaaf3cd6749a7558a76b3005417fbaae7ef037b4d348bf9f",
            "gfx/type_chart/type_chart.tilemap": "a8c253787518fecf236b9aa1c082ffa2486c47c049db39b1d9f8c6c2b2140f8b",
            "gfx/type_chart/type_chart.attrmap": "7fa282db68a9db18b3cacb0773de49890fbfeaf980ba62bd130d48f46407d77d",
        },
        _type_chart_job,
        (
            "gfx/type_chart/bg.png",
            "gfx/type_chart/ob.png",
            "gfx/type_chart/type_chart.tilemap",
            "gfx/type_chart/type_chart.attrmap",
        ),
    ),
    Job(
        "music player tilemap",
        {
            "gfx/music_player/music_player.tilemap": "97e4084d68a49381e0411cdab39fcd5b0c6e806c850cca423ac2be4d08ef907f"
        },
        _music_tilemap_job,
        ("gfx/music_player/music_player.tilemap",),
    ),
)


# --- writing --------------------------------------------------------------------------


class PristineMismatch(ValueError):
    """A graphic is not the pinned original the lettering is drawn over."""


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def redraw(graphic: Graphic, data: bytes) -> bytes:
    """The graphic's PNG bytes with the Arabic lettering, from its pristine bytes."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != graphic.sha256:
        raise PristineMismatch(f"{graphic.path}: not the pristine file (sha256 {digest})")
    with Image.open(io.BytesIO(data)) as original:
        original.load()
        if original.size != graphic.size:
            raise PristineMismatch(f"{graphic.path}: size {original.size}, not {graphic.size}")
        image = original.copy()
    mode = image.mode
    graphic.draw(image)
    if image.mode != mode or image.size != graphic.size:
        raise ValueError(f"{graphic.path}: drawing changed the mode or size")
    return _png_bytes(image)


def _redraw_png(
    path: str, data: bytes, size: tuple[int, int], draw: Callable[[Image.Image], None]
) -> bytes:
    """A PNG redrawn inside a job (its bytes already checked against the pin)."""
    with Image.open(io.BytesIO(data)) as original:
        original.load()
        if original.size != size:
            raise PristineMismatch(f"{path}: size {original.size}, not {size}")
        image = original.copy()
    mode = image.mode
    draw(image)
    if image.mode != mode or image.size != size:
        raise ValueError(f"{path}: drawing changed the mode or size")
    return _png_bytes(image)


def _check(path: str, data: bytes, sha256: str) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise PristineMismatch(f"{path}: not the pristine file (sha256 {digest})")


def outputs(read: Callable[[str], bytes]) -> dict[str, bytes]:
    """Every file the lettering rewrites (path -> bytes); ``read(path)`` gives a pristine file."""
    out: dict[str, bytes] = {}
    for graphic in GRAPHICS:
        out[graphic.path] = redraw(graphic, read(graphic.path))
    for job in JOBS:
        sources = {}
        for path, sha256 in job.sources.items():
            data = read(path)
            _check(path, data, sha256)
            sources[path] = data
        written = job.build(sources)
        if set(written) != set(job.writes) or set(written) & set(out):
            raise ValueError(f"job {job.name}: writes files it does not own")
        out.update(written)
    return out


def apply(tree: Path) -> list[str]:
    """Redraw the graphics of a checkout in place; the paths rewritten.

    Everything is computed (and every original checked) before a file is written.
    """
    tree = Path(tree)
    written = outputs(lambda path: (tree / path).read_bytes())
    for path, data in written.items():
        (tree / path).write_bytes(data)
    return sorted(written)


def paths() -> list[str]:
    """The files ``outputs`` writes."""
    out = {graphic.path for graphic in GRAPHICS}
    for job in JOBS:
        out |= set(job.writes)
    return sorted(out)


def pristine_sha256() -> dict[str, str]:
    """Path -> SHA-256 of every pristine file ``outputs`` reads."""
    out = {graphic.path: graphic.sha256 for graphic in GRAPHICS}
    for job in JOBS:
        out.update(job.sources)
    return dict(sorted(out.items()))


if __name__ == "__main__":
    import sys

    for path in apply(Path(sys.argv[1])):
        print(path)
