"""Batches of a translations file: ``targets split`` and ``targets merge``.

A large script is translated in batches, by several translators at once or one
batch at a time: ``split`` cuts a translations file or workspace into files of a
few entries each, every one a valid file of the same target, and ``merge`` puts
their text back into the whole. A batch is checked on its own with
``targets check-entries``, which takes every entry it lacks from the baseline.

A batch of a workspace is a workspace too: it holds the originals of its entries,
so it stays on the user's machine like the workspace. Its glossary is the terms
its originals name, so a translator sees the writings that batch needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from fnmatch import fnmatchcase

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.translations import TranslationSet, names_term


def split_translations(
    translations: TranslationSet, size: int, only: Sequence[str] = ()
) -> list[TranslationSet]:
    """``translations`` in batches of ``size`` entries, in its order.

    ``only`` keeps the entries whose id matches one of these shell patterns.
    """
    if size < 1:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "A batch holds at least one entry")
    entries = [
        entry
        for entry in translations.entries
        if not only or any(fnmatchcase(entry.id, pattern) for pattern in only)
    ]
    if not entries:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            f"No entry of {translations.target} matches {' '.join(only)}",
        )
    batches = []
    for start in range(0, len(entries), size):
        chunk = tuple(entries[start : start + size])
        glossary = translations.glossary
        if translations.is_workspace:
            glossary = tuple(
                term
                for term in translations.glossary
                if any(entry.source and names_term(entry.source, term.term) for entry in chunk)
            )
        batches.append(replace(translations, entries=chunk, glossary=glossary))
    return batches


def merge_translations(
    translations: TranslationSet, batches: Sequence[TranslationSet]
) -> tuple[TranslationSet, dict[str, object]]:
    """``translations`` with the text and notes of every batch's entries.

    The batches' entries must be entries of ``translations``, each in one batch.
    A batch's glossary adds the terms ``translations`` lacks; a term written
    otherwise than in ``translations`` is refused, so a name keeps one writing.
    """
    known = {entry.id for entry in translations.entries}
    terms = {term.term: term for term in translations.glossary}
    merged: dict[str, tuple[str, str | None]] = {}
    unknown: list[str] = []
    twice: list[str] = []
    conflicts: list[str] = []
    added = []
    for batch in batches:
        if batch.target != translations.target:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"A batch holds translations of {batch.target}, not {translations.target}",
            )
        for entry in batch.entries:
            if entry.id not in known:
                unknown.append(entry.id)
            elif entry.id in merged:
                twice.append(entry.id)
            else:
                merged[entry.id] = (entry.text, entry.notes)
        for term in batch.glossary:
            if term.term not in terms:
                terms[term.term] = term
                added.append(term.term)
            elif terms[term.term].text != term.text:
                conflicts.append(f"{term.term} ({terms[term.term].text} / {term.text})")
    problems = []
    if unknown:
        problems.append(f"{translations.target} has no entry " + ", ".join(unknown))
    if twice:
        problems.append("in more than one batch: " + ", ".join(twice))
    if conflicts:
        problems.append("glossary terms written two ways: " + ", ".join(conflicts))
    if problems:
        raise ClassicRetroError(ErrorCode.INVALID_TRANSLATION_DOCUMENT, "; ".join(problems))
    changed = []
    entries = []
    for entry in translations.entries:
        if entry.id in merged:
            text, notes = merged[entry.id]
            new = replace(entry, text=text, notes=notes)
            if new != entry:
                changed.append(entry.id)
            entries.append(new)
        else:
            entries.append(entry)
    result = replace(translations, entries=tuple(entries), glossary=tuple(terms.values()))
    return result, {"merged": len(merged), "changed": changed, "glossary_added": added}
