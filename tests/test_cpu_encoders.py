"""The 65816 and 68000 encoders write the bytes the overlays wrote by hand before them.

The expected bytes are what ``rom.alttp_arabic._short``, ``rom.chrono_trigger_arabic._long``
and ``rom.sf2_arabic._jump``/``_call`` produced for their ``SITES``, taken from those
tuples before the overlays moved to ``cpu.m65816`` and ``cpu.m68k``; the hooks' symbol
addresses are those the overlays store.
"""

from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu import m68k, m65816
from classic_retro.rom import alttp_arabic, chrono_trigger_arabic, sf2_arabic

# A Link to the Past: JMP $EE30 + 2 NOPs, JSR $EEE7, JSR $EFAD + 7 NOPs (bank $0E).
ALTTP_SITES = {
    0x0EC4E2: "4c30eeeaea",
    0x0ECAD5: "20e7ee",
    0x0ED313: "20adefeaeaeaeaeaeaea",
}
# Chrono Trigger: JSL $DB:8000, JML $DB:803D, JML $DB:80D1.
CHRONO_TRIGGER_SITES = {
    0xC257F7: "220080db",
    0xC258B2: "5c3d80db",
    0xC25DC4: "5cd180db",
}
# Shining Force II: JMP $042600.L, JMP $042632.L + NOP, JMP $04268A.L + NOP, JSR $04278E.L.
SF2_SITES = {
    0x006272: "4ef900042600",
    0x00634E: "4ef9000426324e71",
    0x006B70: "4ef90004268a4e71",
    0x0064DA: "4eb90004278e",
}


def _patched(sites) -> dict[int, str]:
    return {site.address: site.patched.hex() for site in sites}


def test_65816_absolute_jumps_reproduce_the_link_to_the_past_sites():
    hooks = alttp_arabic.HOOKS
    assert m65816.nop_fill(m65816.jmp_abs(0x0EC4E2, hooks.symbol_address("parse_hook")), 5) == (
        bytes.fromhex(ALTTP_SITES[0x0EC4E2])
    )
    assert m65816.jsr_abs(0x0ECAD5, hooks.symbol_address("draw_hook")) == bytes.fromhex(
        ALTTP_SITES[0x0ECAD5]
    )
    assert m65816.nop_fill(m65816.jsr_abs(0x0ED313, hooks.symbol_address("tilemap_hook")), 10) == (
        bytes.fromhex(ALTTP_SITES[0x0ED313])
    )
    patched = _patched(alttp_arabic.SITES)
    assert {address: patched[address] for address in ALTTP_SITES} == ALTTP_SITES
    # The draw table's entry is a word the overlay packs itself, not a jump.
    assert patched[0x0ECA09] == "2bef"


def test_65816_long_jumps_reproduce_the_chrono_trigger_sites():
    hooks = chrono_trigger_arabic.HOOKS
    assert m65816.jsl_long(hooks.symbol_address("setup_hook")).hex() == "220080db"
    assert m65816.jml_long(hooks.symbol_address("reader_hook")).hex() == "5c3d80db"
    assert m65816.jml_long(hooks.symbol_address("glyph_hook")).hex() == "5cd180db"
    assert _patched(chrono_trigger_arabic.SITES) == CHRONO_TRIGGER_SITES


def test_68000_long_jumps_reproduce_the_shining_force_sites():
    hooks = sf2_arabic.HOOKS
    assert m68k.jmp_long(hooks.symbol_address("redirect_hook")).hex() == "4ef900042600"
    assert m68k.nop_fill(m68k.jmp_long(hooks.symbol_address("symbol_hook")), 8).hex() == (
        "4ef9000426324e71"
    )
    assert m68k.nop_fill(m68k.jmp_long(hooks.symbol_address("draw_hook")), 8).hex() == (
        "4ef90004268a4e71"
    )
    assert m68k.jsr_long(hooks.symbol_address("cursor_hook")).hex() == "4eb90004278e"
    assert _patched(sf2_arabic.SITES) == SF2_SITES


def test_65816_jumps_keep_to_their_bank_and_to_24_bits():
    assert m65816.jmp_abs(0x0EC4E2, 0x0E8000).hex() == "4c0080"
    assert m65816.jsl_long(0xFFFFFF).hex() == "22ffffff"
    assert m65816.nop_fill(b"\x4c\x00\x80", 3) == b"\x4c\x00\x80"
    for encode, arguments in (
        (m65816.jmp_abs, (0x0EC4E2, 0x0FEE30)),  # another bank
        (m65816.jsr_abs, (0x0EC4E2, 0x0FEE30)),
        (m65816.jmp_abs, (0x0EC4E2, -1)),
        (m65816.jmp_abs, (0x1000000, 0x1000000)),
        (m65816.jml_long, (0x1000000,)),
        (m65816.jsl_long, (-1,)),
        (m65816.nop_fill, (b"\x4c\x00\x80", 2)),
    ):
        with pytest.raises(ClassicRetroError) as caught:
            encode(*arguments)
        assert caught.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS, arguments


def test_68000_jumps_are_even_24_bit_and_filled_by_words():
    assert m68k.jmp_long(0).hex() == "4ef900000000"
    assert m68k.jsr_long(0xFFFFFE).hex() == "4eb900fffffe"
    assert m68k.NOP == bytes.fromhex("4e71")
    assert m68k.nop_fill(m68k.jmp_long(0x042600), 10).hex() == "4ef9000426004e714e71"
    for encode, arguments in (
        (m68k.jmp_long, (0x042601,)),  # odd
        (m68k.jsr_long, (0x1000000,)),  # past the address lines
        (m68k.jmp_long, (-2,)),
        (m68k.nop_fill, (m68k.jmp_long(0x042600), 7)),  # not whole words
        (m68k.nop_fill, (b"\x4e\x71\x4e", 4)),
        (m68k.nop_fill, (m68k.jmp_long(0x042600), 4)),  # too short
    ):
        with pytest.raises(ClassicRetroError) as caught:
            encode(*arguments)
        assert caught.value.code is ErrorCode.WRITE_OUT_OF_BOUNDS, arguments
