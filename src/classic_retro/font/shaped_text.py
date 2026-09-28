"""Render logical Arabic lines into grayscale coverage with HarfBuzz shaping.

Pillow's basic layout cannot shape Arabic, and its Raqm layout depends on
system libraries. Here HarfBuzz (uharfbuzz) shapes each line (contextual
forms, lam-alef and other ligatures, mark and kerning positions) and Pillow
rasterizes every glyph through a private-use cmap added to an in-memory copy
of the font, so the result does not depend on the platform.

HarfBuzz shapes one direction at a time and does not run the bidi algorithm:
a whole line in one right-to-left buffer comes out with its numbers reversed
("2024" reads 4202). So the renderer first cuts the line into directional
runs, the part of UAX #9 a line of Arabic with numbers needs. Digits after
Arabic letters are Arabic numbers (rule W2); a single ``,`` ``.`` ``:`` or
``/`` between two digit groups belongs to the number (rule W4); spaces and
other punctuation between letters and numbers take the line's direction
(rule N1). Each digit run is shaped left to right, every other run right to
left, and the runs are joined in visual order, which for a right-to-left
line is the logical order reversed. A line without digits is one run,
shaped exactly as one buffer.

Fonts without Latin punctuation (Noto Kufi Arabic has none) get simple ``.``,
``!`` and ``:`` outlines sized from the font's alef. The user's font file is
never modified or redistributed.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageChops, ImageDraw, ImageFont

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.glyph_raster import arabic_font_file

PRIVATE_USE_START = 0xE000
PRIVATE_USE_END = 0xF8FF
ALEF = 0x0627
PUNCTUATION = (".", "!", ":")
# HarfBuzz direction names.
LEFT_TO_RIGHT = "ltr"
RIGHT_TO_LEFT = "rtl"
# Common separators (UAX #9 class CS) that join two digit groups into one number.
NUMBER_SEPARATORS = frozenset(",.:/")


@dataclass(frozen=True, slots=True)
class ShapedGlyph:
    """One glyph in visual order: private-use character and pixel positions."""

    character: str
    advance: float
    x_offset: float
    y_offset: float


@dataclass(frozen=True, slots=True)
class TextRun:
    """A stretch of a logical line that HarfBuzz shapes in one direction."""

    text: str
    direction: str


def _is_digit(character: str) -> bool:
    """A decimal digit of any script: ASCII, Arabic-Indic or extended Arabic-Indic."""
    return unicodedata.category(character) == "Nd"


def _number_end(text: str, start: int) -> int:
    """Where the number starting at the digit ``text[start]`` ends.

    A separator counts only between two digits (rule W4): ``1,000`` and
    ``3.5`` are one number, but the full stop of ``2024.`` is not.
    """
    end = start + 1
    while end < len(text):
        if _is_digit(text[end]):
            end += 1
        elif text[end] in NUMBER_SEPARATORS and end + 1 < len(text) and _is_digit(text[end + 1]):
            end += 2
        else:
            break
    return end


def directional_runs(text: str) -> list[TextRun]:
    """The line's runs in logical order: numbers left to right, the rest right to left.

    Everything that is not a number, spaces and punctuation included, stays in
    the right-to-left runs (rule N1): a right-to-left line has no left-to-right
    text besides its numbers. A line without digits is one run.
    """
    runs: list[TextRun] = []
    start = position = 0
    while position < len(text):
        if not _is_digit(text[position]):
            position += 1
            continue
        if start < position:
            runs.append(TextRun(text[start:position], RIGHT_TO_LEFT))
        end = _number_end(text, position)
        runs.append(TextRun(text[position:end], LEFT_TO_RIGHT))
        start = position = end
    if start < len(text):
        runs.append(TextRun(text[start:], RIGHT_TO_LEFT))
    return runs


class ShapedLineRenderer:
    """Right-to-left lines of one font at one pixel size."""

    def __init__(self, font_path: Path, size: int) -> None:
        data = _with_punctuation(arabic_font_file(font_path).read_bytes())
        self.size = size
        face = hb.Face(data)
        self._font = hb.Font(face)
        self._scale = size / face.upem
        self._pil = ImageFont.truetype(
            BytesIO(_private_use_font(data)), size=size, layout_engine=ImageFont.Layout.BASIC
        )

    def shape(self, text: str) -> list[ShapedGlyph]:
        """The line's glyphs in visual order, left to right.

        Each directional run is shaped in its own buffer, whose glyphs HarfBuzz
        gives in visual order whatever the direction; in a right-to-left line
        the runs themselves stand in the logical order reversed.
        """
        glyphs: list[ShapedGlyph] = []
        for run in reversed(directional_runs(text)):
            glyphs.extend(self._shape_run(run, text))
        return glyphs

    def _shape_run(self, run: TextRun, line: str) -> list[ShapedGlyph]:
        buffer = hb.Buffer()
        buffer.add_str(run.text)
        buffer.direction = run.direction
        buffer.script = "Arab"
        buffer.language = "ar"
        hb.shape(self._font, buffer)
        glyphs = []
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            if info.codepoint == 0:
                raise ClassicRetroError(
                    ErrorCode.MISSING_GLYPH,
                    f"The font has no glyph for part of {line!r}",
                )
            glyphs.append(
                ShapedGlyph(
                    chr(PRIVATE_USE_START + info.codepoint),
                    position.x_advance * self._scale,
                    position.x_offset * self._scale,
                    position.y_offset * self._scale,
                )
            )
        return glyphs

    def width(self, text: str) -> float:
        return sum(glyph.advance for glyph in self.shape(text))

    def draw(self, canvas: Image.Image, text: str, x: float, baseline: float) -> None:
        """Draw ``text`` with its visual left edge at ``x`` (coverage, lighter wins)."""
        self.draw_glyphs(canvas, self.shape(text), x, baseline)

    def draw_glyphs(
        self, canvas: Image.Image, glyphs: list[ShapedGlyph], x: float, baseline: float
    ) -> None:
        """Draw shaped glyphs in visual order from ``x`` (coverage, lighter wins)."""
        for glyph in glyphs:
            layer = Image.new("L", canvas.size, 0)
            ImageDraw.Draw(layer).text(
                (x + glyph.x_offset, baseline - glyph.y_offset),
                glyph.character,
                font=self._pil,
                fill=255,
                anchor="ls",
            )
            canvas.paste(ImageChops.lighter(canvas, layer))
            x += glyph.advance


def _open(data: bytes) -> TTFont:
    try:
        return TTFont(BytesIO(data), recalcTimestamp=False)
    except TTLibError as exc:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Invalid TTF/OTF font file") from exc


def _save(font: TTFont) -> bytes:
    output = BytesIO()
    font.save(output)
    return output.getvalue()


def _private_use_font(data: bytes) -> bytes:
    """Map every glyph ID to U+E000 + ID so Pillow can draw glyphs by ID."""
    font = _open(data)
    order = font.getGlyphOrder()
    if PRIVATE_USE_START + len(order) > PRIVATE_USE_END:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "Font has too many glyphs")
    mapping = {PRIVATE_USE_START + index: name for index, name in enumerate(order)}
    for table in font["cmap"].tables:
        if table.isUnicode() and table.format != 14:
            if table.format in (0, 2, 4, 6) and max(mapping) > 0xFFFF:
                continue
            table.cmap.update(mapping)
    return _save(font)


def _with_punctuation(data: bytes) -> bytes:
    """Add ``.``, ``!`` and ``:`` outlines when the font has none."""
    font = _open(data)
    cmap = font.getBestCmap() or {}
    missing = [mark for mark in PUNCTUATION if ord(mark) not in cmap]
    if not missing:
        return data
    if "glyf" not in font or ALEF not in cmap:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            "The font lacks " + " ".join(missing) + "; choose a TrueType font that has them",
        )
    glyph_set = font.getGlyphSet()
    bounds = BoundsPen(glyph_set)
    glyph_set[cmap[ALEF]].draw(bounds)
    if bounds.bounds is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "The font's alef has no outline")
    left, _, right, top = (round(value) for value in bounds.bounds)
    stroke = right - left
    dots = {
        ".": [(0, stroke)],
        "!": [(0, stroke), (2 * stroke, top)],
        ":": [(0, stroke), (top // 2, top // 2 + stroke)],
    }
    order = list(font.getGlyphOrder())
    for mark in missing:
        pen = TTGlyphPen(None)
        for bottom, upper in dots[mark]:
            pen.moveTo((left, bottom))
            pen.lineTo((left, upper))
            pen.lineTo((right, upper))
            pen.lineTo((right, bottom))
            pen.closePath()
        name = f"classic_retro_{ord(mark):04X}"
        order.append(name)
        font["glyf"].glyphs[name] = pen.glyph()
        font["hmtx"].metrics[name] = (2 * left + stroke, left)
        for table in font["cmap"].tables:
            if table.isUnicode() and table.format != 14:
                table.cmap[ord(mark)] = name
    font.setGlyphOrder(order)
    font["glyf"].glyphOrder = order
    if "post" in font:
        font["post"].formatType = 3.0
    return _save(font)
