from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from classic_retro import __version__
from classic_retro.adapters.discovery import detect_input
from classic_retro.adapters.registry import build_registry
from classic_retro.arabic.pipeline import ArabicPipeline
from classic_retro.codec.model import load_codec_profile
from classic_retro.codec.table import TableTextCodec
from classic_retro.core.errors import ClassicRetroError
from classic_retro.core.identity import fingerprint_file
from classic_retro.engines.fire_emblem_arabic import TalkBox
from classic_retro.engines.pmd_arabic import PmdTextBox
from classic_retro.engines.pokemon_gen3_arabic import PokemonGen3ArabicEncoder
from classic_retro.media.resolve import resolve_media
from classic_retro.rebuild.bps import apply_bps, create_bps
from classic_retro.rebuild.model import load_rebuild_plan
from classic_retro.rebuild.pipeline import verify_round_trip
from classic_retro.rom import fire_emblem_arabic, golden_sun_arabic, pmd_arabic
from classic_retro.rom.ff6a_arabic import (
    build_ff6a_arabic_rom,
    check_ff6a_translations,
    check_hook_code,
    encode_ff6a_arabic_line,
    write_build_outputs,
)
from classic_retro.source.pokefirered_arabic import (
    check_pokefirered_arabic_source,
    prepare_pokefirered_arabic_source,
)
from classic_retro.source.tmc_arabic import (
    check_tmc_arabic_source,
    encode_tmc_arabic_line,
    prepare_tmc_arabic_source,
)
from classic_retro.text.document import load_translation_file
from classic_retro.transform.profile import build_pipeline, load_transform_profile
from classic_retro.transform.registry import build_transform_registry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classic-retro",
        description="Classic Retro Arabic localization toolkit",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    version = subcommands.add_parser("version", help="Show toolkit version")
    version.set_defaults(handler=_cmd_version)

    fingerprint = subcommands.add_parser(
        "fingerprint",
        help="Calculate deterministic metadata for one input file",
    )
    fingerprint.add_argument("path", type=Path)
    fingerprint.set_defaults(handler=_cmd_fingerprint)

    detect = subcommands.add_parser(
        "detect",
        help="Detect a platform and match exact supported game revisions",
    )
    detect.add_argument("path", type=Path)
    detect.set_defaults(handler=_cmd_detect)

    media = subcommands.add_parser("media", help="Inspect game media/container inputs")
    media_commands = media.add_subparsers(dest="media_command", required=True)
    inspect_media = media_commands.add_parser(
        "inspect",
        help="Resolve a single file or CUE set and print its deterministic identity",
    )
    inspect_media.add_argument("path", type=Path)
    inspect_media.set_defaults(handler=_cmd_media_inspect)

    translation = subcommands.add_parser(
        "translation",
        help="Validate and inspect canonical translation documents",
    )
    translation_commands = translation.add_subparsers(
        dest="translation_command",
        required=True,
    )
    validate_translation = translation_commands.add_parser(
        "validate",
        help="Validate schema, entry IDs, and protected token preservation",
    )
    validate_translation.add_argument("path", type=Path)
    validate_translation.set_defaults(handler=_cmd_translation_validate)

    arabic = subcommands.add_parser(
        "arabic",
        help="Validate Arabic normalization, shaping, bidi, and protected tokens",
    )
    arabic_commands = arabic.add_subparsers(dest="arabic_command", required=True)
    check_arabic = arabic_commands.add_parser(
        "check",
        help="Run the Arabic preparation pipeline over all target messages",
    )
    check_arabic.add_argument("path", type=Path)
    check_arabic.set_defaults(handler=_cmd_arabic_check)

    rebuild = subcommands.add_parser(
        "rebuild",
        help="Validate binary extraction/rebuild plans",
    )
    rebuild_commands = rebuild.add_subparsers(dest="rebuild_command", required=True)
    verify_rebuild = rebuild_commands.add_parser(
        "verify",
        help="Extract and rebuild unchanged resources and require a byte-exact image",
    )
    verify_rebuild.add_argument("plan", type=Path)
    verify_rebuild.add_argument("image", type=Path)
    verify_rebuild.set_defaults(handler=_cmd_rebuild_verify)

    bps_create = rebuild_commands.add_parser(
        "bps-create",
        help="Write a BPS patch from an original and a modified image, verified by re-applying",
    )
    bps_create.add_argument("source", type=Path)
    bps_create.add_argument("target", type=Path)
    bps_create.add_argument("patch", type=Path)
    bps_create.set_defaults(handler=_cmd_rebuild_bps_create)

    bps_apply = rebuild_commands.add_parser(
        "bps-apply",
        help="Apply a BPS patch; source, target and patch checksums are verified",
    )
    bps_apply.add_argument("patch", type=Path)
    bps_apply.add_argument("source", type=Path)
    bps_apply.add_argument("output", type=Path)
    bps_apply.set_defaults(handler=_cmd_rebuild_bps_apply)

    transform = subcommands.add_parser(
        "transform",
        help="Validate resource transform pipelines and compressed fixtures",
    )
    transform_commands = transform.add_subparsers(dest="transform_command", required=True)
    verify_transform = transform_commands.add_parser(
        "verify",
        help="Decode, reuse unchanged bytes, and verify forced re-encoding",
    )
    verify_transform.add_argument("profile", type=Path)
    verify_transform.add_argument("data", type=Path)
    verify_transform.set_defaults(handler=_cmd_transform_verify)

    codec = subcommands.add_parser(
        "codec",
        help="Validate fixed game-text byte codecs and round trips",
    )
    codec_commands = codec.add_subparsers(dest="codec_command", required=True)
    verify_codec = codec_commands.add_parser(
        "verify",
        help="Decode and exactly rebuild one binary text fixture",
    )
    verify_codec.add_argument("profile", type=Path)
    verify_codec.add_argument("data", type=Path)
    verify_codec.add_argument("--require-terminator", action="store_true")
    verify_codec.set_defaults(handler=_cmd_codec_verify)

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
    source_check.set_defaults(handler=_cmd_pokemon_source_check)

    prepare_source = pokemon_commands.add_parser(
        "prepare-arabic-source",
        help="Patch pinned pokefirered source for RTL and build the Arabic font atlas",
    )
    prepare_source.add_argument("source", type=Path)
    prepare_source.add_argument("--font", type=Path, required=True)
    prepare_source.set_defaults(handler=_cmd_pokemon_prepare_arabic_source)

    compile_arabic = pokemon_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to Gen III RTL paint-order bytes",
    )
    compile_arabic.add_argument("text")
    compile_arabic.add_argument("--right-x", type=int, default=224)
    compile_arabic.set_defaults(handler=_cmd_pokemon_encode_arabic)

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
    tmc_check.set_defaults(handler=_cmd_tmc_source_check)

    tmc_prepare = tmc_commands.add_parser(
        "prepare-arabic-source",
        help="Patch pinned zeldaret/tmc for RTL Arabic text and write the Arabic font",
    )
    tmc_prepare.add_argument("source", type=Path)
    tmc_prepare.add_argument("--font", type=Path, required=True)
    tmc_prepare.set_defaults(handler=_cmd_tmc_prepare_arabic_source)

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
    tmc_encode.set_defaults(handler=_cmd_tmc_encode_arabic)

    ff6a = subcommands.add_parser(
        "ff6a",
        help="Final Fantasy VI Advance (USA) Arabic ROM overlay helpers",
    )
    ff6a_commands = ff6a.add_subparsers(dest="ff6a_command", required=True)

    ff6a_check = ff6a_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    ff6a_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    ff6a_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    ff6a_check.set_defaults(handler=_cmd_ff6a_check_translations)

    ff6a_hooks = ff6a_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    ff6a_hooks.set_defaults(handler=_cmd_ff6a_check_hooks)

    ff6a_build = ff6a_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the USA ROM",
    )
    ff6a_build.add_argument("rom", type=Path)
    ff6a_build.add_argument("--font", type=Path, required=True)
    ff6a_build.add_argument("--out-dir", type=Path, required=True)
    ff6a_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    ff6a_build.set_defaults(handler=_cmd_ff6a_build_arabic)

    ff6a_encode = ff6a_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to FF6A codes in right-to-left paint order",
    )
    ff6a_encode.add_argument("text")
    ff6a_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of the line",
    )
    ff6a_encode.set_defaults(handler=_cmd_ff6a_encode_arabic)

    golden_sun = subcommands.add_parser(
        "golden-sun",
        help="Golden Sun (USA, Europe) Arabic ROM overlay helpers",
    )
    golden_sun_commands = golden_sun.add_subparsers(dest="golden_sun_command", required=True)

    golden_sun_check = golden_sun_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    golden_sun_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    golden_sun_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    golden_sun_check.set_defaults(handler=_cmd_golden_sun_check_translations)

    golden_sun_hooks = golden_sun_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    golden_sun_hooks.set_defaults(handler=_cmd_golden_sun_check_hooks)

    golden_sun_build = golden_sun_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    golden_sun_build.add_argument("rom", type=Path)
    golden_sun_build.add_argument("--font", type=Path, required=True)
    golden_sun_build.add_argument("--out-dir", type=Path, required=True)
    golden_sun_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    golden_sun_build.set_defaults(handler=_cmd_golden_sun_build_arabic)

    golden_sun_encode = golden_sun_commands.add_parser(
        "encode-arabic",
        help="Encode one logical Arabic line to Golden Sun codes in right-to-left paint order",
    )
    golden_sun_encode.add_argument("text")
    golden_sun_encode.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF used to report the pixel width of the line",
    )
    golden_sun_encode.set_defaults(handler=_cmd_golden_sun_encode_arabic)

    fire_emblem = subcommands.add_parser(
        "fire-emblem",
        help="Fire Emblem: The Sacred Stones (USA) Arabic ROM overlay helpers",
    )
    fire_emblem_commands = fire_emblem.add_subparsers(dest="fire_emblem_command", required=True)

    fire_emblem_check = fire_emblem_commands.add_parser(
        "check-translations",
        help="Validate the Arabic script without the ROM; with --font, measure every line",
    )
    fire_emblem_check.add_argument(
        "--font",
        type=Path,
        help="Arabic TTF/OTF; also builds the font and measures every translated line",
    )
    fire_emblem_check.add_argument(
        "--preview", type=Path, help="Write the generated Arabic glyph atlas as PNG"
    )
    fire_emblem_check.add_argument(
        "--legend-preview", type=Path, help="Write the seven Arabic legend images as one PNG"
    )
    fire_emblem_check.set_defaults(handler=_cmd_fire_emblem_check_translations)

    fire_emblem_hooks = fire_emblem_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    fire_emblem_hooks.set_defaults(handler=_cmd_fire_emblem_check_hooks)

    fire_emblem_build = fire_emblem_commands.add_parser(
        "build-arabic",
        help="Build the Arabic BPS patch (and optionally the patched image) from the ROM",
    )
    fire_emblem_build.add_argument("rom", type=Path)
    fire_emblem_build.add_argument("--font", type=Path, required=True)
    fire_emblem_build.add_argument("--out-dir", type=Path, required=True)
    fire_emblem_build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    fire_emblem_build.set_defaults(handler=_cmd_fire_emblem_build_arabic)

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
    fire_emblem_encode.set_defaults(handler=_cmd_fire_emblem_encode_arabic)

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
    pmd_check.set_defaults(handler=_cmd_pmd_check_translations)

    pmd_hooks = pmd_commands.add_parser(
        "check-hooks",
        help="Re-assemble the Thumb hooks with arm-none-eabi binutils and compare the bytes",
    )
    pmd_hooks.set_defaults(handler=_cmd_pmd_check_hooks)

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
    pmd_build.set_defaults(handler=_cmd_pmd_build_arabic)

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
    pmd_encode.set_defaults(handler=_cmd_pmd_encode_arabic)

    adapters = subcommands.add_parser("adapters", help="List loaded adapter IDs")
    adapters.set_defaults(handler=_cmd_adapters)

    return parser


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    result = fingerprint_file(args.path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    registry = build_registry()
    result = detect_input(args.path, registry)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_media_inspect(args: argparse.Namespace) -> int:
    result = resolve_media(args.path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_translation_validate(args: argparse.Namespace) -> int:
    document = load_translation_file(args.path)
    print(json.dumps(document.summary(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_arabic_check(args: argparse.Namespace) -> int:
    document = load_translation_file(args.path)
    pipeline = ArabicPipeline()

    inline_tokens = 0
    visible_characters = 0
    for entry in document.entries:
        result = pipeline.process(entry.target)
        inline_tokens += len(result.normalized.inline_tokens)
        visible_characters += len(result.normalized.visible_text)

    payload = {
        "game_id": document.game_id,
        "entries": len(document.entries),
        "inline_tokens": inline_tokens,
        "visible_characters": visible_characters,
        "normalization": "NFC",
        "base_direction": "R",
        "ligatures": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_rebuild_verify(args: argparse.Namespace) -> int:
    plan = load_rebuild_plan(args.plan)
    original = args.image.read_bytes()
    result = verify_round_trip(original, plan)
    payload = {
        "plan": plan.id,
        "resources": len(plan.resources),
        "references": len(plan.references),
        "safe_regions": len(plan.safe_regions),
        "writes": result.writes,
        "round_trip": True,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_rebuild_bps_create(args: argparse.Namespace) -> int:
    patch = create_bps(args.source.read_bytes(), args.target.read_bytes())
    args.patch.write_bytes(patch.data)
    payload = {
        "patch_bytes": len(patch.data),
        "source_bytes": patch.source_size,
        "target_bytes": patch.target_size,
        "source_crc32": f"{patch.source_crc32:08x}",
        "target_crc32": f"{patch.target_crc32:08x}",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_rebuild_bps_apply(args: argparse.Namespace) -> int:
    output = apply_bps(args.patch.read_bytes(), args.source.read_bytes())
    args.output.write_bytes(output)
    print(json.dumps({"output_bytes": len(output)}, indent=2, sort_keys=True))
    return 0


def _cmd_transform_verify(args: argparse.Namespace) -> int:
    profile = load_transform_profile(args.profile)
    registry = build_transform_registry()
    pipeline = build_pipeline(profile, registry)
    data = args.data.read_bytes()
    result = pipeline.verify(data)
    payload = {
        "pipeline": profile.id,
        "stages": [stage.codec for stage in profile.stages],
        "original_bytes": result.original_size,
        "decoded_bytes": result.decoded_size,
        "rebuilt_bytes": result.rebuilt_size,
        "reused_original": result.reused_original,
        "forced_reencode_exact": result.forced_reencode_exact,
        "round_trip": True,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_codec_verify(args: argparse.Namespace) -> int:
    profile = load_codec_profile(args.profile)
    codec = TableTextCodec(profile)
    data = args.data.read_bytes()
    decoded = codec.verify_round_trip(
        data,
        require_terminator=args.require_terminator,
    )
    payload = {
        "profile": profile.id,
        "consumed_bytes": decoded.consumed_bytes,
        "terminated": decoded.terminated,
        "terminator_id": decoded.terminator_id,
        "tokens": len(decoded.stream.tokens),
        "inline_tokens": len(decoded.stream.inline_tokens),
        "visible_text": decoded.stream.visible_text,
        "round_trip": True,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pokemon_source_check(args: argparse.Namespace) -> int:
    result = check_pokefirered_arabic_source(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pokemon_prepare_arabic_source(args: argparse.Namespace) -> int:
    result = prepare_pokefirered_arabic_source(args.source, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pokemon_encode_arabic(args: argparse.Namespace) -> int:
    from classic_retro.text.tokens import TextToken, TokenStream

    encoder = PokemonGen3ArabicEncoder()
    data = encoder.encode_message(
        TokenStream((TextToken(args.text),)),
        right_x=args.right_x,
        terminator=True,
    )
    payload = {
        "right_x": args.right_x,
        "bytes_hex": data.hex(),
        "bytes": len(data),
        "glyphs": len(encoder.glyph_map.characters),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_tmc_source_check(args: argparse.Namespace) -> int:
    result = check_tmc_arabic_source(args.source, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_tmc_prepare_arabic_source(args: argparse.Namespace) -> int:
    result = prepare_tmc_arabic_source(args.source, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_tmc_encode_arabic(args: argparse.Namespace) -> int:
    result = encode_tmc_arabic_line(args.text, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_ff6a_check_translations(args: argparse.Namespace) -> int:
    result = check_ff6a_translations(args.font, args.preview)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_ff6a_check_hooks(_: argparse.Namespace) -> int:
    result = check_hook_code()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_ff6a_build_arabic(args: argparse.Namespace) -> int:
    build = build_ff6a_arabic_rom(args.rom.read_bytes(), args.font)
    written = write_build_outputs(build, args.out_dir, rom_name=args.write_rom)
    report = {**build.report, "outputs": written}
    (args.out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_ff6a_encode_arabic(args: argparse.Namespace) -> int:
    result = encode_ff6a_arabic_line(args.text, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_golden_sun_check_translations(args: argparse.Namespace) -> int:
    result = golden_sun_arabic.check_golden_sun_translations(args.font, args.preview)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_golden_sun_check_hooks(_: argparse.Namespace) -> int:
    result = golden_sun_arabic.check_hook_code()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_golden_sun_build_arabic(args: argparse.Namespace) -> int:
    build = golden_sun_arabic.build_golden_sun_arabic_rom(args.rom.read_bytes(), args.font)
    written = golden_sun_arabic.write_build_outputs(build, args.out_dir, rom_name=args.write_rom)
    report = {**build.report, "outputs": written}
    (args.out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_golden_sun_encode_arabic(args: argparse.Namespace) -> int:
    result = golden_sun_arabic.encode_golden_sun_arabic_line(args.text, args.font)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_fire_emblem_check_translations(args: argparse.Namespace) -> int:
    result = fire_emblem_arabic.check_fire_emblem_translations(
        args.font, args.preview, args.legend_preview
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_fire_emblem_check_hooks(_: argparse.Namespace) -> int:
    result = fire_emblem_arabic.check_hook_code()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_fire_emblem_build_arabic(args: argparse.Namespace) -> int:
    build = fire_emblem_arabic.build_fire_emblem_arabic_rom(args.rom.read_bytes(), args.font)
    written = fire_emblem_arabic.write_build_outputs(build, args.out_dir, rom_name=args.write_rom)
    report = {**build.report, "outputs": written}
    (args.out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_fire_emblem_encode_arabic(args: argparse.Namespace) -> int:
    result = fire_emblem_arabic.encode_fire_emblem_arabic_line(
        args.text, args.font, TalkBox(args.box)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pmd_check_translations(args: argparse.Namespace) -> int:
    result = pmd_arabic.check_pmd_translations(args.font, args.preview, args.text_preview)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pmd_check_hooks(_: argparse.Namespace) -> int:
    result = pmd_arabic.check_hook_code()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pmd_build_arabic(args: argparse.Namespace) -> int:
    build = pmd_arabic.build_pmd_arabic_rom(args.rom.read_bytes(), args.font)
    written = pmd_arabic.write_build_outputs(build, args.out_dir, rom_name=args.write_rom)
    report = {**build.report, "outputs": written}
    (args.out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_pmd_encode_arabic(args: argparse.Namespace) -> int:
    result = pmd_arabic.encode_pmd_arabic_line(args.text, args.font, PmdTextBox(args.box))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_adapters(_: argparse.Namespace) -> int:
    registry = build_registry()
    payload = {
        "platforms": sorted(registry.platforms),
        "engines": sorted(registry.engines),
        "games": sorted(registry.games),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.handler(args))
    except (ClassicRetroError, OSError) as exc:
        code = exc.code.value if isinstance(exc, ClassicRetroError) else "INPUT_IO_ERROR"
        print(f"{code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
