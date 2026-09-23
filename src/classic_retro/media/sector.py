from __future__ import annotations

import io
import os
from pathlib import Path

from classic_retro.core.errors import ClassicRetroError, ErrorCode

_LAYOUTS = {
    "MODE1/2048": (2048, 0),
    "MODE1/2352": (2352, 16),
    "MODE2/2352": (2352, 24),
}


class SectorView(io.RawIOBase):
    """Read-only 2048-byte logical view over common CD data-track sector layouts."""

    def __init__(
        self,
        path: Path,
        track_mode: str,
        *,
        start_sector: int = 0,
        sector_count: int | None = None,
    ) -> None:
        super().__init__()
        mode = track_mode.upper()
        if mode not in _LAYOUTS:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_TRACK_MODE,
                f"Unsupported data-track mode: {track_mode}",
            )
        if start_sector < 0 or sector_count is not None and sector_count < 0:
            raise ValueError("sector offsets and counts must be non-negative")

        self._path = path
        self._stream = path.open("rb")
        self._physical_size, self._data_offset = _LAYOUTS[mode]
        self._start_sector = start_sector
        file_size = path.stat().st_size
        available = max(0, (file_size // self._physical_size) - start_sector)
        if sector_count is None:
            sector_count = available
        if sector_count > available:
            raise ClassicRetroError(
                ErrorCode.INVALID_MEDIA_LAYOUT,
                "Track extends beyond the referenced file",
            )
        self._sector_count = sector_count
        self._size = sector_count * 2048
        self._position = 0

    @property
    def logical_size(self) -> int:
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            target = offset
        elif whence == os.SEEK_CUR:
            target = self._position + offset
        elif whence == os.SEEK_END:
            target = self._size + offset
        else:
            raise ValueError(f"Unsupported whence: {whence}")
        if target < 0:
            raise ValueError("negative seek position")
        self._position = min(target, self._size)
        return self._position

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("I/O operation on closed file")
        remaining = self._size - self._position
        if size is None or size < 0:
            size = remaining
        else:
            size = min(size, remaining)
        if size <= 0:
            return b""

        output = bytearray()
        while size:
            sector_index, offset_in_sector = divmod(self._position, 2048)
            chunk_size = min(size, 2048 - offset_in_sector)
            physical_offset = (
                (self._start_sector + sector_index) * self._physical_size
                + self._data_offset
                + offset_in_sector
            )
            self._stream.seek(physical_offset)
            chunk = self._stream.read(chunk_size)
            if len(chunk) != chunk_size:
                raise ClassicRetroError(
                    ErrorCode.INVALID_MEDIA_LAYOUT,
                    "Unexpected end of physical sector data",
                )
            output.extend(chunk)
            self._position += chunk_size
            size -= chunk_size

        return bytes(output)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed:
            self._stream.close()
        super().close()
