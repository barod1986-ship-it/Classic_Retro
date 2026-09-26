"""The Pokémon Platinum ROM overlay, built from a synthetic DS image.

The image has Platinum's layout and none of its data: the ARM9 binary holds the
bytes the overlay checks (the call sites and anchors) where the game has them,
and zeros elsewhere; the ITCM and DTCM autoload blocks, the 74 overlays (the
intro's with the control pages' window), the fonts (invented 509-glyph fonts)
and the text banks (invented strings) are where the build looks for them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import struct

import pytest

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_target
from classic_retro.engines.pokemon_gen4 import (
    Gen4Font,
    MessageBank,
    command_skeleton,
    parse_notation,
    pieces_codes,
    split_text,
)
from classic_retro.engines.pokemon_gen4_arabic import (
    BASELINE,
    RTL_END,
    RTL_FIRST,
    SPACE_WIDTH,
    Gen4ArabicEncoder,
    Gen4RtlFont,
    rtl_glyph,
)
from classic_retro.patching.nitro import (
    NITROCODE,
    SECURE_AREA_CRC,
    Arm9Binary,
    Autoload,
    Narc,
    NitroImage,
    crc16,
    header_crc_valid,
    set_header_crc,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import platinum_arabic as overlay
from classic_retro.rom.platinum_arabic_script import (
    CONTROL_INFO,
    DIALOGUE,
    INFO_CHOICES,
    ROWAN_INTRO,
    ROWAN_INTRO_TV,
    TELEVISION,
    YES_NO,
    PlatinumArabicString,
    platinum_arabic_strings,
)

RAM = 0x02000000
PARAMS = 0xBA0
STATIC = 0x24000
DTCM = Autoload(0x027E0000, 0x60, 0x20)
OVERLAY_COUNT = 74
IMAGE_SIZE = 0x80000
# Invented originals: the intro's bank and the television's.
BANKS = {
    ROWAN_INTRO: (
        "Hello there!\rWelcome to the\nworld of Pokémon!",
        "Is your name {STRVAR_1 3, 0, 0}?{YESNO 0}",
        "Button A\n\nButton B",
        "Left in English.",
        "YES",
    ),
    ROWAN_INTRO_TV: ("\nGood night!\nSee you.",),
}
# key: (bank, index, window, rows), and the translations.
TRANSLATED = {
    "hello": (ROWAN_INTRO, 0, DIALOGUE, None),
    "name": (ROWAN_INTRO, 1, DIALOGUE, None),
    "control": (ROWAN_INTRO, 2, CONTROL_INFO, (True, False, True)),
    "yes": (ROWAN_INTRO, 4, YES_NO, None),
    "tv": (ROWAN_INTRO_TV, 0, TELEVISION, None),
}
ARABIC = {
    "hello": "مرحبا!\rأهلا بك في\nعالم بوكيمون!",
    "name": "هل اسمك {STRVAR_1 3, 0, 0}{YESNO 0}",
    "control": "الزر أ\n\nالزر ب",
    "yes": "نعم",
    "tv": "\nتصبح على خير!\nإلى اللقاء.",
}


def _align(offset: int) -> int:
    return (offset + 0x1FF) & ~0x1FF


def _original(bank: int, index: int) -> tuple[int, ...]:
    return pieces_codes(parse_notation(BANKS[bank][index]))


def _bank(number: int) -> bytes:
    strings = tuple(_original(number, index) for index in range(len(BANKS[number])))
    return MessageBank(0x1000 + number, strings).build()


def _narc(members: dict[int, bytes], count: int) -> bytes:
    """A NARC of ``count`` members without names, ``members`` by index, the rest empty."""
    data = bytearray()
    ranges = []
    for index in range(count):
        data += b"\xff" * (-len(data) % 4)
        member = members.get(index, b"")
        ranges.append((len(data), len(data) + len(member)))
        data += member
    data += b"\xff" * (-len(data) % 4)
    table = struct.pack("<HH", count, 0) + b"".join(struct.pack("<II", *r) for r in ranges)
    blocks = b"".join(
        magic + struct.pack("<I", 8 + len(body)) + body
        for magic, body in (
            (b"BTAF", table),
            (b"BTNF", struct.pack("<IHH", 4, 0, 1)),
            (b"GMIF", bytes(data)),
        )
    )
    return b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x100, 16 + len(blocks), 16, 3) + blocks


def _font() -> bytes:
    """509 invented glyphs of 16x16, widths 3 to 10."""
    glyphs = bytes((7 * index + 3) & 0xFF for index in range(64 * (RTL_FIRST - 1)))
    return Gen4Font(16, 16, 2, 2, glyphs, bytes(3 + n % 8 for n in range(RTL_FIRST - 1))).build()


def _intro_overlay() -> bytes:
    data = bytearray((bytes(range(256)) * 46)[: overlay.INTRO_OVERLAY_SIZE])
    at = overlay.CONTROL_WINDOW - overlay.INTRO_OVERLAY_RAM
    data[at : at + 8] = overlay.CONTROL_WINDOW_TEMPLATE
    return bytes(data)


def _arm9() -> bytes:
    """The static code with the sites and anchors, then ITCM's and DTCM's blocks and table."""
    data = bytearray(STATIC)

    def put(address: int, chunk: bytes) -> None:
        data[address - RAM : address - RAM + len(chunk)] = chunk

    for site in overlay.SITES:
        put(site.address, site.original)
    for address, chunk in overlay.ANCHORS.items():
        put(address, chunk)
    table = RAM + STATIC + overlay.ITCM_BLOCK_SIZE + DTCM.size
    params = (table, table + 24, RAM + STATIC, 0x02100000, 0x02100100, 0, 0x05027531)
    struct.pack_into("<7I", data, PARAMS, *params)
    data += bytes(range(0x60, 0xC0)) * (overlay.ITCM_BLOCK_SIZE // 0x60)
    data += bytes(range(DTCM.size))
    data += struct.pack("<III", overlay.ITCM_BLOCK_ADDRESS, overlay.ITCM_BLOCK_SIZE, 0)
    data += struct.pack("<III", DTCM.address, DTCM.size, DTCM.bss)
    return bytes(data)


def _fnt(first: int) -> bytes:
    root = b"\x87graphic" + struct.pack("<H", 0xF001) + b"\x87msgdata" + struct.pack("<H", 0xF002)
    root += b"\x00"
    graphic = b"\x0cpl_font.narc\x00"
    msgdata = b"\x0bpl_msg.narc\x00"
    tables = 24
    return (
        struct.pack("<IHH", tables, first, 3)
        + struct.pack("<IHH", tables + len(root), first, 0xF000)
        + struct.pack("<IHH", tables + len(root) + len(graphic), first + 1, 0xF000)
        + root
        + graphic
        + msgdata
    )


def _overlay_entry(number: int) -> bytes:
    if number == overlay.DUMMY_OVERLAY:
        ram, size = 0x01FF8660, 0x20
    elif number == overlay.INTRO_OVERLAY:
        ram, size = overlay.INTRO_OVERLAY_RAM, overlay.INTRO_OVERLAY_SIZE
    else:
        ram, size = 0x021D0D80, 0
    return struct.pack("<8I", number, ram, size, 0, 0, 0, number, 0)


def _synthetic_rom() -> bytes:
    rom = bytearray(b"\xff" * IMAGE_SIZE)
    rom[:0x4000] = bytes(0x4000)
    position = 0x4000

    def place(data: bytes) -> int:
        nonlocal position
        start = position
        rom[start : start + len(data)] = data
        position = _align(start + len(data))
        return start

    arm9 = _arm9()
    arm9_at = place(arm9 + struct.pack("<III", NITROCODE, PARAMS, 0))
    table = b"".join(_overlay_entry(number) for number in range(OVERLAY_COUNT))
    table_at = place(table)
    files = {overlay.INTRO_OVERLAY: _intro_overlay()}
    starts = {overlay.INTRO_OVERLAY: place(files[overlay.INTRO_OVERLAY])}
    arm7 = bytes(range(256)) * 2
    arm7_at = place(arm7)
    fnt = _fnt(OVERLAY_COUNT)
    fnt_at = place(fnt)
    fat_at = place(bytes(8 * (OVERLAY_COUNT + 2)))
    banks = _narc({number: _bank(number) for number in BANKS}, ROWAN_INTRO_TV + 1)
    fonts = _narc({0: _font(), 1: _font(), 2: b"another font"}, 3)
    for file_id, data in ((OVERLAY_COUNT, fonts), (OVERLAY_COUNT + 1, banks)):
        files[file_id] = data
        starts[file_id] = place(data)
    for file_id, data in files.items():
        struct.pack_into(
            "<II", rom, fat_at + 8 * file_id, starts[file_id], starts[file_id] + len(data)
        )
    used = max(starts[file_id] + len(data) for file_id, data in files.items())

    rom[0:12] = b"POKEMON PL\0\0"
    rom[12:18] = b"CPUE01"
    struct.pack_into("<4I", rom, 0x20, arm9_at, RAM + 0x800, RAM, len(arm9))
    struct.pack_into("<4I", rom, 0x30, arm7_at, 0x02380000, 0x02380000, len(arm7))
    struct.pack_into("<4I", rom, 0x40, fnt_at, len(fnt), fat_at, 8 * (OVERLAY_COUNT + 2))
    struct.pack_into("<4I", rom, 0x50, table_at, len(table), 0, 0)
    struct.pack_into("<I", rom, 0x80, used)
    # The secure area's CRC, as a dump without the cartridge's encryption would hold it.
    struct.pack_into("<H", rom, SECURE_AREA_CRC, crc16(bytes(rom[0x4000:0x8000])))
    set_header_crc(rom)
    return bytes(rom)


def _strings() -> tuple[PlatinumArabicString, ...]:
    strings = []
    for key, (bank, index, window, rows) in TRANSLATED.items():
        codes = _original(bank, index)
        strings.append(
            PlatinumArabicString(
                key=key,
                bank=bank,
                index=index,
                window=window,
                source_sha256=overlay.source_digest(codes),
                source_skeleton=command_skeleton(codes),
                notation=ARABIC[key],
                fixed_rows=rows,
            )
        )
    return tuple(strings)


def _fake_font(font_path=None, glyph_map: GlyphCodes | None = None, **_kwargs) -> Gen4RtlFont:
    """Every glyph a bar 5 pixels wide; the space is the real one."""
    assert glyph_map is not None
    bar = rtl_glyph({(x, y) for x in range(4) for y in range(4, BASELINE)}, 5)
    glyphs = {
        codes[0]: rtl_glyph((), SPACE_WIDTH) if character == " " else bar
        for character, codes in glyph_map.sequences.items()
    }
    return Gen4RtlFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


@pytest.fixture(autouse=True)
def synthetic_data(monkeypatch):
    """The synthetic image's fonts and banks are the pinned ones; the font is drawn by hand."""
    monkeypatch.setattr(overlay, "FONT_SHA256", hashlib.sha256(_font()).hexdigest())
    monkeypatch.setattr(
        overlay,
        "BANK_SHA256",
        {number: hashlib.sha256(_bank(number)).hexdigest() for number in BANKS},
    )
    monkeypatch.setattr(overlay, "BANK_STRINGS", {number: len(BANKS[number]) for number in BANKS})
    monkeypatch.setattr(overlay, "build_gen4_rtl_font", _fake_font)


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


def _build(rom: bytes, tmp_path, **changes):
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    arguments = {"strings": _strings(), "verify_identity": False} | changes
    return overlay.build_platinum_arabic_rom(rom, font_file, **arguments)


@pytest.fixture
def build(synthetic, tmp_path):
    return synthetic, _build(synthetic, tmp_path)


def test_every_site_calls_its_hook_in_itcm(build):
    rom, result = build
    before = Arm9Binary.from_image(NitroImage(rom))
    after = Arm9Binary.from_image(NitroImage(result.rom))
    for site in overlay.SITES:
        call = after.read(site.address, 4)
        assert bl_target(site.address, call) == overlay.HOOKS.symbol_address(site.hook)
        assert overlay.HOOK_CODE_ADDRESS <= bl_target(site.address, call) < 0x01FF8900
    # The ITCM block grew by the room of overlay 3 and the hooks; DTCM's moved along.
    grown = overlay.ITCM_BLOCK_SIZE + 0x20 + len(overlay.HOOK_CODE)
    assert after.autoloads() == (Autoload(overlay.ITCM_BLOCK_ADDRESS, grown, 0), DTCM)
    itcm = after.block_data_offset(0)
    assert (
        after.data[itcm : itcm + overlay.ITCM_BLOCK_SIZE]
        == before.data[itcm : itcm + overlay.ITCM_BLOCK_SIZE]
    )
    hooks = itcm + overlay.HOOK_CODE_ADDRESS - overlay.ITCM_BLOCK_ADDRESS
    assert after.data[hooks - 0x20 : hooks] == bytes(0x20)
    assert after.data[hooks : hooks + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    dtcm = after.block_data_offset(1)
    assert after.data[dtcm : dtcm + DTCM.size] == bytes(range(DTCM.size))
    # The static code changes at the five calls only.
    sites = {site.address - RAM + offset for site in overlay.SITES for offset in range(4)}
    changed = {
        offset for offset in range(STATIC) if after.data[offset] != before.data[offset]
    } - set(range(PARAMS, PARAMS + 8))
    assert changed <= sites and len(changed) > 5


def test_the_overlay_table_moves_to_the_free_space(build):
    rom, result = build
    before, after = NitroImage(rom), NitroImage(result.rom)
    assert after.header.arm9_overlay_offset == _align(before.header.used_size)
    assert after.overlays() == before.overlays()
    assert after.header.arm9_size == before.header.arm9_size + 0x20 + len(overlay.HOOK_CODE)
    assert after.arm9_footer() == before.arm9_footer()
    assert header_crc_valid(result.rom)
    # The calls the hooks take over are in the secure area: its CRC follows them.
    assert rom[0x4000:0x8000] != result.rom[0x4000:0x8000]
    stored = struct.unpack_from("<H", result.rom, SECURE_AREA_CRC)[0]
    assert stored == crc16(result.rom[0x4000:0x8000])


def test_the_fonts_gain_the_right_to_left_glyphs(build):
    _, result = build
    data = NitroImage(result.rom).read(overlay.FONT_ARCHIVE)
    archive = Narc.read(data)
    game = Gen4Font.read(_font())
    last = max(result.font.glyphs)
    for index in overlay.FONTS:
        font = Gen4Font.read(archive.member(data, index))
        assert font.count == last
        assert font.glyphs[: len(game.glyphs)] == game.glyphs
        assert font.widths[: game.count] == game.widths
        for code, glyph in result.font.glyphs.items():
            assert font.width(code) == glyph.width
            assert font.glyph(code) == glyph.pixels
    assert archive.member(data, 2) == b"another font"
    # The first code is the menus' arrow, whatever the script holds.
    assert min(result.font.glyphs) == RTL_FIRST and last < RTL_END


def test_the_translations_are_written_in_paint_order(build):
    _, result = build
    data = NitroImage(result.rom).read(overlay.MESSAGE_ARCHIVE)
    archive = Narc.read(data)
    banks = {number: MessageBank.read(archive.member(data, number)) for number in BANKS}
    strings = _strings()
    glyph_map = overlay.script_glyph_codes(strings)
    encoder = Gen4ArabicEncoder(glyph_map, result.font)
    encoded = overlay.encode_strings(encoder, strings, Gen4Font.read(_font()))
    for string in strings:
        codes = banks[string.bank].strings[string.index]
        assert codes == encoded[string.key].codes
        assert command_skeleton(codes) == string.source_skeleton
        assert any(RTL_FIRST <= code < RTL_END for code in codes)
        assert banks[string.bank].seed == 0x1000 + string.bank
    # The string left in English is as the image had it.
    assert banks[ROWAN_INTRO].strings[3] == _original(ROWAN_INTRO, 3)
    # The name and the icon stay in the string, as the game's commands.
    name = split_text(banks[ROWAN_INTRO].strings[1])
    assert [piece.notation for piece in name if not isinstance(piece, str)] == [
        "{STRVAR_1 3, 0, 0}",
        "{YESNO 0}",
    ]
    # Five letters and a space a row: 5 * 5 + 4 pixels.
    assert result.report["string_lines"]["control"] == [29, 0, 29]


def test_the_control_pages_window_is_narrowed_in_place(build):
    rom, result = build
    before, after = NitroImage(rom), NitroImage(result.rom)
    number = overlay.INTRO_OVERLAY
    assert after.file_range(number) == before.file_range(number)
    old, new = before.read(number), after.read(number)
    at = overlay.CONTROL_WINDOW - overlay.INTRO_OVERLAY_RAM
    assert new[at : at + 8] == overlay.CONTROL_WINDOW_NARROW
    # 22 tiles wide instead of 24; nothing else changes.
    assert (old[at + 3], new[at + 3]) == (24, 22)
    assert new[:at] + new[at + 8 :] == old[:at] + old[at + 8 :]


def test_only_the_code_the_tables_and_the_free_space_change(build):
    rom, result = build
    before, after = NitroImage(rom), NitroImage(result.rom)
    output = result.rom
    arm9_end = after.header.arm9_offset + after.header.arm9_size + 12
    window = before.file_range(overlay.INTRO_OVERLAY)[0] + (
        overlay.CONTROL_WINDOW - overlay.INTRO_OVERLAY_RAM
    )
    fat = before.header.fat_offset
    allowed = [
        (0, 0x200),
        (before.header.arm9_offset, arm9_end),
        (window, window + 8),
        (fat, fat + before.header.fat_size),
        # The text banks, rewritten where they were when they fit.
        before.file_range(OVERLAY_COUNT + 1),
        (before.header.used_size, IMAGE_SIZE),
    ]
    changed = [
        offset
        for block in range(0, IMAGE_SIZE, 0x100)
        if output[block : block + 0x100] != rom[block : block + 0x100]
        for offset in range(block, block + 0x100)
        if output[offset] != rom[offset]
    ]
    assert changed and all(any(a <= offset < b for a, b in allowed) for offset in changed)
    # A file that fits where it was stays there (the intro's overlay); one that grew
    # moves past the used area, after the overlay table (the fonts).
    placed = result.report["files"]
    assert set(placed) == {str(overlay.INTRO_OVERLAY), str(OVERLAY_COUNT), str(OVERLAY_COUNT + 1)}
    for file_id in (overlay.INTRO_OVERLAY, OVERLAY_COUNT, OVERLAY_COUNT + 1):
        start, end = before.file_range(file_id)
        new_start, new_end = after.file_range(file_id)
        assert placed[str(file_id)] == f"{new_start:#x}..{new_end:#x}"
        if new_end - new_start <= end - start:
            assert new_start == start
        else:
            assert new_start >= after.header.arm9_overlay_offset + 32 * OVERLAY_COUNT
    fonts = after.file_range(OVERLAY_COUNT)
    assert fonts[0] > before.header.used_size and after.header.used_size >= fonts[1]


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, result = build
    assert apply_bps(result.patch.data, rom) == result.rom
    report = result.report
    assert report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()
    assert report["base"] == "unverified" and report["strings"] == len(TRANSLATED)
    assert report["hook_sites"] == 5 and report["hook_bytes"] == len(overlay.HOOK_CODE)
    assert report["rtl_codes"].startswith("01FE..") and report["text_banks"] == [389, 607]


def test_an_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_platinum_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


def _patch(rom: bytearray, offset: int, data: bytes) -> None:
    rom[offset : offset + len(data)] = data


@pytest.mark.parametrize(
    "damage",
    [
        "site",
        "anchor",
        "itcm",
        "dummy",
        "itcm overlay",
        "window",
        "intro size",
        "font",
        "bank",
        "strings",
        "footer",
    ],
)
def test_a_different_image_is_refused(synthetic, tmp_path, monkeypatch, damage):
    rom = bytearray(synthetic)
    image = NitroImage(synthetic)
    arm9 = image.header.arm9_offset
    table = image.header.arm9_overlay_offset
    if damage == "site":
        rom[arm9 + overlay.SITES[2].address - RAM] ^= 1
    elif damage == "anchor":
        rom[arm9 + 0x0201C294 - RAM] ^= 1
    elif damage == "itcm":
        itcm = arm9 + STATIC + overlay.ITCM_BLOCK_SIZE + DTCM.size
        struct.pack_into("<I", rom, itcm, overlay.ITCM_BLOCK_ADDRESS + 0x20)
    elif damage == "dummy":
        struct.pack_into("<I", rom, table + 32 * overlay.DUMMY_OVERLAY + 8, 0x40)
    elif damage == "itcm overlay":
        struct.pack_into("<I", rom, table + 32 * 5 + 4, 0x01FF9000)
    elif damage == "window":
        start = image.file_range(overlay.INTRO_OVERLAY)[0]
        rom[start + overlay.CONTROL_WINDOW - overlay.INTRO_OVERLAY_RAM + 3] = 23
    elif damage == "intro size":
        struct.pack_into("<I", rom, table + 32 * overlay.INTRO_OVERLAY + 8, 0x2D00)
    elif damage == "font":
        start = image.file_range(OVERLAY_COUNT)[0]
        fonts = image.read(OVERLAY_COUNT)
        font = bytearray(_font())
        font[-1] ^= 1
        _patch(rom, start, Narc.read(fonts).rebuilt(fonts, {1: bytes(font)}))
    elif damage == "bank":
        start = image.file_range(OVERLAY_COUNT + 1)[0]
        banks = image.read(OVERLAY_COUNT + 1)
        bank = MessageBank.read(_bank(ROWAN_INTRO))
        changed = bank.replaced({3: _original(ROWAN_INTRO, 4)}).build()
        _patch(rom, start, Narc.read(banks).rebuilt(banks, {ROWAN_INTRO: changed}))
    elif damage == "strings":
        monkeypatch.setattr(overlay, "BANK_STRINGS", {ROWAN_INTRO: 45, ROWAN_INTRO_TV: 1})
    else:
        rom[arm9 + image.header.arm9_size] ^= 1
    with pytest.raises(ClassicRetroError) as caught:
        _build(bytes(rom), tmp_path)
    # A different structure is a format error; different bytes are not the pinned image.
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.INVALID_BYTE_RANGE,
    }


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("digest", ErrorCode.SOURCE_BASELINE_MISMATCH),
        ("skeleton", ErrorCode.SOURCE_BASELINE_MISMATCH),
        ("index", ErrorCode.INVALID_REFERENCE),
        ("bank", ErrorCode.INVALID_REFERENCE),
        ("twice", ErrorCode.DUPLICATE_ENTRY_ID),
        ("same string", ErrorCode.DUPLICATE_ENTRY_ID),
        ("rows", ErrorCode.TEXT_BOX_OVERFLOW),
        ("commands", ErrorCode.TOKEN_ORDER_VIOLATION),
        ("window", ErrorCode.TEXT_BOX_OVERFLOW),
    ],
)
def test_a_translation_that_does_not_match_its_original_is_refused(
    synthetic, tmp_path, damage, code
):
    strings = list(_strings())
    hello, name, control = strings[:3]
    if damage == "digest":
        strings[0] = dataclasses.replace(hello, source_sha256="0" * 64)
    elif damage == "skeleton":
        strings[0] = dataclasses.replace(hello, source_skeleton=("\r", "\r"))
    elif damage == "index":
        strings[0] = dataclasses.replace(hello, index=len(BANKS[ROWAN_INTRO]))
    elif damage == "bank":
        strings[0] = dataclasses.replace(hello, bank=ROWAN_INTRO + 1)
    elif damage == "twice":
        strings.append(hello)
    elif damage == "same string":
        strings.append(dataclasses.replace(hello, key="hello again"))
    elif damage == "rows":
        # The same commands, but the blank row moved to the top.
        strings[2] = dataclasses.replace(control, notation="\nالزر أ\nالزر ب")
    elif damage == "commands":
        strings[1] = dataclasses.replace(name, notation="هل اسمك {STRVAR_1 3, 1, 0}{YESNO 0}")
    else:
        strings[3] = dataclasses.replace(strings[3], notation="نعم نعم نعم")
    with pytest.raises(ClassicRetroError) as caught:
        _build(synthetic, tmp_path, strings=tuple(strings))
    assert caught.value.code is code


def test_extract_gives_every_original_in_notation(synthetic):
    originals = overlay.extract_originals(synthetic, strings=_strings(), verify_identity=False)
    assert originals == {key: BANKS[bank][index] for key, (bank, index, _, _) in TRANSLATED.items()}


def test_shipped_translations_check_without_the_rom():
    report = overlay.check_platinum_translations()
    strings = platinum_arabic_strings()
    assert report["strings"] == len(strings) == 38
    assert report["lines_measured"] is False and report["encoded_codes"] > 38
    assert report["rtl_glyphs"] <= RTL_END - RTL_FIRST
    # In the order the game shows them: the intro's strings 0 to 36, then the television's.
    assert [(string.bank, string.index) for string in strings] == [
        *((ROWAN_INTRO, index) for index in range(37)),
        (ROWAN_INTRO_TV, 0),
    ]
    by_key = {string.key: string for string in strings}
    assert by_key["control_info_icon"].window == DIALOGUE
    assert by_key["choice_yes"].window == YES_NO
    assert by_key["choice_control_info"].window == INFO_CHOICES
    assert [key for key, string in by_key.items() if string.fixed_rows] == [
        "control_info_buttons",
        "control_info_xy",
    ]


def test_translations_are_measured_and_previewed_with_a_font(tmp_path):
    preview = tmp_path / "font.png"
    text_preview = tmp_path / "text.png"
    report = overlay.check_platinum_translations(tmp_path / "f.ttf", preview, text_preview)
    assert report["lines_measured"] and report["widest_line"] <= TELEVISION.width
    assert report["font_size"] == 11 and report["name_width"] == 48
    assert preview.is_file() and text_preview.is_file()
    with pytest.raises(ClassicRetroError) as caught:
        overlay.check_platinum_translations(None, preview)
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_encode_command_prints_the_codes(capsys, tmp_path):
    assert main(["platinum", "encode-arabic", "بب {STRVAR_1 3, 0, 0}\nب"]) == 0
    payload = json.loads(capsys.readouterr().out)
    codes = payload["codes"].split()
    assert codes[-1] == "FFFF" and "FFFE" in codes and "E000" in codes
    assert all(code in ("FFFE", "0103", "0002", "0000", "E000", "FFFF") or code >= "01FE"
               for code in codes)  # fmt: skip
    assert payload["count"] == len(codes) and "widths" not in payload
    font = tmp_path / "f.ttf"
    arguments = ["platinum", "encode-arabic", "نعم", "--window", "yes-no", "--font", str(font)]
    assert main(arguments) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["widths"] == [15] and payload["line_width"] == 36
    assert main(["platinum", "encode-arabic", "ب\nب", "--window", "yes-no"]) != 0
    assert "TEXT_BOX_OVERFLOW" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_stored_hook_bytes_match_the_source():
    assert overlay.check_hook_code()["match"] is True
