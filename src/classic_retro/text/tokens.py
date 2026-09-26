"""The text model the engines and the Arabic pipeline share.

A message is a ``TokenStream``: runs of text (``TextToken``) and the engine's
commands between them (``InlineToken``: a wait, a colour, a line or page break,
a name), each with an id unique in its message. ``classic_retro.text.commands``
says how engines carry a command's codes; ``classic_retro.arabic`` shapes the
text and puts it in drawing order, keeping every token whole.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias

from classic_retro.core.errors import ClassicRetroError, ErrorCode

TokenScalar: TypeAlias = str | int | bool


class TokenKind(StrEnum):
    VARIABLE = "variable"
    CONTROL = "control"
    LINE_BREAK = "line_break"
    PAGE_BREAK = "page_break"
    OPAQUE = "opaque"


class TokenMovement(StrEnum):
    FREE = "free"
    ORDERED = "ordered"


@dataclass(frozen=True, slots=True)
class TextToken:
    text: str


@dataclass(frozen=True, slots=True)
class InlineToken:
    id: str
    kind: TokenKind
    movement: TokenMovement
    name: str | None = None
    args: Mapping[str, TokenScalar] = field(default_factory=dict)
    data_hex: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                "Inline token id cannot be empty",
            )
        if self.kind in {TokenKind.VARIABLE, TokenKind.CONTROL} and not self.name:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"{self.kind.value} token {self.id} requires a name",
            )
        if self.kind is TokenKind.OPAQUE:
            if not self.data_hex:
                raise ClassicRetroError(
                    ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                    f"opaque token {self.id} requires data_hex",
                )
            normalized = self.data_hex.lower()
            if len(normalized) % 2 or any(char not in "0123456789abcdef" for char in normalized):
                raise ClassicRetroError(
                    ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                    f"opaque token {self.id} has invalid data_hex",
                )
            object.__setattr__(self, "data_hex", normalized)
        elif self.data_hex is not None:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"{self.kind.value} token {self.id} cannot carry data_hex",
            )

        for key, value in self.args.items():
            if not isinstance(key, str) or not isinstance(value, (str, int, bool)):
                raise ClassicRetroError(
                    ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                    f"token {self.id} args must use string keys and scalar values",
                )

        object.__setattr__(self, "args", MappingProxyType(dict(self.args)))


Token: TypeAlias = TextToken | InlineToken


@dataclass(frozen=True, slots=True)
class TokenStream:
    tokens: tuple[Token, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for token in self.tokens:
            if not isinstance(token, InlineToken):
                continue
            if token.id in seen:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_TOKEN_ID,
                    f"Duplicate inline token id: {token.id}",
                )
            seen.add(token.id)

    @property
    def visible_text(self) -> str:
        return "".join(token.text for token in self.tokens if isinstance(token, TextToken))

    @property
    def inline_tokens(self) -> tuple[InlineToken, ...]:
        return tuple(token for token in self.tokens if isinstance(token, InlineToken))
