from __future__ import annotations

from pathlib import Path

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening
from classic_retro.source import polishedcrystal_showtext as patch


def _scene(
    name: str, *, scene_id: str = "ST01", dynamic: bool = False, calls: int = 1
) -> patch.OverworldScene:
    return patch.OverworldScene(
        scene_id,
        "maps/ElmsLab.asm",
        name,
        calls,
        dynamic,
        (("line" if dynamic else "text", "مرحبًا"),),
    )


def _assets(*codes: int) -> opening.ElmArabicAssets:
    image = bytearray(opening.FONT_TILES * 8)
    for code in codes:
        image[(code - 0x80) * 8 : (code - 0x80 + 1) * 8] = bytes((code - 0x7F,)) * 8
    return opening.ElmArabicAssets(bytes(image), (tuple(codes),), (), len(codes))


def test_curated_translation_files_contain_stable_validated_entries():
    pins, scenes = patch.load_scenes()
    assert set(pins) == {"maps/ElmsLab.asm", "maps/NewBarkTown.asm"}
    assert len(scenes) == 12
    assert sum(len(scene.lines) for scene in scenes) == 72
    assert len({(scene.file, scene.label) for scene in scenes}) == len(scenes)
    assert sum(scene.player_name for scene in scenes) >= 3
    assert all(scene.calls == 1 for scene in scenes)


def test_original_control_check_rejects_hidden_asm_and_dropped_player_name():
    scene = _scene("MyText")
    original = 'MyText:\n\ttext "Hello."\n\tline "Hello again."\n\tdone\nOther:\n\tend\n'
    patch.verify_original(original, scene)
    with pytest.raises(ClassicRetroError) as rejected:
        patch.verify_original(
            'MyText:\n\ttext "Hello."\n\ttext_ram wStringBuffer1\n\tdone\n', scene
        )
    assert rejected.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH

    dynamic = _scene("MyText", dynamic=True)
    with pytest.raises(ClassicRetroError) as rejected:
        patch.verify_original(original, dynamic)
    assert rejected.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    patch.verify_original('MyText:\n\ttext "Hi, <PLAYER>!"\n\tdone\n', dynamic)
    with pytest.raises(ClassicRetroError) as rejected:
        patch.verify_original('MyText:\n\ttext "Use <RIVAL>!"\n\tdone\n', scene)
    assert rejected.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_shared_bitmap_atlas_packing_is_deterministic_and_preserves_name_cells():
    first = _scene("Alpha", scene_id="ST01")
    second = _scene("Beta", scene_id="ST02")
    dynamic = _scene("Gamma", scene_id="ST03", dynamic=True)
    images = ((first, _assets(0x80, 0x81)), (second, _assets(0x80)), (dynamic, _assets(0xD0)))
    groups, remapped = patch.pack_atlases(images)
    assert len(groups) == 2
    assert groups[0] is remapped[0].atlas is remapped[1].atlas
    assert groups[1] is remapped[2].atlas
    assert len(groups[0].glyphs) == 2
    assert len(groups[1].glyphs) == 1
    assert remapped[0].codes == ((0x80, 0x81),)
    assert remapped[1].codes == ((0x80,),)
    assert remapped[2].codes == ((0xD0,),)
    assert groups[0].filename != groups[1].filename


def test_long_dynamic_text_becomes_name_page_plus_short_regular_pages():
    original = patch.OverworldScene(
        "ST12",
        "maps/ElmsLab.asm",
        "ElmAfterTicketText",
        1,
        True,
        (
            ("line", "أهلًا"),
            ("para", "رسالة أولى"),
            ("line", "جملة أخرى"),
            ("para", "الجزء الثاني"),
            ("line", "ثم التالية"),
            ("para", "والأخيرة"),
        ),
    )
    pages = patch.pages_for(original)
    assert len(pages) == 3
    assert [len(page.lines) for page in pages] == [1, 4, 1]
    assert [page.player_name for page in pages] == [True, False, False]
    assert pages[0].label == "ElmAfterTicketText"
    assert pages[1].label == "ClassicRetroST12Page2"
    assert pages[0].ending == pages[1].ending == "<PROMPT>"
    assert pages[2].ending == "<DONE>"
    assert pages[1].lines[0][0] == "text"


def test_showtext_rewrite_preserves_game_script_command_sequence():
    scene = _scene("MyText", calls=2)
    group = patch.Atlas(1, False, {})
    rendered = patch.RenderedScene(scene, group, ((0x80,),))
    text = "Talk1:\n\tshowtext MyText\n\tend\nTalk2:\n\tshowtext MyText\n\tend\n"
    changed = patch._replace_event_calls(text, scene, (rendered,))
    assert changed.count("\topentext\n") == 2
    assert changed.count("\tcallasm ClassicRetroSTA01Load\n") == 2
    assert changed.count("\twritetext MyText\n") == 2
    assert changed.count("\twaitbutton\n") == 2
    assert changed.count("\tcallasm ClassicRetroSTRestoreFont\n") == 2
    assert changed.count("\tclosetext\n") == 2
    with pytest.raises(ClassicRetroError):
        patch._replace_event_calls("\tshowtext MyText\n", scene, (rendered,))


def _synthetic_source(tmp_path: Path):
    root = tmp_path / "source"
    (root / "maps").mkdir(parents=True)
    (root / "data/text").mkdir(parents=True)
    (root / "gfx/font").mkdir(parents=True)
    (root / "maps/ElmsLab.asm").write_bytes(
        b'Talk:\n\tshowtext HelloText\n\tend\nHelloText:\n\ttext "Welcome, <PLAYER>!"\n\tdone\n'
    )
    (root / "maps/NewBarkTown.asm").write_bytes(b"Empty:\n\tend\n")
    (root / "data/text/common.asm").write_bytes(b'SECTION "Original", ROMX\n')
    (root / "gfx/font/normal.1bpp").write_bytes(bytes(912))
    return root


def test_generate_shared_atlases_into_pending_changes_without_mutating_source(
    tmp_path, monkeypatch
):
    root = _synthetic_source(tmp_path)
    labels = (_scene("HelloText", scene_id="ST01", dynamic=True),)
    pins = {
        "maps/ElmsLab.asm": opening._git_blob_sha((root / "maps/ElmsLab.asm").read_bytes()),
        "maps/NewBarkTown.asm": opening._git_blob_sha((root / "maps/NewBarkTown.asm").read_bytes()),
    }
    monkeypatch.setattr(patch, "load_scenes", lambda: (pins, labels))
    monkeypatch.setattr(
        opening,
        "make_assets",
        lambda source, font, lines, *, code_pool=None: opening.ElmArabicAssets(
            bytes(912), ((0x7F,),), (), 0
        ),
    )
    pending = {root / "data/text/common.asm": (root / "data/text/common.asm").read_bytes()}
    updated, report = patch.augment(root, root / "unused.ttf", pending)
    assert report["scenes"] == 1
    assert report["live_name_scenes"] == 1
    assert report["arabic_lines"] == 1
    assert report["source_verified"] is True
    assert report["shared_atlases"] == 1
    assert report["gameplay_verified"] is False
    changed = updated[root / "maps/ElmsLab.asm"].decode()
    assert "<PLAYER>" in changed
    assert "ClassicRetroSTA01Load" in changed
    assert "\tshowtext HelloText\n" not in changed
    assert (root / "maps/ElmsLab.asm").read_bytes().startswith(b"Talk:\n\tshowtext")
    assert (root / "gfx/font/classic_retro_showtext_a01.1bpp") in updated
    assert updated[root / "data/text/common.asm"].decode().count("ClassicRetroSTRestoreFont") == 1


def test_invalid_source_pin_leaves_all_files_unchanged(tmp_path, monkeypatch):
    root = _synthetic_source(tmp_path)
    monkeypatch.setattr(
        patch,
        "load_scenes",
        lambda: ({"maps/ElmsLab.asm": "0" * 40}, (_scene("HelloText"),)),
    )
    before = (root / "maps/ElmsLab.asm").read_bytes()
    with pytest.raises(ClassicRetroError) as rejected:
        patch.augment(root, root / "unused.ttf", {})
    assert rejected.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    assert (root / "maps/ElmsLab.asm").read_bytes() == before
