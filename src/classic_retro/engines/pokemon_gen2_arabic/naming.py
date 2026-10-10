"""The Arabic text input of Polished Crystal: shaping tables, keyboards, the key phrase.

The naming screen and the mail composer type isolated letters; the engine's
``ShapeArabicName`` (``engine/menus/arabic_shaping.asm``) gives each letter the
form its neighbours call for, in place, from two tables written here
(``shaping_asm``): the letter each glyph code belongs to, and the four forms of
each letter. ``runtime_shape`` models that routine; ``self_test`` checks it
against the build-time shaper (``forms.shape`` without ligatures, as names have
none) over every string of up to three characters and random longer ones, so a
name typed in the game is stored byte for byte as the build writes names.

``keyboards_asm`` writes the four keyboards (names and mail, letters and
symbols), and ``key_phrase_asm`` the trendy phrase the game checks for, shaped
as the naming screen stores it. The symbols come from the tree's charmap.
"""

from __future__ import annotations

import itertools
import random
import re
from collections.abc import Mapping, Sequence

from classic_retro.engines.pokemon_gen2_arabic.forms import (
    CODES,
    GLYPH_OF_FORM,
    JOINING,
    PRESENTATION_GLYPH,
    presentation,
    shape,
)

# 28 letters in hija'i order, then the hamza and alef variants, teh marbuta and alef maksura.
LETTERS_HIJAI = list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي") + list("ءآأإؤئىة")

# Runtime table order: dual-joining letters first (so "joins the next letter" is
# index < NUM_DUAL), then the right-joining ones, then the non-joining hamza.
LETTER_ORDER = (
    [char for char in LETTERS_HIJAI if JOINING[char] == "D"]
    + [char for char in LETTERS_HIJAI if JOINING[char] == "R"]
    + [char for char in LETTERS_HIJAI if JOINING[char] == "U"]
)
NUM_DUAL = sum(1 for char in LETTER_ORDER if JOINING[char] == "D")
NUM_LETTERS = len(LETTER_ORDER)


def _glyph_code(letter: str, form: str) -> int:
    return CODES[GLYPH_OF_FORM[letter][form]]


def letter_forms(letter: str) -> list[int]:
    """[isolated, final, initial, medial] codes of a letter.

    A right-joining letter never joins the next one (initial = isolated,
    medial = final); the hamza has one form.
    """
    joining = JOINING[letter]
    isolated = _glyph_code(letter, "i")
    if joining == "U":
        return [isolated] * 4
    final = _glyph_code(letter, "f")
    if joining == "R":
        return [isolated, final, isolated, final]
    return [isolated, final, _glyph_code(letter, "n"), _glyph_code(letter, "m")]


FORM_CODES = [letter_forms(char) for char in LETTER_ORDER]
ISOLATED = {char: FORM_CODES[index][0] for index, char in enumerate(LETTER_ORDER)}


def _letter_of_glyph() -> dict[int, int]:
    # Every glyph a letter uses must belong to that letter only: the keyboard
    # types isolated forms and the shaper finds the letter of any form it meets,
    # so shaping in place is idempotent.
    letter_of: dict[int, int] = {}
    for index, codes in enumerate(FORM_CODES):
        for code in codes:
            other = letter_of.setdefault(code, index)
            if other != index:
                raise ValueError(
                    f"glyph ${code:02x} is shared by {LETTER_ORDER[other]} and {LETTER_ORDER[index]}"
                )
    if len(set(ISOLATED.values())) != NUM_LETTERS:
        raise ValueError("isolated forms must be unique per letter")
    return letter_of


LETTER_OF_GLYPH = _letter_of_glyph()
FIRST_GLYPH = min(CODES.values())
LAST_GLYPH = max(LETTER_OF_GLYPH)
GLYPH_RANGE = LAST_GLYPH - FIRST_GLYPH + 1
NOT_A_LETTER = 0xFF
# Whether a dual-joining letter takes its initial or medial form before a
# hamza: whatever the build-time shaper does, so both always agree.
HAMZA_JOINS = shape("بء", ligatures=False)[0] == presentation("ب", "n")
NUM_JOINABLE = NUM_LETTERS if HAMZA_JOINS else NUM_LETTERS - 1

SPACE = "␣"
NAME_COLUMNS, NAME_ROWS = 9, 5
MAIL_COLUMNS, MAIL_ROWS = 10, 5
# Rows are written in reading order: "rtl" rows from the rightmost cell, "ltr"
# rows from the leftmost. The tables hold the cells left to right.
KEYBOARDS: tuple[tuple[str, str, int, tuple[tuple[str, str], ...]], ...] = (
    (
        "NameInputLetters",
        "names, page 1: the letters, alef in the top right corner",
        NAME_COLUMNS,
        (
            ("rtl", "ا ب ت ث ج ح خ د ذ"),
            ("rtl", "ر ز س ش ص ض ط ظ ع"),
            ("rtl", "غ ف ق ك ل م ن ه و"),
            ("rtl", "ي ى ة ء أ إ آ ؤ ئ"),
            ("rtl", "␣ ، ؟ ! . - : … “"),
        ),
    ),
    (
        "NameInputSymbols",
        "names, page 2: digits and symbols",
        NAME_COLUMNS,
        (
            ("ltr", "1 2 3 4 5 6 7 8 9"),
            ("ltr", "0 . : - + × / % ¥"),
            ("rtl", "، ؟ ! … “ & <SHARP> № ★"),
            ("rtl", "♥ ♪ ♂ ♀ <PK> <MN> ␣ ␣ ␣"),
            ("rtl", "␣ ␣ ␣ ␣ ␣ ␣ ␣ ␣ ␣"),
        ),
    ),
    (
        "MailInputLetters",
        "mail, page 1: the letters, alef in the top right corner",
        MAIL_COLUMNS,
        (
            ("rtl", "ا ب ت ث ج ح خ د ذ ر"),
            ("rtl", "ز س ش ص ض ط ظ ع غ ف"),
            ("rtl", "ق ك ل م ن ه و ي ى ة"),
            ("rtl", "ء أ إ آ ؤ ئ ، . ؟ !"),
            ("rtl", "␣ - : … “ ♥ ♪ ★ & /"),
        ),
    ),
    (
        "MailInputSymbols",
        "mail, page 2: digits and symbols",
        MAIL_COLUMNS,
        (
            ("ltr", "1 2 3 4 5 6 7 8 9 0"),
            ("ltr", ". : - + × / % ¥ <SHARP> №"),
            ("rtl", "، ؟ ! … “ & ★ ♥ ♪ ♂"),
            ("rtl", "♀ <PK> <MN> ↑ ↓ ␣ ␣ ␣ ␣ ␣"),
            ("rtl", "␣ ␣ ␣ ␣ ␣ ␣ ␣ ␣ ␣ ␣"),
        ),
    ),
)

# Codes a typed name may hold: the 7-bit box encoding keeps $80-$f9 (and space).
NAME_OK = frozenset({*range(0x80, 0xFA), 0x7F})
# Mail crosses the link cable: $21 stands in for $fe, $fd-$ff frame it.
MAIL_BAD = frozenset({0x21, 0xFD, 0xFE, 0xFF})
TERMINATOR = 0x53  # "@"
PLAYER_NAME_LENGTH = 8  # constants/text_constants.asm

_CHARMAP_LINE = re.compile(
    r'^\s*(?:charmap|ctxtmap)\s+"((?:[^"\\]|\\.)*)"\s*,\s*\$([0-9a-fA-F]{2})\b'
)
HEADER = (
    "; Generated by gen_arabic_input.py from fontwork/pc_arabic.py; do not edit.\n"
    "; Edit and rerun the generator instead.\n"
)


def no_ngrams_charmap(charmap_asm: str) -> dict[str, int]:
    """The ``no_ngrams`` charmap of ``constants/charmap.asm`` (what ``rawchar`` uses)."""
    charmap: dict[str, int] = {}
    active = False
    for line in charmap_asm.splitlines(keepends=True):
        if "newcharmap no_ngrams" in line:
            active = True
        elif active and "newcharmap" in line:
            break
        if active and (match := _CHARMAP_LINE.match(line)):
            charmap.setdefault(match.group(1), int(match.group(2), 16))
    return charmap


def _token_code(token: str, charmap: Mapping[str, int]) -> int:
    if token == SPACE:
        return charmap[" "]
    if token in ISOLATED:
        return ISOLATED[token]
    if token not in charmap:
        raise ValueError(f"keyboard symbol {token!r} is not in the charmap")
    return charmap[token]


def build_keyboard(
    name: str, columns: int, rows: Sequence[tuple[str, str]], charmap: Mapping[str, int]
) -> list[list[tuple[str, int]]]:
    """The keyboard's cells, left to right, as (token, code)."""
    cells = []
    for direction, row in rows:
        tokens = row.split()
        if len(tokens) != columns:
            raise ValueError(f"{name}: row {tokens} has {len(tokens)} cells, not {columns}")
        if direction == "rtl":
            tokens = tokens[::-1]
        cells.append([(token, _token_code(token, charmap)) for token in tokens])
    codes = [code for row in cells for _, code in row]
    if name.startswith("Name"):
        bad = [f"${code:02x}" for code in codes if code not in NAME_OK]
        if bad:
            raise ValueError(f"{name}: codes not allowed in names: {bad}")
    bad = [f"${code:02x}" for code in codes if code in MAIL_BAD]
    if bad:
        raise ValueError(f"{name}: codes not allowed in mail: {bad}")
    return cells


def runtime_shape(codes: Sequence[int]) -> list[int]:
    """What ShapeArabicName does to a ``@``-terminated byte string, in place."""
    out = list(codes)
    joined = 0
    for index, code in enumerate(out):
        if code == TERMINATOR:
            break
        letter = LETTER_OF_GLYPH.get(code)
        if letter is None:
            joined = 0
            continue
        following = out[index + 1] if index + 1 < len(out) else TERMINATOR
        next_letter = LETTER_OF_GLYPH.get(following)
        joins = next_letter is not None and next_letter < NUM_JOINABLE
        out[index] = FORM_CODES[letter][joined | (2 if joins else 0)]
        joined = 1 if letter < NUM_DUAL else 0
    return out


def build_time_codes(text: str, charmap: Mapping[str, int]) -> list[int]:
    """``shape(text, ligatures=False)`` as glyph codes."""
    out = []
    for char in shape(text, ligatures=False):
        glyph = PRESENTATION_GLYPH.get(char)
        out.append(CODES[glyph] if glyph is not None else charmap[char])
    return out


def typed_codes(text: str, charmap: Mapping[str, int]) -> list[int]:
    """What the keyboard types for ``text``: isolated forms."""
    return [ISOLATED[char] if char in ISOLATED else charmap[char] for char in text]


def check_runtime_shaper(text: str, charmap: Mapping[str, int]) -> None:
    """The runtime shaper gives ``text`` the build's forms, and shaping again changes nothing."""
    want = build_time_codes(text, charmap)
    got = runtime_shape([*typed_codes(text, charmap), TERMINATOR])[:-1]
    if got != want:
        raise ValueError(
            f"runtime shaper differs from the build's shaper on {text!r}: "
            f"{' '.join(f'{c:02x}' for c in got)} != {' '.join(f'{c:02x}' for c in want)}"
        )
    if runtime_shape([*got, TERMINATOR])[:-1] != got:
        raise ValueError(f"shaping {text!r} again changes it")


def self_test(
    charmap: Mapping[str, int], *, length: int = 3, samples: int = 20000, seed: int = 42
) -> int:
    """Check the runtime shaper on every string of up to ``length`` characters and samples."""
    alphabet = [*LETTER_ORDER, " ", "!", "."]
    checked = 0
    for size in range(1, length + 1):
        for chars in itertools.product(alphabet, repeat=size):
            check_runtime_shaper("".join(chars), charmap)
            checked += 1
    generator = random.Random(seed)
    for _ in range(samples):
        text = "".join(generator.choice(alphabet) for _ in range(generator.randint(4, 16)))
        check_runtime_shaper(text, charmap)
        checked += 1
    for text in ("ليلى", "محمد", "سارة", "شيء", "مسؤول", "هيئة"):
        check_runtime_shaper(text, charmap)
        checked += 1
    return checked


def _hexlist(codes: Sequence[int]) -> str:
    return ", ".join(f"${code:02x}" for code in codes)


def shaping_asm() -> str:
    """``data/text/arabic_shaping.asm``: the tables of ShapeArabicName."""
    joinable = f"letters 0-{NUM_JOINABLE - 1} join a dual-joining letter before them"
    lines = [
        HEADER,
        "; Tables of ShapeArabicName (engine/menus/arabic_shaping.asm).",
        "",
        f"DEF ARABIC_FIRST_GLYPH EQU ${FIRST_GLYPH:02x}",
        f"DEF ARABIC_GLYPH_RANGE EQU ${GLYPH_RANGE:02x} ; glyphs "
        f"${FIRST_GLYPH:02x}-${LAST_GLYPH:02x} may be letters",
        f"DEF NUM_ARABIC_LETTERS EQU {NUM_LETTERS}",
        f"DEF NUM_ARABIC_DUAL_JOINING EQU {NUM_DUAL} ; letters 0-{NUM_DUAL - 1} join the next letter",
        f"DEF NUM_ARABIC_JOINABLE EQU {NUM_JOINABLE} ; {joinable}"
        + ("" if HAMZA_JOINS else " (not the hamza)"),
        "; ArabicForms columns: isolated, final (joined before), initial (joins after), medial",
        "DEF ARABIC_FORM_FINAL EQU 1",
        "DEF ARABIC_FORM_INITIAL EQU 2",
        "",
        "ArabicLetterOfGlyph:",
        f"; the letter (index into ArabicForms) of each glyph ${FIRST_GLYPH:02x}-"
        f"${LAST_GLYPH:02x}, or ${NOT_A_LETTER:02x}",
        "\ttable_width 1",
    ]
    for base in range(FIRST_GLYPH, LAST_GLYPH + 1, 8):
        row = [
            LETTER_OF_GLYPH.get(code, NOT_A_LETTER)
            for code in range(base, min(base + 8, LAST_GLYPH + 1))
        ]
        lines.append(f"\tdb {_hexlist(row)} ; ${base:02x}")
    lines += [
        "\tassert_table_length ARABIC_GLYPH_RANGE",
        "",
        "ArabicForms:",
        "; isolated, final, initial, medial glyph of each letter",
        "\ttable_width 4",
    ]
    kinds = {"D": "dual", "R": "right", "U": "none"}
    for index, char in enumerate(LETTER_ORDER):
        lines.append(
            f"\tdb {_hexlist(FORM_CODES[index])} ; {index:2d} {char} ({kinds[JOINING[char]]})"
        )
    lines += ["\tassert_table_length NUM_ARABIC_LETTERS", ""]
    return "\n".join(lines)


def keyboards_asm(charmap: Mapping[str, int]) -> str:
    """``data/text/input_chars.asm``: the keyboards of the naming screen and mail composer."""
    lines = [
        HEADER,
        "; Keyboards of the naming screen and mail composer (engine/menus/naming_screen.asm).",
        "; The cells are written into the tilemap one by one (not reversed), left to right;",
        "; the letters are isolated forms, which ShapeArabicName joins as they are typed.",
        '; Both settings of the "Keyboard" option use these tables.',
        "",
        f"DEF NAME_INPUT_COLUMNS EQU {NAME_COLUMNS}",
        f"DEF NAME_INPUT_ROWS EQU {NAME_ROWS}",
        f"DEF MAIL_INPUT_COLUMNS EQU {MAIL_COLUMNS}",
        f"DEF MAIL_INPUT_ROWS EQU {MAIL_ROWS}",
        "",
    ]
    for name, description, columns, rows in KEYBOARDS:
        cells = build_keyboard(name, columns, rows, charmap)
        lines += [f"{name}:", f"; {description}", "\ttable_width 1"]
        for row in cells:
            shown = " ".join("sp" if token == SPACE else token for token, _ in row)
            lines.append(f"\tdb {_hexlist([code for _, code in row])} ; {shown}")
        prefix = "NAME" if name.startswith("Name") else "MAIL"
        lines += [f"\tassert_table_length {prefix}_INPUT_COLUMNS * {prefix}_INPUT_ROWS", ""]
    return "\n".join(lines)


def key_phrase_codes(phrase: str, charmap: Mapping[str, int]) -> list[int]:
    """The trendy phrase as the naming screen stores it: shaped without lam-alef."""
    codes = build_time_codes(phrase, charmap)
    if codes != runtime_shape([*typed_codes(phrase, charmap), TERMINATOR])[:-1]:
        raise ValueError(f"the runtime shaper stores {phrase!r} differently")
    if len(codes) > PLAYER_NAME_LENGTH - 1:
        raise ValueError(
            f"the key phrase must fit a trendy phrase ({PLAYER_NAME_LENGTH - 1} glyphs)"
        )
    if not all(code in NAME_OK for code in codes):
        raise ValueError("the key phrase holds a code a name cannot")
    return codes


def key_phrase_asm(phrase: str, charmap: Mapping[str, int]) -> str:
    """``data/text/lucky_key_phrase.asm``: the phrase CheckIfTrendyPhraseIsLucky accepts."""
    codes = key_phrase_codes(phrase, charmap)
    return "\n".join(
        [
            HEADER,
            f"; The trendy phrase CheckIfTrendyPhraseIsLucky accepts: {phrase}, shaped as the",
            "; naming screen stores it (no lam-alef ligature), with its terminator.",
            f'\tdb {_hexlist(codes)}, "@"',
            "",
        ]
    )
