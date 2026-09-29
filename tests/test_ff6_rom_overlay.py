from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import struct
from functools import cache

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines import ff6 as engine
from classic_retro.engines import ff6_arabic as arabic
from classic_retro.engines.ff6 import (
    CHARACTER_CODES,
    COMMAND_CODES,
    DLG_BANK_INCREMENT,
    DLG_COUNT,
    DLG_POINTERS,
    DLG_TEXT,
    DTE_CODES,
    DTE_FIRST,
    DTE_TABLE,
    END,
    NAME_CODES,
    hirom_offset,
    message_at,
)
from classic_retro.engines.ff6_arabic import (
    BASELINE,
    GLYPH_BYTES,
    GLYPH_ROWS,
    NAME_STRIDE,
    WIDEST,
    Ff6Font,
    Ff6Glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import ff6_arabic as overlay
from classic_retro.rom.ff6_arabic_script import NAME_KEYS, Ff6Message

# Invented English for four messages, with the commands the Arabic keeps; the
# last is past the bank increment, in bank $CE.
BANK_INCREMENT = 1819
NUMBERS = {"narshe.town": 0, "narshe.esper": 1, "narshe.wake": 2, "narshe.late": 2000}
OFFSETS = {0: 0x0000, 1: 0x0100, 2: 0x0200, 2000: 0x0300}
ENGLISH = {
    "narshe.town": "{Terra}: There is the town.{line}Go!",
    "narshe.esper": "Frozen Esper!{Key}{line}Now.",
    "narshe.wake": "Where am I?{Pause 04}",
    "narshe.late": "Hurry!",
}
ARABIC = {
    "narshe.town": "{Terra}: هناك المدينة.{line}هيا!",
    "narshe.esper": "الإسبر المتجمد!{Key}{line}الآن.",
    "narshe.wake": "أين أنا؟{Pause 04}\nهيا",
    "narshe.late": "أسرع!",
}
NAMES = dict(
    zip(
        NAME_KEYS,
        "تيرا لوك سيان شادو إدغار سابين سيليس ستراغو ريلم سيتزر موغ غاو غوغو أومارو".split(),
        strict=True,
    )
)
TERRA = NAME_CODES["Terra"]


def _encode(text: str) -> bytes:
    data = bytearray()
    at = 0
    while at < len(text):
        if text[at] == "{":
            close = text.index("}", at)
            name, _, argument = text[at + 1 : close].partition(" ")
            data.append(COMMAND_CODES[name])
            if argument:
                data.append(int(argument, 16))
            at = close + 1
        else:
            data.append(CHARACTER_CODES[text[at]])
            at += 1
    return bytes(data) + bytes((END,))


def _put(rom: bytearray, address: int, data: bytes) -> None:
    at = hirom_offset(address)
    rom[at : at + len(data)] = data


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """3 MiB of zeros but the header, the engine's bytes the overlay checks, a table
    of pairs, the pointers and the four messages at their offsets."""
    rom = bytearray(overlay.ROM_SIZE)
    rom[overlay.MAP_MODE_BYTE] = overlay.MAP_MODE
    rom[overlay.ROM_SIZE_BYTE] = overlay.ROM_SIZE_CODE
    for site in overlay.SITES:
        _put(rom, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(rom, address, data)
    for code in DTE_CODES:
        pair = bytes((0x20 + (code - DTE_FIRST) % 26, 0x3A + (code - DTE_FIRST) % 26))
        _put(rom, DTE_TABLE + 2 * (code - DTE_FIRST), pair)
    _put(rom, DLG_BANK_INCREMENT, struct.pack("<H", BANK_INCREMENT))
    pointers = [OFFSETS.get(number, 0) for number in range(DLG_COUNT)]
    _put(rom, DLG_POINTERS, struct.pack(f"<{DLG_COUNT}H", *pointers))
    for key, number in NUMBERS.items():
        bank = DLG_TEXT + (0x10000 if number >= BANK_INCREMENT else 0)
        _put(rom, bank + OFFSETS[number], _encode(ENGLISH[key]))
    for address, data in change:
        _put(rom, address, data)
    overlay.set_checksum(rom)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _messages(rom: bytes | None = None) -> tuple[Ff6Message, ...]:
    rom = rom or _rom()
    return tuple(
        Ff6Message(key, number, _digest(message_at(rom, number).data), ARABIC[key])
        for key, number in NUMBERS.items()
    )


def _fake_font(font_path=None, glyph_map=None, used=(), **_kwargs) -> Ff6Font:
    """Every character six pixels wide (the space four) with a bar on the baseline
    and a pixel of its own."""
    glyphs = {}
    for character in used:
        code = glyph_map.code(character)
        width = 4 if character == " " else 6
        rows = [[0] * WIDEST for _ in range(GLYPH_ROWS)]
        if character != " ":
            for x in range(width):
                rows[BASELINE][x] = 1
            rows[code % 9 + 1][code % 5] = 1
        glyphs[code] = Ff6Glyph(width, tuple(tuple(row) for row in rows))
    return Ff6Font(glyphs, 11)


def _build(rom: bytes, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_ff6_font", _fake_font)
        return overlay.build_ff6_arabic_rom(
            rom,
            font_path,
            translated=options.pop("translated", _messages(rom)),
            names=options.pop("names", NAMES),
            verify_identity=options.pop("verify_identity", False),
        )


@pytest.fixture(scope="module")
def font_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("font") / "font.ttf"
    path.write_bytes(b"not read by the fake font")
    return path


@pytest.fixture(scope="module")
def built(font_path):
    rom = _rom()
    return rom, _build(rom, font_path)


def _read(rom: bytes, address: int, length: int) -> bytes:
    at = hirom_offset(address)
    return rom[at : at + length]


def _writes(result) -> dict[int, bytes]:
    return {
        overlay.HOOK_ADDRESS: overlay.HOOK_CODE,
        **{
            address: _read(result.rom, address, size)
            for address, size in (
                (overlay.WIDTHS, 224),
                (overlay.GLYPH_ADDRESSES, 3 * 224),
                (overlay.NAMES, 14 * NAME_STRIDE),
                (overlay.MESSAGES, 3 * DLG_COUNT),
            )
        },
    }


def test_the_build_adds_a_mib_and_changes_only_its_places(built):
    rom, result = built
    assert len(result.rom) == overlay.EXPANDED_SIZE == 4 * 1024 * 1024
    assert result.rom[overlay.ROM_SIZE_BYTE] == overlay.ROM_SIZE_CODE
    changed = {
        at
        for at in range(len(rom))
        if rom[at] != result.rom[at] and not overlay.CHECKSUM <= at < overlay.CHECKSUM + 4
    }
    sites = {
        at
        for site in overlay.SITES
        for at in range(hirom_offset(site.address), hirom_offset(site.address) + len(site.patched))
    }
    assert changed <= sites
    for site in overlay.SITES:
        assert _read(result.rom, site.address, len(site.patched)) == site.patched
        assert site.patched[0] == 0x22 and site.patched[3] == overlay.HOOK_ADDRESS >> 16
    added = result.rom[len(rom) :]
    used = sum(len(data) for data in _writes(result).values())
    used += len(_read(result.rom, overlay.GLYPHS, 0x20000).rstrip(b"\xff"))
    assert added.count(0xFF) >= len(added) - used - 0x1000
    assert sum(result.rom) & 0xFFFF == struct.unpack_from("<H", result.rom, overlay.CHECKSUM + 2)[0]
    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["messages"]["narshe.town"]["source_skeleton"] == ["{Terra}"]
    # Seven glyphs and a space, then the three letters of the second page.
    assert result.report["messages"]["narshe.wake"]["pages"] == [[6 * 7 + 4], [6 * 3]]


def test_the_added_banks_hold_the_tables_the_glyphs_and_the_arabic(built):
    rom, result = built
    assert _read(result.rom, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    table = overlay.read_message_table(result.rom)
    assert sorted(table) == sorted(NUMBERS.values())
    # The messages follow each other from the Arabic's first bank; the rest is English.
    assert table[0] == overlay.ARABIC_TEXT and table[1] > table[0]
    entry = _read(result.rom, overlay.MESSAGES + 3 * 3, 3)
    assert entry == b"\xff\xff\xff"
    font = result.font
    for key, number in NUMBERS.items():
        data = overlay.read_arabic_message(result.rom, table[number])
        assert data[-1] == END and engine.command_skeleton(data) == arabic.notation_skeleton(
            ARABIC[key]
        )
        for code in data:
            if code >= arabic.FIRST_CODE:
                assert _read(result.rom, overlay.WIDTHS + code - arabic.FIRST_CODE, 1)[0] == (
                    font.width(code)
                )
    widths, addresses, glyphs = arabic.glyph_table(font, overlay.GLYPHS, 0x20000)
    assert _read(result.rom, overlay.GLYPHS, len(glyphs)) == glyphs
    assert len(glyphs) == len(font.glyphs) * GLYPH_BYTES
    assert _read(result.rom, overlay.GLYPH_ADDRESSES, 3 * 224) == addresses
    assert int.from_bytes(addresses[:3], "little") == overlay.GLYPHS
    terra = _read(result.rom, overlay.NAMES, NAME_STRIDE)
    assert terra.endswith(b"\xff") and 3 <= terra.index(0xFF) <= 6
    assert all(code >= arabic.FIRST_CODE for code in terra[: terra.index(0xFF)])
    assert result.report["names"]["name.terra"] == 6 * terra.index(0xFF)
    # An Arabic message with a name: the name's code stays a byte for the hook.
    town = overlay.read_arabic_message(result.rom, table[0])
    assert town[0] == TERRA


def test_the_arabic_keeps_to_its_banks(font_path, monkeypatch):
    monkeypatch.setattr(overlay, "ARABIC_TEXT_END", overlay.ARABIC_TEXT + 8)
    with pytest.raises(ClassicRetroError) as caught:
        _build(_rom(), font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    monkeypatch.undo()
    # A message that would cross a bank, or end on its last byte, starts the next.
    monkeypatch.setattr(overlay, "BANK", 64)
    result = _build(_rom(), font_path)
    table = overlay.read_message_table(result.rom)
    for address in table.values():
        data = overlay.read_arabic_message(result.rom, address)
        assert (address % 64) + len(data) < 64
    assert table[0] == overlay.ARABIC_TEXT
    assert any(address % 64 == 0 for number, address in table.items() if number)


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, translated=_messages(rom), verify_identity=False)
    assert originals == ENGLISH
    skeletons = overlay.extract_skeletons(rom, translated=_messages(rom), verify_identity=False)
    assert skeletons["narshe.esper"] == ("{Key}",) and skeletons["narshe.late"] == ()
    wrong = tuple(
        dataclasses.replace(message, source_sha256="0" * 64) for message in _messages(rom)
    )
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=wrong, verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    pinned = tuple(
        dataclasses.replace(message, source_skeleton=("{Key}", "{Key}"))
        for message in _messages(rom)
    )
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_skeletons(rom, translated=pinned, verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_different_rom_is_refused(font_path):
    with pytest.raises(ClassicRetroError) as caught:
        _build(_rom(), font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom()[:-1])
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        ((overlay.SITES[0].address, b"\x00"),),
        ((overlay.SITES[6].address + 2, b"\x00"),),
        ((0xC08519, b"\x6b"),),
        ((0xC00000 + overlay.MAP_MODE_BYTE, b"\x21"),),
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def _map_all() -> list[tuple[int, int, str]]:
    spans = [(site.address, len(site.patched), "site") for site in overlay.SITES]
    spans += [(address, len(data), "anchor") for address, data in overlay.ANCHORS.items()]
    return sorted(spans)


def test_the_sites_and_anchors_lie_apart_and_the_parts_are_in_order():
    spans = _map_all()
    for (start, size, _), (next_start, _, _) in zip(spans, spans[1:], strict=False):
        assert start + size <= next_start
    assert all(0xC07000 <= start < 0xC09000 for start, _, _ in spans) and len(overlay.SITES) == 8
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.WIDTHS
    assert overlay.WIDTHS + 224 <= overlay.GLYPH_ADDRESSES
    assert overlay.GLYPH_ADDRESSES + 3 * 224 <= overlay.NAMES
    assert overlay.NAMES + 14 * NAME_STRIDE <= overlay.MESSAGES
    assert overlay.MESSAGES_END == overlay.MESSAGES + 3 * DLG_COUNT <= overlay.GLYPHS
    assert overlay.GLYPHS < overlay.GLYPHS_END <= overlay.ARABIC_TEXT
    assert overlay.ARABIC_TEXT < overlay.ARABIC_TEXT_END == 0xC00000 + overlay.EXPANDED_SIZE
    assert overlay.HOOK_ADDRESS >> 16 == 0xF0 and overlay.GLYPHS & 0xFFFF == 0
    assert overlay.ARABIC_TEXT & 0xFFFF == 0 and overlay.GLYPHS_END - overlay.GLYPHS == 0x20000


def _equates() -> dict[str, int]:
    found = {}
    for line in overlay.HOOK_SOURCE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(\w+)\s*=\s*(\$[0-9A-Fa-f]+|\d+)\b", line)
        if match:
            value = match.group(2)
            found[match.group(1)] = int(value[1:], 16) if value.startswith("$") else int(value)
    return found


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    assert equates["WIDTHS"] == overlay.WIDTHS
    assert equates["GLYPH_ADDRESSES"] == overlay.GLYPH_ADDRESSES
    assert equates["NAMES"] == overlay.NAMES
    assert equates["MESSAGES"] == overlay.MESSAGES
    assert equates["ENGLISH"] == overlay.ENGLISH & 0xFFFF
    assert equates["GLYPHS"] == overlay.GLYPHS
    assert equates["ARABIC_TEXT"] == overlay.ARABIC_TEXT
    assert equates["FONT_WIDTHS"] == engine.FONT_WIDTHS
    for name in ("DRAW_RETURN", "LINE_RETURN", "PAGE_RETURN", "TRANSFER_NONE"):
        assert overlay.ANCHORS[equates[name]] == b"\x60"
    assert overlay.ANCHORS[equates["DTE_PAIR"]][:2] == b"\x29\x7f"
    assert equates["FIRST_CODE"] == arabic.FIRST_CODE
    assert equates["NAME_FIRST"] == engine.NAME_FIRST and equates["NAME_LAST"] == engine.NAME_LAST
    assert equates["NAME_STRIDE"] == NAME_STRIDE and equates["NAME_END"] == arabic.NAME_END
    assert equates["RIGHT_EDGE"] == arabic.RIGHT_EDGE and equates["LEFT_EDGE"] == arabic.LEFT_EDGE
    assert equates["GLYPH_ROWS"] == GLYPH_ROWS and equates["ROW_BYTES"] == arabic.ROW_BYTES
    assert equates["LINE"] == engine.LINE and equates["PAGE"] == engine.PAGE
    assert equates["LINE_CELLS"] == 14 and equates["CHOICE_WIDTH"] == arabic.CHOICE_WIDTH
    assert equates["SPACES"] == engine.SPACES and equates["CHOICE"] == arabic.CHOICE
    assert equates["CHOICES_MAX"] == 4 and equates["CELL_WORDS"] == 0x20
    header = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    for site in overlay.SITES:
        assert f"${site.address >> 16:02X}:{site.address & 0xFFFF:04X}" in header


@pytest.mark.skipif(shutil.which("ca65") is None, reason="needs cc65")
def test_the_stored_hook_matches_its_source(capsys):
    report = overlay.check_hook_code()
    assert report["match"] and report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert main(["targets", "check-hooks", "final-fantasy-iii"]) == 0
    assert str(len(overlay.HOOK_CODE)) in capsys.readouterr().out


def test_the_command_group_encodes(capsys):
    assert main(["final-fantasy-iii", "encode-arabic", "{Terra}: هيا"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["count"] == 7 and encoded["bytes"].startswith("02 ")


def test_the_translations_are_checked_and_encoded_without_the_rom():
    report = overlay.check_ff6_translations()
    assert report["messages"] == 3077 and set(report["names"]) == set(NAME_KEYS)
    assert report["keys"][:2] == ["narshe.000", "narshe.001"]
    assert report["keys"][-1] == "ending.3083" and report["keys"][367] == "locke.369"
    assert report["keys"][1327] == "vector.1330" and report["keys"][1326] == "airship.1329"
    assert report["keys"][1495] == "ruin.1498" and report["keys"][1494] == "maduin.1497"
    assert report["keys"][1884] == "voyage.1888" and report["keys"][1883] == "setzer.1887"
    assert report["keys"][2164] == "island.2168" and report["keys"][2163] == "continent.2167"
    assert (
        report["keys"][2415] == "colosseum.2419" and report["keys"][2414] == "ancient-castle.2418"
    )
    assert report["keys"][2610] == "narshe-ruin.2614" and report["keys"][2609] == "phoenix.2613"
    assert report["keys"][2796] == "gau-father.2800" and report["keys"][2795] == "dream.2799"
    assert "system.2949" not in report["keys"] and "system.2952" in report["keys"]
    assert report["keys"][930] == "castle.933" and report["keys"][64] == "figaro.064"
    assert "returners.364" not in report["keys"] and "doma.484" not in report["keys"]
    encoded = overlay.encode_ff6_arabic_message("{Terra}: هيا")
    assert encoded["count"] == 7 and encoded["bytes"].startswith("02 ")


def test_the_output_is_read_back_before_it_is_accepted(built, monkeypatch, font_path):
    rom, result = built
    monkeypatch.setattr(overlay, "read_message_table", lambda _rom: {})
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    monkeypatch.undo()
    endless = bytes(overlay.EXPANDED_SIZE).replace(b"\x00", b"\x20")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_arabic_message(endless, overlay.ARABIC_TEXT)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_arabic_message(endless, overlay.GLYPHS)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_a_translation_keeps_the_originals_commands(font_path):
    rom = _rom()
    dropped = tuple(
        dataclasses.replace(message, notation="بلا زر.")
        if message.key == "narshe.esper"
        else message
        for message in _messages(rom)
    )
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, translated=dropped)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    twice = _messages(rom) + (_messages(rom)[0],)
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, translated=twice)
    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def test_a_name_too_wide_is_refused(font_path):
    with pytest.raises(ClassicRetroError) as caught:
        _build(_rom(), font_path, names={**NAMES, "name.terra": "تيراتيراتيرا"})
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
