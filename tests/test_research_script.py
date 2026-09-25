"""The research script language and runner, on a fake emulator."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.emulator import (
    Address,
    Emulator,
    Hit,
    MemoryProbe,
    RegionAddress,
    Screen,
)
from classic_retro.research.script import (
    Break,
    Echo,
    HoldKeys,
    Poke,
    Shot,
    TapKeys,
    Watch,
    parse_script,
    run_script,
)


class FakeEmulator(Emulator):
    """Counts frames into memory; a breakpoint hits once a frame."""

    backend = "fake"
    core = "fake core"
    platform = "gba"
    keys = frozenset({"A", "B", "START", "UP"})
    regions = frozenset({"system_ram"})
    debugger = True

    def __init__(self) -> None:
        self.memory = bytearray(64)
        self.frames = 0
        self.pressed: list[frozenset[str]] = []
        self.points: dict[int, tuple[str, int, int | None]] = {}
        self.closed = False

    def run(self, frames: int, keys: frozenset[str]) -> list[Hit]:
        hits = []
        for frame in range(frames):
            self.frames += 1
            self.pressed.append(keys)
            self.memory[0] = self.frames & 0xFF
            for point, (kind, address, remaining) in list(self.points.items()):
                if remaining == 0:
                    continue
                hits.append(
                    Hit(point, frame, kind, address, {"r0": self.frames}, pc=address, access=None)
                )
                self.points[point] = (kind, address, None if remaining is None else remaining - 1)
        return hits

    def screen(self) -> Screen:
        return Screen(2, 1, bytes([self.frames, 0, 0, 0, self.frames, 0]))

    def save_state(self) -> bytes:
        return bytes([self.frames]) + bytes(self.memory)

    def load_state(self, state: bytes) -> None:
        self.frames = state[0]
        self.memory[:] = state[1:]

    def _offset(self, address: Address) -> int:
        return address.offset if isinstance(address, RegionAddress) else address - 0x100

    def read(self, address: Address, length: int) -> bytes:
        start = self._offset(address)
        return bytes(self.memory[start : start + length])

    def write(self, address: Address, data: bytes) -> None:
        start = self._offset(address)
        self.memory[start : start + len(data)] = data

    def reset(self) -> None:
        self.frames = 0

    def close(self) -> None:
        self.closed = True

    def add_breakpoint(self, address: int, count: int | None, probe: MemoryProbe | None) -> int:
        self.points[len(self.points) + 1] = ("breakpoint", address, count)
        return len(self.points)

    def add_watchpoint(self, address: int, access: str, count: int | None) -> int:
        self.points[len(self.points) + 1] = ("watchpoint", address, count)
        return len(self.points)

    def clear_points(self) -> None:
        self.points.clear()


def test_parse_reads_every_command():
    steps = parse_script(
        """
        # reach the title screen
        load start.state
        keys A+up                  # held from now on
        run 0x10
        tap START
        tap B 4 0
        shot "title screen.png"
        peek system_ram:0x20 4
        dump 0x02000000 256 ewram.bin
        poke 0x02000000 01 ff
        break 0x08001234
        break 0x08001234 all r1 16
        break 0x08001234 3 0x02000000 8
        watch write 0x02000004
        watch change 0x02000004 all
        clear
        reset
        echo title  reached
        save "states/title.state"
        """
    )
    assert [step.line for step in steps][:3] == [3, 4, 5]
    commands = [step.command for step in steps]
    assert commands[1] == HoldKeys(frozenset({"A", "UP"}))
    assert commands[3] == TapKeys(frozenset({"START"}), 2, 8)
    assert commands[4] == TapKeys(frozenset({"B"}), 4, 0)
    assert commands[5] == Shot("title screen.png")
    assert commands[8] == Poke(0x02000000, b"\x01\xff")
    assert commands[9] == Break(0x08001234, 100, None)
    assert commands[10] == Break(0x08001234, None, MemoryProbe(16, register=1))
    assert commands[11] == Break(0x08001234, 3, MemoryProbe(8, address=0x02000000))
    assert commands[12] == Watch("write", 0x02000004, 100)
    assert commands[13] == Watch("change", 0x02000004, None)
    assert commands[16] == Echo("title reached")


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("jump 5", "unknown command 'jump'"),
        ("run", "usage: run FRAMES"),
        ("run ten", "the frame count must be a number"),
        ("run -1", "cannot be negative"),
        ("keys A+Z", "unknown keys Z"),
        ("tap A 1 2 3", "usage: tap KEYS [HOLD [GAP]]"),
        ("shot title.bmp", "name it FILE.png"),
        ("peek 0x02000000 0", "at least 1"),
        ("peek 0x02000000 5000", "at most 4096"),
        ("poke 0x02000000 1", "two digits a byte"),
        ("break 0x08000000 0", "at least 1"),
        ("break 0x08000000 2 r1", "usage: break"),
        ("break 0x08000000 2 r16 4", "r0 to r15"),
        ("break system_ram:0x10", "bus address"),
        ("watch 0x02000000 0x10", "the mode is one of"),
        ("clear now", "usage: clear"),
        ("peek :0x10 4", "names no region"),
    ],
)
def test_parse_rejects_mistakes(line: str, message: str):
    with pytest.raises(ClassicRetroError) as error:
        parse_script(line)
    assert error.value.code is ErrorCode.INVALID_EMULATOR_SCRIPT
    assert message in str(error.value)


def test_parse_reports_every_mistake_by_line():
    with pytest.raises(ClassicRetroError) as error:
        parse_script("run 1\nrun x\n\nfly\n")
    assert str(error.value).startswith("line 2: ")
    assert "; line 4: unknown command 'fly'" in str(error.value)


def test_run_script_reports_frames_files_events_and_points(tmp_path: Path):
    steps = parse_script(
        """
        run 3
        peek 0x100 1
        keys A
        break 0x08000010 2
        tap B 2 1
        echo tapped
        shot out/frame.png
        save out/three.state
        run 4
        load out/three.state
        peek system_ram:0x00 1
        poke 0x101 aa
        dump 0x100 2 out/memory.bin
        clear
        run 1
        reset
        """
    )
    emulator = FakeEmulator()
    report = run_script(emulator, steps, tmp_path)
    assert report["frames"] == 11
    assert emulator.pressed == [
        *[frozenset()] * 3,
        *[frozenset({"A", "B"})] * 2,
        frozenset({"A"}),
        *[frozenset({"A"})] * 5,
    ]
    assert [event["kind"] for event in report["events"]] == [
        "peek",
        "breakpoint",
        "breakpoint",
        "echo",
        "peek",
    ]
    peek, first, second, echo, reloaded = report["events"]
    assert peek == {"line": 3, "frame": 3, "kind": "peek", "address": "0x00000100", "bytes": "03"}
    assert first["line"] == second["line"] == 5
    assert (first["frame"], second["frame"]) == (3, 4)
    assert first["registers"] == {"r0": "0x00000004"}
    assert echo == {"line": 7, "frame": 6, "kind": "echo", "text": "tapped"}
    # The state saved after six frames holds 6, whatever ran after it.
    assert reloaded["address"] == "system_ram:0x0" and reloaded["bytes"] == "06"
    assert report["points"] == [
        {"line": 5, "kind": "breakpoint", "address": "0x08000010", "limit": 2, "hits": 2}
    ]
    files = {Path(item["path"]).name: item for item in report["files"]}
    assert files["frame.png"]["line"] == 8 and files["three.state"]["command"] == "save"
    assert (tmp_path / "out/memory.bin").read_bytes() == b"\x06\xaa"
    with Image.open(tmp_path / "out/frame.png") as picture:
        assert picture.size == (2, 1)
        assert picture.getpixel((0, 0)) == (6, 0, 0)


def test_run_script_checks_the_backend_before_running(tmp_path: Path):
    class NoDebugger(FakeEmulator):
        debugger = False
        platform = "gb"
        regions = frozenset()

    steps = parse_script(
        "run 1\nkeys L\npeek video_ram:0 1\nbreak 0x100\nwatch read 0x100\nclear\n"
    )
    emulator = NoDebugger()
    with pytest.raises(ClassicRetroError) as error:
        run_script(emulator, steps, tmp_path)
    message = str(error.value)
    assert error.value.code is ErrorCode.INVALID_EMULATOR_SCRIPT
    assert "line 2: this console has no L key" in message
    assert "line 3: the fake backend has no region video_ram (regions: none)" in message
    for line in (4, 5, 6):
        assert f"line {line}: The fake backend has no debugger" in message
    assert emulator.frames == 0

    with pytest.raises(ClassicRetroError, match="register memory probes need an ARM console"):
        run_script(
            type("GameBoy", (FakeEmulator,), {"platform": "gb"})(),
            parse_script("break 0x100 1 r0 4"),
            tmp_path,
        )


def test_run_script_names_the_failing_line(tmp_path: Path):
    with pytest.raises(ClassicRetroError) as error:
        run_script(FakeEmulator(), parse_script("run 1\nload missing.state\n"), tmp_path)
    assert error.value.code is ErrorCode.EMULATOR_FAILED
    assert str(error.value).startswith("line 2: ")
