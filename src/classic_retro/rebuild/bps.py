"""BPS patches (byuu's beat format): create, apply and verify.

Patches are the distributable output of binary ROM overlays. The encoder is a
greedy matcher: unchanged bytes become SourceRead, byte runs become an
overlapping TargetCopy, data moved inside the image becomes SourceCopy, and
everything else is TargetRead. Every patch is checked by applying it again.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

BPS_MAGIC = b"BPS1"
_SOURCE_READ, _TARGET_READ, _SOURCE_COPY, _TARGET_COPY = range(4)
_BLOCK = 16
_MIN_RUN = 32
_MIN_SOURCE_READ = 4


def _number(value: int) -> bytes:
    output = bytearray()
    while True:
        low = value & 0x7F
        value >>= 7
        if value == 0:
            output.append(0x80 | low)
            return bytes(output)
        output.append(low)
        value -= 1


def _signed(value: int) -> bytes:
    return _number(abs(value) << 1 | (value < 0))


def _read_number(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 1
    while True:
        if position >= len(data):
            raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "Truncated BPS number")
        byte = data[position]
        position += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, position
        shift <<= 7
        value += shift


def _same_length(source: memoryview, target: memoryview, position: int) -> int:
    """Length of the run where target equals source at the same offset."""
    limit = min(len(source), len(target))
    length = 0
    step = 16
    while position + length < limit:
        end = min(position + length + step, limit)
        if source[position + length : end] == target[position + length : end]:
            length = end - position
            step = min(step * 4, 1 << 20)
        elif step > 1:
            step = max(1, step // 16)
        else:
            break
    return length


def _run_length(target: memoryview, position: int) -> int:
    """Length of the run of one repeated byte starting at position (0 when short)."""
    head = target[position : position + _MIN_RUN]
    if len(head) < _MIN_RUN or head != bytes(head[:1]) * _MIN_RUN:
        return 0
    window = bytes(target[position : position + 0x10000])
    return len(window) - len(window.lstrip(window[:1]))


@dataclass(frozen=True, slots=True)
class BpsPatch:
    data: bytes
    source_size: int
    target_size: int
    source_crc32: int
    target_crc32: int


def create_bps(source: bytes, target: bytes, metadata: bytes = b"") -> BpsPatch:
    index: dict[bytes, int] = {}
    for offset in range(0, len(source) - _BLOCK + 1, _BLOCK):
        index.setdefault(source[offset : offset + _BLOCK], offset)
    source_view = memoryview(source)
    target_view = memoryview(target)

    output = bytearray(BPS_MAGIC)
    output += _number(len(source)) + _number(len(target)) + _number(len(metadata)) + metadata
    literal_start = -1
    source_relative = 0
    target_relative = 0

    def flush_literal(end: int) -> None:
        nonlocal literal_start
        if literal_start >= 0:
            output.extend(_number((end - literal_start - 1) << 2 | _TARGET_READ))
            output.extend(target[literal_start:end])
            literal_start = -1

    position = 0
    while position < len(target):
        same = _same_length(source_view, target_view, position)
        if same >= _MIN_SOURCE_READ:
            flush_literal(position)
            output.extend(_number((same - 1) << 2 | _SOURCE_READ))
            position += same
            continue

        run = _run_length(target_view, position)
        if run and position > 0 and target[position - 1] == target[position]:
            flush_literal(position)
            output.extend(_number((run - 1) << 2 | _TARGET_COPY))
            output.extend(_signed(position - 1 - target_relative))
            target_relative = position - 1 + run
            position += run
            continue

        match = index.get(bytes(target_view[position : position + _BLOCK]))
        if match is not None:
            length = _BLOCK + _same_length(
                source_view[match + _BLOCK :], target_view[position + _BLOCK :], 0
            )
            flush_literal(position)
            output.extend(_number((length - 1) << 2 | _SOURCE_COPY))
            output.extend(_signed(match - source_relative))
            source_relative = match + length
            position += length
            continue

        if literal_start < 0:
            literal_start = position
        position += 1
    flush_literal(position)

    source_crc = zlib.crc32(source)
    target_crc = zlib.crc32(target)
    output += source_crc.to_bytes(4, "little") + target_crc.to_bytes(4, "little")
    output += zlib.crc32(output).to_bytes(4, "little")
    patch = BpsPatch(bytes(output), len(source), len(target), source_crc, target_crc)
    if apply_bps(patch.data, source) != target:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "BPS patch does not reproduce the target"
        )
    return patch


def apply_bps(patch: bytes, source: bytes) -> bytes:
    if len(patch) < 16 or patch[:4] != BPS_MAGIC:
        raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "Not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS patch checksum mismatch")
    if zlib.crc32(source) != int.from_bytes(patch[-12:-8], "little"):
        raise ClassicRetroError(
            ErrorCode.UNKNOWN_GAME_REVISION, "BPS patch was made for a different source image"
        )
    position = 4
    source_size, position = _read_number(patch, position)
    target_size, position = _read_number(patch, position)
    metadata_size, position = _read_number(patch, position)
    position += metadata_size
    if source_size != len(source):
        raise ClassicRetroError(ErrorCode.UNKNOWN_GAME_REVISION, "BPS source size mismatch")

    target = bytearray()
    source_relative = 0
    target_relative = 0
    end = len(patch) - 12
    while position < end:
        action, position = _read_number(patch, position)
        command, length = action & 3, (action >> 2) + 1
        if command == _SOURCE_READ:
            start = len(target)
            if start + length > len(source):
                raise ClassicRetroError(
                    ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS SourceRead past the source"
                )
            target += source[start : start + length]
        elif command == _TARGET_READ:
            target += patch[position : position + length]
            position += length
        else:
            raw, position = _read_number(patch, position)
            offset = -(raw >> 1) if raw & 1 else raw >> 1
            if command == _SOURCE_COPY:
                source_relative += offset
                if not 0 <= source_relative <= len(source) - length:
                    raise ClassicRetroError(
                        ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS SourceCopy outside the source"
                    )
                target += source[source_relative : source_relative + length]
                source_relative += length
            else:
                target_relative += offset
                if not 0 <= target_relative < len(target):
                    raise ClassicRetroError(
                        ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS TargetCopy outside the output"
                    )
                # An overlapping copy repeats the bytes between the start and the end.
                period = len(target) - target_relative
                chunk = bytes(target[target_relative : target_relative + min(length, period)])
                repeated = (chunk * (length // len(chunk) + 1))[:length]
                target += repeated
                target_relative += length
        if len(target) > target_size:
            raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS output overflow")
    if len(target) != target_size:
        raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS output size mismatch")
    if zlib.crc32(target) != int.from_bytes(patch[-8:-4], "little"):
        raise ClassicRetroError(ErrorCode.INVALID_REBUILD_PAYLOAD, "BPS target checksum mismatch")
    return bytes(target)
