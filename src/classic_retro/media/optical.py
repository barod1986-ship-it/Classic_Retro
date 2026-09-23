from __future__ import annotations

from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.media.cue import CueFile, CueSheet, CueTrack, parse_cue
from classic_retro.media.model import MediaKind, MediaSet
from classic_retro.media.sector import SectorView

_DATA_TRACK_MODES = {"MODE1/2048", "MODE1/2352", "MODE2/2352"}


@dataclass(frozen=True, slots=True)
class DataTrack:
    file_index: int
    cue_file: CueFile
    track: CueTrack
    start_sector: int


def cue_sheet(media: MediaSet) -> CueSheet:
    if media.kind is not MediaKind.CUE_SHEET:
        raise ClassicRetroError(
            ErrorCode.INVALID_MEDIA_LAYOUT,
            "Media input is not a CUE sheet",
        )
    return parse_cue(media.entry_path)


def first_data_track(media: MediaSet) -> DataTrack:
    sheet = cue_sheet(media)
    for file_index, cue_file in enumerate(sheet.files):
        for track in cue_file.tracks:
            if track.mode not in _DATA_TRACK_MODES:
                continue
            index = track.index(1)
            if index is None:
                continue
            if cue_file.file_type != "BINARY":
                raise ClassicRetroError(
                    ErrorCode.INVALID_MEDIA_LAYOUT,
                    f"Data track references unsupported FILE type {cue_file.file_type}",
                )
            return DataTrack(
                file_index=file_index,
                cue_file=cue_file,
                track=track,
                start_sector=index.frames,
            )
    raise ClassicRetroError(
        ErrorCode.INVALID_MEDIA_LAYOUT,
        "CUE contains no supported data track",
    )


def open_data_track(media: MediaSet) -> SectorView:
    data_track = first_data_track(media)
    member = media.members[data_track.file_index]
    return SectorView(
        member.path,
        data_track.track.mode,
        start_sector=data_track.start_sector,
    )
