"""Arabic support for the fourth-generation Pokémon text engine (Nintendo DS).

The ROM overlay (``classic_retro.rom.platinum_arabic``) turns the printer right
to left without changing how it moves its pen. The printer still lays a line
out from the left; on a right-to-left line, the hook draws each glyph at the
mirror of its pen on the window's width:

    x' = width - x - glyph's width

A line then starts at the window's right edge and grows leftwards, and the
typewriter reveals it from the right. A translated string holds its glyphs in
right-to-left paint order: the first glyph of a line is its rightmost one.

The right-to-left glyphs are added to the game's own fonts, after their 509
glyphs: codes from ``RTL_FIRST`` (``01FE``), which the game's fonts leave to
``?``. Every line that holds one is right to left. The build gives codes only
to the characters the script uses, in a fixed order (the menus' left arrow
first, then the space, the punctuation drawn here and the forms by code
point), so the same characters always get the same codes.

A run of the game's own glyphs inside a right-to-left line (a name the string
inserts, a Latin word) is drawn left to right, as a block at the mirror of the
run. The encoder therefore keeps the Latin runs of a translation in reading
order, and the Arabic text around them uses only right-to-left glyphs, its
spaces and punctuation included, so an inserted name never joins the text
around it.

Glyphs are up to 16 pixels wide and 16 rows tall, drawn from the reference
font at the largest size whose every form fits on the game's baseline (row
12), off the top row. Coverage from ``INK_LEVEL`` is the text colour (1); the
game's one-pixel shadow (2) goes right, down and down-right of the ink, inside
the glyph's advance so it never covers the neighbour on the right, which is
painted first. ``.``, ``!`` and ``:`` are drawn by hand like the game's own,
and so is the menus' left arrow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageFont

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import no_glyph
from classic_retro.arabic.paint import reject_combining_marks, reject_mirrored, rtl_paint_order
from classic_retro.arabic.repertoire import arabic_presentation_repertoire, legacy_renderer_pipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen4 import (
    CLEAR,
    EOS,
    LATIN,
    NEWLINE,
    SCROLL,
    YESNO,
    Gen4Command,
    Gen4Font,
    Gen4Line,
    Piece,
    Pixels,
    encode_text,
    lay_out,
    notation_skeleton,
)
from classic_retro.font.arabic_outline import contextual_font_data
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    arabic_font_file,
    draw_form,
    drop_shadow,
    largest_fitting_size,
    pattern_pixels,
    raised_form,
)
from classic_retro.font.previews import glyph_atlas, pages_right_to_left, preview_sheet
from classic_retro.text.commands import command_codes, command_token, require_same_commands
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream

INK = 1
SHADOW = 2
BASELINE = 12
INK_LEVEL = 110
SIZES = range(16, 7, -1)
# A right-to-left glyph: up to 16 pixels wide, 16 rows tall, off the top row.
GLYPH_COLUMNS = 16
GLYPH_ROWS = 16
TOP_ROW = 1
SHADOW_OFFSETS = ((1, 0), (0, 1), (1, 1))
# The codes after the fonts' 509 glyphs, up to the Korean codes at 0400; the
# hooks read the same range as right to left.
RTL_FIRST = 0x01FE
RTL_END = 0x0400
RTL_GLYPH_CODES = tuple(range(RTL_FIRST, RTL_END))
# The menus' cursor for a right-to-left menu, at RTL_FIRST in every build.
LEFT_ARROW = "◀"
SPACE_WIDTH = 4
# Drawn by hand, on the baseline, like the game's own punctuation.
_HAND_DRAWN: dict[str, tuple[int, tuple[str, ...]]] = {
    ".": (BASELINE - 2, ("##", "##")),
    "!": (BASELINE - 10, ("#", "#", "#", "#", "#", "#", ".", ".", "#", "#")),
    ":": (BASELINE - 7, ("##", "##", "..", "..", "..", "##", "##")),
    LEFT_ARROW: (
        BASELINE - 9,
        ("....#", "...##", "..###", ".####", "#####", ".####", "..###", "...##", "....#"),
    ),
}
# The tails of final and isolated meem and yeh reach below the cell: these forms
# go up, a row at a time, up to two rows.
_RAISED_FORMS = frozenset("ﻡﻢﻱﻲ")
_RAISE_LIMIT = 2
# A name the string inserts (a player's or a rival's): up to 7 of the game's
# letters, 6 pixels each, and some room.
NAME_WIDTH = 48
# The touch-screen icon's width, at the left edge of a right-to-left window.
ICON_WIDTH = 24


def glyph_characters() -> tuple[str, ...]:
    """Every character the right-to-left glyphs can draw, in the order codes follow."""
    return (LEFT_ARROW, " ", ".", "!", ":", *arabic_presentation_repertoire())


def gen4_glyph_codes(characters: Iterable[str]) -> GlyphCodes:
    """Codes for the characters a script uses (and the left arrow, always at ``RTL_FIRST``)."""
    used = {*characters, LEFT_ARROW}
    order = glyph_characters()
    unknown = sorted(used - set(order))
    if unknown:
        raise no_glyph(unknown[0], "Pokémon Gen 4 Arabic")
    return assign_glyph_codes(
        (character for character in order if character in used),
        RTL_GLYPH_CODES,
        what="Pokémon Gen 4 Arabic glyphs",
    )


@dataclass(frozen=True, slots=True)
class Gen4RtlGlyph:
    """A right-to-left glyph: its advance and 16 rows of 16 pixels (0, 1 ink, 2 shadow)."""

    width: int
    pixels: Pixels


def rtl_glyph(ink: Iterable[tuple[int, int]], width: int) -> Gen4RtlGlyph:
    """A glyph of ``width`` from its ink; the shadow follows the game's, inside the advance."""
    ink = set(ink)
    if not 1 <= width <= GLYPH_COLUMNS:
        raise FormDoesNotFit
    if any(not (0 <= x < width and TOP_ROW <= y < GLYPH_ROWS) for x, y in ink):
        raise FormDoesNotFit
    shadow = drop_shadow(ink, SHADOW_OFFSETS, width, GLYPH_ROWS)
    pixels = tuple(
        tuple(
            INK if (x, y) in ink else SHADOW if (x, y) in shadow else 0
            for x in range(GLYPH_COLUMNS)
        )
        for y in range(GLYPH_ROWS)
    )
    return Gen4RtlGlyph(width, pixels)


@dataclass(frozen=True, slots=True)
class Gen4RtlFont:
    """Every right-to-left glyph by code, and each character's code."""

    glyphs: dict[int, Gen4RtlGlyph]
    sequences: dict[str, tuple[int, ...]]
    font_size: int

    def width(self, code: int) -> int:
        return self.glyphs[code].width

    def extend(self, font: Gen4Font) -> Gen4Font:
        """``font`` with these glyphs after its own, which must end just before ``RTL_FIRST``."""
        if font.count != RTL_FIRST - 1:
            raise ClassicRetroError(
                ErrorCode.FONT_BUILD_FAILED,
                f"The font has {font.count} glyphs; the right-to-left codes need {RTL_FIRST - 1}",
            )
        if font.tiles_wide * 8 != GLYPH_COLUMNS or font.tiles_high * 8 != GLYPH_ROWS:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "The font's cell is not 16x16")
        last = max(self.glyphs)
        blank = Gen4RtlGlyph(0, tuple((0,) * GLYPH_COLUMNS for _ in range(GLYPH_ROWS)))
        glyphs = [self.glyphs.get(code, blank) for code in range(RTL_FIRST, last + 1)]
        return font.with_glyphs([(glyph.pixels, glyph.width) for glyph in glyphs])


def build_gen4_rtl_font(
    font_path: Path, glyph_map: GlyphCodes, *, sizing: Iterable[str] | None = None
) -> Gen4RtlFont:
    """Rasterize the forms ``glyph_map`` holds and add the space and the hand-drawn glyphs.

    The size is the largest where every form of ``sizing`` fits: the whole
    repertoire by default, so a new word never changes the size of the others.
    """
    used = {
        character
        for character in glyph_map.characters
        if character != " " and character not in _HAND_DRAWN
    }
    sized = set(arabic_presentation_repertoire() if sizing is None else sizing)
    drawn = tuple(sorted(sized | used, key=ord))
    _, size, rendered = largest_fitting_size(
        contextual_font_data(arabic_font_file(font_path), drawn),
        SIZES,
        lambda font: _glyphs(font, drawn),
        "Selected font cannot fit the Pokémon Gen 4 16x16 glyphs",
    )
    rendered[" "] = rtl_glyph((), SPACE_WIDTH)
    for character, (top, rows) in _HAND_DRAWN.items():
        rendered[character] = rtl_glyph(pattern_pixels(rows, top=top), len(rows[0]) + 2)
    glyphs: dict[int, Gen4RtlGlyph] = {}
    sequences: dict[str, tuple[int, ...]] = {}
    for character in glyph_map.characters:
        codes = glyph_map.sequence(character)
        assert codes is not None
        sequences[character] = codes
        glyphs[codes[0]] = rendered[character]
    return Gen4RtlFont(glyphs=glyphs, sequences=sequences, font_size=size)


def _glyphs(
    font: ImageFont.FreeTypeFont, characters: Sequence[str]
) -> dict[str, Gen4RtlGlyph] | None:
    """Every form at this size, or None when one leaves its 16x16 glyph."""
    try:
        rendered = {
            character: draw_form(font, character, BASELINE, ink_level=INK_LEVEL)
            for character in characters
        }
        for character in _RAISED_FORMS & set(rendered):
            for _ in range(_RAISE_LIMIT):
                rendered[character] = raised_form(
                    character, rendered[character], height=GLYPH_ROWS - 1, baseline=BASELINE
                )
        return {character: _glyph(form) for character, form in rendered.items()}
    except FormDoesNotFit:
        return None


def _glyph(form: DrawnForm) -> Gen4RtlGlyph:
    # The shadow needs the row under the lowest ink.
    if max(y for _, y in form.ink) >= GLYPH_ROWS - 1:
        raise FormDoesNotFit
    return rtl_glyph(form.ink, form.advance)


# ---------------------------------------------------------------------------
# Encoding translated strings

# The width of a code of the game's own font.
GameWidth = Callable[[int], int]


# Commands a translation may hold: line breaks, the string variables (names)
# and the touch-screen icon.
def _supported(command: Gen4Command) -> bool:
    return command.is_break or command.is_string_variable or command.code == YESNO


def arabic_command_token(token_id: str, command: Gen4Command) -> InlineToken:
    if command.code == NEWLINE:
        kind = TokenKind.LINE_BREAK
    elif command.code in (CLEAR, SCROLL):
        kind = TokenKind.PAGE_BREAK
    elif command.is_string_variable:
        kind = TokenKind.VARIABLE
    else:
        kind = TokenKind.CONTROL
    codes = " ".join(f"{code:04x}" for code in command.codes)
    return command_token(token_id, kind, codes, name=command.notation)


def paint_stream(pieces: Sequence[Piece]) -> TokenStream:
    """A string in right-to-left paint order."""
    for piece in pieces:
        if isinstance(piece, Gen4Command) and not _supported(piece):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"Pokémon Gen 4 Arabic v1 does not support {piece.notation}",
            )
    tokens: list[TextToken | InlineToken] = []
    for number, piece in enumerate(pieces):
        if isinstance(piece, str):
            tokens.append(TextToken(piece))
        else:
            tokens.append(arabic_command_token(f"t{number}", piece))
    stream = TokenStream(tuple(tokens))
    reject_mirrored(stream, "Pokémon Gen 4 Arabic v1")
    reject_combining_marks(stream, "Pokémon Gen 4 Arabic font v1")
    return rtl_paint_order(legacy_renderer_pipeline(), stream)


def painted_characters(pieces: Sequence[Piece]) -> set[str]:
    """The characters of a string that the right-to-left glyphs draw."""
    order = set(glyph_characters())
    return {
        character
        for token in paint_stream(pieces).tokens
        if isinstance(token, TextToken)
        for character in token.text
        if character in order or not _is_latin(character)
    }


def _is_latin(character: str) -> bool:
    """A letter or digit of the game's own font, kept in a left-to-right run."""
    return character.isalnum() and character in LATIN.values()


@dataclass(frozen=True, slots=True)
class Gen4ArabicEncoding:
    """A translated string's codes (with its ``FFFF``) and, with a font, its lines."""

    codes: tuple[int, ...]
    lines: tuple[Gen4Line, ...] | None

    @property
    def line_widths(self) -> tuple[int, ...] | None:
        return None if self.lines is None else tuple(line.width for line in self.lines)


@dataclass(frozen=True, slots=True)
class Gen4Window:
    """Where a string is shown: the window's width and rows, and its kind.

    ``dialogue`` is the message box (pages, scrolling); ``block`` is text shown
    at once, whose lines are the original's (``fixed_lines``) or free; ``menu``
    is one entry of a list, drawn from ``text_x`` with the cursor beside it.
    """

    kind: str
    width: int
    rows: int
    text_x: int = 0


class Gen4ArabicEncoder:
    """Convert logical Arabic text into Gen 4 codes in right-to-left paint order."""

    def __init__(self, glyph_map: GlyphCodes, font: Gen4RtlFont | None = None) -> None:
        self.sequences: Mapping[str, tuple[int, ...]] = glyph_map.sequences
        self.font = font

    def encode(
        self, pieces: Sequence[Piece], window: Gen4Window, *, game_width: GameWidth | None = None
    ) -> Gen4ArabicEncoding:
        codes: list[int] = []
        for token in paint_stream(pieces).tokens:
            if isinstance(token, TextToken):
                codes.extend(self._text(token.text))
            else:
                codes.extend(command_codes(token, "Pokémon Gen 4"))
        codes = _reading_order_runs(codes)
        codes.append(EOS)
        lines = lay_out(codes, self._width(game_width), rows=window.rows, name_width=NAME_WIDTH)
        self._check_lines(lines, window)
        if self.font is None:
            return Gen4ArabicEncoding(tuple(codes), None)
        for number, line in enumerate(lines, 1):
            limit = window.width - window.text_x - (ICON_WIDTH if line.icon else 0)
            if line.width > limit:
                raise ClassicRetroError(
                    ErrorCode.TEXT_BOX_OVERFLOW,
                    f"Line {number} needs {line.width}px; the window holds {limit}px",
                )
        return Gen4ArabicEncoding(tuple(codes), lines)

    @staticmethod
    def _check_lines(lines: Sequence[Gen4Line], window: Gen4Window) -> None:
        if window.kind == "menu" and len(lines) != 1:
            raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, "A menu entry is one line")
        if window.kind == "block" and any(line.page for line in lines):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, "Text shown at once has no pages"
            )

    def _text(self, text: str) -> list[int]:
        codes: list[int] = []
        for character in text:
            sequence = self.sequences.get(character)
            if sequence is not None:
                codes.extend(sequence)
            elif _is_latin(character):
                codes.extend(encode_text(character))
            else:
                raise no_glyph(character, "Pokémon Gen 4 Arabic")
        return codes

    def _width(self, game_width: GameWidth | None) -> Callable[[int], int]:
        def width(code: int) -> int:
            if RTL_FIRST <= code < RTL_END:
                return self.font.width(code) if self.font is not None else 0
            return game_width(code) if game_width is not None else 6

        return width


def _reading_order_runs(codes: Sequence[int]) -> list[int]:
    """Paint order with every run of the game's glyphs back in reading order.

    The hooks draw such a run left to right as a block, which puts it back
    where paint order had it. A command ends a run.
    """
    output: list[int] = []
    run: list[int] = []
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0xFFFE:
            length = 3 + codes[index + 2]
            output.extend(reversed(run))
            run.clear()
            output.extend(codes[index : index + length])
            index += length
            continue
        if code in (NEWLINE, CLEAR, SCROLL) or RTL_FIRST <= code < RTL_END:
            output.extend(reversed(run))
            run.clear()
            output.append(code)
        else:
            run.append(code)
        index += 1
    output.extend(reversed(run))
    return output


def validate_command_skeleton(source: tuple[str, ...], pieces: Sequence[Piece]) -> None:
    """The translation's commands must equal the original's; only line ends may move."""
    require_same_commands("Pokémon Gen 4", source, notation_skeleton(pieces), "".join)


# ---------------------------------------------------------------------------
# Previews

# The message box: dark grey ink and light grey shadow on white; a text block:
# white on the intro's blue; a name the game inserts is a grey box.
DIALOGUE_COLOURS = {0: (248, 248, 248), INK: (72, 72, 72), SHADOW: (192, 192, 200)}
BLOCK_COLOURS = {0: (56, 72, 200), INK: (248, 248, 248), SHADOW: (40, 40, 120)}
NAME_COLOUR = (180, 160, 120)
ICON_COLOUR = (200, 80, 60)
PREVIEW_MARGIN = 4


def font_preview(font: Gen4RtlFont) -> Image.Image:
    """Atlas of the right-to-left glyphs: ink white, shadow grey, width dark red, baseline blue."""
    codes = sorted(font.glyphs)

    def colour(index: int, x: int, y: int) -> tuple[int, int, int]:
        glyph = font.glyphs[codes[index]]
        value = glyph.pixels[y][x]
        if value == INK:
            return (255, 255, 255)
        if value == SHADOW:
            return (120, 120, 120)
        if x >= glyph.width:
            return (70, 20, 20)
        if y == BASELINE:
            return (20, 20, 70)
        return (0, 0, 0)

    return glyph_atlas(len(codes), GLYPH_COLUMNS, GLYPH_ROWS, colour)


def message_preview(
    font: Gen4RtlFont, lines: Sequence[Gen4Line], window: Gen4Window
) -> Image.Image:
    """A translated string as its window shows it: screens side by side, the first on the right.

    A new page or a scroll starts a screen; after a scroll the rows above move
    up a row. Every line ends at the window's right edge (less the menu's
    margin) and grows leftwards; a name is a box as wide as the widest name.
    """
    colours = BLOCK_COLOURS if window.kind == "block" else DIALOGUE_COLOURS
    rows = window.rows if window.kind == "dialogue" else max(line.row for line in lines) + 1
    screens: list[list[Gen4Line]] = []
    shown: list[Gen4Line] = []
    page = 0
    for line in lines:
        if line.page != page or line.scrolled:
            screens.append(shown)
            if line.page != page:
                shown = []
            else:
                shown = [replace(old, row=old.row - 1) for old in shown if old.row > 0]
            page = line.page
        shown.append(line)
    screens.append(shown)
    screens = [screen for screen in screens if any(line.places for line in screen)]
    size = (window.width + 2 * PREVIEW_MARGIN, rows * GLYPH_ROWS + 2 * PREVIEW_MARGIN)
    images = []
    for screen in screens:
        image = Image.new("RGB", size, colours[0])
        for line in screen:
            _draw_line(image, font, line, window, colours)
        images.append(image)
    return pages_right_to_left(images or [Image.new("RGB", size, colours[0])])


def _draw_line(
    image: Image.Image,
    font: Gen4RtlFont,
    line: Gen4Line,
    window: Gen4Window,
    colours: Mapping[int, tuple[int, int, int]],
) -> None:
    top = PREVIEW_MARGIN + line.row * GLYPH_ROWS
    right = PREVIEW_MARGIN + window.width - window.text_x
    if line.icon:
        for y in range(2 * GLYPH_ROWS):
            for x in range(ICON_WIDTH):
                if (x + y) % 6 == 0:
                    image.putpixel((PREVIEW_MARGIN + x, PREVIEW_MARGIN + y), ICON_COLOUR)
    for place in line.places:
        left = right - place.end
        if place.code is None or not RTL_FIRST <= place.code < RTL_END:
            for y in range(3, 13):
                for x in range(place.width - 1):
                    image.putpixel((left + x, top + y), NAME_COLOUR)
            continue
        for y, values in enumerate(font.glyphs[place.code].pixels):
            for x, value in enumerate(values[: place.width]):
                if value:
                    image.putpixel((left + x, top + y), colours[value])


def messages_sheet(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Previews one under another, each with its key on the left."""
    return preview_sheet(images, 180)
