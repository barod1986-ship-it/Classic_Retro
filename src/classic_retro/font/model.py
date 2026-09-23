from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document


@dataclass(frozen=True, slots=True)
class GlyphMetrics:
    id: str
    sequence: str
    advance_px: int
    ink_width_px: int | None = None
    ink_height_px: int | None = None
    offset_x_px: int = 0
    offset_y_px: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                "Glyph id cannot be empty",
            )
        if not self.sequence:
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                f"Glyph {self.id} sequence cannot be empty",
            )
        if self.advance_px < 0:
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                f"Glyph {self.id} advance_px cannot be negative",
            )
        for field_name in ("ink_width_px", "ink_height_px"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ClassicRetroError(
                    ErrorCode.INVALID_FONT_PROFILE,
                    f"Glyph {self.id} {field_name} cannot be negative",
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GlyphMetrics:
        return cls(
            id=data["id"],
            sequence=data["sequence"],
            advance_px=data["advance_px"],
            ink_width_px=data.get("ink_width_px"),
            ink_height_px=data.get("ink_height_px"),
            offset_x_px=data.get("offset_x_px", 0),
            offset_y_px=data.get("offset_y_px", 0),
        )


@dataclass(frozen=True, slots=True)
class ResolvedGlyph:
    glyph: GlyphMetrics
    source: str


@dataclass(frozen=True, slots=True)
class FontProfile:
    id: str
    line_height_px: int
    glyphs: tuple[GlyphMetrics, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)
    _by_first: Mapping[str, tuple[GlyphMetrics, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                "Font profile id cannot be empty",
            )
        if self.line_height_px < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_FONT_PROFILE,
                "line_height_px must be positive",
            )

        ids: set[str] = set()
        sequences: set[str] = set()
        by_first: dict[str, list[GlyphMetrics]] = {}

        for glyph in self.glyphs:
            if glyph.id in ids:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_GLYPH_ID,
                    f"Duplicate glyph id: {glyph.id}",
                )
            if glyph.sequence in sequences:
                codepoints = " ".join(f"U+{ord(char):04X}" for char in glyph.sequence)
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_GLYPH_SEQUENCE,
                    f"Duplicate glyph sequence: {codepoints}",
                )

            ids.add(glyph.id)
            sequences.add(glyph.sequence)
            by_first.setdefault(glyph.sequence[0], []).append(glyph)

        ordered = {
            first: tuple(sorted(items, key=lambda item: len(item.sequence), reverse=True))
            for first, items in by_first.items()
        }
        object.__setattr__(self, "_by_first", MappingProxyType(ordered))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FontProfile:
        validate_document("font-profile.schema.json", data)
        return cls(
            id=data["id"],
            line_height_px=data["line_height_px"],
            glyphs=tuple(GlyphMetrics.from_dict(item) for item in data["glyphs"]),
            metadata=data.get("metadata", {}),
        )

    def resolve_text(self, text: str) -> tuple[ResolvedGlyph, ...]:
        resolved: list[ResolvedGlyph] = []
        index = 0

        while index < len(text):
            candidates = self._by_first.get(text[index], ())
            match = next(
                (glyph for glyph in candidates if text.startswith(glyph.sequence, index)),
                None,
            )
            if match is None:
                character = text[index]
                raise ClassicRetroError(
                    ErrorCode.MISSING_GLYPH,
                    f"Font {self.id} has no glyph for U+{ord(character):04X} {character!r}",
                )

            resolved.append(ResolvedGlyph(glyph=match, source=match.sequence))
            index += len(match.sequence)

        return tuple(resolved)


def load_font_profile(path: Path) -> FontProfile:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_FONT_PROFILE,
            f"Could not read font profile {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise ClassicRetroError(
            ErrorCode.INVALID_FONT_PROFILE,
            "Font profile root must be an object",
        )

    return FontProfile.from_dict(data)
