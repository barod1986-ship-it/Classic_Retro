"""Disassembly of image bytes, through GNU binutils' objdump.

ARM7TDMI code (Game Boy Advance) is shown in Thumb or ARM mode with
``arm-none-eabi-objdump``, the binutils the hook checks already use. Another
CPU would add its objdump machine here.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode

MODES = ("thumb", "arm")


def disassemble(
    code: bytes, address: int, *, mode: str = "thumb", objdump: str | None = None
) -> list[str]:
    """The listing of ``code`` as if loaded at ``address``: one line per instruction."""
    tool = objdump or shutil.which("arm-none-eabi-objdump")
    if tool is None:
        raise ClassicRetroError(
            ErrorCode.EMULATOR_UNAVAILABLE,
            "Disassembly needs arm-none-eabi-objdump (Debian/Ubuntu: binutils-arm-none-eabi)",
        )
    options = ["-M", "force-thumb"] if mode == "thumb" else []
    with tempfile.TemporaryDirectory() as work:
        blob = Path(work) / "code.bin"
        blob.write_bytes(code)
        result = subprocess.run(
            [tool, "-D", "-b", "binary", "-m", "arm", *options]
            + [f"--adjust-vma={address:#x}", str(blob)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise ClassicRetroError(
            ErrorCode.EMULATOR_FAILED, f"objdump failed: {result.stderr.strip()}"
        )
    # The listing starts after objdump's header, at the first address line.
    lines = result.stdout.splitlines()
    first = next(
        (index for index, line in enumerate(lines) if line.strip().endswith(">:")), len(lines)
    )
    return [line for line in lines[first + 1 :] if line.strip()]
