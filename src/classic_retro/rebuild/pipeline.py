from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.allocator import RegionAllocator
from classic_retro.rebuild.image import BinaryEditor
from classic_retro.rebuild.model import ByteRange, RebuildPlan, ReferenceSite, ResourceSpec


@dataclass(frozen=True, slots=True)
class ResourcePlacement:
    resource_id: str
    original: ByteRange
    rebuilt: ByteRange
    relocated: bool
    region_id: str | None = None


@dataclass(frozen=True, slots=True)
class RebuildResult:
    image: bytes
    placements: Mapping[str, ResourcePlacement]
    writes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "placements", MappingProxyType(dict(self.placements)))

    @property
    def relocated_resources(self) -> tuple[str, ...]:
        return tuple(
            resource_id
            for resource_id, placement in self.placements.items()
            if placement.relocated
        )


def extract_resources(original: bytes, plan: RebuildPlan) -> dict[str, bytes]:
    _validate_plan_against_image(original, plan)
    return {
        resource.id: original[resource.source.start : resource.source.end]
        for resource in plan.resources
    }


def rebuild_resources(
    original: bytes,
    plan: RebuildPlan,
    payloads: Mapping[str, bytes],
) -> RebuildResult:
    _validate_plan_against_image(original, plan)

    expected_ids = {resource.id for resource in plan.resources}
    supplied_ids = set(payloads)
    if supplied_ids != expected_ids:
        missing = sorted(expected_ids - supplied_ids)
        extra = sorted(supplied_ids - expected_ids)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ClassicRetroError(
            ErrorCode.RESOURCE_SET_MISMATCH,
            "Rebuild payload set differs from plan: " + "; ".join(details),
        )

    _validate_reference_targets(original, plan)
    allocator = RegionAllocator(plan.safe_regions, original)
    placements: dict[str, ResourcePlacement] = {}

    for resource in plan.resources:
        payload = payloads[resource.id]
        if not payload:
            raise ClassicRetroError(
                ErrorCode.INVALID_REBUILD_PAYLOAD,
                f"Resource {resource.id} cannot rebuild to zero bytes",
            )

        if resource.allow_in_place and len(payload) <= resource.source.size:
            rebuilt = ByteRange.from_start_size(resource.source.start, len(payload))
            placements[resource.id] = ResourcePlacement(
                resource_id=resource.id,
                original=resource.source,
                rebuilt=rebuilt,
                relocated=False,
            )
            continue

        allocation = allocator.allocate(len(payload), alignment=resource.alignment)
        placements[resource.id] = ResourcePlacement(
            resource_id=resource.id,
            original=resource.source,
            rebuilt=allocation.span,
            relocated=True,
            region_id=allocation.region_id,
        )

    editor = BinaryEditor(original)

    for resource in plan.resources:
        payload = payloads[resource.id]
        placement = placements[resource.id]
        current = original[placement.rebuilt.start : placement.rebuilt.end]
        if payload != current:
            editor.write(
                placement.rebuilt.start,
                payload,
                label=f"resource:{resource.id}",
            )

    for reference in plan.references:
        placement = placements[reference.target_resource_id]
        encoded = reference.codec.encode(
            placement.rebuilt.start,
            site_offset=reference.offset,
        )
        current = original[reference.offset : reference.offset + len(encoded)]
        if encoded != current:
            editor.write(
                reference.offset,
                encoded,
                label=f"reference:{reference.id}",
            )

    return RebuildResult(
        image=editor.bytes,
        placements=placements,
        writes=len(editor.writes),
    )


def verify_round_trip(original: bytes, plan: RebuildPlan) -> RebuildResult:
    payloads = extract_resources(original, plan)
    rebuilt = rebuild_resources(original, plan, payloads)
    if rebuilt.image != original:
        mismatch = _first_mismatch(original, rebuilt.image)
        raise ClassicRetroError(
            ErrorCode.REBUILD_ROUNDTRIP_FAILED,
            (
                "Unchanged extraction/rebuild changed the image"
                if mismatch is None
                else f"Unchanged extraction/rebuild changed byte 0x{mismatch:X}"
            ),
        )
    return rebuilt


def _validate_plan_against_image(original: bytes, plan: RebuildPlan) -> None:
    image = ByteRange(0, len(original))

    for resource in plan.resources:
        if not image.contains(resource.source):
            raise ClassicRetroError(
                ErrorCode.RESOURCE_OUT_OF_BOUNDS,
                f"Resource {resource.id} is outside the input image",
            )

    for reference in plan.references:
        if not image.contains(reference.span):
            raise ClassicRetroError(
                ErrorCode.REFERENCE_OUT_OF_BOUNDS,
                f"Reference {reference.id} is outside the input image",
            )


def _validate_reference_targets(original: bytes, plan: RebuildPlan) -> None:
    resources = {resource.id: resource for resource in plan.resources}
    for reference in plan.references:
        target = _decode_reference(original, reference)
        expected = resources[reference.target_resource_id].source.start
        if target != expected:
            raise ClassicRetroError(
                ErrorCode.REFERENCE_TARGET_MISMATCH,
                (
                    f"Reference {reference.id} resolves to 0x{target:X}; "
                    f"expected 0x{expected:X}"
                ),
            )


def _decode_reference(original: bytes, reference: ReferenceSite) -> int:
    raw = original[reference.span.start : reference.span.end]
    return reference.codec.decode(raw, site_offset=reference.offset)


def _first_mismatch(left: bytes, right: bytes) -> int | None:
    for index, (left_byte, right_byte) in enumerate(zip(left, right, strict=False)):
        if left_byte != right_byte:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None
