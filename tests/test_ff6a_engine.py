from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff6a import (
    CENTER,
    END,
    FONT_ASCII_ENTRIES,
    FONT_NO_GLYPH,
    NEWLINE,
    PAGE,
    PAUSE,
    Ff6aFont,
    Ff6aGlyph,
    Ff6aTextBank,
    command_notation,
    command_skeleton,
    decode_codes,
    encode_code,
    encode_codes,
    split_message,
)


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (0x00, b"\x00"),
        (0x7F, b"\x7f"),
        (0x80, b"\xc2\x80"),
        (0x10E, b"\xc4\x8e"),
        (0x5FF, b"\xd7\xbf"),
        (0x600, b"\xd8\x80"),
        (0x7FF, b"\xdf\xbf"),
        (0x800, b"\xe0\xa0\x80"),
        (0xFFFF, b"\xef\xbf\xbf"),
    ],
)
def test_codes_use_the_readers_utf8_like_lengths(value, encoded):
    assert encode_code(value) == encoded
    assert decode_codes(encoded) == (value,)


def test_reader_masks_lead_bytes_like_the_game():
    # The game treats every lead byte 0x80..0xDF as a two-byte code.
    assert decode_codes(b"\x85\x82") == ((0x05 << 6) | 0x02,)


@pytest.mark.parametrize("data", [b"\xc4", b"\xe0\x80", b"\xf0"])
def test_truncated_or_unknown_lead_bytes_fail(data):
    with pytest.raises(ClassicRetroError) as caught:
        decode_codes(data)
    assert caught.value.code is ErrorCode.UNKNOWN_TEXT_BYTE


def test_code_range_is_checked():
    with pytest.raises(ClassicRetroError):
        encode_code(0x10000)


def test_split_message_keeps_the_bytes_after_end():
    data = encode_codes([0x1F, 0x09, NEWLINE, 0x01, END]) + b"\x0e"
    codes, tail = split_message(data)
    assert codes == (0x1F, 0x09, NEWLINE, 0x01, END)
    assert tail == b"\x0e"
    with pytest.raises(ClassicRetroError) as caught:
        split_message(encode_codes([0x1F, NEWLINE]))
    assert caught.value.code is ErrorCode.MISSING_TERMINATOR


def test_skeleton_keeps_commands_and_arguments_only():
    codes = (0x142, CENTER, 0x1F, NEWLINE, CENTER, 0x01, PAUSE, 0x14C, PAGE, NEWLINE, 0x02, END)
    assert command_skeleton(codes) == (0x142, PAUSE, 0x14C, PAGE, END)
    assert command_notation(PAGE) == "{13E:PAGE}"
    assert command_notation(0x5FF) == "{5FF}"


def _bank(messages: list[bytes], languages: int = 1) -> Ff6aTextBank:
    return Ff6aTextBank(languages=languages, messages=tuple(messages))


def test_text_bank_round_trip_and_replace():
    messages = [encode_codes([index, END]) + b"\x0e" for index in range(6)]
    data = b"\xaa" * 8 + _bank(messages).build()

    parsed = Ff6aTextBank.parse(data, 8)
    assert parsed.message_count == 6
    assert parsed.message(3) == messages[3]
    assert parsed.build() == data[8:]

    replaced = parsed.replace({2: b"new"})
    assert replaced.message(2) == b"new"
    assert Ff6aTextBank.parse(replaced.build()).message(2) == b"new"
    assert replaced.message(3) == messages[3]


def test_text_bank_with_languages_indexes_message_then_language():
    bank = _bank([b"a0", b"a1", b"b0", b"b1"], languages=2)
    parsed = Ff6aTextBank.parse(bank.build())
    assert parsed.message_count == 2
    assert parsed.message(1, 0) == b"b0"
    assert parsed.message(1, 1) == b"b1"


def test_text_bank_rejects_bad_magic_and_unordered_offsets():
    good = bytearray(_bank([b"xx", b"yy"]).build())
    with pytest.raises(ClassicRetroError):
        Ff6aTextBank.parse(b"\x00" * 4 + b"NOPE" + bytes(good[8:]))
    good[16:20], good[20:24] = good[20:24], good[16:20]
    with pytest.raises(ClassicRetroError) as caught:
        Ff6aTextBank.parse(bytes(good))
    assert caught.value.code is ErrorCode.INVALID_REFERENCE


def _font() -> Ff6aFont:
    ascii_map = [FONT_NO_GLYPH] * FONT_ASCII_ENTRIES
    ascii_map[ord(" ")] = 0
    ascii_map[ord("a")] = 1
    glyphs = (
        Ff6aGlyph(3, 1, (0,) * 12),
        Ff6aGlyph(6, 2, tuple((row % 3) << 2 * (row % 8) for row in range(12))),
    )
    return Ff6aFont(height=12, flags=2, ascii_map=tuple(ascii_map), glyphs=glyphs)


def test_font_round_trip_and_character_codes():
    font = _font()
    data = font.build()
    parsed = Ff6aFont.parse(b"\x00" * 4 + data, 4)

    assert parsed == font
    assert parsed.build() == data
    assert parsed.character_codes() == {" ": 0, "a": 1}
    assert parsed.glyphs[1].pixel(1, 1) == 1


def test_glyph_rows_are_limited_to_the_blitter_word():
    with pytest.raises(ClassicRetroError) as caught:
        Ff6aGlyph(20, 5, (0,) * 12).encode()
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED
