from __future__ import annotations

import hashlib
import shutil
import struct

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu import thumb
from classic_retro.patching import hooks
from classic_retro.patching.hooks import HookProgram, assembler_for, register_assembler
from classic_retro.patching.image import GBA_ROM_BASE, ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import create_bps


def test_bl_round_trips_and_checks_its_range():
    for address, target in ((0x08001000, 0x08001008), (0x08400000, 0x08000100)):
        code = thumb.bl_instruction(address, target)
        assert thumb.bl_target(address, code) == target
    assert thumb.bl_instruction(0x0804EFD0, 0x0804EFD8) == bytes.fromhex("00f002f8")
    with pytest.raises(ClassicRetroError) as error:
        thumb.bl_instruction(0x08000000, 0x08800000)
    assert error.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS
    with pytest.raises(ClassicRetroError) as error:
        thumb.bl_target(0x08000000, b"\x00\x00\x00\x00")
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_branch_reaches_two_kilobytes():
    assert thumb.branch_instruction(0x0804EFD4, 0x0804EFE0) == bytes.fromhex("04e0")
    assert thumb.branch_instruction(0x08000100, 0x080000FC) == bytes.fromhex("fce7")
    with pytest.raises(ClassicRetroError):
        thumb.branch_instruction(0x08000000, 0x08001000)


def test_literal_jump_puts_its_word_on_the_next_boundary():
    aligned = thumb.literal_jump(0x08000000, 2, 0x08760000)
    assert aligned == bytes.fromhex("004a1047") + struct.pack("<I", 0x08760001)
    unaligned = thumb.literal_jump(0x08000002, 0, 0x08800000)
    assert unaligned == bytes.fromhex("01480047c046") + struct.pack("<I", 0x08800001)
    with pytest.raises(ClassicRetroError) as error:
        thumb.literal_jump(0x08000000, 8, 0x08800000)
    assert error.value.code is ErrorCode.REFERENCE_ALIGNMENT_ERROR


def test_veneers():
    patch = thumb.bl_veneer_patch(0x0819975C, 0x0819977A, 0x08D00000)
    assert patch == bytes.fromhex("00f002f80be0c04600480047") + struct.pack("<I", 0x08D00001)
    assert thumb.arm_veneer(0x08F00000) == struct.pack(
        "<HHIII", 0x4778, 0x46C0, 0xE59FC000, 0xE12FFF1C, 0x08F00001
    )


def test_image_spec_verifies_and_reads():
    rom = bytearray(0x100)
    struct.pack_into("<I", rom, 0x10, 0x08000040)
    struct.pack_into("<I", rom, 0x20, 0x08000040)
    rom[0x80:] = b"\xff" * 0x80
    image = ImageSpec("Test Game (USA)", hashlib.sha256(rom).hexdigest(), len(rom))
    image.verify(bytes(rom))
    with pytest.raises(ClassicRetroError) as error:
        image.verify(bytes(rom[:-1]))
    assert error.value.code is ErrorCode.UNKNOWN_GAME_REVISION
    assert str(error.value).startswith("Input is not Test Game (USA) with SHA-256 ")
    assert image.base == GBA_ROM_BASE and image.offset(0x08000010) == 0x10
    assert image.word(rom, 0x08000010) == 0x08000040
    assert image.read(rom, 0x08000080, 2) == b"\xff\xff"
    assert image.filled(rom, 0x08000080, 0x08000100, 0xFF)
    assert not image.filled(rom, 0x08000000, 0x08000100, 0xFF)
    assert image.references(rom, {0x08000040, 0x08000050}) == {
        0x08000040: [0x08000010, 0x08000020],
        0x08000050: [],
    }


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_hook_program_checks_its_stored_bytes(tmp_path):
    source = tmp_path / "hooks.s"
    source.write_text(
        ".syntax unified\n.cpu arm7tdmi\n.thumb\n.text\n"
        ".global entry\n.thumb_func\nentry:\n    movs r0, #1\n    bx lr\n"
    )
    program = HookProgram("test hooks", source, 0x08700000, bytes.fromhex("01207047"), {"entry": 0})
    assert program.check() == {"hook_bytes": 4, "symbols": {"entry": 0}, "match": True}
    assert program.thumb_entry("entry") == 0x08700001
    wrong = HookProgram("test hook", source, 0x08700000, b"\0\0\0\0", {"entry": 0}, singular=True)
    with pytest.raises(ClassicRetroError) as error:
        wrong.check()
    assert "Assembled test hook differs from the stored" in str(error.value)
    broken = tmp_path / "broken.s"
    broken.write_text(".thumb\n    not_an_instruction\n")
    with pytest.raises(ClassicRetroError) as error:
        program.assemble(broken)
    assert str(error.value).startswith("Assembling the test hooks failed:")


def test_assemblers_are_registered_per_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "_ASSEMBLERS", dict(hooks._ASSEMBLERS))

    def fake(source, address, symbols, label):
        return b"\xea", {name: address + 1 for name in symbols}

    register_assembler("fake-cpu", fake)
    program = HookProgram("fake hooks", tmp_path / "x.s", 0x8000, b"\xea", {"start": 1}, "fake-cpu")
    assert program.check()["match"] is True
    assert assembler_for("arm7tdmi") is hooks.assemble_gnu_arm
    with pytest.raises(ClassicRetroError) as error:
        register_assembler("fake-cpu", fake)
    assert error.value.code is ErrorCode.ADAPTER_ID_CONFLICT
    with pytest.raises(ClassicRetroError):
        assembler_for("z80")


def test_outputs_report_and_files(tmp_path):
    rom, output = b"\x00" * 64, b"\x01" + b"\x00" * 63
    patch = create_bps(rom, output)
    report = base_report("Test Game", rom, output, patch)
    assert report["game"] == "Test Game"
    assert report["base_sha256"] == hashlib.sha256(rom).hexdigest()
    assert report["target_sha256"] == hashlib.sha256(output).hexdigest()
    assert report["patch_bytes"] == len(patch.data) and report["target_bytes"] == 64
    path = write_patch(tmp_path / "out", "test.bps", patch)
    assert path.read_bytes() == patch.data
    assert write_image(tmp_path / "out", None, output) == {}
    written = write_image(tmp_path / "out", "test.gba", output)
    assert (tmp_path / "out" / "test.gba").read_bytes() == output
    assert written == {"rom": str(tmp_path / "out" / "test.gba")}
