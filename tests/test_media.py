from __future__ import annotations

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.media.cue import parse_cue
from classic_retro.media.model import MediaKind
from classic_retro.media.resolve import resolve_media
from classic_retro.media.sector import SectorView


def test_parse_and_resolve_cue(tmp_path):
    payload = tmp_path / "disc.bin"
    payload.write_bytes(bytes(2352 * 2))
    cue = tmp_path / "disc.cue"
    cue.write_text(
        'FILE "disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',
        encoding="utf-8",
    )

    sheet = parse_cue(cue)
    media = resolve_media(cue)

    assert sheet.files[0].tracks[0].mode == "MODE2/2352"
    assert media.kind is MediaKind.CUE_SHEET
    assert media.members[0].path == payload.resolve()
    assert len(media.identity_sha256) == 64
    assert media.metadata["track_count"] == "1"


def test_cue_missing_member_fails_closed(tmp_path):
    cue = tmp_path / "disc.cue"
    cue.write_text(
        'FILE "missing.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',
        encoding="utf-8",
    )

    with pytest.raises(ClassicRetroError) as caught:
        resolve_media(cue)

    assert caught.value.code is ErrorCode.CUE_MEMBER_NOT_FOUND


def test_sector_view_exposes_only_2048_byte_payload(tmp_path):
    raw = tmp_path / "track.bin"
    first = b"A" * 2048
    second = b"B" * 2048

    def sector(payload: bytes) -> bytes:
        return bytes(24) + payload + bytes(280)

    raw.write_bytes(sector(first) + sector(second))

    with SectorView(raw, "MODE2/2352") as view:
        assert view.logical_size == 4096
        assert view.read(2048) == first
        assert view.read(16) == second[:16]
        view.seek(2048 + 100)
        assert view.read(8) == second[100:108]
