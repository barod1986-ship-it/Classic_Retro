"""Digests of every target's ``check-translations`` output, checked without the game.

A target's script is laid out with the reference font and its glyphs are
rasterized by FreeType, so the report and the previews change whenever the
rasterization stack (``classic_retro.core.environment``) changes, even when
no source of the toolkit did. CI has no game image to build a patch from, but
it does run ``check-translations`` for every target: recording a digest of
that output (``digests.json``, next to this module) makes any such change fail
CI instead of passing silently, and names the versions the recorded output
was made with.

What is digested:

- the report, minus its volatile keys: ``translations``, ``raster`` and
  ``digests`` say how the report was made, and the path keys (``outputs``,
  ``workspace``, ``source``, ``rom``, ``font_png``, ``widths``, ``font_binary``)
  hold where files went on one machine. The rest is serialized in canonical
  JSON (sorted keys, no spaces, unescaped non-ASCII) and hashed with SHA-256;
- each preview, as decoded pixels (mode, size and ``Image.tobytes()``), never
  as the PNG file, so a change of PNG encoder does not count as a change.

``digests.json`` maps target ids to ``{"report", "previews", "generated_with"}``;
``classic-retro targets check-translations TARGET --update-digests`` writes an
entry, ``--check-digests`` compares. A target without an entry is a difference:
CI cannot pass a target nobody has recorded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from PIL import Image

from classic_retro.core.environment import library_versions

DIGESTS_PATH = Path(__file__).with_name("digests.json")
# Keys that say how a report was made rather than what it found.
VOLATILE_KEYS = frozenset({"translations", "raster", "digests"})
# Keys whose value is a filesystem path (or a mapping of them): the same
# build on another machine writes the same files elsewhere.
PATH_KEYS = frozenset(
    {"outputs", "workspace", "source", "rom", "font_png", "widths", "font_binary"}
)

Digests = dict[str, dict[str, object]]


def report_digest(report: Mapping[str, object]) -> str:
    """SHA-256 of the report without its volatile and path keys, in canonical JSON."""
    stable = {
        key: value
        for key, value in report.items()
        if key not in VOLATILE_KEYS and key not in PATH_KEYS
    }
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preview_digest(path: Path) -> str:
    """SHA-256 of a preview's decoded image: its mode, its size, then its pixels."""
    with Image.open(path) as image:
        header = f"{image.mode}:{image.width}x{image.height}:".encode()
        return hashlib.sha256(header + image.tobytes()).hexdigest()


def digest_entry(
    report: Mapping[str, object], preview_dir: Path, previews: Iterable[str]
) -> dict[str, object]:
    """One target's entry as ``digests.json`` records it."""
    return {
        "report": report_digest(report),
        "previews": {name: preview_digest(preview_dir / name) for name in previews},
        "generated_with": library_versions(),
    }


def load_expected(path: Path | None = None) -> Digests:
    """The recorded digests by target id (``digests.json`` unless ``path`` says otherwise)."""
    path = DIGESTS_PATH if path is None else path
    return json.loads(path.read_text(encoding="utf-8"))


def save_expected(digests: Mapping[str, Mapping[str, object]], path: Path | None = None) -> None:
    """Write the digests with sorted keys and a trailing newline, so diffs stay small."""
    path = DIGESTS_PATH if path is None else path
    path.write_text(
        json.dumps(digests, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def compare(
    target_id: str,
    report: Mapping[str, object],
    preview_dir: Path,
    previews: Iterable[str],
    *,
    expected: Mapping[str, Mapping[str, object]] | None = None,
) -> list[str]:
    """Every way the target's output differs from its recorded entry, readably.

    Empty when they are equal. A target without an entry differs ("no digest
    recorded"), so a check never passes for want of a record. When something
    differs and the libraries changed since the record, the last line says
    which, since that is the usual reason.
    """
    expected = load_expected() if expected is None else expected
    entry = expected.get(target_id)
    if entry is None:
        return [f"{target_id}: no digest recorded (record it with --update-digests)"]
    differences: list[str] = []
    actual_report = report_digest(report)
    if actual_report != entry.get("report"):
        differences.append(f"report: recorded {entry.get('report')}, now {actual_report}")
    recorded_previews = entry.get("previews")
    recorded_previews = recorded_previews if isinstance(recorded_previews, Mapping) else {}
    names = list(previews)
    for name in names:
        recorded = recorded_previews.get(name)
        if not (preview_dir / name).is_file():
            differences.append(f"preview {name}: not written")
        elif recorded is None:
            differences.append(f"preview {name}: no digest recorded")
        elif recorded != (actual_preview := preview_digest(preview_dir / name)):
            differences.append(f"preview {name}: recorded {recorded}, now {actual_preview}")
    for name in sorted(set(recorded_previews) - set(names)):
        differences.append(f"preview {name}: recorded, but the target no longer writes it")
    if differences:
        differences.extend(_library_changes(entry.get("generated_with")))
    return differences


def _library_changes(recorded: object) -> list[str]:
    """One line naming the libraries whose version moved since the record, if any did."""
    if not isinstance(recorded, Mapping):
        return []
    current = library_versions()
    changed = [
        f"{name} {recorded.get(name)} -> {version}"
        for name, version in current.items()
        if recorded.get(name) != version
    ]
    return [f"libraries changed since the record: {', '.join(changed)}"] if changed else []
