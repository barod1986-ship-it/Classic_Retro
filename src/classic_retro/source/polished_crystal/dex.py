"""The Pokédex's labels, which the game draws from tilemaps rather than strings.

``gfx/pokedex/*.tilemap`` are 32x19 background maps the Pokédex copies to the
screen as they are, labels included. The overlay clears each label's cells and
writes the Arabic label from the translation into them in visual order
(``forms.visual_codes``): the glyph the line ends with first, runs of digits
left to right. Only font cells change (a code from ``$7f`` in VRAM bank 0, by the
tilemap's attribute map), never artwork.

Each label is a translation entry of its own (``gfx/pokedex/<map>:<name>``),
which the shipped translation must have: the engine prints the counters and
values where the Arabic layout puts them. The English cells are pinned through
the tilemap files' blobs, so no English is needed to find them. A few cells hold
no Arabic but a placeholder the engine prints over (``??.?``); those are layout,
written by the overlay itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen2_arabic.forms import visual_codes

WIDTH = 32
SPACE = 0x7F
BANK_BIT = 0x08
# The characters a label may hold besides the Arabic letters.
SYMBOLS = {" ": SPACE, ".": 0x9C, ",": 0x9D, "?": 0x9E, "!": 0x9F, "-": 0xBC, ":": 0xBD, "/": 0xDC}
SYMBOLS.update({str(digit): 0xE0 + digit for digit in range(10)})
MAPS = ("main", "mode", "search", "bio", "description", "stats", "unown")


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a text goes: cells ``first``..``last`` of the row, aligned right or left."""

    text_id: str | None  # a translation entry, or None for ``fixed``
    first: int
    last: int
    align: str
    fixed: str | None = None

    @property
    def cells(self) -> int:
        return self.last - self.first + 1


@dataclass(frozen=True, slots=True)
class Label:
    """One English label's cells, cleared, and what the Arabic layout writes there."""

    tilemap: str
    row: int
    clear_first: int
    clear_last: int
    placements: tuple[Placement, ...]


def _put(text_id: str, first: int, last: int, align: str = "right") -> Placement:
    return Placement(f"gfx/pokedex/{text_id}", first, last, align)


def _fixed(text: str, first: int, last: int, align: str) -> Placement:
    return Placement(None, first, last, align, text)


LABELS: tuple[Label, ...] = (
    # main: the two counters change places (the engine prints Seen at x=17, Own at x=11)
    Label("main", 6, 9, 19, (_put("main:seen", 15, 19), _put("main:owned", 9, 13))),
    # mode menu: the title right-aligned in the title bar, the items next to the cursor
    Label("mode", 2, 1, 4, (_put("mode:title", 1, 18),)),
    Label("mode", 4, 2, 11, (_put("mode:regional", 2, 11, "left"),)),
    Label("mode", 6, 2, 14, (_put("mode:national", 2, 18, "left"),)),
    Label("mode", 10, 2, 7, (_put("mode:cancel", 2, 7, "left"),)),
    # search menu: labels next to the cursor; the values below them start at x=7
    Label("search", 1, 1, 6, (_put("search:title", 1, 18),)),
    Label("search", 3, 2, 7, (_put("search:order", 2, 18, "left"),)),
    Label("search", 4, 7, 15, (_put("search:order_value", 7, 15, "left"),)),
    Label("search", 5, 2, 7, (_put("search:type1", 2, 18, "left"),)),
    Label("search", 7, 2, 7, (_put("search:type2", 2, 18, "left"),)),
    Label("search", 9, 2, 8, (_put("search:group1", 2, 18, "left"),)),
    Label("search", 11, 2, 8, (_put("search:group2", 2, 18, "left"),)),
    Label("search", 13, 2, 7, (_put("search:color", 2, 18, "left"),)),
    Label("search", 15, 2, 6, (_put("search:body", 2, 7, "left"),)),
    Label("search", 17, 2, 7, (_put("search:start", 2, 18, "left"),)),
    # bio: labels right-aligned in the label column x=1..6 (the values start at x=8)
    Label("bio", 5, 1, 5, (_put("bio:catch_rate", 1, 6),)),
    Label("bio", 7, 1, 4, (_put("bio:exp", 1, 6),)),
    Label("bio", 9, 1, 6, (_put("bio:gender", 1, 6),)),
    Label("bio", 11, 1, 3, (_put("bio:egg_group_1", 1, 6),)),
    Label("bio", 12, 1, 5, (_put("bio:egg_group_2", 1, 6),)),
    Label("bio", 14, 1, 5, (_put("bio:hatch", 1, 6),)),
    Label("bio", 16, 1, 6, (_put("bio:growth", 1, 6),)),
    # description: label | number | unit, right to left (the engine prints the
    # numbers at x=11..15; the units are the metric ones)
    Label(
        "description",
        7,
        9,
        18,
        (
            _put("description:height", 17, 19),
            _fixed("??.?", 12, 15, "left"),
            _put("description:height_unit", 10, 10, "left"),
        ),
    ),
    Label(
        "description",
        9,
        9,
        19,
        (
            _put("description:weight", 17, 19),
            _fixed("??.?", 12, 15, "left"),
            _put("description:weight_unit", 9, 10, "left"),
        ),
    ),
    # stats: two columns, labels right-aligned before the values (x=5, x=15)
    Label("stats", 5, 1, 2, (_put("stats:hp", 1, 4),)),
    Label("stats", 5, 11, 13, (_put("stats:sp_atk", 9, 13),)),
    Label("stats", 7, 1, 3, (_put("stats:atk", 1, 4),)),
    Label("stats", 7, 11, 13, (_put("stats:sp_def", 9, 13),)),
    Label("stats", 9, 1, 3, (_put("stats:def", 1, 4),)),
    Label("stats", 9, 11, 13, (_put("stats:speed", 9, 13),)),
    Label("stats", 11, 1, 8, (_put("stats:ability", 1, 7),)),
    Label("unown", 3, 10, 14, (_put("unown:title", 10, 14),)),
)


def label_entries() -> dict[str, Placement]:
    """Every label entry the translation must have, by id."""
    return {
        placement.text_id: placement
        for label in LABELS
        for placement in label.placements
        if placement.text_id is not None
    }


def check_label(text_id: str, text: str) -> None:
    """A label's Arabic fits its cells and holds only the glyphs a tilemap can show."""
    placement = label_entries()[text_id]
    if "\n" in text or not text.strip():
        raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, f"{text_id}: a label is one line of text")
    try:
        codes = visual_codes(text, SYMBOLS)
    except ValueError as exc:
        raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"{text_id}: {exc}") from exc
    if len(codes) > placement.cells:
        raise ClassicRetroError(
            ErrorCode.TEXT_OVERFLOW,
            f"{text_id}: {len(codes)} cells, the label has {placement.cells}",
        )


def _is_font_cell(tiles: bytes | bytearray, attributes: bytes, index: int) -> bool:
    return tiles[index] >= SPACE and not attributes[index] & BANK_BIT


def apply(
    tilemaps: Mapping[str, tuple[bytes, bytes]], texts: Mapping[str, str]
) -> dict[str, bytes]:
    """The tilemaps (name -> (tilemap, attrmap)) with the Arabic labels written in."""
    out = {name: bytearray(tiles) for name, (tiles, _) in tilemaps.items()}
    for label in LABELS:
        tiles = out[label.tilemap]
        attributes = tilemaps[label.tilemap][1]
        base = label.row * WIDTH
        for x in range(label.clear_first, label.clear_last + 1):
            if not _is_font_cell(tiles, attributes, base + x):
                raise ClassicRetroError(
                    ErrorCode.SOURCE_BASELINE_MISMATCH,
                    f"gfx/pokedex/{label.tilemap}.tilemap: ({x},{label.row}) is no text cell",
                )
            tiles[base + x] = SPACE
        for placement in label.placements:
            text = placement.fixed if placement.text_id is None else texts[placement.text_id]
            assert text is not None
            codes = visual_codes(text, SYMBOLS)
            if len(codes) > placement.cells:
                raise ClassicRetroError(
                    ErrorCode.TEXT_OVERFLOW,
                    f"{placement.text_id}: {len(codes)} cells, the label has {placement.cells}",
                )
            start = (
                placement.last - len(codes) + 1 if placement.align == "right" else placement.first
            )
            for offset, code in enumerate(codes):
                index = base + start + offset
                if not _is_font_cell(tiles, attributes, index):
                    raise ClassicRetroError(
                        ErrorCode.SOURCE_BASELINE_MISMATCH,
                        f"gfx/pokedex/{label.tilemap}.tilemap: ({start + offset},{label.row}) "
                        "is no text cell",
                    )
                tiles[index] = code
    return {name: bytes(tiles) for name, tiles in out.items()}
