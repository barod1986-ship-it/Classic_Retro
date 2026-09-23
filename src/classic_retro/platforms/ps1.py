from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource


class PlayStationPlatformAdapter(PlatformAdapter):
    id = "ps1"
    display_name = "PlayStation"

    def probe(self, source: ProbeSource) -> ProbeResult:
        # Disc-image recognition requires a container/filesystem adapter.
        if source.read_at(0, 8) != b"PS-X EXE":
            return ProbeResult.no_match()
        return ProbeResult(
            1.0,
            ("PlayStation executable ASCII ID 'PS-X EXE' at offset 0",),
            {"container": "ps-x-exe"},
        )
