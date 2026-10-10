"""The extractor: every player-visible text of Polished Crystal as a manifest entry.

The extractor reads the tree the overlay builds on (the pinned source with the
engine patch applied), groups each text's statements into a unit (``units``)
and gives every unit a stable id, a kind, the line range it owns, a pin of
those lines, its placeholders, its limits and a context. Which unit becomes
which kind of entry, with which limits and context, is decided per file by the
handlers below; the limits come from the research done on the game (data tables,
map scripts, engine strings) and from the engine-patched screens (``screen.ROOM``:
the real room of menu items, labels and name fields). The engine strings' layout
notes ship with the overlay (``data/engine_strings.json``), without any text of the game.

Kinds: ``dialog`` (a text block of the speech box), ``box`` (text wrapped in a
box of its own: descriptions, the Pokédex), ``string`` (a menu item, a label, a
name) and ``field`` (a fixed-size name). The originals (``originals``) are the
English converted into the translators' notation: they are for a translator's
local workspace and never leave the user's machine.
"""

from __future__ import annotations

import collections
import io
import json
import os
import re
import sys
from functools import cache
from importlib.resources import files

from classic_retro.source.polished_crystal import asmscan, screen
from classic_retro.source.polished_crystal import encode as ENC
from classic_retro.source.polished_crystal import units as X

PH_DEFAULT_DIALOG_WIDTH = 18
# The two tiles that spell PKMN: a menu item made of them alone (the battle menu's) is a
# word of its own in Arabic.
_PKMN = "<PK><MN>"


@cache
def engine_string_notes() -> list[dict]:
    """Layout notes on the engine's strings, by file and label (no text of the game)."""
    data = files("classic_retro.source.polished_crystal").joinpath("data", "engine_strings.json")
    return json.loads(data.read_text(encoding="utf-8"))


# text_ram buffers whose content is known per file group (cells)
RAM_OVERRIDES = {
    "data/phone/": {"wStringBuffer5": 18},  # landmark names (getlandmarkname)
}
RAM_WIDTH_EXTRA = {
    "wStringBuffer5": 18,
    "wOTPartyMonNicknames": 10,
    "wOTTrademonSpeciesName": 10,
    "wPlayerTrademonSpeciesName": 10,
    "wOTTrademonSenderName": 7,
    "wPlayerTrademonSenderName": 7,
    "wBugContestWinnerName": 10,
    "wBreedMon1Nickname": 10,
    "wBreedMon2Nickname": 10,
}


def path_id(path: str) -> str:
    return path[:-4] if path.endswith(".asm") else path


def first_int(s) -> int | None:
    if s is None:
        return None
    m = re.match(r"\s*(\d+)", str(s))
    return int(m.group(1)) if m else None


class Extractor:
    def __init__(self, tree: str, defined=()):
        self.tree = os.path.abspath(tree)
        self.scan = asmscan.TreeScanner(self.tree, defined).scan()
        self.consts = self.scan.consts
        self.cm = X.Charmap(self.tree)
        self.entries: list[dict] = []
        self.originals: dict[str, str] = {}
        self.skipped: list[dict] = []
        self.problems: list[str] = []
        self.ids = set()
        self._lines: dict[str, list[str]] = {}
        self.engstr = {}
        for r in engine_string_notes():
            self.engstr[(r["file"], r["label"])] = r
        self._maps = None
        self.counters = collections.Counter()
        self.dr_groups: dict[str, dict] = {}
        self.dr_member_of: dict[str, list] = collections.defaultdict(list)
        self.claimed: dict[str, set] = collections.defaultdict(set)  # file -> claimed lines

    # ------------------------------------------------------------------
    def lines(self, path) -> list[str]:
        if path not in self._lines:
            with open(os.path.join(self.tree, path), encoding="utf-8") as f:
                t = f.read().split("\n")
            if t and t[-1] == "":
                t.pop()
            self._lines[path] = t
        return self._lines[path]

    def run(self):
        for path in self.scan.order:
            fs = self.scan.files[path]
            if not any(s.kind == "stmt" and s.active and s.has_strings for s in fs.stmts):
                continue
            units = X.build_units(fs)
            handler = self.handler_for(path)
            if handler is None:
                continue
            handler(fs, units)
        self._finish()
        return self

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------
    def handler_for(self, path: str):
        p = path
        if p.startswith("maps/"):
            return self.h_maps
        table = {
            "data/text/common.asm": ("common", "Common text (items, PC, marts, Day-Care, events)"),
            "data/text/std_text.asm": (
                "std_text",
                "Standard script text (Pokémon Center, PC, marts, …)",
            ),
            "data/text/battle.asm": ("battle", "Battle text box"),
            "data/battle_tower/trainer_text.asm": ("battle_tower", "Battle Tower trainer speech"),
            "data/options/descriptions.asm": ("options", "New-game options help (speech box)"),
        }
        if p in table:
            cat, ctx = table[p]
            return lambda fs, units: self.h_dialog_file(fs, units, cat, ctx)
        if p.startswith("data/phone/text/"):
            return self.h_phone
        special = {
            "data/pokemon/dex_entries.asm": self.h_dex,
            "data/pokemon/names.asm": self.h_species,
            "data/moves/names.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "move_names",
                "Move name (battle move list, summary, TM list)",
                width=12,
                bytes_=12,
            ),
            "data/items/names.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "item_names",
                "Item name (bag, marts, PC; copied into text)",
                width=12,
                bytes_=12,
                raw=True,
            ),
            "data/items/key_names.asm": lambda fs, u: self.h_li(
                fs, u, "key_item_names", "Key item name", width=12, bytes_=12
            ),
            "data/items/special_names.asm": lambda fs, u: self.h_li(
                fs, u, "special_item_names", "Special item name", width=12, bytes_=12
            ),
            "data/items/apricorn_names.asm": lambda fs, u: self.h_li(
                fs, u, "apricorn_names", "Apricorn name", width=12, bytes_=12
            ),
            "data/items/wing_names.asm": lambda fs, u: self.h_li(
                fs, u, "wing_names", "Wing name", width=12, bytes_=12
            ),
            "data/items/exp_candy_names.asm": lambda fs, u: self.h_li(
                fs, u, "exp_candy_names", "Exp. Candy name", width=12, bytes_=12
            ),
            "data/trainers/class_names.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "trainer_classes",
                "Trainer class name (<ENEMY>, phone list, trainer card)",
                width=12,
                bytes_=12,
            ),
            "data/events/badge_names.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "badge_names",
                "Badge name (the noun after the word badge where the game tells of a new badge)",
                width=12,
                bytes_=12,
            ),
            "data/decorations/names.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "decoration_names",
                "Decoration name part (composed with colours / Pokémon names in the decoration menu)",
                width=None,
            ),
            "data/mon_menu.asm": lambda fs, u: self.h_li(
                fs, u, "mon_menu", "Party Pokémon submenu item (box text from x=8)", width=None
            ),
            "data/battle/stat_names.asm": lambda fs, u: self.h_li(
                fs, u, "stat_names", "Stat name inside battle / item messages", width=None
            ),
            "data/music_player/song_artists.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "music_artists",
                "Music player: composer / arranger (rows of 20, padded to force a wrap)",
                width=20,
                multi20=True,
            ),
            "data/music_player/song_origins.asm": lambda fs, u: self.h_li(
                fs,
                u,
                "music_origins",
                "Music player: game of origin (after the song number)",
                width=None,
            ),
            "data/music_player/song_info.asm": self.h_song_info,
            "data/abilities/names.asm": self.h_ability_names,
            "data/abilities/descriptions.asm": lambda fs, u: self.h_box_file(
                fs, u, "ability_desc", "Ability description (summary/Pokédex, 2 lines)", 18, 2, 1
            ),
            "data/moves/descriptions.asm": lambda fs, u: self.h_box_file(
                fs,
                u,
                "move_desc",
                "Move description (move screen, TM pocket, battle text box)",
                18,
                2,
                1,
            ),
            "data/items/descriptions.asm": lambda fs, u: self.h_box_file(
                fs, u, "item_desc", "Item description (bag, summary)", 18, 2, 1
            ),
            "data/characteristics.asm": lambda fs, u: self.h_box_file(
                fs,
                u,
                "characteristics",
                "Characteristic (summary memo page, single-spaced rows)",
                10,
                3,
                1,
            ),
            "data/types/names.asm": self.h_types,
            "data/natures.asm": self.h_natures,
            "data/pokedex_bio.asm": lambda fs, u: self.h_dr_strings(
                fs,
                u,
                "dex_bio",
                "Pokédex bio page word (hatch speed / growth rate / body colour)",
                width=11,
            ),
            "data/items/pocket_names.asm": lambda fs, u: self.h_dr_strings(
                fs, u, "pocket_names", "Bag pocket name (put-in-pocket messages)", width=12
            ),
            "data/events/elevator_floors.asm": lambda fs, u: self.h_dr_strings(
                fs, u, "elevator_floors", "Elevator floor (menu box (12,1)-(18,9))", width=5
            ),
            "data/pc/theme_names.asm": lambda fs, u: self.h_dr_strings(
                fs, u, "pc_themes", "Bill's PC box theme name", width=8
            ),
            "data/battle/stat_strings.asm": lambda fs, u: self.h_dr_strings(
                fs, u, "stat_strings", "Stat word inside battle text", width=None
            ),
            "data/pokemon/unown_words.asm": lambda fs, u: self.skip_units(
                fs,
                u,
                "unown_words",
                "Unown dex words: each word starts with its Unown letter; kept in Latin (Unown font)",
            ),
            "data/trainers/parties.asm": self.h_parties,
            "data/trainers/psychic_inver.asm": self.h_parties,
            "data/battle_tower/classes.asm": lambda fs, u: self.h_table_fields(
                fs,
                u,
                "bt_names",
                "Battle Tower trainer name (fixed 10-byte field)",
                size=10,
                width=10,
            ),
            "data/events/wonder_trade/ot_names.asm": lambda fs, u: self.h_table_fields(
                fs,
                u,
                "wonder_trade_ot",
                "Wonder Trade OT name (fixed 8 bytes: ≤7 + @)",
                size=8,
                width=7,
            ),
            "data/default_player_names.asm": lambda fs, u: self.h_table_fields(
                fs,
                u,
                "default_player_names",
                "Default player name (naming screen preset; 8 bytes)",
                size=8,
                width=7,
            ),
            "data/events/npc_trades.asm": self.h_npc_trades,
            "data/maps/landmarks.asm": self.h_landmarks,
            "data/credits_strings.asm": self.h_credits,
            "data/phone/non_trainer_names.asm": self.h_phone_names,
            "data/radio/buenas_passwords.asm": self.h_buena,
            "data/text/ngrams.asm": self.h_ngrams,
            "data/text/plural_table.asm": lambda fs, u: self.skip_stmts(
                fs,
                "plural",
                "plural_table",
                "English plural rules; text_plural does nothing in the Arabic engine",
            ),
            "data/text/input_chars.asm": lambda fs, u: self.skip_units(
                fs,
                u,
                "naming_keyboard",
                "Naming/mail keyboard grids (fixed 9×5 / 10×5 cells); need an Arabic keyboard layout, not a translation",
            ),
            "data/music_player/notes.asm": lambda fs, u: self.skip_units(
                fs, u, "note_names", "Musical note names (fixed 2 bytes, C<SHARP>…): kept in Latin"
            ),
            "data/pc/bad_egg.asm": lambda fs, u: self.skip_units(
                fs,
                u,
                "bad_egg",
                "Bad Egg nickname stored as RLE of character codes; must be hand-encoded",
            ),
        }
        if p in special:
            return special[p]
        if p.startswith(("engine/", "home/", "audio/")) or p in (
            "main.asm",
            "home.asm",
            "audio.asm",
        ):
            return self.h_engine
        if p.startswith("data/"):
            return self.h_generic_data
        return None

    # ------------------------------------------------------------------
    # id helpers
    # ------------------------------------------------------------------
    def unit_label(self, u) -> tuple[str, bool]:
        if u.labels:
            return u.labels[0], True
        return u.owner, False

    def new_id(self, base: str) -> str:
        i = base
        n = 2
        while i in self.ids:
            i = f"{base}~{n}"
            n += 1
        self.ids.add(i)
        return i

    def text_id(self, fs, u, inline_counter) -> str:
        lab, own = self.unit_label(u)
        if own:
            return f"{path_id(fs.path)}:{lab}"
        inline_counter[lab] += 1
        return f"{path_id(fs.path)}:{lab}+{inline_counter[lab]}"

    # ------------------------------------------------------------------
    # entry creation
    # ------------------------------------------------------------------
    def _range(self, fs, u, start=None, end=None):
        if start is None:
            s, e, probs = X.unit_range(fs, u)
        else:
            s, e, probs = start, end, []
        return s, e, probs

    def add(
        self,
        fs,
        entry_id,
        kind,
        start,
        end,
        skeleton,
        limits,
        context,
        category,
        fmt,
        original,
        charmap="default",
        extra=None,
    ):
        lines = self.lines(fs.path)
        claimed = self.claimed[fs.path]
        overlap = [number for number in range(start, end + 1) if number in claimed]
        if overlap:
            self.problems.append(
                f"{entry_id}: lines {overlap[0]}.. already owned by another entry; skipped"
            )
            return None
        for number in range(start, end + 1):
            claimed.add(number)
        if category == "engine":
            # research notes sometimes name the very words of the string: keep them out
            for w in sorted(
                set(re.findall(r"[A-Za-z][A-Za-z'.]{2,}", original)), key=len, reverse=True
            ):
                context = re.sub(r"(?<![\w.])" + re.escape(w) + r"(?![\w])", "…", context)
        e = {
            "id": entry_id,
            "kind": kind,
            "file": fs.path,
            "start": start,
            "end": end,
            "sha256": X.pin(lines, start, end),
            "skeleton": skeleton,
            "limits": limits,
            "context": context,
            "category": category,
            "charmap": charmap,
            "fmt": fmt,
        }
        if extra:
            e.update(extra)
        self.entries.append(e)
        self.originals[entry_id] = original
        self.ids.add(entry_id)
        return e

    def skip(self, fs, start, end, sid, category, reason):
        self.skipped.append(
            {
                "id": sid,
                "file": fs.path,
                "start": start,
                "end": end,
                "category": category,
                "reason": reason,
            }
        )

    def skip_stmts(self, fs, directive, category, reason):
        k = 0
        for st in fs.stmts:
            if st.kind == "stmt" and st.active and st.directive == directive:
                self.skip(fs, st.line, st.line, f"{path_id(fs.path)}#{k}", category, reason)
                k += 1

    def skip_units(self, fs, units, category, reason):
        for u in units:
            if not any(s.has_strings for s in u.active_stmts):
                continue
            lab, own = self.unit_label(u)
            self.skip(fs, u.first_line, u.last_line, f"{path_id(fs.path)}:{lab}", category, reason)

    # ------------------------------------------------------------------
    # placeholder limits
    # ------------------------------------------------------------------
    def ph_limits(self, path, skeleton) -> dict:
        out = {}
        over = {}
        for pre, tab in RAM_OVERRIDES.items():
            if path.startswith(pre):
                over.update(tab)
        for p in skeleton:
            name = ENC.ph_name(p)
            if name == "ram":
                buf = p[5:-1].split("+")[0].strip()
                out[p] = over.get(
                    buf, RAM_WIDTH_EXTRA.get(buf, ENC.RAM_WIDTH.get(buf, ENC.RAM_DEFAULT))
                )
            elif name == "num":
                out[p] = ENC.make_ph_width({"limits": {}})(p)
            elif name == "d":
                out[p] = X.interp_width(p, self.consts)
            elif name in ENC.PH_WIDTH:
                out[p] = ENC.PH_WIDTH[name]
        return out

    # ------------------------------------------------------------------
    # dialog
    # ------------------------------------------------------------------
    def dialog_parse(self, fs, u):
        """Returns (notation, skeleton, fmt, problems, info)."""
        paras = [[[]]]
        skeleton = []
        first = None
        term = ""
        started = False
        probs = []
        keep = []
        plural = False
        last_at = False
        ind = None
        label_prefix = ""
        ops = u.active_stmts
        for st in ops:
            d = st.directive
            if ind is None:
                if st.label_prefix:
                    label_prefix = st.label_prefix
                    ind = "\t"
                else:
                    ind = re.match(r"\s*", st.raw).group(0) or "\t"
            if d in X.TRANSPARENT_IN_TEXT:
                keep.append(st.code.strip())
                continue
            last_at = False
            if d in X.TEXT_MACROS:
                lits = []
                for a, s_ in zip(st.args, st.strings, strict=False):
                    if s_ is not None:
                        lits.append(s_)
                    elif strfmt_literal(a) is not None:
                        lits.append(strfmt_literal(a))
                    else:
                        probs.append(f"non-literal argument at line {st.line}")
                s = "".join(lits)
                if d == "text":
                    if not started:
                        first = "text"
                elif d in ("line", "cont", "next", "next1"):
                    if not started:
                        first = d
                    else:
                        paras[-1].append([])
                elif d == "para":
                    if not started:
                        first = "para"
                    else:
                        paras.append([[]])
                elif d == "page":
                    paras[-1].append([])
                elif d in ("done", "prompt"):
                    term = d
                started = True
                last_at = self._feed(s, paras, skeleton, probs)
                if last_at is None:
                    term = self._last_term
                    last_at = False
            elif d in X.TEXT_CMDS:
                if d == "text_end":
                    term = "text_end"
                elif d == "text_asm":
                    term = "text_asm"
                elif d == "text_plural":
                    plural = True
                elif d == "text_start":
                    pass
                else:
                    ph = self.cmd_placeholder(st)
                    paras[-1][-1].append(ph)
                    skeleton.append(ph)
                    started = True
        if not term and last_at:
            term = "@"
        rows_text = []
        for rows in paras:
            rows_text.append(X.join_rows(["".join(r) for r in rows]))
        notation = "\\p".join(rows_text)
        fmt = {"indent": ind or "\t", "first": first or "text", "term": term}
        if keep:
            fmt["keep"] = keep
        if label_prefix:
            fmt["label_prefix"] = label_prefix
        info = {"plural": plural, "rows": sum(len(r) for r in paras), "paras": len(paras)}
        return notation, skeleton, fmt, probs, info

    _last_term = ""

    def _feed(self, s, paras, skeleton, probs):
        """Append an English literal to the current row; handles inline codes.
        Returns True if it ended with '@', None if it ended with <DONE>/<PROMPT>."""
        toks = X.en_tokens(self.cm, s)
        buf = []
        ended_at = False

        def flush():
            if buf:
                nota, ph, _ = X.en_piece(self.cm, "".join(buf), self.consts)
                paras[-1][-1].append(nota)
                skeleton.extend(ph)
                buf.clear()

        for i, t in enumerate(toks):
            if t in ("<LINE>", "<CONT>", "<NEXT>", "<LNBRK>"):
                flush()
                paras[-1].append([])
            elif t == "<PARA>":
                flush()
                paras.append([[]])
            elif t in ("<DONE>", "<PROMPT>"):
                flush()
                self._last_term = {"<DONE>": "done", "<PROMPT>": "prompt"}[t]
                if i != len(toks) - 1:
                    probs.append("terminator inside a literal")
                return None
            elif t == "@":
                flush()
                ended_at = i == len(toks) - 1
                if not ended_at:
                    probs.append("'@' inside a literal")
            else:
                buf.append(t)
        flush()
        return ended_at

    def cmd_placeholder(self, st) -> str:
        d = st.directive
        a = [x.strip() for x in st.args]
        if d == "text_ram":
            return "{ram:" + a[0] + "}"
        if d == "text_decimal":
            return ENC.normalize_ph("num:" + ",".join(a))
        if d == "text_promptbutton":
            return "{wait}"
        if d == "text_pause":
            return "{pause}"
        if d == "text_sound":
            return "{sound:" + a[0] + "}"
        if d == "text_today":
            return "{day}"
        if d == "text_far":
            return "{far:" + a[0] + "}"
        raise ValueError(d)

    def add_dialog(
        self, fs, u, eid, category, context, width=PH_DEFAULT_DIALOG_WIDTH, extra_limits=None
    ):
        notation, skeleton, fmt, probs, info = self.dialog_parse(fs, u)
        if not X.has_letters(notation.replace("{", " {")) and not any(
            ENC.ph_name(p) in ("PLAYER", "RIVAL", "TRENDY") for p in skeleton
        ):
            if notation.strip():
                self.skip(fs, u.first_line, u.last_line, eid, category, "no translatable letters")
            return None
        s, e, rprobs = X.unit_range(fs, u)
        probs += rprobs
        limits = {"width": width}
        phl = self.ph_limits(fs.path, skeleton)
        if phl:
            limits["ph"] = phl
        if extra_limits:
            limits.update(extra_limits)
        if info["plural"]:
            limits["note"] = "text_plural dropped (English plural); write a number-neutral sentence"
        if probs:
            self.problems += [f"{eid}: {p}" for p in probs]
        return self.add(fs, eid, "dialog", s, e, skeleton, limits, context, category, fmt, notation)

    # ------------------------------------------------------------------
    # box (wrapped text in a custom box)
    # ------------------------------------------------------------------
    def add_box(
        self,
        fs,
        u,
        eid,
        category,
        context,
        width,
        lines,
        pages,
        extra_limits=None,
        min_pages=None,
        raw=False,
    ):
        ops = u.active_stmts
        rows = []
        skeleton = []
        prefixes = {}
        first = None
        term = u.term or ""
        nlines_by_page = [0]
        probs = []
        label_prefix = ""
        ind = None
        for st in ops:
            d = st.directive
            if d in X.TRANSPARENT_IN_TEXT:
                continue
            if d in ("done", "prompt", "text_end") and not st.has_strings:
                term = d
                continue
            if not st.has_strings:
                probs.append(f"unexpected {d} in box at line {st.line}")
                continue
            if ind is None:
                if st.label_prefix:
                    label_prefix = st.label_prefix
                    ind = "\t"
                else:
                    ind = re.match(r"\s*", st.raw).group(0) or "\t"
            # the exact "macro + spacing" as written, e.g. 'db   ' / 'next ' / 'page '
            code = st.code[len(st.label_prefix) :] if st.label_prefix else st.code
            m = re.match(r'\s*(\w+\s*)"', code)
            macro_sp = m.group(1) if m else d + " "
            if first is None:
                first = macro_sp
            elif d == "page":
                prefixes["page"] = macro_sp
                nlines_by_page.append(0)
            else:
                prefixes["line"] = macro_sp
            nlines_by_page[-1] += 1
            lit = "".join(x for x in st.strings if x is not None)
            if lit.endswith("@"):
                lit = lit[:-1]
                term = "@"
            nota, ph, _ = X.en_piece(self.cm, lit, self.consts)
            rows.append(nota)
            skeleton += ph
        notation = X.join_rows(rows)
        if not X.has_letters(notation):
            return None
        s, e, rprobs = X.unit_range(fs, u)
        probs += rprobs
        fmt = {
            "indent": ind or "\t",
            "first": (first or "text ").rstrip(" "),
            "line": prefixes.get("line", "next ").rstrip(" "),
            "page": prefixes.get("page", "page ").rstrip(" "),
            "term": term,
            "min_pages": min_pages or 1,
        }
        # exact spacing after the macro names (dex: "db   ", "next ")
        fmt["first_sp"] = first or "text "
        fmt["line_sp"] = prefixes.get("line", fmt["line"] + " ")
        fmt["page_sp"] = prefixes.get("page", fmt["page"] + " ")
        if label_prefix:
            fmt["label_prefix"] = label_prefix
        fmt["seen"] = sorted(k for k in ("line", "page") if k in prefixes)
        limits = {"width": width, "lines": lines, "pages": pages}
        if raw:
            limits["raw"] = True
        phl = self.ph_limits(fs.path, skeleton)
        if phl:
            limits["ph"] = phl
        if extra_limits:
            limits.update(extra_limits)
        if probs:
            self.problems += [f"{eid}: {p}" for p in probs]
        return self.add(fs, eid, "box", s, e, skeleton, limits, context, category, fmt, notation)

    # ------------------------------------------------------------------
    # strings / fields
    # ------------------------------------------------------------------
    def string_from_stmts(
        self,
        fs,
        stmts,
        *,
        width=None,
        lines_max=None,
        exact=False,
        centre=None,
        size=None,
        raw=None,
        bytes_=None,
        nbytes_line=None,
        split_macro_lines=True,
        sep_tokens=("<NEXT>", "<LNBRK>"),
        extra_sep=None,
        start=None,
        end=None,
    ):
        """Build (slots, fmt_lines, notation_lines, skeleton, probs, charmap) for string statements.
        Every source line becomes {'pre': text, 'parts': [{'slot': k} | {'text': verbatim}]};
        pieces without letters (layout, tile codes, terminators) stay verbatim."""
        slots = []
        flines = []
        nlines = []
        skeleton = []
        probs = []
        cm_name = None
        seps = tuple(sep_tokens) + ((extra_sep,) if extra_sep else ())
        wanted = {id(s) for s in stmts}
        if start is not None:
            in_range = fs.stmts[start - 1 : end]
        else:
            in_range = [s for s in stmts]
        for st in in_range:
            if id(st) not in wanted or st.kind != "stmt" or not st.active or not st.has_strings:
                # other lines owned by the entry: active code is kept verbatim (no comments),
                # conditionals / inactive branches / blank lines are dropped
                if st.active and st.kind in ("stmt", "label") and st.code.strip():
                    flines.append({"pre": st.code, "parts": []})
                continue
            cm_name = cm_name or st.charmap
            code = st.code
            spans = literal_spans(code)
            if not spans:
                continue
            line = {"pre": code[: spans[0][0] + 1], "parts": []}
            for k, (a, b) in enumerate(spans):
                body = code[a + 1 : b]
                post = code[b : spans[k + 1][0] + 1] if k + 1 < len(spans) else code[b:]
                for piece, sep_after in split_seps(self.cm, body, seps):
                    d = X.decompose(self.cm, piece, self.consts)
                    if not (
                        X.has_letters(d["core"])
                        or (
                            d["core"]
                            and any(
                                t in d["core"] for t in ("<PLAYER>", "<RIVAL>", "<TRENDY>", _PKMN)
                            )
                        )
                    ):
                        line["parts"].append({"text": piece + sep_after})
                        continue
                    if sep_after:
                        d["ctl_after"] = d["ctl_after"] + sep_after
                    if d["core"].startswith(":") and d["lead"]:
                        # "        :Type" -- the colon belongs to the layout column
                        d["ctl_before"] += " " * d["lead"] + ":"
                        d["lead"] = 0
                        d["core"] = d["core"][1:]
                        d["core_w"] -= 1
                    slot = X.make_slot(
                        self.cm,
                        self.consts,
                        d,
                        "",
                        "",
                        width=width,
                        centre=centre,
                        size=size,
                        nbytes=nbytes_line,
                    )
                    if d["tail_text"]:
                        slot["tail_w"] = X.en_piece(self.cm, d["tail_text"], self.consts)[2]
                        slot["tail_bytes"] = self.cm.nbytes(d["tail_text"], st.charmap, self.consts)
                    nota, ph, w = X.en_piece(self.cm, d["core"], self.consts)
                    cols = core_columns(self.cm, d["core"], self.consts)
                    if cols and len(cols) > 1:
                        slot["cols"] = cols
                    slots.append(slot)
                    nlines.append(nota)
                    skeleton += ph
                    line["parts"].append({"slot": len(slots) - 1})
                line["parts"].append({"text": post})
            flines.append(line)
        return slots, flines, nlines, skeleton, probs, cm_name or "default"

    def add_string(
        self,
        fs,
        stmts,
        eid,
        category,
        context,
        start=None,
        end=None,
        kind="string",
        *,
        width=None,
        lines=None,
        exact=False,
        centre=None,
        size=None,
        raw=None,
        bytes_=None,
        nbytes_line=None,
        extra_sep=None,
        extra_limits=None,
        allow_no_letters=False,
        total_size=None,
        size_extra=0,
    ):
        if start is None:
            start = min(s.line for s in stmts if s.kind == "stmt")
            end = max(s.line for s in stmts if s.kind == "stmt")
        slots, flines, nlines, skeleton, probs, cmn = self.string_from_stmts(
            fs,
            stmts,
            width=width,
            centre=centre,
            size=size,
            bytes_=bytes_,
            nbytes_line=nbytes_line,
            extra_sep=extra_sep,
            start=start,
            end=end,
        )
        if not slots or (not allow_no_letters and not any(X.has_letters(n) for n in nlines)):
            self.skip(
                fs, start, end, eid, category, "no letters (placeholder, digits or layout only)"
            )
            return None
        if start is None:
            start = min(s.line for s in stmts if s.kind == "stmt")
            end = max(s.line for s in stmts if s.kind == "stmt")
        is_raw = raw if raw is not None else (cmn == "no_ngrams")
        limits = {"width": max(s["width"] for s in slots), "lines": len(slots)}
        if len(slots) > 1:
            limits["exact_lines"] = exact
        if is_raw:
            limits["raw"] = True
        if bytes_ is not None:
            limits["bytes"] = bytes_
        if total_size is not None:
            limits["size"] = total_size
            limits["size_extra"] = size_extra
            slots[-1]["ctl_after"] = "@"
        for _k, s in enumerate(slots):
            if s.get("pad") is not None:
                limits.setdefault("pad", True)
            if s.get("centre"):
                limits["centre"] = s["centre"]
            if s.get("size") is not None:
                limits["size"] = s["size"]
            if s.get("cols"):
                limits["cols"] = s["cols"]
        if len(slots) > 1 and len(set(s["width"] for s in slots)) > 1:
            limits["line_widths"] = [s["width"] for s in slots]
        phl = self.ph_limits(fs.path, skeleton)
        if phl:
            limits["ph"] = phl
        if extra_limits:
            limits.update(extra_limits)
        fmt = {"slots": slots, "lines": flines}
        notation = "\\n".join(nlines)
        if probs:
            self.problems += [f"{eid}: {p}" for p in probs]
        return self.add(
            fs,
            eid,
            kind,
            start,
            end,
            skeleton,
            limits,
            context,
            category,
            fmt,
            notation,
            charmap=cmn,
        )

    # ------------------------------------------------------------------
    # handlers: maps
    # ------------------------------------------------------------------
    def maps_info(self):
        if self._maps is not None:
            return self._maps
        from classic_retro.source.polished_crystal import maps_scan as M

        cm, scans = M.scan_tree(self.tree)
        roles = {}
        for fsx in scans:
            for b in fsx.blocks:
                roles[f"maps/{fsx.stem}:{b.id.split(':', 1)[1]}"] = b
        menus = {}
        buf = io.StringIO()
        for r in M.menu_report(cm, scans, out=buf):
            for i in r["ids"]:
                menus["maps/" + i] = r
        dbs = {}
        for fsx in scans:
            for d in fsx.dbstrings:
                dbs[(fsx.stem, d.line)] = d
        # refs: label -> list of (cmd, file, line)
        refs = collections.defaultdict(list)
        for fsx in scans:
            for r in fsx.refs:
                refs[r.resolved].append((r.cmd, fsx.stem, r.line, r.argi))
        self._maps = {"roles": roles, "menus": menus, "dbs": dbs, "refs": refs, "scans": scans}
        self._speakers = self._map_speakers()
        return self._maps

    def _map_speakers(self):
        """label -> speaker description (object sprite / trainer)."""
        sp = {}
        for path in self.scan.order:
            if not path.startswith("maps/"):
                continue
            fs = self.scan.files[path]
            script_owner = {}
            texts_in_script = collections.defaultdict(list)
            for st in fs.stmts:
                if st.kind != "stmt" or not st.active:
                    continue
                d = st.directive
                a = st.args
                if d == "object_event" and len(a) >= 11:
                    sprite = a[2].strip().replace("SPRITE_", "").replace("_", " ").title()
                    tgt = a[10].strip()
                    if a[8].strip() == "OBJECTTYPE_COMMAND":
                        sp.setdefault(tgt, sprite)
                    elif a[8].strip() in ("OBJECTTYPE_SCRIPT",):
                        script_owner.setdefault(tgt, sprite)
                    elif a[8].strip() in ("OBJECTTYPE_TRAINER", "OBJECTTYPE_GENERICTRAINER"):
                        script_owner.setdefault(tgt, sprite)
                if d in ("generictrainer", "trainer") and len(a) >= 2:
                    who = f"{a[0].strip().replace('_', ' ').title()} {a[1].strip().title()}"
                    for k in range(3, min(len(a), 6)):
                        lab = a[k].strip()
                        full = (st.glabel + lab) if lab.startswith(".") else lab
                        sp.setdefault(full, "trainer " + who)
                    sp.setdefault(st.glabel, "trainer " + who)
                if (
                    d
                    in (
                        "writetext",
                        "jumptext",
                        "jumptextfaceplayer",
                        "jumpopenedtext",
                        "showtext",
                        "showtextfaceplayer",
                        "iftrue_jumptext",
                        "iffalse_jumptext",
                        "iftrue_jumpopenedtext",
                        "iffalse_jumpopenedtext",
                        "iftrue_jumptextfaceplayer",
                        "iffalse_jumptextfaceplayer",
                    )
                    and a
                ):
                    lab = a[0].strip()
                    full = (st.glabel + lab) if lab.startswith(".") else lab
                    texts_in_script[st.glabel].append(full)
            for script, sprite in script_owner.items():
                for t in texts_in_script.get(script, []):
                    sp.setdefault(t, sprite)
                sp.setdefault(script, sprite)
        return sp

    def h_maps(self, fs, units):
        info = self.maps_info()
        stem = os.path.basename(fs.path)[:-4]
        mapname = X.nice_name(stem)
        inline = collections.Counter()
        collections.Counter()
        unown = self._unown_texts(fs)
        str_units_by_owner = collections.defaultdict(list)
        for u in units:
            if u.kind == "chain":
                lab, own = self.unit_label(u)
                str_units_by_owner[lab].append(u)
        for u in units:
            if u.kind == "text":
                eid = self.text_id(fs, u, inline)
                lab, own = self.unit_label(u)
                if not any(s.directive in X.TEXT_MACROS and s.has_strings for s in u.active_stmts):
                    continue
                b = info["roles"].get(eid)
                roles = list(b.roles) if b else []
                if lab in unown or (u.owner in unown):
                    self.skip(
                        fs,
                        u.first_line,
                        u.last_line,
                        eid,
                        "unown_font",
                        "Unown-font puzzle text (printed with unowntypeface; Latin letters shown as Unown glyphs)",
                    )
                    continue
                speaker = self._speakers.get(lab) or self._speakers.get(u.owner) or ""
                rdesc = ", ".join(dict.fromkeys(ROLE.get(r, r) for r in roles)) or "dialogue"
                if "sign" in roles and not speaker:
                    speaker = "sign"
                ctx = f"{mapname}: {rdesc}" + (f" ({speaker})" if speaker else "")
                aliases = u.labels[1:]
                e = self.add_dialog(fs, u, eid, "maps", ctx)
                if e is not None and aliases:
                    e["aliases"] = aliases
                if e is not None and b is not None and b.inline_cmd:
                    e["context"] += f" [inline after {b.inline_cmd}]"
            else:
                lab, own = self.unit_label(u)
                group = str_units_by_owner[lab]
                k = group.index(u)
                eid = f"{path_id(fs.path)}:{lab}" + (f"[{k}]" if len(group) > 1 else "")
                self.map_string(fs, u, eid, mapname, info, lab)

    def map_string(self, fs, u, eid, mapname, info, lab):
        st0 = u.active_stmts[0]
        stem = os.path.basename(fs.path)[:-4]
        mid = f"maps/{stem}:{lab}"
        # menu items
        menu = None
        for key, r in info["menus"].items():
            if key.startswith(mid + "[") or key == mid:
                menu = r
                break
        refs = info["refs"].get(lab, [])
        refcmds = {r[0] for r in refs}
        if st0.charmap == "no_ngrams" and any(s.directive == "next" for s in u.active_stmts):
            # mail message (32 bytes, 2 lines of 16, raw)
            same = None
            if lab.startswith("ReceivedSpearowMail"):
                same = "maps/Route35GoldenrodGate:GiftSpearowMail"
            elif "GiftSpearowMail" in lab:
                same = "maps/Route31:ReceivedSpearowMailText"
            lim = {"note": "Mail message: line 1 + line 2 ≤ 16 cells each, raw bytes"}
            if same:
                lim["must_equal"] = same
            total = 32 if "Received" not in lab else None
            return self.add_string(
                fs,
                u.active_stmts,
                eid,
                "mail",
                f"{mapname}: mail message (mail viewer)",
                start=u.first_line,
                end=u.last_line,
                width=16,
                raw=True,
                extra_limits=lim,
                total_size=total,
                size_extra=1 if total else 0,
            )
        if st0.directive == "rawchar":
            lit = "".join(x for x in st0.strings if x)
            if "MailOTID" in lab:
                return self.add_string(
                    fs,
                    [st0],
                    eid,
                    "gift_names",
                    f"{mapname}: mail author name (stored in the mail)",
                    kind="field",
                    width=8,
                    size=self.cm.nbytes(lit, "no_ngrams", self.consts),
                    raw=True,
                )
            is_ot = "OT" in lab
            return self.add_string(
                fs,
                [st0],
                eid,
                "gift_names",
                f"{mapname}: gift Pokémon {'OT name' if is_ot else 'nickname'} (stored in the save; ≤{7 if is_ot else 10})",
                width=7 if is_ot else 10,
                raw=True,
                extra_limits={
                    "must_equal": "engine/events/shuckle:SpecialShuckleOTAndExtra.OTAndExtra"
                }
                if lab == "ShuckieOTName"
                else None,
            )
        if menu is not None:
            w = menu["avail"]
            ctx = f"{mapname}: menu item (box {tuple(menu['coords'])}, {w} cells)"
            if "AcademyBlackboard" in lab:
                w = 4
                ctx = f"{mapname}: blackboard 2-D menu cell (≤4 cells)"
            return self.add_string(
                fs,
                u.active_stmts,
                eid,
                "map_menus",
                ctx,
                start=u.first_line,
                end=u.last_line,
                width=w,
            )
        if "getstring" in refcmds or "BadgeText" in lab:
            return self.add_string(
                fs,
                u.active_stmts,
                eid,
                "map_strings",
                f"{mapname}: name copied with getstring into wStringBuffer3, printed inside a sentence",
                start=u.first_line,
                end=u.last_line,
                width=12,
                bytes_=18,
            )
        return self.add_string(
            fs,
            u.active_stmts,
            eid,
            "map_strings",
            f"{mapname}: string",
            start=u.first_line,
            end=u.last_line,
        )

    def _unown_texts(self, fs):
        out = set()
        on = False
        for st in fs.stmts:
            if st.kind != "stmt":
                continue
            if st.directive == "unowntypeface":
                on = True
            elif st.directive == "restoretypeface":
                on = False
            elif on and st.directive in ("writetext", "showtext", "jumptext") and st.args:
                lab = st.args[0].strip()
                out.add((st.glabel + lab) if lab.startswith(".") else lab)
        return out

    # ------------------------------------------------------------------
    # handlers: dialog files
    # ------------------------------------------------------------------
    def h_dialog_file(self, fs, units, category, ctx):
        inline = collections.Counter()
        for u in units:
            if u.kind == "text":
                eid = self.text_id(fs, u, inline)
                if not any(s.directive in X.TEXT_MACROS and s.has_strings for s in u.active_stmts):
                    continue
                lab, own = self.unit_label(u)
                e = self.add_dialog(fs, u, eid, category, f"{ctx} ({lab})")
                if e is not None and u.labels[1:]:
                    e["aliases"] = u.labels[1:]
            else:
                self.generic_chain(fs, u, category, ctx)

    def h_phone(self, fs, units):
        stem = os.path.basename(fs.path)[:-4]
        who, _, kind = stem.partition("_")
        kind_desc = {
            "caller": "calls you",
            "callee": "you call",
            "overworld": "rematch / gift reminder",
        }.get(kind, kind)
        self.h_dialog_file(fs, units, "phone", f"Phone call: {who.title()} ({kind_desc})")

    # ------------------------------------------------------------------
    # data: lists, tables
    # ------------------------------------------------------------------
    def h_li(self, fs, units, category, context, width=None, bytes_=None, raw=None, multi20=False):
        collections.Counter()
        tables = []
        for u in units:
            st = u.active_stmts[0]
            if st.directive != "li":
                self.generic_chain(fs, u, category, context) if u.kind == "chain" else None
                continue
            tab = self._table_label(fs, st)
            if tab not in tables:
                tables.append(tab)
        for u in units:
            st = u.active_stmts[0]
            if st.directive != "li":
                continue
            tab = self._table_label(fs, st)
            k = self._list_index(fs, st)
            eid = f"{path_id(fs.path)}#{k}" if len(tables) == 1 else f"{path_id(fs.path)}:{tab}#{k}"
            w = width
            lit = "".join(x for x in st.strings if x is not None)
            d = X.decompose(self.cm, lit, self.consts)
            if w is None:
                w = d["core_w"]
            if multi20:
                # artists: "A,      B" padded so that B wraps to the next 20-cell row
                if X.has_letters(lit):
                    self.two_row_string(fs, st, eid, category, context)
                continue
            if bytes_ is not None:
                self.add_string(fs, [st], eid, category, context, width=w, raw=raw, bytes_=bytes_)
            else:
                self.add_string(fs, [st], eid, category, context, width=w, raw=raw)

    def _table_label(self, fs, st):
        """The global label of the list containing st."""
        for s in reversed(fs.stmts[: st.index + 1]):
            if s.directive in ("list_start", "table_width"):
                # label is the nearest global label above
                for s2 in reversed(fs.stmts[: s.index + 1]):
                    if s2.labels:
                        return s2.labels[0]
                return "<top>"
        return st.glabel or "<top>"

    def _list_index(self, fs, st):
        k = 0
        for s in reversed(fs.stmts[: st.index]):
            if s.directive in ("list_start", "table_width"):
                break
            if (
                s.kind == "stmt"
                and s.active
                and s.directive in ("li", "rawchar", "db", "song_info")
                and s.has_strings
            ):
                k += 1
        return k

    def h_species(self, fs, units):
        for u in units:
            for st in u.active_stmts:
                if not st.has_strings:
                    continue
                k = self._list_index(fs, st)
                eid = f"{path_id(fs.path)}#{k}"
                lit = "".join(x for x in st.strings if x is not None)
                if not X.has_letters(lit):
                    self.skip(
                        fs,
                        st.line,
                        st.line,
                        eid,
                        "species_names",
                        'no letters ("?000?" placeholder name)',
                    )
                    continue
                self.add_string(
                    fs,
                    [st],
                    eid,
                    "species_names",
                    "Species name (fixed 10-byte field; battle HUD, party, Pokédex, default nickname)",
                    start=st.line,
                    end=st.line,
                    kind="field",
                    width=10,
                    size=10,
                    raw=True,
                )

    def h_table_fields(self, fs, units, category, context, size, width):
        for u in units:
            for st in u.active_stmts:
                if not st.has_strings or st.directive != "rawchar":
                    continue
                lab, own = self.unit_label(u)
                if st.glabel and fs.path.endswith("default_player_names.asm"):
                    eid = f"{path_id(fs.path)}:{st.glabel}"
                else:
                    tab = self._table_label(fs, st)
                    k = self._list_index(fs, st)
                    eid = f"{path_id(fs.path)}:{tab}#{k}"
                    if fs.path.endswith("classes.asm"):
                        eid = f"{path_id(fs.path)}#{k}"
                self.add_string(
                    fs,
                    [st],
                    eid,
                    category,
                    context,
                    start=st.line,
                    end=st.line,
                    kind="field",
                    width=width,
                    size=size,
                    raw=True,
                )

    def h_ability_names(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            u.active_stmts[0]
            eid = f"{path_id(fs.path)}:{lab}"
            self.add_string(
                fs,
                u.active_stmts,
                eid,
                "ability_names",
                "Ability name (summary, Pokédex, battle pop-up VWF ≤80 px, battle text; buffer 19 bytes)",
                width=16,
                bytes_=18,
                raw=True,
            )

    def h_box_file(self, fs, units, category, context, width, lines, pages):
        inline = collections.Counter()
        for u in units:
            eid = self.text_id(fs, u, inline)
            if u.kind == "text" or any(s.directive in ("next", "next1") for s in u.active_stmts):
                e = self.add_box(fs, u, eid, category, context, width, lines, pages)
                if e is not None and u.labels[1:]:
                    e["aliases"] = u.labels[1:]
            else:
                self.generic_chain(fs, u, category, context)

    def h_dex(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            sts = u.active_stmts
            if not sts:
                continue
            species = re.sub(r"PokedexEntry$", "", u.owner.split(".")[0])
            if (
                len(sts) == 1
                and sts[0].directive == "db"
                and "".join(x for x in sts[0].strings if x).endswith("@")
                and lab.endswith("PokedexEntry")
            ):
                eid = f"{path_id(fs.path)}:{lab}.category"
                self.add_string(
                    fs,
                    sts,
                    eid,
                    "dex_category",
                    f"Pokédex: {species} category (what kind of Pokémon it is), at (9,5)",
                    width=11,
                )
                continue
            eid = f"{path_id(fs.path)}:{u.owner}.body"
            if eid in self.ids:
                eid = self.new_id(eid)
            self.add_box(
                fs,
                u,
                eid,
                "dex_body",
                f"Pokédex: {species} description (2 pages × 3 lines; also read on the radio Pokédex Show)",
                18,
                3,
                2,
                extra_limits={"bytes_per_line": 18},
                min_pages=2,
            )

    def h_types(self, fs, units):
        names = set()
        egg_only = set()
        for st in fs.stmts:
            if st.directive == "dr" and st.args:
                tab = self._table_label(fs, st)
                if tab == "TypeNames":
                    names.add(st.args[0].strip())
                else:
                    egg_only.add(st.args[0].strip())
        budgets = self.dr_budgets(fs)
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            if lab in names and lab in egg_only:
                ctx, w = "Type name, also used as an egg group name", 8
            elif lab in names:
                ctx, w = "Type name (move info, Pokédex, summary; ≤12 bytes)", 8
            else:
                ctx, w = "Egg group name (Pokédex bio page)", 12
            self.add_string(
                fs,
                u.active_stmts,
                eid,
                "type_names",
                ctx,
                width=w,
                bytes_=budgets.get(lab),
                start=u.first_line,
                end=u.last_line,
            )

    def h_natures(self, fs, units):
        budgets = self.dr_budgets(fs)
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            lit = "".join(x for s in u.active_stmts for x in s.strings if x)
            if not X.has_letters(lit):
                continue
            self.add_string(
                fs,
                u.active_stmts,
                eid,
                "natures",
                "Nature name (summary memo page)",
                width=8,
                bytes_=budgets.get(lab),
                start=u.first_line,
                end=u.last_line,
            )

    def h_dr_strings(self, fs, units, category, context, width=None):
        budgets = self.dr_budgets(fs)
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            sts = u.active_stmts
            lit = "".join(x for s in sts for x in s.strings if x)
            if not X.has_letters(lit):
                continue
            self.add_string(
                fs,
                sts,
                eid,
                category,
                context,
                width=width,
                bytes_=budgets.get(lab),
                start=u.first_line,
                end=u.last_line,
            )

    def dr_budgets(self, fs) -> dict[str, int]:
        """Byte budget per string reached through 1-byte `dr` offsets: English
        bytes + an even share of the table's remaining slack (offset ≤ 255)."""
        # layout: sizes of statements in order
        addr = 0
        pos = {}
        size = {}
        drs = []
        for st in fs.stmts:
            if st.kind != "stmt" or not st.active:
                if st.labels and st.active:
                    for label in st.labels:
                        pos[label] = addr
                continue
            for label in st.labels:
                pos[label] = addr
            d = st.directive
            if d == "dr":
                drs.append((addr, st.args[0].strip(), st))
                addr += 1
            elif d in ("db", "rawchar", "li") and st.has_strings:
                n = 0
                for _arg, s in zip(st.args, st.strings, strict=False):
                    if s is not None:
                        n += self.cm.nbytes(
                            s, "no_ngrams" if d == "rawchar" else st.charmap, self.consts
                        )
                    else:
                        n += 1
                if d == "li":
                    n += 1
                if st.labels:
                    size[st.labels[0]] = n
                addr += n
            elif d == "password_group":
                n = 2 + sum(
                    self.cm.nbytes(s, st.charmap, self.consts)
                    if s is not None
                    else (2 if st.args[0].strip() == "BUENA_MON" else 1)
                    for s in st.strings[2:]
                )
                if st.labels:
                    size[st.labels[0]] = n
                addr += n
            elif d in X.NON_EMITTING:
                continue
            else:
                return {}
        out = {}
        if not drs:
            return out

        def full(lab, st):
            return (st.glabel + lab) if lab.startswith(".") else lab

        tables = collections.defaultdict(list)
        for a, lab, st in drs:
            fl = full(lab, st)
            if fl in pos:
                tables[self._table_label(fs, st)].append((pos[fl] - a, fl))
        for tab, items in tables.items():
            worst = max(off for off, _ in items)
            slack = max(0, 255 - worst)
            gid = f"{path_id(fs.path)}:{tab}"
            members = [t for t in dict.fromkeys(fl for _, fl in items) if t in size]
            self.dr_groups[gid] = {
                "slack": slack,
                "members": [f"{path_id(fs.path)}:{m}" for m in members],
            }
            for t in members:
                # a single string may use the whole slack if the others do not grow
                out[t] = min(out.get(t, 10**6), size[t] + slack)
                self.dr_member_of[f"{path_id(fs.path)}:{t}"].append(gid)
        return out

    def h_parties(self, fs, units):
        k = collections.Counter()
        for st in fs.stmts:
            if st.kind != "stmt" or not st.active:
                continue
            if st.directive == "def_trainer" and len(st.args) >= 2 and st.strings[1] is not None:
                cls = self._current_class(fs, st)
                eid = f"{path_id(fs.path)}:{cls}#{st.args[0].strip()}"
                eid = self.new_id(eid) if eid in self.ids else eid
                if not X.has_letters(st.strings[1].replace("<RIVAL>", "").replace("<PLAYER>", "")):
                    self.skip(
                        fs,
                        st.line,
                        st.line,
                        eid,
                        "trainer_names",
                        "name is a placeholder (<RIVAL>/<PLAYER>)",
                    )
                    continue
                self.add_string(
                    fs,
                    [st],
                    eid,
                    "trainer_names",
                    f"Trainer name ({cls}); ≤10 (11-byte copy)",
                    start=st.line,
                    end=st.line,
                    width=10,
                    bytes_=10,
                )
            elif st.directive == "tr_mon" and len(st.args) >= 2 and st.strings[1] is not None:
                cls = self._current_class(fs, st)
                k[cls] += 1
                eid = f"{path_id(fs.path)}:{cls}.nick{k[cls]}"
                self.add_string(
                    fs,
                    [st],
                    eid,
                    "trainer_mon_nicknames",
                    f"Nickname of a {cls} trainer Pokémon; ≤10",
                    start=st.line,
                    end=st.line,
                    width=10,
                    bytes_=10,
                )

    def _current_class(self, fs, st):
        for s in reversed(fs.stmts[: st.index]):
            if s.directive == "def_trainer_class" and s.args:
                return s.args[0].strip()
        return "TRAINER"

    def h_npc_trades(self, fs, units):
        n = 0
        for st in fs.stmts:
            if (
                st.kind != "stmt"
                or not st.active
                or st.directive != "rawchar"
                or not st.has_strings
            ):
                continue
            lit = "".join(x for x in st.strings if x)
            size = self.cm.nbytes(lit, "no_ngrams", self.consts)
            is_ot = size == 8
            n += 1
            eid = f"{path_id(fs.path)}#{(n - 1) // 2}.{'ot' if is_ot else 'nickname'}"
            self.add_string(
                fs,
                [st],
                eid,
                "npc_trades",
                f"NPC trade {'OT name (8 bytes: ≤7 + @)' if is_ot else 'nickname (11 bytes: ≤10 + @)'}",
                start=st.line,
                end=st.line,
                kind="field",
                width=7 if is_ot else 10,
                size=size,
                raw=True,
            )

    def h_landmarks(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            st = u.active_stmts[0]
            eid = f"{path_id(fs.path)}:{lab}"
            e = self.add_string(
                fs,
                [st],
                eid,
                "landmarks",
                "Landmark (map) name: sign pop-up (one row, ≤18, centred); Pokégear/Town Map and Fly "
                "(two rows of ≤11; \\n marks the split, written as ¯); summary met location; phone text",
                start=st.line,
                end=st.line,
                width=11,
                raw=True,
                bytes_=22,
                extra_sep="¯",
                extra_limits={"total_width": 18},
            )
            if e is None:
                continue
            lit = "".join(x for x in st.strings if x).rstrip("@")
            e["limits"]["total_width"] = max(18, X.en_piece(self.cm, lit, self.consts)[2])
            slots = e["fmt"]["slots"]
            if len(slots) == 1:
                # allow a split even where the English has none
                only = slots[0]
                second = {
                    "pre": "",
                    "post": "",
                    "ctl_before": "",
                    "ctl_after": only["ctl_after"],
                    "width": 11,
                }
                only["ctl_after"] = "¯"
                slots.append(second)
                for ln in e["fmt"]["lines"]:
                    for i, part in enumerate(ln["parts"]):
                        if part.get("slot") == 0:
                            ln["parts"].insert(i + 1, {"slot": 1})
                            break
            slots[0]["sep_optional"] = True
            e["limits"]["lines"] = 2
            e["limits"]["exact_lines"] = False

    def h_credits(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            lit = "".join(x for s in u.active_stmts for x in s.strings if x)
            if not X.has_letters(lit):
                self.skip(
                    fs,
                    u.first_line,
                    u.last_line,
                    eid,
                    "credits",
                    "copyright tile codes / no letters",
                )
                continue
            self.add_string(
                fs,
                u.active_stmts,
                eid,
                "credits",
                "Credits roll line(s), centred in 20 cells",
                start=u.first_line,
                end=u.last_line,
                width=20,
                centre=20,
            )

    def h_song_info(self, fs, units):
        for st in fs.stmts:
            if (
                st.kind != "stmt"
                or not st.active
                or st.directive != "song_info"
                or st.strings[0] is None
            ):
                continue
            k = self._list_index(fs, st)
            eid = f"{path_id(fs.path)}#{k}"
            self.two_row_string(
                fs,
                st,
                eid,
                "music_titles",
                "Music player: song title at (0,3); two rows of 20 (\\n = second row)",
            )

    def two_row_string(self, fs, st, eid, category, context):
        """A literal shown over two 20-cell screen rows; the English forces the
        wrap with spaces.  Two slots: row 1 (padded to 20 when row 2 is used), row 2."""
        code = st.code
        spans = literal_spans(code)
        a, b = spans[0]
        body = code[a + 1 : b]
        toks = X.en_tokens(self.cm, body)
        ctl_after = ""
        while toks and toks[-1] == "@":
            ctl_after = "@" + ctl_after
            toks.pop()
        # find a run of >=2 spaces after which the text starts at cell 20
        pos = 0
        split = None
        i = 0
        cells = []
        for t in toks:
            cells.append(pos)
            pos += X.en_piece(self.cm, t, self.consts)[2]
        for i in range(1, len(toks)):
            if (
                toks[i - 1] == " "
                and toks[i] != " "
                and cells[i] == 20
                and i >= 2
                and toks[i - 2] == " "
            ):
                split = i
                break
        if split is not None:
            j = split
            while j > 0 and toks[j - 1] == " ":
                j -= 1
            row1, row2 = "".join(toks[:j]), "".join(toks[split:])
        else:
            text = "".join(toks)
            row1, row2 = text, ""
            if pos > 20:
                cut = text.rfind(" ", 0, 21)
                if cut > 0:
                    row1, row2 = text[:cut], text[cut + 1 :]
        n1, ph1, w1 = X.en_piece(self.cm, row1, self.consts)
        n2, ph2, w2 = X.en_piece(self.cm, row2, self.consts) if row2 else ("", [], 0)
        slots = [
            {"ctl_before": "", "ctl_after": "", "width": 20, "pad_next": 20},
            {"ctl_before": "", "ctl_after": ctl_after, "width": 20},
        ]
        fmt = {
            "slots": slots,
            "lines": [
                {"pre": code[: a + 1], "parts": [{"slot": 0}, {"slot": 1}, {"text": code[b:]}]}
            ],
        }
        limits = {"width": 20, "lines": 2, "exact_lines": False}
        if st.charmap == "no_ngrams":
            limits["raw"] = True
        nota = n1 + ("\\n" + n2 if n2 else "")
        return self.add(
            fs,
            eid,
            "string",
            st.line,
            st.line,
            ph1 + ph2,
            limits,
            context,
            category,
            fmt,
            nota,
            charmap=st.charmap,
        )

    def h_phone_names(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            lines = [s for s in u.active_stmts if s.has_strings]
            if not lines:
                continue
            e = self.add_string(
                fs,
                lines,
                eid,
                "phone_names",
                'Phone list caller label: name + ":" on row 1, title indented on row 2 (mimics trainer entries)',
                start=u.first_line,
                end=u.last_line,
                exact=True,
                width=17,
            )
            if e is not None and len(e["fmt"]["slots"]) > 1:
                e["fmt"]["slots"][1]["width"] = 14
                e["limits"]["line_widths"] = [17, 14]

    def h_buena(self, fs, units):
        for st in fs.stmts:
            if (
                st.kind != "stmt"
                or not st.active
                or st.directive != "password_group"
                or not st.has_strings
            ):
                continue
            eid = f"{path_id(fs.path)}:{st.labels[0] if st.labels else st.owner}"
            self.add_string(
                fs,
                [st],
                eid,
                "buena_passwords",
                "Buena's password options (three choices; must match the names shown elsewhere: "
                "towns = landmarks, types = type names, stations = radio station names)",
                start=st.line,
                end=st.line,
                exact=True,
                width=12,
            )

    def h_ngrams(self, fs, units):
        for u in units:
            lab, own = self.unit_label(u)
            eid = f"{path_id(fs.path)}:{lab}"
            if lab.endswith((".Poke", ".Pokemon")):
                self.add_string(
                    fs,
                    u.active_stmts,
                    eid,
                    "ngrams",
                    "The word the n-gram # (or #mon) stands for all over the text. "
                    "Translations that contain this word exactly can be stored as the n-gram.",
                    start=u.first_line,
                    end=u.last_line,
                    width=7,
                    raw=True,
                )
            else:
                self.skip(
                    fs,
                    u.first_line,
                    u.last_line,
                    eid,
                    "ngrams",
                    "English n-gram expansion (compression table)",
                )

    def h_generic_data(self, fs, units):
        self.counters["generic_data_files"] += 1
        cat = "data_misc"
        self.h_dialog_file(fs, units, cat, f"{fs.path}")

    def generic_chain(self, fs, u, category, context):
        lab, own = self.unit_label(u)
        st0 = u.active_stmts[0]
        if st0.directive == "li":
            eid = f"{path_id(fs.path)}:{self._table_label(fs, st0)}#{self._list_index(fs, st0)}"
            if (
                eid.split(":", 1)[1].startswith(lab.split(".")[0])
                and sum(1 for s in fs.stmts if s.directive == "list_start") == 1
            ):
                eid = f"{path_id(fs.path)}#{self._list_index(fs, st0)}"
            return self.add_string(
                fs, u.active_stmts, eid, category, context, start=u.first_line, end=u.last_line
            )
        eid = f"{path_id(fs.path)}:{lab}"
        if eid in self.ids:
            eid = self.new_id(eid)
        return self.add_string(
            fs, u.active_stmts, eid, category, context, start=u.first_line, end=u.last_line
        )

    # ------------------------------------------------------------------
    # engine / home / audio
    # ------------------------------------------------------------------
    def h_engine(self, fs, units):
        inline = collections.Counter()
        per_owner = collections.defaultdict(list)
        for u in units:
            lab, own = self.unit_label(u)
            per_owner[lab].append(u)
        for u in units:
            lab, own = self.unit_label(u)
            rec = self.engstr.get((fs.path, lab)) or self.engstr.get((fs.path, u.owner))
            cls = rec["cls"] if rec else "?"
            scr = rec["scr"] if rec else ""
            w = first_int(rec["w"]) if rec else None
            ctx = scrub(scr) or f"{fs.path} {lab}"
            if rec and rec.get("at"):
                ctx += f" — at {scrub(rec['at'])}"
            if rec and rec.get("dep"):
                ctx += f" — {scrub(rec['dep'])}"
            group = per_owner[lab]
            if cls in ("n", "dead"):
                self.skip(
                    fs,
                    u.first_line,
                    u.last_line,
                    f"{path_id(fs.path)}:{lab}",
                    "engine_" + cls,
                    "not text (blanker / tile codes / digits)"
                    if cls == "n"
                    else "dead code (not in the ROM)",
                )
                continue
            if u.kind == "text":
                macros = {s.directive for s in u.active_stmts}
                if not any(s.directive in X.TEXT_MACROS and s.has_strings for s in u.active_stmts):
                    continue
                eid = (
                    self.text_id(fs, u, inline)
                    if len(group) == 1 or not own
                    else f"{path_id(fs.path)}:{lab}[{group.index(u)}]"
                )
                sb = (
                    "speech box" in scr.lower()
                    or "SB" in (rec or {}).get("at", "")
                    or "textbox" in scr.lower()
                    or "message" in scr.lower()
                    or macros & {"line", "para", "cont", "prompt"}
                )
                if macros & {"next", "next1", "page"} and not macros & {"line", "para", "cont"}:
                    if (
                        cls == "a"
                        and (w or 18) >= 12
                        and len([s for s in u.active_stmts if s.has_strings]) <= 6
                    ):
                        nl = len([s for s in u.active_stmts if s.has_strings])
                        self.add_box(fs, u, eid, "engine", ctx, w or 18, nl, 1)
                    else:
                        self.per_line_strings(fs, u, lab, "engine", ctx, w)
                    continue
                if sb or len([s for s in u.active_stmts if s.has_strings]) > 1:
                    self.add_dialog(fs, u, eid, "engine", ctx)
                else:
                    self.per_line_strings(fs, u, lab, "engine", ctx, w)
            else:
                eid = f"{path_id(fs.path)}:{lab}" + (
                    f"[{group.index(u)}]" if len(group) > 1 else ""
                )
                lits = [x for s in u.active_stmts for x in s.strings if x is not None]
                pkmn_only = not X.has_letters("".join(lits)) and _PKMN in "".join(lits)
                if not X.has_letters("".join(lits)) and not pkmn_only:
                    continue
                extra = None
                width = None
                if w is not None:
                    d = X.decompose(self.cm, lits[0], self.consts)
                    eng = d["core_w"]
                    width = max(w - d["lead"], eng) if not d["gap"] else None
                    if d["gap"] and not d["tail_text"]:
                        width = max(w - d["lead"], eng)
                kind = "string"
                multi = len([s for s in u.active_stmts if s.has_strings]) > 1 or any(
                    t in "".join(lits) for t in ("<NEXT>", "<LNBRK>")
                )
                extra = None
                if not any("@" in x for x in lits):
                    # falls through into the next label (e.g. "Foe" -> SpaceText): keep the English width
                    width = None
                    extra = {
                        "note": "no terminator: continues into the following label; composition order is fixed by the engine"
                    }
                if lab == "PrintDayOfWeek.Day":
                    extra = {
                        "allow_empty": True,
                        "note": "printed right after the weekday stem; put full day names in the stems and leave this empty",
                    }
                elif lab.startswith("PrintDayOfWeek."):
                    width = 8
                    extra = {
                        "note": "weekday stem; PrintDayOfWeek.Day is appended after it: write the full day names here"
                    }
                if lab == "_PlaceBattleNickname.EnemyText":
                    width = 6
                    extra = {
                        "note": "the word that marks the opponent's Pokémon in battle text (<USER>/<TARGET>); "
                        "the engine writes it after the nickname, a space before it"
                    }
                self.add_string(
                    fs,
                    u.active_stmts,
                    eid,
                    "engine",
                    ctx,
                    start=u.first_line,
                    end=u.last_line,
                    kind=kind,
                    width=width,
                    exact=multi and cls == "b",
                    extra_limits=extra,
                    allow_no_letters=pkmn_only,
                )

    def per_line_strings(self, fs, u, lab, category, ctx, w):
        k = 0
        for st in u.active_stmts:
            if not st.has_strings:
                continue
            lit = "".join(x for x in st.strings if x is not None)
            eid = f"{path_id(fs.path)}:{lab}[{k}]"
            k += 1
            if not X.has_letters(lit):
                continue
            d = X.decompose(self.cm, lit, self.consts)
            width = None
            if w is not None and not d["tail_text"]:
                width = max(w - d["lead"], d["core_w"])
            self.add_string(
                fs,
                [st],
                eid,
                category,
                ctx + f" (row {k})",
                start=st.line,
                end=st.line,
                width=width,
            )

    # ------------------------------------------------------------------
    def _jr_guard(self):
        """Entries that a `jr` jumps across (text inline in code): their ROM
        size may not grow, or the jump goes out of range."""
        from classic_retro.source.polished_crystal.sizes import SizeModel

        sm = None
        by_file = collections.defaultdict(list)
        for e in self.entries:
            by_file[e["file"]].append(e)
        for path, ents in by_file.items():
            if not path.startswith(("engine/", "home/", "audio/")):
                continue
            fs = self.scan.files[path]
            labels = {}
            for st in fs.stmts:
                for label in st.labels:
                    labels[label] = st.line
            jrs = []
            for st in fs.stmts:
                if st.kind == "stmt" and st.active and st.directive == "jr" and st.args:
                    tgt = st.args[-1].strip()
                    full = (st.glabel + tgt) if tgt.startswith(".") and st.glabel else tgt
                    if full in labels:
                        jrs.append((st.line, labels[full]))
            for e in ents:
                hit = [(a, b) for a, b in jrs if min(a, b) < e["start"] and max(a, b) > e["end"]]
                if not hit:
                    continue
                if sm is None:
                    sm = SizeModel(self.tree)
                en = sm.estimate(self.lines(path)[e["start"] - 1 : e["end"]])
                e["limits"]["rom_bytes"] = en
                e["limits"]["note"] = (
                    (e["limits"].get("note", "") + " " if e["limits"].get("note") else "")
                    + f"a jr at line {hit[0][0]} jumps across this text, which takes {en} ROM "
                    "bytes in English: prepare makes it a jp if the text grows past that"
                )
                self.counters["jr_guarded"] += 1

    def _finish(self):
        # the room the engine-patched screens give the short strings (screen.ROOM)
        ruled = {e["id"] for e in self.entries if screen.apply(e)}
        for missing in sorted(set(screen.ROOM) - ruled):
            self.problems.append(f"{missing}: screen rule for an entry the extractor did not make")
        self._jr_guard()
        for e in self.entries:
            g = self.dr_member_of.get(e["id"])
            if g:
                e["limits"]["dr_groups"] = g
                e["limits"]["note"] = (
                    (e["limits"].get("note", "") + " " if e["limits"].get("note") else "")
                    + "reached through a 1-byte dr offset table: all strings of the table share "
                    + ", ".join(f"{self.dr_groups[x]['slack']} bytes" for x in g)
                    + " of growth"
                )
        # sort entries by file order then line
        order = {p: i for i, p in enumerate(self.scan.order)}
        self.entries.sort(key=lambda e: (order.get(e["file"], 0), e["start"]))

    def manifest(self) -> dict:
        ng = {}
        for e in self.entries:
            if e["id"].endswith("NgramStrings.Pokemon"):
                ng["#mon"] = e["id"]
            elif e["id"].endswith("NgramStrings.Poke"):
                ng["#"] = e["id"]
        return {
            "format": "pc-arabic-manifest/1",
            "ngram_entries": ng,
            "groups": self.dr_groups,
            "entries": self.entries,
            "skipped": self.skipped,
            "problems": self.problems,
        }

    def print_stats(self, out=None):
        out = out or sys.stdout
        c = collections.Counter((e["kind"]) for e in self.entries)
        cat = collections.Counter(e["category"] for e in self.entries)
        cells = collections.Counter()
        kcells = collections.Counter()
        for e in self.entries:
            n = ENC.cells(self.originals[e["id"]].replace("\\p", " ").replace("\\n", " "), e)
            cells[e["category"]] += n
            kcells[e["kind"]] += n
        print(
            f"entries: {len(self.entries)} {dict(c)}; cells {sum(cells.values())} {dict(kcells)}",
            file=out,
        )
        for k, v in sorted(cat.items(), key=lambda x: -x[1]):
            kinds = collections.Counter(e["kind"] for e in self.entries if e["category"] == k)
            print(f"  {k:24s} {v:6d} entries {cells[k]:8d} cells  {dict(kinds)}", file=out)
        sc = collections.Counter(s["category"] for s in self.skipped)
        print(f"skipped: {len(self.skipped)} {dict(sc)}", file=out)
        print(f"problems: {len(self.problems)}", file=out)
        for p in self.problems[:40]:
            print("   ", p, file=out)


ROLE = X.ROLE_DESC


# ---------------------------------------------------------------------------
# literal helpers
# ---------------------------------------------------------------------------


def scrub(s: str) -> str:
    """Remove quoted English (research notes quote menu words) from a context."""
    s = re.sub(r'"[^"]*"|`[^`]*`|“[^”]*”', "…", s or "")
    return re.sub(r"\s+", " ", s).strip(" -—")


def literal_spans(code: str) -> list[tuple[int, int]]:
    """(start, end) indices of each "..." literal (inclusive quotes) in a code line."""
    spans = []
    i = 0
    n = len(code)
    while i < n:
        if code[i] == '"':
            j = i + 1
            while j < n:
                if code[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if code[j] == '"':
                    break
                j += 1
            spans.append((i, j))
            i = j + 1
        else:
            i += 1
    return spans


def strfmt_literal(arg: str) -> str | None:
    """STRFMT("..%d..", EXPR) -> literal with {d:EXPR}."""
    m = re.fullmatch(r'\s*STRFMT\(\s*("(?:[^"\\]|\\.)*")\s*,(.*)\)\s*', arg, re.S)
    if not m:
        return None
    fmt = asmscan.unquote(m.group(1))
    exprs = asmscan.split_args(m.group(2))
    out = []
    k = 0
    for part in re.split(r"(%d)", fmt):
        if part == "%d":
            out.append("{d:" + " ".join(exprs[k].split()) + "}")
            k += 1
        else:
            out.append(part)
    return "".join(out)


def unquote_span(s: str) -> str:
    v = asmscan.unquote(s)
    return v if v is not None else s[1:-1]


def split_seps(cm, content: str, seps) -> list[tuple[str, str]]:
    """Split a literal at inner separator tokens (not at its ends)."""
    toks = X.en_tokens(cm, content)
    # leading / trailing separators stay with their piece (decompose keeps them)
    pieces = []
    cur = []
    for i, t in enumerate(toks):
        if (
            t in seps
            and any(x not in seps and x not in ("@",) for x in toks[:i])
            and any(x not in seps and x != "@" for x in toks[i + 1 :])
        ):
            pieces.append(("".join(cur), t))
            cur = []
        else:
            cur.append(t)
    pieces.append(("".join(cur), ""))
    return pieces


def core_columns(cm, core: str, consts) -> list[tuple[int, int]] | None:
    """Column starts/widths if the core contains runs of ≥2 spaces."""
    if not re.search(r"\S {2,}\S", core):
        return None
    toks = X.en_tokens(cm, core)
    # compute positions in cells
    cols = []
    pos = 0
    i = 0
    cur_start = 0
    cur_w = 0
    while i < len(toks):
        if toks[i] == " " and i + 1 < len(toks) and toks[i + 1] == " ":
            j = i
            while j < len(toks) and toks[j] == " ":
                j += 1
            cols.append([cur_start, cur_w])
            pos += j - i
            cur_start = pos
            cur_w = 0
            i = j
            continue
        w = X.en_piece(cm, toks[i], consts)[2]
        pos += w
        cur_w += w
        i += 1
    cols.append([cur_start, cur_w])
    # each column may use the space up to 2 cells before the next column
    out = []
    for k, (s, w) in enumerate(cols):
        room = (cols[k + 1][0] - 2 - s) if k + 1 < len(cols) else w
        out.append([s, max(w, room)])
    return out
