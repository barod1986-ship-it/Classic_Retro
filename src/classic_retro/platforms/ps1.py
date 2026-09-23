from __future__ import annotations

import re

from pycdlib import pycdlibexception

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource
from classic_retro.core.errors import ClassicRetroError
from classic_retro.media.iso9660 import Iso9660Volume
from classic_retro.media.model import MediaKind, MediaSet
from classic_retro.media.optical import open_data_track

_BOOT_RE = re.compile(
    rb"^\s*BOOT\s*=\s*cdrom:\s*(\\?[^\r\n\s]+)",
    re.IGNORECASE | re.MULTILINE,
)


def _boot_iso_path(system_cnf: bytes) -> str | None:
    match = _BOOT_RE.search(system_cnf)
    if match is None:
        return None
    value = match.group(1).decode("ascii", errors="strict")
    value = value.replace("\\", "/")
    if not value.startswith("/"):
        value = "/" + value
    return value.upper()


class PlayStationPlatformAdapter(PlatformAdapter):
    id = "ps1"
    display_name = "PlayStation"

    def probe(self, source: ProbeSource) -> ProbeResult:
        if source.read_at(0, 8) != b"PS-X EXE":
            return ProbeResult.no_match()
        return ProbeResult(
            1.0,
            ("PlayStation executable ASCII ID 'PS-X EXE' at offset 0",),
            {"container": "ps-x-exe"},
        )

    def probe_media(self, media: MediaSet) -> ProbeResult:
        if media.kind is not MediaKind.CUE_SHEET:
            return ProbeResult.no_match()

        try:
            with open_data_track(media) as stream, Iso9660Volume(stream) as volume:
                system_cnf = volume.read_file("/SYSTEM.CNF;1")
                boot_path = _boot_iso_path(system_cnf)
                if boot_path is None:
                    return ProbeResult.no_match()
                executable = volume.read_file(boot_path)
        except (
            ClassicRetroError,
            OSError,
            UnicodeDecodeError,
            pycdlibexception.PyCdlibException,
        ):
            return ProbeResult.no_match()

        if not executable.startswith(b"PS-X EXE"):
            return ProbeResult.no_match()

        return ProbeResult(
            1.0,
            (
                "CUE contains a supported CD data track",
                "ISO9660 filesystem contains SYSTEM.CNF",
                "SYSTEM.CNF boot target begins with the PS-X EXE signature",
            ),
            {"container": "cue-bin", "boot_executable": boot_path},
        )
