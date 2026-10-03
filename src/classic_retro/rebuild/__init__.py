"""The binary formats every image build writes.

- ``bps``: BPS patches, the distributable output of binary ROM overlays;
- ``lz77``: the GBA/DS BIOS LZ77 compression;
- ``blz``: the DS backward LZ of ARM9 binaries and overlays;
- ``lz_parse``: the optimal parse both LZ formats share;
- ``mio0``: the MIO0 compression of Nintendo 64 games, and where an image's blocks lie;
- ``gtzip``: Gran Turismo's LZSS (GT-ZIP), and a changed stream packed in its
  original's place;
- ``pslz``: Gran Turismo's packed executables, unpacked as their stub does and packed
  again in place.

Placing and checking a target's changes is ``classic_retro.patching``.
"""
