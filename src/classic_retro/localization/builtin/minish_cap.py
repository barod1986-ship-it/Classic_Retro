"""The Legend of Zelda: The Minish Cap (USA): the source overlay on zeldaret/tmc."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.localization.targets import LocalizationTarget, print_json
from classic_retro.localization.translations import TranslationSet
from classic_retro.source.tmc_arabic import (
    PINNED_COMMIT,
    check_tmc_arabic_source,
    encode_tmc_arabic_line,
    extract_tmc_originals,
    prepare_tmc_arabic_source,
)


def prepare(
    source: Path, font: Path, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Patch the user's pristine checkout: the overlay, the font and the Arabic text."""
    return prepare_tmc_arabic_source(source, font, translations=translations)


def extract(source: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read from the user's pristine checkout."""
    return f"zeldaret/tmc at {PINNED_COMMIT}", extract_tmc_originals(source, translations)


def _source_check(args: argparse.Namespace) -> int:
    return print_json(check_tmc_arabic_source(args.source, args.font))


def _encode_arabic(args: argparse.Namespace) -> int:
    return print_json(encode_tmc_arabic_line(args.text, args.font))


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    tmc = subcommands.add_parser(
        "tmc",
        help="The Legend of Zelda: The Minish Cap (zeldaret/tmc) helpers",
    )
    tmc_commands = tmc.add_subparsers(dest="tmc_command", required=True)

    tmc_check = tmc_commands.add_parser(
        "source-check",
        help="Dry-run the Arabic overlay on the pinned zeldaret/tmc source",
    )
    tmc_check.add_argument("source", type=Path)
    tmc_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    tmc_check.set_defaults(handler=_source_check)

    tmc_encode = tmc_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to tmc_strings notation in RTL paint order",
    )
    tmc_encode.add_argument("text")
    tmc_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of the line",
    )
    tmc_encode.set_defaults(handler=_encode_arabic)


TARGET = LocalizationTarget(
    id="minish-cap",
    game_id="zelda-minish-cap-usa",
    title="The Legend of Zelda: The Minish Cap (USA)",
    platform_id="gba",
    kind="source-overlay",
    strategies=("glyph-font",),
    scope="The whole new-game opening (26 messages)",
    guide="docs/MINISH_CAP_ARABIC_TEST_AR.md",
    notes="docs/TMC_ARABIC_RENDERER.md",
    register_cli=register_cli,
    prepare=prepare,
    extract=extract,
)
