"""Letters, contextual forms, glyph codes and the shaper of the Polished Crystal font.

Each Arabic letter has up to four contextual forms (isolated, final, initial,
medial). An 8x8 cell cannot tell many of them apart, so several forms share one
hand-drawn glyph (``glyphs.GLYPHS``): beh's isolated and final forms are one
glyph, its initial and medial forms another. 70 glyphs cover the 36 letters and
the four lam-alef ligatures; they take the 70 codes the Latin letters, the
contractions and the accented letters held in the English font
(``FREE_CODES``), in the order of ``GLYPHS``.

The translation is written in logical Arabic letters. ``shape`` turns it into
presentation forms (U+FE70-U+FEFC), which the charmap maps to the glyph codes;
the game's right-to-left renderer draws them from the right. Letters join by
their Unicode joining type: dual-joining letters join both neighbours,
right-joining letters only the letter before them, and the hamza neither.
"""

from __future__ import annotations

import unicodedata

from classic_retro.engines.pokemon_gen2_arabic.glyphs import GLYPHS

# Joining type of every letter the font draws: D dual, R right, U none.
JOINING: dict[str, str] = {
    **dict.fromkeys("بتثنيئجحخسشصضطظعغفقكلمه", "D"),
    **dict.fromkeys("اأإآدذرزوؤةى", "R"),
    "ء": "U",
}

# The four forms a letter has: isolated, final, initial, medial.
FORMS = ("i", "f", "n", "m")


def _forms(
    isolated: str, final: str | None = None, initial: str | None = None, medial: str | None = None
) -> dict[str, str]:
    """The glyph of each form; a form not given takes the isolated (or initial) one."""
    final = final or isolated
    initial = initial or isolated
    return {"i": isolated, "f": final, "n": initial, "m": medial or initial}


# Letter -> form -> glyph name. Several forms may share a glyph.
GLYPH_OF_FORM: dict[str, dict[str, str]] = {
    "ا": _forms("alef.i", "alef.f"),
    "أ": _forms("alefhamza"),
    "إ": _forms("alefhamzabelow"),
    "آ": _forms("alefmadda"),
    "د": _forms("dal"),
    "ذ": _forms("thal"),
    "ر": _forms("reh"),
    "ز": _forms("zain"),
    "و": _forms("waw"),
    "ؤ": _forms("wawhamza"),
    "ة": _forms("tehmarbuta"),
    "ى": _forms("alefmaksura", "alefmaksura.f"),
    "ء": _forms("hamza"),
    "ب": _forms("beh.if", "beh.if", "beh.im"),
    "ت": _forms("teh.if", "teh.if", "teh.im"),
    "ث": _forms("theh.if", "theh.if", "theh.im"),
    "ن": _forms("noon.if", "noon.if", "noon.im"),
    "ي": _forms("yeh.if", "yeh.if", "yeh.im"),
    "ئ": _forms("yehhamza.if", "yehhamza.if", "yehhamza.im"),
    "ج": _forms("jeem.if", "jeem.if", "jeem.im"),
    "ح": _forms("hah.if", "hah.if", "hah.im"),
    "خ": _forms("khah.if", "khah.if", "khah.im"),
    "س": _forms("seen.if", "seen.if", "seen.im"),
    "ش": _forms("sheen.if", "sheen.if", "sheen.im"),
    "ص": _forms("sad.if", "sad.if", "sad.im"),
    "ض": _forms("dad.if", "dad.if", "dad.im"),
    "ط": _forms("tah.if", "tah.if", "tah"),
    "ظ": _forms("zah.if", "zah.if", "zah"),
    "ع": _forms("ain.if", "ain.if", "ain.i", "ain.m"),
    "غ": _forms("ghain.if", "ghain.if", "ghain.i", "ghain.m"),
    "ف": _forms("feh.if", "feh.if", "feh.im"),
    "ق": _forms("qaf.if", "qaf.if", "qaf.im"),
    "ك": _forms("kaf.if", "kaf.if", "kaf.im"),
    "ل": _forms("lam.if", "lam.if", "lam.im"),
    "م": _forms("meem.if", "meem.if", "meem.im"),
    "ه": _forms("heh.i", "heh.f", "heh.in", "heh.m"),
}

# Alef after lam -> (isolated glyph, final glyph, isolated code point, final code point).
LAMALEF: dict[str, tuple[str, str, int, int]] = {
    "ا": ("lamalef", "lamalef.f", 0xFEFB, 0xFEFC),
    "أ": ("lamalefhamza", "lamalefhamza", 0xFEF7, 0xFEF8),
    "إ": ("lamalefhamzabelow", "lamalefhamzabelow", 0xFEF9, 0xFEFA),
    "آ": ("lamalefmadda", "lamalefmadda", 0xFEF5, 0xFEF6),
}

_FORM_NAMES = {"i": "ISOLATED", "f": "FINAL", "n": "INITIAL", "m": "MEDIAL"}


def presentation(letter: str, form: str) -> str:
    """The presentation form (U+FE70-U+FEFC) of ``letter`` in ``form`` (i, f, n or m)."""
    name = unicodedata.name(letter).replace("ARABIC LETTER ", "")
    return unicodedata.lookup(f"ARABIC LETTER {name} {_FORM_NAMES[form]} FORM")


def _presentation_glyphs() -> dict[str, str]:
    glyphs: dict[str, str] = {}
    for letter, forms in GLYPH_OF_FORM.items():
        for form, glyph in forms.items():
            if JOINING[letter] != "D" and form in "nm":
                continue
            if JOINING[letter] == "U" and form != "i":
                continue
            glyphs[presentation(letter, form)] = glyph
    for isolated, final, isolated_point, final_point in LAMALEF.values():
        glyphs[chr(isolated_point)] = isolated
        glyphs[chr(final_point)] = final
    return glyphs


# Every presentation form the shaper writes -> its glyph name.
PRESENTATION_GLYPH: dict[str, str] = _presentation_glyphs()

# The glyphs the forms use, in the order of GLYPHS (which gives their codes).
ARABIC_GLYPHS: tuple[str, ...] = tuple(
    sorted(set(PRESENTATION_GLYPH.values()), key=list(GLYPHS).index)
)

# The codes the Latin letters ($80-$99, $a0-$b9), the contractions and the
# accented letters ($c0-$d1) held in the English font.
FREE_CODES: tuple[int, ...] = (*range(0x80, 0x9A), *range(0xA0, 0xBA), *range(0xC0, 0xD2))


def _assign_codes() -> dict[str, int]:
    if len(ARABIC_GLYPHS) > len(FREE_CODES):
        raise ValueError(f"{len(ARABIC_GLYPHS)} glyphs, {len(FREE_CODES)} codes")
    return dict(zip(ARABIC_GLYPHS, FREE_CODES, strict=False))


# Glyph name -> its character code in the game's font.
CODES: dict[str, int] = _assign_codes()

# Punctuation the translation may use -> the game's character it is written as.
PUNCTUATION: dict[str, str] = {
    "،": ",",
    "؟": "?",
    "؛": ";",
    "«": "“",
    "»": "“",
    '"': "“",
    "٫": ".",
}
# Arabic-Indic digits are written as the game's digits.
DIGITS: dict[str, str] = {chr(0x660 + value): str(value) for value in range(10)}


def shape(text: str, ligatures: bool = True) -> str:
    """Logical Arabic -> presentation forms; other characters kept (mapped as above).

    With ``ligatures`` a lam before an alef becomes one lam-alef glyph, as the
    build writes the translation; the naming screen's runtime shaper has no
    ligatures, so names are shaped with ``ligatures=False``.
    """
    out = []
    chars = list(text)
    index = 0
    while index < len(chars):
        char = chars[index]
        if char not in JOINING:
            out.append(DIGITS.get(char, PUNCTUATION.get(char, char)))
            index += 1
            continue
        joined_before = index > 0 and JOINING.get(chars[index - 1]) == "D"
        if ligatures and char == "ل" and index + 1 < len(chars) and chars[index + 1] in LAMALEF:
            _, _, isolated_point, final_point = LAMALEF[chars[index + 1]]
            out.append(chr(final_point if joined_before else isolated_point))
            index += 2
            continue
        joins_after = (
            JOINING[char] == "D"
            and index + 1 < len(chars)
            and JOINING.get(chars[index + 1]) in ("D", "R")
        )
        if joined_before and joins_after:
            form = "m"
        elif joined_before:
            form = "f"
        elif joins_after:
            form = "n"
        else:
            form = "i"
        if JOINING[char] == "U":
            form = "i"
        out.append(presentation(char, form))
        index += 1
    return "".join(out)


def glyph_code(char: str) -> int | None:
    """The font code of a presentation form, or None for any other character."""
    glyph = PRESENTATION_GLYPH.get(char)
    return None if glyph is None else CODES[glyph]


DIGIT_CODES = range(0xE0, 0xEA)


def visual_codes(text: str, symbols: dict[str, int]) -> list[int]:
    """A logical line as glyph codes in visual order, leftmost first.

    For text the game copies as it is (the Pokédex's tilemaps): the line is
    shaped, turned into codes (``symbols`` gives the codes of everything but the
    Arabic forms) and reversed, runs of digits kept left to right. A line with
    no Arabic letter (a placeholder such as ``??.?``) is kept as it is.
    """
    out = []
    for char in shape(text):
        code = glyph_code(char)
        if code is None:
            if char not in symbols:
                raise ValueError(f"{text!r}: no glyph for {char!r}")
            code = symbols[char]
        out.append(code)
    if not any(char in JOINING for char in text):
        return out
    visual: list[int] = []
    end = len(out)
    while end > 0:
        start = end
        while start > 0 and out[start - 1] in DIGIT_CODES:
            start -= 1
        if start < end:
            visual += out[start:end]
            end = start
        else:
            visual.append(out[end - 1])
            end -= 1
    return visual


def charmap_lines() -> list[str]:
    """The charmap lines that map every presentation form to its glyph's code."""
    lines = ["; Arabic presentation forms (logical order; the renderer draws right to left)"]
    for char, glyph in sorted(PRESENTATION_GLYPH.items()):
        lines.append(f'\tcharmap "{char}", ${CODES[glyph]:02x} ; {glyph}')
    return lines
