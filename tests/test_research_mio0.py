"""``research mio0`` and what the scanners make of a Nintendo 64 image, on synthetic images.

The images are built here from invented data: two blocks packed with
``compress_mio0`` among filler and a false magic, and an N64 image whose
header holds only the z64 magic.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from classic_retro.cli import main
from classic_retro.patching.n64 import MAGIC_Z64
from classic_retro.rebuild.mio0 import compress_mio0

FIRST = b"an invented line, an invented line, an invented line, and a last one"
SECOND = bytes(range(64)) * 3
FIRST_OFFSET = 0x20
FALSE_MAGIC_OFFSET = FIRST_OFFSET + len(compress_mio0(FIRST))
SECOND_OFFSET = FALSE_MAGIC_OFFSET + 16 + 5


def _image(path: Path) -> Path:
    """Two blocks among filler, a false magic between them and another after the second."""
    path.write_bytes(
        b"\xee" * FIRST_OFFSET
        + compress_mio0(FIRST)
        + b"MIO0 not a block"
        + b"\xff" * 5
        + compress_mio0(SECOND)
        + b"trailing bytes MIO0"
    )
    return path


def _n64_image(path: Path, order: str = "z64") -> Path:
    """An image of filler behind the z64 magic: a big-endian pointer table and a block.

    The filler is no pointer into the image, so the table is the only one. In
    the ``v64`` order the image is stored with the bytes of each halfword swapped.
    """
    image = bytearray(b"\xee" * 0x200)
    image[0:4] = MAGIC_Z64
    struct.pack_into(">6I", image, 0x100, *(0x40 + 8 * index for index in range(6)))
    block = compress_mio0(SECOND)
    image[0x140 : 0x140 + len(block)] = block
    if order == "v64":
        image = bytearray(b"".join(image[n : n + 2][::-1] for n in range(0, len(image), 2)))
    path.write_bytes(bytes(image))
    return path


def _run(capsys, *arguments: str) -> dict:
    assert main(["research", *arguments]) == 0
    return json.loads(capsys.readouterr().out)


def _refused(capsys, code: str, *arguments: str) -> str:
    assert main(["research", *arguments]) == 2
    message = capsys.readouterr().err
    assert message.startswith(f"{code}: ")
    return message


def test_mio0_lists_every_block_with_its_sizes(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    report = _run(capsys, "mio0", str(image))
    assert (report["platform"], report["base"], report["size"]) == (
        None,
        "0x00000000",
        image.stat().st_size,
    )
    assert (report["count"], report["truncated"]) == (2, False)
    assert report["packed_bytes"] == len(compress_mio0(FIRST)) + len(compress_mio0(SECOND))
    assert report["unpacked_bytes"] == len(FIRST) + len(SECOND)
    assert report["blocks"] == [
        {
            "address": f"0x{FIRST_OFFSET:08X}",
            "offset": f"0x{FIRST_OFFSET:X}",
            "packed_size": len(compress_mio0(FIRST)),
            "size": len(FIRST),
        },
        {
            "address": f"0x{SECOND_OFFSET:08X}",
            "offset": f"0x{SECOND_OFFSET:X}",
            "packed_size": len(compress_mio0(SECOND)),
            "size": len(SECOND),
        },
    ]


def test_mio0_takes_the_limit_range_and_base_of_every_scanner(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    limited = _run(capsys, "mio0", str(image), "--limit", "1")
    assert (limited["count"], limited["truncated"], len(limited["blocks"])) == (2, True, 1)
    assert limited["packed_bytes"] == len(compress_mio0(FIRST)) + len(compress_mio0(SECOND))

    later = _run(capsys, "mio0", str(image), "--start", f"0x{FIRST_OFFSET + 1:X}")
    assert [block["offset"] for block in later["blocks"]] == [f"0x{SECOND_OFFSET:X}"]
    # A block cut by --end is no block of the scanned part.
    earlier = _run(capsys, "mio0", str(image), "--end", f"0x{SECOND_OFFSET + 8:X}")
    assert [block["offset"] for block in earlier["blocks"]] == [f"0x{FIRST_OFFSET:X}"]

    based = _run(capsys, "mio0", str(image), "--base", "0x02000000")
    assert based["base"] == "0x02000000"
    assert based["blocks"][0]["address"] == f"0x{0x02000000 + FIRST_OFFSET:08X}"
    assert based["blocks"][0]["offset"] == f"0x{FIRST_OFFSET:X}"


def test_mio0_extracts_the_block_at_an_address(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    out = tmp_path / "segment.bin"
    report = _run(capsys, "mio0", str(image), "--extract", hex(FIRST_OFFSET), "--out", str(out))
    assert out.read_bytes() == FIRST
    assert report["platform"] is None
    assert report["block"] == {
        "address": f"0x{FIRST_OFFSET:08X}",
        "offset": f"0x{FIRST_OFFSET:X}",
        "packed_size": len(compress_mio0(FIRST)),
        "size": len(FIRST),
    }
    assert report["out"] == str(out)

    second = tmp_path / "second.bin"
    _run(capsys, "mio0", str(image), "--extract", str(SECOND_OFFSET), "--out", str(second))
    assert second.read_bytes() == SECOND
    # With a base, the address is the block's address, as the report gives it.
    based = tmp_path / "based.bin"
    report = _run(
        capsys,
        "mio0",
        str(image),
        "--base",
        "0x02000000",
        "--extract",
        hex(0x02000000 + SECOND_OFFSET),
        "--out",
        str(based),
    )
    assert based.read_bytes() == SECOND
    assert report["block"]["offset"] == f"0x{SECOND_OFFSET:X}"


def test_mio0_does_not_replace_a_file_without_force(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    out = tmp_path / "segment.bin"
    out.write_bytes(b"kept")
    message = _refused(
        capsys,
        "OUTPUT_EXISTS",
        "mio0",
        str(image),
        "--extract",
        hex(FIRST_OFFSET),
        "--out",
        str(out),
    )
    assert "exists; pass --force to replace it" in message
    assert out.read_bytes() == b"kept"

    _run(capsys, "mio0", str(image), "--extract", hex(FIRST_OFFSET), "--out", str(out), "--force")
    assert out.read_bytes() == FIRST


def test_mio0_refuses_an_address_without_a_block(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    out = tmp_path / "segment.bin"
    for address in ("0", hex(FALSE_MAGIC_OFFSET), hex(FIRST_OFFSET + 1)):
        message = _refused(
            capsys,
            "COMPRESSION_ROUNDTRIP_FAILED",
            "mio0",
            str(image),
            "--extract",
            address,
            "--out",
            str(out),
        )
        assert f"0x{int(address, 0):08X}" in message
    _refused(
        capsys,
        "INVALID_BYTE_RANGE",
        "mio0",
        str(image),
        "--extract",
        hex(image.stat().st_size + 1),
        "--out",
        str(out),
    )
    assert not out.exists()


def test_mio0_extract_and_out_go_together(tmp_path: Path, capsys):
    image = _image(tmp_path / "game.bin")
    out = tmp_path / "segment.bin"
    message = _refused(capsys, "INVALID_BYTE_RANGE", "mio0", str(image), "--extract", "0x20")
    assert "--out" in message
    message = _refused(capsys, "INVALID_BYTE_RANGE", "mio0", str(image), "--out", str(out))
    assert "--extract" in message
    assert not out.exists()


def test_scanners_label_an_n64_image_and_read_a_z64_image_big_endian(tmp_path: Path, capsys):
    image = _n64_image(tmp_path / "game.z64")
    tables = _run(capsys, "pointer-tables", str(image), "--min-count", "4")
    assert (tables["platform"], tables["base"], tables["byteorder"]) == ("n64", "0x00000000", "big")
    assert tables["tables"] == [
        {
            "address": "0x00000100",
            "offset": "0x100",
            "count": 6,
            "stride": 4,
            "lowest": "0x00000040",
            "highest": "0x00000068",
            "ascending": True,
            "odd": 0,
        }
    ]
    pointers = _run(capsys, "pointers", str(image), "--to", "0x48")
    assert pointers["byteorder"] == "big"
    assert pointers["references"] == [
        {"address": "0x00000104", "offset": "0x104", "value": "0x00000048"}
    ]
    # An explicit --byteorder always wins.
    little = _run(capsys, "pointer-tables", str(image), "--min-count", "4", "--byteorder", "little")
    assert (little["platform"], little["byteorder"], little["tables"]) == ("n64", "little", [])

    blocks = _run(capsys, "mio0", str(image))
    assert (blocks["platform"], blocks["count"]) == ("n64", 1)
    assert blocks["blocks"][0]["offset"] == "0x140" and blocks["blocks"][0]["size"] == len(SECOND)


def test_a_byte_swapped_n64_image_is_labelled_but_read_as_before(tmp_path: Path, capsys):
    image = _n64_image(tmp_path / "game.v64", "v64")
    tables = _run(capsys, "pointer-tables", str(image), "--min-count", "4")
    assert (tables["platform"], tables["byteorder"], tables["tables"]) == ("n64", "little", [])
    big = _run(capsys, "pointer-tables", str(image), "--min-count", "4", "--byteorder", "big")
    assert (big["byteorder"], big["tables"]) == ("big", [])
    # An image of no known platform is read little-endian, as before.
    other = _image(tmp_path / "game.bin")
    tables = _run(capsys, "pointer-tables", str(other))
    assert (tables["platform"], tables["byteorder"]) == (None, "little")
