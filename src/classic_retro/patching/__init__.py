"""Shared machinery of binary ROM overlays.

Every binary target follows the same recipe: verify the exact input image and
every byte it replaces, place hook code and data in free space, point the
game's references at them, read everything back, and ship a BPS patch. This
package holds the parts that do not depend on the game:

- ``image``: the pinned image identity, address/offset conversion, reference
  scans, free-space checks;
- ``hooks``: hook programs stored as bytes and re-assembled from source with a
  pluggable assembler per CPU;
- ``outputs``: the build report's common fields and the patch/image files;
- ``nitro``: Nintendo DS images: the header, NitroFS, NARC archives and the
  ARM9 binary, rebuilt with a file replaced or moved.

CPU-specific encoders live in ``classic_retro.cpu``.
"""
