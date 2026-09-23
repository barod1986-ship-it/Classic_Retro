from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode


@dataclass(frozen=True, slots=True)
class DecodedTransform:
    payload: bytes
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ResourceTransform(ABC):
    id: str

    @abstractmethod
    def decode(self, data: bytes) -> DecodedTransform:
        """Decode exactly one resource payload."""

    @abstractmethod
    def encode(self, payload: bytes, metadata: Mapping[str, Any]) -> bytes:
        """Encode one decoded resource payload."""


@dataclass(frozen=True, slots=True)
class TransformStageSnapshot:
    transform_id: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class TransformSnapshot:
    pipeline_id: str
    original_encoded: bytes
    decoded_sha256: str
    decoded_size: int
    stages: tuple[TransformStageSnapshot, ...]


@dataclass(frozen=True, slots=True)
class TransformVerification:
    decoded_size: int
    original_size: int
    rebuilt_size: int
    reused_original: bool
    forced_reencode_exact: bool


class TransformPipeline:
    def __init__(self, pipeline_id: str, transforms: tuple[ResourceTransform, ...]) -> None:
        if not pipeline_id:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSFORM_PROFILE,
                "Transform pipeline id cannot be empty",
            )
        if not transforms:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSFORM_PROFILE,
                "Transform pipeline must contain at least one stage",
            )
        self.id = pipeline_id
        self.transforms = transforms

    def extract(self, data: bytes) -> tuple[bytes, TransformSnapshot]:
        current = data
        stages: list[TransformStageSnapshot] = []

        for transform in self.transforms:
            decoded = transform.decode(current)
            stages.append(
                TransformStageSnapshot(
                    transform_id=transform.id,
                    metadata=decoded.metadata,
                )
            )
            current = decoded.payload

        snapshot = TransformSnapshot(
            pipeline_id=self.id,
            original_encoded=data,
            decoded_sha256=_sha256(current),
            decoded_size=len(current),
            stages=tuple(stages),
        )
        return current, snapshot

    def rebuild(
        self,
        snapshot: TransformSnapshot,
        payload: bytes,
        *,
        reuse_original: bool = True,
    ) -> bytes:
        self._validate_snapshot(snapshot)

        if (
            reuse_original
            and len(payload) == snapshot.decoded_size
            and _sha256(payload) == snapshot.decoded_sha256
        ):
            return snapshot.original_encoded

        current = payload
        for transform, stage in zip(
            reversed(self.transforms),
            reversed(snapshot.stages),
            strict=True,
        ):
            encoded = transform.encode(current, stage.metadata)
            decoded = transform.decode(encoded)
            if decoded.payload != current:
                raise ClassicRetroError(
                    ErrorCode.TRANSFORM_ROUNDTRIP_FAILED,
                    f"Transform {transform.id} failed encode/decode verification",
                )
            current = encoded

        return current

    def verify(self, data: bytes) -> TransformVerification:
        payload, snapshot = self.extract(data)
        rebuilt = self.rebuild(snapshot, payload)
        if rebuilt != data:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_ROUNDTRIP_FAILED,
                "Unchanged transformed resource did not reuse original bytes",
            )

        forced = self.rebuild(snapshot, payload, reuse_original=False)
        forced_payload, _ = self.extract(forced)
        if forced_payload != payload:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_ROUNDTRIP_FAILED,
                "Forced transform re-encode changed decoded payload",
            )

        return TransformVerification(
            decoded_size=len(payload),
            original_size=len(data),
            rebuilt_size=len(rebuilt),
            reused_original=True,
            forced_reencode_exact=forced == data,
        )

    def _validate_snapshot(self, snapshot: TransformSnapshot) -> None:
        if snapshot.pipeline_id != self.id:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_SNAPSHOT_MISMATCH,
                (
                    f"Snapshot belongs to pipeline {snapshot.pipeline_id}; "
                    f"current pipeline is {self.id}"
                ),
            )

        transform_ids = tuple(transform.id for transform in self.transforms)
        snapshot_ids = tuple(stage.transform_id for stage in snapshot.stages)
        if transform_ids != snapshot_ids:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_SNAPSHOT_MISMATCH,
                "Transform stage sequence differs from extraction snapshot",
            )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
