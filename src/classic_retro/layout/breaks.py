from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from uniseg.linebreak import line_break_boundaries


class BreakProvider(Protocol):
    unicode_version: str

    def boundaries(self, text: str) -> Iterable[int]:
        """Return legal soft line-break boundaries in code-point indices."""


class UnisegBreakProvider:
    unicode_version = "16.0.0"

    def boundaries(self, text: str) -> Iterable[int]:
        return line_break_boundaries(text)
