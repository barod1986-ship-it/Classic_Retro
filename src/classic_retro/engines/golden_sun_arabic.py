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

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import (
    reject_combining_marks,
    reject_mirrored,
    reject_text_newlines,
    rtl_paint_order,
)
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    COMMAND_NAMES,
    COMMANDS_WITH_ARGUMENT,
    DASH,
    FIRST_GLYPH,
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
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    arabic_font_file,
    draw_form,
    drop_shadow,
    form_bounds,
    largest_fitting_size,
    two_bit_rows,
)
from classic_retro.font.previews import glyph_atlas
from classic_retro.text.commands import (
    command_codes,
    command_token,
    is_inserted,
    require_same_commands,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

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
    return command_token(
        token_id,
        kind,
        " ".join(f"{code:02X}" for code in codes),
        name=command_notation(codes[0]).strip("{}"),
        inserted=inserted,
    )


def golden_sun_newline(token_id: str) -> InlineToken:
    return command_token(token_id, TokenKind.LINE_BREAK, f"{NEWLINE:02X}")


def token_codes(token: InlineToken) -> tuple[int, ...]:
    return command_codes(token, "Golden Sun")


# The translators' notation (translations/golden-sun.json and extracted
# originals): text, \n for a new line, and every other command by name in
# braces with its argument code in hex: {KEY_END}, {QUESTION}, {CHARACTER_NAME 01}
# (the hero's name). {+KEY_PAGE} is a page break the translation adds. Codes
# without a name, and glyphs outside printable ASCII, are written as hex: {1C}.
_CODES_BY_NAME = {name: code for code, name in COMMAND_NAMES.items()}
_BRACES = re.compile(r"\{([^{}]*)\}")


def _code_notation(code: int) -> str:
    return COMMAND_NAMES.get(code, f"{code:02X}")


def golden_sun_notation(stream: TokenStream) -> str:
    """A translation's tokens in the translators' notation."""
    parts: list[str] = []
    for token in stream.tokens:
        if isinstance(token, TextToken):
            parts.append(token.text)
            continue
        codes = token_codes(token)
        if codes == (NEWLINE,) and token.kind is TokenKind.LINE_BREAK:
            parts.append("\n")
            continue
        words = [_code_notation(codes[0]), *(f"{code:02X}" for code in codes[1:])]
        parts.append("{" + ("+" if is_inserted(token) else "") + " ".join(words) + "}")
    return "".join(parts)


def parse_golden_sun_notation(text: str, prefix: str) -> TokenStream:
    """Tokens of a translation in the translators' notation; ids ``<prefix><n>`` by part."""
    tokens: list[InlineToken | TextToken] = []
    for number, part in enumerate(_notation_parts(text)):
        token_id = f"{prefix}{number}"
        if isinstance(part, str):
            tokens.append(TextToken(part))
        elif part == ((NEWLINE,), False):
            tokens.append(golden_sun_newline(token_id))
        else:
            codes, inserted = part
            tokens.append(golden_sun_command(token_id, *codes, inserted=inserted))
    return TokenStream(tuple(tokens))


def _notation_parts(text: str) -> list[str | tuple[tuple[int, ...], bool]]:
    parts: list[str | tuple[tuple[int, ...], bool]] = []
    position = 0
    for match in _BRACES.finditer(text):
        parts.extend(_text_parts(text[position : match.start()]))
        parts.append(_command_codes(match.group(1)))
        position = match.end()
    parts.extend(_text_parts(text[position:]))
    return parts


def _text_parts(text: str) -> list[str | tuple[tuple[int, ...], bool]]:
    if "{" in text or "}" in text:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unbalanced brace in Golden Sun text: {text!r}"
        )
    parts: list[str | tuple[tuple[int, ...], bool]] = []
    for number, line in enumerate(text.split("\n")):
        if number:
            parts.append(((NEWLINE,), False))
        if line:
            parts.append(line)
    return parts


def _command_codes(body: str) -> tuple[tuple[int, ...], bool]:
    inserted = body.startswith("+")
    words = body.removeprefix("+").split()
    if not words:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, "Empty Golden Sun command {}")
    name, *arguments = words
    code = _CODES_BY_NAME.get(name)
    if code is None:
        code = _hex_code(name, body)
    expected = 1 if code in COMMANDS_WITH_ARGUMENT else 0
    if len(arguments) != expected:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE,
            f"Golden Sun command {{{body}}} needs {expected} argument code(s)",
        )
    return (code, *(_hex_code(argument, body) for argument in arguments)), inserted


def _hex_code(word: str, body: str) -> int:
    try:
        return int(word, 16)
    except ValueError:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown Golden Sun command {{{body}}}"
        ) from None


def golden_sun_codes_notation(codes: Sequence[int]) -> str:
    """An original string (English codes, terminator included) in the translators' notation."""
    parts: list[str] = []
    argument_of: int | None = None
    for code in codes:
        if argument_of is not None:
            parts[-1] = parts[-1][:-1] + f" {code:02X}}}"
            argument_of = None
        elif code == NEWLINE:
            parts.append("\n")
        elif code < FIRST_GLYPH:
            parts.append("{" + _code_notation(code) + "}")
            if code in COMMANDS_WITH_ARGUMENT:
                argument_of = code
        elif 0x20 <= code < 0x7F and chr(code) not in "{}":
            parts.append(chr(code))
        else:
            parts.append(f"{{{code:02X}}}")
    return "".join(parts)


def golden_sun_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes 0x100 onwards for ``characters``: the text model stores 12-bit codes."""
    return assign_glyph_codes(
        characters,
        range(ARABIC_CODE_BASE, ARABIC_CODE_BASE + MAX_ARABIC_GLYPHS),
        what="Golden Sun Arabic glyphs",
    )


@lru_cache(maxsize=1)
def build_golden_sun_arabic_glyph_map() -> GlyphCodes:
    return golden_sun_glyph_codes(arabic_presentation_repertoire())


@dataclass(frozen=True, slots=True)
class RtlGlyph:
    """16 rows of 2-bit pixels (1 ink, 2 shadow), pixel x at bits 2x..2x+1."""

    advance: int
    rows: tuple[int, ...]

    def pixel(self, x: int, y: int) -> int:
        return self.rows[y] >> 2 * x & 3

    def encode(self) -> bytes:
        return b"".join(row.to_bytes(ROW_BYTES, "little") for row in self.rows)


def _encode_rows(ink: set[tuple[int, int]] | frozenset[tuple[int, int]], advance: int) -> RtlGlyph:
    shadow = drop_shadow(ink, ((1, 1),), min(advance, CELL_WIDTH), CELL_HEIGHT)
    rows = two_bit_rows(
        ink,
        shadow,
        columns=CELL_WIDTH,
        height=CELL_HEIGHT,
        ink_value=_PIXEL_INK,
        shadow_value=_PIXEL_SHADOW,
    )
    return RtlGlyph(advance, rows)


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
    glyph_map: GlyphCodes | None = None,
) -> GoldenSunRtlFont:
    """Rasterize every Arabic presentation form (and copy the Latin glyphs) into 16x16 cells."""
    glyph_map = glyph_map or build_golden_sun_arabic_glyph_map()
    characters = glyph_map.characters
    font, size, _ = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), characters),
        range(14, 5, -1),
        lambda font: _fits(font, characters),
        "Selected font cannot fit the Golden Sun 16x15 glyph area",
    )
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


def _fits(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> bool | None:
    """Whether the ink fits rows 0..14 around the row-10 baseline, narrower than a cell."""
    bounds = form_bounds(font, characters)
    if (
        BASELINE + bounds.top >= 0
        and BASELINE + bounds.bottom <= CELL_HEIGHT - 1
        and bounds.widest_ink < CELL_WIDTH
    ):
        return True
    return None


def _rasterize(
    font: ImageFont.FreeTypeFont, character: str
) -> tuple[frozenset[tuple[int, int]], int]:
    form = draw_form(font, character, BASELINE)
    if form.advance > PAIR_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {form.advance}px; a Golden Sun sprite holds 15",
        )
    if any(y >= CELL_HEIGHT - 1 for _, y in form.ink):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"Glyph U+{ord(character):04X} reaches the shadow row"
        )
    return form.ink, form.advance


def font_preview(font: GoldenSunRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, shadow blue, advance dark red."""
    codes = sorted(font.glyphs)
    colours = {0: (0, 0, 0), _PIXEL_INK: (255, 255, 255), _PIXEL_SHADOW: (90, 90, 150)}

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixel(x, y)
        if value == 0 and x >= glyph.advance:
            return (70, 20, 20)
        return colours.get(value, (255, 0, 0))

    return glyph_atlas(len(codes), CELL_WIDTH, CELL_HEIGHT, colour)


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
        glyph_map: GlyphCodes | None = None,
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.glyph_map = glyph_map or build_golden_sun_arabic_glyph_map()
        self.advances = dict(advances)

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        reject_combining_marks(stream, "Golden Sun Arabic font v1")
        reject_mirrored(stream, "Golden Sun Arabic v1")
        reject_text_newlines(
            stream, "Use explicit Golden Sun newline tokens instead of '\\n' in text"
        )
        for token in stream.inline_tokens:
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
        raise no_glyph(character, "Golden Sun Arabic")


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
    require_same_commands("Golden Sun", _without_dashes(source_skeleton), target, skeleton_notation)


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
