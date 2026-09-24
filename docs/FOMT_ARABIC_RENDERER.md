# Harvest Moon: Friends of Mineral Town Arabic Renderer v1

Target: *Harvest Moon: Friends of Mineral Town* (USA). No decompilation builds this
image; the facts below come from its own code, read with GNU binutils and checked in
mGBA, with the notes of [StanHash/FOMT-DOC](https://github.com/StanHash/FOMT-DOC)
(written for the image of *More Friends of Mineral Town*, whose addresses differ) as a
guide. This is a binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `a2fc3574f0a65a4fcf7682fb274b9d7eebdef963` |
| SHA-256 | `ca6cebe7211b6f2693af210709f76222204bf9f7621dec08b30ca268117460dd` |
| Game code | `A4NE` (`HARVESTMOGBA`) |
| Output | 8 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Event scripts.** `0x080F89D4` holds 1329 pointers to RIFF files of form `SCR `:
  a `CODE` chunk (a word, then the bytecode), sometimes `JUMP`, and `STR ` (a count,
  an offset per string from the end of the offset table, then NUL-terminated strings).
  The size field counts the whole file, header included; the loader (`0x0803EEEC`)
  reads chunk headers while its offset is within that size and does not pad chunks, so
  it reads one header past the end. The code names strings by index. Script 867 is the
  first of a new game: Thomas on the farm.
- **Story scenes.** The opening's flashback (`0x0805F770` onwards) sets the speaker's
  name tag (`0x08050E68`) and starts the text box (`0x08050DA0`) with strings reached
  through the literal pools of its code (`0x080FB234`..`0x080FB818`).
- **Text codes.** Strings are ASCII: `05` waits for a key, `0C` clears the box, `0D`
  returns to the line start, `0A` goes down a line (the game writes `0D 0A`; a line feed
  on the third line scrolls the box up). The interpreter (`0x080ADD78`) hands every
  byte above `1F` to the box's draw-character method; when that draws nothing, the byte
  is a lead: it asks the box's character expander, then pairs it with the next byte.
- **Expanders.** The event scripts' expander (vtable `0x080E76E8`, method `+12` at
  `0x0803B4DC`) turns `FF 21`..`FF 2D` into the player's name, the farm's, the dog's...;
  the story scenes' expander (vtable `0x080E79E8`, `0x080E19A4`) turns a lone `FF` into
  the player's name. The naming screen takes up to 12 characters, all single bytes.
- **Glyph routine.** `0x080D0D28` draws one character into a buffer of four tiles
  (top left, top right, bottom left, bottom right) and returns its width in tiles:
  single bytes through the table at `0x084FA7A0` (1bpp glyphs of 8x12, unpacked with a
  shadow one pixel right and one down-right, ink colour 1, shadow colour 2), Shift-JIS
  pairs with a lead `81`..`9F` or `E0`..`EA` as 16-pixel glyphs; any other lead byte
  draws nothing and returns 0. It is the only caller of the unpacking routines: the text
  box, the name tags and the menus all come through it.
- **Text box.** The draw-character method (`0x0804EFAC`, display manager vtable
  `0x080E78C0`) keeps x (+20, in 8-pixel columns), the line (+22) and the top line
  (+24). Each of the box's three lines is seven 32x16 sprites (28 columns); x wraps at
  28. It draws the character at column x of the current line and advances x by its width.
- **Name tag.** `0x08050B50` shows a name of 1 to 12 bytes, four bytes per 32-pixel
  sprite, drawn from the tag's left edge.
- **Free space.** The image ends with 0xFF padding from `0x0875C244` to `0x08800000`.

## Right-to-left text

1. `engines/fomt_arabic.py` draws every translated line whole with HarfBuzz and the
   reference font, gives its ink the game's shadow, and cuts it into 8x16 cells from
   its right end. The cells of all translations form one bank; cell `n` is the code
   `F0 + n / 189`, `40 + n % 189` (`F0 40`..`FA FC`, 2079 codes). The game draws
   neither lead on its own, so it pairs it with the trail like a Shift-JIS lead.
2. `hook_glyph` gives the glyph routine a cell for such a code (its top and bottom
   tiles), a 16x16 name tag cell for `FC xx`, and for `FB xx` the game's own glyph
   `xx`; everything else runs the routine as before.
3. `hook_mirror` replaces the draw-character code that picks the sprite and column of
   x: for `F0`..`FB` codes the column is `27 - x`. x still advances left to right, so
   wrapping, line ends and scrolling are unchanged, a line fills from the right edge of
   the box and the typewriter reveals it from the right.
4. `{name}` is `FD 21` in a translation. The expanders' method slots point to
   `hook_expand_script` and `hook_expand_story`: for `FD xx` they ask the original
   expander for `FF xx` (a lone `FF` in the story scenes), then write its text reversed,
   each character as `FB xx`. Drawn mirrored, the player's name reads left to right
   inside the right-to-left line; the layout keeps 12 cells for it.
5. A speaker name is drawn in 16x16 cells (`FC 40`..`FC FC`), two codes per sprite,
   right-aligned in the tag's six cells.

English text never uses these codes: its characters, the expansions of `FF xx` and
the name tags go through the original code.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08760000` | Thumb hooks (`src/classic_retro/rom/fomt_arabic_hooks.s`, 276 bytes) |
| `0x08760400` | Bank header: cells, count, tag cells, count |
| `0x08760410` | 816 cells of 64 bytes, then 10 name tag cells of 128 bytes |
| after them | The 23 story strings and 5 speaker names, then script 867 rebuilt (and 8 zero bytes) |
| `0x080F9760` | Script 867's table entry, now the rebuilt script |
| flashback literals | The 23 strings' and 5 names' 45 literals, now the Arabic texts |

The overlay checks the input hash, the code at both hook sites, both expander slots,
that the padding is still 0xFF, script 867 (its table entry and the SHA-256 of the
whole file), and for every translated string and name its SHA-256, its command skeleton
and, for the story texts, that the pinned literals are the only words of the image that
point to it. After writing it reads everything back: the hook code, the bank header,
every code of every text against the bank, the literals, the rebuilt script (the same
code and chunks, the expected strings, the zero tail) and that nothing else changed.

## Hooks

| Site | Original | Patch |
|------|----------|-------|
| `0x080D0D28` | `push {r4-r6, lr}` and the three moves after it (8 bytes) | `ldr r2, [pc]; bx r2; .word hook_glyph`; the hook runs the four instructions for other characters |
| `0x0804EFD0` | 16 bytes computing the sprite (r7) and column (r2) of x | `bl` to a veneer, `b 0x0804EFE0`, `nop`, then the veneer: `ldr r0, =hook_mirror; bx r0` |
| `0x080E76F4` | `0x0803B4DD` (script expander) | `hook_expand_script` |
| `0x080E79F4` | `0x080E19A5` (story expander) | `hook_expand_story` |

The hook area is out of `BL` range from the sites, hence the jumps and the veneer.
`classic-retro fomt check-hooks` re-assembles the source with GNU binutils and
compares the result with the bytes stored in `fomt_arabic.py` (run in CI).

## Cells and font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`, shaped with
  HarfBuzz (lam-alef and the other ligatures, contextual forms, kerning).
- Size 10 on a baseline at row 11 of the 16-row cell: the forms span rows 1 to 14 and
  their shadow row 15. Coverage from 128 of 255 is ink.
- The shadow is the game's: colour 2 one pixel right and one down-right of the ink,
  computed on the whole line so it crosses cell edges.
- Hamza on a carrier (`أ إ ؤ ئ`) is two or three pixels at this size and reads as part
  of the letter; the renderer draws the base letter (`ا و ى`) and a drawn hamza of two
  rows over it (under it for `إ`), one blank row away, at the place the font gives its
  own hamza (the two glyphs compared at 100 pixels).
- A line keeps one free pixel at its right; text before the player's name ends three
  pixels before it.

## Translations

The script (`src/classic_retro/rom/fomt_arabic_script.py`) covers the opening, from
the naming screens to the first morning on the farm: 33 strings and 5 speaker names.

- Script 867, strings 0-4: Thomas stops the newcomer, hears that they knew the late
  owner, tells of the will and asks how they met.
- The flashback (23 strings): the family's trip, the lost child found by the old
  farmer, the invitation to his farm, the girl who wakes the child, the farewell and
  the promise to write. The tags read `الأم`, `الأب`, `العجوز`, `؟؟؟` and `الفتاة`.
- Script 867, strings 5-9: the letters, the farm handed over, and the next day.

For each string its place (script index, or address and literals), its SHA-256 and
its command skeleton (`{wait}`, `{clear}`, `{name}` in order) are pinned; the Arabic
keeps every command in order, and line ends may move (a line feed that scrolls the box
must follow a `{wait}` that shows the line it hides). The English texts are not in the
repository.

## Verification

In mGBA, with the patch built from the reference font, from the naming screens with a
12-letter name: all 33 strings and the five tags in the order the game shows them,
each revealed from the right; the player's name read left to right in its five lines;
the old farmer's box scrolling twice; `وفي اليوم التالي...` and the first morning. The
same input from the same state on the first morning (the bookshelf menu and one of its
books, in English) gives pixel-identical frames with the original image (10 frames).

## Limits

- Only the opening is in Arabic; object names, menus and the rest of the game are in
  English.
- Thomas's name tag stays `Thomas`: it comes from the table of the townspeople's names,
  which every dialogue with him shares.
- The player's name keeps the game's Latin glyphs. Arabic text holds no Latin letters,
  and no vowel marks.
- The box's arrow stays in its corner.
