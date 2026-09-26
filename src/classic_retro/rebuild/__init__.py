"""The binary formats every image build writes.

- ``bps``: BPS patches, the distributable output of binary ROM overlays;
- ``lz77``: the GBA/DS BIOS LZ77 compression;
- ``blz``: the DS backward LZ of ARM9 binaries and overlays;
- ``lz_parse``: the optimal parse both LZ formats share.

Placing and checking a target's changes is ``classic_retro.patching``.
"""
