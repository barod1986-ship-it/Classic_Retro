from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_elm_dynamic as dynamic
from classic_retro.source import polishedcrystal_opening as opening


def _fake_source(tmp_path):
    root = tmp_path / "source"
    (root / "gfx/font").mkdir(parents=True)
    (root / "data/text").mkdir(parents=True)
    (root / "engine/menus").mkdir(parents=True)
    native = bytes((i * 17) % 256 for i in range(opening.FONT_TILES * 8))
    (root / "gfx/font/normal.1bpp").write_bytes(native)
    (root / "data/text/common.asm").write_text('SECTION "Other", ROMX\n')
    (root / "engine/menus/intro_menu.asm").write_text(
        "ProfElmSpeech:\n\tld hl, ElmText7\n\tjmp PrintText\n"
    )
    return root


def _pending_changes(root):
    return {
        root / "data/text/common.asm": (root / "data/text/common.asm").read_bytes(),
        root / "engine/menus/intro_menu.asm": (root / "engine/menus/intro_menu.asm").read_bytes(),
    }


def test_arabic_dynamic_intro_keeps_runtime_name_and_divides_into_pages():
    assert len(dynamic.PAGES) == 4
    assert dynamic.PAGES[0].dynamic_player is True
    assert not any(page.dynamic_player for page in dynamic.PAGES[1:])
    assert not any(c in dynamic.NAME_SAFE_POOL for c in range(0x80, 0xBA))
    page = dynamic.PAGES[0]
    glyphs = tuple((0xD0,) * opening.COLUMNS for _ in page.lines)
    assets = opening.ElmArabicAssets(bytes(912), glyphs, (), 1)
    assembler = dynamic._asm_page(page, assets)
    assert assembler.index('db "<PLAYER>"') < assembler.index('db "<LINE>"')
    assert assembler.count('db "<PLAYER>"') == 1
    assert assembler.count('db "<PROMPT>"') == 1
    assert "هل أنت مستعد" not in assembler
    assert 'farcall ClassicRetroPrintElm7Ready' in dynamic._asm_caller()


def test_all_dynamic_pages_compose_into_unique_memory_banks(tmp_path, monkeypatch):
    root = _fake_source(tmp_path)
    original = _pending_changes(root)
    source_atlas = (root / "gfx/font/normal.1bpp").read_bytes()

    def fake_assets(source, font, lines, *, code_pool=None):
        # All nonempty Arabic cells would reside inside code_pool. For the
        # fixture, provide the unmodified original font atlas.
        assert code_pool == dynamic.NAME_SAFE_POOL or code_pool is None
        return opening.ElmArabicAssets(
            source_atlas,
            tuple((0x7F,) * opening.COLUMNS for _ in lines),
            (),
            0,
        )

    monkeypatch.setattr(opening, "make_assets", fake_assets)
    generated, report = dynamic.augment(root, root / "font.ttf", original)
    assert len(generated) == 6
    assert report["pages"] == 4
    assert report["translated_lines"] == 11
    assert report["dynamic_player_name"] is True
    assert report["latin_name_preserved"] is True
    intro = generated[root / "engine/menus/intro_menu.asm"].decode("utf-8")
    common = generated[root / "data/text/common.asm"].decode("utf-8")
    assert "farjp ClassicRetroElm7Sequence" in intro
    assert "\tjmp PrintText" not in intro
    assert common.count("call FarCall_de") == 4
    assert '<PLAYER>' in common
    for page in dynamic.PAGES:
        name = "classic_retro_elm7_" + page.label.lower() + ".1bpp"
        assert (root / "gfx/font" / name) in generated
    # Does not write any source file; existing callers control atomic writes.
    assert (root / "engine/menus/intro_menu.asm").read_bytes() == original[
        root / "engine/menus/intro_menu.asm"
    ]


def test_dynamic_augmentation_rejects_unexpected_tail_before_build(tmp_path):
    root = _fake_source(tmp_path)
    patches = _pending_changes(root)
    patches[root / "engine/menus/intro_menu.asm"] = b"\tret\n"
    with pytest.raises(ClassicRetroError) as exc:
        dynamic.augment(root, root / "font.ttf", patches)
    assert exc.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert not list((root / "gfx/font").glob("classic_retro_*"))


def test_sparse_arabic_atlas_keeps_native_ascii(tmp_path, reference_font):
    root = _fake_source(tmp_path)
    native = (root / "gfx/font/normal.1bpp").read_bytes()
    page = dynamic.PAGES[0]
    result = opening.make_assets(root, reference_font, page.lines, code_pool=dynamic.NAME_SAFE_POOL)
    assert 0 < result.used_glyphs <= len(dynamic.NAME_SAFE_POOL)
    assert all(value in dynamic.NAME_SAFE_POOL or value == 0x7F for row in result.codes for value in row)
    for code in range(0x80, 0xBA):
        low = (code - 0x80) * 8
        assert result.tiles[low : low + 8] == native[low : low + 8]
