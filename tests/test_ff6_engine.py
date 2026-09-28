from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff6 import (
    CHARACTER_CODES,
    COMMAND_CODES,
    DLG_BANK_INCREMENT,
    DLG_COUNT,
    DLG_END,
    DLG_POINTERS,
    DLG_TEXT,
    DTE_CODES,
    DTE_FIRST,
    DTE_TABLE,
    END,
    FONT_WIDTHS,
    LARGE_FONT,
    LINE,
    NAME_CODES,
    PAGE,
    command_skeleton,
    dte_pairs,
    font_widths,
    glyph_rows,
    hirom_address,
    hirom_offset,
    message_at,
    message_notation,
    messages,
)
from classic_retro.engines.ff6 import (
    GLYPH_BYTES as ENGLISH_GLYPH_BYTES,
)
from classic_retro.engines.ff6_arabic import (
    BASELINE,
    FIRST_CODE,
    GLYPH_BYTES,
    GLYPH_ROWS,
    LINE_WIDTH,
    MAX_LINES,
    NAME_WIDTH_MAX,
    RIGHT_EDGE,
    SIZES,
    VARIANT_BYTES,
    WIDEST,
    EncodedMessage,
    Ff6ArabicEncoder,
    Ff6Font,
    Ff6Glyph,
    build_ff6_font,
    choice_advance,
    encode_name,
    ff6_glyph_codes,
    font_preview,
    form_glyph,
    glyph_table,
    hand_drawn_glyph,
    laid_out_line,
    message_characters,
    message_preview,
    notation_skeleton,
    paint_text,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {
    form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM")
    for form in ("ISOLATED", "INITIAL", "MEDIAL", "FINAL")
}
TERRA = NAME_CODES["Terra"]
ROM_SIZE = 3 * 1024 * 1024
# The numbers of the messages the fake ROM holds, with their offsets; from
# BANK_INCREMENT on, the offset counts from bank $CE.
BANK_INCREMENT = 3
POINTERS = {0: 0x0000, 1: 0x0020, 2: 0x0040, 3: 0x0000, 4: 0xF0FE}


def _code(text: str) -> bytes:
    """Invented English in the notation, as the game stores it, with its end."""
    data = bytearray()
    at = 0
    while at < len(text):
        if text[at] == "{":
            close = text.index("}", at)
            name, _, argument = text[at + 1 : close].partition(" ")
            data.append(COMMAND_CODES[name])
            if argument:
                data.append(int(argument, 16))
            at = close + 1
        else:
            data.append(CHARACTER_CODES[text[at]])
            at += 1
    return bytes(data) + bytes((END,))


def _put(rom: bytearray, address: int, data: bytes) -> None:
    at = hirom_offset(address)
    rom[at : at + len(data)] = data


@pytest.fixture(scope="module")
def rom() -> bytes:
    """3 MiB of zeros with a table of pairs, the pointers, five messages, the widths
    and a glyph."""
    rom = bytearray(ROM_SIZE)
    for code in DTE_CODES:
        pair = bytes((0x20 + (code - DTE_FIRST) % 26, 0x3A + (code - DTE_FIRST) % 26))
        _put(rom, DTE_TABLE + 2 * (code - DTE_FIRST), pair)
    _put(rom, DLG_BANK_INCREMENT, struct.pack("<H", BANK_INCREMENT))
    pointers = [POINTERS.get(number, 0) for number in range(DLG_COUNT)]
    _put(rom, DLG_POINTERS, struct.pack(f"<{DLG_COUNT}H", *pointers))
    _put(rom, DLG_TEXT + POINTERS[0], _code("Hi{line}Go!"))
    _put(rom, DLG_TEXT + POINTERS[1], _code("{Terra}: Ok{Key}"))
    _put(
        rom, DLG_TEXT + POINTERS[2], _code("Gil {Gil} {Spaces 02}")[:-1] + bytes((0x80, 0x71, END))
    )
    _put(rom, DLG_TEXT + 0x10000 + POINTERS[3], _code("Far{Pause 04}{page}!"))
    # The last message: two letters to the text's end, without an end.
    _put(rom, DLG_TEXT + 0x10000 + POINTERS[4], b"\x20\x21")
    _put(rom, FONT_WIDTHS, bytes(code % 13 + 4 for code in range(0x100)))
    _put(rom, LARGE_FONT, struct.pack("<11H", *(0x8000 >> row for row in range(11))))
    return bytes(rom)


def test_hirom_addresses_are_64_kib_pieces():
    assert hirom_offset(0xC00000) == 0
    assert hirom_offset(0xCD1234) == 0xD1234
    assert hirom_offset(0x4D1234) == 0xD1234
    assert hirom_address(0xD1234) == 0xCD1234
    with pytest.raises(ClassicRetroError) as caught:
        hirom_offset(0x001234)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_the_pairs_the_widths_and_the_glyphs_come_from_the_rom(rom):
    pairs = dte_pairs(rom)
    assert pairs[0x80] == "Aa" and pairs[0x9B] == "Bb" and len(pairs) == 128
    widths = font_widths(rom)
    assert len(widths) == 256 and widths[0x20] == 0x20 % 13 + 4
    assert glyph_rows(rom, 0x20) == tuple(0x8000 >> row for row in range(11))
    assert ENGLISH_GLYPH_BYTES == 22
    with pytest.raises(ClassicRetroError):
        glyph_rows(rom, 0x1F)


def test_messages_are_found_by_number_in_their_bank(rom):
    first = message_at(rom, 0)
    assert (first.number, first.address, first.data) == (0, DLG_TEXT, _code("Hi{line}Go!"))
    assert message_at(rom, 1).data == _code("{Terra}: Ok{Key}")
    far = message_at(rom, 3)
    assert far.address == DLG_TEXT + 0x10000 and far.data == _code("Far{Pause 04}{page}!")
    assert far.address == 0xCE0000 and DLG_END == 0xCEF100


def test_a_message_without_an_end_is_refused(rom):
    with pytest.raises(ClassicRetroError) as caught:
        message_at(rom, 4)
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
    with pytest.raises(ClassicRetroError) as caught:
        message_at(rom, DLG_COUNT)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE
    with pytest.raises(ClassicRetroError):
        messages(rom)


def test_the_notation_writes_pairs_icons_and_commands(rom):
    pairs = dte_pairs(rom)
    assert message_notation(message_at(rom, 0).data, pairs) == "Hi{line}Go!"
    assert message_notation(message_at(rom, 1).data, pairs) == "{Terra}: Ok{Key}"
    assert message_notation(message_at(rom, 2).data, pairs) == "Gil {Gil} {Spaces 02}Aa{Note}"
    assert message_notation(message_at(rom, 3).data, pairs) == "Far{Pause 04}{page}!"
    with pytest.raises(ClassicRetroError) as caught:
        message_notation(b"\x74", pairs)
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE


def test_the_command_skeleton_keeps_every_command_but_the_layout():
    data = _code("{Terra}: Hi{line}there{Key}{page}{Spaces 03}{Pause 04}{Gil}")
    assert command_skeleton(data) == ("{Terra}", "{Key}", "{Pause 04}", "{Gil}")
    assert command_skeleton(data[:-1]) == command_skeleton(data)
    # An Arabic message's glyph codes are skipped as letters are.
    assert command_skeleton(bytes((0x9A, TERRA, 0xFF, LINE, 0x12, END))) == ("{Terra}", "{Key}")
    with pytest.raises(ClassicRetroError) as caught:
        command_skeleton(bytes((0x11,)))
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_a_translations_skeleton_is_its_tokens_but_the_layout():
    notation = "{Terra}: هيا{line}الآن{Key}\n{Pause 04}نعم"
    assert notation_skeleton(notation) == ("{Terra}", "{Key}", "{Pause 04}")
    validate_command_skeleton(("{Terra}", "{Key}", "{Pause 04}"), notation)
    with pytest.raises(ClassicRetroError) as caught:
        validate_command_skeleton(("{Terra}", "{Key}"), notation)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    assert notation_skeleton("{center}{Choice} نعم") == ("{Choice}",)
    for bad in ("{Gil}", "{Spaces 02}", "{Pause}", "{Key 01}", "{Nobody}"):
        with pytest.raises(ClassicRetroError) as caught:
            notation_skeleton(bad)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_message_characters_are_the_painted_forms():
    assert message_characters("{Terra}: بب") == {" ", ":", BEH["INITIAL"], BEH["FINAL"]}
    assert message_characters("ب{line}ب\nب") == {" ", BEH["ISOLATED"]}
    with pytest.raises(ClassicRetroError) as caught:
        message_characters("ب  ب")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


# ---------------------------------------------------------------------------
# Glyphs


def _glyph(width: int, *ink: tuple[int, int]) -> Ff6Glyph:
    rows = [[0] * WIDEST for _ in range(GLYPH_ROWS)]
    for x, y in ink:
        rows[y][x] = 1
    return Ff6Glyph(width, tuple(tuple(row) for row in rows))


def test_a_glyph_packs_nine_variants_shifted_into_three_bytes():
    glyph = _glyph(5, *((x, BASELINE) for x in range(5)), (15, 0))
    assert glyph.words()[BASELINE] == 0xF800 and glyph.words()[0] == 0x0001
    data = glyph.variant_data()
    assert len(data) == GLYPH_BYTES == 9 * VARIANT_BYTES == 405
    row = BASELINE * 3
    assert data[row : row + 3] == bytes((0xF8, 0x00, 0x00))
    assert data[VARIANT_BYTES + row : VARIANT_BYTES + row + 3] == bytes((0x7C, 0x00, 0x00))
    assert data[8 * VARIANT_BYTES + row : 8 * VARIANT_BYTES + row + 3] == bytes((0x00, 0xF8, 0x00))
    # The rightmost pixel of the top row, shifted by 8, lands in the third byte.
    assert data[8 * VARIANT_BYTES : 8 * VARIANT_BYTES + 3] == bytes((0x00, 0x00, 0x01))


def test_a_forms_width_is_its_advance_or_its_stroke_to_the_edge():
    stroke = [(x, BASELINE) for x in range(3)]
    # The initial form joins the glyph on its left, so it keeps its advance and a free pixel.
    assert form_glyph(BEH["INITIAL"], stroke, 5).width == 5
    assert form_glyph(BEH["INITIAL"], stroke, 2).width == 4
    # The final form joins the glyph on its right: its stroke runs to its edge.
    assert form_glyph(BEH["FINAL"], stroke, 5).width == 3
    with pytest.raises(FormDoesNotFit):
        form_glyph(BEH["ISOLATED"], [(WIDEST, BASELINE)], 3)
    with pytest.raises(FormDoesNotFit):
        form_glyph(BEH["ISOLATED"], [(0, GLYPH_ROWS)], 3)


def test_the_glyph_table_lists_widths_and_addresses_by_code():
    font = Ff6Font({FIRST_CODE: _glyph(6, (0, BASELINE)), FIRST_CODE + 5: _glyph(9)}, 11)
    widths, addresses, data = glyph_table(font, 0xF10000, 0x20000)
    assert len(widths) == 224 and len(addresses) == 3 * 224 and len(data) == 2 * GLYPH_BYTES
    assert widths[0] == 6 and widths[5] == 9 and widths[1] == 0
    assert int.from_bytes(addresses[0:3], "little") == 0xF10000
    assert int.from_bytes(addresses[15:18], "little") == 0xF10000 + GLYPH_BYTES
    assert data[:GLYPH_BYTES] == font.glyphs[FIRST_CODE].variant_data()
    # A glyph never crosses a bank: the 162nd starts the second, after padding.
    many = Ff6Font({code: _glyph(6) for code in range(FIRST_CODE, FIRST_CODE + 162)}, 11)
    widths, addresses, data = glyph_table(many, 0xF10000, 0x20000)
    assert int.from_bytes(addresses[161 * 3 : 162 * 3], "little") == 0xF20000
    assert len(data) == 0x10000 + GLYPH_BYTES
    assert data[161 * GLYPH_BYTES : 0x10000] == bytes((0xFF,)) * (0x10000 - 161 * GLYPH_BYTES)
    with pytest.raises(ClassicRetroError) as caught:
        glyph_table(many, 0xF10000, 0x10000)
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED
    with pytest.raises(ClassicRetroError) as caught:
        glyph_table(font, 0xF10800, 0x20000)
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE


def test_hand_drawn_punctuation_sits_on_the_baseline():
    glyph = hand_drawn_glyph(".")
    assert glyph.width == 4
    assert glyph.rows[BASELINE][:2] == (1, 1) and glyph.rows[BASELINE - 1][:2] == (1, 1)
    assert not any(glyph.rows[BASELINE + 1])


# ---------------------------------------------------------------------------
# Encoding


def _font(used: set[str]) -> tuple[Ff6Font, Ff6ArabicEncoder]:
    """Every character six pixels wide, the space four, with a bar on the baseline."""
    glyph_map = ff6_glyph_codes(used)
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        width = 4 if character == " " else 6
        ink = () if character == " " else tuple((x, BASELINE) for x in range(width))
        glyphs[code] = _glyph(width, *ink)
    font = Ff6Font(glyphs, 11)
    return font, Ff6ArabicEncoder(glyph_map, font, {TERRA: 30})


def test_the_codes_follow_the_fonts_order():
    codes = ff6_glyph_codes({BEH["FINAL"], " ", "1", "،", BEH["INITIAL"]})
    assert codes.code(" ") == FIRST_CODE
    # The repertoire follows the code points: the final form before the initial.
    assert codes.code("،") < codes.code("1") < codes.code(BEH["FINAL"]) < codes.code(BEH["INITIAL"])
    with pytest.raises(ClassicRetroError) as caught:
        ff6_glyph_codes({"x"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_a_message_is_painted_from_the_right_in_reading_order():
    font, encoder = _font(message_characters("بب 12"))
    encoded = encoder.encode("بب 12")
    initial, final = encoder.codes(BEH["INITIAL"]), encoder.codes(BEH["FINAL"])
    space, one, two = encoder.codes(" "), encoder.codes("1"), encoder.codes("2")
    # The first letter is the rightmost; the digits read left to right, so the 2 is painted first.
    assert encoded.data == initial + final + space + two + one + bytes((END,))
    assert [[line.width for line in page] for page in encoded.pages] == [[6 * 4 + 4]]


def test_lines_break_before_the_word_that_would_pass_the_line():
    word = "ب" * 10  # 60 pixels
    font, encoder = _font(message_characters(word))
    lines = encoder.page(" ".join([word] * 4))
    assert [line.width for line in lines] == [3 * 60 + 2 * 4, 60]
    assert LINE_WIDTH == RIGHT_EDGE - 4 == 220
    forced = encoder.page(f"{word}{{line}}{word}")
    assert [line.width for line in forced] == [60, 60]
    with pytest.raises(ClassicRetroError) as caught:
        encoder.page("ب" * 40)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_pages_are_joined_by_a_page_end_or_by_a_fourth_line():
    font, encoder = _font(message_characters("ب"))
    beh = encoder.codes(BEH["ISOLATED"])
    assert encoder.encode("ب\nب").data == beh + bytes((PAGE,)) + beh + bytes((END,))
    full = "ب{line}ب{line}ب{line}ب\nب"
    assert encoder.encode(full).data == (beh + bytes((LINE,))) * 4 + beh + bytes((END,))
    assert len(encoder.encode(full).pages[0]) == MAX_LINES
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("ب{line}ب{line}ب{line}ب{line}ب")
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_a_name_is_as_wide_as_its_translation():
    font, encoder = _font(message_characters("{Terra}: ب"))
    data, width = encoder.word("{Terra}:")
    assert data[0] == TERRA and width == 30 + 6
    encoded = encoder.encode("{Terra}: ب{Key}")
    assert encoded.data[0] == TERRA and encoded.data[-2] == COMMAND_CODES["Key"]
    assert encoded.pages[0][0].width == 30 + 6 + 4 + 6
    nameless = Ff6ArabicEncoder(encoder.glyph_map, font)
    with pytest.raises(ClassicRetroError) as caught:
        nameless.word("{Locke}")
    assert caught.value.code is ErrorCode.MISSING_GLYPH


def test_a_name_is_one_word_of_a_limited_width():
    font, encoder = _font(message_characters("ب" * 12))
    codes, width = encode_name(encoder, "name.terra", "ب" * 8)
    assert len(codes) == 8 and width == 48
    with pytest.raises(ClassicRetroError) as caught:
        encode_name(encoder, "name.terra", "ب" * 12)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW and NAME_WIDTH_MAX == 64
    with pytest.raises(ClassicRetroError) as caught:
        encode_name(encoder, "name.terra", "ب ب")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_without_the_font_the_codes_are_provisional_and_nothing_is_laid_out():
    encoder = Ff6ArabicEncoder(ff6_glyph_codes(message_characters("بب")))
    encoded = encoder.encode("بب")
    assert encoded.pages is None and len(encoded.data) == 3
    assert encoder.word("بب")[1] == 0


def test_the_hook_model_lays_a_line_out_from_the_right_edge():
    font, encoder = _font(message_characters("{Terra}: بب") | set(paint_text("ب" * 5)))
    line = encoder.encode("{Terra}: بب{Key}").pages[0][0]
    names = {TERRA: encoder.codes(paint_text("ب" * 5))}
    placed = laid_out_line(line.data, font, names)
    lefts = [x for x, _ in placed]
    # Terra's five glyphs first, from the right edge; then the colon, the space, the two letters.
    assert lefts == [218, 212, 206, 200, 194, 188, 184, 178, 172]
    assert all(glyph.width in (4, 6) for _, glyph in placed)


def test_previews_draw_the_font_and_the_pages(tmp_path):
    font, encoder = _font(message_characters("{Terra}: بب\nب"))
    encoded = encoder.encode("{Terra}: بب\nب")
    names = {TERRA: encoder.codes(paint_text("بب"))}
    image = message_preview(encoded, font, names)
    assert image.size == (256, 2 * (MAX_LINES * 16 + 8))
    # The first glyph's baseline bar ends at the right edge, with its shadow after it.
    assert image.getpixel((RIGHT_EDGE - 1, 4 + BASELINE)) == (248, 248, 248)
    assert image.getpixel((RIGHT_EDGE, 4 + BASELINE)) == (16, 16, 24)
    image.save(tmp_path / "pages.png")
    font_preview(font).save(tmp_path / "font.png")
    with pytest.raises(ClassicRetroError):
        message_preview(EncodedMessage(b"\x00", None), font, names)


# ---------------------------------------------------------------------------
# The reference font


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


def test_the_font_is_drawn_at_the_largest_size_its_rows_hold(beh_font):
    used = {BEH["INITIAL"], BEH["FINAL"], " ", "!", "1", "،"}
    glyph_map = ff6_glyph_codes(used)
    font = build_ff6_font(beh_font, glyph_map, used, sizing=set(BEH.values()))
    assert font.font_size in SIZES
    assert set(font.glyphs) == {glyph_map.code(character) for character in used}
    initial = font.glyphs[glyph_map.code(BEH["INITIAL"])]
    final = font.glyphs[glyph_map.code(BEH["FINAL"])]
    # The initial joins on its left: its ink reaches its first column; the final's
    # stroke reaches its last, its width.
    assert any(row[0] for row in initial.rows)
    assert any(row[final.width - 1] for row in final.rows)
    assert 0 < initial.width <= WIDEST and 0 < final.width <= WIDEST
    assert font.glyphs[glyph_map.code("،")] == hand_drawn_glyph("،")
    assert font.width(glyph_map.code(" ")) == 4
    with pytest.raises(ClassicRetroError) as caught:
        build_ff6_font(beh_font, glyph_map, {"x"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_a_choice_leaves_its_cursor_room_and_a_centred_page_indents_its_lines():
    font, encoder = _font(message_characters("{Choice} بب") | message_characters("ب"))
    line = encoder.encode("{Choice} بب").pages[0][0]
    assert line.data[0] == COMMAND_CODES["Choice"] and line.width == 16 + 4 + 12
    placed = laid_out_line(line.data, font, {})
    # The cursor's cell (208-223) stays free: the space and the letters follow it.
    assert [x for x, _ in placed] == [204, 198, 192]
    centred = encoder.encode("{center}بب{line}ب").pages[0]
    assert centred[0].data[:2] == bytes((COMMAND_CODES["Spaces"], (220 - 12) // 2))
    assert centred[0].width == 12 + 104 and centred[1].width == 6 + 107
    assert [x for x, _ in laid_out_line(centred[1].data, font, {})] == [224 - 107 - 6]
    assert notation_skeleton("{center}بب{line}ب") == ()
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("ب{center}ب")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    # Without a font a centred page is laid out by nobody: no spaces command.
    bare = Ff6ArabicEncoder(encoder.glyph_map)
    assert bare.encode("{center}بب").data[0] != COMMAND_CODES["Spaces"]
    # A second choice on the line: the pen moves to a cell's edge (188 to 176), then
    # its cursor takes the next cell (160-175); the text follows.
    two = encoder.encode("{Choice} بب {Choice} بب").pages[0][0]
    assert two.width == 16 + 4 + 12 + 4 + 28 + 4 + 12
    assert [x for x, _ in laid_out_line(two.data, font, {})] == [204, 198, 192, 188, 156, 150, 144]
    assert choice_advance(224) == 16 and choice_advance(188) == 28 and choice_advance(10) == 10
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("{center}{Choice} بب")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
