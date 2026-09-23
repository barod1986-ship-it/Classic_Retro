from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from classic_retro.arabic.pipeline import ArabicPipeline, ArabicPipelineConfig
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen3 import PokemonGen3TextCodec
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    Token,
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

_STANDARD_ARABIC_LETTERS = "ءآأؤإئابتثجحخدذرزسشصضطظعغفقكلمنهويىة"
_ARABIC_STATIC_CHARACTERS = "،؛؟ـ٠١٢٣٤٥٦٧٨٩"


@dataclass(frozen=True, slots=True)
class ArabicGlyphMap:
    characters: tuple[str, ...]
    slots: dict[str, int]

    @property
    def first_slot(self) -> int:
        return ARABIC_SLOT_FIRST

    @property
    def last_slot(self) -> int:
        return ARABIC_SLOT_FIRST + len(self.characters) - 1

    def encode(self, character: str) -> bytes | None:
        slot = self.slots.get(character)
        if slot is None:
            return None
        return bytes((EXTRA_SYMBOL_PREFIX, slot))

    def charmap_lines(self) -> tuple[str, ...]:
        return tuple(
            f"'{character}' = F9 {self.slots[character]:02X}" for character in self.characters
        )


@lru_cache(maxsize=1)
def build_arabic_glyph_map() -> ArabicGlyphMap:
    pipeline = ArabicPipeline(
        ArabicPipelineConfig(
            support_ligatures=False,
            preserve_harakat=True,
            preserve_tatweel=True,
            support_zwj=True,
        )
    )
    characters: set[str] = set(_ARABIC_STATIC_CHARACTERS)

    for letter in _STANDARD_ARABIC_LETTERS:
        for prefix, suffix in (("", ""), ("ب", ""), ("", "ب"), ("ب", "ب")):
            source = prefix + letter + suffix
            shaped = pipeline.process(TokenStream((TextToken(source),))).shaped.visible_text
            index = len(prefix)
            if index >= len(shaped):
                raise ClassicRetroError(
                    ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                    f"Could not derive shaped form for Arabic letter {letter!r}",
                )
            characters.add(shaped[index])

    ordered = tuple(sorted(characters, key=ord))
    capacity = ARABIC_SLOT_LAST - ARABIC_SLOT_FIRST + 1
    if len(ordered) > capacity:
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"Arabic glyph set needs {len(ordered)} slots; only {capacity} are available",
        )

    slots = {character: ARABIC_SLOT_FIRST + index for index, character in enumerate(ordered)}
    return ArabicGlyphMap(characters=ordered, slots=slots)


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


class PokemonGen3ArabicEncoder:
    def __init__(self) -> None:
        self.pipeline = ArabicPipeline(
            ArabicPipelineConfig(
                support_ligatures=False,
                preserve_harakat=True,
                preserve_tatweel=True,
                support_zwj=True,
            )
        )
        self.base_codec = PokemonGen3TextCodec()
        self.glyph_map = build_arabic_glyph_map()

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        _reject_combining_marks(stream)
        output: list[Token] = []
        segment: list[Token] = []

        def flush_segment() -> None:
            if not segment:
                return
            visual = self.pipeline.process(TokenStream(tuple(segment))).visual
            output.extend(_reverse_visual_stream(visual).tokens)
            segment.clear()

        for token in stream.tokens:
            if isinstance(token, InlineToken) and token.movement is TokenMovement.ORDERED:
                flush_segment()
                output.append(token)
            else:
                segment.append(token)

        flush_segment()
        return TokenStream(tuple(output))

    def encode_prepared(self, stream: TokenStream) -> bytes:
        output = bytearray()
        for token in stream.tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    encoded = self.glyph_map.encode(character)
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
    glyph_map: ArabicGlyphMap | None = None,
) -> FontAtlasResult:
    glyph_map = glyph_map or build_arabic_glyph_map()
    font_path = font_path.expanduser()

    if not font_path.is_file():
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Arabic font file not found: {font_path}",
        )

    font, font_size, top, _ = _choose_font(font_path, glyph_map.characters)
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
    baseline = 1 - top

    for index, character in enumerate(glyph_map.characters):
        cell = Image.new("L", (16, 16), 0)
        draw = ImageDraw.Draw(cell)
        left, _, right, _ = font.getbbox(character, anchor="ls")
        ink_width = right - left
        x = max(0, (16 - ink_width) // 2 - left)
        draw.text((x, baseline), character, font=font, fill=255, anchor="ls")

        pixels = cell.load()
        foreground: list[tuple[int, int]] = []
        for y in range(15):
            for x_pos in range(16):
                if pixels[x_pos, y] >= 128:
                    foreground.append((x_pos, y))

        if not foreground:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                f"Selected font produced an empty glyph for U+{ord(character):04X}",
            )

        colored = Image.new("P", (16, 16), 0)
        colored.putpalette(atlas.getpalette())
        colored_pixels = colored.load()

        for x_pos, y in foreground:
            shadow_x = x_pos + 1
            shadow_y = y + 1
            if shadow_x < 16 and shadow_y < 16:
                colored_pixels[shadow_x, shadow_y] = 2
        for x_pos, y in foreground:
            colored_pixels[x_pos, y] = 1

        occupied = [
            x_pos for y in range(16) for x_pos in range(16) if colored_pixels[x_pos, y] != 0
        ]
        advance = min(15, max(3, max(occupied) - min(occupied) + 2))
        widths.append(advance)

        column = index % 16
        row = index // 16
        atlas.paste(colored, (column * 16, row * 16))

    png_path.parent.mkdir(parents=True, exist_ok=True)
    widths_path.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(png_path, format="PNG", optimize=False)
    widths_path.write_bytes(bytes(widths))

    return FontAtlasResult(
        glyphs=len(glyph_map.characters),
        font_size=font_size,
        rows=rows,
        max_advance=max(widths),
    )


def _choose_font(
    font_path: Path,
    characters: tuple[str, ...],
) -> tuple[ImageFont.FreeTypeFont, int, int, int]:
    for size in range(18, 5, -1):
        font = ImageFont.truetype(str(font_path), size=size)
        boxes = [font.getbbox(character, anchor="ls") for character in characters]
        widths = [right - left for left, _, right, _ in boxes]
        top = min(box[1] for box in boxes)
        bottom = max(box[3] for box in boxes)
        if max(widths) <= 13 and bottom - top <= 13:
            return font, size, top, bottom

    raise ClassicRetroError(
        ErrorCode.FONT_BUILD_FAILED,
        "Selected font cannot fit the FireRed 16x16 Arabic glyph cell",
    )


def _reject_combining_marks(stream: TokenStream) -> None:
    marks = sorted(
        {
            character
            for token in stream.tokens
            if isinstance(token, TextToken)
            for character in token.text
            if unicodedata.combining(character)
        }
    )
    if marks:
        values = ", ".join(f"U+{ord(character):04X}" for character in marks)
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_ARABIC_MARK,
            "Pokémon Gen III Arabic font v1 does not support combining marks: " + values,
        )


def _reverse_visual_stream(stream: TokenStream) -> TokenStream:
    output: list[Token] = []
    for token in reversed(stream.tokens):
        if isinstance(token, TextToken):
            output.append(TextToken(token.text[::-1]))
        else:
            output.append(token)
    return TokenStream(tuple(output))
