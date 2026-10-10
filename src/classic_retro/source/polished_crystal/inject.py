"""Putting the translated entries into the source, in memory.

Each translated entry replaces the lines it owns (``start``..``end``) with the
encoder's lines. The owned lines are checked against the entry's pin first, so
the translation lands only on the text it was written for. A file's entries
are replaced from the bottom up, so the manifest's line numbers stay valid; an
entry is never allowed to overlap another.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source.polished_crystal import encode
from classic_retro.source.polished_crystal.asmscan import split_comment
from classic_retro.source.polished_crystal.manifest import Manifest, pin


def ngram_leaves(manifest: Manifest, texts: Mapping[str, str]) -> encode.Ngrams | None:
    """The n-gram leaves compressed text may use: ``#mon`` once its word is translated.

    The encoder writes ``#mon`` for the Arabic word wherever it occurs, so the
    whole word takes one Huffman code, as "Pokémon" does in English.
    """
    table = {}
    for token, entry_id in manifest.ngram_entries.items():
        if token == "#mon" and texts.get(entry_id, "").strip():
            table[token] = texts[entry_id].strip()
    return encode.Ngrams(table) if table else None


def encode_entries(
    manifest: Manifest, texts: Mapping[str, str], ngrams: encode.Ngrams | None
) -> dict[str, list[str]]:
    """Every translated entry's replacement lines, in manifest order."""
    out = {}
    problems = []
    for entry_id, entry in manifest.entries.items():
        text = texts.get(entry_id)
        if text is None or not text.strip():
            continue
        lines, errors = encode._encode(entry, text, ngrams)
        if errors:
            problems.append(f"{entry_id}: {'; '.join(errors)}")
            continue
        out[entry_id] = lines
    if problems:
        # A character or a command the game cannot take, or a text that does not fit.
        unencodable = any(
            word in problem
            for problem in problems
            for word in ("not in the font", "not allowed", "placeholder", "reserved")
        )
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TEXT if unencodable else ErrorCode.TEXT_OVERFLOW,
            f"{len(problems)} entries cannot be encoded: " + " | ".join(problems[:20]),
        )
    return out


def inject(
    sources: Mapping[str, str], manifest: Manifest, encoded: Mapping[str, Sequence[str]]
) -> dict[str, str]:
    """The files of ``sources`` that hold translated entries, with the entries replaced."""
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry_id in encoded:
        entry = manifest.entries[entry_id]
        by_file[entry["file"]].append(entry)
    out = {}
    for path, entries in by_file.items():
        if path not in sources:
            raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"{path} is not read")
        lines = sources[path].split("\n")
        below = None
        for entry in sorted(entries, key=lambda item: item["start"], reverse=True):
            start, end = entry["start"], entry["end"]
            if below is not None and end >= below:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_PATCH_FAILED, f"{entry['id']} overlaps another entry"
                )
            if pin(lines, start, end) != entry["sha256"]:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_BASELINE_MISMATCH,
                    f"{entry['id']}: the lines {path}:{start}-{end} differ from the pinned ones",
                )
            lines[start - 1 : end] = list(encoded[entry["id"]])
            below = start
        out[path] = "\n".join(lines)
    return out


def entry_lines(
    sources: Mapping[str, str], manifest: Manifest, encoded: Mapping[str, Sequence[str]]
) -> Iterable[tuple[dict[str, Any], Sequence[str]]]:
    """Every entry with the lines it will have: its translation's, or its own."""
    split: dict[str, list[str]] = {}
    for entry_id, entry in manifest.entries.items():
        if entry_id in encoded:
            yield entry, encoded[entry_id]
            continue
        path = entry["file"]
        if path not in split:
            split[path] = sources[path].split("\n")
        yield entry, split[path][entry["start"] - 1 : entry["end"]]


_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
_TOKEN = re.compile(r"<[^<>]*>|\{[^{}]*\}|\\.|.", re.DOTALL)
# Bytes a line's macro adds to its strings (the line code it stands for, li's terminator).
_MACRO_BYTES = {"next": 1, "next1": 1, "page": 1, "li": 1, "line": 1, "cont": 1, "para": 1}


def plain_bytes(lines: Iterable[str]) -> int:
    """Bytes of uncompressed string lines, counting every character as one byte.

    No n-gram is counted, so this never comes out below what the assembler
    writes: a budget it passes the build passes too. ``{d:...}`` counts five
    digits, the most a 16-bit number has.
    """
    total = 0
    for line in lines:
        code, _ = split_comment(line)
        literals = _LITERAL.findall(code)
        if not literals:
            continue
        body = re.sub(r"^[\w.]+:+\s*", "", code.strip())
        macro = re.split(r'[\s"]', body, maxsplit=1)[0].lower()
        total += _MACRO_BYTES.get(macro, 0)
        for literal in literals:
            for token in _TOKEN.findall(literal):
                total += 5 if token.startswith("{d:") else 1
    return total


def group_growth(
    manifest: Manifest, encoded: Mapping[str, Sequence[str]]
) -> dict[str, tuple[int, int]]:
    """For each ``dr`` table a translated entry is in: (growth in bytes, slack)."""
    growth: dict[str, int] = defaultdict(int)
    for entry_id, lines in encoded.items():
        limits = manifest.entries[entry_id].get("limits") or {}
        for group in limits.get("dr_groups") or ():
            growth[group] += plain_bytes(lines) - int(limits.get("en_bytes", 0))
    return {
        group: (bytes_, int(manifest.groups[group]["slack"])) for group, bytes_ in growth.items()
    }
