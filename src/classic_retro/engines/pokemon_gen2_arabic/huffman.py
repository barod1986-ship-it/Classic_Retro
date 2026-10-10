"""Huffman codes for Polished Crystal's compressed text, from symbol counts.

The game decodes compressed text through a tree built at assembly time from the
``ctxtmap`` lines of ``constants/charmap.asm`` (``data/text/compressed_text.asm``).
Its leaves are the characters ``$7f-$eb`` and the shifted specials ``$4a-$5c``
(the gender codes, the n-gram leaves ``#`` and ``#mon``, the RAM names and the
line codes). Node ids are one byte, parents ``$00-$7e``, so the tree has at most
128 leaves and 127 parents; the assembler keeps its bit accumulator in 32 bits,
so no code may be longer than ``MAX_CODE_BITS``.

Every leaf gets a code, even one never counted, so no text fails to compress
for want of one: a count ``n`` weighs ``2n + 1``. When the longest code would be
too long, rare symbols are weighed up until it fits.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping
from itertools import count

LEAVES: tuple[int, ...] = (*range(0x4A, 0x5D), *range(0x7F, 0xEC))
MAX_PARENTS = 0x7F
MAX_CODE_BITS = 24


def huffman_codes(
    counts: Mapping[int, int], leaves: Iterable[int] = LEAVES, max_bits: int = MAX_CODE_BITS
) -> dict[int, str]:
    """A complete prefix code ("0"/"1" strings) for every leaf, weighed by ``counts``."""
    leaves = tuple(leaves)
    floor = 0
    while True:
        codes = _codes({leaf: max(counts.get(leaf, 0), 0) * 2 + 1 + floor for leaf in leaves})
        if max(len(code) for code in codes.values()) <= max_bits:
            return codes
        floor = floor * 2 + 1


def _codes(weights: Mapping[int, int]) -> dict[int, str]:
    order = count()
    heap: list[tuple[int, int, object]] = [
        (weight, next(order), leaf) for leaf, weight in weights.items()
    ]
    heapq.heapify(heap)
    children: dict[object, tuple[object, object]] = {}
    while len(heap) > 1:
        weight_a, _, a = heapq.heappop(heap)
        weight_b, _, b = heapq.heappop(heap)
        node = ("node", next(order))
        children[node] = (a, b)
        heapq.heappush(heap, (weight_a + weight_b, node[1], node))
    if len(children) > MAX_PARENTS:
        raise ValueError(f"{len(children)} parent nodes, at most {MAX_PARENTS}")
    codes: dict[int, str] = {}
    stack: list[tuple[object, str]] = [(heap[0][2], "")]
    while stack:
        node, prefix = stack.pop()
        if node in children:
            left, right = children[node]
            stack.append((left, prefix + "0"))
            stack.append((right, prefix + "1"))
        else:
            assert isinstance(node, int)
            codes[node] = prefix
    return codes


def is_complete_prefix_code(codes: Iterable[str]) -> bool:
    """Whether no code prefixes another and the codes fill the tree (Kraft sum 1)."""
    ordered = sorted(codes)
    if any(b.startswith(a) for a, b in zip(ordered, ordered[1:], strict=False)):
        return False
    return sum(2.0 ** -len(code) for code in ordered) == 1.0


def coded_bits(counts: Mapping[int, int], codes: Mapping[int, str]) -> int:
    """Bits the counted symbols take with ``codes``."""
    return sum(number * len(codes[symbol]) for symbol, number in counts.items() if symbol in codes)
