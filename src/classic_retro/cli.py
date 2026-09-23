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
from classic_retro.media.resolve import resolve_media
from classic_retro.rebuild.model import load_rebuild_plan
from classic_retro.rebuild.pipeline import verify_round_trip
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
