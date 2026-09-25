"""``classic-retro research``: run a game from a script, and scan its image.

Every command prints JSON, except ``disasm``, which prints the listing.
Addresses on the command line and in reports include the image's base: a Game
Boy Advance image is detected and starts at ``0x08000000``; any other starts at
0 unless ``--base`` says otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from classic_retro.adapters.base import ProbeSource
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.patching.image import GBA_ROM_BASE
from classic_retro.platforms.gba import GBAPlatformAdapter
from classic_retro.research.disasm import MODES, disassemble
from classic_retro.research.emulator import Emulator
from classic_retro.research.libretro import LibretroEmulator
from classic_retro.research.mgba import MgbaEmulator, build_harness
from classic_retro.research.scan import (
    ascii_strings,
    find_pattern,
    find_references,
    free_space,
    parse_pattern,
    pointer_tables,
    relative_search,
    table_strings,
)
from classic_retro.research.script import parse_script, run_script
from classic_retro.research.tables import load_table

DEFAULT_LIMIT = 500


def _integer(text: str) -> int:
    try:
        value = int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number (decimal or 0x hex)") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text} cannot be negative")
    return value


def _byte(text: str) -> int:
    value = _integer(text)
    if value > 0xFF:
        raise argparse.ArgumentTypeError(f"{text} is not a byte")
    return value


def _range(text: str) -> tuple[int, int]:
    """``ADDRESS`` or ``START:END`` (END exclusive)."""
    low, colon, high = text.partition(":")
    start = _integer(low)
    end = _integer(high) if colon else start + 1
    if end <= start:
        raise argparse.ArgumentTypeError(f"{text}: the end must be above the start")
    return start, end


def _address(value: int) -> str:
    return f"0x{value:08X}"


@dataclass(frozen=True, slots=True)
class _Image:
    path: Path
    data: bytes
    base: int
    platform: str | None
    # The scanned offsets.
    start: int
    end: int

    def header(self) -> dict[str, object]:
        return {
            "image": str(self.path),
            "size": len(self.data),
            "platform": self.platform,
            "base": _address(self.base),
        }

    def where(self, offset: int) -> dict[str, str]:
        return {"address": _address(self.base + offset), "offset": f"0x{offset:X}"}

    def offset(self, address: int, option: str) -> int:
        return _offset(address, self.base, len(self.data), option)


def _offset(address: int, base: int, size: int, option: str) -> int:
    if not base <= address <= base + size:
        raise ClassicRetroError(
            ErrorCode.INVALID_BYTE_RANGE,
            f"{option} {_address(address)} is outside the image "
            f"({_address(base)}..{_address(base + size)}; addresses include the base, see --base)",
        )
    return address - base


def _open(args: argparse.Namespace) -> _Image:
    data = args.image.read_bytes()
    gba = GBAPlatformAdapter().probe(ProbeSource(args.image)).confidence > 0
    base = args.base if args.base is not None else (GBA_ROM_BASE if gba else 0)
    start = 0 if args.start is None else _offset(args.start, base, len(data), "--start")
    end = len(data) if args.end is None else _offset(args.end, base, len(data), "--end")
    if end < start:
        raise ClassicRetroError(ErrorCode.INVALID_BYTE_RANGE, "--end is before --start")
    return _Image(args.image, data, base, "gba" if gba else None, start, end)


def _image_arguments(parser: argparse.ArgumentParser, *, limit: bool = True) -> None:
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--base",
        type=_integer,
        help="The image's first address (default: 0x08000000 for GBA, else 0)",
    )
    parser.add_argument("--start", type=_integer, help="Scan from this address")
    parser.add_argument("--end", type=_integer, help="Scan up to this address")
    if limit:
        parser.add_argument(
            "--limit",
            type=_integer,
            default=DEFAULT_LIMIT,
            help=f"Report at most this many results (default {DEFAULT_LIMIT}; 0: all)",
        )


def _pointer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--width", type=int, choices=(2, 3, 4), default=4, help="Bytes a pointer")
    parser.add_argument("--byteorder", choices=("little", "big"), default="little")
    parser.add_argument(
        "--align", type=_integer, default=None, help="Pointer alignment (default: the width)"
    )


def _listed(items: Sequence[object], limit: int) -> tuple[Sequence[object], dict[str, object]]:
    shown = items if limit == 0 else items[:limit]
    return shown, {"count": len(items), "truncated": len(shown) < len(items)}


def _print(payload: object) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def register_cli(subcommands: argparse._SubParsersAction) -> None:
    group = subcommands.add_parser(
        "research",
        help="Study a game: run it from a script of emulator commands, and scan its image",
    )
    commands = group.add_subparsers(dest="research_command", required=True)

    run = commands.add_parser(
        "run",
        help="Run a game from a script: keys, frames, screenshots, savestates, memory, "
        "breakpoints (docs/RESEARCH_TOOLS.md)",
    )
    run.add_argument("image", type=Path)
    run.add_argument("script", help="The script file, or - to read it from standard input")
    run.add_argument(
        "--core", type=Path, help="Run under this libretro core instead of the mGBA harness"
    )
    run.add_argument(
        "--option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set a libretro core option (repeatable)",
    )
    run.add_argument("--system-dir", type=Path, help="The libretro system directory (BIOS files)")
    run.add_argument("--harness", type=Path, help="Use this mGBA harness binary")
    run.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Where the script's relative paths lead (default: the current directory)",
    )
    run.set_defaults(handler=_run)

    harness = commands.add_parser(
        "build-harness", help="Build the mGBA harness now (it is also built on first use)"
    )
    harness.add_argument("--out-dir", type=Path, help="Build into this directory, not the cache")
    harness.set_defaults(handler=lambda args: _print({"harness": str(build_harness(args.out_dir))}))

    free = commands.add_parser(
        "free-space", help="Runs of padding bytes long enough for new code, fonts or text"
    )
    _image_arguments(free)
    free.add_argument(
        "--fill",
        type=_byte,
        action="append",
        help="A padding byte (repeatable; default: 0xFF and 0x00)",
    )
    free.add_argument("--min-size", type=_integer, default=256, help="Smallest run (default 256)")
    free.add_argument(
        "--align", type=_integer, default=4, help="Align each run's start (default 4)"
    )
    free.set_defaults(handler=_free_space)

    pointers = commands.add_parser(
        "pointers", help="Every pointer to an address or into a range of addresses"
    )
    _image_arguments(pointers)
    pointers.add_argument(
        "--to",
        type=_range,
        action="append",
        required=True,
        metavar="ADDRESS|START:END",
        help="What the pointers point to (repeatable; END is exclusive)",
    )
    _pointer_arguments(pointers)
    pointers.set_defaults(handler=_pointers)

    tables = commands.add_parser(
        "pointer-tables", help="Runs of consecutive entries that all point into the image"
    )
    _image_arguments(tables)
    _pointer_arguments(tables)
    tables.add_argument(
        "--stride", type=_integer, help="Bytes from one entry to the next (default: the width)"
    )
    tables.add_argument(
        "--min-count", type=_integer, default=8, help="Fewest entries a table (default 8)"
    )
    tables.add_argument(
        "--into",
        type=_range,
        metavar="START:END",
        help="Entries must point into this range (default: the whole image)",
    )
    tables.set_defaults(handler=_pointer_tables)

    text = commands.add_parser(
        "text", help="Strings: printable ASCII, or the game's own codes with a .tbl table"
    )
    _image_arguments(text)
    text.add_argument("--table", type=Path, help="Decode with this text table (.tbl)")
    text.add_argument(
        "--min-length", type=_integer, default=8, help="Fewest characters a string (default 8)"
    )
    text.set_defaults(handler=_text)

    relative = commands.add_parser(
        "relative-search",
        help="Find a known word in an unknown encoding whose letters are consecutive codes",
    )
    _image_arguments(relative)
    relative.add_argument("word", help="Three or more letters, all of one case")
    relative.set_defaults(handler=_relative_search)

    find = commands.add_parser("find", help="Every match of a byte pattern (?? for any byte)")
    _image_arguments(find)
    find.add_argument("pattern", help='Hex bytes, e.g. "70 47 ?? B5", or ASCII with --ascii')
    find.add_argument("--ascii", action="store_true", help="The pattern is ASCII text")
    find.set_defaults(handler=_find)

    disasm = commands.add_parser("disasm", help="Disassemble ARM7TDMI code (Thumb or ARM)")
    _image_arguments(disasm, limit=False)
    disasm.add_argument(
        "address", type=_integer, help="Where to start; an odd address means Thumb code"
    )
    disasm.add_argument(
        "--length", type=_integer, default=64, help="Bytes to disassemble (default 64)"
    )
    disasm.add_argument("--mode", choices=MODES, help="Thumb or ARM (default: Thumb)")
    disasm.add_argument("--objdump", help="The objdump to run (default: arm-none-eabi-objdump)")
    disasm.set_defaults(handler=_disasm)


def _run(args: argparse.Namespace) -> int:
    image = args.image.read_bytes()
    if args.script == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.script).read_text(encoding="utf-8")
    steps = parse_script(text)
    options = {}
    for item in args.option:
        key, equals, value = item.partition("=")
        if not equals or not key:
            raise ClassicRetroError(
                ErrorCode.INVALID_EMULATOR_SCRIPT, f"--option takes KEY=VALUE, not {item!r}"
            )
        options[key] = value
    emulator: Emulator
    if args.core is not None:
        if args.harness is not None:
            raise ClassicRetroError(
                ErrorCode.INVALID_EMULATOR_SCRIPT, "--harness is for the mgba backend, not --core"
            )
        emulator = LibretroEmulator(
            args.core, args.image, options=options, system_dir=args.system_dir
        )
    else:
        if options or args.system_dir is not None:
            raise ClassicRetroError(
                ErrorCode.INVALID_EMULATOR_SCRIPT,
                "--option and --system-dir set a libretro core: give --core",
            )
        emulator = MgbaEmulator(args.image, harness=args.harness)
    with emulator:
        report = run_script(emulator, steps, args.out_dir)
        payload = {
            "image": str(args.image),
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "backend": emulator.backend,
            "core": emulator.core,
            "platform": emulator.platform,
            **report,
        }
    return _print(payload)


def _free_space(args: argparse.Namespace) -> int:
    image = _open(args)
    fills = args.fill or [0xFF, 0x00]
    runs = free_space(
        image.data,
        fills=fills,
        min_size=args.min_size,
        align=max(args.align, 1),
        start=image.start,
        end=image.end,
    )
    totals = {f"0x{fill:02X}": sum(run.size for run in runs if run.fill == fill) for fill in fills}
    shown, listing = _listed(runs, args.limit)
    return _print(
        {
            **image.header(),
            "fills": [f"0x{fill:02X}" for fill in fills],
            "min_size": args.min_size,
            "align": args.align,
            "free_bytes": totals,
            "largest": max((run.size for run in runs), default=0),
            **listing,
            "runs": [
                {
                    **image.where(run.offset),
                    "size": run.size,
                    "end": _address(image.base + run.offset + run.size),
                    "fill": f"0x{run.fill:02X}",
                }
                for run in shown
            ],
        }
    )


def _pointer_options(args: argparse.Namespace) -> tuple[int, str, int]:
    return args.width, args.byteorder, args.align or args.width


def _pointers(args: argparse.Namespace) -> int:
    image = _open(args)
    width, byteorder, align = _pointer_options(args)
    found = find_references(
        image.data,
        args.to,
        width=width,
        byteorder=byteorder,
        align=align,
        start=image.start,
        end=image.end,
    )
    shown, listing = _listed(found, args.limit)
    return _print(
        {
            **image.header(),
            "width": width,
            "byteorder": byteorder,
            "align": align,
            "targets": [
                _address(low) if high == low + 1 else f"{_address(low)}:{_address(high)}"
                for low, high in args.to
            ],
            **listing,
            "references": [
                {**image.where(reference.offset), "value": _address(reference.value)}
                for reference in shown
            ],
        }
    )


def _pointer_tables(args: argparse.Namespace) -> int:
    image = _open(args)
    width, byteorder, align = _pointer_options(args)
    target = args.into or (image.base, image.base + len(image.data))
    found = pointer_tables(
        image.data,
        target=target,
        width=width,
        byteorder=byteorder,
        align=align,
        stride=args.stride,
        min_count=args.min_count,
        start=image.start,
        end=image.end,
    )
    shown, listing = _listed(found, args.limit)
    return _print(
        {
            **image.header(),
            "width": width,
            "byteorder": byteorder,
            "align": align,
            "into": f"{_address(target[0])}:{_address(target[1])}",
            "min_count": args.min_count,
            **listing,
            "tables": [
                {
                    **image.where(table.offset),
                    "count": table.count,
                    "stride": table.stride,
                    "lowest": _address(table.lowest),
                    "highest": _address(table.highest),
                    "ascending": table.ascending,
                    "odd": table.odd,
                }
                for table in shown
            ],
        }
    )


def _text(args: argparse.Namespace) -> int:
    image = _open(args)
    if args.table is not None:
        table = load_table(args.table)
        runs = list(
            table_strings(
                image.data, table, min_length=args.min_length, start=image.start, end=image.end
            )
        )
    else:
        runs = ascii_strings(
            image.data, min_length=args.min_length, start=image.start, end=image.end
        )
    shown, listing = _listed(runs, args.limit)
    return _print(
        {
            **image.header(),
            "encoding": "ascii" if args.table is None else "table",
            "table": None if args.table is None else str(args.table),
            "min_length": args.min_length,
            **listing,
            "strings": [
                {
                    **image.where(run.offset),
                    "size": run.size,
                    "terminated": run.terminated,
                    "text": run.text,
                }
                for run in shown
            ],
        }
    )


def _preview(data: bytes, offset: int, size: int, alphabet: int, letter: str) -> str:
    """The bytes around a match read with the implied alphabet; other bytes as dots."""
    window = data[max(0, offset - 8) : offset + size + 24]
    return "".join(
        chr(ord(letter) + byte - alphabet) if alphabet <= byte < alphabet + 26 else "."
        for byte in window
    )


def _relative_search(args: argparse.Namespace) -> int:
    image = _open(args)
    found = relative_search(image.data, args.word, start=image.start, end=image.end)
    letter = "A" if args.word.isupper() else "a"
    shown, listing = _listed(found, args.limit)
    return _print(
        {
            **image.header(),
            "word": args.word,
            **listing,
            "matches": [
                {
                    **image.where(match.offset),
                    "code": f"0x{match.code:02X}",
                    letter: f"0x{match.alphabet:02X}" if 0 <= match.alphabet <= 0xFF else None,
                    "preview": _preview(
                        image.data, match.offset, len(args.word), match.alphabet, letter
                    ),
                }
                for match in shown
            ],
        }
    )


def _find(args: argparse.Namespace) -> int:
    image = _open(args)
    hex_pattern = args.pattern.encode("ascii").hex() if args.ascii else args.pattern
    found = find_pattern(image.data, parse_pattern(hex_pattern), start=image.start, end=image.end)
    shown, listing = _listed(found, args.limit)
    return _print(
        {
            **image.header(),
            "pattern": args.pattern,
            **listing,
            "matches": [image.where(offset) for offset in shown],
        }
    )


def _disasm(args: argparse.Namespace) -> int:
    image = _open(args)
    address = args.address
    mode = args.mode or "thumb"
    if address & 1:
        if args.mode == "arm":
            raise ClassicRetroError(
                ErrorCode.INVALID_BYTE_RANGE, "ARM code starts at an even address"
            )
        address &= ~1
    offset = image.offset(address, "the address")
    code = image.data[offset : offset + args.length]
    for line in disassemble(code, address, mode=mode, objdump=args.objdump):
        print(line)
    return 0
