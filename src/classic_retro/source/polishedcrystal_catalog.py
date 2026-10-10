"""Source-text inventory for Rangi42/polishedcrystal v3.2.3.

This is a research catalog, NOT a playable Arabic ROM overlay. The upstream
RGBDS charmap/font/text renderer are not Arabic-aware. Never treat entries in
this catalog as directly safe to assemble into the game.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode

SOURCE_COMMIT = "3fa43192379df5c3e7b09a08e4d5d79af4f02f42"
SUPPORTED_VERSION = "3.2.3"
SOURCE_DIRS = ("maps", "data", "engine", "home")
PINNED_BLOBS = {
    "Makefile": "d096349b08875a26d1fc1c2df6b98d09461e8cf8",
    "constants/charmap.asm": "7550b07027b58385603d95dd89c4d7af0c4782c0",
    "home/text.asm": "e913e837020629499c25d968044543171a3a9d4a",
    "macros/scripts/text.asm": "9806b9482e9c9525c49fb7412272c4dd19410aff",
    "engine/gfx/load_font.asm": "a639c6c441ef5cb80e58fced7434ebdbcbbf314d",
}
DIALOGUE = frozenset(("text", "next", "next1", "line", "cont", "para", "done", "prompt", "page"))
STRING_DIRECTIVES = frozenset(("db", "rawchar"))
TOKEN = re.compile(r"<[A-Za-z][A-Za-z0-9_]*>")
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
DIRECTIVE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_.]*::?\s*)*([A-Za-z_][A-Za-z0-9_]*)\b"
)
ARABIC = re.compile(r"[\u0600-\u06ff]")


def without_comment(line: str) -> str:
    """Keep semicolons in RGBDS quoted strings, discard source comments."""
    quoted = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            return line[:index]
    return line


def _source_files(root: Path):
    for subdir in SOURCE_DIRS:
        folder = root / subdir
        if folder.is_dir():
            yield from sorted(folder.rglob("*.asm"))
    for name in ("home.asm", "main.asm"):
        if (root / name).is_file():
            yield root / name


def _verify_upstream(root: Path) -> None:
    """Require the exact v3.2.3 tag, even if another branch keeps VERSION=3.2.3."""
    for name, expected in PINNED_BLOBS.items():
        path = root / name
        if not path.is_file():
            raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"missing {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"unexpected {name}: v3.2.3 required"
            )
    if (root / ".git").exists():
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, capture_output=True, check=False,
        )
        if commit.returncode != 0 or commit.stdout.strip() != SOURCE_COMMIT:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, "source checkout is not v3.2.3"
            )


def scan_source(root: Path, *, strict: bool = True) -> dict[str, object]:
    """Inventory all quoted strings; classify unknown and non-dialogue strings for review.

    'review' includes every unknown quoted literal, rather than silently dropping
    it. Menus, items, names, and binary data use 'db'; a translator must audit
    these before ever describing the game's localization as complete.
    """
    root = Path(root).resolve()
    makefile = root / "Makefile"
    if not makefile.is_file() or not re.search(
        rf"(?m)^VERSION\s*:=\s*{re.escape(SUPPORTED_VERSION)}\s*$",
        makefile.read_text(encoding="utf-8"),
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"expected Polished Crystal v{SUPPORTED_VERSION} source: {root}",
        )
    if strict:
        _verify_upstream(root)
    entries: list[dict[str, object]] = []
    file_count = 0
    for path in _source_files(root):
        file_count += 1
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(data).hexdigest()
        for line_no, raw in enumerate(data.decode("utf-8-sig").splitlines(), 1):
            source = without_comment(raw)
            matches = list(QUOTED.finditer(source))
            if not matches:
                continue
            directive = DIRECTIVE.match(source)
            opcode = directive.group(1).lower() if directive else ""
            if opcode in DIALOGUE:
                category = "dialogue"
            elif opcode in STRING_DIRECTIVES:
                category = "string"
            else:
                category = "review"
            for idx, match in enumerate(matches):
                literal = match.group()[1:-1]
                entries.append({
                    "id": f"{rel}:{line_no}:{idx}",
                    "file": rel,
                    "line": line_no,
                    "index": idx,
                    "category": category,
                    "directive": opcode,
                    "source": literal,
                    "source_file_sha256": digest,
                    "arabic": None,
                })
    counts = dict(sorted(Counter(e["category"] for e in entries).items()))
    return {
        "format": "classic-retro-polishedcrystal-catalog-v1",
        "game": "polished-crystal",
        "source_commit": SOURCE_COMMIT,
        "version": SUPPORTED_VERSION,
        "source_verified": strict,
        "files_scanned": file_count,
        "count": len(entries),
        "categories": counts,
        "entries": entries,
    }


def validate_translation(source: str, arabic: str) -> list[str]:
    """Require preserved runtime tokens and terminators; font fit is separate."""
    problems: list[str] = []
    if not ARABIC.search(arabic):
        problems.append("no Arabic text")
    if Counter(TOKEN.findall(arabic)) != Counter(TOKEN.findall(source)):
        problems.append("runtime placeholders changed")
    if arabic.count("@") != source.count("@"):
        problems.append("@ terminator count changed")
    if any(c in arabic for c in ("\n", "\r", "\x00")):
        problems.append("newlines or NUL are not allowed inside one RGBDS literal")
    if '"' in arabic:
        problems.append("raw double quote is not escaped")
    return problems


def check_workspace(
    root: Path, workspace: dict[str, object], *, strict: bool = True
) -> dict[str, object]:
    """Re-read the source; check ID, exact line, preserved tokens and coverage.

    'review' entries can be set to 'not_text' after a human checks them.
    Neither a complete catalog nor a complete translation proves RTL rendering.
    """
    fresh = scan_source(root, strict=strict)
    expected = {e["id"]: e for e in fresh["entries"]}
    entries = workspace.get("entries")
    if not isinstance(entries, list):
        raise ClassicRetroError(ErrorCode.INVALID_TRANSLATION_DOCUMENT, "workspace.entries must be a list")
    if workspace.get("source_commit") != SOURCE_COMMIT:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "workspace targets another upstream commit")
    reported: list[dict[str, str]] = []
    translated = 0
    reviewed_non_text = 0
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ClassicRetroError(ErrorCode.INVALID_TRANSLATION_DOCUMENT, "invalid workspace entry")
        key = item["id"]
        if key in seen:
            reported.append({"id": key, "problem": "duplicate ID"})
            continue
        seen.add(key)
        reference = expected.get(key)
        if reference is None:
            reported.append({"id": key, "problem": "unknown source ID"})
            continue
        for field in ("file", "line", "index", "category", "directive", "source", "source_file_sha256"):
            if item.get(field) != reference[field]:
                reported.append({"id": key, "problem": f"source drift: {field}"})
                break
        else:
            arabic = item.get("arabic")
            ignored = item.get("review") == "not_text"
            if ignored and reference["category"] != "review":
                reported.append({"id": key, "problem": "only review entries can be not_text"})
            elif ignored and arabic is not None:
                reported.append({"id": key, "problem": "review entry has both Arabic and not_text"})
            elif ignored:
                reviewed_non_text += 1
            elif isinstance(arabic, str) and arabic:
                problems = validate_translation(str(reference["source"]), arabic)
                for problem in problems:
                    reported.append({"id": key, "problem": problem})
                if not problems:
                    translated += 1
            elif arabic is not None:
                reported.append({"id": key, "problem": "Arabic must be text or null"})
    missing_ids = sorted(set(expected) - seen)
    for key in missing_ids[:50]:
        reported.append({"id": key, "problem": "missing entry"})
    return {
        "source_entries": len(expected),
        "translated": translated,
        "reviewed_not_text": reviewed_non_text,
        "remaining": len(expected) - translated - reviewed_non_text,
        "missing_entries": len(missing_ids),
        "errors": reported,
        "source_only": True,
        "renderer_ready": False,
        "complete": not reported and len(expected) == translated + reviewed_non_text,
    }


def write_catalog(source: Path, output: Path) -> dict[str, object]:
    catalog = scan_source(source)
    if output.exists():
        raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"refusing to overwrite existing catalog: {output}")
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in catalog.items() if key != "entries"}
