from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from classic_retro.arabic.pipeline import ArabicPipeline
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.font.measure import TextMeasurer
from classic_retro.layout.breaks import BreakProvider, UnisegBreakProvider
from classic_retro.text.tokens import InlineToken, TextToken, Token, TokenKind, TokenStream

_OBJECT_REPLACEMENT = "\ufffc"


class LayoutBreak(StrEnum):
    SOFT = "soft"
    LINE = "line"
    PAGE = "page"
    END = "end"


@dataclass(frozen=True, slots=True)
class LayoutBox:
    max_width_px: int
    max_lines: int | None = None

    def __post_init__(self) -> None:
        if self.max_width_px < 1:
            raise ValueError("max_width_px must be positive")
        if self.max_lines is not None and self.max_lines < 1:
            raise ValueError("max_lines must be positive")


@dataclass(frozen=True, slots=True)
class LayoutLine:
    logical: TokenStream
    visual: TokenStream
    width_px: int
    break_after: LayoutBreak


@dataclass(frozen=True, slots=True)
class LayoutPage:
    lines: tuple[LayoutLine, ...]

    @property
    def height_lines(self) -> int:
        return len(self.lines)


@dataclass(frozen=True, slots=True)
class LayoutResult:
    pages: tuple[LayoutPage, ...]
    line_height_px: int

    @property
    def total_lines(self) -> int:
        return sum(len(page.lines) for page in self.pages)

    @property
    def max_width_px(self) -> int:
        return max(
            (line.width_px for page in self.pages for line in page.lines),
            default=0,
        )


LayoutElement = str | InlineToken


class LayoutEngine:
    def __init__(
        self,
        measurer: TextMeasurer,
        *,
        arabic: ArabicPipeline | None = None,
        breaks: BreakProvider | None = None,
    ) -> None:
        self.measurer = measurer
        self.arabic = arabic or ArabicPipeline()
        self.breaks = breaks or UnisegBreakProvider()

    def layout(self, stream: TokenStream, box: LayoutBox) -> LayoutResult:
        pages: list[LayoutPage] = []
        page_lines: list[LayoutLine] = []
        segment: list[Token] = []

        def append_segment(hard_break: LayoutBreak) -> None:
            nonlocal segment, page_lines
            logical = TokenStream(tuple(segment))
            wrapped = self._wrap_segment(logical, box.max_width_px)

            if not wrapped:
                wrapped = [self._prepare_line(TokenStream(()), LayoutBreak.END)]

            for index, line in enumerate(wrapped):
                break_after = LayoutBreak.SOFT
                if index == len(wrapped) - 1:
                    break_after = hard_break
                page_lines.append(
                    LayoutLine(
                        logical=line.logical,
                        visual=line.visual,
                        width_px=line.width_px,
                        break_after=break_after,
                    )
                )

            self._validate_page_lines(page_lines, box)
            segment = []

        for token in stream.tokens:
            if isinstance(token, InlineToken) and token.kind is TokenKind.LINE_BREAK:
                append_segment(LayoutBreak.LINE)
                continue

            if isinstance(token, InlineToken) and token.kind is TokenKind.PAGE_BREAK:
                append_segment(LayoutBreak.PAGE)
                pages.append(LayoutPage(tuple(page_lines)))
                page_lines = []
                continue

            segment.append(token)

        append_segment(LayoutBreak.END)
        pages.append(LayoutPage(tuple(page_lines)))

        return LayoutResult(
            pages=tuple(pages),
            line_height_px=self.measurer.font.line_height_px,
        )

    def _validate_page_lines(self, lines: list[LayoutLine], box: LayoutBox) -> None:
        if box.max_lines is not None and len(lines) > box.max_lines:
            raise ClassicRetroError(
                ErrorCode.TEXT_BOX_OVERFLOW,
                f"Text page requires {len(lines)} lines; limit is {box.max_lines}",
            )

    def _prepare_line(self, logical: TokenStream, break_after: LayoutBreak) -> LayoutLine:
        processed = self.arabic.process(logical)
        measurement = self.measurer.measure(processed.visual)
        return LayoutLine(
            logical=logical,
            visual=processed.visual,
            width_px=measurement.width_px,
            break_after=break_after,
        )

    def _wrap_segment(self, stream: TokenStream, max_width_px: int) -> list[LayoutLine]:
        elements = _flatten(stream)
        if not elements:
            return []

        shadow = "".join(
            element if isinstance(element, str) else _OBJECT_REPLACEMENT for element in elements
        )
        boundaries = set(self.breaks.boundaries(shadow))
        boundaries.add(len(elements))
        boundaries = _filter_inline_boundaries(
            boundaries,
            elements,
            self.measurer,
        )

        lines: list[LayoutLine] = []
        start = 0

        while start < len(elements):
            candidates = sorted(boundary for boundary in boundaries if boundary > start)
            best_boundary: int | None = None
            best_line: LayoutLine | None = None

            for boundary in candidates:
                logical = _elements_to_stream(elements[start:boundary])
                if boundary < len(elements):
                    logical = _trim_trailing_break_spaces(logical)
                candidate = self._prepare_line(logical, LayoutBreak.SOFT)
                if candidate.width_px <= max_width_px:
                    best_boundary = boundary
                    best_line = candidate

            if best_boundary is None or best_line is None:
                smallest = candidates[0] if candidates else len(elements)
                logical = _elements_to_stream(elements[start:smallest])
                candidate = self._prepare_line(logical, LayoutBreak.SOFT)
                raise ClassicRetroError(
                    ErrorCode.TEXT_OVERFLOW,
                    (
                        f"Unbreakable text requires {candidate.width_px}px; "
                        f"line limit is {max_width_px}px"
                    ),
                )

            lines.append(best_line)
            start = best_boundary

        return lines


def _flatten(stream: TokenStream) -> list[LayoutElement]:
    output: list[LayoutElement] = []
    for token in stream.tokens:
        if isinstance(token, TextToken):
            output.extend(token.text)
        else:
            output.append(token)
    return output


def _elements_to_stream(elements: list[LayoutElement]) -> TokenStream:
    output: list[Token] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            output.append(TextToken("".join(buffer)))
            buffer.clear()

    for element in elements:
        if isinstance(element, str):
            buffer.append(element)
            continue
        flush()
        output.append(element)

    flush()
    return TokenStream(tuple(output))


def _filter_inline_boundaries(
    boundaries: set[int],
    elements: list[LayoutElement],
    measurer: TextMeasurer,
) -> set[int]:
    filtered = set(boundaries)
    end = len(elements)

    for boundary in tuple(filtered):
        if boundary == end:
            continue

        if boundary > 0 and isinstance(elements[boundary - 1], InlineToken):
            metric = measurer.inline_metrics.resolve(elements[boundary - 1])
            if not metric.break_after:
                filtered.discard(boundary)
                continue

        if boundary < end and isinstance(elements[boundary], InlineToken):
            metric = measurer.inline_metrics.resolve(elements[boundary])
            if not metric.break_before:
                filtered.discard(boundary)

    return filtered


def _trim_trailing_break_spaces(stream: TokenStream) -> TokenStream:
    tokens = list(stream.tokens)
    while tokens and isinstance(tokens[-1], TextToken):
        trimmed = tokens[-1].text.rstrip(" \t")
        if trimmed:
            tokens[-1] = TextToken(trimmed)
            break
        tokens.pop()

    return TokenStream(tuple(tokens))
