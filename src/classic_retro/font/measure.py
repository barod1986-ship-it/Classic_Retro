from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.model import FontProfile, ResolvedGlyph
from classic_retro.text.tokens import InlineToken, TextToken, TokenKind, TokenStream


@dataclass(frozen=True, slots=True)
class InlineLayoutMetric:
    advance_px: int
    break_before: bool = True
    break_after: bool = True

    def __post_init__(self) -> None:
        if self.advance_px < 0:
            raise ValueError("advance_px cannot be negative")


class InlineMetricResolver:
    def __init__(
        self,
        *,
        by_id: Mapping[str, InlineLayoutMetric] | None = None,
        by_name: Mapping[str, InlineLayoutMetric] | None = None,
    ) -> None:
        self._by_id = dict(by_id or {})
        self._by_name = dict(by_name or {})

    def resolve(self, token: InlineToken) -> InlineLayoutMetric:
        if token.id in self._by_id:
            return self._by_id[token.id]
        if token.name is not None and token.name in self._by_name:
            return self._by_name[token.name]

        if token.kind is TokenKind.VARIABLE:
            raise ClassicRetroError(
                ErrorCode.INLINE_WIDTH_UNKNOWN,
                f"No maximum layout width is defined for runtime variable {token.name or token.id}",
            )

        if token.kind in {TokenKind.LINE_BREAK, TokenKind.PAGE_BREAK}:
            return InlineLayoutMetric(0, break_before=False, break_after=False)

        return InlineLayoutMetric(0, break_before=False, break_after=False)


@dataclass(frozen=True, slots=True)
class TextMeasurement:
    width_px: int
    glyphs: tuple[ResolvedGlyph, ...]
    inline_tokens: tuple[InlineToken, ...]


class TextMeasurer:
    def __init__(
        self,
        font: FontProfile,
        inline_metrics: InlineMetricResolver | None = None,
    ) -> None:
        self.font = font
        self.inline_metrics = inline_metrics or InlineMetricResolver()

    def measure(self, stream: TokenStream) -> TextMeasurement:
        width = 0
        glyphs: list[ResolvedGlyph] = []
        inline_tokens: list[InlineToken] = []

        for token in stream.tokens:
            if isinstance(token, TextToken):
                resolved = self.font.resolve_text(token.text)
                glyphs.extend(resolved)
                width += sum(item.glyph.advance_px for item in resolved)
                continue

            metric = self.inline_metrics.resolve(token)
            width += metric.advance_px
            inline_tokens.append(token)

        return TextMeasurement(
            width_px=width,
            glyphs=tuple(glyphs),
            inline_tokens=tuple(inline_tokens),
        )
