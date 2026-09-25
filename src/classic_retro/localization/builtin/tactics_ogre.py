"""Tactics Ogre: The Knight of Lodis (USA): the binary ROM overlay."""

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
from classic_retro.rom import tactics_ogre_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return tactics_ogre_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return tactics_ogre_arabic.check_tactics_ogre_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = tactics_ogre_arabic.build_tactics_ogre_arabic_rom(rom, font, translations=translations)
    written = tactics_ogre_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    image_spec = tactics_ogre_arabic.IMAGE
    origin = f"{image_spec.title} image, SHA-256 {image_spec.sha256}"
    return origin, tactics_ogre_arabic.extract_originals(image.read_bytes(), translations)


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(
        tactics_ogre_arabic.check_tactics_ogre_translations(
            args.font, args.preview, args.text_preview
        )
    )


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        tactics_ogre_arabic.encode_tactics_ogre_arabic_message(
            args.text, args.font, lines_per_page=args.lines
        )
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    tactics_ogre = subcommands.add_parser(
        "tactics-ogre",
        help="Tactics Ogre: The Knight of Lodis (USA) Arabic ROM overlay helpers",
    )
    commands = tactics_ogre.add_subparsers(dest="tactics_ogre_command", required=True)

    check = commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the right-to-left font and measures every line",
    )
    check.add_argument("--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG")
    check.add_argument(
        "--text-preview",
        type=Path,
        help="Write every translated message, laid out as the game shows it, as one PNG",
    )
    check.set_defaults(handler=_check_translations_command)

    hooks = commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    hooks.set_defaults(handler=_check_hooks_command)

    build_parser = commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    build_parser.add_argument("rom", type=Path)
    build_parser.add_argument("--font", type=Path, required=True)
    build_parser.add_argument("--out-dir", type=Path, required=True)
    build_parser.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    build_parser.set_defaults(handler=_build_command)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation ({8B}, {8C}, {8E}{8A}, {8705}, \\n...) in paint order",
    )
    encode.add_argument("text")
    encode.add_argument(
        "--font", type=Path, help="Arabic TTF/OTF used to report the width of each line"
    )
    encode.add_argument(
        "--lines",
        type=int,
        choices=(1, 2, 3),
        default=3,
        help="The lines of a page of the message's window (its header; 3 by default)",
    )
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="tactics-ogre",
    game_id="tactics-ogre-usa",
    title="Tactics Ogre: The Knight of Lodis (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The opening scene in the harbour town: the dialogue up to the name screen (15 messages)"
    ),
    guide="docs/TACTICS_OGRE_ARABIC_TEST_AR.md",
    notes="docs/TACTICS_OGRE_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="be77beca5cf95f3cbddfccc61ef209930d91fcb1aa213e4abc30eb9fa2d3d40c",
)
