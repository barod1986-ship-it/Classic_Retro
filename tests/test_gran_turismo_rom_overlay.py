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

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.mips import address_pair, jal_instruction, jal_target
from classic_retro.engines import gran_turismo_arabic as engine
from classic_retro.engines.gran_turismo import (
    BRIEFINGS,
    GT_ARC_MAGIC,
    LICENSE_FILE,
    Briefing,
    briefing_bytes,
    gt_arc_file,
    join_briefings,
    parse_briefing,
    parse_notation,
    read_gt_arc,
    split_briefings,
)
from classic_retro.engines.gran_turismo_arabic import (
    BODY,
    INK,
    PAGE_ROWS,
    ROW_BYTES,
    TITLE,
    TITLE_SPACE,
    GranTurismoArabicEncoder,
    GtFont,
    GtGlyph,
)
from classic_retro.patching.cdrom import (
    DATA_SIZE,
    SECTOR_SIZE,
    RawTrack,
    check_form1,
    form1_sector,
    iso_file,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rebuild.gtzip import (
    MAX_MATCH,
    MIN_MATCH,
    compress_gtzip,
    decompress_gtzip,
    item_size,
    write_items,
)
from classic_retro.rebuild.pslz import EXE_HEADER, read_pslz, unpack_pslz, unpacks_in_place
from classic_retro.rom import gran_turismo_arabic as overlay
from classic_retro.rom.gran_turismo_arabic_script import GranTurismoBriefing

LOAD = 0x80010000
IMAGE_END = 0x800A7800
ZERO_ROW = 0x800A7700
KERNED_ROW = 0x800A7780
# Invented briefings in the place of the game's 24, and three translated.
ENGLISH = [f"Test {n + 1}\nDrive {n + 1} laps and stop.\nThe car is fast." for n in range(24)]
ARABIC = {
    "license.b1": (0, "اختبار 1\nانطلق ثم توقف.\nالسيارة سريعة."),
    "license.b3": (2, "منعطف\nانعطف يمينا."),
    "license.b8": (7, "النهائي\nلفة واحدة و22 ثانية."),
}
# The page's glyphs: (font, first code, count, width, height, u, v); the rest blank.
RECTS = (
    (0, 0x41, 26, 6, 7, 0, 8),
    (1, 0x41, 26, 8, 9, 0, 16),
    (2, 0x41, 21, 12, 15, 0, 26),
    (2, 0x56, 5, 12, 15, 0, 41),
    (1, 0x86, 32, 8, 16, 0, 60),
    (2, 0x86, 21, 12, 24, 0, 80),
    (2, 0x9B, 11, 12, 24, 0, 104),
)


def _english(index: int) -> bytes:
    title, paragraphs = parse_notation(ENGLISH[index])
    words = tuple(tuple(word.encode() for word in paragraph) for paragraph in paragraphs)
    text = briefing_bytes(Briefing(title.encode(), words))
    return text + bytes(len(text) % 2)


def _set_pixel(page: bytearray, x: int, y: int, low: int) -> None:
    at = y * ROW_BYTES + x // 2
    shift = 4 * (x % 2)
    page[at] = page[at] & ~(0x3 << shift) & 0xFF | low << shift


@cache
def _page() -> bytes:
    """Font 3's plane (the high bits) a pattern everywhere; glyphs, palettes and the HUD in
    the low one."""
    rng = random.Random(21)
    page = bytearray(PAGE_ROWS * ROW_BYTES)
    for y in range(PAGE_ROWS):
        for x in range(0, 256, 2):
            page[y * ROW_BYTES + x // 2] = ((x // 16 + y) % 4) << 2 | ((x // 16 + y + 1) % 4) << 6
    for _, _, count, width, height, u0, v0 in RECTS:
        for k in range(count):
            for y in range(v0 + 1, v0 + height - 1):
                for x in range(u0 + k * width + 1, u0 + (k + 1) * width - 1):
                    _set_pixel(page, x, y, rng.choice((0, 2, 3)))
    for y in range(4):
        for x in range(64):
            _set_pixel(page, x, y, 1)
    for y in range(231, 256):
        for x in range(256):
            _set_pixel(page, x, y, 2)
    return bytes(page)


def _put(image: bytearray, address: int, data: bytes) -> None:
    image[address - LOAD : address - LOAD + len(data)] = data


def _image(change: dict[int, bytes] | None = None) -> bytes:
    """The race program: zeros but the word loop, the words the overlay checks, the font
    select's table addresses, the glyph and kerning tables and two kerning rows."""
    image = bytearray(IMAGE_END - LOAD)
    loop = random.Random(22).randbytes(overlay.HOOK_END - overlay.HOOK_ADDRESS)
    _put(image, overlay.HOOK_ADDRESS, loop)
    for site in overlay.SITES:
        _put(image, site.address, site.original)
    for address, data in overlay.ANCHORS.items():
        _put(image, address, data)
    for font, at in overlay.FONT_SELECT.items():
        _put(image, at, address_pair("a2", overlay.FONT_TABLES[font]))
        _put(image, at + 8, address_pair("a1", overlay.KERN_TABLES[font]))
    for font, first, count, width, height, u0, v0 in RECTS:
        for k in range(count):
            entry = bytes((u0 + k * width, v0, width, height, 0, 4, width - 1, height))
            _put(image, overlay.FONT_TABLES[font] + 8 * (first + k), entry)
    _put(image, KERNED_ROW, b"\x11" * 128)
    for table in overlay.KERN_TABLES.values():
        for code in range(256):
            row = ZERO_ROW if code == overlay.SPACE else KERNED_ROW
            _put(image, table + 4 * code, struct.pack("<I", row))
    for address, data in (change or {}).items():
        _put(image, address, data)
    return bytes(image)


def _greedy(data: bytes) -> list[tuple[int, int, int]]:
    """A packer cruder than the game's: runs of a byte as matches one back, the rest literal."""
    items: list[tuple[int, int, int]] = []
    position = 0
    while position < len(data):
        run = 0
        if position:
            limit = min(MAX_MATCH, len(data) - position)
            while run < limit and data[position + run] == data[position - 1]:
                run += 1
        if run >= MIN_MATCH:
            items.append((run, 1, 1))
            position += run
        else:
            items.append((1, 0, data[position]))
            position += 1
    return items


def _exe(image: bytes) -> bytes:
    """GTMAIN.EXE: the image packed with PSLZ, the stream ending where the saving peaks."""
    items = _greedy(image[::-1])
    saved, total = [], 0
    for number, item in enumerate(items):
        total += item[0] - item_size(item) - (1 if number % 8 == 0 else 0)
        saved.append(total)
    kept = items[: saved.index(max(saved)) + 1]
    assert unpacks_in_place(kept)
    stored = len(image) - sum(length for length, _, _ in kept)
    stream = write_items(kept)[::-1]
    stub = bytes(range(0x40))
    text = bytearray(image[:stored] + stream)
    text += bytes(-len(text) % 4)
    header = LOAD + len(text)
    text += struct.pack(
        "<4s6I", b"PSLZ", LOAD + len(image) - 1, len(image), LOAD + stored + len(stream) - 1,
        LOAD + len(image), len(stub), LOAD,
    )  # fmt: skip
    text += stub + bytes(-(len(text) + len(stub)) % 0x800)
    exe = bytearray(EXE_HEADER)
    exe[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", exe, 0x10, header + 0x1C, 0, LOAD, len(text))
    return bytes(exe + text)


def _messages(room: int = 0x1000, change: dict[int, bytes] | None = None) -> bytes:
    """MESSAGES.DAT: 24 files, the 18th the license file."""
    texts = [_english(index) for index in range(BRIEFINGS)]
    for index, text in (change or {}).items():
        texts[index] = text
    files = [f"file {index}".encode() for index in range(24)]
    files[LICENSE_FILE] = join_briefings(texts)
    table = 16 + 12 * len(files)
    data = bytearray(GT_ARC_MAGIC + struct.pack("<HH", 1, len(files)))
    data += bytes(-(-table // room) * room - len(data))
    for index, content in enumerate(files):
        struct.pack_into("<III", data, 16 + 12 * index, len(data), len(content), len(content))
        data += content + bytes(-len(content) % room)
    return bytes(data)


def _iso(files: dict[str, bytes]) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1)
    for path, data in files.items():
        iso.add_fp(BytesIO(data), len(data), path)
    output = BytesIO()
    iso.write_fp(output)
    iso.close()
    return output.getvalue()


def _disc(
    image: bytes | None = None, page: bytes | None = None, messages: bytes | None = None
) -> tuple[bytes, overlay.GranTurismoLayout]:
    """A data track with the three files, and the layout that pins them."""
    image = image or _image()
    page = page or _page()
    files = {
        "/SYSTEM.CNF;1": b"BOOT = cdrom:\\SCUS_941.94;1\r\n",
        overlay.USA_LAYOUT.gtmain.path: _exe(image),
        overlay.USA_LAYOUT.gamefont.path: write_items(_greedy(page)),
        overlay.USA_LAYOUT.messages.path: messages or _messages(),
    }
    cooked = _iso(files)
    raw = b"".join(
        form1_sector(lba, cooked[lba * DATA_SIZE : (lba + 1) * DATA_SIZE])
        for lba in range(len(cooked) // DATA_SIZE)
    )
    track = RawTrack(raw)

    def spec(pinned: overlay.GtFile) -> overlay.GtFile:
        record = iso_file(track, pinned.path)
        data = files[pinned.path]
        return overlay.GtFile(pinned.path, record.lba, record.size, _digest(data))

    loop = image[overlay.HOOK_ADDRESS - LOAD : overlay.HOOK_END - LOAD]
    layout = overlay.GranTurismoLayout(
        gtmain=spec(overlay.USA_LAYOUT.gtmain),
        gamefont=spec(overlay.USA_LAYOUT.gamefont),
        messages=spec(overlay.USA_LAYOUT.messages),
        image_sha256=_digest(image),
        page_sha256=_digest(page),
        word_loop_sha256=_digest(loop),
    )
    return raw, layout


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@cache
def _synthetic() -> tuple[bytes, overlay.GranTurismoLayout]:
    return _disc()


def _briefings() -> tuple[GranTurismoBriefing, ...]:
    return tuple(
        GranTurismoBriefing(key, index, _digest(_english(index)), notation)
        for key, (index, notation) in ARABIC.items()
    )


def _fake_fonts(font_path=None, glyph_map=None, *, body, title, **_kwargs) -> dict[int, GtFont]:
    """Every glyph a bar: 6 wide and 10 rows in the body, 8 and 18 in the title."""
    assert glyph_map is not None
    fonts = {}
    for index, used, bar in (
        (BODY, body, GtGlyph(6, 2, ((INK,) * 6,) * 10)),
        (TITLE, title, GtGlyph(8, 3, ((INK,) * 8,) * 18)),
    ):
        glyphs = {
            glyph_map.code(character): GtGlyph(TITLE_SPACE, 0, ()) if character == " " else bar
            for character in used
        }
        fonts[index] = GtFont(index, glyphs, 10 if index == BODY else 18)
    return fonts


def _build(track: bytes, layout: overlay.GranTurismoLayout, font_path, **options):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(overlay, "build_gran_turismo_fonts", _fake_fonts)
        return overlay.build_gran_turismo_arabic_image(
            track,
            font_path,
            briefings=options.pop("briefings", _briefings()),
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


def _sectors(first: bytes, second: bytes) -> set[int]:
    return {
        lba
        for lba in range(len(first) // SECTOR_SIZE)
        if first[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
        != second[lba * SECTOR_SIZE : (lba + 1) * SECTOR_SIZE]
    }


def test_the_build_rewrites_the_three_files_in_their_own_sectors(built):
    track, layout, result = built
    assert apply_bps(result.patch.data, track) == result.track
    assert len(result.track) == len(track)
    output = RawTrack(result.track)
    extents = set()
    for spec, data in (
        (layout.gtmain, result.gtmain),
        (layout.gamefont, result.gamefont),
        (layout.messages, result.messages),
    ):
        record = iso_file(output, spec.path)
        assert (record.lba, record.size) == (spec.lba, spec.size) == (spec.lba, len(data))
        assert output.read(record.lba, record.size) == data
        extents |= set(range(record.lba, record.lba + record.sectors))
    changed = _sectors(track, result.track)
    assert changed and changed <= extents
    for lba in changed:
        check_form1(output.sector(lba), lba)
    report = result.report
    assert report["changed_sectors"] == {
        name: len({lba for lba in changed if spec.lba <= lba < spec.lba + -(-spec.size // 2048)})
        for name, spec in (
            ("gtmain", layout.gtmain),
            ("gamefont", layout.gamefont),
            ("messages", layout.messages),
        )
    }
    assert report["font_sizes"] == {"1": 10, "2": 18}
    assert report["page_pixels_blank"] == 0 and report["page_pixels_over_latin_glyphs"] > 0


def test_the_race_program_gets_the_hook_the_glyph_entries_and_the_empty_kerning_row(built):
    _, _, result = built
    original = _image()
    image = unpack_pslz(result.gtmain)
    assert len(image) == len(original)
    assert read_pslz(result.gtmain) == read_pslz(_exe(original))

    def at(address: int, length: int) -> bytes:
        return image[address - LOAD : address - LOAD + length]

    assert at(overlay.HOOK_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    call = at(overlay.LINE_STEP_CALL, 4)
    assert jal_target(overlay.LINE_STEP_CALL, call) == overlay.HOOKS.symbol_address("line_step")
    allowed = set(range(overlay.HOOK_ADDRESS, overlay.HOOK_END))
    allowed |= set(range(overlay.LINE_STEP_CALL, overlay.LINE_STEP_CALL + 4))
    for index, font in result.fonts.items():
        for code, glyph in font.glyphs.items():
            entry = at(overlay.FONT_TABLES[index] + 8 * code, 8)
            dy = engine.CELLS[index].dy
            assert entry[2:] == bytes((glyph.width, glyph.height, 0, dy + glyph.top,
                                       glyph.width - 1, glyph.height))  # fmt: skip
            kerning = at(overlay.KERN_TABLES[index] + 4 * code, 4)
            assert struct.unpack("<I", kerning)[0] == ZERO_ROW
            allowed |= set(
                range(
                    overlay.FONT_TABLES[index] + 8 * code, overlay.FONT_TABLES[index] + 8 * code + 8
                )
            )
            allowed |= set(
                range(
                    overlay.KERN_TABLES[index] + 4 * code, overlay.KERN_TABLES[index] + 4 * code + 4
                )
            )
    differ = {LOAD + offset for offset in range(len(image)) if image[offset] != original[offset]}
    assert differ <= allowed


def test_the_page_holds_the_glyphs_over_the_latin_ones_it_took(built):
    _, _, result = built
    before = _page()
    page = decompress_gtzip(result.gamefont, len(before))
    image = unpack_pslz(result.gtmain)
    covered: set[tuple[int, int]] = set()
    for index, font in result.fonts.items():
        for code, glyph in font.glyphs.items():
            if not glyph.height:
                continue
            offset = overlay.FONT_TABLES[index] + 8 * code - LOAD
            u, v = image[offset], image[offset + 1]
            for y, row in enumerate(glyph.rows):
                for x, value in enumerate(row):
                    pixel = page[(v + y) * ROW_BYTES + (u + x) // 2] >> 4 * ((u + x) % 2)
                    assert pixel & 0x3 == value
                    covered.add((u + x, v + y))
            # Over the Latin-1 glyphs of fonts 1 and 2, where the Arabic codes were.
            assert 60 <= v and v + glyph.height <= 128
    for y in range(PAGE_ROWS):
        for x in range(256):
            old = before[y * ROW_BYTES + x // 2] >> 4 * (x % 2) & 0xF
            new = page[y * ROW_BYTES + x // 2] >> 4 * (x % 2) & 0xF
            assert old >> 2 == new >> 2  # font 3's plane stays
            if (x, y) not in covered:
                assert old == new


def test_the_translated_briefings_replace_the_originals(built):
    _, _, result = built
    kind, files = read_gt_arc(result.messages)
    assert (kind, len(files)) == (1, 24) and len(result.messages) == len(_messages())
    texts = split_briefings(gt_arc_file(result.messages, LICENSE_FILE))
    briefings = _briefings()
    glyph_map = overlay.briefing_glyph_codes(briefings)[0]
    encoder = GranTurismoArabicEncoder(glyph_map)
    for briefing in briefings:
        encoded = encoder.encode(briefing.title, briefing.paragraphs).briefing
        assert parse_briefing(texts[briefing.index]) == encoded
    translated = {briefing.index for briefing in briefings}
    for index in set(range(BRIEFINGS)) - translated:
        assert texts[index] == _english(index)
    for index in range(24):
        if index != LICENSE_FILE:
            assert gt_arc_file(result.messages, index) == f"file {index}".encode()
    assert result.report["briefings"]["license.b1"]["test"] == "B-1"
    # Bars 6 pixels wide: "لفة واحدة و22 ثانية." is 17 glyphs on one line.
    assert result.report["briefings"]["license.b8"]["lines"] == [17 * 6]
    assert result.report["license_file_bytes"] < result.report["license_file_room"]


def test_originals_are_extracted_and_verified():
    track, layout = _synthetic()
    originals = overlay.extract_originals(
        track, briefings=_briefings(), layout=layout, verify_identity=False
    )
    assert originals == {key: ENGLISH[index] for key, (index, _) in ARABIC.items()}


def test_a_different_track_file_or_briefing_is_refused(font_path):
    track, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, verify_identity=True)
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    refused = [
        dataclasses.replace(layout, gtmain=dataclasses.replace(layout.gtmain, sha256="0" * 64)),
        dataclasses.replace(layout, gamefont=dataclasses.replace(layout.gamefont, lba=1)),
        dataclasses.replace(layout, messages=dataclasses.replace(layout.messages, size=1)),
        dataclasses.replace(layout, image_sha256="0" * 64),
        dataclasses.replace(layout, page_sha256="0" * 64),
        dataclasses.replace(layout, word_loop_sha256="0" * 64),
    ]
    for wrong in refused:
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_files(RawTrack(track), wrong)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH, wrong
    changed = dataclasses.replace(_briefings()[0], source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(track, briefings=(changed,), layout=layout, verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        {0x8002928C: b"\x00" * 4},  # an anchor
        {overlay.LINE_STEP_CALL: b"\x01\x00\x00\x00"},  # the site
        {overlay.FONT_SELECT[1]: address_pair("a2", 0x8009BE60)},  # font 1's table elsewhere
        {ZERO_ROW + 64: b"\x01"},  # the space has kerning
    ],
)
def test_game_code_that_differs_where_the_overlay_works_is_refused(change):
    track, layout = _disc(image=_image(change))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_files(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_the_hook_may_only_call_the_routines_it_names(monkeypatch):
    track, layout = _synthetic()
    code = bytearray(overlay.HOOK_CODE)
    end = overlay.HOOK_ADDRESS + len(code)
    code[-4:] = jal_instruction(end - 4, 0x80010000)
    monkeypatch.setattr(overlay, "HOOK_CODE", bytes(code))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_files(RawTrack(track), layout)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_the_license_file_keeps_to_its_room(font_path):
    # Files 16 bytes apart: the license file's room is little more than its English.
    track, layout = _disc(messages=_messages(room=0x10))
    words = " ".join(["انطلق"] * 12)  # two lines, 84 bytes
    long = dataclasses.replace(_briefings()[0], notation=f"اختبار 1\n{words}\nالسيارة.")
    with pytest.raises(ClassicRetroError) as caught:
        _build(track, layout, font_path, briefings=(long,))
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


def test_the_page_is_packed_afresh_when_it_does_not_fit_its_original_stream():
    page = _page()
    tight = compress_gtzip(page)
    changed = bytearray(page)
    changed[100 * ROW_BYTES : 101 * ROW_BYTES] = random.Random(3).randbytes(ROW_BYTES)
    padded = tight + bytes(400)
    stream, in_place = overlay.pack_page(padded, bytes(changed))
    assert not in_place and len(stream) == len(padded)
    assert decompress_gtzip(stream, len(page)) == bytes(changed)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.pack_page(tight, random.Random(4).randbytes(len(page)))
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


def test_the_sites_and_anchors_lie_apart_and_off_the_hook():
    spans = sorted(
        [(site.address, site.address + len(site.original)) for site in overlay.SITES]
        + [(address, address + len(data)) for address, data in overlay.ANCHORS.items()]
        + [(overlay.HOOK_ADDRESS, overlay.HOOK_END)]
    )
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
    for site in overlay.SITES:
        assert len(site.original) == len(site.patched) and site.original != site.patched
    assert len(overlay.HOOK_CODE) == overlay.HOOK_END - overlay.HOOK_ADDRESS
    # The hook's first word is the game's delay slot, as it was.
    assert overlay.HOOK_CODE[:4] == struct.pack("<I", 0x02C0A821)


def _equates() -> dict[str, int]:
    source = overlay.HOOK_SOURCE.read_text(encoding="utf-8")
    return {
        name: int(value, 0)
        for name, value in re.findall(r"^\s*\.equ\s+(\w+),\s*(\S+)", source, re.MULTILINE)
    }


def test_the_hook_source_uses_the_overlay_addresses_and_the_engine_geometry():
    assert _equates() == {
        "MEASURE": overlay.MEASURE,
        "DRAW_WORD": overlay.DRAW_WORD,
        "ARABIC_FIRST": engine.ARABIC_CODES[0],
        "MIRROR": engine.MIRROR,
        "DROP": engine.DROP,
        "BODY_FONT": BODY,
    }
    assert engine.LINE_STEP == 12 + 3


@pytest.mark.skipif(shutil.which("mipsel-linux-gnu-as") is None, reason="needs GNU MIPS binutils")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["targets", "check-translations", "gran-turismo"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["briefings"] == 3 and report["tests"] == ["B-1", "B-3", "B-8"]
    assert report["lines_measured"] is False
    assert main(["gran-turismo", "encode-arabic", "بب 1\nب ب."]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # One paragraph; the title, a word of four glyphs; two words of one glyph and two.
    assert encoded["count"] == (1 + 1) + (1 + 4 + 1) + 1 + (1 + 1 + 1) + (1 + 2 + 1)
    assert "lines" not in encoded
