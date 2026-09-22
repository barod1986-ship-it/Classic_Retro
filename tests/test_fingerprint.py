from __future__ import annotations

import hashlib

from classic_retro.core.identity import fingerprint_file


def test_fingerprint_file(tmp_path):
    payload = b"classic-retro\x00fixture"
    sample = tmp_path / "sample.bin"
    sample.write_bytes(payload)

    result = fingerprint_file(sample)

    assert result.name == "sample.bin"
    assert result.size == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
