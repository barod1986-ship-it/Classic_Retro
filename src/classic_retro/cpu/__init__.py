"""Instruction encoders for the CPUs whose code the toolkit patches.

Each module covers one instruction set and only what patching needs: the
calls, branches and far jumps written over a game's code to reach a hook.
Five exist: ``thumb`` (the ARM7TDMI's Thumb code, and the ARM946E-S's),
``arm`` (the ARM946E-S's ARM code), ``mips`` (the R3000A's MIPS I),
``m65816`` (the 65C816's absolute and long jumps and calls) and ``m68k``
(the 68000's ``JMP`` and ``JSR`` with a long address, and ``NOP``). A new CPU
(6502, SM83...) gets a module of its own next to them.
"""
