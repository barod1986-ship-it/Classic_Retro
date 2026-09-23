from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource

_SYSTEM_TYPES = (b"SEGA MEGA DRIVE", b"SEGA GENESIS")


class MegaDrivePlatformAdapter(PlatformAdapter):
    id = "megadrive"
    display_name = "Mega Drive / Genesis"

    def probe(self, source: ProbeSource) -> ProbeResult:
        system_type = source.read_at(0x100, 16)
        if not any(system_type.startswith(value) for value in _SYSTEM_TYPES):
            return ProbeResult.no_match()
        label = system_type.rstrip(b" \x00").decode("ascii", errors="replace")
        return ProbeResult(
            0.99,
            ("Mega Drive system-type field at 0x100 begins with a documented SEGA identifier",),
            {"system_type": label},
        )
