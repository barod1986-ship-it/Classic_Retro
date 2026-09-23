"""Arabic support for The Minish Cap text engine (renderer/font v1).

The source overlay adds a double-width Arabic font page and three render
commands to the decompiled text engine:

- ``04 16``    right-to-left painting on,
- ``04 17``    right-to-left painting off,
- ``04 18 xx`` Arabic presentation-form glyph ``xx`` from font page 9.

The USA script never uses ``04`` sub-codes above ``15``, so existing text keeps
its meaning. Translations stay logical Unicode Arabic; this module shapes them,
resolves bidi per line, and stores them in right-to-left paint order.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.paint import reject_combining_marks, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import (
    TMC_PLAYER_NAME_LENGTH,
    render_tmc_string,
    token_notation,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

TMC_ARABIC_FONT_PAGE = 9
TMC_RENDER_CONTROL = 0x04
TMC_RTL_ON = 0x16
TMC_RTL_OFF = 0x17
TMC_ARABIC_GLYPH = 0x18

RTL_ON_NOTATION = "{04:16}"
RTL_OFF_NOTATION = "{04:17}"

# One Arabic glyph = two 8x16 4bpp halves, as the engine's 16px pages (5..9).
GLYPH_CELL_WIDTH = 16
GLYPH_CELL_HEIGHT = 16
GLYPH_BYTES = 128
# Row 0 is the engine's width marker and stays ink-free as line spacing.
FIRST_INK_ROW = 1
# The Latin font sits on row 13 (its capitals end there).
LATIN_BASELINE = 14
INK_THRESHOLD = 96

_NIBBLE_UNUSED = 0xF
_NIBBLE_BACKGROUND = 0x0
_NIBBLE_INK = 0xE

# Characters whose glyph must be mirrored in right-to-left runs. The game font
# cannot mirror, and the shared bidi step does not apply rule L4.
_MIRRORED = frozenset("()[]{}<>«»‹›")

# Sentence punctuation drawn on the Arabic baseline. Arabic fonts often lack
# these marks, and the game's Latin ones sit on the lower Latin baseline.
# Offsets are (column, rows above the baseline); the advance leaves the gap on
# the right, towards the preceding glyph.
BASELINE_PUNCTUATION: dict[str, tuple[int, tuple[tuple[int, int], ...]]] = {
    ".": (3, ((0, 2), (1, 2), (0, 1), (1, 1))),
    "!": (3, ((0, 8), (0, 7), (0, 6), (0, 5), (0, 4), (0, 2), (0, 1))),
    ":": (3, ((0, 7), (1, 7), (0, 6), (1, 6), (0, 2), (1, 2), (0, 1), (1, 1))),
}


@dataclass(frozen=True, slots=True)
class TmcArabicGlyphMap:
    characters: tuple[str, ...]
    slots: dict[str, int]

    def notation(self, character: str) -> str | None:
        slot = self.slots.get(character)
        if slot is None:
            return None
        return f"{{04:18:{slot:02X}}}"


@lru_cache(maxsize=1)
def build_tmc_arabic_glyph_map() -> TmcArabicGlyphMap:
    characters = arabic_presentation_repertoire() + tuple(BASELINE_PUNCTUATION)
    if len(characters) > 0x100:
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"Arabic glyph set needs {len(characters)} slots; the font page has 256",
        )
    return TmcArabicGlyphMap(
        characters=characters,
        slots={character: index for index, character in enumerate(characters)},
    )


@dataclass(frozen=True, slots=True)
class TmcArabicFontResult:
    glyphs: int
    font_size: int
    baseline: int
    widths: dict[str, int]
    max_advance: int
    data: bytes


def build_tmc_arabic_font(
    font_path: Path,
    *,
    glyph_map: TmcArabicGlyphMap | None = None,
) -> TmcArabicFontResult:
    """Rasterize every presentation form into the engine's 16x16 two-half format."""
    glyph_map = glyph_map or build_tmc_arabic_glyph_map()
    font_path = font_path.expanduser()
    if not font_path.is_file():
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Arabic font file not found: {font_path}",
        )

    outlined = tuple(
        character for character in glyph_map.characters if character not in BASELINE_PUNCTUATION
    )
    font_data = contextual_font_data(font_path, outlined)
    font, size, top, bottom = _choose_font(font_data, outlined)
    # Share the Latin baseline when descenders allow it; otherwise raise the
    # baseline just enough to keep every contextual form inside the cell.
    baseline = min(LATIN_BASELINE, GLYPH_CELL_HEIGHT - bottom)
    baseline = max(baseline, FIRST_INK_ROW - top)

    output = bytearray()
    widths: dict[str, int] = {}
    for character in glyph_map.characters:
        if character in BASELINE_PUNCTUATION:
            width, offsets = BASELINE_PUNCTUATION[character]
            ink = {(x, baseline - above) for x, above in offsets}
        else:
            ink, width = _rasterize(font, character, baseline)
        widths[character] = width
        output.extend(_encode_glyph(ink, width))

    return TmcArabicFontResult(
        glyphs=len(glyph_map.characters),
        font_size=size,
        baseline=baseline,
        widths=widths,
        max_advance=max(widths.values()),
        data=bytes(output),
    )


def _choose_font(
    font_data: bytes, characters: tuple[str, ...]
) -> tuple[ImageFont.FreeTypeFont, int, int, int]:
    rows = GLYPH_CELL_HEIGHT - FIRST_INK_ROW
    for size in range(18, 5, -1):
        font = ImageFont.truetype(
            BytesIO(font_data), size=size, layout_engine=ImageFont.Layout.BASIC
        )
        boxes = [font.getbbox(character, anchor="ls") for character in characters]
        top = min(box[1] for box in boxes)
        bottom = max(box[3] for box in boxes)
        widest = max(
            max(math.ceil(font.getlength(character)), box[2] - box[0])
            for character, box in zip(characters, boxes, strict=True)
        )
        if bottom - top <= rows and widest <= GLYPH_CELL_WIDTH:
            return font, size, top, bottom
    raise ClassicRetroError(
        ErrorCode.FONT_BUILD_FAILED,
        "Selected font cannot fit the Minish Cap 16x15 Arabic glyph area",
    )


def _rasterize(
    font: ImageFont.FreeTypeFont, character: str, baseline: int
) -> tuple[set[tuple[int, int]], int]:
    cell = Image.new("L", (GLYPH_CELL_WIDTH * 2, GLYPH_CELL_HEIGHT), 0)
    draw = ImageDraw.Draw(cell)
    left, _, right, _ = font.getbbox(character, anchor="ls")
    draw.text((-left, baseline), character, font=font, fill=255, anchor="ls")
    pixels = cell.load()
    ink = {
        (x, y)
        for y in range(GLYPH_CELL_HEIGHT)
        for x in range(GLYPH_CELL_WIDTH * 2)
        if pixels[x, y] >= INK_THRESHOLD
    }
    if not ink:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Selected font produced an empty glyph for U+{ord(character):04X}",
        )

    # Glyphs start at their first ink column. A left-joining form must touch
    # the glyph painted after it (to its left) without a side-bearing gap.
    ink_left = min(x for x, _ in ink)
    ink = {(x - ink_left, y) for x, y in ink}
    ink_right = max(x for x, _ in ink)
    if joins_right_neighbour(character):
        # The right edge meets the previous (right-hand) glyph exactly.
        width = ink_right + 1
    else:
        # Non-joining right side: keep the font's advance as the gap to the
        # right-hand neighbour.
        width = max(math.ceil(font.getlength(character)), right - left, ink_right + 1)
        if not joins_left_neighbour(character) and width == ink_right + 1:
            width += 1

    if width > GLYPH_CELL_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {width}px; the Minish Cap cell is 16px",
        )
    outside = [(x, y) for x, y in ink if x >= width or y < FIRST_INK_ROW or y >= GLYPH_CELL_HEIGHT]
    if outside:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} has pixels outside its {width}x16 cell",
        )
    return ink, width


def _encode_glyph(ink: set[tuple[int, int]], width: int) -> bytes:
    output = bytearray()
    for half in range(2):
        for y in range(GLYPH_CELL_HEIGHT):
            row = []
            for column in range(8):
                x = half * 8 + column
                if x >= width:
                    row.append(_NIBBLE_UNUSED)
                elif (x, y) in ink:
                    row.append(_NIBBLE_INK)
                else:
                    row.append(_NIBBLE_BACKGROUND)
            output.extend(row[i] | (row[i + 1] << 4) for i in range(0, 8, 2))
    return bytes(output)


def font_preview(result: TmcArabicFontResult, glyph_map: TmcArabicGlyphMap) -> Image.Image:
    """Atlas of the generated glyphs: 16 per row, ink white, unused columns dark red."""
    rows = math.ceil(result.glyphs / 16)
    atlas = Image.new("RGB", (16 * 18, rows * 18), (40, 40, 40))
    colours = {
        _NIBBLE_UNUSED: (90, 20, 20),
        _NIBBLE_BACKGROUND: (0, 0, 0),
        _NIBBLE_INK: (255, 255, 255),
    }
    for index in range(result.glyphs):
        glyph = result.data[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES]
        origin_x = (index % 16) * 18 + 1
        origin_y = (index // 16) * 18 + 1
        for half in range(2):
            for y in range(GLYPH_CELL_HEIGHT):
                for column in range(8):
                    value = glyph[half * 64 + y * 4 + column // 2]
                    nibble = value & 0xF if column % 2 == 0 else value >> 4
                    atlas.putpixel(
                        (origin_x + half * 8 + column, origin_y + y),
                        colours.get(nibble, (0, 0, 255)),
                    )
    return atlas


@dataclass(frozen=True, slots=True)
class TmcArabicLine:
    width: int
    dynamic: tuple[str, ...]


class TmcArabicEncoder:
    """Convert logical Arabic token streams into tmc_strings notation."""

    def __init__(
        self,
        *,
        arabic_widths: dict[str, int],
        latin_widths: dict[str, int],
        player_width: int | None = None,
        glyph_map: TmcArabicGlyphMap | None = None,
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.glyph_map = glyph_map or build_tmc_arabic_glyph_map()
        self.arabic_widths = dict(arabic_widths)
        self.latin_widths = dict(latin_widths)
        if player_width is None:
            player_width = TMC_PLAYER_NAME_LENGTH * max(self.latin_widths.values())
        self.player_width = player_width

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        reject_combining_marks(stream, "Minish Cap Arabic font v1")
        mirrored = sorted(
            {
                character
                for token in stream.tokens
                if isinstance(token, TextToken)
                for character in token.text
                if character in _MIRRORED
            }
        )
        if mirrored:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT,
                "Minish Cap Arabic v1 cannot mirror bracket glyphs: " + "".join(mirrored),
            )
        return rtl_paint_order(self.pipeline, stream)

    def line_widths(self, stream: TokenStream) -> tuple[TmcArabicLine, ...]:
        """Pixel width of every rendered line, with runtime variables at their maximum."""
        lines: list[TmcArabicLine] = []
        width = 0
        dynamic: list[str] = []
        for token in self.prepare_paint_order(stream).tokens:
            if isinstance(token, TextToken):
                width += sum(self._character_width(character) for character in token.text)
                continue
            if token.kind is TokenKind.LINE_BREAK:
                lines.append(TmcArabicLine(width, tuple(dynamic)))
                width = 0
                dynamic = []
                continue
            if token.kind is TokenKind.VARIABLE:
                if token.name != "PLAYER":
                    raise ClassicRetroError(
                        ErrorCode.INLINE_WIDTH_UNKNOWN,
                        f"No width bound for Minish Cap variable {token.name}",
                    )
                width += self.player_width
                dynamic.append(token.name)
                continue
            if token.name in {"KEY_ICON", "SYMBOL"}:
                raise ClassicRetroError(
                    ErrorCode.INLINE_WIDTH_UNKNOWN,
                    f"Minish Cap Arabic v1 does not measure {token.name} glyphs yet",
                )
        lines.append(TmcArabicLine(width, tuple(dynamic)))
        return tuple(lines)

    def encode_message(self, stream: TokenStream, *, line_width: int | None = None) -> str:
        if line_width is not None:
            for number, line in enumerate(self.line_widths(stream), start=1):
                if line.width > line_width:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"Line {number} needs {line.width}px; the Minish Cap box has {line_width}px",
                    )

        parts = [RTL_ON_NOTATION]
        for token in self.prepare_paint_order(stream).tokens:
            if isinstance(token, TextToken):
                parts.append(self._encode_text(token.text))
                continue
            if isinstance(token, InlineToken) and token.name == "CONTINUE_TEXT":
                # The continued text starts its own direction state.
                parts.append(RTL_OFF_NOTATION)
            parts.append(token_notation(token))
        parts.append(RTL_OFF_NOTATION)
        return "".join(parts)

    def _encode_text(self, text: str) -> str:
        parts = []
        for character in text:
            notation = self.glyph_map.notation(character)
            if notation is not None:
                parts.append(notation)
            else:
                parts.append(render_tmc_string(TokenStream((TextToken(character),))))
        return "".join(parts)

    def _character_width(self, character: str) -> int:
        width = self.arabic_widths.get(character)
        if width is None:
            width = self.latin_widths.get(character)
        if width is None:
            if unicodedata.category(character).startswith("L") and "ARABIC" in unicodedata.name(
                character, ""
            ):
                raise ClassicRetroError(
                    ErrorCode.MISSING_GLYPH,
                    f"No Minish Cap Arabic glyph for U+{ord(character):04X}",
                )
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT,
                f"Minish Cap text has no glyph for {character!r}",
            )
        return width
