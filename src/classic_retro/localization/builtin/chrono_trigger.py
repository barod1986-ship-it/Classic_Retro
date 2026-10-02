"""Chrono Trigger (USA): the ROM overlay."""

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
from classic_retro.rom import chrono_trigger_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return chrono_trigger_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The messages checked without the ROM; with a font and a folder, their previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return chrono_trigger_arabic.check_chrono_trigger_translations(
        font, *previews, translations=translations
    )


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = chrono_trigger_arabic.build_chrono_trigger_arabic_rom(
        rom, font, translations=translations
    )
    written = chrono_trigger_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own ROM."""
    image_spec = chrono_trigger_arabic.IMAGE
    origin = f"{image_spec.title}, SHA-256 {image_spec.sha256}"
    return origin, chrono_trigger_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(
        chrono_trigger_arabic.encode_chrono_trigger_arabic_message(args.text, args.font)
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    chrono_trigger = subcommands.add_parser(
        "chrono-trigger", help="Chrono Trigger (USA) Arabic ROM overlay helpers"
    )
    commands = chrono_trigger.add_subparsers(dest="chrono_trigger_command", required=True)

    encode = commands.add_parser(
        "encode-arabic",
        help="Encode one message in notation (a line a box, {line} to end a line)",
    )
    encode.add_argument("text")
    encode.add_argument("--font", type=Path, help="Arabic TTF/OTF used to lay the boxes out")
    encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="chrono-trigger",
    game_id="chrono-trigger-usa",
    title="Chrono Trigger (USA)",
    platform_id="snes",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope=(
        "The dialogue table by table: three of the game's fifteen string tables, 2058 "
        "messages of Crono's house and Truce in 1000 and in 600, Truce Canyon, the "
        "prison's cell, Lab 32, the Proto Dome, the Sun Keep and the Geno Dome; of "
        "Leene Square with the Millennial Fair, the trial, the castle's cellars, Melchior's "
        "hut, Norstein Bekkler's tent, the Tyrano Lair's cells, the Lavos crater, Zeal's "
        "sealed palace and Death Peak; and of Castle Guardia in 600 and 1000, the domes of "
        "2300 A.D., Medina, the End of Time with Gaspar and Spekkio, Ozzie's and Magus's "
        "scenes, the Blackbird and the Reptites' land; the other twelve tables stay English"
    ),
    guide="docs/CHRONO_TRIGGER_ARABIC_TEST_AR.md",
    notes="docs/CHRONO_TRIGGER_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="dcbb38d299ddf98716482e253ec28a138e79a0509eeb840f96696a9ece5fc1e2",
)
