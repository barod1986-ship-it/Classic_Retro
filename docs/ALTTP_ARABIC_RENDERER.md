# A Link to the Past Arabic Renderer v1

Target: *The Legend of Zelda: A Link to the Past* (USA, SNS-ZL-USA), the second Super NES
target. The [spannerisms/usdasm](https://github.com/spannerisms/usdasm) disassembly (commit
`bcdd96e96ee092824078754b6192a5b40f1f39ac`) assembles to this exact ROM and names its code;
its data comes from the user's ROM, so this is a binary ROM overlay: it patches the user's
ROM and ships as a BPS patch of it. The text engine was read from the disassembly, checked
against the ROM's own bytes and run in snes9x with the [research tools](RESEARCH_TOOLS.md);
the [snesrev/zelda3](https://github.com/snesrev/zelda3) reimplementation (commit
`fbbb3f967a51fafe642e6140d0753979e73b4090`), whose tools read the dialogue out of this ROM,
confirmed the text format: the engine's reading of all 397 messages matches theirs byte for
byte. Names in brackets are the disassembly's.

| Item | Value |
|------|-------|
| No-Intro | *Legend of Zelda, The - A Link to the Past (USA)*: one ROM, no copier header |
| ROM | 1048576 bytes, LoROM (map `20`): CRC32 `777AAC2F`, SHA-1 `6d4f10a8b10e10dbe624cb23cf03b88bb8252973`, SHA-256 `66871d66be19ad2c34c927d6b14cd8eb6fc3181965b6e517cb361f7316009cfb` |
| Header | `THE LEGEND OF ZELDA` at `$7FC0`; `classic-retro detect` names the platform and the game |
| Output | The ROM with a second MiB (banks `$20`-`$3F`, `FF` where nothing is written), its header's size and checksum set again. Shipped as BPS |

## Engine facts the overlay relies on

- **Mapping.** LoROM: bank `$00` is the ROM's first 32 KiB, at `$8000`-`$FFFF`, and so on,
  so `$1C:8000` is offset `0xE0000`. Banks `$00`-`$3F` show work RAM's first 8 KiB at
  `$0000`-`$1FFF`.
- **Messages.** They are stored one after another, with no table, from `$1C:8000`
  [`Message_Data`], going on at `$0E:DF40` [`Message_DataExtra`] where a message starts
  with `80`, until `FF`. At boot the game finds each start and writes a 3-byte pointer a
  message to `$7F:71C0` [`CreateMessagePointers`, `$0E:D3EB`]; a message is numbered by its
  place (397 in all).
- **Codes.** `00`-`62`: a character of the font (capitals, small letters, digits, signs,
  the pad's buttons and arrows, hearts; `59` the space). `67`-`7E`: a command, a byte after
  `6B`-`6E` and `77`-`7A` [`TextCommandLengths`]: `74`-`76` the line to write on, `73` a
  scroll, `7E` a wait for the button, `78` a pause, `7A` the speed, `6B` the window's kind,
  `6A` the player's name, `6C` a digit of a number. `7F`: the end. `88`-`E8`: a word of the
  dictionary (`$0E:C703` [`WordDictionary`]: 97 pointers into bank `$0E`, a word running to
  the next's start) ([`engines/alttp.py`](../src/classic_retro/engines/alttp.py)).
- **The parse.** A message's start (`$0E:C4E2` [`RenderText_ParseMessage`]) writes it out
  into `$7F:1200`: a character as it is, a word as its characters, a command through
  `$0E:C547` [`RenderText_ExecuteCommand`] and its table (the name as its six characters,
  a number's digit as a character; the window and place are set there and dropped; the
  others copied).
- **The draw.** Each frame takes the buffer's next byte, drops its bit 7, and draws anything
  below `66` as a character; the rest goes through the table at `$0E:CA01`, from `66`. A
  character goes to `$0E:CAB8` [`RenderText_DrawSingleCharacter`], which calls `$0E:CB5E`
  [`RenderText_PerformVWFing`].
- **The glyphs.** The font is 8x16 pixels, two bits each, at `$0E:8000` [`TheFont`]: a
  code's top tile at `((code & F0) << 1) | (code & 0F)`, its bottom tile 16 tiles on; its width
  at `$0E:CADF`. The pen of each character of a line is at `$7E:C230` (from `+$00`, `+$40`,
  `+$80` a line, [`RenderText_PerformVWFing`'s `line_offsets`]), the line's tiles at `$7F:0000`
  (from `+$0000`, `+$02A0`, `+$0540`: 21 tiles, the lower half `$150` on). A glyph's pixels are
  written within its width; the rest of its row, when it crosses a tile, is stored over the next
  tile's row.
- **The lines.** `74`-`76` put the pen on line 1 to 3 [`RenderText_SetLine`]; `73` scrolls the
  three lines up a line and writes on the third [`RenderText_ScrollText`]. The English starts a
  message on line 1, writes `{2}` and `{3}` before the next lines, `{Scroll}` before each one
  after them and `{Waitkey}` where the player reads.
- **The window.** `$0E:D307` [`RenderText_DrawACharacter`] shows each row of 21 tiles a row
  down and a tile right of the window's corner (`$1CD0 + $21`). Inside its frame the window is
  22 tiles, so the English lines start against its left side and end a tile short of its right.
- **The settings.** For each message the engine copies 32 bytes of settings to
  `$1CD0`-`$1CEF` (`$0E:C493` [`RenderText_Initialize_IgnoreAttract`]); nothing else in the
  game reads or writes `$1CE4`, whose setting is `00`.
- **The font's look.** The letters are white strokes a pixel wide (value 2) with a dark outline
  all round (value 1).

## Right-to-left text

The overlay's hooks (`rom/alttp_arabic_hooks.s`, 662 bytes) live in 1503 free bytes of bank
`$0E`, the text engine's own, so they reach its code and tables with short calls. Their data is
in a second MiB the overlay adds to the ROM.

- **Arabic messages.** At a message's start, one whose number is in the overlay's list is
  parsed from its Arabic text instead, and `$1CE4` says it is Arabic (the next message's
  settings set it back to 0). The English stays where it was, as it was.
- **Glyphs.** In an Arabic message every byte below `67`, or from `80` to `E6`, is a glyph of
  the Arabic font (205 codes); the commands keep their meaning. The space keeps `59`, which the
  game types without a sound.
- **Mirrored draw.** Each glyph is drawn at `168 - pen - width` while the pen moves on as the
  engine's does, so a line starts at the right. Its two bits are ORed into the tiles: a glyph
  drawn right to left shares its tile bytes with the glyph on its right, which the engine's own
  routine would write over.
- **Names and numbers.** The parse writes the player's name and a number's digits between the
  codes `6A` and `6B` (the first the name's command, which the parse replaces, the second the
  window's, which it drops), one block for those that follow each other. The draw table's entry
  for `6A`, which no English message reaches, draws the block whole in the English font, left
  to right, as a block that ends at the mirror of the pen. So `{Name}` in an Arabic line shows
  the name the player gave, in Latin letters, the right way round, and a number's digits read
  left to right.
- **The window.** An Arabic message's rows are shown a tile further right, so its lines end
  against the window's right side as the English's start against its left.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. The glyphs come from a cell of 16x16 pixels,
the letters on row 11 (two rows above the English letters' last), at 11 pixels: the largest
size at which every form of the repertoire and every digit fits the cell with its outline (from
14 down; at 12 seen and sheen are 17 pixels wide). Coverage from 140 of 255 is ink, and a dot
between 60 and 140 keeps its strongest pixel. The merged dots of two- and three-dot letters are
drawn apart (`separated_dots`); hamza above alef is drawn by hand over the font's alef
(`alef_with_mark`), and final and isolated yeh are raised a row (`raised_form`). `.`, `,`, `:`,
`!`, `-`, `…`, `،`, `؛` and `؟` are drawn by hand. Every glyph is a white stroke with a dark
outline all round, but on a side where the letter joins the next: there the stroke runs on to
the glyph's edge, where the neighbour's goes on. The space is 4 pixels, as the English's.

## Layout

The encoder lays each page out itself, a word at a time: a line holds 168 pixels, a page three
lines. It writes the line changes as the English does: the message's second line after `{2}`,
its third after `{3}`, each next one after `{Scroll}`, and `{Waitkey}` between pages. A name
counts 42 pixels (six letters, the widest 7 each), a digit 6. The glyphs of a line are stored
in reading order: the first is drawn at the right.

## The overlay's room

| Address | Content |
|---------|---------|
| `$0E:EE30` | the hooks: `parse_hook` at `+0`, `draw_hook` at `+$B7`, `island_hook` at `+$FB`, `tilemap_hook` at `+$17D` |
| `$20:8000` | the list: 5 bytes a message (its number, its Arabic's address); `FFFF` ends it |
| `$20:8800` | a width a code (256 codes) |
| `$20:8900` | 64 bytes a code: 16 rows of plane 0, then plane 1, 16 bits each |
| `$21:8000` | the Arabic messages, none across a bank |

The hooks' room is `$0E:EE21` to `$0E:F3FF`, `FF` in the ROM; the overlay checks it is. The
added MiB is `FF` where the overlay writes nothing, and the header's size byte (`$7FD7`) goes
from `0A` to `0B`.

| Site | Original | Arabic |
|------|----------|--------|
| `$0E:C4E2`, `RenderText_ParseMessage` | `REP #$30`; `LDA $1CF0` | `JMP parse_hook` |
| `$0E:CA09`, the draw table's entry for `6A` | `dw RenderText_IgnoreThis` | `dw island_hook` |
| `$0E:CAD5`, in `RenderText_DrawSingleCharacter` | `JSR RenderText_PerformVWFing` | `JSR draw_hook` |
| `$0E:D313`, in `RenderText_DrawACharacter` | `LDA $1CD0`; `ADC #$0021`; `STA $1CD0` | `JSR tilemap_hook` |

Anchors checked before any change: the ROM (SHA-256) and its header's size; where an English
message's parse goes on; `RenderText_ExecuteCommand` and its entries for the name and a number;
the settings' copy and the `$1CE4` setting; the draw's reading of the buffer, its table and
what follows a character's draw; `RenderText_PerformVWFing`'s widths, lines' tiles and pens,
its line change, pens, font, buffer and lower half; `RenderText_DrawACharacter` after its site;
the hooks' room, free; each translated message (its number and the SHA-256 of its bytes). The
build then sets the header's checksum and checks that nothing but the sites, the hooks, the
header and the added MiB changed.

## Translations

`rom/alttp_arabic_script.py` pins three messages of the opening. The Arabic is in
`translations/link-to-the-past.json`, a line a page, `{line}` where a line must end. The three
were chosen to be unlike:

| Entry | Message | What it tries |
|-------|---------|---------------|
| `house.uncle` | `0D`: Link's uncle leaves him | the name the player gave, drawn left to right at the line's start |
| `house.zelda_calls` | `1F`: Zelda calls to Link in his sleep | six pages, waits and scrolls, slowly, in the window without a frame |
| `house.lamp` | `51`: the lamp in the chest | an item's message, three lines |

They use 72 glyphs (`00..47`) and the space, and 356 bytes of Arabic.

## Verification

With the reference font the build matches the reference patch (4204 bytes). In snes9x
(`snes9x_libretro`), from power-on with the patched ROM, a new file named `GGG`: Zelda's call in
Arabic from the right, a page at a time, scrolling as the English does; the uncle's message with
`GGG` left to right at the right end of its first line; after walking round the table to the
chest, the lamp's message. A research build that leaves the uncle's message in English draws its
box pixel for pixel as the original ROM does, and one whose uncle writes a four-digit number and
the name followed by digits shows them left to right in the Arabic line. The script, inputs only:

```text
# Core: snes9x_libretro.
run 900
tap START
run 120
tap START
run 240
# File 1, a name of three letters, START to end it.
tap A
run 90
tap A
run 30
tap A
run 30
tap A
run 30
tap START
run 180
# The file: Zelda's call starts.
tap A
run 240
shot zelda_calls.png
```

The RetroPad's A is the Super NES's A.

## Limits

- Three messages are in Arabic; every other message, the menus and the rest of the game stay
  English.
- 205 glyph codes for all the Arabic; a message holds no Latin letters, and a name is the
  player's, in Latin letters.
- A page holds three lines of 168 pixels; the encoder refuses more.
- The choices of an answer (`{Choose}` and the others) are drawn by the game on the left; the
  encoder refuses them in Arabic.
- The font is 11 pixels; no vowel marks, lam and alef stay two glyphs.
- The ROM grows to 2 MiB; the added banks hold only the overlay's data.
