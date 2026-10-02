"""Adding a string table to the Chrono Trigger translation, from the user's own ROM.

The translation takes the dialogue a whole string table at a time (``TABLES`` in
``chrono_trigger_arabic_script``). Adding one is four commands of the
``chrono-trigger`` group:

- ``tables ROM`` lists the fifteen tables that hold the dialogue, each with its
  number of strings and, when translated, its key;
- ``new-table ROM ADDRESS KEY`` reads one from the ROM into two local files: a
  workspace (``targets extract``'s format: each message's original, so it holds
  the game's text and stays on the user's machine) and a *plan* that holds none:
  each message's pin (its number, the SHA-256 of its bytes and its commands), the
  decision boxes the location events open on its messages, the messages that run
  on inside another, and what is left to decide by hand;
- ``check-table PLAN FILE`` checks the translated messages of the workspace, or of
  a batch of it (``targets split``), one by one as the build will;
- ``adopt-table PLAN WORKSPACE`` writes the table into the script module (its
  ``TABLES`` entry, its ``DECISIONS`` and its pins) and its Arabic into the
  shipped translations, whose contexts say only where each message is.

Decisions come from a scan of the location events: each script is unpacked, and
a byte ``B8`` with a table's address, then ``C0``, ``C3`` or ``C4`` with a string's
number and the first and last lines of its choices, is taken as a decision box on
that string. The scan reads bytes, not the event language, so a decision is kept
only when the original's lines it names are its indented option lines; anything
else goes to the plan's ``review`` for a person.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.chrono_trigger import (
    PAUSE,
    WITH_BYTE,
    command_skeleton,
    dictionary,
    string_bytes,
    string_notation,
    table_count,
    table_string,
)
from classic_retro.engines.chrono_trigger_arabic import (
    ChronoTriggerArabicEncoder,
    build_chrono_trigger_font,
    chrono_trigger_glyph_codes,
    glyph_characters,
    message_characters,
    validate_command_skeleton,
)
from classic_retro.localization.entries import notation_warnings
from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    builtin_translation_set,
)
from classic_retro.rom import chrono_trigger_arabic_script as script
from classic_retro.rom.chrono_trigger_arabic import (
    IMAGE,
    ROM_BANK,
    check_choices,
    verify_usa_image,
)
from classic_retro.rom.chrono_trigger_arabic_script import ChronoTriggerMessage

# The fifteen string tables that hold the dialogue, by file offset
# (docs/CHRONO_TRIGGER_ARABIC_RENDERER.md).
DIALOGUE_TABLES = (
    0x18D000,
    0x18DD80,
    0x1EC000,
    0x1EE300,
    0x36A000,
    0x36B230,
    0x370000,
    0x374900,
    0x384650,
    0x39B000,
    0x3CBA00,
    0x3F4460,
    0x3F5860,
    0x3F6B00,
    0x3F8400,
)
# The location events: three bytes a location at $FC:F9F0, each the address of
# its compressed script.
LOCATION_EVENTS = 0x3CF9F0
LOCATIONS = 0x201
# The event commands the decision scan reads: one names the string table that
# the dialogue commands after it take their strings from; the others open a box
# of a string's number with the first and last line of its choices.
SET_STRING_TABLE = 0xB8
DECISION_COMMANDS = frozenset((0xC0, 0xC3, 0xC4))
# An option line of a decision, as the English writes it.
OPTION_INDENT = "   "
_LINES = re.compile(r"\{line\+?(?: auto| wait)?\}")
_BOXES = re.compile(r"\{box\+?(?: auto)?\}")
# A table's key in the entries' ids.
_KEY = re.compile(r"[a-z][a-z0-9_]*")
PLAN_VERSION = 1
# A quotation of the English in a glossary note, which no committed file may hold.
ORIGINAL_QUOTE = re.compile(r"«[^»]*[A-Za-z]{2,}[^»]*»")


def snes_address(offset: int) -> str:
    """A file offset as the HiROM address the docs write (``$F7:4900``)."""
    address = ROM_BANK + offset
    return f"${address >> 16:02X}:{address & 0xFFFF:04X}"


def table_offset(text: str) -> int:
    """A table's file offset from ``$F7:4900``, ``F7:4900``, ``0xF74900`` or ``0x374900``."""
    cleaned = text.strip().lstrip("$").replace(":", "")
    try:
        value = int(cleaned, 16)
    except ValueError as exc:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No address in {text!r}") from exc
    offset = value - ROM_BANK if value >= ROM_BANK else value
    if offset not in DIALOGUE_TABLES:
        known = ", ".join(snes_address(table) for table in DIALOGUE_TABLES)
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            f"{snes_address(offset)} is not one of the dialogue's tables ({known})",
        )
    return offset


# ---------------------------------------------------------------------------
# The location events


def decompress(rom: bytes, offset: int) -> bytes:
    """The data of the game's compressed block at ``offset``.

    A block starts with the size of its first run of codes; each control byte
    then says, a bit for each item from its lowest, whether the item is a byte
    to copy (0) or two bytes naming earlier output (1): an offset back and a
    length, 12 and 4 bits or 11 and 5 by the block's mode, the top bits of the
    byte after the run. A control byte of zero copies the eight bytes after it.
    Past a run, a byte of zero ends the block; another gives the number of items
    of the next control byte and a word, the next run's end in the bank.
    """
    bank = offset & ~0xFFFF
    start = offset & 0xFFFF

    def word(at: int) -> int:
        return int(struct.unpack_from("<H", rom, at)[0])

    at = offset + 2
    end = at + word(offset)
    if end >= len(rom):
        raise ClassicRetroError(ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "A block past the ROM")
    mask, shift = (0x0FFF, 4) if rom[end] & 0xC0 == 0 else (0x07FF, 3)
    out = bytearray()
    items = 8

    def item(copy: int) -> None:
        nonlocal at
        if not copy:
            out.append(rom[at])
            at += 1
            return
        back = word(at) & mask
        length = (rom[at + 1] >> shift) + 3
        source = len(out) - back
        if source < 0:
            raise ClassicRetroError(
                ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "A copy from before the block"
            )
        for index in range(length):
            out.append(out[source + index])
        at += 2

    while True:
        if at == end:
            count = rom[at] & 0x3F
            if count == 0:
                return bytes(out)
            items = count
            end = bank + ((start + word(at + 1)) & 0xFFFF)
            at += 3
            continue
        if at > end or at >= len(rom) or len(out) > 0x10000:
            raise ClassicRetroError(
                ErrorCode.COMPRESSION_ROUNDTRIP_FAILED, "A block that does not end"
            )
        control = rom[at]
        if control == 0:
            out += rom[at + 1 : at + 9]
            at += 9
            continue
        at += 1
        item(control & 1)
        control >>= 1
        while True:
            items -= 1
            if items == 0:
                items = 8
                break
            item(control & 1)
            control >>= 1


def location_events(rom: bytes) -> tuple[list[bytes], int]:
    """Every location's event script, and how many could not be read."""
    scripts: list[bytes] = []
    unread = 0
    for number in range(LOCATIONS):
        at = LOCATION_EVENTS + 3 * number
        address = rom[at] | rom[at + 1] << 8 | rom[at + 2] << 16
        if not ROM_BANK <= address < ROM_BANK + len(rom):
            break
        try:
            scripts.append(decompress(rom, address - ROM_BANK))
        except (ClassicRetroError, IndexError, struct.error):
            unread += 1
    return scripts, unread


def decision_ops(
    scripts: Iterable[bytes], table: int, count: int
) -> dict[int, set[tuple[int, int]]]:
    """The decision boxes the scripts open on the table's strings, by string number:
    the first and the last line of each one's choices."""
    base = ROM_BANK + table
    found: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for data in scripts:
        current = None
        for at in range(len(data) - 3):
            if data[at] == SET_STRING_TABLE and data[at + 3] >= ROM_BANK >> 16:
                current = data[at + 1] | data[at + 2] << 8 | data[at + 3] << 16
            if data[at] in DECISION_COMMANDS and current is not None:
                if not base <= current < base + 2 * count:
                    continue
                operand = data[at + 2]
                first, last = operand >> 2 & 3, operand & 3
                number = (current - base) // 2 + data[at + 1]
                if operand <= 0x0F and first < last and number < count:
                    found[number].add((first, last))
    return dict(found)


def option_lines(notation: str) -> list[int]:
    """The lines of the original's last box that it indents as options."""
    last_box = _BOXES.split(notation.split("{pause 00}")[-1])[-1]
    return [
        number
        for number, line in enumerate(_LINES.split(last_box))
        if line.startswith(OPTION_INDENT) and line.strip()
    ]


def _pause_ends(data: bytes) -> list[int]:
    """The offsets just past each ``{pause 00}`` of a string, read code by code."""
    ends = []
    at = 0
    while at < len(data):
        if data[at] in WITH_BYTE:
            if data[at] == PAUSE and at + 1 < len(data) and data[at + 1] == 0:
                ends.append(at + 2)
            at += 2
        else:
            at += 1
    return ends


def tails(rom: bytes, table: int, count: int) -> tuple[dict[int, tuple[int, int]], list[int]]:
    """The strings that run on inside another: each one's string and segment (the
    part after that string's n-th ``{pause 00}``), and the strings that start inside
    another anywhere else."""
    starts = [table_string(rom, table, number) for number in range(count)]
    lengths = [len(string_bytes(rom, start)) for start in starts]
    found: dict[int, tuple[int, int]] = {}
    odd: list[int] = []
    for number, start in enumerate(starts):
        heads = [
            other
            for other, other_start in enumerate(starts)
            if other_start < start < other_start + lengths[other]
        ]
        if not heads:
            continue
        head = min(heads, key=lambda other: starts[other])
        ends = _pause_ends(string_bytes(rom, starts[head]))
        if start - starts[head] in ends:
            found[number] = (head, ends.index(start - starts[head]) + 1)
        else:
            odd.append(number)
    return found, odd


# ---------------------------------------------------------------------------
# The plan


def list_tables(rom: bytes) -> list[dict[str, object]]:
    """``chrono-trigger tables``: every dialogue table, and which are translated."""
    keys = {table.address: table.key for table in script.TABLES.values()}
    rows = []
    for table in DIALOGUE_TABLES:
        try:
            strings: int | None = table_count(rom, table)
        except ClassicRetroError:
            strings = None
        rows.append(
            {"address": snes_address(table), "strings": strings, "translated": keys.get(table)}
        )
    return rows


def plan_table(
    rom: bytes, table: int, key: str, what: str = "", *, verify_identity: bool = True
) -> tuple[dict[str, Any], dict[str, str]]:
    """``new-table``: a table's plan, and each message's original by id.

    The plan holds no text of the game; the originals are for the workspace.
    """
    if verify_identity:
        verify_usa_image(rom)
    if not _KEY.fullmatch(key):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"A table's key is lower-case letters and digits: {key!r}"
        )
    for existing in script.TABLES.values():
        if existing.key == key or existing.address == table:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE,
                f"{snes_address(existing.address)} is translated already, as {existing.key}",
            )
    count = table_count(rom, table)
    words = dictionary(rom)
    ids = [f"{key}.{number:03d}" for number in range(count)]
    messages: dict[str, dict[str, Any]] = {}
    originals: dict[str, str] = {}
    for number, entry_id in enumerate(ids):
        data = string_bytes(rom, table_string(rom, table, number))
        messages[entry_id] = {
            "index": number,
            "sha256": hashlib.sha256(data).hexdigest(),
            "skeleton": list(command_skeleton(data)),
        }
        originals[entry_id] = string_notation(data, words)
    chains, odd = tails(rom, table, count)
    scripts, unread = location_events(rom)
    review: list[dict[str, Any]] = [
        {"id": ids[number], "why": "it starts inside another string, not after a {pause 00}"}
        for number in odd
    ]
    decisions: dict[str, list[int]] = {}
    ops = decision_ops(scripts, table, count)
    for number, entry_id in enumerate(ids):
        options = option_lines(originals[entry_id])
        found = sorted(ops.get(number, ()))
        fitting = [op for op in found if set(range(op[0], op[1] + 1)) <= set(options)]
        if len(fitting) == 1:
            decisions[entry_id] = list(fitting[0])
        elif found:
            review.append(
                {
                    "id": entry_id,
                    "why": "the events open a decision box that its option lines do not match",
                    "events": [list(op) for op in found],
                    "option_lines": options,
                }
            )
        elif len(options) > 1 and options == list(range(options[0], options[-1] + 1)):
            review.append(
                {
                    "id": entry_id,
                    "why": "its last box ends with option lines, but no event was found that "
                    "opens a decision box on it: add it to decisions if the game asks",
                    "option_lines": options,
                }
            )
    plan = {
        "plan_version": PLAN_VERSION,
        "target": script.TARGET,
        "image_sha256": IMAGE.sha256,
        "table": {"key": key, "address": snes_address(table), "count": count, "what": what},
        "messages": messages,
        "decisions": decisions,
        "tails": {
            ids[number]: {"of": ids[head], "segment": segment}
            for number, (head, segment) in sorted(chains.items())
        },
        "review": review,
        "events": {"read": len(scripts), "unread": unread},
    }
    return plan, originals


def table_workspace(plan: Mapping[str, Any], originals: Mapping[str, str]) -> TranslationSet:
    """The table's workspace: every message with its original and no Arabic yet."""
    shipped = builtin_translation_set(script.TARGET)
    key = plan["table"]["key"]
    entries = []
    for entry_id, message in plan["messages"].items():
        notes = []
        tail = plan["tails"].get(entry_id)
        if tail:
            notes.append(
                f"It runs on inside {tail['of']} after its {{pause 00}} number "
                f"{tail['segment']}: its Arabic is that message's Arabic from there on."
            )
        choices = plan["decisions"].get(entry_id)
        if choices:
            notes.append(
                f"A decision box: lines {choices[0] + 1} to {choices[1] + 1} of its last box are "
                "the choices; write them, and only them, as {choice} lines."
            )
        entries.append(
            Translation(
                entry_id,
                "",
                context=f"Message {message['index']} of the {key} table",
                source=originals[entry_id],
                notes=" ".join(notes) or None,
            )
        )
    return TranslationSet(
        script.TARGET,
        shipped.notation,
        tuple(entries),
        glossary=shipped.glossary,
        workspace_from=f"{IMAGE.title}, SHA-256 {IMAGE.sha256}",
    )


def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"Could not read the plan {path}: {exc}"
        ) from exc
    if (
        not isinstance(plan, dict)
        or plan.get("plan_version") != PLAN_VERSION
        or plan.get("target") != script.TARGET
    ):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{path} is not a Chrono Trigger table plan"
        )
    return plan


# ---------------------------------------------------------------------------
# The check


def _message(plan: Mapping[str, Any], entry_id: str, text: str) -> ChronoTriggerMessage:
    message = plan["messages"][entry_id]
    choices = plan["decisions"].get(entry_id)
    return ChronoTriggerMessage(
        entry_id,
        table_offset(plan["table"]["address"]),
        message["index"],
        message["sha256"],
        text,
        tuple(message["skeleton"]),
        None if choices is None else (choices[0], choices[1]),
    )


def check_table(
    plan: Mapping[str, Any], translations: TranslationSet, font: Path | None
) -> dict[str, object]:
    """``check-table``: every translated message of the table checked as the build
    checks it, an error for each one refused; untranslated messages are counted."""
    characters = glyph_characters()
    glyph_map = chrono_trigger_glyph_codes(characters)
    ct_font = None if font is None else build_chrono_trigger_font(font, glyph_map, characters)
    encoder = ChronoTriggerArabicEncoder(glyph_map, ct_font)
    texts = {entry.id: entry.text for entry in translations.entries}
    sources = {entry.id: entry.source for entry in translations.entries}
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    untranslated: list[str] = []
    passed: set[str] = set()

    def refuse(entry_id: str, code: str, message: str) -> None:
        errors.append({"id": entry_id, "code": code, "message": message})

    for entry in translations.entries:
        if entry.id not in plan["messages"]:
            refuse(
                entry.id,
                ErrorCode.INVALID_TRANSLATION_DOCUMENT.value,
                f"The {plan['table']['key']} table has no message {entry.id}",
            )
            continue
        if not entry.text.strip():
            untranslated.append(entry.id)
            continue
        message = _message(plan, entry.id, entry.text)
        try:
            validate_command_skeleton(message.source_skeleton or (), entry.text)
            message_characters(entry.text)
            check_choices(message, encoder.encode(entry.text))
        except ClassicRetroError as exc:
            refuse(entry.id, exc.code.value, str(exc))
            continue
        passed.add(entry.id)
        warnings.extend(notation_warnings(entry.id, entry.text, sources.get(entry.id)))
    # A message that runs on inside another is that one's Arabic from its segment on.
    for entry_id, tail in plan["tails"].items():
        head = tail["of"]
        if entry_id not in passed or head not in passed:
            continue
        parts = texts[head].split("{pause 00}")
        expected = "{pause 00}".join(parts[tail["segment"] :])
        if len(parts) <= tail["segment"] or texts[entry_id] != expected:
            passed.discard(entry_id)
            refuse(
                entry_id,
                ErrorCode.INVALID_TRANSLATION_DOCUMENT.value,
                f"{entry_id} runs on inside {head}: its Arabic must be {head}'s from its "
                f"{{pause 00}} number {tail['segment']} on",
            )
    order = {entry_id: number for number, entry_id in enumerate(plan["messages"])}
    errors.sort(key=lambda error: order.get(str(error["id"]), -1))
    return {
        "table": plan["table"]["key"],
        "messages": len(plan["messages"]),
        "checked": len(passed) + len(errors),
        "untranslated": len(untranslated),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_with_font": font is not None,
    }


# ---------------------------------------------------------------------------
# Adoption

SCRIPT_PATH = Path(script.__file__)
_TABLES_END = re.compile(r"(\nTABLES = \{\n.*?)(\n\}\n)", re.S)
_DECISIONS_END = re.compile(
    r"(\nDECISIONS: dict\[str, tuple\[int, int\]\] = \{\n.*?)(\n\}\n)", re.S
)
_SOURCES_END = re.compile(r"(\n_SOURCES: dict\[.*?\] = \{\n.*?)(\n\}\n# fmt: on\n)", re.S)


def _insert(source: str, pattern: re.Pattern[str], lines: Sequence[str], what: str) -> str:
    match = pattern.search(source)
    if match is None:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"No {what} in the script module")
    if not lines:
        return source
    return source[: match.end(1)] + "\n" + "\n".join(lines) + source[match.end(1) :]


def adopt_table(
    plan: Mapping[str, Any],
    workspace: TranslationSet,
    font: Path,
    *,
    what: str | None = None,
    script_path: Path = SCRIPT_PATH,
    translations_path: Path | None = None,
) -> dict[str, object]:
    """``adopt-table``: the table into the script module and the shipped translations.

    Every message must be translated and pass ``check_table`` with the font. The
    shipped file gets each message's Arabic and a context that says only where it
    is: never its original, which no committed file holds.
    """
    key = plan["table"]["key"]
    what = (what if what is not None else plan["table"].get("what", "")).strip()
    place = what.split(",")[0].strip()
    if not place or re.search(r"[():{}]", place):
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            "Say what the table holds (--what): the places first, without ( ) : { }",
        )
    report = check_table(plan, workspace, font)
    missing = [
        entry_id for entry_id in plan["messages"] if entry_id not in workspace_ids(workspace)
    ]
    if missing or report["untranslated"] or not report["ok"]:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSLATION_DOCUMENT,
            f"The {key} table is not ready: {len(missing)} messages missing, "
            f"{report['untranslated']} untranslated, {len(report['errors'])} refused "
            "(check-table lists them)",
        )
    source = script_path.read_text(encoding="utf-8")
    if re.search(rf'\n    "{re.escape(key)}": StringTable\(', source):
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, f"{key} is in TABLES already")
    address = table_offset(plan["table"]["address"])
    table_lines = [
        f'    "{key}": StringTable(',
        f'        "{key}",',
        f"        {address:#x},",
        f"        {plan['table']['count']},",
        f"        {json.dumps(what, ensure_ascii=False)},",
        "    ),",
    ]
    decision_lines = [
        f'    "{entry_id}": ({lines[0]}, {lines[1]}),'
        for entry_id, lines in plan["decisions"].items()
    ]
    pin_lines = [
        f'    "{entry_id}": ({message["index"]}, "{message["sha256"]}", '
        f"{tuple(message['skeleton'])!r}),"
        for entry_id, message in plan["messages"].items()
    ]
    source = _insert(source, _TABLES_END, table_lines, "TABLES")
    source = _insert(source, _DECISIONS_END, decision_lines, "DECISIONS")
    source = _insert(source, _SOURCES_END, pin_lines, "_SOURCES")
    compile(source, str(script_path), "exec")

    shipped_path = translations_path or Path(script.__file__).parents[1] / "translations" / (
        f"{script.TARGET}.json"
    )
    shipped = json.loads(shipped_path.read_text(encoding="utf-8"))
    known = {entry["id"] for entry in shipped["entries"]}
    clash = sorted(known & set(plan["messages"]))
    if clash:
        raise ClassicRetroError(
            ErrorCode.DUPLICATE_ENTRY_ID, f"Shipped already: {', '.join(clash[:5])}"
        )
    texts = {entry.id: entry.text for entry in workspace.entries}
    for entry_id, message in plan["messages"].items():
        shipped["entries"].append(
            {
                "id": entry_id,
                "context": f"Message {message['index']} of the {key} table ({place}...)",
                "text": texts[entry_id],
            }
        )
    added = _glossary_additions(shipped.get("glossary", []), workspace.glossary, texts.values())
    if added:
        shipped["glossary"] = [*shipped.get("glossary", []), *added]
    script_path.write_text(source, encoding="utf-8")
    shipped_path.write_text(
        json.dumps(shipped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "table": key,
        "address": plan["table"]["address"],
        "messages": len(plan["messages"]),
        "decisions": len(plan["decisions"]),
        "glossary_added": [term["term"] for term in added],
        "script": str(script_path),
        "translations": str(shipped_path),
        "next": [
            "ruff format " + str(script_path),
            "the target's scope and the docs name the new table",
            "classic-retro targets check-translations chrono-trigger --font FONT "
            "--preview-dir DIR --update-digests",
            "classic-retro targets build chrono-trigger ROM --font FONT --out-dir DIR, "
            "and its patch_sha256 as the target's reference_patch_sha256",
            "CLASSIC_RETRO_UPDATE_PINS=1 python -m pytest tests/test_overlay_pins.py",
            "the count of chrono-trigger entries in tests/test_translations.py",
        ],
    }


def workspace_ids(translations: TranslationSet) -> set[str]:
    return {entry.id for entry in translations.entries}


def _glossary_additions(
    shipped: Sequence[Mapping[str, str]],
    terms: Sequence[GlossaryTerm],
    texts: Iterable[str],
) -> list[dict[str, str]]:
    """The workspace's terms the shipped glossary lacks and the new Arabic uses; a
    term the shipped glossary writes otherwise is refused."""
    have = {term["term"]: term["text"] for term in shipped}
    joined = "\n".join(texts)
    added = []
    for term in terms:
        if term.notes and ORIGINAL_QUOTE.search(term.notes):
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                f"The note of the glossary term {term.term} quotes the original: no committed "
                "file holds text of the game",
            )
        if term.term in have:
            if have[term.term] != term.text:
                raise ClassicRetroError(
                    ErrorCode.INVALID_TRANSLATION_DOCUMENT,
                    f"The glossary writes {term.term} {have[term.term]}, the workspace {term.text}",
                )
            continue
        if term.text in joined:
            added.append(
                {
                    "term": term.term,
                    "text": term.text,
                    **({"notes": term.notes} if term.notes else {}),
                }
            )
    return added


def with_text(translations: TranslationSet, texts: Mapping[str, str]) -> TranslationSet:
    """``translations`` with these entries' text (for tests and tools)."""
    return replace(
        translations,
        entries=tuple(
            replace(entry, text=texts[entry.id]) if entry.id in texts else entry
            for entry in translations.entries
        ),
    )
