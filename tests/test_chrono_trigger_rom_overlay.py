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
from classic_retro.engines import chrono_trigger_arabic as engine
from classic_retro.engines.chrono_trigger import (
    CHARACTERS,
    DICTIONARY_BANK,
    DICTIONARY_TABLE,
    string_notation,
)
from classic_retro.engines.chrono_trigger_arabic import (
    CELL,
    CLEAR,
    INK,
    SPACE_WIDTH,
    WIDEST,
    CtFont,
    CtGlyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import chrono_trigger_arabic as overlay
from classic_retro.rom import chrono_trigger_arabic_script as script
from classic_retro.rom.chrono_trigger_arabic_script import ChronoTriggerMessage

TABLE = script.STRING_TABLE
# Invented English for the three messages (the dictionary's first word, "the").
ENGLISH = {
    6: "MOM: Wake up!{line+}Now!",
    8: "MOM: The fair is on.{box+}Be good!",
    11: "MOM: Right, {Lucca}!",
}
ARABIC = {
    "opening.get_up": "الأم: انهض!{line}الآن!",
    "opening.the_fair": "الأم: المهرجان اليوم.\nكن مهذبا!",
    "opening.lucca": "الأم: صحيح، {Lucca}!",
}
NAMES = {"{line+}": 0x06, "{box+}": 0x0C, "{Lucca}": 0x15}


def _encode(text: str) -> bytes:
    data = bytearray()
    at = 0
    while at < len(text):
        for token, code in NAMES.items():
            if text.startswith(token, at):
                data.append(code)
                at += len(token)
                break
        else:
            data.append(0xA0 + CHARACTERS.index(text[at]))
            at += 1
    return bytes(data) + b"\x00"


def _put(rom: bytearray, address: int, data: bytes) -> None:
    at = overlay.rom_offset(address)
    rom[at : at + len(data)] = data


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """4 MiB of zeros but the engine's bytes the overlay checks, a dictionary and a string
    table of 12 messages (the three translated among them)."""
    rom = bytearray(overlay.ROM_SIZE)
    for site in overlay.SITES:
        _put(rom, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(rom, address, data)
    struct.pack_into("<127H", rom, DICTIONARY_TABLE, *([0xF000] * 127))
    rom[DICTIONARY_BANK + 0xF000 : DICTIONARY_BANK + 0xF004] = bytes([3, 0xCD, 0xC1, 0xBE])
    pointers = []
    texts = bytearray()
    for index in range(12):
        pointers.append(24 + len(texts))
        texts += _encode(ENGLISH.get(index, f"Line {index}."))
    struct.pack_into("<12H", rom, TABLE, *pointers)
    rom[TABLE + 24 : TABLE + 24 + len(texts)] = texts
    for address, data in change:
        _put(rom, address, data)
    overlay.set_checksum(rom)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _messages(rom: bytes | None = None) -> tuple[ChronoTriggerMessage, ...]:
    rom = rom or _rom()
    out = []
    for key, (index, _) in script._SOURCES.items():
        (pointer,) = struct.unpack_from("<H", rom, TABLE + 2 * index)
        at = TABLE + pointer
        data = rom[at : rom.index(b"\x00", at) + 1]
        out.append(ChronoTriggerMessage(key, TABLE, index, _digest(data), ARABIC[key]))
    return tuple(out)


def _fake_font(font_path=None, glyph_map=None, used=(), **_kwargs) -> CtFont:
    """Every glyph a bar 6 pixels wide; the space the real one."""
    assert glyph_map is not None
    bar = CtGlyph(6, tuple((INK,) * 6 + (CLEAR,) * (WIDEST - 6) for _ in range(CELL)))
    space = CtGlyph(SPACE_WIDTH, ((CLEAR,) * WIDEST,) * CELL)
    return CtFont({glyph_map.code(c): space if c == " " else bar for c in used}, 9)


def _build(rom: bytes, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_chrono_trigger_font", _fake_font)
        return overlay.build_chrono_trigger_arabic_rom(
            rom,
            font_path,
            messages=options.pop("messages", _messages(rom)),
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
    at = overlay.rom_offset(address)
    return rom[at : at + length]


def test_the_build_changes_only_the_sites_the_room_and_the_checksum(built):
    rom, result = built
    assert len(result.rom) == len(rom)
    assert apply_bps(result.patch.data, rom) == result.rom
    (checksum,) = struct.unpack_from("<H", result.rom, overlay.CHECKSUM + 2)
    (complement,) = struct.unpack_from("<H", result.rom, overlay.CHECKSUM)
    assert sum(result.rom) & 0xFFFF == checksum and checksum ^ complement == 0xFFFF
    for site in overlay.SITES:
        assert _read(result.rom, site.address, 4) == site.patched
    changed = {
        at // 0x10000
        for at in range(0, len(rom), 0x1000)
        if rom[at : at + 0x1000] != result.rom[at : at + 0x1000]
    }
    assert changed == {0x00, 0x02, 0x1B}  # the header, the engine's bank, the room's
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(result.report["messages"]) == set(ARABIC)


def test_the_room_holds_the_hooks_the_list_the_font_and_the_arabic(built):
    rom, result = built
    out = result.rom
    assert _read(out, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    glyph_map = engine.chrono_trigger_glyph_codes(overlay.messages_characters(_messages()))
    encoder = engine.ChronoTriggerArabicEncoder(glyph_map, result.font)
    arabic = overlay.MESSAGES
    for number, message in enumerate(_messages()):
        english, english_bank, target, bank = struct.unpack_from(
            "<HBHB", _read(out, overlay.REDIRECTS + 6 * number, 6)
        )
        (pointer,) = struct.unpack_from("<H", rom, TABLE + 2 * message.index)
        assert (english, english_bank) == (pointer, 0xC0 + (TABLE >> 16))
        assert (target | bank << 16) == arabic
        data = encoder.encode(message.notation).data
        assert _read(out, arabic, len(data)) == data
        arabic += len(data)
    assert _read(out, overlay.REDIRECTS + 18, 6) == bytes(6)
    assert not any(_read(out, arabic, overlay.ROOM_END - arabic))
    for code, glyph in result.font.glyphs.items():
        index = code - engine.ARABIC_CODES[0]
        assert _read(out, overlay.ARABIC_WIDTHS + index, 1)[0] == glyph.width
        assert _read(out, overlay.ARABIC_FONT + 48 * index, 48) == glyph.data()
    # The English stays where it was.
    assert out[TABLE : TABLE + 0x200] == rom[TABLE : TABLE + 0x200]


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, messages=_messages(), verify_identity=False)
    assert originals["opening.get_up"] == "MOM: Wake up!{line+}Now!"
    assert originals["opening.lucca"] == "MOM: Right, {Lucca}!"
    changed = dataclasses.replace(_messages()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(changed,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    words = overlay.dictionary(rom)
    assert string_notation(bytes([0x21]), words) == "the"


def test_a_different_rom_is_refused(font_path):
    rom = _rom()
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(rom[:-0x10000])
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        ((0xC258BE, b"\xea"),),  # where the reader goes back
        ((0xC257F7, b"\xea"),),  # a site
        ((0xC25FE8, b"\x11"),),  # a tile column
        ((overlay.ROOM_END - 1, b"\x01"),),  # the room is not empty
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_the_arabic_keeps_to_the_room(font_path, monkeypatch):
    rom = _rom()
    monkeypatch.setattr(overlay, "ROOM_END", overlay.MESSAGES + 16)
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    twice = _messages() + (_messages()[0],)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages(twice, engine.ChronoTriggerArabicEncoder(_map_all()))
    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def _map_all():
    return engine.chrono_trigger_glyph_codes(overlay.messages_characters(_messages()))


def test_the_sites_and_anchors_lie_apart_and_the_room_holds_its_parts():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched) == 4
        opcode, low, high, bank = site.patched
        assert opcode in (0x22, 0x5C) and bank == overlay.ARABIC_BANK
    parts = [
        overlay.HOOK_ADDRESS,
        overlay.REDIRECTS,
        overlay.ARABIC_WIDTHS,
        overlay.ARABIC_FONT,
        overlay.MESSAGES,
        overlay.ROOM_END,
    ]
    assert parts == sorted(parts) and parts[0] == overlay.ROOM_START
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.REDIRECTS
    assert overlay.ARABIC_WIDTHS + len(engine.ARABIC_CODES) <= overlay.ARABIC_FONT
    assert overlay.ARABIC_FONT + 48 * len(engine.ARABIC_CODES) <= overlay.MESSAGES


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    values = {}
    for name, value in re.findall(r"^(\w+)\s*=\s*(\$?[0-9A-Fa-f]+)", source, re.MULTILINE):
        values[name] = int(value[1:], 16) if value.startswith("$") else int(value)
    return values


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    assert {
        name: equates[name] for name in ("ARABIC_BANK", "REDIRECTS", "ARABIC_WIDTHS", "ARABIC_FONT")
    } == {
        "ARABIC_BANK": overlay.ARABIC_BANK,
        "REDIRECTS": overlay.REDIRECTS,
        "ARABIC_WIDTHS": overlay.ARABIC_WIDTHS,
        "ARABIC_FONT": overlay.ARABIC_FONT,
    }
    assert (equates["FIRST_GLYPH"], equates["GLYPH_BYTES"]) == (engine.ARABIC_CODES[0], 48)
    assert equates["MIRROR"] == engine.MIRROR
    # Where the hooks go back to: bytes the overlay pins.
    for name in ("DRAW_CHAR", "DICTIONARY", "CONTROL", "GLYPH_BODY", "GLYPH_RTS"):
        assert equates[name] in overlay.ANCHORS, name
    assert equates["ENGINE_RTS"] == 0xC258CB  # inside the pinned DRAW_CHAR bytes
    assert overlay.ANCHORS[0xC258BE][13:] == bytes.fromhex("a910851560")


@pytest.mark.skipif(shutil.which("ca65") is None, reason="needs cc65")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "chrono-trigger"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 3 and report["laid_out"] is False
    assert report["keys"] == ["opening.get_up", "opening.the_fair", "opening.lucca"]
    assert main(["chrono-trigger", "encode-arabic", "بب {Crono}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Initial and final beh, the space, the name's code, the zero.
    assert encoded["count"] == 5 and encoded["bytes"].split()[-2:] == ["13", "00"]
    assert "boxes" not in encoded
