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
from classic_retro.engines import ff4_arabic as engine
from classic_retro.engines.ff4 import (
    BANKS,
    CHARACTER_CODES,
    COMMAND_CODES,
    DTE_CODES,
    DTE_FIRST,
    DTE_TABLE,
    END,
    FONT,
    FONT_TILE_BYTES,
    LINE,
    lorom_address,
    lorom_offset,
    message_at,
    message_notation,
)
from classic_retro.engines.ff4_arabic import (
    BACKGROUND,
    CELL,
    CELL_HEIGHT,
    INK,
    LETTER_CODES,
    PAIR_CODES,
    TILE_ROWS,
    Ff4Font,
    Ff4Glyph,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import ff4_arabic as overlay
from classic_retro.rom import ff4_arabic_script as script
from classic_retro.rom.ff4_arabic_script import NAME_KEYS, Ff4Message

# Invented English for the six messages, with the commands the Arabic keeps.
ENGLISH = {
    "deck.arrive": "Crew:Captain {Name 00},{line} arrive!{line}{Name 00}:Good.",
    "deck.robbing": "Crew:Why?{line}Crew:Duty.",
    "deck.captain": "Crew:Sir!{line}{Name 00}:Listen!",
    "deck.monsters": "Crew:Monst!",
    "deck.ouch": "Crew:Ouch!{line}{Name 00}:Okay?{line}{Name 00}:Watch out!",
    "deck.baron": "Crew:Baron!{line}{Name 00}:Land.",
}
ARABIC = {
    "deck.arrive": "الطاقم:أيها القائد {Name 00}،{line}وصلنا!{line}{Name 00}:جيد.",
    "deck.robbing": "الطاقم:لماذا؟{line}الطاقم:واجب.",
    "deck.captain": "الطاقم:سيدي!{line}{Name 00}:أنصتوا!",
    "deck.monsters": "الطاقم:وحوش!!",
    "deck.ouch": "الطاقم:آه!{line}{Name 00}:بخير؟\n{Name 00}:احذر!",
    "deck.baron": "الطاقم:بارون!{line}{Name 00}:اهبط.",
}
NAMES = dict(
    zip(
        NAME_KEYS,
        "سيسل كاين ريديا تيلا إدوارد روزا يانغ بالوم بوروم سيد إدج فسويا غولبز آنا".split(),
        strict=True,
    )
)


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
    at = lorom_offset(address)
    rom[at : at + len(data)] = data


@cache
def _rom(change: tuple[tuple[int, bytes], ...] = ()) -> bytes:
    """1 MiB of zeros but the header's size, the engine's bytes the overlay checks, a
    table of pairs, and the six messages at their pinned offsets of bank 1."""
    rom = bytearray(overlay.ROM_SIZE)
    rom[overlay.ROM_SIZE_BYTE] = 0x0A
    for site in overlay.SITES:
        _put(rom, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(rom, address, data)
    for code in DTE_CODES:
        _put(rom, DTE_TABLE + 2 * (code - DTE_FIRST), bytes([0x42, 0x43]))
    _put(rom, FONT + LETTER_CODES[0] * FONT_TILE_BYTES, bytes(range(1, 17)) * len(LETTER_CODES))
    bank = BANKS[1]
    pointers = []
    for key, (_, offset, _, _) in script._SOURCES.items():
        _put(rom, bank.text + offset, _encode(ENGLISH[key]))
        pointers.append(offset)
    struct.pack_into(f"<{len(pointers)}H", rom, lorom_offset(bank.pointers), *pointers)
    for address, data in change:
        _put(rom, address, data)
    overlay.set_checksum(rom)
    return bytes(rom)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _messages(rom: bytes | None = None) -> tuple[Ff4Message, ...]:
    rom = rom or _rom()
    return tuple(
        Ff4Message(key, bank, offset, _digest(message_at(rom, bank, offset).data), ARABIC[key])
        for key, (bank, offset, _, _) in script._SOURCES.items()
    )


def _fake_font(font_path=None, used=(), **_kwargs) -> Ff4Font:
    """Every form a cell with a bar of its own in its bottom half; the initial and
    medial forms a dot in their top half too."""
    glyphs = {}
    drawn = sorted(character for character in used if character not in engine._GAME_CHARACTERS)
    for number, character in enumerate(drawn):
        rows = [[BACKGROUND] * CELL for _ in range(CELL_HEIGHT)]
        for x in range(CELL):
            if number >> (x % 7) & 1 or x == 7:
                rows[TILE_ROWS + 1 + number % 6][x] = INK
        if engine.joins_left_neighbour(character):
            rows[2][number % CELL] = INK
        glyphs[character] = Ff4Glyph(1, tuple(tuple(row) for row in rows))
    return Ff4Font(glyphs, 11)


def _build(rom: bytes, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_ff4_font", _fake_font)
        return overlay.build_ff4_arabic_rom(
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
    assert changed == {0x00, 0x05}  # the header and the engine's bank $00, the font's bank $0A
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(result.report["messages"]) == set(ARABIC)
    assert result.report["names"]["name.00"] == 4
    # The English stays where it was, as it was.
    text = lorom_offset(BANKS[1].text)
    assert result.rom[text : text + 0x800] == rom[text : text + 0x800]
    # The Latin letters' tiles too: the hook puts them back from here.
    latin = lorom_offset(overlay.LATIN_TILES)
    assert result.rom[latin : latin + 52 * 16] == rom[latin : latin + 52 * 16]


def test_the_added_banks_hold_the_list_the_tiles_the_names_and_the_arabic(built):
    rom, result = built
    out = result.rom
    assert _read(out, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    tiles = result.tiles
    assert _read(out, overlay.TOP_FIRST, 1)[0] == tiles.top_first
    encoder = engine.Ff4ArabicEncoder(tiles.codes, tiles)
    arabic = 0
    for number, message in enumerate(_messages()):
        bank, offset, target = struct.unpack_from(
            "<BHH", _read(out, overlay.REDIRECTS + overlay.REDIRECT_ENTRY * number, 5)
        )
        assert (bank, offset) == (message.bank, message.offset) and target == arabic
        data = encoder.encode(message.notation).data
        assert _read(out, overlay.ARABIC_TEXT + arabic, len(data)) == data
        arabic += len(data)
    assert _read(out, overlay.REDIRECTS + 30, 1) == b"\xff"
    assert set(_read(out, overlay.ARABIC_TEXT + arabic, 0x100)) == {overlay.EXPANSION_FILL}
    for number, code in enumerate(LETTER_CODES):
        tile = tiles.tiles.get(code, engine.SPACE_TILE)
        assert _read(out, overlay.LETTER_TILES + 16 * number, 16) == tile
    for code in PAIR_CODES:
        tile = tiles.tiles.get(code, bytes(16))
        assert _read(out, FONT + code * FONT_TILE_BYTES, 16) == tile
    for number, key in enumerate(NAME_KEYS):
        entry = _read(out, overlay.NAMES + overlay.NAME_STRIDE * number, overlay.NAME_STRIDE)
        codes = engine.encode_name(encoder, key, NAMES[key])
        assert entry == codes + b"\xff" * (overlay.NAME_STRIDE - len(codes))


def test_the_arabic_keeps_to_its_bank(font_path, monkeypatch):
    rom = _rom()
    monkeypatch.setattr(overlay, "ARABIC_TEXT_END", overlay.ARABIC_TEXT + 16)
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    twice = _messages() + (_messages()[0],)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages(twice, engine.Ff4ArabicEncoder(_map_all()))
    assert caught.value.code is ErrorCode.DUPLICATE_ENTRY_ID


def test_originals_are_extracted_and_verified():
    rom = _rom()
    originals = overlay.extract_originals(rom, translated=_messages(), verify_identity=False)
    assert originals["deck.arrive"] == "Crew:Captain {Name 00},{line} arrive!{line}{Name 00}:Good."
    assert originals["deck.monsters"] == "Crew:Monst!"
    changed = dataclasses.replace(_messages()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(changed,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    missing = dataclasses.replace(_messages()[0], offset=0x0291)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(missing,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert message_notation(bytes([0x8A]), {0x8A: "BC"}) == "BC"
    assert lorom_address(lorom_offset(BANKS[1].text)) == BANKS[1].text


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
        ((0x00B224, b"\xea"),),  # DecodeDlgText's loop
        ((0x00B2BE, b"\xea"),),  # a site
        ((0x00B2C5, b"\xea"),),  # GetByte's English banks
        ((0x00B564, b"\xea"),),  # the transfer the hook repeats
        ((0x00FFD7, b"\x0b"),),  # the header says 2 MiB
    ],
)
def test_engine_code_that_differs_where_the_overlay_works_is_refused(change):
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(_rom(change))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_font_tile_that_is_not_blank_is_refused():
    code = PAIR_CODES[3]
    rom = _rom(((FONT + code * FONT_TILE_BYTES + 5, b"\x01"),))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_rom(rom)
    assert caught.value.code is ErrorCode.SAFE_REGION_CONTENT_MISMATCH
    assert str(caught.value) == (
        f"The font's tile {code:#04x} holds data at "
        f"{lorom_offset(FONT) + code * FONT_TILE_BYTES + 5:#x}, where 0x00 was expected"
    )


def _map_all():
    used = overlay.messages_characters(_messages(), NAMES)
    return engine.ff4_glyph_codes(used)


def test_the_sites_and_anchors_lie_apart_and_the_parts_are_in_order():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    hooks = range(overlay.HOOK_ADDRESS, overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE))
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched) >= 4
        assert site.patched[0] == 0x5C and set(site.patched[4:]) <= {0xEA}
        target = int.from_bytes(site.patched[1:4], "little")
        assert target in hooks
    assert len(overlay.SITES) == 7 and len(overlay.HOOK_SYMBOLS) == 7
    parts = [
        overlay.HOOK_ADDRESS,
        overlay.TOP_FIRST,
        overlay.REDIRECTS,
        overlay.LETTER_TILES,
        overlay.NAMES,
        overlay.ARABIC_TEXT,
    ]
    assert parts == sorted(parts)
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.TOP_FIRST
    assert overlay.LETTER_TILES + 52 * 16 <= overlay.NAMES
    assert overlay.NAMES + overlay.NAME_COUNT * overlay.NAME_STRIDE <= 0x209000
    assert lorom_offset(overlay.HOOK_ADDRESS) == overlay.ROM_SIZE
    assert overlay.ARABIC_TEXT_END - overlay.ARABIC_TEXT == 0x8000
    assert overlay.LATIN_TILES == FONT + 0x42 * FONT_TILE_BYTES


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    values = {}
    for name, value in re.findall(r"^(\w+)\s*=\s*(\$?[0-9A-Fa-f]+)", source, re.MULTILINE):
        values[name] = int(value[1:], 16) if value.startswith("$") else int(value)
    return values


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    for name in ("TOP_FIRST", "REDIRECTS", "LETTER_TILES", "NAMES", "ARABIC_TEXT", "LATIN_TILES"):
        assert equates[name] == getattr(overlay, name), name
    assert equates["ROW"] == 26 and equates["ROWS"] == 4
    assert (equates["ISLAND_FIRST"], equates["ISLAND_LAST"]) == (0x21, 0x41)
    assert (equates["DIGIT_FIRST"], equates["DIGIT_LAST"]) == (0x79, 0x89)
    assert equates["NAME_STRIDE"] == overlay.NAME_STRIDE
    assert equates["LETTER_FIRST"] == LETTER_CODES[0] and equates["LETTER_COUNT"] == len(
        LETTER_CODES
    )
    assert equates["REDIRECT_ENTRY"] == overlay.REDIRECT_ENTRY
    # The engine's code the hooks go back to: bytes the overlay pins.
    for name in (
        "DECODE_LOOP",
        "STORE_CONTINUE",
        "DTE_LETTERS",
        "BYTE_MAP",
        "NAME_CHECK",
        "PAGE_CONTINUE",
    ):
        assert equates[name] in overlay.ANCHORS, name
    assert equates["BYTE_EVENT"] == 0x00B2CC and equates["BYTE_RETURN"] == 0x00B2DB
    assert equates["TRANSFER_NONE"] == 0x00B563 and equates["TRANSFER_ENGLISH"] == 0x00B564
    assert equates["TRANSFER_DONE"] == 0x00B5E7
    assert overlay.ANCHORS[0x00B563][:1] == b"\x60"  # the RTS the transfer hook goes back to
    assert overlay.ANCHORS[0x00B563][-3:] == bytes.fromhex("e6ba60")  # INC $BA; RTS
    # The buffers in free work RAM lie apart.
    assert equates["TOP_BUFFER"] == 0x7ED000 and equates["MIRROR_PAGE"] == 0x7ED100
    assert equates["TOP_PAGE"] == 0x7ED180 and equates["PENDING_TOP"] < equates["MIRROR_PAGE"]


@pytest.mark.skipif(shutil.which("ca65") is None, reason="needs cc65")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "final-fantasy-ii"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 6 and report["laid_out"] is False
    assert report["keys"][0] == "deck.arrive" and len(report["names"]) == 14
    assert main(["final-fantasy-ii", "encode-arabic", "بب {Name 00}"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Initial and final beh, the space, the name and its byte, the row's end, the end.
    assert encoded["count"] == 7 and encoded["bytes"].split()[-4:] == ["04", "00", "01", "00"]
    assert "pages" not in encoded


def _writes(result):
    translated = _messages()
    tiles = result.tiles
    encoder = engine.Ff4ArabicEncoder(tiles.codes, tiles)
    encoded = overlay.encode_messages(translated, encoder)
    names = overlay.encode_names(NAMES, encoder)
    writes = {overlay.HOOK_ADDRESS: overlay.HOOK_CODE}
    writes |= overlay.data_writes(translated, encoded, names, tiles)
    return translated, encoded, writes


def test_the_output_is_read_back_before_it_is_accepted(built):
    rom, result = built
    translated, encoded, writes = _writes(result)
    overlay._verify_output(result.rom, rom, writes, translated, encoded)
    redirects = overlay.read_redirects(result.rom)
    assert list(redirects) == [(message.bank, message.offset) for message in translated]
    for message in translated:
        data = overlay.read_arabic_message(result.rom, redirects[message.bank, message.offset])
        assert data == encoded[message.key].data
    a_pair = next(code for code in result.tiles.tiles if code in PAIR_CODES)
    for address, what in (
        (overlay.HOOK_ADDRESS + 3, "hook code"),
        (overlay.SITES[2].address + 1, "site at $00B2BE"),
        (overlay.TOP_FIRST, "first top code"),
        (overlay.REDIRECTS + 2, "list of translated messages"),
        (overlay.LETTER_TILES + 1, "letters' tiles"),
        (overlay.NAMES + 1, "names"),
        (overlay.ARABIC_TEXT + 1, "Arabic text"),
        (FONT + a_pair * FONT_TILE_BYTES + 1, f"font's tile at ${FONT + a_pair * 16:06X}"),
        (
            lorom_address(lorom_offset(BANKS[1].text) + 2),
            f"at {lorom_offset(BANKS[1].text) + 2:#x}, outside the overlay's places",
        ),
    ):
        tampered = bytearray(result.rom)
        tampered[lorom_offset(address)] ^= 0x01
        with pytest.raises(ClassicRetroError) as caught:
            overlay._verify_output(bytes(tampered), rom, writes, translated, encoded)
        assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED, what
        assert what in str(caught.value), what
    # A list that sends a message elsewhere than its Arabic is caught through the reader.
    elsewhere = bytearray(result.rom)
    struct.pack_into("<H", elsewhere, lorom_offset(overlay.REDIRECTS + 3), 0x7000)
    with pytest.raises(ClassicRetroError) as caught:
        overlay._verify_output(bytes(elsewhere), rom, writes, translated, encoded)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_arabic_message(result.rom, 0x7F00)  # 0xFF fill, no end
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_a_translation_keeps_the_originals_commands(font_path):
    """The arrival's English writes the captain's name twice. The build holds each
    translation against the ROM's commands, the check against the pinned ones."""
    rom = _rom()
    arrive = _messages()[0]
    for notation in (
        "الطاقم:وصلنا!",  # the names dropped
        "{Name 00}{Wait 01}:جيد.{line}{Name 00}",  # a wait added
    ):
        with pytest.raises(ClassicRetroError) as caught:
            _build(rom, font_path, translated=(dataclasses.replace(arrive, notation=notation),))
        assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION, notation
    kept = _build(rom, font_path, translated=(arrive,))
    assert kept.report["messages"]["deck.arrive"]["source_skeleton"] == ["{Name 00}", "{Name 00}"]
    # A pinned skeleton is held against the ROM's, at the build and at the extraction.
    pinned = dataclasses.replace(arrive, source_skeleton=("{Name 00}", "{Name 00}"))
    assert _build(rom, font_path, translated=(pinned,)).rom
    wrong = dataclasses.replace(arrive, source_skeleton=("{Wait 01}",))
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, translated=(wrong,))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, translated=(wrong,), verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # Without the ROM, the pinned skeleton is what the translation is held against.
    encoder = engine.Ff4ArabicEncoder(_map_all())
    assert overlay.encode_messages((pinned,), encoder)["deck.arrive"].data.endswith(b"\x00")
    dropped = dataclasses.replace(pinned, notation="الطاقم:وصلنا!")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_messages((dropped,), encoder)
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    assert overlay.extract_skeletons(rom, translated=_messages(), verify_identity=False)[
        "deck.ouch"
    ] == ("{Name 00}", "{Name 00}")


def test_a_name_too_wide_for_its_cells_is_refused(font_path):
    rom = _rom()
    wide = {**NAMES, "name.00": "بببببببب"}
    with pytest.raises(ClassicRetroError) as caught:
        _build(rom, font_path, names=wide)
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    assert engine.LINE == LINE
