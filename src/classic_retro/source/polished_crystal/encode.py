"""Encode an Arabic translation, in the overlay's notation, into RGBDS source lines.

    encode(entry, arabic_text, ngrams=None) -> list[str]   replacement lines for entry['start']..entry['end']
    check(entry, arabic_text, ngrams=None)  -> list[str]   problems (empty list = OK)

`entry` is one record of the manifest (``manifest.expand``).  The encoder never
needs the English: everything structural (macro names, indentation, label
prefixes, terminators, frames) is in entry['fmt'].

Notation (what translators write):
  * logical Arabic letters, no harakat / tatweel / presentation forms;
  * punctuation  space . ، ؛ ؟ ! : - … « » " “ ”  digits 0-9 ٠-٩  / × % + ¥ ♂ ♀ & ♪ ♥
    (ASCII , ? ; are accepted as ، ؟ ؛);
  * \\p new paragraph (dialog), \\f new page (multi-page boxes), \\n forced line break;
  * placeholders {PLAYER} {RIVAL} {TRENDY} {USER} {TARGET} {ENEMY} {ram:SYM}
    {num:SYM,BYTES,DIGITS} {wait} {pause} {sound:SFX} {day} {far:LABEL} {d:CONST}
    {LV} {PK} {MN} {ID} {No};
  * gender alternatives {masculine|feminine} (letters, spaces, punctuation only).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from classic_retro.engines.pokemon_gen2_arabic import forms as AR

# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

LETTERS = set("ءآأؤإئابةتثجحخدذرزسشصضطظعغفقكلمنهوىي")
assert LETTERS == set(AR.JOINING), "the notation's letters are the font's"

# notation punctuation -> character written into the RGBDS literal
PUNCT = {
    " ": " ",
    ".": ".",
    "!": "!",
    ":": ":",
    "-": "-",
    "…": "…",
    "،": ",",
    ",": ",",
    "؛": ",",
    ";": ",",
    "؟": "?",
    "?": "?",
    "«": "“",
    "»": "“",
    '"': "“",
    "“": "“",
    "”": "“",
    "/": "/",
    "×": "×",
    "%": "%",
    "٪": "%",
    "+": "+",
    "¥": "¥",
    "♂": "♂",
    "♀": "♀",
    "&": "&",
    "♪": "♪",
    "♥": "♥",
}
for _i in range(10):
    PUNCT[str(_i)] = str(_i)
    PUNCT[chr(0x660 + _i)] = str(_i)

HARAKAT = set(chr(c) for c in range(0x64B, 0x660)) | {"ٰ", "ـ"}

# placeholder name -> (in-string code or None for commands, default cell width)
IN_STRING = {
    "PLAYER": "<PLAYER>",
    "RIVAL": "<RIVAL>",
    "TRENDY": "<TRENDY>",
    "USER": "<USER>",
    "TARGET": "<TARGET>",
    "ENEMY": "<ENEMY>",
    "LV": "<LV>",
    "PK": "<PK>",
    "MN": "<MN>",
    "ID": "<ID>",
    "No": "№",
}
PH_WIDTH = {
    "PLAYER": 7,
    "RIVAL": 7,
    "TRENDY": 7,
    # nickname (<=10) + the word for the foe the engine adds after it
    "USER": 16,
    "TARGET": 16,
    # trainer class (<=12) + " " + name (<=10) = 23 > 18: always a row of its own
    "ENEMY": 18,
    "LV": 1,
    "PK": 1,
    "MN": 1,
    "ID": 1,
    "No": 1,
    "wait": 0,
    "pause": 0,
    "sound": 0,
    "far": 0,
    "day": 8,  # longest Arabic weekday (الأربعاء / الثلاثاء)
}
# text_ram buffers: worst-case content in cells (research 02 §0.2, 03 §2)
RAM_WIDTH = {
    "wPlayerName": 7,
    "wRivalName": 7,
    "wTrendyPhrase": 7,
    "wBackupName": 7,
    "wMomsName": 7,
    "wMagikarpRecordHoldersName": 7,
    "wBattleMonNickname": 10,
    "wEnemyMonNickname": 10,
    "wTempMonNickname": 10,
    "wBufferTrademonNickname": 10,
    "wOTTrademonNickname": 10,
    "wPlayerTrademonNickname": 10,
    "wMonOrItemNameBuffer": 12,
    "wStringBuffer1": 12,
    "wStringBuffer2": 12,
    "wStringBuffer3": 12,
    "wStringBuffer4": 12,
    "wStringBuffer5": 12,
    "wOTClassName": 12,
    "wMoveName": 12,
    "wItemName": 12,
}
RAM_DEFAULT = 12
SPECIAL_WIDTH_DEFAULT = 1
RAW_FORBIDDEN = {"PLAYER", "RIVAL", "TRENDY", "USER", "TARGET", "ENEMY"}

GENDER_CODES = ("<GM>", "<GF>", "<GE>")


def code_of(ch: str):
    """Glyph code of a written character (Arabic presentation forms share codes)."""
    g = AR.PRESENTATION_GLYPH.get(ch)
    if g is not None:
        return AR.CODES[g]
    return ch


# ---------------------------------------------------------------------------
# notation tokenizer
# ---------------------------------------------------------------------------


class Tok:
    __slots__ = ("t", "a", "b", "raw")

    def __init__(self, t, a=None, b=None, raw=""):
        self.t, self.a, self.b, self.raw = t, a, b, raw

    def __repr__(self):
        return f"Tok({self.t!r},{self.a!r},{self.b!r})"


RE_PH = re.compile(
    r"^(?:(PLAYER|RIVAL|TRENDY|USER|TARGET|ENEMY|LV|PK|MN|ID|No|wait|pause|day)"
    r"|(ram):([^{}|,]+)"
    r"|(num):([^,{}|]+?)\s*,\s*([^,{}|]+?)\s*,\s*([^,{}|]+?)"
    r"|(sound):([A-Za-z_]\w*)"
    r"|(far):([A-Za-z_][\w.]*)"
    r"|(d):([^{}|]+))$"
)


def normalize_ph(body: str) -> str | None:
    """Canonical text of a placeholder body, or None if invalid."""
    m = RE_PH.match(body.strip())
    if not m:
        return None
    if m.group(1):
        return "{" + m.group(1) + "}"
    if m.group(2):
        return "{ram:" + " ".join(m.group(3).split()) + "}"
    if m.group(4):
        return "{num:" + ",".join(re.sub(r"\s+", "", m.group(k)) for k in (5, 6, 7)) + "}"
    if m.group(8):
        return "{sound:" + m.group(9) + "}"
    if m.group(10):
        return "{far:" + m.group(11) + "}"
    return "{d:" + " ".join(m.group(13).split()) + "}"


def ph_name(ph: str) -> str:
    body = ph[1:-1]
    return body.split(":", 1)[0]


def tokenize(text: str) -> tuple[list[Tok], list[str]]:
    """Split notation into tokens; returns (tokens, errors)."""
    toks: list[Tok] = []
    errs: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            toks.append(Tok("t", "".join(buf)))
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in "pnf":
            flush()
            toks.append(Tok({"p": "para", "n": "nl", "f": "page"}[text[i + 1]]))
            i += 2
            continue
        if c == "\n":
            flush()
            toks.append(Tok("nl"))
            i += 1
            continue
        if c == "{":
            j = text.find("}", i)
            if j < 0:
                errs.append(f'unclosed "{{" at {i}')
                buf.append(c)
                i += 1
                continue
            body = text[i + 1 : j]
            if "{" in body:
                errs.append(f'nested "{{" at {i}')
            flush()
            if "|" in body:
                parts = body.split("|")
                if len(parts) != 2:
                    errs.append(f"gender alternative must have exactly two sides: {{{body}}}")
                    parts = (parts + ["", ""])[:2]
                toks.append(Tok("alt", parts[0], parts[1], raw=text[i : j + 1]))
            else:
                ph = normalize_ph(body)
                if ph is None:
                    errs.append(f"unknown placeholder {{{body}}}")
                    toks.append(Tok("ph", "{" + body + "}", raw=text[i : j + 1]))
                else:
                    toks.append(Tok("ph", ph, raw=text[i : j + 1]))
            i = j + 1
            continue
        if c == "}":
            errs.append(f'stray "}}" at {i}')
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return toks, errs


def check_chars(s: str, where: str) -> list[str]:
    errs = []
    for ch in s:
        if ch in LETTERS or ch in PUNCT:
            continue
        if ch in HARAKAT:
            errs.append(f"{where}: harakat/tatweel not allowed ({ch!r} U+{ord(ch):04X})")
        elif "ﭐ" <= ch <= "﻿":
            errs.append(f"{where}: presentation form not allowed ({ch!r}); write logical letters")
        elif ch in "()[]":
            errs.append(f"{where}: brackets are not allowed ({ch!r})")
        elif "‎" <= ch <= "‮" or ch in "⁦⁧⁨⁩":
            errs.append(f"{where}: direction control characters are not allowed (U+{ord(ch):04X})")
        elif ch == "\\":
            errs.append(f"{where}: backslash only allowed in \\p \\n \\f")
        elif ch == "@" or ch == "#":
            errs.append(f"{where}: {ch!r} is reserved")
        else:
            errs.append(f"{where}: character not in the font: {ch!r} (U+{ord(ch):04X})")
    return errs


# ---------------------------------------------------------------------------
# shaping with context
# ---------------------------------------------------------------------------


def _pmap(c: str) -> str:
    return PUNCT.get(c, c)


def shape_ctx(text: str, left: str | None = None, right: str | None = None) -> str:
    """Shape `text` (logical) as if `left`/`right` (logical chars or None)
    surround it.  Same rules as ``forms.shape``."""
    chars = list(text)
    out = []
    n = len(chars)
    i = 0
    while i < n:
        c = chars[i]
        if c not in AR.JOINING:
            out.append(_pmap(c))
            i += 1
            continue
        prev = chars[i - 1] if i > 0 else left
        prev_joins = prev is not None and AR.JOINING.get(prev) == "D"
        nxt = chars[i + 1] if i + 1 < n else right
        if c == "ل" and i + 1 < n and chars[i + 1] in AR.LAMALEF:
            iso, fin, ciso, cfin = AR.LAMALEF[chars[i + 1]]
            out.append(chr(cfin if prev_joins else ciso))
            i += 2
            continue
        next_joins = AR.JOINING[c] == "D" and nxt is not None and AR.JOINING.get(nxt) in ("D", "R")
        form = (
            "m" if prev_joins and next_joins else "f" if prev_joins else "n" if next_joins else "i"
        )
        if AR.JOINING[c] == "U":
            form = "i"
        out.append(AR.presentation(c, form))
        i += 1
    return "".join(out)


def _first_letter_ctx(tok_seq: Sequence[Tok], idx: int, step: int) -> str | None:
    """Context character seen from a text run next to tok_seq[idx] in direction step."""
    j = idx
    while 0 <= j < len(tok_seq):
        t = tok_seq[j]
        if t.t == "t":
            return t.a[0] if step > 0 else t.a[-1]
        if t.t == "alt":
            s = t.a if t.a else t.b
            if s:
                return s[0] if step > 0 else s[-1]
            j += step
            continue
        return None
    return None


class Shaped:
    """A paragraph-level token after shaping: text / ph / alt / nl / para / page."""

    __slots__ = ("t", "s", "m", "f", "ph", "w")

    def __init__(self, t, s="", m="", f="", ph="", w=0):
        self.t, self.s, self.m, self.f, self.ph, self.w = t, s, m, f, ph, w

    def __repr__(self):
        return f"Shaped({self.t},{self.s or self.m or self.ph!r},w={self.w})"


def joins_left_of(s: str) -> bool:
    return bool(s) and s[0] in AR.JOINING


def shape_tokens(toks: list[Tok], ph_width) -> tuple[list[Shaped], list[str]]:
    """Shape every text run / alternative with its neighbours as context."""
    errs: list[str] = []
    out: list[Shaped] = []
    for i, t in enumerate(toks):
        if t.t == "t":
            left = _first_letter_ctx(toks, i - 1, -1) if i > 0 else None
            right = _first_letter_ctx(toks, i + 1, +1) if i + 1 < len(toks) else None
            # a lam-alef pair across a boundary cannot be expressed
            if t.a and t.a[-1] == "ل" and right in AR.LAMALEF:
                errs.append(
                    "lam followed by alef across a gender alternative / boundary; write whole words"
                )
            s = shape_ctx(t.a, left, right)
            out.append(Shaped("t", s=s, w=len(s)))
        elif t.t == "alt":
            left = _first_letter_ctx(toks, i - 1, -1) if i > 0 else None
            right = _first_letter_ctx(toks, i + 1, +1) if i + 1 < len(toks) else None
            sides = []
            for side in (t.a, t.b):
                sides.append(shape_ctx(side, left, right))

            # neighbours must be shaped the same way for both sides
            def first_join(side, right=right):
                if side:
                    return AR.JOINING.get(side[0]) in ("D", "R")
                return right is not None and AR.JOINING.get(right) in ("D", "R")

            def last_join(side, left=left):
                if side:
                    return AR.JOINING.get(side[-1]) == "D"
                return left is not None and AR.JOINING.get(left) == "D"

            if (
                left is not None
                and AR.JOINING.get(left) == "D"
                and first_join(t.a) != first_join(t.b)
            ):
                errs.append(
                    f"gender alternative {t.raw} changes the form of the letter before it; "
                    "put whole words inside {…|…}"
                )
            if (
                right is not None
                and AR.JOINING.get(right) in ("D", "R")
                and last_join(t.a) != last_join(t.b)
            ):
                errs.append(
                    f"gender alternative {t.raw} changes the form of the letter after it; "
                    "put whole words inside {…|…}"
                )
            if left == "ل" and ((t.a and t.a[0] in AR.LAMALEF) or (t.b and t.b[0] in AR.LAMALEF)):
                errs.append(f"lam-alef split by gender alternative {t.raw}")
            out.append(Shaped("alt", m=sides[0], f=sides[1], w=max(len(sides[0]), len(sides[1]))))
        elif t.t == "ph":
            out.append(Shaped("ph", ph=t.a, w=ph_width(t.a)))
        else:
            out.append(Shaped(t.t))
    return out, errs


# ---------------------------------------------------------------------------
# widths, wrapping
# ---------------------------------------------------------------------------


def make_ph_width(entry: dict):
    over = (entry.get("limits") or {}).get("ph") or {}

    def width(ph: str) -> int:
        if ph in over:
            return over[ph]
        name = ph_name(ph)
        if name in PH_WIDTH:
            return PH_WIDTH[name]
        if name == "ram":
            return RAM_WIDTH.get(ph[5:-1].split("+")[0].strip(), RAM_DEFAULT)
        if name == "num":
            try:
                return int(ph[1:-1].split(",")[2], 0)
            except (ValueError, IndexError):
                return 7
        if name == "d":
            return 5
        return SPECIAL_WIDTH_DEFAULT

    return width


def split_words(items: list[Shaped]) -> list[list[Shaped]]:
    """Split a run of shaped tokens (no breaks) into words at spaces.
    Alternatives and placeholders never split.  Returns list of words; each
    word is a list of Shaped pieces (text pieces contain no spaces)."""
    words: list[list[Shaped]] = []
    cur: list[Shaped] = []
    for it in items:
        if it.t == "t":
            parts = it.s.split(" ")
            for k, p in enumerate(parts):
                if k > 0:
                    words.append(cur)
                    cur = []
                if p:
                    cur.append(Shaped("t", s=p, w=len(p)))
        else:
            cur.append(it)
    words.append(cur)
    return words


def word_width(w: list[Shaped]) -> int:
    return sum(p.w for p in w)


def wrap(items: list[Shaped], width: int) -> list[list[Shaped]]:
    """Greedy wrap of one paragraph.  'nl' items force a break.  Returns rows,
    each a list of Shaped pieces with explicit single spaces between words."""
    rows: list[list[Shaped]] = []
    segment: list[Shaped] = []
    segments: list[list[Shaped]] = []
    for it in items:
        if it.t == "nl":
            segments.append(segment)
            segment = []
        else:
            segment.append(it)
    segments.append(segment)
    for seg in segments:
        words = split_words(seg)
        # leading/trailing/multiple spaces collapse (empty words)
        words = [w for w in words if w]
        row: list[Shaped] = []
        roww = 0
        for w in words:
            ww = word_width(w)
            if ww > width:
                # hard-break an over-long word between characters
                if row:
                    rows.append(row)
                    row, roww = [], 0
                pieces = _break_word(w, width)
                for p in pieces[:-1]:
                    rows.append(p)
                row = list(pieces[-1])
                roww = word_width(row)
                continue
            need = ww if not row else roww + 1 + ww
            if need <= width:
                if row:
                    row.append(Shaped("t", s=" ", w=1))
                row.extend(w)
                roww = need
            else:
                rows.append(row)
                row = list(w)
                roww = ww
        rows.append(row)
    return rows


def _break_word(w: list[Shaped], width: int) -> list[list[Shaped]]:
    out: list[list[Shaped]] = []
    cur: list[Shaped] = []
    curw = 0
    for p in w:
        if p.t == "t":
            s = p.s
            while s:
                room = width - curw
                if room <= 0:
                    out.append(cur)
                    cur, curw = [], 0
                    room = width
                take = s[:room]
                hyphen = False
                if len(s) > room:
                    # prefer to break after a hyphen
                    k = take.rfind("-")
                    if k >= 0:
                        take = s[: k + 1]
                        hyphen = True
                cur.append(Shaped("t", s=take, w=len(take)))
                curw = width if hyphen else curw + len(take)
                s = s[len(take) :]
        else:
            if curw + p.w > width and cur:
                out.append(cur)
                cur, curw = [], 0
            cur.append(p)
            curw += p.w
    out.append(cur)
    return out


def row_width(row: list[Shaped]) -> int:
    return sum(p.w for p in row)


# ---------------------------------------------------------------------------
# literal emission
# ---------------------------------------------------------------------------


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{").replace("}", "\\}")


class Ngrams:
    """Optional n-gram substitution: shaped glyph-code sequences that are
    written as an existing charmap n-gram (e.g. "#mon" after NgramStrings.Pokemon
    was translated).  Only used where the default/compressing charmap applies."""

    # charmap n-grams that are also Huffman leaves, so they may sit in compressed text
    LEAVES = ("#", "#mon")

    def __init__(self, table: dict[str, str] | None = None, leaves_only: bool = False):
        self.items: list[tuple[str, tuple]] = []
        for token, word in (table or {}).items():
            if not word or (leaves_only and token not in self.LEAVES):
                continue
            shaped = word if any("ﭐ" <= c <= "﻿" for c in word) else AR.shape(word)
            codes = tuple(code_of(c) for c in shaped)
            if len(codes) >= 2:
                self.items.append((token, codes))
        self.items.sort(key=lambda x: -len(x[1]))
        self.table = dict(table or {})

    def leaves(self) -> Ngrams:
        return Ngrams(self.table, leaves_only=True)

    def apply(self, s: str) -> list[tuple[str, str]]:
        """Split shaped text into [('t', text) | ('ng', token)]."""
        if not self.items:
            return [("t", s)]
        codes = [code_of(c) for c in s]
        out: list[tuple[str, str]] = []
        buf = []
        i = 0
        while i < len(s):
            for token, seq in self.items:
                L = len(seq)
                if tuple(codes[i : i + L]) == seq:
                    if buf:
                        out.append(("t", "".join(buf)))
                        buf = []
                    out.append(("ng", token))
                    i += L
                    break
            else:
                buf.append(s[i])
                i += 1
        if buf:
            out.append(("t", "".join(buf)))
        return out


def literal(pieces: list[Shaped], ngrams: Ngrams | None = None) -> str:
    """RGBDS string-literal body for in-string pieces (no commands)."""
    out = []
    for p in pieces:
        if p.t == "t":
            if ngrams is not None:
                for kind, v in ngrams.apply(p.s):
                    out.append(esc(v) if kind == "t" else v)
            else:
                out.append(esc(p.s))
        elif p.t == "alt":
            out.append("<GM>" + esc(p.m) + "<GF>" + esc(p.f) + "<GE>")
        elif p.t == "raw":
            out.append(p.s)
        elif p.t == "ph":
            name = ph_name(p.ph)
            if name in IN_STRING:
                out.append(IN_STRING[name])
            elif name == "d":
                out.append("{d:" + d_symbol(p.ph) + "}")  # RGBDS interpolation
            else:
                raise ValueError(f"command placeholder {p.ph} inside a string")
        else:
            raise ValueError(f"unexpected token {p.t} in a string")
    return "".join(out)


def literal_bytes(pieces: list[Shaped], charmap: str, ngrams: Ngrams | None = None) -> int:
    """Bytes the literal assembles to (n-gram ", " in the default charmap)."""
    n = 0
    for p in pieces:
        if p.t == "t":
            parts = (
                ngrams.apply(p.s)
                if (ngrams is not None and charmap != "no_ngrams")
                else [("t", p.s)]
            )
            for kind, v in parts:
                if kind == "ng":
                    n += 1
                    continue
                k = len(v)
                if charmap != "no_ngrams":
                    k -= v.count(", ")
                n += k
        elif p.t == "alt":
            n += 3 + len(p.m) + len(p.f)
        elif p.t == "raw":
            n += int(p.ph)
        elif p.t == "ph":
            if ph_name(p.ph) == "d":
                n += p.w
            else:
                n += 1
    return n


def d_symbol(ph: str) -> str:
    """Symbol interpolated for {d:X}; an expression gets a helper variable."""
    body = ph[3:-1]
    if re.fullmatch(r"[A-Za-z_][\w.]*", body):
        return body
    import hashlib

    return "__AR_D_" + hashlib.sha1(body.encode()).hexdigest()[:8].upper()


def d_defs(entry: dict, text_or_toks) -> list[str]:
    """DEF lines needed for {d:EXPR} placeholders (assembly-time expressions)."""
    out = []
    for ph in entry.get("skeleton") or []:
        if ph_name(ph) == "d":
            sym = d_symbol(ph)
            if sym != ph[3:-1]:
                line = f"DEF {sym} = {ph[3:-1]}"
                if line not in out:
                    out.append(line)
    return out


def command_line(ph: str) -> str:
    name = ph_name(ph)
    body = ph[1:-1]
    if name == "ram":
        return "text_ram " + body[4:]
    if name == "num":
        a, b, c = body[4:].split(",")
        return f"text_decimal {a}, {b}, {c}"
    if name == "wait":
        return "text_promptbutton"
    if name == "pause":
        return "text_pause"
    if name == "sound":
        return "text_sound " + body[6:]
    if name == "day":
        return "text_today"
    if name == "far":
        return "text_far " + body[4:]
    raise ValueError(ph)


def is_command(p: Shaped) -> bool:
    return p.t == "ph" and ph_name(p.ph) not in IN_STRING and ph_name(p.ph) != "d"


# ---------------------------------------------------------------------------
# common validation
# ---------------------------------------------------------------------------

# Special tiles the English used as glyphs (Lv, PKMN, ID No): an Arabic text may drop or add them.
OPTIONAL_TILES = {"{LV}", "{PK}", "{MN}", "{ID}", "{No}"}


def _skeleton_errors(entry: dict, toks: list[Tok]) -> list[str]:
    want = Counter(p for p in (entry.get("skeleton") or []) if p not in OPTIONAL_TILES)
    have = Counter(t.a for t in toks if t.t == "ph" and t.a not in OPTIONAL_TILES)
    errs = []
    if want != have:
        missing = want - have
        extra = have - want
        if missing:
            errs.append("missing placeholders: " + " ".join(sorted(missing.elements())))
        if extra:
            errs.append("unexpected placeholders: " + " ".join(sorted(extra.elements())))
    return errs


def _token_errors(entry: dict, toks: list[Tok]) -> list[str]:
    kind = entry["kind"]
    lim = entry.get("limits") or {}
    errs = []
    for t in toks:
        if t.t == "t":
            errs += check_chars(t.a, "text")
        elif t.t == "alt":
            for side in (t.a, t.b):
                errs += check_chars(side, "gender alternative")
            if not t.a.strip() and not t.b.strip():
                errs.append(f"empty gender alternative {t.raw}")
            if lim.get("raw") or kind == "field":
                errs.append(f"gender alternatives are not possible here (raw/fixed field): {t.raw}")
        elif t.t == "para" and kind != "dialog":
            errs.append("\\p (new paragraph) is only allowed in dialog entries")
        elif t.t == "page" and not (kind == "box" and lim.get("pages", 1) > 1):
            errs.append("\\f (new page) is only allowed in multi-page boxes")
        elif t.t == "nl" and kind == "field":
            errs.append("line breaks are not allowed in a fixed field")
        elif t.t == "nl" and kind == "string" and lim.get("lines", 1) <= 1:
            errs.append("this string is a single line (no \\n)")
        elif t.t == "ph":
            name = ph_name(t.a)
            if lim.get("raw") and name in RAW_FORBIDDEN:
                errs.append(f"{t.a} cannot be used in a raw string")
            if kind != "dialog" and is_command(Shaped("ph", ph=t.a)):
                errs.append(f"{t.a} is a text command and only works in dialog entries")
    return errs


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------


def _long_words(shaped: list[Shaped], width: int) -> list[str]:
    """Words (text between spaces, inside one text run) wider than a line."""
    errs = []
    for p in shaped:
        if p.t == "t":
            for w in re.split(r"[ ]|(?<=-)", p.s):
                if len(w) > width:
                    errs.append(
                        f"word of {len(w)} cells is wider than a line ({width}); use shorter words"
                    )
        elif p.t == "alt" and max(len(x) for y in (p.m, p.f) for x in y.split(" ") or [""]) > width:
            errs.append(f"gender alternative wider than a line ({width})")
    return errs


def _paragraphs(shaped: list[Shaped]) -> list[list[Shaped]]:
    paras: list[list[Shaped]] = [[]]
    for s in shaped:
        if s.t == "para":
            paras.append([])
        else:
            paras[-1].append(s)
    return paras


def _dialog_rows(entry, text, ngrams=None):
    toks, errs = tokenize(text)
    width_of = make_ph_width(entry)
    shaped, e2 = shape_tokens(toks, width_of)
    errs += e2
    width = (entry.get("limits") or {}).get("width", 18)
    errs += _long_words(shaped, width)
    paras = []
    for p in _paragraphs(shaped):
        paras.append(wrap(p, width))
    return toks, paras, errs


def _emit_dialog(entry, paras, ngrams) -> list[str]:
    fmt = entry["fmt"]
    ind = fmt.get("indent", "\t")
    out: list[str] = list(ind + k for k in fmt.get("keep", []))
    first = fmt.get("first", "text")
    row_macros = fmt.get("rows", ["line", "cont"])  # macros for row 2 and rows 3+
    para_macro = fmt.get("para", "para")
    term = fmt.get("term", "done")
    last_kind = None  # 'str' | 'cmd'
    started = False
    for pi, rows in enumerate(paras):
        for ri, row in enumerate(rows):
            if pi == 0 and ri == 0:
                macro = first
                if first == "line":
                    row_after = ["cont", "cont"]
                elif first == "cont":
                    row_after = ["cont", "cont"]
                else:
                    row_after = row_macros
            elif ri == 0:
                macro = para_macro
                row_after = row_macros
            else:
                macro = row_after[0] if ri == 1 else row_after[1]
            # split the row into string pieces and commands
            pieces: list[Shaped] = []
            emitted_break = False

            def flush_pieces(force=False, macro=macro):
                nonlocal pieces, emitted_break, last_kind, started
                if not pieces and not force:
                    return
                lit = literal(pieces, ngrams.leaves() if ngrams is not None else None)
                if not emitted_break:
                    if macro == "text" and not started and not pieces:
                        pass  # block starts with a command: no empty text
                    else:
                        out.append(f'{ind}{macro} "{lit}"')
                        last_kind = "str"
                    emitted_break = True
                else:
                    out.append(f'{ind}text "{lit}"')
                    last_kind = "str"
                started = True
                pieces = []

            for p in row:
                if is_command(p):
                    if not emitted_break:
                        flush_pieces(force=True)
                    else:
                        flush_pieces()
                    out.append(ind + command_line(p.ph))
                    last_kind = "cmd"
                    started = True
                else:
                    pieces.append(p)
            if pieces or not emitted_break:
                flush_pieces(force=True)
    if term == "@":
        if last_kind == "str" and out and out[-1].endswith('"'):
            out[-1] = out[-1][:-1] + '@"'
        else:
            out.append(ind + "text_end")
    elif term in ("done", "prompt", "text_end", "text_asm"):
        out.append(ind + term)
    out += [ind + k for k in fmt.get("keep_after", [])]
    return _with_label(fmt, out, len(fmt.get("keep", [])))


# ---------------------------------------------------------------------------
# box (wrapped multi-line text in a custom box)
# ---------------------------------------------------------------------------


def _box_pages(entry, text, ngrams=None):
    toks, errs = tokenize(text)
    width_of = make_ph_width(entry)
    shaped, e2 = shape_tokens(toks, width_of)
    errs += e2
    lim = entry.get("limits") or {}
    width = lim.get("width", 18)
    errs += _long_words(shaped, width)
    pages_src: list[list[Shaped]] = [[]]
    for s in shaped:
        if s.t == "page":
            pages_src.append([])
        else:
            pages_src[-1].append(s)
    nlines = lim.get("lines", 2)
    pages: list[list[list[Shaped]]] = []
    for src in pages_src:
        rows = wrap(src, width)
        # automatic page breaks when a page overflows
        for k in range(0, max(len(rows), 1), nlines):
            pages.append(rows[k : k + nlines])
    return toks, pages, errs


def _emit_box(entry, pages, ngrams) -> list[str]:
    fmt = entry["fmt"]
    ind = fmt.get("indent", "\t")
    first = fmt.get("first_sp", fmt.get("first", "text") + " ")
    linem = fmt.get("line_sp", fmt.get("line", "next") + " ")
    pagem = fmt.get("page_sp", fmt.get("page", "page") + " ")
    term = fmt.get("term", "done")
    min_pages = fmt.get("min_pages", 1)
    use_ng = (
        ngrams
        if not (entry.get("limits") or {}).get("raw") and entry.get("charmap") != "no_ngrams"
        else None
    )
    if use_ng is not None and first.strip() == "text":
        use_ng = use_ng.leaves()  # a box that starts with `text` is Huffman-compressed
    pages = [p for p in pages]
    while len(pages) < min_pages:
        pages.append([[]])
    out = list(ind + k for k in fmt.get("keep", []))
    for pi, page in enumerate(pages):
        if not page:
            page = [[]]
        for ri, row in enumerate(page):
            if pi == 0 and ri == 0:
                m = first
            elif ri == 0:
                m = pagem
            else:
                m = linem
            lit = literal(row, use_ng)
            out.append(f'{ind}{m}"{lit}"')
    if term == "@":
        out[-1] = out[-1][:-1] + '@"'
    elif term:
        out.append(ind + term)
    return _with_label(fmt, out, len(fmt.get("keep", [])))


def _with_label(fmt, out, at=0):
    lp = fmt.get("label_prefix")
    if lp and out:
        out[at] = lp + out[at].lstrip()
    return out


# ---------------------------------------------------------------------------
# string / field
# ---------------------------------------------------------------------------


def _string_lines(entry, text):
    toks, errs = tokenize(text)
    width_of = make_ph_width(entry)
    lines: list[list[Tok]] = [[]]
    for t in toks:
        if t.t == "nl":
            lines.append([])
        else:
            lines[-1].append(t)
    shaped_lines = []
    for ln in lines:
        sh, e2 = shape_tokens(ln, width_of)
        errs += e2
        shaped_lines.append(sh)
    return toks, shaped_lines, errs


def _layout_line(core: list[Shaped], slot: dict, lim: dict) -> tuple[list[Shaped], list[str]]:
    """Apply frames / columns / centring / padding to one line's core."""
    errs = []
    width = slot.get("width", lim.get("width", 18))
    core = _strip_spaces(core)
    cols = slot.get("cols")
    if cols:
        # split the core into columns at runs of 2+ spaces
        colpieces = _split_columns(core)
        if len(colpieces) != len(cols):
            errs.append(
                f"expected {len(cols)} columns separated by 2+ spaces, got {len(colpieces)}"
            )
            colpieces = (colpieces + [[]] * len(cols))[: len(cols)]
        laid: list[Shaped] = []
        pos = 0
        for k, (start, cw) in enumerate(cols):
            if pos < start:
                laid.append(Shaped("t", s=" " * (start - pos), w=start - pos))
                pos = start
            elif k > 0:
                errs.append(f"column {k + 1} would start late (needs ≥2 spaces before x={start})")
            piece = colpieces[k]
            pw = row_width(piece)
            if pw > cw:
                errs.append(f"column {k + 1} is {pw} cells, limit {cw}")
            laid.extend(piece)
            pos += pw
        core = laid
    cw = row_width(core)
    if cw > width:
        errs.append(f"line is {cw} cells, limit {width}")
    lead = slot.get("lead", "")
    tail = slot.get("tail", "")
    if slot.get("centre"):
        field = slot["centre"]
        n = max(0, (field - cw) // 2)
        lead = " " * n
    pieces = []
    if lead:
        pieces.append(Shaped("t", s=lead, w=len(lead)))
    pieces.extend(core)
    if slot.get("pad") is not None:
        # pad so that the tail starts where it did in the English
        pad_to = slot["pad"]
        cur = len(lead) + cw if not slot.get("centre") else len(lead) + cw
        if cur < pad_to:
            pieces.append(Shaped("t", s=" " * (pad_to - cur), w=pad_to - cur))
    if tail:
        # verbatim source (digits, ¥, {d:…}, layout symbols): never escaped
        pieces.append(
            Shaped(
                "raw", s=tail, w=slot.get("tail_w", 0), ph=str(slot.get("tail_bytes", len(tail)))
            )
        )
    return pieces, errs


def _strip_spaces(core: list[Shaped]) -> list[Shaped]:
    core = list(core)
    while core and core[0].t == "t" and not core[0].s.strip():
        core.pop(0)
    while core and core[-1].t == "t" and not core[-1].s.strip():
        core.pop()
    if core and core[0].t == "t":
        s = core[0].s.lstrip(" ")
        core[0] = Shaped("t", s=s, w=len(s))
    if core and core[-1].t == "t":
        s = core[-1].s.rstrip(" ")
        core[-1] = Shaped("t", s=s, w=len(s))
    return core


def _split_columns(core: list[Shaped]) -> list[list[Shaped]]:
    cols: list[list[Shaped]] = [[]]
    for p in core:
        if p.t == "t":
            parts = re.split(r"( {2,})", p.s)
            for k, part in enumerate(parts):
                if k % 2 == 1:
                    cols.append([])
                elif part:
                    cols[-1].append(Shaped("t", s=part, w=len(part)))
        else:
            cols[-1].append(p)
    return [_strip_spaces(c) for c in cols]


def _emit_string(entry, shaped_lines, ngrams) -> tuple[list[str], list[str]]:
    """fmt = {'slots': [slot...], 'lines': [{'pre': str, 'parts': [{'slot': k, 'post': str}]}]}
    Translation line i (\\n-separated) fills slot i."""
    fmt = entry["fmt"]
    lim = entry.get("limits") or {}
    errs: list[str] = []
    slots = fmt["slots"]
    charmap = entry.get("charmap", "default")
    use_ng = ngrams if (charmap != "no_ngrams" and not lim.get("raw")) else None
    exact = lim.get("exact_lines", False)
    if len(shaped_lines) > len(slots):
        errs.append(f"{len(shaped_lines)} lines, at most {len(slots)} allowed")
        shaped_lines = shaped_lines[: len(slots)]
    if exact and len(shaped_lines) != len(slots):
        errs.append(
            f"exactly {len(slots)} lines (\\n-separated) are required, got {len(shaped_lines)}"
        )
    while len(shaped_lines) < len(slots):
        shaped_lines.append([])
    laid_lines = []
    empty = [
        not any(p.t in ("t", "alt", "ph") and (p.t != "t" or p.s.strip()) for p in sl)
        for sl in shaped_lines
    ]
    for k, (sl, slot) in enumerate(zip(shaped_lines, slots, strict=False)):
        pieces, e2 = _layout_line(sl, slot, lim)
        errs += [f"line {k + 1}: {e}" if len(slots) > 1 else e for e in e2]
        if slot.get("pad_next") and k + 1 < len(slots) and not all(empty[k + 1 :]):
            # the next line is pushed to the next screen row by padding this one
            w = row_width(pieces)
            if w < slot["pad_next"]:
                pieces = pieces + [
                    Shaped("t", s=" " * (slot["pad_next"] - w), w=slot["pad_next"] - w)
                ]
        laid_lines.append(pieces)
    bodies = []
    total = 0
    for k, (pieces, slot) in enumerate(zip(laid_lines, slots, strict=False)):
        lit = literal(pieces, use_ng)
        nb = literal_bytes(pieces, charmap, use_ng)
        if slot.get("bytes") is not None and nb > slot["bytes"]:
            errs.append(f"line {k + 1}: {nb} bytes, limit {slot['bytes']}")
        before = slot.get("ctl_before", "")
        after = slot.get("ctl_after", "")
        if slot.get("sep_optional") and k + 1 < len(slots) and all(empty[k + 1 :]):
            after = ""  # nothing follows: drop the separator (e.g. landmark "¯")
        if slot.get("size") is not None:
            nb2 = nb + len(_ctl_tokens(before))
            if nb2 > slot["size"]:
                errs.append(f"{nb2} bytes, field size {slot['size']}")
            after = "@" * max(0, slot["size"] - nb2)
        body = before + lit + after
        total += nb + len(_ctl_tokens(before)) + len(_ctl_tokens(after))
        bodies.append(body)
    if lim.get("total_width") is not None:
        tw = sum(
            row_width(_strip_spaces(sl))
            for sl, e in zip(shaped_lines, empty, strict=False)
            if not e
        )
        tw += max(0, sum(1 for e in empty if not e) - 1)
        if tw > lim["total_width"]:
            errs.append(
                f"{tw} cells on one row (lines joined by a space), limit {lim['total_width']}"
            )
    total += lim.get("size_extra", 0)  # bytes emitted by the line macros (next = <NEXT>)
    if lim.get("size") is not None:
        # whole-entry fixed size (mail): pad the last slot with '@'
        if total > lim["size"]:
            errs.append(f"{total} bytes, size {lim['size']}")
        elif total < lim["size"]:
            bodies[-1] = bodies[-1] + "@" * (lim["size"] - total)
            total = lim["size"]
    if lim.get("bytes") is not None and total > lim["bytes"]:
        errs.append(f"{total} bytes, limit {lim['bytes']}")
    out: list[str] = []
    for ln in fmt["lines"]:
        line = ln["pre"]
        for part in ln["parts"]:
            if "slot" in part:
                line += bodies[part["slot"]]
            else:
                line += part["text"]
        out.append(line)
    return out, errs


def _ctl_tokens(s: str) -> list[str]:
    return re.findall(r"<[^<>]*>|.", s)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def _prepare(entry, text, ngrams):
    ng = ngrams if isinstance(ngrams, Ngrams) or ngrams is None else Ngrams(ngrams)
    return ng


def check(entry: dict, arabic_text: str, ngrams=None, sizer=None) -> list[str]:
    """Return a list of problems (empty if the translation can be encoded).
    `sizer(lines) -> bytes` (e.g. sizeest.SizeModel(tree).estimate) enables the
    ROM-size limit of entries that a `jr` jumps across (limits.rom_bytes)."""
    try:
        lines, errs = _encode(entry, arabic_text, ngrams)
    except Exception as e:  # pragma: no cover - defensive
        return [f"internal error: {type(e).__name__}: {e}"]
    rb = (entry.get("limits") or {}).get("rom_bytes")
    if rb is not None and sizer is not None and not errs:
        n = sizer(lines)
        if n > rb:
            errs.append(f"{n} ROM bytes, limit {rb} (a jr jumps across this text)")
    return errs


def encode(entry: dict, arabic_text: str, ngrams=None) -> list[str]:
    """Replacement source lines for entry['start']..entry['end'].  Raises
    ValueError when the translation has problems (see check())."""
    lines, errs = _encode(entry, arabic_text, ngrams)
    if errs:
        raise ValueError(f"{entry['id']}: " + "; ".join(errs))
    return lines


def _encode(entry: dict, text: str, ngrams=None) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    try:
        return _encode_inner(entry, text, ngrams, errs)
    except ValueError as e:
        if errs:
            return [], errs
        return [], [f"cannot encode: {e}"]


def _encode_inner(entry: dict, text: str, ngrams, errs: list[str]) -> tuple[list[str], list[str]]:
    ng = _prepare(entry, text, ngrams)
    kind = entry["kind"]
    lim = entry.get("limits") or {}
    toks, terrs = tokenize(text)
    errs += terrs
    errs += _token_errors(entry, toks)
    errs += _skeleton_errors(entry, toks)
    if not any(t.t in ("t", "alt", "ph") for t in toks) and not lim.get("allow_empty"):
        errs.append("empty translation")
    if terrs or any(t.t == "ph" and normalize_ph(t.a[1:-1]) is None for t in toks):
        return [], errs  # cannot lay out malformed notation
    if kind == "dialog":
        _, paras, e2 = _dialog_rows(entry, text, ng)
        errs += e2
        width = lim.get("width", 18)
        nonempty = [any(r) for r in paras]
        if not any(nonempty):
            errs.append("empty translation")
        for pi, rows in enumerate(paras):
            # an empty paragraph is allowed: it waits for a button and clears the box (para "")
            for ri, row in enumerate(rows):
                if row_width(row) > width:
                    errs.append(
                        f"paragraph {pi + 1} row {ri + 1}: {row_width(row)} cells > {width}"
                    )
        maxrows = lim.get("rows")
        if maxrows:
            for pi, rows in enumerate(paras):
                if len(rows) > maxrows:
                    errs.append(f"paragraph {pi + 1} has {len(rows)} rows, limit {maxrows}")
        lines = _emit_dialog(entry, paras, ng)
        return d_defs(entry, None) + lines, errs
    if kind == "box":
        _, pages, e2 = _box_pages(entry, text, ng)
        errs += e2
        if len(pages) > lim.get("pages", 1):
            errs.append(
                f"{len(pages)} pages of {lim.get('lines', 2)} lines, limit {lim.get('pages', 1)} "
                f"(width {lim.get('width', 18)})"
            )
        bpl = lim.get("bytes_per_line")
        charmap = entry.get("charmap", "default")
        use_ng = ng if not lim.get("raw") else None
        for pi, page in enumerate(pages):
            for ri, row in enumerate(page):
                if row_width(row) > lim.get("width", 18):
                    errs.append(f"page {pi + 1} line {ri + 1}: {row_width(row)} cells")
                if bpl is not None:
                    b = literal_bytes(row, charmap, use_ng)
                    if b > bpl:
                        errs.append(f"page {pi + 1} line {ri + 1}: {b} bytes > {bpl}")
        lines = _emit_box(entry, pages, ng)
        return d_defs(entry, None) + lines, errs
    if kind in ("string", "field"):
        _, shaped_lines, e2 = _string_lines(entry, text)
        errs += e2
        lines, e3 = _emit_string(entry, shaped_lines, ng)
        errs += e3
        return d_defs(entry, None) + lines, errs
    raise ValueError(f"unknown kind {kind}")


def cells(text: str, entry: dict | None = None) -> int:
    """Total display cells of a notation text (placeholders at max width)."""
    toks, _ = tokenize(text)
    width_of = make_ph_width(entry or {"limits": {}})
    shaped, _ = shape_tokens(toks, width_of)
    return sum(s.w for s in shaped if s.t in ("t", "alt", "ph"))


def shaped_text(text: str) -> str:
    """Shaped form of a notation text, with in-string codes for placeholders and
    <GM>/<GF>/<GE> for alternatives (what roundtrip.py compares)."""
    toks, _ = tokenize(text)
    shaped, _ = shape_tokens(toks, make_ph_width({"limits": {}}))
    out = []
    for s in shaped:
        if s.t == "t":
            out.append(s.s)
        elif s.t == "alt":
            out.append("<GM>" + s.m + "<GF>" + s.f + "<GE>")
        elif s.t == "ph":
            out.append(s.ph)
        elif s.t == "nl":
            out.append("\n")
        elif s.t == "para":
            out.append("\f")
        elif s.t == "page":
            out.append("\f")
    return "".join(out)
