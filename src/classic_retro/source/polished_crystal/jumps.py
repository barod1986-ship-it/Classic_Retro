"""Short jumps over text, made long where the text between them grows.

A few jumps of Polished Crystal's code and scripts store their distance in one
byte: the CPU's ``jr`` (a signed byte) and the scripts' ``sjumpfwd``,
``iftruefwd``, ``iffalsefwd`` and ``ifequalfwd`` (an unsigned byte, forward
only). Where text lies between such a jump and its target, a translation that
grows the text may push the target out of reach: the assembler then only warns
and truncates the distance. ``prepare`` finds every such jump whose text grows
and writes its long form instead (``jp``, ``sjump``, ``iftrue``, ``iffalse``,
``ifequal``: an address, one byte more), which reaches anywhere in the bank. A
short jump to a label of another file (the text between is beyond this file) is
always made long.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from classic_retro.source.polished_crystal.asmscan import split_comment

# Short form -> long form.
LONG_FORM = {
    "jr": "jp",
    "sjumpfwd": "sjump",
    "iftruefwd": "iftrue",
    "iffalsefwd": "iffalse",
    "ifequalfwd": "ifequal",
}
_DIRECTIVES = frozenset(
    "DEF REDEF MACRO ENDM IF ELIF ELSE ENDC REPT FOR ENDR BREAK SECTION ENDSECTION INCLUDE "
    "INCBIN LOAD ENDL UNION NEXTU ENDU PUSHS POPS OPT PUSHO POPO ASSERT STATIC_ASSERT CHARMAP "
    "NEWCHARMAP SETCHARMAP PUSHC POPC EXPORT PURGE RSRESET RSSET PRINTLN PRINT WARN FAIL SHIFT".split()
)
_LABEL = re.compile(r"^(\.?[A-Za-z_][\w.]*)(::?)?(?=\s|$|;)")
_JUMP = re.compile(r"^\s*(?:[\w.]+:+\s*)?(jr|sjumpfwd|iftruefwd|iffalsefwd|ifequalfwd)\b\s*(.*)$")


_IDENTIFIER = re.compile(r"[A-Za-z_][\w.]*")


@dataclass(frozen=True, slots=True)
class Jump:
    line: int  # 1-based
    kind: str
    target: int | None  # the target label's line; None for a label of another file


def short_jumps(text: str) -> list[Jump]:
    """Every short jump of a source file to a label (outside macro definitions)."""
    lines = text.split("\n")
    labels: dict[str, int] = {}
    pending: list[tuple[int, str, str, str]] = []
    scope = ""
    in_macro = False
    for number, raw in enumerate(lines, start=1):
        code, _ = split_comment(raw)
        if not code.strip():
            continue
        first = code.split()[0].upper()
        if first == "MACRO" or code.strip().upper().startswith("MACRO "):
            in_macro = True
            continue
        if in_macro:
            in_macro = first != "ENDM"
            continue
        if not raw[:1].isspace():
            match = _LABEL.match(code)
            if match and match.group(1).upper() not in _DIRECTIVES:
                name = match.group(1)
                if name.startswith("."):
                    labels[scope + name] = number
                elif match.group(2):
                    scope = name
                    labels[name] = number
        jump = _JUMP.match(code)
        if jump:
            arguments = [argument.strip() for argument in jump.group(2).split(",")]
            target = arguments[-1] if arguments and arguments[-1] else ""
            if (
                jump.group(1) == "jr"
                and len(arguments) == 2
                and arguments[0]
                not in (
                    "z",
                    "nz",
                    "c",
                    "nc",
                )
            ):
                continue
            pending.append((number, jump.group(1), target, scope))
    out = []
    for number, kind, target, scope_at in pending:
        full = scope_at + target if target.startswith(".") else target
        if full in labels:
            out.append(Jump(number, kind, labels[full]))
        elif not target.startswith(".") and _IDENTIFIER.fullmatch(target):
            out.append(Jump(number, kind, None))
    return out


def jumps_to_lengthen(
    text: str, entries: Sequence[tuple[int, int, int]], margin: int = 3
) -> list[int]:
    """The lines of the short jumps over text that may grow past their reach.

    ``entries`` are (start, end, growth in bytes) of the file's texts. A jump is
    made long when the texts between it and its target grow by more than
    ``-margin`` bytes in all: the sizes are estimates, so a margin of a few
    bytes keeps a jump that was at the edge of its reach safe.
    """
    lines = []
    for jump in short_jumps(text):
        if jump.target is None:
            lines.append(jump.line)
            continue
        low, high = sorted((jump.line, jump.target))
        growth = sum(delta for start, end, delta in entries if low < start and end < high)
        if growth > -margin and any(low < start and end < high for start, end, _ in entries):
            lines.append(jump.line)
    return lines


def lengthen(text: str, numbers: Sequence[int]) -> str:
    """The file with the short jumps of ``numbers`` written in their long form."""
    rows = text.split("\n")
    for number in numbers:
        row = rows[number - 1]
        match = _JUMP.match(split_comment(row)[0])
        if match is None:
            raise ValueError(f"line {number} is no short jump: {row!r}")
        short = match.group(1)
        rows[number - 1] = re.sub(rf"\b{short}\b", LONG_FORM[short], row, count=1)
    return "\n".join(rows)


def lengthen_all(
    sources: Mapping[str, str], growth: Mapping[str, Sequence[tuple[int, int, int]]]
) -> dict[str, tuple[str, int]]:
    """Each file with texts whose jumps must be long: (new text, jumps made long)."""
    out = {}
    for path, entries in growth.items():
        numbers = jumps_to_lengthen(sources[path], entries)
        if numbers:
            out[path] = (lengthen(sources[path], numbers), len(numbers))
    return out
