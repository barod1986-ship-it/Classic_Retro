"""Metroid Fusion (USA): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.engines.metroid_fusion_arabic import LINES_PER_PAGE, STRIP
from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import metroid_fusion_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return metroid_fusion_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return metroid_fusion_arabic.check_metroid_fusion_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = metroid_fusion_arabic.build_metroid_fusion_arabic_rom(
        rom, font, translations=translations
    )
    written = metroid_fusion_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    image_spec = metroid_fusion_arabic.IMAGE
    origin = f"{image_spec.title} image, SHA-256 {image_spec.sha256}"
    return origin, metroid_fusion_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        metroid_fusion_arabic.encode_metroid_fusion_arabic_message(
            args.text, args.font, renderer=args.renderer
        )
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    metroid_fusion = subcommands.add_parser(
        "metroid-fusion",
        help="Metroid Fusion (USA) Arabic ROM overlay helpers",
    )
    commands = metroid_fusion.add_subparsers(dest="metroid_fusion_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one text in notation ({FC00}, {FD00}, {81xx}, \\n...) in paint order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.add_argument(
        "--renderer",
        choices=sorted(LINES_PER_PAGE),
        default=STRIP,
        help="The intro's two-line strip (default), a monologue page of nine lines, a "
        "briefing's two-line box or the objective question",
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="metroid-fusion",
    game_id="metroid-fusion-usa",
    title="Metroid Fusion (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The new-game intro (Samus's narration up to her new mission, 12 monologues) and the "
        "first two briefings on the map with their questions"
    ),
    guide="docs/METROID_FUSION_ARABIC_TEST_AR.md",
    notes="docs/METROID_FUSION_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="4e2f7a836557447e9a508ae988de644442956075a1a5dbfb1f67a3f509d0af47",
)
