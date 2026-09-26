# Classic Retro — Master Specification

Version: 0.4 (Sixteen reference targets on one pipeline)

## 1. Purpose

Classic Retro is a reusable toolkit for Arabic localization of classic video games across multiple systems.

It is **not centered on Game Boy Advance or any other single console**. Platform support is added through adapters while the Arabic localization core remains shared.

Target systems may include:

- Game Boy / Game Boy Color
- Game Boy Advance
- Nintendo DS
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
- use naive string reversal as the Arabic solution (a target that stores lines in
  visual order stores the bidi algorithm's order of shaped text, and refuses a line it
  would reorder differently),
- commit commercial ROM or disc images,
- silently modify unknown revisions,
- build a GUI before the underlying pipeline is stable.

## 3. Architecture

```text
src/classic_retro/
  core/           fingerprints, structured errors, JSON Schema validation
  media/          input files and disc sets: single files, CUE/BIN, ISO 9660
  adapters/       the platform, engine and game contracts, their registry, detection
  platforms/      one adapter per system: gb/gbc, gba, nds, nes, snes, megadrive, ps1, n64
  engines/        text engines, each with its Arabic module
  games/          exact supported revisions
  text/           the token model, engine commands, BMG message files
  arabic/         logical-text checks, shaping and bidi, glyph codes, paint order
  font/           Arabic forms drawn from the user's font, game font formats, previews
  cpu/            instruction encoders for hooks (Thumb, ARM, MIPS)
  rebuild/        BPS patches, the LZ77 and BLZ compressions
  patching/       the binary overlay kit, DS images and CD data tracks
  rom/            one binary overlay per rom-overlay target
  source/         source overlays (pokefirered, tmc)
  localization/   targets, rendering strategies, translation files, `targets` commands
  translations/   each target's Arabic
  schemas/        target-translations.schema.json
  research/       the scripted emulator, scanners, disassembler
tests/            synthetic data only
docs/
```

Every system in the tree is detected; the Game Boy Advance, the Nintendo DS and the
PlayStation also have Arabic targets. A platform is supported when a target ships on
it, not when its adapter exists.

There is one pipeline: the localization targets (§3.5). The foundation phase also
built a generic one: a JSON translation document of token streams, table-driven text
codecs, a layout engine over font profiles, resource transforms, and rebuild plans
with an allocator. No target used it: each engine needed its own encoding, measuring
and placement, and the pieces the targets do share are the core modules below. It was
removed once fifteen targets had shown this; §6, §7, §10, §12 and §13 describe what
the targets do instead.

### 3.1 Core

The core must contain only reusable behavior:

- game-image identity: fingerprints and revision verification (`core.identity`, `media`);
- the token model and engine commands (`text.tokens`, `text.commands`);
- target translation files (`localization.translations`, `target-translations.schema.json`);
- logical-text checks, Arabic shaping, bidi, glyph codes and paint order (`arabic`);
- glyphs drawn from the user's font, whole shaped lines, tiles and previews (`font`);
- patches and compression (`rebuild`);
- structured errors (`core.errors`).

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

### 3.5 Localization targets

A localization target (`classic_retro.localization.targets`) is one supported game
revision together with the way it is put into Arabic. It names its game adapter,
its platform, its kind, the rendering strategies it uses, its scope, its guide and
notes, and the operations the toolkit runs the same way for every target:

- `check_hooks()`: re-assemble the hook code and compare it with the stored bytes;
- `check_translations(font, preview_dir)`: validate the script without the game
  image; with a font, lay out every string and write the target's previews;
- `build(rom, font, out_dir, rom_name)`: build the patch from the user's image;
- `prepare(source, font)`: patch the user's decompilation checkout (a source overlay);
- `extract(input)`: read each entry's original from the user's own copy.

Kinds:

- `rom-overlay`: a patch built from the user's own image and shipped as BPS;
- `source-overlay`: a patched source tree of a decompilation that builds the image.

`classic-retro targets list | strategies | check-hooks | check-translations | build |
prepare | extract | strip` is the one way to run these for any target, by id, and CI
builds its target jobs from `targets list`. A target's own command group holds only its
engine's tools: `encode-arabic` (one line in the game's encoding) and, for a source
overlay, `source-check` (its anchors in a checkout, patching nothing). A rom-overlay target
records `reference_patch_sha256`, the hash of the patch built from its pinned image
with the reference font. A target that accepts several images (dumps that differ only
in bytes the game never reads) records one patch for each in `reference_patches`, by the
image's SHA-256. `targets build` reports whether a build matches the patch for its image.

Targets are registered in `classic_retro.localization.builtin`. External packages add
theirs through the `classic_retro.targets.v1` entry point group. The registry refuses
duplicate ids, unknown kinds and strategies that are not registered.
[ADDING_A_TARGET.md](ADDING_A_TARGET.md) is the playbook for a new target.

### 3.6 Rendering strategies

A rendering strategy (`classic_retro.localization.strategies`) is a way of drawing
Arabic through a game's renderer. It records what it needs from the engine, which
core modules it builds on, and what it costs. The sixteen targets proved four:

- `glyph-font`: a right-to-left glyph font in the game's own format;
- `line-cells`: lines shaped with HarfBuzz and cut into the engine's fixed cells;
- `text-images`: text the game shows as images, redrawn;
- `composed-lines`: a right-to-left glyph font that hooks compose into an image of
  each line at run time.

This is a starting set, not a closed list. A new strategy is registered in-tree or
through the `classic_retro.strategies.v1` entry point group. It starts as
`experimental` and becomes `proven` once a target ships with it. The
right-to-left techniques around the strategies (mirrored draw or reversed pen, the
direction markers, where glyph codes come from, runtime names) are catalogued in
[ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md).

The pieces the targets share are in the core:

- `arabic.logical`: the checks on logical text;
- `arabic.glyph_codes` and `arabic.paint`: glyph codes and paint order;
- `font.glyph_raster`: forms drawn to the cell with the joining advance;
- `font.tiles`: 4bpp tiles;
- `font.previews`: review images;
- `text.commands`: command tokens and the command check.

An engine keeps only its formats and limits.

### 3.7 Binary patching kit

Binary overlays share one recipe:

1. verify the exact image;
2. verify every byte replaced;
3. place hooks and data in proven free space;
4. repoint references;
5. read everything back;
6. ship a BPS patch.

The parts that do not depend on the game live in:

- `classic_retro.patching`:
  - `image.ImageSpec`: identity, address/offset conversion, reference scans, free-space checks
  - `hooks.HookProgram`: hook code stored as bytes, re-assembled from source in CI
    with an assembler registered per CPU
  - `outputs`: the common report fields and patch/image files
- `classic_retro.cpu`: one module per instruction set, holding the calls, branches
  and far jumps written over game code. `cpu.thumb` covers the ARM7TDMI's Thumb
  code, `cpu.arm` the ARM946E-S's ARM code and `cpu.mips` the PlayStation's MIPS I.

A game's overlay module keeps only what is its own: addresses, hook source,
script, and the strategy-specific drawing.

### 3.8 The package as built

| Layer | Packages |
|-------|----------|
| Core | `core`, `adapters`, `media`, `text`, `arabic`, `font`, `rebuild`, `schemas` |
| Platform | `platforms`, `cpu` |
| Engine | `engines` |
| Game | `games` |
| Localization | `localization` (targets, strategies, the `targets` commands), `rom` (binary overlays), `source` (source overlays) |
| Shared overlay machinery | `patching` (and `patching.nitro` for DS images: header, NitroFS, NARC, the ARM9's autoload blocks and overlay table; `patching.cdrom` for CD data tracks: raw sectors with their EDC and ECC, ISO 9660 records) |
| Research | `research` (the scripted emulator, its backends, the scanners) |

Adapter discovery (`classic_retro.{platforms,engines,games}.v1`), target discovery
(`classic_retro.targets.v1`), strategy discovery (`classic_retro.strategies.v1`) and
assembler registration are all open. A new platform, engine, game, target, strategy
or CPU is added without editing the others.

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

The revisions live in the game adapters (`games/`, `GameRevision`: SHA-256 and size),
which `classic-retro detect` matches. A rom overlay's `ImageSpec` names the image it
patches, and a test holds every such image to a revision of its target's game.

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

The `research` commands do this work on the user's own image
([RESEARCH_TOOLS.md](RESEARCH_TOOLS.md)):

- a scripted emulator session with screenshots, savestates, memory access,
  breakpoints and watchpoints;
- scanners for free space, pointers, pointer tables, text (ASCII, `.tbl` tables,
  relative search) and byte patterns;
- a disassembler.

What these tools find comes from the game and stays local. Scripts hold only inputs.

## 6. Translation data model

Human translation files are UTF-8 and independent from binary addresses whenever possible.

An entry:

```json
{
  "id": "thomas_owner",
  "context": "Thomas; event script 867, string 0",
  "text": "مهلا! صاحب هذه المزرعة\nتوفي منذ مدة.{wait}{clear}لا يمكنك أن تدخل إلى هنا\nهكذا وكأن المكان مكانك!{wait}"
}
```

Stable logical IDs are preferred over raw offsets, sectors, or file positions.

Binary locations belong to adapter/build metadata, not translator-facing text.

### 6.1 Target translation files

Each localization target keeps its Arabic in `classic_retro/translations/<target>.json`
(`target-translations.schema.json`):

- `entries`: one per translated text, each with a stable `id`, the Arabic `text` in the
  target's notation, and optional `context` and `notes` for people;
- `notation`: what the commands inside the texts mean for this engine;
- `glossary`: how the names and terms of the original are written in Arabic.

A committed file holds no text of the game. Where each original is and what it must
match (addresses, SHA-256 pins, command skeletons) stays in the target's code, and every
check and build holds the file against those pins: a missing or unknown entry, or a
translation that drops or reorders the original's commands, is refused.

`classic-retro targets extract` writes a *workspace*: the same file with each original
(`source`) decoded from the user's own copy and verified against its pin, so the
translator sees what every entry translates. A workspace stays on the user's machine
(`*.workspace.json` is ignored by git), and `targets strip` writes it back without the
originals. `--translations` gives a file or a workspace to `check-translations`, `build`
and `prepare`. With a workspace, `check-translations` also lists the entries whose
original names a glossary term that their Arabic does not use.
[TRANSLATING_AR.md](TRANSLATING_AR.md) is the translator's guide.

These files are the toolkit's one translation format. The text of an entry is in its
engine's own notation, which is what a translator reads; the engine parses it into the
token model (§7).

## 7. Control codes and placeholders

Control codes and dynamic placeholders must never be flattened into ordinary translated text.

In a translation file they are written in the engine's notation:

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

Inside the toolkit a message is a token stream (`text.tokens`): runs of text and
inline tokens between them. An inline token is a `variable` (a name, a number), a
`control` (a wait, a colour, a sound), a `line_break` or `page_break`, or an `opaque`
command not yet named, which keeps its bytes. Each has an id unique in its message and
a movement policy: `free` tokens (a runtime name) may move within the translation,
`ordered` ones (waits, page breaks, sounds) keep their order among themselves.

Engines carry each command's codes in its token (`text.commands`) and hold a
translation's commands against the original's (`require_same_commands`): a command
dropped, added, changed or reordered is refused. An engine may let a translation add a
page break, and marks it as inserted. The Arabic pipeline shapes and orders the text
around the tokens without altering them ([ARABIC_PIPELINE.md](ARABIC_PIPELINE.md)).

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

Each localization target declares the registered rendering strategies it uses (§3.6).
The four proven ones shape at build time. Runtime shaping remains a candidate for
text assembled at run time ([ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md)).

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

Each engine knows its box: its width, its lines, how a page ends. A translation's line
and page breaks are part of its text, and a target measures every line with the real
advances of the glyphs it will draw, against that box. Widths come from shaped glyphs,
and each line is shaped and put in visual order on its own, so joining at a line's
ends is that of the line (UAX #9: shaping, then widths, then reordering per line).

Validation should detect:

- line overflow,
- text-box overflow,
- impossible words,
- unsupported glyphs,
- malformed tokens.

`targets check-translations` runs these checks for a target without its image. No
target wraps automatically yet; when one does, its wrapping must be deterministic.

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

A codec may be:

- platform-common,
- engine-specific,
- game-specific.

Each codec is a module of plain functions: the GBA/DS BIOS LZ77 (`rebuild.lz77`) and
the DS backward LZ of ARM9 binaries (`rebuild.blz`) are shared, and an engine's own
(Golden Sun's Huffman text) stays in its engine. A compressed
binary is packed again so that its unchanged parts keep their original compressed
bytes (`rebuild.blz.repack_blz`), and the patch carries only what changed.

Each container has its own module, which reads it and rebuilds it where a target
needs to: `patching.nitro` (the DS header, NitroFS, NARC archives, the ARM9 and its
autoload blocks), `text.bmg` (BMG messages), `font.nftr` (NFTR fonts), `media`
(CUE/BIN and ISO 9660, read only) and `patching.cdrom` (a CD data track's raw
sectors, written back whole with their EDC and ECC, and ISO 9660 records repointed).

No algorithm or archive layout should be assigned to the platform layer merely because several games happen to use it.

## 13. Extraction and rebuild symmetry

Whenever practical:

```text
extract(original)
→ rebuild(unmodified extracted data)
→ binary/semantic verification
```

An adapter should prove that it can round-trip unchanged data before Arabic modifications are trusted.

The targets do: `text.bmg` rebuilds an unchanged message file byte for byte, the Gen
III text codec re-encodes what it decodes (`verify_round_trip`), a packed ARM9 is
packed again so that its unchanged parts keep their bytes, and every rom overlay reads
its output back before it writes the patch (§3.7).

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

Tests live in `tests/`, a module per concern: the shared layers (`test_arabic_core.py`,
`test_localization.py`, `test_translations.py`...) and, for each target, its engine
(`test_<game>_engine.py`), its Arabic module (`test_<game>_arabic.py`) and its overlay
(`test_<game>_rom_overlay.py`, `test_<game>_source_overlay.py`).

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

Every rom-overlay build writes the patch and `build-report.json` (base, target and
patch hashes and sizes). The patched image is written only when asked, for local
use.

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
- A change to shared code keeps every target's results byte-identical: its reference
  patch hash, its previews and its translation report. A target's results change only
  with its own translation or renderer, and its reference hash is updated in the same
  commit.

## 21. Foundation acceptance criteria

The foundation phase is accepted when:

- multi-platform repository structure is agreed,
- game-image identity model is defined,
- platform/engine/game adapter contracts are defined,
- translation schema is defined,
- Arabic pipeline behavior is defined,
- validation/error model is defined,
- first reference-game selection criteria are defined,
- basic CI/test structure is ready.

Only then should game-specific implementation begin.
