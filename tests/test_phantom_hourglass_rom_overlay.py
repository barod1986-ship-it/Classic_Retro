from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import shutil
import struct
from functools import cache

import pytest

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.arm import bl_instruction, bl_target
from classic_retro.engines.phantom_hourglass import DEMO_MESSAGES, FONT_FILE
from classic_retro.engines.phantom_hourglass_arabic import (
    ARABIC_CODES,
    BASELINE,
    SPACE_WIDTH,
    PhArabicEncoder,
    PhArabicFont,
    ph_glyph,
)
from classic_retro.font.nftr import GlyphWidth, NftrFont
from classic_retro.patching.nitro import (
    SIGNATURE_MAGIC,
    NdsHeader,
    NitroImage,
    header_crc_valid,
    secure_area_crc,
    set_header_crc,
)
from classic_retro.rebuild.blz import compress_blz, decompress_blz_in_place
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import phantom_hourglass_arabic as overlay
from classic_retro.rom.phantom_hourglass_arabic_script import PhArabicMessage
from classic_retro.text.bmg import Bmg, encode_text, notation_skeleton, parse_notation

# Invented English messages of the prologue's file, and the translated ones.
TEXTS = [
    "{01:14000600}Once upon{01:0A001400} a time\nthere was a sea.\n{01:0E00BE00}",
    "{01:14000200}Her name was {FF:00000300}Tetra{FF:00000000}.",
    "Left alone.",
]
ARABIC = {
    "once": (0, "{01:14000600}كان يا{01:0A001400} ما كان\nبحر واسع.\n{01:0E00BE00}"),
    "name": (1, "{01:14000200}اسمها {FF:00000300}تيترا{FF:00000000}."),
}
FOOTER = struct.pack("<III", 0xDEC00621, overlay.MODULE_PARAMS, 0)
# The ARM9 reaches past the routine the hook replaces.
ARM9_END = 0x50000
IMAGE_SIZE = 0x200000


def _fnt(tree: dict) -> bytes:
    """A file name table for nested directories (dicts) and files (lists of names)."""
    directories: list[tuple[str, dict | list]] = []

    def collect(name: str, node: dict | list) -> None:
        directories.append((name, node))
        if isinstance(node, dict):
            for child, sub in node.items():
                collect(child, sub)

    collect("", tree)
    numbers = {id(node): number for number, (_, node) in enumerate(directories)}
    tables = []
    first_ids = []
    file_id = 0
    for _, node in directories:
        table = bytearray()
        first_ids.append(file_id)
        if isinstance(node, dict):
            for child, sub in node.items():
                table += bytes((0x80 | len(child),)) + child.encode()
                table += struct.pack("<H", 0xF000 | numbers[id(sub)])
        else:
            for name in node:
                table += bytes((len(name),)) + name.encode()
                file_id += 1
        tables.append(bytes(table) + b"\x00")
    main_table = bytearray()
    offset = 8 * len(directories)
    for number, table in enumerate(tables):
        parent = len(directories) if number == 0 else 0xF000
        main_table += struct.pack("<IHH", offset, first_ids[number], parent)
        offset += len(table)
    return bytes(main_table) + b"".join(tables)


def _font() -> bytes:
    """A 14x16, 2-bit font: a space, the kana codes and a few Latin letters, their glyphs
    noise (dense like the kana it stands for)."""
    codes = [0x20, *ARABIC_CODES, *range(0x41, 0x5B)]
    count = len(codes)
    glyph_bytes = 56
    cglp_at = 16 + 0x1C
    glyphs = random.Random(4).randbytes(glyph_bytes * count)
    cglp = struct.pack("<BBHBBBB", 14, 16, glyph_bytes, 14, 14, 2, 0) + glyphs
    cglp = b"PLGC" + struct.pack("<I", 8 + len(cglp)) + cglp
    cwdh_at = cglp_at + len(cglp)
    cwdh = struct.pack("<HHI", 0, count - 1, 0) + struct.pack("<bBB", 0, 9, 9) * count
    cwdh += bytes(-len(cwdh) % 4)
    cwdh = b"HDWC" + struct.pack("<I", 8 + len(cwdh)) + cwdh
    cmap_at = cwdh_at + len(cwdh)
    pairs = b"".join(struct.pack("<HH", code, glyph) for glyph, code in enumerate(codes))
    cmap = struct.pack("<HHHHI", 0, 0xFFFF, 2, 0, 0) + struct.pack("<H", count) + pairs
    cmap += bytes(-len(cmap) % 4)
    cmap = b"PAMC" + struct.pack("<I", 8 + len(cmap)) + cmap
    info = struct.pack("<BBHbBBBIII", 0, 16, 0, 0, 14, 14, 1, cglp_at + 8, cwdh_at + 8, cmap_at + 8)
    info = b"FNIF" + struct.pack("<I", 8 + len(info)) + info
    body = info + cglp + cwdh + cmap
    return b"RTFN" + struct.pack("<HHIHH", 0xFEFF, 0x100, 16 + len(body), 16, 4) + body


def _bmg(texts: list[str]) -> bytes:
    return Bmg(
        header_tail=bytes((2,)) + bytes(15),
        info_field=0x16,
        attributes=tuple(bytes.fromhex("00010300") for _ in texts),
        texts=tuple(parse_notation(text) for text in texts),
    ).build()


def _arm9() -> bytearray:
    """An unpacked ARM9: start-up code with its module parameters, then code with the glyph
    call, the routines the hook calls and the routine it replaces where the game has them."""
    rng = random.Random(21)
    words = [rng.randrange(1 << 32) for _ in range(48)]
    data = bytearray(b"".join(struct.pack("<I", rng.choice(words)) for _ in range(ARM9_END // 4)))
    data[:0x4000] = rng.randbytes(0x4000)
    params = overlay.MODULE_PARAMS
    struct.pack_into("<7I", data, params, *(rng.randrange(1 << 32) for _ in range(7)))
    data[params + 0x1C : params + 0x24] = overlay.NITROCODE
    for address in (*overlay.USA_LAYOUT.anchors, overlay.HOOK_CODE_ADDRESS):
        size = overlay.HOOK_ROOM if address == overlay.HOOK_CODE_ADDRESS else 0x24
        start = address - overlay.ARM9_RAM
        data[start : start + size] = rng.randbytes(size)
    site = overlay.GLYPH_SITE - overlay.ARM9_RAM
    data[site : site + 4] = bl_instruction(overlay.GLYPH_SITE, overlay.DRAW_CHAR)
    return data


def _read(arm9: bytes, address: int, length: int) -> bytes:
    return arm9[address - overlay.ARM9_RAM : address - overlay.ARM9_RAM + length]


@cache
def _synthetic() -> tuple[bytes, overlay.PhLayout]:
    """A DS image with the parts the overlay reads, and the layout that pins them."""
    arm9 = _arm9()
    stored = bytearray(compress_blz(bytes(arm9)))
    for binary in (arm9, stored):
        struct.pack_into("<I", binary, overlay.PACKED_END, overlay.ARM9_RAM + len(stored))
    image = bytearray(b"\xff" * IMAGE_SIZE)
    image[:0x4000] = bytes(0x4000)
    image[0:12] = b"CLASSICRETRO"
    image[12:16] = b"CRTE"
    image[0x4000 : 0x4000 + len(stored)] = stored
    footer_at = 0x4000 + len(stored)
    image[footer_at : footer_at + len(FOOTER)] = FOOTER
    table = -(-(footer_at + len(FOOTER) + 0x100) // 0x200) * 0x200
    struct.pack_into("<4I", image, 0x20, 0x4000, 0x02000800, overlay.ARM9_RAM, len(stored))
    fnt = _fnt({"English": {"Message": ["demo.bmg"]}, "Font": ["zeldaDS_15.nftr"]})
    fnt_at, fat_at, data_at = table + 0x200, table + 0x1200, table + 0x2000
    image[fnt_at : fnt_at + len(fnt)] = fnt
    struct.pack_into("<4I", image, 0x40, fnt_at, len(fnt), fat_at, 16)
    struct.pack_into("<I", image, 0x50, table)
    position = data_at
    for number, data in enumerate((_bmg(TEXTS), _font())):
        image[position : position + len(data)] = data
        struct.pack_into("<II", image, fat_at + 8 * number, position, position + len(data))
        position += -(-len(data) // 0x200) * 0x200
    struct.pack_into("<I", image, 0x80, position)
    image[position : position + 0x88] = SIGNATURE_MAGIC + bytes(range(0x84))
    struct.pack_into("<H", image, 0x6C, 0x1357)
    struct.pack_into("<H", image, 0x15C, 0xCF56)
    set_header_crc(image)
    anchors = {
        address: _read(arm9, address, len(expected))
        for address, expected in overlay.USA_LAYOUT.anchors.items()
    }
    layout = overlay.PhLayout(
        arm9_size=len(stored),
        arm9_stored_sha256=hashlib.sha256(stored).hexdigest(),
        arm9_sha256=hashlib.sha256(arm9).hexdigest(),
        arm9_footer=FOOTER,
        overlay_table=table,
        font_sha256=hashlib.sha256(_font()).hexdigest(),
        messages_sha256=hashlib.sha256(_bmg(TEXTS)).hexdigest(),
        anchors=anchors,
        hook_room_sha256=hashlib.sha256(
            _read(arm9, overlay.HOOK_CODE_ADDRESS, overlay.HOOK_ROOM)
        ).hexdigest(),
    )
    return bytes(image), layout


def _messages() -> tuple[PhArabicMessage, ...]:
    messages = []
    for key, (index, arabic) in ARABIC.items():
        original = parse_notation(TEXTS[index])
        messages.append(
            PhArabicMessage(
                key=key,
                index=index,
                source_sha256=hashlib.sha256(encode_text(original)).hexdigest(),
                source_skeleton=notation_skeleton(original),
                notation=arabic,
            )
        )
    return tuple(messages)


def _fake_font(font_path=None, glyph_map: GlyphCodes | None = None, **_kwargs) -> PhArabicFont:
    """Every glyph a bar 5 pixels wide; the space is the real one."""
    assert glyph_map is not None
    bar = ph_glyph({(x, y) for x in range(5) for y in range(4, BASELINE)}, 5)
    glyphs = {}
    for character, codes in glyph_map.sequences.items():
        for code in codes:
            glyphs[code] = ph_glyph((), SPACE_WIDTH) if character == " " else bar
    return PhArabicFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=11)


@pytest.fixture
def build(monkeypatch, tmp_path):
    monkeypatch.setattr(overlay, "build_ph_arabic_font", _fake_font)
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"not read by the fake font")
    rom, layout = _synthetic()
    result = overlay.build_ph_arabic_rom(
        rom, font_path, messages=_messages(), layout=layout, verify_identity=False
    )
    return rom, layout, result


def _unpacked(output: bytes) -> bytes:
    header = NdsHeader.read(output)
    return decompress_blz_in_place(output[0x4000 : 0x4000 + header.arm9_size])


def test_the_build_writes_the_hook_the_font_the_messages_and_a_patch(build):
    rom, layout, result = build
    output = result.rom
    assert apply_bps(result.patch.data, rom) == output
    assert header_crc_valid(output)
    header = NdsHeader.read(output)
    assert 0x4000 + header.arm9_size + len(FOOTER) <= layout.overlay_table
    assert output[0x4000 + header.arm9_size :][: len(FOOTER)] == FOOTER
    assert set(output[0x4000 + header.arm9_size + len(FOOTER) : layout.overlay_table]) <= {0xFF}
    arm9 = _unpacked(output)
    packed_end = struct.unpack_from("<I", arm9, overlay.PACKED_END)[0]
    assert packed_end == overlay.ARM9_RAM + header.arm9_size
    # The hook over the unused routine, and the glyph call to it; nothing else moved.
    assert _read(arm9, overlay.HOOK_CODE_ADDRESS, len(overlay.HOOK_CODE)) == overlay.HOOK_CODE
    site = _read(arm9, overlay.GLYPH_SITE, 4)
    assert bl_target(overlay.GLYPH_SITE, site) == overlay.HOOK_CODE_ADDRESS
    original = _arm9()
    changed = [index for index, (a, b) in enumerate(zip(original, arm9, strict=True)) if a != b]
    hook = overlay.HOOK_CODE_ADDRESS - overlay.ARM9_RAM
    assert all(
        overlay.PACKED_END <= index < overlay.PACKED_END + 4
        or overlay.GLYPH_SITE - overlay.ARM9_RAM
        <= index
        < overlay.GLYPH_SITE - overlay.ARM9_RAM + 4
        or hook <= index < hook + len(overlay.HOOK_CODE)
        for index in changed
    )
    # The font: the Arabic glyphs at the first kana, blank kana after them.
    font = NftrFont(NitroImage(output).read(FONT_FILE))
    first = font.codes[ARABIC_CODES[0]]
    assert font.width(first) == GlyphWidth(0, SPACE_WIDTH, SPACE_WIDTH - 1)
    second = font.codes[ARABIC_CODES[1]]
    assert font.width(second) == GlyphWidth(0, 5, 4)
    assert font.glyph(second)[BASELINE - 1][:6] == (3, 3, 3, 3, 3, 0)
    assert font.width(font.codes[ARABIC_CODES[-1]]) == GlyphWidth(0, 0, 0)
    assert font.width(font.codes[0x41]) == GlyphWidth(0, 9, 9)
    # The messages: the translated ones, the others as they were.
    messages = Bmg.parse(NitroImage(output).read(DEMO_MESSAGES))
    assert messages.texts[2] == ("Left alone.",)
    assert result.report["messages"] == 2
    assert result.report["hook_bytes"] == len(overlay.HOOK_CODE) <= overlay.HOOK_ROOM


def test_translated_messages_read_back_as_encoded(build):
    _, _, result = build
    messages = _messages()
    glyph_map = overlay.script_glyph_codes(messages)
    encoder = PhArabicEncoder(glyph_map, _fake_font(glyph_map=glyph_map))
    texts = Bmg.parse(NitroImage(result.rom).read(DEMO_MESSAGES)).texts
    for message in messages:
        assert texts[message.index] == encoder.encode(message.pieces).pieces
    assert result.report["message_lines"]["once"][2] == 0


def test_the_secure_area_crc_follows_the_module_parameters(build):
    rom, _, result = build
    expected = secure_area_crc(rom, result.rom, NdsHeader.read(rom).secure_area_crc)
    assert NdsHeader.read(result.rom).secure_area_crc == expected
    assert (
        rom[0x4000 : 0x4000 + overlay.PACKED_END]
        == result.rom[0x4000 : 0x4000 + overlay.PACKED_END]
    )


def test_the_patch_keeps_the_original_arm9_where_it_did_not_change(build):
    rom, layout, result = build
    stored = rom[0x4000 : 0x4000 + layout.arm9_size]
    changed = result.rom[0x4000 : 0x4000 + NdsHeader.read(result.rom).arm9_size]
    common = next(i for i in range(len(changed)) if changed[i] != stored[i])
    assert common == overlay.PACKED_END
    later = next(i for i in range(overlay.PACKED_END + 4, len(changed)) if changed[i] != stored[i])
    assert later > 0x4000 + 0x100
    assert len(result.patch.data) < 0x4000


def test_an_arm9_that_packs_past_its_room_is_refused(build, monkeypatch):
    rom, layout, result = build
    parts = overlay.read_parts(rom, layout)
    size = NdsHeader.read(result.rom).arm9_size
    tight = dataclasses.replace(layout, overlay_table=0x4000 + size + len(FOOTER) - 1)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.packed_arm9(parts, tight)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    monkeypatch.setattr(overlay, "HOOK_ROOM", len(overlay.HOOK_CODE) - 4)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.hooked_arm9(parts.arm9)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


def test_the_hook_may_only_call_the_game_routines_it_names(monkeypatch):
    rom, layout = _synthetic()
    parts = overlay.read_parts(rom, layout)
    code = bytearray(overlay.HOOK_CODE)
    code[-12:-8] = bl_instruction(overlay.HOOK_CODE_ADDRESS + len(code) - 12, 0x02000000)
    monkeypatch.setattr(overlay, "HOOK_CODE", bytes(code))
    with pytest.raises(ClassicRetroError) as caught:
        overlay.hooked_arm9(parts.arm9)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_originals_are_extracted_and_verified():
    rom, layout = _synthetic()
    originals = overlay.extract_originals(
        rom, messages=_messages(), layout=layout, verify_identity=False
    )
    assert originals == {"once": TEXTS[0], "name": TEXTS[1]}


def _corrupted(rom: bytes, offset: int, data: bytes) -> bytes:
    image = bytearray(rom)
    image[offset : offset + len(data)] = data
    set_header_crc(image)
    return bytes(image)


def test_a_different_image_or_script_is_refused(tmp_path):
    rom, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_ph_arabic_rom(rom, tmp_path / "font.ttf", messages=_messages())
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    refused = [
        dataclasses.replace(layout, font_sha256="0" * 64),
        dataclasses.replace(layout, messages_sha256="0" * 64),
        dataclasses.replace(layout, hook_room_sha256="0" * 64),
        dataclasses.replace(layout, anchors={**layout.anchors, overlay.DRAW_CHAR: bytes(16)}),
        dataclasses.replace(layout, overlay_table=layout.overlay_table + 0x200),
    ]
    for wrong in refused:
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_parts(rom, wrong)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    message = _messages()[0]
    changed = dataclasses.replace(message, source_sha256="0" * 64)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(changed,), layout=layout, verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    # The ARM9 changed, or its padding before the overlay table.
    size = layout.arm9_size
    for offset in (0x4000 + 0x5000, 0x4000 + size + len(FOOTER) + 4):
        with pytest.raises(ClassicRetroError) as caught:
            overlay.read_parts(_corrupted(rom, offset, b"\x00"), layout)
        assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_a_glyph_call_that_is_no_bl_to_draw_char_is_refused():
    rom, layout = _synthetic()
    arm9 = _arm9()
    site = overlay.GLYPH_SITE - overlay.ARM9_RAM
    arm9[site : site + 4] = bl_instruction(overlay.GLYPH_SITE, overlay.DRAW_CHAR + 4)
    stored = bytearray(compress_blz(bytes(arm9)))
    for binary in (arm9, stored):
        struct.pack_into("<I", binary, overlay.PACKED_END, overlay.ARM9_RAM + len(stored))
    image = bytearray(rom)
    image[0x4000 : layout.overlay_table] = b"\xff" * (layout.overlay_table - 0x4000)
    image[0x4000 : 0x4000 + len(stored)] = stored
    footer_at = 0x4000 + len(stored)
    image[footer_at : footer_at + len(FOOTER)] = FOOTER
    struct.pack_into("<I", image, 0x2C, len(stored))
    set_header_crc(image)
    wrong = dataclasses.replace(
        layout,
        arm9_size=len(stored),
        arm9_stored_sha256=hashlib.sha256(stored).hexdigest(),
        arm9_sha256=hashlib.sha256(arm9).hexdigest(),
    )
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_parts(bytes(image), wrong)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert "glyph call" in str(caught.value)


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_the_stored_hook_matches_its_source():
    assert overlay.check_hook_code()["match"] is True


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["phantom-hourglass", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 7 and report["lines_measured"] is False
    assert main(["phantom-hourglass", "encode-arabic", "بب ب{01:0A000800}."]) == 0
    encoded = json.loads(capsys.readouterr().out)
    # Four letters and a space, the pause (4 units) and the stop.
    assert encoded["units"] == 4 + 4 + 1 and "widths" not in encoded
