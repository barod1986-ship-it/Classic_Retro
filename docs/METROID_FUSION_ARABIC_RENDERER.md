# Metroid Fusion Arabic Renderer v1

Target: *Metroid Fusion* (USA). The [metroidret/mf](https://github.com/metroidret/mf)
decompilation matches this image and names the code below, but it cannot be shifted
and takes its data from the original, so this is a binary ROM overlay built from the
user's image, like the targets without a decompilation. The facts below come from
the decompilation's sources and the image's own code, checked with the
[research tools](RESEARCH_TOOLS.md) (`disasm`, `free-space`, and mGBA runs with
breakpoints).

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `ca33f4348c2c05dd330d37b97e2c5a69531dfe87` |
| SHA-256 | `a56ce3d7f8f3f4f4d0468d421fff5dd3ee3aec99a58244377e43aae769dc3fe8` |
| Game code | `AMTE` (`METROID4USA`), header revision 0 |
| Output | 8 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Text.** A string of 16-bit units ended by `FF00`: `FE00` ends a line, `FD00`
  clears the text for a new page, `FC00` shows the next-page arrow and waits for A,
  and `E1xx` waits `xx` frames. Any other unit is a glyph. The English text uses the
  Latin codes `0x40..0x5F`, `0x80..0x9F` and `0xC0..0xDF` (ASCII shifted by 0x20,
  0x40 and 0x60).
- **Font.** `GetCharacterWidth` (`0x08079118`) gives code `c` the width at
  `0x08576234 + c` up to `0x49F`, and 10 above. `DrawCharacter` (`0x0807913C`) reads
  glyph `c` from a sheet of 4bpp tiles, 32 a row: the tile at `0x08682FAC + 32 * c`
  above the one at `+ 0x400`, and for a glyph wider than 8 pixels the next code's two
  tiles on its right, up to 16 pixels. It ORs the glyph into a row of tiles at a pixel
  offset, spilling into the tiles on its right. Pixel 2 is the ink and 3 the outline
  around it, on all eight sides.
- **Monologues.** Samus's narration in cutscenes: 19 texts in each language, listed by
  language at `0x0879C5A4`. The game reads the list of the language byte at
  `0x03000011`, which is 2 (English) in this image: the list at `0x0879E6EC`.
- **The new-file intro** (`NewFileIntroHandler`) tells the story through twelve of
  them, read by index as its scenes go on: 8 to 17, then 18 and 0. Its current text
  is the first word of `gNonGameplayRam` (`0x03001484`), and three routines draw it,
  one character each call:
  - `IntroProcessText` (`0x080984AC`): two lines at the bottom of the screen, in the
    strip of tiles at `0x0600D000`, one character every three frames. A line is a row
    of 32 tiles (`0x400` bytes, two rows for its 16 pixels), the second line two rows
    down. `FE00` after the second line waits two seconds and starts a new page.
  - `NewFileIntroProcessAdamText` (`0x080986F0`): the same for the ship's computer in
    its box, with a sound for every character but the space (`0x40`).
  - `SpecialCutsceneProcessMonologue` (`0x08097F80`): a page of nine lines of 28 tiles
    at `0x06000000`. Every tile the pen reaches is marked in a table, and
    `0x08098158` fades the marked tiles in one by one, in the pen's order, through the
    palette of their tilemap entries (at `0x06004842 + 2 * column + 128 * line`).
- **Arrows and cursor.** `NewFileIntroProcessTextCursor` puts the next-page arrow (an
  8x8 sprite centred on its x) at the bottom right (x = 235) at `FC00`;
  `NewFileIntroProcessAdamTextCursor` puts the ship computer's typing cursor 14 pixels
  past the pen (the arrow there, and the monologue page's, are centred).
- **Screen.** The strip's first pixel and the page's first column are at x = 8 of the
  240-pixel screen; the English lines are at most 224 pixels wide.
- **Free space.** The image ends with 398136 bytes of `0xFF` from `0x0879ECC8`, 7 MiB
  from the intro's code: out of a `BL`'s 4 MiB reach. `Dma3Transfer_Unused1`
  (`0x08098940`, 64 bytes, next to the intro's text routines) is called by nothing.

## Right-to-left text

The routines keep their pen and lay a line out from the left. For a text of the
Arabic bank the overlay mirrors where each glyph lands on a line of 224 pixels
(**mirrored draw**):

```text
left' = 224 - pen - width
```

A line then starts at the right edge (x = 232) and grows leftwards, and the
typewriter reveals it from the right.

1. `hook_draw`, called instead of `DrawCharacter` at the three drawing calls, turns
   the tile and pixel offset it is given into the mirrored ones and calls
   `DrawCharacter` with the caller's registers and stack (its fifth argument is on the
   stack). The glyphs are not flipped.
2. `hook_fade`: the page's fade walks the tiles in the pen's order, and for Arabic
   updates the tilemap entry of the mirrored column (`27 - column`). The tiles a glyph
   covers are exactly the mirrors of the ones the pen marked.
3. `hook_arrow` puts the strip's next-page arrow at the other end of the bottom line
   (x = 4); `hook_cursor` puts the typing cursor left of the text, at the mirror of its
   place (x = 226 - pen).
4. `hook_width` replaces `GetCharacterWidth`: the game's widths below `0x4A0`, the
   right-to-left glyphs' from `0x9000`, 10 otherwise as before.
5. Any other text keeps the game's own path: every hook but the width first checks
   whether the current text lies in the Arabic bank.

The right-to-left glyphs have codes from `0x9000`: `DrawCharacter` reads glyph `c` at
`0x08682FAC + 32 * c`, which for these codes falls in the padding, where the overlay
writes their sheet. Every glyph takes two tile columns (one code every two in a row
of 32, rows of 32 codes alternating with the rows of their lower halves), so it may be
16 pixels wide: no form is split. The space is the game's own (`0x40`, 6 pixels), so
the ship's computer stays silent between words.

## Reaching the hooks

The hooks lie beyond a `BL`'s reach, so every site calls a veneer written over
`Dma3Transfer_Unused1`, and each veneer jumps to its hook through a register its sites
do not need:

| Veneer | Hook | Through |
|--------|------|---------|
| `0x08098940` | `hook_draw` | `ip` (`bx pc; nop; ldr ip, [pc]; bx ip`): at a call, the callee may use it |
| `0x08098950` | `hook_fade` | `r3`: the fade keeps its loop's end in `ip`, and reloads `r3` after the site |
| `0x08098958` | `hook_arrow` | `r1` |
| `0x08098960` | `hook_cursor` | `r1` |

A first build that sent the fade through `ip` hung the page after a few glyphs: its
loop never reached its end. A veneer must leave alone every register its site still
uses.

## ROM layout

| Address | Content |
|---------|---------|
| `0x0879F000` | Thumb hooks (`src/classic_retro/rom/metroid_fusion_arabic_hooks.s`, 212 bytes) |
| `0x0879F800` | The right-to-left widths: a byte for each code from `0x9000` (2 KiB) |
| `0x087A2FAC` | The right-to-left glyph sheet: glyph `0x9000` onwards, 136 glyphs in 9 rows of `0x800` bytes |
| `0x087B4000` | The Arabic bank: the 12 translated monologues (3948 bytes), up to `0x087B8000` |
| `0x08098940` | The four veneers (40 bytes) |
| `0x08079118` | `GetCharacterWidth`: a jump to `hook_width` |
| The English list | The 12 pointers, now to the Arabic monologues |

A stored monologue ends with `FF00`, then zeros up to a word. The overlay checks the
input hash, the code at every site and the entry of `GetCharacterWidth`, the SHA-256
of `Dma3Transfer_Unused1`, the bytes the hooks rely on (the width table and the glyph
sheet's address, the game's space, the intro's data, the strip's tiles, the page's
last column and fading map, the typing cursor's pen, the English list), that the
padding is still `0xFF`, and for every translated monologue its place in the list,
its SHA-256 and its control units. After writing it reads back every site, veneer,
table and monologue.

## Hooks

| Site | Original | Hook |
|------|----------|------|
| `0x08079118` | `push {lr}; lsls r0, r0, #16; lsrs r1, r0, #16; ldr r0, =0x49F` (the entry of `GetCharacterWidth`) | `hook_width` (`ldr r1, =hook; bx r1`) |
| `0x08098690`, `0x080988D4`, `0x080980CC` | `bl DrawCharacter` (the strip, the ship's computer, the page) | `hook_draw` |
| `0x080981F8` | `lsls r2, r6, #1; lsls r0, r7, #7` (the fade's tilemap entry) | `hook_fade` |
| `0x08098C1E` | `movs r0, #235; strh r0, [r2, #12]` (the arrow's x) | `hook_arrow` |
| `0x08090740` | `adds r0, #14; movs r1, #0` (the cursor's x) | `hook_cursor` |

`classic-retro metroid-fusion check-hooks` re-assembles the source with GNU binutils
and compares the result with the bytes stored in `metroid_fusion_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 136 glyphs, codes `0x9000..0x920E`: `.`, `!` and `:` drawn by hand (the font has no
  Latin punctuation), then the 133 forms of the shared repertoire, with the Arabic
  comma, question mark and digits.
- The game's style: ink (2) inside a one-pixel outline (3) on all eight sides. A form
  has no outline column on a side where it joins its neighbour, and its ink reaches
  that edge, so joined letters meet and their outlines go on across the join.
  `DrawCharacter` ORs its pixels, so an outline over a neighbour's ink would turn it
  into outline: glyphs never overlap.
- Size 11, the largest whose forms fit 16 rows with their outline (ink on rows 1..14)
  on the baseline of row 11, once hamza above alef is drawn by hand above a shortened
  alef and final and isolated yeh are raised a row. A glyph is at most 16 pixels wide.
- Coverage from 140 of 255 is ink; the outline is drawn around it.

## Translations

The script (`src/classic_retro/translations/metroid-fusion.json`; its originals are
pinned in `src/classic_retro/rom/metroid_fusion_arabic_script.py`) covers the whole
new-file intro: 12 monologues.

- Eleven go through the two-line strip: Samus's mission on SR388 and the X that
  attacked her, her ship drifting into an asteroid belt, her rescue, the surgery on her
  suit, the Metroid vaccine and her rebirth, and the ship's computer announcing the
  B.S.L station (in its box).
- The last one fills four pages of the nine-line monologue: the explosion on the
  station, her new mission and her new commanding officer.

For each monologue its index in the list, its address, its SHA-256 and its control
units are pinned; the Arabic keeps every control unit in order (line ends after text
may move; a strip page holds two lines and a monologue page nine). Names are
transliterated (إس آر ٣٨٨ with Arabic-Indic digits, بي إس إل, بيولوجيك, إكس,
ميترويد) and terms translated (الاتحاد المجري, بدلة القوة, حاسوب السفينة); Samus
narrates as a woman.

## Verification

In mGBA, with the patch built from the reference font, from a new game: every page of
the twelve monologues, each line typed from the right with the next-page arrow at the
bottom left, the ship computer's box with its cursor left of the text, and the four
pages of the monologue fading in from the right. With the same input from power-on
and from a savestate on the landing, the title screen, the file select screen, the
landing and the first briefing on the map (English text with coloured words, drawn
through the width hook) are pixel-identical to the original image's, 67 screens.

## Limits

- Only the new-file intro is in Arabic. The briefings on the map (the navigation
  conversations, another renderer with colours and two panels), the game's messages
  and menus, and the in-game cutscenes are in English.
- Words drawn in the intro's pictures (the vaccine's name, the labels) stay as they are.
- Arabic monologues cannot hold Latin letters (the right-to-left font has digits and
  punctuation only) or colours.
- No vowel marks, one font size, and no lam-alef ligature (lam and alef are separate
  forms).
