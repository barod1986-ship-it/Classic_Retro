from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.gran_turismo import (
    BRIEFINGS,
    GT_ARC_MAGIC,
    GT_ARC_PACKED,
    LICENSE_TESTS,
    Briefing,
    GranTurismoEngineAdapter,
    briefing_bytes,
    briefing_notation,
    gt_arc_file,
    gt_arc_room,
    join_briefings,
    parse_briefing,
    parse_notation,
    read_gt_arc,
    replace_gt_arc_file,
    split_briefings,
)
from classic_retro.rebuild.gtzip import compress_gtzip


def archive(files: list[bytes], *, kind: int = 1, room: int = 0x100) -> bytes:
    """A GT-ARC archive: each file at the next multiple of ``room``."""
    table = 16 + 12 * len(files)
    start = -(-table // room) * room
    data = bytearray(GT_ARC_MAGIC + struct.pack("<HH", kind, len(files)))
    data += bytes(start - len(data))
    for index, content in enumerate(files):
        stored = compress_gtzip(content) if kind & GT_ARC_PACKED else content
        offset = len(data)
        struct.pack_into("<III", data, 16 + 12 * index, offset, len(stored), len(content))
        data += stored + bytes(-len(stored) % room)
    return bytes(data)


def test_an_archive_lists_its_files_and_unpacks_them():
    files = [b"first", bytes(range(200)), b"third" * 40]
    data = archive(files)
    kind, entries = read_gt_arc(data)
    assert kind == 1 and [entry.size for entry in entries] == [5, 200, 200]
    assert [gt_arc_file(data, index) for index in range(3)] == files
    assert gt_arc_room(data, 0) == 0x100 and gt_arc_room(data, 2) == 0x100
    packed = archive(files, kind=1 | GT_ARC_PACKED)
    assert [gt_arc_file(packed, index) for index in range(3)] == files
    with pytest.raises(ClassicRetroError):
        gt_arc_file(data, 3)


@pytest.mark.parametrize(
    "broken",
    [b"not an archive at all", GT_ARC_MAGIC + struct.pack("<HH", 1, 9) + bytes(16)],
)
def test_other_data_is_refused(broken):
    with pytest.raises(ClassicRetroError) as caught:
        read_gt_arc(broken)
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def test_a_file_is_replaced_in_its_own_room():
    data = archive([b"a" * 10, b"b" * 20, b"c" * 30])
    replaced = replace_gt_arc_file(data, 1, b"new" * 50)
    assert len(replaced) == len(data)
    assert gt_arc_file(replaced, 1) == b"new" * 50
    assert gt_arc_file(replaced, 0) == b"a" * 10 and gt_arc_file(replaced, 2) == b"c" * 30
    # The rest of its room is cleared.
    offset = read_gt_arc(replaced)[1][1].offset
    assert replaced[offset + 150 : offset + 0x100] == bytes(0x100 - 150)
    with pytest.raises(ClassicRetroError) as caught:
        replace_gt_arc_file(data, 1, bytes(0x101))
    assert caught.value.code is ErrorCode.RELOCATION_OVERFLOW
    with pytest.raises(ClassicRetroError):
        replace_gt_arc_file(archive([b"x"], kind=1 | GT_ARC_PACKED), 0, b"y")


def _briefing() -> Briefing:
    return Briefing(
        b"Starting and stopping 9",
        ((b"Accelerate", b"away", b"from", b"here."), (b"The", b"car."), (b"36", b"seconds.")),
    )


def test_a_briefing_is_its_title_word_then_its_paragraphs_words():
    data = briefing_bytes(_briefing())
    assert data[:3] == bytes((3, 1, 24))
    assert data[3:27] == b"Starting and stopping 9\x00"
    assert data[27:40] == bytes((4, 11)) + b"Accelerate\x00"
    assert parse_briefing(data) == _briefing()
    assert parse_briefing(data + b"\x00") == _briefing()  # the padding
    assert briefing_notation(_briefing()) == (
        "Starting and stopping 9\nAccelerate away from here.\nThe car.\n36 seconds."
    )


@pytest.mark.parametrize(
    "broken",
    [
        bytes((1, 2, 2, 65, 0, 2, 66, 0, 1, 2, 67, 0)),  # a title of two words
        bytes((1, 1, 3, 65, 66, 0, 1, 3, 67)),  # cut short
        bytes((1, 1, 2, 65, 0, 1, 2, 67, 1)),  # a word without its zero
        bytes((1, 1, 2, 65, 0, 1, 2, 67, 0, 0, 0)),  # more than the padding
    ],
)
def test_broken_briefings_are_refused(broken):
    with pytest.raises(ClassicRetroError):
        parse_briefing(broken)


def test_unstorable_briefings_are_refused():
    with pytest.raises(ClassicRetroError) as caught:
        briefing_bytes(Briefing(b"t", ()))
    assert caught.value.code is ErrorCode.TEXT_OVERFLOW
    for word in (b"", b"a\x00b", b"x" * 0xFF):
        with pytest.raises(ClassicRetroError) as caught:
            briefing_bytes(Briefing(b"t", ((word,),)))
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_the_license_file_holds_24_texts_each_padded_to_an_even_length():
    texts = [briefing_bytes(Briefing(f"T{index}".encode(), ((b"w" * index or b"x",),)))
             for index in range(BRIEFINGS)]  # fmt: skip
    data = join_briefings(texts)
    offsets = struct.unpack_from(f"<{BRIEFINGS}H", data)
    assert offsets[0] == 2 * BRIEFINGS and all(offset % 2 == 0 for offset in offsets)
    split = split_briefings(data)
    assert [parse_briefing(text) for text in split] == [parse_briefing(text) for text in texts]
    assert join_briefings(split) == data
    with pytest.raises(ClassicRetroError):
        join_briefings(texts[:-1])
    broken = bytearray(data)
    struct.pack_into("<H", broken, 2, 0x7FFF)
    with pytest.raises(ClassicRetroError):
        split_briefings(bytes(broken))


def test_the_notation_is_a_title_line_then_a_line_a_paragraph():
    assert parse_notation("عنوان 1\nكلمة  أخرى\nثالثة") == (
        "عنوان 1",
        (("كلمة", "أخرى"), ("ثالثة",)),
    )
    for broken in ("title only", "\nno title", "title\nfirst\n\nthird"):
        with pytest.raises(ClassicRetroError) as caught:
            parse_notation(broken)
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT


def test_the_tests_follow_the_briefings():
    assert LICENSE_TESTS[:3] == ("B-1", "B-2", "B-3")
    assert LICENSE_TESTS[8] == "A-1" and LICENSE_TESTS[-1] == "IA-8"
    assert len(LICENSE_TESTS) == BRIEFINGS
    assert GranTurismoEngineAdapter.id == "ps1.gran-turismo-license"
