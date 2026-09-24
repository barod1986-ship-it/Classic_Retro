from __future__ import annotations

import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.fomt import (
    CLEAR_COMMAND,
    NEWLINE_COMMAND,
    WAIT_COMMAND,
    FomtCommand,
    FomtScript,
    PlaceholderStyle,
    command_skeleton,
    name_command,
    parse_notation,
    read_string,
    split_text,
    text_notation,
)


def _riff(chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = b"SCR " + b"".join(name + struct.pack("<I", len(data)) + data for name, data in chunks)
    return b"RIFF" + struct.pack("<I", 8 + len(body)) + body


def _string_chunk(strings: list[bytes]) -> bytes:
    offsets, text = [], b""
    for string in strings:
        offsets.append(len(text))
        text += string + b"\0"
    return struct.pack(f"<I{len(strings)}I", len(strings), *offsets) + text


def test_script_text_splits_into_runs_and_commands():
    data = b"Hi, \xff\x21!\x05\x0cSee the \x0d\x0adog \xff\x23 run\x81\x49\x01\x05"
    pieces = split_text(data, PlaceholderStyle.SCRIPT)
    assert pieces == (
        "Hi, ",
        name_command(PlaceholderStyle.SCRIPT),
        "!",
        WAIT_COMMAND,
        CLEAR_COMMAND,
        "See the ",
        NEWLINE_COMMAND,
        "dog ",
        FomtCommand(b"\xff\x23", "{FF 23}"),
        " run{81 49}",
        FomtCommand(b"\x01", "{01}"),
        WAIT_COMMAND,
    )
    assert (
        text_notation(pieces)
        == "Hi, {name}!{wait}{clear}See the \ndog {FF 23} run{81 49}{01}{wait}"
    )
    assert command_skeleton(pieces) == (
        "{name}",
        "{wait}",
        "{clear}",
        "{FF 23}",
        "{01}",
        "{wait}",
    )


def test_story_text_names_the_player_with_a_lone_ff():
    pieces = split_text(b"\x0cWell, \xff?\x05", PlaceholderStyle.STORY)
    assert pieces == (
        CLEAR_COMMAND,
        "Well, ",
        name_command(PlaceholderStyle.STORY),
        "?",
        WAIT_COMMAND,
    )
    assert name_command(PlaceholderStyle.STORY).data == b"\xff"
    assert name_command(PlaceholderStyle.SCRIPT).data == b"\xff\x21"


def test_split_text_rejects_nul_and_a_cut_placeholder():
    with pytest.raises(ClassicRetroError) as error:
        split_text(b"a\0b", PlaceholderStyle.SCRIPT)
    assert error.value.code is ErrorCode.TOKEN_ORDER_VIOLATION
    with pytest.raises(ClassicRetroError):
        split_text(b"a\xff", PlaceholderStyle.SCRIPT)


def test_notation_round_trips_and_rejects_unknown_commands():
    notation = "{clear}One {name}!\nTwo{wait}"
    pieces = parse_notation(notation, PlaceholderStyle.STORY)
    assert text_notation(pieces) == notation
    assert pieces[2] == name_command(PlaceholderStyle.STORY)
    with pytest.raises(ClassicRetroError) as error:
        parse_notation("{pause}", PlaceholderStyle.SCRIPT)
    assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as error:
        parse_notation("a } b", PlaceholderStyle.SCRIPT)
    assert error.value.code is ErrorCode.UNENCODABLE_TEXT


def test_skeleton_ignores_line_ends():
    first = parse_notation("A\nB{wait}", PlaceholderStyle.SCRIPT)
    second = parse_notation("AB{wait}", PlaceholderStyle.SCRIPT)
    assert command_skeleton(first) == command_skeleton(second) == ("{wait}",)


def test_script_reads_its_strings_and_round_trips():
    code = struct.pack("<I", 6) + bytes(range(6))
    data = _riff([(b"CODE", code), (b"STR ", _string_chunk([b"Hello\x05", b"Bye\x05"]))])
    image = b"\xaa" * 12 + data + b"\x00\x00RIFF"
    script = FomtScript.read(image, 12)
    assert script.strings == (b"Hello\x05", b"Bye\x05")
    assert script.chunk(b"CODE") == code
    assert script.to_bytes() == data
    # The size field counts the whole file, header included.
    assert struct.unpack_from("<I", data, 4)[0] == len(data)


def test_script_takes_new_strings_and_keeps_its_code():
    code = struct.pack("<I", 2) + b"\x10\x20"
    script = FomtScript.read(_riff([(b"CODE", code), (b"STR ", _string_chunk([b"a", b"b"]))]), 0)
    rebuilt = script.with_strings([b"\xf0\x40\x05", b"xyz"])
    assert rebuilt.strings == (b"\xf0\x40\x05", b"xyz")
    assert rebuilt.chunk(b"CODE") == code
    chunk = rebuilt.chunk(b"STR ")
    assert len(chunk) % 2 == 0
    assert struct.unpack_from("<3I", chunk, 0) == (2, 0, 4)
    assert FomtScript.read(rebuilt.to_bytes(), 0) == rebuilt
    with pytest.raises(ClassicRetroError) as error:
        script.with_strings([b"only one"])
    assert error.value.code is ErrorCode.RESOURCE_SET_MISMATCH
    with pytest.raises(ClassicRetroError) as error:
        script.with_strings([b"a\0", b"b"])
    assert error.value.code is ErrorCode.UNENCODABLE_TEXT


def test_script_rejects_what_is_not_a_script():
    with pytest.raises(ClassicRetroError) as error:
        FomtScript.read(b"RIFX" + bytes(40), 0)
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    broken = bytearray(_riff([(b"CODE", b"\0" * 8)]))
    broken[16:20] = struct.pack("<I", 64)
    with pytest.raises(ClassicRetroError):
        FomtScript.read(bytes(broken), 0)
    with pytest.raises(ClassicRetroError):
        FomtScript.read(_riff([(b"CODE", b"")]), 0).chunk(b"STR ")


def test_read_string_needs_its_terminator():
    assert read_string(b"ab\0cd", 0) == b"ab"
    with pytest.raises(ClassicRetroError) as error:
        read_string(b"abc", 1)
    assert error.value.code is ErrorCode.MISSING_TERMINATOR
