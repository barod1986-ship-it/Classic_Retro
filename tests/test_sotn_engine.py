from __future__ import annotations

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.sotn import (
    ARGUMENTS,
    GLYPH_START,
    LINE_BREAK,
    SET_WAIT,
    TEXT_COMMANDS,
    WAIT_FOR_SOUND,
    SotnCommand,
    command_skeleton,
    encode_latin,
    message_pieces,
    notation_skeleton,
    parse_notation,
    pieces_bytes,
    script_messages,
    split_script,
    text_notation,
)

# An invented scene in the engine's notation: what two speakers say.
FIRST = "{speed 4}Hello there.\n{wait 28}Who goes{wait 8} there?{wait 48}"
SECOND = "{flag 10}{speed 2}Only me!\n{wait-flag 8}{flag 6}Bye.{wait 48}"


def _command(code: int, *arguments: int) -> bytes:
    return SotnCommand(code, bytes(arguments)).data


def _scene() -> tuple[bytes, list[tuple[int, int]]]:
    """The box opens, then each speaker's portrait, voice and message; the box closes."""
    script = bytearray(_command(0x07, 0x10, 0x20))
    spans = []
    for number, text in enumerate((FIRST, SECOND)):
        script += _command(0x05, 0x01, number) + _command(0x09, 0x06, 0x0A + number)
        script += _command(WAIT_FOR_SOUND)
        start = len(script)
        script += pieces_bytes(parse_notation(text))
        spans.append((start, len(script)))
        script += _command(0x06)
    # A voice with nothing said after it, then the end.
    script += _command(0x09, 0x01, 0x02) + _command(WAIT_FOR_SOUND) + _command(0x08)
    script += _command(0x00)
    return bytes(script), spans


def test_the_engine_is_registered_for_the_game():
    registry = build_registry()
    game = registry.games["castlevania-sotn-usa"]
    assert game.engine_id == "ps1.sotn-cutscene" and game.platform_id == "ps1"
    assert registry.engines["ps1.sotn-cutscene"].platform_ids == ("ps1",)


def test_commands_lie_below_the_glyphs():
    assert max(ARGUMENTS) < GLYPH_START == 0x15
    assert set(TEXT_COMMANDS) < set(ARGUMENTS) and LINE_BREAK not in TEXT_COMMANDS
    assert 0x0E not in ARGUMENTS
    assert SotnCommand(0x13, bytes(5)).data == b"\x13" + bytes(5)


def test_a_script_splits_into_glyph_runs_and_commands_at_their_offsets():
    script, spans = _scene()
    pieces = split_script(script)
    assert pieces[:4] == [
        (0, SotnCommand(0x07, b"\x10\x20")),
        (3, SotnCommand(0x05, b"\x01\x00")),
        (6, SotnCommand(0x09, b"\x06\x0a")),
        (9, SotnCommand(WAIT_FOR_SOUND)),
    ]
    assert pieces[4] == (spans[0][0], SotnCommand(0x02, b"\x04"))
    assert pieces[5] == (spans[0][0] + 2, "Hello there.")
    assert split_script(script, spans[1][0] + 4, spans[1][0] + 8) == [(spans[1][0] + 4, "Only")]


def test_messages_follow_the_wait_for_the_voice():
    script, spans = _scene()
    assert script_messages(script) == spans
    first, second = (script[start:end] for start, end in spans)
    assert text_notation(first) == FIRST and text_notation(second) == SECOND
    assert command_skeleton(first) == ("{speed 4}", "{wait 28}", "{wait 8}", "{wait 48}")
    # A message may run to the end of the part read.
    assert script_messages(script, 0, spans[0][1] - 3) == [(spans[0][0], spans[0][1] - 3)]


def test_notation_round_trips_to_the_same_bytes():
    script, spans = _scene()
    for start, end in spans:
        data = script[start:end]
        pieces = message_pieces(data)
        assert pieces_bytes(pieces) == data
        assert parse_notation(text_notation(data)) == pieces
    assert parse_notation("a\n{wait 0}{flag 255}") == (
        "a",
        SotnCommand(LINE_BREAK),
        SotnCommand(SET_WAIT, b"\x00"),
        SotnCommand(0x11, b"\xff"),
    )
    assert notation_skeleton(parse_notation("a\n{wait 3}b\n")) == ("{wait 3}",)


@pytest.mark.parametrize("data", [b"Hi\x0e\x00\x00\x00\x00", b"Hi\x02", b"\x09\x01"])
def test_unreadable_commands_are_refused(data):
    with pytest.raises(ClassicRetroError) as caught:
        split_script(data)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_a_message_holds_only_text_and_the_text_commands():
    with pytest.raises(ClassicRetroError) as caught:
        message_pieces(b"Hi\x06")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    with pytest.raises(ClassicRetroError) as caught:
        text_notation(b"Hi" + SotnCommand(0x05, b"\x01\x00").data)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    portrait = SotnCommand(0x05, b"\x01\x00")
    assert not portrait.in_text and not portrait.is_line_break
    with pytest.raises(ClassicRetroError) as caught:
        assert portrait.notation
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    for code, arguments in ((0x0E, b""), (0x02, b""), (0x00, b"\x01")):
        with pytest.raises(ClassicRetroError) as caught:
            SotnCommand(code, arguments)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{jump 3}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{wait 256}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("{wait}", ErrorCode.UNSUPPORTED_CONTROL_CODE),
        ("a}b", ErrorCode.UNENCODABLE_TEXT),
    ],
)
def test_bad_notation_is_refused(text, code):
    with pytest.raises(ClassicRetroError) as caught:
        parse_notation(text)
    assert caught.value.code is code


def test_the_game_font_holds_printable_ascii():
    assert encode_latin("Die monster!") == b"Die monster!"
    for text in ("café", "tab\t", "م"):
        with pytest.raises(ClassicRetroError) as caught:
            encode_latin(text)
        assert caught.value.code is ErrorCode.UNENCODABLE_TEXT
