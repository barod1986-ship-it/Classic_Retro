# Classic Retro — Master Specification

Version: 0.1 (Foundation)

## 1. Purpose

Classic Retro is a reusable toolkit for Arabic localization of classic video games.

The first implementation target is **Game Boy Advance**, while the architecture must allow later support for systems such as GB/GBC, SNES, Mega Drive / Genesis, NES, and PlayStation without rewriting the Arabic localization core.

The project is not a universal "replace text in ROM" script. It is a framework that separates:

1. reusable localization logic,
2. console-specific behavior,
3. engine/family-specific behavior,
4. unavoidable game-specific overrides.

## 2. Non-goals for the foundation phase

The foundation phase will not:

- claim support for games that have not been verified,
- use hard-coded offsets as a general architecture,
- assume all GBA games share one text format,
- use naive string reversal as the Arabic solution,
- commit commercial ROMs,
- silently modify unknown ROM revisions,
- build a GUI before the underlying pipeline is stable.

## 3. Architecture

```text
classic_retro/
  core/
    detection/
    text/
    arabic/
    layout/
    validation/
    build/
  platforms/
    gba/
  engines/
  games/
  schemas/
  tools/
  tests/
  docs/
```

### 3.1 Core

The core must contain only reusable behavior.

Expected responsibilities:

- ROM identity model
- hashes and revision verification
- translation document model
- token model
- placeholders and control-code preservation
- Arabic shaping
- bidirectional text processing
- line breaking / wrapping
- glyph mapping abstraction
- validation
- build manifest
- reproducibility metadata
- diagnostics and structured errors

The core must not know game offsets.

### 3.2 Platform adapters

Platform adapters describe hardware/container concerns shared by games on one platform.

Initial platform:

```text
platforms/gba/
```

Possible responsibilities:

- GBA ROM header inspection
- address/offset conversion helpers
- platform checksum/header rules when applicable
- common graphics encodings
- common compression helpers only when genuinely platform-wide

Platform adapters must not pretend engine-specific formats are platform standards.

### 3.3 Engine / family adapters

An engine adapter represents a reusable text/resource implementation shared by a related group of games.

Possible responsibilities:

- text encoding
- control codes
- pointer formats
- script banks
- compression codecs
- font format
- text renderer behavior
- runtime variables
- dialogue window constraints

One engine adapter may support multiple titles and revisions.

### 3.4 Game adapters

A game adapter binds exact supported ROM revisions to an engine/platform implementation.

It may define:

- accepted SHA-256 hashes
- title/revision metadata
- engine selection
- ROM ranges
- resource tables
- game-specific exceptions
- build hooks

Game adapters should stay small. Reusable discoveries must move upward into the engine or platform layer.

## 4. ROM identity and safety

Every input ROM must be identified before modification.

Minimum identity data:

```yaml
platform: gba
title: Example
region: USA
revision: Rev 1
size: 16777216
sha256: ...
```

Rules:

- SHA-256 is authoritative for supported input revisions.
- CRC32 may be recorded for convenience but is not sufficient as the primary identity check.
- Unknown hashes fail closed.
- Similar filenames never imply compatible ROMs.
- A build manifest records the source hash and toolkit version.

## 5. Research-first workflow

Before implementing support for a new game:

1. identify exact ROM revision,
2. search for existing decompilation/disassembly projects,
3. search for technical documentation and ROM maps,
4. search for existing translation/hacking tools,
5. identify known compression algorithms,
6. identify text encoding and control codes,
7. identify font/renderer architecture,
8. determine pointer/reference formats,
9. determine whether text is static or dynamically composed,
10. choose the least fragile implementation strategy.

Preferred implementation order:

```text
source-level rebuild
    ↓ if unavailable/inappropriate
documented engine tooling
    ↓
binary extraction/reinsertion
    ↓
targeted reverse engineering
```

## 6. Translation data model

Human translation files are UTF-8 and independent from ROM addresses whenever possible.

Conceptual record:

```yaml
id: intro.professor.001
source: "Welcome to the world!"
translation: "مرحبًا بك في هذا العالم!"
context: "Opening dialogue"
tokens: []
constraints:
  box: dialogue
```

Stable logical IDs are preferred over raw offsets.

Offsets and addresses belong to adapter/build metadata, not translator-facing text.

## 7. Control codes and placeholders

Control codes and dynamic placeholders must never be flattened into ordinary translated text.

Conceptual representation:

```text
Welcome, {PLAYER}!{WAIT}
```

A parser must distinguish:

- visible text,
- player/item/location variables,
- waits,
- pauses,
- colors,
- line breaks,
- page breaks,
- formatting commands,
- engine opcodes.

Validation must fail when required tokens are removed, duplicated, reordered illegally, or malformed.

## 8. Arabic localization pipeline

The project must not implement Arabic as simple character reversal.

Logical pipeline:

```text
UTF-8 Arabic
  ↓
token protection
  ↓
normalization policy
  ↓
Arabic shaping
  ↓
bidi / RTL resolution
  ↓
game-aware line layout
  ↓
glyph mapping
  ↓
game encoding
```

### 8.1 Shaping

The system must support contextual Arabic forms according to the capabilities of each target renderer.

Possible strategies:

- pre-shaped glyphs generated at build time,
- runtime contextual shaping,
- hybrid rendering for dynamic strings.

The adapter declares which strategy it supports.

### 8.2 Bidirectional text

Mixed Arabic, Latin text, numbers, punctuation, and placeholders require bidi-aware handling.

Game-specific visual-order encodings may differ from normal Unicode display order. Therefore logical text and encoded display order must remain separate concepts.

### 8.3 Dynamic text

Static dialogue may be shaped at build time.

Text assembled at runtime may require:

- token-aware precomputation,
- multiple contextual variants,
- modified renderer logic,
- or runtime Arabic handling.

The toolkit must never assume static preprocessing is sufficient for every string.

## 9. Fonts and glyphs

Fonts are adapter-owned resources.

The generic font pipeline should support:

- glyph source assets,
- glyph IDs,
- contextual Arabic variants,
- fixed-width or variable-width metrics,
- tile/bitmap conversion,
- width tables,
- missing-glyph detection.

A future font compiler may transform source glyph assets into engine-specific binary formats.

## 10. Layout and wrapping

Line wrapping must use rendered width, not Unicode character count.

The layout engine should accept constraints such as:

```yaml
max_width_px: 208
max_lines: 2
line_height_px: 16
overflow: error
```

Validation should detect:

- line overflow,
- text-box overflow,
- impossible words,
- unsupported glyphs,
- malformed tokens.

Automatic wrapping must be deterministic.

## 11. Pointers and relocation

Binary adapters must model references explicitly.

Potential reference types include:

- absolute pointers,
- relative pointers,
- banked pointers,
- table indexes,
- 16/24/32-bit values,
- little/big-endian encodings,
- custom packed formats.

Text expansion must never overwrite neighboring data blindly.

Supported relocation strategies may include:

- known free-space regions,
- expanded ROM regions,
- rebuilt resource banks,
- source-level linker relocation.

Every relocation must be validated.

## 12. Compression

Compression is plugin/adapter behavior.

Conceptual interface:

```text
decode(bytes) -> bytes
encode(bytes) -> bytes
verify(original_decoded, rebuilt_decoded)
```

A codec may be:

- platform-common,
- engine-specific,
- game-specific.

No algorithm should be assigned to the platform layer merely because several games happen to use it.

## 13. Extraction and rebuild symmetry

Whenever practical:

```text
extract(original)
→ rebuild(unmodified extracted data)
→ binary/semantic verification
```

An adapter should prove that it can round-trip unchanged data before Arabic modifications are trusted.

Perfect byte identity may not be possible for every format, but semantic equivalence must be defined and tested.

## 14. Validation levels

### Level 1 — Input

- known hash
- expected size
- valid platform metadata

### Level 2 — Extraction

- tables in bounds
- pointers resolve
- resources decode
- no duplicate/overlapping ownership unless documented

### Level 3 — Translation

- required tokens preserved
- glyphs available
- line constraints satisfied
- valid Arabic processing

### Level 4 — Rebuild

- writes in bounds
- relocations valid
- pointers valid
- compressed resources decode
- no accidental overwrite

### Level 5 — Runtime

- emulator boot
- target scene reachable
- text visually verified
- no regression in surrounding UI/logic

## 15. Testing strategy

Tests should be split into:

```text
tests/unit/
tests/fixtures/
tests/adapters/
tests/integration/
```

ROMs are not committed.

Small synthetic fixtures are preferred for unit tests.

Tests involving user-supplied ROMs run locally or in an explicitly configured environment.

## 16. Build outputs

Generated output directory should be disposable and reproducible.

Possible outputs:

```text
build/
  manifest.json
  translated.rom        # local only, ignored
  patch.*
  reports/
```

Distributed project artifacts should favor patch formats rather than copyrighted original ROM content.

## 17. Error model

Errors must be explicit and actionable.

Examples:

```text
UNKNOWN_ROM_REVISION
INVALID_POINTER
UNSUPPORTED_CONTROL_CODE
MISSING_GLYPH
TEXT_OVERFLOW
RELOCATION_OVERFLOW
COMPRESSION_ROUNDTRIP_FAILED
BUILD_VALIDATION_FAILED
```

Never silently continue when corruption is possible.

## 18. Logging

Diagnostics should distinguish:

- user-facing build status,
- warnings,
- adapter research/debug information,
- binary trace details.

Normal builds should remain readable.

Verbose binary diagnostics should be opt-in.

## 19. Initial GBA milestone

The first GBA milestone is complete only when one reference game can pass the full pipeline:

```text
identify
→ extract
→ represent translation
→ Arabic-process
→ rebuild
→ validate
→ boot/test
→ generate patch
```

The first supported game is a reference implementation, not the architecture itself.

Before adding a second game, code from the first implementation must be reviewed and moved into the correct Core / Platform / Engine / Game layer.

## 20. Repository rules

- No commercial ROM files.
- No unexplained magic offsets in core code.
- Every supported revision must have explicit identity metadata.
- Every adapter must document how its text system works.
- Every binary transformation should have tests where practical.
- Research notes that affect implementation belong in the repository.
- Generated files do not become source-of-truth inputs.
- Clean rebuilds must be possible from documented inputs.

## 21. Foundation acceptance criteria

The foundation phase is accepted when:

- repository structure is agreed,
- ROM identity schema is defined,
- adapter contracts are defined,
- translation schema is defined,
- Arabic pipeline behavior is defined,
- validation/error model is defined,
- first reference-game selection criteria are defined,
- basic CI/test structure is ready.

Only then should game-specific implementation begin.
