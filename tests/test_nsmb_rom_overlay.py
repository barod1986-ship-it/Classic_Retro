from __future__ import annotations

import hashlib
import json
import random
import struct

import pytest

from classic_retro.arabic.glyph_codes import GlyphCodes
from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.nsmb import FONT_FILE, notation_skeleton, parse_notation
from classic_retro.engines.nsmb_arabic import (
    ARABIC_CODES,
    BASELINE,
    SPACE_WIDTH,
    NsmbArabicEncoder,
    NsmbArabicFont,
    nsmb_glyph,
)
from classic_retro.font.nftr import GlyphWidth, NftrFont
from classic_retro.patching.nitro import (
    SIGNATURE_MAGIC,
    Narc,
    NdsHeader,
    NitroImage,
    header_crc_valid,
    secure_area_crc,
    set_header_crc,
)
from classic_retro.rebuild.blz import compress_blz, decompress_blz_in_place
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rebuild.lz77 import compress_lz77, decompress_lz77
from classic_retro.rom import nsmb_arabic as overlay
from classic_retro.rom.nsmb_arabic_script import NsmbArabicMessage
from classic_retro.text.bmg import Bmg, encode_text

# Invented English messages of the three files, and the translated ones.
FILES = {
    "script/course.bmg": ["Yes", "No", "Pay {FF:00000100}{01:0100}{FF:00000000} shells\nto pass?"],
    "script/data.bmg": ["Pick a slot."],
    "script/game.bmg": ["Go on\n{FF:00000200}Back\n{FF:00000000}Stop", "Left alone."],
}
ARABIC = {
    "pay": ("script/course.bmg", 2, "ادفع {FF:00000100}{01:0100}{FF:00000000} صدفات\nلتعبر؟"),
    "pick": ("script/data.bmg", 0, "اختر خانة من الخانات الثلاث المتاحة الآن."),
    "menu": ("script/game.bmg", 0, "تابع\n{FF:00000200}عودة\n{FF:00000000}توقف"),
}
FOOTER = struct.pack("<III", 0xDEC00621, overlay.MODULE_PARAMS, 0x1234)
IMAGE_SIZE = 0x100000


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
    """An 11x15, 2-bit font: a space, the kana codes and a few Latin letters, their glyphs
    noise (dense like the kana it stands for)."""
    codes = [0x20, *ARABIC_CODES, *range(0x41, 0x5B)]
    count = len(codes)
    glyph_bytes = 42
    cglp_at = 16 + 0x1C
    glyphs = random.Random(4).randbytes(glyph_bytes * count)
    cglp = struct.pack("<BBHBBBB", 11, 15, glyph_bytes, 13, 11, 2, 0) + glyphs
    cglp = b"PLGC" + struct.pack("<I", 8 + len(cglp)) + cglp
    cwdh_at = cglp_at + len(cglp)
    cwdh = struct.pack("<HHI", 0, count - 1, 0) + struct.pack("<bBB", 0, 7, 7) * count
    cwdh += bytes(-len(cwdh) % 4)
    cwdh = b"HDWC" + struct.pack("<I", 8 + len(cwdh)) + cwdh
    cmap_at = cwdh_at + len(cwdh)
    pairs = b"".join(struct.pack("<HH", code, glyph) for glyph, code in enumerate(codes))
    cmap = struct.pack("<HHHHI", 0, 0xFFFF, 2, 0, 0) + struct.pack("<H", count) + pairs
    cmap += bytes(-len(cmap) % 4)
    cmap = b"PAMC" + struct.pack("<I", 8 + len(cmap)) + cmap
    info = struct.pack("<BBHbBBBIII", 0, 15, 0, 0, 11, 11, 1, cglp_at + 8, cwdh_at + 8, cmap_at + 8)
    info = b"FNIF" + struct.pack("<I", 8 + len(info)) + info
    body = info + cglp + cwdh + cmap
    return b"RTFN" + struct.pack("<HHIHH", 0xFEFF, 0x100, 16 + len(body), 16, 4) + body


def _narc(files: dict[str, bytes], room: int) -> bytes:
    """A NARC with ``files`` under message/common/USA, each followed by ``room`` spare bytes."""
    data = bytearray()
    ranges = []
    for content in files.values():
        ranges.append((len(data), len(data) + len(content)))
        data += content + b"\xff" * (-len(content) % 4 + room)
    fat = struct.pack("<HH", len(files), 0) + b"".join(struct.pack("<II", *r) for r in ranges)
    names = _fnt({"message": {"common": {"USA": [name.split("/")[-1] for name in files]}}})
    names += bytes(-len(names) % 4)
    body = (
        b"BTAF" + struct.pack("<I", 8 + len(fat)) + fat
        + b"BTNF" + struct.pack("<I", 8 + len(names)) + names
        + b"GMIF" + struct.pack("<I", 8 + len(data)) + bytes(data)
    )  # fmt: skip
    return b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x100, 16 + len(body), 16, 3) + body


def _arm9() -> tuple[bytes, int]:
    """An unpacked ARM9: start-up code with its module parameters, code, the NARC, code."""
    rng = random.Random(21)
    words = [rng.randrange(1 << 32) for _ in range(48)]
    start = bytearray(rng.randbytes(0x4000))
    struct.pack_into(
        "<7I", start, overlay.MODULE_PARAMS, *(rng.randrange(1 << 32) for _ in range(7))
    )
    start[overlay.MODULE_PARAMS + 0x1C : overlay.MODULE_PARAMS + 0x24] = overlay.NITROCODE
    code = b"".join(struct.pack("<I", rng.choice(words)) for _ in range(0x1000))
    packed_font = b"LZ77" + compress_lz77(_font())
    archive = _narc({FONT_FILE: packed_font, "message/common/USA/font_b.NFTR": b"other"}, 0x800)
    archive_at = len(start) + len(code)
    return bytes(start) + code + archive + code[:0x2000], archive_at


def _bmg(texts: list[str]) -> bytes:
    return Bmg(
        header_tail=bytes((2,)) + bytes(15),
        info_field=0,
        attributes=tuple(b"" for _ in texts),
        texts=tuple(parse_notation(text) for text in texts),
    ).build()


def _synthetic() -> tuple[bytes, overlay.NsmbLayout]:
    """A DS image with the parts the overlay reads, and the layout that pins them."""
    arm9, archive_at = _arm9()
    stored = bytearray(compress_blz(arm9))
    arm9 = bytearray(arm9)
    for binary in (arm9, stored):
        struct.pack_into("<I", binary, overlay.PACKED_END, overlay.ARM9_RAM + len(stored))
    image = bytearray(b"\xff" * IMAGE_SIZE)
    image[:0x4000] = bytes(0x4000)
    image[0:12] = b"CLASSICRETRO"
    image[12:16] = b"CRTE"
    image[0x4000 : 0x4000 + len(stored)] = stored
    footer_at = 0x4000 + len(stored)
    image[footer_at : footer_at + len(FOOTER)] = FOOTER
    struct.pack_into("<4I", image, 0x20, 0x4000, 0x02000800, overlay.ARM9_RAM, len(stored))
    fnt = _fnt({"script": [path.split("/")[1] for path in FILES]})
    fnt_at, fat_at, data_at = 0x40000, 0x41000, 0x50000
    image[fnt_at : fnt_at + len(fnt)] = fnt
    struct.pack_into("<4I", image, 0x40, fnt_at, len(fnt), fat_at, 8 * len(FILES))
    struct.pack_into("<I", image, 0x50, footer_at + len(FOOTER))
    position = data_at
    digests = {}
    for number, (path, texts) in enumerate(FILES.items()):
        data = _bmg(texts)
        digests[path] = hashlib.sha256(data).hexdigest()
        image[position : position + len(data)] = data
        struct.pack_into("<II", image, fat_at + 8 * number, position, position + len(data))
        position += len(data)
    struct.pack_into("<I", image, 0x80, position)
    image[position : position + 0x88] = SIGNATURE_MAGIC + bytes(range(0x84))
    struct.pack_into("<H", image, 0x6C, 0x1357)
    struct.pack_into("<H", image, 0x15C, 0xCF56)
    set_header_crc(image)
    font_start = Narc.read(bytes(arm9), archive_at).file_range(FONT_FILE)[0]
    layout = overlay.NsmbLayout(
        arm9_size=len(stored),
        arm9_stored_sha256=hashlib.sha256(stored).hexdigest(),
        arm9_sha256=hashlib.sha256(arm9).hexdigest(),
        arm9_footer=FOOTER,
        font_archive=archive_at,
        font_sha256=hashlib.sha256(_font()).hexdigest(),
        files=digests,
    )
    assert arm9[font_start : font_start + 4] == b"LZ77"
    return bytes(image), layout


def _messages() -> tuple[NsmbArabicMessage, ...]:
    messages = []
    for key, (path, index, arabic) in ARABIC.items():
        original = parse_notation(FILES[path][index])
        messages.append(
            NsmbArabicMessage(
                key=key,
                file=path,
                index=index,
                line_width=200,
                source_sha256=hashlib.sha256(encode_text(original)).hexdigest(),
                source_skeleton=notation_skeleton(original),
                notation=arabic,
            )
        )
    return tuple(messages)


def _fake_font(font_path=None, glyph_map: GlyphCodes | None = None, **_kwargs) -> NsmbArabicFont:
    """Every glyph a bar 5 pixels wide; the space is the real one."""
    assert glyph_map is not None
    bar = nsmb_glyph({(x, y) for x in range(4) for y in range(4, BASELINE)}, 5)
    glyphs = {}
    for character, codes in glyph_map.sequences.items():
        for code in codes:
            glyphs[code] = nsmb_glyph((), SPACE_WIDTH) if character == " " else bar
    return NsmbArabicFont(glyphs=glyphs, sequences=dict(glyph_map.sequences), font_size=12)


@pytest.fixture
def build(monkeypatch, tmp_path):
    monkeypatch.setattr(overlay, "build_nsmb_arabic_font", _fake_font)
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"not read by the fake font")
    rom, layout = _synthetic()
    result = overlay.build_nsmb_arabic_rom(
        rom, font_path, messages=_messages(), layout=layout, verify_identity=False
    )
    return rom, layout, result


def test_the_build_writes_the_font_the_files_and_a_patch(build):
    rom, layout, result = build
    output = result.rom
    assert apply_bps(result.patch.data, rom) == output
    assert header_crc_valid(output)
    header = NdsHeader.read(output)
    assert header.arm9_size <= layout.arm9_size
    stored = output[0x4000 : 0x4000 + header.arm9_size]
    assert output[0x4000 + header.arm9_size :][: len(FOOTER)] == FOOTER
    arm9 = decompress_blz_in_place(stored)
    packed_end = struct.unpack_from("<I", arm9, overlay.PACKED_END)[0]
    assert packed_end == overlay.ARM9_RAM + header.arm9_size
    # The font: the Arabic glyphs at the first kana, blank kana after them.
    start, end = Narc.read(arm9, layout.font_archive).file_range(FONT_FILE)
    font = NftrFont(decompress_lz77(arm9[start + 4 : end]))
    first = font.codes[ARABIC_CODES[0]]
    assert font.width(first) == GlyphWidth(0, SPACE_WIDTH, SPACE_WIDTH)
    second = font.codes[ARABIC_CODES[1]]
    assert font.width(second) == GlyphWidth(0, 5, 5)
    assert font.glyph(second)[BASELINE - 1][:5] == (1, 1, 1, 1, 0)
    assert font.width(font.codes[ARABIC_CODES[-1]]) == GlyphWidth(0, 0, 0)
    assert font.width(font.codes[0x41]) == GlyphWidth(0, 7, 7)
    # The files: translated messages in visual order, the others as they were.
    nitro = NitroImage(output)
    course = Bmg.parse(nitro.read("script/course.bmg"))
    assert course.texts[:2] == (("Yes",), ("No",))
    game = Bmg.parse(nitro.read("script/game.bmg"))
    assert game.texts[1] == ("Left alone.",)
    assert result.report["messages"] == 3


def test_translated_messages_read_back_as_encoded(build, monkeypatch):
    rom, _, result = build
    messages = _messages()
    glyph_map = overlay.script_glyph_codes(messages)
    encoder = NsmbArabicEncoder(glyph_map, _fake_font(glyph_map=glyph_map))
    nitro = NitroImage(result.rom)
    for message in messages:
        texts = Bmg.parse(nitro.read(message.file)).texts
        assert texts[message.index] == encoder.encode(message.pieces, 200).pieces


def test_a_file_that_grows_moves_past_the_used_area(build):
    rom, _, result = build
    before = NdsHeader.read(rom)
    after = NdsHeader.read(result.rom)
    nitro = NitroImage(result.rom)
    start, end = nitro.file_range(nitro.file_id("script/data.bmg"))
    assert start >= before.used_size and after.used_size == end
    assert result.rom[end : end + 4] == SIGNATURE_MAGIC
    assert result.report["message_files"]["script/data.bmg"] == f"{start:#x}"


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


def test_originals_are_extracted_and_verified(monkeypatch):
    rom, layout = _synthetic()
    originals = overlay.extract_originals(
        rom, messages=_messages(), layout=layout, verify_identity=False
    )
    assert originals["pay"] == FILES["script/course.bmg"][2]
    assert originals["pick"] == "Pick a slot."


def test_a_different_image_or_script_is_refused(monkeypatch, tmp_path):
    rom, layout = _synthetic()
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_nsmb_arabic_rom(rom, tmp_path / "font.ttf", messages=_messages())
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    wrong_font = overlay.NsmbLayout(**{**_layout_fields(layout), "font_sha256": "0" * 64})
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_parts(rom, wrong_font)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    message = _messages()[0]
    changed = NsmbArabicMessage(**{**_message_fields(message), "source_sha256": "0" * 64})
    with pytest.raises(ClassicRetroError) as caught:
        overlay.extract_originals(rom, messages=(changed,), layout=layout, verify_identity=False)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    corrupted = bytearray(rom)
    corrupted[0x4000 + 0x5000] ^= 0xFF
    set_header_crc(corrupted)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.read_parts(bytes(corrupted), layout)
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def _layout_fields(layout: overlay.NsmbLayout) -> dict:
    return {name: getattr(layout, name) for name in layout.__dataclass_fields__}


def _message_fields(message: NsmbArabicMessage) -> dict:
    return {name: getattr(message, name) for name in message.__dataclass_fields__}


def test_the_command_group_checks_and_encodes(capsys):
    assert main(["nsmb", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 42 and report["lines_measured"] is False
    assert main(["nsmb", "encode-arabic", "بب ب"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["units"] == 4 and "widths" not in encoded
