from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening


def _fixture_source(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    for name in ("data/text/common.asm", "engine/menus/intro_menu.asm"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / "data/text/common.asm").write_text(
        'SECTION "_ElmText1", ROMX\n'
        '_ElmText1::\n\ttext "Hello!"\n\tprompt\n\n'
        'SECTION "_ElmText2", ROMX\n_ElmText2::\n\ttext "Original"\n\tdone\n',
        encoding="utf-8",
    )
    (root / "engine/menus/intro_menu.asm").write_text(
        "ProfElmSpeech:\n\tld hl, ElmText1\n\tcall PrintText\n\tret\n",
        encoding="utf-8",
    )
    (root / "gfx/font").mkdir(parents=True)
    (root / "gfx/font/normal.1bpp").write_bytes(bytes(114 * 8))
    return root


def _fake_assets():
    codes = tuple((0x7F,) * opening.COLUMNS for _ in opening.OPENING_LINES)
    images = tuple(Image.new("1", (opening.COLUMNS * 8, 8)) for _ in opening.OPENING_LINES)
    return opening.ElmArabicAssets(bytes(114 * 8), codes, images, 0)


def test_intro_raw_bytecode_preserves_line_and_paragraph_controls():
    asm = opening._opening_asm(_fake_assets().codes)
    assert asm.count('db "<LINE>"') == 3
    assert asm.count('db "<PARA>"') == 3
    assert asm.count('db "<PROMPT>"') == 1
    assert asm.count("text_start") == 1
    assert asm.index("if !DEF(DEBUG)") > asm.index('db "<LINE>"')
    assert asm.index("endc") < asm.index('db "<PROMPT>"')
    assert "أهلًا" not in asm  # RGBDS receives tile codes, never Unicode Arabic


def test_injects_original_font_switch_without_touching_other_texts(tmp_path, monkeypatch):
    source = _fixture_source(tmp_path)
    pinned = {
        path: opening._git_blob_sha((source / path).read_bytes()) for path in opening.SOURCE_FILES
    }
    monkeypatch.setattr(opening, "SOURCE_FILES", pinned)
    monkeypatch.setattr(opening, "_verify_upstream", lambda path: None)
    monkeypatch.setattr(opening, "make_assets", lambda source, font: _fake_assets())
    preview = tmp_path / "preview.png"
    result = opening.prepare(source, tmp_path / "unused-font.ttf", preview)
    intro = (source / "engine/menus/intro_menu.asm").read_text(encoding="utf-8")
    common = (source / "data/text/common.asm").read_text(encoding="utf-8")
    assert result["scope"] == "ElmText1 only"
    assert result["playable_verified"] is False
    assert result["dynamic_arabic"] is False
    assert "farcall ClassicRetroPrintArabicElm" in intro
    assert "jmp LoadStandardFont" in common
    assert "call GetMaybeOpaque1bpp" in common
    assert "call FarCall_de" in common
    assert "BANK(ElmText1)" in common
    assert "ClassicRetroArabicElmFont::" in common
    assert '\ttext "Original"' in common
    assert (source / opening.OUTPUT_FONT).stat().st_size == 912
    assert preview.is_file()


def test_refuses_changes_to_pinned_source_before_writing(tmp_path, monkeypatch):
    source = _fixture_source(tmp_path)
    monkeypatch.setattr(opening, "_verify_upstream", lambda path: None)
    with pytest.raises(ClassicRetroError) as caught:
        opening.prepare(source, tmp_path / "missing.ttf")
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert not (source / opening.OUTPUT_FONT).exists()


def test_rejects_missing_prebuilt_english_font(tmp_path):
    source = _fixture_source(tmp_path)
    (source / "gfx/font/normal.1bpp").unlink()
    with pytest.raises(ClassicRetroError) as caught:
        opening.make_assets(source, tmp_path / "missing.ttf")
    assert caught.value.code is ErrorCode.FONT_BUILD_FAILED


def test_actual_rtl_font_atlas_preserves_original_unused_codes(tmp_path, reference_font):
    source = _fixture_source(tmp_path)
    native = bytes((i * 13) % 256 for i in range(114 * 8))
    (source / "gfx/font/normal.1bpp").write_bytes(native)
    assets = opening.make_assets(source, reference_font)
    assert len(assets.tiles) == len(native)
    assert 0 < assets.used_glyphs <= opening.LAST_ARABIC_CODE - opening.FIRST_ARABIC_CODE + 1
    assert len(assets.codes) == len(opening.OPENING_LINES)
    assert all(len(row) == 18 for row in assets.codes)
    # The font's last glyphs, including the ▼ continuation marker, were not overwritten.
    protected = (opening.LAST_ARABIC_CODE + 1 - opening.FIRST_ARABIC_CODE) * 8
    assert assets.tiles[protected:] == native[protected:]
    # Every cell displayed by the game reconstructs the exact shaped image.
    for image, line in zip(assets.images, assets.codes, strict=True):
        for x, code in enumerate(line):
            observed = (
                bytes(8)
                if code == 0x7F
                else assets.tiles[(code - 0x80) * 8 : (code - 0x80 + 1) * 8]
            )
            assert opening._tile_bytes(image, x) == observed
