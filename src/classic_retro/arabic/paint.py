"""Paint-order preparation for game renderers that draw from the right edge leftwards."""

from __future__ import annotations

import unicodedata

from classic_retro.arabic.pipeline import ArabicPipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import InlineToken, TextToken, Token, TokenMovement, TokenStream


def reject_combining_marks(stream: TokenStream, profile: str) -> None:
    """Fail loudly instead of letting a renderer without mark placement drop harakat."""
    marks = sorted(
        {
            character
            for token in stream.tokens
            if isinstance(token, TextToken)
            for character in token.text
            if unicodedata.combining(character)
        }
    )
    if marks:
        values = ", ".join(f"U+{ord(character):04X}" for character in marks)
        raise ClassicRetroError(
            ErrorCode.UNSUPPORTED_ARABIC_MARK,
            f"{profile} does not support combining marks: " + values,
        )


def reverse_visual_stream(stream: TokenStream) -> TokenStream:
    output: list[Token] = []
    for token in reversed(stream.tokens):
        if isinstance(token, TextToken):
            output.append(TextToken(token.text[::-1]))
        else:
            output.append(token)
    return TokenStream(tuple(output))


def rtl_paint_order(pipeline: ArabicPipeline, stream: TokenStream) -> TokenStream:
    """Convert logical text into right-to-left paint order.

    Ordered inline tokens (line breaks, colours, runtime variables, engine
    commands) keep execution order and split the text into independent bidi
    segments. Each segment is shaped and reordered by the shared pipeline, then
    its visual order is reversed so that the first painted glyph is the
    rightmost one.
    """
    output: list[Token] = []
    segment: list[Token] = []

    def flush_segment() -> None:
        if not segment:
            return
        visual = pipeline.process(TokenStream(tuple(segment))).visual
        output.extend(reverse_visual_stream(visual).tokens)
        segment.clear()

    for token in stream.tokens:
        if isinstance(token, InlineToken) and token.movement is TokenMovement.ORDERED:
            flush_segment()
            output.append(token)
        else:
            segment.append(token)

    flush_segment()
    return TokenStream(tuple(output))
