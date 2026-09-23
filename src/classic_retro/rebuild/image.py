from __future__ import annotations

from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.rebuild.model import ByteRange


@dataclass(frozen=True, slots=True)
class WriteRecord:
    label: str
    span: ByteRange


class BinaryEditor:
    def __init__(self, original: bytes) -> None:
        self._data = bytearray(original)
        self._writes: list[WriteRecord] = []

    @property
    def bytes(self) -> bytes:
        return bytes(self._data)

    @property
    def writes(self) -> tuple[WriteRecord, ...]:
        return tuple(self._writes)

    def write(self, offset: int, data: bytes, *, label: str) -> None:
        span = ByteRange.from_start_size(offset, len(data))
        if span.end > len(self._data):
            raise ClassicRetroError(
                ErrorCode.WRITE_OUT_OF_BOUNDS,
                f"Write {label} ends beyond input image",
            )
        if not data:
            return

        for existing in self._writes:
            if span.overlaps(existing.span):
                raise ClassicRetroError(
                    ErrorCode.OVERLAPPING_WRITE,
                    f"Write {label} overlaps {existing.label}",
                )

        self._data[span.start : span.end] = data
        self._writes.append(WriteRecord(label=label, span=span))
