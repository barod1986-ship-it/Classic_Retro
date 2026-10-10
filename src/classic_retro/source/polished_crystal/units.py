"""Source units of Polished Crystal's text: the charmap, literals, notation and frames.

The extractor (``extract``) reads the source a statement at a time
(``asmscan``) and groups the statements of one text into a unit: a text block
(``text``/``line``/``para``/... up to its terminator) or a chain of strings
(``db``/``li``/``next``/``rawchar``). This module holds what the rules need for
every unit: the English charmap (to read a literal's tokens and widths), the
conversion of an English literal into the translators' notation, the line
range a unit owns (widened over the conditionals it crosses) and its pin, and
the frame of a literal (control codes, padding and layout around the text).
"""

from __future__ import annotations

import hashlib
import os
import re

from classic_retro.source.polished_crystal import asmscan
from classic_retro.source.polished_crystal import encode as ENC
from classic_retro.source.polished_crystal.asmscan import Stmt, unquote

TEXT_MACROS = {"text", "line", "cont", "para", "next", "next1", "page", "done", "prompt"}
TEXT_CMDS = {
    "text_start",
    "text_ram",
    "text_decimal",
    "text_promptbutton",
    "text_pause",
    "text_sound",
    "text_today",
    "text_far",
    "text_plural",
    "text_end",
    "text_asm",
}
CHAIN_DIRS = {"db", "rawchar", "li"}
TERMINATORS = {"done", "prompt", "text_end", "text_asm"}
NON_EMITTING = {
    "assert",
    "static_assert",
    "def",
    "redef",
    "purge",
    "warn",
    "println",
    "print",
    "opt",
    "pusho",
    "popo",
    "table_width",
    "assert_table_length",
    "list_start",
    "assert_list_length",
    "setcharmap",
    "charmap",
    "newcharmap",
    "pushc",
    "popc",
    "export",
    "fail",
}
TRANSPARENT_IN_TEXT = {
    "assert",
    "static_assert",
    "def",
    "redef",
    "purge",
    "warn",
    "println",
    "print",
}
CTRL_BREAKS = {"<LINE>", "<CONT>", "<PARA>", "<NEXT>", "<LNBRK>"}
CTRL_TERMS = {"<DONE>", "<PROMPT>", "@"}
PH_CODES = {
    "<PLAYER>": "PLAYER",
    "<RIVAL>": "RIVAL",
    "<TRENDY>": "TRENDY",
    "<USER>": "USER",
    "<TARGET>": "TARGET",
    "<ENEMY>": "ENEMY",
    "<PK>": "PK",
    "<MN>": "MN",
    "<LV>": "LV",
    "<ID>": "ID",
    "№": "No",
}
ENGLISH_WIDTH = {"#": 4, "#mon": 7, "<PO>": 2, "<KE>": 2}
LETTER_RE = re.compile(r"[A-Za-z#éÉáêíóÈ\u0621-\u064A\uFE70-\uFEFC]")


# ---------------------------------------------------------------------------
# charmap model (English side)
# ---------------------------------------------------------------------------


class Charmap:
    """The charmaps of ``constants/charmap.asm``: ``no_ngrams``, ``compressing``, ``default``."""

    def __init__(self, root=None, *, text: str | None = None):
        self.maps: dict[str, dict[str, int]] = {}
        cur = None
        in_macro = False
        if text is None:
            with open(os.path.join(root, "constants", "charmap.asm"), encoding="utf-8") as f:
                text = f.read()
        for raw in text.splitlines(keepends=True):
            code, _ = asmscan.split_comment(raw)
            s = code.strip()
            if not s:
                continue
            low = s.split()[0].lower()
            if low == "macro":
                in_macro = True
                continue
            if in_macro:
                if low == "endm":
                    in_macro = False
                continue
            m = re.match(r"newcharmap\s+(\w+)(?:\s*,\s*(\w+))?", s)
            if m:
                cur = m.group(1)
                self.maps[cur] = dict(self.maps[m.group(2)]) if m.group(2) else {}
                continue
            m = re.match(r'(?:charmap|ctxtmap)\s+("(?:[^"\\]|\\.)*")\s*,\s*\$([0-9A-Fa-f]+)', s)
            if m and cur:
                self.maps[cur][unquote(m.group(1))] = int(m.group(2), 16)
        self.sorted = {k: sorted(v, key=len, reverse=True) for k, v in self.maps.items()}
        self.maxlen = {k: max(map(len, v)) for k, v in self.maps.items()}

    def tokenize(self, s: str, cm: str = "compressing") -> list[tuple[str, int | None]]:
        cm = cm if cm in self.maps else "default"
        m = self.maps[cm]
        out = []
        i = 0
        while i < len(s):
            if s[i] == "{":
                j = s.find("}", i)
                if j > 0:
                    out.append((s[i : j + 1], None))
                    i = j + 1
                    continue
            if s[i] == "\\" and i + 1 < len(s):
                out.append((s[i + 1], m.get(s[i + 1])))
                i += 2
                continue
            for L in range(min(self.maxlen[cm], len(s) - i), 0, -1):
                t = s[i : i + L]
                if t in m:
                    out.append((t, m[t]))
                    i += L
                    break
            else:
                out.append((s[i], None))
                i += 1
        return out

    def nbytes(self, s: str, cm: str, consts) -> int:
        n = 0
        for tok, _b in self.tokenize(s, cm):
            if tok.startswith("{") and tok.endswith("}"):
                n += interp_width(tok, consts)
            else:
                n += 1
        return n


def interp_width(tok: str, consts) -> int:
    m = re.fullmatch(r"\{d:([^{}]+)\}", tok)
    if m:
        v = consts.eval(m.group(1))
        if v is not None:
            return len(str(v))
    return 5


# ---------------------------------------------------------------------------
# English -> notation
# ---------------------------------------------------------------------------


def en_tokens(cm: Charmap, s: str) -> list[str]:
    return [t for t, _ in cm.tokenize(s, "compressing")]


def en_piece(cm: Charmap, s: str, consts, ram_width=None) -> tuple[str, list[str], int]:
    """English literal (no break codes) -> (notation, placeholders, cells)."""
    out = []
    ph = []
    w = 0
    toks = en_tokens(cm, s)
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "#mon":
            out.append("Pokémon")
            w += 7
        elif t == "#":
            out.append("Poké")
            w += 4
        elif t == "<PO>" and i + 1 < len(toks) and toks[i + 1] == "<KE>":
            out.append("Poké")
            w += 2  # two bold tiles
            i += 1
        elif t in PH_CODES:
            p = "{" + PH_CODES[t] + "}"
            out.append(p)
            ph.append(p)
            w += ENC.PH_WIDTH[PH_CODES[t]]
        elif t.startswith("{d:"):
            out.append(t)
            ph.append(t)
            w += interp_width(t, consts)
        elif t.startswith("{"):
            out.append(t)
            w += 5
        elif t == "¯":
            out.append(" ")
            w += 1
        elif t in ("<GM>", "<GF>", "<GE>"):
            out.append(t)
        elif t == "<BOLDP>":
            out.append("P")  # bold "P" tile (PP)
            w += 1
        elif t.startswith("<") and len(t) > 2:
            out.append("{sym:" + t[1:-1] + "}")
            w += 1
        else:
            out.append(t)
            w += len(t) if len(t) > 1 and t[0] != "'" else 1
        i += 1
    return "".join(out), ph, w


def has_letters(s: str) -> bool:
    s2 = re.sub(
        r"<[^<>]*>",
        lambda m: "#" if m.group(0) in ("<PLAYER>", "<RIVAL>", "<TRENDY>", "<PO>", "<KE>") else " ",
        s,
    )
    s2 = re.sub(r"\{[^{}]*\}", " ", s2)
    return bool(LETTER_RE.search(s2))


def join_rows(rows: list[str]) -> str:
    out = ""
    for r in rows:
        r = r.strip(" ")
        if not r:
            continue
        if not out:
            out = r
        elif re.search(r"[A-Za-zé]-$", out) and re.match(r"[a-zé]", r):
            out = out[:-1] + r
        elif out.endswith("-") and re.match(r"[a-z]", r):
            out = out + r
        else:
            out = out + " " + r
    return out


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------


class Unit:
    def __init__(self, kind, file, labels, owner):
        self.kind = kind  # 'text' | 'chain'
        self.file = file
        self.labels = labels  # stacked labels on the first byte
        self.owner = owner
        self.stmts: list[Stmt] = []
        self.closed = False
        self.term = ""
        self.inline_cmd = None

    @property
    def active_stmts(self):
        return [s for s in self.stmts if s.kind == "stmt" and s.active]

    @property
    def first_line(self):
        return min(s.line for s in self.stmts if s.kind == "stmt")

    @property
    def last_line(self):
        return max(s.line for s in self.stmts if s.kind == "stmt")

    def __repr__(self):
        return f"Unit({self.kind},{self.file}:{self.first_line}-{self.last_line},{self.labels or self.owner})"


INLINE_CMDS = {
    "writethistext",
    "jumpthistext",
    "jumpthistextfaceplayer",
    "jumpthisopenedtext",
    "generictrainer",
}


def build_units(fs) -> list[Unit]:
    units: list[Unit] = []
    cur: Unit | None = None
    pending: list[str] = []
    last_script_cmd = None

    def close(term=""):
        nonlocal cur
        if cur is not None:
            if not cur.closed:
                cur.closed = True
                if not cur.term:
                    cur.term = term
            units.append(cur)
        cur = None

    for st in fs.stmts:
        if st.kind in ("blank", "macro"):
            continue
        if st.kind == "cond":
            if cur is not None:
                cur.stmts.append(st)
            continue
        if not st.active:
            if cur is not None and (
                st.directive in TEXT_MACROS | TEXT_CMDS | CHAIN_DIRS or not st.directive
            ):
                cur.stmts.append(st)
            continue
        if st.labels:
            if cur is not None:
                close("")
            pending.extend(st.labels)
            last_script_cmd = None
            if not st.directive:
                continue
        d = st.directive
        texty = d in TEXT_MACROS or d in TEXT_CMDS
        chainy = d in CHAIN_DIRS and st.has_strings
        if cur is not None and not cur.closed:
            if cur.kind == "text" and (texty or d in TRANSPARENT_IN_TEXT):
                cur.stmts.append(st)
                if d in TERMINATORS:
                    cur.term = d
                    close()
                continue
            if (
                cur.kind == "chain"
                and d in ("next", "next1", "page", "db", "rawchar")
                and st.has_strings
                and not _chain_ended(cur)
            ):
                cur.stmts.append(st)
                continue
            if cur.kind == "chain" and d in TRANSPARENT_IN_TEXT:
                cur.stmts.append(st)
                continue
            close("")
        if texty or chainy:
            kind = "chain" if (chainy or d in ("next", "next1", "page")) else "text"
            owner = st.owner
            cur = Unit(kind, fs.path, list(pending), owner)
            cur.inline_cmd = last_script_cmd if not pending else None
            pending = []
            cur.stmts.append(st)
            if kind == "text" and d in TERMINATORS:
                cur.term = d
                close()
            elif kind == "chain" and d == "li":
                close("@")
            continue
        # any other statement
        if d and d not in NON_EMITTING:
            pending = []
        if d in INLINE_CMDS:
            last_script_cmd = d
        elif d and d not in NON_EMITTING:
            last_script_cmd = None
    close("")
    # chains that end with '@' get their term
    for u in units:
        if u.kind == "chain" and not u.term:
            u.term = "@" if _chain_ended(u) else ""
    return units


def _chain_ended(u: Unit) -> bool:
    for s in reversed(u.stmts):
        if s.kind == "stmt" and s.active and s.has_strings:
            lit = [x for x in s.strings if x is not None]
            return bool(lit) and lit[-1].endswith("@")
    return False


# ---------------------------------------------------------------------------
# ranges and pins
# ---------------------------------------------------------------------------


def unit_range(fs, u: Unit) -> tuple[int, int, list[str]]:
    """[start, end] lines covering the unit, widened to whole conditionals that
    cross it.  Also returns problems (labels / code swallowed by widening)."""
    s, e = u.first_line, u.last_line
    probs = []
    changed = True
    while changed:
        changed = False
        for _cid, cb in fs.conds.items():
            bounds = [cb.if_line, cb.endc_line] + cb.else_lines
            if any(s <= b <= e for b in bounds):
                ns, ne = min(s, cb.if_line), max(e, cb.endc_line)
                if (ns, ne) != (s, e):
                    s, e = ns, ne
                    changed = True
    # what is inside?
    for st in fs.stmts[s - 1 : e]:
        if st.line == u.first_line:
            continue
        if st.labels and st.line != s:
            probs.append(f"label {st.labels[0]} inside the widened range (line {st.line})")
        if (
            st.kind == "stmt"
            and st.directive
            and st.directive not in TEXT_MACROS | TEXT_CMDS | CHAIN_DIRS | TRANSPARENT_IN_TEXT
        ):
            probs.append(f"non-text statement {st.directive} inside the range (line {st.line})")
    return s, e, probs


def pin(lines: list[str], s: int, e: int) -> str:
    h = hashlib.sha256()
    h.update("\n".join(lines[s - 1 : e]).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# literal decomposition (frames)
# ---------------------------------------------------------------------------

LAYOUT_SYMS = set("▶▷◀▲▼★┌┐└┘─│━┃↑↓→←·") | {
    "<BOLDP>",
    "<PHONE>",
    "<BLACK>",
    "<SHARP>",
    "<MALE>",
    "<FEMALE>",
    "<STAR>",
    "<BALL>",
    "<NONO>",
    "◢",
    "◣",
    "—",
}


def decompose(cm: Charmap, content: str, consts) -> dict:
    """Split one literal (no inner line breaks) into frame and core."""
    toks = en_tokens(cm, content)
    # control tokens at both ends
    ctl_before = []
    while toks and (toks[0] in CTRL_BREAKS or toks[0] in CTRL_TERMS):
        ctl_before.append(toks.pop(0))
    ctl_after = []
    while toks and (toks[-1] in CTRL_BREAKS or toks[-1] in CTRL_TERMS):
        ctl_after.insert(0, toks.pop())
    # leading spaces
    lead = 0
    while toks and toks[0] == " ":
        toks.pop(0)
        lead += 1
    # trailing: spaces, layout symbols, and a final non-letter column
    tail_toks = []
    # final column separated by >=2 spaces without letters
    joined = toks
    # find last run of >=2 spaces
    gap_at = None
    k = len(joined) - 1
    while k > 0:
        if joined[k] == " " and joined[k - 1] == " ":
            j = k
            while j > 0 and joined[j - 1] == " ":
                j -= 1
            rest = "".join(joined[k + 1 :])
            if rest and not has_letters(rest):
                gap_at = j
            break
        k -= 1
    if gap_at is not None:
        tail_toks = joined[gap_at:]
        toks = joined[:gap_at]
    while toks and (toks[-1] == " " or toks[-1] in LAYOUT_SYMS):
        tail_toks.insert(0, toks.pop())
    while toks and toks[0] in LAYOUT_SYMS:
        # a leading layout symbol stays in the lead frame
        lead_sym = toks.pop(0)
        ctl_before.append(" " * lead + lead_sym)
        lead = 0
        while toks and toks[0] == " ":
            toks.pop(0)
            lead += 1
    core = "".join(toks)
    tail = "".join(tail_toks)
    # spaces before the tail text
    tail_text = tail.lstrip(" ")
    gap = len(tail) - len(tail_text)
    core_w = en_piece(cm, core, consts)[2] if core else 0
    return {
        "ctl_before": "".join(ctl_before),
        "lead": lead,
        "core": core,
        "core_w": core_w,
        "tail": tail,
        "tail_text": tail_text,
        "gap": gap,
        "ctl_after": "".join(ctl_after),
    }


def make_slot(
    cm, consts, d: dict, pre: str, post: str, width=None, centre=None, size=None, nbytes=None
) -> dict:
    """Encoder slot for one decomposed literal (see encode._layout_line)."""
    slot = {
        "pre": pre,
        "post": post,
        "ctl_before": d["ctl_before"] + ("" if centre else " " * d["lead"]),
        "ctl_after": d["ctl_after"],
    }
    tail_text = d["tail_text"]
    gap = d["gap"]
    core_w = d["core_w"]
    gap_min = 0
    if tail_text:
        slot["tail"] = tail_text
        gap_min = 2 if gap >= 2 else gap
    if gap:
        slot["pad"] = core_w + gap  # cells from the core start to the tail / field end
    auto_w = core_w + gap - gap_min
    if width is None:
        w = auto_w
    elif tail_text:
        w = min(width, auto_w) if gap else width
    else:
        w = width
        if gap:
            slot["pad"] = max(slot["pad"], w)
    if size is None:
        # the English fits in the real game, so the limit is never below its width
        w = max(w, core_w)
    if centre:
        slot["centre"] = centre
    slot["width"] = w
    if size is not None:
        slot["size"] = size
    if nbytes is not None:
        slot["bytes"] = nbytes
    return slot


# ---------------------------------------------------------------------------
# context helpers
# ---------------------------------------------------------------------------


def nice_name(stem: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z][a-z])", " ", stem)
    return s.replace("Poke Center", "Pokémon Center").replace("Poke Mart", "Poké Mart")


ROLE_DESC = {
    "textbox": "dialogue",
    "npc": "NPC talk",
    "sign": "sign / object",
    "trainer_seen": "trainer, before battle",
    "battle_win": "trainer defeated (battle text box)",
    "battle_loss": "trainer won (battle text box)",
    "trainer_after": "trainer, after battle",
    "textbox_inline": "dialogue",
    "pokemon_cry": "Pokémon cry",
}

# (the category logic lives in extract.py)
