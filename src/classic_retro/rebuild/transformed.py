from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.model import RebuildPlan
from classic_retro.rebuild.pipeline import RebuildResult, extract_resources, rebuild_resources
from classic_retro.transform.base import TransformPipeline, TransformSnapshot


@dataclass(frozen=True, slots=True)
class TransformedExtraction:
    payloads: Mapping[str, bytes]
    snapshots: Mapping[str, TransformSnapshot]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payloads", MappingProxyType(dict(self.payloads)))
        object.__setattr__(self, "snapshots", MappingProxyType(dict(self.snapshots)))


def extract_transformed_resources(
    original: bytes,
    plan: RebuildPlan,
    pipelines: Mapping[str, TransformPipeline],
) -> TransformedExtraction:
    raw = extract_resources(original, plan)
    payloads: dict[str, bytes] = {}
    snapshots: dict[str, TransformSnapshot] = {}

    for resource_id, packed in raw.items():
        pipeline = pipelines.get(resource_id)
        if pipeline is None:
            payloads[resource_id] = packed
            continue

        payload, snapshot = pipeline.extract(packed)
        payloads[resource_id] = payload
        snapshots[resource_id] = snapshot

    return TransformedExtraction(payloads=payloads, snapshots=snapshots)


def rebuild_transformed_resources(
    original: bytes,
    plan: RebuildPlan,
    extraction: TransformedExtraction,
    edited_payloads: Mapping[str, bytes],
    pipelines: Mapping[str, TransformPipeline],
) -> RebuildResult:
    expected_ids = {resource.id for resource in plan.resources}
    if set(edited_payloads) != expected_ids:
        raise ClassicRetroError(
            ErrorCode.RESOURCE_SET_MISMATCH,
            "Transformed rebuild payload set differs from rebuild plan",
        )

    packed_payloads: dict[str, bytes] = {}
    for resource_id, payload in edited_payloads.items():
        snapshot = extraction.snapshots.get(resource_id)
        pipeline = pipelines.get(resource_id)

        if snapshot is None and pipeline is None:
            packed_payloads[resource_id] = payload
            continue

        if snapshot is None or pipeline is None:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_SNAPSHOT_MISMATCH,
                f"Resource {resource_id} transform configuration changed after extraction",
            )

        packed_payloads[resource_id] = pipeline.rebuild(snapshot, payload)

    return rebuild_resources(original, plan, packed_payloads)
