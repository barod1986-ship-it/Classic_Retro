"""Arabic translation of three license test briefings of *Gran Turismo* (USA) (Rev 1).

Before a license test the game shows its briefing: a title, what to do, the
car and the time limit. The translation takes three of license B's eight, of
different lengths and shapes: B-1 (starting and stopping, a number with a
thousands comma), B-3 (a first corner: the longest body, with an Arabic comma)
and B-8 (the license's final test, a lap: the widest title, and a number
joined to a letter). The other 21 briefings stay in English, as the game draws them.

Each original is pinned by its place among the 24 texts of MESSAGES.DAT's
license file and the SHA-256 of its bytes (its padding included), so the
translation can be checked without the disc and the build refuses another
text.

The Arabic lives in ``classic_retro/translations/gran-turismo.json``: logical
Unicode Arabic in the engine's notation (``engines.gran_turismo``), the title
on the first line and a line for each paragraph. A paragraph's words are laid
out by the game; a line holds 288 pixels and the box seven lines under the
title (``engines.gran_turismo_arabic``).
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.gran_turismo import LICENSE_TESTS, parse_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class GranTurismoBriefing:
    """A translated briefing: its entry, its test's place and the original's SHA-256."""

    key: str
    index: int
    source_sha256: str
    notation: str

    @property
    def test(self) -> str:
        return LICENSE_TESTS[self.index]

    @property
    def title(self) -> str:
        return parse_notation(self.notation)[0]

    @property
    def paragraphs(self) -> tuple[tuple[str, ...], ...]:
        return parse_notation(self.notation)[1]


# key: (the briefing's place among the 24, SHA-256 of the original with its padding)
# fmt: off
_SOURCES: dict[str, tuple[int, str]] = {
    "license.b1": (0, "c6c93486af1d531b13642f09e0ce2cd92373343a0335e661e113f0a77946f4c1"),
    "license.b3": (2, "6a4a70804838a39af0c181e30c0d31f0aad953c09954485a60089397a4a267f3"),
    "license.b8": (7, "7ea328f235ae6d0ac611959cd86d9d02f84303bf4451a6a40b48ac2ac80cc0eb"),
}
# fmt: on

TARGET = "gran-turismo"


def gran_turismo_arabic_briefings(
    translations: TranslationSet | None = None,
) -> tuple[GranTurismoBriefing, ...]:
    """Every translated briefing, in the order of the tests."""
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))
    return tuple(
        GranTurismoBriefing(key=key, index=index, source_sha256=digest, notation=texts[key])
        for key, (index, digest) in _SOURCES.items()
    )
