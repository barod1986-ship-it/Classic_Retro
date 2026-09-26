from __future__ import annotations

import hashlib
import json
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    FONT_FIRST,
    FONT_GLYPH_BYTES,
    FONT_GLYPHS,
    KEY_END,
    NEWLINE,
    GoldenSunTextBank,
    build_text_bank,
    read_string_store,
)
from classic_retro.engines.golden_sun_arabic import (
    ARABIC_CODE_BASE,
    CELL_HEIGHT,
    RTL_MARKER,
    SPACE_ADVANCE,
    USA_LATIN_ADVANCES,
    GoldenSunRtlFont,
    RtlGlyph,
    build_golden_sun_arabic_glyph_map,
    golden_sun_command,
    golden_sun_newline,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import golden_sun_arabic as overlay
from classic_retro.rom.golden_sun_arabic_script import GoldenSunArabicMessage
from classic_retro.text.tokens import TextToken, TokenStream

BASE = overlay.ROM_BASE
BANK_ADDRESS = 0x08100000


def _english(index: int) -> tuple[int, ...]:
    codes = tuple(f"Line {index % 97}".encode("ascii"))
    if index == 1:
        return (CHARACTER_NAME, 0x01, *b", wake up!", KEY_END)
    if index == 2:
        return (*b"The Boulder", NEWLINE, *b"is falling!", KEY_END)
    return codes


def _synthetic_rom(strings: list[tuple[int, ...]]) -> bytes:
    rom = bytearray(overlay.USA_SIZE)
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        rom[start : start + len(site.original)] = site.original
    for patch in overlay.CODE_PATCHES:
        start = patch.address - BASE
        rom[start : start + len(patch.original)] = patch.original
    font = overlay.LATIN_FONT_ADDRESS - BASE
    for code in range(FONT_FIRST + 1, FONT_FIRST + FONT_GLYPHS):
        advance = USA_LATIN_ADVANCES.get(chr(code), 6)
        glyph = font + (code - FONT_FIRST) * FONT_GLYPH_BYTES
        struct.pack_into("<H", rom, glyph, advance)
        struct.pack_into("<H", rom, glyph + 2 + 2 * 5, 0b1110 << 12)
    built = build_text_bank(strings, BANK_ADDRESS)
    start = BANK_ADDRESS - BASE
    rom[start : start + len(built.data)] = built.data
    tree_table = built.data[: 8 * built.tree_blocks]
    string_table = built.data[built.string_table - BANK_ADDRESS :]
    table = overlay.TREE_TABLE_ADDRESS - BASE
    rom[table : table + len(tree_table)] = tree_table
    table = overlay.STRING_TABLE_ADDRESS - BASE
    rom[table : table + len(string_table)] = string_table
    for reference in overlay.TREE_TABLE_REFERENCES:
        struct.pack_into("<I", rom, reference - BASE, overlay.TREE_TABLE_ADDRESS)
    for reference in overlay.STRING_TABLE_REFERENCES:
        struct.pack_into("<I", rom, reference - BASE, overlay.STRING_TABLE_ADDRESS)
    return bytes(rom)


def _fake_font(font_path, latin=None, **_kwargs) -> GoldenSunRtlFont:
    glyph_map = build_golden_sun_arabic_glyph_map()
    glyphs = {
        ARABIC_CODE_BASE + slot: RtlGlyph(5, (0b0101,) * (CELL_HEIGHT - 1) + (0b1010,))
        for slot in range(len(glyph_map.characters))
    }
    for character, advance in USA_LATIN_ADVANCES.items():
        glyphs[ord(character)] = RtlGlyph(advance, (0b01,) * CELL_HEIGHT)
    glyphs[0x20] = RtlGlyph(SPACE_ADVANCE, (0,) * CELL_HEIGHT)
    return GoldenSunRtlFont(
        glyphs=glyphs,
        font_size=10,
        arabic_widths=dict.fromkeys(glyph_map.characters, 5),
    )


def _translations(strings: list[tuple[int, ...]]) -> tuple[GoldenSunArabicMessage, ...]:
    def sha(index: int) -> str:
        return hashlib.sha256(bytes(strings[index])).hexdigest()

    wake = TokenStream(
        (
            golden_sun_command("n", CHARACTER_NAME, 0x01),
            TextToken("، استيقظ!"),
            golden_sun_command("e", KEY_END),
        )
    )
    boulder = TokenStream(
        (
            TextToken("صخرة جبل أليف"),
            golden_sun_newline("l"),
            TextToken("على وشك السقوط!"),
            golden_sun_command("e", KEY_END),
        )
    )
    return (
        GoldenSunArabicMessage(1, "Dora", sha(1), (CHARACTER_NAME, 0x01, KEY_END), wake),
        GoldenSunArabicMessage(2, "Dora", sha(2), (KEY_END,), boulder),
    )


@pytest.fixture(scope="module")
def english():
    return [_english(index) for index in range(overlay.STRING_COUNT)]


@pytest.fixture(scope="module")
def build(english, tmp_path_factory):
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_golden_sun_rtl_font", _fake_font)
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    rom = _synthetic_rom(english)
    try:
        result = overlay.build_golden_sun_arabic_rom(
            rom, font_file, messages=_translations(english), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, result


def test_overlay_expands_the_image_and_places_hooks_glyphs_and_bank(build):
    rom, result = build
    output = result.rom

    assert len(output) == overlay.EXPANDED_SIZE
    assert output[-1] == overlay.EXPANSION_FILL
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    assert not any(output[code + len(overlay.HOOK_CODE) : overlay.HOOK_REGION_END - BASE])
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        assert output[start : start + len(site.original)] == site.replacement(target)
    for patch in overlay.CODE_PATCHES:
        start = patch.address - BASE
        assert output[start : start + len(patch.replacement)] == patch.replacement
    font = overlay.RTL_FONT_ADDRESS - BASE
    assert output[font + 0x20] == SPACE_ADVANCE
    assert output[font + ARABIC_CODE_BASE] == 5
    store = overlay.ARABIC_STORE_ADDRESS - BASE
    assert struct.unpack_from("<HHI", output, store + 16)[0] == 1
    # The original bank and its tables stay untouched.
    for address in (overlay.TREE_TABLE_ADDRESS, overlay.STRING_TABLE_ADDRESS, BANK_ADDRESS):
        assert output[address - BASE : address - BASE + 64] == rom[address - BASE :][:64]


def test_translated_strings_live_in_the_store_and_the_bank_is_untouched(build, english):
    rom, result = build
    output = result.rom
    for references, table in (
        (overlay.TREE_TABLE_REFERENCES, overlay.TREE_TABLE_ADDRESS),
        (overlay.STRING_TABLE_REFERENCES, overlay.STRING_TABLE_ADDRESS),
    ):
        for reference in references:
            assert struct.unpack_from("<I", output, reference - BASE)[0] == table

    bank = GoldenSunTextBank.parse(
        output,
        overlay.TREE_TABLE_ADDRESS - BASE,
        overlay.STRING_TABLE_ADDRESS - BASE,
        overlay.STRING_COUNT,
    )
    assert bank.strings == tuple(english)
    stored = read_string_store(output, overlay.ARABIC_STORE_ADDRESS)
    assert sorted(stored) == [1, 2]
    for codes in stored.values():
        assert codes[0] == RTL_MARKER
        assert codes[-1] == KEY_END
        assert any(code >= ARABIC_CODE_BASE for code in codes)
    assert stored[1][1:3] == (CHARACTER_NAME, 0x01)
    assert result.report["strings"] == [1, 2]
    assert result.report["tree_blocks"] == 2
    assert result.report["arabic_store_bytes"] < 0x1000
    assert [line["names"] for line in result.report["string_lines"]["1"]] == [1]
    assert len(result.report["string_lines"]["2"]) == 2
    # Outside the hook sites, the hook region and the expansion, nothing changes.
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    assert changed == {0x16000, 0x18000, 0x74000}


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, result = build

    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(overlay.USA_SIZE))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize(
    "damage",
    ["hook", "code", "reference", "padding", "latin"],
)
def test_changed_anchors_are_refused(english, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_golden_sun_rtl_font", _fake_font)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    rom = bytearray(_synthetic_rom(english))
    if damage == "hook":
        rom[overlay.HOOK_SITES[2].address - BASE] ^= 0xFF
    elif damage == "code":
        rom[overlay.CODE_PATCHES[0].address - BASE] ^= 0xFF
    elif damage == "reference":
        rom[overlay.STRING_TABLE_REFERENCES[0] - BASE] ^= 0x04
    elif damage == "padding":
        rom[overlay.HOOK_REGION_END - BASE - 1] = 1
    else:
        rom[overlay.LATIN_FONT_ADDRESS - BASE + (ord("!") - FONT_FIRST) * FONT_GLYPH_BYTES] += 1

    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_golden_sun_arabic_rom(
            bytes(rom), font_file, messages=_translations(english), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


def test_changed_script_is_refused(english, tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_golden_sun_rtl_font", _fake_font)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    translations = _translations(english)
    edited = list(english)
    edited[2] = (*b"The Rock", NEWLINE, *b"is falling!", KEY_END)

    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_golden_sun_arabic_rom(
            _synthetic_rom(edited), font_file, messages=translations, verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_cli_checks_the_script_and_encodes_a_line(capsys):
    assert main(["targets", "check-translations", "golden-sun"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["lines_measured"] is False
    assert report["strings"][0] == 3666 and report["strings"][-1] == 3686

    assert main(["golden-sun", "encode-arabic", "مرحبا!"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["codes"].startswith(f"{RTL_MARKER:03X} ")
    assert encoded["codes"].endswith(f"{KEY_END:03X}")


def test_cli_refuses_an_unknown_rom(tmp_path, capsys):
    rom = tmp_path / "game.gba"
    rom.write_bytes(bytes(64))
    font = tmp_path / "font.ttf"
    font.write_bytes(b"x")

    code = main(
        [
            "targets",
            "build",
            "golden-sun",
            str(rom),
            "--font",
            str(font),
            "--out-dir",
            str(tmp_path / "o"),
        ]
    )
    assert code == 2
    assert "UNKNOWN_GAME_REVISION" in capsys.readouterr().err


def test_extract_reads_every_string_in_the_notation(english):
    originals = overlay.extract_originals(
        _synthetic_rom(english), messages=_translations(english), verify_identity=False
    )
    assert originals == {
        "message.1": "{CHARACTER_NAME 01}, wake up!{KEY_END}",
        "message.2": "The Boulder\nis falling!{KEY_END}",
    }
