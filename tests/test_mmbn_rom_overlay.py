from __future__ import annotations

import hashlib
import json
import shutil
import struct

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mmbn import (
    BACKGROUND,
    CELL_BYTES,
    FONT_GLYPHS,
    INK,
    SECTION_TRAILER,
    ScriptArchive,
    build_archive,
    cell_data,
    command_skeleton,
    parse_notation,
    script_bytes,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import mmbn_arabic as overlay
from classic_retro.rom.mmbn_arabic_script import MmbnArabicSection, MmbnScriptArchive

BASE = overlay.ROM_BASE
SCENE_ADDRESS = 0x08700000
ROOM_ADDRESS = 0x08701000
SCENE_POINTER = 0x08010000
ROOM_POINTER = 0x08010004
# Invented scripts in the engine's notation.
SCENE = (
    "{pic 0 0}{dialog_up}<Morning,Robo!>\\p{cls 5}{jump 1}",
    "{hidepic}{dialog_up}<Up you get!>{d 30}\n<Now.>\\p{cls 0}<Go!>\\p{end 5}",
    "{dialog_up}Stay here.\\p{end 0}",
)
ROOM = (
    "{dialog_up}A box.\\p{end 5}",
    "{dialog_up}{raw F3 00 80 02}Got the {key 0}!\\p{end 5}",
    "{dialog_up}Nothing.\\p{end 5}",
)
TRANSLATIONS = {
    "scene.0": ("scene", 0, "{pic 0 0}{dialog_up}<بابا!>\\p{cls 5}{jump 1}"),
    "scene.1": ("scene", 1, "{hidepic}{dialog_up}<اب اب!>{d 30}\n<ابا.>\\p{cls 0}<اب!>\\p{end 5}"),
    "room.1": ("room", 1, "{dialog_up}{raw F3 00 80 02}باب ابا\nPET!\\p{end 5}"),
}


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
    builder.setupNameTable({"familyName": "Classic Retro MMBN Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=800, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(
        builder.font,
        "languagesystem DFLT dflt; languagesystem arab dflt;"
        "feature init { sub beh by beh.init; } init;"
        "feature medi { sub beh by beh.medi; } medi;"
        "feature fina { sub beh by beh.fina; } fina;",
    )
    path = tmp_path / "mmbn-test.ttf"
    builder.save(path)
    return path


def _scripts(sources: tuple[str, ...]) -> list[bytes]:
    return [script_bytes(parse_notation(source)) for source in sources]


def _synthetic_rom() -> bytes:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    put(overlay.PADDING_START, b"\xff" * (overlay.PADDING_END - overlay.PADDING_START))
    for site in overlay.HOOK_SITES:
        put(site.address, site.original)
    put(overlay.TEXT_COPY_CHAR_TILE, overlay.TEXT_COPY_CHAR_TILE_CODE)
    put(overlay.FONT_LITERAL_ADDRESS, struct.pack("<I", overlay.FONT_ADDRESS))
    glyph = cell_data(
        [[INK if 3 <= y <= 13 and 1 <= x <= 6 else BACKGROUND for x in range(8)] for y in range(16)]
    )
    put(overlay.FONT_ADDRESS, glyph * FONT_GLYPHS)
    scene = build_archive(body + SECTION_TRAILER for body in _scripts(SCENE))
    room = build_archive([*(body + SECTION_TRAILER for body in _scripts(ROOM)), SECTION_TRAILER])
    put(SCENE_ADDRESS, scene)
    put(ROOM_ADDRESS, room + bytes.fromhex("cc015555"))
    put(SCENE_POINTER, struct.pack("<I", SCENE_ADDRESS))
    put(ROOM_POINTER, struct.pack("<I", ROOM_ADDRESS))
    return bytes(rom)


def _archives() -> tuple[MmbnScriptArchive, ...]:
    return (
        MmbnScriptArchive("scene", SCENE_ADDRESS, (SCENE_POINTER,), len(SCENE)),
        MmbnScriptArchive("room", ROOM_ADDRESS, (ROOM_POINTER,), len(ROOM) + 1),
    )


def _sections() -> tuple[MmbnArabicSection, ...]:
    originals = {"scene": _scripts(SCENE), "room": _scripts(ROOM)}
    return tuple(
        MmbnArabicSection(
            key=key,
            archive=archive,
            index=index,
            speaker="test",
            source_sha256=hashlib.sha256(originals[archive][index]).hexdigest(),
            source_skeleton=command_skeleton(originals[archive][index]),
            notation=notation,
        )
        for key, (archive, index, notation) in TRANSLATIONS.items()
    )


def _build(font, rom=None, sections=None, archives=None):
    return overlay.build_mmbn_arabic_rom(
        rom or _synthetic_rom(),
        font,
        sections=sections or _sections(),
        archives=archives or _archives(),
        verify_identity=False,
    )


def test_overlay_rebuilds_archives_and_patches_the_calls(arabic_font):
    rom = _synthetic_rom()
    build = _build(arabic_font, rom)
    output = build.rom

    assert len(output) == len(rom)
    assert apply_bps(build.patch.data, rom) == output
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        patched = output[start : start + len(site.original)]
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        assert overlay.bl_target(site.address, patched[:4]) == target
        assert patched[4:] == overlay.NOP * ((len(site.original) - 4) // 2)
    start = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[start : start + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    assert build.report["sections"] == 3 and build.report["pages"] == 4


def test_archives_are_repointed_and_read_back(arabic_font):
    build = _build(arabic_font)
    output = build.rom
    (scene_address,) = struct.unpack_from("<I", output, SCENE_POINTER - BASE)
    (room_address,) = struct.unpack_from("<I", output, ROOM_POINTER - BASE)
    scene = ScriptArchive.parse(output, scene_address)
    room = ScriptArchive.parse(output, room_address)

    assert overlay.PADDING_START <= scene_address < room_address < overlay.PADDING_END
    assert scene.section(output, 0) == build.scripts["scene.0"].data
    assert room.section(output, 1) == build.scripts["room.1"].data
    # Untranslated sections are copied as they are, the empty one included.
    assert scene.section(output, 2) == _scripts(SCENE)[2]
    assert room.section(output, 0) == _scripts(ROOM)[0]
    assert room.extent(output, 3) == SECTION_TRAILER


def test_bank_table_gives_translated_pages_their_banks(arabic_font):
    build = _build(arabic_font)
    output = build.rom
    table_start = overlay.BANK_TABLE_ADDRESS - BASE
    end, count = struct.unpack_from("<II", output, table_start)
    table = output[table_start : table_start + 8 + 8 * count]
    (scene_address,) = struct.unpack_from("<I", output, SCENE_POINTER - BASE)
    (room_address,) = struct.unpack_from("<I", output, ROOM_POINTER - BASE)
    scene = ScriptArchive.parse(output, scene_address)
    room = ScriptArchive.parse(output, room_address)

    page = build.scripts["scene.1"].pages[1]
    offset = overlay.table_lookup(table, scene.section_address(1) + page.start + 1)
    bank = (overlay.FONT_ADDRESS + offset * CELL_BYTES) & 0xFFFFFFFF
    assert output[bank - BASE : bank - BASE + CELL_BYTES] == page.cells[0]
    for untouched in (scene.section_address(2), room.section_address(0), SCENE_ADDRESS, 0x02000000):
        assert overlay.table_lookup(table, untouched) == overlay.NO_BANK
    assert overlay.table_lookup(table, end) == overlay.NO_BANK

    # The page is drawn from column 27 leftwards, line by line.
    placed = overlay.simulate_page(output, table, room.section_address(1))
    first_line = [column for line, column, _ in placed if line == 0]
    assert first_line == list(range(27, 27 - len(first_line), -1))
    assert {line for line, _, _ in placed} == {0, 1}


def test_overlay_refuses_a_different_script(arabic_font):
    rom = bytearray(_synthetic_rom())
    text = _scripts(ROOM)[1]
    start = ScriptArchive.parse(bytes(rom), ROOM_ADDRESS).section_address(1) - BASE
    # "G" of the invented "Got" becomes "F".
    rom[start + text.index(0x65)] ^= 1
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, bytes(rom))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_overlay_refuses_changed_code_or_padding(arabic_font):
    rom = bytearray(_synthetic_rom())
    rom[overlay.HOOK_SITES[1].address - BASE] ^= 0xFF
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, bytes(rom))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH

    rom = bytearray(_synthetic_rom())
    rom[overlay.PADDING_START - BASE + 0x100] = 0
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, bytes(rom))
    assert caught.value.code is ErrorCode.SAFE_REGION_CONTENT_MISMATCH


def test_overlay_checks_the_script_layout(arabic_font):
    stray = MmbnArabicSection("stray", "nowhere", 0, "test", "0" * 64, (), "")
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, sections=(*_sections(), stray))
    assert caught.value.code is ErrorCode.INVALID_REFERENCE
    spare = MmbnScriptArchive("spare", 0x08702000, (0x08010008,), 1)
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, archives=(*_archives(), spare))
    assert caught.value.code is ErrorCode.RESOURCE_SET_MISMATCH
    wrong_count = (
        MmbnScriptArchive("scene", SCENE_ADDRESS, (SCENE_POINTER,), len(SCENE) + 1),
        _archives()[1],
    )
    with pytest.raises(ClassicRetroError) as caught:
        _build(arabic_font, archives=wrong_count)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_only_the_usa_image_is_accepted(arabic_font):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_mmbn_arabic_rom(_synthetic_rom(), arabic_font)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


def test_bank_offsets_are_font_aligned():
    assert overlay.bank_offset(overlay.FONT_ADDRESS + 3 * CELL_BYTES) == 3
    assert overlay.bank_offset(overlay.FONT_ADDRESS - CELL_BYTES) == 0xFFFFFFFF
    with pytest.raises(ClassicRetroError) as caught:
        overlay.bank_offset(overlay.FONT_ADDRESS + 1)
    assert caught.value.code is ErrorCode.REFERENCE_ALIGNMENT_ERROR


def test_table_lookup_matches_a_linear_scan():
    entries = [(0x08160000 + 0x40 * n, n if n % 3 else overlay.NO_BANK) for n in range(1, 30)]
    table = struct.pack("<II", 0x08161000, len(entries))
    table += b"".join(struct.pack("<II", *entry) for entry in entries)
    for address in range(0x08160000, 0x08161080, 0x10):
        expected = overlay.NO_BANK
        if entries[0][0] <= address < 0x08161000:
            expected = [value for start, value in entries if start <= address][-1]
        assert overlay.table_lookup(table, address) == expected


def test_real_script_checks_without_the_rom(capsys):
    assert main(["targets", "check-translations", "mmbn"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["archives"] == 6 and report["sections"] >= 40
    assert report["pages_drawn"] is False


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_assembly():
    assert overlay.check_hook_code()["match"] is True


def test_extract_reads_every_original_in_the_notation():
    originals = overlay.extract_originals(
        _synthetic_rom(), sections=_sections(), archives=_archives(), verify_identity=False
    )
    assert originals == {"scene.0": SCENE[0], "scene.1": SCENE[1], "room.1": ROOM[1]}
