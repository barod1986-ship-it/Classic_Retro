from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource


class NESPlatformAdapter(PlatformAdapter):
    id = "nes"
    display_name = "Nintendo Entertainment System / Famicom"

    def probe(self, source: ProbeSource) -> ProbeResult:
        if source.read_at(0, 4) != b"NES\x1a":
            return ProbeResult.no_match()
        return ProbeResult(
            1.0,
            ("iNES/NES 2.0 identification bytes 4E 45 53 1A at offset 0",),
            {"container": "ines"},
        )
