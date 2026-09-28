"""Checks every overlay makes of its input and its output, whatever the game.

An overlay pins the bytes it relies on and proves, after the build, that
nothing changed outside the places it wrote. The three checks here are pure
functions over the images: ``verify_bytes`` compares pinned originals before
any change, ``verify_empty`` proves a region the overlay is about to fill
holds nothing yet, and ``verify_untouched`` diffs the output against the
original, byte for byte, and refuses the first byte that changed outside the
overlay's places. The last one runs on images up to 128 MiB, so it compares
blocks first and looks at single bytes only where a block differs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# The block the untouched check compares at a time; only a block that differs
# is looked at byte by byte.
BLOCK = 0x1000


def verify_bytes(
    image: bytes,
    expected: Mapping[int, bytes],
    *,
    offset: Callable[[int], int] | None = None,
    what: str = "image",
) -> None:
    """Every ``expected`` original (by address) is in ``image`` at ``offset(address)``.

    ``offset`` converts an address to an offset in the image; without it the
    addresses are offsets. An original that reaches past the image is missing,
    not present.
    """
    for address, original in expected.items():
        start = address if offset is None else offset(address)
        if image[start : start + len(original)] != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x} in {what}"
            )


def verify_empty(image: bytes, start: int, end: int, fill: int, *, what: str) -> None:
    """``image[start:end]`` holds nothing but ``fill`` bytes.

    An empty, inverted or out-of-image range would check nothing, so it is a
    ``ValueError``: the caller asked about bytes that are not there.
    """
    if not 0 <= start < end <= len(image):
        raise ValueError(f"{what}: {start:#x}..{end:#x} is not a range of the image")
    region = image[start:end]
    if region.count(fill) != len(region):
        first = next(start + at for at, byte in enumerate(region) if byte != fill)
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{what} holds data at {first:#x}, where {fill:#04x} was expected",
        )


def verify_untouched(
    original: bytes,
    output: bytes,
    allowed: Iterable[tuple[int, int]],
    *,
    what: str = "image",
) -> None:
    """``output`` differs from ``original`` only inside the ``allowed`` ranges.

    The ranges are (start, end) offsets of the original, the end exclusive;
    they may overlap. Only the images' common prefix is compared: what an
    overlay adds past the original's end (an expanded GBA image) is checked
    by the overlay itself. Blocks of ``BLOCK`` bytes are compared first and
    a block that differs is compared again between the allowed ranges, so
    the check stays linear on a large image.
    """
    ranges = _merged(allowed)
    length = min(len(original), len(output))
    index = 0
    for block in range(0, length, BLOCK):
        stop = min(block + BLOCK, length)
        if output[block:stop] == original[block:stop]:
            continue
        # The allowed ranges that reach into this block, in order; the ones
        # before it are done with.
        while index < len(ranges) and ranges[index][1] <= block:
            index += 1
        position = block
        for start, end in ranges[index:]:
            if start >= stop:
                break
            _same(original, output, position, min(start, stop), what)
            position = max(position, end)
        _same(original, output, position, stop, what)


def _same(original: bytes, output: bytes, start: int, end: int, what: str) -> None:
    """``start``..``end`` is the same in both images, or the first byte that is not."""
    if start >= end or output[start:end] == original[start:end]:
        return
    offset = next(at for at in range(start, end) if output[at] != original[at])
    raise ClassicRetroError(
        ErrorCode.BUILD_VALIDATION_FAILED,
        f"{what} changed at {offset:#x}, outside the overlay's places",
    )


def _merged(allowed: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """The ranges sorted and joined where they overlap or touch; empty ones dropped."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(allowed):
        if end < start:
            raise ValueError(f"Inverted range {start:#x}..{end:#x}")
        if end == start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
