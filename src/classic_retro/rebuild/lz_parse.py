"""Optimal parsing for the LZ77 formats of Nintendo's handhelds.

The GBA/DS BIOS LZ77 (``lz77``) and the DS backward LZ of ARM9 binaries
(``blz``) share their items: a flag bit per item, a literal byte, or a match of
3..18 bytes coded in two bytes. They differ in the window and the shortest
distance. With every match costing the same, the fewest bits come from the
longest match at each position (any shorter one is a prefix of it) and a
shortest-path choice over the data, from its end.
"""

from __future__ import annotations

MIN_MATCH = 3
MAX_MATCH = 18
LITERAL_BITS = 9
MATCH_BITS = 17


def longest_matches(
    data: bytes, *, min_distance: int, max_distance: int, start: int = 0, end: int | None = None
) -> list[int]:
    """The longest match at each position of ``start``..``end`` (0 for none).

    Matches end by ``end`` and may copy from anywhere before their position at
    a distance in the range, the bytes before ``start`` included. ``bytes.rfind``
    looks for a match; a match of some length implies one of every shorter
    length at the same place, so a binary search on the length finds the
    longest. A match may run on into the bytes it produces.
    """
    end = len(data) if end is None else end
    lengths = [0] * (end - start)
    rfind = data.rfind
    for position in range(start, end - MIN_MATCH + 1):
        window = max(0, position - max_distance)
        reach = position - min_distance
        if reach < window:
            continue
        if rfind(data[position : position + MIN_MATCH], window, reach + MIN_MATCH) < 0:
            continue
        found, missing = MIN_MATCH, min(MAX_MATCH, end - position) + 1
        while missing - found > 1:
            length = (found + missing) // 2
            if rfind(data[position : position + length], window, reach + length) >= 0:
                found = length
            else:
                missing = length
        lengths[position - start] = found
    return lengths


def optimal_parse(lengths: list[int]) -> list[int]:
    """The length to take at each position (1 for a literal) for the fewest bits."""
    cost = [0] * (len(lengths) + 1)
    choices = [1] * len(lengths)
    for position in range(len(lengths) - 1, -1, -1):
        best = cost[position + 1] + LITERAL_BITS
        choice = 1
        for length in range(MIN_MATCH, lengths[position] + 1):
            bits = cost[position + length] + MATCH_BITS
            if bits < best:
                best, choice = bits, length
        cost[position] = best
        choices[position] = choice
    return choices


def parse_items(
    data: bytes, *, min_distance: int, max_distance: int, start: int = 0, end: int | None = None
) -> list[tuple[int, int, int]]:
    """The cheapest items for ``data[start:end]``: (1, 0, byte) for a literal,
    (length, distance, 0) for a match."""
    end = len(data) if end is None else end
    choices = optimal_parse(
        longest_matches(
            data, min_distance=min_distance, max_distance=max_distance, start=start, end=end
        )
    )
    items: list[tuple[int, int, int]] = []
    position = start
    while position < end:
        length = choices[position - start]
        if length < MIN_MATCH:
            items.append((1, 0, data[position]))
            position += 1
            continue
        distance = closest_match(data, position, length, min_distance, max_distance)
        assert distance is not None
        items.append((length, distance, 0))
        position += length
    return items


def closest_match(
    data: bytes, position: int, length: int, min_distance: int, max_distance: int
) -> int | None:
    """The shortest distance of a match of ``length`` at ``position``, or None."""
    window = max(0, position - max_distance)
    start = data.rfind(data[position : position + length], window, position - min_distance + length)
    return None if start < 0 else position - start
