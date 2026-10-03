from __future__ import annotations

import pytest

from classic_retro.cli import main
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


def test_cue_that_is_not_utf8_or_cp1252_text_is_refused(tmp_path):
    # 0x81 is undefined in Windows-1252 and never a valid UTF-8 start byte.
    cue = tmp_path / "disc.cue"
    cue.write_bytes(b"\x81")

    with pytest.raises(ClassicRetroError) as caught:
        parse_cue(cue)

    assert caught.value.code is ErrorCode.INVALID_CUE_SHEET
    message = str(caught.value)
    assert "disc.cue" in message
    assert "UTF-8" in message and "Windows-1252" in message


def test_shift_jis_cue_is_refused_rather_than_guessed(tmp_path):
    cue = tmp_path / "disc.cue"
    encoded = 'FILE "ゲーム.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'.encode(
        "shift_jis"
    )
    assert b"\x81" in encoded
    cue.write_bytes(encoded)

    with pytest.raises(ClassicRetroError) as caught:
        resolve_media(cue)

    assert caught.value.code is ErrorCode.INVALID_CUE_SHEET


def test_cli_media_inspect_refuses_an_undecodable_cue_on_one_line(tmp_path, capsys):
    cue = tmp_path / "disc.cue"
    cue.write_bytes(b"\x81")

    assert main(["media", "inspect", str(cue)]) == 2

    err = capsys.readouterr().err
    assert err.startswith("INVALID_CUE_SHEET: ")
    assert err.count("\n") == 1 and err.endswith("\n")
    assert "disc.cue" in err


def test_cue_with_a_minutes_field_of_thousands_of_digits_is_refused(tmp_path, capsys):
    # int() refuses more than 4300 digits; at exactly 4300 it is the frame
    # count that can no longer be printed. INDEX and the gaps share the check.
    for digits in (5000, 4300):
        minutes = "1" * digits
        for timing in (
            f"INDEX 01 {minutes}:00:00",
            f"INDEX 01 00:00:00\n    PREGAP {minutes}:00:00",
        ):
            cue = tmp_path / "disc.cue"
            cue.write_text(
                f'FILE "disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    {timing}\n', encoding="utf-8"
            )

            with pytest.raises(ClassicRetroError) as caught:
                parse_cue(cue)

            assert caught.value.code is ErrorCode.INVALID_CUE_SHEET
            assert "MM:SS:FF" in str(caught.value)

            assert main(["media", "inspect", str(cue)]) == 2
            err = capsys.readouterr().err
            assert err.startswith("INVALID_CUE_SHEET: ") and err.count("\n") == 1

    # Minutes past 99, as a long disc needs, still parse.
    (tmp_path / "disc.bin").write_bytes(bytes(2352))
    cue.write_text(
        'FILE "disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 100:00:00\n', encoding="utf-8"
    )
    assert parse_cue(cue).files[0].tracks[0].indexes[0].frames == 100 * 60 * 75


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
