"""New Super Mario Bros. (USA): the binary ROM overlay of its menus and prompts."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import nsmb_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return nsmb_arabic.check_nsmb_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = nsmb_arabic.build_nsmb_arabic_rom(rom, font, translations=translations)
    written = nsmb_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    image_spec = nsmb_arabic.IMAGE
    origin = f"{image_spec.title} image, SHA-256 {image_spec.sha256}"
    return origin, nsmb_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        nsmb_arabic.encode_nsmb_arabic_message(args.text, args.font, line_width=args.width)
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    nsmb = subcommands.add_parser(
        "nsmb", help="New Super Mario Bros. (USA) Arabic ROM overlay helpers"
    )
    commands = nsmb.add_subparsers(dest="nsmb_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation ({FF:00000100}, {01:0100}, \\n) in visual order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.add_argument(
        "--width", type=int, default=200, help="The width a line may take (200 by default)"
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="nsmb",
    game_id="new-super-mario-bros-usa",
    title="New Super Mario Bros. (USA)",
    platform_id="nds",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The menus and prompts: the file select, the world map's menu, the pause menu, "
        "the save and quit prompts and the Star Coin gates (42 messages)"
    ),
    guide="docs/NSMB_ARABIC_TEST_AR.md",
    notes="docs/NSMB_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="66802016d788b335720967807567377c4205d1012269663e8ab5d5bc249af757",
)
