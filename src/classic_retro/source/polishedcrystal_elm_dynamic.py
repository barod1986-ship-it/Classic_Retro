"""Named PLAYER placeholder inside an Arabic Polished Crystal GBC opening.

Arabic lines are shaped offline; the PLAYER line remains game-rendered from
WRAM with its original Latin glyphs and original line direction. Other pages
swap their font atlas only while their own dialog is active. This is a first
mixed-content bridge, *not* an arbitrary inline Arabic/Latin bidi engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening

# Original font codes MUST remain untouched while <PLAYER> is being
# expanded by the ROM's n-gram command. The game permits mixed-case names.
NAME_SAFE_POOL = (*range(0xD0, 0xE0), 0xEA, 0xEB)


@dataclass(frozen=True)
class DynamicPage:
    label: str
    lines: tuple[tuple[str, str], ...]
    dynamic_player: bool = False


PAGES = (
    DynamicPage("Ready", (("line", "هل أنت مستعد؟"),), dynamic_player=True),
    DynamicPage(
        "Journey",
        (
            ("text", "قصتك الخاصة"),
            ("line", "مع البوكيمون"),
            ("para", "ستبدأ الآن!"),
            ("para", "ستعيش أوقاتًا"),
            ("line", "ممتعة وصعبة."),
        ),
    ),
    DynamicPage(
        "World",
        (
            ("text", "عالم الأحلام"),
            ("line", "والمغامرات"),
            ("para", "في انتظارك!"),
            ("line", "هيا ننطلق!"),
        ),
    ),
    DynamicPage("Goodbye", (("text", "سأراك لاحقًا!"),)),
)


def _asm_page(page: DynamicPage, assets: opening.ElmArabicAssets) -> str:
    if len(assets.codes) != len(page.lines):
        raise ClassicRetroError(ErrorCode.SOURCE_PATCH_FAILED, "dynamic scene line mismatch")
    label = "ClassicRetroElm7" + page.label
    result = [f'SECTION "{label} Text", ROMX', f"{label}::", "\ttext_start"]
    if page.dynamic_player:
        result.append('\tdb "<PLAYER>"')
    for (op, _), row in zip(page.lines, assets.codes, strict=True):
        if op != "text":
            code = {"line": "<LINE>", "para": "<PARA>", "cont": "<CONT>"}.get(op)
            if code is None:
                raise ClassicRetroError(ErrorCode.UNSUPPORTED_CONTROL_CODE, op)
            result.append(f'\tdb "{code}"')
        result.append("\tdb " + ", ".join("$" + format(tile, "02x") for tile in row))
    result += ['\tdb "<PROMPT>"', ""]
    return "\n".join(result)


def _asm_font(page: DynamicPage) -> str:
    font_label = "ClassicRetroElm7" + page.label + "Font"
    font_path = "gfx/font/classic_retro_elm7_" + page.label.lower() + ".1bpp"
    print_label = "ClassicRetroPrintElm7" + page.label
    text_label = "ClassicRetroElm7" + page.label
    return "\n".join(
        (
            f'SECTION "{font_label} Data", ROMX',
            f"{font_label}::",
            f'\tINCBIN "{font_path}"',
            f'SECTION "{font_label} Code", ROMX',
            f"{print_label}::",
            "\tpush hl",
            f"\tld de, {font_label}",
            "\tld hl, vTiles0 tile 'A'",
            f"\tlb bc, BANK({font_label}), 114",
            "\txor a",
            "\tldh [hRequestOpaque1bpp], a",
            "\tcall GetMaybeOpaque1bpp",
            "\tpop hl",
            f"\tld a, BANK({text_label})",
            "\tld de, PrintText",
            "\tcall FarCall_de",
            "\tjmp LoadStandardFont",
            "",
        )
    )


def _asm_caller() -> str:
    lines = ['SECTION "Classic Retro Elm7 Mixed Name Dispatcher", ROMX']
    lines.append("ClassicRetroElm7Sequence::")
    for page in PAGES:
        label = "ClassicRetroElm7" + page.label
        lines.extend((f"\tld hl, {label}", f"\tfarcall ClassicRetroPrintElm7{page.label}"))
    lines += ["\tret", ""]
    return "\n".join(lines)


def augment(
    source: Path, font: Path, changes: dict[Path, bytes]
) -> tuple[dict[Path, bytes], dict[str, object]]:
    """Patch the dynamic speech in pending source edits; no intermediate writes."""
    source = Path(source)
    common_file = source / "data/text/common.asm"
    intro_file = source / "engine/menus/intro_menu.asm"
    common = changes[common_file].decode("utf-8")
    intro = changes[intro_file].decode("utf-8")
    original = "\tld hl, ElmText7\n\tjmp PrintText\n"
    if intro.count(original) != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            "exact ElmText7 tail not found; cannot safely replace dynamic speech",
        )
    intro = intro.replace(original, "\tfarjp ClassicRetroElm7Sequence\n")

    local_changes = dict(changes)
    report: dict[str, object] = {
        "pages": len(PAGES),
        "translated_lines": sum(len(p.lines) for p in PAGES),
        "dynamic_player_name": True,
        "latin_name_preserved": True,
        "page_glyphs": {},
    }
    for page in PAGES:
        code_pool = NAME_SAFE_POOL if page.dynamic_player else None
        assets = opening.make_assets(source, font, page.lines, code_pool=code_pool)
        if page.dynamic_player:
            native_atlas = (source / "gfx/font/normal.1bpp").read_bytes()
            # Retain all uppercase and lowercase letters, including user-entered names.
            for code in range(0x80, 0xBA):
                offset = (code - 0x80) * 8
                if assets.tiles[offset : offset + 8] != native_atlas[offset : offset + 8]:
                    raise ClassicRetroError(
                        ErrorCode.BUILD_VALIDATION_FAILED, "player-name glyph was changed"
                    )
        path = source / ("gfx/font/classic_retro_elm7_" + page.label.lower() + ".1bpp")
        if path.exists() or path in local_changes:
            raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"font already exists: {path}")
        local_changes[path] = assets.tiles
        common += "\n" + _asm_page(page, assets) + "\n" + _asm_font(page)
        report["page_glyphs"][page.label] = assets.used_glyphs
    common += "\n" + _asm_caller()
    local_changes[common_file] = common.encode("utf-8")
    local_changes[intro_file] = intro.encode("utf-8")
    return local_changes, report
