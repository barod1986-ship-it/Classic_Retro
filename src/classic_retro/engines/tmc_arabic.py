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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import (
    TMC_PLAYER_NAME_LENGTH,
    render_tmc_string,
    token_notation,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    arabic_font_file,
    draw_form,
    form_bounds,
    largest_fitting_size,
)
from classic_retro.font.previews import glyph_atlas
from classic_retro.font.tiles import pack_4bpp, unpack_4bpp
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

_NIBBLE_UNUSED = 0xF
_NIBBLE_BACKGROUND = 0x0
_NIBBLE_INK = 0xE

# Sentence punctuation drawn on the Arabic baseline. Arabic fonts often lack
# these marks, and the game's Latin ones sit on the lower Latin baseline.
# Offsets are (column, rows above the baseline); the advance leaves the gap on
# the right, towards the preceding glyph.
BASELINE_PUNCTUATION: dict[str, tuple[int, tuple[tuple[int, int], ...]]] = {
    ".": (3, ((0, 2), (1, 2), (0, 1), (1, 1))),
    "!": (3, ((0, 8), (0, 7), (0, 6), (0, 5), (0, 4), (0, 2), (0, 1))),
    ":": (3, ((0, 7), (1, 7), (0, 6), (1, 6), (0, 2), (1, 2), (0, 1), (1, 1))),
}


def tmc_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Slots 0..255 of the Arabic font page for ``characters``."""
    return assign_glyph_codes(characters, range(0x100), what="Minish Cap Arabic glyphs")


def glyph_notation(slot: int) -> str:
    """The tmc_strings notation that draws slot ``slot`` of the Arabic font page."""
    return f"{{04:18:{slot:02X}}}"


@lru_cache(maxsize=1)
def build_tmc_arabic_glyph_map() -> GlyphCodes:
    return tmc_glyph_codes(arabic_presentation_repertoire() + tuple(BASELINE_PUNCTUATION))


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
    glyph_map: GlyphCodes | None = None,
) -> TmcArabicFontResult:
    """Rasterize every presentation form into the engine's 16x16 two-half format."""
    glyph_map = glyph_map or build_tmc_arabic_glyph_map()
    outlined = tuple(
        character for character in glyph_map.characters if character not in BASELINE_PUNCTUATION
    )
    font, size, (top, bottom) = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), outlined),
        range(18, 5, -1),
        lambda font: _ink_rows(font, outlined),
        "Selected font cannot fit the Minish Cap 16x15 Arabic glyph area",
    )
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


def _ink_rows(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> tuple[int, int] | None:
    """The forms' top and bottom rows when they fit rows 1..15 and 16 columns, else None."""
    bounds = form_bounds(font, characters)
    rows = GLYPH_CELL_HEIGHT - FIRST_INK_ROW
    if bounds.bottom - bounds.top <= rows and bounds.widest_advance <= GLYPH_CELL_WIDTH:
        return bounds.top, bounds.bottom
    return None


def _rasterize(
    font: ImageFont.FreeTypeFont, character: str, baseline: int
) -> tuple[frozenset[tuple[int, int]], int]:
    form = draw_form(font, character, baseline)
    width = form.advance
    if width > GLYPH_CELL_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {width}px; the Minish Cap cell is 16px",
        )
    outside = [
        (x, y) for x, y in form.ink if x >= width or y < FIRST_INK_ROW or y >= GLYPH_CELL_HEIGHT
    ]
    if outside:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} has pixels outside its {width}x16 cell",
        )
    return form.ink, width


def _encode_glyph(ink: set[tuple[int, int]] | frozenset[tuple[int, int]], width: int) -> bytes:
    """Two 8x16 halves, left then right; columns past the advance hold the unused marker."""
    pixels = [
        [
            _NIBBLE_UNUSED if x >= width else _NIBBLE_INK if (x, y) in ink else _NIBBLE_BACKGROUND
            for x in range(GLYPH_CELL_WIDTH)
        ]
        for y in range(GLYPH_CELL_HEIGHT)
    ]
    return pack_4bpp(pixels, columns=True)


def font_preview(result: TmcArabicFontResult, glyph_map: GlyphCodes) -> Image.Image:
    """Atlas of the generated glyphs: 16 per row, ink white, unused columns dark red."""
    colours = {
        _NIBBLE_UNUSED: (90, 20, 20),
        _NIBBLE_BACKGROUND: (0, 0, 0),
        _NIBBLE_INK: (255, 255, 255),
    }
    glyphs = [
        unpack_4bpp(
            result.data[index * GLYPH_BYTES : (index + 1) * GLYPH_BYTES],
            GLYPH_CELL_WIDTH,
            GLYPH_CELL_HEIGHT,
            columns=True,
        )
        for index in range(result.glyphs)
    ]
    return glyph_atlas(
        result.glyphs,
        GLYPH_CELL_WIDTH,
        GLYPH_CELL_HEIGHT,
        lambda index, x, y: colours.get(glyphs[index][y][x], (0, 0, 255)),
    )


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
        glyph_map: GlyphCodes | None = None,
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
        reject_mirrored(stream, "Minish Cap Arabic v1")
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
            slot = self.glyph_map.code(character)
            if slot is not None:
                parts.append(glyph_notation(slot))
            else:
                parts.append(render_tmc_string(TokenStream((TextToken(character),))))
        return "".join(parts)

    def _character_width(self, character: str) -> int:
        width = self.arabic_widths.get(character)
        if width is None:
            width = self.latin_widths.get(character)
        if width is None:
            raise no_glyph(character, "Minish Cap Arabic")
        return width
