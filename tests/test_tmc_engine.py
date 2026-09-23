from __future__ import annotations

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.tmc import (
    control_signature,
    glyph_advance,
    latin_glyph_widths,
    parse_tmc_string,
    render_tmc_string,
)
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream


@pytest.mark.parametrize(
    "text",
    [
        "{Sound:00:95}Good morning, {Color:Green}Master Smith{Color:White}.",
        "Oh!\n\nWhere's {Player}?\n{07:10:05}",
        "{04:10:0E}You got {Var:1} Rupees! {Key:A} {Symbol:1F}",
        "{Choice:FF}Buy {Choice:2D:0A}Don't buy",
        "Àçé ⋯ “quoted” ♪",
        "",
    ],
)
def test_tmc_strings_notation_round_trips(text):
    assert render_tmc_string(parse_tmc_string(text)) == text


def test_commands_become_ordered_tokens_with_names():
    stream = parse_tmc_string("{Sound:00:95}Hi {Player}!\n{07:10:05}")
    names = [token.name for token in stream.tokens if isinstance(token, InlineToken)]
    kinds = [token.kind for token in stream.tokens if isinstance(token, InlineToken)]

    assert names == ["SOUND", "PLAYER", None, "CONTINUE_TEXT"]
    assert kinds[2] is TokenKind.LINE_BREAK
    assert all(
        token.movement.value == "ordered"
        for token in stream.tokens
        if isinstance(token, InlineToken)
    )


def test_unknown_command_is_rejected():
    with pytest.raises(ClassicRetroError) as caught:
        parse_tmc_string("{Colour:Green}text")
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_text_without_game_glyph_is_rejected():
    with pytest.raises(ClassicRetroError) as caught:
        parse_tmc_string("مرحبا")
    assert caught.value.code is ErrorCode.UNENCODABLE_TEXT

    with pytest.raises(ClassicRetroError):
        render_tmc_string(TokenStream((TextToken("{"),)))


def test_control_signature_allows_moving_colours_and_lines():
    english = parse_tmc_string("{Color:Green}Zelda{Color:White} is here.\n{Player}!\n{07:10:05}")
    translated = parse_tmc_string("{Player}! {Color:Green}Z{Color:White}{07:10:05}")

    assert control_signature(english) == control_signature(translated)
    assert control_signature(english) == ("{Player}", "{07:10:05}")


def _half(first_row_nibbles: list[int]) -> bytes:
    row = bytes(
        first_row_nibbles[index] | (first_row_nibbles[index + 1] << 4) for index in range(0, 8, 2)
    )
    return row + bytes(60)


@pytest.mark.parametrize(
    "nibbles,width",
    [
        ([0xF, 0, 0, 0xE, 0, 0xF, 0xF, 0xF], 4),  # skip 1, four drawn columns
        ([0, 0, 0, 0, 0, 0, 0, 0], 8),
        ([0xF] * 8, 0),  # empty second half of a narrow 16px glyph
        ([0xF, 0xF, 0xF, 0xE, 0, 0xF, 0xF, 0xF], 2),
    ],
)
def test_glyph_advance_reads_engine_width_marker(nibbles, width):
    assert glyph_advance(_half(nibbles)) == width


def test_latin_widths_use_lowest_byte_for_duplicate_characters():
    page = bytearray(b"\xff" * 64 * 128)
    page[0x2C * 64 : 0x2C * 64 + 64] = _half([0, 0, 0, 0xF, 0xF, 0xF, 0xF, 0xF])
    extension = bytearray(b"\xff" * 64 * 128)
    extension[(0x82 - 0x80) * 64 : (0x82 - 0x80) * 64 + 64] = _half([0] * 8)

    widths = latin_glyph_widths(bytes(page), bytes(extension))

    assert widths[","] == 3


def test_minish_cap_adapter_is_registered_with_exact_revision():
    registry = build_registry(load_external=False)
    game = registry.games["zelda-minish-cap-usa"]

    assert game.engine_id == "gba.tmc"
    assert "gba.tmc" in registry.engines
    assert game.revisions[0].sha256 == (
        "bedc74df62755f705398273de8ed3bc59be610cf55760d0b9aa277f1f5035e73"
    )
    assert game.source_build is not None
    assert game.source_build.expected_sha1 == "b4bd50e4131b027c334547b4524e2dbbd4227130"
