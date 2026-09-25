"""Arabic support for the Fire Emblem talk renderer (*The Sacred Stones*, USA).

The ROM overlay (``classic_retro.rom.fire_emblem_arabic``) adds:

- ``0x1E`` as the first byte of a message: right-to-left mode. When a talk
  (dialogue bubbles or the world map's narration box) starts with it, the
  hooks skip it and set bit 15 of the talk flags; while it is set, glyph
  widths and bitmaps come from the right-to-left table and every glyph is
  drawn at the mirrored position of the typewriter cursor.
- the right-to-left glyph table, 256 pointers like the game's own: the game's
  talk glyphs ``0x21..0x7E`` moved onto the Arabic baseline, a 4-pixel space,
  the zero-width pacing glyph ``0x1F`` and the Arabic presentation forms at
  ``0x82 + slot``. ``0x80`` and ``0x81`` stay command prefixes.

Every glyph is 16 rows of 16 two-bit pixels, as in the game: 3 is ink and 2
the light shade the game's font puts right of its strokes (it never leaves
the glyph's own width, so joined letters touch without overlapping).

Translations stay logical Unicode Arabic in the engine's bracket notation;
this module shapes them, resolves bidi per segment and stores every line in
right-to-left paint order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
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
from classic_retro.engines.fire_emblem import (
    CHOICE_COMMANDS,
    CLEAR,
    END,
    EXTENDED,
    FIRST_GLYPH,
    LINE_FEED,
    PACE,
    RUNTIME_TEXT_COMMANDS,
    TAB,
    TAB_PREFIX,
    WAIT_KEY,
    FireEmblemFont,
    FireEmblemGlyph,
    command_notation,
    command_skeleton,
    skeleton_notation,
    split_notation,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    arabic_font_file,
    draw_form,
    drawn_mark,
    drop_shadow,
    form_bounds,
    largest_fitting_size,
    two_bit_rows,
)
from classic_retro.font.previews import glyph_atlas
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

RTL_MARKER = 0x1E
ARABIC_CODE_BASE = 0x82
LAST_ARABIC_CODE = 0xFE
TABLE_ENTRIES = 0x100
FALLBACK_CODE = ord("?")

CELL_HEIGHT = 16
CELL_WIDTH = 16
# Arabic letters end on row 10 (the anchor sits on row 11); their ink uses
# rows 1..15. The game's Latin glyphs end on row 13 and move up three rows.
BASELINE = 11
LATIN_ROW_SHIFT = -3
PIXEL_INK = 3
PIXEL_SHADE = 2

SPACE = 0x20
SPACE_ADVANCE = 4
# The game sizes a bubble with 12 extra pixels per [A] for the key arrow.
WAIT_KEY_ALLOWANCE = 12
TAB_ADVANCE = 6

# Arabic-Indic digits have no code left; translations use Western digits.
_EXCLUDED = frozenset(chr(code) for code in range(0x0660, 0x066A))
# At 10 pixels the reference font draws the Arabic comma as two pixels; these
# follow its slanted Kufi comma at a readable size (rows end on the baseline).
_PUNCTUATION_INK: dict[str, tuple[str, ...]] = {
    "،": (".#", ".#", "#.", "#."),
    "؛": (".#", ".#", "#.", "#.", "..", "#.", "#."),
}
# Advances of the talk glyphs 0x21..0x7E (USA) that keep all their ink once
# moved onto the Arabic baseline. The ROM build compares this table with the
# font it reads before using it.
USA_TALK_ADVANCES: dict[str, int] = {
    "!": 3, "#": 8, "$": 6, "%": 8, "&": 7, "(": 4, ")": 4, "*": 8, "+": 8, ",": 2, "-": 4,
    ".": 2, "0": 6, "1": 4, "2": 6, "3": 6, "4": 7, "5": 6, "6": 6, "7": 6, "8": 6, "9": 6,
    ":": 2, ";": 2, "<": 6, "=": 6, ">": 6, "?": 7, "@": 8, "A": 6, "B": 6, "C": 6, "D": 6,
    "E": 6, "F": 6, "G": 6, "H": 6, "I": 4, "J": 6, "K": 6, "L": 5, "M": 8, "N": 6, "O": 6,
    "P": 6, "Q": 7, "R": 6, "S": 7, "T": 6, "U": 6, "V": 6, "W": 8, "X": 6, "Y": 6, "Z": 6,
    "[": 3, "\\": 8, "]": 3, "_": 4, "a": 6, "b": 5, "c": 5, "d": 5, "e": 5, "f": 5, "g": 7,
    "h": 5, "i": 2, "j": 3, "k": 5, "l": 2, "m": 6, "n": 5, "o": 5, "p": 5, "q": 5, "r": 4,
    "s": 5, "t": 5, "u": 5, "v": 6, "w": 6, "x": 6, "y": 4, "z": 5, "{": 4, "|": 2, "}": 4,
    "~": 7,
}  # fmt: skip


class TalkBox(StrEnum):
    """Where a message is shown, which decides the widest line it may hold."""

    BUBBLE = "bubble"
    WORLD_MAP = "world-map"


# Text width of a line including the key arrow allowance: a bubble is at most
# 28 tiles (26 for text) wide to stay on screen whatever the speaker's slot,
# and the world map's box clears 27 tiles (216 pixels) of each line.
LINE_WIDTH: dict[TalkBox, int] = {TalkBox.BUBBLE: 208, TalkBox.WORLD_MAP: 216}

# Commands that end a line on screen: newline, box clear, speaker changes,
# bubble close and the end of the message.
_LINE_ENDS = frozenset({END, LINE_FEED, CLEAR, 0x11, 0x15, *range(0x08, 0x10)})


def fire_emblem_command(token_id: str, command: bytes) -> InlineToken:
    """An ordered engine command (with its arguments) inside a translation."""
    if not command:
        raise ValueError("a Fire Emblem command needs at least one byte")
    if command[0] == LINE_FEED:
        kind = TokenKind.LINE_BREAK
    elif command[0] == CLEAR:
        kind = TokenKind.PAGE_BREAK
    else:
        kind = TokenKind.CONTROL
    return command_token(
        token_id, kind, command.hex(" "), name=command_notation(command).strip("[]")
    )


def fire_emblem_stream(notation: str, prefix: str = "t") -> TokenStream:
    """A translation in bracket notation as a token stream."""
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(split_notation(notation)):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(fire_emblem_command(f"{prefix}{number}", piece))
    return TokenStream(tuple(tokens))


def token_command(token: InlineToken) -> bytes:
    return bytes(command_codes(token, "Fire Emblem"))


def fire_emblem_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes 0x82..0xFE for ``characters``: the byte codes the talk font leaves free."""
    return assign_glyph_codes(
        characters, range(ARABIC_CODE_BASE, LAST_ARABIC_CODE + 1), what="Fire Emblem Arabic glyphs"
    )


@lru_cache(maxsize=1)
def build_fire_emblem_arabic_glyph_map() -> GlyphCodes:
    return fire_emblem_glyph_codes(
        character for character in arabic_presentation_repertoire() if character not in _EXCLUDED
    )


def _encode_rows(
    ink: set[tuple[int, int]] | frozenset[tuple[int, int]], width: int
) -> FireEmblemGlyph:
    shade = drop_shadow(ink, ((1, 0),), min(width, CELL_WIDTH), CELL_HEIGHT)
    rows = two_bit_rows(
        ink,
        shade,
        columns=CELL_WIDTH,
        height=CELL_HEIGHT,
        ink_value=PIXEL_INK,
        shadow_value=PIXEL_SHADE,
    )
    return FireEmblemGlyph(width, rows)


@dataclass(frozen=True, slots=True)
class FireEmblemRtlFont:
    """The right-to-left glyph table: code -> glyph."""

    glyphs: dict[int, FireEmblemGlyph]
    font_size: int
    arabic_widths: dict[str, int]

    def advances(self) -> dict[int, int]:
        """Width per code for the encoder: the glyphs plus the pinned Latin table."""
        advances = {ord(character): width for character, width in USA_TALK_ADVANCES.items()}
        advances.update((code, glyph.width) for code, glyph in self.glyphs.items())
        return advances

    def data(self, address: int) -> bytes:
        """256 glyph pointers, then the glyphs (72 bytes each) they point to."""
        if FALLBACK_CODE not in self.glyphs:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH, "The right-to-left table needs the '?' fallback glyph"
            )
        pointers = bytearray(4 * TABLE_ENTRIES)
        glyphs = bytearray()
        first = address + len(pointers)
        for code in sorted(self.glyphs):
            pointers[4 * code : 4 * code + 4] = (first + len(glyphs)).to_bytes(4, "little")
            glyphs += self.glyphs[code].encode()
        return bytes(pointers + glyphs)


def latin_rtl_glyphs(font: FireEmblemFont) -> dict[int, FireEmblemGlyph]:
    """The game's talk glyphs 0x21..0x7E that keep their ink on the Arabic baseline."""
    glyphs: dict[int, FireEmblemGlyph] = {}
    for code in range(FIRST_GLYPH + 1, 0x7F):
        source = font.glyphs.get(code)
        if source is None or source.width > CELL_WIDTH:
            continue
        rows = [0] * CELL_HEIGHT
        kept = True
        for y, row in enumerate(source.rows):
            if not row:
                continue
            if 0 <= y + LATIN_ROW_SHIFT < CELL_HEIGHT:
                rows[y + LATIN_ROW_SHIFT] = row
            else:
                kept = False
        if kept:
            glyphs[code] = FireEmblemGlyph(source.width, tuple(rows))
    return glyphs


def build_fire_emblem_rtl_font(
    font_path: Path,
    talk: FireEmblemFont | None = None,
    *,
    glyph_map: GlyphCodes | None = None,
) -> FireEmblemRtlFont:
    """Rasterize the Arabic forms into 16x16 cells and add the game's own Latin glyphs."""
    glyph_map = glyph_map or build_fire_emblem_arabic_glyph_map()
    outlined = tuple(c for c in glyph_map.characters if c not in _PUNCTUATION_INK)
    font, size, _ = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), outlined),
        range(14, 5, -1),
        lambda font: _fits(font, outlined),
        "Selected font cannot fit the Fire Emblem 16x15 glyph area",
    )
    glyphs: dict[int, FireEmblemGlyph] = latin_rtl_glyphs(talk) if talk is not None else {}
    if talk is None:
        glyphs[FALLBACK_CODE] = _encode_rows(set(), USA_TALK_ADVANCES["?"])
    glyphs[PACE] = FireEmblemGlyph(0, (0,) * CELL_HEIGHT)
    glyphs[SPACE] = FireEmblemGlyph(SPACE_ADVANCE, (0,) * CELL_HEIGHT)
    widths: dict[str, int] = {}
    for character in glyph_map.characters:
        if character in _PUNCTUATION_INK:
            ink, width = drawn_mark(_PUNCTUATION_INK[character], BASELINE)
        else:
            ink, width = _rasterize(font, character)
        code = glyph_map.code(character)
        assert code is not None
        glyphs[code] = _encode_rows(ink, width)
        widths[character] = width
    return FireEmblemRtlFont(glyphs=glyphs, font_size=size, arabic_widths=widths)


def _fits(font: ImageFont.FreeTypeFont, characters: Sequence[str]) -> bool | None:
    """Whether the ink fits rows 1..15 around the row-11 anchor, narrower than a cell."""
    bounds = form_bounds(font, characters)
    if (
        BASELINE + bounds.top >= 1
        and BASELINE + bounds.bottom <= CELL_HEIGHT
        and bounds.widest_ink < CELL_WIDTH
    ):
        return True
    return None


def _rasterize(
    font: ImageFont.FreeTypeFont, character: str
) -> tuple[frozenset[tuple[int, int]], int]:
    form = draw_form(font, character, BASELINE)
    if form.advance > CELL_WIDTH:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            f"Glyph U+{ord(character):04X} needs {form.advance}px; a Fire Emblem glyph holds 16",
        )
    return form.ink, form.advance


def font_preview(font: FireEmblemRtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, shade grey, width dark red."""
    codes = sorted(font.glyphs)
    colours = {0: (0, 0, 0), PIXEL_INK: (255, 255, 255), PIXEL_SHADE: (130, 130, 150)}

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixel(x, y)
        if value == 0 and x >= glyph.width:
            return (70, 20, 20)
        return colours.get(value, (255, 0, 0))

    return glyph_atlas(len(codes), CELL_WIDTH, CELL_HEIGHT, colour)


@dataclass(frozen=True, slots=True)
class FireEmblemArabicLine:
    width: int


@dataclass(frozen=True, slots=True)
class FireEmblemArabicEncoding:
    data: bytes
    lines: tuple[FireEmblemArabicLine, ...]


class FireEmblemArabicEncoder:
    """Convert logical Arabic token streams into Fire Emblem bytes in paint order."""

    def __init__(
        self,
        *,
        advances: dict[int, int],
        glyph_map: GlyphCodes | None = None,
    ) -> None:
        self.pipeline = legacy_renderer_pipeline()
        self.glyph_map = glyph_map or build_fire_emblem_arabic_glyph_map()
        self.advances = dict(advances)

    def prepare_paint_order(self, stream: TokenStream) -> TokenStream:
        reject_combining_marks(stream, "Fire Emblem Arabic font v1")
        reject_mirrored(stream, "Fire Emblem Arabic v1")
        reject_text_newlines(stream, "Use [LF] tokens instead of '\\n' in Fire Emblem text")
        for token in stream.inline_tokens:
            command = token_command(token)
            if command[0] == EXTENDED and len(command) == 2 and command[1] in RUNTIME_TEXT_COMMANDS:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Fire Emblem Arabic v1 does not place {command_notation(command)}",
                )
            if command[0] in CHOICE_COMMANDS:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Fire Emblem Arabic v1 does not draw the {command_notation(command)} choice",
                )
            if (
                command[0] == RTL_MARKER
                or command[0] >= FIRST_GLYPH
                and command[0]
                not in (
                    EXTENDED,
                    TAB_PREFIX,
                )
            ):
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TOKEN,
                    f"Fire Emblem token {token.id} is not a command",
                )
        return rtl_paint_order(self.pipeline, stream)

    def encode_message(self, stream: TokenStream, box: TalkBox) -> FireEmblemArabicEncoding:
        """Encode, then measure every line against the box it is shown in."""
        limit = LINE_WIDTH[box]
        data = bytearray((RTL_MARKER,))
        lines: list[FireEmblemArabicLine] = []
        width = 0
        drawn = False

        def close_line() -> None:
            nonlocal width, drawn
            if drawn or width:
                if width > limit:
                    raise ClassicRetroError(
                        ErrorCode.TEXT_BOX_OVERFLOW,
                        f"Line {len(lines) + 1} needs {width}px; a Fire Emblem {box} "
                        f"line holds {limit}px",
                    )
                lines.append(FireEmblemArabicLine(width))
            width = 0
            drawn = False

        ended = False
        for token in self.prepare_paint_order(stream).tokens:
            if ended:
                raise ClassicRetroError(
                    ErrorCode.TOKEN_ORDER_VIOLATION, "Fire Emblem text after the end of the message"
                )
            if isinstance(token, TextToken):
                for character in token.text:
                    code = self.code(character)
                    data.append(code)
                    width += self.advances[code]
                    drawn = True
                continue
            command = token_command(token)
            data += command
            if command == bytes((TAB_PREFIX, TAB)):
                width += TAB_ADVANCE
            elif command[0] == WAIT_KEY:
                width += WAIT_KEY_ALLOWANCE
            elif command[0] == PACE:
                drawn = True
            elif command[0] in _LINE_ENDS:
                close_line()
                ended = command[0] == END
        if not ended:
            raise ClassicRetroError(
                ErrorCode.MISSING_TERMINATOR, "Fire Emblem message must end with [X]"
            )
        return FireEmblemArabicEncoding(data=bytes(data), lines=tuple(lines))

    def code(self, character: str) -> int:
        if character == " ":
            return SPACE
        code = self.glyph_map.code(character)
        if code is None and character.isascii() and ord(character) > SPACE:
            code = ord(character)
        if code is not None and code in self.advances:
            return code
        if character in _EXCLUDED:
            raise ClassicRetroError(
                ErrorCode.MISSING_GLYPH,
                "Fire Emblem Arabic v1 has no Arabic-Indic digits; use 0-9",
            )
        raise no_glyph(character, "Fire Emblem Arabic")


def validate_command_skeleton(source_skeleton: tuple[bytes, ...], stream: TokenStream) -> None:
    """The translation's commands must equal the original's; only [LF] and [.] may move."""
    # Text becomes placeholder glyphs so that adjacency ([CR][LF]) is preserved.
    layout = b"".join(
        token_command(token) if isinstance(token, InlineToken) else b"a" * len(token.text)
        for token in stream.tokens
    )
    require_same_commands(
        "Fire Emblem", source_skeleton, command_skeleton(layout), skeleton_notation
    )
