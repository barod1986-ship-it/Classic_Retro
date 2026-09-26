"""Pokémon FireRed (Rev 1): the source overlay on pret/pokefirered."""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.engines.pokemon_gen3_arabic import PokemonGen3ArabicEncoder
from classic_retro.localization.targets import LocalizationTarget, print_json
from classic_retro.localization.translations import TranslationSet
from classic_retro.source.pokefirered_arabic import (
    PINNED_COMMIT,
    check_pokefirered_arabic_source,
    extract_pokefirered_originals,
    prepare_pokefirered_arabic_source,
)
from classic_retro.text.tokens import TextToken, TokenStream


def prepare(
    source: Path, font: Path, translations: TranslationSet | None = None
) -> dict[str, object]:
    """Patch the user's pristine checkout: the overlay, the font and the Arabic text."""
    return prepare_pokefirered_arabic_source(source, font, translations)


def extract(source: Path, translations: TranslationSet | None = None) -> tuple[str, dict[str, str]]:
    """The original of every entry, read from the user's pristine checkout."""
    return f"pret/pokefirered at {PINNED_COMMIT}", extract_pokefirered_originals(
        source, translations
    )


def _source_check(args: argparse.Namespace) -> int:
    return print_json(check_pokefirered_arabic_source(args.source))


def _encode_arabic(args: argparse.Namespace) -> int:
    encoder = PokemonGen3ArabicEncoder()
    data = encoder.encode_message(
        TokenStream((TextToken(args.text),)),
        right_x=args.right_x,
        terminator=True,
    )
    return print_json(
        {
            "right_x": args.right_x,
            "bytes_hex": data.hex(),
            "bytes": len(data),
            "glyphs": len(encoder.glyph_map.characters),
        }
    )


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    pokemon = subcommands.add_parser(
        "pokemon-gen3",
        help="Pokémon Generation III engine helpers",
    )
    pokemon_commands = pokemon.add_subparsers(dest="pokemon_command", required=True)

    source_check = pokemon_commands.add_parser(
        "source-check",
        help="Verify the pinned pokefirered source and Arabic overlay anchors",
    )
    source_check.add_argument("source", type=Path)
    source_check.set_defaults(handler=_source_check)

    compile_arabic = pokemon_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to Gen III RTL paint-order bytes",
    )
    compile_arabic.add_argument("text")
    compile_arabic.add_argument("--right-x", type=int, default=224)
    compile_arabic.set_defaults(handler=_encode_arabic)


TARGET = LocalizationTarget(
    id="firered",
    game_id="pokemon-firered-rev1-en",
    title="Pokémon FireRed Version (USA, Europe) (Rev 1)",
    platform_id="gba",
    kind="source-overlay",
    strategies=("glyph-font",),
    scope="The 13 Professor Oak speech strings of the new-game intro",
    guide="docs/FIRERED_ARABIC_TEST_AR.md",
    notes="docs/POKEMON_GEN3_ARABIC_RENDERER.md",
    register_cli=register_cli,
    prepare=prepare,
    extract=extract,
)
