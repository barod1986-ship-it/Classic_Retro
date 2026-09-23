from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias

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

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


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

    @property
    def signature(self) -> str:
        payload = {
            "kind": self.kind.value,
            "movement": self.movement.value,
            "name": self.name,
            "args": dict(self.args),
            "data_hex": self.data_hex,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.kind.value,
            "id": self.id,
            "movement": self.movement.value,
        }
        if self.name is not None:
            result["name"] = self.name
        if self.args:
            result["args"] = dict(self.args)
        if self.data_hex is not None:
            result["data_hex"] = self.data_hex
        return result


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

    def to_dict(self) -> dict[str, Any]:
        return {"tokens": [token.to_dict() for token in self.tokens]}


def token_from_dict(data: Mapping[str, Any]) -> Token:
    token_type = data["type"]
    if token_type == "text":
        return TextToken(text=data["text"])

    return InlineToken(
        id=data["id"],
        kind=TokenKind(token_type),
        movement=TokenMovement(data["movement"]),
        name=data.get("name"),
        args=data.get("args", {}),
        data_hex=data.get("data_hex"),
    )


def stream_from_dict(data: Mapping[str, Any]) -> TokenStream:
    return TokenStream(tokens=tuple(token_from_dict(item) for item in data["tokens"]))


def validate_token_preservation(source: TokenStream, target: TokenStream) -> None:
    source_by_id = {token.id: token for token in source.inline_tokens}
    target_by_id = {token.id: token for token in target.inline_tokens}

    source_ids = set(source_by_id)
    target_ids = set(target_by_id)
    if source_ids != target_ids:
        missing = sorted(source_ids - target_ids)
        extra = sorted(target_ids - source_ids)
        parts: list[str] = []
        if missing:
            parts.append(f"missing={','.join(missing)}")
        if extra:
            parts.append(f"extra={','.join(extra)}")
        raise ClassicRetroError(
            ErrorCode.TOKEN_SET_MISMATCH,
            "Protected token set differs between source and target: " + "; ".join(parts),
        )

    for token_id, source_token in source_by_id.items():
        if source_token.signature != target_by_id[token_id].signature:
            raise ClassicRetroError(
                ErrorCode.TOKEN_DEFINITION_MISMATCH,
                f"Protected token definition changed: {token_id}",
            )

    source_order = [
        token.id
        for token in source.inline_tokens
        if token.movement is TokenMovement.ORDERED
    ]
    target_order = [
        token.id
        for token in target.inline_tokens
        if token.movement is TokenMovement.ORDERED
    ]
    if source_order != target_order:
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            "Ordered inline tokens changed relative order",
        )
