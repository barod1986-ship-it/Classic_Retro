"""The mgba backend: a small C harness built against the user's libmgba.

mGBA runs Game Boy Advance, Game Boy and Game Boy Color games, and its debugger
gives breakpoints and watchpoints. The harness (``mgba_harness.c``, shipped in
this package) is compiled on first use with the system C compiler and cached,
keyed by its source and build flags, so it is rebuilt only when either changes.

It needs a C compiler and libmgba's development files (Debian and Ubuntu:
``libmgba-dev``). ``CC`` names the compiler; ``CLASSIC_RETRO_MGBA_CFLAGS`` and
``CLASSIC_RETRO_MGBA_LIBS`` override the flags (by default pkg-config's
``libmgba``, else ``-lmgba``); ``CLASSIC_RETRO_CACHE`` moves the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from importlib.resources import as_file, files
from pathlib import Path
from typing import IO, Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.emulator import (
    Address,
    Emulator,
    Hit,
    MemoryProbe,
    RegionAddress,
    Screen,
)

HARNESS_SOURCE = "mgba_harness.c"
# mGBA's key bits; a Game Boy has the first eight.
_KEY_BITS = {
    "A": 0,
    "B": 1,
    "SELECT": 2,
    "START": 3,
    "RIGHT": 4,
    "LEFT": 5,
    "UP": 6,
    "DOWN": 7,
    "R": 8,
    "L": 9,
}
_GB_KEYS = frozenset(name for name, bit in _KEY_BITS.items() if bit < 8)
# mGBA's watchpoint types.
_WATCH_TYPES = {"write": 1, "read": 2, "access": 3, "change": 5}
_INSTALL_HINT = (
    "the mgba backend needs a C compiler and libmgba's development files "
    "(Debian/Ubuntu: apt install build-essential libmgba-dev)"
)


def cache_dir() -> Path:
    """Where built helpers are kept: ``CLASSIC_RETRO_CACHE``, else the user's cache."""
    configured = os.environ.get("CLASSIC_RETRO_CACHE")
    if configured:
        return Path(configured)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "classic-retro"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "classic-retro"


def _pkg_config(*arguments: str) -> list[str] | None:
    tool = shutil.which("pkg-config")
    if tool is None:
        return None
    result = subprocess.run(
        [tool, *arguments, "libmgba"], capture_output=True, text=True, check=False
    )
    return shlex.split(result.stdout) if result.returncode == 0 else None


def _flags(variable: str, pkg_config: str, default: list[str]) -> list[str]:
    configured = os.environ.get(variable)
    if configured is not None:
        return shlex.split(configured)
    found = _pkg_config(pkg_config)
    return default if found is None else found


def build_harness(directory: Path | None = None) -> Path:
    """The harness binary, compiled into ``directory`` (the cache) unless already there."""
    source = files("classic_retro.research").joinpath(HARNESS_SOURCE)
    compiler = shlex.split(os.environ.get("CC", "cc"))
    if not compiler or shutil.which(compiler[0]) is None:
        raise ClassicRetroError(
            ErrorCode.EMULATOR_UNAVAILABLE,
            f"No C compiler {' '.join(compiler)!r} (set CC): {_INSTALL_HINT}",
        )
    cflags = _flags("CLASSIC_RETRO_MGBA_CFLAGS", "--cflags", [])
    libs = _flags("CLASSIC_RETRO_MGBA_LIBS", "--libs", ["-lmgba"])
    key = hashlib.sha256(
        json.dumps([source.read_bytes().hex(), compiler, cflags, libs]).encode()
    ).hexdigest()[:16]
    folder = directory or cache_dir()
    binary = folder / f"mgba-harness-{key}{'.exe' if os.name == 'nt' else ''}"
    if binary.is_file():
        return binary
    folder.mkdir(parents=True, exist_ok=True)
    handle, partial = tempfile.mkstemp(prefix="mgba-harness-", dir=folder)
    os.close(handle)
    try:
        with as_file(source) as path:
            result = subprocess.run(
                [*compiler, "-O2", "-o", partial, str(path), *cflags, *libs],
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-12:]
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE,
                f"Could not build the mGBA harness; {_INSTALL_HINT}:\n" + "\n".join(detail),
            )
        os.chmod(partial, 0o755)
        os.replace(partial, binary)
    finally:
        if os.path.exists(partial):
            os.unlink(partial)
    return binary


class MgbaEmulator(Emulator):
    """A game under the mGBA harness: GBA, GB and GBC, with breakpoints and watchpoints."""

    backend = "mgba"
    debugger = True

    def __init__(self, image: Path, *, harness: Path | None = None) -> None:
        binary = harness or build_harness()
        self._errors: IO[bytes] = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(
                [str(binary), str(image)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._errors,
            )
        except OSError as exc:
            self._errors.close()
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE, f"Could not start the mGBA harness {binary}: {exc}"
            ) from exc
        self._hits: list[Hit] = []
        try:
            platform, _width, _height, version = self._reply("ready")
        except (ClassicRetroError, ValueError):
            self.close()
            raise
        self.platform = platform
        self.core = f"mGBA {version}"
        self.keys = frozenset(_KEY_BITS) if platform == "gba" else _GB_KEYS
        self.register_digits = 8 if platform == "gba" else 4

    # The pipe protocol: see mgba_harness.c.

    def _send(self, line: str, payload: bytes = b"") -> None:
        pipe = self._process.stdin
        assert pipe is not None
        try:
            pipe.write(line.encode("ascii") + b"\n" + payload)
            pipe.flush()
        except OSError as exc:
            raise self._failure(f"the harness stopped ({exc})") from exc

    def _reply(self, expected: str = "ok") -> list[str]:
        pipe = self._process.stdout
        assert pipe is not None
        while True:
            line = pipe.readline().decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                raise self._failure("the harness stopped")
            word, _, rest = line.partition(" ")
            if word == "hit":
                self._hits.append(self._hit(json.loads(rest)))
            elif word == "error":
                raise ClassicRetroError(ErrorCode.EMULATOR_FAILED, f"mGBA: {rest}")
            elif word == expected:
                return rest.split()
            else:
                raise self._failure(f"unexpected reply {line!r}")

    def _payload(self, size: int) -> bytes:
        pipe = self._process.stdout
        assert pipe is not None
        data = pipe.read(size)
        if len(data) != size:
            raise self._failure("the harness stopped mid-reply")
        return data

    def _failure(self, message: str) -> ClassicRetroError:
        self._process.poll()
        self._errors.seek(0)
        detail = self._errors.read().decode("utf-8", "replace").strip()
        return ClassicRetroError(
            ErrorCode.EMULATOR_FAILED, f"mGBA: {message}" + (f": {detail}" if detail else "")
        )

    def _hit(self, data: dict[str, Any]) -> Hit:
        registers = data["registers"]
        kind = "watchpoint" if data["kind"] == "watch" else "breakpoint"
        pc = None
        if self.platform == "gba":
            # Mid-instruction, r15 reads two instructions ahead of the one executing.
            ahead = 4 if registers["cpsr"] & 0x20 else 8
            pc = data["address"] if kind == "breakpoint" else registers["r15"] - ahead
        memory = None
        if "memory" in data:
            memory = (data["memory_address"], bytes.fromhex(data["memory"]))
        access = data.get("access")
        return Hit(
            point=data["id"],
            frame=data["frame"],
            kind=kind,
            address=data["address"],
            registers=registers,
            pc=pc,
            access=access,
            old=data.get("old"),
            new=data.get("new") if access == "write" else None,
            memory=memory,
        )

    @staticmethod
    def _bus(address: Address) -> int:
        if isinstance(address, RegionAddress):
            raise ClassicRetroError(
                ErrorCode.INVALID_EMULATOR_SCRIPT, "the mgba backend takes bus addresses"
            )
        return address

    def run(self, frames: int, keys: frozenset[str]) -> list[Hit]:
        mask = sum(1 << _KEY_BITS[key] for key in keys)
        self._hits = []
        self._send(f"run {frames} {mask}")
        self._reply()
        hits, self._hits = self._hits, []
        return hits

    def screen(self) -> Screen:
        self._send("screen")
        width, height = (int(value) for value in self._reply())
        return Screen(width, height, self._payload(width * height * 3))

    def save_state(self) -> bytes:
        self._send("save")
        (size,) = self._reply()
        return self._payload(int(size))

    def load_state(self, state: bytes) -> None:
        self._send(f"load {len(state)}", state)
        self._reply()

    def read(self, address: Address, length: int) -> bytes:
        self._send(f"read {self._bus(address)} {length}")
        (size,) = self._reply()
        return self._payload(int(size))

    def write(self, address: Address, data: bytes) -> None:
        self._send(f"write {self._bus(address)} {len(data)}", data)
        self._reply()

    def reset(self) -> None:
        self._send("reset")
        self._reply()

    def add_breakpoint(self, address: int, count: int | None, probe: MemoryProbe | None) -> int:
        kind, value, length = 0, 0, 0
        if probe is not None:
            length = probe.length
            if probe.register is not None:
                kind, value = 1, probe.register
            else:
                kind, value = 2, probe.address or 0
        self._send(f"break {address} {-1 if count is None else count} {kind} {value} {length}")
        (point,) = self._reply()
        return int(point)

    def add_watchpoint(self, address: int, access: str, count: int | None) -> int:
        watch = _WATCH_TYPES[access]
        self._send(f"watch {address} {watch} {-1 if count is None else count}")
        (point,) = self._reply()
        return int(point)

    def clear_points(self) -> None:
        self._send("clear")
        self._reply()

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is not None and process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.write(b"quit\n")
                process.stdin.close()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        self._errors.close()
