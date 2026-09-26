"""The DS image's ARM9 binary, overlay table and NARC rebuilding (``patching.nitro``).

The image is built here and holds no game data: a header, a small NitroSDK ARM9
binary with an ITCM and a DTCM autoload block, two overlays, an ARM7 binary, a
file system of two files, then free space (0xFF) to the image's end.
"""

from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching.nitro import (
    ARM9_OVERLAY_TABLE,
    NITROCODE,
    SIGNATURE_MAGIC,
    USED_SIZE,
    Arm9Binary,
    Autoload,
    Narc,
    NdsHeader,
    NitroImage,
    header_crc_valid,
    move_arm9_overlay_table,
    replace_arm9,
    set_header_crc,
)

RAM = 0x02000000
PARAMS = 0x100
STATIC = 0x400
ITCM = Autoload(0x01FF8000, 0x40, 0)
DTCM = Autoload(0x027E0000, 0x20, 0x20)
IMAGE_SIZE = 0x10000
OVERLAYS = (b"\x01" * 0x40, b"\x02" * 0x30)
# By file id: the overlays are files 0 and 1.
FILES = {"y.bin": (2, b"why" * 50), "a/x.bin": (3, b"ex" * 300)}


def _align(offset: int) -> int:
    return (offset + 0x1FF) & ~0x1FF


def _arm9() -> bytes:
    """Static code, then the two blocks' data, then their table (the params point at it)."""
    data = bytearray(bytes(range(256)) * (STATIC // 256))
    table = RAM + STATIC + ITCM.size + DTCM.size
    params = (table, table + 24, RAM + STATIC, 0x02100000, 0x02100100, 0, 0x05027531)
    struct.pack_into("<7I", data, PARAMS, *params)
    data += bytes(range(0x40, 0x40 + ITCM.size)) + bytes(range(0xA0, 0xA0 + DTCM.size))
    for block in (ITCM, DTCM):
        data += struct.pack("<III", block.address, block.size, block.bss)
    return bytes(data)


def _fnt(first: int) -> bytes:
    """The root holds y.bin and the directory a, which holds x.bin."""
    root = b"\x05y.bin" + b"\x81a" + struct.pack("<H", 0xF001) + b"\x00"
    directory = b"\x05x.bin\x00"
    table = 16
    header = struct.pack("<IHHIHH", table, first, 2, table + len(root), first + 1, 0xF000)
    return header + root + directory


def _image(*, signature: bool = False) -> bytearray:
    image = bytearray(b"\xff" * IMAGE_SIZE)
    image[:0x4000] = bytes(0x4000)
    position = 0x4000

    def place(data: bytes) -> int:
        nonlocal position
        start = position
        image[start : start + len(data)] = data
        position = _align(start + len(data))
        return start

    arm9 = _arm9()
    arm9_at = place(arm9 + struct.pack("<III", NITROCODE, PARAMS, 0))
    table = b"".join(
        struct.pack("<8I", number, 0x02100000, len(data), 0, 0, 0, number, 0)
        for number, data in enumerate(OVERLAYS)
    )
    table_at = place(table)
    contents = dict(enumerate(OVERLAYS))
    starts = {number: place(data) for number, data in contents.items()}
    arm7 = bytes(range(0x100))
    arm7_at = place(arm7)
    fnt = _fnt(2)
    fnt_at = place(fnt)
    fat_at = place(bytes(8 * (len(OVERLAYS) + len(FILES))))
    for file_id, data in FILES.values():
        contents[file_id] = data
        starts[file_id] = place(data)
    for file_id, data in contents.items():
        start = starts[file_id]
        struct.pack_into("<II", image, fat_at + 8 * file_id, start, start + len(data))
    used = max(starts[file_id] + len(data) for file_id, data in contents.items())
    if signature:
        image[used : used + 0x88] = SIGNATURE_MAGIC + bytes(range(0x84))

    image[0:12] = b"CLASSICRETRO"
    image[12:16] = b"CRTE"
    image[16:18] = b"01"
    struct.pack_into("<4I", image, 0x20, arm9_at, RAM, RAM, len(arm9))
    struct.pack_into("<4I", image, 0x30, arm7_at, 0x02380000, 0x02380000, len(arm7))
    struct.pack_into("<4I", image, 0x40, fnt_at, len(fnt), fat_at, 8 * len(contents))
    struct.pack_into("<4I", image, 0x50, table_at, len(table), 0, 0)
    struct.pack_into("<I", image, USED_SIZE, used)
    struct.pack_into("<H", image, 0x15C, 0xCF56)
    set_header_crc(image)
    return image


@pytest.fixture(scope="module")
def rom() -> bytes:
    return bytes(_image())


def test_the_image_gives_its_arm9_overlays_and_parts(rom):
    image = NitroImage(rom)
    header = image.header
    assert (header.arm7_size, header.arm9_overlay_size, header.banner_offset) == (0x100, 64, 0)
    assert image.paths == {path: file_id for path, (file_id, _) in FILES.items()}
    for path, (file_id, data) in FILES.items():
        assert image.read(path) == image.read(file_id) == data
    assert image.arm9() == _arm9()
    assert struct.unpack_from("<II", image.arm9_footer()) == (NITROCODE, PARAMS)
    overlays = image.overlays()
    assert [(overlay.id, overlay.size, overlay.file_id) for overlay in overlays] == [
        (0, 0x40, 0),
        (1, 0x30, 1),
    ]
    assert image.read(overlays[1].file_id) == OVERLAYS[1]
    # After the ARM9 comes the overlay table, then the first overlay's file.
    assert image.next_region(header.arm9_offset) == header.arm9_overlay_offset
    assert image.next_region(header.arm9_overlay_offset) == image.file_range(0)[0]
    assert image.next_region(image.file_range(3)[0]) == header.used_size
    broken = bytearray(rom)
    broken[header.arm9_offset + header.arm9_size] ^= 1
    assert NitroImage(bytes(broken)).arm9_footer() == b""


def test_the_arm9_autoload_blocks_are_read(rom):
    arm9 = Arm9Binary.from_image(NitroImage(rom))
    assert arm9.autoloads() == (ITCM, DTCM)
    assert arm9.autoload_start == RAM + STATIC
    assert arm9.autoload_table == (RAM + STATIC + 0x60, RAM + STATIC + 0x78)
    assert arm9.block_data_offset(1) == STATIC + ITCM.size
    assert arm9.read(RAM + STATIC, 2) == b"\x40\x41"
    with pytest.raises(ClassicRetroError) as caught:
        arm9.read(RAM - 2, 2)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_an_autoload_block_grows_and_the_rest_follows(rom):
    arm9 = Arm9Binary.from_image(NitroImage(rom))
    grown = arm9.with_block_grown(0, b"HOOK" * 4)
    assert grown.autoloads() == (Autoload(ITCM.address, ITCM.size + 16, 0), DTCM)
    assert grown.autoload_table == tuple(address + 16 for address in arm9.autoload_table)
    # The block keeps its bytes; the new ones follow; the next block moved with its data.
    start = grown.block_data_offset(0)
    assert grown.data[start : start + ITCM.size] == arm9.data[start : start + ITCM.size]
    assert grown.data[start + ITCM.size : start + ITCM.size + 16] == b"HOOK" * 4
    dtcm = grown.block_data_offset(1)
    assert grown.data[dtcm : dtcm + DTCM.size] == bytes(range(0xA0, 0xC0))
    assert grown.data[:PARAMS] == arm9.data[:PARAMS]
    # A block with a BSS would move the BSS over what follows it.
    with pytest.raises(ClassicRetroError) as caught:
        arm9.with_block_grown(1, b"\0" * 4)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


def test_only_the_static_code_is_patched(rom):
    arm9 = Arm9Binary.from_image(NitroImage(rom))
    patched = arm9.patched({RAM + 0x10: b"\xbe\xef"})
    assert patched.read(RAM + 0x10, 2) == b"\xbe\xef" and patched.autoloads() == (ITCM, DTCM)
    with pytest.raises(ClassicRetroError) as caught:
        arm9.patched({RAM + STATIC - 1: b"\x01\x02"})
    assert caught.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS


@pytest.mark.parametrize("damage", ["footer", "compressed", "table"])
def test_an_arm9_binary_the_toolkit_cannot_read_is_refused(rom, damage):
    header = NdsHeader.read(rom)
    broken = bytearray(rom)
    arm9 = header.arm9_offset
    if damage == "footer":
        broken[arm9 + header.arm9_size] ^= 1
    elif damage == "compressed":
        struct.pack_into("<I", broken, arm9 + PARAMS + 20, RAM + 0x300)
    else:
        struct.pack_into("<I", broken, arm9 + PARAMS + 8, RAM + STATIC + 4)
    with pytest.raises(ClassicRetroError) as caught:
        Arm9Binary.from_image(NitroImage(bytes(broken)))
    assert caught.value.code is ErrorCode.INVALID_BYTE_RANGE


@pytest.mark.parametrize("signature", [False, True])
def test_the_arm9_grows_into_the_room_the_overlay_table_leaves(signature):
    image = _image(signature=signature)
    before = NitroImage(bytes(image))
    used = before.header.used_size
    kept = bytes(image[used : used + 0x88])
    grown = Arm9Binary.from_image(before).with_block_grown(0, bytes(0x200))
    with pytest.raises(ClassicRetroError) as caught:
        replace_arm9(image, grown.data)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    assert bytes(image) == bytes(_image(signature=signature))

    moved = move_arm9_overlay_table(image)
    assert moved == _align(used) and header_crc_valid(image)
    assert struct.unpack_from("<I", image, ARM9_OVERLAY_TABLE)[0] == moved
    after_move = NitroImage(bytes(image))
    assert after_move.overlays() == before.overlays()
    assert after_move.header.used_size == moved + 64
    if signature:
        # The signature follows the used area.
        assert image[moved + 64 : moved + 64 + 0x88] == kept
    replace_arm9(image, grown.data)
    after = NitroImage(bytes(image))
    assert header_crc_valid(image) and after.header.arm9_size == len(grown.data)
    assert Arm9Binary.from_image(after).data == grown.data
    assert after.arm9_footer() == before.arm9_footer()
    assert after.read(0) == OVERLAYS[0] and after.read("a/x.bin") == FILES["a/x.bin"][1]
    # The binary may not reach the next file, even with the table moved.
    with pytest.raises(ClassicRetroError) as caught:
        replace_arm9(image, Arm9Binary.from_image(before).with_block_grown(0, bytes(0x800)).data)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    # A smaller binary leaves padding behind its footer.
    replace_arm9(image, _arm9())
    end = after.header.arm9_offset + len(_arm9()) + 12
    assert set(image[end : end + 0x200]) == {0xFF} and NitroImage(bytes(image)).arm9() == _arm9()


def test_the_overlay_table_needs_room_in_the_image(rom):
    image = bytearray(rom[: NdsHeader.read(rom).used_size + 0x10])
    with pytest.raises(ClassicRetroError) as caught:
        move_arm9_overlay_table(image)
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW


# ---------------------------------------------------------------------------
# NARC archives


def _narc(members: list[bytes], *, prefix: bytes = b"") -> bytes:
    """``prefix``, then a NARC of ``members`` without names, each 4-byte aligned."""
    data = bytearray()
    ranges = []
    for member in members:
        data += b"\xff" * (-len(data) % 4)
        ranges.append((len(data), len(data) + len(member)))
        data += member
    data += b"\xff" * (-len(data) % 4)
    table = struct.pack("<HH", len(members), 0) + b"".join(struct.pack("<II", *r) for r in ranges)
    names = struct.pack("<IHH", 4, 0, 1)
    blocks = b"".join(
        magic + struct.pack("<I", 8 + len(body)) + body
        for magic, body in ((b"BTAF", table), (b"BTNF", names), (b"GMIF", bytes(data)))
    )
    return prefix + b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x100, 16 + len(blocks), 16, 3) + blocks


MEMBERS = [b"alpha", b"bravo!!!", b"cha"]


def test_a_narc_gives_its_members_and_is_rebuilt_unchanged():
    data = _narc(MEMBERS, prefix=b"ab")
    archive = Narc.read(data, 2)
    assert [archive.member(data, index) for index in range(3)] == MEMBERS
    assert archive.rebuilt(data, {}) == data[2:]
    assert archive.ranges == ((0, 5), (8, 16), (16, 19))


def test_a_replaced_member_leaves_the_others_in_place():
    data = _narc(MEMBERS)
    archive = Narc.read(data)
    shorter = archive.rebuilt(data, {1: b"b"})
    rebuilt = Narc.read(shorter)
    assert rebuilt.ranges == ((0, 5), (8, 9), (16, 19)) and len(shorter) == len(data)
    assert shorter[rebuilt.data_offset + 9 : rebuilt.data_offset + 16] == b"\xff" * 7
    fits = Narc.read(archive.rebuilt(data, {0: b"ALPHA!!!"}))
    assert fits.ranges[0] == (0, 8)
    # Too long for its place: after the last member, the old place kept.
    longer = archive.rebuilt(data, {0: b"a much longer alpha", 2: b"C"})
    again = Narc.read(longer)
    assert again.ranges == ((20, 39), (8, 16), (16, 17))
    assert [again.member(longer, index) for index in range(3)] == [
        b"a much longer alpha",
        b"bravo!!!",
        b"C",
    ]
    assert struct.unpack_from("<I", longer, 8)[0] == len(longer) and len(longer) % 4 == 0
    with pytest.raises(ClassicRetroError) as caught:
        archive.rebuilt(data, {3: b""})
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_a_narc_whose_data_is_not_last_is_not_rebuilt():
    data = bytearray(_narc(MEMBERS))
    # One more block's worth of bytes after the data, counted in the archive's size.
    data += b"\0" * 8
    struct.pack_into("<I", data, 8, len(data))
    with pytest.raises(ClassicRetroError) as caught:
        Narc.read(bytes(data)).rebuilt(bytes(data), {0: b"a"})
    assert caught.value.code is ErrorCode.CONTAINER_REBUILD_FAILED
