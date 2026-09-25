"""Which game codes draw which characters.

A glyph-font target gives every character it adds (the Arabic presentation
forms, and sometimes a space, punctuation or copies of the game's Latin glyphs)
codes from a range the game leaves free. A form wider than one glyph can take
two codes, painted one after the other. Codes are given in order, so a font
and the text encoded for it always agree.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from classic_retro.core.errors import ClassicRetroError, ErrorCode


@dataclass(frozen=True, slots=True)
class GlyphCodes:
    """Characters in the order they took their codes, and each one's codes."""

    characters: tuple[str, ...]
    sequences: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequences", MappingProxyType(dict(self.sequences)))

    def code(self, character: str) -> int | None:
        """The character's (first) code, or None when the game has none for it."""
        sequence = self.sequences.get(character)
        return None if sequence is None else sequence[0]

    def sequence(self, character: str) -> tuple[int, ...] | None:
        return self.sequences.get(character)

    def all_codes(self) -> tuple[int, ...]:
        return tuple(sorted(code for sequence in self.sequences.values() for code in sequence))


def assign_glyph_codes(
    characters: Iterable[str],
    codes: Iterable[int],
    *,
    what: str,
    doubled: Collection[str] = frozenset(),
) -> GlyphCodes:
    """Give ``characters`` the next ``codes`` in order; each of ``doubled`` takes two."""
    ordered = tuple(characters)
    if len(set(ordered)) != len(ordered):
        raise ValueError("characters must be distinct")
    available = tuple(codes)
    needed = len(ordered) + sum(1 for character in ordered if character in doubled)
    if needed > len(available):
        raise ClassicRetroError(
            ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
            f"{what} need {needed} codes; the game has {len(available)} free",
        )
    free = iter(available)
    sequences = {
        character: tuple(next(free) for _ in range(2 if character in doubled else 1))
        for character in ordered
    }
    return GlyphCodes(ordered, sequences)
