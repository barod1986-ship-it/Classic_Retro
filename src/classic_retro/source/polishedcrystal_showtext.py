"""Strict data-driven Arabic source overlay for Polished Crystal v3.2.3 showtext.

Supports only selected, verified showtext instructions. Arabic is shaped offline
into 8x8 tile cells, with shared banked atlases to reduce duplicated font data.
Does not translate other script commands, art, battles or the entire game.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from classic_retro.arabic.logical import DIRECTION_CONTROLS
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source import polishedcrystal_opening as opening
from classic_retro.source.polishedcrystal_newbark import NAME_SAFE_POOL

RESOURCE = "polished-crystal-323-showtext.json"
SCHEMA = "classic-retro-polished-crystal-showtext-v1"
COMMIT = "3fa43192379df5c3e7b09a08e4d5d79af4f02f42"
NORMAL_POOL = tuple(range(opening.FIRST_ARABIC_CODE, opening.LAST_ARABIC_CODE + 1))
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:", re.MULTILINE)
_COMMAND = re.compile(r'\s*(text|line|cont|para)\s+"([^"]*)"\s*(?:;.*)?')
_TERMINATOR = re.compile(r"\s*done(?:\s*;.*)?")
_CONTROL = {"line": "<LINE>", "cont": "<CONT>", "para": "<PARA>"}


@dataclass(frozen=True, slots=True)
class OverworldScene:
    id: str
    file: str
    label: str
    calls: int
    player_name: bool
    lines: tuple[tuple[str, str], ...]


@dataclass
class Atlas:
    index: int
    dynamic: bool
    glyphs: dict[bytes, int]

    @property
    def pool(self) -> tuple[int, ...]:
        return NAME_SAFE_POOL if self.dynamic else NORMAL_POOL

    @property
    def font_label(self) -> str:
        return f"ClassicRetroSTA{self.index:02d}Font"

    @property
    def loader_label(self) -> str:
        return f"ClassicRetroSTA{self.index:02d}Load"

    @property
    def filename(self) -> str:
        return f"gfx/font/classic_retro_showtext_a{self.index:02d}.1bpp"


@dataclass(frozen=True)
class RenderedScene:
    scene: OverworldScene
    atlas: Atlas
    codes: tuple[tuple[int, ...], ...]


def _invalid(message: str) -> ClassicRetroError:
    return ClassicRetroError(ErrorCode.INVALID_TRANSLATION_DOCUMENT, message)


def load_scenes() -> tuple[dict[str, str], tuple[OverworldScene, ...]]:
    """Arabic only, with stable labels and pinned source revisions."""
    try:
        resource = files("classic_retro.translations").joinpath(RESOURCE)
        data = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(f"Could not load Polished Crystal overworld translations: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise _invalid("Incorrect overworld translation format")
    if data.get("version") != "3.2.3" or data.get("source_commit") != COMMIT:
        raise _invalid("Overworld source revision mismatch")
    pins = data.get("files")
    records = data.get("scenes")
    if not isinstance(pins, dict) or set(pins) != {
        "maps/NewBarkTown.asm",
        "maps/ElmsLab.asm",
    }:
        raise _invalid("Invalid pinned source map set")
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
        for value in pins.values()
    ):
        raise _invalid("Invalid Git blob SHA in source pins")
    if not isinstance(records, list) or not records:
        raise _invalid("Empty translation records")
    seen_ids: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    scenes: list[OverworldScene] = []
    for record in records:
        if not isinstance(record, dict):
            raise _invalid("Dialogue record is not an object")
        identifier = record.get("id")
        path = record.get("file")
        label = record.get("label")
        calls = record.get("calls")
        dynamic = record.get("player_name")
        rows = record.get("lines")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"ST[0-9]{2}", identifier)
            or identifier in seen_ids
            or path not in pins
            or not isinstance(label, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label)
            or (path, label) in seen_labels
            or type(calls) is not int
            or not 1 <= calls <= 8
            or type(dynamic) is not bool
            or not isinstance(rows, list)
            or not rows
        ):
            raise _invalid(f"Invalid or duplicate scene {identifier!r}")
        lines: list[tuple[str, str]] = []
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not isinstance(row[0], str)
                or not isinstance(row[1], str)
                or row[0] not in {"text", "line", "cont", "para"}
                or not row[1].strip()
                or not any("\u0600" <= c <= "\u06FF" for c in row[1])
                or any(c in row[1] for c in '<>"@\n\r\x00')
                or bool(set(row[1]) & DIRECTION_CONTROLS)
            ):
                raise _invalid(f"{identifier}: invalid Arabic line {row!r}")
            lines.append((row[0], row[1]))
        if lines[0][0] != ("line" if dynamic else "text"):
            raise _invalid(f"{identifier}: first line must follow PLAYER/new text")
        scenes.append(OverworldScene(identifier, path, label, calls, dynamic, tuple(lines)))
        seen_ids.add(identifier)
        seen_labels.add((path, label))
    return pins, tuple(scenes)


def _block(original: str, label: str) -> tuple[int, int, str]:
    """Exact top-level RGBDS text block (no ambiguous label substring match)."""
    matches = list(re.finditer(r"^" + re.escape(label) + r":\n", original, re.MULTILINE))
    if len(matches) != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"Missing or duplicate label {label}"
        )
    start = matches[0].start()
    next_label = _LABEL.search(original, matches[0].end())
    end = next_label.start() if next_label else len(original)
    return start, end, original[start:end]


def verify_original(original: str, scene: OverworldScene) -> None:
    """Reject any unseen command instead of silently destroying game behavior."""
    _, _, text = _block(original, scene.label)
    lines = text.splitlines()[1:]
    player_tokens = 0
    endings = 0
    strings = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if _TERMINATOR.fullmatch(stripped):
            endings += 1
            continue
        matched = _COMMAND.fullmatch(line)
        if matched is None or endings:
            raise ClassicRetroError(
                ErrorCode.SOURCE_BASELINE_MISMATCH,
                f"{scene.label}: unsupported original text command {stripped!r}",
            )
        strings += 1
        original_text = matched.group(2)
        player_tokens += original_text.count("<PLAYER>")
        tokens = re.findall(r"<[A-Za-z0-9_]+>", original_text)
        if any(token != "<PLAYER>" for token in tokens):
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"{scene.label}: unknown dynamic controls: {tokens}",
            )
    if endings != 1 or not strings or player_tokens != int(scene.player_name):
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH,
            f"{scene.label}: source terminator or PLAYER tokens have changed",
        )
