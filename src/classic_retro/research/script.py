"""Scripted emulator sessions: the command language and the runner.

A script is plain text with one command per line. ``#`` starts a comment, and a
path with spaces goes in double quotes. Numbers are decimal or ``0x`` hex.
Relative paths are taken from the run's directory.

    load FILE                  load a savestate
    save FILE                  save a savestate
    keys KEYS                  hold KEYS (``A``, ``A+UP``) from now on; ``keys none``
    run FRAMES                 run FRAMES frames
    tap KEYS [HOLD [GAP]]      press KEYS for HOLD frames (2), then let go for GAP (8)
    shot FILE.png              save the last frame drawn
    peek ADDRESS LENGTH        report LENGTH bytes of memory (at most 4096)
    dump ADDRESS LENGTH FILE   write LENGTH bytes of memory to FILE
    poke ADDRESS HEX           write bytes, in memory order (``poke 0x02000000 01ff``)
    break ADDRESS [COUNT [MEMORY LENGTH]]
                               report the registers when ADDRESS executes, the first
                               COUNT times (100; ``all``: every time), with LENGTH
                               bytes at MEMORY (a register ``r0``..``r15`` or an address)
    watch MODE ADDRESS [COUNT] report the registers when ADDRESS is read, written or
                               changed (MODE: read, write, change, access)
    clear                      remove every breakpoint and watchpoint
    reset                      reset the console
    echo TEXT                  report TEXT

An address is a bus address, or ``REGION:OFFSET`` on a backend with named
memory regions (``system_ram:0x100``). Key names are RetroPad buttons: A, B,
X, Y, L, R, L2, R2, L3, R3, SELECT, START, UP, DOWN, LEFT, RIGHT.

``run_script`` checks the whole script against the backend first, so that a
mistake on the last line is reported before any frame runs. The report lists
every event with the frames completed before it: echoes, peeks, and each
breakpoint and watchpoint hit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.emulator import (
    RETROPAD_KEYS,
    WATCH_ACCESSES,
    Address,
    Emulator,
    Hit,
    MemoryProbe,
    RegionAddress,
)

DEFAULT_TAP_HOLD = 2
DEFAULT_TAP_GAP = 8
DEFAULT_POINT_COUNT = 100
PEEK_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class LoadState:
    path: str


@dataclass(frozen=True, slots=True)
class SaveState:
    path: str


@dataclass(frozen=True, slots=True)
class HoldKeys:
    keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class RunFrames:
    frames: int


@dataclass(frozen=True, slots=True)
class TapKeys:
    keys: frozenset[str]
    hold: int
    gap: int


@dataclass(frozen=True, slots=True)
class Shot:
    path: str


@dataclass(frozen=True, slots=True)
class Peek:
    address: Address
    length: int


@dataclass(frozen=True, slots=True)
class Dump:
    address: Address
    length: int
    path: str


@dataclass(frozen=True, slots=True)
class Poke:
    address: Address
    data: bytes


@dataclass(frozen=True, slots=True)
class Break:
    address: int
    count: int | None
    probe: MemoryProbe | None = None


@dataclass(frozen=True, slots=True)
class Watch:
    access: str
    address: int
    count: int | None


@dataclass(frozen=True, slots=True)
class ClearPoints:
    pass


@dataclass(frozen=True, slots=True)
class Reset:
    pass


@dataclass(frozen=True, slots=True)
class Echo:
    text: str


Command = (
    LoadState
    | SaveState
    | HoldKeys
    | RunFrames
    | TapKeys
    | Shot
    | Peek
    | Dump
    | Poke
    | Break
    | Watch
    | ClearPoints
    | Reset
    | Echo
)


@dataclass(frozen=True, slots=True)
class Step:
    line: int
    command: Command


class _Invalid(Exception):
    pass


_TOKEN = re.compile(r'"([^"]*)"|(\S+)')
_REGISTER = re.compile(r"r(\d+)", re.IGNORECASE)


def _tokens(line: str) -> list[str]:
    tokens = []
    for match in _TOKEN.finditer(line):
        quoted, bare = match.groups()
        if bare is not None and bare.startswith("#"):
            break
        tokens.append(quoted if quoted is not None else bare)
    return tokens


def _number(token: str, what: str) -> int:
    try:
        value = int(token, 0)
    except ValueError:
        raise _Invalid(f"{what} must be a number, not {token!r}") from None
    if value < 0:
        raise _Invalid(f"{what} cannot be negative")
    return value


def _address(token: str) -> Address:
    region, colon, offset = token.partition(":")
    if colon:
        if not region:
            raise _Invalid(f"{token!r} names no region")
        return RegionAddress(region.lower(), _number(offset, "the offset"))
    return _number(token, "the address")


def _bus_address(token: str) -> int:
    address = _address(token)
    if isinstance(address, RegionAddress):
        raise _Invalid("breakpoints and watchpoints take a bus address")
    return address


def _keys(token: str) -> frozenset[str]:
    if token.lower() == "none":
        return frozenset()
    names = token.upper().split("+")
    unknown = [name or "(empty)" for name in names if name not in RETROPAD_KEYS]
    if unknown:
        raise _Invalid(f"unknown keys {', '.join(unknown)} (keys: {' '.join(RETROPAD_KEYS)})")
    return frozenset(names)


def _count(token: str) -> int | None:
    if token.lower() == "all":
        return None
    count = _number(token, "the count")
    if count == 0:
        raise _Invalid("the count must be at least 1 (or all)")
    return count


def _length(token: str, limit: int | None = None) -> int:
    length = _number(token, "the length")
    if length == 0:
        raise _Invalid("the length must be at least 1")
    if limit is not None and length > limit:
        raise _Invalid(f"the length can be at most {limit}")
    return length


def _arity(name: str, arguments: list[str], usage: str, *counts: int) -> None:
    if len(arguments) not in counts:
        raise _Invalid(f"usage: {name} {usage}".rstrip())


def _command(name: str, arguments: list[str]) -> Command:
    if name in {"load", "save", "shot"}:
        _arity(name, arguments, "FILE.png" if name == "shot" else "FILE", 1)
        if name == "load":
            return LoadState(arguments[0])
        if name == "save":
            return SaveState(arguments[0])
        if not arguments[0].lower().endswith(".png"):
            raise _Invalid("shot writes a PNG file: name it FILE.png")
        return Shot(arguments[0])
    if name == "keys":
        _arity(name, arguments, "KEYS", 1)
        return HoldKeys(_keys(arguments[0]))
    if name == "run":
        _arity(name, arguments, "FRAMES", 1)
        return RunFrames(_number(arguments[0], "the frame count"))
    if name == "tap":
        _arity(name, arguments, "KEYS [HOLD [GAP]]", 1, 2, 3)
        hold = _number(arguments[1], "the hold") if len(arguments) > 1 else DEFAULT_TAP_HOLD
        gap = _number(arguments[2], "the gap") if len(arguments) > 2 else DEFAULT_TAP_GAP
        return TapKeys(_keys(arguments[0]), hold, gap)
    if name == "peek":
        _arity(name, arguments, "ADDRESS LENGTH", 2)
        return Peek(_address(arguments[0]), _length(arguments[1], PEEK_LIMIT))
    if name == "dump":
        _arity(name, arguments, "ADDRESS LENGTH FILE", 3)
        return Dump(_address(arguments[0]), _length(arguments[1]), arguments[2])
    if name == "poke":
        if len(arguments) < 2:
            raise _Invalid("usage: poke ADDRESS HEX")
        try:
            data = bytes.fromhex("".join(arguments[1:]))
        except ValueError:
            raise _Invalid("poke takes bytes in hex, two digits a byte") from None
        return Poke(_address(arguments[0]), data)
    if name == "break":
        _arity(name, arguments, "ADDRESS [COUNT [MEMORY LENGTH]]", 1, 2, 4)
        count = _count(arguments[1]) if len(arguments) > 1 else DEFAULT_POINT_COUNT
        probe = None
        if len(arguments) == 4:
            length = _length(arguments[3], PEEK_LIMIT)
            register = _REGISTER.fullmatch(arguments[2])
            if register:
                number = int(register.group(1))
                if number > 15:
                    raise _Invalid("registers are r0 to r15")
                probe = MemoryProbe(length, register=number)
            else:
                probe = MemoryProbe(length, address=_bus_address(arguments[2]))
        return Break(_bus_address(arguments[0]), count, probe)
    if name == "watch":
        _arity(name, arguments, "MODE ADDRESS [COUNT]", 2, 3)
        access = arguments[0].lower()
        if access not in WATCH_ACCESSES:
            raise _Invalid(f"the mode is one of {', '.join(WATCH_ACCESSES)}")
        count = _count(arguments[2]) if len(arguments) > 2 else DEFAULT_POINT_COUNT
        return Watch(access, _bus_address(arguments[1]), count)
    if name in {"clear", "reset"}:
        _arity(name, arguments, "", 0)
        return ClearPoints() if name == "clear" else Reset()
    if name == "echo":
        return Echo(" ".join(arguments))
    raise _Invalid(f"unknown command {name!r}")


def parse_script(text: str) -> tuple[Step, ...]:
    """Every command of a script; all mistakes are reported at once, by line."""
    steps = []
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        tokens = _tokens(line)
        if not tokens:
            continue
        try:
            steps.append(Step(number, _command(tokens[0].lower(), tokens[1:])))
        except _Invalid as exc:
            problems.append(f"line {number}: {exc}")
    _raise(problems)
    return tuple(steps)


def _raise(problems: list[str]) -> None:
    if problems:
        raise ClassicRetroError(ErrorCode.INVALID_EMULATOR_SCRIPT, "; ".join(problems))


def check_script(steps: Sequence[Step], emulator: Emulator) -> list[str]:
    """What this backend cannot do in the script, by line."""
    problems = []
    for step in steps:
        command = step.command
        keys: frozenset[str] = frozenset()
        addresses: list[Address] = []
        if isinstance(command, HoldKeys | TapKeys):
            keys = command.keys
        if isinstance(command, Peek | Dump | Poke):
            addresses.append(command.address)
        unsupported = sorted(keys - emulator.keys)
        if unsupported:
            problems.append(
                f"line {step.line}: this console has no {', '.join(unsupported)} key "
                f"(keys: {' '.join(sorted(emulator.keys))})"
            )
        for address in addresses:
            if isinstance(address, RegionAddress) and address.region not in emulator.regions:
                regions = ", ".join(sorted(emulator.regions)) or "none"
                problems.append(
                    f"line {step.line}: the {emulator.backend} backend has no region "
                    f"{address.region} (regions: {regions})"
                )
        if isinstance(command, Break | Watch | ClearPoints) and not emulator.debugger:
            problems.append(f"line {step.line}: {emulator.no_debugger()}")
        if (
            isinstance(command, Break)
            and command.probe is not None
            and command.probe.register is not None
            and emulator.platform != "gba"
        ):
            problems.append(f"line {step.line}: register memory probes need an ARM console (gba)")
    return problems


@dataclass(slots=True)
class _Point:
    line: int
    kind: str
    address: int
    limit: int | None
    hits: int = 0

    def describe(self) -> dict[str, object]:
        return {
            "line": self.line,
            "kind": self.kind,
            "address": _hex(self.address),
            "limit": self.limit,
            "hits": self.hits,
        }


def _hex(value: int, digits: int = 8) -> str:
    return f"0x{value:0{digits}X}"


def _where(address: Address) -> str:
    return str(address) if isinstance(address, RegionAddress) else _hex(address)


class _Session:
    def __init__(self, emulator: Emulator, directory: Path) -> None:
        self.emulator = emulator
        self.directory = directory
        self.held: frozenset[str] = frozenset()
        self.frames = 0
        self.events: list[dict[str, object]] = []
        self.files: list[dict[str, object]] = []
        self.points: dict[int, _Point] = {}
        self.cleared: list[_Point] = []

    def path(self, name: str) -> Path:
        path = Path(name)
        return path if path.is_absolute() else self.directory / path

    def output(self, line: int, command: str, name: str, data: bytes | None = None) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            path.write_bytes(data)
        self.files.append({"line": line, "command": command, "path": str(path)})
        return path

    def event(self, line: int, kind: str, **fields: object) -> None:
        self.events.append({"line": line, "frame": self.frames, "kind": kind, **fields})

    def advance(self, frames: int, keys: frozenset[str]) -> None:
        if frames == 0:
            return
        for hit in self.emulator.run(frames, keys):
            point = self.points.get(hit.point)
            if point is None:
                continue
            point.hits += 1
            self.events.append(self.hit_event(point, hit))
        self.frames += frames

    def hit_event(self, point: _Point, hit: Hit) -> dict[str, object]:
        digits = self.emulator.register_digits
        event: dict[str, object] = {
            "line": point.line,
            "frame": self.frames + hit.frame,
            "kind": hit.kind,
            "address": _hex(hit.address),
        }
        if hit.pc is not None:
            event["pc"] = _hex(hit.pc)
        if hit.access is not None:
            event["access"] = hit.access
            if hit.access == "write":
                event["old"] = _hex(hit.old or 0)
                event["new"] = _hex(hit.new or 0)
            else:
                event["value"] = _hex(hit.old or 0)
        event["registers"] = {name: _hex(value, digits) for name, value in hit.registers.items()}
        if hit.memory is not None:
            address, data = hit.memory
            event["memory"] = {"address": _hex(address), "bytes": data.hex()}
        return event

    def perform(self, step: Step) -> None:
        emulator = self.emulator
        command = step.command
        match command:
            case LoadState(path):
                emulator.load_state(self.path(path).read_bytes())
            case SaveState(path):
                self.output(step.line, "save", path, emulator.save_state())
            case HoldKeys(keys):
                self.held = keys
            case RunFrames(frames):
                self.advance(frames, self.held)
            case TapKeys(keys, hold, gap):
                self.advance(hold, self.held | keys)
                self.advance(gap, self.held)
            case Shot(path):
                emulator.screen().save_png(self.output(step.line, "shot", path))
            case Peek(address, length):
                data = emulator.read(address, length)
                self.event(step.line, "peek", address=_where(address), bytes=data.hex())
            case Dump(address, length, path):
                self.output(step.line, "dump", path, emulator.read(address, length))
            case Poke(address, data):
                emulator.write(address, data)
            case Break(address, count, probe):
                point = emulator.add_breakpoint(address, count, probe)
                self.points[point] = _Point(step.line, "breakpoint", address, count)
            case Watch(access, address, count):
                point = emulator.add_watchpoint(address, access, count)
                self.points[point] = _Point(step.line, "watchpoint", address, count)
            case ClearPoints():
                emulator.clear_points()
                self.cleared.extend(self.points.values())
                self.points.clear()
            case Reset():
                emulator.reset()
            case Echo(text):
                self.event(step.line, "echo", text=text)


def run_script(emulator: Emulator, steps: Sequence[Step], directory: Path) -> dict[str, object]:
    """Run ``steps`` on ``emulator``; the report of frames, files, events and points."""
    _raise(check_script(steps, emulator))
    session = _Session(emulator, directory)
    for step in steps:
        try:
            session.perform(step)
        except ClassicRetroError as exc:
            raise ClassicRetroError(exc.code, f"line {step.line}: {exc}") from exc
        except OSError as exc:
            raise ClassicRetroError(ErrorCode.EMULATOR_FAILED, f"line {step.line}: {exc}") from exc
    points = sorted([*session.cleared, *session.points.values()], key=lambda point: point.line)
    return {
        "frames": session.frames,
        "files": session.files,
        "events": session.events,
        "points": [point.describe() for point in points],
    }
