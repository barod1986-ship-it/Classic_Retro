from __future__ import annotations

import hashlib
import json
import shutil
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_target
from classic_retro.engines.metroid_fusion import (
    END,
    ROM_BASE,
    command_skeleton,
    is_command,
    pack_units,
    parse_notation,
    pieces_units,
    read_text,
)
from classic_retro.engines.metroid_fusion_arabic import (
    BASELINE,
    PAGE,
    SPACE,
    STRIP,
    MfRtlFont,
    build_metroid_fusion_arabic_glyph_map,
    outlined_glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import metroid_fusion_arabic as overlay
from classic_retro.rom.metroid_fusion_arabic_script import (
    MONOLOGUE_LIST,
    MfArabicMessage,
    metroid_fusion_arabic_messages,
)

TEXTS = 0x08700000
# Invented originals and translations: (monologue index, renderer, text).
ENGLISH = {
    "dusk": (8, STRIP, "Stars at dusk\nand a quiet hum.{FC00}{FD00}We fly on.{FC00}"),
    "count": (9, STRIP, "Count to three.{FC00}{FC00}{FD00}{E10A}Then land.{FC00}"),
    "log": (0, PAGE, "A longer log\nwith three lines\nof its own.{FC00}{FD00}The end.{FC00}"),
}
ARABIC = {
    "dusk": "نجوم عند الغروب\nوطنين هادئ.{FC00}{FD00}ونواصل الطيران.{FC00}",
    "count": "عد إلى ثلاثة.{FC00}{FC00}{FD00}{E10A}ثم اهبط.{FC00}",
    "log": "سجل أطول\nفيه ثلاثة أسطر\nخاصة به.{FC00}{FD00}النهاية.{FC00}",
}
VENEER_AREA = bytes(range(64))


def _english(key: str) -> tuple[int, ...]:
    return pieces_units(parse_notation(ENGLISH[key][2]))


def _synthetic_rom() -> tuple[bytes, dict[str, int]]:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - ROM_BASE : address - ROM_BASE + len(data)] = data

    put(overlay.GET_CHARACTER_WIDTH, overlay.WIDTH_ENTRY)
    put(overlay.VENEER_AREA, VENEER_AREA)
    for site in overlay.SITES:
        put(site.address, site.original)
    for address, expected in overlay.ANCHORS.items():
        put(address, expected)
    put(
        overlay.HOOK_CODE_ADDRESS,
        bytes((0xFF,)) * (overlay.REGION_END - overlay.HOOK_CODE_ADDRESS),
    )
    addresses = {}
    cursor = TEXTS
    for key, (index, _, _) in ENGLISH.items():
        data = pack_units((*_english(key), END))
        addresses[key] = cursor
        put(cursor, data)
        put(MONOLOGUE_LIST + 4 * index, struct.pack("<I", cursor))
        cursor += len(data) + 3 & ~3
    return bytes(rom), addresses


def _translations(addresses: dict[str, int]) -> tuple[MfArabicMessage, ...]:
    return tuple(
        MfArabicMessage(
            key=key,
            index=index,
            source_address=addresses[key],
            renderer=renderer,
            speaker="test",
            source_sha256=hashlib.sha256(pack_units(_english(key))).hexdigest(),
            source_skeleton=command_skeleton(_english(key)),
            notation=ARABIC[key],
        )
        for key, (index, renderer, _) in ENGLISH.items()
    )


def _fake_font(font_path=None, **_kwargs) -> MfRtlFont:
    glyph_map = build_metroid_fusion_arabic_glyph_map()
    bar = {(x, y) for x in range(3) for y in range(4, BASELINE)}
    glyph = outlined_glyph(bar, joins_left=False, joins_right=False)
    glyphs = {code: glyph for code in glyph_map.all_codes() if code != SPACE}
    return MfRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


@pytest.fixture(autouse=True)
def synthetic_veneer_area(monkeypatch):
    """The synthetic image holds invented bytes where the game's unused code is."""
    monkeypatch.setattr(overlay, "VENEER_AREA_SHA256", hashlib.sha256(VENEER_AREA).hexdigest())


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


@pytest.fixture(scope="module")
def build(synthetic, tmp_path_factory):
    rom, addresses = synthetic
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_metroid_fusion_rtl_font", _fake_font)
    patcher.setattr(overlay, "VENEER_AREA_SHA256", hashlib.sha256(VENEER_AREA).hexdigest())
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    try:
        result = overlay.build_metroid_fusion_arabic_rom(
            rom, font_file, messages=_translations(addresses), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, addresses, result


def _read(data: bytes, address: int, length: int) -> bytes:
    return data[address - ROM_BASE : address - ROM_BASE + length]


def test_width_hook_replaces_get_character_width(build):
    _, _, result = build
    entry = _read(result.rom, overlay.GET_CHARACTER_WIDTH, 8)
    # ldr r1, [pc, #0]; bx r1; .word hook_width | 1
    assert struct.unpack_from("<HH", entry) == (0x4900, 0x4708)
    (target,) = struct.unpack_from("<I", entry, 4)
    assert target == overlay.HOOKS.thumb_entry("hook_width")
    code = _read(result.rom, overlay.HOOK_CODE_ADDRESS, len(overlay.HOOK_CODE))
    assert code == overlay.HOOK_CODE


def test_every_site_calls_its_hook_through_a_veneer(build):
    _, _, result = build
    for site in overlay.SITES:
        patched = _read(result.rom, site.address, len(site.original))
        veneer = overlay.VENEERS[site.hook]
        assert bl_target(site.address, patched) == veneer.address
    for veneer in overlay.VENEERS.values():
        code = _read(result.rom, veneer.address, 16)
        if veneer.register is None:
            # bx pc; nop; ldr ip, [pc]; bx ip: the ARM part reaches the hook through ip.
            assert struct.unpack_from("<HHII", code) == (0x4778, 0x46C0, 0xE59FC000, 0xE12FFF1C)
            (target,) = struct.unpack_from("<I", code, 12)
        else:
            # ldr rN, [pc, #0]; bx rN through the register the site does not need.
            load, jump = struct.unpack_from("<HH", code)
            assert load == 0x4800 | veneer.register << 8
            assert jump == 0x4700 | veneer.register << 3
            (target,) = struct.unpack_from("<I", code, 4)
        assert target == overlay.HOOKS.thumb_entry(veneer.hook)
    # The fade keeps its loop end in ip: its veneer must not use it.
    assert overlay.VENEERS["hook_fade"].register is not None
    # The veneers stay inside the unused function they replace.
    end = max(veneer.address + len(veneer.code()) for veneer in overlay.VENEERS.values())
    assert end <= overlay.VENEER_AREA + overlay.VENEER_AREA_SIZE


def test_every_monologue_pointer_leads_to_its_arabic_text(build):
    _, _, result = build
    output = result.rom
    seen = set()
    for key, (index, _, _) in ENGLISH.items():
        (address,) = struct.unpack_from("<I", output, MONOLOGUE_LIST + 4 * index - ROM_BASE)
        assert overlay.ARABIC_TEXT_ADDRESS <= address < overlay.REGION_END
        assert address % 4 == 0 and address not in seen
        seen.add(address)
        units = read_text(output, address)
        assert command_skeleton(units) == command_skeleton(_english(key))
        glyphs = [unit for unit in units if not is_command(unit)]
        assert glyphs and all(unit in result.font.glyphs or unit == SPACE for unit in glyphs)
    assert result.report["messages"] == len(ENGLISH)
    assert result.report["hook_sites"] == len(overlay.SITES) + 1


def test_the_glyphs_and_their_widths_are_written(build):
    _, _, result = build
    sheet = result.font.sheet()
    assert _read(result.rom, overlay.FONT_ADDRESS, len(sheet)) == sheet
    widths = _read(result.rom, overlay.RTL_WIDTHS_ADDRESS, len(result.font.width_table()))
    assert widths == result.font.width_table()
    # DrawCharacter finds glyph c at 0x08682FAC + 32 * c.
    code = min(result.font.glyphs)
    assert overlay.FONT_ADDRESS == 0x08682FAC + 32 * code


def test_only_the_sites_pointers_and_padding_change(build):
    rom, _, result = build
    output = result.rom
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {(site.address - ROM_BASE) & ~0xFFF for site in overlay.SITES}
    allowed |= {(address - ROM_BASE) & ~0xFFF for address in (
        overlay.GET_CHARACTER_WIDTH, overlay.VENEER_AREA, MONOLOGUE_LIST)}  # fmt: skip
    allowed |= set(
        range(overlay.HOOK_CODE_ADDRESS - ROM_BASE, overlay.REGION_END - ROM_BASE, 0x1000)
    )
    assert changed <= allowed
    text_end = overlay.ARABIC_TEXT_ADDRESS + result.report["arabic_text_bytes"]
    assert set(output[text_end - ROM_BASE : overlay.REGION_END - ROM_BASE]) == {0xFF}


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, _, result = build
    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_stored_texts_end_on_their_final_unit_and_a_word():
    for length in range(1, 6):
        units = tuple(range(0x9000, 0x9000 + length))
        stored = overlay.stored_text(units)
        assert len(stored) % 4 == 0
        assert stored[: 2 * length + 2] == pack_units((*units, END))
        assert set(stored[2 * length + 2 :]) <= {0}


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize("damage", ["site", "entry", "anchor", "space", "padding", "veneers"])
def test_changed_anchors_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_metroid_fusion_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    if damage == "site":
        rom[overlay.SITES[3].address - ROM_BASE + 1] ^= 1
    elif damage == "entry":
        rom[overlay.GET_CHARACTER_WIDTH - ROM_BASE] ^= 1
    elif damage == "anchor":
        rom[0x080791D8 - ROM_BASE] ^= 4
    elif damage == "space":
        rom[0x08576234 + SPACE - ROM_BASE] = 5
    elif damage == "padding":
        rom[overlay.ARABIC_TEXT_ADDRESS - ROM_BASE + 7] = 0
    else:
        rom[overlay.VENEER_AREA - ROM_BASE + 9] ^= 1
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_metroid_fusion_arabic_rom(
            bytes(rom), font_file, messages=_translations(addresses), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


@pytest.mark.parametrize("damage", ["pointer", "text", "skeleton"])
def test_changed_originals_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_metroid_fusion_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    messages = list(_translations(addresses))
    count = messages[1]
    if damage == "pointer":
        struct.pack_into("<I", rom, count.pointer - ROM_BASE, addresses["dusk"])
    elif damage == "text":
        rom[addresses["count"] - ROM_BASE] ^= 1
    else:
        messages[1] = MfArabicMessage(
            count.key,
            count.index,
            count.source_address,
            count.renderer,
            count.speaker,
            count.source_sha256,
            ("{FC00}",),
            count.notation,
        )
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_metroid_fusion_arabic_rom(
            bytes(rom), font_file, messages=tuple(messages), verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_extract_gives_every_original_in_notation(synthetic):
    rom, addresses = synthetic
    originals = overlay.extract_originals(
        rom, messages=_translations(addresses), verify_identity=False
    )
    assert originals == {key: text for key, (_, _, text) in ENGLISH.items()}


def test_shipped_translations_check_without_the_rom():
    report = overlay.check_metroid_fusion_translations()
    assert report["messages"] == len(metroid_fusion_arabic_messages()) == 12
    assert report["lines_measured"] is False


def test_translations_are_measured_and_previewed_with_a_font(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_metroid_fusion_rtl_font", _fake_font)
    preview = tmp_path / "font.png"
    text_preview = tmp_path / "text.png"
    report = overlay.check_metroid_fusion_translations(tmp_path / "f.ttf", preview, text_preview)
    assert report["lines_measured"] and report["widest_line"] <= 224
    assert preview.is_file() and text_preview.is_file()


def test_encode_command_prints_the_units(capsys):
    assert main(["metroid-fusion", "encode-arabic", "ب ب\nب{FC00}"]) == 0
    payload = json.loads(capsys.readouterr().out)
    units = payload["units"].split()
    assert units[-1] == "FC00" and "FE00" in units and "0040" in units
    assert main(["metroid-fusion", "encode-arabic", "ب\nب\nب{FC00}", "--renderer", "page"]) == 0


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_source():
    assert overlay.check_hook_code()["match"] is True
