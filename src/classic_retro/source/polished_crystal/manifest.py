"""The overlay's manifest: every text of the game it can translate, without the text.

``extract.Extractor`` finds 13,000-odd texts in the engine-patched tree and
describes each one: a stable id, a kind (``dialog``, ``box``, ``string``,
``field``), the lines of its file it owns, a pin of those lines, its
placeholders (the skeleton), its limits and the structure the encoder rebuilds
it from (``fmt``). The manifest ships that description, compacted:

- entries grouped by file; an id that starts with the file's path (without
  ``.asm``) keeps only the rest;
- ``limits``, ``fmt``, skeletons and categories stored once in tables and named
  by index;
- the pin truncated to ``HASH_LENGTH`` hexadecimal digits of the SHA-256 of the
  owned lines joined by line ends (``make`` checks the truncated pins of a file
  are distinct).

It holds no text of the game and no context: the contexts are the translation
file's, and the originals are read from the user's own checkout
(``targets extract``). ``classic-retro polished-crystal make-manifest`` builds it
again from a pristine checkout.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode

FORMAT = "polished-crystal-manifest/1"
HASH_LENGTH = 16
KINDS = ("dialog", "box", "string", "field")
CHARMAPS = ("default", "no_ngrams")


@dataclass(frozen=True, slots=True)
class Manifest:
    """The entries, by id in source order, and what the overlay needs around them."""

    commit: str
    engine_patch: str
    entries: Mapping[str, dict[str, Any]]
    ngram_entries: Mapping[str, str]
    groups: Mapping[str, dict[str, Any]]

    def __len__(self) -> int:
        return len(self.entries)

    def files(self) -> list[str]:
        """Every file an entry is in, in source order."""
        return list(dict.fromkeys(entry["file"] for entry in self.entries.values()))


def pin(lines: Sequence[str], start: int, end: int) -> str:
    """The truncated pin of lines ``start``..``end`` (1-based, inclusive)."""
    return hashlib.sha256("\n".join(lines[start - 1 : end]).encode("utf-8")).hexdigest()[
        :HASH_LENGTH
    ]


def _path_id(path: str) -> str:
    return path[:-4] if path.endswith(".asm") else path


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compact(
    entries: Iterable[Mapping[str, Any]],
    *,
    commit: str,
    engine_patch: str,
    ngram_entries: Mapping[str, str],
    groups: Mapping[str, Any],
) -> dict[str, Any]:
    """The extractor's entries as the shipped manifest (see the module's docstring)."""
    tables: dict[str, list[object]] = {"limits": [], "fmt": [], "skeleton": [], "category": []}
    index: dict[str, dict[str, int]] = {name: {} for name in tables}

    def ref(table: str, value: object) -> int:
        key = _canonical(value)
        if key not in index[table]:
            index[table][key] = len(tables[table])
            tables[table].append(value)
        return index[table][key]

    by_file: dict[str, list[list[object]]] = {}
    seen_pins: dict[str, dict[str, str]] = {}
    for entry in entries:
        path = entry["file"]
        prefix = _path_id(path)
        entry_id = entry["id"]
        short = entry_id[len(prefix) :] if entry_id.startswith(prefix) else "=" + entry_id
        short_pin = entry["sha256"][:HASH_LENGTH]
        other = seen_pins.setdefault(path, {}).setdefault(short_pin, entry["sha256"])
        if other != entry["sha256"]:
            raise ClassicRetroError(
                ErrorCode.SOURCE_PATCH_FAILED,
                f"{entry_id}: two texts of {path} share the pin {short_pin}; lengthen HASH_LENGTH",
            )
        by_file.setdefault(path, []).append(
            [
                short,
                KINDS.index(entry["kind"]),
                entry["start"],
                entry["end"],
                short_pin,
                CHARMAPS.index(entry.get("charmap", "default")),
                ref("category", entry["category"]),
                ref("skeleton", list(entry.get("skeleton") or [])),
                ref("limits", entry.get("limits") or {}),
                ref("fmt", entry["fmt"]),
            ]
        )
    return {
        "format": FORMAT,
        "commit": commit,
        "engine_patch": engine_patch,
        "hash_length": HASH_LENGTH,
        "ngram_entries": dict(ngram_entries),
        "groups": dict(groups),
        "tables": tables,
        "files": by_file,
    }


def expand(data: Mapping[str, Any]) -> Manifest:
    """A shipped manifest's entries as the encoder and injector read them."""
    if data.get("format") != FORMAT:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"Not a {FORMAT} manifest: {data.get('format')}"
        )
    tables = data["tables"]
    entries: dict[str, dict[str, Any]] = {}
    for path, rows in data["files"].items():
        prefix = _path_id(path)
        for short, kind, start, end, short_pin, charmap, category, skeleton, limits, fmt in rows:
            entry_id = short[1:] if short.startswith("=") else prefix + short
            entries[entry_id] = {
                "id": entry_id,
                "kind": KINDS[kind],
                "file": path,
                "start": start,
                "end": end,
                "sha256": short_pin,
                "charmap": CHARMAPS[charmap],
                "category": tables["category"][category],
                "skeleton": list(tables["skeleton"][skeleton]),
                "limits": tables["limits"][limits],
                "fmt": tables["fmt"][fmt],
            }
    return Manifest(
        commit=data["commit"],
        engine_patch=data["engine_patch"],
        entries=entries,
        ngram_entries=data["ngram_entries"],
        groups=data["groups"],
    )


def dumps(data: Mapping[str, Any]) -> str:
    """The manifest as shipped: one file's entries a line, the tables one item a line."""
    lines = ["{"]
    head = {key: data[key] for key in data if key not in ("tables", "files")}
    for key, value in head.items():
        lines.append(f"  {json.dumps(key)}: {_canonical(value)},")
    lines.append('  "tables": {')
    names = list(data["tables"])
    for number, name in enumerate(names):
        items = data["tables"][name]
        lines.append(f"    {json.dumps(name)}: [")
        lines += [
            f"      {_canonical(item)}" + ("," if k + 1 < len(items) else "")
            for k, item in enumerate(items)
        ]
        lines.append("    ]" + ("," if number + 1 < len(names) else ""))
    lines.append("  },")
    lines.append('  "files": {')
    paths = list(data["files"])
    for number, path in enumerate(paths):
        separator = "," if number + 1 < len(paths) else ""
        lines.append(f"    {json.dumps(path)}: {_canonical(data['files'][path])}{separator}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


@cache
def builtin_manifest() -> Manifest:
    """The manifest the overlay ships (``data/manifest.json``)."""
    resource = files("classic_retro.source.polished_crystal").joinpath("data", "manifest.json")
    return expand(json.loads(resource.read_text(encoding="utf-8")))
