"""The Arabic of the Pokémon Generation II engine (Polished Crystal): glyphs, forms, shaper,
fonts, Huffman codes and the naming screen's data. Synthetic inputs only: the fonts are drawn
into blank images, the charmap is the symbols' codes alone."""

from __future__ import annotations

import hashlib
import random

import pytest
from PIL import Image

from classic_retro.engines.pokemon_gen2_arabic import fonts, huffman, naming
from classic_retro.engines.pokemon_gen2_arabic.forms import (
    ARABIC_GLYPHS,
    CODES,
    FREE_CODES,
    GLYPH_OF_FORM,
    JOINING,
    LAMALEF,
    PRESENTATION_GLYPH,
    charmap_lines,
    glyph_code,
    presentation,
    shape,
    visual_codes,
)
from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS, PUNCTUATION_GLYPHS

# The codes of the symbols the keyboards type, as the game's charmap has them.
SYMBOLS = {
    " ": 0x7F,
    "!": 0x9F,
    "%": 0xDD,
    "&": 0xD8,
    "+": 0xDE,
    "-": 0xBC,
    ".": 0x9C,
    "/": 0xDC,
    **{str(digit): 0xE0 + digit for digit in range(10)},
    ":": 0xBD,
    "<MN>": 0xD3,
    "<PK>": 0xD2,
    "<SHARP>": 0xDF,
    "¥": 0xEA,
    "×": 0xDB,
    "،": 0x9D,
    "؟": 0x9E,
    "“": 0xBA,
    "…": 0xEB,
    "№": 0xD5,
    "↑": 0xF2,
    "↓": 0xF3,
    "★": 0xEC,
    "♀": 0xBF,
    "♂": 0xBE,
    "♥": 0xDA,
    "♪": 0xD9,
}


def _pixels(image: Image.Image) -> str:
    header = f"{image.mode}:{image.width}x{image.height}:".encode()
    return hashlib.sha256(header + image.tobytes()).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_every_glyph_is_8x8_and_joins_on_row_5():
    assert len(GLYPHS) == 70 and set(ARABIC_GLYPHS) == set(GLYPHS)
    for name, rows in {**GLYPHS, **{str(c): r for c, r in PUNCTUATION_GLYPHS.items()}}.items():
        assert len(rows) == 8 and all(len(row) == 8 and set(row) <= set("#.") for row in rows)
        # Column 0 holds ink only on the baseline, and only where the form joins on.
        column0 = [row[0] for row in rows]
        assert column0.count("#") <= 1 and (column0.count("#") == 0 or rows[5][0] == "#"), name
    for letter, forms in GLYPH_OF_FORM.items():
        for form, glyph in forms.items():
            if JOINING[letter] == "D" and form in "nm":
                # A form that joins the next letter reaches column 0 on the baseline.
                assert GLYPHS[glyph][5][0] == "#", (letter, form)
            if form in "fm" and (JOINING[letter] == "D" or glyph != forms["i"]):
                # A form joined by the letter before it reaches column 7 on the baseline
                # (the alefs with a hamza or madda keep their isolated glyph when joined).
                assert GLYPHS[glyph][5][7] == "#", (letter, form)


def test_the_70_glyphs_take_the_latin_letters_codes_in_order():
    assert len(FREE_CODES) == 70 and len(set(FREE_CODES)) == 70
    assert list(CODES.values()) == list(FREE_CODES)
    assert list(CODES) == [name for name in GLYPHS if name in ARABIC_GLYPHS]
    assert CODES["alef.i"] == 0x80 and CODES["lamalefmadda"] == 0xD1
    # Forms an 8x8 cell cannot tell apart share a glyph: beh's isolated and final.
    assert glyph_code(presentation("ب", "i")) == glyph_code(presentation("ب", "f"))
    assert glyph_code(presentation("ب", "n")) == glyph_code(presentation("ب", "m"))
    assert glyph_code(presentation("ه", "n")) != glyph_code(presentation("ه", "m"))
    assert len(PRESENTATION_GLYPH) == 125 and glyph_code("ب") is None
    assert len(charmap_lines()) == len(PRESENTATION_GLYPH) + 1


def test_the_shaper_joins_by_joining_type_with_or_without_lam_alef():
    def forms(text: str, ligatures: bool = True) -> list[str]:
        return [PRESENTATION_GLYPH.get(char, char) for char in shape(text, ligatures)]

    assert forms("بيت") == ["beh.im", "yeh.im", "teh.if"]
    # A right-joining letter does not join the next one.
    assert forms("دب") == ["dal", "beh.if"]
    # The hamza joins nothing, before or after it.
    assert forms("بءب") == ["beh.if", "hamza", "beh.if"]
    assert forms("سلام") == ["seen.im", "lamalef.f", "meem.if"]
    assert forms("سلام", ligatures=False) == ["seen.im", "lam.im", "alef.f", "meem.if"]
    assert forms("لأن") == ["lamalefhamza", "noon.if"]
    # Every quotation mark becomes the one neutral quote.
    assert shape("، ؟ ؛ «» ١٢٣") == ", ? ; ““ 123"
    assert shape("ABC 12") == "ABC 12"
    random_text = random.Random(5)
    letters = [*JOINING, " ", "!"]
    for _ in range(300):
        text = "".join(random_text.choice(letters) for _ in range(8))
        assert len(shape(text, ligatures=False)) == len(text)
        assert all(char in PRESENTATION_GLYPH or char in " !" for char in shape(text))


def test_visual_order_reverses_letters_but_not_digit_runs():
    symbols = {" ": 0x7F, ":": 0xBD, **{str(digit): 0xE0 + digit for digit in range(10)}}
    codes = visual_codes("طريق 29", symbols)
    assert codes[:2] == [0xE2, 0xE9] and codes[2] == 0x7F
    assert codes[3:] == [glyph_code(char) for char in reversed(shape("طريق"))]
    assert visual_codes("12:30", symbols) == [0xE1, 0xE2, 0xBD, 0xE3, 0xE0]
    with pytest.raises(ValueError, match="no glyph"):
        visual_codes("بX", symbols)


def test_the_fonts_are_drawn_as_pinned():
    blank = Image.new("L", (128, 64), 255)
    assert _pixels(fonts.draw_font(blank)) == (
        "063d016f0fcd6c2f0f2c90e5292751590179d57e7a5dada4e5ce0f59af3552db"
    )
    assert _pixels(fonts.draw_font(blank, bold=True)) == (
        "3e7c5db49e0738781985938f097a52f4d492fa1a4fe3ea9e54dc58a2ae35f504"
    )
    assert _pixels(fonts.draw_vwf_font(blank)) == (
        "68f3067c824e5e7a6bd3524a9f921c4494bcc3dba0da44a16b3cfd4c6670c955"
    )
    typefaces = fonts.typefaces(blank)
    assert list(typefaces) == list(fonts.TYPEFACES)
    assert _pixels(typefaces["bold"]) != _pixels(typefaces["normal"])
    assert _pixels(typefaces["serif"]) == _pixels(typefaces["normal"])
    assert fonts.png_bytes(typefaces["normal"]).startswith(b"\x89PNG")


def test_bold_widens_strokes_to_the_left_but_not_into_column_0():
    assert fonts.bold_rows(["..#.....", "#######.", "........"] + ["........"] * 5)[:2] == [
        ".##.....",
        "#######.",
    ]
    rows = ["........"] * 5 + [".#######", "........", "........"]
    assert fonts.bold_rows(rows)[5] == "########"


def test_vwf_glyphs_crop_to_ink_keep_one_pixel_of_a_join_and_a_gap():
    # alef: no join; one blank column on its left, then its stroke.
    assert fonts.vwf_columns(GLYPHS["alef.i"]) == ["........", "######.."]
    # A medial form keeps one baseline pixel on each joined side.
    medial = fonts.vwf_columns(GLYPHS["beh.im"])
    assert medial[0] == ".....#.." and medial[-1] == ".....#.."
    widths = fonts.vwf_widths(fonts.draw_vwf_font(Image.new("L", (128, 64), 255)), _space())
    assert widths[0x7F] == 4 and widths[CODES["alef.i"]] == 2
    assert all(1 <= widths[code] <= 8 for code in CODES.values())
    assert fonts.vwf_text_width("بيت", widths) == sum(
        widths[glyph_code(char)] for char in shape("بيت")
    )


def _space() -> Image.Image:
    image = Image.new("L", (8, 8), 255)
    for x in range(4, 8):
        for y in range(8):
            image.putpixel((x, y), fonts.GREY)
    return image


def test_huffman_codes_are_a_complete_tree_within_the_engines_limits():
    counts = {leaf: (leaf * 37) % 1000 for leaf in huffman.LEAVES}
    codes = huffman.huffman_codes(counts)
    assert set(codes) == set(huffman.LEAVES) and len(codes) == 128
    assert huffman.is_complete_prefix_code(codes.values())
    assert max(len(code) for code in codes.values()) <= huffman.MAX_CODE_BITS
    # Skewed counts are weighed up until the longest code fits.
    skewed = {leaf: 2**index for index, leaf in enumerate(huffman.LEAVES[:40])}
    limited = huffman.huffman_codes(skewed, max_bits=12)
    assert max(len(code) for code in limited.values()) <= 12
    assert huffman.is_complete_prefix_code(limited.values())
    assert not huffman.is_complete_prefix_code(["0", "01", "1"])
    assert huffman.coded_bits({0x7F: 3}, {0x7F: "01"}) == 6


def test_the_naming_screen_data_is_generated_as_pinned():
    assert _sha(naming.shaping_asm()) == (
        "3e29435abfbc20e3445aaa77cc5dd16fffcf5c8679bec8a01610a98dc368ed85"
    )
    assert _sha(naming.keyboards_asm(SYMBOLS)) == (
        "7b53f7b3dab5b99601382b96b7f0bccde03ea9e00628f63d4de2a69e28524b08"
    )
    assert _sha(naming.key_phrase_asm("محظوظ", SYMBOLS)) == (
        "ec44315d0a91fe4f09fde37b7540aa13a9ed294168a9d23d3d919da47350d778"
    )
    assert naming.NUM_LETTERS == 36 and naming.NUM_DUAL == 23 and not naming.HAMZA_JOINS


def test_the_runtime_shaper_writes_what_the_build_writes():
    assert naming.self_test(SYMBOLS, length=2, samples=500) > 1500
    typed = naming.typed_codes("محمد", SYMBOLS)
    assert naming.runtime_shape([*typed, naming.TERMINATOR])[:-1] == naming.build_time_codes(
        "محمد", SYMBOLS
    )
    # Names have no lam-alef: the runtime shaper has none.
    assert naming.build_time_codes("لا", SYMBOLS) == [CODES["lam.im"], CODES["alef.f"]]
    with pytest.raises(ValueError, match="must fit"):
        naming.key_phrase_codes("محظوظمحظوظ", SYMBOLS)
    with pytest.raises(ValueError, match="not in the charmap"):
        naming.keyboards_asm({" ": 0x7F})


def test_lam_alef_ligatures_cover_every_alef():
    for alef, (isolated, final, isolated_point, final_point) in LAMALEF.items():
        assert shape("ل" + alef) == chr(isolated_point)
        assert shape("بل" + alef)[-1] == chr(final_point)
        assert {isolated, final} <= set(CODES)
