from __future__ import annotations

import hashlib
import json
import shutil
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.cpu import thumb
from classic_retro.engines.mlss import (
    GROUP_BYTES,
    MlssFont,
    MlssMessage,
    command_length,
    command_skeleton,
    glyph_bytes,
    measure_text,
    parse_notation,
    text_bytes,
)
from classic_retro.engines.mlss_arabic import (
    ARABIC_FONT_INDEX,
    ARABIC_PREFIX,
    CELL_HEIGHT,
    CELL_WIDTH,
    LATIN_COPIES,
    RTL_LATIN_WIDTHS,
    SPACE_ADVANCE,
    TEXT,
    MlssRtlFont,
    MlssRtlGlyph,
    build_mlss_arabic_glyph_map,
    validate_command_skeleton,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import mlss_arabic as overlay
from classic_retro.rom.mlss_arabic_script import (
    STORY_TABLE,
    MlssArabicMessage,
    mlss_arabic_messages,
)

BASE = overlay.ROM_BASE
MESSAGES = 0x083EA000
OTHER_LANGUAGES = 0x08400000
ENGLISH = {
    "banner": (
        "{FF 0B 01}\n{FF 03}{FF 35}{FF 41}{FF 25}A parade is coming{FF 0C 3C}{FF 01 00}"
        "{FF 0B 01}\n{FF 03}{FF 35}to the old town square.{FF 0C 5A}{FF 0A}"
    ),
    "shout": "{FF 0B 01}{FF 03}{FF 31}{FF 35}Watch the pot!{FF 11 01}{FF 0A}",
    "note": "{FF 0B 01}The kettle is humming\nin the kitchen.{FF 11 01}{FF 0A}",
}
ARABIC = {
    "banner": (
        "{FF 0B 01}\n{FF 03}{FF 35}{FF 41}{FF 25}موكب قادم{FF 0C 3C}{FF 01 00}"
        "{FF 0B 01}\n{FF 03}{FF 35}إلى ساحة البلدة.{FF 0C 5A}{FF 0A}"
    ),
    "shout": "{FF 0B 01}{FF 03}{FF 31}{FF 35}انتبه للقدر!{FF 11 01}{FF 0A}",
    "note": "{FF 0B 01}الإبريق يغني\nفي المطبخ.{FF 11 01}{FF 0A}",
}
GROUPS = {"banner": 7, "shout": 8, "note": 20}


def _game_font(latin_width: dict[str, int] | None = None) -> MlssFont:
    widths = [5] * 256
    glyphs = [bytes(24)] * 256
    ink = [[TEXT if x == 1 and 2 <= y <= 8 else 0 for x in range(8)] for y in range(12)]
    for character, code in LATIN_COPIES.items():
        widths[code] = (latin_width or {}).get(character, RTL_LATIN_WIDTHS[character])
        glyphs[code] = glyph_bytes(ink, 8, 12)
    return MlssFont(8, 12, tuple(widths), tuple(glyphs))


def _english(key: str) -> MlssMessage:
    body = text_bytes(parse_notation(ENGLISH[key]))
    fonts: list[MlssFont | None] = [_game_font(), None, None, None, None, None]
    width, height = measure_text(body, fonts).header()
    return MlssMessage(width, height, body)


def _synthetic_rom() -> tuple[bytes, dict[str, int]]:
    rom = bytearray(overlay.USA_SIZE)

    def put(address: int, data: bytes) -> None:
        rom[address - BASE : address - BASE + len(data)] = data

    put(overlay.PEN_SITE, overlay.PEN_SITE_ORIGINAL)
    for font_list, font in overlay.FONT_LISTS.items():
        put(font_list, struct.pack("<6I", font, 0, 0, 0, 0, 0))
        put(font, _game_font().pack())
    addresses = {}
    cursor = MESSAGES
    for key in ENGLISH:
        stored = _english(key).stored()
        addresses[key] = cursor
        put(cursor, stored)
        cursor += len(stored)
        group = STORY_TABLE + GROUPS[key] * GROUP_BYTES
        others = [OTHER_LANGUAGES + 0x100 * language for language in range(1, 5)]
        put(group, struct.pack("<5I", cursor - len(stored), *others))
    return bytes(rom), addresses


def _translations(addresses: dict[str, int]) -> tuple[MlssArabicMessage, ...]:
    return tuple(
        MlssArabicMessage(
            key=key,
            group=STORY_TABLE + GROUPS[key] * GROUP_BYTES,
            source_address=addresses[key],
            speaker="test",
            source_sha256=hashlib.sha256(_english(key).data).hexdigest(),
            source_skeleton=command_skeleton(_english(key).body),
            notation=ARABIC[key],
        )
        for key in ENGLISH
    )


def _fake_font(font_path, latin=None, **_kwargs) -> MlssRtlFont:
    glyph_map = build_mlss_arabic_glyph_map()
    ink = tuple(
        tuple(TEXT if x < 4 and 2 <= y < 9 else 0 for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    )
    glyphs = {code: MlssRtlGlyph(5, ink) for code in glyph_map.all_codes()}
    for character in LATIN_COPIES:
        glyphs[glyph_map.codes[character]] = latin[character]
    empty = tuple((0,) * CELL_WIDTH for _ in range(CELL_HEIGHT))
    glyphs[glyph_map.space] = MlssRtlGlyph(SPACE_ADVANCE, empty)
    return MlssRtlFont(
        glyphs=glyphs, codes=dict(glyph_map.codes), space=glyph_map.space, font_size=10
    )


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_rom()


@pytest.fixture(scope="module")
def build(synthetic, tmp_path_factory):
    rom, addresses = synthetic
    patcher = pytest.MonkeyPatch()
    patcher.setattr(overlay, "build_mlss_rtl_font", _fake_font)
    font_file = tmp_path_factory.mktemp("font") / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    try:
        result = overlay.build_mlss_arabic_rom(
            rom, font_file, messages=_translations(addresses), verify_identity=False
        )
    finally:
        patcher.undo()
    return rom, addresses, result


def _bl_target(address: int, data: bytes) -> int:
    high, low = struct.unpack("<HH", data)
    assert high & 0xF800 == 0xF000 and low & 0xF800 == 0xF800
    offset = (high & 0x7FF) << 12 | (low & 0x7FF) << 1
    if offset & 0x400000:
        offset -= 0x800000
    return address + 4 + offset


def test_hook_and_the_pen_site_veneer_are_written(build):
    _, _, result = build
    output = result.rom

    assert len(output) == overlay.USA_SIZE
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    site = output[overlay.PEN_SITE - BASE : overlay.PEN_SITE - BASE + 16]
    veneer = _bl_target(overlay.PEN_SITE, site[:4])
    assert veneer == overlay.PEN_SITE + 8
    (branch,) = struct.unpack_from("<H", site, 4)
    assert branch >> 11 == 0x1C
    assert overlay.PEN_SITE + 8 + ((branch & 0x7FF) << 1) == overlay.PEN_RESUME
    # ldr r0, [pc, #0]; bx r0; .word hook_draw_x | 1
    assert site[8:12] == bytes.fromhex("00480047")
    assert struct.unpack_from("<I", site, 12)[0] == overlay.HOOK_CODE_ADDRESS | 1
    # The hook compares the glyph's font with the one the overlay writes.
    assert struct.unpack_from("<I", overlay.HOOK_CODE, len(overlay.HOOK_CODE) - 4)[0] == (
        overlay.FONT_ADDRESS
    )


def test_font_lists_get_the_right_to_left_font(build):
    rom, _, result = build
    output = result.rom

    for font_list, font in overlay.FONT_LISTS.items():
        slots = struct.unpack_from("<6I", output, font_list - BASE)
        expected = [font, 0, 0, 0, 0, 0]
        expected[ARABIC_FONT_INDEX] = overlay.FONT_ADDRESS
        assert list(slots) == expected
        assert output[font - BASE : font - BASE + 0x1884] == rom[font - BASE : font - BASE + 0x1884]
    arabic = MlssFont.read(output, overlay.FONT_ADDRESS)
    assert arabic == result.font.game_font()
    assert (arabic.cell_width, arabic.cell_height) == (16, 12)
    # The Latin copies are the game's glyphs, widened to their right-to-left advances.
    dot = result.font.codes["."]
    assert arabic.widths[dot] == RTL_LATIN_WIDTHS["."]


def _only_right_to_left_glyphs(body: bytes, font: MlssRtlFont) -> bool:
    """Every character of the text is ``FE`` and a code of the right-to-left font."""
    index = 0
    glyphs = 0
    while index < len(body):
        if body[index] == 0xFF:
            index += command_length(body, index)
            continue
        if body[index] != ARABIC_PREFIX or body[index + 1] not in font.glyphs:
            return False
        glyphs += 1
        index += 2
    return glyphs > 0


def test_every_group_leads_to_its_arabic_message(build):
    rom, _, result = build
    output = result.rom
    fonts: list[MlssFont | None] = [_game_font(), None, None, None, None, None]
    fonts[ARABIC_FONT_INDEX] = result.font.game_font()

    seen = set()
    for key, group_number in GROUPS.items():
        group = STORY_TABLE + group_number * GROUP_BYTES
        (address,) = struct.unpack_from("<I", output, group - BASE)
        assert overlay.ARABIC_TEXT_ADDRESS <= address < overlay.REGION_END
        assert address % 4 == 0 and address not in seen
        seen.add(address)
        # The other languages keep their pointers.
        assert (
            output[group - BASE + 4 : group - BASE + 20]
            == rom[group - BASE + 4 : group - BASE + 20]
        )
        message = MlssMessage.read(output, address)
        assert measure_text(message.body, fonts).header() == (
            message.width_tiles,
            message.height_tiles,
        )
        assert _only_right_to_left_glyphs(message.body, result.font)
        validate_command_skeleton(command_skeleton(_english(key).body), parse_notation(ARABIC[key]))
        assert message.stored() == output[address - BASE : address - BASE + len(message.stored())]
    assert result.report["messages"] == len(GROUPS)
    assert result.report["message_headers"]["shout"] == list(
        output[struct.unpack_from("<I", output, STORY_TABLE + 8 * GROUP_BYTES - BASE)[0] - BASE :][
            :2
        ]
    )


def test_only_the_sites_pointers_and_padding_change(build):
    rom, _, result = build
    output = result.rom
    changed = [
        start
        for start in range(0, len(rom), 0x1000)
        if output[start : start + 0x1000] != rom[start : start + 0x1000]
    ]
    allowed = {
        (overlay.PEN_SITE - BASE) & ~0xFFF,
        *(((font_list - BASE) & ~0xFFF) for font_list in overlay.FONT_LISTS),
        *((((STORY_TABLE + number * GROUP_BYTES) - BASE) & ~0xFFF) for number in GROUPS.values()),
        *range(overlay.HOOK_CODE_ADDRESS - BASE, overlay.REGION_END - BASE, 0x1000),
    }
    assert set(changed) <= allowed
    assert output[overlay.REGION_END - BASE : overlay.PADDING_END - BASE].count(0) == (
        overlay.PADDING_END - overlay.REGION_END
    )


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, _, result = build

    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(16))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


@pytest.mark.parametrize("damage", ["site", "slot", "font", "padding", "latin"])
def test_changed_anchors_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_mlss_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    if damage == "site":
        rom[overlay.PEN_SITE - BASE + 5] ^= 1
    elif damage == "slot":
        struct.pack_into("<I", rom, 0x0851F9B8 + 8 - BASE, 0x08123456)
    elif damage == "font":
        struct.pack_into("<I", rom, overlay.BUBBLE_FONT - BASE, 0x33)
    elif damage == "padding":
        rom[overlay.ARABIC_TEXT_ADDRESS - BASE + 5] = 1
    else:
        font = _game_font(latin_width={"!": 9}).pack()
        rom[overlay.BUBBLE_FONT - BASE : overlay.BUBBLE_FONT - BASE + len(font)] = font
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_mlss_arabic_rom(
            bytes(rom), font_file, messages=_translations(addresses), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.SAFE_REGION_CONTENT_MISMATCH,
    }


@pytest.mark.parametrize("damage", ["pointer", "text", "header", "skeleton", "group"])
def test_changed_originals_are_refused(synthetic, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(overlay, "build_mlss_rtl_font", _fake_font)
    rom, addresses = synthetic
    rom = bytearray(rom)
    messages = list(_translations(addresses))
    shout = messages[1]
    if damage == "pointer":
        struct.pack_into("<I", rom, shout.group - BASE, addresses["note"])
    elif damage == "text":
        # "h" of the English text becomes "H".
        rom[addresses["shout"] - BASE + 18] ^= 0x20
    elif damage == "header":
        rom[addresses["shout"] - BASE] += 1
        messages[1] = MlssArabicMessage(
            **{
                **{field: getattr(shout, field) for field in shout.__dataclass_fields__},
                "source_sha256": hashlib.sha256(
                    bytes(rom[addresses["shout"] - BASE : addresses["shout"] - BASE + 2])
                    + _english("shout").body
                ).hexdigest(),
            }
        )
    elif damage == "skeleton":
        messages[1] = MlssArabicMessage(
            **{
                **{field: getattr(shout, field) for field in shout.__dataclass_fields__},
                "source_skeleton": ("{FF 0B 01}", "{FF 0A}"),
            }
        )
    else:
        messages[1] = MlssArabicMessage(
            **{
                **{field: getattr(shout, field) for field in shout.__dataclass_fields__},
                "group": shout.group + 2,
            }
        )
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_mlss_arabic_rom(
            bytes(rom), font_file, messages=tuple(messages), verify_identity=False
        )
    assert caught.value.code in {
        ErrorCode.SOURCE_BASELINE_MISMATCH,
        ErrorCode.INVALID_REFERENCE,
    }


def test_translations_must_keep_the_original_commands(synthetic, tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_mlss_rtl_font", _fake_font)
    rom, addresses = synthetic
    messages = list(_translations(addresses))
    note = messages[2]
    messages[2] = MlssArabicMessage(
        **{
            **{field: getattr(note, field) for field in note.__dataclass_fields__},
            "notation": "{FF 0B 01}الإبريق يغني في المطبخ.{FF 0A}",
        }
    )
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_mlss_arabic_rom(
            rom, font_file, messages=tuple(messages), verify_identity=False
        )
    assert caught.value.code is ErrorCode.TOKEN_ORDER_VIOLATION


def test_bl_and_branch_encoding():
    assert thumb.bl_instruction(0x0819975C, 0x08199764) == bytes.fromhex("00f002f8")
    assert thumb.branch_instruction(0x08199760, 0x0819977A) == bytes.fromhex("0be0")
    with pytest.raises(ClassicRetroError):
        thumb.bl_instruction(0x0819975C, overlay.HOOK_CODE_ADDRESS)
    with pytest.raises(ClassicRetroError):
        thumb.branch_instruction(0x08199760, 0x08199760 + 0x1000)


def test_pinned_script_covers_the_opening():
    messages = mlss_arabic_messages()

    assert len(messages) == 12
    assert len({message.key for message in messages}) == len(messages)
    assert len({message.group for message in messages}) == len(messages)
    for message in messages:
        assert (message.group - STORY_TABLE) % GROUP_BYTES == 0
        assert len(message.source_sha256) == 64
        validate_command_skeleton(message.source_skeleton, message.pieces)
        assert message.pieces[-1].is_end


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs GNU ARM binutils")
def test_hook_source_assembles_to_the_stored_bytes():
    assert overlay.check_hook_code()["match"] is True


def test_cli_checks_translations_without_rom(capsys):
    assert main(["mlss", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["messages"] == 12 and report["lines_measured"] is False


def test_cli_encodes_a_message(capsys):
    assert main(["mlss", "encode-arabic", "{FF 0B 01}مرحبا!{FF 11 01}{FF 0A}"]) == 0
    payload = json.loads(capsys.readouterr().out)
    data = bytes.fromhex(payload["bytes"])
    assert data.startswith(b"\xff\x0b\x01\xfe") and data.endswith(b"\xff\x11\x01\xff\x0a")
    assert payload["count"] == len(data)


def test_extract_reads_every_original_in_the_notation(synthetic):
    rom, addresses = synthetic
    originals = overlay.extract_originals(
        rom, messages=_translations(addresses), verify_identity=False
    )
    assert originals == ENGLISH
