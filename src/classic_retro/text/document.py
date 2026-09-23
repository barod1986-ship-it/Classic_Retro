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
from classic_retro.text.tokens import TokenStream, stream_from_dict, validate_token_preservation


class TranslationStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class LayoutConstraints:
    box: str | None = None
    max_width_px: int | None = None
    max_lines: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> LayoutConstraints:
        if data is None:
            return cls()
        return cls(
            box=data.get("box"),
            max_width_px=data.get("max_width_px"),
            max_lines=data.get("max_lines"),
        )


@dataclass(frozen=True, slots=True)
class TranslationEntry:
    id: str
    source: TokenStream
    target: TokenStream
    status: TranslationStatus = TranslationStatus.DRAFT
    context: str | None = None
    notes: str | None = None
    constraints: LayoutConstraints = field(default_factory=LayoutConstraints)

    def __post_init__(self) -> None:
        validate_token_preservation(self.source, self.target)
        if (
            self.status is TranslationStatus.FINAL
            and self.source.visible_text
            and not self.target.visible_text
        ):
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"Final entry {self.id} has no translated visible text",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TranslationEntry:
        return cls(
            id=data["id"],
            source=stream_from_dict(data["source"]),
            target=stream_from_dict(data["target"]),
            status=TranslationStatus(data.get("status", "draft")),
            context=data.get("context"),
            notes=data.get("notes"),
            constraints=LayoutConstraints.from_dict(data.get("constraints")),
        )


@dataclass(frozen=True, slots=True)
class TranslationDocument:
    schema_version: str
    game_id: str
    source_language: str
    target_language: str
    entries: tuple[TranslationEntry, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_ENTRY_ID,
                    f"Duplicate translation entry id: {entry.id}",
                )
            seen.add(entry.id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TranslationDocument:
        validate_document("translation.schema.json", data)
        return cls(
            schema_version=data["schema_version"],
            game_id=data["game_id"],
            source_language=data["source_language"],
            target_language=data["target_language"],
            entries=tuple(TranslationEntry.from_dict(item) for item in data["entries"]),
        )

    def summary(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in TranslationStatus}
        for entry in self.entries:
            counts[entry.status.value] += 1
        return {
            "schema_version": self.schema_version,
            "game_id": self.game_id,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "entries": len(self.entries),
            "status": counts,
        }


def load_translation_file(path: Path) -> TranslationDocument:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"Could not read translation document {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            "Translation document root must be an object",
        )

    return TranslationDocument.from_dict(data)
