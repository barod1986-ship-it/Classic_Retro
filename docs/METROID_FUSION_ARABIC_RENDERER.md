# Metroid Fusion Arabic Renderer v1

Target: *Metroid Fusion* (USA). The [metroidret/mf](https://github.com/metroidret/mf)
decompilation matches this image and names the code below, but it cannot be shifted
and takes its data from the original, so this is a binary ROM overlay built from the
user's image, like the targets without a decompilation. The facts below come from
the decompilation's sources and the image's own code, checked with the
[research tools](RESEARCH_TOOLS.md) (`disasm`, `free-space`, and mGBA runs with
breakpoints and watchpoints).

| Item | Value |
|------|-------|
| ROM size | 8388608 bytes |
| SHA-1 | `ca33f4348c2c05dd330d37b97e2c5a69531dfe87` |
| SHA-256 | `a56ce3d7f8f3f4f4d0468d421fff5dd3ee3aec99a58244377e43aae769dc3fe8` |
| Game code | `AMTE` (`METROID4USA`), header revision 0 |
| Output | 8 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Text.** A string of 16-bit units ended by `FF00`. Which units are commands depends
  on the routine that reads it; any other unit is a glyph. The English text uses the
  Latin codes `0x40..0x5F`, `0x80..0x9F` and `0xC0..0xDF` (ASCII shifted by 0x20,
  0x40 and 0x60).
- **Font.** `GetCharacterWidth` (`0x08079118`) gives code `c` the width at
  `0x08576234 + c` up to `0x49F`, and 10 above. `DrawCharacter` (`0x0807913C`) reads
  glyph `c` from a sheet of 4bpp tiles, 32 a row: the tile at `0x08682FAC + 32 * c`
  above the one at `+ 0x400`, and for a glyph wider than 8 pixels the next code's two
  tiles on its right, up to 16 pixels. It ORs the glyph into a row of tiles at a pixel
  offset, spilling into the tiles on its right. Pixel 2 is the ink and 3 the outline
  around it, on all eight sides; its last argument, a colour `n`, draws them as
  `2 + 2n` and `3 + 2n`.
- **Lists.** The game reads each list of texts by the language byte at `0x03000011`,
  which is 2 (English) in this image: the monologues (19, at `0x0879E6EC`), the
  briefings (201, at `0x0879D50C`) and the messages (74, at `0x0879C810`).
- **The new-file intro** (`NewFileIntroHandler`) tells the story through twelve
  monologues (Samus's narration in cutscenes), read by index as its scenes go on: 8 to
  17, then 18 and 0. Its current text is the first word of `gNonGameplayRam`
  (`0x03001484`), and three routines draw it, one character each call. They read
  `FE00` as a line end, `FD00` as a new page, `FC00` as the next-page arrow (it waits
  for A) and `E1xx` as a wait of `xx` frames.
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
- **The briefings** on the map (`NavigationConversationHandler`, `0x0807A3A4`): the
  ship's computer speaks in a box of two lines. The text of conversation `n` is entry
  `(n - 1) * 2` of the list, or the next one when the conversation comes again
  (`gPreviousNavigationConversation`, `0x03000B88`); `n` is at `gNonGameplayRam + 0x220`.
  `NavigationConversationProcessText` (`0x08079AFC`) draws it one character each call,
  at `0x06007000` (the second line `0x800` bytes down) or, for the second panel, at
  `0x06006000`, and reads every unit from `0x8000` as a command but `Bxxx` (past
  `B001..B003`), `Dxxx` and odd `Fxxx`, which are glyphs:
  - `80xx` moves the pen `xx` pixels, `81xx` sets the colour of the glyphs that
    follow, `82xx` their speed and `83xx` puts the pen at `xx` on its line; `9xxx` and
    `Axxx` play sounds, `B001..B003` and `Cxxx` are events (`B003` starts the music);
    `E000` shows the target on the map, `E1xx` waits, `E2xx` picks a panel and the other
    `Exxx` set flags;
  - `FE00` ends a line (on the second one, the box scrolls at once), `FC00` waits for A
    and ends the line, `FD00` waits for A and clears the box, and `FB00` asks the
    objective question, after which the text goes on in a cleared box.
  A line that would pass 224 pixels wraps. The typing cursor (an 8x8 sprite, a
  6-pixel line from its x) follows the pen at `x = pen + 8`.
- **The objective questions** (`0x0807A0FC`): messages 43 (whether the objective is
  clear) after a briefing, and 44 (whether to hear it again) when a briefing comes again, drawn
  at `0x06007000` with a pen of their own. They read only `FE00`, `80xx` and `83xx`
  (`83A0` puts the pen 16 pixels before `0xA0`) as commands, and end at the glyph
  before `FF00`. English: the question on the first line, then Yes at `0x40` and No at
  `0x90`. The handler moves a cursor (a triangle pointing right, `x - 1` to `x + 5` as it
  bobs) to `x = 0x34` for Yes and `0x84` for No: left chooses Yes, right No.
- **Arrows and cursors in the intro.** `NewFileIntroProcessTextCursor` puts the
  next-page arrow (an 8x8 sprite centred on its x) at the bottom right (x = 235) at
  `FC00`; `NewFileIntroProcessAdamTextCursor` puts the ship computer's typing cursor 14
  pixels past the pen (the arrow there, and the monologue page's, are centred). A
  briefing's arrow is centred too.
- **Screen.** The strip's, the box's and the page's first pixel is at x = 8 of the
  240-pixel screen; the English lines are at most 224 pixels wide.
- **Free space.** The image ends with 398136 bytes of `0xFF` from `0x0879ECC8`, 7 MiB
  from the text code: out of a `BL`'s 4 MiB reach. `Dma3Transfer_Unused1`
  (`0x08098940`, 64 bytes, next to the intro's text routines) is called by nothing.

## Right-to-left text

The routines keep their pen and lay a line out from the left. For a right-to-left
glyph the overlay mirrors where it lands on a line of 224 pixels (**mirrored draw**):

```text
left' = 224 - pen - width
```

A line then starts at the right edge (x = 232) and grows leftwards, and the
typewriter reveals it from the right.

1. `hook_draw`, called instead of `DrawCharacter` at the five drawing calls (the
   strip, the ship's computer, the monologue page, the briefings and the question),
   turns the tile and pixel offset it is given into the mirrored ones for a code of the
   right-to-left font, and calls `DrawCharacter` with the caller's registers and stack
   (its fifth argument, the colour, is on the stack). The glyphs are not flipped, and
   English glyphs keep their place.
2. `hook_fade`: the page's fade walks the tiles in the pen's order, and for Arabic
   updates the tilemap entry of the mirrored column (`27 - column`). The tiles a glyph
   covers are exactly the mirrors of the ones the pen marked.
3. `hook_arrow` puts the strip's next-page arrow at the other end of the bottom line
   (x = 4); `hook_cursor` puts the ship computer's typing cursor left of the text, at
   the mirror of its place (x = 226 - pen).
4. `hook_nav_cursor` does the same for a briefing's typing cursor on either line
   (x = 226 - pen on the line), and `hook_nav_cursor_start` for its place before the
   first character, as a briefing starts and when it starts again (x = 226, where the
   game puts 8).
5. `hook_width` replaces `GetCharacterWidth`: the game's widths below `0x4A0`, the
   right-to-left glyphs' from `0xB040`, 10 otherwise as before.
6. The question's options change sides: the handler's immediates put the cursor left
   of each Arabic option (Yes on the right), and the right key now chooses Yes, the
   left one No.

`hook_draw` knows a right-to-left glyph by its code. The other hooks keep the game's
path for English text: the intro's check whether its current text lies in the Arabic
bank, and `hook_nav_cursor` finds the briefing's text as the game does (the entry of
the conversation in the language's list) and checks the same.

The right-to-left glyphs have codes from `0xB040`, which every routine draws as
glyphs: `DrawCharacter` reads glyph `c` at `0x08682FAC + 32 * c`, which for these codes
falls in the padding, where the overlay writes their sheet. A briefing reads `0x8000`
up as commands but `Bxxx`, so the codes start past `B001..B003` (the first build used
`0x9000`, which a briefing reads as sounds). Every glyph takes two tile columns (one
code every two in a row of 32, rows of 32 codes alternating with the rows of their
lower halves), so it may be 16 pixels wide: no form is split. The space is the game's
own (`0x40`, 6 pixels), so the ship's computer stays silent between words.

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
| `0x08098968` | `hook_nav_cursor` | `r1`: the cursor's x, which the hook returns |
| `0x08098970` | `hook_nav_cursor_start` | `r1`: the cursor's x, which the hook stores |

A first build that sent the fade through `ip` hung the page after a few glyphs: its
loop never reached its end. A veneer must leave alone every register its site still
uses.

## ROM layout

| Address | Content |
|---------|---------|
| `0x0879F000` | Thumb hooks (`src/classic_retro/rom/metroid_fusion_arabic_hooks.s`, 320 bytes) |
| `0x0879F800` | The right-to-left widths: a byte for each code from `0xB040` (2 KiB) |
| `0x087A0000` | The Arabic bank: the 18 translated texts, up to `0x087E0000` (256 KiB: every free byte before the sheet, room for every text of the game) |
| `0x087E37AC` | The right-to-left glyph sheet: glyph `0xB040` onwards, 136 glyphs in 9 rows of `0x800` bytes |
| `0x08098940` | The six veneers (56 bytes) |
| `0x08079118` | `GetCharacterWidth`: a jump to `hook_width` |
| The English lists | The 18 pointers, now to the Arabic texts |

A stored text ends with `FF00`, then zeros up to a word. The overlay checks the input
hash, the code at every site and the entry of `GetCharacterWidth`, the SHA-256 of
`Dma3Transfer_Unused1`, the bytes the hooks rely on (the width table and the glyph
sheet's address, the game's space, the intro's data, the strip's tiles, the page's last
column and fading map, the typing cursors' code and sprites, how a briefing finds its
text, the question's message, pen and cursor sprite, the three English lists), that
the padding is still `0xFF`, and for every translated text its list, its place there,
its SHA-256 and its commands. After writing it reads back every site, veneer, table,
immediate and text.

## Hooks

| Site | Original | Hook |
|------|----------|------|
| `0x08079118` | `push {lr}; lsls r0, r0, #16; lsrs r1, r0, #16; ldr r0, =0x49F` (the entry of `GetCharacterWidth`) | `hook_width` (`ldr r1, =hook; bx r1`) |
| `0x08098690`, `0x080988D4`, `0x080980CC`, `0x0807A076`, `0x0807A28E` | `bl DrawCharacter` (the strip, the ship's computer, the page, the briefings, the question) | `hook_draw` |
| `0x080981F8` | `lsls r2, r6, #1; lsls r0, r7, #7` (the fade's tilemap entry) | `hook_fade` |
| `0x08098C1E` | `movs r0, #235; strh r0, [r2, #12]` (the arrow's x) | `hook_arrow` |
| `0x08090740` | `adds r0, #14; movs r1, #0` (the cursor's x) | `hook_cursor` |
| `0x0807A65A`, `0x0807A696` | `ldr r4, =0xFF28; adds r1, r2, r4` and `adds r1, r2, #0; adds r1, #8` (a briefing's cursor on each line) | `hook_nav_cursor` |
| `0x0807AB5C`, `0x0807ADF6` | `movs r1, #8; strh r1, [r0, #0x2e]` (the cursor as a briefing starts, and again after No) | `hook_nav_cursor_start` |

The question's handler keeps its code; ten of its immediates change for the two
translated questions (`movs rN, #imm8`):

| Message | Cursor's x at the start | On Yes | On No | Key to Yes | Key to No |
|---------|------------------------|--------|-------|------------|-----------|
| 43 | `0x0807A88A` (Yes) | `0x0807A90C` | `0x0807A91A` | `0x0807A8A8` | `0x0807A8D0` |
| 44 | `0x0807ACA2` (No) | `0x0807AD28` | `0x0807AD36` | `0x0807ACC6` | `0x0807ACEC` |

The cursor's x is worked out from the Arabic question: 12 pixels left of each option's
mirrored end. The keys swap: right (`0x10`) chooses Yes, left (`0x20`) No. A question
left untranslated keeps the game's code.

`classic-retro metroid-fusion check-hooks` re-assembles the source with GNU binutils
and compares the result with the bytes stored in `metroid_fusion_arabic.py` (run in CI).

## Font

- Reference font: Noto Kufi Arabic SemiBold (SIL OFL 1.1), SHA-256
  `aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
- 136 glyphs, codes `0xB040..0xB24E`: `.`, `!` and `:` drawn by hand (the font has no
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
- Coverage from 140 of 255 is ink; the outline is drawn around it. A mark whose
  coverage stays under that everywhere keeps its strongest pixel: at this size, medial
  beh's dot (139 at best) would vanish, and the first build drew «العنبر» with a
  dotless tooth.

## Translations

The script (`src/classic_retro/translations/metroid-fusion.json`; its originals are
pinned in `src/classic_retro/rom/metroid_fusion_arabic_script.py`) covers the
opening: 18 texts.

- The whole new-file intro, 12 monologues. Eleven go through the two-line strip:
  Samus's mission on SR388 and the X that attacked her, her ship drifting into an
  asteroid belt, her rescue, the surgery on her suit, the Metroid vaccine and her
  rebirth, and the ship's computer announcing the B.S.L station (in its box). The last
  one fills four pages of the nine-line monologue: the explosion on the station, her
  new mission and her new commanding officer.
- The first briefing on the map, eleven boxes: the explosion in the Quarantine Bay,
  what it holds, the target on the map, Samus's lost abilities and the Navigation Room
  on the way, then the question and the order to go. Its second text is what the
  computer says when Samus comes back.
- The second briefing, in the Navigation Room on the way: the bay ahead and the signs
  of life found there, and its own text for when she comes back. It took no change of
  code: two pinned originals and their translations.
- The two questions and their options.

For each text its list, its index there, its address, its SHA-256 and its commands are
pinned; the Arabic keeps every command in order (line ends after text may move, and so
may a pen advance's amount; a strip page holds two lines, a monologue page nine, a
briefing's box two and a question its line and options). A colour command stands
between words, since the text on each side of it is shaped apart. Names are
transliterated (إس آر ٣٨٨ with Arabic-Indic digits, بي إس إل, بيولوجيك, إكس, ميترويد,
سامس) and terms translated (الاتحاد المجري, بدلة القوة, حاسوب السفينة, عنبر الحجر
الصحي, غرفة الملاحة); Samus narrates as a woman, and the computer speaks to her as one.

## What the game's briefings use

Every one of the 201 English briefings, read from the image, and what the overlay
does with each case. The first two briefings use only colours 2 and 3, line and box
ends, the target, the music and the question; the rest of the game adds:

| Case | Briefings | In Arabic |
|------|-----------|-----------|
| Colours 1 to 6 (red, magenta, yellow, green, blue, cyan) | 63 | The game's palette draws them; the previews show them |
| Sounds (`9xxx`, `Axxx`), events (`B001..B003`), waits (`E1xx`), flags (`E3xx`), the target (`E000`) | 3 to 22 each | Kept in order; they move no pen |
| The objective question (`FB00`) | 28 | Messages 43 and 44, in Arabic for every briefing |
| A dialogue across two panels (`E200..E202`: the box at the bottom and one at the top of the screen) | 6 | The same hooks: checked with a text written for the purpose in conversation 26 (text mirrored across the whole top box, its cursor on the left) |
| A third line after `FC00` | 1 | Allowed: the reader has pressed A |
| A line the game wraps itself | 1 | The translation ends its lines itself |
| The game's second `?` (`0x41F`) | 13 | The Arabic `؟` |
| An opening quotation mark (`0x311`) | 2 | Not yet: quotation marks and brackets are mirrored characters, which the shared bidi step does not mirror, so every engine refuses them |
| Latin letters in brackets (the sector name `SRX`, codes `0x452`, `0x453`, `0x458`) | 1 | Not yet: the brackets as above; the name can be transliterated, and Latin letters inside an Arabic line would need a left-to-right run |

No English briefing scrolls its box with a line end on the second line, so the
Arabic ones do not either.

## Verification

In mGBA, with the patch built from the reference font:

- From a new game, every page of the twelve monologues: each line typed from the right
  with the next-page arrow at the bottom left, the ship computer's box with its cursor
  left of the text, and the four pages of the monologue fading in from the right. The
  same run on the first build's patch gives the same 210 screens but where medial beh
  now has its dot.
- From the landing, the whole first briefing: every box typed from the right, the
  typing cursor left of the text on both lines (at the right end before the first
  character), the names in their colours, the arrow, the target on the map, then the
  question with its cursor on نعم, right keeping it there and left taking it to لا, and
  after نعم the last order and the room; after لا, the briefing again from its start.
- The second question, with the conversation marked as coming again: centred, its
  cursor on لا, right taking it to نعم, which replays the briefing.
- The second briefing and its text for coming back, with the conversation number set
  to 2 as the game sets it in that room: typed from the right, in their colours, with
  the cursor on the left.
- With the same input from power-on and from a savestate on the landing, the title
  screen, the file select screen and the landing are pixel-identical to the original
  image's (20 screens). With the conversation switched to English ones, the English
  briefings are too, their typing cursor included (conversations 3 and 4, 180
  screens).

## Limits

- Only the new-file intro and the first two briefings are in Arabic. The other
  briefings, the game's messages and menus, and the in-game cutscenes are in English.
  The two questions are the game's for every briefing, so they are in Arabic after
  English briefings too.
- Quotation marks and brackets cannot be written yet (see the table above).
- Words drawn in the intro's pictures (the vaccine's name, the labels) stay as they are.
- The question's cursor points right, left of each option: the game has no sprite
  pointing left.
- Arabic texts cannot hold Latin letters (the right-to-left font has digits and
  punctuation only).
- No vowel marks, one font size, and no lam-alef ligature (lam and alef are separate
  forms).
