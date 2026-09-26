"""Mario & Luigi: Superstar Saga (USA): the binary ROM overlay."""

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
from classic_retro.rom import mlss_arabic

PREVIEWS = ("arabic_font_preview.png", "arabic_messages_preview.png")


def check_hooks() -> dict[str, object]:
    return mlss_arabic.check_hook_code()


def check_translations(
    font: Path | None, preview_dir: Path | None, translations: TranslationSet | None = None
) -> dict[str, object]:
    """The script checked without the ROM; with a font and a folder, its previews too."""
    previews = preview_paths(font, preview_dir, *PREVIEWS)
    return mlss_arabic.check_mlss_translations(font, *previews, translations=translations)


def build(
    rom: bytes,
    font: Path,
    out_dir: Path,
    rom_name: str | None,
    translations: TranslationSet | None = None,
) -> dict[str, object]:
    result = mlss_arabic.build_mlss_arabic_rom(rom, font, translations=translations)
    written = mlss_arabic.write_build_outputs(result, out_dir, rom_name=rom_name)
    return write_build_report(out_dir, {**result.report, "outputs": written})


def extract(image: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read and verified from the user's own image."""
    origin = f"{mlss_arabic.IMAGE.title} image, SHA-256 {mlss_arabic.IMAGE.sha256}"
    return origin, mlss_arabic.extract_originals(image.read_bytes(), translations)


def _encode_command(args: argparse.Namespace) -> int:
    return print_json(mlss_arabic.encode_mlss_arabic_message(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    mlss = subcommands.add_parser(
        "mlss",
        help="Mario & Luigi: Superstar Saga (USA) Arabic ROM overlay helpers",
    )
    mlss_commands = mlss.add_subparsers(dest="mlss_command", required=True)

    mlss_encode = mlss_commands.add_parser(
        "encode-arabic",
        help="Encode one message text in notation ({FF 0B 01}, \\n, ... {FF 0A}) in paint order",
    )
    mlss_encode.add_argument("text")
    mlss_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the width of each line and the header",
    )
    mlss_encode.set_defaults(handler=_encode_command)


TARGET = LocalizationTarget(
    id="mlss",
    game_id="mario-luigi-superstar-saga-usa",
    title="Mario & Luigi: Superstar Saga (USA)",
    platform_id="gba",
    kind="rom-overlay",
    strategies=("glyph-font",),
    scope="The opening up to the first battle (12 messages)",
    guide="docs/MLSS_ARABIC_TEST_AR.md",
    notes="docs/MLSS_ARABIC_RENDERER.md",
    register_cli=register_cli,
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,
    previews=PREVIEWS,
    reference_patch_sha256="39803b96a4f4cfe5f8c4ec1ab23d6a0fd861683d1b318cc3637a3ad75271eb58",
)
