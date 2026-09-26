"""Game-engine adapters and the text engines they describe.

Each engine module holds what the toolkit knows of a text engine: its encoding
and commands and, where a target needs them, its font and text box rules. Its
``*_arabic`` module turns logical Arabic into what that engine draws. The
targets in ``classic_retro.localization.builtin`` use them.
"""
