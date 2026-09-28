# Shining Force II Arabic Renderer v1

Target: *Shining Force II* (USA, GM MK-1315 -00), the first Mega Drive target. The
[ShiningForceCentral/SF2DISASM](https://github.com/ShiningForceCentral/SF2DISASM) disassembly
(commit `43e9fc47370ba60efdb7daa81fe0a72deb33f046`) assembles back into this exact ROM and names
its code; the data it does not hold it splits out of the user's ROM, so this is a binary ROM
overlay: it patches the user's ROM and ships as a BPS patch of it. The text engine was read from
the disassembly, checked against the ROM's own bytes and run in Genesis Plus GX with the
[research tools](RESEARCH_TOOLS.md): the engine's reading of all 4267 strings matches the
disassembly's own script, character for character. Names in brackets are the disassembly's.

| Item | Value |
|------|-------|
| No-Intro | *Shining Force II (USA)*: one ROM |
| ROM | 2097152 bytes: CRC32 `4815E075`, SHA-1 `22defc2e8e6c1dbb20421b906796538725b3d893`, SHA-256 `9adf662d09881f58ec37d174ab01e87a7fcfb24700b5f84b26c0cd4f351509e9` |
| Header | `SEGA GENESIS` at `$100`, `GM MK-1315 -00` at `$180`; `classic-retro detect` names the platform and the game |
| Output | The ROM, the same size, its header's checksum set again. Shipped as BPS |

## Engine facts the overlay relies on

- **Strings.** 4267 strings in 17 banks of 256 [`pt_TextBanks`, pointed to from `$028000`]: a
  string's number shifted right 8 is its bank, and in the bank the strings follow each other,
  each a length byte and that many bytes of code; a length of 1 is the empty string.
  `DisplayText` (`$006260`) walks the bank to the string, keeps its code's address
  [`COMPRESSED_STRING_POINTER`, `$FFB77E`] and reads it a symbol at a time.
- **Huffman code.** A symbol's tree depends on the symbol before it (`$02E196`
  [`TextBankTreeOffsets`], a word a symbol, from `$02E394` [`TextBankTreeData`]; the first
  symbol's is the end's, `FE`). A tree is a string of bits, `0` a branch and `1` a leaf, in
  preorder; the leaves' symbols are stored before it, last first. A string's bits choose the
  left branch (`0`) or the right (`1`) ([`engines/sf2.py`](../src/classic_retro/engines/sf2.py)).
- **Symbols.** `01` the space; `02`-`50` a character of the font (digits, capitals, small
  letters, signs); `EE`-`FD` a command [`ParseSpecialTextSymbol`]: `{N}` a new line, `{W1}` and
  `{W2}` a wait for the button, `{D1}`-`{D3}` a pause, `{CLEAR}` the window cleared, `{DICT}` the
  string going on where the pen is; `{NAME;x}`, `{LEADER}`, `{NAME}`, `{ITEM}`, `{SPELL}`,
  `{CLASS}` and `{#}` write a name, an item, a spell, a class or a number in ASCII
  [`DIALOGUE_STRING_TO_PRINT`, `$FFB6F0`]; `{NAME;x}` and `{COLOR;x}` take the next symbol.
  `FE` ends the string.
- **The next symbol** [`GetNextTextSymbol`, `$00634E`] is the next one decoded, or, while
  `$FFB77A` [`CURRENT_DIALOGUE_ASCII_BYTE_ADDRESS`] points into the ASCII a command wrote, that
  ASCII's next byte through `$00666E` [`table_AsciiToTextSymbolMap`].
- **The loop.** A character (below `EE`) that is the string's first [`DIALOGUE_REGULAR_TILE_TOGGLE`,
  `$FFB6D8`, cleared at the start, set by `{DICT}`] starts a new line when the pen is not at the
  line's start; `ApplyAutomaticNewline` (`$006308`) breaks the line when the pen is past 204;
  `SymbolsToGraphics` (`$006B70`) draws the character; `HandleDialogueTypewriting` sends the
  pen's line to VRAM [`HandleBlinkingDialogueCursor`, `$00697A`], speaks (not for the space) and
  waits (not for `7C` and `7D`).
- **The font.** 80 characters from symbol `01`, 32 bytes each [`p_font_VariableWidth`, `$02800C`,
  to `$029002`]: a word whose low nibble is the width less one (`0`: no width), then 15 rows of
  16 bits, 12 used, the leftmost pixel in the top bit. A character is drawn in the ink's colour
  [`USE_REGULAR_DIALOGUE_FONT`, `$FFB6D6`: 1, or the colour `{COLOR;x}` sets, when it is drawn
  twice, a pixel apart], and only its ink's pixels are written.
- **The window.** Its lines are tiles of 4-bit pixels in work RAM from `$FF6802`, 27 tiles a
  line (216 pixels); the pen [`DIALOGUE_TYPEWRITING_CURRENT_X`, `$FFB6D4`] starts a line at 2, and
  `$006BDE` finds its place in the tiles. The window scrolls a line when it is full: after two
  lines, or three in the scenes with the black bar (the witch's).
- **The arrow.** While `{W1}` or `{W2}` waits, `sub_64A8` blinks the arrow's sprite at X `$168`,
  the window's bottom right, where an English line ends.
- **The checksum.** The header's word at `$18E` is the sum of the ROM's big-endian words from
  `$200`. The game does not check it; the overlay sets it all the same.

## Right-to-left text

The overlay's hooks (`rom/sf2_arabic_hooks.s`, 580 bytes of 68000 code) and its data live in the
free bytes at the end of section 06, the one that holds the text: the disassembly's layout counts
6681, `$0425E7` to `$043FFF`, all `FF` in the ROM.

- **Arabic strings.** Where `DisplayText` looks a string up, one whose number is in the overlay's
  list is read from its Arabic instead, stored as the game stores a string (a length byte, then
  its symbols) but not compressed. The hooks tell an Arabic string by its code's address, which
  lies in the room; the string's end clears it. The English stays where it was, as it was.
- **Glyphs.** In an Arabic string every symbol below the commands is a glyph of the Arabic font
  (234 codes, `02`-`ED` but `7C` and `7D`, which the game draws without a pause); the commands
  keep their meaning. The space keeps `01`, which the game types without a voice.
- **Mirrored draw.** Each glyph is drawn at `216 - pen - width` while the pen moves on as the
  engine's does, so a line starts at the window's right. The engine's line breaks and new lines
  work as they are: an Arabic line ends where an English one would.
- **Names and numbers.** What a command writes in ASCII is drawn whole, left to right, in the
  English font, as a block that ends at the mirror of the pen. It starts a new line as the
  English's first letter would (the string's first character not at the line's start), and a
  new one when it would pass the line's end; then its line goes to VRAM. So `{NAME;0}` in an
  Arabic line shows the name the player gave, in Latin letters, the right way round.
- **The arrow.** In an Arabic string the arrow blinks at X `$98`, the window's bottom left,
  where an Arabic line ends.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. The glyphs come from a cell of 16 pixels by 15
rows, the letters' baseline on row 11 (the English capitals' last row), at 10 pixels: the largest
size at which every form of the repertoire and every digit fits the cell (from 14 down; at 11 the
tails of meem and yeh, isolated and final, pass its last row). Coverage from 140 of 255 is ink,
and a dot between 60 and 140 keeps its strongest pixel. The merged dots of two- and three-dot
letters are drawn apart (`separated_dots`); hamza above alef is drawn by hand over the font's alef
(`alef_with_mark`), and final and isolated yeh are raised a row (`raised_form`). `.`, `,`, `:`,
`!`, `-`, `…`, `،`, `؛` and `؟` are drawn by hand. The glyphs are one colour, as the game's
letters: a form that joins the glyph on its right runs on to its edge, any other keeps a free
column. The space is 5 pixels.

## Layout

The encoder lays each string out itself, a word at a time, as the engine breaks the English's: a
glyph starts by 204 and ends by 214, from 2 (212 pixels a line). `{N}` in the translation ends a
line where it stands, and the encoder writes `{N}` where the next word would not fit. A name
counts 70 pixels (seven letters, the widest 10 each), an item, a spell or a class 96, a number 40.
The glyphs of a line are stored in reading order: the first is drawn at the right.

## The overlay's room

| Address | Content |
|---------|---------|
| `$042600` | the hooks: `redirect_hook` at `+0`, `symbol_hook` at `+$32`, `draw_hook` at `+$8A`, `cursor_hook` at `+$18E` |
| `$042A00` | the list: 6 bytes a string (its number, its Arabic's address); `FFFF` ends it |
| `$042B00` | the Arabic font: 32 bytes a code, as the game's font |
| after the font | the Arabic strings, each a length byte and its symbols, each from an even address |

The room is `$042600` to `$043FFF`, `FF` in the ROM; the overlay checks it is.

| Site | Original | Arabic |
|------|----------|--------|
| `$006272`, in `DisplayText` | `MOVEM.W d0,-(sp)`; `LSR.W #6,d0` | `JMP redirect_hook` |
| `$00634E`, `GetNextTextSymbol` | `TST.L $FFB77A`; `BNE.W` | `JMP symbol_hook`; `NOP` |
| `$006B70`, `SymbolsToGraphics` | `MOVEM.W d0-d2,-(sp)`; `ANDI.W #$FF,d0` | `JMP draw_hook`; `NOP` |
| `$0064DA`, in `sub_64A8` | `MOVE.W #$168,6(a0)` | `JSR cursor_hook` |

Anchors checked before any change: the ROM (SHA-256); where an English string's lookup goes on,
and where a string is read once found; `ApplyAutomaticNewline`; both ways `GetNextTextSymbol`
goes on, and its ASCII table; `sub_64A8` about its site; `HandleBlinkingDialogueCursor`;
`SymbolsToGraphics` after its site and the pen's place in the tiles (`$006BDE`); the font's
pointer; the room, free; each translated string (its number and the SHA-256 of its bytes). The
build then sets the header's checksum and checks that nothing but the sites, the room and the
checksum changed.

## Translations

`rom/sf2_arabic_script.py` pins three strings of the witch who starts a new game. The Arabic is
in `translations/shining-force-2.json`, in the English's notation. The three were chosen to be
unlike:

| Entry | String | What it tries |
|-------|--------|---------------|
| `witch.greeting` | `D8`: the witch greets the player | the window cleared first, two lines, a wait |
| `witch.confused` | `D9`: the player looks confused | three English lines laid out again as two |
| `witch.nice_name` | `DF`: she repeats the name the player gave | the name, drawn left to right at the right of its line |

They use 39 glyphs (`02..28`) and the space, and 100 bytes of Arabic.

## Verification

With the reference font the build matches the reference patch (1922 bytes). In Genesis Plus GX
(`genesis_plus_gx_libretro`), from power-on with the patched ROM, a new game in the first slot and
the name `AAA`: the witch's greeting and her question in Arabic from the right, scrolling as the
English does, the arrow blinking at the window's bottom left; after the name, `AAA…` at the right
of the first line and her word on it under it. Her next English window, three lines on, and the
name screen are pixel for pixel the original ROM's at the same frame. The script, inputs only:

```text
# Core: genesis_plus_gx_libretro. From power-on: savestates do not keep the save RAM.
run 1200
tap START
run 180
tap START
run 240
shot greeting.png
# Her strings, the menu (the first option: a new game), the first slot.
tap A
run 180
tap A
run 180
tap A
run 180
tap A
run 180
tap A
run 180
tap A
run 120
tap A
run 120
tap A
run 240
# The name: three letters, then down, down and left to END.
tap A
run 20
tap A
run 20
tap A
run 20
tap DOWN
run 15
tap DOWN
run 15
tap LEFT
run 15
tap A
run 180
shot nice_name.png
```

The RetroPad's A is the Mega Drive's C.

## Limits

- Three strings are in Arabic; every other string, the menus and the rest of the game stay
  English.
- 234 glyph codes for all the Arabic; a string holds no Latin letters, and a name is the game's,
  in Latin letters.
- The room holds the font, 32 bytes a code, and the strings: 5376 bytes from `$042B00`. A larger
  translation needs more room than the section's free bytes.
- Coloured text (`{COLOR;x}`) is drawn in its colour, but once, not twice as the English's.
- An item, a spell or a class wider than 96 pixels may start a line of its own, which the
  encoder did not reckon with.
- The font is 10 pixels; no vowel marks, lam and alef stay two glyphs.
