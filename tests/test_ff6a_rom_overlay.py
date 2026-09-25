from __future__ import annotations

import hashlib
import json
import struct

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff6a import (
    CLOSE,
    END,
    FONT_ASCII_ENTRIES,
    FONT_NO_GLYPH,
    NARRATION,
    NEWLINE,
    PAGE,
    PAUSE,
    TIMED_CLOSE,
    Ff6aFont,
    Ff6aGlyph,
    Ff6aTextBank,
    encode_codes,
    split_message,
)
from classic_retro.engines.ff6a_arabic import (
    ARABIC_CODE_BASE,
    GLYPH_HEIGHT,
    RTL_MARKER,
    USA_LATIN_GLYPHS,
    Ff6aArabicFontResult,
    Ff6aLayout,
    build_ff6a_arabic_glyph_map,
    ff6a_command,
    ff6a_newline,
)
from classic_retro.rebuild.bps import apply_bps
from classic_retro.rom import ff6a_arabic as overlay
from classic_retro.rom.ff6a_arabic_script import Ff6aArabicMessage
from classic_retro.text.tokens import TextToken, TokenStream

BASE = overlay.ROM_BASE


def _english(index: int) -> bytes:
    codes = [0x1F, 0x09, 0x01, 0x00, index % 0x40]
    if index == 1:
        codes += [PAUSE, 0x14C, PAGE, NEWLINE, 0x02]
    if index == 6:
        codes = [NARRATION, 0x140, *codes, TIMED_CLOSE, 0x243, CLOSE]
    return encode_codes([*codes, END]) + b"\x0e"


def _synthetic_rom(messages: list[bytes]) -> bytes:
    rom = bytearray(overlay.USA_SIZE)
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        rom[start : start + len(site.original)] = site.original
    for reference in overlay.DIALOGUE_BANK_REFERENCES:
        struct.pack_into("<I", rom, reference - BASE, overlay.DIALOGUE_BANK_ADDRESS)
    ascii_map = [FONT_NO_GLYPH] * FONT_ASCII_ENTRIES
    count = max(code for code, _ in USA_LATIN_GLYPHS.values()) + 1
    glyphs = [Ff6aGlyph(1, 1, (0,) * 12)] * count
    for character, (code, advance) in USA_LATIN_GLYPHS.items():
        ascii_map[ord(character)] = code
        glyphs[code] = Ff6aGlyph(advance, 1, (1,) * 12)
    latin = Ff6aFont(12, 2, tuple(ascii_map), tuple(glyphs)).build()
    start = overlay.LATIN_FONT_ADDRESS - BASE
    rom[start : start + len(latin)] = latin
    bank = Ff6aTextBank(1, tuple(messages)).build()
    start = overlay.DIALOGUE_BANK_ADDRESS - BASE
    rom[start : start + len(bank)] = bank
    return bytes(rom)


def _fake_font(*_args, **_kwargs) -> Ff6aArabicFontResult:
    characters = build_ff6a_arabic_glyph_map().characters
    glyphs = tuple(Ff6aGlyph(5, 2, (0b0110,) * GLYPH_HEIGHT) for _ in characters)
    font = Ff6aFont(GLYPH_HEIGHT, 2, (FONT_NO_GLYPH,) * FONT_ASCII_ENTRIES, glyphs)
    return Ff6aArabicFontResult(
        font=font, font_size=10, baseline=10, widths=dict.fromkeys(characters, 5), max_advance=5
    )


def _translations(messages: list[bytes]) -> tuple[Ff6aArabicMessage, ...]:
    def sha(index: int) -> str:
        return hashlib.sha256(messages[index]).hexdigest()

    dialogue = TokenStream(
        (
            TextToken("ويدج: ها هي المدينة..."),
            ff6a_command("p", PAUSE, 0x14C),
            ff6a_command("g", PAGE, NEWLINE),
            TextToken("بيغز: يصعب تصديق ذلك"),
            ff6a_newline("n"),
            TextToken("منذ ألف عام..."),
            ff6a_command("e", END),
        )
    )
    narration = TokenStream(
        (
            ff6a_command("n", NARRATION),
            ff6a_command("c", 0x140),
            TextToken("حرب السحرة القديمة..."),
            ff6a_command("t", TIMED_CLOSE, 0x243),
            ff6a_command("x", CLOSE),
            ff6a_command("e", END),
        )
    )
    return (
        Ff6aArabicMessage(1, Ff6aLayout.DIALOGUE, sha(1), (PAUSE, 0x14C, PAGE, END), dialogue),
        Ff6aArabicMessage(
            6,
            Ff6aLayout.NARRATION,
            sha(6),
            (NARRATION, TIMED_CLOSE, 0x243, CLOSE, END),
            narration,
        ),
    )


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_ff6a_arabic_font", _fake_font)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"not read by the fake font builder")
    english = [_english(index) for index in range(24)]
    rom = _synthetic_rom(english)
    result = overlay.build_ff6a_arabic_rom(
        rom, font_file, messages=_translations(english), verify_identity=False
    )
    return rom, english, result


def test_overlay_expands_the_image_and_places_hooks_font_and_bank(build):
    rom, _, result = build
    output = result.rom

    assert len(output) == overlay.EXPANDED_SIZE
    first_change = (
        min([*overlay.DIALOGUE_BANK_REFERENCES, *(site.address for site in overlay.HOOK_SITES)])
        - BASE
    )
    assert output[:first_change] == rom[:first_change]
    assert output[first_change : len(rom)] != rom[first_change:]
    code = overlay.HOOK_CODE_ADDRESS - BASE
    assert output[code : code + len(overlay.HOOK_CODE)] == overlay.HOOK_CODE
    assert output[-1] == overlay.EXPANSION_FILL
    for reference in overlay.DIALOGUE_BANK_REFERENCES:
        assert struct.unpack_from("<I", output, reference - BASE)[0] == overlay.TEXT_BANK_ADDRESS
    for site in overlay.HOOK_SITES:
        start = site.address - BASE
        target = overlay.HOOK_CODE_ADDRESS + overlay.HOOK_SYMBOLS[site.symbol]
        assert output[start : start + len(site.original)] == site.replacement(target)
    arabic = Ff6aFont.parse(output, overlay.ARABIC_FONT_ADDRESS - BASE)
    assert arabic.height == GLYPH_HEIGHT
    assert len(arabic.glyphs) == len(build_ff6a_arabic_glyph_map().characters)


def test_rebuilt_bank_replaces_only_the_translated_messages(build):
    _, english, result = build
    bank = Ff6aTextBank.parse(result.rom, overlay.TEXT_BANK_ADDRESS - BASE)
    original = Ff6aTextBank.parse(result.rom, overlay.DIALOGUE_BANK_ADDRESS - BASE)

    assert original.messages == tuple(english)
    for index, message in enumerate(bank.messages):
        if index in {1, 6}:
            codes, tail = split_message(message)
            assert codes[0] == RTL_MARKER
            assert any(code >= ARABIC_CODE_BASE for code in codes)
            assert tail == b"\x0e"
        else:
            assert message == english[index]
    assert result.report["messages"] == [1, 6]
    assert [line["page"] for line in result.report["message_lines"]["1"]] == [0, 1, 1]


def test_bps_patch_reproduces_the_arabic_image(build):
    rom, _, result = build

    assert apply_bps(result.patch.data, rom) == result.rom
    assert result.report["patch_bytes"] == len(result.patch.data)
    assert result.report["target_sha256"] == hashlib.sha256(result.rom).hexdigest()


def test_unknown_image_is_refused():
    with pytest.raises(ClassicRetroError) as caught:
        overlay.verify_usa_image(bytes(overlay.USA_SIZE))
    assert caught.value.code is ErrorCode.UNKNOWN_GAME_REVISION


def test_changed_code_or_script_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "build_ff6a_arabic_font", _fake_font)
    font_file = tmp_path / "font.ttf"
    font_file.write_bytes(b"x")
    english = [_english(index) for index in range(24)]
    translations = _translations(english)

    rom = bytearray(_synthetic_rom(english))
    rom[overlay.HOOK_SITES[2].address - BASE] ^= 0xFF
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_ff6a_arabic_rom(
            bytes(rom), font_file, messages=translations, verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH

    edited = list(english)
    edited[1] = _english(2)
    with pytest.raises(ClassicRetroError) as caught:
        overlay.build_ff6a_arabic_rom(
            _synthetic_rom(edited), font_file, messages=translations, verify_identity=False
        )
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_cli_checks_the_script_and_encodes_a_line(capsys):
    assert main(["ff6a", "check-translations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["lines_measured"] is False
    assert 1 in report["messages"] and 20 in report["messages"]

    assert main(["ff6a", "encode-arabic", "مرحبا!"]) == 0
    encoded = json.loads(capsys.readouterr().out)
    assert encoded["codes"].startswith(f"{RTL_MARKER:03X} ")
    assert encoded["codes"].endswith(f"{END:03X}")


def test_cli_refuses_an_unknown_rom(tmp_path, capsys):
    rom = tmp_path / "game.gba"
    rom.write_bytes(bytes(64))
    font = tmp_path / "font.ttf"
    font.write_bytes(b"x")

    code = main(
        ["ff6a", "build-arabic", str(rom), "--font", str(font), "--out-dir", str(tmp_path / "o")]
    )
    assert code == 2
    assert "UNKNOWN_GAME_REVISION" in capsys.readouterr().err


def test_extract_reads_every_message_in_the_notation():
    english = [_english(index) for index in range(24)]
    originals = overlay.extract_originals(
        _synthetic_rom(english), messages=_translations(english), verify_identity=False
    )
    # The synthetic font prints only the space; the other glyphs are written as hex.
    assert originals == {
        "message.1": "{01F}{009}{001} {001}{PAUSE 14C}{PAGE}{002}{END}",
        "message.6": "{NARRATION}{CENTER}{01F}{009}{001} {006}{TIMED_CLOSE 243}{CLOSE}{END}",
    }
