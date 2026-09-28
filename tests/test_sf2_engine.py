from __future__ import annotations

import struct
import unicodedata

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.sf2 import (
    CHARACTERS,
    COMMANDS,
    END,
    FONT_POINTER,
    LAYOUT_COMMANDS,
    NEW_LINE,
    SPACE,
    STRINGS,
    TAGS,
    TAGS_WITH_ARGUMENT,
    TEXT_BANKS,
    TEXT_BANKS_POINTER,
    TREE_DATA,
    TREE_OFFSETS,
    HuffmanTrees,
    character,
    command_skeleton,
    decode_string,
    font_width,
    notation,
    string_bytes,
    string_offset,
    tag_notation,
    text_banks,
)
from classic_retro.engines.sf2_arabic import (
    ARABIC_CODES,
    ISLAND_WIDTHS,
    LAST_START,
    LINE_END,
    LINE_HEIGHT,
    LINE_START,
    PREVIEW_BACKGROUND,
    PREVIEW_INK,
    PREVIEW_MARGIN,
    RIGHT,
    ROWS,
    SPACE_CODE,
    SPACE_WIDTH,
    WIDEST,
    EncodedString,
    Sf2ArabicEncoder,
    Sf2Font,
    Sf2Glyph,
    build_sf2_font,
    command,
    font_preview,
    form_glyph,
    glyph_characters,
    hand_drawn_glyph,
    ink_glyph,
    message_characters,
    message_preview,
    notation_skeleton,
    paint_text,
    sf2_glyph_codes,
    validate_command_skeleton,
)
from classic_retro.font.glyph_raster import FormDoesNotFit

BEH = {form: unicodedata.lookup(f"ARABIC LETTER BEH {form} FORM") for form in
       ("ISOLATED", "FINAL", "INITIAL", "MEDIAL")}  # fmt: skip


def _symbol(text: str) -> int:
    return CHARACTERS.index(text) + 1


# ---------------------------------------------------------------------------
# The game's text: trees of our own, a tree for the first symbol and one for the rest.

Tree = int | tuple["Tree", "Tree"]
CAPITAL_H, SMALL_I, BANG = _symbol("H"), _symbol("i"), _symbol("!")
FIRST_TREE: Tree = ((CAPITAL_H, 0xFB), (0x02, END))
OTHER_TREE: Tree = (((SMALL_I, SPACE), (NEW_LINE, 0xFC)), ((0x00, END), (BANG, 0xFF)))


def _tree_bits(tree: Tree) -> list[int]:
    if isinstance(tree, int):
        return [1]
    return [0, *_tree_bits(tree[0]), *_tree_bits(tree[1])]


def _leaves(tree: Tree) -> list[int]:
    if isinstance(tree, int):
        return [tree]
    return [*_leaves(tree[0]), *_leaves(tree[1])]


def _paths(tree: Tree, path: tuple[int, ...] = ()) -> dict[int, tuple[int, ...]]:
    if isinstance(tree, int):
        return {tree: path}
    return {**_paths(tree[0], (*path, 0)), **_paths(tree[1], (*path, 1))}


def _pack(bits: list[int]) -> bytes:
    bits = bits + [0] * (-len(bits) % 8)
    return bytes(int("".join(map(str, bits[at : at + 8])), 2) for at in range(0, len(bits), 8))


def _code(symbols: list[int]) -> bytes:
    """A string as stored: its length byte, then its symbols' paths."""
    bits: list[int] = []
    previous = END
    for symbol in symbols:
        bits += _paths(FIRST_TREE if previous == END else OTHER_TREE)[symbol]
        previous = symbol
    code = _pack(bits)
    return bytes((len(code),)) + code


HELLO = [CAPITAL_H, SMALL_I, SPACE, NEW_LINE, 0xFC, 0x00, BANG, END]
CLEARED = [0xFB, SMALL_I, SMALL_I, SMALL_I, END]
BANKS = 0x030000


@pytest.fixture(scope="module")
def rom() -> bytes:
    """Bank 0: a string, the empty string, one whose symbol has no tree after it; bank 1:
    a window cleared. The font's first two characters."""
    data = bytearray(0x40000)
    first = _leaves(FIRST_TREE)[::-1] + list(_pack(_tree_bits(FIRST_TREE)))
    other = _leaves(OTHER_TREE)[::-1] + list(_pack(_tree_bits(OTHER_TREE)))
    offsets = [len(first) + len(_leaves(OTHER_TREE))] * 255
    offsets[END] = len(_leaves(FIRST_TREE))
    struct.pack_into(">255H", data, TREE_OFFSETS, *offsets)
    data[TREE_DATA : TREE_DATA + len(first) + len(other)] = bytes(first + other)
    struct.pack_into(">I", data, TEXT_BANKS_POINTER, BANKS)
    struct.pack_into(f">{TEXT_BANKS}I", data, BANKS, *[BANKS + 0x100 * (1 + n) for n in range(17)])
    bank = _code(HELLO) + b"\x01\x00" + _code([CAPITAL_H, SMALL_I, 0xFF, SMALL_I])
    data[BANKS + 0x100 : BANKS + 0x100 + len(bank)] = bank
    cleared = _code(CLEARED)
    data[BANKS + 0x200 : BANKS + 0x200 + len(cleared)] = cleared
    struct.pack_into(">I", data, FONT_POINTER, 0x029002)
    struct.pack_into(">H", data, 0x029002, 0x0003)
    return bytes(data)


def test_strings_are_found_in_their_bank_one_after_another(rom):
    assert text_banks(rom)[:2] == (BANKS + 0x100, BANKS + 0x200)
    hello = _code(HELLO)
    assert string_offset(rom, 0) == BANKS + 0x100
    assert string_offset(rom, 1) == BANKS + 0x100 + len(hello)
    assert string_bytes(rom, 0) == hello
    assert string_bytes(rom, 1) == b"\x01\x00"
    assert string_offset(rom, 256) == BANKS + 0x200
    for index in (-1, STRINGS):
        with pytest.raises(ClassicRetroError) as caught:
            string_offset(rom, index)
        assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_a_symbol_is_decoded_with_the_tree_of_the_symbol_before(rom):
    trees = HuffmanTrees.read(rom)
    assert len(trees.offsets) == 255
    assert decode_string(rom, 0, trees) == HELLO
    assert decode_string(rom, 1) == [END]  # the empty string: its length byte 1
    assert decode_string(rom, 256) == CLEARED
    # A code of a byte is the empty string, as the game reads it.
    assert _code([0xFB, END])[0] == 1
    with pytest.raises(ClassicRetroError) as caught:
        decode_string(rom, 2)  # FF has no tree after it
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE
    with pytest.raises(ClassicRetroError) as caught:
        trees.decode(b"\x00")  # H, then its code runs out
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR
    # A tree whose leaf lies before the tree data's start.
    short = HuffmanTrees((0,) * 255, _pack(_tree_bits(FIRST_TREE)))
    with pytest.raises(ClassicRetroError) as caught:
        short.decode(b"\x00")
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE


def test_the_notation_writes_characters_and_tags(rom):
    assert notation(decode_string(rom, 0)) == "Hi {N}{NAME;0}!"
    assert notation([0xFB, 0xF2, 0xFD, 3, 0xF1]) == "{CLEAR}{NAME}{COLOR;3}{#}"
    assert character(SPACE) == " " and character(0x50) == ":" and len(CHARACTERS) == 80
    assert CHARACTERS[0x45:0x47] == ("“", "”")
    assert TAGS["NAME"] == 0xF2 and TAGS_WITH_ARGUMENT["NAME"] == 0xFC
    assert TAGS["W2"] == 0xF7 and TAGS["W1"] == 0xFA and set(COMMANDS) == set(range(0xEE, 0xFE))
    for symbols, error in (
        ([0x51], ErrorCode.UNKNOWN_TEXT_BYTE),
        ([0x00], ErrorCode.UNKNOWN_TEXT_BYTE),
        ([0xFD], ErrorCode.MISSING_TERMINATOR),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            notation(symbols)
        assert caught.value.code is error, symbols


def test_the_command_skeleton_keeps_every_tag_but_the_new_lines(rom):
    assert LAYOUT_COMMANDS == {NEW_LINE}
    symbols = [0xFB, CAPITAL_H, SMALL_I, NEW_LINE, 0xFC, 0x00, 0x10, 0xFD, 3, 0xF1, 0xF7]
    skeleton = ("{CLEAR}", "{NAME;0}", "{COLOR;3}", "{#}", "{W2}")
    assert command_skeleton(symbols) == command_skeleton([*symbols, END, 0xFA]) == skeleton
    assert command_skeleton(decode_string(rom, 0)) == ("{NAME;0}",)
    # Arabic glyph codes, below the commands, are text; the commands keep their symbols.
    assert command_skeleton([0x02, 0xED, 0xF2, SPACE, END]) == ("{NAME}",)
    assert command_skeleton([CAPITAL_H, END]) == ()
    assert tag_notation(0xF7) == "{W2}" and tag_notation(0xFC, 3) == "{NAME;3}"
    for symbol, argument in ((0xF7, 1), (0xFC, None)):
        with pytest.raises(ClassicRetroError) as caught:
            tag_notation(symbol, argument)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as caught:
        command_skeleton([0xFD])
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_a_translations_skeleton_is_its_tags_but_the_new_lines():
    notation = "{CLEAR}ب ب{N}{NAME;0} ب{COLOR;3}{#}{W2}"
    assert notation_skeleton(notation) == ("{CLEAR}", "{NAME;0}", "{COLOR;3}", "{#}", "{W2}")
    assert notation_skeleton("ب{N}ب") == ()
    # What the encoder writes has the same skeleton, whatever its layout.
    glyph_map = _map(notation)
    encoded = Sf2ArabicEncoder(glyph_map, _font(glyph_map)).encode(notation)
    assert command_skeleton(encoded.data) == notation_skeleton(notation)
    validate_command_skeleton(("{NAME;0}", "{W2}"), "{NAME;0}…{N}ب{W2}")
    for source, translation in (
        (("{NAME;0}", "{W2}"), "ب{W2}"),
        (("{W2}",), "{CLEAR}ب{W2}"),
        (("{NAME;0}", "{W2}"), "{W2}ب{NAME;0}"),
        (("{NAME;0}",), "{NAME;1}ب"),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            validate_command_skeleton(source, translation)
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    with pytest.raises(ClassicRetroError) as caught:
        notation_skeleton("{NAME;X}")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_a_characters_width_is_its_first_words_nibble_plus_one(rom):
    assert font_width(rom, SPACE) == 4
    assert font_width(rom, 2) == 0


# ---------------------------------------------------------------------------
# Codes, glyphs and encoding


def _map(*texts: str) -> GlyphCodes:
    characters: set[str] = set()
    for text in texts:
        characters |= message_characters(text)
    return sf2_glyph_codes(characters)


def _bar(width: int) -> Sf2Glyph:
    return Sf2Glyph(width, tuple(tuple(x < width for x in range(WIDEST)) for _ in range(ROWS)))


def _font(glyph_map: GlyphCodes, width: int = 10) -> Sf2Font:
    """Every glyph a bar ``width`` pixels wide; the space the real one."""
    glyphs = {code: _bar(width) for (code,) in glyph_map.sequences.values()}
    glyphs[SPACE_CODE] = Sf2Glyph(SPACE_WIDTH, _bar(0).rows)
    return Sf2Font(glyphs, 10)


def test_the_codes_skip_the_commands_and_two_the_game_draws_at_once():
    assert len(ARABIC_CODES) == 234 and ARABIC_CODES[:2] == (0x02, 0x03)
    assert ARABIC_CODES[-1] == 0xED and not {0x7C, 0x7D, SPACE_CODE} & set(ARABIC_CODES)
    assert glyph_characters()[:3] == (".", ",", ":")
    glyph_map = sf2_glyph_codes({BEH["ISOLATED"], " ", "1", "!"})
    assert [glyph_map.code(c) for c in (" ", "!", "1", BEH["ISOLATED"])] == [SPACE, 2, 3, 4]
    for character_, error in (("A", ErrorCode.UNENCODABLE_TEXT), ("ﭐ", ErrorCode.MISSING_GLYPH)):
        with pytest.raises(ClassicRetroError) as caught:
            sf2_glyph_codes({character_})
        assert caught.value.code is error


def test_a_string_is_painted_from_the_right_and_keeps_the_english_tags():
    assert paint_text("بب ب") == BEH["INITIAL"] + BEH["FINAL"] + " " + BEH["ISOLATED"]
    glyph_map = _map("ب {NAME;0}!")
    encoded = Sf2ArabicEncoder(glyph_map).encode("{CLEAR}ب {NAME;0}!{W2}")
    b, bang = glyph_map.code(BEH["ISOLATED"]), glyph_map.code("!")
    assert encoded.data == bytes([0xFB, b, SPACE, 0xFC, 0x00, bang, 0xF7, END])
    assert encoded.lines is None
    assert command("NAME;1") == command("NAME;1") and command("NAME;1").data == b"\xfc\x01"
    assert command("NAME;1").width == ISLAND_WIDTHS["NAME"] and command("#").width == 40
    assert command("N").new_line and command("COLOR;2").width == 0


def test_lines_break_before_the_word_that_would_pass_the_window():
    words = " ".join(["ببب"] * 8)  # 30 pixels a word, 35 with its space
    glyph_map = _map(words)
    encoded = Sf2ArabicEncoder(glyph_map, _font(glyph_map)).encode(words)
    assert encoded.lines is not None
    assert [line.end for line in encoded.lines] == [LINE_START + 6 * 30 + 5 * 5, 2 + 2 * 30 + 5]
    assert encoded.data.count(NEW_LINE) == 1
    assert all(line.end <= LINE_END for line in encoded.lines)
    # {N} ends a line where it stands; a name is reckoned 70 pixels wide.
    split = Sf2ArabicEncoder(glyph_map, _font(glyph_map)).encode("ببب{N}{NAME;0} ببب")
    assert split.lines is not None
    assert [line.end for line in split.lines] == [32, 2 + ISLAND_WIDTHS["NAME"] + 5 + 30]


def test_a_glyph_starts_by_204_and_ends_by_214():
    glyph_map = _map("ب", "ببب")
    encoder = Sf2ArabicEncoder(glyph_map, _font(glyph_map, width=12))
    b = glyph_map.code(BEH["ISOLATED"])
    # 17 glyphs of 12 end at 206; the 18th would start at 206, past 204.
    fits = encoder.encode("ب" * 17)
    assert fits.lines is not None and fits.lines[0].end == 2 + 17 * 12 <= LINE_END
    assert LAST_START == 204
    with pytest.raises(ClassicRetroError) as caught:
        encoder.encode("ب" * 18)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert encoder.codes(BEH["ISOLATED"]) == bytes([b])
    for bad, error in (
        ("ب  ب", ErrorCode.UNENCODABLE_TEXT),
        (" ب", ErrorCode.UNENCODABLE_TEXT),
        ("{DOOR}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{COLOR}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{NAME;238}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{N;1}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            encoder.encode(bad)
        assert caught.value.code is error, bad


def test_a_glyph_is_stored_as_the_game_stores_its_own():
    rows = [[False] * WIDEST for _ in range(ROWS)]
    rows[0][0] = True
    rows[1][15] = True
    rows[14][8] = True
    data = Sf2Glyph(16, tuple(tuple(row) for row in rows)).data()
    assert len(data) == 32
    assert data[:2] == b"\x00\x0f"  # its width less one
    assert data[2:6] == bytes([0x80, 0x00, 0x00, 0x01])
    assert data[30:32] == bytes([0x00, 0x80])
    assert Sf2Glyph(0, _bar(0).rows).data()[:2] == b"\x00\x00"


def test_a_form_keeps_a_free_column_but_where_it_joins_the_glyph_on_its_right():
    stroke = {(x, 8) for x in range(4)}
    assert form_glyph(BEH["FINAL"], stroke, 3).width == 4  # joins on its right: to its edge
    assert form_glyph(BEH["INITIAL"], stroke, 3).width == 5
    assert form_glyph(BEH["ISOLATED"], stroke, 7).width == 7
    for ink, width in (({(0, 0)}, 1), ({(0, 0)}, 17), ({(0, ROWS)}, 4), ({(4, 0)}, 4)):
        with pytest.raises(FormDoesNotFit):
            ink_glyph(ink, width)
    stop = hand_drawn_glyph(".")
    assert stop.width == 2 and stop.rows[11][:2] == (True, False)
    assert sum(map(sum, stop.rows)) == 1
    question = hand_drawn_glyph("؟")
    assert question.width == 5 and question.rows[11][2] and not any(question.rows[12])


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


def test_the_font_is_drawn_at_the_largest_size_its_cell_holds(beh_font):
    used = {BEH["INITIAL"], BEH["FINAL"], " ", "!", "1"}
    glyph_map = sf2_glyph_codes(used)
    font = build_sf2_font(beh_font, glyph_map, used, sizing=set(BEH.values()) | {"1"})
    assert font.font_size in range(8, 15)
    code = glyph_map.code
    assert set(font.glyphs) == {code(character_) for character_ in used}
    initial = font.glyphs[code(BEH["INITIAL"])]
    final = font.glyphs[code(BEH["FINAL"])]
    # The initial joins on its left: its first column is ink; the final's last is.
    assert any(row[0] for row in initial.rows)
    assert any(row[final.width - 1] for row in final.rows)
    # On the English capitals' baseline: nothing under row 11 but a tail.
    assert not any(any(row) for row in initial.rows[12:])
    assert font.glyphs[SPACE_CODE].width == SPACE_WIDTH
    assert font.glyphs[code("!")] == hand_drawn_glyph("!")
    assert font.width(code("!")) == 2
    with pytest.raises(ClassicRetroError) as caught:
        font.width(0xED)
    assert caught.value.code is ErrorCode.MISSING_GLYPH
    with pytest.raises(ClassicRetroError) as caught:
        build_sf2_font(beh_font, glyph_map, {"A"})
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_previews_show_the_glyphs_at_the_mirror_of_the_pen():
    glyph_map = _map("بب ب {NAME;0}")
    font = _font(glyph_map)
    encoded = Sf2ArabicEncoder(glyph_map, font).encode("{CLEAR}بب {NAME;0}{N}ب{W2}")
    image = message_preview(encoded, font)
    assert image.size == (RIGHT + 2 * PREVIEW_MARGIN, 2 * LINE_HEIGHT + 2 * PREVIEW_MARGIN)
    right = PREVIEW_MARGIN + RIGHT - LINE_START
    y = PREVIEW_MARGIN + 5
    assert image.getpixel((right - 1, y)) == PREVIEW_INK
    assert image.getpixel((right + 1, y)) == PREVIEW_BACKGROUND
    # The name, a grey block left of the word and its space.
    name_x = right - 20 - SPACE_WIDTH - ISLAND_WIDTHS["NAME"]
    assert image.getpixel((name_x + 1, PREVIEW_MARGIN + 8)) == (150, 150, 150)
    # The second line, a line lower.
    assert image.getpixel((right - 1, y + LINE_HEIGHT)) == PREVIEW_INK
    atlas = font_preview(font)
    assert atlas.width > 0 and atlas.height > 0
    with pytest.raises(ClassicRetroError):
        message_preview(EncodedString(encoded.data, None), font)
