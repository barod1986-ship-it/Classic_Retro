# Adding a Localization Target

Version: 1

A **localization target** is one supported game revision together with the way it
is put into Arabic. Ten targets are registered today:

```text
classic-retro targets list
```

This guide collects what those ten taught, in the order the work happens. It is a
checklist, not a template: every game gets its own research, and a game that fits
none of the existing methods gets a new one (see
[ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md)).

## 1. Identity

- Pin the exact revision: SHA-256 and size (see [MASTER_SPEC.md](MASTER_SPEC.md) §4).
  Similar file names prove nothing.
- Add a game adapter under `games/` with its `GameRevision`, and an engine adapter
  under `engines/` when the text engine is new
  ([ADAPTER_ARCHITECTURE.md](ADAPTER_ARCHITECTURE.md)).
- Never commit the image, the game's text or its graphics. The repository holds
  hashes, addresses and the tools that rebuild from the user's own image.

## 2. Research before code

Answer each question and write the answers into the target's renderer notes
(`docs/<GAME>_ARABIC_RENDERER.md`) before relying on them. The
[research tools](RESEARCH_TOOLS.md) answer them on your own copy of the game. They
include an emulator you run from a script, with screenshots, savestates, breakpoints
and watchpoints, and scanners for free space, pointers and text.

1. **Sources.** Is there a decompilation or disassembly? Does it build the image?
   Does it take its data from the original?
   - It builds with editable data: a `source-overlay` patches the source tree
     (FireRed, Minish Cap).
   - Otherwise: a `rom-overlay` patches the user's image and ships a BPS patch.
     The sources still give addresses and names.
2. **Storage.** Where the strings live and how they are compressed (Huffman, LZ77,
   script archives), and every reference that points to them.
3. **Encoding.** The byte form of characters and commands (one byte, lead bytes,
   UTF-8-like forms), the control codes, and how names and numbers are expanded
   at run time.
4. **Font.** Pixel format, cell size, proportional or monospace, the widths table,
   free codes or free font slots.
5. **Renderer.** The one place that decides where a glyph is drawn, and how lines
   are measured, wrapped and centred. Also the typewriter, scrolling, choices,
   cursors and key arrows.
6. **Free space.** Padding in the image (`0xFF` or `0x00` runs) for hooks, fonts
   and text, and whether the image may grow (`research free-space`).
7. **Reaching the scene.** The inputs that take a new game to the translated text in
   an emulator, so every build can be checked on screen. A `research run` script
   records them: it holds only inputs, so it can be kept with the target's guide.

## 3. Choose the strategy

| The engine has... | Start from |
|-------------------|------------|
| Proportional glyphs, spare codes or a free font slot, one draw point | `glyph-font` |
| Fixed-width cells too small for letter-by-letter Arabic, codes to spare | `line-cells` |
| Text shown as images | `text-images` |
| Something else | a new strategy, registered as `experimental` |

Then choose how the renderer turns right to left, how right-to-left text is marked,
where glyph codes come from, and how runtime names behave. The tables in
[ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md) list what each target did. Prefer
**mirrored draw**: it keeps the game's measuring, wrapping and typewriter.

Write the engine's Arabic module (`engines/<engine>_arabic.py`) on
[the shared core](ARABIC_STRATEGIES.md#the-shared-core). It already has:

- the checks on logical text;
- glyph codes and paint order;
- drawing forms at the largest size that fits, with the joining advance;
- 4bpp tiles, shadows and review images;
- command tokens and the check that a translation keeps its commands.

Only the game's formats and limits belong in the module.

## 4. Build a rom overlay with the kit

The steps are the same for every binary target. Only the addresses, the hook source
and the script belong to the game.

- `patching.image.ImageSpec`: the pinned title, SHA-256, size and base address.
  - `verify`: refuses any other image.
  - `offset`, `word`, `read`: address arithmetic.
  - `filled`: proves a free range is really padding.
  - `references`: finds every word that points to a table you move.
- `cpu.thumb`: the patches written over game code to reach a hook.
  - `bl_instruction` and `branch_instruction`.
  - `literal_jump`: `ldr`/`bx` with its literal on the next word boundary.
  - `bl_veneer_patch`: replaces a block with a call and a resume.
  - `arm_veneer`: reaches Thumb code from ARM code.

  Another CPU gets a module of its own under `cpu/`.
- `patching.hooks.HookProgram`: the hook source (`rom/<game>_arabic_hooks.s`), its
  assembled bytes and symbol offsets stored in Python.
  - A build therefore needs no toolchain.
  - `check()` re-assembles the source and proves the stored bytes match.
  - The assembler is chosen per CPU: GNU binutils for the ARM7TDMI.
    `patching.hooks.register_assembler` adds another CPU.
- Verify the original bytes of every site before writing it, and read back
  everything written.
- `rebuild.bps.create_bps` builds the patch. `patching.outputs` supplies the common
  report fields and writes the patch file, plus the patched image only when asked
  (local use).
- The script module (`rom/<game>_arabic_script.py`) pins each original by address,
  the SHA-256 of its bytes and its command skeleton, and names each entry with a
  stable id. The Arabic goes into `translations/<target>.json` (MASTER_SPEC §6.1),
  never into code, and the English goes nowhere: translations are checked without
  the image.
- `extract_originals(rom, translations)` verifies the image and every original and
  returns each entry's original in the engine's notation, for a translator's
  workspace.

## 5. Register the target

In this repository, write `localization/builtin/<target>.py` and add its `TARGET` to
`builtin_targets()`:

```python
TARGET = LocalizationTarget(
    id="my-game",  # the id the targets commands take
    game_id="my-game-usa",  # the game adapter's id
    title="My Game (USA)",
    platform_id="gba",
    kind="rom-overlay",  # or "source-overlay"
    strategies=("glyph-font",),  # registered strategy ids, one or more
    scope="What is translated",
    guide="docs/MY_GAME_ARABIC_TEST_AR.md",
    notes="docs/MY_GAME_ARABIC_RENDERER.md",
    register_cli=register_cli,  # the target's own command group
    check_hooks=check_hooks,
    check_translations=check_translations,
    build=build,
    extract=extract,  # each entry's original, for a translator's workspace
    previews=PREVIEWS,  # files check_translations writes, given a font
    reference_patch_sha256="...",  # the patch built from the pinned image
)
```

A target from another package uses the `classic_retro.targets.v1` entry point group,
where the object or a zero-argument callable returns a `LocalizationTarget`. Its
strategies must be registered first, either built in or through
`classic_retro.strategies.v1`. It ships its translations itself and passes them with
`--translations`.

A source overlay has `prepare(source, font, translations)` instead of `build`: it
patches the user's pristine checkout of the decompilation, which then builds the image.

Every target then runs the same way:

```text
classic-retro targets check-hooks my-game
classic-retro targets check-translations my-game --font reference-font.ttf --preview-dir previews
classic-retro targets build my-game "path/to/game.gba" --font reference-font.ttf --out-dir build
classic-retro targets extract my-game "path/to/game.gba"
```

`targets build` reports `matches_reference`, which is true when the patch equals the
recorded `reference_patch_sha256`.

## 6. Tests, CI and documents

- Unit tests use synthetic data only: invented strings, generated images and fonts
  drawn in the test. No game bytes.
- `tests/test_translations.py` holds every shipped translations file against its
  target's pinned entries; add the new target there.
- CI finds the target by itself. The `localization-targets` job reads
  `classic-retro targets list`. Every target with a `check-translations` operation
  gets an `<id>-arabic-overlay` job, which does three things:
  - re-assembles the hooks (if the target has any)
  - lays out the script with the reference font, and fails when a declared preview
    is missing
  - uploads the previews for review
- Documents:
  - `docs/<GAME>_ARABIC_TEST_AR.md`: the Arabic guide for applying the patch and
    reaching the scene
  - `docs/<GAME>_ARABIC_RENDERER.md`: the research notes and limits
  - a paragraph in the README

## 7. Keep results byte-identical

Shared code serves every target, so a change to it must not change any target's
output. Before merging such a change:

- build every target whose image you have with `targets build` and check
  `matches_reference`;
- compare the CI previews and `translation-report.json` with the previous run.

A target's own results change only when that target's translation or renderer is
changed on purpose. Its `reference_patch_sha256` is updated in the same commit.
