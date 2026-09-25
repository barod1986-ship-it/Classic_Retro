"""The research scanners and text tables, on synthetic images with invented text."""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.scan import (
    FreeRun,
    PointerTable,
    Reference,
    RelativeMatch,
    TextRun,
    ascii_strings,
    find_pattern,
    find_references,
    free_space,
    parse_pattern,
    pointer_tables,
    relative_search,
    table_strings,
)
from classic_retro.research.tables import TextTable, parse_table

TABLE = "\n".join(
    [
        "# An invented code page.",
        "01=a",
        "02=b",
        "03=c",
        "10= ",
        "20=<name>",
        "3D==",
        "8140=[wide]",
        "/FF=<end>",
        "*FE",
        "$E0=<wait>",
    ]
)


def test_free_space_finds_aligned_runs_of_each_fill():
    data = b"\x12" * 16 + b"\xff" * 300 + b"\x34" + b"\x00" * 50 + b"\x56" * 3 + b"\x00" * 600
    assert free_space(data, min_size=64) == [FreeRun(16, 300, 0xFF), FreeRun(370, 600, 0x00)]
    assert free_space(data, min_size=64, align=32) == [
        FreeRun(32, 284, 0xFF),
        FreeRun(384, 586, 0x00),
    ]
    assert free_space(data, fills=(0xFF,), min_size=290, align=32) == []
    assert free_space(data, min_size=64, start=100, end=400) == [FreeRun(100, 216, 0xFF)]
    with pytest.raises(ClassicRetroError) as error:
        free_space(data, start=10, end=len(data) + 1)
    assert error.value.code is ErrorCode.INVALID_BYTE_RANGE


def test_references_by_value_range_width_and_order():
    data = bytearray(64)
    for offset, value in ((8, 0x08000100), (20, 0x08000100), (32, 0x08000180), (42, 0x08000100)):
        struct.pack_into("<I", data, offset, value)
    exact = [(0x08000100, 0x08000101)]
    assert find_references(data, exact) == [
        Reference(8, 0x08000100),
        Reference(20, 0x08000100),
    ]
    assert [ref.offset for ref in find_references(data, [(0x08000100, 0x08000200)])] == [8, 20, 32]
    assert [ref.offset for ref in find_references(data, exact, align=2)] == [8, 20, 42]
    assert [ref.offset for ref in find_references(data, exact, start=12)] == [20]

    big = b"\x00\x00\x12\x34\x00\x00\x12\x34\x12"
    assert find_references(big, [(0x1234, 0x1235)], width=2, byteorder="big", align=2) == [
        Reference(2, 0x1234),
        Reference(6, 0x1234),
    ]
    three = b"\x00\x01\x02\x03\x00"
    assert find_references(three, [(0x030201, 0x030202)], width=3, align=1) == [
        Reference(1, 0x030201)
    ]


def test_pointer_tables():
    data = bytearray(512)
    for index in range(10):
        # Ten ascending pointers at 0x40; one is odd, as a Thumb function would be.
        struct.pack_into("<I", data, 0x40 + 4 * index, 0x08000080 + 8 * index + (index == 3))
    for index in range(3):
        struct.pack_into("<I", data, 0x10 + 4 * index, 0x08000000)
    for index in range(8):
        # A structure array: a pointer, then a word that is not one.
        struct.pack_into("<II", data, 0x100 + 8 * index, 0x08000180 - 4 * index, 0x12345678)
    image = (0x08000000, 0x08000200)
    assert pointer_tables(data, target=image) == [
        PointerTable(0x40, 10, 4, 0x08000080, 0x080000C8, ascending=True, odd=1)
    ]
    assert pointer_tables(data, target=image, min_count=3)[0].offset == 0x10
    # At a stride of 8 the ten become two runs of five, too short.
    assert pointer_tables(data, target=image, stride=8) == [
        PointerTable(0x100, 8, 8, 0x08000164, 0x08000180, ascending=False, odd=0)
    ]
    assert pointer_tables(data, target=(0x08000100, 0x08000200), stride=8, min_count=4) == [
        PointerTable(0x100, 8, 8, 0x08000164, 0x08000180, ascending=False, odd=0)
    ]
    with pytest.raises(ClassicRetroError) as error:
        pointer_tables(data, target=image, stride=6)
    assert error.value.code is ErrorCode.INVALID_SEARCH_PATTERN


def test_ascii_strings():
    data = b"\x01\x02Hello, research!\x00\xffshort\x00\x80Another string here\xff"
    assert ascii_strings(data) == [
        TextRun(2, 16, "Hello, research!", True),
        TextRun(27, 19, "Another string here", False),
    ]
    assert [run.text for run in ascii_strings(data, min_length=5)][1] == "short"
    assert ascii_strings(data, start=26, end=33) == []


def test_parse_table():
    table = parse_table(TABLE)
    assert table.entries[b"\x10"] == " "
    assert table.entries[b"\x3d"] == "="
    assert table.entries[b"\xfe"] == "\n"
    assert table.entries[b"\xe0"] == "<wait>"
    assert table.ends == frozenset({b"\xff"})
    assert table.longest == 2
    assert table.decode(b"\x01\x02\x81\x40\x99\x20\xff") == "ab[wide]{99}<name><end>"
    for text, message in (
        ("zz=a", "not hex bytes"),
        ("123=a", "not hex bytes"),
        ("01=a\n01=b", "defined twice"),
        ("$E0", "expected HEX=TEXT"),
        ("# nothing\n", "has no entries"),
    ):
        with pytest.raises(ClassicRetroError) as error:
            parse_table(text)
        assert error.value.code is ErrorCode.INVALID_TEXT_TABLE
        assert message in str(error.value)


def test_table_strings_read_left_to_right_and_stop_at_end_codes():
    table = parse_table(TABLE)
    data = (
        b"\x00"
        + b"\x01\x02\x03\x10\x01\x02\x03\x81\x40\xff"
        + b"\x00\x00"
        + b"\x01\x02\xfe\x03\x01\x02\x03\x02\x01"
        + b"\x00"
    )
    assert list(table_strings(data, table)) == [
        TextRun(1, 10, "abc abc[wide]<end>", True),
        TextRun(13, 9, "ab\ncabcba", False),
    ]
    assert [run.offset for run in table_strings(data, table, min_length=9)] == [13]
    assert list(table_strings(data, table, start=2)) == [TextRun(13, 9, "ab\ncabcba", False)]


def test_one_byte_tables_find_the_same_strings_faster():
    table = parse_table("\n".join(line for line in TABLE.splitlines() if "8140" not in line))
    assert table.longest == 1
    data = bytes(range(256)) * 3 + b"\x01\x02\x03" * 5 + b"\xff\x00" + b"\x02" * 20 + b"\x10"
    general = TextTable({**table.entries, b"\xee\xee\xee": "?"}, table.ends)
    for min_length in (1, 3, 8):
        fast = list(table_strings(data, table, min_length=min_length))
        assert fast == list(table_strings(data, general, min_length=min_length))
    assert list(table_strings(data, table, min_length=15))[0] == TextRun(
        768, 16, "abc" * 5 + "<end>", True
    )


def _encode(word: str, alphabet: int, letter: str = "A") -> bytes:
    return bytes(alphabet + ord(character) - ord(letter) for character in word)


def test_relative_search_finds_a_word_in_an_unknown_encoding():
    data = bytes(0x21) + _encode("SCROLLSAHEAD", 0x40) + bytes(8) + _encode("scroll", 0x90, "a")
    # Upper and lower case letters run the same way: both spellings match.
    assert relative_search(data, "SCROLL") == [
        RelativeMatch(0x21, 0x52, 0x40),
        RelativeMatch(0x35, 0xA2, 0x90),
    ]
    assert relative_search(data, "scroll") == [
        RelativeMatch(0x21, 0x52, 0x52 - 18),
        RelativeMatch(0x35, 0xA2, 0x90),
    ]
    assert relative_search(data, "AHEAD", start=0x30) == []
    for word in ("Hi", "MiXed", "AB1"):
        with pytest.raises(ClassicRetroError) as error:
            relative_search(data, word)
        assert error.value.code is ErrorCode.INVALID_SEARCH_PATTERN


def test_patterns_match_every_offset_with_wildcards():
    data = b"\x70\x47\x00\xb5\x70\x47\x01\xb5\x70\x47"
    assert find_pattern(data, parse_pattern("70 47 ?? B5")) == [0, 4]
    assert find_pattern(b"\xaa\xaa\xaa", parse_pattern("aaaa")) == [0, 1]
    assert find_pattern(data, parse_pattern("7047"), start=1, end=9) == [4]
    for text in ("7", "zz", ""):
        with pytest.raises(ClassicRetroError) as error:
            parse_pattern(text)
        assert error.value.code is ErrorCode.INVALID_SEARCH_PATTERN


def _gba_image(path: Path, body: bytes) -> Path:
    header = bytearray(0xC0)
    header[0:4] = bytes.fromhex("2e0000ea")
    header[0xB2] = 0x96
    header[0xBD] = -(sum(header[0xA0:0xBD]) + 0x19) & 0xFF
    path.write_bytes(bytes(header) + body)
    return path


def _run(capsys, *arguments: str) -> dict:
    assert main(["research", *arguments]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_scans_a_gba_image(tmp_path: Path, capsys):
    body = bytearray(0x340)
    struct.pack_into("<4I", body, 0x40, 0x08000200, 0x08000210, 0x08000220, 0x08000230)
    body[0x140:0x152] = b"An invented line.\x00"
    body[0x200:0x240] = b"\xff" * 0x40
    image = _gba_image(tmp_path / "game.gba", bytes(body))

    free = _run(capsys, "free-space", str(image), "--fill", "0xff", "--min-size", "32")
    assert (free["platform"], free["base"], free["count"]) == ("gba", "0x08000000", 1)
    assert free["runs"] == [
        {
            "address": "0x080002C0",
            "offset": "0x2C0",
            "size": 64,
            "end": "0x08000300",
            "fill": "0xFF",
        }
    ]
    assert free["free_bytes"] == {"0xFF": 64} and free["largest"] == 64

    pointers = _run(capsys, "pointers", str(image), "--to", "0x08000210:0x08000230")
    assert pointers["references"] == [
        {"address": "0x08000104", "offset": "0x104", "value": "0x08000210"},
        {"address": "0x08000108", "offset": "0x108", "value": "0x08000220"},
    ]
    assert pointers["targets"] == ["0x08000210:0x08000230"]

    tables = _run(capsys, "pointer-tables", str(image), "--min-count", "4")
    assert tables["tables"] == [
        {
            "address": "0x08000100",
            "offset": "0x100",
            "count": 4,
            "stride": 4,
            "lowest": "0x08000200",
            "highest": "0x08000230",
            "ascending": True,
            "odd": 0,
        }
    ]

    text = _run(capsys, "text", str(image), "--min-length", "10")
    assert text["strings"] == [
        {
            "address": "0x08000200",
            "offset": "0x200",
            "size": 17,
            "terminated": True,
            "text": "An invented line.",
        }
    ]

    found = _run(capsys, "find", str(image), "invented", "--ascii")
    assert found["matches"] == [{"address": "0x08000203", "offset": "0x203"}]
    limited = _run(capsys, "find", str(image), "ff ff", "--limit", "3")
    assert (limited["count"], limited["truncated"], len(limited["matches"])) == (63, True, 3)


def test_cli_text_tables_relative_search_and_base(tmp_path: Path, capsys):
    image = tmp_path / "game.bin"
    image.write_bytes(bytes(16) + _encode("PICORIWORLD", 0x20) + bytes(16))
    relative = _run(capsys, "relative-search", str(image), "WORLD")
    assert (relative["platform"], relative["base"]) == (None, "0x00000000")
    assert relative["matches"] == [
        {
            "address": "0x00000016",
            "offset": "0x16",
            "code": "0x36",
            "A": "0x20",
            "preview": ".." + "PICORIWORLD" + "." * 16,
        }
    ]
    table = tmp_path / "game.tbl"
    table.write_text("".join(f"{0x20 + index:02X}={chr(65 + index)}\n" for index in range(26)))
    decoded = _run(capsys, "text", str(image), "--table", str(table), "--base", "0x02000000")
    assert decoded["strings"] == [
        {
            "address": "0x02000010",
            "offset": "0x10",
            "size": 11,
            "terminated": False,
            "text": "PICORIWORLD",
        }
    ]
    assert main(["research", "free-space", str(image), "--start", "0x100"]) == 2
    assert "INVALID_BYTE_RANGE" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("arm-none-eabi-objdump") is None, reason="needs GNU ARM binutils")
def test_cli_disassembles_thumb_code(tmp_path: Path, capsys):
    image = _gba_image(tmp_path / "game.gba", bytes.fromhex("00b5 0120 00bd 7047"))
    assert main(["research", "disasm", str(image), "0x080000C1", "--length", "8"]) == 0
    listing = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[-2:] for line in listing] == [
        ["push", "{lr}"],
        ["movs", "r0, #1"],
        ["pop", "{pc}"],
        ["bx", "lr"],
    ]
    assert listing[0].strip().startswith("80000c0:")
