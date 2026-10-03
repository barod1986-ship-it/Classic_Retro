from __future__ import annotations

from classic_retro.adapters.base import PlatformAdapter, ProbeResult, ProbeSource
from classic_retro.patching.n64 import (
    BOOT_CODE_END,
    CHECKSUM_END,
    CHECKSUM_SEEDS,
    HEADER_SIZE,
    MAGIC_N64,
    MAGIC_V64,
    MAGIC_Z64,
    N64Header,
    boot_code,
    header_checksum,
    to_big_endian,
)

_MAGIC = {
    MAGIC_Z64: "big-endian (z64)",
    MAGIC_V64: "byte-swapped (v64)",
    MAGIC_N64: "little-endian/word-swapped (n64)",
}


class N64PlatformAdapter(PlatformAdapter):
    id = "n64"
    display_name = "Nintendo 64"

    def probe(self, source: ProbeSource) -> ProbeResult:
        byte_order = _MAGIC.get(source.read_at(0, 4))
        if byte_order is None:
            return ProbeResult.no_match()
        evidence = ["Nintendo 64 ROM byte-order magic matched"]
        metadata = {"byte_order": byte_order}
        if source.size >= HEADER_SIZE:
            # As much of the image as the header, the boot code and the check code
            # need, whole words of it, so any byte order converts.
            length = next(n for n in (CHECKSUM_END, BOOT_CODE_END, HEADER_SIZE) if source.size >= n)
            image = to_big_endian(source.read_at(0, length))
            header = N64Header.read(image)
            crc1, crc2 = header.checksum
            metadata["title"] = header.title
            metadata["game_code"] = header.game_code
            metadata["revision"] = str(header.revision)
            metadata["header_checksum"] = f"{crc1:08X} {crc2:08X}"
            name = boot_code(image)
            metadata["boot_code"] = name or "unknown"
            if name is not None:
                evidence.append(f"{name} boot code identified by its CRC-32")
            if name in CHECKSUM_SEEDS and len(image) >= CHECKSUM_END:
                valid = header_checksum(image) == header.checksum
                metadata["checksum_valid"] = "true" if valid else "false"
                evidence.append(
                    "Header check code matches the megabyte after the boot code"
                    if valid
                    else "Header check code does not match the megabyte after the boot code"
                )
        return ProbeResult(1.0, tuple(evidence), metadata)
