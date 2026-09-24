"""Arabic ROM overlay for Golden Sun (USA, Europe).

The disassembly at https://github.com/gsret/goldensun rebuilds this exact
image but cannot relocate data yet, so the overlay patches the user's image
(``AGSE``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified, and
   the original strings are decoded to check the pinned script;
2. the image is expanded from 8 to 16 MiB (0xFF fill); the right-to-left
   glyph table goes to ``0x08800000`` and the translated strings, compressed
   with their own trees (Arabic codes are ``0x100 + slot``), to a string
   store at ``0x08810000``. The game's text bank stays untouched: the dialogue
   decoder is pointed at the store when it opens a translated string;
3. the Thumb hooks (``golden_sun_arabic_hooks.s``) go into the zero padding
   at ``0x08074000``, close enough to the text engine for plain ``BL`` calls;
   five calls become ``BL`` to a hook, two width lookups jump to a hook, and
   one branch stops the decoder from replacing codes above ``0xFF``.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import bl_instruction, literal_jump
from classic_retro.engines.golden_sun import (
    KEY_END,
    STORE_TREE_BLOCKS,
    BuiltStringStore,
    GoldenSunFont,
    GoldenSunTextBank,
    build_string_store,
    command_skeleton,
    read_string_store,
)
from classic_retro.engines.golden_sun_arabic import (
    ARABIC_CODE_BASE,
    BASELINE,
    CELL_HEIGHT,
    LINES_PER_PAGE,
    MAX_LINE_WIDTH,
    NAME_WIDTH_BUDGET,
    RTL_MARKER,
    RTL_TAG,
    USA_LATIN_ADVANCES,
    GoldenSunArabicEncoder,
    GoldenSunRtlFont,
    build_golden_sun_arabic_glyph_map,
    build_golden_sun_rtl_font,
    font_preview,
    golden_sun_command,
    validate_command_skeleton,
)
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.golden_sun_arabic_script import (
    GoldenSunArabicMessage,
    golden_sun_arabic_messages,
)
from classic_retro.text.tokens import TextToken, TokenStream

USA_SHA256 = "c14f1151897e8d73f25ffdd67e21eebb6dc57973ff2458872ee89fa9060aaca1"
USA_SIZE = 0x800000
ROM_BASE = 0x08000000
EXPANDED_SIZE = 0x1000000
EXPANSION_FILL = 0xFF
STRING_COUNT = 10722

LATIN_FONT_ADDRESS = 0x08032224
TREE_TABLE_ADDRESS = 0x0803842C
STRING_TABLE_ADDRESS = 0x080736B8
TREE_TABLE_REFERENCES = (0x0801556C, 0x08019D08)
STRING_TABLE_REFERENCES = (0x080155CC,)
# The ARM decoder is copied to RAM for every message; its tree table literal
# (the first reference above) is retargeted in that copy for translated strings.
ARM_DECODER_ADDRESS = 0x08015430
DECODER_TREES = TREE_TABLE_REFERENCES[0] - ARM_DECODER_ADDRESS

HOOK_CODE_ADDRESS = 0x08074000
HOOK_REGION_END = 0x08077000
RTL_FONT_ADDRESS = 0x08800000
ARABIC_STORE_ADDRESS = 0x08810000
HOOK_SOURCE = Path(__file__).with_name("golden_sun_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi golden_sun_arabic_hooks.s; ld -Ttext 0x08074000; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "60b505000e0000f016f89348934b0188b14203d099420bd00830f8e741680022"
    "2a6069600122aa608d494a468d4bd15060bc01bc00478c4a1047089d6d004544"
    "2d880b2d17d1c1b4884a841b1440640810d0411e114033005d00454448004044"
    "2e8807882f8006800133134001391140013cf1d1c1bc061c7d480047f1b50e99"
    "4900414409880b291ad10e99774b794d01311940b14213d04a0042441488202c"
    "02d32c431480f3e7082cf1d30a2c03d90f2c01d01d2cebd101311940b142e7d1"
    "01bc00f003f8f0bc01bc00476a4908473068684b1f4201d1c28a7047634b1f40"
    "202f1fd06549ca5d624b1c420fd05f4b1c40202c0bd00b5d9b180f2b07d81a00"
    "24042743738a013358490b4073820389db000c3b5b1b9b1a00d500231d000123"
    "db071f43564b1847002801db554a1047f0b544464d4656465f46f0b48846c405"
    "e40da346000c494b184084460022202304c1013bfcd14c4b1b684c4a9a5c002a"
    "04d0082291460022924604e0484a9a5a914601229246414d60460021002805d0"
    "295c02b4002100f012f802bc584602b400f00df802bc394d5846285c4018f0bc"
    "a046a946b246bb46f0bc02bc0847394a80011218002420ca0e00002d29d00327"
    "2f40ad08002f22d0102e22d2012f01d14f4602e05746002f19d0e0084000f308"
    "c01840016307db0ec01873079b0fc0184044037802b4710803d2f0210b403b43"
    "03e00f210b403f013b4302bc03700136d3e70134102cced37047c046154b1a42"
    "04d1203a52011c4b9a5a03e00f4b1a40124b9a5c194b18470e4b1a4204d1203a"
    "5201154b9a5a03e0084b1a400b4b9a5c134b08b4134b00bd10008108ffff0000"
    "000081083c010000ad9b0108ff0100001586010800020000d92d000800008008"
    "3f6e0108b17801088c1e0003a40e0000ae0e00000002800824220308b1880108"
    "cd8a0108ac0e000000008008"
)
HOOK_SYMBOLS = {
    "hook_init": 0x000,
    "hook_expand": 0x03A,
    "hook_tag": 0x07C,
    "hook_pair": 0x0D0,
    "hook_render": 0x128,
    "hook_measure": 0x21C,
    "hook_measure_alt": 0x238,
    "rtl_font_pointer": 0x2A8,
}
IMAGE = ImageSpec("Golden Sun (USA, Europe)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Golden Sun hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "golden-sun-usa-europe-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class HookSite:
    """Original code replaced by a ``BL`` to a hook, or by ``ldr r3, [pc]; bx r3; .word``."""

    address: int
    original: bytes
    kind: str
    symbol: str
    purpose: str

    def replacement(self, target: int) -> bytes:
        if self.kind == "bl":
            offset = target - (self.address + 4)
            if not -0x400000 <= offset < 0x400000 or offset % 2:
                raise ClassicRetroError(
                    ErrorCode.WRITE_OUT_OF_BOUNDS, f"Hook at {self.address:#x} is out of BL range"
                )
            data = bl_instruction(self.address, target)
        elif self.kind == "jump":
            if self.address % 4:
                raise ClassicRetroError(
                    ErrorCode.REFERENCE_ALIGNMENT_ERROR, f"Jump at {self.address:#x} is unaligned"
                )
            data = literal_jump(self.address, 3, target)
        else:
            raise ValueError(f"unknown hook kind {self.kind}")
        if len(data) != len(self.original):
            raise ClassicRetroError(
                ErrorCode.WRITE_OUT_OF_BOUNDS, f"Hook at {self.address:#x} changes the code size"
            )
        return data


HOOK_SITES = (
    HookSite(0x080180BE, bytes.fromhex("01f075fd"), "bl", "hook_init", "open translated strings"),
    HookSite(0x0801851A, bytes.fromhex("061c7ae0"), "bl", "hook_expand", "reverse runtime names"),
    HookSite(0x0801864A, bytes.fromhex("eaf7c5fb"), "bl", "hook_tag", "tag right-to-left glyphs"),
    HookSite(0x08016DFE, bytes.fromhex("3068c28a"), "bl", "hook_pair", "pair and mirror glyphs"),
    HookSite(0x08018DCA, bytes.fromhex("fef771fd"), "bl", "hook_render", "draw glyph sprites"),
    HookSite(0x080188A8, bytes.fromhex("544b203a52019a5a"), "jump", "hook_measure", "page width"),
    HookSite(
        0x08018AC4, bytes.fromhex("203a52019a5a654b"), "jump", "hook_measure_alt", "page width"
    ),
)


@dataclass(frozen=True, slots=True)
class CodePatch:
    address: int
    original: bytes
    replacement: bytes
    purpose: str


# "bls" -> "b": the decoder no longer replaces codes above 0xFF with '@'.
CODE_PATCHES = (
    CodePatch(0x080180D4, bytes.fromhex("00d9"), bytes.fromhex("00e0"), "keep 12-bit codes"),
)


@dataclass(frozen=True, slots=True)
class GoldenSunArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: GoldenSunRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset


def source_digest(codes: tuple[int, ...]) -> str:
    """SHA-256 of an original string's codes (all below 0x100) as bytes."""
    return hashlib.sha256(bytes(codes)).hexdigest()


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> tuple[GoldenSunFont, GoldenSunTextBank]:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB; it may be patched already"
        )
    for site in HOOK_SITES:
        start = _offset(site.address)
        if rom[start : start + len(site.original)] != site.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {site.address:#x} ({site.purpose})",
            )
    for patch in CODE_PATCHES:
        start = _offset(patch.address)
        if rom[start : start + len(patch.original)] != patch.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {patch.address:#x} ({patch.purpose})",
            )
    for references, table in (
        (TREE_TABLE_REFERENCES, TREE_TABLE_ADDRESS),
        (STRING_TABLE_REFERENCES, STRING_TABLE_ADDRESS),
    ):
        for reference in references:
            (value,) = struct.unpack_from("<I", rom, _offset(reference))
            if value != table:
                raise ClassicRetroError(
                    ErrorCode.SOURCE_BASELINE_MISMATCH,
                    f"Reference at {reference:#x} does not point to {table:#x}",
                )
    if any(rom[_offset(HOOK_CODE_ADDRESS) : _offset(HOOK_REGION_END)]):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, "Hook region 0x08074000 is not empty padding"
        )
    latin = GoldenSunFont.parse(rom, _offset(LATIN_FONT_ADDRESS))
    for character, advance in USA_LATIN_ADVANCES.items():
        if latin.glyph(ord(character)).advance != advance:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Latin glyph for {character!r} differs from the pinned USA/Europe font",
            )
    bank = GoldenSunTextBank.parse(
        rom, _offset(TREE_TABLE_ADDRESS), _offset(STRING_TABLE_ADDRESS), STRING_COUNT
    )
    return latin, bank


def _verify_source_message(bank: GoldenSunTextBank, message: GoldenSunArabicMessage) -> None:
    original = bank.strings[message.index]
    if any(code > 0xFF for code in original) or source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"String {message.index} differs from the pinned USA/Europe script",
        )
    if command_skeleton(original) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"String {message.index} has different commands than pinned",
        )


def encode_translations(
    encoder: GoldenSunArabicEncoder,
    messages: tuple[GoldenSunArabicMessage, ...] | None = None,
) -> dict[int, tuple[tuple[int, ...], list[dict[str, object]]]]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[int, tuple[tuple[int, ...], list[dict[str, object]]]] = {}
    for message in messages or golden_sun_arabic_messages():
        if message.index in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"String {message.index} twice")
        validate_command_skeleton(message.source_skeleton, message.stream)
        result = encoder.encode_message(message.stream)
        lines = [
            {"page": line.page, "width": line.width, "names": line.names} for line in result.lines
        ]
        encoded[message.index] = (result.codes, lines)
    return encoded


def build_golden_sun_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[GoldenSunArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> GoldenSunArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA/Europe image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    latin, bank = _verify_anchors(rom)
    messages = messages or golden_sun_arabic_messages()
    for message in messages:
        _verify_source_message(bank, message)
    font = build_golden_sun_rtl_font(font_path, latin)
    font_data = font.data
    if RTL_FONT_ADDRESS + len(font_data) > ARABIC_STORE_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Glyph table exceeds its region")
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > HOOK_REGION_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")

    encoded = encode_translations(GoldenSunArabicEncoder(advances=font.advances()), messages)
    replacements = {index: codes for index, (codes, _) in encoded.items()}
    store = build_string_store(replacements, ARABIC_STORE_ADDRESS)
    if ARABIC_STORE_ADDRESS + len(store.data) > ROM_BASE + EXPANDED_SIZE:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "String store exceeds the image")

    target = bytearray(rom) + bytes([EXPANSION_FILL]) * (EXPANDED_SIZE - len(rom))

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(RTL_FONT_ADDRESS, font_data)
    write(ARABIC_STORE_ADDRESS, store.data)
    for site in HOOK_SITES:
        write(site.address, site.replacement(HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol]))
    for patch in CODE_PATCHES:
        write(patch.address, patch.replacement)

    output = bytes(target)
    _verify_output(output, rom, bank, replacements, font_data, store)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "strings": sorted(replacements),
        "string_lines": {str(index): encoded[index][1] for index in sorted(encoded)},
        "arabic_glyphs": len(build_golden_sun_arabic_glyph_map().characters),
        "rtl_glyphs": len(font.glyphs),
        "arabic_code_base": f"{ARABIC_CODE_BASE:#x}",
        "rtl_marker": f"{RTL_MARKER:#x}",
        "rtl_tag": f"{RTL_TAG:#x}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "glyph_height": CELL_HEIGHT,
        "max_line_width": MAX_LINE_WIDTH,
        "lines_per_page": LINES_PER_PAGE,
        "name_width_budget": NAME_WIDTH_BUDGET,
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "rtl_font_address": f"{RTL_FONT_ADDRESS:#x}",
        "arabic_store_address": f"{ARABIC_STORE_ADDRESS:#x}",
        "arabic_store_bytes": len(store.data),
        "tree_blocks": STORE_TREE_BLOCKS,
    }
    return GoldenSunArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    rom: bytes,
    bank: GoldenSunTextBank,
    replacements: dict[int, tuple[int, ...]],
    font_data: bytes,
    store: BuiltStringStore,
) -> None:
    changed = [
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    ]
    allowed = {_offset(site.address) & ~0xFFF for site in HOOK_SITES}
    allowed |= {_offset(patch.address) & ~0xFFF for patch in CODE_PATCHES}
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS), _offset(HOOK_REGION_END), 0x1000))
    if not set(changed) <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    untouched = GoldenSunTextBank.parse(
        output, _offset(TREE_TABLE_ADDRESS), _offset(STRING_TABLE_ADDRESS), STRING_COUNT
    )
    if untouched != bank:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "The game's text bank changed")
    stored = read_string_store(output, ARABIC_STORE_ADDRESS)
    if stored != replacements:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The Arabic string store does not decode back"
        )
    if any(codes[0] != RTL_MARKER for codes in stored.values()):
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "A translated string lacks the RTL marker"
        )
    start = _offset(RTL_FONT_ADDRESS)
    if output[start : start + len(font_data)] != font_data:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Glyph table was not written")
    (font_pointer,) = struct.unpack_from(
        "<I", output, _offset(HOOK_CODE_ADDRESS + HOOK_SYMBOLS["rtl_font_pointer"])
    )
    if font_pointer != RTL_FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook glyph table is wrong")


def check_golden_sun_translations(
    font_path: Path | None = None, preview_path: Path | None = None
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure every line."""
    glyph_map = build_golden_sun_arabic_glyph_map()
    font = build_golden_sun_rtl_font(font_path) if font_path is not None else None
    if preview_path is not None:
        if font is None:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
        font_preview(font).save(preview_path)
    advances = font.advances() if font is not None else _unmeasured_advances()
    encoded = encode_translations(GoldenSunArabicEncoder(advances=advances, glyph_map=glyph_map))
    report: dict[str, object] = {
        "strings": sorted(encoded),
        "arabic_glyphs": len(glyph_map.characters),
        "lines_measured": font is not None,
        "encoded_codes": sum(len(codes) for codes, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["widest_line"] = max(
            int(line["width"]) for _, lines in encoded.values() for line in lines
        )
    return report


def _unmeasured_advances() -> dict[int, int]:
    glyph_map = build_golden_sun_arabic_glyph_map()
    advances = {ord(character): 0 for character in USA_LATIN_ADVANCES}
    advances.update((ARABIC_CODE_BASE + slot, 0) for slot in range(len(glyph_map.characters)))
    advances[0x20] = 0
    return advances


def encode_golden_sun_arabic_line(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one logical line; with a font, also report its rendered pixel width."""
    font = build_golden_sun_rtl_font(font_path) if font_path is not None else None
    advances = font.advances() if font is not None else _unmeasured_advances()
    encoder = GoldenSunArabicEncoder(advances=advances)
    result = encoder.encode_message(
        TokenStream((TextToken(text), golden_sun_command("end", KEY_END)))
    )
    payload: dict[str, object] = {
        "codes": " ".join(f"{code:03X}" for code in result.codes),
        "count": len(result.codes),
    }
    if font is not None:
        payload["width"] = result.lines[0].width
        payload["max_line_width"] = MAX_LINE_WIDTH
    return payload


def write_build_outputs(
    build: GoldenSunArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
