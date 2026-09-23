from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document
from classic_retro.text.tokens import TokenKind, TokenMovement, TokenScalar


class UnknownDecodePolicy(StrEnum):
    ERROR = "error"
    OPAQUE = "opaque"


def _parse_hex(value: str, *, label: str) -> bytes:
    normalized = "".join(value.split()).lower()
    if not normalized or len(normalized) % 2:
        raise ClassicRetroError(
            ErrorCode.INVALID_CODEC_PROFILE,
            f"{label} must contain a non-empty even-length hexadecimal byte string",
        )
    try:
        return bytes.fromhex(normalized)
    except ValueError as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_CODEC_PROFILE,
            f"{label} contains invalid hexadecimal data",
        ) from exc


@dataclass(frozen=True, slots=True)
class GlyphCode:
    sequence: str
    data: bytes

    def __post_init__(self) -> None:
        if not self.sequence:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                "Glyph sequence cannot be empty",
            )
        if not self.data:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                f"Glyph {self.sequence!r} cannot encode to empty bytes",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GlyphCode:
        return cls(
            sequence=data["sequence"],
            data=_parse_hex(data["bytes_hex"], label=f"glyph {data['sequence']!r}"),
        )


@dataclass(frozen=True, slots=True)
class InlineCode:
    kind: TokenKind
    movement: TokenMovement
    data: bytes
    name: str | None = None
    args: Mapping[str, TokenScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in {
            TokenKind.VARIABLE,
            TokenKind.CONTROL,
            TokenKind.LINE_BREAK,
            TokenKind.PAGE_BREAK,
        }:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                f"Unsupported fixed inline token kind: {self.kind.value}",
            )
        if self.kind in {TokenKind.VARIABLE, TokenKind.CONTROL} and not self.name:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                f"{self.kind.value} codec entry requires a name",
            )
        if self.kind in {TokenKind.LINE_BREAK, TokenKind.PAGE_BREAK} and self.name is not None:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                f"{self.kind.value} codec entry cannot have a name",
            )
        if not self.data:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                "Inline token cannot encode to empty bytes",
            )
        object.__setattr__(self, "args", MappingProxyType(dict(self.args)))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InlineCode:
        return cls(
            kind=TokenKind(data["type"]),
            movement=TokenMovement(data["movement"]),
            name=data.get("name"),
            args=data.get("args", {}),
            data=_parse_hex(
                data["bytes_hex"],
                label=f"inline code {data.get('name', data['type'])}",
            ),
        )

    @property
    def semantic_key(self) -> tuple[object, ...]:
        return (
            self.kind,
            self.movement,
            self.name,
            tuple(sorted(self.args.items())),
        )


@dataclass(frozen=True, slots=True)
class TerminatorCode:
    id: str
    data: bytes

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                "Terminator id cannot be empty",
            )
        if not self.data:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                f"Terminator {self.id} cannot be empty",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TerminatorCode:
        return cls(
            id=data["id"],
            data=_parse_hex(data["bytes_hex"], label=f"terminator {data['id']}"),
        )


@dataclass(frozen=True, slots=True)
class CodecProfile:
    id: str
    glyphs: tuple[GlyphCode, ...]
    inline_codes: tuple[InlineCode, ...] = ()
    terminators: tuple[TerminatorCode, ...] = ()
    unknown_decode: UnknownDecodePolicy = UnknownDecodePolicy.ERROR
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_CODEC_PROFILE,
                "Codec profile id cannot be empty",
            )

        glyph_sequences: set[str] = set()
        inline_keys: set[tuple[object, ...]] = set()
        terminator_ids: set[str] = set()

        for glyph in self.glyphs:
            if glyph.sequence in glyph_sequences:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_CODEC_SYMBOL,
                    f"Duplicate codec glyph sequence: {glyph.sequence!r}",
                )
            glyph_sequences.add(glyph.sequence)

        for inline in self.inline_codes:
            if inline.semantic_key in inline_keys:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_CODEC_SYMBOL,
                    f"Duplicate inline codec definition: {inline.name or inline.kind.value}",
                )
            inline_keys.add(inline.semantic_key)

        for terminator in self.terminators:
            if terminator.id in terminator_ids:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_CODEC_SYMBOL,
                    f"Duplicate terminator id: {terminator.id}",
                )
            terminator_ids.add(terminator.id)

        static_codes: list[tuple[str, bytes]] = []
        static_codes.extend((f"glyph:{glyph.sequence}", glyph.data) for glyph in self.glyphs)
        static_codes.extend(
            (f"inline:{inline.name or inline.kind.value}", inline.data)
            for inline in self.inline_codes
        )
        static_codes.extend(
            (f"terminator:{terminator.id}", terminator.data) for terminator in self.terminators
        )
        _validate_prefix_free(static_codes)

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CodecProfile:
        validate_document("text-codec-profile.schema.json", data)
        return cls(
            id=data["id"],
            glyphs=tuple(GlyphCode.from_dict(item) for item in data["glyphs"]),
            inline_codes=tuple(InlineCode.from_dict(item) for item in data.get("inline_codes", [])),
            terminators=tuple(
                TerminatorCode.from_dict(item) for item in data.get("terminators", [])
            ),
            unknown_decode=UnknownDecodePolicy(data.get("unknown_decode", "error")),
            metadata=data.get("metadata", {}),
        )


def _validate_prefix_free(codes: list[tuple[str, bytes]]) -> None:
    ordered = sorted(codes, key=lambda item: (len(item[1]), item[1], item[0]))
    for index, (label, data) in enumerate(ordered):
        for other_label, other_data in ordered[index + 1 :]:
            if other_data.startswith(data):
                relation = "duplicates" if other_data == data else "is a prefix of"
                raise ClassicRetroError(
                    ErrorCode.AMBIGUOUS_CODEC_PREFIX,
                    f"{label} {relation} {other_label}",
                )


def load_codec_profile(path: Path) -> CodecProfile:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_CODEC_PROFILE,
            f"Could not read codec profile {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise ClassicRetroError(
            ErrorCode.INVALID_CODEC_PROFILE,
            "Codec profile root must be an object",
        )

    return CodecProfile.from_dict(data)
