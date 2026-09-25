from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from arabic_reshaper import ArabicReshaper
from bidi import get_display

from classic_retro.arabic.logical import EXPLICIT_DIRECTION_CONTROLS, is_presentation_form
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import InlineToken, TextToken, Token, TokenStream

_MARKER_BOUNDARY = "\ufffc"
_MARKER_CODES = tuple(chr(codepoint) for codepoint in range(0x2400, 0x2427))
_MARKER_WIDTH = 5
_MAX_MARKERS = len(_MARKER_CODES) ** 2


class ArabicBaseDirection(StrEnum):
    RTL = "R"
    LTR = "L"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class ArabicPipelineConfig:
    base_direction: ArabicBaseDirection = ArabicBaseDirection.RTL
    support_ligatures: bool = False
    preserve_harakat: bool = True
    preserve_tatweel: bool = True
    support_zwj: bool = True


@dataclass(frozen=True, slots=True)
class ArabicPipelineResult:
    normalized: TokenStream
    shaped: TokenStream
    visual: TokenStream


class ArabicPipeline:
    def __init__(self, config: ArabicPipelineConfig | None = None) -> None:
        self.config = config or ArabicPipelineConfig()
        self._reshaper = ArabicReshaper(
            configuration={
                "delete_harakat": not self.config.preserve_harakat,
                "delete_tatweel": not self.config.preserve_tatweel,
                "support_ligatures": self.config.support_ligatures,
                "support_zwj": self.config.support_zwj,
                "shift_harakat_position": False,
                "use_unshaped_instead_of_isolated": False,
            }
        )

    def process(self, stream: TokenStream) -> ArabicPipelineResult:
        normalized = _normalize_stream(stream)
        encoded, markers = _encode_protected_tokens(normalized)

        shaped_text = self._reshaper.reshape(encoded)
        shaped = _restore_protected_tokens(shaped_text, markers)

        base_dir = None
        if self.config.base_direction is not ArabicBaseDirection.AUTO:
            base_dir = self.config.base_direction.value

        visual_text = get_display(shaped_text, base_dir=base_dir)
        visual = _restore_protected_tokens(visual_text, markers)

        return ArabicPipelineResult(
            normalized=normalized,
            shaped=shaped,
            visual=visual,
        )


def _contains_presentation_form(text: str) -> bool:
    return any(is_presentation_form(character) for character in text)


def _validate_logical_text(text: str) -> None:
    if _MARKER_BOUNDARY in text:
        raise ClassicRetroError(
            ErrorCode.RESERVED_ARABIC_MARKER_CHARACTER,
            "U+FFFC OBJECT REPLACEMENT CHARACTER is reserved for protected-token processing",
        )

    if _contains_presentation_form(text):
        raise ClassicRetroError(
            ErrorCode.PRE_SHAPED_ARABIC_INPUT,
            "Translation text contains Arabic Presentation Forms; use logical Arabic letters",
        )

    controls = sorted({character for character in text if character in EXPLICIT_DIRECTION_CONTROLS})
    if controls:
        values = ", ".join(f"U+{ord(character):04X}" for character in controls)
        raise ClassicRetroError(
            ErrorCode.EXPLICIT_BIDI_CONTROL,
            f"Explicit bidi formatting controls are not allowed in logical translation text: {values}",
        )


def _normalize_stream(stream: TokenStream) -> TokenStream:
    output: list[Token] = []

    for token in stream.tokens:
        if isinstance(token, InlineToken):
            output.append(token)
            continue

        _validate_logical_text(token.text)
        normalized = unicodedata.normalize("NFC", token.text)
        _validate_logical_text(normalized)

        if output and isinstance(output[-1], TextToken):
            previous = output[-1]
            output[-1] = TextToken(previous.text + normalized)
        elif normalized:
            output.append(TextToken(normalized))

    return TokenStream(tuple(output))


def _marker(index: int) -> str:
    if index < 0 or index >= _MAX_MARKERS:
        raise ClassicRetroError(
            ErrorCode.TOO_MANY_INLINE_TOKENS,
            f"One message can contain at most {_MAX_MARKERS} protected inline tokens",
        )

    first_index, second_index = divmod(index, len(_MARKER_CODES))
    first = _MARKER_CODES[first_index]
    second = _MARKER_CODES[second_index]
    return f"{_MARKER_BOUNDARY}{first}{second}{first}{_MARKER_BOUNDARY}"


def _encode_protected_tokens(
    stream: TokenStream,
) -> tuple[str, dict[str, InlineToken]]:
    parts: list[str] = []
    markers: dict[str, InlineToken] = {}

    inline_index = 0
    for token in stream.tokens:
        if isinstance(token, TextToken):
            parts.append(token.text)
            continue

        marker = _marker(inline_index)
        markers[marker] = token
        parts.append(marker)
        inline_index += 1

    return "".join(parts), markers


def _restore_protected_tokens(
    text: str,
    markers: dict[str, InlineToken],
) -> TokenStream:
    output: list[Token] = []
    buffer: list[str] = []
    seen: set[str] = set()
    index = 0

    def flush() -> None:
        if buffer:
            output.append(TextToken("".join(buffer)))
            buffer.clear()

    while index < len(text):
        if text[index] == _MARKER_BOUNDARY:
            candidate = text[index : index + _MARKER_WIDTH]
            token = markers.get(candidate)
            if token is not None:
                flush()
                if candidate in seen:
                    raise ClassicRetroError(
                        ErrorCode.PROTECTED_TOKEN_CORRUPTED,
                        f"Protected token marker appeared more than once: {token.id}",
                    )
                output.append(token)
                seen.add(candidate)
                index += _MARKER_WIDTH
                continue

        buffer.append(text[index])
        index += 1

    flush()

    if seen != set(markers):
        missing = [token.id for marker, token in markers.items() if marker not in seen]
        raise ClassicRetroError(
            ErrorCode.PROTECTED_TOKEN_CORRUPTED,
            "Protected tokens were lost during Arabic processing: " + ", ".join(missing),
        )

    return TokenStream(tuple(output))
