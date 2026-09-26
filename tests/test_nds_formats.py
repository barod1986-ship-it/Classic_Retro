from __future__ import annotations

import random
import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.nftr import GlyphWidth, NftrFont
from classic_retro.patching.nitro import (
    FILE_ALIGNMENT,
    SIGNATURE_MAGIC,
    Narc,
    NdsHeader,
    NitroImage,
    crc16,
    file_name_table,
    header_crc_valid,
    replace_files,
    secure_area_crc,
    set_header_crc,
)
from classic_retro.rebuild.blz import (
    compress_blz,
    decompress_blz,
    decompress_blz_in_place,
    repack_blz,
)
from classic_retro.rebuild.lz77 import compress_lz77, compress_lz77_optimal, decompress_lz77
from classic_retro.rebuild.lz_parse import longest_matches
from classic_retro.text.bmg import Bmg, BmgEscape, decode_text, encode_text


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
    main = bytearray()
    offset = 8 * len(directories)
    for number, table in enumerate(tables):
        parent = len(directories) if number == 0 else 0xF000
        main += struct.pack("<IHH", offset, first_ids[number], parent)
        offset += len(table)
    return bytes(main) + b"".join(tables)


def _image(files: dict[str, bytes], *, size: int = 0x20000) -> bytearray:
    """A small DS image: a header, an FNT and FAT for ``files`` under script/, the files."""
    image = bytearray(b"\xff" * size)
    image[:0x200] = bytes(0x200)
    image[0:12] = b"CLASSICRETRO"
    image[12:16] = b"CRTE"
    fnt = _fnt({"script": list(files)})
    fnt_at, fat_at, data_at = 0x1000, 0x2000, 0x3000
    image[fnt_at : fnt_at + len(fnt)] = fnt
    position = data_at
    for number, data in enumerate(files.values()):
        image[position : position + len(data)] = data
        struct.pack_into("<II", image, fat_at + 8 * number, position, position + len(data))
        position += len(data)
    struct.pack_into("<4I", image, 0x40, fnt_at, len(fnt), fat_at, 8 * len(files))
    struct.pack_into("<I", image, 0x80, position)
    image[position : position + 0x88] = SIGNATURE_MAGIC + bytes(range(0x84))
    struct.pack_into("<H", image, 0x15C, 0xCF56)
    set_header_crc(image)
    return image


def test_crc16_is_the_modbus_variant():
    assert crc16(b"123456789") == 0x4B37


def test_the_secure_area_crc_follows_a_change_without_the_encryption():
    original = bytes(random.Random(3).randbytes(0x9000))
    changed = bytearray(original)
    changed[0x4B5C:0x4B60] = b"\x12\x34\x56\x78"
    stored = crc16(original[0x4000:0x8000])
    assert secure_area_crc(original, bytes(changed), stored) == crc16(changed[0x4000:0x8000])
    changed[0x4010] ^= 1
    with pytest.raises(ClassicRetroError) as caught:
        secure_area_crc(original, bytes(changed), stored)
    assert caught.value.code is ErrorCode.BUILD_VALIDATION_FAILED


def test_file_name_table_gives_paths_their_ids():
    table = _fnt({"a": {"b": ["x.bin", "y.bin"]}, "c": ["z.bin"]})
    assert file_name_table(table) == {"a/b/x.bin": 0, "a/b/y.bin": 1, "c/z.bin": 2}


def test_a_nitro_image_reads_its_header_and_files():
    image = _image({"one.bin": b"first", "two.bin": b"second!"})
    nitro = NitroImage(bytes(image))
    assert header_crc_valid(image)
    assert (nitro.header.title, nitro.header.game_code) == ("CLASSICRETRO", "CRTE")
    assert nitro.paths == {"script/one.bin": 0, "script/two.bin": 1}
    assert nitro.read("script/two.bin") == b"second!"
    with pytest.raises(ClassicRetroError) as caught:
        nitro.file_id("script/three.bin")
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_replaced_files_stay_in_place_or_move_past_the_used_area():
    image = _image({"one.bin": b"first", "two.bin": b"second!"})
    used = NdsHeader.read(image).used_size
    signature = bytes(image[used : used + 0x88])
    placed = replace_files(image, {0: b"1st", 1: b"a longer second file"})
    nitro = NitroImage(bytes(image))
    assert nitro.read("script/one.bin") == b"1st"
    assert image[placed[0][1] : placed[0][1] + 2] == b"\xff\xff"
    start, end = placed[1]
    assert start == -(-used // FILE_ALIGNMENT) * FILE_ALIGNMENT
    assert nitro.read("script/two.bin") == b"a longer second file"
    assert NdsHeader.read(image).used_size == end
    assert image[end : end + 0x88] == signature
    assert image[used : used + 4] == b"\xff" * 4
    assert header_crc_valid(image)


def _narc(files: dict[str, bytes]) -> bytes:
    """A NARC holding ``files`` under message/, each 4-aligned."""
    data = bytearray()
    ranges = []
    for content in files.values():
        ranges.append((len(data), len(data) + len(content)))
        data += content + b"\xff" * (-len(content) % 4)
    fat = struct.pack("<HH", len(files), 0) + b"".join(struct.pack("<II", *r) for r in ranges)
    names = _fnt({"message": list(files)})
    names += bytes(-len(names) % 4)
    blocks = (
        b"BTAF" + struct.pack("<I", 8 + len(fat)) + fat,
        b"BTNF" + struct.pack("<I", 8 + len(names)) + names,
        b"GMIF" + struct.pack("<I", 8 + len(data)) + bytes(data),
    )
    body = b"".join(blocks)
    return b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x100, 16 + len(body), 16, 3) + body


def test_a_narc_gives_its_files_ranges_room_and_new_ends():
    archive_data = b"\x00" * 6 + _narc({"a.bin": b"abcde", "b.bin": b"xyz"})
    archive = Narc.read(archive_data, 6)
    start, end = archive.file_range("message/a.bin")
    assert archive_data[start:end] == b"abcde"
    assert archive.room("message/a.bin") == 8
    assert archive.room("message/b.bin") == 4
    changed = bytearray(archive_data)
    archive.set_end(changed, "message/a.bin", start + 2)
    assert Narc.read(bytes(changed), 6).file_range("message/a.bin") == (start, start + 2)
    with pytest.raises(ClassicRetroError):
        Narc.read(archive_data, 0)


def _binary() -> bytes:
    """A binary with some structure: code-like words, text and a run."""
    rng = random.Random(11)
    words = [rng.randrange(1 << 32) for _ in range(64)]
    body = b"".join(struct.pack("<I", rng.choice(words)) for _ in range(12000))
    return bytes(rng.randbytes(0x4000)) + body + b"invented table " * 40 + bytes(600)


def test_blz_round_trips_and_decompresses_in_place():
    data = _binary()
    packed = compress_blz(data)
    assert len(packed) % 4 == 0 and len(packed) < len(data)
    assert packed[:0x4000] == data[:0x4000]
    assert decompress_blz(packed) == data
    assert decompress_blz_in_place(packed) == data


def test_blz_leaves_what_it_cannot_shrink_as_it_is():
    data = bytes(random.Random(5).randbytes(600))
    assert compress_blz(data, stored=0) == data


def test_a_broken_blz_footer_is_refused():
    packed = bytearray(compress_blz(_binary()))
    packed[-8:-4] = struct.pack("<I", 0x0F000000 | len(packed) + 10)
    with pytest.raises(ClassicRetroError) as caught:
        decompress_blz(bytes(packed))
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED


def test_a_repacked_binary_keeps_the_original_where_it_did_not_change():
    data = _binary()
    original = compress_blz(data)
    changed = bytearray(data)
    changed[0xA000:0xA040] = bytes(range(64))
    changed[0xB000] ^= 0xFF
    repacked = repack_blz(original, bytes(changed))
    assert decompress_blz_in_place(repacked) == bytes(changed)
    # The part stored as it is, and the items decoded last (the binary's start),
    # stay byte for byte.
    common = next(i for i in range(len(repacked)) if repacked[i] != original[i])
    assert common > 0x4000 + (len(original) - 0x4000) // 4
    # The items decoded first sit, unchanged, just before the footer.
    assert repacked[-200:-16] in original
    with pytest.raises(ClassicRetroError) as caught:
        repack_blz(original, bytes(changed) + b"\x00")
    assert caught.value.code is ErrorCode.COMPRESSION_ROUNDTRIP_FAILED


def test_optimal_lz77_never_loses_to_greedy_and_stays_vram_safe():
    rng = random.Random(9)
    data = bytes(rng.choice(b"\x00\x01\x11\x10") for _ in range(4000)) + b"\x11" * 300
    optimal = compress_lz77_optimal(data)
    assert decompress_lz77(optimal) == data
    assert len(optimal) <= len(compress_lz77(data))
    assert len(optimal) % 4 == 0
    unsafe = compress_lz77_optimal(data, vram_safe=False)
    assert decompress_lz77(unsafe) == data and len(unsafe) <= len(optimal)


def test_matches_end_with_their_segment():
    data = b"abcabcabcabc"
    assert longest_matches(data, min_distance=3, max_distance=100, start=3, end=9) == [
        6,
        5,
        4,
        3,
        0,
        0,
    ]


def _nftr(codes: list[int], *, cmap_kind: int = 2) -> bytes:
    """An 11x15, 2-bit font with a blank glyph for each code, in order."""
    count = len(codes)
    info_size, glyph_bytes = 0x1C, 42
    cglp_at = 16 + info_size
    cglp = struct.pack("<BBHBBBB", 11, 15, glyph_bytes, 13, 11, 2, 0) + bytes(glyph_bytes * count)
    cglp = b"PLGC" + struct.pack("<I", 8 + len(cglp)) + cglp
    cwdh_at = cglp_at + len(cglp)
    widths = b"".join(struct.pack("<bBB", 0, 5, 6) for _ in range(count))
    cwdh = struct.pack("<HHI", 0, count - 1, 0) + widths
    cwdh += bytes(-len(cwdh) % 4)
    cwdh = b"HDWC" + struct.pack("<I", 8 + len(cwdh)) + cwdh
    cmap_at = cwdh_at + len(cwdh)
    if cmap_kind == 2:
        table = struct.pack("<H", count) + b"".join(
            struct.pack("<HH", code, glyph) for glyph, code in enumerate(codes)
        )
        cmap = struct.pack("<HHHHI", 0, 0xFFFF, 2, 0, 0) + table
    else:
        cmap = struct.pack("<HHHHI", codes[0], codes[-1], 0, 0, 0) + struct.pack("<H", 0)
    cmap += bytes(-len(cmap) % 4)
    cmap = b"PAMC" + struct.pack("<I", 8 + len(cmap)) + cmap
    info = struct.pack("<BBHbBBBIII", 0, 15, 0, 0, 11, 11, 1, cglp_at + 8, cwdh_at + 8, cmap_at + 8)
    info = b"FNIF" + struct.pack("<I", 8 + len(info)) + info
    body = info + cglp + cwdh + cmap
    return b"RTFN" + struct.pack("<HHIHH", 0xFEFF, 0x100, 16 + len(body), 16, 4) + body


def test_an_nftr_font_reads_and_replaces_glyphs_in_place():
    data = _nftr([0x20, 0x41, 0x3042])
    font = NftrFont(data)
    assert (font.cell_width, font.cell_height, font.bits, font.glyph_count) == (11, 15, 2, 3)
    assert font.codes == {0x20: 0, 0x41: 1, 0x3042: 2}
    assert font.width(1) == GlyphWidth(0, 5, 6)
    rows = tuple(tuple((x + y) % 4 if x < 7 else 0 for x in range(11)) for y in range(15))
    font.set_glyph(2, rows, GlyphWidth(0, 7, 8))
    again = NftrFont(font.to_bytes())
    assert again.glyph(2) == rows and again.width(2) == GlyphWidth(0, 7, 8)
    assert again.glyph(1) == tuple((0,) * 11 for _ in range(15))
    assert len(font.to_bytes()) == len(data)
    assert NftrFont(_nftr([0x30, 0x31, 0x32], cmap_kind=0)).codes == {0x30: 0, 0x31: 1, 0x32: 2}
    with pytest.raises(ClassicRetroError) as caught:
        font.set_glyph(0, rows[:3], GlyphWidth(0, 1, 1))
    assert caught.value.code is ErrorCode.INVALID_FONT_PROFILE
    with pytest.raises(ClassicRetroError):
        NftrFont(b"NOPE" + data[4:])


def _bmg(texts: list[str | tuple]) -> Bmg:
    return Bmg(
        header_tail=bytes((2,)) + bytes(15),
        info_field=0,
        attributes=tuple(b"" for _ in texts),
        texts=tuple(text if isinstance(text, tuple) else (text,) for text in texts),
    )


def test_bmg_files_rebuild_byte_for_byte():
    colour = BmgEscape(0xFF, bytes.fromhex("00000100"))
    number = BmgEscape(0x01, bytes.fromhex("0100"))
    data = _bmg(["Yes", "Two\nlines", ("Pay ", colour, number, " now")]).build()
    assert data[:8] == b"MESGbmg1" and len(data) % 32 == 0
    parsed = Bmg.parse(data)
    assert parsed.texts[2] == ("Pay ", colour, number, " now")
    assert parsed.build() == data
    changed = parsed.with_texts([("A",), ("B",), ("C",)]).build()
    assert Bmg.parse(changed).texts == (("A",), ("B",), ("C",))
    assert colour.notation == "{FF:00000100}"
    assert decode_text(encode_text(("x", number)) + b"\x00\x00", 0)[0] == ("x", number)
    with pytest.raises(ClassicRetroError) as caught:
        encode_text(("a\x00b",))
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
    with pytest.raises(ClassicRetroError):
        parsed.with_texts([("A",)])
