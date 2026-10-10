"""First Arabic overworld dialogs, preserving Polished Crystal script engine behavior.

The showtext instruction calls opentext which reloads Latin glyphs. Each
selected event is expanded into an equivalent sequence where the temporary
Arabic atlas is loaded *after* opentext and restored before closetext.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening

MAP_PATH = "maps/NewBarkTown.asm"
MAP_BLOB_SHA = "76a556311a4aadcd016fbd38418ee447c5147caf"
NAME_SAFE_POOL = (*range(0xD0, 0xE0), 0xEA, 0xEB)


@dataclass(frozen=True)
class TownScene:
    label: str
    lines: tuple[tuple[str, str], ...]
    call_count: int
    dynamic_player: bool = False


SCENES = (
    TownScene(
        "NewBarkTownRivalText1",
        (
            ("text", "إذًا هذا مختبر"),
            ("line", "البوكيمون الشهير"),
            ("cont", "للأستاذ إلم..."),
        ),
        1,
    ),
    TownScene(
        "NewBarkTownRivalText2",
        (
            ("text", "ماذا؟ ولماذا"),
            ("line", "تحدق بي هكذا؟"),
        ),
        1,
    ),
    TownScene("Text_WaitPlayer", (("line", "انتظر قليلًا!"),), 2, dynamic_player=True),
    TownScene(
        "Text_WhatDoYouThinkYoureDoing",
        (("text", "ما الذي تحاول"), ("line", "فعله الآن؟")),
        2,
    ),
    TownScene(
        "Text_ItsDangerousToGoAlone",
        (
            ("text", "الخروج وحدك"),
            ("line", "أمر خطير!"),
            ("cont", "من دون بوكيمون!"),
            ("para", "على الطريق"),
            ("line", "إلى البلدة"),
            ("para", "يقفز بوكيمون"),
            ("line", "بري من العشب!"),
        ),
        2,
    ),
)


def _text(scene: TownScene, asset: opening.ElmArabicAssets) -> str:
    result = [scene.label + ":", "\ttext_start"]
    if scene.dynamic_player:
        result.append('\tdb "<PLAYER>"')
    controls = {"line": "<LINE>", "cont": "<CONT>", "para": "<PARA>"}
    for (directive, _), row in zip(scene.lines, asset.codes, strict=True):
        if directive != "text":
            code = controls.get(directive)
            if code is None:
                raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, directive)
            result.append(f'\tdb "{code}"')
        result.append("\tdb " + ", ".join("$" + format(byte, "02x") for byte in row))
    return "\n".join((*result, '\tdb "<DONE>"', "", ""))


def _replace_text(source: str, scene: TownScene, asset: opening.ElmArabicAssets) -> str:
    regex = re.compile(
        r"^" + re.escape(scene.label) + r":\n.*?(?=^[A-Za-z_][A-Za-z0-9_]*:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    found = list(regex.finditer(source))
    if len(found) != 1 or "\tdone" not in found[0].group():
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"unexpected source block: {scene.label}"
        )
    match = found[0]
    return source[: match.start()] + _text(scene, asset) + source[match.end() :]


def _font_loader(scene: TownScene) -> str:
    label = "ClassicRetroNewBark" + scene.label + "Font"
    loader = "ClassicRetroLoad" + scene.label
    font = "gfx/font/classic_retro_newbark_" + scene.label.lower() + ".1bpp"
    return "\n".join(
        (
            f'SECTION "{label} Data", ROMX',
            f"{label}::",
            f'\tINCBIN "{font}"',
            f'SECTION "{label} Loader", ROMX',
            f"{loader}::",
            f"\tld de, {label}",
            "\tld hl, vTiles0 tile 'A'",
            f"\tlb bc, BANK({label}), 114",
            "\txor a",
            "\tldh [hRequestOpaque1bpp], a",
            "\tjmp GetMaybeOpaque1bpp",
            "",
        )
    )


def _replace_dialogue_calls(source: str, scene: TownScene) -> str:
    original = "\tshowtext " + scene.label + "\n"
    if source.count(original) != scene.call_count:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{scene.label} calls {source.count(original)} (expected {scene.call_count})",
        )
    replacement = (
        "\topentext\n"
        + "\tcallasm ClassicRetroLoad"
        + scene.label
        + "\n"
        + "\twritetext "
        + scene.label
        + "\n"
        + "\twaitbutton\n"
        + "\tcallasm ClassicRetroRestoreNewBarkFont\n"
        + "\tclosetext\n"
    )
    return source.replace(original, replacement)


def augment(
    source: Path, font: Path, changes: dict[Path, bytes]
) -> tuple[dict[Path, bytes], dict[str, object]]:
    """Source-pinned map edits plus atlas assets, committed atomically by caller."""
    source = Path(source)
    map_path = source / MAP_PATH
    if not map_path.is_file() or opening._git_blob_sha(map_path.read_bytes()) != MAP_BLOB_SHA:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "unexpected New Bark Town source")
    common_path = source / "data/text/common.asm"
    if common_path not in changes:
        raise ClassicRetroError(ErrorCode.INVALID_REFERENCE, "missing pending font-bank changes")
    map_text = map_path.read_text(encoding="utf-8")
    common = changes[common_path].decode("utf-8")
    patches = dict(changes)
    counts: dict[str, int] = {}
    for scene in SCENES:
        assets = opening.make_assets(
            source,
            font,
            scene.lines,
            code_pool=NAME_SAFE_POOL if scene.dynamic_player else None,
        )
        if scene.dynamic_player:
            native = (source / "gfx/font/normal.1bpp").read_bytes()
            for code in range(0x80, 0xBA):
                start = (code - 0x80) * 8
                if assets.tiles[start : start + 8] != native[start : start + 8]:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED, "player name letters overwritten"
                    )
        binary_path = source / ("gfx/font/classic_retro_newbark_" + scene.label.lower() + ".1bpp")
        if binary_path.exists() or binary_path in patches:
            raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"font exists: {binary_path}")
        map_text = _replace_dialogue_calls(map_text, scene)
        map_text = _replace_text(map_text, scene, assets)
        common += "\n" + _font_loader(scene)
        patches[binary_path] = assets.tiles
        counts[scene.label] = assets.used_glyphs
    common += "\n".join(
        (
            'SECTION "Classic Retro New Bark Font Restore", ROMX',
            "ClassicRetroRestoreNewBarkFont::",
            "\tjmp LoadStandardFont",
            "",
        )
    )
    patches[common_path] = common.encode("utf-8")
    patches[map_path] = map_text.encode("utf-8")
    return patches, {
        "scenes": len(SCENES),
        "arabic_lines": sum(len(s.lines) for s in SCENES),
        "dynamic_player_name": True,
        "font_glyphs": counts,
        "script_calls": sum(s.call_count for s in SCENES),
        "global_font_patched": False,
        "gameplay_verified": False,
    }
