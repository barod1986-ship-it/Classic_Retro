# Research Tools

Version: 1

The research tools answer the questions in [adding a target](ADDING_A_TARGET.md) §2
using your own copy of a game. There are three kinds:

- an emulator you run from a script: keys, frames, screenshots, savestates,
  memory, breakpoints and watchpoints;
- scanners for free space, pointers, pointer tables, text and byte patterns;
- a disassembler.

The tools only read the image; they never change it.

```text
classic-retro research run IMAGE SCRIPT          # an emulator session from a script
classic-retro research free-space IMAGE          # padding big enough for code, fonts, text
classic-retro research pointers IMAGE --to ADDR  # every pointer to an address or range
classic-retro research pointer-tables IMAGE      # runs of entries pointing into the image
classic-retro research text IMAGE [--table T]    # ASCII strings, or the game's own codes
classic-retro research relative-search IMAGE WORD
classic-retro research find IMAGE "70 47 ?? B5"  # byte patterns, ?? for any byte
classic-retro research disasm IMAGE ADDRESS      # ARM7TDMI, Thumb or ARM
```

**Keep what they find on your machine.** Screenshots, memory dumps, savestates and the
text a scanner finds all come from the game. Never commit or share them, just as with a
translator's workspace. A script is only inputs and addresses, so it can live in the
repository, for example next to a target's guide as the way to reach its scene.

## Running a game from a script

```text
classic-retro research run IMAGE SCRIPT [--out-dir DIR]
classic-retro research run IMAGE SCRIPT --core CORE [--option KEY=VALUE ...] [--system-dir DIR]
```

- A script has one command per line. `#` starts a comment, and a path with spaces goes in
  double quotes.
- Numbers are decimal or `0x` hex.
- Relative paths are taken from `--out-dir` (by default, the current directory).
- `SCRIPT` can be `-`, to read the script from standard input.

| Command | What it does |
|---------|--------------|
| `load FILE` | Load a savestate |
| `save FILE` | Save a savestate |
| `keys KEYS` | Hold `KEYS` from now on (`A`, `A+UP`); `keys none` lets go |
| `run FRAMES` | Run that many frames |
| `tap KEYS [HOLD [GAP]]` | Press `KEYS` for `HOLD` frames (2), then let go for `GAP` frames (8) |
| `touch X Y [HOLD [GAP]]` | Press the frame's pixel (`X`, `Y`) for `HOLD` frames (2), then let go for `GAP` frames (8): a touch screen, on a libretro core that reads a pointer |
| `shot FILE.png` | Save the last frame drawn |
| `peek ADDRESS LENGTH` | Report up to 4096 bytes of memory |
| `dump ADDRESS LENGTH FILE` | Write memory to a file |
| `poke ADDRESS HEX` | Write bytes, in memory order (`poke 0x02000000 01ff`) |
| `break ADDRESS [COUNT [MEMORY LENGTH]]` | Report the registers when `ADDRESS` executes (see below) |
| `watch MODE ADDRESS [COUNT]` | Report the registers when `ADDRESS` is accessed (see below) |
| `clear` | Remove every breakpoint and watchpoint |
| `reset` | Reset the console |
| `echo TEXT` | Put a marker in the report |

`break` details:

- It reports the first `COUNT` hits: 100 by default, or `all`.
- With `MEMORY LENGTH`, it also reports `LENGTH` bytes at `MEMORY`. `MEMORY` is either a
  register (`r0` to `r15`), meaning the address that register holds, or a fixed address.

`watch` details:

- `MODE` is `read`, `write`, `change` (a write that changes the value) or `access`
  (reads and writes).
- `COUNT` works as for `break`.

Key names are RetroPad buttons: `A B X Y L R L2 R2 L3 R3 SELECT START UP DOWN LEFT
RIGHT`. Each backend accepts the ones its console has. The whole script is checked
before the first frame runs, so a mistake on the last line costs nothing.

An example script finds the code that writes a variable:

```text
# From power-on to the title screen, then into the menu.
run 300
tap START
run 60
shot menu.png
save menu.state
# Which instruction writes the cursor? Report it the first three times.
watch write 0x03001234 3
tap DOWN
run 10
echo cursor moved
```

The report is JSON with these fields:

- the image and its SHA-256;
- the backend, core and platform;
- `frames` run;
- `files`: the files written, with the line of the command that wrote each;
- `events`: every echo, peek and hit, with the frames completed before it;
- `points`: every breakpoint and watchpoint, with its hit count.

A hit reports these fields:

- `address`;
- `pc`: the instruction that hit, when the backend knows it;
- `registers`;
- for a watchpoint: the access, and the old and new values;
- for a breakpoint with a memory probe: the bytes it read.

### Backends

| | `mgba` (default) | `libretro` (`--core`) |
|---|---|---|
| Consoles | Game Boy Advance, Game Boy, Game Boy Color | Whatever the core runs: SNES, Mega Drive, NES, PlayStation, Nintendo DS... |
| Breakpoints and watchpoints | Yes | No: libretro has no debugger |
| Touch (`touch`) | No | Yes, on a core that reads a pointer (DeSmuME) |
| Memory | Any bus address | Bus addresses through the core's memory map, or a named region (`save_ram:0x10`) |
| Needs | A C compiler and libmgba's development files | The core's shared library |
| Colour | 8 bits a channel | As the core draws it, often 16-bit |

**mgba.**

- The backend is a small C harness (`research/mgba_harness.c`) built against libmgba the
  first time it is needed, then cached.
- It needs a C compiler and libmgba's development files. On Debian and Ubuntu:
  `apt install build-essential libmgba-dev`.
- `CC` chooses the compiler. `CLASSIC_RETRO_MGBA_CFLAGS` and `CLASSIC_RETRO_MGBA_LIBS`
  set the build flags; the defaults come from pkg-config's `libmgba`, else `-lmgba`.
- `CLASSIC_RETRO_CACHE` moves the cache.
- `classic-retro research build-harness` builds the harness now and prints its path.
- `--harness` uses a harness binary you already have.
- A watchpoint reports the instruction that made the access (`pc`), found from the
  pipeline offset of `r15`.

**libretro.**

- Any libretro core that draws in software works.
- Cores come from your package manager (Debian and Ubuntu: `libretro-mgba`,
  `libretro-snes9x`, `libretro-genesisplusgx`, ...) or from the libretro buildbot, as
  `.so`, `.dll` or `.dylib` files.
- The core gets an empty system directory. Use `--system-dir` for BIOS files.
- Core options keep their defaults unless `--option` sets them.
- Key names are RetroPad buttons, and each core maps them to its console.
- Bus addresses work when the core publishes a memory map.
  - mGBA's core maps the whole GBA bus and names only its save RAM.
  - A core without a map is read through its regions: `save_ram`, `system_ram`,
    `video_ram` and `rtc`.
- A process runs one game per core at a time.
- The frontend gives a core a log callback, which drops what the core logs: current
  DeSmuME builds call it without checking that they were given one.
- For the Nintendo DS, `libretro-desmume` (DeSmuME) boots an image without BIOS files. A
  shot holds both screens, the top one above the bottom one (256x384).
  - `touch X Y` presses a pixel of that frame, so the touch screen is its lower half
    (`touch 128 272` is the point 128, 80 of the touch screen). The backend hands the
    pixel to the core as libretro's pointer; DeSmuME reads it as the touch screen with
    `--option desmume_pointer_mouse=enable --option desmume_pointer_type=touch`. Current
    builds spell the first value `enabled`; an option value the core does not know leaves
    the pointer off, and the touches do nothing.
  - The packaged core (0.9.11, Debian and Ubuntu) gives its memory regions no size, so
    `peek`, `dump` and `poke` fail.
    A core built from libretro/desmume's current source names the DS's main memory
    `system_ram` (`system_ram:0x33564` is `0x02033564`): `make -C
    desmume/src/frontend/libretro` builds it (with libpcap's and OpenGL's development
    files), and `--core` loads it. A `poke` over code right after a `load` then patches
    the game for that run, under the JIT or the interpreter: a `BL` turned into a jump
    to a few instructions that record what a call receives, or into a `NOP` that shows
    what the call draws (Phantom Hourglass).
  - `--option desmume_cpu_mode=interpreter` keeps the core off its JIT, which drew
    black frames in some environments.
  - DeSmuME's clock is the host's, so two runs of a script can drift apart by a few
    frames; wait generously before a shot.
  - DeSmuME writes its log to standard output too, ahead of the report: the report is the
    JSON object that ends the output.

A savestate belongs to the backend and core that wrote it.

## Scanning an image

Every scanner prints JSON. Addresses on the command line and in the report include the
image's **base**:

- A Game Boy Advance image is detected by its header, and its base is `0x08000000`.
- Any other image starts at 0 unless `--base` sets the base.
- A report gives each result's address and its offset in the file.

Every scanner also takes these options:

- `--start` and `--end`: limit the scan to part of the image.
- `--limit`: at most this many results (500 by default; 0 for all). `count` always gives
  the total, and `truncated` says whether the list was cut.

### Free space

```text
classic-retro research free-space IMAGE [--fill 0xFF] [--min-size 256] [--align 4]
```

- Finds runs of one padding byte: `0xFF` and `0x00` unless `--fill` is given.
- Each run starts on an `--align` boundary and is at least `--min-size` bytes long.
- The report gives each run's address, size, end and fill byte, the total free bytes per
  fill, and the largest run.
- Check a run before relying on it. Padding is usually free, but a run of zeros can be
  data, such as an empty table or a black tile. `ImageSpec.filled` in the patching kit
  proves a chosen range when the overlay is built.

### Pointers and pointer tables

```text
classic-retro research pointers IMAGE --to 0x08123456 [--to 0x08200000:0x08210000]
classic-retro research pointer-tables IMAGE [--min-count 8] [--stride 8] [--into START:END]
```

- `pointers` reports every aligned value that equals an address, or falls in a range
  (`START:END`, with `END` exclusive).
- Use it to find every reference to a string or table before moving it.
- `pointer-tables` reports runs of entries, each `--stride` bytes after the one before,
  that all point into the image or into `--into`. For each table it gives:
  - the count;
  - the lowest and highest target;
  - whether the targets ascend, as a table of strings stored in order does;
  - how many are odd, which on ARM means pointers to Thumb code.
- `--width` (2, 3 or 4 bytes) and `--byteorder` fit other consoles.
- `--align` defaults to the width.
- Pointers are read as linear addresses (base + offset). That fits the GBA and any flat
  mapping. Banked mappings, such as the SNES LoROM, are not modelled yet.

### Text

```text
classic-retro research text IMAGE [--min-length 8]
classic-retro research text IMAGE --table game.tbl [--min-length 8]
classic-retro research relative-search IMAGE WORD
```

- Without a table, `text` reports runs of printable ASCII, and whether a zero byte ends
  each one.
- With a table, it decodes the game's own codes:
  - It reads left to right, taking the longest entry at each byte.
  - A string ends at a byte the table does not know, or after an end code.
  - A string is reported when it has at least `--min-length` entries before its end code.
- `relative-search` finds a word you have seen on screen, in an encoding you do not know
  yet, when its letters are consecutive codes (A, B, C...).
  - The word needs three or more letters, all of one case.
  - Each match gives the code of the word's first letter and the code of `A` (or `a`)
    that follows from it: the start of a table.
  - Each match also shows a preview of the bytes around it, read with that alphabet.

A text table uses the common Thingy format, one entry per line:

| Line | Meaning |
|------|---------|
| `41=A` | One byte stands for one character |
| `8140=X` | Several bytes stand for one character; the longest match wins |
| `/FF=<end>` | An end code: the string stops after it |
| `*FE` | A line break, shown as a newline unless the line gives a text |
| `$E0=<wait>` | A control code, decoded like any entry |

- Hex digits come in pairs.
- Lines starting with `#` or `;` are comments. There are no comments after an entry.
- A value keeps its spaces: `20=` followed by one space maps `0x20` to a space.

### Byte patterns and code

```text
classic-retro research find IMAGE "00 B5 ?? 1C"
classic-retro research find IMAGE "some text" --ascii
classic-retro research disasm IMAGE 0x08012345 [--length 64] [--mode thumb|arm]
```

- `find` reports every offset where the pattern matches, overlapping matches included.
- `disasm` shows ARM7TDMI code through `arm-none-eabi-objdump`. This is the same binutils
  the hook checks use; on Debian and Ubuntu, install `binutils-arm-none-eabi`.
  - An odd address means Thumb code, as a Thumb function pointer is.
  - Otherwise, `--mode` chooses Thumb (the default) or ARM.

## From question to command

| Question in §2 of [adding a target](ADDING_A_TARGET.md) | Tools |
|---|---|
| Storage: where the strings live and what points to them | `text`, `relative-search`, `pointers`, `pointer-tables` |
| Encoding: characters and control codes | `relative-search`, then `text --table` with a growing table |
| Font: where the glyphs are and how they are drawn | `watch read` on the glyph data, `peek` and `dump` of VRAM |
| Renderer: the one place that draws a glyph | `watch write` on the tile buffer, `break` with a memory probe, `disasm` |
| Free space | `free-space` |
| Reaching the scene | a `research run` script with `shot`, and `save` for a savestate to start from |

## Limits

- The disassembler knows the ARM7TDMI only.
- The mgba harness reads 32-bit frames. libmgba is built that way by default; a build
  with `COLOR_16_BIT` is refused when the harness is compiled.
- The libretro backend drives software-rendered cores only (no OpenGL or Vulkan).
- Relative search covers one-byte codes whose letters are consecutive.
