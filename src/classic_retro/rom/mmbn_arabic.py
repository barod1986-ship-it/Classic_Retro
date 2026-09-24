"""Arabic ROM overlay for *Mega Man Battle Network* (USA).

The Silenthal/bn1 disassembly (https://github.com/Silenthal/bn1) matches this
exact image and gave every address below. Its assets are extracted from the
original, so the overlay patches the user's image (``AREE``, SHA-256 below)
and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   every translated section's original is checked against its pinned hash;
2. the Thumb hooks (``mmbn_arabic_hooks.s``), their bank table, the rebuilt
   script archives and the glyph banks go into the linker padding (``0xFF``)
   between the end of the code and the IWRAM code at ``0x08180000``; the
   image stays 8 MiB;
3. every page of a translated section is drawn ahead of time
   (``engines.mmbn_arabic``) and its cells form a bank laid out like the
   dialogue font (64 bytes per cell, at an address the font's own can reach:
   ``font + 64 * offset``); the bank table maps the address of each page's
   text to its bank;
4. ``Text_Main``'s call of ``Text_CopyCharTile`` for one-byte characters goes
   to ``hook_copy``, and the column computation of ``Text_LoadCharTileLayout``
   to ``hook_column``: text inside a translated page reads its cells from the
   page's bank and fills its lines from column 27 leftwards; any other text
   keeps the font and the left-to-right layout;
5. every archive with a translated section is rebuilt whole (untranslated
   sections are copied byte for byte) and its pointer repointed.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.mmbn import (
    BOX_COLUMNS,
    BOX_LINES,
    CELL_BYTES,
    CLEAR,
    FIRST_COLUMN,
    FIRST_COMMAND,
    NEWLINE,
    PAGE_CELLS,
    ROM_BASE,
    SECTION_TRAILER,
    SYMBOL_LEAD,
    ScriptArchive,
    build_archive,
    command_skeleton,
    decode_command,
    parse_notation,
)
from classic_retro.engines.mmbn_arabic import (
    BASELINE,
    FONT_SIZE,
    LAST_COLUMN,
    LINE_PIXELS,
    MmbnArabicEncoder,
    MmbnArabicScript,
    MmbnLineRenderer,
    game_latin_cells,
    pages_sheet,
    validate_command_skeleton,
)
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.mmbn_arabic_script import (
    MmbnArabicSection,
    MmbnScriptArchive,
    mmbn_arabic_sections,
    mmbn_script_archives,
)

USA_SHA256 = "87bc7257f2f9ed0acc9f4874177e474e3d339d1e23a0b621d2d8edd73c1a09ed"
USA_SIZE = 0x800000

# tilesetDialogueText: 512 glyphs of 64 bytes, read by Text_CopyCharTile
# through the literal at 0x08013984.
FONT_ADDRESS = 0x08613AA8
FONT_LITERAL_ADDRESS = 0x08013984
TEXT_COPY_CHAR_TILE = 0x080137C0
# Text_CopyCharTile up to its return: glyph = font + code * 64, copied (with
# the colour shift) into the next slot of the tile buffer.
TEXT_COPY_CHAR_TILE_CODE = bytes.fromhex(
    "7048890140187049aa78920189186f4fea7c9200bf5840220368db190b6004300431043af8d1ab780133ab70f746"
)

# The code ends at 0x08160AC4; linker padding (0xFF) follows up to the IWRAM
# code copied from 0x08180000.
PADDING_START = 0x08160AC4
PADDING_END = 0x08180000
HOOK_CODE_ADDRESS = 0x08160B00
REGION_END = PADDING_END
FREE_FILL = 0xFF
NO_BANK = 0x80000000
HOOK_SOURCE = Path(__file__).with_name("mmbn_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi mmbn_arabic_hooks.s; ld -Ttext 0x08160B00; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "00b500f018f801bc86460120c007824200d089181648004700b5ae7b701ca873"
    "00f009f80120c007824202d01b20861b00bd083600bd0f480268944215d28268"
    "944212d30ab44168083001290ad04b08da008258944203d3da008018c91af4e7"
    "1900f2e742680abc70470122d2077047c1370108780b1608"
)
HOOK_SYMBOLS = {
    "hook_copy": 0x00,
    "hook_column": 0x18,
    "bank_offset": 0x36,
    "bank_table": 0x78,
}
BANK_TABLE_ADDRESS = HOOK_CODE_ADDRESS + HOOK_SYMBOLS["bank_table"]
NOP = bytes.fromhex("c046")


@dataclass(frozen=True, slots=True)
class HookSite:
    """Code replaced by a ``BL`` to a hook, padded with ``NOP``s to its length."""

    address: int
    original: bytes
    symbol: str
    purpose: str


HOOK_SITES = (
    HookSite(0x080136F2, bytes.fromhex("00f065f8"), "hook_copy", "Text_Main: one-byte character"),
    HookSite(
        0x08013806,
        bytes.fromhex("ae7b701ca8730836"),
        "hook_column",
        "Text_LoadCharTileLayout: column of the next cell",
    ),
)


@dataclass(frozen=True, slots=True)
class MmbnArabicBuild:
    rom: bytes
    patch: BpsPatch
    scripts: dict[str, MmbnArabicScript]
    report: dict[str, object] = field(default_factory=dict)


def _offset(address: int) -> int:
    return address - ROM_BASE


def bl_instruction(address: int, target: int) -> bytes:
    offset = target - (address + 4)
    if not -0x400000 <= offset < 0x400000 or offset % 2:
        raise ClassicRetroError(
            ErrorCode.WRITE_OUT_OF_BOUNDS, f"{target:#x} is out of BL range from {address:#x}"
        )
    return struct.pack("<HH", 0xF000 | offset >> 12 & 0x7FF, 0xF800 | offset >> 1 & 0x7FF)


def bl_target(address: int, data: bytes) -> int:
    high, low = struct.unpack("<HH", data)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"No BL at {address:#x}")
    offset = (high & 0x7FF) << 12 | (low & 0x7FF) << 1
    if offset & 0x400000:
        offset -= 0x800000
    return address + 4 + offset


def site_patch(site: HookSite) -> bytes:
    code = bl_instruction(site.address, HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol])
    return code + NOP * ((len(site.original) - len(code)) // 2)


def source_digest(data: bytes) -> str:
    """SHA-256 of an original section's script (its ending command included)."""
    return hashlib.sha256(data).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    if len(rom) != USA_SIZE or hashlib.sha256(rom).hexdigest() != USA_SHA256:
        raise ClassicRetroError(
            ErrorCode.UNKNOWN_GAME_REVISION,
            "Input is not Mega Man Battle Network (USA) with SHA-256 " + USA_SHA256,
        )


def _verify_anchors(rom: bytes, archives: tuple[MmbnScriptArchive, ...]) -> None:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB")
    for site in HOOK_SITES:
        start = _offset(site.address)
        if rom[start : start + len(site.original)] != site.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {site.address:#x} ({site.purpose})",
            )
    if bl_target(HOOK_SITES[0].address, HOOK_SITES[0].original) != TEXT_COPY_CHAR_TILE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "Text_Main does not call Text_CopyCharTile"
        )
    start = _offset(TEXT_COPY_CHAR_TILE)
    if rom[start : start + len(TEXT_COPY_CHAR_TILE_CODE)] != TEXT_COPY_CHAR_TILE_CODE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "Text_CopyCharTile differs from the USA code"
        )
    (font,) = struct.unpack_from("<I", rom, _offset(FONT_LITERAL_ADDRESS))
    if font != FONT_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"The dialogue font is at {font:#x}, not the USA's"
        )
    region = rom[_offset(PADDING_START) : _offset(PADDING_END)]
    if region.count(FREE_FILL) != len(region):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{PADDING_START:#x}..{PADDING_END:#x} is not empty padding",
        )
    for archive in archives:
        for reference in archive.references:
            (pointer,) = struct.unpack_from("<I", rom, _offset(reference))
            if pointer != archive.address:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_BASELINE_MISMATCH,
                    f"{archive.key}: pointer at {reference:#x} does not lead to "
                    f"{archive.address:#x}",
                )
        parsed = ScriptArchive.parse(rom, archive.address)
        if len(parsed.offsets) != archive.sections:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{archive.key} has {len(parsed.offsets)} sections, not {archive.sections}",
            )


def _verify_source(rom: bytes, section: MmbnArabicSection, archive: MmbnScriptArchive) -> None:
    original = ScriptArchive.parse(rom, archive.address).section(rom, section.index)
    if source_digest(original) != section.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{section.key}: the original section differs from the pinned USA script",
        )
    if command_skeleton(original) != section.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{section.key}: the original has different commands than pinned",
        )


def check_script_layout(
    archives: tuple[MmbnScriptArchive, ...], sections: tuple[MmbnArabicSection, ...]
) -> dict[str, MmbnScriptArchive]:
    """Every translated section names a known archive and section, once."""
    by_key = {archive.key: archive for archive in archives}
    if len(by_key) != len(archives):
        raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, "Two archives share a key")
    seen: set[tuple[str, int]] = set()
    keys: set[str] = set()
    for section in sections:
        archive = by_key.get(section.archive)
        if archive is None or not 0 <= section.index < archive.sections:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE,
                f"{section.key}: no section {section.index} in {section.archive}",
            )
        place = (section.archive, section.index)
        if place in seen or section.key in keys:
            raise ClassicRetroError(
                ErrorCode.DUPLICATE_ENTRY_ID, f"{section.key}: section translated twice"
            )
        seen.add(place)
        keys.add(section.key)
    unused = sorted(set(by_key) - {section.archive for section in sections})
    if unused:
        raise ClassicRetroError(
            ErrorCode.RESOURCE_SET_MISMATCH, "Archives without a translation: " + ", ".join(unused)
        )
    return by_key


def encode_sections(
    encoder: MmbnArabicEncoder, sections: tuple[MmbnArabicSection, ...]
) -> dict[str, MmbnArabicScript]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[str, MmbnArabicScript] = {}
    for section in sections:
        pieces = section.pieces
        validate_command_skeleton(section.source_skeleton, pieces)
        encoded[section.key] = encoder.encode(pieces)
    return encoded


def bank_offset(address: int) -> int:
    """The table's value for a bank at ``address``: glyphs from the font, as a u32."""
    delta = address - FONT_ADDRESS
    if delta % CELL_BYTES:
        raise ClassicRetroError(
            ErrorCode.REFERENCE_ALIGNMENT_ERROR, f"Bank {address:#x} is not font-aligned"
        )
    return (delta // CELL_BYTES) & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class _Layout:
    archives: dict[str, tuple[int, bytes]]
    table: bytes
    banks_address: int
    banks_data: bytes


def _layout(
    rom: bytes,
    archives: tuple[MmbnScriptArchive, ...],
    sections: tuple[MmbnArabicSection, ...],
    encoded: dict[str, MmbnArabicScript],
) -> _Layout:
    by_place = {(section.archive, section.index): section for section in sections}
    bodies: dict[str, bytes] = {}
    # (archive, offset in the archive, bank index or None for the game's font)
    marks: list[tuple[str, int, int | None]] = []
    pages = []
    for archive in archives:
        source = ScriptArchive.parse(rom, archive.address)
        parts = []
        for index in range(archive.sections):
            section = by_place.get((archive.key, index))
            parts.append(
                source.extent(rom, index)
                if section is None
                else encoded[section.key].data + SECTION_TRAILER
            )
        data = build_archive(parts)
        bodies[archive.key] = data
        offsets = struct.unpack_from(f"<{archive.sections}H", data)
        for index, offset in enumerate(offsets):
            section = by_place.get((archive.key, index))
            if section is None:
                marks.append((archive.key, offset, None))
                continue
            for page in encoded[section.key].pages:
                if page.cells:
                    marks.append((archive.key, offset + page.start, len(pages)))
                    pages.append(page)
    # Neighbouring marks for the game's font collapse into one entry, and
    # text before the first translated page needs none.
    entries_marks: list[tuple[str, int, int | None]] = []
    for mark in marks:
        if mark[2] is None and (not entries_marks or entries_marks[-1][2] is None):
            continue
        entries_marks.append(mark)
    table_size = 8 + 8 * len(entries_marks)
    cursor = BANK_TABLE_ADDRESS + table_size
    cursor += -cursor % 16
    placed: dict[str, tuple[int, bytes]] = {}
    for archive in archives:
        placed[archive.key] = (cursor, bodies[archive.key])
        cursor += len(bodies[archive.key])
    end = cursor
    cursor += -(cursor - FONT_ADDRESS) % CELL_BYTES
    banks_address = cursor
    bank_addresses = []
    for page in pages:
        bank_addresses.append(cursor)
        cursor += CELL_BYTES * len(page.cells)
    if cursor > REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Glyph banks exceed the region")
    table = bytearray(struct.pack("<II", end, len(entries_marks)))
    for key, offset, bank in entries_marks:
        value = NO_BANK if bank is None else bank_offset(bank_addresses[bank])
        table += struct.pack("<II", placed[key][0] + offset, value)
    addresses = [placed[key][0] + offset for key, offset, _ in entries_marks]
    if not entries_marks or addresses != sorted(set(addresses)):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Bank table is not sorted")
    banks_data = b"".join(b"".join(page.cells) for page in pages)
    return _Layout(placed, bytes(table), banks_address, banks_data)


def build_mmbn_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    sections: tuple[MmbnArabicSection, ...] | None = None,
    archives: tuple[MmbnScriptArchive, ...] | None = None,
    verify_identity: bool = True,
) -> MmbnArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``sections``, ``archives`` and ``verify_identity`` exist for synthetic
    tests; a real build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    archives = archives or mmbn_script_archives()
    sections = sections or mmbn_arabic_sections()
    by_key = check_script_layout(archives, sections)
    _verify_anchors(rom, archives)
    for section in sections:
        _verify_source(rom, section, by_key[section.archive])
    renderer = MmbnLineRenderer(font_path, game_latin_cells(rom, FONT_ADDRESS))
    encoded = encode_sections(MmbnArabicEncoder(renderer), sections)
    layout = _layout(rom, archives, sections, encoded)

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(BANK_TABLE_ADDRESS, layout.table)
    for archive in archives:
        address, data = layout.archives[archive.key]
        write(address, data)
        for reference in archive.references:
            write(reference, struct.pack("<I", address))
    write(layout.banks_address, layout.banks_data)
    for site in HOOK_SITES:
        write(site.address, site_patch(site))

    output = bytes(target)
    _verify_output(output, rom, archives, sections, encoded, layout)
    patch = create_bps(rom, output)
    pages = [page for section in sections for page in encoded[section.key].pages if page.cells]
    report: dict[str, object] = {
        "game": "Mega Man Battle Network (USA)",
        "base_sha1": hashlib.sha1(rom).hexdigest(),
        "base_sha256": hashlib.sha256(rom).hexdigest(),
        "target_sha256": hashlib.sha256(output).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.data).hexdigest(),
        "patch_bytes": len(patch.data),
        "target_bytes": len(output),
        "archives": {archive.key: f"{layout.archives[archive.key][0]:#x}" for archive in archives},
        "sections": len(sections),
        "pages": len(pages),
        "cells": sum(len(page.cells) for page in pages),
        "section_lines": {
            section.key: [
                list(page.line_widths) for page in encoded[section.key].pages if page.cells
            ]
            for section in sections
        },
        "line_pixels": LINE_PIXELS,
        "font_size": FONT_SIZE,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "bank_table_address": f"{BANK_TABLE_ADDRESS:#x}",
        "bank_table_entries": (len(layout.table) - 8) // 8,
        "banks_address": f"{layout.banks_address:#x}",
        "banks_bytes": len(layout.banks_data),
    }
    return MmbnArabicBuild(rom=output, patch=patch, scripts=encoded, report=report)


def table_lookup(table: bytes, address: int) -> int:
    """What ``bank_offset`` returns for text at ``address`` (the same binary search)."""
    end, count = struct.unpack_from("<II", table)
    entries = [struct.unpack_from("<II", table, 8 + 8 * number) for number in range(count)]
    if address >= end or address < entries[0][0]:
        return NO_BANK
    low, size = 0, count
    while size > 1:
        half = size // 2
        if address >= entries[low + half][0]:
            low += half
            size -= half
        else:
            size = half
    return entries[low][1]


def simulate_page(rom: bytes, table: bytes, address: int) -> list[tuple[int, int, bytes]]:
    """Run a page like ``Text_Main``: ``(line, column, cell)`` of every character.

    Stops after the page's box clear, or at the section's end.
    """
    placed: list[tuple[int, int, bytes]] = []
    index = _offset(address)
    line = column = 0
    while True:
        code = rom[index]
        if code >= FIRST_COMMAND:
            command = decode_command(rom, index)
            index += len(command.data)
            if code == NEWLINE:
                line, column = line + 1, 0
            if code == CLEAR or command.ends_section:
                return placed
            continue
        if code >= SYMBOL_LEAD:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, "Two-byte character in a translated page"
            )
        offset = table_lookup(table, ROM_BASE + index)
        if offset == NO_BANK:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Text at {ROM_BASE + index:#x} has no bank"
            )
        start = _offset((FONT_ADDRESS + (code + offset) * CELL_BYTES) & 0xFFFFFFFF)
        placed.append((line, LAST_COLUMN - column, rom[start : start + CELL_BYTES]))
        column += 1
        index += 1


def _verify_output(
    output: bytes,
    rom: bytes,
    archives: tuple[MmbnScriptArchive, ...],
    sections: tuple[MmbnArabicSection, ...],
    encoded: dict[str, MmbnArabicScript],
    layout: _Layout,
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    allowed = {_offset(site.address) & ~0xFFF for site in HOOK_SITES}
    allowed |= {
        _offset(reference) & ~0xFFF for archive in archives for reference in archive.references
    }
    allowed |= set(range(_offset(PADDING_START) & ~0xFFF, _offset(PADDING_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    for site in HOOK_SITES:
        start = _offset(site.address)
        patched = output[start : start + len(site.original)]
        if bl_target(site.address, patched[:4]) != HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Call at {site.address:#x} misses its hook"
            )
    start = _offset(HOOK_CODE_ADDRESS)
    if output[start : start + len(HOOK_CODE)] != HOOK_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook code was not written")
    table = output[_offset(BANK_TABLE_ADDRESS) : _offset(BANK_TABLE_ADDRESS) + len(layout.table)]
    if table != layout.table:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Bank table was not written")
    by_place = {(section.archive, section.index): section for section in sections}
    for archive in archives:
        address, _ = layout.archives[archive.key]
        for reference in archive.references:
            (pointer,) = struct.unpack_from("<I", output, _offset(reference))
            if pointer != address:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{archive.key}: pointer not repointed"
                )
        original = ScriptArchive.parse(rom, archive.address)
        rebuilt = ScriptArchive.parse(output, address)
        if len(rebuilt.offsets) != archive.sections:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{archive.key}: archive does not read back"
            )
        for index in range(archive.sections):
            section = by_place.get((archive.key, index))
            if section is None:
                # The game's own sections: the same bytes, drawn with the font.
                kept = original.extent(rom, index)
                if rebuilt.raw_section(output, index, len(kept)) != kept:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED,
                        f"{archive.key} section {index} was not copied",
                    )
                if table_lookup(table, rebuilt.section_address(index)) != NO_BANK:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED,
                        f"{archive.key} section {index} would use a bank",
                    )
                continue
            script = encoded[section.key]
            if rebuilt.section(output, index) != script.data:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{section.key} does not read back"
                )
            for number, page in enumerate(script.pages):
                placed = simulate_page(output, table, rebuilt.section_address(index) + page.start)
                expected = [
                    (line, LAST_COLUMN - column, cell)
                    for line, drawn in enumerate(page.lines)
                    for column, cell in enumerate(drawn.cells)
                ]
                if placed != expected:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED,
                        f"{section.key} page {number} does not draw its cells in place",
                    )
                if len(placed) > PAGE_CELLS or any(
                    not (0 <= line < BOX_LINES and FIRST_COLUMN <= column <= LAST_COLUMN)
                    for line, column, _ in placed
                ):
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED,
                        f"{section.key} page {number} leaves the box",
                    )
    # The game's own archives, and text in RAM (item names), keep the font.
    for archive in archives:
        if table_lookup(table, archive.address) != NO_BANK:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The original {archive.key} would use a bank"
            )
    if table_lookup(table, 0x02000000) != NO_BANK:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "RAM text would use a bank")


def check_mmbn_translations(
    font_path: Path | None = None, text_preview_path: Path | None = None
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, draw and measure every page."""
    if font_path is None and text_preview_path is not None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    archives = mmbn_script_archives()
    sections = mmbn_arabic_sections()
    check_script_layout(archives, sections)
    for section in sections:
        validate_command_skeleton(section.source_skeleton, section.pieces)
    report: dict[str, object] = {
        "archives": len(archives),
        "sections": len(sections),
        "pages_drawn": font_path is not None,
    }
    if font_path is None:
        return report
    encoded = encode_sections(MmbnArabicEncoder(MmbnLineRenderer(font_path)), sections)
    pages = [
        (f"{section.key}/{number}", page)
        for section in sections
        for number, page in enumerate(encoded[section.key].pages)
        if page.cells
    ]
    if text_preview_path is not None:
        pages_sheet(pages).save(text_preview_path)
    report["font_size"] = FONT_SIZE
    report["font_baseline"] = BASELINE
    report["pages"] = len(pages)
    report["cells"] = sum(len(page.cells) for _, page in pages)
    report["widest_line"] = max(max(page.line_widths) for _, page in pages)
    report["line_pixels"] = LINE_PIXELS
    report["most_page_cells"] = max(sum(page.line_cells) for _, page in pages)
    report["page_cells"] = PAGE_CELLS
    return report


def encode_mmbn_arabic_section(text: str, font_path: Path) -> dict[str, object]:
    """Encode one section in notation; report its bytes and every page's lines."""
    encoded = MmbnArabicEncoder(MmbnLineRenderer(font_path)).encode(parse_notation(text))
    return {
        "bytes": encoded.data.hex(" "),
        "count": len(encoded.data),
        "pages": [
            {
                "start": page.start,
                "cells": len(page.cells),
                "line_cells": list(page.line_cells),
                "line_widths": list(page.line_widths),
            }
            for page in encoded.pages
            if page.cells
        ],
        "line_pixels": LINE_PIXELS,
        "box_columns": BOX_COLUMNS,
    }


def write_build_outputs(
    build: MmbnArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / "megaman-battle-network-usa-arabic-opening.bps"
    patch_path.write_bytes(build.patch.data)
    preview_path = out_dir / "arabic_pages_preview.png"
    pages_sheet(
        [
            (f"{key}/{number}", page)
            for key, script in build.scripts.items()
            for number, page in enumerate(script.pages)
            if page.cells
        ]
    ).save(preview_path)
    written = {"patch": str(patch_path), "pages_preview": str(preview_path)}
    if rom_name:
        rom_path = out_dir / rom_name
        rom_path.write_bytes(build.rom)
        written["rom"] = str(rom_path)
    return written


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    tools = {name: shutil.which(f"arm-none-eabi-{name}") for name in ("as", "ld", "objcopy", "nm")}
    missing = sorted(name for name, path in tools.items() if path is None)
    if missing:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "Missing GNU ARM binutils: " + ", ".join(f"arm-none-eabi-{name}" for name in missing),
        )
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        steps = (
            [tools["as"], "-mcpu=arm7tdmi", "-o", folder / "hooks.o", source],
            [tools["ld"], "-e", "0", "-Ttext", f"{HOOK_CODE_ADDRESS:#x}"]
            + ["-o", folder / "hooks.elf", folder / "hooks.o"],
            [tools["objcopy"], "-O", "binary", folder / "hooks.elf", folder / "hooks.bin"],
            [tools["nm"], folder / "hooks.elf"],
        )
        try:
            listing = [
                subprocess.run(step, check=True, capture_output=True, text=True).stdout
                for step in steps
            ][-1]
        except subprocess.CalledProcessError as exc:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Assembling the MMBN hooks failed: {exc.stderr.strip()}",
            ) from exc
        code = (folder / "hooks.bin").read_bytes()
    symbols = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in HOOK_SYMBOLS:
            symbols[parts[2]] = int(parts[0], 16) - HOOK_CODE_ADDRESS
    return code, symbols


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    code, symbols = assemble_hooks(source)
    if code != HOOK_CODE or symbols != HOOK_SYMBOLS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED,
            "Assembled MMBN hooks differ from the stored HOOK_CODE / HOOK_SYMBOLS",
        )
    return {"hook_bytes": len(code), "symbols": dict(sorted(symbols.items())), "match": True}
