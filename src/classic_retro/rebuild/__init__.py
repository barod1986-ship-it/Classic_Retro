"""Safe binary resource extraction, relocation, and rebuild primitives."""

from classic_retro.rebuild.model import (
    ByteOrder,
    ByteRange,
    IntegerReferenceCodec,
    RebuildPlan,
    ReferenceBaseKind,
    ReferenceSite,
    ResourceSpec,
    SafeRegion,
    load_rebuild_plan,
)
from classic_retro.rebuild.pipeline import (
    RebuildResult,
    ResourcePlacement,
    extract_resources,
    rebuild_resources,
    verify_round_trip,
)
from classic_retro.rebuild.transformed import (
    TransformedExtraction,
    extract_transformed_resources,
    rebuild_transformed_resources,
)

__all__ = [
    "ByteOrder",
    "ByteRange",
    "IntegerReferenceCodec",
    "RebuildPlan",
    "RebuildResult",
    "ReferenceBaseKind",
    "ReferenceSite",
    "ResourcePlacement",
    "ResourceSpec",
    "SafeRegion",
    "TransformedExtraction",
    "extract_resources",
    "extract_transformed_resources",
    "load_rebuild_plan",
    "rebuild_resources",
    "rebuild_transformed_resources",
    "verify_round_trip",
]
