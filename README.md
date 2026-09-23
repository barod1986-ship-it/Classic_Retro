# Classic Retro Arabic Translation Toolkit

A clean-room toolkit for researching, extracting, translating, rebuilding, and validating Arabic localizations for classic video games.

## Project direction

Classic Retro is **multi-platform from the foundation**. It is not a GBA project that may later expand to other consoles.

The architecture is designed for classic systems including, but not limited to:

- Game Boy / Game Boy Color
- Game Boy Advance
- NES / Famicom
- SNES / Super Famicom
- Mega Drive / Genesis
- PlayStation
- Nintendo 64
- other classic systems when a verified adapter is added

No platform is the architectural center of the project.

The core model is:

```text
Platform -> Engine / Family -> Game Adapter
```

Reusable Arabic localization logic stays in the core. Platform, engine, and game-specific behavior stays in adapters.

## Core principles

- Research the exact game revision before editing anything.
- Prefer an existing source-matching decompilation/disassembly when appropriate.
- Do not assume two games on the same console use the same text engine.
- Do not assume one console is the default or primary platform.
- Keep Arabic shaping, bidi/RTL handling, tokenization, wrapping, and glyph mapping reusable.
- Keep game-specific offsets, pointers, compression, control codes, and rendering behavior outside the core.
- Build reproducibly from a verified original game image supplied by the user.
- Never commit copyrighted ROM/disc images to this repository.
- Produce patches/build outputs, not redistributed commercial game images.
- Validate every supported revision by hashes and automated checks.
- Document discoveries before turning them into assumptions.

## Initial pipeline

```text
Verified Game Image
   |
Platform + Game / Revision Detection
   |
Research + Engine Identification
   |
Extractor
   |-- text
   |-- control codes
   |-- pointers / references
   |-- fonts / graphics metadata
   |
Translation Source (UTF-8 Arabic)
   |
Arabic Pipeline
   |-- tokenization
   |-- shaping
   |-- bidi / RTL
   |-- wrapping
   |-- glyph mapping
   |
Rebuild
   |-- relocation
   |-- reference repair
   |-- compression
   |-- font build
   |-- platform-specific finalization
   |
Validation
   |
Patch / Build Artifact
```

## Repository status

**Foundation toolkit with a playable FireRed Rev 1 reference patch.**

The first end-to-end example translates the 13 Professor OAK speech strings in
the new-game intro. This is a renderer/font test, not a complete game translation.
Other platforms currently have detection or foundation components; they do not
all have playable Arabic adapters.

Install with `python -m pip install -e ".[dev]"`, run `pytest`, and identify your
own input with `classic-retro detect "path/to/game.gba"`.

See [the Arabic FireRed testing guide](docs/FIRERED_ARABIC_TEST_AR.md) for applying
the reference BPS patch, the exact supported ROM, and the current limits.

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md).
