from __future__ import annotations

import hashlib
import json
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pmd import (
    ENTRY_BYTES,
    GLYPH_BYTES,
    GLYPH_COLUMNS,
    GLYPH_ROWS,
    PmdCharmap,
    PmdGlyphEntry,
    command_skeleton,
    glyph_bitmap,
    read_string,
)
from classic_retro.engines.pmd_arabic import (
    ARABIC_LEAD,
    LATIN_COPIES,
    RTL_FLAG,
    SPACE_ADVANCE,
    USA_LATIN_WIDTHS,
    PmdRtlFont,
    PmdRtlGlyph,
    PmdTextBox,
    build_pmd_arabic_glyph_map,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import pmd_arabic as overlay
from classic_retro.rom.pmd_arabic_script import PmdArabicString

BASE = overlay.ROM_BASE
GLYPH_DATA = 0x0830F67C
STRINGS = 0x080F0000
POINTERS = 0x080F2000
ENGLISH = {
    "welcome": b"#+Hello there!",
    "question": b"Is this a drill?#W\nWhat would you pick~2c then?",
    "yes": b"Yes.",
}
ARABIC = {
    "welcome": (PmdTextBox.FLOATING, "{CENTER_ALIGN}أهلا بك!"),
    "question": (PmdTextBox.DIALOGUE, "هناك اختبار قريب.{WAIT_PRESS}\nكيف تذاكر له؟"),
    "yes": (PmdTextBox.MENU, "نعم."),
}
# Two pointers lead to "Yes.", like the questions sharing it in the game.
REFERENCES = {
    "welcome": (POINTERS,),
    "question": (POINTERS + 4,),
    "yes": (POINTERS + 8, POINTERS + 16),
}


def _charmap_codes() -> list[int]:
    codes = list(range(0x20, 0x100)) + [0x8140 + n for n in range(60)]
    codes += [0x8486, 0x8487] + [0x8740 + n for n in range(473 - len(codes) - 2)]
    return sorted(codes)


def _synthetic_rom() -> tuple[bytes, dict[str, int]]:
    rom = bytearray(b"\x00" * overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    padding = overlay.PADDING_END - overlay.PADDING_START
    put(overlay.PADDING_START, b"\xff" * padding)
    for site in overlay.HOOK_SITES:
        put(site.address, site.original)
    put(overlay.CHARMAP_FILE_ADDRESS, b"SIRO" + struct.pack("<I", overlay.CHARMAP_TABLE_ADDRESS))
    codes = _charmap_codes()
    assert len(codes) == overlay.CHARMAP_COUNT
    put(
        overlay.CHARMAP_TABLE_ADDRESS,
        struct.pack("<iI", len(codes), overlay.CHARMAP_ENTRIES_ADDRESS),
    )
    for number, code in enumerate(codes):
        character = chr(code) if code < 0x100 else ""
        width = USA_LATIN_WIDTHS.get(character, 5)
        bitmap = GLYPH_DATA + number * GLYPH_BYTES
        entry = PmdGlyphEntry(code, width, 0, 2, bitmap)
        put(overlay.CHARMAP_ENTRIES_ADDRESS + number * ENTRY_BYTES, entry.pack())
        pixels = [
            [0xF if x == 1 and 1 <= y <= 8 else 0 for x in range(GLYPH_COLUMNS)]
            for y in range(GLYPH_ROWS)
        ]
        put(bitmap, glyph_bitmap(pixels))
    addresses = {}
    cursor = STRINGS
    for key, text in ENGLISH.items():
        addresses[key] = cursor
        put(cursor, text + b"\0")
        cursor += len(text) + 4 - len(text) % 4
        for reference in REFERENCES[key]:
            put(reference, struct.pack("<I", addresses[key]))
    return bytes(rom), addresses


def _translations(addresses: dict[str, int]) -> tuple[PmdArabicString, ...]:
    return tuple(
        PmdArabicString(
            key=key,
            box=ARABIC[key][0],
            source_address=addresses[key],
            references=REFERENCES[key],
            source_sha256=hashlib.sha256(ENGLISH[key]).hexdigest(),
            source_skeleton=command_skeleton(ENGLISH[key]),
            notation=ARABIC[key][1],
        )
        for key in ENGLISH
    )


def _fake_font(font_path, latin=None, **_kwargs) -> PmdRtlFont:
    glyph_map = build_pmd_arabic_glyph_map()
    ink = tuple(
        tuple(0xF if x < 4 and 2 <= y < 8 else 0 for x in range(GLYPH_COLUMNS))
        for y in range(GLYPH_ROWS)
    )
    space = glyph_map.code(" ")
    glyphs = {code: PmdRtlGlyph(5, ink) for code in glyph_map.all_codes()}
    for character in LATIN_COPIES:
        glyphs[glyph_map.sequences[character][0]] = latin[character]
    glyphs[space] = PmdRtlGlyph(SPACE_ADVANCE, tuple((0,) * 12 for _ in range(12)))
    sequences = {character: codes[:1] for character, codes in glyph_map.sequences.items()}
    return PmdRtlFont(glyphs=glyphs, sequences=sequences, space=space, font_size=9)


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


@pytest.fixture(scope="module")
def build(synthetic, tmp_path_factory):
    rom, addresses = synthetic
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_pmd_rtl_font", _fake_font)
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    try:
        result = overlay.build_pmd_arabic_rom(
            rom, font_file, strings=_translations(addresses), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, addresses, result


def test_hooks_are_written_and_every_site_calls_its_hook(build):
    rom, _, result = build
    output = result.rom

    assert len(output) == overlay.USA_SIZE
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        assert overlay.bl_target(site.address, output[start : start + 4]) == target
        if site.resume is not None:
            (branch,) = struct.unpack_from("<H", output, start + 4)
            assert branch >> 11 == 0b11100
            assert site.address + 8 + ((branch & 0x7FF) << 1) == site.resume
            # The bytes after the branch are left as they were.
            end = start + len(site.original)
            assert output[start + 6 : end] == rom[start + 6 : end]


def test_new_charmap_keeps_the_game_glyphs_and_adds_right_to_left_ones(build):
    rom, _, result = build
    original = PmdCharmap.parse(rom, overlay.CHARMAP_FILE_ADDRESS)
    charmap = PmdCharmap.parse(result.rom, overlay.CHARMAP_FILE_ADDRESS)

    assert charmap.table_address == overlay.CHARMAP_ADDRESS
    codes = [entry.code for entry in charmap.entries]
    assert codes == sorted(set(codes))
    kept = [entry for entry in charmap.entries if not entry.flags]
    assert tuple(kept) == original.entries
    added = [entry for entry in charmap.entries if entry.flags]
    assert all(entry.flags == RTL_FLAG and entry.code >> 8 == ARABIC_LEAD for entry in added)
    assert len(added) == len(result.font.glyphs)
    # The right-to-left full stop is the game's own, one row higher.
    dot = charmap.entry(build_pmd_arabic_glyph_map().code("."))
    pixels = charmap.pixels(result.rom, dot.code)
    assert dot.width == USA_LATIN_WIDTHS["."]
    assert [y for y in range(GLYPH_ROWS) if pixels[y][1]] == list(range(0, 8))
    # The game's original table is left in place.
    table = original.table_address - BASE
    assert result.rom[table : table + 8] == rom[table : table + 8]


def test_every_pointer_leads_to_its_arabic_string(build):
    rom, addresses, result = build
    output = result.rom

    seen = {}
    for key, references in REFERENCES.items():
        for reference in references:
            (pointer,) = struct.unpack_from("<I", output, reference - BASE)
            assert overlay.ARABIC_TEXT_ADDRESS <= pointer < overlay.REGION_END
            seen.setdefault(key, set()).add(pointer)
        assert len(seen[key]) == 1
        text = read_string(output, seen[key].pop())
        assert command_skeleton(text) == command_skeleton(ENGLISH[key])
        assert b"\x84" in text and b" " not in text
        # The English original stays where it was.
        assert read_string(output, addresses[key]) == ENGLISH[key]
    assert result.report["strings"] == 3 and result.report["pointers"] == 4
    assert result.report["string_boxes"]["yes"] == "menu"


def test_only_the_sites_pointers_and_padding_change(build):
    rom, _, result = build
    output = result.rom

    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    region = range(overlay.HOOK_CODE_ADDRESS - BASE & ~0xFFF, overlay.REGION_END - BASE)
    assert {page for page in changed if page not in region} == {
        0x7000, 0x9000, 0x13000, 0xF2000, 0x30F000
    }  # fmt: skip
    assert output[overlay.REGION_END - BASE : overlay.PADDING_END - BASE].count(0xFF) == (
        overlay.PADDING_END - overlay.REGION_END
    )


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, _, result = build

    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize("damage", ["site", "padding", "charmap", "width", "code", "flags"])
def test_changed_anchors_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_pmd_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    if damage == "site":
        rom[overlay.HOOK_SITES[3].address - BASE + 6] ^= 1
    elif damage == "padding":
        rom[overlay.ARABIC_TEXT_ADDRESS - BASE + 5] = 0
    elif damage == "charmap":
        struct.pack_into("<i", rom, overlay.CHARMAP_TABLE_ADDRESS - BASE, 472)
    else:
        entries = overlay.CHARMAP_ENTRIES_ADDRESS - BASE
        number = _charmap_codes().index(ord("!") if damage != "code" else 0x8486)
        entry = entries + number * ENTRY_BYTES
        if damage == "width":
            struct.pack_into("<h", rom, entry + 6, 9)
        elif damage == "code":
            struct.pack_into("<H", rom, entry + 4, build_pmd_arabic_glyph_map().code(" "))
            # Keep the entries sorted so only the collision is reported.
            _resort(rom, entries)
        else:
            rom[entry + 8] = 1
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_pmd_arabic_rom(
            bytes(rom), font_file, strings=_translations(addresses), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


def _resort(rom: bytearray, entries: int) -> None:
    raw = [
        rom[entries + number * ENTRY_BYTES : entries + (number + 1) * ENTRY_BYTES]
        for number in range(overlay.CHARMAP_COUNT)
    ]
    raw.sort(key=lambda entry: struct.unpack_from("<H", entry, 4)[0])
    rom[entries : entries + len(raw) * ENTRY_BYTES] = b"".join(raw)


@pytest.mark.parametrize("damage", ["pointer", "text", "skeleton"])
def test_changed_originals_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_pmd_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    strings = list(_translations(addresses))
    if damage == "pointer":
        struct.pack_into("<I", rom, POINTERS + 16 - BASE, addresses["question"])
    elif damage == "text":
        rom[addresses["yes"] - BASE] = ord("N")
    else:
        strings[1] = PmdArabicString(
            **{
                **{field: getattr(strings[1], field) for field in strings[1].__slots__},
                "source_skeleton": ("{EXTRA_MSG}",),
            }
        )
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_pmd_arabic_rom(
            bytes(rom), font_file, strings=tuple(strings), verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_translations_must_keep_the_original_commands(synthetic, tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_pmd_rtl_font", _fake_font)
    rom, addresses = synthetic
    strings = list(_translations(addresses))
    fields = {field: getattr(strings[1], field) for field in strings[1].__slots__}
    strings[1] = PmdArabicString(**{**fields, "notation": "هناك اختبار قريب.\nكيف؟"})
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_pmd_arabic_rom(rom, font_file, strings=tuple(strings), verify_identity=False)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_bl_and_branch_encoding_round_trip():
    code = overlay.bl_instruction(0x08007454, 0x08272C00)
    assert overlay.bl_target(0x08007454, code) == 0x08272C00
    assert overlay.branch_instruction(0x0800931E, 0x0800932A) == b"\x04\xe0"
    with pytest.raises(ClassicRetroError):
        overlay.bl_instruction(0x08000000, 0x08800000)
    with pytest.raises(ClassicRetroError):
        overlay.branch_instruction(0x08000000, 0x08001000)
    with pytest.raises(ClassicRetroError):
        overlay.bl_target(0x08000000, b"\x00\x00\x00\x00")


def test_cli_checks_translations_without_rom(capsys):
    assert main(["pmd", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["strings"] == 158 and report["lines_measured"] is False


def test_cli_encodes_a_menu_item(capsys):
    assert main(["pmd", "encode-arabic", "نعم.", "--box", "menu"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["bytes"].startswith("84") and report["bytes"].endswith("00")
    assert main(["pmd", "encode-arabic", "{CENTER_ALIGN}نعم", "--box", "menu"]) == 2


def test_extract_reads_every_original_in_the_notation(synthetic):
    rom, addresses = synthetic
    originals = overlay.extract_originals(
        rom, strings=_translations(addresses), verify_identity=False
    )
    assert originals == {
        "welcome": "{CENTER_ALIGN}Hello there!",
        "question": "Is this a drill?{WAIT_PRESS}\nWhat would you pick, then?",
        "yes": "Yes.",
    }
