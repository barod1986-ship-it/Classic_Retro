# Mega Man Battle Network Arabic Renderer v1

Target: *Mega Man Battle Network* (USA). The disassembly
[Silenthal/bn1](https://github.com/Silenthal/bn1) (commit
`a3b4c2e0c0b6df3bd3c2c0100181c609a4649e08`) matches this exact image and was used
to find everything below; [TextPet](https://github.com/Prof9/TextPet)'s MMBN1 plugin
(commit `6c6d70561290b42d8261f6d76b03051d534c7032`) confirmed the script format and
the character table. The disassembly extracts its assets from the
original image, so this is a binary ROM overlay built from the user's image.

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `a4fbae389654a6611d0597b1e9109cbbd32a132f` |
| SHA-256 | `87bc7257f2f9ed0acc9f4874177e474e3d339d1e23a0b621d2d8edd73c1a09ed` |
| Game code | `AREE` (`MEGAMAN_BN`) |
| Output | 8 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Script archives.** Dialogue is stored in archives: a table of u16 offsets (one
  per section, relative to the archive; the first is twice the section count), then
  the sections. `Text_LoadDialogue(archive, n)` starts section `n`. Each scene has
  its own archive (`story_00` for waking up, `story_01` for the walk to school, read
  through literals at `0x08082AB0` and `0x08082DCC`); each map has a dialogue
  archive (`DialogueData_Offline`, `0x08014DB4` for Lan's room, `0x08014DB0` for the
  living room) and a commentary archive for the L Button (`CommentaryData_Offline`,
  `0x08015010` and `0x0801500C`). A scan of the image finds no other pointer to any
  of the six.
- **Scripts.** `Text_Main` reads a section byte by byte. Bytes below `0xE5` are
  characters, `E5 xx`/`E6 xx` two-byte ones (`E5 xx` is glyph `0xE5 + xx`: the USA
  font's punctuation). From `0xE7` on, commands: `E7` end, `E8` new line, `E9` clear
  the box, `EA` wait, `EB` wait for a key, `ED` mugshot, `EE` mouth animation, `F2`
  box control, `F3` flags, `F4` conditional jumps, `F5` input lock, `F6` jump,
  `F7` items, `FA` Lan's animation, `FB` item names, `FC` sounds... Their lengths
  come from the tables of the layout pass (`JT_LayoutCommand`); `engines/mmbn.py`
  decodes and re-encodes every section of the six archives byte for byte.
- **Two passes per frame.** The character pass copies glyph `code` of the dialogue
  font (`tilesetDialogueText`, `0x08613AA8`, 512 glyphs of 8x16 pixels in two 4bpp
  tiles, read by `Text_CopyCharTile` through the literal at `0x08013984`) into the
  next of 60 slots of the tile buffer (`0x020037E0`, `0xF00` bytes). The layout pass
  then walks the page again from its start, and `Text_LoadCharTileLayout` puts slot
  `n` in column `textCol + 8` of line `textRow` (tilemap rows 1-2, 3-4, 5-6), then
  increments `textCol`; `E8` sets it back to 0. Both passes keep the address of the
  byte they read in `r4`.
- **Pages.** `E9` (and every jump) empties the tile buffer and makes the layout pass
  start after it: a page is the text between two clears, at most 3 lines of 20
  cells.
- **Colours.** Glyph pixels are palette indices 1 (box, `(246, 246, 246)`), 2
  (anti-aliasing, `(205, 205, 205)`) and 3 (ink, `(49, 57, 57)`) of palette 15.
- **Key arrow.** Drawn at a fixed place (columns 28-29, rows 6-7), outside the text
  columns 8-27.
- **Free space.** The code ends at `0x08160AC4`; linker padding (`0xFF`) follows up
  to the IWRAM code copied from `0x08180000` (125 KB, within `BL` range of the text
  engine).

## Right-to-left pages

Arabic cannot be drawn one letter per monospace cell: its letters join and vary in
width. The overlay therefore draws every translated line ahead of time and cuts it
into 8-pixel cells from its right end:

1. `engines/mmbn_arabic.py` shapes each Arabic run with HarfBuzz
   (`font/shaped_text.py`) and draws it with the reference font; Latin words (PET,
   WWW, MegaMan.EXE, Recov10 A, START, L) are left-to-right islands drawn with the
   game's own glyphs, a cell each. Coverage becomes the game's colours: 3 from 150
   of 255, 2 from 60.
2. The line starts one pixel left of the box's right edge and grows leftwards; cell
   0 is its rightmost 8 pixels.
3. The cells of a page, duplicates merged, form the page's **bank**, laid out like
   the font (64 bytes per cell). The page's characters are cell numbers of that bank
   (0 to at most 59, below the two-byte leads).

Commands keep their byte form and their order (`E8` between lines). A mouth command
goes to the cell boundary where the text before it ends; after a wait (`{d N}`,
`{fd N}`) the next text starts in a cell of its own, so it only appears after the
wait (Lan's `. . .` are three cells, one per wait).

Two hooks give a translated page its bank and its direction; both look up the text
address in `r4`:

- `hook_copy` (instead of `Text_Main`'s call of `Text_CopyCharTile` for one-byte
  characters) adds the page's bank offset to the code: `Text_CopyCharTile` then
  copies cell `code` of the bank (`font + 64 * (code + offset)`).
- `hook_column` (instead of `Text_LoadCharTileLayout`'s `textCol + 8`) returns
  column `27 - textCol`: cell 0 of a line lands in column 27, the next one to its
  left.

`bank_offset` reads the **bank table** written after the hooks: `{end, count}`,
then `count` entries `{text address, bank offset}` sorted by address. Text before
the first entry or at or after `end` (every English script, item names in RAM) gets
`NO_BANK` (`0x80000000`) at once and keeps the font and the left-to-right layout;
anything else is found by a binary search. Pages of untranslated sections copied
into the rebuilt archives have `NO_BANK` entries too.

## ROM layout

| Address | Content |
|---------|---------|
| `0x08160B00` | Thumb hooks (`src/classic_retro/rom/mmbn_arabic_hooks.s`, 120 bytes) |
| `0x08160B78` | Bank table: 72 entries |
| `0x08160DC0` | Rebuilt archives: `story_00`, Lan's room (dialogue), living room (dialogue), Lan's room (commentary), living room (commentary), `story_01` |
| `0x08165128` | Glyph banks: 61 pages, 1302 cells (83 KB), each bank at `font + 64 * offset` |

Every archive with a translated section is rebuilt whole: its other sections (other
days of the story) are copied byte for byte, empty ones included, and its pointer is
repointed. The overlay checks the input hash, the six pointers, the section counts,
the pinned hash and command skeleton of every translated section, the code at both
hook sites and of `Text_CopyCharTile`, the font literal and that the padding is
still `0xFF`, before writing. After writing it reads every archive back and runs
every translated page like the game (table lookup, bank cell, mirrored column), and
checks that English text outside the rebuilt archives gets no bank.

## Hooks

| Site | Original | Hook |
|------|----------|------|
| `0x080136F2` | `00 F0 65 F8` (`Text_Main` → `Text_CopyCharTile`) | `hook_copy` |
| `0x08013806` | `AE 7B 70 1C A8 73 08 36` (`Text_LoadCharTileLayout`: `textCol + 8`, `textCol += 1`) | `BL hook_column`, two `NOP`s |

`classic-retro mmbn check-hooks` re-assembles the source with GNU binutils and
compares the result with the bytes stored in `mmbn_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 11 pixels on a baseline at row 11 of the 16-row cell: the reference font's forms
  then span rows 0 (hamza above alef) to 15 (the tail of final yeh), like the
  game's own letters use the whole cell.
- The font has no Latin punctuation: `.`, `!` and `:` are drawn from its alef
  (`font/shaped_text.py`); `،`, `؟` and `؛` are its own.
- Latin words keep the game's glyphs moved three rows up (their capitals end on row
  13, the Arabic letters on row 10); a word with digits, which start a row higher,
  moves up two rows.

## Translations

The script (`src/classic_retro/rom/mmbn_arabic_script.py`) covers Lan's first
morning, from a new game to the school gate: 50 sections, 61 pages.

- `story_00` (9 sections): MegaMan wakes Lan up, the net news, the mail from Dad.
- Lan's room: the PET and MegaMan.EXE, the good morning, the L Button, the reminder
  to check the mail, the PC, and what Lan reads on that morning's objects (13
  sections); MegaMan's advice on the L Button (1).
- The living room: Mom's good morning, breakfast and the chip under the plate, and
  that morning's objects (13 sections); MegaMan's advice on the L Button (1).
- `story_01` (13 sections): Mayl waits outside, the walk to school, the oven
  accidents.

For each section its archive, index, SHA-256 and command skeleton are pinned; the
Arabic keeps every command in order (only line ends may move). Item names printed
from the game's tables (`{key 0}` is the PET, `FB 00 43 01` the chip Recov10) are
written as text. The quotation marks of Dad's mail are not in the reference font:
the Arabic introduces it with a colon instead. Mom's second line gives her, under
her own mugshot, Lan's words about being late in the USA script; it is translated as
what she means: hurry, or you will be late.

## Verification

In mGBA, with the patch built from the reference font, from a fresh boot: New Game,
the whole of `story_00` (every page, Lan's timed dots, PET and WWW in the game's
glyphs), picking up the PET and every message after it, the room's objects (drawer,
bookshelf, PC), the L Button in both rooms, the stairs, Mom's conversation,
breakfast (the timed dots, Recov10 A), the front door, and the whole of `story_01`
with its timed lines while walking. After the school gate, MegaMan's English advice
at school draws left to right with the game's font as before, and so did the
reminder to take the PET while it was still in English (first overlay build).

## Limits

- Only Lan's first morning is in Arabic; school and everything after it, the menus,
  the PET screen, mail, battles and chip names are in English.
- Translated text is drawn ahead of time: it cannot hold names or numbers the game
  prints at run time (the translations write them as text), and a page holds at most
  60 cells (3 lines of 20).
- No vowel marks, one font size, and no Arabic-Indic digits (Western digits use the
  game's glyphs).
