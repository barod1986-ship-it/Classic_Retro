"""GT-ZIP, the LZSS of *Gran Turismo* (PlayStation).

A stream is a flags byte, read from its lowest bit, for each group of up to
eight items: a literal byte (flag 0), or a match (flag 1) of a length byte,
``length - 3`` (3..258), and a distance, ``distance - 1`` in one byte below
0x80 or ``0x80 | (distance - 1) >> 8`` then its low byte, up to 0x8000 bytes
back. A match may run on into the bytes it produces. The game's font page
(GAMEFONT.DAT) is a bare stream; its executables are packed with the same items
backwards (``rebuild.pslz``).

``compress_gtzip`` takes the cheapest sequence of items: a literal costs 9
bits, a match 17 with a one-byte distance and 25 with two. Every match of some
length implies one of each shorter length at the same distance, so at each
position the longest match within 0x80 bytes and the longest within the window
are all the parse needs; ``bytes.rfind`` finds them, and a shortest path from
the data's end chooses.

``repack_items`` packs changed data like its original, so that a patch between
the two carries the changes and not the whole stream: the stream keeps its
length; items that still produce the same bytes stay byte for byte; a match
that now copies changed bytes takes another distance of the same width where
the same bytes lie; the groups of eight items around the changes are parsed
again into the same number of bytes and whole groups, so every other group
keeps its bytes. Groups that come out longer take their neighbours in, twice
as many each time, until the parse saves what the change costs (the game's
streams are not the cheapest); shorter ones are padded: matches give bytes to
literals, eight at a time, and near distances are written in two bytes.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence

from classic_retro.core.errors import ClassicRetroError, ErrorCode

MIN_MATCH = 3
MAX_MATCH = 258
# The farthest distance a one-byte distance holds, and the window.
NEAR = 0x80
WINDOW = 0x8000
GROUP = 8
LITERAL_BITS = 9
NEAR_BITS = 17
FAR_BITS = 25

# (1, 0, byte) for a literal; (length, distance, width) for a match, ``width``
# the bytes its distance takes: 1 up to NEAR, else 2 (2 can hold a near one too).
Item = tuple[int, int, int]


def _refuse(message: str) -> ClassicRetroError:
    return ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, message)


def item_size(item: Item) -> int:
    """The bytes an item takes, its flag bit aside."""
    _, distance, value = item
    return 1 + value if distance else 1


def stream_size(items: Sequence[Item]) -> int:
    """The bytes the items take with their flags bytes."""
    return sum(item_size(item) for item in items) + -(-len(items) // GROUP)


def match(length: int, distance: int) -> Item:
    """A match in its shortest encoding."""
    if not (MIN_MATCH <= length <= MAX_MATCH and 1 <= distance <= WINDOW):
        raise _refuse(f"No GT-ZIP match of {length} at {distance}")
    return (length, distance, 1 if distance <= NEAR else 2)


def read_items(data: bytes, size: int) -> tuple[list[Item], int]:
    """The items at the start of ``data`` that produce ``size`` bytes, and where they end."""
    items: list[Item] = []
    position = 0
    produced = 0
    try:
        while produced < size:
            flags = data[position]
            position += 1
            for bit in range(GROUP):
                if produced >= size:
                    break
                if not flags >> bit & 1:
                    items.append((1, 0, data[position]))
                    position += 1
                    produced += 1
                    continue
                length = data[position] + MIN_MATCH
                value = data[position + 1]
                width = 1
                if value & NEAR:
                    value = (value & 0x7F) << 8 | data[position + 2]
                    width = 2
                position += 1 + width
                items.append((length, value + 1, width))
                produced += length
    except IndexError:
        raise _refuse("GT-ZIP data is cut short") from None
    return items, position


def decode_items(items: Sequence[Item]) -> bytes:
    """What the items produce."""
    output = bytearray()
    for length, distance, value in items:
        if not distance:
            output.append(value)
            continue
        if distance > len(output):
            raise _refuse("GT-ZIP match reaches before the data")
        for _ in range(length):
            output.append(output[-distance])
    return bytes(output)


def decompress_gtzip(data: bytes, size: int) -> bytes:
    """The ``size`` bytes the stream at the start of ``data`` holds."""
    output = decode_items(read_items(data, size)[0])
    if len(output) != size:
        raise _refuse(f"GT-ZIP data makes {len(output)} bytes, not {size}")
    return output


def write_items(items: Sequence[Item]) -> bytes:
    """The items with their flags bytes."""
    stream = bytearray()
    flags_at = 0
    for number, (length, distance, value) in enumerate(items):
        if number % GROUP == 0:
            flags_at = len(stream)
            stream.append(0)
        if not distance:
            stream.append(value)
            continue
        stream[flags_at] |= 1 << number % GROUP
        stream.append(length - MIN_MATCH)
        if value == 1:
            stream.append(distance - 1)
        else:
            stream += (0x8000 | distance - 1).to_bytes(2, "big")
    return bytes(stream)


def _longest(data: bytes, position: int, end: int, reach: int, shortest: int) -> int:
    """The longest match of ``shortest`` or more within ``reach`` bytes back (0 for none)."""
    window = max(0, position - reach)
    rfind = data.rfind
    if rfind(data[position : position + shortest], window, position - 1 + shortest) < 0:
        return 0
    longest = min(MAX_MATCH, end - position)
    if rfind(data[position : position + longest], window, position - 1 + longest) >= 0:
        return longest
    found, missing = shortest, longest
    while missing - found > 1:
        length = (found + missing) // 2
        if rfind(data[position : position + length], window, position - 1 + length) >= 0:
            found = length
        else:
            missing = length
    return found


def closest(data: bytes, position: int, length: int, reach: int = WINDOW) -> int | None:
    """The shortest distance, up to ``reach``, of a match of ``length`` at ``position``."""
    window = max(0, position - reach)
    found = data.rfind(data[position : position + length], window, position - 1 + length)
    return None if found < 0 else position - found


def parse_items(data: bytes, start: int = 0, end: int | None = None) -> list[Item]:
    """The cheapest items for ``data[start:end]``; matches may reach before ``start``."""
    end = len(data) if end is None else end
    count = end - start
    cost = [0] * (count + 1)
    choice: list[tuple[int, int]] = [(1, 0)] * count
    for offset in range(count - 1, -1, -1):
        position = start + offset
        best = cost[offset + 1] + LITERAL_BITS
        pick = (1, 0)
        near = 0
        limit = min(MAX_MATCH, end - position)
        if limit < MIN_MATCH:
            pass
        elif (
            position
            and data[position - 1] == data[position + limit - 1]
            and (data[position - 1 : position - 1 + limit] == data[position : position + limit])
        ):
            near = limit  # inside a run: one back, as long as a match goes
        else:
            near = _longest(data, position, end, NEAR, MIN_MATCH)
        far = 0
        if limit > max(near, MIN_MATCH - 1):
            far = _longest(data, position, end, WINDOW, max(near + 1, MIN_MATCH))
        for longest, bits, reach in ((near, NEAR_BITS, NEAR), (far, FAR_BITS, WINDOW)):
            if longest < MIN_MATCH:
                continue
            reachable = cost[offset + MIN_MATCH : offset + longest + 1]
            least = min(reachable)
            if least + bits < best:
                best = least + bits
                pick = (reachable.index(least) + MIN_MATCH, reach)
        cost[offset] = best
        choice[offset] = pick
    items: list[Item] = []
    offset = 0
    while offset < count:
        length, reach = choice[offset]
        position = start + offset
        if length == 1:
            items.append((1, 0, data[position]))
        else:
            distance = closest(data, position, length, reach)
            assert distance is not None
            items.append(match(length, distance))
        offset += length
    return items


def compress_gtzip(data: bytes) -> bytes:
    """``data`` as the cheapest GT-ZIP stream."""
    return write_items(parse_items(data))


def repack_items(items: Sequence[Item], new: bytes) -> list[Item]:
    """Items for ``new`` in the place of ``items`` (see the module notes).

    ``new`` has the length of what ``items`` produce. The result takes as many
    bytes as ``items``, and so does each group of eight but around the changes.
    """
    old = decode_items(items)
    if len(old) != len(new):
        raise _refuse("The changed data has another length")
    changed = _changed_ranges(old, new)
    positions = [0]
    for length, _, _ in items:
        positions.append(positions[-1] + length)

    def touches(start: int, end: int) -> bool:
        index = bisect.bisect_right(changed, (start, float("inf"))) - 1
        return any(
            begin < end and start < finish for begin, finish in changed[max(index, 0) : index + 2]
        )

    marked: set[int] = set()
    kept = list(items)
    for number, (length, distance, width) in enumerate(kept):
        start = positions[number]
        if touches(start, start + length):
            marked.add(number // GROUP)
        elif distance and touches(start - distance, start - distance + length):
            moved = closest(new, start, length, NEAR if width == 1 else WINDOW)
            if moved is None:
                marked.add(number // GROUP)
            else:
                kept[number] = (length, moved, width)

    groups = -(-len(kept) // GROUP)

    def original_group(group: int) -> list[Item]:
        return kept[group * GROUP : (group + 1) * GROUP]

    result: list[Item] = []
    group = 0
    while group < groups:
        if group not in marked:
            result += original_group(group)
            group += 1
            continue
        first = positions[group * GROUP]
        budget = 0
        end = group
        packed = None
        step = 1
        while packed is None:
            if end < groups:
                for _ in range(min(step, groups - end)):
                    budget += stream_size(original_group(end))
                    end += 1
                while end < groups and end in marked:
                    budget += stream_size(original_group(end))
                    end += 1
            elif result:
                taken = result[-GROUP * min(step, len(result) // GROUP) :]
                del result[-len(taken) :]
                budget += stream_size(taken)
                first -= sum(length for length, _, _ in taken)
            else:
                raise _refuse("The changed data does not pack into the original's place")
            step *= 2
            last = positions[min(end * GROUP, len(kept))]
            packed = _fit(new, first, last, budget, whole=end < groups)
        result += packed
        group = end
    return result


def repack_gtzip(original: bytes, data: bytes) -> bytes:
    """``data`` packed in the place of the stream ``original`` (``repack_items``);
    whatever follows the original stream stays."""
    items, end = read_items(original, len(data))
    stream = write_items(repack_items(items, data))
    if len(stream) != end or decompress_gtzip(stream, len(data)) != data:
        raise _refuse("The repacked GT-ZIP stream does not match its original")
    return stream + original[end:]


def _fit(data: bytes, first: int, last: int, budget: int, *, whole: bool) -> list[Item] | None:
    """Items for ``data[first:last]`` in exactly ``budget`` bytes, in whole groups when
    ``whole``; None when they do not fit."""
    items: list[Item] | None = parse_items(data, first, last)
    if whole and items is not None:
        items = _in_groups(items, data, first)
    if items is None:
        return None
    extra = budget - stream_size(items)
    if extra < 0:
        return None
    return _padded(items, data, first, extra)


def _in_groups(items: list[Item], data: bytes, start: int) -> list[Item] | None:
    """The items split until they fill whole groups of eight, or None when they cannot.

    A match of 4 or more gives its first byte to a literal (a byte and an item
    more); one of 3 becomes three literals.
    """
    items = list(items)
    while len(items) % GROUP:
        position = start
        for index, (length, distance, width) in enumerate(items):
            if distance and length > MIN_MATCH:
                items[index : index + 1] = [(1, 0, data[position]), (length - 1, distance, width)]
                break
            position += length
        else:
            position = start
            for index, (length, distance, _) in enumerate(items):
                if distance:
                    items[index : index + 1] = [(1, 0, data[position + k]) for k in range(length)]
                    break
                position += length
            else:
                return None
    return items


def _padded(items: list[Item], data: bytes, start: int, extra: int) -> list[Item] | None:
    """The items ``extra`` bytes longer, or None when they cannot be.

    Eight matches at a time give their first byte to a literal (eight bytes,
    eight items and their flags byte: nine), then near distances are written
    in two bytes (one each).
    """
    near = sum(1 for _, distance, width in items if distance and width == 1)
    while extra > near and extra > GROUP:
        peeled = _peeled(items, data, start, GROUP)
        if peeled is None:
            return None
        items = peeled
        extra -= GROUP + 1
    if extra > near:
        return None
    items = list(items)
    for index, (length, distance, width) in enumerate(items):
        if not extra:
            break
        if distance and width == 1:
            items[index] = (length, distance, 2)
            extra -= 1
    return items


def _peeled(items: list[Item], data: bytes, start: int, count: int) -> list[Item] | None:
    """``count`` matches of 4 or more, from the first, each giving its first byte to a
    literal (a match may give several); None when there are not that many bytes to give."""
    while count:
        output: list[Item] = []
        position = start
        for length, distance, width in items:
            if count and distance and length > MIN_MATCH:
                output += [(1, 0, data[position]), (length - 1, distance, width)]
                count -= 1
            else:
                output.append((length, distance, width))
            position += length
        if len(output) == len(items):
            return None
        items = output
    return items


def _changed_ranges(old: bytes, new: bytes) -> list[tuple[int, int]]:
    """Where two equally long byte strings differ, as sorted (start, end) ranges."""
    ranges: list[tuple[int, int]] = []
    block = 256
    for start in range(0, len(new), block):
        if old[start : start + block] == new[start : start + block]:
            continue
        for position in range(start, min(start + block, len(new))):
            if old[position] != new[position]:
                if ranges and ranges[-1][1] == position:
                    ranges[-1] = (ranges[-1][0], position + 1)
                else:
                    ranges.append((position, position + 1))
    return ranges
