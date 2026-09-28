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
from classic_retro.engines import alttp_arabic as engine
from classic_retro.engines.alttp import (
    CHARACTERS,
    COMMAND_CODES,
    DICTIONARY_BANK,
    END,
    FINISH,
    MESSAGE_DATA,
    WORD_DICTIONARY,
    lorom_offset,
    message_notation,
    messages,
)
from classic_retro.engines.alttp_arabic import (
    CELL,
    CLEAR,
    INK,
    SPACE_CODE,
    SPACE_WIDTH,
    AlttpFont,
    AlttpGlyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import alttp_arabic as overlay
from classic_retro.rom import alttp_arabic_script as script
from classic_retro.rom.alttp_arabic_script import AlttpMessage

# Invented English for the three messages (the dictionary's first word, "the").
ENGLISH = {
    0x0D: "{Name}, the door.{2}Stay in.",
    0x1F: "{Window 02}{Speed 03}Hello.{Waitkey}{Scroll}Come.",
    0x51: "A lamp!{2}Light.",
}
ARABIC = {
    "house.uncle": "{Name}، الباب.{line}ابق هنا.",
    "house.zelda_calls": "{Window 02}{Speed 03}مرحبا.\nتعال.",
    "house.lamp": "مصباح!{line}نور.",
}


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
        elif text.startswith("the", at):
            data.append(0x88)
            at += 3
        else:
            data.append(CHARACTERS.index(text[at]))
            at += 1
    return bytes(data) + bytes((END,))


def _put(rom: bytearray, address: int, data: bytes) -> None:
    at = lorom_offset(address)
    rom[at : at + len(data)] = data


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """1 MiB of zeros but the header's size, the engine's bytes the overlay checks, the
    hooks' free room, a dictionary and 0x60 messages (the three translated among them)."""
    rom = bytearray(overlay.ROM_SIZE)
    rom[overlay.ROM_SIZE_BYTE] = 0x0A
    for site in overlay.SITES:
        _put(rom, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(rom, address, data)
    _put(rom, overlay.HOOK_ROOM_START, b"\xff" * (overlay.HOOK_ROOM_END - overlay.HOOK_ROOM_START))
    pointers = [0xC7C7, 0xC7CA] + [0xC7CA] * 96
    struct.pack_into("<98H", rom, WORD_DICTIONARY, *pointers)
    rom[DICTIONARY_BANK + 0xC7C7 : DICTIONARY_BANK + 0xC7CA] = bytes(
        CHARACTERS.index(c) for c in "the"
    )
    texts = bytearray()
    for index in range(0x60):
        texts += _encode(ENGLISH.get(index, f"Line {index}."))
    texts.append(FINISH)
    rom[MESSAGE_DATA : MESSAGE_DATA + len(texts)] = texts
    for address, data in change:
        _put(rom, address, data)
    overlay.set_checksum(rom)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _messages(rom: bytes | None = None) -> tuple[AlttpMessage, ...]:
    stored = messages(rom or _rom())
    return tuple(
        AlttpMessage(key, index, _digest(stored[index].data), ARABIC[key])
        for key, (index, _) in script._SOURCES.items()
    )


def _fake_font(font_path=None, glyph_map=None, used=(), **_kwargs) -> AlttpFont:
    """Every glyph a bar 6 pixels wide; the space the real one."""
    assert glyph_map is not None
    bar = AlttpGlyph(6, tuple((INK,) * 6 + (CLEAR,) * (CELL - 6) for _ in range(CELL)))
    space = AlttpGlyph(SPACE_WIDTH, ((CLEAR,) * CELL,) * CELL)
    return AlttpFont({glyph_map.code(c): space if c == " " else bar for c in used}, 11)


def _build(rom: bytes, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_alttp_font", _fake_font)
        return overlay.build_alttp_arabic_rom(
            rom,
            font_path,
            translated=options.pop("translated", _messages(rom)),
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
    at = lorom_offset(address)
    return rom[at : at + length]


def test_the_build_adds_a_mib_and_changes_only_its_places(built):
    rom, result = built
    assert len(result.rom) == overlay.EXPANDED_SIZE and result.rom[: len(rom)] != rom
    assert result.rom[overlay.ROM_SIZE_BYTE] == 0x0B
    assert apply_bps(result.patch.data, rom) == result.rom
    (checksum,) = struct.unpack_from("<H", result.rom, overlay.CHECKSUM + 2)
    (complement,) = struct.unpack_from("<H", result.rom, overlay.CHECKSUM)
    assert sum(result.rom) & 0xFFFF == checksum and checksum ^ complement == 0xFFFF
    for site in overlay.SITES:
        assert _read(result.rom, site.address, len(site.patched)) == site.patched
    changed = {
        at // 0x10000
        for at in range(0, len(rom), 0x1000)
        if rom[at : at + 0x1000] != result.rom[at : at + 0x1000]
    }
    assert changed == {0x00, 0x07}  # the header, the engine's bank $0E
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(result.report["messages"]) == set(ARABIC)
    # The English stays where it was, as it was.
    assert (
        result.rom[MESSAGE_DATA : MESSAGE_DATA + 0x800] == rom[MESSAGE_DATA : MESSAGE_DATA + 0x800]
    )


def test_the_added_banks_hold_the_list_the_font_and_the_arabic(built):
    rom, result = built
    out = result.rom
    assert _read(out, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    glyph_map = engine.alttp_glyph_codes(overlay.messages_characters(_messages()))
    encoder = engine.AlttpArabicEncoder(glyph_map, result.font)
    arabic = overlay.MESSAGES
    for number, message in enumerate(_messages()):
        index, target, bank = struct.unpack_from(
            "<HHB", _read(out, overlay.REDIRECTS + overlay.REDIRECT_ENTRY * number, 5)
        )
        assert index == message.index and (target | bank << 16) == arabic
        data = encoder.encode(message.notation).data
        assert _read(out, arabic, len(data)) == data
        arabic += len(data)
    assert _read(out, overlay.REDIRECTS + 15, 2) == b"\xff\xff"
    assert set(_read(out, arabic, 0x100)) == {overlay.EXPANSION_FILL}
    for code, glyph in result.font.glyphs.items():
        assert _read(out, overlay.ARABIC_WIDTHS + code, 1)[0] == glyph.width
        assert _read(out, overlay.ARABIC_FONT + 64 * code, 64) == glyph.data()
    assert _read(out, overlay.ARABIC_WIDTHS + SPACE_CODE, 1)[0] == SPACE_WIDTH
    assert _read(out, overlay.ARABIC_WIDTHS + 0x70, 1)[0] == 0  # a command's code: no glyph


def test_a_message_never_runs_across_a_bank(font_path):
    rom = _rom()
    long = dataclasses.replace(_messages()[1], notation="\n".join(["مرحبا"] * 20))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "MESSAGES", 0x21FFF0)
        result = _build(rom, font_path, translated=(long,))
        index, target, bank = struct.unpack_from("<HHB", _read(result.rom, overlay.REDIRECTS, 5))
    assert (target | bank << 16) == 0x228000


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, translated=_messages(), verify_identity=False)
    assert originals["house.uncle"] == "{Name}, the door.{2}Stay in."
    assert originals["house.zelda_calls"].startswith("{Window 02}{Speed 03}Hello.")
    changed = dataclasses.replace(_messages()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(changed,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    missing = dataclasses.replace(_messages()[0], index=0x200)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(missing,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    words = overlay.dictionary(rom)
    assert message_notation(bytes([0x88]), words) == "the"
    assert overlay.message_address(rom, 0) == 0x1C8000


def test_a_different_rom_is_refused(font_path):
    rom = _rom()
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(rom[:-0x8000])
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        ((0x0EC4E7, b"\xea"),),  # where an English message goes on
        ((0x0ECAD5, b"\xea"),),  # a site
        ((0x0ECADF, b"\x09"),),  # a width the name is measured with
        ((0x0ED36E, b"\x01"),),  # the flag's first value
        ((overlay.HOOK_ROOM_END - 1, b"\x00"),),  # the hooks' room is not free
        ((0x00FFD7, b"\x0b"),),  # the header says 2 MiB
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_the_arabic_keeps_to_the_added_banks(font_path, monkeypatch):
    rom = _rom()
    monkeypatch.setattr(overlay, "MESSAGES_END", overlay.MESSAGES + 16)
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    twice = _messages() + (_messages()[0],)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages(twice, engine.AlttpArabicEncoder(_map_all()))
    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def _map_all():
    return engine.alttp_glyph_codes(overlay.messages_characters(_messages()))


def test_the_sites_and_anchors_lie_apart_and_the_parts_are_in_order():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    hooks = range(overlay.HOOK_ADDRESS, overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE))
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched)
        if len(site.patched) == 2:  # the draw table's entry
            (target,) = struct.unpack("<H", site.patched)
        else:
            assert site.patched[0] in (0x4C, 0x20) and set(site.patched[3:]) <= {0xEA}
            (target,) = struct.unpack("<H", site.patched[1:3])
        assert 0x0E0000 | target in hooks
    assert overlay.HOOK_ROOM_START <= overlay.HOOK_ADDRESS < overlay.HOOK_ROOM_END
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.HOOK_ROOM_END
    parts = [overlay.REDIRECTS, overlay.ARABIC_WIDTHS, overlay.ARABIC_FONT, overlay.MESSAGES]
    assert parts == sorted(parts)
    assert overlay.ARABIC_WIDTHS + overlay.CODES <= overlay.ARABIC_FONT
    assert overlay.ARABIC_FONT + 64 * overlay.CODES <= 0x210000
    assert max(engine.ARABIC_CODES) < overlay.CODES
    assert lorom_offset(overlay.REDIRECTS) == overlay.ROM_SIZE


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    values = {}
    for name, value in re.findall(r"^(\w+)\s*=\s*(\$?[0-9A-Fa-f]+)", source, re.MULTILINE):
        values[name] = int(value[1:], 16) if value.startswith("$") else int(value)
    return values


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    for name in ("REDIRECTS", "ARABIC_WIDTHS", "ARABIC_FONT"):
        assert equates[name] == getattr(overlay, name), name
    assert equates["RIGHT"] == engine.LINE_WIDTH
    assert (equates["ISLAND"], equates["NAME"], equates["NUMBER"]) == (
        COMMAND_CODES["Name"],
        COMMAND_CODES["Name"],
        COMMAND_CODES["Number"],
    )
    assert equates["ISLAND_END"] == COMMAND_CODES["Window"]  # never written by the parser
    assert (equates["FIRST_COMMAND"], equates["END"], equates["GLYPHS_ABOVE"]) == (0x67, 0x7F, 0x80)
    # The engine's code and tables the hooks call or read: bytes the overlay pins.
    for name in ("PARSE_ENGLISH", "EXECUTE", "PERFORM_VWF", "ENGLISH_WIDTHS", "RENDER_OFFSETS"):
        assert 0x0E0000 | equates[name] in overlay.ANCHORS, name
    assert overlay.ANCHORS[0x0ECB4A][6:] == struct.pack("<3H", 0x00, 0x40, 0x80)  # LINE_OFFSETS
    assert equates["LINE_OFFSETS"] == 0xCB50
    assert overlay.ANCHORS[0x0ECC50][4:7] == bytes([0x69]) + struct.pack("<H", equates["HALF"])
    assert equates["ENGLISH_FONT"] == 0x0E8000
    assert overlay.ANCHORS[0x0ECBB2][:3] == bytes([0xA9, 0x00, 0x80])
    # FLAG is a byte of the engine's settings that starts at 0 for each message.
    assert 0x0ED35A + equates["FLAG"] - 0x1CD0 == 0x0ED36E
    assert overlay.ANCHORS[0x0ED36E] == b"\x00"


@pytest.mark.skipif(shutil.which("ca65") is None, reason="needs cc65")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "link-to-the-past"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 3 and report["laid_out"] is False
    assert report["keys"] == ["house.uncle", "house.zelda_calls", "house.lamp"]
    assert main(["link-to-the-past", "encode-arabic", "بب {Name}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Initial and final beh, the space, the name, the end.
    assert encoded["count"] == 5 and encoded["bytes"].split()[-3:] == ["59", "6A", "7F"]
    assert "pages" not in encoded
