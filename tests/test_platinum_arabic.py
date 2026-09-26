"""Arabic for the fourth-generation Pokémon engine: codes, glyphs, encoder, previews.

The text is invented and the outlines are drawn here; no game data.
"""

from __future__ import annotations

import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen4 import (
    EOS,
    FORMAT,
    NEWLINE,
    YESNO,
    Gen4Font,
    parse_notation,
)
from classic_retro.engines.pokemon_gen4_arabic import (
    BASELINE,
    DIALOGUE_COLOURS,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    ICON_WIDTH,
    INK,
    LEFT_ARROW,
    NAME_WIDTH,
    PREVIEW_MARGIN,
    RTL_END,
    RTL_FIRST,
    RTL_GLYPH_CODES,
    SHADOW,
    SIZES,
    SPACE_WIDTH,
    TOP_ROW,
    Gen4ArabicEncoder,
    Gen4RtlFont,
    Gen4RtlGlyph,
    Gen4Window,
    build_gen4_rtl_font,
    font_preview,
    gen4_glyph_codes,
    glyph_characters,
    message_preview,
    messages_sheet,
    painted_characters,
    rtl_glyph,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip
ALEF = unicodedata.lookup("ARABIC LETTER ALEF ISOLATED FORM")
SEEN = unicodedata.lookup("ARABIC LETTER SEEN ISOLATED FORM")
JEEM = unicodedata.lookup("ARABIC LETTER JEEM ISOLATED FORM")
DIALOGUE = Gen4Window("dialogue", 216, 2)
BLOCK = Gen4Window("block", 176, 12)
MENU = Gen4Window("menu", 48, 1, text_x=12)


def _pixels(glyph: Gen4RtlGlyph, value: int) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(glyph.pixels) for x, v in enumerate(row) if v == value}


def _map(text: str = "بب ب. !ا بببب:") -> GlyphCodes:
    return gen4_glyph_codes(painted_characters(parse_notation(text)))


def _fake_font(glyph_map: GlyphCodes, width: int = 5) -> Gen4RtlFont:
    """Every glyph a bar ``width`` pixels wide; the space is the real one."""
    bar = rtl_glyph({(x, y) for x in range(width - 1) for y in range(4, BASELINE)}, width)
    glyphs = {
        codes[0]: rtl_glyph((), SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return Gen4RtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def _code(glyph_map: GlyphCodes, character: str) -> int:
    code = glyph_map.code(character)
    assert code is not None
    return code


def test_codes_go_to_the_characters_a_script_uses_with_the_arrow_first():
    glyph_map = gen4_glyph_codes({BEH["MEDIAL"], ".", " ", ALEF, "!"})
    assert glyph_map.characters == (LEFT_ARROW, " ", ".", "!", ALEF, BEH["MEDIAL"])
    assert glyph_map.all_codes() == tuple(range(RTL_FIRST, RTL_FIRST + 6))
    assert RTL_GLYPH_CODES == tuple(range(0x01FE, 0x0400))
    # The same characters in another order get the same codes.
    again = gen4_glyph_codes([ALEF, "!", BEH["MEDIAL"], " ", "."])
    assert again.sequences == glyph_map.sequences
    assert glyph_characters()[:5] == (LEFT_ARROW, " ", ".", "!", ":")
    # The whole repertoire fits the codes the game's fonts leave free.
    assert len(gen4_glyph_codes(glyph_characters()).all_codes()) == len(glyph_characters())
    with pytest.raises(ClassicRetroError) as caught:
        gen4_glyph_codes({ALEF, "x"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


@pytest.mark.parametrize(
    ("ink", "width"),
    [({(3, 5)}, 3), ({(0, TOP_ROW - 1)}, 4), (set(), 0), (set(), GLYPH_COLUMNS + 1)],
)
def test_glyphs_keep_their_ink_inside_their_advance_and_off_the_top_row(ink, width):
    with pytest.raises(FormDoesNotFit):
        rtl_glyph(ink, width)


def test_the_shadow_goes_right_and_down_inside_the_advance():
    glyph = rtl_glyph({(0, 5), (2, 5), (1, GLYPH_ROWS - 1)}, 3)
    assert glyph.pixels[5][:4] == (INK, SHADOW, INK, 0)
    assert glyph.pixels[6][:4] == (SHADOW, SHADOW, SHADOW, 0)
    assert _pixels(glyph, SHADOW) <= {(x, y) for x in range(3) for y in range(GLYPH_ROWS)}
    assert glyph.pixels[GLYPH_ROWS - 1][:3] == (0, INK, SHADOW)


def test_the_glyphs_follow_the_games_509_in_its_fonts():
    game = Gen4Font(16, 16, 2, 2, bytes(64 * (RTL_FIRST - 1)), bytes([6]) * (RTL_FIRST - 1))
    wide = rtl_glyph({(0, 2), (12, 11)}, 14)
    font = Gen4RtlFont({RTL_FIRST: rtl_glyph((), SPACE_WIDTH), RTL_FIRST + 3: wide}, {}, 11)
    extended = font.extend(game)
    assert extended.count == RTL_FIRST + 3
    assert extended.width(RTL_FIRST) == SPACE_WIDTH and extended.width(RTL_FIRST + 3) == 14
    # Codes the script does not use are blank and take no room.
    assert extended.width(RTL_FIRST + 1) == 0 and not any(map(any, extended.glyph(RTL_FIRST + 1)))
    assert extended.glyph(RTL_FIRST + 3) == wide.pixels
    assert extended.glyphs[: len(game.glyphs)] == game.glyphs
    for other in (
        Gen4Font(16, 16, 2, 2, bytes(64 * 508), bytes(508)),
        Gen4Font(8, 16, 1, 2, bytes(32 * 509), bytes(509)),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            font.extend(other)
        assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


@pytest.fixture
def contextual_font(tmp_path):
    """Original test outlines: alef, beh and a wide seen, with OpenType forms."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
        "seen": [(0, 0, 1200, 300)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh", 0x633: "seen"})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for left, bottom, right, top in shapes.get(name, []):
            pen.moveTo((left, bottom))
            pen.lineTo((left, top))
            pen.lineTo((right, top))
            pen.lineTo((right, bottom))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["alef"] = (329, 100)
    metrics["seen"] = (1200, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro Gen4 Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "contextual.ttf"
    builder.save(path)
    return path


def test_the_font_draws_forms_in_the_games_ink_and_shadow(contextual_font):
    glyph_map = gen4_glyph_codes({" ", ".", "!", ":", ALEF, SEEN, *BEH.values()})
    forms = (ALEF, SEEN, *BEH.values())
    font = build_gen4_rtl_font(contextual_font, glyph_map, sizing=forms)

    assert font.font_size in SIZES
    assert set(font.glyphs) == set(glyph_map.all_codes())
    for code, glyph in font.glyphs.items():
        assert 1 <= glyph.width <= GLYPH_COLUMNS, code
        assert {value for row in glyph.pixels for value in row} <= {0, INK, SHADOW}, code
        painted = _pixels(glyph, INK) | _pixels(glyph, SHADOW)
        assert all(x < glyph.width and TOP_ROW <= y < GLYPH_ROWS for x, y in painted), code
    # The letters sit on the baseline: the body's ink ends on the row above it.
    beh = font.glyphs[_code(glyph_map, BEH["ISOLATED"])]
    assert max(y for _, y in _pixels(beh, INK) if y < BASELINE) == BASELINE - 1
    # A medial form's ink reaches both edges of its advance.
    medial = font.glyphs[_code(glyph_map, BEH["MEDIAL"])]
    columns = {x for x, _ in _pixels(medial, INK)}
    assert min(columns) == 0 and max(columns) == medial.width - 1
    # The wide seen stays one glyph, wider than half the cell.
    assert 8 < font.glyphs[_code(glyph_map, SEEN)].width <= GLYPH_COLUMNS
    # The space is blank; the full stop a 2x2 dot on the letters' last rows.
    space = font.glyphs[_code(glyph_map, " ")]
    assert space.width == SPACE_WIDTH and not _pixels(space, INK)
    stop = font.glyphs[_code(glyph_map, ".")]
    assert _pixels(stop, INK) == {(0, BASELINE - 2), (1, BASELINE - 2), (0, BASELINE - 1),
                                  (1, BASELINE - 1)}  # fmt: skip
    assert stop.width == 4
    # The menus' left arrow: a triangle pointing left, its tip in the first column.
    arrow = font.glyphs[RTL_FIRST]
    assert glyph_map.characters[0] == LEFT_ARROW and arrow.width == 7
    ink = _pixels(arrow, INK)
    assert {y for x, y in ink if x == 0} == {BASELINE - 5}
    assert {y for x, y in ink if x == 4} == set(range(BASELINE - 9, BASELINE))


def test_a_font_without_a_form_is_refused(contextual_font):
    glyph_map = gen4_glyph_codes({ALEF, JEEM})
    with pytest.raises(ClassicRetroError) as caught:
        build_gen4_rtl_font(contextual_font, glyph_map)
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_text_is_encoded_in_right_to_left_paint_order():
    glyph_map = _map()
    encoding = Gen4ArabicEncoder(glyph_map).encode(parse_notation("بب ب\nب."), DIALOGUE)

    def code(character: str) -> int:
        return _code(glyph_map, character)

    # The first glyph painted is the rightmost: the first letter of the line.
    assert encoding.codes == (
        code(BEH["INITIAL"]),
        code(BEH["FINAL"]),
        code(" "),
        code(BEH["ISOLATED"]),
        NEWLINE,
        # The full stop ends the sentence on its left, so it is painted last.
        code(BEH["ISOLATED"]),
        code("."),
        EOS,
    )
    assert encoding.lines is None and encoding.line_widths is None
    assert all(RTL_FIRST <= value < RTL_END for value in encoding.codes[:4])


def test_a_latin_run_and_a_name_stay_left_to_right_between_arabic_spaces():
    pieces = parse_notation("ب BC2 ب {STRVAR_1 3, 0, 0}.")
    glyph_map = gen4_glyph_codes(painted_characters(pieces))
    assert glyph_map.characters == (LEFT_ARROW, " ", ".", BEH["ISOLATED"])
    codes = Gen4ArabicEncoder(glyph_map).encode(pieces, DIALOGUE).codes
    beh, space, stop = (_code(glyph_map, c) for c in (BEH["ISOLATED"], " ", "."))
    # The Latin run keeps its reading order: the hooks draw it left to right.
    assert codes[:7] == (beh, space, 0x012C, 0x012D, 0x0123, space, beh)
    assert codes[7:] == (space, FORMAT, 0x0103, 2, 0, 0, stop, EOS)


def test_lines_are_measured_against_their_window():
    glyph_map = _map()
    encoder = Gen4ArabicEncoder(glyph_map, _fake_font(glyph_map))
    encoding = encoder.encode(parse_notation("بب ب\nب {STRVAR_1 3, 0, 0}"), DIALOGUE)
    assert encoding.line_widths == (3 * 5 + SPACE_WIDTH, 5 + SPACE_WIDTH + NAME_WIDTH)
    # A Latin letter takes the width the game gives it (6 without its font).
    widths = encoder.encode(parse_notation("ب A"), DIALOGUE, game_width=lambda code: 9)
    assert widths.line_widths == (5 + SPACE_WIDTH + 9,)
    # 43 bars fill the box's 216 pixels; 44 do not.
    assert encoder.encode(parse_notation("ب" * 43), DIALOGUE).line_widths == (215,)
    with pytest.raises(ClassicRetroError, match="needs 220px") as caught:
        encoder.encode(parse_notation("ب" * 44), DIALOGUE)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    # The touch-screen icon takes the left of every line of its page.
    with pytest.raises(ClassicRetroError, match="holds 192px") as caught:
        encoder.encode(parse_notation("ب" * 39 + "{YESNO 0}"), DIALOGUE)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert ICON_WIDTH == 24
    # A menu entry starts after the cursor.
    assert encoder.encode(parse_notation("ب" * 7), MENU).line_widths == (35,)
    with pytest.raises(ClassicRetroError, match="holds 36px"):
        encoder.encode(parse_notation("ب" * 8), MENU)


@pytest.mark.parametrize(
    ("text", "window", "code"),
    [
        ("ب{COLOR 1}ب", DIALOGUE, ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("ب\rب", MENU, ErrorCode.TEXT_BOX_OVERFLOW),
        ("ب\nب", MENU, ErrorCode.TEXT_BOX_OVERFLOW),
        ("ب\rب", BLOCK, ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("ب\nب\nب", DIALOGUE, ErrorCode.TEXT_BOX_OVERFLOW),
        # A form this script gave no code; a character no glyph draws ("x" is the game's).
        ("ب ج", DIALOGUE, ErrorCode.MISSING_GLYPH),
        ("ب @", DIALOGUE, ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_what_a_window_cannot_show_is_refused(text, window, code):
    pieces = parse_notation(text)
    glyph_map = gen4_glyph_codes({*_map().characters})
    with pytest.raises(ClassicRetroError) as caught:
        Gen4ArabicEncoder(glyph_map).encode(pieces, window)
    assert caught.value.code is code


def test_the_translation_keeps_the_originals_commands():
    validate_command_skeleton(("\r", "{YESNO 0}"), parse_notation("ب\nب\rب{YESNO 0}"))
    for text in ("ب\nب{YESNO 0}", "ب\rب", "ب\fب{YESNO 0}"):
        with pytest.raises(ClassicRetroError) as caught:
            validate_command_skeleton(("\r", "{YESNO 0}"), parse_notation(text))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    assert YESNO == 0x0200


def test_previews_show_each_screen_from_the_right():
    glyph_map = _map()
    font = _fake_font(glyph_map)
    atlas = font_preview(font)
    assert atlas.size == (16 * (GLYPH_COLUMNS + 2), GLYPH_ROWS + 2)
    encoder = Gen4ArabicEncoder(glyph_map, font)
    one = encoder.encode(parse_notation("بب ب"), DIALOGUE)
    two = encoder.encode(parse_notation("ب\nب\fبب\rب"), DIALOGUE)
    assert one.lines is not None and two.lines is not None
    single = message_preview(font, one.lines, DIALOGUE)
    screen = (DIALOGUE.width + 2 * PREVIEW_MARGIN, 2 * GLYPH_ROWS + 2 * PREVIEW_MARGIN)
    assert single.size == screen
    # The line ends at the window's right edge: its first glyph is the rightmost.
    right = PREVIEW_MARGIN + DIALOGUE.width
    assert single.getpixel((right - 5, PREVIEW_MARGIN + 6)) == DIALOGUE_COLOURS[INK]
    assert single.getpixel((right + 1, PREVIEW_MARGIN + 6)) == DIALOGUE_COLOURS[0]
    # Two lines, a scroll, then a new page: three screens, the first on the right.
    three = message_preview(font, two.lines, DIALOGUE)
    assert three.size == (3 * screen[0] + 2 * 4, screen[1])
    first = three.crop((2 * (screen[0] + 4), 0, three.width, screen[1]))
    assert first.getpixel((right - 5, PREVIEW_MARGIN + 6)) == DIALOGUE_COLOURS[INK]
    assert first.getpixel((right - 5, PREVIEW_MARGIN + GLYPH_ROWS + 6)) == DIALOGUE_COLOURS[INK]
    sheet = messages_sheet([("one", single), ("two", three)])
    assert sheet.size == (180 + three.width, single.height + three.height + 8)
