# Adding a Localization Target

Version: 1

A **localization target** is one supported game revision together with the way it
is put into Arabic. Sixteen targets are registered today:

```text
classic-retro targets list
```

This guide collects what those sixteen taught, in the order the work happens. It is a
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
   cursors and key arrows. A renderer that draws each line at once and centres it
   may need no change at all (see visual order in the next section).
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
| Fixed cells copied into an image of each line, one draw call, RAM for a line | `composed-lines` |
| Something else | a new strategy, registered as `experimental` |

Then choose how the renderer turns right to left, how right-to-left text is marked,
where glyph codes come from, and how runtime names behave. The tables in
[ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md) list what each target did. Prefer
**mirrored draw**: it keeps the game's measuring, wrapping and typewriter. When the
game draws every line at once and centres it (New Super Mario Bros.'s menus), store
the lines in **visual order** instead: nothing in the game changes.

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
  - `arm_veneer`: reaches Thumb code from ARM code, or any hook through `ip`.

  A hook more than 4 MiB from its site (the padding of an 8 MiB image) is reached
  through a veneer near the site, in code nothing calls: the site keeps a 4-byte
  `BL`. Each veneer jumps through a register its sites no longer need: `ip` at a
  call (the callee may use it), otherwise a register the code reloads after the
  site. Metroid Fusion's fade keeps a loop's end in `ip`; a veneer through `ip`
  hung it.

  Choose the right-to-left glyph codes against every routine that will draw them,
  not only the first one: Metroid Fusion's briefings read the intro's glyph codes
  (`0x9xxx`) as sounds, and its glyphs had to move to `0xB040`.

  Without a decompilation's names, unused code for veneers is found with the
  research tools: no `bl` reaches the function in the disassembly, no word of the
  image points to it (`research pointers`, odd and even), and a breakpoint on it never
  fires through the scenes you test (Tactics Ogre's `sub_0801C498`).

  Read how the game's routine writes a glyph before mirroring it. One that ORs a
  glyph into its tiles (Metroid Fusion) can draw at the mirrored place; one that
  composes a scratch column and writes whole columns (Tactics Ogre) would erase the
  mirrored glyphs, so the hook draws every glyph of right-to-left text itself.

  When the game finds a message by a small offset from a block (Tactics Ogre's
  16-bit offsets), copy the block: the translated messages go to the bank, the others
  stay in English next to the copied table, outside the bank.

  Most of a DS game's code is ARM, not Thumb: `cpu.arm` writes and reads the ARM `BL` of a
  site (`bl_instruction`, `bl_target`) and lists the branches of a piece of code
  (`branch_targets`), so a build can check that a stored hook calls exactly the routines it
  names (Phantom Hourglass).

  The PlayStation's R3000A runs MIPS I: `cpu.mips` writes the `jal` that reaches a hook
  anywhere in the same 256 MiB segment, the constants and shifts an overlay rewrites in
  place (`li`, `addiu`, `slti`, `sll`) and a `lui`/`addiu` address pair, and lists the
  jumps of a piece of code (`jump_targets`). The instruction after a jump runs before
  the jump: hooks are written with `.set noreorder`, so each delay slot holds what the
  source says (Symphony of the Night).

  Another CPU gets a module of its own under `cpu/`.
- `patching.hooks.HookProgram`: the hook source (`rom/<game>_arabic_hooks.s`), its
  assembled bytes and symbol offsets stored in Python.
  - A build therefore needs no toolchain.
  - `check()` re-assembles the source and proves the stored bytes match.
  - The assembler is chosen per CPU: GNU binutils for the ARM7TDMI (the GBA), the
    ARM946E-S (the DS's ARM9, `cpu="arm946e-s"`) and the R3000A (the PlayStation,
    `cpu="r3000"`, `mipsel-linux-gnu-*`; GNU as rounds its `.text` up to 16 bytes).
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

An image with a file system (a Nintendo DS cartridge) changes files, not addresses:

- `patching.nitro`: `NitroImage` reads the header and finds a file by its path;
  `replace_files` writes files back, in place when they fit, past the used area when
  they grew. `Narc` does the same inside a NARC archive. The header CRC is computed
  again, and `secure_area_crc` updates the secure area's CRC from the bytes that
  changed, without the cartridge's encryption.
- A compressed binary is packed again like the original: `rebuild.blz.repack_blz`
  keeps the ARM9's compressed items wherever the code did not change, so the patch
  carries the change (a font, a table) and not the game's code. Pin the binary packed
  and unpacked, and read it back decompressed in place, as its start-up code does.
- `font.nftr.NftrFont` and `text.bmg.Bmg` read and write the SDK's fonts and message
  files; an unchanged file is rebuilt byte for byte.
- Hooks for the ARM9 can live in its instruction TCM, which nothing the game loads
  overwrites: `Arm9Binary` (an uncompressed binary) reads the module parameters and
  autoload blocks, and `with_block_grown` adds code at the end of the ITCM block with
  the later blocks and the table moved. The binary then grows: `move_arm9_overlay_table`
  puts the overlay table past the used area and `replace_arm9` writes the binary into
  the room, up to the next part of the image. Check that no overlay loads where the
  hooks go (Pokémon Platinum).
- When the ITCM is full and the ARM9 cannot grow (its BSS runs up to the first overlay), a
  hook takes the place of a routine nothing calls. A decompilation's relocations suggest
  candidates, but check the unpacked ARM9 and every overlay yourself for a branch to the
  routine and a word pointing to it: zeldaret/ph's relocations miss the table that reaches
  SHA-1's block function, which a Download Play boot runs. Phantom Hourglass's hook went
  over a routine of the C++ runtime, and needs no memory: it reads only the arguments of
  the call it takes over.
- `Narc.rebuilt` rebuilds a NARC file with members replaced, each in place when it
  fits up to the next one; the others keep their offsets.
- Some screens wait for the touch screen: `research run` touches the frame's pixels
  (`touch X Y`) on a core that reads a pointer (DeSmuME).

A disc image (a PlayStation CD) changes sectors, and a game may find its files by
sector rather than by name:

- `patching.cdrom.RawTrack` holds a data track of raw 2352-byte sectors: it reads the
  data of Mode 2 Form 1 sectors, checks their EDC and ECC, and writes sectors whole
  (sync, header, subheader, data, EDC and ECC; a Mode 2 sector's codes leave its header
  out). `iso_file` finds a file's ISO 9660 directory record and `set_file_extent`
  points it at other sectors.
- A file that grows past its sectors moves. The empty sectors after the last file's
  extent, at the end of the data track, may hold it when they are a header and zeros, no
  record claims them and the volume spans them (`empty`, `claimed`, `volume_space`). The
  original stays where it was.
- Repoint every reference to the file, and search the whole track for others: Symphony
  of the Night loads a stage by the sector and length in DRA.BIN's table of stages,
  which its overlay rewrites; a stale copy of the table in the title's program is read
  by nothing.
- Pin the track (SHA-256), each file read (SHA-256, and every sector's codes) and the
  references. The CUE sheet and the other tracks do not change, so the patch is of the
  data track.
- `create_bps(..., copy_from=...)` indexes only the source ranges moved data comes
  from: an index of a whole disc would not fit in memory, and the patch copies the
  moved file from the user's own disc (about 10 KB for Symphony of the Night).
- Data added after a program's end must lie in memory the game leaves to that program:
  Symphony of the Night loads every stage at the same address, and larger stages
  cover the room its prologue's stage grows into.

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
    register_cli=register_cli,  # the engine's own tools, such as encode-arabic
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

These are the only commands for what every target does: a target's own command group
(`register_cli`) holds just the tools of its engine, such as `encode-arabic` (one line in
the game's encoding) or `source-check` (a source overlay's anchors, without patching).

`targets build` reports `matches_reference`, which is true when the patch equals the
recorded `reference_patch_sha256`. A target that accepts more than one image (dumps that
differ only in bytes the game never reads) records the patch from each in
`reference_patches`, by the image's SHA-256, and `targets build` compares with the one for
the image it was given (Pokémon Platinum).

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
