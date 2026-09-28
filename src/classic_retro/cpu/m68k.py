"""68000 encoders for hook sites: the Mega Drive's CPU, big-endian.

An instruction is a run of 16-bit words on an even address. A hook site is
game code replaced by ``JMP`` or ``JSR`` with an absolute long address
(``jmp_long``, ``jsr_long``): six bytes, to any address of the 68000's 16 MiB
(the cartridge lies at its start), so a hook anywhere in the ROM is reached
from any site. A hook a ``JSR`` calls returns with ``RTS``. A site longer than
its jump is filled with ``NOP`` (``nop_fill``), a word each, so the bytes a
hook goes back over hold nothing.
"""

from __future__ import annotations

import struct

from classic_retro.core.errors import ClassicRetroError, ErrorCode

NOP = bytes.fromhex("4e71")
_JMP_LONG = 0x4EF9
_JSR_LONG = 0x4EB9
# The 68000 has 24 address lines: a long address above them wraps.
_LAST_ADDRESS = 0xFFFFFF


def _long(opcode: int, target: int) -> bytes:
    if not 0 <= target <= _LAST_ADDRESS or target % 2:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#08x} is not an even 24-bit address"
        )
    return struct.pack(">HI", opcode, target)


def jmp_long(target: int) -> bytes:
    """``JMP target.l``: any even 24-bit address."""
    return _long(_JMP_LONG, target)


def jsr_long(target: int) -> bytes:
    """``JSR target.l``: any even 24-bit address."""
    return _long(_JSR_LONG, target)


def nop_fill(code: bytes, length: int) -> bytes:
    """``code``, then ``NOP`` up to ``length`` bytes: a site longer than its jump.

    Both are whole words, since every instruction is.
    """
    if len(code) % 2 or length % 2:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{len(code)} bytes into {length}: not whole words"
        )
    if len(code) > length:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{len(code)} bytes do not fit a site of {length}"
        )
    return code + NOP * ((length - len(code)) // 2)
