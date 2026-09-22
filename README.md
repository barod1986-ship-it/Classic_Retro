# Classic Retro Arabic Translation Toolkit

A clean-room toolkit for researching, extracting, translating, rebuilding, and validating Arabic localizations for classic video games.

## Project direction

The project starts with **Game Boy Advance (GBA)**, but the architecture is intentionally not tied to one game or one console.

The core model is:

```text
Platform -> Engine / Family -> Game Adapter
```

Reusable Arabic localization logic stays in the core. Platform, engine, and game-specific behavior stays in adapters.

## Core principles

- Research the exact game revision before editing anything.
- Prefer an existing source-matching decompilation/disassembly when appropriate.
- Do not assume two games on the same console use the same text engine.
- Keep Arabic shaping, bidi/RTL handling, tokenization, wrapping, and glyph mapping reusable.
- Keep game-specific offsets, pointers, compression, control codes, and rendering behavior outside the core.
- Build reproducibly from a verified original ROM supplied by the user.
- Never commit copyrighted ROM images to this repository.
- Produce patches/build outputs, not redistributed commercial ROMs.
- Validate every supported revision by hashes and automated checks.
- Document discoveries before turning them into assumptions.

## Initial pipeline

```text
Verified ROM
   |
Game / Revision Detection
   |
Research + Engine Identification
   |
Extractor
   |-- text
   |-- control codes
   |-- pointers
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
   |-- pointer repair
   |-- compression
   |-- font build
   |-- checksums
   |
Validation
   |
Patch / Build Artifact
```

## Repository status

**Foundation phase.**

No previous implementation is treated as authoritative. The project is being rebuilt from a clean base with documented architecture and reproducible tooling.

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md).
