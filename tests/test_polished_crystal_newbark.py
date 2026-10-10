from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_newbark as town
from classic_retro.source import polishedcrystal_opening as opening


def _source(tmp_path):
    root = tmp_path / "source"
    (root / "maps").mkdir(parents=True)
    (root / "data/text").mkdir(parents=True)
    (root / "gfx/font").mkdir(parents=True)
    code = "NewBarkTown_TeacherStopsYouTrigger1:\n"
    for label in ("Text_WaitPlayer", "Text_WhatDoYouThinkYoureDoing", "Text_ItsDangerousToGoAlone"):
        code += "\tshowtext " + label + "\n"
    code += "NewBarkTown_TeacherStopsYouTrigger2:\n"
    for label in ("Text_WaitPlayer", "Text_WhatDoYouThinkYoureDoing", "Text_ItsDangerousToGoAlone"):
        code += "\tshowtext " + label + "\n"
    code += "NewBarkTownRivalScript:\n"
    for label in ("NewBarkTownRivalText1", "NewBarkTownRivalText2"):
        code += "\tshowtext " + label + "\n"
    code += "RemainingScript:\n\tend\n"
    for scene in town.SCENES:
        code += scene.label + ':\n\ttext "English"\n\tdone\n'
    (root / "maps/NewBarkTown.asm").write_text(code)
    (root / "data/text/common.asm").write_text('SECTION "Other", ROMX\n')
    (root / "gfx/font/normal.1bpp").write_bytes(bytes(912))
    return root


def _fake_asset(lines, original):
    return opening.ElmArabicAssets(
        original,
        tuple((0x7F,) * 18 for _ in lines),
        (),
        0,
    )


def test_new_bark_text_is_uncompressed_and_respects_gbc_commands():
    assert len(town.SCENES) == 5
    assert sum(scene.call_count for scene in town.SCENES) == 8
    assert sum(len(scene.lines) for scene in town.SCENES) == 15
    for scene in town.SCENES:
        result = town._text(scene, _fake_asset(scene.lines, bytes(912)))
        assert result.startswith(scene.label + ":\n\ttext_start")
        assert result.endswith('\tdb "<DONE>"\n\n')
        assert "\tdb " in result
        assert all(letter not in result for letter in ("البلدة", "العشب"))


def test_map_dialogue_swaps_font_after_opentext_and_preserves_wait(tmp_path, monkeypatch):
    root = _source(tmp_path)
    code = (root / town.MAP_PATH).read_bytes()
    monkeypatch.setattr(town, "MAP_BLOB_SHA", opening._git_blob_sha(code))
    monkeypatch.setattr(
        opening,
        "make_assets",
        lambda source, font, lines, *, code_pool=None: _fake_asset(
            lines, (root / "gfx/font/normal.1bpp").read_bytes()
        ),
    )
    initial = {
        root / "data/text/common.asm": (root / "data/text/common.asm").read_bytes(),
    }
    patches, report = town.augment(root, root / "font.ttf", initial)
    assert report["scenes"] == 5 and report["arabic_lines"] == 15
    assert report["script_calls"] == 8 and report["gameplay_verified"] is False
    changed = patches[root / town.MAP_PATH].decode()
    assert "\tshowtext Text_WaitPlayer\n" not in changed
    assert changed.count("\topentext\n") == 8
    assert changed.count("\tcallasm ClassicRetroRestoreNewBarkFont\n") == 8
    assert changed.count("\tclosetext\n") == 8
    assert changed.count("\twaitbutton\n") == 8
    assert changed.count("\tcallasm ClassicRetroLoadText_WaitPlayer\n") == 2
    assert '\tdb "<PLAYER>"' in changed
    assert "RemainingScript:\n\tend\n" in changed
    assert (root / town.MAP_PATH).read_bytes() == code
    assert len(patches) == 7


def test_town_patch_rejects_drift_and_does_not_modify_disk(tmp_path):
    root = _source(tmp_path)
    original = (root / town.MAP_PATH).read_bytes()
    with pytest.raises(ClassicRetroError) as error:
        town.augment(root, root / "font.ttf", {root / "data/text/common.asm": b""})
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert (root / town.MAP_PATH).read_bytes() == original


def test_source_rejects_wrong_call_count(tmp_path):
    source = "\tshowtext Text_WaitPlayer\n"
    with pytest.raises(ClassicRetroError) as error:
        town._replace_dialogue_calls(source, town.SCENES[2])
    assert error.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
