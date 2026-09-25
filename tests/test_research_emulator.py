"""The research emulator backends, run on a tiny generated GBA program.

The program holds no game data. It fills the screen with red, then once a frame
writes the keys to the first pixel and to 0x02000000, and counts the frames at
0x02000004. A test is skipped when its backend is not installed (a C compiler
and libmgba-dev; a libretro mGBA core), unless CLASSIC_RETRO_REQUIRE_EMULATORS
is set, as in CI, where a missing backend fails instead.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from typing import NoReturn

import pytest
from PIL import Image

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching.hooks import HookProgram
from classic_retro.research.emulator import Emulator, RegionAddress
from classic_retro.research.libretro import LibretroEmulator
from classic_retro.research.mgba import MgbaEmulator, build_harness
from classic_retro.research.script import parse_script, run_script

REQUIRED = bool(os.environ.get("CLASSIC_RETRO_REQUIRE_EMULATORS"))

PROGRAM_SOURCE = """\
    .arm
start:
    b       init                @ byte 3 is 0xEA: the ARM branch the header expects
    .space  0xBC                @ the header; the test writes 0x96 and the checksum
init:
    mov     r0, #0x04000000     @ I/O registers
    mov     r1, #0x0400
    orr     r1, r1, #0x0003
    strh    r1, [r0]            @ DISPCNT: mode 3, BG2 on
    mov     r2, #0x06000000     @ the mode 3 frame buffer
    mov     r3, #0x001F         @ red, BGR555
    mov     r4, #0x9600         @ 240 * 160 pixels
fill:
    strh    r3, [r2], #2
    subs    r4, r4, #1
    bne     fill
    add     r9, r0, #0x130      @ KEYINPUT: a clear bit for each pressed key
    mov     r6, #0x02000000     @ EWRAM
    mov     r7, #0
frame:
    ldrh    r5, [r9]
    mov     r2, #0x06000000
keys:
    strh    r5, [r2]            @ the first pixel shows the keys
    strh    r5, [r6]            @ 0x02000000: the keys
    add     r7, r7, #1
count:
    str     r7, [r6, #4]        @ 0x02000004: frames counted
leave:
    ldrh    r8, [r0, #6]        @ VCOUNT: wait for the vertical blank to end
    cmp     r8, #160
    beq     leave
enter:
    ldrh    r8, [r0, #6]        @ then for the next one to begin
    cmp     r8, #160
    bne     enter
    b       frame
"""
PROGRAM = HookProgram(
    label="research test program",
    source=Path("research_test_program.s"),
    address=0x08000000,
    code=bytes.fromhex("2e0000ea")
    + bytes(0xBC)
    + bytes.fromhex(
        "0103a0e3011ba0e3031081e3b010c0e10624a0e31f30a0e3964ca0e3b230c2e0"
        "014054e2fcffff1a139e80e20264a0e30070a0e3b050d9e10624a0e3b050c2e1"
        "b050c6e1017087e2047086e5b680d0e1a00058e3fcffff0ab680d0e1a00058e3"
        "fcffff1af2ffffea"
    ),
    symbols={"keys": 0xFC, "count": 0x108},
)
KEYS_AT = PROGRAM.symbol_address("keys")
COUNT_AT = PROGRAM.symbol_address("count")
NO_KEYS = 0x03FF  # KEYINPUT with no key pressed
A_HELD = 0x03FE
LIBRETRO_CORES = (
    "/usr/lib/x86_64-linux-gnu/libretro/mgba_libretro.so",
    "/usr/lib/aarch64-linux-gnu/libretro/mgba_libretro.so",
    "/usr/lib/libretro/mgba_libretro.so",
    "/usr/local/lib/libretro/mgba_libretro.so",
)


def _unavailable(reason: str) -> NoReturn:
    if REQUIRED:
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    rom = bytearray(PROGRAM.code)
    rom += b"\xff" * (0x400 - len(rom))
    rom[0xB2] = 0x96
    rom[0xBD] = -(sum(rom[0xA0:0xBD]) + 0x19) & 0xFF
    path = tmp_path_factory.mktemp("program") / "program.gba"
    path.write_bytes(rom)
    return path


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    try:
        return build_harness(tmp_path_factory.mktemp("harness"))
    except ClassicRetroError as exc:
        _unavailable(f"no mGBA harness: {exc}")


@pytest.fixture(scope="module")
def core() -> Path:
    configured = os.environ.get("CLASSIC_RETRO_LIBRETRO_CORE")
    for candidate in (configured, *LIBRETRO_CORES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    _unavailable("no libretro mGBA core (Debian/Ubuntu: libretro-mgba)")


@pytest.fixture(params=["mgba", "libretro"])
def emulator(request: pytest.FixtureRequest, image: Path):
    if request.param == "mgba":
        session: Emulator = MgbaEmulator(image, harness=request.getfixturevalue("harness"))
    else:
        session = LibretroEmulator(request.getfixturevalue("core"), image)
    with session:
        yield session


def _word(emulator: Emulator, address: int, size: int) -> int:
    return int.from_bytes(emulator.read(address, size), "little")


def test_the_assembled_program_matches_its_source(tmp_path: Path):
    if shutil.which("arm-none-eabi-as") is None:
        _unavailable("needs GNU ARM binutils")
    source = tmp_path / "program.s"
    source.write_text(PROGRAM_SOURCE)
    assert PROGRAM.check(source)["match"]


def test_frames_keys_screen_and_memory(emulator: Emulator):
    assert emulator.keys >= {"A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT"}
    assert emulator.run(10, frozenset()) == []
    counted = _word(emulator, 0x02000004, 4)
    assert 1 <= counted <= 10
    assert _word(emulator, 0x02000000, 2) == NO_KEYS
    emulator.run(2, frozenset({"A"}))
    assert _word(emulator, 0x02000000, 2) == A_HELD
    assert _word(emulator, 0x02000004, 4) == counted + 2

    screen = emulator.screen()
    assert (screen.width, screen.height) == (240, 160)
    red, green, blue = screen.pixel(239, 159)
    assert red > 0xF0 and green == blue == 0
    red, green, blue = screen.pixel(0, 0)  # 0x03FE: red 30, green 31, no blue
    assert red > 0xE0 and green > 0xF0 and blue == 0

    emulator.write(0x02000010, b"\x12\x34")
    assert emulator.read(0x02000010, 2) == b"\x12\x34"
    assert emulator.read(0x08000000, 4) == PROGRAM.code[:4]


def test_savestates_return_to_the_same_frame(emulator: Emulator):
    emulator.run(6, frozenset())
    state = emulator.save_state()
    saved = _word(emulator, 0x02000004, 4)
    emulator.run(5, frozenset())
    after = _word(emulator, 0x02000004, 4)
    assert after == saved + 5
    emulator.load_state(state)
    assert _word(emulator, 0x02000004, 4) == saved
    emulator.run(5, frozenset())
    assert _word(emulator, 0x02000004, 4) == after
    with pytest.raises(ClassicRetroError) as error:
        emulator.load_state(b"not a state")
    assert error.value.code is ErrorCode.EMULATOR_FAILED


def test_mgba_breakpoints_and_watchpoints(image: Path, harness: Path, tmp_path: Path):
    script = parse_script(
        f"""
        run 8
        keys A
        break {KEYS_AT:#x} 2 r6 8     # the keys, and the words at 0x02000000
        watch write 0x02000004 3
        watch read {KEYS_AT:#x} 1     # an instruction fetch is not a data read
        run 4
        clear
        run 2
        echo done
        """
    )
    with MgbaEmulator(image, harness=harness) as emulator:
        report = run_script(emulator, script, tmp_path)
    events = report["events"]
    breaks = [event for event in events if event["kind"] == "breakpoint"]
    writes = [event for event in events if event["kind"] == "watchpoint"]
    assert len(breaks) == 2 and len(writes) == 3
    first = breaks[0]
    assert first["line"] == 4 and first["address"] == first["pc"] == f"0x{KEYS_AT:08X}"
    assert first["registers"]["r5"] == f"0x{A_HELD:08X}"
    assert first["registers"]["r6"] == "0x02000000"
    assert first["memory"]["address"] == "0x02000000"
    counted = int.from_bytes(bytes.fromhex(first["memory"]["bytes"])[4:], "little")
    write = writes[0]
    assert write["access"] == "write" and write["address"] == "0x02000004"
    assert write["pc"] == f"0x{COUNT_AT:08X}"
    assert int(write["new"], 16) == int(write["old"], 16) + 1 == counted + 1
    assert all(8 <= event["frame"] < 12 for event in breaks + writes)
    assert events[-1] == {"line": 10, "frame": 14, "kind": "echo", "text": "done"}
    assert report["points"] == [
        {"line": 4, "kind": "breakpoint", "address": f"0x{KEYS_AT:08X}", "limit": 2, "hits": 2},
        {"line": 5, "kind": "watchpoint", "address": "0x02000004", "limit": 3, "hits": 3},
        {"line": 6, "kind": "watchpoint", "address": f"0x{KEYS_AT:08X}", "limit": 1, "hits": 0},
    ]


def test_mgba_harness_reports_what_it_cannot_run(harness: Path, tmp_path: Path):
    not_a_game = tmp_path / "notes.txt"
    not_a_game.write_text("not a game image")
    with pytest.raises(ClassicRetroError) as error:
        MgbaEmulator(not_a_game, harness=harness)
    assert error.value.code is ErrorCode.EMULATOR_FAILED
    assert "does not recognise" in str(error.value)


def test_libretro_regions_and_limits(image: Path, core: Path, tmp_path: Path):
    with LibretroEmulator(core, image) as emulator:
        assert emulator.core.startswith("mGBA")
        assert not emulator.debugger
        emulator.run(8, frozenset({"B"}))
        assert emulator.read(0x02000000, 2) == (0x03FD).to_bytes(2, "little")
        # The core names its save RAM as a region and maps it at 0x0E000000.
        emulator.write(RegionAddress("save_ram", 0x10), b"\x5a\xa5")
        assert emulator.read(0x0E000010, 2) == b"\x5a\xa5"
        with pytest.raises(ClassicRetroError, match="not mapped"):
            emulator.read(0x0F000000, 4)
        with pytest.raises(ClassicRetroError, match="read-only"):
            emulator.write(0x08000000, b"\x00")
        with pytest.raises(ClassicRetroError, match="outside"):
            emulator.read(RegionAddress("save_ram", 0x20000), 1)
        with pytest.raises(ClassicRetroError) as error:
            run_script(emulator, parse_script("break 0x08000000"), tmp_path)
        assert error.value.code is ErrorCode.INVALID_EMULATOR_SCRIPT
        assert "no debugger" in str(error.value)
        with pytest.raises(ClassicRetroError, match="already runs"):
            LibretroEmulator(core, image)


def _cli(*arguments: str) -> dict:
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(list(arguments)) == 0
    return json.loads(output.getvalue())


def test_research_run_command(image: Path, harness: Path, core: Path, tmp_path: Path):
    script = tmp_path / "reach.txt"
    script.write_text(
        'run 10\ntap A 3 2\nshot "shots/after tap.png"\npeek 0x02000000 2\nsave state.bin\n'
    )
    run = ("research", "run", str(image), str(script), "--out-dir")
    reports = {
        "mgba": _cli(*run, str(tmp_path / "mgba"), "--harness", str(harness)),
        "libretro": _cli(*run, str(tmp_path / "libretro"), "--core", str(core)),
    }
    for backend, report in reports.items():
        assert report["backend"] == backend
        assert report["frames"] == 15
        assert [item["command"] for item in report["files"]] == ["shot", "save"]
        assert report["events"][0]["bytes"] == "ff03"
        shot = Path(report["files"][0]["path"])
        assert shot == tmp_path / backend / "shots" / "after tap.png"
        with Image.open(shot) as picture:
            assert picture.size == (240, 160)
        assert (tmp_path / backend / "state.bin").stat().st_size > 0
    assert reports["mgba"]["platform"] == "gba"
    assert reports["mgba"]["image_sha256"] == reports["libretro"]["image_sha256"]
