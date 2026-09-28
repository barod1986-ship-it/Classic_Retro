"""The documents and docstrings agree with the code they describe.

What a new target changes by hand (docs/ADDING_A_TARGET.md §5 and §6) is held
to the registry here, so that it fails when a target is added without it
rather than going stale: the number of reference targets the localization
docstrings name, the README's target table, and the documents every target
points to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from classic_retro import localization
from classic_retro.localization import builtin, strategies
from classic_retro.localization.targets import build_target_registry

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
# The README's table of targets starts with this header; a row is "| `id` | ...".
TARGET_TABLE_HEADER = "| Target | Game | Kind | Rendering strategy |"
TABLE_ROW = re.compile(r"^\| `([a-z0-9-]+)` \|")

_UNITS = {
    word: number
    for number, word in enumerate(
        "one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        start=1,
    )
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
# The word before "targets" or "reference targets": "twenty-one reference targets",
# "of the twenty-one targets", across a docstring's line breaks. Words that name no
# number ("the targets") are skipped.
_BEFORE_TARGETS = re.compile(r"\b([A-Za-z]+(?:-[A-Za-z]+)?)\s+(?:reference\s+)?targets\b")


def _number(word: str) -> int | None:
    """The integer a number word names (``twenty-one``), or None for another word."""
    tens, hyphen, units = word.lower().partition("-")
    if not hyphen:
        return _UNITS.get(tens, _TENS.get(tens))
    if tens in _TENS and units in _UNITS:
        return _TENS[tens] + _UNITS[units]
    return None


def _counts_named(text: str) -> list[int]:
    numbers = (_number(word) for word in _BEFORE_TARGETS.findall(text))
    return [number for number in numbers if number is not None]


def _registered_ids() -> list[str]:
    return [target.id for target in build_target_registry(load_external=False)]


def test_number_words_are_read_as_written():
    assert _counts_named("the sixteen reference targets") == [16]
    assert _counts_named("Fourteen of the seventeen targets turn") == [17]
    assert _counts_named("The twenty-one reference targets proved four") == [21]
    assert _counts_named("the twenty-one\nreference targets") == [21]
    assert _counts_named("all the targets, and these targets") == []


@pytest.mark.parametrize(
    "module", [localization, builtin, strategies], ids=lambda module: module.__name__
)
def test_the_docstrings_count_the_registered_targets(module):
    registered = len(_registered_ids())
    counts = _counts_named(module.__doc__ or "")
    assert counts, f"{module.__name__} names no number of targets"
    assert counts == [registered] * len(counts), module.__name__


def test_the_readme_table_has_a_row_per_registered_target():
    lines = README.read_text(encoding="utf-8").splitlines()
    start = lines.index(TARGET_TABLE_HEADER)
    rows = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        match = TABLE_ROW.match(line)
        if match:
            rows.append(match.group(1))
    assert rows == _registered_ids()


def test_every_document_a_target_names_exists():
    for target in build_target_registry(load_external=False):
        for document in (target.guide, target.notes):
            assert document.startswith("docs/"), f"{target.id}: {document}"
            assert (REPO / document).is_file(), f"{target.id}: {document}"
