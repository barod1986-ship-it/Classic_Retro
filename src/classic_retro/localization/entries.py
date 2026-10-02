"""Every entry a target's check refuses, and why, in one run: ``targets check-entries``.

``check-translations`` stops at a script's first error, and most targets' errors
say what is wrong ("Line 2 needs 230px") without naming the entry. A translator
who changed a hundred entries needs them all at once. This module finds them
with no code of the target's own: against a *baseline* that passes (the shipped
translations, or ``--baseline``), it runs the target's ``check_translations``
with the translator's text in some entries and the baseline's in the rest, and
halves the entries that fail until each failure has its entry. Every message in
the report is the target's own, from a run where only that entry was changed.

The checked file may hold only some of the target's entries, a *batch*: every
entry it lacks takes the baseline's text, so batches are checked one at a time
by different translators. An entry that is refused only together with others
(two briefings that each fit a glyph budget but overflow it together) is reported
as a group, never blamed on one of them. An entry that is refused against the
baseline but passes with the translator's other changes (a message re-fitted to
a shortened name) is a warning.

The run is checked first without the font (parse, commands, glyphs, line counts),
which is fast, then with it (pixel widths) for the entries that passed. Next to
the errors the report lists warnings read from the notation alone, the same for
every target: Latin letters, marks and presentation forms, unbalanced brackets,
empty text and, in a workspace, untranslated text, commands or numbers of the
original that the Arabic drops or adds, and glossary terms not used.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from pathlib import Path

from classic_retro.arabic.logical import DIRECTION_CONTROLS, is_arabic_letter, is_presentation_form
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document
from classic_retro.localization.targets import TranslationCheck
from classic_retro.localization.translations import (
    SCHEMA,
    GlossaryTerm,
    TranslationSet,
    glossary_report,
)

# A notation command: {braces}, [brackets] (Fire Emblem) or a backslash escape (\p).
TOKEN = re.compile(r"\{[^{}\n]*\}|\[[^\[\]\n]*\]|\\[A-Za-z]")
_LATIN = re.compile(r"[A-Za-z]+")
_DIGITS = re.compile(r"[0-9]+")
# Arabic-Indic and Eastern Arabic-Indic digits, read as the digits they write.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Fathatan to sukun, the further marks, and the superscript alef.
_ARABIC_MARKS = frozenset(chr(code) for code in (*range(0x064B, 0x0660), 0x0670))
# Fewer entries than this are tried one at a time instead of halved.
_ONE_BY_ONE = 4


@dataclass(frozen=True, slots=True)
class Batch:
    """A checked file read leniently, over its baseline.

    ``translations`` is the baseline with the file's text in its entries: the
    complete set a target's check takes. ``ids`` are the file's entries the run
    looks at, in the baseline's order. ``problems`` are the file's own errors by
    entry (an unknown or duplicate id, direction controls), whose entries keep
    the baseline's text in the search.
    """

    translations: TranslationSet
    baseline: TranslationSet
    ids: tuple[str, ...]
    sources: dict[str, str]
    problems: tuple[dict[str, object], ...]
    glossary: tuple[GlossaryTerm, ...]


def load_batch(
    path: Path, target_id: str, baseline: TranslationSet, only: Sequence[str] = ()
) -> Batch:
    """The file at ``path`` over ``baseline``; ``only`` narrows it to matching ids.

    A file that is not JSON, breaks the schema or holds another target's
    translations is refused outright. Anything wrong with one entry is a problem
    of that entry, and the rest is still checked.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT, f"Could not read translations {path}: {exc}"
        ) from exc
    validate_document(SCHEMA, data)
    if data["target"] != target_id:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"{path} holds translations of {data['target']}, not {target_id}",
        )
    known = {entry.id: entry for entry in baseline.entries}
    texts: dict[str, str] = {}
    sources = {entry.id: entry.source for entry in baseline.entries if entry.source is not None}
    problems: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in data["entries"]:
        entry_id = item["id"]
        if only and not any(fnmatchcase(entry_id, pattern) for pattern in only):
            continue
        if entry_id not in known:
            problems.append(
                _problem(
                    entry_id,
                    ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                    f"{target_id} has no entry {entry_id}",
                )
            )
            continue
        if entry_id in seen:
            problems.append(
                _problem(
                    entry_id,
                    ErrorCode.DUPLICATE_ENTRY_ID,
                    f"{entry_id} is in the file more than once; the first one is checked",
                )
            )
            continue
        seen.add(entry_id)
        controls = _direction_controls(item["text"])
        if controls:
            problems.append(
                _problem(
                    entry_id,
                    ErrorCode.EXPLICIT_BIDI_CONTROL,
                    f"{entry_id} text holds direction controls ({controls}); write logical text",
                )
            )
        else:
            texts[entry_id] = item["text"]
        source = item.get("source")
        if source is not None and not _direction_controls(source):
            sources[entry_id] = source
    entries = tuple(
        replace(entry, text=texts[entry.id]) if entry.id in texts else entry
        for entry in baseline.entries
    )
    glossary = tuple(
        GlossaryTerm(term=term["term"], text=term["text"], notes=term.get("notes"))
        for term in data.get("glossary", ())
    )
    return Batch(
        translations=replace(baseline, entries=entries),
        baseline=baseline,
        ids=tuple(entry.id for entry in baseline.entries if entry.id in seen),
        sources=sources,
        problems=tuple(problems),
        glossary=glossary or baseline.glossary,
    )


def _problem(entry_id: str, code: ErrorCode, message: str) -> dict[str, object]:
    return {"id": entry_id, "code": code.value, "message": message}


def _direction_controls(text: str) -> str:
    return ", ".join(f"U+{ord(c):04X}" for c in sorted(set(text) & DIRECTION_CONTROLS))


# The search.


class _Stopped(Exception):
    """The run limit was reached."""


@dataclass(slots=True)
class _Search:
    """Runs of a target's check, each with the translator's text in some entries."""

    check: TranslationCheck
    baseline: TranslationSet
    texts: dict[str, str]
    max_runs: int
    runs: int = 0
    errors: dict[str, dict[str, object]] = field(default_factory=dict)
    groups: list[dict[str, object]] = field(default_factory=list)

    def run(self, ids: Iterable[str], font: Path | None) -> tuple[str, str] | None:
        """The check's error with ``ids`` changed, or None when it passes."""
        if self.runs >= self.max_runs:
            raise _Stopped
        changed = set(ids)
        entries = tuple(
            replace(entry, text=self.texts[entry.id]) if entry.id in changed else entry
            for entry in self.baseline.entries
        )
        self.runs += 1
        try:
            self.check(font, None, replace(self.baseline, entries=entries))
        except ClassicRetroError as exc:
            return exc.code.value, str(exc)
        except Exception as exc:  # a crash on a translator's text is that entry's failure
            return "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"
        return None

    def placed(self) -> set[str]:
        return set(self.errors) | {i for group in self.groups for i in group["ids"]}

    def find(self, ids: list[str], font: Path | None) -> tuple[str, str] | None:
        """Place every failing entry of ``ids``; the baseline's error if it fails alone."""
        error = self.run(ids, font)
        if error is None:
            return None
        baseline_error = self.run((), font)
        if baseline_error is not None:
            return baseline_error
        pending = ids
        while error is not None and pending:
            self._split(pending, error, font)
            placed = self.placed()
            pending = [entry_id for entry_id in pending if entry_id not in placed]
            error = self.run(pending, font) if pending else None
        return None

    def _split(self, ids: list[str], error: tuple[str, str], font: Path | None) -> None:
        if len(ids) == 1:
            self.errors[ids[0]] = {
                "id": ids[0],
                "code": error[0],
                "message": error[1],
                "font": font is not None,
            }
            return
        if len(ids) <= _ONE_BY_ONE:
            parts = [[entry_id] for entry_id in ids]
        else:
            half = len(ids) // 2
            parts = [ids[:half], ids[half:]]
        found = False
        for part in parts:
            part_error = self.run(part, font)
            if part_error is not None:
                found = True
                self._split(part, part_error, font)
        if not found:
            group, error = self._smallest(ids, error, font)
            self.groups.append(
                {
                    "ids": group,
                    "code": error[0],
                    "message": error[1],
                    "font": font is not None,
                    "note": "each passes alone; together they are refused",
                }
            )

    def _smallest(
        self, ids: list[str], error: tuple[str, str], font: Path | None
    ) -> tuple[list[str], tuple[str, str]]:
        """A subset of ``ids`` still refused that is refused no more without any one of them."""
        group = list(ids)
        for entry_id in ids:
            trial = [other for other in group if other != entry_id]
            trial_error = self.run(trial, font)
            if trial_error is not None:
                group, error = trial, trial_error
        return group, error


@dataclass(frozen=True, slots=True)
class Located:
    errors: tuple[dict[str, object], ...]
    groups: tuple[dict[str, object], ...]
    # Entries refused against the baseline that pass with the other changes.
    together: tuple[str, ...]
    baseline_error: dict[str, object] | None
    stopped: bool
    runs: int


def locate_failures(
    check: TranslationCheck,
    baseline: TranslationSet,
    texts: dict[str, str],
    changed: Sequence[str],
    font: Path | None,
    *,
    max_runs: int,
) -> Located:
    """Every entry of ``changed`` whose text ``check`` refuses, by group testing.

    ``texts`` holds the translator's text by id. The check runs without the
    font first, then with it for the entries that passed.
    """
    search = _Search(check, baseline, texts, max_runs)
    baseline_error = None
    stopped = False
    together: list[str] = []
    try:
        for phase_font in (None, font) if font is not None else (None,):
            pending = [entry_id for entry_id in changed if entry_id not in search.placed()]
            error = search.find(pending, phase_font) if pending else None
            if error is not None:
                baseline_error = {
                    "code": error[0],
                    "message": error[1],
                    "font": phase_font is not None,
                }
                break
        if baseline_error is None:
            # The rest passes now. An entry that passes with it is refused only
            # against the baseline's text of an entry it depends on.
            rest = [entry_id for entry_id in changed if entry_id not in search.placed()]
            for entry_id, error in list(search.errors.items()):
                if search.run([*rest, entry_id], font if error["font"] else None) is None:
                    together.append(entry_id)
                    del search.errors[entry_id]
    except _Stopped:
        stopped = True
    order = {entry.id: index for index, entry in enumerate(baseline.entries)}
    return Located(
        errors=tuple(sorted(search.errors.values(), key=lambda error: order[str(error["id"])])),
        groups=tuple(search.groups),
        together=tuple(sorted(together, key=order.__getitem__)),
        baseline_error=baseline_error,
        stopped=stopped,
        runs=search.runs,
    )


# Warnings from the notation alone.


def notation_warnings(
    entry_id: str, text: str, source: str | None, tolerated: frozenset[str] = frozenset()
) -> list[dict[str, object]]:
    """What the text's notation suggests is wrong, for any target.

    ``source`` is the original, in a workspace. ``tolerated`` are the commands
    the target's accepted translations add or drop against their originals
    (line ends a target lays out itself), which are no warning.
    """
    warnings: list[dict[str, object]] = []

    def warn(kind: str, detail: str) -> None:
        warnings.append({"id": entry_id, "kind": kind, "detail": detail})

    plain = TOKEN.sub(" ", text)
    latin = _LATIN.findall(plain)
    if latin:
        warn("latin_letters", "Latin letters outside the commands: " + ", ".join(latin))
    marks = sorted({c for c in plain if c in _ARABIC_MARKS})
    if marks:
        warn("vowel_marks", "vowel marks: " + ", ".join(f"U+{ord(c):04X}" for c in marks))
    forms = sorted({c for c in plain if is_presentation_form(c)})
    if forms:
        warn(
            "presentation_forms",
            "presentation forms, not letters: " + ", ".join(f"U+{ord(c):04X}" for c in forms),
        )
    for opening, closing in ("{}", "[]"):
        if text.count(opening) != text.count(closing):
            warn(
                "unbalanced_brackets",
                f"{text.count(opening)} '{opening}' against {text.count(closing)} '{closing}'",
            )
    if not text.strip():
        warn("empty", "no text")
    if source is None:
        return warnings
    source_latin = [run for run in _LATIN.findall(TOKEN.sub(" ", source)) if len(run) > 1]
    if text == source and source_latin:
        warn("untranslated", "the text is the original's")
    elif source_latin and not any(is_arabic_letter(c) for c in plain):
        warn("no_arabic", "no Arabic letter, but the original has words")
    dropped, added = _token_difference(source, text, tolerated)
    if dropped or added:
        parts = []
        if dropped:
            parts.append("dropped " + " ".join(dropped))
        if added:
            parts.append("added " + " ".join(added))
        warn("commands_differ", "; ".join(parts))
    missing = Counter(_DIGITS.findall(TOKEN.sub(" ", source))) - Counter(
        _DIGITS.findall(plain.translate(_ARABIC_DIGITS))
    )
    if missing:
        warn("numbers_missing", "the original's " + ", ".join(sorted(missing.elements())))
    return warnings


def _token_difference(
    source: str, text: str, tolerated: frozenset[str]
) -> tuple[list[str], list[str]]:
    before = Counter(token for token in TOKEN.findall(source) if token not in tolerated)
    after = Counter(token for token in TOKEN.findall(text) if token not in tolerated)
    return sorted((before - after).elements()), sorted((after - before).elements())


def tolerated_tokens(pairs: Iterable[tuple[str, str]]) -> frozenset[str]:
    """The commands accepted translations add or drop against their originals.

    ``pairs`` are (original, accepted Arabic): a command that differs in any of
    them is one the target lets the translator move (a line end it lays out).
    """
    tolerated: set[str] = set()
    for source, text in pairs:
        dropped, added = _token_difference(source, text, frozenset())
        tolerated.update(dropped)
        tolerated.update(added)
    return frozenset(tolerated)


# The report.


def entry_report(
    check: TranslationCheck,
    batch: Batch,
    font: Path | None,
    *,
    max_runs: int,
) -> dict[str, object]:
    """``targets check-entries``: the errors and warnings of ``batch``'s entries."""
    started = time.perf_counter()
    texts = {entry.id: entry.text for entry in batch.translations.entries}
    base = {entry.id: entry.text for entry in batch.baseline.entries}
    problem_ids = {str(problem["id"]) for problem in batch.problems}
    changed = [
        entry_id
        for entry_id in batch.ids
        if texts[entry_id] != base[entry_id] and entry_id not in problem_ids
    ]
    located = locate_failures(check, batch.baseline, texts, changed, font, max_runs=max_runs)

    # The baseline's text of an entry is an accepted translation of its original.
    tolerated = tolerated_tokens(
        (batch.sources[entry.id], entry.text)
        for entry in batch.baseline.entries
        if entry.id in batch.sources
    )
    warnings: list[dict[str, object]] = []
    for entry_id in batch.ids:
        if entry_id in problem_ids:
            continue
        warnings.extend(
            notation_warnings(entry_id, texts[entry_id], batch.sources.get(entry_id), tolerated)
        )
    for entry_id in located.together:
        warnings.append(
            {
                "id": entry_id,
                "kind": "passes_with_your_other_changes",
                "detail": "refused with the baseline's text in the other entries",
            }
        )
    scoped = replace(
        batch.translations,
        entries=tuple(
            replace(entry, source=batch.sources.get(entry.id))
            for entry in batch.translations.entries
            if entry.id in batch.ids
        ),
        glossary=batch.glossary,
    )
    for missing in glossary_report(scoped):
        warnings.append(
            {
                "id": missing["id"],
                "kind": "glossary",
                "detail": f"{missing['term']} is written {missing['expected']}",
            }
        )
    order = {entry.id: index for index, entry in enumerate(batch.baseline.entries)}
    warnings.sort(key=lambda warning: order[str(warning["id"])])

    errors = [*batch.problems, *located.errors]
    errors.sort(key=lambda error: order.get(str(error["id"]), -1))
    groups = list(located.groups)
    if located.stopped:
        placed = {str(error["id"]) for error in errors} | {
            entry_id for group in groups for entry_id in group["ids"]
        }
        groups.append(
            {
                "ids": [entry_id for entry_id in changed if entry_id not in placed],
                "code": "SEARCH_STOPPED",
                "message": f"stopped after {max_runs} runs (--max-runs) before these were placed",
                "font": font is not None,
                "note": "not checked one by one",
            }
        )
    report: dict[str, object] = {
        "entries": len(batch.ids),
        "from_baseline": len(batch.baseline.entries) - len(batch.ids),
        "changed": len(changed),
        "ok": not errors and not groups and located.baseline_error is None,
        "errors": errors,
        "group_errors": groups,
        "warnings": warnings,
        "runs": located.runs,
        "seconds": round(time.perf_counter() - started, 2),
        "checked_with_font": font is not None,
    }
    if located.baseline_error is not None:
        report["baseline_error"] = located.baseline_error
    return report
