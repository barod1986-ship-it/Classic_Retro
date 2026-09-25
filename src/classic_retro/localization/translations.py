"""A target's Arabic text as data: one file per target, entries by stable id.

Every target keeps its translations in ``classic_retro/translations/<target>.json``
(schema ``target-translations.schema.json``), so a translator edits text, never
code. A file holds only the Arabic: each entry has a stable id (never an
address), its text in the target's notation, and optional context and notes. The
file's ``notation`` field explains the commands; its ``glossary`` fixes how names
and terms are written. Where each original is and what it must match (addresses,
SHA-256 pins, command skeletons) stays in the target's code.

``classic-retro targets extract`` writes a *workspace*: the same file with each
original's text (``source``) decoded from the user's own copy of the game, so the
translator sees what every entry translates. A workspace holds the game's text,
so it stays on the user's machine and is never committed. The check and build
commands take either file with ``--translations``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.schema import validate_document

SCHEMA = "target-translations.schema.json"
SCHEMA_VERSION = "1.0"
WORKSPACE_NOTICE = (
    "Local only: this workspace holds text from your own copy of the game. "
    "Do not commit or share it."
)
# Invisible direction controls: embeddings, overrides, isolates and marks. The
# notation is logical text; direction is the toolkit's job.
_DIRECTION_CONTROLS = frozenset(
    chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C)
)


@dataclass(frozen=True, slots=True)
class Translation:
    id: str
    text: str
    context: str | None = None
    # The original in the target's notation: only in a workspace.
    source: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    """How a name or term of the original is written in Arabic, everywhere."""

    term: str
    text: str
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationSet:
    target: str
    notation: str
    entries: tuple[Translation, ...]
    glossary: tuple[GlossaryTerm, ...] = ()
    # Where a workspace's sources come from; None for a committed file.
    workspace_from: str | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                raise ClassicRetroError(
                    ErrorCode.DUPLICATE_ENTRY_ID,
                    f"{self.target} translations: duplicate entry id {entry.id}",
                )
            seen.add(entry.id)
            for field_name, value in (("text", entry.text), ("source", entry.source)):
                controls = sorted(set(value or "") & _DIRECTION_CONTROLS)
                if controls:
                    codes = ", ".join(f"U+{ord(character):04X}" for character in controls)
                    raise ClassicRetroError(
                        ErrorCode.EXPLICIT_BIDI_CONTROL,
                        f"{self.target} translations: {entry.id} {field_name} holds "
                        f"direction controls ({codes}); write logical text",
                    )

    @property
    def is_workspace(self) -> bool:
        return self.workspace_from is not None

    def texts(self, ids: Sequence[str]) -> dict[str, str]:
        """The text of exactly these entries (a target's pinned ones), in their order."""
        known = {entry.id: entry.text for entry in self.entries}
        wanted = set(ids)
        missing = [entry_id for entry_id in ids if entry_id not in known]
        unknown = [entry_id for entry_id in known if entry_id not in wanted]
        if missing or unknown:
            problems = []
            if missing:
                problems.append("missing " + ", ".join(missing))
            if unknown:
                problems.append("unknown " + ", ".join(unknown))
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"{self.target} translations: " + "; ".join(problems),
            )
        return {entry_id: known[entry_id] for entry_id in ids}

    def with_sources(self, sources: Mapping[str, str], origin: str) -> TranslationSet:
        """A workspace: every entry with its original, decoded from ``origin``."""
        entries = tuple(
            replace(entry, source=sources[entry.id]) if entry.id in sources else entry
            for entry in self.entries
        )
        return replace(self, entries=entries, workspace_from=origin)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "target": self.target,
            "language": "ar",
            "notation": self.notation,
        }
        if self.workspace_from is not None:
            data["workspace"] = {"from": self.workspace_from, "notice": WORKSPACE_NOTICE}
        if self.glossary:
            data["glossary"] = [_without_none(_term_dict(term)) for term in self.glossary]
        data["entries"] = [_without_none(_entry_dict(entry)) for entry in self.entries]
        return data

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def _entry_dict(entry: Translation) -> dict[str, Any]:
    return {
        "id": entry.id,
        "context": entry.context,
        "source": entry.source,
        "text": entry.text,
        "notes": entry.notes,
    }


def _term_dict(term: GlossaryTerm) -> dict[str, Any]:
    return {"term": term.term, "text": term.text, "notes": term.notes}


def _without_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def translation_set_from_dict(data: object) -> TranslationSet:
    validate_document(SCHEMA, data)
    assert isinstance(data, dict)
    workspace = data.get("workspace")
    return TranslationSet(
        target=data["target"],
        notation=data["notation"],
        entries=tuple(
            Translation(
                id=item["id"],
                text=item["text"],
                context=item.get("context"),
                source=item.get("source"),
                notes=item.get("notes"),
            )
            for item in data["entries"]
        ),
        glossary=tuple(
            GlossaryTerm(term=item["term"], text=item["text"], notes=item.get("notes"))
            for item in data.get("glossary", ())
        ),
        workspace_from=None if workspace is None else workspace["from"],
    )


def load_translation_set(path: Path, target: str | None = None) -> TranslationSet:
    """A translations file or workspace; ``target`` refuses another target's file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"Could not read translations {path}: {exc}",
        ) from exc
    translations = translation_set_from_dict(data)
    if target is not None and translations.target != target:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"{path} holds translations of {translations.target}, not {target}",
        )
    return translations


@cache
def builtin_translation_set(target: str) -> TranslationSet:
    """The shipped translations of a target (``classic_retro/translations/<target>.json``)."""
    resource = files("classic_retro").joinpath("translations", f"{target}.json")
    try:
        data = json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"No shipped translations for target {target}"
        ) from exc
    translations = translation_set_from_dict(data)
    if translations.target != target or translations.is_workspace:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"translations/{target}.json must be the committed translations of {target}",
        )
    return translations


def glossary_report(translations: TranslationSet) -> list[dict[str, str]]:
    """Entries whose original names a glossary term that their Arabic does not use.

    Only a workspace has the originals. Where terms overlap, the longest one
    counts ("MegaMan.EXE" over "MegaMan"). A report is a reminder, not an error:
    a translation may say "he" instead of repeating a name.
    """
    report = []
    for entry in translations.entries:
        if entry.source is None:
            continue
        found = [
            (match.start(), match.end(), term)
            for term in translations.glossary
            for match in _occurrences(entry.source, term.term)
        ]
        reported: set[str] = set()
        for start, end, term in found:
            if any(
                other_start <= start and end <= other_end and other_end - other_start > end - start
                for other_start, other_end, _ in found
            ):
                continue
            if term.text not in entry.text and term.term not in reported:
                reported.add(term.term)
                report.append({"id": entry.id, "term": term.term, "expected": term.text})
    return report


def _occurrences(text: str, term: str) -> Iterator[re.Match[str]]:
    return re.finditer(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text)
