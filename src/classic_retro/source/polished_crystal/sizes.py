"""The ROM bytes of text source lines, as the game's text macros would emit them.

``SizeModel`` reads a tree's charmap and Huffman code lengths and imitates
``macros/scripts/text.asm``: a ``text``-started stream is Huffman-coded (a
``<CTXT>`` byte and the bits) when that is shorter than its raw bytes, and
``db``/``li``/``rawchar`` strings are raw (with the n-grams of the default
charmap). The overlay uses it where a size is a limit: text a ``jr`` jumps
across, and the strings of a one-byte ``dr`` offset table.
"""

from __future__ import annotations

import math
import os
import re

from classic_retro.source.polished_crystal import asmscan
from classic_retro.source.polished_crystal import units as X
from classic_retro.source.polished_crystal.extract import literal_spans

CMD_BYTES = {
    "text_ram": 3,
    "text_decimal": 4,
    "text_promptbutton": 1,
    "text_pause": 1,
    "text_sound": 2,
    "text_today": 1,
    "text_far": 4,
    "text_plural": 1,
    "text_end": 1,
    "text_asm": 1,
    "text_start": 1,
}
MACRO_CTL = {
    "line": "<LINE>",
    "cont": "<CONT>",
    "para": "<PARA>",
    "next": "<NEXT>",
    "next1": "<LNBRK>",
    "done": "<DONE>",
    "prompt": "<PROMPT>",
    "page": "@",
}


class SizeModel:
    """Bytes of text lines with one tree's charmap and Huffman code lengths.

    ``tree`` reads both from a checkout; ``charmap_text`` (with ``consts``, the
    tree's constants, for ``{d:...}`` widths) from a charmap not yet written.
    """

    def __init__(self, tree: str | None = None, *, charmap_text: str | None = None, consts=None):
        if charmap_text is None:
            with open(os.path.join(tree, "constants", "charmap.asm"), encoding="utf-8") as f:
                charmap_text = f.read()
        self.cm = X.Charmap(text=charmap_text)
        if consts is None:
            consts = asmscan.Consts()
            if tree is not None:
                consts.load_tree(tree)
        self.consts = consts
        self.huff: dict[int, int] = {}
        for m in re.finditer(
            r'ctxtmap\s+"((?:[^"\\]|\\.)*)",\s*\$([0-9A-Fa-f]+),\s*([01]+)', charmap_text
        ):
            self.huff[int(m.group(2), 16)] = len(m.group(3))

    def _codes(self, s: str, cmap: str):
        out = []
        for tok, b in self.cm.tokenize(s, cmap):
            if tok.startswith("{") and tok.endswith("}"):
                n = X.interp_width(tok, self.consts)
                out += [0xE0] * n
            elif b is not None:
                out.append(b)
            else:
                out.append(None)
        return out

    def estimate(self, lines: list[str]) -> int:
        total = 0
        seg_codes: list = []  # current text stream codes
        in_text = False

        def flush(term_needed=False):
            nonlocal total, seg_codes
            if not seg_codes:
                return
            raw = len(seg_codes)
            if all(c is not None and c in self.huff for c in seg_codes):
                bits = sum(self.huff[c] for c in seg_codes)
                if term_needed:
                    bits += self.huff.get(0x53, 9)
                comp = 1 + math.ceil(bits / 8)
                total += min(raw, comp)
            else:
                total += raw
            seg_codes = []

        for raw_line in lines:
            code, _ = asmscan.split_comment(raw_line)
            body = code.strip()
            if not body:
                continue
            body = re.sub(r"^[\w.]+:+\s*", "", body)
            if not body:
                continue
            d = body.split(None, 1)[0].lower()
            spans = literal_spans(body)
            lits = [body[a + 1 : b] for a, b in spans]
            if d in ("text",) or (d in MACRO_CTL and in_text):
                if d == "text":
                    in_text = True
                if d != "text":
                    seg_codes.append(self.cm.maps["compressing"].get(MACRO_CTL[d]))
                for lit in lits:
                    seg_codes += self._codes(lit, "compressing")
                if d in ("done", "prompt"):
                    flush()
                    in_text = False
                elif seg_codes and seg_codes[-1] == 0x53:
                    flush()
            elif d in MACRO_CTL:
                total += 1 + sum(len(self._codes(lit, "default")) for lit in lits)
            elif d in CMD_BYTES:
                flush(term_needed=True)
                total += CMD_BYTES[d]
                if d in ("text_end", "text_asm"):
                    in_text = False
                else:
                    in_text = True
            elif d in ("db", "li", "rawchar") or spans:
                flush()
                cmap = "no_ngrams" if d == "rawchar" else "default"
                n = sum(len(self._codes(lit, cmap)) for lit in lits)
                # numeric db args
                args = asmscan.split_args(body.split(None, 1)[1]) if " " in body else []
                n += (
                    sum(1 for a in args if not a.strip().startswith('"'))
                    if d in ("db", "rawchar")
                    else 0
                )
                total += n + (1 if d == "li" else 0)
            elif d.startswith("def"):
                continue
        flush()
        return total
