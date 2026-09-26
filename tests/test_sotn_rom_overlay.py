from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import re
import shutil
import struct
from functools import cache
from io import BytesIO

import pycdlib
import pytest

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.mips import jal_instruction, jal_target, pair_address
from classic_retro.engines import sotn_arabic as engine
from classic_retro.engines.sotn import (
    WAIT_FOR_SOUND,
    SotnCommand,
    notation_skeleton,
    parse_notation,
    pieces_bytes,
    script_messages,
    split_script,
)
from classic_retro.engines.sotn_arabic import (
    GLYPH_BYTES,
    INK,
    SPACE_WIDTH,
    SotnArabicEncoder,
    SotnFont,
    sotn_glyph,
)
from classic_retro.patching.cdrom import (
    DATA_SIZE,
    SECTOR_SIZE,
    SYNC,
    RawTrack,
    check_form1,
    form1_sector,
    header,
    iso_file,
    sector_count,
    set_file_extent,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import sotn_arabic as overlay
from classic_retro.rom.sotn_arabic_script import (
    NAME_TABLE,
    SCRIPT_ADDRESS,
    SCRIPT_END,
    SotnArabicMessage,
    SotnArabicName,
)

# An invented scene in the place of ST0's script: three messages, two translated.
ENGLISH = {
    "greeting": (0, "{speed 4}Die, fiend.\n{wait 28}Begone!{wait 48}"),
    "reply": (1, "{speed 3}Who are you?\n{wait 4}{flag 10}Leave.{wait 48}"),
    "kept": (0, "{speed 2}So be it.{wait 48}"),
}
ARABIC = {
    "greeting": "{speed 4}مت أيها الوحش.\n{wait 28}ارحل!{wait 48}",
    "reply": "{speed 3}من أنت؟\n{wait 4}{flag 10}ارحل\nالآن.{wait 48}",
}
NAMES = {"name.richter": (0, 0x80181000, "Richter", "ريختر"),
         "name.dracula": (1, 0x80181010, "Dracula", "دراكولا")}  # fmt: skip
# DRA.BIN's entry for ST0 crosses a sector: the overlay rewrites both.
STAGE_ENTRY = DATA_SIZE - 8
GRAPHICS_LBA = 0x1234
FREE = 149


def _command(code: int, *arguments: int) -> bytes:
    return SotnCommand(code, bytes(arguments)).data


def _script() -> tuple[bytes, dict[str, tuple[int, int]]]:
    """The scene: the box opens, then each speaker's portrait, voice and message."""
    script = bytearray(_command(0x07, 0x10, 0x20))
    spans = {}
    for number, (key, (speaker, text)) in enumerate(ENGLISH.items()):
        script += _command(0x05, speaker, speaker) + _command(0x09, 0x06, number)
        script += _command(WAIT_FOR_SOUND)
        start = SCRIPT_ADDRESS + len(script)
        script += pieces_bytes(parse_notation(text))
        spans[key] = (start, SCRIPT_ADDRESS + len(script))
        script += _command(0x06)
    script += _command(0x08)
    return bytes(script).ljust(SCRIPT_END - SCRIPT_ADDRESS, b"\x00"), spans


def _put(st0: bytearray, address: int, data: bytes) -> None:
    start = address - overlay.ST0_BASE
    st0[start : start + len(data)] = data


def _st0(change: dict[int, bytes] | None = None) -> bytes:
    """ST0.BIN: noise, the code the overlay checks, the scene and the names."""
    st0 = bytearray(random.Random(12).randbytes(overlay.ST0_SIZE))
    for site in overlay.SITES:
        _put(st0, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(st0, address, data)
    _put(st0, SCRIPT_ADDRESS, _script()[0])
    for speaker, address, english, _ in NAMES.values():
        _put(st0, NAME_TABLE + 4 * speaker, struct.pack("<I", address))
        _put(st0, address, bytes(ord(letter) - 0x20 for letter in english) + b"\xff\x00")
    for address, data in (change or {}).items():
        _put(st0, address, data)
    return bytes(st0)


def _iso(st0: bytes) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1)
    iso.add_directory("/ST")
    iso.add_directory("/ST/ST0")
    files = {
        "/SYSTEM.CNF;1": b"BOOT = cdrom:\\SLUS_000.67;1\r\n",
        overlay.DRA_PATH: random.Random(13).randbytes(2 * DATA_SIZE),
        overlay.ST0_PATH: st0,
    }
    for path, data in files.items():
        iso.add_fp(BytesIO(data), len(data), path)
    output = BytesIO()
    iso.write_fp(output)
    iso.close()
    return output.getvalue()


def _disc(st0: bytes) -> tuple[bytes, overlay.SotnLayout]:
    """A data track: the file system, ``FREE`` empty sectors and a last one with data."""
    cooked = bytearray(_iso(st0))
    used = len(cooked) // DATA_SIZE
    for offset, order in ((80, "<I"), (84, ">I")):
        struct.pack_into(order, cooked, 16 * DATA_SIZE + offset, used + FREE + 1)
    raw = bytearray()
    for lba in range(used):
        raw += form1_sector(lba, bytes(cooked[lba * DATA_SIZE : (lba + 1) * DATA_SIZE]))
    for lba in range(used, used + FREE):
        raw += SYNC + header(lba) + bytes(SECTOR_SIZE - 16)
    raw += form1_sector(used + FREE, b"\x5a" * DATA_SIZE)
    track = RawTrack(raw)
    st0_record = iso_file(track, overlay.ST0_PATH)
    dra_record = iso_file(track, overlay.DRA_PATH)
    entry = struct.pack("<III", GRAPHICS_LBA, st0_record.lba, st0_record.size)
    track.patch(dra_record.lba, STAGE_ENTRY, entry)
    dra = track.read(dra_record.lba, dra_record.size)
    script = st0[SCRIPT_ADDRESS - overlay.ST0_BASE : SCRIPT_END - overlay.ST0_BASE]
    layout = overlay.SotnLayout(
        st0_lba=st0_record.lba,
        st0_sha256=hashlib.sha256(st0).hexdigest(),
        dra_lba=dra_record.lba,
        dra_sha256=hashlib.sha256(dra).hexdigest(),
        stage_entry=STAGE_ENTRY,
        graphics_lba=GRAPHICS_LBA,
        script_sha256=hashlib.sha256(script).hexdigest(),
        free_lba=used,
        free_sectors=FREE,
    )
    return bytes(raw), layout


@cache
def _synthetic() -> tuple[bytes, overlay.SotnLayout]:
    return _disc(_st0())


def _messages() -> tuple[SotnArabicMessage, ...]:
    spans = _script()[1]
    messages = []
    for index, (key, arabic) in enumerate(ARABIC.items()):
        speaker, english = ENGLISH[key]
        original = parse_notation(english)
        messages.append(
            SotnArabicMessage(
                key=key,
                index=index,
                source_address=spans[key][0],
                source_end=spans[key][1],
                speaker=speaker,
                source_sha256=hashlib.sha256(pieces_bytes(original)).hexdigest(),
                source_skeleton=notation_skeleton(original),
                notation=arabic,
            )
        )
    return tuple(messages)


def _names() -> tuple[SotnArabicName, ...]:
    return tuple(
        SotnArabicName(
            key=key,
            speaker=speaker,
            source_address=address,
            source_sha256=hashlib.sha256(
                bytes(ord(letter) - 0x20 for letter in english) + b"\xff\x00"
            ).hexdigest(),
            text=arabic,
        )
        for key, (speaker, address, english, arabic) in NAMES.items()
    )


def _fake_font(font_path=None, glyph_map: GlyphCodes | None = None, **_kwargs) -> SotnFont:
    """Every glyph a bar 6 pixels wide; the space is the real one."""
    assert glyph_map is not None
    bar = sotn_glyph(dict.fromkeys(((x, y) for x in range(6) for y in range(4, 12)), INK), 6)
    glyphs = {
        codes[0]: sotn_glyph({}, SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return SotnFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


def _build(track: bytes, layout: overlay.SotnLayout, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_sotn_font", _fake_font)
        return overlay.build_sotn_arabic_image(
            track,
            font_path,
            messages=options.pop("messages", _messages()),
            names=options.pop("names", _names()),
            layout=layout,
            verify_identity=options.pop("verify_identity", False),
        )


@pytest.fixture(scope="module")
def font_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("font") / "font.ttf"
    path.write_bytes(b"not read by the fake font")
    return path


@pytest.fixture(scope="module")
def built(font_path):
    track, layout = _synthetic()
    return track, layout, _build(track, layout, font_path)


def _address(st0: bytes, address: int, length: int) -> bytes:
    return st0[address - overlay.ST0_BASE :][:length]


def test_the_build_moves_st0_to_the_free_sectors_and_points_the_game_at_it(built):
    track, layout, result = built
    assert apply_bps(result.patch.data, track) == result.track
    assert len(result.track) == len(track)
    new_st0 = result.st0
    assert len(new_st0) == overlay.FILE_END - overlay.ST0_BASE
    count = sector_count(len(new_st0))
    assert count <= FREE
    output = RawTrack(result.track)
    assert output.read(layout.free_lba, len(new_st0)) == new_st0
    record = iso_file(output, overlay.ST0_PATH)
    assert (record.lba, record.size) == (layout.free_lba, len(new_st0))
    dra = output.read(layout.dra_lba, 2 * DATA_SIZE)
    assert struct.unpack_from("<III", dra, STAGE_ENTRY) == (
        GRAPHICS_LBA,
        layout.free_lba,
        len(new_st0),
    )
    # Only the new file's sectors, the stage entry's two and the record's changed,
    # each a sound sector; the original ST0.BIN stays where it was.
    changed = {
        lba
        for lba in range(len(track) // SECTOR_SIZE)
        if track[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
        != result.track[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
    }
    expected = set(range(layout.free_lba, layout.free_lba + count))
    expected |= {layout.dra_lba, layout.dra_lba + 1, record.record_lba}
    assert changed == expected
    for lba in changed:
        check_form1(output.sector(lba), lba)
    assert output.read(layout.st0_lba, overlay.ST0_SIZE) == _st0()
    assert output.empty(layout.free_lba + count, FREE - count)
    assert result.report["st0_lba"] == layout.free_lba
    assert result.report["st0_original_lba"] == layout.st0_lba


def test_the_new_st0_holds_the_hooks_the_font_the_names_and_the_script(built):
    _, _, result = built
    original, new_st0 = _st0(), result.st0
    # The original's bytes, but the sites.
    sites = {
        offset
        for site in overlay.SITES
        for offset in range(site.address, site.address + len(site.patched))
    }
    for offset, (old, new) in enumerate(zip(original, new_st0[: len(original)], strict=True)):
        assert old == new or overlay.ST0_BASE + offset in sites
    for site in overlay.SITES:
        assert _address(new_st0, site.address, len(site.patched)) == site.patched
    # The two calls the hooks take, and the script the cutscene reads.
    hooks = overlay.HOOKS
    name_call = _address(new_st0, 0x801A9718, 4)
    assert jal_target(0x801A9718, name_call) == hooks.symbol_address("hook_name")
    glyph_call = _address(new_st0, 0x801A9C58, 4)
    assert jal_target(0x801A9C58, glyph_call) == hooks.symbol_address("hook_glyph")
    pointer = _address(new_st0, overlay.SCRIPT_POINTER, 8)
    assert pair_address(pointer) == overlay.ARABIC_SCRIPT_ADDRESS
    code = overlay.HOOK_CODE
    assert _address(new_st0, overlay.HOOK_CODE_ADDRESS, len(code)) == code
    assert _address(new_st0, overlay.WIDTHS_ADDRESS, 128) == result.font.width_table()
    glyphs = result.font.glyph_table()
    assert _address(new_st0, overlay.GLYPHS_ADDRESS, len(glyphs)) == glyphs
    # The line images and the pen start empty.
    images = overlay.FILE_END - overlay.LINE_IMAGE_ADDRESS
    assert _address(new_st0, overlay.LINE_IMAGE_ADDRESS, images) == bytes(images)
    # A name slot a speaker: its glyph count, then its codes in paint order.
    encoder = SotnArabicEncoder(overlay.script_glyph_codes(_messages(), _names()))
    for name in _names():
        codes = encoder.encode_name(name.text).data
        slot = _address(new_st0, overlay.NAMES_ADDRESS + overlay.NAME_SLOT * name.speaker, 16)
        assert slot == bytes((len(codes),)) + codes + bytes(15 - len(codes))
    assert result.report["name_widths"] == {"0": 5 * 6, "1": 7 * 6}


def test_translated_messages_replace_the_originals_in_the_script(built):
    _, _, result = built
    script = _address(result.st0, overlay.ARABIC_SCRIPT_ADDRESS, 0x900)
    script = script[: result.report["arabic_script_bytes"]]
    split_script(script)
    messages = [script[start:end] for start, end in script_messages(script)]
    glyph_map = overlay.script_glyph_codes(_messages(), _names())
    encoder = SotnArabicEncoder(glyph_map, _fake_font(glyph_map=glyph_map))
    translated = [encoder.encode(message.pieces).data for message in _messages()]
    kept = pieces_bytes(parse_notation(ENGLISH["kept"][1]))
    assert messages == [*translated, kept]
    # Everything around the messages is the original script.
    original, spans = _script()
    assert script.startswith(original[: spans["greeting"][0] - SCRIPT_ADDRESS])
    assert script.endswith(original[spans["kept"][0] - SCRIPT_ADDRESS :])
    assert result.report["messages"] == 2 and result.report["names"] == 2
    # Letters and stops 6 pixels wide, spaces 4; no lam-alef ligature.
    assert result.report["message_lines"] == {
        "greeting": [6 * 12 + 2 * SPACE_WIDTH, 6 * 5],
        "reply": [6 * 6 + SPACE_WIDTH, 6 * 4, 6 * 5],
    }


def test_originals_are_extracted_and_verified():
    track, layout = _synthetic()
    originals = overlay.extract_originals(
        track, messages=_messages(), names=_names(), layout=layout, verify_identity=False
    )
    assert originals == {
        "greeting": ENGLISH["greeting"][1],
        "reply": ENGLISH["reply"][1],
        "name.richter": "Richter",
        "name.dracula": "Dracula",
    }


def test_a_different_image_file_or_script_is_refused(font_path):
    track, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    refused = [
        dataclasses.replace(layout, st0_sha256="0" * 64),
        dataclasses.replace(layout, dra_sha256="0" * 64),
        dataclasses.replace(layout, script_sha256="0" * 64),
        dataclasses.replace(layout, st0_lba=layout.st0_lba + 1),
        dataclasses.replace(layout, graphics_lba=GRAPHICS_LBA + 1),
        dataclasses.replace(layout, stage_entry=STAGE_ENTRY + 4),
        dataclasses.replace(layout, stage_entry=2 * DATA_SIZE - 8),
    ]
    for wrong in refused:
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_files(RawTrack(track), wrong)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH, wrong
    message = _messages()[0]
    for changed in (
        dataclasses.replace(message, source_sha256="0" * 64),
        dataclasses.replace(message, source_address=message.source_address + 1),
        dataclasses.replace(message, source_skeleton=("{wait 1}",)),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.extract_originals(
                track, messages=(changed,), names=_names(), layout=layout, verify_identity=False
            )
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    name = _names()[0]
    for changed in (
        dataclasses.replace(name, source_sha256="0" * 64),
        dataclasses.replace(name, speaker=1),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.extract_originals(
                track, messages=_messages(), names=(changed,), layout=layout, verify_identity=False
            )
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_game_code_that_differs_where_the_overlay_works_is_refused():
    for address in (overlay.SITES[0].address, overlay.TEXT_CLUT_TABLE, 0x801A9C1C):
        track, layout = _disc(_st0({address: b"\x00\x00\x00\x00"}))
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_files(RawTrack(track), layout)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
        assert f"{address:#x}" in str(caught.value)


def test_the_free_sectors_must_be_empty_unclaimed_and_inside_the_volume(font_path):
    track, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, dataclasses.replace(layout, free_sectors=144), font_path)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    # The last sector holds data: the free run may not reach it.
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, dataclasses.replace(layout, free_sectors=FREE + 1), font_path)
    assert caught.value.code is ErrorCode.SAFE_REGION_CONTENT_MISMATCH
    claimed = RawTrack(bytearray(track))
    system = iso_file(claimed, "/SYSTEM.CNF;1")
    set_file_extent(claimed, system, layout.free_lba + FREE - 1, 1)
    outside = RawTrack(bytearray(track))
    volume = struct.pack("<I", layout.free_lba + 100) + struct.pack(">I", layout.free_lba + 100)
    outside.patch(16, 80, volume)
    for image, what in ((claimed, "claims"), (outside, "outside the volume")):
        with pytest.raises(ClassicRetroError) as caught:
            _build(bytes(image.image), layout, font_path)
        assert caught.value.code is ErrorCode.SAFE_REGION_CONTENT_MISMATCH
        assert what in str(caught.value)


def test_names_and_lines_must_fit(font_path):
    track, layout = _synthetic()
    long_name = dataclasses.replace(_names()[0], text="ب" * 29)
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, names=(long_name, _names()[1]))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW
    # 86 pixels, but 17 codes: a slot holds a count and 15.
    crowded = dataclasses.replace(_names()[0], text=" ".join("ب" * 9))
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, names=(crowded, _names()[1]))
    assert caught.value.code is ErrorCode.TEXT_OVERFLOW
    wide = dataclasses.replace(
        _messages()[0], notation=ARABIC["greeting"].replace("ارحل", "ب" * 29)
    )
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, messages=(wide,))
    assert caught.value.code is ErrorCode.TEXT_BOX_OVERFLOW


def test_the_hooks_may_only_call_the_game_routines_they_name(monkeypatch):
    track, layout = _synthetic()
    code = bytearray(overlay.HOOK_CODE)
    end = overlay.HOOK_CODE_ADDRESS + len(code)
    code[-4:] = jal_instruction(end - 4, 0x80010000)
    monkeypatch.setattr(overlay, "HOOK_CODE", bytes(code))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_files(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_the_sites_and_anchors_lie_apart_inside_st0():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched) and site.original != site.patched
    assert spans[0][0] >= overlay.ST0_BASE
    assert spans[-1][1] == overlay.ST0_BASE + overlay.ST0_SIZE
    # The overlay's part: the hooks, the widths, the names, the script, the glyphs
    # (a code from 0x80 to 0xFF each) and the two line images, then the pen.
    regions = [
        overlay.HOOK_CODE_ADDRESS,
        overlay.WIDTHS_ADDRESS,
        overlay.NAMES_ADDRESS,
        overlay.ARABIC_SCRIPT_ADDRESS,
        overlay.GLYPHS_ADDRESS,
        overlay.LINE_IMAGE_ADDRESS,
        overlay.NAME_IMAGE_ADDRESS,
        overlay.PEN_ADDRESS,
    ]
    assert regions == sorted(regions) and overlay.ST0_BASE + overlay.ST0_SIZE <= regions[0]
    assert overlay.HOOK_CODE_ADDRESS + len(overlay.HOOK_CODE) <= overlay.WIDTHS_ADDRESS
    assert overlay.WIDTHS_ADDRESS + 128 <= overlay.NAMES_ADDRESS
    assert (
        overlay.NAMES_ADDRESS + overlay.NAME_SLOT * overlay.NAME_SLOTS
        <= overlay.ARABIC_SCRIPT_ADDRESS
    )
    assert (
        overlay.GLYPHS_END
        == overlay.GLYPHS_ADDRESS + 128 * GLYPH_BYTES
        <= overlay.LINE_IMAGE_ADDRESS
    )
    assert overlay.LINE_IMAGE_ADDRESS + overlay.LINE_IMAGE_BYTES <= overlay.NAME_IMAGE_ADDRESS
    assert overlay.NAME_IMAGE_ADDRESS + overlay.LINE_IMAGE_BYTES <= overlay.PEN_ADDRESS
    assert sector_count(overlay.FILE_END - overlay.ST0_BASE) <= overlay.USA_LAYOUT.free_sectors


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    return {
        name: int(value, 0)
        for name, value in re.findall(r"^\s*\.equ\s+(\w+),\s*(\S+)", source, re.MULTILINE)
    }


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    equates = _equates()
    assert {
        "WIDTHS": overlay.WIDTHS_ADDRESS,
        "NAMES": overlay.NAMES_ADDRESS,
        "GLYPHS": overlay.GLYPHS_ADDRESS,
        "LINE_IMAGE": overlay.LINE_IMAGE_ADDRESS,
        "NAME_IMAGE": overlay.NAME_IMAGE_ADDRESS,
        "PEN": overlay.PEN_ADDRESS,
        "DIALOGUE": overlay.DIALOGUE,
        "MOVE_IMAGE": overlay.MOVE_IMAGE,
        "LOAD_IMAGE": overlay.LOAD_IMAGE,
        "ALLOC_PRIMITIVES": overlay.ALLOC_PRIMITIVES,
        "PRIM_BUF": overlay.PRIM_BUF,
        "DESTROY_ENTITY": overlay.DESTROY_ENTITY,
        "TEXT_CLUT": overlay.TEXT_CLUT,
        "ARABIC_FIRST": engine.ARABIC_CODES[0],
        "LINE_RIGHT": engine.LINE_RIGHT,
        "ROWS": engine.GLYPH_ROWS,
        "ROW_BYTES": engine.LINE_PIXELS // 2,
        "LINE_HALFWORDS": engine.LINE_PIXELS // 4,
        "LINE_BYTES": overlay.LINE_IMAGE_BYTES,
    }.items() <= equates.items()
    assert equates["LINE_BYTES"] == equates["ROW_BYTES"] * equates["ROWS"]


@pytest.mark.skipif(shutil.which("mipsel-linux-gnu-as") is None, reason="needs GNU MIPS binutils")
def test_the_stored_hooks_match_their_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "sotn"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 6 and report["names"] == 2
    assert report["lines_measured"] is False
    assert main(["sotn", "encode-arabic", "بب ب{wait 4}."]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Three letters and a space, the wait (two bytes) and the stop.
    assert encoded["count"] == 4 + 2 + 1 and "widths" not in encoded
    assert encoded["bytes"].split()[-3:-1] == ["03", "04"]
