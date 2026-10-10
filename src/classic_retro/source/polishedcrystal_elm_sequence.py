"""Second Polished Crystal Arabic proof: all *static* intro dialogs around professor Elm.

Each message is given its own temporary, RAQM-shaped 1bpp font atlas. Original
text graphics are restored on exit. Dynamic PLAYER text in ElmText7 is deliberately
left untouched until an inline mixed-script renderer has been implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening
from classic_retro.source.polishedcrystal_catalog import _verify_upstream


@dataclass(frozen=True)
class Scene:
    source_label: str
    caller_label: str
    font_label: str
    output_font: str
    lines: tuple[tuple[str, str], ...]
    ending: tuple[str, ...]


SCENES = (
    Scene(
        "_ElmText2",
        "ElmText2",
        "ClassicRetroArabicElm2Font",
        "gfx/font/classic_retro_arabic_elm2.1bpp",
        (
            ("text", "هذا العالم مأهول"),
            ("line", "بمخلوقات غريبة"),
            ("cont", "نسميها جميعًا"),
            ("cont", "البوكيمون."),
        ),
        ("@", "@"),
    ),
    Scene(
        "_ElmText4",
        "ElmText4",
        "ClassicRetroArabicElm4Font",
        "gfx/font/classic_retro_arabic_elm4.1bpp",
        (
            ("text", "يعيش الناس"),
            ("line", "والبوكيمون معًا"),
            ("para", "ويتعاون الجميع"),
            ("line", "فيما بينهم."),
            ("para", "بعضهم يلعب"),
            ("line", "مع البوكيمون"),
            ("cont", "والبعض يقاتل."),
        ),
        ("<PROMPT>",),
    ),
    Scene(
        "_ElmText5",
        "ElmText5",
        "ClassicRetroArabicElm5Font",
        "gfx/font/classic_retro_arabic_elm5.1bpp",
        (
            ("text", "لكن أسرار"),
            ("line", "البوكيمون كثيرة"),
            ("cont", "لم نكتشفها بعد."),
            ("para", "ما زال أمامنا"),
            ("line", "الكثير من"),
            ("cont", "الألغاز."),
            ("para", "لهذا أدرس"),
            ("line", "البوكيمون دائمًا."),
        ),
        ("<PROMPT>",),
    ),
    Scene(
        "_ElmText6",
        "ElmText6",
        "ClassicRetroArabicElm6Font",
        "gfx/font/classic_retro_arabic_elm6.1bpp",
        (
            ("text", "أخبرني لو سمحت"),
            ("line", "ما اسمك؟"),
        ),
        ("<PROMPT>",),
    ),
    Scene(
        "Text_AreYouABoyOrAreYouAGirl",
        "AreYouABoyOrAreYouAGirlText",
        "ClassicRetroArabicGenderFont",
        "gfx/font/classic_retro_arabic_gender.1bpp",
        (
            ("text", "أي صورة تريدها"),
            ("line", "على بطاقة مدربك؟"),
        ),
        ("<DONE>",),
    ),
    Scene(
        "Text_SoThisIsYou",
        "SoThisIsYouText",
        "ClassicRetroArabicConfirmFont",
        "gfx/font/classic_retro_arabic_confirm.1bpp",
        (("text", "هل هذه صورتك؟"),),
        ("<DONE>",),
    ),
)


def _asm_for_scene(scene: Scene, assets: opening.ElmArabicAssets) -> str:
    """Preserve each upstream dialogue's control-flow skeleton and exit tokens."""
    if len(scene.lines) != len(assets.codes):
        raise ClassicRetroError(ErrorCode.SOURCE_PATCH_FAILED, "line count mismatch")
    output = [
        'SECTION "' + scene.source_label + '", ROMX',
        scene.source_label + "::",
        "\ttext_start",
    ]
    controls = {
        "line": "<LINE>",
        "cont": "<CONT>",
        "para": "<PARA>",
        "next": "<NEXT>",
    }
    for (directive, _), codes in zip(scene.lines, assets.codes, strict=True):
        if directive != "text":
            control = controls.get(directive)
            if control is None:
                raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, directive)
            output.append('\tdb "' + control + '"')
        output.append("\tdb " + ", ".join("$" + format(byte, "02x") for byte in codes))
    for terminator in scene.ending:
        output.append('\tdb "' + terminator + '"')
    output.extend(("", ""))
    return "\n".join(output)


def _replace_section(source: str, scene: Scene, assets: opening.ElmArabicAssets) -> str:
    regex = re.compile(
        r'^SECTION "' + re.escape(scene.source_label) + r'", ROMX\n.*?(?=^SECTION |\Z)',
        flags=re.M | re.S,
    )
    matches = list(regex.finditer(source))
    if len(matches) != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "expected one dialogue section: " + scene.source_label,
        )
    before = matches[0].group()
    if scene.source_label + "::" not in before:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "missing source label " + scene.source_label,
        )
    return source[: matches[0].start()] + _asm_for_scene(scene, assets) + source[matches[0].end() :]


def _font_sections(scene: Scene) -> str:
    """Banked font and transient loader, avoiding the already full ROM bank 1."""
    loader = "ClassicRetroPrint" + scene.caller_label
    marker = scene.font_label
    lines = (
        "",
        f'SECTION "{marker} Data", ROMX',
        f"{marker}::",
        f'\tINCBIN "{scene.output_font}"',
        "",
        f'SECTION "{marker} Loader", ROMX',
        f"{loader}::",
        "\tpush hl",
        f"\tld de, {marker}",
        "\tld hl, vTiles0 tile 'A'",
        f"\tlb bc, BANK({marker}), 114",
        "\txor a",
        "\tldh [hRequestOpaque1bpp], a",
        "\tcall GetMaybeOpaque1bpp",
        "\tpop hl",
        f"\tld a, BANK({scene.caller_label})",
        "\tld de, PrintText",
        "\tcall FarCall_de",
        "\tjmp LoadStandardFont",
        "",
    )
    return "\n".join(lines)


def _replace_caller(intro: str, scene: Scene) -> str:
    before = f"\tld hl, {scene.caller_label}\n\tcall PrintText\n"
    after = f"\tld hl, {scene.caller_label}\n\tfarcall ClassicRetroPrint{scene.caller_label}\n"
    if intro.count(before) != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "missing/duplicate intro call: " + scene.caller_label,
        )
    return intro.replace(before, after)


def prepare(
    source: Path,
    font: Path,
    preview: Path | None = None,
    *,
    dynamic_player: bool = False,
    new_bark_town: bool = False,
) -> dict[str, object]:
    """Build one source overlay for all static intro scenes from untouched v3.2.3."""
    source = Path(source).expanduser().resolve()
    font = Path(font).expanduser().resolve()
    _verify_upstream(source)
    for name, digest in opening.SOURCE_FILES.items():
        path = source / name
        if opening._git_blob_sha(path.read_bytes()) != digest:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH, "unexpected upstream file: " + name
            )
    originals = [opening.OUTPUT_FONT, *(scene.output_font for scene in SCENES)]
    if preview is not None and preview.exists():
        raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"preview exists: {preview}")
    for name in originals:
        if (source / name).exists():
            raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"font exists: {name}")

    first = opening.make_assets(source, font)
    patches = opening._source_overlays(source, first)
    common_path = source / "data/text/common.asm"
    intro_path = source / "engine/menus/intro_menu.asm"
    common = patches[common_path].decode("utf-8")
    intro = patches[intro_path].decode("utf-8")
    scenes = [("ElmText1", first)]
    for scene in SCENES:
        assets = opening.make_assets(source, font, scene.lines)
        common = _replace_section(common, scene, assets)
        common += _font_sections(scene)
        intro = _replace_caller(intro, scene)
        patches[source / scene.output_font] = assets.tiles
        scenes.append((scene.caller_label, assets))

    patches[common_path] = common.encode("utf-8")
    patches[intro_path] = intro.encode("utf-8")
    dynamic_report: dict[str, object] | None = None
    if dynamic_player:
        from classic_retro.source.polishedcrystal_elm_dynamic import augment

        patches, dynamic_report = augment(source, font, patches)
    town_report: dict[str, object] | None = None
    if new_bark_town:
        from classic_retro.source.polishedcrystal_newbark import augment as augment_town

        patches, town_report = augment_town(source, font, patches)
    for path, data in patches.items():
        path.write_bytes(data)

    if preview is not None:
        images = [image for _, assets in scenes for image in assets.images]
        review = Image.new("1", (opening.COLUMNS * 8, len(images) * 10))
        for index, image in enumerate(images):
            review.paste(image, (0, index * 10))
        review.resize((review.width * 4, review.height * 4), Image.Resampling.NEAREST).save(preview)
    return {
        "version": "3.2.3",
        "game": "polished-crystal",
        "status": "incomplete (selected Elm and New Bark Town dialogs, not whole game)",
        "source_scenes": len(scenes) + (1 if dynamic_report else 0)
        + (town_report["scenes"] if town_report else 0),
        "arabic_lines": sum(len(assets.images) for _, assets in scenes)
        + (dynamic_report["translated_lines"] if dynamic_report else 0)
        + (town_report["arabic_lines"] if town_report else 0),
        "tile_counts": {name: assets.used_glyphs for name, assets in scenes},
        "modified_files": sorted(path.relative_to(source).as_posix() for path in patches),
        "untranslated_dynamic_message": None if dynamic_report else "_ElmText7",
        "dynamic_player_intro": dynamic_report,
        "new_bark_town": town_report,
        "full_game_translated": False,
        "gameplay_verified": False,
    }
