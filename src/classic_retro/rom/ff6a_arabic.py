"""Arabic ROM overlay for Final Fantasy VI Advance (USA).

There is no source-matching decompilation of this game, so the overlay patches
the exact USA image (``BZ6E``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced are verified;
2. the image is expanded from 8 to 16 MiB (0xFF fill);
3. the Thumb hooks (``ff6a_arabic_hooks.s``) go to ``0x08800000``, the Arabic
   ``FONT`` to ``0x08801000`` and a rebuilt dialogue ``TEXT`` bank, with the
   translated messages in place, to ``0x08804000``;
4. the five references to the original dialogue bank point to the rebuilt one
   (the original bank stays in the image, untouched);
5. six short code sequences become ``ldr rN, [pc]; bx rN`` jumps to the hooks.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import literal_jump
from classic_retro.engines.ff6a import (
    END,
    Ff6aFont,
    Ff6aTextBank,
    command_skeleton,
    split_message,
)
from classic_retro.engines.ff6a_arabic import (
    ARABIC_CODE_BASE,
    GLYPH_HEIGHT,
    RIGHT_EDGE,
    RTL_MARKER,
    USA_LATIN_GLYPHS,
    Ff6aArabicEncoder,
    Ff6aArabicFontResult,
    Ff6aLayout,
    build_ff6a_arabic_font,
    build_ff6a_arabic_glyph_map,
    ff6a_codes_notation,
    ff6a_command,
    font_preview,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.ff6a_arabic_script import Ff6aArabicMessage, ff6a_arabic_messages
from classic_retro.text.tokens import TextToken, TokenStream

USA_SHA256 = "1310f2ad3c13f5446cf6c43d01d48aad640d6b8a4fbba2b92c776f4f6d90e6ff"
USA_SIZE = 0x800000
ROM_BASE = 0x08000000
EXPANDED_SIZE = 0x1000000
EXPANSION_FILL = 0xFF

LATIN_FONT_ADDRESS = 0x08162CCC
DIALOGUE_BANK_ADDRESS = 0x08174454
DIALOGUE_BANK_REFERENCES = (0x08108A88, 0x0810A0C8, 0x08150B00, 0x0815FFD8, 0x0815FFEC)

HOOK_CODE_ADDRESS = 0x08800000
ARABIC_FONT_ADDRESS = 0x08801000
TEXT_BANK_ADDRESS = 0x08804000
HOOK_SOURCE = Path(__file__).with_name("ff6a_arabic_hooks.s")

# arm-none-eabi-as -mcpu=arm7tdmi ff6a_arabic_hooks.s; ld -Ttext 0x08800000; objcopy -O binary
HOOK_CODE = bytes.fromhex(
    "a0b44f48844207d94e48251a4e4f3868408985422ad201e0376c2500307ef028"
    "27d84a4909680a78d72a01d14a78bf2a0cd13968aa005218414bd21812688a5c"
    "b37de0331b1a981a00d500200290707e0390504604903e48844638002b00a0bc"
    "3c49202200f008f83b490847a0bc3b480047a0bc3a4800476047c04631480a1a"
    "3148006843899a4208d2920012182c4bd2181268825c90443248004732488142"
    "01d0324b1847324b1847c046b07d3076264909680b78d72b01d14b78bf2b707e"
    "00d104300c30707610780130107029480047c046b07d30761c4a12681378d72b"
    "01d15378bf2b707e00d104300c3070760878013008701f480047c046134a1268"
    "1378d72b01d15378bf2b717e00d104310c310a1c0240184b1847c0460b480068"
    "0178d72901d14178bf2901d1482100e03f2108916126114a0992114800470000"
    "0c0100000006000084018008682400039508150800250202d3141508f1141508"
    "d5131508ff0e15083c010000650f15083d101508ef1915080d1a1508f8ff0000"
    "cbbf130800108008"
)
HOOK_SYMBOLS = {
    "hook_glyph": 0x000,
    "hook_measure": 0x07C,
    "hook_newline": 0x0AC,
    "hook_newline_alt": 0x0D4,
    "hook_dirty_band": 0x0FC,
    "hook_narration_band": 0x11C,
    "arabic_font_object": 0x184,
}
IMAGE = ImageSpec("Final Fantasy VI Advance (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("FF6A hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "ff6a-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class HookSite:
    """Original code replaced by ``ldr rN, [pc, #4*k]; bx rN; [nop]; .word hook|1``."""

    address: int
    original: bytes
    register: int
    symbol: str
    purpose: str

    def replacement(self, target: int) -> bytes:
        data = literal_jump(self.address, self.register, target)
        if len(data) > len(self.original):
            raise ClassicRetroError(
                ErrorCode.WRITE_OUT_OF_BOUNDS, f"Hook at {self.address:#x} too large"
            )
        return data + self.original[len(data) :]


HOOK_SITES = (
    HookSite(0x081514AC, bytes.fromhex("8620400084421dd8"), 0, "hook_glyph", "glyph or command"),
    HookSite(0x08150F5C, bytes.fromhex("9e20400081426bd0"), 0, "hook_measure", "line width"),
    HookSite(0x08151652, bytes.fromhex("b07d3076707e0c307076"), 0, "hook_newline", "newline"),
    HookSite(0x08151628, bytes.fromhex("b07d3076707e0c30"), 0, "hook_newline_alt", "newline"),
    HookSite(0x08151A04, bytes.fromhex("717e0c310a1c0240"), 2, "hook_dirty_band", "canvas copy"),
    HookSite(0x0813BFAC, bytes.fromhex("3f2108916126024a"), 1, "hook_narration_band", "text band"),
)


@dataclass(frozen=True, slots=True)
class Ff6aArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: Ff6aArabicFontResult
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _verify_anchors(rom: bytes) -> tuple[Ff6aFont, Ff6aTextBank]:
    """Every byte the overlay relies on or replaces, checked before any change."""
    for site in HOOK_SITES:
        start = _offset(site.address)
        if rom[start : start + len(site.original)] != site.original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Unexpected code at {site.address:#x} ({site.purpose})",
            )
    for reference in DIALOGUE_BANK_REFERENCES:
        (value,) = struct.unpack_from("<I", rom, _offset(reference))
        if value != DIALOGUE_BANK_ADDRESS:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Reference at {reference:#x} does not point to the dialogue bank",
            )
    if any(rom[_offset(HOOK_CODE_ADDRESS) :]):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH, "Image already has data after 8 MiB"
        )
    latin = Ff6aFont.parse(rom, _offset(LATIN_FONT_ADDRESS))
    codes = latin.character_codes()
    for character, (code, advance) in USA_LATIN_GLYPHS.items():
        if codes.get(character) != code or latin.glyphs[code].advance != advance:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"Latin glyph for {character!r} differs from the pinned USA font",
            )
    return latin, Ff6aTextBank.parse(rom, _offset(DIALOGUE_BANK_ADDRESS))


def _verify_source_message(bank: Ff6aTextBank, message: Ff6aArabicMessage) -> bytes:
    original = bank.message(message.index)
    if hashlib.sha256(original).hexdigest() != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Dialogue message {message.index} differs from the pinned USA script",
        )
    codes, tail = split_message(original)
    if command_skeleton(codes) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"Dialogue message {message.index} has different commands than pinned",
        )
    return tail


def encode_translations(
    encoder: Ff6aArabicEncoder,
    messages: tuple[Ff6aArabicMessage, ...] | None = None,
) -> dict[int, tuple[bytes, list[dict[str, object]]]]:
    """Validate every translation against its original commands and encode it."""
    encoded: dict[int, tuple[bytes, list[dict[str, object]]]] = {}
    for message in messages or ff6a_arabic_messages():
        if message.index in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Message {message.index} twice")
        validate_command_skeleton(message.source_skeleton, message.stream)
        result = encoder.encode_message(message.stream, layout=message.layout)
        lines = [
            {"page": line.page, "width": line.width, "centered": line.centered}
            for line in result.lines
        ]
        encoded[message.index] = (result.data, lines)
    return encoded


def build_ff6a_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[Ff6aArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> Ff6aArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    _, bank = _verify_anchors(rom)
    messages = messages or ff6a_arabic_messages(translations)
    tails = {message.index: _verify_source_message(bank, message) for message in messages}
    font = build_ff6a_arabic_font(font_path)
    font_data = font.data
    if ARABIC_FONT_ADDRESS + len(font_data) > TEXT_BANK_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic font exceeds its region")
    if len(HOOK_CODE) > ARABIC_FONT_ADDRESS - HOOK_CODE_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")

    encoded = encode_translations(Ff6aArabicEncoder(arabic_widths=font.widths), messages)
    replacements = {index: data + tails[index] for index, (data, _) in encoded.items()}
    new_bank = bank.replace(replacements).build()
    if TEXT_BANK_ADDRESS + len(new_bank) > ROM_BASE + EXPANDED_SIZE:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Dialogue bank exceeds the image")

    target = bytearray(rom) + bytes([EXPANSION_FILL]) * (EXPANDED_SIZE - len(rom))

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(ARABIC_FONT_ADDRESS, font_data)
    write(TEXT_BANK_ADDRESS, new_bank)
    for reference in DIALOGUE_BANK_REFERENCES:
        write(reference, struct.pack("<I", TEXT_BANK_ADDRESS))
    for site in HOOK_SITES:
        write(site.address, site.replacement(HOOK_CODE_ADDRESS + HOOK_SYMBOLS[site.symbol]))

    output = bytes(target)
    _verify_output(output, messages, replacements, font_data)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": sorted(replacements),
        "message_lines": {str(index): encoded[index][1] for index in sorted(encoded)},
        "arabic_glyphs": len(font.font.glyphs),
        "arabic_code_base": f"{ARABIC_CODE_BASE:#x}",
        "rtl_marker": f"{RTL_MARKER:#x}",
        "font_size": font.font_size,
        "font_baseline": font.baseline,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "glyph_height": GLYPH_HEIGHT,
        "rtl_right_x": RIGHT_EDGE,
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "arabic_font_address": f"{ARABIC_FONT_ADDRESS:#x}",
        "text_bank_address": f"{TEXT_BANK_ADDRESS:#x}",
        "text_bank_bytes": len(new_bank),
    }
    return Ff6aArabicBuild(rom=output, patch=patch, font=font, report=report)


def _verify_output(
    output: bytes,
    messages: tuple[Ff6aArabicMessage, ...],
    replacements: dict[int, bytes],
    font_data: bytes,
) -> None:
    bank = Ff6aTextBank.parse(output, _offset(TEXT_BANK_ADDRESS))
    original = Ff6aTextBank.parse(output, _offset(DIALOGUE_BANK_ADDRESS))
    for index in range(original.message_count):
        expected = replacements.get(index, original.message(index))
        if bank.message(index) != expected:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Rebuilt dialogue message {index} differs"
            )
    for message in messages:
        codes, _ = split_message(bank.message(message.index))
        if codes[0] != RTL_MARKER:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"Message {message.index} lacks the RTL marker"
            )
    arabic = Ff6aFont.parse(output, _offset(ARABIC_FONT_ADDRESS))
    if arabic.build() != font_data or arabic.height != GLYPH_HEIGHT:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Arabic FONT does not reparse")
    (font_object,) = struct.unpack_from(
        "<I", output, _offset(HOOK_CODE_ADDRESS + HOOK_SYMBOLS["arabic_font_object"])
    )
    if font_object != ARABIC_FONT_ADDRESS:
        raise ClassicRetroError(ErrorCode.BUILD_VALIDATION_FAILED, "Hook font object is wrong")


def check_ff6a_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure every line."""
    glyph_map = build_ff6a_arabic_glyph_map()
    font = build_ff6a_arabic_font(font_path) if font_path is not None else None
    if preview_path is not None:
        if font is None:
            raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
        font_preview(font).save(preview_path)
    widths = font.widths if font is not None else dict.fromkeys(glyph_map.characters, 0)
    encoded = encode_translations(
        Ff6aArabicEncoder(arabic_widths=widths), ff6a_arabic_messages(translations)
    )
    report: dict[str, object] = {
        "messages": sorted(encoded),
        "arabic_glyphs": len(glyph_map.characters),
        "lines_measured": font is not None,
        "encoded_bytes": sum(len(data) for data, _ in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = font.baseline
        report["widest_line"] = max(
            line["width"] for _, lines in encoded.values() for line in lines
        )
    return report


def encode_ff6a_arabic_line(text: str, font_path: Path | None = None) -> dict[str, object]:
    """Encode one logical line; with a font, also report its rendered pixel width."""
    glyph_map = build_ff6a_arabic_glyph_map()
    font = build_ff6a_arabic_font(font_path) if font_path is not None else None
    widths = font.widths if font is not None else dict.fromkeys(glyph_map.characters, 0)
    encoder = Ff6aArabicEncoder(arabic_widths=widths)
    result = encoder.encode_message(
        TokenStream((TextToken(text), ff6a_command("end", END))),
        layout=Ff6aLayout.DIALOGUE,
    )
    payload: dict[str, object] = {
        "codes": " ".join(f"{code:03X}" for code in result.codes),
        "bytes_hex": result.data.hex(),
        "bytes": len(result.data),
    }
    if font is not None:
        payload["width"] = result.lines[0].width
        payload["window_width"] = RIGHT_EDGE
    return payload


def write_build_outputs(
    build: Ff6aArabicBuild, out_dir: Path, *, rom_name: str | None
) -> dict[str, str]:
    patch_path = write_patch(out_dir, PATCH_NAME, build.patch)
    font_preview(build.font).save(out_dir / "arabic_font_preview.png")
    written = {"patch": str(patch_path), "font_preview": str(out_dir / "arabic_font_preview.png")}
    return written | write_image(out_dir, rom_name, build.rom)


def assemble_hooks(source: Path = HOOK_SOURCE) -> tuple[bytes, dict[str, int]]:
    """Assemble the hook source with GNU binutils (arm-none-eabi-*) and read its symbols."""
    return HOOKS.assemble(source)


def extract_originals(
    rom: bytes,
    translations: TranslationSet | None = None,
    *,
    messages: tuple[Ff6aArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the translators' notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    messages = messages or ff6a_arabic_messages(translations)
    latin, bank = _verify_anchors(rom)
    characters = {code: character for character, code in latin.character_codes().items()}
    originals: dict[str, str] = {}
    for message in messages:
        _verify_source_message(bank, message)
        codes, _ = split_message(bank.message(message.index))
        originals[f"message.{message.index}"] = ff6a_codes_notation(codes, characters)
    return originals


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
