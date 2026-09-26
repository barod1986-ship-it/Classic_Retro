"""What an emulator backend offers the research script runner.

A backend runs one game image. It runs frames with keys held, returns the last
frame drawn, saves and loads states, and reads and writes memory by address.
A backend with a debugger also sets breakpoints and watchpoints.
``classic_retro.research.script`` drives every backend with the same commands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType, TracebackType

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode

# RetroPad buttons: the key names scripts use with every backend. A backend
# accepts those its console has.
RETROPAD_KEYS = (
    "A",
    "B",
    "X",
    "Y",
    "L",
    "R",
    "L2",
    "R2",
    "L3",
    "R3",
    "SELECT",
    "START",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
)
# What a watchpoint reports: reads, writes, writes that change the value, or both.
WATCH_ACCESSES = ("read", "write", "change", "access")


@dataclass(frozen=True, slots=True)
class RegionAddress:
    """An offset into a memory region a backend names (``system_ram:0x100``)."""

    region: str
    offset: int

    def __str__(self) -> str:
        return f"{self.region}:0x{self.offset:X}"


# An address on the console's bus, or an offset into a named region.
Address = int | RegionAddress


@dataclass(frozen=True, slots=True)
class MemoryProbe:
    """Memory a breakpoint reports when it hits: at a register's value, or at an address."""

    length: int
    register: int | None = None
    address: int | None = None


@dataclass(frozen=True, slots=True)
class Hit:
    """A breakpoint or watchpoint that fired during ``Emulator.run``."""

    point: int
    # Frames completed in this run before the hit.
    frame: int
    kind: str  # "breakpoint" or "watchpoint"
    # The breakpoint's address, or the address a watchpoint saw accessed.
    address: int
    registers: Mapping[str, int] = field(default_factory=dict)
    # The instruction that hit, when the backend knows it.
    pc: int | None = None
    # Watchpoints: "read" or "write", and the value before and after a write
    # (a read reports the value read as ``old``).
    access: str | None = None
    old: int | None = None
    new: int | None = None
    # Breakpoints with a memory probe: where it read, and the bytes.
    memory: tuple[int, bytes] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "registers", MappingProxyType(dict(self.registers)))


@dataclass(frozen=True, slots=True)
class Screen:
    """A frame as the console drew it: RGB, 8 bits a channel, row by row."""

    width: int
    height: int
    rgb: bytes

    def __post_init__(self) -> None:
        if len(self.rgb) != self.width * self.height * 3:
            raise ValueError("RGB data does not match the frame size")

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        start = (y * self.width + x) * 3
        red, green, blue = self.rgb[start : start + 3]
        return red, green, blue

    def save_png(self, path: Path) -> None:
        Image.frombytes("RGB", (self.width, self.height), self.rgb).save(path, format="PNG")


class Emulator(ABC):
    """One game running under a backend; close it (or use ``with``) when done."""

    backend: str
    # What runs the game, for the report ("mGBA 0.10.2").
    core: str
    # The console, when the backend knows it ("gba", "gb").
    platform: str | None = None
    keys: frozenset[str] = frozenset()
    # Memory regions a ``RegionAddress`` may name.
    regions: frozenset[str] = frozenset()
    debugger: bool = False
    # Whether ``touch`` can press a point of the frame (a touch screen, through a pointer).
    pointer: bool = False
    # Hex digits a register value is reported with.
    register_digits: int = 8

    @abstractmethod
    def run(self, frames: int, keys: frozenset[str]) -> list[Hit]:
        """Run ``frames`` frames with ``keys`` held; the breakpoints and watchpoints hit."""

    @abstractmethod
    def screen(self) -> Screen:
        """The last frame drawn."""

    @abstractmethod
    def save_state(self) -> bytes: ...

    @abstractmethod
    def load_state(self, state: bytes) -> None: ...

    @abstractmethod
    def read(self, address: Address, length: int) -> bytes: ...

    @abstractmethod
    def write(self, address: Address, data: bytes) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def touch(self, point: tuple[int, int] | None) -> None:
        """Press the frame's pixel ``point`` (x, y as ``screen`` draws it) while frames run.

        None lets go. The pixel is on the whole frame: a console with two
        screens draws both into it, the touch screen included.
        """
        raise ClassicRetroError(
            ErrorCode.EMULATOR_UNAVAILABLE,
            f"The {self.backend} backend cannot touch the screen: touch needs a libretro core "
            "that reads a pointer",
        )

    def add_breakpoint(self, address: int, count: int | None, probe: MemoryProbe | None) -> int:
        """Report the registers when ``address`` executes, ``count`` times (None: every time)."""
        raise self.no_debugger()

    def add_watchpoint(self, address: int, access: str, count: int | None) -> int:
        """Report the registers when ``address`` is accessed (``WATCH_ACCESSES``)."""
        raise self.no_debugger()

    def clear_points(self) -> None:
        raise self.no_debugger()

    def no_debugger(self) -> ClassicRetroError:
        return ClassicRetroError(
            ErrorCode.EMULATOR_UNAVAILABLE,
            f"The {self.backend} backend has no debugger: breakpoints and watchpoints "
            "need the mgba backend",
        )

    def __enter__(self) -> Emulator:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
