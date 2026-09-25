"""The shared Arabic core: glyph drawing, codes, tiles, previews and text checks."""

from __future__ import annotations

from io import BytesIO

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image

from classic_retro.arabic.glyph_codes import GlyphCodes, assign_glyph_codes
from classic_retro.arabic.logical import (
    DIRECTION_CONTROLS,
    EXPLICIT_DIRECTION_CONTROLS,
    check_logical_arabic,
    is_arabic_letter,
    is_presentation_form,
    no_glyph,
)
from classic_retro.arabic.paint import reject_mirrored, reject_text_newlines
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.glyph_raster import (
    DrawnForm,
    FormDoesNotFit,
    alef_with_mark,
    arabic_font_file,
    draw_form,
    drawn_mark,
    drop_shadow,
    form_bounds,
    largest_fitting_size,
    pattern_pixels,
    sized_font,
    two_bit_rows,
)
from classic_retro.font.previews import (
    enlarged_preview_sheet,
    glyph_atlas,
    pages_right_to_left,
    preview_sheet,
)
from classic_retro.font.tiles import pack_4bpp, unpack_4bpp
from classic_retro.text.commands import (
    command_codes,
    command_token,
    is_inserted,
    require_same_commands,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenMovement, TokenStream

ISOLATED, FINAL, INITIAL, MEDIAL = "\ufe8f", "\ufe90", "\ufe91", "\ufe92"
ALEF, ALEF_FINAL = "\ufe8d", "\ufe8e"
SOFT_EDGE = "\ufe8b"
# Test outlines in pixels at SIZE: ink box (left, bottom, right, top) and advance.
SIZE = 20
UNITS = 1000 // SIZE
FORMS = {
    ISOLATED: ((0, 0, 5, 6), 5),
    FINAL: ((0, 0, 5, 6), 4),
    INITIAL: ((1, 0, 3, 6), 6),
    MEDIAL: ((0, -2, 3, 8), 3),
    ALEF: ((1, 0, 2, 9), 4),
    # Its right edge is half a pixel: one column of half coverage.
    SOFT_EDGE: ((0, 0, 2.5, 4), 3),
}


def _font_data() -> bytes:
    """Original rectangles on a 1000-unit em: at SIZE pixels they cover whole pixels."""
    names = {character: f"u{ord(character):04X}" for character in FORMS}
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "space", *names.values()])
    builder.setupCharacterMap({0x20: "space", **{ord(key): name for key, name in names.items()}})
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (0, 0), "space": (4 * UNITS, 0)}
    for character, ((left, bottom, right, top), advance) in FORMS.items():
        pen = TTGlyphPen(None)
        pen.moveTo((left * UNITS, bottom * UNITS))
        pen.lineTo((left * UNITS, top * UNITS))
        pen.lineTo((right * UNITS, top * UNITS))
        pen.lineTo((right * UNITS, bottom * UNITS))
        pen.closePath()
        glyphs[names[character]] = pen.glyph()
        metrics[names[character]] = (advance * UNITS, left * UNITS)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Classic Retro Core Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    output = BytesIO()
    builder.save(output)
    return output.getvalue()


@pytest.fixture(scope="module")
def font_data() -> bytes:
    return _font_data()


@pytest.fixture(scope="module")
def font(font_data):
    return sized_font(font_data, SIZE)


def _columns(pixels) -> tuple[int, int]:
    return min(x for x, _ in pixels), max(x for x, _ in pixels)


def _rows(pixels) -> tuple[int, int]:
    return min(y for _, y in pixels), max(y for _, y in pixels)


# ---------------------------------------------------------------------------
# Drawing forms


def test_a_form_starts_at_its_first_ink_column_and_sits_on_the_baseline(font):
    initial = draw_form(font, INITIAL, baseline=10)
    # The outline starts one pixel right of its origin; the glyph starts at its ink.
    assert _columns(initial.ink) == (0, 1)
    assert _rows(initial.ink) == (4, 9)
    assert len(initial.ink) == 2 * 6
    medial = draw_form(font, MEDIAL, baseline=10)
    # Two rows below the baseline, eight above it.
    assert _rows(medial.ink) == (2, 11)


def test_joining_forms_end_at_their_ink_and_others_keep_the_font_advance(font):
    # Medial and final forms join the glyph on their right: no gap after the ink.
    assert draw_form(font, MEDIAL, 10).advance == 3
    assert draw_form(font, FINAL, 10).advance == 5
    # An initial form keeps the font's advance (six pixels for two columns of ink).
    assert draw_form(font, INITIAL, 10).advance == 6
    # An isolated form keeps its advance when it has room after its ink...
    assert draw_form(font, ALEF, 10).advance == 4
    # ...and gets one more pixel when its ink fills it, so it never touches the next word.
    assert draw_form(font, ISOLATED, 10).advance == 6


def test_soft_pixels_are_the_coverage_between_the_two_levels(font):
    plain = draw_form(font, SOFT_EDGE, 10)
    assert _columns(plain.ink) == (0, 2)
    assert plain.soft == frozenset()
    graded = draw_form(font, SOFT_EDGE, 10, ink_level=200, soft_level=60)
    assert _columns(graded.ink) == (0, 1)
    assert graded.soft == frozenset((2, y) for y in range(6, 10))
    # Without a soft level, the ink level alone decides.
    assert draw_form(font, SOFT_EDGE, 10, ink_level=200).soft == frozenset()


def test_a_form_without_ink_is_reported(font):
    with pytest.raises(ClassicRetroError) as error:
        draw_form(font, " ", 10)
    assert error.value.code is ErrorCode.FONT_BUILD_FAILED
    assert "U+0020" in str(error.value)


def test_form_bounds_measure_every_form_from_the_baseline(font):
    bounds = form_bounds(font, (ISOLATED, INITIAL, MEDIAL))
    assert (bounds.top, bounds.bottom) == (-8, 2)
    assert bounds.widest_ink == 6
    assert bounds.widest_advance == 6


def test_the_largest_size_that_fits_is_chosen(font_data):
    def fits(candidate):
        width = form_bounds(candidate, (ISOLATED,)).widest_advance
        return width if width <= 3 else None

    chosen, size, width = largest_fitting_size(font_data, (20, 12, 10), fits, "unused")
    # Five pixels at size 20, three at size 12.
    assert (size, width) == (12, 3)
    assert chosen.size == 12
    with pytest.raises(ClassicRetroError) as error:
        largest_fitting_size(font_data, (20,), fits, "No size fits the test cell")
    assert error.value.code is ErrorCode.FONT_BUILD_FAILED
    assert str(error.value) == "No size fits the test cell"


def test_arabic_font_file_must_exist(tmp_path):
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"")
    assert arabic_font_file(font_path) == font_path
    with pytest.raises(ClassicRetroError) as error:
        arabic_font_file(tmp_path / "absent.ttf")
    assert error.value.code is ErrorCode.FONT_BUILD_FAILED
    assert "absent.ttf" in str(error.value)


# ---------------------------------------------------------------------------
# Drawn marks, alef with a mark, shadows and 2-bit rows


def test_patterns_and_drawn_marks():
    assert pattern_pixels(("#.", ".#"), left=3, top=5) == {(3, 5), (4, 6)}
    ink, advance = drawn_mark(("##", "#."), baseline=10)
    assert ink == {(0, 8), (1, 8), (0, 9)}
    assert advance == 3


def _alef(advance: int = 3) -> DrawnForm:
    return DrawnForm(frozenset((0, y) for y in range(1, 10)), frozenset({(0, 0)}), advance)


def test_alef_with_mark_draws_the_mark_above_the_cut_stroke():
    marked = alef_with_mark(ALEF, _alef(), ("##", "#."))
    assert marked.ink == frozenset({(0, 0), (1, 0), (0, 1), *((0, y) for y in range(3, 10))})
    # The alef's own pixels in the mark's rows are gone, soft ones too.
    assert marked.soft == frozenset()
    assert marked.advance == 3
    # A final alef joins its right neighbour: it ends at its ink.
    assert alef_with_mark(ALEF_FINAL, _alef(), ("##", "#.")).advance == 2


def test_alef_with_mark_moves_the_glyph_when_the_mark_starts_left_of_the_stroke():
    marked = alef_with_mark(ALEF, _alef(), ("##", "#."), shift=-1)
    assert (0, 0) in marked.ink and (1, 0) in marked.ink
    assert {(1, y) for y in range(3, 10)} <= marked.ink
    assert marked.advance == 4


def test_alef_with_mark_needs_stroke_below_the_mark():
    short = DrawnForm(frozenset({(0, 0), (0, 1)}), frozenset(), 2)
    with pytest.raises(FormDoesNotFit):
        alef_with_mark(ALEF, short, ("##", "#."))


def test_drop_shadow_stays_inside_the_glyph_and_off_its_ink():
    ink = {(0, 0), (1, 0)}
    assert drop_shadow(ink, ((1, 0), (1, 1)), 3, 2) == {(1, 1), (2, 0), (2, 1)}
    assert drop_shadow(ink, ((1, 0), (1, 1)), 2, 2) == {(1, 1)}
    assert drop_shadow(ink, ((1, 0), (1, 1)), 3, 1) == {(2, 0)}


def test_two_bit_rows_put_pixel_x_at_bits_2x_with_ink_over_shadow():
    rows = two_bit_rows(
        {(0, 0), (1, 1)},
        {(1, 0), (0, 1), (1, 1)},
        columns=2,
        height=3,
        ink_value=1,
        shadow_value=2,
    )
    assert rows == (0b1001, 0b0110, 0)


# ---------------------------------------------------------------------------
# 4bpp tiles


def _quarters(size: int = 16) -> list[list[int]]:
    """Pixel values 1 to 4 by 8x8 quarter, row by row."""
    return [[1 + (x >= 8) + 2 * (y >= 8) for x in range(size)] for y in range(size)]


def test_tiles_are_stored_row_by_row_or_column_by_column():
    rows = pack_4bpp(_quarters())
    assert rows == b"".join(bytes([value * 0x11]) * 32 for value in (1, 2, 3, 4))
    columns = pack_4bpp(_quarters(), columns=True)
    assert columns == b"".join(bytes([value * 0x11]) * 32 for value in (1, 3, 2, 4))


def test_the_left_pixel_of_a_byte_is_its_low_nibble():
    pixels = [[1, 2, 0, 0, 0, 0, 0, 15]] + [[0] * 8 for _ in range(7)]
    data = pack_4bpp(pixels)
    assert data[:4] == bytes([0x21, 0x00, 0x00, 0xF0])
    assert unpack_4bpp(data, 8, 8) == tuple(tuple(row) for row in pixels)


@pytest.mark.parametrize("columns", [False, True])
def test_unpacking_reverses_packing(columns):
    pixels = [[(3 * x + 5 * y) % 16 for x in range(16)] for y in range(24)]
    data = pack_4bpp(pixels, columns=columns)
    assert len(data) == 16 * 24 // 2
    assert unpack_4bpp(data, 16, 24, columns=columns) == tuple(tuple(row) for row in pixels)


@pytest.mark.parametrize(
    "pixels",
    [
        [[0] * 12 for _ in range(8)],
        [[0] * 8 for _ in range(4)],
        [],
        [[0] * 8 for _ in range(7)] + [[0] * 7],
        [[16] + [0] * 7] + [[0] * 8 for _ in range(7)],
    ],
)
def test_packing_refuses_what_is_not_whole_tiles_of_palette_indices(pixels):
    with pytest.raises(ClassicRetroError) as error:
        pack_4bpp(pixels)
    assert error.value.code is ErrorCode.FONT_BUILD_FAILED


def test_unpacking_refuses_data_of_another_size():
    with pytest.raises(ClassicRetroError):
        unpack_4bpp(bytes(31), 8, 8)
    with pytest.raises(ClassicRetroError):
        unpack_4bpp(bytes(24), 6, 8)


# ---------------------------------------------------------------------------
# Glyph codes


def test_characters_take_free_codes_in_order():
    codes = assign_glyph_codes("abc", range(0x10, 0x20), what="Test forms")
    assert codes.characters == ("a", "b", "c")
    assert dict(codes.sequences) == {"a": (0x10,), "b": (0x11,), "c": (0x12,)}
    assert codes.code("b") == 0x11
    assert codes.code("z") is None
    assert codes.sequence("z") is None


def test_a_doubled_character_takes_two_codes():
    codes = assign_glyph_codes(("b", "a", "c"), (9, 7, 8, 5), what="Test forms", doubled={"a"})
    assert codes.sequence("a") == (7, 8)
    assert codes.code("a") == 7
    assert codes.sequence("c") == (5,)
    assert codes.all_codes() == (5, 7, 8, 9)


def test_too_few_free_codes_are_reported():
    with pytest.raises(ClassicRetroError) as error:
        assign_glyph_codes("abc", (1, 2, 3), what="Test forms", doubled={"b"})
    assert error.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED
    assert str(error.value) == "Test forms need 4 codes; the game has 3 free"


def test_characters_must_be_distinct_and_codes_stay_fixed():
    with pytest.raises(ValueError):
        assign_glyph_codes("aba", range(8), what="Test forms")
    codes = GlyphCodes(("a",), {"a": (1,)})
    with pytest.raises(TypeError):
        codes.sequences["b"] = (2,)  # type: ignore[index]


# ---------------------------------------------------------------------------
# Logical Arabic


def test_direction_control_sets():
    assert len(EXPLICIT_DIRECTION_CONTROLS) == 9
    assert {"\u202a", "\u202e", "\u2066", "\u2069"} <= EXPLICIT_DIRECTION_CONTROLS
    assert DIRECTION_CONTROLS - EXPLICIT_DIRECTION_CONTROLS == {"\u200e", "\u200f", "\u061c"}


def test_presentation_forms_and_letters():
    assert is_presentation_form("\ufb50") and is_presentation_form("\ufdff")
    assert is_presentation_form("\ufe70") and is_presentation_form(ISOLATED)
    assert not is_presentation_form("\u0628") and not is_presentation_form("\ufe6f")
    assert is_arabic_letter("\u0628") and is_arabic_letter(ISOLATED)
    assert not is_arabic_letter("b")
    assert not is_arabic_letter("\u064e")
    assert not is_arabic_letter("\u0661")


def test_logical_text_passes_and_the_rest_is_refused():
    check_logical_arabic("\u0628\u0627\u0628 1.", "Test Arabic")
    cases = {
        "\u202b": ErrorCode.EXPLICIT_BIDI_CONTROL,
        "\u200f": ErrorCode.EXPLICIT_BIDI_CONTROL,
        ISOLATED: ErrorCode.PRE_SHAPED_ARABIC_INPUT,
        "\u064e": ErrorCode.UNSUPPORTED_ARABIC_MARK,
    }
    for character, code in cases.items():
        with pytest.raises(ClassicRetroError) as error:
            check_logical_arabic("\u0628" + character, "Test Arabic")
        assert error.value.code is code
    with pytest.raises(ClassicRetroError, match=r"Test Arabic v1 has no vowel marks \(U\+064E\)"):
        check_logical_arabic("\u064e", "Test Arabic")


def test_no_glyph_names_a_missing_form_or_unencodable_text():
    missing = no_glyph(ISOLATED, "Test Arabic")
    assert missing.code is ErrorCode.MISSING_GLYPH
    assert str(missing) == "No Test Arabic glyph for U+FE8F"
    other = no_glyph("%", "Test Arabic")
    assert other.code is ErrorCode.UNENCODABLE_TEXT
    assert str(other) == "Test Arabic text has no glyph for '%'"


# ---------------------------------------------------------------------------
# Paint-order checks


def _stream(*tokens) -> TokenStream:
    return TokenStream(tuple(tokens))


def test_mirrored_brackets_are_refused_in_text_only():
    reject_mirrored(_stream(TextToken("\u0628 1.")), "Test Arabic")
    named = InlineToken(
        id="t0", kind=TokenKind.CONTROL, movement=TokenMovement.ORDERED, name="[wait]"
    )
    reject_mirrored(_stream(named, TextToken("\u0628")), "Test Arabic")
    with pytest.raises(ClassicRetroError) as error:
        reject_mirrored(_stream(TextToken("(\u0628)"), TextToken("\u00ab")), "Test Arabic")
    assert error.value.code is ErrorCode.UNENCODABLE_TEXT
    assert str(error.value) == "Test Arabic cannot mirror bracket glyphs: ()\u00ab"
    # A target that draws its own mirrored parentheses refuses only the rest.
    reject_mirrored(_stream(TextToken("(\u0628)")), "Test Arabic", frozenset("[]"))


def test_raw_newlines_are_refused_with_the_engines_advice():
    reject_text_newlines(_stream(TextToken("\u0628")), "unused")
    with pytest.raises(ClassicRetroError, match="Use the line command"):
        reject_text_newlines(_stream(TextToken("\u0628\n\u0628")), "Use the line command")


# ---------------------------------------------------------------------------
# Engine commands


def test_command_tokens_carry_their_codes():
    token = command_token("t0", TokenKind.CONTROL, "0A 1F", name="wait")
    assert token.movement is TokenMovement.ORDERED
    assert token.name == "wait"
    assert dict(token.args) == {"codes": "0A 1F"}
    assert command_codes(token, "Test") == (0x0A, 0x1F)
    assert not is_inserted(token)
    added = command_token("t1", TokenKind.PAGE_BREAK, "03", inserted=True)
    assert dict(added.args) == {"codes": "03", "inserted": True}
    assert is_inserted(added)


def test_a_token_without_codes_is_reported():
    token = InlineToken(id="t7", kind=TokenKind.LINE_BREAK, movement=TokenMovement.ORDERED)
    with pytest.raises(ClassicRetroError) as error:
        command_codes(token, "Test")
    assert error.value.code is ErrorCode.UNENCODABLE_TOKEN
    assert str(error.value) == "Test token t7 carries no command codes"


def test_translated_commands_must_equal_the_original():
    require_same_commands("Test", ("[a]", "[b]"), ["[a]", "[b]"], "".join)
    with pytest.raises(ClassicRetroError) as error:
        require_same_commands("Test", ("[a]", "[b]"), ("[b]", "[a]"), "".join)
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    assert str(error.value) == "Test commands differ from the original: [a][b] != [b][a]"


# ---------------------------------------------------------------------------
# Previews


def test_glyph_atlas_places_cells_sixteen_a_row_one_pixel_apart():
    atlas = glyph_atlas(17, 2, 3, lambda index, x, y: (index, x, y))
    assert atlas.size == (16 * 4, 2 * 5)
    assert atlas.getpixel((0, 0)) == (40, 40, 40)
    assert atlas.getpixel((1, 1)) == (0, 0, 0)
    assert atlas.getpixel((2, 3)) == (0, 1, 2)
    assert atlas.getpixel((5, 1)) == (1, 0, 0)
    assert atlas.getpixel((1, 6)) == (16, 0, 0)


def _image(width: int, height: int, colour) -> Image.Image:
    return Image.new("RGB", (width, height), colour)


def test_boxes_stand_side_by_side_with_the_first_on_the_right():
    image = pages_right_to_left([_image(3, 2, (255, 0, 0)), _image(3, 2, (0, 255, 0))])
    assert image.size == (10, 2)
    assert image.getpixel((9, 1)) == (255, 0, 0)
    assert image.getpixel((0, 0)) == (0, 255, 0)
    assert image.getpixel((5, 0)) == (0, 0, 0)


def test_preview_sheets_stack_previews_with_their_keys_on_the_left():
    images = [("a", _image(5, 3, (255, 0, 0))), ("b", _image(7, 2, (0, 0, 255)))]
    sheet = preview_sheet(images, 20)
    assert sheet.size == (27, 3 + 4 + 2 + 4)
    assert sheet.getpixel((22, 0)) == (255, 0, 0)
    assert sheet.getpixel((21, 0)) == (12, 12, 12)
    assert sheet.getpixel((20, 7)) == (0, 0, 255)
    enlarged = enlarged_preview_sheet(images, 20)
    assert enlarged.size == (20 + 14, 6 + 6 + 4 + 6)
    assert enlarged.getpixel((20, 0)) == (255, 0, 0)
    assert enlarged.getpixel((29, 5)) == (255, 0, 0)
    assert enlarged.getpixel((30, 0)) == (16, 16, 16)
    assert enlarged.getpixel((33, 12)) == (0, 0, 255)
