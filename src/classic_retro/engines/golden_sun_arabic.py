"""Arabic support for the Golden Sun dialogue renderer.

The ROM overlay (``classic_retro.rom.golden_sun_arabic``) adds:

- text codes ``0x100 + slot``: Arabic glyphs, reachable because the text
  model stores 12-bit codes;
- the command ``0x0B`` (unused by the game) as the first code of a message:
  right-to-left mode. When such a message is decoded the hooks reverse every
  name inserted at runtime and tag every glyph with ``0x200``, so the
  typewriter mirrors it inside the window and the measuring code uses the
  right-to-left font.

Right-to-left glyphs come from one table indexed by ``code & 0x1FF``: the
Arabic forms and a copy of the game's Latin glyphs moved onto the Arabic
baseline. Every glyph is 16 rows high with the game's shadow (one pixel right
and down) baked in, as 2-bit pixels (1 ink, 2 shadow).

Translations stay logical Unicode Arabic; this module shapes them, resolves
bidi per segment and stores every line in right-to-left paint order.
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
from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    COMMANDS_WITH_ARGUMENT,
    DASH,
    FONT_FIRST,
    FONT_GLYPHS,
    FONT_ROWS,
    KEY_PAGE,
    LEADER_NAME,
    NEWLINE,
    PARTY_NAME,
    RUNTIME_TEXT_COMMANDS,
    SPACE,
    TERMINATORS,
    GoldenSunFont,
    command_notation,
    command_skeleton,
    skeleton_notation,
)
from classic_retro.font.arabic_outline import (
    contextual_font_data,
    joins_left_neighbour,
    joins_right_neighbour,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream

ARABIC_CODE_BASE = 0x100
RTL_MARKER = 0x0B
RTL_TAG = 0x200
RTL_CODES = 0x200
MAX_ARABIC_GLYPHS = 0x100

CELL_HEIGHT = 16
CELL_WIDTH = 16
ROW_BYTES = 4
GLYPH_BYTES = CELL_HEIGHT * ROW_BYTES
# Arabic ink uses rows 0..14 and sits on the row-10 baseline; row 15 takes the
# shadow. The game's Latin glyphs (caps end on font row 10) move up one row.
BASELINE = 10
LATIN_ROW_SHIFT = BASELINE - 11
INK_THRESHOLD = 96

# The game's sprite typewriter: 5-pixel word space, two glyphs share a 16x16
# sprite when their advances fit in 15 pixels.
SPACE_ADVANCE = 5
PAIR_WIDTH = 15
MAX_LINE_WIDTH = 176
LINES_PER_PAGE = 3
# Names are typed by the player in Latin letters (at most 5, 10 pixels widest).
NAME_WIDTH_BUDGET = 50
NAME_COMMANDS = frozenset({LEADER_NAME, CHARACTER_NAME, PARTY_NAME})

_PIXEL_INK = 1
_PIXEL_SHADOW = 2

# The game font cannot mirror, and the shared bidi step does not apply rule L4.
_MIRRORED = frozenset("()[]{}<>«»‹›")
# Latin glyphs of the USA/Europe dialogue font (0x08032224) that Arabic lines
# may use, with their advances. The ROM build compares this table with the
# font it reads before using it.
USA_LATIN_ADVANCES: dict[str, int] = {
    '!': 4, '"': 6, "'": 3, '*': 9, '+': 8, ',': 3, '-': 7, '.': 3, '/': 9, '0': 7, '1': 3,
    '2': 7, '3': 6, '4': 7, '5': 7, '6': 7, '7': 7, '8': 6, '9': 7, ':': 5, ';': 5, '=': 7,
    '?': 7, 'A': 9, 'B': 8, 'C': 7, 'D': 8, 'E': 8, 'F': 7, 'G': 7, 'H': 9, 'I': 4, 'J': 8,
    'K': 9, 'L': 7, 'M': 10, 'N': 9, 'O': 8, 'P': 8, 'Q': 8, 'R': 8, 'S': 7, 'T': 6, 'U': 7,
    'V': 8, 'W': 10, 'X': 10, 'Y': 7, 'Z': 8, 'a': 7, 'b': 7, 'c': 7, 'd': 8, 'e': 7, 'f': 6,
    'g': 7, 'h': 7, 'i': 3, 'j': 8, 'k': 8, 'l': 4, 'm': 9, 'n': 7, 'o': 7, 'p': 7, 'q': 7,
    'r': 8, 's': 7, 't': 6, 'u': 7, 'v': 8, 'w': 10, 'x': 8, 'y': 7, 'z': 8,
}  # fmt: skip


def golden_sun_command(token_id: str, *codes: int, inserted: bool = False) -> InlineToken:
    """An ordered engine command (with its argument) inside a translation.

    ``inserted`` marks a page break (``KEY_PAGE``) that the translation adds
    to the original commands.
    """
    if not codes:
        raise ValueError("a Golden Sun command needs at least one code")
    kind = TokenKind.PAGE_BREAK if codes[0] == KEY_PAGE else TokenKind.CONTROL
    if codes[0] in NAME_COMMANDS:
        kind = TokenKind.VARIABLE
    args: dict[str, str | bool] = {"codes": " ".join(f"{code:02X}" for code in codes)}
    if inserted:
        args["inserted"] = True
    return InlineToken(
        id=token_id,
        kind=kind,
        movement=TokenMovement.ORDERED,
        name=command_notation(codes[0]).strip("{}"),
        args=args,
    )


def golden_sun_newline(token_id: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=TokenKind.LINE_BREAK,
        movement=TokenMovement.ORDERED,
        args={"codes": f"{NEWLINE:02X}"},
    )


def token_codes(token: InlineToken) -> tuple[int, ...]:
    codes = token.args.get("codes")
    if not isinstance(codes, str) or not codes:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TOKEN, f"Golden Sun token {token.id} carries no command codes"
        )
    return tuple(int(code, 16) for code in codes.split())


def is_inserted(token: InlineToken) -> bool:
    return bool(token.args.get("inserted", False))


@dataclass(frozen=True, slots=True)
class GoldenSunArabicGlyphMap:
    characters: tuple[str, ...]
    slots: dict[str, int]

    def code(self, character: str) -> int | None:
        slot = self.slots.get(character)
        return None if slot is None else ARABIC_CODE_BASE + slot


@lru_cache(maxsize=1)
def build_golden_sun_arabic_glyph_map() -> GoldenSunArabicGlyphMap:
    characters = arabic_presentation_repertoire()
    if len(characters) > MAX_ARABIC_GLYPHS:
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"Arabic glyph set needs {len(characters)} codes; 0x100..0x1FF has 256",
        )
    return GoldenSunArabicGlyphMap(
        characters=characters,
        slots={character: index for index, character in enumerate(characters)},
    )


@dataclass(frozen=True, slots=True)
class RtlGlyph:
    """16 rows of 2-bit pixels (1 ink, 2 shadow), pixel x at bits 2x..2x+1."""

    advance: int
    rows: tuple[int, ...]

    def pixel(self, x: int, y: int) -> int:
        return self.rows[y] >> 2 * x & 3

    def encode(self) -> bytes:
        return b"".join(row.to_bytes(ROW_BYTES, "little") for row in self.rows)


def _encode_rows(ink: set[tuple[int, int]], advance: int) -> RtlGlyph:
    # The shadow stays inside the glyph's own advance: the neighbour on the
    # right is painted first and must keep its joining stroke.
    shadow = {
        (x + 1, y + 1) for x, y in ink if x + 1 < min(advance, CELL_WIDTH) and y + 1 < CELL_HEIGHT
    } - ink
    rows = []
    for y in range(CELL_HEIGHT):
        value = 0
        for x in range(CELL_WIDTH):
            if (x, y) in ink:
                value |= _PIXEL_INK << 2 * x
            elif (x, y) in shadow:
                value |= _PIXEL_SHADOW << 2 * x
        rows.append(value)
    return RtlGlyph(advance, tuple(rows))


@dataclass(frozen=True, slots=True)
class GoldenSunRtlFont:
    """The right-to-left glyph table indexed by ``code & 0x1FF``."""

    glyphs: dict[int, RtlGlyph]
    font_size: int
    arabic_widths: dict[str, int]

    def advance(self, code: int) -> int:
        glyph = self.glyphs.get(code & (RTL_CODES - 1))
        if glyph is None:
            raise ClassicRetroError(ErrorCode.MISSING_GLYPH, f"No right-to-left glyph {code:#x}")
        return glyph.advance

    def advances(self) -> dict[int, int]:
        """Advance per code for the encoder: the glyphs plus the pinned Latin table."""
        advances = {ord(character): width for character, width in USA_LATIN_ADVANCES.items()}
        advances.update((code, glyph.advance) for code, glyph in self.glyphs.items())
        return advances

    @property
    def widths_data(self) -> bytes:
        return bytes(
            self.glyphs[code].advance if code in self.glyphs else 0 for code in range(RTL_CODES)
        )

    @property
    def bitmap_data(self) -> bytes:
        empty = bytes(GLYPH_BYTES)
        return b"".join(
            self.glyphs[code].encode() if code in self.glyphs else empty
            for code in range(RTL_CODES)
        )

    @property
    def data(self) -> bytes:
        """Widths (512 bytes) followed by 512 glyphs of 64 bytes."""
        return self.widths_data + self.bitmap_data


def latin_rtl_glyphs(font: GoldenSunFont) -> dict[int, RtlGlyph]:
    """The game's own Latin glyphs, moved onto the Arabic baseline."""
    glyphs: dict[int, RtlGlyph] = {}
    for code in range(FONT_FIRST + 1, FONT_FIRST + FONT_GLYPHS):
        source = font.glyph(code)
        if source.advance == 0 or source.advance > CELL_WIDTH:
            continue
        ink = {
            (x, y + LATIN_ROW_SHIFT)
            for y in range(FONT_ROWS)
            for x in range(CELL_WIDTH)
            if source.pixel(x, y)
        }
        if any(not 0 <= y < CELL_HEIGHT - 1 for _, y in ink):
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED, f"Latin glyph {code:#x} leaves the 16-row cell"
            )
        glyphs[code] = _encode_rows(ink, source.advance)
    return glyphs


def build_golden_sun_rtl_font(
    font_path: Path,
    latin: GoldenSunFont | None = None,
    *,
    glyph_map: GoldenSunArabicGlyphMap | None = None,
) -> GoldenSunRtlFont:
    """Rasterize every Arabic presentation form (and copy the Latin glyphs) into 16x16 cells."""
    glyph_map = glyph_map or build_golden_sun_arabic_glyph_map()
    font_path = font_path.expanduser()
    if not font_path.is_file():
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"Arabic font file not found: {font_path}"
        )
    font, size = _choose_font(contextual_font_data(font_path, glyph_map.characters), glyph_map)
    glyphs: dict[int, RtlGlyph] = latin_rtl_glyphs(latin) if latin is not None else {}
    glyphs[SPACE] = RtlGlyph(SPACE_ADVANCE, (0,) * CELL_HEIGHT)
    widths: dict[str, int] = {}
    for character in glyph_map.characters:
        ink, advance = _rasterize(font, character)
        code = glyph_map.code(character)
        assert code is not None
        glyphs[code] = _encode_rows(ink, advance)
        widths[character] = advance
    return GoldenSunRtlFont(glyphs=glyphs, font_size=size, arabic_widths=widths)


def _choose_font(
    font_data: bytes, glyph_map: GoldenSunArabicGlyphMap
) -> tuple[ImageFont.FreeTypeFont, int]:
    """Largest size whose ink fits rows 0..14 around the row-10 baseline."""
    for size in range(14, 5, -1):
        font = ImageFont.truetype(
            BytesIO(font_data), size=size, layout_engine=ImageFont.Layout.BASIC
        )
        boxes = [font.getbbox(character, anchor="ls") for character in glyph_map.characters]
        top = min(box[1] for box in boxes)
        bottom = max(box[3] for box in boxes)
        widest = max(box[2] - box[0] for box in boxes)
        if BASELINE + top >= 0 and BASELINE + bottom <= CELL_HEIGHT - 1 and widest < CELL_WIDTH:
            return font, size
    raise ClassicRetroError(
        ErrorCode.FONT_BUILD_FAILED, "Selected font cannot fit the Golden Sun 16x15 glyph area"
    )


def _rasterize(font: ImageFont.FreeTypeFont, character: str) -> tuple[set[tuple[int, int]], int]:
    cell = Image.new("L", (CELL_WIDTH * 3, CELL_HEIGHT), 0)
    left, _, right, _ = font.getbbox(character, anchor="ls")
    ImageDraw.Draw(cell).text(
        (CELL_WIDTH - left, BASELINE), character, font=font, fill=255, anchor="ls"
    )
    pixels = cell.load()
    ink = {
        (x, y)
        for y in range(CELL_HEIGHT)
        for x in range(cell.width)
        if pixels[x, y] >= INK_THRESHOLD
    }
    if not ink:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Selected font produced an empty glyph for U+{ord(character):04X}",
        )
    ink_left = min(x for x, _ in ink)
    ink = {(x - ink_left, y) for x, y in ink}
    ink_right = max(x for x, _ in ink)
    if joins_right_neighbour(character):
        # Medial and final forms end at their last ink column, touching the
        # glyph painted before them (on their right).
        advance = ink_right + 1
    else:
        advance = max(math.ceil(font.getlength(character)), right - left, ink_right + 1)
        if not joins_left_neighbour(character) and advance == ink_right + 1:
            advance += 1
    if advance > PAIR_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {advance}px; a Golden Sun sprite holds 15",
        )
    if any(y >= CELL_HEIGHT - 1 for _, y in ink):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"Glyph U+{ord(character):04X} reaches the shadow row"
        )
    return ink, advance


def font_preview(font: GoldenSunRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, shadow blue, advance dark red."""
    codes = sorted(font.glyphs)
    cell = CELL_WIDTH + 2
    atlas = Image.new("RGB", (16 * cell, math.ceil(len(codes) / 16) * cell), (40, 40, 40))
    colours = {0: (0, 0, 0), _PIXEL_INK: (255, 255, 255), _PIXEL_SHADOW: (90, 90, 150)}
    for index, code in enumerate(codes):
        glyph = font.glyphs[code]
        origin_x = (index % 16) * cell + 1
        origin_y = (index // 16) * cell + 1
        for y in range(CELL_HEIGHT):
            for x in range(CELL_WIDTH):
                value = glyph.pixel(x, y)
                colour = colours.get(value, (255, 0, 0))
                if value == 0 and x >= glyph.advance:
                    colour = (70, 20, 20)
                atlas.putpixel((origin_x + x, origin_y + y), colour)
    return atlas


@dataclass(frozen=True, slots=True)
class GoldenSunArabicLine:
    page: int
    width: int
    names: int


@dataclass(frozen=True, slots=True)
class GoldenSunArabicEncoding:
    codes: tuple[int, ...]
    lines: tuple[GoldenSunArabicLine, ...]


class GoldenSunArabicEncoder:
    """Convert logical Arabic token streams into Golden Sun codes in paint order."""

    def __init__(
        self,
        *,
        advances: dict[int, int],
        glyph_map: GoldenSunArabicGlyphMap | None = None,
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.glyph_map = glyph_map or build_golden_sun_arabic_glyph_map()
        self.advances = dict(advances)

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        reject_combining_marks(stream, "Golden Sun Arabic font v1")
        for token in stream.tokens:
            if isinstance(token, TextToken):
                mirrored = sorted({character for character in token.text if character in _MIRRORED})
                if mirrored:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TEXT,
                        "Golden Sun Arabic v1 cannot mirror bracket glyphs: " + "".join(mirrored),
                    )
                if "\n" in token.text:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TEXT,
                        "Use explicit Golden Sun newline tokens instead of '\\n' in text",
                    )
                continue
            codes = token_codes(token)
            command = codes[0]
            if command in RUNTIME_TEXT_COMMANDS - NAME_COMMANDS or command == DASH:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Golden Sun Arabic v1 does not place {command_notation(command)}",
                )
            expected = 2 if command in COMMANDS_WITH_ARGUMENT else 1
            if len(codes) != expected or command == RTL_MARKER:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TOKEN,
                    f"Golden Sun token {token.id} must hold one command and its argument",
                )
            if is_inserted(token) and codes != (KEY_PAGE,):
                raise ClassicRetroError(
                    ErrorCode.TOKEN_DEFINITION_MISMATCH,
                    f"Golden Sun token {token.id} may only insert KEY_PAGE",
                )
        return rtl_paint_order(self.pipeline, stream)

    def encode_message(self, stream: TokenStream) -> GoldenSunArabicEncoding:
        """Encode, then measure every line against the window and page capacity."""
        pages = _PageLayout()
        codes: list[int] = [RTL_MARKER]
        for token in self.prepare_paint_order(stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    code = self.code(character)
                    codes.append(code)
                    pages.add(SPACE_ADVANCE if code == SPACE else self.advances[code])
                continue
            values = token_codes(token)
            command = values[0]
            if command == NEWLINE:
                pages.close_line()
            elif command == KEY_PAGE:
                pages.close_page()
            elif command in TERMINATORS:
                pages.close_page()
                pages.ended = True
            elif command in NAME_COMMANDS:
                pages.add(NAME_WIDTH_BUDGET, name=True)
            codes.extend(values)
        if not pages.ended or codes[-1] not in TERMINATORS:
            raise ClassicRetroError(
                ErrorCode.MISSING_TERMINATOR, "Golden Sun message must end with KEY_END or QUESTION"
            )
        return GoldenSunArabicEncoding(codes=tuple(codes), lines=tuple(pages.lines))

    def code(self, character: str) -> int:
        if character == " ":
            return SPACE
        code = self.glyph_map.code(character)
        if code is None and character in USA_LATIN_ADVANCES:
            code = ord(character)
        if code is not None and code in self.advances:
            return code
        if unicodedata.category(character).startswith("L") and "ARABIC" in unicodedata.name(
            character, ""
        ):
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, f"No Golden Sun Arabic glyph for U+{ord(character):04X}"
            )
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT, f"Golden Sun Arabic text has no glyph for {character!r}"
        )


class _PageLayout:
    """Line widths and page capacity of one message."""

    def __init__(self) -> None:
        self.lines: list[GoldenSunArabicLine] = []
        self.ended = False
        self._page = 0
        self._page_lines = 0
        self._width = 0
        self._names = 0

    def add(self, advance: int, *, name: bool = False) -> None:
        if self.ended:
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION, "Golden Sun text after the end of the message"
            )
        self._width += advance
        self._names += name

    def close_line(self) -> None:
        self._page_lines += 1
        if self._page_lines > LINES_PER_PAGE:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Page {self._page + 1} has more than {LINES_PER_PAGE} lines",
            )
        if self._width > MAX_LINE_WIDTH:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Line {len(self.lines) + 1} needs {self._width}px; "
                f"Golden Sun Arabic lines hold {MAX_LINE_WIDTH}px",
            )
        self.lines.append(GoldenSunArabicLine(self._page, self._width, self._names))
        self._width = 0
        self._names = 0

    def close_page(self) -> None:
        self.close_line()
        self._page += 1
        self._page_lines = 0


def validate_command_skeleton(source_skeleton: tuple[int, ...], stream: TokenStream) -> None:
    """The translation's commands, minus inserted pages, must equal the original's.

    The em dash command only draws two dash glyphs, so a translation may drop it.
    """
    target = command_skeleton(
        tuple(
            code
            for token in stream.inline_tokens
            if not is_inserted(token)
            for code in token_codes(token)
        )
    )
    source = _without_dashes(source_skeleton)
    if target != source:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            "Golden Sun commands differ from the original: "
            + skeleton_notation(source)
            + " != "
            + skeleton_notation(target),
        )


def _without_dashes(skeleton: tuple[int, ...]) -> tuple[int, ...]:
    output: list[int] = []
    expect_argument = False
    for code in skeleton:
        if expect_argument:
            output.append(code)
            expect_argument = False
        elif code != DASH:
            output.append(code)
            expect_argument = code in COMMANDS_WITH_ARGUMENT
    return tuple(output)
