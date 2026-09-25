"""Review images that every target draws the same way.

A glyph atlas shows a generated font, sixteen cells a row. A message's boxes
stand side by side, the first on the right like the text. A preview sheet
stacks a target's previews, each with its key on the left. The colours and
contents stay with each engine; the layout is shared.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PIL import Image, ImageDraw

RGB = tuple[int, int, int]


def glyph_atlas(
    count: int,
    cell_width: int,
    cell_height: int,
    colour: Callable[[int, int, int], RGB],
    *,
    columns: int = 16,
    background: RGB = (40, 40, 40),
) -> Image.Image:
    """``count`` glyph cells, ``columns`` a row, one pixel apart.

    ``colour(index, x, y)`` gives the colour of pixel (x, y) of glyph ``index``.
    """
    step_x, step_y = cell_width + 2, cell_height + 2
    atlas = Image.new("RGB", (columns * step_x, math.ceil(count / columns) * step_y), background)
    for index in range(count):
        origin_x = (index % columns) * step_x + 1
        origin_y = (index // columns) * step_y + 1
        for y in range(cell_height):
            for x in range(cell_width):
                atlas.putpixel((origin_x + x, origin_y + y), colour(index, x, y))
    return atlas


def pages_right_to_left(pages: Sequence[Image.Image]) -> Image.Image:
    """Boxes of one size side by side, four pixels apart, the first on the right."""
    width, height = pages[0].size
    image = Image.new("RGB", (len(pages) * (width + 4) - 4, height), (0, 0, 0))
    for number, page in enumerate(reversed(pages)):
        image.paste(page, (number * (width + 4), 0))
    return image


def preview_sheet(images: Sequence[tuple[str, Image.Image]], label_width: int) -> Image.Image:
    """Previews one under another, each with its key on the left and itself on the right."""
    width = label_width + max(image.width for _, image in images)
    sheet = Image.new("RGB", (width, sum(image.height + 4 for _, image in images)), (12, 12, 12))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for key, image in images:
        draw.text((2, y + 2), key, fill=(200, 200, 120))
        sheet.paste(image, (width - image.width, y))
        y += image.height + 4
    return sheet


def enlarged_preview_sheet(
    images: Sequence[tuple[str, Image.Image]], label_width: int
) -> Image.Image:
    """Previews one under another at twice their size, each with its key on the left."""
    width = label_width + 2 * max(image.width for _, image in images)
    height = sum(2 * image.height + 6 for _, image in images)
    sheet = Image.new("RGB", (width, height), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for key, image in images:
        draw.text((4, y + 4), key, fill=(220, 220, 140))
        sheet.paste(
            image.resize((image.width * 2, image.height * 2), Image.NEAREST), (label_width, y)
        )
        y += 2 * image.height + 6
    return sheet
