"""Arabic support for the Final Fantasy VI Advance event text renderer.

The ROM overlay (``classic_retro.rom.ff6a_arabic``) adds:

- text codes ``0x600 + slot``: Arabic glyphs from a second ``FONT`` resource,
  16 pixels high, in the game's 2-bit ink/shadow format;
- the code ``0x5FF`` as the first code of a message: right-to-left mode for the
  whole message, 16-pixel lines and a taller window-less text band.

The renderer skips unknown commands, so the marker is invisible. Translations
stay logical Unicode Arabic; this module shapes them, resolves bidi per
segment and stores every line in right-to-left paint order.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
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
from classic_retro.engines.ff6a import (
    CENTER,
    CHOICE,
    COMMAND_NAMES,
    COMMANDS_WITH_ARGUMENT,
    END,
    FONT_ASCII_ENTRIES,
    FONT_NO_GLYPH,
    KEY_PAGE,
    LAST_GLYPH,
    MAX_GLYPH_ROW_BYTES,
    NEWLINE,
    PAGE,
    PAUSE,
    PORTRAIT_FIRST,
    PORTRAIT_LAST,
    RUNTIME_TEXT_COMMANDS,
    Ff6aFont,
    Ff6aGlyph,
    command_notation,
    command_skeleton,
    encode_code,
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

ARABIC_CODE_BASE = 0x600
RTL_MARKER = 0x5FF
MAX_ARABIC_GLYPHS = 0x100

GLYPH_HEIGHT = 16
GLYPH_MAX_WIDTH = 16
# The Latin font (12 rows) puts its baseline under row 9; Arabic shares it so
# that the game's own punctuation can sit inside Arabic lines.
LATIN_BASELINE = 10

RIGHT_EDGE = 224
PORTRAIT_MARGIN = 40
DIALOGUE_LINES = 2
NARRATION_LINES = 4

_PIXEL_INK = 1
_PIXEL_SHADOW = 2
_SHADOW_OFFSETS = ((1, 0), (0, 1), (1, 1))

# Latin glyph codes and advances of the USA dialogue font (FONT at 0x08162CCC),
# for characters that may appear inside Arabic lines. The ROM build compares
# this table with the font it reads before using it.
USA_LATIN_GLYPHS: dict[str, tuple[int, int]] = {
    " ": (0x00, 3), "!": (0x16, 5), '"': (0x39, 5), "%": (0x4F, 8), "'": (0x18, 3),
    "*": (0x3B, 7), "+": (0x52, 7), "-": (0x34, 7), ".": (0x0A, 4), "/": (0x4E, 6),
    "0": (0x33, 8), "1": (0x40, 5), "2": (0x45, 8), "3": (0x46, 7), "4": (0x47, 8),
    "5": (0x42, 7), "6": (0x49, 8), "7": (0x4A, 7), "8": (0x48, 8), "9": (0x4C, 8),
    ":": (0x19, 4), "=": (0x4D, 6), "~": (0x51, 8),
}  # fmt: skip


class Ff6aLayout:
    DIALOGUE = "dialogue"
    NARRATION = "narration"

    LINES = {DIALOGUE: DIALOGUE_LINES, NARRATION: NARRATION_LINES}


def ff6a_command(token_id: str, *codes: int, inserted: bool = False) -> InlineToken:
    """An ordered engine command (with its argument codes) inside a translation.

    ``inserted`` marks a page break that the translation adds to the original
    commands; only ``PAUSE n, PAGE, NEWLINE`` and ``KEY_PAGE`` may be inserted.
    """
    if not codes:
        raise ValueError("an FF6A command needs at least one code")
    kind = TokenKind.PAGE_BREAK if {PAGE, KEY_PAGE} & set(codes) else TokenKind.CONTROL
    return command_token(
        token_id,
        kind,
        " ".join(f"{code:03X}" for code in codes),
        name=command_notation(codes[0]).strip("{}"),
        inserted=inserted,
    )


def ff6a_newline(token_id: str) -> InlineToken:
    return command_token(token_id, TokenKind.LINE_BREAK, f"{NEWLINE:03X}")


def token_codes(token: InlineToken) -> tuple[int, ...]:
    return command_codes(token, "FF6A")


# The translators' notation (translations/ff6a.json and extracted originals):
# text, \n for a new line, and every other command by name in braces, its
# argument in hex after it: {CENTER}, {PAUSE 14C}, {TIMED_CLOSE 243}. {PAGE}
# is a new page (the engine's PAGE and the newline after it). A brace may hold
# several commands; a leading + marks a page break the translation adds:
# {+KEY_PAGE}, {+PAUSE 14C PAGE}. Codes without a name are written as hex.
_CODES_BY_NAME = {name: code for code, name in COMMAND_NAMES.items()}
_BRACES = re.compile(r"\{([^{}]*)\}")


def _code_words(codes: Sequence[int]) -> list[str]:
    words: list[str] = []
    position = 0
    while position < len(codes):
        code = codes[position]
        following = codes[position + 1] if position + 1 < len(codes) else None
        if code == PAGE and following == NEWLINE:
            words.append("PAGE")
            position += 2
        elif code in COMMANDS_WITH_ARGUMENT and following is not None:
            words.append(f"{COMMAND_NAMES[code]} {following:03X}")
            position += 2
        else:
            words.append(COMMAND_NAMES.get(code, f"{code:03X}"))
            position += 1
    return words


def ff6a_notation(stream: TokenStream) -> str:
    """A translation's tokens in the translators' notation."""
    parts: list[str] = []
    for token in stream.tokens:
        if isinstance(token, TextToken):
            parts.append(token.text)
        elif token.kind is TokenKind.LINE_BREAK and not is_inserted(token):
            parts.append("\n")
        else:
            prefix = "+" if is_inserted(token) else ""
            parts.append("{" + prefix + " ".join(_code_words(token_codes(token))) + "}")
    return "".join(parts)


def parse_ff6a_notation(text: str, prefix: str) -> TokenStream:
    """Tokens of a translation in the translators' notation; ids ``<prefix><n>`` by part."""
    tokens: list[InlineToken | TextToken] = []
    position = 0
    parts: list[str | tuple[tuple[int, ...], bool] | None] = []
    for match in _BRACES.finditer(text):
        parts.extend(_text_parts(text[position : match.start()]))
        parts.append(_brace_codes(match.group(1)))
        position = match.end()
    parts.extend(_text_parts(text[position:]))
    for number, part in enumerate(parts):
        token_id = f"{prefix}{number}"
        if part is None:
            tokens.append(ff6a_newline(token_id))
        elif isinstance(part, str):
            tokens.append(TextToken(part))
        else:
            codes, inserted = part
            tokens.append(ff6a_command(token_id, *codes, inserted=inserted))
    return TokenStream(tuple(tokens))


def _text_parts(text: str) -> list[str | tuple[tuple[int, ...], bool] | None]:
    if "{" in text or "}" in text:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unbalanced brace in FF6A text: {text!r}"
        )
    parts: list[str | tuple[tuple[int, ...], bool] | None] = []
    for number, line in enumerate(text.split("\n")):
        if number:
            parts.append(None)
        if line:
            parts.append(line)
    return parts


def _brace_codes(body: str) -> tuple[tuple[int, ...], bool]:
    inserted = body.startswith("+")
    words = body.removeprefix("+").split()
    codes: list[int] = []
    position = 0
    while position < len(words):
        word = words[position]
        code = _CODES_BY_NAME.get(word)
        if code is None:
            code = _hex_code(word, body)
        codes.append(code)
        position += 1
        if code == PAGE:
            codes.append(NEWLINE)
        elif code in COMMANDS_WITH_ARGUMENT:
            if position == len(words):
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"FF6A command {word} needs its argument in the same braces: {{{body}}}",
                )
            codes.append(_hex_code(words[position], body))
            position += 1
    if not codes:
        raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, "Empty FF6A command {}")
    return tuple(codes), inserted


def _hex_code(word: str, body: str) -> int:
    try:
        return int(word, 16)
    except ValueError:
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown FF6A command {{{body}}}"
        ) from None


def ff6a_codes_notation(codes: Sequence[int], characters: Mapping[int, str]) -> str:
    """An original message (English codes) in the translators' notation.

    ``characters`` maps glyph codes back to ASCII (``Ff6aFont.character_codes``
    inverted); other glyphs are written as hex.
    """
    parts: list[str] = []
    position = 0
    while position < len(codes):
        code = codes[position]
        following = codes[position + 1] if position + 1 < len(codes) else None
        if code == NEWLINE:
            parts.append("\n")
            position += 1
        elif code <= LAST_GLYPH:
            character = characters.get(code)
            parts.append(character if character and character not in "{}" else f"{{{code:03X}}}")
            position += 1
        else:
            step = (
                2
                if code in COMMANDS_WITH_ARGUMENT or (code == PAGE and following == NEWLINE)
                else 1
            )
            parts.append("{" + " ".join(_code_words(codes[position : position + step])) + "}")
            position += step
    return "".join(parts)


def ff6a_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes 0x600 onwards for ``characters``: the glyphs appended to the dialogue font."""
    return assign_glyph_codes(
        characters,
        range(ARABIC_CODE_BASE, ARABIC_CODE_BASE + MAX_ARABIC_GLYPHS),
        what="FF6A Arabic glyphs",
    )


@lru_cache(maxsize=1)
def build_ff6a_arabic_glyph_map() -> GlyphCodes:
    # A wider word space than the Latin one; shaped forms come first.
    return ff6a_glyph_codes((*arabic_presentation_repertoire(), " "))


@dataclass(frozen=True, slots=True)
class Ff6aArabicFontResult:
    font: Ff6aFont
    font_size: int
    baseline: int
    widths: dict[str, int]
    max_advance: int

    @property
    def data(self) -> bytes:
        return self.font.build()


def build_ff6a_arabic_font(
    font_path: Path, *, glyph_map: GlyphCodes | None = None
) -> Ff6aArabicFontResult:
    """Rasterize every presentation form into 16-row FF6A glyphs with the game's shadow."""
    glyph_map = glyph_map or build_ff6a_arabic_glyph_map()
    outlined = tuple(character for character in glyph_map.characters if character != " ")
    font, size, baseline = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), outlined),
        range(18, 5, -1),
        lambda font: _baseline(font, outlined),
        "Selected font cannot fit the FF6A 16x15 Arabic glyph area",
    )

    glyphs: list[Ff6aGlyph] = []
    widths: dict[str, int] = {}
    for character in glyph_map.characters:
        if character == " ":
            advance = max(4, math.ceil(font.getlength(" ")))
            glyphs.append(Ff6aGlyph(advance, 1, (0,) * GLYPH_HEIGHT))
            widths[character] = advance
            continue
        ink, width = _rasterize(font, character, baseline)
        glyphs.append(_encode_glyph(character, ink, width))
        widths[character] = width

    return Ff6aArabicFontResult(
        font=Ff6aFont(
            height=GLYPH_HEIGHT,
            flags=2,
            ascii_map=(FONT_NO_GLYPH,) * FONT_ASCII_ENTRIES,
            glyphs=tuple(glyphs),
        ),
        font_size=size,
        baseline=baseline,
        widths=widths,
        max_advance=max(widths.values()),
    )


def _baseline(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> int | None:
    """The baseline row when the ink fits rows 0..14 (row 15 takes the shadow), else None."""
    ink_rows = GLYPH_HEIGHT - 1
    bounds = form_bounds(font, characters)
    if bounds.bottom - bounds.top > ink_rows or bounds.widest_ink > GLYPH_MAX_WIDTH - 1:
        return None
    # Share the Latin baseline when the descenders allow it.
    return max(min(LATIN_BASELINE, ink_rows - bounds.bottom), -bounds.top)


def _rasterize(
    font: ImageFont.FreeTypeFont, character: str, baseline: int
) -> tuple[frozenset[tuple[int, int]], int]:
    form = draw_form(font, character, baseline)
    if form.advance > GLYPH_MAX_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {form.advance}px; FF6A glyph rows hold 16",
        )
    if any(y >= GLYPH_HEIGHT - 1 for _, y in form.ink):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} reaches the shadow row",
        )
    return form.ink, form.advance


def _encode_glyph(character: str, ink: frozenset[tuple[int, int]], width: int) -> Ff6aGlyph:
    shadow = drop_shadow(ink, _SHADOW_OFFSETS, width, GLYPH_HEIGHT)
    row_bytes = math.ceil((max(x for x, _ in ink | shadow) + 1) / 4)
    if row_bytes > MAX_GLYPH_ROW_BYTES:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, f"Glyph U+{ord(character):04X} is wider than 16 pixels"
        )
    rows = two_bit_rows(
        ink,
        shadow,
        columns=row_bytes * 4,
        height=GLYPH_HEIGHT,
        ink_value=_PIXEL_INK,
        shadow_value=_PIXEL_SHADOW,
    )
    return Ff6aGlyph(width, row_bytes, rows)


def font_preview(result: Ff6aArabicFontResult) -> Image.Image:
    """Atlas of the generated glyphs: 16 per row, ink white, shadow blue, advance dark red."""
    glyphs = result.font.glyphs
    colours = {0: (0, 0, 0), _PIXEL_INK: (255, 255, 255), _PIXEL_SHADOW: (90, 90, 150)}

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = glyphs[index]
        value = glyph.pixel(x, y) if x < glyph.row_bytes * 4 else 0
        if value == 0 and x >= glyph.advance:
            return (70, 20, 20)
        return colours.get(value, (255, 0, 0))

    return glyph_atlas(len(glyphs), GLYPH_MAX_WIDTH, GLYPH_HEIGHT, colour)


@dataclass(frozen=True, slots=True)
class Ff6aArabicLine:
    page: int
    width: int
    centered: bool


@dataclass(frozen=True, slots=True)
class Ff6aArabicEncoding:
    codes: tuple[int, ...]
    lines: tuple[Ff6aArabicLine, ...]

    @property
    def data(self) -> bytes:
        return b"".join(encode_code(code) for code in self.codes)


class Ff6aArabicEncoder:
    """Convert logical Arabic token streams into FF6A code streams in paint order."""

    def __init__(
        self,
        *,
        arabic_widths: dict[str, int],
        latin_glyphs: dict[str, tuple[int, int]] | None = None,
        glyph_map: GlyphCodes | None = None,
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.glyph_map = glyph_map or build_ff6a_arabic_glyph_map()
        self.arabic_widths = dict(arabic_widths)
        self.latin_glyphs = dict(USA_LATIN_GLYPHS if latin_glyphs is None else latin_glyphs)

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        reject_combining_marks(stream, "FF6A Arabic font v1")
        reject_mirrored(stream, "FF6A Arabic v1")
        reject_text_newlines(stream, "Use explicit FF6A newline tokens instead of '\\n' in text")
        for token in stream.inline_tokens:
            for code in _commands(token_codes(token)):
                if code in RUNTIME_TEXT_COMMANDS:
                    raise ClassicRetroError(
                        ErrorCode.UNSUPPORTED_CONTROL_CODE,
                        f"FF6A Arabic v1 does not place runtime text {command_notation(code)}",
                    )
                if code == CHOICE:
                    raise ClassicRetroError(
                        ErrorCode.UNSUPPORTED_CONTROL_CODE,
                        "FF6A Arabic v1 does not mirror choice cursors",
                    )
            if is_inserted(token) and not _is_insertable(token_codes(token)):
                raise ClassicRetroError(
                    ErrorCode.TOKEN_DEFINITION_MISMATCH,
                    f"FF6A token {token.id} may only insert PAUSE+PAGE or KEY_PAGE",
                )
        return rtl_paint_order(self.pipeline, stream)

    def encode_message(self, stream: TokenStream, *, layout: str) -> Ff6aArabicEncoding:
        """Encode, then measure every line against the window and page capacity."""
        if layout not in Ff6aLayout.LINES:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT, f"Unknown FF6A layout {layout}"
            )
        pages = _PageLayout(layout)
        codes: list[int] = [RTL_MARKER]
        for token in self.prepare_paint_order(stream).tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    code, advance = self._glyph(character)
                    codes.append(code)
                    pages.add(advance)
                continue
            values = token_codes(token)
            position = 0
            while position < len(values):
                code = values[position]
                position += 1
                if code in COMMANDS_WITH_ARGUMENT:
                    if position >= len(values):
                        raise ClassicRetroError(
                            ErrorCode.UNENCODABLE_TOKEN,
                            f"{command_notation(code)} needs its argument in the same token",
                        )
                    position += 1
                elif code in {NEWLINE, END}:
                    pages.close_line()
                elif code == PAGE:
                    if values[position : position + 1] != (NEWLINE,):
                        raise ClassicRetroError(
                            ErrorCode.UNENCODABLE_TOKEN,
                            "FF6A PAGE must be followed by the newline the engine skips",
                        )
                    position += 1
                    pages.close_page()
                elif code == KEY_PAGE:
                    pages.close_page()
                elif code == CENTER:
                    pages.center()
                elif PORTRAIT_FIRST <= code <= PORTRAIT_LAST:
                    pages.margin = PORTRAIT_MARGIN
            codes.extend(values)
        if codes[-1] != END:
            raise ClassicRetroError(ErrorCode.MISSING_TERMINATOR, "FF6A message must end with END")
        return Ff6aArabicEncoding(codes=tuple(codes), lines=tuple(pages.lines))

    def _glyph(self, character: str) -> tuple[int, int]:
        code = self.glyph_map.code(character)
        if code is not None:
            return code, self.arabic_widths[character]
        latin = self.latin_glyphs.get(character)
        if latin is not None:
            return latin
        raise no_glyph(character, "FF6A Arabic")


def _commands(values: tuple[int, ...]) -> tuple[int, ...]:
    """Command codes of a token, without the argument codes that follow them."""
    commands: list[int] = []
    expect_argument = False
    for code in values:
        if expect_argument:
            expect_argument = False
            continue
        commands.append(code)
        expect_argument = code in COMMANDS_WITH_ARGUMENT
    return tuple(commands)


def _is_insertable(values: tuple[int, ...]) -> bool:
    return values == (KEY_PAGE,) or (
        len(values) == 4 and values[0] == PAUSE and values[2:] == (PAGE, NEWLINE)
    )


class _PageLayout:
    """Line widths and page capacity of one message, in paint order."""

    def __init__(self, layout: str) -> None:
        self.layout = layout
        self.max_lines = Ff6aLayout.LINES[layout]
        self.lines: list[Ff6aArabicLine] = []
        self.margin = 0
        self._page = 0
        self._page_lines = 0
        self._width = 0
        self._centered = False
        self._open = False

    def add(self, advance: int) -> None:
        self._width += advance
        self._open = True

    def center(self) -> None:
        if self._open:
            raise ClassicRetroError(
                ErrorCode.TOKEN_ORDER_VIOLATION, "FF6A CENTER must start a line"
            )
        self._centered = True

    def close_line(self) -> None:
        self._page_lines += 1
        if self._page_lines > self.max_lines:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Page {self._page + 1} has more than {self.max_lines} lines "
                f"for the {self.layout} layout",
            )
        limit = RIGHT_EDGE - (0 if self._centered else self.margin)
        if self._width > limit:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Line {len(self.lines) + 1} needs {self._width}px; the FF6A window has {limit}px",
            )
        self.lines.append(Ff6aArabicLine(self._page, self._width, self._centered))
        self._width = 0
        self._centered = False
        self._open = False

    def close_page(self) -> None:
        self.close_line()
        self._page += 1
        self._page_lines = 0


def validate_command_skeleton(source_skeleton: tuple[int, ...], stream: TokenStream) -> None:
    """The translation's commands, minus inserted pages, must equal the original's."""
    target = command_skeleton(
        tuple(
            code
            for token in stream.inline_tokens
            if not is_inserted(token)
            for code in token_codes(token)
        )
    )
    require_same_commands(
        "FF6A",
        tuple(source_skeleton),
        target,
        lambda codes: " ".join(command_notation(code) for code in codes),
    )
