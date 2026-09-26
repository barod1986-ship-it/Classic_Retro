"""ARM-state encoders for hook sites: the ARM946E-S's (the Nintendo DS's ARM9).

Most DS code is ARM, 32-bit instructions: a hook site there is an ARM ``BL``
(``bl_instruction``), a call within 32 MiB, which reaches any hook in the
ARM9's main memory. The hook is ARM code too; a Thumb hook would take ``BLX``.
"""

from __future__ import annotations

import struct

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# The condition "always" and the BL opcode, bits 24-31.
_BL = 0xEB


def bl_instruction(address: int, target: int) -> bytes:
    """``BL target`` at ``address``: both word aligned, within 32 MiB."""
    offset = target - (address + 8)
    if not -0x2000000 <= offset < 0x2000000 or offset % 4 or address % 4:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#x} is out of BL range from {address:#x}"
        )
    return struct.pack("<I", _BL << 24 | offset >> 2 & 0xFFFFFF)


def bl_target(address: int, data: bytes) -> int:
    """Where the ``BL`` at ``address`` (its four bytes ``data``) calls."""
    (word,) = struct.unpack("<I", data)
    if word >> 24 != _BL:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"No BL at {address:#x}")
    return _target(address, word)


def branch_targets(address: int, code: bytes) -> dict[int, int]:
    """Every ``B`` or ``BL`` of ARM ``code`` loaded at ``address``: where it is, where it goes.

    Any condition counts; ``BLX`` (condition 0b1111) does not. A word of data
    that looks like a branch counts too.
    """
    targets: dict[int, int] = {}
    for offset in range(0, len(code) - len(code) % 4, 4):
        (word,) = struct.unpack_from("<I", code, offset)
        if word >> 25 & 0b111 == 0b101 and word >> 28 != 0b1111:
            targets[address + offset] = _target(address + offset, word)
    return targets


def _target(address: int, word: int) -> int:
    offset = (word & 0xFFFFFF) << 2
    if offset & 0x2000000:
        offset -= 0x4000000
    return address + 8 + offset
