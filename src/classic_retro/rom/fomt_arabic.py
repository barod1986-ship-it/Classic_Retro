"""Arabic ROM overlay for *Harvest Moon: Friends of Mineral Town* (USA).

No decompilation of this game builds the image, so the overlay patches the
user's image (``A4NE``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   every translated string's original is checked against its pinned hash and
   command skeleton;
2. the Thumb hooks (``fomt_arabic_hooks.s``), the bank of pre-drawn cells
   (``engines.fomt_arabic``) and the translated texts go into the 0xFF padding
   at the end of the image; it stays 8 MiB;
3. the game's glyph routine (``0x080D0D28``) starts with a jump to
   ``hook_glyph``, which copies the overlay's cells; the text box's
   draw-character method calls ``hook_mirror`` through a veneer written in
   the code it replaces (``0x0804EFD0``), so those cells fill a line from the
   right; the expanders of the event scripts and of the story scenes point to
   ``hook_expand_script`` and ``hook_expand_story``, which give the player's
   name reversed for ``FD 21``;
4. the opening's event script (867) is rebuilt with the Arabic strings in the
   padding and its table entry repointed; the literals of the flashback
   scene point to the Arabic strings and speaker names.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_veneer_patch, literal_jump
from classic_retro.engines.fomt import (
    ROM_BASE,
    FomtScript,
    PlaceholderStyle,
    command_skeleton,
    parse_notation,
    read_string,
    split_text,
    text_notation,
)
from classic_retro.engines.fomt_arabic import (
    BASELINE,
    CELL_LEAD,
    CELL_LEADS,
    FONT_SIZE,
    ISLAND_LEAD,
    NAME_CELLS,
    NAME_CODE,
    TAG_LEAD,
    TRAIL_FIRST,
    TRAIL_LAST,
    CellBank,
    FomtArabicEncoder,
    FomtArabicText,
    FomtCellRenderer,
    TagBank,
    code_cell,
    page_preview,
    previews_sheet,
    render_tag,
    tag_preview,
    text_pages,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.fomt_arabic_script import (
    OPENING_SCRIPT,
    OPENING_SCRIPT_ADDRESS,
    OPENING_SCRIPT_SHA256,
    OPENING_SCRIPT_STRINGS,
    SCRIPT_COUNT,
    SCRIPT_TABLE,
    FomtArabicName,
    FomtArabicString,
    fomt_arabic_names,
    fomt_arabic_strings,
)

USA_SHA256 = "ca6cebe7211b6f2693af210709f76222204bf9f7621dec08b30ca268117460dd"
USA_SIZE = 0x800000

# The glyph routine: `push {r4-r6, lr}; adds r4, r0, #0; adds r2, r1, #0; movs r6, #0`.
GLYPH_SITE = 0x080D0D28
GLYPH_SITE_ORIGINAL = bytes.fromhex("70b5041c0a1c0026")
# The text box's draw-character method (0x0804EFAC): the sprite and column of x.
DRAW_SITE = 0x0804EFD0
DRAW_SITE_ORIGINAL = bytes.fromhex("4246900800010f1803200240032a1ad8")
DRAW_RESUME = 0x0804EFE0
# Method slot +12 (expand) of the two character expanders' vtables.
SCRIPT_EXPANDER_SLOT = 0x080E76F4
SCRIPT_EXPANDER = 0x0803B4DD
STORY_EXPANDER_SLOT = 0x080E79F4
STORY_EXPANDER = 0x080E19A5

PATCH_NAME = "harvest-moon-fomt-usa-arabic-opening.bps"
# 0xFF padding from 0x0875C244 to the end of the image.
PADDING_START = 0x0875C244
PADDING_END = 0x08800000
HOOK_CODE_ADDRESS = 0x08760000
BANK_ADDRESS = 0x08760400
CELLS_ADDRESS = 0x08760410
HOOK_SOURCE = Path(__file__).with_name("fomt_arabic_hooks.s")
# The game's script loader reads one chunk header past the end of a file.
SCRIPT_TAIL = bytes(8)

# arm-none-eabi-as -mcpu=arm7tdmi fomt_arabic_hooks.s; ld -Ttext 0x08760000; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "0a0af02a3ad3fc2a38d80b061b0efb2a33d0403b32d3bc2b30d8fc2a1bd0f03a"
    "30b4bd246243d218364b5c68a24210d200280bd01b6892019b1836cb36c036cb"
    "36c0203036cb36c036cb36c030bc0120704730bc12e02b4a10b4d468a34210bc"
    "0cd2002807d09268db01d2188023043bd158c150fbd102207047190070b5041c"
    "0a1c00262048004742464846000af02803d3fb2801d81b20821a900800010f18"
    "032002407047130afd2b184b29d102231b02d218154b04e0130afd2b144b20d1"
    "ff2201b500f01df80178002916d084b0011d00228b5c002b04d0684683540132"
    "0f2af7d3fb20013a05d36b469b5c08704b700231f7e700230b7004b001bc02bc"
    "0847184700047608310d0d08ddb40308a5190e08"
)
HOOK_SYMBOLS = {
    "hook_glyph": 0x00,
    "hook_mirror": 0x88,
    "hook_expand_script": 0xA6,
    "hook_expand_story": 0xB8,
}
IMAGE = ImageSpec("Harvest Moon: Friends of Mineral Town (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("FoMT hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)


@dataclass(frozen=True, slots=True)
class FomtArabicBuild:
    rom: bytes
    patch: BpsPatch
    texts: dict[str, FomtArabicText]
    tags: dict[str, bytes]
    bank: CellBank
    tag_bank: TagBank
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


_hook = HOOKS.thumb_entry


def glyph_site_patch() -> bytes:
    """``ldr r2, [pc, #0]; bx r2; .word hook_glyph``: r2 is free at the entry."""
    code = literal_jump(GLYPH_SITE, 2, _hook("hook_glyph"))
    if len(code) != len(GLYPH_SITE_ORIGINAL):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Glyph site patch size")
    return code


def draw_site_patch() -> bytes:
    """``bl veneer; b resume; nop``, then the veneer: ``ldr r0, =hook_mirror; bx r0``.

    The BL leaves the return address in lr; r0 is free there (the replaced
    code sets it too).
    """
    code = bl_veneer_patch(DRAW_SITE, DRAW_RESUME, _hook("hook_mirror"))
    if len(code) != len(DRAW_SITE_ORIGINAL):
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Draw site patch size")
    return code


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> None:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB")
    for site, original, what in (
        (GLYPH_SITE, GLYPH_SITE_ORIGINAL, "glyph routine"),
        (DRAW_SITE, DRAW_SITE_ORIGINAL, "text box draw-character method"),
    ):
        start = _offset(site)
        if rom[start : start + len(original)] != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {site:#x} ({what})"
            )
    for slot, method in (
        (SCRIPT_EXPANDER_SLOT, SCRIPT_EXPANDER),
        (STORY_EXPANDER_SLOT, STORY_EXPANDER),
    ):
        if _word(rom, slot) != method:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"The expander slot {slot:#x} differs"
            )
    if not IMAGE.filled(rom, PADDING_START, PADDING_END, 0xFF):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{PADDING_START:#x}..{PADDING_END:#x} is not empty padding",
        )
    (bank,) = struct.unpack_from("<I", HOOK_CODE, len(HOOK_CODE) - 16)
    if bank != BANK_ADDRESS:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The hooks' bank address differs from BANK_ADDRESS"
        )


def _script_entry() -> int:
    return SCRIPT_TABLE + 4 * OPENING_SCRIPT


def _verify_script(rom: bytes, strings: tuple[FomtArabicString, ...]) -> FomtScript:
    if (
        not 0 <= OPENING_SCRIPT < SCRIPT_COUNT
        or _word(rom, _script_entry()) != OPENING_SCRIPT_ADDRESS
    ):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Script {OPENING_SCRIPT} does not lead to {OPENING_SCRIPT_ADDRESS:#x}",
        )
    try:
        script = FomtScript.read(rom, _offset(OPENING_SCRIPT_ADDRESS))
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"No event script at {OPENING_SCRIPT_ADDRESS:#x}",
        ) from exc
    if hashlib.sha256(script.to_bytes()).hexdigest() != OPENING_SCRIPT_SHA256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Script {OPENING_SCRIPT} differs from the pinned USA script",
        )
    originals = script.strings
    if len(originals) != OPENING_SCRIPT_STRINGS:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Script {OPENING_SCRIPT} has {len(originals)} strings",
        )
    for string in strings:
        if string.index is None:
            continue
        if not 0 <= string.index < len(originals):
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"{string.key}: no string {string.index}"
            )
        _verify_original(string, originals[string.index])
    return script


def _verify_original(string: FomtArabicString, original: bytes) -> None:
    if hashlib.sha256(original).hexdigest() != string.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: the original differs from the pinned USA text",
        )
    if command_skeleton(split_text(original, string.style)) != string.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{string.key}: the original has different commands than pinned",
        )


def _verify_story(
    rom: bytes,
    strings: tuple[FomtArabicString, ...],
    names: tuple[FomtArabicName, ...],
) -> None:
    story = [string for string in strings if string.index is None]
    targets: list[tuple[str, int, tuple[int, ...]]] = [
        (string.key, string.address or 0, string.literals) for string in story
    ]
    targets += [(name.key, name.address, name.literals) for name in names]
    references = IMAGE.references(rom, {address for _, address, _ in targets})
    for key, address, literals in targets:
        if sorted(references[address]) != sorted(literals):
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{key}: {address:#x} is referenced from "
                + ", ".join(f"{literal:#x}" for literal in references[address])
                + " instead of the pinned literals",
            )
    for string in story:
        _verify_original(string, read_string(rom, _offset(string.address or 0)))
    for name in names:
        original = read_string(rom, _offset(name.address))
        if hashlib.sha256(original).hexdigest() != name.source_sha256:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{name.key}: the speaker name differs from the pinned USA text",
            )


def encode_strings(
    encoder: FomtArabicEncoder, strings: tuple[FomtArabicString, ...]
) -> dict[str, FomtArabicText]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[str, FomtArabicText] = {}
    for string in strings:
        if string.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {string.key} twice")
        pieces = string.pieces
        validate_command_skeleton(string.source_skeleton, pieces)
        encoded[string.key] = encoder.encode(pieces)
    return encoded


def encode_names(
    renderer: FomtCellRenderer, bank: TagBank, names: tuple[FomtArabicName, ...]
) -> dict[str, bytes]:
    return {name.key: render_tag(renderer, name.arabic, bank) for name in names}


def build_fomt_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    strings: tuple[FomtArabicString, ...] | None = None,
    names: tuple[FomtArabicName, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> FomtArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``strings``, ``names`` and ``verify_identity`` exist for synthetic tests; a
    real build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    _verify_anchors(rom)
    strings = strings or fomt_arabic_strings(translations)
    names = names or fomt_arabic_names(translations)
    script = _verify_script(rom, strings)
    _verify_story(rom, strings, names)

    renderer = FomtCellRenderer(font_path)
    encoder = FomtArabicEncoder(renderer)
    texts = encode_strings(encoder, strings)
    tag_bank = TagBank()
    tags = encode_names(renderer, tag_bank, names)

    cells = b"".join(encoder.bank.cells)
    tag_cells_address = CELLS_ADDRESS + len(cells)
    tag_cells = b"".join(tag_bank.cells)
    cursor = tag_cells_address + len(tag_cells)
    blob = bytearray()
    addresses: dict[str, int] = {}
    for string in strings:
        if string.index is None:
            addresses[string.key] = cursor + len(blob)
            blob += texts[string.key].data + b"\0"
    for name in names:
        addresses[name.key] = cursor + len(blob)
        blob += tags[name.key] + b"\0"
    while (cursor + len(blob)) % 4:
        blob.append(0)
    script_address = cursor + len(blob)
    new_strings = list(script.strings)
    for string in strings:
        if string.index is not None:
            new_strings[string.index] = texts[string.key].data
    new_script = script.with_strings(new_strings).to_bytes()
    blob += new_script + SCRIPT_TAIL
    end = cursor + len(blob)
    if end > PADDING_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The overlay exceeds the padding")
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > BANK_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(
        BANK_ADDRESS,
        struct.pack(
            "<4I", CELLS_ADDRESS, len(encoder.bank.cells), tag_cells_address, len(tag_bank.cells)
        ),
    )
    write(CELLS_ADDRESS, cells)
    write(tag_cells_address, tag_cells)
    write(cursor, bytes(blob))
    write(GLYPH_SITE, glyph_site_patch())
    write(DRAW_SITE, draw_site_patch())
    write(SCRIPT_EXPANDER_SLOT, struct.pack("<I", _hook("hook_expand_script")))
    write(STORY_EXPANDER_SLOT, struct.pack("<I", _hook("hook_expand_story")))
    write(_script_entry(), struct.pack("<I", script_address))
    for string in strings:
        for literal in string.literals:
            write(literal, struct.pack("<I", addresses[string.key]))
    for name in names:
        for literal in name.literals:
            write(literal, struct.pack("<I", addresses[name.key]))

    output = bytes(target)
    _verify_output(output, rom, strings, names, texts, tags, addresses, script_address, end)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "strings": len(strings),
        "speaker_names": len(names),
        "line_cells": {key: [line.cells for line in text.lines] for key, text in texts.items()},
        "cells": len(encoder.bank.cells),
        "tag_cells": len(tag_bank.cells),
        "cell_codes": f"{CELL_LEAD:02X} {TRAIL_FIRST:02X}..{CELL_LEAD + CELL_LEADS - 1:02X} "
        f"{TRAIL_LAST:02X}",
        "name_cells": NAME_CELLS,
        "font_size": FONT_SIZE,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "bank_address": f"{BANK_ADDRESS:#x}",
        "script_address": f"{script_address:#x}",
        "overlay_end": f"{end:#x}",
    }
    return FomtArabicBuild(
        rom=output,
        patch=patch,
        texts=texts,
        tags=tags,
        bank=encoder.bank,
        tag_bank=tag_bank,
        report=report,
    )


def _check_codes(data: bytes, cell_count: int, tag_count: int, key: str) -> None:
    """Every overlay code in ``data`` names a cell of the bank."""
    index = 0
    while index < len(data):
        byte = data[index]
        if CELL_LEAD <= byte < CELL_LEAD + CELL_LEADS:
            if index + 1 >= len(data) or code_cell(data[index : index + 2]) >= cell_count:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{key}: a cell code outside the bank"
                )
            index += 2
        elif byte == TAG_LEAD:
            if index + 1 >= len(data) or not 0 <= data[index + 1] - TRAIL_FIRST < tag_count:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{key}: a tag code outside the bank"
                )
            index += 2
        elif data[index : index + 2] == NAME_CODE:
            index += 2
        elif byte >= ISLAND_LEAD or byte == 0:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{key}: unexpected byte {byte:#04x}"
            )
        else:
            index += 1


def _verify_output(
    output: bytes,
    rom: bytes,
    strings: tuple[FomtArabicString, ...],
    names: tuple[FomtArabicName, ...],
    texts: dict[str, FomtArabicText],
    tags: dict[str, bytes],
    addresses: dict[str, int],
    script_address: int,
    end: int,
) -> None:
    sites = [
        (GLYPH_SITE, len(GLYPH_SITE_ORIGINAL)),
        (DRAW_SITE, len(DRAW_SITE_ORIGINAL)),
        (SCRIPT_EXPANDER_SLOT, 4),
        (STORY_EXPANDER_SLOT, 4),
        (_script_entry(), 4),
        (HOOK_CODE_ADDRESS, end - HOOK_CODE_ADDRESS),
    ]
    sites += [(literal, 4) for string in strings for literal in string.literals]
    sites += [(literal, 4) for name in names for literal in name.literals]
    allowed = bytearray(len(rom))
    for address, length in sites:
        allowed[_offset(address) : _offset(address) + length] = b"\1" * length
    for start in range(0, len(rom), 0x1000):
        if output[start : start + 0x1000] != rom[start : start + 0x1000]:
            for index in range(start, start + 0x1000):
                if output[index] != rom[index] and not allowed[index]:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED,
                        f"The overlay changed {ROM_BASE + index:#x}, outside its sites",
                    )
    start = _offset(HOOK_CODE_ADDRESS)
    if output[start : start + len(HOOK_CODE)] != HOOK_CODE:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook code was not written")
    cells_address, cell_count, tag_address, tag_count = struct.unpack_from(
        "<4I", output, _offset(BANK_ADDRESS)
    )
    if cells_address != CELLS_ADDRESS or tag_address != CELLS_ADDRESS + 64 * cell_count:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The bank header is wrong")
    for string in strings:
        data = texts[string.key].data
        _check_codes(data, cell_count, tag_count, string.key)
        if string.index is None:
            for literal in string.literals:
                if _word(output, literal) != addresses[string.key]:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key}: literal not repointed"
                    )
            if read_string(output, _offset(addresses[string.key])) != data:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{string.key} does not read back"
                )
    for name in names:
        _check_codes(tags[name.key], cell_count, tag_count, name.key)
        for literal in name.literals:
            if _word(output, literal) != addresses[name.key]:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED, f"{name.key}: literal not repointed"
                )
        if read_string(output, _offset(addresses[name.key])) != tags[name.key]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{name.key} does not read back"
            )
    if _word(output, _script_entry()) != script_address or script_address % 4:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The script was not repointed")
    rebuilt = FomtScript.read(output, _offset(script_address))
    original = FomtScript.read(rom, _offset(OPENING_SCRIPT_ADDRESS))
    if [chunk for chunk in rebuilt.chunks if chunk[0] != b"STR "] != [
        chunk for chunk in original.chunks if chunk[0] != b"STR "
    ]:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The rebuilt script's code differs"
        )
    expected = list(original.strings)
    for string in strings:
        if string.index is not None:
            expected[string.index] = texts[string.key].data
    if list(rebuilt.strings) != expected:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The rebuilt script's strings do not read back"
        )
    tail = _offset(script_address) + len(rebuilt.to_bytes())
    if output[tail : tail + len(SCRIPT_TAIL)] != SCRIPT_TAIL:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The script's tail is missing")


def translation_previews(
    texts: dict[str, FomtArabicText],
    tags: dict[str, bytes],
    tag_bank: TagBank,
) -> list[tuple[str, Image.Image]]:
    """Every box of every translation, then every name tag, as the game draws them."""
    previews: list[tuple[str, Image.Image]] = []
    for key, text in texts.items():
        for number, box in enumerate(text_pages(text)):
            previews.append((f"{key} {number + 1}", page_preview(box)))
    for key, codes in tags.items():
        previews.append((f"tag {key}", tag_preview(codes, tag_bank)))
    return previews


def check_fomt_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, draw and lay out every one."""
    strings = fomt_arabic_strings(translations)
    names = fomt_arabic_names(translations)
    for string in strings:
        validate_command_skeleton(string.source_skeleton, string.pieces)
    report: dict[str, object] = {
        "strings": len(strings),
        "speaker_names": len(names),
        "laid_out": font_path is not None,
    }
    if font_path is None:
        if preview_path is not None:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
        return report
    renderer = FomtCellRenderer(font_path)
    encoder = FomtArabicEncoder(renderer)
    texts = encode_strings(encoder, strings)
    tag_bank = TagBank()
    tags = encode_names(renderer, tag_bank, names)
    if preview_path is not None:
        previews_sheet(translation_previews(texts, tags, tag_bank)).save(preview_path)
    report["cells"] = len(encoder.bank.cells)
    report["tag_cells"] = len(tag_bank.cells)
    report["widest_line_cells"] = max(line.cells for text in texts.values() for line in text.lines)
    report["encoded_bytes"] = sum(len(text.data) for text in texts.values())
    return report


def encode_fomt_arabic_text(
    text: str, font_path: Path, *, story: bool = False
) -> dict[str, object]:
    """Encode one translation in notation; its bytes and the cells of its lines."""
    style = PlaceholderStyle.STORY if story else PlaceholderStyle.SCRIPT
    encoder = FomtArabicEncoder(FomtCellRenderer(font_path))
    result = encoder.encode(parse_notation(text, style))
    return {
        "bytes": result.data.hex(" "),
        "count": len(result.data),
        "line_cells": [line.cells for line in result.lines],
        "cells": len(encoder.bank.cells),
    }


def write_build_outputs(
    build: FomtArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    preview_path = out_dir / "arabic_text_preview.png"
    previews_sheet(translation_previews(build.texts, build.tags, build.tag_bank)).save(preview_path)
    written = {"patch": str(patch_path), "text_preview": str(preview_path)}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    strings: tuple[FomtArabicString, ...] | None = None,
    names: tuple[FomtArabicName, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    strings = strings or fomt_arabic_strings(translations)
    names = names or fomt_arabic_names(translations)
    script = _verify_script(rom, strings)
    _verify_story(rom, strings, names)
    originals: dict[str, str] = {}
    for string in strings:
        if string.index is not None:
            original = script.strings[string.index]
        else:
            original = read_string(rom, _offset(string.address or 0))
        originals[string.key] = text_notation(split_text(original, string.style))
    for name in names:
        original = read_string(rom, _offset(name.address))
        originals[f"name.{name.key}"] = text_notation(split_text(original, PlaceholderStyle.STORY))
    return originals


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
