"""Hook programs: code an overlay adds to a game, stored as bytes, checked from source.

An overlay stores its assembled hook code and symbol offsets in Python, so a
build needs no toolchain. ``HookProgram.check`` re-assembles the source and
proves the stored bytes match (run in CI). The assembler is chosen by CPU from
an open registry: GNU binutils for the ARM7TDMI (Game Boy Advance), the
ARM946E-S (the Nintendo DS's ARM9) and the R3000A (the PlayStation, MIPS I,
``mipsel-linux-gnu-*``) today; other CPUs register their own
(``register_assembler``).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# An assembler builds ``source`` linked at ``address`` and returns its bytes and
# the addresses of ``symbols`` (absolute). ``label`` names the program in errors.
Assembler = Callable[[Path, int, frozenset[str], str], tuple[bytes, dict[str, int]]]


def assemble_gnu_arm(
    source: Path, address: int, symbols: frozenset[str], label: str
) -> tuple[bytes, dict[str, int]]:
    """``arm-none-eabi-as -mcpu=arm7tdmi``, ``ld -Ttext``, ``objcopy -O binary``, ``nm``."""
    return _assemble_gnu(source, address, symbols, label, "arm-none-eabi-", ["-mcpu=arm7tdmi"])


def assemble_gnu_arm9(
    source: Path, address: int, symbols: frozenset[str], label: str
) -> tuple[bytes, dict[str, int]]:
    """The same with ``-mcpu=arm946e-s``: ARMv5TE, whose Thumb code has ``blx``."""
    return _assemble_gnu(source, address, symbols, label, "arm-none-eabi-", ["-mcpu=arm946e-s"])


def assemble_gnu_r3000(
    source: Path, address: int, symbols: frozenset[str], label: str
) -> tuple[bytes, dict[str, int]]:
    """``mipsel-linux-gnu-as -march=r3000``, absolute code, and the ``.text`` section only.

    The source sets ``noreorder``, so every delay slot is what it says.
    """
    return _assemble_gnu(
        source,
        address,
        symbols,
        label,
        "mipsel-linux-gnu-",
        ["-march=r3000", "-mabi=32", "-non_shared", "-mno-pdr", "-EL"],
        ["-EL", "-N"],
        ["-j", ".text"],
    )


def _assemble_gnu(
    source: Path,
    address: int,
    symbols: frozenset[str],
    label: str,
    prefix: str,
    as_flags: list[str],
    ld_flags: list[str] | None = None,
    objcopy_flags: list[str] | None = None,
) -> tuple[bytes, dict[str, int]]:
    tools = {name: shutil.which(f"{prefix}{name}") for name in ("as", "ld", "objcopy", "nm")}
    missing = sorted(name for name, path in tools.items() if path is None)
    if missing:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "Missing GNU binutils: " + ", ".join(f"{prefix}{name}" for name in missing),
        )
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        steps = (
            [tools["as"], *as_flags, "-o", folder / "hooks.o", source],
            [tools["ld"], *(ld_flags or []), "-e", "0", "-Ttext", f"{address:#x}"]
            + ["-o", folder / "hooks.elf", folder / "hooks.o"],
            [tools["objcopy"], *(objcopy_flags or []), "-O", "binary"]
            + [folder / "hooks.elf", folder / "hooks.bin"],
            [tools["nm"], folder / "hooks.elf"],
        )
        try:
            listing = [
                subprocess.run(step, check=True, capture_output=True, text=True).stdout
                for step in steps
            ][-1]
        except subprocess.CalledProcessError as exc:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Assembling the {label} failed: {exc.stderr.strip()}",
            ) from exc
        code = (folder / "hooks.bin").read_bytes()
    found = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in symbols:
            found[parts[2]] = int(parts[0], 16)
    return code, found


_ASSEMBLERS: dict[str, Assembler] = {
    "arm7tdmi": assemble_gnu_arm,
    "arm946e-s": assemble_gnu_arm9,
    "r3000": assemble_gnu_r3000,
}


def register_assembler(cpu: str, assembler: Assembler) -> None:
    """Make hook programs for ``cpu`` assemble with ``assembler``."""
    if cpu in _ASSEMBLERS:
        raise ClassicRetroError(ErrorCode.ADAPTER_ID_CONFLICT, f"Assembler for {cpu} exists")
    _ASSEMBLERS[cpu] = assembler


def assembler_for(cpu: str) -> Assembler:
    try:
        return _ASSEMBLERS[cpu]
    except KeyError:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, f"No assembler is registered for {cpu}"
        ) from None


@dataclass(frozen=True, slots=True)
class HookProgram:
    """Hook code linked at ``address``: its stored bytes, symbols and source."""

    label: str
    source: Path
    address: int
    code: bytes
    symbols: Mapping[str, int] = field(default_factory=dict)
    cpu: str = "arm7tdmi"
    # The check's message treats the label as one hook ("differs").
    singular: bool = False

    def symbol_address(self, name: str) -> int:
        return self.address + self.symbols[name]

    def thumb_entry(self, name: str) -> int:
        return self.symbol_address(name) | 1

    def assemble(self, source: Path | None = None) -> tuple[bytes, dict[str, int]]:
        """Assemble the source; symbols as offsets from ``address``."""
        code, found = assembler_for(self.cpu)(
            source or self.source, self.address, frozenset(self.symbols), self.label
        )
        return code, {name: value - self.address for name, value in found.items()}

    def check(self, source: Path | None = None) -> dict[str, object]:
        code, symbols = self.assemble(source)
        if code != self.code or symbols != dict(self.symbols):
            verb = "differs" if self.singular else "differ"
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Assembled {self.label} {verb} from the stored HOOK_CODE / HOOK_SYMBOLS",
            )
        return {"hook_bytes": len(code), "symbols": dict(sorted(symbols.items())), "match": True}
