from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document


@dataclass(frozen=True, order=True, slots=True)
class ByteRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE,
                f"Invalid byte range [0x{self.start:X}, 0x{self.end:X})",
            )

    @classmethod
    def from_start_size(cls, start: int, size: int) -> ByteRange:
        if size < 0:
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE,
                f"Range size cannot be negative: {size}",
            )
        return cls(start, start + size)

    @property
    def size(self) -> int:
        return self.end - self.start

    def overlaps(self, other: ByteRange) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: ByteRange) -> bool:
        return self.start <= other.start and other.end <= self.end


class ByteOrder(StrEnum):
    LITTLE = "little"
    BIG = "big"


class ReferenceBaseKind(StrEnum):
    ZERO = "zero"
    CONSTANT = "constant"
    SITE = "site"


@dataclass(frozen=True, slots=True)
class IntegerReferenceCodec:
    size_bytes: int
    byte_order: ByteOrder
    signed: bool = False
    scale: int = 1
    base_kind: ReferenceBaseKind = ReferenceBaseKind.ZERO
    base_value: int = 0
    addend: int = 0

    def __post_init__(self) -> None:
        if self.size_bytes < 1 or self.size_bytes > 8:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Integer reference size_bytes must be between 1 and 8",
            )
        if self.scale < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Integer reference scale must be positive",
            )
        if self.base_kind is ReferenceBaseKind.ZERO and self.base_value != 0:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "zero-based references cannot define base_value",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IntegerReferenceCodec:
        return cls(
            size_bytes=data["size_bytes"],
            byte_order=ByteOrder(data["byte_order"]),
            signed=data.get("signed", False),
            scale=data.get("scale", 1),
            base_kind=ReferenceBaseKind(data.get("base_kind", "zero")),
            base_value=data.get("base_value", 0),
            addend=data.get("addend", 0),
        )

    def _base(self, site_offset: int) -> int:
        if self.base_kind is ReferenceBaseKind.ZERO:
            return 0
        if self.base_kind is ReferenceBaseKind.CONSTANT:
            return self.base_value
        return site_offset + self.base_value

    def decode(self, raw: bytes, *, site_offset: int) -> int:
        if len(raw) != self.size_bytes:
            raise ClassicRetroError(
                ErrorCode.REFERENCE_OUT_OF_BOUNDS,
                f"Expected {self.size_bytes} reference bytes, got {len(raw)}",
            )
        stored = int.from_bytes(raw, self.byte_order.value, signed=self.signed)
        return self._base(site_offset) + stored * self.scale + self.addend

    def encode(self, target_offset: int, *, site_offset: int) -> bytes:
        numerator = target_offset - self._base(site_offset) - self.addend
        if numerator % self.scale:
            raise ClassicRetroError(
                ErrorCode.REFERENCE_ALIGNMENT_ERROR,
                (f"Target 0x{target_offset:X} cannot be represented with scale {self.scale}"),
            )

        stored = numerator // self.scale
        bits = self.size_bytes * 8
        if self.signed:
            minimum = -(1 << (bits - 1))
            maximum = (1 << (bits - 1)) - 1
        else:
            minimum = 0
            maximum = (1 << bits) - 1

        if not minimum <= stored <= maximum:
            raise ClassicRetroError(
                ErrorCode.REFERENCE_VALUE_OUT_OF_RANGE,
                (f"Stored reference value {stored} does not fit {self.size_bytes} byte(s)"),
            )

        return stored.to_bytes(
            self.size_bytes,
            self.byte_order.value,
            signed=self.signed,
        )


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    id: str
    source: ByteRange
    alignment: int = 1
    allow_in_place: bool = True

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Resource id cannot be empty",
            )
        if self.source.size < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Resource {self.id} cannot have an empty source range",
            )
        if self.alignment < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Resource {self.id} alignment must be positive",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResourceSpec:
        return cls(
            id=data["id"],
            source=ByteRange.from_start_size(data["start"], data["size"]),
            alignment=data.get("alignment", 1),
            allow_in_place=data.get("allow_in_place", True),
        )


@dataclass(frozen=True, slots=True)
class ReferenceSite:
    id: str
    offset: int
    target_resource_id: str
    codec: IntegerReferenceCodec

    def __post_init__(self) -> None:
        if not self.id or not self.target_resource_id:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Reference id and target_resource_id cannot be empty",
            )
        if self.offset < 0:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Reference {self.id} offset cannot be negative",
            )

    @property
    def span(self) -> ByteRange:
        return ByteRange.from_start_size(self.offset, self.codec.size_bytes)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReferenceSite:
        return cls(
            id=data["id"],
            offset=data["offset"],
            target_resource_id=data["target_resource_id"],
            codec=IntegerReferenceCodec.from_dict(data["integer"]),
        )


@dataclass(frozen=True, slots=True)
class SafeRegion:
    id: str
    span: ByteRange
    expected_fill_byte: int | None = None

    def __post_init__(self) -> None:
        if not self.id or self.span.size < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Safe region must have an id and non-empty range",
            )
        if self.expected_fill_byte is not None and not 0 <= self.expected_fill_byte <= 0xFF:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Safe region {self.id} expected_fill_byte must be 0..255",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SafeRegion:
        return cls(
            id=data["id"],
            span=ByteRange.from_start_size(data["start"], data["size"]),
            expected_fill_byte=data.get("expected_fill_byte"),
        )


@dataclass(frozen=True, slots=True)
class RebuildPlan:
    id: str
    resources: tuple[ResourceSpec, ...]
    references: tuple[ReferenceSite, ...] = ()
    safe_regions: tuple[SafeRegion, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                "Rebuild plan id cannot be empty",
            )

        _require_unique("resource", (item.id for item in self.resources))
        _require_unique("reference", (item.id for item in self.references))
        _require_unique("safe region", (item.id for item in self.safe_regions))

        resource_ids = {item.id for item in self.resources}
        for reference in self.references:
            if reference.target_resource_id not in resource_ids:
                raise ClassicRetroError(
                    ErrorCode.INVALID_REBUILD_PLAN,
                    (
                        f"Reference {reference.id} targets unknown resource "
                        f"{reference.target_resource_id}"
                    ),
                )

        _reject_overlaps(
            "resource",
            [(item.id, item.source) for item in self.resources],
        )
        _reject_overlaps(
            "reference",
            [(item.id, item.span) for item in self.references],
        )
        _reject_overlaps(
            "safe region",
            [(item.id, item.span) for item in self.safe_regions],
        )

        occupied = [
            *(("resource:" + item.id, item.source) for item in self.resources),
            *(("reference:" + item.id, item.span) for item in self.references),
        ]
        for region in self.safe_regions:
            for label, span in occupied:
                if region.span.overlaps(span):
                    raise ClassicRetroError(
                        ErrorCode.INVALID_REBUILD_PLAN,
                        f"Safe region {region.id} overlaps {label}",
                    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RebuildPlan:
        validate_document("rebuild-plan.schema.json", data)
        return cls(
            id=data["id"],
            resources=tuple(ResourceSpec.from_dict(item) for item in data["resources"]),
            references=tuple(ReferenceSite.from_dict(item) for item in data.get("references", [])),
            safe_regions=tuple(SafeRegion.from_dict(item) for item in data.get("safe_regions", [])),
        )


def _require_unique(label: str, values) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Duplicate {label} id: {value}",
            )
        seen.add(value)


def _reject_overlaps(label: str, items: list[tuple[str, ByteRange]]) -> None:
    ordered = sorted(items, key=lambda item: item[1])
    for (_, previous), (current_id, current) in zip(ordered, ordered[1:], strict=False):
        if previous.overlaps(current):
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PLAN,
                f"Overlapping {label} range near {current_id}",
            )


def load_rebuild_plan(path: Path) -> RebuildPlan:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_REBUILD_PLAN,
            f"Could not read rebuild plan {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise ClassicRetroError(
            ErrorCode.INVALID_REBUILD_PLAN,
            "Rebuild plan root must be an object",
        )

    return RebuildPlan.from_dict(data)
