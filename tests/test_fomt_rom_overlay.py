from __future__ import annotations

import dataclasses
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
from classic_retro.cpu import thumb
from classic_retro.engines.fomt import (
    FomtScript,
    PlaceholderStyle,
    command_skeleton,
    parse_notation,
    read_string,
    split_text,
)
from classic_retro.engines.fomt_arabic import (
    CELL_LEAD,
    NAME_CODE,
    TAG_CELLS,
    TAG_LEAD,
    code_cell,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import fomt_arabic as overlay
from classic_retro.rom.fomt_arabic_script import (
    OPENING_SCRIPT,
    OPENING_SCRIPT_ADDRESS,
    SCRIPT_TABLE,
    FomtArabicName,
    FomtArabicString,
    fomt_arabic_names,
    fomt_arabic_strings,
)

BASE = overlay.ROM_BASE
STORY_TEXT = 0x080FB000
STORY_CODE = 0x0805F000
# Invented English texts: ten strings of the script, two story lines, two names.
SCRIPT_TEXTS = [
    b"Good morning! The barn\r\nis open today.\x05",
    b"You must be \xff\x21!\x05\x0cWelcome to town.\x05",
    *(f"Line {number}.\x05".encode() for number in range(2, 10)),
]
STORY_TEXTS = {
    "story_hello": b"\x0cHello there, \xff?\x05",
    "story_bye": b"\x0cSee you soon!\x05\x0cTake care.\x05",
}
NAME_TEXTS = {"aunt": b"Aunt", "uncle": b"Uncle"}
ARABIC_SCRIPT = {
    0: "\u0635\u0628\u0627\u062d \u0627\u0644\u062e\u064a\u0631!\n\u0627\u0644\u062d\u0638\u064a\u0631\u0629 \u0645\u0641\u062a\u0648\u062d\u0629.{wait}",
    1: "\u0623\u0646\u062a {name}!{wait}{clear}\u0645\u0631\u062d\u0628\u0627 \u0628\u0643.{wait}",
}
ARABIC_STORY = {
    "story_hello": "{clear}\u0645\u0631\u062d\u0628\u0627 \u064a\u0627 {name}\u061f{wait}",
    "story_bye": "{clear}\u0625\u0644\u0649 \u0627\u0644\u0644\u0642\u0627\u0621!{wait}{clear}\u0627\u0639\u062a\u0646 \u0628\u0646\u0641\u0633\u0643.{wait}",
}
ARABIC_NAMES = {"aunt": "\u0627\u0644\u0639\u0645\u0629", "uncle": "\u0627\u0644\u0639\u0645"}


def _box(pen: TTGlyphPen, left: int, bottom: int, right: int, top: int) -> None:
    pen.moveTo((left, bottom))
    pen.lineTo((left, top))
    pen.lineTo((right, top))
    pen.lineTo((right, bottom))
    pen.closePath()


@pytest.fixture
def arabic_font(tmp_path):
    """Original test outlines: one box glyph for every letter the invented texts use."""
    letters = sorted(
        {
            character
            for text in (*ARABIC_SCRIPT.values(), *ARABIC_STORY.values(), *ARABIC_NAMES.values())
            for character in text
            if "\u0621" <= character <= "\u064a"
        }
        | {"\u0627", "\u0649"}
    )
    letters.append("\u061f")
    names = [".notdef", "space", *(f"u{ord(letter):04X}" for letter in letters)]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    cmap = {0x20: "space"}
    cmap.update({ord(letter): f"u{ord(letter):04X}" for letter in letters})
    builder.setupCharacterMap(cmap)
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        if name.startswith("u"):
            _box(pen, 60, 0, 440, 500)
            if name in ("u0623", "u0625"):
                _box(
                    pen, 60, 800 if name == "u0623" else -300, 440, 900 if name == "u0623" else -200
                )
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = dict.fromkeys(names, (500, 0))
    metrics["space"] = (300, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=900, descent=-300)
    builder.setupNameTable({"familyName": "Classic Retro FoMT ROM Test", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=900, sTypoDescender=-300, usWinAscent=900, usWinDescent=300)
    builder.setupPost()
    addOpenTypeFeaturesFromString(builder.font, "languagesystem DFLT dflt;")
    path = tmp_path / "fomt-rom-test.ttf"
    builder.save(path)
    return path


def _script_bytes() -> bytes:
    code = struct.pack("<I", 8) + bytes(range(8))
    offsets, text = [], b""
    for string in SCRIPT_TEXTS:
        offsets.append(len(text))
        text += string + b"\0"
    chunk = struct.pack(f"<I{len(SCRIPT_TEXTS)}I", len(SCRIPT_TEXTS), *offsets) + text
    body = b"SCR CODE" + struct.pack("<I", len(code)) + code
    body += b"STR " + struct.pack("<I", len(chunk)) + chunk
    return b"RIFF" + struct.pack("<I", 8 + len(body)) + body


def _layout() -> dict[str, tuple[int, tuple[int, ...]]]:
    """Where each invented story text and name is, and the literals that point to it."""
    layout: dict[str, tuple[int, tuple[int, ...]]] = {}
    address, literal = STORY_TEXT, STORY_CODE
    for key, text in [*STORY_TEXTS.items(), *NAME_TEXTS.items()]:
        count = 2 if key in NAME_TEXTS else 1
        layout[key] = (address, tuple(literal + 4 * number for number in range(count)))
        address += len(text) + 1 + (-(len(text) + 1) % 4)
        literal += 16
    return layout


def _synthetic_rom() -> bytes:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    put(overlay.PADDING_START, b"\xff" * (overlay.PADDING_END - overlay.PADDING_START))
    put(overlay.GLYPH_SITE, overlay.GLYPH_SITE_ORIGINAL)
    put(overlay.DRAW_SITE, overlay.DRAW_SITE_ORIGINAL)
    put(overlay.SCRIPT_EXPANDER_SLOT, struct.pack("<I", overlay.SCRIPT_EXPANDER))
    put(overlay.STORY_EXPANDER_SLOT, struct.pack("<I", overlay.STORY_EXPANDER))
    put(SCRIPT_TABLE + 4 * OPENING_SCRIPT, struct.pack("<I", OPENING_SCRIPT_ADDRESS))
    put(OPENING_SCRIPT_ADDRESS, _script_bytes() + b"\0\0RIFF")
    texts = {**STORY_TEXTS, **NAME_TEXTS}
    for key, (address, literals) in _layout().items():
        put(address, texts[key] + b"\0")
        for literal in literals:
            put(literal, struct.pack("<I", address))
    return bytes(rom)


def _strings() -> tuple[FomtArabicString, ...]:
    strings = []
    for index, notation in ARABIC_SCRIPT.items():
        original = SCRIPT_TEXTS[index]
        strings.append(
            FomtArabicString(
                key=f"script_{index}",
                style=PlaceholderStyle.SCRIPT,
                index=index,
                address=None,
                literals=(),
                speaker="someone",
                source_sha256=hashlib.sha256(original).hexdigest(),
                source_skeleton=command_skeleton(split_text(original, PlaceholderStyle.SCRIPT)),
                notation=notation,
            )
        )
    for key, notation in ARABIC_STORY.items():
        address, literals = _layout()[key]
        original = STORY_TEXTS[key]
        strings.append(
            FomtArabicString(
                key=key,
                style=PlaceholderStyle.STORY,
                index=None,
                address=address,
                literals=literals,
                speaker="someone",
                source_sha256=hashlib.sha256(original).hexdigest(),
                source_skeleton=command_skeleton(split_text(original, PlaceholderStyle.STORY)),
                notation=notation,
            )
        )
    return tuple(strings)


def _names() -> tuple[FomtArabicName, ...]:
    return tuple(
        FomtArabicName(
            key,
            _layout()[key][0],
            _layout()[key][1],
            hashlib.sha256(NAME_TEXTS[key]).hexdigest(),
            arabic,
        )
        for key, arabic in ARABIC_NAMES.items()
    )


@pytest.fixture
def synthetic(monkeypatch):
    monkeypatch.setattr(
        overlay, "OPENING_SCRIPT_SHA256", hashlib.sha256(_script_bytes()).hexdigest()
    )
    return _synthetic_rom()


@pytest.fixture
def build(synthetic, arabic_font):
    return synthetic, overlay.build_fomt_arabic_rom(
        synthetic, arabic_font, strings=_strings(), names=_names(), verify_identity=False
    )


def _word(rom: bytes, address: int) -> int:
    return struct.unpack_from("<I", rom, address - BASE)[0]


def test_hooks_sites_and_expander_slots_are_written(build):
    rom, result = build
    output = result.rom
    start = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[start : start + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    site = overlay.GLYPH_SITE - BASE
    assert output[site : site + 8] == bytes.fromhex("004a1047") + struct.pack(
        "<I", overlay.HOOK_CODE_ADDRESS | 1
    )
    site = overlay.DRAW_SITE - BASE
    assert output[site : site + 16] == overlay.draw_site_patch()
    assert output[site : site + 8] == bytes.fromhex("00f002f804e0c046")
    assert _word(output, overlay.SCRIPT_EXPANDER_SLOT) == (
        overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS["hook_expand_script"] | 1
    )
    assert _word(output, overlay.STORY_EXPANDER_SLOT) == (
        overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS["hook_expand_story"] | 1
    )
    assert len(output) == len(rom) == overlay.USA_SIZE


def test_bank_header_describes_the_cells(build):
    _, result = build
    cells, count, tags, tag_count = struct.unpack_from(
        "<4I", result.rom, overlay.BANK_ADDRESS - BASE
    )
    assert cells == overlay.CELLS_ADDRESS and count == len(result.bank.cells) > 0
    assert tags == cells + 64 * count and tag_count == len(result.tag_bank.cells) > 0
    assert result.rom[cells - BASE : cells - BASE + 64] == result.bank.cells[0]
    assert result.rom[tags - BASE : tags - BASE + 128] == result.tag_bank.cells[0]


def test_the_script_is_rebuilt_with_its_code(build):
    rom, result = build
    address = _word(result.rom, SCRIPT_TABLE + 4 * OPENING_SCRIPT)
    assert address != OPENING_SCRIPT_ADDRESS and address % 4 == 0
    original = FomtScript.read(rom, OPENING_SCRIPT_ADDRESS - BASE)
    rebuilt = FomtScript.read(result.rom, address - BASE)
    assert rebuilt.chunk(b"CODE") == original.chunk(b"CODE")
    strings = rebuilt.strings
    assert strings[0] == result.texts["script_0"].data
    assert NAME_CODE in strings[1]
    assert strings[2:] == original.strings[2:]
    end = address - BASE + len(rebuilt.to_bytes())
    assert result.rom[end : end + 8] == bytes(8)


def test_story_literals_lead_to_the_arabic_texts_and_tags(build):
    _, result = build
    for string in _strings()[2:]:
        for literal in string.literals:
            data = read_string(result.rom, _word(result.rom, literal) - BASE)
            assert data == result.texts[string.key].data
            assert data[0] == 0x0C and data[-1] == 0x05
    for name in _names():
        tags = {
            read_string(result.rom, _word(result.rom, literal) - BASE) for literal in name.literals
        }
        assert tags == {result.tags[name.key]}
        (tag,) = tags
        assert len(tag) == 2 * TAG_CELLS and tag[0::2] == bytes([TAG_LEAD]) * TAG_CELLS


def test_every_code_names_a_cell(build):
    _, result = build
    for text in result.texts.values():
        data = text.data
        for index in range(len(data) - 1):
            if CELL_LEAD <= data[index] < 0xFB and (index == 0 or data[index - 1] < CELL_LEAD):
                assert code_cell(data[index : index + 2]) < len(result.bank.cells)


def test_only_the_sites_literals_and_padding_change(build):
    rom, result = build
    output = result.rom
    changed = [index for index in range(len(rom)) if rom[index] != output[index]]
    padding = range(overlay.PADDING_START - BASE, overlay.PADDING_END - BASE)
    literals = {
        literal - BASE + offset
        for item in (*_strings(), *_names())
        for literal in item.literals
        for offset in range(4)
    }
    fixed = set(range(overlay.GLYPH_SITE - BASE, overlay.GLYPH_SITE - BASE + 8))
    fixed |= set(range(overlay.DRAW_SITE - BASE, overlay.DRAW_SITE - BASE + 16))
    for slot in (
        overlay.SCRIPT_EXPANDER_SLOT,
        overlay.STORY_EXPANDER_SLOT,
        SCRIPT_TABLE + 4 * OPENING_SCRIPT,
    ):
        fixed |= set(range(slot - BASE, slot - BASE + 4))
    assert all(index in padding or index in literals or index in fixed for index in changed)


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, result = build
    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()
    assert result.report["strings"] == 4 and result.report["speaker_names"] == 2


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize("damage", ["glyph", "draw", "slot", "padding", "table"])
def test_changed_anchors_are_refused(synthetic, arabic_font, damage):
    rom = bytearray(synthetic)
    if damage == "glyph":
        rom[overlay.GLYPH_SITE - BASE + 3] ^= 1
    elif damage == "draw":
        rom[overlay.DRAW_SITE - BASE + 9] ^= 1
    elif damage == "slot":
        struct.pack_into("<I", rom, overlay.STORY_EXPANDER_SLOT - BASE, 0x08123457)
    elif damage == "padding":
        rom[overlay.PADDING_END - BASE - 5] = 0
    else:
        struct.pack_into("<I", rom, SCRIPT_TABLE + 4 * OPENING_SCRIPT - BASE, 0x08300000)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_fomt_arabic_rom(
            bytes(rom), arabic_font, strings=_strings(), names=_names(), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


@pytest.mark.parametrize("damage", ["script", "story", "name", "extra_literal", "skeleton"])
def test_changed_originals_are_refused(synthetic, arabic_font, monkeypatch, damage):
    rom = bytearray(synthetic)
    strings = list(_strings())
    if damage == "script":
        monkeypatch.setattr(overlay, "OPENING_SCRIPT_SHA256", "0" * 64)
    elif damage == "story":
        rom[_layout()["story_bye"][0] - BASE + 3] ^= 0x20
    elif damage == "name":
        rom[_layout()["uncle"][0] - BASE] ^= 0x20
    elif damage == "extra_literal":
        struct.pack_into("<I", rom, STORY_CODE + 0x100 - BASE, _layout()["aunt"][0])
    else:
        strings[2] = dataclasses.replace(strings[2], source_skeleton=("{wait}",))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_fomt_arabic_rom(
            bytes(rom), arabic_font, strings=tuple(strings), names=_names(), verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_translations_must_keep_the_original_commands(synthetic, arabic_font):
    strings = list(_strings())
    strings[1] = dataclasses.replace(strings[1], notation="\u0623\u0646\u062a!{wait}")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_fomt_arabic_rom(
            synthetic, arabic_font, strings=tuple(strings), names=_names(), verify_identity=False
        )
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_bl_and_branch_encoding():
    assert thumb.bl_instruction(0x0804EFD0, 0x0804EFD8) == bytes.fromhex("00f002f8")
    assert thumb.branch_instruction(0x0804EFD4, 0x0804EFE0) == bytes.fromhex("04e0")
    with pytest.raises(ClassicRetroError):
        thumb.bl_instruction(0x0804EFD0, overlay.HOOK_CODE_ADDRESS)
    with pytest.raises(ClassicRetroError):
        thumb.branch_instruction(0x0804EFD4, 0x0804EFD4 + 0x1000)


def test_pinned_script_covers_the_opening():
    strings = fomt_arabic_strings()
    assert len(strings) == 33 and len(fomt_arabic_names()) == 5
    for string in strings:
        assert len(string.source_sha256) == 64
        assert string.pieces
        assert string.source_skeleton == command_skeleton(string.pieces)


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_hook_source_assembles_to_the_stored_bytes():
    result = overlay.check_hook_code()
    assert result["match"] is True and result["hook_bytes"] == len(overlay.HOOK_CODE)


def test_cli_checks_translations_without_rom(capsys):
    assert main(["fomt", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"laid_out": False, "speaker_names": 5, "strings": 33}


def test_cli_encodes_a_string(arabic_font, capsys):
    text = "{clear}\u0645\u0631\u062d\u0628\u0627 \u064a\u0627 {name}\u061f{wait}"
    assert main(["fomt", "encode-arabic", text, "--story", "--font", str(arabic_font)]) == 0
    payload = json.loads(capsys.readouterr().out)
    data = bytes.fromhex(payload["bytes"])
    assert data[0] == 0x0C and data[-1] == 0x05 and NAME_CODE in data
    assert payload["count"] == len(data) and payload["line_cells"][0] == 0


def test_cli_refuses_another_image(tmp_path, arabic_font, capsys):
    rom = tmp_path / "other.gba"
    rom.write_bytes(bytes(1024))
    code = main(
        ["fomt", "build-arabic", str(rom), "--font", str(arabic_font), "--out-dir", str(tmp_path)]
    )
    assert code == 2
    assert "UNKNOWN_GAME_REVISION" in capsys.readouterr().err
    assert parse_notation("{wait}", PlaceholderStyle.SCRIPT)
