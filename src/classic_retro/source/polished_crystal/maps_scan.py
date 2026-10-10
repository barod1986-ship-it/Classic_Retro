"""Scan Polished Crystal maps/*.asm for player-visible text and give each
string a stable translation id.

Pure Python 3, no third-party dependencies.  Designed to be reused by the
extraction / re-injection tooling, so the parsing layer (lexer, charmap,
block state machine) is kept separate from the reporting layer.

The extractor (``extract``) uses it for the role of each map text (dialogue,
sign, trainer before or after a battle), the references between texts, and the
menu boxes map scripts open.

ID scheme:
    labelled text block   <MapStem>:<Global>            e.g. VioletCity:VioletCitySignText
                          <MapStem>:<Global>.<local>    e.g. Route23:Route23ZephyrBadgeOfficerScript.ZephyrBadgeText
    inline text block     <MapStem>:<Owner>+<n>         Owner = innermost label (Global or Global.local)
                                                        that owns the jumpthis*/writethistext command,
                                                        n = 1-based ordinal of inline blocks under that owner
    db / rawchar string   <MapStem>:<Owner>[<k>]        k = 0-based index of the string under that label
Global labels are unique in the whole ROM (all maps are INCLUDEd into one
assembly unit, data/maps/scripts.asm), so <Global>[.<local>] alone is already
unique; the <MapStem>: prefix is kept for grouping and for sanity checks.
"""

from __future__ import annotations

import collections
import os
import re
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Lexing helpers
# ---------------------------------------------------------------------------


def strip_comment(line: str) -> str:
    """Remove a ';' comment that is outside string literals.

    Handles backslash escapes inside strings (\\" and \\\\)."""
    out = []
    in_str = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append(line[i : i + 2])
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == ";":
                break
            if c == '"':
                in_str = True
        out.append(c)
        i += 1
    return "".join(out).rstrip()


def split_args(s: str) -> list[str]:
    """Split a macro argument list on commas outside strings / parens."""
    args, cur = [], []
    depth = 0
    in_str = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(s[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail or args:
        args.append(tail)
    return args


_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "{": "{",
    "}": "}",
    ",": ",",
    "(": "(",
    ")": ")",
}


def unquote(arg: str) -> str | None:
    """Return the decoded content of a "..." literal, or None if arg is not
    a single plain string literal.  {interpolations} are kept verbatim."""
    arg = arg.strip()
    if len(arg) < 2 or arg[0] != '"' or arg[-1] != '"':
        return None
    body = arg[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
            continue
        if c == '"':  # two literals glued together, not expected here
            return None
        out.append(c)
        i += 1
    return "".join(out)


LABEL_CHARS = r"[A-Za-z0-9_@#$]"
RE_GLOBAL = re.compile(r"^([A-Za-z_]" + LABEL_CHARS + r"*)(::?)(.*)$")
RE_SCOPED_LOCAL = re.compile(
    r"^([A-Za-z_]" + LABEL_CHARS + r"*)\.(" + LABEL_CHARS + r"+)(::?)(.*)$"
)
RE_LOCAL = re.compile(r"^\.(" + LABEL_CHARS + r"+):?(?=\s|$)(.*)$")
RE_INSTR = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\b\s*(.*)$")

# ---------------------------------------------------------------------------
# Charmap / glyph width model
# ---------------------------------------------------------------------------


class Charmap:
    """Minimal model of constants/charmap.asm (three charmaps)."""

    def __init__(self, root: str):
        self.maps: dict[str, dict[str, int]] = {}
        path = os.path.join(root, "constants", "charmap.asm")
        cur: str | None = None
        with open(path, encoding="utf-8") as f:
            for raw in f:
                code = strip_comment(raw).strip()
                if not code:
                    continue
                m = re.match(r"newcharmap\s+(\w+)(?:\s*,\s*(\w+))?", code)
                if m:
                    cur = m.group(1)
                    self.maps[cur] = dict(self.maps[m.group(2)]) if m.group(2) else {}
                    continue
                m = re.match(
                    r'(?:charmap|ctxtmap)\s+("(?:[^"\\]|\\.)*")\s*,\s*\$([0-9A-Fa-f]+)', code
                )
                if m and cur is not None:
                    key = unquote(m.group(1))
                    self.maps[cur][key] = int(m.group(2), 16)
        # byte -> key (no_ngrams) for the n-gram expansions
        self.byte_to_glyph: dict[int, str] = {v: k for k, v in self.maps["no_ngrams"].items()}
        self._sorted_keys = {
            name: sorted(m.keys(), key=len, reverse=True) for name, m in self.maps.items()
        }
        self._maxlen = {name: max(len(k) for k in m) for name, m in self.maps.items()}

    def tokenize(self, s: str, charmap: str = "compressing") -> list[tuple[str, int | None]]:
        """Longest-match tokenisation like rgbds.  Returns (token, byte)
        pairs; byte is None for characters with no mapping and for
        {interpolations} (kept as one token)."""
        m = self.maps[charmap]
        maxlen = self._maxlen[charmap]
        out = []
        i = 0
        while i < len(s):
            if s[i] == "{":
                j = s.find("}", i)
                if j != -1:
                    out.append((s[i : j + 1], None))
                    i = j + 1
                    continue
            for L in range(min(maxlen, len(s) - i), 0, -1):
                tok = s[i : i + L]
                if tok in m:
                    out.append((tok, m[tok]))
                    i += L
                    break
            else:
                out.append((s[i], None))
                i += 1
        return out


# Display width of the special bytes (worst case for variable ones).
VAR_WIDTH = {
    "#": 4,  # "Poké"   (data/text/ngrams.asm .Poke)
    "#mon": 7,  # "Pokémon"
    "<PLAYER>": 7,  # PLAYER_NAME_LENGTH - 1 (naming screen .StoreSpriteIconParams)
    "<RIVAL>": 7,
    "<TRENDY>": 7,
    "<TARGET>": 16,  # battle only; "Enemy "/"Foe" + nickname, rough worst case
    "<USER>": 16,
    "<ENEMY>": 16,
}
CONTROL_IN_STRING = {
    "<DONE>",
    "@",
    "<PROMPT>",
    "<LNBRK>",
    "<NEXT>",
    "<LINE>",
    "<CONT>",
    "<PARA>",
    "<START>",
    "<RAM>",
    "<WAIT>",
    "<ASM>",
    "<NUM>",
    "<PAUSE>",
    "<SOUND>",
    "<DAY>",
    "<FAR>",
    "<PLURAL>",
    "<CTXT>",
}
INTERP_WIDTH = 5  # {d:CONST} interpolation in db strings, assume <= 5 digits


DEFS: dict[str, int] = {}  # numeric constants for {d:NAME} interpolation (filled by scan_tree)


def interp_width(tok: str) -> tuple[int, int]:
    """(min, max) width of a {d:NAME} interpolation."""
    m = re.fullmatch(r"\{d:(\w+)\}", tok)
    if m and m.group(1) in DEFS:
        w = len(str(DEFS[m.group(1)]))
        return w, w
    return 1, INTERP_WIDTH


def glyph_width(cm: Charmap, s: str) -> tuple[int, int, list[str], list[str]]:
    """Return (min_width, max_width, specials, unknown) for a source string.
    min counts variable placeholders as 1, max uses VAR_WIDTH."""
    lo = hi = 0
    specials, unknown = [], []
    for tok, b in cm.tokenize(s, "compressing"):
        if tok in VAR_WIDTH:
            lo += 1
            hi += VAR_WIDTH[tok]
            specials.append(tok)
        elif tok in CONTROL_IN_STRING:
            specials.append(tok)
        elif tok.startswith("{"):
            wlo, whi = interp_width(tok)
            lo += wlo
            hi += whi
            specials.append("{interp}")
        elif b is None:
            unknown.append(tok)
            lo += 1
            hi += 1
        else:
            lo += 1
            hi += 1
            if tok.startswith("<"):
                specials.append(tok)
    return lo, hi, specials, unknown


# ---------------------------------------------------------------------------
# Text command model
# ---------------------------------------------------------------------------

# commands that start / continue a 'text' stream (all take string args)
TEXT_STRING_CMDS = {"text", "line", "cont", "para", "next", "next1", "page", "done", "prompt"}
# what each command does to the cursor
NEW_LINE_CMDS = {"line", "cont", "para", "next", "next1", "page"}
TERMINATORS = {"done", "prompt", "text_end"}
# other text commands (macros/scripts/text.asm)
TEXT_SPECIAL_CMDS = {
    "text_start",
    "text_ram",
    "text_decimal",
    "text_promptbutton",
    "text_pause",
    "text_sound",
    "text_today",
    "text_far",
    "text_plural",
    "text_asm",
    "text_end",
}
TEXT_CMDS = TEXT_STRING_CMDS | TEXT_SPECIAL_CMDS
# directives that emit no bytes and may appear inside a text block
TRANSPARENT_DIRECTIVES = {
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
}

# script commands whose text follows inline (no label)
INLINE_TEXT_SCRIPT_CMDS = {
    "writethistext",
    "jumpthistext",
    "jumpthistextfaceplayer",
    "jumpthisopenedtext",
    # generictrainer CLASS, ID, FLAG, .SeenText, .BeatenText is followed
    # directly by the after-battle text (read by the trainer engine)
    "generictrainer",
}
# script/data commands that point at text labels: name -> indices of label args
TEXT_POINTER_CMDS = {
    "writetext": (0,),
    "jumptext": (0,),
    "jumptextfaceplayer": (0,),
    "jumpopenedtext": (0,),
    "showtext": (0,),
    "showtextfaceplayer": (0,),
    "showcrytext": (0,),
    "iftrue_jumptext": (0,),
    "iffalse_jumptext": (0,),
    "iftrue_jumptextfaceplayer": (0,),
    "iffalse_jumptextfaceplayer": (0,),
    "iftrue_jumpopenedtext": (0,),
    "iffalse_jumpopenedtext": (0,),
    "farwritetext": (0,),
    "farjumptext": (0,),
    "winlosstext": (0, 1),
    "trainer": (3, 4, 5),  # seen, win, lost (arg 6 = after script)
    "generictrainer": (3, 4),  # seen, win
    "getstring": (0,),  # db string -> wStringBufferN
    "givepokemail": (0,),
    "checkpokemail": (0,),
    "givepoke": (6, 7),  # nickname, OT name (only with >= 7 args)
    "loadmenu": (0,),  # menu header containing db item strings
}


@dataclass
class TextCmd:
    cmd: str
    args: list[str]
    line: int
    strings: list[str] = field(default_factory=list)
    active: bool = True  # False inside an if DEF(FAITHFUL)/DEF(DEBUG) branch not built


@dataclass
class TextBlock:
    id: str
    file: str
    owner: str  # Global or Global.local label that owns the block
    kind: str  # 'label' | 'inline' | 'orphan'
    inline_cmd: str | None  # writethistext/... for inline blocks
    line_start: int
    line_end: int = 0
    terminator: str | None = None
    active: bool = True  # assembled in the non-FAITHFUL, non-DEBUG build
    cond: str = ""
    aliases: list[str] = field(default_factory=list)  # extra labels stacked on the start
    tail_labels: list[str] = field(default_factory=list)  # labels in the middle of the block
    commands: list[TextCmd] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    # derived (filled by analyse_block / assign_roles)
    rows: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


@dataclass
class DbString:
    id: str
    file: str
    owner: str
    index: int
    line: int
    directive: str
    charmap: str
    text: str
    raw_args: list[str]
    active: bool = True
    cond: str = ""


@dataclass
class Ref:
    file: str
    line: int
    cmd: str
    label: str  # as written
    resolved: str  # Global.local fully qualified (best effort)
    argi: int = 0  # which argument of the command held the label


@dataclass
class FileScan:
    path: str
    stem: str
    blocks: list[TextBlock] = field(default_factory=list)
    dbstrings: list[DbString] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    labels: list[tuple[str, int]] = field(default_factory=list)  # fully qualified
    menu_headers: dict[str, dict] = field(default_factory=dict)
    macros: list[tuple[str, int]] = field(default_factory=list)
    db_numeric: dict[str, list] = field(default_factory=dict)  # owner -> non-string db args


# ---------------------------------------------------------------------------
# File parser
# ---------------------------------------------------------------------------


class CondStack:
    """Tracks if/elif/else/endc.  Evaluates DEF(FAITHFUL)/DEF(DEBUG) as
    undefined (the user's ROM is the normal build); other conditions are
    treated as true but recorded."""

    def __init__(self, defined=()):
        self.defined = set(defined)
        self.stack: list[tuple[bool, bool, str]] = []  # (active, any_taken, desc)

    def _eval(self, expr: str) -> bool | None:
        e = expr.replace(" ", "")
        m = re.fullmatch(r"(!?)DEF\((\w+)\)", e)
        if m:
            val = m.group(2) in self.defined
            return (not val) if m.group(1) else val
        return None

    def handle(self, instr: str, args: str) -> bool:
        """Return True if the line was a conditional directive."""
        low = instr.lower()
        if low == "if":
            v = self._eval(args)
            desc = args.strip()
            if v is None:
                v = True
                desc += " (assumed true)"
            self.stack.append((v, v, desc))
            return True
        if low == "elif":
            act, taken, desc = self.stack.pop()
            v = self._eval(args)
            v = True if v is None else v
            self.stack.append(((not taken) and v, taken or v, "elif " + args.strip()))
            return True
        if low == "else":
            act, taken, desc = self.stack.pop()
            self.stack.append((not taken, True, "else of " + desc))
            return True
        if low == "endc":
            self.stack.pop()
            return True
        return False

    @property
    def active(self) -> bool:
        return all(a for a, _, _ in self.stack)

    @property
    def desc(self) -> str:
        return " / ".join(d for _, _, d in self.stack)


def parse_map_file(path: str, cm: Charmap, defined=()) -> FileScan:
    stem = os.path.splitext(os.path.basename(path))[0]
    fs = FileScan(path=path, stem=stem)
    cond = CondStack(defined)

    cur_global: str | None = None
    cur_local: str | None = None
    pending_label: str | None = None  # label with nothing emitted after it yet
    stacked: list[str] = []  # all labels stacked on the same address
    pending_inline: tuple[str, str, int] | None = None  # (cmd, owner, line)
    inline_counter: dict[str, int] = collections.Counter()
    db_counter: dict[str, int] = collections.Counter()
    block: TextBlock | None = None
    charmap = "default"
    label_at_if: list[tuple] = []
    last_menu: str | None = None

    def owner() -> str:
        if cur_global is None:
            return "<toplevel>"
        return cur_global + ("." + cur_local if cur_local else "")

    def close_block(line_no: int, term: str | None, problem: str | None = None):
        nonlocal block
        if block is None:
            return
        block.line_end = line_no
        block.terminator = term
        block.active = any(tc.active for tc in block.commands)
        if not block.active:
            # same label is assembled in another branch: keep ids unique
            tag = re.sub(r"[^A-Za-z0-9]+", "_", block.cond).strip("_") or "inactive"
            block.id += "!" + tag
        if problem:
            block.problems.append(problem)
        fs.blocks.append(block)
        block = None

    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    in_macro = False
    for idx, raw in enumerate(lines, 1):
        code = strip_comment(raw)
        if not code.strip():
            continue
        # skip local MACRO ... ENDM bodies (e.g. FightingDojo rematch_script builds
        # text label names by concatenation: writetext \1Text_Greeting)
        first = code.split(None, 1)[0].lower()
        if first == "macro":
            in_macro = True
            fs.macros.append((code.split()[1] if len(code.split()) > 1 else "?", idx))
            continue
        if in_macro:
            if first == "endm":
                in_macro = False
            continue

        # ---- label(s) at column 0 ----------------------------------------
        rest = code
        if not code[0].isspace():
            m_sl = RE_SCOPED_LOCAL.match(code)
            m_g = RE_GLOBAL.match(code)
            m_l = RE_LOCAL.match(code)
            label_fq = None
            if m_sl:
                cur_global, cur_local = m_sl.group(1), m_sl.group(2)
                label_fq = owner()
                rest = m_sl.group(4)
            elif m_l:
                cur_local = m_l.group(1)
                label_fq = owner()
                rest = m_l.group(2)
            elif m_g:
                cur_global, cur_local = m_g.group(1), None
                label_fq = owner()
                rest = m_g.group(3)
            if label_fq is not None:
                fs.labels.append((label_fq, idx))
                if block is not None:
                    # label inside an open text block: the block has a shared tail
                    block.tail_labels.append(label_fq)
                if pending_label is not None and block is None:
                    stacked.append(label_fq)  # several labels on one address
                else:
                    stacked = [label_fq]
                pending_label = label_fq
                pending_inline = None
                rest = rest.strip()
                if not rest:
                    continue

        m = RE_INSTR.match(rest.strip())
        if not m:
            continue
        instr, argstr = m.group(1), m.group(2)
        low = instr.lower()

        # ---- conditionals -----------------------------------------------
        if low == "if":
            label_at_if.append((pending_label, pending_inline, list(stacked)))
        elif low in ("else", "elif") and label_at_if:
            # each branch starts with the same pending label / inline owner
            if label_at_if[-1][0] is not None or label_at_if[-1][1] is not None:
                if block is None:
                    pending_label, pending_inline, stacked = (
                        label_at_if[-1][0],
                        label_at_if[-1][1],
                        list(label_at_if[-1][2]),
                    )
        elif low == "endc" and label_at_if:
            label_at_if.pop()
        if cond.handle(low, argstr):
            continue

        if low in TRANSPARENT_DIRECTIVES:
            continue

        if low == "setcharmap":
            charmap = argstr.strip()
            continue

        args = split_args(argstr) if argstr.strip() else []

        # ---- text commands ----------------------------------------------
        is_text = low in TEXT_CMDS and not (low == "next" and charmap == "no_ngrams")
        if is_text:
            if block is None:
                o = owner()
                if pending_inline is not None:
                    icmd, iowner, _ = pending_inline
                    inline_counter[iowner] += 1
                    bid = f"{stem}:{iowner}+{inline_counter[iowner]}"
                    block = TextBlock(
                        id=bid,
                        file=path,
                        owner=iowner,
                        kind="inline",
                        inline_cmd=icmd,
                        line_start=idx,
                    )
                elif pending_label is not None:
                    first = stacked[0] if stacked else pending_label
                    block = TextBlock(
                        id=f"{stem}:{first}",
                        file=path,
                        owner=first,
                        kind="label",
                        inline_cmd=None,
                        line_start=idx,
                    )
                    block.aliases.extend(label for label in stacked[1:])
                else:
                    inline_counter["~orphan~" + o] += 1
                    bid = f"{stem}:{o}~{inline_counter['~orphan~' + o]}"
                    block = TextBlock(
                        id=bid, file=path, owner=o, kind="orphan", inline_cmd=None, line_start=idx
                    )
                    block.problems.append("text without label or inline script command")
                block.cond = cond.desc
                if low not in ("text", "text_start", "text_ram", "text_decimal", "text_far"):
                    block.problems.append(f"block starts with {low}")
                pending_label = None
                pending_inline = None
            tc = TextCmd(cmd=low, args=args, line=idx, active=cond.active)
            if low in TEXT_STRING_CMDS:
                for a in args:
                    s = unquote(a)
                    if s is None:
                        block.problems.append(f"non-literal arg {a!r} at line {idx}")
                    else:
                        tc.strings.append(s)
            if block.commands and cond.active != block.commands[-1].active:
                block.problems.append(f"conditional inside block (line {idx})")
            block.commands.append(tc)
            if low in TERMINATORS:
                close_block(idx, low)
            elif low == "text_asm":
                close_block(idx, low)
            elif low in TEXT_STRING_CMDS and tc.strings and tc.strings[-1].endswith("@"):
                close_block(idx, "@")
            continue

        # ---- non-text instruction ----------------------------------------
        if block is not None:
            close_block(idx - 1, None, f"unterminated: next instruction {low!r} at line {idx}")

        if low in INLINE_TEXT_SCRIPT_CMDS:
            pending_inline = (low, owner(), idx)
            pending_label = None
            if low not in TEXT_POINTER_CMDS:
                continue

        if low in TEXT_POINTER_CMDS:
            for ai in TEXT_POINTER_CMDS[low]:
                if ai < len(args):
                    lab = args[ai].strip()
                    if (
                        lab
                        and re.fullmatch(r"\.?" + LABEL_CHARS + r"+(\." + LABEL_CHARS + r"+)?", lab)
                        and not lab.isdigit()
                        and not lab.startswith("$")
                    ):
                        res = (cur_global + lab) if lab.startswith(".") and cur_global else lab
                        fs.refs.append(Ref(path, idx, low, lab, res, ai))
        elif (
            low == "object_event"
            and len(args) >= 11
            and args[8].strip() == "OBJECTTYPE_COMMAND"
            and args[9].strip()
            in ("jumptextfaceplayer", "jumptext", "jumpopenedtext", "farjumptext")
        ):
            lab = args[10].strip()
            res = (cur_global + lab) if lab.startswith(".") and cur_global else lab
            fs.refs.append(Ref(path, idx, "object_event:" + args[9].strip(), lab, res))
        elif low == "pokemon_event" and len(args) in (8, 9):
            lab = args[len(args) - 2].strip()  # text shown with the cry
            res = (cur_global + lab) if lab.startswith(".") and cur_global else lab
            fs.refs.append(Ref(path, idx, "pokemon_event", lab, res, len(args) - 2))
        elif low == "bg_event" and len(args) >= 4 and "JUMPTEXT" in args[2]:
            lab = args[3].strip()
            fs.refs.append(Ref(path, idx, "bg_event:" + args[2].strip(), lab, lab))

        # ---- menu headers (loadmenu targets) ------------------------------
        if low == "menu_coords" and len(args) == 4:
            fs.menu_headers[owner()] = {
                "coords": [a.strip() for a in args],
                "line": idx,
                "data": None,
            }
            last_menu = owner()
        elif (
            low == "dw"
            and args
            and last_menu == owner()
            and fs.menu_headers[last_menu]["data"] is None
        ):
            lab = args[0].strip()
            fs.menu_headers[last_menu]["data"] = (cur_global + lab) if lab.startswith(".") else lab
        if low == "db" and args and all(unquote(a) is None for a in args):
            fs.db_numeric.setdefault(owner(), []).append(args)
        if low == "dba" and args:
            fs.db_numeric.setdefault(owner(), []).append(["dba"] + args)

        if low in ("db", "rawchar") or (low == "next" and charmap == "no_ngrams"):
            strs = [unquote(a) for a in args]
            strs = [s for s in strs if s is not None]
            if strs:
                o = owner()
                k = db_counter[o]
                db_counter[o] += 1
                fs.dbstrings.append(
                    DbString(
                        id=f"{stem}:{o}[{k}]",
                        file=path,
                        owner=o,
                        index=k,
                        line=idx,
                        directive=low,
                        charmap="no_ngrams" if low == "rawchar" else charmap,
                        text="".join(strs),
                        raw_args=args,
                        active=cond.active,
                        cond=cond.desc,
                    )
                )
            pending_label = None  # bytes were emitted: a following label is a new address
            stacked = []
            continue

        pending_label = None
        if low not in INLINE_TEXT_SCRIPT_CMDS:
            pending_inline = None

    if block is not None:
        close_block(len(lines), None, "unterminated at EOF")
    return fs


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

RAM_WIDTH = {  # worst-case widths of text_ram sources seen in maps
    "wStringBuffer1": 12,  # item / key item names (ITEM_NAME_LENGTH - 1)
    "wStringBuffer3": 12,  # mon (10), item/TM (12), trainer name (10), badge (getstring)
    "wStringBuffer4": 12,
}


def analyse_block(cm: Charmap, b: TextBlock) -> None:
    """Split the block into displayed rows and compute widths."""
    rows: list[dict] = []
    cur = None
    para = 0

    def new_row(cmd, line):
        nonlocal cur
        cur = {
            "cmd": cmd,
            "line": line,
            "para": para,
            "src": "",
            "min": 0,
            "max": 0,
            "specials": [],
            "unknown": [],
            "parts": [],
        }
        rows.append(cur)

    for tc in b.commands:
        c = tc.cmd
        if b.active and not tc.active:
            continue  # line from a FAITHFUL/DEBUG branch that is not assembled
        if c in TEXT_STRING_CMDS:
            if c == "para":
                para += 1
            if c in NEW_LINE_CMDS or cur is None or (c == "text" and cur is None):
                new_row(c, tc.line)
            for s in tc.strings:
                lo, hi, sp, unk = glyph_width(cm, s)
                cur["src"] += s
                cur["min"] += lo
                cur["max"] += hi
                cur["specials"] += sp
                cur["unknown"] += unk
                cur["parts"].append(("str", s))
                for t in sp:
                    if t in ("<LINE>", "<CONT>", "<PARA>", "<NEXT>", "<LNBRK>"):
                        cur["embedded_break"] = True
        elif c in ("text_ram", "text_decimal", "text_plural", "text_today"):
            if cur is None:
                new_row(c, tc.line)
            if c == "text_ram":
                src = tc.args[0] if tc.args else "?"
                w = RAM_WIDTH.get(src, 12)
                cur["min"] += 1
                cur["max"] += w
                cur["parts"].append(("ram", src))
                cur["src"] += "{" + src + "}"
            elif c == "text_decimal":
                digits = (
                    int(tc.args[2], 0) if len(tc.args) >= 3 and tc.args[2].strip().isdigit() else 5
                )
                cur["min"] += 1
                cur["max"] += digits
                cur["parts"].append(("num", ",".join(tc.args)))
                cur["src"] += "{num:" + (tc.args[0] if tc.args else "?") + "}"
            elif c == "text_plural":
                cur["max"] += 2
                cur["parts"].append(("plural", ""))
                cur["src"] += "{plural}"
            elif c == "text_today":
                cur["max"] += 9
                cur["parts"].append(("day", ""))
        # text_promptbutton etc. do not change the row
    b.rows = rows


# ---------------------------------------------------------------------------
# Driver / report
# ---------------------------------------------------------------------------

# how a reference determines the display role of a block
REF_ROLE = {
    "writetext": "textbox",
    "jumptext": "textbox",
    "jumptextfaceplayer": "textbox",
    "jumpopenedtext": "textbox",
    "showtext": "textbox",
    "showtextfaceplayer": "textbox",
    "showcrytext": "textbox",
    "iftrue_jumptext": "textbox",
    "iffalse_jumptext": "textbox",
    "iftrue_jumptextfaceplayer": "textbox",
    "iffalse_jumptextfaceplayer": "textbox",
    "iftrue_jumpopenedtext": "textbox",
    "iffalse_jumpopenedtext": "textbox",
    "farwritetext": "textbox",
    "farjumptext": "textbox",
    "object_event:jumptextfaceplayer": "npc",
    "object_event:jumptext": "npc",
    "object_event:jumpopenedtext": "npc",
    "pokemon_event": "pokemon_cry",
    "bg_event:BGEVENT_JUMPTEXT": "sign",
}


def assign_roles(scans: list[FileScan]) -> None:
    by_label: dict[str, TextBlock] = {}
    for fs in scans:
        for b in fs.blocks:
            if b.kind == "label":
                by_label[b.owner] = b
            for a in b.aliases + b.tail_labels:
                by_label.setdefault(a, b)
            if b.kind == "inline":
                b.roles.append(
                    "trainer_after" if b.inline_cmd == "generictrainer" else "textbox_inline"
                )
    for fs in scans:
        for r in fs.refs:
            b = by_label.get(r.resolved)
            if b is None:
                continue
            if r.cmd == "winlosstext":
                role = ("battle_win", "battle_loss")[r.argi]
            elif r.cmd == "trainer":
                role = ("trainer_seen", "battle_win", "battle_loss")[r.argi - 3]
            elif r.cmd == "generictrainer":
                role = ("trainer_seen", "battle_win")[r.argi - 3]
            else:
                role = REF_ROLE.get(r.cmd, r.cmd)
            if role not in b.roles:
                b.roles.append(role)


def load_numeric_defs(root: str, paths: list[str]) -> dict[str, int]:
    """DEF NAME EQU <integer literal> from the given files (good enough for
    the {d:NAME} interpolations used in map strings)."""
    out = {}
    rx = re.compile(r"^\s*DEF\s+(\w+)\s+EQU\s+(\$?[0-9A-Fa-f]+|%[01]+)\s*$", re.I)
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = rx.match(strip_comment(line))
                if m:
                    v = m.group(2)
                    try:
                        out[m.group(1)] = (
                            int(v[1:], 16)
                            if v.startswith("$")
                            else int(v[1:], 2)
                            if v.startswith("%")
                            else int(v)
                        )
                    except ValueError:
                        pass
    return out


def scan_tree(
    root: str, files: list[str] | None = None, defined=()
) -> tuple[Charmap, list[FileScan]]:
    cm = Charmap(root)
    cdir = os.path.join(root, "constants")
    mdir = os.path.join(root, "maps")
    DEFS.update(
        load_numeric_defs(
            root,
            [os.path.join(cdir, n) for n in os.listdir(cdir) if n.endswith(".asm")]
            + [os.path.join(mdir, n) for n in os.listdir(mdir) if n.endswith(".asm")],
        )
    )
    # derived constants that are not plain literals
    tmhm = os.path.join(cdir, "tmhm_constants.asm")
    if os.path.exists(tmhm) and "NUM_TMS" not in DEFS:
        with open(tmhm, encoding="utf-8") as f:
            DEFS["NUM_TMS"] = sum(1 for line in f if re.match(r"\s*add_tm\b", line))
    mapdir = os.path.join(root, "maps")
    names = files or sorted(n for n in os.listdir(mapdir) if n.endswith(".asm"))
    scans = []
    for n in names:
        fs = parse_map_file(os.path.join(mapdir, os.path.basename(n)), cm, defined)
        for b in fs.blocks:
            analyse_block(cm, b)
        scans.append(fs)
    assign_roles(scans)
    return cm, scans


def menu_report(cm: Charmap, scans: list[FileScan], out=sys.stdout) -> list[dict]:
    """Fit of db item strings in their loadmenu boxes.
    Item text starts at x1+1 (+1 more if flags bit 7, home/menu.asm
    GetMenuTextStartCoord) and must end before the right border x2."""
    res = []
    for fs in scans:
        for hdr, info in fs.menu_headers.items():
            data = info["data"]
            if not data:
                continue
            x1, y1, x2, y2 = info["coords"]
            try:
                x1, x2, y1, y2 = int(x1), int(x2), int(y1), int(y2)
            except ValueError:
                continue
            nums = fs.db_numeric.get(data, [])
            flags = 0
            if nums and nums[0] and nums[0][0] != "dba":
                try:
                    flags = int(nums[0][0].replace("$", "0x"), 0)
                except ValueError:
                    flags = 0
            # 2D menus keep their strings under a separate label (dba .Text)
            src = data
            for n in nums:
                if n and n[0] == "dba":
                    lab = n[1].strip()
                    src = (data.split(".")[0] + lab) if lab.startswith(".") else lab
            items = [d for d in fs.dbstrings if d.owner == src]
            start = x1 + 1 + (1 if flags & 0x80 else 0)
            avail = x2 - start
            widths = [glyph_width(cm, d.text.rstrip("@"))[1] for d in items]
            r = {
                "file": fs.stem,
                "header": hdr,
                "data": src,
                "coords": (x1, y1, x2, y2),
                "flags": flags,
                "avail": avail,
                "n": len(items),
                "maxw": max(widths or [0]),
                "ids": [d.id for d in items],
            }
            res.append(r)
    print("\nmenus defined in maps/ (loadmenu headers):", len(res), file=out)
    for r in res:
        print(
            f"   {r['file']}:{r['header']} box={r['coords']} flags=${r['flags']:02x} "
            f"items={r['n']} maxw={r['maxw']} avail={r['avail']}"
            + ("  OVER" if r["maxw"] > r["avail"] else ""),
            file=out,
        )
    return res
