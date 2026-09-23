from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.metadata import entry_points
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.transform.base import ResourceTransform
from classic_retro.transform.builtin import (
    build_gzip,
    build_identity,
    build_raw_deflate,
    build_zlib,
)

TRANSFORM_ENTRY_POINT_GROUP = "classic_retro.transforms.v1"
TransformBuilder = Callable[[Mapping[str, Any]], ResourceTransform]


class TransformRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, TransformBuilder] = {}

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._builders))

    def register(self, transform_id: str, builder: TransformBuilder) -> None:
        if not transform_id:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSFORM_PROFILE,
                "Transform id cannot be empty",
            )
        if transform_id in self._builders:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_ID_CONFLICT,
                f"Duplicate transform id: {transform_id}",
            )
        self._builders[transform_id] = builder

    def create(
        self,
        transform_id: str,
        options: Mapping[str, Any] | None = None,
    ) -> ResourceTransform:
        builder = self._builders.get(transform_id)
        if builder is None:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_NOT_FOUND,
                f"Unknown transform: {transform_id}",
            )
        transform = builder(dict(options or {}))
        if not isinstance(transform, ResourceTransform):
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_TYPE_ERROR,
                f"Transform builder {transform_id} returned an invalid object",
            )
        return transform

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group=TRANSFORM_ENTRY_POINT_GROUP):
            try:
                builder = entry_point.load()
            except Exception as exc:
                raise ClassicRetroError(
                    ErrorCode.TRANSFORM_LOAD_FAILED,
                    f"Failed to load transform {entry_point.name}: {exc}",
                ) from exc
            if not callable(builder):
                raise ClassicRetroError(
                    ErrorCode.TRANSFORM_TYPE_ERROR,
                    f"Transform entry point {entry_point.name} is not callable",
                )
            self.register(entry_point.name, builder)


def build_transform_registry(*, load_external: bool = True) -> TransformRegistry:
    registry = TransformRegistry()
    registry.register("identity", build_identity)
    registry.register("zlib", build_zlib)
    registry.register("raw-deflate", build_raw_deflate)
    registry.register("gzip", build_gzip)

    if load_external:
        registry.load_entry_points()

    return registry
