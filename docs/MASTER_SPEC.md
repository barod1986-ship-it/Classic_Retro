# Classic Retro — Master Specification

Version: 0.2 (Multi-platform Foundation)

## 1. Purpose

Classic Retro is a reusable toolkit for Arabic localization of classic video games across multiple systems.

It is **not centered on Game Boy Advance or any other single console**. Platform support is added through adapters while the Arabic localization core remains shared.

Target systems may include:

- Game Boy / Game Boy Color
- Game Boy Advance
- NES / Famicom
- SNES / Super Famicom
- Mega Drive / Genesis
- PlayStation
- Nintendo 64
- additional classic platforms when their formats and workflows are understood and verified

The project is not a universal "replace text in ROM" script. It is a framework that separates:

1. reusable localization logic,
2. console/platform-specific behavior,
3. engine/family-specific behavior,
4. unavoidable game-specific overrides.

## 2. Non-goals for the foundation phase

The foundation phase will not:

- claim support for games or platforms that have not been verified,
- use hard-coded offsets as a general architecture,
- assume games on the same console share one text format,
- assume cartridge-based and disc-based systems use the same storage model,
- use naive string reversal as the Arabic solution,
- commit commercial ROM or disc images,
- silently modify unknown revisions,
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
    gb/
    gbc/
    gba/
    nes/
    snes/
    megadrive/
    ps1/
    n64/
  engines/
  games/
  schemas/
  tools/
  tests/
  docs/
```

Platform directories are created when real support work begins; the list above describes the intended adapter model, not a claim that all platforms are already implemented.

### 3.1 Core

The core must contain only reusable behavior.

Expected responsibilities:

- game-image identity model
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

The core must not know game-specific offsets, sectors, archives, banks, or addresses.

### 3.2 Platform adapters

Platform adapters describe hardware/container concerns shared by games on one system.

Examples of possible responsibilities:

- ROM/header inspection
- cartridge banking/address conversion
- disc-image filesystem or sector handling
- executable/container identification
- platform checksum/header rules
- common graphics encodings
- platform-specific address spaces
- common compression helpers only when genuinely platform-wide

A platform adapter must not pretend engine-specific formats are platform standards.

No platform is treated as the default implementation target.

### 3.3 Engine / family adapters

An engine adapter represents a reusable text/resource implementation shared by a related group of games.

Possible responsibilities:

- text encoding
- control codes
- pointer/reference formats
- script banks or resource archives
- compression codecs
- font format
- text renderer behavior
- runtime variables
- dialogue window constraints

One engine adapter may support multiple titles, revisions, and sometimes multiple releases on the same platform.

### 3.4 Game adapters

A game adapter binds exact supported game revisions to an engine/platform implementation.

It may define:

- accepted SHA-256 hashes
- title/region/revision metadata
- platform and engine selection
- ROM ranges, files, sectors, or resources
- resource tables
- game-specific exceptions
- build hooks

Game adapters should stay small. Reusable discoveries must move upward into the engine or platform layer.

## 4. Game-image identity and safety

Every input game image must be identified before modification.

Cartridge example:

```yaml
platform: gba
title: Example
region: USA
revision: Rev 1
container: rom
size: 16777216
sha256: ...
```

Disc example:

```yaml
platform: ps1
title: Example
region: USA
revision: 1.0
container: bin_cue
sha256: ...
```

Rules:

- SHA-256 is authoritative for supported input revisions.
- CRC32 may be recorded for convenience but is not sufficient as the primary identity check.
- Multi-file disc releases may require hashes for each required component.
- Unknown hashes fail closed.
- Similar filenames never imply compatible game images.
- A build manifest records the source hash(es), platform, adapter, and toolkit version.

## 5. Research-first workflow

Before implementing support for a new game:

1. identify the exact platform, release, region, revision, and hashes,
2. search for existing decompilation/disassembly/source projects,
3. search for technical documentation, ROM maps, filesystem maps, and executable notes,
4. search for existing translation/hacking tools,
5. identify storage/container structure,
6. identify known compression algorithms,
7. identify text encoding and control codes,
8. identify font/renderer architecture,
9. determine pointer/reference formats,
10. determine whether text is static or dynamically composed,
11. choose the least fragile implementation strategy.

Preferred implementation order:

```text
source-level rebuild
    ↓ if unavailable/inappropriate
documented engine tooling
    ↓
structured resource extraction/reinsertion
    ↓
binary extraction/reinsertion
    ↓
targeted reverse engineering
```

The method is selected per game/engine, not per project globally.

## 6. Translation data model

Human translation files are UTF-8 and independent from binary addresses whenever possible.

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

Stable logical IDs are preferred over raw offsets, sectors, or file positions.

Binary locations belong to adapter/build metadata, not translator-facing text.

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

A font compiler may transform source glyph assets into platform/engine-specific binary formats.

Different platforms may impose radically different constraints: tile-based fonts, sprite text, software-rendered bitmaps, texture pages, VRAM limits, palette limits, or executable-driven renderers.

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

## 11. References, pointers, relocation, and storage

Binary/resource adapters must model references explicitly.

Potential reference types include:

- absolute pointers,
- relative pointers,
- banked pointers,
- table indexes,
- file offsets,
- archive indexes,
- disc sectors / LBAs,
- 16/24/32/64-bit values,
- little/big-endian encodings,
- custom packed formats.

Text expansion must never overwrite neighboring data blindly.

Supported relocation strategies may include:

- known free-space regions,
- expanded ROM regions,
- rebuilt resource banks,
- rebuilt archives,
- relocated disc files with repaired references,
- source-level linker relocation.

Every relocation must be validated.

## 12. Compression and containers

Compression/container handling is plugin/adapter behavior.

Conceptual codec interface:

```text
decode(bytes) -> bytes
encode(bytes) -> bytes
verify(original_decoded, rebuilt_decoded)
```

A codec may be:

- platform-common,
- engine-specific,
- game-specific.

Container adapters may additionally expose operations such as:

```text
list_resources()
extract_resource(id)
replace_resource(id, bytes)
rebuild()
```

No algorithm or archive layout should be assigned to the platform layer merely because several games happen to use it.

## 13. Extraction and rebuild symmetry

Whenever practical:

```text
extract(original)
→ rebuild(unmodified extracted data)
→ binary/semantic verification
```

An adapter should prove that it can round-trip unchanged data before Arabic modifications are trusted.

Perfect byte identity may not be possible for every format or disc build, but semantic equivalence must be defined and tested.

## 14. Validation levels

### Level 1 — Input

- known platform
- known hash(es)
- expected size/container
- valid platform metadata

### Level 2 — Extraction

- tables/resources in bounds
- pointers/references resolve
- resources decode
- no duplicate/overlapping ownership unless documented

### Level 3 — Translation

- required tokens preserved
- glyphs available
- line constraints satisfied
- valid Arabic processing

### Level 4 — Rebuild

- writes/resources in bounds
- relocations valid
- references valid
- compressed resources decode
- container/filesystem remains valid
- no accidental overwrite

### Level 5 — Runtime

- game boots in a suitable emulator
- target scene is reachable
- text is visually verified
- surrounding UI/logic remains functional

## 15. Testing strategy

Tests should be split into:

```text
tests/unit/
tests/fixtures/
tests/platforms/
tests/engines/
tests/games/
tests/integration/
```

Commercial game images are not committed.

Small synthetic fixtures are preferred for unit tests.

Tests involving user-supplied game images run locally or in an explicitly configured environment.

Platform-specific runtime tests may use different emulators or headless tooling.

## 16. Build outputs

Generated output directories should be disposable and reproducible.

Possible outputs:

```text
build/
  manifest.json
  translated-game-image.*   # local only, ignored
  patch.*
  reports/
```

Distributed project artifacts should favor patches rather than copyrighted original game content.

The patch format may differ by platform and container type.

## 17. Error model

Errors must be explicit and actionable.

Examples:

```text
UNKNOWN_PLATFORM
UNKNOWN_GAME_REVISION
INVALID_REFERENCE
UNSUPPORTED_CONTROL_CODE
MISSING_GLYPH
TEXT_OVERFLOW
RELOCATION_OVERFLOW
CONTAINER_REBUILD_FAILED
COMPRESSION_ROUNDTRIP_FAILED
BUILD_VALIDATION_FAILED
```

Never silently continue when corruption is possible.

## 18. Logging

Diagnostics should distinguish:

- user-facing build status,
- warnings,
- adapter research/debug information,
- binary/resource trace details.

Normal builds should remain readable.

Verbose binary diagnostics should be opt-in.

## 19. First reference-game milestone

There is no mandatory first console.

The first reference game should be selected because it gives us a useful, well-understood end-to-end implementation—not because its platform is privileged.

The first reference milestone is complete when one verified game on any supported classic platform can pass the full pipeline:

```text
identify platform + revision
→ extract
→ represent translation
→ Arabic-process
→ rebuild
→ validate
→ boot/test
→ generate patch
```

After that, support for additional games and platforms is added incrementally.

Before adding each substantially different game/engine, reusable code from previous work must be reviewed and moved into the correct Core / Platform / Engine / Game layer.

## 20. Repository rules

- No commercial ROM/disc images.
- No unexplained magic offsets in core code.
- Every supported revision must have explicit identity metadata.
- Every adapter must document how its text/resource system works.
- Every binary/resource transformation should have tests where practical.
- Research notes that affect implementation belong in the repository.
- Generated files do not become source-of-truth inputs.
- Clean rebuilds must be possible from documented inputs.
- A platform is not considered supported merely because its directory exists.

## 21. Foundation acceptance criteria

The foundation phase is accepted when:

- multi-platform repository structure is agreed,
- game-image identity schema is defined,
- platform/engine/game adapter contracts are defined,
- translation schema is defined,
- Arabic pipeline behavior is defined,
- validation/error model is defined,
- first reference-game selection criteria are defined,
- basic CI/test structure is ready.

Only then should game-specific implementation begin.
