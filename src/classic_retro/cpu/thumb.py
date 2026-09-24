"""ARM7TDMI Thumb encoders for hook sites (Game Boy Advance).

A hook site is game code replaced by a jump to overlay code. Thumb gives three
ways to get there:

- ``BL`` (``bl_instruction``): a call within 4 MiB, 4 bytes;
- a literal jump (``literal_jump``): ``ldr rN, [pc, #k]; bx rN`` and the
  target word, for any distance, 8 or 10 bytes depending on alignment;
- ``B`` (``branch_instruction``): a short branch, to skip the rest of a site.

``bl_veneer_patch`` combines them for far hooks that must return: a ``BL`` to
a veneer written in the site itself, a ``B`` over it, and the veneer.
"""

from __future__ import annotations

import struct

from classic_retro.core.errors import ClassicRetroError, ErrorCode

NOP = bytes.fromhex("c046")  # mov r8, r8


def bl_instruction(address: int, target: int) -> bytes:
    offset = target - (address + 4)
    if not -0x400000 <= offset < 0x400000 or offset % 2:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#x} is out of BL range from {address:#x}"
        )
    return struct.pack("<HH", 0xF000 | offset >> 12 & 0x7FF, 0xF800 | offset >> 1 & 0x7FF)


def bl_target(address: int, data: bytes) -> int:
    """Where the ``BL`` at ``address`` (its four bytes ``data``) calls."""
    high, low = struct.unpack("<HH", data)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"No BL at {address:#x}")
    offset = (high & 0x7FF) << 12 | (low & 0x7FF) << 1
    if offset & 0x400000:
        offset -= 0x800000
    return address + 4 + offset


def branch_instruction(address: int, target: int) -> bytes:
    offset = target - (address + 4)
    if not -0x800 <= offset < 0x800 or offset % 2:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#x} is out of B range from {address:#x}"
        )
    return struct.pack("<H", 0xE000 | offset >> 1 & 0x7FF)


def literal_jump(address: int, register: int, target: int) -> bytes:
    """``ldr rN, [pc, #k]; bx rN``, ``nop`` up to the next word, then ``target | 1``.

    The literal is the first word boundary after the ``bx``: 8 bytes at a
    word-aligned ``address``, 10 bytes (one ``nop``) otherwise.
    """
    if not 0 <= register <= 7 or address % 2:
        raise ClassicRetroError(
            ErrorCode.REFERENCE_ALIGNMENT_ERROR,
            f"No literal jump through r{register} at {address:#x}",
        )
    pc = address + 4 & ~3
    literal = address + 4 + 3 & ~3
    words = (literal - pc) // 4
    code = struct.pack("<HH", 0x4800 | register << 8 | words, 0x4700 | register << 3)
    return code + NOP * ((literal - (address + 4)) // 2) + struct.pack("<I", target | 1)


def bl_veneer_patch(address: int, resume: int, target: int, register: int = 0) -> bytes:
    """``bl veneer; b resume; nop``, then the veneer ``ldr rN, =target; bx rN``.

    16 bytes at a word-aligned ``address``: the hook returns to ``address + 4``
    (through the ``BL``'s return address), which branches to ``resume``. The
    veneer clobbers ``register``.
    """
    veneer = address + 8
    code = bl_instruction(address, veneer) + branch_instruction(address + 4, resume) + NOP
    return code + literal_jump(veneer, register, target)


def arm_veneer(target: int) -> bytes:
    """``bx pc; nop`` (to ARM), ``ldr ip, [pc]; bx ip``, ``.word target | 1``: 16 bytes."""
    return struct.pack("<HHIII", 0x4778, 0x46C0, 0xE59FC000, 0xE12FFF1C, target | 1)
