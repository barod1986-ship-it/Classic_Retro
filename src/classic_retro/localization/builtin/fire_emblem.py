"""Fire Emblem: The Sacred Stones (USA, Australia): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.engines.fire_emblem_arabic import TalkBox
from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import fire_emblem_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_legend_preview.png")


def check_hooks() -> dict[str, object]:
    return fire_emblem_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return fire_emblem_arabic.check_fire_emblem_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = fire_emblem_arabic.build_fire_emblem_arabic_rom(rom, font, translations=translations)
    written = fire_emblem_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{fire_emblem_arabic.IMAGE.title} image, SHA-256 {fire_emblem_arabic.IMAGE.sha256}"
    return origin, fire_emblem_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        fire_emblem_arabic.encode_fire_emblem_arabic_line(args.text, args.font, TalkBox(args.box))
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    fire_emblem = subcommands.add_parser(
        "fire-emblem",
        help="Fire Emblem: The Sacred Stones (USA) Arabic ROM overlay helpers",
    )
    fire_emblem_commands = fire_emblem.add_subparsers(dest="fire_emblem_command", required=True)

    fire_emblem_encode = fire_emblem_commands.add_parser(
        "encode-arabic",
        help="Encode logical Arabic text ([LF], [A]... allowed) in right-to-left paint order",
    )
    fire_emblem_encode.add_argument("text")
    fire_emblem_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of each line",
    )
    fire_emblem_encode.add_argument(
        "--box",
        choices=[box.value for box in TalkBox],
        default=TalkBox.BUBBLE.value,
        help="Dialogue bubble or world map narration box (decides the line width)",
    )
    fire_emblem_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="fire-emblem",
    game_id="fire-emblem-sacred-stones-usa",
    title="Fire Emblem: The Sacred Stones (USA, Australia)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font", "text-images"),
    scope="The opening legend (7 images), the world map narration and the prologue's throne room (5 messages)",
    guide="docs/FIRE_EMBLEM_ARABIC_TEST_AR.md",
    notes="docs/FIRE_EMBLEM_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="f955d6235b3c5958e414a9fab9bb350ccdcc88158249fef9efec19ef30756784",
)
