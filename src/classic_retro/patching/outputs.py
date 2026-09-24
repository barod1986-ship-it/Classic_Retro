"""What every overlay build reports and writes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from classic_retro.rebuild.bps import BpsPatch


def base_report(game: str, rom: bytes, output: bytes, patch: BpsPatch) -> dict[str, object]:
    """The identity fields every build report starts with."""
    return {
        "game": game,
        "base_sha1": hashlib.sha1(rom).hexdigest(),
        "base_sha256": hashlib.sha256(rom).hexdigest(),
        "target_sha256": hashlib.sha256(output).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.data).hexdigest(),
        "patch_bytes": len(patch.data),
        "target_bytes": len(output),
    }


def write_patch(out_dir: Path, name: str, patch: BpsPatch) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_bytes(patch.data)
    return path


def write_image(out_dir: Path, name: str | None, rom: bytes) -> dict[str, str]:
    """The patched image under ``name`` (local use only), if asked for."""
    if not name:
        return {}
    path = out_dir / name
    path.write_bytes(rom)
    return {"rom": str(path)}
