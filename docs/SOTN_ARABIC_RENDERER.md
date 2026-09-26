# Castlevania: Symphony of the Night Arabic Renderer v1

Target: *Castlevania: Symphony of the Night* (USA, SLUS-00067), the first PlayStation
target. The [Xeeynamo/sotn-decomp](https://github.com/Xeeynamo/sotn-decomp) decompilation
(commit `5279c8403cfe6f8829d2b43be4523f0e6a33964e`) gave the names and addresses below;
it builds the game's files from the user's own disc, so this is a binary overlay that
patches the user's disc image and ships as a BPS patch of its data track. The facts were
checked on the disc and in Beetle PSX with the [research tools](RESEARCH_TOOLS.md).

| Item | Value |
|------|-------|
| Redump | *Castlevania - Symphony of the Night (USA)*: a CUE sheet, a data track and an audio track |
| Track 1 (data) | 538655040 bytes (229020 sectors of 2352 bytes, Mode 2): CRC32 `05BE47B2`, SHA-1 `f967119e006695a59a6442237f9fc7c7811cf7bf`, SHA-256 `ce01203a9df93e001b88ef4c350889c19f11ffba89d20f214bdd8dec0b2d8d7c` |
| Track 2 (audio) | 44676240 bytes: SHA-256 `bfd0a11552d17fbf4d798ef9d03981949760f26cfaebd3ff167025deaebd8246` |
| Boot | `SYSTEM.CNF` boots `SLUS_000.67`; `classic-retro detect` on the CUE names the game |
| Output | Track 1, the same size; the CUE sheet and Track 2 stay as they are. Shipped as BPS |

## Engine facts the overlay relies on

- **Files.** `DRA.BIN` (LBA 299) is the game's main program, loaded at `0x800A0000`. A
  stage is a program of its own: `ST/ST0/ST0.BIN` (LBA 37113, 271812 bytes) is the
  prologue of 1792, loaded at `0x80180000`. Its code, data and BSS all lie inside the
  file, which ends at `0x801C25C4` (sotn-decomp's `splat.us.stst0.yaml`). Other stages'
  programs are larger (`NO3.BIN` reaches `0x801D7E18`), so the memory after ST0 belongs
  to the stage area.
- **Loading a stage.** The game finds a stage by sector, not by name: DRA.BIN's table of
  stages (sotn-decomp's `g_StagesLba`) gives each stage's graphics sector, program sector
  and program length; ST0's entry is at offset `0x4194` of the file (`0x9044`, `0x90F9`,
  `0x425C4`). The loader (`CopyStageOvlCallback`) copies the program to `0x80180000` a
  sector at a time, as many as its length gives, with no bound of its own. `ST/SEL/SEL.BIN`
  (the title and file menus) holds a stale copy of the table, where ST0 is `0x4267C` bytes
  long; no code of SEL reads it (all of SEL is decompiled but one video routine), and a new
  game loads the prologue through DRA's table. Besides these two tables, only the ISO 9660
  directory record of `ST0.BIN` holds its sector (every Form 1 sector of the track was
  searched).
- **The dialogue.** ST0's `EntityCutscene` reads the cutscene's script
  (`cutscene_script`, `0x801829D8` to `0x80182C4A`) a byte at a time: bytes `00` to `14`
  are commands with their arguments ([`engines/sotn.py`](../src/classic_retro/engines/sotn.py)
  lists them), every other byte a glyph. The prologue has six messages, Richter's and
  Dracula's in turn, each after the command that waits for its voice (`0A`), timed with
  waits, speeds and flags that start the animations.
- **Glyphs.** The font is 8x8 cells of 4 bits in VRAM: code `c` is the cell at
  (`896 + 2 * (c % 16)`, `240 + 8 * (c // 16)`), in halfwords. The routine copies the cell
  with `MoveImage` (`0x80012BEC`; the call at `0x801A9C58`) to the pen: `nextCharX` of
  `g_Dialogue` (`0x801C24CC`), and row `384 + 12 * nextCharY`, then moves the pen by one
  cell; a space (`20`) only moves the pen. A line end takes the pen back to `nextLineX`
  and down a line. Codes from `80` would be copied from VRAM below the font; the English
  script uses none.
- **Lines.** Each line is an image in VRAM, 192 pixels wide, shown by a sprite of its own
  over the box: five images of 12 rows (rows 384 to 443), four lines in the box, the fifth
  scrolling in (`CutsceneUnk3` clears a line's image, `CutsceneUnk4` points a line's
  sprite at it, `ScaleCutsceneAvatar` scrolls). The English lines start at column 8 of
  their image; the longest (19 letters) ends at column 160. For the PSP version
  sotn-decomp's `cutscene.h` gives lines 16 rows apart, three to the box.
- **Names.** At a portrait command `DrawCutsceneActorName` (`0x801A8CB0`, called at
  `0x801A9718`) draws the speaker's name with a sprite a letter from the table of names
  (`actor_names`, `0x80180828`: Richter's and Dracula's, their codes ASCII minus `0x20`,
  ended by `FF 00`). The sprites are primitives of `g_Dialogue`'s second group
  (`primIndex[1]`), hidden until the text starts; with no primitive left the routine
  destroys the entity.
- **The box's right end.** The boss's health bar shows at the right edge of the screen
  while Dracula's last message is typed, over the box's last columns (from about column
  172 of the line images); the English lines never reach them.

## Right-to-left text

A code from `80` is a glyph of the Arabic font, and a hook draws it; the game's glyphs
keep the game's path. The game's typewriter, waits, flags and scrolling run unchanged,
and so does its pen, which moves one cell a glyph: the hook keeps a pen of its own.

- **A line image in RAM.** `hook_glyph` takes the call of `MoveImage`. A code below `80`
  goes on to `MoveImage` as before. For an Arabic glyph it draws the glyph into an image
  of the line in RAM (192 pixels, 16 rows, 4 bits), then sends the whole image to the
  line's place in VRAM with `LoadImage`, so the typewriter reveals the line glyph by glyph.
- **A reversed pen.** The hook's pen starts a line at its right edge, column 160, and
  moves left by each glyph's width before drawing it: a line fills from the right, and a
  translated message holds its glyphs in right-to-left paint order. A line starts when the
  game's pen is at `nextLineX`: the hook clears its image and takes its pen back to the
  right edge. Only a glyph's ink is written, so the glyph painted before it keeps its
  joining stroke. The Arabic lines hold 152 pixels, the English lines' own room, and end
  where the longest English line ends, clear of the boss's health bar.
- **Names.** `hook_name` takes the call of `DrawCutsceneActorName`. It allocates one
  sprite from the same group as the game's routine, draws the speaker's Arabic name into a
  second line image from the right edge, sends it to VRAM row 448 and shows it with the
  sprite, whose right edge is the lines' right edge; the sprite is hidden until the text
  starts, and with no primitive left the entity is destroyed, as the game's routine does.
- **Lines 16 rows apart.** The Arabic glyphs are 16 rows tall, so the lines are 16 rows
  apart (they were 12): four images (rows 384 to 447), three lines in the box, the fourth
  scrolling in, as in the PSP version; the scroll moves 16 rows, two a frame. English text
  in ST0 would take the same spacing. The name's image goes to rows 448 to 463: rows 444
  to 463 of these columns are blank in the original's VRAM at the stage's start and after
  the battle begins.

## Glyph codes

Codes `80` to `FF` are the Arabic font's glyphs, in the font's order: the space, `.`, `!`,
`:`, then the forms by code point. Only the characters the script uses get codes; every
form is one glyph of up to 16 pixels. The prologue uses 72 codes (`80..C7`). A code the
script does not use has no width and a blank glyph.

## Hooks

The hooks (`rom/sotn_arabic_hooks.s`, R3000A MIPS I, 816 bytes with the assembler's
padding) are linked at `0x801C2600`, after ST0's end, in the part the overlay adds to the
file. They call `MoveImage`, `LoadImage` and the entity's destroy routine
(`0x801B4908`) and allocate through `g_api.AllocPrimitives`; the build checks that the
stored code jumps to exactly those three routines (`cpu.mips.jump_targets`).

| Site | Original | Arabic |
|------|----------|--------|
| `0x801A9C58` in `EntityCutscene` | `jal MoveImage` | `hook_glyph` |
| `0x801A9718` in `EntityCutscene` | `jal DrawCutsceneActorName` | `hook_name` |
| `0x801A9384` | the script's address (`lui`/`addiu`) | the Arabic script |
| `0x801A9C44` | the glyph's row, `nextCharY * 12` | `nextCharY * 16` |
| `0x801A94E4` | the line end's spacing, 12 | 16 |
| `0x801A9504`, `0x801A9538` | five line images, four in the box | four, three |
| `0x801A8BA8`, `0x801A8BC4` in `CutsceneUnk3` | a line's row and its 12 rows | 16 |
| `0x801A8C74`, `0x801A8C88` in `CutsceneUnk4` | the sprite's height and row, 12 | 16 |
| `0x801A911C` to `0x801A91E8` in `ScaleCutsceneAvatar` | five lines in turn | four |
| `0x801A9C94` | the scroll's length, 6 frames of 2 rows | 8 |

Anchors checked before any change: every original of the table; the code before the
glyph call that reads the code and the pen (`0x801A9468`, `0x801A9C1C`); the name routine's
allocation, its group and its destroy call (`0x801A8D18`, `0x801A8D6C`, `0x801A8D40`); the
line end's return of the pen to `nextLineX` (`0x801A94C8`); the dialogue's palette,
`0x01A1` for both speakers (`0x80180794`); ST0's last word (zero); the script (SHA-256);
the table of names; every translated original (SHA-256 and commands); ST0.BIN and DRA.BIN
(SHA-256, and every sector's EDC and ECC) and DRA's stage entry.

## Image layout

ST0.BIN grows to 294916 bytes (the part after its end: hooks, widths, name slots, the
Arabic script, glyphs, line images and the pen), more than its own sectors hold. The new
file goes to the empty sectors at the end of the data track, and the original stays where
it was:

| Part | Where |
|------|-------|
| `0x801C2600` | the hooks |
| `0x801C2A00` | a width a code, `80` to `FF` |
| `0x801C2A80` | eight name slots of 16 bytes: a glyph count, then the codes in paint order |
| `0x801C2B00` | the Arabic script: the original with each translated message replaced (558 bytes) |
| `0x801C3400` | the glyphs, 128 bytes each (16 rows of 16 pixels, 4 bits) |
| `0x801C7400`, `0x801C7A00` | the line image and the name's image, 1536 bytes each |
| `0x801C8000` | the hook's pen |

| On the disc | Original | Arabic image |
|-------------|----------|--------------|
| `ST0.BIN` | LBA 37113, 133 sectors | LBA 228870, 145 sectors |
| The free sectors | 149 empty sectors (LBA 228870 to 229018) after the extent of `SD/XA_STR1`, the track's last file; the track's last sector holds parity bytes and stays | 4 left |
| DRA.BIN's stage entry | `0x90F9`, `0x425C4` | `228870`, `0x48004` |
| ST0.BIN's directory record | LBA 37113, 271812 bytes | LBA 228870, 294916 bytes |

`patching.cdrom` writes every sector whole: sync, header, subheader, data, EDC and ECC.
The free sectors are checked to be empty (a header and zeros), claimed by no file and
inside the ISO 9660 volume. The build reads everything back: only these sectors changed,
each is a sound Form 1 sector, the file reads back through its record, and DRA's entry and
the script's address point at the new file.

## Font

The reference font is Noto Kufi Arabic SemiBold, drawn at 11 pixels (the largest size,
from 16 down, at which every form of the repertoire fits a 16x16 glyph with the baseline
on row 12 and the top row left empty, which keeps the lines apart). Final and isolated yeh
are raised a row. Coverage from 140 of 255 is colour 6 of the dialogue's palette, the grey
of the English letters, and from 60 colour 2, a darker grey that smooths the strokes; no
smoothing lies right of a glyph's width. The space is 4 pixels; `.`, `!` and `:` are drawn
by hand; the Arabic comma, semicolon and question mark come from the font. Lam and alef
stay two glyphs.

## Translations

`rom/sotn_arabic_script.py` pins the six messages, each by its place in the script, the
SHA-256 of its bytes and its commands, and the two names by the table's pointers and the
SHA-256 of their bytes. The Arabic is in `translations/sotn.json`, in the engine's
notation (`{speed N}`, `{wait N}`, `{flag N}`, `{wait-flag N}`, a new line for a line end).
A translation keeps every command in order; line ends are its own. A line holds at most
152 pixels; the prologue's widest is 120. The names are 27 and 37 pixels.

## Verification

With the reference font the build matches the reference patch (10247 bytes). In Beetle
PSX (`mednafen_psx_libretro`, Ubuntu's `libretro-beetle-psx`, a US BIOS in the system
directory), from power-on with the patched track: both names over the portraits; every
line of the six messages typed from the right, the waits and the animations as in English,
the fourth line scrolling the box; the last message clear of the boss's health bar; then
the battle. The same script on the original disc shows the English at the same frames.

A script for `classic-retro research run` that reaches the dialogue from power-on with no
memory card, inputs only:

```text
# Core: mednafen_psx_libretro, --system-dir holding a US BIOS (scph5501.bin).
run 1200
tap START
run 420
# File select, a new game (no memory card), the name screen.
tap START
run 120
tap START
run 120
tap START
run 120
tap START
run 120
tap START
run 180
# Three letters, START: the opening film, then 1792.
tap B
run 120
tap B
run 120
tap B
run 120
tap START
run 5160
# Richter climbs the stairs to Dracula's throne room.
keys LEFT+UP
run 1080
shot dialogue.png
```

The dialogue then takes about 40 seconds. Beetle PSX (0.9.44.1) gives the PlayStation's
main RAM as `system_ram` (`system_ram:0x1C24CC` is `g_Dialogue`, `0x801C24CC`) and no
`video_ram`: VRAM is read from a savestate, whose `GPURAM[0][0]` chunk holds its 1 MiB.

## Limits

- Only the prologue's dialogue is in Arabic: the opening film's captions, the text that
  scrolls after the battle, the menus and the rest of the game stay English.
- ST0.BIN moves to the empty sectors at the end of the data track, so the patched track
  must be kept whole: the CUE sheet with its BIN files, or a CHD made from them.
- Arabic lines hold no Latin letters or digits: the hook draws every glyph of a line from
  the right.
- 128 glyph codes for the whole script (the prologue uses 72).
- No vowel marks, no ligatures, one size.
- Commands other than the typewriter's waits, speeds and flags are refused in Arabic text.
