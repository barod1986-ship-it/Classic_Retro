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
    command_skeleton,
    string_bytes,
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
from classic_retro.rom.chrono_trigger_arabic_script import TABLES, ChronoTriggerMessage

TRUCE = TABLES["truce"]
FAIR = TABLES["fair"]
# Invented English for the translated messages (the dictionary's first word,
# "the"); message 1 of the first table is the tail of message 0, after its
# pause of nothing, as the opening's chain is.
ENGLISH = {
    ("truce", 0): "{Crono}…{pause 0F}{box auto}Wake!{pause 00}MOM: Up!",
    ("truce", 6): "MOM: Wake up!{line+}Now!",
    ("truce", 8): "MOM: The fair is on.{box+}Be good!",
    ("truce", 11): "MOM: Right, {Lucca}!",
    ("truce", 14): "Snooze?{line+}   Yes.{line+}   No.",
    ("fair", 3): "Princess!{line}Again?",
}
ARABIC = {
    "truce.000": "{Crono}…{pause 0F}{box auto}استيقظ!{pause 00}الأم: انهض!",
    "truce.001": "الأم: انهض!",
    "truce.006": "الأم: انهض!{line}الآن!",
    "truce.008": "الأم: المهرجان اليوم.\nكن مهذبا!",
    "truce.011": "الأم: صحيح، {Lucca}!",
    "truce.014": "غفوة؟{line}{choice}نعم.{line}{choice}لا.",
    "fair.003": "أميرتي!{line}مجددا؟",
}
CODES = {
    "{line}": 0x05,
    "{line+}": 0x06,
    "{box auto}": 0x09,
    "{box+}": 0x0C,
    "{Crono}": 0x13,
    "{Lucca}": 0x15,
    "{pause 0F}": bytes((0x03, 0x0F)),
    "{pause 00}": bytes((0x03, 0x00)),
}


def _encode(text: str) -> bytes:
    data = bytearray()
    at = 0
    while at < len(text):
        for token, code in CODES.items():
            if text.startswith(token, at):
                data += bytes((code,)) if isinstance(code, int) else code
                at += len(token)
                break
        else:
            data.append(0xA0 + CHARACTERS.index(text[at]))
            at += 1
    return bytes(data) + b"\x00"


def _put(rom: bytearray, address: int, data: bytes) -> None:
    at = overlay.rom_offset(address)
    rom[at : at + len(data)] = data


def _table(rom: bytearray, table: script.StringTable) -> None:
    """The table's pointers just past its entries, a string each ("Line N.") but the
    invented ones; message 1 of the first table points into message 0."""
    pointers = []
    texts = bytearray()
    start = (table.address & 0xFFFF) + 2 * table.count
    tail = None
    for index in range(table.count):
        if table.key == "truce" and index == 1:
            pointers.append(tail)
            continue
        pointers.append(start + len(texts))
        encoded = _encode(ENGLISH.get((table.key, index), f"Line {index}."))
        if table.key == "truce" and index == 0:
            tail = start + encoded.index(b"\x03\x00") + 2
        texts += encoded
    struct.pack_into(f"<{table.count}H", rom, table.address, *pointers)
    rom[table.address + 2 * table.count : table.address + 2 * table.count + len(texts)] = texts


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """4 MiB of zeros but the header, the engine's bytes the overlay checks, a
    dictionary and the two string tables with their pinned counts."""
    rom = bytearray(overlay.ROM_SIZE)
    rom[overlay.MAP_MODE_BYTE] = overlay.MAP_MODES[overlay.ROM_SIZE]
    rom[overlay.ROM_SIZE_BYTE] = overlay.ROM_SIZE_CODES[overlay.ROM_SIZE]
    for site in overlay.SITES:
        _put(rom, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(rom, address, data)
    struct.pack_into("<127H", rom, DICTIONARY_TABLE, *([0xF000] * 127))
    rom[DICTIONARY_BANK + 0xF000 : DICTIONARY_BANK + 0xF004] = bytes([3, 0xCD, 0xC1, 0xBE])
    _table(rom, TRUCE)
    _table(rom, FAIR)
    # Something in every upper half the added banks mirror.
    for bank in range(0x20):
        rom[bank * overlay.BANK + overlay.HALF_BANK + 0x10] = 0x40 + bank
    for address, data in change:
        _put(rom, address, data)
    struct.pack_into("<HH", rom, overlay.CHECKSUM, 0xFFFF ^ (sum(rom) & 0xFFFF), sum(rom) & 0xFFFF)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _messages(rom: bytes | None = None) -> tuple[ChronoTriggerMessage, ...]:
    rom = rom or _rom()
    out = []
    for key in ARABIC:
        table = TABLES[key.rsplit(".", 1)[0]]
        index = int(key.rsplit(".", 1)[1])
        (pointer,) = struct.unpack_from("<H", rom, table.address + 2 * index)
        data = string_bytes(rom, (table.address & ~0xFFFF) + pointer)
        out.append(ChronoTriggerMessage(key, table.address, index, _digest(data), ARABIC[key]))
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


def _encoded(font: CtFont) -> dict[str, bytes]:
    glyph_map = engine.chrono_trigger_glyph_codes(overlay.messages_characters(_messages()))
    encoder = engine.ChronoTriggerArabicEncoder(glyph_map, font)
    return {message.key: encoder.encode(message.notation).data for message in _messages()}


def test_the_build_adds_two_mib_and_changes_only_its_places(built):
    rom, result = built
    assert len(result.rom) == overlay.EXPANDED_SIZE == 6 * 1024 * 1024
    assert result.rom[overlay.MAP_MODE_BYTE] == 0x35 and result.rom[overlay.ROM_SIZE_BYTE] == 0x0D
    assert apply_bps(result.patch.data, rom) == result.rom
    checksum = overlay.checksum_of(result.rom)
    for at in (overlay.CHECKSUM, overlay.HEADER_COPY + 0x1C):
        assert struct.unpack_from("<HH", result.rom, at) == (checksum ^ 0xFFFF, checksum)
    changed = {
        at // 0x1000
        for at in range(0, len(rom), 0x1000)
        if rom[at : at + 0x1000] != result.rom[at : at + 0x1000]
    }
    # The header, the cursor routine (bank $C0) and the engine's sites (bank $C2).
    assert changed == {0x0F, 0x25}
    for site in overlay.SITES:
        assert _read(result.rom, site.address, len(site.patched)) == site.patched
    # The added banks' upper halves are the ROM's first banks' upper halves as they
    # are now (the header's copy, mode and size set, among them).
    for bank in range(0x20):
        low = bank * overlay.BANK + overlay.HALF_BANK
        assert (
            result.rom[overlay.EXTENSION + low : overlay.EXTENSION + low + overlay.HALF_BANK]
            == (result.rom[low : low + overlay.HALF_BANK])
        )
    assert result.rom[overlay.HEADER_COPY + 0x15] == 0x35
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(result.report["messages"]) == set(ARABIC)
    assert result.report["messages"]["truce.011"]["source_skeleton"] == ["{Lucca}"]
    assert result.report["messages"]["truce.000"]["source_skeleton"] == [
        "{Crono}",
        "{pause 0F}",
        "{box auto}",
        "{pause 00}",
    ]
    assert result.report["messages_shared"] == 1
    assert result.report["tables"] == {
        "truce": {"address": "$F70000"},
        "fair": {"address": "$FCBA00"},
    }


def test_the_added_banks_hold_the_hooks_the_tables_the_font_and_the_arabic(built):
    rom, result = built
    out = result.rom
    assert _read(out, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    # The bank index names the first table of $F7 and of $FC, and no other.
    index = struct.unpack_from("<64H", out, overlay.rom_offset(overlay.BANK_INDEX))
    assert index[0x37] == overlay.TABLE_LIST & 0xFFFF
    assert index[0x3C] == (overlay.TABLE_LIST + overlay.TABLE_ENTRY) & 0xFFFF
    assert sum(1 for word in index if word) == 2
    first = struct.unpack_from("<HBHHB", out, overlay.rom_offset(overlay.TABLE_LIST))
    assert first == (0x0000, 0xF7, 2 * TRUCE.count, overlay.ENTRIES & 0xFFFF, 0x41)
    second = struct.unpack_from("<HBHHB", out, overlay.rom_offset(overlay.TABLE_LIST + 8))
    assert second[:3] == (0xBA00, 0xFC, 2 * FAIR.count)
    assert second[3] | second[4] << 16 == overlay.ENTRIES + 3 * TRUCE.count
    assert _read(out, overlay.TABLE_LIST + 16, 8) == bytes(8)
    redirects = overlay.read_redirects(out)
    assert sorted(redirects) == sorted((message.table, message.index) for message in _messages())
    encoded = _encoded(result.font)
    assert redirects[TRUCE.address, 0] == overlay.ARABIC_TEXT
    # Message 1's Arabic is the tail of message 0's, stored once.
    head = encoded["truce.000"]
    assert redirects[TRUCE.address, 1] == overlay.ARABIC_TEXT + len(head) - len(
        encoded["truce.001"]
    )
    for message in _messages():
        arabic = redirects[message.table, message.index]
        data = encoded[message.key]
        assert _read(out, arabic, len(data)) == data
        assert command_skeleton(data) == engine.notation_skeleton(message.notation)
    # A string of another table has no Arabic: its entry is zero.
    assert _read(out, overlay.ENTRIES + 3 * 2, 3) == bytes(3)
    assert _read(out, overlay.ENTRIES + 3 * TRUCE.count + 3 * 3, 3) != bytes(3)
    for code, glyph in result.font.glyphs.items():
        number = code - engine.ARABIC_CODES[0]
        assert _read(out, overlay.ARABIC_WIDTHS + number, 1)[0] == glyph.width
        assert _read(out, overlay.ARABIC_FONT + 48 * number, 48) == glyph.data()
    # The English stays where it was; the rest of the added banks is the fill.
    assert out[TRUCE.address : TRUCE.address + 0x400] == rom[TRUCE.address : TRUCE.address + 0x400]
    text_end = overlay.ARABIC_TEXT + result.report["arabic_message_bytes"]
    assert result.report["arabic_text_banks"] == 1
    assert not any(byte != 0xFF for byte in _read(out, text_end, 0x100))
    assert _read(out, 0x5F0000, 0x10) == bytes((0xFF,)) * 0x10


def test_the_arabic_keeps_to_the_lower_halves_of_its_banks(font_path, monkeypatch):
    monkeypatch.setattr(overlay, "ARABIC_TEXT_END", overlay.ARABIC_TEXT + 8)
    with pytest.raises(ClassicRetroError) as caught:
        _build(_rom(), font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    monkeypatch.undo()
    # A message that would cross the half's end starts the next bank.
    monkeypatch.setattr(overlay, "HALF_BANK", 24)
    monkeypatch.setattr(overlay, "BANK", 64)
    # Invented bytes: the tail message's are the end of the head's, so it is shared.
    encoded = {
        message.key: engine.EncodedMessage(
            bytes(6) if message.key == "truce.001" else bytes(8 + 2 * n), None
        )
        for n, message in enumerate(_messages())
    }
    with pytest.raises(ClassicRetroError) as caught:
        overlay.lay_out_text(
            _messages(), {**encoded, "fair.003": engine.EncodedMessage(bytes(25), None)}
        )
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    layout = overlay.lay_out_text(_messages(), encoded)
    for message in _messages():
        offset = layout.addresses[message.key] - overlay.ARABIC_TEXT
        assert offset % 64 + len(encoded[message.key].data) <= 24, message.key
    assert layout.addresses["truce.000"] == overlay.ARABIC_TEXT
    offsets = [address - overlay.ARABIC_TEXT for address in layout.addresses.values()]
    assert any(offset and offset % 64 == 0 for offset in offsets)
    # A run of bytes a lower half, none over its end, and no fill between the runs.
    assert len(layout.segments) > 1
    for address, data in layout.segments:
        assert (address - overlay.ARABIC_TEXT) % 64 == 0 and len(data) <= 24
    assert layout.shared == 1 and layout.addresses["truce.001"] == overlay.ARABIC_TEXT + 2
    assert layout.size == sum(len(result.data) for result in encoded.values()) - 6
    twice = _messages() + (_messages()[0],)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages(twice, engine.ChronoTriggerArabicEncoder(_map_all()))
    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, messages=_messages(), verify_identity=False)
    assert originals["truce.006"] == "MOM: Wake up!{line+}Now!"
    assert originals["truce.011"] == "MOM: Right, {Lucca}!"
    assert originals["truce.001"] == "MOM: Up!"
    assert originals["fair.003"] == "Princess!{line}Again?"
    changed = dataclasses.replace(_messages()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(changed,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    beyond = dataclasses.replace(_messages()[-1], key="fair.399", index=FAIR.count)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(beyond,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # A table with another count than pinned is refused.
    shorter = bytearray(rom)
    struct.pack_into("<H", shorter, FAIR.address, (FAIR.address & 0xFFFF) + 2 * FAIR.count - 2)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(bytes(shorter), messages=_messages(), verify_identity=False)
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
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(((0xC0FFD5, b"\x35"),)))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        ((0xC258BE, b"\xea"),),  # where the reader goes back
        ((0xC257F7, b"\xea"),),  # a site
        ((0xC25FE8, b"\x11"),),  # a tile column
        ((0xC0F0CE, b"\xea"),),  # the cursor routine's end
        ((0xC0FF03, b"\xea"),),  # the reset stub the mirror carries
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


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
        assert len(site.original) == len(site.patched) >= 4
        opcode, low, high, bank = site.patched[:4]
        assert opcode in (0x22, 0x5C) and bank == overlay.HOOK_ADDRESS >> 16
        assert site.patched[4:] == b"\xea" * (len(site.patched) - 4)
    parts = [
        overlay.HOOK_ADDRESS,
        overlay.BANK_INDEX,
        overlay.TABLE_LIST,
        overlay.TABLE_LIST_END,
        overlay.ARABIC_WIDTHS,
        overlay.ARABIC_FONT,
        overlay.ARABIC_FONT_END,
        overlay.ENTRIES,
        overlay.ENTRIES_END,
        overlay.ARABIC_TEXT,
        overlay.ARABIC_TEXT_END,
    ]
    assert parts == sorted(parts) and parts[0] == overlay.EXTENSION
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.BANK_INDEX
    assert overlay.BANK_INDEX + 2 * overlay.BANK_INDEX_COUNT <= overlay.TABLE_LIST
    assert overlay.ARABIC_WIDTHS + len(engine.ARABIC_CODES) <= overlay.ARABIC_FONT
    assert overlay.ARABIC_FONT + 48 * len(engine.ARABIC_CODES) <= overlay.ARABIC_FONT_END
    # Every part starts in a lower half and ends by its end, under the mirrors.
    for part in (
        overlay.HOOK_ADDRESS,
        overlay.BANK_INDEX,
        overlay.TABLE_LIST,
        overlay.ARABIC_WIDTHS,
        overlay.ARABIC_FONT,
        overlay.ENTRIES,
        overlay.ARABIC_TEXT,
    ):
        assert part & 0xFFFF < overlay.HALF_BANK
    for end in (overlay.TABLE_LIST_END, overlay.ARABIC_FONT_END, overlay.ENTRIES_END):
        assert end & 0xFFFF <= overlay.HALF_BANK
    assert overlay.ARABIC_TEXT_END == overlay.EXPANDED_SIZE
    for start, length in overlay.mirror_ranges():
        assert start & 0xFFFF == overlay.HALF_BANK and length == overlay.HALF_BANK
    assert len(overlay.mirror_ranges()) == len(overlay.EXTENSION_BANKS) == 0x20


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    values = {}
    for name, value in re.findall(r"^(\w+)\s*=\s*(\$?[0-9A-Fa-f]+)", source, re.MULTILINE):
        values[name] = int(value[1:], 16) if value.startswith("$") else int(value)
    return values


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    assert {
        name: equates[name]
        for name in ("DATA_BANK", "BANK_INDEX", "TABLES", "ARABIC_WIDTHS", "ARABIC_FONT")
    } == {
        "DATA_BANK": overlay.EXTENSION,
        "BANK_INDEX": overlay.BANK_INDEX,
        "TABLES": overlay.TABLE_LIST,
        "ARABIC_WIDTHS": overlay.ARABIC_WIDTHS,
        "ARABIC_FONT": overlay.ARABIC_FONT,
    }
    assert (equates["FIRST_ARABIC_BANK"], equates["END_ARABIC_BANK"]) == (
        overlay.FIRST_ARABIC_BANK,
        overlay.END_ARABIC_BANK,
    )
    assert (equates["FIRST_GLYPH"], equates["GLYPH_BYTES"]) == (engine.ARABIC_CODES[0], 48)
    assert equates["MIRROR"] == engine.MIRROR
    # The cursor's cells: the English's at column 2, the Arabic's at 29, past the
    # choice's text, which ends at the mirror of CHOICE_PEN.
    assert equates["CURSOR_MAP"] == 0x1C02 and equates["CURSOR_MAP_RTL"] == 0x1C1D
    assert 8 * 29 >= engine.MIRROR - engine.CHOICE_PEN
    assert equates["TEXT_TILE"] == 0x2902 and equates["TEXT_TILE_RTL"] == 0x2900 + 0x20 + 13
    # Where the hooks go back to: bytes the overlay pins.
    for name in ("DRAW_CHAR", "DICTIONARY", "CONTROL", "GLYPH_BODY", "GLYPH_RTS"):
        assert equates[name] in overlay.ANCHORS, name
    assert equates["ENGINE_RTS"] == 0xC258CB  # inside the pinned DRAW_CHAR bytes
    assert overlay.ANCHORS[0xC258BE][13:] == bytes.fromhex("a910851560")
    for name in ("CURSOR_DONE", "CURSOR_IDLE"):
        assert equates[name] in overlay.ANCHORS, name
    assert overlay.ANCHORS[equates["CURSOR_DONE"]] == bytes.fromhex("2b60")


@pytest.mark.skipif(shutil.which("ca65") is None, reason="needs cc65")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "chrono-trigger"]) == 0
    report = json.loads(capsys.readouterr().out)
    shipped = script.chrono_trigger_arabic_messages()
    assert report["messages"] == len(shipped) and report["laid_out"] is False
    assert report["keys"] == [message.key for message in shipped]
    assert report["tables"] == sorted({message.table_key for message in shipped})
    assert main(["chrono-trigger", "encode-arabic", "بب {Crono}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Initial and final beh, the space, the name's code, the zero.
    assert encoded["count"] == 5 and encoded["bytes"].split()[-2:] == ["13", "00"]
    assert "boxes" not in encoded


def test_the_output_is_read_back_before_it_is_accepted(built):
    rom, result = built
    messages = _messages()
    encoded = overlay.encode_messages(
        messages, engine.ChronoTriggerArabicEncoder(_map_all(), result.font)
    )
    writes = overlay.room_data(rom, messages, encoded, result.font)
    overlay._verify_output(result.rom, rom, writes, messages, encoded)
    a_glyph = next(iter(result.font.glyphs)) - engine.ARABIC_CODES[0]
    for address, what in (
        (overlay.HOOK_ADDRESS + 3, "hook code"),
        (overlay.SITES[1].address + 1, "site at $C258B2"),
        (overlay.BANK_INDEX + 0x6E, "bank index"),
        (overlay.TABLE_LIST + 2, "list of tables"),
        (overlay.ARABIC_WIDTHS + a_glyph, "width table"),
        (overlay.ARABIC_FONT + 48 * a_glyph + 1, "font table"),
        (overlay.ENTRIES + 3 * 6, "entries"),
        (overlay.ARABIC_TEXT + 1, "Arabic text"),
        (0x408010, "added banks differ"),  # a mirror
        (0x428010, "added banks differ"),  # the mirror over the Arabic's first bank
        (0x5F0100, "added banks differ"),  # the fill
        (
            0xC00000 + TRUCE.address + 30,
            f"at {TRUCE.address + 30:#x}, outside the overlay's places",
        ),
    ):
        tampered = bytearray(result.rom)
        tampered[overlay.rom_offset(address)] ^= 0x01
        with pytest.raises(ClassicRetroError) as caught:
            overlay._verify_output(bytes(tampered), rom, writes, messages, encoded)
        assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED, what
        assert what in str(caught.value), what
    # A wrong checksum in either header is caught.
    for at in (overlay.CHECKSUM, overlay.HEADER_COPY + 0x1C):
        wrong = bytearray(result.rom)
        wrong[at] ^= 0x01
        with pytest.raises(ClassicRetroError) as caught:
            overlay._verify_output(bytes(wrong), rom, writes, messages, encoded)
        assert "checksum" in str(caught.value) or "added banks" in str(caught.value)
    # A list of tables that has no end, or is out of order, is caught through the reader.
    unended = bytearray(result.rom)
    at = overlay.rom_offset(overlay.TABLE_LIST)
    unended[at : overlay.rom_offset(overlay.TABLE_LIST_END)] = b"\x01" * (
        overlay.TABLE_LIST_END - overlay.TABLE_LIST
    )
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_redirects(bytes(unended))
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    swapped = bytearray(result.rom)
    swapped[at : at + 16] = result.rom[at + 8 : at + 16] + result.rom[at : at + 8]
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_redirects(bytes(swapped))
    assert "order" in str(caught.value)


def test_the_checksum_counts_the_added_banks_twice():
    rom = bytearray(overlay.EXPANDED_SIZE)
    rom[0x100] = 1
    rom[overlay.EXTENSION + 0x100] = 1
    checksum = overlay.set_checksum(rom)
    assert checksum == 3 + 3 * 0x1FE
    for at in (overlay.CHECKSUM, overlay.HEADER_COPY + 0x1C):
        assert struct.unpack_from("<HH", rom, at) == (checksum ^ 0xFFFF, checksum)
    assert overlay.checksum_of(bytes(rom)) == checksum


def test_a_translation_keeps_the_originals_commands(font_path):
    """Lucca's message writes her name. The build holds each translation against the ROM's
    commands, the check against the pinned ones."""
    rom = _rom()
    by_key = {message.key: message for message in _messages()}
    lucca = by_key["truce.011"]
    for notation in (
        "الأم: صحيح!",  # the name dropped
        "الأم: صحيح، {Lucca} {Crono}!",  # a name added
        "الأم: صحيح، {Marle}!",  # another name
    ):
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path, messages=(dataclasses.replace(lucca, notation=notation),))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION, notation
    # The chained message must keep its pauses and its box without the button.
    head = by_key["truce.000"]
    for notation in (
        "{Crono}…{pause 0F}\nاستيقظ!{pause 00}الأم: انهض!",  # the box waits
        "{Crono}…{box auto}استيقظ!{pause 00}الأم: انهض!",  # a pause dropped
    ):
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path, messages=(dataclasses.replace(head, notation=notation),))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION, notation
    kept = _build(rom, font_path, messages=(by_key["truce.006"], lucca))
    assert kept.report["messages"]["truce.011"]["source_skeleton"] == ["{Lucca}"]
    assert kept.report["messages"]["truce.006"]["source_skeleton"] == []
    # A pinned skeleton is held against the ROM's, at the build and at the extraction.
    pinned = dataclasses.replace(lucca, source_skeleton=("{Lucca}",))
    assert _build(rom, font_path, messages=(pinned,)).rom
    wrong = dataclasses.replace(lucca, source_skeleton=("{Crono}",))
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, messages=(wrong,))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(wrong,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # Without the ROM, the pinned skeleton is what the translation is held against.
    encoder = engine.ChronoTriggerArabicEncoder(_map_all())
    assert overlay.encode_messages((pinned,), encoder)["truce.011"].data.endswith(b"\x00")
    dropped = dataclasses.replace(pinned, notation="الأم: صحيح!")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages((dropped,), encoder)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    skeletons = overlay.extract_skeletons(rom, messages=_messages(), verify_identity=False)
    assert skeletons["truce.006"] == () and skeletons["truce.011"] == ("{Lucca}",)
    assert skeletons["truce.001"] == () and skeletons["fair.003"] == ()
