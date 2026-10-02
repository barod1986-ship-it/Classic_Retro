"""Every entry a target's check refuses, and why, in one run: ``targets check-entries``.

``check-translations`` stops at a script's first error, and most targets' errors
say what is wrong ("Line 2 needs 230px") without naming the entry. A translator
who changed a hundred entries needs them all at once. This module finds them
with no code of the target's own: against a *baseline* that passes (the shipped
translations, or ``--baseline``), it runs the target's ``check_translations``
with the translator's text in some entries and the baseline's in the rest. It
gathers the changes that pass together, halving the ones refused, and judges
every other change with them, so an entry is reported only if it is refused
with the translator's other changes in place. Every message is the target's own.

The checked file may hold only some of the target's entries, a *batch*: every
entry it lacks takes the baseline's text, so batches are checked one at a time
by different translators. An entry that passes alone but is refused together
with some of the other changes (two briefings that each fit a glyph budget but
overflow it together) is reported with them, none of which can be left out.

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
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
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
# A thousands separator between digits (1,000 or ١٬٠٠٠): one number, not two.
_GROUP_SEPARATOR = re.compile(r"(?<=\d)[,٬](?=\d{3}(?!\d))")
# Arabic-Indic and Eastern Arabic-Indic digits, read as the digits they write.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Fathatan to sukun, the further marks, and the superscript alef.
_ARABIC_MARKS = frozenset(chr(code) for code in (*range(0x064B, 0x0660), 0x0670))


@dataclass(frozen=True, slots=True)
class Batch:
    """A checked file read leniently, over its baseline.

    ``translations`` is the baseline with the file's text in its entries: the
    complete set a target's check takes. ``ids`` are the file's entries the run
    looks at, in the baseline's order. ``problems`` are the file's own errors by
    entry: an unknown id, an id again (its first text is checked), and direction
    controls, whose entry keeps the baseline's text in the search.
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
    translations is refused outright, and so are patterns ``only`` that match no
    entry of it. Anything wrong with one entry is a problem of that entry, and
    the rest is still checked.
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
    matched = 0
    for item in data["entries"]:
        entry_id = item["id"]
        if only and not any(fnmatchcase(entry_id, pattern) for pattern in only):
            continue
        matched += 1
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
    if only and not matched:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"No entry of {path} matches {' '.join(only)}"
        )
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

    def grow(
        self, accepted: list[str], ids: Sequence[str], font: Path | None
    ) -> dict[str, tuple[str, str]]:
        """Add to ``accepted`` every entry of ``ids`` that passes with it; the others' errors.

        A part of ``ids`` that passes with the accepted entries joins them, and a
        part refused is halved. An entry refused before more were accepted is
        tried again, as it may have been refused only against the baseline's
        text of one of them (a message re-fitted to a renamed name), so every
        error returned is from a run with the final accepted entries.
        """
        pending = list(ids)
        while True:
            refused: dict[str, tuple[str, str]] = {}
            size = len(accepted)
            self._add(accepted, pending, font, refused)
            if not refused or len(accepted) == size:
                return refused
            pending = list(refused)

    def _add(
        self,
        accepted: list[str],
        part: list[str],
        font: Path | None,
        refused: dict[str, tuple[str, str]],
    ) -> None:
        error = self.run([*accepted, *part], font)
        if error is None:
            accepted.extend(part)
        elif len(part) == 1:
            refused[part[0]] = error
        else:
            half = len(part) // 2
            self._add(accepted, part[:half], font, refused)
            self._add(accepted, part[half:], font, refused)

    def partners(self, fixed: list[str], pool: list[str], font: Path | None) -> list[str]:
        """Entries of ``pool`` that ``fixed`` is refused with, none of them needless.

        ``fixed`` with all of ``pool`` is refused; with none it is refused alone,
        and the answer is empty. The pool is halved: the part found in one half
        is kept while the other half is searched (QuickXplain), so a few runs
        find two partners among thousands. The set is minimal (no entry of it
        can be left out), not always the smallest there is.
        """
        if not pool or self.run(fixed, font) is not None:
            return []
        if len(pool) == 1:
            return list(pool)
        half = len(pool) // 2
        found = self.partners([*fixed, *pool[half:]], pool[:half], font)
        return found + self.partners([*fixed, *found], pool[half:], font)


@dataclass(frozen=True, slots=True)
class Located:
    errors: tuple[dict[str, object], ...]
    # Entries refused only together with others of the changes ("with").
    groups: tuple[dict[str, object], ...]
    baseline_error: dict[str, object] | None
    # Changed entries the run limit left undecided.
    undecided: tuple[str, ...]
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

    ``texts`` holds the translator's text by id. The search keeps the changes
    that pass together and judges every other one with them: an entry refused
    even with no other change is an error; one refused only with some of the
    passing changes is reported with them, none of which can be left out. It checks without the
    font first, then with it the changes that passed. An error's ``font`` says
    the entry is refused only when laid out with the font.
    """
    order = {entry.id: index for index, entry in enumerate(baseline.entries)}
    search = _Search(check, baseline, texts, max_runs)
    errors: dict[str, dict[str, object]] = {}
    groups: list[dict[str, object]] = []
    baseline_error = None
    candidates = list(changed)
    cleared: list[str] = []
    try:
        for phase in (None,) if font is None else (None, font):
            if not candidates and phase is None:
                continue
            if search.run(candidates, phase) is None:
                continue
            error = search.run((), phase)
            if error is not None:
                baseline_error = {
                    "code": error[0],
                    "message": error[1],
                    "font": phase is not None and search.run((), None) is None,
                }
                candidates = []
                break
            accepted: list[str] = []
            refused = search.grow(accepted, candidates, phase)
            for entry_id, error in refused.items():
                partners = search.partners([entry_id], accepted, phase)
                only_font = phase is not None and search.run([*accepted, entry_id], None) is None
                found = {"id": entry_id, "code": error[0], "message": error[1], "font": only_font}
                if partners:
                    groups.append({**found, "with": sorted(partners, key=order.__getitem__)})
                else:
                    errors[entry_id] = found
            candidates = accepted
        cleared = candidates
    except _Stopped:
        pass
    placed = {*errors, *(str(group["id"]) for group in groups), *cleared}
    if baseline_error is not None:
        placed.update(changed)
    return Located(
        errors=tuple(sorted(errors.values(), key=lambda error: order[str(error["id"])])),
        groups=tuple(sorted(groups, key=lambda group: order[str(group["id"])])),
        baseline_error=baseline_error,
        undecided=tuple(entry_id for entry_id in changed if entry_id not in placed),
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
    missing = Counter(_numbers(TOKEN.sub(" ", source))) - Counter(
        _numbers(plain.translate(_ARABIC_DIGITS))
    )
    if missing:
        warn("numbers_missing", "the original's " + ", ".join(sorted(missing.elements())))
    return warnings


def _numbers(text: str) -> list[str]:
    return _DIGITS.findall(_GROUP_SEPARATOR.sub("", text))


def _commands(text: str, tolerated: frozenset[str]) -> Iterator[str]:
    """The commands of ``text`` one by one: a brace may hold several ({PAUSE 154 PAGE}).

    A brace that starts with "+" is one the notation lets the translation add
    (FF6 Advance's page splits), never the original's.
    """
    for token in TOKEN.findall(text):
        if token.startswith("{+"):
            continue
        words = [f"{{{word}}}" for word in token[1:-1].split()] if token[0] == "{" else [token]
        yield from (word for word in words if word not in tolerated)


def _token_difference(
    source: str, text: str, tolerated: frozenset[str]
) -> tuple[list[str], list[str]]:
    before = Counter(_commands(source, tolerated))
    after = Counter(_commands(text, tolerated))
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
    # An id given twice is checked with its first text.
    problem_ids = {
        str(problem["id"])
        for problem in batch.problems
        if problem["code"] != ErrorCode.DUPLICATE_ENTRY_ID.value
    }
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
    report: dict[str, object] = {
        "entries": len(batch.ids),
        "from_baseline": len(batch.baseline.entries) - len(batch.ids),
        "changed": len(changed),
        "ok": not errors
        and not located.groups
        and located.baseline_error is None
        and not located.undecided,
        "errors": errors,
        "group_errors": list(located.groups),
        "warnings": warnings,
        "runs": located.runs,
        "seconds": round(time.perf_counter() - started, 2),
        "checked_with_font": font is not None,
    }
    if located.baseline_error is not None:
        report["baseline_error"] = located.baseline_error
    if located.undecided:
        # The run limit (--max-runs) came first: these are neither passed nor refused.
        report["undecided"] = list(located.undecided)
    return report
