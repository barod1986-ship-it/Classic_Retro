from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ridge_racer import (
    BUTTONS,
    program_string,
    string_notation,
    string_room,
)
from classic_retro.engines.ridge_racer_arabic import (
    ARABIC_CODES,
    ATLAS_ROW_BYTES,
    ATLAS_ROWS,
    ATLAS_U,
    ATLAS_V,
    ATLAS_WIDTH,
    CELLS,
    CENTRE,
    CLEAR,
    GLYPH_ENTRY,
    INK,
    LARGE,
    LEFT_EDGE,
    MIRROR,
    MIRROR_BIAS,
    OUTLINE,
    PREVIEW_ABOVE,
    PREVIEW_BACKGROUND,
    PREVIEW_COLOURS,
    SCREEN_WIDTH,
    SHADES,
    SMALL,
    TABLE_BYTES,
    TOP_EDGE,
    EncodedString,
    RidgeRacerArabicEncoder,
    RrFont,
    RrGlyph,
    build_atlas,
    build_ridge_racer_fonts,
    font_preview,
    glyph_characters,
    hand_drawn_glyph,
    large_glyph,
    pack_atlas,
    pen_start,
    ridge_racer_glyph_codes,
    small_glyph,
    string_preview,
    visual_text,
)
from classic_retro.font.glyph_raster import FormDoesNotFit, emboldened

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
TRIANGLE = BUTTONS[ord("a")]


def _map(*texts: str) -> GlyphCodes:
    characters: set[str] = set()
    for text in texts:
        characters |= set(visual_text(text))
    return ridge_racer_glyph_codes(characters | {" "})


def _bar(width: int, height: int = 3, dy: int = 2) -> RrGlyph:
    return RrGlyph(width, dy, ((INK,) * width,) * height)


def _fonts(glyph_map: GlyphCodes, width: int = 10) -> dict[str, RrFont]:
    """Every glyph a bar ``width`` pixels wide; the space a blank of 4."""
    glyphs = {
        code: RrGlyph(4, 0, ()) if character == " " else _bar(width)
        for character, (code,) in glyph_map.sequences.items()
    }
    return {SMALL: RrFont(SMALL, glyphs, 11), LARGE: RrFont(LARGE, glyphs, 18)}


# ---------------------------------------------------------------------------
# The program's strings


def test_a_string_takes_its_bytes_its_zero_and_the_padding_to_the_next_word():
    data = b"GO\x00\x00" + b"PUSH START\x00\x00" + b"NEXT\x00\x00\x00\x00" + b"END\x00"
    assert program_string(data, 4) == b"PUSH START"
    assert string_room(data, 0) == 4
    assert string_room(data, 4) == 12  # ten letters, the zero, one byte of padding
    assert string_room(data, 16) == 8  # a word of zeros after it is the next string's
    assert string_room(data, 24) == 4
    with pytest.raises(ClassicRetroError) as caught:
        program_string(b"NO END", 0)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_the_notation_writes_the_buttons_as_the_symbols_they_draw():
    assert string_notation(b"a OR b BUTTON:EXIT") == "△ OR □ BUTTON:EXIT"
    assert string_notation(b"c OR B") == "Ⅱ OR B"
    assert string_notation(b"d") == "○"
    assert [BUTTONS[code] for code in b"abcd"] == ["△", "□", "Ⅱ", "○"]
    with pytest.raises(ClassicRetroError) as caught:
        string_notation(b"\x82k")
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE


# ---------------------------------------------------------------------------
# Codes and encoding


def test_the_codes_start_at_the_space_in_the_fonts_order():
    assert ARABIC_CODES[0] == 0x20 and len(ARABIC_CODES) == 128
    order = glyph_characters()
    assert order[:5] == (" ", "△", "□", "Ⅱ", "○")
    glyph_map = ridge_racer_glyph_codes({BEH["ISOLATED"], " ", TRIANGLE, "1"})
    assert glyph_map.code(" ") == 0x20 and glyph_map.code(TRIANGLE) == 0x21
    assert glyph_map.code("1") == 0x22 and glyph_map.code(BEH["ISOLATED"]) == 0x23
    for character in ("A", "é"):
        with pytest.raises(ClassicRetroError) as caught:
            ridge_racer_glyph_codes({character})
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_a_string_is_its_mode_its_parameter_its_glyphs_left_to_right_and_a_zero():
    glyph_map = _map("ب بب △")
    encoded = RidgeRacerArabicEncoder(glyph_map).encode("ب بب △", SMALL, CENTRE, 17, 0x60)
    code = glyph_map.code
    visual = (TRIANGLE, " ", BEH["FINAL"], BEH["INITIAL"], " ", BEH["ISOLATED"])
    assert visual_text("ب بب △") == "".join(visual)
    assert encoded.codes == bytes(code(character) for character in visual)
    assert encoded.data == bytes((CENTRE, 17)) + encoded.codes + b"\x00"
    assert encoded.width is None and encoded.pen is None
    for parameter in (0, 256):
        with pytest.raises(ClassicRetroError) as caught:
            RidgeRacerArabicEncoder(glyph_map).encode("ب", SMALL, CENTRE, parameter, 0)
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_the_pen_starts_where_the_hook_puts_it():
    # Centred on the English's n cells, halved as the hook's arithmetic shift does.
    assert pen_start(CENTRE, 17, 0x60, 75, 8) == 0x60 + (17 * 8 - 75) // 2
    assert pen_start(CENTRE, 2, 10, 21, 8) == 7
    # Ending at the mirror of the English's left edge, moved by the parameter less 128.
    assert pen_start(MIRROR, MIRROR_BIAS, 0x20, 153, 16) == SCREEN_WIDTH - 0x20 - 153
    assert pen_start(MIRROR, MIRROR_BIAS + 3, 0x20, 153, 16) == SCREEN_WIDTH - 0x20 - 150
    with pytest.raises(ClassicRetroError) as caught:
        pen_start(3, 0, 0, 0, 8)
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_the_encoder_measures_with_the_fonts_and_keeps_the_text_on_the_screen():
    glyph_map = _map("بب ب")
    fonts = _fonts(glyph_map)
    encoder = RidgeRacerArabicEncoder(glyph_map, fonts)
    encoded = encoder.encode("بب ب", SMALL, CENTRE, 17, 0x60)
    assert encoded.width == 3 * 10 + 4
    assert encoded.pen == 0x60 + (17 * 8 - 34) // 2
    large = encoder.encode("بب ب", LARGE, MIRROR, MIRROR_BIAS, 0x20)
    assert large.pen == SCREEN_WIDTH - 0x20 - 34
    for mode, parameter, x in ((CENTRE, 1, 0), (MIRROR, MIRROR_BIAS, 300)):
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode("بب ب", SMALL, mode, parameter, x)
        assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    with pytest.raises(ClassicRetroError) as caught:
        RrFont(SMALL, {}, 11).measure(b"\x21")
    assert caught.value.code is ErrorCode.MISSING_GLYPH


# ---------------------------------------------------------------------------
# Glyphs


def test_one_pixel_strokes_are_emboldened_but_dots_and_counters_stay_apart():
    # An L: its upright one pixel wide, its foot four; the upright gains a column.
    upright = {(0, y) for y in range(5)} | {(x, 5) for x in range(4)}
    assert emboldened(upright) - upright == {(1, y) for y in range(5)}
    # At the ink's right edge the new pixel goes left.
    right = {(3, y) for y in range(5)} | {(x, 5) for x in range(4)}
    assert emboldened(right) - right == {(2, y) for y in range(5)}
    # A one-pixel counter stays open; the walls have no room outside the ink's box.
    cup = {(0, y) for y in range(4)} | {(2, y) for y in range(4)} | {(x, 4) for x in range(3)}
    assert emboldened(cup) == cup
    # Dots (groups under three pixels) stay; a stroke keeps a pixel from another group.
    dots = {(0, 0), (2, 0), (5, 0), (6, 0)}
    assert emboldened(dots) == dots
    stroke = {(0, y) for y in range(2, 6)}
    near = stroke | {(2, 1), (3, 1), (4, 1)} | {(2, 6), (3, 6)}
    assert emboldened(near) - near == {(1, 3), (1, 4)}
    assert emboldened(set()) == frozenset()


def test_small_glyphs_are_colour_1_emboldened_and_cropped_to_their_rows():
    cell = CELLS[SMALL]
    ink = {(0, y) for y in range(6, 11)} | {(x, 10) for x in range(4)} | {(2, 4)}
    glyph = small_glyph(ink, 5, cell)
    assert (glyph.width, glyph.dy, glyph.height) == (5, cell.top + 4, 7)
    assert glyph.rows[0] == (CLEAR, CLEAR, INK, CLEAR, CLEAR)  # the dot, as it was
    assert glyph.rows[2] == (INK, INK, CLEAR, CLEAR, CLEAR)  # the upright, two wide
    assert glyph.rows[-1] == (INK, INK, INK, INK, CLEAR)
    for bad in ({(0, -1)}, {(0, cell.rows)}, {(cell.widest, 5)}):
        with pytest.raises(FormDoesNotFit):
            small_glyph(bad, 1, cell)


def test_large_glyphs_are_shaded_like_chrome_and_outlined_but_where_they_join():
    cell = CELLS[LARGE]
    # A block three wide on rows 10 to 13 of the cell: the string's rows 6 to 9.
    ink = {(x, y) for x in range(3) for y in range(10, 14)}
    alone = large_glyph(ink, cell, joins_left=False, joins_right=False)
    assert (alone.width, alone.dy, alone.height) == (5, cell.top + 9, 6)
    assert alone.rows[0] == (OUTLINE,) * 5
    assert alone.rows[1] == (OUTLINE, TOP_EDGE, TOP_EDGE, TOP_EDGE, OUTLINE)
    assert alone.rows[2] == (OUTLINE, LEFT_EDGE, SHADES[7 - 1], SHADES[7 - 1], OUTLINE)
    assert alone.rows[4] == (OUTLINE, LEFT_EDGE, SHADES[9 - 1], SHADES[9 - 1], OUTLINE)
    joined = large_glyph(ink, cell, joins_left=True, joins_right=True)
    assert joined.width == 3
    # No ring on the joining sides, and no light edge where the stroke goes on.
    assert joined.rows[2] == (SHADES[7 - 1],) * 3
    assert joined.rows[0] == (OUTLINE,) * 3
    for bad in ({(0, 0)}, {(0, cell.rows - 1)}, {(cell.widest, 5)}):
        with pytest.raises(FormDoesNotFit):
            large_glyph(bad, cell, joins_left=False, joins_right=False)


def test_hand_drawn_glyphs_keep_their_rows_on_the_english_letters():
    triangle = hand_drawn_glyph(SMALL, TRIANGLE)
    assert (triangle.width, triangle.dy, triangle.height) == (8, 0, 7)
    assert triangle.rows[-1] == (INK,) * 7 + (CLEAR,)
    stop = hand_drawn_glyph(LARGE, ".")
    assert (stop.width, stop.dy, stop.height) == (5, 10, 5)
    assert stop.rows[2] == (OUTLINE, LEFT_EDGE, SHADES[12 - 1], SHADES[12 - 1], OUTLINE)


def test_a_glyph_entry_is_its_place_size_and_row_offset():
    glyph = RrGlyph(5, -2, ((INK,) * 5,) * 3)
    assert glyph.entry(70, 200) == bytes((70, 200, 5, 3, 0xFE, 0, 0, 0))
    assert RrGlyph(4, 0, ()).entry(70, 200) == bytes((0, 0, 4, 0, 0, 0, 0, 0))
    assert GLYPH_ENTRY == 8 and TABLE_BYTES == 8 * 128


@pytest.fixture(scope="module")
def beh_font(tmp_path_factory):
    """Original test outlines: beh's four forms (a box each, the medial widest) and a digit."""
    names = [".notdef", "space", "beh", "beh.init", "beh.medi", "beh.fina", "one"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x628: "beh", 0x31: "one"})
    glyphs = {}
    for index, name in enumerate(names):
        pen = TTGlyphPen(None)
        if name != "space":
            pen.moveTo((0, 0))
            pen.lineTo((100 + index * 60, 0))
            pen.lineTo((100 + index * 60, 500))
            pen.lineTo((0, 500))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(dict.fromkeys(names, (500, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Classic Retro Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path_factory.mktemp("font") / "beh.ttf"
    builder.save(path)
    return path


def test_the_fonts_are_drawn_at_the_largest_size_their_cells_hold(beh_font):
    small = {BEH["INITIAL"], BEH["FINAL"], " ", TRIANGLE, "."}
    large = {BEH["INITIAL"], BEH["FINAL"], "1", "."}
    glyph_map = ridge_racer_glyph_codes(small | large)
    fonts = build_ridge_racer_fonts(
        beh_font, glyph_map, small=small, large=large, sizing=set(BEH.values()) | {"1"}
    )
    assert fonts[SMALL].font_size in CELLS[SMALL].sizes
    assert fonts[LARGE].font_size in CELLS[LARGE].sizes
    assert fonts[LARGE].font_size > fonts[SMALL].font_size
    code = glyph_map.code
    assert set(fonts[SMALL].glyphs) == {code(character) for character in small}
    assert set(fonts[LARGE].glyphs) == {code(character) for character in large}
    assert fonts[SMALL].glyphs[code(" ")] == RrGlyph(CELLS[SMALL].space, 0, ())
    assert fonts[SMALL].glyphs[code(TRIANGLE)] == hand_drawn_glyph(SMALL, TRIANGLE)
    initial = fonts[LARGE].glyphs[code(BEH["INITIAL"])]
    final = fonts[LARGE].glyphs[code(BEH["FINAL"])]
    # The initial joins on its left: its first column is the stroke; the final on its right.
    assert any(row[0] not in (CLEAR, OUTLINE) for row in initial.rows)
    assert all(row[0] in (CLEAR, OUTLINE) for row in final.rows)
    assert any(row[-1] not in (CLEAR, OUTLINE) for row in final.rows)
    # The buttons are the small font's only.
    with pytest.raises(ClassicRetroError) as caught:
        build_ridge_racer_fonts(
            beh_font, glyph_map, small=set(), large={TRIANGLE}, sizing=set(BEH.values())
        )
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


# ---------------------------------------------------------------------------
# The atlas and the previews


def test_glyphs_go_on_shelves_the_tallest_first():
    places = pack_atlas([(10, 4), (4, 0), (20, 9), (ATLAS_WIDTH - 25, 2), (6, 3)])
    assert places[2] == (ATLAS_U, ATLAS_V)
    assert places[0] == (ATLAS_U + 20, ATLAS_V)
    assert places[4] == (ATLAS_U + 30, ATLAS_V)
    assert places[3] == (ATLAS_U, ATLAS_V + 9)  # no room left on the first shelf
    assert places[1] == (0, 0)  # a blank takes none
    for sizes in ([(ATLAS_WIDTH + 1, 1)], [(10, ATLAS_ROWS + 1)], [(ATLAS_WIDTH, 40)] * 2):
        with pytest.raises(ClassicRetroError) as caught:
            pack_atlas(sizes)
        assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED


def test_the_atlas_holds_both_fonts_pixels_and_their_tables():
    small = {0x21: RrGlyph(3, 1, ((INK, CLEAR, INK),) * 2), 0x20: RrGlyph(4, 0, ())}
    large = {0x21: RrGlyph(2, -3, ((OUTLINE, 0xC),) * 4)}
    atlas = build_atlas({SMALL: RrFont(SMALL, small, 11), LARGE: RrFont(LARGE, large, 18)})
    assert atlas.rows == 4
    assert atlas.places[LARGE, 0x21] == (ATLAS_U, ATLAS_V)
    assert atlas.places[SMALL, 0x21] == (ATLAS_U + 2, ATLAS_V)
    # Four bits a pixel, the first in the low bits.
    assert atlas.pixels[0] == 0xC2
    assert atlas.pixels[1] == 0x01 and atlas.pixels[2] == 0x01
    assert atlas.pixels[ATLAS_ROW_BYTES * 2 + 1] == 0x00
    entry = GLYPH_ENTRY * (0x21 - ARABIC_CODES[0])
    assert atlas.tables[SMALL][entry : entry + 8] == bytes((ATLAS_U + 2, ATLAS_V, 3, 2, 1, 0, 0, 0))
    assert atlas.tables[LARGE][entry : entry + 5] == bytes((ATLAS_U, ATLAS_V, 2, 4, 0xFD))
    assert atlas.tables[SMALL][:8] == bytes((0, 0, 4, 0, 0, 0, 0, 0))
    assert atlas.tables[LARGE][:8] == bytes(8)


def test_previews_show_the_glyphs_and_the_string_where_the_game_draws_it():
    glyph_map = _map("بب ب")
    fonts = _fonts(glyph_map)
    encoded = RidgeRacerArabicEncoder(glyph_map, fonts).encode("بب ب", SMALL, CENTRE, 17, 0x60)
    assert encoded.pen is not None
    image = string_preview(encoded, fonts[SMALL])
    assert image.width == SCREEN_WIDTH
    assert image.getpixel((encoded.pen, PREVIEW_ABOVE + 2)) == PREVIEW_COLOURS[INK]
    assert image.getpixel((encoded.pen - 1, PREVIEW_ABOVE + 2)) == PREVIEW_BACKGROUND
    atlas = font_preview(fonts)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        string_preview(EncodedString(encoded.data, encoded.codes, None, None), fonts[SMALL])
