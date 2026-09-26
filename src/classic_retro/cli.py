from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from classic_retro import __version__
from classic_retro.adapters.discovery import detect_input
from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError
from classic_retro.core.identity import fingerprint_file
from classic_retro.localization.commands import register_cli as register_target_cli
from classic_retro.localization.targets import build_target_registry
from classic_retro.media.resolve import resolve_media
from classic_retro.rebuild.bps import apply_bps, create_bps
from classic_retro.research.commands import register_cli as register_research_cli


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

    rebuild = subcommands.add_parser(
        "rebuild",
        help="Create and apply BPS patches",
    )
    rebuild_commands = rebuild.add_subparsers(dest="rebuild_command", required=True)

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

    register_target_cli(subcommands, build_target_registry())
    register_research_cli(subcommands)

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
