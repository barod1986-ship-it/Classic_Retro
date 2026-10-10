from __future__ import annotations

import pytest
from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_elm_sequence as seq
from classic_retro.source import polishedcrystal_opening as opening


def _assets(lines):
    codes = tuple((0x7F,) * opening.COLUMNS for _ in lines)
    images = tuple(Image.new("1", (opening.COLUMNS * 8, 8)) for _ in lines)
    return opening.ElmArabicAssets(bytes(114 * 8), codes, images, 0)


def _fixture(tmp_path):
    source = tmp_path / "source"
    (source / "data/text").mkdir(parents=True)
    (source / "engine/menus").mkdir(parents=True)
    (source / "gfx/font").mkdir(parents=True)
    extra = ''.join(
        'SECTION "' + scene.source_label + '", ROMX\n'
        + scene.source_label + '::\n'
        + '\ttext "English"\n\tprompt\n\n'
        for scene in seq.SCENES
    )
    (source / "data/text/common.asm").write_text(
        'SECTION "_ElmText1", ROMX\n'
        '_ElmText1::\n\ttext "Hello"\n\tprompt\n\n'
        + extra,
        encoding="utf-8",
    )
    (source / "engine/menus/intro_menu.asm").write_text(
        'ProfElmSpeech:\n\tld hl, ElmText1\n\tcall PrintText\n'
        + ''.join(
            '\tld hl, ' + scene.caller_label + '\n\tcall PrintText\n'
            for scene in seq.SCENES
        ),
        encoding="utf-8",
    )
    (source / "gfx/font/normal.1bpp").write_bytes(bytes(912))
    return source


def test_scene_bytecode_matches_exact_exit_controls():
    assert len(seq.SCENES) == 6
    assert seq.SCENES[0].ending == ("@", "@")
    for scene in seq.SCENES:
        output = seq._asm_for_scene(scene, _assets(scene.lines))
        assert output.count("\ttext_start") == 1
        assert output.count("\tdb $7f") == len(scene.lines)
        for terminator in scene.ending:
            assert '\tdb "' + terminator + '"' in output
        assert "البوكيمون" not in output


def test_fails_safely_on_ambiguous_text_sections():
    scene = seq.SCENES[0]
    with pytest.raises(ClassicRetroError) as caught:
        seq._replace_section('SECTION "Else", ROMX\n', scene, _assets(scene.lines))
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    with pytest.raises(ClassicRetroError):
        seq._replace_caller("ProfElmSpeech:\n\tret\n", scene)


def test_multi_dialogue_overlay_preserves_dynamic_player_and_font(tmp_path, monkeypatch):
    source = _fixture(tmp_path)
    originals = {
        name: opening._git_blob_sha((source / name).read_bytes())
        for name in opening.SOURCE_FILES
    }
    monkeypatch.setattr(opening, "SOURCE_FILES", originals)
    monkeypatch.setattr(seq, "_verify_upstream", lambda p: None)
    monkeypatch.setattr(
        opening,
        "make_assets",
        lambda source, font, lines=opening.OPENING_LINES: _assets(lines),
    )
    preview = tmp_path / "proof.png"
    report = seq.prepare(source, tmp_path / "test.ttf", preview)
    assert report["source_scenes"] == 7
    assert report["arabic_lines"] == 31
    assert report["full_game_translated"] is False
    assert report["untranslated_dynamic_message"] == "_ElmText7"
    assert preview.is_file()
    common = (source / "data/text/common.asm").read_text(encoding="utf-8")
    intro = (source / "engine/menus/intro_menu.asm").read_text(encoding="utf-8")
    assert common.count("ClassicRetroArabicElm2Font::") == 1
    assert len(list((source / "gfx/font").glob("classic_retro_*.1bpp"))) == 7
    assert intro.count("farcall ClassicRetroPrint") == 7
    assert intro.count("\tcall PrintText") == 0
    # Re-running must reject changes rather than corrupting source or overwrite assets.
    with pytest.raises(ClassicRetroError) as caught:
        seq.prepare(source, tmp_path / "test.ttf")
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH


def test_refuses_unverified_source_before_modifying(tmp_path, monkeypatch):
    source = _fixture(tmp_path)
    monkeypatch.setattr(seq, "_verify_upstream", lambda p: None)
    with pytest.raises(ClassicRetroError) as caught:
        seq.prepare(source, tmp_path / "missing.ttf")
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert not (source / opening.OUTPUT_FONT).exists()
