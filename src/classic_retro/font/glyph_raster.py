"""Contextual Arabic forms drawn as game glyphs.

Every glyph-font target does the same work before its own pixel format takes
over. It takes each presentation form's outline from the user's font
(``font.arabic_outline``) and draws it at the largest size that fits the game's
cell. It keeps the pixels above a coverage threshold as ink, moves the glyph to
its first ink column, and gives it an advance that makes joined letters touch.
This module holds those steps. Each engine keeps its cell size, baseline,
limits, shadow and byte layout.

The advance rule:

- A form that joins the glyph painted before it (medial, final) ends at its last
  ink column, so the stroke meets its neighbour on the right.
- Any other glyph keeps the widest of the font's advance, its ink box and its
  ink. An isolated form whose ink fills that width gets one more pixel, so it
  never touches the next word's letter.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TypeVar

from PIL import Image, ImageDraw, ImageFont

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.arabic_outline import joins_left_neighbour, joins_right_neighbour

# Coverage (0-255) from which a pixel is ink, in every glyph-font target so far.
INK_THRESHOLD = 96

Pixel = tuple[int, int]
_Fit = TypeVar("_Fit")


class FormDoesNotFit(Exception):
    """A form is too wide or too tall for the cell at the size being tried."""


def arabic_font_file(path: Path) -> Path:
    """The user's Arabic font, which must exist."""
    path = path.expanduser()
    if not path.is_file():
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, f"Arabic font file not found: {path}")
    return path


def sized_font(font_data: bytes, size: int) -> ImageFont.FreeTypeFont:
    """The font at ``size``, with Pillow's basic layout.

    HarfBuzz has already chosen each form (``contextual_font_data``); the basic
    layout draws it without a second shaping pass, and needs no libraqm.
    """
    return ImageFont.truetype(BytesIO(font_data), size=size, layout_engine=ImageFont.Layout.BASIC)


def largest_fitting_size(
    font_data: bytes,
    sizes: Iterable[int],
    fits: Callable[[ImageFont.FreeTypeFont], _Fit | None],
    failure: str,
) -> tuple[ImageFont.FreeTypeFont, int, _Fit]:
    """The first of ``sizes`` (largest first) where ``fits`` gives a result, not None."""
    for size in sizes:
        font = sized_font(font_data, size)
        result = fits(font)
        if result is not None:
            return font, size, result
    raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, failure)


@dataclass(frozen=True, slots=True)
class FormBounds:
    """The forms at one size, measured from the baseline and each form's origin."""

    # Highest and lowest ink rows (negative above the baseline).
    top: int
    bottom: int
    # The widest ink box, and the widest of each form's advance and ink box.
    widest_ink: int
    widest_advance: int


def form_bounds(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> FormBounds:
    boxes = [font.getbbox(character, anchor="ls") for character in characters]
    return FormBounds(
        top=min(box[1] for box in boxes),
        bottom=max(box[3] for box in boxes),
        widest_ink=max(box[2] - box[0] for box in boxes),
        widest_advance=max(
            max(math.ceil(font.getlength(character)), box[2] - box[0])
            for character, box in zip(characters, boxes, strict=True)
        ),
    )


@dataclass(frozen=True, slots=True)
class DrawnForm:
    """A form drawn at one size.

    Pixels count from the form's first ink column and from the cell's top row,
    so rows outside the cell show that the form does not fit.
    """

    ink: frozenset[Pixel]
    # Pixels below the ink level but at or above the soft level, when one is asked.
    soft: frozenset[Pixel]
    advance: int

    @property
    def ink_right(self) -> int:
        return max(x for x, _ in self.ink)


def draw_form(
    font: ImageFont.FreeTypeFont,
    character: str,
    baseline: int,
    *,
    ink_level: int = INK_THRESHOLD,
    soft_level: int | None = None,
    mark_level: int | None = None,
) -> DrawnForm:
    """``character`` drawn on the cell's ``baseline`` row, with the shared advance rule.

    With ``mark_level``, a mark whose coverage stays under the ink level (a dot
    that falls between pixels) keeps its strongest pixel as ink (``kept_marks``).
    """
    left, top, right, bottom = font.getbbox(character, anchor="ls")
    pad = 2
    canvas = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), 0)
    origin_x, origin_y = pad - left, pad - top
    ImageDraw.Draw(canvas).text((origin_x, origin_y), character, font=font, fill=255, anchor="ls")
    pixels = canvas.load()
    lowest = min(level for level in (ink_level, soft_level, mark_level) if level is not None)
    coverage = {
        (x, y): pixels[x, y]
        for y in range(canvas.height)
        for x in range(canvas.width)
        if pixels[x, y] >= lowest
    }
    ink_pixels = [pixel for pixel, level in coverage.items() if level >= ink_level]
    if mark_level is not None:
        ink_pixels += kept_marks(coverage, ink_level, mark_level)
    if soft_level is None:
        coverage = {pixel: level for pixel, level in coverage.items() if level >= ink_level}
    if not ink_pixels:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Selected font produced an empty glyph for U+{ord(character):04X}",
        )
    ink_left = min(x for x, _ in ink_pixels)
    shift_y = baseline - origin_y
    ink = frozenset((x - ink_left, y + shift_y) for x, y in ink_pixels)
    soft = (
        frozenset(
            (x - ink_left, y + shift_y)
            for (x, y), level in coverage.items()
            if level < ink_level and x >= ink_left
        )
        - ink
    )
    ink_right = max(x for x, _ in ink)
    return DrawnForm(ink, soft, contextual_advance(font, character, ink_right, right - left))


def kept_marks(coverage: dict[Pixel, int], ink_level: int, mark_level: int) -> list[Pixel]:
    """The strongest pixel of every mark that never reaches ``ink_level``.

    A mark is a group of touching pixels (by side or corner) of at least
    ``mark_level`` coverage. At a small size a dot can fall between pixels
    and stay just under the ink level everywhere; it would vanish.
    """
    left = {pixel for pixel, level in coverage.items() if level >= mark_level}
    kept: list[Pixel] = []
    while left:
        stack = [left.pop()]
        mark = set(stack)
        while stack:
            x, y = stack.pop()
            for neighbour in ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if neighbour in left:
                    left.remove(neighbour)
                    mark.add(neighbour)
                    stack.append(neighbour)
        if all(coverage[pixel] < ink_level for pixel in mark):
            kept.append(max(sorted(mark), key=lambda pixel: coverage[pixel]))
    return kept


def contextual_advance(
    font: ImageFont.FreeTypeFont, character: str, ink_right: int, box_width: int
) -> int:
    """The advance of a form whose ink ends at column ``ink_right`` (see the module notes)."""
    if joins_right_neighbour(character):
        return ink_right + 1
    advance = max(math.ceil(font.getlength(character)), box_width, ink_right + 1)
    if not joins_left_neighbour(character) and advance == ink_right + 1:
        advance += 1
    return advance


def pattern_pixels(rows: Sequence[str], left: int = 0, top: int = 0) -> set[Pixel]:
    """The ``#`` pixels of a drawn pattern, one string per row."""
    return {
        (left + x, top + y)
        for y, row in enumerate(rows)
        for x, mark in enumerate(row)
        if mark == "#"
    }


def drawn_mark(rows: Sequence[str], baseline: int) -> tuple[set[Pixel], int]:
    """A small glyph drawn by hand, ending on the baseline, with a free column after it."""
    return pattern_pixels(rows, top=baseline - len(rows)), len(rows[0]) + 1


def alef_with_mark(
    character: str, alef: DrawnForm, mark: Sequence[str], shift: int = 0
) -> DrawnForm:
    """An alef form cut one row below ``mark``, with the mark drawn above its stroke.

    At game sizes a font's hamza or madda over alef can reach above the cell or
    touch the letter. This draws the alef below the mark's rows and the mark from
    the alef's stroke (moved by ``shift``) on the top rows.
    """
    stroke = min(x for x, _ in alef.ink)
    marked = pattern_pixels(mark, left=stroke + shift)
    ink = {(x, y) for x, y in alef.ink if y > len(mark)}
    if not ink:
        raise FormDoesNotFit
    ink |= marked
    soft = {(x, y) for x, y in alef.soft if y > len(mark)} - marked
    left = min(x for x, _ in ink | soft)
    ink = {(x - left, y) for x, y in ink}
    soft = {(x - left, y) for x, y in soft}
    right = max(x for x, _ in ink)
    if joins_right_neighbour(character):
        advance = right + 1
    else:
        advance = max(alef.advance - left, right + 2)
    return DrawnForm(frozenset(ink), frozenset(soft), advance)


def raised_form(character: str, form: DrawnForm, *, height: int, baseline: int) -> DrawnForm:
    """One row up when the form reaches below a cell ``height`` rows tall.

    Only the dots or tail of a few forms (final and isolated yeh) go that low.
    A form that joins the glyph on its right keeps a pixel on the joining row,
    just above ``baseline``, at its right edge.
    """
    if max(y for _, y in form.ink | form.soft) < height:
        return form
    ink = {(x, y - 1) for x, y in form.ink}
    soft = {(x, y - 1) for x, y in form.soft}
    if joins_right_neighbour(character):
        join = (form.advance - 1, baseline - 1)
        ink.add(join)
        soft.discard(join)
    return DrawnForm(frozenset(ink), frozenset(soft), form.advance)


def drop_shadow(
    ink: Collection[Pixel], offsets: Iterable[Pixel], width: int, height: int
) -> set[Pixel]:
    """The shadow pixels ``offsets`` away from the ink, inside ``width`` x ``height``.

    Glyph shadows stay inside the glyph's own advance: the neighbour on the right
    is painted first and must keep its joining stroke.
    """
    offsets = tuple(offsets)
    return {
        (x + dx, y + dy) for x, y in ink for dx, dy in offsets if x + dx < width and y + dy < height
    } - set(ink)


def two_bit_rows(
    ink: Collection[Pixel],
    shadow: Collection[Pixel],
    *,
    columns: int,
    height: int,
    ink_value: int,
    shadow_value: int,
) -> tuple[int, ...]:
    """Rows of 2-bit pixels, pixel ``x`` at bits ``2x``..``2x+1``: ink over shadow."""
    rows = []
    for y in range(height):
        value = 0
        for x in range(columns):
            if (x, y) in ink:
                value |= ink_value << 2 * x
            elif (x, y) in shadow:
                value |= shadow_value << 2 * x
        rows.append(value)
    return tuple(rows)
