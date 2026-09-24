"""``classic-retro targets``: what every localization target runs the same way.

Each target also keeps its own command group; these commands take a target id
instead, so a script or a CI matrix can run any target without knowing its
module.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.targets import TargetRegistry, print_json


def register_cli(subcommands: argparse._SubParsersAction, registry: TargetRegistry) -> None:
    """Every target's own command group, then the ``targets`` group."""
    for target in registry:
        target.register_cli(subcommands)

    group = subcommands.add_parser(
        "targets",
        help="List localization targets and run their checks and builds by target id",
    )
    commands = group.add_subparsers(dest="targets_command", required=True)

    listing = commands.add_parser(
        "list", help="Every target: its game, platform, strategies, documents and operations"
    )
    listing.set_defaults(handler=lambda _: print_json([t.describe() for t in registry]))

    strategies = commands.add_parser(
        "strategies",
        help="Every registered way of drawing Arabic, and the targets that use it",
    )
    strategies.set_defaults(
        handler=lambda _: print_json(
            [
                {**strategy.describe(), "targets": registry.using(strategy.id)}
                for strategy in registry.strategies
            ]
        )
    )

    hooks = commands.add_parser(
        "check-hooks",
        help="Re-assemble the hook code of targets (all of them without ids) and compare it",
    )
    hooks.add_argument("targets", nargs="*", metavar="TARGET")
    hooks.set_defaults(handler=lambda args: _check_hooks(registry, args.targets))

    check = commands.add_parser(
        "check-translations",
        help="Validate a target's script without the game image; with --font, lay it out",
    )
    check.add_argument("target")
    check.add_argument("--font", type=Path, help="Arabic TTF/OTF to draw every string with")
    check.add_argument(
        "--preview-dir", type=Path, help="With --font: write the target's previews into it"
    )
    check.set_defaults(handler=lambda args: _check_translations(registry, args))

    build = commands.add_parser(
        "build", help="Build a target's patch from its game image and compare it with the reference"
    )
    build.add_argument("target")
    build.add_argument("rom", type=Path)
    build.add_argument("--font", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument(
        "--write-rom",
        metavar="NAME",
        help="Also write the patched image into --out-dir under this name (local use only)",
    )
    build.set_defaults(handler=lambda args: _build(registry, args))


def _unsupported(target_id: str, operation: str) -> ClassicRetroError:
    return ClassicRetroError(
        ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Target {target_id} has no {operation} operation"
    )


def _check_hooks(registry: TargetRegistry, target_ids: list[str]) -> int:
    targets = (
        [registry.get(target_id) for target_id in target_ids]
        if target_ids
        else [target for target in registry if target.check_hooks is not None]
    )
    results = {}
    for target in targets:
        if target.check_hooks is None:
            raise _unsupported(target.id, "check-hooks")
        results[target.id] = target.check_hooks()
    return print_json(results)


def _check_translations(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.check_translations is None:
        raise _unsupported(target.id, "check-translations")
    if args.preview_dir is not None and args.font is None:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, "A preview needs --font")
    report = target.check_translations(args.font, args.preview_dir)
    if args.preview_dir is not None:
        missing = [name for name in target.previews if not (args.preview_dir / name).is_file()]
        if missing:
            raise ClassicRetroError(
                ErrorCode.BUILD_VALIDATION_FAILED,
                f"Target {target.id} did not write {', '.join(missing)}",
            )
    return print_json(report)


def _build(registry: TargetRegistry, args: argparse.Namespace) -> int:
    target = registry.get(args.target)
    if target.build is None:
        raise _unsupported(target.id, "build")
    report = target.build(args.rom.read_bytes(), args.font, args.out_dir, args.write_rom)
    reference = target.reference_patch_sha256
    return print_json(
        {
            **report,
            "target": target.id,
            "reference_patch_sha256": reference,
            "matches_reference": None if reference is None else report["patch_sha256"] == reference,
        }
    )
