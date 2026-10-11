"""The text codes trained on the translated tree: n-grams and Huffman codes.

Polished Crystal stores text two ways (``macros/scripts/text.asm``):

- a ``text``-started stream (the speech box) is Huffman-coded with the codes of
  the ``ctxtmap`` lines of ``constants/charmap.asm``, from which the assembler
  builds the decoding tree;
- every other string (menus, names, descriptions, the Pokédex) is stored a byte
  a character, but the ``default`` charmap maps 64 multi-character strings to
  the codes ``$0a-$49``, which the game expands from ``data/text/ngrams.asm``.

English codes would waste the ROM on Arabic, so ``prepare`` trains both on the
tree it is about to write: the translated texts as the encoder writes them and
every text still in English as it is. The Huffman codes come from the symbols of
every compressed text. The n-grams are chosen greedily over the uncompressed
strings, by the bytes they save, within the bytes the English n-gram strings
take in ROM0; ``, `` stays an n-gram, as the encoder counts it. An n-gram is a
sequence of glyph codes, written in the charmap as every spelling of it the
tree uses (a glyph has several presentation forms, and Latin letters share the
Arabic glyphs' codes), so the assembler applies it wherever it fits.

``charmap_asm`` writes the charmap from the pinned original: the shifted leaves
start at the gender codes, the gender codes ``<GM>``, ``<GF>`` and ``<GE>``
(``$4a-$4c``) take the place of three English n-grams, the presentation forms
map to their glyph codes, and every ``ctxtmap`` gets its trained code.
``ngrams_asm`` writes the n-gram strings over the original's, line for line.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.pokemon_gen2_arabic.forms import charmap_lines
from classic_retro.engines.pokemon_gen2_arabic.huffman import (
    LEAVES,
    coded_bits,
    huffman_codes,
    is_complete_prefix_code,
)
from classic_retro.source.polished_crystal import asmscan
from classic_retro.source.polished_crystal.units import Charmap

NGRAM_CODES = tuple(range(0x0A, 0x4A))
GENDER_CODES = {"<GM>": 0x4A, "<GF>": 0x4B, "<GE>": 0x4C}
# The English n-grams the gender codes replace.
REPLACED_NGRAM_CODES = tuple(GENDER_CODES.values())
# Kept whatever the corpus: the encoder counts ", " as one byte (encode.literal_bytes).
COMMA_SPACE = (0x9D, 0x7F)
GLYPH_RANGE = range(0x7F, 0xEC)
MACRO_CODE = {
    "line": 0x57,
    "cont": 0x58,
    "para": 0x59,
    "next": 0x56,
    "next1": 0x55,
    "done": 0x52,
    "prompt": 0x54,
    "page": 0x53,
}
TEXT_COMMANDS = frozenset(
    {
        "text_ram",
        "text_decimal",
        "text_promptbutton",
        "text_pause",
        "text_sound",
        "text_today",
        "text_far",
        "text_plural",
    }
)
TERMINATOR = 0x53
_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
_CTXTMAP = re.compile(
    r'^(\s*ctxtmap\s+)("(?:[^"\\]|\\.)*")(\s*,\s*)\$([0-9a-fA-F]{2})(\s*,\s*)([01]+)(.*)$'
)
_NGRAM_CHARMAP = re.compile(r'^\s*charmap\s+"((?:[^"\\]|\\.)*)"\s*,\s*\$([0-9a-fA-F]{2})\s*$')
_ARABIC_PUNCTUATION_LINES = ('\tcharmap "،", $9d', '\tcharmap "؟", $9e')


@dataclass
class Corpus:
    """What the tree's texts are made of, as glyph codes."""

    # Symbol counts of the compressed (Huffman-coded) streams.
    huffman: Counter[int] = field(default_factory=Counter)
    # Each uncompressed string the n-grams apply to, as (spelling, code) tokens.
    plain: list[list[tuple[str, int]]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TextCodes:
    """The trained codes: a Huffman code per leaf, and the n-grams by code."""

    huffman: Mapping[int, str]
    # code -> (glyph codes, the spellings the charmap maps to it)
    ngrams: Mapping[int, tuple[tuple[int, ...], tuple[str, ...]]]
    huffman_bits: int
    ngram_saving: int

    def report(self) -> dict[str, object]:
        return {
            "huffman_leaves": len(self.huffman),
            "huffman_longest_code": max(len(code) for code in self.huffman.values()),
            "huffman_bytes": (self.huffman_bits + 7) // 8,
            "ngrams": len(self.ngrams),
            "ngram_saving_bytes": self.ngram_saving,
        }


def _macro(line: str) -> str:
    code, _ = asmscan.split_comment(line)
    body = re.sub(r"^[\w.]+:+\s*", "", code.strip())
    return re.split(r'[\s"]', body, maxsplit=1)[0].lower() if body else ""


def _literals(line: str) -> list[str]:
    code, _ = asmscan.split_comment(line)
    return [match.group(1) for match in _LITERAL.finditer(code)]


def is_compressed(entry: Mapping[str, object]) -> bool:
    """Whether the game stores the entry Huffman-coded (a ``text``-started stream)."""
    if entry["kind"] == "dialog":
        return True
    fmt = entry.get("fmt") or {}
    return entry["kind"] == "box" and isinstance(fmt, dict) and fmt.get("first", "") == "text"


def gather(charmap: Charmap, texts: Iterable[tuple[Mapping[str, object], Sequence[str]]]) -> Corpus:
    """The corpus of every entry's source lines (translated or not), entry by entry."""
    corpus = Corpus()
    for entry, lines in texts:
        limits = entry.get("limits") or {}
        compressed = is_compressed(entry)
        plain = (
            not compressed
            and not (isinstance(limits, dict) and limits.get("raw"))
            and entry.get("charmap", "default") != "no_ngrams"
        )
        for line in lines:
            macro = _macro(line)
            if compressed and macro in TEXT_COMMANDS:
                corpus.huffman[TERMINATOR] += 1
            if compressed and macro in MACRO_CODE:
                corpus.huffman[MACRO_CODE[macro]] += 1
            for literal in _literals(line):
                tokens = charmap.tokenize(literal, "compressing" if compressed else "no_ngrams")
                if compressed:
                    corpus.huffman.update(code for _, code in tokens if code is not None)
                elif plain:
                    run: list[tuple[str, int]] = []
                    for spelling, code in tokens:
                        if code is None or code not in GLYPH_RANGE:
                            if len(run) > 1:
                                corpus.plain.append(run)
                            run = []
                        else:
                            run.append((spelling, code))
                    if len(run) > 1:
                        corpus.plain.append(run)
    return corpus


def select_ngrams(
    runs: Sequence[Sequence[tuple[str, int]]], count: int, budget: int
) -> list[tuple[tuple[int, ...], int]]:
    """Up to ``count`` code sequences (2-4 glyphs), greedily by bytes saved.

    An n-gram of ``n`` glyphs saves ``n - 1`` bytes where it is used and costs
    ``n + 1`` bytes of ROM0 (its string and terminator) and one of the table;
    the strings stay within ``budget`` bytes. ``, `` is always chosen first.
    """
    work: list[list[object]] = [[code for _, code in run] for run in runs]
    chosen: list[tuple[tuple[int, ...], int]] = []
    used = 0

    def replace(sequence: tuple[int, ...]) -> int:
        hits = 0
        marker = ("ngram", len(chosen))
        for row in work:
            index = 0
            while index <= len(row) - len(sequence):
                if tuple(row[index : index + len(sequence)]) == sequence:
                    row[index : index + len(sequence)] = [marker]
                    hits += 1
                index += 1
        return hits

    chosen.append((COMMA_SPACE, replace(COMMA_SPACE)))
    used += len(COMMA_SPACE) + 1
    while len(chosen) < count:
        counts: Counter[tuple[int, ...]] = Counter()
        for row in work:
            for size in (2, 3, 4):
                for index in range(len(row) - size + 1):
                    sequence = tuple(row[index : index + size])
                    if all(isinstance(code, int) for code in sequence):
                        counts[sequence] += 1  # type: ignore[index]
        best: tuple[int, ...] | None = None
        best_gain = 0
        for sequence, hits in sorted(counts.items()):
            gain = hits * (len(sequence) - 1) - (len(sequence) + 2)
            if gain > best_gain and used + len(sequence) + 1 <= budget:
                best, best_gain = sequence, gain
        if best is None:
            break
        hits = replace(best)
        chosen.append((best, hits * (len(best) - 1) - (len(best) + 2)))
        used += len(best) + 1
    return chosen


def ngram_spellings(
    runs: Sequence[Sequence[tuple[str, int]]],
    sequences: Iterable[tuple[int, ...]],
    taken: Iterable[str],
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Every spelling of each code sequence the runs use, but strings the charmap has."""
    wanted = {tuple(sequence): set() for sequence in sequences}
    sizes = sorted({len(sequence) for sequence in wanted})
    for run in runs:
        codes = [code for _, code in run]
        for size in sizes:
            for index in range(len(run) - size + 1):
                sequence = tuple(codes[index : index + size])
                if sequence in wanted:
                    wanted[sequence].add(
                        "".join(spelling for spelling, _ in run[index : index + size])
                    )
    taken = set(taken)
    return {
        sequence: tuple(sorted(s for s in found if s not in taken))
        for sequence, found in wanted.items()
    }


def train(
    charmap: Charmap, texts: Iterable[tuple[Mapping[str, object], Sequence[str]]], ngram_budget: int
) -> TextCodes:
    """Huffman codes and n-grams for the tree whose entries' lines ``texts`` gives."""
    corpus = gather(charmap, texts)
    codes = huffman_codes(corpus.huffman)
    if not is_complete_prefix_code(codes.values()):
        raise ClassicRetroError(ErrorCode.SOURCE_PATCH_FAILED, "the Huffman codes are not a tree")
    chosen = select_ngrams(corpus.plain, len(NGRAM_CODES), ngram_budget)
    taken = set(charmap.maps.get("compressing", {}))
    spellings = ngram_spellings(corpus.plain, (sequence for sequence, _ in chosen), taken)
    ngrams = {}
    for code, (sequence, _) in zip(NGRAM_CODES, chosen, strict=False):
        names = spellings[sequence]
        if sequence == COMMA_SPACE:
            # The encoder writes the Arabic comma and its space as ", ".
            names = tuple(sorted({*names, ", "}))
        if not names:
            # The sequence's every spelling is a single charmap string already: unused.
            continue
        ngrams[code] = (sequence, names)
    return TextCodes(
        huffman=codes,
        ngrams=ngrams,
        huffman_bits=coded_bits(corpus.huffman, codes),
        ngram_saving=sum(gain for _, gain in chosen),
    )


def _quoted(name: str) -> str:
    return (
        '"'
        + name.replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{").replace("}", "\\}")
        + '"'
    )


def _charmap_line(directive: str, name: str, code: int, bits: str | None = None) -> str:
    line = f"\t{directive} {(_quoted(name) + ','):<12}${code:02x}"
    return line if bits is None else f"{line}, {bits}"


def charmap_asm(
    pristine: str,
    huffman: Mapping[int, str],
    ngrams: Mapping[int, tuple[tuple[int, ...], tuple[str, ...]]] | None = None,
) -> str:
    """``constants/charmap.asm`` for Arabic, from the pinned original.

    ``ngrams`` None keeps the English n-grams ``$0a-$49`` (the gender codes still
    replace ``$4a-$4c``).
    """
    lines = pristine.split("\n")

    def replace_line(old: str, new: str) -> None:
        if lines.count(old) != 1:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"constants/charmap.asm: no single {old!r}"
            )
        lines[lines.index(old)] = new

    replace_line(
        "; characters $4d-$5c correspond to leaf nodes $ec-$fb",
        "; characters $4a-$5c correspond to leaf nodes $ec-$fe",
    )
    replace_line("DEF FIRST_SHIFTED_LEAF_CHAR_ID EQU $4d", "DEF FIRST_SHIFTED_LEAF_CHAR_ID EQU $4a")
    # The presentation forms (and the Arabic comma and question mark the keyboards
    # type) in the base charmap, before the n-grams.
    at = lines.index("DEF NGRAMS_START EQU $0a")
    lines[at:at] = [*charmap_lines(), *_ARABIC_PUNCTUATION_LINES, ""]
    # The gender codes, first of the compressing charmap's leaves.
    at = lines.index('\tctxtmap "#",        $4d, ' + _bits_of(lines, '"#"'))
    gender = [
        _charmap_line("ctxtmap", name, code, huffman.get(code, "0"))
        for name, code in GENDER_CODES.items()
    ]
    lines[at:at] = ["\t; gender alternatives: <GM>masculine<GF>feminine<GE>", *gender]
    # The static n-grams of the default charmap.
    first = next(
        index
        for index, line in enumerate(lines)
        if (m := _NGRAM_CHARMAP.match(line)) and int(m.group(2), 16) == 0x0A
    )
    last = max(
        index
        for index, line in enumerate(lines)
        if (m := _NGRAM_CHARMAP.match(line)) and 0x0A <= int(m.group(2), 16) <= 0x4C
    )
    block = lines[first : last + 1]
    if ngrams is None:
        new_block = [
            line
            for line in block
            if not (
                (m := _NGRAM_CHARMAP.match(line)) and int(m.group(2), 16) in REPLACED_NGRAM_CODES
            )
        ]
    else:
        new_block = [
            _charmap_line("charmap", name, code)
            for code, (_, names) in sorted(ngrams.items())
            for name in names
        ]
    lines[first : last + 1] = new_block
    # Every leaf's trained code.
    out = []
    for line in lines:
        match = _CTXTMAP.match(line)
        if match:
            code = int(match.group(4), 16)
            if code not in huffman:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_PATCH_FAILED, f"no Huffman code for ${code:02x}"
                )
            line = (
                f"{match.group(1)}{match.group(2)}{match.group(3)}${code:02x}"
                f"{match.group(5)}{huffman[code]}{match.group(7)}"
            )
        out.append(line)
    return "\n".join(out)


def _bits_of(lines: Sequence[str], quoted: str) -> str:
    for line in lines:
        match = _CTXTMAP.match(line)
        if match and match.group(2) == quoted:
            return match.group(6)
    raise ClassicRetroError(
        ErrorCode.SOURCE_BASELINE_MISMATCH, f"constants/charmap.asm: no {quoted}"
    )


_DR = re.compile(r"^\tdr (\.\S+)$")
_GENDER_STRING = '{label}:   rawchar "@" ; <GM>/<GF>/<GE> are not n-grams'


def ngrams_asm(
    text: str, ngrams: Mapping[int, tuple[tuple[int, ...], tuple[str, ...]]] | None = None
) -> str:
    """``data/text/ngrams.asm`` with the trained n-grams, over the original line for line.

    The table's ``dr`` lines name the strings in code order from ``$0a``; each
    n-gram's ``dr`` line and string line are rewritten in place, so the other
    lines (the ``#`` and ``#mon`` strings the translation writes) keep their
    numbers. ``ngrams`` None keeps the English n-grams.
    """
    lines = text.split("\n")
    start = lines.index("NgramStrings:")
    drs = [index for index in range(start, len(lines)) if _DR.match(lines[index])]
    if len(drs) < len(NGRAM_CODES) + len(REPLACED_NGRAM_CODES):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "data/text/ngrams.asm: no table"
        )

    def string_line(label: str) -> int:
        found = [
            index for index, line in enumerate(lines) if re.match(re.escape(label) + r":\s", line)
        ]
        if len(found) != 1:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"data/text/ngrams.asm: no single {label}"
            )
        return found[0]

    for code in REPLACED_NGRAM_CODES:
        label = _DR.match(lines[drs[code - 0x0A]]).group(1)  # type: ignore[union-attr]
        lines[string_line(label)] = _GENDER_STRING.format(label=label)
    if ngrams is not None:
        for code in NGRAM_CODES:
            index = drs[code - 0x0A]
            label = _DR.match(lines[index]).group(1)  # type: ignore[union-attr]
            at = string_line(label)
            new_label = f".ngram{code:02x}"
            lines[index] = f"\tdr {new_label}"
            if code in ngrams:
                sequence, _ = ngrams[code]
                body = ", ".join(f"${value:02x}" for value in sequence)
                lines[at] = f'{new_label}: db {body}, "@"'
            else:
                lines[at] = f'{new_label}: db "@" ; unused'
    return "\n".join(lines)


def ngram_string_bytes(text: str, charmap: Charmap) -> int:
    """ROM0 bytes the original's static n-gram strings take (``$0a-$49``), terminators included."""
    lines = text.split("\n")
    start = lines.index("NgramStrings:")
    drs = [index for index in range(start, len(lines)) if _DR.match(lines[index])]
    total = 0
    for code in NGRAM_CODES:
        label = _DR.match(lines[drs[code - 0x0A]]).group(1)  # type: ignore[union-attr]
        for line in lines:
            if re.match(re.escape(label) + r":\s", line):
                for literal in _literals(line):
                    total += len(charmap.tokenize(literal, "no_ngrams"))
    return total


def codes_json(codes: TextCodes) -> str:
    """The trained codes, for the prepare report's folder (reviewable, no text)."""
    return json.dumps(
        {
            "huffman": {f"{code:02x}": bits for code, bits in sorted(codes.huffman.items())},
            "ngrams": {
                f"{code:02x}": [f"{value:02x}" for value in sequence]
                for code, (sequence, _) in sorted(codes.ngrams.items())
            },
        },
        indent=1,
    )


__all__ = [
    "GENDER_CODES",
    "LEAVES",
    "Corpus",
    "TextCodes",
    "charmap_asm",
    "gather",
    "ngram_string_bytes",
    "ngrams_asm",
    "select_ngrams",
    "train",
]
