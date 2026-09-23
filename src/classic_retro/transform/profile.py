from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document
from classic_retro.transform.base import TransformPipeline
from classic_retro.transform.registry import TransformRegistry


@dataclass(frozen=True, slots=True)
class TransformStageSpec:
    codec: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class TransformProfile:
    id: str
    stages: tuple[TransformStageSpec, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TransformProfile:
        validate_document("transform-pipeline.schema.json", data)
        return cls(
            id=data["id"],
            stages=tuple(
                TransformStageSpec(
                    codec=item["codec"],
                    options=item.get("options", {}),
                )
                for item in data["stages"]
            ),
        )


def build_pipeline(
    profile: TransformProfile,
    registry: TransformRegistry,
) -> TransformPipeline:
    transforms = tuple(registry.create(stage.codec, stage.options) for stage in profile.stages)
    return TransformPipeline(profile.id, transforms)


def load_transform_profile(path: Path) -> TransformProfile:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            f"Could not read transform profile {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            "Transform profile root must be an object",
        )

    return TransformProfile.from_dict(data)
