from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import struct
from functools import cache
from io import BytesIO

import pycdlib
import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.mips import jal_instruction, jump_targets
from classic_retro.engines import ridge_racer_arabic as engine
from classic_retro.engines.ridge_racer import string_notation
from classic_retro.engines.ridge_racer_arabic import (
    ATLAS_TPAGE,
    INK,
    LARGE,
    OUTLINE,
    SMALL,
    Atlas,
    RrFont,
    RrGlyph,
    visual_text,
)
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.patching.cdrom import (
    DATA_SIZE,
    SECTOR_SIZE,
    RawTrack,
    check_form1,
    form1_sector,
    iso_file,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import ridge_racer_arabic as overlay
from classic_retro.rom import ridge_racer_arabic_script as script
from classic_retro.rom.ridge_racer_arabic_script import RidgeRacerString

LOAD = overlay.LOAD_ADDRESS
PROGRAM_END = 0x8006B800
# Invented English in the rooms of the three strings, and the Arabic for them.
ENGLISH = {
    "title.start": "PRESS THE BUTTON",
    "menu.exit_pad": "a OR b TO GO BACK",
    "card.load_title": "LOAD FROM A CARD",
}
ARABIC = {
    "title.start": "ابدأ الآن",
    "menu.exit_pad": "△ أو □ رجوع",
    "card.load_title": "تحميل",
}


def _put(text: bytearray, address: int, data: bytes) -> None:
    text[address - LOAD : address - LOAD + len(data)] = data


def _program(change: dict[int, bytes] | None = None) -> bytes:
    """SCUS-943.00: zeros but the words the overlay checks and the three strings."""
    text = bytearray(PROGRAM_END - LOAD)
    for site in overlay.SITES:
        _put(text, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(text, address, data)
    for calls in overlay.CALLS.values():
        for address, words in calls.items():
            _put(text, address, words)
    for key, english in ENGLISH.items():
        _put(text, script._SOURCES[key][0], english.encode())
    for address, data in (change or {}).items():
        _put(text, address, data)
    header = bytearray(overlay.HEADER)
    header[:8] = overlay.EXE_MAGIC
    struct.pack_into("<IIII", header, 0x10, 0x80040000, 0, LOAD, len(text))
    return bytes(header + text)


def _iso(files: dict[str, bytes]) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=4)
    for path, data in files.items():
        iso.add_fp(BytesIO(data), len(data), path)
    output = BytesIO()
    iso.write_fp(output)
    iso.close()
    return output.getvalue()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _disc(program: bytes | None = None) -> tuple[bytes, overlay.RidgeRacerLayout]:
    """A data track with the program, and the layout that pins it."""
    program = program or _program()
    path = overlay.USA_LAYOUT.path
    cooked = _iso({"/SYSTEM.CNF;1": b"BOOT = cdrom:\\SCUS_943.00;1\r\n", path: program})
    raw = b"".join(
        form1_sector(lba, cooked[lba * DATA_SIZE : (lba + 1) * DATA_SIZE])
        for lba in range(len(cooked) // DATA_SIZE)
    )
    record = iso_file(RawTrack(raw), path)
    return raw, overlay.RidgeRacerLayout(path, record.lba, record.size, _digest(program))


@cache
def _synthetic() -> tuple[bytes, overlay.RidgeRacerLayout]:
    return _disc()


def _entries(program: bytes | None = None) -> tuple[RidgeRacerString, ...]:
    program = program or _program()
    entries = []
    for key, (address, room, *place, _) in script._SOURCES.items():
        at = overlay.HEADER + address - LOAD
        digest = _digest(program[at : at + room])
        entries.append(RidgeRacerString(key, address, room, *place, digest, ARABIC[key]))
    return tuple(entries)


def _fake_fonts(font_path=None, glyph_map=None, *, small, large, **_kwargs):
    """Every glyph a bar: 6 wide and 8 rows in the small font, 10 and 16 in the large."""
    assert glyph_map is not None
    fonts = {}
    for name, used, bar in (
        (SMALL, small, RrGlyph(6, -1, ((INK,) * 6,) * 8)),
        (LARGE, large, RrGlyph(10, -2, ((OUTLINE,) + (0xC,) * 8 + (OUTLINE,),) * 16)),
    ):
        glyphs = {
            glyph_map.code(character): RrGlyph(4, 0, ()) if character == " " else bar
            for character in used
        }
        fonts[name] = RrFont(name, glyphs, 11 if name == SMALL else 18)
    return fonts


def _build(track: bytes, layout: overlay.RidgeRacerLayout, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_ridge_racer_fonts", _fake_fonts)
        return overlay.build_ridge_racer_arabic_image(
            track,
            font_path,
            entries=options.pop("entries", _entries()),
            layout=layout,
            verify_identity=options.pop("verify_identity", False),
        )


@pytest.fixture(scope="module")
def font_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("font") / "font.ttf"
    path.write_bytes(b"not read by the fake fonts")
    return path


@pytest.fixture(scope="module")
def built(font_path):
    track, layout = _synthetic()
    return track, layout, _build(track, layout, font_path)


def _read(program: bytes, address: int, length: int) -> bytes:
    at = overlay.HEADER + address - LOAD
    return program[at : at + length]


def test_the_build_rewrites_the_program_in_its_own_sectors(built):
    track, layout, result = built
    changed = {
        lba
        for lba in range(len(track) // SECTOR_SIZE)
        if track[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
        != result.track[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
    }
    sectors = -(-layout.size // DATA_SIZE)
    assert changed and all(layout.lba <= lba < layout.lba + sectors for lba in changed)
    for lba in changed:
        check_form1(result.track[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE], lba)
    assert RawTrack(result.track).read(layout.lba, layout.size) == result.program
    assert len(result.track) == len(track)
    assert apply_bps(result.patch.data, track) == result.track
    report = result.report
    assert report["changed_sectors"] == len(changed)
    assert report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert set(report["strings"]) == set(ENGLISH)


def test_the_program_gets_the_jumps_the_hook_and_its_data(built):
    _, _, result = built
    program = result.program
    for site in overlay.SITES:
        assert _read(program, site.address, len(site.patched)) == site.patched
    assert _read(program, overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    atlas = engine.build_atlas(result.fonts)
    data = overlay.hook_data(atlas)
    assert _read(program, overlay.DATA_ADDRESS, len(data)) == data
    assert _read(program, overlay.UPLOADED, 4) == bytes(4)
    assert struct.unpack("<4h", _read(program, overlay.RECT, 8)) == (976, 192, 48, atlas.rows)
    for name in (SMALL, LARGE):
        table, slot, tpage, cell, cycles = struct.unpack(
            "<IhHBB", _read(program, overlay.DESCRIPTORS[name], 10)
        )
        assert (table, slot, tpage) == (overlay.TABLES[name], overlay.ORDER_SLOTS[name], 15)
        assert (cell, cycles) == ((8, 0) if name == SMALL else (16, 1))
        assert _read(program, table, engine.TABLE_BYTES) == atlas.tables[name]
    assert _read(program, overlay.PIXELS, len(atlas.pixels)) == atlas.pixels
    end = overlay.DATA_ADDRESS + len(data)
    assert not any(_read(program, end, overlay.FREE_END - end))
    assert ATLAS_TPAGE == 15


def test_the_translated_strings_replace_the_originals_in_their_rooms(built):
    _, _, result = built
    for entry in _entries():
        room = _read(result.program, entry.address, entry.room)
        assert room[:2] == bytes((entry.mode, entry.parameter))
        text = room[2:].split(b"\x00")[0]
        assert room[2 + len(text) :] == bytes(entry.room - 2 - len(text))
        assert len(text) == len(visual_text(entry.notation))
        assert result.report["strings"][entry.key]["bytes"] == len(text) + 3


def test_originals_are_extracted_and_verified():
    track, layout = _synthetic()
    originals = overlay.extract_originals(
        track, entries=_entries(), layout=layout, verify_identity=False
    )
    assert originals == {key: string_notation(english.encode()) for key, english in ENGLISH.items()}
    assert originals["menu.exit_pad"].startswith("△ OR □")


def test_a_different_track_program_or_string_is_refused(font_path):
    track, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    for wrong in (
        dataclasses.replace(layout, sha256="0" * 64),
        dataclasses.replace(layout, lba=layout.lba + 1),
        dataclasses.replace(layout, size=layout.size - 4),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_program(RawTrack(track), wrong)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH, wrong
    first = _entries()[0]
    for changed in (
        dataclasses.replace(first, source_sha256="0" * 64),
        dataclasses.replace(first, room=24),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.extract_originals(
                track, entries=(changed,), layout=layout, verify_identity=False
            )
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    stray = dataclasses.replace(first, key="title.other")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(track, entries=(stray,), layout=layout, verify_identity=False)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


@pytest.mark.parametrize(
    "change",
    [
        {overlay.SMALL_ROUTINE + 8: b"\x00" * 4},  # an anchor
        {overlay.LARGE_ROUTINE: b"\x01\x00\x00\x00"},  # a site
        {0x8001C9E8: b"\x61\x00\x04\x34"},  # a call draws the title's string elsewhere
        {0x80011120: b"LoadImagf"},  # not LoadImage
        {overlay.FREE_END - 4: b"\x01"},  # the hook's room is not empty
    ],
)
def test_program_code_that_differs_where_the_overlay_works_is_refused(change):
    track, layout = _disc(_program(change))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_program(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_program_that_is_not_the_pinned_exe_is_refused():
    program = bytearray(_program())
    program[:8] = b"PS-X EXF"
    track, layout = _disc(bytes(program))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_program(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_the_hook_may_only_call_the_routines_it_names(monkeypatch):
    track, layout = _synthetic()
    code = bytearray(overlay.HOOK_CODE)
    end = overlay.HOOK_ADDRESS + len(code)
    code[-4:] = jal_instruction(end - 4, 0x80010000)
    monkeypatch.setattr(overlay, "HOOK_CODE", bytes(code))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_program(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_a_string_keeps_to_its_room(font_path):
    track, layout = _synthetic()
    long = dataclasses.replace(_entries()[2], notation="تحميل من بطاقة الذاكرة")
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, entries=(long,))
    assert caught.value.code is ErrorCode.TEXT_OVERFLOW


def test_the_glyphs_keep_to_the_room_after_the_hook():
    room = overlay.FREE_END - overlay.PIXELS
    tables = {name: bytes(engine.TABLE_BYTES) for name in (SMALL, LARGE)}
    fits = overlay.hook_data(Atlas(bytes(room), 1, tables, {}))
    assert len(fits) == overlay.FREE_END - overlay.DATA_ADDRESS
    with pytest.raises(ClassicRetroError) as caught:
        overlay.hook_data(Atlas(bytes(room + 1), 1, tables, {}))
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED


def test_the_check_puts_the_glyphs_in_the_room_after_the_hook(font_path, monkeypatch):
    # The fullest atlas fits the room, so the atlas's own limit (the same error) comes first.
    assert engine.ATLAS_ROWS * engine.ATLAS_ROW_BYTES <= overlay.FREE_END - overlay.PIXELS
    monkeypatch.setattr(overlay, "build_ridge_racer_fonts", _fake_fonts)
    report = overlay.check_ridge_racer_translations(font_path)
    rows = report["atlas_rows"]
    monkeypatch.setattr(overlay, "FREE_END", overlay.PIXELS + rows * engine.ATLAS_ROW_BYTES - 1)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.check_ridge_racer_translations(font_path)
    assert caught.value.code is ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED
    assert "the room holds" in str(caught.value)


def _shipped_with(texts: dict[str, str]) -> TranslationSet:
    """The shipped translations with ``texts`` in place of theirs."""
    shipped = builtin_translation_set("ridge-racer")
    entries = tuple(
        dataclasses.replace(entry, text=texts.get(entry.id, entry.text))
        for entry in shipped.entries
    )
    return dataclasses.replace(shipped, entries=entries)


@pytest.mark.parametrize("character", ["△", "□", "Ⅱ", "○"])
def test_the_check_keeps_the_buttons_to_the_small_font_without_a_font(character):
    # The large font's string may not use what only the small font draws.
    with pytest.raises(ClassicRetroError) as caught:
        overlay.check_ridge_racer_translations(
            translations=_shipped_with({"card.load_title": f"تحميل {character}"})
        )
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    assert "(large font)" in str(caught.value)
    report = overlay.check_ridge_racer_translations(
        translations=_shipped_with({"title.start": f"ابدأ {character}"})
    )
    assert report["measured"] is False


def test_the_sites_anchors_and_calls_lie_apart_and_off_the_hook():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
        + [
            (address, address + len(words))
            for calls in overlay.CALLS.values()
            for address, words in calls.items()
        ]
        + [(overlay.HOOK_ADDRESS, overlay.FREE_END)]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched) and site.original != site.patched
    assert overlay.HOOK_ADDRESS + len(overlay.HOOK_CODE) <= overlay.DATA_ADDRESS
    assert overlay.DATA_ADDRESS + 36 <= min(overlay.TABLES.values())
    assert max(overlay.TABLES.values()) + engine.TABLE_BYTES <= overlay.PIXELS
    # Each entry's jump lands on its entry; the hook goes back into each routine.
    small, large = (jump_targets(site.address, site.patched) for site in overlay.SITES)
    assert list(small.values()) == [overlay.HOOKS.symbol_address("small_entry")]
    assert list(large.values()) == [overlay.HOOKS.symbol_address("large_entry")]
    assert {overlay.SMALL_ROUTINE + 8, overlay.LARGE_ROUTINE + 8} <= overlay.HOOK_CALLS


def _immediates(words: bytes, opcode: int, register: int) -> list[int]:
    values = []
    for (word,) in struct.iter_unpack("<I", words):
        if word >> 26 == opcode and word >> 16 & 31 == register:
            values.append(word & 0xFFFF)
    return values


def test_the_calls_draw_each_string_where_the_entry_says():
    routines = {SMALL: overlay.SMALL_ROUTINE, LARGE: overlay.LARGE_ROUTINE}
    for entry in script.ridge_racer_arabic_strings():
        words = b"".join(overlay.CALLS[entry.key].values())
        xs = _immediates(words, 0x0D, 4)  # ori a0, zero, x
        ys = _immediates(words, 0x0D, 5)
        assert xs[0] == entry.x and ys[0] == entry.y, entry.key
        highs = _immediates(words, 0x0F, 6)  # lui a2
        lows = _immediates(words, 0x09, 6)  # addiu a2, a2
        assert {high << 16 | low for high, low in zip(highs, lows, strict=True)} == {entry.address}
        targets = {
            target
            for address, words in overlay.CALLS[entry.key].items()
            for target in jump_targets(address, words).values()
        }
        assert targets == {routines[entry.font]}, entry.key
    # The help line's shadow: a pixel right and down.
    words = b"".join(overlay.CALLS["menu.exit_pad"].values())
    assert _immediates(words, 0x0D, 4) == [0x58, 0x59]
    assert _immediates(words, 0x0D, 5) == [0xD0, 0xD1]


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for name, expression in re.findall(r"^\s*\.equ\s+(\w+),\s*([^#\n]+)", source, re.MULTILINE):
        terms = [term.strip() for term in expression.split("+")]
        values[name] = sum(values[term] if term in values else int(term, 0) for term in terms)
    return values


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    assert {
        name: equates[name]
        for name in (
            "SMALL_ROUTINE",
            "LARGE_ROUTINE",
            "LOAD_IMAGE",
            "DRAW_SYNC",
            "ADD_PRIM",
            "SET_DRAW_MODE",
            "DATA",
            "UPLOADED",
            "RECT",
            "SMALL_FONT",
            "LARGE_FONT",
            "PIXELS",
        )
    } == {
        "SMALL_ROUTINE": overlay.SMALL_ROUTINE,
        "LARGE_ROUTINE": overlay.LARGE_ROUTINE,
        "LOAD_IMAGE": overlay.LOAD_IMAGE,
        "DRAW_SYNC": overlay.DRAW_SYNC,
        "ADD_PRIM": overlay.ADD_PRIM,
        "SET_DRAW_MODE": overlay.SET_DRAW_MODE,
        "DATA": overlay.DATA_ADDRESS,
        "UPLOADED": overlay.UPLOADED,
        "RECT": overlay.RECT,
        "SMALL_FONT": overlay.DESCRIPTORS[SMALL],
        "LARGE_FONT": overlay.DESCRIPTORS[LARGE],
        "PIXELS": overlay.PIXELS,
    }
    assert (equates["CENTRE"], equates["MIRROR"]) == (engine.CENTRE, engine.MIRROR)
    assert (equates["MIRROR_BIAS"], equates["SCREEN_WIDTH"]) == (
        engine.MIRROR_BIAS,
        engine.SCREEN_WIDTH,
    )
    assert (equates["GLYPH_BYTES"], equates["FIRST_CODE"]) == (
        engine.GLYPH_ENTRY,
        engine.ARABIC_CODES[0],
    )
    assert (equates["FONT_TABLE"], equates["FONT_SLOT"], equates["FONT_TPAGE"]) == (0, 4, 6)
    assert (equates["FONT_CELL"], equates["FONT_CYCLES"]) == (8, 9)
    assert overlay.HOOK_ADDRESS == 0x80068A00


@pytest.mark.skipif(shutil.which("mipsel-linux-gnu-as") is None, reason="needs GNU MIPS binutils")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "ridge-racer"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["strings"] == 3 and report["measured"] is False
    assert report["keys"] == ["title.start", "menu.exit_pad", "card.load_title"]
    assert all(size <= 20 for size in report["encoded_bytes"].values())
    assert main(["ridge-racer", "encode-arabic", "بب ب"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Visual order: beh alone, the space, the final and the initial; header and zero.
    assert (encoded["count"], encoded["bytes"]) == (4, 7)
    assert encoded["glyphs"].split()[1] == "20" and "width" not in encoded
    with pytest.raises(ClassicRetroError) as caught:
        overlay.encode_ridge_racer_arabic_string("ب", "medium")
    assert caught.value.code is ErrorCode.INVALID_REFERENCE
