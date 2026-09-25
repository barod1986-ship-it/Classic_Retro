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
    BRIEFING,
    PAGE,
    QUESTION_BOX,
    RENDERER_DIALECTS,
    SPACE,
    STRIP,
    MfRtlFont,
    build_metroid_fusion_arabic_glyph_map,
    outlined_glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import metroid_fusion_arabic as overlay
from classic_retro.rom.metroid_fusion_arabic_script import (
    MESSAGE_LIST,
    MONOLOGUE_LIST,
    NAVIGATION_LIST,
    MfArabicMessage,
    metroid_fusion_arabic_messages,
)

TEXTS = 0x08700000
# Invented originals and translations: (list, index, renderer, text).
ENGLISH = {
    "dusk": (MONOLOGUE_LIST, 8, STRIP, "Stars at dusk\nand a quiet hum.{FC00}{FD00}We fly on.{FC00}"),
    "count": (MONOLOGUE_LIST, 9, STRIP, "Count to three.{FC00}{FC00}{FD00}{E10A}Then land.{FC00}"),
    "log": (
        MONOLOGUE_LIST, 0, PAGE, "A longer log\nwith three lines\nof its own.{FC00}{FD00}The end.{FC00}"
    ),
    "orders": (
        NAVIGATION_LIST, 0, BRIEFING,
        "{B003}Head to the {8102}Old Dock{8100}\nright now.{FD00}Keep your eyes open.{FB00}"
        "Then report {8103}back{8100}.",
    ),
    "ready": (MESSAGE_LIST, 43, QUESTION_BOX, "{8020}Ready to go{char 041F}\n{8057}{8340}Yes {83A0}No"),
}  # fmt: skip
ARABIC = {
    "dusk": "نجوم عند الغروب\nوطنين هادئ.{FC00}{FD00}ونواصل الطيران.{FC00}",
    "count": "عد إلى ثلاثة.{FC00}{FC00}{FD00}{E10A}ثم اهبط.{FC00}",
    "log": "سجل أطول\nفيه ثلاثة أسطر\nخاصة به.{FC00}{FD00}النهاية.{FC00}",
    "orders": (
        "{B003}توجهي إلى {8102}الرصيف القديم{8100} الآن.{FD00}ابقي متيقظة.{FB00}"
        "ثم عودي {8103}للإبلاغ{8100}."
    ),
    "ready": "{8040}هل أنت جاهزة؟\n{8057}{8340}نعم {83A0}لا",
}
VENEER_AREA = bytes(range(64))


def _english(key: str) -> tuple[int, ...]:
    _, _, renderer, text = ENGLISH[key]
    dialect = RENDERER_DIALECTS[renderer]
    return pieces_units(parse_notation(text, dialect), dialect)


def _synthetic_rom() -> tuple[bytes, dict[str, int]]:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - ROM_BASE : address - ROM_BASE + len(data)] = data

    put(overlay.GET_CHARACTER_WIDTH, overlay.WIDTH_ENTRY)
    put(overlay.VENEER_AREA, VENEER_AREA)
    for site in overlay.SITES:
        put(site.address, site.original)
    for sites in overlay.QUESTION_SITES.values():
        for question_site in sites:
            put(question_site.address, question_site.code(question_site.original))
    for address, expected in overlay.ANCHORS.items():
        put(address, expected)
    put(
        overlay.HOOK_CODE_ADDRESS,
        bytes((0xFF,)) * (overlay.IMAGE_END - overlay.HOOK_CODE_ADDRESS),
    )
    addresses = {}
    cursor = TEXTS
    for key, (text_list, index, _, _) in ENGLISH.items():
        data = pack_units((*_english(key), END))
        addresses[key] = cursor
        put(cursor, data)
        put(text_list.address + 4 * index, struct.pack("<I", cursor))
        cursor += len(data) + 3 & ~3
    return bytes(rom), addresses


def _translations(addresses: dict[str, int]) -> tuple[MfArabicMessage, ...]:
    return tuple(
        MfArabicMessage(
            key=key,
            text_list=text_list,
            index=index,
            source_address=addresses[key],
            renderer=renderer,
            speaker="test",
            source_sha256=hashlib.sha256(pack_units(_english(key))).hexdigest(),
            source_skeleton=command_skeleton(_english(key), RENDERER_DIALECTS[renderer]),
            notation=ARABIC[key],
        )
        for key, (text_list, index, renderer, _) in ENGLISH.items()
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


def test_every_pointer_leads_to_its_arabic_text(build):
    _, _, result = build
    output = result.rom
    seen = set()
    for key, (text_list, index, renderer, _) in ENGLISH.items():
        dialect = RENDERER_DIALECTS[renderer]
        (address,) = struct.unpack_from("<I", output, text_list.address + 4 * index - ROM_BASE)
        assert overlay.ARABIC_TEXT_ADDRESS <= address < overlay.ARABIC_TEXT_END
        assert address % 4 == 0 and address not in seen
        seen.add(address)
        units = read_text(output, address)
        assert command_skeleton(units, dialect) == command_skeleton(_english(key), dialect)
        glyphs = [unit for unit in units if not is_command(unit, dialect)]
        assert glyphs and all(unit in result.font.glyphs or unit == SPACE for unit in glyphs)
    assert result.report["messages"] == len(ENGLISH)
    assert result.report["hook_sites"] == len(overlay.SITES) + 1


def test_a_translated_question_moves_its_cursor_and_swaps_its_keys(build):
    rom, _, result = build
    # The fake glyphs are 5 pixels wide: Yes (3 glyphs) at 64..79 and No (2) at
    # 144..154 on the line; the cursor stands 12 pixels left of their mirrored end.
    expected = {
        overlay.YES: 8 + 224 - 79 - 12,
        overlay.NO: 8 + 224 - 154 - 12,
        overlay.YES_KEY: overlay.KEY_RIGHT,
        overlay.NO_KEY: overlay.KEY_LEFT,
    }
    for site in overlay.QUESTION_SITES[43]:
        assert _read(result.rom, site.address, 2) == site.code(expected[site.role])
    # Message 44 is not translated here: its question keeps the game's code.
    for site in overlay.QUESTION_SITES[44]:
        assert _read(result.rom, site.address, 2) == _read(rom, site.address, 2)
    assert result.report["question_sites"] == len(overlay.QUESTION_SITES[43])


def test_the_glyphs_and_their_widths_are_written(build):
    _, _, result = build
    sheet = result.font.sheet()
    assert _read(result.rom, overlay.FONT_ADDRESS, len(sheet)) == sheet
    widths = _read(result.rom, overlay.RTL_WIDTHS_ADDRESS, len(result.font.width_table()))
    assert widths == result.font.width_table()
    # DrawCharacter finds glyph c at 0x08682FAC + 32 * c.
    code = min(result.font.glyphs)
    assert overlay.FONT_ADDRESS == 0x08682FAC + 32 * code
    # The hooks, widths, bank and sheet follow each other in the padding.
    assert overlay.HOOK_CODE_ADDRESS + len(overlay.HOOK_CODE) <= overlay.RTL_WIDTHS_ADDRESS
    assert overlay.RTL_WIDTHS_ADDRESS + len(widths) <= overlay.ARABIC_TEXT_ADDRESS
    assert overlay.ARABIC_TEXT_END <= overlay.FONT_ADDRESS < overlay.FONT_END <= overlay.IMAGE_END


def test_only_the_sites_pointers_and_padding_change(build):
    rom, _, result = build
    output = result.rom
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    written = [site.address for site in overlay.SITES]
    written += [site.address for sites in overlay.QUESTION_SITES.values() for site in sites]
    written += [overlay.GET_CHARACTER_WIDTH, overlay.VENEER_AREA]
    written += [text_list.address + 4 * index for text_list, index, _, _ in ENGLISH.values()]
    allowed = {(address - ROM_BASE) & ~0xFFF for address in written}
    allowed |= set(
        range(overlay.HOOK_CODE_ADDRESS - ROM_BASE, overlay.IMAGE_END - ROM_BASE, 0x1000)
    )
    assert changed <= allowed
    text_end = overlay.ARABIC_TEXT_ADDRESS + result.report["arabic_text_bytes"]
    assert set(output[text_end - ROM_BASE : overlay.ARABIC_TEXT_END - ROM_BASE]) == {0xFF}


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


@pytest.mark.parametrize(
    "damage", ["site", "entry", "anchor", "space", "padding", "font", "veneers", "question"]
)
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
    elif damage == "font":
        rom[overlay.FONT_ADDRESS - ROM_BASE + 0x41] = 0
    elif damage == "veneers":
        rom[overlay.VENEER_AREA - ROM_BASE + 9] ^= 1
    else:
        rom[overlay.QUESTION_SITES[44][0].address - ROM_BASE] ^= 1
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
            count.text_list,
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
    assert originals == {key: text for key, (_, _, _, text) in ENGLISH.items()}


@pytest.mark.parametrize("wrong", ["list", "index", "question", "twice"])
def test_texts_out_of_place_are_refused(synthetic, wrong):
    _, addresses = synthetic
    messages = list(_translations(addresses))
    ready = messages[-1]
    if wrong == "list":
        messages[-1] = _moved(ready, text_list=NAVIGATION_LIST)
    elif wrong == "index":
        messages[-1] = _moved(ready, index=overlay.MESSAGE_LIST.length)
    elif wrong == "question":
        messages[-1] = _moved(ready, index=42)
    else:
        messages.append(_moved(messages[0], key="dusk again"))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages(overlay.MfArabicEncoder(_fake_font()), tuple(messages))
    assert caught.value.code in {ErrorCode.INVALID_REFERENCE, ErrorCode.DUPLICATE_ENTRY_ID}


def _moved(message: MfArabicMessage, **changes) -> MfArabicMessage:
    fields = {name: getattr(message, name) for name in MfArabicMessage.__dataclass_fields__}
    return MfArabicMessage(**(fields | changes))


def test_shipped_translations_check_without_the_rom():
    report = overlay.check_metroid_fusion_translations()
    assert report["messages"] == len(metroid_fusion_arabic_messages()) == 18
    assert report["lines_measured"] is False
    lists = {message.key: message.text_list for message in metroid_fusion_arabic_messages()}
    assert lists["first_briefing"] == NAVIGATION_LIST
    assert lists["objective_clear"] == lists["confirm_objective"] == MESSAGE_LIST


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
    capsys.readouterr()
    briefing = "{8102}ب{8100} ب{FD00}ب"
    assert main(["metroid-fusion", "encode-arabic", briefing, "--renderer", "briefing"]) == 0
    assert json.loads(capsys.readouterr().out)["units"].split()[0] == "8102"
    question = "{8040}ب\n{8340}ب {83A0}ب"
    assert main(["metroid-fusion", "encode-arabic", question, "--renderer", "question"]) == 0


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_source():
    assert overlay.check_hook_code()["match"] is True
