"""Pokémon Mystery Dungeon: Red Rescue Team (USA, Australia): the binary ROM overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.engines.pmd_arabic import PmdTextBox
from classic_retro.localization.targets import (
    LocalizationTarget,
    preview_paths,
    print_json,
    write_build_report,
)
from classic_retro.localization.translations import TranslationSet
from classic_retro.rom import pmd_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_text_preview.png")


def check_hooks() -> dict[str, object]:
    return pmd_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return pmd_arabic.check_pmd_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = pmd_arabic.build_pmd_arabic_rom(rom, font, translations=translations)
    written = pmd_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{pmd_arabic.IMAGE.title} image, SHA-256 {pmd_arabic.IMAGE.sha256}"
    return origin, pmd_arabic.extract_originals(image.read_bytes(), translations)


def _check_translations_command(args: argparse.Namespace) -> int:
    return print_json(pmd_arabic.check_pmd_translations(args.font, args.preview, args.text_preview))


def _check_hooks_command(_: argparse.Namespace) -> int:
    return print_json(check_hooks())


def _build_command(args: argparse.Namespace) -> int:
    return print_json(build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom))


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(pmd_arabic.encode_pmd_arabic_line(args.text, args.font, PmdTextBox(args.box)))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    pmd = subcommands.add_parser(
        "pmd",
        help="Pokémon Mystery Dungeon: Red Rescue Team (USA) Arabic ROM overlay helpers",
    )
    pmd_commands = pmd.add_subparsers(dest="pmd_command", required=True)

    pmd_check = pmd_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    pmd_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    pmd_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    pmd_check.add_argument(
        "--text-preview",
        type=Path,
        help="Write every translated string, laid out as the game draws it, as one PNG",
    )
    pmd_check.set_defaults(handler=_check_translations_command)

    pmd_hooks = pmd_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    pmd_hooks.set_defaults(handler=_check_hooks_command)

    pmd_build = pmd_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    pmd_build.add_argument("rom", type=Path)
    pmd_build.add_argument("--font", type=Path, required=True)
    pmd_build.add_argument("--out-dir", type=Path, required=True)
    pmd_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    pmd_build.set_defaults(handler=_build_command)

    pmd_encode = pmd_commands.add_parser(
        "encode-arabic",
        help="Encode logical Arabic text ({CENTER_ALIGN}, {WAIT_PRESS}... allowed) in paint order",
    )
    pmd_encode.add_argument("text")
    pmd_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of each line",
    )
    pmd_encode.add_argument(
        "--box",
        choices=[box.value for box in PmdTextBox],
        default=PmdTextBox.DIALOGUE.value,
        help="Floating text, dialogue box or menu item (decides the line width)",
    )
    pmd_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="pmd-red",
    game_id="pokemon-mystery-dungeon-red-usa",
    title="Pokémon Mystery Dungeon: Red Rescue Team (USA, Australia)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="The personality test: its intro, 56 questions with their answers and the gender question (158 strings)",
    guide="docs/PMD_RED_ARABIC_TEST_AR.md",
    notes="docs/PMD_RED_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="5fd64c9bb52c193e0b70a58e7d8e3a66bcd9634e1701db3cf8c4fc2c4397ea24",
)
