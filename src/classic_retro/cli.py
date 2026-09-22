from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from classic_retro import __version__
from classic_retro.core.errors import ClassicRetroError
from classic_retro.core.identity import fingerprint_file


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

    return parser


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    result = fingerprint_file(args.path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.handler(args))
    except ClassicRetroError as exc:
        print(f"{exc.code.value}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
