from __future__ import annotations

from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.model import ByteRange, SafeRegion


@dataclass(frozen=True, slots=True)
class Allocation:
    region_id: str
    span: ByteRange


class RegionAllocator:
    """Deterministic best-fit allocator over adapter-declared safe regions."""

    def __init__(self, regions: tuple[SafeRegion, ...], original: bytes) -> None:
        self._gaps: list[tuple[str, ByteRange]] = []

        for region in regions:
            if region.span.end > len(original):
                raise ClassicRetroError(
                    ErrorCode.INVALID_REBUILD_PLAN,
                    (
                        f"Safe region {region.id} extends beyond the input image; "
                        "implicit file expansion is not allowed"
                    ),
                )

            if region.expected_fill_byte is not None:
                payload = original[region.span.start : region.span.end]
                if any(byte != region.expected_fill_byte for byte in payload):
                    raise ClassicRetroError(
                        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
                        (
                            f"Safe region {region.id} does not contain only "
                            f"0x{region.expected_fill_byte:02X}"
                        ),
                    )

            self._gaps.append((region.id, region.span))

    def allocate(self, size: int, *, alignment: int = 1) -> Allocation:
        if size < 1 or alignment < 1:
            raise ValueError("allocation size and alignment must be positive")

        candidates: list[tuple[int, int, str, int, ByteRange]] = []
        for index, (region_id, gap) in enumerate(self._gaps):
            start = _align_up(gap.start, alignment)
            end = start + size
            if end > gap.end:
                continue
            waste = gap.size - size
            candidates.append((waste, start, region_id, index, ByteRange(start, end)))

        if not candidates:
            raise ClassicRetroError(
                ErrorCode.ALLOCATION_FAILED,
                f"No declared safe region can fit {size} byte(s) aligned to {alignment}",
            )

        _, _, region_id, gap_index, allocated = min(candidates)
        _, gap = self._gaps.pop(gap_index)

        replacement: list[tuple[str, ByteRange]] = []
        if gap.start < allocated.start:
            replacement.append((region_id, ByteRange(gap.start, allocated.start)))
        if allocated.end < gap.end:
            replacement.append((region_id, ByteRange(allocated.end, gap.end)))
        self._gaps.extend(replacement)
        self._gaps.sort(key=lambda item: (item[1].start, item[0]))

        return Allocation(region_id=region_id, span=allocated)


def _align_up(value: int, alignment: int) -> int:
    remainder = value % alignment
    return value if remainder == 0 else value + alignment - remainder
