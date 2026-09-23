from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.core.identity import fingerprint_file
from classic_retro.media.cue import CueSheet, parse_cue
from classic_retro.media.model import MediaKind, MediaMember, MediaSet


def _resolve_cue_reference(cue_path: Path, reference: str) -> Path:
    candidates: list[Path] = []
    native = Path(reference).expanduser()
    if native.is_absolute():
        candidates.append(native)
    else:
        candidates.append(cue_path.parent / native)

    if os.name != "nt" and "\\" in reference:
        windows_path = PureWindowsPath(reference)
        if not windows_path.is_absolute():
            candidates.append(cue_path.parent.joinpath(*windows_path.parts))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise ClassicRetroError(
        ErrorCode.CUE_MEMBER_NOT_FOUND,
        f'CUE member not found: "{reference}"',
    )


def _resolve_cue(path: Path, sheet: CueSheet) -> MediaSet:
    members: list[MediaMember] = []
    fingerprint_cache: dict[Path, object] = {}

    for index, cue_file in enumerate(sheet.files, start=1):
        member_path = _resolve_cue_reference(path, cue_file.reference)
        fingerprint = fingerprint_cache.get(member_path)
        if fingerprint is None:
            fingerprint = fingerprint_file(member_path)
            fingerprint_cache[member_path] = fingerprint
        members.append(
            MediaMember(
                role=f"file-{index:02d}",
                path=member_path,
                fingerprint=fingerprint,
            )
        )

    return MediaSet(
        entry_path=path.resolve(),
        kind=MediaKind.CUE_SHEET,
        members=tuple(members),
        metadata={
            "layout_sha256": sheet.layout_sha256,
            "cue_file_count": str(len(sheet.files)),
            "track_count": str(sum(len(item.tracks) for item in sheet.files)),
        },
    )


def resolve_media(path: Path) -> MediaSet:
    path = path.expanduser()
    if not path.exists():
        raise ClassicRetroError(ErrorCode.INPUT_NOT_FOUND, f"Input does not exist: {path}")
    if not path.is_file():
        raise ClassicRetroError(ErrorCode.INPUT_NOT_FILE, f"Input is not a file: {path}")

    if path.suffix.lower() == ".cue":
        return _resolve_cue(path, parse_cue(path))

    fingerprint = fingerprint_file(path)
    return MediaSet(
        entry_path=path.resolve(),
        kind=MediaKind.SINGLE_FILE,
        members=(MediaMember(role="primary", path=path.resolve(), fingerprint=fingerprint),),
    )
