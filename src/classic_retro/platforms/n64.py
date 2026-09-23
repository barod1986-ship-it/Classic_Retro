from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource

_MAGIC = {
    b"\x80\x37\x12\x40": "big-endian (z64)",
    b"\x37\x80\x40\x12": "byte-swapped (v64)",
    b"\x40\x12\x37\x80": "little-endian/word-swapped (n64)",
}


class N64PlatformAdapter(PlatformAdapter):
    id = "n64"
    display_name = "Nintendo 64"

    def probe(self, source: ProbeSource) -> ProbeResult:
        byte_order = _MAGIC.get(source.read_at(0, 4))
        if byte_order is None:
            return ProbeResult.no_match()
        return ProbeResult(
            1.0,
            ("Nintendo 64 ROM byte-order magic matched",),
            {"byte_order": byte_order},
        )
