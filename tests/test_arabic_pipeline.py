from __future__ import annotations

import unicodedata

import pytest

from classic_retro.arabic.pipeline import ArabicPipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    TokenKind,
    TokenMovement,
    TokenStream,
)


def test_pipeline_normalizes_to_nfc():
    stream = TokenStream((TextToken("ا\u0654هلاً"),))

    result = ArabicPipeline().process(stream)

    assert result.normalized.visible_text == unicodedata.normalize("NFC", "ا\u0654هلاً")


def test_pipeline_produces_shaped_and_visual_arabic():
    stream = TokenStream((TextToken("مرحبا بكم"),))

    result = ArabicPipeline().process(stream)

    assert result.shaped.visible_text != result.normalized.visible_text
    assert result.visual.visible_text != result.normalized.visible_text
    assert len(result.visual.visible_text) == len(result.shaped.visible_text)


def test_bidi_keeps_latin_and_numbers_in_reading_order():
    stream = TokenStream((TextToken("الإصدار 2.0 - TEST"),))

    result = ArabicPipeline().process(stream)

    assert "2.0" in result.visual.visible_text
    assert "TEST" in result.visual.visible_text
    assert "TSET" not in result.visual.visible_text


def test_protected_tokens_survive_shaping_and_bidi():
    player = InlineToken(
        id="player",
        kind=TokenKind.VARIABLE,
        movement=TokenMovement.FREE,
        name="PLAYER",
    )
    wait = InlineToken(
        id="wait",
        kind=TokenKind.CONTROL,
        movement=TokenMovement.ORDERED,
        name="WAIT",
        args={"frames": 30},
    )
    stream = TokenStream(
        (
            TextToken("مرحبًا "),
            player,
            TextToken("، لديك 25 نقطة "),
            wait,
        )
    )

    result = ArabicPipeline().process(stream)

    assert {token.id for token in result.normalized.inline_tokens} == {"player", "wait"}
    assert {token.id for token in result.shaped.inline_tokens} == {"player", "wait"}
    assert {token.id for token in result.visual.inline_tokens} == {"player", "wait"}
    assert "25" in result.visual.visible_text


def test_harakat_are_preserved_by_default():
    stream = TokenStream((TextToken("مَرْحَبًا"),))
    original_marks = sum(bool(unicodedata.combining(character)) for character in stream.visible_text)

    result = ArabicPipeline().process(stream)

    shaped_marks = sum(
        bool(unicodedata.combining(character)) for character in result.shaped.visible_text
    )
    visual_marks = sum(
        bool(unicodedata.combining(character)) for character in result.visual.visible_text
    )
    assert shaped_marks == original_marks
    assert visual_marks == original_marks


@pytest.mark.parametrize(
    ("text", "error_code"),
    [
        ("\uFE8D", ErrorCode.PRE_SHAPED_ARABIC_INPUT),
        ("مرحبا\u202Eabc", ErrorCode.EXPLICIT_BIDI_CONTROL),
        ("مرحبا\uFFFC", ErrorCode.RESERVED_ARABIC_MARKER_CHARACTER),
    ],
)
def test_pipeline_rejects_unsafe_logical_input(text, error_code):
    with pytest.raises(ClassicRetroError) as caught:
        ArabicPipeline().process(TokenStream((TextToken(text),)))

    assert caught.value.code is error_code
