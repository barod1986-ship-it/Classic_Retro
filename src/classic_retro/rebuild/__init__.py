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
    "extract_resources",
    "load_rebuild_plan",
    "rebuild_resources",
    "verify_round_trip",
]
