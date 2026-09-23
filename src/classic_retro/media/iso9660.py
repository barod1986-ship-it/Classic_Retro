from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

import pycdlib


class Iso9660Volume:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._iso = pycdlib.PyCdlib()
        self._iso.open_fp(stream)

    def read_file(self, iso_path: str) -> bytes:
        output = BytesIO()
        self._iso.get_file_from_iso_fp(output, iso_path=iso_path)
        return output.getvalue()

    def close(self) -> None:
        self._iso.close()

    def __enter__(self) -> Iso9660Volume:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
