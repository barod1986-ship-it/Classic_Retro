from __future__ import annotations

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fire_emblem_legend import (
    LINE_PITCH,
    MAX_LINE_WIDTH,
    RAMP_LEVELS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_BYTES,
    TILES_X,
    TILES_Y,
    TITLE_TILE_BUDGET,
    LegendImage,
    decode_legend_image,
    encode_legend_image,
    legend_budget,
    legend_font_size,
    legend_sheet,
    render_legend_image,
    validate_legend_lines,
)
from classic_retro.font.shaped_text import ShapedLineRenderer
from classic_retro.rom.fire_emblem_arabic_script import fire_emblem_arabic_legend


def _box(pen: TTGlyphPen, left: int, bottom: int, right: int, top: int) -> None:
    pen.moveTo((left, bottom))
    pen.lineTo((left, top))
    pen.lineTo((right, top))
    pen.lineTo((right, bottom))
    pen.closePath()


@pytest.fixture
def arabic_font(tmp_path):
    """Original test outlines: alef, beh with OpenType forms, no Latin punctuation."""
    shapes = {
        "alef": [(100, 0, 229, 760)],
        "beh": [(50, 0, 450, 130), (200, -230, 330, -100)],
        "beh.init": [(0, 0, 400, 130), (200, -230, 330, -100)],
        "beh.medi": [(0, 0, 500, 130), (200, -230, 330, -100)],
        "beh.fina": [(0, 0, 450, 130), (200, -230, 330, -100)],
    }
    names = [".notdef", "space", *shapes]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x627: "alef", 0x628: "beh"})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        for box in shapes.get(name, []):
            _box(pen, *box)
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["alef"] = (329, 100)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro Legend Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "legend.ttf"
    builder.save(path)
    return path


def test_font_size_puts_the_alef_at_capital_height(arabic_font):
    # 10 pixels / 760 units of alef at 1000 units per em.
    assert legend_font_size(arabic_font) == 13


def test_renderer_shapes_right_to_left_and_adds_missing_punctuation(arabic_font):
    renderer = ShapedLineRenderer(arabic_font, 13)

    pair = renderer.shape("بب")
    # Visual order: the final form (left) comes first, then the initial form.
    assert len(pair) == 2 and pair[0].character != pair[1].character
    assert renderer.width("ب.") > renderer.width("ب")
    assert renderer.width("!") > 0 and renderer.width(":") > 0
    with pytest.raises(ClassicRetroError) as caught:
        renderer.shape("ج")
    assert caught.value.code is ErrorCode.MISSING_GLYPH


def test_missing_font_is_reported(tmp_path):
    with pytest.raises(ClassicRetroError) as caught:
        ShapedLineRenderer(tmp_path / "absent.ttf", 13)
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_legend_image_centres_lines_on_the_palette_ramp(arabic_font):
    renderer = ShapedLineRenderer(arabic_font, 13)
    image = render_legend_image(renderer, ("بب", "ببب."))

    assert len(image.pixels) == SCREEN_WIDTH * SCREEN_HEIGHT
    assert set(image.pixels) <= set(range(RAMP_LEVELS + 1))
    assert 1 in image.pixels and 0 in image.pixels
    rows = [
        y
        for y in range(SCREEN_HEIGHT)
        if any(image.pixels[y * SCREEN_WIDTH : (y + 1) * SCREEN_WIDTH])
    ]
    # Two lines 24 pixels apart around the screen's centre.
    assert rows[0] < SCREEN_HEIGHT // 2 < rows[-1]
    assert rows[-1] - rows[0] < 2 * LINE_PITCH
    columns = [
        x
        for x in range(SCREEN_WIDTH)
        if any(image.pixels[y * SCREEN_WIDTH + x] for y in range(SCREEN_HEIGHT))
    ]
    assert abs((columns[0] + columns[-1]) / 2 - SCREEN_WIDTH / 2) <= 2
    assert image.widths[1] > image.widths[0]


def test_legend_lines_must_fit_and_be_arabic(arabic_font):
    renderer = ShapedLineRenderer(arabic_font, 13)
    with pytest.raises(ClassicRetroError) as caught:
        render_legend_image(renderer, ("ب" * (MAX_LINE_WIDTH // 6 + 1),))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW

    for lines, code in (
        (("Grado",), ErrorCode.UNENCODABLE_TEXT),
        (("عام 803",), ErrorCode.UNENCODABLE_TEXT),
        (("بَ",), ErrorCode.UNSUPPORTED_ARABIC_MARK),
        ((), ErrorCode.TEXT_BOX_OVERFLOW),
        (("ب",) * 6, ErrorCode.TEXT_BOX_OVERFLOW),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            validate_legend_lines(lines)
        assert caught.value.code is code


def _pattern(tiles: int) -> LegendImage:
    """``tiles`` distinct tiles along the top rows, the rest blank."""
    pixels = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    for number in range(tiles):
        tile_x, tile_y = number % TILES_X, number // TILES_X
        for bit in range(8):
            if (number + 1) >> bit & 1:
                pixels[(tile_y * 8 + bit) * SCREEN_WIDTH + tile_x * 8] = 1 + bit
    return LegendImage(pixels=bytes(pixels), lines=("ب",), widths=(1,))


def test_tiles_and_bottom_up_tile_map_round_trip():
    image = _pattern(3)
    encoded = encode_legend_image(image)

    assert encoded.tile_count == 4
    assert encoded.tiles[:TILE_BYTES] == bytes(TILE_BYTES)
    assert encoded.tile_map[:2] == bytes((TILES_X - 1, TILES_Y - 1))
    entries = [
        int.from_bytes(encoded.tile_map[2 + 2 * n : 4 + 2 * n], "little")
        for n in range(TILES_X * TILES_Y)
    ]
    # The first data row is the screen's bottom row; the top-left tiles come last.
    top_row = entries[-TILES_X:]
    assert top_row[:3] == [1, 2, 3] and set(entries[:-TILES_X]) == {0}
    assert decode_legend_image(encoded.tiles, encoded.tile_map) == image.pixels


def test_tile_budgets_are_enforced():
    assert legend_budget(2) == TITLE_TILE_BUDGET
    assert legend_budget(0) > TITLE_TILE_BUDGET
    with pytest.raises(ClassicRetroError) as caught:
        encode_legend_image(_pattern(TITLE_TILE_BUDGET), TITLE_TILE_BUDGET)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


def test_shipped_legend_has_one_valid_entry_per_image():
    legend = fire_emblem_arabic_legend()

    assert [subtitle.index for subtitle in legend] == list(range(7))
    for subtitle in legend:
        assert subtitle.english
        validate_legend_lines(subtitle.lines)
    assert legend[2].lines == ("الأحجار المقدسة",)


def test_sheet_shows_every_image():
    images = [_pattern(2), _pattern(5)]
    sheet = legend_sheet(images)
    assert sheet.width > 2 * SCREEN_WIDTH and sheet.height > SCREEN_HEIGHT
