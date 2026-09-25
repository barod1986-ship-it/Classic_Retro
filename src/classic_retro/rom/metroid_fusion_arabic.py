"""Arabic ROM overlay for *Metroid Fusion* (USA).

The metroidret/mf decompilation names the code below, but it cannot be
shifted and takes its data from the original, so the overlay patches the
user's image (``AMTE``, SHA-256 below) and ships as a BPS patch:

1. the input hash and every original byte that is replaced or relied on are
   verified, and every translated text's original is checked against its
   pinned hash and commands, and against its English list;
2. the Thumb hooks (``metroid_fusion_arabic_hooks.s``), the right-to-left
   glyph widths and sheet (``engines.metroid_fusion_arabic``) and the
   translated texts go into the 0xFF padding at the end of the image; the
   image stays 8 MiB;
3. ``GetCharacterWidth`` jumps to its hook, and twelve sites in the text routines
   call theirs through veneers written over Dma3Transfer_Unused1, since the
   padding is out of a BL's reach;
4. a translated question's cursor stands left of each Arabic option, and the
   right and left keys choose the option on that side: immediates of the
   questions' handler;
5. the English lists' pointer to every translated text is repointed to the
   Arabic one. A text of the Arabic bank is what the hooks turn right to left.

The hook bytes are stored here; ``assemble_hooks`` rebuilds them from the
assembly source with GNU binutils so CI can prove they match.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu.thumb import arm_veneer, bl_instruction, literal_jump
from classic_retro.engines.metroid_fusion import (
    END,
    ENGLISH,
    FONT_CODES,
    FONT_GRAPHICS,
    FONT_WIDTHS,
    MESSAGE_LANGUAGES,
    MONOLOGUE_LANGUAGES,
    NAVIGATION_LANGUAGES,
    ROM_BASE,
    TILE_BYTES,
    command_skeleton,
    pack_units,
    parse_notation,
    read_text,
    text_notation,
    text_units,
)
from classic_retro.engines.metroid_fusion_arabic import (
    BASELINE,
    BRIEFING,
    LINE_WIDTH,
    PAGE,
    QUESTION_BOX,
    RENDERER_DIALECTS,
    RTL_CODE_SPAN,
    RTL_FIRST_CODE,
    SPACE,
    SPACE_WIDTH,
    STRIP,
    MfArabicEncoder,
    MfRtlFont,
    build_metroid_fusion_rtl_font,
    font_preview,
    message_preview,
    messages_sheet,
    question_cursor_x,
    question_options,
    validate_command_skeleton,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.patching.hooks import HookProgram
from classic_retro.patching.image import ImageSpec
from classic_retro.patching.outputs import base_report, write_image, write_patch
from classic_retro.rebuild.bps import BpsPatch, create_bps
from classic_retro.rom.metroid_fusion_arabic_script import (
    MESSAGE_LIST,
    MONOLOGUE_LIST,
    NAVIGATION_LIST,
    MfArabicMessage,
    MfTextList,
    metroid_fusion_arabic_messages,
)

USA_SHA256 = "a56ce3d7f8f3f4f4d0468d421fff5dd3ee3aec99a58244377e43aae769dc3fe8"
USA_SIZE = 0x800000
IMAGE_END = ROM_BASE + USA_SIZE

# The 0xFF padding at the end of the image (from 0x0879ECC8 to its end).
HOOK_CODE_ADDRESS = 0x0879F000
RTL_WIDTHS_ADDRESS = 0x0879F800
# The Arabic bank: every free byte up to the glyph sheet, room for every text.
ARABIC_TEXT_ADDRESS = 0x087A0000
ARABIC_TEXT_END = 0x087E0000
# DrawCharacter reads glyph c at FONT_GRAPHICS + 32 * c.
FONT_ADDRESS = FONT_GRAPHICS + TILE_BYTES * RTL_FIRST_CODE
FONT_END = FONT_ADDRESS + TILE_BYTES * RTL_CODE_SPAN
PADDING = 0xFF
HOOK_SOURCE = Path(__file__).with_name("metroid_fusion_arabic_hooks.s")

# The game's code the hooks call or rely on (names from the decompilation).
GET_CHARACTER_WIDTH = 0x08079118
DRAW_CHARACTER = 0x0807913C
NONGAMEPLAY_RAM = 0x03001484
PREVIOUS_CONVERSATION = 0x03000B88
LANGUAGE = 0x03000011
# Dma3Transfer_Unused1: 64 bytes nothing calls, near the intro's text routines
# (the SHA-256 of its code).
VENEER_AREA = 0x08098940
VENEER_AREA_SIZE = 64
VENEER_AREA_SHA256 = "db472d6b4ef115eee7a30b5b677aaad91223e1740781c1cbeedd33e6632695ba"

# arm-none-eabi-as -mcpu=arm7tdmi metroid_fusion_arabic_hooks.s; ld -Ttext 0x0879F000; objcopy
HOOK_CODE = bytes.fromhex(
    "0004000c4149884202d24149085c70474049401a05d34049884202d23f49085c"
    "70470a20704730b43a4c041b3a4dac4210d24c091f252c40e400e418a418e025"
    "2c1b00d50024890a8902e5086d01491907232340324ca44630bc604730b57200"
    "00f036f801d236218a1af80130bc02bc084730b500f02cf8eb2000d204209081"
    "30bc02bc084730b500f022f802d2e221081a00e00e30002130bc10bc204729b5"
    "e02a00d3e03a00f01af802d2e221891a01e00821891829bc10bc20473db500f0"
    "0ef8082100d2e2213dbcc18501bc0047144c2468144d641b144dac427047114b"
    "134c185d451e6d00124c2478a04200d10135114c00202456a400104b1c59ad00"
    "6459094d641b094dac427047a00400003462570840b000000008000000f87908"
    "3d9107088414000300007a080000040020020000880b000311000003f0c07908"
)
HOOK_SYMBOLS = {
    "hook_arrow": 0x72,
    "hook_cursor": 0x86,
    "hook_draw": 0x26,
    "hook_fade": 0x5C,
    "hook_nav_cursor": 0x9E,
    "hook_nav_cursor_start": 0xBC,
    "hook_width": 0x00,
}
IMAGE = ImageSpec("Metroid Fusion (USA)", USA_SHA256, USA_SIZE, ROM_BASE)
HOOKS = HookProgram("Metroid Fusion hooks", HOOK_SOURCE, HOOK_CODE_ADDRESS, HOOK_CODE, HOOK_SYMBOLS)
PATCH_NAME = "metroid-fusion-usa-arabic-opening.bps"


@dataclass(frozen=True, slots=True)
class Veneer:
    """A jump to a hook, in the veneer area: through ip (an ARM veneer) or a low register.

    Each veneer clobbers a register its sites do not need: ip at a call (the
    callee may clobber it), otherwise a register the code reloads after the site.
    """

    address: int
    hook: str
    register: int | None = None

    def code(self) -> bytes:
        target = HOOKS.symbol_address(self.hook)
        if self.register is None:
            return arm_veneer(target)
        return literal_jump(self.address, self.register, target)


VENEERS = {
    veneer.hook: veneer
    for veneer in (
        # At the five DrawCharacter calls: ip.
        Veneer(0x08098940, "hook_draw"),
        # In the fade, ip holds the loop's end; r3 is reloaded after the site.
        Veneer(0x08098950, "hook_fade", 3),
        Veneer(0x08098958, "hook_arrow", 1),
        Veneer(0x08098960, "hook_cursor", 1),
        # r1 is the cursor's x the hook returns, or stores.
        Veneer(0x08098968, "hook_nav_cursor", 1),
        Veneer(0x08098970, "hook_nav_cursor_start", 1),
    )
}


@dataclass(frozen=True, slots=True)
class Site:
    """Game code replaced by a BL to a hook's veneer."""

    address: int
    original: bytes
    hook: str

    def patch(self) -> bytes:
        return bl_instruction(self.address, VENEERS[self.hook].address)


def _call_site(address: int, hook: str) -> Site:
    """A call to DrawCharacter, sent to a hook instead."""
    return Site(address, bl_instruction(address, DRAW_CHARACTER), hook)


SITES = (
    # IntroProcessText, NewFileIntroProcessAdamText, SpecialCutsceneProcessMonologue,
    # NavigationConversationProcessText and the questions (0x0807A0FC).
    _call_site(0x08098690, "hook_draw"),
    _call_site(0x080988D4, "hook_draw"),
    _call_site(0x080980CC, "hook_draw"),
    _call_site(0x0807A076, "hook_draw"),
    _call_site(0x0807A28E, "hook_draw"),
    # The monologue's fade (0x08098158): `lsls r2, r6, #1; lsls r0, r7, #7`.
    Site(0x080981F8, bytes.fromhex("7200f801"), "hook_fade"),
    # NewFileIntroProcessTextCursor: `movs r0, #235; strh r0, [r2, #12]`.
    Site(0x08098C1E, bytes.fromhex("eb209081"), "hook_arrow"),
    # NewFileIntroProcessAdamTextCursor: `adds r0, #14; movs r1, #0`.
    Site(0x08090740, bytes.fromhex("0e300021"), "hook_cursor"),
    # NavigationConversationHandler, the briefing's typing cursor: on the second
    # line `ldr r4, =0xFF28; adds r1, r2, r4`, on the first `adds r1, r2, #0; adds r1, #8`.
    Site(0x0807A65A, bytes.fromhex("0a4c1119"), "hook_nav_cursor"),
    Site(0x0807A696, bytes.fromhex("111c0831"), "hook_nav_cursor"),
    # Its x before the first character, as a briefing starts and when it starts
    # again: `movs r1, #8; strh r1, [r0, #0x2e]`.
    Site(0x0807AB5C, bytes.fromhex("0821c185"), "hook_nav_cursor_start"),
    Site(0x0807ADF6, bytes.fromhex("0821c185"), "hook_nav_cursor_start"),
)
# GetCharacterWidth's first eight bytes, replaced by a jump to hook_width
# (`push {lr}; lsls r0, r0, #16; lsrs r1, r0, #16; ldr r0, =0x49F`).
WIDTH_ENTRY = bytes.fromhex("00b50004010c0348")

# The questions' keys (gChangedInput).
KEY_RIGHT = 0x10
KEY_LEFT = 0x20
YES = "yes"
NO = "no"
YES_KEY = "yes key"
NO_KEY = "no key"


@dataclass(frozen=True, slots=True)
class QuestionSite:
    """A ``movs rN, #imm8`` of the questions' handler: the Yes/No cursor's x or a key.

    ``YES`` and ``NO`` are the cursor's x on that option, ``YES_KEY`` and
    ``NO_KEY`` the key that moves it there. In English Yes is on the left.
    """

    address: int
    register: int
    original: int
    role: str

    def code(self, value: int) -> bytes:
        return bytes((value, 0x20 | self.register))


# NavigationConversationHandler, for each question (by its message): the
# cursor's x as the question starts, then on Yes and on No; the keys.
# fmt: off
QUESTION_SITES: dict[int, tuple[QuestionSite, ...]] = {
    43: (
        QuestionSite(0x0807A88A, 1, 0x34, YES),
        QuestionSite(0x0807A90C, 0, 0x34, YES),
        QuestionSite(0x0807A91A, 0, 0x84, NO),
        QuestionSite(0x0807A8A8, 0, KEY_LEFT, YES_KEY),
        QuestionSite(0x0807A8D0, 0, KEY_RIGHT, NO_KEY),
    ),
    44: (
        QuestionSite(0x0807ACA2, 1, 0x84, NO),
        QuestionSite(0x0807AD28, 0, 0x34, YES),
        QuestionSite(0x0807AD36, 0, 0x84, NO),
        QuestionSite(0x0807ACC6, 0, KEY_LEFT, YES_KEY),
        QuestionSite(0x0807ACEC, 0, KEY_RIGHT, NO_KEY),
    ),
}
# fmt: on
# Which list each renderer's texts come from.
RENDERER_LISTS = {
    STRIP: MONOLOGUE_LIST,
    PAGE: MONOLOGUE_LIST,
    BRIEFING: NAVIGATION_LIST,
    QUESTION_BOX: MESSAGE_LIST,
}

# Bytes the hooks rely on without replacing them:
ANCHORS = {
    # GetCharacterWidth's last code with a width and the widths it reads;
    0x0807912C: struct.pack("<II", FONT_CODES - 1, FONT_WIDTHS),
    # DrawCharacter's glyph sheet, where the right-to-left codes are found;
    0x080791D8: struct.pack("<I", FONT_GRAPHICS),
    # the game's space, which Arabic text uses;
    FONT_WIDTHS + SPACE: bytes((SPACE_WIDTH,)),
    # the text being drawn: the intro's data (IntroProcessText,
    # SpecialCutsceneProcessMonologue, NewFileIntroProcessTextCursor);
    0x08098514: struct.pack("<I", NONGAMEPLAY_RAM),
    0x08097FF0: struct.pack("<I", NONGAMEPLAY_RAM),
    0x08098C28: struct.pack("<I", NONGAMEPLAY_RAM),
    # the strip's tiles (IntroProcessText, NewFileIntroProcessAdamText);
    0x080986E4: struct.pack("<I", 0x0600D000),
    0x08098938: struct.pack("<I", 0x0600D000),
    # a monologue page's last column (`cmp r0, #27`) and its fading map;
    0x080980D2: bytes.fromhex("1b28"),
    0x0809823C: struct.pack("<II", 0x06004842, 0x06004882),
    # the typing cursor's pen (`ldrh r0, [r3, #12]` ... `adds r0, r0, r1`);
    0x08090734: bytes.fromhex("9889084c1919c00009784018"),
    # how a briefing finds its text, which hook_nav_cursor repeats: the entry
    # (conversation - 1) * 2, one more when it comes again, of the language's list;
    0x08079CCE: bytes.fromhex("88229200a8180178481e430012480078814200d10133"),
    0x08079CE4: bytes.fromhex("10491148007800060016800040180168980040180668"),
    0x08079D24: struct.pack("<III", PREVIOUS_CONVERSATION, NAVIGATION_LANGUAGES, LANGUAGE),
    # the question (0x0807A0FC): message 43 + its number, in the box of the
    # first panel; 83A0 16 pixels before 0xA0;
    0x0807A14E: bytes.fromhex("ac30"),
    0x0807A174: struct.pack("<III", MESSAGE_LANGUAGES, LANGUAGE, 0x06007000),
    0x0807A1D0: bytes.fromhex("1038"),
    0x0807A1DC: struct.pack("<I", 0x83A0),
    # the sprites the cursors are: a briefing's typing cursor (x - 5, the
    # line under the pen) and the question's triangle (x - 5 to x - 3);
    0x08565EBA: bytes.fromhex("0100fc00fb012332"),
    0x08565F08: bytes.fromhex("0100f880fb0141320100f880fc0141320100f880fd014132"),
    # the English lists.
    MONOLOGUE_LANGUAGES + 4 * ENGLISH: struct.pack("<I", MONOLOGUE_LIST.address),
    NAVIGATION_LANGUAGES + 4 * ENGLISH: struct.pack("<I", NAVIGATION_LIST.address),
    MESSAGE_LANGUAGES + 4 * ENGLISH: struct.pack("<I", MESSAGE_LIST.address),
}


@dataclass(frozen=True, slots=True)
class MfArabicBuild:
    rom: bytes
    patch: BpsPatch
    font: MfRtlFont
    report: dict[str, object] = field(default_factory=dict)


_offset = IMAGE.offset
_word = IMAGE.word


def source_digest(units: tuple[int, ...]) -> str:
    """SHA-256 of an original text's units, up to its final ``FF00``."""
    return hashlib.sha256(pack_units(units)).hexdigest()


def stored_text(units: tuple[int, ...]) -> bytes:
    """A text as the bank holds it: its units and ``FF00``, then zeros up to a word."""
    data = pack_units((*units, END))
    return data + bytes(-len(data) % 4)


def verify_usa_image(rom: bytes) -> None:
    IMAGE.verify(rom)


def _question_sites() -> tuple[QuestionSite, ...]:
    return tuple(site for sites in QUESTION_SITES.values() for site in sites)


def _verify_anchors(rom: bytes) -> None:
    """Every byte the overlay relies on or replaces, checked before any change."""
    if len(rom) != USA_SIZE:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "Image is not 8 MiB")
    expected = {
        GET_CHARACTER_WIDTH: WIDTH_ENTRY,
        **{site.address: site.original for site in SITES},
        **{site.address: site.code(site.original) for site in _question_sites()},
        **ANCHORS,
    }
    for address, original in expected.items():
        if IMAGE.read(rom, address, len(original)) != original:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected bytes at {address:#x}"
            )
    veneer_area = IMAGE.read(rom, VENEER_AREA, VENEER_AREA_SIZE)
    if hashlib.sha256(veneer_area).hexdigest() != VENEER_AREA_SHA256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"Unexpected code at {VENEER_AREA:#x}"
        )
    if not IMAGE.filled(rom, HOOK_CODE_ADDRESS, IMAGE_END, PADDING):
        raise ClassicRetroError(
            ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
            f"{HOOK_CODE_ADDRESS:#x}..{IMAGE_END:#x} is not empty padding",
        )
    # The hooks' literals: the bank and its size, the widths and their codes,
    # the game's widths, the text's data, the briefings' lists and DrawCharacter.
    for value in (
        ARABIC_TEXT_ADDRESS,
        ARABIC_TEXT_END - ARABIC_TEXT_ADDRESS,
        RTL_WIDTHS_ADDRESS,
        RTL_FIRST_CODE,
        RTL_CODE_SPAN,
        FONT_WIDTHS,
        NONGAMEPLAY_RAM,
        PREVIOUS_CONVERSATION,
        LANGUAGE,
        NAVIGATION_LANGUAGES,
        DRAW_CHARACTER | 1,
    ):
        if struct.pack("<I", value) not in HOOK_CODE:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"The hooks do not use {value:#x}"
            )


def _verify_source(rom: bytes, message: MfArabicMessage) -> tuple[int, ...]:
    if _word(rom, message.pointer) != message.source_address:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: {message.text_list.name} {message.index} is not at "
            f"{message.source_address:#x}",
        )
    try:
        original = read_text(rom, message.source_address)
    except ClassicRetroError as exc:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: no text at {message.source_address:#x}",
        ) from exc
    if source_digest(original) != message.source_sha256:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original at {message.source_address:#x} differs from the "
            "pinned USA script",
        )
    if command_skeleton(original, message.dialect) != message.source_skeleton:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{message.key}: the original has different commands than pinned",
        )
    return original


def _check_place(message: MfArabicMessage, places: set[tuple[str, int]]) -> None:
    """A text of its renderer's list, once, and a question the handler asks."""
    text_list: MfTextList = message.text_list
    if RENDERER_LISTS.get(message.renderer) != text_list:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            f"{message.key}: the {message.renderer} does not show {text_list.name} texts",
        )
    if not 0 <= message.index < text_list.length:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE, f"{message.key}: no {text_list.name} {message.index}"
        )
    if message.renderer == QUESTION_BOX and message.index not in QUESTION_SITES:
        raise ClassicRetroError(
            ErrorCode.INVALID_REFERENCE,
            f"{message.key}: message {message.index} is not a question of the briefings",
        )
    place = (text_list.name, message.index)
    if place in places:
        raise ClassicRetroError(
            ErrorCode.DUPLICATE_ENTRY_ID,
            f"{message.key} shares {text_list.name} {message.index}",
        )
    places.add(place)


@dataclass(frozen=True, slots=True)
class MfEncodedText:
    """A translated text as the bank stores it, its units and, with a font, its line widths."""

    stored: bytes
    units: tuple[int, ...]
    line_widths: tuple[int, ...]


def encode_messages(
    encoder: MfArabicEncoder, messages: tuple[MfArabicMessage, ...] | None = None
) -> dict[str, MfEncodedText]:
    """Validate every translation against its original's commands and encode it."""
    encoded: dict[str, MfEncodedText] = {}
    places: set[tuple[str, int]] = set()
    for message in messages or metroid_fusion_arabic_messages():
        if message.key in encoded:
            raise ClassicRetroError(ErrorCode.DUPLICATE_ENTRY_ID, f"Text {message.key} twice")
        _check_place(message, places)
        pieces = message.pieces
        validate_command_skeleton(message.source_skeleton, pieces)
        result = encoder.encode(pieces, message.renderer)
        encoded[message.key] = MfEncodedText(
            stored_text(result.units), result.units, result.line_widths or ()
        )
    return encoded


def question_patches(
    font: MfRtlFont, messages: Sequence[MfArabicMessage], encoded: dict[str, MfEncodedText]
) -> dict[int, bytes]:
    """The handler's code for every translated question: its cursor and its keys.

    The cursor stands left of each Arabic option, and the right key chooses
    Yes (on the right), the left key No.
    """
    patches: dict[int, bytes] = {}
    for message in messages:
        if message.renderer != QUESTION_BOX:
            continue
        options = question_options(encoded[message.key].units, font.width)
        if len(options) != 2:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"{message.key}: a question needs two options, Yes then No",
            )
        values = {
            YES: question_cursor_x(options[0]),
            NO: question_cursor_x(options[1]),
            YES_KEY: KEY_RIGHT,
            NO_KEY: KEY_LEFT,
        }
        for site in QUESTION_SITES[message.index]:
            value = values[site.role]
            if not 0 <= value <= 0xFF:
                raise ClassicRetroError(
                    ErrorCode.BUILD_VALIDATION_FAILED,
                    f"{message.key}: the cursor's x ({value}) does not fit its instruction",
                )
            patches[site.address] = site.code(value)
    return patches


def build_metroid_fusion_arabic_rom(
    rom: bytes,
    font_path: Path,
    *,
    messages: tuple[MfArabicMessage, ...] | None = None,
    translations: TranslationSet | None = None,
    verify_identity: bool = True,
) -> MfArabicBuild:
    """Build the Arabic image and its BPS patch from the original USA image.

    ``messages`` and ``verify_identity`` exist for synthetic tests; a real
    build always uses the pinned script against the pinned image.
    """
    if verify_identity:
        verify_usa_image(rom)
    _verify_anchors(rom)
    messages = messages or metroid_fusion_arabic_messages(translations)
    for message in messages:
        _verify_source(rom, message)
    font = build_metroid_fusion_rtl_font(font_path)
    sheet = font.sheet()
    widths = font.width_table()
    if HOOK_CODE_ADDRESS + len(HOOK_CODE) > RTL_WIDTHS_ADDRESS:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Hook code exceeds its region")
    if FONT_ADDRESS + len(sheet) > FONT_END or FONT_END > IMAGE_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "The glyphs exceed their region")

    encoded = encode_messages(MfArabicEncoder(font), messages)
    texts = bytearray()
    addresses: dict[str, int] = {}
    for message in messages:
        addresses[message.key] = ARABIC_TEXT_ADDRESS + len(texts)
        texts += encoded[message.key].stored
    if ARABIC_TEXT_ADDRESS + len(texts) > ARABIC_TEXT_END:
        raise ClassicRetroError(ErrorCode.RELOCATION_OVERFLOW, "Arabic texts exceed the region")
    questions = question_patches(font, messages, encoded)

    target = bytearray(rom)

    def write(address: int, data: bytes) -> None:
        start = _offset(address)
        target[start : start + len(data)] = data

    write(HOOK_CODE_ADDRESS, HOOK_CODE)
    write(RTL_WIDTHS_ADDRESS, widths)
    write(FONT_ADDRESS, sheet)
    write(ARABIC_TEXT_ADDRESS, bytes(texts))
    for veneer in VENEERS.values():
        write(veneer.address, veneer.code())
    write(GET_CHARACTER_WIDTH, _width_jump())
    for site in SITES:
        write(site.address, site.patch())
    for address, code in questions.items():
        write(address, code)
    for message in messages:
        write(message.pointer, struct.pack("<I", addresses[message.key]))

    output = bytes(target)
    _verify_output(output, rom, widths, sheet, messages, encoded, addresses, questions)
    patch = create_bps(rom, output)
    report: dict[str, object] = {
        **base_report(IMAGE.title, rom, output, patch),
        "messages": len(messages),
        "message_lines": {
            message.key: list(encoded[message.key].line_widths) for message in messages
        },
        "line_width_limit": LINE_WIDTH,
        "rtl_glyphs": len(font.glyphs),
        "rtl_codes": f"{min(font.glyphs):04X}..{max(font.glyphs):04X}",
        "font_size": font.font_size,
        "font_baseline": BASELINE,
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "hook_sites": len(SITES) + 1,
        "veneers": len(VENEERS),
        "question_sites": len(questions),
        "hook_code_address": f"{HOOK_CODE_ADDRESS:#x}",
        "font_address": f"{FONT_ADDRESS:#x}",
        "arabic_text_address": f"{ARABIC_TEXT_ADDRESS:#x}",
        "arabic_text_bytes": len(texts),
    }
    return MfArabicBuild(rom=output, patch=patch, font=font, report=report)


def _width_jump() -> bytes:
    return literal_jump(GET_CHARACTER_WIDTH, 1, HOOKS.symbol_address("hook_width"))


def _verify_output(
    output: bytes,
    rom: bytes,
    widths: bytes,
    sheet: bytes,
    messages: tuple[MfArabicMessage, ...],
    encoded: dict[str, MfEncodedText],
    addresses: dict[str, int],
    questions: dict[int, bytes],
) -> None:
    changed = {
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    }
    written = [
        (GET_CHARACTER_WIDTH, len(WIDTH_ENTRY)),
        (VENEER_AREA, VENEER_AREA_SIZE),
        *((site.address, len(site.original)) for site in SITES),
        *((address, len(code)) for address, code in questions.items()),
        *((message.pointer, 4) for message in messages),
    ]
    allowed = {
        _offset(address + delta) & ~0xFFF
        for address, length in written
        for delta in (0, length - 1)
    }
    allowed |= set(range(_offset(HOOK_CODE_ADDRESS) & ~0xFFF, _offset(IMAGE_END), 0x1000))
    if not changed <= allowed:
        raise ClassicRetroError(
            ErrorCode.BUILD_VALIDATION_FAILED, "The overlay changed bytes outside its sites"
        )
    expected = {
        HOOK_CODE_ADDRESS: HOOK_CODE,
        RTL_WIDTHS_ADDRESS: widths,
        FONT_ADDRESS: sheet,
        GET_CHARACTER_WIDTH: _width_jump(),
        **{veneer.address: veneer.code() for veneer in VENEERS.values()},
        **{site.address: site.patch() for site in SITES},
        **questions,
    }
    for address, data in expected.items():
        if IMAGE.read(output, address, len(data)) != data:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{address:#x} does not read back"
            )
    for message in messages:
        address = _word(output, message.pointer)
        if address != addresses[message.key]:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key}: pointer not repointed"
            )
        stored = encoded[message.key].stored
        if (
            IMAGE.read(output, address, len(stored)) != stored
            or stored_text(read_text(output, address)) != stored
        ):
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED, f"{message.key} does not read back"
            )


def check_metroid_fusion_translations(
    font_path: Path | None = None,
    preview_path: Path | None = None,
    text_preview_path: Path | None = None,
    *,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    """Validate the translations without the ROM; with a font, measure and draw every text."""
    font = build_metroid_fusion_rtl_font(font_path) if font_path is not None else None
    if font is None and (preview_path is not None or text_preview_path is not None):
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    if font is not None and preview_path is not None:
        font_preview(font).save(preview_path)
    messages = metroid_fusion_arabic_messages(translations)
    encoded = encode_messages(MfArabicEncoder(font), messages)
    if font is not None and text_preview_path is not None:
        messages_sheet(
            [
                (message.key, message_preview(font, encoded[message.key].units, message.renderer))
                for message in messages
            ]
        ).save(text_preview_path)
    report: dict[str, object] = {
        "messages": len(messages),
        "lines_measured": font is not None,
        "encoded_units": sum(len(text.units) for text in encoded.values()),
    }
    if font is not None:
        report["font_size"] = font.font_size
        report["font_baseline"] = BASELINE
        report["rtl_glyphs"] = len(font.glyphs)
        report["widest_line"] = max(max(text.line_widths) for text in encoded.values())
        report["question_sites"] = len(question_patches(font, messages, encoded))
    return report


def stored_preview(font: MfRtlFont, stored: bytes, renderer: str = STRIP) -> Image.Image:
    """``message_preview`` of a stored text (up to its ``FF00``)."""
    return message_preview(font, text_units(stored, 0), renderer)


def encode_metroid_fusion_arabic_message(
    text: str, font_path: Path | None = None, *, renderer: str = STRIP
) -> dict[str, object]:
    """Encode one text in notation; with a font, the width of each line."""
    font = build_metroid_fusion_rtl_font(font_path) if font_path is not None else None
    pieces = parse_notation(text, RENDERER_DIALECTS[renderer])
    result = MfArabicEncoder(font).encode(pieces, renderer)
    payload: dict[str, object] = {
        "units": " ".join(f"{unit:04X}" for unit in result.units),
        "count": len(result.units),
    }
    if result.line_widths is not None:
        payload["widths"] = list(result.line_widths)
        payload["line_width"] = LINE_WIDTH
    return payload


def write_build_outputs(
    build: MfArabicBuild, out_dir: Path, *, rom_name: str | None
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
    messages: tuple[MfArabicMessage, ...] | None = None,
    verify_identity: bool = True,
) -> dict[str, str]:
    """Every pinned original, verified, in the engine's notation, by entry id.

    The keyword arguments exist for synthetic tests, as in the build.
    """
    if verify_identity:
        verify_usa_image(rom)
    messages = messages or metroid_fusion_arabic_messages(translations)
    _verify_anchors(rom)
    return {
        message.key: text_notation(_verify_source(rom, message), message.dialect)
        for message in messages
    }


def check_hook_code(source: Path = HOOK_SOURCE) -> dict[str, object]:
    return HOOKS.check(source)
