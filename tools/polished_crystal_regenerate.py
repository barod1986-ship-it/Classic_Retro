"""Rebuild every piece of Polished Crystal's overlay data, in order, after the engine or the
translation moved:

    python tools/polished_crystal_regenerate.py \\
        --engine path/to/engine-clone --ref main \\
        --source path/to/pristine/polishedcrystal \\
        --fill glossary_fill.json --batches 'batches/batch-*.ar.json' --glossary-dir glossary \\
        --font NotoKufiArabic-SemiBold.ttf --preview-dir previews

1. ``polished-crystal make-engine-patch``: the engine patch from the engine branch's head;
2. ``polished-crystal make-manifest``: the manifest and pins of the patched tree, and the
   contexts (written next to ``--preview-dir``, never into the repository);
3. ``tools/polished_crystal_translations.py``: the translation file from the batches;
4. ``targets check-translations --update-digests``: the target's recorded digests.

Leave out ``--engine`` to keep the engine patch, or ``--fill``/``--batches`` to keep the
translation. Each step prints its report; the first that fails stops the run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(*command: str) -> None:
    print("$", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=REPO, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", type=Path, help="A git clone with the engine commits")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--source", type=Path, required=True, help="A pristine checkout")
    parser.add_argument("--fill", action="append", default=[])
    parser.add_argument("--batches", action="append", default=[])
    parser.add_argument("--glossary-dir", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--preview-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    # The steps run from the repository: every path the user gave is made absolute first.
    for name in ("engine", "source", "glossary_dir", "labels", "font", "preview_dir"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    args.fill = [str(Path(path).resolve()) for path in args.fill]
    args.batches = [str(Path(pattern).absolute()) for pattern in args.batches]
    cli = [sys.executable, "-m", "classic_retro"]
    args.preview_dir.mkdir(parents=True, exist_ok=True)
    contexts = args.preview_dir.parent / "polished-crystal.contexts.json"
    if args.engine is not None:
        _run(*cli, "polished-crystal", "make-engine-patch", str(args.engine), "--ref", args.ref)
    _run(*cli, "polished-crystal", "make-manifest", str(args.source), "--contexts", str(contexts))
    if args.fill or args.batches:
        command = [sys.executable, str(REPO / "tools" / "polished_crystal_translations.py")]
        for path in args.fill:
            command += ["--fill", path]
        for pattern in args.batches:
            command += ["--batches", pattern]
        if args.glossary_dir is not None:
            command += ["--glossary-dir", str(args.glossary_dir)]
        if args.labels is not None:
            command += ["--labels", str(args.labels)]
        rejects = args.preview_dir.parent / "polished-crystal.rejects.json"
        command += ["--contexts", str(contexts), "--rejects", str(rejects)]
        _run(*command)
    _run(
        *cli,
        "targets",
        "check-translations",
        "polished-crystal",
        "--font",
        str(args.font),
        "--preview-dir",
        str(args.preview_dir),
        "--update-digests",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
