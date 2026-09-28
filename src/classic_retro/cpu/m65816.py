"""65C816 encoders for hook sites: the Super NES's CPU, little-endian.

A hook site is game code replaced by a jump to overlay code. The 65816 gives
two reaches:

- ``JMP`` and ``JSR`` with an absolute address (``jmp_abs``, ``jsr_abs``):
  three bytes, to a target in the bank of the site, since the program bank
  stays what it is; for a hook in the game's own bank (A Link to the Past's,
  in free bytes of the text engine's bank $0E). A hook a ``JSR`` calls
  returns with ``RTS``;
- ``JML`` and ``JSL`` with a long address (``jml_long``, ``jsl_long``): four
  bytes, to any 24-bit address; for a hook in another bank (Chrono Trigger's,
  in bank $DB). A hook a ``JSL`` calls returns with ``RTL``.

A site longer than its jump is filled with ``NOP`` (``nop_fill``), so the
bytes a hook goes back over hold nothing.
"""

from __future__ import annotations

from classic_retro.core.errors import ClassicRetroError, ErrorCode

NOP = bytes((0xEA,))
_JMP_ABS = 0x4C
_JSR_ABS = 0x20
_JML_LONG = 0x5C
_JSL_LONG = 0x22
_LAST_ADDRESS = 0xFFFFFF


def _absolute(opcode: int, address: int, target: int) -> bytes:
    if not 0 <= address <= _LAST_ADDRESS or not 0 <= target <= _LAST_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#08x} is not a 24-bit address"
        )
    if target >> 16 != address >> 16:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS,
            f"{target:#08x} is not in the bank of {address:#08x}: an absolute jump stays in it",
        )
    return bytes((opcode, target & 0xFF, target >> 8 & 0xFF))


def jmp_abs(address: int, target: int) -> bytes:
    """``JMP target`` at ``address``: both in one bank."""
    return _absolute(_JMP_ABS, address, target)


def jsr_abs(address: int, target: int) -> bytes:
    """``JSR target`` at ``address``: both in one bank."""
    return _absolute(_JSR_ABS, address, target)


def _long(opcode: int, target: int) -> bytes:
    if not 0 <= target <= _LAST_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#08x} is not a 24-bit address"
        )
    return bytes((opcode, target & 0xFF, target >> 8 & 0xFF, target >> 16))


def jml_long(target: int) -> bytes:
    """``JML target``: any 24-bit address."""
    return _long(_JML_LONG, target)


def jsl_long(target: int) -> bytes:
    """``JSL target``: any 24-bit address."""
    return _long(_JSL_LONG, target)


def nop_fill(code: bytes, length: int) -> bytes:
    """``code``, then ``NOP`` up to ``length`` bytes: a site longer than its jump."""
    if len(code) > length:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{len(code)} bytes do not fit a site of {length}"
        )
    return code + NOP * (length - len(code))
