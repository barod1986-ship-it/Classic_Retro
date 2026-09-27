# Gran Turismo Arabic Renderer v1

Target: *Gran Turismo* (USA, Rev 1, SCUS-94194), the second PlayStation target. No
decompilation exists; the facts below come from the disc and from the unpacked race
program's code, read in memory and on screen in Beetle PSX with the
[research tools](RESEARCH_TOOLS.md). The overlay patches the user's disc image and ships as
a BPS patch of its one track.

| Item | Value |
|------|-------|
| Redump | *Gran Turismo (USA) (Rev 1)*: a CUE sheet and one data track |
| Track | 693668304 bytes (294927 sectors of 2352 bytes, Mode 2): CRC32 `2B3845AA`, SHA-1 `5433c55806f7cd5ca2e42a6c39ff816d442ed6b6`, SHA-256 `e1ba7def96b7f213637fa82658b53c34a3a5f6c54df7d7e5ab9c3f53a2d41f03` |
| Boot | `SYSTEM.CNF` boots `SCUS_941.94`; `classic-retro detect` on the CUE names the game |
| Output | The track, the same size; the CUE sheet stays as it is. Shipped as BPS |

## Engine facts the overlay relies on

- **Files.** `GTMAIN.EXE` (LBA 202, 346112 bytes) is the race program, which the license
  tests run in; `GAMEFONT.DAT` (LBA 617, 23077 bytes) is the fonts' page; `MESSAGES.DAT`
  (LBA 629, 135168 bytes) holds the texts.
- **PSLZ.** GTMAIN.EXE is a PS-X EXE whose text is packed. Its entry point
  (`0x80063CB8`) is a stub with a header of seven words before it (`0x80063C9C`):
  `"PSLZ"`, the image's last byte (`0x800B3FFF`), its size (`0xA4000`), the stream's last
  byte (`0x80063C9A`), where the stub copies itself (`0x800B4000`), the stub's size and the
  image's entry point (`0x80010000`). The stub copies itself above the image and unpacks it
  in place, from the top down, reading the stream backwards; before each flags byte but the
  first and before each item it checks that it still reads below where it writes, and stops
  when it does not. Whatever lies below then is stored as it is (nothing, in GTMAIN). Read
  from its end the stream is GT-ZIP of the image read from its end
  ([`rebuild/pslz.py`](../src/classic_retro/rebuild/pslz.py)).
- **GT-ZIP.** A flags byte, from its lowest bit, for each group of eight items: a literal
  byte (0), or a match (1) of a length byte (length − 3, so 3 to 258) and a distance
  (distance − 1 in one byte below `0x80`, else `0x80 | high` then its low byte, up to
  `0x8000` back). `GAMEFONT.DAT` is a bare stream of the page's 32768 bytes
  ([`rebuild/gtzip.py`](../src/classic_retro/rebuild/gtzip.py)).
- **GT-ARC.** `"@(#)GT-ARC"` and two zero bytes, the kind (1: files stored; with `0x8000`:
  packed with GT-ZIP), the file count, then three words a file: offset, bytes stored, size.
  MESSAGES.DAT holds four kinds of text in six languages; its file 18 is the US English
  license briefings: 24 offsets of two bytes, then 24 texts, each padded to an even length,
  B-1 to B-8, then A, then International A. The file takes 8230 bytes of a room of 10240
  (five sectors, to file 19). The game loads it at `0x8019D00C`; the memory after it is
  unused.
- **A briefing.** Its paragraph count, then its title and its paragraphs as lists of words:
  a word count, then each word as its length (the ending zero included), its characters
  and the zero. The title is a list of one word, spaces and all. The US English uses ASCII
  only ([`engines/gran_turismo.py`](../src/classic_retro/engines/gran_turismo.py)).
- **The font page.** 256 x 256 pixels of 4 bits at VRAM (320, 0): fonts 0 to 2 use the low
  two bits of each pixel, font 3 the high two, and each font's palette reads only its own
  (fonts 0 to 2: 0 white, 1 and 3 clear, 2 black; font 2's 1 is grey). The palettes are the
  page's first 64 pixels of rows 0 to 3; rows 231 to 255 hold graphics the game draws over
  while it runs. At the briefing, VRAM holds the page exactly as the file does.
- **Fonts.** A font is a glyph table (8 bytes a code: page position, width, height, an
  unused byte, a row offset, the advance less one, the height again) and a kerning table
  (a pointer a code to a row of 256 four-bit amounts, one for each code that may follow).
  The routine that selects a font (`0x8006C770`) loads both with `lui`/`addiu` pairs:

  | Font | Glyphs | Kerning | Used for |
  |------|--------|---------|----------|
  | 0 | `0x800999DC` | `0x8009BA5C` | |
  | 1 | `0x8009BE5C` | `0x800A195C` | a briefing's paragraphs |
  | 2 | `0x800A1D5C` | `0x800A725C` | a briefing's title |

  The space's row (code `20`) is empty. Codes `86` to `FF` of fonts 1 and 2 hold Latin-1
  letters and signs that the US game never draws; `80`, `81` and `A0` are blanks, `84` and
  `85` signs.
- **Drawing a word.** `0x8006C9F0` (ordering table, x, y, glyphs) draws a sprite a glyph
  (`0x800723F8`) at the pen and row y + row offset − 4, unless its height is 0; then the pen
  moves by 1 + advance − the kerning amount between the glyph and the next.
  `0x8006C8E0` (font, glyphs) measures a word the same way.
- **The briefing's layout** (`0x800290F8`). The title goes in font 2, centred:
  x = (288 − width) / 2 + 16, at y + 2; then y moves down 24. The paragraphs go in font 1
  from x 16, the first line of each indented 8 pixels, the words 4 pixels apart; a line ends
  before the word that would make it wider than 288, and every line but a paragraph's last
  spreads the room left over its gaps. Each line moves y down 12. The caller (`0x800293F8`)
  starts at y 64 and clips to rows 64 to 195. The count it would scroll by is the
  paragraph count, never past the box, so the text never scrolls; English briefings take up
  to 8 lines.

## Right-to-left text

The Arabic takes codes `86` to `FF` but `A0` of fonts 1 and 2: 121 glyphs, whose entries
the overlay rewrites and whose kerning pointers it points at the space's empty row, so an
Arabic word's width is the sum of its glyphs'. Every glyph of an Arabic word is one of
these: the digits and punctuation too, so no kerning between the game's glyphs and the
Arabic ones arises, and the lines are measured without the disc.

- **Mirrored words.** A hook (`rom/gran_turismo_arabic_hooks.s`) replaces the layout's word
  loop. The game still measures, breaks, indents and justifies every line from the left; a
  word whose first glyph is `86` or above is drawn at the mirror of its place,
  320 − x − width, so a paragraph reads from the right, its first line is indented on the
  right and its last line ends on the right. A word keeps its glyphs in visual order (the
  game draws them left to right); the words keep the reading order.
- **The title** is one word in visual order, which the game centres.
- **Rows.** The Arabic title's glyphs take a cell of 26 rows from the box's top row, so the
  hook draws Arabic words 6 rows lower, and a call at the line's end (`line_step`) puts an
  Arabic line 15 rows after the last, not 12: seven lines fit under the title, the last
  ending on row 195.
- **English stays English.** A word whose first glyph is below `86` is drawn where the game
  puts it and its lines stay 12 rows apart, so the 21 untranslated briefings look as they
  did.

## Glyphs and the font page

The reference font is Noto Kufi Arabic SemiBold. The body's glyphs come from a cell of 16
rows (baseline on row 11) at 10 pixels, the title's from a cell of 26 rows (baseline on row
19) at 18: for each font the largest size, from 13 and 18 down, at which every form of the
repertoire and the digits fits with its outline. Coverage from 128 of 255 is ink, and a
dot that stays between 60 and 128 keeps its strongest pixel. Every glyph is white with a
black outline a pixel wide all round but on a side where it joins its neighbour, where its
stroke runs on to the edge; it is stored cropped to its rows, its row offset keeping it in
place.

At 10 pixels the two dots of teh, qaf, teh marbuta and yeh run into one bar or lose one,
and so do the three of theh and sheen: they are redrawn as single pixels a pixel apart,
centred where the font drew them, a free row from the letter
(`font.glyph_raster.separated_dots`). At 18 the two dots under final and isolated yeh
reach below the title's cell: they move up and keep a free row from the letter
(`raised_marks`). `.`, `,`, `:`, `!` and `-`, which the reference font lacks, are drawn by
hand, and in the body so are `،` and `؛`, which it draws too small to tell from a full
stop; the digits, `؟` and the title's `،` come from the font. The title's space is a blank
glyph of 6 pixels.

The glyphs go first over the glyphs of the codes they take (the Latin-1 letters of fonts 1
and 2): those pixels held glyphs, so the packed page keeps its size. Then into blank
pixels: none of fonts 0 to 2 uses them, off the palettes and rows 231 to 255, blank in the
low plane (13208 pixels, rows 183 to 230 whole). Font 3's plane is never touched. The three
briefings' 110 glyphs take 9777 pixels, all over the Latin-1 glyphs.

## Packing

A packed file keeps its size and its bytes but around the changes, so the patch carries
the changes and not the files (`gtzip.repack_items`): the original's items that still
make the same bytes stay; a match that copies changed bytes takes another distance of the
same width where the same bytes lie; the groups of eight items around the changes are
parsed again, cheapest first, into the same bytes and whole groups. When they come out
longer they take their neighbours in, twice as many each time: the game's streams are not
the cheapest, so parsing them again saves room. When shorter, matches give bytes to
literals, eight at a time, and near distances are written in two bytes. GTMAIN keeps the
stub's in-place check: every check before the stream's end has saved less than the whole.
When the page does not fit its stream it is packed afresh, if that fits the file.

| File | Sectors | Changed |
|------|---------|---------|
| GTMAIN.EXE | 169 | 15: the hook, the glyph entries and kerning pointers |
| GAMEFONT.DAT | 12 | 12: the glyphs are spread over the page |
| MESSAGES.DAT | 66 | 6: the license file (8004 bytes) and its entry |

Every file keeps its sectors and size, so no directory record changes; each sector written
gets its EDC and ECC, with its subheader kept. The build reads everything back: only these
sectors changed, each a sound Form 1 sector, the files read back, and GTMAIN unpacks in one
buffer, as the stub does (`pslz.unpack_in_place`), to the patched program.

## Hook

The hook (R3000A MIPS I, 224 bytes) is linked at `0x80029290`, in place of the word loop
(`0x80029290` to `0x80029370`). Its first word is the delay slot the loop starts in, as the
game has it; it keeps the game's justification without the compiler's checks of a divisor
that is never 0. It calls the measuring and drawing routines only; the build checks that
the stored code jumps to exactly those two (`cpu.mips.jump_targets`).

| Site | Original | Arabic |
|------|----------|--------|
| `0x80029290` to `0x80029370` | the word loop | `word`: an Arabic word mirrored and 6 rows lower |
| `0x80029384` | `nop` | `jal line_step`: 15 rows after an Arabic line |
| Glyph entries of fonts 1 and 2 | Latin-1 glyphs | the Arabic glyphs |
| Kerning pointers of fonts 1 and 2 | Latin-1 rows | the space's empty row |

Anchors checked before any change: the word loop (SHA-256); the branch into it
(`0x8002928C`); the loop's end, the next word and the line's step
(`0x80029370` to `0x8002938C`); the font tables' addresses in the font select routine; the
space's empty kerning rows; the three files (SHA-256, and every sector's EDC and ECC); the
unpacked program and page (SHA-256); every translated briefing (SHA-256).

## Translations

`rom/gran_turismo_arabic_script.py` pins the three briefings by their place among the 24
and the SHA-256 of their bytes. The Arabic is in `translations/gran-turismo.json`, in the
engine's notation: the title on the first line, then a line a paragraph. The three were
chosen to be unlike: B-1 (a number with a thousands comma), B-3 (the longest body, six
lines, an Arabic comma) and B-8 (the widest title, 250 pixels, and a number joined to a
letter, «و22»). They use 82 codes (`86..D8`); the license file shrinks from 8230 to 8004
bytes.

## Verification

With the reference font the build matches the reference patch (45940 bytes). In Beetle
PSX (`mednafen_psx_libretro`, a US BIOS in the system directory), from power-on with the
patched track and no memory card: B-1 and B-3 in Arabic, from the right, their dots apart,
their numbers the right way round; B-2 in English exactly as before. B-8 opens only once
B-1 to B-7 are passed; a research build that puts its text in B-2's place shows it in the
game the same way. The script, inputs only:

```text
# Core: mednafen_psx_libretro, --system-dir holding a US BIOS.
run 7200
# The title: Simulation Mode.
tap START
run 480
tap DOWN
run 60
tap B
run 720
# The city map: from Home down to Go Race, right to License.
tap DOWN
run 90
tap RIGHT
run 90
tap B
run 600
# The License Center: B-Class. The pointer starts on the fifth test.
tap LEFT
run 90
tap B
run 480
save blist.state
# B-1: up to the first test.
tap UP
run 60
tap UP
run 60
tap UP
run 60
tap UP
run 60
tap B
run 1200
shot b1.png
# B-3: two up.
load blist.state
tap UP
run 60
tap UP
run 60
tap B
run 1200
shot b3.png
```

The RetroPad's B is the PlayStation's cross. Beetle PSX gives the main RAM as
`system_ram` and VRAM only in a savestate's `GPURAM[0][0]` chunk.

## Limits

- Three of the 24 briefings are in Arabic; the other 21, the menus and the rest of the
  game stay English.
- Arabic text holds no Latin letters, and a number stays one word: the game places the
  words, and the hook mirrors each.
- 121 glyph codes for all the briefings (the three use 82); the Arabic glyphs replace the
  Latin-1 ones of fonts 1 and 2, which the US game never draws.
- The body is 10 pixels and the title 18; no vowel marks, lam and alef stay two glyphs.
