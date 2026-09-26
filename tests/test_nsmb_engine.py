from __future__ import annotations

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.nsmb import (
    COLOUR,
    NUMBER,
    colour_escape,
    escape_colour,
    notation_skeleton,
    parse_notation,
    split_lines,
    text_notation,
)
from classic_retro.text.bmg import BmgEscape

# An invented prompt in the engine's notation.
PROMPT = "Pay {FF:00000100}{01:0100}{FF:00000000} shells\nto cross?"


def test_notation_round_trips_escapes_and_line_ends():
    pieces = parse_notation(PROMPT)
    assert pieces == (
        "Pay ",
        BmgEscape(COLOUR, bytes.fromhex("00000100")),
        BmgEscape(NUMBER, bytes.fromhex("0100")),
        BmgEscape(COLOUR, bytes(4)),
        " shells\nto cross?",
    )
    assert text_notation(pieces) == PROMPT
    assert notation_skeleton(pieces) == ("{FF:00000100}", "{01:0100}", "{FF:00000000}", "\n")


@pytest.mark.parametrize("text", ["a{b", "a}", "{FF:000}", "{1:00}", "{FF:0000"])
def test_braces_only_open_whole_escapes(text):
    with pytest.raises(ClassicRetroError) as caught:
        parse_notation(text)
    assert caught.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_colours_are_escapes_of_their_own():
    assert escape_colour(colour_escape(2)) == 2
    assert colour_escape(1).notation == "{FF:00000100}"
    assert escape_colour(BmgEscape(NUMBER, bytes.fromhex("0100"))) is None
    assert escape_colour(BmgEscape(COLOUR, bytes.fromhex("01000100"))) is None


def test_lines_keep_their_escapes():
    lines = split_lines(parse_notation("One\n{FF:00000200}Two\n{FF:00000000}Three"))
    assert lines == [
        ["One"],
        [colour_escape(2), "Two"],
        [colour_escape(0), "Three"],
    ]
    assert split_lines(parse_notation("A\n\nB")) == [["A"], [], ["B"]]


def test_the_game_and_its_engine_are_registered():
    registry = build_registry(load_external=False)
    game = registry.games["new-super-mario-bros-usa"]
    assert (game.platform_id, game.engine_id, game.game_code) == ("nds", "nds.nsmb", "A2DE")
    assert registry.engines["nds.nsmb"].platform_ids == ("nds",)
    assert "nds" in registry.platforms
