# Adapter Architecture

Version: 1

## Goal

Classic Retro must be able to add consoles, engine families, and exact game revisions without turning the core into a collection of title-specific conditionals.

The dependency direction is:

```text
Core
  ↑
Platform Adapter
  ↑
Engine Adapter
  ↑
Game Adapter
```

A game adapter selects an engine and a platform. The core never imports a specific game.

## Plugin discovery

External adapters use Python package metadata entry points.

Versioned groups:

```text
classic_retro.platforms.v1
classic_retro.engines.v1
classic_retro.games.v1
```

Each entry point resolves to either an adapter instance or a zero-argument adapter class.

This follows the plugin-discovery mechanism standardized by PyPA and exposed by Python's importlib.metadata.

References:

- https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/
- https://packaging.python.org/en/latest/specifications/entry-points/
- https://docs.python.org/3/library/importlib.metadata.html

We intentionally do not add a separate plugin framework yet. Entry points plus explicit adapter contracts are enough for the current requirements.

## Platform detection

Platform detection is based on file content, not filename extensions.

A platform probe returns:

- confidence from 0.0 to 1.0,
- human-readable evidence,
- small platform metadata.

The detector accepts only candidates above the configured minimum confidence. Equal top scores fail as ambiguous rather than silently choosing one.

Built-in identification probes currently cover:

- Game Boy
- Game Boy Color
- Game Boy Advance
- Nintendo DS, by the header's CRC-16 and the Nintendo logo's CRC (`platforms/nds.py`)
- NES/Famicom in iNES/NES 2.0 containers
- SNES/Super Famicom through internal-header heuristics
- Mega Drive/Genesis
- Nintendo 64, by the first word in any of the three common byte orders (z64,
  v64, n64); when the header is complete the probe reads it in big-endian order
  and reports the title, game code and revision, the two check code words, which
  boot code the image carries (CIC-NUS-6102 by the CRC-32 of 0x40..0x1000, else
  "unknown") and, for a known boot code with the whole first megabyte present,
  whether the check code matches it (`platforms/n64.py`, `patching/n64.py`)
- PlayStation: standalone PS-X EXE files, and CUE/BIN disc sets through the media
  layer (see the PlayStation note below)

This is identification support only. It does not mean a game is translatable yet.

### Detection references

NES iNES magic:
- https://www.nesdev.org/wiki/INES

Game Boy cartridge header:
- https://gbdev.io/pandocs/
- https://rgbds.gbdev.io/docs/v1.0.0/rgbfix.1

GBA cartridge header:
- https://mgba-emu.github.io/gbatek/

Nintendo DS cartridge header (its CRC-16 and the logo's CRC):
- https://mgba-emu.github.io/gbatek/

SNES header locations and verification heuristics:
- https://snes.nesdev.org/wiki/ROM_header
- https://snes.nesdev.org/wiki/ROM_file_formats

Mega Drive ROM header:
- https://www.plutiedev.com/rom-header

Nintendo 64 byte order, header and boot checksum:
- https://n64brew.dev/wiki/ROM_Header (the header's fields; the check code
  "calculated on 1 Mbyte of ROM contents starting from offset 0x1000")
- established z64/v64/n64 magic conventions (`80 37 12 40` as the console reads
  it, byte-swapped pairs, little-endian words); the probe converts what it reads
  to big-endian, so the same game reports the same header in all three orders.
- The CIC-NUS-6102 check code is the widely published "n64crc" computation,
  written from its description and confirmed against a real 6102 image. Only
  that boot code is implemented; images with another one report it as "unknown"
  and get no checksum verdict.
- The limit that stays: a game's identity is the SHA-256 of the file as given, so
  the same game in another byte order has another identity and matches no game
  adapter. A future N64 game adapter pins the big-endian (z64) image;
  `patching.n64.to_big_endian` gets there from the other two orders.

PlayStation executable header:
- https://psx-spx.consoledev.net/cdromfileformats/

## Exact game detection

A platform signature is not enough to modify a game safely.

A game adapter therefore declares exact revisions with SHA-256 and, when known, expected size. A game becomes `supported: true` only when one exact revision matches.

Filename, title text, product code, region text, or a platform header alone never authorizes game-specific writes.

## Engine selection

The engine is selected only after an exact game revision matches.

This is deliberate. Heuristically guessing a text engine can be useful during research, but it must not be used as authority for a destructive rebuild.

A matched game adapter names its required engine adapter. Missing engines fail explicitly.

## First-party and external adapters

First-party adapters are registered directly by Classic Retro.

Third-party packages can add adapters without editing this repository by publishing one or more of the versioned entry points.

Duplicate IDs are errors. A plugin cannot silently replace a built-in adapter.

## PlayStation note

The PlayStation probe (`platforms/ps1.py`) recognizes a standalone PS-X EXE file by its signature, which is unambiguous.

A CUE/BIN disc set is detected through the media layer ([MEDIA_LAYER.md](MEDIA_LAYER.md)): `probe_media` takes the `MediaSet` the CUE parser built, opens its data track through the sector view, reads the ISO 9660 file system with pycdlib, finds `SYSTEM.CNF` at the root, follows its `BOOT` line to the executable and checks that the file begins with `PS-X EXE`. Any missing step is no match. File extension guessing is still not used: the CUE sheet is parsed, and the content of the track decides.

## Safety rules

1. Detect platform from content.
2. Match games by exact SHA-256 revision.
3. Resolve the engine declared by the exact game adapter.
4. Refuse duplicate adapter IDs.
5. Refuse ambiguous platform detection.
6. Keep identification separate from claims of translation support.
