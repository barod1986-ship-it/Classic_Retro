from __future__ import annotations

import hashlib
import json
import shutil
import struct

import pytest

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import NOP, bl_target
from classic_retro.engines.tactics_ogre import (
    GLYPH_CODES,
    INK,
    NAME,
    NAME_LIST,
    ROM_BASE,
    SCENE_TEXTS,
    TABLE_END,
    command_skeleton,
    parse_notation,
    pieces_bytes,
    read_block,
    read_message,
)
from classic_retro.engines.tactics_ogre_arabic import (
    BASELINE,
    SPACE_WIDTH,
    ToRtlFont,
    rtl_glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import tactics_ogre_arabic as overlay
from classic_retro.rom.tactics_ogre_arabic_script import (
    BLOCK_ADDRESS,
    ToArabicMessage,
    ToArabicName,
    tactics_ogre_arabic_messages,
    tactics_ogre_arabic_names,
)

# An invented block: (header, original); the translated ones by key.
BLOCK = (
    (0x0031, "{8B}Old Sailor{8C}\nFair winds today.{8D}{8A}"),
    (0x0021, "A quiet note\nleft in English.{8D}{8A}"),
    (0x0031, "{8B}{8705}{8C}\nSee you at dawn,\n friend.{8E}{8A}Rest well.{8D}{8A}"),
    (0x0011, "unused{8D}{8A}"),
)
TRANSLATED = {"sailor": 0, "dawn": 2}
ARABIC = {
    "sailor": "{8B}بحار عجوز{8C}\nالرياح طيبة اليوم.{8D}{8A}",
    "dawn": "{8B}{8705}{8C}\nأراك عند الفجر\nيا صديقي.{8E}{8A}نم جيدا.{8D}{8A}",
}
NAME_ADDRESS = 0x08700001
NAME_ENGLISH = "Tarn"
NAME_ARABIC = "تارن"
VENEER_AREA = bytes(range(overlay.VENEER_AREA_SIZE))


def _data(text: str) -> bytes:
    return pieces_bytes(parse_notation(text))


def _block() -> tuple[bytes, tuple[int, ...]]:
    table_size = 2 * (len(BLOCK) + 1)
    messages = b""
    offsets = []
    for header, text in BLOCK:
        offsets.append(table_size + len(messages))
        stored = struct.pack("<H", header) + _data(text) + b"\xff"
        messages += stored + bytes(len(stored) % 2)
    table = struct.pack(f"<{len(BLOCK) + 1}H", *offsets, TABLE_END)
    return table + messages, tuple(offsets)


def _synthetic_rom() -> bytes:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - ROM_BASE : address - ROM_BASE + len(data)] = data

    for site in overlay.SITES:
        put(site.address, site.original)
    for address, expected in overlay.ANCHORS.items():
        put(address, expected)
    put(overlay.VENEER_AREA, VENEER_AREA)
    put(BLOCK_ADDRESS, _block()[0])
    put(NAME_LIST + 4 * 5, struct.pack("<I", NAME_ADDRESS))
    put(NAME_ADDRESS, _data(NAME_ENGLISH) + b"\xff")
    return bytes(rom)


def _messages() -> tuple[ToArabicMessage, ...]:
    _, offsets = _block()
    return tuple(
        ToArabicMessage(
            key=key,
            index=index,
            source_address=BLOCK_ADDRESS + offsets[index],
            header=BLOCK[index][0],
            speaker="test",
            source_sha256=hashlib.sha256(_data(BLOCK[index][1])).hexdigest(),
            source_skeleton=command_skeleton(_data(BLOCK[index][1])),
            notation=ARABIC[key],
        )
        for key, index in TRANSLATED.items()
    )


def _names() -> tuple[ToArabicName, ...]:
    digest = hashlib.sha256(_data(NAME_ENGLISH)).hexdigest()
    return (ToArabicName("tarn", 5, NAME_ADDRESS, digest, NAME_ARABIC),)


def _fake_font(font_path=None, glyph_map: GlyphCodes | None = None, **_kwargs) -> ToRtlFont:
    """Every glyph a bar 5 pixels wide; the space is the real one."""
    assert glyph_map is not None
    bar = rtl_glyph({(x, y): INK for x in range(4) for y in range(4, BASELINE)}, 5)
    glyphs = {
        codes[0]: rtl_glyph({}, SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return ToRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


@pytest.fixture(autouse=True)
def synthetic_block(monkeypatch):
    """The synthetic image holds an invented block and invented code where the game's is."""
    block, _ = _block()
    monkeypatch.setattr(overlay, "VENEER_AREA_SHA256", hashlib.sha256(VENEER_AREA).hexdigest())
    monkeypatch.setattr(overlay, "BLOCK_END", BLOCK_ADDRESS + len(block))
    monkeypatch.setattr(overlay, "BLOCK_SHA256", hashlib.sha256(block).hexdigest())
    monkeypatch.setattr(overlay, "BLOCK_MESSAGES", len(BLOCK))
    monkeypatch.setattr(overlay, "build_tactics_ogre_rtl_font", _fake_font)


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


def _build(rom: bytes, tmp_path, **changes):
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    arguments = {"messages": _messages(), "names": _names(), "verify_identity": False} | changes
    return overlay.build_tactics_ogre_arabic_rom(rom, font_file, **arguments)


@pytest.fixture
def build(synthetic, tmp_path):
    return synthetic, _build(synthetic, tmp_path)


def _read(data: bytes, address: int, length: int) -> bytes:
    return data[address - ROM_BASE : address - ROM_BASE + length]


def test_every_site_calls_its_hook_through_a_veneer(build):
    _, result = build
    for site in overlay.SITES:
        patched = _read(result.rom, site.address, len(site.original))
        veneer = overlay.VENEERS[site.hook]
        assert bl_target(site.address, patched[:4]) == veneer.address
        # The rest of the site does nothing, and the code goes on after it.
        assert patched[4:] == NOP * ((len(site.original) - 4) // 2)
    width = overlay.VENEERS["hook_width"]
    code = _read(result.rom, width.address, 8)
    # ldr r1, [pc, #0]; bx r1: r1 is set again after the site.
    assert struct.unpack_from("<HH", code) == (0x4900, 0x4708)
    assert struct.unpack_from("<I", code, 4)[0] == overlay.HOOKS.thumb_entry("hook_width")
    draw = overlay.VENEERS["hook_draw"]
    code = _read(result.rom, draw.address, 16)
    # bx pc; nop; ldr ip, [pc]; bx ip: a call may clobber ip.
    assert struct.unpack_from("<HHII", code) == (0x4778, 0x46C0, 0xE59FC000, 0xE12FFF1C)
    assert struct.unpack_from("<I", code, 12)[0] == overlay.HOOKS.thumb_entry("hook_draw")
    end = max(veneer.address + len(veneer.code()) for veneer in overlay.VENEERS.values())
    assert end <= overlay.VENEER_AREA + overlay.VENEER_AREA_SIZE
    assert _read(result.rom, overlay.HOOK_CODE_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE


def test_the_scene_entries_lead_to_the_copied_block(build):
    rom, result = build
    output = result.rom
    for scene in overlay.SCENE_ENTRIES:
        (offset,) = struct.unpack_from("<I", output, SCENE_TEXTS + 4 * scene - ROM_BASE)
        assert SCENE_TEXTS + offset == overlay.BLOCK_AREA
    block = read_block(output, overlay.BLOCK_AREA)
    assert len(block.offsets) == len(BLOCK)
    for index, (header, text) in enumerate(BLOCK):
        address = block.message_address(index)
        in_bank = overlay.ARABIC_TEXT_ADDRESS <= address < overlay.ARABIC_TEXT_END
        assert address % 2 == 0 and in_bank == (index in TRANSLATED.values())
        stored_header, data = read_message(output, address)
        assert stored_header == header
        if not in_bank:
            # Left in English, as the image had it, before the bank.
            assert data == _data(text) and address < overlay.ARABIC_TEXT_ADDRESS
            continue
        assert command_skeleton(data) != ()
        assert all(code < GLYPH_CODES or code >= 0x88 for code in data)
    # The original block stays where it was.
    assert _read(output, BLOCK_ADDRESS, 64) == _read(rom, BLOCK_ADDRESS, 64)
    assert result.report["messages"] == len(TRANSLATED) and result.report["names"] == 1
    assert result.report["scene_entries"] == 2 and result.report["hook_sites"] == 2


def test_a_name_of_the_list_is_written_out_in_arabic(build):
    _, result = build
    block = read_block(result.rom, overlay.BLOCK_AREA)
    _, data = read_message(result.rom, block.message_address(TRANSLATED["dawn"]))
    assert NAME not in data
    # The name's four letters, then the typewriter again: {8C}.
    assert data[0] == 0x8B and data[5] == 0x8C


def test_the_glyphs_and_their_widths_are_written(build):
    _, result = build
    widths = result.font.width_table()
    glyphs = result.font.glyph_table()
    assert _read(result.rom, overlay.RTL_WIDTHS_ADDRESS, len(widths)) == widths
    assert _read(result.rom, overlay.RTL_GLYPHS_ADDRESS, len(glyphs)) == glyphs
    assert len(widths) == GLYPH_CODES and widths[0] == widths[1] == 0
    # The data's end, the hooks, the widths, the glyphs, the block, then the bank.
    assert overlay.DATA_END <= overlay.HOOK_CODE_ADDRESS
    assert overlay.HOOK_CODE_ADDRESS + len(overlay.HOOK_CODE) <= overlay.RTL_WIDTHS_ADDRESS
    assert overlay.RTL_WIDTHS_ADDRESS + GLYPH_CODES <= overlay.RTL_GLYPHS_ADDRESS
    assert overlay.RTL_GLYPHS_END <= overlay.BLOCK_AREA < overlay.ARABIC_TEXT_ADDRESS
    assert overlay.ARABIC_TEXT_END == overlay.IMAGE_END


def test_only_the_sites_entries_and_padding_change(build):
    rom, result = build
    output = result.rom
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    written = [site.address for site in overlay.SITES]
    written += [overlay.VENEER_AREA, SCENE_TEXTS]
    allowed = {(address - ROM_BASE) & ~0xFFF for address in written}
    allowed |= set(range(overlay.DATA_END - ROM_BASE & ~0xFFF, overlay.USA_SIZE, 0x1000))
    assert changed <= allowed
    text_end = overlay.ARABIC_TEXT_ADDRESS + result.report["arabic_text_bytes"]
    assert set(output[text_end - ROM_BASE :]) == {0}


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, result = build
    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_stored_messages_end_on_ff_and_a_halfword():
    for length in range(1, 5):
        data = bytes(range(length))
        stored = overlay.stored_message(0x0021, data)
        assert len(stored) % 2 == 0
        assert stored[: 3 + length] == b"\x21\x00" + data + b"\xff"
        assert set(stored[3 + length :]) <= {0}


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize(
    "damage", ["site", "anchor", "veneers", "padding", "block", "entry", "messages"]
)
def test_changed_anchors_are_refused(synthetic, tmp_path, monkeypatch, damage):
    rom = bytearray(synthetic)
    if damage == "site":
        rom[overlay.SITES[0].address - ROM_BASE + 1] ^= 1
    elif damage == "anchor":
        rom[0x0801BFF8 - ROM_BASE] ^= 4
    elif damage == "veneers":
        rom[overlay.VENEER_AREA - ROM_BASE + 9] ^= 1
    elif damage == "padding":
        rom[overlay.ARABIC_TEXT_ADDRESS - ROM_BASE + 7] = 1
    elif damage == "block":
        rom[BLOCK_ADDRESS - ROM_BASE + 40] ^= 1
    elif damage == "entry":
        # A third scene reads the block.
        struct.pack_into("<I", rom, SCENE_TEXTS + 4 * 9 - ROM_BASE, BLOCK_ADDRESS - SCENE_TEXTS)
    else:
        monkeypatch.setattr(overlay, "BLOCK_MESSAGES", len(BLOCK) + 1)
    with pytest.raises(ClassicRetroError) as caught:
        _build(bytes(rom), tmp_path)
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


def _changed(message: ToArabicMessage, **changes) -> ToArabicMessage:
    fields = {name: getattr(message, name) for name in ToArabicMessage.__dataclass_fields__}
    return ToArabicMessage(**(fields | changes))


@pytest.mark.parametrize("damage", ["digest", "header", "skeleton", "address", "name"])
def test_changed_originals_are_refused(synthetic, tmp_path, damage):
    messages = list(_messages())
    names = _names()
    dawn = messages[1]
    if damage == "digest":
        messages[1] = _changed(dawn, source_sha256="0" * 64)
    elif damage == "header":
        messages[1] = _changed(dawn, header=0x0021)
    elif damage == "skeleton":
        messages[1] = _changed(dawn, source_skeleton=("{8D}",))
    elif damage == "address":
        messages[1] = _changed(dawn, source_address=dawn.source_address + 2)
    else:
        names = (ToArabicName("tarn", 5, NAME_ADDRESS, "0" * 64, NAME_ARABIC),)
    with pytest.raises(ClassicRetroError) as caught:
        _build(synthetic, tmp_path, messages=tuple(messages), names=names)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize("wrong", ["index", "twice", "same message"])
def test_messages_out_of_place_are_refused(synthetic, tmp_path, wrong):
    messages = list(_messages())
    if wrong == "index":
        messages[1] = _changed(messages[1], index=len(BLOCK))
    elif wrong == "twice":
        messages.append(messages[0])
    else:
        messages.append(_changed(messages[0], key="sailor again"))
    with pytest.raises(ClassicRetroError) as caught:
        _build(synthetic, tmp_path, messages=tuple(messages))
    assert caught.value.code in {ErrorCode.INVALID_REFERENCE, ErrorCode.DUPLICATE_ENTRY_ID}


def test_extract_gives_every_original_in_notation(synthetic):
    originals = overlay.extract_originals(
        synthetic, messages=_messages(), names=_names(), verify_identity=False
    )
    assert originals == {
        **{key: BLOCK[index][1] for key, index in TRANSLATED.items()},
        "tarn": NAME_ENGLISH,
    }


def test_shipped_translations_check_without_the_rom():
    report = overlay.check_tactics_ogre_translations()
    messages = tactics_ogre_arabic_messages()
    assert report["messages"] == len(messages) == 15
    assert report["names"] == len(tactics_ogre_arabic_names()) == 1
    assert report["lines_measured"] is False
    assert report["rtl_glyphs"] <= len(range(2, GLYPH_CODES))
    # In the order the game shows them: messages 0 to 4, 13 to 15, 5 to 8, 10 to 12.
    assert [message.index for message in messages] == [
        0, 1, 2, 3, 4, 13, 14, 15, 5, 6, 7, 8, 10, 11, 12,
    ]  # fmt: skip
    assert {message.lines_per_page for message in messages} == {2, 3}
    assert all(message.source_address > BLOCK_ADDRESS for message in messages)


def test_translations_are_measured_and_previewed_with_a_font(tmp_path):
    preview = tmp_path / "font.png"
    text_preview = tmp_path / "text.png"
    report = overlay.check_tactics_ogre_translations(tmp_path / "f.ttf", preview, text_preview)
    assert report["lines_measured"] and report["widest_line"] <= overlay.LINE_WIDTH
    assert preview.is_file() and text_preview.is_file()
    with pytest.raises(ClassicRetroError) as caught:
        overlay.check_tactics_ogre_translations(None, preview)
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_encode_command_prints_the_bytes(capsys):
    assert main(["tactics-ogre", "encode-arabic", "{8B}{8705}{8C}\nب ب.{8D}{8A}"]) == 0
    payload = json.loads(capsys.readouterr().out)
    data = payload["bytes"].split()
    assert data[0] == "8B" and data[-2:] == ["8D", "8A"] and "87" not in data
    assert payload["count"] == len(data)
    assert main(["tactics-ogre", "encode-arabic", "ب\nب\nب", "--lines", "2"]) != 0
    assert "TEXT_BOX_OVERFLOW" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_source():
    assert overlay.check_hook_code()["match"] is True
