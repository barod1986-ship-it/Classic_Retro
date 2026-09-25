from __future__ import annotations

import hashlib
import json
import shutil
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import NOP, bl_target
from classic_retro.engines.advance_wars import (
    FONT_POINTERS,
    FONT_WIDTHS,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    AwFont,
    command_skeleton,
    parse_notation,
    read_message,
    text_bytes,
)
from classic_retro.engines.advance_wars_arabic import (
    INK,
    LATIN_COPIES,
    LATIN_WIDTHS,
    SPACE,
    SPACE_ADVANCE,
    THIN_SPACE,
    AwRtlFont,
    AwRtlGlyph,
    build_advance_wars_arabic_glyph_map,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import advance_wars_arabic as overlay
from classic_retro.rom.advance_wars_arabic_script import (
    MESSAGE_COMMAND,
    AwArabicMessage,
    advance_wars_arabic_messages,
)

BASE = 0x08000000
MESSAGES = 0x082EF000
SCRIPT = 0x082F0800
GLYPHS = 0x08117000
# Invented originals and translations.
ENGLISH = {
    "greeting": "Good morning, recruit!{0F}",
    "ask": "Shall we begin?\n{16}",
    "roll_call": "Welcome aboard,\n{15}.{0F}Stay sharp.{0F}",
}
ARABIC = {
    "greeting": "صباح الخير أيها المجند!{0F}",
    "ask": "هل نبدأ؟\n{16}",
    "roll_call": "أهلا بك معنا يا\n{15}.{0F}كن يقظا.{0F}",
}


def _english(key: str) -> bytes:
    return text_bytes(parse_notation(ENGLISH[key]))


def _synthetic_rom(latin_widths: dict[str, int] | None = None) -> tuple[bytes, dict[str, int]]:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    for site in overlay.SITES:
        put(site.address, site.original)
    for address, expected in overlay.ANCHORS.items():
        put(address, expected)
    # The game's font: every glyph points at empty rows but the Latin copies'.
    for code in range(256):
        put(FONT_POINTERS + 4 * code, struct.pack("<I", GLYPHS))
    for number, (character, code) in enumerate(LATIN_COPIES.items(), 1):
        width = (latin_widths or {}).get(character, LATIN_WIDTHS[character])
        rows = bytes(
            (INK if y in range(5, 13) else 0)
            for y in range(GLYPH_ROWS)
            for _ in range((width + 1) // 2)
        )
        put(GLYPHS + 64 * number, rows)
        put(FONT_POINTERS + 4 * code, struct.pack("<I", GLYPHS + 64 * number))
        put(FONT_WIDTHS + code, bytes((width,)))
    put(
        overlay.HOOK_CODE_ADDRESS, bytes((0xFF,)) * (overlay.REGION_END - overlay.HOOK_CODE_ADDRESS)
    )
    addresses = {}
    cursor = MESSAGES
    for number, key in enumerate(ENGLISH):
        body = _english(key)
        addresses[key] = cursor
        put(cursor, body + b"\x00")
        cursor += len(body) + 4 & ~3
        record = SCRIPT + 16 * number
        put(record, struct.pack("<4I", MESSAGE_COMMAND, addresses[key], 0, 0))
    return bytes(rom), addresses


def _translations(addresses: dict[str, int]) -> tuple[AwArabicMessage, ...]:
    return tuple(
        AwArabicMessage(
            key=key,
            pointer=SCRIPT + 16 * number + 4,
            source_address=addresses[key],
            speaker="test",
            source_sha256=hashlib.sha256(_english(key)).hexdigest(),
            source_skeleton=command_skeleton(_english(key)),
            notation=ARABIC[key],
        )
        for number, key in enumerate(ENGLISH)
    )


def _fake_font(font_path, latin=None, **_kwargs) -> AwRtlFont:
    glyph_map = build_advance_wars_arabic_glyph_map()
    ink = tuple(
        tuple(INK if x < 4 and 4 <= y < 12 else 0 for x in range(GLYPH_COLUMNS))
        for y in range(GLYPH_ROWS)
    )
    empty = tuple((0,) * GLYPH_COLUMNS for _ in range(GLYPH_ROWS))
    glyphs = {code: AwRtlGlyph(5, ink) for code in glyph_map.all_codes()}
    for character in LATIN_COPIES:
        glyphs[glyph_map.code(character)] = latin[character]
    glyphs[SPACE] = AwRtlGlyph(SPACE_ADVANCE, empty)
    glyphs[glyph_map.code(THIN_SPACE)] = AwRtlGlyph(1, empty)
    return AwRtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=10)


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


@pytest.fixture(scope="module")
def build(synthetic, tmp_path_factory):
    rom, addresses = synthetic
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_advance_wars_rtl_font", _fake_font)
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    try:
        result = overlay.build_advance_wars_arabic_rom(
            rom, font_file, messages=_translations(addresses), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, addresses, result


def test_hooks_are_written_and_every_site_calls_its_hook(build):
    _, _, result = build
    output = result.rom

    assert len(output) == overlay.USA_SIZE
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    for site in overlay.SITES:
        patched = output[site.address - BASE : site.address - BASE + len(site.original)]
        assert bl_target(site.address, patched[:4]) == overlay.HOOKS.symbol_address(site.hook)
    arrow = next(site for site in overlay.SITES if site.hook == "hook_arrow")
    patched = output[arrow.address - BASE : arrow.address - BASE + len(arrow.original)]
    (branch,) = struct.unpack_from("<H", patched, 4)
    assert branch >> 11 == 0x1C
    assert arrow.address + 8 + ((branch & 0x7FF) << 1) == arrow.resume
    assert patched[6:] == NOP * 6
    # The hooks test the Arabic bank and draw from the font the overlay writes.
    for address in (overlay.ARABIC_TEXT_ADDRESS, overlay.FONT_ADDRESS):
        assert struct.pack("<I", address) in overlay.HOOK_CODE


def test_every_script_pointer_leads_to_its_arabic_message(build):
    rom, _, result = build
    output = result.rom
    font = result.font

    seen = set()
    for number, key in enumerate(ENGLISH):
        record = SCRIPT + 16 * number
        assert struct.unpack_from("<I", output, record - BASE)[0] == MESSAGE_COMMAND
        (address,) = struct.unpack_from("<I", output, record + 4 - BASE)
        assert overlay.ARABIC_TEXT_ADDRESS <= address < overlay.REGION_END
        assert address % 4 == 0 and address not in seen
        seen.add(address)
        body = read_message(output, address)
        assert command_skeleton(body) == command_skeleton(_english(key))
        # At least two zeros end every message.
        end = address - BASE + len(body)
        assert output[end : end + 2] == b"\x00\x00"
        glyphs = [byte for byte in body if byte not in (0x0D, 0x0F, 0x15, 0x16)]
        assert glyphs and all(byte in font.glyphs for byte in glyphs)
    assert result.report["messages"] == len(ENGLISH)
    assert result.report["hook_sites"] == len(overlay.SITES)


def test_the_font_is_written_with_the_games_latin_glyphs(build):
    _, _, result = build
    output = result.rom
    data = result.font.tables(overlay.FONT_ADDRESS)
    start = overlay.FONT_ADDRESS - BASE
    assert output[start : start + len(data)] == data
    widths = output[start + 1024 : start + 1280]
    for character, code in LATIN_COPIES.items():
        assert widths[code] == LATIN_WIDTHS[character] + 1


def test_only_the_sites_pointers_and_padding_change(build):
    rom, _, result = build
    output = result.rom
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {(site.address - BASE) & ~0xFFF for site in overlay.SITES}
    allowed |= {(SCRIPT - BASE) & ~0xFFF}
    allowed |= set(range(overlay.HOOK_CODE_ADDRESS - BASE, overlay.REGION_END - BASE, 0x1000))
    assert changed <= allowed
    text_end = overlay.ARABIC_TEXT_ADDRESS + result.report["arabic_text_bytes"]
    assert set(output[text_end - BASE : overlay.REGION_END - BASE]) == {0xFF}


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, _, result = build
    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_stored_messages_end_with_at_least_two_zeros():
    for length in range(1, 9):
        stored = overlay.stored_message(b"x" * length)
        assert len(stored) % 4 == 0 and stored[length:] == bytes(len(stored) - length)
        assert len(stored) - length >= 2


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize("damage", ["site", "anchor", "padding", "latin"])
def test_changed_anchors_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_advance_wars_rtl_font", _fake_font)
    rom, addresses = synthetic
    if damage == "latin":
        rom, addresses = _synthetic_rom(latin_widths={"!": 4})
    rom = bytearray(rom)
    if damage == "site":
        rom[overlay.SITES[4].address - BASE + 3] ^= 1
    elif damage == "anchor":
        rom[0x0801796E - BASE] = 8
    elif damage == "padding":
        rom[overlay.ARABIC_TEXT_ADDRESS - BASE + 5] = 0
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_advance_wars_arabic_rom(
            bytes(rom), font_file, messages=_translations(addresses), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


@pytest.mark.parametrize("damage", ["command", "pointer", "text", "skeleton"])
def test_changed_originals_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_advance_wars_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    messages = list(_translations(addresses))
    ask = messages[1]
    if damage == "command":
        struct.pack_into("<I", rom, ask.pointer - 4 - BASE, 0x18)
    elif damage == "pointer":
        struct.pack_into("<I", rom, ask.pointer - BASE, addresses["greeting"])
    elif damage == "text":
        rom[addresses["ask"] - BASE] ^= 0x20
    else:
        messages[1] = AwArabicMessage(
            ask.key,
            ask.pointer,
            ask.source_address,
            ask.speaker,
            ask.source_sha256,
            ("{0F}",),
            ask.notation,
        )
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_advance_wars_arabic_rom(
            bytes(rom), font_file, messages=tuple(messages), verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_extract_gives_every_original_in_notation(synthetic):
    rom, addresses = synthetic
    originals = overlay.extract_originals(
        rom, messages=_translations(addresses), verify_identity=False
    )
    assert originals == ENGLISH


def test_shipped_translations_check_without_the_rom():
    report = overlay.check_advance_wars_translations()
    assert report["messages"] == len(advance_wars_arabic_messages()) == 14
    assert report["lines_measured"] is False


def test_translations_are_measured_and_previewed_with_a_font(synthetic, tmp_path, monkeypatch):
    latin = overlay.latin_rtl_glyphs(AwFont.read(synthetic[0]))
    monkeypatch.setattr(
        overlay, "build_advance_wars_rtl_font", lambda path: _fake_font(path, latin=latin)
    )
    preview = tmp_path / "font.png"
    text_preview = tmp_path / "text.png"
    report = overlay.check_advance_wars_translations(tmp_path / "f.ttf", preview, text_preview)
    assert report["lines_measured"] and report["widest_line"] <= 176
    assert preview.is_file() and text_preview.is_file()


def test_encode_command_prints_the_bytes(capsys):
    assert main(["advance-wars", "encode-arabic", "هل نبدأ؟\n{16}"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bytes"].endswith("16") and "0d" in payload["bytes"]


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_source():
    assert overlay.check_hook_code()["match"] is True
