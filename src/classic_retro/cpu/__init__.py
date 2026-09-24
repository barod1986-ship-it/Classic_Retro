"""Instruction encoders for the CPUs whose code the toolkit patches.

Each module covers one instruction set and only what patching needs: the
calls, branches and far jumps written over a game's code to reach a hook.
New CPUs (65816, 6502, SM83, 68000, MIPS...) get a module of their own.
"""
