# Super Mario 64 Research Notes

**Research only.** There is no Super Mario 64 target, engine or game adapter: the Nintendo 64
is detected and nothing more. Nothing below has been run in an emulator. Every fact comes from
the user's image, read with the toolkit's N64 modules (`rebuild.mio0`, `patching.n64`, the
`research mio0` and `research pointer-tables` commands) and scratch scripts, and from the
game's code, read by disassembling it. The notes exist so that the session that builds the
target starts from verified facts rather than from assumptions (the [README](../README.md)'s
rule, "document discoveries before turning them into assumptions", and the research-before-code
step of [adding a target](ADDING_A_TARGET.md)). Numbers are decimal unless prefixed `0x`; ROM
offsets are offsets into the big-endian image; a RAM address of the main code segment is its
ROM offset plus `0x80245000`.

| Item | Value |
|------|-------|
| Image | *Super Mario 64 (USA)*: one cartridge image in big-endian order (`.z64`) |
| ROM | 8388608 bytes (8 MiB): SHA-1 `9bef1128717f958171a4afac3ed78ee2bb4e86ce`, SHA-256 `17ce077343c6133f8c9f2d6d6d9a4ab62c8cd2aa57c40aea1f490b4c8bb21d91` |
| Header | entry point `0x80246000`; the title field (20 bytes: 14 characters, then 6 spaces of padding); game code `NSME`; revision 0; check code `635A2BFF 8B022326` |
| Boot code | CIC-NUS-6102 (CRC-32 of `0x40..0x1000` is `90BB6CB5`); `header_checksum` computes `635A2BFF 8B022326` from `0x1000..0x101000`, so the header verifies |
| Decompilation | [n64decomp/sm64](https://github.com/n64decomp/sm64) pins the same SHA-1 for its US build (`sm64.us.sha1`: `9bef1128…86ce  build/us/sm64.us.z64`) |
| `classic-retro detect` | platform `n64`, confidence 1.0, metadata `boot_code` `CIC-NUS-6102`, `byte_order` `big-endian (z64)`, `checksum_valid` `true`, `game_code`, `header_checksum`, `revision`, `title`; no game |

## The image

- **Checksum window.** The boot code checks `0x1000..0x101000` (`patching.n64`). Inside it:
  the whole main code segment, ROM `0x1000..0xF5580` (1000832 bytes), loaded at
  `0x80246000`; the width table (`0xEC370`) and the loader of segment 2 (`0x3AC0`) are in it;
  and the first 47744 bytes of the engine segment, ROM `0xF5580..0x108A10` (78992 bytes),
  which the function at `0x80278974` (ROM `0x33974`, the pairs at `0x3397C..0x339D8`) DMAs to
  `0x80378800`. Outside it: the engine segment's last 31248 bytes, the entry segment
  (`0x108A10..0x108A40`, 48 bytes of level script whose `EXECUTE` command names the menu
  script, ROM `0x269EA0..0x26A3A0`, as segment `0x14`), every MIO0 block,
  the raw code of the menus (`0x21F4C0..0x269EA0`, 305632 bytes, loaded at `0x8016F000` by
  a `FIXED_LOAD` level command, `16 10`, of which the image holds six copies; every call site
  of the menu-font printer is in it, and by the decompilation's account, not checked here, so
  is the Mario head) and the padding at the end. A change inside the window needs
  `with_header_checksum`; a change outside it does not.
- **MIO0 blocks.** 79 `MIO0` magics, all 79 decode (`find_mio0`, `research mio0`): 3438897
  packed bytes hold 7463840. Every block starts on a 16-byte boundary (34 on 32, 18 on 64, 4 on
  256); none overlaps the next; the gap from a block's end to the next block's start is 0 to
  333315 bytes. The first block is at `0x108A40`, the last at `0x4D1910` (ending `0x4EB1E6`).
  78 of the 79 are named by the start word of a 12-byte level-script load command somewhere
  in the image (141 commands `18`, `LOAD_MIO0`, and 31 commands `1A`, `LOAD_MIO0_TEXTURE`, in
  the decompilation's `level_commands.h`); the one that is not is `0x108A40`, segment 2,
  loaded from code.
- **The end.** The image ends with 211264 bytes of `FF` from `0x7CC6C0` (`0x33940`), the only
  run of `FF` or `00` of 4 KiB or more; it is outside the checksum window.

## Segment 2

The dialogue, the course and act names and the three fonts live in segment 2, the block at
`0x108A40`: 48390 packed bytes (`0xBD06`) hold 100878 (`0x18A0E`); its header puts the
match stream at `+0xF30` and the literal stream at `+0x7900`. The next block starts at
`0x114750`, so the slot is 48400 bytes with 10 bytes of zero slack. No word of the image
equals `0x108A40` or the block's end `0x114746`: the loader builds the range in registers.
(`0x114750` occurs once, at `0x2ABCA4`, as the start of the next block's own `LOAD_MIO0`.)

- **The loader.** The function at `0x80248964` (ROM `0x3964..0x3AF0`, one caller) loads the
  entry segment and then segment 2:

  | ROM | Instruction | Value |
  |-----|-------------|-------|
  | `0x3AA4` / `0x3AB0` | `lui a1,0x11` / `addiu a1,a1,-30192` | `0x108A10`, the entry segment's start |
  | `0x3AA8` / `0x3AAC` | `lui a2,0x11` / `addiu a2,a2,-30144` | `0x108A40`, the entry segment's **end** |
  | `0x3AB4`, `0x3AB8` | `addiu a0,zero,16`; `jal 0x8027868C` | load segment `0x10` raw |
  | `0x3AC0` / `0x3ACC` | `lui a1,0x11` / `addiu a1,a1,-30144` | `0x108A40`, segment 2's start |
  | `0x3AC4` / `0x3AC8` | `lui a2,0x11` / `addiu a2,a2,18256` | `0x114750`, segment 2's end: the slot's end, not the block's |
  | `0x3AD0`, `0x3AD4` | `jal 0x802787D8`; `addiu a0,zero,2` | load segment 2 and decompress it |

  The value `0x108A40` is therefore built twice: at `0x3AA8`/`0x3AAC` as the end of the
  previous load, which must stay, and at `0x3AC0`/`0x3ACC` as the start that a moved block
  changes. The decompressing loader (`0x802787D8`, ROM `0x337D8`, 55 words, this one caller)
  rounds the range up to 16 bytes, takes that much from the pool (`0x80278120`), DMAs it
  (`0x80278504`), reads the decompressed size from the block's own header word at `+4`, takes
  that much from the pool, decodes (`0x8027F4E0`), sets the segment's base (`0x80277EE0`) and
  frees the packed copy (`0x80278238`): a block of another size needs no other change, but a
  larger decompressed size is a larger allocation (see the open questions).
- **Repacking.** `compress_mio0` packs the decoded segment into 47858 bytes, 532 fewer than
  the original and 542 under the slot; the round trip is exact and `mio0_packed_size` agrees
  with the length.

Offsets in the rest of these notes are into the decoded segment (`research mio0 --extract
0x108A40` writes it); the game addresses them as `0x02000000 + offset`, and the main code
builds the table and list addresses below with `lui`/`addiu` pairs (one site for the dialogue
font's table, two for the dialogue table, three for the course names, two for the act names,
three for the HUD font's table, one for the credits font's). `research pointer-tables` on the
extracted file with `--base 0x02000000 --byteorder big` lists the three text tables (171, 26
and 97 ascending pointers; the first of the 171 is the word before the dialogue table, the
last entry's string pointer).

| Offset | Content |
|--------|---------|
| `0x0000..0x4A00` | HUD font textures: 37 of 16x16 texels in RGBA 16-bit, 512 bytes each |
| `0x4A00..0x5900` | credits font textures: 30 of 128 bytes (8x8 RGBA 16-bit) |
| `0x5900..0x7000` | dialogue font textures: 92 of 64 bytes, one per code, contiguous; `00..3D` in code order from `0x5900`, the other 30 in an order of their own (the lookup table, not the code, locates a texture) |
| `0x7000..0x7700` | textures named by five of the six pointers at `0x7C7C` (the sixth names a HUD texture), not surveyed |
| `0x7700..0x77E8` | HUD font lookup table: 58 words, 37 of them pointers |
| `0x77E8..0x7BE8` | dialogue font lookup table: 256 words, 92 pointers, 164 zero |
| `0x7BE8..0x7C7C` | credits font lookup table: 37 words, 30 pointers |
| `0x7C7C..0x7D34` | six texture pointers (one site of the main code builds `0x02007C7C`); then two strings (88 and 25 bytes with their terminators; 40 of the first's 87 codes and 6 of the second's 24 are free codes or the marks `F0`/`F1`, which this font cannot draw, and the rest are glyphs, spaces, newlines and, in the first, one word code: another release's encoding), two 16-byte entries of the dialogue layout at `0x7D08` and `0x7D18` that point at them (8 lines, x 30, y 200; 3 lines, x 100, y 150) and a table of the two at `0x7D28` with a zero word after it, which no site of the main code builds |
| `0x7D34..0xFFC8` | the 170 dialogue strings, in entry order, 4-byte aligned, zero-padded |
| `0xFFC8..0x10A68` | the 170 dialogue entries, 16 bytes each |
| `0x10A68..0x10D14` | the dialogue table: 170 pointers to the entries, in order; a zero word follows |
| `0x10D14..0x10FD4` | the 26 course-name strings (`0x10D14..0x10F67`, then a zero byte) and their table at `0x10F68`: 26 pointers, in order; a zero word follows |
| `0x10FD4..0x11AC0` | the 97 act-name strings (`0x10FD4..0x11929`, then three zero bytes) and their table at `0x1192C`: 97 pointers, in order; zero words from `0x11AB0` |
| `0x11AC0..0x11E10` | the display lists the text code names (eleven addresses built by the main code, `0x11AC0` to `0x11DC0`): the glyph quad's vertices at `0x11C88`, `begin` at `0x11CC8`, the glyph draw's list at `0x11D08`, `end` at `0x11D50` |
| `0x11E10..0x18A0E` | textures, display lists and matrices (the main code builds addresses from `0x17350` on), not surveyed for text |

## Text

- **Dialogue table.** 170 entries of 16 bytes at `0xFFC8`: a word (1 in 167 entries, 2 in
  two, 3 in one), a signed byte of lines per box (1 in 2 entries, 2 in 9, 3 in 21, 4 in 52,
  5 in 57, 6 in 29), a zero byte, a signed halfword x (30 in 125 entries, 95 in 38, 150 in
  7), a signed halfword y (200 in 169, 150 in one), two zero bytes, and the string's address.
  The pointer table at `0x10A68` lists the entries in order. The box routine (`0x802D8E2C`,
  ROM `0x93E2C`, one caller) translates to (x, y) before anything is drawn, so x is the left
  edge the lines start from and y the box's vertical position (the projection's *y* points
  up); the renderer (`0x802DA1AC`, ROM `0x951AC`) clips the box to 132 pixels across from x
  and 16 rows a line down from `240 - y` (`0x955E8`, `0x9568C`).
- **Dialogue strings.** 170 strings from `0x7D34` to `0xFFC8` (33428 bytes): 33167 bytes of
  strings with their `FF` terminators, 32997 codes of which 1567 are the newline `FE` (1737
  lines in all, 33 at most in one dialogue, one to ten boxes), and 261 zero bytes of padding
  (0 to 3 after each string, so that every string starts on a 4-byte boundary; one after the
  last). The longest string is 613 bytes with its terminator. The strings use 85 distinct
  codes. Measured with the width table, the widest line is 133 pixels (one line; every other
  is 131 or less) against the box's 132-pixel clip; four lines carry the number code `E0`.
- **Course names.** 26 strings from `0x10D14` (562 bytes with terminators, 0 to 30 codes
  each, no newline; the string at index 24 is empty; 39 distinct codes), the table at
  `0x10F68`.
- **Act names.** 97 strings from `0x10FD4` (2235 bytes with terminators, 0 to 33 codes each,
  no newline; the last six, 91 to 96, are empty; 37 distinct codes), the table at `0x1192C`.
- No run of six or more letter codes ending in `FF` lies anywhere else in the segment.
- **Codes.** By the lookup table and the glyphs themselves: `00..09` the digits, `0A..23`
  the capitals, `24..3D` the small letters (the five that reach below the baseline are `2A`,
  `2D`, `33`, `34` and `3C`), `3E` an apostrophe, `3F` a full stop, `50..58` the nine pad
  glyphs (four arrows, five buttons), `6F` a comma, `9F` a hyphen, `E1..E6`, `F2..F7` and
  `F9..FD` signs (brackets, an arrow, an ampersand, a colon, an exclamation and a question
  mark, a percent sign, quotation marks, a tilde, a ring, two stars, a cross and a dot), `9E`
  the space (no glyph, 5 pixels), `FE` the newline and `FF` the end. Codes without a glyph
  that the strings use: `9E`, `D0` (a double space), `D1` and `D2` (two three-letter words of
  15 pixels, drawn from a 5-byte entry each, length then codes; the main code holds two
  identical copies of the pair, ROM `0xEC4A4` for the generic printer and `0xEC4C0` for the
  dialogue printer) and `E0` (the dialogue printer writes in the number at `0x803613F4` as one
  or two digit glyphs of this font; the generic printer would draw it as a glyph). `F0` and
  `F1` make the generic printer draw glyph `F0` or `F1` over the next glyph, 5 pixels right
  and 5 up; the dialogue printer records them and never draws them, and `6E` makes the generic
  printer alone draw glyph `F1` 2 pixels left and 5 down: none of the three has a glyph in
  this image and no string uses them (presumably the Japanese release's marks; nothing in
  this image says what they were). 92 codes have a glyph, 10 are read as something else by at
  least one printer (`6E`, `9E`, `D0..D2`, `E0`, `F0`, `F1`, `FE`, `FF`), and the other 154
  are free: `40..4F`, `59..6D`, `70..9D`, `A0..CF`, `D3..DF`, `E7..EF`, `F8`. Every free code
  falls to the glyph path of both printers, which would read a zero pointer from the table, so
  a new code needs its table word, its texture and its width. Nine glyphs are drawn by no
  string of the dialogue or the names: `E2`, `E4`, `F3`, `F7`, `F9..FD`.

## The dialogue font

- **Lookup table.** 256 words at `0x77E8` (the main code builds `0x020077E8` at ROM
  `0x925E8`, inside the glyph draw); a code's word is the address of its texture or zero.
  The 92 textures lie at `0x5900..0x7000`, 64 bytes each, contiguous and none shared; only
  the 62 of `00..3D` are in code order (`0x5900 + 64 * code`), the other 30 lie after them
  in an order of their own (`0x5900 + 64 * 0x3F` holds `F2`'s texture, not `3F`'s), so a
  texture is reached through the table, never computed from its code.
- **Texture.** IA 4-bit, 16 texels in *s* by 8 in *t*: the glyph draw emits `SETTIMG` IA
  16-bit then the list at `0x11D08`, which loads 32 16-bit texels as one block, sets tile 0 to
  IA 4-bit with a line of one 8-byte row, `maskS` 4 and `maskT` 3, and sizes it `(0,0)` to
  `(15,7)`. Texel `(s, t)` is the nibble at byte `8t + s/2`, the high nibble for even *s*.
  Only the nibbles `0` and `F` occur in all 92 textures (10129 and 1647 of 11776): the glyphs
  are one-bit shapes, white where `F`.
- **The quad.** Four vertices at `0x11C88`, position then `(s, t)` in texels: `(0, 0)` with
  `(0, 8)`, `(8, 0)` with `(0, 0)`, `(8, 16)` with `(15, 0)`, `(0, 16)` with `(15, 8)`; two
  triangles. So *t* runs from 8 at the left edge to 0 at the right, and *s* from 0 at the
  bottom to 15 at the top, the projection's *y* pointing up (both printers put line *n* 16
  below line *n − 1* by subtracting from *y*). **Texel `(s, t)` is screen column `7 - t`, row
  `15 - s`** from the glyph's top left. Decoded that way in a scratch image, the digits 1, 2
  and 7, the capitals F, J, L, P and R, the small b, d and r, the apostrophe and the comma are
  upright and unmirrored; `(t, s)` turns them by a half turn, `(t, 15 - s)` mirrors them left
  to right and `(7 - t, s)` flips them top to bottom. (The two earlier passes disagreed; the
  one with `s = row` was wrong.)
- **The cell.** 8 columns by 16 rows. Ink starts in column 0 for 84 glyphs and column 1 for
  8; every capital and digit occupies rows 3 to 12 exactly; the small letters end on row 12
  (21 of them) or 14 (the five descenders); the topmost ink of any glyph is row 2, the lowest
  row 14. Ink is 2 to 8 columns wide (two glyphs of 2, 8 of 3, 20 of 4, 31 of 5, 17 of 6, 10
  of 7, 4 of 8: `E4`, `F9`, `FA`, `FD`); the advance is the ink width plus one for 75 glyphs,
  plus two for 9, plus three for 3 and plus nothing for 5. Four advances exceed the cell (`E2`
  10, `E4` 9, `FA` 10, `FD` 10). The letters are slanted.
- **HUD font.** 58 words at `0x7700` (three sites of the main code), 37 glyphs (`00..12`,
  `14..19`, `1B..1E`, `20`, `22`, `32..35`, `38..39`) of 16x16 RGBA 16-bit (512 bytes,
  textures at `0x0000..0x4A00`), drawn by the routine at `0x802D69F8` (one call site); the
  credits font is 37 words at `0x7BE8` (one site), 30 glyphs of 128 bytes, drawn as texture
  rectangles by `0x802D82D4` (one call site).

## The width table

256 bytes at RAM `0x80331370`, ROM `0xEC370`, in the main code segment and inside the
checksum window. 96 entries are nonzero, 3 to 10 (one 3, six 4, 24 of 5, 29 of 6, 21 of 7,
eleven 8, one 9, three 10): the codes `00..41`, `50..58`, `6F`, `9E..9F`, `E0..E6`,
`F2..F7`, `F9..FD`. Every glyph has a width; `40`, `41`, `9E` and `E0` have a width and no
glyph. Fifteen sites of the main code address it, found as a `lui 0x8033` whose register is
then the base of an `addiu ...,0x1370` or an `lbu ...,0x1370(...)`; the whole image holds 18
instruction words with the immediate `0x1370`, the same fifteen and three in data or other
code with no such base, and no word of the image holds the table's address. No code outside
the main segment addresses it.

| Sites (ROM) | Routine |
|-------------|---------|
| `0x92760` | the multi-glyph words, generic (`0x802D76C8`) |
| `0x929B8`, `0x92A10`, `0x92ADC` | the generic printer (`0x802D77DC`): the double space, the space, a glyph |
| `0x93284` | the menu-font printer (`0x802D7E88`, 275 words, 45 call sites, all in the raw menu code): its glyphs are 8-bit IA texture rectangles from a table in segment 7 (`0x0700B840`), its space 4 pixels, so the menus share the widths but not the font |
| `0x93894`, `0x93970` | two measuring routines: `0x802D8844` (x less half the string's width, 5 call sites) and `0x802D8934` (the string's width, 2 call sites) |
| `0x944C0`, `0x94510`, `0x9457C`, `0x945D0` | the number (`0x802D944C`) |
| `0x946C0`, `0x94760` | the multi-glyph words, dialogue (`0x802D9634`) |
| `0x94B68`, `0x94BB8` | the dialogue printer (`0x802D982C`): the pending spaces, a glyph |

## How text is drawn

- **Glyph draw.** `0x802D75DC` (ROM `0x925DC`, 59 words, 8 call sites, all in the main
  code): takes a code, resolves the table and the texture through `segmented_to_virtual`
  (`0x80277F50`), emits a pipe sync, `SETTIMG` and the list at `0x11D08`, which draws the quad
  at the current matrix. Nothing in it moves the pen.
- **Translate.** `0x802D7070` (ROM `0x92070`): allocates a 64-byte matrix, fills it with a
  translation and pushes or multiplies it (first argument 1 or 2). 38 call sites in the main
  code and 2 in the menu code, 40 in all.
- **Generic printer** `0x802D77DC` (ROM `0x927DC`, 234 words, 37 call sites in the main code
  and 19 in the menu code): pushes a translation to `(x, y)`, then for each code: `FE` pops
  and pushes `(x, y - 16 * line)`; `9E` translates by the space's width; `D0` by twice it;
  `D1` and `D2` draw the word's glyphs each followed by its translate; `F0`, `F1` and `6E` as
  above; any other code is drawn and then translated by its width; `FF` pops.
- **Dialogue printer** `0x802D982C` (ROM `0x9482C`, 289 words, one call site, `0x95750` in
  the renderer): a code below `0x9F` is a glyph unless it is `9E`, which adds one to a count of
  pending spaces; `9F..CF` are glyphs; `D0..FF` go through a 48-entry jump table at ROM
  `0xF31B8`: `FF` the end, `FE` the next line, `F0` and `F1` the marks, `D0` two pending
  spaces, `D1` and `D2` the words, `E0` the number, and the other 40 glyphs. A glyph of a
  visible line (from the lower bound the caller passes to that plus the lines per box) first
  translates by the space's width times the pending spaces, then is drawn, then translates by
  its own width. The printer has no character counter: it draws every glyph of the visible
  lines each time it runs.
- **Left to right, one point of change.** Both printers draw a glyph at the pen and then move
  the pen right by the code's width; the pen never moves left, and neither printer measures a
  line before drawing it (the two measuring routines serve other screens). For Arabic this
  means one of two things, as for [New Super Mario Bros.](NSMB_ARABIC_RENDERER.md): either
  MIPS changes at the sites above (a mirrored draw needs the line's width first, so every
  place that starts a line would change too, in a big-endian MIPS the toolkit cannot yet
  encode), or lines stored in visual order, the leftmost glyph first, drawn by the game
  unchanged and aligned at build time: a right edge is reached with leading blanks, the space
  (5 pixels) or a blank glyph of width 1 on a free code, since the dialogue printer applies
  pending spaces before the next glyph.

## Room

- The 211264 bytes of `FF` at `0x7CC6C0` lie outside the checksum window and after every
  ROM range a level-script command names: the highest load command's range ends at
  `0x4EB1F0` (the last MIO0 block's slot), and the highest of all, a script segment named by
  an `EXECUTE` command, at `0x4EC000`; what the audio code reads between there and the run was
  not surveyed.
- Segment 2 repacked with `compress_mio0` is 47858 bytes in a slot of 48400: 542 bytes to
  spare, before any glyph is added (a code's texture is 64 bytes, a translated script replaces
  33167 bytes of English).
- Moving the block means a new start at `0x3ACC` (and its `lui` at `0x3AC0`) and a new end at
  `0x3AC8` (and `0x3AC4`), 16-byte aligned like every block of the game, then
  `with_header_checksum`, since the loader lies inside the window; nothing else names the
  block. The block's own header carries the decompressed size, so the segment may hold more.

## Arabic budget

- 154 free codes against the repertoire's 133 glyphs (`arabic.repertoire`: 119 contextual
  forms of the 36 letters and 14 static characters, the punctuation, tatweel and digits), each
  needing a 64-byte texture in segment 2 and a width byte in the main segment.
- The cell is 8 pixels wide and 16 tall with the letters ending on row 12, the geometry of
  [Advance Wars](ADVANCE_WARS_ARABIC_RENDERER.md), which at size 10 found 37 forms wider than
  8 pixels and gave each two codes, the right part painted first: 170 codes if every form gets
  one, 16 more than are free. So the target gives codes only to the forms its script uses, as
  New Super Mario Bros. (84 of 166) and Tactics Ogre did, or takes a smaller size. The
  reference font was not available in this session, so nothing was measured here.
- A box's line holds 132 pixels (the renderer's clip; the English's widest line is 133), one
  to six lines a box.
- A line of a translated dialogue holds no Latin letters or digits (visual order keeps their
  direction); the number `E0` is the game's own digits and stays one unit, as the number
  New Super Mario Bros. writes in.

## What the toolkit has and lacks

After this change: the MIO0 codec and block finder (`rebuild.mio0`), the three byte orders,
the header fields, the boot code's identity and the CIC-NUS-6102 check code, computed,
verified and rewritten (`patching.n64`), the header in `detect`, and `research mio0` to list
and extract blocks. Still missing: big-endian MIPS encoders or an assembler (`cpu.mips` is the
PlayStation's little-endian R3000A), a MIPS disassembler (`research disasm` is ARM7TDMI; the
code above was read with a scratch reader), analog-stick input and a hardware render callback
in the libretro front end (it presses RetroPad buttons, reads a pointer and takes software
frames, and the game is played with the stick), and any Super Mario 64 adapter, engine or
target.

Two routes:

- **ROM overlay, visual order, no code hooks.** Segment 2 rebuilt: the Arabic strings in
  visual order, the tables, the lookup table's new words and textures, packed with
  `compress_mio0`; the width bytes in the main segment; the block moved to the `FF` run if it
  outgrows the slot; the checksum. Only data changes, as in New Super Mario Bros., and the
  limits are its: a line holds nothing with a direction of its own, and the game must draw a
  line whole.
- **Source overlay over n64decomp/sm64.** The decompilation builds this exact image from its
  assets; a `prepare` step would patch its C (the two printers and the glyph draw, one point
  each) and its segment 2 sources. It costs the decompilation's toolchain per user and a
  mirrored draw written in C, and buys a right-to-left pen, runtime names and no bidi limits.

Open questions an emulator must answer before either is chosen:

1. Does a dialogue page appear at once or type out? The printer draws every glyph of the
   lines it is given each frame; whether the caller reveals them gradually (by its lower
   bound, its alpha or anything else) was not read. A typewriter would reveal a visual-order
   line from its left end.
2. Does a larger decompressed segment 2 fit the pool where the loader takes it, with every
   level's data loaded after it?
3. Text outside segment 2 is not surveyed: the menus draw from a font in segment 7 with the
   menu-font printer (the raw menu code builds 39 addresses of strings in this encoding, 382
   codes in all, the first at ROM `0x2581B8` and the last at `0x25866C`), the HUD from its
   own font, the credits from theirs.

## Not verified

- The decompilation's names for the routines and tables above were not checked against its
  source this session (only `sm64.us.sha1` and `level_commands.h` were); the notes name them
  by address.
- Which caller feeds the dialogue printer, with what lower bound, and how a box's pages
  follow each other, was not read.
- The regions of segment 2 marked not surveyed were scanned only for runs of letter codes.
