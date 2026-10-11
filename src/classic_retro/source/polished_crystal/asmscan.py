"""Generic line scanner for the Polished Crystal RGBDS sources.

It walks the INCLUDE tree of the default (non-FAITHFUL, non-DEBUG) build in
assembly order and turns every source line into a `Stmt` record:
labels, the directive and its arguments, the decoded string literals, the
conditional state (`active` = assembled in the scanned build), the charmap in
force and the enclosing conditional blocks (so an entry that crosses an
if/else/endc can be widened to the whole conditional).

MACRO ... ENDM and REPT/FOR ... ENDR bodies are recorded as `in_macro` and
never yield text.  No third-party dependencies.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Objects of the default `make` target (Makefile rom_obj); each is assembled
# from the .asm of the same name.
ROM_OBJECTS = [
    "main",
    "home",
    "ram",
    "audio",
    "audio/music_player",
    "data/pokemon/dex_entries",
    "data/pokemon/egg_moves",
    "data/pokemon/evos_attacks",
    "data/maps/map_data",
    "data/text/common",
    "data/tilesets",
    "engine/movie/credits",
    "engine/overworld/events",
    "gfx/minis_icons",
    "gfx/pokemon",
    "gfx/sprites",
    "gfx/trainers",
    "gfx/items",
    "gfx/misc",
]


def rom_objects(root: str) -> list[str]:
    """Read rom_obj from the Makefile (falls back to the 3.2.3 list)."""
    try:
        with open(os.path.join(root, "Makefile"), encoding="utf-8") as f:
            mk = f.read()
        m = re.search(r"^rom_obj\s*:=\s*((?:.*\\\n)*.*)$", mk, re.M)
        if m:
            objs = re.findall(r"([\w/]+)\.o", m.group(1))
            if objs:
                return objs
    except OSError:
        pass
    return list(ROM_OBJECTS)


# ---------------------------------------------------------------------------
# lexing
# ---------------------------------------------------------------------------


def split_comment(line: str) -> tuple[str, str]:
    """(code, comment) -- the comment starts at the first ';' outside strings."""
    in_str = False
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == ";":
                return line[:i].rstrip(), line[i:]
            if c == '"':
                in_str = True
        i += 1
    return line.rstrip(), ""


def split_args(s: str) -> list[str]:
    """Split a directive argument list on top-level commas."""
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
        elif c in "([":
            depth += 1
            cur.append(c)
        elif c in ")]":
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


_ESC = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "{": "\x00LBRACE",
    "}": "\x00RBRACE",
    ",": ",",
    "(": "(",
    ")": ")",
}


def unquote(arg: str) -> str | None:
    """Content of a single "..." literal, or None.  `{...}` interpolations are
    kept verbatim; escaped braces are returned as literal braces."""
    arg = arg.strip()
    if len(arg) < 2 or arg[0] != '"' or arg[-1] != '"':
        return None
    body = arg[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            e = _ESC.get(body[i + 1], body[i + 1])
            out.append({"\x00LBRACE": "\\{", "\x00RBRACE": "\\}"}.get(e, e))
            i += 2
            continue
        if c == '"':
            return None
        out.append(c)
        i += 1
    return "".join(out)


LABEL_CHARS = r"[A-Za-z0-9_@#$]"
RE_SCOPED = re.compile(r"^([A-Za-z_]" + LABEL_CHARS + r"*)\.(" + LABEL_CHARS + r"+)(::?)(.*)$")
RE_GLOBAL = re.compile(r"^([A-Za-z_]" + LABEL_CHARS + r"*)(::?)(.*)$")
RE_LOCAL = re.compile(r"^\.(" + LABEL_CHARS + r"+)(::?)?(?=\s|$)(.*)$")
RE_WORD = re.compile(r"^([A-Za-z_][A-Za-z0-9_?]*)\b\s*(.*)$")

NON_LABEL_WORDS = {
    "def",
    "redef",
    "section",
    "include",
    "incbin",
    "macro",
    "endm",
    "if",
    "elif",
    "else",
    "endc",
    "rept",
    "for",
    "endr",
    "assert",
    "static_assert",
    "charmap",
    "setcharmap",
    "newcharmap",
    "pushc",
    "popc",
    "load",
    "endl",
    "export",
    "purge",
    "opt",
    "pusho",
    "popo",
    "println",
    "print",
    "fail",
    "warn",
    "endsection",
    "pushs",
    "pops",
    "union",
    "nextu",
    "endu",
    "ds",
    "db",
    "dw",
    "dl",
}


# ---------------------------------------------------------------------------
# constants (for {d:X}, conditionals, text_decimal digits)
# ---------------------------------------------------------------------------


class Consts:
    """A small evaluator for DEF X EQU expr / const_def / const lines."""

    def __init__(self):
        self.vals: dict[str, int] = {}

    def load_tree(self, root: str):
        paths = []
        for d in ("constants",):
            for dp, _, fn in os.walk(os.path.join(root, d)):
                for f in sorted(fn):
                    if f.endswith(".asm"):
                        paths.append(os.path.join(dp, f))
        for dp, _, fn in os.walk(os.path.join(root, "maps")):
            for f in sorted(fn):
                if f.endswith(".asm"):
                    paths.append(os.path.join(dp, f))
        # two passes so forward references resolve
        for _ in range(2):
            for p in paths:
                self._load(p)
        # derived: NUM_TMS etc. counted from add_tm lines
        tm = os.path.join(root, "constants", "item_constants.asm")
        if "NUM_TMS" not in self.vals and os.path.exists(tm):
            with open(tm, encoding="utf-8") as f:
                n = sum(1 for line in f if re.match(r"\s*add_tm\b", line))
            if n:
                self.vals["NUM_TMS"] = n

    def _load(self, path):
        const_val = 0
        step = 1
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                code, _ = split_comment(raw)
                s = code.strip()
                if not s:
                    continue
                m = re.match(r"(?i)(?:re)?def\s+(\w+)\s+(?:equ|=)\s+(.+)$", s)
                if m:
                    v = self.eval(m.group(2))
                    if v is not None:
                        self.vals[m.group(1)] = v
                    continue
                m = re.match(r"(?i)const_def(?:\s+(.+))?$", s)
                if m:
                    a = split_args(m.group(1) or "")
                    const_val = self.eval(a[0]) if a and a[0] else 0
                    step = self.eval(a[1]) if len(a) > 1 else 1
                    const_val = const_val or 0
                    step = step if step is not None else 1
                    continue
                m = re.match(r"(?i)const\s+(\w+)$", s)
                if m:
                    self.vals[m.group(1)] = const_val
                    const_val += step
                    continue
                m = re.match(r"(?i)const_skip(?:\s+(.+))?$", s)
                if m:
                    k = self.eval(m.group(1)) if m.group(1) else 1
                    const_val += (k or 1) * step
                    continue
                m = re.match(r"(?i)const_next\s+(.+)$", s)
                if m:
                    v = self.eval(m.group(1))
                    if v is not None:
                        const_val = v

    _TOK = re.compile(
        r"\s*(\$[0-9A-Fa-f_]+|%[01_]+|&[0-7]+|\d[\d_]*|[A-Za-z_][\w.]*|<<|>>|==|!=|<=|>=|&&|\|\||[-+*/%()&|^~!<>])"
    )

    def eval(self, expr: str) -> int | None:
        """Evaluate a simple integer expression; None if unknown."""
        if expr is None:
            return None
        expr = expr.strip()
        toks = []
        pos = 0
        while pos < len(expr):
            m = self._TOK.match(expr, pos)
            if not m:
                return None
            toks.append(m.group(1))
            pos = m.end()
        py = []
        for t in toks:
            if t.startswith("$"):
                py.append(str(int(t[1:].replace("_", ""), 16)))
            elif t.startswith("%"):
                py.append(str(int(t[1:].replace("_", ""), 2)))
            elif t.startswith("&") and len(t) > 1 and t[1].isdigit():
                py.append(str(int(t[1:], 8)))
            elif t[0].isdigit():
                py.append(t.replace("_", ""))
            elif re.match(r"[A-Za-z_]", t):
                if t.upper() in ("HIGH", "LOW", "DEF", "BANK", "STRLEN", "CHARLEN"):
                    return None
                if t not in self.vals:
                    return None
                py.append(str(self.vals[t]))
            elif t == "&&":
                py.append(" and ")
            elif t == "||":
                py.append(" or ")
            elif t == "!":
                py.append(" not ")
            elif t == "/":
                py.append("//")
            else:
                py.append(t)
        try:
            v = eval("".join(py), {"__builtins__": {}}, {})  # noqa: S307 (numbers only)
        except Exception:
            return None
        if isinstance(v, bool):
            return int(v)
        return v if isinstance(v, int) else None


# ---------------------------------------------------------------------------
# statements
# ---------------------------------------------------------------------------


@dataclass
class CondBlock:
    id: int
    file: str
    if_line: int
    else_lines: list[int] = field(default_factory=list)
    endc_line: int = 0
    expr: str = ""


@dataclass
class Stmt:
    file: str  # path relative to the root
    line: int  # 1-based
    raw: str  # the full source line (no newline)
    code: str  # comment stripped
    comment: str
    labels: list[str]  # fully qualified labels defined on this line
    label_prefix: str  # the exact text of the label(s) part of the line ('' if none)
    directive: str  # lower-case directive / macro name ('' if none)
    directive_raw: str  # as written
    argstr: str
    args: list[str]
    strings: list[str | None]  # decoded literal per arg (None for non-literal args)
    active: bool
    cond: str  # description of enclosing conditionals
    cond_ids: tuple[int, ...]
    charmap: str
    glabel: str | None
    llabel: str | None
    kind: str  # 'stmt' | 'label' | 'cond' | 'blank' | 'macro'
    index: int = 0  # position in the file's statement list

    @property
    def owner(self) -> str:
        if self.glabel is None:
            return "<top>"
        return self.glabel + ("." + self.llabel if self.llabel else "")

    @property
    def has_strings(self) -> bool:
        return any(s is not None for s in self.strings)


@dataclass
class FileScan:
    path: str
    stmts: list[Stmt]
    conds: dict[int, CondBlock]
    include_from: str | None = None


class CondState:
    def __init__(self, defined):
        self.defined = set(defined)
        self.stack: list[list] = []  # [active, taken, desc, id]

    def evaluate(self, expr: str, consts: Consts) -> tuple[bool, bool]:
        """(value, known)"""
        e = expr.strip()

        def repl(m):
            return "1" if m.group(1) in self.defined else "0"

        e2 = re.sub(r"DEF\s*\(\s*\{?(\w+)\}?\s*\)", repl, e)
        e2 = re.sub(r"\bDEF\s+(\w+)", repl, e2)
        v = consts.eval(e2)
        if v is None:
            return True, False
        return bool(v), True

    @property
    def active(self):
        return all(x[0] for x in self.stack)

    @property
    def desc(self):
        return " / ".join(x[2] for x in self.stack)

    @property
    def ids(self):
        return tuple(x[3] for x in self.stack)


class TreeScanner:
    """Scan the include tree of a build."""

    def __init__(self, root: str, defined=(), consts: Consts | None = None):
        self.root = root
        self.defined = set(defined)
        self.consts = consts or Consts()
        if consts is None:
            self.consts.load_tree(root)
        self.files: dict[str, FileScan] = {}
        self.order: list[str] = []
        self._cond_counter = 0
        self.unknown_conds: list[tuple[str, int, str]] = []

    def scan(self):
        charmap = ["default"]
        for obj in rom_objects(self.root):
            p = obj + ".asm"
            if os.path.exists(os.path.join(self.root, p)):
                charmap = ["default"]
                self._scan_file(p, charmap, None)
        return self

    def _scan_file(self, rel: str, charmap: list, parent: str | None):
        if rel in self.files:
            return
        path = os.path.join(self.root, rel)
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        cs = CondState(self.defined)
        fs = FileScan(path=rel, stmts=[], conds={}, include_from=parent)
        self.files[rel] = fs
        self.order.append(rel)
        glabel: str | None = None
        llabel: str | None = None
        in_macro = 0
        in_rept = 0
        for idx, raw in enumerate(lines, 1):
            code, comment = split_comment(raw)
            stripped = code.strip()
            base = dict(
                file=rel,
                line=idx,
                raw=raw,
                code=code,
                comment=comment,
                labels=[],
                label_prefix="",
                directive="",
                directive_raw="",
                argstr="",
                args=[],
                strings=[],
                active=cs.active,
                cond=cs.desc,
                cond_ids=cs.ids,
                charmap=charmap[0],
                glabel=glabel,
                llabel=llabel,
                kind="blank",
            )
            if not stripped:
                fs.stmts.append(Stmt(**base))
                continue
            first = stripped.split(None, 1)[0].lower()
            first = first.rstrip(":")
            # macro / rept bodies
            if in_macro:
                if first == "endm":
                    in_macro -= 1
                base["kind"] = "macro"
                fs.stmts.append(Stmt(**base))
                continue
            if first in ("macro",) or re.match(r"(?i)^macro\b", stripped):
                in_macro += 1
                base["kind"] = "macro"
                fs.stmts.append(Stmt(**base))
                continue
            if in_rept:
                if first == "endr":
                    in_rept -= 1
                elif first in ("rept", "for"):
                    in_rept += 1
                base["kind"] = "macro"
                fs.stmts.append(Stmt(**base))
                continue
            if first in ("rept", "for"):
                in_rept += 1
                base["kind"] = "macro"
                fs.stmts.append(Stmt(**base))
                continue

            rest = code
            labels = []
            label_prefix = ""
            if code and not code[0].isspace():
                m_s = RE_SCOPED.match(code)
                m_l = RE_LOCAL.match(code)
                m_g = RE_GLOBAL.match(code)
                if m_s:
                    glabel, llabel = m_s.group(1), m_s.group(2)
                    labels.append(f"{glabel}.{llabel}")
                    rest = m_s.group(4)
                elif m_l:
                    llabel = m_l.group(1)
                    labels.append(f"{glabel}.{llabel}" if glabel else "." + llabel)
                    rest = m_l.group(3)
                elif m_g and m_g.group(1).lower() not in NON_LABEL_WORDS:
                    glabel, llabel = m_g.group(1), None
                    labels.append(glabel)
                    rest = m_g.group(3)
                if labels:
                    label_prefix = code[: len(code) - len(rest)]
            base["labels"] = labels
            base["label_prefix"] = label_prefix
            base["glabel"] = glabel
            base["llabel"] = llabel
            body = rest.strip()
            if not body:
                base["kind"] = "label" if labels else "blank"
                fs.stmts.append(Stmt(**base))
                continue
            m = RE_WORD.match(body)
            if not m:
                base["kind"] = "stmt"
                base["argstr"] = body
                fs.stmts.append(Stmt(**base))
                continue
            word, argstr = m.group(1), m.group(2)
            low = word.lower()
            # conditionals
            if low in ("if", "elif", "else", "endc"):
                if low == "if":
                    self._cond_counter += 1
                    cid = self._cond_counter
                    v, known = cs.evaluate(argstr, self.consts)
                    if not known:
                        self.unknown_conds.append((rel, idx, argstr))
                    cs.stack.append([v, v, argstr.strip(), cid])
                    fs.conds[cid] = CondBlock(cid, rel, idx, expr=argstr.strip())
                elif low == "elif":
                    act, taken, desc, cid = cs.stack.pop()
                    v, known = cs.evaluate(argstr, self.consts)
                    cs.stack.append([(not taken) and v, taken or v, "elif " + argstr.strip(), cid])
                    fs.conds[cid].else_lines.append(idx)
                elif low == "else":
                    act, taken, desc, cid = cs.stack.pop()
                    cs.stack.append([not taken, True, "else of " + desc, cid])
                    fs.conds[cid].else_lines.append(idx)
                else:
                    if cs.stack:
                        _, _, _, cid = cs.stack.pop()
                        fs.conds[cid].endc_line = idx
                base.update(
                    kind="cond",
                    directive=low,
                    directive_raw=word,
                    argstr=argstr,
                    active=cs.active if low == "endc" else base["active"],
                    cond_ids=base["cond_ids"] if low != "if" else base["cond_ids"] + (cs.ids[-1],),
                )
                fs.stmts.append(Stmt(**base))
                continue
            args = split_args(argstr) if argstr.strip() else []
            strings = [unquote(a) for a in args]
            base.update(
                kind="stmt",
                directive=low,
                directive_raw=word,
                argstr=argstr,
                args=args,
                strings=strings,
            )
            st = Stmt(**base)
            fs.stmts.append(st)
            if not cs.active:
                continue
            if low == "setcharmap" and args:
                charmap[0] = args[0].strip()
            elif low == "include" and args:
                inc = unquote(args[0])
                if inc and inc.endswith(".asm") and os.path.exists(os.path.join(self.root, inc)):
                    self._scan_file(inc, charmap, rel)
        for i, s in enumerate(fs.stmts):
            s.index = i
        return fs

    # -- helpers -----------------------------------------------------------
    def stmt_files(self, prefix=""):
        return [f for f in self.order if f.startswith(prefix)]
