"""Text tables: a game's own character codes, from ``.tbl`` files.

A table uses the common Thingy format, one entry per line:

- ``41=A``: the byte 0x41 stands for "A";
- ``8140=X``: two bytes stand for one character;
- ``/FF=<end>``: an end code; a string stops after it;
- ``*FE``: a line break, shown as a newline unless the line gives a text;
- ``$E0=<wait>``: a control code, decoded like any entry.

Hex digits come in pairs. An entry may be longer than one byte, and the
longest match wins. Blank lines and lines starting with ``#`` or ``;`` are
skipped. A value keeps its spaces, so ``20=`` and a space maps 0x20 to a space.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from classic_retro.core.errors import ClassicRetroError, ErrorCode


@dataclass(frozen=True, slots=True)
class TextTable:
    entries: Mapping[bytes, str]
    # Codes that end a string (their text still shows).
    ends: frozenset[bytes] = frozenset()
    longest: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))
        object.__setattr__(self, "longest", max((len(code) for code in self.entries), default=0))

    def match(self, data: bytes, offset: int) -> tuple[bytes, str] | None:
        """The longest entry whose code starts at ``offset``."""
        for size in range(min(self.longest, len(data) - offset), 0, -1):
            code = bytes(data[offset : offset + size])
            text = self.entries.get(code)
            if text is not None:
                return code, text
        return None

    def decode(self, data: bytes) -> str:
        """``data`` as text; a byte without an entry shows as ``{XX}``."""
        parts = []
        offset = 0
        while offset < len(data):
            found = self.match(data, offset)
            if found is None:
                parts.append(f"{{{data[offset]:02X}}}")
                offset += 1
            else:
                code, text = found
                parts.append(text)
                offset += len(code)
        return "".join(parts)


def parse_table(text: str, source: str = "table") -> TextTable:
    entries: dict[bytes, str] = {}
    ends: set[bytes] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        kind = line[0] if line[0] in "/*$" else ""
        code_text, equals, value = line[len(kind) :].partition("=")
        if not equals:
            if not kind or kind == "$":
                raise ClassicRetroError(
                    ErrorCode.INVALID_TEXT_TABLE, f"{source} line {number}: expected HEX=TEXT"
                )
            value = "\n" if kind == "*" else ""
        code_text = code_text.strip()
        try:
            code = bytes.fromhex(code_text)
        except ValueError:
            code = b""
        if not code or len(code_text) != 2 * len(code):
            raise ClassicRetroError(
                ErrorCode.INVALID_TEXT_TABLE,
                f"{source} line {number}: {code_text!r} is not hex bytes",
            )
        if code in entries:
            raise ClassicRetroError(
                ErrorCode.INVALID_TEXT_TABLE,
                f"{source} line {number}: {code.hex().upper()} is defined twice",
            )
        entries[code] = value
        if kind == "/":
            ends.add(code)
    if not entries:
        raise ClassicRetroError(ErrorCode.INVALID_TEXT_TABLE, f"{source} has no entries")
    return TextTable(entries, frozenset(ends))


def load_table(path: Path) -> TextTable:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_TEXT_TABLE, f"Could not read the table {path}: {exc}"
        ) from exc
    return parse_table(text, str(path))
