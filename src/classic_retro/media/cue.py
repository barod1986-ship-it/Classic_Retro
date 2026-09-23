from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode

_FILE_RE = re.compile(r'^FILE\s+(?:"([^"]+)"|(\S+))\s+(\S+)\s*$', re.IGNORECASE)
_TRACK_RE = re.compile(r"^TRACK\s+(\d{1,2})\s+(\S+)\s*$", re.IGNORECASE)
_INDEX_RE = re.compile(
    r"^INDEX\s+(\d{1,2})\s+(\d+):(\d{1,2}):(\d{1,2})\s*$",
    re.IGNORECASE,
)
_GAP_RE = re.compile(
    r"^(PREGAP|POSTGAP)\s+(\d+):(\d{1,2}):(\d{1,2})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CueIndex:
    number: int
    frames: int


@dataclass(frozen=True, slots=True)
class CueTrack:
    number: int
    mode: str
    indexes: tuple[CueIndex, ...]
    pregap_frames: int | None = None
    postgap_frames: int | None = None

    def index(self, number: int) -> CueIndex | None:
        return next((item for item in self.indexes if item.number == number), None)


@dataclass(frozen=True, slots=True)
class CueFile:
    reference: str
    file_type: str
    tracks: tuple[CueTrack, ...]


@dataclass(frozen=True, slots=True)
class CueSheet:
    source: Path
    files: tuple[CueFile, ...]

    @property
    def layout_sha256(self) -> str:
        canonical: list[dict[str, Any]] = []
        for cue_file in self.files:
            canonical.append(
                {
                    "file_type": cue_file.file_type,
                    "tracks": [
                        {
                            "number": track.number,
                            "mode": track.mode,
                            "indexes": [
                                {"number": index.number, "frames": index.frames}
                                for index in track.indexes
                            ],
                            "pregap_frames": track.pregap_frames,
                            "postgap_frames": track.postgap_frames,
                        }
                        for track in cue_file.tracks
                    ],
                }
            )

        encoded = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


def _decode_cue(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _frames(minutes: str, seconds: str, frames: str, *, line_number: int) -> int:
    minute = int(minutes)
    second = int(seconds)
    frame = int(frames)
    if second >= 60 or frame >= 75:
        raise ClassicRetroError(
            ErrorCode.INVALID_CUE_SHEET,
            f"Invalid MM:SS:FF at line {line_number}",
        )
    return ((minute * 60) + second) * 75 + frame


def parse_cue(path: Path) -> CueSheet:
    files: list[dict[str, Any]] = []
    current_file: dict[str, Any] | None = None
    current_track: dict[str, Any] | None = None
    seen_tracks: set[int] = set()

    for line_number, raw_line in enumerate(_decode_cue(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.upper().startswith("REM "):
            continue

        match = _FILE_RE.match(line)
        if match:
            reference = match.group(1) or match.group(2)
            current_file = {
                "reference": reference,
                "file_type": match.group(3).upper(),
                "tracks": [],
            }
            files.append(current_file)
            current_track = None
            continue

        match = _TRACK_RE.match(line)
        if match:
            if current_file is None:
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"TRACK appears before FILE at line {line_number}",
                )
            number = int(match.group(1))
            if number < 1 or number > 99 or number in seen_tracks:
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"Invalid or duplicate TRACK number at line {line_number}",
                )
            seen_tracks.add(number)
            current_track = {
                "number": number,
                "mode": match.group(2).upper(),
                "indexes": [],
                "pregap_frames": None,
                "postgap_frames": None,
            }
            current_file["tracks"].append(current_track)
            continue

        match = _INDEX_RE.match(line)
        if match:
            if current_track is None:
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"INDEX appears before TRACK at line {line_number}",
                )
            number = int(match.group(1))
            indexes = current_track["indexes"]
            if any(index.number == number for index in indexes):
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"Duplicate INDEX {number:02d} at line {line_number}",
                )
            indexes.append(
                CueIndex(
                    number=number,
                    frames=_frames(
                        match.group(2),
                        match.group(3),
                        match.group(4),
                        line_number=line_number,
                    ),
                )
            )
            continue

        match = _GAP_RE.match(line)
        if match:
            if current_track is None:
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"{match.group(1).upper()} appears before TRACK at line {line_number}",
                )
            value = _frames(
                match.group(2),
                match.group(3),
                match.group(4),
                line_number=line_number,
            )
            key = "pregap_frames" if match.group(1).upper() == "PREGAP" else "postgap_frames"
            current_track[key] = value
            continue

        # Metadata commands are intentionally ignored. They do not affect track layout.
        command = line.split(maxsplit=1)[0].upper()
        if command in {
            "CATALOG",
            "CDTEXTFILE",
            "FLAGS",
            "ISRC",
            "PERFORMER",
            "SONGWRITER",
            "TITLE",
        }:
            continue

        raise ClassicRetroError(
            ErrorCode.INVALID_CUE_SHEET,
            f"Unsupported CUE command at line {line_number}: {command}",
        )

    if not files:
        raise ClassicRetroError(ErrorCode.INVALID_CUE_SHEET, "CUE contains no FILE entries")

    result_files: list[CueFile] = []
    for file_item in files:
        if not file_item["tracks"]:
            raise ClassicRetroError(
                ErrorCode.INVALID_CUE_SHEET,
                f'CUE FILE "{file_item["reference"]}" contains no TRACK entries',
            )
        tracks: list[CueTrack] = []
        for track_item in file_item["tracks"]:
            indexes = tuple(sorted(track_item["indexes"], key=lambda item: item.number))
            if not any(index.number == 1 for index in indexes):
                raise ClassicRetroError(
                    ErrorCode.INVALID_CUE_SHEET,
                    f"TRACK {track_item['number']:02d} has no INDEX 01",
                )
            tracks.append(
                CueTrack(
                    number=track_item["number"],
                    mode=track_item["mode"],
                    indexes=indexes,
                    pregap_frames=track_item["pregap_frames"],
                    postgap_frames=track_item["postgap_frames"],
                )
            )
        result_files.append(
            CueFile(
                reference=file_item["reference"],
                file_type=file_item["file_type"],
                tracks=tuple(tracks),
            )
        )

    return CueSheet(source=path, files=tuple(result_files))
