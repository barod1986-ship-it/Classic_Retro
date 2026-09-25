from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.paint import reject_combining_marks, rtl_paint_order
from classic_retro.arabic.repertoire import (
    ARABIC_STATIC_CHARACTERS,
    STANDARD_ARABIC_LETTERS,
    arabic_presentation_repertoire,
    legacy_renderer_pipeline,
)
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3 import PokemonGen3TextCodec
from classic_retro.font.arabic_outline import contextual_font_data, font_glyph_text
from classic_retro.font.glyph_raster import (
    INK_THRESHOLD,
    arabic_font_file,
    drop_shadow,
    form_bounds,
    largest_fitting_size,
)
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    TokenKind,
    TokenMovement,
    TokenStream,
)

EXTRA_SYMBOL_PREFIX = 0xF9
EXT_CTRL_PREFIX = 0xFC
EXT_CTRL_RTL = 0x19
EXT_CTRL_LTR = 0x1A
EXT_CTRL_LTR_PLACEHOLDER = 0x1B
ARABIC_SLOT_FIRST = 0x40
ARABIC_SLOT_LAST = 0xCF

_STANDARD_ARABIC_LETTERS = STANDARD_ARABIC_LETTERS
_ARABIC_STATIC_CHARACTERS = ARABIC_STATIC_CHARACTERS


def firered_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Extra-symbol slots ``F9 40``..``F9 CF`` for ``characters``, in order."""
    return assign_glyph_codes(
        characters, range(ARABIC_SLOT_FIRST, ARABIC_SLOT_LAST + 1), what="FireRed Arabic glyphs"
    )


@lru_cache(maxsize=1)
def build_arabic_glyph_map() -> GlyphCodes:
    return firered_glyph_codes(arabic_presentation_repertoire())


def encode_glyph(glyph_map: GlyphCodes, character: str) -> bytes | None:
    """The two bytes (``F9 slot``) that draw ``character``, or None."""
    slot = glyph_map.code(character)
    return None if slot is None else bytes((EXTRA_SYMBOL_PREFIX, slot))


def charmap_lines(glyph_map: GlyphCodes) -> tuple[str, ...]:
    """The glyphs as pokefirered ``charmap.txt`` lines."""
    return tuple(
        f"'{character}' = F9 {glyph_map.code(character):02X}" for character in glyph_map.characters
    )


def make_ltr_placeholder_token(
    token_id: str,
    name: str,
    placeholder_id: int,
) -> InlineToken:
    if not 0 <= placeholder_id <= 0xFF:
        raise ValueError("placeholder_id must fit one byte")
    return InlineToken(
        id=token_id,
        kind=TokenKind.VARIABLE,
        movement=TokenMovement.ORDERED,
        name=name,
        args={
            "raw_hex": (f"{EXT_CTRL_PREFIX:02x}{EXT_CTRL_LTR_PLACEHOLDER:02x}{placeholder_id:02x}")
        },
    )


# The translators' notation (translations/firered.json), as in pokefirered's
# data/text: text, \n for a new line, \p for a new page after a key press
# (PROMPT_CLEAR), and {PLAYER} and {RIVAL} for the names, which stay left to right.
LTR_PLACEHOLDERS = {"PLAYER": 0x01, "RIVAL": 0x06}
PROMPT_CLEAR = 0xFB
_NOTATION = re.compile(r"\n|\\p|\{([A-Z_]+)\}")


def line_break_token(token_id: str) -> InlineToken:
    return InlineToken(id=token_id, kind=TokenKind.LINE_BREAK, movement=TokenMovement.ORDERED)


def prompt_clear_token(token_id: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=TokenKind.CONTROL,
        movement=TokenMovement.ORDERED,
        name="PROMPT_CLEAR",
        args={"raw_hex": f"{PROMPT_CLEAR:02x}"},
    )


def parse_pokemon_gen3_notation(text: str, prefix: str) -> TokenStream:
    """Tokens of a translation in the translators' notation; ids ``<prefix><n>``."""
    tokens: list[TextToken | InlineToken] = []
    position = 0
    for match in _NOTATION.finditer(text):
        _append_text(tokens, text[position : match.start()])
        token_id = f"{prefix}{len(tokens)}"
        if match.group(0) == "\n":
            tokens.append(line_break_token(token_id))
        elif match.group(0) == "\\p":
            tokens.append(prompt_clear_token(token_id))
        elif match.group(1) in LTR_PLACEHOLDERS:
            name = match.group(1)
            tokens.append(make_ltr_placeholder_token(token_id, name, LTR_PLACEHOLDERS[name]))
        else:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"Unsupported placeholder {match.group(0)} (only {{PLAYER}} and {{RIVAL}})",
            )
        position = match.end()
    _append_text(tokens, text[position:])
    return TokenStream(tuple(tokens))


def _append_text(tokens: list[TextToken | InlineToken], text: str) -> None:
    if "{" in text or "}" in text or "\\" in text:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unsupported command in FireRed text: {text!r}"
        )
    if text:
        tokens.append(TextToken(text))


def pokemon_gen3_notation(stream: TokenStream) -> str:
    """A translation's tokens in the translators' notation."""
    parts: list[str] = []
    for token in stream.tokens:
        if isinstance(token, TextToken):
            parts.append(token.text)
        elif token.kind is TokenKind.LINE_BREAK:
            parts.append("\n")
        elif token.name == "PROMPT_CLEAR":
            parts.append("\\p")
        elif token.name in LTR_PLACEHOLDERS:
            parts.append(f"{{{token.name}}}")
        else:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TOKEN, f"No FireRed notation for token {token.id}"
            )
    return "".join(parts)


class PokemonGen3ArabicEncoder:
    def __init__(self) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.base_codec = PokemonGen3TextCodec()
        self.glyph_map = build_arabic_glyph_map()

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        _reject_combining_marks(stream)
        return rtl_paint_order(self.pipeline, stream)

    def encode_prepared(self, stream: TokenStream) -> bytes:
        output = bytearray()
        for token in stream.tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    encoded = encode_glyph(self.glyph_map, character)
                    if encoded is not None:
                        output.extend(encoded)
                    else:
                        output.extend(self.base_codec.encode_character(character))
                continue

            output.extend(self.base_codec.encode(TokenStream((token,))))

        return bytes(output)

    def encode_message(
        self,
        stream: TokenStream,
        *,
        right_x: int,
        terminator: bool = True,
    ) -> bytes:
        if not 0 <= right_x <= 0xFF:
            raise ValueError("right_x must fit one byte")

        prepared = self.prepare_paint_order(stream)
        output = bytearray((EXT_CTRL_PREFIX, EXT_CTRL_RTL, right_x))
        output.extend(self.encode_prepared(prepared))
        output.extend((EXT_CTRL_PREFIX, EXT_CTRL_LTR))
        if terminator:
            output.append(0xFF)
        return bytes(output)


@dataclass(frozen=True, slots=True)
class FontAtlasResult:
    glyphs: int
    font_size: int
    rows: int
    max_advance: int


def build_arabic_font_atlas(
    font_path: Path,
    png_path: Path,
    widths_path: Path,
    *,
    glyph_map: GlyphCodes | None = None,
) -> FontAtlasResult:
    glyph_map = glyph_map or build_arabic_glyph_map()
    font, font_size, top = _choose_font(arabic_font_file(font_path), glyph_map.characters)
    rows = math.ceil(len(glyph_map.characters) / 16)
    atlas = Image.new("P", (256, rows * 16), 0)
    palette = [
        0x90,
        0xC8,
        0xFF,
        0x38,
        0x38,
        0x38,
        0xD8,
        0xD8,
        0xD8,
        0xFF,
        0xFF,
        0xFF,
    ]
    atlas.putpalette(palette + [0] * (768 - len(palette)))

    widths: list[int] = []
    # FireRed copies normal glyphs from the top-left of a 16x16 buffer and
    # renders only 14 rows. Keep foreground inside rows 0..12 so the one-pixel
    # shadow can remain inside the copied 14-row area.
    baseline = -top

    for index, character in enumerate(glyph_map.characters):
        glyph_text = character
        cell = Image.new("L", (16, 16), 0)
        draw = ImageDraw.Draw(cell)
        left, _, right, _ = font.getbbox(glyph_text, anchor="ls")

        # FireRed's CopyGlyphToWindow always starts reading at glyph x=0.
        # Centering variable-width glyphs here would make the engine crop them
        # to the first 'advance' columns. Align the ink box to x=0 instead.
        x = -left
        draw.text((x, baseline), glyph_text, font=font, fill=255, anchor="ls")

        pixels = cell.load()
        foreground = [
            (x_pos, y)
            for y in range(14)
            for x_pos in range(16)
            if pixels[x_pos, y] >= INK_THRESHOLD
        ]

        if not foreground:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                f"Selected font produced an empty glyph for U+{ord(character):04X}",
            )

        form = unicodedata.decomposition(character).split()[:1]
        if form in (["<initial>"], ["<medial>"]):
            # A joining edge must meet the adjacent cell, not the fractional
            # side bearing left by rasterization at this small pixel size.
            ink_left = min(x_pos for x_pos, _ in foreground)
            foreground = [(x_pos - ink_left, y) for x_pos, y in foreground]
        copy_width = _glyph_copy_width(font, glyph_text, left, right)
        ink_right = max(x_pos for x_pos, _ in foreground)
        if form in (["<final>"], ["<medial>"]):
            copy_width = ink_right + 1
        else:
            copy_width = max(copy_width, ink_right + 1)
        if copy_width > 16:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                (
                    f"Glyph U+{ord(character):04X} needs {copy_width}px, "
                    "which exceeds the FireRed 16px cell"
                ),
            )

        colored = Image.new("P", (16, 16), 0)
        colored.putpalette(atlas.getpalette())
        colored_pixels = colored.load()

        # Keep the shadow inside the same advance. Extending the width for a
        # shadow pixel would introduce a one-pixel gap between connected Arabic
        # presentation forms.
        for x_pos, y in drop_shadow(foreground, ((1, 1),), copy_width, 14):
            colored_pixels[x_pos, y] = 2
        for x_pos, y in foreground:
            colored_pixels[x_pos, y] = 1

        _validate_fire_red_glyph_bounds(colored, copy_width, character)
        widths.append(copy_width)

        column = index % 16
        row = index // 16
        atlas.paste(colored, (column * 16, row * 16))

    png_path.parent.mkdir(parents=True, exist_ok=True)
    widths_path.parent.mkdir(parents=True, exist_ok=True)
    # Store the palette PNG as native 2bpp so gbagfx receives the same bit
    # depth as FireRed's font format and does not need an 8bpp -> 2bpp step.
    atlas.save(png_path, format="PNG", optimize=False, bits=2)
    widths_path.write_bytes(bytes(widths))

    return FontAtlasResult(
        glyphs=len(glyph_map.characters),
        font_size=font_size,
        rows=rows,
        max_advance=max(widths),
    )


def _glyph_copy_width(
    font: ImageFont.FreeTypeFont,
    character: str,
    left: int,
    right: int,
) -> int:
    advance = math.ceil(font.getlength(character))
    ink_width = right - left
    return max(1, advance, ink_width)


def _validate_fire_red_glyph_bounds(
    glyph: Image.Image,
    copy_width: int,
    character: str,
) -> None:
    pixels = glyph.load()
    clipped = [
        (x_pos, y)
        for y in range(16)
        for x_pos in range(16)
        if pixels[x_pos, y] != 0 and (x_pos >= copy_width or y >= 14)
    ]
    if clipped:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            (
                f"Glyph U+{ord(character):04X} has pixels outside FireRed's "
                f"{copy_width}x14 copied region"
            ),
        )


def _choose_font(
    font_path: Path,
    characters: Sequence[str],
) -> tuple[ImageFont.FreeTypeFont, int, int]:
    """The largest size, and its top ink row, whose glyphs fit the copied 16x14 area."""
    return largest_fitting_size(
        _contextual_font_data(font_path, tuple(characters)),
        range(20, 5, -1),
        lambda font: _top_row(font, characters),
        "Selected font cannot fit the FireRed 16x14 copied glyph area",
    )


def _top_row(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> int | None:
    bounds = form_bounds(font, characters)
    # 13 foreground rows + one shadow row = FireRed's normal 14px height; a glyph
    # copies at least one column.
    if max(1, bounds.widest_advance) <= 16 and bounds.bottom - bounds.top <= 13:
        return bounds.top
    return None


_font_glyph_text = font_glyph_text
_contextual_font_data = contextual_font_data


def _reject_combining_marks(stream: TokenStream) -> None:
    reject_combining_marks(stream, "Pokémon Gen III Arabic font v1")
