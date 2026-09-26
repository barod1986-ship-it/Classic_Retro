"""MIPS I encoders for hook sites: the R3000A's (the PlayStation's CPU), little-endian.

An instruction is one 32-bit word. A call is ``JAL``, which reaches any
address in the same 256 MiB segment, so a hook anywhere in main RAM is one
word away from its site; the instruction after a jump (its delay slot) runs
before the jump. Overlays also rewrite a constant in place (``ori`` for a
small ``li``, ``addiu``, ``slti``) or a multiplication the compiler wrote as
shifts and adds (``sll``), and point a ``lui``/``addiu`` pair at a new address.
"""

from __future__ import annotations

import struct

from classic_retro.core.errors import ClassicRetroError, ErrorCode

REGISTERS = {
    name: number
    for number, name in enumerate(
        "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 "
        "s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split()
    )
}
NOP = bytes(4)
_J = 0x02
_JAL = 0x03
_ADDIU = 0x09
_SLTI = 0x0A
_ORI = 0x0D
_LUI = 0x0F


def _word(value: int) -> bytes:
    return struct.pack("<I", value)


def _register(name: str) -> int:
    try:
        return REGISTERS[name]
    except KeyError:
        raise ValueError(f"No MIPS register {name}") from None


def _jump(opcode: int, address: int, target: int) -> bytes:
    if address % 4 or target % 4 or (address + 4) >> 28 != target >> 28:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#x} is out of jump range from {address:#x}"
        )
    return _word(opcode << 26 | target >> 2 & 0x3FFFFFF)


def jal_instruction(address: int, target: int) -> bytes:
    """``jal target`` at ``address``."""
    return _jump(_JAL, address, target)


def j_instruction(address: int, target: int) -> bytes:
    """``j target`` at ``address``."""
    return _jump(_J, address, target)


def jal_target(address: int, data: bytes) -> int:
    """Where the ``jal`` at ``address`` (its four bytes ``data``) calls."""
    (word,) = struct.unpack("<I", data)
    if word >> 26 != _JAL:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"No jal at {address:#x}")
    return _target(address, word)


def jump_targets(address: int, code: bytes) -> dict[int, int]:
    """Every ``j`` and ``jal`` of ``code`` loaded at ``address``: where it is, where it goes.

    A word of data that looks like a jump counts too.
    """
    targets: dict[int, int] = {}
    for offset in range(0, len(code) - len(code) % 4, 4):
        (word,) = struct.unpack_from("<I", code, offset)
        if word >> 26 in (_J, _JAL):
            targets[address + offset] = _target(address + offset, word)
    return targets


def _target(address: int, word: int) -> int:
    return (address + 4) & 0xF0000000 | (word & 0x3FFFFFF) << 2


def _immediate(opcode: int, rt: str, rs: str, value: int, signed: bool) -> bytes:
    low, high = (-0x8000, 0x7FFF) if signed else (0, 0xFFFF)
    if not low <= value <= high:
        raise ValueError(f"{value} does not fit a 16-bit immediate")
    return _word(opcode << 26 | _register(rs) << 21 | _register(rt) << 16 | value & 0xFFFF)


def addiu(rt: str, rs: str, value: int) -> bytes:
    return _immediate(_ADDIU, rt, rs, value, signed=True)


def slti(rt: str, rs: str, value: int) -> bytes:
    return _immediate(_SLTI, rt, rs, value, signed=True)


def ori(rt: str, rs: str, value: int) -> bytes:
    return _immediate(_ORI, rt, rs, value, signed=False)


def li(rt: str, value: int) -> bytes:
    """A small unsigned constant, as the compiler loads it: ``ori rt, zero, value``."""
    return ori(rt, "zero", value)


def lui(rt: str, value: int) -> bytes:
    return _immediate(_LUI, rt, "zero", value, signed=False)


def sll(rd: str, rt: str, shift: int) -> bytes:
    if not 0 <= shift < 32:
        raise ValueError("a shift is 0 to 31")
    return _word(_register(rt) << 16 | _register(rd) << 11 | shift << 6)


def address_pair(rt: str, address: int) -> bytes:
    """``lui rt, %hi(address)`` then ``addiu rt, rt, %lo(address)``: an address in ``rt``."""
    low = address & 0xFFFF
    low = low - 0x10000 if low & 0x8000 else low
    high = (address - low) >> 16 & 0xFFFF
    return lui(rt, high) + addiu(rt, rt, low)


def pair_address(data: bytes) -> int:
    """The address a ``lui``/``addiu`` pair (its eight bytes) loads."""
    first, second = struct.unpack("<II", data)
    if first >> 26 != _LUI or second >> 26 != _ADDIU or (first >> 16 & 31) != (second >> 21 & 31):
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Not a lui/addiu pair")
    low = second & 0xFFFF
    return ((first & 0xFFFF) << 16) + (low - 0x10000 if low & 0x8000 else low) & 0xFFFFFFFF
